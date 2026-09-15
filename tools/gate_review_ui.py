# -*- coding: utf-8 -*-
"""GATE 0 评审台的 UI 与服务器部分（解析逻辑在 gate_review.py）。

职责边界（重要）：
  · 本工具**不改 decomp.md 的表格内容** —— 那是 test-case-design 的产物，谁的产物谁改。
  · 它只产出 gate0_verdicts.json（机器可读）+ gate0_verdicts.md（人可读），
    然后由 orchestrator 派 test-case-design **增补轮**读裁决回填 decomp.md。
    （增补轮的触发条件在 artifacts/agents/orchestrator.md 里本来就写着「用户答复了大量 ⚠️」。）
  · apply 只做三件事：存 decomp.pre_gate0.md 快照 → 写裁决单 → frontmatter status 改 gate0_answered。

用法（<task> 可以是 task_id，也可以是任意指向任务目录的路径）：
    python3 tools/gate_review_ui.py serve <task> [端口]   # 默认 8901
    python3 tools/gate_review_ui.py apply <task>
    python3 tools/gate_review_ui.py stats <task>
"""
import json
import re
import sys
from collections import Counter, defaultdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gate_review import (parse_md, extract_decisions, paths, load_verdicts,  # noqa: E402
                         save_verdicts, build_options, MARK_MISS,
                         needs_user_judgment, load_config)

EXCLUDE_TABLES = {"解构债清单", "已识别的依赖", "变更对照总表", "输入档位判定"}
KIND_META = {
    "conflict": ("⚠️冲突", "需求文档与实测记录互相矛盾，必须你裁决"),
    "verify":   ("⚠️待核实", "需求文档说的现值与实测记录不符，你看一眼就能答"),
    "infer":    ("🔶推断", "agent 靠类比填的，认同就放行、不对就改"),
    "missing":  ("⚠️缺失", "无人知道，你知道就填、不知道就留给实测"),
}

# ── 需求文档交叉引用的可配置形状（configs/gate_review.json，整块可缺省）──
# 不同团队的需求文档长得完全不一样，这里**不硬编码任何一家的章节名**：
# 配置为空时只按字面值反查原文，命中不了就整块不显示，功能优雅退化而非报错。
_PRD_CFG = (load_config().get("prd_index") or {})
CATS = set(_PRD_CFG.get("categories") or [])          # 变更分类标题（空 = 不分类）
SIDES = set(_PRD_CFG.get("scopes") or [])             # 端别 / 角色标题（空 = 不分端）
RULE_SECTION_MARKERS = tuple(_PRD_CFG.get("rule_section_markers") or
                             ("规范内容", "规则说明", "总体规则", "背景与目标"))


def find_prd(task_id: str) -> Path | None:
    d = paths(task_id)["dir"] / "input"
    if not d.exists():
        return None
    for f in sorted(d.glob("prd_*.md")):
        return f
    return None


def prd_index(task_id: str) -> list[dict]:
    """把需求文档切成「章节链 → 位置 → 变更行」的块，供卡片反查原文背景。

    认的形状：`# 标题` 建立上下文，`1. <位置>` 标记位置，含 `→` 的行是「旧 → 新」变更行。
    标题只有在命中 configs/gate_review.json 里声明的 categories / scopes 时才被用作
    分类/端别；没配置就只留位置与变更行。文档形状对不上 → 返回空列表，卡片不显示原文区块。
    """
    f = find_prd(task_id)
    if not f:
        return []
    lines = f.read_text(encoding="utf-8").splitlines()
    blocks, cat, side, loc, loc_no = [], "", "", "", 0
    for i, l in enumerate(lines, 1):
        t = l.strip()
        if t.startswith("#"):
            h = t.lstrip("#").strip()
            if h in CATS:
                cat, side, loc = h, "", ""
            elif h in SIDES:
                side, loc = h, ""
            continue
        m = re.match(r"^\d+\.\s*(.+)$", t)
        if m:
            loc, loc_no = m.group(1).strip(), i
            continue
        if "→" in t:
            a, b = [x.strip() for x in t.split("→", 1)]
            blocks.append({"cat": cat, "side": side, "loc": loc, "loc_line": loc_no,
                           "before": a, "after": b, "line": i, "raw": t})
    return blocks


LIT_RE = re.compile(r"`([^`]+)`|\"([^\"]+)\"")


def literals(*texts: str) -> list[str]:
    """抽出文本里的字面值（反引号或双引号包裹），用于反查需求文档。"""
    out = []
    for t in texts:
        for m in LIT_RE.finditer(t or ""):
            v = (m.group(1) or m.group(2) or "").strip()
            if 2 < len(v) < 60 and v not in out and not v.startswith(("page_map", "tests/", "specs/", "DBT-")):
                out.append(v)
    return out


# 位置线索词：英文页面/模块名，外加配置里声明的端别词（没配置就只认英文名）
_SCOPE_ALT = "|".join(re.escape(s) for s in sorted(SIDES, key=len, reverse=True))
LOC_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z ]{2,}" + (f"|{_SCOPE_ALT}" if _SCOPE_ALT else ""))


