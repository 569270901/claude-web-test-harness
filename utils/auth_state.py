# -*- coding: utf-8 -*-
"""登录态复用模板 —— 按角色缓存 storage_state，失效自动回落重新登录。

问题背景：每条用例的登录 fixture 都重新走一遍完整登录，用例一多既慢又脆。带 TOTP 的系统更糟：
码 30 秒一变、服务端一次性校验，短用例连着跑会把多次登录挤进同一个 30 秒窗口 → 拿到同一个码
→ 服务端判"已使用" → 整批用例死在登录步，看上去像一大片功能故障。

解法：整个 pytest session 里每个角色只真正登录一次，把 cookie + localStorage 缓存下来；后续用例
注入到各自的新 context，跳过登录。注入后做登录态校验，失效则自动回落到重新登录并刷新缓存。

本模块与站点无关：**怎么登录、怎么判断已登录由调用方传回调**，OTP 可选（见 totp_window_wait）。

接入示例（放在你的 conftest.py；demo 站点无需登录，所以默认不接入）：

    from utils.auth_state import AuthStateCache

    _auth = AuthStateCache()

    def _login_admin(page):
        page.goto(f"{BASE}/login")
        page.fill("#username", os.environ["ADMIN_USER"])      # 凭据从环境变量 / 本地配置读，绝不入库
        page.fill("#password", os.environ["ADMIN_PASS"])
        page.click("button[type=submit]")
        page.wait_for_url("**/dashboard")

    def _is_logged_in(page):
        return page.locator("#username").count() == 0

    @pytest.fixture
    def admin_page(page):
        return _auth.login(page, role="admin", url=f"{BASE}/dashboard",
                           login_fn=_login_admin, is_logged_in=_is_logged_in)
"""
import time
from typing import Callable

# 登录回调：在给定 page 上完成一次完整登录（含 OTP 等），结束时应已进入应用内页
LoginFn = Callable[[object], None]
# 登录态校验回调：page 已在目标 url 上，返回是否处于"正确角色的已登录态"
CheckFn = Callable[[object], bool]


def totp_window_wait(period: int = 30, margin: float = 2.0) -> float:
    """TOTP 防撞车：等到下一个时间窗口再取码，返回实际等待秒数。

    只在"刚用过同一个 secret 取码、紧接着又要登录"时调用（例如预检脚本刚登录过）。
    正常情况下有了登录态缓存，一个角色整个 session 只取一次码，用不到它。
    """
    wait = period - time.time() % period + margin
    time.sleep(wait)
    return wait


def _default_is_logged_in(page) -> bool:
    """兜底校验：页面上没有密码输入框就当已登录。

    ⚠️ 只查"没有登录表单"往往不够：多个角色共用同一域名时，残留的另一个角色登录态同样没有
    登录表单，但会落到无权限页。真实项目请传 is_logged_in，把"无权限"页一并识别出来，
    否则误判成功、连重新登录的兜底都不会触发。
    """
    return page.locator('input[type="password"]').count() == 0


class AuthStateCache:
    """session 级登录态缓存：role -> storage_state dict（{cookies: [...], origins: [...]}）。"""

    def __init__(self):
        self._states: dict[str, dict] = {}

    def clear(self, role: str | None = None):
        if role is None:
            self._states.clear()
        else:
            self._states.pop(role, None)

    @staticmethod
    def _reset_context(page, url: str):
        """清掉当前 context 的登录残留（等效登出）。

        顺序很重要：**先清存储、再动 cookie**。SPA 在页面加载瞬间就会用残留的 localStorage
        初始化身份（甚至回写 cookie），先注 cookie 再清 localStorage 就清晚了。
        """
        origin = "/".join(url.split("/")[:3])
        try:
            page.goto(origin, wait_until="domcontentloaded")
        except Exception:
            time.sleep(1)  # 清 cookie 后首跳可能被 SPA 重定向打断（ERR_ABORTED），重进一次
            page.goto(origin, wait_until="domcontentloaded")
        page.evaluate("localStorage.clear(); sessionStorage.clear();")
        page.context.clear_cookies()

    def _inject(self, page, url: str, state: dict, is_logged_in: CheckFn) -> bool:
        """把缓存的 cookie + localStorage 注入当前 context，返回登录态是否有效。"""
        try:
            for origin in state.get("origins") or [{"origin": "/".join(url.split("/")[:3])}]:
                self._reset_context(page, origin["origin"])
            if state.get("cookies"):
                page.context.add_cookies(state["cookies"])
            for origin in state.get("origins") or []:
                if origin.get("localStorage"):
                    page.goto(origin["origin"], wait_until="domcontentloaded")
                    page.evaluate(
                        "items => { for (const it of items) localStorage.setItem(it.name, it.value); }",
                        origin["localStorage"],
                    )
            page.goto(url)
            page.wait_for_load_state("networkidle")
            return bool(is_logged_in(page))
        except Exception:
            return False

    def login(self, page, role: str, url: str, login_fn: LoginFn,
              is_logged_in: CheckFn | None = None):
        """返回已登录（role 身份、停在 url）的 page。优先复用缓存，失效则重新登录并刷新缓存。"""
        check = is_logged_in or _default_is_logged_in
        state = self._states.get(role)
        if state and self._inject(page, url, state, check):
            return page

        # 无缓存或注入失效 → 先清残留态再走真正的登录
        try:
            self._reset_context(page, url)
        except Exception:
            pass
        login_fn(page)
        page.goto(url)
        page.wait_for_load_state("networkidle")
        if not check(page):
            raise AssertionError(f"角色 {role} 登录后校验失败（仍不在已登录态）：{page.url}")
        try:
            self._states[role] = page.context.storage_state()
        except Exception:
            pass
        return page
