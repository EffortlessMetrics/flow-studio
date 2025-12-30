# Spec-First Architecture

This directory contains the machine-readable specifications that drive stepwise execution. The spec is the source of truth - prompts and SDK options are compiled from these specs, not hand-written.

## Philosophy

**The spec is the contract.** Everything else is derived:
- Station prompts are compiled from spec + fragments
- SDK options come from station YAML, not .claude filesystem
- Routing logic is declarative, not imperative
- Changes to behavior require changes to spec

## Directory Structure

```
swarm/spec/
+-- README.md              # This file
+-- types.py               # Python dataclasses for specs
+-- loader.py              # YAML loading and validation
+-- compiler.py            # Spec to PromptPlan compilation
|
+-- schemas/               # JSON Schema for validation
|   +-- station.schema.json
|   +-- flow.schema.json
|
+-- stations/              # Station specifications (YAML)
|   +-- code-implementer.yaml
|   +-- test-author.yaml
|   +-- ...
|
+-- flows/                 # Flow specifications (YAML)
|   +-- 1-signal.yaml
|   +-- 2-plan.yaml
|   +-- 3-build.yaml
|   +-- 4-gate.yaml
|   +-- 5-deploy.yaml
|   +-- 6-wisdom.yaml
|
+-- fragments/             # Reusable prompt fragments
    +-- common/            # Cross-cutting fragments
    |   +-- invariants.md  # Behavioral invariants
    |   +-- evidence.md    # Evidence and receipt patterns
    |   +-- handoff.md     # Handoff contract patterns
    |   +-- preflight.md   # Preflight check pattern
    |   +-- lane_discipline.md  # Lane discipline rules
    |
    +-- flow/              # Flow-specific fragments (empty for now)
```

## Key Concepts

### Stations

A **station** is a reusable execution role. It defines:
- **Identity**: Who am I? (system prompt append)
- **SDK Config**: What tools/model do I use?
- **IO Contract**: What do I read/write?
- **Handoff Contract**: How do I signal completion?
- **Invariants**: What rules must I follow?

Stations are like job descriptions. They don't know about specific flows.

### Flows

A **flow** is an orchestration spine. It defines:
- **Steps**: Sequence of station invocations
- **Routing**: How steps connect (linear, microloop, branch)
- **Overrides**: Step-specific customizations

Flows are like project plans. They compose stations into workflows.

### Fragments

**Fragments** are reusable markdown chunks included in prompts:
- `common/invariants.md` - Rules that apply to every station
- `common/evidence.md` - Evidence and status patterns
- `common/handoff.md` - Handoff structure and fields
- `common/preflight.md` - Input validation pattern
- `common/lane_discipline.md` - Scope boundaries

Fragments are included via the `runtime_prompt.fragments` field.

## How It Works

### Compilation Flow

```
Station YAML + Flow YAML + Fragments
            |
            v
        compiler.py
            |
            v
       PromptPlan
            |
            v
    Claude SDK Call
```

The compiler:
1. Loads station spec
2. Loads flow spec and finds the step
3. Merges step overrides onto station
4. Loads and concatenates fragments
5. Renders the prompt template
6. Produces a PromptPlan with all SDK options

### Example Station Spec

```yaml
id: code-implementer
version: 1
title: Implement Scoped Changes
category: implementation

sdk:
  model: sonnet
  permission_mode: bypassPermissions
  allowed_tools: [Read, Write, Edit, Bash, Grep, Glob]
  max_turns: 15

identity:
  system_append: |
    You are the Code Implementer.
    Your job is to write production code that passes tests.
  tone: neutral

io:
  required_inputs:
    - plan/adr.md
    - plan/api_contracts.yaml
  required_outputs:
    - build/impl_changes_summary.md

runtime_prompt:
  fragments:
    - common/invariants.md
    - common/evidence.md
  template: |
    ## Implementation Approach
    1. Read the ADR...

invariants:
  - "Run tests before claiming VERIFIED"
  - "Never delete tests to make them pass"
```

### Example Flow Spec

```yaml
id: build
version: 1
title: Flow 3 - Build

steps:
  - id: implement
    station: code-implementer
    objective: Write code that passes tests
    inputs:
      - plan/adr.md
    outputs:
      - build/impl_changes_summary.md
    routing:
      kind: microloop
      loop_target: critique_code
      loop_condition_field: status
      loop_success_values: [VERIFIED]
```

## Fragment Reference

### invariants.md

Core behavioral rules:
- Evidence first (claims require artifacts)
- No fabrication (never invent results)
- No reward hacking (no deleting tests)
- Bounded work (stay in scope)
- No git ops except repo-operator
- Safe Bash only
- Document assumptions explicitly

### evidence.md

Evidence and receipt patterns:
- Status model (VERIFIED / UNVERIFIED / PARTIAL / BLOCKED)
- Evidence binding rules
- Receipt structure
- Metric consistency checks

### handoff.md

Handoff contract patterns:
- Required fields (status, summary, artifacts, confidence, can_further_iteration_help)
- Status meanings and next actions
- Iteration control logic
- Loop exit conditions

### preflight.md

Preflight check pattern:
- Required input validation
- Context validation
- State validation (previous work)
- Preflight outcomes

### lane_discipline.md

Lane discipline rules:
- No drive-by refactoring
- No weaker tests
- No scope creep
- No role confusion
- Boundaries by station category

## Extending the System

### Adding a New Station

1. Create `swarm/spec/stations/<station-id>.yaml`
2. Define all required fields (id, version, title, category, sdk, identity, io, etc.)
3. Reference appropriate fragments in `runtime_prompt.fragments`
4. Add station to relevant flow specs

### Adding a New Fragment

1. Create `swarm/spec/fragments/common/<name>.md` or `swarm/spec/fragments/flow/<name>.md`
2. Write the reusable content
3. Reference it in station specs via `runtime_prompt.fragments`

### Adding a New Flow

1. Create `swarm/spec/flows/<n>-<name>.yaml`
2. Define steps with station references
3. Configure routing for each step
4. Register cross-cutting stations if needed

## Validation

Use the loader to validate specs:

```python
from swarm.spec.loader import load_station, load_flow

# Load and validate a station
station = load_station("code-implementer")

# Load and validate a flow
flow = load_flow("3-build")
```

Schema validation is provided by `schemas/station.schema.json` and `schemas/flow.schema.json`.