def match_prd(card_texts: list[str], blocks: list[dict]) -> list[dict]:
    """卡片 → 需求文档原文块。字面值命中为准入，位置词重合度用于排序
    （区分同一字符串出现在多个页面的情况）。"""
    def norm(x):
        return re.sub(r"\s+", " ", (x or "").replace("\u00a0", " ")).strip().lower()

    q = " ".join(card_texts)
    lits = [norm(x) for x in literals(*card_texts)]
    clues = {w.strip().lower() for w in LOC_TOKEN_RE.findall(q) if len(w.strip()) > 2}
    clues -= {"tab", "tabs", "prd"}

    scored = []
    for b in blocks:
        nb, na = norm(b["before"]), norm(b["after"])
        if not any(l == nb or l == na or (len(l) > 6 and (l in nb or l in na)) for l in lits):
            continue
        hay = norm(b["loc"] + " " + b["side"] + " " + b["cat"])
        score = sum(1 for c in clues if c in hay)
        if b["side"] and norm(b["side"]) in norm(q):
            score += 2                                    # 端别命中权重更高
        scored.append((score, b))
    scored.sort(key=lambda x: (-x[0], x[1]["line"]))
    top = scored[0][0] if scored else 0
    out = []
    for sc, b in scored[:6]:
        b = dict(b)
        b["likely"] = bool(top and sc == top and sc > 0)
        out.append(b)
    return out


def prd_rule_block(task_id: str) -> dict | None:
    """兜底：影响面/范围类的卡在需求文档里没有对应变更行，给它规则段原文当背景。
    段落标题字面值见 configs/gate_review.json 的 prd_index.rule_section_markers。"""
    f = find_prd(task_id)
    if not f:
        return None
    lines = f.read_text(encoding="utf-8").splitlines()
    for i, l in enumerate(lines, 1):
        if any(k in l for k in RULE_SECTION_MARKERS):
            txt = [x.strip() for x in lines[i - 1:i + 8] if x.strip()]
            return {"line": i, "raw": "\n".join(txt[:6]), "cat": "规则段", "side": "",
                    "loc": "需求文档开头的规则定义", "likely": False}
    return None


DEBT_TABLE = "解构债清单"


def load_debts(doc: dict) -> dict:
    """解构债清单的「描述」列就是人话问题 —— 这是卡片的正文来源。"""
    for sec in doc["sections"]:
        if sec["key"] == DEBT_TABLE and sec["header"]:
            hdr = sec["header"]
            out = {}
            for r in sec["rows"]:
                d = dict(zip(hdr, r["cells"]))
                did = d.get("债ID", "").strip().strip("*`")
                if did:
                    out[did] = d
            return out
    return {}


# 「A（图）vs B（需求文档）」这类字面值冲突：冲突双方是设计图与需求文档，不是地图实测
SRC_PAIR_RE = re.compile(
    r"([^：:，。]+?)\s*[（(](图|设计图)[）)]\s*vs\.?\s*([^：:，。（(]+?)\s*[（(](PRD|需求|需求文档)[）)]")


def options_from_question(q: str, kind: str) -> list[dict]:
    """从人话问题里解析出具体候选答案。选项必须是答案本身，不是「同意/不同意」。"""
    plain = re.sub(r"\*\*|`", "", q)

    # ① 「X（图）vs Y（需求文档）」—— 字面值冲突，双方是设计图与需求文档
    m = SRC_PAIR_RE.search(plain)
    if m:
        fig, prd = m.group(1).strip(), m.group(3).strip()
        return [{"id": f"is:{fig}", "label": f"按设计图：{fig}", "hint": "需求文档记为勘误"},
                {"id": f"is:{prd}", "label": f"按需求文档：{prd}", "hint": "设计图记为笔误"},
                {"id": "answer", "label": "两者都不对，我给正确值", "hint": "→ 在下面填，来源记「用户」"},
                {"id": "untested", "label": "我不确定，留给提测实测", "hint": "保持 ⚠️，不猜"}]

    # ② 「当前是 X 还是 Y」—— 两侧都必须短、且不含破折号/说明，否则会把解释切进选项
    m = re.search(r"是\s*([^，。？?—－]{1,40}?)\s*还是\s*([^，。？?（(—－]{1,40})", plain)
    if m:
        a, b = m.group(1).strip(), m.group(2).strip()
        if a and b and not any(x in a + b for x in ("决定", "——", "写 ")):
            return [{"id": f"is:{a}", "label": f"现在是 {a}", "hint": ""},
                    {"id": f"is:{b}", "label": f"现在是 {b}", "hint": ""},
                    {"id": "untested", "label": "我不确定，留给提测实测", "hint": "保持 ⚠️，不猜"}]
    # 形如「是否有 / 是否可搜索 / 是否需要」——把「——」之后的后果拼进 hint，
    # 否则「是/否」看不出选了会怎样
    if re.search(r"是否", plain):
        tail = ""
        m2 = re.search(r"[—－]{1,2}\s*(.+)$", plain)
        if m2:
            tail = m2.group(1).strip()[:80]
        return [{"id": "yes", "label": "是", "hint": tail},
                {"id": "no", "label": "不是 / 没有", "hint": tail},
                {"id": "answer", "label": "情况更复杂，我说明", "hint": "→ 在下面填"},
                {"id": "untested", "label": "我不确定，留给提测实测", "hint": ""}]
    # 形如「指哪个页面：A，还是 B？」
    m = re.search(r"[:：]\s*(.+)$", plain)
    if m and "还是" in m.group(1):
        parts = [x.strip(" ？?，,。") for x in m.group(1).split("还是") if x.strip()]
        if 2 <= len(parts) <= 4:
            return [{"id": f"is:{x}", "label": x, "hint": ""} for x in parts] + \
                   [{"id": "untested", "label": "我不确定，留给提测实测", "hint": ""}]
    return []


