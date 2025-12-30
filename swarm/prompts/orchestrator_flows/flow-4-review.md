---
description: "Run Flow 4 (Review): harvest PR feedback, apply fixes, flip Draft to Ready when complete."
---

# Flow 4: PR Review + Improvement

You are orchestrating Flow 4 of the SDLC swarm.

## The Mental Model: "The Finishing School"

Flow 3 built the house. Flow 4 does the punch list.

**Mentality:** Feedback is noisy, time is linear, code rots instantly. Grab what's available, fix it, report it, move on. Don't wait for perfect signal.

**Three Phases:**
1. **Harvest & Cluster** — Pull all feedback, cluster into actionable Work Items
2. **Execute** — Route Work Items to agents, fix what's current, skip what's stale
3. **Close the Loop** — Update the PR, show humans what was addressed

**Key principle:** Agents are smart. They read the file, see if the code is there, fix it or report "context changed." No separate stale-check ceremony.

## Working Directory + Paths (Invariant)

- All commands run from **repo root**.
- All paths in this doc are **repo-root-relative**.
- Run artifacts live under: `.runs/<run-id>/`
- Flow artifacts live under: `.runs/<run-id>/review/`
- Do **not** rely on `cd` into any folder to make relative paths work.

**Important**: Setup (run-prep) establishes the run directory and ensures `.runs/<run-id>/review/` exists.

#### Artifact visibility rule

* Do **not** attempt to prove files exist under `.runs/<run-id>/` **before** `signal-run-prep` / `run-prep`.
* If `.runs/` is not directly readable in the current tool context, **do not conclude artifacts are missing**. Proceed with the flow and rely on verification agents to obtain evidence from committed state when necessary.
* Preflight in flow docs is **policy**, not mechanics. Mechanics live in agents.

## Your Goals

- Ensure a PR exists (create Draft if missing)
- Harvest all available PR feedback (grab partials from CI if already failing)
- Convert feedback into clustered Work Items (by file/theme, not individual comments)
- Apply fixes until completion (agents handle staleness naturally)
- Flip Draft PR to Ready when review is complete
- Post a closure checklist so humans see feedback was addressed

## Before You Begin (Required)

### Two State Machines

Flow 4 uses **two complementary state machines**:

1. **TodoWrite** = session navigation (keeps the orchestrator on track during this run)
2. **`flow_plan.md`** = durable on-disk state (enables reruns, handoffs, inspection)

### Setup Steps

1. Use Claude Code's **TodoWrite** tool to create a TODO list of **major stations**.
   - Track at the behavioral/station level, NOT per agent call.
   - The worklist loop is ONE todo (unbounded iterations).

2. Mirror the same list into `.runs/<run-id>/review/flow_plan.md` as checkboxes.
   - As each station completes: mark TodoWrite done AND tick the checkbox.

### Suggested TodoWrite Items

```
- run-prep (establish run infrastructure)
- repo-operator (ensure run branch)
- pr-creator (create Draft PR if none exists)
- pr-feedback-harvester (pull all bot/human feedback)
- review-worklist-writer (cluster into actionable items)
- worklist loop (unbounded: resolve items until completion/context/unrecoverable)
- pr-commenter (post/update PR summary comment)
- pr-status-manager (flip Draft to Ready if review complete)
- review-cleanup (finalize receipt; update index; update flow_plan.md)
- secrets-sanitizer (publish gate)
- repo-operator (commit/push)
- gh-issue-manager (update issue board; gated)
- gh-reporter (report to GitHub; gated)
```

### On Rerun

If running `/flow-4-review` on an existing run-id:
- Read `.runs/<run-id>/review/flow_plan.md`
- Read `.runs/<run-id>/review/review_worklist.json` for current item statuses
- Create TodoWrite from the checklist
- Pre-mark items done if artifacts exist and look current
- Resume the worklist loop from pending items

If you encounter missing PR or unclear state, **document it and continue**. Create the PR if possible.

## Subagents to use

**Infrastructure (Step 0)**:
- **run-prep** -- establish the run directory and `.runs/<run-id>/review/`

**Git operations (cross-cutting)**:
- repo-operator -- branch at start, commit at end

**PR lifecycle**:
- pr-creator -- create Draft PR if none exists
- pr-feedback-harvester -- read all PR feedback sources
- review-worklist-writer -- convert feedback to actionable worklist
- pr-commenter -- post idempotent PR summary comment (after worklist loop)
- pr-status-manager -- flip Draft to Ready when review complete

