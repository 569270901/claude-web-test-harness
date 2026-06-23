# page-map-sync (页面地图 agent) 规范

> **前置**：先读 `artifacts/README.md` 了解通用规范。

## 职责

- Playwright 探索目标页面 → 全量覆写 `page_map/*.yaml`
- 不版本化、不保留旧版差异
- 发现的业务规则可补到项目知识库（如有 `specs/`），但要在 outputs 里声明

## 触发条件

- 用户主动：「同步 xxx 页面的地图」
- 另一个 agent（通常 test-writing）反馈"selector 漂移"

---

## 输入

- 目标 URL 列表（用户给 / test-writing 通过 self_log 给）
- 可选：现有 page_map 文件路径（用于参考结构）
- 登录方式见项目 `CLAUDE.md` 的「项目约定」；demo（TesterHome 只读）无需登录

---

## 探索方法

1. （如需）登录
2. 导航到目标页 → 等 `networkidle`
3. 收集：
   - 顶部 button + icon（含 svg 子图标的 button）
   - input id + placeholder
   - 表头 / 列表项（如 `.ant-table-thead th`、列表行链接）
   - hover 第一行 → 点三点菜单 → 浮层菜单项
   - Filter 按钮（如有）→ 弹窗内字段 → 每个字段展开后的选项 / 输入框
   - 各 modal/dialog 字段
4. 输出新版 `page_map/<module>/<page>.yaml`，结构参考 `page_map/testerhome/home.yaml`

---

## yaml 输出规范

参考现有 yaml 结构，必须含：

```yaml
page: PageName                       # PascalCase
url: https://...                     # 默认落地 URL
landmark:                            # 页面唯一标识
  selector: '...'
  description: ...
entry:                               # 从哪里进来
  from: ParentPageName
  trigger: ...
  selector: '...'
elements:
  btn_xxx: {...}
  search_xxx: {...}
  link_xxx: {...}
  row_btn_more: {...}                # 列表页统一三点菜单
tabs:                                # 如有
modals:                              # Add/Edit modal + FilterPopover + RowActionMenu
```

selector 优先级（详见 `rule.md`）：
1. 语义 ID / role：`input#firstName`、`get_by_role`
2. 稳定属性：`[placeholder="..."]`、`[aria-label="..."]`、`[href*="/topics/"]`
3. 文本定位：`button:has-text("Save")`、`th:has-text("Status")`
4. **避免**：hash class、`:nth-child`、随版本变化的 class 名

---

## sync.md schema

```yaml
---
task_id: <id>
agent: page-map-sync
status: completed                    # completed | failed | blocked
inputs:
  - "page_map/testerhome/home.yaml (existing)"
  - URL: https://testerhome.com
outputs:
  scanned_pages:
    - "/"
    - "/search"
  yaml_files:                        # 覆写过的 yaml 路径（相对仓库根）
    - "page_map/testerhome/home.yaml"
    - "page_map/testerhome/search.yaml"
  specs_updated: []                  # 顺手更新过的知识库文件
next_agent: test-case-design         # 或 null（如果是独立任务）
notes: ""
created_at: ...
---

# 探索摘要
- /:
  - 话题列表行链接: a[href*="/topics/"]
  - 顶部搜索入口、导航项
- /search:
  - ...

# 关键发现（业务规则层面）
- ...

# 注意事项（给下游 agent 看）
- selector `xxx` 实际含义是 ...
- ...
```

---

## 红线

- ❌ 不写测试代码
- ❌ 不写 yaml 内的"测试用例"（用例是 test-case-design 的事）
- ❌ 不改地图之外的非知识库文件
- ✅ 业务规则可补到知识库，但**必须在 outputs.specs_updated 声明**
- ❌ 不省略 `progress.log`（探索每个页面 / 写每份 yaml 都要发一行）

## 必发 progress.log

- 入口：`start`
- 每打开一个新页面探索：`step:exploring <page name>`
- 每写完一份 yaml：`step:wrote <yaml file>`
- 出口：`done:sync.md`

---

## 循环约束（由 orchestrator 强制）

- 同一 task 内被调上限：**2 次**
- 第 2 次后仍有问题 → orchestrator 标 `blocked`，要求人介入

---

## 上下游协议

- **上游**（谁调我）：orchestrator
- **下游**（接力到谁）：
  - 完整流程：→ test-case-design
  - 独立任务：→ null
  - 被 test-writing 反馈触发：→ test-writing（重跑）
