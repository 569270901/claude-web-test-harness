**English** | [中文](README.zh-CN.md)

# claude-web-test-harness

A multi-agent UI test automation framework driven by [Claude Code](https://claude.com/claude-code). Drop it into your Web project, tell it "help me test xxx", and it explores the pages, drafts a checklist, writes test cases, writes the code, and runs it — **pausing at the key checkpoints so you confirm before it moves on, instead of guessing on its own.**

> The demo site is [TesterHome](https://testerhome.com) (a QA community forum). The demo flow is entirely **read-only** (browsing, searching, asserting rendered content) — no signup/login/posting is automated.

---

## What problem it solves

The real workflow behind writing UI automation breaks down into five steps:

**Figure out what's on the page → draft a checklist confirming nothing is missed → turn the
checklist into formal test cases and step-by-step actions, confirm they're correct → generate
test code and run it → have someone review the code**

This harness assigns these five steps to 5 roles that hand off work through documents (not
direct conversation), pausing wherever you need to confirm:

```
   you
   │ describe what to test
   ▼
┌────────────┐   ┌──────────────────────────────┐   ┌──────────────┐   ┌────────┐
│ explore    │ → │ draft checklist (you confirm) │ → │ code & run   │ → │ review │
│ pages      │   │ → turn into test cases         │   │ tests        │   │        │
│            │   │   (you confirm)                │   │              │   │        │
└────────────┘   └──────────────────────────────┘   └──────────────┘   └────────┘
 page map file      checklist → cases + steps           test code          verdict
```

### Why draft a "checklist" instead of writing test cases straight away

Jumping straight from requirements to "write test cases" makes it easy to miss things — and
**there's no way to check afterward whether something was missed**. A scenario the requirements
never mention simply shows up as "one fewer test case" in the final list, and a missing item
by itself never draws anyone's attention.

So a step is inserted in between: break the requirements down into a **checklist** first
(7 categories, in plain terms):

| Category | What it checks |
|---|---|
| Feature list | What points this feature needs to be tested on |
| Field specs | The rules for each field — required? max length? default value? |
| State transitions | How states can change, and which transitions are disallowed |
| Business rules | What extra constraints apply |
| User journeys | What the user actually clicks, and what happens next |
| Impact scope | Whether this change could affect other features |
| Element specs | What each on-screen element should look like in each situation — its exact wording, and whether it should even show up for this role, in this state |

Anything the checklist can't fill in or isn't sure about **is flagged as-is** — never silently
skipped or made up. All you need to do is scan this list — "is this category's scope right",
"I know the answer to these uncertain items", "this state transition wasn't specified, should
it be allowed or not" — which is far easier than being handed a list of dozens of test cases
afterward and having to judge by feel whether "everything" was covered. **Judging whether one
line is correct is something you're good at; judging whether a whole list is complete is
exactly where things get missed.**

And you don't even have to look at every flagged item: each one is first sorted into
"**someone has to decide this**" versus "**we'll just see when the build lands**", and only the
first kind is put in front of you. (Why: an earlier version pushed every single open question at
the user indiscriminately — one small feature produced 33 cards to decide on, which nobody can
get through. A review nobody finishes is the same as no review at all.)

Once you confirm the checklist, the harness generates the formal test cases and the
"what the user actually does" step-by-step description from it — that step also pauses for
your confirmation before the test code gets written.

For the full methodology (exactly how the checklist gets filled in, and the judgment criteria
for each category), see
[`artifacts/agents/decomposition.md`](artifacts/agents/decomposition.md) — you don't need to
read it to use the harness normally; it follows this method on its own.

**The mechanism is generic, the business logic is yours.** The harness itself contains no
business concepts — your page maps, login logic, and testing conventions are plugged in
through a handful of directory conventions.

---

## Prerequisite: a coding tool that can run AI agents (Claude Code recommended)

This harness relies on an **AI coding tool** to act as the "dispatcher" — it's responsible for
telling each role what to do, reading/writing documents, and running tests. The harness itself
is just **a pile of markdown instructions + an ordinary pytest-playwright project**; it isn't
tied to any one tool.

### With Claude Code (native support, works out of the box)

Claude Code can directly read `.claude/agents/` (role definitions) and `CLAUDE.md` (project
conventions), so it runs with zero configuration. The "Quick Start" section below is the
Claude Code flow.

### With Codex / CodeBuddy / other agent tools (feed it a compatibility prompt)

Other tools don't have Claude Code's native ability to dispatch isolated roles, but the
harness's instructions are all plain markdown, so you can have **a single agent play each role
in sequence** to walk the whole pipeline. Feed it this prompt:

```text
You are the test orchestration dispatcher for this repo. First read these files to understand
how it works:
- artifacts/README.md (overview: document formats, statuses, where to pause for confirmation, hard rules)
- everything under artifacts/agents/ (dispatcher / page explorer / checklist+test-case design / test writing / review)
- artifacts/agents/decomposition.md (the methodology for how the "checklist" gets filled in)
- CLAUDE.md (project conventions: site URL, directories, login, development principles)
- rule.md (technical hard rules such as selector conventions)

Then execute this pipeline in order (you don't have isolated sub-roles, so play each role in
sequence within the current conversation):
explore pages → draft checklist → (pause for my confirmation) → generate formal test cases and
steps → (pause for my confirmation) → write code and run it → review

Strictly follow these rules:
1. Each role produces its corresponding document with a complete format (see artifacts/README.md
   for the exact schema)
2. You must pause and wait for my confirmation after producing the checklist and the test
   cases/steps — never skip this
3. Append a log line to artifacts/<task_id>/progress.log at each key stage
4. Never delete assertions just to make a test pass; selectors must not use hash classes,
   :nth-child, or positional xpath indices

My requirement is: <describe what you want tested here>
```

> Note: non-Claude-Code tools run as "one agent playing multiple roles", without true context
> isolation — long tasks can bleed context between roles. Run one pipeline at a time and watch
> `progress.log` closely. Results depend on the capability of the tool you're using.

---

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt
python -m playwright install chromium

# 2. Run the bundled sample tests first (proves the scaffold works)
python -m pytest tests/ -v

# 3. Open Claude Code in this project directory and just say what you want, e.g.:
#    "Design and write a read-only test suite for the TesterHome homepage and search"
#    It will automatically dispatch: explore pages → draft checklist (you confirm) →
#    generate test cases (you confirm) → write code & self-run → review
```

While it's running, watch progress live in another terminal:

```bash
tail -f artifacts/<task_id>/progress.log
```

---

## Plugging in your own project

The harness has no config files — it relies on **directory conventions + one `CLAUDE.md`**.
Nothing is hardcoded to any particular business path; everything adapts by reading `CLAUDE.md`.
Swap out the demo for your own project in four steps:

### Step 1: Change the base URL (required)

The site address lives in **`pytest.ini`'s `--base-url`** — change it to your environment:

```ini
# pytest.ini
addopts = --tb=short --base-url=https://your-app.example.com
```

Tests pick it up via pytest-playwright's built-in `base_url` fixture, so no domain is hardcoded
in the test code. Also update the "Project Conventions" table in `CLAUDE.md` (the agents read
it to understand your site).

### Step 2: Add login logic (as needed)

The demo is entirely read-only and needs no login. To test pages behind a login, add a fixture
in **`conftest.py`** (there's already a placeholder comment in the file):

```python
import pytest

@pytest.fixture
def logged_in_page(page, base_url):
    page.goto(f"{base_url}/account/sign_in")
    page.fill("input#user_login", "your-test-account")   # swap in your site's selectors
    page.fill("input#user_password", "***")               # use env vars for real passwords, never commit them
    page.click("button[type=submit]")
    page.wait_for_url(f"{base_url}/")                     # wait for the post-login redirect
    return page
```

Tests that need to be logged in then use `logged_in_page` instead of `page`. Note the entry
point on the "Login logic" line in `CLAUDE.md`, and the test-writing step will pick it up
automatically.

> ⚠️ Credentials go through environment variables / `.env` (already gitignored) —
> **never commit account credentials into the repo.**

### Step 3: Declare your project conventions

Open **`CLAUDE.md`** and edit the "Project Conventions" table — every role reads it before
doing any work:

| Convention | Default value (this demo) | Change to yours |
|---|---|---|
| Site base URL | `https://testerhome.com` | Same as step 1 |
| Page map directory | `page_map/` | Usually keep as-is |
| Test code directory + run command | `tests/`, `python -m pytest tests/ -v` | Your directory / command |
| Test data directory | `data/` (YAML) | Your existing data-driven layer |
| Login logic | Demo is read-only, no login needed | Point to the fixture from step 2 |

### Step 4: Clear out the demo artifacts and let it regenerate

Just delete the bundled TesterHome artifacts — the harness will re-explore and regenerate them
for your site:

```bash
rm -f page_map/testerhome/*.yaml      # old page map
rm -f tests/test_*.py                 # old tests
rm -f data/testerhome.yaml            # old data
rm -rf artifacts/2026-*               # old task archives (keep artifacts/README.md and agents/)
```

---

## 🚀 Then just drive testing by describing what you want in plain language

This is the core workflow of the whole harness — **once it's plugged in, you never write a line
of test code by hand; you just describe what to test in natural language**:

```text
After the user logs in, search for a keyword in the product list, add it to the cart, and
verify the cart's item count and total price.
```

It will explore the relevant pages on its own, break this requirement down into a checklist
(what points this feature needs testing on, what rules each field has, how states transition,
what business constraints apply, exactly what the user does, whether it could affect other
features) — **and pause for you to scan it**; once you confirm, it generates the formal test
cases and step-by-step actions from the checklist — **and pauses again for your confirmation**;
after both confirmations, it writes the test code and self-runs/self-repairs it.
**You describe "what to test", it handles "how to test it" and "whether it's fully covered" —
you just need to nod or correct it at two checkpoints.**

> 💡 `artifacts/2026-06-23_testerhome_home_search/` in this repo holds one early trial run, but
> it predates the current two-phase methodology (no decomp.md/GATE 0) and part of what it
> describes never actually landed in the codebase — see the disclaimer at the top of each file
> in that folder. A real, up-to-date example run is on the to-do list (best produced against a
> project with real login/state, where the full GATE 0/1/2 pipeline actually gets exercised).

---

## The console — where you do your confirming

The two confirmation points don't have to happen by reading raw markdown in a terminal. There's
a small local console (pure standard library, nothing to install) that opens in your browser:

```bash
python3 tools/qa_console.py            # one port, pick the version → the feature → the view
```

What it gives you:

- **The open questions arrive pre-sorted.** Anything the harness is unsure about gets split into
  "someone has to decide this" and "we'll find out by looking once it's built", and only the
  first kind is put in front of you. This exists because an earlier version pushed all of them at
  the user equally — one small feature produced **33 cards to decide on**, and a pile that big
  just doesn't get read. Your decisions are saved as a separate file; the checklist itself is
  never edited behind your back, and a snapshot is taken before anything is written back.
- **You can actually edit the test cases, not just approve or reject them.** Spotting a case
  that's wrong, or one that's missing, and being able to fix it on the spot is the whole point of
  a review. Every edit is keyed by case ID (not line number, which drifts), snapshots the file
  the first time you touch it, and appends to an audit log recording the previous value — so
  everything is reversible and traceable.
- **Test results fill themselves in, by case ID.** Add `-p tools.pytest_case_ledger` to your
  pytest run and every result is matched back to the case it belongs to (it just needs the case
  ID in the test's docstring — no changes to your existing tests). Automated runs and manual runs
  are kept as **two separate lanes**, and when the two disagree about the same case, that row is
  **highlighted** — a case that passes by hand and fails in CI (or the reverse) is exactly where
  bugs like to hide.
- **A hard-rule scan before you commit.** `scripts/check_compliance.py` statically flags things
  like deleted assertions, placeholder expected values, and banned selector patterns. Install it
  as a git hook once and it runs on every commit:

  ```bash
  bash scripts/install_hooks.sh
  ```

  The rules live in `configs/compliance-rules.json` — most default to warnings rather than errors
  on purpose, because a scanner that cries wolf just teaches people to suppress it.

---

## Layout

```
.claude/agents/               Definitions for the 4 roles (page explorer / checklist+test-case design / test writing / review)
artifacts/README.md           Overview: document formats, statuses, confirmation points, hard rules, progress log
artifacts/agents/             Detailed spec for all 5 roles (incl. the dispatcher) + decomposition.md (checklist methodology)
tools/                        The console (see the section above): review the checklist, edit test cases, record and compare test results
scripts/                      journal.py (run log), check_compliance.py (hard-rule scanner), install_hooks.sh (installs the git hook)
configs/                      Rule config for the scanner + console settings — edit these instead of the scripts
hooks/                        The pre-commit hook itself (installed by scripts/install_hooks.sh)
page_map/                     Page maps (YAML describing the currently deployed page elements/selectors)
data/                         Test data
tests/                        Test code
CLAUDE.md                     Project conventions (declare your own directories/commands/login here)
rule.md                       Technical pitfalls to avoid, in three sections: generic engineering lessons / component-library quirks / demo-site-only facts (delete that last one when you plug in your own site)
```

Every task run is archived under `artifacts/<task_id>/` with every document produced along the
way (the checklist, test cases, step-by-step actions, records of test-code changes, review
conclusions, progress log), so you can always go back and inspect the input/output of each step.

---

## License

[MIT](./LICENSE)
