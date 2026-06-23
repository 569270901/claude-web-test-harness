# claude-web-test-harness

一套**领域无关**的多 agent UI 自动化测试编排骨架。把它放进任意 Web 项目，用 [Claude Code](https://claude.com/claude-code) 驱动「探索页面 → 设计用例 → 写测试 → 审查」这条流水线。

> 演示站点用 [TesterHome](https://testerhome.com)（QA 社区论坛），demo 流程全部**只读**（浏览/搜索/断言渲染），不涉及注册登录发帖。

---

## 它解决什么

写 UI 自动化的真实流程是：**摸清页面有哪些元素 → 根据需求设计测试点 → 落成测试代码 → 有人 review**。
这套 harness 把这四步固化成四个隔离的 Claude Code 子 agent，用 artifact 文档接力，关键节点设人工 gate：

```
   你(orchestrator/主对话)
        │  派发
        ▼
┌─────────────────┐   ┌──────────────────┐   ┌───────────────┐   ┌──────────┐
│ page-map-sync   │ → │ test-case-design │ → │ test-writing  │ → │ review   │
│ 探页面→页面地图 │   │ 需求→用例(待审) │   │ 用例→测试代码 │   │ 静态审查 │
└─────────────────┘   └──────────────────┘   └───────────────┘   └──────────┘
   page_map/*.yaml       cases.md (GATE)         test 代码           verdict
```

**机制是通用的，业务是你的。** harness 本身不含任何业务概念——你的页面地图、登录逻辑、测试约定通过几个目录约定接进来。

---

## 前提：依赖 Claude Code

这套 harness 的「执行引擎」就是 Claude Code 本身——子 agent 派发（`.claude/agents/`）、Skill / Agent 工具、artifact 接力都跑在 Claude Code 里。
**没有 Claude Code，这个仓库只是一堆 markdown + 一个普通的 pytest-playwright 工程。** 接入前请确认你在用 Claude Code。

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
#    主对话会按需派发 page-map-sync → test-case-design →(你审核)→ test-writing → review
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

这是整套 harness 的核心用法——**接入完成后，你不用再手写一行测试代码，只要对 Claude Code 主对话用自然语言描述要测什么**，编排就会自动跑起来（探索页面 → 设计用例 →（你审核）→ 写代码 → 审查）：

```text
用户登录后，在商品列表搜索关键词，加入购物车，校验购物车数量和金额
```

agent 会自己去探索这些页面、设计覆盖正常/边界的用例、停下来等你审核用例清单、再落成测试代码并自跑自修。**你描述「测什么」，harness 负责「怎么测」。**

> 💡 想看它真实跑出来什么样？仓库里 `artifacts/2026-06-23_testerhome_home_search/` 保留了一次完整运行的全部产物（`sync.md` / `cases.md` / `impl.md` / `review.md` / `progress.log`），可以照着看每一步的输入输出。

---

## 目录

```
.claude/agents/        4 个原生子 agent 定义（page-map-sync / test-case-design / test-writing / review）
artifacts/README.md    编排总览：artifact schema、状态枚举、gate、红线、progress.log
artifacts/agents/      5 个角色规范（含 orchestrator）
page_map/              页面地图（YAML，描述当前部署的页面元素/selector）
data/                  测试数据
tests/                 测试代码
CLAUDE.md              项目约定（接入方在此声明自己的目录/命令/登录）
rule.md                技术避坑（selector 写法、等待时机）
```

每跑一个任务会在 `artifacts/<task_id>/` 下归档 `state.md` / `sync.md` / `cases.md` / `impl.md` / `review.md` / `progress.log`。

---

## License

[Apache-2.0](./LICENSE)
