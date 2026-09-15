# -*- coding: utf-8 -*-
"""GATE 0/1 交互式评审台 —— 把 decomp.md / cases.md 变成可点选的决策队列。

设计前提：**decomp.md 仍是唯一事实来源**。本工具只做三件事：
  1. 解析 decomp.md → 抽出「需要人决策的行」（含 ⚠️ / 🔶 的行）
  2. 起本地服务器让人逐条点选，决策落 verdicts.json（机器可读）
  3. apply 把决策回填进 decomp.md，回填前存 decomp.pre_gate0.md 快照

快照的副作用是白捡的评测信号：`stats` 能算出「人在 GATE 0 改了多少格」——
这是 agent 准不准的直接读数，以前就地编辑会把它销毁。

纯标准库，无需 pip 安装。

本文件是**解析层 + 路径层**，UI / 服务器在 `gate_review_ui.py`，
三级导航的单端口控制台在 `qa_console.py`。

用法（<task> 可以是 task_id，也可以是任意指向任务目录的路径）：
    python3 tools/gate_review.py parse <task>            # 只打印解析结果，自检用
    python3 tools/gate_review_ui.py serve <task> [端口]  # 起评审台（默认 8901）
    python3 tools/gate_review_ui.py apply <task>         # 决策落裁决单
    python3 tools/gate_review_ui.py stats <task>         # GATE 0 改动量统计
"""
import json
import os
import re
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "configs" / "gate_review.json"
LOCK = threading.Lock()

# 置信度标记
MARK_OK, MARK_INFER, MARK_MISS = "✅", "🔶", "⚠️"
TABLE_RE = re.compile(r"^##\s+(①|②|③|④|⑤|⑥|⑦)\s*(.*)$")
SECTION_RE = re.compile(r"^##\s+(.+)$")


# ─────────────────────── 可选配置 ───────────────────────

def load_config() -> dict:
    """读 configs/gate_review.json（可选）。文件不在 / 解析失败一律退化成空配置——
    本工具在没有任何配置的情况下必须能用，配置只是让它更贴合具体项目。"""
    if not CONFIG.exists():
        return {}
    try:
        return json.loads(CONFIG.read_text(encoding="utf-8"))
    except Exception:
        return {}


_CFG = load_config()


# ─────────────────────── 任务目录解析 ───────────────────────

def resolve_task_dir(task_ref: str) -> Path:
    """<task> → 任务目录。两种写法都认：

      · task_id（如 `2026-06-26_fragdar_ux`）→ 解析成 <repo>/artifacts/<task_id>
      · 路径（如 `artifacts/2026-06-26_fragdar_ux` 或绝对路径）→ 按路径用

    支持第二种是为了让工具能跑在仓库外的任务目录上、也方便在任意 cwd 下 tab 补全。
    判定顺序固定，避免同名歧义：带路径分隔符 → 按路径；否则优先当 task_id。
    """
    ref = str(task_ref).rstrip("/\\")
    p = Path(ref).expanduser()
    if os.sep in ref or "/" in ref or p.is_absolute():
        return p.resolve()
    d = ROOT / "artifacts" / ref
    if d.is_dir():
        return d
    if p.is_dir():
        return p.resolve()
    return d                                   # 都不存在 → 按惯例路径返回，让下游报「文件不存在」


# ─────────────────────────── 解析 ───────────────────────────

def split_row(line: str) -> list[str]:
    """markdown 表格行 → cell 列表（去掉首尾空管道）。"""
    cells = line.split("|")
    if cells and cells[0].strip() == "":
        cells = cells[1:]
    if cells and cells[-1].strip() == "":
        cells = cells[:-1]
    return [c.strip() for c in cells]


def is_sep(line: str) -> bool:
    return bool(re.match(r"^\|[\s:\-|]+\|?\s*$", line))


