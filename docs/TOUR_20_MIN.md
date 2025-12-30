# Flow Studio: 20-Minute Tour

> **You are here:** Quick tour for curious engineers. Next:
> [1-Hour Deep Dive →](./FLOW_STUDIO.md) | [Adoption TL;DR →](./ADOPTING_SWARM_VALIDATION.md)

> **Version note:** This tour assumes mainline (`v2.2.0+`) or Flow Studio milestone
> (`v0.4.1-flowstudio`). If UI elements differ from these screenshots, compare your
> branch to those tags: `git diff v0.4.1-flowstudio -- swarm/tools/flow_studio_ui/`

See the swarm SDLC in action. No reading required—just click and explore.

## Setup (2 min)

```bash
# One time only: install dependencies
uv sync --extra dev

# Download demo artifacts
make demo-run

# Start Flow Studio
make flow-studio
```

Flow Studio opens at
`http://localhost:5000/?run=demo-health-check&mode=operator`.

---

## The Interface (1 min)

You're looking at a 7-flow SDLC with 56 agents. Here's what you see:

```text
┌───────────────────────────────────────────────────────────────────┐
│  Flow Studio   [?]                                   [👤 operator] │
├──[Signal ✓ Plan ✓ Build ✓ Review ✓ Gate ✓ Deploy ✓ Wisdom ✓]─────┤
├─────┬───────────────────────────────────────────────────┬────────┤
│     │                                                   │        │
│  7  │         SDLC Flow Graph                          │Details │
│flows│      (nodes = steps, colors = agents)            │ panel  │
│ in  │                                                   │        │
│side │  Click nodes to see details                       │        │
│ bar │                                                   │        │
│     │                                                   │        │
└─────┴───────────────────────────────────────────────────┴────────┘
```

**Left sidebar**: 7 flows (click to switch)
**Center**: Step and agent graph for the current flow
**Top bar**: SDLC progress across all flows (all green = complete)
**Right panel**: Details for the selected node (3 tabs: Node, Run, Selftest)

---

## Explore One Flow (5 min)

Let's walk **Build** (Flow 3), where code and tests happen.

1. **Click "Build"** in the left sidebar (or press `3`)
   - You see 9 steps (colored nodes) and their agents (circles)

2. **Click any step node** (teal boxes labeled like "test-author")
   - Right panel shows:
     - **Node tab**: Step ID, flow, role description
     - **Run tab**: Artifact status (what files this step created)
     - **Selftest tab**: Governance checks that apply to this step

3. **Switch to Selftest tab**
   - See selftest summary (how many KERNEL/GOVERNANCE/OPTIONAL checks exist)
   - Click **"View Full Plan"** to see all 16 selftest steps (1 KERNEL, 13 GOVERNANCE, 2 OPTIONAL)
   - Click any step to see:
     - Why it matters (KERNEL failures block merges)
     - What it validates (linting, contracts, coverage, etc.)
     - Commands to run it: `uv run swarm/tools/selftest.py --step <step-id>`

4. **Click an agent node** (colored dots around the flow)
   - See agent name, category (shaping, spec, implementation, etc.)
   - See which model it uses (inherit, haiku, sonnet)
   - See all the flows where this agent appears

---

## Understand What Happened (5 min)

You just ran a complete SDLC. Here's what each flow did:

### Signal (Flow 1) ✓
**Problem shaping**: Turned raw input into requirements and BDD scenarios.
- Agents: signal-normalizer, problem-framer, requirements-author, requirements-critic
- Output: `problem_statement.md`, `requirements.md`, `bdd_scenarios.feature`, `risk_assessment.md`

### Plan (Flow 2) ✓
**Design decisions**: Turned requirements into architecture, contracts, and test plans.
- Agents: impact-analyzer, design-optioneer, adr-author, interface-designer, test-strategist, work-planner
- Output: `adr.md`, `api_contracts.yaml`, `observability_spec.md`, `test_plan.md`, `work_plan.md`

