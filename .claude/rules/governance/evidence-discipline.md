# Evidence Discipline

**"Don't listen to the worker; measure the bolt."**

This rule defines how the system distinguishes agent claims from forensic evidence.

## The Sheriff Pattern

The kernel runs forensic tools (DiffScanner, TestParser, MetricParser) and the Navigator
makes routing decisions based on this physical evidence—not the agent's narrative.

### What Counts as Evidence

| Evidence Type | Source | Trust Level |
|---------------|--------|-------------|
| Exit codes | Process execution | Physics |
| Test counts | pytest/jest output parsing | Receipt |
| Diff summary | git diff analysis | Receipt |
| File hashes | Filesystem | Physics |
| Line counts | wc, grep | Receipt |
| Coverage % | Coverage tools | Receipt |
| Scan results | Security/lint tools | Receipt |

### What Does NOT Count as Evidence

| Claim Type | Why It's Insufficient |
|------------|----------------------|
| "Tests passed" | No output cited |
| "All requirements met" | No spec cross-reference |
| "Security is fine" | No scan log |
| "Code is complete" | No diff or file list |
| "I fixed the bug" | No before/after evidence |

## Measured vs Estimated vs Unknown

Every metric in receipts or routing must be labeled:

### MEASURED
- Value comes from running a command
- Evidence path provided
- Can be reproduced

### ESTIMATED
- Value derived from heuristics or sampling
- Method + confidence + range provided
- Flagged for validation

### UNKNOWN
- Not measured, not estimated
- Explicitly stated as "unknown" or "not measured"
- **Never guessed or omitted**

## The Rule

> If we claim it, we must be able to point to a reproducible artifact proving it.

## Enforcement

Receipts that claim success without evidence pointers are flagged by:
1. `receipt_io.py` validation (required fields)
2. Gate agents (require evidence before merge recommendation)
3. Forensic scanners (compare claims to measured reality)

## Example: Code Critic Evidence

Bad:
```
The implementation looks correct and follows the spec.
```

Good:
```
## Evidence
- Spec compliance: 8/10 requirements have matching implementation (see checklist.md:15-45)
- Test coverage: 78% line coverage (evidence: coverage.json)
- Style: 0 lint errors (evidence: eslint_output.log)
- Security: Not measured (no SAST tool configured)

## Concerns
- Requirement REQ-004 has no corresponding test (tests/test_auth.py missing)
- Function `validate_token` at src/auth.py:42 lacks error handling
```