def parse_md(path: Path) -> dict:
    """把 decomp.md 切成 {frontmatter, sections:[{key,title,header,rows}]}。"""
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()

    fm, body_start = {}, 0
    if lines and lines[0].strip() == "---":
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
        for l in lines[1:end]:
            if ":" in l and not l.startswith((" ", "-", "#")):
                k, v = l.split(":", 1)
                fm[k.strip()] = v.strip()
        body_start = end + 1

    # ⚠️ 一个 ## 段落下可以有**多张表**（如 cases.md 的「阅读约定」表 + 用例表）。
    # 早期实现假设一段一表，导致第二张表的表头被当数据行、整表静默丢失
    # （实锤过一次：某任务 cases.md 的 18 条用例全被吞）。
    # markdown 表格必须连续，所以「上一行不是表格行」就意味着新表开始。
    sections, cur, sec_meta, prev_is_row = [], None, None, False
    for i in range(body_start, len(lines)):
        l = lines[i]
        m = SECTION_RE.match(l)
        if m:
            tm = TABLE_RE.match(l)
            sec_meta = {
                "key": tm.group(1) if tm else m.group(1).split("（")[0].strip(),
                "title": m.group(1).strip(),
                "is_core_table": bool(tm),
            }
            cur, prev_is_row = None, False
            continue
        if not l.startswith("|"):
            prev_is_row = False
            continue
        if is_sep(l):
            continue                       # 分隔线不改变「上一行是表格行」的判断
        cells = split_row(l)
        if cur is None or not prev_is_row:  # 新表开始
            cur = dict(sec_meta or {"key": "(无标题)", "title": "(无标题)",
                                    "is_core_table": False},
                       header=cells, rows=[], line_no=i + 1,
                       table_idx=sum(1 for x in sections
                                     if sec_meta and x["key"] == sec_meta["key"]))
            sections.append(cur)
        else:
            cur["rows"].append({"cells": cells, "line_no": i + 1})
        prev_is_row = True
    return {"frontmatter": fm, "sections": sections}


# ───────────────────── 决策项抽取 ─────────────────────

CAND_PATTERNS = [
    # `新值`（前 `旧值`）
    re.compile(r"`([^`]+)`\s*（前\s*`([^`]+)`）"),
    # `A` → `B`  /  A → B
    re.compile(r"`([^`]+)`\s*→\s*`([^`]+)`"),
]


def extract_candidates(row_text: str) -> list[str]:
    """从行文本里启发式抽出「候选字面值」，给人做点选用。"""
    out = []
    for pat in CAND_PATTERNS:
        for m in pat.finditer(row_text):
            for g in m.groups():
                if g and g not in out:
                    out.append(g)
    if not out:  # 退化：抓所有反引号串，取前两个不同的
        for g in re.findall(r"`([^`]+)`", row_text):
            if g not in out and len(g) < 60:
                out.append(g)
    return out[:4]


def classify(row_text: str) -> str:
    if "⚠️冲突" in row_text:
        return "conflict"
    if "⚠️待核实" in row_text or "待核实" in row_text:
        return "verify"
    if MARK_INFER in row_text:
        return "infer"
    if MARK_MISS in row_text:
        return "missing"
    return "ok"


def build_options(kind: str, cands: list[str]) -> list[dict]:
    """每类决策的预设选项。**选项是具体答案，不是「同意/不同意」**。"""
    opts = []
    if kind == "verify":
        for c in cands[:3]:
            opts.append({"id": f"is:{c}", "label": f"现在显示的是 {c}", "hint": ""})
        opts.append({"id": "untested", "label": "我不确定，留给提测实测", "hint": "保持 ⚠️，不猜"})
    elif kind == "conflict":
        # 冲突的另一方可能是设计图 / 地图实测 / 另一份需求文档 —— 不预设，让债描述的原文说话
        opts.append({"id": "prd_right", "label": "以需求文档为准", "hint": "→ 另一方记为勘误"})
        opts.append({"id": "other_right", "label": "以另一方为准（设计图 / 实测记录）", "hint": "→ 需求文档记为勘误"})
        opts.append({"id": "answer", "label": "两者都不对，我给正确值", "hint": "→ 在下面填，来源记「用户」"})
        opts.append({"id": "untested", "label": "我不确定，留给提测实测", "hint": ""})
    elif kind == "infer":
        opts.append({"id": "agree", "label": "推断成立，按此执行", "hint": "→ 🔶 升为 ✅"})
        opts.append({"id": "fix", "label": "推断不对，我给正确值", "hint": "→ 在下面填"})
        opts.append({"id": "untested", "label": "我不确定，留给提测实测", "hint": ""})
    else:  # missing
        opts.append({"id": "answer", "label": "我知道答案，我来填", "hint": "→ 在下面填，来源记「用户」"})
        opts.append({"id": "untested", "label": "留给提测实测", "hint": "保持 ⚠️ + 解构债"})
        opts.append({"id": "out_of_scope", "label": "本轮不测（出局）", "hint": "→ 进「未覆盖说明」"})
    return opts


# 这些列的 ⚠️ **不是问用户的问题**，是给 page-map-sync 的探索工作项 /
# 给下游的承接位说明。把它们当决策卡会白占用户注意力（实锤过：某任务 28 张卡里
# 有 7 张是这类噪音）。
NON_DECISION_COLS = set(_CFG.get("non_decision_cols") or
                        ["page_ref", "承接位", "归宿", "证据", "来源"])