### Build (Flow 3) ✓
**Implementation + test loops**: Agents wrote code and tests, critics reviewed, mutator tested.
- Key pattern: **microloop** (test-author ↔ test-critic, code-implementer ↔ code-critic)
- Agents: context-loader, test-author, test-critic, code-implementer, code-critic, mutator, fixer, doc-writer, self-reviewer
- Output: Source code, tests, `build_receipt.json` (audit trail of all decisions)

### Gate (Flow 4) ✓
**Pre-merge audit**: Checked contracts, security, coverage, policy.
- Agents: receipt-checker, contract-enforcer, security-scanner, coverage-enforcer, merge-decider
- Output: `merge_decision.md` (approve / bounce / escalate)

### Deploy (Flow 5) ✓
**Verification**: Merged to main, deployed, ran smoke tests.
- Agents: deploy-monitor, smoke-verifier, deploy-decider
- Output: `deployment_log.md`, `verification_report.md`

### Wisdom (Flow 6) ✓
**Learning extraction**: Analyzed what went well, what failed, why. Created issues and updated docs.
- Agents: artifact-auditor, regression-analyzer, flow-historian, learning-synthesizer, feedback-applier
- Output: `artifact_audit.md`, `regression_report.md`, `learnings.md`, `feedback_actions.md`

---

## Try One More Thing: Compare Runs (3 min)

Open this URL:

```
http://localhost:5000/?run=demo-health-check&compare=health-check-risky-deploy
```

Now you see side-by-side flows:
- **health-check**: All green (everything worked)
- **health-check-risky-deploy**: Gate shows red (deployment was risky, merge blocked)

This is how you diagnose why a run failed: visually compare status across all flows.

---

## The Aha Moment (2 min)

You now understand:

1. **Flows are structured SDLC spec**: Not chat, not magic. Each flow has a defined role, inputs, outputs, agent roster.

2. **Steps are checkpoints**: Each step has agents assigned, artifacts produced, and governance checks attached.

3. **Agents are narrow interns**: They specialize (test-author writes tests, test-critic reviews them, they iterate until tests pass).

4. **Selftest is the governance gate**: 16 steps validate everything (linting → contracts → coverage → policy). Failures block merges tier-by-tier (KERNEL blocks all, GOVERNANCE is conditional, OPTIONAL is informational).

5. **Receipts are on disk**: All decisions, command outputs, timings are in JSON/Markdown under `swarm/runs/<run-id>/`, so you can audit everything.

---

## Next Steps

- **Deeper dive**: Read [docs/FLOW_STUDIO.md](./FLOW_STUDIO.md) (detailed walk, 1 hour)
- **Use in your repo**: Read [docs/ADOPTING_SWARM_VALIDATION.md](./ADOPTING_SWARM_VALIDATION.md)
- **Understand the philosophy**: Read [docs/WHY_DEMO_SWARM.md](./WHY_DEMO_SWARM.md)
- **Run it yourself**: Read [DEMO_RUN.md](../DEMO_RUN.md) for a narrative walkthrough
- **Use the API**: Read [docs/FLOW_STUDIO_API.md](./FLOW_STUDIO_API.md) to integrate Flow Studio data into dashboards

---

## Keyboard Shortcuts

Press `?` in Flow Studio to see all shortcuts:

- `1`–`6`: Jump to flows (Signal through Wisdom)
- `/`: Focus search
- `←` / `→`: Navigate between steps
- `Esc`: Close modals
- `?`: Show this help

---

## One Slide Summary

> Flow Studio visualizes an agentic SDLC where agents implement 7 flows (Signal → Plan → Build → Review → Gate → Deploy → Wisdom). Each flow has steps (roles), agents (specialists), and artifacts (proof). Selftest validates everything in tiers (KERNEL/GOVERNANCE/OPTIONAL). You review the receipts, not the process.

That's the whole idea in 30 seconds.
