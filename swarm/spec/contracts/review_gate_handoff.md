# Review -> Gate Handoff Contract

> **Version:** 1.0.0
> **Status:** Canonical
> **Last Updated:** 2025-12-29

This document defines the **formal contract** between the Review phase and Gate (Flow 5). In this architecture, Review is the final phase of Flow 4 that produces a PR ready for merge decision. This contract specifies what the review process must produce and what Gate expects to consume.

---

## Contract Summary

| Producer | Consumer | Handoff Point | Key Artifact |
|----------|----------|---------------|--------------|
| Review (Flow 4) | Gate (Flow 5) | `review_receipt.json` | PR ready for merge decision |

---

## Review Phase Outputs (Required)

### Primary Artifact: `RUN_BASE/review/review_receipt.json`

The `review_receipt.json` is the **canonical handoff artifact**. It MUST include:

```json
{
  "schema_version": "1.0.0",
  "run_id": "<run-id>",
  "timestamp": "<ISO 8601>",

  "status": "VERIFIED | UNVERIFIED | BLOCKED",
  "summary": "<Human-readable summary of review outcome>",

  "pr_metadata": {
    "pr_number": "<number>",
    "pr_url": "<URL>",
    "pr_state": "open",
    "head_branch": "<branch name>",
    "base_branch": "main",
    "ready_for_review": true,
    "draft": false
  },

  "worklist_status": {
    "review_complete": true,
    "has_critical_pending": false,
    "counts": {
      "total": "<count>",
      "resolved": "<count>",
      "pending": 0,
      "wontfix": "<count>",
      "deferred": "<count>"
    }
  },

  "feedback_sources": [
    {
      "source": "coderabbit | github-actions | human-reviewer",
      "items_received": "<count>",
      "items_resolved": "<count>",
      "items_deferred": "<count>"
    }
  ],

  "ci_status": {
    "all_checks_passed": true,
    "required_checks": ["lint", "test", "build"],
    "check_results": {
      "lint": "PASS",
      "test": "PASS",
      "build": "PASS"
    }
  },

  "fix_actions": [
    {
      "action_id": "FIX-001",
      "feedback_ref": "coderabbit-comment-123",
      "description": "Fixed null check in handler",
      "status": "applied",
      "files_changed": ["src/handler.py"]
    }
  ],

  "deferred_items": [
    {
      "item_id": "DEFER-001",
      "reason": "Out of scope for this PR",
      "tracking_issue": "#456"
    }
  ]
}
```

### Supporting Artifacts

The Review phase also produces these artifacts in `RUN_BASE/review/`:

| Artifact | Purpose | Required |
|----------|---------|----------|
| `pr_feedback.md` | Collected feedback from all sources | Yes |
| `review_worklist.md` | Categorized work items from feedback | Yes |
| `fix_actions.md` | Actions taken to address feedback | Yes |
| `pr_status_update.md` | Draft -> Open transition record | Yes |
| `review_summary.md` | Narrative summary of review cycle | Yes |
| `deferred_items.md` | Items intentionally not addressed | If any |

---

## Gate Inputs (Expected)

### Required Inputs

1. **`RUN_BASE/review/review_receipt.json`**
   - MUST exist
   - MUST show `pr_state: "open"` (not draft)
   - MUST show `worklist_status.pending: 0`
   - MUST show `has_critical_pending: false`

2. **`RUN_BASE/build/build_receipt.json`**
   - MUST exist (from Build phase)
   - Gate reads this for context

3. **PR in GitHub**
   - PR must be in "open" state (not draft)
   - Required CI checks must have completed

### Input Validation

Gate's `receipt-checker` step MUST validate:

```python
def validate_review_handoff(run_base: Path) -> ValidationResult:
    review_receipt_path = run_base / "review" / "review_receipt.json"

    if not review_receipt_path.exists():
        return ValidationResult(
            valid=False,
            error="BLOCKED: review_receipt.json not found"
        )

    receipt = json.load(review_receipt_path.open())

    # Check required fields
    required = ["status", "pr_metadata", "worklist_status", "ci_status"]
    missing = [f for f in required if f not in receipt]
    if missing:
        return ValidationResult(
            valid=False,
            error=f"BLOCKED: Missing required fields: {missing}"
        )

    # Verify PR is ready for review
    pr_meta = receipt.get("pr_metadata", {})
    if pr_meta.get("draft", True):
        return ValidationResult(
            valid=False,
            error="BLOCKED: PR is still in draft state"
        )

    if pr_meta.get("pr_state") != "open":
        return ValidationResult(
            valid=False,
            error=f"BLOCKED: PR state is '{pr_meta.get('pr_state')}', expected 'open'"
        )

    # Verify review is complete
    worklist = receipt.get("worklist_status", {})
    if worklist.get("pending", 1) > 0:
        return ValidationResult(
            valid=False,
            error=f"BLOCKED: {worklist.get('pending')} pending items in worklist"
        )

    if worklist.get("has_critical_pending", True):
        return ValidationResult(
            valid=False,
            error="BLOCKED: Critical items still pending"
        )

    return ValidationResult(valid=True)
```

