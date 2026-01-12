---
title: Adopting Swarm Validation in Your Repository
description: Guide for teams who want to bring swarm patterns into their own
  SDLC
---

← [Back to README](../README.md) | [See all docs](./INDEX.md)

# Adopting Swarm Validation in Your Repository

> **Context:** This guide assumes you're using **Flow Studio** (or an equivalent
> backend) as the harness for your swarm.
>
> In this repo, Flow Studio + the DemoSwarm definitions in `.claude/` provide the
> full demo harness. For just the `.claude` pack to use with Claude Code in your
> own repo, see [`EffortlessMetrics/demo-swarm`](https://github.com/EffortlessMetrics/demo-swarm).

> **You are here:** Adoption guide for platform teams. Coming from:
> [20-Minute Tour ←](./TOUR_20_MIN.md) | [Technical Deep Dive ←](./FLOW_STUDIO.md)

This guide is for **platform/DevEx teams** who want to adopt the swarm
validator and Flow Studio patterns into an existing repository.

**You don't need to adopt the entire 7-flow swarm** to get value. This
document shows minimal, intermediate, and advanced adoption paths.

---

## TL;DR: 5-Command Adoption

Get selftest validation + Flow Studio running in your repo in 10 minutes:

```bash
# 1. Install UV and sync dependencies
uv sync

# 2. Copy the swarm toolkit
cp -r flow-studio/swarm/tools ./
cp -r flow-studio/swarm/validator ./
cp -r flow-studio/swarm/flowstudio ./
cp -r flow-studio/swarm/config ./

# 3. Create your AGENTS.md registry
# (See Minimal Path section below for format)

# 4. Validate locally
uv run swarm/tools/validate_swarm.py

# 5. Start the UI
make flow-studio
# Opens http://localhost:5000
```

**Next step**: Pick your adoption path below (Minimal, Intermediate, or
Advanced).

---

## Which Path?

| Goal | Read This |
|------|-----------|
| Just want selftest framework | [`ADOPTING_SELFTEST_CORE.md`](ADOPTING_SELFTEST_CORE.md) |
| Want full swarm SDLC | This doc + consider forking `flow-studio` |
| Hybrid (validation + some flows) | Start here, adopt incrementally |

> **Template repository**: Coming soon—this will be the easiest way to spin up a new repo with the same flows, selftest, and CI wiring.

---

## Table of Contents

1. [Minimal Path](#minimal-path-validator-only)
2. [Intermediate Path](#intermediate-path-validator--flow-studio)
3. [Advanced Path](#advanced-path-full-swarm-implementation)
4. [Decision Tree](#decision-tree-which-path-is-right-for-you)
5. [FAQ](#faq)

---

## Minimal Path: Validator Only

**Effort:** 30 minutes
**Value:** Catch agent/flow misalignments in CI before merging
**Use case:** Teams that already have SDLC patterns, just want alignment checks

### What you get

- CI gate that prevents invalid agent/flow definitions
- JSON reports for dashboards
- Stops: missing agent files, color mismatches, broken flow references, hardcoded paths

### Setup

1. **Copy the validator**:

   ```bash
   mkdir -p swarm/tools
   cp flow-studio/swarm/tools/validate_swarm.py ./swarm/tools/
   cp -r flow-studio/swarm/validator ./swarm/
   ```

2. **Create your agent registry** (`swarm/AGENTS.md`):

   ```markdown
   # Agent Registry

   | key | flows | role_family | color | source | description |
   |-----|-------|-------------|-------|--------|-------------|
   | my-agent | build | implementation | green | project/user | Does X |
   ```

3. **Create agent definition** (`.claude/agents/my-agent.md`):

   ```yaml
   ---
   name: my-agent
   description: Does X
   color: green
   model: inherit
   ---
   You are the **My Agent**.
   ...
   ```

4. **Add CI check** (`.github/workflows/validate.yml`):

   Blessed Minimal Snippet:

   ```yaml
   name: Validate Swarm
   on: [pull_request, push]
   jobs:
     validate:
       runs-on: ubuntu-latest
       steps:
         - uses: actions/checkout@v4
         - uses: astral-sh/setup-uv@v2
         - name: Swarm validation gate
           run: |
             ./swarm/tools/ci_validate_swarm.sh \
               --fail-on-fail \
               --enforce-fr FR-001,FR-002,FR-003,FR-004,FR-005
   ```

   This is intentionally narrow: enforces only **structural FRs** (agent
   bijection, colors, references, skills, RUN_BASE paths), not your full
   test suite. It blocks PRs that would silently break the swarm's alignment.

   Alternative (simpler, uses Python directly):

   ```yaml
   - name: Swarm validation
     run: uv run swarm/tools/validate_swarm.py --json
   ```

5. **Run locally before each commit**:

   ```bash
   uv run swarm/tools/validate_swarm.py
   ```

**That's it.** Your agents are now validated. Move to Intermediate if you want the UI.

---

## Intermediate Path: Validator + Flow Studio

**Effort:** 2–3 hours
**Value:** Visual teaching surface + alignment checks
**Use case:** Teams mentoring new engineers, or teams with complex multi-agent flows

### What you get on top of Minimal

- Interactive graph showing flows → steps → agents
- Run history and artifact tracking
- Quick verification of which agents are used where
- Operator vs. Author modes (different audiences)

### Setup (beyond Minimal)

1. **Copy Flow Studio**:

   ```bash
   # Copy FastAPI backend
   cp -r flow-studio/swarm/tools/flow_studio_fastapi.py ./swarm/tools/

   # Copy supporting modules
   cp -r flow-studio/swarm/flowstudio ./swarm/
   cp flow-studio/swarm/tools/run_inspector.py ./swarm/tools/
   cp flow-studio/swarm/meta/artifact_catalog.json ./swarm/meta/
   ```

2. **Create flow config** (`swarm/config/flows/my-flow.yaml`):

   ```yaml
   key: my-flow
   title: "My Flow"
   description: "Does something"
   steps:
     - id: step-1
       role: "Prepare"
       agents: [my-agent]
   ```

3. **Create flow spec** (`swarm/flows/flow-my-flow.md`):

   ```markdown
   # My Flow

   ... step table, mermaid diagram, RUN_BASE paths ...
   ```

4. **Create example run** (`swarm/examples/my-scenario/my-flow/...`):

   ```
   swarm/examples/my-scenario/
     my-flow/
       artifact1.md
       artifact2.md
   ```

5. **Start Flow Studio**:

   ```bash
   make flow-studio
   # → http://localhost:5000
   ```

**Use cases for the UI:**

- **Onboarding**: Point new engineers to `/?mode=author&flow=build` to learn roles
- **Design reviews**: `/?mode=operator&flow=gate&run=incident-123` to see where decisions happened
- **Retros**: Compare runs: `/?run=success-case&compare=failure-case`

### Flow Studio Backend

Flow Studio uses **FastAPI** as its backend, providing asynchronous operation, modern Python patterns, and built-in OpenAPI documentation:

```bash
make flow-studio
# → Starts FastAPI backend with auto-reload on http://localhost:5000
```

**Why FastAPI:**
- Async/await support for integrations
- OpenAPI/Swagger docs for API consumers (`/docs` endpoint)
- High-performance production deployment
- Modern Python type hints and validation

**API endpoints:** `/api/flows`, `/api/graph/{flow}`, `/api/runs`, `/platform/status`, `/api/selftest/plan`

### Selftest Integration in Flow Studio

Flow Studio includes built-in selftest visualization accessible via the governance badge:

**How to access:**
1. Start Flow Studio: `make flow-studio`
2. Click the **governance badge** in the top-right header (shows ⏳ Checking... initially)
3. Status changes to ✅ GREEN, ⚠️ YELLOW, or ❌ RED based on selftest results
4. Click badge to open **Governance Status** panel

**What you see:**

- **Kernel status**: HEALTHY or BROKEN (red=blocks all work)
- **Selftest tier breakdown**: Kernel (red), Governance (orange), Optional (gray)
- **Failed steps**: List of failing step IDs with tier color-coding
- **Resolution hints**: Colored cards with:
  - Root cause analysis
  - Suggested command (with copy button)
  - Documentation link
- **Selftest Plan Details**: Full step table with:
  - Step ID, tier, severity, category, dependencies
  - Status icons (✅ pass, ❌ fail, ⚠️ degraded)
  - Quick-copy commands for common selftest operations

**Workflow:**
1. Click governance badge → See high-level status
2. Scroll to **Resolution Hints** → Identify root cause
3. Click **Copy** button → Paste command in terminal
4. Fix issue → Run `make selftest` → Refresh Flow Studio
5. Badge updates automatically on next load

### Quick Workflows

**Diagnose and fix failing selftest:**
```bash
# 1. See what failed
make selftest
# → Note failed step IDs

# 2. Open Flow Studio
make flow-studio
# → Click governance badge → See resolution hints

# 3. Fix specific step (example: core-checks)
ruff check swarm/ && python -m compileall -q swarm/

# 4. Verify fix
make selftest-step STEP=core-checks

# 5. Refresh Flow Studio → Badge should be green
```

**Work in degraded mode while fixing governance issues:**
```bash
# 1. Run in degraded mode (only KERNEL failures block)
make selftest-degraded
# → Exit code 0 if KERNEL passes, even if GOVERNANCE fails

# 2. See what's degraded
make selftest-degradations
# → Shows logged governance failures

# 3. Fix issues incrementally
uv run swarm/tools/selftest.py --step agents-governance

# 4. Switch back to strict mode when ready
make selftest
```

**Use FastAPI for programmatic access:**
```bash
# 1. Start FastAPI backend
make flow-studio

# 2. Fetch selftest plan JSON
curl http://localhost:5000/api/selftest/plan | jq .

# 3. Check governance status
curl http://localhost:5000/platform/status | jq .governance

# 4. Integrate into dashboards or CI
```

### Example Adoption Workflows

#### Scenario 1: Team adopting swarm validation for the first time

**Day 1** — Minimal path:
```bash
# Add to CI
echo "uv run swarm/tools/validate_swarm.py" > .github/workflows/validate.yml

# Run locally
make validate-swarm
# → Fix any errors

# Optional: Add pre-commit
pre-commit install
```

**Week 2** — Add selftest:
```bash
# Run selftest to establish baseline
make selftest
# → Fix KERNEL failures (blocking)
# → Document GOVERNANCE failures as tech debt

# Add to CI (degraded mode initially)
echo "uv run swarm/tools/selftest.py --degraded" >> CI

# Use Flow Studio to track progress
make flow-studio
# → Click governance badge → See what needs fixing
```

**Month 1** — Strict mode:
```bash
# Fix all governance failures
make selftest
# → All green

# Switch CI to strict mode
echo "uv run swarm/tools/selftest.py" > CI
```

#### Scenario 2: Debugging a failing selftest in CI

**Problem:** CI fails with "selftest: agents-governance FAIL"

**Solution:**
1. Run locally: `make selftest-step STEP=agents-governance`
2. Open Flow Studio: `make flow-studio`
3. Click governance badge → See **Resolution Hints**
4. Hint shows: "Agent bijection, color, or frontmatter validation failed"
5. Click **Copy** → Run command: `uv run swarm/tools/validate_swarm.py --check-agents`
6. Fix errors → Verify: `make selftest-step STEP=agents-governance`
7. Commit and push

#### Scenario 3: Contributing to swarm while some tests are broken

**Problem:** You need to make agent changes but `policy-tests` is failing (unrelated to your change)

**Solution (degraded mode):**
```bash
# 1. Run in degraded mode
make selftest-degraded
# → Passes if KERNEL is healthy

# 2. Create override for policy-tests (temporary)
make override-create STEP=policy-tests REASON="Known issue, tracked in #123" APPROVER=your-name

# 3. Verify override is active
make override-list

# 4. Make your changes
$EDITOR swarm/config/agents/my-agent.yaml
make gen-adapters
make check-adapters

# 5. Run selftest (policy-tests skipped via override)
make selftest

# 6. Revoke override when policy-tests is fixed
make override-revoke STEP=policy-tests
```

### Troubleshooting

**Problem:** Flow Studio governance badge stuck on "Checking..."

**Solution:**
```bash
# 1. Check if selftest report exists
ls -la swarm/runs/*/build/selftest_report.json

# 2. Run selftest to generate report
make selftest

# 3. Restart Flow Studio
# (stop server with Ctrl+C, then run make flow-studio again)
```

**Problem:** Resolution hints not showing in Flow Studio

**Solution:**
- Resolution hints only appear when selftest has failures
- Run `make selftest` first to generate failure data
- Click governance badge to refresh status
- Check browser console for JavaScript errors

**Problem:** `/api/selftest/plan` returns 503

**Solution:**
```bash
# Check if selftest module is importable
uv run python -c "from swarm.tools.selftest import get_selftest_plan_json; print('OK')"

# If import fails, check dependencies
uv sync --extra dev
```

**Problem:** Flow Studio backend won't start

**Solution:**
```bash
# Check if FastAPI dependencies are installed
uv sync

# Check for port conflicts
lsof -i :5000

# Use different port if needed
uv run uvicorn swarm.tools.flow_studio_fastapi:app --port 5001
```

---

## Advanced Path: Full Swarm Implementation

**Effort:** 1–2 weeks (depends on team size)
**Value:** Full SDLC automation with receipts, governance gates, closed feedback loops
**Use case:** Large platform/infrastructure teams, or organizations building internal DevX platforms

### What you get on top of Intermediate

- All 7 flows: Signal → Plan → Build → Review → Gate → Deploy → Wisdom
- Microloops (test ⇄ critic, code ⇄ critic)
- Governance gates (receipt audits, policy checks, security scans)
- Artifact-driven feedback (learnings extracted and fed back to earlier flows)
- Multi-agent coordination

### Key decisions before you start

1. **Which orchestrator?** (Claude Code, GitHub Actions, custom agent framework)
2. **Which flows are mandatory?** (You might skip Wisdom if you don't need closed-loop learning)
3. **How many agents do you need?** (You don't need all 45; build incrementally)
4. **CI/CD integration level?** (Just validation, or full merge automation?)

### Getting started

See `ARCHITECTURE.md` and `swarm/positioning.md` for the full design, then:

1. Adapt agent templates from `.claude/agents/` to your flow semantics
2. Write flow specs in `swarm/flows/flow-*.md` with exact RUN_BASE paths and mermaid diagrams
3. Add skills (test-runner, auto-linter, policy-runner) as needed
4. Implement orchestrator in your system (Claude Code, or custom)
5. Wire CI gates (Flow 4 merge decisions, Flow 5 deployment, Flow 6 feedback)

Start with one flow (usually Flow 3: Build with test/code microloops), then add others once that's stable.

---

## Decision Tree: Which Path Is Right for You?

```
Start: "We want swarm patterns"
  │
  ├─→ "Just need alignment checks in CI"
  │    └─→ Minimal Path (validator only)
  │        Time: 30 min | Value: High
  │
  ├─→ "Want to teach engineers how agents coordinate"
  │    └─→ Intermediate Path (validator + Flow Studio)
  │        Time: 2–3 hours | Value: High
  │
  └─→ "Full automation: agents doing SDLC, humans reviewing receipts"
       └─→ Advanced Path (full swarm)
           Time: 1–2 weeks | Value: Very High
           Prerequisites: 3+ engineers, 2+ week project runway
```

---

## FAQ

### Q: Can I use just the validator without the full swarm?

**A:** Yes, and that's the most common adoption path. The validator is platform-agnostic; it works with any agent/flow system.

### Q: Can I use Flow Studio without Claude Code?

**A:** Yes. Flow Studio is a web UI that reads YAML configs and run artifacts. It works with any orchestrator (GitHub Actions, custom agents, etc.).

### Q: Do I need to adopt all 7 flows?

**A:** No. Most teams start with Flow 3 (Build) with test/code microloops, then add Gate (Flow 5) for CI. Flows 1–2 (Signal/Plan) and 6–7 (Deploy/Wisdom) are optional add-ons.

### Q: What if I want to customize agents for my domain?

**A:** Agent prompts are in `.claude/agents/*.md`; registry is in `swarm/AGENTS.md`. Edit both. The validator will catch any inconsistencies.

### Q: How do I know if my setup is correct?

**A:** Run:

```bash
uv run swarm/tools/validate_swarm.py
uv run swarm/tools/validate_swarm.py --json  # for CI/dashboards
```

Exit code `0` means all checks pass.

### Q: Can I exclude certain FRs (Functional Requirements) from validation?

**A:** Yes. The validator and CI gate support `--enforce-fr` to whitelist specific checks:

```bash
uv run swarm/tools/validate_swarm.py --enforce-fr FR-001,FR-002,FR-005
```

Use this during gradual rollout if you can't fix everything at once.

### Q: Where do I put flow artifacts?

**A:** Use the `RUN_BASE` placeholder:

```
RUN_BASE = swarm/runs/<run-id>/

swarm/runs/ticket-123/
  signal/
    problem_statement.md
  plan/
    adr.md
  build/
    build_receipt.json
  ...
```

This keeps artifacts organized and makes Flow Studio's timeline/artifact tracking work.

### Q: How do I add a second platform (e.g., GitLab)?

**A:** The spec layer (`swarm/flows/*.md`, `swarm/AGENTS.md`) is platform-agnostic. Only the adapters (`.claude/agents/*.md` or equivalent) are platform-specific.

1. Create a new adapter layer (e.g., `.gitlab/agents/<key>.yml`)
2. Wire the orchestrator for your platform (GitHub Actions runner → GitLab CI job)
3. Validator remains unchanged

See `swarm/infrastructure/` for extension guides.

---

## What's Next?

- **Just validation?** Start with the Minimal Path and run `make validate-swarm` on every PR.
- **Want to teach?** Follow the Intermediate Path and share demo links (`/?run=demo-health-check&mode=author`).
- **Full automation?** See [ARCHITECTURE.md](../ARCHITECTURE.md) and clone patterns from `.claude/agents/`.

Questions? Check [docs/INDEX.md](./INDEX.md) for the full learning map.
