# Golden Runs: Example Run Documentation

> **Context:** These golden runs are curated **Flow Studio demo runs** for the DemoSwarm
> pattern in `.claude/`.
>
> They exercise the Flow Studio UI, APIs, and selftest.

This document provides comprehensive documentation for all curated example runs in the swarm. Golden runs are **teaching material** that demonstrate flow behavior across various scenarios.

---

## What Are Golden Runs?

Golden runs are committed snapshots of flow executions that serve as:

1. **Reference implementations**: Show what artifacts each flow should produce
2. **Teaching material**: Help new users understand flow behavior
3. **Test fixtures**: Provide stable inputs for Flow Studio, validators, and agents
4. **Contract definitions**: Define the artifact shapes orchestrators must produce

Golden runs live in `swarm/examples/<scenario>/` and are committed to version control. Active runs live in `swarm/runs/` and are gitignored.

> **Note:** Historical examples use `operate/` instead of `deploy/` for Flow 5 artifacts.
> The `swarm-alignment` run uses the canonical naming (`deploy/`, `wisdom/`).

**Philosophy**: Golden runs demonstrate both success paths and failure modes. Understanding how the swarm handles degraded states is as important as understanding the happy path.

---

## Quick Reference Matrix

| Run ID | Scenario | Flows Covered | Status | Learning Goal |
|--------|----------|---------------|--------|---------------|
| `health-check` | Complete baseline | 1-7 (all) | GREEN | Full flow execution, artifact shapes |
| `health-check-missing-tests` | Degraded build | 1-5 | BOUNCE | Failure detection, receipt audit |
| `health-check-no-gate-decision` | Incomplete gate | 1-5 (partial) | INCOMPLETE | Missing decision artifacts |
| `health-check-risky-deploy` | Risk management | 1-7 (all) | CONDITIONAL | Risk acceptance, conditional approval |
| `swarm-selftest-baseline` | Infrastructure | N/A | GREEN | Selftest report structure |
| `swarm-alignment` | Governance verification | 1-7 (all) | GREEN | Canonical naming, self-referential validation |

### Status Legend

- **GREEN**: All flows complete, all artifacts present, no issues
- **YELLOW/CONDITIONAL**: Complete with warnings or conditions
- **BOUNCE**: Gate rejected, work returned to earlier flow
- **INCOMPLETE**: Flow did not finish, missing required artifacts
- **GRAY**: Flow not started (blocked by upstream)

---

## Learning Paths

### Path 1: Understanding Complete Flow Execution

**Goal**: Learn what a successful end-to-end run looks like.

**Start with**: `health-check`

**Key takeaways**:
- All 7 flows produce artifacts in their respective directories (signal/, plan/, build/, review/, gate/, deploy/, wisdom/)
- Each artifact has a defined shape and purpose
- Receipts (especially `build_receipt.json`) tie everything together
- Gate produces a clear merge recommendation after Review gathers feedback

### Path 2: Understanding Failure Detection

**Goal**: Learn how the swarm detects and handles incomplete work.

**Progression**:
1. `health-check` (baseline) - See what success looks like
2. `health-check-missing-tests` - See how missing artifacts trigger bounce
3. `health-check-no-gate-decision` - See what happens when flow is incomplete

**Key takeaways**:
- Receipt audit catches missing evidence
- Gate does not fix test gaps; it bounces to Build
- Incomplete flows block downstream flows

### Path 3: Understanding Risk Management

**Goal**: Learn how the swarm handles acceptable risks.

**Start with**: `health-check-risky-deploy`

**Key takeaways**:
- Not all risks block deployment
- Gate can approve with conditions (MERGE_WITH_CONDITIONS)
- Risk mitigation flows through all stages: Signal identifies, Plan mitigates, Gate conditions, Deploy monitors
- Wisdom extracts learnings for future improvement

### Path 4: Understanding Infrastructure

**Goal**: Learn the selftest system and swarm health monitoring.

**Start with**: `swarm-selftest-baseline`

