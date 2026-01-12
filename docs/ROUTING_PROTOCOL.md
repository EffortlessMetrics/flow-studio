# Routing Protocol v3

This document defines the V3 routing contract for Flow Studio's graph-native execution model.

---

## 1. Overview

Flow Studio V3 introduces **graph-native routing** with the following properties:

- **Suggested Sidequests**: The system proposes detours and injections based on context, but the orchestrator decides
- **Open World Model**: Flows can go "off-road" when the golden path is insufficient—novel situations are expected, not exceptional
- **Always Spec'd and Logged**: Every routing decision produces artifacts; no silent deviations

The routing protocol treats flows as directed graphs where nodes can be injected, bypassed, or extended at runtime. This enables adaptive execution while maintaining auditability.

---

## 2. Routing Decisions

| Decision | Description | Use Case |
|----------|-------------|----------|
| **CONTINUE** | Proceed on golden path | Normal flow progression; no intervention needed |
| **DETOUR** | Inject sidequest chain | Common failure handling (lint fix, dep update) |
| **INJECT_FLOW** | Insert entire flow | Flow 3 calling Flow 8 rebase when upstream diverges |
| **INJECT_NODES** | Ad-hoc nodes | Novel requirements not covered by existing flows |
| **EXTEND_GRAPH** | Propose patch | Wisdom learns new pattern; suggests SOP evolution |

### Decision Hierarchy

1. **CONTINUE** is the default—prefer the golden path when viable
2. **DETOUR** for known failure patterns with established remediation
3. **INJECT_FLOW** when a complete flow exists for the situation
4. **INJECT_NODES** when no existing flow matches but nodes can be composed
5. **EXTEND_GRAPH** when a novel pattern warrants permanent graph evolution

---

## 3. Decision Schema

Every routing decision is logged with the following structure:

```json
{
  "decision": "INJECT_FLOW",
  "target": "flow-8-rebase",
  "justification": "Upstream commit contains required API",
  "evidence": ["gh-issue:1234", "commit:abcd1234"],
  "offroad": true,
  "suggestions_considered": ["lint-fix", "dependency-triage"],
  "timestamp": "2025-01-15T10:30:00Z",
  "source_node": "build.step-3",
  "stack_depth": 1
}
```

### Field Definitions

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `decision` | enum | Yes | One of: CONTINUE, DETOUR, INJECT_FLOW, INJECT_NODES, EXTEND_GRAPH |
| `target` | string | Conditional | Target flow/node(s); required for all except CONTINUE |
| `justification` | string | Yes | Human-readable explanation for the decision |
| `evidence` | array | Yes | Links to artifacts supporting the decision |
| `offroad` | boolean | Yes | Whether this deviates from the golden path |
| `suggestions_considered` | array | No | Alternative routes that were evaluated but not taken |
| `timestamp` | ISO 8601 | Yes | When the decision was made |
| `source_node` | string | Yes | The node where the decision was made |
| `stack_depth` | integer | Yes | Current depth in the graph stack (0 = root flow) |

### Why-Now Ticket (Structured Justification)

When a routing decision deviates from the golden path, it MUST include a `why_now` block:

```json
{
  "decision": "INJECT_FLOW",
  "target": "flow-8-rebase",
  "why_now": {
    "trigger": "Tests failed with 'Method Not Found'",
    "analysis": "Upstream introduced breaking change to Auth interface",
    "relevance_to_charter": "Cannot satisfy AC-2 without upstream fix",
    "alternatives_considered": ["skip AC-2", "mock the interface"],
    "expected_outcome": "After rebase, Auth interface available for implementation"
  }
}
```

This is **not a permission prompt**—it's a structured justification that:
1. Explains what triggered the deviation
2. Documents the analysis that led to the decision
3. Ties the decision back to the flow's charter goal
4. Records alternatives that were considered
5. States what the deviation is expected to accomplish

The `why_now` block becomes training data for Wisdom and enables forensic debugging of run behavior.

**Required fields:** `trigger`, `relevance_to_charter`
**Optional fields:** `analysis`, `alternatives_considered`, `expected_outcome`

---

## 4. The Blocking Dependency Test

Before making a routing decision, apply this test:

> **"Does this help achieve the objective?"**

