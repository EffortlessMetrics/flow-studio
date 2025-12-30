# Signal -> Plan Handoff Contract

> **Version:** 1.0.0
> **Status:** Canonical
> **Last Updated:** 2025-12-29

This document defines the **formal contract** between Flow 1 (Signal) and Flow 2 (Plan). It specifies exactly what artifacts Flow 1 must produce and what Flow 2 expects to consume.

---

## Contract Summary

| Producer | Consumer | Handoff Point | Key Artifact |
|----------|----------|---------------|--------------|
| Flow 1 (Signal) | Flow 2 (Plan) | `requirements.md` | Verified requirements with acceptance criteria |

---

## Flow 1 Outputs (Required)

### Primary Artifact: `RUN_BASE/signal/requirements.md`

The `requirements.md` is the **canonical handoff artifact**. It MUST include:

```markdown
# Requirements

## Functional Requirements

### REQ-001: [Title]
- **Priority:** MUST | SHOULD | COULD | WONT
- **Description:** [What the system must do]
- **Acceptance Criteria:**
  - AC-001.1: [Testable criterion]
  - AC-001.2: [Testable criterion]
- **Dependencies:** [Other REQs or external systems]
- **Risk Level:** low | medium | high

## Non-Functional Requirements

### NFR-001: [Title]
- **Category:** performance | security | reliability | usability
- **Description:** [Constraint or quality attribute]
- **Measurable Target:** [Quantifiable threshold]

## Assumptions Made to Proceed
- Assumption: [what] -> [why] -> [impact if wrong]

## Questions / Clarifications Needed
- Question: [what] -> [default answer] -> [impact if different]
```

### Supporting Artifacts

Flow 1 also produces these artifacts in `RUN_BASE/signal/`:

| Artifact | Purpose | Required |
|----------|---------|----------|
| `problem_statement.md` | Goals, non-goals, constraints, success criteria | Yes |
| `issue_normalized.md` | Structured summary of raw input | Yes |
| `context_brief.md` | Related history and context | Yes |
| `clarification_questions.md` | Open questions and assumptions | Yes |
| `requirements_critique.md` | Verdict on requirements quality | Yes |
| `features/*.feature` | BDD scenarios (Gherkin format) | Yes |
| `example_matrix.md` | Edge cases and boundary conditions | Optional |
| `stakeholders.md` | Teams, systems, users affected | Yes |
| `early_risks.md` | First-pass risk identification | Yes |
| `scope_estimate.md` | S/M/L/XL estimate with rationale | Yes |

---

## Flow 2 Inputs (Expected)

### Required Inputs

1. **`RUN_BASE/signal/requirements.md`**
   - MUST exist
   - MUST contain functional requirements with IDs (REQ-xxx)
   - MUST contain acceptance criteria per requirement
   - MUST have priority classification (MUST/SHOULD/COULD/WONT)

2. **`RUN_BASE/signal/problem_statement.md`**
   - MUST exist
   - MUST define success criteria
   - MUST list constraints

3. **`RUN_BASE/signal/features/*.feature`**
   - At least one BDD scenario MUST exist
   - Scenarios MUST be linked to requirements via tags

4. **`RUN_BASE/signal/early_risks.md`**
   - MUST exist
   - Informs design trade-offs

### Input Validation

Flow 2's first step MUST validate:

```python
def validate_signal_handoff(run_base: Path) -> ValidationResult:
    signal_dir = run_base / "signal"

    # Check required files
    required_files = [
        "requirements.md",
        "problem_statement.md",
        "requirements_critique.md",
        "early_risks.md",
        "scope_estimate.md"
    ]

    missing = [f for f in required_files if not (signal_dir / f).exists()]
    if missing:
        return ValidationResult(
            valid=False,
            error=f"BLOCKED: Missing required signal artifacts: {missing}"
        )

    # Check BDD scenarios exist
    features = list((signal_dir / "features").glob("*.feature"))
    if not features:
        return ValidationResult(
            valid=False,
            error="BLOCKED: No BDD scenarios found in signal/features/"
        )

    # Parse requirements
    requirements = parse_requirements(signal_dir / "requirements.md")

    # Validate requirements have IDs and acceptance criteria
    for req in requirements:
        if not req.id or not req.id.startswith("REQ-"):
            return ValidationResult(
                valid=False,
                error=f"BLOCKED: Requirement missing ID: {req}"
            )
        if not req.acceptance_criteria:
            return ValidationResult(
                valid=False,
                error=f"BLOCKED: REQ {req.id} missing acceptance criteria"
            )

    return ValidationResult(valid=True)
```

