---
description: Run Flow 5 (Code -> Artifact): verify receipts, contracts, security, policies; decide merge vs bounce; execute bounded fix-forward lane when eligible.
---

# Flow 5: Code -> Artifact (Gate)

You are orchestrating Flow 5 of the SDLC swarm.

## Working Directory + Paths (Invariant)

- All commands run from **repo root**.
- All paths in this doc are **repo-root-relative**.
- Run artifacts live under: `.runs/<run-id>/`
- Flow artifacts live under: `.runs/<run-id>/gate/`
- Do **not** rely on `cd` into any folder to make relative paths work.

**Important**: Step 0 (run-prep) establishes the run directory and ensures `.runs/<run-id>/gate/` exists.

#### Artifact visibility rule

* Do **not** attempt to prove files exist under `.runs/<run-id>/` **before** `signal-run-prep` / `run-prep`.
* If `.runs/` is not directly readable in the current tool context, **do not conclude artifacts are missing**. Proceed with the flow and rely on verification agents (e.g., `receipt-checker`) to obtain evidence from committed state when necessary.
* Preflight in flow docs is **policy**, not mechanics. Mechanics live in agents.

## Your Goals

- Verify build receipts exist and are complete
- Check API/schema contracts
- Scan security and coverage
- Enforce policies
- Decide: MERGE / BOUNCE (with reason for human-review vs fix-required)
- **Runner-bounded fix-forward lane** for deterministic mechanical drift (fmt/import/whitespace/docs) when `gate-fixer` says it is safe and resealable

## Role Clarification: Final Verification, Not Primary Detection

Flow 5 Gate is the **last line of defense**, not the first.

**Primary detection happens earlier:**
- Flow 3 (Build): Critics catch issues per-AC, standards-enforcer catches reward hacking
- Flow 4 (Review): Worklist drains all feedback items, stale check prevents wasted work

**Gate's job is to VERIFY**, not DISCOVER:
- Verify that receipts from earlier flows are complete and consistent
- Verify that policy compliance was checked (not run the checks from scratch)
- Verify that security findings were addressed (not scan for new ones)
- Make the merge decision based on accumulated evidence

**If Gate is catching issues that should have been caught earlier:**
- That's a signal that earlier flows need improvement
- Document the gap in `observations[]` for Flow 7 (Wisdom)
- Fix-forward only for mechanical drift (formatting, imports)
- BOUNCE for semantic issues (they should have been caught in Build/Review)

**Anti-pattern:** Running full security scans, coverage checks, and lint sweeps in Gate that duplicate earlier flows. Gate should READ results, not RE-RUN analysis.

## Before You Begin (Required)

### Two State Machines

Flow 5 uses **two complementary state machines**:

1. **TodoWrite** = session navigation (keeps the orchestrator on track during this run)
2. **`flow_plan.md`** = durable on-disk state (enables reruns, handoffs, inspection)

### Setup Steps

1. Use Claude Code's **TodoWrite** tool to create a TODO list of **major stations**.
   - Track at the behavioral/station level, NOT per agent call.
   - Parallel checks (contracts/security/coverage) are ONE todo.

2. Mirror the same list into `.runs/<run-id>/gate/flow_plan.md` as checkboxes.
   - As each station completes: mark TodoWrite done AND tick the checkbox.

### Suggested TodoWrite Items

```
- run-prep (establish run infrastructure)
- repo-operator (ensure run branch)
- receipt-checker (verify receipts first; route on Result)
- contract-enforcer / security-scanner / coverage-enforcer (parallel checks)
- gate-fixer (mechanical issues report; emits FIX_FORWARD_PLAN_V1)
- fix-forward-runner (if eligible; execute `FIX_FORWARD_PLAN_V1`; confirm via `receipt-checker` + `gate-fixer`)
- traceability-auditor (traceability audit)
- risk-analyst (risk assessment)
- policy-analyst (policy compliance)
- merge-decider (merge decision)
- gate-cleanup (finalize receipt; update index; update `flow_plan.md`)
- secrets-sanitizer (publish gate)
- repo-operator (checkpoint commit)
- gh-issue-manager (update issue board; gated)
- gh-reporter (report gate verdict; gated)
```

