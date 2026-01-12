# Flow Studio

> An agentic SDLC harness that transforms requirements into merged PRs with forensic evidence.

[![License](https://img.shields.io/badge/license-Apache--2.0%20%2F%20MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)

---

## Why This Exists

The job is moving up the stack. Again.

```
Punchcards → Assembly → High-level languages → Now
```

Each transition followed the same pattern: what was once skilled craft becomes mechanical, and humans move to higher-leverage work. Programmers stopped managing memory addresses. Then stopped thinking in registers. Now they stop grinding on first-draft implementation.

**The shift:** Models write nearly-working code at 1,000+ tokens/second. The bottleneck isn't generation—it's *trust*. Can a human review and trust the output in 30 minutes instead of spending a week doing it themselves?

**Flow Studio addresses that constraint.** It produces forensic evidence alongside code. You review the evidence, spot-check the hotspots, and ship—or bounce it back for another iteration.

The machine does the implementation. You do the architecture, the intent, the judgment.

Just like every transition before.

---

## What Flow Studio Does

Flow Studio runs **7 sequential flows** that transform a requirement into a merged PR:

| Flow | Transformation | Output |
|------|----------------|--------|
| **Signal** | Raw input → structured problem | Requirements, BDD scenarios, risk assessment |
| **Plan** | Requirements → architecture | ADR, contracts, work plan, test plan |
| **Build** | Plan → working code | Implementation + tests via adversarial loops |
| **Review** | Draft PR → Ready PR | Harvest feedback, apply fixes |
| **Gate** | Code → merge decision | Audit receipts, policy check, recommendation |
| **Deploy** | Approved → production | Merge, verify health, audit trail |
| **Wisdom** | Artifacts → learnings | Pattern detection, feedback loops |

Each flow produces **receipts** (proof of execution) and **evidence** (test results, coverage, lint output). Kill the process anytime—resume from the last checkpoint with zero data loss.

---

## The Economics

| Approach | Cost | Output |
|----------|------|--------|
| Developer implements feature | 5 days of salary | Code you hope works |
| Flow Studio runs overnight | ~$30 compute | Code + tests + receipts + evidence panel + hotspot list |

The receipts are the product. The code is a side effect.

---

## Installation

**Requirements:**
- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip
- GNU Make (Linux/macOS: included; Windows: use WSL2 or [MSYS2](https://www.msys2.org/))
- Node.js 20+ (optional, for UI development)

**Install:**

```bash
git clone https://github.com/EffortlessMetrics/flow-studio-swarm.git
cd flow-studio-swarm
uv sync --extra dev
```

**Verify:**

```bash
make dev-check    # Should pass all checks
```

---

## Quick Start

```bash
make demo-run       # Populate example artifacts
make flow-studio    # Start UI → http://localhost:5000
```

Open: **http://localhost:5000/?run=demo-health-check&mode=operator**

You'll see:
- **Left**: 7 flows (Signal → Plan → Build → Review → Gate → Deploy → Wisdom)
- **Center**: Step graph showing what ran and what it produced
- **Right**: Evidence, artifacts, and agent details

The demo shows a complete run—all seven flows executed, all receipts captured. Click around. This is what "done" looks like.

---

## What You Get

Every completed run produces:

| Artifact | Purpose |
|----------|---------|
| **Receipts** | Forensic proof of what happened—commands run, exit codes, timing |
| **Evidence panel** | Multi-metric dashboard (tests, coverage, lint, security) that resists gaming |
| **Hotspots** | The 3-8 files a reviewer should actually look at |
| **Bounded diff** | The change itself, with clear scope |
| **Explicit unknowns** | What wasn't measured, what's still risky |

A reviewer answers three questions in under 5 minutes:

1. **Does evidence exist and is it fresh?**
2. **Does the panel of metrics agree?**
3. **What would I spot-check?**

If yes, approve. If contradictions, investigate. The system did the grinding.

---

## The Mental Model

Don't anthropomorphize the AI as a "copilot." View it as a manufacturing plant.

| Component | Role | Behavior |
|-----------|------|----------|
| **Python Kernel** | Factory Foreman | Deterministic. Manages time, disk, budget. Never guesses. |
| **Agents** | Enthusiastic Interns | Brilliant, tireless. Will claim success to please you. Need boundaries. |
| **Disk** | Ledger | If it isn't written, it didn't happen. |
| **Receipts** | Audit Trail | The actual product. |

**The foreman's job:**
- Don't ask interns if they succeeded—measure the bolt
- Don't give them everything—curate what they need
- Don't trust their prose—trust their receipts

This is why the system doesn't rely on agent claims and runs forensic scanners. Exit codes don't lie. Git diffs don't hallucinate.

---

## Architecture

Three planes, cleanly separated:

| Plane | Component | What it does |
|-------|-----------|--------------|
| **Control** | Python kernel | State machine, budgets, atomic disk commits |
| **Execution** | Claude Agent SDK | Autonomous work in a sandbox |
| **Projection** | DuckDB | Queryable index for the UI |

The kernel is deterministic. The agent is stochastic. The database is ephemeral (rebuildable from the event journal).

**Step lifecycle:**
1. **Work** — Agent executes with full autonomy
2. **Finalize** — Structured handoff envelope extracted from hot context
3. **Route** — Next step determined from forensic evidence, not prose

Flow Studio orchestrates work in repos of any language. It's implemented in Python (kernel) and TypeScript (UI).

---

## Key Principles

| Principle | What it means |
|-----------|---------------|
| **Forensics over narrative** | Trust the git diff, the test log, the receipt. Not the agent's claim. |
| **Verification is the product** | Output is code + the evidence needed to trust it. |
| **Steps, not sessions** | Each step has one job in fresh context. No 100k-token confusion. |
| **Adversarial loops** | Critics find problems. Authors fix them. They never agree to be nice. |
| **Resumable by default** | Kill anytime. Resume from last checkpoint. Zero data loss. |

---

## Commands

```bash
make dev-check          # Validate swarm health (run before commits)
make selftest           # Full 16-step validation
make kernel-smoke       # Fast kernel check (~300ms)
make stepwise-sdlc-stub # Zero-cost demo run
make help               # All commands
```

---

## Documentation

### Get Started
| Time | Document | What you'll learn |
|------|----------|-------------------|
| 10 min | [GETTING_STARTED.md](docs/GETTING_STARTED.md) | Run the demo, see it work |
| 20 min | [TOUR_20_MIN.md](docs/TOUR_20_MIN.md) | Understand the full system |
| 5 min | [MARKET_SNAPSHOT.md](docs/MARKET_SNAPSHOT.md) | Why this approach, why now |

### Go Deeper
| Topic | Document |
|-------|----------|
| Flow Studio UI | [FLOW_STUDIO.md](docs/FLOW_STUDIO.md) |
| Stepwise execution | [STEPWISE_BACKENDS.md](docs/STEPWISE_BACKENDS.md) |
| Reviewing PRs | [REVIEWING_PRS.md](docs/REVIEWING_PRS.md) |
| Adopting for your repo | [ADOPTION_PLAYBOOK.md](docs/ADOPTION_PLAYBOOK.md) |
| Full reference | [CLAUDE.md](CLAUDE.md) |

### Philosophy
| Topic | Document |
|-------|----------|
| The full manifesto | [AGOPS_MANIFESTO.md](docs/AGOPS_MANIFESTO.md) |
| What this system is | [TRUST_COMPILER.md](docs/explanation/TRUST_COMPILER.md) |
| 15 lessons learned | [META_LEARNINGS.md](docs/explanation/META_LEARNINGS.md) |
| 12 emergent laws | [EMERGENT_PHYSICS.md](docs/explanation/EMERGENT_PHYSICS.md) |

---

## Contributing

Contributions are welcome. Before submitting:

1. Run `make dev-check` to validate the swarm
2. Run `make selftest` for full validation
3. Follow existing patterns in `swarm/` and `.claude/`

See [CLAUDE.md](CLAUDE.md) for the full reference on how the system works.

Something broken? [Open an issue](../../issues).

---

## Related

- [EffortlessMetrics/demo-swarm](https://github.com/EffortlessMetrics/demo-swarm) — Portable `.claude/` swarm pack for your own repo

---

## License

Apache-2.0 or MIT
