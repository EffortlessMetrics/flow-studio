# Navigator Protocol: The Routing Brain

The Navigator is an LLM call that makes routing decisions when deterministic rules are insufficient.

## When Navigator Runs

Navigator is invoked **only when deterministic routing fails**:

```
1. Fast-Path (No LLM) → If matches, route directly
2. Deterministic Checks → If matches, route directly
3. Navigator (LLM) → Only if above fail
4. Envelope Fallback → Legacy path
5. Escalate → Failure case
```

Navigator is expensive (LLM call). Avoid it when possible.

## Navigator Input: Compact Forensics

Navigator receives a **forensic summary**, not raw data:

```json
{
  "step_completed": "build-step-3",
  "agent": "code-implementer",
  "status": "UNVERIFIED",
  "forensics": {
    "tests": { "passed": 42, "failed": 2, "skip": 0 },
    "lint": { "errors": 0 },
    "diff": { "files": 5, "additions": 120, "deletions": 45 },
    "concerns": [
      { "severity": "HIGH", "description": "Missing error handling", "location": "src/auth.py:42" }
    ]
  },
  "iteration": { "current": 2, "max": 3 },
  "previous_failure_signature": null
}
```

Navigator sees **measurements**, not narrative.

## Navigator Output: Bounded Decision

Navigator produces a routing decision from a closed vocabulary:

```json
{
  "decision": "LOOP | CONTINUE | DETOUR | INJECT_FLOW | ESCALATE",
  "next_step_id": "string (if applicable)",
  "detour_target": "string (if DETOUR)",
  "reason": "string (justification)",
  "confidence": "HIGH | MEDIUM | LOW"
}
```

## Decision Vocabulary

| Decision | When Used | Example |
|----------|-----------|---------|
| **CONTINUE** | Ready to advance | Tests pass, no HIGH concerns |
| **LOOP** | Needs iteration | Critic found fixable issues |
| **DETOUR** | Known fix pattern | Lint errors → auto-linter |
| **INJECT_FLOW** | Need another flow | Upstream diverged → Flow 8 |
| **INJECT_NODES** | Novel requirement | Ad-hoc steps needed |
| **ESCALATE** | Cannot proceed | Human decision required |
| **TERMINATE** | Flow complete | Terminal step reached |

## Signature Matching

Navigator recognizes **failure signatures** and routes to known fixes:

| Signature | Detour Target | Description |
|-----------|---------------|-------------|
| `lint_errors` | `auto-linter` | Fixable style issues |
| `missing_import` | `import-fixer` | ImportError in tests |
| `type_mismatch` | `type-annotator` | Type checking failures |
| `test_fixture_missing` | `test-setup` | FixtureNotFoundError |
| `upstream_diverged` | `Flow 8 (Reset)` | Behind upstream |

When signature matches, skip generic iteration.

## Goal-Alignment Test

Every Navigator decision passes this test:

> "Does this help achieve the flow's objective?"

Navigator checks against the flow charter:
- Does the decision serve the goal?
- Is it within scope (not a non-goal)?
- Will it help answer the key question?

If the decision drifts from charter, Navigator rejects it.

## Microloop Exit Conditions

Navigator knows when to exit microloops:

1. **Status == VERIFIED** → CONTINUE
2. **can_further_iteration_help == false** → CONTINUE (with concerns)
3. **Iteration limit reached** → CONTINUE (with warnings)
4. **Repeated failure signature** → DETOUR to known fix

Navigator never loops indefinitely.

## Navigator Model

Navigator uses **economy tier** (haiku):
- Decisions are bounded
- Input is structured
- Speed matters
- Low judgment (evidence-based)

Complex reasoning happens in agents. Navigator just routes.

## Kernel Validation

Kernel validates Navigator decisions:
- Decision is in vocabulary
- Next step exists in flow graph
- Detour target exists
- No graph constraint violations

Invalid decisions are rejected and logged.

## Off-Road Logging

All Navigator decisions are logged:

```
RUN_BASE/<flow>/routing/decisions.jsonl

{
  "timestamp": "ISO8601",
  "step_id": "build-step-3",
  "decision": "DETOUR",
  "detour_target": "auto-linter",
  "reason": "5 fixable lint errors detected",
  "forensic_summary": {...}
}
```

Every non-CONTINUE decision is an "off-road" event.

## The Rule

> Navigator routes based on forensics, not narrative.
> Decisions are bounded, validated, and logged.
> When in doubt, escalate—never guess.

---

## See Also
- [routing-decisions.md](./routing-decisions.md) - Decision vocabulary
- [detour-catalog.md](./detour-catalog.md) - Known fix patterns
- [microloop-rules.md](./microloop-rules.md) - Exit conditions