### On Rerun

If running `/flow-5-gate` on an existing run-id:
- Read `.runs/<run-id>/gate/flow_plan.md`
- Create TodoWrite from the checklist
- Pre-mark items done if artifacts exist and look current
- Run remaining stations to refine

If you encounter missing receipts or unclear state, **document it and continue with available information**. Gate agents should note gaps in their reports rather than blocking.

## Subagents to use

**Infrastructure (Step 0)**:
- run-prep (establish run directory)

Domain agents (Flow 5 specific):
- receipt-checker
- contract-enforcer
- security-scanner
- coverage-enforcer
- gate-fixer (reports mechanical issues; no repo mutations)
- fix-forward-runner (executes FIX_FORWARD_PLAN_V1; no git side effects)
- build-cleanup (reseal Build receipt after runner changes code)
- merge-decider

Cross-cutting agents:
- risk-analyst
- policy-analyst
- traceability-auditor (run-level coherence + spec traceability before merge decision)

Cleanup + Reporting (End of Flow):
- gate-cleanup -- writes gate_receipt.json, updates index.json status
- secrets-sanitizer -- publish gate
- repo-operator -- checkpoint commit (gated on secrets-sanitizer result); writes git_status.md if anomaly
- gh-issue-manager -- updates issue body status board
- gh-reporter -- posts gate verdict to issue

## Upstream Inputs

Read from `.runs/<run-id>/build/` (if available):
- build receipt and supporting critiques (tests, code, self-review)
- `build/ac_status.json` (AC completion tracker)

Read from `.runs/<run-id>/review/` (if available):
- `review_receipt.json` (for bounce-to-review evidence)
- Check `worklist_status.has_critical_pending` and `counts.worklist_pending` for unresolved items

If these files are not visible locally but may exist in committed state, do **not** block Gate. Proceed and let `receipt-checker` pull evidence from the committed snapshot; workspace visibility alone is not a missing-artifact signal.

**If upstream artifacts are missing**: Flow 5 can start without Flows 1-3. Proceed best-effort: document assumptions, set status to UNVERIFIED, and continue. This enables flexibility for gate-only checks.

## Artifact Outputs

| Artifact | Producer | Description |
|----------|----------|-------------|
| `flow_plan.md` | Orchestrator | Flow progress tracking |
| `receipt_audit.md` | receipt-checker | Build receipt verification |
| `contract_compliance.md` | contract-enforcer | API contract check results |
| `security_scan.md` | security-scanner | Security scan findings |
| `coverage_audit.md` | coverage-enforcer | Coverage threshold check |
| `gate_fix_summary.md` | gate-fixer | Mechanical issues report (no fixes) + fix-forward plan |
| `fix_forward_report.md` | fix-forward-runner (conditional) | Runner execution log: commands run, scope check, files touched, reseal guidance |
| `traceability_audit.md` | traceability-auditor | Run-level coherence + spec traceability (REQ<->BDD) across receipts/index/GitHub markers |
| `risk_assessment.md` | risk-analyst | Risk analysis |
| `policy_analysis.md` | policy-analyst | Policy compliance check |
| `merge_decision.md` | merge-decider | MERGE / BOUNCE decision (with reason) |
| `cleanup_report.md` | gate-cleanup | Cleanup summary |
| `gate_receipt.json` | gate-cleanup | Machine-readable receipt |
| `secrets_scan.md` | secrets-sanitizer | Secrets scan findings |
| `secrets_status.json` | secrets-sanitizer | Gate status (audit record) |
| `git_status.md` | repo-operator | Anomaly documentation (if detected) |
| `gh_issue_status.md` | gh-issue-manager | Issue operation status |
| `github_report.md` | gh-reporter | Local copy of GitHub post |
| `gh_report_status.md` | gh-reporter | GitHub posting status |

All artifacts live under `.runs/<run-id>/gate/`.

