# Fix-Forward Vocabulary

The system uses explicit vocabulary to prevent bureaucracy and maintain velocity.

## Valid Outcomes

Every agent ends in one of these states:

### Needs Fixes
Issues found that can be fixed by iteration or routing.
```json
{
  "status": "UNVERIFIED",
  "concerns": [...],
  "routing": {
    "recommendation": "LOOP",
    "can_further_iteration_help": true
  }
}
```
**Next action:** Route to fixer (author in microloop, or dedicated fixer agent).

### Cannot Proceed (Mechanical)
Environment or infrastructure issue prevents work.
```json
{
  "status": "BLOCKED",
  "reason": "pytest not installed",
  "routing": {
    "recommendation": "ESCALATE",
    "reason": "Environment issue requires human fix"
  }
}
```
**Next action:** Fix environment, then retry.

### Needs Human Decision
Choice that cannot be derived from specs or evidence.
```json
{
  "status": "BLOCKED",
  "decision_needed": {
    "question": "Should we use OAuth or API keys for auth?",
    "options": ["OAuth", "API Keys"],
    "context": "ADR-001 doesn't specify auth method"
  }
}
```
**Next action:** Human answers, then continue.

### Not Safe to Publish Yet
Boundary check found issue.
```json
{
  "status": "BLOCKED",
  "boundary_issue": {
    "type": "secrets_detected",
    "location": "src/config.py:15",
    "recommendation": "Remove API key before merge"
  }
}
```
**Next action:** Remediate boundary issue, then retry publish.

### Ready to Advance
Work complete, no issues.
```json
{
  "status": "VERIFIED",
  "routing": {
    "recommendation": "CONTINUE"
  }
}
```
**Next action:** Advance to next step.

## Invalid Patterns

These patterns indicate vocabulary misuse:

### ❌ Blocked Because Ambiguous
**Wrong:**
```json
{
  "status": "BLOCKED",
  "reason": "Requirements are ambiguous"
}
```

**Right:**
```json
{
  "status": "UNVERIFIED",
  "assumptions": [
    {
      "assumption": "User means OAuth when they say 'login'",
      "why": "Most common interpretation",
      "impact_if_wrong": "Would need to refactor auth module"
    }
  ]
}
```
**Rule:** Make documented assumption, proceed with UNVERIFIED.

### ❌ Blocked Because Uncertain
**Wrong:**
```json
{
  "status": "BLOCKED",
  "reason": "Not sure if this approach is correct"
}
```

**Right:**
```json
{
  "status": "UNVERIFIED",
  "concerns": [
    {
      "description": "Approach may not scale beyond 10k users",
      "severity": "MEDIUM",
      "recommendation": "Review scaling strategy at gate"
    }
  ]
}
```
**Rule:** State uncertainty as concern, proceed.

### ❌ Need Approval to Continue
**Wrong:**
```json
{
  "status": "BLOCKED",
  "reason": "Waiting for approval to proceed"
}
```

**Right:** Complete the work. Gate at flow boundary.

**Rule:** Flows don't stop mid-flow for approval. Complete work, document concerns, gate at boundary.

### ❌ Blocked by Style Preference
**Wrong:**
```json
{
  "status": "BLOCKED",
  "reason": "Code doesn't match preferred style"
}
```

**Right:**
```json
{
  "routing": {
    "recommendation": "DETOUR",
    "detour_target": "auto-linter",
    "reason": "Style issues are mechanical, route to linter"
  }
}
```
**Rule:** Style issues are mechanical. Route to auto-linter, not block.

## BLOCKED is Rare

BLOCKED is reserved for:
1. Missing input artifacts (literally don't exist)
2. Environment/infrastructure failure
3. Non-derivable human decision needed
4. Boundary violation (publish safety)

**BLOCKED is NOT for:**
- Ambiguity (make assumption)
- Uncertainty (document concern)
- Style issues (route to linter)
- "Needs review" (that's what gates are for)

## The Rule

> Fix-forward by default. BLOCKED is rare and literal.
> Ambiguity → assumption. Uncertainty → concern. Style → auto-fix.
> Flows complete; gates review.
