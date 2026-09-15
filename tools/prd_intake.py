# -*- coding: utf-8 -*-
"""需求文档入档预处理 —— 把「正文 + 内嵌 base64 图」拆成 agent 能消费的三份。

为什么需要：在线文档工具（石墨 / Notion / 飞书等）导出的 md 会把设计图内嵌成
base64 data URI，一份需求文档动辄 1.5MB 而正文只有几百字。agent 直接 Read
会被 base64 淹掉上下文，而那些图恰恰是**设计图**（表现类信息的权威源），不能丢。

产出三份：
    input/prd_<slug>.md            原件，保真归档（版本锚，gitignore）
    input/prd_<slug>.text.md       ★ agent 读这份：正文 + 图占位符（指向下面的图片）
    ui_design/<slug>_fig<N>.<ext>  抽出的设计图，agent 用 Read 当图片读

`input/` 与 `ui_design/` 都在 .gitignore 里——需求文档与设计图只留本地，不入公开仓库。

用法（<task> 可以是 task_id，也可以是任意指向任务目录的路径）：
    python3 tools/prd_intake.py <task> <需求文档路径> [更多路径…]
    python3 tools/prd_intake.py --list <task>
"""
import base64
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gate_review import resolve_task_dir  # noqa: E402

IMG_RE = re.compile(r'!\[[^\]]*\]\((data:image/(\w+);base64,([A-Za-z0-9+/=]+))\)')
BARE_RE = re.compile(r'data:image/(\w+);base64,([A-Za-z0-9+/=]{200,})')


def slugify(name: str) -> str:
    s = Path(name).stem
    s = re.sub(r"^副本\s*", "", s).strip()
    s = re.sub(r"\s*PRD$", "", s).strip()
    s = re.sub(r"[\s—–\-/]+", "_", s)
    return re.sub(r"[^\w一-鿿]", "", s) or "prd"


def intake(task_id: str, src: Path) -> dict:
    d = resolve_task_dir(task_id)
    inp, ui = d / "input", d / "ui_design"
    inp.mkdir(parents=True, exist_ok=True)
    slug = slugify(src.name)

    raw = src.read_text(encoding="utf-8", errors="ignore")
    shutil.copy2(src, inp / f"prd_{slug}.md")          # 原件保真

    figs, n = [], 0

    def save(ext: str, b64: str) -> str:
        nonlocal n
        n += 1
        ui.mkdir(parents=True, exist_ok=True)
        ext = {"jpeg": "jpg"}.get(ext.lower(), ext.lower())
        p = ui / f"{slug}_fig{n}.{ext}"
        try:
            p.write_bytes(base64.b64decode(b64))
        except Exception:
            return "［图片解码失败］"
        figs.append(p)
        return f"［图 {n} → {p.relative_to(d)}］"

    text = IMG_RE.sub(lambda m: save(m.group(2), m.group(3)), raw)
    text = BARE_RE.sub(lambda m: save(m.group(1), m.group(2)), text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()

    header = (f"<!-- 由 tools/prd_intake.py 生成：原件 input/prd_{slug}.md，"
              f"设计图 {len(figs)} 张已抽到 ui_design/ -->\n"
              f"<!-- ★ agent 读本文件，不要读原件（原件含 base64 会淹掉上下文）；"
              f"图占位符处用 Read 工具读对应图片 -->\n\n")
    (inp / f"prd_{slug}.text.md").write_text(header + text + "\n", encoding="utf-8")
    return {"slug": slug, "text_chars": len(text), "figs": [f.name for f in figs],
            "raw_kb": src.stat().st_size // 1024}


if __name__ == "__main__":
    if len(sys.argv) < 3 or sys.argv[1] == "--list":
        if len(sys.argv) >= 3 and sys.argv[1] == "--list":
            d = resolve_task_dir(sys.argv[2])
            for p in sorted((d / "input").glob("*")) + sorted((d / "ui_design").glob("*")):
                print(f"  {p.relative_to(d)}  {p.stat().st_size//1024}K")
            sys.exit(0)
        print(__doc__)
        sys.exit(1)
    task = sys.argv[1]
    for a in sys.argv[2:]:
        src = Path(a).expanduser()
        if not src.exists():
            print(f"✗ 找不到 {src}")
            continue
        r = intake(task, src)
        print(f"✓ {src.name}\n   → prd_{r['slug']}.text.md（正文 {r['text_chars']} 字，"
              f"原件 {r['raw_kb']}K）  图 {len(r['figs'])} 张 {r['figs']}")
