# Demo Swarm System Map

> For: Anyone needing a single-page overview of how all the pieces fit together.

This document is the canonical "system map" for the demo swarm. It shows how surfaces, flows, lifecycle, and governance interconnect.

---

## System Overview

```
┌──────────────────────────────────────────────────────────────────────────┐
│                           CLAUDE SURFACES                                 │
├─────────────────┬────────────────────┬───────────────────────────────────┤
│   Agent SDK     │       CLI          │         HTTP API                  │
│   (TS/Python)   │  (claude --json)   │    (api.anthropic.com)           │
│   Local dev     │   Shell/Debug      │      Server/CI                    │
└────────┬────────┴─────────┬──────────┴───────────────┬───────────────────┘
         │                  │                          │
         ▼                  ▼                          ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                          SWARM ORCHESTRATOR                               │
│  (make stepwise-* / slash commands / Flow Studio)                        │
└────────────────────────────────┬─────────────────────────────────────────┘
                                 │
                                 ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                              7 FLOWS                                      │
│  ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐          │
│  │Signal│→│ Plan │→│Build │→│Review│→│ Gate │→│Deploy│→│Wisdom│          │
│  │ (1)  │ │ (2)  │ │ (3)  │ │ (4)  │ │ (5)  │ │ (6)  │ │ (7)  │          │
│  └──────┘ └──────┘ └──────┘ └──────┘ └──────┘ └──────┘ └──────┘          │
└────────────────────────────────┬─────────────────────────────────────────┘
                                 │
                                 ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                          RUN ARTIFACTS                                    │
│  swarm/runs/<run-id>/{signal,plan,build,gate,deploy,wisdom}/             │
│  ├── receipts/           # Execution metadata                            │
│  ├── llm/                # Transcripts                                   │
│  └── *.md, *.json        # Flow artifacts                                │
└────────────────────────────────┬─────────────────────────────────────────┘
                                 │
         ┌───────────────────────┼───────────────────────┐
         ▼                       ▼                       ▼
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│   GOVERNANCE    │  │    LIFECYCLE    │  │   VISUALIZATION │
│   (selftest)    │  │    (runs GC)    │  │  (Flow Studio)  │
│   16 steps      │  │    retention    │  │   localhost:5000│
│   3 tiers       │  │    quarantine   │  │   REST API      │
└─────────────────┘  └─────────────────┘  └─────────────────┘
```

---

## Claude Surfaces

Three ways to interact with Claude from this repo:

| Surface | Auth | Use Case | API Key? |
|---------|------|----------|----------|
| **Agent SDK** (TS/Python) | Claude login (Max/Team/Enterprise) | Local dev, building agents | No |
| **CLI** (`claude --output-format`) | Claude login | Shell integration, debugging | No |
| **HTTP API** (`api.anthropic.com`) | API account | Server-side, CI, multi-tenant | Yes |

**Key insight**: The Agent SDK is "headless Claude Code"—it reuses your Claude subscription. Use HTTP APIs for server deployments.

See: [AGENT_SDK_INTEGRATION.md](./AGENT_SDK_INTEGRATION.md)

---

## The 7 Flows

| Flow | Key | Purpose | Core Artifacts |
|------|-----|---------|----------------|
| 1. Signal → Spec | `signal` | Problem definition, requirements | problem_statement.md, requirements.md |
| 2. Spec → Plan | `plan` | Architecture, contracts | adr.md, api_contracts.yaml |
| 3. Plan → Draft | `build` | Implementation via microloops | code, tests, build_receipt.json |
| 4. Draft → Review | `review` | Pre-gate review | review_receipt.json |
| 5. Review → Verify | `gate` | Pre-merge audit | merge_recommendation.md |
| 6. Artifact → Prod | `deploy` | Merge, verify, report | deployment_log.md |
| 7. Prod → Wisdom | `wisdom` | Learn, close feedback loops | learnings.md, wisdom_summary.json |

**Microloops**: Flows 1 and 3 use adversarial author ⇄ critic pairs.

See: `swarm/flows/flow-*.md`

---

## Run Lifecycle

```
Birth                    Life                      End
─────────────────────────────────────────────────────────────
create_run()  →  flow execution  →  wisdom  →  prune/quarantine
                 ├── signal/
                 ├── plan/
                 ├── build/
                 ├── gate/
                 ├── deploy/
                 └── wisdom/
```

**Retention**: 30-60 days depending on flow. Gate/Deploy/Wisdom kept longer.

**Cleanup Commands**:
- `make runs-prune` — Surgical (respects retention policy)
- `make runs-quarantine` — Move corrupt runs
- `make runs-clean` — Nuclear reset

