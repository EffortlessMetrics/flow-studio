# Error Taxonomy: Classification and Handling

Errors are routing signals, not hard stops. This taxonomy classifies errors and defines handling strategies for each category.

## The Fix-Forward Principle

**Errors are information, not barriers.**

The system's job is to complete flows with documented issues, not to halt at the first problem. Every error becomes a routing decision:
- Retry? (transient)
- Fail fast? (permanent)
- Try again with limits? (retriable)
- Stop everything? (fatal)

Only fatal errors halt immediately. Everything else routes forward.

## Error Categories

### 1. Transient Errors

**Definition:** Temporary failures caused by external conditions that are likely to resolve on their own.

| Signature | Examples |
|-----------|----------|
| Network failure | `ConnectionError`, `TimeoutError`, `ETIMEDOUT` |
| Rate limiting | HTTP 429, `RateLimitExceeded`, `quota_exceeded` |
| Service unavailable | HTTP 502, 503, 504, `ServiceUnavailable` |
| Resource contention | `EBUSY`, `ResourceTemporarilyUnavailable` |

**Detection Criteria:**
```json
{
  "error_class": "transient",
  "indicators": [
    "exit_code in [124, 137]",
    "http_status in [408, 429, 500, 502, 503, 504]",
    "error_message matches /timeout|timed out|connection refused|rate limit/i"
  ]
}
```

**Handling Strategy:**
- Retry with exponential backoff
- Base delay: 1 second
- Max delay: 60 seconds
- Max attempts: 5
- Jitter: 0-500ms random

```python
def retry_transient(attempt):
    delay = min(60, (2 ** attempt) + random.uniform(0, 0.5))
    sleep(delay)
    return attempt < 5
```

**Escalation Path:**
1. After 5 retries: log as persistent transient
2. Route to DETOUR if alternative path exists (e.g., different API endpoint)
3. After DETOUR fails: ESCALATE to human

**Logging Requirements:**
```json
{
  "error_category": "transient",
  "error_type": "rate_limit",
  "attempt": 3,
  "delay_ms": 4000,
  "will_retry": true,
  "context": {
    "endpoint": "api.anthropic.com",
    "http_status": 429,
    "retry_after": "5s"
  }
}
```

### 2. Permanent Errors

**Definition:** Failures that will not resolve with retry. The operation is fundamentally invalid.

| Signature | Examples |
|-----------|----------|
| Invalid input | `ValidationError`, malformed JSON, missing required field |
| Missing dependency | `ModuleNotFoundError`, `FileNotFoundError` (for required files) |
| Permission denied | `EACCES`, HTTP 401, 403 |
| Resource not found | HTTP 404, `KeyError` on required config |
| Configuration error | Invalid API key format, malformed YAML |

**Detection Criteria:**
```json
{
  "error_class": "permanent",
  "indicators": [
    "http_status in [400, 401, 403, 404, 422]",
    "error_message matches /invalid|not found|permission denied|unauthorized/i",
    "validation_errors is not empty"
  ]
}
```

**Handling Strategy:**
- Fail fast (no retry)
- Capture full error context
- Route to appropriate recovery path
- BLOCKED status if input is missing
- ESCALATE if configuration issue

```python
def handle_permanent(error):
    log_with_context(error, level="ERROR")
    if is_missing_input(error):
        return RoutingDecision(status="BLOCKED", reason=str(error))
    elif is_config_error(error):
        return RoutingDecision(decision="ESCALATE", reason="Configuration issue")
    else:
        return RoutingDecision(status="UNVERIFIED", concerns=[error_to_concern(error)])
```

**Escalation Path:**
1. Log full error with context
2. If missing input: BLOCKED
3. If fixable by agent: DETOUR to fixer
4. If human decision needed: ESCALATE immediately

**Logging Requirements:**
```json
{
  "error_category": "permanent",
  "error_type": "validation_error",
  "will_retry": false,
  "routing_decision": "BLOCKED",
  "context": {
    "field": "api_key",
    "error": "Invalid format: expected sk-... pattern",
    "input_source": "config/secrets.yaml"
  },
  "stack_trace": "..."
}
```

