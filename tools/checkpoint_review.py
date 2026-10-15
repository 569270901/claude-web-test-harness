# -*- coding: utf-8 -*-
"""检查点清单 · GATE 0 评审服务器（纯标准库）

⚠️ 实验性工具，不在主流程里：GATE 0 的正式审核介质是 decomp.md + 评审控制台
（`tools/qa_console.py`，见 artifacts/agents/orchestrator.md「Gate 处理」）。本工具对应的
"粗粒度检查点清单 checkpoints.md"还没有进任何 agent 契约，新人可以忽略它。


    python3 tools/checkpoint_review.py artifacts/<task_id> [端口]      # 默认 8878

与 decomp_review.py 的分工：
  · decomp_review  审「解构底稿」—— 我的疑惑清单，内部工作用
  · checkpoint_review 审「完整检查点清单」—— **GATE 0 的正式人审介质**

两层判断，缺一不可（用户 2026-07-28 提的核心诉求）：
  · **检查点级**：这条写得对不对（认可 / 要改 / 删掉）
  · **模块级**：这个模块的覆盖够不够（够 / 缺什么）
    ——「够不够」是模块级判断，逐条看是看不出漏了什么的。

每条检查点可**就地展开它回指的 decomp 表行**，不用离开页面就能查证溯源是不是编的。
批注存 <task_dir>/checkpoint_notes.json，按检查点 ID / 模块名存。
"""
import json
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from decomp_review import parse as parse_decomp                      # noqa: E402
from checkpoint_audit import load_checkpoints, parse_prd_sections   # noqa: E402
from gate_review import load_config                                 # noqa: E402

LOCK = threading.Lock()
CP_STANCE = {"ok", "fix", "drop", ""}
MOD_STANCE = {"enough", "missing", ""}
# 检查点 ID 前缀 → 模块中文名。**纯展示用**，是每个项目自己的模块划分，
# 所以不硬编码在代码里：写在 configs/gate_review.json 的 checkpoint_module_names，
# 形如 {"CP-SRCH": "搜索", "CP-AUTH": "登录态"}。
# 不配置就是空表，界面直接显示裸 ID（`MC[m]||''` / `.get(m,'')` 已做退化）。
MODULE_CN = dict(load_config().get("checkpoint_module_names") or {})


def build(td: Path):
    """溯源解析次序（2026-07-28 用户指正后确立）：
    检查点的证据链必须终结在 **PRD 原文**，不能终结在 decomp（那是我自己的转述，
    自引不是证据）。所以 src 首选 PRD (5) 章节原文；decomp 行仅作 v1 遗留的次级参考。"""
    # PRD 原文（主溯源）
    secs = {}
    prd_name = ""
    ptr = td / "PRD_PATH.txt"
    if ptr.exists():
        pp = Path(ptr.read_text(encoding="utf-8").strip())
        if pp.exists():
            secs = parse_prd_sections(pp)
            prd_name = pp.name
    # decomp（次级，仅 v1 风格引用还在时用）
    rows, _ = parse_decomp(td / "decomp.md") if (td / "decomp.md").exists() else ([], [])
    dmap = {r["id"]: r for r in rows}
    for r in rows:
        if "-" in r["id"]:
            a, b = r["id"].split("-")
            for n in range(int(a[1:]), int(b[1:]) + 1):
                dmap.setdefault(f"{a[0]}{n:02d}", r)

    cps = load_checkpoints(td)
    for c in cps:
        c["mod"] = c["id"].rsplit("-", 1)[0]
        # 主溯源：PRD 原文段落
        c["prd"] = []
        for s in dict.fromkeys(c.get("prd_refs", [])):
            if s == "变更记录":
                c["prd"].append({"sec": s, "title": "变更记录（PRD 末尾，标题无编号）",
                                 "text": "该章为变更日志，请对照 PRD 原文末尾核对"})
                continue
            if s in secs:
                t = secs[s]["text"]
                c["prd"].append({"sec": s, "title": secs[s]["title"],
                                 "text": t[:1500] + ("\n…（后略）" if len(t) > 1500 else "")})
            else:
                c["prd"].append({"sec": s, "title": "❌ PRD 中不存在此章节号",
                                 "text": "（可能是编造的溯源，需人工核实）"})
        c["prd_name"] = prd_name
        # 次级：decomp 行（v1 遗留）
        c["src"] = []
        for tbl, rid in c["refs"]:
            r = dmap.get(rid)
            if r:
                vals = [v for v in r["cols"].values() if v and v not in ("—", "-")]
                c["src"].append({"id": f"{tbl}{rid}", "conf": r["conf"],
                                 "text": " ｜ ".join(vals[1:5])[:300]})
            else:
                c["src"].append({"id": f"{tbl}{rid}", "conf": "❌", "text": "（decomp 中查无此行）"})
    return cps


