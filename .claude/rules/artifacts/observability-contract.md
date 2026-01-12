# Observability Contract

Logs are the runtime audit trail. They capture what happened, when, and why.

## Structured Logging

All logs MUST be JSON lines (JSONL). One JSON object per line.

### Required Fields

Every log entry MUST include:

```json
{
  "timestamp": "2024-01-15T10:30:00.123Z",
  "level": "INFO | WARN | ERROR | DEBUG",
  "run_id": "abc123",
  "flow_key": "signal | plan | build | review | gate | deploy | wisdom",
  "step_id": "step-3",
  "agent_key": "code-implementer",
  "message": "Human-readable description"
}
```

### Optional Fields

```json
{
  "tokens": {
    "prompt": 1500,
    "completion": 500,
    "total": 2000
  },
  "duration_ms": 1234,
  "error": {
    "type": "ValidationError",
    "message": "Missing required field: step_id",
    "stack": "string (DEBUG only)"
  },
  "parent_step_id": "step-2",
  "child_step_id": "substep-3a",
  "routing": {
    "decision": "CONTINUE | LOOP | DETOUR | ...",
    "reason": "string"
  },
  "artifact_path": "RUN_BASE/build/output.json",
  "command": "pytest tests/ -v",
  "exit_code": 0
}
```

## Log Levels

| Level | Purpose | When to Use |
|-------|---------|-------------|
| **ERROR** | Failures that need attention | Step failed, unhandled exception, missing required input |
| **WARN** | Concerns that don't block | Assumption made, evidence gap, retry attempted |
| **INFO** | Step transitions, key decisions | Step start/end, routing decision, artifact produced |
| **DEBUG** | Detailed execution | Tool calls, context loading, internal state (off by default) |

### Level Selection Guide

```
ERROR: "Step failed: pytest returned exit code 1"
WARN:  "Assumption: user means OAuth when they say 'login'"
INFO:  "Step build-step-3 completed in 4523ms"
DEBUG: "Loading context: 15234 tokens from previous step"
```

## What to Always Log

### Step Lifecycle

```json
{
  "timestamp": "2024-01-15T10:30:00.000Z",
  "level": "INFO",
  "run_id": "abc123",
  "flow_key": "build",
  "step_id": "step-3",
  "agent_key": "code-implementer",
  "message": "Step started",
  "event": "step_start"
}
```

```json
{
  "timestamp": "2024-01-15T10:30:04.523Z",
  "level": "INFO",
  "run_id": "abc123",
  "flow_key": "build",
  "step_id": "step-3",
  "agent_key": "code-implementer",
  "message": "Step completed",
  "event": "step_end",
  "duration_ms": 4523,
  "status": "succeeded",
  "tokens": {
    "prompt": 15000,
    "completion": 3500,
    "total": 18500
  }
}
```

### Routing Decisions

```json
{
  "timestamp": "2024-01-15T10:30:04.600Z",
  "level": "INFO",
  "run_id": "abc123",
  "flow_key": "build",
  "step_id": "step-3",
  "agent_key": "navigator",
  "message": "Routing decision: CONTINUE to step-4",
  "event": "routing_decision",
  "routing": {
    "decision": "CONTINUE",
    "next_step_id": "step-4",
    "reason": "Tests passed, no HIGH severity concerns"
  }
}
```

### Error Details

```json
{
  "timestamp": "2024-01-15T10:30:04.523Z",
  "level": "ERROR",
  "run_id": "abc123",
  "flow_key": "build",
  "step_id": "step-3",
  "agent_key": "code-implementer",
  "message": "Step failed: pytest returned exit code 1",
  "event": "step_error",
  "error": {
    "type": "CommandError",
    "message": "pytest returned exit code 1",
    "command": "pytest tests/ -v",
    "exit_code": 1,
    "evidence_path": "RUN_BASE/build/test_output.log"
  }
}
```

### Token Usage

Always logged in `step_end` events. Also log when approaching limits:

```json
{
  "timestamp": "2024-01-15T10:30:03.000Z",
  "level": "WARN",
  "run_id": "abc123",
  "flow_key": "build",
  "step_id": "step-3",
  "agent_key": "code-implementer",
  "message": "Token budget 90% consumed",
  "event": "token_warning",
  "tokens": {
    "used": 27000,
    "budget": 30000,
    "remaining": 3000
  }
}
```

