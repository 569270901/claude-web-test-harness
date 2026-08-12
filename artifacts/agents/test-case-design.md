# test-case-design (测试用例输出 agent) 规范

> **前置**：先读 `artifacts/README.md` 了解通用规范。

## 职责（两阶段，由 orchestrator 分两次派发，派发 prompt 指明阶段）

**阶段1 = 解构**（拿到需求即可派发）：
1. 读需求（用户贴的 markdown）+ **UI 设计图（截图，用 Read 读图）** + `page_map` + 项目知识库 + 已有用例
2. 判定输入档位（A 有完整需求文档 / B 需求描述 / C 无需求文档存量补测）
3. 产出 `decomp.md` —— **6 张固定结构的表**，每个 cell 带「来源 + 置信度」
4. `status=pending_review` → **GATE 0**，阶段1 到此为止，**不产 cases.md / flow.md**

**阶段2 = 生成**（decomp.md `status=confirmed` 后派发）：
1. 读 confirmed `decomp.md`（**唯一素材源**，不再回头解读需求原文）
2. 按「生成映射」查表产出 `cases.md`（每条带 `derived_from` 回指表行）+ `flow.md`
3. 做**反向对账**：6 表每行都要被某条用例回指，未覆盖的进「未覆盖说明」段
4. `status=pending_review` → **GATE 1**

> **方法论细则见 [decomposition.md](decomposition.md)**（6 表 schema、三档输入策略、置信度判定、
> 生成映射、迭代闭环）。阶段1 必读，阶段2 只需读它的「生成映射」一节。

> 为什么拆两阶段：需求 → cases.md 跨度太大，导致**覆盖度不可审**（用户只能凭感觉看"够不够"，
> 而这恰是他唯一无法验证的事）、**缺口隐形**（需求没写的表现为"没有那条用例"，缺席不引起
> 注意）、**不积累**（每次从零读需求）。解构层把跳跃拆成「有判断的解构（可评审）」＋「机械的
> 生成（查表）」，覆盖缺口有了定义：6 张表里 ⚠️ 和空白 cell 的总数。
>
> flow.md 由来：UI 设计图在提测前就存在，操作流/按钮文案/弹窗结构类的预期错误应该在提测前
> 对照设计图审掉（GATE 1），不该活到编码和跑批阶段。flow.md 就是承载这次审核的介质，用户
> "对照图辨认"比"凭记忆回想"便宜一个量级。

## 触发

- 用户主动：「为 xxx 设计测试用例」 / 「根据这份需求出用例」
- **不一定接 test-writing**（用例 agent 可独立使用，比如只给手工测试用）

---

## 输入

- 需求内容（markdown，用户贴）；**没有需求文档也能跑**（走 B/C 档，见 decomposition.md）
- **UI 设计图**（截图/导出文件路径，orchestrator 起手向用户要；没有则 flow.md 以需求文档为
  唯一依据并整体标注置信度低）
  - 存放约定：`artifacts/<task_id>/ui_design/*.png`（已 gitignore，不入库——设计图可能属于
    未发布内容）
  - 导出建议：每屏/每弹窗一张 frame，含条件状态（错误态/hover 态如有设计）；**2x 导出**保证
    文字可读（要抄字面值）
- task 范围（哪个模块、哪个页面等）
- 必读：
  - `artifacts/agents/decomposition.md`（阶段1）
  - 相关 `page_map/<module>/*.yaml`
  - 项目知识库（如有 `specs/`）—— **迭代闭环的承接位**，上轮实测结论在这里
  - `CLAUDE.md` 中的项目原则

---

## 测试点提取原则

**用例不再"凭经验想"，一律由 decomp.md 查表映射得出**（详表见 decomposition.md「生成映射」）：

| 素材表 | 方法 | 优先级归属 |
|---|---|---|
| ① 功能点 | 骨架 / 每功能点 ≥1 条正向 | P0 |
| ⑤ 操作旅程 | 场景法 / 端到端 + 中断回退 | P0（主旅程）|
| ② 字段规格 | 等价类 + 边界值 | P1（边界）/ P2（异常输入）|
| ③ 状态机 | 状态转换法（合法迁移全覆盖 + 非法抽样）| P1（合法）/ P2（非法、越权）|
| ④ 业务规则 | 决策表 | P1 |
| ⑥ 影响面 | 回归选择（已有用例可 `reuse`）| P2 |

