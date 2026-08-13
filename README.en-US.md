# claude-web-test-harness

A **domain-agnostic** multi-agent UI automation test orchestration skeleton. Drop it into any Web project and use [Claude Code](https://claude.com/claude-code) to drive the pipeline: "Explore Page → Design Cases → Write Tests → Review."

> The demo site uses [TesterHome](https://testerhome.com) (a QA community forum). All demo flows are **read-only** (browsing/searching/asserting rendering) and do not involve registration, login, or posting.

---

## What it Solves

The real workflow of writing UI automation is: **Understanding which elements are on the page → Designing test points based on requirements → Implementing test code → Reviewing the work**.

This harness solidifies these four steps into four isolated Claude Code sub-agents. They pass information via artifact documents, with manual "gates" at critical nodes:

```
   You (orchestrator/main chat)
        │  Dispatch
        ▼
┌─────────────────┐   ┌──────────────────┐   ┌───────────────┐   ┌──────────┐
│ page-map-sync   │ → │ test-case-design │ → │ test-writing  │ → │ review   │
│ Page Map Sync   │   │ Req → Cases     │   │ Cases → Code   │   │ Static   │
└─────────────────┘   └──────────────────┘   └───────────────┘   └──────────┘
   page_map/*.yaml       cases.md (GATE)         test code           verdict
```

**The mechanism is universal; the business logic is yours.** The harness itself contains no business concepts—your page maps, login logic, and test conventions are integrated via a few directory agreements.

---

## Prerequisite: A Coding Tool capable of running agents (Claude Code preferred)

The "execution engine" of this harness is an **agentic coding tool**—it acts as the orchestrator, scheduling roles, reading/writing artifacts, and running tests.

The underlying mechanism (role specifications in `artifacts/agents/*.md`, artifact schema, pipeline, and `page_map`/`data`/`tests` conventions) consists of **Markdown + a standard pytest-playwright project**, making it agnostic to any specific tool.

### Using Claude Code (Native support, out-of-the-box)

Claude Code can directly read `.claude/agents/` (sub-agent definitions) and `CLAUDE.md` (project conventions) to perform **isolated sub-agent dispatching** natively, so it runs with zero configuration. The "Quick Start" below follows the Claude Code flow.

### Using Codex / CodeBuddy / Other agent tools (Via compatibility prompt)

Other tools may lack Claude Code's sub-agent dispatching and `CLAUDE.md` auto-loading. However, since the role specifications are pure Markdown, you can have a **single agent read the specifications and play each role sequentially** to simulate the pipeline. Feed it the following prompt:

```text
You are the test orchestration orchestrator for this repository. First, read these files to understand the mechanism:
- artifacts/README.md (Orchestration spec: artifact schema, status enums, gates, red lines, progress.log)
- All role specs under artifacts/agents/ (orchestrator / page-map-sync / test-case-design / test-writing / review)
- CLAUDE.md (Project conventions: site URL, directories, login, development principles)
- rule.md (Technical red lines, such as selector patterns)

Then execute this pipeline in order (since you do not have isolated sub-agents, play each role sequentially within the current context):
page-map-sync → test-case-design → (Stop and wait for me to review cases.md) → test-writing → review

Strictly adhere to:
1. Each role must produce a corresponding artifact with complete frontmatter (see schema in artifacts/README.md)
2. Once cases.md is produced, set status=pending_review and STOP to wait for my confirmation; do not skip this gate
3. Append a line to artifacts/<task_id>/progress.log at critical stages
4. Never delete assertions just to make a test pass; avoid hash classes / :nth-child / xpath positional indices for selectors

My requirement is: <Write what you want to test here>
```

> Note: Non-Claude Code tools "simulate multiple roles in a single context" and lack true process isolation, which can lead to context drift in long tasks. It is recommended to run only one pipeline at a time and frequently check `progress.log`. Any sufficiently capable agent tool can run this; effectiveness depends on the tool itself.

---

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt
python -m playwright install chromium

# 2. Run the included example tests (to prove the scaffold works)
python -m pytest tests/ -v

# 3. Open Claude Code in the project directory and start the orchestration with one sentence:
#    "Design and write a set of read-only tests for the TesterHome homepage and search"
#    The main chat will dispatch page-map-sync → test-case-design → (your review) → test-writing → review
```

While the orchestration is running, you can monitor progress in another terminal:

```bash
tail -f artifacts/<task_id>/progress.log
```

---

## Integrating into Your Own Project

The harness doesn't rely on a config file, but on **directory conventions + a `CLAUDE.md` file**. The agent specifications contain no hard-coded business paths—they adapt by reading `CLAUDE.md`. To replace the demo with your own project, follow these four steps:

### Step 1: Change Base URL (Required)

The site address is defined in **`pytest.ini` under `--base-url`**. Change it to your environment:

```ini
# pytest.ini
addopts = --tb=short --base-url=https://your-app.example.com
```

Tests retrieve this via the built-in `base_url` fixture from pytest-playwright, so you don't need to hardcode the domain in your code. Update the "Project Conventions" table in `CLAUDE.md` as well (the agent reads this to understand your site).

### Step 2: Add Login Logic (Optional)

The demo is entirely read-only and doesn't require login. To test pages behind a login, add a fixture to **`conftest.py`** (placeholder comments are provided in the file):

```python
import pytest

@pytest.fixture
def logged_in_page(page, base_url):
    page.goto(f"{base_url}/account/sign_in")
    page.fill("input#user_login", "your-test-account")   # Replace selector with your site's
    page.fill("input#user_password", "***")              # Use env variables for real passwords; do not commit to repo
    page.click("button[type=submit]")
    page.wait_for_url(f"{base_url}/")                     # Wait for login redirect
    return page
```

Tests that require authentication can then use `logged_in_page` instead of `page`. Note the entry point in the "Login Logic" line of `CLAUDE.md`; the `test-writing` agent will use it when creating authenticated test cases.

> ⚠️ Use environment variables or `.env` (already gitignored) for credentials. **Do not commit usernames or passwords to the repository.**

### Step 3: Declare Project Conventions

Open **`CLAUDE.md`** and update the "Project Conventions" table—the agent reads this before every task:

| Convention | Default (this demo) | Change to yours |
|---|---|---|
| Base Site URL | `https://testerhome.com` | See Step 1 |
| Page Map Directory | `page_map/` | Usually kept as is |
| Test Code Directory + Run Command | `tests/`, `python -m pytest tests/ -v` | Your directory / command |
| Test Data Directory | `data/` (YAML) | Your existing data-driven layer |
| Login Logic | Demo is read-only, no login | Point to the fixture from Step 2 |

### Step 4: Clear Demo Artifacts

Delete the TesterHome demo artifacts; the agent will re-explore and generate new ones for your site:

```bash
rm -f page_map/testerhome/*.yaml      # Old page maps
rm -f tests/test_*.py                 # Old tests
rm -f data/testerhome.yaml            # Old data
rm -rf artifacts/2026-*               # Old task archives (keep artifacts/README.md and agents/)
```

---

## 🚀 Then, Drive Testing with Natural Language

This is the core value of the harness—**once integrated, you no longer need to write a single line of test code by hand. Just describe what you want to test to the Claude Code main chat**, and the orchestration will automatically execute (Explore → Design → Review → Implement → Verify):

```text
After the user logs in, search for a keyword in the product list, add it to the cart, and verify the cart quantity and total amount.
```

The agent will explore the pages, design cases covering normal and edge scenarios, stop for your approval of the case list, implement the test code, and self-correct through execution. **You describe "what to test," and the harness handles "how to test."**

> 💡 Want to see a real-world example? The folder `artifacts/2026-06-23_testerhome_home_search/` contains all artifacts from a complete run (`sync.md` / `cases.md` / `impl.md` / `review.md` / `progress.log`). You can follow it to see the input and output of each step.

---

## Directory Structure

```
.claude/agents/        4 native sub-agent definitions (page-map-sync / test-case-design / test-writing / review)
artifacts/README.md    Orchestration overview: artifact schema, status enums, gates, red lines, progress.log
artifacts/agents/      5 role specifications (including orchestrator)
page_map/              Page maps (YAML, describes elements/selectors of the current deployment)
data/                  Test data
tests/                 Test code
scripts/journal.py     Execution log: hooks for objective records + agent narratives on "why," used for reviewing agent behavior
CLAUDE.md              Project conventions (integration party declares directories/commands/login here)
rule.md                Technical pitfalls (selector patterns, waiting strategies)
```

Each task run is archived under `artifacts/<task_id>/` containing `state.md` / `sync.md` / `cases.md` / `impl.md` / `review.md` / `progress.log` / `journal.jsonl` (execution log, see "Running Log Journal" in `artifacts/README.md`).

---

## License

[Apache-2.0](./LICENSE)