**Fix-forward contract:** `gate_fix_summary.md` must contain the `## Fix-forward Plan (machine readable)` block (`PACK-CONTRACT: FIX_FORWARD_PLAN_V1`). `fix_forward_report.md` records what the runner actually executed (commands, scope check, files touched, reseal guidance).

## Orchestration outline

### Step 0: Establish Run Infrastructure

**Call `run-prep` first.**

This agent will:
- Derive or confirm the `<run-id>` from context, branch name, or user input
- Create `.runs/<run-id>/gate/` directory structure
- Update `.runs/<run-id>/run_meta.json` with "gate" in `flows_started`
- Update `.runs/index.json`

After this step, you will have a confirmed run directory. All subsequent agents write to `.runs/<run-id>/gate/`.

### Step 0b: Ensure Run Branch

**Call `repo-operator`** with task: "ensure run branch `run/<run-id>`"

The agent handles branch creation/switching safely. This keeps checkpoint commits off main.

**Do not** read `.runs/` artifacts before run-prep. After run-prep, call `receipt-checker` first and route on its Result block before running contracts/security/coverage.

### Step 1: Initialize Flow Plan

Create or update `.runs/<run-id>/gate/flow_plan.md`:

```markdown
# Flow 5: Gate for <run-id>

## Planned Steps

- [ ] run-prep (establish run directory)
- [ ] repo-operator (ensure run branch `run/<run-id>`)
- [ ] receipt-checker (verify receipts first; route on Result)
- [ ] contract-enforcer / security-scanner / coverage-enforcer (parallel)
- [ ] gate-fixer (mechanical issues report)
- [ ] fix-forward-runner (if eligible; execute `FIX_FORWARD_PLAN_V1`; confirm via `receipt-checker` + `gate-fixer`)
- [ ] traceability-auditor (run-level coherence)
- [ ] risk-analyst (risk assessment)
- [ ] policy-analyst (policy compliance)
- [ ] merge-decider (decide: MERGE/BOUNCE + reason)
- [ ] gate-cleanup (write receipt, update index)
- [ ] secrets-sanitizer (publish gate)
- [ ] repo-operator (checkpoint commit)
- [ ] gh-issue-manager (update issue board)
- [ ] gh-reporter (post summary)

## Progress Notes

<Update as each step completes>
```

### Step 2: Verify receipts
- `receipt-checker` -> `.runs/<run-id>/gate/receipt_audit.md`
- Run this before contracts/security/coverage; route on its Result block.
- **Evidence audit, not re-execution:** The receipt-checker verifies that earlier flows produced complete artifacts with passing gates. It does NOT re-run tests or re-scan for secrets—it reads the receipts.
- **Receipts are logs, not locks:** The git log is the audit trail. If code was modified after a receipt was written (ad-hoc fixes, fix-forward), the receipt is still valid as historical evidence of what happened at that station. Don't BOUNCE just because `evidence_sha != HEAD`.
- **AC completion check:** Receipt-checker should verify `build_receipt.json.counts.ac_completed == build_receipt.json.counts.ac_total`. If either is null/missing, treat as UNVERIFIED with blocker. If not equal, BOUNCE to Flow 3 with blocker: "AC loop incomplete: {ac_completed}/{ac_total}".

### Step 3: Check contracts (can run in parallel with security/coverage)
- `contract-enforcer` -> `.runs/<run-id>/gate/contract_compliance.md`

### Step 4: Security scan (can run in parallel with contracts/coverage)
- `security-scanner` -> `.runs/<run-id>/gate/security_scan.md`

### Step 5: Coverage (can run in parallel with contracts/security)
- `coverage-enforcer` -> `.runs/<run-id>/gate/coverage_audit.md`

### Step 6: Mechanical issues report
- `gate-fixer` -> `.runs/<run-id>/gate/gate_fix_summary.md` (recommendations only; **no repo mutations in Gate**)
- Identifies lint, format, and doc issues that would be fixed in Build

### Step 7: Fix-forward lane (conditional; runner-bounded)
Treat fix-forward as a **subroutine station**, not a per-call checklist.

