# Evaluation Checklist

> **Time**: ~1 hour | **Track**: Operator | **Goal**: Decide if Flow Studio fits your team

This checklist is for engineers evaluating Flow Studio for their team. Complete it in order—each step builds on the previous one.

---

## Prerequisites

Before starting, ensure you have:

- [ ] Git installed
- [ ] Python 3.10+ installed
- [ ] [uv](https://github.com/astral-sh/uv) installed (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
- [ ] ~1 hour of uninterrupted time

---

## Phase 1: Setup (5 minutes)

```bash
# Clone and install
git clone https://github.com/EffortlessMetrics/flow-studio.git
cd flow-studio
uv sync --extra dev
```

**Checkpoint**: No errors during install.

---

## Phase 2: Health Check (10 minutes)

```bash
# Validate the swarm is healthy
make validate-swarm
```

**Expected**: Exit code 0, all 5 FRs pass (FR-001 through FR-005).

```bash
# Run the full selftest suite
make selftest
```

**Expected**: 16 steps execute. KERNEL and GOVERNANCE tiers should pass. Note the summary at the end.

**Checkpoint**: Both commands succeed without errors.

---

## Phase 3: Visual Exploration (15 minutes)

```bash
# Start Flow Studio
make flow-studio
```

Open your browser to the URLs shown in the output:

1. **Operator view**: `http://localhost:5000/?run=demo-health-check&mode=operator`
2. **Selftest view**: `http://localhost:5000/?run=swarm-selftest-baseline&flow=build`

### What to Look For

- [ ] **Left sidebar**: 7 flows (Signal → Plan → Build → Review → Gate → Deploy → Wisdom)
- [ ] **Flow graph**: Nodes represent steps, circles represent agents
- [ ] **Details panel**: Click any node to see its configuration
- [ ] **Artifacts tab**: See what each flow produces
- [ ] **Selftest tab**: See the 16-step governance breakdown

**Checkpoint**: You can navigate the UI and understand the flow structure.

---

## Phase 4: Understanding the Model (15 minutes)

Read these in order:

1. **[docs/TOUR_20_MIN.md](TOUR_20_MIN.md)** — Visual walkthrough of Flow Studio
2. **[docs/DEFINITION_OF_DONE.md](DEFINITION_OF_DONE.md)** — Quality bar and merge criteria
3. **[docs/RELEASE_NOTES_2_3_2.md](RELEASE_NOTES_2_3_2.md)** — Current release highlights

### Key Concepts to Understand

- [ ] **Flows**: Structured SDLC stages (not chat)
- [ ] **Agents**: Narrow specialists (48 total, think "interns not wizards")
- [ ] **Receipts**: Every decision traced to disk
- [ ] **Selftest tiers**: KERNEL (core) → GOVERNANCE (policy) → OPTIONAL (extras)
- [ ] **Microloops**: Critics never fix; they write harsh critiques, implementers iterate

**Checkpoint**: You can explain the 7-flow model to a colleague.

---

## Phase 5: Run a Golden Example (10 minutes)

```bash
# Populate a complete demo run
make demo-run
```

This populates `swarm/runs/demo-health-check/` with artifacts from all 7 flows.

```bash
# View the run in Flow Studio
make flow-studio
# Open http://localhost:5000/?run=demo-health-check&mode=operator
```

### Explore the Artifacts

- [ ] **Signal flow**: `swarm/runs/demo-health-check/signal/` — requirements, BDD scenarios
- [ ] **Plan flow**: `swarm/runs/demo-health-check/plan/` — ADR, contracts, test plan
- [ ] **Build flow**: `swarm/runs/demo-health-check/build/` — code, tests, receipts
- [ ] **Gate flow**: `swarm/runs/demo-health-check/gate/` — audit report, merge decision
- [ ] **Deploy flow**: `swarm/runs/demo-health-check/deploy/` — merge status, smoke test
- [ ] **Wisdom flow**: `swarm/runs/demo-health-check/wisdom/` — learnings, feedback

**Checkpoint**: You understand what each flow produces.

---

## Phase 6: Decision Point (5 minutes)

### You're Done When You Can:

Before deciding, confirm you can check these boxes:

- [ ] **Explain** the 7-flow model to a colleague (Signal → Plan → Build → Review → Gate → Deploy → Wisdom)
- [ ] **Run** selftest locally and understand what KERNEL vs GOVERNANCE tiers mean
- [ ] **Navigate** Flow Studio: find a step, see its agent, view artifacts
- [ ] **Assess** whether this fits your team using the criteria below

If you can check all four, you've completed the evaluation. Move to "Next Steps" based on your decision.

---

### This is a good fit if:

- [ ] You have a repo where you control CI
- [ ] You want audit trails, not vibes
- [ ] You can tolerate a 5-10 minute CI step on PR
- [ ] You have someone who will own keeping KERNEL checks green
- [ ] You're willing to have build failures block merges
- [ ] You want to trade compute for senior engineer attention

### This is NOT a good fit if:

- [ ] You need magic autopilot (agents are narrow interns)
- [ ] You have a small team or simple project (this is overkill)
- [ ] You want a hosted SaaS solution
- [ ] You need turnkey compliance (this is a pattern library)

---

## Next Steps

### If You're Ready to Adopt

1. **Read**: [docs/ADOPTION_PLAYBOOK.md](ADOPTION_PLAYBOOK.md) — Full adoption guide
2. **Copy**: Start with selftest tooling (`swarm/tools/`)
3. **Wire**: Add CI gate using `.github/workflows/` as reference
4. **Customize**: Adapt flows to your stack

### If You Need More Time

1. **Explore**: Run `make help` for all available commands
2. **Deep dive**: Read [docs/INDEX.md](INDEX.md) for the full 75-minute tour
3. **Ask**: Open an [Adoption Question issue](../../../issues/new?template=adoption_question.md)

### If This Isn't Right for You

No hard feelings! This repo is intentionally opinionated. Consider:

- **Simpler needs?** Use Copilot or Cursor for code completion
- **Different stack?** The specs in `swarm/` are portable; implement on your platform
- **Just curious?** Star the repo and check back later

---

## Summary

| Phase | Duration | What You Learned |
|-------|----------|------------------|
| Setup | 5 min | Install works, no dependency issues |
| Health Check | 10 min | Selftest passes, swarm is healthy |
| Visual Exploration | 15 min | UI navigation, flow structure |
| Understanding | 15 min | Core concepts, quality bar |
| Golden Example | 10 min | What flows produce |
| Decision | 5 min | Fit assessment |

**Total time**: ~1 hour

---

## Feedback

Found something unclear? Open an issue or PR. This checklist should get you to a decision in under an hour—if it doesn't, that's a bug.
