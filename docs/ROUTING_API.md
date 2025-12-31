# Routing API Reference

> For: Developers extending or debugging the routing subsystem.
>
> **Prerequisites:** [ROUTING_PROTOCOL.md](./ROUTING_PROTOCOL.md) | **Related:** [STEPWISE_CONTRACT.md](./STEPWISE_CONTRACT.md)

---

This document provides the code-facing API reference for the routing subsystem. For conceptual understanding, see ROUTING_PROTOCOL.md.

## Canonical Import

```python
from swarm.runtime.stepwise.routing import route_step, RoutingOutcome
from swarm.runtime.types import RoutingMode, RoutingDecision, RoutingCandidate
```

**Deprecated aliases** (for backwards compatibility only):
- `route_step_unified` → Use `route_step` instead
- `route_step_legacy` → Legacy signature, avoid in new code

---

## Core Function: `route_step()`

The single entry point for all routing decisions in stepwise orchestration.

```python
def route_step(
    *,
    step: StepDefinition,
    step_result: Any,  # StepResult dict or object
    run_state: RunState,
    loop_state: Dict[str, int],
    iteration: int,
    routing_mode: RoutingMode,
    # Optional Navigator parameters (required for ASSIST/AUTHORITATIVE modes)
    run_id: Optional[str] = None,
    flow_key: Optional[str] = None,
    flow_graph: Optional[FlowGraph] = None,
    flow_def: Optional[FlowDefinition] = None,
    spec: Optional[RunSpec] = None,
    run_base: Optional[Path] = None,
    navigation_orchestrator: Optional[Any] = None,
) -> RoutingOutcome:
    """Determine the next step after execution.

    Implements priority-based routing strategy:
    1. Fast-path (obvious deterministic cases)
    2. Deterministic fallback (if routing_mode == DETERMINISTIC_ONLY)
    3. Navigator (if available, for ASSIST/AUTHORITATIVE modes)
    4. Envelope fallback (legacy RoutingSignal from step finalization)
    5. Escalate (if nothing else works)

    Args:
        step: The step definition that just executed.
        step_result: The execution result (StepResult dict/object with status).
        run_state: Current run state with cursor position.
        loop_state: Dict mapping step_id to iteration count.
        iteration: Current iteration count for this step.
        routing_mode: Controls Navigator behavior (see RoutingMode).
        run_id: Run identifier (for navigator context).
        flow_key: Flow being executed (for navigator context).
        flow_graph: Flow graph for topology-aware routing.
        flow_def: Flow definition with step specs.
        spec: RunSpec with execution settings.
        run_base: Path to run artifacts directory.
        navigation_orchestrator: Navigator instance for LLM routing.

    Returns:
        RoutingOutcome with decision, next_step_id, and audit trail.
    """
```

**Note:** All parameters are keyword-only (`*`). The optional Navigator parameters are required for ASSIST/AUTHORITATIVE modes to enable LLM-based routing.

---

## RoutingOutcome

The result of a routing decision with full audit information.

```python
@dataclass
class RoutingOutcome:
    decision: RoutingDecision        # ADVANCE, LOOP, TERMINATE, BRANCH, SKIP
    next_step_id: Optional[str]      # ID of next step, or None if terminating
    reason: str                      # Human-readable explanation
    confidence: float                # 0.0 to 1.0
    needs_human: bool                # Whether human intervention required
    routing_source: str              # How decision was made (see below)
    chosen_candidate_id: Optional[str]  # ID of chosen candidate
    candidates: List[RoutingCandidate]  # Evaluated candidates
    loop_iteration: int              # Current loop iteration count
    exit_condition_met: bool         # Whether exit condition satisfied
    timestamp: datetime              # When decision was made
    signal: Optional[RoutingSignal]  # Underlying signal (if available)
```

### `routing_source` Values

The `routing_source` field documents how the routing decision was made:

