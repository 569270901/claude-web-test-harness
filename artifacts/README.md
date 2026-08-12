# Multi-Agent 编排规范（总览）

本目录定义"多 agent 协作"的编排规范。所有 agent 间不直接对话，**通过 artifact 文档接力**。

**每个 agent 启动只读 2 份**：本文件 + `agents/<self>.md`。
（唯一例外：test-case-design **阶段1** 追加读 `agents/decomposition.md` —— 解构层方法论。）

---

## 5 个 agent

| Agent | 职责 | 触发 | 独立可用 | 详细规范 |
|---|---|---|:-:|---|
| **orchestrator** | 路由 / 状态机 / 调度 | 用户 prompt | - | [agents/orchestrator.md](agents/orchestrator.md) |
| **page-map-sync** | Playwright 探索 → 覆写 page_map | 主动 / agent 反馈 | ✅ | [agents/page-map-sync.md](agents/page-map-sync.md) |
| **test-case-design** | 两阶段：需求 → **结构化解构** → 测试用例 | 主动 | ✅ | [agents/test-case-design.md](agents/test-case-design.md)<br>方法论：[agents/decomposition.md](agents/decomposition.md) |
| **test-writing** | 写脚本 + 自跑自修 | 主动 (需 confirmed cases) | ❌ | [agents/test-writing.md](agents/test-writing.md) |
| **review** | 静态审查代码改动 | test-writing 收敛后 / 主动 | ✅ | [agents/review.md](agents/review.md) |

---

## 任务目录结构

每次任务起 `task_id`（格式 `YYYY-MM-DD_<短描述>`），所有产物归档：

```
artifacts/
  README.md
  agents/...
  <task_id>/                         ← 例: 2026-06-22_testerhome_home_search
    state.md                         ← orchestrator 维护
    sync.md                          ← page-map-sync 产出
    decomp.md                        ← test-case-design 阶段1 产出（结构化解构层：6 张表，GATE 0 单独审）
    cases.md                         ← test-case-design 阶段2 产出（用例表，每条 derived_from 回指 decomp 表行）
    flow.md                          ← test-case-design 阶段2 产出（操作流程对照单，GATE 1 与 cases.md 一并审）
    ops_review.md                    ← test-writing 阶段1产出（与 confirmed flow.md 的偏差清单；偏差=0 不触发 gate）
    impl.md                          ← test-writing 阶段2产出
    review.md                        ← review 产出（orchestrator 落盘）
    progress.log                     ← 行式进度日志
```

未涉及的 agent 跳过对应文件（只更新地图的任务只有 `state.md` + `sync.md`）。

---

## Artifact 通用 Schema

每份 artifact 顶部 YAML frontmatter + markdown 正文：

```yaml
---
task_id: 2026-06-22_testerhome_home_search
agent: page-map-sync                  # 5 个 agent 之一
status: completed                     # 状态枚举见下
inputs:                               # 这个 agent 读了什么
  - "page_map/testerhome/home.yaml"
outputs:                              # 这个 agent 产出（agent-specific，见各 agent 规范）
  ...
next_agent: test-case-design          # 主控应接力到哪个；null = 任务结束
notes: ""
created_at: 2026-06-22T10:30:00Z
---

# 正文 markdown ...
```

**主控只读 frontmatter** 决定下一步；agent 自身看 frontmatter + 必要正文。

**status 枚举**：
- `pending` — 还没开始
- `in_progress` — 干活中
- `pending_review` — 等用户介入（GATE）
- `confirmed` — 用户已确认（仅 decomp.md / cases.md / ops_review.md 用）
- `completed` — 完成，可接力
- `failed` — 出错，需人介入
- `blocked` — 达到上限/规则禁止继续

---

## Gate（人工介入点）

2 个强制 gate + 1 个条件 gate：

| Gate | 时机 | 用户动作 |
|---|---|---|
| **GATE 0: decomp.md 解构审核**（强制） | test-case-design **阶段1** 产出后 | 直接编辑 6 张表的 cell。重点：表①范围 / 所有 `🔶推断` / 所有 `⚠️缺失`（知道答案的直接填）/ 表③ `⚠️未定义` 格子（未定义=应禁止？）/ 表⑥ 影响面；审完回"确认" |
| **GATE 1: cases.md + flow.md 审核**（强制，**提测前即可完成**） | test-case-design **阶段2** 产出后 | cases.md 审覆盖度 + 「未覆盖说明」是否成立；flow.md **对照 UI 设计图**审操作流/文案字面值，不一致处加 `实际：…`；审完回"确认" |
| **GATE 2: 偏差裁决**（条件触发） | test-writing 阶段1编码后，ops_review.md 偏差数 > 0 时 | 逐条二选一：`实际：…`（改断言跟实测）或 `产品bug：…`（xfail 挂号）；偏差=0 自动流转不打扰 |

