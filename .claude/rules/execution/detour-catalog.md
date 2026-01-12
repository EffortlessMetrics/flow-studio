# Detour Catalog: Known Fix Patterns

Detours (sidequests) are pre-defined response patterns for known failure modes. When a signature is detected, route to the known fix instead of generic iteration.

## Why Detours Exist

Generic iteration is expensive:
- Full agent cycle for known problems
- Re-discovery of known solutions
- Token waste on solved patterns

Detours are cheap:
- Pattern matched, solution applied
- Skip the discovery phase
- Fast, focused fix

## Detour Registry

### Auto-Linter (lint-fix)
**Signature:** Lint errors in diff
**Trigger:**
```json
{
  "forensics": {
    "lint": { "errors": 5, "fixable": 5 }
  }
}
```
**Action:** Route to auto-linter skill
**Resolution:** Apply fixes, re-run lint, verify clean
**Return:** Continue from where we left off

### Import Fixer (import-fix)
**Signature:** Missing import errors
**Trigger:**
```json
{
  "test_failures": [
    { "type": "ImportError", "module": "os" }
  ]
}
```
**Action:** Add missing imports
**Resolution:** Analyze imports, add missing, verify passes
**Return:** Continue to next step

### Type Annotator (type-fix)
**Signature:** Type checking errors
**Trigger:**
```json
{
  "lint": {
    "errors": [
      { "rule": "type-mismatch", "count": 3 }
    ]
  }
}
```
**Action:** Fix type annotations
**Resolution:** Analyze types, add/fix annotations, verify mypy passes
**Return:** Continue from where we left off

### Test Fixture Creator (fixture-fix)
**Signature:** Missing test fixtures
**Trigger:**
```json
{
  "test_failures": [
    { "type": "FixtureNotFoundError", "fixture": "db_session" }
  ]
}
```
**Action:** Create missing fixtures
**Resolution:** Identify needed fixtures, create conftest entries, verify tests run
**Return:** Continue with tests

### Dependency Resolver (dep-fix)
**Signature:** Missing dependencies
**Trigger:**
```json
{
  "test_failures": [
    { "type": "ModuleNotFoundError", "module": "requests" }
  ]
}
```
**Action:** Add missing dependencies
**Resolution:** Add to requirements/package.json, install, verify import
**Return:** Continue from where we left off

### Merge Conflict Resolver (conflict-fix)
**Signature:** Git merge conflicts
**Trigger:**
```json
{
  "git_status": {
    "conflicts": ["src/auth.py", "tests/test_auth.py"]
  }
}
```
**Action:** Resolve conflicts
**Resolution:** Analyze conflicts, apply resolution strategy, verify clean merge
**Return:** Continue with build

### Flow 8: Rebase (upstream-sync)
**Signature:** Upstream divergence
**Trigger:**
```json
{
  "git_status": {
    "behind_upstream": 15,
    "conflicts_likely": true
  }
}
```
**Action:** Inject Flow 8 (Reset/Rebase)
**Resolution:** Fetch upstream, rebase, resolve conflicts
**Return:** Resume interrupted flow

## Detour Flow

```
Step execution
     |
     v
Failure detected
     |
     v
Signature matched? --no--> Generic iteration
     | yes
     v
Route to detour
     |
     v
Detour executes fix
     |
     v
Verify fix
     |
     v
Return to main path
```

## Detour Routing Schema

```json
{
  "routing": {
    "decision": "DETOUR",
    "detour_id": "lint-fix",
    "reason": "5 fixable lint errors detected",
    "signature": {
      "type": "lint_errors",
      "fixable": 5
    },
    "return_to": "build-step-3",
    "max_attempts": 2
  }
}
```

## Detour Limits

Detours have attempt limits:
- Default: 2 attempts per detour type per step
- After limit: Escalate to human or advance with warnings

```json
{
  "detour_attempts": {
    "lint-fix": 2,
    "import-fix": 1
  },
  "status": "LIMIT_REACHED",
  "action": "ESCALATE"
}
```

## Adding New Detours

To add a new detour:
1. Identify the recurring failure pattern
2. Define the signature (what triggers it)
3. Define the fix (skill or agent)
4. Define verification (how to know it worked)
5. Add to catalog

## The Rule

> Known problems deserve known solutions.
> Match signatures to detours before generic iteration.
> Detours are cheap; re-discovery is expensive.

## Current Implementation

Detours are implemented as:
- Skills (auto-linter, test-runner)
- Flow injection (Flow 8 for rebase)
- Routing rules in Navigator