# 「无债描述可用」时，退化取哪一列当问题文案——绝不能用「置信度/来源/证据」这类纯元数据列。
# 两次实锤：
#  ① 清单类表（表①那种）里，「置信度」列写的是 "✅确定（规则本身）／…⚠️冲突（见 M06）"，
#    被直接当问题显示给用户，用户看不懂在问什么；
#  ② 矩阵类表（表③ 那种 N×N）列名是本次需求现造的状态/条件名，压根不在任何固定列名单里
#    —— 两类表要用两种退化策略。
# 另一次实锤：曾把「当前状态」也放进 CONTENT_COLS，以为它跟「字段」一样是内容列——
# 实际它是表③矩阵的**行身份列**，命中它会在还没走到 hot 分支前就把裸行名当问题返回，
# 正是本文件想避免的「看不懂在问什么」。
CONTENT_COLS = ("功能点", "字段", "元素含义", "测试点", "条件", "结果/约束",
                "旅程", "新功能点", "描述", "触发节点")
_MARKER_STRIP_RE = re.compile(
    r"^(✅|🔶|⚠️)(推断|确定|缺失|冲突|合法|待核实)?\s*(［[^］]+］|\[[^\]]+\])?\s*")


def _row_gist(cells: dict, hot: list[dict] | None = None) -> str:
    """挑一列真正描述"这行在说什么"的内容。

    优先级：① 固定内容列（功能点/字段等，适用于清单类表）
           ② 矩阵类表（列名是本次现造的状态/条件名）没有固定列名可猜，
              退化成「行身份 × 列头（这本身就是问题）：格子里的值（去掉标记）」——
              列头本来就是人话，比瞎猜列名靠谱。
    """
    for col in CONTENT_COLS:
        v = (cells.get(col) or "").strip()
        if v and v not in ("—", "-"):
            return v
    if hot:
        h = hot[0]
        row_label = next(iter(cells.values()), "").strip() if cells else ""
        val = _MARKER_STRIP_RE.sub("", h["val"] or "").strip()
        col = h["col"].strip()
        if row_label and row_label != col:
            return f"{row_label} × {col}：{val}"[:220]
        return f"{col}：{val}"[:220]
    return ""


