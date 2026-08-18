---
task_id: 2026-06-23_testerhome_home_search
agent: test-case-design
status: confirmed
inputs:
  - "需求: TesterHome 首页（话题列表/字段/详情）+ 搜索（匿名门控）只读测试"
  - "artifacts/2026-06-23_testerhome_home_search/sync.md"
  - "page_map/testerhome/home.yaml"
  - "page_map/testerhome/search.yaml"
  - "rule.md (TesterHome 站点特有坑)"
  - "CLAUDE.md"
outputs:
  case_count: 12
  priority_breakdown: {P0: 5, P1: 5, P2: 2}
next_agent: test-writing
created_at: 2026-06-23T11:45:00Z
---

> ⚠️ **归档降级声明（2026-08-18 追加）**：本任务产出于两阶段方法论（decomp.md / GATE 0）
> 引入之前，是这套 harness 最早期的一次试跑草稿。经外部审查+核实发现：本文档描述的部分
> 实现（如 `test_search.py`、`conftest.py` 的 `td` fixture、data-driven 断言）**从未真正
> 合入代码库**，当前 `tests/` 目录下的实际文件与本文档描述不一致。保留此归档仅作历史参考，
> **不代表当前项目的实际能力**，请勿据此判断 harness 现状。真正货真价实的完整样例待接入一个
> 带登录/带状态机的真实项目后重新产出（见 `README` 的"接进你自己的项目"一节）。


# 测试用例

> **用户审阅区**：请在表格中编辑/补充/删除测试点。完成后回复"确认"或"OK"，本 artifact status 改为 confirmed，主控才会推进到 test-writing。
>
> 本批次为**匿名只读**：首页浏览 + 列表→详情，以及搜索门控。受 page-map-sync 实地发现约束——匿名提交搜索会被重定向到 `/account/sign_in`，**无任何"搜索结果命中关键词"类用例**。

## 首页（Home，只读浏览）

| # | ID | 优先级 | 测试点 | 前置 | 步骤 | 期望 | page_ref |
|---|----|------:|--------|------|------|------|----------|
| 1 | TC-HOME-001 | P0 | 首页标题含站点名 | 无 | 1. goto `/` 2. 等 networkidle | `page.title()` 包含子串 "TesterHome" | page_map/testerhome/home.yaml: url |
| 2 | TC-HOME-002 | P0 | 话题列表渲染出多行 | 无 | 1. goto `/` 2. 等 networkidle 3. 定位 `div.topic.media` | 匹配到的话题行数量 >= 10（实地约 28 行，取保守下界） | page_map/testerhome/home.yaml: topic_row |
| 3 | TC-HOME-003 | P0 | 首行话题标题链接可点且 href 指向帖子 | 无 | 1. goto `/` 2. 取首个 `div.title.media-heading a[href*="/topics/"]` | 该链接可见，且其 href 匹配正则 `/topics/\d+`（排除 `#reply-` / `/node`） | page_map/testerhome/home.yaml: topic_title_link |
| 4 | TC-HOME-004 | P0 | 首行话题标题文本非空 | 无 | 1. goto `/` 2. 取首个 `div.title.media-heading a[href*="/topics/"]` 的 inner_text | 标题文本去空白后长度 >= 2（有真实标题，非空白占位） | page_map/testerhome/home.yaml: topic_title_link |
| 5 | TC-HOME-005 | P1 | 话题行含作者名字段 | 无 | 1. goto `/` 2. 在首个 `div.topic.media` 内定位 `a.user-name` | 作者名链接可见，inner_text 去空白后长度 >= 1 | page_map/testerhome/home.yaml: topic_author_name |
| 6 | TC-HOME-006 | P1 | 话题行作者头像 href 指向用户主页 | 无 | 1. goto `/` 2. 在首个 `div.topic.media` 内定位 `div.avatar.media-left a[href^="/"]` | 头像链接可见，href 以 `/` 开头且不含 `/topics/`（指向 `/<username>`） | page_map/testerhome/home.yaml: topic_author_avatar |
| 7 | TC-HOME-007 | P1 | 话题行节点（分类）标签存在且 href 指向 node | 无 | 1. goto `/` 2. 定位 `a[href*="/topics/node"]` | 至少 1 个节点标签可见，其 href 匹配 `/topics/node\d+` | page_map/testerhome/home.yaml: node_tag_link |
| 8 | TC-HOME-008 | P1 | 顶部社区导航 href 正确 | 无 | 1. goto `/` 2. 定位 `header a[href="/topics"]` | 该导航可见，文本含 "社区"，href 为 `/topics` | page_map/testerhome/home.yaml: nav_community |

