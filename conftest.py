"""pytest-playwright 公共 fixture。

pytest-playwright 已自带 `page` / `browser` 等 fixture，并通过 `--base-url`
（见 pytest.ini）提供 `base_url` fixture，测试里直接用 `base_url` 参数即可。
这个文件留给接入方放登录 fixture、page object 基类等项目专有的公共件。
"""

# 接入你的项目时，在此添加登录 fixture，例如：
#
# @pytest.fixture
# def logged_in_page(page, base_url):
#     page.goto(f"{base_url}/account/sign_in")
#     ...你的登录逻辑...
#     return page
#
# demo（TesterHome 只读流程）无需登录，故此处留空。
