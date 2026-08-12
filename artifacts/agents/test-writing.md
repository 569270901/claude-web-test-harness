# test-writing (脚本编写 + 自跑自修 agent) 规范

> **前置**：先读 `artifacts/README.md` 了解通用规范。

## 职责（两阶段，由 orchestrator 分两次派发，派发 prompt 指明阶段）

**阶段1 = 编码**（cases.md + flow.md 均 confirmed 后派发）：
1. 读 confirmed cases.md + **confirmed flow.md（行为基准：文案字面值/操作流以它为准）** + page_map + 项目知识库
2. 生成/修改测试代码（`tests/**/test_*.py`）与测试数据（`data/*.yaml`）
3. 跑 compliance 轻扫
4. 产出 `ops_review.md` = **偏差清单**（status=pending_review）：只列
   ①实现与 flow.md 的出入 ②sync.md 报的实测偏差 ③flow.md `⚠️待实测` 项的实测取值。
   frontmatter 必带 `deviation_count`；**偏差=0 也要写空清单**（orchestrator 据此自动流转）
5. 阶段1 到此为止，**不进自跑循环**

**阶段2 = 验证**（偏差=0 自动进入，或用户裁决完后派发）：
1. 逐条应用用户裁决：`实际：…` → 按用户所见改断言；`产品bug：…` → 改 xfail(strict=True)
   并注明 bug；**无标注的条目 = 用户确认无误，禁止再改其断言**
2. 自己跑测试，挂了 → 自调整代码或地图 → 重跑（最多 3 轮）
3. **结算解构债**：把本轮实测掉的 `decomp.md` `⚠️`/`🔶` 项（flow.md 里带 `［DBT-00x］` 标记的）
   写进 impl.md 的「解构债结算」段，**并实际回写项目知识库**——这是让下一迭代的解构少一个 ⚠️
   的唯一动作，跳过它整套方法论就不积累
4. 产出 impl.md

> 为什么这样拆：行为模型/文案类错误在 GATE 1 就该被 flow.md（对照 UI 设计图）审掉；编码阶段
> 只剩"实现忠不忠于 flow.md"和"实测冒出的新偏差"，所以 GATE 2 降级为条件触发的偏差裁决。
> **发现归人，固化归 agent，审核前置到提测前。**

## 触发

- 用户主动：「写自动化」
- 阶段1：orchestrator 在 cases.md status=`confirmed` 后调
- 阶段2：orchestrator 在 ops_review.md status=`confirmed` 后调

## ops_review.md schema（偏差清单）

```yaml
---
task_id: <id>
agent: test-writing
status: pending_review               # deviation_count=0 时 orchestrator 直接视为通过
deviation_count: 3                   # 关键字段：0 = 自动流转，>0 = GATE 2 等用户裁决
source_files:
  - "tests/test_search.py"
created_at: ...
---
# 正文：逐条偏差块（涉及用例 → flow.md 怎么说 → 实现/实测是什么 → 待用户二选一：
# `实际：…` 跟实测改断言 / `产品bug：…` xfail 挂号）。
```

---

## 入口前置检查

启动时必须验证：
1. `cases.md` 存在且 `status=confirmed`，否则拒绝执行
2. 相关 page_map yaml 存在且 cases.md 的 `page_ref` 都能在 page_map 中找到
3. 测试环境可访问（见 `CLAUDE.md` 的 base_url / 登录约定）

---

## 实现风格（项目约定）

参考 `CLAUDE.md`、`rule.md` 和现有代码（如 `tests/test_home.py`）：

1. **优先复用项目既有的数据驱动 / page object 层**
   - 本骨架的 demo 用普通 pytest-playwright；如果你的项目有数据驱动表单引擎或 PO 基类，
     优先复用，不要为单一场景硬编码一次性 selector
2. **selector 走稳定定位**
   - ID / role / 稳定属性 / 文本，**禁用** hash class、`:nth-child`、xpath 位置索引（详见 `rule.md`）
3. **测试目录**
   - 统一放 `tests/`，不嵌套 module 子目录
4. **断言**
   - 所有有意义的字段都断言；`expected` 不能为 `"0"` / `"-"` / 空；用 Playwright `expect(...)`
5. **测试数据**外置到 `data/*.yaml`，代码读数据，不写死

---

## 自跑流程

```
1. 写代码 / 改 data yaml
   ↓
2. 轻量自检（compliance scan）：
   - 没有删/弱化断言、没有 expected="0"/"-"/空
   - 没有通配 selector（* / :nth-child / xpath 索引）
   - 测试文件在 tests/ 下、注释中文
   （如项目提供 scripts/check_compliance.py 就跑它，否则自查）
   ↓
3. 跑指定测试（pytest 命令见下）
   ↓
4. 全过? 写 impl.md status=completed 退出
   失败? → round += 1
   ↓
5. round > 3? status=blocked_after_3_retries 退出
   ↓
6. 分析失败原因（看 stack + 失败截图/DOM）：
   - selector 找不到? → 怀疑地图过期，next_agent=page-map-sync
   - 数据/格式问题? → 改 data yaml
   - 真 bug (UI 行为错)? → status=likely_bug，next_agent=null，等用户介入
   ↓
7. 回 3 重跑
```

