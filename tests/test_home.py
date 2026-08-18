"""TesterHome 首页只读测试（示例 / 黄金参照）。

这是手写的种子测试，证明脚手架能跑通，也给 test-writing agent 一个风格参照。
全部只读：不注册、不登录、不发帖。selector 是种子值，若站点改版，
让 page-map-sync 刷新 page_map/testerhome/home.yaml 后据此调整。

断言阈值外置到 data/testerhome.yaml（`td` fixture，见 conftest.py），不写死在代码里——
这是本项目的数据驱动原则，也是这份种子测试本身要示范的写法。
"""
import re

from playwright.sync_api import Page, expect


def test_home_title(page: Page, base_url: str, td):
    """访问首页，标题应包含 data/testerhome.yaml 里配置的站点名。"""
    page.goto(base_url)
    expected = td["home"]["expect_title_contains"]
    expect(page).to_have_title(re.compile(re.escape(expected)))


def test_home_has_topic_links(page: Page, base_url: str):
    """首页话题列表应至少有一个指向帖子详情(/topics/<id>)的链接。"""
    page.goto(base_url)
    page.wait_for_load_state("networkidle")
    topic_links = page.locator('a[href*="/topics/"]')
    expect(topic_links.first).to_be_visible()
