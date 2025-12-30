# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Overview

This repo implements an agentic SDLC with **seven flows** covering the full lifecycle of a change:

1. **Signal → Specs** (Flow 1): Raw input → problem statement, requirements, BDD, early risk
2. **Specs → Plan** (Flow 2): Requirements → ADR, contracts, observability, test/work plans
3. **Plan → Draft** (Flow 3): Implement via adversarial microloops → code, tests, receipts
4. **Draft → Review** (Flow 4): Create Draft PR, harvest bot/human feedback, iterate on feedback
5. **Review → Gate** (Flow 5): Pre-merge gate → audit receipts, check contracts/policy, recommend merge/bounce
6. **Gate → Prod** (Flow 6): Move approved artifact to deployed → verify health, create audit trail
7. **Prod → Wisdom** (Flow 7): Analyze artifacts, detect regressions, extract learnings, close feedback loops

**Core trade**: Spend compute to save senior engineer attention. Optimize for receipts and auditability, not speed.

When an agent makes a decision, you can trace it back to the spec it was following. That's how you debug agentic flows without guessing.

**Out-of-the-Box**: GitHub integration is woven throughout:
- Flows 1-2: GitHub for issue research and context
- Flow 3: Creates Draft PRs to wake bots
- Flow 4: Harvests PR feedback
- Flows 5-7: Gating, deployment, learning

Works immediately on clone. See `swarm/infrastructure/` for production extension patterns.

See `swarm/positioning.md` for the full approach and `REPO_MAP.md` for a comprehensive structural overview.

---

## Technology Stack

- **Python**: UV for validation tooling, selftest, Flow Studio, and runtime backends
- **TypeScript**: Flow Studio UI components
- **Git**: Managed by `repo-operator` agent in Flows 3-6

---

## Essential Commands

### Validation
Always run before committing changes to `swarm/` or `.claude/`:

```bash
uv run swarm/tools/validate_swarm.py
# or
make validate-swarm
```

The validator (`swarm/tools/validate_swarm.py`) enforces the two-layer architecture:

**Layer 1: Claude Code Platform Spec**
- YAML parses correctly
- Fields are of correct types
- Values are sensible (e.g., `model` in `[inherit, haiku, sonnet, opus]`)

**Layer 2: Demo Swarm Design Constraints**
- Required fields: `name`, `description`, `color`, `model`
- Domain agents omit `tools:` and `permissionMode:` (prompt-based constraints)
- Agent `name:` matches filename and registry key
- Flow specs reference valid agents only
- Skills have valid SKILL.md files
- Flow specs use RUN_BASE placeholders

See root `/CLAUDE.md` for detailed validation documentation, common errors, and troubleshooting.

Validates:
- FR-001: Bijection (agents ⟷ registry)
- FR-002: Frontmatter (required fields, design constraints)
- FR-003: Flow references (with typo detection)
- FR-004: Skills (skill files exist)
- FR-005: RUN_BASE (placeholders, not hardcoded paths)

### Testing
```bash
# Run Python tests
uv run pytest tests/

# Run specific test
uv run pytest tests/test_validate_swarm.py -k "test_name"
```

### Pre-commit Hooks
```bash
pip install pre-commit
pre-commit install
```

---

## Architecture

### Spec vs Adapter Separation

The swarm uses a **two-layer architecture**:

- **Spec layer** (`swarm/flows/*.md`): Defines abstract roles and artifacts—*what* should happen
- **Adapter layer** (`.claude/`): GitHub-native implementation—*how* it happens with `gh` CLI

**Flows 1-5**: Spec role = adapter agent (1:1 mapping). The spec says "use `requirements-critic`" and there's a concrete `requirements-critic` agent in `.claude/agents/`.

**Flows 6-7**: Spec roles are abstract; adapter fans them out to multiple GitHub-specific agents:
- Spec role `deploy-trigger` → adapters `merge-executor` + `release-tagger`
- Spec role `regression-analyzer` → adapters `test-analyzer` + `coverage-tracker` + `issue-correlator` + `regression-detector`

This keeps the spec portable (GitLab/Bitbucket orgs can implement differently) while providing batteries-included GitHub integration.

