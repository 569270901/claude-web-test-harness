#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""只增不改的运行日志（journal）—— 谁 / 何时 / 做了什么 / 为什么。

目的：让用户能复盘、追述 agent 的真实行为，处理理解债。

**任务级**：日志写在 `artifacts/<task_id>/journal.jsonl`，跟该任务的其它产物
（state/sync/cases/impl/review/progress.log）同目录，天然按任务封顶、随任务归档。
当前 task_id 由 orchestrator 写到 `.claude/journal_task`（单行）；**没有这个指针就不记**
（journal 只审计任务执行，任务外的零散工具调用是噪声，不入账，项目级零膨胀）。

两层记录：
  1) 客观层（harness 强制，不可遗漏/美化）
     由 Claude Code 的 PostToolUse / SubagentStart / SubagentStop hook 调用：
         python3 scripts/journal.py hook       # 从 stdin 读 hook JSON
     记录每一次工具调用：谁(agent_type)、何时、调了什么工具、目标、结果。
  2) 叙事层（agent 写，补"为什么"）
     agent 在关键决策点调用：
         python3 scripts/journal.py log --actor test-writing --action decide \\
             --what "改 data 而非报 selector 漂移" --why "元素定位到了，只是值不对" --ref round-1

复盘（人读）：
     python3 scripts/journal.py show                 # 当前任务（读指针）
     python3 scripts/journal.py show --task <id>      # 指定任务
     python3 scripts/journal.py show --actor test-writing --no-reads
     python3 scripts/journal.py show --all            # 跨所有任务归并时间线（低频）
     python3 scripts/journal.py show --follow          # 实时跟随当前任务