---

## Requirements Quality Contract

### Preconditions for Plan to Proceed

Plan (Flow 2) may proceed when **ALL** of these conditions are met:

1. **Requirements Exist:** `requirements.md` has at least one REQ-xxx entry
2. **Acceptance Criteria Present:** Each requirement has testable AC entries
3. **BDD Coverage:** At least one `.feature` file references requirements
4. **Risk Assessment:** `early_risks.md` exists with categorized risks
5. **Scope Bounded:** `scope_estimate.md` provides size estimate

### Quality Signals from `requirements_critique.md`

```yaml
status: VERIFIED | UNVERIFIED | BLOCKED

requirements_quality:
  completeness: "All user stories have ACs"
  testability: "ACs are measurable"
  consistency: "No conflicting requirements"
  feasibility: "Within technical constraints"

can_further_iteration_help: yes | no

concerns:
  - "REQ-003 acceptance criteria are vague"
  - "Missing NFR for response time"

recommendations:
  - "Add performance NFR before design"
```

---

## What Plan Expects

### Verified Requirements with Acceptance Criteria

Flow 2 agents (`impact-analyzer`, `design-optioneer`, etc.) expect:

1. **Clear Problem Boundaries:**
   - `problem_statement.md` defines what is in/out of scope
   - Success criteria are measurable

2. **Implementable Requirements:**
   - Each REQ has acceptance criteria that can become test cases
   - Priority is clear (MUST vs SHOULD)
   - Dependencies between requirements are documented

3. **Testable Behaviors:**
   - BDD scenarios in `features/*.feature` exercise key flows
   - Edge cases identified in `example_matrix.md`

4. **Risk Context:**
   - `early_risks.md` informs architectural decisions
   - Security/compliance risks flag NFR needs

5. **Scope Constraints:**
   - `scope_estimate.md` informs work breakdown
   - Complexity flags inform design options

---

## Error Handling

### Missing `requirements.md`

If `requirements.md` is missing, Flow 2 MUST:

1. Set status to `BLOCKED`
2. Write to `RUN_BASE/plan/plan_receipt.json`:
   ```json
   {
     "status": "BLOCKED",
     "summary": "Cannot proceed: requirements.md not found",
     "blockers": [{
       "type": "missing_input",
       "description": "Flow 1 did not produce requirements.md",
       "recoverable": true
     }]
   }
   ```
3. Recommend re-running Flow 1

### Missing BDD Scenarios

If `features/*.feature` directory is empty, Flow 2 MUST:

1. Set status to `BLOCKED`
2. Document that test strategy cannot be formed without BDD scenarios
3. Recommend re-running Flow 1 with focus on BDD authoring

### Unverified Requirements

If `requirements_critique.md` shows `status: UNVERIFIED`:

1. Flow 2 MAY proceed with documented assumptions
2. `impact-analyzer` must note which requirements are uncertain
3. `design-optioneer` should propose options that accommodate ambiguity
4. All assumptions must be captured in `RUN_BASE/plan/assumptions.md`

---

## Handoff Envelope Schema

For programmatic validation, the handoff can be represented as:

```json
{
  "schema_version": "1.0.0",
  "producer_flow": "signal",
  "consumer_flow": "plan",
  "run_id": "<run-id>",
  "timestamp": "<ISO 8601>",

  "primary_artifact": {
    "path": "signal/requirements.md",
    "exists": true,
    "requirements_count": 5,
    "must_have_count": 3,
    "should_have_count": 2
  },

  "supporting_artifacts": {
    "problem_statement": {"path": "signal/problem_statement.md", "exists": true},
    "bdd_scenarios": {"path": "signal/features/", "count": 3},
    "requirements_critique": {
      "path": "signal/requirements_critique.md",
      "status": "VERIFIED"
    },
    "early_risks": {"path": "signal/early_risks.md", "exists": true},
    "scope_estimate": {"path": "signal/scope_estimate.md", "exists": true}
  },

  "validation": {
    "all_requirements_have_ids": true,
    "all_requirements_have_ac": true,
    "bdd_scenarios_exist": true,
    "risks_documented": true
  },

  "handoff_ready": true
}
```

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0.0 | 2025-12-29 | Initial contract definition |