### Orchestration Model

The swarm has **two execution levels**:

**1. Orchestrator (top-level Claude)**:
- Can call **all agents**: built-in (`explore`, `plan-subagent`, `general-subagent`) and domain (`.claude/agents/*.md`)
- Interprets agent outputs (status, recommended_next) to decide routing
- Controls microloop iteration in Flows 1 and 3
- May use `explore` to gather context before invoking domain agents

**2. All Agents** (built-in and domain):
- **Built-in agents**: provided by Claude Code, no local definition files
- **Domain agents**: defined in `.claude/agents/*.md` with frontmatter + prompt
- All agents use tools declared in their frontmatter (Read, Write, Glob, Grep, Bash)
- All agents use Skills when declared in frontmatter
- All agents read inputs from files, write outputs to files

**Current Implementation Constraint**: Due to Claude Code limitations, domain agents currently cannot call other agents. This is a runtime constraint, not a design requirement. For now: agents are pure tool-users; only the orchestrator coordinates multiple agents.

### Agent Taxonomy

**Built-in Infra Agents (3)** — native to Claude Code, no `.claude/agents/` files:
- `explore` — Fast Haiku read-only search (Glob/Grep/Read/Bash)
- `plan-subagent` — High-level repo analyzer for complex architecture
- `general-subagent` — Generic Task worker (implicit)

**Cross-cutting Agents (5)** — used across multiple flows:
- `clarifier` — Detect ambiguities, draft clarification questions
- `risk-analyst` — Identify risk patterns (security, compliance, data, performance)
- `policy-analyst` — Interpret policy docs vs change
- `repo-operator` — Git workflows: branch, commit, merge, tag (safe Bash only)
- `gh-reporter` — Post summaries to GitHub issues/PRs

**Utility Agents (3)** — used for operations and tooling:
- `swarm-ops` — Guide for agent operations: model changes, adding agents, inspecting flows
- `ux-critic` — Inspect Flow Studio screens and produce structured JSON critiques
- `ux-implementer` — Apply UX critique fixes to Flow Studio code and run tests

**Flow-specific Agents (40+)**:
- **Flow 1 - Signal** (6): signal-normalizer, problem-framer, requirements-author, requirements-critic, bdd-author, scope-assessor
- **Flow 2 - Plan** (8): impact-analyzer, design-optioneer, adr-author, interface-designer, observability-designer, test-strategist, work-planner, design-critic
- **Flow 3 - Build** (9): context-loader, test-author, test-critic, code-implementer, code-critic, mutator, fixer, doc-writer, self-reviewer
- **Flow 4 - Review** (3+): pr-creator, feedback-harvester, feedback-responder
- **Flow 5 - Gate** (6): receipt-checker, contract-enforcer, security-scanner, coverage-enforcer, gate-fixer, merge-decider
- **Flow 6 - Deploy** (3): deploy-monitor, smoke-verifier, deploy-decider
- **Flow 7 - Wisdom** (5): artifact-auditor, regression-analyst, flow-historian, learning-synthesizer, feedback-applier

**Total: 51+ agents** (3 built-in + 48+ domain)

### Skills vs. Agents

**Skills** (`.claude/skills/*/SKILL.md`): Global, model-invoked capabilities:
- `test-runner` — Execute test suites, write `test_output.log` and `test_summary.md`
- `auto-linter` — Mechanical lint/format fixes
- `policy-runner` — Policy-as-code validation
- `heal_selftest` — Diagnose and repair selftest failures

Domain agents invoke Skills via their `skills:` frontmatter. Skills are **tools**, not agents.

---

## RUN_BASE: Artifact Placement

For a run identified by `<run-id>` (e.g., ticket ID, branch name):

```
RUN_BASE = swarm/runs/<run-id>/
```

