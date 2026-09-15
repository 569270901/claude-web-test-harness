# -*- coding: utf-8 -*-
"""用例执行台 —— 把 cases.md 变成可执行、可记录的 HTML 控制台。

设计前提（与 GATE 0 评审台同一套）：
  · **cases.md 仍是唯一事实来源**（agent 产物、可 diff、可 git、可追溯）。
    本工具只读它，**从不改它** —— 定稿的用例不该被执行结果污染。
    （用户在 GATE 1 主动改用例走 tools/cases_edit.py，那是另一条有快照有审计的路径。）
  · 执行记录落**只增不改**的台账：
      artifacts/_runs/auto_runs.jsonl    ← pytest 插件写（tools/pytest_case_ledger.py）
      artifacts/_runs/manual_runs.jsonl  ← 本控制台写（人工执行）
  · 一条用例两条泳道：自动化 / 人工。**两边结论不一致时高亮** —— 那是 bug 最好的藏身处
    （要么脚本断言写错了，要么人看漏了）。

为什么要留人工泳道：现阶段不可能把所有用例都交给自动化 ——
一是信心问题，二是时间性场景（跨周期累积/结转这类需要等真实时间推进的），
写成自动化又慢又脆，人工点一遍反而更快更准。

用法（<task> 可以是 task_id，也可以是任意指向任务目录的路径）：
    python3 tools/case_console.py serve <task> [端口]     # 默认 8902
    python3 tools/case_console.py stats <task>
"""
import json
import re
import sys
import threading
import time
from collections import defaultdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gate_review import parse_md, resolve_task_dir  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RUNS = ROOT / "artifacts" / "_runs"
AUTO = RUNS / "auto_runs.jsonl"
MANUAL = RUNS / "manual_runs.jsonl"
LOCK = threading.Lock()
CASE_ID_RE = re.compile(r"^\*{0,2}(TC-[A-Za-z0-9\-]+)\*{0,2}$")

MANUAL_STATUS = {
    "pass":    ("通过", "符合预期"),
    "fail":    ("失败", "与预期不符 —— 记下实际看到什么"),
    "blocked": ("阻塞", "环境/数据/权限导致执行不下去"),
    "skip":    ("跳过", "本轮不测（写明原因）"),
}


# ─────────────────────────── 读取 ───────────────────────────

def task_dir(task_id: str) -> Path:
    return resolve_task_dir(task_id)


def load_cases(task_id: str) -> dict:
    """从 cases.md 抽出用例。只读，不改。"""
    f = task_dir(task_id) / "cases.md"
    doc = parse_md(f)
    cases, groups = [], []
    for sec in doc["sections"]:
        hdr = sec["header"] or []
        if "ID" not in hdr:
            continue
        idx = {h: i for i, h in enumerate(hdr)}
        got = []
        for r in sec["rows"]:
            c = r["cells"]
            if len(c) <= idx["ID"]:
                continue
            m = CASE_ID_RE.match(c[idx["ID"]].strip())
            if not m:
                continue
            g = lambda k: c[idx[k]].strip() if k in idx and len(c) > idx[k] else ""  # noqa: E731
            pr = g("page_ref")
            got.append({
                "id": m.group(1),
                "group": sec["title"],
                "priority": g("优先级").replace("*", ""),
                "exec": g("exec"),
                "title": g("测试点"),
                "pre": g("前置"),
                "steps": g("步骤"),
                "expect": g("期望"),
                "page_ref": pr,
                "map_gap": "⚠️待补" in pr,
                "reuse": [x for x in re.findall(r"([\w/]+\.py(?:::\w+)?)", pr + " " + g("步骤"))],
                "derived_from": g("derived_from"),
                "line_no": r["line_no"],
            })
        if got:
            groups.append({"title": sec["title"], "count": len(got)})
            cases += got
    return {"frontmatter": doc["frontmatter"], "cases": cases, "groups": groups}


def read_jsonl(p: Path) -> list[dict]:
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


def collect_runs(case_ids: set[str]) -> dict:
    """把两个台账按用例 ID 归拢，各自按时间倒序。"""
    auto, manual = defaultdict(list), defaultdict(list)
    for r in read_jsonl(AUTO):
        for cid in (r.get("case_ids") or []):
            if cid in case_ids:
                auto[cid].append(r)
    for r in read_jsonl(MANUAL):
        cid = r.get("case_id")
        if cid in case_ids:
            manual[cid].append(r)
    for d in (auto, manual):
        for k in d:
            d[k].sort(key=lambda x: x.get("ts", ""), reverse=True)
    return {"auto": auto, "manual": manual}


