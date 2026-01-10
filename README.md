# Flow Studio

> Stepwise orchestration for an industrialized SDLC.

This is not a chatbot. It's a system that executes structured flows, one step at a time, with durable state and forensic receipts.

**For:** Platform engineers, agent architects, and teams building agentic SDLC tooling at scale.

---

## The Economics Shift

**Code generation is faster than human review. The bottleneck is trust.**

Open-weight models now produce junior-or-better code, faster than you can read it, cheap enough to run repeatedly. Just like programmers stopped reading assembly, developers stop grinding on first-draft implementation—the job moves up the stack.

**Verification becomes the limiting reagent.** When generation is cheap and fast, the constraint shifts to: *Can I trust this output?* Flow Studio addresses this directly—every step produces forensic receipts, not just artifacts.

Flow Studio uses that leverage: run many small, scoped iterations (research, plan, build, test, harden), then publish a PR cockpit—hotspots, quality events, evidence, and explicit "not measured"—that's reviewable in one sitting.

The system does the repetitions. Humans do the decisions.

---

## What Flow Studio Is (and Isn't)

**Flow Studio IS:**
- A **flow orchestrator** that executes structured SDLC steps with durable state
- A **PR cockpit generator** that produces reviewable evidence packages
- A **trust-building system** that makes verification tractable through forensic receipts

**Flow Studio is NOT:**
- A code generator (it orchestrates agents that generate; it doesn't generate itself)
- An IDE plugin (it's infrastructure that runs alongside your existing tools)
- A CI replacement (it produces artifacts that CI consumes and validates)

---

## What Makes This Different

| Principle | What it means |
|-----------|---------------|
| **Forensics over narrative** | We ignore prose explanations. Trust the git diff, the test log, the receipt. If it's not on disk, it didn't happen. |
| **Verification is the product** | The output isn't code—it's code plus the evidence needed to trust it. |
| **Steps, not sessions** | Each step has one job in a fresh context. No "context drunkenness" from 100k-token sessions. |
| **PARTIAL is a save point** | Agents exit honestly when blocked. Resume later with zero data loss. |

---

## The Seven Flows

| Flow | What happens | What you get |
|------|--------------|--------------|
| **Signal** | Shape vague input into rigid acceptance criteria | requirements, BDD scenarios, risks |
| **Plan** | Design before writing logic | ADR, contracts, work plan |
| **Build** | Implement with adversarial loops | code, tests, build receipt |
| **Review** | Harvest feedback, apply fixes | drained worklist, ready PR |
| **Gate** | Forensic audit of the diff | MERGE or BOUNCE verdict |
| **Deploy** | Merge to mainline | CI verification, audit trail |
| **Wisdom** | Extract learnings | feedback actions, pattern library |

---

## Quick Start

```bash
uv sync --extra dev
make demo-run          # Populate example run
make flow-studio       # Start UI at http://localhost:5000
```

Open: `http://localhost:5000/?run=demo-health-check&mode=operator`

**What you'll see:**
- Left sidebar: 7 flows
- Center: Step graph for selected flow
- Top bar: SDLC progress (all green for the demo)
- Right panel: Agent details and artifacts

---

## Essential Commands

```bash
make dev-check         # Validate swarm health (run before commits)
make selftest          # Full 16-step validation
make kernel-smoke      # Fast kernel check (~300ms)
make stepwise-sdlc-stub # Run stepwise demo (zero-cost stub)
make help              # Show all commands
```

---

## Architecture

Three planes, cleanly separated:

| Plane | Component | What it does |
|-------|-----------|--------------|
| **Control** | Python kernel | Manages state, budgets, atomic disk commits |
| **Execution** | Claude Agent SDK | Autonomous agent work in a sandbox |
| **Projection** | DuckDB | Fast queryable index for the UI |

The kernel is deterministic. The agent is autonomous. The database is ephemeral (rebuildable from `events.jsonl`).

> **Flow Studio is implemented in Python (kernel/runtime) and TypeScript (UI).** It orchestrates work in repos of any language.

**Step lifecycle:**
1. **Work** — Agent executes with full autonomy
2. **Finalize** — JIT prompt forces structured `handoff_envelope.json`
3. **Route** — Separate call proposes next state transition

Kill the process at any point. Resume with zero data loss.

---

## Documentation

### Start Here

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
| Quality event types | [QUALITY_EVENTS.md](docs/QUALITY_EVENTS.md) |
| Adopt for your repo | [ADOPTION_PLAYBOOK.md](docs/ADOPTION_PLAYBOOK.md) |
| Example runs | [GOLDEN_RUNS.md](docs/GOLDEN_RUNS.md) |
| Full reference | [CLAUDE.md](CLAUDE.md) |
| All docs | [docs/INDEX.md](docs/INDEX.md) |

### Philosophy

| Topic | Document |
|-------|----------|
| Why this design | [WHY_DEMO_SWARM.md](docs/WHY_DEMO_SWARM.md) |
| Full positioning | [swarm/positioning.md](swarm/positioning.md) |
| AgOps manifesto | [AGOPS_MANIFESTO.md](docs/AGOPS_MANIFESTO.md) |

---

## Operational Invariants

These aren't suggestions—they're load-bearing walls:

- **Shadow fork isolation** — Work happens in a fork to prevent "moving target" hallucinations
- **Atomic commits** — State moves only after the handoff envelope is durable
- **DB-backed UI** — TypeScript queries DuckDB, not JSONL parsing—instant at any scale
- **Agent-driven routing** — Next-step decisions come from agents who understand context, not regex

---

## Ready to Adopt?

Before adopting, ensure you have:

- [ ] Run `make dev-check` and confirmed green
- [ ] Read [GETTING_STARTED.md](docs/GETTING_STARTED.md)
- [ ] Reviewed [GOLDEN_RUNS.md](docs/GOLDEN_RUNS.md) examples
- [ ] Understood [STEPWISE_BACKENDS.md](docs/STEPWISE_BACKENDS.md)

See [ADOPTION_PLAYBOOK.md](docs/ADOPTION_PLAYBOOK.md) for the complete checklist.

---

## Related

- [EffortlessMetrics/demo-swarm](https://github.com/EffortlessMetrics/demo-swarm) — Portable `.claude/` pack for your own repo

---

## Status

Early re-implementation of a proven pattern. Bundled examples work; outside those, you're exploring.

Something broken? [Open an issue](../../issues).

---

## License

Apache-2.0 or MIT
