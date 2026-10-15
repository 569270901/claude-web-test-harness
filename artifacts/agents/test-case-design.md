# test-case-design (测试用例输出 agent) 规范

> **前置**：先读 `artifacts/README.md` 了解通用规范。

## 职责（两阶段，由 orchestrator 分两次派发，派发 prompt 指明阶段）

**阶段1 = 解构**（拿到需求即可派发）：
1. 读需求（入档于 `input/`）+ **UI 设计图（`ui_design/`，用 Read 读图）** + `page_map` + 项目知识库 + 已有用例
2. 判定输入档位（A 有完整需求文档 / B 需求描述 / C 无需求文档存量补测）
3. 产出 `decomp.md` —— **7 张固定结构的表**，每个 cell 带「来源 + 置信度」
4. `status=pending_review` → **GATE 0**，阶段1 到此为止，**不产 cases.md / flow.md**

**阶段2 = 生成**（decomp.md `status=confirmed` 后派发）：
1. 读 confirmed `decomp.md`（**唯一素材源**，不再回头解读需求原文）
2. 按「生成映射」查表产出 `cases.md`（每条带 `derived_from` 回指表行）+ `flow.md`
3. 做**反向对账**：7 表每行都要被某条用例回指，未覆盖的进「未覆盖说明」段
4. `status=pending_review` → **GATE 1**

> **方法论细则见 [decomposition.md](decomposition.md)**（7 表 schema、三档输入策略、置信度判定、
> 审阅层级判定、生成映射、迭代闭环）。阶段1 必读，阶段2 只需读它的「生成映射」一节。

> 为什么拆两阶段：需求 → cases.md 跨度太大，导致**覆盖度不可审**（用户只能凭感觉看"够不够"，
> 而这恰是他唯一无法验证的事）、**缺口隐形**（需求没写的表现为"没有那条用例"，缺席不引起
> 注意）、**不积累**（每次从零读需求）。解构层把跳跃拆成「有判断的解构（可评审）」＋「机械的
> 生成（查表）」，覆盖缺口有了定义：7 张表里 ⚠️ 和空白 cell 的总数。
>
> flow.md 由来：UI 设计图在提测前就存在，操作流/按钮文案/弹窗结构类的预期错误应该在提测前
> 对照设计图审掉（GATE 1），不该活到编码和跑批阶段。flow.md 就是承载这次审核的介质，用户
> "对照图辨认"比"凭记忆回想"便宜一个量级。

## 触发

- 用户主动：「为 xxx 设计测试用例」 / 「根据这份需求出用例」
- **不一定接 test-writing**（用例 agent 可独立使用，比如只给手工测试用）

---

## 输入

**输入契约（需求入档路径、设计图约定、范围、权威顺序）唯一出处在契约卡 §1**
（`.claude/agents/test-case-design.md`）。此处不复制，只补 agent 侧的必读清单：

- `artifacts/agents/decomposition.md`（阶段1 必读，7 表方法论）
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
| ⑦ 控件规格 | 呈现断言，按「屏 × 情境」聚合 | P1（可见性/角色差异）/ P2（纯文案）|

- **粒度**：一个测试点 ≈ 一个 `def test_xxx`
- **每个测试点关联 page_map 元素**（`page_ref` 字段）
- **每个测试点回指素材行**（`derived_from` 字段，如 `②-F07` / `⑦-C08`）
- **每个测试点回指原始依据**（`prd_ref` 字段）：照抄 `derived_from` 那几行在 decomp 表里的「来源」，
  如 `PRD §3.2`、`设计图 p4`、`实测 2026-06-30`、`用户（GATE 0）`、`知识库 specs/<模块>.md`。
  `derived_from` 是给 agent 对账用的内部回指；`prd_ref` 是给**人**看的——评审人和手工执行人
  不用打开 decomp.md 就能回到需求原文核对。**不许拿自己的中间产物当依据**：来源只能是需求文档 /
  设计图 / 实测 / 用户 / 知识库，不能写"见 decomp 表②"（那是循环论证）

---

## 测试点标题写法（硬性格式）

`cases.md`「测试点」列必须是**一句人话**，不是给写这条用例的人自己看的备忘录。

**固定句式**：`验证 + <场景/操作，说人话> + <关键结果>`

- 以"验证"开头
- 中段说清楚"在什么情况下/做了什么操作"——用产品里看得到的名词（页面名、字段名、状态名），
  **不用内部代号**（`S0`、`①`、`R02`、`C08` 这类只有解构表自己人看得懂的编号，用户和以后接手
  的人都不知道 `S0` 指什么）
- 结尾说清楚"预期的结果是什么"（显示正确/生效/被拦截/保留/消失/恢复/不可用……）
- 一行内说完（约 15~30 字），更细的机制、内部依据放到「前置」「步骤」「期望」列里，标题不是
  拿来解释实现细节的地方
- 需要区分多语境时可以用"："分隔场景和结果，但分隔符前后都必须是人话，不是代号

**反例 → 正例**：

