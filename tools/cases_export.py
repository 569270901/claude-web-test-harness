# -*- coding: utf-8 -*-
"""把 cases.md 导出成能直接交给别人执行的表格（xlsx / csv，纯标准库，无需安装依赖）。

为什么需要：cases.md 是给 agent 和评审用的，里面有 `page_ref`（页面地图外键）、
`derived_from`（解构表回指）这类内部列，手工执行的人看不懂也用不上。导出时：
  · 去掉内部列，只留 ID / 分组 / 优先级 / 执行方式 / 测试点 / 前置 / 步骤 / 期望 / 依据（prd_ref）
  · `exec` 翻成人话（自动化 / 手工 / 本轮不测）
  · 单元格里的 `<br>` 还原成换行，去掉 markdown 的反引号和加粗

用法（<task> 可以是 task_id，也可以是任意指向任务目录的路径）：
    python3 tools/cases_export.py <task>                 # 默认导出 xlsx：<任务目录>/cases_export.xlsx
    python3 tools/cases_export.py <task> --csv           # 导出 csv（UTF-8 带 BOM，Excel 双击直接打开不乱码）
    python3 tools/cases_export.py <task> -o 路径.xlsx     # 指定输出路径
    python3 tools/cases_export.py <task> --only-manual   # 只导出 exec=manual 的（交给手工执行的那部分）
"""
import csv
import re
import sys
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gate_review import parse_md, resolve_task_dir  # noqa: E402

CASE_ID_RE = re.compile(r"^\*{0,2}(TC-[A-Za-z0-9\-]+)\*{0,2}$")
EXEC_LABEL = {"auto": "自动化", "manual": "手工", "blocked": "本轮不测"}
# 导出列：(表头, cases.md 里的列名；None 表示由导出逻辑生成)
COLUMNS = [
    ("用例ID", "ID"), ("分组", None), ("优先级", "优先级"), ("执行方式", "exec"),
    ("测试点", "测试点"), ("前置条件", "前置"), ("操作步骤", "步骤"), ("预期结果", "期望"),
    ("依据", "prd_ref"),
]


def _plain(cell: str) -> str:
    """markdown 单元格 → 纯文本：<br> 变换行，去掉反引号、加粗、首尾空白。"""
    s = re.sub(r"<br\s*/?>", "\n", cell, flags=re.I)
    s = s.replace("`", "")
    s = re.sub(r"\*\*(.+?)\*\*", r"\1", s)
    return s.strip()


def load_rows(task: str, only_manual: bool = False) -> list[list[str]]:
    f = resolve_task_dir(task) / "cases.md"
    doc = parse_md(f)  # 缺文件时 parse_md 会给友好提示
    rows = []
    for sec in doc["sections"]:
        hdr = sec["header"] or []
        if "ID" not in hdr or "测试点" not in hdr:
            continue
        idx = {h: i for i, h in enumerate(hdr)}
        for r in sec["rows"]:
            c = r["cells"]

            def g(k):
                return c[idx[k]].strip() if k in idx and len(c) > idx[k] else ""

            m = CASE_ID_RE.match(g("ID"))
            if not m:
                continue
            exec_ = g("exec").replace("*", "").strip()
            if only_manual and exec_ != "manual":
                continue
            out = []
            for _, src in COLUMNS:
                if src is None:
                    out.append(sec["title"])
                elif src == "ID":
                    out.append(m.group(1))
                elif src == "exec":
                    out.append(EXEC_LABEL.get(exec_, exec_))
                else:
                    out.append(_plain(g(src)))
            rows.append(out)
    return rows


def write_csv(path: Path, rows: list[list[str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as fp:
        w = csv.writer(fp)
        w.writerow([h for h, _ in COLUMNS])
        w.writerows(rows)


def _col(n: int) -> str:
    s = ""
    n += 1
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


# 列宽（字符数），与 COLUMNS 一一对应
WIDTHS = [16, 14, 8, 10, 40, 28, 48, 48, 18]


def write_xlsx(path: Path, rows: list[list[str]]) -> None:
    """最小可用的 xlsx：一张表、表头加粗冻结、自动换行、固定列宽。"""
    def cell(ref: str, val: str, style: int) -> str:
        v = escape(val).replace("\n", "&#10;")
        return f'<c r="{ref}" t="inlineStr" s="{style}"><is><t xml:space="preserve">{v}</t></is></c>'

    sheet_rows = []
    for ri, row in enumerate([[h for h, _ in COLUMNS]] + rows, start=1):
        style = 1 if ri == 1 else 2
        cells = "".join(cell(f"{_col(ci)}{ri}", v, style) for ci, v in enumerate(row))
        sheet_rows.append(f'<row r="{ri}">{cells}</row>')
    cols = "".join(f'<col min="{i+1}" max="{i+1}" width="{w}" customWidth="1"/>'
                   for i, w in enumerate(WIDTHS))
    last = f"{_col(len(COLUMNS) - 1)}{len(rows) + 1}"
    sheet = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" '
        'activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>'
        f'<cols>{cols}</cols><sheetData>{"".join(sheet_rows)}</sheetData>'
        f'<autoFilter ref="A1:{last}"/></worksheet>')
    styles = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font>'
        '<font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
        '<fills count="2"><fill><patternFill patternType="none"/></fill>'
        '<fill><patternFill patternType="gray125"/></fill></fills>'
        '<borders count="1"><border/></borders>'
        '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
        '<cellXfs count="3"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
        '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1" applyAlignment="1">'
        '<alignment vertical="center" wrapText="1"/></xf>'
        '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0" applyAlignment="1">'
        '<alignment vertical="top" wrapText="1"/></xf></cellXfs>'
        '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
        '</styleSheet>')
    files = {
        "[Content_Types].xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
            '</Types>'),
        "_rels/.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            '</Relationships>'),
        "xl/workbook.xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="测试用例" sheetId="1" r:id="rId1"/></sheets>'
            '<definedNames><definedName name="_xlnm._FilterDatabase" localSheetId="0" hidden="1">'
            f"'测试用例'!$A$1:${_col(len(COLUMNS) - 1)}${len(rows) + 1}</definedName></definedNames>"
            '</workbook>'),
        "xl/_rels/workbook.xml.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
            '</Relationships>'),
        "xl/worksheets/sheet1.xml": sheet,
        "xl/styles.xml": styles,
    }
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(name, data)


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 1
    task, rest = argv[0], argv[1:]
    as_csv = "--csv" in rest
    only_manual = "--only-manual" in rest
    out = None
    if "-o" in rest:
        i = rest.index("-o")
        if i + 1 >= len(rest):
            print("-o 后面要跟输出路径")
            return 1
        out = Path(rest[i + 1])
    try:
        rows = load_rows(task, only_manual)
    except FileNotFoundError as e:
        print(e)
        return 2
    if not rows:
        print("cases.md 里没有找到用例行（需要含 `ID` 和 `测试点` 两列的表，ID 形如 TC-XXX-001）")
        return 2
    if out is None:
        out = resolve_task_dir(task) / ("cases_export.csv" if as_csv else "cases_export.xlsx")
    (write_csv if as_csv or out.suffix.lower() == ".csv" else write_xlsx)(out, rows)
    print(f"✓ 已导出 {len(rows)} 条用例 → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
