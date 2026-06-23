# test-case-design (测试用例输出 agent) 规范

> **前置**：先读 `artifacts/README.md` 了解通用规范。

## 职责

- 读需求（用户贴的 markdown）+ 现有 page_map + 项目知识库
- 输出测试用例清单
- **不一定接 test-writing**（用例 agent 可独立使用，比如只给手工测试用）

## 触发

- 用户主动：「为 xxx 设计测试用例」 / 「根据这份需求出用例」

---

## 输入

- 需求内容（markdown，用户贴）
- task 范围（哪个模块、哪个页面、哪个流程等）
- 必读：
  - 相关 `page_map/<module>/*.yaml`
  - 项目知识库（如有 `specs/`）
  - `CLAUDE.md` 中的项目原则

---

## 测试点提取原则

1. **覆盖功能正向流程**（P0）
2. **覆盖业务规则边界**（P1） — 来自知识库中"约束与限制"
3. **覆盖异常 / 兼容性**（P2） — 来自知识库中"高风险场景"
4. **每个测试点关联 page_map 元素**（page_ref 字段）
5. **粒度建议中粒度**：一个测试点 ≈ 一个 `def test_xxx`

---

## cases.md schema

```yaml
---
task_id: <id>
agent: test-case-design
status: pending_review               # ← 关键：等用户编辑确认
inputs:
  - "需求: <用户贴的 markdown 摘要/路径>"
  - "page_map/testerhome/home.yaml"
outputs:
  case_count: 3
  priority_breakdown: {P0: 2, P1: 1, P2: 0}
next_agent: null                     # 用户确认后 orchestrator 才填 test-writing
created_at: ...
---

# 测试用例

> **用户审阅区**：请在表格中编辑/补充/删除测试点。完成后回复"确认"或"OK"，本 artifact status 改为 confirmed，主控才会推进到 test-writing。

| # | ID | 优先级 | 测试点 | 前置 | 步骤 | 期望 | page_ref |
|---|----|------:|--------|------|------|------|----------|
| 1 | TC-HOME-001 | P0 | 首页标题含站点名 | 直接访问首页 | 1. goto / | 标题包含 "TesterHome" | page_map/testerhome/home.yaml: landmark |
| 2 | TC-HOME-002 | P0 | 首页话题列表可见 | 直接访问首页 | 1. goto / 2. 等 networkidle | 至少 1 个 a[href*="/topics/"] 可见 | page_map/testerhome/home.yaml: link_topic |
| 3 | TC-SEARCH-001 | P1 | 搜索关键词出结果 | 在搜索页 | 1. 进 /search 2. 输入 "appium" 3. 提交 | 结果区出现含 "appium" 的文本 | page_map/testerhome/search.yaml: input_query |

# 测试数据建议

- search.keyword: "appium"
- home.expect_title_contains: "TesterHome"

# 已识别的依赖

- ⚠️ TC-SEARCH-001 引用 `page_map/testerhome/search.yaml`，**当前未发现**该页地图，需先调 page-map-sync 探索 /search
- ✅ 首页相关元素在 `page_map/testerhome/home.yaml` 已覆盖
```

---

## 红线

- ❌ **不能引用 page_map 里不存在的元素** — 硬校验。如果发现需求涉及的元素 page_map 没有，必须：
  - 在 cases.md 的「已识别的依赖」段标注「需先调 page-map-sync 探索 xxx」
  - 设 `status=pending_review`，让用户决定是回去同步地图还是先出用例
- ❌ 不写代码
- ❌ 不修改其他 artifact
- ❌ 不替用户决定"用例够不够"——一律 status=`pending_review` 让用户审
- ❌ 不省略 `progress.log`（每个里程碑必发一行）

## 必发 progress.log

- 入口：`start`
- 每读完一份需求 / 知识库：`step:loaded <file>`
- 每输出一组用例：`step:designed N cases for <module>`
- 出口（进入审核）：`gate:cases_review` + `done:cases.md`

---

## Human Gate（关键）

- 产出后 status 永远是 `pending_review`
- **orchestrator 不自动推进**
- 用户编辑 cases.md 后回复"确认/OK/通过" → 改 status=`confirmed` → orchestrator 才接力 test-writing

---

## 上下游协议

- **上游**：orchestrator（路由后调用）
- **下游**：
  - 用户确认后：→ test-writing
  - 用户只想要用例不写自动化：→ null（任务结束）

---

## 输出格式注意

- 表格用 markdown 表格（用户能直接编辑）
- 每个用例的"步骤"段尽量含可执行的关键动作（点哪个按钮、填什么值），不写概念性描述
- "期望"段必须可断言（避免「正常显示」这种模糊词）
