# -*- coding: utf-8 -*-
"""pytest 插件：把每条测试的执行结果写进用例台账，供 case_console / qa_console 展示。

**非侵入**：测试的 docstring 里只要写了 `TC-SEARCH-012` 这类用例 ID，插件就自动提取，
不需要改任何存量测试。想显式绑定时用 `@pytest.mark.case("TC-HOME-005")`（优先级更高）。

启用（不改全局配置）：
    python -m pytest -p tools.pytest_case_ledger tests/... -v

想常开就把 `-p tools.pytest_case_ledger` 加进 pytest.ini 的 addopts。

落盘：`artifacts/_runs/auto_runs.jsonl`（**只增不改**，一行一条结果）
"""
import json
import os
import re
import time
from pathlib import Path

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


def pytest_runtest_makereport(item, call):
    """只在 call 阶段（真正执行）以及 setup 失败时记录，避免一条测试写三行。"""
    if call.when not in ("setup", "call"):
        return
    if call.when == "setup" and call.excinfo is None:
        return

    ids = _case_ids(item)
    if call.excinfo is None:
        status = "passed"
    elif call.excinfo.typename == "Skipped":
        status = "skipped"
    elif call.when == "setup":
        status = "error"
    else:
        status = "failed"

    err = None
    if call.excinfo is not None and status != "skipped":
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
    try:
        n = sum(1 for _ in LEDGER.open(encoding="utf-8")) if LEDGER.exists() else 0
    except Exception:
        return
    terminalreporter.write_sep("-", f"用例台账已记录，累计 {n} 条 → {LEDGER.relative_to(ROOT)}")
