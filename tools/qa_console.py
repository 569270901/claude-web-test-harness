# -*- coding: utf-8 -*-
"""QA 控制台 —— **一个端口**，版本为锚，需求可切换。

为什么合并：原先 GATE 0 评审台和用例执行台各起一个端口，一个版本十个需求
就要开二十个端口，荒谬。改成单端口 + 三级导航：

    版本（v2 / v1 / 未归版）→ 需求（task）→ 视图（评审 / 执行）

数据来源一律只读，写入只落两类台账（都只增不改）：
    artifacts/<task>/gate0_verdicts.json     ← GATE 0 裁决
    artifacts/_runs/{auto,manual}_runs.jsonl ← 执行记录
（用户在 GATE 1 改用例是第三条写路径，走 tools/cases_edit.py，有快照有审计。）

版本字段来自 `artifacts/<task>/state.md` frontmatter 的 `version:`（orchestrator 维护）。
没有该字段的历史任务归入「未归版」—— **不做推断**，任务名里的 v1/v2 多是功能版本号
而不是产品版本号。

用法：
    python3 tools/qa_console.py serve [端口]     # 默认 8900
    python3 tools/qa_console.py index            # 命令行看一眼索引
"""
import json
import re
import sys
import time
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
ROOT = HERE.parent

from gate_review import paths, load_verdicts, save_verdicts          # noqa: E402,F401
from gate_review_ui import build_cards                               # noqa: E402
import case_console                                                  # noqa: E402
import cases_edit                                                    # noqa: E402

UNVERSIONED = "未归版"


# ─────────────────────────── 索引 ───────────────────────────

def _fm(path: Path) -> dict:
    if not path.exists():
        return {}
    t = path.read_text(encoding="utf-8", errors="ignore")
    if not t.startswith("---"):
        return {}
    body = t.split("---", 2)[1]
    out = {}
    for line in body.splitlines():
        m = re.match(r"^([a-z_]+):\s*(.*)$", line)
        if m:
            out[m.group(1)] = m.group(2).split("#")[0].strip()
    return out


_GENERIC_H1 = ("测试用例", "结构化解构层")


def _title(d: Path) -> str:
    # 优先用产物的 H1；还没跑过产物的任务只有 state.md，取它「# 任务」段的加粗标题
    for f in ("cases.md", "decomp.md"):
        p = d / f
        if not p.exists():
            continue
        for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.startswith("# "):
                raw = line[2:].strip()
                t = re.sub(r"^(测试用例|结构化解构层)\s*[—\-–]+\s*", "", raw)
                # agent 忘了写副标题（H1 只剩泛用模板词本身）——不能就地返回，
                # 否则多个任务会撞出同一个看不出区别的标题；退回 state.md 拿真实任务名
                if t.strip() not in _GENERIC_H1:
                    return t[:60]
                break
    st = d / "state.md"
    if st.exists():
        lines = st.read_text(encoding="utf-8", errors="ignore").splitlines()
        for i, l in enumerate(lines):
            if l.strip() == "# 任务":
                for nx in lines[i + 1:i + 6]:
                    m = re.match(r"^\*\*(.+?)\*\*\s*$", nx.strip())
                    if m:
                        return m.group(1)[:60]
                break
    return d.name


def discover() -> dict:
    """扫 artifacts/ 得到 版本 → 需求 → 可用视图。只读。"""
    groups: "OrderedDict[str, list]" = OrderedDict()
    for d in sorted(ROOT.glob("artifacts/20*"), reverse=True):
        if not d.is_dir():
            continue
        state, decomp, cases = d / "state.md", d / "decomp.md", d / "cases.md"
        if not (state.exists() or decomp.exists() or cases.exists()):
            continue
        sfm, dfm, cfm = _fm(state), _fm(decomp), _fm(cases)
        views, badges = [], []

        if decomp.exists():
            views.append("gate0")
            try:
                st = dfm.get("status", "")
                n_cards = len(build_cards(d.name)["cards"]) if st != "" else 0
                answered = len(load_verdicts(d.name))
                if st == "pending_review":
                    badges.append({"k": "gate", "t": f"GATE 0 待审 {answered}/{n_cards}"})
                elif n_cards:
                    badges.append({"k": "ok", "t": f"GATE 0 已结 {answered}/{n_cards}"})
            except Exception as e:
                badges.append({"k": "warn", "t": f"decomp 解析失败: {type(e).__name__}"})

        if cases.exists():
            views.append("cases")
            try:
                cc = case_console.build(d.name)
                cs = cc["cases"]
                ok = sum(1 for c in cs if c["auto_status"] in ("passed", "xfailed") or c["manual_status"] == "pass")
                dv = sum(1 for c in cs if c["divergent"])
                badges.append({"k": "run", "t": f"执行 {ok}/{len(cs)}"})
                if dv:
                    badges.append({"k": "warn", "t": f"分歧 {dv}"})
                if cfm.get("status") == "pending_review":
                    badges.append({"k": "gate", "t": "GATE 1 待审"})
            except Exception as e:
                badges.append({"k": "warn", "t": f"cases 解析失败: {type(e).__name__}"})

        ver = sfm.get("version") or dfm.get("version") or UNVERSIONED
        groups.setdefault(ver, []).append({
            "task_id": d.name,
            "title": _title(d),
            "status": sfm.get("status", "—"),
            "current_step": sfm.get("current_step", ""),
            "views": views,
            "badges": badges,
        })
    # 有版本的排前面，未归版垫底
    ordered = OrderedDict((k, v) for k, v in groups.items() if k != UNVERSIONED)
    if UNVERSIONED in groups:
        ordered[UNVERSIONED] = groups[UNVERSIONED]
    return {"versions": [{"version": k, "tasks": v} for k, v in ordered.items()],
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S")}


def cmd_index() -> None:
    d = discover()
    for g in d["versions"]:
        print(f"\n▌{g['version']}")
        for t in g["tasks"]:
            b = " ".join(f"[{x['t']}]" for x in t["badges"]) or "—"
            print(f"   {t['task_id']:<42}{t['title'][:34]:<36}{b}")
    print(f"\n共 {sum(len(g['tasks']) for g in d['versions'])} 个需求，"
          f"{len(d['versions'])} 个版本分组")


# ─────────────────────────── server ───────────────────────────

class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        raw = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False), "application/json; charset=utf-8")

    def do_GET(self):
        p = urlparse(self.path).path
        try:
            if p == "/":
                return self._send(200, PAGE, "text/html; charset=utf-8")
            if p == "/api/index":
                return self._json(discover())
            m = re.match(r"^/api/(gate0|cases)/(.+)$", p)
            if m:
                kind, task = m.group(1), m.group(2)
                return self._json(build_cards(task) if kind == "gate0" else case_console.build(task))
            m = re.match(r"^/api/verdicts/(.+)$", p)
            if m:
                return self._json(load_verdicts(m.group(1)))
            # 设计图缩略图（决策卡「需求原文」区引用 img_NN 时用）。只放行 ui_design/ 下的图片，
            # 文件名只认 [\w.-]，防止 ../ 跳出任务目录
            m = re.match(r"^/asset/([^/]+)/ui_design/([\w.\-]+)$", p)
            if m:
                f = paths(m.group(1))["dir"] / "ui_design" / m.group(2)
                ctype = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                         ".webp": "image/webp", ".gif": "image/gif"}.get(f.suffix.lower())
                if ctype and f.is_file():
                    return self._send(200, f.read_bytes(), ctype)
                return self._json({"error": "not found"}, 404)
        except FileNotFoundError as e:
            return self._json({"error": f"文件不存在: {e}"}, 404)
        except Exception as e:
            return self._json({"error": f"{type(e).__name__}: {e}"}, 500)
        self._json({"error": "not found"}, 404)

    def do_POST(self):
        p = urlparse(self.path).path
        n = int(self.headers.get("Content-Length", 0))
        try:
            payload = json.loads(self.rfile.read(n) or b"{}")
        except Exception as e:
            return self._json({"error": str(e)}, 400)

        m = re.match(r"^/api/verdicts/(.+)$", p)
        if m:
            task, cid = m.group(1), payload.get("cid")
            if not cid:
                return self._json({"error": "cid required"}, 400)
            data = load_verdicts(task)
            if payload.get("clear"):
                data.pop(cid, None)
            else:
                data[cid] = {k: payload.get(k, "") for k in ("choice", "value", "note")}
                data[cid]["answered_at"] = payload.get("answered_at", "")
                if payload.get("rowvals"):
                    data[cid]["rowvals"] = payload["rowvals"]
            save_verdicts(task, data)
            return self._json({"ok": True, "count": len(data)})

        m = re.match(r"^/api/case/(.+)$", p)
        if m:
            task, op = m.group(1), payload.get("op")
            try:
                if op == "update":
                    r = cases_edit.update(task, payload["case_id"], payload.get("changes") or {})
                elif op == "create":
                    r = cases_edit.create(task, payload.get("cells") or {})
                elif op == "delete":
                    r = cases_edit.delete(task, payload["case_id"], payload.get("reason", ""))
                elif op == "confirm":
                    r = cases_edit.confirm(task)
                else:
                    return self._json({"error": f"未知 op: {op}"}, 400)
                return self._json(r)
            except Exception as e:
                return self._json({"error": f"{type(e).__name__}: {e}"}, 400)

        m = re.match(r"^/api/manual/(.+)$", p)
        if m:
            task = m.group(1)
            if not payload.get("case_id") or payload.get("status") not in case_console.MANUAL_STATUS:
                return self._json({"error": "case_id 与合法 status 必填"}, 400)
            case_console.append_manual({
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "case_id": payload["case_id"],
                "status": payload["status"],
                "note": (payload.get("note") or "")[:2000],
                "actual": (payload.get("actual") or "")[:2000],
                "by": payload.get("by") or "user",
                "task_id": task,
            })
            return self._json({"ok": True})

        self._json({"error": "not found"}, 404)

    def log_message(self, *a):
        pass


