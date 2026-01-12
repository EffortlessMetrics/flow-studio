# Microloop Rules

Microloops are adversarial iteration patterns between author and critic agents.

## The Pattern

```
┌────────────────────────────────────────────────────────┐
│                                                        │
│   Author ──────────► Critic                            │
│      ▲                  │                              │
│      │                  │                              │
│      └──────────────────┘                              │
│         (if can_further_iteration_help)                │
│                                                        │
└────────────────────────────────────────────────────────┘
```

## Exit Conditions

Loops exit when ANY of these are true:

### 1. VERIFIED
Critic finds no issues.
```json
{
  "status": "VERIFIED",
  "routing": {
    "recommendation": "CONTINUE"
  }
}
```

### 2. No Viable Fix Path
Critic finds issues but iteration won't help.
```json
{
  "status": "UNVERIFIED",
  "routing": {
    "can_further_iteration_help": false,
    "reason": "Requires architectural change"
  }
}
```

### 3. Iteration Limit Reached
Configurable per flow. Default: 3.
```json
{
  "loop_iteration": 3,
  "max_iterations": 3
}
```

### 4. Repeated Failure Signature
Same error pattern twice in a row.
```json
{
  "failure_signature": "missing_import_os",
  "previous_failure_signature": "missing_import_os",
  "action": "DETOUR to known fix"
}
```

## Iteration Limits by Flow

| Flow | Default Limit | Rationale |
|------|---------------|-----------|
| Signal (Requirements) | 3 | Requirements should converge quickly |
| Build (Code) | 5 | Complex code may need more iteration |
| Build (Tests) | 3 | Tests should be straightforward |
| Review (Fixes) | 3 | Fix scope should be bounded |

## Critic Obligations

Critics MUST include:
- `can_further_iteration_help: boolean` - Can another iteration fix the issues?
- Specific, cited concerns with file:line
- Severity rating for each concern
- Clear recommendation

Critics MUST NOT:
- Fix the code themselves
- Approve to be nice
- Be vague about issues
- Skip the iteration judgment

## Fuse Detection

The kernel detects stuck conditions:

### Signature Matching
```python
def matches_previous_failure(current, previous):
    # Normalize error messages
    # Compare patterns
    # Return True if same root cause
```

### Budget Tracking
```python
if loop_iteration >= max_iterations:
    advance_with_warnings()
```

### Detour Routing
```python
if repeated_failure:
    route_to_known_fix_pattern()
```

## Known Fix Patterns

When specific failure signatures are detected, route to known fixes:

| Signature | Detour Target | Description |
|-----------|---------------|-------------|
| `lint_errors` | auto-linter skill | Run formatter/linter |
| `missing_import` | import-fixer | Add missing imports |
| `type_mismatch` | type-annotator | Fix type annotations |
| `test_fixture_missing` | test-setup | Create missing fixtures |

## The Rule

> Microloops exit when: VERIFIED, no viable fix path, limit reached, or stuck.
> Critics decide if iteration helps. Kernel enforces limits. Detours handle stuck patterns.
