# -*- coding: utf-8 -*-
"""decomp.md 结构化解构层 · GATE 0 评审服务器（纯标准库，无需安装依赖）

用法：
    python3 tools/decomp_review.py artifacts/<task_id> [端口]     # 默认 8877

数据存储：
    <task_dir>/decomp_notes.json —— {行ID: {stance, text, ts}}
    只增改不删表；空表态 + 空说明 = 撤回该行的批注。

导出（给 orchestrator 读）：
    http://127.0.0.1:<port>/api/export   → Markdown

设计要点：
  · decomp.md 每次请求都重新解析 —— agent 在增补轮改了文件，刷新页面就能看到，
    批注按「行 ID」存，行内容变了批注也不丢。
  · 默认只列 🔶推断 / ⚠️缺失 / ⚠️冲突 的行（GATE 0 真正要审的），✅确定 的行默认折叠。
"""
import json
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

LOCK = threading.Lock()
ID_RE = re.compile(r"^\*{0,2}(A\d+|F\d+|S\d+(?:-S\d+)?|R\d+|J\d+|I\d+)\*{0,2}$")
DBT_RE = re.compile(r"DBT-\d+")
STANCE_OK = {"agree", "answer", "test", "skip", ""}
STANCE_CN = {"agree": "认同推断 / 确认没定义", "answer": "用户给了答案",
             "test": "留待实测", "skip": "不用管"}
TABLE_NAMES = {
    "①": "功能点清单", "②": "字段规格表", "③": "状态机",
    "④": "业务规则表", "⑤": "操作旅程", "⑥": "影响面",
}


def _cells(line: str):
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _is_sep(cells):
    return bool(cells) and all(set(c) <= set("-: ") and c for c in cells)


def parse(md_path: Path):
    """把 decomp.md 解析成 [{id, table, sub, cols:{表头:值}, conf, dbt}]

    表头识别按 markdown 语法来：**分隔行 |---|---| 的上一行才是表头**。
    一个 section 里可以有任意多张表（③ 就是先 N×N 矩阵、后明细表），每碰到一次
    分隔行就换一次表头 —— 早期版本只认 section 的第一行当表头，导致后续表列数
    对不上、退化成 c0/c1/c2。
    """
    rows, debts = [], []
    table = sub = None
    header = None       # 当前表的表头；None = 还没进入任何表体
    cand = None         # 候选表头（上一行的 cells）
    for line in md_path.read_text(encoding="utf-8").split("\n"):
        m = re.match(r"^##\s+([①②③④⑤⑥])\s*(.*)", line)
        if m:
            table, sub, header, cand = m.group(1), m.group(2).strip(), None, None
            continue
        if re.match(r"^##\s+解构债清单", line):
            table, sub, header, cand = "DBT", "解构债清单", None, None
            continue
        if line.startswith("## "):                       # 其它段落（档位判定/依赖/摘要…）
            table = sub = header = cand = None
            continue
        m = re.match(r"^###\s+(.*)", line)
        if m and table:
            sub, header, cand = m.group(1).strip(), None, None
            continue
        if not table:
            continue
        if not line.lstrip().startswith("|"):            # 表结束（空行/正文/统计行）
            header = cand = None
            continue

        cells = _cells(line)
        if _is_sep(cells):                               # 分隔行 → 上一行就是表头
            header, cand = cand, None
            continue
        if header is None:                               # 还没见分隔行 → 存为候选表头
            cand = cells
            continue

        first = cells[0]
        if table == "DBT":
            if first.startswith("DBT-"):
                debts.append(dict(zip(header, cells)) | {"id": first})
            continue
        if not ID_RE.match(first):                       # N×N 矩阵行、小计行等
            continue
        rid = ID_RE.match(first).group(1)
        if len(cells) < len(header):                     # 少列补空，多列并进最后一列
            cells = cells + [""] * (len(header) - len(cells))
        elif len(cells) > len(header):
            cells = cells[:len(header) - 1] + [" | ".join(cells[len(header) - 1:])]
        cols = dict(zip(header, cells))
        blob = " ".join(cells)
        conf = "⚠️" if "⚠️" in cells[-1] else ("🔶" if "🔶" in cells[-1] else "✅")
        # kind 比 conf 细一档：冲突/缺帧 是「两边都有主张但对不上 / 该有的没有」，
        # 比单纯的"没写"贵得多，GATE 0 该优先裁决 → 单独给个筛选档位
        tail = cells[-1]
        kind = ("冲突" if "冲突" in tail else "缺帧" if "缺帧" in tail
                else "缺失" if conf == "⚠️" else "推断" if conf == "🔶" else "确定")
        rows.append({"id": rid, "table": table, "sub": sub, "cols": cols,
                     "conf": conf, "kind": kind,
                     "dbt": sorted(set(DBT_RE.findall(blob)))})

    # ── 给每一行算出「到底要用户回答什么」──────────────────────────────
    # 光把数据摆出来用户不知道要干嘛。缺口的位置（哪一列带 ⚠️/🔶）+ 解构债的描述
    # 合起来才是那句人话的问题。
    dmap = {}
    for d in debts:
        desc = next((v for k, v in d.items() if "描述" in k), "")
        dmap[d["id"]] = re.sub(r"\*\*", "", desc)
    for r in rows:
        asks = []
        for k, v in r["cols"].items():
            if k in ("ID", "来源") or not v:
                continue
            for mark in ("⚠️", "🔶"):
                if mark not in v:
                    continue
                # 取带标记的那个片段（到最近的分隔符为止），当作"这里不确定"的说明
                for seg in re.split(r"[；;|]", v):
                    if mark in seg:
                        asks.append({"col": k, "mark": mark, "frag": seg.strip()[:120]})
        r["asks"] = asks
        r["dbt_desc"] = [{"id": i, "desc": dmap.get(i, "")} for i in r["dbt"]]
        # 主值 = 带缺口的那一列的完整内容（用户主要就是在核这一列）
        gapcol = next((a["col"] for a in asks if a["col"] not in ("置信度",)), None)
        r["gapcol"] = gapcol
        r["gapval"] = r["cols"].get(gapcol, "") if gapcol else ""
    return rows, debts