EXPLORE_ONLY = ("⚠️待探索", "⚠️待补")


def _decision_hot(hdr: list[str], cells: list[str]) -> list[dict]:
    """只保留「真的在问用户」的那些格子。"""
    out = []
    for i, c in enumerate(cells):
        if not (MARK_MISS in c or MARK_INFER in c):
            continue
        col = hdr[i] if i < len(hdr) else f"col{i}"
        if col.strip() in NON_DECISION_COLS:
            continue                       # page_ref 的 ⚠️待探索 → 探索项，不是决策
        if any(k in c for k in EXPLORE_ONLY) and len(c) < 160:
            continue                       # 整格就是「待探索」一句话，同上
        out.append({"col": col, "val": c})
    return out


# ─────────────────────── 分诊：这张卡该不该进用户队列 ───────────────────────
#
# 为什么需要分诊（这个机制存在的全部理由，删了就没人知道为什么要有它）：
# 一次实跑里，一个**小**需求的解构产出了 33 张决策卡丢给用户，用户的原话是
# 「注意力会崩溃」—— 33 张卡等于没有卡，人会开始无脑点下一张。
# 逐张人工复核后发现：只有 8 张真的需要用户判断，另外 25 张是「提测时看一眼就知道」
# 的实现细节（下拉能不能搜索、DOM 是隐藏还是移除、报错文案的精确措辞）。
#
# 由此得到的规律：
#   ⚠️待核实（verify）这个类型的定义本身就是「现状是什么」—— 本质是可观测事实，
#   **一律**自动留测，不该有任何一张进用户队列。
#   🔶推断 / ⚠️缺失 要分两种问法：
#     问「它现在长什么样 / 怎么实现的」（DOM 结构 / 报错措辞 / 能否搜索 / 长度上界）
#       → 可观测事实，自动留测
#     问「它应该长什么样 / 这条路径存不存在」（该不该落库 / 能不能回退 / 会不会卡住存量数据）
#       → 真正的产品判断或范围问题，才进队列
#
# 下面两张关键词表是**兜底**（见 needs_user_judgment）。调优时的两次实锤教训：
#   · 裸词「存量」会误伤「无法从存量验证」这类与业务存量数据无关的说法
#     → 只认真正指「存量业务数据」语义的复合词
#   · 「是否可达」会误伤「清空回未选态 UI 是否可达」这类纯 UI 机制问题（提测一试便知）
#     → 删掉该词；真正的范围问题由「回退」等词覆盖
# 两张表都可以在 configs/gate_review.json 里覆盖成你项目的说法。
HIGH_STAKES_MARKERS = tuple(_CFG.get("high_stakes_markers") or (
    "存量数据", "存量语义", "存量记录", "存量业务", "存量用户",
    "发版", "故障", "阻塞", "落库", "共用", "联动", "枚举字典", "数据字典",
    "上线前", "造不出", "不可逆", "越权", "权限", "脏数据", "静默失败", "静默地",
))
# 范围/存在性问题的信号词 —— 问的是「这条路径/这个场景存不存在，或数据该不该保留」，
# 不是「现在长什么样、UI 机制上走不走得通」（后者提测一试便知，不进队列）
SCOPE_MARKERS = tuple(_CFG.get("scope_markers") or (
    "能否", "是否存在", "本身未定", "回退", "作用域", "保留", "存不存", "是否一致", "暂存",
))


def needs_user_judgment(kind: str, text: str) -> bool:
    """这张卡该不该进用户队列。

    首选**agent 在 decomp.md 里显式写的标签**（`artifacts/agents/decomposition.md`
    要求每个 🔶/⚠️ 都带 `［需判断］`/`［可提测］`）—— agent 写这行时知道自己在问
    「现状」还是在问「该怎样」，下游猜不如它准。
    关键词表只是**兜底**：处理这条规则出台前写的 decomp.md（没有显式标签的旧文件）。
    """
    if kind == "conflict":
        return True                        # 冲突永远需要人裁决
    if kind == "verify":
        return False                       # 「现状是什么」— 恒为可观测事实，自动留测
    # 实锤修复：agent 经常在标签括号里塞解释性文字，比如
    # "［需判断——这是计价政策问题…］"——严格要求 "［需判断］" 四字紧跟着闭括号
    # 会在这种写法下完全匹配不到，导致真正需要用户判断的债被静默丢进 deferred，
    # 用户在 GATE 0 根本看不到。改成宽松子串匹配——"需判断"/"可提测"这两个词本身
    # 已经足够独特，不必强求括号格式。
    if "需判断" in text:
        return True                        # agent 显式声明——优先采信
    if "可提测" in text:
        return False                       # 同上
    # 兜底：没有显式标签的旧 decomp.md，退回关键词启发式
    # （精度有限，所以 UI 上有「已自动搁置」透明列表 + 「拉回来自己答」按钮）
    if any(m in text for m in HIGH_STAKES_MARKERS):
        return True
    if any(m in text for m in SCOPE_MARKERS):
        return True
    return False                           # 其余 infer/missing：默认是可观测的实现细节