**Key takeaways**:
- 16-step selftest validates swarm configuration
- Three tiers: Kernel (critical), Governance (contracts), Optional (informational)
- Agents can read selftest reports to understand swarm health
- Used by Flow 6 (Wisdom) for regression detection

---

## Detailed Run Documentation

### 1. health-check (Complete Baseline)

> Complete end-to-end demonstration of all 7 flows in the industrial agentic SDLC swarm.

**Scenario**: Implement a simple health-check endpoint through all SDLC flows.

**Directory Structure**:
```
health-check/
├── code-snapshot/          # Copy of code/tests/features at snapshot time
│   ├── 0001_add_health_endpoint.sql
│   ├── example_fuzz.rs
│   └── health.feature
├── signal/                 # Flow 1 artifacts
│   ├── problem_statement.md
│   ├── requirements_functional.md
│   ├── requirements_constraints.md
│   ├── early_risk_assessment.md
│   ├── clarification_questions.md
│   └── ... (15+ artifacts)
├── plan/                   # Flow 2 artifacts
│   ├── adr_current.md
│   ├── api_contracts.yaml
│   ├── interface_spec.md
│   ├── observability_spec.md
│   ├── test_plan.md
│   └── ... (11 artifacts)
├── build/                  # Flow 3 artifacts
│   ├── build_receipt.json
│   ├── code_critique.md
│   ├── test_critique.md
│   ├── impl_changes_summary.md
│   └── ... (12 artifacts)
├── review/                 # Flow 4 artifacts
│   ├── pr_feedback_summary.md
│   ├── review_worklist.md
│   ├── review_actions.md
│   └── ... (6 artifacts)
├── gate/                   # Flow 5 artifacts
│   ├── receipt_audit.md
│   ├── contract_status.md
│   ├── security_status.md
│   ├── merge_recommendation.md
│   └── ... (8 artifacts)
├── deploy/                 # Flow 6 artifacts
│   ├── deployment_verification.md
│   ├── regression_report.md
│   ├── flow_timeline.md
│   └── verification_report.md
├── wisdom/                 # Flow 7 artifacts
│   ├── artifact_audit.md
│   ├── learnings.md
│   └── feedback_actions.md
├── reports/                # Generated diagnostics
│   ├── flow-build-report.txt
│   └── ... (per-flow reports)
├── EXPECTED_ARTIFACTS.md   # Artifact checklist
└── README.md
```

**Key Artifacts**:
- `signal/problem_statement.md`: Canonical problem framing
- `plan/adr_current.md`: Architecture decision record
- `build/build_receipt.json`: Machine-readable receipt with all verification data
- `review/pr_feedback_summary.md`: Consolidated PR feedback from reviewers
- `gate/merge_recommendation.md`: Final gate decision (MERGE)
- `deploy/verification_report.md`: Post-deploy verification
- `wisdom/learnings.md`: Extracted patterns and lessons learned

**Flow Studio Status**:
- Signal: GREEN
- Plan: GREEN
- Build: GREEN
- Review: GREEN
- Gate: GREEN
- Deploy: GREEN
- Wisdom: GREEN

**Educational Value**: This is the **reference implementation**. All other scenarios compare against this baseline. Study this first to understand artifact shapes and flow contracts.

---

### 2. health-check-missing-tests (Degraded Build)

> Teaching scenario: Build flow completed with missing test artifacts, gate bounces back.

**Scenario**: Build flow runs but `test-author` step fails to produce required test artifacts. Review and Gate detect the gap and bounce back.

**Directory Structure**:
```
health-check-missing-tests/
├── run.json                    # Scenario metadata
├── signal/                     # Flow 1 - Complete
│   ├── problem_statement.md
│   └── requirements_functional.md
├── plan/                       # Flow 2 - Complete
│   ├── adr_current.md
│   └── work_plan.md
├── build/                      # Flow 3 - DEGRADED
│   ├── subtask_context_manifest.json
│   ├── impl_changes_summary.md
│   ├── code_critique.md
│   └── build_receipt.json     # Status shows test step incomplete
├── review/                     # Flow 4 - DETECTED
│   ├── pr_feedback_summary.md # Flags missing test coverage
│   └── review_worklist.md
└── gate/                       # Flow 5 - BOUNCE
    ├── receipt_audit.md       # Identifies missing test artifacts
    └── merge_recommendation.md # Status: BOUNCE
```

