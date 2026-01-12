# Stepwise Execution Contract

> For: Developers building stepwise integrations, operators debugging flow execution.
>
> **Prerequisites:** [STEPWISE_BACKENDS.md](./STEPWISE_BACKENDS.md) | **Related:** CLAUDE.md (Architecture section)

---

This document defines the behavioral contract for stepwise execution. All step engines (Claude, Gemini, or future implementations) must satisfy these invariants.

## Receipt Schema

Receipts capture execution metadata for auditing and debugging. Written to `RUN_BASE/<flow>/receipts/<step_id>-<agent>.json`.

### Required Fields

| Field | Type | Description |
|-------|------|-------------|
| `engine` | string | Engine identifier: `"claude-step"` or `"gemini-step"` |
| `mode` | string | Execution mode: `"stub"` \| `"sdk"` \| `"cli"` |
| `provider` | string | API provider: `"anthropic"` \| `"anthropic_compat"` \| `"gemini"` |
| `model` | string | Model identifier (e.g., `"claude-sonnet-4-20250514"`, `"claude-stub"`) |
| `step_id` | string | Step identifier within the flow |
| `flow_key` | string | Flow being executed (`signal`, `plan`, `build`, etc.) |
| `run_id` | string | Run identifier |
| `agent_key` | string | Agent executing this step |
| `started_at` | string | ISO 8601 timestamp with timezone |
| `completed_at` | string | ISO 8601 timestamp with timezone |
| `duration_ms` | integer | Execution duration in milliseconds (>= 0) |
| `status` | string | Execution status: `"succeeded"` \| `"failed"` |
| `tokens` | object | Token usage: `{prompt, completion, total}` |
| `transcript_path` | string | Relative path to JSONL transcript |

### Optional Fields

| Field | Type | Description |
|-------|------|-------------|
| `error` | string | Error message if `status == "failed"` |
| `routing` | object | Routing decision metadata (for microloops) |
| `tools_allowed` | array | List of tools enabled for this step (SDK mode) |

### Routing Object

Present when the step uses microloop routing:

```json
{
  "routing": {
    "loop_iteration": 2,
    "max_iterations": 5,
    "decision": "loop",
    "reason": "loop_iteration:2"
  }
}
```

| Field | Type | Description |
|-------|------|-------------|
| `loop_iteration` | integer | Current iteration count (0-indexed) |
| `max_iterations` | integer | Maximum iterations allowed |
| `decision` | string | Routing decision: `"loop"` \| `"advance"` \| `"terminate"` \| `"pending"` |
| `reason` | string | Human-readable reason for the decision |

---

## Event Kinds

Events are written to `RUN_BASE/events.jsonl` and provide observability into run execution.

### Run-Level Events

| Kind | When Emitted | Payload |
|------|--------------|---------|
| `run_created` | Run initialized | `{flows, backend, initiator, stepwise: true}` |
| `run_started` | Execution begins | `{mode: "stepwise", routing_enabled: true}` |
| `run_completed` | All steps finished | `{status, error, steps_completed, total_steps_executed}` |

### Step-Level Events

| Kind | When Emitted | Payload |
|------|--------------|---------|
| `step_start` | Step begins | `{role, agents, step_index, engine}` |
| `step_end` | Step succeeds | `{status, duration_ms, engine}` |
| `step_error` | Step fails | `{status, duration_ms, error, engine}` |

### Tool-Level Events

| Kind | When Emitted | Payload |
|------|--------------|---------|
| `tool_start` | Tool invoked | `{tool, input}` |
| `tool_end` | Tool completes | `{tool, success, output}` |

### Routing Events

| Kind | When Emitted | Payload |
|------|--------------|---------|
| `route_decision` | **Primary audit event.** After routing decision. | `{from_step, to_step, reason, loop_state, routing_source}` |

**Note:** `route_decision` is the canonical event kind (see `db.py` `CANONICAL_EVENT_KINDS`). It includes the routing decision payload with audit trail.

### `routing_source` Field

The `routing_source` field documents how the routing decision was made:

| Value | Description |
|-------|-------------|
| `fast_path` | Obvious deterministic case (terminal step, single edge, explicit next_step_id) |
| `deterministic` | CEL evaluation or deterministic graph rules |
| `navigator` | Navigator chose from candidates |
| `navigator:detour` | Navigator chose a detour/sidequest |
| `envelope_fallback` | Legacy RoutingSignal from step output |
| `escalate` | Last resort fallback |

This field enables audit trail analysis to understand routing behavior patterns.

---

## Transcript Format

Transcripts capture the full LLM conversation. Written to `RUN_BASE/<flow>/llm/<step_id>-<agent>-<engine>.jsonl`.

### Format

JSONL (one JSON object per line). Each line represents a message or event.

### Message Schema