- Entry condition: `fix_forward_eligible: true` (from `gate-fixer` / `gate_fix_summary.md`)
- Apply Fix-forward Subroutine Template with:
  - producer = `gate-fixer` (emits `FIX_FORWARD_PLAN_V1`)
  - fix lane = `fix-forward-runner` (executes `apply_steps`/`verify_steps`; no git side effects)
  - confirm = rerun `receipt-checker`, then rerun `gate-fixer` once

If the runner reports `changes_detected: true`, update build receipt + stage + secrets gate + commit/push the runner-touched scope, then run the confirm pass.

If the runner reports UNVERIFIED or scope violation, proceed with remaining Gate stations; `merge-decider` should BOUNCE to Flow 3 with the runner report as evidence.

### Step 8: Traceability audit
- `traceability-auditor` -> `.runs/<run-id>/gate/traceability_audit.md`
- Run after fix-forward reruns so receipts/index are current.

### Step 9: Risk assessment
- `risk-analyst` -> `.runs/<run-id>/gate/risk_assessment.md`

### Step 10: Policy compliance
- `policy-analyst` -> `.runs/<run-id>/gate/policy_analysis.md`

### Step 11: Merge decision
- `merge-decider` -> `.runs/<run-id>/gate/merge_decision.md` (MERGE/BOUNCE with reason)

### Step 12: Finalize and Write Receipt
- `gate-cleanup` -> `.runs/<run-id>/gate/gate_receipt.json`, `.runs/<run-id>/gate/cleanup_report.md`
- Verifies all required artifacts exist
- Computes counts mechanically (never estimates)
- Updates `.runs/index.json` with status, last_flow, updated_at

### Step 13: Sanitize Secrets (Publish Gate)
- `secrets-sanitizer` -> `.runs/<run-id>/gate/secrets_scan.md`, `.runs/<run-id>/gate/secrets_status.json`
- Scans .runs/ artifacts before GitHub posting
- Returns a **Gate Result** block (control plane; file is audit-only)

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

**Gating logic (boolean gate — the sanitizer says yes/no, orchestrator decides next steps):**
- The sanitizer is a fix-first pre-commit hook, not a router
- If `safe_to_commit: true` → proceed to checkpoint commit (Step 13c)
- If `safe_to_commit: false`:
  - `blocker_kind: MECHANICAL` → **FIX_ENV** (tool/IO failure)
  - `blocker_kind: SECRET_IN_CODE` → route to `fixer` (orchestrator decides)
  - `blocker_kind: SECRET_IN_ARTIFACT` → investigate manually
- Push requires: `safe_to_publish: true` AND Repo Operator Result `proceed_to_github_ops: true`
- GitHub reporting ops still run in RESTRICTED mode when publish is blocked or `publish_surface: NOT_PUSHED`

### Step 13b: Checkpoint Commit

- `repo-operator` -> `.runs/<run-id>/gate/git_status.md` (if anomaly detected)

Checkpoint the audit trail **before** any GitHub operations.

**Allowlist for Flow 5:**
- `.runs/<run-id>/gate/`
- `.runs/<run-id>/run_meta.json`
- `.runs/index.json`

**Call `repo-operator`** with `checkpoint_mode: normal` (default). The agent:
1. Resets staging and stages only the allowlist (not `git add .`)
2. Enforces the allowlist/anomaly interlock mechanically
3. Writes `.runs/<run-id>/gate/git_status.md` if anomaly detected
4. Handles no-op (nothing staged) gracefully—no empty commits

**Control plane:** `repo-operator` returns a Repo Operator Result block:
```
## Repo Operator Result
operation: checkpoint
status: COMPLETED | COMPLETED_WITH_ANOMALY | FAILED | CANNOT_PROCEED
proceed_to_github_ops: true | false
commit_sha: <sha>
publish_surface: PUSHED | NOT_PUSHED
anomaly_paths: []
```
**Note:** `commit_sha` is always populated (current HEAD on no-op), never null.

Orchestrators route on this block, not by re-reading `git_status.md`.