**Key Artifacts**:
- `review/pr_feedback_summary.md`: Initial detection of missing tests
- `gate/receipt_audit.md`: Shows which artifacts are missing
- `gate/merge_recommendation.md`: Status is `BOUNCE` with reason "missing test coverage"

**Flow Studio Status**:
- Signal: GREEN
- Plan: GREEN
- Build: YELLOW (missing `test_changes_summary.md`)
- Review: YELLOW (detected issues)
- Gate: RED (BOUNCE)
- Deploy: GRAY (not started)
- Wisdom: GRAY (not started)

**Educational Value**: Demonstrates that **incomplete flows are detectable**. Review and Gate enforce receipts and bounce work back to Build rather than trying to fix test gaps. The human reviews `merge_recommendation.md` to understand why.

**Contrast with Baseline**: Baseline has all test artifacts; this scenario is missing `test_changes_summary.md`.

---

### 3. health-check-no-gate-decision (Incomplete Gate)

> Teaching scenario: Gate flow incomplete - individual checks passed but decision artifact missing.

**Scenario**: Build and Review flows complete successfully, but Gate flow performs individual verification steps without the `merge-decider` agent being invoked, leaving no final decision artifact.

**Directory Structure**:
```
health-check-no-gate-decision/
├── run.json                    # Scenario metadata
├── signal/                     # Flow 1 - Complete
│   ├── problem_statement.md
│   └── requirements_functional.md
├── plan/                       # Flow 2 - Complete
│   ├── adr_current.md
│   └── work_plan.md
├── build/                      # Flow 3 - Complete
│   ├── subtask_context_manifest.json
│   ├── test_changes_summary.md
│   ├── impl_changes_summary.md
│   ├── code_critique.md
│   └── build_receipt.json
├── review/                     # Flow 4 - Complete
│   ├── pr_feedback_summary.md
│   └── review_worklist.md
└── gate/                       # Flow 5 - INCOMPLETE
    ├── receipt_audit.md        # Present
    └── security_status.md      # Present
    # MISSING: merge_recommendation.md
```

**Key Artifacts**:
- `review/pr_feedback_summary.md`: Review flow completed
- `gate/receipt_audit.md`: Individual check completed
- `gate/security_status.md`: Individual check completed
- **Missing**: `gate/merge_recommendation.md` (the decision artifact)

**Flow Studio Status**:
- Signal: GREEN
- Plan: GREEN
- Build: GREEN
- Review: GREEN
- Gate: YELLOW (incomplete - no decision)
- Deploy: GRAY (cannot start without gate decision)
- Wisdom: GRAY (not started)

**Educational Value**: Demonstrates that **individual checks are not enough**. A final decision artifact is required for the flow to be complete. Deploy cannot proceed without Gate's `merge_recommendation.md`.

**Contrast with Baseline**: Baseline has `merge_recommendation.md`; this scenario is missing it.

**Contrast with missing-tests**: In `missing-tests`, Gate completes and produces a decision (BOUNCE). Here, Gate is incomplete and produces no decision.

---

### 4. health-check-risky-deploy (Risk Management)

> Teaching scenario: Complete flows with risk warnings, conditional approval, monitored deployment.

**Scenario**: All flows complete successfully, but with documented risks. Review consolidates feedback, Gate approves with conditions (MERGE_WITH_CONDITIONS), and Deploy proceeds with enhanced monitoring.

**Directory Structure**:
```
health-check-risky-deploy/
├── run.json                    # Scenario metadata
├── signal/                     # Flow 1 - Complete with risk
│   ├── problem_statement.md
│   ├── requirements_functional.md
│   └── early_risk_assessment.md  # Identifies performance concern
├── plan/                       # Flow 2 - Complete with mitigation
│   ├── adr_current.md
│   ├── work_plan.md
│   └── observability_spec.md  # Adds monitoring for mitigation
├── build/                      # Flow 3 - Complete
│   ├── subtask_context_manifest.json
│   ├── test_changes_summary.md
│   ├── impl_changes_summary.md
│   ├── code_critique.md
│   └── build_receipt.json
├── review/                     # Flow 4 - Complete with risk notes
│   ├── pr_feedback_summary.md
│   ├── review_worklist.md
│   └── review_risk_notes.md   # Flags risks identified in PR review
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
    ├── learnings.md
    └── feedback_actions.md
```

