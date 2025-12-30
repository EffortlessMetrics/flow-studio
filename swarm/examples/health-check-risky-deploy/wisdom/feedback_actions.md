# Feedback Actions

## Feedback to Flow 1 (Signal)

### Issue to Create: Enhance risk-analyst prompt with performance risk checklist

**Title**: Add performance risk checklist to risk-analyst agent prompt

**Description**:
The health-check-risky-deploy run demonstrated effective early risk identification. The risk-analyst agent identified a MEDIUM performance risk in Signal flow, enabling systematic mitigation through all subsequent flows.

**Recommendation**: Add a performance risk checklist to risk-analyst agent prompt to ensure consistent identification:
- Is this a public endpoint?
- Expected request frequency?
- Latency requirements?
- Resource impact estimation?

**Evidence**: See `swarm/examples/health-check-risky-deploy/signal/early_risk_assessment.md`

**Priority**: MEDIUM

**Labels**: enhancement, flow-1-signal, risk-analyst

---

### Documentation Update: Create early_risk_assessment.md template

**File**: `swarm/templates/early_risk_assessment_template.md`

**Content**: Template based on `swarm/examples/health-check-risky-deploy/signal/early_risk_assessment.md` with:
- Standard risk categories (performance, security, data, compliance)
- Risk scoring matrix
- Mitigation options brainstorming
- Risk acceptance criteria for gate

**Priority**: LOW

**Labels**: documentation, templates, flow-1-signal

## Feedback to Flow 2 (Plan)

### Issue to Create: Make observability_spec.md required for MEDIUM+ risk

**Title**: Require observability_spec.md when risk level is MEDIUM or higher

**Description**:
The health-check-risky-deploy run showed that having observability_spec.md ready before implementation enabled confident deployment despite identified risk.

**Recommendation**: Update work-planner and observability-designer prompts to require observability_spec.md when early_risk_assessment.md shows risk level >= MEDIUM.

**Evidence**: See `swarm/examples/health-check-risky-deploy/plan/observability_spec.md` - metrics enabled conditional approval

**Priority**: HIGH

**Labels**: enhancement, flow-2-plan, observability-designer

---

### Documentation Update: Create observability_spec.md template

**File**: `swarm/templates/observability_spec_template.md`

**Content**: Template based on `swarm/examples/health-check-risky-deploy/plan/observability_spec.md` with:
- Metrics definition (counter, histogram, gauge)
- Alert configuration
- Dashboard requirements
- Logging guidelines
- Risk mitigation traceability

**Priority**: MEDIUM

**Labels**: documentation, templates, flow-2-plan

## Feedback to Flow 3 (Build)

### Documentation Update: Add metrics verification test pattern

**File**: `swarm/examples/test_patterns/metrics_verification.md`

**Content**: Document the test pattern from `health-check-risky-deploy/build/test_changes_summary.md`:
- How to test metrics collection (counter increments)
- How to test metrics labels
- How to test latency histograms
- Example: `test_health_endpoint_metrics_recorded`

**Priority**: LOW

**Labels**: documentation, test-patterns, flow-3-build

## Feedback to Flow 4 (Gate)

### Issue to Create: Document MERGE_WITH_CONDITIONS pattern

**Title**: Add conditional approval pattern to merge-decider agent

**Description**:
The health-check-risky-deploy run demonstrated successful use of MERGE_WITH_CONDITIONS decision - not binary MERGE/BOUNCE, but conditional approval with monitoring requirements.

**Recommendation**: Update merge-decider agent prompt to include MERGE_WITH_CONDITIONS as a standard decision pattern.

**Decision criteria**:
- Risk identified: YES
- Risk mitigated: YES (to LOW residual)
- Monitoring ready: YES
- Rollback plan: YES
- Result: CONDITIONAL APPROVAL

**Evidence**: See `swarm/examples/health-check-risky-deploy/gate/merge_recommendation.md`

**Priority**: HIGH

**Labels**: enhancement, flow-4-gate, merge-decider

---

### Documentation Update: Create conditional approval template

**File**: `swarm/templates/merge_recommendation_conditional.md`

**Content**: Template based on `swarm/examples/health-check-risky-deploy/gate/merge_recommendation.md` with:
- Conditional approval checklist
- Monitoring requirements template
- Rollback criteria template
- Risk acceptance documentation

**Priority**: MEDIUM

**Labels**: documentation, templates, flow-4-gate

## Feedback to Flow 7 (Wisdom)

### Documentation Update: Add this run to reference examples

**File**: `swarm/examples/README.md`

**Content**: Add health-check-risky-deploy as a reference example for:
- Complete 7-flow execution
- Risk management workflow
- Conditional approval pattern
- Observability-first design

**Priority**: HIGH

**Labels**: documentation, examples

## Summary

**Issues to create**: 3
- Enhance risk-analyst prompt (MEDIUM)
- Require observability_spec for MEDIUM+ risk (HIGH)
- Document MERGE_WITH_CONDITIONS pattern (HIGH)

**Documentation updates**: 5
- early_risk_assessment_template.md (LOW)
- observability_spec_template.md (MEDIUM)
- metrics_verification test pattern (LOW)
- merge_recommendation_conditional.md (MEDIUM)
- Update examples README (HIGH)

**Total feedback actions**: 8

All feedback actions trace back to specific artifacts in `swarm/examples/health-check-risky-deploy/` for evidence-based improvement.