```jsonl
{"timestamp": "2025-01-15T10:00:00Z", "role": "system", "content": "..."}
{"timestamp": "2025-01-15T10:00:01Z", "role": "user", "content": "..."}
{"timestamp": "2025-01-15T10:00:05Z", "role": "assistant", "content": "..."}
{"timestamp": "2025-01-15T10:00:06Z", "type": "tool_use", "tool": "Read", "input": {...}}
{"timestamp": "2025-01-15T10:00:07Z", "type": "tool_result", "tool": "Read", "success": true, "output": "..."}
```

### Required Message Fields

- `timestamp`: ISO 8601 timestamp
- `role` or `type`: Message type indicator
- `content` (for messages) or type-specific fields

---

## Behavioral Invariants

### Mode Parity

Stub mode behavior matches SDK/CLI mode at the contract level:

1. **Same file structure**: Both modes write transcripts and receipts to identical paths
2. **Same receipt schema**: All required fields present regardless of mode
3. **Same event sequence**: `run_created` -> `run_started` -> `step_start` -> ... -> `run_completed`

### StepResult Guarantees

Engines return `StepResult` satisfying:

- `duration_ms >= 0`
- `status in {"succeeded", "failed", "skipped"}`
- `len(output) < 50KB`
- `step_id` matches the input context

### Event Sequencing

1. `run_created` always emitted first
2. `run_started` emitted before any step events
3. Each step has exactly one `step_start` followed by either `step_end` or `step_error`
4. `run_completed` always emitted last (even on failure)

---

## Routing Contract

The orchestrator determines step traversal based on routing configuration and receipt values.

### Routing Kinds

| Kind | Behavior |
|------|----------|
| `linear` | Simple sequential execution; `next` field determines successor |
| `microloop` | Loops back to `loop_target` until exit condition met |
| `branch` | Maps receipt values to different next steps via `branches` |

### Microloop Exit Conditions

A microloop exits when ANY of these conditions is true:

1. **Success value match**: `receipt[loop_condition_field]` is in `loop_success_values`
2. **No further help**: `receipt["can_further_iteration_help"]` equals `"no"`
3. **Max iterations**: Current iteration >= `max_iterations` (default: 5)

### Routing Decision Values

| Decision | Meaning |
|----------|---------|
| `loop` | Loop back to target step |
| `advance` | Move to next step (linear progression) |
| `terminate` | Flow complete, no more steps |
| `pending` | Decision not yet made (transient state) |

### Microloop Example (Requirements)

```yaml
# From swarm/config/flows/signal.yaml
- id: critique_reqs
  agents: [requirements-critic]
  routing:
    kind: microloop
    loop_target: author_reqs
    loop_condition_field: status
    loop_success_values: ["VERIFIED"]
    max_iterations: 5
    next: author_bdd
```

The orchestrator reads `receipt["status"]` after the critic step. If `"VERIFIED"`, it advances to `author_bdd`. Otherwise, it loops back to `author_reqs` (unless max iterations reached).

---

## Contract Verification

These contracts are enforced by tests:

| Contract | Test File | What It Proves |
|----------|-----------|----------------|
| Receipt required fields | `tests/test_step_engine_contract.py` | All receipts include engine, mode, provider, step_id, flow_key, run_id, status, duration_ms |
| Transcript JSONL format | `tests/test_step_engine_contract.py` | Each line is valid JSON with role, content, timestamp |
| Teaching notes in prompts | `tests/test_step_prompt_teaching_notes.py` | Inputs/outputs/emphasizes/constraints appear in LLM prompts |
| Routing follows receipts | `tests/test_build_stepwise_routing.py` | Orchestrator routes based on receipt status field |

### Running Contract Tests

```bash
# All contract tests
uv run pytest tests/test_step_engine_contract.py -v

# Routing tests
uv run pytest tests/test_build_stepwise_routing.py -v

# Teaching notes tests
uv run pytest tests/test_step_prompt_teaching_notes.py -v
```

---

## Golden Examples

Pre-generated examples demonstrate the contract in practice:

| Example | Location |
|---------|----------|
| Receipt with routing | `swarm/examples/stepwise-sdlc-claude/signal/receipts/critique_reqs-requirements-critic.json` |
| Transcript | `swarm/examples/stepwise-sdlc-claude/signal/llm/normalize-signal-normalizer-claude.jsonl` |
| Events log | `swarm/examples/stepwise-sdlc-claude/events.jsonl` |

---

## See Also

- [STEPWISE_BACKENDS.md](./STEPWISE_BACKENDS.md) -- Full configuration and usage guide
- [FLOW_STUDIO.md](./FLOW_STUDIO.md) -- Flow Studio UI for visualizing stepwise runs
- `swarm/runtime/engines.py` -- Engine implementations
- `swarm/runtime/orchestrator.py` -- Routing logic
