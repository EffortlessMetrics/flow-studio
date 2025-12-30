# Swarm Sidequest Registry

> Sidequests are pre-defined detour patterns that the Navigator can inject when specific conditions are detected.
> They provide bounded, catalog-based options for handling common interruptions without breaking flow execution.
> Sidequests live in `swarm/runtime/sidequest_catalog.py` (built-in) and `swarm/packs/stations/sidequests.yaml` (station configs).

<!-- META:SIDEQUEST_COUNTS -->
**Total: 6 built-in sidequests**
<!-- /META:SIDEQUEST_COUNTS -->

---

## Sidequests vs. Main Flows

| Aspect | Main Flows | Sidequests |
|--------|------------|------------|
| **Purpose** | Complete SDLC lifecycle stages | Handle interruptions and special cases |
| **Invocation** | Explicit (via `/flow-*` commands) | Automatic (trigger-based by Navigator) |
| **Scope** | Full flow with multiple steps | Single station or short mini-flow |
| **Return** | Flows complete at boundaries | Return to interrupted point |
| **State** | Own artifacts in `RUN_BASE/<flow>/` | May write to `RUN_BASE/sidequest/` or parent flow |
| **Frequency** | Once per SDLC cycle | Multiple times per flow as needed |

### When Sidequests Trigger

Sidequests are **suggested by the system** and **decided by the orchestrator**. The Navigator evaluates trigger conditions using traditional tooling (no LLM), then presents applicable sidequests as options. The orchestrator decides whether to inject them.

**Trigger evaluation is deterministic**: Field checks, stall detection, and path pattern matching happen without LLM involvement.

---

## Execution Model

### Sidequest Lifecycle

1. **Detection**: Navigator evaluates triggers against current context
2. **Selection**: Applicable sidequests sorted by priority; orchestrator decides
3. **Push**: Current state pushed to interruption stack
4. **Execute**: Sidequest station(s) run with injected objective
5. **Return**: Resume from interruption point (or bounce to specified node)

### Trigger Modes

| Mode | Description | Use Case |
|------|-------------|----------|
| `any` | Any trigger condition matches (OR) | Multiple possible causes |
| `all` | All trigger conditions must match (AND) | Specific failure signature |

### Return Behaviors

| Mode | Description | Example |
|------|-------------|---------|
| `resume` | Return to interrupted point | Default: continue where left off |
| `bounce_to` | Go to specific node | Security issue bounces to gate |
| `advance` | Skip to next node | Context loaded, skip redundant load |
| `halt` | Stop the flow | Critical failure requiring human |
| `conditional` | Evaluate condition to decide | Pass/fail determines path |

---

## All Sidequests

| ID | Name | Trigger | Primary Station | Priority | Cost | Max Uses |
|----|------|---------|-----------------|----------|------|----------|
| clarifier | Clarifier | Ambiguity OR stall >= 2 | `clarifier` | 70 | low | 3 |
| env-doctor | Environment Doctor | Environment failure OR import error | `fixer` | 80 | medium | 3 |
| test-triage | Test Triage | Verification failed AND same failure signature | `test-critic` | 60 | medium | 3 |
| security-audit | Security Audit | Paths match security patterns | `security-scanner` | 90 | high | 1 |
| contract-check | Contract Check | Paths match API/schema patterns | `contract-enforcer` | 75 | medium | 3 |
| context-refresh | Context Refresh | Stall >= 3 OR context insufficient | `context-loader` | 55 | low | 3 |

---

## Sidequest Details

### clarifier

**Purpose**: Resolve ambiguity or missing requirements by asking clarifying questions.

| Attribute | Value |
|-----------|-------|
| **ID** | `clarifier` |
| **Primary Station** | `clarifier` |
| **Priority** | 70 |
| **Cost Hint** | low |
| **Max Uses Per Run** | 3 |
| **Tags** | `requirements`, `ambiguity` |
| **Trigger Mode** | `any` |

**Trigger Conditions** (any match):
1. `has_ambiguity == true` - Ambiguity detected in inputs
2. `stall_count >= 2` - Progress stalled twice (same issue recurring)

**Objective Template**:
```
Clarify the following ambiguity: {{issue}}. Document assumptions and questions.
```

**Return Behavior**: `resume` - Returns to the interrupted point after clarification.

**Example Use Case**:
During Flow 3 (Build), the `code-implementer` encounters conflicting requirements between the ADR and the requirements doc. After two iterations without progress (stall_count >= 2), the Navigator suggests the clarifier sidequest. The clarifier station searches existing docs, documents assumptions, and returns control to the implementer with clarified context.

