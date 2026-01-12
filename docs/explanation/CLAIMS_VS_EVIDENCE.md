# Claims vs Evidence: The Sheriff Pattern

> **Status:** Living document
> **Purpose:** Teaching doc for evidence discipline

## The Core Insight

LLMs are **convincing narrators**. They produce plausible-sounding output
that may or may not be true.

The failure mode is not gibberish. It's **confident errors**:
- "Tests passed" (they didn't)
- "All requirements implemented" (3 are missing)
- "Security is handled" (SQL injection exists)

## The Sheriff Pattern

Flow Studio implements the "Sheriff" pattern:

```
┌─────────────────────────────────────────┐
│            Worker Agent                 │
│  (Produces work + narrative)            │
│                                         │
│  "I implemented the auth module.        │
│   Tests are passing. Code is secure."   │
└────────────────────┬────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────┐
│           Sheriff (Kernel)              │
│  (Runs forensic tools)                  │
│                                         │
│  pytest → exit code 1, 3 failures       │
│  diff → 5 files, 120 lines added        │
│  scan → 2 security warnings             │
└────────────────────┬────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────┐
│            Navigator                    │
│  (Decides based on evidence)            │
│                                         │
│  "Tests failed. Route to fixer."        │
└─────────────────────────────────────────┘
```

**The Sheriff doesn't trust workers. The Sheriff measures.**

## What Counts as Evidence

### Physics (Highest Trust)
| Evidence | Source | Example |
|----------|--------|---------|
| Exit codes | OS | `pytest` returned 1 |
| File existence | Filesystem | `src/auth.py` exists |
| Git status | Git | 3 files modified |
| Process output | Runtime | "FAILED: test_login" |

### Receipts (Recorded Physics)
| Evidence | Source | Example |
|----------|--------|---------|
| Test output | Captured log | `test_output.log` |
| Coverage report | Tool output | 78.5% line coverage |
| Lint results | Captured scan | 0 errors, 5 warnings |
| Diff summary | Git diff | +120 lines, -45 lines |

### NOT Evidence (Claims)
| Claim | Why Insufficient |
|-------|------------------|
| "Tests passed" | No output cited |
| "Code is secure" | No scan results |
| "Requirements met" | No spec cross-ref |
| "Everything works" | Nothing measured |

## The Evidence Discipline

### Rule 1: Measured vs Claimed

Every statement about outcomes must be one of:

**MEASURED**: Value from running a command
```json
{
  "tests": {
    "measured": true,
    "command": "pytest tests/ -v",
    "passed": 42,
    "failed": 0,
    "evidence": "RUN_BASE/build/test_output.log"
  }
}
```

**ESTIMATED**: Derived from heuristics (with method)
```json
{
  "complexity": {
    "estimated": true,
    "method": "Cyclomatic complexity via radon",
    "value": "B (moderate)",
    "confidence": "HIGH"
  }
}
```

**UNKNOWN**: Not measured, not estimated
```json
{
  "security_scan": {
    "measured": false,
    "reason": "No SAST tool configured"
  }
}
```

### Rule 2: Evidence Pointers Required

Claims must include pointers to evidence:

❌ Bad:
```
Tests passed successfully.
```

✅ Good:
```
Tests: 42 passed, 0 failed (evidence: RUN_BASE/build/test_output.log:15-89)
```

### Rule 3: "Not Measured" is Valid

Honest uncertainty beats false certainty:

❌ Bad:
```
Security looks fine.
```

✅ Good:
```
Security: NOT MEASURED (no SAST tool configured; recommend adding before merge)
```

## The Forensic Tools

Flow Studio uses forensic tools to measure reality:

### DiffScanner
Analyzes git diff:
- Files changed
- Lines added/removed
- Types of changes (code, tests, docs)

### TestParser
Parses test output:
- Pass/fail counts
- Failure details
- Flaky test detection

### CoverageAnalyzer
Reads coverage reports:
- Line coverage %
- Branch coverage %
- Uncovered hotspots

### SecurityScanner
Runs security tools:
- SAST findings
- Dependency vulnerabilities
- Secrets detection

## Evidence in Routing

The Navigator receives **forensic evidence**, not claims:

```json
{
  "forensics": {
    "tests": {
      "passed": 42,
      "failed": 3,
      "status": "FAILING"
    },
    "lint": {
      "errors": 0,
      "warnings": 5
    },
    "diff": {
      "files": 5,
      "additions": 120,
      "deletions": 45
    }
  },
  "worker_claim": "Implementation complete",
  "evidence_status": "CONTRADICTED"
}
```

The Navigator sees the contradiction: worker claims "complete" but tests fail.

## Why This Matters

### Without Evidence Discipline
- Black box: "Trust me, it works"
- Review requires reading everything
- No reproducible verification
- Slow, expensive trust

### With Evidence Discipline
- Transparent: "Here's the evidence"
- Review focuses on hotspots
- Reproducible verification
- Fast, cheap trust

## The Economics

This is Steven Zimmerman's core insight:

> **Code generation is fast, good, and cheap. The bottleneck is trust.**

Evidence discipline is how you make trust cheap:
- Spend compute on verification (cheap)
- Save human attention for judgment (expensive)
- Trade ~$30 in API calls for 5 days of debugging

## The Rule

> "Don't listen to the worker; measure the bolt."
> Claims require evidence. "Not measured" is valid. False certainty is not.
