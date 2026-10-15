# -*- coding: utf-8 -*-
"""检查点清单 · 合并 + 完整性查账（纯标准库）

⚠️ 实验性工具，不在主流程里：GATE 0 的正式审核介质是 decomp.md + 评审控制台
（`tools/qa_console.py`，见 artifacts/agents/orchestrator.md「Gate 处理」）。本工具对应的
"粗粒度检查点清单 checkpoints.md"还没有进任何 agent 契约，新人可以忽略它。


    python3 tools/checkpoint_audit.py artifacts/<task_id> [--merge]

做三件事，前两件是**机器查账**，不信任 agent 的自述：

1. **孤儿行**：decomp 里没有被任何检查点 `←` 回指到的行 → 可能被静默漏掉
2. **幽灵回指**：检查点 `←` 指向的表行在 decomp 里根本不存在 → agent 编造了溯源（幻觉）
3. `--merge`：把 checkpoints_part*.md 合并成 checkpoints.md

第 2 项尤其重要：用户担心「你的疑惑有可能是幻觉」，回指是唯一能机器验证的抓手 ——
一条检查点如果指向不存在的素材行，它多半是凭空造的。
"""
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from decomp_review import parse as parse_decomp  # noqa: E402

CP_RE = re.compile(r"^(CP-[A-Z]+-\d+)\s+\[([^\]]+)\]\s*(.*)")
# 回指三种：decomp 表行（v1 遗留）/ PRD 章节号（v2 主锚）/ 设计图帧号
REF_RE = re.compile(r"[①②③④⑤⑥]\s*([AFSRJI]\d+)")
TBL_RE = re.compile(r"([①②③④⑤⑥])\s*([AFSRJI]\d+)")
PRD_REF_RE = re.compile(r"PRD[\s§]*(\d+(?:\.\d+)*)")
CHAP_RE = re.compile(r"第\s*(\d+)\s*章")          # 中文写法「PRD 第4章」
NAMED_SECS = ("变更记录",)                          # 无编号的章节标题（如文末的变更记录）
FRAME_RE = re.compile(r"帧\s*(\d{1,2})")
HEAD_RE = re.compile(r"^(#{2,4})\s*(\d+(?:\.\d+)*)\.?\s*(.*)")


def parse_prd_sections(prd_path: Path):
    """PRD markdown → {章节号: {"title":…, "text": 该节原文}}（text 到下一个同级或更高级标题为止）"""
    secs, order = {}, []
    cur = None
    for line in prd_path.read_text(encoding="utf-8").split("\n"):
        m = HEAD_RE.match(line)
        if m:
            cur = m.group(2)
            secs[cur] = {"title": m.group(3).strip(), "lines": []}
            order.append(cur)
            continue
        if cur:
            secs[cur]["lines"].append(line)
    return {k: {"title": v["title"], "text": "\n".join(v["lines"]).strip()}
            for k, v in secs.items()}


def _part_files(task_dir: Path):
    """v2 优先；没有 v2 才回落 v1（v1 已归档时自然取不到）"""
    return sorted(task_dir.glob("checkpoints_v2_part*.md")) or \
        sorted(task_dir.glob("checkpoints_part*.md"))


def load_checkpoints(task_dir: Path):
    """返回 [{id, meta, title, refs:[(表,行)], prd_refs:[章节号], frames:[帧], blocked, part, module}]"""
    cps = []
    for f in _part_files(task_dir):
        part = f.stem.replace("checkpoints_part", "")
        module = ""
        cur = None
        for line in f.read_text(encoding="utf-8").split("\n"):
            m = re.match(r"^##\s*■?\s*(.+?)[\s　]*\d*\s*个检查点", line) or \
                re.match(r"^##\s*■\s*(.+)", line)
            if m:
                module = m.group(1).strip()
            m = CP_RE.match(line.strip())
            if m:
                cur = {"id": m.group(1), "meta": m.group(2).strip(),
                       "title": m.group(3).strip(), "refs": [], "prd_refs": [],
                       "frames": [], "extra": [], "blocked": False,
                       "part": part, "module": module}
                cps.append(cur)
                continue
            if cur is None:
                continue
            if line.strip().startswith("CP-") or line.startswith("#"):
                cur = None
                continue
            if "🔒" in line:
                cur["blocked"] = True
            if "←" in line:
                tail = line.split("←", 1)[1]
                cur["refs"] += TBL_RE.findall(tail)
                cur["prd_refs"] += PRD_REF_RE.findall(tail) + CHAP_RE.findall(tail)
                cur["prd_refs"] += [n for n in NAMED_SECS if n in tail]
                # 同一行「← PRD 3.6.1 / 3.7.2 / 2.3」只写一次 PRD 前缀是常态，
                # 后续裸编号（必须带点，避免误吃帧号）也全收
                if "PRD" in tail:
                    cur["prd_refs"] += re.findall(r"\d+\.\d+(?:\.\d+)*", tail)
                cur["prd_refs"] = list(dict.fromkeys(cur["prd_refs"]))
                cur["frames"] += FRAME_RE.findall(tail)
            elif line.strip() and not line.startswith("```"):
                cur["extra"].append(line.strip())
    return cps


