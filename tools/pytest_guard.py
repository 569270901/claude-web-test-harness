# -*- coding: utf-8 -*-
"""pytest 插件：撞墙止损 + 可选的跑批前预检。

为什么要有它：一个被十几条用例共用的 helper 里，某个下拉选项的文案大小写变了，十几条用例
陪着一起挂，整批跑了一个小时才拿到结果。撞墙本身不可怕，可怕的是撞墙之后还继续跑几十条
注定失败的用例——既浪费时间，也把真正的信号淹没在噪音里。

止损规则（任一命中就停掉本次跑批，剩余用例不再执行）：
1. **同一个定位**在 N 条用例里失败（默认 3）——疑似页面漂移，报一次就够，不用陪跑
2. **连续** M 条用例失败 / 报错（默认 5，不管原因）——疑似环境整体出问题（登录态、外部依赖、
   测试数据），继续跑只是在制造噪音

不计入的情况：xfail（已知缺陷按预期失败）、XPASS(strict)（疑似缺陷已修复，是好消息不是撞墙）、
跳过的用例。用例通过或按预期 xfail 会把"连续失败"计数清零。

"同一个定位"的判断：从 Playwright 报错的 `waiting for locator(...)` 那一行提取定位，把 6 位以上
的数字（时间戳、自增 id）归一化成 <N>，这样不同用例造的不同数据不会被当成不同的墙。

**默认关闭**（不改变现有用例的运行结果），靠命令行或 ini 开启：
    python -m pytest tests/ --guard                          # 开启，阈值用默认 3 / 5
    python -m pytest tests/ --guard --guard-same=2 --guard-consecutive=4
    python -m pytest tests/ --guard --preflight "python tools/my_preflight.py"
    # 想常开：pytest.ini 里写 `guard = true`（以及 guard_same / guard_consecutive）
    python -m pytest tests/ --no-guard                       # ini 常开时临时关掉

`--preflight <命令>`：跑用例前先执行一条命令（例如按 page_map 提前探路的脚本），退出码非 0
就整批不跑。命令由接入方自己提供，本插件不内置任何站点逻辑。

止损记录写入 `artifacts/_runs/guard_last.json`（下一步做 selector 自愈时，输入就是里面的
repeated_locators）。
"""
import json
import re
import shlex
import subprocess
import time
from collections import defaultdict
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "artifacts" / "_runs" / "guard_last.json"

_WAIT_RE = re.compile(r"waiting for (.+)")
_NUM_RE = re.compile(r"\d{6,}")
_DEFAULT_SAME = 3
_DEFAULT_CONSECUTIVE = 5


def locator_signature(longrepr: str) -> str | None:
    """从失败堆栈里提取"卡在哪个定位上"，提不出来返回 None（说明不是定位类失败）。"""
    m = _WAIT_RE.search(longrepr or "")
    if not m:
        return None
    sig = re.sub(r"\s+", " ", m.group(1).strip())
    # wait_for 的报错末尾带 "to be visible"，click 的不带——同一个定位不该算成两堵墙
    sig = re.sub(r"\s+to be (visible|hidden|attached|detached|enabled|editable|checked)\s*$", "", sig)
    sig = _NUM_RE.sub("<N>", sig)
    return sig[:300]


def _ini_bool(config, name: str) -> bool:
    return str(config.getini(name)).strip().lower() in ("1", "true", "yes", "on")


def _ini_int(config, name: str, default: int) -> int:
    try:
        return int(str(config.getini(name)).strip())
    except (TypeError, ValueError):
        return default


class _Guard:
    def __init__(self, config):
        if config.getoption("--no-guard"):
            self.enabled = False
        else:
            self.enabled = bool(config.getoption("--guard")) or _ini_bool(config, "guard")
        same = config.getoption("--guard-same")
        cons = config.getoption("--guard-consecutive")
        self.same = same if same is not None else _ini_int(config, "guard_same", _DEFAULT_SAME)
        self.consecutive_limit = (cons if cons is not None
                                  else _ini_int(config, "guard_consecutive", _DEFAULT_CONSECUTIVE))
        self.session = None
        self.hits: dict[str, list[str]] = defaultdict(list)
        self.consecutive: list[str] = []
        self.executed: set[str] = set()
        self.stop_reason: str | None = None
        self.stop_kind: str | None = None
        self.started = time.time()

    def _stop(self, kind: str, reason: str):
        if self.stop_reason:
            return
        self.stop_kind, self.stop_reason = kind, reason
        if self.session is not None:
            self.session.shouldstop = f"[撞墙止损] {reason}"

    def on_report(self, report):
        if report.when not in ("setup", "call"):
            return
        if report.when == "call" or report.failed:
            self.executed.add(report.nodeid)
        longrepr = str(report.longrepr or "")
        wasxfail = getattr(report, "wasxfail", None)
        # 通过 / 按预期 xfail = 环境和页面在正常工作，连续失败清零
        if report.when == "call" and (report.passed or (wasxfail is not None and report.skipped)):
            self.consecutive.clear()
            return
        if not report.failed or "XPASS(strict)" in longrepr:
            return
        self.consecutive.append(report.nodeid)
        sig = locator_signature(longrepr)
        if sig:
            if report.nodeid not in self.hits[sig]:
                self.hits[sig].append(report.nodeid)
            if len(self.hits[sig]) >= self.same:
                self._stop("same_locator",
                           f"同一个定位在 {len(self.hits[sig])} 条用例里失败，疑似页面漂移：{sig}")
                return
        if len(self.consecutive) >= self.consecutive_limit:
            self._stop("consecutive",
                       f"连续 {len(self.consecutive)} 条用例失败/报错，疑似环境整体出问题"
                       f"（登录态 / 外部依赖 / 测试数据），先排查环境再跑")

    def dump(self, total: int) -> dict:
        data = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "seconds": round(time.time() - self.started),
            "stopped": bool(self.stop_reason),
            "stop_kind": self.stop_kind,
            "stop_reason": self.stop_reason,
            "thresholds": {"same": self.same, "consecutive": self.consecutive_limit},
            "total_selected": total,
            "executed": len(self.executed),
            "not_run": max(total - len(self.executed), 0),
            # 出现 ≥2 次的定位都记下来：没到止损阈值也值得看
            "repeated_locators": {s: n for s, n in self.hits.items() if len(n) >= 2},
            "consecutive_failures": list(self.consecutive),
        }
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return data


