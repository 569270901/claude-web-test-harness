"""pytest-playwright 公共 fixture。

pytest-playwright 已自带 `page` / `browser` 等 fixture，并通过 `--base-url`
（见 pytest.ini）提供 `base_url` fixture，测试里直接用 `base_url` 参数即可。
这个文件也是接入方放登录 fixture、page object 基类等项目专有公共件的地方。
"""
import pathlib

import pytest
import yaml


@pytest.fixture(scope="session")
def td():
    """加载 data/testerhome.yaml 的测试数据。

    项目原则：断言阈值/关键词/正则外置到 data/*.yaml，测试代码不写死——
    这样站点文案变化时改一行 yaml 就行，不用改测试代码。
    接入你自己的项目后，把这个 fixture 指向你的数据文件（或删掉，改用你已有的数据驱动层）。
    """
    path = pathlib.Path(__file__).parent / "data" / "testerhome.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))

# 接入你的项目时，在此添加登录 fixture，例如：
#
# @pytest.fixture
# def logged_in_page(page, base_url):
#     page.goto(f"{base_url}/account/sign_in")
#     ...你的登录逻辑...
#     return page
#
# demo（TesterHome 只读流程）无需登录，故此处留空。
