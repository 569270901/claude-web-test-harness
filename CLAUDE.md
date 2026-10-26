# 项目指南（接入方在此声明自己的约定）

> 这是多 agent UI 测试 harness 的项目约定文件。**agent 读它来自适应你的项目**，
> 没有硬编码业务路径。接入你自己的项目时，改下面「项目约定」一节即可。
> demo 默认值面向 TesterHome（只读流程）。

## 你的身份（主对话必读，先于一切）

**主对话就是 orchestrator（总调度）。** 用户提出任何"测试 / 用例 / 地图 / 审查"类需求时，
先完整读一遍 `artifacts/agents/orchestrator.md`，按里面的路由规则派发子 agent、维护
`artifacts/<task_id>/state.md`，到 GATE 就停下等用户。你自己**不写业务 artifact、不写测试代码**，
这些交给对应子 agent（`.claude/agents/*.md`）。不熟悉的术语查 `artifacts/GLOSSARY.md`。

用户常见的三种开口方式（照着说就能触发对应流程）：

| 场景 | 用户这样说 | 走的流程 |
|---|---|---|
| 有需求文档（PRD） | 「按 PRD 设计 <功能> 的测试用例，PRD 在 `<路径>`（设计图在 `<目录>`，可选）」 | 解构 → GATE 0 → 生成用例 → GATE 1 |
| 只有网站，没有需求文档 | 「没有需求文档，帮我摸清 <站点/页面> 的 <功能> 并设计测试用例」 | **先探页面（page-map-sync 必跑）** → 解构（C 档，来源 = 实测）→ GATE 0 → 生成用例 → GATE 1 |
| 要一路做到自动化 | 「给 <功能> 补完整测试，包括自动化代码」 | 上面任一种 → test-writing 自跑自修 → review |

需求文档、设计图怎么准备，见 `README.zh-CN.md` 的「输入准备」一节。

## 必读文件

每次写代码 / 写测试 / 补页面地图前，先读：

- `rule.md` — 编码规则与技术避坑（selector 写法、等待时机、组件行为）
- `artifacts/README.md` — 多 agent 编排总览（artifact schema、gate、红线、progress.log）
- 相关的 `page_map/*.yaml` — 当前页面元素地图

发现新知识主动回写：技术坑 → `rule.md`；页面元素变化 → 对应 `page_map/*.yaml`；
业务行为（规则、状态、字段约束）的已确认结论 → `specs/<模块>.md`。不要等用户提醒，发现即记录。

**写完测试代码后跑一次红线静态扫描**（秒级，纯标准库）：

```bash
python3 scripts/check_compliance.py            # 扫全仓
python3 scripts/check_compliance.py --staged   # 只扫本次待提交的文件
```

`error` 必须修（不要 noqa 了事），`warn` 打印不阻断。规则在 `configs/compliance-rules.json`，
**接入自己的项目时按需增删**——里面有几条是组件库特有的，文件内 `$design_notes` 标注了哪些要换。
想让它在 commit 前自动拦截：`bash scripts/install_hooks.sh` 装 git pre-commit hook。

---

## 项目约定（← 接入时改这里）

| 约定 | 本项目取值 |
|---|---|
| 站点基础 URL | `https://testerhome.com`（见 `pytest.ini` 的 `--base-url`） |
| 页面地图目录 | `page_map/`（按 `page_map/<模块>/<页面>.yaml` 组织） |
| 测试数据目录 | `data/`（YAML） |
| 测试代码目录 | `tests/`（不嵌套模块子目录） |
| 测试运行命令 | `python -m pytest tests/ -v` |
| 登录逻辑 | demo 全部只读，无需登录；接入时在 `conftest.py` 加登录 fixture |
| 失败 DOM 落盘目录 | `data/debug/`（调试用，已 gitignore） |
| 需求文档 / 设计图入档位置 | `artifacts/<task_id>/input/`、`artifacts/<task_id>/ui_design/`（两者已 gitignore，只留本地）（入档方式见 README「输入准备」） |
| 产品知识库目录 | `specs/`（按模块一个 `.md`：业务规则、状态流转、字段约束的**已确认结论**；没有需求文档时，实测结论经 GATE 0 确认后回写这里） |

---

## 开发原则

- **所有字段都填（包括非必填）、都断言**
- **绝不删断言来让测试通过——失败就是 bug**
- `expected` 避免用 `"0"`，用有语义的值
- 注释用中文
- selector 优先 ID / role / 稳定属性，禁用 hash class / `:nth-child` / xpath 位置索引（详见 `rule.md`）
- **不动现有数据**：只写自己造的对象（名字带前缀 + 时间戳），清理按完整名字精确匹配、绝不按前缀批量删；
  只读用例挂写保护 `utils/write_guard.WriteGuard`；有风险（全局配置、发通知、可能锁账号）就只测只读。详见 `rule.md`「只读与无痕」
- **断言要真的在断言**：抓包断言挂在用例实际用的页面上（否则恒为空、永远通过），同时看 HTTP 状态和响应体里的业务码

---

## 测试命令

```bash
# 全部测试
python -m pytest tests/ -v

# 单个文件 / 单个用例
python -m pytest tests/test_home.py -v
python -m pytest tests/test_home.py::test_home_title -v

# 看得见浏览器（调试）
python -m pytest tests/ -v --headed

# 长回归：断点续跑（被杀 / 休眠后原样重跑同一条命令只补没跑完的）+ 撞墙止损（连败就停批）
python -m pytest tests/ -v --batch nightly --guard

# 用例导出成 Excel 交给人工执行
python3 tools/cases_export.py <task_id> --only-manual
```

---

## demo 任务（验证 harness 跑通）

在本目录打开 Claude Code，对主对话说：

> 「为 TesterHome 首页（话题列表 + 帖子详情）设计一套只读测试并写出来」

（搜索页匿名访问会被重定向到登录页，所以 demo 不含搜索。）

主对话（orchestrator）会按需派发：
`page-map-sync → test-case-design(阶段1解构→decomp.md，你审 GATE 0) → test-case-design(阶段2生成→cases.md+flow.md，你审 GATE 1) → test-writing → review`。
**只做只读流程**（浏览话题列表、打开帖子详情、断言渲染），不要自动化注册/登录/发帖。