**Key Artifacts**:
- `signal/early_risk_assessment.md`: Identifies performance concern early
- `plan/observability_spec.md`: Adds monitoring for risk mitigation
- `review/pr_feedback_summary.md`: PR reviewers flag risks
- `gate/gate_risk_report.md`: Documents the accepted risk
- `gate/merge_recommendation.md`: Status is `MERGE_WITH_CONDITIONS`
- `deploy/deployment_decision.md`: Shows `proceed_with_risk: true`
- `wisdom/learnings.md`: Extracts patterns for future improvement

**Flow Studio Status**:
- Signal: GREEN (with risk documentation)
- Plan: GREEN (with mitigation plan)
- Build: GREEN
- Review: YELLOW (risks noted)
- Gate: YELLOW (CONDITIONAL - approved with monitoring requirements)
- Deploy: GREEN (deployed with monitoring)
- Wisdom: GREEN (with learnings)

**Educational Value**: Demonstrates the swarm's approach to risk:
1. **Early identification**: Signal flow identifies performance concern
2. **Mitigation planning**: Plan flow adds observability spec
3. **Review feedback**: Review flow captures risks from PR reviewers
4. **Informed decision**: Gate evaluates risk vs mitigation, approves with conditions
5. **Monitored deployment**: Deploy proceeds with enhanced instrumentation
6. **Learning extraction**: Wisdom analyzes for regression detection

The swarm aims for **managed risk with receipts**, not zero risk.

**Contrast with Baseline**: Baseline has clean approval with no risks; this scenario has managed risk with conditional approval.

---

### 5. swarm-selftest-baseline (Infrastructure)

> Captured example of the Swarm Selftest output for a healthy swarm configuration.

**Scenario**: Not a flow execution, but a selftest report showing swarm governance health.

**Directory Structure**:
```
swarm-selftest-baseline/
├── selftest_report.json   # Full structured output
├── status_snapshot.json   # Compact governance status
├── notes.md               # Commentary and interpretation guide
├── run.json               # Scenario metadata
└── README.md
```

**Key Artifacts**:
- `selftest_report.json`: Full 16-step selftest report with:
  - Metadata (run ID, timestamp, git state)
  - Summary (overall status, pass/fail counts)
  - Tier breakdown (Kernel, Governance, Optional)
  - Per-step details (command, duration, exit code)
- `status_snapshot.json`: Compact summary for dashboards
- `notes.md`: How to interpret the report

**Selftest Steps** (all passing in baseline):

| Step | Tier | Description |
|------|------|-------------|
| core-checks | KERNEL | Python lint + compile check |
| skills-governance | GOVERNANCE | Skills YAML validation |
| agents-governance | GOVERNANCE | Agent bijection, colors |
| bdd | GOVERNANCE | BDD feature file structure |
| ac-status | GOVERNANCE | Acceptance criteria tracking |
| policy-tests | GOVERNANCE | OPA policy validation |
| devex-contract | GOVERNANCE | Flow/agent/skill contracts |
| graph-invariants | GOVERNANCE | Flow graph connectivity |
| ac-coverage | OPTIONAL | Coverage thresholds |
| extras | OPTIONAL | Experimental checks |

**Educational Value**:
- Shows agents how to interpret selftest reports
- Provides stable fixture for Flow 6 (Wisdom) integration
- Demonstrates the 16-step pattern in action
- Explains tier/severity/category dimensions

---

### 6. swarm-alignment (Complete Governance Verification)

> Complete governance verification run demonstrating all 7 flows with canonical directory naming.

**Scenario**: Self-referential governance validation - the swarm validates its own configuration through all SDLC flows.