**Fix loop agents (reused from Build)**:
- test-author -- fix test-related items
- code-implementer -- fix code-related items
- doc-writer -- fix documentation items
- fixer -- apply targeted fixes
- test-executor -- verify fixes

**Polish and wrap-up**:
- build-cleanup -- reseal build receipt after code changes
- review-cleanup -- write review_receipt.json, update index

**Cleanup + Reporting (End of Flow)**:
- secrets-sanitizer -- publish gate
- repo-operator -- commit/push (gated on secrets)
- gh-issue-manager -- update issue board
- gh-reporter -- post summary to GitHub

## Upstream Inputs

Read from `.runs/<run-id>/build/` (if available):
- `build_receipt.json`
- `pr_creation_status.md`

Read from `.runs/<run-id>/run_meta.json`:
- `pr_number` (from pr-creator in Flow 3)
- `issue_number`
- `github_repo`

**If PR does not exist**: Call `pr-creator` to create a Draft PR first.

**If upstream artifacts are missing**: Flow 4 can start without Flows 1-3. Proceed best-effort: document assumptions, set status to UNVERIFIED, and continue.

## Artifact Outputs

| Artifact | Producer | Description |
|----------|----------|-------------|
| `flow_plan.md` | Orchestrator | Flow progress tracking |
| `pr_feedback.md` | pr-feedback-harvester | Summarized bot + human feedback |
| `pr_feedback_raw.json` | pr-feedback-harvester | Raw API responses (optional) |
| `review_worklist.md` | review-worklist-writer | Actionable items with stable markers |
| `review_worklist.json` | review-worklist-writer | Machine-readable worklist |
| `review_actions.md` | Orchestrator | Cumulative log of changes made |
| `style_sweep.md` | Orchestrator | Style sweep result (NOOP if no pending MINOR Markdown items) |
| `cleanup_report.md` | review-cleanup | Cleanup summary |
| `review_receipt.json` | review-cleanup | Machine-readable receipt |
| `secrets_scan.md` | secrets-sanitizer | Secrets scan findings |
| `secrets_status.json` | secrets-sanitizer | Gate status (audit record) |
| `git_status.md` | repo-operator | Anomaly documentation (if detected) |
| `gh_issue_status.md` | gh-issue-manager | Issue operation status |
| `github_report.md` | gh-reporter | Local copy of GitHub post |
| `gh_report_status.md` | gh-reporter | GitHub posting status |

All artifacts live under `.runs/<run-id>/review/`.

## Orchestration Outline

Flow 4 follows the 3-phase model with setup and seal bookends:

```
[Setup] → [Phase 1: Harvest & Cluster] → [Phase 2: Execute] → [Phase 3: Close] → [Seal]
```

---

### Setup: Infrastructure

**run-prep** → **repo-operator** (branch) → **pr-creator** (if needed)

1. **Call `run-prep`** to establish `.runs/<run-id>/review/`
2. **Call `repo-operator`** with task: "ensure run branch `run/<run-id>`"
3. **Call `pr-creator`** to ensure a Draft PR exists

After setup, you have a run directory and a PR to harvest feedback from.

---

### Phase 1: Harvest & Cluster

**pr-feedback-harvester** → **review-worklist-writer**

**Call `pr-feedback-harvester`:**
- Grabs all available feedback (bots, humans, CI)
- Grabs partial CI failures if jobs are still running but already failing
- Doesn't wait for pending checks
- **Non-blocking:** Returns immediately with what's available. CI latency is handled by re-harvest during checkpoints, not by waiting.

**Call `review-worklist-writer`:**
- Clusters feedback into Work Items (by file/theme, not individual comments)
- 50 comments → 5-10 Work Items
- Items get stable `RW-NNN` IDs
- Markdown nits grouped into single `RW-MD-SWEEP`
- **Owns worklist state:** Workers report naturally what they did. This agent parses responses and updates `review_worklist.json`. The worker's job is to fix code; this agent's job is to track status.

**Route on worklist:** If no items, proceed to Close. Otherwise, enter Execute loop.

**Non-Blocking Principle:** Push. Immediately Harvest. If new blockers appear, add to list. If not, **keep working on the existing list.** Don't stall waiting for bots to think. Drain the known queue first.

---

### Phase 2: Execute (Unbounded Loop)

**The core of Flow 4: iteratively resolve Work Items.**

**This is an explicit agent call chain, not a narrative algorithm.**

**The Worklist Microloop:**

