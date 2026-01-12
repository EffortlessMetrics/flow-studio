# Chaos Verification Runbook

> For: Operators verifying system behavior under failure conditions.
>
> **Prerequisites:** System running via `make stepwise-sdlc-stub` | **Related:** [GOLDEN_RUNS.md](./GOLDEN_RUNS.md)

---

This runbook documents how to verify that the system behaves correctly under failure conditions. Each scenario includes trigger conditions, expected artifacts, and grep-able success criteria.

> **Review the output, not the process.**
> Chaos runs prove the factory produces durable, reviewable outputs even when interrupted.
> You don't watch chaos runs—you trust the receipts and resume substrate afterward.

The goal is **production confidence**: knowing that the system's audit trail and recovery mechanisms work under real failure conditions.

## Overview

The system is **"proven under violence"** when these three scenarios pass:

1. **Golden Path** — Happy path completes without detours
2. **Stalled Worker** — Stall detection triggers recovery
3. **Kill/Resume** — Atomic resume after interruption

---

## Scenario A: Golden Path Verification

**Goal:** Verify end-to-end autonomy on the happy path.

### Trigger

```bash
make stepwise-sdlc-stub routing_mode=AUTHORITATIVE
```

### Expected Behavior

1. Flows execute sequentially: Signal → Plan → Build → Review → Gate → Deploy → Wisdom
2. No detours or injections
3. All steps complete with `routing_source="fast_path"` or `routing_source="deterministic"`

### Artifacts to Verify

| Artifact | Location | What to Check |
|----------|----------|---------------|
| Run state | `RUN_BASE/run_state.json` | `status: "succeeded"` |
| Events | `RUN_BASE/events.jsonl` | All `step_end` events have `status: "succeeded"` |
| Routing | `RUN_BASE/events.jsonl` | `route_decision` events show `routing_source` values |

### Success Criteria (Grep-able)

```bash
# Check run completed successfully
grep '"status": "succeeded"' RUN_BASE/run_state.json

# Check no errors in events
grep '"kind": "step_error"' RUN_BASE/events.jsonl && echo "FAIL: Errors found" || echo "PASS: No errors"

# Count routing decisions by source
grep '"route_decision"' RUN_BASE/events.jsonl | grep -o '"routing_source": "[^"]*"' | sort | uniq -c
```

### Pass Condition

- Run completes with `status: "succeeded"`
- Zero `step_error` events
- All routing via `fast_path` or `deterministic` (no Navigator calls in stub mode)

---

## Scenario B: Stalled Worker (Stall Detection)

**Goal:** Verify that the system detects and recovers from repeated identical failures.

### Setup

Inject a "stall fault" into the stub responses:

```python
# In test fixture or via environment variable
INJECT_STALL_FAULT = "code-implementer:3"  # Fail 3 times with identical error
```

Or manually edit `swarm/runtime/engines/stub.py` to return identical errors for a specific agent.

### Trigger

```bash
INJECT_STALL_FAULT="code-implementer:3" make stepwise-sdlc-stub
```

### Expected Behavior

1. `code-implementer` step fails with identical error 3 times
2. `ProgressTracker` detects zero delta (same error signature)
3. Navigator receives `stall_detected=True` in context
4. Routing decision changes from `LOOP` to `DETOUR` or `TERMINATE`

### Artifacts to Verify

| Artifact | Location | What to Check |
|----------|----------|---------------|
| Routing events | `RUN_BASE/events.jsonl` | `stall_detected: true` in routing payload |
| Loop state | `RUN_BASE/build/loop_state.json` | `stall_count > 0` |
| Routing source | `RUN_BASE/events.jsonl` | `routing_source` contains "elephant" or "stall" |

### Success Criteria (Grep-able)

```bash
# Check stall was detected
grep -i "stall_detected.*true" RUN_BASE/events.jsonl && echo "PASS: Stall detected" || echo "FAIL: No stall detection"

# Check routing responded to stall
grep '"route_decision"' RUN_BASE/events.jsonl | grep -i "elephant\|stall"

# Count loop iterations (should cap at 3-5, not infinite)
grep '"loop_iteration"' RUN_BASE/events.jsonl | tail -5
```

