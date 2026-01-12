# Timeout and Retry Policy

Timeouts prevent runaway operations. Retries handle transient failures. Circuit breakers prevent cascading failures.

## Timeout Hierarchy

| Scope | Default | Hard Limit | Rationale |
|-------|---------|------------|-----------|
| **Step** | 10 minutes | 15 minutes | Single agent task |
| **Flow** | 30 minutes | 45 minutes | Complete flow with all steps |
| **LLM call** | 2 minutes | 3 minutes | Single model invocation |
| **Tool execution** | 5 minutes | 10 minutes | Bash, file ops, git |

### Timeout Enforcement

```python
TIMEOUTS = {
    "step": 600_000,      # 10 minutes in ms
    "flow": 1_800_000,    # 30 minutes in ms
    "llm_call": 120_000,  # 2 minutes in ms
    "tool": 300_000,      # 5 minutes in ms
}
```

### Nested Timeout Behavior

Timeouts cascade inward:
- Flow timeout triggers: all active steps terminate
- Step timeout triggers: current LLM call and tools terminate
- LLM timeout triggers: request cancelled, retry or fail

Inner timeouts are capped by outer timeouts:
```
Remaining flow time: 5 minutes
Step timeout: 10 minutes
Effective step timeout: 5 minutes (capped)
```

## Retry Policy

### Transient Errors

Errors that may succeed on retry.

| Error Type | Max Retries | Backoff | Example |
|------------|-------------|---------|---------|
| Network timeout | 3 | Exponential: 1s, 2s, 4s | Connection reset |
| 5xx server error | 3 | Exponential: 1s, 2s, 4s | 502 Bad Gateway |
| Rate limit (429) | 5 | Retry-After header | API throttling |
| Transient API error | 3 | Exponential: 1s, 2s, 4s | Temporary unavailable |

### Rate Limit Handling

```python
def handle_rate_limit(response):
    retry_after = response.headers.get("Retry-After", 60)
    retry_after = min(int(retry_after), 300)  # Cap at 5 minutes
    sleep(retry_after)
    # Retry with same parameters
```

Rate limit retries:
- Respect `Retry-After` header
- Cap wait at 300 seconds (5 minutes)
- Max 5 retries before escalate
- Log each rate limit event

### Network Errors with Jitter

```python
def retry_with_jitter(attempt):
    base_delay = 1.0 * (2 ** attempt)  # 1s, 2s, 4s
    jitter = random.uniform(0, 0.5 * base_delay)
    return base_delay + jitter
```

Jitter prevents thundering herd when multiple operations retry simultaneously.

### No-Retry Errors

These errors are permanent. Retrying wastes resources.

| Error Type | Action | Example |
|------------|--------|---------|
| Validation error | Fail immediately | Invalid JSON schema |
| Auth error (401/403) | Escalate | Bad API key |
| Not found (404) | Fail immediately | Missing resource |
| Bad request (400) | Fail immediately | Malformed request |
| Permanent API error | Escalate | Account suspended |

```python
NO_RETRY_CODES = {400, 401, 403, 404, 422}

def should_retry(error):
    if hasattr(error, 'status_code'):
        return error.status_code not in NO_RETRY_CODES
    if isinstance(error, ValidationError):
        return False
    if isinstance(error, AuthenticationError):
        return False
    return True  # Default: try retry
```

## Circuit Breaker

Prevents cascading failures when a service is degraded.

### Thresholds

| Threshold | Value | Action |
|-----------|-------|--------|
| Consecutive failures to open | 3 | Pause 30 seconds |
| Consecutive failures to escalate | 5 | Human intervention |
| Success count to reset | 1 | Resume normal operation |
| Pause duration | 30 seconds | Cooling period |

### State Machine

```
CLOSED (normal) ──[3 failures]──► OPEN (paused)
                                      │
                                  [30 sec]
                                      │
                                      ▼
                                 HALF-OPEN
                                      │
                    [success]─────────┼─────────[failure]
                        │             │              │
                        ▼             │              ▼
                    CLOSED            │           OPEN
                                      │
                              [5 total failures]
                                      │
                                      ▼
                                 ESCALATE
```

### Circuit Breaker Logic

