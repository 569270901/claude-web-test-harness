# 项目指南（接入方在此声明自己的约定）

> 这是多 agent UI 测试 harness 的项目约定文件。**agent 读它来自适应你的项目**，
> 没有硬编码业务路径。接入你自己的项目时，改下面「项目约定」一节即可。
> demo 默认值面向 TesterHome（只读流程）。

## 必读文件

每次写代码 / 写测试 / 补页面地图前，先读：

- `rule.md` — 编码规则与技术避坑（selector 写法、等待时机、组件行为）
- `artifacts/README.md` — 多 agent 编排总览（artifact schema、gate、红线、progress.log）
- 相关的 `page_map/*.yaml` — 当前页面元素地图

发现新知识主动回写：技术坑 → `rule.md`；页面元素变化 → 对应 `page_map/*.yaml`。

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

---

## 开发原则

- **所有字段都填（包括非必填）、都断言**
- **绝不删断言来让测试通过——失败就是 bug**
- `expected` 避免用 `"0"`，用有语义的值
- 注释用中文
- selector 优先 ID / role / 稳定属性，禁用 hash class / `:nth-child` / xpath 位置索引（详见 `rule.md`）

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
```

---

## demo 任务（验证 harness 跑通）

在本目录打开 Claude Code，对主对话说：

> 「为 TesterHome 首页 + 搜索设计一套只读测试并写出来」

主对话（orchestrator）会按需派发：
`page-map-sync → test-case-design(阶段1解构→decomp.md，你审 GATE 0) → test-case-design(阶段2生成→cases.md+flow.md，你审 GATE 1) → test-writing → review`。
**只做只读流程**（浏览话题列表、打开帖子详情、搜索关键词、断言渲染），不要自动化注册/登录/发帖。