def load(store: Path) -> dict:
    if store.exists():
        try:
            return json.loads(store.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save(store: Path, data: dict) -> None:
    tmp = store.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(store)


def export_md(rows, debts, notes) -> str:
    done = {k: v for k, v in notes.items() if v.get("stance") or v.get("text")}
    by_id = {r["id"]: r for r in rows}
    out = ["# GATE 0 评审批注汇总", "",
           f"导出时间：{time.strftime('%Y-%m-%d %H:%M')} · 共 {len(done)} 条批注", ""]
    for stance in ["answer", "agree", "test", "skip"]:
        ids = [i for i, n in done.items() if n.get("stance") == stance]
        if not ids:
            continue
        out += [f"## {STANCE_CN[stance]}（{len(ids)} 条）", "",
                "| 行ID | 表 | 对象 | 问的是什么 | 用户批注 | DBT |",
                "|---|---|---|---|---|---|"]
        for i in sorted(ids):
            r = by_id.get(i, {})
            vals = list(r.get("cols", {}).values())
            obj = vals[1][:40] if len(vals) > 1 else ""
            ask = "；".join(f"{a['col']}: {a['frag']}" for a in r.get("asks", []))[:90]
            out.append(f"| {i} | {r.get('table','')} | {obj} | {ask} | "
                       f"{done[i].get('text','').replace(chr(10),' ')} | "
                       f"{','.join(r.get('dbt',[]))} |")
        out.append("")
    未 = [r["id"] for r in rows if r["conf"] != "✅" and r["id"] not in done]
    out += [f"## 未处理（{len(未)} 条）", "", " ".join(未) or "（无）", ""]
    return "\n".join(out)


HTML = r"""<!doctype html><meta charset="utf-8"><title>GATE 0 · 解构评审</title>
<style>
*{box-sizing:border-box}body{margin:0;font:14px/1.6 -apple-system,"PingFang SC",sans-serif;background:#12141a;color:#dfe3ea}
header{position:sticky;top:0;z-index:9;background:#181b23;border-bottom:1px solid #2a2f3a;padding:10px 16px}
h1{font-size:15px;margin:0 0 8px;font-weight:600}
.bar{display:flex;gap:6px;flex-wrap:wrap;align-items:center}
button,select,input{font:inherit;background:#232833;color:#dfe3ea;border:1px solid #333a49;border-radius:6px;padding:4px 10px;cursor:pointer}
button.on{background:#2d6a4f;border-color:#40916c;color:#fff}
input[type=search]{cursor:text;min-width:200px}
.prog{margin-left:auto;font-variant-numeric:tabular-nums;color:#9aa4b6}
.prog b{color:#7ee2b8;font-size:16px}
main{padding:14px 16px 80px;max-width:1180px}
.card{background:#181b23;border:1px solid #262b36;border-left:3px solid #555;border-radius:8px;padding:10px 12px;margin:0 0 10px}
.card.miss{border-left-color:#d97706}.card.inf{border-left-color:#3b82f6}.card.ok{border-left-color:#2d6a4f}
.card.done{background:#141b17;border-color:#2d6a4f}
.hd{display:flex;gap:8px;align-items:baseline;flex-wrap:wrap;margin-bottom:6px}
.rid{font:600 13px ui-monospace,Menlo,monospace;color:#7ee2b8}
.title{font-size:15px;font-weight:600;color:#f0f3f8}
.tag{font-size:11px;padding:1px 7px;border-radius:99px;background:#232833;color:#9aa4b6}
.tag.dbt{background:#3b2f1a;color:#e5b567}
.tag.hot{background:#4a1d1d;color:#ff9b9b;font-weight:700}
.kv{display:grid;grid-template-columns:max-content 1fr;gap:3px 12px;font-size:13px;margin:2px 0 8px}
.kv dt{color:#7c8598;white-space:nowrap}.kv dd{margin:0;color:#c9d1de;overflow-wrap:anywhere}
.kv dt.meta,.kv dd.meta{color:#5f6878;font-size:12px}
.kv b{color:#fff}.kv code{background:#0d0f14;padding:1px 5px;border-radius:4px;font-size:12px;color:#9fd5ff}
.kv i{color:#c8b78a;font-style:normal}
.warn{color:#e0a458;font-weight:600}.inf2{color:#7cb3f5;font-weight:600}
.ask{background:#1f1a12;border:1px solid #4a3a1d;border-radius:7px;padding:8px 11px;margin:0 0 9px}
.card.inf .ask{background:#141b26;border-color:#25405e}
.askh{font-weight:700;color:#f0c987;margin-bottom:4px;font-size:13px}
.card.inf .askh{color:#8dc0f7}
.ask ul{margin:0;padding-left:17px}.ask li{margin:2px 0;font-size:13px;color:#cfd6e2}
.ask li.dd{color:#a9b3c4;list-style:'▸ '}
.cur{background:#0f1218;border:1px dashed #333a49;border-radius:7px;padding:7px 11px;margin:0 0 9px;font-size:13px}
.curk{display:block;font-size:11px;color:#7c8598;margin-bottom:2px}
details.more{margin:0 0 9px}details.more summary{cursor:pointer;font-size:12px;color:#7c8598;outline:none}
details.more .kv{margin-top:6px;padding-left:4px;border-left:2px solid #262b36}
.act{display:flex;gap:6px;flex-wrap:wrap;align-items:center}
.act label{display:flex;align-items:center;gap:4px;font-size:13px;background:#232833;border:1px solid #333a49;border-radius:6px;padding:3px 9px;cursor:pointer}
.act label:has(input:checked){background:#2d6a4f;border-color:#40916c;color:#fff}
textarea{width:100%;margin-top:6px;min-height:34px;background:#12141a;color:#dfe3ea;border:1px solid #333a49;border-radius:6px;padding:6px 8px;font:inherit;resize:vertical}
.sec{margin:22px 0 8px;font-size:13px;color:#7c8598;border-bottom:1px solid #262b36;padding-bottom:4px}
.saved{color:#7ee2b8;font-size:12px;margin-left:6px;opacity:0;transition:.3s}.saved.s{opacity:1}
</style>
<header>
  <h1>GATE 0 · 结构化解构评审 <span id="task" style="color:#7c8598;font-weight:400"></span></h1>
  <div class="bar">
    <span>表：</span><span id="tabs"></span>
    <select id="fconf"><option value="conflict">⚠️冲突 + 缺帧（最该先裁决）</option>
      <option value="gap" selected>全部待审（🔶+⚠️）</option><option value="miss">只看 ⚠️缺失</option>
      <option value="inf">只看 🔶推断</option><option value="all">全部（含 ✅）</option></select>
    <button id="fnew" class="on">只看未处理</button>
    <input type="search" id="q" placeholder="搜索文字 / 行ID / DBT-012">
    <a href="/api/export" style="color:#7ee2b8;font-size:13px">导出批注 ↓</a>
    <span class="prog"><b id="pd">0</b> / <span id="pt">0</span> 已处理</span>
  </div>
</header><main id="app">加载中…</main>
<script>
let ROWS=[],NOTES={},TABLE='',F={conf:'gap',onlyNew:true,q:''};
// 表态值稳定（agree/answer/test/skip），但按缺口类型换成不同的人话标签
const L={
 inf:{agree:'✔ 推断对',answer:'✍ 不对，实际是',test:'⏳ 待实测',skip:'⊘ 不用管',
      ph:'选「推断对」就不用写。选「不对」请写正确的值，例：菜单项文案是 "Edit category"'},
 hot:{agree:'✔ 按 PRD 算数',answer:'✍ 我裁定为→',test:'⏳ 待实测/待问产品',skip:'⊘ 不用管',
      ph:'裁定这条以哪边为准、或写下真实规则。缺帧的写清该功能 V1 到底做不做'},
 miss:{agree:'❓ 确实没定义，要产品补',answer:'✍ 我知道，答案是',test:'⏳ 待实测',skip:'⊘ 不用管',
      ph:'知道答案就写这里，例：上限 999，超出报 "Value too large"'}};
// cell 里的行内 markdown 渲染：**粗** / *斜* / `码`，并高亮 ⚠️🔶
function fmt(s){return (s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;')
  .replace(/\*\*(.+?)\*\*/g,'<b>$1</b>').replace(/`(.+?)`/g,'<code>$1</code>')
  .replace(/(?<!\*)\*([^*]+?)\*(?!\*)/g,'<i>$1</i>')
  .replace(/⚠️[^\s，。；/|]*/g,m=>`<span class="warn">${m}</span>`)
  .replace(/🔶[^\s，。；/|]*/g,m=>`<span class="inf2">${m}</span>`)}
async function boot(){const d=await (await fetch('/api/data')).json();ROWS=d.rows;NOTES=d.notes;
  document.getElementById('task').textContent=d.task;
  const ts=[...new Set(ROWS.map(r=>r.table))];
  document.getElementById('tabs').innerHTML=['',...ts].map(t=>
    `<button data-t="${t}" class="${t===TABLE?'on':''}">${t||'全部'}${t?` <span style="opacity:.6">${ROWS.filter(r=>r.table===t&&r.conf!=='✅').length}</span>`:''}</button>`).join('');
  document.querySelectorAll('#tabs button').forEach(b=>b.onclick=()=>{TABLE=b.dataset.t;boot()});
  render()}
function vis(r){if(F.conf==='gap'&&r.conf==='✅')return false;
  if(F.conf==='conflict'&&!['冲突','缺帧'].includes(r.kind))return false;
  if(F.conf==='miss'&&r.kind!=='缺失')return false;if(F.conf==='inf'&&r.conf!=='🔶')return false;
  if(TABLE&&r.table!==TABLE)return false;
  const n=NOTES[r.id];if(F.onlyNew&&n&&(n.stance||n.text))return false;
  if(F.q){const s=(r.id+JSON.stringify(r.cols)+r.dbt.join()).toLowerCase();
    if(!s.includes(F.q.toLowerCase()))return false}
  return true}
function render(){const app=document.getElementById('app');const show=ROWS.filter(vis);
  const gap=ROWS.filter(r=>r.conf!=='✅');
  document.getElementById('pt').textContent=gap.length;
  document.getElementById('pd').textContent=gap.filter(r=>{const n=NOTES[r.id];return n&&(n.stance||n.text)}).length;
  if(!show.length){app.innerHTML='<p style="color:#7c8598">没有符合条件的行 —— 可能这一批都审完了 🎉</p>';return}
  let h='',sub=null;
  for(const r of show){const key=r.table+' · '+(r.sub||'');
    if(key!==sub){sub=key;const nm=['功能点清单','字段规格表','状态机','业务规则表','操作旅程','影响面']['①②③④⑤⑥'.indexOf(r.table)]||'';
      const s=(r.sub&&r.sub!==nm)?' — '+r.sub:'';
      h+=`<div class="sec">${r.table} ${nm}${s}</div>`}
    const n=NOTES[r.id]||{};const cls=r.conf==='⚠️'?'miss':r.conf==='🔶'?'inf':'ok';
    const ent=Object.entries(r.cols).filter(([k,v])=>v&&v!=='—'&&v!=='-');
    const [tk,tv]=ent[1]||['',''];                       // 第2列 = 主语，当卡片标题
    const ctx=ent.slice(2).filter(([k])=>k!==r.gapcol&&k!=='置信度');
    const lab=['冲突','缺帧'].includes(r.kind)?L.hot:(r.conf==='🔶'?L.inf:L.miss);
    h+=`<div class="card ${cls} ${(n.stance||n.text)?'done':''}" id="c-${r.id}">
      <div class="hd"><span class="rid">${r.table}-${r.id}</span>
        <span class="title">${fmt(tv)}</span>
        ${['冲突','缺帧'].includes(r.kind)?`<span class="tag hot">${r.kind}</span>`:''}
        ${r.dbt.map(d=>`<span class="tag dbt">${d}</span>`).join('')}</div>

      <div class="ask"><div class="askh">${
        r.kind==='冲突'?'PRD 和设计图对不上，你判哪个算数？':
        r.kind==='缺帧'?'PRD 要求了，但设计稿里没画 —— 这功能设计了吗？':
        r.conf==='🔶'?'这是我推断的，对不对？':'这里 PRD 没写，你知道吗？'}</div>
        <ul>${(r.asks.length?r.asks:[{col:'—',frag:'（见下方内容）'}]).map(a=>
          `<li><b>${a.col}</b> — ${fmt(a.frag)}</li>`).join('')}
          ${r.dbt_desc.filter(d=>d.desc).map(d=>`<li class="dd"><b>${d.id}</b> ${fmt(d.desc)}</li>`).join('')}</ul></div>

      ${r.gapcol?`<div class="cur"><span class="curk">当前${r.conf==='🔶'?'推断':''}值 · ${r.gapcol}</span>
        <div>${fmt(r.gapval)}</div></div>`:''}

      <details class="more"><summary>其它字段 (${ctx.length}) · 来源 ${fmt(r.cols['来源']||'')}</summary>
        <dl class="kv">${ctx.map(([k,v])=>`<dt>${k}</dt><dd>${fmt(v)}</dd>`).join('')}</dl></details>

      <div class="act">${['agree','answer','test','skip'].map(v=>
        `<label><input type="radio" name="s-${r.id}" value="${v}" ${n.stance===v?'checked':''}>${lab[v]}</label>`).join('')}
        <span class="saved" id="sv-${r.id}">已存</span></div>
      <textarea id="t-${r.id}" placeholder="${lab.ph}">${(n.text||'').replace(/</g,'&lt;')}</textarea>
    </div>`}
  app.innerHTML=h;
  for(const r of show){
    document.querySelectorAll(`input[name="s-${r.id}"]`).forEach(i=>i.onchange=()=>put(r.id));
    document.getElementById('t-'+r.id).onblur=()=>put(r.id)}}
async function put(id){const el=document.querySelector(`input[name="s-${id}"]:checked`);
  const body={id,stance:el?el.value:'',text:document.getElementById('t-'+id).value};
  await fetch('/api/notes',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  NOTES[id]=body.stance||body.text?{...body,ts:new Date().toLocaleString()}:undefined;
  if(!NOTES[id])delete NOTES[id];
  const s=document.getElementById('sv-'+id);s.classList.add('s');setTimeout(()=>s.classList.remove('s'),900);
  document.getElementById('c-'+id).classList.toggle('done',!!NOTES[id]);
  const gap=ROWS.filter(r=>r.conf!=='✅');
  document.getElementById('pd').textContent=gap.filter(r=>NOTES[r.id]).length}
document.getElementById('fconf').onchange=e=>{F.conf=e.target.value;render()};
document.getElementById('fnew').onclick=e=>{F.onlyNew=!F.onlyNew;e.target.classList.toggle('on',F.onlyNew);render()};
document.getElementById('q').oninput=e=>{F.q=e.target.value;render()};
boot()
</script>"""


class Handler(BaseHTTPRequestHandler):
    task_dir: Path = None

    def _send(self, code, body, ctype="application/json; charset=utf-8", extra=None):
        raw = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(raw)

    @property
    def md(self):
        return self.task_dir / "decomp.md"

    @property
    def store(self):
        return self.task_dir / "decomp_notes.json"

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._send(200, HTML, "text/html; charset=utf-8")
        elif self.path == "/api/data":
            with LOCK:
                rows, debts = parse(self.md)
                self._send(200, json.dumps(
                    {"rows": rows, "debts": debts, "notes": load(self.store),
                     "task": self.task_dir.name}, ensure_ascii=False))
        elif self.path == "/api/export":
            with LOCK:
                rows, debts = parse(self.md)
                md = export_md(rows, debts, load(self.store))
            self._send(200, md, "text/markdown; charset=utf-8",
                       {"Content-Disposition": "attachment; filename=gate0_notes.md"})
        else:
            self._send(404, '{"ok":false}')

    def do_POST(self):
        if self.path != "/api/notes":
            return self._send(404, '{"ok":false}')
        try:
            n = int(self.headers.get("Content-Length", 0))
            p = json.loads(self.rfile.read(n).decode("utf-8"))
        except Exception:
            return self._send(400, '{"ok":false,"msg":"bad json"}')
        rid = str(p.get("id", "")).strip()[:16]
        stance = str(p.get("stance", "")).strip()
        text = str(p.get("text", "")).strip()[:4000]
        if not rid or stance not in STANCE_OK:
            return self._send(400, '{"ok":false,"msg":"缺行ID或表态非法"}')
        with LOCK:
            data = load(self.store)
            if not stance and not text:
                data.pop(rid, None)
            else:
                data[rid] = {"stance": stance, "text": text,
                             "ts": time.strftime("%Y-%m-%d %H:%M")}
            save(self.store, data)
        self._send(200, '{"ok":true}')

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("用法: python3 tools/decomp_review.py artifacts/<task_id> [端口]")
    Handler.task_dir = Path(sys.argv[1]).resolve()
    if not (Handler.task_dir / "decomp.md").exists():
        sys.exit(f"找不到 {Handler.task_dir/'decomp.md'}")
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 8877
    rows, debts = parse(Handler.task_dir / "decomp.md")
    gap = [r for r in rows if r["conf"] != "✅"]
    print(f"解析 {Handler.task_dir.name}/decomp.md：{len(rows)} 行，其中待审 {len(gap)} 行"
          f"（⚠️{sum(1 for r in gap if r['conf']=='⚠️')} / 🔶{sum(1 for r in gap if r['conf']=='🔶')}）"
          f"，解构债 {len(debts)} 条")
    print(f"→ 打开 http://127.0.0.1:{port}/    批注存 {Handler.task_dir.name}/decomp_notes.json（Ctrl+C 停止）")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