```
while pending > 0 and not exhausted:
    1. review-worklist-writer (mode: create or refresh)
       → returns: pending_blocking, stuck_signal, next_batch (IDs + route_to + batch_hint)

    2. Route next_batch to fix-lane agent:
       - TESTS → test-author
       - CORRECTNESS → code-implementer
       - STYLE → fixer
       - DOCS → doc-writer

       Agent receives: batch IDs + file paths + evidence
       Agent reports naturally: what it fixed, what was stale, what it couldn't fix

    3. review-worklist-writer (mode: apply)
       → Receives: worker's natural language response + batch_ids
       → Parses response to determine per-item status
       → Updates review_worklist.json
       → Appends to review_actions.md
       → Returns updated pending count + next_batch

    4. Periodically: Checkpoint Routine (explicit agent chain)
       a. repo-operator (stage intended changes)
       b. secrets-sanitizer (gate staged surface; capture Gate Result)
       c. repo-operator (commit/push; gated on Gate Result)
       d. pr-feedback-harvester (re-harvest CI/bot status)
       e. review-worklist-writer (mode: refresh; may add new items)
       → If stuck_signal: true → exit loop
```

**Key principle:** The orchestrator does NOT read `review_worklist.json` directly. It calls `review-worklist-writer` which reads the JSON, picks the batch, and returns routing info. After the fix-lane agent works, it calls `review-worklist-writer` in apply mode to parse the worker's response and update state.

**Handling Design Feedback (Law 7: Local Resolution):**

If a reviewer flags a fundamental design issue (not just a code fix):
1. **Call `design-optioneer`** to analyze the feedback against the current code and ADR
2. **If the analysis suggests a scoped fix:** Call `code-implementer` to apply it
3. **Verification:** Run `test-executor` to confirm no regressions
4. **Report back:** "Resolved design concern [RW-NNN] with surgical refactor; verified with tests."

**Write-Through Requirement:** When `design-optioneer` resolves a design snag, it MUST use the Edit tool to update the relevant plan artifact (`adr.md`, `ac_matrix.md`, or `work_plan.md`) immediately. This ensures the resolution survives context resets and is visible to subsequent agents.

**Only escalate to Flow 2** if the design feedback invalidates the entire architecture.

**Workers report naturally:** Fix-lane agents (code-implementer, fixer, test-author, doc-writer) do their job and describe what happened. They don't need special output formats. The `review-worklist-writer` parses their natural language response to update item statuses.

**Checkpoint Routine:** Sanitizer gates the **staged surface**. Always stage before scan. The re-harvest immediately captures bot feedback on the new push.

**Exit conditions:**
- `pending == 0` → complete
- Context exhausted → PARTIAL (checkpoint, rerun to continue)
- `stuck_signal: true` → PARTIAL (human may need to intervene)

**Style Sweep:** If `RW-MD-SWEEP` is pending, call `fixer` once to apply all markdown fixes in one pass.

---

### Phase 3: Close the Loop

**pr-commenter** → **pr-status-manager**

**Call `pr-commenter`:**
- Posts resolved items checklist (closure signal)
- Shows what was fixed, skipped, or pending
- Idempotent (updates existing comment)

**Call `pr-status-manager`:**
- If review complete: flip Draft → Ready for Review
- If incomplete: keep Draft, document remaining items

---

### Seal: Receipt + Publish

**review-cleanup** → **secrets-sanitizer** → **repo-operator** → **gh-issue-manager** → **gh-reporter**

1. **`review-cleanup`** — Write `review_receipt.json`, update index
2. **`secrets-sanitizer`** — Publish gate (returns Gate Result)
3. **`repo-operator`** — Commit/push (gated on secrets + hygiene)
4. **`gh-issue-manager`** + **`gh-reporter`** — Update issue (if allowed)

**Gate Result semantics:**
- `safe_to_commit: false` → skip commit
- `safe_to_publish: false` → commit locally, skip push
- `proceed_to_github_ops: false` → skip GitHub updates

---

### flow_plan.md Template

```markdown
# Flow 4: Review for <run-id>

## Agents (explicit checklist)

- [ ] run-prep
- [ ] repo-operator (ensure run branch)
- [ ] pr-creator (create Draft PR if needed)
- [ ] pr-feedback-harvester
- [ ] review-worklist-writer
- [ ] worklist loop (unbounded)
- [ ] pr-commenter
- [ ] pr-status-manager
- [ ] review-cleanup
- [ ] secrets-sanitizer
- [ ] repo-operator (commit/push)
- [ ] gh-issue-manager
- [ ] gh-reporter

## Worklist Progress

| Item | Category | Severity | Status |
|------|----------|----------|--------|
| (populated by worklist loop) |

## Summary

- **Final Status**: VERIFIED | PARTIAL | UNVERIFIED
- **Worklist Items**: <resolved>/<total> resolved
- **PR State**: draft | ready
- **Next Flow**: `/flow-5-gate`
```