Each flow writes artifacts under `RUN_BASE/<flow>/`:
- `RUN_BASE/signal/` — problem statement, requirements, BDD, risk assessment
- `RUN_BASE/plan/` — ADR, contracts, observability spec, test/work plans
- `RUN_BASE/build/` — test summaries, critiques, receipts, git status
- `RUN_BASE/review/` — PR feedback, bot comments, review iterations
- `RUN_BASE/gate/` — audit reports, policy verdict, merge recommendation
- `RUN_BASE/deploy/` — merge status, release info, CI status, smoke test results
- `RUN_BASE/wisdom/` — artifact audit, test analysis, regressions, learnings, playbook updates

**Code/tests** remain in standard locations: `src/`, `tests/`, `features/`, `migrations/`, `fuzz/`.

**Curated examples** live in `swarm/examples/<scenario>/` (e.g., `swarm/examples/health-check/`). Each example includes:
- Flow artifacts from all 7 flows (`signal/`, `plan/`, `build/`, `review/`, `gate/`, `deploy/`, `wisdom/`)
- A `code-snapshot/` directory with copies of code at the time of the snapshot (for teaching only)
- A `reports/` directory with dry-run diagnostics
- See `swarm/examples/health-check/README.md` for the example structure

**Active runs** are gitignored via `swarm/runs/` in `.gitignore`.

**Important**: The authoritative code lives in `src/`, `tests/`, `features/`, `migrations/`, and `fuzz/` at the repo root. The `code-snapshot/` directories in examples are read-only copies for teaching purposes only.

---

## Key Patterns

### 1. Microloops: Adversarial Iteration

Flows 1 and 3 use **microloops**—the orchestrator loops between writer and reviewer based on explicit `Status` and `can_further_iteration_help` signals:

- **Requirements loop** (Flow 1): `requirements-author` ⇄ `requirements-critic`
- **Test loop** (Flow 3): `test-author` ⇄ `test-critic`
- **Code loop** (Flow 3): `code-implementer` ⇄ `code-critic`
- **Hardening** (Flow 3): `mutator` → `fixer` → re-verify as needed

#### Loop Exit Conditions (Canonical Rule)

**Continue looping while:**
- `Status == UNVERIFIED` **and**
- `can_further_iteration_help == yes` in critic's Iteration Guidance

**Exit loop when:**
- `Status == VERIFIED`, **or**
- `Status == UNVERIFIED` **and** `can_further_iteration_help == no` (critic explicitly judges there is no viable fix path within current scope/constraints)

Critics **never fix**; they write harsh critiques with clear status and explicit iteration guidance. Implementers may be called multiple times while `can_further_iteration_help: yes`.

**Agents never block**: If work can't be perfected within constraints, critics set `can_further_iteration_help: no` and document concerns. Human reviews receipts at flow boundary and decides whether to rerun or accept documented limitations. There are no hard iteration caps—context and runtime naturally constrain loops. The critic's judgment about iteration viability, not a loop counter, determines exit.

### 2. Heavy Context Loading

Context-heavy agents (`context-loader`, `impact-analyzer`) are **encouraged** to load 20-50k tokens of relevant material. Compute is cheap; reducing downstream re-search saves attention.

The **orchestrator** may use `explore` liberally to locate files, docs, incidents before invoking domain agents. Domain agents then use Glob/Grep/Read on specific paths.

### 3. Git State Management

- **Flow 3 Step 0**: `repo-operator` ensures clean tree, creates feature branch
- **Flow 3 Final Step**: `repo-operator` stages changes, composes message, commits
- **Flow 4**: `pr-creator` opens Draft PR to trigger bots
- **Flow 5 (optional)**: `repo-operator` for mechanical gate fixes only

`repo-operator` uses **safe Bash commands only** (no `--force`, no `--hard`).

### 4. Bounce-Backs

Gate (Flow 5) may **bounce** work back to Build (Flow 3) or Plan (Flow 2) if issues are non-trivial:
- Gate fixes are **mechanical only** (lint, format, docstrings, typos, changelogs)
- Logic/test/API/schema issues → bounce to Build
- Design flaws → bounce to Plan

See Flow 5 spec for full mechanical-only definition.

### 5. Always Complete the Flow

Agents **never block or escalate mid-flow**:
- Document ambiguities in `clarification_questions.md`
- Document concerns in critiques/receipts
- State assumptions explicitly
- Continue with best interpretation
- **Always reach the flow boundary**
- Humans review receipts at flow gate and decide whether to rerun

