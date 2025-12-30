---
description: Run Flow 2 (Spec to Design): produce ADR, contracts, observability spec, test/work plans, design validation.
---

# Flow 2: Spec to Design

You are orchestrating Flow 2 of the SDLC swarm.

## Working Directory + Paths (Invariant)

- All commands run from **repo root**.
- All paths in this doc are **repo-root-relative**.
- Run artifacts live under: `.runs/<run-id>/`
- Flow artifacts live under: `.runs/<run-id>/plan/`
- Do **not** rely on `cd` into any folder to make relative paths work.

**Important**: Step 0 (run-prep) establishes the run directory and ensures `.runs/<run-id>/plan/` exists.

#### Artifact visibility rule

* Do **not** attempt to “prove files exist” under `.runs/<run-id>/…` **before** `signal-run-prep` / `run-prep`.
* If `.runs/` is not directly readable in the current tool context, **do not conclude artifacts are missing**. Proceed with the flow and rely on the flow’s verification agents (e.g., `receipt-checker` in Gate) to obtain evidence from committed state when necessary.
* Preflight in flow docs is **policy**, not mechanics. Mechanics live in agents.

## Your Goals

- Turn requirements into architecture decisions
- Define API contracts and data models
- Create observability, test, and work plans
- Validate design feasibility

## Before You Begin (Required)

### Two State Machines

Flow 2 uses **two complementary state machines**:

1. **TodoWrite** = session navigation (keeps the orchestrator on track during this run)
2. **`flow_plan.md`** = durable on-disk state (enables reruns, handoffs, inspection)

### Setup Steps

1. Use Claude Code's **TodoWrite** tool to create a TODO list of **major stations**.
   - Track at the behavioral/station level, NOT per agent call.
   - Parallel steps (6-9) are ONE todo.
   - Microloops (`design-optioneer` ↔ `option-critic`, `interface-designer` ↔ `contract-critic`, `observability-designer` ↔ `observability-critic`) are ONE todo each.

2. Mirror the same list into `.runs/<run-id>/plan/flow_plan.md` as checkboxes.
   - As each station completes: mark TodoWrite done AND tick the checkbox.

### Suggested TodoWrite Items

```
- run-prep (establish run infrastructure; initialize `flow_plan.md`)
- repo-operator (ensure run branch)
- clarifier (plan open questions)
- impact-analyzer (map impact)
- design-optioneer ↔ option-critic (microloop; signal-based termination)
- adr-author (write ADR)
- interface-designer / observability-designer / test-strategist / work-planner (lanes; parallel)
- interface-designer ↔ contract-critic (microloop; signal-based termination; recommended)
- observability-designer ↔ observability-critic (microloop; signal-based termination; recommended)
- design-critic (integrative validation; may return worklist)
- policy-analyst (policy compliance)
- plan-cleanup (finalize receipt; update index; update `flow_plan.md`)
- secrets-sanitizer (publish gate)
- repo-operator (checkpoint commit)
- gh-issue-manager (update issue status board; gated)
- gh-reporter (post Plan summary; gated)
```

### Critic choreography (default behavior)

Think in **worklists**, not "who wins".

- **Signal-based microloop:** writer → critic → route on handoff. If critic recommends improvements and says further iteration will help: call writer with critique worklist, then call critic again. Otherwise proceed (carry blockers honestly).
- **Option critique (early):** Apply microloop pattern between `design-optioneer` and `option-critic`.
- **Lane worklists:** If `contract-critic` or `observability-critic` recommends fixes or changes, treat that as the active worklist for its lane unless you resolve it or explicitly defer it (Decision Log entry).
- **Integration read (late):** `design-critic` is integrative across artifacts. Run it after lane worklists are resolved/deferred. A later `design-critic` `PROCEED` does not clear an open lane worklist.

### Decision log (only when you defer a critic worklist)

If you intentionally proceed while a critic still has an open worklist (e.g., you choose not to rerun/bounce), record a short entry in `.runs/<run-id>/plan/flow_plan.md` capturing what you deferred, why, evidence, and what you will re-check before sealing `plan_receipt.json`.

### On Rerun

If running `/flow-2-plan` on an existing run-id:
- Read `.runs/<run-id>/plan/flow_plan.md`
- Create TodoWrite from the checklist
- Pre-mark items done if artifacts exist and look current
- Run remaining stations to refine

