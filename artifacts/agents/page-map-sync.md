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
- **confirmed flow.md（如任务有）**——探索时的核对基准：逐项核对实际 UI 与其记录的操作流/
  文案字面值，不一致在 sync.md 单列「与 flow.md 的偏差」；flow.md 标 `⚠️待实测` 的值
  （maxlength/toast/接口行为）在探索中顺手取证补上
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
  upload_xxx:                        # ⬇ 动力学字段：有异步副作用的元素必须记满
    selector: 'input#file'
    kind: upload                     # 交互类型：upload / submit / advance
    async:
      request: 'POST /api/upload'                        # 探索时实际触发一次抓包取证
      settled: '.upload-item-success'                     # "真正完成"的 DOM 证据
    gates: btn_continue              # 未 settled 时会静默拦截哪个动作（前端校验不弹任何错）
tabs:                                # 如有
modals:                              # Add/Edit modal + FilterPopover + RowActionMenu
flows:                               # ⬇ 页面级交互流：多步表单必填
  steps:
    indicator: 'text=/Step \d of 3/' # 当前步指示器
    total: 3
    dom: coexist-hidden              # 各步 DOM 共存、切可见性 → 字段 count>0 ≠ 在当前步
    advance:
      trigger: 'button:has-text("Continue")'
      gated_by: form-validation      # 校验不过 = 静默拦截，页面停在原步、零提示
      success_evidence: indicator-text-change
      failure_probe: '.form-error-message'   # 排查拦截原因看这里
```

**知识分家原则**：通用组件行为（stale dropdown、mask 动画、DatePicker 裁切等"某组件库在本项目
怎么表现"）沉淀在 `rule.md` + 引擎共享 helper，**不进 page_map**；只有**页面特有**的动力学
（接口 URL、settle 证据、gate 关系、步骤结构）才写进 yaml。

selector 优先级：
1. 语义 ID / role：`input#firstName`、`get_by_role`
2. 稳定属性：`[placeholder="..."]`、`[aria-label="..."]`、`[href*="/topics/"]`
3. 文本定位：`button:has-text("Save")`、`th:has-text("Status")`
4. **避免**：hash class、`:nth-child`、随版本变化的 class 名

---

## 验收标准（写进 yaml 的每个 selector 都要有证据）

> 背景：凭视觉印象猜的 selector（如猜标题标签是 h1 而实际是 h5）一旦写进 yaml，等到下游用例
> 跑批时才会暴露，返工成本远高于探索阶段多花一分钟核实。下面这套标准就是为了把验证前移。

1. **每个 selector 必须有实测证据**：`locator.count() >= 1` 探针、heading/DOM dump、或实际点击
   成功三者之一。禁止「视觉候选写法」入 yaml。
2. **关键交互路径完整走通**：多步表单、modal 提交等，走通一遍后对标题/关键元素 heading dump
   复核，再定稿 selector。
3. **怀疑项交叉验证**：同一目标两种写法各测 count，不一致必须查明（防组件库旧 dropdown 留 DOM
   仅加 hidden class 的假匹配）。
4. **confidence 分级申报**：sync.md 的 `outputs.confidence` 逐 yaml 标 `verified` / `unverified`
   （含未实测区域与原因）。环境不可用、探索被阻断（如接口 500）时如实标 unverified —— 下游
   test-writing 对 unverified 项降级信任、优先实跑冒烟。
5. **交互动力学取证**：凡 `kind ∈ upload / submit / advance` 的元素，探索时必须**实际触发一次**
   并开 network 捕获，把 `async.request / async.settled / gates` 写实测值；多步表单必须填
   `flows.steps`（indicator / dom 共存方式 / advance 的 gate 与 failure_probe）。动作不可逆
   （如正式提交、删除确认）无法触发时，标 unverified 并写明原因，禁止编造。
   > 地图缺动力学字段而实测发现异步行为，是"提交后翻页卡死"这类问题最常见的根因——测试代码
   > 只能靠固定 sleep 赌时间，赌不准就偶发失败。**地图格式即探索验收标准**。

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
  confidence:                        # 逐 yaml 证据等级
    "page_map/testerhome/home.yaml": verified
    "page_map/testerhome/search.yaml": "unverified — Filter 弹窗被接口 500 阻断，仅收录顶栏与表头"
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
- ❌ 不写没有实测证据的 selector（见上方验收标准）
- ✅ 业务规则可补到知识库，但**必须在 outputs.specs_updated 声明**
- ❌ 不省略 `progress.log`（探索每个页面 / 写每份 yaml 都要发一行）

## 必发 progress.log

- 入口：`start`
- 每打开一个新页面探索：`step:exploring <page name>`
- 每写完一份 yaml：`step:wrote <yaml file>`
- 出口：`done:sync.md`

详见 `artifacts/README.md` 的 Progress Log 一节。

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