**Location**: `swarm/runs/swarm-alignment/`

**What it demonstrates**:
- Full Flow 1-7 coverage (Signal -> Wisdom)
- Review flow integration between Build and Gate
- Branch protection configuration
- Self-referential governance validation
- Canonical directory naming (`review/`, `deploy/`, `wisdom/`)

**Directory Structure**:
```
swarm-alignment/
├── signal/                     # Flow 1 artifacts
│   └── ...
├── plan/                       # Flow 2 artifacts
│   └── ...
├── build/                      # Flow 3 artifacts
│   └── ...
├── review/                     # Flow 4 artifacts
│   ├── pr_feedback_summary.md
│   ├── review_worklist.md
│   └── ...
├── gate/                       # Flow 5 artifacts
│   ├── receipt_audit.md
│   ├── merge_recommendation.md
│   └── ...
├── deploy/                     # Flow 6 artifacts (canonical naming)
│   ├── branch_protection.md
│   ├── deployment_decision.md
│   ├── deployment_log.md
│   └── verification_report.md
├── wisdom/                     # Flow 7 artifacts
│   ├── artifact_audit.md
│   ├── feedback_actions.md
│   ├── flow_history.json
│   ├── learnings.md
│   └── regression_report.md
├── EXECUTION_CHECKLIST.md
└── README.md
```

**Key Artifacts**:
- `review/pr_feedback_summary.md`: Consolidated PR feedback
- `gate/merge_recommendation.md`: Gate decision
- `deploy/branch_protection.md`: GitHub branch protection configuration
- `deploy/verification_report.md`: Post-deployment verification
- `wisdom/learnings.md`: Meta-learnings from governance implementation
- `wisdom/feedback_actions.md`: Recommended improvements for future runs

**Flow Studio Status**:
- Signal: GREEN
- Plan: GREEN
- Build: GREEN
- Review: GREEN
- Gate: GREEN
- Deploy: GREEN
- Wisdom: GREEN

**Educational Value**: This is the only example with **complete Flow 1-7 coverage using canonical naming**. Use this to understand:
- How Review flow fits between Build and Gate
- How review artifacts differ from gate artifacts
- What wisdom extraction looks like in practice
- How the swarm closes feedback loops

**Note**: Unlike examples in `swarm/examples/`, this run lives in `swarm/runs/` and demonstrates an active governance run rather than a teaching snapshot.

---

## How to Use These Examples

### For New Users

1. **Start with `health-check`**: Read artifacts in order (signal -> plan -> build -> gate -> operate)
2. **Focus on key files**:
   - `signal/problem_statement.md`: How the swarm frames problems
   - `plan/adr_current.md`: How design decisions are documented
   - `build/build_receipt.json`: The structured output that ties everything together
   - `gate/merge_recommendation.md`: How the gate evaluates readiness
3. **Then explore failure scenarios**: See how incomplete work is detected

### For Agent Authors

Each flow's artifacts show what that flow's agents produce:

| Flow | Example Artifacts | Producing Agents |
|------|-------------------|------------------|
| Signal | `problem_statement.md`, `requirements_functional.md` | signal-normalizer, problem-framer, requirements-author |
| Plan | `adr_current.md`, `interface_spec.md`, `test_plan.md` | adr-author, interface-designer, test-strategist |
| Build | `build_receipt.json`, `code_critique.md`, `test_critique.md` | code-implementer, code-critic, test-critic |
| Review | `pr_feedback_summary.md`, `review_worklist.md` | review-collector, review-summarizer |
| Gate | `receipt_audit.md`, `merge_recommendation.md` | receipt-checker, merge-decider |
| Deploy | `deployment_log.md`, `verification_report.md` | deploy-monitor, smoke-verifier |
| Wisdom | `learnings.md`, `feedback_actions.md` | learning-synthesizer, feedback-applier |

### For Orchestrator Implementers

These snapshots define the **contract** your orchestrator must implement:

- **RUN_BASE layout**: Artifacts under `<flow>/` subdirectories
- **Artifact shapes**: See JSON schemas in `build_receipt.json`, `flow_history.json`
- **Microloop evidence**: Check `test_critique.md` -> `test_changes_summary.md` cycles
- **Git ops**: Look for `git_status.txt`, commit messages in `build/`

If your orchestrator can produce these artifacts in this structure, it is compatible with the swarm spec.

---

## Artifact Checklist by Flow

### Flow 1 - Signal

| Artifact | Required | Description |
|----------|----------|-------------|
| `issue_normalized.md` | Yes | Normalized incoming signal |
| `problem_statement.md` | Yes | Canonical problem statement |
| `requirements_functional.md` | Yes | Functional requirements |
| `requirements_constraints.md` | No | Non-functional requirements |
| `early_risk_assessment.md` | No | Early risk identification |
| `clarification_questions.md` | No | Questions for humans |
| `context_brief.md` | No | Summarized internal context |
| `doc_research.md` | No | External research summary |

### Flow 2 - Plan

| Artifact | Required | Description |
|----------|----------|-------------|
| `adr_current.md` | Yes | Architecture decision record |
| `interface_spec.md` | Yes | API/interface contract |
| `test_plan.md` | Yes | Test strategy |
| `implementation_plan.md` | Yes | Work breakdown |
| `observability_spec.md` | No | Telemetry/metrics spec |
| `policy_plan.md` | No | Policy checks to run |
| `design_options.md` | No | Candidate designs |
| `impact_map.json` | No | Impact mapping |

### Flow 3 - Build

| Artifact | Required | Description |
|----------|----------|-------------|
| `build_receipt.json` | Yes | Machine-readable receipt |
| `test_changes_summary.md` | Yes | Test changes |
| `impl_changes_summary.md` | Yes | Code changes |
| `code_critique.md` | Yes | Code critic output |
| `test_critique.md` | Yes | Test critic output |
| `self_review.md` | No | Self-review output |
| `mutation_report.md` | No | Mutation testing results |
| `subtask_context_manifest.json` | No | Context bundle |

### Flow 4 - Review

| Artifact | Required | Description |
|----------|----------|-------------|
| `pr_feedback_summary.md` | Yes | Consolidated PR feedback |
| `review_worklist.md` | Yes | Itemized feedback list |
| `review_actions.md` | No | Actions taken from feedback |
| `review_risk_notes.md` | No | Risk signals from PR review |
| `final_status.md` | No | Review completion status |

### Flow 5 - Gate

| Artifact | Required | Description |
|----------|----------|-------------|
| `merge_recommendation.md` | Yes | Final decision (MERGE/BOUNCE/ESCALATE) |
| `receipt_audit.md` | Yes | Receipt verification |
| `contract_status.md` | No | API contract check |
| `security_status.md` | No | Security scan summary |
| `policy_verdict.md` | No | Policy gate outcome |
| `gate_risk_report.md` | No | Aggregated risk signals |
| `gate_fix_summary.md` | No | Trivial fixes applied |

### Flow 6 - Deploy

| Artifact | Required | Description |
|----------|----------|-------------|
| `deployment_decision.md` | Yes | Deploy decision |
| `deployment_log.md` | Yes | Deployment record |
| `verification_report.md` | Yes | Post-deploy verification |

### Flow 7 - Wisdom

| Artifact | Required | Description |
|----------|----------|-------------|
| `artifact_audit.md` | Yes | Cross-run artifact analysis |
| `regression_report.md` | No | Detected regressions |
| `learnings.md` | No | Extracted patterns |
| `feedback_actions.md` | No | Recommended feedback actions |
| `flow_history.json` | No | Run history |

---

## How to Regenerate Examples

### Regenerating health-check (Complete Baseline)

```bash
# 1. Clear the example
rm -rf swarm/examples/health-check/{signal,plan,build,review,gate,deploy,wisdom,reports}

# 2. Run all 7 flows with a new run ID
/flow-1-signal health-check-v2 "Add a health-check endpoint"
/flow-2-plan health-check-v2
/flow-3-build health-check-v2
/flow-4-review health-check-v2
/flow-5-gate health-check-v2
/flow-6-deploy health-check-v2
/flow-7-wisdom health-check-v2

# 3. Copy artifacts from active run to example
cp -r swarm/runs/health-check-v2/* swarm/examples/health-check/

# 4. Update code-snapshot if needed
cp src/handlers/health.rs swarm/examples/health-check/code-snapshot/
cp features/health.feature swarm/examples/health-check/code-snapshot/

# 5. Generate reports
uv run swarm/tools/run_flow_dry.py --example health-check
```

