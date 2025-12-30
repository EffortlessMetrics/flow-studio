---

description: Run Flow 7 (Prod -> Wisdom): analyze artifacts, detect regressions, extract learnings, close feedback loops.

---



# Flow 7: Prod -> Wisdom



You are orchestrating Flow 7 of the SDLC swarm.



## Working Directory + Paths (Invariant)



- All commands run from **repo root**.

- All paths in this doc are **repo-root-relative**.

- Run artifacts live under: `.runs/<run-id>/`

- Flow artifacts live under: `.runs/<run-id>/wisdom/`

- Do **not** rely on `cd` into any folder to make relative paths work.



**Important**: Step 0 (run-prep) establishes the run directory and ensures `.runs/<run-id>/wisdom/` exists.



#### Artifact visibility rule



* Do **not** attempt to prove files exist under `.runs/<run-id>/` **before** `signal-run-prep` / `run-prep`.

* If `.runs/` is not directly readable in the current tool context, **do not conclude artifacts are missing**. Proceed with the flow and rely on the flows verification agents (e.g., `receipt-checker` in Gate) to obtain evidence from committed state when necessary.

* Preflight in flow docs is **policy**, not mechanics. Mechanics live in agents.



## Your Goals

**Primary focus:** Wisdom is a **retrospective factory**. You call specialized analysts, synthesize their findings, and surface learnings to humans.

**The questions you're answering:**
- **Solution Fit:** Did we solve the right problem? (→ `solution-analyst`)
- **Code Quality:** How healthy is the code we just shipped? (→ `quality-analyst`)
- **Maintainability:** Will this code be easy to work with? (→ `maintainability-analyst`)
- **Friction:** Where did the swarm hit walls? (→ `friction_log.md`)
- **Process:** Did we build it efficiently? (→ `process-analyst`)
- **Regressions:** Did we break anything? (→ `regression-analyst`)
- **Patterns:** Are we seeing the same issues across runs? (→ `pattern-analyst`)
- **Signal Quality:** Which feedback sources were accurate? (→ `signal-quality-analyst`)
- **Timeline:** How long did this take? Where did we stall? (→ `flow-historian` with DevLT)
- **Learning:** What should we do differently next time? (→ `learning-synthesizer`)

**You are a manager, not an analyst.** Call the analysts, collect their reports, and synthesize. Don't do the analysis yourself.

**Fix-forward authority:** Wisdom can fix minor nits (typos, leftover console.logs, stale comments) discovered during retrospective. These become a checkpoint commit before the final seal. If the fixes are substantial enough, consider a follow-up PR.



## Before You Begin (Required)



### Two State Machines



Flow 7 uses **two complementary state machines**:



1. **TodoWrite** = session navigation (keeps the orchestrator on track during this run)

2. **`flow_plan.md`** = durable on-disk state (enables reruns, handoffs, inspection)



### Setup Steps



1. Use Claude Code's **TodoWrite** tool to create a TODO list of **major stations**.

   - Track at the behavioral/station level, NOT per agent call.



2. Mirror the same list into `.runs/<run-id>/wisdom/flow_plan.md` as checkboxes.

   - As each station completes: mark TodoWrite done AND tick the checkbox.



### Suggested TodoWrite Items



```
- run-prep (establish run infrastructure)
- repo-operator (ensure run branch)
- artifact-auditor (verify artifacts)
- solution-analyst (requirement/implementation alignment)
- quality-analyst (code health/complexity)
- maintainability-analyst (naming, modularity, DRY, coupling)
- process-analyst (flow efficiency, iterations, bounces)
- regression-analyst (analyze regressions)
- pattern-analyst (cross-run patterns)
- signal-quality-analyst (feedback accuracy)
- flow-historian (build history + DevLT)
- learning-synthesizer (synthesize learnings)
- feedback-applier (draft actions only; no gh issue create before secrets gate)
- traceability-auditor (run-level coherence + spec traceability)
- risk-analyst (compare predicted vs actual)
- wisdom-cleanup (finalize receipt; update index; update `flow_plan.md`)
- secrets-sanitizer (publish gate; capture Gate Result block)
- repo-operator (checkpoint commit; allowlist interlock)
- gh-issue-manager (update issue board; gated)
- gh-reporter (report learnings; gated)
```