---

### env-doctor

**Purpose**: Diagnose and fix environment/build issues that are causing test failures.

| Attribute | Value |
|-----------|-------|
| **ID** | `env-doctor` |
| **Primary Station** | `fixer` |
| **Priority** | 80 |
| **Cost Hint** | medium |
| **Max Uses Per Run** | 3 |
| **Tags** | `environment`, `build`, `dependencies` |
| **Trigger Mode** | `any` |

**Trigger Conditions** (any match):
1. `failure_type == "environment"` - Test failure categorized as environment issue
2. `error_category contains "import"` - Import-related errors detected
3. `error_category contains "module"` - Module loading errors detected

**Objective Template**:
```
Diagnose environment issue: {{error_signature}}. Check dependencies, configs, and paths.
```

**Return Behavior**: `resume` - Returns to the interrupted point after environment fix.

**Example Use Case**:
During Flow 3 (Build), the `test-author` runs the test suite but encounters `ModuleNotFoundError`. The Navigator detects the import error category and suggests the env-doctor sidequest. The fixer station investigates missing dependencies, updates `pyproject.toml` or `requirements.txt`, and returns control to the test-author to re-run tests.

---

### test-triage

**Purpose**: Analyze failing tests to determine root cause and fix strategy.

| Attribute | Value |
|-----------|-------|
| **ID** | `test-triage` |
| **Primary Station** | `test-critic` |
| **Priority** | 60 |
| **Cost Hint** | medium |
| **Max Uses Per Run** | 3 |
| **Tags** | `testing`, `triage` |
| **Trigger Mode** | `all` (both conditions required) |

**Trigger Conditions** (all must match):
1. `verification_passed == false` - Tests are failing
2. `same_failure_signature == true` - The same failure is recurring across iterations

**Objective Template**:
```
Triage test failures: {{failure_summary}}. Identify root cause and recommend fixes.
```

**Return Behavior**: `resume` - Returns to the interrupted point with triage analysis.

**Example Use Case**:
During the test microloop in Flow 3, the `test-author` produces tests that fail verification. After three iterations with the same assertion error, the Navigator detects both conditions (verification failed AND same signature) and suggests test-triage. The test-critic performs deep analysis of why tests fail, categorizes the root cause (flaky test, missing setup, wrong assertion), and provides targeted recommendations before returning control.

---

### security-audit

**Purpose**: Review security implications of changes touching sensitive paths.

| Attribute | Value |
|-----------|-------|
| **ID** | `security-audit` |
| **Primary Station** | `security-scanner` |
| **Priority** | 90 (highest) |
| **Cost Hint** | high |
| **Max Uses Per Run** | 1 |
| **Tags** | `security`, `audit` |
| **Trigger Mode** | `any` |

**Trigger Conditions** (any path match):
1. `auth/**` - Authentication code paths
2. `security/**` - Security module paths
3. `**/credentials*` - Credential file patterns
4. `**/secret*` - Secret file patterns

**Objective Template**:
```
Audit security of changes to: {{sensitive_paths}}. Check for vulnerabilities.
```

**Return Behavior**: `resume` - Returns to the interrupted point with security findings.

**Example Use Case**:
During Flow 3 (Build), the `code-implementer` modifies `src/auth/jwt_handler.py`. The Navigator detects the `auth/**` path pattern and suggests the security-audit sidequest (priority 90, highest). The security-scanner performs OWASP checks, secret scanning, and auth/authz review, then returns control with findings that must be addressed. Note: This sidequest has `max_uses_per_run: 1` to prevent audit fatigue while ensuring critical paths get reviewed once.

---

### contract-check

**Purpose**: Verify API/interface contracts when schema or interface changes detected.

| Attribute | Value |
|-----------|-------|
| **ID** | `contract-check` |
| **Primary Station** | `contract-enforcer` |
| **Priority** | 75 |
| **Cost Hint** | medium |
| **Max Uses Per Run** | 3 |
| **Tags** | `contracts`, `api`, `schema` |
| **Trigger Mode** | `any` |

**Trigger Conditions** (any path match):
1. `**/api/**` - API definition paths
2. `**/schema*` - Schema file patterns
3. `**/interface*` - Interface definition patterns
4. `**/*.proto` - Protocol buffer files
5. `**/openapi*` - OpenAPI specification files

