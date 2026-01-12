# Off-Road Logging: Routing Decision Audit Trail

When flows deviate from the golden path, every decision is logged. This is the audit trail for V3 routing.

## Why Off-Road Logging

The golden path (CONTINUE at every step) needs no special logging.
But when routing goes "off-road":
- LOOP (iterate again)
- DETOUR (known fix pattern)
- INJECT_FLOW (insert another flow)
- INJECT_NODES (ad-hoc steps)
- ESCALATE (human needed)

...every decision must be traceable.

## Artifact Locations

```
RUN_BASE/<flow>/routing/
├── decisions.jsonl          # Append-only decision log
├── injections/              # Flow/node injection records
│   ├── flow-8-inject-001.json
│   └── nodes-ad-hoc-001.json
└── proposals/               # Graph extension proposals (from Wisdom)
    └── extend-001.json
```

## Decision Log Schema

`decisions.jsonl` - Append-only, one JSON object per line:

```json
{
  "timestamp": "2024-01-15T10:30:00Z",
  "run_id": "abc123",
  "flow_key": "build",
  "step_id": "step-3",
  "agent_key": "code-implementer",
  "decision": "DETOUR",
  "detour_target": "auto-linter",
  "reason": "5 fixable lint errors detected",
  "forensic_summary": {
    "tests": { "passed": 42, "failed": 0 },
    "lint": { "errors": 5, "fixable": 5 }
  },
  "iteration": {
    "current": 2,
    "max": 3
  },
  "signature_matched": "lint_errors",
  "confidence": "HIGH"
}
```

### Required Fields

| Field | Type | Description |
|-------|------|-------------|
| `timestamp` | ISO8601 | When decision was made |
| `run_id` | string | Run identifier |
| `flow_key` | string | Current flow |
| `step_id` | string | Current step |
| `decision` | enum | CONTINUE, LOOP, DETOUR, INJECT_FLOW, INJECT_NODES, ESCALATE, TERMINATE |
| `reason` | string | Human-readable justification |

### Optional Fields

| Field | Type | Description |
|-------|------|-------------|
| `agent_key` | string | Agent that completed the step |
| `detour_target` | string | Target for DETOUR decisions |
| `injected_flow` | string | Flow key for INJECT_FLOW |
| `injected_nodes` | array | Node specs for INJECT_NODES |
| `forensic_summary` | object | Compact forensics that informed decision |
| `iteration` | object | Microloop state |
| `signature_matched` | string | Known failure signature if matched |
| `confidence` | enum | HIGH, MEDIUM, LOW |

## Flow Injection Record

`injections/flow-<id>.json`:

```json
{
  "injection_id": "flow-8-inject-001",
  "timestamp": "2024-01-15T10:30:00Z",
  "injected_at": {
    "flow_key": "build",
    "step_id": "step-3",
    "after_iteration": 2
  },
  "injected_flow": "reset",
  "reason": "Upstream diverged by 15 commits",
  "trigger": {
    "type": "upstream_divergence",
    "behind_by": 15,
    "conflicts_likely": true
  },
  "return_to": {
    "flow_key": "build",
    "step_id": "step-3"
  },
  "status": "completed",
  "completed_at": "2024-01-15T10:35:00Z"
}
```

## Node Injection Record

`injections/nodes-<id>.json`:

```json
{
  "injection_id": "nodes-ad-hoc-001",
  "timestamp": "2024-01-15T10:30:00Z",
  "injected_at": {
    "flow_key": "build",
    "step_id": "step-3"
  },
  "nodes": [
    {
      "id": "ad-hoc-1",
      "agent": "dependency-resolver",
      "purpose": "Resolve missing dependency",
      "inputs": ["requirements.txt"],
      "outputs": ["requirements.txt (updated)"]
    }
  ],
  "reason": "ModuleNotFoundError: requests",
  "goal_alignment": "Unblocks implementation step",
  "status": "completed"
}
```

## Graph Extension Proposal

`proposals/extend-<id>.json` (from Wisdom flow):

```json
{
  "proposal_id": "extend-001",
  "timestamp": "2024-01-15T10:30:00Z",
  "proposed_by": "wisdom-analyst",
  "pattern_observed": {
    "description": "Lint errors frequently cause DETOUR",
    "frequency": "15 of last 20 runs",
    "evidence_runs": ["run-001", "run-002", "..."]
  },
  "proposed_change": {
    "type": "add_step",
    "flow": "build",
    "after_step": "step-2",
    "new_step": {
      "id": "step-2b",
      "agent": "auto-linter",
      "purpose": "Pre-emptive lint fix"
    }
  },
  "rationale": "Running linter before code-critic reduces DETOUR rate",
  "status": "pending_review",
  "reviewed_by": null,
  "decision": null
}
```

## Logging Rules

### Always Log
- All non-CONTINUE decisions
- All flow injections
- All node injections
- All escalations

### Never Log
- CONTINUE decisions on golden path (implicit)
- Internal step mechanics
- Agent thinking/reasoning

### Log Format
- JSONL for decisions (append-only, streamable)
- JSON for injection records (complete objects)
- JSON for proposals (complete objects)

## Querying the Log

Common queries:

### All Detours in a Run
```bash
grep '"decision":"DETOUR"' RUN_BASE/build/routing/decisions.jsonl
```

### Escalation Rate
```bash
grep '"decision":"ESCALATE"' RUN_BASE/*/routing/decisions.jsonl | wc -l
```

### Flow Injections
```bash
ls RUN_BASE/*/routing/injections/flow-*.json
```

## The Rule

> Every off-road decision leaves a trace.
> The audit trail is append-only.
> Golden path is implicit; deviations are explicit.

---

## See Also
- [routing-decisions.md](../execution/routing-decisions.md) - Decision vocabulary
- [navigator-protocol.md](../execution/navigator-protocol.md) - How decisions are made
- [receipt-schema.md](./receipt-schema.md) - Step-level audit trail
