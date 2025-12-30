# Deploy -> Wisdom Handoff Contract

> **Version:** 1.0.0
> **Status:** Canonical
> **Last Updated:** 2025-12-29

This document defines the **formal contract** between Flow 5 (Deploy) and Flow 6 (Wisdom). It specifies exactly what artifacts Flow 5 must produce and what Flow 6 expects to consume.

---

## Contract Summary

| Producer | Consumer | Handoff Point | Key Artifact |
|----------|----------|---------------|--------------|
| Flow 5 (Deploy) | Flow 6 (Wisdom) | `deployment_decision.md` | Completed deployment with verification |

---

## Flow 5 Outputs (Required)

### Primary Artifact: `RUN_BASE/deploy/deployment_decision.md`

The `deployment_decision.md` is the **canonical handoff artifact**. It MUST include:

```yaml
# Deployment Decision

status: STABLE | INVESTIGATE | ROLLBACK | NOT_DEPLOYED

signals:
  ci: PASS | FAIL | FLAKY | N/A
  smoke: PASS | FAIL | UNKNOWN | N/A
  gate_decision: MERGE | BOUNCE | ESCALATE

merge:
  performed: true | false
  commit: "<merge commit SHA>"
  branch: "main"
  timestamp: "<ISO 8601>"

release:
  tag: "v1.2.3" | null
  release_url: "<GitHub release URL>" | null
  release_notes: "<path or inline>"

verification:
  ci_checks_passed: true | false
  smoke_checks_passed: true | false
  operationalization_frs:
    FR-OP-001: PASS | FAIL | UNKNOWN
    FR-OP-002: PASS | FAIL | UNKNOWN
    FR-OP-003: PASS | FAIL | UNKNOWN
    FR-OP-004: PASS | FAIL | UNKNOWN
    FR-OP-005: PASS | FAIL | UNKNOWN

summary:
  - "Merge successful: abc123 -> main"
  - "CI: all required checks passed"
  - "Release v1.2.3 created"
  - "Smoke: health endpoint responded 200 OK"

concerns:  # if INVESTIGATE or ROLLBACK
  - "CI job 'e2e-tests' flaky; passed on retry"
  - "Smoke check latency above baseline"

recommended_actions:
  - "Monitor error rate for 30 minutes"
  - "Check dashboard X for anomalies"

not_deployed_reason:  # if NOT_DEPLOYED
  - "Gate decision was BOUNCE"
  - "FR-OP-001 not met: CI job missing"

metadata:
  deploy_run_timestamp: "<ISO 8601>"
  deploy_run_duration_seconds: <number>
  environment: "production" | "staging" | "local"
```

### Supporting Artifacts

Flow 5 also produces these artifacts in `RUN_BASE/deploy/`:

| Artifact | Purpose | Required |
|----------|---------|----------|
| `deployment_log.md` | Record of merge, tag, release actions | Yes |
| `verification_report.md` | CI status + smoke check results | Yes |
| `release_notes.md` | Generated release notes | If release created |
| `branch_protection.md` | Manual snapshot of branch rules | If API unavailable |

---

## Flow 6 Inputs (Expected)

### Required Inputs

1. **`RUN_BASE/deploy/deployment_decision.md`**
   - MUST exist
   - MUST contain `status` field
   - MUST contain `merge.performed` field

2. **`RUN_BASE/deploy/verification_report.md`**
   - MUST exist
   - Contains CI and smoke check details

3. **Artifacts from All Previous Flows**
   - Flow 6 reads from `signal/`, `plan/`, `build/`, `review/`, `gate/`, `deploy/`
   - All are needed for comprehensive analysis

### Input Validation

Flow 6's `artifact-auditor` step MUST validate:

