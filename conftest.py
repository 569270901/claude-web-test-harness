"""pytest-playwright 公共 fixture。

pytest-playwright 已自带 `page` / `browser` 等 fixture，并通过 `--base-url`
（见 pytest.ini）提供 `base_url` fixture，测试里直接用 `base_url` 参数即可。
这个文件也是接入方放登录 fixture、page object 基类等项目专有公共件的地方。
"""
import pathlib

import pytest
import yaml

# 默认注册的执行层插件。放在根 conftest 的 pytest_plugins，而不是 pytest.ini 的 addopts（`-p ...`）：
# 调试常用 `--override-ini="addopts="` 会把 addopts 整个清空，插件跟着失效、台账悄悄漏记。
# 命令行再传 `-p tools.pytest_case_ledger` 也不会重复注册。
# - pytest_case_ledger：每条用例的结果写进 artifacts/_runs/auto_runs.jsonl（区分 xfailed / xpassed_strict）
# - pytest_guard：撞墙止损（同一定位连败 / 连续失败就停批），**默认关闭**，`--guard` 开启
# - pytest_resume：断点续跑，**默认关闭**，`--batch <名字>` 开启
pytest_plugins = ["tools.pytest_case_ledger", "tools.pytest_guard", "tools.pytest_resume"]


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args):
    """统一视口：默认 1280x720 下，宽表格 / 弹窗底部按钮容易被挤出视口导致点击失败。
    与 page-map-sync 探索时用的视口保持一致，地图里的 selector 才能在用例里复现。"""
    return {
        **browser_context_args,
        "viewport": {"width": 1600, "height": 1000},
    }


@pytest.fixture(scope="session")
def td():
    """加载 data/testerhome.yaml 的测试数据。

    项目原则：断言阈值/关键词/正则外置到 data/*.yaml，测试代码不写死——
    这样站点文案变化时改一行 yaml 就行，不用改测试代码。
    接入你自己的项目后，把这个 fixture 指向你的数据文件（或删掉，改用你已有的数据驱动层）。
    """
    path = pathlib.Path(__file__).parent / "data" / "testerhome.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))

# 接入你的项目时，在此添加登录 fixture。推荐用 utils/auth_state.py 按角色缓存登录态
# （每个角色整个 session 只真正登录一次，失效自动回落重新登录；带 TOTP 的系统尤其需要，
# 否则短用例连着登录会撞同一个 30 秒窗口）：
#
# from utils.auth_state import AuthStateCache
# _auth = AuthStateCache()
#
# def _login_admin(page):                       # 登录动作由你提供，凭据从环境变量读，绝不入库
#     page.goto(f"{BASE_URL}/account/sign_in")
#     ...填账号密码 / OTP...
#
# @pytest.fixture
# def admin_page(page, base_url):
#     return _auth.login(page, role="admin", url=f"{base_url}/dashboard",
#                        login_fn=_login_admin,
#                        is_logged_in=lambda p: p.locator("#password").count() == 0)
#
# demo（TesterHome 只读流程）无需登录，故此处留空。