### 6. Closed Feedback Loops (Flow 7)

Flow 7 (Wisdom) closes the SDLC loop by feeding learnings back:
- **→ Flow 3**: `feedback-applier` creates GitHub issues for missing test scenarios
- **→ Flow 2**: `feedback-applier` suggests updates to architecture docs and templates
- **→ Flow 1**: `learning-synthesizer` extracts problem patterns for requirement templates

These are **recommendations in artifacts**, not direct flow invocations. Humans decide which to act on.

---

## File Structure

```
.claude/
  agents/          # 48+ domain agent definitions (YAML frontmatter + prompt)
  commands/flows/  # 7 slash commands for flow orchestration
  skills/          # 4 global skills
  settings.json

swarm/
  flows/           # Flow specs with mermaid diagrams, RUN_BASE pathing, microloops
  infrastructure/  # Production extension guides (flow-6-extensions.md, flow-7-extensions.md)
  tools/           # Python validation scripts
  runs/            # Active run artifacts (gitignored)
  examples/        # Curated demo snapshots (committed)
    health-check/  # Complete end-to-end example
      code-snapshot/  # Copies of code at snapshot time (teaching only)
      signal/      # Flow 1 artifacts
      plan/        # Flow 2 artifacts
      build/       # Flow 3 artifacts
      review/      # Flow 4 artifacts
      gate/        # Flow 5 artifacts
      deploy/      # Flow 6 artifacts
      wisdom/      # Flow 7 artifacts
      reports/     # Flow dry-run diagnostics
  AGENTS.md        # Agent registry (source of truth)
  positioning.md   # Philosophy and axioms
  skills.md        # Skills documentation

src/               # Rust implementation (minimal; primarily swarm demo) - AUTHORITATIVE
tests/             # Rust tests - AUTHORITATIVE
features/          # BDD scenarios (Gherkin) - AUTHORITATIVE
migrations/        # SQL migrations - AUTHORITATIVE
fuzz/              # Fuzz harnesses - AUTHORITATIVE
```

---

## Development Workflow

### Running Flows

1. **Signal** (`/flow-1-signal <issue-description>`):
   - Runs requirements microloop: author ⇄ critic
   - Produces: problem statement, requirements, BDD, risk assessment
   - Outputs to: `swarm/runs/<run-id>/signal/`

2. **Plan** (`/flow-2-plan`):
   - Produces: ADR, contracts, observability spec, test/work plans
   - Outputs to: `swarm/runs/<run-id>/plan/`

3. **Build** (`/flow-3-build [subtask-id]`):
   - Runs microloops: test ⇄ critic, code ⇄ critic, mutator → fixer
   - Produces: code, tests, receipts (`build_receipt.json`)
   - Outputs to: `swarm/runs/<run-id>/build/`
   - Git: `repo-operator` (branch at start, commit at end)

4. **Review** (`/flow-4-review`):
   - Creates Draft PR to wake bots, harvests feedback, iterates
   - Produces: PR feedback, bot comments, review iterations
   - Outputs to: `swarm/runs/<run-id>/review/`
   - Git: `pr-creator` opens Draft PR

5. **Gate** (`/flow-5-gate`):
   - Audits receipts, checks contracts/security/perf/policy
   - Applies mechanical fixes or bounces to Build/Plan
   - Produces: `merge_decision.md`
   - Outputs to: `swarm/runs/<run-id>/gate/`

6. **Deploy** (`/flow-6-deploy`):
   - Always callable; reads Gate's decision and behaves accordingly
   - If MERGE: merge, verify, report. If BOUNCE/ESCALATE: don't merge, explain why.
   - Produces: `deployment_log.md`, `verification_report.md`, `deployment_decision.md`
   - Outputs to: `swarm/runs/<run-id>/deploy/`

7. **Wisdom** (`/flow-7-wisdom`):
   - Analyze artifacts, detect regressions, extract learnings, close feedback loops
   - Spec roles: `artifact-auditor` → `regression-analyst` → `flow-historian` → `learning-synthesizer` → `feedback-applier` → `gh-reporter`
   - Produces: `artifact_audit.md`, `regression_report.md`, `flow_history.json`, `learnings.md`, `feedback_actions.md`
   - Outputs to: `swarm/runs/<run-id>/wisdom/`

