# Forensic Scanners: The Sheriff's Tools

> **Status:** Living document
> **Purpose:** Document the forensic tools that produce ground truth

## The Role of Scanners

Scanners are the "Sheriff's deputies" - they measure reality so routing decisions are based on evidence, not narrative.

The Sheriff Pattern (see [CLAIMS_VS_EVIDENCE.md](./CLAIMS_VS_EVIDENCE.md)) establishes the principle: **don't trust the worker, measure the bolt**. Scanners are the measurement tools that make this possible.

```
Worker produces output + narrative
        |
        v
Kernel runs scanners on output
        |
        v
Scanners produce structured evidence
        |
        v
Navigator routes based on evidence
        |
        v
Narrative is ignored for routing
```

## The Scanner Taxonomy

### DiffScanner

**Location:** `swarm/runtime/diff_scanner.py`

**Purpose:** Analyze git changes to capture ALL mutations made during a step

**Design Philosophy:**
- Tool telemetry misses: bash scripts, formatters, generators, indirect edits
- Git diff captures everything: insertions, deletions, modifications, renames
- Post-step scanning is authoritative; agent narrative is supplementary

**Input:** Git repository state (working directory)

**Output:**
```json
{
  "files": [
    {
      "path": "src/auth.py",
      "status": "M",
      "insertions": 50,
      "deletions": 10,
      "old_path": null
    }
  ],
  "total_insertions": 120,
  "total_deletions": 45,
  "untracked": ["src/new_file.py"],
  "staged": ["src/auth.py"],
  "scan_error": null,
  "summary": "5 files changed, +120, -45"
}
```

**Use Cases:**
- Verify work was actually done (not just claimed)
- Categorize change types for routing
- Detect "claimed progress no diff" reward hacking
- Capture file changes for HandoffEnvelope

**Key Types:**
- `FileDiff`: Single file change record (path, status, insertions, deletions)
- `FileChanges`: Complete scan result with totals and summaries

### TestParser

**Location:** `swarm/runtime/test_parser.py`

**Purpose:** Parse test execution output from various frameworks into standardized format

**Design Philosophy:**
- Parse raw output, not agent claims
- Extract error signatures for Elephant Protocol stall detection
- Support multiple frameworks without external dependencies
- Produce consistent output regardless of input format

**Supported Frameworks:**
- pytest (console output)
- JUnit XML (pytest --junitxml, Jest, Cargo, Maven)
- Playwright traces (ZIP archives, JSON reports)

**Input:** Raw test output (string) or file path (JUnit XML, Playwright trace)

**Output:**
```json
{
  "total": 45,
  "passed": 42,
  "failed": 3,
  "skipped": 2,
  "errors": 0,
  "duration_ms": 12500,
  "source_format": "pytest",
  "failures": [
    {
      "test_name": "test_login_invalid_password",
      "error_message": "AssertionError: Expected 401, got 200",
      "test_file": "tests/test_auth.py",
      "test_line": 45,
      "failure_type": "assertion",
      "expected": "401",
      "actual": "200"
    }
  ],
  "error_signatures": ["a3f2b1c9e8d7f6a5"],
  "coverage_percent": 78.5
}
```

**Use Cases:**
- Determine if tests actually pass (not just claimed)
- Extract failure details for routing decisions
- Detect stall conditions via error_signatures
- Calculate pass rate for gate decisions

**Key Types:**
- `TestSummary`: Standardized test summary for Navigator
- `TestFailure`: Detailed failure information (from `forensic_types.py`)
- `FailureType`: Category of failure (assertion, timeout, setup, etc.)

### ForensicComparator

**Location:** `swarm/runtime/forensic_comparator.py`

**Purpose:** Compare worker's handoff claims against actual evidence to catch reward hacking

**Design Philosophy:**
- Worker claims in HandoffEnvelope are hypotheses, not facts
- DiffScanner results are authoritative (what actually changed)
- TestParseResult shows actual test outcomes (not claimed outcomes)
- ForensicVerdict gives Navigator confidence signal for routing

**Input:** HandoffEnvelope + DiffScanResult + TestParseResult

**Output:**
```json
{
  "claim_verified": false,
  "confidence": 0.45,
  "discrepancies": [
    {
      "category": "test_outcome",
      "claim": "tests pass",
      "evidence": "3 tests failed",
      "severity": "critical",
      "details": "Claimed tests pass but 3 failures found"
    }
  ],
  "reward_hacking_flags": [
    "claimed_pass_but_failed",
    "claimed_verified_with_failures"
  ],
  "recommendation": "REJECT",
  "summary": "2 discrepancies found; 2 reward hacking patterns",
  "evidence_hashes": {
    "diff_scan": "a1b2c3d4...",
    "test_summary": "e5f6g7h8..."
  }
}
```

**Reward Hacking Patterns Detected:**
| Flag | Description |
|------|-------------|
| `test_count_decreased` | Tests removed between iterations |
| `coverage_dropped` | Coverage percentage decreased |
| `tests_deleted` | Explicit test file deletions |
| `claimed_pass_but_failed` | Summary says "tests pass" but failures exist |
| `claimed_progress_no_diff` | Claims progress but git shows no changes |
| `claimed_verified_with_failures` | VERIFIED status but tests failing |
| `file_changes_mismatch` | Claimed file count doesn't match actual |
| `unverified_claims_high_confidence` | High confidence claimed despite evidence issues |

**Verdict Recommendations:**
- `TRUST`: Claims align with evidence; proceed normally
- `VERIFY`: Minor discrepancies; Navigator should double-check
- `REJECT`: Major discrepancies; likely reward hacking