def build_cards(task_id: str) -> dict:
    doc = parse_md(paths(task_id)["decomp"])
    debts = load_debts(doc)
    blocks = prd_index(task_id)
    prd_file = find_prd(task_id)
    rule_blk = prd_rule_block(task_id)
    items = [i for i in extract_decisions(doc) if i["table"] not in EXCLUDE_TABLES]
    # 分组单位是「解构债」而不是「表行」：一行常同时提多个债（实锤见过一行提 7 个），
    # 只取 dbt[0] 会让其余债静默消失（有两条债从未进过队列）。
    # 一行可以同时作为多张卡的证据 —— 问题的单位是债，行只是证据。
    groups = defaultdict(list)
    for it in items:
        for d in (it["dbt"] or [f"solo:{it['uid']}"]):
            groups[d].append(it)
    # 债清单里登记了、但没有任何表行引用的债，同样要能成卡（哪怕没有表行证据）。
    # 过滤统一放在函数末尾，对着 question 文案判断——见文件末尾 needs_user_judgment 调用处。
    for did in debts:
        groups.setdefault(did, [])

    cards = []
    for key, rows in groups.items():
        if not rows:                       # 债清单里有、表行没引用 → 用债描述单独成卡
            d = debts.get(key, {})
            q = d.get("描述", "").strip() or "（该债缺描述）"
            kd = "missing" if MARK_MISS in q or not q else "infer"
            derived = options_from_question(q, kd)
            cards.append({"cid": key, "dbt": key, "question": q,
                          "_judge": " ".join([q, " ".join(d.values())]),
                          "prd": (match_prd([q], blocks) or ([rule_blk] if rule_blk else [])),
                          "debt_rows": d.get("所属表", ""), "debt_status": d.get("状态", ""),
                          "kind": kd, "kind_label": KIND_META[kd][0], "kind_hint": KIND_META[kd][1],
                          "rows": [], "row_count": 0, "evidence": [],
                          "options": derived or build_options(kd, []), "per_row": False})
            continue
        head = rows[0]
        evid, seen = [], set()
        for r in rows:
            for h in r["hot"]:
                sig = (h["col"], h["val"][:80])
                if sig not in seen:
                    seen.add(sig)
                    evid.append({"row": r["uid"], "col": h["col"], "val": h["val"]})
        # 选项合并规则：单行卡可以给具体候选值；多行卡（一个债覆盖多个字符串）
        # 给具体值会歧义 —— 改为「卡级处置 + 逐行填值」，见 per_row。
        opts, seen_lbl = [], set()
        for o in head["options"]:
            lbl = o["label"].strip().strip('"`')          # 注意：不要叫 key，会遮蔽外层分组键
            if lbl not in seen_lbl:
                seen_lbl.add(lbl)
                opts.append(o)
        if len(rows) > 1:
            opts = [o for o in opts if not o["id"].startswith("is:")]
            if head["kind"] in ("verify", "missing") and not any(o["id"] == "answer" for o in opts):
                opts.insert(0, {"id": "answer", "label": "我逐行填正确值（在下面填）",
                                "hint": "→ 来源记「用户」，未填的行保持 ⚠️"})
        debt = debts.get(key, {})
        question = debt.get("描述", "").strip()
        if not question:
            # 无债描述（solo 卡）→ 优先取行内真正的内容列，矩阵表退化成「行×列头：值」
            # （见 _row_gist 注释里的两次实锤），绝不能退化成「置信度」原始值
            question = _row_gist(head.get("cells", {}), head.get("hot"))
            if not question:
                question = max((e["val"] for e in evid), key=len, default="（该行缺少可读描述）")
        # 债描述能解析出单一问题 → 用它的具体候选值（哪怕覆盖多行，也只是一个答案）；
        # 解析不出来才退化成「逐行填值」。
        derived = options_from_question(question, head["kind"])
        if derived:
            opts = derived
        # 实锤修复：agent 常把［需判断］/［可提测］标签写在债清单的「状态」列
        # （而非「描述」列，`question` 只取自「描述」），或者写在被引用的具体表行里，
        # 而不是债清单本身——原先只对 `question` 判断，两种情况都会让标签
        #「实际写了、但过滤器读不到」，真正需要用户判断的债被静默丢进 deferred。
        # 现在判断时把债清单整行 + 所有引用行的原始 cell 文本都拼进去，标签写在哪一处都能命中。
        judge_text = " ".join([question, " ".join(debt.values())] +
                              [" ".join(r["cells"].values()) for r in rows])
        cards.append({
            "cid": key,
            "dbt": key if key.startswith("DBT") else None,
            "question": question,
            "_judge": judge_text,
            "prd": (match_prd([question] + [e["val"] for e in evid], blocks)
                    or ([rule_blk] if rule_blk else [])),
            "debt_rows": debt.get("所属表", ""),
            "debt_status": debt.get("状态", ""),
            "kind": head["kind"],
            "kind_label": KIND_META[head["kind"]][0],
            "kind_hint": KIND_META[head["kind"]][1],
            "rows": [{"uid": r["uid"], "table": r["table"], "row_id": r["row_id"],
                      "cells": r["cells"], "line_no": r["line_no"]} for r in rows],
            "row_count": len(rows),
            "evidence": evid,
            "options": opts,
            "per_row": (not derived) and len(rows) > 1
                       and head["kind"] in ("verify", "missing"),
        })
    # 唯一的过滤点：对着用户实际会读到的 question 文案判断，而不是原始表格行
    # （行文本混着来源列/类比说明等噪音，会导致漏判——实锤：33 张卡人工复核只有 8 张
    # 真正需要用户判断，而行级过滤只漏判到 21 张）。
    all_cards, cards = cards, [c for c in cards if needs_user_judgment(c["kind"], c["_judge"])]
    deferred = [c for c in all_cards if c not in cards]
    for c in all_cards:
        c.pop("_judge", None)                # 内部判断用，不进前端 payload
    order = {"conflict": 0, "verify": 1, "infer": 2, "missing": 3}
    cards.sort(key=lambda c: (order.get(c["kind"], 9), -c.get("row_count", 0), c["cid"]))
    deferred.sort(key=lambda c: (order.get(c["kind"], 9), c["cid"]))
    return {"frontmatter": doc["frontmatter"], "cards": cards, "deferred": deferred,
            "prd_file": prd_file.name if prd_file else None,
            "prd_total": len(blocks),
            "sections": [{"key": s["key"], "title": s["title"], "header": s["header"],
                          "rows": [r["cells"] for r in s["rows"]],
                          "is_core_table": s["is_core_table"]} for s in doc["sections"]]}


# ─────────────────────── apply / stats ───────────────────────