**Objective Template**:
```
Verify contracts for: {{changed_interfaces}}. Check backwards compatibility.
```

**Return Behavior**: `resume` - Returns to the interrupted point with contract validation.

**Example Use Case**:
During Flow 3 (Build), the `code-implementer` adds a new field to `api/v2/users.proto`. The Navigator detects the `.proto` file pattern and suggests contract-check. The contract-enforcer verifies backwards compatibility, checks for breaking changes, validates wire format consistency, and returns control with compliance status.

---

### context-refresh

**Purpose**: Reload context when stalled due to missing information.

| Attribute | Value |
|-----------|-------|
| **ID** | `context-refresh` |
| **Primary Station** | `context-loader` |
| **Priority** | 55 |
| **Cost Hint** | low |
| **Max Uses Per Run** | 3 |
| **Tags** | `context`, `refresh` |
| **Trigger Mode** | `any` |

**Trigger Conditions** (any match):
1. `stall_count >= 3` - Progress stalled three or more times
2. `context_insufficient == true` - Agent explicitly flagged insufficient context

**Objective Template**:
```
Refresh context for: {{current_task}}. Load additional files: {{suggested_paths}}.
```

**Return Behavior**: `resume` - Returns to the interrupted point with expanded context.

**Example Use Case**:
During Flow 3 (Build), the `code-implementer` stalls repeatedly because it lacks understanding of the existing architecture. After three stalls, the Navigator suggests context-refresh. The context-loader station performs comprehensive context loading (20-50k tokens), gathering related code, tests, ADRs, and historical changes. The implementer resumes with a richer context manifest.

---

## Station Configurations

The stations used by sidequests are defined in `swarm/packs/stations/sidequests.yaml`. These configurations include:

- **SDK settings**: Model tier, permission mode, allowed/denied tools, max turns
- **Context budgets**: Total chars, recent chars, older chars allocations
- **Identity**: System prompt with role-specific guidance
- **IO contracts**: Required/optional inputs and outputs
- **Handoff schema**: Required fields for status transitions
- **Invariants**: Rules the station must never violate
- **Routing hints**: What to do on VERIFIED/UNVERIFIED/BLOCKED

### Station Summary

| Station ID | Name | Category | Agent Key | Model | Max Turns |
|------------|------|----------|-----------|-------|-----------|
| clarifier | Clarifier | shaping | `clarifier` | sonnet | 8 |
| research | Deep Research | shaping | `context-loader` | sonnet | 15 |
| risk-assessment | Risk Assessment | analytics | `risk-analyst` | sonnet | 10 |
| policy-check | Policy Check | analytics | `policy-analyst` | sonnet | 8 |
| security-review | Security Review | verification | `security-scanner` | sonnet | 10 |
| impact-analysis | Impact Analysis | analytics | `impact-analyzer` | sonnet | 12 |

---

## Adding New Sidequests

### Step 1: Define the Sidequest in Catalog

Add to `DEFAULT_SIDEQUESTS` in `swarm/runtime/sidequest_catalog.py`:

```python
{
    "sidequest_id": "my-sidequest",
    "name": "My Sidequest",
    "description": "What this sidequest does and when to use it",
    "station_id": "target-station",  # Must exist in station configs
    "objective_template": "Action: {{placeholder}}. Context: {{another}}.",
    "triggers": [
        {
            "condition_type": "field_check",  # or: stall, path_pattern, iteration_count
            "field": "field_name",
            "operator": "equals",  # equals, not_equals, gt, lt, gte, lte, contains
            "value": True,
        },
        {
            "condition_type": "path_pattern",
            "pattern": "src/sensitive/**",
        },
    ],
    "trigger_mode": "any",  # or "all"
    "priority": 50,  # Higher = more likely selected (0-100)
    "cost_hint": "low",  # low, medium, high
    "max_uses_per_run": 3,  # Prevent infinite loops
    "tags": ["category1", "category2"],
}
```

### Step 2: Define the Station (if new)

Add to `swarm/packs/stations/sidequests.yaml`:

```yaml
- station_id: target-station
  name: Target Station Name
  description: |
    What this station does when invoked as a sidequest.
  category: shaping  # or: analytics, verification, implementation
  version: 1

  sdk:
    model: sonnet
    permission_mode: bypassPermissions
    allowed_tools:
      - Read
      - Grep
      - Glob
    denied_tools:
      - Write
      - Edit
      - Bash
    max_turns: 10
    context_budget:
      total_chars: 150000
      recent_chars: 60000
      older_chars: 20000

  identity:
    system_append: |
      You are the **Station Name**.

      Your role is to...

      ## Approach
      1. First step
      2. Second step

      ## Output Format
      - Field 1: Description
      - Field 2: Description
    tone: analytical

  io:
    required_inputs: []
    optional_inputs:
      - signal/requirements.md
    required_outputs:
      - sidequest/output_artifact.md
    optional_outputs: []

  handoff:
    path_template: "{{run.base}}/handoff/{{step.id}}.draft.json"
    required_fields:
      - status
      - summary
      - artifacts
      - can_further_iteration_help

  routing_hints:
    on_verified: return
    on_unverified: return
    on_partial: return
    on_blocked: return

  agent_key: agent-name
  tags:
    - sidequest
    - category
```

### Step 3: Update This Registry

Add your sidequest to the tables and details sections in this file.

### Step 4: Test the Sidequest

```python
from swarm.runtime.sidequest_catalog import load_default_catalog

catalog = load_default_catalog()

# Test trigger evaluation
context = {
    "field_name": True,
    "changed_paths": ["src/sensitive/config.py"],
}
applicable = catalog.get_applicable_sidequests(context)
print([sq.sidequest_id for sq in applicable])
```

---

## Trigger Condition Types

| Type | Description | Fields | Example |
|------|-------------|--------|---------|
| `field_check` | Check a context field value | `field`, `operator`, `value` | `verification_passed == false` |
| `stall` | Detect progress stalls | `field`, `operator`, `value` | `stall_count >= 2` |
| `path_pattern` | Match changed file paths | `pattern` (glob) | `auth/**` matches `auth/login.py` |
| `iteration_count` | Microloop iteration threshold | `value`, `operator` | `iteration >= 5` |

### Operators

| Operator | Description | Example |
|----------|-------------|---------|
| `equals` | Exact match | `failure_type == "environment"` |
| `not_equals` | Not equal | `status != "verified"` |
| `gt` | Greater than | `stall_count > 2` |
| `lt` | Less than | `iteration < 10` |
| `gte` | Greater than or equal | `stall_count >= 3` |
| `lte` | Less than or equal | `attempts <= 5` |
| `contains` | Substring match | `error_category contains "import"` |

---

## Multi-Step Sidequests (v2)

Sidequests can be multi-step mini-flows for complex investigations:

```python
{
    "sidequest_id": "deep-investigation",
    "name": "Deep Investigation",
    "description": "Multi-step investigation for complex issues",
    "steps": [
        {
            "template_id": "context-loader",
            "step_id": "load-context",
            "on_verified": "next",
            "on_blocked": "halt",
        },
        {
            "template_id": "risk-analyst",
            "step_id": "assess-risks",
            "inputs_from": ["previous"],
            "on_verified": "next",
        },
        {
            "template_id": "fixer",
            "step_id": "apply-fixes",
            "inputs_from": ["previous", "origin"],
            "on_verified": "resume",
        },
    ],
    "triggers": [...],
    "allow_nested_sidequests": False,  # Prevent infinite nesting
}
```

Multi-step sidequests execute sequentially, with each step able to reference artifacts from previous steps (`inputs_from: ["previous"]`) or the original interruption point (`inputs_from: ["origin"]`).

---

## Summary

<!-- META:SIDEQUEST_COUNTS -->
**Total: 6 built-in sidequests**
<!-- /META:SIDEQUEST_COUNTS -->

| Category | Count | Purpose |
|----------|-------|---------|
| Clarification | 1 | Resolve ambiguity (`clarifier`) |
| Environment | 1 | Fix build/dependency issues (`env-doctor`) |
| Testing | 1 | Triage failing tests (`test-triage`) |
| Security | 1 | Audit sensitive changes (`security-audit`) |
| Contracts | 1 | Validate API compatibility (`contract-check`) |
| Context | 1 | Reload missing information (`context-refresh`) |

### Key Principles

1. **Sidequests are suggestions**: The system proposes based on triggers; orchestrator decides
2. **Triggers are deterministic**: No LLM involved in trigger evaluation
3. **Always return**: Sidequests complete and return control to the interrupted flow
4. **Bounded catalog**: Fixed menu prevents unbounded exploration
5. **Usage limits**: `max_uses_per_run` prevents infinite sidequest loops
6. **Priority ordering**: Higher priority sidequests are presented first when multiple match
