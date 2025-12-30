# Selftest System Architecture and Design

> For: Platform engineers understanding the governance architecture.

This document explains the selftest system: its architecture, design goals, the 16 steps, governance model, and how it integrates with the seven Swarm flows.

> **First time?**
> Try Lane B of [docs/GETTING_STARTED.md](./GETTING_STARTED.md) (10 min) to see selftest in action:
> ```bash
> uv run swarm/tools/selftest.py --plan     # See the plan
> make selftest                               # Run it
> make flow-studio                            # View status
> ```
> Then come back here for the deep details.

**Quick links:**
- **Governance reference**: `docs/SELFTEST_GOVERNANCE.md` — Quick fixes, escalation tree, remediation
- **Validation rules**: [docs/VALIDATION_RULES.md](./VALIDATION_RULES.md) — FR-001–FR-005 reference for `validate_swarm.py`
- **Specifications**: `specs/spec_ledger.yaml` — Formal acceptance criteria
- **BDD scenarios**: `features/selftest.feature` — Executable test scenarios
- **Diagnostic tool**: `.claude/skills/heal_selftest/SKILL.md` — How to diagnose failures

---

## Design Goals

The selftest system is designed to:

1. **Fail fast, fail clearly** — Detect violations of specs and contracts immediately, with actionable error messages
2. **Be decomposable** — Teams should be able to work around governance failures temporarily (`--degraded` mode) while fixing the underlying issue
3. **Be introspectable** — `--plan` mode shows all steps, their tiers, and dependencies in < 0.2 seconds
4. **Be scalable** — Should run in ~2 seconds regardless of repo size (baseline, KERNEL + GOVERNANCE)
5. **Close the loop** — Integration with Flows 3-4 ensures that merges are only approved if selftest passes
6. **Support human decision-making** — Explicit tiers (KERNEL, GOVERNANCE, OPTIONAL) and hints help humans decide whether to proceed or escalate

---

## How We Use Gherkin: BDD Scenarios as Spec, Pytest as Executor

The selftest system uses **Gherkin feature files as specification, not as executable tests**. This is an intentional architectural choice:

### Design: Gherkin as Spec

**File**: `features/selftest.feature`

This file is the **canonical source of truth** for selftest acceptance criteria. It:

- Documents all `@AC-*` tags (e.g., `@AC-SELFTEST-KERNEL-FAST`, `@AC-SELFTEST-DEGRADED`)
- Describes expected behavior in human-readable scenarios
- Links each AC to Gherkin "Given/When/Then" language
- Serves as living documentation (updated when ACs change)

**Example scenario** from the file:

```gherkin
@AC-SELFTEST-KERNEL-FAST @executable
Scenario: Kernel smoke check is fast and reliable
  When I run `uv run swarm/tools/kernel_smoke.py`
  Then the exit code should be 0 or 1
  And the output should contain either "HEALTHY" or "BROKEN"
```

### Implementation: Pytest as Executor

**Why not Cucumber?**

We do **not** run Gherkin through the Cucumber/Behave runtime because:

1. **Native Python tooling**: Pytest is already our test framework (it's in CI, developer workflows, etc.)
2. **Better error messages**: Pytest provides detailed diffs and stack traces; Gherkin runners often hide details
3. **Flexible assertions**: Python assertions are more powerful than Gherkin's limited step patterns
4. **Direct tool access**: Pytest can import `selftest_config`, call `validate_swarm()`, etc. directly

### Mapping: AC → Test

**Path**: Gherkin AC tag → Python test function

| Gherkin Tag | Test File(s) | How It's Tested |
|-------------|--------------|-----------------|
| `@AC-SELFTEST-KERNEL-FAST` | `tests/test_selftest_acceptance.py` | Unit test: `test_kernel_smoke_check_is_fast()` |
| `@AC-SELFTEST-INTROSPECTABLE` | `tests/test_selftest_api_contract.py` | Contract test: `test_selftest_plan_api_contract_*()` |
| `@AC-SELFTEST-INDIVIDUAL-STEPS` | `tests/test_selftest_acceptance.py` | Integration test: `test_run_individual_step_*()` |
| `@AC-SELFTEST-DEGRADED` | `tests/test_selftest_acceptance.py` | Integration test: `test_degraded_mode_*()` |
| `@AC-SELFTEST-FAILURE-HINTS` | `tests/test_selftest_acceptance.py` | Integration test: `test_failure_hints_*()` |
| `@AC-SELFTEST-DEGRADATION-TRACKED` | `tests/test_selftest_degradation_log.py` | Integration test: `test_log_*()` |

### What to Do If You See "Undefined Step" in Your Editor

If you use VS Code with the **Cucumber (Gherkin) Full Support** extension:

- **Expected behavior**: The plugin shows "Undefined step" warnings on every line of `features/selftest.feature`
- **Why**: The plugin is looking for Cucumber/Behave step definitions, which we don't have
- **It's OK**: This is by design. Ignore the warnings.
- **How to quiet it**: See `.vscode/settings.json` sample below

**Sample `.vscode/settings.json` to quiet Cucumber warnings**:

```jsonc
{
  "cucumber.features": ["features/**/*.feature"],
  "cucumber.formatters": [],
  "cucumberAutoRun": false,
  "[gherkin]": {
    "editor.defaultFormatter": "kurron.vscode-gherkin-formatter"
  }
}
```

### For Future Readers: How to Add a New AC

**Step 1: Add Gherkin scenario** in `features/selftest.feature`:

```gherkin
@AC-SELFTEST-NEW-FEATURE
Scenario: New feature is introspectable
  When I run `...`
  Then the output should contain "..."
```

**Step 2: Map AC to config** in `swarm/tools/selftest_config.py`:

```python
SelfTestStep(
    id="my-step",
    ac_ids=["AC-SELFTEST-NEW-FEATURE"],  # ← Link AC tag here
    ...
)
```

**Step 3: Write pytest test** in `tests/test_selftest_*.py`:

```python
def test_new_feature():
    """Verifies AC-SELFTEST-NEW-FEATURE."""
    # Arrange, Act, Assert
```

**Step 4: Run to verify**:

```bash
# Gherkin spec is updated ✓
# Config links AC to step ✓
# Pytest verifies it works ✓
uv run pytest tests/test_selftest_acceptance.py::test_new_feature -v
```

### See Also

- **Gherkin scenarios**: `features/selftest.feature`
- **AC-to-test mapping**: `docs/SELFTEST_AC_MATRIX.md`
- **Pytest tests**: `tests/test_selftest_*.py`
- **Config with AC IDs**: `swarm/tools/selftest_config.py` (SelfTestStep.ac_ids)

---

## Selftest in Four Commands: A Concrete Walkthrough

If you just want to **understand and use** selftest, here's the minimal path:

### Command 1: See the Plan

```bash
uv run swarm/tools/selftest.py --plan
```

**What it does**: Shows all 16 selftest steps with their tiers (KERNEL, GOVERNANCE, OPTIONAL) and dependencies, without actually running anything.

**Why**: Gives you a **read-only blueprint** of what selftest will check. Use this to understand the shape of the system before running it.

**Sample output**:
```
Selftest Plan (16 steps):

  KERNEL tier (1 step, always blocks):
    core-checks         – Python linting, compilation check

  GOVERNANCE tier (7 steps, blocks unless --degraded):
    skills-governance   – Skill .md files and YAML validity
    agents-governance   – Agent bijection and color scheme
    bdd                 – BDD feature files structure
    ac-status           – Acceptance criteria tracking
    policy-tests        – OPA policy validation
    devex-contract      – Flow/agent/skill contracts
    graph-invariants    – Flow graph connectivity

  OPTIONAL tier (2 steps, informational):
    ac-coverage         – Coverage thresholds
    extras              – Experimental checks

Dependencies:
  None; all steps can run in parallel after their tier starts.
```

### Command 2: Run a Single Step

```bash
uv run swarm/tools/selftest.py --step core-checks
```

**What it does**: Runs **only** the `core-checks` step, showing timing and detailed output.

**Why**: When selftest fails, you can debug step-by-step instead of re-running everything. Good for:
- Testing your fix for a single step
- Understanding what a step actually does
- Iterating quickly without 2-second waits

**Common steps to debug**:
```bash
uv run swarm/tools/selftest.py --step agents-governance    # Agent config
uv run swarm/tools/selftest.py --step devex-contract       # Flow/agent contracts
uv run swarm/tools/selftest.py --step policy-tests         # OPA policies
```

### Command 3: Run Full Selftest

```bash
uv run swarm/tools/selftest.py
```

**What it does**: Runs all 16 steps in dependency order, reports pass/fail for each.

**Exit codes**:
- `0` – All KERNEL + GOVERNANCE + OPTIONAL passed ✓
- `1` – Any KERNEL step failed, OR GOVERNANCE failed in strict mode

**When to use**: Before committing, as part of CI, or to validate the whole system.

### Command 4: Work Around Governance Failures (Degraded Mode)

```bash
uv run swarm/tools/selftest.py --degraded
```

**What it does**: Runs all steps, but only **blocks on KERNEL failures**. GOVERNANCE and OPTIONAL failures are logged but don't affect the exit code.

**Why**: Lets you merge work-in-progress or temporary fixes while the governance team fixes the underlying issue (e.g., a stray Gherkin comment, a documentation gap).

**Exit codes**:
- `0` – KERNEL passed; GOVERNANCE/OPTIONAL may have issues (logged to `selftest_degradations.log`)
- `1` – KERNEL failed (always blocks)

**Caution**: `--degraded` is **not** a long-term mode; use it to unblock while fixing the root cause.

---

## The 16 Selftest Steps

### Tier: KERNEL (1 step)

**Purpose**: Verify the repository isn't fundamentally broken. KERNEL failures are **always blocking**.

#### Step 1: `core-checks` (~0.1s)

**What it checks** (Flow Studio):
- `ruff check swarm/tools` — Python linting (unused imports, f-string issues, etc.)
- `python -m compileall swarm/tools` — Python modules compile successfully

**Why it matters**:
- Python tooling must be syntactically correct and follow style guidelines
- This is the foundational gate for all downstream work

**When it fails**:
```bash
FAIL core-checks:
  F401 Unused import 'os' in swarm/tools/gen_flows.py:21
  F541 f-string without placeholders in swarm/tools/validate_swarm.py:661
```

**How to fix**:
```bash
uv run ruff check swarm/tools --fix  # Auto-fix most issues
# Then review any remaining issues manually
git add . && git commit -m "fix: resolve core-checks"
```

**Note**: In other repos (e.g., template-repo with Rust), `core-checks` will validate Rust code (cargo fmt, clippy, tests) instead. The principle is the same: verify the repo's core code is syntactically correct and passes basic quality gates.

**Dependency**: None (root step)

---

### Tier: GOVERNANCE (12 steps)

**Purpose**: Verify that the Swarm's contracts are met (agents configured correctly, flows valid, specs aligned). GOVERNANCE failures block merges unless `--degraded` mode is used.

#### Step 2: `skills-governance` (~0.05s)

**What it checks**:
- All `.claude/skills/*/SKILL.md` files exist
- YAML frontmatter is valid (required fields: name, description, allowed-tools, category, tier)
- Skill names match directory names (case-sensitive)
- No symlinks (symlinks are skipped for security)

**Why it matters**:
- Skills are tools available to agents; invalid skills cause agents to fail

**When it fails**:
```bash
FAIL skills-governance:
  Skill 'heal_selftest' registered in swarm/skills.md but
  .claude/skills/heal-selftest/SKILL.md (name mismatch: heal_selftest vs heal-selftest)
```

**How to fix**:
```bash
# Rename directory or file to match
mv .claude/skills/heal-selftest .claude/skills/heal_selftest

# Or update swarm/skills.md to match actual directory
make gen-adapters  # Regenerate if config-backed
```

**Dependency**: None

---

#### Step 3: `agents-governance` (~0.1s)

**What it checks**:
- All agents registered in `swarm/AGENTS.md` have corresponding `.claude/agents/<key>.md` files
- Agent frontmatter is valid (required: name, description, color, model)
- Agent names match filenames and registry keys (case-sensitive)
- Color matches role family (e.g., `critic` → `red`, `spec` → `purple`)
- No symlinks

**Why it matters**:
- Agents are the workers in the Swarm; misconfigured agents break flows

**When it fails**:
```bash
FAIL agents-governance:
  Agent 'test-critic' in swarm/AGENTS.md has no .claude/agents/test-critic.md file
  OR
  Agent 'test-critic' color is 'blue' but role family 'critic' requires 'red'
```

**How to fix**:
```bash
# Create missing agent file
touch .claude/agents/test-critic.md
# Add frontmatter with correct color

# OR fix color in existing file
# color: red  # (change from blue)

# Regenerate if config-backed
make gen-adapters
make check-adapters
```

**Dependency**: None

---

#### Step 4: `bdd-scenarios` (~0.2s)

**What it checks**:
- All `features/*.feature` files have valid Gherkin syntax
- Keywords (Scenario, Given, When, Then, etc.) are spelled correctly
- Indentation is correct
- Feature names and scenario tags are consistent

**Why it matters**:
- BDD scenarios are executable specifications that drive test code
- Syntax errors prevent scenarios from running

**When it fails**:
```bash
FAIL bdd-scenarios:
  features/selftest.feature:42: Expected 'Scenario' but got 'Sceario:'
  features/selftest.feature:50: Indentation error (expected 2 spaces, got 3)
```

**How to fix**:
```bash
# Edit feature files
$EDITOR features/selftest.feature

# Check syntax manually
grep -n "Sceario" features/selftest.feature  # Find typos
# Fix: Scenario

# Validate
make selftest --step bdd-scenarios --verbose
```

**Dependency**: None

---

#### Step 5: `ac-status` (~0.1s)

**Demo-only pattern**: This step is present in demo-swarm to show acceptance criteria tracking; it does not gate CI in this repo.

**What it checks**:
- All acceptance criteria in `specs/spec_ledger.yaml` have:
  - Unique `id` fields
  - Non-empty `text` descriptions
  - At least one test entry
  - `status` field (PENDING, IN_PROGRESS, VERIFIED, BLOCKED)
- Each AC has linked BDD scenarios (by tag) or unit/integration test references
- No duplicate AC IDs

**Why it matters**:
- Acceptance criteria are formal contracts for what the system must do
- Untracked ACs can slip through cracks

**When it fails**:
```bash
FAIL ac-status:
  AC 'AC-SELFTEST-KERNEL-FAST' in specs/spec_ledger.yaml has no linked tests
  AC 'AC-SELFTEST-KERNEL-FAST' appears twice (duplicate ID)
```

**How to fix**:
```bash
# Edit specs/spec_ledger.yaml
$EDITOR specs/spec_ledger.yaml

# Add tests array if missing:
# acceptance_criteria:
#   - id: AC-SELFTEST-KERNEL-FAST
#     text: "..."
#     tests:
#       - type: integration
#         command: "make kernel-smoke"
#     status: PENDING

# Add BDD scenario with matching @tag
# @AC-SELFTEST-KERNEL-FAST
# Scenario: ...
```

**Dependency**: None

---

#### Step 6: `policy-tests` (~0.3s)

**What it checks** (if policy tooling is configured):
- OPA/Conftest policies are valid
- Policies evaluate without errors
- Example: policies might check that all microservices have security headers, rate limits, etc.

**Why it matters**:
- Policies enforce organizational standards (security, compliance, performance)
- Policy failures can indicate misalignment with standards

**When it fails**:
```bash
FAIL policy-tests:
  OPA policy 'src/policies/auth.rego' has syntax error at line 12
  Policy evaluation failed: undefined reference to 'data.users'
```

**How to fix**:
```bash
# Check policy syntax
conftest verify src/policies/auth.rego

# Fix syntax errors
$EDITOR src/policies/auth.rego

# Re-evaluate
make selftest --step policy-tests --verbose
```

**Dependency**: None (but may be skipped if policy tooling not installed)

---

#### Step 7: `devex-contract` (~0.2s)

**What it checks**:
- All flows referenced in `swarm/flows/*.md` or `swarm/config/flows/*.yaml` are defined
- All agents referenced in flows exist in `swarm/AGENTS.md` and `.claude/agents/`
- All skills referenced in agent frontmatter exist in `.claude/skills/`
- All agents referenced exist (typo detection via Levenshtein distance)
- Flow specs use `RUN_BASE/<flow>/` paths, not hardcoded paths
- No circular dependencies between flows

**Why it matters**:
- The devex (developer experience) contract ensures that the Swarm's infrastructure is valid
- Broken references cause flows to fail at runtime

**When it fails**:
```bash
FAIL devex-contract:
  Flow 'flow-3-build' references unknown agent 'test-critic'
  Did you mean: test-critic ?
  OR
  Flow spec uses hardcoded path 'swarm/runs/my-ticket/build/'
  instead of 'RUN_BASE/build/'
```

**How to fix**:
```bash
# Fix agent typos
grep "test-critic" swarm/config/flows/build.yaml
# Change to: test-critic

# Fix hardcoded paths
sed -i 's|swarm/runs/my-ticket/|RUN_BASE/|g' swarm/flows/flow-build.md

# Regenerate flows if config-backed
make gen-flows
make check-flows
```

**Dependency**: `core-checks` (must pass first)

---

#### Step 8: `graph-invariants` (~0.15s)

**What it checks**:
- Flow graph is connected (all steps reachable from entry point)
- No orphaned steps or agents
- Step dependencies are acyclic (no loops)
- All inter-flow dependencies are valid (e.g., Flow 3 requires Flow 2 outputs)

**Why it matters**:
- A disconnected flow graph means some steps never execute
- Cycles can cause infinite loops or deadlocks

**When it fails**:
```bash
FAIL graph-invariants:
  Flow 'flow-3-build' has unreachable step 'mutate' (not reachable from entry)
  OR
  Circular dependency detected: step A depends on B, B depends on A
```

**How to fix**:
```bash
# Review flow structure
make selftest --plan

# Check dependencies
grep -E "depends_on:|entry_point:" swarm/config/flows/build.yaml

# Re-structure flow to make all steps reachable
make gen-flows
make check-flows
```

**Dependency**: `devex-contract` (must pass first)

---

#### Step 9: `flowstudio-smoke` (~0.3s)

**What it checks**:
- Flow Studio FastAPI app starts successfully
- `/api/health` returns 200 with flow and agent counts
- `/api/flows` returns all 7 flows
- `/api/graph/signal` returns nodes and edges
- `/api/runs` includes health-check example

**Why it matters**:
- Flow Studio is the visual learning interface for the swarm
- API failures mean the UI won't render correctly
- Ensures the tool surface is stable for demos and learning

**Why GOVERNANCE (not KERNEL or OPTIONAL)?**

- **Not KERNEL**: Flow Studio is a learning/visualization tool, not core infrastructure.
  Swarm flows execute successfully without it; it's purely for operator visibility.

- **Degradable**: Failures indicate config drift but don't prevent work; teams can use
  `--degraded` mode to merge fixes while addressing the config issue separately.

- **Not OPTIONAL**: Unlike `ac-coverage`, Flow Studio's health directly reflects swarm
  integrity. If `/api/health` fails, it means config parsing broke—a sign of systemic
  issues that operators need to see.

**When it fails**:
```bash
FAIL flowstudio-smoke:
  /api/health returned 500
  OR
  /api/flows returned only 6 flows (expected 7)
  OR
  health-check example not found in /api/runs
```

**How to fix**:
```bash
# Check Flow Studio can start
uv run python -m swarm.tools.flow_studio_smoke

# Verify config files exist
ls swarm/config/flows/*.yaml  # Should show 7 files
ls swarm/examples/health-check/run.json  # Should exist

# Regenerate if needed
make gen-flows
make demo-run

# Run full API contract tests
uv run pytest tests/test_flow_studio_governance.py -v
```

**Dependency**: None

---

### Tier: OPTIONAL (2 steps)

**Purpose**: Nice-to-have checks that improve code quality. OPTIONAL failures never block merges.

#### Step 10: `ac-coverage` (~0.3s)

**Demo-only pattern**: This step is present in demo-swarm to show acceptance criteria coverage tracking; it does not gate CI in this repo.

**What it checks**:
- Acceptance criteria have sufficient test coverage
- Default threshold: 80% of ACs must have at least one test
- Each AC status should progress: PENDING → IN_PROGRESS → VERIFIED

**Why it matters**:
- High AC coverage means the system's promises are testable and verifiable
- Low coverage suggests missing or untested requirements

**When it fails**:
```bash
FAIL ac-coverage:
  Only 60/100 ACs have test coverage (60% < 80% threshold)
  Missing tests for ACs:
    - AC-SELFTEST-INDIVIDUAL-STEPS
    - AC-SELFTEST-DEGRADED
```

**How to fix** (optional):
```bash
# Add BDD scenarios or test references
$EDITOR features/selftest.feature
$EDITOR specs/spec_ledger.yaml

# Or adjust threshold (with ADR justification)
# min_ac_coverage_threshold: 70  # (in selftest config)
```

**Dependency**: None

---

#### Step 11: `extras` (~0.2s)

**Demo-only pattern**: This step is present in demo-swarm as a placeholder for experimental checks; it does not gate CI in this repo.

**What it checks**:
- Experimental checks, future validations
- Examples: code complexity metrics, doc coverage, build time regression

**Why it matters**:
- Ahead-of-the-curve checks that help catch potential issues early
- Can be enabled/disabled per project

**When it fails**:
```bash
WARN extras:
  Code complexity in src/handler.rs is HIGH (cyclomatic: 15)
  Suggest: Refactor or document why complexity is necessary
```

**How to fix** (optional):
```bash
# These are warnings, not failures
# Fix if you want; otherwise, ignore
# To disable: add experimental_checks: false in config
```

**Dependency**: None

---

## Acceptance Criteria Mapping

This table traces acceptance criteria (AC IDs from `features/selftest.feature`) to the selftest steps that implement them. Use this to understand which steps validate which requirements.

| AC ID | Selftest Steps | Description |
|-------|---|---|
| AC-SELFTEST-KERNEL-FAST | core-checks | Python linting and compilation check; must execute in < 1 second for inner-loop development |
| AC-SELFTEST-INTROSPECTABLE | core-checks, (all steps) | Selftest is introspectable via `--plan` and `--json` flags; shows all 10+ steps with tiers and dependencies |
| AC-SELFTEST-INDIVIDUAL-STEPS | core-checks, skills-governance, agents-governance, bdd-scenarios, ac-status, policy-tests, devex-contract, graph-invariants, flowstudio-smoke, ac-coverage, extras | Can run individual steps via `--step <id>` and `--until <id>`; output includes timing and error details |
| AC-SELFTEST-DEGRADED | core-checks, (all GOVERNANCE/OPTIONAL steps) | Degraded mode (`--degraded` flag) allows work-around of GOVERNANCE failures while still blocking KERNEL failures |
| AC-SELFTEST-FAILURE-HINTS | core-checks, (all steps) | Failed selftest provides actionable hints; failures output references how to debug, run individual steps, or see documentation |
| AC-SELFTEST-DEGRADATION-TRACKED | core-checks, (all steps with --degraded) | Governance failures are logged to persistent `selftest_degradations.log` with timestamp, step ID, tier, and failure reason |

**How to use this table**:
- To verify AC-SELFTEST-KERNEL-FAST: Run `uv run swarm/tools/selftest.py --step core-checks` and check timing
- To verify AC-SELFTEST-INTROSPECTABLE: Run `uv run swarm/tools/selftest.py --plan` and `--json`
- To verify AC-SELFTEST-DEGRADATION-TRACKED: Run `uv run swarm/tools/selftest.py --degraded` and inspect `selftest_degradations.log`

---

## Governance Tiers: Why Three?

| Tier | Blocking? | Degradable? | Reason |
|------|-----------|------------|--------|
| **KERNEL** | Always | Never | Fundamentals; if broken, repo is unusable |
| **GOVERNANCE** | Yes (unless `--degraded`) | Yes | Swarm contracts; important but can be deferred |
| **OPTIONAL** | Never | Always | Nice-to-have; humans choose to fix or ignore |

**Example scenario**:
- Your team is migrating agents from one naming scheme to another
- This breaks `agents-governance` (GOVERNANCE tier)
- You can use `--degraded` mode to ship code now and fix the migration tomorrow
- KERNEL must still pass (you can't ship broken code)

---

## Degradation Log Format (AC-6: Degradation Logging Closure)

When running selftest in `--degraded` mode, non-blocking (GOVERNANCE/OPTIONAL) failures are logged to a persistent JSONL file: `selftest_degradations.log`.

### Schema

Each line in `selftest_degradations.log` is a JSON object with the following **required fields**:

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| `timestamp` | String (ISO 8601) | Time of failure, UTC | `2025-12-01T10:15:22+00:00` |
| `step_id` | String | Unique step identifier | `agents-governance` |
| `step_name` | String | Human-readable step description | `Agent definitions linting and formatting` |
| `tier` | String | Selftest tier | `governance`, `optional`, or `kernel` |
| `message` | String | Failure output (stderr or stdout) | `Agent 'foo-bar' not found in registry` |
| `severity` | String | Severity level | `critical`, `warning`, or `info` |
| `remediation` | String | Suggested fix command | `Run: uv run swarm/tools/selftest.py --step agents-governance` |

### Example Entry

```json
{
  "timestamp": "2025-12-01T10:15:22+00:00",
  "step_id": "agents-governance",
  "step_name": "Agent definitions linting and formatting",
  "tier": "governance",
  "message": "Agent 'foo-bar' not found in registry. Run: uv run swarm/tools/validate_swarm.py for details.",
  "severity": "warning",
  "remediation": "Run: uv run swarm/tools/selftest.py --step agents-governance"
}
```

### Usage

**View degradations (human-readable)**:
```bash
uv run swarm/tools/show_selftest_degradations.py
```

**View degradations (JSON)**:
```bash
uv run swarm/tools/show_selftest_degradations.py --json
```

**View degradations (JSON v2 with metadata)**:
```bash
uv run swarm/tools/show_selftest_degradations.py --json-v2
```

### Key Properties

- **Persistent**: Log appends across runs; doesn't overwrite
- **Immutable entries**: Each entry is timestamped and immutable (audit trail)
- **Chronologically ordered**: Entries ordered by timestamp for tracking history
- **Machine-readable**: Valid JSONL format, parseable by any JSON tool
- **Human-friendly**: CLI tool formats for easy reading
- **Actionable**: Each entry includes remediation hint

### Severity Mapping

- **KERNEL tier** failures → `critical` severity (always logged separately, always blocks)
- **GOVERNANCE tier** failures → `warning` severity (logged in degraded mode)
- **OPTIONAL tier** failures → `info` severity (logged in degraded mode)

### Tests

AC-6 acceptance tests in `tests/test_selftest_degradation_log.py`:
- `TestDegradationLogJSONLFormat`: Schema validation and field types
- `TestDegradationLogPersistence`: Log append behavior, chronological ordering
- `TestDegradationLogSeverityMapping`: Tier → severity mapping
- `TestShowSelftestDegradationsCLI`: CLI tool output formats

Run with:
```bash
uv run pytest tests/test_selftest_degradation_log.py -v
```

---

## How Selftest Integrates with Swarm Flows

### Flow 1: Signal → Spec
- Selftest is NOT run in Flow 1
- Flow 1 produces requirements and BDD scenarios
- These flow into the `bdd-scenarios` step (added to `features/`)

### Flow 2: Spec → Design
- Selftest is NOT run in Flow 2
- Flow 2 produces ADR, contracts, observability specs
- These are informational for Flow 3

### Flow 3: Design → Code (BUILD)
- **Selftest RUN**: `make selftest --strict` (all failures block)
- Runs at the END of code implementation
- Part of the build receipt (`RUN_BASE/build/build_receipt.json`)
- If selftest fails, build is UNVERIFIED

### Flow 4: Code → Gate (GATE)
- **Selftest RE-RUN**: `make selftest --strict` to verify Flow 3's claim
- Used by `receipt-checker` to validate build receipt
- Used by `contract-enforcer` to verify swarm contracts
- If selftest fails, merge decision is BOUNCE (back to Flow 3)

### Flow 5: Artifact → Prod (DEPLOY)
- **Selftest STATE**: Checked but not re-run (was already verified in Flow 4)
- Included in deployment metadata
- Used to assess risk (degraded deployments are higher risk)

### Flow 6: Prod → Wisdom (ANALYSIS)
- **Selftest HISTORY**: Previous selftest states are analyzed
- Regressions detected (e.g., "selftest was green last week, now red")
- Used to identify systemic issues (e.g., "governance checks keep failing")
- Feedback loops: "Fix agents-governance once and for all" → Flow 3 task

---

## Selftest State Representation

Selftest state can be stored in multiple places:

### Build Receipt (Flow 3)
```json
{
  "flow": "build",
  "timestamp": "2025-11-30T10:15:22Z",
  "selftest": {
    "status": "VERIFIED",
    "mode": "strict",
    "kernel_passed": true,
    "governance_passed": true,
    "governance_failures": [],
    "optional_failures": [],
    "elapsed_ms": 2100
  }
}
```

### /platform/status Endpoint (if implemented)
```json
{
  "status": "HEALTHY",
  "state": "OK",  // or "DEGRADED" or "BROKEN"
  "selftest": {
    "kernel": "PASS",
    "governance": "PASS",
    "optional": "1 warning (ac-coverage)"
  },
  "hints": [
    "All checks passed",
    "Last run: 2 minutes ago"
  ]
}
```

### Degradation Log (persistent)
```jsonl
{"timestamp": "2025-11-30T10:15:22Z", "step_id": "agents-governance", "tier": "GOVERNANCE", "message": "Agent 'foo' not registered", "severity": "P1", "remediation": "Run: make gen-adapters"}
{"timestamp": "2025-11-30T10:20:15Z", "step_id": "devex-contract", "tier": "GOVERNANCE", "message": "Hardcoded path found in flow-build.md", "severity": "P2", "remediation": "Replace with RUN_BASE placeholder"}
```

---

## Known Limitations

1. **YAML tilde issue**: Custom YAML parser may crash on bare `~` in descriptions. Workaround: use `""` or explicit text.
2. **Symlinks skipped**: Symlinked agent/skill files are not validated (security measure). Use real files.
3. **Policy tests optional**: If OPA/Conftest is not installed, policy-tests step is skipped (not an error).
4. **No soft-reset**: Selftest state doesn't auto-reset between runs. `selftest_degradations.log` is persistent (by design, for tracking).

---

## Extending Selftest

To add a new selftest step:

1. **Define the step** in a new YAML config or Python module
2. **Implement the checker** (a Python function that returns PASS/FAIL)
3. **Add to selftest runner** (`swarm/tools/selftest.py`)
4. **Document** in SELFTEST_GOVERNANCE.md
5. **Add ACs and tests** to specs/spec_ledger.yaml and features/selftest.feature
6. **Validate** with `make selftest --plan` and `make selftest`

Example:
```python
# swarm/tools/selftest_steps/my_new_step.py

def run_my_new_step(config: dict) -> StepResult:
    """Check that custom policy is valid."""
    try:
        # Run check
        result = validate_my_policy()
        if result.ok:
            return StepResult(
                step_id="my-step",
                status="PASS",
                tier="GOVERNANCE",
                elapsed_ms=result.elapsed
            )
        else:
            return StepResult(
                step_id="my-step",
                status="FAIL",
                tier="GOVERNANCE",
                error_message=result.error,
                hints=["Run: fix-my-policy", "See docs/MY_POLICY.md"]
            )
    except Exception as e:
        return StepResult(
            step_id="my-step",
            status="FAIL",
            tier="GOVERNANCE",
            error_message=str(e),
            escalate=True
        )
```

---

## AC (Acceptance Criteria) Traceability

The selftest system implements **end-to-end AC traceability**: every acceptance criterion flows from config → plan → status → UI.

### AC Traceability Chain

**Path**: Config → Plan API → Status API → Flow Studio UI

```
┌────────────────────────────────────────────────────────────┐
│ 1. Config Layer: swarm/tools/selftest_config.py            │
│    SelfTestStep.ac_ids: List[str]                          │
│    e.g., ac_ids=["AC-SELFTEST-KERNEL-FAST"]               │
└──────────────────┬─────────────────────────────────────────┘
                   │
                   ▼
┌────────────────────────────────────────────────────────────┐
│ 2. Plan API: GET /api/selftest/plan                        │
│    Returns: {steps: [{id, tier, ac_ids, ...}, ...]}        │
│    Contract: Every step includes ac_ids field (list)       │
└──────────────────┬─────────────────────────────────────────┘
                   │
                   ▼
┌────────────────────────────────────────────────────────────┐
│ 3. Status API: GET /platform/status                        │
│    Returns: {governance: {ac: {AC-ID: status, ...}, ...}} │
│    Contract: governance.ac maps AC ID → worst status       │
└──────────────────┬─────────────────────────────────────────┘
                   │
                   ▼
┌────────────────────────────────────────────────────────────┐
│ 4. UI Layer: Flow Studio (http://localhost:5000)           │
│    Displays: AC IDs as badges in selftest step modal       │
│    Hover: Shows AC description and status                  │
└────────────────────────────────────────────────────────────┘
```

### AC to Step Mapping

| AC ID | Step(s) | Tier | Severity | Description |
|-------|---------|------|----------|-------------|
| AC-SELFTEST-KERNEL-FAST | core-checks | KERNEL | CRITICAL | Python tooling (ruff, compile) must pass; fast baseline check |
| AC-SELFTEST-INTROSPECTABLE | skills-governance, agents-governance, bdd, ac-status, policy-tests, devex-contract, graph-invariants, flowstudio-smoke | GOVERNANCE | WARNING | All governance steps are introspectable via `--plan`; clear contract |
| AC-SELFTEST-INDIVIDUAL-STEPS | ac-coverage | OPTIONAL | INFO | Each step is independently runnable and debuggable |
| AC-SELFTEST-DEGRADED | extras | OPTIONAL | INFO | System supports `--degraded` mode for working around governance failures |

### How AC Status is Aggregated

When multiple steps claim the same AC, the **worst status wins**:

```
Status Precedence (worst → best):
  CRITICAL > FAILURE > WARNING > INFO > PASS

Example:
  AC-SELFTEST-INTROSPECTABLE covers 6 steps:
    - Step A: PASS
    - Step B: PASS
    - Step C: FAIL (governance_failed)  ← WARNING severity
    - Step D: PASS
    - Step E: PASS
    - Step F: PASS

  Aggregated AC status: WARNING (worst of all 6)
```

### From AC to UI: Full Traceability Example

**Scenario**: User sees AC-SELFTEST-KERNEL-FAST in Flow Studio modal.

**Trace back**:

1. **UI Layer**: Click selftest step modal → see badge "AC-SELFTEST-KERNEL-FAST"
2. **Status API**: `GET /platform/status` → `governance.ac["AC-SELFTEST-KERNEL-FAST"] = "PASS"`
3. **Plan API**: `GET /api/selftest/plan` → step `{id: "core-checks", ac_ids: ["AC-SELFTEST-KERNEL-FAST"]}`
4. **Config Layer**: `swarm/tools/selftest_config.py` → `SelfTestStep(id="core-checks", ac_ids=["AC-SELFTEST-KERNEL-FAST"])`

**Benefits**:

- **Auditable**: Every AC decision is traceable to a step, tier, and severity
- **Debuggable**: If AC status is RED, know exactly which step(s) failed
- **Intentional**: ACs are declared upfront; no surprise requirements emerge mid-testing

### Testing AC Traceability

Run the AC traceability test suite:

```bash
# Test full chain: config → plan → status → UI
uv run pytest tests/test_selftest_ac_traceability.py -v

# Individual tests:
uv run pytest tests/test_selftest_ac_traceability.py::TestACTraceabilityChain::test_plan_includes_ac_ids
uv run pytest tests/test_selftest_ac_traceability.py::TestACTraceabilityChain::test_status_ac_aggregation
uv run pytest tests/test_selftest_ac_traceability.py::TestACTraceabilityChain::test_ac_references_valid_steps
```

**Test Coverage**:

- `test_plan_includes_ac_ids()` — `/api/selftest/plan` has ac_ids for every step
- `test_status_ac_aggregation()` — `/platform/status` includes governance.ac
- `test_ac_references_valid_steps()` — All ACs in status reference valid plan steps
- `test_ac_status_worst_status_wins()` — AC aggregation logic selects worst status
- `test_ac_config_consistency()` — Config has non-empty, valid AC IDs
- `test_full_chain_end_to_end()` — Complete flow from config to UI

---

## AC-6: Degradation Log Persistence (AC-SELFTEST-DEGRADATION-TRACKED)

**Goal**: Track governance and optional failures persistently when running in `--degraded` mode, enabling operators to see what went wrong even when work is allowed to proceed.

### When Degradation Log is Written

The selftest system writes entries to `selftest_degradations.log` when **all** of these are true:

1. Running with `--degraded` flag (e.g., `uv run swarm/tools/selftest.py --degraded`)
2. A **non-KERNEL** step fails (GOVERNANCE or OPTIONAL tier)
3. The step's `allow_fail_in_degraded: True` (most GOVERNANCE/OPTIONAL steps have this)

**KERNEL failures are NOT logged** — they still block the workflow even in degraded mode.

### Degradation Log Schema (Frozen at v1.0)

Each line in `selftest_degradations.log` is a JSON object with these required fields:

```json
{
  "timestamp": "2025-12-01T10:15:22+00:00",
  "step_id": "agents-governance",
  "step_name": "Agent definitions linting and formatting",
  "tier": "governance",
  "message": "Agent 'foo-bar' not found in registry",
  "severity": "warning",
  "remediation": "Run: make selftest --step agents-governance for details"
}
```

| Field | Type | Example | Notes |
|-------|------|---------|-------|
| `timestamp` | string (ISO 8601) | `2025-12-01T10:15:22+00:00` | UTC timezone; frozen at write time |
| `step_id` | string | `agents-governance` | Must match a SelfTestStep.id from config |
| `step_name` | string | `Agent definitions linting…` | Human-readable description (from SelfTestStep.description) |
| `tier` | string | `"governance"` \| `"optional"` | Never `"kernel"` (kernel failures always block) |
| `message` | string | `Agent 'foo-bar' not found…` | Last line of stderr or stdout; max 500 chars recommended |
| `severity` | string | `"critical"` \| `"warning"` \| `"info"` | From SelfTestStep.severity |
| `remediation` | string | `Run: make selftest --step…` | Actionable command to investigate/fix |

**Schema Validation**:

```python
# From swarm/tools/selftest.py (frozen constant)
DEGRADATION_LOG_SCHEMA = {
    "version": "1.0",
    "required_fields": [
        "timestamp", "step_id", "step_name", "tier",
        "message", "severity", "remediation"
    ],
    "example": { /* ... */ }
}
```

### Viewing Degradations

**Human-readable format**:

```bash
uv run swarm/tools/show_selftest_degradations.py
```

Output:

```
======================================================================
SELFTEST DEGRADATIONS
======================================================================

[2025-12-01 10:15:22 UTC] GOVERNANCE/agents-governance
  Severity: WARNING
  Step:     Agent definitions linting and formatting
  Message:  Agent 'foo-bar' not found in registry
  Fix:      Run: make selftest --step agents-governance for details

[2025-12-01 10:16:05 UTC] OPTIONAL/ac-coverage
  Severity: INFO
  Step:     Acceptance criteria coverage thresholds
  Message:  Coverage: 95% (target: 98%)
  Fix:      Run: make selftest --step ac-coverage for details

======================================================================
Total degradations: 2
```

**Machine-readable format**:

```bash
# JSON array (JSONL parsed)
uv run swarm/tools/show_selftest_degradations.py --json | jq .

# JSON v2 with metadata
uv run swarm/tools/show_selftest_degradations.py --json-v2 | jq .metadata
```

### Degradation Log Lifecycle

**Creation**:
- Created when first degradation is logged in degraded mode
- If file doesn't exist, it's created with write permissions for the runner

**Append behavior**:
- Multiple runs **append** to the same log (never overwrite)
- Entries are chronologically ordered (timestamps are ISO 8601 sortable)
- No deduplication; same failure in multiple runs creates multiple entries

**Cleanup**:
- Log persists across runs (intentional; historical record)
- Manual cleanup: `rm selftest_degradations.log`
- Recommended: Commit log to git to track degradations over time

### Degradations in APIs

#### GET /platform/status — governance.degradations

```json
{
  "state": "DEGRADED",
  "governance": {
    "status": "FAIL",
    "degradations": [
      {
        "timestamp": "2025-12-01T10:15:22+00:00",
        "step_id": "agents-governance",
        "message": "Agent 'foo-bar' not found…",
        "remediation": "Run: make selftest --step agents-governance for details"
      },
      {
        "timestamp": "2025-12-01T10:16:05+00:00",
        "step_id": "ac-coverage",
        "message": "Coverage: 95% (target: 98%)",
        "remediation": "Run: make selftest --step ac-coverage for details"
      }
    ]
  }
}
```

#### GET /api/selftest/plan — version and ac_ids

Every step in the plan includes `ac_ids` (list of AC IDs it covers). Combined with degradation log, you can trace which ACs are failing:

```bash
# Plan for ac-coverage step
uv run swarm/tools/selftest.py --plan --json | jq '.steps[] | select(.id == "ac-coverage")'

# Output:
# {
#   "id": "ac-coverage",
#   "ac_ids": ["AC-SELFTEST-INDIVIDUAL-STEPS"],
#   "tier": "optional",
#   ...
# }
```

### Testing AC-6

**Unit tests** (in `tests/test_selftest_degradation_log.py`):

```bash
# Full degradation log test suite
uv run pytest tests/test_selftest_degradation_log.py -v

# Specific tests:
uv run pytest tests/test_selftest_degradation_log.py::test_log_created_on_governance_failure_in_degraded_mode
uv run pytest tests/test_selftest_degradation_log.py::test_degradation_log_entries_are_jsonl_valid
uv run pytest tests/test_selftest_degradation_log.py::test_log_persists_across_runs
```

**Integration tests** (in `tests/test_selftest_api_contract.py`):

```bash
# Verify /platform/status includes degradations
uv run pytest tests/test_selftest_api_contract.py::test_status_includes_degradations -v
```

**Manual testing**:

```bash
# Force a degradation (e.g., break agents-governance temporarily)
# Then run in degraded mode
uv run swarm/tools/selftest.py --degraded

# Verify log was created
ls -lah selftest_degradations.log

# View degradations
uv run swarm/tools/show_selftest_degradations.py

# Check API sees them
curl http://localhost:5000/platform/status | jq '.governance.degradations'
```

### AC-6 Design Rationale

**Why persistent logging?**
- Operators need a **historical record** of what failed, not just a real-time flag
- Degraded mode allows work to proceed; log shows what still needs fixing
- Multi-day issue tracking: "Did this step fail yesterday too?"

**Why append-only?**
- Auditable: No data loss; full history available
- Chronological: Easy to correlate with other logs
- Git-friendly: Can commit and review degradation patterns over time

**Why JSONL (not JSON array)?**
- Streaming: Can read/write individual entries without loading entire file
- Tool-friendly: Standard for log aggregation systems
- Schema evolution: Can parse even with added future fields

### See Also

- **Full AC matrix**: `docs/SELFTEST_AC_MATRIX.md` — All ACs, steps, tests, surfaces
- **Degradation tool**: `swarm/tools/show_selftest_degradations.py` — Pretty-printer CLI
- **Schema constant**: `swarm/tools/selftest.py::DEGRADATION_LOG_SCHEMA` — Frozen schema version
- **Tests**: `tests/test_selftest_degradation_log.py` — Schema validation tests

---

## See Also

- **Quick reference**: `docs/SELFTEST_GOVERNANCE.md` — Common errors, fixes, escalation
- **Specs**: `specs/spec_ledger.yaml` — Formal ACs with tests
- **Scenarios**: `features/selftest.feature` — BDD test suite
- **Diagnostic tool**: `.claude/skills/heal_selftest/SKILL.md` — How to diagnose failures
- **Flows**: `docs/SWARM_FLOWS.md` — How selftest fits into the SDLC
- **AC Tests**: `tests/test_selftest_ac_traceability.py` — Full chain validation
- **AC Matrix**: `docs/SELFTEST_AC_MATRIX.md` — Complete AC to step mapping
- **Incident Response**: `observability/alerts/README.md` — Alert runbooks, incident pack, first response steps
