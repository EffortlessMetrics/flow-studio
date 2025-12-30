## Routing Vocabulary

Station handoffs use a closed vocabulary to drive orchestrator routing. These action verbs have precise meanings.

### Action Enum

| Action | Meaning | When to Use |
|--------|---------|-------------|
| **PROCEED** | Continue to the next station in the flow | Work complete, ready for next step |
| **RERUN** | Re-execute the current station | Transient failure, retry may succeed |
| **BOUNCE** | Return to an earlier station/flow | Issues found that upstream must fix |
| **FIX_ENV** | Environment issue requires human intervention | Missing dependencies, config errors |

### Action Semantics

**PROCEED** means:
- Station work is complete (VERIFIED or UNVERIFIED with `can_further_iteration_help: no`)
- Orchestrator should advance to the next station in sequence
- Any concerns are documented in handoff for downstream awareness

**RERUN** means:
- Transient failure occurred (network timeout, rate limit, flaky test)
- Same inputs with same station may succeed on retry
- Should include `retry_count` and `max_retries` to prevent infinite loops
- Not appropriate for deterministic failures

**BOUNCE** means:
- Issues found that require upstream changes
- Specifies `bounce_target` (flow key or station id)
- Gate bouncing to Build for test failures
- Gate bouncing to Plan for design issues
- Includes `bounce_reasons` explaining what must change

**FIX_ENV** means:
- Environment is misconfigured
- Human must intervene before flow can continue
- Examples: missing API keys, broken toolchain, permissions error
- Not a station failure; environment failure

### Routing Fields in Handoff

```json
{
  "status": "VERIFIED | UNVERIFIED | PARTIAL | BLOCKED",
  "action": "PROCEED | RERUN | BOUNCE | FIX_ENV",
  "proposed_next_step": "station-id or null",
  "bounce_target": "flow-key or station-id (if BOUNCE)",
  "bounce_reasons": ["reason 1", "reason 2 (if BOUNCE)"],
  "retry_count": 0,
  "max_retries": 3
}
```

### Status-to-Action Mapping

| Status | Typical Action | Notes |
|--------|---------------|-------|
| VERIFIED | PROCEED | Work complete, advance |
| UNVERIFIED + can_further_iteration_help: yes | (loop continues) | Orchestrator re-invokes same station |
| UNVERIFIED + can_further_iteration_help: no | PROCEED | Advance with documented concerns |
| PARTIAL | PROCEED or BOUNCE | Depends on severity |
| BLOCKED | FIX_ENV or BOUNCE | Cannot continue as-is |

### BOUNCE Target Rules

When bouncing, specify the correct target:

| Issue Type | Bounce Target |
|------------|---------------|
| Test failures, missing tests | build (test-author) |
| Code bugs, incomplete implementation | build (code-implementer) |
| API contract violations | plan (interface-designer) |
| Architecture issues | plan (adr-author) |
| Requirements unclear | signal (requirements-author) |

### Retry Behavior

For RERUN actions, implement backoff:

```json
{
  "action": "RERUN",
  "retry_count": 1,
  "max_retries": 3,
  "retry_reason": "API timeout; transient failure"
}
```

When `retry_count >= max_retries`, convert to FIX_ENV or BOUNCE.

### Orchestrator Contract

The orchestrator reads routing fields and acts accordingly:

1. **PROCEED**: Invoke `proposed_next_step` or flow's default next station
2. **RERUN**: Re-invoke current station (if retries remain)
3. **BOUNCE**: Switch to `bounce_target` flow/station with context
4. **FIX_ENV**: Halt flow, surface error to human

Stations do not route themselves; they declare intent. Orchestrator executes.
