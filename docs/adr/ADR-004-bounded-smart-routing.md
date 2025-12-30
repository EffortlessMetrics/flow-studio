# ADR-004: Bounded Smart Routing

**Status:** Proposed
**Date:** 2025-12-28
**Deciders:** Flow Studio Swarm Team

## Context

The orchestrator needs intelligent routing to handle complex flow execution scenarios:
- Microloops between author/critic agents with dynamic exit conditions
- Conditional branching based on step results (VERIFIED/UNVERIFIED)
- Detours for error recovery or prerequisite gathering
- Multi-flow transitions (macro-routing between flows)

The current implementation in `swarm/runtime/orchestrator.py` uses a hybrid approach:
- `StepRouting` configuration defines static edges (next step, loop targets, branch conditions)
- `RoutingSignal` and `HandoffEnvelope` carry runtime routing decisions
- Deterministic evaluation of `loop_condition_field` against `loop_success_values`

However, we face a fundamental tension:

1. **Hardcoded routing** is brittle: Every new edge case requires code changes
2. **Fully autonomous LLM routing** is unpredictable: Agents could route anywhere, breaking flow contracts
3. **Rule-based expert systems** hit combinatorial explosion: Complex condition trees become unmaintainable

We need **bounded flexibility**: intelligent routing that cannot escape the defined flow graph.

## Decision

We adopt **Graph-Constrained Routing with LLM Tie-Breaker**:

### 1. Graph Definition (Deterministic)

The flow graph defines all legal transitions. No routing decision can create an edge not in the graph:

```yaml
# In FlowSpec YAML
steps:
  - id: code-implementer
    station: code-implementer
    routing:
      kind: conditional
      next: code-critic  # default edge
      branches:
        VERIFIED: self-reviewer
        BLOCKED: context-loader
      conditions:
        - expr: "status == 'VERIFIED' && iteration >= 2"
          target: self-reviewer
```

### 2. Edge Conditions Using CEL (Not Custom DSL)

