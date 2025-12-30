# Flow Studio Documentation Index

> For: Engineering managers / staff engineers evaluating or operating this repo.

This repo is the **Flow Studio demo harness**: a backend and UI for visualizing agentic SDLC flows.

It contains:

- Flow Studio UI and FastAPI backend
- A governed demo harness (flows, runs, selftest, validation)
- `.claude/` swarm definitions used as the specimen for this demo

For a portable `.claude` pack, see [`EffortlessMetrics/demo-swarm`](https://github.com/EffortlessMetrics/demo-swarm).

**Status:** early re-implementation of a proven pattern. See [README.md § Status](../README.md#status) and [RELEASE_NOTES_2_3_2.md § Stability Matrix](./RELEASE_NOTES_2_3_2.md#stability-matrix).

---

## Operator Spine (Read These First)

These 12 docs are the canonical operator surface. Everything else is reference.

| # | Doc | Purpose | Time |
|---|-----|---------|------|
| 1 | [README.md](../README.md) | Who this is for, what it is | 5 min |
| 2 | [docs/GETTING_STARTED.md](./GETTING_STARTED.md) | Hands-on path (two lanes) | 15 min |
| 3 | [CHEATSHEET.md](../CHEATSHEET.md) | Quick reference for daily operators | 3 min |
| 4 | [GLOSSARY.md](../GLOSSARY.md) | Terminology definitions | 5 min |
| 5 | [docs/LEXICON.md](./LEXICON.md) | Canonical vocabulary (prevents noun-overload) | 3 min |
| 6 | [docs/ROUTING_PROTOCOL.md](./ROUTING_PROTOCOL.md) | V3 routing model and decisions | 10 min |
| 7 | [docs/SELFTEST_SYSTEM.md](./SELFTEST_SYSTEM.md) | Selftest architecture and tiers | 10 min |
| 8 | [docs/FLOW_STUDIO.md](./FLOW_STUDIO.md) | Visual UI guide | 10 min |
| 9 | [REPO_MAP.md](../REPO_MAP.md) | Physical directory layout | 5 min |
| 10 | [docs/VALIDATION_RULES.md](./VALIDATION_RULES.md) | FR-001–FR-005 reference | 15 min |
| 11 | [docs/AGENT_OPS.md](./AGENT_OPS.md) | Agent management guide | 10 min |
| 12 | [ARCHITECTURE.md](../ARCHITECTURE.md) | v3.0 system architecture | 15 min |
| 13 | [docs/AGOPS_MANIFESTO.md](./AGOPS_MANIFESTO.md) | Operational philosophy (AgOps) | 20 min |

**Total spine time**: ~128 minutes for complete understanding.

If you're new, read these in order. Everything beyond is deepening, not new patterns.

---

## Operator Pack

Quick reference for day-to-day operations:

### Runbooks

- [`swarm/runbooks/10min-health-check.md`](../swarm/runbooks/10min-health-check.md) — First-time setup and sanity check
- [`swarm/runbooks/selftest-flowstudio-fastpath.md`](../swarm/runbooks/selftest-flowstudio-fastpath.md) — Fast validation path

### Flow Studio

- [FLOW_STUDIO.md](./FLOW_STUDIO.md) — Visual UI guide and API reference
- [FLOW_STUDIO_FIRST_EDIT.md](./FLOW_STUDIO_FIRST_EDIT.md) — Your first edit walkthrough (15 min)
- [FLOW_STUDIO_BUILD_YOUR_OWN.md](./FLOW_STUDIO_BUILD_YOUR_OWN.md) — Build your own swarm guide (20 min)
- [FLOW_STUDIO_API.md](./FLOW_STUDIO_API.md) — REST API documentation
- [FLOW_STUDIO_UX_HANDOVER.md](./FLOW_STUDIO_UX_HANDOVER.md) — Handover for new owners
- **Governed Surfaces** — SDK contract and UIID selectors (see FLOW_STUDIO.md)

### Architecture & Philosophy (35 min)

1. [ARCHITECTURE.md](../ARCHITECTURE.md) - v3.0 system architecture (cognitive hierarchy, components)
2. [AGOPS_MANIFESTO.md](./AGOPS_MANIFESTO.md) - AgOps operational philosophy (Factory Floor model)
3. [ROUTING_PROTOCOL.md](./ROUTING_PROTOCOL.md) - V3 routing model (CONTINUE, DETOUR, INJECT)
4. [ROADMAP_3_0.md](./ROADMAP_3_0.md) - v3.0 roadmap and next steps

### Contracts & Handoffs

- [`swarm/spec/contracts/`](../swarm/spec/contracts/) - Inter-flow contract definitions
- [`build_review_handoff.md`](../swarm/spec/contracts/build_review_handoff.md) - Build-to-Review handoff contract

### Runtime & Stepwise Execution (15-20 min)

1. [RUNTIME_BACKENDS.md](./RUNTIME_BACKENDS.md) - Backend architecture overview
2. [STEPWISE_BACKENDS.md](./STEPWISE_BACKENDS.md) - Per-step execution details
3. [AGENT_SDK_INTEGRATION.md](./AGENT_SDK_INTEGRATION.md) - Agent SDK integration guide
4. [TRANSCRIPT_SCHEMA.md](./TRANSCRIPT_SCHEMA.md) - Artifact format specification
5. [LONG_RUNNING_HARNESSES.md](./LONG_RUNNING_HARNESSES.md) - Pattern mapping (Anthropic harness patterns)
6. [PLAN_STEPWISE_VNEXT.md](./PLAN_STEPWISE_VNEXT.md) - Executable Graph IR plan (legacy)

### Wisdom & Analytics

- [WISDOM_SCHEMA.md](./WISDOM_SCHEMA.md) — Wisdom summary JSON schema
- [RUN_LIFECYCLE.md](./RUN_LIFECYCLE.md) — Run management and retention

### Quick Reference

- [SYSTEM_MAP.md](./SYSTEM_MAP.md) — Single-page system overview
- [PRE_DEMO_CHECKLIST.md](./PRE_DEMO_CHECKLIST.md) — Demo preparation checklist

### Validation & Selftest

- [VALIDATION_RULES.md](./VALIDATION_RULES.md) — FR-001 through FR-005
- [SELFTEST_SYSTEM.md](./SELFTEST_SYSTEM.md) — Tier system and governance checks
- [SELFTEST_DEVELOPER_WORKFLOW.md](./SELFTEST_DEVELOPER_WORKFLOW.md) — Local dev workflow

### Evaluation & Adoption

- [EVALUATION_CHECKLIST.md](./EVALUATION_CHECKLIST.md) — 1-hour checklist for team evaluation
- [ADOPTING_SWARM_VALIDATION.md](./ADOPTING_SWARM_VALIDATION.md) — 5-min TL;DR for adoption
- [ADOPTION_PLAYBOOK.md](./ADOPTION_PLAYBOOK.md) — Full adoption guide

### Contributing & Governance

- [SUPPORT.md](../SUPPORT.md) — Engagement expectations and how to participate
- [DEFINITION_OF_DONE.md](./DEFINITION_OF_DONE.md) — What "done" means for merging
- [MERGE_CHECKLIST.md](./MERGE_CHECKLIST.md) — Pre-merge verification checklist
- [RELEASE_CHECKLIST.md](./RELEASE_CHECKLIST.md) — Release preparation checklist
- [CI_TROUBLESHOOTING.md](./CI_TROUBLESHOOTING.md) — Fixing CI failures
- [CONTRIBUTING.md](../CONTRIBUTING.md) — How to contribute

---

## 0-10 min: Get oriented

**Read first**: [docs/GETTING_STARTED.md](./GETTING_STARTED.md)

This is the fastest way to understand the demo. Two paths:

- **Lane A: SDLC Demo** — See flows in action with Flow Studio (7 min)
- **Lane B: Governance Demo** — Understand validation and selftest (7 min)

After 10 minutes, you've seen it work. Continue below for deeper understanding.

---

## 10–25 min: See it work

```bash
uv sync --extra dev
make dev-check
make demo-run
make flow-studio  # → http://localhost:5000
```

You should now have:

- A healthy swarm (`make dev-check` green)
- A demo run under `swarm/runs/demo-health-check/`
- Flow Studio open with 7 flows in the sidebar

Read `DEMO_RUN.md` (2–3 minutes) to understand the health-check scenario.

---

## 25–45 min: Understand the flows

**Open Flow Studio** (`http://localhost:5000`) and keep it open while you read.

### Walk Signal (Flow 1)

1. Open Flow Studio with Signal pre-selected:

   ```text
   http://localhost:5000/?flow=signal&run=demo-health-check
   ```

2. Notice the step sequence: `parse` → `shape` → `requirements` → `bdd` →
   `assess` → `report`
3. Click a step node (teal) — the right panel shows:
   - Step ID and role
   - Where the spec lives: `swarm/flows/flow-signal.md`
   - Where demo artifacts live: `swarm/runs/demo-health-check/signal/`
4. Click an agent node (colored) — see its category, model, and file locations

Now open the spec file and compare:

```bash
cat swarm/flows/flow-signal.md
```

Match the "Steps" table to the graph. They should tell the same story.

### Walk Build (Flow 3)

1. Open Flow Studio with Build pre-selected (or use keyboard shortcut `3`):

   ```text
   http://localhost:5000/?flow=build&run=demo-health-check
   ```

2. Notice it's the heaviest flow — long chain from `branch` → `commit`
3. Look for the microloop clusters (test/critic, code/critic pairs)
4. Click step nodes to see how they map to agents

Open the spec and compare:

```bash
cat swarm/flows/flow-build.md
```

Look at:

- **Artifact Paths**: Where outputs go (`RUN_BASE/build/...`)
- **Orchestration Strategy**: How microloops work
- **Steps** table: Which agents run at each step

**Goal**: Understand that the graph is the spec, the spec is the graph.

---

## 45–60 min: Understand governance

The swarm has a layered validation system that catches misalignment early.

### Learn validation through a walkthrough

**New?** Start here: Read `docs/VALIDATION_WALKTHROUGH.md` for a narrative walkthrough of how validation works. You'll add a fake agent, make realistic mistakes, see the exact error messages, and learn why each check matters.

```bash
# While reading the walkthrough, follow along:
make validate-swarm
```

### Run validation

```bash
uv run swarm/tools/validate_swarm.py --debug
```

Watch what it checks:

- FR-001: Bijection (agents ↔ registry)
- FR-002: Frontmatter (required fields, color matches role)
- FR-003: Flow references (agents actually exist)
- FR-004: Skills (skill files exist)
- FR-005: RUN_BASE (placeholders, not hardcoded paths)

### Run selftest

```bash
make selftest --plan    # See the 16 steps
make selftest           # Run them
make selftest-doctor    # Diagnose issues if any
```

The selftest has 3 tiers:

| Tier | Steps | Meaning |
|------|-------|---------|
| KERNEL | 1 step | Python lint + compile — must pass |
| GOVERNANCE | 13 steps | Agents, skills, flows, BDD, policy, stepwise, wisdom — should pass |
| OPTIONAL | 2 steps | Coverage thresholds, extras — nice to have |

### Governance Surfaces (Three-Layer Model)

The swarm protects itself with **three complementary governance layers**. Know which one to use:

**1. Validator** (`validate_swarm.py`): Static checks on metadata

```bash
uv run swarm/tools/validate_swarm.py --json | jq .summary
```

**What it checks:** Agent ↔ registry alignment, frontmatter schema, color matching, flow references, RUN_BASE paths.

**When:** Before committing changes to `.claude/` or `swarm/` directories.

**Output:** `summary.status` is `PASS` or `FAIL`. When it fails, tells you exactly which agent/flow/field caused the problem.

**2. Selftest** (`selftest.py`): Dynamic repo health

```bash
uv run swarm/tools/selftest.py --plan    # Show plan
uv run swarm/tools/selftest.py           # Full check
uv run swarm/tools/selftest.py --degraded   # Work around GOVERNANCE failures
```

**What it checks:** Python tooling (ruff, compile), agent/flow/skill integrity, BDD structure, OPA policies, development experience contracts, graph connectivity.

**When:** Every build/CI, or before submitting work.

**Exit codes:**
- `0` = All checks passed (strict mode)
- `1` = KERNEL or GOVERNANCE failure (strict), or KERNEL failure (degraded)
- `2` = Configuration error

**3. Flow Studio** (Visual status): Real-time artifact verification

```bash
make flow-studio
# Open http://localhost:5000
# Click "Governance" strip in header (when implemented) to see status
```

**What it shows:** Flow shapes, agent allocation, step timing, FR status overlays, degradation alerts.

**When:** After a run completes, to visualize what passed/failed and why.

**Output:** Interactive graph + artifact browser. When selftest reports degradations, Flow Studio flags them on nodes.

#### How to Choose

> **When you want to know if things are broken:**
>
> 1. **Is it a typo/schema error?** → Run `validate_swarm.py` (3–5 seconds)
> 2. **Is the system healthy?** → Run `kernel-smoke.py` (0.3–0.5 seconds)
> 3. **What's the full story?** → Run `selftest.py` (10–30 seconds)
> 4. **Visualize what happened?** → Open Flow Studio and inspect the run

### Read the docs

- `docs/VALIDATION_WALKTHROUGH.md` → **Teaching walkthrough** (learn by example)
- `CLAUDE.md` → **Validation** section (detailed reference, error messages)
- `docs/SELFTEST_SYSTEM.md` → Tier descriptions, troubleshooting, AC traceability
- `docs/SELFTEST_DEVELOPER_WORKFLOW.md` → **Developer guide** (local testing, CI, debugging)
- `docs/SELFTEST_OWNERSHIP.md` → **Ownership** (maintainer contact, escalation, decision log)
- `docs/SELFTEST_OBSERVABILITY_SPEC.md` → **Observability** (metrics, logging contracts)
- `docs/SELFTEST_AC_MATRIX.md` → **AC-to-step mapping** (which AC is tested where)
- `docs/OPERATOR_CHECKLIST.md` → **Operator runbook** (health checks, troubleshooting, escalation)
- `docs/RECONCILIATION.md` → Spec-to-reality alignment (pytest + Gherkin)

**Goal**: Know what `make dev-check` actually validates.

---

## 60–75 min: Try hands-on tasks

See `DEMO_RUN.md` → **Hands-On Tasks** for three exercises:

1. **Change an agent model** — Edit config, regenerate, verify
2. **Break the validator** — Introduce a color mismatch, see the error, fix it
3. **Explore Flow Studio** — Match the graph to the spec

These are small, reversible, and teach the key patterns.

---

## After 75 minutes, you know

- The 7 flows and their shapes (Signal light, Build heavy, Review/Gate/Deploy/Wisdom lean)
- How agents fit into steps (config → adapter → invocation)
- How validation works (FR-001..005, selftest tiers)
- How to make changes safely (edit config, regenerate, validate)

Everything beyond this is deepening, not new patterns.

---

## Quick Reference

### Commands

| Command | What it does |
|---------|--------------|
| `make dev-check` | Validate + kernel smoke test |
| `make demo-run` | Populate demo artifacts |
| `make flow-studio` | Visual graph of flows |
| `make validate-swarm` | Full FR-001..005 validation |
| `make selftest` | Run all 16 selftest steps |
| `make gen-adapters` | Regenerate agent .md from config |
| `make gen-flows` | Regenerate flow docs from config |

### Flow Studio Deep Links

Flow Studio supports URL parameters for direct navigation:

| Parameter | Description | Example |
|-----------|-------------|---------|
| `mode` | `author` or `operator` | `?mode=operator` |
| `run` | Select a run | `?run=demo-health-check` |
| `flow` | Select a flow | `?flow=build` |
| `step` | Select a step (requires flow) | `?flow=build&step=implement` |
| `view` | `agents` or `artifacts` | `?view=artifacts` |
| `tour` | Start a guided tour | `?tour=walk-build` |
| `tab` | Open details tab | `?tab=run` |

**Example URLs**:

- Build flow in author mode: `http://localhost:5000/?flow=build&run=demo-health-check`
- Gate flow in operator mode: `http://localhost:5000/?mode=operator&flow=gate&run=demo-health-check`
- Start the governance tour: `http://localhost:5000/?tour=governance-path`
- View artifacts graph: `http://localhost:5000/?flow=build&view=artifacts&run=demo-health-check`

### Key files

| Path | Purpose |
|------|---------|
| `swarm/config/flows/*.yaml` | Flow definitions (source of truth) |
| `swarm/config/agents/*.yaml` | Agent definitions (source of truth) |
| `swarm/flows/flow-*.md` | Flow specs (generated + prose) |
| `.claude/agents/*.md` | Agent adapters (generated) |
| `swarm/AGENTS.md` | Agent registry |
| `swarm/runs/demo-health-check/` | Demo run artifacts |
| `docs/FLOW_STUDIO.md` | Flow Studio documentation |
| `docs/AGENT_OPS.md` | Agent management guide |

### Reading order (if you prefer linear)

1. `DEMO_RUN.md` — See it work
2. `docs/WHY_DEMO_SWARM.md` — Understand the ideas
3. `docs/VALIDATION_STORY.md` — Why validation matters (1-2 page story)
4. `docs/VALIDATION_WALKTHROUGH.md` — Learn validation through a realistic scenario
5. `docs/FLOW_STUDIO.md` — Flow Studio reference
6. `docs/SELFTEST_SYSTEM.md` — Governance tiers, AC traceability, Gherkin-to-pytest mapping
7. `docs/SELFTEST_DEVELOPER_WORKFLOW.md` — Local testing, CI integration, debugging guide
8. `docs/SELFTEST_OWNERSHIP.md` — Maintainer contact, escalation paths, decision log
9. `docs/SELFTEST_OBSERVABILITY_SPEC.md` — Metrics, logging, and observability contracts
10. `docs/SELFTEST_AC_MATRIX.md` — Complete AC-to-test traceability
11. `docs/OPERATOR_CHECKLIST.md` — Operator runbook & troubleshooting
12. `docs/AGENT_OPS.md` — Agent management guide
13. `CLAUDE.md` — Full reference
14. `ARCHITECTURE.md` — v3.0 system architecture (cognitive hierarchy, components)
15. `docs/AGOPS_MANIFESTO.md` — AgOps operational philosophy (the "why" behind the design)
16. `docs/ROADMAP_3_0.md` — v3.0 roadmap and immediate priorities
