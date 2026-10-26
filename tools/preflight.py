# -*- coding: utf-8 -*-
"""跑批前"提前探路"（preflight）参考实现：按 page_map 把 URL 固定的页面挨个打开，几分钟内发现整页级的墙。

为什么要有它：一个测试文件整跑可能要一个小时，若页面路由变了 / 登录态失效 / 页面结构大改，
要等跑完才知道，而且十几条用例陪着一起挂。预检在跑批之前先把"能不能进、路由还在不在、
页面标志元素还在不在"这类整页级的问题探一遍。

判定口径：
- **FAIL**（硬失败，退出码 1）：页面打不开 / landmark（"进这个页面一定能看到的元素"）找不到 /
  被重定向到登录页或无权限页。landmark 找不到 = 路由变了或页面结构大改，这批用例大概率成片失败。
- **WARN**（不影响退出码）：页面上的普通元素（page_map 的 `elements`）找不到。有的元素要满足特定
  条件才出现（某个状态才有的按钮），找不到不一定是漂移，但值得看一眼。
- **SKIP**：URL 带 `{id}` 这类占位符（要先造数据才能打开）/ page_map 里写了 `preflight: false` /
  page_map 写了 `role: <角色>` 但没提供该角色的登录态。

landmark 优先：landmark 在就说明页面对了，页面上恰好有个密码框 / 邮箱框也不算"被踢回登录页"
（例如个人设置页本身就有修改密码的输入框）。只有 landmark 找不到时才去判断是不是落在了登录 / 无权限页。

登录态：本工具**不内置任何账号或 OTP**。需要登录的系统，先用你自己的登录流程（例如 utils/auth_state.py）
把 `context.storage_state(path=...)` 存成文件，再传给 `--storage-state`：
    --storage-state state.json                  # 所有页面共用
    --storage-state admin=admin.json --storage-state user=user.json
                                                # 按 page_map 顶层的 `role:` 字段选；没写 role 的页面用不带角色名的那个

URL 解析：page_map 里的 url 是相对路径时拼到 base_url 上；是绝对 URL 时原样打开，
加 `--rebase` 则把它的协议 + 域名换成 base_url 的（地图在 A 环境探索、预检跑 B 环境时用）。
base_url 默认从 pytest.ini 的 `--base-url=` / `base_url =` 读，也可 `--base-url` 显式传。

用法：
    python tools/preflight.py                                  # 探全部 page_map/**/*.yaml
    python tools/preflight.py page_map/myapp/*.yaml --storage-state .auth/state.json
    python -m pytest tests/ --preflight "python tools/preflight.py page_map/myapp/*.yaml"   # 接 pytest_guard

能力边界：只能发现"整页级"的墙。下拉选项文案变了、弹窗字段换了这类要交互才看得到的深层漂移，
预检发现不了——那部分靠 tools/pytest_guard.py 的撞墙止损兜底。

结果同时写入 artifacts/_runs/preflight_last.json。
"""
import argparse
import configparser
import glob
import json
import re
import shlex
import sys
import time
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "artifacts" / "_runs" / "preflight_last.json"

DEFAULT_LOGIN_URL = r"(login|log-in|signin|sign-in|sign_in|/auth)"
DEFAULT_DENIED_TEXT = (r"(permission denied|access denied|not authorized|you do not have permission"
                       r"|forbidden|无权限|没有权限|无访问权限)")


def base_url_from_ini(ini: Path = ROOT / "pytest.ini") -> str | None:
    """从 pytest.ini 读 base_url：先看 `base_url =`，再看 addopts 里的 `--base-url`。"""
    if not ini.exists():
        return None
    cp = configparser.ConfigParser(interpolation=None)
    cp.read(ini, encoding="utf-8")
    if not cp.has_section("pytest"):
        return None
    if cp.get("pytest", "base_url", fallback=None):
        return cp.get("pytest", "base_url").strip()
    opts = shlex.split(cp.get("pytest", "addopts", fallback=""))
    for i, o in enumerate(opts):
        if o.startswith("--base-url="):
            return o.split("=", 1)[1]
        if o == "--base-url" and i + 1 < len(opts):
            return opts[i + 1]
    return None


def _selector_of(v):
    if isinstance(v, dict):
        return v.get("selector")
    if isinstance(v, str):
        return v
    return None


def resolve_url(url: str, base_url: str | None, rebase: bool) -> str:
    parts = urlsplit(url)
    if not parts.scheme:
        if not base_url:
            raise ValueError("page_map 里是相对路径，但没有 base_url（pytest.ini 或 --base-url）")
        return urljoin(base_url.rstrip("/") + "/", url.lstrip("/"))
    if rebase and base_url:
        b = urlsplit(base_url)
        return urlunsplit((b.scheme, b.netloc, parts.path, parts.query, parts.fragment))
    return url