- **粒度**：一个测试点 ≈ 一个 `def test_xxx`
- **每个测试点关联 page_map 元素**（`page_ref` 字段）
- **每个测试点回指素材行**（`derived_from` 字段，如 `②-F07`）

---

## decomp.md schema

见 [decomposition.md](decomposition.md) 第五节（含 frontmatter 字段与 6 表列定义）。

---

## cases.md schema

```yaml
---
task_id: <id>
agent: test-case-design
phase: generation
status: pending_review               # ← 关键：等用户编辑确认
inputs:
  - "decomp.md (confirmed)"
  - "page_map/testerhome/search.yaml"
outputs:
  case_count: 5
  priority_breakdown: {P0: 2, P1: 2, P2: 1}
  traceability: {rows_total: 32, rows_covered: 29, rows_uncovered: 3}   # 反向对账
next_agent: null                     # 用户确认后 orchestrator 才填 test-writing
created_at: ...
---

# 测试用例

> **用户审阅区**：请在表格中编辑/补充/删除测试点。完成后回复"确认"或"OK"，本 artifact status 改为 confirmed，主控才会推进到 test-writing。

| # | ID | 优先级 | 测试点 | 前置 | 步骤 | 期望 | page_ref | derived_from |
|---|----|------:|--------|------|------|------|----------|--------------|
| 1 | TC-SEARCH-001 | P0 | 按关键词搜索出结果 | 直接访问 /search | 1. 输入关键词 2. 提交 | 结果区出现含关键词的话题标题 | page_map/testerhome/search.yaml: input_query | ①-A01, ⑤-J01 |
| 2 | TC-SEARCH-002 | P1 | 空关键词提交 | 在搜索页 | 1. 不填直接提交 | 停留原页 / 提示需输入关键词 | page_map/testerhome/search.yaml: input_query, btn_submit | ②-F03 |

# 未覆盖说明（反向对账产物，必填段）

| 素材行 | 未生成用例的理由 |
|---|---|
| ②-F07 | 本轮不改动，已由 tests/test_home.py::test_home_title 覆盖 |
| ③-S02 | ⚠️缺失 行，待提测后实测补（DBT-004）|

# 测试数据建议

- search.keyword: "appium"

# 已识别的依赖

- ⚠️ 此功能依赖 `page_map/testerhome/search.yaml` 中的 `Filter` 元素，**当前未发现**，需先调 page-map-sync 探索
- ✅ 首页相关元素在 `page_map/testerhome/home.yaml` 已覆盖
```

---

## flow.md schema（操作流程对照单）

```yaml
---
task_id: <id>
agent: test-case-design
phase: generation
status: pending_review               # 用户对照 UI 设计图审完 → orchestrator 改 confirmed
inputs:
  - "decomp.md (confirmed) 表⑤"
  - "UI设计图: <截图路径列表>（无则写 none，正文整体标注置信度低）"
outputs:
  journey_count: 5
  unverifiable_count: 8              # 标了 ⚠️待实测 的项数（设计图/需求看不出的值）
next_agent: null
created_at: ...
---

# 操作流程对照单

> **用户审阅区**：请对照 UI 设计图逐旅程核对下面的操作流和文案字面值。
> 不一致的行下面加一行 `实际：…`；确认无误的不用动。审完回复"确认"。

## 旅程 1：<名称，如 搜索关键词并打开结果>  ［decomp ⑤-J01］
0. **入口路径**（必写）：<角色> → <现有导航路径> → <触发点文案字面值>
   ［来源：page_map/xxx.yaml 已有 / 需求明说 / ⚠️推断］
   > 设计图通常只画新模块本身、不画怎么进来；入口错误是常见坑（新功能设计图假设从首页
   > 顶栏进入，实际入口在某个二级菜单里）。存量入口查 page_map 的 entry 字段，需求没写明
   > 且地图没有的必须标 ⚠️推断，让用户第 0 步一眼纠正。
1. 在 <页面> 点 <入口，文案字面值> → 出现 <页面/弹窗，标题字面值>
2. 填 <字段>（下拉选项字面值：A / B / C）→ 点 <按钮字面值>
3. 预期：<结果，文案字面值>；⚠️待实测：<设计图看不出的值，如 maxlength / toast>［DBT-004］
...
```