## 列表 → 详情（只读流程）

| # | ID | 优先级 | 测试点 | 前置 | 步骤 | 期望 | page_ref |
|---|----|------:|--------|------|------|------|----------|
| 9 | TC-DETAIL-001 | P0 | 点首行标题进入帖子详情页 | 在首页 | 1. goto `/` 2. 记录首个 `div.title.media-heading a[href*="/topics/"]` 的 inner_text 为 `t` 与 href 3. 点击该链接 4. 等 networkidle | `page.url` 匹配 `/topics/\d+`，且 `page.title()` 包含步骤2记录的标题文本 `t`（去空白后的非空片段） | page_map/testerhome/home.yaml: topic_title_link |

## 搜索（匿名门控，只能断言跳转 + flash）

| # | ID | 优先级 | 测试点 | 前置 | 步骤 | 期望 | page_ref |
|---|----|------:|--------|------|------|------|----------|
| 10 | TC-SEARCH-001 | P1 | 匿名顶部搜索框提交关键词被重定向到登录页 | 在首页 | 1. goto `/` 2. 在 `input[name="q"]` 填 "appium" 3. 回车提交（form GET `/search`） 4. 等 networkidle | `page.url` 以 `/account/sign_in` 结尾，且页面出现登录表单 `form#new_user` 可见 | page_map/testerhome/search.yaml: search_input / login_form |
| 11 | TC-SEARCH-002 | P2 | 匿名搜索门控显示 flash 提示文案 | 在首页 | 1. goto `/` 2. 在 `input[name="q"]` 填 "appium" 3. 回车提交 4. 等 networkidle | 页面可见文本 "继续操作前请注册或者登录。"（flash，仅重定向路径出现） | page_map/testerhome/search.yaml: flash_login_required |
| 12 | TC-SEARCH-003 | P2 | 直达 `/search?q=xxx` 同样被门控重定向 | 无 | 1. goto `/search?q=appium` 2. 等 networkidle | `page.url` 以 `/account/sign_in` 结尾，且 `input#user_login` 登录用户名框可见 | page_map/testerhome/search.yaml: url / login_username_input |

# 测试数据建议

- `home.expect_title_contains`: "TesterHome"
- `home.min_topic_rows`: 10  （实地约 28 行，留缓冲取下界）
- `home.topic_href_pattern`: `/topics/\d+`
- `home.node_href_pattern`: `/topics/node\d+`
- `search.keyword`: "appium"
- `search.redirect_url_suffix`: "/account/sign_in"
- `search.flash_text`: "继续操作前请注册或者登录。"

# 已识别的依赖

- ✅ 首页全部用例引用的元素（`topic_row` / `topic_title_link` / `topic_author_name` / `topic_author_avatar` / `node_tag_link` / `nav_community` / `search_input` / `search_form`）均在 `page_map/testerhome/home.yaml` 已覆盖。
- ✅ 搜索门控用例引用的元素（`search_input` / `flash_login_required` / `login_form` / `login_username_input`）均在 `page_map/testerhome/search.yaml` 已覆盖。
- ✅ 列表→详情（TC-DETAIL-001）只依赖首页标题链接 + URL 断言，匿名可读 `/topics/<id>`，无新元素依赖。
- ⚠️ **不设计任何"搜索结果命中关键词"用例**：受 page-map-sync 实地发现约束，匿名搜索结果页被重定向至 `/account/sign_in`，结果列表元素（search.yaml 中 `result_*` 为注释占位）匿名不可采。若产品要求测真实搜索结果，需先在 `conftest.py` 加登录 fixture，再调 page-map-sync 二次同步补全 `search.yaml` 的 `result_*`，本批次范围外。

# 给 test-writing 的提醒（来自 rule.md / sync.md）

- 话题标题断言务必用 `div.title.media-heading a[href*="/topics/"]` 并排除 `#reply-` 与 `/node`，避免命中回复锚点和节点标签。
- 行整体定位用 `div.topic.media`，勿带动态 `topic-<id>` 段。
- flash 文案只在「提交搜索→被重定向」路径出现，不要直接 goto `/account/sign_in` 找 flash（直达不带 flash）。
- 导航后用 `wait_for_load_state("networkidle")`，断言用 `expect(...)` 自动重试，勿用固定 sleep。
