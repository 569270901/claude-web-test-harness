# 术语表

harness 文档里反复出现的内部术语，一句话说清。详细规则以对应文档为准（括号里给出处）。

## 角色与产物

| 术语 | 含义 |
|---|---|
| orchestrator | 总调度，就是主对话本身。只负责路由、维护 `state.md`、在 GATE 停下等人，不写业务产物（`agents/orchestrator.md`） |
| page-map-sync | 探页面的子 agent：实地打开页面取证，覆写 `page_map/*.yaml`，产出 `sync.md` |
| test-case-design | 设计用例的子 agent，分两阶段：阶段1 解构出 `decomp.md`，阶段2 生成 `cases.md` + `flow.md` |
| test-writing | 写代码的子 agent：按确认过的用例写测试、自跑自修，产出 `ops_review.md`、`impl.md` |
| review | 只读复查代码和 `impl.md`，给 pass / fail |
| task_id / 任务目录 | 每个任务一个目录 `artifacts/<task_id>/`，这次任务的全部产物都在里面 |
| state.md | 任务状态机：当前在哪一步、各 agent 调了几次、哪些 GATE 在等人；`version:` 字段决定控制台分组 |
| page_map | 页面地图 YAML：页面上有哪些元素、selector 是什么、交互有什么异步副作用。**selector 只在这里写** |
| sync.md | page-map-sync 的探索报告；没有需求文档时还要写「行为实测记录」（字段约束、校验文案、状态与可点动作） |
| decomp.md | 解构产物 = README 里说的「检查点清单」：把需求拆成 7 张表，每个格子带来源和置信度 |
| cases.md | 正式用例表，每行一个测试点 |
| flow.md | 用户视角的操作流：每一步点什么、出现什么、文案逐字是什么 |
| ops_review.md | test-writing 阶段1 的偏差清单：实现/实测和 flow.md 不一致的地方 |
| impl.md | test-writing 的实现报告：改了什么、跑的结果、转手测清单、解构债结算 |
| progress.log | 每个 agent 关键节点写一行进度，`tail -f` 可实时看 |
| journal | 只增不改的运行日志：hook 自动记工具调用 + agent 记关键决策和理由（`scripts/journal.py`） |
| 知识库 / specs | 被测产品已确认的业务知识，按模块一个 `.md`，下次同模块任务直接复用（目录见 `CLAUDE.md`） |

## 解构（decomp.md）

| 术语 | 含义 |
|---|---|
| 7 张表 / 表①~⑦ | ①功能点清单 ②字段规格 ③状态机 ④业务规则 ⑤操作旅程 ⑥影响面 ⑦控件规格（`agents/decomposition.md`） |
| 表⑦ 控件规格 | 每个界面元素在不同情境（状态 × 角色）下该长什么样：文案、可见、可用。是页面地图的"对偶面"：地图管怎么找到它，表⑦ 管它该是什么样 |
| `✅确定` | 有明文依据：需求文档、设计图、知识库写了，或实测取证过，或用户答复过 |
| `🔶推断` | 没有明文，但有可以指名的类比依据（写清类比对象）。没有类比对象的猜测算 `⚠️缺失` |
| `⚠️缺失` | 不知道。保留该行、留空，不许删行 |
| `⚠️冲突` | 需求文档和设计图（或实测）对同一条规则说法不一样，必须人裁决 |
| `⚠️待核实` | 现状和需求文档不符，但还说不清是不是同一回事，提测时看一眼就能定 |
| `⚠️未定义`（表③） | 状态机里真正两可、推导不出来的迁移格子。能从业务流程推出来的格子不许标它 |
| ［需判断］ | 只有人能拍板的疑点（"该怎样"的问题），进 GATE 0 待审队列 |
| ［可提测］ | 提测后看一眼就知道的疑点（"现在怎样"的问题），本轮可跳过 |
| coverage_gap | `🔶` + `⚠️` 的总数，衡量解构还剩多少不确定 |
| A / B / C 档 | 输入完整度：A 有完整需求文档；B 只有需求描述或变更单；C 没有需求文档、功能已上线，只能靠页面实测 |
| DBT / 解构债 | 每个 `🔶`/`⚠️` 行分配一个编号（`DBT-001`…），在 GATE 0、提测实测中逐步还清，还清后回写知识库 |
| 已识别的依赖 | decomp.md 末尾一节：本轮缺的证据或前置条件（如地图还没探到的元素 `⚠️待探索`） |