See: [RUN_LIFECYCLE.md](./RUN_LIFECYCLE.md), [runs-retention.md](../swarm/runbooks/runs-retention.md)

---

## Governance: Selftest

16 selftest steps in 3 tiers:

| Tier | Steps | Behavior |
|------|-------|----------|
| **KERNEL** | 1 | Must pass; always blocks |
| **GOVERNANCE** | 13 | Should pass; warnings in degraded mode |
| **OPTIONAL** | 2 | Nice-to-have; informational |

**Key Commands**:
```bash
make kernel-smoke    # Fast (~400ms)
make selftest        # Full (all 16 steps)
make selftest-doctor # Diagnose issues
```

See: [SELFTEST_SYSTEM.md](./SELFTEST_SYSTEM.md)

---

## Visualization: Flow Studio

Interactive UI at http://localhost:5000

**Key Features**:
- SDLC bar showing flow progress
- Graph visualization of steps and agents
- Run comparison
- Selftest integration

**Start**:
```bash
make flow-studio
# Open http://localhost:5000/?run=demo-health-check&mode=operator
```

See: [FLOW_STUDIO.md](./FLOW_STUDIO.md)

---

## Wisdom: Cross-Run Analytics

Flow 6 produces structured summaries for trend analysis:

```bash
make wisdom-summary RUN_ID=<run>  # Single run summary
make wisdom-aggregate             # Cross-run JSON
make wisdom-report               # Cross-run markdown
```

See: [WISDOM_SCHEMA.md](./WISDOM_SCHEMA.md)

---

## Wisdom Loop

The wisdom lifecycle connects runs to learnings to cleanup:

```
Runs → Wisdom Summary → Wisdom Aggregate → Human Action → (optional) GC
```

**Commands:**
- `make wisdom-summary RUN_ID=<id>` — Generate wisdom for one run
- `make wisdom-aggregate` — Aggregate all runs (JSON)
- `make wisdom-report` — Aggregate all runs (Markdown)
- `make wisdom-cycle` — Full cycle: summarize, aggregate, preview cleanup
- `make runs-prune` — Apply retention and delete old runs

After aggregating wisdom and reviewing the report, you can prune raw runs with `make runs-prune`.

---

## Where to Start by Persona

| Persona | Start Here |
|---------|------------|
| New to swarm | [GETTING_STARTED.md](./GETTING_STARTED.md) |
| Daily operator | [CHEATSHEET.md](../CHEATSHEET.md) |
| Preparing demo | [PRE_DEMO_CHECKLIST.md](./PRE_DEMO_CHECKLIST.md) |
| Claude Max/Team user | [AGENT_SDK_INTEGRATION.md](./AGENT_SDK_INTEGRATION.md) |
| CI/production | [LONG_RUNNING_HARNESSES.md](./LONG_RUNNING_HARNESSES.md) |
| Understanding flows | [INDEX.md](./INDEX.md) operator spine |
| Managing runs | [RUN_LIFECYCLE.md](./RUN_LIFECYCLE.md) |

---

## Quick Reference: Key Files

| Category | Path | Purpose |
|----------|------|---------|
| **Flows** | `swarm/flows/flow-*.md` | Flow specifications |
| **Configs** | `swarm/config/flows/*.yaml` | Flow definitions (source of truth) |
| **Agents** | `swarm/config/agents/*.yaml` | Agent definitions |
| **Adapters** | `.claude/agents/*.md` | Platform-specific adapters |
| **Runs** | `swarm/runs/<run-id>/` | Active run artifacts |
| **Examples** | `swarm/examples/` | Curated demo snapshots |
| **Selftest** | `swarm/tools/selftest_config.py` | Step definitions |
| **Retention** | `swarm/config/runs_retention.yaml` | GC policy |

---

## Quick Reference: Key Commands

```bash
# Validation
make dev-check        # Full validation suite
make validate-swarm   # FR-001 through FR-005

# Selftest
make kernel-smoke     # Fast kernel check
make selftest         # Full 16 steps

# Flow Studio
make flow-studio      # Start UI

# Runs
make runs-list        # Show run stats
make runs-prune       # Apply retention policy

# Wisdom
make wisdom-report    # Cross-run analytics

# Stepwise Execution
make stepwise-sdlc-stub       # Zero-cost demo
make stepwise-sdlc-claude-sdk # Real execution
```

---

## See Also

- [README.md](../README.md) — Main entry point
- [CLAUDE.md](../CLAUDE.md) — Full reference for Claude Code
- [INDEX.md](./INDEX.md) — Documentation reading order
- [ARCHITECTURE.md](../ARCHITECTURE.md) — Structural overview