PAGE = r"""<!doctype html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>QA 控制台</title><style>
:root{--bg:#f4f6f7;--surf:#fff;--surf2:#e9eef1;--ink:#121b23;--ink2:#47555f;--ink3:#6d7c86;
--rule:#d2dae0;--ok:#0f6f5c;--bad:#a03127;--warn:#8f6304;--gate:#9c6a05;--gap:#6b5aa6;--info:#1c5f86}
@media(prefers-color-scheme:dark){:root{--bg:#0d1319;--surf:#151d24;--surf2:#1b252d;--ink:#e5ecf1;
--ink2:#9aaab5;--ink3:#788994;--rule:#2a3943;--ok:#46b39b;--bad:#e0796d;--warn:#dba62c;--gate:#dca62c;--gap:#a693e0;--info:#5fa8d3}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.65 -apple-system,"PingFang SC","Microsoft YaHei",sans-serif}
.mono{font-family:"IBM Plex Mono",ui-monospace,Menlo,Consolas,monospace}
header{position:sticky;top:0;z-index:9;background:var(--surf);border-bottom:1px solid var(--rule);padding:9px 20px}
.nav{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.nav h1{font-size:14.5px;margin:0;font-weight:600;cursor:pointer}
.nav h1:hover{color:var(--info)}
select,button{font:inherit;font-size:13px;cursor:pointer;border:1px solid var(--rule);background:var(--surf);
color:var(--ink);border-radius:5px;padding:4px 9px}
button:hover,select:hover{border-color:var(--ink3)}
button.on{background:var(--ink);color:var(--bg);border-color:var(--ink)}
.sep{color:var(--ink3)}
.kpi{display:flex;gap:14px;flex-wrap:wrap;margin-left:auto;font-size:12px;align-items:center}
.helpbtn{font-size:12px;padding:4px 10px}
.vlab{font-size:12px;color:var(--ink2);margin:4px 0 6px}
textarea.ans{min-height:64px}
.mask{position:fixed;inset:0;background:rgba(20,20,20,.45);display:none;align-items:flex-start;justify-content:center;z-index:50;padding:48px 16px;overflow:auto}
.mask.on{display:flex}
.dlg{background:var(--surf);border-radius:10px;max-width:720px;width:100%;padding:24px 28px;box-shadow:0 12px 40px rgba(0,0,0,.25);line-height:1.7;font-size:14px}
.dlg h3{margin:0 0 6px;font-size:18px}
.dlg h4{margin:18px 0 6px;font-size:15px}
.dlg .lead{color:var(--ink2);margin:0 0 12px}
.dlg table{width:100%;border-collapse:collapse;font-size:13px;margin:6px 0}
.dlg td,.dlg th{border:1px solid var(--rule);padding:8px 10px;vertical-align:top;text-align:left}
.dlg th{background:var(--surf2);font-weight:600;white-space:nowrap}
.dlg td:first-child{white-space:nowrap;font-weight:600}
.dlg ol{padding-left:20px;margin:6px 0}
.dlg .x{float:right}
.kpi b{font-variant-numeric:tabular-nums}
.fil{display:flex;gap:6px;flex-wrap:wrap;margin-top:8px}
main{max-width:1240px;margin:0 auto;padding:18px 20px 60px}
.pill{font-size:11px;padding:1.5px 7px;border-radius:3px;border:1px solid currentColor;white-space:nowrap;flex:none}
.k-gate{color:var(--gate)}.k-ok{color:var(--ok)}.k-run{color:var(--info)}.k-warn{color:var(--warn)}
/* 索引 */
.vgrp{margin-bottom:26px}
.vgrp h2{font-size:13px;margin:0 0 9px;color:var(--ink3);letter-spacing:.08em;font-weight:500;
border-bottom:1px solid var(--rule);padding-bottom:6px}
.tk{background:var(--surf);border:1px solid var(--rule);border-radius:7px;padding:12px 14px;margin-bottom:8px;
display:flex;align-items:center;gap:11px;flex-wrap:wrap}
.tk .tt{flex:1;min-width:220px}
.tk .tid{font-family:"IBM Plex Mono",monospace;font-size:11.5px;color:var(--ink3)}
/* 决策卡 */
.card{background:var(--surf);border:1px solid var(--rule);border-radius:8px;padding:20px 22px;margin-bottom:16px}
.q{font-size:17px;line-height:1.6;margin:2px 0 8px;font-weight:500}
.q code,.prdr code{background:var(--surf2);padding:1px 6px;border-radius:3px}
.hint{color:var(--ink2);font-size:13px;margin:0 0 16px}
.prd{border:1px solid var(--rule);border-radius:6px;padding:12px 14px;margin-bottom:14px;background:var(--bg)}
.prdt{font-size:11px;letter-spacing:.1em;color:var(--ink3);margin-bottom:9px}
.prdb{padding:8px 10px;border-radius:4px;margin-bottom:6px;background:var(--surf)}
.prdb.lk{box-shadow:inset 0 0 0 1px var(--gate)}
.prdh{display:flex;gap:10px;font-size:11px;color:var(--ink3);margin-bottom:3px}
.prdl{font-size:12px;color:var(--ink2);margin-bottom:4px}
.bgd{font-size:14px;line-height:1.7;color:var(--ink);background:var(--surf2);border-radius:6px;padding:10px 14px;margin:0 0 14px}
.srcs{display:grid;gap:10px;margin-bottom:14px}
.srcs.vs{grid-template-columns:repeat(auto-fit,minmax(260px,1fr))}
.src{border:1px solid var(--rule);border-radius:6px;padding:10px 12px;background:var(--bg)}
.src .sh{display:flex;justify-content:space-between;gap:8px;font-size:12px;color:var(--ink3);margin-bottom:6px}
.src .sh b{color:var(--ink);font-weight:600}
.src pre{white-space:pre-wrap;word-break:break-word;margin:0;font:13px/1.65 inherit;color:var(--ink)}
.thumbs{display:flex;gap:8px;flex-wrap:wrap;margin-top:8px}
.thumbs a{display:block;border:1px solid var(--rule);border-radius:4px;overflow:hidden;background:var(--surf)}
.thumbs img{display:block;max-width:220px;max-height:150px;object-fit:contain}
.thumbs span{display:block;font-size:11px;color:var(--ink3);padding:2px 6px}
.opt em.dflt{display:inline-block;width:auto;margin:0 0 0 8px;vertical-align:1px;font-size:11px;padding:1px 6px;border-radius:3px;
background:color-mix(in srgb,var(--gate) 16%,transparent);color:var(--ink2);font-style:normal}
.prdr{margin:0;font-family:"IBM Plex Mono",monospace;font-size:13px;white-space:pre-wrap;word-break:break-word}
details summary{cursor:pointer;color:var(--ink3);font-size:12px;padding:4px 0}
.ev{background:var(--surf2);border-radius:6px;padding:12px 14px;margin:8px 0}
.ev div{margin-bottom:7px;font-size:13px;word-break:break-word}
.ev b{color:var(--ink3);font-weight:500;font-size:11px}
.evg+.evg{border-top:1px dashed var(--rule);padding-top:9px;margin-top:4px}
.evh{font-size:12px;font-weight:600;color:var(--ink2);margin-bottom:6px}
.ref{background:color-mix(in srgb,var(--gate) 10%,transparent);border-radius:3px;padding:0 2px}
.opts{display:flex;flex-direction:column;gap:8px;margin:14px 0}
.opt{display:flex;gap:10px;text-align:left;padding:11px 14px;width:100%;align-items:flex-start}
.opt.sel{border-color:var(--ok);box-shadow:inset 0 0 0 1px var(--ok)}
.opt kbd{border:1px solid var(--rule);border-radius:3px;padding:0 5px;font-size:11px;color:var(--ink3);flex:none}
.opt em{color:var(--ink3);font-style:normal;font-size:12px;display:block}
input,textarea{width:100%;font:inherit;font-size:13px;padding:8px 10px;border:1px solid var(--rule);
border-radius:5px;background:var(--bg);color:var(--ink);margin-bottom:8px}
textarea{min-height:46px;resize:vertical}
/* 执行台 */
.case{background:var(--surf);border:1px solid var(--rule);border-radius:7px;margin-bottom:10px;overflow:hidden}
.case.div{border-color:var(--warn);box-shadow:inset 3px 0 0 var(--warn)}
.hd{display:flex;align-items:center;gap:10px;padding:11px 14px;cursor:pointer;flex-wrap:wrap}
.hd:hover{background:var(--surf2)}
.cid{font-family:"IBM Plex Mono",monospace;font-size:12.5px;color:var(--ink2);flex:none}
.ttl{flex:1;min-width:230px}
.p-P0{color:var(--bad)}.p-P1{color:var(--warn)}.p-P2{color:var(--ink3)}
.s-passed,.s-pass,.s-xfailed{color:var(--ok)}.s-failed,.s-fail,.s-error,.s-xpassed_strict{color:var(--bad)}
.s-blocked,.s-xpassed{color:var(--warn)}.s-skip,.s-skipped{color:var(--ink3)}.s-none{color:var(--ink3);opacity:.6}
.gapc{color:var(--gap)}
.bd{border-top:1px solid var(--rule);padding:14px;display:none}
.case.open .bd{display:block}
.meta{display:grid;grid-template-columns:74px 1fr;gap:7px 12px;font-size:13px;margin-bottom:14px}
.meta dt{color:var(--ink3);font-size:11.5px}.meta dd{margin:0}
.meta code{background:var(--surf2);padding:1px 5px;border-radius:3px;font-size:12px}
.lanes{display:grid;grid-template-columns:1fr 1fr;gap:12px}
@media(max-width:860px){.lanes{grid-template-columns:1fr}}
.lane{border:1px solid var(--rule);border-radius:6px;padding:11px 13px;background:var(--bg)}
.lane h4{margin:0 0 9px;font-size:12px;color:var(--ink3);letter-spacing:.05em;font-weight:500;
display:flex;justify-content:space-between}
.run{border-top:1px dashed var(--rule);padding:7px 0;font-size:12.5px}
.run:first-of-type{border-top:none}
.run .t{color:var(--ink3);font-size:11px;font-family:"IBM Plex Mono",monospace}
.run pre,.cmd{margin:4px 0 0;white-space:pre-wrap;word-break:break-word;font-size:11.5px;
background:var(--surf2);padding:6px 8px;border-radius:4px;max-height:130px;overflow:auto;
font-family:"IBM Plex Mono",monospace}
.empty{color:var(--ink3);font-size:12.5px;padding:6px 0}
.mbtns{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:8px}
.editbox{border:1px solid var(--gate);border-radius:6px;padding:14px;background:var(--bg)}
.ehd{font-size:12px;color:var(--gate);margin-bottom:10px}
.erow{display:flex;gap:8px;align-items:center;margin-bottom:10px}
.erow2{margin-bottom:9px}
.erow2 label,.erow label{font-size:11.5px;color:var(--ink3);display:block;margin-bottom:3px}
.erow label{margin:0 4px 0 0;display:inline}
.editbox input,.editbox textarea,.editbox select{margin:0;font-size:13px}
.editbox textarea{min-height:auto}
.divmsg{background:var(--surf2);border-left:3px solid var(--warn);padding:8px 11px;font-size:12.5px;
margin-bottom:12px;border-radius:0 4px 4px 0}
.err{background:var(--surf);border:1px solid var(--bad);color:var(--bad);border-radius:7px;padding:14px 18px}
</style></head><body>
<header><div class="nav" id="nav"></div><div class="fil" id="fil"></div></header>
<main id="app">加载中…</main>
<script>
let IDX=null,VIEW='index',TASK=null,DATA=null,F='all',OPEN={},VD={},G0I=0;
const $=s=>document.querySelector(s);
const esc=s=>(s||'').replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
const md=s=>esc(s).replace(/\*\*([^*]+)\*\*/g,'<b>$1</b>').replace(/`([^`]+)`/g,'<code>$1</code>');
const AS={passed:'通过',failed:'失败',error:'错误',skipped:'跳过',xfailed:'已知缺陷(预期失败)',xpassed:'意外通过',xpassed_strict:'⚠️意外通过(疑似已修复,待复核)'};
const MS={pass:'通过',fail:'失败',blocked:'阻塞',skip:'跳过'};
const VIEWNAME={gate0:'GATE 0 评审',cases:'用例执行'};

function route(){
  const h=location.hash.replace(/^#\/?/,'').split('/');
  if(h[0]==='t'&&h[1]){TASK=decodeURIComponent(h[1]);VIEW=h[2]||'cases'}
  else{VIEW='index';TASK=null}
}
async function boot(){route();IDX=await (await fetch('/api/index')).json();await load()}
window.onhashchange=async()=>{route();OPEN={};F='all';await load()};

async function load(){
  if(VIEW==='index'){DATA=null;return draw()}
  DATA=await (await fetch(`/api/${VIEW}/${encodeURIComponent(TASK)}`)).json();
  if(VIEW==='gate0'&&!DATA.error){
    VD=await (await fetch(`/api/verdicts/${encodeURIComponent(TASK)}`)).json();
    const first=DATA.cards.findIndex(c=>!VD[c.cid]); G0I=first<0?0:first;
  }
  draw();
}
function taskOf(id){for(const g of IDX.versions)for(const t of g.tasks)if(t.task_id===id)return{...t,version:g.version};return null}

function nav(){
  let h=`<h1 onclick="location.hash='#/'">QA 控制台</h1>`;
  if(VIEW==='index'){
    const n=IDX.versions.reduce((a,g)=>a+g.tasks.length,0);
    h+=`<span class="sep">·</span><span class="mono" style="font-size:12px;color:var(--ink3)">${IDX.versions.length} 个版本 / ${n} 个需求</span>`;
  }else{
    const t=taskOf(TASK)||{};
    h+=`<span class="sep">›</span><select onchange="location.hash='#/'">`+
       `<option>${esc(t.version||'')}</option></select>`;
    h+=`<span class="sep">›</span><select onchange="location.hash='#/t/'+encodeURIComponent(this.value)+'/'+'${VIEW}'">`+
       IDX.versions.flatMap(g=>g.tasks).map(x=>
         `<option value="${esc(x.task_id)}"${x.task_id===TASK?' selected':''}>${esc(x.title||x.task_id)}</option>`).join('')+'</select>';
    h+='<span class="sep">›</span>';
    (t.views||[]).forEach(v=>{h+=`<button class="${v===VIEW?'on':''}" onclick="location.hash='#/t/'+encodeURIComponent('${esc(TASK)}')+'/${v}'">${VIEWNAME[v]}</button>`});
  }
  h+='<div class="kpi" id="kpi"></div>';
  $('#nav').innerHTML=h;
}
function draw(){
  nav();$('#fil').innerHTML='';
  if(DATA&&DATA.error)return $('#app').innerHTML=`<div class="err"><b>加载失败</b><br>${esc(DATA.error)}</div>`;
  if(VIEW==='index')return drawIndex();
  if(VIEW==='gate0')return drawGate0();
  return drawCases();
}
/* ── 索引 ──
   未归版（历史任务）默认折叠：当前在做的版本才该占视线，但不删除入口。 */
let SHOWOLD=false;
function toggleOld(){SHOWOLD=!SHOWOLD;draw()}
function grpHtml(g){
  return `<div class="vgrp"><h2>${esc(g.version)}　·　${g.tasks.length} 个需求</h2>`+
    g.tasks.map(t=>`<div class="tk">`+
      `<div class="tt"><div>${esc(t.title||t.task_id)}</div><div class="tid">${esc(t.task_id)}　${esc(t.current_step||t.status)}</div></div>`+
      t.badges.map(b=>`<span class="pill k-${b.k}">${esc(b.t)}</span>`).join('')+
      t.views.map(v=>`<button onclick="location.hash='#/t/'+encodeURIComponent('${esc(t.task_id)}')+'/${v}'">${VIEWNAME[v]}</button>`).join('')+
      `</div>`).join('')+'</div>';
}
function drawIndex(){
  const cur=IDX.versions.filter(g=>g.version!=='未归版');
  const old=IDX.versions.filter(g=>g.version==='未归版');
  let h=cur.map(grpHtml).join('');
  if(old.length){
    const n=old[0].tasks.length;
    h+=`<div style="margin-top:8px"><button onclick="toggleOld()">`+
       `${SHOWOLD?'▾':'▸'} 未归版历史任务 ${n} 个</button></div>`;
    if(SHOWOLD)h+='<div style="margin-top:12px">'+old.map(grpHtml).join('')+'</div>';
  }
  $('#app').innerHTML=h;
}
/* ── GATE 0 ── */
function g0list(){return F==='all'?DATA.cards:DATA.cards.filter(c=>c.kind===F)}
function drawGate0(){
  const cs=DATA.cards;
  // 只统计「当前队列」里已答的——历史裁决可能有条目现在被自动搁置了，
  // 用全局 VD 条数当分子会出现「已答 21/9」这种反直觉的数字
  const ans=cs.filter(c=>VD[c.cid]).length;
  $('#kpi').innerHTML=`<button class="helpbtn" onclick="showHelp()">ⓘ 这些卡是什么？</button><span>已答 <b>${ans}/${cs.length}</b></span>`+
    (DATA.deferred&&DATA.deferred.length?`<span class="t" style="color:var(--ink3)">（另有 ${DATA.deferred.length} 项已自动搁置）</span>`:'');
  const cnt={};cs.forEach(c=>cnt[c.kind]=(cnt[c.kind]||0)+1);
  $('#fil').innerHTML=['all','conflict','verify','infer','missing'].map(f=>{
    const n=f==='all'?cs.length:(cnt[f]||0);
    const lab=f==='all'?'全部':(cs.find(x=>x.kind===f)||{}).kind_label||f;
    return `<button class="${F===f?'on':''}" onclick="setF('${f}')">${lab} ${n}</button>`}).join('');
  const L=g0list();
  if(!L.length)return $('#app').innerHTML='<div class="card">这个筛选下没有待决项。</div>';
  if(G0I>=L.length)G0I=L.length-1;
  const c=L[G0I],v=VD[c.cid]||{};
  const blk=b=>`<div class="prdb${b.likely?' lk':''}"><div class="prdh"><span class="mono">需求文档 第 ${b.line} 行</span>`+
    (b.cat?`<span>${esc(b.cat)}${b.side?' › '+esc(b.side):''}</span>`:'')+`</div>`+
    (b.loc?`<div class="prdl">${esc(b.loc)}</div>`:'')+`<pre class="prdr">${esc(b.raw)}</pre></div>`;
  const pl=(c.prd||[]).filter(b=>b.likely),po=(c.prd||[]).filter(b=>!b.likely);
  let h=`<div class="card"><div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:6px">`+
    // 卡片编号（DBT-xxx）对评审人没有意义，不显示；悬停在类型标签上可看，方便跟 agent 对话时引用
    `<span class="pill k-gate"${c.dbt?` title="编号 ${c.dbt}"`:''}>${c.kind_label}</span>`+
    (c.row_count>1?`<span class="pill k-warn">1 个答案决定 ${c.row_count} 行</span>`:'')+
    (VD[c.cid]?'<span class="pill k-ok">已答（已存盘）</span>':'')+
    '<span id="svtag"></span>'+'</div>';
  h+=`<p class="q">${md(c.question)}</p>`+(c.background?`<p class="bgd">${md(c.background)}</p>`:'')+
     `<p class="hint">${c.kind_hint}　·　这个答案会更新 ${c.row_count} 处解构表内容</p>`;
  const S=c.sources||[],T=S.filter(x=>x.type==='text'),I=S.filter(x=>x.type==='image');
  const th=(f,cap)=>`<a href="/asset/${encodeURIComponent(TASK)}/ui_design/${encodeURIComponent(f)}" target="_blank" title="点击看大图">`+
     `<img src="/asset/${encodeURIComponent(TASK)}/ui_design/${encodeURIComponent(f)}" loading="lazy"><span>${esc(cap)}</span></a>`;
  if(T.length||I.length){
    h+=`<div class="prdt">需求原文${c.kind==='conflict'&&T.length>=2?'（冲突双方并排）':''}</div>`;
    h+=`<div class="srcs${c.kind==='conflict'&&T.length>=2?' vs':''}">`+T.map(x=>
       `<div class="src"><div class="sh"><b>${esc(x.ref)}</b><span class="mono">第 ${x.line} 行</span></div><pre>${esc(x.text)}</pre>`+
       ((x.image_files||[]).length?`<div class="thumbs">${x.image_files.map(f=>th(f,f)).join('')}</div>`:'')+'</div>').join('')+'</div>';
    if(I.length)h+=`<div class="thumbs" style="margin:-4px 0 14px">${I.map(x=>th(x.file,x.ref)).join('')}</div>`;
  }
  if(c.prd&&c.prd.length){h+='<div class="prd"><div class="prdt">需求文档原文</div>'+(pl.length?pl.map(blk).join(''):blk(c.prd[0]));
    const rest=pl.length?po:c.prd.slice(1);
    if(rest.length)h+=`<details><summary>另有 ${rest.length} 处也提到这个字符串</summary>${rest.map(blk).join('')}</details>`;
    h+='</div>'}
  // 证据按条目分组、标题用人话（"业务规则表 · 第 3 条"）。
  // 兜底：契约要求人读列不用代号，万一漏网，把「R02 / ④-R02」就地替换成它指的那条内容，评审人不看编号
  const REFS=c.refs||{};
  const refx=html=>html.replace(/(^|>)([^<]+)/g,(m,a,t)=>a+t.replace(/([①②③④⑤⑥⑦]\s*[-:：]\s*)?\b([A-Z]{1,2}\d{2,3})\b/g,
     (all,pre,id)=>REFS[id]?`<span class="ref" title="${esc(REFS[id].label)}">「${esc(REFS[id].gist)}」这条</span>`:all));
  const groups=[];c.evidence.forEach(e=>{let g=groups.find(x=>x.row===e.row);if(!g)groups.push(g={row:e.row,label:e.row_label||e.row,items:[]});g.items.push(e)});
  h+=`<details><summary>agent 的拆解依据（检查点表里的相关条目，${groups.length} 条）</summary><div class="ev">`+
     groups.map(g=>`<div class="evg"><div class="evh">${esc(g.label)}</div>`+
       g.items.map(e=>`<div><b>${esc(e.col)}</b>　${refx(md(e.val))}</div>`).join('')+'</div>').join('')+
     '</div></details>';
  h+='<div class="opts">'+c.options.map((o,i)=>
     `<button class="opt ${v.choice===o.id?'sel':''}" onclick="pick('${c.cid}','${o.id.replace(/'/g,"\\'")}')"><kbd>${i+1}</kbd>`+
     `<span>${esc(o.label)}${o.default?'<em class="dflt">agent 默认假设</em>':''}${o.hint?`<em>${esc(o.hint)}</em>`:''}</span></button>`).join('')+'</div>';
  const needVal=NEEDVAL.has(v.choice);
  if(needVal&&c.per_row){const rv=v.rowvals||{};
    h+='<div class="vlab">逐行写下正确的内容（不确定的行留空）</div>'+c.rows.map(r=>`<div style="display:flex;gap:8px;align-items:center;margin-bottom:6px">`+
      `<code class="mono" style="flex:none;min-width:112px;font-size:12px">${r.uid}</code>`+
      `<input class="rv" data-row="${r.uid}" value="${esc(rv[r.uid]||'')}" placeholder="这一行正确的内容是什么？" oninput="sync('${c.cid}')" onblur="reSave('${c.cid}')" style="margin:0"></div>`).join('');
  }else if(needVal){h+=`<div class="vlab">你的答案</div><textarea id="val" class="ans" oninput="sync('${c.cid}')" onblur="reSave('${c.cid}')" `+
     `placeholder="用一两句话写下正确的规则或取值，比如「只有企业账号必填，个人账号选填」。界面文案请照原样写，大小写、标点都别改">${esc(v.value)}</textarea>`}
  h+=`<textarea id="note" oninput="sync('${c.cid}')" onblur="reSave('${c.cid}')" placeholder="备注（可选）：补充例外情况、适用范围或你的理由。agent 回填检查点表、生成用例时都会照着它来，写清楚能少一轮来回">${esc(v.note)}</textarea>`;
  h+=`<div style="display:flex;gap:8px;align-items:center"><button onclick="g0save()">下一张未答 ⏎</button>`+
     `<button onclick="g0jump(-1)">← 上一张</button><button onclick="g0jump(1)">下一张 →</button>`+
     (VD[c.cid]?`<button onclick="g0clear('${c.cid}')">清除本卡</button>`:'')+
     `<span class="t mono" style="margin-left:auto">${G0I+1} / ${L.length}　选项点一下即存盘 · 1-9 选项 · j/k 翻卡</span></div></div>`;
  const df=DATA.deferred||[];
  if(df.length){
    h+=`<div style="margin-top:16px"><button onclick="toggleDeferred()">`+
       `${SHOW_DEF?'▾':'▸'} 另有 ${df.length} 项已自动判定为「提测时看一眼就知道」，无需现在处理</button></div>`;
    if(SHOW_DEF){
      h+='<div style="margin-top:8px">'+df.map(c=>
        `<div class="case"><div class="hd"><span class="pill k-${c.kind}">${c.kind_label}</span>`+
        `<span class="ttl" style="font-size:13px;color:var(--ink2)">${md(c.question)}</span>`+
        `<button onclick="promote('${c.cid}')">拉回来自己答</button></div></div>`
      ).join('')+'</div>';
    }
  }
  $('#app').innerHTML=h;
}
let SHOW_DEF=false;
function toggleDeferred(){SHOW_DEF=!SHOW_DEF;draw()}
function promote(cid){
  const c=(DATA.deferred||[]).find(x=>x.cid===cid);
  if(!c)return;
  DATA.deferred=DATA.deferred.filter(x=>x.cid!==cid);
  DATA.cards.push(c);
  const L=g0list();G0I=L.findIndex(x=>x.cid===cid);if(G0I<0)G0I=0;
  draw();
}
function setF(f){F=f;G0I=0;draw()}
// 存盘反馈只就地改这一个小标签，**绝不 draw()**：重绘会重建输入框，用户正在打字的那个框
// 会丢焦点（实锤：选完选项 1.5s 内点进备注框、或从补充框切到备注框触发失焦存盘，都会被重绘打断）
let SVT=null;
function flashSaved(){
  const t=$('#svtag'); if(!t)return;
  t.innerHTML='<span class="pill k-run">✓ 已存盘</span>';
  clearTimeout(SVT); SVT=setTimeout(()=>{const t2=$('#svtag'); if(t2)t2.innerHTML=''},1500);
}
// 需要用户自己写答案的选项：只有选了它们，才出现「你的答案」输入框
const NEEDVAL=new Set(['answer','fix']);
// 把当前 DOM 里的输入采集进 VD —— **必须在任何 draw() 之前调用**，
// 否则重绘会按 VD 重建输入框、把用户刚打的字冲掉（实锤过的 bug）
function grab(cid){
  const v=(VD[cid]=VD[cid]||{});
  const c=DATA.cards.find(x=>x.cid===cid)||{};
  const nt=$('#note'); if(nt)v.note=nt.value;
  if(c.per_row){
    const rv=v.rowvals||{};
    document.querySelectorAll('.rv').forEach(el=>{rv[el.dataset.row]=el.value});
    v.rowvals=rv;
    v.value=Object.entries(rv).filter(([,x])=>x&&x.trim()).map(([k,x])=>k+'='+x).join('; ');
  }else{const iv=$('#val'); if(iv)v.value=iv.value}
  return v;
}
async function pick(cid,oid){
  const body={...grab(cid),cid,choice:oid,answered_at:new Date().toISOString()};
  VD[cid]={...body}; draw();
  if(NEEDVAL.has(oid)){const f=$('#val')||document.querySelector('.rv'); if(f)f.focus()}  // 选了「我来说明」直接聚焦
  try{
    const r=await fetch(`/api/verdicts/${encodeURIComponent(TASK)}`,{method:'POST',
      headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    if(!r.ok)throw new Error('HTTP '+r.status);
    VD[cid]=body; flashSaved();
  }catch(e){
    delete VD[cid]; alert('没保存上：'+e.message+'\n服务可能已停，确认控制台端口还在跑再重试。'); draw();
  }
}
function sync(cid){grab(cid)}                       // 只入内存，不重绘（重绘会抢焦点）
async function reSave(cid){                          // 失焦时把文字也落盘
  const v=grab(cid); if(!v.choice)return;            // 还没选选项就先不存
  const body={...v,cid,answered_at:new Date().toISOString()};
  try{
    const r=await fetch(`/api/verdicts/${encodeURIComponent(TASK)}`,{method:'POST',
      headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    if(!r.ok)throw new Error('HTTP '+r.status);
    VD[cid]={...body}; flashSaved();                 // 不重绘：用户可能正在另一个框里打字
  }catch(e){alert('没保存上：'+e.message)}
}
function g0jump(d){
  const L=g0list(); if(L[G0I])grab(L[G0I].cid);      // 翻卡前先把当前输入收进 VD
  G0I=Math.max(0,Math.min(L.length-1,G0I+d));draw();
}
async function g0save(){
  const L=g0list(),c=L[G0I],v=VD[c.cid]||{};
  if(!v.choice)return alert('先选一个选项');
  const body={cid:c.cid,choice:v.choice,note:$('#note').value,answered_at:new Date().toISOString()};
  if(c.per_row){const rv={};document.querySelectorAll('.rv').forEach(el=>{if(el.value.trim())rv[el.dataset.row]=el.value.trim()});
    body.rowvals=rv;body.value=Object.entries(rv).map(([k,x])=>k+'='+x).join('; ')}
  else body.value=$('#val')?$('#val').value:(NEEDVAL.has(v.choice)?(v.value||''):'');
  await fetch(`/api/verdicts/${encodeURIComponent(TASK)}`,{method:'POST',
    headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  VD[c.cid]=body;
  const nx=DATA.cards.findIndex(x=>!VD[x.cid]);
  if(nx>=0){const j=L.findIndex(x=>x.cid===DATA.cards[nx].cid);if(j>=0)G0I=j}
  draw();
}
async function g0clear(cid){
  await fetch(`/api/verdicts/${encodeURIComponent(TASK)}`,{method:'POST',
    headers:{'Content-Type':'application/json'},body:JSON.stringify({cid,clear:true})});
  delete VD[cid];draw();
}
/* ── 执行台 ── */
function ok(c){return ['passed','xfailed'].includes(c.auto_status)||c.manual_status==='pass'}
function cpass(c){
  if(F==='all')return true;
  if(F==='undone')return !c.auto_status&&!c.manual_status;
  if(F==='div')return c.divergent;
  if(F==='bad')return ['failed','error','xpassed_strict'].includes(c.auto_status)||c.manual_status==='fail';
  if(F==='gap')return c.map_gap;
  if(F==='ok')return ok(c);
  return true;
}
function drawCases(){
  const cs=DATA.cases,n=f=>cs.filter(f).length;
  $('#kpi').innerHTML=
    `<span>自动 <b class="s-passed">${n(c=>c.auto_status==='passed')}</b>/<b class="s-failed">${n(c=>['failed','error'].includes(c.auto_status))}</b>/<b class="s-xfailed">${n(c=>c.auto_status==='xfailed')}</b>已知缺陷/<b>${n(c=>!c.auto_status)}</b></span>`+
    `<span>人工 <b class="s-pass">${n(c=>c.manual_status==='pass')}</b>/<b class="s-fail">${n(c=>c.manual_status==='fail')}</b>/<b>${n(c=>!c.manual_status)}</b></span>`+
    `<span>分歧 <b class="s-blocked">${n(c=>c.divergent)}</b></span><span>已验证 <b>${n(ok)}/${cs.length}</b></span>`+
    (n(c=>c.auto_status==='xpassed_strict')?`<span>⚠️疑似已修复 <b class="s-xpassed_strict">${n(c=>c.auto_status==='xpassed_strict')}</b>（xfail意外通过，待复核）</span>`:'');
  $('#fil').innerHTML=[['all','全部',cs.length],['undone','未执行',n(c=>!c.auto_status&&!c.manual_status)],
    ['div','两边分歧',n(c=>c.divergent)],['bad','有失败',n(c=>['failed','error','xpassed_strict'].includes(c.auto_status)||c.manual_status==='fail')],
    ['gap','卡地图缺口',n(c=>c.map_gap)],['ok','已验证',n(ok)]]
    .map(([k,l,v])=>`<button class="${F===k?'on':''}" onclick="setF('${k}')">${l} ${v}</button>`).join('');
  const gst=(DATA.frontmatter||{}).status||'';
  let body=(ADDING?addForm():'')+
    `<div style="margin-bottom:12px"><button onclick="ADDING=true;draw()">＋ 新增用例</button>`+
    (gst==='pending_review'
      ?`<button style="margin-left:8px;border-color:var(--gate);color:var(--gate)" onclick="confirmGate1()">✓ 标记 GATE 1 已审</button>`
      :gst==='confirmed'
        ?`<span class="pill" style="margin-left:8px;color:var(--ok);border-color:var(--ok)">GATE 1 已过审</span>`
        :'')+
    `<span class="t" style="margin-left:10px;color:var(--ink3)">改动直接写进 cases.md，`+
    `首次编辑前自动存 cases.pre_gate1.md 快照，每次改动记入 cases_edits.jsonl</span></div>`;
  body+=cs.filter(cpass).map(ccard).join('')||'<div class="case"><div class="hd">这个筛选下没有用例。</div></div>';
  $('#app').innerHTML=body;
}
function badge(k,st){const lab=k==='auto'?(AS[st]||'未跑'):(MS[st]||'未执行');
  return `<span class="pill s-${st||'none'}">${k==='auto'?'自动':'人工'} ${lab}</span>`}
function runs(rs,k){
  if(!rs.length)return '<div class="empty">暂无记录</div>';
  return rs.map(r=>{const lab=k==='auto'?(AS[r.status]||r.status):(MS[r.status]||r.status);
    let h=`<div class="run"><span class="pill s-${r.status}">${lab}</span> <span class="t">${esc(r.ts||'')}</span>`;
    if(k==='auto'){h+=` <span class="t">${r.duration!=null?r.duration+'s':''}</span>`;
      if(r.nodeid)h+=`<div class="t" style="margin-top:3px">${esc(r.nodeid)}</div>`;
      if(r.error)h+=`<pre>${esc(r.error)}</pre>`;
      if(r.artifacts&&r.artifacts.length)h+=`<div class="t" style="margin-top:4px">取证：${r.artifacts.map(esc).join('　')}</div>`}
    else{if(r.actual)h+=`<div style="margin-top:4px"><b>实际看到：</b>${esc(r.actual)}</div>`;
      if(r.note)h+=`<div style="margin-top:3px;color:var(--ink2)">${esc(r.note)}</div>`}
    return h+'</div>'}).join('');
}
function ccard(c){
  const op=OPEN[c.id]?' open':'',dv=c.divergent?' div':'';
  let h=`<div class="case${op}${dv}"><div class="hd" onclick="tog('${c.id}')"><span class="cid">${c.id}</span>`+
    `<span class="pill p-${c.priority}">${c.priority}</span><span class="ttl">${md(c.title)}</span>`+
    (c.map_gap?'<span class="pill gapc">缺地图</span>':'')+badge('auto',c.auto_status)+badge('manual',c.manual_status)+'</div>';
  if(!OPEN[c.id])return h+'</div>';
  h+='<div class="bd">';
  if(c.divergent)h+=`<div class="divmsg"><b>两边结论不一致。</b>自动化说「${AS[c.auto_status]||c.auto_status}」，`+
    `人工说「${MS[c.manual_status]||c.manual_status}」——要么脚本断言写错了，要么人看漏了。先查这条。</div>`;
  if(EDIT===c.id){h+=editForm(c);return h+'</div></div>'}
  h+=`<div style="margin-bottom:10px"><button onclick="startEdit('${c.id}')">编辑这条</button></div>`;
  h+=`<dl class="meta"><dt>前置</dt><dd>${md(c.pre)||'—'}</dd><dt>步骤</dt><dd>${md(c.steps)||'—'}</dd>`+
     `<dt>期望</dt><dd>${md(c.expect)||'—'}</dd><dt>依据</dt><dd>${md(c.prd_ref)||'—'}</dd><dt>page_ref</dt><dd>${md(c.page_ref)||'—'}</dd>`+
     `<dt>溯源</dt><dd class="mono" style="font-size:11.5px">${esc(c.derived_from)}　·　cases.md:${c.line_no}</dd></dl>`;
  h+='<div class="lanes"><div class="lane"><h4><span>自动化执行</span><span class="t mono">auto_runs.jsonl</span></h4>';
  if(c.map_gap)h+='<p class="hint">⚠️ 卡在 page_map 缺口上，探索补完前跑不了自动化——先走人工。</p>';
  h+=`<pre class="cmd">python -m pytest -p tools.pytest_case_ledger \\
  -k "${esc(c.id)}" -v --override-ini="addopts="</pre>`;
  h+='<div style="margin-top:9px">'+runs(c.auto_runs,'auto')+'</div></div>';
  h+='<div class="lane"><h4><span>人工执行</span><span class="t mono">manual_runs.jsonl</span></h4><div class="mbtns">'+
     Object.entries(MS).map(([k,v])=>`<button onclick="mark('${c.id}','${k}')">${v}</button>`).join('')+'</div>'+
     `<textarea id="ac-${c.id}" placeholder="实际看到什么（判失败/阻塞时必填，逐字抄）"></textarea>`+
     `<textarea id="nt-${c.id}" placeholder="备注（可选）"></textarea>`+
     '<div style="margin-top:4px">'+runs(c.manual_runs,'manual')+'</div></div></div>';
  return h+'</div></div>';
}
function tog(id){OPEN[id]=!OPEN[id];draw()}
let EDIT=null,ADDING=false;
const F_MAP={title:'测试点',pre:'前置',steps:'步骤',expect:'期望',priority:'优先级',exec:'exec',page_ref:'page_ref'};
function startEdit(id){EDIT=id;draw()}
function cancelEdit(){EDIT=null;ADDING=false;draw()}
async function saveEdit(id){
  const ch={};
  for(const [k,col] of Object.entries(F_MAP)){
    const el=document.getElementById('e-'+k+'-'+id); if(el)ch[col]=el.value;
  }
  const r=await(await fetch(`/api/case/${encodeURIComponent(TASK)}`,{method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({op:'update',case_id:id,changes:ch})})).json();
  if(r.error)return alert('保存失败：'+r.error);
  EDIT=null;DATA=await(await fetch(`/api/cases/${encodeURIComponent(TASK)}`)).json();draw();
}
async function delCase(id){
  const reason=prompt('删除 '+id+' 的理由（会记进审计日志，可回溯）：');
  if(reason===null)return;
  const r=await(await fetch(`/api/case/${encodeURIComponent(TASK)}`,{method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({op:'delete',case_id:id,reason})})).json();
  if(r.error)return alert('删除失败：'+r.error);
  DATA=await(await fetch(`/api/cases/${encodeURIComponent(TASK)}`)).json();draw();
}
async function addCase(){
  const cells={};
  for(const [k,col] of Object.entries(F_MAP)){
    const el=document.getElementById('n-'+k); if(el&&el.value.trim())cells[col]=el.value;
  }
  if(!cells['测试点'])return alert('至少填「测试点」');
  const r=await(await fetch(`/api/case/${encodeURIComponent(TASK)}`,{method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({op:'create',cells})})).json();
  if(r.error)return alert('新增失败：'+r.error);
  ADDING=false;DATA=await(await fetch(`/api/cases/${encodeURIComponent(TASK)}`)).json();
  OPEN[r.case_id]=true;draw();
}
function editForm(c){
  const F=[['title','测试点',1],['pre','前置',1],['steps','步骤',3],['expect','期望',3],
           ['page_ref','page_ref',2]];
  let h='<div class="editbox"><div class="ehd">编辑用例 —— 改动会写进 cases.md 并记入审计日志</div>';
  h+=`<div class="erow"><label>优先级</label><select id="e-priority-${c.id}">`+
     ['P0','P1','P2'].map(p=>`<option${c.priority===p?' selected':''}>${p}</option>`).join('')+'</select>'+
     `<label>exec</label><select id="e-exec-${c.id}">`+
     ['auto','manual','blocked'].map(x=>`<option${c.exec===x?' selected':''}>${x}</option>`).join('')+'</select></div>';
  F.forEach(([k,lab,rows])=>{h+=`<div class="erow2"><label>${lab}</label>`+
    (rows>1?`<textarea id="e-${k}-${c.id}" rows="${rows}">${esc(c[k]||'')}</textarea>`
           :`<input id="e-${k}-${c.id}" value="${esc(c[k]||'')}">`)+'</div>'});
  h+=`<div class="erow"><button onclick="saveEdit('${c.id}')">保存</button>`+
     `<button onclick="cancelEdit()">取消</button>`+
     `<button onclick="delCase('${c.id}')" style="margin-left:auto;color:var(--bad)">删除这条</button></div></div>`;
  return h;
}
function addForm(){
  const F=[['title','测试点',1],['pre','前置',1],['steps','步骤',3],['expect','期望',3],['page_ref','page_ref',2]];
  let h='<div class="case"><div class="bd" style="display:block"><div class="editbox">'+
        '<div class="ehd">新增用例 —— ID 自动分配，`exec` 默认 manual（避免误进自动化）</div>';
  h+='<div class="erow"><label>优先级</label><select id="n-priority">'+
     ['P2','P1','P0'].map(p=>`<option>${p}</option>`).join('')+'</select>'+
     '<label>exec</label><select id="n-exec">'+
     ['manual','auto','blocked'].map(x=>`<option>${x}</option>`).join('')+'</select></div>';
  F.forEach(([k,lab,rows])=>{h+=`<div class="erow2"><label>${lab}</label>`+
    (rows>1?`<textarea id="n-${k}" rows="${rows}"></textarea>`:`<input id="n-${k}">`)+'</div>'});
  h+='<div class="erow"><button onclick="addCase()">新增</button>'+
     '<button onclick="cancelEdit()">取消</button></div></div></div></div>';
  return h;
}
async function confirmGate1(){
  if(!confirm('整份 cases.md 标记为 GATE 1 已审？这一步不检查有没有逐条看过，确认前请自己确认已经看完。'))return;
  const r=await(await fetch(`/api/case/${encodeURIComponent(TASK)}`,{method:'POST',
    headers:{'Content-Type':'application/json'},body:JSON.stringify({op:'confirm'})})).json();
  if(r.error)return alert('标记失败：'+r.error);
  DATA=await(await fetch(`/api/cases/${encodeURIComponent(TASK)}`)).json();draw();
}
async function mark(id,st){
  const actual=$('#ac-'+id).value.trim(),note=$('#nt-'+id).value.trim();
  if((st==='fail'||st==='blocked')&&!actual)return alert('判失败/阻塞时请填「实际看到什么」');
  await fetch(`/api/manual/${encodeURIComponent(TASK)}`,{method:'POST',
    headers:{'Content-Type':'application/json'},body:JSON.stringify({case_id:id,status:st,actual,note})});
  DATA=await (await fetch(`/api/cases/${encodeURIComponent(TASK)}`)).json();draw();
}
// 关页面/刷新前，若当前卡有已输入但未落盘的文字，拦一下
window.addEventListener('beforeunload',e=>{
  if(VIEW!=='gate0')return;
  const L=g0list(),c=L[G0I]; if(!c)return;
  const nt=$('#note'),iv=$('#val'),v=VD[c.cid]||{};
  const dirty=(nt&&nt.value&&nt.value!==(v.note||''))||(iv&&iv.value&&iv.value!==(v.value||''));
  if(dirty){e.preventDefault();e.returnValue=''}
});
document.addEventListener('keydown',e=>{
  if(VIEW!=='gate0'||['INPUT','TEXTAREA'].includes(e.target.tagName))return;
  if($('#helpmask')&&$('#helpmask').classList.contains('on'))return;   // 说明弹窗开着时不响应选项快捷键
  const L=g0list(),c=L[G0I];if(!c)return;
  if(/^[1-9]$/.test(e.key)){const o=c.options[+e.key-1];if(o)pick(c.cid,o.id)}
  else if(e.key==='j')g0jump(1);else if(e.key==='k')g0jump(-1);
  else if(e.key==='Enter')g0save();
});
// ── 卡片类型说明（右上角「这些卡是什么？」）──
const HELP=`<h3>这些卡是什么？为什么要你来判断？</h3>
<p class="lead">agent 先把需求拆成一张张检查点表（每个功能点、每个字段、每种状态切换）。遇到需求没写清楚的地方，
它<b>不会自己瞎猜</b>，而是标出来。这里只推给你<b>必须由人拍板</b>的那几条：你的答案会直接写进检查点表，
后面生成的测试用例就照着你的答案写。答对一张卡，等于提前堵住一类"需求理解错了"的返工。</p>
<h4>三种卡片</h4>
<table>
<tr><th>类型</th><th>是什么意思</th><th>你怎么答</th><th>答完之后会怎样</th></tr>
<tr><td>⚠️ 冲突</td><td>需求里有两处说法打架（比如正文和变更日志、需求和设计图），agent 不知道该信哪一个。</td>
<td>选你认为对的那一方；两边都不对就选「我来说明」写正确规则。</td>
<td>采纳的一方成为用例依据；另一方会被记成"文档勘误"，建议同步给产品改需求。</td></tr>
<tr><td>⚠️ 缺失</td><td>需求根本没提，agent 也推不出来，比如"老数据要不要也遵守新规则"。</td>
<td>你知道答案就直接选或写；不知道就选「留给提测实测」。</td>
<td>有答案的，按你的答案出用例；留给实测的，会变成一条"提测后去看实际行为"的检查项，不会漏掉。</td></tr>
<tr><td>🔶 推断</td><td>需求没明说，agent 参照同类功能先填了一个答案。</td>
<td>认同就选它；不对就改成正确的。</td>
<td>认同后它就从"猜的"变成"确定的"，以后同类需求可以直接复用。</td></tr>
</table>
<h4>几个常见问题</h4>
<ol>
<li><b>「agent 默认假设」是什么？</b>如果你不改，agent 就按这个选项写用例。同意的话点它就行，最省事。</li>
<li><b>拿不准怎么办？</b>选「我不确定，留给提测实测」永远是安全的：它不会被当成同意，只是把这个问题留到功能能用时再看。</li>
<li><b>为什么只有这几张？</b>"提测时看一眼就知道"的问题（比如提示文案的具体措辞）已经自动放到页面底部，不占你的时间；你也可以展开把它们拉回来自己答。</li>
<li><b>答完以后呢？</b>告诉 agent「审完了」→ 它把你的答案回填进检查点表 → 请你确认一次 → 生成正式测试用例和操作步骤（下一轮评审）。</li>
<li><b>备注有什么用？</b>备注会和你的选项一起交给 agent：回填检查点表、生成用例时，它会把你写的例外、适用范围、补充条件一并体现进去。只选选项说不全的，写在备注里。</li>
<li><b>答错了能改吗？</b>能。每张卡选完就自动保存，随时回来改选项；点「清除本卡」可以撤回。</li>
</ol>
<div style="text-align:right;margin-top:14px"><button onclick="hideHelp()">知道了</button></div>`;
function showHelp(){let m=$('#helpmask');
  if(!m){m=document.createElement('div');m.id='helpmask';m.className='mask';
    m.innerHTML='<div class="dlg" role="dialog" aria-modal="true">'+HELP+'</div>';
    m.addEventListener('click',e=>{if(e.target===m)hideHelp()});document.body.appendChild(m)}
  m.classList.add('on')}
function hideHelp(){const m=$('#helpmask');if(m)m.classList.remove('on')}
document.addEventListener('keydown',e=>{if(e.key==='Escape')hideHelp()});
boot();
</script></body></html>"""


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "serve"
    if cmd == "index":
        cmd_index()
    elif cmd == "serve":
        port = int(sys.argv[2]) if len(sys.argv) > 2 else 8900
        d = discover()
        n = sum(len(g["tasks"]) for g in d["versions"])
        ThreadingHTTPServer.allow_reuse_address = True   # 免得 TIME_WAIT 占位
        try:
            srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        except OSError as e:
            print(f"端口 {port} 起不来：{e}\n"
                  f"先看是谁占着：lsof -nP -iTCP:{port} -sTCP:LISTEN\n"
                  f"或换个端口：python3 tools/qa_console.py serve {port + 1}")
            sys.exit(1)
        print(f"QA 控制台：http://127.0.0.1:{port}/\n"
              f"{len(d['versions'])} 个版本 / {n} 个需求 · 单端口，页面内切换\nCtrl-C 结束")
        srv.serve_forever()
    else:
        print(__doc__)