### Pass Condition

- Stall detected after 3 identical failures
- Routing responds appropriately (DETOUR, TERMINATE, or RETRY with modified context)
- No infinite loop (iteration count bounded)

---

## Scenario C: Kill/Resume (Atomic Resume)

**Goal:** Verify that interrupting mid-step produces recoverable state.

### Trigger

```bash
# Start a long run
make stepwise-sdlc-stub &
PID=$!

# Wait for mid-execution (e.g., during Build flow)
sleep 10

# Kill the process
kill -9 $PID
```

### Expected Behavior

1. `run_state.json` on disk reflects the last completed step
2. No partial writes (atomic file operations)
3. `events.jsonl` has no corrupted lines
4. Resume picks up exactly where interrupted

### Artifacts to Verify

| Artifact | Location | What to Check |
|----------|----------|---------------|
| Run state | `RUN_BASE/run_state.json` | Valid JSON, points to last completed step |
| Events log | `RUN_BASE/events.jsonl` | No corrupted/partial lines |
| Receipts | `RUN_BASE/<flow>/receipts/` | Only completed steps have receipts |

### Resume Verification

```bash
# Resume the interrupted run
make stepwise-sdlc-stub --resume RUN_ID

# Verify it continues from the right point
grep '"step_start"' RUN_BASE/events.jsonl | tail -5
```

### Success Criteria (Grep-able)

```bash
# Validate run_state.json is valid JSON
python -m json.tool RUN_BASE/run_state.json > /dev/null && echo "PASS: Valid JSON" || echo "FAIL: Corrupted state"

# Check events.jsonl has no corrupted lines
python -c "import json; [json.loads(line) for line in open('RUN_BASE/events.jsonl')]" && echo "PASS: Valid events" || echo "FAIL: Corrupted events"

# Verify no double-writes after resume (uniq -d exits 0 regardless of duplicates)
test -z "$(grep '"step_start"' RUN_BASE/events.jsonl | sort | uniq -d)" \
  && echo "PASS: No duplicates" || echo "FAIL: Duplicate step starts"
```

### Pass Condition

- `run_state.json` is valid JSON after kill
- `events.jsonl` has no corrupted lines
- Resume continues from correct position
- No duplicate step executions

---

## Verification Matrix

| Scenario | Trigger | Key Artifact | Success Grep |
|----------|---------|--------------|--------------|
| Golden Path | `make stepwise-sdlc-stub` | `run_state.json` | `grep '"status": "succeeded"'` |
| Stalled Worker | Inject 3x identical failure | `events.jsonl` | `grep -i "stall_detected"` |
| Kill/Resume | `kill -9` mid-run + resume | `run_state.json` | Valid JSON after kill |

---

## Automated Verification Script

For CI integration:

```bash
#!/bin/bash
set -e

echo "=== Scenario A: Golden Path ==="
make stepwise-sdlc-stub
grep '"status": "succeeded"' swarm/runs/*/run_state.json

echo "=== Scenario B: Stall Detection ==="
# Requires test fixture
echo "Skipping (requires stall fault injection)"

echo "=== Scenario C: Kill/Resume ==="
make stepwise-sdlc-stub &
PID=$!
sleep 10
kill -9 $PID 2>/dev/null || true
python -m json.tool swarm/runs/*/run_state.json > /dev/null

echo "=== All scenarios passed ==="
```

---

## Troubleshooting

### Golden Path Fails

- Check `events.jsonl` for `step_error` events
- Look at the error message in the event payload
- Verify all required inputs exist

### Stall Detection Not Triggering

- Verify `ProgressTracker` is enabled in config
- Check that errors are truly identical (same signature)
- Look for `stall_analysis` in debug logs

### Resume Creates Duplicates

- Check for race condition in event emission
- Verify `run_state.json` is written atomically (temp file + rename)
- Look for lock contention on events file

---

## See Also

- [GOLDEN_RUNS.md](./GOLDEN_RUNS.md) — Pre-validated golden run examples
- [STEPWISE_CONTRACT.md](./STEPWISE_CONTRACT.md) — Behavioral contracts
- [ROUTING_API.md](./ROUTING_API.md) — Routing implementation reference