### Regenerating Failure Scenarios

For scenarios like `health-check-missing-tests`:

1. Run flows normally until the failure point
2. Manually remove or omit the specific artifact to demonstrate the failure
3. Run Gate to capture the bounce decision
4. Update `run.json` with scenario metadata

### Regenerating Selftest Baseline

```bash
# 1. Run selftest and capture output
make selftest

# 2. Copy report to example
cp swarm/runs/<run-id>/build/selftest_report.json \
   swarm/examples/swarm-selftest-baseline/

# 3. Update notes.md if step structure changed
```

---

## Related Documentation

- `swarm/positioning.md`: Philosophy and axioms behind the swarm
- `swarm/SELFTEST_SYSTEM.md`: Complete selftest system specification
- `swarm/flows/flow-*.md`: Individual flow specifications
- `swarm/AGENTS.md`: Agent registry
- `CLAUDE.md`: Main developer reference

---

## Stepwise Execution Examples

These examples demonstrate stepwise backend execution with per-step observability.

| Example | Backend | Flows | Learning Goal |
|---------|---------|-------|---------------|
| `stepwise-gemini` | Gemini CLI (stepwise) | signal, plan | Per-step transcripts with Gemini |
| `stepwise-claude` | Claude SDK (stepwise) | signal, plan | Alternative backend comparison |

### What to Look For

1. **Transcripts** (`<flow>/llm/*.jsonl`): Raw LLM conversation for each step
2. **Receipts** (`<flow>/receipts/*.json`): Structured metadata (duration, tokens, status)
3. **Events** (`events.jsonl`): Step-by-step lifecycle events

### Viewing in Flow Studio

```bash
# Copy example to runs directory
cp -r swarm/examples/stepwise-gemini swarm/runs/stepwise-gemini

# Start Flow Studio and open
make flow-studio
# Navigate to http://localhost:5000/?run=stepwise-gemini&mode=operator
```

Select a step and click the "Transcript" tab to see the LLM conversation.

---

## Wisdom Coverage Matrix

This matrix shows which examples have wisdom summaries generated.

| Example | Has Wisdom | Reason |
|---------|------------|--------|
| `health-check` | Yes | Complete 7-flow example |
| `health-check-missing-tests` | No | **Teaching**: demonstrates missing test artifact |
| `health-check-no-gate-decision` | No | **Teaching**: demonstrates incomplete gate |
| `health-check-risky-deploy` | Yes | Complete 7-flow with risk management |
| `stepwise-claude` | Yes | Two-flow stepwise (signal + plan) |
| `stepwise-build-claude` | Yes | Three-flow stepwise (signal + plan + build) |
| `stepwise-gate-claude` | Yes | Four-flow stepwise |
| `stepwise-deploy-claude` | Yes | Five-flow stepwise |
| `stepwise-sdlc-claude` | Yes | Full 7-flow SDLC |
| `stepwise-build-gemini` | Yes | Gemini backend comparison |
| `stepwise-gemini` | Yes | Gemini two-flow |
| `swarm-selftest-baseline` | No | **Metadata**: baseline config, not a run |

**Generate missing summaries**: `make wisdom-examples`

---

## Changelog

| Date | Change |
|------|--------|
| 2025-12-30 | Updated all flows to include Review (Flow 4); renumbered Deploy (Flow 6) and Wisdom (Flow 7) |
| 2025-12-10 | Added Wisdom Coverage Matrix section |
| 2025-12-09 | Added Stepwise Execution Examples section |
| 2025-12-01 | Added swarm-alignment run; clarified operate/ vs deploy/ naming |
| 2025-12-01 | Initial documentation with 5 golden runs |