其他全部 agent 自动流转。

> GATE 0 由来：需求 → cases.md 一跳太大，覆盖度不可审、缺口隐形（需求没写的表现为"没有那条
> 用例"，而**缺席不引起注意**）、不积累。中间插入**结构化解构层**：需求/线上UI 先落成 6 张
> 固定结构的表（功能点 / 字段规格 / 状态机 / 业务规则 / 操作旅程 / 影响面），每 cell 带
> 「来源 + 置信度」，缺口从"没有用例"变成"表里一个显式的 ⚠️ 行"——**缺席变成在场**。
> 于是覆盖率有了定义：`覆盖缺口 = 6 表里 ⚠️ 和空白 cell 的总数`；生成用例退化成查表映射
> （表 × 方法，有数量下界），不再是 agent 的自由裁量。
> **判断"这张表填得对不对"是人的强项，判断"这份清单全不全"是人的弱项**——GATE 0 就是把人
> 放回他擅长的位置。完整方法论（A/B/C 三档输入策略、生成映射、迭代闭环）见
> [agents/decomposition.md](agents/decomposition.md)。

> GATE 1 由来：**审核尽量前置到提测前的等待期**——UI 设计图提测前就有、用户看得到而 agent
> 没喂过；按钮文案/弹窗流/导航层级/tab 顺序这类错误应死在 flow.md 审核（对照设计图辨认，
> 分钟级），不该活到跑批（一次全量回归可能是小时级）。**任务起手就把 UI 设计图（截图/导出）
> 给 test-case-design 当输入——agent 能读图。**提测后设计图上看不出的东西（maxlength、toast、
> DOM、时序）由 page-map-sync 取证和自跑循环兜住。

---

## 红线汇总（所有 agent 共享）

1. **不修改不属于自己的 artifact**（test-writing 不改 sync.md / review 不改 impl.md）
2. **不绕过 gate**（orchestrator 看到 pending_review 必停下）
3. **不撒谎**：失败就是失败，不能在 artifact 写"完成"但实际没完成
4. **artifact 必须有完整 frontmatter**（缺字段算违规，主控有权拒绝接力）
5. **agent 互调有上限**（防死循环，具体见各 agent 规范）
6. **每个关键阶段必须 append 一行到 `progress.log`**（详见下文 — 不写日志算违规）

---

## Progress Log（运行可观测）

每个 task 目录下维护一个 `progress.log`（行式 append，不删不改），让用户用 `tail -f` 就能实时知道 agent 跑到哪。

**文件路径**：`artifacts/<task_id>/progress.log`

**强制时机**（每个 agent 都要发）：
- `start` — agent 拿到控制权
- `step:<短描述>` — 每个有意义的内部步骤（如"探索首页"、"跑搜索测试"、"调 review"）
- `gate:<gate_name>` — 进入 pending_review
- `done:<artifact_file>` — 产出 artifact 完成
- `error:<msg>` — 出错（status=failed 时配套）
- `route:<next_agent>` — orchestrator 路由到下一个 agent

**格式**（一行一事件）：
```
[YYYY-MM-DD HH:MM:SS] <agent> <event>
```

**示例**：
```
[2026-06-22 14:23:01] orchestrator start
[2026-06-22 14:23:02] orchestrator route:page-map-sync
[2026-06-22 14:23:05] page-map-sync start
[2026-06-22 14:23:08] page-map-sync step:exploring page=Home
[2026-06-22 14:25:12] page-map-sync done:sync.md
[2026-06-22 14:25:13] orchestrator route:test-case-design
[2026-06-22 14:27:30] test-case-design gate:decomp_review
```

**实现**（Bash 一行写入即可，agent 自己负责）：
```bash
echo "[$(date +'%Y-%m-%d %H:%M:%S')] page-map-sync step:exploring page=Home" \
  >> artifacts/<task_id>/progress.log
```

**用户怎么看进度**：
```bash
tail -f artifacts/<task_id>/progress.log
```

或者让 Claude 在另一个会话里启 `Monitor` 工具 tail 该文件，每条事件作为推送通知。

> 5 分钟以上无新事件 = 极可能挂了，可以人工介入或杀掉重启。

---

## 运行日志 Journal（双层 / 只增不改）

