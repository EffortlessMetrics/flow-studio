# Getting Started with Flow Studio

> For: Developers wanting to try the swarm in under 30 minutes.

> **Scope:** This guide is for running the **Flow Studio demo harness** in this repo.
> For a portable `.claude` pack to use with Claude Code in your own repo, see [`EffortlessMetrics/demo-swarm`](https://github.com/EffortlessMetrics/demo-swarm).

> **Version note:** This guide assumes mainline (`v2.3.0+`). If commands or UI differ,
> check `CHANGELOG.md` or the release notes in `docs/RELEASE_NOTES_2_3_0.md`.

> **Status:** early re-implementation of a proven pattern. If what you see disagrees with this guide, trust the code and open an issue.

Welcome! You're 10 minutes away from understanding how Flow Studio works. This guide has two paths depending on what you care about.

> **Fastest path?** Run `make demo-swarm` — it validates, creates a demo run, and starts Flow Studio in one command.

> **Already convinced?**
>
> - For **CI-only selftest**, start from [`templates/selftest-minimal/`](../templates/selftest-minimal/)
> - For **just flow visualization**, start from [`templates/flowstudio-only/`](../templates/flowstudio-only/)
> - For the **full swarm**, continue with this guide

**Choose your lane:**

- **Lane A: SDLC Demo** — See the seven flows in action with Flow Studio
- **Lane B: Governance Demo** — Understand how the selftest validates the swarm

Both paths take about 10 minutes. You can do both.

---

## Prerequisites

**Required (to run the harness):**
- **Python 3.11+** and [uv](https://docs.astral.sh/uv/)
- **GNU Make**
  - **Linux/macOS**: usually already installed
  - **Windows**: use **WSL2**, or install make via [MSYS2](https://www.msys2.org/) / Chocolatey (`choco install make`)
  - Note: Git Bash alone doesn't include make—you need MSYS2 or another source
  - Alternative: run the underlying commands directly (see Makefile for equivalents)

**Optional (for UI development / TypeScript checks):**
- **Node.js 20+** (npm is fine; pnpm optional)

---

## Lane A: SDLC Demo

**What you'll learn:** How the seven flows (Signal → Plan → Build → Review → Gate → Deploy → Wisdom) work together to automate the SDLC.

**Time:** 10 minutes

### Step 1: Setup (2 min)

```bash
uv sync --extra dev          # Install dependencies
make dev-check               # Verify swarm is healthy
```

If `make dev-check` is green, skip ahead. If it fails, run `make selftest-doctor` to diagnose.

### Step 2: Populate Demo Run (2 min)

```bash
make demo-run
```

This copies the example health-check scenario to `swarm/runs/demo-health-check/`, complete with all 7 flow artifacts.

### Step 3: Launch Flow Studio (1 min)

```bash
make demo-flow-studio
```

This starts Flow Studio and prints demo links. **Open this URL in your browser:**

```
http://localhost:5000/?run=demo-health-check&mode=operator
```

You should see:

- **Left sidebar**: 7 flows (Signal, Plan, Build, Review, Gate, Deploy, Wisdom)
- **Center graph**: Steps and stations for the selected flow
- **SDLC bar at top**: Progress across all flows (all green for demo-health-check)
- **Right panel**: Details for the selected step/agent

### Step 4: Explore (5 min)

1. Click each flow in the left sidebar to see its structure
2. Notice Build (Flow 3) is the heaviest — most steps, most stations
3. Click agent nodes (colored dots) to see their role and model
4. Click the **Artifacts** tab to see what each flow produced
5. Click the **Validation** tab to see governance status

**Key insight**: The graph *is* the spec. Each flow has steps, each step executes a station. The shape tells you the story.

### What You've Seen

- **Signal (Flow 1)**: Requirements loop — author ↔ critic
- **Plan (Flow 2)**: Design decisions — ADR, contracts, observability spec
- **Build (Flow 3)**: Implementation — test loop, code loop, mutation hardening
- **Gate (Flow 4)**: Pre-merge audit — receipts, contracts, security, policy
- **Deploy (Flow 5)**: Release — merge, verify, report
- **Wisdom (Flow 6)**: Learning — regressions, learnings, feedback

---

## Lane B: Governance Demo

**What you'll learn:** How the swarm validates itself (validator, selftest tiers, introspectable checks).

**Time:** 10 minutes

### Step 1: Setup (2 min)

```bash
uv sync --extra dev          # Install dependencies
```

### Step 2: See the Selftest Plan (2 min)

```bash
uv run swarm/tools/selftest.py --plan
```

This shows all 16 selftest steps without running them:

- **KERNEL tier** (1 step): Python checks — must pass
- **GOVERNANCE tier** (13 steps): Swarm alignment — should pass
- **OPTIONAL tier** (2 steps): Advanced checks — nice to have

**Key insight**: Selftest is decomposable. You can run individual steps or whole tiers.

### Step 3: Run the Full Selftest (3 min)

```bash
make selftest
```

Watch it run through all 16 steps. Notice:

- Each step is atomic and fast (< 0.2s each)
- Steps are independent (no cascading failures)
- Exit code is 0 (all pass) or 1 (KERNEL failure)

### Step 4: Run the Validator Separately (2 min)

```bash
uv run swarm/tools/validate_swarm.py
```

This validates just the **metadata** (FR-001..005):

- **FR-001**: Agent ↔ registry bijection
- **FR-002**: Frontmatter (required fields, color matching)
- **FR-003**: Flow references (agents exist)
- **FR-004**: Skills (skill files exist)
- **FR-005**: RUN_BASE paths (no hardcoded paths)

### Step 5: View Validation in Flow Studio (3 min)

```bash
make flow-studio
```

Open your browser to:

```
http://localhost:5000/?tab=validation&mode=governance
```

You'll see:

- **Validation status** for each FR (FR-001..005)
- **Agent issues** if any (color mismatches, missing files, etc.)
- **Flow issues** if any (invalid references, hardcoded paths, etc.)

Click on an issue to see the full error message and fix suggestion.

### What You've Learned

- **Validator** (5 seconds): Checks metadata alignment (FR-001..005)
- **Selftest** (2–5 seconds): Checks repo health and governance (16 steps)
- **Tiers**: KERNEL must pass; GOVERNANCE should pass; OPTIONAL is informational
- **Introspectable**: `--plan` mode shows structure without running it
- **Decomposable**: Run individual steps or whole tiers; work around failures with `--degraded`

**Next**: Read `docs/SELFTEST_SYSTEM.md` for deep details, or `docs/FLOW_STUDIO.md` for the UI reference.

---

## Combining Both Lanes

If you have 20 minutes, do both:

1. Lane A (SDLC Demo) → understand flows
2. Lane B (Governance Demo) → understand validation

Then open Flow Studio with both tabs:

```bash
make flow-studio
# Then open: http://localhost:5000/?mode=operator
```

Click between the **Artifacts** tab (shows what the flows produced) and the **Validation** tab (shows what the swarm validated). You'll see how specs (flows) and governance (validation) work together.

---

## Troubleshooting

**`uv sync` fails**: Make sure you have uv installed:

```bash
pip install uv
```

**`make dev-check` fails**: Run `make selftest-doctor` for diagnosis:

```bash
make selftest-doctor
```

**Flow Studio won't start**: Check if port 5000 is in use:

```bash
# Linux/macOS
lsof -i :5000

# Windows
netstat -ano | findstr :5000
```

If something is running, use a different port:

```bash
uv run uvicorn swarm.tools.flow_studio_fastapi:app --host 127.0.0.1 --port 5001
```

**Browser can't reach localhost:5000**: Check the uvicorn startup message. It should say:

```
Uvicorn running on http://127.0.0.1:5000
```

If it says a different address, use that instead.

---

## Next Steps

**After 10 minutes, you've seen it work.** Pick what to learn next:

- **Understand the flows deeply**: Read `DEMO_RUN.md` (narrative walkthrough)
- **Learn validation**: Read `docs/VALIDATION_WALKTHROUGH.md` (realistic scenario)
- **Explore governance**: Read `docs/SELFTEST_SYSTEM.md` (16-step breakdown)
- **Full reference**: Read `CLAUDE.md` (complete guide for Claude Code)
- **Learn the vocabulary**: Read `docs/LEXICON.md` (canonical terms like station, step, navigator)
- **Understand the ideas**: Read `docs/WHY_DEMO_SWARM.md` (three core ideas)
- **Use it**: See `docs/INDEX.md` for reading order and key patterns

---

## Key Files Referenced

| Path | Purpose |
|------|---------|
| `swarm/runs/demo-health-check/` | Demo run artifacts (all 7 flows) |
| `swarm/flows/flow-*.md` | Flow specs (what should happen) |
| `.claude/agents/*.md` | Agent definitions (who does it) |
| `docs/FLOW_STUDIO.md` | Flow Studio reference |
| `docs/SELFTEST_SYSTEM.md` | Selftest design and tiers |
| `docs/INDEX.md` | Full documentation index |
| `docs/WHY_DEMO_SWARM.md` | Philosophy and core ideas |