## What to Never Log

### Secrets and Credentials

NEVER log:
- API keys (`sk-...`, `ghp_...`, `AKIA...`)
- Passwords or tokens
- Private keys
- Connection strings with credentials
- Bearer tokens

**Enforcement:** Redact patterns matching known secret formats.

### Full File Contents

NEVER log file contents. Log paths instead:

```json
// BAD
{ "file_content": "def auth():\n    password = 'secret123'\n..." }

// GOOD
{ "artifact_path": "src/auth.py", "lines_modified": 45 }
```

### PII

NEVER log:
- Email addresses
- Names
- Phone numbers
- Addresses
- Any user-identifiable information

### Raw LLM Responses

NEVER log raw LLM output in structured logs. Write to transcript file instead:

```json
// BAD
{ "llm_response": "Here is the implementation:\n\n```python\n..." }

// GOOD
{ "transcript_path": "RUN_BASE/build/llm/step-3-code-implementer.jsonl" }
```

## Trace Correlation

### Run-Level Correlation

`run_id` ties all logs from a single run together:

```bash
# Find all logs for a run
grep '"run_id":"abc123"' RUN_BASE/*/logs/*.jsonl
```

### Step-Level Correlation

`step_id` correlates within a step:

```bash
# Find all logs for a step
grep '"step_id":"step-3"' RUN_BASE/build/logs/*.jsonl
```

### Parent/Child for Subagent Calls

When a step spawns subagents:

```json
{
  "timestamp": "2024-01-15T10:30:02.000Z",
  "level": "INFO",
  "run_id": "abc123",
  "flow_key": "build",
  "step_id": "step-3",
  "agent_key": "code-implementer",
  "message": "Spawning subagent: explore",
  "event": "subagent_spawn",
  "child_step_id": "step-3-explore-1"
}
```

The child logs with:

```json
{
  "step_id": "step-3-explore-1",
  "parent_step_id": "step-3",
  ...
}
```

## Log Locations

Logs are written per-step to:

```
RUN_BASE/<flow>/logs/<step_id>.jsonl
```

Example:
```
swarm/runs/abc123/build/logs/step-3.jsonl
swarm/runs/abc123/build/logs/step-4.jsonl
```

### Aggregated Logs

For flow-level view:

```
RUN_BASE/<flow>/logs/flow.jsonl
```

Contains all step logs concatenated in order.

### Run-Level Index

For cross-flow view:

```
RUN_BASE/logs/run.jsonl
```

Contains key events (step_start, step_end, routing_decision) from all flows.

## Log Rotation

Within a run, logs are append-only. No rotation during execution.

After run completion:
- Compress logs older than 7 days
- Archive to cold storage after 30 days
- Delete after retention period (configurable)

## The Rule

> Logs are structured, correlated, and safe.
> Required fields enable querying. Forbidden content prevents leaks.
> `run_id` ties everything together. Step logs are the primary unit.

## Validation

Log validation checks:
1. Required fields present
2. Timestamps are valid ISO8601
3. Level is valid enum
4. No forbidden patterns (secrets, PII)
5. Paths resolve (when claimed)

## Anti-Patterns

### Unstructured Logs
```
// BAD
console.log("Step 3 completed successfully!")

// GOOD
logger.info({ event: "step_end", step_id: "step-3", status: "succeeded" })
```

### Missing Correlation
```json
// BAD - no run_id or step_id
{ "message": "Something happened" }

// GOOD - fully correlated
{ "run_id": "abc123", "step_id": "step-3", "message": "Something happened" }
```

### Secret Leakage
```json
// BAD
{ "api_key": "sk-abc123..." }

// GOOD
{ "api_key_present": true }
```

### Content Dumping
```json
// BAD
{ "file": { "path": "src/auth.py", "content": "..." } }

// GOOD
{ "artifact_path": "src/auth.py", "size_bytes": 1234 }
```

---

## See Also
- [receipt-schema.md](./receipt-schema.md) - Step-level proof of work
- [handoff-protocol.md](./handoff-protocol.md) - Step transition protocol
- [off-road-logging.md](./off-road-logging.md) - Routing decision audit trail