```python
def validate_deploy_handoff(run_base: Path) -> ValidationResult:
    deploy_decision_path = run_base / "deploy" / "deployment_decision.md"
    verification_report_path = run_base / "deploy" / "verification_report.md"

    if not deploy_decision_path.exists():
        return ValidationResult(
            valid=False,
            error="BLOCKED: deployment_decision.md not found"
        )

    if not verification_report_path.exists():
        return ValidationResult(
            valid=False,
            error="BLOCKED: verification_report.md not found"
        )

    decision = parse_deployment_decision(deploy_decision_path)

    # Check required fields
    required = ["status", "signals", "merge", "verification"]
    missing = [f for f in required if f not in decision]
    if missing:
        return ValidationResult(
            valid=False,
            error=f"BLOCKED: Missing required fields: {missing}"
        )

    # Validate status is a known value
    valid_statuses = ["STABLE", "INVESTIGATE", "ROLLBACK", "NOT_DEPLOYED"]
    if decision.status not in valid_statuses:
        return ValidationResult(
            valid=False,
            error=f"BLOCKED: Invalid status: {decision.status}"
        )

    return ValidationResult(valid=True, status=decision.status)
```

---

## Deploy Status Contract

### Status Values

| Status | Meaning | Wisdom Analysis Focus |
|--------|---------|----------------------|
| **STABLE** | Deployment successful, healthy | Focus on learnings, optimization opportunities |
| **INVESTIGATE** | Warnings or anomalies observed | Focus on understanding anomalies, risk patterns |
| **ROLLBACK** | Critical issues, reverted | Focus on root cause, failure patterns |
| **NOT_DEPLOYED** | Gate did not approve | Focus on Gate feedback, process gaps |

### What Each Status Means for Wisdom

**STABLE:**
- Full SDLC cycle completed successfully
- Wisdom can extract positive patterns
- Good candidate for "what worked well" analysis

**INVESTIGATE:**
- Deployment succeeded but concerns exist
- Wisdom should correlate concerns with historical patterns
- May reveal recurring issues

**ROLLBACK:**
- Deployment failed or was reverted
- Wisdom must identify root cause
- High-priority for feedback loop improvements

**NOT_DEPLOYED:**
- Change did not reach production
- Wisdom analyzes why (Gate bounce, escalation)
- Informs process improvements

---

## What Wisdom Expects

### Completed Deployment with Verification

Flow 6 agents (`artifact-auditor`, `regression-analyst`, `learning-synthesizer`) expect:

1. **Clear Deployment Outcome:**
   - `status` tells Wisdom what kind of analysis to perform
   - `merge.performed` confirms whether code reached production

2. **Verification Evidence:**
   - `verification_report.md` provides CI and smoke details
   - Enables correlation with test coverage from Build

3. **Complete Artifact Trail:**
   - All flows' artifacts available for cross-flow analysis
   - Enables tracing from Signal -> Deploy

4. **Operationalization Status:**
   - FR-OP-001 through FR-OP-005 results
   - Informs governance health analysis

---

## Error Handling

### Missing `deployment_decision.md`

If `deployment_decision.md` is missing, Flow 6 MUST:

1. Set audit status to `BLOCKED`
2. Write to `RUN_BASE/wisdom/artifact_audit.md`:
   ```markdown
   ## Artifact Audit

   **Status:** BLOCKED

   ### Missing Critical Artifacts

   | Flow | Artifact | Status |
   |------|----------|--------|
   | deploy | deployment_decision.md | MISSING |

   **Impact:** Cannot determine deployment outcome

   **Recommendation:** Re-run Flow 5 (Deploy) to completion
   ```
3. Continue with partial analysis of available artifacts

### NOT_DEPLOYED Status

If `status == NOT_DEPLOYED`:

1. Wisdom proceeds with analysis
2. Focus shifts to understanding Gate decision
3. Artifact audit still runs for all flows
4. Learnings focus on process gaps, not production behavior

```markdown
## Analysis Context

**Deployment Status:** NOT_DEPLOYED

**Reason:** Gate decision was BOUNCE

**Analysis Focus:**
- Why did Gate bounce?
- What gaps exist in Build artifacts?
- How can flow execution improve?
```

### ROLLBACK Status

If `status == ROLLBACK`:

1. Wisdom treats this as high-priority analysis
2. Root cause identification is mandatory
3. `regression_report.md` must include rollback analysis
4. `feedback_actions.md` must include preventive measures

```markdown
## Rollback Analysis

**Deployment Status:** ROLLBACK

**Trigger:** Production error rate exceeded threshold

**Root Cause Analysis:**
1. Timeline of events
2. What signals were missed?
3. What tests should have caught this?
4. What monitoring should exist?

**Preventive Actions:**
- [ ] Add test for edge case X
- [ ] Add monitoring for metric Y
- [ ] Update Gate checks for condition Z
```

---

## Verification Report Structure

`verification_report.md` must include:

```markdown
# Verification Report

## Commit
- SHA: abc123def456
- Branch: main
- Tag: v1.2.3
- Merge Timestamp: 2025-12-29T15:30:00Z

## CI Status

| Check | Status | Duration | Notes |
|-------|--------|----------|-------|
| lint | PASS | 45s | |
| test | PASS | 3m 22s | |
| build | PASS | 2m 15s | |
| e2e | PASS | 5m 10s | Retry 1 (flaky) |

### CI Summary
- Total checks: 4
- Passed: 4
- Failed: 0
- Flaky: 1 (e2e)

## Smoke Checks

| Endpoint | Expected | Actual | Status |
|----------|----------|--------|--------|
| /_health | 200 | 200 | PASS |
| /api/version | v1.2.3 | v1.2.3 | PASS |

### Smoke Summary
- Endpoints checked: 2
- All healthy: Yes

## Operationalization FRs

| FR | Status | Evidence |
|----|--------|----------|
| FR-OP-001 | PASS | CI validator job runs on push |
| FR-OP-002 | PASS | CI test job runs on push |
| FR-OP-003 | PASS | Pre-commit hook configured |
| FR-OP-004 | PASS | Branch protection verified |
| FR-OP-005 | FAIL | RUNBOOK.md missing enforcement section |

## Issues Observed
- e2e test required retry (known flaky test)
- No other issues
```

---

## Handoff Envelope Schema

For programmatic validation, the handoff can be represented as:

```json
{
  "schema_version": "1.0.0",
  "producer_flow": "deploy",
  "consumer_flow": "wisdom",
  "run_id": "<run-id>",
  "timestamp": "<ISO 8601>",

  "primary_artifact": {
    "path": "deploy/deployment_decision.md",
    "exists": true,
    "status": "STABLE",
    "merge_performed": true
  },

  "supporting_artifacts": {
    "deployment_log": {
      "path": "deploy/deployment_log.md",
      "exists": true
    },
    "verification_report": {
      "path": "deploy/verification_report.md",
      "exists": true
    },
    "release_notes": {
      "path": "deploy/release_notes.md",
      "exists": true
    }
  },

  "deployment_info": {
    "merge_commit": "abc123def456",
    "tag": "v1.2.3",
    "release_url": "https://github.com/owner/repo/releases/tag/v1.2.3",
    "environment": "production"
  },

  "verification_summary": {
    "ci_checks_passed": true,
    "smoke_checks_passed": true,
    "operationalization_frs_passed": 4,
    "operationalization_frs_failed": 1
  },

  "all_flows_available": {
    "signal": true,
    "plan": true,
    "build": true,
    "review": true,
    "gate": true,
    "deploy": true
  },

  "handoff_ready": true
}
```

---

## Cross-Flow Artifact Availability

Wisdom requires artifacts from ALL previous flows:

| Flow | Key Artifacts | Purpose in Wisdom |
|------|--------------|-------------------|
| signal | requirements.md, early_risks.md | Compare predicted vs actual |
| plan | adr.md, test_plan.md | Evaluate design decisions |
| build | build_receipt.json, test_critique.md | Assess implementation quality |
| review | review_receipt.json, fix_actions.md | Understand feedback patterns |
| gate | merge_decision.md, security_scan.md | Analyze gate effectiveness |
| deploy | deployment_decision.md, verification_report.md | Ground truth for analysis |

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0.0 | 2025-12-29 | Initial contract definition |
