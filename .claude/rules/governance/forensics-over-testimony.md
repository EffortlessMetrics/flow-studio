# Forensics Over Testimony: The Sheriff Pattern

**"Don't listen to the worker; measure the bolt."**

The Sheriff pattern means routing decisions are based on forensic evidence, not agent claims.

## The Problem

Agents will claim:
- "Tests passed"
- "All requirements implemented"
- "Code is secure"
- "Everything works"

These are **testimony**—claims that may or may not be true.

## The Solution

The kernel runs forensic tools and makes decisions based on **physical evidence**:
- Exit codes (did the command succeed?)
- File existence (does the artifact exist?)
- Output parsing (what did the tool actually report?)
- Diff analysis (what actually changed?)

## Evidence Hierarchy

| Level | Type | Example | Trust |
|-------|------|---------|-------|
| 1 | Physics | Exit code, file hash | Highest |
| 2 | Receipts | Captured tool output | High |
| 3 | Artifacts | Generated files | Medium |
| 4 | Narrative | Agent prose claims | Lowest |

When levels conflict, higher levels win.

## Forensic Tools

The Sheriff uses these tools:

### DiffScanner
Analyzes git diffs:
```json
{
  "files_changed": 5,
  "additions": 120,
  "deletions": 45,
  "file_types": { ".py": 3, ".md": 2 }
}
```

### TestParser
Parses test output:
```json
{
  "framework": "pytest",
  "passed": 42,
  "failed": 2,
  "skipped": 1,
  "duration_ms": 1234
}
```

### LintScanner
Parses linter output:
```json
{
  "errors": 0,
  "warnings": 5,
  "fixable": 3
}
```

### SecurityScanner
Parses security scan output:
```json
{
  "vulnerabilities": 0,
  "severity": { "high": 0, "medium": 0, "low": 0 }
}
```

## The Cross-Examination Test

Before trusting a claim, ask:

1. **Is there physical evidence?** (exit code, file, log)
2. **Can it be reproduced?** (run the command again)
3. **Does it corroborate the claim?** (evidence matches narrative)
4. **Is it fresh?** (from this commit, not stale)

If any answer is "no," the claim is **unverified**.

## Evidence Corroboration

Multiple evidence sources should agree:

| Claim | Evidence Required |
|-------|-------------------|
| "Tests pass" | pytest exit code 0 + captured output |
| "Lint clean" | linter exit code 0 + captured output |
| "Secure" | scanner exit code 0 + captured output |
| "Implemented" | diff exists + tests cover new code |

Single-source claims are suspect.

## The Rule

> Never route based on narrative alone.
> Always require forensic evidence.
> When evidence is missing, status is UNKNOWN, not assumed.

## Applying the Sheriff Pattern

### At Step Completion
```python
# Bad: Trust the agent
if agent_says("tests passed"):
    advance()

# Good: Check the evidence
test_result = parse_pytest_output(captured_log)
if test_result.exit_code == 0 and test_result.failed == 0:
    advance()
```

### At Routing Decisions
```python
# Bad: Route based on narrative
if envelope.summary contains "ready for review":
    route_to_critic()

# Good: Route based on forensics
if forensics.tests.passed > 0 and forensics.lint.errors == 0:
    route_to_critic()
```

### At Gate Decisions
```python
# Bad: Approve based on claims
if agent_says("all checks pass"):
    recommend_merge()

# Good: Verify evidence panel
if all_evidence_exists() and all_evidence_fresh() and all_checks_pass():
    recommend_merge()
```

## Unknown is Valid

When evidence is missing:
```json
{
  "tests": {
    "measured": false,
    "reason": "No test output captured"
  }
}
```

**UNKNOWN is honest.** It means:
- We didn't measure this
- The claim is unverified
- Human judgment required

**Assumed pass is dangerous.** Absence of evidence ≠ evidence of absence.

## Anti-Patterns

### Testimony-Based Routing
```
Agent says: "All requirements implemented"
Evidence: None
Action: Advance to gate
```
**Problem:** No forensic verification.

### Stale Evidence
```
Evidence: Tests passed (3 commits ago)
Current commit: Different files changed
Action: Trust old evidence
```
**Problem:** Evidence doesn't match current state.

### Single-Source Trust
```
Evidence: Agent-generated receipt says "pass"
Verification: None
Action: Trust the receipt
```
**Problem:** Agent generated its own evidence.

---

## See Also
- [evidence-discipline.md](./evidence-discipline.md) - What counts as evidence
- [truth-hierarchy.md](./truth-hierarchy.md) - Evidence levels
- [navigator-protocol.md](../execution/navigator-protocol.md) - Forensics in routing