def pytest_addoption(parser):
    g = parser.getgroup("guard", "撞墙止损 / 跑批前预检（tools/pytest_guard.py）")
    g.addoption("--guard", action="store_true", default=False,
                help="开启撞墙止损（默认关闭）")
    g.addoption("--no-guard", action="store_true", default=False,
                help="强制关闭撞墙止损（覆盖 ini 里的 guard = true）")
    g.addoption("--guard-same", type=int, default=None,
                help=f"同一个定位失败几条用例就停批，默认 {_DEFAULT_SAME}（或 ini guard_same）")
    g.addoption("--guard-consecutive", type=int, default=None,
                help=f"连续几条用例失败/报错就停批，默认 {_DEFAULT_CONSECUTIVE}（或 ini guard_consecutive）")
    g.addoption("--preflight", default=None, metavar="CMD",
                help="跑用例前先执行这条命令，退出码非 0 就整批不跑")
    parser.addini("guard", "是否默认开启撞墙止损（true/false）", default="false")
    parser.addini("guard_same", f"同一定位失败几条就停批（默认 {_DEFAULT_SAME}）", default=str(_DEFAULT_SAME))
    parser.addini("guard_consecutive", f"连续失败几条就停批（默认 {_DEFAULT_CONSECUTIVE}）",
                  default=str(_DEFAULT_CONSECUTIVE))


_STATE: dict = {}


def pytest_configure(config):
    config._guard = _Guard(config)
    _STATE["guard"] = config._guard


def pytest_sessionstart(session):
    guard = session.config._guard
    guard.session = session
    cmd = session.config.getoption("--preflight")
    if not cmd or session.config.option.collectonly:
        return
    print(f"\n[preflight] 跑批前预检：{cmd}", flush=True)
    proc = subprocess.run(shlex.split(cmd), cwd=ROOT, capture_output=True, text=True)
    tail = "\n".join((proc.stdout or "").strip().splitlines()[-20:])
    if tail:
        print(tail, flush=True)
    if proc.returncode != 0:
        err_tail = "\n".join((proc.stderr or "").strip().splitlines()[-10:])
        if err_tail:
            print(err_tail, flush=True)
        pytest.exit(f"[preflight] 预检退出码 {proc.returncode}，本次跑批不执行。"
                    "修好或确认是误报后再跑；想跳过预检就去掉 --preflight。", returncode=3)
    print("[preflight] 通过，开始跑用例", flush=True)


def pytest_runtest_logreport(report):
    # 用 logreport 而不是 makereport：这里拿到的是 xfail / rerunfailures 处理完的最终结果
    # （rerun 的中间尝试 outcome='rerun'，report.failed 为 False，不会被重复计数）
    guard = _STATE.get("guard")
    if guard is not None and guard.enabled:
        guard.on_report(report)


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    guard = config._guard
    if not guard.enabled or config.option.collectonly:
        return  # collect-only 不落盘，免得覆盖上一次真实跑批的止损记录
    total = len(getattr(guard.session, "items", None) or [])
    data = guard.dump(total)
    if not data["stopped"] and not data["repeated_locators"]:
        return
    tr = terminalreporter
    tr.write_sep("=", "撞墙止损")
    if data["stopped"]:
        tr.write_line(f"⛔ {data['stop_reason']}")
        tr.write_line(f"   已执行 {data['executed']} 条，未执行 {data['not_run']} 条"
                      f"（修好后重跑即可，不用再陪跑这 {data['not_run']} 条）")
    for sig, nodes in data["repeated_locators"].items():
        tr.write_line(f"△ 定位反复失败 {len(nodes)} 次：{sig}")
        for n in nodes[:5]:
            tr.write_line(f"     - {n}")
    tr.write_line(f"   记录 → {OUT.relative_to(ROOT)}")
