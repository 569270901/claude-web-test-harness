# -*- coding: utf-8 -*-
"""pytest 插件：跑批收尾时释放被 Chrome 孤儿进程占住的 driver stderr，避免 Browser.close() 白等十几分钟。

背景：用正式版 Chrome 通道跑（`--browser-channel=chrome`，常见于自带 Chromium 起不来的机器）时，
Chrome 会派生崩溃上报进程（chrome_crashpad_handler），运行一段时间后还会拉起自动更新进程。它们脱离父进程
（ppid=1）后**继承了 Chrome 的 stderr**——在 macOS 上这是一根连回 Playwright node driver 的 unix socket。
driver 关浏览器时要等 stderr EOF 才算关完，于是 pytest-playwright 的 session 级 `browser` fixture
teardown 卡在 `Browser.close()`，直到这几个孤儿自己退出（可能要 15~25 分钟）。
表现：用例早就跑完，pytest 却迟迟不退出、整批总时长莫名多出一截；手动结束这几个孤儿后 pytest 几秒内退出。

做法：最后一条用例 teardown（session fixture 在这里收尾）开始时，起一个后台守护线程，每 2 秒找一次
"持有本进程 driver 的 unix socket 对端、且已成孤儿（ppid=1）的进程"并 SIGTERM（仍不退再 SIGKILL），
直到 pytest 进程退出（最多 15 分钟）。
- 为什么是持续而不是一次：Chrome 关闭过程中可能又冒出新的持有者，一次性清理不够
- 为什么不按进程名过滤：能持有**本 driver** stderr socket 的孤儿只可能是本次自动化 Chrome 派生的
  （socket 是一对一的），按 socket 匹配本身就是精确的，不会误伤用户自己在用的 Chrome；名字只用于日志
只在 macOS 生效（其他平台什么都不做）；任何异常都吞掉，绝不影响用例结果。
"""
import os
import re
import signal
import subprocess
import sys
import threading
import time

import pytest


def _ps() -> dict[int, tuple[int, str]]:
    out = subprocess.run(["ps", "-A", "-o", "pid=,ppid=,command="], capture_output=True, text=True).stdout
    procs = {}
    for line in out.splitlines():
        parts = line.strip().split(None, 2)
        if len(parts) == 3 and parts[0].isdigit() and parts[1].isdigit():
            procs[int(parts[0])] = (int(parts[1]), parts[2])
    return procs


def _unix_sockets(args: list[str]) -> list[tuple[int, str, str]]:
    """返回 [(pid, 本端地址, 对端地址)]。"""
    out = subprocess.run(["lsof", "-nP", "-U", *args], capture_output=True, text=True).stdout
    rows = []
    for line in out.splitlines()[1:]:
        m = re.match(r"\S+\s+(\d+)\s+.*?\sunix\s+(0x[0-9a-f]+)\s+\S+\s+->(0x[0-9a-f]+)", line)
        if m:
            rows.append((int(m.group(1)), m.group(2), m.group(3)))
    return rows


_TERMED: set[int] = set()


def release_chrome_orphans() -> list[str]:
    procs = _ps()
    me = os.getpid()
    drivers = [pid for pid, (ppid, cmd) in procs.items() if ppid == me and "playwright/driver" in cmd]
    if not drivers:
        return []
    peers = set()
    for d in drivers:
        peers |= {peer for _, _, peer in _unix_sockets(["-a", "-p", str(d)])}
    if not peers:
        return []
    killed = []
    for pid, addr, _ in _unix_sockets([]):
        if addr not in peers or pid in drivers or pid not in procs:
            continue
        ppid, cmd = procs[pid]
        if ppid == 1:
            # 上一轮已发过 SIGTERM 还活着 → 升级 SIGKILL（防止个别进程忽略 TERM 继续占着 socket）
            sig = signal.SIGKILL if pid in _TERMED else signal.SIGTERM
            try:
                os.kill(pid, sig)
                _TERMED.add(pid)
                killed.append(f"{pid}:{os.path.basename(cmd.split(' --')[0])}:{sig.name}")
            except ProcessLookupError:
                pass
    return killed


def _watchdog(deadline: float):
    seen = set()
    while time.time() < deadline:
        try:
            for k in release_chrome_orphans():
                if k not in seen:
                    seen.add(k)
                    print(f"\n[chrome-orphans] 释放占住 driver stderr 的 Chrome 孤儿进程：{k}", flush=True)
        except Exception:  # noqa: BLE001 —— 收尾辅助，绝不影响用例结果
            pass
        time.sleep(2)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_teardown(item, nextitem):
    if nextitem is None and sys.platform == "darwin":
        # daemon 线程：pytest 退出时随进程结束，不会拖住退出
        threading.Thread(target=_watchdog, args=(time.time() + 900,), daemon=True).start()
    yield
