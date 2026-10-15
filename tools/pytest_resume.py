# -*- coding: utf-8 -*-
"""pytest 插件：断点续跑。`--batch <名字>` 让一批用例每跑完一条就落盘一次，中断后重跑同一条命令只补没跑完的。

为什么：长回归经常跑不完——执行环境有单次时长上限（某次长回归跑到约 30 分钟被环境直接杀掉），
笔记本合盖 / 断电睡眠也会让整批中断。没有断点记录时只能整批从头再跑，越长的回归越难跑完。

用法（根 conftest.py 已通过 `pytest_plugins` 注册；不带 --batch 时本插件什么都不做）：
    python -m pytest tests/ --batch nightly -v
    # 中断后原样再跑一次 → 已完成的自动略过，只跑剩下的
    python -m pytest tests/ --batch nightly --batch-fresh     # 清掉这批记录、从头跑
    # 配合外层分块：每块控制在环境时长上限以内，循环调用同一条命令直到全部完成

规则：
- 每条用例**最终结果**（装了 pytest-rerunfailures 时取重跑后的那次）跑完立刻追加写入
  artifacts/_runs/batches/<名字>.jsonl，并 fsync，断电也不丢
- 续跑时略过最近一次结果为 passed / xfailed / skipped 的用例；failed / error / 没记录的照跑
- 一条用例执行期间机器睡过（墙钟时长比单调时钟多出 --batch-sleep-gap 秒以上，默认 30；
  macOS 的 time.monotonic 在睡眠时不走），记为 slept=True，**无论结果如何下次都重跑**——
  睡眠期间的结果多半受断网 / 会话过期影响，不可信
- 已知局限：用例之间有顺序依赖时（B 复用 A 产出的数据），A 已通过被略过，B 会失败；
  这类成对用例需要一起重跑（`--batch-fresh` 或删掉对应记录行）
"""
import json
import os
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
BATCH_DIR = ROOT / "artifacts" / "_runs" / "batches"
_DONE = {"passed", "xfailed", "skipped"}


def pytest_addoption(parser):
    g = parser.getgroup("resume", "断点续跑（tools/pytest_resume.py）")
    g.addoption("--batch", default=None, help="批次名：每条用例跑完即落盘，重跑同名批次只补未完成的")
    g.addoption("--batch-fresh", action="store_true", default=False, help="清空该批次已有记录，从头跑")
    g.addoption("--batch-sleep-gap", type=float, default=30.0,
                help="墙钟比单调时钟多出几秒判为中途睡眠（该用例下次必重跑），默认 30")


def _batch_file(config) -> Path | None:
    name = config.getoption("--batch")
    if not name:
        return None
    safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in name)
    return BATCH_DIR / f"{safe}.jsonl"


def _load(path: Path) -> dict:
    """nodeid → 最后一条记录。坏行（断电时写了一半）直接跳过。"""
    last = {}
    if not path.exists():
        return last
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line)
            last[rec["nodeid"]] = rec
        except (ValueError, KeyError, TypeError):
            continue
    return last


_STATE: dict = {}


def pytest_configure(config):
    path = _batch_file(config)
    config._resume = None
    _STATE.pop("st", None)
    if not path:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    if config.getoption("--batch-fresh") and path.exists():
        path.unlink()
    config._resume = {"path": path, "prev": _load(path), "skipped": 0, "attempt": {},
                      "gap": config.getoption("--batch-sleep-gap")}
    _STATE["st"] = config._resume


def pytest_collection_modifyitems(session, config, items):
    st = getattr(config, "_resume", None)
    if not st or not st["prev"]:
        return
    keep, done = [], []
    for it in items:
        rec = st["prev"].get(it.nodeid)
        if rec and rec.get("outcome") in _DONE and not rec.get("slept"):
            done.append(it)
        else:
            keep.append(it)
    if done:
        config.hook.pytest_deselected(items=done)
        items[:] = keep
        st["skipped"] = len(done)


def pytest_runtest_logreport(report):
    st = _STATE.get("st")
    if not st:
        return
    a = st["attempt"].setdefault(report.nodeid, {"outcome": None, "when": None})
    if report.outcome == "rerun":
        a.update(outcome=None, when=None)  # 被 rerunfailures 重跑，作废这次，等最终那次
        return
    longrepr = str(getattr(report, "longrepr", "") or "")
    if report.when == "call":
        if hasattr(report, "wasxfail"):
            a.update(outcome="xfailed" if report.skipped else "xpassed", when="call")
        elif "XPASS(strict)" in longrepr:
            # strict 意外通过：pytest 判 failed，续跑时照跑（需要人复核，不算完成）
            a.update(outcome="xpassed_strict", when="call")
        else:
            a.update(outcome=report.outcome, when="call")
    elif report.failed:  # setup / teardown 出错
        if a["outcome"] in (None, "passed"):
            a.update(outcome="error", when=report.when)
    elif report.skipped and report.when == "setup":
        if hasattr(report, "wasxfail"):  # xfail(run=False) 在 setup 阶段就判定
            a.update(outcome="xfailed", when="setup")
        else:
            a.update(outcome="skipped", when="setup")


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_protocol(item, nextitem):
    st = getattr(item.config, "_resume", None)
    if not st:
        yield
        return
    w0, m0 = time.time(), time.monotonic()
    yield
    wall, mono = time.time() - w0, time.monotonic() - m0
    a = st["attempt"].pop(item.nodeid, {}) or {}
    rec = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "nodeid": item.nodeid,
        "outcome": a.get("outcome") or "unknown",
        "when": a.get("when"),
        "duration": round(mono, 1),
        "slept": (wall - mono) > st["gap"],
    }
    with open(st["path"], "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    st = getattr(config, "_resume", None)
    if not st:
        return
    last = _load(st["path"])
    done = sum(1 for r in last.values() if r.get("outcome") in _DONE and not r.get("slept"))
    slept = [r["nodeid"] for r in last.values() if r.get("slept")]
    bad = [r["nodeid"] for r in last.values()
           if r.get("outcome") not in _DONE and not r.get("slept")]
    tr = terminalreporter
    tr.section("断点续跑")
    tr.write_line(f"批次记录：{st['path'].relative_to(ROOT)}（本次略过已完成 {st['skipped']} 条）")
    tr.write_line(f"累计已完成 {done} 条；未完成 {len(bad)} 条；中途睡眠需重跑 {len(slept)} 条")
    for n in slept:
        tr.write_line(f"  [睡眠] {n}")
    for n in bad:
        tr.write_line(f"  [未完成] {n}")