**Safe-bail enforcement:** If this checkpoint was invoked due to safe-bail (Step 13b), `repo-operator` must set `proceed_to_github_ops: false` even if `safe_to_publish: true`.

**Gating logic (from prior secrets-sanitizer Gate Result + repo-operator result):**
- If `safe_to_commit: false` (from Gate Result): `repo-operator` skips commit entirely
- If anomaly detected: `repo-operator` commits allowlist only, skips push, returns `proceed_to_github_ops: false`
- If `safe_to_publish: true` and no anomaly: `repo-operator` commits and pushes, returns `proceed_to_github_ops: true`
- If `safe_to_publish: false`:
  - If `needs_upstream_fix: true` → **BOUNCE** (Navigator determines routing from handoff summary + pointer to `secrets_scan.md`); flow ends UNVERIFIED
  - If `status: BLOCKED_PUBLISH` → **CANNOT_PROCEED** (mechanical failure); stop and require human intervention
  - Otherwise → UNVERIFIED; skip push (`publish_surface: NOT_PUSHED`). Continue with GitHub Reporting Ops in RESTRICTED mode when access allows.

### Step 14-15: GitHub Reporting

**Call `gh-issue-manager`** then **`gh-reporter`** to update the issue.

See `CLAUDE.md` → **GitHub Access + Content Mode** for gating rules. Quick reference:
- Skip if `github_ops_allowed: false` or `gh` unauthenticated
- Content mode is derived from secrets gate + push surface (not workspace hygiene)
- Issue-first: flow summaries go to the issue, never the PR

### Step 16: Finalize Flow

Update `flow_plan.md`:
- Mark all steps as complete
- Add final summary section:

```markdown
## Summary

- **Final Status**: VERIFIED | UNVERIFIED
- **Merge Decision**: MERGE | BOUNCE (reason: NEEDS_HUMAN_REVIEW | FIX_REQUIRED | POLICY_BLOCK | OTHER)
- **Blockers**: <list if any>
- **Next Flow**: `/flow-6-deploy` (if MERGE) or bounce target

## Human Review Checklist

Before proceeding:
- [ ] `.runs/<run-id>/gate/merge_decision.md` - Is the decision correct?
- [ ] `.runs/<run-id>/gate/security_scan.md` - Are security findings acceptable?
- [ ] `.runs/<run-id>/gate/policy_analysis.md` - Are policy concerns addressed?
```

## Bounce Semantics

Gate-fixer **remains report-only**. It emits the fix-forward plan; the **fix-forward lane** applies deterministic hygiene once (fmt/import order/docs) and reseals before merge-decision. Formatting/import-only drift should be fixed-forward when `fix_forward_eligible: true`; bounce only if ineligible or the fix-forward attempt failed.

**BOUNCE to Review (Flow 4)**:
- Unaddressed PR feedback (CodeRabbit, CI issues, review comments)
- Review worklist items still pending

**Evidence-based check:** If `review_receipt.json` exists, Gate should read:
- `review_receipt.json.worklist_status.has_critical_pending` — if true, BOUNCE to Flow 4
- `review_receipt.json.counts.worklist_pending` — if > 0 and items are CRITICAL/MAJOR, BOUNCE to Flow 4
- `review_receipt.json.worklist_status.review_complete` — if false, consider BOUNCE to Flow 4

**BOUNCE to Build (Flow 3)**:
- Logic errors
- Test failures
- API contract violations
- Security vulnerabilities
- Coverage below threshold
- AC loop incomplete (`build_receipt.json.counts.ac_completed < build_receipt.json.counts.ac_total`, or either is null)
- Mechanical drift that is **not** eligible for fix-forward or failed within the runner-bounded lane

**BOUNCE to Plan (Flow 2)**:
- Design flaws
- Architecture issues
- Missing requirements

## Status States

Agents set status in their output artifacts:

- **VERIFIED**: `blockers` empty, `missing_required` empty, and check passed. Set `recommended_action: PROCEED`.
- **UNVERIFIED**: `blockers` non-empty OR `missing_required` non-empty OR check has concerns. Set `recommended_action: RERUN | BOUNCE` depending on fix location.
- **CANNOT_PROCEED**: IO/permissions/tool failure only (exceptional); cannot read files, tool missing, etc. Set `missing_required` with paths and `recommended_action: FIX_ENV`.

**Key rule**: CANNOT_PROCEED is strictly for mechanical failures. Missing upstream artifacts are UNVERIFIED with `missing_required` populated, not CANNOT_PROCEED.

`merge-decider` synthesizes all statuses into a merge decision.

## Merge Decision States

`merge-decider` outputs one of:

- **MERGE**: All checks pass or concerns are acceptable; ready to deploy.
- **BOUNCE**: Issues found **or** human judgment is required. Include a `reason` field (e.g., `NEEDS_HUMAN_REVIEW`, `FIX_REQUIRED`, `POLICY_BLOCK`, `UNKNOWN_UPSTREAM`) and the target flow/agent when action is known.

Human-review-only cases use `reason: NEEDS_HUMAN_REVIEW` instead of a separate human-only verdict.

---

## Orchestrator Kickoff

### Station order + templates

#### Station order

1. `run-prep`

2. `repo-operator` (ensure run branch)

3. `receipt-checker`

4. `contract-enforcer` / `security-scanner` / `coverage-enforcer` (parallel)

5. `gate-fixer` (report + fix-forward plan)

6. `fix-forward-runner` (if eligible; execute `FIX_FORWARD_PLAN_V1`; confirm via rerun `receipt-checker` + `gate-fixer`)

7. `traceability-auditor`

8. `risk-analyst`

9. `policy-analyst`

10. `merge-decider`

11. `gate-cleanup`

12. `secrets-sanitizer`

13. `repo-operator` (checkpoint; read Repo Operator Result)

14. `gh-issue-manager` (if allowed)

15. `gh-reporter` (if allowed)

#### Fix-forward Subroutine Template (plan -> execute -> confirm)

Do not treat fix-forward as "run runner, rerun runner". It is a bounded subroutine:

1) Plan: run `gate-fixer` to emit `FIX_FORWARD_PLAN_V1` (report-only)
2) Execute: if eligible, run `fix-forward-runner` to execute the plan (runner-bounded; no git side effects)
3) If changes were made, update Build receipt (build-cleanup) and run secrets-sanitizer (rescan the new staged surface)
4) Confirm: rerun `receipt-checker`, then rerun `gate-fixer` once

#### Worklist Loop Template (producer → fix lane → confirm)

1) Run the producer (`mutation-auditor` / `fuzz-triager` / `flakiness-detector`)
2) If it returns `recommended_action: RERUN` or a worklist that routes to an agent:
   - call the routed agent once (`test-author` / `code-implementer` / `fixer`)
3) Confirm once: rerun the producer one time to verify the top items moved.
4) If still UNVERIFIED, proceed with blockers unless the producer says another pass will help and the fix lane can actually address it.

### TodoWrite (copy exactly)
- [ ] run-prep
- [ ] repo-operator (ensure `run/<run-id>` branch)
- [ ] receipt-checker
- [ ] contract-enforcer / security-scanner / coverage-enforcer (parallel)
- [ ] gate-fixer (report + fix-forward plan)
- [ ] fix-forward-runner (if eligible; execute `FIX_FORWARD_PLAN_V1`; confirm via rerun `receipt-checker` + `gate-fixer`)
- [ ] traceability-auditor
- [ ] risk-analyst
- [ ] policy-analyst
- [ ] merge-decider
- [ ] gate-cleanup
- [ ] secrets-sanitizer (capture Gate Result block)
- [ ] repo-operator (checkpoint; allowlist interlock + no-op handling)
- [ ] gh-issue-manager (skip only if github_ops_allowed: false or gh unauth; FULL/RESTRICTED from gates + publish_surface)
- [ ] gh-reporter (skip only if github_ops_allowed: false or gh unauth; FULL/RESTRICTED from gates + publish_surface)


Use explore agents to answer any immediate questions you have and then create the todo list and call the agents.