def load(p: Path):
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save(p: Path, d):
    t = p.with_suffix(".json.tmp")
    t.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    t.replace(p)


def export_md(cps, notes):
    cp_n = notes.get("cp", {})
    md_n = notes.get("mod", {})
    o = ["# GATE 0 · 检查点评审结论", "",
         f"导出 {time.strftime('%Y-%m-%d %H:%M')} · 检查点批注 {len(cp_n)} 条 · "
         f"模块覆盖度判定 {len(md_n)} 个", ""]
    o += ["## 一、模块级：覆盖够不够", "", "| 模块 | 判定 | 用户说 |", "|---|---|---|"]
    for m, n in sorted(md_n.items()):
        o.append(f"| {m} {MODULE_CN.get(m,'')} | "
                 f"{'✅ 够' if n.get('stance')=='enough' else '❌ 缺'} | "
                 f"{n.get('text','').replace(chr(10),' ')} |")
    for st, cn in [("fix", "要改"), ("drop", "删掉"), ("ok", "认可")]:
        ids = [i for i, n in cp_n.items() if n.get("stance") == st]
        if not ids:
            continue
        o += ["", f"## 二、检查点级 · {cn}（{len(ids)} 条）", ""]
        if st == "ok":
            o += ["<details><summary>展开 {} 条</summary>".format(len(ids)), "",
                  " ".join(sorted(ids)), "", "</details>"]
            continue
        o += ["| 检查点 | 用户说 |", "|---|---|"]
        by = {c["id"]: c for c in cps}
        for i in sorted(ids):
            o.append(f"| **{i}** {by.get(i,{}).get('title','')[:50]} | "
                     f"{cp_n[i].get('text','').replace(chr(10),' ')} |")
    todo = [c["id"] for c in cps if c["id"] not in cp_n]
    o += ["", f"## 三、未过目（{len(todo)} 条）", "", " ".join(todo[:400]) or "（无）"]
    return "\n".join(o)


