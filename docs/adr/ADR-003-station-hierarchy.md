# ADR-003: Station/Template/Flow Hierarchy

**Status:** Proposed
**Date:** 2025-12-28
**Deciders:** Flow Studio Team

## Context

The Flow Studio swarm currently manages **53+ agents** across **7 flows** (Signal, Plan, Build, Review, Gate, Deploy, Wisdom). The current architecture has several pain points:

### Current State

1. **Dual definitions for each agent:**
   - `swarm/config/agents/*.yaml` - Simple adapter config (key, flows, model tier, color)
   - `.claude/agents/*.md` - Full prompt with frontmatter

2. **No explicit contracts:**
   - I/O dependencies are documented in prose, not machine-readable
   - Verification requirements scattered across prompts
   - Handoff protocols implicit, not enforced

3. **Duplication across similar agents:**
   - `test-author` and `code-implementer` share ~60% of their patterns
   - All critic agents (`requirements-critic`, `test-critic`, `code-critic`, `design-critic`) duplicate the microloop protocol
   - Cleanup agents across flows repeat the same archival pattern

4. **No capability reuse:**
   - An agent's capability (e.g., "write tests", "critique output", "run verification") cannot be shared
   - Adding a new flow requires re-implementing similar steps from scratch

### The Problem

As the swarm grows beyond 50 agents, we need:
- **Reusable capabilities** that can be composed into different contexts
- **Explicit contracts** that tooling can validate
- **A library of patterns** that reduce duplication
- **Clear composition** from capability to flow execution

## Decision

We adopt a **three-layer architecture** with a **phased rollout**:

### Layer 1: StationSpec (Capability Definition)

A `StationSpec` defines a **reusable execution capability** with explicit contracts.

```
swarm/spec/stations/<station-id>.yaml
```

**Structure** (from `swarm/spec/types.py`):
- `id`, `version`, `title`, `category` - Identity
- `sdk` - Model, tools, permissions, context budget
- `identity.system_append` - Core prompt (who am I)
- `io` - Required/optional inputs and outputs (machine-readable)
- `handoff` - Completion protocol (status, artifacts, required fields)
- `verify` - Verification requirements (artifacts, commands)
- `routing_hints` - Default behavior on verified/unverified/blocked
- `invariants` - Rules this station must follow

**Key properties:**
- Stations are **reusable** across flows
- Stations define **contracts**, not prose
- Stations are **versionable** (breaking changes increment version)

### Layer 2: StepTemplate (Reusable Pattern) - V2

A `StepTemplate` captures a **reusable step pattern** that combines a station with step-specific behavior.

```
swarm/spec/templates/<template-id>.yaml
```

**Structure:**
- `id`, `version`, `title`
- `station` - Reference to base StationSpec
- `sdk_overrides` - Step-specific tool/model adjustments
- `inputs`, `outputs` - Pattern-level I/O (relative paths)
- `routing` - Default routing behavior (linear, microloop, branch)
- `teaching` - Educational metadata for Flow Studio

**Examples:**
- `critic-microloop` - Shared pattern for all critic agents
- `cleanup-archival` - Shared pattern for flow cleanup steps
- `context-loading` - Heavy context loading pattern

### Layer 3: FlowSpec (Composition)

A `FlowSpec` **composes** stations (or templates) into an executable flow.

```
swarm/spec/flows/<flow-id>.yaml
```

**Structure** (from `swarm/spec/types.py`):
- `id`, `version`, `title`, `description`
- `defaults` - Flow-wide SDK overrides, context pack config
- `steps[]` - Sequence of FlowStep definitions
- `cross_cutting_stations` - Available throughout flow (e.g., clarifier)

**FlowStep structure:**
- `id`, `station` (or `template` in V2)
- `objective` - What this step accomplishes
- `inputs`, `outputs` - Step-specific I/O (overrides station defaults)
- `routing` - Step-specific routing (linear, microloop, branch, terminal)
- `sdk_overrides` - Step-specific adjustments
- `teaching` - Step-level educational notes

## Phased Approach

### V1: Station + Flow (Current Implementation)

Use **two layers only**: StationSpec directly referenced in FlowSpec.

```
FlowSpec.steps[].station -> StationSpec.id
```

**Rationale:**
- Simpler to implement and understand
- Templates can be extracted once patterns emerge naturally
- Avoids premature abstraction

**V1 deliverables:**
- 53 StationSpecs in `swarm/spec/stations/`
- 7 FlowSpecs in `swarm/spec/flows/`
- Compiler: `spec -> PromptPlan` for SDK execution
- Validator: Contract checking at flow boundaries

### V2: Station + Template + Flow (Future)

Add templates when **duplication becomes painful**:
- 3+ stations share >50% of their pattern
- Pattern changes require updating multiple stations
- New flow would benefit from existing step patterns