If you encounter ambiguity or missing information, **document it and continue**. Write assumptions clearly in artifacts.

## Subagents to use

Flow 2 uses infrastructure + domain agents + cross-cutting agents:

### Infrastructure (Step 0)
- run-prep (establish run directory)

### Domain agents (in order)
- impact-analyzer
- design-optioneer
- option-critic
- adr-author
- interface-designer
- contract-critic
- observability-designer
- observability-critic
- test-strategist
- work-planner
- design-critic

### Cross-cutting agents
- clarifier (Plan-local open questions)
- risk-analyst (if risk patterns identified)
- policy-analyst (policy compliance check)
- plan-cleanup (seal receipt, update index)
- secrets-sanitizer (publish gate)
- repo-operator (checkpoint commit - gated on secrets-sanitizer result)
- gh-issue-manager (update issue status board)
- gh-reporter (one comment per Plan run)

## Upstream Inputs

Read from `.runs/<run-id>/signal/` (if available):
- `problem_statement.md`
- `requirements.md`
- `requirements_critique.md`
- `features/*.feature` (BDD scenarios)
- `example_matrix.md`
- `bdd_critique.md`
- `verification_notes.md` (NFR verification criteria)
- `stakeholders.md`
- `early_risks.md`
- `risk_assessment.md`
- `scope_estimate.md`
- `open_questions.md` (Signal's question register)
- `signal_receipt.json` (optional; provides counts and quality gate status without re-parsing)

**If upstream artifacts are missing**: Flow 2 can start without Flow 1. Proceed best-effort: document assumptions, set status to UNVERIFIED, and continue. This enables flexibility for hotfixes or design-first workflows.

## Orchestration outline

### Step 0: Establish Run Infrastructure

**Call `run-prep` first.**

This agent will:
- Derive or confirm the `<run-id>` from context, branch name, or user input
- Create `.runs/<run-id>/plan/` directory structure
- Update `.runs/<run-id>/run_meta.json` with "plan" in `flows_started`
- Update `.runs/index.json`

After this step, you will have a confirmed run directory. All subsequent agents write to `.runs/<run-id>/plan/`.

### Step 0b: Ensure Run Branch

**Call `repo-operator`** with task: "ensure run branch `run/<run-id>`"

The agent handles branch creation/switching safely. This keeps checkpoint commits off main.

### Step 1: Initialize Flow Plan

Create or update `.runs/<run-id>/plan/flow_plan.md`:

```markdown
# Flow 2: Plan for <run-id>

## Planned Steps

- [ ] run-prep (establish run directory)
- [ ] repo-operator (ensure run branch `run/<run-id>`)
- [ ] clarifier (Plan open questions)
- [ ] impact-analyzer (map affected components)
- [ ] design-optioneer ↔ option-critic (microloop; apply Microloop Template)
- [ ] adr-author (write architecture decision)
- [ ] interface-designer (contracts/schema; lane; parallel)
- [ ] interface-designer ↔ contract-critic (microloop; apply Microloop Template)
- [ ] observability-designer (observability; lane; parallel)
- [ ] observability-designer ↔ observability-critic (microloop; apply Microloop Template)
- [ ] test-strategist (test plan; lane; parallel)
- [ ] work-planner (work plan; lane; parallel)
- [ ] design-critic (integrative validation; may return worklist)
- [ ] policy-analyst (check compliance)
- [ ] plan-cleanup (write receipt, update index)
- [ ] secrets-sanitizer (publish gate)
- [ ] repo-operator (checkpoint commit)
- [ ] gh-issue-manager (update issue board)
- [ ] gh-reporter (post summary)

## Progress Notes

<Update as each step completes>

## Decision Log (only when you defer a critic worklist)

- Deferred: <critic-name> requested <RERUN|BOUNCE|FIX_ENV> on <artifact> -> proceeding with <action>
  - Why: <short>
  - Evidence: <artifact/path pointers>
  - Re-check before seal: <what you will re-verify before plan-cleanup>
```

### Step 2: Plan Open Questions (Non-blocking)

Call `clarifier` to create the Plan-local questions register. Signal's `open_questions.md` is upstream input; Plan gets its own register for design-phase questions.

### Step 3: Map impact
- Use `impact-analyzer` to map impact and blast radius.

### Step 4: Propose design options
- Use `design-optioneer` to propose design options.

### Step 4b: Critique design options (microloop; recommended)
- Use `option-critic` to critique `design_options.md` and write `option_critique.md`.

**Route on the critic's handoff recommendation:**
- If critic says "blocked" → stop (mechanical failure)
- If critic recommends routing to a different flow/agent → follow the recommendation
- If critic recommends "rerun optioneer" or "fix X" → run design-optioneer with critique worklist, then rerun critic
- If critic says "ready to proceed" → proceed (Decision Log when deferring issues)

### Step 5: Write ADR
- Use `adr-author` to write the ADR.

### Step 6: Define contracts and schema (FIRST - others depend on this)
- Use `interface-designer` for contracts/schema/migrations (planned migrations live under the run directory; actual migrations move during Build).
- **This must complete before Steps 8-9** because:
  - `test-strategist` reads `schema.md` to plan test data/fixture updates
  - `test-strategist` reads `api_contracts.yaml` to generate contract-bound ACs
  - `work-planner` reads `migrations/` to schedule infrastructure subtasks (ST-000)

### Step 6b: Validate contracts (microloop; recommended)
- Use `contract-critic` to validate `api_contracts.yaml` + `schema.md` and write `contract_critique.md`.

**Route on the critic's handoff recommendation:**
- If critic says "blocked" → stop (mechanical failure)
- If critic recommends routing to a different flow/agent → follow the recommendation
- If critic recommends "rerun designer" or "fix X" → run interface-designer with critique worklist, then rerun critic
- If critic says "ready to proceed" → proceed (Decision Log when deferring issues)

**Conflict note (default):** If Contract Critic recommends fixes or changes, treat that as an open contract-lane worklist unless you resolve it or explicitly defer it (record a Decision Log entry in `flow_plan.md`).

### Step 7: Plan observability (parallel)
- Use `observability-designer` to define observability.

### Step 7b: Validate observability (microloop; recommended)
- Use `observability-critic` to validate `observability_spec.md` and write `observability_critique.md`.

**Route on the critic's handoff recommendation:**
- If critic says "blocked" → stop (mechanical failure)
- If critic recommends routing to a different flow/agent → follow the recommendation
- If critic recommends "rerun designer" or "fix X" → run observability-designer with critique worklist, then rerun critic
- If critic says "ready to proceed" → proceed (Decision Log when deferring issues)

**Conflict note (default):** If Observability Critic recommends fixes or changes, treat that as an open observability-lane worklist unless you resolve it or explicitly defer it (record a Decision Log entry in `flow_plan.md`).

### Step 8: Plan testing (after interface-designer)
- Use `test-strategist` to write the test plan (incorporate Signal BDD + verification notes).
- **Requires:** `schema.md` (for fixture planning) and `api_contracts.yaml` (for contract-to-AC binding)

### Step 9: Plan work (after interface-designer)
- Use `work-planner` — "produce subtask index + work plan".
- **Requires:** `migrations/` (to sequence infrastructure subtasks as ST-000 prerequisites)

### Step 10: Validate design (microloop)
- Use `design-critic` to validate the design.

**Conflict handling (default):**
- If a targeted critic still recommends fixes or changes, keep that lane's worklist open until resolved or explicitly deferred (Decision Log entry in `flow_plan.md`). You can still run `design-critic` for an integration read.

**Route on the critic's handoff recommendation:**
- If critic says "verified" or "ready to proceed" → proceed to policy check
- If critic recommends improvements and says further iteration will help → rerun affected steps (options/ADR/contracts/plans); if you rerun `interface-designer` or `observability-designer`, run the matching targeted critic (`contract-critic` / `observability-critic`) before re-running design-critic
- If critic says "no further improvement possible" → proceed (remaining issues documented)
- If critic says "blocked" → stop (mechanical failure)

**Loop guidance**: The handoff is the routing surface; `design_validation.md` is the audit artifact. Agents do not know they are in a loop—they read inputs, write outputs, and provide a recommendation. The orchestrator routes on the handoff.

### Step 11: Check policy compliance
- Use `policy-analyst` for policy compliance.

### Step 12: Finalize Plan (receipt + index)
- Use `plan-cleanup` to seal the receipt, verify artifacts, and update index counts mechanically.

### Step 13: Sanitize secrets (publish gate)
- Use `secrets-sanitizer` (publish gate).

**Gate Result block (returned by secrets-sanitizer):**

The agent returns a Gate Result block for orchestrator routing:

<!-- PACK-CONTRACT: GATE_RESULT_V3 START -->
```yaml
## Gate Result
status: CLEAN | FIXED | BLOCKED
safe_to_commit: true | false
safe_to_publish: true | false
modified_files: true | false
findings_count: <int>
blocker_kind: NONE | MECHANICAL | SECRET_IN_CODE | SECRET_IN_ARTIFACT
blocker_reason: <string | null>
```
<!-- PACK-CONTRACT: GATE_RESULT_V3 END -->

**Field semantics:**
- `status` is **descriptive** (what happened). **Never infer permissions** from it.
- `safe_to_commit` / `safe_to_publish` are **authoritative permissions**.
- `modified_files` signals that artifact files were changed (for audit purposes).
- `blocker_kind` explains why blocked (machine-readable category): `NONE | MECHANICAL | SECRET_IN_CODE | SECRET_IN_ARTIFACT`

**Control plane vs audit plane:** The Gate Result block is the control plane for orchestrator routing. `secrets_status.json` is the durable audit record. Route on the returned block, not by re-reading the file.

**Gating logic (boolean gate — the sanitizer says yes/no, orchestrator decides next steps):**
- The sanitizer is a fix-first pre-commit hook, not a router
- If `safe_to_commit: true` → proceed to checkpoint commit (Step 13c)
- If `safe_to_commit: false`:
  - `blocker_kind: MECHANICAL` → **FIX_ENV** (tool/IO failure)
  - `blocker_kind: SECRET_IN_CODE` → route to appropriate agent (orchestrator decides)
  - `blocker_kind: SECRET_IN_ARTIFACT` → investigate manually
- Publish mode gating: `FULL` only when `safe_to_publish: true`, Repo Operator Result `proceed_to_github_ops: true`, **and** `publish_surface: PUSHED`. Otherwise, GitHub ops (when access is allowed) run in `RESTRICTED` mode. Publish blocked implies RESTRICTED, **not skip**.

### Step 13b: Checkpoint Commit

Checkpoint the audit trail **before** any GitHub operations.

**Call `repo-operator`** in checkpoint mode. The agent handles:
1. Resets staging and stages allowlist only
2. Enforces allowlist/anomaly interlock mechanically
3. Writes `.runs/<run-id>/plan/git_status.md` if anomaly detected
4. Handles no-op gracefully (nothing to commit = success)
5. Returns **Repo Operator Result** (control plane)

**Allowlist for Flow 2:**
- `.runs/<run-id>/plan/`
- `.runs/<run-id>/run_meta.json`
- `.runs/index.json`

**Control plane:** The `repo-operator` returns a **Repo Operator Result block** for orchestrator routing:

```md
## Repo Operator Result
operation: checkpoint
status: COMPLETED | COMPLETED_WITH_ANOMALY | FAILED | CANNOT_PROCEED
proceed_to_github_ops: true | false
commit_sha: <sha>
publish_surface: PUSHED | NOT_PUSHED
anomaly_paths: []
```

**Note:** `commit_sha` is always populated (current HEAD on no-op), never null. `publish_surface` must always be present (PUSHED or NOT_PUSHED), even on no-op commits, anomalies, `safe_to_commit: false`, push skipped, or push failure.

**Routing logic (from Repo Operator Result):**
- `status: COMPLETED` + `proceed_to_github_ops: true` → proceed to GitHub ops
- `status: COMPLETED_WITH_ANOMALY` → allowlist committed, anomaly documented in `git_status.md`; `proceed_to_github_ops: false`
- `status: FAILED` or `status: CANNOT_PROCEED` → mechanical failure; stop and require human intervention

**Gating interaction with secrets-sanitizer:**
- `repo-operator` reads `safe_to_commit` and `safe_to_publish` from the prior Gate Result
- If `safe_to_commit: false`: skips commit entirely
- If `safe_to_publish: false`: commits locally but skips push; sets `proceed_to_github_ops: false` and `publish_surface: NOT_PUSHED`

**Why checkpoint before GitHub ops:** The issue comment can reference a stable commit SHA. Also keeps local history clean if the flow is interrupted.

### Step 14-15: GitHub Reporting

**Call `gh-issue-manager`** then **`gh-reporter`** to update the issue.

See `CLAUDE.md` → **GitHub Access + Content Mode** for gating rules. Quick reference:
- Skip if `github_ops_allowed: false` or `gh` unauthenticated
- Content mode is derived from secrets gate + push surface (not workspace hygiene)
- Issue-first: flow summaries go to the issue, never the PR

### Step 16: Finalize flow_plan.md

Update `flow_plan.md`:
- Mark all steps as complete
- Add final summary section:

```markdown
## Summary

- **Final Status**: VERIFIED | UNVERIFIED
- **ADR Decision**: <brief summary of chosen approach>
- **Design Concerns**: See `.runs/<run-id>/plan/design_validation.md`
- **Next Flow**: `/flow-3-build` (after human review)

## Human Review Checklist

Before proceeding to Flow 3, humans should review:
- [ ] `.runs/<run-id>/plan/adr.md` - Is this the right architecture decision?
- [ ] `.runs/<run-id>/plan/api_contracts.yaml` - Are the contracts correct?
- [ ] `.runs/<run-id>/plan/work_plan.md` - Is the breakdown reasonable?
- [ ] `.runs/<run-id>/plan/design_validation.md` - Are flagged concerns acceptable?
```

## Downstream Contract

Flow 2 is complete when these exist (even if imperfect):

- `flow_plan.md` - Execution plan and progress
- `plan_receipt.json` - Receipt for downstream consumers
- `impact_map.json` - Services, modules, data, external systems affected
- `design_options.md` - 2-3 architecture options with trade-offs
- `option_critique.md` - Options critique + worklist (decision readiness)
- `adr.md` - Chosen option with rationale and consequences
- `api_contracts.yaml` - Endpoints, schemas, error shapes
- `schema.md` - Data models, relationships, invariants
- `migrations/*.sql` - Draft migrations (optional, if DB changes needed)
- `observability_spec.md` - Metrics, logs, traces, SLOs, alerts
- `test_plan.md` - BDD to test types mapping, priorities
- `ac_matrix.md` - AC-driven build contract (Flow 3 iterates per AC; Build creates `build/ac_status.json` at runtime)
- `work_plan.md` - Subtasks, ordering, dependencies
- `design_validation.md` - Feasibility assessment, known issues

## Status States

Agents communicate status through their handoff prose:

- **Complete / Verified**: Work is done, evidence exists, no blockers. Handoff recommends "proceed" or "ready for X".
- **Incomplete / Unverified**: Gaps exist, blockers documented. Handoff recommends next steps ("fix X", "rerun Y") or acknowledges human review needed.
- **Blocked**: Mechanical failure only (IO/permissions/tooling). Handoff explains what's broken and that environment needs fixing.

**Key rule**: "Blocked" is strictly for mechanical failures. Missing upstream artifacts result in "incomplete" status with documented gaps, not "blocked".

Use `plan_receipt.json` (primary) and the latest critic handoffs (secondary) to determine flow outcome. When critics recommend fixes, treat those as open lane worklists unless explicitly deferred (Decision Log entry in `flow_plan.md`).

## Notes

- **Lane dependencies (Materials-First sequencing):**
  - `interface-designer` (Step 6) must complete first — produces `schema.md`, `api_contracts.yaml`, `migrations/`
  - `observability-designer` (Step 7) can run in parallel with Step 6
  - `test-strategist` (Step 8) depends on Step 6 outputs (contract-to-AC binding, fixture planning)
  - `work-planner` (Step 9) depends on Step 6 outputs (infrastructure subtask sequencing)
- `design-critic` reviews ALL artifacts before policy check
- `option-critic` critiques options before ADR authoring
- Human gate at end: "Is this the right design?"
- Agents never block; they document concerns and continue

## Artifact Outputs

All written to `.runs/<run-id>/plan/`:

| Artifact | Source Agent | Description |
|----------|--------------|-------------|
| `flow_plan.md` | orchestrator | Execution plan and progress |
| `open_questions.md` | clarifier | Plan-local questions register |
| `impact_map.json` | impact-analyzer | Affected services, modules, data |
| `design_options.md` | design-optioneer | 2-3 architecture options |
| `option_critique.md` | option-critic | Options critique + worklist |
| `adr.md` | adr-author | Chosen option with rationale |
| `api_contracts.yaml` | interface-designer | Endpoints, schemas, errors |
| `schema.md` | interface-designer | Data models, relationships |
| `migrations/*.sql` | interface-designer | Draft migrations (if needed) |
| `contract_critique.md` | contract-critic | Contract validation critique (optional) |
| `observability_spec.md` | observability-designer | Metrics, logs, traces, SLOs |
| `observability_critique.md` | observability-critic | Observability validation critique (optional) |
| `test_plan.md` | test-strategist | BDD to test types mapping |
| `ac_matrix.md` | test-strategist | AC-driven build contract (Build creates `build/ac_status.json`) |
| `work_plan.md` | work-planner | Subtasks, ordering, dependencies |
| `design_validation.md` | design-critic | Feasibility assessment |
| `policy_analysis.md` | policy-analyst | Policy compliance check |
| `plan_receipt.json` | plan-cleanup | Receipt for downstream |
| `cleanup_report.md` | plan-cleanup | Cleanup status and evidence |
| `secrets_scan.md` | secrets-sanitizer | Secrets scan report |
| `secrets_status.json` | secrets-sanitizer | Publish gate status |
| `gh_issue_status.md` | gh-issue-manager | Issue board update status |
| `gh_report_status.md` | gh-reporter | GitHub posting status |
| `github_report.md` | gh-reporter | Report content (local copy) |
| `git_status.md` | repo-operator | Git tree status (if anomaly detected) |

---

## Orchestrator Kickoff

### Station order + templates

#### Station order

1. `run-prep`

2. `repo-operator` (ensure run branch)

3. `clarifier`

4. `impact-analyzer`

5. `design-optioneer` ↔ `option-critic` (microloop; apply Microloop Template)

6. `adr-author`

7. `interface-designer` / `observability-designer` / `test-strategist` / `work-planner` (parallel)

8. `interface-designer` ↔ `contract-critic` (microloop; apply Microloop Template; recommended)

9. `observability-designer` ↔ `observability-critic` (microloop; apply Microloop Template; recommended)

10. `design-critic` (integrative validation; route to options/contracts/observability/plans as returned; rerun once to confirm the top worklist moved)

11. `policy-analyst`

12. `plan-cleanup`

13. `secrets-sanitizer`

14. `repo-operator` (checkpoint; read Repo Operator Result)

15. `gh-issue-manager` (if allowed)

16. `gh-reporter` (if allowed)

#### Microloop Template (writer ↔ critic)

Run this template for: tests, code, docs, requirements, BDD, options, contracts, observability.

1) Writer pass: call `<writer>`
2) Critique pass: call `<critic>` and read its handoff
3) Route on critic handoff:
   - If critic says "ready to proceed" → proceed (no apply pass needed)
   - If critic recommends "fix X" or "rerun writer" → continue to step 4
   - Otherwise → proceed with blockers documented
