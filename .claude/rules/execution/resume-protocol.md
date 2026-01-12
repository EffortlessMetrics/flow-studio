# Resume Protocol

What happens when a run fails mid-step? How do you recover?

## The Problem

Runs can fail for many reasons:
- API timeout
- Process crash
- Human interrupt
- Infrastructure failure

Without a resume protocol:
- Start over from scratch
- Lose completed work
- Repeat expensive operations

## The Solution: Checkpoint Semantics

### Checkpoint Invariant

After each step completes:
1. Receipt written to disk
2. Artifacts persisted
3. Handoff envelope committed
4. State is resumable

### What Constitutes a Checkpoint

A valid checkpoint exists when:
```
RUN_BASE/<flow>/receipts/<step_id>-<agent>.json  # exists
RUN_BASE/<flow>/handoffs/<step_id>-<agent>.json  # exists (if finalized)
```

### Resume Logic

```python
def find_resume_point(run_id, flow_key):
    completed_steps = list_completed_receipts(run_id, flow_key)
    last_completed = max(completed_steps, key=lambda s: s.step_index)

    if last_completed.status == "succeeded":
        return last_completed.step_index + 1  # Resume from next
    else:
        return last_completed.step_index  # Retry failed step
```

## Partial Artifacts

When a step fails mid-execution:

### What's Preserved
- Any files written to disk
- Partial transcript (up to failure point)
- Git changes (uncommitted)

### What's Lost
- In-memory state
- Uncommitted handoff
- Routing decision (never made)

### Recovery Strategy

1. Check for partial artifacts
2. Assess completeness
3. Either:
   - Resume with partial context
   - Retry step from scratch
   - Escalate for human decision

## Idempotence Expectations

Steps SHOULD be idempotent:
- Running twice produces same result
- No harmful side effects on retry
- Safe to resume after crash

Steps that are NOT idempotent:
- Git commits (would create duplicates)
- External API calls (might duplicate)
- File appends (would duplicate content)

### Making Steps Idempotent

```python
# Bad: Always appends
with open(file, 'a') as f:
    f.write(content)

# Good: Write complete state
with open(file, 'w') as f:
    f.write(complete_content)
```

## Resume Commands

### Resume from Checkpoint
```bash
# Resume flow from last checkpoint
make stepwise-resume RUN_ID=abc123 FLOW=build

# Resume from specific step
make stepwise-resume RUN_ID=abc123 FLOW=build START_STEP=step-3
```

### Retry Failed Step
```bash
# Retry the step that failed
make stepwise-retry RUN_ID=abc123 FLOW=build STEP=step-3
```

## Crash Recovery

### Graceful Shutdown
On SIGINT/SIGTERM:
1. Complete current LLM call (if possible)
2. Write partial receipt with status="interrupted"
3. Persist any artifacts
4. Exit cleanly

### Hard Crash
On unexpected termination:
1. No receipt written
2. Artifacts may be partial
3. Next run detects incomplete state
4. Offers: retry, skip, or abort

## The Rule

> Every step leaves a checkpoint. Runs are resumable by default.
> Steps should be idempotent. Partial state is explicitly handled.

## Current State

**Implemented**: Receipts and artifacts persist after each step
**Supported**: Manual resume by specifying start_step
**Aspirational**: Automatic resume detection and graceful interrupt handling