def build(task_id: str) -> dict:
    data = load_cases(task_id)
    ids = {c["id"] for c in data["cases"]}
    runs = collect_runs(ids)
    for c in data["cases"]:
        a = runs["auto"].get(c["id"], [])
        m = runs["manual"].get(c["id"], [])
        c["auto_runs"] = a[:6]
        c["manual_runs"] = m[:6]
        c["auto_status"] = a[0]["status"] if a else None
        c["manual_status"] = m[0]["status"] if m else None
        # 分歧：一边通过、另一边失败 —— 最值得看的格子
        c["divergent"] = bool(
            c["auto_status"] and c["manual_status"]
            and (c["auto_status"] == "passed") != (c["manual_status"] == "pass")
            and c["manual_status"] in ("pass", "fail")
            and c["auto_status"] in ("passed", "failed", "error")
        )
    data["task_id"] = task_id
    data["manual_status_meta"] = MANUAL_STATUS
    return data


def append_manual(rec: dict) -> None:
    with LOCK:
        RUNS.mkdir(parents=True, exist_ok=True)
        with MANUAL.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


# ─────────────────────────── stats ───────────────────────────

def cmd_stats(task_id: str) -> None:
    d = build(task_id)
    cs = d["cases"]
    def n(f): return sum(1 for c in cs if f(c))
    print(f"用例 {len(cs)} 条（{', '.join(g['title'].split('.')[0]+':'+str(g['count']) for g in d['groups'])}）\n")
    print(f"  自动化：通过 {n(lambda c: c['auto_status']=='passed')}"
          f" / 失败 {n(lambda c: c['auto_status'] in ('failed','error'))}"
          f" / 未跑 {n(lambda c: not c['auto_status'])}")
    print(f"  人  工：通过 {n(lambda c: c['manual_status']=='pass')}"
          f" / 失败 {n(lambda c: c['manual_status']=='fail')}"
          f" / 阻塞 {n(lambda c: c['manual_status']=='blocked')}"
          f" / 未执行 {n(lambda c: not c['manual_status'])}")
    print(f"  两边分歧：{n(lambda c: c['divergent'])} 条  ← 优先看这些")
    print(f"  卡在地图缺口：{n(lambda c: c['map_gap'])} 条（自动化跑不了，先走人工）")
    cov = n(lambda c: c["auto_status"] == "passed" or c["manual_status"] == "pass")
    print(f"\n  已验证（任一泳道通过）：{cov}/{len(cs)} = {cov/max(len(cs),1):.0%}")


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
        elif self.path.startswith("/api/cases"):
            self._send(200, json.dumps(build(self.task_id), ensure_ascii=False))
        else:
            self._send(404, json.dumps({"error": "not found"}))

    def do_POST(self):
        if self.path != "/api/manual":
            return self._send(404, json.dumps({"error": "not found"}))
        n = int(self.headers.get("Content-Length", 0))
        try:
            p = json.loads(self.rfile.read(n) or b"{}")
        except Exception as e:
            return self._send(400, json.dumps({"error": str(e)}))
        if not p.get("case_id") or p.get("status") not in MANUAL_STATUS:
            return self._send(400, json.dumps({"error": "case_id 与合法 status 必填"}))
        append_manual({
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "case_id": p["case_id"],
            "status": p["status"],
            "note": (p.get("note") or "")[:2000],
            "actual": (p.get("actual") or "")[:2000],
            "by": p.get("by") or "user",
            "task_id": self.task_id,
        })
        self._send(200, json.dumps({"ok": True}))

    def log_message(self, *a):
        pass


