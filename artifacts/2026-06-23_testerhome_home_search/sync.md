---
task_id: 2026-06-23_testerhome_home_search
agent: page-map-sync
status: completed
inputs:
  - "artifacts/README.md"
  - "artifacts/agents/page-map-sync.md"
  - "CLAUDE.md"
  - "rule.md"
  - "pytest.ini (base_url=https://testerhome.com)"
  - URL: https://testerhome.com/
  - URL: https://testerhome.com/search
  - URL: https://testerhome.com/account/sign_in
  - URL: https://testerhome.com/topics
outputs:
  scanned_pages:
    - "/"
    - "/topics"
    - "/search (匿名重定向到 /account/sign_in)"
    - "/account/sign_in"
  yaml_files:
    - "page_map/testerhome/home.yaml"
    - "page_map/testerhome/search.yaml"
  specs_updated:
    - "rule.md (新增 TesterHome 站点特有坑：搜索鉴权门控、flash 时机、话题链接去噪等)"
next_agent: test-case-design
notes: "搜索结果页对匿名用户鉴权门控，匿名只读无法采集结果列表元素；search.yaml 记录了门控行为与登录落地页元素，result_* 元素留作登录态二次同步的占位。"
created_at: 2026-06-23T11:30:00Z
---

> ⚠️ **归档降级声明（2026-08-18 追加）**：本任务产出于两阶段方法论（decomp.md / GATE 0）
> 引入之前，是这套 harness 最早期的一次试跑草稿。经外部审查+核实发现：本文档描述的部分
> 实现（如 `test_search.py`、`conftest.py` 的 `td` fixture、data-driven 断言）**从未真正
> 合入代码库**，当前 `tests/` 目录下的实际文件与本文档描述不一致。保留此归档仅作历史参考，
> **不代表当前项目的实际能力**，请勿据此判断 harness 现状。真正货真价实的完整样例待接入一个
> 带登录/带状态机的真实项目后重新产出（见 `README` 的"接进你自己的项目"一节）。


# 探索摘要

实地用 Playwright（headless chromium）匿名访问，等 `networkidle` 后采集。

- **/（首页 Home）**：
  - 顶部导航：测试之家 `/`、社区 `/topics`、问答 `/questions`、招聘 `/jobs`、社区学堂 `/training_courses`、开源项目 `/opensource_projects`、活动 `/events`、Wiki `/wiki`、注册/登录。
  - 搜索入口：头部 `input[name="q"]` placeholder「搜索」，外层 `form[action="/search"]` GET。
  - 话题列表：约 28 行，行容器 `div.topic.media`（class 另含动态 `topic-<id>`）。
    - 标题链接 `div.title.media-heading a[href*="/topics/"]`（href 形如 `/topics/44095`）。
    - 作者头像 `div.avatar.media-left a[href^="/"]`（href `/<username>`），作者名 `a.user-name`。
    - 回复数角标 `a.state-false[href*="#reply-"]`。
    - 节点标签 `a[href*="/topics/node"]`（如 Appium=node23）。
  - 无 hover 三点菜单、无 Filter 弹窗、无 modal（纯服务端渲染）。

- **/search（Search）**：
  - 匿名访问被门控：`GET /search?q=appium` → 200 但最终 URL = `/account/sign_in`，flash「继续操作前请注册或者登录。」。
  - 落地登录页元素：`form#new_user`，`input#user_login`（user[login]）、`input#user_password`（user[password]）、`input#user_remember_me`、`input[name="commit"][type=submit]`。
  - 真实搜索结果列表元素本次匿名无法采集，已在 search.yaml 以注释 `result_*` 占位。

# 关键发现（业务规则层面）

1. **搜索是登录后功能**：TesterHome 的站内搜索结果页对未登录用户不可见，统一重定向到登录页并提示注册/登录。这直接约束了「只读搜索」用例——匿名只能验证「触发搜索 → 跳转登录 + flash 文案」，验证不了关键词命中结果。
2. **flash 提示依赖来源**：登录页的「继续操作前请注册或者登录。」flash 仅在从门控页被重定向时出现；直接 goto 登录页不带 flash。
3. 站点为 Homeland/RubyChina 系服务端渲染，selector 语义稳定无 hash class，但话题行 class 带动态 `topic-<id>` 段。

# 注意事项（给下游 test-case-design / test-writing）

- **搜索用例只能做到「跳转断言」**：匿名提交搜索后断言 `page.url` 落到 `/account/sign_in` 且页面含 flash 文案；不要写「搜索 appium 应出现含 appium 的结果」这类需登录的断言，会失败。若产品要求测真实搜索结果，须先在 conftest.py 加登录 fixture，再让 page-map-sync 二次同步补全 search.yaml 的 `result_*`（当前注释占位）。
- **话题标题断言要去噪**：`a[href*="/topics/"]` 会命中回复锚点（`a.state-false`，href 带 `#reply-`）和节点标签（href 带 `/node`）。断言话题标题用 `div.title.media-heading a[href*="/topics/"]`，并排除 `#reply-` / `/node`。
- **打开帖子详情**：可点首页任一 `div.title.media-heading a[href*="/topics/"]` 进入 `/topics/<id>`，匿名可读，适合做「列表→详情」只读流程。
- **行定位**用 `div.topic.media`，勿用带 id 的 `topic-44095`。
- rule.md 已补「TesterHome 站点特有坑」一节，写测试前请先读。