| Value | Description |
|-------|-------------|
| `fast_path` | Obvious deterministic case (terminal step, single edge, explicit next_step_id) |
| `deterministic` | CEL evaluation or deterministic graph traversal |
| `navigator` | Navigator chose from candidates |
| `navigator:detour` | Navigator chose a detour/sidequest |
| `navigator:extend_graph` | Navigator proposed graph extension |
| `envelope_fallback` | Legacy RoutingSignal from step finalization |
| `escalate` | Last resort, no other strategy worked |

### Methods

```python
# Convert to dictionary for JSON serialization
outcome.to_dict() -> Dict[str, Any]

# Convert to event payload for route_decision events
outcome.to_event_payload() -> Dict[str, Any]

# Create from legacy RoutingSignal
RoutingOutcome.from_signal(signal, routing_source="signal") -> RoutingOutcome
```

---

## RoutingMode

Controls the balance between deterministic and Navigator-based routing.

```python
class RoutingMode(str, Enum):
    DETERMINISTIC_ONLY = "deterministic_only"
    ASSIST = "assist"
    AUTHORITATIVE = "authoritative"
```

| Mode | Navigator Calls | Use Case |
|------|-----------------|----------|
| `DETERMINISTIC_ONLY` | Never | CI, debugging, reproducibility |
| `ASSIST` (default) | For complex routing | Normal execution |
| `AUTHORITATIVE` | More latitude | Allow EXTEND_GRAPH proposals |

---

## RoutingDecision

The routing decision types.

```python
class RoutingDecision(str, Enum):
    ADVANCE = "advance"      # Move to next step
    LOOP = "loop"            # Loop back to target step
    TERMINATE = "terminate"  # Flow complete
    BRANCH = "branch"        # Take a branch/detour
    SKIP = "skip"            # Skip step, move to next
```

**Note:** Documentation may use "CONTINUE" which maps to `ADVANCE` in code.

---

## RoutingCandidate

A potential routing option for the Navigator to evaluate.

```python
@dataclass
class RoutingCandidate:
    candidate_id: str           # Unique identifier
    action: str                 # "advance", "loop", "detour", etc.
    target_node: str            # Target step ID
    reason: str                 # Why this candidate exists
    priority: int               # Ordering preference (lower = higher priority)
    source: str                 # Where this candidate came from
    evidence_pointers: List[str]  # References to supporting evidence
    is_default: bool            # Whether this is the default/golden-path option
```

---

## Usage Example

```python
from swarm.runtime.stepwise.routing import route_step, RoutingOutcome
from swarm.runtime.types import RoutingMode

# After step execution
outcome = route_step(
    step=current_step,
    step_result=result,
    run_state=state,
    loop_state=loops,
    iteration=iter_count,
    routing_mode=RoutingMode.ASSIST,
)

# Check the result
if outcome.decision == RoutingDecision.TERMINATE:
    print("Flow complete")
elif outcome.decision == RoutingDecision.LOOP:
    print(f"Looping back, iteration {outcome.loop_iteration}")
else:
    print(f"Advancing to {outcome.next_step_id}")

# Emit routing event
event_payload = outcome.to_event_payload()
emit_event("route_decision", payload=event_payload)
```

---

## Priority-Based Routing Strategy

The routing driver follows this fallback chain:

1. **Fast-path**: Terminal steps, explicit next_step_id, single outgoing edge
2. **Deterministic**: CEL evaluation, deterministic graph rules
3. **Navigator**: LLM-based routing for complex decisions
4. **Envelope fallback**: Legacy RoutingSignal from step output
5. **Escalate**: Default behavior when nothing else works

Each stage sets `routing_source` appropriately for audit trail.

---

## See Also

- [ROUTING_PROTOCOL.md](./ROUTING_PROTOCOL.md) — Conceptual routing model
- [STEPWISE_CONTRACT.md](./STEPWISE_CONTRACT.md) — Behavioral contract
- `swarm/runtime/stepwise/routing/driver.py` — Implementation
- `swarm/runtime/types/` — Type definitions package