| Answer | Blocking Without It? | Decision |
|--------|---------------------|----------|
| Yes | Yes | **INJECT** or **DETOUR** — required for progress |
| Yes | No | **SKIP** — beneficial but not essential |
| No | N/A | **IGNORE** — not relevant to objective |

### Examples

1. **Lint failure during build**
   - Helps achieve objective? Yes (clean build required)
   - Blocking without it? Yes (CI will fail)
   - Decision: **DETOUR** to lint-fix sidequest

2. **Upstream API changed**
   - Helps achieve objective? Yes (need the new API)
   - Blocking without it? Yes (code won't compile)
   - Decision: **INJECT_FLOW** to Flow 8 rebase

3. **Nice-to-have refactor suggested**
   - Helps achieve objective? Marginally
   - Blocking without it? No
   - Decision: **SKIP** — log for future consideration

4. **Unrelated issue discovered**
   - Helps achieve objective? No
   - Decision: **IGNORE** — create separate issue if needed

---

## 5. Flow Charters (Per-Flow Constitution)

Each flow has a **charter** that defines its purpose and constraints. The charter is injected into Navigator prompts to enforce contextual discipline and prevent scope creep.

### Charter Structure

```json
{
  "charter": {
    "goal": "Produces verified code that satisfies the AC Matrix",
    "question": "Does implementation match design?",
    "exit_criteria": [
      "All ACs marked PASS",
      "No new lint errors",
      "Build succeeds"
    ],
    "non_goals": [
      "Refactoring unrelated code",
      "Updating upstream dependencies (unless blocking)"
    ],
    "prime_directive": "Maximize passing tests. Minimize changes. Only detach from Golden Path if build is blocked."
  }
}
```

### Charter Fields

| Field | Purpose | Example |
|-------|---------|---------|
| `goal` | The single outcome this flow must achieve | "Produces verified code that satisfies the AC Matrix" |
| `question` | The question this flow answers | "Does implementation match design?" |
| `exit_criteria` | Conditions for successful completion | ["All ACs PASS", "Build succeeds"] |
| `non_goals` | Explicitly out-of-scope activities | ["Refactoring unrelated code"] |
| `prime_directive` | Navigator's constitution | "Maximize passing tests. Minimize changes." |

### How Charters Prevent Scope Creep

When the Navigator considers a routing decision:

1. **Check goal alignment**: "Does this help achieve the goal?"
2. **Check non-goals**: "Is this explicitly out of scope?"
3. **If yes to #2**: SKIP, log observation for Wisdom
4. **If no to #1 and not blocking**: SKIP, continue on golden path

### Prime Directives Summary

Each flow has a prime directive that guides routing decisions within that flow:

| Flow | Prime Directive | Constraints |
|------|-----------------|-------------|
| **Flow 1: Signal** | Maximize clarity, reduce ambiguity | Do not write code; focus on requirements |
| **Flow 2: Plan** | Maximize completeness of design artifacts | Do not implement; focus on contracts |
| **Flow 3: Build** | Maximize passing tests, minimize changes | Only detach if blocked by external factors |
| **Flow 4: Review** | Maximize issue resolution from feedback | Do not add unrequested features |
| **Flow 5: Gate** | Maximize confidence in merge safety | Do not fix; only recommend or bounce |
| **Flow 6: Deploy** | Maximize deployment reliability | Do not modify code; verify and report |
| **Flow 7: Wisdom** | Maximize learning extraction | Do not execute; observe and propose |
| **Flow 8: Rebase** | Maximize sync with upstream | Do not implement features; only integrate |

### Directive Conflicts

When routing decisions conflict with the prime directive:

1. Log the conflict explicitly
2. If blocking, escalate to parent flow for decision
3. If not blocking, prefer the prime directive
4. Always document the trade-off in the routing decision

---

## 6. Graph Stack Model

Flow injection creates a nested execution model:

```
┌─────────────────────────────────────────────┐
│ Flow 3: Build (root)                        │
│   ├── step-1: context-loader                │
│   ├── step-2: test-author                   │
│   ├── step-3: code-implementer              │
│   │     └── [BLOCKED: upstream diverged]    │
│   │         ┌─────────────────────────────┐ │
│   │         │ Flow 8: Rebase (injected)   │ │
│   │         │   ├── fetch-upstream        │ │
│   │         │   ├── merge-analysis        │ │
│   │         │   └── resolve-conflicts     │ │
│   │         └─────────────────────────────┘ │
│   ├── step-4: code-critic                   │
│   └── step-5: repo-operator                 │
└─────────────────────────────────────────────┘
```

### Stack Operations

| Operation | Trigger | Effect |
|-----------|---------|--------|
| **PUSH** | INJECT_FLOW or INJECT_NODES | New frame added; nested execution begins |
| **POP** | Injected flow completes | Frame removed; return to parent flow |
| **ABORT** | Injected flow fails critically | Unwind stack; propagate failure to root |

### Recursive Goal Inheritance

Injected flows inherit the goal context from their parent:

```json
{
  "root_goal": "Implement feature X per issue #1234",
  "stack": [
    {
      "flow": "build",
      "goal": "Create passing implementation",
      "step": "code-implementer"
    },
    {
      "flow": "rebase",
      "goal": "Sync with upstream to unblock build",
      "inherited_from": "build.code-implementer"
    }
  ]
}
```

### Stack Depth Limits

- **Default max depth**: 3 (configurable)
- **Exceeding depth**: Log warning, require explicit override
- **Infinite loop detection**: Track (flow, trigger) pairs; reject duplicates within same root execution

---

## 7. Off-Road Logging

All deviations from the golden path produce artifacts in `RUN_BASE/<flow>/routing/`:

### Event Types

| Event | Description | Artifact |
|-------|-------------|----------|
| `routing_offroad` | Any non-CONTINUE decision | `routing_decision.json` |
| `flow_injected` | INJECT_FLOW executed | `flow_injection.json` |
| `node_injected` | INJECT_NODES executed | `node_injection.json` |
| `graph_extended` | EXTEND_GRAPH proposed | `graph_extension_proposal.json` |

### Artifact Structure

```
RUN_BASE/<flow>/routing/
├── decisions.jsonl          # Append-only log of all routing decisions
├── injections/
│   ├── 001-flow-8-rebase.json
│   └── 002-lint-fix-sidequest.json
└── proposals/
    └── extend-build-flow-dep-check.json
```

### Wisdom Capture

Flow 7 (Wisdom) monitors routing logs across runs to:

1. **Identify patterns**: Common detours that should become golden path
2. **Propose SOP evolution**: EXTEND_GRAPH suggestions with evidence
3. **Track off-road frequency**: Flows with high deviation rates need design review
4. **Validate suggestions**: Compare suggested vs taken routes to tune heuristics

---

## 8. Observations (Wisdom Stream)

Stations emit **observations**—things noticed during execution that may not have been acted upon. This creates a shadow telemetry stream that flows to Wisdom for analysis.

### Observation Types

| Type | Description | Example |
|------|-------------|---------|
| `action_taken` | Logged for audit trail | "I chose to run EnvDoctor because npm install failed" |
| `action_deferred` | Noticed but didn't act (due to charter) | "I noticed the README is outdated, but I am in Flow 3 (Build), so I ignored it" |
| `optimization_opportunity` | Suggestion for spec evolution | "I spent 3 loops fixing a typo. We should add a TypoFixer step to Flow 1" |
| `pattern_detected` | Recurring behavior worth codifying | "Every build requires lint-fix first. Consider making it a standard step" |

### Observation Schema

```json
{
  "observations": [
    {
      "type": "action_deferred",
      "observation": "README.md is outdated (refers to v1.0 API)",
      "reason": "I am in Flow 3 (Build); documentation is not in scope per charter",
      "suggested_action": "Create issue for documentation update",
      "target_flow": "wisdom",
      "priority": "low"
    },
    {
      "type": "optimization_opportunity",
      "observation": "Lint errors on every first iteration of code-implementer",
      "reason": "auto-linter could run before code-critic to reduce loop count",
      "suggested_action": "Add auto-linter step before first critique",
      "target_flow": "build",
      "priority": "medium"
    }
  ]
}
```

### How Wisdom Processes Observations

1. **Collect**: Observations flow to `RUN_BASE/wisdom/observations.jsonl`
2. **Aggregate**: Group by type, target_flow, and observation pattern
3. **Analyze**: High-frequency patterns become candidates for spec changes
4. **Propose**: EXTEND_GRAPH proposals are generated for validated patterns
5. **Report**: Human-readable summary in `RUN_BASE/wisdom/learnings.md`

### Observation vs Concern

| Concept | Scope | Action |
|---------|-------|--------|
| **Observation** | Cross-flow, cross-run learning | Deferred to Wisdom for analysis |
| **Concern** | Current execution, current step | Documented in handoff, may affect routing |

Observations are for **organizational learning**. Concerns are for **immediate execution decisions**.

### Retention Policy

- **Decisions**: Retained for 30 days or 100 runs (whichever is longer)
- **Injection artifacts**: Retained with their parent run
- **Extension proposals**: Retained until accepted, rejected, or superseded

---

## 9. Navigator Context Model

The Navigator operates with **full graph visibility**—it sees the entire execution topology, not just the immediate next step.

### Full Graph Injection

Python injects the complete `FlowGraph.json` into the Navigator's context at each routing decision point. The graph is small token-wise (~1-2k tokens) but provides massive reasoning benefit:

```json
{
  "graph": {
    "nodes": [...],
    "edges": [...],
    "current_node": "build.step-3",
    "traversed_path": ["build.step-1", "build.step-2", "build.step-3"],
    "available_detours": ["lint-fix", "env-doctor", "dep-update"],
    "resume_stack": []
  }
}
```

The trade-off is asymmetric: 1-2k tokens of graph context enables routing decisions that would otherwise require 10-20k tokens of situational re-discovery.

### Annotation Layer

Python enriches the raw graph with execution state before injection:

| Annotation | Description | Example |
|------------|-------------|---------|
| `current_node` | Where we are now | `"build.step-3"` |
| `traversed_path` | Breadcrumbs of nodes already visited | `["build.step-1", "build.step-2"]` |
| `available_detours` | Library nodes that can be injected | `["lint-fix", "env-doctor"]` |
| `resume_stack` | Paused nodes waiting to resume after injection | `["build.step-3"]` |

These annotations are computed by Python at runtime—the Navigator never needs to reconstruct execution history from artifacts.

### Why This Matters

The Navigator sees the whole board, not just the immediate next step. It can reason about:

- **Topology of work**: How nodes connect, what depends on what
- **Where we came from**: The traversed path provides context for current decisions
- **What's ahead**: Remaining nodes inform whether a detour is worth the cost
- **What optional paths exist**: Available detours are pre-computed, not discovered

This enables strategic routing decisions that account for downstream consequences.

### The General with a Map

Think of the Navigator as a **general with a full battle map**, not a soldier who only sees their immediate surroundings.

A soldier asks: "What's in front of me?"
A general asks: "What's the state of the entire field?"

| Soldier View | General View |
|--------------|--------------|
| Current node only | Full graph topology |
| No history context | Complete traversal path |
| Discovers options reactively | Pre-computed available detours |
| Optimizes locally | Optimizes for objective completion |

The Navigator operates at the general's level. It can say: "Yes, we could detour here, but looking at the graph, that issue will be caught by the gate flow anyway—CONTINUE."

Without the full graph, the Navigator would make myopic decisions based only on immediate context, leading to unnecessary detours or missed opportunities.

---

## 10. Semantic Forensics

Raw diffs are metadata, not information. The Navigator never reads raw diffs—it reads semantic summaries produced by the Forensic Analyst.

### The Problem with Raw Diffs

```diff
+50/-10 lines changed in src/auth/handler.py
```

This tells you nothing useful for routing decisions:
- What changed semantically?
- Is this a breaking change or a refactor?
- Does this affect downstream flows?
- Should we trigger additional validation?

Line counts are **noise**. The Navigator needs **signal**.

### Forensic Analyst Translation

The Forensic Analyst translates diffs into semantic summaries:

| Raw Diff | Semantic Summary |
|----------|------------------|
| `+50/-10 in handler.py` | "Added rate limiting to auth endpoint. New dependency on redis client." |
| `+200/-0 in tests/` | "Added integration tests for payment flow. No production code changed." |
| `+5/-5 in config.yaml` | "Changed timeout from 30s to 60s. May affect downstream retry logic." |

### What the Navigator Sees

The Navigator receives pre-digested summaries:

```json
{
  "semantic_changes": [
    {
      "scope": "auth/handler.py",
      "summary": "Added rate limiting middleware",
      "impact": "New redis dependency; may require env-doctor",
      "risk_level": "medium",
      "affected_flows": ["build", "gate"]
    }
  ]
}
```

This is actionable. The Navigator can now ask:
- "Does this require a detour to env-doctor?" (yes, new dependency)
- "Should we inject additional validation?" (medium risk suggests yes)
- "Which downstream flows need to know?" (gate should see this)

### Why Semantic > Syntactic

| Metric | Syntactic (Line Count) | Semantic (Summary) |
|--------|----------------------|-------------------|
| Token cost | Low | Medium |
| Reasoning value | Near zero | High |
| Routing utility | None | Direct |
| False positive rate | High | Low |

A 1000-line refactor with zero semantic change should not trigger any routing decision. A 5-line security fix should trigger gate escalation. Line counts cannot distinguish these cases; semantic summaries can.

### Forensic Analyst Placement

The Forensic Analyst runs:
1. **Before routing decisions**: To inform CONTINUE vs DETOUR
2. **At handoff boundaries**: To summarize what changed for the next step
3. **Before Wisdom**: To provide high-quality input for pattern detection

The Navigator trusts the Forensic Analyst's summaries. It does not second-guess by requesting raw diffs.

---

## 11. Utility Flows vs Main Flows

The SDLC consists of **main flows** (1-7) that form the autopilot sequence, plus **utility flows** that are injected on-demand via INJECT_FLOW routing decisions.

### Main Flows (Autopilot Sequence)

| Flow | Name | Description |
|------|------|-------------|
| 1 | Signal | Raw input to problem statement, requirements, BDD |
| 2 | Plan | Requirements to ADR, contracts, test/work plans |
| 3 | Build | Implement via adversarial microloops |
| 4 | Review | Harvest PR feedback, apply fixes |
| 5 | Gate | Pre-merge gate, audit receipts, recommend merge/bounce |
| 6 | Deploy | Execute deployment, verify health |
| 7 | Wisdom | Analyze artifacts, extract learnings |

Main flows are defined in `flows.yaml` and execute sequentially. Each flow's `on_complete` transitions to the next flow in sequence.

### Utility Flows (Injected On-Demand)

| Flow | Trigger | Purpose |
|------|---------|---------|
| Flow 8: Reset | `upstream_diverged` | Branch synchronization, rebase, run archiving |

Utility flows are **NOT** part of the autopilot sequence. They are:
- Defined as `*.graph.json` files in `swarm/spec/flows/`
- Marked with `is_utility_flow: true` in metadata
- Have an `injection_trigger` field documenting when to inject
- Return to the caller via `on_complete.next_flow: "return"`

### Utility Flow Schema Markers

Utility flows use these metadata fields:

```json
{
  "metadata": {
    "is_utility_flow": true,
    "injection_trigger": "upstream_diverged",
    "tags": ["reset", "git", "cleanup", "utility"]
  },
  "on_complete": {
    "next_flow": "return",
    "reason": "Reset complete; return to interrupted flow",
    "pass_artifacts": ["reset/git_status.md", "reset/sync_report.md"]
  }
}
```

### How Utility Flows Are Invoked

1. **Trigger detection**: A station or navigator detects a condition matching `injection_trigger`
2. **INJECT_FLOW decision**: The navigator issues an INJECT_FLOW routing decision
3. **Stack push**: The utility flow is pushed onto the graph stack
4. **Execution**: The utility flow runs to completion
5. **Stack pop**: On completion, control returns to the interrupted flow

Example: During Flow 3 (Build), `code-implementer` detects that upstream has diverged:

```json
{
  "decision": "INJECT_FLOW",
  "target": "reset-flow",
  "why_now": {
    "trigger": "git fetch shows origin/main is 15 commits ahead",
    "relevance_to_charter": "Cannot verify code against stale baseline",
    "expected_outcome": "After reset, work branch synchronized with upstream"
  }
}
```

### Why Separate Main and Utility Flows?

1. **Autopilot clarity**: Main flows form a predictable 1-7 sequence; utility flows don't clutter it
2. **Conditional execution**: Utility flows only run when conditions match
3. **Return semantics**: Utility flows return to their caller, not advance to the next flow
4. **Catalog management**: Utility flows can be added without changing the main flow sequence

---

## 12. Routing Implementation Surface

This section documents the implementation details for developers extending the routing subsystem.

### Canonical Import

```python
from swarm.runtime.stepwise.routing import route_step, RoutingOutcome
from swarm.runtime.types import RoutingMode, RoutingDecision, RoutingCandidate
```

**Deprecated:** `route_step_unified` is an alias for backwards compatibility. Use `route_step` directly.

### RoutingOutcome vs RoutingSignal

The routing system uses two types for routing results:

| Type | Status | Use Case |
|------|--------|----------|
| `RoutingOutcome` | **Canonical** | New code, full audit trail |
| `RoutingSignal` | Legacy | Step envelope fallback |

`RoutingOutcome` includes all audit fields (`routing_source`, `candidates`, `timestamp`). Use `RoutingOutcome.from_signal()` to convert legacy signals.

### RoutingMode Enum

Controls the balance between deterministic and Navigator-based routing:

```python
class RoutingMode(str, Enum):
    DETERMINISTIC_ONLY = "deterministic_only"  # No LLM calls; CI/debugging
    ASSIST = "assist"                          # Default; Navigator for complex cases
    AUTHORITATIVE = "authoritative"            # Navigator has more latitude
```

- **DETERMINISTIC_ONLY**: Fast-path handles all routing. No Navigator calls. Use for CI and reproducibility.
- **ASSIST**: Fast-path for obvious cases, Navigator for complex routing. Python can override via hard gates.
- **AUTHORITATIVE**: Navigator can propose EXTEND_GRAPH and detours more freely.

### Priority-Based Routing Strategy

The routing driver (`driver.py`) follows this fallback chain:

1. **Fast-path**: Terminal steps, explicit `next_step_id`, single outgoing edge
2. **Deterministic**: CEL evaluation, deterministic graph rules
3. **Navigator**: LLM-based routing for complex decisions (ASSIST/AUTHORITATIVE modes)
4. **Envelope fallback**: Legacy `RoutingSignal` from step finalization
5. **Escalate**: Default behavior when nothing else works

Each stage sets `routing_source` appropriately.

### `routing_source` Values

The `routing_source` field in `RoutingOutcome` documents how the decision was made:

| Value | Description |
|-------|-------------|
| `fast_path` | Obvious deterministic case (terminal step, single edge) |
| `deterministic` | CEL evaluation or deterministic graph traversal |
| `navigator` | Navigator chose from candidates |
| `navigator:detour` | Navigator chose a detour/sidequest |
| `navigator:extend_graph` | Navigator proposed graph extension |
| `envelope_fallback` | Legacy RoutingSignal from step output |
| `escalate` | Last resort fallback |

### Terminology Mapping

Documentation uses conceptual terms that map to code enums:

| Docs Term | Code Enum Value |
|-----------|-----------------|
| CONTINUE | `RoutingDecision.ADVANCE` |
| DETOUR | `RoutingDecision.BRANCH` |
| LOOP | `RoutingDecision.LOOP` |
| TERMINATE | `RoutingDecision.TERMINATE` |

### API Reference

See [ROUTING_API.md](./ROUTING_API.md) for the complete code-facing API reference.

---

## Appendix: Integration with Existing Systems

### Stepwise Backends

Routing decisions integrate with stepwise execution:

- Each routing decision is a potential step boundary
- INJECT_FLOW creates a sub-orchestration context
- Transcripts include routing decision metadata

### Selftest Validation

Routing behavior is validated by:

- `test_routing_decision_schema`: Validates decision JSON structure
- `test_blocking_dependency_logic`: Validates the blocking test
- `test_stack_depth_limits`: Validates recursion guards

### Flow Studio UI

Routing decisions are visualized in Flow Studio:

- Off-road paths shown with distinct styling
- Injection points marked on the graph
- Stack depth shown in execution trace
