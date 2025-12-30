# Flow Studio Swarm

> For: Platform engineers, agent architects, and teams building industrialized agentic SDLC tooling.

Stepwise orchestration for an industrialized SDLC.

This is not a chatbot. It's a system that executes structured flows, one step at a time, with durable state and forensic receipts.

---

## The Core Trade

**Compute is cheap. Reviewer attention is scarce.**

We burn tokens on adversarial loops, harsh critics, and architectural re-evaluation to buy back senior engineer time. The output isn't code—it's code plus the evidence needed to trust it.

---

## What Makes This Different

### Forensics Over Narrative

We ignore an agent's prose explanation of its work. We trust:
- The **git diff**
- The **test execution log**
- The **durable receipt**

If it's not on disk with evidence, it didn't happen.

### PARTIAL is a Save Point

Hallucination is a response to success pressure. We reward honesty: if an agent is blocked, it exits with `PARTIAL` status and a save-state. Resume later with zero data loss.

### Single-Responsibility Steps

Each step has one job. Tightly scoped tasks in fresh context windows ensure maximum reasoning density. No "context drunkenness" from 100k-token sessions.

---

## Architecture

The system splits into three planes:

| Plane | Component | Responsibility |
|-------|-----------|----------------|
| **Control** | Python kernel | Manages `run_state.json` (the program counter), budgets, and atomic disk commits |
| **Execution** | Claude Agent SDK | Autonomous agent work with full tool access in a sandbox |
| **Projection** | DuckDB | Fast queryable index of telemetry for the UI |

The Python kernel is deterministic. The agent is autonomous. The database is ephemeral (rebuildable from `events.jsonl`).

### Step Lifecycle

Every step follows a three-phase protocol:

1. **Work**: The agent executes its task with full autonomy
2. **Finalize**: A JIT prompt forces the agent to author a structured `handoff_envelope.json` at peak recency
3. **Route**: A separate call analyzes the envelope and flow spec to propose the next state transition

Python commits to disk only after the envelope is durable. Kill the process at any point; resume with zero data loss.

---

## The Seven Flows

| Flow | Purpose | Key Outputs |
|------|---------|-------------|
| **1. Signal** | Shape vague input into rigid AC matrix | requirements, BDD scenarios, risks |
| **2. Plan** | Design before writing logic | ADR, contracts, work plan |
| **3. Build** | Implement AC-by-AC with adversarial loops | code, tests, build receipt |
| **4. Review** | Harvest feedback, apply fixes | drained worklist, ready PR |
| **5. Gate** | Forensic audit of the diff | MERGE or BOUNCE verdict |
| **6. Deploy** | Merge to mainline | CI verification, audit trail |
| **7. Wisdom** | Extract learnings | feedback actions, pattern library |

---

## Quick Start

```bash
uv sync --extra dev
make demo-run          # Populate example run
make flow-studio       # Start UI at http://localhost:5000
```

Open: `http://localhost:5000/?run=demo-health-check&mode=operator`

---

## Essential Commands

| Task | Command |
|------|---------|
| Validate swarm health | `make dev-check` |
| Fast kernel check | `make kernel-smoke` |
| Full selftest | `make selftest` |
| Run stepwise demo | `make stepwise-sdlc-stub` |
| List runs | `make runs-list` |
| Prune old runs | `make runs-prune` |
| Show all commands | `make help` |

---

## Documentation

| Topic | Document |
|-------|----------|
| Get oriented (10 min) | [GETTING_STARTED.md](docs/GETTING_STARTED.md) |
| 20-minute tour | [TOUR_20_MIN.md](docs/TOUR_20_MIN.md) |
| Flow Studio UI | [FLOW_STUDIO.md](docs/FLOW_STUDIO.md) |
| Stepwise execution | [STEPWISE_BACKENDS.md](docs/STEPWISE_BACKENDS.md) |
| Adopt for your repo | [ADOPTION_PLAYBOOK.md](docs/ADOPTION_PLAYBOOK.md) |
| Example runs | [GOLDEN_RUNS.md](docs/GOLDEN_RUNS.md) |
| Claude Code integration | [CLAUDE.md](CLAUDE.md) |
| All docs | [docs/INDEX.md](docs/INDEX.md) |

---

## Operational Invariants

- **Shadow fork isolation**: Work happens in a fork to prevent "moving target" hallucinations from upstream
- **Atomic commits**: `run_state.json` moves only after the handoff envelope is durable
- **DB-backed UI**: TypeScript queries DuckDB, not JSONL parsing—instant even in large repos
- **Agent-driven routing**: Next-step decisions come from agents who understand context, not regex on logs

---

## Ready to Adopt?

Before adopting this system, ensure you have:

- [ ] Read the [ADOPTION_PLAYBOOK.md](docs/ADOPTION_PLAYBOOK.md)
- [ ] Reviewed the [GOLDEN_RUNS.md](docs/GOLDEN_RUNS.md) examples
- [ ] Run `make dev-check` and confirmed a green build
- [ ] Understood the [STEPWISE_BACKENDS.md](docs/STEPWISE_BACKENDS.md) execution model

See the [ADOPTION_PLAYBOOK](docs/ADOPTION_PLAYBOOK.md) for the complete readiness checklist.

---

## Related

- [EffortlessMetrics/demo-swarm](https://github.com/EffortlessMetrics/demo-swarm) — Portable `.claude` pack for your own repo

---

## Status

Early re-implementation of a proven pattern. Bundled examples work; outside those, you're exploring. If something breaks, [open an issue](../../issues).

---

## License

Apache-2.0
