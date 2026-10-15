# -*- coding: utf-8 -*-
"""pytest 插件：把每条测试的执行结果写进用例台账，供 case_console / qa_console 展示。

**非侵入**：测试的 docstring 里只要写了 `TC-SEARCH-012` 这类用例 ID，插件就自动提取，
不需要改任何存量测试。想显式绑定时用 `@pytest.mark.case("TC-HOME-005")`（优先级更高）。

启用：根 conftest.py 的 `pytest_plugins` 已默认注册，直接跑 pytest 即可。
（不放 pytest.ini 的 addopts：调试常用 `--override-ini="addopts="` 会把 addopts 整个清空，
插件跟着失效、台账悄悄漏记。命令行再传 `-p tools.pytest_case_ledger` 也不会重复注册。）

台账 status 取值：passed / failed / error / skipped / xfailed（按预期失败，已知缺陷）/
xpassed（非 strict 意外通过）/ xpassed_strict（strict 意外通过，pytest 判 failed，疑似缺陷已修复）。

落盘：`artifacts/_runs/auto_runs.jsonl`（**只增不改**，一行一条结果）
"""
import json
import os
import re
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
LEDGER = ROOT / "artifacts" / "_runs" / "auto_runs.jsonl"
CASE_RE = re.compile(r"\bTC-[A-Z]{2,6}-[A-Z]?\d{2,4}\b")


def pytest_configure(config):
    config.addinivalue_line("markers", "case(id): 绑定到 cases.md 的用例 ID，如 case('TC-HOME-005')")
    LEDGER.parent.mkdir(parents=True, exist_ok=True)


def _case_ids(item) -> list[str]:
    """用例 ID 来源优先级：marker > docstring。"""
    ids = []
    for m in item.iter_markers(name="case"):
        ids += [str(a) for a in m.args]
    if ids:
        return ids
    doc = (getattr(item, "function", None).__doc__ or "") if hasattr(item, "function") else ""
    return CASE_RE.findall(doc)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """只在 call 阶段（真正执行）以及 setup 失败时记录，避免一条测试写三行。

    **必须是 hookwrapper**：普通 hook 只能看到 `call.excinfo`（原始异常），完全不知道
    `xfail` 标记的存在——一条 `@pytest.mark.xfail(strict=True)` 的用例按预期失败时，
    `call.excinfo` 依然非空，会被错记成 `failed`，执行台就把"已确认的产品缺陷、预期失败"
    显示得跟"新炸的故障"一模一样。hookwrapper 能拿到 pytest 自带 xfail 插件处理完之后的
    最终 `report`（`report.wasxfail` 才是权威判断依据）。
    """
    outcome = yield
    report = outcome.get_result()

    if report.when not in ("setup", "call"):
        return
    if report.when == "setup" and report.outcome != "failed":
        return

    ids = _case_ids(item)
    wasxfail = getattr(report, "wasxfail", None)
    # strict=True 下"意外通过"这条路径，pytest 的 xfail 插件（_pytest/skipping.py）**不会**设置
    # report.wasxfail——只有真正 xfail 命中和非 strict 的意外通过才会设。strict-XPASS 唯一的信号
    # 是 report.longrepr 里的 "[XPASS(strict)]" 前缀；漏掉这条分支会把"疑似缺陷已修复"误记成
    # 普通 failed，跟真故障混在一起。
    xpass_strict = "XPASS(strict)" in str(getattr(report, "longrepr", "") or "")
    if wasxfail is not None:
        if report.outcome == "skipped":
            status = "xfailed"          # 预期失败，符合 xfail 声明——不是故障
        else:
            status = "xpassed"          # strict=False 下意外通过
    elif xpass_strict:
        status = "xpassed_strict"       # strict=True 下意外通过，pytest 判为 failed：已知缺陷可能已修复，待复核
    elif report.outcome == "passed":
        status = "passed"
    elif report.outcome == "skipped":
        status = "skipped"
    elif report.when == "setup":
        status = "error"
    else:
        status = "failed"

    err = None
    if wasxfail:
        err = str(wasxfail)[:600]
    elif xpass_strict:
        err = str(getattr(report, "longrepr", ""))[:600]
    elif call.excinfo is not None and status != "skipped":
        err = f"{call.excinfo.typename}: {call.excinfo.value}"
        err = re.sub(r"\s+", " ", err)[:600]

    # 失败取证：失败时落盘的 DOM / 截图约定放在 data/debug/（见 CLAUDE.md「项目约定」），
    # 取最近 5 分钟内改动的文件挂到这条记录上
    art = []
    dbg = ROOT / "data" / "debug"
    if status in ("failed", "error") and dbg.exists():
        now = time.time()
        art = sorted(
            (str(p.relative_to(ROOT)) for p in dbg.iterdir()
             if p.is_file() and now - p.stat().st_mtime < 300),
            key=lambda x: x, reverse=True)[:6]

    rec = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "case_ids": ids,
        "nodeid": item.nodeid,
        "status": status,
        "phase": call.when,
        "duration": round(call.stop - call.start, 2),
        "error": err,
        "artifacts": art,
        "markers": sorted({m.name for m in item.iter_markers()} - {"case"}),
        "run": os.environ.get("CASE_RUN_LABEL", ""),
    }
    with LEDGER.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    if config.option.collectonly:
        return
    try:
        n = sum(1 for _ in LEDGER.open(encoding="utf-8")) if LEDGER.exists() else 0
    except Exception:
        return
    terminalreporter.write_sep("-", f"用例台账已记录，累计 {n} 条 → {LEDGER.relative_to(ROOT)}")
