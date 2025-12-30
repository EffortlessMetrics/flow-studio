# Plan -> Build Handoff Contract

> **Version:** 1.0.0
> **Status:** Canonical
> **Last Updated:** 2025-12-29

This document defines the **formal contract** between Flow 2 (Plan) and Flow 3 (Build). It specifies exactly what artifacts Flow 2 must produce and what Flow 3 expects to consume.

---

## Contract Summary

| Producer | Consumer | Handoff Point | Key Artifact |
|----------|----------|---------------|--------------|
| Flow 2 (Plan) | Flow 3 (Build) | `work_plan.md` | Implementable design with clear subtasks |

---

## Flow 2 Outputs (Required)

### Primary Artifact: `RUN_BASE/plan/work_plan.md`

The `work_plan.md` is the **canonical handoff artifact** for orchestrating Build. It MUST include:

```markdown
# Work Plan

## Overview
- **Total Subtasks:** <count>
- **Estimated Complexity:** S | M | L | XL
- **Dependencies:** [External systems, APIs, etc.]

## Subtasks

### SUBTASK-001: [Title]
- **Description:** [What to implement]
- **Requirements:** REQ-001, REQ-002
- **Files to Touch:** [src/module/file.py, tests/test_module.py]
- **Dependencies:** [Other subtasks that must complete first]
- **Acceptance Criteria:** AC-001.1, AC-001.2
- **Test Strategy:** unit | integration | e2e
- **Estimated Effort:** S | M | L

### SUBTASK-002: [Title]
...

## Execution Order
1. SUBTASK-001 (no dependencies)
2. SUBTASK-002 (depends on SUBTASK-001)
3. SUBTASK-003, SUBTASK-004 (can run in parallel)

## Rollout Strategy
- **Approach:** all-at-once | incremental | feature-flag
- **Rationale:** [Why this approach]
```

### Supporting Artifacts

Flow 2 also produces these artifacts in `RUN_BASE/plan/`:

| Artifact | Purpose | Required |
|----------|---------|----------|
| `adr.md` | Architecture Decision Record with rationale | Yes |
| `api_contracts.yaml` | API endpoints, schemas, error shapes | Yes |
| `schema.md` | Data models, relationships, invariants | Yes |
| `test_plan.md` | BDD -> test types mapping, priorities | Yes |
| `observability_spec.md` | Metrics, logs, traces, SLOs | Yes |
| `impact_map.json` | Affected services, modules, files | Yes |
| `design_options.md` | 2-3 architecture options with trade-offs | Yes |
| `design_validation.md` | Feasibility assessment, known issues | Yes |
| `migrations/*.sql` | Draft database migrations | If needed |

---

## Flow 3 Inputs (Expected)

### Required Inputs

1. **`RUN_BASE/plan/work_plan.md`**
   - MUST exist
   - MUST contain at least one SUBTASK entry
   - Each subtask MUST reference requirement IDs
   - Execution order MUST be defined

2. **`RUN_BASE/plan/adr.md`**
   - MUST exist
   - MUST document chosen architecture approach
   - MUST list consequences and trade-offs

3. **`RUN_BASE/plan/api_contracts.yaml`**
   - MUST exist if API changes are planned
   - Defines the shape code must implement

4. **`RUN_BASE/plan/test_plan.md`**
   - MUST exist
   - Maps requirements to test types
   - Defines coverage expectations

5. **`RUN_BASE/plan/impact_map.json`**
   - MUST exist
   - Lists files and modules that will be changed

### Input Validation

Flow 3's `context-loader` step MUST validate:

```python
def validate_plan_handoff(run_base: Path) -> ValidationResult:
    plan_dir = run_base / "plan"

    # Check required files
    required_files = [
        "work_plan.md",
        "adr.md",
        "test_plan.md",
        "impact_map.json"
    ]

    missing = [f for f in required_files if not (plan_dir / f).exists()]
    if missing:
        return ValidationResult(
            valid=False,
            error=f"BLOCKED: Missing required plan artifacts: {missing}"
        )

    # Parse work plan
    work_plan = parse_work_plan(plan_dir / "work_plan.md")

    # Validate subtasks exist
    if not work_plan.subtasks:
        return ValidationResult(
            valid=False,
            error="BLOCKED: work_plan.md contains no subtasks"
        )

    # Validate each subtask has requirements linkage
    for subtask in work_plan.subtasks:
        if not subtask.requirements:
            return ValidationResult(
                valid=False,
                error=f"BLOCKED: {subtask.id} missing requirements linkage"
            )

    # Validate impact map
    impact_map = json.load((plan_dir / "impact_map.json").open())
    if not impact_map.get("files") and not impact_map.get("modules"):
        return ValidationResult(
            valid=False,
            error="BLOCKED: impact_map.json has no files or modules"
        )

    return ValidationResult(valid=True)
```

---

## Design Quality Contract

### Preconditions for Build to Proceed

Build (Flow 3) may proceed when **ALL** of these conditions are met:

1. **ADR Approved:** `adr.md` documents a chosen approach
2. **Work Breakdown Complete:** `work_plan.md` has subtasks with requirements
3. **Test Strategy Defined:** `test_plan.md` maps requirements to test types
4. **Impact Scoped:** `impact_map.json` identifies affected code

### Quality Signals from `design_validation.md`

```yaml
status: VERIFIED | UNVERIFIED | BLOCKED

design_quality:
  feasibility: "Design is implementable with current stack"
  completeness: "All requirements have design coverage"
  testability: "Design supports testing strategy"
  maintainability: "Complexity within acceptable bounds"

can_further_iteration_help: yes | no

concerns:
  - "API contract may conflict with legacy endpoint"
  - "Schema migration requires downtime"

recommendations:
  - "Add feature flag for gradual rollout"
```

---

## What Build Expects

### Implementable Design with Clear Subtasks

Flow 3 agents (`context-loader`, `test-author`, `code-implementer`) expect:

1. **Clear Architecture Direction:**
   - `adr.md` provides rationale for implementation choices
   - Trade-offs are documented (Build knows what was sacrificed)

2. **Concrete Work Items:**
   - Each subtask in `work_plan.md` is independently implementable
   - Requirements linkage enables traceability
   - File paths in `impact_map.json` guide context loading

3. **Defined Contracts:**
   - `api_contracts.yaml` specifies exact API shapes
   - `schema.md` defines data structures
   - Build implements TO these contracts, not around them

4. **Test Guidance:**
   - `test_plan.md` tells test-author what kinds of tests to write
   - Coverage expectations are quantified
   - Priorities help when time is constrained

5. **Observability Requirements:**
   - `observability_spec.md` tells code-implementer what to instrument
   - Metrics and log points are specified upfront

---

## Error Handling

### Missing `work_plan.md`

If `work_plan.md` is missing, Flow 3 MUST:

1. Set status to `BLOCKED`
2. Write to `RUN_BASE/build/build_receipt.json`:
   ```json
   {
     "status": "BLOCKED",
     "summary": "Cannot proceed: work_plan.md not found",
     "blockers": [{
       "type": "missing_input",
       "description": "Flow 2 did not produce work_plan.md",
       "recoverable": true
     }]
   }
   ```
3. Recommend re-running Flow 2

### Missing ADR

If `adr.md` is missing, Flow 3 MUST:

1. Set status to `BLOCKED`
2. Document that architectural guidance is required
3. Recommend re-running Flow 2 to produce ADR

### Empty Work Plan

If `work_plan.md` exists but has no subtasks:

1. Set status to `BLOCKED`
2. Document that work breakdown is incomplete
3. Recommend re-running Flow 2 with focus on work planning

### Unverified Design

If `design_validation.md` shows `status: UNVERIFIED`:

1. Flow 3 MAY proceed with documented caution
2. `context-loader` must note design concerns in manifest
3. `code-implementer` should implement defensively
4. All design assumptions must be captured in critiques

---

## Subtask Context Manifest

When Flow 3 starts a subtask, `context-loader` produces:

```json
{
  "subtask_id": "SUBTASK-001",
  "requirements": ["REQ-001", "REQ-002"],
  "acceptance_criteria": ["AC-001.1", "AC-001.2"],

  "context_sources": {
    "from_plan": {
      "adr": "plan/adr.md",
      "api_contracts": "plan/api_contracts.yaml",
      "schema": "plan/schema.md",
      "test_plan": "plan/test_plan.md"
    },
    "from_signal": {
      "requirements": "signal/requirements.md",
      "bdd_scenarios": ["signal/features/auth.feature"]
    },
    "from_codebase": {
      "files_to_modify": ["src/auth/handler.py"],
      "files_to_reference": ["src/auth/models.py"],
      "existing_tests": ["tests/test_auth.py"]
    }
  },

  "design_decisions": [
    "Use JWT tokens per ADR section 3.2",
    "Add logging per observability_spec.md"
  ],

  "known_concerns": [
    "design_validation.md flagged complexity"
  ]
}
```

---

## Handoff Envelope Schema

For programmatic validation, the handoff can be represented as:

```json
{
  "schema_version": "1.0.0",
  "producer_flow": "plan",
  "consumer_flow": "build",
  "run_id": "<run-id>",
  "timestamp": "<ISO 8601>",

  "primary_artifact": {
    "path": "plan/work_plan.md",
    "exists": true,
    "subtask_count": 4,
    "execution_order_defined": true
  },

  "supporting_artifacts": {
    "adr": {"path": "plan/adr.md", "exists": true},
    "api_contracts": {"path": "plan/api_contracts.yaml", "exists": true},
    "schema": {"path": "plan/schema.md", "exists": true},
    "test_plan": {"path": "plan/test_plan.md", "exists": true},
    "impact_map": {"path": "plan/impact_map.json", "exists": true},
    "design_validation": {
      "path": "plan/design_validation.md",
      "status": "VERIFIED"
    }
  },

  "validation": {
    "all_subtasks_have_requirements": true,
    "execution_order_defined": true,
    "adr_has_decision": true,
    "test_strategy_defined": true
  },

  "handoff_ready": true
}
```

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0.0 | 2025-12-29 | Initial contract definition |
