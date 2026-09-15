# -*- coding: utf-8 -*-
"""用例的增删改 —— GATE 1 阶段由**用户**直接编辑 cases.md。

为什么允许改（推翻了原先「控制台只读」的设计）：
GATE 1 的本质是**用户接管**。审核不该只有「通过 / 打回」两个动作 ——
看到用例写错了、少一条，就该能当场改。agent 的所有权在交付评审那一刻结束。

安全前提（三条，缺一不可）：
  1. **首次编辑前存快照** `cases.pre_gate1.md` —— 既可回滚，也是评测信号
     （人在 GATE 1 改了多少 = agent 准不准的直接读数）
  2. **改动全部记进只增不改的** `cases_edits.jsonl`（含改前值，可逐条回溯）
  3. **按用例 ID 定位而非行号** —— 行号会随编辑漂移，ID 不会

cases.md 仍是唯一事实来源：编辑直接落进它，不搞第二份覆盖层。
"""
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gate_review import resolve_task_dir  # noqa: E402

CASE_ID_RE = re.compile(r"^\*{0,2}(TC-[A-Za-z0-9\-]+)\*{0,2}$")


def paths(task_id: str) -> dict:
    d = resolve_task_dir(task_id)
    return {"dir": d, "cases": d / "cases.md",
            "snapshot": d / "cases.pre_gate1.md",
            "audit": d / "cases_edits.jsonl"}


def _cell(v: str) -> str:
    """写回单元格：竖线与换行会破坏表格结构，必须转义。"""
    return (v or "").replace("|", "\\|").replace("\n", " ").strip()


def _split(line: str) -> list[str]:
    cells = line.split("|")
    if cells and cells[0].strip() == "":
        cells = cells[1:]
    if cells and cells[-1].strip() == "":
        cells = cells[:-1]
    return [c.strip() for c in cells]


def _is_sep(line: str) -> bool:
    return bool(re.match(r"^\|[\s:\-|]+\|?\s*$", line))


def locate(task_id: str) -> dict:
    """扫 cases.md，返回 {用例ID: {line_idx, header, header_line_idx, cells}} 与各用例表的范围。"""
    lines = paths(task_id)["cases"].read_text(encoding="utf-8").splitlines()
    idx, tables, hdr, hdr_i, prev_row = {}, [], None, -1, False
    for i, l in enumerate(lines):
        if not l.startswith("|"):
            if hdr and prev_row:
                tables[-1]["end"] = i - 1
            hdr, prev_row = None, False
            continue
        if _is_sep(l):
            continue
        cells = _split(l)
        if hdr is None or not prev_row:
            hdr, hdr_i = cells, i
            tables.append({"header": cells, "header_idx": i, "end": i})
            prev_row = True
            continue
        prev_row = True
        tables[-1]["end"] = i
        if "ID" in hdr:
            j = hdr.index("ID")
            if len(cells) > j:
                m = CASE_ID_RE.match(cells[j])
                if m:
                    idx[m.group(1)] = {"line_idx": i, "header": hdr,
                                       "header_idx": hdr_i,
                                       "cells": dict(zip(hdr, cells))}
    case_tables = [t for t in tables if "ID" in t["header"] and "测试点" in t["header"]]
    return {"lines": lines, "cases": idx, "case_tables": case_tables}


def _snapshot(task_id: str) -> bool:
    p = paths(task_id)
    if p["snapshot"].exists():
        return False
    p["snapshot"].write_text(p["cases"].read_text(encoding="utf-8"), encoding="utf-8")
    return True


