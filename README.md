**English** | [中文](README.zh-CN.md)

# claude-web-test-harness

A multi-agent UI testing framework driven by [Claude Code](https://claude.com/claude-code). Drop it into your Web project and hand it a requirement doc (PRD): it breaks the requirement into a checklist, **starts a test ledger web page on your machine and sends you the link**, and you review it by clicking through in the browser. Then it generates the formal test cases, writes the automation, runs it, and writes the results back into the same ledger. **Wherever a decision is yours, it stops and waits — it never guesses on its own.**

> The demo site is [TesterHome](https://testerhome.com) (a QA community forum). The demo flow is entirely **read-only** (browsing the topic list, opening a topic, asserting rendered content) — no signup/login/posting is automated.

---

## What a complete run looks like (with a PRD)

```
 You: "Design test cases for <feature> from the PRD at <path>" (add mockups if you have them)
   │
   ▼
 ① the agent breaks the PRD into a checklist (7 tables; anything uncertain is flagged as-is)
   │
   ▼
 ② the agent starts the test ledger on your machine and sends you the link  ──►  http://localhost:8900
   │
   ▼
 ③ you review in the browser: only the cards that need YOUR decision; one click saves      ← GATE 0
   │  say "done reviewing" in the chat
   ▼
 ④ the agent writes your answers (and notes) back into the checklist, then generates
   │  formal test cases + step-by-step actions
   ▼
 ⑤ same ledger: read the cases, edit them in place, export to Excel for manual testers     ← GATE 1
   │  continue if you want automation ↓
   ▼
 ⑥ check against the real pages → write code & self-run → review; results flow back into the ledger by case ID
```

**You never have to type a command**: the agent starts the ledger when it needs your review
(`python3 tools/qa_console.py ensure 8900`) and gives you the link. Each review card has:

- **one plain-language question**, e.g. "Can a file of exactly 50 MB be uploaded?" — not the agent's internal shorthand
- **background** plus **the source text** (the PRD section, the changelog row, mockup thumbnails); when two sources
  disagree, they are shown **side by side**
- **concrete options** ("50 MB allowed, only larger files rejected" / "must be under 50 MB"), with the agent's working
  assumption marked "agent default" — click it if you agree
- "not sure, check after it's built" is always a safe choice; add a note if you need to — the agent follows it when writing back
- "What are these cards?" (top right) explains conflict / missing / inferred cards and what your answer changes downstream

Two safety nets at the top of the page: a banner when the console code on disk is newer than the running process
(restart it), and a yellow bar when the checklist doesn't follow the template, so you ask the agent to fix it instead
of guessing at shorthand.

No PRD, only a website? It still works — step ① is preceded by observing the real pages (see "Preparing inputs").

---

## What problem it solves

The real workflow behind UI testing breaks down into these steps:

**break the requirement into a checklist and confirm nothing is missed → turn the checklist into
formal test cases and step-by-step actions, confirm they're correct → (for automation) check them
against the real pages, generate test code and run it → have someone review the code**

This harness assigns these steps to a few roles that hand off work through documents (not direct
conversation), and pauses wherever you need to confirm — waiting for you in the local test ledger:

```
   you
   │ hand over the PRD (+ mockups)
   ▼
┌───────────────────────────┐   ┌───────────────────────────┐   ┌───────────────┐   ┌────────┐
│ draft checklist            │ → │ formal cases + steps       │ → │ check pages    │ → │ review │
│ (you review in ledger) G0  │   │ (you review in ledger) G1  │   │ code & run     │   │        │
└───────────────────────────┘   └───────────────────────────┘   └───────────────┘   └────────┘
        checklist                       cases + steps            page map + test code   verdict
```

**Why the pages come later**: when there is a requirement doc, looking at the pages first biases the cases toward
"what the system does now" — bugs in the implementation get written into the cases as if they were the spec. So cases
are derived from the requirement first, reviewed, and only then checked against the real pages, with any mismatch
handed to you. Observing the pages first is only needed when there is **no** requirement doc.

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
#    "Design and write a read-only test suite for the TesterHome homepage (topic list + topic detail)"
#    The demo has no requirement doc, so it observes the pages first, then drafts the checklist.
#    When it needs your review, it starts the test ledger on your machine and sends you the link
#    (http://localhost:8900); review in the browser, then reply "done reviewing"
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

## Preparing inputs: requirement docs, design mockups, or just a website

The harness picks its approach from what you have (tiers A / B / C — see [`artifacts/GLOSSARY.md`](artifacts/GLOSSARY.md), Chinese). Just hand over what you've got:

| You have | How to hand it over | Notes |
|---|---|---|
| **A requirement doc** (Markdown / md exported from an online doc tool / PDF / Word) | Give the path in chat: "the PRD is at `<path>`". The agent copies it into `artifacts/<task_id>/input/` | Markdown exported from online doc tools often inlines images as base64 (several MB). Run `python3 tools/prd_intake.py <task_id> <file>` first to split it into text + image files, or the text drowns in base64 |
| **Design mockups** | Export one PNG per screen / dialog (**2x**, so copy text is legible verbatim) into `artifacts/<task_id>/ui_design/` | Include error / empty / hover states if they were designed. Figma: select the frame → Export PNG 2x; if your agent tool has a Figma MCP connected, it can pull frames into that folder for you |
| **Only a website, no requirement doc** | Nothing to prepare — say "there's no requirement doc; explore `<page>` and design tests for `<feature>`" | It explores first and gathers evidence: field constraints, validation messages, which actions are available in each state. Then it decomposes from what it observed. Make sure the environment is reachable; add a login fixture (Step 2 above) if needed |
| **A version label** (optional) | Say "this is the v1.4 requirement" | Goes into `state.md` as `version:`; the console groups tasks by it |

A few conventions:

- `input/` and `ui_design/` are gitignored: **requirement docs and mockups stay local and never enter the repo**.
- With only a website, what gets recorded is how the product behaves **now**, not how it **should** behave. GATE 0 explicitly asks you which observed behaviors are actually bugs.
- Anything beyond read-only exploration (real submits, deletes) is not triggered during exploration; it is marked "not observed" for you to decide.
- Confirmed business conclusions are written back to `specs/` (the product knowledge base), so the next task on the same module reuses them.

## 🚀 Then just drive testing by describing what you want in plain language

This is the core workflow of the whole harness — **once it's plugged in, you never write a line
of test code by hand; you just describe what to test in natural language**:

```text
After the user logs in, search for a keyword in the product list, add it to the cart, and
verify the cart's item count and total price.
```

It breaks this requirement down into a checklist (what points this feature needs testing on, what rules
each field has, how states transition, what business constraints apply, exactly what the user does,
whether it could affect other features), then **starts the test ledger on your machine and sends you the
link** — you review in the browser. Once you're done, it generates the formal test cases and step-by-step
actions from the checklist and **has you review them in the same ledger**; only after both reviews does it
check the real pages and write the test code, self-running and self-repairing it.
**You describe "what to test", it handles "how to test it" and "whether it's fully covered" — you just
click or correct at two checkpoints.** (See "What a complete run looks like" at the top.)

> 💡 `artifacts/2026-06-23_testerhome_home_search/` in this repo holds one early trial run, but
> it predates the current two-phase methodology (no decomp.md/GATE 0) and part of what it
> describes never actually landed in the codebase — see the disclaimer at the top of each file
> in that folder. A real, up-to-date example run is on the to-do list (best produced against a
> project with real login/state, where the full GATE 0/1/2 pipeline actually gets exercised).

---

## The test ledger (review console) — where you review

Both checkpoints (GATE 0 checklist, GATE 1 test cases) happen on this local web page instead of raw markdown in a
terminal. It's pure standard library — nothing to install. **Normally you don't start it yourself**: when your review
is needed, the agent starts it with the command below and sends you the link. To open it manually:

```bash
python3 tools/qa_console.py ensure 8900   # one port, pick the version → the feature → the view
# ensure = make sure what's on 8900 runs the CURRENT code: reuse it if fresh, replace it if stale or pre-versioning.
# Always start the console this way after updating harness code — it is a long-running process and never notices file changes;
# a banner at the top of the page tells you when the code on disk is newer than what's running
```

What it gives you:

- **Every card makes sense on its own.** A plain-language question, background, the source text (conflicting sources
  side by side, mockup thumbnails), and concrete options with the agent's default marked. No internal codes like `R02`
  or `DBT-003` — the checklist follows a template, and `python3 tools/gate_review.py check <task_id>` verifies the format
  before it ever reaches you.
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
- **Test results fill themselves in, by case ID.** The ledger plugin is registered in the root
  `conftest.py`, so just run pytest and every result is matched back to the case it belongs to
  (it just needs the case ID in the test's docstring — no changes to your existing tests). Known
  bugs (`xfail`) are recorded as "known defect" rather than mixed in with new failures, and a
  known-bug case that unexpectedly passes is flagged separately as "possibly fixed — please verify". Automated runs and manual runs
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
- **Export test cases to Excel for someone else to execute.** Internal columns (`page_ref`,
  `derived_from`) are dropped, the source column (requirement section / mockup / observed) is kept,
  and `exec` is translated into plain words:

  ```bash
  python3 tools/cases_export.py <task_id>                 # → artifacts/<task_id>/cases_export.xlsx
  python3 tools/cases_export.py <task_id> --only-manual   # only the cases to run by hand
  python3 tools/cases_export.py <task_id> --csv           # CSV (opens in Excel without mojibake)
  ```

## Long regressions: resumable batches and fail-fast

Both plugins are registered in the root `conftest.py` and are **off by default**:

```bash
# Resumable batch: every result is written to disk as soon as it finishes. If the run is killed
# or the machine sleeps, rerun the exact same command and only the unfinished cases run.
python -m pytest tests/ --batch nightly
python -m pytest tests/ --batch nightly --batch-fresh     # wipe this batch's record and start over

# Fail-fast guard: stop the batch when the same locator fails N times, or M cases fail in a row,
# instead of grinding on for another half hour after the environment has hit a wall
python -m pytest tests/ --guard --guard-same=2 --guard-consecutive=4
```

- Resume rules: passed / known-defect / skipped cases are skipped next time; a case during which the machine slept is always rerun. Cases with ordering dependencies should be rerun together.
- The guard doesn't count known defects (`xfail`); the reason it stopped is written to `artifacts/_runs/guard_last.json`.
- The plugins are listed in `pytest_plugins` rather than `addopts` in `pytest.ini`, so `--override-ini="addopts="` while debugging doesn't silently disable them.

## Don't touch existing data: write guard, response capture, data footprint

Test environments are usually shared. These three make sure read-only tests really are read-only, assertions really
assert, and whatever you create can be cleaned up:

```python
from utils.write_guard import WriteGuard
guard = WriteGuard(page)          # read-only test: block and record every write request (login / token refresh pass by default)
...                               # open the dialog, look, click Cancel
guard.assert_clean()              # passes only if no write went out — even if a redesign turned "Cancel" into "Save"

from utils.response_capture import ResponseCapture, code_field_checker, assert_no_error_responses
cap = ResponseCapture([page], business_error=code_field_checker()).start()   # attach to EVERY page the test uses
...
cap.assert_saw_traffic()          # first prove it captured something — attached to the wrong page it sees nothing and always passes
assert_no_error_responses(cap)    # HTTP >= 400 and "HTTP 200 + business error code" both fail, with path and msg in the message

from utils.footprint import Footprint
fp = Footprint(require_prefix="AUTO_")   # only register objects you created (guards against registering existing data)
fp.created("AUTO_ITEM_1792000000", kind="item", where="...")
```

- `WriteGuard` doubles as a probe: after clicking submit, look at what was blocked — you learn whether client validation
  let it through and what would have been sent (`PostRecorder`), without writing anything
- Leftover cleanup: `python3 tools/cleanup_footprint.py` lists what the ledger says to clean, dry-run by default and **matched by
  full name only** (someone else's data with the same prefix is never listed). Real deletion needs your project's delete
  callback (`--deleter module:function --yes`); the harness ships no delete logic
- Rules and pitfalls: `rule.md` (Chinese), sections on read-only/no-trace work and assertion strength

## Release regression manifests and preflight

```bash
python -m pytest -m example                   # run one release's regression as listed in data/regression/example.yaml
python3 tools/preflight.py                    # before a batch, open each page in page_map: landmark present, not bounced to login, no "no permission"
python -m pytest tests/ --guard --preflight "python3 tools/preflight.py"   # don't start the batch if preflight fails
```

- Manifest format: `data/regression/<name>.yaml` maps "feature → file / test-function prefix"; matching tests get `-m <name>`
  at collection time, and an entry that matches nothing prints a hint (usually a renamed file)
- After a release is accepted: remove `xfail` from bugs that were fixed; turn accepted-as-is deviations into "guard the current
  behavior" assertions instead of leaving `xfail` around forever
- When running with branded Chrome (`--browser-channel=chrome`), `tools/pytest_chrome_orphans.py` cleans up orphaned Chrome helper
  processes that hold the driver open (macOS only) — the fix for "all tests finished but pytest never exits"

---

## Layout

```
.claude/agents/               Definitions for the 4 roles (page explorer / checklist+test-case design / test writing / review)
artifacts/README.md           Overview: document formats, statuses, confirmation points, hard rules, progress log
artifacts/agents/             Detailed spec for all 5 roles (incl. the dispatcher) + decomposition.md (checklist methodology)
tools/                        The test ledger (see above), case export, contract check; resume / guard / manifest / Chrome-orphan plugins; preflight, footprint cleanup
utils/                        Reusable helpers for test code: write_guard, response_capture, footprint, interaction (waits on async
                              evidence from the page map's dynamics fields), soft_check (soft assertions), auth_state (per-role login-state cache)
artifacts/templates/          The checklist (decomp.md) template — the single source of its format; the agent copies it first
data/regression/              Release regression manifests (-m <name> runs one release)
scripts/                      journal.py (run log), check_compliance.py (hard-rule scanner), install_hooks.sh (installs the git hook)
configs/                      Rule config for the scanner + console settings — edit these instead of the scripts
hooks/                        The pre-commit hook itself (installed by scripts/install_hooks.sh)
page_map/                     Page maps (YAML describing the currently deployed page elements/selectors)
data/                         Test data
tests/                        Test code
artifacts/GLOSSARY.md         Glossary of internal terms (GATE, tiers, confidence markers, exec…), Chinese
specs/                        Product knowledge base (confirmed business rules / state transitions / field constraints, one .md per module)
CLAUDE.md                     Project conventions (declare your own directories/commands/login here); also tells the main conversation it is the dispatcher
rule.md                       Technical pitfalls to avoid, in three sections: generic engineering lessons / component-library quirks / demo-site-only facts (delete that last one when you plug in your own site)
```

Every task run is archived under `artifacts/<task_id>/` with every document produced along the
way (the checklist, test cases, step-by-step actions, records of test-code changes, review
conclusions, progress log), so you can always go back and inspect the input/output of each step.

---

## License

[MIT](./LICENSE)