"""
import glob
import json
import os
import sys
import time
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARTIFACTS = os.path.join(ROOT, "artifacts")
TASK_PTR = os.path.join(ROOT, ".claude", "journal_task")

# 工具名 → 动作语义
ACTION_BY_TOOL = {
    "Read": "read", "Write": "write", "Edit": "edit", "MultiEdit": "edit",
    "NotebookEdit": "edit", "Bash": "run", "Glob": "search", "Grep": "search",
    "WebFetch": "fetch", "WebSearch": "search", "Task": "dispatch", "Agent": "dispatch",
}


def _now():
    # 本地时区 ISO，到毫秒
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def _read_task():
    try:
        with open(TASK_PTR, encoding="utf-8") as f:
            return f.read().strip() or None
    except OSError:
        return None


def _journal_path(task):
    """task → 日志文件路径；task 为空则返回 None（不记）。"""
    if not task:
        return None
    return os.path.join(ARTIFACTS, task, "journal.jsonl")


def _append(entry, task):
    """追加一行，永不抛出（绝不能因日志失败而打断工具流）。task 为空则静默跳过。"""
    path = _journal_path(task)
    if not path:
        return
    try:
        entry = {k: v for k, v in entry.items() if v not in (None, "", {}, [])}
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _trunc(s, n=200):
    s = str(s).replace("\n", " ⏎ ").strip()
    return s if len(s) <= n else s[:n] + "…"


# ---------------------------------------------------------------- hook 客观层
def cmd_hook():
    task = _read_task()
    if not task:
        return  # 没有活动任务 → 不记，项目级零膨胀
    try:
        data = json.load(sys.stdin)
    except Exception:
        return
    if not isinstance(data, dict):
        return

    event = data.get("hook_event_name", "")
    tool = data.get("tool_name", "")
    ti = data.get("tool_input") or {}
    tr = data.get("tool_response") or {}
    actor = data.get("agent_type") or "orchestrator"   # 子 agent 才有 agent_type，缺省即主对话
    session = (data.get("session_id") or "")[:8]
    if not isinstance(ti, dict):
        ti = {}

    # 过滤掉 journal 自身的调用，避免噪声/自指
    if tool == "Bash" and "journal.py" in str(ti.get("command", "")):
        return

    base = {"ts": _now(), "src": "hook", "session": session, "actor": actor}
    if data.get("agent_id"):
        base["agent_id"] = data["agent_id"]

    if event in ("SubagentStart", "SubagentStop"):
        base["action"] = "dispatch" if event == "SubagentStart" else "return"
        base["target"] = data.get("agent_type") or data.get("subagent_type") or "?"
        base["info"] = event
        _append(base, task)
        return

    # PostToolUse
    base["action"] = ACTION_BY_TOOL.get(tool, "tool")
    base["tool"] = tool
    target = (ti.get("file_path") or ti.get("path") or ti.get("notebook_path")
              or ti.get("url") or ti.get("pattern") or ti.get("subagent_type"))
    if tool == "Bash":
        target = _trunc(ti.get("command", ""), 240)
    base["target"] = _trunc(target, 240) if target else None

    info = None
    if tool == "Bash" and isinstance(tr, dict):
        ec = tr.get("exit_code")
        out = tr.get("stdout") or tr.get("stderr") or ""
        info = f"exit={ec} {_trunc(out, 140)}".strip()
    elif tool in ("Task", "Agent"):
        info = _trunc(ti.get("description", ""), 80)
    base["info"] = info
    _append(base, task)


# ---------------------------------------------------------------- log 叙事层
def cmd_log(argv):
    import argparse
    p = argparse.ArgumentParser(prog="journal.py log")
    p.add_argument("--actor", required=True, help="谁：orchestrator / page-map-sync / ...")
    p.add_argument("--action", default="decide",
                   help="decide|find|note|gate|route|error|lifecycle（默认 decide）")
    p.add_argument("--target", default=None, help="涉及的文件/元素/URL")
    p.add_argument("--what", default=None, help="做了什么（一句话）")
    p.add_argument("--why", default=None, help="为什么（决策依据，理解债的关键）")
    p.add_argument("--ref", default=None, help="关联，如 round-1 / TC-xxx")
    p.add_argument("--task", default=None, help="task_id（默认读 .claude/journal_task）")
    a = p.parse_args(argv)
    if a.action == "decide" and not a.why:
        sys.stderr.write("⚠️ decide 类事件必须带 --why（决策依据）。\n")
        sys.exit(2)
    task = a.task or _read_task()
    if not task:
        sys.stderr.write("⚠️ 无活动任务（.claude/journal_task 未设），日志未记录。\n")
        sys.exit(0)
    _append({"ts": _now(), "src": "agent", "actor": a.actor, "action": a.action,
             "target": a.target, "info": a.what, "why": a.why, "ref": a.ref}, task)


# ---------------------------------------------------------------- show 复盘
def _fmt(e, show_task=False):
    t = (e.get("ts", "") + "             ")[11:23]   # HH:MM:SS.mmm
    actor = (e.get("actor", "?") + "              ")[:16]
    action = (e.get("action", "?") + "       ")[:8]
    tag = "·" if e.get("src") == "hook" else "✎"      # ✎=agent 叙事
    prefix = f"[{e.get('task','?')}] " if show_task else ""
    line = f"{prefix}{t} {tag} {actor} {action} {e.get('target') or ''}"
    extra = e.get("why") or e.get("info")
    if extra:
        line += f"  — {extra}"
    return line.rstrip()


def cmd_show(argv):
    import argparse
    p = argparse.ArgumentParser(prog="journal.py show")
    p.add_argument("--task", default=None, help="指定任务（默认读当前指针）")
    p.add_argument("--all", action="store_true", help="跨所有任务归并（低频）")
    p.add_argument("--actor", default=None)
    p.add_argument("--action", default=None)
    p.add_argument("--no-reads", action="store_true", help="隐藏 read/search 噪声")
    p.add_argument("--limit", type=int, default=0, help="只看最后 N 行")
    p.add_argument("--follow", action="store_true", help="实时跟随（仅单任务）")
    a = p.parse_args(argv)

    def keep(e):
        if a.actor and e.get("actor") != a.actor:
            return False
        if a.action and e.get("action") != a.action:
            return False
        if a.no_reads and e.get("action") in ("read", "search"):
            return False
        return True

    # --all：扫所有任务目录，按 ts 归并
    if a.all:
        rows = []
        for path in glob.glob(os.path.join(ARTIFACTS, "*", "journal.jsonl")):
            tid = os.path.basename(os.path.dirname(path))
            try:
                for ln in open(path, encoding="utf-8"):
                    ln = ln.strip()
                    if not ln:
                        continue
                    e = json.loads(ln)
                    e["task"] = tid
                    if keep(e):
                        rows.append(e)
            except Exception:
                continue
        rows.sort(key=lambda e: e.get("ts", ""))
        if a.limit:
            rows = rows[-a.limit:]
        for e in rows:
            print(_fmt(e, show_task=True))
        return

    # 单任务
    task = a.task or _read_task()
    if not task:
        print("(没有当前任务指针，请用 --task <id> 指定，或 --all 看全部)")
        return
    path = _journal_path(task)
    if not os.path.exists(path):
        print(f"(任务 {task} 还没有 journal.jsonl —— 跑起来后再来)")
        return

    def emit(lines):
        for ln in lines:
            ln = ln.strip()
            if not ln:
                continue
            try:
                e = json.loads(ln)
            except Exception:
                continue
            if keep(e):
                print(_fmt(e))

    with open(path, encoding="utf-8") as f:
        all_lines = f.readlines()
    if a.limit and not a.follow:
        all_lines = all_lines[-a.limit:]
    emit(all_lines)

    if a.follow:
        with open(path, encoding="utf-8") as f:
            f.seek(0, os.SEEK_END)
            try:
                while True:
                    chunk = f.readlines()
                    if chunk:
                        emit(chunk)
                    else:
                        time.sleep(1.0)
            except KeyboardInterrupt:
                pass


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)
    sub, rest = sys.argv[1], sys.argv[2:]
    if sub == "hook":
        cmd_hook()
    elif sub == "log":
        cmd_log(rest)
    elif sub == "show":
        cmd_show(rest)
    else:
        sys.stderr.write(f"未知子命令: {sub}\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