def _audit(task_id: str, rec: dict) -> None:
    rec["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    with paths(task_id)["audit"].open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _write(task_id: str, lines: list[str]) -> None:
    paths(task_id)["cases"].write_text("\n".join(lines) + "\n", encoding="utf-8")


def update(task_id: str, case_id: str, changes: dict, by: str = "user") -> dict:
    """改：只动传进来的那几列，其余原样。"""
    st = locate(task_id)
    if case_id not in st["cases"]:
        raise KeyError(f"找不到用例 {case_id}")
    ent = st["cases"][case_id]
    before = dict(ent["cells"])
    after = dict(before)
    for k, v in changes.items():
        if k in ent["header"]:
            after[k] = _cell(v)
    if after == before:
        return {"ok": True, "noop": True}
    snap = _snapshot(task_id)
    lines = st["lines"]
    lines[ent["line_idx"]] = "| " + " | ".join(after.get(h, "") for h in ent["header"]) + " |"
    _write(task_id, lines)
    _audit(task_id, {"op": "update", "case_id": case_id, "by": by,
                     "changed": {k: {"from": before.get(k, ""), "to": after[k]}
                                 for k in changes if before.get(k, "") != after.get(k, "")}})
    return {"ok": True, "snapshot_created": snap}


def create(task_id: str, cells: dict, by: str = "user") -> dict:
    """增：追加到最后一张用例表末尾；ID 未给则自动分配 `<前缀>-U<n>`。"""
    st = locate(task_id)
    if not st["case_tables"]:
        raise RuntimeError("cases.md 里找不到用例表（需含 ID 与 测试点 两列）")
    tbl = st["case_tables"][-1]
    hdr = tbl["header"]
    cid = (cells.get("ID") or "").strip()
    if not cid:
        pref = "TC-USER"
        for k in st["cases"]:
            m = re.match(r"^(TC-[A-Za-z]+)-", k)
            if m:
                pref = m.group(1)
                break
        n = 1 + sum(1 for k in st["cases"] if re.match(rf"^{re.escape(pref)}-U\d+$", k))
        cid = f"{pref}-U{n:02d}"
    if cid in st["cases"]:
        raise ValueError(f"用例 ID 已存在：{cid}")
    row = dict(cells)
    row["ID"] = cid
    row.setdefault("exec", "manual")          # 用户新增的默认人工，避免误进自动化
    row.setdefault("优先级", "P2")
    if "#" in hdr:
        row["#"] = str(len(st["cases"]) + 1)
    snap = _snapshot(task_id)
    lines = st["lines"]
    lines.insert(tbl["end"] + 1,
                 "| " + " | ".join(_cell(row.get(h, "")) for h in hdr) + " |")
    _write(task_id, lines)
    _audit(task_id, {"op": "create", "case_id": cid, "by": by, "cells": row})
    return {"ok": True, "case_id": cid, "snapshot_created": snap}


def delete(task_id: str, case_id: str, reason: str = "", by: str = "user") -> dict:
    """删：真删行，但把整行原文记进审计日志 —— 可回溯、可恢复。"""
    st = locate(task_id)
    if case_id not in st["cases"]:
        raise KeyError(f"找不到用例 {case_id}")
    ent = st["cases"][case_id]
    snap = _snapshot(task_id)
    lines = st["lines"]
    removed = lines.pop(ent["line_idx"])
    _write(task_id, lines)
    _audit(task_id, {"op": "delete", "case_id": case_id, "by": by,
                     "reason": reason, "removed_line": removed})
    return {"ok": True, "snapshot_created": snap}


def _status(path: Path) -> str:
    if not path.exists():
        return ""
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^status:\s*(\S+)", line)
        if m:
            return m.group(1)
    return ""


def _set_status(path: Path, new_status: str, note: str = "") -> bool:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    for i, l in enumerate(lines):
        m = re.match(r"^status:\s*(\S+)(.*)$", l)
        if m:
            if m.group(1) == new_status:
                return False
            comment = f"   # {note}" if note else m.group(2)
            lines[i] = f"status: {new_status}{comment}"
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            return True
    return False


def confirm(task_id: str, by: str = "user") -> dict:
    """GATE 1 一次性确认：整份 cases.md 通过，一个按钮，不逐条打勾。

    只改状态字段（cases.md + flow.md 若存在），不动任何用例内容；
    改前状态必须是 pending_review，防止重复点击/误触把别的状态覆盖掉。
    """
    p = paths(task_id)
    if not p["cases"].exists():
        raise FileNotFoundError(f"{p['cases']} 不存在")
    cur = _status(p["cases"])
    if cur != "pending_review":
        raise ValueError(f"当前状态是 {cur!r}，不是 pending_review，不能确认（可能已经确认过，或还没到 GATE 1）")
    snap = _snapshot(task_id)
    note = time.strftime("GATE 1 已审，%Y-%m-%d %H:%M")
    changed_cases = _set_status(p["cases"], "confirmed", note)
    flow_path = p["dir"] / "flow.md"
    changed_flow = _set_status(flow_path, "confirmed", note) if flow_path.exists() else False
    _audit(task_id, {"op": "confirm_gate1", "by": by,
                     "cases_changed": changed_cases, "flow_changed": changed_flow})
    return {"ok": True, "cases_changed": changed_cases, "flow_changed": changed_flow,
            "snapshot_created": snap}


def history(task_id: str) -> list[dict]:
    p = paths(task_id)["audit"]
    if not p.exists():
        return []
    out = []
    for l in p.read_text(encoding="utf-8").splitlines():
        if l.strip():
            try:
                out.append(json.loads(l))
            except Exception:
                pass
    return out
