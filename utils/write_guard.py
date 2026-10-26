# -*- coding: utf-8 -*-
"""写请求保护（WriteGuard）—— 只读用例的兜底：保证"只是看一眼"的用例绝不改动环境里的数据。

为什么要有它：很多用例本意只是"打开弹窗看一眼文案 / 点 Cancel 关掉"。一旦页面改版让 Cancel
变成了 Save、或者 selector 点偏到了提交按钮，用例会**悄悄改掉共享测试环境里别人的真实数据**
（甚至触发发邮件 / 站内信这类收不回来的副作用），而且用例本身还可能是绿的。
挂上 WriteGuard 后，写请求在浏览器层就被拦下、根本发不出去，并被记录；用例结尾 `assert_clean()`
断言一次都没尝试过——"误点了保存"会变成一条失败的用例，而不是一条脏数据。

能力：
- 拦截：方法属于 `methods`（默认 POST / PUT / DELETE / PATCH）的请求一律 `abort()`，并记进 `attempts`
- 放行：
  1. `pass_through` —— 默认放行 URL 里含 login / logout / token / refresh / auth 的请求
     （登录、刷新令牌这类接口通常是 POST，拦了会把会话弄掉，页面直接跳回登录页）。
     **按你的项目改**：传正则字符串 / 编译好的正则 / `callable(url) -> bool`，传 None 表示不放行任何写请求
  2. `allow` —— 额外放行的 URL 子串白名单（例如某页面的"名称是否重复"校验接口是 POST，属只读语义）
- `release()`：摘掉保护（同一用例里先做只读校验、之后要真写**自己新建的**数据时用；之后写请求不再被拦）
- `PostRecorder`：WriteGuard 子类，额外记下被拦请求的方法 / 路径 / 请求体——用来取证"点提交时
  前端到底会发什么"，但请求同样不到达服务端、不落库

用法：
    from utils.write_guard import WriteGuard, PostRecorder

    guard = WriteGuard(page)                        # page 或 BrowserContext 都行（context 能覆盖弹出的新页）
    ... 只读操作 ...
    guard.assert_clean()

    rec = PostRecorder(page)
    try:
        page.get_by_role("button", name="Submit").click()
        page.wait_for_timeout(1000)                 # 等前端把请求发出来（被拦下）
    finally:
        rec.release()
    method, path, body = rec.bodies[-1]             # 断言请求体里的字段

适用边界：只适合确认页面**读数据全走 GET** 的场景。有些系统的查询接口也用 POST（如分页搜索），
挂上会被误拦、页面显示加载失败——这种页面要么把查询接口加进 `allow`，要么别用 WriteGuard。
被拦的请求在页面里表现为网络错误，页面可能弹出报错提示，这是预期现象。
"""
import re
from typing import Callable, Iterable, Union
from urllib.parse import urlsplit

WRITE_METHODS = ("POST", "PUT", "DELETE", "PATCH")

# 默认放行规则：登录 / 登出 / 令牌 / 刷新 / 认证类接口。按单词片段匹配、大小写不敏感。
# 接入项目时按实际接口名收紧或放宽，例如 r"/api/(session|oauth2?)/"。
DEFAULT_PASS_THROUGH = r"(?i)(login|logout|token|refresh|auth)"

UrlRule = Union[str, re.Pattern, Callable[[str], bool], None]


def _compile_rule(rule: UrlRule) -> Callable[[str], bool]:
    if rule is None:
        return lambda url: False
    if callable(rule) and not isinstance(rule, re.Pattern):
        return rule
    pat = re.compile(rule) if isinstance(rule, str) else rule
    return lambda url: bool(pat.search(url))


def short_path(url: str, strip_prefix: str = "") -> str:
    """把完整 URL 缩成便于阅读的路径：去掉协议 / 域名 / 查询串，可选再去掉一段公共前缀（如 "/api"）。"""
    path = urlsplit(url).path or url
    if strip_prefix and path.startswith(strip_prefix):
        path = path[len(strip_prefix):] or "/"
    return path


class WriteGuard:
    """拦截写请求的路由守卫。

    Args:
        target: Playwright Page 或 BrowserContext（二者都有 route / unroute）。
        allow: 额外放行的 URL 子串白名单。
        pass_through: 放行规则（正则字符串 / 正则 / callable(url)->bool / None），默认 DEFAULT_PASS_THROUGH。
        url_pattern: 交给 `route()` 的 URL 匹配（glob / 正则 / callable），默认 "**/*" 全部经过守卫；
            只想守住业务接口时可以收窄，例如 "**/api/**"。
        methods: 视为"写"的 HTTP 方法。
        path_prefix: 记录 / 报错时从路径里去掉的公共前缀，纯展示用。
    """

    def __init__(self, target, allow: Iterable[str] = (), pass_through: UrlRule = DEFAULT_PASS_THROUGH,
                 url_pattern="**/*", methods: Iterable[str] = WRITE_METHODS, path_prefix: str = ""):
        self.attempts: list[str] = []
        self.allow = tuple(allow)
        self.methods = tuple(m.upper() for m in methods)
        self.path_prefix = path_prefix
        self._is_pass_through = _compile_rule(pass_through)
        self._target = target
        self._pattern = url_pattern
        self._active = True
        target.route(self._pattern, self._handle)

    # ── 判定 ─────────────────────────────────────────────
    def is_blocked(self, method: str, url: str) -> bool:
        if method.upper() not in self.methods:
            return False
        if self._is_pass_through(url):
            return False
        return not any(a in url for a in self.allow)

    def _on_blocked(self, request):
        """子类扩展点：请求被拦下时调用（在 abort 之前）。"""

    def _handle(self, route):
        req = route.request
        if self._active and self.is_blocked(req.method, req.url):
            self.attempts.append(f"{req.method} {short_path(req.url, self.path_prefix)}")
            self._on_blocked(req)
            route.abort()
        else:
            # fallback 而不是 continue_：把请求交给更早注册的 route（用例自己的 mock 等），
            # 没有其他 route 时等同于正常发出
            route.fallback()

    # ── 生命周期 ─────────────────────────────────────────
    def release(self):
        """摘掉保护，之后的写请求正常发出。可重复调用。"""
        if not self._active:
            return
        self._active = False
        try:
            self._target.unroute(self._pattern, self._handle)
        except Exception:  # noqa: BLE001 —— 页面已关闭时 unroute 会抛，摘不摘都无所谓了
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.release()
        return False

    def assert_clean(self):
        assert not self.attempts, (
            f"只读用例不应发出写请求，但尝试了 {self.attempts}（已被拦截，没有改动任何数据）——"
            f"多半是页面改版让取消按钮 / selector 点到了提交，先查清再改用例；"
            f"若确属只读语义的 POST 查询接口，加进 allow 白名单"
        )


class PostRecorder(WriteGuard):
    """WriteGuard 子类：记下被拦写请求的 (方法, 路径, 请求体)，请求本身同样不发出。

    用途：取证"点提交时前端到底会提交什么"，而不真的落库（不污染环境、不触发通知）。
    `bodies` 里的请求体是原始字符串，JSON 接口用 `json.loads(body)` 再断言字段。
    """

    def __init__(self, target, **kwargs):
        self.bodies: list[tuple[str, str, str]] = []
        super().__init__(target, **kwargs)

    def _on_blocked(self, request):
        self.bodies.append((request.method, short_path(request.url, self.path_prefix), request.post_data or ""))