HTML = r"""<!doctype html><meta charset="utf-8"><title>GATE 0 · 检查点评审</title>
<style>
*{box-sizing:border-box}body{margin:0;font:14px/1.65 -apple-system,"PingFang SC",sans-serif;background:#12141a;color:#dfe3ea}
header{position:sticky;top:0;z-index:20;background:#181b23;border-bottom:1px solid #2a2f3a;padding:9px 16px}
h1{font-size:15px;margin:0 0 7px;font-weight:600}
.bar{display:flex;gap:6px;flex-wrap:wrap;align-items:center}
button,select,input{font:inherit;background:#232833;color:#dfe3ea;border:1px solid #333a49;border-radius:6px;padding:4px 10px;cursor:pointer}
button.on{background:#2d6a4f;border-color:#40916c;color:#fff}
input[type=search]{cursor:text;min-width:190px}
.prog{margin-left:auto;color:#9aa4b6;font-variant-numeric:tabular-nums}.prog b{color:#7ee2b8;font-size:16px}
main{padding:0 16px 90px;max-width:1150px}
.modh{position:sticky;top:64px;z-index:10;background:#151922;border:1px solid #2a3140;border-left:4px solid #40916c;border-radius:8px;padding:9px 12px;margin:20px 0 10px}
.modt{font-size:15px;font-weight:700;color:#eaf0f7}
.modsub{font-size:12px;color:#8b95a7;margin-top:1px}
.modq{margin-top:8px;padding-top:8px;border-top:1px dashed #2f3745}
.modq .q{font-size:13px;color:#f0c987;font-weight:600;margin-bottom:5px}
.card{background:#181b23;border:1px solid #262b36;border-left:3px solid #3d4椒;border-radius:8px;padding:9px 12px;margin:0 0 8px}
.card{border-left-color:#39414f}.card.P0{border-left-color:#e05c5c}.card.P1{border-left-color:#d9a441}.card.P2{border-left-color:#4a7fb5}
.card.done{background:#141b17;border-color:#2d6a4f}.card.drop{background:#1d1518;border-color:#6a2d2d;opacity:.65}
.hd{display:flex;gap:7px;align-items:baseline;flex-wrap:wrap}
.cid{font:600 12px ui-monospace,Menlo,monospace;color:#7ee2b8}
.ttl{font-size:14px;color:#f0f3f8;font-weight:600;flex:1;min-width:260px}
.tag{font-size:11px;padding:1px 7px;border-radius:99px;background:#232833;color:#9aa4b6;white-space:nowrap}
.tag.lock{background:#3b2f1a;color:#e5b567}
.ext{font-size:13px;color:#b9c2d0;margin:5px 0 0;padding-left:10px;border-left:2px solid #262b36;white-space:pre-wrap}
.ext b{color:#fff}.ext code{background:#0d0f14;padding:1px 5px;border-radius:4px;color:#9fd5ff;font-size:12px}
.lockline{color:#e0a458}
details.src{margin-top:6px}details.src summary{cursor:pointer;font-size:12px;color:#7c8598}
.srcrow{font-size:12px;color:#a9b3c4;margin:4px 0 0;padding:4px 8px;background:#0f1218;border-radius:5px}
.srcrow b{color:#7ee2b8;font-family:ui-monospace,Menlo,monospace}
.prdq{margin:6px 0 0;background:#101720;border-left:3px solid #40916c;border-radius:5px;padding:7px 10px}
.prdh{font-size:12px;font-weight:700;color:#7ee2b8;margin-bottom:3px}
.prdq pre{margin:0;font:12px/1.6 -apple-system,"PingFang SC",sans-serif;white-space:pre-wrap;color:#c9d1de;max-height:340px;overflow-y:auto}
.act{display:flex;gap:5px;flex-wrap:wrap;align-items:center;margin-top:7px}
.act label{display:flex;align-items:center;gap:4px;font-size:12px;background:#232833;border:1px solid #333a49;border-radius:6px;padding:2px 9px;cursor:pointer}
.act label:has(input:checked){background:#2d6a4f;border-color:#40916c;color:#fff}
.act label.d:has(input:checked){background:#6a2d2d;border-color:#a04040}
textarea{width:100%;margin-top:5px;min-height:30px;background:#12141a;color:#dfe3ea;border:1px solid #333a49;border-radius:6px;padding:5px 8px;font:inherit;resize:vertical}
.saved{color:#7ee2b8;font-size:11px;opacity:0;transition:.3s}.saved.s{opacity:1}
</style>
<header><h1>GATE 0 · 检查点评审 <span id="task" style="color:#7c8598;font-weight:400"></span></h1>
<div class="bar">
  <select id="fmod"></select>
  <select id="fp"><option value="">全部优先级</option><option>P0</option><option>P1</option><option>P2</option></select>
  <button id="flock">只看 🔒 阻塞</button>
  <button id="fnew">只看未过目</button>
  <input type="search" id="q" placeholder="搜索标题 / CP-ID / DBT-092">
  <a href="/api/export" style="color:#7ee2b8;font-size:13px">导出结论 ↓</a>
  <span class="prog">检查点 <b id="pd">0</b>/<span id="pt">0</span> · 模块 <b id="md">0</b>/<span id="mt">0</span></span>
</div></header><main id="app">加载中…</main>
<script>
let CPS=[],N={cp:{},mod:{}},F={mod:'',p:'',lock:false,onlyNew:false,q:''},MC={};
function fmt(s){return (s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;')
 .replace(/\*\*(.+?)\*\*/g,'<b>$1</b>').replace(/`(.+?)`/g,'<code>$1</code>')}
async function boot(){const d=await(await fetch('/api/data')).json();
 CPS=d.cps;N=d.notes;MC=d.mc;document.getElementById('task').textContent=d.task;
 const mods=[...new Set(CPS.map(c=>c.mod))];
 document.getElementById('fmod').innerHTML='<option value="">全部模块（'+CPS.length+' 条）</option>'+
   mods.map(m=>`<option value="${m}">${m} ${MC[m]||''}（${CPS.filter(c=>c.mod===m).length}）</option>`).join('');
 document.getElementById('fmod').onchange=e=>{F.mod=e.target.value;render()};
 document.getElementById('pt').textContent=CPS.length;document.getElementById('mt').textContent=mods.length;
 render()}
function vis(c){if(F.mod&&c.mod!==F.mod)return false;
 if(F.p&&!c.meta.includes(F.p))return false;if(F.lock&&!c.blocked)return false;
 if(F.onlyNew&&N.cp[c.id])return false;
 if(F.q){const s=(c.id+c.title+c.extra.join()+c.refs.join()).toLowerCase();if(!s.includes(F.q.toLowerCase()))return false}
 return true}
function render(){const app=document.getElementById('app');const show=CPS.filter(vis);
 document.getElementById('pd').textContent=Object.keys(N.cp).length;
 document.getElementById('md').textContent=Object.keys(N.mod).length;
 if(!show.length){app.innerHTML='<p style="color:#7c8598;padding-top:20px">没有符合条件的检查点</p>';return}
 let h='',cur=null;
 for(const c of show){
  if(c.mod!==cur){cur=c.mod;const all=CPS.filter(x=>x.mod===cur);
   const done=all.filter(x=>N.cp[x.id]).length;const mn=N.mod[cur]||{};
   h+=`<div class="modh"><div class="modt">${cur} · ${MC[cur]||''}</div>
    <div class="modsub">${all.length} 个检查点（🔒 ${all.filter(x=>x.blocked).length}） · 已过目 ${done}/${all.length}
      · P0 ${all.filter(x=>x.meta.includes('P0')).length} / P1 ${all.filter(x=>x.meta.includes('P1')).length} / P2 ${all.filter(x=>x.meta.includes('P2')).length}</div>
    <div class="modq"><div class="q">▸ 这个模块该测的都在这儿了吗？还缺什么？</div>
      <div class="act">
       <label><input type="radio" name="m-${cur}" value="enough" ${mn.stance==='enough'?'checked':''}>✔ 覆盖够了</label>
       <label class="d"><input type="radio" name="m-${cur}" value="missing" ${mn.stance==='missing'?'checked':''}>➕ 还缺（写在下面）</label>
       <span class="saved" id="msv-${cur}">已存</span></div>
      <textarea id="mt-${cur}" placeholder="缺什么写这里，例：漏了「同一条记录被两个入口并发修改」这种组合场景">${(mn.text||'').replace(/</g,'&lt;')}</textarea>
    </div></div>`}
  const n=N.cp[c.id]||{};const p=(c.meta.match(/P\d/)||[''])[0];
  h+=`<div class="card ${p} ${n.stance?(n.stance==='drop'?'drop':'done'):''}" id="c-${c.id}">
   <div class="hd"><span class="cid">${c.id}</span><span class="ttl">${fmt(c.title)}</span>
    <span class="tag">${c.meta}</span>${c.blocked?'<span class="tag lock">🔒</span>':''}</div>
   ${c.extra.length?`<div class="ext">${c.extra.map(x=>x.includes('🔒')?`<span class="lockline">${fmt(x)}</span>`:fmt(x)).join('\n')}</div>`:''}
   ${c.prd.length?`<details class="src"><summary>← PRD 原文 ${c.prd.map(p=>'§'+p.sec).join(' ')}（${c.prd_name}，点开核对）</summary>
     ${c.prd.map(p=>`<div class="prdq"><div class="prdh">§${p.sec} ${p.title}</div><pre>${(p.text||'').replace(/</g,'&lt;')}</pre></div>`).join('')}</details>`:''}
   ${c.src.length?`<details class="src"><summary>（次级）decomp 转述 ${c.src.length} 行 —— 仅供参考，以上方 PRD 原文为准</summary>
     ${c.src.map(s=>`<div class="srcrow"><b>${s.id}</b> ${s.conf} ${fmt(s.text)}</div>`).join('')}</details>`:''}
   <div class="act">
    <label><input type="radio" name="s-${c.id}" value="ok" ${n.stance==='ok'?'checked':''}>✔ 认可</label>
    <label><input type="radio" name="s-${c.id}" value="fix" ${n.stance==='fix'?'checked':''}>✍ 要改</label>
    <label class="d"><input type="radio" name="s-${c.id}" value="drop" ${n.stance==='drop'?'checked':''}>✕ 删掉</label>
    <span class="saved" id="sv-${c.id}">已存</span></div>
   <textarea id="t-${c.id}" placeholder="选「要改」写怎么改；选「删掉」写为什么（重复 / 超范围 / 不该测）">${(n.text||'').replace(/</g,'&lt;')}</textarea>
  </div>`}
 app.innerHTML=h;
 for(const c of show){document.querySelectorAll(`input[name="s-${c.id}"]`).forEach(i=>i.onchange=()=>put('cp',c.id));
  document.getElementById('t-'+c.id).onblur=()=>put('cp',c.id)}
 for(const m of [...new Set(show.map(c=>c.mod))]){
  document.querySelectorAll(`input[name="m-${m}"]`).forEach(i=>i.onchange=()=>put('mod',m));
  document.getElementById('mt-'+m).onblur=()=>put('mod',m)}}
async function put(kind,id){
 const pre=kind==='cp'?'s-':'m-',tp=kind==='cp'?'t-':'mt-',sp=kind==='cp'?'sv-':'msv-';
 const el=document.querySelector(`input[name="${pre}${id}"]:checked`);
 const b={kind,id,stance:el?el.value:'',text:document.getElementById(tp+id).value};
 await fetch('/api/notes',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b)});
 const box=kind==='cp'?N.cp:N.mod;
 if(b.stance||b.text)box[id]={stance:b.stance,text:b.text};else delete box[id];
 const s=document.getElementById(sp+id);if(s){s.classList.add('s');setTimeout(()=>s.classList.remove('s'),900)}
 document.getElementById('pd').textContent=Object.keys(N.cp).length;
 document.getElementById('md').textContent=Object.keys(N.mod).length;
 if(kind==='cp'){const cd=document.getElementById('c-'+id);
  cd.classList.toggle('done',!!box[id]&&b.stance!=='drop');cd.classList.toggle('drop',b.stance==='drop')}}
document.getElementById('fp').onchange=e=>{F.p=e.target.value;render()};
document.getElementById('flock').onclick=e=>{F.lock=!F.lock;e.target.classList.toggle('on',F.lock);render()};
document.getElementById('fnew').onclick=e=>{F.onlyNew=!F.onlyNew;e.target.classList.toggle('on',F.onlyNew);render()};
document.getElementById('q').oninput=e=>{F.q=e.target.value;render()};
boot()
</script>"""