### On Rerun



If running `/flow-7-wisdom` on an existing run-id:

- Read `.runs/<run-id>/wisdom/flow_plan.md`

- Create TodoWrite from the checklist

- Pre-mark items done if artifacts exist and look current

- Run remaining stations to refine



This flow uses **flow artifacts and git/GitHub**. No external observability platform required.



**For production extensions** (metrics, logs, traces, incidents, SLOs): extend this flow with your observability platform.



## Subagents to use



**Infrastructure (Step 0)**:

- **run-prep** -- MUST be called first to establish the run directory and `.runs/<run-id>/wisdom/`



Domain agents (Flow 7):

- artifact-auditor

- solution-analyst

- quality-analyst

- maintainability-analyst

- process-analyst

- regression-analyst

- pattern-analyst

- signal-quality-analyst

- flow-historian

- learning-synthesizer

- feedback-applier

- traceability-auditor



Cross-cutting agents:

- risk-analyst



Cleanup + Reporting (End of Flow):

- wisdom-cleanup -- writes wisdom_receipt.json, updates index.json status

- secrets-sanitizer -- publish gate (returns Gate Result block)

- repo-operator -- checkpoint commit (gated on Gate Result + anomaly check)

- gh-issue-manager -- updates issue body status board (final update)

- gh-reporter -- posts mini-postmortem summary



## Upstream Inputs



Read from all prior flow directories (if available):

- `.runs/<run-id>/signal/signal_receipt.json`

- `.runs/<run-id>/plan/plan_receipt.json`

- `.runs/<run-id>/build/build_receipt.json`

- `.runs/<run-id>/gate/gate_receipt.json`

- `.runs/<run-id>/deploy/deploy_receipt.json`



**If upstream artifacts are missing**: Flow 7 can start without all prior flows. Proceed best-effort: analyze what's available, document gaps, set status to UNVERIFIED, and continue.



## Orchestration outline



