# Repository Map

> For: Contributors understanding the physical directory layout.

> Structural overview of Flow Studio
> Generated: 2025-11-26 (post-alignment)

## Purpose

This map shows the **as-built** layout of the industrial agentic SDLC swarm repository. It distinguishes between:

- **Platform-neutral spec layer** (`swarm/`) — portable definitions of agents, flows, skills, and examples
- **Claude adapter layer** (`.claude/`) — Claude Code-specific implementation of those specs
- **Code under test** (`src/`, `tests/`, `features/`, `migrations/`, `fuzz/`) — standard project structure

---

## Top-Level Structure

```
/  (repo root)
├── .claude/               # Claude Code adapter layer (Claude-specific)
├── .github/               # GitHub workflows and CI config
├── features/              # BDD feature files (Gherkin scenarios)
├── fuzz/                  # Fuzz harnesses for property testing
├── migrations/            # SQL migrations
├── src/                   # Rust implementation (minimal demo)
├── swarm/                 # Platform-neutral spec layer
├── tests/                 # Rust tests
│
├── ALIGNMENT_PLAN.md      # Original alignment design doc
├── ALIGNMENT_SUMMARY.md   # Execution report from alignment
├── CLAUDE.md              # Guide for Claude Code instances
├── CONTRIBUTING.md        # Contribution guidelines
├── LICENSE                # License file
├── Makefile               # Common tasks (validate-swarm, etc.)
├── README.md              # Repository overview
├── REPO_CLEANUP_PLAN.md   # Cleanup strategy (historical)
└── REPO_MAP.md            # This file
```

---

## Spec Layer: `swarm/`

**Platform-neutral definitions.** Other orchestrators can reuse these specs if they implement the required RUN_BASE semantics, Explore-like search, git ops, and microloop mechanics.

```
swarm/
├── flows/                      # Flow specifications (7 flows)
│   ├── flow-signal.md          # Flow 1: Signal → Specs
│   ├── flow-plan.md            # Flow 2: Specs → Plan
│   ├── flow-build.md           # Flow 3: Plan → Draft (microloops)
│   ├── flow-review.md          # Flow 4: Draft → Reviewed
│   ├── flow-gate.md            # Flow 5: Reviewed → Verify
│   ├── flow-deploy.md          # Flow 6: Artifact → Prod
│   └── flow-wisdom.md          # Flow 7: Prod → Wisdom
│
├── spec/                       # Formal specifications
│   ├── contracts/              # Inter-flow contract definitions
│   │   └── build_review_handoff.md  # Build-to-Review handoff contract
│   └── schemas/                # JSON schemas for artifacts
│
├── tools/                      # Validation and introspection scripts
│   ├── validate_swarm.py       # Validates AGENTS.md ↔ .claude/agents/*.md
│   └── run_flow_dry.py         # Dry-run flow graph analysis
│
├── examples/                   # Curated demonstration snapshots
│   └── health-check/           # End-to-end example of all 7 flows
│       ├── code-snapshot/      # Copy of code/tests/features at snapshot time
│       ├── signal/             # Flow 1 artifacts (problem, requirements, BDD)
│       ├── plan/               # Flow 2 artifacts (ADR, contracts, test plan)
│       ├── build/              # Flow 3 artifacts (receipts, critiques, git status)
│       ├── review/             # Flow 4 artifacts (code review, feedback)
│       ├── gate/               # Flow 5 artifacts (audits, merge recommendation)
│       ├── deploy/             # Flow 6 artifacts (deployment verification)
│       ├── wisdom/             # Flow 7 artifacts (regression, flow history, learnings)
│       ├── reports/            # Generated flow-*-report.txt from run_flow_dry.py
│       ├── EXPECTED_ARTIFACTS.md
│       └── README.md           # Explains snapshot structure
│
├── AGENTS.md                   # Agent registry (56 agents: 3 infra + 53 domain)
├── positioning.md              # Philosophy and axioms (compute for attention)
└── skills.md                   # Skill documentation (test-runner, auto-linter, policy-runner)
```

### Key Files in `swarm/`