Edge conditions use [Common Expression Language (CEL)](https://github.com/google/cel-spec):

- Industry standard, well-documented, deterministic
- Supports boolean logic, comparisons, string operations
- Existing implementations in Python (`cel-python`), TypeScript, Go
- Security: No file I/O, network, or arbitrary code execution

Example conditions:
```cel
status == "VERIFIED"
iteration >= max_iterations
confidence < 0.7 && needs_human == false
receipt.test_coverage >= 80
```

### 3. Routing Evaluation Order

Routing decisions follow strict precedence:

1. **Check stop conditions**: Safety limits, explicit termination signals
2. **Evaluate CEL conditions**: Process in order until one matches
3. **Check hardcoded routing**: `routing.next`, `routing.loop_target` from config
4. **LLM tie-breaker**: Only invoked when multiple valid edges exist and no condition resolved

The LLM tie-breaker is constrained:
- Receives only the set of valid next steps from the graph
- Cannot propose steps outside the graph
- Must provide confidence score and reasoning
- If confidence < threshold (0.7), flags `needs_human: true`

### 4. Interruption Stack for Detours (Phased Rollout)

**Phase 1 (Current):** Single-level detours only
- Step can route to a "detour step" with automatic return
- Return address stored in `RoutingSignal.route` field
- No nested detours allowed

**Phase 2 (Future):** Full interruption stack
- Push/pop semantics for nested detours
- Maximum stack depth of 3 to prevent unbounded recursion
- Stack persisted in `RunState` for crash recovery

### 5. Failure Modes and Recovery

| Failure Mode | Detection | Recovery |
|--------------|-----------|----------|
| **Invalid step reference** | Graph validation at load time | Reject flow spec with error |
| **CEL evaluation error** | Try/catch in evaluator | Fall through to next condition or default edge |
| **LLM tie-breaker timeout** | 30s timeout per decision | Use default edge with `needs_human: true` |
| **LLM returns invalid step** | Validate against graph | Reject, use default edge, log warning |
| **Infinite loop detection** | Safety limit: `steps * 10` max | Abort run with `PARTIAL` status |
| **Stack overflow (Phase 2)** | Depth check before push | Reject detour, continue on current path |

Recovery follows the principle: **degrade to deterministic, never block**.

## Consequences

### Positive

- **Bounded flexibility**: LLM can only choose from graph-defined edges
- **Auditable decisions**: Every routing choice is logged with reason and confidence
- **Graceful degradation**: Failures fall back to deterministic paths
- **CEL portability**: Same conditions work across Python, TypeScript backends
- **Incremental adoption**: Existing flows work unchanged; smart routing opts-in per step

### Negative

- **Added complexity**: CEL evaluator adds a dependency
- **Testing burden**: Need to test condition evaluation, tie-breaker behavior
- **Performance overhead**: LLM tie-breaker adds latency (mitigated by deterministic fast-path)
- **CEL learning curve**: Authors need to learn CEL syntax

### Risks

| Risk | Mitigation |
|------|------------|
| CEL becomes a bottleneck | Profile and cache compiled expressions; most flows won't need complex conditions |
| LLM tie-breaker makes poor decisions | Confidence threshold triggers human review; log all decisions for post-hoc analysis |
| Graph constraints are too restrictive | Design review catches missing edges; always allow "escape hatch" to human review |
| Phase 2 stack implementation is complex | Defer until Phase 1 proves value; single-level detours handle most cases |

## Alternatives Considered

### A. Hardcoded Routing Only

**Description:** All routing logic in Python code, no dynamic evaluation.

**Pros:**
- Simple to understand and debug
- No external dependencies
- Fully deterministic

**Cons:**
- Every new routing pattern requires code changes
- Cannot adapt to runtime conditions without code deployment
- Microloop exit conditions become fragile receipt field parsing

**Rejected:** Too brittle for the complexity of 7-flow SDLC with microloops.

### B. Fully Autonomous LLM Routing

**Description:** LLM decides next step with full freedom, constrained only by prompts.

**Pros:**
- Maximum flexibility
- Can handle any edge case
- No upfront graph design needed

**Cons:**
- Unpredictable: LLM could skip critical steps or loop infinitely
- Unauditable: Reasoning is opaque
- Expensive: Every routing decision costs LLM tokens
- Unreliable: Model updates could change routing behavior

**Rejected:** Violates the swarm principle of auditable, reproducible execution.

### C. Rule-Based Expert System

**Description:** Comprehensive rule engine with forward/backward chaining.

**Pros:**
- Expressive, can model complex logic
- Deterministic once rules are defined
- Well-understood from enterprise systems

**Cons:**
- Rule explosion: N conditions * M states = O(N*M) rules to maintain
- Debugging nightmare: "Why did it route here?" requires rule trace
- Overkill: Most routing is simple; complex cases are rare

**Rejected:** Complexity disproportionate to the problem.

### D. Custom DSL for Conditions

**Description:** Define our own expression language for edge conditions.

**Pros:**
- Tailored to our needs
- No external dependency

**Cons:**
- Must design, document, implement, and maintain a language
- No tooling ecosystem (syntax highlighting, linting)
- Learning curve for something bespoke

**Rejected:** CEL already exists and does exactly what we need.

## Implementation Notes

### Type Updates (`swarm/runtime/types.py`)

```python
@dataclass
class RoutingSignal:
    decision: RoutingDecision
    next_step_id: Optional[str] = None
    route: Optional[str] = None  # Used for detour return address
    reason: str = ""
    confidence: float = 1.0
    needs_human: bool = False
    # ... existing fields

    # New fields for bounded smart routing
    evaluated_conditions: List[str] = field(default_factory=list)  # CEL exprs tried
    tie_breaker_used: bool = False  # Whether LLM was invoked
```

### FlowSpec Schema Extension

```yaml
steps:
  - id: code-implementer
    station: code-implementer
    routing:
      kind: conditional  # linear | conditional | branch | loop
      next: code-critic
      conditions:  # Evaluated in order, first match wins
        - expr: "status == 'VERIFIED'"
          target: self-reviewer
        - expr: "iteration >= 5"
          target: self-reviewer
          reason: "max_iterations_reached"
      branches:  # Legacy: simple key-value routing
        BLOCKED: context-loader
      loop_target: code-implementer  # For microloops
      tie_breaker:
        enabled: false  # Default off, opt-in per step
        valid_targets: [code-critic, self-reviewer]
        prompt_hint: "Choose based on code quality assessment"
```

### Integration Points

- **Orchestrator**: `_route()` method updated to evaluate CEL conditions
- **Storage**: `commit_step_completion()` already persists routing decisions
- **Events**: `route_decision` event includes `evaluated_conditions` and `tie_breaker_used`

## References

- `swarm/runtime/orchestrator.py` - Current routing implementation
- `swarm/runtime/types.py` - `RoutingSignal`, `HandoffEnvelope` definitions
- `swarm/config/flow_registry.py` - `StepRouting` configuration
- [CEL Specification](https://github.com/google/cel-spec) - Common Expression Language
- [cel-python](https://github.com/cloud-custodian/cel-python) - Python CEL implementation

## Related ADRs

- ADR-00001: Swarm Selftest vs Service Selftest (establishes layered validation pattern)
- (Future) ADR-005: Interruption Stack for Nested Detours
