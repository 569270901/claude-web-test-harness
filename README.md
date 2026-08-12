# claude-web-test-harness

一套**领域无关**的多 agent UI 自动化测试编排骨架。把它放进任意 Web 项目，用 [Claude Code](https://claude.com/claude-code) 驱动「探索页面 → 设计用例 → 写测试 → 审查」这条流水线。

> 演示站点用 [TesterHome](https://testerhome.com)（QA 社区论坛），demo 流程全部**只读**（浏览/搜索/断言渲染），不涉及注册登录发帖。

---

## 它解决什么

写 UI 自动化的真实流程是：**摸清页面有哪些元素 → 把需求拆成可审的结构化清单 → 落成测试用例
→ 落成测试代码 → 有人 review**。这套 harness 把这五步固化成四个隔离的 Claude Code 子 agent
（test-case-design 内部再分两阶段），用 artifact 文档接力，关键节点设人工 gate：

```
   你(orchestrator/主对话)
        │  派发
        ▼
┌────────────────┐   ┌───────────────────────────────┐   ┌───────────────┐   ┌──────────┐
│ page-map-sync  │ → │ test-case-design（两阶段）     │ → │ test-writing  │ → │ review   │
│ 探页面→页面地图│   │ 阶段1 需求→解构表(GATE 0)      │   │ 用例→测试代码 │   │ 静态审查 │
│                │   │ 阶段2 解构表→用例+操作流(GATE1)│   │               │   │          │
└────────────────┘   └───────────────────────────────┘   └───────────────┘   └──────────┘
  page_map/*.yaml         decomp.md      cases.md+flow.md      test 代码         verdict
```

为什么中间插一道解构表：需求直接跳到用例清单，覆盖度没法审——需求没写的东西表现为"少一条
用例"，而**缺席这件事本身不会被注意到**。解构层先把需求拆成 6 张固定结构的表（功能点/字段
规格/状态机/业务规则/操作旅程/影响面），每个格子标"来源+置信度"，缺口就变成表里一个显眼的
`⚠️` 行——用户在 **GATE 0** 审的是"这格填得对不对"，比审"这份用例清单全不全"容易判断得多。
方法论细节见 [`artifacts/agents/decomposition.md`](artifacts/agents/decomposition.md)。

**机制是通用的，业务是你的。** harness 本身不含任何业务概念——你的页面地图、登录逻辑、测试约定通过几个目录约定接进来。

---

## 前提：一个能跑 agent 的编码工具（首选 Claude Code）

这套 harness 的「执行引擎」是一个 **agentic 编码工具**——它负责扮演 orchestrator、调度各角色、读写 artifact、跑测试。
本身的机制（角色规范 `artifacts/agents/*.md`、artifact schema、流水线、`page_map`/`data`/`tests` 约定）就是 **markdown + 一个普通的 pytest-playwright 工程**，不绑死任何一家工具。

### 用 Claude Code（原生支持，开箱即用）

Claude Code 能直接读 `.claude/agents/`（子 agent 定义）和 `CLAUDE.md`（项目约定），原生做**隔离子 agent 派发**，所以零配置就能跑。下面「快速开始」就是 Claude Code 的流程。

### 用 Codex / CodeBuddy / 其他 agent 工具（喂一段兼容 prompt）

其他工具没有 Claude Code 的子 agent 派发和 `CLAUDE.md` 自动加载机制，但 harness 的角色规范都是纯 markdown，可以让**单个 agent 读规范、按顺序扮演各角色**来模拟整条流水线。把下面这段 prompt 喂给它即可：

```text
你是这个仓库的测试编排 orchestrator。先读这几份文件理解机制：
- artifacts/README.md（编排规范：artifact schema、状态枚举、gate、红线、progress.log）
- artifacts/agents/ 下全部角色规范（orchestrator / page-map-sync / test-case-design / test-writing / review）
- artifacts/agents/decomposition.md（test-case-design 阶段1 的解构方法论，6 张表 schema）
- CLAUDE.md（项目约定：站点 URL、目录、登录、开发原则）
- rule.md（selector 写法等技术红线）

然后按这条流水线依次执行（你没有隔离子 agent，就在当前上下文里逐个扮演每个角色）：
page-map-sync
→ test-case-design 阶段1=解构（产出 decomp.md）→（停下来等我审 GATE 0）
→ test-case-design 阶段2=生成（产出 cases.md + flow.md）→（停下来等我审 GATE 1）
→ test-writing → review

严格遵守：
1. 每个角色产出对应 artifact，带完整 frontmatter（schema 见 artifacts/README.md）
2. decomp.md 产出后 status=pending_review，必须停下等我确认（GATE 0），cases.md+flow.md
   产出后同样必须停下（GATE 1）——两个 gate 都不准跳过
3. 关键阶段 append 一行到 artifacts/<task_id>/progress.log
4. 绝不删断言来让测试通过；selector 禁用 hash class / :nth-child / xpath 位置索引

我的需求是：<在这里写你要测什么>
```

> 注意：非 Claude Code 工具是「单上下文模拟多角色」，没有真正的进程隔离，长任务上下文容易串味；建议一次只跑一条流水线、勤看 `progress.log`。能力够强的 agent 工具都能跑，效果取决于工具本身。

---

## 快速开始

```bash
# 1. 装依赖
pip install -r requirements.txt
python -m playwright install chromium

# 2. 先跑一下自带的示例测试（证明脚手架能跑）
python -m pytest tests/ -v

# 3. 在本项目目录打开 Claude Code，对主对话说一句话即可启动编排：
#    「为 TesterHome 首页+搜索设计一套只读测试并写出来」
#    主对话会按需派发 page-map-sync → test-case-design(解构→GATE 0→生成→GATE 1) → test-writing → review
```

跑编排时，用另一个终端实时看进度：

```bash
tail -f artifacts/<task_id>/progress.log
```

---

## 接进你自己的项目

harness 不靠配置文件，靠**目录约定 + 一份 `CLAUDE.md`**。agent 规范里没有硬编码任何业务路径——它们读 `CLAUDE.md` 自适应。把 demo 换成你自己的项目，按下面四步改：

### 第 1 步：改基础 URL（必改）

站点地址在 **`pytest.ini` 的 `--base-url`**，改成你的环境：

```ini
# pytest.ini
addopts = --tb=short --base-url=https://your-app.example.com
```

测试里通过 pytest-playwright 自带的 `base_url` fixture 拿到它，无需在代码里写死域名。`CLAUDE.md` 的「项目约定」表里也同步改一下（agent 读它来理解你的站点）。

### 第 2 步：加登录逻辑（按需）

demo 全程只读、不需要登录。要测登录后的页面，就在 **`conftest.py`** 里加一个 fixture（文件里已有占位注释）：

```python
import pytest

@pytest.fixture
def logged_in_page(page, base_url):
    page.goto(f"{base_url}/account/sign_in")
    page.fill("input#user_login", "your-test-account")   # selector 换成你站点的
    page.fill("input#user_password", "***")              # 真实密码用环境变量，别提交进仓库
    page.click("button[type=submit]")
    page.wait_for_url(f"{base_url}/")                     # 等登录跳转完成
    return page
```

然后需要登录的测试用 `logged_in_page` 代替 `page` 即可。在 `CLAUDE.md` 的「登录逻辑」一行注明入口，test-writing agent 写需要登录的用例时会用上它。

> ⚠️ 凭据走环境变量 / `.env`（已 gitignore），**不要把账号密码提交进仓库**。

### 第 3 步：声明项目约定

打开 **`CLAUDE.md`** 改「项目约定」表——agent 每次干活前都读它：

| 约定 | 默认值（本 demo） | 换成你的 |
|---|---|---|
| 站点基础 URL | `https://testerhome.com` | 同第 1 步 |
| 页面地图目录 | `page_map/` | 一般保持 |
| 测试代码目录 + 运行命令 | `tests/`，`python -m pytest tests/ -v` | 你的目录 / 命令 |
| 测试数据目录 | `data/`（YAML） | 你已有的数据驱动层 |
| 登录逻辑 | demo 只读、无需登录 | 指向第 2 步的 fixture |

### 第 4 步：清掉 demo 产物，让 agent 重新生成

demo 自带的 TesterHome 产物删掉即可，agent 会按你的站点重新探索生成：

```bash
rm -f page_map/testerhome/*.yaml      # 旧页面地图
rm -f tests/test_*.py                 # 旧测试
rm -f data/testerhome.yaml            # 旧数据
rm -rf artifacts/2026-*               # 旧任务归档（保留 artifacts/README.md 和 agents/）
```

---

## 🚀 然后就是「说人话」驱动测试

这是整套 harness 的核心用法——**接入完成后，你不用再手写一行测试代码，只要对 Claude Code 主对话用自然语言描述要测什么**，编排就会自动跑起来（探索页面 → 结构化解构需求（你审 GATE 0）→ 生成用例和操作流（你审 GATE 1）→ 写代码 → 审查）：

```text
用户登录后，在商品列表搜索关键词，加入购物车，校验购物车数量和金额
```

agent 会先把这段需求拆成 6 张结构化表（功能点、字段规格、状态机、业务规则、操作旅程、影响面），
你在 GATE 0 扫一遍表格 cell（比读用例清单判断"够不够"轻松得多）；确认后 agent 才查表生成正式
用例和操作流对照单，你在 GATE 1 对照 UI 设计图核对一遍；确认后落成测试代码并自跑自修。
**你描述「测什么」，harness 负责「怎么测」和「测没测全」。**

> 💡 想看它真实跑出来什么样？仓库里 `artifacts/2026-06-23_testerhome_home_search/` 保留了一次完整运行的全部产物（`sync.md` / `cases.md` / `impl.md` / `review.md` / `progress.log`），可以照着看每一步的输入输出。

---

## 目录

```
.claude/agents/               4 个原生子 agent 定义（page-map-sync / test-case-design / test-writing / review）
artifacts/README.md           编排总览：artifact schema、状态枚举、gate、红线、progress.log
artifacts/agents/             5 个角色规范（含 orchestrator）+ decomposition.md（解构层方法论）
tools/decomp_review.py        decomp.md 批注服务器（内部工作用，GATE 0 前自查）
tools/checkpoint_review.py    检查点清单评审服务器（GATE 0 正式人审介质，可选用法）
tools/checkpoint_audit.py     机器查账：孤儿行（漏覆盖）+ 幽灵回指（agent 编造溯源）
page_map/                     页面地图（YAML，描述当前部署的页面元素/selector）
data/                         测试数据
tests/                        测试代码
scripts/journal.py            运行日志：hook 客观记录 + agent 叙事「为什么」，用于复盘 agent 行为
CLAUDE.md                     项目约定（接入方在此声明自己的目录/命令/登录）
rule.md                       技术避坑（selector 写法、等待时机）
```

每跑一个任务会在 `artifacts/<task_id>/` 下归档 `state.md` / `sync.md` / `decomp.md` / `cases.md` /
`flow.md` / `ops_review.md` / `impl.md` / `review.md` / `progress.log` / `journal.jsonl`
（运行日志，见 `artifacts/README.md`「运行日志 Journal」）。未涉及的阶段跳过对应文件。

---

## License

[Apache-2.0](./LICENSE)
