# Build → Review Handoff Contract

> **Version:** 1.0.0
> **Status:** Canonical
> **Last Updated:** 2025-12-29

This document defines the **formal contract** between Flow 3 (Build) and Flow 4 (Review). It specifies exactly what artifacts Flow 3 must produce and what Flow 4 expects to consume.

---

## Contract Summary

| Producer | Consumer | Handoff Point | Key Artifact |
|----------|----------|---------------|--------------|
| Flow 3 (Build) | Flow 4 (Review) | `build_receipt.json` | PR metadata + build status |

---

## Flow 3 Outputs (Required)

### Primary Artifact: `RUN_BASE/build/build_receipt.json`

The `build_receipt.json` is the **canonical handoff artifact**. It MUST include:

```json
{
  "schema_version": "1.0.0",
  "run_id": "<run-id>",
  "timestamp": "<ISO 8601>",

  "status": "VERIFIED | UNVERIFIED | BLOCKED",
  "summary": "<Human-readable summary of build outcome>",

  "pr_metadata": {
    "pr_number": "<number or null>",
    "pr_url": "<URL or null>",
    "pr_state": "draft | open | null",
    "head_branch": "<branch name>",
    "base_branch": "main",
    "created_at": "<ISO 8601 or null>"
  },

  "ac_matrix": {
    "total": "<count>",
    "passed": "<count>",
    "failed": "<count>",
    "skipped": "<count>",
    "details": [
      {
        "ac_id": "AC-001",
        "status": "PASS | FAIL | SKIP",
        "evidence": "<path to test or artifact>"
      }
    ]
  },

  "test_summary": {
    "total": "<count>",
    "passed": "<count>",
    "failed": "<count>",
    "skipped": "<count>",
    "coverage_percent": "<number or null>"
  },

  "code_changes": {
    "files_added": ["<path>"],
    "files_modified": ["<path>"],
    "files_deleted": ["<path>"],
    "total_lines_added": "<count>",
    "total_lines_removed": "<count>"
  },

  "critiques": {
    "test_critique_status": "VERIFIED | UNVERIFIED",
    "code_critique_status": "VERIFIED | UNVERIFIED",
    "remaining_issues": ["<issue description>"]
  },

  "assumptions": [
    {
      "assumption": "<what was assumed>",
      "why": "<reason for assumption>",
      "impact_if_wrong": "<what changes if wrong>"
    }
  ],

  "concerns": [
    {
      "concern": "<description>",
      "severity": "low | medium | high",
      "recommendation": "<suggested action>"
    }
  ],

  "observations": [
    {
      "type": "action_taken | action_deferred | optimization_opportunity",
      "observation": "<what was noticed>",
      "reason": "<why acted or deferred>"
    }
  ]
}
```

### Supporting Artifacts

Flow 3 also produces these artifacts in `RUN_BASE/build/`:

| Artifact | Purpose | Required |
|----------|---------|----------|
| `test_changes_summary.md` | What tests were written/changed | Yes |
| `test_critique.md` | Critic's verdict on test quality | Yes |
| `impl_changes_summary.md` | What code was written/changed | Yes |
| `code_critique.md` | Critic's verdict on code quality | Yes |
| `self_review.md` | Final narrative summary | Yes |
| `mutation_report.md` | Mutation test results | Optional |
| `fix_summary.md` | Issues fixed during hardening | Optional |
| `clarification_questions.md` | Ambiguities encountered | If any |
| `git_status.md` | Git state after commit | Yes |

---

## Flow 4 Inputs (Expected)

### Required Inputs

1. **`RUN_BASE/build/build_receipt.json`**
   - MUST exist
   - MUST contain `pr_metadata` block
   - MUST contain `status` field

2. **`RUN_BASE/run_meta.json`**
   - Contains run identity: `run_id`, `github_repo`, `github_ops_allowed`

### Input Validation

Flow 4's `run_prep` step MUST validate:

```python
def validate_build_handoff(run_base: Path) -> ValidationResult:
    receipt_path = run_base / "build" / "build_receipt.json"

    if not receipt_path.exists():
        return ValidationResult(
            valid=False,
            error="BLOCKED: build_receipt.json not found"
        )

    receipt = json.load(receipt_path.open())

    # Check required fields
    required = ["status", "pr_metadata", "ac_matrix", "test_summary"]
    missing = [f for f in required if f not in receipt]
    if missing:
        return ValidationResult(
            valid=False,
            error=f"BLOCKED: Missing required fields: {missing}"
        )

    return ValidationResult(valid=True)
```

---

## Draft → Ready Transition Contract

### Preconditions for Transition

The PR may transition from `draft` to `open` (ready for review) when **ALL** of these conditions are met:

1. **Review Complete:** `review_worklist.worklist_pending == 0`
2. **No Critical Pending:** `review_worklist.has_critical_pending == false`
3. **Safe to Publish:** `safe_to_publish == true` (secrets sanitizer passed)
4. **GitHub Ops Allowed:** `proceed_to_github_ops == true` (repo-operator check)

### Transition Command

```bash
gh pr ready <pr_number> --repo <github_repo>
```

### Transition Artifact

After transition, `pr-status-manager` writes `RUN_BASE/review/pr_status_update.md`:

```markdown
# PR Status Update

- **PR Number:** #<number>
- **Previous State:** draft
- **New State:** open
- **Transition Time:** <ISO 8601>
- **Reason:** Review complete, no critical issues pending

## Criteria Met
- [x] worklist_pending: 0
- [x] has_critical_pending: false
- [x] safe_to_publish: true
- [x] proceed_to_github_ops: true
```

---

## Review Completion Contract

### Definition: "Review Complete"

A review is complete when:

```python
def is_review_complete(worklist: ReviewWorklist) -> bool:
    return (
        worklist.counts.pending == 0 and
        not worklist.has_critical_pending and
        all(
            item.status in ["resolved", "wontfix", "deferred"]
            for item in worklist.items
        )
    )
```

### Review Receipt Schema

Flow 4 produces `RUN_BASE/review/review_receipt.json`:

```json
{
  "schema_version": "1.0.0",
  "run_id": "<run-id>",
  "timestamp": "<ISO 8601>",

  "status": "VERIFIED | UNVERIFIED | BLOCKED",
  "summary": "<Human-readable summary>",

  "worklist_status": {
    "review_complete": true,
    "has_critical_pending": false,
    "counts": {
      "total": "<count>",
      "resolved": "<count>",
      "pending": "<count>",
      "wontfix": "<count>",
      "deferred": "<count>"
    }
  },

  "pr_status": {
    "pr_number": "<number>",
    "pr_state": "draft | open",
    "ci_passing": true,
    "reviews_approved": "<count>"
  },

  "feedback_sources": [
    {
      "source": "coderabbit | github-actions | human-reviewer",
      "items_received": "<count>",
      "items_resolved": "<count>"
    }
  ]
}
```

---

## Error Handling

### Missing `build_receipt.json`

If `build_receipt.json` is missing, Flow 4 MUST:

1. Set status to `BLOCKED`
2. Write to `RUN_BASE/review/review_receipt.json`:
   ```json
   {
     "status": "BLOCKED",
     "summary": "Cannot proceed: build_receipt.json not found",
     "blockers": [{
       "type": "missing_input",
       "description": "Flow 3 did not produce build_receipt.json",
       "recoverable": true
     }]
   }
   ```
3. Recommend re-running Flow 3

### Missing PR Metadata

If `pr_metadata.pr_number` is null, Flow 4 MUST:

1. Attempt to create a Draft PR (via `pr-creator`)
2. Update `build_receipt.json` with the new PR metadata
3. Continue with feedback harvesting

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0.0 | 2025-12-29 | Initial contract definition |