## 审核（GATE）

| 术语 | 含义 |
|---|---|
| GATE 0 | 解构审核：人审 decomp.md 的 7 张表（主要看［需判断］），确认后才生成用例 |
| GATE 1 | 用例审核：人审 cases.md + flow.md，并在 `exec` 列标出不做自动化的例外 |
| GATE 2 | 条件触发：test-writing 阶段1 发现实现和 flow.md 有偏差时，人逐条裁决 |
| 评审控制台 | `python3 tools/qa_console.py ensure 8900`（保证跑的是当前代码），浏览器打开 `http://localhost:8900`，GATE 0 逐条裁决、GATE 1 直接改用例 |
| 契约版本（contract） | 评审卡片依赖的 decomp.md 格式版本，写在 decomp.md 的 frontmatter。`python3 tools/gate_review.py check <task_id>` 按它核对；不合规时控制台会在待审队列上方亮黄条 |
| 模板 | `artifacts/templates/decomp.template.md`，decomp.md 格式的唯一出处，agent 起手先复制它 |
| gate0_verdicts.json | 控制台里 GATE 0 的裁决单；apply 后 decomp.md 状态变成 `gate0_answered` |
| 增补轮 | test-case-design 在两阶段之间的一次补充派发：把 GATE 0 裁决或新到的证据回填进 decomp.md。不许用来"再想想" |

## 用例（cases.md）

| 术语 | 含义 |
|---|---|
| `exec` | 这条用例怎么执行：`auto` 写自动化；`manual` 手工测；`blocked` 本轮不测（写清复活条件）。是给 test-writing 的硬契约 |
| `page_ref` | 用例涉及的页面元素：`page_map/<模块>/<页>.yaml: <元素 key>`；地图还没有的填 `⚠️待探索` |
| `derived_from` | 这条用例来自 decomp 的哪几行（如 `②-F07`），给 agent 对账用 |
| `prd_ref` | 这条用例的原始依据（需求文档章节号 / 设计图 / 实测 / 用户 / 知识库），给人回到原文核对用 |
| 反向对账 | 7 张表的每一行都必须被某条用例的 `derived_from` 引用，没引用的要在「未覆盖说明」里写理由 |
| 控件覆盖率 | 表⑦ 覆盖的元素数 ÷ 地图该页元素总数 |
| PAUSE | GATE 1 确认了但功能还没上线：state.md 记 PAUSE，等提测后再继续 |

## 执行

| 术语 | 含义 |
|---|---|
| 动力学字段 | page_map 里描述交互异步副作用的字段：`async`（发什么请求、什么 DOM 算完成）、`gates`（没完成时会拦住哪个动作）、`flows.steps`（多步表单的步骤指示） |
| verified / unverified | page-map-sync 对每份地图的证据等级；unverified 的部分下游要降级信任、优先实跑 |
| xfail（产品 bug） | 已确认的产品缺陷：用例保留、断言不改，标 `xfail` 挂号，修好后会变 xpass 提醒你摘标 |
| 按现状守护 | 版本验收后，确认不修、按现状上线的需求偏差：断言改成当前行为，docstring 写明和需求的差异。现状一变用例就红，由人确认再改。是 xfail 的出口 |
| xfail 审计 | `--runxfail --no-guard` 跑一遍，确认每条预期失败的失败信息正好是预期那条断言，而不是被吞掉的 selector / 时序错误 |
| 写保护（WriteGuard） | 只读用例挂在页面上，拦截并记录所有写请求，结束时断言一条都没有；也可以当探针，不落库地看"提交会发出什么" |
| 数据足迹台账 | 记录自动化"建了 / 删了 / 删不掉"哪些对象（完整名字），清理只按台账里的完整名字精确匹配 |
| 版本回归清单 | `data/regression/<清单名>.yaml` 登记一个版本涉及的用例，`-m <清单名>` 一次跑完 |
| 转手测 | 自动化成本明显不划算时，把用例 `exec` 改成 `manual` 并写清卡在哪，交还人工 |
