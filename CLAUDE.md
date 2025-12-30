# CLAUDE.md

This document is the top-level map for **Flow Studio**—the demo harness for visualizing agentic SDLC flows.

> The `.claude/` directory defines the swarm used by this demo harness.
> For a portable `.claude` pack intended to be copied into *your* repo, use [`EffortlessMetrics/demo-swarm`](https://github.com/EffortlessMetrics/demo-swarm).

This is not a complete manual; it points you to the right artifacts.

---

## If You're a Human

Start here:

1. **Fast orientation** – [docs/GETTING_STARTED.md](./docs/GETTING_STARTED.md)
2. **What this repo is** – [docs/INDEX.md](./docs/INDEX.md) (spine + reading order)
3. **How the flows work** – `swarm/flows/` + [docs/FLOW_STUDIO.md](./docs/FLOW_STUDIO.md)
4. **How agents are managed** – [docs/AGENT_OPS.md](./docs/AGENT_OPS.md)
5. **How validation works** – [docs/VALIDATION_RULES.md](./docs/VALIDATION_RULES.md) and [swarm/SELFTEST_SYSTEM.md](./swarm/SELFTEST_SYSTEM.md)
6. **How to run things** – `swarm/runbooks/` (e.g., `selftest-flowstudio-fastpath`)
7. **The v3.0 architecture** – [ARCHITECTURE.md](./ARCHITECTURE.md) (cognitive hierarchy, components)
8. **The operational philosophy** – [docs/AGOPS_MANIFESTO.md](./docs/AGOPS_MANIFESTO.md) (AgOps paradigm)

## If You're an Agent / Automation

Treat this repo as four layers:

| Layer          | Path                            | Purpose                      |
|----------------|---------------------------------|------------------------------|
| Specs          | `swarm/flows/`                  | What should happen           |
| Runbooks       | `swarm/runbooks/`               | How to do it safely          |
| UI surface     | `swarm/tools/flow_studio_ui/`   | Visual + semantic contract   |
| Adapter config | `.claude/`                      | Provider-specific wiring     |
| Run artifacts  | `swarm/runs/<run-id>/`          | Ephemeral outputs (RUN_BASE) |

**When driving Flow Studio:**

- Wait for `html[data-ui-ready="ready"]`
- Use the SDK:
  - `window.__flowStudio.getState()`
  - `window.__flowStudio.setActiveFlow("build")`
  - `window.__flowStudio.selectStep("build", "1")`
- Use `data-uiid` selectors, not arbitrary CSS:
  - `[data-uiid="flow_studio.header.search.input"]`
  - `[data-uiid="flow_studio.sidebar.flow_list"]`
  - `[data-uiid^="flow_studio.canvas.outline.step:"]`

---

## Quick Start

```bash
make dev-check      # Validate the swarm is healthy
make demo-run       # Populate a complete example run
make flow-studio    # Visualize flows as a node graph (http://localhost:5000)
```

Then read [DEMO_RUN.md](./DEMO_RUN.md) for a worked example, and [docs/WHY_DEMO_SWARM.md](./docs/WHY_DEMO_SWARM.md) for the philosophy.

---

## Repository Overview

This repo implements an agentic SDLC with **seven flows** covering the full lifecycle of a change:

1. **Signal -> Specs** (Flow 1): Raw input -> problem statement, requirements, BDD, early risk
2. **Specs -> Plan** (Flow 2): Requirements -> ADR, contracts, observability, test/work plans
3. **Plan -> Draft** (Flow 3): Implement via adversarial microloops -> code, tests, receipts
4. **Draft -> Ready** (Flow 4): Harvest PR feedback, cluster into work items, apply fixes, flip Draft to Ready
5. **Code -> Gate** (Flow 5): Pre-merge gate -> audit receipts, check contracts/policy, recommend merge/bounce
6. **Artifact -> Prod** (Flow 6): Move approved artifact to deployed -> verify health, create audit trail
7. **Prod -> Wisdom** (Flow 7): Analyze artifacts, detect regressions, extract learnings, close feedback loops

**Core trade**: Spend compute to save senior engineer attention. Optimize for receipts and auditability, not speed.

**Out-of-the-Box**: GitHub integration is woven throughout. Flows 1-2 use GitHub for issue research and context. Flow 3 creates Draft PRs to wake bots. Flow 4 harvests PR feedback. Flows 5-7 handle gating, deployment, and learning. No external services beyond GitHub required.

See `swarm/positioning.md` for the full approach and `ARCHITECTURE.md` for a structural overview.

---

## Technology Stack

- **Python**: UV for validation tooling (`swarm/tools/validate_swarm.py`, `swarm/validator/`)
- **Git**: Managed by `repo-operator` agent in Flows 3-5
- **Runtime Backends**: Pluggable LLM execution via `swarm/runtime/`:
  - `claude-harness`: Make harness for Claude Code (default)
  - `gemini-cli`: Single-call Gemini CLI execution
  - `gemini-step-orchestrator`: Stepwise Gemini execution (one CLI call per step)
  - `claude-step-orchestrator`: Stepwise Claude Agent SDK execution

---

## Understanding Claude Surfaces

This repo uses three Anthropic surfaces. Understanding which to use saves confusion:

| Surface | Auth/Plan | Use Case | API Key? |
|---------|-----------|----------|----------|
| **Agent SDK** (TS/Python) | Claude login (Max/Team/Enterprise) | Local dev, building agents | No |
| **CLI** (`claude --output-format`) | Claude login | Shell integration, debugging | No |
| **HTTP API** (`api.anthropic.com`) | API account | Server-side, CI, multi-tenant | Yes |

> **Key insight**: The Agent SDK is "headless Claude Code"—it reuses your existing Claude
> subscription when you're logged into Claude Code. No separate API billing account needed.
> Use HTTP APIs when you need explicit keys for server deployments.

**For this repo:**
- **Agent SDK** is the primary programmable surface for local development
- **CLI mode** is for debugging and bridging to non-Claude providers (Gemini CLI, etc.)
- **HTTP API** is for CI, batch runs, and production harnesses

See [docs/STEPWISE_BACKENDS.md](./docs/STEPWISE_BACKENDS.md) for detailed configuration.

---

## Essential Commands

### Validation

Always run before committing changes to `swarm/` or `.claude/`:

```bash
make validate-swarm                             # Full validation
uv run swarm/tools/validate_swarm.py --strict   # Enforce swarm constraints
```

See [docs/VALIDATION_RULES.md](./docs/VALIDATION_RULES.md) for detailed validation rules (FR-001 through FR-005).

### Selftest

```bash
make selftest        # Full suite (strict mode, all 16 steps)
make kernel-smoke    # Fast kernel check (1 KERNEL step, ~300-400ms)
make selftest-doctor # Diagnose harness vs service issues
```

See [swarm/SELFTEST_SYSTEM.md](./swarm/SELFTEST_SYSTEM.md) for complete selftest documentation.

### Agent Operations

```bash
make gen-adapters    # Regenerate agent adapters from config
make check-adapters  # Verify adapters match config
make agents-models   # Show model distribution
make agents-help     # Show agent workflow reminder
```

See [docs/AGENT_OPS.md](./docs/AGENT_OPS.md) for detailed agent management guide.

### Flow Studio

```bash
make flow-studio     # Start visualization UI at http://localhost:5000
make ts-check        # Type-check TypeScript
make ts-build        # Compile TypeScript
make gen-index-html  # Regenerate index.html from fragments
```

See [docs/FLOW_STUDIO.md](./docs/FLOW_STUDIO.md) for Flow Studio documentation.

**HTML Source Layout**: Flow Studio's `index.html` is generated from modular fragments in `swarm/tools/flow_studio_ui/fragments/`. To edit the UI structure, modify the appropriate fragment and run `make gen-index-html`. Do not edit `index.html` directly.

**Governed Surfaces**: Flow Studio exposes a stable SDK (`window.__flowStudio`) and typed UIID selectors (`[data-uiid="..."]`) for tests and agents. If you change these surfaces, update the corresponding tests. See "Governed Surfaces" section in FLOW_STUDIO.md.

### Testing

```bash
uv run pytest tests/                              # Run Python tests
uv run pytest tests/test_validate_swarm.py -k "test_name"  # Run specific test
```

### Profile Management

Profiles are portable snapshots of your swarm configuration (flows + agents) that you can save, share, compare, and apply.

```bash
make profile-list                              # List available profiles
make profile-save PROFILE_ID=my-swarm          # Save current config as profile
make profile-load PROFILE_ID=baseline          # Apply a profile
make profile-diff PROFILE_A=a PROFILE_B=b      # Compare two profiles
make profile-diff PROFILE_A=a CURRENT=1        # Compare profile to current state
make profiles-help                             # Show full profile workflow
```

After loading a profile, regenerate adapters: `make gen-flow-constants && make gen-adapters && make ts-build`

See [docs/FLOW_PROFILES.md](./docs/FLOW_PROFILES.md) for detailed profile documentation.

### Stepwise Execution

Stepwise backends execute flows one step at a time, enabling per-step observability:

```bash
make stepwise-sdlc-stub          # Zero-cost demo (CI / Demo persona)
make stepwise-sdlc-claude-cli    # Full SDLC with Claude CLI (CLI-only persona)
make stepwise-sdlc-claude-sdk    # Full SDLC with Claude Agent SDK (API User persona)
make stepwise-help               # Show all stepwise commands
```

Stepwise runs execute one LLM call per step. Artifacts:
- Transcripts: `RUN_BASE/<flow>/llm/<step>-<agent>-<engine>.jsonl`
- Receipts: `RUN_BASE/<flow>/receipts/<step>-<agent>.json`

For what's actually enforced (teaching_notes, routing, receipts), see the [Contracts table in STEPWISE_BACKENDS.md](./docs/STEPWISE_BACKENDS.md#contracts-proof-not-promise).

See [docs/STEPWISE_BACKENDS.md](./docs/STEPWISE_BACKENDS.md) for full documentation.

---

## Architecture

### Spec vs Adapter Separation

- **Spec layer** (`swarm/flows/*.md`): Defines abstract roles and artifacts—*what* should happen
- **Adapter layer** (`.claude/`): GitHub-native implementation—*how* it happens with `gh` CLI

**Flows 1-4**: Spec role = adapter agent (1:1 mapping). GitHub ops integrated throughout.
**Flows 5-7**: Spec roles may fan out to multiple GitHub-specific agents (e.g., deploy-trigger → merge-executor + release-tagger).

### Orchestration Model

**Orchestrator (top-level Claude)**:
- Can call all agents: built-in (`explore`, `plan-subagent`, `general-subagent`) and domain (`.claude/agents/*.md`)
- Controls microloop iteration in Flows 1 and 3

**Domain Agents**:
- Defined in `.claude/agents/*.md` with frontmatter + prompt
- All agents inherit full tooling (behavior constrained by prompts, not tool denial)
- Currently cannot call other agents (runtime constraint)

**Stepwise Execution** (optional):
- Uses `GeminiStepOrchestrator` from `swarm/runtime/orchestrator.py`
- Makes one LLM call per step instead of one call per flow
- Enables per-step observability, context handoff, and better error isolation
- Writes transcripts to `RUN_BASE/<flow>/llm/` and receipts to `RUN_BASE/<flow>/receipts/`
- See [docs/FLOW_STUDIO.md](./docs/FLOW_STUDIO.md) "Stepwise Backends" section for details

### V3 Routing Model

The V3 architecture introduces **graph-native routing** with goal-aligned decisions:

**Routing Decisions** (closed vocabulary):

| Decision | Description | Use Case |
|----------|-------------|----------|
| **CONTINUE** | Proceed on golden path | Normal flow progression |
| **DETOUR** | Inject sidequest chain | Known failure patterns (lint fix, dep update) |
| **INJECT_FLOW** | Insert entire flow | Flow 3 calling Flow 8 rebase when upstream diverges |
| **INJECT_NODES** | Ad-hoc nodes | Novel requirements not covered by existing flows |
| **EXTEND_GRAPH** | Propose patch | Wisdom learns new pattern; suggests SOP evolution |

**Key Principles**:
- **Suggested Sidequests**: The system proposes detours based on context; orchestrator decides
- **Flow Injection**: Complete flows can be injected mid-execution (e.g., rebase during build)
- **Goal-Aligned Routing**: Every decision passes the "Does this help achieve the objective?" test
- **Off-Road Capability**: Novel situations are expected, not exceptional; always logged

See [docs/ROUTING_PROTOCOL.md](./docs/ROUTING_PROTOCOL.md) for the full routing contract.

### Agent Summary

- **Built-in (3)**: explore, plan-subagent, general-subagent
- **Cross-cutting (5)**: clarifier, risk-analyst, policy-analyst, repo-operator, gh-reporter
- **Utility (3)**: swarm-ops, ux-critic, ux-implementer
- **Flow-specific (45)**: See [docs/AGENT_OPS.md](./docs/AGENT_OPS.md) for full taxonomy

**Total: 56 agents** (3 built-in + 53 domain)

---

## Config & Registry Contracts

The swarm uses two registries as single sources of truth for flow and profile state.

### Flow Registry (`flow_registry.py`)

**Location:** `swarm/config/flow_registry.py`

This is the **ONLY** place code asks about flow order, step indices, or agent positions.

- `swarm/config/flows.yaml`: Flow ordering and keys (signal, plan, build, gate, deploy, wisdom)
- `swarm/config/flows/*.yaml`: Per-flow step definitions and agent assignments

**Key functions:**

```python
from swarm.config.flow_registry import (
    get_flow_index,      # Flow 1-7 index by key
    get_step_index,      # Step index within flow
    get_agent_position,  # Agent's [(flow_key, step_id, flow_idx, step_idx), ...]
    get_total_flows,     # Total flows (7)
    get_total_steps,     # Steps in a flow
)
```

### Profile Registry (`profile_registry.py`)

**Location:** `swarm/config/profile_registry.py`

This is the **ONLY** place code reads/writes profile state.

- Profiles: Snapshots of `flows.yaml` + `flows/*.yaml` + `config/agents/*.yaml`
- Current profile marker: `swarm/profiles/.current_profile`
- Profile files: `swarm/profiles/*.swarm_profile.yaml`

**Key functions:**

```python
from swarm.config.profile_registry import (
    get_current_profile,    # Returns current profile ID or None
    set_current_profile,    # Updates .current_profile marker
    list_profiles,          # Lists available profile IDs
    load_profile_meta,      # Loads profile metadata
)
```

### Why This Matters

- **Single source of truth**: Both registries wrap config files; no other code should parse these YAMLs directly
- **Stable numbering**: Flow indices (1-6) and step indices come from `flow_registry.py`, not hardcoded
- **Profile portability**: When you swap profiles, the registries update consistently

---

## RUN_BASE: Artifact Placement

For a run identified by `<run-id>`:

```text
RUN_BASE = swarm/runs/<run-id>/
```

Each flow writes artifacts under `RUN_BASE/<flow>/`:

- `RUN_BASE/signal/` — problem statement, requirements, BDD, risk assessment
- `RUN_BASE/plan/` — ADR, contracts, observability spec, test/work plans
- `RUN_BASE/build/` — test summaries, critiques, receipts, git status
- `RUN_BASE/review/` — PR feedback, review worklist, fix actions, review receipt
- `RUN_BASE/gate/` — audit reports, policy verdict, merge recommendation
- `RUN_BASE/deploy/` — merge status, release info, CI status, smoke test results
- `RUN_BASE/wisdom/` — artifact audit, test analysis, regressions, learnings

**Code/tests** remain in standard locations: `src/`, `tests/`, `features/`, `migrations/`, `fuzz/`.

**Curated examples** live in `swarm/examples/<scenario>/` (e.g., `swarm/examples/health-check/`).

---

## Key Patterns

### 1. Microloops: Adversarial Iteration

Flows 1 and 3 use microloops between writer and reviewer:

- **Requirements loop** (Flow 1): `requirements-author` <-> `requirements-critic`
- **Test loop** (Flow 3): `test-author` <-> `test-critic`
- **Code loop** (Flow 3): `code-implementer` <-> `code-critic`

**Exit when**: `Status == VERIFIED` OR (`Status == UNVERIFIED` AND `can_further_iteration_help == no`)

Critics never fix; they write harsh critiques. Stations never block—they document concerns and continue.

### 2. Heavy Context Loading

Context-heavy agents (`context-loader`, `impact-analyzer`) are encouraged to load 20-50k tokens. Compute is cheap; reducing downstream re-search saves attention.

### 3. Git State Management

- **Flow 3 Step 0**: `repo-operator` ensures clean tree, creates feature branch
- **Flow 3 Final Step**: `repo-operator` stages changes, composes message, commits
- `repo-operator` uses **safe Bash commands only** (no `--force`, no `--hard`)

### 4. Bounce-Backs

Gate (Flow 4) may bounce work back to Build or Plan if issues are non-trivial. Gate fixes are mechanical only (lint, format, docstrings).

### 5. Always Complete the Flow

Stations never block or escalate mid-flow. Document ambiguities and concerns in receipts, then continue. Humans review at flow gates.

### 6. Assumptive-but-Transparent Work

When facing ambiguity, stations:
1. Make a reasonable assumption
2. Document the assumption explicitly (what, why, impact if wrong)
3. Note what would change if the assumption is wrong
4. Proceed with work

This enables re-running flows with better inputs. Humans answer clarification questions at flow boundaries, not mid-flow. Each flow is designed to be **run again** with refined inputs.

**BLOCKED is exceptional**: Set BLOCKED only when input artifacts don't exist. Ambiguity uses documented assumptions + UNVERIFIED status, not BLOCKED.

See [docs/CONTEXT_BUDGETS.md](./docs/CONTEXT_BUDGETS.md) for how budgets control input context selection (not output generation).

See [docs/LEXICON.md](./docs/LEXICON.md) for canonical vocabulary (station, step, navigator, worker, etc.).

### 7. Context Sharding

Steps delegate token-heavy operations to subagents to avoid context pollution:

- A Step maintains the *logic* while Subagents burn tokens on *mechanics* (reading files, running commands)
- The Step doesn't get "drunk" on grep output—the Subagent abstracts it away
- Both Steps and Subagents are full Claude Code orchestrators with different scopes
- This distributes token load across isolated sessions

**Hierarchy**:
```
Python Kernel (Director)  →  Step (Manager)  →  Subagent (Specialist)
      manages resources        executes station      executes operation
```

### 8. Off-Road Capability with Logging

The V3 routing model allows flows to go "off-road" when the golden path is insufficient:

- **Novel situations expected**: Not every scenario fits pre-defined flows
- **Always spec'd and logged**: Every routing decision produces artifacts in `RUN_BASE/<flow>/routing/`
- **Deviations tracked**: `routing_offroad` events log all non-CONTINUE decisions

Artifacts include:
- `decisions.jsonl` — Append-only log of all routing decisions
- `injections/` — Flow and node injection records
- `proposals/` — Graph extension proposals from Wisdom

See [docs/ROUTING_PROTOCOL.md](./docs/ROUTING_PROTOCOL.md) for off-road logging details.

---

## File Structure

```text
.claude/
  agents/          # 53 domain agent definitions
  commands/        # Slash commands (including 7 flow entrypoints)
  skills/          # 4 global skills
  settings.json

swarm/
  flows/           # Flow specs with mermaid diagrams
  runbooks/        # Implementation playbooks
  infrastructure/  # Production extension guides
  tools/           # Python validation scripts
  config/          # Agent and flow config YAML (source of truth)
  runs/            # Active run artifacts (gitignored)
  examples/        # Curated demo snapshots
  AGENTS.md        # Agent registry

src/               # Implementation code (AUTHORITATIVE)
tests/             # Tests (AUTHORITATIVE)
features/          # BDD scenarios (AUTHORITATIVE)
```

---

## Running Flows

1. **Signal** (`/flow-1-signal <issue>`): Requirements microloop -> `RUN_BASE/signal/`
2. **Plan** (`/flow-2-plan`): ADR, contracts, test/work plans -> `RUN_BASE/plan/`
3. **Build** (`/flow-3-build [subtask-id]`): Code microloops -> `RUN_BASE/build/`
4. **Review** (`/flow-4-review`): PR feedback, fixes, Draft->Ready -> `RUN_BASE/review/`
5. **Gate** (`/flow-5-gate`): Audit and merge decision -> `RUN_BASE/gate/`
6. **Deploy** (`/flow-6-deploy`): Merge, verify, report -> `RUN_BASE/deploy/`
7. **Wisdom** (`/flow-7-wisdom`): Analyze, learn, feedback -> `RUN_BASE/wisdom/`

---

## Common Pitfalls

1. **Don't skip validation**: Run `make validate-swarm` before committing
2. **Respect RUN_BASE**: Never write flow artifacts to repo root
3. **Flow order matters**: Don't run Flow 3 without Flow 2 outputs
4. **Agent naming**: `name:` frontmatter must match filename and `AGENTS.md` key exactly
5. **Don't edit frontmatter**: Edit `swarm/config/agents/<key>.yaml`, then regenerate
6. **Critics don't fix**: They write reports; implementers apply fixes
7. **Stations never block**: Complete the flow and document concerns in receipts
8. **Don't overuse BLOCKED**: BLOCKED is for missing inputs, not ambiguity. If you can read your inputs, you're VERIFIED or UNVERIFIED.
9. **Document assumptions explicitly**: Every station output should have "Assumptions Made" if any were needed.

---

## CI/CD Troubleshooting

```bash
uv sync --frozen     # Replicate CI environment
make dev-check       # Run all checks
make selftest-doctor # Diagnose issues
```

See [docs/CI_TROUBLESHOOTING.md](./docs/CI_TROUBLESHOOTING.md) for detailed troubleshooting guide.

---

## Extension Points

1. **Add new agent**: Edit `swarm/AGENTS.md` + create config in `swarm/config/agents/` + run `make gen-adapters`
2. **Add new flow**: Create `swarm/flows/flow-<name>.md` + create command in `.claude/commands/`
3. **Add new skill**: Create `.claude/skills/<name>/SKILL.md` + update `swarm/skills.md`
4. **Extend Flows 6-7**: See `swarm/infrastructure/` for production patterns

---

## For New Contributors

This repo demonstrates:

- How to model SDLC as **flows** (not chat)
- How to use **agents as narrow interns** (not magic copilots)
- How to enforce **receipts and gravity wells** (not vibes)
- How to **trade compute for attention** (working patterns)
- How to implement **graph-native routing** (flows as directed graphs with injection capability)
- How to enable **high-trust orchestration** (suggested sidequests, goal-aligned decisions, always-logged deviations)

The V3 architecture treats flows as graphs where nodes can be injected, bypassed, or extended at runtime. This enables adaptive execution while maintaining auditability through the routing protocol.

Read `swarm/positioning.md` for the full philosophy. Browse `swarm/examples/health-check/` for concrete flow outputs. See [docs/ROUTING_PROTOCOL.md](./docs/ROUTING_PROTOCOL.md) for the routing model.

---

## Detailed Documentation

| Topic | Document |
|-------|----------|
| **Architecture & Philosophy** | |
| v3.0 Architecture | [ARCHITECTURE.md](./ARCHITECTURE.md) |
| Routing Protocol v3 | [docs/ROUTING_PROTOCOL.md](./docs/ROUTING_PROTOCOL.md) |
| AgOps Manifesto | [docs/AGOPS_MANIFESTO.md](./docs/AGOPS_MANIFESTO.md) |
| Lexicon (canonical vocabulary) | [docs/LEXICON.md](./docs/LEXICON.md) |
| v3.0 Roadmap | [docs/ROADMAP_3_0.md](./docs/ROADMAP_3_0.md) |
| v2.4 Roadmap (legacy) | [docs/ROADMAP_2_4.md](./docs/ROADMAP_2_4.md) |
| **Validation & Governance** | |
| Validation rules (FR-001-FR-005) | [docs/VALIDATION_RULES.md](./docs/VALIDATION_RULES.md) |
| Validation walkthrough | [docs/VALIDATION_WALKTHROUGH.md](./docs/VALIDATION_WALKTHROUGH.md) |
| Agent operations | [docs/AGENT_OPS.md](./docs/AGENT_OPS.md) |
| Selftest system | [swarm/SELFTEST_SYSTEM.md](./swarm/SELFTEST_SYSTEM.md) |
| **Flow Studio & UI** | |
| Flow Studio | [docs/FLOW_STUDIO.md](./docs/FLOW_STUDIO.md) |
| Flow profiles | [docs/FLOW_PROFILES.md](./docs/FLOW_PROFILES.md) |
| **Runtime & Execution** | |
| Stepwise backends | [docs/STEPWISE_BACKENDS.md](./docs/STEPWISE_BACKENDS.md) |
| Stepwise contract | [docs/STEPWISE_CONTRACT.md](./docs/STEPWISE_CONTRACT.md) |
| Context budgets | [docs/CONTEXT_BUDGETS.md](./docs/CONTEXT_BUDGETS.md) |
| **Getting Started** | |
| Getting started | [docs/GETTING_STARTED.md](./docs/GETTING_STARTED.md) |
| 20-minute tour | [docs/TOUR_20_MIN.md](./docs/TOUR_20_MIN.md) |
| CI troubleshooting | [docs/CI_TROUBLESHOOTING.md](./docs/CI_TROUBLESHOOTING.md) |
| **Release Notes** | |
| Release notes v2.3.0 | [docs/RELEASE_NOTES_2_3_0.md](./docs/RELEASE_NOTES_2_3_0.md) |