This is a **linear pipeline**. The sanitizer scans before checkpoint — rescans are allowed if new changes are staged, but no reseal loop (don't regenerate receipts after sanitizer runs).



### Step 0: Establish Run Infrastructure



**Call `run-prep` first.**



This agent will:

- Derive or confirm the `<run-id>` from context, branch name, or user input

- Create `.runs/<run-id>/wisdom/` directory structure

- Update `.runs/<run-id>/run_meta.json` with "wisdom" in `flows_started`

- Update `.runs/index.json`



After this step, you will have a confirmed run directory. All subsequent agents write to `.runs/<run-id>/wisdom/`.



### Step 0b: Ensure Run Branch



**Call `repo-operator`** with task: "ensure run branch `run/<run-id>`"



The agent handles branch creation/switching safely. This keeps checkpoint commits off main.



### Step 1: Initialize Flow Plan



Create or update `.runs/<run-id>/wisdom/flow_plan.md`:



```markdown

# Flow 7: Wisdom for <run-id>



## Planned Steps

- [ ] run-prep (establish run directory)
- [ ] repo-operator (ensure run branch)
- [ ] artifact-auditor (verify all flow artifacts)
- [ ] solution-analyst (requirement/implementation alignment)
- [ ] quality-analyst (code health/complexity)
- [ ] maintainability-analyst (naming, modularity, DRY, coupling)
- [ ] process-analyst (flow efficiency, iterations, bounces)
- [ ] regression-analyst (analyze test/coverage regressions)
- [ ] pattern-analyst (cross-run patterns)
- [ ] signal-quality-analyst (feedback accuracy)
- [ ] flow-historian (build timeline + DevLT)
- [ ] learning-synthesizer (extract learnings)
- [ ] feedback-applier (draft actions; no gh issue create before secrets gate)
- [ ] traceability-auditor (run-level coherence + spec traceability)
- [ ] risk-analyst (compare predicted vs actual)
- [ ] wisdom-cleanup (write receipt, update index)
- [ ] secrets-sanitizer (capture Gate Result block)
- [ ] repo-operator (checkpoint commit with allowlist interlock)
- [ ] gh-issue-manager (update issue board)
- [ ] gh-reporter (post summary)


## Progress Notes



<Update as each step completes>

```



### Step 2: Artifact Audit

**Call `artifact-auditor`** — verifies all expected flow artifacts exist.

### Step 3: Solution Analysis

**Call `solution-analyst`** — traces requirements → BDD → implementation → tests. Verifies we built the right thing.

### Step 4: Quality Analysis

**Call `quality-analyst`** — analyzes code health, complexity of the changed files.

### Step 5: Maintainability Analysis

**Call `maintainability-analyst`** — deep dive on naming, modularity, DRY, coupling, documentation, test quality.

### Step 6: Process Analysis + Friction Log

**Call `process-analyst`** — analyzes flow efficiency: iterations, bounces, stalls, where we could improve.

The process-analyst also writes `.runs/<run-id>/wisdom/friction_log.md`:
- Where the swarm hit walls (stuck loops, CANNOT_PROCEED states)
- Context exhaustion events (PARTIAL exits)
- Tool/environment failures
- Unclear prompts or missing context that caused rerun loops
- Agent capabilities that were missing or underperforming

This friction log informs pack improvements—the "Staff Engineer" whispers in the ear of the next run.

### Step 7: Regression Analysis

**Call `regression-analyst`** — checks for test regressions, coverage changes, stability issues.

### Step 8: Pattern Analysis

**Call `pattern-analyst`** — looks across historical runs to find recurring issues, repeated failures, and trends.

### Step 9: Signal Quality Analysis

**Call `signal-quality-analyst`** — analyzes accuracy of feedback sources (CI, bots, humans). Tracks which signals were valid vs noise.

### Step 10: Timeline + DevLT

**Call `flow-historian`** — compiles the run timeline and calculates Developer Lead Time (DevLT): how much human attention did this run actually require?

### Step 11: Synthesize Learnings

**Call `learning-synthesizer`** — extracts patterns from the analysis: what worked, what didn't, what to do differently.

### Step 12: Apply Feedback

**Call `feedback-applier`** — turns learnings into concrete actions. Does NOT create GitHub issues directly.

**Audience-Segmented Outputs:**

Wisdom learnings are only valuable if they reach the right consumer:

| Output | Audience | Content |
|--------|----------|---------|
| `pack_improvements.md` | **Pack (Machine)** | Ready-to-apply diffs for agent prompts, flow docs, skills |
| `codebase_wisdom.md` | **Repo (Human)** | Structural hotspots, brittle patterns, architectural observations |
| `feedback_actions.md` | **Project (Both)** | Issue drafts, doc suggestions, follow-up work items |
| `.runs/_wisdom/latest.md` | **Future (Scent Trail)** | Top learnings that inform the next run's researcher |

**The Scent Trail:** `.runs/_wisdom/latest.md` is a special file that persists across runs. It captures the top 3-5 learnings from this run that should inform future runs. The `gh-researcher` reads this file before starting research, closing the learning loop.

**Wisdom Produces Edits, Not Advice:**

When Flow 7 identifies pack/flow improvements (from friction log, process analysis, or pattern analysis):
- `feedback-applier` should produce **suggested diffs** to agent prompts, not just prose advice
- Example: If `bdd-critic` keeps missing edge cases, propose a specific edit to `.claude/agents/bdd-critic.md` with the new guidance
- The diff goes in `.runs/<run-id>/wisdom/pack_improvements.md` as fenced code blocks
- Humans review and apply the diffs (or reject them)

This is the "Staff Engineer whisper" — concrete improvements to the factory, not vague recommendations.

**Pack improvement output format:**
```markdown
## Pack Improvement: <title>

**Pattern observed:** <what friction/failure was seen>
**Evidence:** <which runs, which agents, which artifacts>
**Suggested edit:**

File: `.claude/agents/<agent>.md`
```diff
- <old line>
+ <new line>
```

**Risk:** <Low/Medium/High>
**Rationale:** <why this fix addresses the pattern>
```

### Step 12b: Traceability

**Call `traceability-auditor`** — verifies run identity, receipts, and GitHub markers are coherent.

### Step 12c: Risk Comparison

**Call `risk-analyst`** — compares predicted risks (from Signal) vs actual outcomes.



### Step 13: Finalize and Write Receipt

- `wisdom-cleanup` -> `.runs/<run-id>/wisdom/wisdom_receipt.json`, `.runs/<run-id>/wisdom/cleanup_report.md`

- Verifies all required artifacts exist

- Computes counts mechanically (never estimates)

- Updates `.runs/index.json` with status, last_flow, updated_at

- This is the final receipt for the run



### Step 14: Sanitize Secrets (Publish Gate)

- `secrets-sanitizer` -> `.runs/<run-id>/wisdom/secrets_scan.md`, `.runs/<run-id>/wisdom/secrets_status.json`

- Scans all wisdom artifacts before posting

- **Returns a Gate Result block**  this is the control plane for routing decisions



**Status vs flags:**

- `status` is descriptive (CLEAN/FIXED/BLOCKED_PUBLISH)

- `safe_to_commit` / `safe_to_publish` are authoritative



**Control plane:** Route on the **Gate Result block** returned by `secrets-sanitizer`. `secrets_status.json` is audit-only (optional last-mile verification).



**Gate Result block (returned by secrets-sanitizer):**

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
- If `safe_to_commit: true` → proceed to checkpoint commit (Step 14b)
- If `safe_to_commit: false`:
  - `blocker_kind: MECHANICAL` → **FIX_ENV** (tool/IO failure)
  - `blocker_kind: SECRET_IN_CODE` → route to appropriate agent (orchestrator decides)
  - `blocker_kind: SECRET_IN_ARTIFACT` → investigate manually
- Push requires: `safe_to_publish: true` AND Repo Operator Result `proceed_to_github_ops: true`
- GitHub reporting ops still run in RESTRICTED mode when publish is blocked or `publish_surface: NOT_PUSHED`



### Step 14b: Checkpoint Commit



Checkpoint the audit trail **before** any GitHub operations.



**Call `repo-operator`** with checkpoint mode. The agent:

1. Resets staging and stages only the allowlist (not `git add .`)

2. Enforces the allowlist/anomaly interlock mechanically

3. Writes `.runs/<run-id>/wisdom/git_status.md` if anomaly detected

4. Handles no-op (nothing staged) gracefullyno empty commits



**Allowlist for Flow 7:**

- `.runs/<run-id>/wisdom/`

- `.runs/<run-id>/run_meta.json`

- `.runs/index.json`



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



**Anomaly detection:** If anything outside allowlist is dirty (modified/staged/untracked):

- **Anomaly detected**  commit allowlist only

- Set `proceed_to_github_ops: false`

- Write `.runs/<run-id>/wisdom/git_status.md` documenting unexpected paths

- Flow completes locally **UNVERIFIED**



**Gating logic (from prior secrets-sanitizer Gate Result + repo-operator result):**

- If `safe_to_commit: false` (from Gate Result): skip commit entirely

- If anomaly detected: `repo-operator` commits allowlist only, skips push, returns `proceed_to_github_ops: false`

- If `safe_to_publish: true` AND no anomaly: `repo-operator` pushes the branch, returns `proceed_to_github_ops: true`

- If `safe_to_publish: false`:

  - If `needs_upstream_fix: true` → **BOUNCE** (Navigator determines routing from handoff summary + pointer to `secrets_scan.md`)

  - If `status: BLOCKED_PUBLISH` → **CANNOT_PROCEED** (mechanical failure); stop and require human intervention

  - Otherwise → UNVERIFIED; skip push (`publish_surface: NOT_PUSHED`). Continue with GitHub Reporting Ops in RESTRICTED mode when access allows.



### Step 15-16: GitHub Reporting (Final)

**Call `gh-issue-manager`** (marks run complete) then **`gh-reporter`** (mini-postmortem).

See `CLAUDE.md` → **GitHub Access + Content Mode** for gating rules. Quick reference:
- Skip if `github_ops_allowed: false` or `gh` unauthenticated
- Content mode is derived from secrets gate + push surface (not workspace hygiene)
- Issue-first: flow summaries go to the issue, never the PR

**Quality-first reporting (mandatory priority order):** The GitHub postmortem should lead with:
1. **Solution Verdict** — Did we solve the right problem? (from `solution-analyst`)
2. **Asset Health** — Complexity/maintainability score (from `quality-analyst`, `maintainability-analyst`)
3. **Sad Path Coverage** — Were negative scenarios tested? (from `solution-analyst`)
4. **Quality Summary** — Code health assessment

DevLT and process metrics go in a **"Process Metrics" fold** at the bottom. We want humans to see the quality assessment first, not just how fast we worked.

**Why quality leads:** We optimize for **Asset Value** first, **Efficiency** second. A run that took 72 hours but produced verified, maintainable code is better than a 2-hour run that produced untested spaghetti.

**Content for postmortem:** Quality/solution verdicts, learnings, pack/flow observations, feedback actions, meta-notes on the wisdom synthesis.

### Step 17: Finalize Flow



Update `flow_plan.md`:

- Mark all steps as complete

- Add final summary section:



```markdown

## Summary



- **Final Status**: VERIFIED | UNVERIFIED

- **Regressions Found**: <count>

- **Learnings Extracted**: <count>

- **Feedback Actions Created**: <count>

- **Run Complete**: This run-id is now closed



## Human Review Checklist



- [ ] `.runs/<run-id>/wisdom/learnings.md` - Are learnings actionable?

- [ ] `.runs/<run-id>/wisdom/feedback_actions.md` - Which actions should be prioritized?

- [ ] `.runs/<run-id>/wisdom/regression_report.md` - Are regressions understood?

```



## Closed Feedback Loops



Flow 7 closes the SDLC loop by feeding learnings back (recommendations, not direct calls):



### -> Flow 1 (Signal)

- `learning-synthesizer` extracts problem patterns

- `feedback-applier` suggests updates to requirement templates

- Builds institutional memory of "problems that recur"



### -> Flow 2 (Plan)

- `feedback-applier` suggests architecture doc updates

- Documents patterns that worked/failed

- Improves design templates and ADR prompts



### -> Flow 3 (Build)

- `feedback-applier` drafts GitHub issues for test gaps (for human review)

- Links regression failures to coverage gaps

- Suggests test pattern improvements
- If Build produced hardening worklists (e.g., `build/mutation_report.md`, `build/fuzz_report.md`, `build/flakiness_report.md`), promote the top items into `feedback_actions.md` as issue drafts (with evidence pointers).



These are **recommendations in artifacts**, not direct flow invocations. Humans decide which to act on.



## Expected Outputs



When complete, `.runs/<run-id>/wisdom/` should contain:



- `flow_plan.md` - execution plan and progress

- `artifact_audit.md` - structural sanity check of all flows

- `solution_analysis.md` - requirement/implementation alignment

- `quality_report.md` - code health, complexity

- `maintainability_analysis.md` - naming, modularity, DRY, coupling deep dive

- `process_analysis.md` - flow efficiency, iterations, bounces

- `friction_log.md` - where the swarm hit walls (for pack improvement)

- `regression_report.md` - what got worse and where

- `pattern_report.md` - cross-run recurring issues and trends

- `signal_quality_report.md` - feedback source accuracy analysis

- `flow_history.json` - timeline linking all flow events + DevLT metrics

- `learnings.md` - narrative lessons extracted

- `feedback_actions.md` - concrete follow-ups (issues, doc updates)

- `pack_improvements.md` - suggested diffs to pack/agent prompts (from feedback-applier)
- `codebase_wisdom.md` - structural insights for humans: hotspots, brittle patterns, architectural observations (from feedback-applier)

- `risk_assessment.md` - risk perspective (optional, if risk-analyst invoked)

- `wisdom_receipt.json` - final receipt for the run

- `cleanup_report.md` - cleanup status and evidence

- `secrets_scan.md` - secrets scan report

- `secrets_status.json` - publish gate status

- `git_status.md` - repo state at checkpoint (if anomaly detected)

- `gh_issue_status.md` - issue board update status

- `gh_report_status.md` - GitHub posting status

- `github_report.md` - report content (local copy)



## Completion States



Flow 7 agents report:



- **VERIFIED**: `blockers` empty, `missing_required` empty, and analysis complete with all artifacts processed. Set `recommended_action: PROCEED`.

- **UNVERIFIED**: `blockers` non-empty OR `missing_required` non-empty OR some data unavailable (GitHub, git, etc.) OR anomaly detected during checkpoint. Set `recommended_action: RERUN | BOUNCE` depending on fix location.

- **CANNOT_PROCEED**: IO/permissions/tool failure only (exceptional); cannot read files, tool missing, etc. Set `missing_required` with paths and `recommended_action: FIX_ENV`.



**Key rule**: CANNOT_PROCEED is strictly for mechanical failures. Missing upstream artifacts are UNVERIFIED with `missing_required` populated, not CANNOT_PROCEED.



Any of these are valid outcomes. Document concerns and continue.



## Stable Marker Contract (for mechanical counting)



Flow 7 producers must use these stable markers so `wisdom-cleanup` can derive counts mechanically:



| Agent | Marker Pattern | Artifact | Example |

|-------|----------------|----------|---------|

| solution-analyst | `^### SOL-[0-9]{3}:` | solution_analysis.md | `### SOL-001: Missing OAuth implementation` |

| quality-analyst | `^- QUALITY_ISSUE_` | quality_report.md | `- QUALITY_ISSUE_HIGH: 3` |

| maintainability-analyst | `^- \*\*MAINT-[0-9]{3}\*\*:` | maintainability_analysis.md | `- **MAINT-001**: Auth handler too large` |

| process-analyst | `^### PROC-[0-9]{3}:` | process_analysis.md | `### PROC-001: AC-002 took 4 iterations` |

| regression-analyst | `^### REG-[0-9]{3}:` | regression_report.md | `### REG-001: test_foo::bar  assertion failed` |

| pattern-analyst | `^### PAT-[0-9]{3}:` | pattern_report.md | `### PAT-001: Flaky auth tests` |

| signal-quality-analyst | `^### SQ-FP-[0-9]{3}:` | signal_quality_report.md | `### SQ-FP-001: FB-RC-123456789` |

| learning-synthesizer | `^## Learning: ` | learnings.md | `## Learning: Requirements` |

| feedback-applier | `^- ISSUE: ` | feedback_actions.md | `- ISSUE: Missing tests for REQ-004` |

| flow-historian | `"devlt":` | flow_history.json | `"devlt": {"total_run_minutes": 45, "human_attention_minutes": 8}` |



**Regression format rule:** Each regression MUST have exactly one `### REG-NNN:` heading section. (You may also include a register table, but headings are the source for counting.)



**Why this matters:** Without stable markers, `wisdom-cleanup` cannot derive counts mechanically and must set them to `null` with reasons. Agents that omit markers degrade receipt quality.



---



## Orchestrator Kickoff


### Station order

1. `run-prep`

2. `repo-operator` (ensure run branch)

3. `artifact-auditor`

4. `solution-analyst`

5. `quality-analyst`

6. `maintainability-analyst`

7. `process-analyst`

8. `regression-analyst`

9. `pattern-analyst`

10. `signal-quality-analyst`

11. `flow-historian`

12. `learning-synthesizer`

13. `feedback-applier`

14. `traceability-auditor`

15. `risk-analyst`

16. `wisdom-cleanup`

17. `secrets-sanitizer`

18. `repo-operator` (checkpoint commit)

19. `gh-issue-manager` (if allowed)

20. `gh-reporter` (if allowed)

### TodoWrite (copy exactly)

- [ ] run-prep
- [ ] repo-operator (ensure `run/<run-id>` branch)
- [ ] artifact-auditor
- [ ] solution-analyst (requirement/implementation alignment)
- [ ] quality-analyst (code health/complexity)
- [ ] maintainability-analyst (naming, modularity, DRY, coupling)
- [ ] process-analyst (flow efficiency, iterations, bounces)
- [ ] regression-analyst (test/coverage regressions)
- [ ] pattern-analyst (cross-run patterns)
- [ ] signal-quality-analyst (feedback accuracy)
- [ ] flow-historian (timeline + DevLT)
- [ ] learning-synthesizer
- [ ] feedback-applier (draft actions only; no gh issue create before secrets gate)
- [ ] traceability-auditor (run-level coherence + spec traceability)
- [ ] risk-analyst
- [ ] wisdom-cleanup
- [ ] secrets-sanitizer (capture Gate Result block)
- [ ] repo-operator (checkpoint commit; allowlist interlock + no-op handling)
- [ ] gh-issue-manager (skip only if github_ops_allowed: false or gh unauth; FULL/RESTRICTED from gates + publish_surface)
- [ ] gh-reporter (skip only if github_ops_allowed: false or gh unauth; FULL/RESTRICTED from gates + publish_surface)

Use explore agents to answer any immediate questions you have and then create the todo list and call the agents.