---

## Review Completion Contract

### Definition: "Review Complete"

A review is complete when:

```python
def is_review_complete(receipt: ReviewReceipt) -> bool:
    return (
        receipt.worklist_status.pending == 0 and
        not receipt.worklist_status.has_critical_pending and
        receipt.pr_metadata.pr_state == "open" and
        not receipt.pr_metadata.draft and
        all(
            item.status in ["resolved", "wontfix", "deferred"]
            for item in receipt.fix_actions + receipt.deferred_items
        )
    )
```

### Preconditions for Gate to Proceed

Gate may proceed when **ALL** of these conditions are met:

1. **PR Ready:** `pr_metadata.draft == false` AND `pr_state == "open"`
2. **Review Complete:** `worklist_status.pending == 0`
3. **No Critical Pending:** `has_critical_pending == false`
4. **CI Passing:** `ci_status.all_checks_passed == true`

---

## What Gate Expects

### PR Ready for Merge Decision

Gate agents (`receipt-checker`, `contract-enforcer`, `merge-decider`) expect:

1. **Clean PR State:**
   - PR is open (not draft)
   - All review feedback has been addressed or explicitly deferred
   - CI checks have completed and passed

2. **Complete Review Trail:**
   - `pr_feedback.md` documents all feedback received
   - `fix_actions.md` documents all fixes applied
   - `deferred_items.md` documents and justifies deferrals

3. **CI Stability:**
   - All required CI checks have passed
   - No flaky tests that passed on retry without investigation

4. **Reviewer Sign-off:**
   - Bot reviewers (CodeRabbit, etc.) are satisfied
   - Human reviewers (if any) have approved or feedback addressed

---

## Error Handling

### Missing `review_receipt.json`

If `review_receipt.json` is missing, Gate MUST:

1. Set status to `BLOCKED`
2. Write to `RUN_BASE/gate/receipt_audit.md`:
   ```markdown
   ## Review Receipt Audit

   **Status:** BLOCKED

   **Issue:** review_receipt.json not found

   **Impact:** Cannot determine PR review status

   **Recommendation:** Re-run Flow 4 (Review) to complete PR feedback cycle
   ```
3. `merge-decider` cannot produce a MERGE decision

### PR Still in Draft

If PR is still in draft state:

1. Gate sets status to `BLOCKED`
2. Document that PR must be marked ready for review
3. Recommend completing review cycle

### Pending Review Items

If `worklist_status.pending > 0`:

1. Gate MAY proceed with caution
2. `merge-decider` must factor pending items into decision
3. If items are critical: BOUNCE back to Review
4. If items are non-critical: may MERGE with documented concerns

### Failed CI Checks

If `ci_status.all_checks_passed == false`:

1. Gate sets `BOUNCE` with target `build`
2. Document which checks failed
3. Build must fix failures before Review can complete

---

## Draft -> Ready Transition Contract

### Transition Criteria

The PR may transition from `draft` to `open` when:

1. **Review Complete:** `worklist_status.pending == 0`
2. **No Critical Pending:** `has_critical_pending == false`
3. **Safe to Publish:** No secrets or sensitive data in changes
4. **CI Passing:** All required checks green

### Transition Record

`pr_status_update.md` documents the transition:

```markdown
# PR Status Update

- **PR Number:** #123
- **Previous State:** draft
- **New State:** open
- **Transition Time:** 2025-12-29T15:30:00Z
- **Reason:** Review complete, no critical issues pending

## Criteria Met
- [x] worklist_pending: 0
- [x] has_critical_pending: false
- [x] safe_to_publish: true
- [x] ci_checks_passing: true

## Transition Command
```bash
gh pr ready 123 --repo owner/repo
```
```

---

## Handoff Envelope Schema

For programmatic validation, the handoff can be represented as:

```json
{
  "schema_version": "1.0.0",
  "producer_flow": "review",
  "consumer_flow": "gate",
  "run_id": "<run-id>",
  "timestamp": "<ISO 8601>",

  "primary_artifact": {
    "path": "review/review_receipt.json",
    "exists": true,
    "status": "VERIFIED",
    "pr_state": "open"
  },

  "supporting_artifacts": {
    "pr_feedback": {"path": "review/pr_feedback.md", "exists": true},
    "review_worklist": {"path": "review/review_worklist.md", "exists": true},
    "fix_actions": {"path": "review/fix_actions.md", "exists": true},
    "pr_status_update": {"path": "review/pr_status_update.md", "exists": true}
  },

  "validation": {
    "pr_is_open": true,
    "pr_not_draft": true,
    "worklist_pending_zero": true,
    "no_critical_pending": true,
    "ci_checks_passed": true
  },

  "handoff_ready": true
}
```

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0.0 | 2025-12-29 | Initial contract definition |