4) Apply pass: call `<writer>` with the critique worklist
5) Re-critique: call `<critic>` again, return to step 3

**Termination:** Signal-based, not count-based. Loop continues while critic recommends improvements and indicates further iteration will help. Exit when critic says "proceed" or "no further improvement possible" or context exhausted.

### TodoWrite (copy exactly)
- [ ] run-prep
- [ ] repo-operator (ensure `run/<run-id>` branch)
- [ ] clarifier (plan open questions)
- [ ] impact-analyzer
- [ ] design-optioneer ↔ option-critic (microloop; signal-based termination)
- [ ] adr-author
- [ ] interface-designer / observability-designer / test-strategist / work-planner (parallel)
- [ ] interface-designer ↔ contract-critic (microloop; signal-based termination; recommended)
- [ ] observability-designer ↔ observability-critic (microloop; signal-based termination; recommended)
- [ ] design-critic (microloop if needed)
- [ ] policy-analyst
- [ ] plan-cleanup
- [ ] secrets-sanitizer (capture Gate Result block)
- [ ] repo-operator (checkpoint; capture Repo Operator Result)
- [ ] gh-issue-manager (skip when github_ops_allowed: false; FULL/RESTRICTED based on gates/publish_surface)
- [ ] gh-reporter (skip when github_ops_allowed: false; FULL/RESTRICTED based on gates/publish_surface)

Use explore agents to answer any immediate questions you have and then create the todo list and call the agents.