def cmd_apply(task_id: str) -> None:
    p = paths(task_id)
    data, cards = load_verdicts(task_id), build_cards(task_id)["cards"]
    if not data:
        print("没有任何裁决，先 serve 并作答。")
        return
    if not p["snapshot"].exists():
        p["snapshot"].write_text(p["decomp"].read_text(encoding="utf-8"), encoding="utf-8")
        print(f"✓ 已存人审前快照 {p['snapshot'].name}（评测信号，勿删）")

    by_cid = {c["cid"]: c for c in cards}
    lines = ["# GATE 0 裁决单", "",
             f"> 由 `tools/gate_review_ui.py` 生成。机器可读版：`{p['verdicts'].name}`",
             f"> 待决 {len(cards)} 项，已答 {len(data)} 项。",
             "> **回填 decomp.md 由 test-case-design 增补轮执行**（谁的产物谁改）。", "",
             "| 卡 | 类型 | 覆盖行 | 裁决 | 补充值 | 备注 |", "|---|---|---|---|---|---|"]
    for cid, v in sorted(data.items()):
        c = by_cid.get(cid, {})
        rows = ", ".join(r["uid"] for r in c.get("rows", []))
        label = next((o["label"] for o in c.get("options", []) if o["id"] == v.get("choice")),
                     v.get("choice", ""))
        lines.append(f"| {cid} | {c.get('kind_label','')} | {rows} | {label} | "
                     f"{v.get('value','') or '—'} | {v.get('note','') or '—'} |")
    (p["dir"] / "gate0_verdicts.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"✓ 已写人可读裁决单 gate0_verdicts.md（{len(data)} 条）")

    txt = p["decomp"].read_text(encoding="utf-8")
    if "status: pending_review" in txt:
        txt = txt.replace("status: pending_review", "status: gate0_answered", 1)
        txt = txt.replace("baseline_decomp:",
                          f"gate0_verdicts: {p['verdicts'].name}\nbaseline_decomp:", 1)
        p["decomp"].write_text(txt, encoding="utf-8")
        print("✓ decomp.md frontmatter: status → gate0_answered（内容未动）")
    print("\n下一步：orchestrator 派 test-case-design 增补轮，读裁决回填 → status: confirmed")


def cmd_stats(task_id: str) -> None:
    data, cards = load_verdicts(task_id), build_cards(task_id)["cards"]
    print(f"待决 {len(cards)} 项 / 已答 {len(data)} 项 "
          f"（{len(data)/max(len(cards),1):.0%}）\n")
    by_kind = Counter(c["kind"] for c in cards)
    ans_kind = Counter(next((c["kind"] for c in cards if c["cid"] == k), "?") for k in data)
    print("按类型：")
    for k, (lab, _) in KIND_META.items():
        print(f"  {lab:<10} 待决 {by_kind.get(k,0):>3}  已答 {ans_kind.get(k,0):>3}")
    ch = Counter(v.get("choice", "") for v in data.values())
    if ch:
        print("\n用户选了什么（agent 准不准的直接读数）：")
        for c, n in ch.most_common():
            print(f"  {n:>3}  {c}")
        resolved = sum(n for c, n in ch.items() if c not in ("untested",))
        print(f"\n⚠️ 消解率 = {resolved}/{len(data)} = {resolved/max(len(data),1):.0%}"
              "   （untested 的仍留解构债，进下一迭代）")
    snap = paths(task_id)["snapshot"]
    print(f"\n人审前快照：{'存在 ✓' if snap.exists() else '尚未生成（apply 时创建）'}")


# ─────────────────────────── server ───────────────────────────

class Handler(BaseHTTPRequestHandler):
    task_id = ""

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        raw = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path == "/":
            self._send(200, PAGE, "text/html; charset=utf-8")
        elif self.path == "/api/cards":
            self._send(200, json.dumps(build_cards(self.task_id), ensure_ascii=False))
        elif self.path == "/api/verdicts":
            self._send(200, json.dumps(load_verdicts(self.task_id), ensure_ascii=False))
        else:
            self._send(404, json.dumps({"error": "not found"}))

    def do_POST(self):
        if self.path != "/api/verdicts":
            return self._send(404, json.dumps({"error": "not found"}))
        n = int(self.headers.get("Content-Length", 0))
        try:
            payload = json.loads(self.rfile.read(n) or b"{}")
        except Exception as e:
            return self._send(400, json.dumps({"error": str(e)}))
        data = load_verdicts(self.task_id)
        cid = payload.get("cid")
        if not cid:
            return self._send(400, json.dumps({"error": "cid required"}))
        if payload.get("clear"):
            data.pop(cid, None)
        else:
            data[cid] = {k: payload.get(k, "") for k in ("choice", "value", "note")}
            data[cid]["answered_at"] = payload.get("answered_at", "")
            if payload.get("rowvals"):
                data[cid]["rowvals"] = payload["rowvals"]
        save_verdicts(self.task_id, data)
        self._send(200, json.dumps({"ok": True, "count": len(data)}, ensure_ascii=False))

    def log_message(self, *a):
        pass


PAGE = r"""<!doctype html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>GATE 0 评审台</title><style>
:root{--bg:#f5f7f8;--surf:#fff;--surf2:#eaeff2;--ink:#131c24;--ink2:#48565f;--ink3:#6e7d87;
--rule:#d3dbe0;--gate:#9c6a05;--ok:#146f67;--danger:#9e3428;--infer:#7a5901}
@media(prefers-color-scheme:dark){:root{--bg:#0e141a;--surf:#161e25;--surf2:#1c262e;--ink:#e6edf2;
--ink2:#9babb6;--ink3:#7a8b96;--rule:#2b3a44;--gate:#dca62c;--ok:#45afa3;--danger:#de7c70;--infer:#d8b24a}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.7 -apple-system,"PingFang SC","Microsoft YaHei",sans-serif}
.mono{font-family:"IBM Plex Mono",ui-monospace,Menlo,Consolas,monospace}
header{position:sticky;top:0;z-index:9;background:var(--surf);border-bottom:1px solid var(--rule);
padding:12px 22px;display:flex;align-items:center;gap:18px;flex-wrap:wrap}
h1{font-size:16px;margin:0;font-weight:600}
.bar{flex:1;min-width:180px;height:8px;background:var(--surf2);border-radius:4px;overflow:hidden}
.bar>i{display:block;height:100%;background:var(--ok);width:0%;transition:width .25s}
.tabs{display:flex;gap:6px}
button{font:inherit;cursor:pointer;border:1px solid var(--rule);background:var(--surf);
color:var(--ink);border-radius:5px;padding:5px 12px}
button:hover{border-color:var(--ink3)}
button.on{background:var(--ink);color:var(--bg);border-color:var(--ink)}
main{max-width:1080px;margin:0 auto;padding:22px}
.card{background:var(--surf);border:1px solid var(--rule);border-radius:8px;padding:20px 22px;margin-bottom:16px}
.chip{display:inline-block;font-size:11px;padding:2px 8px;border-radius:3px;border:1px solid currentColor}
.k-conflict{color:var(--danger)}.k-verify{color:var(--gate)}.k-infer{color:var(--infer)}.k-missing{color:var(--ink3)}
.head{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:6px}
.q{font-size:17px;line-height:1.6;margin:2px 0 8px;font-weight:500}
.q code{background:var(--surf2);padding:1px 6px;border-radius:3px;font-size:15px;
font-family:"IBM Plex Mono",ui-monospace,Menlo,monospace}
.hint{color:var(--ink2);font-size:13px;margin:0 0 18px}
.prd{border:1px solid var(--rule);border-radius:6px;padding:12px 14px;margin-bottom:16px;background:var(--bg)}
.prdt{font-size:11px;letter-spacing:.1em;color:var(--ink3);margin-bottom:9px;
font-family:"IBM Plex Mono",ui-monospace,monospace}
.prdb{padding:8px 10px;border-radius:4px;margin-bottom:6px;background:var(--surf)}
.prdb.lk{box-shadow:inset 0 0 0 1px var(--gate)}
.prdh{display:flex;gap:10px;font-size:11px;color:var(--ink3);margin-bottom:3px}
.prdl{font-size:12px;color:var(--ink2);margin-bottom:4px}
.prdr{margin:0;font-family:"IBM Plex Mono",ui-monospace,Menlo,monospace;font-size:13px;
white-space:pre-wrap;word-break:break-word;color:var(--ink)}
.more summary{cursor:pointer;font-size:12px;color:var(--ink3);padding:3px 0}
.tech{margin-bottom:16px;font-size:13px}
.tech summary{cursor:pointer;color:var(--ink3);font-size:12px;padding:4px 0}
.tech summary:hover{color:var(--ink)}
.ev code{background:var(--bg);padding:1px 5px;border-radius:3px}
.ev{background:var(--surf2);border-radius:6px;padding:12px 14px;margin-bottom:14px}
.ev div{margin-bottom:7px;font-size:13px;word-break:break-word}
.ev div:last-child{margin:0}
.ev b{color:var(--ink3);font-weight:500;font-size:11px;letter-spacing:.05em}
.rows{font-size:12px;color:var(--ink3);margin-bottom:14px}
.rows code{background:var(--surf2);padding:1px 5px;border-radius:3px;margin-right:5px}
.opts{display:flex;flex-direction:column;gap:8px;margin-bottom:14px}
.opt{display:flex;align-items:flex-start;gap:10px;text-align:left;padding:11px 14px;width:100%}
.opt.sel{border-color:var(--ok);box-shadow:inset 0 0 0 1px var(--ok)}
.opt kbd{border:1px solid var(--rule);border-radius:3px;padding:0 5px;font-size:11px;color:var(--ink3);flex:none}
.opt em{color:var(--ink3);font-style:normal;font-size:12px;display:block}
input,textarea{width:100%;font:inherit;padding:9px 11px;border:1px solid var(--rule);
border-radius:5px;background:var(--bg);color:var(--ink);margin-bottom:10px}
textarea{min-height:56px;resize:vertical}
.nav{display:flex;gap:8px;align-items:center;margin-top:6px}
.nav span{color:var(--ink3);font-size:12px;margin-left:auto}
table{width:100%;border-collapse:collapse;font-size:12px;margin:8px 0 22px}
th,td{border:1px solid var(--rule);padding:6px 9px;text-align:left;vertical-align:top}
th{background:var(--surf2);font-size:11px;color:var(--ink3);font-weight:500}
tr.hot td{background:color-mix(in srgb,var(--gate) 12%,transparent)}
h2{font-size:15px;margin:22px 0 4px}
.done{background:var(--surf);border:1px solid var(--ok);border-radius:8px;padding:18px 22px;color:var(--ink)}
.done code{background:var(--surf2);padding:2px 6px;border-radius:3px}
</style></head><body>
<header>
  <h1>GATE 0 评审台</h1>
  <div class="tabs">
    <button id="tq" class="on" onclick="setView('queue')">决策队列</button>
    <button id="tt" onclick="setView('tables')">全表浏览</button>
  </div>
  <div class="bar"><i id="pb"></i></div>
  <span class="mono" id="pt" style="font-size:12px;color:var(--ink3)"></span>
</header>
<main id="app">加载中…</main>
<script>
let D=null,V={},idx=0,view='queue',filter='all';
const $=s=>document.querySelector(s);
async function boot(){
  D=await (await fetch('/api/cards')).json();
  V=await (await fetch('/api/verdicts')).json();
  const first=D.cards.findIndex(c=>!V[c.cid]); idx=first<0?0:first;
  render();
}
function list(){return filter==='all'?D.cards:D.cards.filter(c=>c.kind===filter)}
function prog(){const t=D.cards.length,a=Object.keys(V).length;
  $('#pb').style.width=(t?a/t*100:0)+'%';$('#pt').textContent=a+' / '+t;}
function esc(s){return (s||'').replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]))}
function md(s){return esc(s).replace(/\*\*([^*]+)\*\*/g,'<b>$1</b>')
  .replace(/`([^`]+)`/g,'<code>$1</code>')}
function setView(v){view=v;$('#tq').className=v==='queue'?'on':'';$('#tt').className=v==='tables'?'on':'';render()}
function setFilter(f){filter=f;idx=0;render()}
function render(){prog(); view==='queue'?renderQueue():renderTables()}

function renderQueue(){
  const L=list();
  if(!L.length){$('#app').innerHTML='<div class="card">这个筛选下没有待决项。</div>';return}
  if(idx>=L.length)idx=L.length-1;
  const c=L[idx],v=V[c.cid]||{};
  const counts={};D.cards.forEach(x=>counts[x.kind]=(counts[x.kind]||0)+1);
  let h='<div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:16px">'+
    ['all','conflict','verify','infer','missing'].map(f=>{
      const n=f==='all'?D.cards.length:(counts[f]||0);
      const lab=f==='all'?'全部':(D.cards.find(x=>x.kind===f)||{}).kind_label||f;
      return `<button class="${filter===f?'on':''}" onclick="setFilter('${f}')">${lab} ${n}</button>`}).join('')+'</div>';
  h+='<div class="card"><div class="head">'+
    `<span class="chip k-${c.kind}">${c.kind_label}</span>`+
    (c.dbt?`<span class="mono" style="font-size:12px;color:var(--ink3)">${c.dbt}</span>`:'')+
    (c.row_count>1?`<span class="chip k-missing">1 个答案决定 ${c.row_count} 行</span>`:'')+
    (V[c.cid]?'<span class="chip k-verify">已答</span>':'')+'</div>';
  h+=`<p class="q">${md(c.question)}</p>`;
  h+=`<p class="hint">${c.kind_hint}　·　这个答案会更新 ${c.row_count} 处解构表内容</p>`;
  const pl=c.prd.filter(b=>b.likely),po=c.prd.filter(b=>!b.likely);
  const blk=b=>`<div class="prdb${b.likely?' lk':''}">`+
    `<div class="prdh"><span class="mono">需求文档 第 ${b.line} 行</span>`+
    (b.cat?`<span>${esc(b.cat)}${b.side?' › '+esc(b.side):''}</span>`:'')+'</div>'+
    (b.loc?`<div class="prdl">${esc(b.loc)}</div>`:'')+
    `<pre class="prdr">${esc(b.raw)}</pre></div>`;
  if(c.prd.length){
    h+='<div class="prd"><div class="prdt">需求文档原文</div>'+
       (pl.length?pl.map(blk).join(''):blk(c.prd[0]));
    const rest=pl.length?po:c.prd.slice(1);
    if(rest.length)h+=`<details class="more"><summary>另有 ${rest.length} 处也提到这个字符串</summary>`+
       rest.map(blk).join('')+'</details>';
    h+='</div>';
  }
  h+=`<details class="tech"><summary>查看解构表原始行与证据（${c.evidence.length} 条）</summary>`;
  h+='<div class="rows">受影响行：'+c.rows.map(r=>`<code>${r.uid}</code>`).join('')+
     (c.debt_rows?`　债登记于 <code>${esc(c.debt_rows)}</code>`:'')+'</div>';
  h+='<div class="ev">'+c.evidence.map(e=>
      `<div><b>${esc(e.col)}</b>　${md(e.val)}<span class="mono" style="color:var(--ink3);font-size:11px"> ·${e.row}</span></div>`
    ).join('')+'</div></details>';
  h+='<div class="opts">'+c.options.map((o,i)=>
      `<button class="opt ${v.choice===o.id?'sel':''}" onclick="pick('${c.cid}','${o.id.replace(/'/g,"\\'")}')">`+
      `<kbd>${i+1}</kbd><span>${esc(o.label)}${o.hint?`<em>${esc(o.hint)}</em>`:''}</span></button>`
    ).join('')+'</div>';
  if(c.per_row){
    const rv=v.rowvals||{};
    h+='<div style="margin-bottom:10px">';
    c.rows.forEach(r=>{h+=`<div style="display:flex;gap:8px;align-items:center;margin-bottom:6px">`+
      `<code class="mono" style="flex:none;min-width:110px;font-size:12px">${r.uid}</code>`+
      `<input data-row="${r.uid}" class="rv" placeholder="这行现在实际显示什么（逐字抄，不确定就留空）" `+
      `value="${esc(rv[r.uid]||'')}" style="margin:0"></div>`});
    h+='</div>';
  } else {
    h+=`<input id="val" placeholder="补充值（选「我来填」「我给正确值」时必填，逐字抄字面值）" value="${esc(v.value)}">`;
  }
  h+=`<textarea id="note" placeholder="备注（为什么这么判，可选）">${esc(v.note)}</textarea>`;
  h+='<div class="nav"><button onclick="save(true)">保存并下一张 ⏎</button>'+
     `<button onclick="jump(-1)">← 上一张</button><button onclick="jump(1)">下一张 →</button>`+
     (V[c.cid]?`<button onclick="clr('${c.cid}')">清除本卡</button>`:'')+
     `<span class="mono">${idx+1} / ${L.length}　快捷键 1-9 选项 · j/k 翻卡 · ⏎ 保存</span></div>`;
  h+='</div>';
  if(Object.keys(V).length===D.cards.length)
    h+=`<div class="done"><b>${D.cards.length} 项全部答完。</b><br>回到终端执行 `+
       '<code>python3 tools/gate_review_ui.py apply '+(D.frontmatter.task_id||'&lt;task&gt;')+'</code>'+
       '，它会存人审前快照、生成裁决单，然后让我派增补轮回填 decomp.md。</div>';
  $('#app').innerHTML=h;
}
function renderTables(){
  let h='';
  D.sections.filter(s=>s.is_core_table).forEach(s=>{
    h+=`<h2>${esc(s.title)}</h2><div style="overflow-x:auto"><table><tr>`+
       (s.header||[]).map(x=>`<th>${esc(x)}</th>`).join('')+'</tr>';
    s.rows.forEach(r=>{
      const t=r.join(' | '),hot=t.includes('⚠️')||t.includes('🔶');
      h+=`<tr class="${hot?'hot':''}">`+r.map(x=>`<td>${esc(x)}</td>`).join('')+'</tr>';
    });
    h+='</table></div>';
  });
  $('#app').innerHTML=h;
}
function pick(cid,oid){(V[cid]=V[cid]||{}).choice=oid;render()}
function jump(d){const L=list();idx=Math.max(0,Math.min(L.length-1,idx+d));render()}
async function save(next){
  const L=list(),c=L[idx],v=V[c.cid]||{};
  if(!v.choice){alert('先选一个选项');return}
  const body={cid:c.cid,choice:v.choice,note:$('#note').value,
              answered_at:new Date().toISOString()};
  if(c.per_row){const rv={};document.querySelectorAll('.rv').forEach(el=>{
      if(el.value.trim())rv[el.dataset.row]=el.value.trim()});
    body.rowvals=rv;body.value=Object.entries(rv).map(([k,x])=>k+'='+x).join('; ');}
  else{body.value=$('#val').value;}
  await fetch('/api/verdicts',{method:'POST',headers:{'Content-Type':'application/json'},
              body:JSON.stringify(body)});
  V[c.cid]=body;
  if(next){const nx=D.cards.findIndex(x=>!V[x.cid]);
    if(nx>=0){const j=L.findIndex(x=>x.cid===D.cards[nx].cid);idx=j>=0?j:idx}}
  render();
}
async function clr(cid){
  await fetch('/api/verdicts',{method:'POST',headers:{'Content-Type':'application/json'},
              body:JSON.stringify({cid,clear:true})});
  delete V[cid];render();
}
document.addEventListener('keydown',e=>{
  if(view!=='queue'||['INPUT','TEXTAREA'].includes(e.target.tagName))
    {if(e.key==='Enter'&&e.metaKey)save(true);return}
  const L=list(),c=L[idx];if(!c)return;
  if(/^[1-9]$/.test(e.key)){const o=c.options[+e.key-1];if(o)pick(c.cid,o.id)}
  else if(e.key==='j')jump(1); else if(e.key==='k')jump(-1);
  else if(e.key==='Enter')save(true);
});
boot();
</script></body></html>"""


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__ + "\n用法：serve <task> [port] | apply <task> | stats <task>")
        sys.exit(1)
    cmd, task = sys.argv[1], sys.argv[2]
    if cmd == "apply":
        cmd_apply(task)
    elif cmd == "stats":
        cmd_stats(task)
    elif cmd == "serve":
        port = int(sys.argv[3]) if len(sys.argv) > 3 else 8901
        Handler.task_id = task
        n = len(build_cards(task)["cards"])
        print(f"GATE 0 评审台：http://127.0.0.1:{port}/\n待决 {n} 项 · 裁决落盘 "
              f"{paths(task)['verdicts']}\nCtrl-C 结束")
        ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
    else:
        print(f"未知命令 {cmd}")
