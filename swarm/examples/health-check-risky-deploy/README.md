# Health Check - Risky Deploy Scenario

> Teaching scenario: Complete flows with risk warnings, conditional approval, monitored deployment

## Purpose

This scenario demonstrates a complete SDLC run where all flows complete successfully but with documented risks. Gate approves the change with conditions (MERGE_WITH_CONDITIONS), and Deploy proceeds with enhanced monitoring.

## Success Pattern with Risk Acceptance

**Root Cause**: No root cause - this is a successful flow with managed risk.

**Risk Identified**: Performance impact concern - new endpoint may be called frequently by external probes, potential load increase.

**Risk Management**: Gate approves with monitoring conditions, Deploy proceeds with instrumentation.

**Result**: All 7 flows complete, change is deployed with risk mitigation in place.

## Directory Structure

```
health-check-risky-deploy/
├── run.json                    # Scenario metadata
├── README.md                   # This file
├── signal/                     # Flow 1 - Complete with risk identified
│   ├── problem_statement.md
│   ├── requirements_functional.md
│   └── early_risk_assessment.md  # Identifies performance concern
├── plan/                       # Flow 2 - Complete with mitigation
│   ├── adr_current.md
│   ├── work_plan.md
│   └── observability_spec.md  # Adds monitoring for risk mitigation
├── build/                      # Flow 3 - Complete
│   ├── subtask_context_manifest.json
│   ├── test_changes_summary.md
│   ├── impl_changes_summary.md
│   ├── code_critique.md
│   └── build_receipt.json
├── review/                     # Flow 4 - Draft PR and feedback
│   └── ...
├── gate/                       # Flow 5 - MERGE_WITH_CONDITIONS
│   ├── receipt_audit.md
│   ├── security_status.md
│   ├── gate_risk_report.md    # Documents accepted risk
│   └── merge_recommendation.md # Status: MERGE_WITH_CONDITIONS
├── deploy/                     # Flow 6 - Complete with monitoring
│   ├── deployment_log.md
│   ├── verification_report.md
│   └── deployment_decision.md # proceed_with_risk: true
└── wisdom/                     # Flow 7 - Complete with learnings
    ├── artifact_audit.md
    ├── regression_report.md
    ├── flow_history.json
    ├── learnings.md
    └── feedback_actions.md
```

## SDLC Bar Status in Flow Studio

When viewed in Flow Studio, this run shows:

- **Signal (Flow 1)**: GREEN - Complete with risk documentation
- **Plan (Flow 2)**: GREEN - Complete with mitigation plan
- **Build (Flow 3)**: GREEN - All artifacts present
- **Review (Flow 4)**: GREEN - PR feedback harvested
- **Gate (Flow 5)**: YELLOW/CONDITIONAL - MERGE_WITH_CONDITIONS
- **Deploy (Flow 6)**: GREEN - Deployed with monitoring
- **Wisdom (Flow 7)**: GREEN - Complete with learnings

## Teaching Points

1. **Risk acceptance is valid**: Not all risks block deployment
2. **Conditional approval pattern**: Gate can approve with monitoring requirements
3. **Risk mitigation in layers**: Signal identifies, Plan mitigates, Gate conditions, Deploy monitors
4. **Complete flow execution**: All 7 flows executed end-to-end
5. **Feedback loop closure**: Wisdom flow extracts learnings for future improvements

## Expected User Action

After viewing this scenario in Flow Studio:

1. Notice Gate shows CONDITIONAL status (yellow) - not blocking, but not unconditional
2. Read `gate/gate_risk_report.md` to understand accepted risk
3. Read `gate/merge_recommendation.md` to see monitoring conditions
4. Review `deploy/deployment_decision.md` to see risk acceptance rationale
5. Check `wisdom/learnings.md` for extracted patterns

## Contrast with Baseline

**health-check (baseline)**: Clean approval, no risks, unconditional MERGE

**health-check-risky-deploy (this scenario)**: Managed risk, conditional approval, enhanced monitoring

## Contrast with Other Scenarios

**health-check-missing-tests**: Gate blocks (BOUNCE) - unacceptable risk

**health-check-no-gate-decision**: Gate incomplete - no decision made

**health-check-risky-deploy (this scenario)**: Gate conditionally approves - acceptable risk with mitigation

## Risk Management Philosophy

This scenario demonstrates the swarm's approach to risk:

1. **Early identification**: Signal flow (risk-analyst) identifies performance concern
2. **Mitigation planning**: Plan flow adds observability spec for monitoring
3. **Informed decision**: Gate evaluates risk vs mitigation, approves with conditions
4. **Monitored deployment**: Deploy proceeds with enhanced instrumentation
5. **Learning extraction**: Wisdom analyzes deployment for regression detection
6. **Feedback loop**: Learnings feed back to improve future risk assessment

The swarm doesn't aim for zero-risk (impossible); it aims for **managed risk with receipts**.