### 3. Retriable Errors

**Definition:** Failures that might succeed on retry, but with limits. Often caused by flaky tests, transient lint issues, or non-deterministic operations.

| Signature | Examples |
|-----------|----------|
| Flaky test | Test fails, then passes on rerun |
| Transient lint | Race condition in linter |
| Network glitch | Single packet loss, not sustained |
| Resource race | File locked temporarily |

**Detection Criteria:**
```json
{
  "error_class": "retriable",
  "indicators": [
    "test_failure AND same_test_passed_recently",
    "lint_error AND previous_run_clean",
    "error_message matches /flaky|intermittent|race/i",
    "failure_count < 3 for same signature"
  ]
}
```

**Handling Strategy:**
- Limited retries (max 3)
- No backoff (failures are random, not load-based)
- Track failure signatures
- On repeated failure: route to DETOUR or ESCALATE

```python
def retry_retriable(attempt, failure_signature, history):
    if attempt >= 3:
        return False  # Stop retrying
    if signature_in_history(failure_signature, history, count=2):
        return False  # Same error twice = not flaky
    return True
```

**Escalation Path:**
1. Retry up to 3 times
2. If same signature twice: route to DETOUR (known fix pattern)
3. If DETOUR fails: advance with WARNING
4. If critical path: ESCALATE

**Logging Requirements:**
```json
{
  "error_category": "retriable",
  "error_type": "flaky_test",
  "attempt": 2,
  "will_retry": true,
  "failure_signature": "test_auth_login::assertion_failed",
  "previous_signatures": ["test_db_connect::timeout"],
  "context": {
    "test_file": "tests/test_auth.py",
    "test_name": "test_login",
    "failure_message": "Expected 200, got 503"
  }
}
```

### 4. Fatal Errors

**Definition:** Errors that require immediate halt. Continuing would cause harm, data loss, or security breach.

| Signature | Examples |
|-----------|----------|
| Secrets exposure | API key in diff, password in log |
| Data corruption | Incomplete transaction, corrupted file |
| Security breach | Unauthorized access attempt, injection detected |
| Invariant violation | Core assumption broken, state machine invalid |
| Boundary violation | Force push to protected, secrets in commit |

**Detection Criteria:**
```json
{
  "error_class": "fatal",
  "indicators": [
    "secrets_detected in diff or output",
    "data_integrity_check failed",
    "security_scan.critical > 0",
    "invariant_violated",
    "boundary_violation_type is not null"
  ]
}
```

**Handling Strategy:**
- HALT IMMEDIATELY
- No retry
- No routing forward
- Preserve state for forensics
- Alert human operator

```python
def handle_fatal(error):
    # Stop everything
    halt_all_agents()

    # Preserve evidence
    snapshot_state_to_forensics()

    # Alert
    notify_operator(error, priority="CRITICAL")

    # Log with full context
    log_fatal_error(error)

    # Return terminal state
    return RoutingDecision(
        decision="TERMINATE",
        reason=f"FATAL: {error.type}",
        requires_human=True
    )
```

**Escalation Path:**
There is no escalation. Fatal errors terminate the run.

**Logging Requirements:**
```json
{
  "error_category": "fatal",
  "error_type": "secrets_exposure",
  "halted_at": "build-step-5",
  "action_taken": "TERMINATE",
  "context": {
    "secret_type": "api_key",
    "location": "src/config.py:15",
    "exposure_risk": "Would be committed to git"
  },
  "forensics": {
    "state_snapshot": "RUN_BASE/build/forensics/fatal-001/",
    "artifacts_preserved": ["diff.patch", "receipt.json", "env_dump.json"]
  },
  "notification_sent": true
}
```

## Error Aggregation

When multiple errors occur, which wins?

### Precedence Order (Highest to Lowest)