def load_pages(patterns: list[str], base_url: str | None, rebase: bool, states: dict) -> list[dict]:
    import yaml

    files = []
    for p in patterns or ["page_map/**/*.yaml"]:
        files += glob.glob(p if Path(p).is_absolute() else str(ROOT / p), recursive=True)
    pages = []
    for f in sorted(set(files)):
        try:
            rel = str(Path(f).resolve().relative_to(ROOT))
        except ValueError:
            rel = f
        try:
            d = yaml.safe_load(Path(f).read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            pages.append({"file": rel, "status": "FAIL", "reason": f"YAML 解析失败：{e}"})
            continue
        if not isinstance(d, dict) or not d.get("url"):
            continue
        raw_url = str(d["url"]).split("#")[0].strip()
        role = d.get("role")
        pg = {"file": rel, "page": d.get("page"), "url": raw_url, "role": role,
              "landmark": _selector_of(d.get("landmark")), "elements": {}}
        els = d.get("elements")
        for k, v in (els.items() if isinstance(els, dict) else []):
            sel = _selector_of(v)
            if sel and "{" not in sel:  # 带 {label} 之类运行时占位符的 selector 没法静态检查
                pg["elements"][k] = sel
        if d.get("preflight") is False:
            pg.update(status="SKIP", reason="page_map 标了 preflight: false")
        elif "{" in raw_url:
            pg.update(status="SKIP", reason="URL 带占位符，需要先造数据才能打开")
        elif role and role not in states:
            pg.update(status="SKIP", reason=f"未提供角色 {role!r} 的 storage_state")
        else:
            try:
                pg["url"] = resolve_url(raw_url, base_url, rebase)
            except ValueError as e:
                pg.update(status="FAIL", reason=str(e))
            pg["state_key"] = role if role in states else None
        pages.append(pg)
    return pages


def _on_login_or_denied(page, login_url_re, denied_re) -> str | None:
    """landmark 找不到时才调用：判断是不是落到了登录页 / 无权限页，返回原因或 None。"""
    try:
        if login_url_re.search(urlsplit(page.url).path or ""):
            return f"被重定向到登录页：{page.url}"
        if page.locator('input[type="password"]:visible').count():
            return f"页面上出现了登录表单（密码框），疑似登录态失效：{page.url}"
        if page.get_by_text(denied_re).count():
            return f"页面提示无权限：{page.url}"
    except Exception:  # noqa: BLE001
        pass
    return None


def _probe_one(page, pg: dict, timeout_ms: int, login_url_re, denied_re):
    t0 = time.time()
    try:
        page.goto(pg["url"], wait_until="domcontentloaded", timeout=timeout_ms * 3)
        try:
            page.wait_for_load_state("networkidle", timeout=timeout_ms)
        except Exception:  # noqa: BLE001 —— 有长轮询的页面等不到 networkidle，不算失败，靠 landmark 判断
            pass
        if pg["landmark"]:
            try:
                page.locator(pg["landmark"]).first.wait_for(state="visible", timeout=timeout_ms)
            except Exception:  # noqa: BLE001
                reason = (_on_login_or_denied(page, login_url_re, denied_re)
                          or f"页面标志元素找不到：{pg['landmark'][:100]}")
                pg.update(status="FAIL", reason=reason, landed_url=page.url)
                return
        else:
            reason = _on_login_or_denied(page, login_url_re, denied_re)
            if reason:
                pg.update(status="FAIL", reason=reason, landed_url=page.url)
                return
        missing = []
        for key, sel in pg["elements"].items():
            try:
                if page.locator(sel).count() == 0:
                    missing.append({"key": key, "selector": sel})
            except Exception as e:  # noqa: BLE001 —— selector 语法本身有问题也算一种漂移信号
                missing.append({"key": key, "selector": sel, "error": e.__class__.__name__})
        pg["missing"] = missing
        pg["status"] = "WARN" if missing else "PASS"
    except Exception as e:  # noqa: BLE001
        pg.update(status="FAIL", reason=f"打开页面出错：{e.__class__.__name__}: {str(e)[:160]}")
    finally:
        pg["seconds"] = round(time.time() - t0, 1)


def probe(pages: list[dict], states: dict, channel: str | None, timeout_ms: int,
          login_url_re, denied_re, viewport=(1600, 1000)) -> list[dict]:
    from playwright.sync_api import sync_playwright

    todo = [pg for pg in pages if "status" not in pg]
    if not todo:
        return pages
    with sync_playwright() as p:
        browser = None
        if channel:
            try:
                browser = p.chromium.launch(headless=True, channel=channel)
            except Exception as e:  # noqa: BLE001
                print(f"[preflight] channel={channel} 启动失败（{e.__class__.__name__}），回落到 Playwright 自带 Chromium")
        browser = browser or p.chromium.launch(headless=True)
        for key in sorted({pg.get("state_key") for pg in todo}, key=lambda k: k or ""):
            group = [pg for pg in todo if pg.get("state_key") == key]
            kwargs = {"viewport": {"width": viewport[0], "height": viewport[1]}, "ignore_https_errors": True}
            if states.get(key):
                kwargs["storage_state"] = states[key]
            ctx = browser.new_context(**kwargs)
            page = ctx.new_page()
            for pg in group:
                _probe_one(page, pg, timeout_ms, login_url_re, denied_re)
                print(f"[preflight] {pg['status']:4s} {pg['file']}"
                      + (f"  ← {pg['reason']}" if pg.get("reason") else "")
                      + (f"  （{len(pg['missing'])} 个元素未找到）" if pg.get("missing") else ""), flush=True)
            ctx.close()
        browser.close()
    return pages


def _parse_states(values: list[str]) -> dict:
    """['state.json', 'admin=a.json'] → {None: 'state.json', 'admin': 'a.json'}"""
    states = {}
    for v in values or []:
        role, sep, path = v.partition("=")
        if not sep:
            role, path = None, v
        if not Path(path).exists():
            raise SystemExit(f"--storage-state 文件不存在：{path}")
        states[role or None] = path
    return states


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="跑批前按 page_map 提前探路（headless）")
    ap.add_argument("files", nargs="*", help="要探的 page_map 文件（支持通配），默认 page_map/**/*.yaml")
    ap.add_argument("--base-url", default=None, help="基础 URL，默认读 pytest.ini")
    ap.add_argument("--rebase", action="store_true", help="把绝对 URL 的协议+域名也换成 base_url 的")
    ap.add_argument("--storage-state", action="append", default=[], metavar="[ROLE=]PATH",
                    help="登录态文件（Playwright storage_state），可多次传；ROLE 对应 page_map 的 role 字段")
    ap.add_argument("--channel", default=None, help="浏览器 channel（如 chrome / msedge），默认 Playwright 自带 Chromium")
    ap.add_argument("--timeout", type=int, default=10000, help="landmark 等待超时（毫秒），默认 10000")
    ap.add_argument("--login-url-pattern", default=DEFAULT_LOGIN_URL, help="落地 URL 路径命中即视为被踢回登录页（正则，大小写不敏感）")
    ap.add_argument("--denied-text", default=DEFAULT_DENIED_TEXT, help="页面文字命中即视为无权限页（正则，大小写不敏感，不要写 (?i) 这类内联标志）")
    ap.add_argument("--out", default=str(OUT), help="结果 JSON 路径")
    args = ap.parse_args(argv)

    base_url = args.base_url or base_url_from_ini()
    states = _parse_states(args.storage_state)
    # 大小写不敏感用编译标志而不是 (?i)：denied_re 会交给 Playwright 的 get_by_text 转成 JS 正则，JS 不认内联标志
    login_url_re = re.compile(args.login_url_pattern, re.IGNORECASE)
    denied_re = re.compile(args.denied_text, re.IGNORECASE)

    t0 = time.time()
    pages = probe(load_pages(args.files, base_url, args.rebase, states), states, args.channel,
                  args.timeout, login_url_re, denied_re)
    cnt = {s: sum(1 for pg in pages if pg.get("status") == s) for s in ("PASS", "WARN", "FAIL", "SKIP")}
    elapsed = round(time.time() - t0)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "seconds": elapsed,
                               "base_url": base_url, "summary": cnt, "pages": pages},
                              ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n[preflight] 完成，用时 {elapsed}s：PASS {cnt['PASS']} / WARN {cnt['WARN']} / "
          f"FAIL {cnt['FAIL']} / SKIP {cnt['SKIP']}  → {out}")
    for pg in pages:
        if pg.get("status") == "FAIL":
            print(f"  ✗ {pg['file']}：{pg['reason']}")
    for pg in pages:
        if pg.get("status") == "WARN":
            keys = ", ".join(m["key"] for m in pg["missing"][:6])
            print(f"  △ {pg['file']}：{len(pg['missing'])} 个元素未找到（{keys}{' …' if len(pg['missing']) > 6 else ''}）")
    if not pages:
        print("[preflight] 没有找到带 url 的 page_map 文件")
    return 1 if cnt["FAIL"] else 0


if __name__ == "__main__":
    sys.exit(main())
