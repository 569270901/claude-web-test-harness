[English](README.md) | **中文**

# claude-web-test-harness

一套用 [Claude Code](https://claude.com/claude-code) 驱动的多智能体 UI 自动化测试框架。放进你的 Web 项目里，跟它说一句"帮我测一下 xxx"，它会自己去摸页面、列检查点、写用例、写代码、跑起来——**关键地方停下来让你确认，不会自作主张**。

> 演示站点用 [TesterHome](https://testerhome.com)（QA 社区论坛），demo 流程全部**只读**（浏览/搜索/断言渲染），不涉及注册登录发帖。

---

## 它解决什么

写 UI 自动化的真实流程，拆开来是这五步：

**摸清页面有哪些元素 → 列一份检查点清单，确认测试没漏东西 → 把检查点变成正式用例和操作步骤，
确认没写错 → 生成测试代码并自己跑 → 有人复查代码质量**

这套 harness 把这五步交给 5 个角色分工完成，角色之间靠文档接力（不是直接对话），到了该你确认
的地方就停下来等你：

```
   你
   │ 提需求
   ▼
┌────────────┐   ┌──────────────────────────┐   ┌─────────────┐   ┌────────┐
│ 摸页面     │ → │ 列检查点(你确认) →       │ → │ 写代码并自跑│ → │ 复查   │
│            │   │ 变成正式用例(你确认)      │   │             │   │        │
└────────────┘   └──────────────────────────┘   └─────────────┘   └────────┘
 页面地图文件        检查点清单 → 用例+操作步骤       测试代码          结论
```

### 为什么中间要多列一份"检查点清单"，不直接写用例

如果直接从需求跳到"写用例"，容易漏东西，而且**漏了也没法事后检查**——需求里没提到的场景，
最后的表现就是"用例清单里少了一条"，而"少了一条"这件事本身不会让人多看一眼。

所以中间插一步：先把需求拆成一份**检查点清单**（6 类，用大白话说就是）：

| 类别 | 检查什么 |
|---|---|
| 功能点清单 | 这个功能要测哪些点 |
| 字段规格 | 每个字段的规则——必填吗？最长多少？默认值是什么？ |
| 状态流转 | 状态之间能怎么切换，哪些切换是不允许的 |
| 业务规则 | 有哪些附加限制条件 |
| 操作步骤 | 用户具体怎么点、点完出现什么 |
| 影响范围 | 这个改动会不会牵连到别的功能 |

清单里填不上、拿不准的地方会**原样标出来**，不会悄悄跳过或者瞎编。你只要扫一眼这份清单——
"这一类范围对不对""这几处不确定的我知道答案""这个状态没写清楚该不该允许"——这比事后拿到
一份几十条的用例清单、凭感觉判断"测全了没有"要轻松得多。**判断"这一条写得对不对"是你的强项，
判断"一份清单全不全"才是最容易漏看的地方。**

确认完这份检查点清单，harness 才会照着它查表生成正式的用例和"用户具体怎么操作"的步骤说明，
这一步同样会停下来让你确认一遍，然后才落成测试代码。

想看更详细的方法论（这份检查点清单具体怎么填、每个类别的判断标准），见
[`artifacts/agents/decomposition.md`](artifacts/agents/decomposition.md)——不看也完全不影响正常使用，
harness 会自己按这套方法走。

**机制是通用的，业务是你的。** harness 本身不含任何业务概念——你的页面地图、登录逻辑、测试约定通过几个目录约定接进来。

---

## 前提：一个能跑 AI agent 的编程工具（首选 Claude Code）

这套 harness 靠一个 **AI 编程工具**充当"总调度"——它负责安排各个角色干活、读写文档、跑测试。
harness 本身只是 **一堆 markdown 说明文档 + 一个普通的 pytest-playwright 项目**，不绑定任何一家工具。

### 用 Claude Code（原生支持，开箱即用）

Claude Code 能直接读 `.claude/agents/`（角色定义）和 `CLAUDE.md`（项目约定），零配置就能跑。下面「快速开始」就是 Claude Code 的流程。

### 用 Codex / CodeBuddy / 其他 agent 工具（喂一段说明 prompt）

其他工具没有 Claude Code 那种"派发独立角色"的原生能力，但 harness 的说明都是纯 markdown，可以让**同一个 agent 依次扮演每个角色**来走完整个流程。把下面这段喂给它即可：

```text
你是这个仓库的测试编排总调度。先读这几份文件理解怎么干活：
- artifacts/README.md（总览：文档格式、状态、需要停下确认的地方、红线）
- artifacts/agents/ 下全部角色说明（总调度 / 摸页面 / 列检查点+写用例 / 写代码 / 复查）
- artifacts/agents/decomposition.md（"检查点清单"具体怎么填的方法论）
- CLAUDE.md（项目约定：站点 URL、目录、登录、开发原则）
- rule.md（selector 写法等技术红线）

然后按这条流程依次执行（你没有独立角色隔离，就在当前对话里依次扮演每个角色）：
摸页面 → 列检查点清单 →（停下来等我确认）→ 生成正式用例和操作步骤 →（停下来等我确认）
→ 写代码并自跑 → 复查

严格遵守：
1. 每个角色产出对应的文档，格式完整（具体格式见 artifacts/README.md）
2. 检查点清单、用例和操作步骤产出后必须停下等我确认，不准跳过
3. 关键阶段写一行日志到 artifacts/<task_id>/progress.log
4. 绝不删断言来让测试通过；selector 禁用 hash class / :nth-child / xpath 位置索引

我的需求是：<在这里写你要测什么>
```

> 注意：非 Claude Code 工具是"一个 agent 依次扮演多个角色"，没有真正的上下文隔离，长任务容易信息串味；建议一次只跑一条流程、勤看 `progress.log`。效果取决于所用工具本身的能力。

---

## 快速开始

```bash
# 1. 装依赖
pip install -r requirements.txt
python -m playwright install chromium

# 2. 先跑一下自带的示例测试（证明脚手架能跑）
python -m pytest tests/ -v

# 3. 在本项目目录打开 Claude Code，对主对话说一句话即可启动：
#    「为 TesterHome 首页+搜索设计一套只读测试并写出来」
#    它会自己按 摸页面 → 列检查点(你确认) → 生成用例(你确认) → 写代码自跑 → 复查 这条流程走
```

跑的过程中，用另一个终端实时看进度：

```bash
tail -f artifacts/<task_id>/progress.log
```

---

## 接进你自己的项目

harness 不靠配置文件，靠**目录约定 + 一份 `CLAUDE.md`**。里面没有硬编码任何业务路径——都是读 `CLAUDE.md` 自适应。把 demo 换成你自己的项目，按下面四步改：

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

然后需要登录的测试用 `logged_in_page` 代替 `page` 即可。在 `CLAUDE.md` 的「登录逻辑」一行注明入口，写代码这一步会用上它。

> ⚠️ 凭据走环境变量 / `.env`（已 gitignore），**不要把账号密码提交进仓库**。

### 第 3 步：声明项目约定

打开 **`CLAUDE.md`** 改「项目约定」表——每个角色干活前都读它：

| 约定 | 默认值（本 demo） | 换成你的 |
|---|---|---|
| 站点基础 URL | `https://testerhome.com` | 同第 1 步 |
| 页面地图目录 | `page_map/` | 一般保持 |
| 测试代码目录 + 运行命令 | `tests/`，`python -m pytest tests/ -v` | 你的目录 / 命令 |
| 测试数据目录 | `data/`（YAML） | 你已有的数据驱动层 |
| 登录逻辑 | demo 只读、无需登录 | 指向第 2 步的 fixture |

### 第 4 步：清掉 demo 产物，让它重新生成

demo 自带的 TesterHome 产物删掉即可，harness 会按你的站点重新探索生成：

```bash
rm -f page_map/testerhome/*.yaml      # 旧页面地图
rm -f tests/test_*.py                 # 旧测试
rm -f data/testerhome.yaml            # 旧数据
rm -rf artifacts/2026-*               # 旧任务归档（保留 artifacts/README.md 和 agents/）
```

---

## 🚀 然后就是「说人话」驱动测试

这是整套 harness 的核心用法——**接入完成后，你不用再手写一行测试代码，只要用自然语言描述要测什么**：

```text
用户登录后，在商品列表搜索关键词，加入购物车，校验购物车数量和金额
```

它会自己去探索这些页面、把这段需求拆成检查点清单（这个功能有哪些点、每个字段什么规则、
状态怎么切换、有什么业务限制、用户具体怎么操作、会不会影响别的功能）——**停下来等你扫一眼**；
你确认后，才照着清单生成正式用例和操作步骤——**再停下来等你确认一遍**；两轮确认过后，
落成测试代码并自跑自修。**你描述「测什么」，它负责「怎么测」和「有没有测全」，你只需要在
两个节点上点头或纠正。**

> 💡 想看它真实跑出来什么样？仓库里 `artifacts/2026-06-23_testerhome_home_search/` 保留了一次
> 完整运行的全部产物，可以照着看每一步的输入输出。

---

## 目录

```
.claude/agents/               4 个角色的定义（摸页面 / 列检查点+写用例 / 写代码 / 复查）
artifacts/README.md           总览：文档格式、状态、确认点、红线、进度日志
artifacts/agents/             5 个角色的详细说明（含总调度）+ decomposition.md（检查点清单方法论）
tools/                        辅助脚本：网页版检查点清单批注工具、漏项/编造溯源核查工具
page_map/                     页面地图（YAML，描述当前部署的页面元素/selector）
data/                         测试数据
tests/                        测试代码
scripts/journal.py            运行日志：自动记录 + 角色自述"为什么这么判断"，用于事后复盘
CLAUDE.md                     项目约定（接入方在此声明自己的目录/命令/登录）
rule.md                       技术避坑（selector 写法、等待时机）
```

每跑一个任务会在 `artifacts/<task_id>/` 下留存这次跑下来的全部文档（检查点清单、用例、
操作步骤、测试代码改动记录、复查结论、进度日志），方便回头查每一步的输入输出。

---

## License

[Apache-2.0](./LICENSE)
