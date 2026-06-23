# Multi-Agent 编排规范（总览）

本目录定义"多 agent 协作"的编排规范。所有 agent 间不直接对话，**通过 artifact 文档接力**。

**每个 agent 启动只读 2 份**：本文件 + `agents/<self>.md`。

---

## 5 个 agent

| Agent | 职责 | 触发 | 独立可用 | 详细规范 |
|---|---|---|:-:|---|
| **orchestrator** | 路由 / 状态机 / 调度 | 用户 prompt | - | [agents/orchestrator.md](agents/orchestrator.md) |
| **page-map-sync** | Playwright 探索 → 覆写 page_map | 主动 / agent 反馈 | ✅ | [agents/page-map-sync.md](agents/page-map-sync.md) |
| **test-case-design** | 需求 + 地图 → 测试用例 | 主动 | ✅ | [agents/test-case-design.md](agents/test-case-design.md) |
| **test-writing** | 写脚本 + 自跑自修 | 主动 (需 confirmed cases) | ❌ | [agents/test-writing.md](agents/test-writing.md) |
| **review** | 静态审查代码改动 | test-writing 跑后 / 主动 | ✅ | [agents/review.md](agents/review.md) |

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
    cases.md                         ← test-case-design 产出
    impl.md                          ← test-writing 产出
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
- `confirmed` — 用户已确认（仅 cases.md 用）
- `completed` — 完成，可接力
- `failed` — 出错，需人介入
- `blocked` — 达到上限/规则禁止继续

---

## Gate（人工介入点）

只有 **1 个**强制 gate：

| Gate | 时机 | 用户动作 |
|---|---|---|
| **cases.md 审核** | test-case-design 产出后 | 编辑 cases.md，确认后回"确认"/"OK"/"通过" |

其他全部 agent 自动流转。

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
[2026-06-22 14:27:30] test-case-design gate:cases_review
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

> 5 分钟以上无新事件 = 极可能挂了，可以人工介入或杀掉重启。

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
- 「根据这份需求设计测试用例（需求贴在下面）」← 只走 test-case-design
- 「审查我刚改的 test_home.py」← 只走 review

orchestrator 自己判断该调哪些 agent、要不要 gate。
