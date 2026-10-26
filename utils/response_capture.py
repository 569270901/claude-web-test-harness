# -*- coding: utf-8 -*-
"""接口响应抓包 + "没有接口报错"断言（可同时挂多个页面 / context）。

为什么要有它：UI 断言只看页面，接口 500 时页面可能只是"少了一行数据"或干脆没变化，UI 断言照样通过。
让每条用例顺手断言"这段操作里没有接口报错"，能把这类静默失败暴露出来。

⚠️ 最大的坑——**抓包挂错页面，断言恒为空**：
如果抓包挂在 pytest-playwright 默认的 `page` 上，而用例实际操作的是自己 `browser.new_context()`
开出来的角色页面（如多角色用例的 admin_page / user_page），两者不是同一个页面：抓包一条响应都收不到，
`assert_no_error_responses` 遍历空列表恒通过——接口明明 500，用例照样绿。
所以：抓包必须挂到用例**实际使用**的所有页面上（见 conftest.py 里的 capture fixture 注释示例），
并且可以用 `capture.assert_saw_traffic()` 自检"确实抓到过响应"。

判定口径：
- 默认只认 HTTP 状态码 ≥ 400 为错误
- 可选 `business_error` 钩子：很多后端 HTTP 永远 200，错误放在 JSON 的 code 字段里。传入
  `callable(body, response) -> str | None`，返回非空字符串即视为错误（字符串作为错误说明）。
  常见写法用 `code_field_checker()` 生成，例如"code 不等于 0 / 200 即错"：
      ResponseCapture(page, business_error=code_field_checker("code", success=(0, 200)))
  或者"code 以 4 / 5 开头算错"这类自定义规则：
      ResponseCapture(page, business_error=lambda body, resp:
          f"code={body.get('code')}" if isinstance(body, dict) and str(body.get("code", ""))[:1] in "45" else None)

用法：
    cap = ResponseCapture([page_a, page_b], url_filter="/api/")
    cap.start()
    ... 操作 ...
    assert_no_error_responses(cap)                      # 报错信息带出 方法 + 接口路径 + 状态码 / 业务 msg
    assert_no_error_responses(cap, allow_status=(404,), allow_paths=("/api/optional-thing",))
"""
import re
from typing import Any, Callable, Iterable, Optional, Union
from urllib.parse import urlsplit

BusinessError = Callable[[Any, Any], Optional[str]]
UrlFilter = Union[str, re.Pattern, Callable[[str], bool], None]

# 默认只关心前端发起的接口请求；图片 / 字体 / 样式表的 404 一般不是被测功能的问题。
# 想连页面文档、静态资源一起判，传 resource_types=None。
DEFAULT_RESOURCE_TYPES = ("xhr", "fetch")


def code_field_checker(field: str = "code", success: Iterable = (0, 200, "0", "200"),
                       msg_fields: Iterable[str] = ("msg", "message", "error")) -> BusinessError:
    """生成一个"业务码"判定函数：JSON 体里 `field` 存在且不在 `success` 中 → 视为错误。

    字段不存在（如列表接口直接返回数组）不算错。返回的错误说明形如 "code=601：<msg>"。
    """
    ok = set(success)
    msg_fields = tuple(msg_fields)

    def _check(body, _response):
        if not isinstance(body, dict) or field not in body:
            return None
        code = body.get(field)
        if code in ok:
            return None
        msg = next((str(body[k]) for k in msg_fields if body.get(k)), "")
        return f"{field}={code}" + (f"：{msg[:200]}" if msg else "")

    return _check


def _compile_filter(f: UrlFilter) -> Callable[[str], bool]:
    if f is None:
        return lambda url: True
    if isinstance(f, str):
        return lambda url: f in url
    if isinstance(f, re.Pattern):
        return lambda url: bool(f.search(url))
    return f