| 反例（拗口） | 正例 |
|---|---|
| 同页内切走/切回：隐藏保留 + 回填端到端（`月付→年付→按量→月付`） | 验证多次切换套餐计费周期后，之前填写的内容能正确保留和回填 |
| 保留作用域①：`保存草稿并退出` 后从草稿行 `查看` 回向导，暂存内容仍在 | 验证保存草稿退出后重新进入向导，之前填写的内容仍然保留 |
| 第 3 步基线态（`S0` 未选）整屏控件断言 + 下拉枚举排他性 | 验证未选择计费周期时，页面各控件的初始状态是否正确 |
| 管理员对 待审批 / 已退回 / 草稿 三态工单发起关闭，参数化跑三态 | 验证对 待审批/已退回/草稿 状态的工单发起关闭后状态正确变更 |

判断标准很简单：**拿掉所有背景知识，一个第一次看这份 cases.md 的人，能不能只读标题就知道这条
在测什么、期望什么结果**——不行就是没写好，跟"够不够详细"无关，是"人话 vs 内部黑话"的问题。

---

## decomp.md schema

见 [decomposition.md](decomposition.md) 第五节（含 frontmatter 字段与 7 表列定义）。

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
  exec_breakdown: {auto: 4, manual: 1, blocked: 0}                      # 执行方式分布
  control_coverage: {mapped: 23, map_total: 31}                         # 表⑦ 控件覆盖
next_agent: null                     # 用户确认后 orchestrator 才填 test-writing
created_at: ...
---

# 测试用例

> **用户审阅区**：请在表格中编辑/补充/删除测试点。完成后回复"确认"或"OK"，本 artifact status 改为 confirmed，主控才会推进到 test-writing。

| # | ID | 优先级 | exec | 测试点 | 前置 | 步骤 | 期望 | page_ref | derived_from | prd_ref |
|---|----|------:|------|--------|------|------|------|----------|--------------|---------|
| 1 | TC-SEARCH-001 | P0 | auto | 验证按关键词搜索后，结果列表出现含该关键词的话题 | 直接访问 /search | 1. 输入关键词 2. 提交 | 结果区出现含关键词的话题标题 | page_map/testerhome/search.yaml: input_query | ①-A01, ⑤-J01 | 实测 |
| 2 | TC-SEARCH-002 | P1 | auto | 验证不填关键词直接提交搜索时，页面提示需要输入关键词 | 在搜索页 | 1. 不填直接提交 | 停留原页 / 提示需输入关键词 | page_map/testerhome/search.yaml: input_query, btn_submit | ②-F03 | 实测 |
| 3 | TC-SEARCH-003 | P1 | auto | 验证搜索无结果时，整屏控件状态正确（空态提示出现、分页器隐藏） | 搜索一个无匹配的关键词 | 1. 提交搜索 | 空态文案 "没有找到相关内容" 出现；分页器不存在 | page_map/testerhome/search.yaml: empty_hint, pager | ⑦-C04, ⑦-C05 | 实测 |

## `exec` 列（执行方式）

| 值 | 含义 | 下游行为 |
|---|---|---|
| `auto` | 该自动化 | 进阶段③ 由 test-writing 写脚本 |
| `manual` | 只能人工执行（依赖真实邮件/支付回调/三方跳转/主观视觉判断） | **test-writing 禁止碰**——不为它生成脚本、不把它算进跑批结果，留作人工用例 |
| `blocked` | 本轮不测，必须同时在「已识别的依赖」段写 `revive_when: <复活条件>` | 不产脚本；条件满足时提醒 |

- **agent 一律先填 `auto`**，由用户在 GATE 1 改例外；只有明显依赖真实邮件 / 支付回调 /
  三方跳转 / 主观视觉判断的，才可先填 `manual` 并在该行注明理由。**agent 不自己判定该不该自动化。**
- 标错的成本不对称：把 `manual` 误标 `auto`，脚本会在自修循环里空转好几轮才放弃；
  把 `auto` 误标 `manual`，只是少一条自动化。**拿不准就标 `manual`。**
- **这是一份对下游的产物契约**：`exec != auto` 的行，test-writing 不得为其生成脚本，
  也不得把它计入"用例已覆盖"。

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

**唯一出处在系统提示** `.claude/agents/test-case-design.md` 的「红线」段。
此处不复制——两处并存必然 drift，改了一边忘另一边就是第二个真相。

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

**唯一出处在契约卡 §3**（`.claude/agents/test-case-design.md`）：GATE 0 审六处、
GATE 1 审三处（含 `exec` 标记）。此处只记不变量：

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
  - 阶段2 → GATE 1 → test-writing（**只接 `exec: auto` 的行**；`manual` / `blocked` 不进脚本）
  - 用户只想要用例不写自动化：→ null（任务结束）
- **迭代闭环**：本轮的 `⚠️` 由 test-writing 阶段2 实测取证 → impl.md「解构债结算」段 →
  **回写项目知识库** → 下轮解构时该项直接是 `✅确定`。详见 decomposition.md 第四节。

---

## 输出格式注意

- 表格用 markdown 表格（用户能直接编辑 cell）
- 每个用例的"步骤"段尽量含可执行的关键动作（点哪个按钮、填什么值），不写概念性描述
- "期望"段必须可断言（避免「正常显示」这种模糊词）
