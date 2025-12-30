# Glossary

> For: Anyone needing quick definitions of swarm terminology.

Key terms used throughout the demo-swarm codebase.

## Core Concepts

### Flow
A sequence of agent invocations that transforms inputs into outputs. The swarm has 7 flows:
- **Flow 1 (Signal)**: Raw input → specs, requirements, BDD
- **Flow 2 (Plan)**: Specs → ADR, contracts, test/work plans
- **Flow 3 (Build)**: Plans → code, tests, receipts
- **Flow 4 (Review)**: Code → review feedback, improvements
- **Flow 5 (Gate)**: Code → audit, merge decision
- **Flow 6 (Deploy)**: Artifact → production
- **Flow 7 (Wisdom)**: Production → learnings, feedback

### Step
A discrete unit of work within a flow. Steps invoke one or more agents and produce specific artifacts. Steps have IDs like `normalize`, `frame-problem`, `implement`.

### Run
A single execution of one or more flows for a specific task. Runs are identified by a run-id (e.g., `demo-health-check`) and store artifacts under `swarm/runs/<run-id>/`.

### RUN_BASE
A placeholder path pattern used in flow specs: `RUN_BASE/<flow>/`. Resolves to `swarm/runs/<run-id>/<flow>/` at runtime. Keeps specs portable across repos.

## Agent Taxonomy

### Domain Agent
An agent defined in `.claude/agents/*.md` with frontmatter + prompt. Responsible for specific tasks within flows. Example: `requirements-author`, `code-critic`.

### Built-in Agent
An agent provided by Claude Code, no local definition. Three built-ins: `explore` (fast search), `plan-subagent` (architecture), `general-subagent` (generic).

### Cross-cutting Agent
A domain agent used across multiple flows. Examples: `clarifier`, `risk-analyst`, `repo-operator`, `gh-reporter`.

### Critic
An agent that reviews work but never fixes it. Critics produce harsh critiques with clear status. Examples: `requirements-critic`, `test-critic`, `code-critic`.

## Governance

### Selftest
The swarm's self-validation system. Runs 10+ steps across 3 tiers (KERNEL, GOVERNANCE, OPTIONAL) to verify the swarm is healthy.

### Tier
A classification of selftest steps by criticality:
- **KERNEL**: Core functionality (must pass)
- **GOVERNANCE**: Design constraints (should pass)
- **OPTIONAL**: Nice-to-haves (may fail without blocking)

### Degraded Mode
Running selftest with `--degraded` flag. KERNEL failures still fail; GOVERNANCE failures are logged but don't block. Used when accepting known issues.

### Degradation Log
File `selftest_degradations.log` at repo root. Records GOVERNANCE failures in degraded mode with timestamps, step IDs, and messages.

### Override
A temporary waiver for a specific selftest step. Managed via `make override-create`, `make override-revoke`, `make override-list`.

## Patterns

### Microloop
Adversarial iteration between writer and reviewer agents. Used in Flows 1 and 3. Loops until `Status: VERIFIED` or `can_further_iteration_help: no`.

### Receipt
A structured artifact documenting what an agent did, decisions made, and outcomes. Enables auditability. Example: `build_receipt.json`.

### Bounce-back
When Gate (Flow 4) rejects work and returns it to Build (Flow 3) or Plan (Flow 2). Only happens for non-mechanical issues.

### Mechanical Fix
A fix that requires no judgment: lint errors, format issues, missing docstrings, typos. Gate-fixer handles these. Logic/design issues bounce back.

## Artifacts

### Validator
Python tool (`swarm/tools/validate_swarm.py`) that enforces FR-001 through FR-005: bijection, frontmatter, flow references, skills, RUN_BASE paths.

### Flow Studio
Web UI for visualizing flows, agents, and run artifacts. Launched via `make flow-studio` at http://localhost:5000.

### Adapter
The generated `.claude/agents/*.md` file. Frontmatter is generated from `swarm/config/agents/*.yaml`; the adapter is the runtime binding.

## Status Values

### VERIFIED / UNVERIFIED
Status set by critics. VERIFIED means work meets requirements. UNVERIFIED means issues remain.

### can_further_iteration_help
Critic's judgment on whether another loop iteration could fix issues. `yes` = keep iterating; `no` = stop, issues are fundamental.

### PASS / FAIL / SKIP
Selftest step outcomes. PASS = success, FAIL = check failed, SKIP = step not applicable or disabled.