**Important:** Do NOT use phase checkboxes ("Setup", "Harvest & Cluster", etc.). Use the explicit agent checklist above. Phases are explanatory prose, not TodoWrite items.

## Status States

Agents report one of:
- **VERIFIED**: All critical items resolved, review complete.
- **UNVERIFIED**: Items still pending or incomplete feedback.
- **CANNOT_PROCEED**: IO/permissions/tool failure only.

## Review Completion Criteria

Flow 4 is VERIFIED when:
- All CRITICAL worklist items are resolved
- All MAJOR worklist items are resolved (or explicitly deferred with reason)
- CI checks are passing
- No blocking review requests

MINOR and INFO items may remain pending without blocking.

---

## Orchestrator Kickoff

### Station Order (5 groups)

```
SETUP          run-prep → repo-operator (branch) → pr-creator
HARVEST        pr-feedback-harvester → review-worklist-writer
EXECUTE        worklist loop (unbounded)
CLOSE          pr-commenter → pr-status-manager
SEAL           review-cleanup → secrets-sanitizer → repo-operator → gh-issue-manager → gh-reporter
```

### Execute Loop (Detailed)

**Entry:** `review_worklist.json` exists with pending items

**This is an explicit agent call chain. The orchestrator routes on returned fields, not by parsing JSON.**

**Loop:**
```
1) Call review-worklist-writer (mode: refresh)
   → Returns: pending_blocking, stuck_signal, next_batch

2) If pending_blocking == 0: exit (complete)
3) If context exhausted: checkpoint and exit (PARTIAL)
4) If stuck_signal: true: checkpoint and exit (PARTIAL)

5) Style Sweep (if next_batch contains `RW-MD-SWEEP`):
   - Call fixer once for all markdown fixes
   - fixer reports naturally what it fixed

6) Route next_batch to fix-lane agent:
   - TESTS → test-author
   - CORRECTNESS → code-implementer
   - STYLE → fixer
   - DOCS → doc-writer

   Agent behavior:
   - Receives: batch IDs + file paths + evidence
   - Reports naturally: what it fixed, what was stale, what needs escalation

7) Call review-worklist-writer (mode: apply)
   → Receives: worker's natural language response + batch_ids
   → Parses response to determine per-item status
   → Updates review_worklist.json
   → Appends to review_actions.md (agent handles this, not orchestrator)
   → Returns: updated pending count, next_batch

8) Periodically: Checkpoint Routine (explicit agent chain)
   a) repo-operator (stage intended changes)
   b) secrets-sanitizer (gate staged surface)
   c) repo-operator (commit/push; gated on Gate Result)
   d) pr-feedback-harvester (re-harvest)
   e) review-worklist-writer (mode: refresh; may add new items)
   → If stuck_signal: true → exit loop
```

**Checkpoint Routine:** Sanitizer gates the **staged surface**. Stage first, then scan. Every push must be gated.

**Exit conditions:**
- `pending_blocking == 0` (all resolved) → VERIFIED
- Context exhausted → PARTIAL
- `stuck_signal: true` → PARTIAL
- Unrecoverable blocker → UNVERIFIED

### TodoWrite (copy exactly)

**These are the agents you call, in order. Do not group. Do not summarize. Execute each line.**

```
- [ ] run-prep
- [ ] repo-operator (ensure run branch `run/<run-id>`)
- [ ] pr-creator (create Draft PR if needed)
- [ ] pr-feedback-harvester
- [ ] review-worklist-writer
- [ ] worklist loop (unbounded: resolve items until completion/context/unrecoverable)
- [ ] pr-commenter (post/update PR summary comment)
- [ ] pr-status-manager (flip Draft to Ready if review complete)
- [ ] review-cleanup
- [ ] secrets-sanitizer (capture Gate Result block)
- [ ] repo-operator (commit/push; return Repo Operator Result)
- [ ] gh-issue-manager (skip only if github_ops_allowed: false or gh unauth)
- [ ] gh-reporter (skip only if github_ops_allowed: false or gh unauth)
```

**Why explicit?** The orchestrator (you) executes what's in the list. Grouped phases get skipped. Explicit agents get called.

Use explore agents to answer any immediate questions you have and then create the todo list and call the agents.