`progress.log` 只记里程碑（跑到哪一步），不足以复盘「谁做了什么、为什么」。
为此引入 **`artifacts/<task_id>/journal.jsonl`**（**任务级**、只增不改，每行一个 JSON 事件），跟该任务其它产物同目录，天然按任务封顶、随任务归档，**项目级零膨胀**。用于事后复盘、追述行为、还理解债。分两层：

| 层 | 谁写 | 怎么写 | 记什么 |
|---|---|---|---|
| **客观层** | Claude Code 的 hook **自动** | 无需 agent 动手 | 每次工具调用：`ts / actor / tool / target / 结果`。**agent 无法遗漏或美化** |
| **叙事层** | **agent 主动** | `python3 scripts/journal.py log ...` | 「为什么」：决策依据、判定、发现。工具调用推断不出的意图 |

- 客观层由 `.claude/settings.json` 的 `PostToolUse / SubagentStart / SubagentStop` hook 驱动，调 `scripts/journal.py hook`。`actor` 取 hook 的 `agent_type`（子 agent 才有；缺省=`orchestrator`），所以**能自动认出是哪个 agent 干的**。
- 写哪个任务目录，由 `.claude/journal_task`（单行 task_id）决定，**由 orchestrator 在任务起手写入、在任务终态清除**（见 orchestrator 规范）。**没有这个指针就不记** —— journal 只审计任务执行，任务外的零散工具调用是噪声，不入账。

### 叙事层 schema（agent 写）

```bash
python3 scripts/journal.py log \
  --actor test-writing --action decide \
  --what "把 search 输入框 selector 从 #query 改为 #q" \
  --why  "元素定位到了，只是 cases.md 写的 id 过期" \
  --ref  round-1
```

`--action` ∈ `decide | find | note | gate | route | error | lifecycle`；**`decide` 必须带 `--why`**（脚本会硬校验，缺了报错）。

### 各 agent 的强制叙事点（最少这些必须记 why）

- **orchestrator**：任务起手写 `.claude/journal_task`、终态清除；每次路由/进 gate 记一条 `route` / `gate`
- **page-map-sync**：每个非平凡 selector 选择、每条「关键发现」记一条 `find`
- **test-case-design**：**阶段1**——档位判定、每个「标 🔶推断 vs 标 ⚠️缺失」的边界判断记一条 `decide`；
  **阶段2**——每个 page_ref 缺口判断（标依赖 vs 编造）、每条「未覆盖说明」的理由记一条 `decide`
- **test-writing**：**每次「修地图 vs 修代码」「判 likely_bug」必须 `decide --why`**（这是理解债最重的地方）
- **review**：每条 Blocking Issue 记一条 `find`，最终 verdict 记一条 `decide --why`

### 复盘（人读）

```bash
python3 scripts/journal.py show                      # 当前任务（读指针）
python3 scripts/journal.py show --task <task_id>      # 指定任务
python3 scripts/journal.py show --actor test-writing --no-reads   # 只看某 agent，隐去 read 噪声
python3 scripts/journal.py show --all                # 跨所有任务归并时间线（低频）
python3 scripts/journal.py show --follow             # 实时跟随当前任务
```

输出里 `·` = 客观层（hook 自动），`✎` = 叙事层（agent 写的「为什么」）。

> `artifacts/*/journal.jsonl` 已 gitignore（运行/取证数据，不入库）。`progress.log` 仍保留做轻量 live 心跳，二者职责不同：progress.log 看「活着没」，journal 看「干了啥、为啥」。

---

## 失败 / 回滚

- 任何 agent 失败：`status=failed`，写明失败原因
- 同 agent 调用次数超上限：`status=blocked`
- 整个任务 blocked：保留所有 artifact，等用户人工修复后清 status 重启
- 紧急回滚：`git reset --hard <锚点 commit>`

---

## 怎么开始一个任务

用户对 orchestrator（主对话）说一句话即可：

- 「为 TesterHome 首页+搜索设计并写一套只读测试」← 完整流程
- 「重新探索首页的页面地图」← 只走 page-map-sync
- 「根据这份需求设计测试用例（需求贴在下面）」← 只走 test-case-design（阶段1，走到 GATE 0）
- 「审查我刚改的 test_home.py」← 只走 review

orchestrator 自己判断该调哪些 agent、要不要 gate。

---

## 后续演化

本规范会随真实任务积累持续演进。每跑完一个真实任务，回顾：
- artifact schema 是否够用？字段冗余/缺失？
- 红线是否被违反？怎么强化 prompt？
- gate 时机合不合适？要不要加/减？
- 循环上限是否合理？