## 推荐 pytest 命令

```bash
# 单测（headless，不抢占你的桌面）
python -m pytest <nodeid> -v

# 调试看浏览器
python -m pytest <nodeid> -v --headed
```

---

## impl.md schema

```yaml
---
task_id: <id>
agent: test-writing
status: completed                    # completed | blocked_after_3_retries | likely_bug | failed
inputs:
  - "artifacts/<task_id>/cases.md"
  - "page_map/testerhome/search.yaml"
outputs:
  files_changed:
    - "tests/test_search.py"
    - "data/testerhome.yaml"
  test_run_summary:
    passed: 3
    failed: 0
    duration_sec: 40
    test_ids:
      - "tests/test_search.py::test_search_by_keyword"
  self_repair_rounds: 1              # 自修了几轮
  review_rounds: 2                   # 调过几次 review
  debt_settled: 4                    # 本轮实测掉的解构债条数（decomp.md 的 DBT-00x）
  debt_carried: 2                    # 仍未解决、挂到下一迭代的条数
next_agent: null                     # 全过 null；blocked / likely_bug 见 status
created_at: ...
---

# 实现摘要
- 在 tests/test_search.py 加空关键词提交的边界用例
- ...

# 解构债结算（必填段）

本轮实测掉的 `decomp.md` `⚠️缺失` / `🔶推断` 项，**必须回写项目知识库才算结清**：

| 债ID | 原描述 | 实测结论 | 回写去向 | 状态 |
|---|---|---|---|---|
| DBT-004 | 话题标题最大长度未知 | maxlength=100，超出静默截断（无报错） | specs/topic.md「字段约束」 | ✅已回写 |
| DBT-007 | 已锁定话题能否被再次举报（表③未定义） | 实测按钮不出现，确为禁止 | specs/topic.md「状态流转」 | ✅已回写 |
| DBT-011 | 移动端搜索结果空态文案 | 本轮未走到该分支 | — | ⏳挂到下一迭代 |

> 挂账允许，静默丢失不允许。orchestrator 在任务终态前会核对这一段。

# 自修日志（每轮）
## Round 1
- 失败: TC-SEARCH-002 找不到 input#q (30s timeout)
- 决策依据: 该字段在 page_map yaml 中 id 是 query，cases.md 写错为 q
- 修法: 改 yaml field id
- 结果: ✅ 通过

## Round 2
- ...
```

如果自修日志很长，可以单独写 `self_log.md`，impl.md 摘要带链接。

---

## 红线（写进 agent prompt，自检）

1. ❌ **禁止删除/弱化断言** — 失败不能改成"跳过断言"
   - 删 `expect()` 语句 ❌
   - 把 `expected: "appium"` 改成 `expected: ""` ❌
2. ❌ **禁止把 expected 改成空 / "0" / "-"** 来匹配实际值
3. ❌ **selector 不能用通配** — `*` / `:nth-child` / xpath 索引位置
4. ✅ **修地图 vs 修代码**必须显式说明依据，写进 self_log
   - 修代码：因为 yaml field type 错 / cases.md 期望值错
   - 修地图：怀疑 UI 改动，反馈给 page-map-sync
5. **循环上限：3 次自修不过 → 退出 `status=blocked_after_3_retries`**，**禁止突破上限**
6. ❌ 不修改不属于自己的 artifact（sync.md / cases.md / review.md）
7. ❌ 不**直接**改 `page_map/*.yaml`（要让 page-map-sync 改）
   - 例外：cases.md 的 page_ref 是错的（你以为 yaml 是 X 实际是 Y），可以**改 cases.md 的引用**而不是改 page_map
8. ❌ 不省略 `progress.log`（每轮自跑前后都要发）
9. 真 bug → `status=likely_bug` 并保留完整断言（用 `xfail(strict=True)` 标记），不许改断言迁就

## 必发 progress.log

- 入口：`start`
- 写完代码每个测试文件：`step:wrote <file>`
- 每轮 round 自跑：`step:round N running` 和 `step:round N <pass|fail count>`
- 调 review：`step:calling review`
- 出口：`done:impl.md`

详见 `artifacts/README.md` 的 Progress Log 一节。

---

## 跑失败时的分类决策

| 现象 | 怀疑 | 行动 |
|---|---|---|
| `Locator.fill` / `Locator.click` 30s timeout | selector 漂移 | 看失败截图/DOM 对比 page_map → 调 page-map-sync |
| DOM 有值但断言区显示空/`-` | 后端字段 bug | status=`likely_bug` 退出，等人介入 |
| 表单提交校验失败 | 业务校验（如格式错） | 改 yaml value 为合法格式 |
| 按钮点了不切换视图 | UI 改版 / headless 点击没生效 | 加 hover + click，或 fallback URL 直达 |
| 下拉选不上 | option 文本变了 | 看 DOM 找新文本 → 改 yaml select |

---

## 上下游协议

- **上游**：orchestrator（cases.md confirmed 后调用）
- **下游**：
  - 全过：→ null（任务结束，orchestrator 随后派 review）
  - selector 漂移：→ page-map-sync（自修循环触发，给目标 URL）
  - 真 bug：→ null（等用户）
  - 超 3 轮：→ null（等用户）