def main():
    if len(sys.argv) < 2:
        sys.exit("用法: python3 tools/checkpoint_audit.py artifacts/<task_id> [--merge]")
    td = Path(sys.argv[1]).resolve()
    rows, _ = parse_decomp(td / "decomp.md")
    cps = load_checkpoints(td)
    if not cps:
        sys.exit("没找到 checkpoints_part*.md")

    print(f"═══ 检查点清单查账 · {td.name} ═══\n")
    print(f"检查点   {len(cps)} 条"
          f"（🔒 阻塞 {sum(c['blocked'] for c in cps)} 条，占 "
          f"{sum(c['blocked'] for c in cps)*100//max(len(cps),1)}%）")
    for p in sorted({c["part"] for c in cps}):
        sub = [c for c in cps if c["part"] == p]
        print(f"  part{p}: {len(sub):>3} 条  "
              f"{', '.join(sorted({c['id'].rsplit('-',1)[0] for c in sub}))}")

    # ── 主查账（v2 口径）：PRD 章节覆盖 + 幽灵章节号 ──────────────────
    # 溯源必须终结在用户给的需求文档原文（自引不是证据，2026-07-28 用户指正）
    prd_ptr = td / "PRD_PATH.txt"
    if prd_ptr.exists():
        prd_path = Path(prd_ptr.read_text(encoding="utf-8").strip())
        secs = parse_prd_sections(prd_path)
        cited = set()
        ghost_secs = defaultdict(list)
        for c in cps:
            for s in c["prd_refs"]:
                if s in secs or s in NAMED_SECS:
                    cited.add(s)
                else:
                    ghost_secs[s].append(c["id"])
        # 叶子章节 = 没有子章节的编号；引用了后代视为父级已覆盖
        leaves = [s for s in secs
                  if not any(o != s and o.startswith(s + ".") for o in secs)]
        covered = {s for s in leaves
                   if any(x == s or x.startswith(s + ".") for x in cited)}
        uncov = [s for s in leaves if s not in covered]
        print(f"\nPRD 「{prd_path.name}」 叶子章节 {len(leaves)} 个 → "
              f"被回指覆盖 {len(covered)} 个，**未覆盖 {len(uncov)} 个**")
        for s in uncov:
            print(f"  ⚠️ §{s} {secs[s]['title'][:36]}")
        print(f"幽灵章节号 {len(ghost_secs)} 个（PRD 里不存在 = 可能是编造的溯源）")
        for g, who in sorted(ghost_secs.items())[:20]:
            print(f"  §{g:<8} ← 被 {', '.join(who[:4])} 引用")
    else:
        print("\n（无 PRD_PATH.txt，跳过 PRD 章节覆盖查账）")

    # ── 副查账：decomp 表行回指（仅当还有 v1 风格引用时才有意义）─────
    if any(c["refs"] for c in cps):
        rows, _ = parse_decomp(td / "decomp.md")
        decomp_ids = {r["id"] for r in rows}
        ghosts = defaultdict(list)
        for c in cps:
            for tbl, rid in c["refs"]:
                if rid not in decomp_ids:
                    ghosts[f"{tbl}{rid}"].append(c["id"])
        if ghosts:
            print(f"\ndecomp 幽灵回指 {len(ghosts)} 个：")
            for g, who in sorted(ghosts.items())[:10]:
                print(f"  {g:<8} ← 被 {', '.join(who[:4])} 引用")

    dup = {c["id"] for c in cps if [x["id"] for x in cps].count(c["id"]) > 1}
    if dup:
        print(f"\n⚠️ 重复的检查点 ID: {' '.join(sorted(dup))}")
    noref = [c["id"] for c in cps if not c["prd_refs"] and not c["refs"]
             and not c["frames"]]
    if noref:
        print(f"\n⚠️ 完全没有溯源的检查点 {len(noref)} 条: {' '.join(noref[:20])}")

    if "--merge" in sys.argv:
        out = [f"# {td.name} · 检查点清单（GATE 0 审核介质）\n",
               f"> 共 **{len(cps)}** 条检查点，🔒 阻塞 {sum(c['blocked'] for c in cps)} 条。\n",
               "> 粒度：一条 = 一个模块 × 一个校验类型。`←` 回指 PRD (5) 章节号（评审页可展开原文）。\n",
               "> `🔒` = 该测但缺前提，照写不删，内联带 DBT-ID。\n"]
        for f in _part_files(td):
            body = f.read_text(encoding="utf-8")
            body = re.sub(r"^---\n.*?\n---\n", "", body, flags=re.S)
            out.append(f"\n\n<!-- ===== {f.name} ===== -->\n" + body)
        (td / "checkpoints.md").write_text("".join(out), encoding="utf-8")
        print(f"\n✅ 已合并 → {td/'checkpoints.md'}")


if __name__ == "__main__":
    main()