PAGE = r"""<!doctype html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>用例执行台</title><style>
:root{--bg:#f4f6f7;--surf:#fff;--surf2:#e9eef1;--ink:#121b23;--ink2:#47555f;--ink3:#6d7c86;
--rule:#d2dae0;--ok:#0f6f5c;--bad:#a03127;--warn:#8f6304;--info:#1c5f86;--gap:#6b5aa6}
@media(prefers-color-scheme:dark){:root{--bg:#0d1319;--surf:#151d24;--surf2:#1b252d;--ink:#e5ecf1;
--ink2:#9aaab5;--ink3:#788994;--rule:#2a3943;--ok:#46b39b;--bad:#e0796d;--warn:#dba62c;--info:#5fa8d3;--gap:#a693e0}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.65 -apple-system,"PingFang SC","Microsoft YaHei",sans-serif}
.mono{font-family:"IBM Plex Mono",ui-monospace,Menlo,Consolas,monospace}
header{position:sticky;top:0;z-index:9;background:var(--surf);border-bottom:1px solid var(--rule);padding:10px 20px}
.row1{display:flex;align-items:center;gap:14px;flex-wrap:wrap}
h1{font-size:15px;margin:0;font-weight:600}
.kpi{display:flex;gap:16px;flex-wrap:wrap;margin-left:auto;font-size:12px}
.kpi b{font-variant-numeric:tabular-nums}
.fil{display:flex;gap:6px;flex-wrap:wrap;margin-top:9px}
button{font:inherit;cursor:pointer;border:1px solid var(--rule);background:var(--surf);color:var(--ink);
border-radius:5px;padding:4px 11px;font-size:13px}
button:hover{border-color:var(--ink3)}button.on{background:var(--ink);color:var(--bg);border-color:var(--ink)}
main{max-width:1240px;margin:0 auto;padding:18px 20px 60px}
.case{background:var(--surf);border:1px solid var(--rule);border-radius:7px;margin-bottom:10px;overflow:hidden}
.case.div{border-color:var(--warn);box-shadow:inset 3px 0 0 var(--warn)}
.hd{display:flex;align-items:center;gap:10px;padding:11px 14px;cursor:pointer;flex-wrap:wrap}
.hd:hover{background:var(--surf2)}
.cid{font-family:"IBM Plex Mono",monospace;font-size:12.5px;color:var(--ink2);flex:none}
.ttl{flex:1;min-width:240px}
.pill{font-size:11px;padding:1.5px 7px;border-radius:3px;border:1px solid currentColor;flex:none;white-space:nowrap}
.p-P0{color:var(--bad)}.p-P1{color:var(--warn)}.p-P2{color:var(--ink3)}
.s-passed,.s-pass{color:var(--ok)}.s-failed,.s-fail,.s-error{color:var(--bad)}
.s-blocked{color:var(--warn)}.s-skip,.s-skipped{color:var(--ink3)}.s-none{color:var(--ink3);opacity:.6}
.gap{color:var(--gap)}
.bd{border-top:1px solid var(--rule);padding:14px;display:none}
.case.open .bd{display:block}
.meta{display:grid;grid-template-columns:74px 1fr;gap:7px 12px;font-size:13px;margin-bottom:14px}
.meta dt{color:var(--ink3);font-size:11.5px;padding-top:2px}
.meta dd{margin:0}
.meta code{background:var(--surf2);padding:1px 5px;border-radius:3px;font-size:12px}
.lanes{display:grid;grid-template-columns:1fr 1fr;gap:12px}
@media(max-width:820px){.lanes{grid-template-columns:1fr}}
.lane{border:1px solid var(--rule);border-radius:6px;padding:11px 13px;background:var(--bg)}
.lane h4{margin:0 0 9px;font-size:12px;color:var(--ink3);letter-spacing:.06em;font-weight:500;
display:flex;justify-content:space-between;align-items:center}
.run{border-top:1px dashed var(--rule);padding:7px 0;font-size:12.5px}
.run:first-of-type{border-top:none}
.run .t{color:var(--ink3);font-size:11px;font-family:"IBM Plex Mono",monospace}
.run pre{margin:4px 0 0;white-space:pre-wrap;word-break:break-word;font-size:11.5px;
background:var(--surf2);padding:6px 8px;border-radius:4px;max-height:120px;overflow:auto}
.empty{color:var(--ink3);font-size:12.5px;padding:6px 0}
.mbtns{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:8px}
textarea{width:100%;font:inherit;font-size:13px;padding:7px 9px;border:1px solid var(--rule);
border-radius:5px;background:var(--surf);color:var(--ink);margin-bottom:7px;min-height:44px;resize:vertical}
.hint{color:var(--ink3);font-size:11.5px;margin:0 0 8px}
.divmsg{background:var(--surf2);border-left:3px solid var(--warn);padding:8px 11px;
font-size:12.5px;margin-bottom:12px;border-radius:0 4px 4px 0}
.cmd{background:var(--surf2);border-radius:5px;padding:8px 10px;font-family:"IBM Plex Mono",monospace;
font-size:11.5px;overflow-x:auto;white-space:pre;margin:0}
</style></head><body>
<header>
  <div class="row1">
    <h1>用例执行台</h1><span class="mono" id="task" style="font-size:12px;color:var(--ink3)"></span>
    <div class="kpi" id="kpi"></div>
  </div>
  <div class="fil" id="fil"></div>
</header>
<main id="app">加载中…</main>
<script>
let D=null,F='all',OPEN={};
const $=s=>document.querySelector(s);
const esc=s=>(s||'').replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
const md=s=>esc(s).replace(/\*\*([^*]+)\*\*/g,'<b>$1</b>').replace(/`([^`]+)`/g,'<code>$1</code>');
const AS={passed:'通过',failed:'失败',error:'错误',skipped:'跳过'};
const MS={pass:'通过',fail:'失败',blocked:'阻塞',skip:'跳过'};

async function boot(){D=await (await fetch('/api/cases')).json();render()}

function pass(c){
  if(F==='all')return true;
  if(F==='undone')return !c.auto_status&&!c.manual_status;
  if(F==='div')return c.divergent;
  if(F==='bad')return ['failed','error'].includes(c.auto_status)||c.manual_status==='fail';
  if(F==='gap')return c.map_gap;
  if(F==='ok')return c.auto_status==='passed'||c.manual_status==='pass';
  return true;
}
function render(){
  const cs=D.cases,n=f=>cs.filter(f).length;
  $('#task').textContent=D.task_id;
  $('#kpi').innerHTML=
    `<span>自动 <b class="s-passed">${n(c=>c.auto_status==='passed')}</b> 过 / <b class="s-failed">${n(c=>['failed','error'].includes(c.auto_status))}</b> 败 / <b>${n(c=>!c.auto_status)}</b> 未跑</span>`+
    `<span>人工 <b class="s-pass">${n(c=>c.manual_status==='pass')}</b> 过 / <b class="s-fail">${n(c=>c.manual_status==='fail')}</b> 败 / <b>${n(c=>!c.manual_status)}</b> 未执行</span>`+
    `<span>分歧 <b class="s-blocked">${n(c=>c.divergent)}</b></span>`+
    `<span>已验证 <b>${n(c=>c.auto_status==='passed'||c.manual_status==='pass')}/${cs.length}</b></span>`;
  $('#fil').innerHTML=[['all','全部',cs.length],['undone','未执行',n(c=>!c.auto_status&&!c.manual_status)],
    ['div','两边分歧',n(c=>c.divergent)],['bad','有失败',n(c=>['failed','error'].includes(c.auto_status)||c.manual_status==='fail')],
    ['gap','卡地图缺口',n(c=>c.map_gap)],['ok','已验证',n(c=>c.auto_status==='passed'||c.manual_status==='pass')]]
    .map(([k,l,v])=>`<button class="${F===k?'on':''}" onclick="setF('${k}')">${l} ${v}</button>`).join('');
  $('#app').innerHTML=cs.filter(pass).map(card).join('')||'<div class="case"><div class="hd">这个筛选下没有用例。</div></div>';
}
function setF(f){F=f;render()}
function tog(id){OPEN[id]=!OPEN[id];render()}

function badge(kind,st){
  const lab=kind==='auto'?(AS[st]||'未跑'):(MS[st]||'未执行');
  return `<span class="pill s-${st||'none'}">${kind==='auto'?'自动':'人工'} ${lab}</span>`;
}
function runsHtml(rs,kind){
  if(!rs.length)return '<div class="empty">暂无记录</div>';
  return rs.map(r=>{
    const st=r.status;
    const lab=kind==='auto'?(AS[st]||st):(MS[st]||st);
    let h=`<div class="run"><span class="pill s-${st}">${lab}</span> <span class="t">${esc(r.ts||'')}</span>`;
    if(kind==='auto'){
      h+=` <span class="t">${r.duration!=null?r.duration+'s':''}</span>`;
      if(r.nodeid)h+=`<div class="t" style="margin-top:3px">${esc(r.nodeid)}</div>`;
      if(r.error)h+=`<pre>${esc(r.error)}</pre>`;
      if(r.artifacts&&r.artifacts.length)h+=`<div class="t" style="margin-top:4px">取证：${r.artifacts.map(esc).join('　')}</div>`;
    }else{
      if(r.actual)h+=`<div style="margin-top:4px"><b>实际看到：</b>${esc(r.actual)}</div>`;
      if(r.note)h+=`<div style="margin-top:3px;color:var(--ink2)">${esc(r.note)}</div>`;
    }
    return h+'</div>';
  }).join('');
}
function card(c){
  const op=OPEN[c.id]?' open':'',dv=c.divergent?' div':'';
  let h=`<div class="case${op}${dv}"><div class="hd" onclick="tog('${c.id}')">`+
    `<span class="cid">${c.id}</span>`+
    `<span class="pill p-${c.priority}">${c.priority}</span>`+
    `<span class="ttl">${md(c.title)}</span>`+
    (c.map_gap?'<span class="pill gap">缺地图</span>':'')+
    badge('auto',c.auto_status)+badge('manual',c.manual_status)+'</div>';
  if(!OPEN[c.id])return h+'</div>';
  h+='<div class="bd">';
  if(c.divergent)h+=`<div class="divmsg"><b>两边结论不一致。</b>自动化说「${AS[c.auto_status]||c.auto_status}」，`+
    `人工说「${MS[c.manual_status]||c.manual_status}」——要么脚本断言写错了，要么人看漏了。先查这条。</div>`;
  h+='<dl class="meta">'+
     `<dt>前置</dt><dd>${md(c.pre)||'—'}</dd>`+
     `<dt>步骤</dt><dd>${md(c.steps)||'—'}</dd>`+
     `<dt>期望</dt><dd>${md(c.expect)||'—'}</dd>`+
     `<dt>page_ref</dt><dd>${md(c.page_ref)||'—'}</dd>`+
     `<dt>溯源</dt><dd class="mono" style="font-size:11.5px">${esc(c.derived_from)}　·　cases.md:${c.line_no}</dd></dl>`;
  h+='<div class="lanes">';
  // 自动化泳道
  h+='<div class="lane"><h4><span>自动化执行</span><span class="t mono">auto_runs.jsonl</span></h4>';
  if(c.map_gap)h+='<p class="hint">⚠️ 这条卡在 page_map 缺口上，探索补完前跑不了自动化——先走人工。</p>';
  h+=`<p class="hint">跑法（结果自动回填到这里）：</p><pre class="cmd">python -m pytest -p tools.pytest_case_ledger \\
  -k "${esc(c.id)}" -v --override-ini="addopts="</pre>`;
  h+='<div style="margin-top:9px">'+runsHtml(c.auto_runs,'auto')+'</div></div>';
  // 人工泳道
  h+='<div class="lane"><h4><span>人工执行</span><span class="t mono">manual_runs.jsonl</span></h4>'+
     '<div class="mbtns">'+Object.entries(MS).map(([k,v])=>
       `<button onclick="mark('${c.id}','${k}')">${v}</button>`).join('')+'</div>'+
     `<textarea id="ac-${c.id}" placeholder="实际看到什么（判失败/阻塞时必填，逐字抄）"></textarea>`+
     `<textarea id="nt-${c.id}" placeholder="备注（可选）"></textarea>`+
     '<div style="margin-top:4px">'+runsHtml(c.manual_runs,'manual')+'</div></div>';
  return h+'</div></div>';
}
async function mark(id,st){
  const actual=$('#ac-'+id).value.trim(),note=$('#nt-'+id).value.trim();
  if((st==='fail'||st==='blocked')&&!actual){alert('判失败/阻塞时请填「实际看到什么」');return}
  await fetch('/api/manual',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({case_id:id,status:st,actual,note})});
  D=await (await fetch('/api/cases')).json();render();
}
boot();
</script></body></html>"""


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    cmd, task = sys.argv[1], sys.argv[2]
    if cmd == "stats":
        cmd_stats(task)
    elif cmd == "serve":
        port = int(sys.argv[3]) if len(sys.argv) > 3 else 8902
        Handler.task_id = task
        d = build(task)
        print(f"用例执行台：http://127.0.0.1:{port}/\n"
              f"用例 {len(d['cases'])} 条 · 自动化台账 {AUTO.relative_to(ROOT)} · 人工台账 {MANUAL.relative_to(ROOT)}\n"
              f"Ctrl-C 结束")
        ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
    else:
        print(f"未知命令 {cmd}")