**V2 additions:**
- Template layer in `swarm/spec/templates/`
- FlowStep can reference `template` instead of `station`
- Template resolution: `station + template_overrides -> resolved_station`

## Alternatives Considered

### A. Flat Agent Definitions (Status Quo)

**Description:** Keep `.claude/agents/*.md` files with prose prompts and frontmatter.

**Pros:**
- Simple, human-readable
- Works today

**Cons:**
- No machine-readable contracts
- No reuse mechanism
- Duplication grows with agent count
- Validation requires parsing prose

**Rejected:** Does not scale beyond 50 agents; contracts remain implicit.

### B. Per-Flow Inline Definitions

**Description:** Define all agent behavior inline within each flow spec.

**Pros:**
- Everything in one place per flow
- No indirection

**Cons:**
- Massive duplication across flows (clarifier in 7 flows, cleanup in all flows)
- Changes require touching every flow
- No capability library

**Rejected:** Maximizes duplication; no reuse.

### C. Two-Layer Only (Station + Flow, No Templates)

**Description:** Skip templates entirely; stations directly in flows.

**Pros:**
- Simpler hierarchy
- Fewer concepts to learn

**Cons:**
- Patterns duplicated across stations
- Critic microloop defined 5 times
- Cleanup pattern defined 6+ times

**Considered and Adopted for V1:** This is the V1 approach. Templates are deferred until duplication pressure justifies them.

### D. Template-Only (No Stations)

**Description:** Templates contain all capability; no separate station layer.

**Pros:**
- Single reuse mechanism

**Cons:**
- Loses separation between "what I can do" (capability) and "how I'm used" (pattern)
- Templates become too large and inflexible
- Hard to version capabilities independently of usage patterns

**Rejected:** Conflates two distinct concerns.

## Consequences

### Positive

1. **Reusable capabilities:**
   - Define `code-critic` once, use in any flow needing code review
   - Cross-cutting stations (clarifier, risk-analyst) defined once

2. **Explicit contracts:**
   - `StationIO` makes dependencies machine-checkable
   - `StationHandoff` enforces completion protocol
   - Validator can catch broken flows before runtime

3. **Library of patterns (V2):**
   - `critic-microloop` template captures the adversarial pattern
   - New critic agents inherit the pattern, customize only what differs

4. **Composable flows:**
   - FlowSpec is just composition of stations/templates
   - Easy to create variant flows (e.g., "fast-gate" without security scan)

5. **Teaching clarity:**
   - Each layer has clear purpose: capability, pattern, composition
   - Flow Studio can visualize each layer

### Negative

1. **More files:**
   - 53 station specs + 7 flow specs = 60 files (vs ~50 agent files today)
   - V2 adds template files

2. **Indirection:**
   - Following `flow -> step -> station -> prompt` requires multiple hops
   - Tooling (spec compiler) must resolve the chain

3. **Migration effort:**
   - Existing agents must be converted to station specs
   - Flow specs must be created from current flow markdown

4. **Learning curve:**
   - Contributors must understand the hierarchy
   - Debugging requires knowing which layer owns what

### Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| Over-engineering for current scale | V1 uses only 2 layers; templates deferred |
| Breaking existing flows during migration | Gradual migration; dual-mode support |
| Spec drift from adapter implementations | Validator checks spec/adapter alignment |
| Templates become too abstract | Clear criteria: 3+ stations, >50% shared |

## Implementation Path

### Phase 1: V1 Foundation (In Progress)
1. Define `StationSpec` types in `swarm/spec/types.py` [DONE]
2. Create station specs for all 53 agents in `swarm/spec/stations/` [DONE]
3. Create flow specs in `swarm/spec/flows/`
4. Build spec compiler: `(station, flow, step) -> PromptPlan`
5. Build spec validator: Check contracts, detect breaks

### Phase 2: V1 Rollout
1. Migrate stepwise executor to use compiled PromptPlans
2. Validate existing example runs against spec contracts
3. Update Flow Studio to visualize spec structure

### Phase 3: V2 Templates (When Justified)
1. Identify 3+ stations sharing >50% pattern
2. Extract first templates (likely: critic-microloop, cleanup-archival)
3. Add template resolution to compiler
4. Update FlowSpec to support template references

## References

- `swarm/spec/types.py` - Type definitions for StationSpec, FlowSpec, PromptPlan
- `swarm/spec/stations/*.yaml` - 53 station specifications (V1 complete)
- `swarm/config/agents/*.yaml` - Current adapter configs (to be aligned)
- `swarm/flows/*.md` - Current flow documentation (source for FlowSpecs)
- `docs/STEPWISE_BACKENDS.md` - Stepwise execution that consumes PromptPlans

## Related ADRs

- ADR-001: Swarm Selftest Scope - Establishes validation patterns
- Future: ADR on spec versioning and breaking change policy