### ForensicTypes

**Location:** `swarm/runtime/forensic_types.py`

**Purpose:** Provide Python dataclasses for forensic verification and progress evidence

**Design Philosophy:**
- Agent claims are narrative; forensic scans are reality
- Markers bind evidence to claims, enabling verification
- Progress deltas detect stalls: activity without meaningful change
- Every dataclass has `to_dict()` and `from_dict()` for serialization

**Key Types:**

**ForensicMarker** - Binds evidence to agent claims:
```json
{
  "marker_id": "fm-a1b2c3d4",
  "marker_type": "diff_scan",
  "evidence_hash": "sha256...",
  "claim": "Created file src/auth.py",
  "reality": "File src/auth.py exists with 120 lines",
  "match": true,
  "confidence": 1.0
}
```

**DiffScanResult** - Schema-aligned diff scan output:
```json
{
  "files": [...],
  "total_insertions": 120,
  "total_deletions": 45,
  "scan_hash": "sha256...",
  "head_commit": "abc123",
  "base_commit": "def456"
}
```

**TestParseResult** - Parsed test execution results:
```json
{
  "total_tests": 45,
  "passed": 42,
  "failed": 3,
  "failures": [...],
  "test_framework": "pytest",
  "raw_output_hash": "sha256..."
}
```

**ProgressDelta** - Computed difference for stall detection:
```json
{
  "files_added": 2,
  "files_modified": 3,
  "lines_added": 120,
  "lines_removed": 45,
  "test_pass_delta": 5,
  "test_fail_delta": -2,
  "has_meaningful_change": true,
  "stall_indicator": false,
  "progress_score": 0.75
}
```

**StallAnalysis** - Elephant Protocol trigger analysis:
```json
{
  "is_stalled": false,
  "stall_type": null,
  "stall_duration_iterations": 0,
  "elephant_protocol_trigger": false,
  "recommended_action": "continue"
}
```

## Scanner Integration

### In Routing

Navigator receives scanner output, not raw logs:

```json
{
  "forensics": {
    "diff": {
      "files_changed": 5,
      "total_insertions": 120,
      "total_deletions": 45
    },
    "tests": {
      "passed": 42,
      "failed": 0,
      "status": "PASSING"
    },
    "verdict": {
      "claim_verified": true,
      "recommendation": "TRUST",
      "confidence": 0.95
    }
  }
}
```

### In Receipts

Scanner results are captured as evidence in receipts:

```json
{
  "evidence": {
    "tests": {
      "measured": true,
      "scanner": "TestParser",
      "result_path": "RUN_BASE/build/test_results.json"
    },
    "diff": {
      "measured": true,
      "scanner": "DiffScanner",
      "scan_hash": "a1b2c3d4..."
    }
  }
}
```

### In HandoffEnvelope

File changes captured directly in handoff:

```python
from swarm.runtime.diff_scanner import scan_file_changes, file_changes_to_dict

# After step execution, before finalization commit
changes = await scan_file_changes(repo_root)

# Include in envelope
envelope.file_changes = file_changes_to_dict(changes)
```

## The Elephant Protocol

Scanners enable the Elephant Protocol - stall detection that breaks loops without progress.

**Stall Detection Logic:**
```python
def compute_stall_indicator(delta: ProgressDelta) -> bool:
    # No file changes at all
    no_file_changes = (delta.files_added + delta.files_modified) == 0

    # Zero meaningful progress indicators
    zero_progress = (
        delta.tests_added == 0
        and delta.test_pass_delta <= 0
        and (delta.coverage_delta is None or delta.coverage_delta <= 0)
    )

    # High churn with no forward motion
    high_churn = (delta.lines_added + delta.lines_removed) > 100
    low_net_progress = abs(delta.net_lines) < 10

    return no_file_changes or (zero_progress and not delta.files_added)
```

**Stall Types:**
| Type | Description |
|------|-------------|
| `no_file_changes` | Step made no file modifications |
| `same_test_failures` | Same tests failing across iterations |
| `zero_progress_delta` | No improvement in any metric |
| `high_churn_low_progress` | Many changes but no net progress |
| `claims_without_evidence` | Worker claims unverifiable |

## Adding New Scanners

To add a new scanner:

1. **Define output schema** in `forensic_types.py`:
   - Create dataclass with required fields
   - Add `to_dict()` and `from_dict()` functions
   - Add schema documentation

2. **Implement parser** in `swarm/runtime/`:
   - Parse tool output to structured format
   - Handle errors gracefully
   - Return empty/default values on parse failure

3. **Register in forensic aggregation**:
   - Add to ForensicComparator if used for claim verification
   - Add to Navigator context injection

4. **Add to evidence capture**:
   - Update HandoffEnvelope if needed
   - Add to receipt evidence section

## Current Implementation Status

| Scanner | Location | Status |
|---------|----------|--------|
| DiffScanner | `diff_scanner.py` | Implemented |
| TestParser | `test_parser.py` | Implemented |
| ForensicComparator | `forensic_comparator.py` | Implemented |
| ForensicTypes | `forensic_types.py` | Implemented |
| CoverageAnalyzer | - | Via TestParser (coverage_percent) |
| LintScanner | - | Planned |
| SecurityScanner | - | Planned |
| ComplexityAnalyzer | - | Planned |

## The Rule

> Scanners produce ground truth. Routing trusts scanners, not narrative.
> Every claim should have a scanner that can verify it.

This is "Forensics Over Narrative" in action:
- Workers produce work and claims
- Scanners measure what actually happened
- Navigator routes based on measurements
- Claims without evidence are ignored