```python
class CircuitBreaker:
    def __init__(self):
        self.failures = 0
        self.state = "CLOSED"
        self.last_failure = None

    def record_failure(self):
        self.failures += 1
        self.last_failure = now()

        if self.failures >= 5:
            return "ESCALATE"
        elif self.failures >= 3:
            self.state = "OPEN"
            return "PAUSE"
        return "RETRY"

    def record_success(self):
        self.failures = 0
        self.state = "CLOSED"

    def can_proceed(self):
        if self.state == "CLOSED":
            return True
        if self.state == "OPEN":
            if now() - self.last_failure > 30:
                self.state = "HALF-OPEN"
                return True
            return False
        return True  # HALF-OPEN: try one request
```

## Timeout Recovery

### What to Capture on Timeout

When a timeout occurs, preserve state for resume:

```json
{
  "timeout_event": {
    "timestamp": "ISO8601",
    "scope": "step | flow | llm_call | tool",
    "timeout_ms": 600000,
    "elapsed_ms": 600123
  },
  "last_known_state": {
    "step_id": "build-step-3",
    "agent_key": "code-implementer",
    "phase": "work | finalize | route",
    "progress_indicator": "string (if available)"
  },
  "partial_artifacts": [
    {
      "path": "RUN_BASE/build/partial_impl.py",
      "complete": false,
      "bytes_written": 4523
    }
  ],
  "context_for_resume": {
    "last_successful_checkpoint": "build-step-2",
    "uncommitted_changes": ["src/auth.py", "tests/test_auth.py"],
    "transcript_path": "RUN_BASE/build/llm/step-3-partial.jsonl"
  }
}
```

### Partial Artifact Handling

On timeout:
1. Write partial receipt with `status: "timeout"`
2. Flush any buffered file writes
3. Capture git status (uncommitted changes)
4. Write transcript up to interruption point
5. Log timeout event to `RUN_BASE/<flow>/timeouts.jsonl`

### Resume After Timeout

```python
def resume_after_timeout(run_id, flow_key, timeout_event):
    checkpoint = timeout_event["context_for_resume"]["last_successful_checkpoint"]

    if has_uncommitted_changes(timeout_event):
        # Offer options
        return {
            "options": ["retry_step", "discard_and_retry", "escalate"],
            "recommendation": "retry_step",
            "reason": "Partial work exists that may be salvageable"
        }
    else:
        # Clean retry
        return resume_from_step(checkpoint)
```

## Timeout Logging

All timeouts are logged to `RUN_BASE/<flow>/timeouts.jsonl`:

```json
{
  "timestamp": "2024-01-15T10:30:00Z",
  "run_id": "abc123",
  "flow_key": "build",
  "step_id": "step-3",
  "scope": "llm_call",
  "timeout_ms": 120000,
  "elapsed_ms": 120034,
  "retry_count": 2,
  "final_action": "escalate | retry | fail",
  "recovery_path": "RUN_BASE/build/receipts/step-3-timeout.json"
}
```

## The Rule

> Concrete timeouts prevent runaway operations.
> Transient errors get retries with backoff. Permanent errors fail fast.
> Circuit breakers prevent cascading failures.
> Always capture state for resume on timeout.

## Configuration Override

Per-flow timeout overrides in flow spec:

```yaml
timeouts:
  step: 900000     # 15 minutes for complex flows
  llm_call: 180000 # 3 minutes for complex prompts
```

Per-step overrides:

```yaml
steps:
  - id: heavy-analysis
    timeout_override: 1200000  # 20 minutes for this step
```

## Current Implementation

| Feature | Status | Location |
|---------|--------|----------|
| Step timeout | Supported | Kernel enforces via asyncio |
| LLM timeout | Supported | Transport layer |
| Retry with backoff | Designed | Transports implement |
| Circuit breaker | Designed | Kernel would implement |
| Timeout artifacts | Supported | `receipt_io.py` handles partial |

---

## See Also
- [resume-protocol.md](./resume-protocol.md) - Checkpoint semantics for recovery
- [navigator-protocol.md](./navigator-protocol.md) - Routing after timeout/failure
- [routing-decisions.md](./routing-decisions.md) - ESCALATE decision for circuit breaker