- **AGENTS.md**: Source of truth for all domain agents and built-in infra agents
- **flows/flow-*.md**: Mermaid diagrams + step tables defining each flow's graph and RUN_BASE paths
- **spec/contracts/**: Inter-flow handoff contracts (e.g., build_review_handoff.md)
- **positioning.md**: Doctrine — why receipts, why microloops, why heavy context
- **skills.md**: Describes the 4 global Skills (test-runner, auto-linter, policy-runner, heal_selftest)
- **examples/health-check/**: Complete snapshot of a run through all 7 flows

---

## Claude Adapter Layer: `.claude/`

**Claude Code-specific implementation.** Wires the `swarm/` specs into Claude's subagent system, slash commands, and Skills.

```
.claude/
├── agents/                     # Claude subagent definitions (45 files)
│   └── <domain-agent>.md       # 45 domain agents (YAML frontmatter + prompt)
│
├── commands/                   # Slash command orchestrators
│   ├── flow-1-signal.md        # /flow-1-signal orchestrator
│   ├── flow-2-plan.md          # /flow-2-plan orchestrator
│   ├── flow-3-build.md         # /flow-3-build orchestrator
│   ├── flow-4-review.md        # /flow-4-review orchestrator
│   ├── flow-5-gate.md          # /flow-5-gate orchestrator
│   ├── flow-6-deploy.md        # /flow-6-deploy orchestrator
│   └── flow-7-wisdom.md        # /flow-7-wisdom orchestrator
│
├── skills/                     # Claude Code Skill definitions
│   ├── test-runner/
│   │   └── SKILL.md            # Execute tests, write test_output.log + test_summary.md
│   ├── auto-linter/
│   │   └── SKILL.md            # Mechanical lint/format fixes
│   ├── policy-runner/
│   │   └── SKILL.md            # Policy-as-code validation (OPA/Conftest)
│   └── heal_selftest/
│       └── SKILL.md            # Diagnose and repair selftest failures
│
└── settings.json               # Claude Code project settings
```

### Notes on `.claude/`

- **Not in `swarm/`**: This is Claude-specific wiring, not part of the portable spec
- **Built-in agents** (`explore`, `plan-subagent`, `general-subagent`) are documented in `swarm/AGENTS.md` but have no files here (they're infra)
- **Skills** are invoked by agents via their `skills:` frontmatter; they're tools, not agents

---

## Code Under Test

Standard Rust project structure. **Code and tests live here**, not under `swarm/`.

```
src/
└── handlers/
    └── health.rs               # Minimal demo: health-check endpoint

tests/
└── health_check_tests.rs       # Rust integration tests

features/
└── health.feature              # BDD scenarios (Gherkin)

migrations/
└── 0001_add_health_endpoint.sql  # SQL migration

fuzz/
└── example_fuzz.rs             # Fuzz harness example
```

---

## RUN_BASE: Active Runs (gitignored)

For a given run identified by `<run-id>` (e.g., ticket ID, branch name):

```
swarm/runs/<run-id>/            # RUN_BASE (gitignored)
├── signal/                     # Flow 1 artifacts
├── plan/                       # Flow 2 artifacts
├── build/                      # Flow 3 artifacts
├── review/                     # Flow 4 artifacts
├── gate/                       # Flow 5 artifacts
├── deploy/                     # Flow 6 artifacts
└── wisdom/                     # Flow 7 artifacts
```

**Active runs** write artifacts under `RUN_BASE/<flow>/` and are excluded from git via `.gitignore`.

**Curated examples** live under `swarm/examples/<scenario>/` and are committed for teaching purposes.

---

## Spec vs. Adapter: Portability Story

### If you're using Claude Code

- **Entry point**: `.claude/commands/` — use `/flow-1-signal`, `/flow-2-plan`, etc.
- **Agents**: `.claude/agents/*.md` — Claude subagents with YAML frontmatter + prompts
- **Skills**: `.claude/skills/*/SKILL.md` — test-runner, auto-linter, policy-runner

### If you're building your own orchestrator

- **Spec**: `swarm/AGENTS.md`, `swarm/flows/`, `swarm/skills.md`, `swarm/examples/`
- **Contracts**: `swarm/spec/contracts/` (handoff requirements between flows)
- **Requirements**: Implement RUN_BASE layout, Explore-like search, microloop mechanics, git ops
- **Adapter**: Build your own `.claude/`-equivalent that wires the spec into your system

The demo swarm is **Claude-native**, but the spec layer is **portable** for orchestrators that support similar primitives.

---

## Documentation Hierarchy

For new users, read in this order:

1. **README.md** — High-level overview of the swarm
2. **docs/GETTING_STARTED.md** — Hands-on orientation (two lanes)
3. **docs/LEXICON.md** — Canonical vocabulary (prevents noun-overload)
4. **swarm/positioning.md** — Philosophy and axioms
5. **CLAUDE.md** — How to use Claude Code with this repo
6. **swarm/AGENTS.md** — Agent roster and taxonomy
7. **swarm/flows/flow-*.md** — Flow specifications and diagrams
8. **swarm/spec/contracts/** — Inter-flow handoff contracts
9. **swarm/examples/health-check/** — Concrete end-to-end snapshot

For maintainers:

- **docs/ROUTING_PROTOCOL.md** — V3 routing model and decisions
- **docs/AGOPS_MANIFESTO.md** — AgOps operational philosophy
- **docs/ROADMAP_3_0.md** — v3.0 roadmap and priorities
- **docs/RELEASE_CHECKLIST.md** — Release preparation checklist
- **ALIGNMENT_PLAN.md** — Original alignment design
- **ALIGNMENT_SUMMARY.md** — Execution report
- **REPO_CLEANUP_PLAN.md** — Cleanup strategy (historical)
- **REPO_MAP.md** — This file (structural overview)

---

## Validation

Before committing changes to `swarm/` or `.claude/`, always run:

```bash
make validate-swarm
# or
uv run swarm/tools/validate_swarm.py
```

This ensures:
- All agents in `swarm/AGENTS.md` have matching `.claude/agents/*.md` files (or are documented as built-ins)
- All flow nodes reference valid agents or built-in infra (explore, plan-subagent, general-subagent)
- YAML frontmatter is valid in all agent/skill definitions

---

## Artifact Conventions

### Active Runs (under `swarm/runs/<run-id>/`)

- **Flow 1 (Signal)**: `problem_statement.md`, `requirements_*.md`, `features/*.feature`, `early_risk_assessment.md`
- **Flow 2 (Plan)**: `adr_current.md`, `api_contracts.yaml`, `observability_spec.md`, `test_plan.md`, `implementation_plan.md`
- **Flow 3 (Build)**: `build_receipt.json`, `self_review.md`, `test_output.log`, `test_summary.md`, `*_critique.md`, `git_status.txt`
- **Flow 4 (Review)**: `code_review.md`, `review_feedback.md`, `review_verdict.md`
- **Flow 5 (Gate)**: `gate_risk_report.md`, `merge_recommendation.md`, `policy_verdict.md`, `*_status.md`
- **Flow 6 (Deploy)**: `deployment_log.md`, `verification_report.md`, `deployment_decision.md`
- **Flow 7 (Wisdom)**: `artifact_audit.md`, `regression_report.md`, `flow_history.json`, `learnings.md`, `feedback_actions.md`

### Code/Tests (standard locations)

- **Code**: `src/**/*.rs`
- **Tests**: `tests/**/*.rs`
- **BDD**: `features/**/*.feature`
- **Migrations**: `migrations/*.sql`
- **Fuzz**: `fuzz/*.rs`

**Never write flow artifacts to repo root.** Always use `RUN_BASE/<flow>/`.

---

## Key Patterns

1. **Microloops** (Flow 3): Adversarial iteration (test-author ⇄ test-critic, code-implementer ⇄ code-critic, mutator → fixer)
2. **Heavy Context** (Context agents): Load 20-50k tokens; use `explore` liberally; invest tokens up-front
3. **Git State Management** (Flow 3): `repo-operator` manages branch creation, staging, and commits
4. **Bounce-Backs** (Flow 5): Gate may bounce work to Build (logic issues) or Plan (design flaws)
5. **Document & Continue**: Agents log questions/assumptions in `clarification_questions.md`, never block

---

## Total Agent Count: 56

- **3 Built-in Infra**: explore, plan-subagent, general-subagent
- **53 Domain Agents**: Grouped into families (Signal/Shaping, Context/Research, Plan/Design, Build/Impl, Build/Verify, Gate/Verify, Deploy, Wisdom, Reporter)

See `swarm/AGENTS.md` for the complete registry.

---

## Changes from Original Layout

This map reflects the **post-alignment state** (2025-12-01). Key changes:

- **Root cleaned**: All demo artifacts moved to `swarm/examples/health-check/`
- **RUN_BASE enforced**: Active runs write to `swarm/runs/<run-id>/` (gitignored)
- **7 flows**: Signal, Plan, Build, Review, Gate, Deploy, Wisdom (was 6 flows before Review was added)
- **Agent count corrected**: 56 total (3 built-in + 53 domain)
- **Flows updated**: All 7 flows now document RUN_BASE paths, microloops, and pathing conventions
- **CLAUDE.md rewritten**: Aligned with actual architecture (RUN_BASE, microloops, heavy context, critics)

See `ALIGNMENT_SUMMARY.md` for full execution report.
