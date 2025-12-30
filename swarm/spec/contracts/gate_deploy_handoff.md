# Gate -> Deploy Handoff Contract

> **Version:** 1.0.0
> **Status:** Canonical
> **Last Updated:** 2025-12-29

This document defines the **formal contract** between Flow 4 (Gate) and Flow 5 (Deploy). It specifies exactly what artifacts Flow 4 must produce and what Flow 5 expects to consume.

---

## Contract Summary

| Producer | Consumer | Handoff Point | Key Artifact |
|----------|----------|---------------|--------------|
| Flow 4 (Gate) | Flow 5 (Deploy) | `merge_decision.md` | MERGE verdict with confidence |

---

## Flow 4 Outputs (Required)

### Primary Artifact: `RUN_BASE/gate/merge_decision.md`

The `merge_decision.md` is the **canonical handoff artifact**. It MUST include:

```yaml
# Merge Decision

decision: MERGE | BOUNCE | ESCALATE

confidence: high | medium | low

bounce_target:  # if BOUNCE
  - build    # Flow 3
  - plan     # Flow 2

checks:
  receipts: VERIFIED | UNVERIFIED | BLOCKED
  contracts: VERIFIED | UNVERIFIED | BLOCKED
  security: VERIFIED | UNVERIFIED | BLOCKED
  coverage: VERIFIED | UNVERIFIED | BLOCKED

fr_readiness:
  must_have_met: true | false
  should_have_met: true | false
  failing_frs: []  # list of FR IDs if any

summary:
  - "All MUST-HAVE requirements FULLY_VERIFIED"
  - "Contracts match api_contracts.yaml; only additive changes"
  - "Security scan found no HIGH severity issues"
  - "Coverage meets threshold for changed modules"

concerns:
  - "Design critic flagged complexity; monitor post-deploy"
  - "One SHOULD-HAVE FR is MVP_VERIFIED, not FULLY_VERIFIED"

bounce_reasons:  # if BOUNCE
  - "security.status == UNVERIFIED: HIGH severity finding"
  - "coverage.status == UNVERIFIED: core paths uncovered"

escalation_reasons:  # if ESCALATE
  - "Human judgment required: conflicting security findings"

metadata:
  gate_run_timestamp: "<ISO 8601>"
  gate_run_duration_seconds: <number>
  pr_number: <number>
  pr_url: "<URL>"
  head_sha: "<commit SHA>"
```

### Supporting Artifacts

Flow 4 also produces these artifacts in `RUN_BASE/gate/`:

| Artifact | Purpose | Required |
|----------|---------|----------|
| `receipt_audit.md` | Verification of Build receipts | Yes |
| `contract_compliance.md` | API/schema compatibility assessment | Yes |
| `security_scan.md` | SAST and secret scan results | Yes |
| `coverage_audit.md` | Test coverage assessment | Yes |
| `gate_fix_summary.md` | Mechanical fixes applied (if any) | Yes |
| `policy_verdict.md` | Policy compliance check results | If policy-runner used |

---

## Flow 5 Inputs (Expected)

### Required Inputs

1. **`RUN_BASE/gate/merge_decision.md`**
   - MUST exist
   - MUST contain `decision` field
   - If `decision == MERGE`: Deploy proceeds with merge
   - If `decision != MERGE`: Deploy documents why no deployment occurred

2. **`RUN_BASE/build/build_receipt.json`**
   - For context about what was built
   - For PR metadata (branch, commit SHA)

3. **Git State**
   - PR branch and target branch (usually `main`)
   - Commit SHA that was gated

### Input Validation

Flow 5's `repo-operator` step MUST validate:

```python
def validate_gate_handoff(run_base: Path) -> ValidationResult:
    merge_decision_path = run_base / "gate" / "merge_decision.md"

    if not merge_decision_path.exists():
        return ValidationResult(
            valid=False,
            error="BLOCKED: merge_decision.md not found"
        )

    decision = parse_merge_decision(merge_decision_path)

    # Check required fields
    if not decision.decision:
        return ValidationResult(
            valid=False,
            error="BLOCKED: merge_decision.md missing 'decision' field"
        )

    if decision.decision not in ["MERGE", "BOUNCE", "ESCALATE"]:
        return ValidationResult(
            valid=False,
            error=f"BLOCKED: Invalid decision value: {decision.decision}"
        )

    # If BOUNCE, validate bounce_target exists
    if decision.decision == "BOUNCE" and not decision.bounce_target:
        return ValidationResult(
            valid=False,
            error="BLOCKED: BOUNCE decision missing bounce_target"
        )

    # If ESCALATE, validate escalation_reasons exist
    if decision.decision == "ESCALATE" and not decision.escalation_reasons:
        return ValidationResult(
            valid=False,
            error="BLOCKED: ESCALATE decision missing escalation_reasons"
        )

    return ValidationResult(valid=True, decision=decision.decision)
```

---

## Gate Decision Contract

### Decision Values

| Decision | Meaning | Deploy Behavior |
|----------|---------|-----------------|
| **MERGE** | All checks pass; ready to deploy | Proceed with merge, tag, release |
| **BOUNCE** | Issues found; needs work | Do NOT merge; document why |
| **ESCALATE** | Needs human judgment | Do NOT merge; await human decision |

### Preconditions for MERGE Decision

Gate outputs `decision: MERGE` when **ALL** of these conditions are met:

1. **Receipts Valid:** `receipt_audit.status == VERIFIED`
2. **Contracts Compliant:** `contract_compliance.status == VERIFIED`
3. **Security Clean:** No HIGH severity issues in `security_scan.md`
4. **Coverage Met:** `coverage_audit.status == VERIFIED`
5. **FR Readiness:** All MUST-HAVE FRs are FULLY_VERIFIED or MVP_VERIFIED

### Confidence Levels

| Level | Criteria | Deploy Behavior |
|-------|----------|-----------------|
| **high** | All checks VERIFIED, no concerns | Auto-deploy if enabled |
| **medium** | All checks pass but concerns exist | Deploy with monitoring |
| **low** | Edge cases, non-blocking concerns | Deploy with extra caution |

---

## What Deploy Expects

### MERGE Verdict with Confidence

Flow 5 agents (`repo-operator`, `deploy-monitor`, `smoke-verifier`) expect:

1. **Clear Decision:**
   - `decision: MERGE` means proceed with deployment
   - Any other decision means DO NOT merge

2. **PR Metadata:**
   - PR number and URL for merge operation
   - Head SHA for tagging
   - Target branch for merge target

3. **Check Results:**
   - Summary of what was verified
   - Any concerns to monitor post-deploy

4. **Confidence Signal:**
   - High confidence enables faster progression
   - Lower confidence triggers extra verification

---

## Error Handling

### Missing `merge_decision.md`

If `merge_decision.md` is missing, Flow 5 MUST:

1. Set deployment status to `BLOCKED`
2. Write to `RUN_BASE/deploy/deployment_decision.md`:
   ```yaml
   status: BLOCKED

   signals:
     ci: N/A
     smoke: N/A
     gate_decision: MISSING

   merge:
     performed: false
     reason: "merge_decision.md not found"

   summary:
     - "Gate decision artifact missing"
     - "Cannot proceed without Gate verdict"

   recommended_actions:
     - "Re-run Flow 4 (Gate) to produce merge decision"
   ```
3. Do NOT attempt any merge or deployment

### BOUNCE Decision

If `decision == BOUNCE`:

1. Flow 5 sets status to `NOT_DEPLOYED`
2. Document that Gate bounced the change
3. Include `bounce_target` and `bounce_reasons` in deployment receipt
4. No merge performed

```yaml
status: NOT_DEPLOYED

signals:
  ci: N/A
  smoke: N/A
  gate_decision: BOUNCE

merge:
  performed: false
  reason: "Gate decision was BOUNCE"

bounce_info:
  target: build  # or plan
  reasons:
    - "security.status == UNVERIFIED"
    - "coverage below threshold"

recommended_actions:
  - "Address issues in bounce_reasons"
  - "Re-run Flow 3 (Build)"
  - "Re-run Flow 4 (Gate)"
```

### ESCALATE Decision

If `decision == ESCALATE`:

1. Flow 5 sets status to `NOT_DEPLOYED`
2. Document that human judgment is required
3. Include `escalation_reasons` in deployment receipt
4. No merge performed

```yaml
status: NOT_DEPLOYED

signals:
  ci: N/A
  smoke: N/A
  gate_decision: ESCALATE

merge:
  performed: false
  reason: "Gate decision was ESCALATE"

escalation_info:
  reasons:
    - "Conflicting security findings require human review"
  awaiting: "human-decision"

recommended_actions:
  - "Review escalation_reasons with security team"
  - "Provide explicit MERGE or BOUNCE decision"
  - "Re-run Flow 5 after human decision"
```

---

## Gate Audit Trail

### What Gate Must Document

For traceability, `merge_decision.md` must include:

1. **Individual Check Results:**
   - Each check (receipts, contracts, security, coverage)
   - Status (VERIFIED/UNVERIFIED/BLOCKED)
   - Evidence file reference

2. **FR Readiness Summary:**
   - Which requirements were checked
   - Status of each (FULLY_VERIFIED, MVP_VERIFIED, PARTIAL)
   - Any failing requirements listed

3. **Decision Rationale:**
   - Why MERGE (all criteria met)
   - Why BOUNCE (which criteria failed)
   - Why ESCALATE (what judgment is needed)

4. **Metadata:**
   - Timestamp of gate run
   - PR and commit being gated
   - Duration of gate checks

---

## Handoff Envelope Schema

For programmatic validation, the handoff can be represented as:

```json
{
  "schema_version": "1.0.0",
  "producer_flow": "gate",
  "consumer_flow": "deploy",
  "run_id": "<run-id>",
  "timestamp": "<ISO 8601>",

  "primary_artifact": {
    "path": "gate/merge_decision.md",
    "exists": true,
    "decision": "MERGE",
    "confidence": "high"
  },

  "supporting_artifacts": {
    "receipt_audit": {
      "path": "gate/receipt_audit.md",
      "status": "VERIFIED"
    },
    "contract_compliance": {
      "path": "gate/contract_compliance.md",
      "status": "VERIFIED"
    },
    "security_scan": {
      "path": "gate/security_scan.md",
      "status": "VERIFIED"
    },
    "coverage_audit": {
      "path": "gate/coverage_audit.md",
      "status": "VERIFIED"
    }
  },

  "pr_metadata": {
    "pr_number": 123,
    "pr_url": "https://github.com/owner/repo/pull/123",
    "head_sha": "abc123def456",
    "base_branch": "main"
  },

  "validation": {
    "decision_present": true,
    "decision_valid": true,
    "all_checks_completed": true,
    "fr_readiness_met": true
  },

  "handoff_ready": true
}
```

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0.0 | 2025-12-29 | Initial contract definition |
