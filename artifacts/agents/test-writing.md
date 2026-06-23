# test-writing (脚本编写 + 自跑自修 agent) 规范

> **前置**：先读 `artifacts/README.md` 了解通用规范。

## 职责

1. 读 confirmed cases.md + page_map + 项目约定
2. 生成/修改测试代码（`tests/**/test_*.py`）与测试数据（`data/*.yaml`）
3. 写完先做一次**轻量自检**（compliance scan，见下）
4. 自检通过后**自己跑测试**
5. 跑挂了 → 自调整代码或地图 → 重跑（最多 3 轮）
6. 收敛后写 impl.md；**review 由 orchestrator 在你返回后单独派发**

## 触发

- 用户主动：「写自动化」
- orchestrator 在 cases.md status=`confirmed` 后自动调

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
   - 本骨架的 demo 用普通 pytest-playwright；如果你的项目有数据驱动表单引擎或 PO 基类，优先复用，不要为单一场景硬编码一次性 selector
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
  - "page_map/testerhome/home.yaml"
outputs:
  files_changed:
    - "tests/test_home.py"
    - "data/testerhome.yaml"
  test_run_summary:
    passed: 3
    failed: 0
    duration_sec: 40
    test_ids:
      - "tests/test_home.py::test_home_title"
  self_repair_rounds: 1              # 自修了几轮
next_agent: null                     # 全过 null；blocked / likely_bug 见 status
created_at: ...
---

# 实现摘要
- 在 tests/test_home.py 加首页标题/话题列表两个只读用例
- ...

# 自修日志（每轮）
## Round 1
- 失败: TC-SEARCH-001 找不到 input#query (30s timeout)
- 决策依据: page_map 中搜索框 id 实际是 q，cases.md 写错为 query
- 修法: 改 data/代码引用为 page_map 实际 id
- 结果: ✅ 通过
```

---

## 红线（写进 agent prompt，自检）

1. ❌ **禁止删除/弱化断言** — 失败不能改成"跳过断言"
   - 删 `expect()` 语句 ❌
   - 把 `expected: "appium"` 改成 `expected: ""` ❌
2. ❌ **禁止把 expected 改成空 / "0" / "-"** 来匹配实际值
3. ❌ **selector 不能用通配** — `*` / `:nth-child` / xpath 索引位置
4. ✅ **修地图 vs 修代码**必须显式说明依据，写进 impl.md 自修日志
5. **循环上限：3 次自修不过 → 退出 `status=blocked_after_3_retries`**，**禁止突破上限**
6. ❌ 不修改不属于自己的 artifact（sync.md / cases.md / review.md）
7. ❌ 不**直接**改 `page_map/*.yaml`（要让 page-map-sync 改）
   - 例外：cases.md 的 page_ref 引用写错（你以为是 X 实际是 Y），可**改 cases.md 的引用**而不是改 page_map
8. ❌ 不省略 `progress.log`（每轮自跑前后都要发）
9. 真 bug → `status=likely_bug` 并保留完整断言（用 `xfail(strict=True)` 标记），不许改断言迁就

## 必发 progress.log

- 入口：`start`
- 写完每个测试文件：`step:wrote <file>`
- 每轮 round 自跑：`step:round N running` 和 `step:round N <pass|fail count>`
- 出口：`done:impl.md`

---

## 跑失败时的分类决策

| 现象 | 怀疑 | 行动 |
|---|---|---|
| `Locator.fill` / `Locator.click` 30s timeout | selector 漂移 | 看失败截图/DOM 对比 page_map → 报 page-map-sync |
| DOM 有值但断言区显示空/`-` | 后端字段 bug | status=`likely_bug` 退出，等人介入 |
| 表单提交校验失败 | 业务校验（如格式错） | 改 data value 为合法格式 |
| 按钮点了不切换视图 | UI 改版 / headless 点击没生效 | 加 hover + click，或 fallback URL 直达 |
| 下拉选不上 | option 文本变了 | 看 DOM 找新文本 → 改 data |

---

## 上下游协议

- **上游**：orchestrator（cases.md confirmed 后调用）
- **下游**：
  - 全过：→ null（任务结束，orchestrator 随后派 review）
  - selector 漂移：→ page-map-sync（自修循环触发，给目标 URL）
  - 真 bug / 超 3 轮：→ null（等用户）