### Attention Economics

Each flow **trades compute for human DevLT** (Dev Lead Time):
- Let agents iterate; review receipts, not intermediate steps
- 10k tokens up-front (context loading) saves 50k downstream
- Harsh critics prevent bugs from reaching Gate/Deploy/Wisdom
- Agents never block; they document concerns and continue
- Human gates at flow boundaries decide whether to proceed or rerun

---

## Working with Agents

### Agent Definition Format

All agents in `.claude/agents/*.md`:

```yaml
---
name: agent-key-name
description: One-line responsibility
tools: Read, Write, Bash
model: inherit  # or sonnet, haiku
permissionMode: default
skills: []      # or [test-runner, auto-linter]
---

You are the **Agent Name**.

## Inputs
- `RUN_BASE/<flow>/file1.md`

## Outputs
- `RUN_BASE/<flow>/artifact.md` describing...

## Behavior
1. Step one
2. Step two
```

### Adding/Modifying Agents

1. Update `swarm/AGENTS.md` with agent key, flows, family, role
2. Create/edit `.claude/agents/<key>.md` with matching `name:` frontmatter
3. If used in flows, update `swarm/flows/flow-*.md` step tables
4. Run `make validate-swarm` before committing

---

## Common Pitfalls

1. **Don't skip validation**: Pre-commit hook prevents invalid agent/flow definitions
2. **Respect RUN_BASE**: Never write flow artifacts to repo root
3. **Flow order matters**: Don't run Flow 3 without Flow 2 outputs
4. **Agent naming**: `name:` frontmatter must match filename and `AGENTS.md` key exactly
5. **All agents are orchestrator-only**: Only top-level Claude calls agents (built-in or domain)
6. **Agents currently can't call agents**: Due to Claude Code limitations (runtime constraint, not design)
7. **Skills are tools**: Agents invoke skills via frontmatter, not the other way around
8. **Critics don't fix**: They write harsh reports; implementers apply fixes
9. **Agents never block**: Agents always complete the flow and document concerns in receipts; they never escalate mid-flow

---

## Testing Philosophy

- **Scaffolding-first**: Write explicit test structure even if implementation minimal
- **BDD-driven**: Scenarios in `features/*.feature` drive test coverage
- **Mutation testing**: `mutator` agent identifies weak spots
- **test-runner skill**: Agents use skill to execute suites, not raw `cargo test`

---

## Extension Points

To extend the swarm:

1. **Add new agent**:
   - Define in `swarm/AGENTS.md` (family, flows, role)
   - Create `.claude/agents/<key>.md` with frontmatter + prompt
   - Update flow specs in `swarm/flows/` if needed
   - Run `make validate-swarm`

2. **Add new flow**:
   - Create `swarm/flows/flow-<name>.md` with mermaid diagram, steps table
   - Create `.claude/commands/flow-<name>.md` orchestrator
   - Add agents to `AGENTS.md` if new ones needed
   - Update `CLAUDE.md` with flow description

3. **Add new skill**:
   - Create `.claude/skills/<name>/SKILL.md` with frontmatter
   - Update `swarm/skills.md` documentation
   - Reference in agent `skills:` frontmatter as needed

4. **Extend Flows 6-7 with production infrastructure**:
   - See `swarm/infrastructure/flow-6-extensions.md` for k8s, canary, metrics
   - See `swarm/infrastructure/flow-7-extensions.md` for observability platforms
   - Add environment variable detection to agent prompts
   - Graceful fallback: baseline always works, extensions add capability

---

## For New Contributors

This repo demonstrates:
- How to model SDLC as **flows** (not chat)
- How to use **agents as narrow interns** (not magic copilots)
- How to enforce **receipts and gravity wells** (not vibes)
- How to **trade compute for attention** (working patterns)

Read `swarm/positioning.md` for the full philosophy. Then browse `swarm/examples/health-check/` to see concrete flow outputs.