class H(BaseHTTPRequestHandler):
    td: Path = None
    cps = None

    def _s(self, code, body, ct="application/json; charset=utf-8", ex=None):
        raw = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ct)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (ex or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(raw)

    @property
    def store(self):
        return self.td / "checkpoint_notes.json"

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._s(200, HTML, "text/html; charset=utf-8")
        elif self.path == "/api/data":
            with LOCK:
                H.cps = build(self.td)
                n = load(self.store)
                n.setdefault("cp", {})
                n.setdefault("mod", {})
                self._s(200, json.dumps({"cps": H.cps, "notes": n, "mc": MODULE_CN,
                                         "task": self.td.name}, ensure_ascii=False))
        elif self.path == "/api/export":
            with LOCK:
                md = export_md(H.cps or build(self.td), load(self.store))
            self._s(200, md, "text/markdown; charset=utf-8",
                    {"Content-Disposition": "attachment; filename=gate0_checkpoints.md"})
        else:
            self._s(404, '{"ok":false}')

    def do_POST(self):
        if self.path != "/api/notes":
            return self._s(404, '{"ok":false}')
        try:
            p = json.loads(self.rfile.read(int(self.headers["Content-Length"])).decode())
        except Exception:
            return self._s(400, '{"ok":false}')
        kind = p.get("kind")
        rid = str(p.get("id", ""))[:32]
        st = str(p.get("stance", ""))
        tx = str(p.get("text", ""))[:4000]
        ok = CP_STANCE if kind == "cp" else MOD_STANCE
        if kind not in ("cp", "mod") or not rid or st not in ok:
            return self._s(400, '{"ok":false}')
        with LOCK:
            d = load(self.store)
            d.setdefault("cp", {})
            d.setdefault("mod", {})
            if not st and not tx:
                d[kind].pop(rid, None)
            else:
                d[kind][rid] = {"stance": st, "text": tx, "ts": time.strftime("%Y-%m-%d %H:%M")}
            save(self.store, d)
        self._s(200, '{"ok":true}')

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("用法: python3 tools/checkpoint_review.py artifacts/<task_id> [端口]")
    H.td = Path(sys.argv[1]).resolve()
    cps = build(H.td)
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 8878
    print(f"{H.td.name}: {len(cps)} 条检查点 / "
          f"{len({c['mod'] for c in cps})} 个模块 / 🔒 {sum(c['blocked'] for c in cps)} 条")
    print(f"→ http://127.0.0.1:{port}/   批注存 checkpoint_notes.json（Ctrl+C 停止）")
    ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()
