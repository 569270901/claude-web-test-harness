---
task_id: 2026-06-23_testerhome_home_search
agent: test-writing
status: completed
inputs:
  - "artifacts/2026-06-23_testerhome_home_search/cases.md"
  - "page_map/testerhome/home.yaml"
  - "page_map/testerhome/search.yaml"
  - "rule.md"
  - "CLAUDE.md"
outputs:
  files_changed:
    - "tests/test_home.py"
    - "tests/test_search.py"
    - "tests/conftest.py"
    - "data/testerhome.yaml"
  test_run_summary:
    passed: 12
    failed: 0
    duration_sec: 74
    test_ids:
      - "tests/test_home.py::test_home_title"            # TC-HOME-001
      - "tests/test_home.py::test_home_topic_rows_rendered"  # TC-HOME-002
      - "tests/test_home.py::test_home_first_topic_link_href"  # TC-HOME-003
      - "tests/test_home.py::test_home_first_topic_title_text"  # TC-HOME-004
      - "tests/test_home.py::test_home_topic_author_name"  # TC-HOME-005
      - "tests/test_home.py::test_home_topic_author_avatar_href"  # TC-HOME-006
      - "tests/test_home.py::test_home_node_tag_link"      # TC-HOME-007
      - "tests/test_home.py::test_home_nav_community"       # TC-HOME-008
      - "tests/test_home.py::test_detail_open_first_topic"  # TC-DETAIL-001
      - "tests/test_search.py::test_search_submit_redirects_to_signin"  # TC-SEARCH-001
      - "tests/test_search.py::test_search_gate_flash_text"  # TC-SEARCH-002
      - "tests/test_search.py::test_search_direct_url_redirects"  # TC-SEARCH-003
  self_repair_rounds: 1
next_agent: review
notes: "全部 12 用例通过。Round 1 暴露 1 处 page_map 漂移（nav 无 <header> 标签），已用稳定 ID 容器在测试侧绕过，建议 orchestrator 派 page-map-sync 更新 home.yaml 的 nav_* selector。"
created_at: 2026-06-23T13:40:00Z
---

# 实现摘要

按 confirmed cases.md 的 12 条用例生成只读测试，全部对 live 站点 https://testerhome.com 真实通过。

- `tests/test_home.py`：TC-HOME-001~008 + TC-DETAIL-001（首页标题、话题列表行数、首行标题链接 href/文本、作者名/头像、节点标签、社区导航、列表→详情）。
- `tests/test_search.py`：TC-SEARCH-001~003（匿名搜索门控：提交/直达均被重定向到 `/account/sign_in`，断言登录表单可见 + flash 文案）。
- `tests/conftest.py`：新增 session 级 `td` fixture，加载 `data/testerhome.yaml`，所有断言阈值/关键词/正则外置，代码不写死。
- `data/testerhome.yaml`：补全 home/search 数据驱动值。

## selector 策略（合规）
- 行整体 `div.topic.media`（不带动态 `topic-<id>`）。
- 标题链接 `div.title.media-heading a[href*="/topics/"]`，正则 `/topics/\d+` 并显式排除 `#reply-` 与 `/topics/node`。
- 节点标签 `a[href*="/topics/node"]`，正则 `/topics/node\d+`。
- 搜索框 `input[name="q"]`、登录表单 `form#new_user`、用户名框 `input#user_login`。
- 无 `:nth-child` / xpath 位置索引 / 通配 `*` / hash class。compliance 自扫唯一命中在 docstring 注释里（引用 rule.md），非真实 selector。

## 断言完整性
- 所有有意义字段都断言，未删/未弱化任何断言，未出现 expected="0"/"-"/空。
- 文本型断言用「包含子串」+ `expect(...)` 自动重试，避免格式漂移与时序抖动。

# 自修日志

## Round 1（9 passed / 3 failed）
三处失败，逐一归因：

1. **TC-HOME-001 `test_home_title`** — 断言 `"TesterHome" in page.title()` 失败，实际 title 为 `'测试之家'`。
   - 决策依据：**cases.md 的数据假设错误**，不是 bug。站点首页 `<title>` 实地就是中文名「测试之家」（与 page_map `home.yaml` 中 `nav_home text: 测试之家` 一致）。`expect_title_contains: "TesterHome"` 是 test-case-design 凭站点英文名臆测的值。
   - 修法：改 `data/testerhome.yaml` 的 `home.expect_title_contains` → `"测试之家"`（有语义的真实值，未弱化为空/"0"/"-"）。属修数据，断言强度不变。

2. **TC-DETAIL-001 `test_detail_open_first_topic`** — 进入详情页后 `title_text in page.title()` 失败，断言时 title 仍是 `'测试之家'`。
   - 决策依据：**非 bug，是时序问题**。实地验证：点击后 `networkidle` 即刻读 `<title>` 仍为旧值 `'测试之家'`，稍后 `<title>` 切换为 `'<帖子标题> · 测试之家'`（`wait_for_function` 10s 内稳定命中）。即详情页确实带正确标题，只是 `<title>` 切换晚于 networkidle。
   - 修法：把一次性 `assert ... in page.title()` 换成 `expect(page).to_have_title(re.compile(re.escape(title_text)))`，用 Playwright 自动重试等 title 更新。断言语义与强度不变（仍要求详情页标题包含列表标题文本）。

3. **TC-HOME-008 `test_home_nav_community`** — `header a[href="/topics"]` 5s 找不到。
   - 决策依据：**page_map 漂移（真实问题）**。实地探查：页面**没有 `<header>` 标签**（`page.locator("header").count()==0`，`nav` 同样为 0）；社区导航实际位于 `div.header.navbar > div#main-navbar > ul#main-nav-menu > li.nav-item > a.nav-link[href="/topics"]`（文本「社区」，全局 `a[href="/topics"]` count=1）。`home.yaml` 把多个 `nav_*` 写成 `header a[...]` 是错的（`<header>` 不存在）。
   - 修法（守红线，不直接改 page_map）：在测试侧改用**稳定 ID 容器** `div#main-navbar a[href="/topics"]`（ID 定位，非 nth-child/xpath/hash，合规），并将容器 selector 外置到 `data` 的 `home.nav_container_selector`。**已在 notes 标注，建议 orchestrator 派 page-map-sync 更新 home.yaml 的 `nav_community`/`nav_*` selector 由 `header ...` → `div#main-navbar ...`。**

## Round 2（12 passed / 0 failed）
三处修复后全绿，收敛。无 likely_bug，无超限。

# 给 review / orchestrator 的提示
- 12 条用例与 cases.md 一一对应（见 frontmatter test_ids 行内注释）。
- 唯一遗留：**home.yaml 的 nav_* selector 仍写 `header ...`，与实地 `div#main-navbar ...` 不符**。本 agent 红线禁止直接改 page_map，已在测试侧用合规稳定 selector 绕过并外置到 data；建议后续派 page-map-sync 修正地图，使地图与测试一致。
- 搜索三条用例严格只断言「匿名门控」行为（重定向 + 登录表单 + flash），未越界测登录态搜索结果，符合 cases.md 范围约束。