class ResponseCapture:
    """监听一个或多个 Page / BrowserContext 的 response 事件，记录匹配的响应。

    Args:
        targets: 单个或一组 Page / BrowserContext。挂 context 能覆盖它后来弹出的新页面。
        url_filter: 只记录 URL 命中的响应——子串 / 正则 / callable(url)->bool / None(全部)。
            用来排除第三方域名（统计、埋点、CDN）。
        business_error: 可选业务码钩子，见模块 docstring。
        resource_types: 只记录这些 resource_type，None 表示不限。
    """

    def __init__(self, targets, url_filter: UrlFilter = None, business_error: Optional[BusinessError] = None,
                 resource_types: Optional[Iterable[str]] = DEFAULT_RESOURCE_TYPES):
        self.targets = list(targets) if isinstance(targets, (list, tuple)) else [targets]
        self.url_filter = _compile_filter(url_filter)
        self.business_error = business_error
        self.resource_types = set(resource_types) if resource_types else None
        self.responses: list[dict] = []
        self._listening: list = []

    def start(self):
        for t in self.targets:
            self.attach(t)
        return self

    def attach(self, target):
        """中途再挂一个页面（例如点击后弹出的新标签页）。重复挂同一个对象无副作用。"""
        if any(t is target for t in self._listening):
            return
        if not any(t is target for t in self.targets):
            self.targets.append(target)
        target.on("response", self._on_response)
        self._listening.append(target)

    def stop(self):
        for t in self._listening:
            try:
                t.remove_listener("response", self._on_response)
            except Exception:  # noqa: BLE001 —— 页面已关闭
                pass
        self._listening.clear()

    def _on_response(self, response):
        try:
            url = response.url
            if not self.url_filter(url):
                return
            req = response.request
            if self.resource_types is not None and req.resource_type not in self.resource_types:
                return
            rec = {"url": url, "method": req.method, "status": response.status, "error": None}
            if response.status >= 400:
                rec["error"] = f"HTTP {response.status}"
            body = None
            ctype = (response.headers.get("content-type") or "").lower()
            if "json" in ctype:
                try:
                    body = response.json()
                except Exception:  # noqa: BLE001 —— 响应体拿不到 / 不是合法 JSON
                    body = None
            if isinstance(body, dict):
                msg = next((str(body[k]) for k in ("msg", "message", "error") if body.get(k)), "")
                rec["msg"] = msg[:200]
            if rec["error"] is None and self.business_error is not None and body is not None:
                rec["error"] = self.business_error(body, response)
            self.responses.append(rec)
        except Exception:  # noqa: BLE001 —— 监听回调里抛异常会被 Playwright 吞掉，干脆自己兜住
            pass

    # ── 查询 ─────────────────────────────────────────────
    def errors(self, allow_status: Iterable[int] = (), allow_paths: Iterable[str] = ()) -> list[dict]:
        allow_status = set(allow_status)
        allow_paths = tuple(allow_paths)
        out = []
        for r in self.responses:
            if not r["error"]:
                continue
            if r["status"] in allow_status:
                continue
            if any(p in r["url"] for p in allow_paths):
                continue
            out.append(r)
        return out

    def clear(self):
        self.responses.clear()

    def assert_saw_traffic(self, min_count: int = 1):
        """自检：确实抓到过响应。抓包挂错页面时这里会失败，而不是让错误断言恒为空。"""
        assert len(self.responses) >= min_count, (
            f"抓包只收到 {len(self.responses)} 条响应（期望 ≥ {min_count}）——"
            f"多半是抓包没挂到用例实际操作的页面上，或 url_filter / resource_types 过严"
        )


def describe(r: dict) -> str:
    path = urlsplit(r["url"]).path or r["url"]
    return f"{r.get('method', '')} {path} → {r['error']}" + (
        f"（{r['msg']}）" if r.get("msg") and r["msg"] not in (r["error"] or "") else "")


def assert_no_error_responses(capture: ResponseCapture, allow_status: Iterable[int] = (),
                              allow_paths: Iterable[str] = ()):
    """断言抓到的响应里没有错误。报错信息逐条列出 方法 + 接口路径 + 状态码 / 业务码 + msg，
    否则只看到一个码，定位不到是哪个请求。

    allow_status / allow_paths：该场景下的**预期**错误（例如故意触发的 404、已知的限流响应），显式放行。
    """
    errs = capture.errors(allow_status=allow_status, allow_paths=allow_paths)
    assert not errs, f"检测到 {len(errs)} 个接口错误：\n" + "\n".join(f"  - {describe(r)}" for r in errs)