```
1. FATAL     → Always wins. Halt immediately.
2. PERMANENT → Cannot proceed. Block or escalate.
3. RETRIABLE → Try again with limits.
4. TRANSIENT → Retry with backoff.
```

### Aggregation Rules

```python
def aggregate_errors(errors):
    # Fatal always wins
    if any(e.category == "fatal" for e in errors):
        return max(errors, key=lambda e: e.severity, default=None)

    # Permanent over retriable over transient
    by_category = {
        "permanent": [],
        "retriable": [],
        "transient": []
    }
    for e in errors:
        by_category[e.category].append(e)

    if by_category["permanent"]:
        return aggregate_permanent(by_category["permanent"])

    if by_category["retriable"]:
        return aggregate_retriable(by_category["retriable"])

    return aggregate_transient(by_category["transient"])
```

### Multiple Errors of Same Category

| Category | Aggregation Rule |
|----------|------------------|
| Fatal | First fatal wins (stop immediately) |
| Permanent | Collect all, report together, use highest severity |
| Retriable | Track signatures, retry if any might succeed |
| Transient | Use longest backoff, retry once |

### Example: Mixed Errors

```json
{
  "errors": [
    { "category": "transient", "type": "rate_limit" },
    { "category": "permanent", "type": "validation_error" },
    { "category": "retriable", "type": "flaky_test" }
  ],
  "aggregation": {
    "winning_category": "permanent",
    "decision": "BLOCKED",
    "reason": "Validation error cannot be retried",
    "suppressed": [
      { "category": "transient", "note": "Would retry, but permanent blocks" },
      { "category": "retriable", "note": "Would retry, but permanent blocks" }
    ]
  }
}
```

## Error Context

What to capture for debugging.

### Required Context (All Errors)

```json
{
  "timestamp": "ISO8601",
  "run_id": "string",
  "flow_key": "string",
  "step_id": "string",
  "agent_key": "string",
  "error_category": "transient | permanent | retriable | fatal",
  "error_type": "string (specific type)",
  "error_message": "string",
  "stack_trace": "string (if available)"
}
```

### Category-Specific Context

#### Transient
```json
{
  "retry_count": 3,
  "total_delay_ms": 7000,
  "endpoint": "api.anthropic.com",
  "http_status": 429,
  "retry_after_header": "5"
}
```

#### Permanent
```json
{
  "input_source": "path or identifier",
  "validation_errors": [],
  "expected_format": "description",
  "actual_value": "sanitized value"
}
```

#### Retriable
```json
{
  "failure_signature": "hash or pattern",
  "previous_signatures": [],
  "test_output": "truncated output",
  "flaky_history": []
}
```

#### Fatal
```json
{
  "halt_reason": "string",
  "affected_resources": [],
  "remediation_steps": [],
  "forensics_path": "RUN_BASE/.../forensics/",
  "notification_id": "string"
}
```

## Routing Integration

Errors map to routing decisions:

| Error Category | Routing Decision | Condition |
|----------------|------------------|-----------|
| Transient | (internal retry) | attempts < max |
| Transient | DETOUR | alternative path exists |
| Transient | ESCALATE | retries exhausted |
| Permanent | BLOCKED | missing input |
| Permanent | DETOUR | fixable by agent |
| Permanent | ESCALATE | human decision needed |
| Retriable | (internal retry) | attempts < 3 |
| Retriable | DETOUR | signature matches known fix |
| Retriable | CONTINUE | advance with warning |
| Fatal | TERMINATE | always |

## The Rule

> Errors are routing signals, not hard stops.
> Transient: retry with backoff. Permanent: fail fast.
> Retriable: try again with limits. Fatal: halt immediately.
> When in doubt, advance with documented concerns.

---

## See Also
- [routing-decisions.md](./routing-decisions.md) - Decision vocabulary
- [detour-catalog.md](./detour-catalog.md) - Known fix patterns
- [resume-protocol.md](./resume-protocol.md) - Recovery from failures
- [fix-forward-vocabulary.md](../governance/fix-forward-vocabulary.md) - BLOCKED is rare