def extract_decisions(doc: dict) -> list[dict]:
    """遍历所有表，把含 ⚠️ / 🔶 的行变成决策卡。

    只有「真的需要人回答」的行才成卡：page_ref 待探索、承接位说明、
    以及「提测时看一眼就知道」的实现细节，一律排除（见 needs_user_judgment）。
    """
    items = []
    for sec in doc["sections"]:
        if not sec["rows"]:
            continue
        # 「为什么判不适用」这类说明段不是表，不产决策卡
        if any(k in sec["key"] for k in ("为什么", "说明", "变更记录", "结账")):
            continue
        hdr = sec["header"] or []
        for row in sec["rows"]:
            text = " | ".join(row["cells"])
            kind = classify(text)
            if kind == "ok":
                continue
            rid = row["cells"][0] if row["cells"] else "?"
            hot = _decision_hot(hdr, row["cells"])
            if not hot:
                continue                   # 触发标记全在非决策列 → 整行不成卡
            # 注意：这里不做 needs_user_judgment 过滤 —— 原始行文本混着来源列/类比说明等噪音，
            # 不是用户实际会看到的那份文字。真正的过滤统一放在 gate_review_ui.build_cards()，
            # 对着「用户会读到的 question 文案」做判断（实测发现两者不一致会漏判）。
            dbt = re.findall(r"DBT-\d+", text)
            items.append({
                "uid": f"{sec['key']}:{rid}",
                "table": sec["key"],
                "table_title": sec["title"],
                "row_id": rid,
                "kind": kind,
                "cells": dict(zip(hdr, row["cells"])) if hdr else {},
                "hot": hot,
                "dbt": dbt,
                "options": build_options(kind, extract_candidates(text)),
                "line_no": row["line_no"],
            })
    order = {"conflict": 0, "verify": 1, "infer": 2, "missing": 3}
    items.sort(key=lambda x: (order.get(x["kind"], 9), x["table"], x["row_id"]))
    return items


# ─────────────────────────── 落盘 ───────────────────────────

def paths(task_id: str) -> dict:
    d = resolve_task_dir(task_id)
    return {
        "dir": d,
        "decomp": d / "decomp.md",
        "snapshot": d / "decomp.pre_gate0.md",
        "verdicts": d / "gate0_verdicts.json",
    }


def load_verdicts(task_id: str) -> dict:
    p = paths(task_id)["verdicts"]
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_verdicts(task_id: str, data: dict) -> None:
    with LOCK:
        paths(task_id)["verdicts"].write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def cmd_parse(task_id: str) -> None:
    p = paths(task_id)
    doc = parse_md(p["decomp"])
    print(f"frontmatter 字段 {len(doc['frontmatter'])} 个；status={doc['frontmatter'].get('status')}")
    print(f"\n段落 {len(doc['sections'])} 个：")
    for s in doc["sections"]:
        flag = "★核心表" if s["is_core_table"] else "      "
        print(f"  {flag} {s['key']:<28} 列 {len(s['header'] or []):>2}  行 {len(s['rows']):>3}   (L{s['line_no']})")
    items = extract_decisions(doc)
    from collections import Counter
    c = Counter(i["kind"] for i in items)
    print(f"\n决策项 {len(items)} 个： " + " / ".join(f"{k}={v}" for k, v in c.items()))
    print("\n前 6 个样本：")
    for it in items[:6]:
        print(f"\n  [{it['uid']}] kind={it['kind']}  DBT={it['dbt']}")
        for h in it["hot"][:2]:
            print(f"      ⚡ {h['col']}: {h['val'][:100]}")
        for o in it["options"]:
            print(f"      · {o['label']}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    cmd, task = sys.argv[1], sys.argv[2]
    if cmd == "parse":
        cmd_parse(task)
    else:
        print(f"（本文件只提供 parse 自检；{cmd} 在 tools/gate_review_ui.py 或 tools/qa_console.py）")