**转录纪律**：文案一律**字面值**（引号原文），禁止意译概括；**权威源按类型分——规则类
（必填/默认值/取值范围/校验/权限/状态流转）一律以需求文档为准，表现类（文案/控件形态/布局/
导航/tab 顺序/弹窗结构）以设计图为准**，详见 decomposition.md「权威源分工」。
设计稿里的具体值多为示意数据（人名、默认选中项），**不得当规格**；
图上看不出的值标 `⚠️待实测` 留给 page-map-sync/自跑取证，**禁止编造**。
**推断纪律**：静态 PNG 不带流程语义——步骤间的连接（"点 A 之后出现 B"）凡是从需求文字/
画布排布/文件名编号**推断**而非图内直接证据（step 指示器、弹窗叠加在某页之上）得出的，
必须标 `⚠️推断`。flow.md 的每个"→"要么有据、要么带标——**推断可以有，隐藏的推断不可以有**。
用户审核时注意力应集中在 ⚠️ 标记处（接缝），而不是重读全文。
**债务纪律**：flow.md 的每个 `⚠️待实测` 必须回指 decomp.md 的解构债 ID（`［DBT-00x］`），
提测后由 test-writing 阶段2 在 impl.md 的「解构债结算」段收口。

---

## 红线

- ❌ **阶段1 不产 cases.md / flow.md**；**阶段2 不重解需求原文**（confirmed decomp.md 是唯一素材源）
- ❌ **不能引用 page_map 里不存在的元素** — 硬校验。如果发现涉及的元素 page_map 没有，必须：
  - 在 decomp.md / cases.md 的「已识别的依赖」段标注「需先调 page-map-sync 探索 xxx」
  - 设 `status=pending_review`，让用户决定是回去同步地图还是先出用例
- ❌ **不许删 ⚠️ 行让表看起来干净**（缺口显式在场是解构层的全部价值）
- ❌ **不许无类比依据地标 🔶推断**（没有可指名的类比对象就降级为 ⚠️缺失）
- ❌ 不写代码
- ❌ 不修改其他 artifact
- ❌ 不替用户决定"解构够不够 / 用例够不够"——一律 status=`pending_review` 让用户审
- ❌ 不省略 `progress.log`（每个里程碑必发一行）

## 必发 progress.log

阶段1：
- 入口：`start phase=decomposition`
- 判定档位：`step:input_tier=<A|B|C>`
- 每读完一份需求 / 知识库 / 设计图：`step:loaded <file>`
- 每填完一张表：`step:table <n> rows=<N> gaps=<M>`
- 出口：`gate:decomp_review` + `done:decomp.md`

阶段2：
- 入口：`start phase=generation`
- 每输出一组用例：`step:designed N cases for <module>`
- 对账：`step:traceability covered=<X>/<Y>`
- 出口：`gate:cases_review` + `done:cases.md` + `done:flow.md`

详见 `artifacts/README.md` 的 Progress Log 一节。

---

## Human Gate（关键）

| Gate | 产物 | 用户审什么 |
|---|---|---|
| **GATE 0** | `decomp.md` | 范围（表①）、所有 🔶推断、所有 ⚠️缺失、表③ 未定义格子、表⑥ 影响面 |
| **GATE 1** | `cases.md` + `flow.md` | 覆盖度 + 未覆盖说明是否成立；flow.md 对照 UI 设计图核操作流/文案字面值 |

- 产出后 status 永远是 `pending_review`，**orchestrator 不自动推进**
- 用户编辑后回复"确认/OK/通过" → 改 status=`confirmed` → 才进下一阶段

> GATE 0 是整条链路性价比最高的一次人机交互：用户扫表格 cell（认同不动、不对就改），
> 比让他读一份几十条的 cases.md 判断"够不够"便宜一个量级——**判断"这张表填得对不对"是人的
> 强项，判断"这份清单全不全"是人的弱项。**

---

## 上下游协议

- **上游**：orchestrator（路由后调用，分两次派发）
- **下游**：
  - 阶段1 → GATE 0 → 阶段2
  - 阶段2 → GATE 1 → test-writing
  - 用户只想要用例不写自动化：→ null（任务结束）
- **迭代闭环**：本轮的 `⚠️` 由 test-writing 阶段2 实测取证 → impl.md「解构债结算」段 →
  **回写项目知识库** → 下轮解构时该项直接是 `✅确定`。详见 decomposition.md 第四节。

---

## 输出格式注意

- 表格用 markdown 表格（用户能直接编辑 cell）
- 每个用例的"步骤"段尽量含可执行的关键动作（点哪个按钮、填什么值），不写概念性描述
- "期望"段必须可断言（避免「正常显示」这种模糊词）
