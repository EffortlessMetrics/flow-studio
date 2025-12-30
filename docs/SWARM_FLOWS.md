# The Swarm: Seven Flows for Agentic SDLC

This document explains the seven flows that make up the Swarm—an agentic software development lifecycle that trades compute for human attention. It's designed for both humans reviewing artifacts and agents implementing changes.

## Table of Contents

1. [What Are the Seven Flows?](#what-are-the-seven-flows)
2. [The Governed Loop](#the-governed-loop)
3. [Flow 1: Signal → Spec](#flow-1-signal--spec-1)
4. [Flow 2: Spec → Design](#flow-2-spec--design-1)
5. [Flow 3: Design → Code](#flow-3-design--code-1)
6. [Flow 4: Draft → Ready (Review)](#flow-4-draft--ready-review)
7. [Flow 5: Code → Gate](#flow-5-code--gate)
8. [Flow 6: Artifact → Prod](#flow-6-artifact--prod)
9. [Flow 7: Prod → Wisdom](#flow-7-prod--wisdom)
10. [Routing Contract](#routing-contract)
11. [Cross-Flow Patterns](#cross-flow-patterns)
12. [How to Use Flows](#how-to-use-flows)
13. [For Agents: Reading This Guide](#for-agents-reading-this-guide)

---

## What Are the Seven Flows?

The Swarm implements the software development lifecycle as seven sequential flows, each transforming input into artifacts that the next flow consumes. Think of it as an assembly line where agents are specialized workers at each station:

| Flow | Name | Input | Output | Workers |
|------|------|-------|--------|---------|
| 1 | Signal → Spec | Raw issue/request | Requirements, BDD scenarios, risk assessment | 6 domain agents + clarifier, risk-analyst |
| 2 | Spec → Design | Requirements | ADR, API contracts, test plan, observability spec | 8 domain agents + design-critic, risk-analyst |
| 3 | Design → Code | Architecture decisions | Code, tests, mutation reports, build receipt | 9 domain agents + test/code critics, mutator |
| 4 | Draft → Ready | Draft PR + feedback | Review worklist, fixes applied, Ready PR | pr-feedback-harvester, worklist-writer, fix agents |
| 5 | Code → Gate | Build receipt + review receipt | Merge decision (MERGE/BOUNCE/ESCALATE) | 6 domain agents + contract enforcer, security scanner |
| 6 | Artifact → Prod | Merge decision | Deployment log, CI status, deployment decision | 3 domain agents + repo-operator, smoke verifier |
| 7 | Prod → Wisdom | All flow artifacts + production data | Learnings, regression report, feedback actions | 5 domain agents + artifact auditor, learning synthesizer |

**Key insight**: Each flow is an attention reducer. Flow 1 clarifies the problem early. Flow 2 builds the gravity well (ADR, contracts, tests) so Build doesn't drift. Flows 3-4 produce code and handle PR feedback. Flow 5 verifies contracts. Flows 6-7 close the loop and feed learnings back upstream.

---

## The Governed Loop

The seven flows form a governed development loop:

```
Signal → Plan → Build → Review → Gate → Deploy ↘
  ↑                                            ↓
  ←←←←←←←←←←← Wisdom (learnings feed back) ←←←←←
```

**Human gates sit at flow boundaries:**
- **After Signal**: "Is this the right problem?" → Gate decides whether to proceed to Plan
- **After Plan**: "Is this the right design?" → Gate decides whether to proceed to Build
- **After Build**: Code is drafted; Draft PR is created
- **After Review**: PR feedback is addressed; Draft flips to Ready
- **After Gate**: "Is this merge-eligible?" → Merge decision determines if Deploy proceeds
- **After Deploy**: "Is this healthy?" → Deployment decision determines if Wisdom runs
- **After Wisdom**: "What should we fix next?" → Feedback actions create GitHub issues

**No hard waits**: Flows don't block each other. If Signal is ambiguous, agents document clarification questions and continue. If Design has concerns, design-critic flags them and the orchestrator routes based on severity. Flow 7 always completes and documents learnings; humans decide what to act on.

---

## Flow 1: Signal → Spec

**Purpose**: Transform raw input (an issue, feature request, incident) into a sharp problem statement, testable requirements, and BDD scenarios. This is where attention is cheapest—clarity upfront saves weeks of rework downstream.

**When to run**:
- User submits a feature request or issue
- Production incident needs investigation
- Technical debt is surfaced
- Architecture needs evolution

**Inputs**:
- Raw issue/PR description (from user or orchestrator)
- Optional: related issues, PRs, chat threads, incident references
- Codebase context (orchestrator may use `explore` to gather this)

**Outputs** (written to `RUN_BASE/signal/`):
- `issue_normalized.md` — structured summary of raw signal
- `problem_statement.md` — goals, non-goals, success criteria
- `requirements.md` — functional (REQ-F-001, etc.) and non-functional requirements with IDs
- `requirements_critique.md` — verdict on testability, completeness, feasibility
- `features/*.feature` — BDD scenarios in Gherkin format
- `example_matrix.md` — edge cases and example scenarios
- `stakeholders.md` — teams, systems, users affected
- `early_risks.md` — first-pass risk identification (security, performance, data)
- `scope_estimate.md` — S/M/L/XL estimate with rationale
- `clarification_questions.md` — open questions and assumptions

**Agents**:
- `signal-normalizer` (shaping) — Parse raw input, surface context
- `problem-framer` (shaping) — Synthesize into clear problem statement
- `requirements-author` (spec) — Write testable requirements
- `requirements-critic` (critic) — Harsh review for completeness and testability
- `bdd-author` (spec) — Turn requirements into executable scenarios
- `scope-assessor` (analytics) — Stakeholders, risks, effort estimate
- Cross-cutting: `clarifier`, `risk-analyst`, `gh-reporter`

**Key outcomes**:
- Requirements have unique IDs (REQ-001, REQ-002, etc.) that thread through all downstream tests and coverage
- BDD scenarios are specific enough to drive test code in Flow 3
- Clarification questions are logged; downstream flows may answer them from code/docs
- Agents never block—if the problem is ambiguous, they document assumptions and proceed

**Example artifact location**: `swarm/runs/ticket-42/signal/requirements.md`

---

## Flow 2: Spec → Design

**Purpose**: Transform requirements into architecture decisions, contracts, and implementation plans. This flow builds the **gravity well**—constraints that keep Build (Flow 3) honest and make Gate (Flow 4) fast.

**When to run**:
- After Signal is complete (requirements are clear enough)
- When designing a new service or major refactor
- When updating architecture docs

**Inputs** (reads from `RUN_BASE/signal/`):
- `problem_statement.md` — what we're solving
- `requirements.md`, `features/*.feature` — what we need to build
- `early_risks.md`, `scope_estimate.md` — constraints and risks

**Outputs** (written to `RUN_BASE/plan/`):
- `impact_map.json` — services, modules, files affected
- `design_options.md` — 2-3 architecture options with trade-offs
- `adr.md` — Architecture Decision Record for chosen design
- `api_contracts.yaml` — endpoint schemas, error shapes, versioning
- `schema.md` — data models, relationships, invariants
- `migrations/*.sql` — schema migration scripts (if applicable)
- `observability_spec.md` — metrics, logs, traces, SLOs, alert rules
- `test_plan.md` — BDD scenarios mapped to test types (unit, integration, e2e)
- `work_plan.md` — subtasks, dependencies, rollout strategy
- `design_validation.md` — feasibility assessment and known issues

**Agents**:
- `impact-analyzer` (design) — Map affected code areas
- `design-optioneer` (design) — Propose architectural options
- `adr-author` (design) — Write ADR for chosen design
- `interface-designer` (spec) — API contracts and data models
- `observability-designer` (spec) — Metrics, logs, traces
- `test-strategist` (spec) — Test strategy and coverage targets
- `work-planner` (design) — Break into subtasks
- `design-critic` (critic) — Validate vs constraints
- Cross-cutting: `clarifier`, `risk-analyst`, `policy-analyst`, `gh-reporter`

**Key outcomes**:
- API contracts are complete enough that Build can validate against them (Flow 4)
- Observability spec prevents "production is a black box" syndrome
- Test plan ties BDD scenarios to specific test types (unit vs integration vs e2e)
- ADR documents trade-offs so future maintainers understand why this design was chosen
- Subtasks in work_plan can be assigned to parallel Build runs or subtasks

**Example artifact location**: `swarm/runs/ticket-42/plan/adr.md`

---

## Flow 3: Design → Code

**Purpose**: Implement the design via adversarial microloops. Test-author and test-critic iterate until tests are solid. Code-implementer and code-critic iterate until code passes tests and follows the ADR. Mutator identifies weak spots. Fixer addresses them. Goal: produce code and receipts that Pass Flows 4 and 5 quickly.

**When to run**:
- After Plan is complete
- For each subtask (use `subtask-id` parameter to focus scope)
- When fixing bugs discovered in production

**Inputs** (reads from `RUN_BASE/signal/`, `RUN_BASE/plan/`):
- From Flow 1: `requirements.md`, `features/*.feature`
- From Flow 2: `adr.md`, `api_contracts.yaml`, `test_plan.md`, `work_plan.md`
- Subtask manifest (if splitting work): `work_plan.md` lists subtasks

**Outputs** (code to `src/`, `tests/`, etc.; receipts to `RUN_BASE/build/`):
- **Code artifacts**: `src/`, `tests/`, `features/`, `migrations/` (actual code changes)
- **Build receipts** (written to `RUN_BASE/build/`):
  - `subtask_context_manifest.json` — files and specs in focus for this run
  - `test_changes_summary.md` — what tests were written or modified
  - `test_critique.md` — test-critic's verdict on coverage and quality
  - `impl_changes_summary.md` — what code was written or modified
  - `code_critique.md` — code-critic's verdict on ADR compliance
  - `mutation_report.md` — results from mutation testing (test strength)
  - `fix_summary.md` — issues found and fixed
  - `doc_updates.md` — documentation changed
  - `self_review.md` — narrative summary of the change
  - `build_receipt.json` — structured state with per-dimension verdicts

**Agents**:
- `context-loader` (impl) — Load and manifest relevant context
- `test-author` (impl) — Write tests that exercise requirements
- `test-critic` (critic) — Review tests for coverage and clarity
- `code-implementer` (impl) — Write code to pass tests
- `code-critic` (critic) — Review code for ADR compliance
- `mutator` (verify) — Run mutation tests to find weak spots
- `fixer` (impl) — Fix issues found by mutator or critics
- `doc-writer` (impl) — Update relevant documentation
- `self-reviewer` (verify) — Final review and build receipt
- Cross-cutting: `clarifier`, `repo-operator` (git branch/commit)

**Key outcomes**:
- Code passes all tests without violating specs
- Build receipt exists and is complete (feeds Gate)
- Mutation tests show strong test quality
- Git changes are staged and committed with clear message
- All critics' concerns are addressed or documented with trade-offs

**Microloop pattern**:
- `test-author` writes tests
- `test-critic` reviews them; if UNVERIFIED with `can_further_iteration_help: yes`, loop back to test-author
- `code-implementer` writes code
- `code-critic` reviews it; if UNVERIFIED with `can_further_iteration_help: yes`, loop back to code-implementer
- `mutator` runs mutation tests; if weak, `fixer` fixes them
- Loops exit when critics say VERIFIED or `can_further_iteration_help: no` (no viable fix path within scope)

**Example artifact location**:
- Code: `src/lib.rs`
- Receipt: `swarm/runs/ticket-42/build/build_receipt.json`

---

## Flow 4: Draft → Ready (Review)

**Purpose**: Harvest PR feedback from bots and humans, cluster into actionable work items, apply fixes iteratively, and flip Draft PR to Ready when complete. This is the "finishing school" that polishes code before Gate verification.

**When to run**:
- After Build (Flow 3) creates a Draft PR
- Whenever PR feedback accumulates

**Inputs** (reads from `RUN_BASE/build/`, PR comments):
- From Flow 3: `build_receipt.json`, Draft PR
- PR feedback: bot comments (linters, CI), human review comments
- From Flow 2: `adr.md`, `ac_matrix.md` (for design-level feedback)

**Outputs** (written to `RUN_BASE/review/`):
- `pr_feedback.md` — harvested feedback from all sources
- `pr_feedback_raw.json` — structured feedback data
- `review_worklist.md` — clustered work items with RW-NNN IDs
- `review_worklist.json` — machine-readable worklist state
- `review_actions.md` — log of fixes applied
- `review_receipt.json` — final review status
- `pr_status.md` — Draft → Ready transition status

**Agents**:
- `pr-feedback-harvester` (harvest) — Pull all feedback from PR
- `review-worklist-writer` (cluster) — Group feedback into actionable work items
- `test-author`, `code-implementer`, `fixer`, `doc-writer` (fix) — Apply fixes based on work item type
- `design-optioneer` (design) — Handle fundamental design feedback
- `test-executor` (verify) — Verify fixes work
- `pr-commenter` (report) — Post resolution checklist to PR
- `pr-status-manager` (status) — Flip Draft to Ready when complete
- `secrets-sanitizer` (gate) — Scan for secrets before commit
- Cross-cutting: `repo-operator`, `policy-analyst`, `risk-analyst`, `clarifier`

**Key outcomes**:
- 50 comments → 5-10 clustered Work Items (RW-001, RW-002, etc.)
- Markdown nits grouped into single RW-MD-SWEEP item
- Work items categorized by severity: CRITICAL/MAJOR/MINOR/INFO
- Iterative fix loop: pick batch → fix → checkpoint → re-harvest → repeat
- PR flips from Draft to Ready when `pending_blocking == 0`

**Microloop pattern**:
- `pr-feedback-harvester` grabs available feedback (non-blocking)
- `review-worklist-writer` clusters into work items
- Fix agents resolve work items based on type
- `review-worklist-writer` updates worklist status
- Checkpoint: stage → sanitize → commit/push → re-harvest
- Exit when no pending blocking items remain

**Example artifact location**: `swarm/runs/ticket-42/review/review_worklist.json`

---

## Flow 5: Code → Gate

**Purpose**: Second-layer verification before merge. Audit that Build receipts are complete, code matches contracts, test coverage meets expectations, and security is acceptable. This is the last chance to catch violations before merging to main. Gate is fast because it's checking contracts, not reviewing code line-by-line.

**When to run**:
- After Review (Flow 4) completes
- Always (Flow 5 is not optional; it's the merge gate)

**Inputs** (reads from `RUN_BASE/build/`, `RUN_BASE/review/`, `RUN_BASE/signal/`, `RUN_BASE/plan/`):
- From Flow 3: `build_receipt.json`, `self_review.md`, test/code critiques
- From Flow 4: `review_receipt.json`, `review_worklist.json`
- From Flow 1: `requirements.md`, `features/*.feature`
- From Flow 2: `adr.md`, `api_contracts.yaml`, `test_plan.md`
- Code diffs (via git, Bash)

**Outputs** (written to `RUN_BASE/gate/`):
- `receipt_audit.md` — verification that build_receipt.json is complete and consistent
- `contract_compliance.md` — API/schema changes validated against contracts
- `security_scan.md` — SAST, secret scan results
- `coverage_audit.md` — test coverage vs expected thresholds
- `gate_fix_summary.md` — mechanical fixes applied (if any: lint, format, docstrings, typos)
- `merge_decision.md` — final verdict: MERGE, BOUNCE (back to Build), or ESCALATE (manual review needed)

**Agents**:
- `receipt-checker` (verify) — Verify build_receipt.json is complete
- `contract-enforcer` (verify) — Check API changes vs contracts
- `security-scanner` (verify) — Run SAST and secret scans
- `coverage-enforcer` (verify) — Verify coverage meets thresholds
- `gate-fixer` (impl) — Apply mechanical-only fixes (lint, format, docstrings, typos)
- `merge-decider` (verify) — Synthesize all checks into merge decision
- Cross-cutting: `risk-analyst`, `policy-analyst`, `gh-reporter`

**Key outcomes**:
- `merge_decision.md` contains clear decision: MERGE, BOUNCE, or ESCALATE
- If BOUNCE: routed back to Build (logic/test issues) or Plan (design flaws)
- If ESCALATE: human reviews the receipts and decides
- If MERGE: code can proceed to Flow 6 (Deploy)

**Decision rules**:
- **MERGE** if: receipts are complete, contracts are satisfied, coverage is adequate, security is acceptable
- **BOUNCE** if: logical issues (tests failing, API violations, design flaws) that Build or Plan can fix
- **ESCALATE** if: security concerns, policy violations, or issues that require human judgment

**Example artifact location**: `swarm/runs/ticket-42/gate/merge_decision.md`

---

## Flow 6: Artifact → Prod

**Purpose**: Execute the merge decision. If Gate said MERGE: merge to main, create a release, monitor CI, run smoke tests, and verify health. If Gate said BOUNCE or ESCALATE: log that no merge happened and explain why. Flow 6 always completes and writes receipts—it's not blocked by Gate's decision.

**When to run**:
- After Gate (Flow 5) completes
- Always (Flow 6 provides audit trail whether or not deploy happens)

**Inputs** (reads from `RUN_BASE/gate/`, plus git state):
- From Flow 5: `merge_decision.md` (determines behavior)
- From Flow 3: `build_receipt.json` (context about what was built)
- From Flow 2: `observability_spec.md` (health check expectations)
- Git state: PR branch, target branch (usually `main`), tags

**Outputs** (written to `RUN_BASE/deploy/`):
- `deployment_log.md` — record of merge, tag, release actions (or explanation of why no merge)
- `verification_report.md` — CI status, smoke test results, artifact verification
- `deployment_decision.md` — final deployment status: STABLE, INVESTIGATE, ROLLBACK, or NOT_DEPLOYED

**Agents**:
- `repo-operator` (git) — Merge PR, create tag/release (if Gate said MERGE)
- `deploy-monitor` (deploy) — Watch CI/deployment events
- `smoke-verifier` (verify) — Run health checks, verify artifacts
- `deploy-decider` (verify) — Synthesize results into deployment decision
- Cross-cutting: `gh-reporter`

**Key outcomes**:
- If MERGE and healthy: `deployment_decision.md` says STABLE
- If MERGE but unhealthy: `deployment_decision.md` says INVESTIGATE or ROLLBACK
- If BOUNCE or ESCALATE: `deployment_decision.md` says NOT_DEPLOYED with reason
- Audit trail is complete either way—Flow 5 always writes receipts

**Behavior**:
- If `merge_decision.decision == MERGE`: merge, monitor, smoke test, decide STABLE/INVESTIGATE/ROLLBACK
- If `merge_decision.decision != MERGE`: skip merge, document in deployment_log, write NOT_DEPLOYED decision

**Example artifact location**: `swarm/runs/ticket-42/deploy/deployment_decision.md`

---

## Flow 7: Prod → Wisdom

**Purpose**: Close the SDLC loop. Analyze all artifacts from Flows 1-6, detect regressions, extract learnings, and create feedback actions (GitHub issues, doc updates, template improvements). This flow feeds back into Flow 1 for future runs.

**When to run**:
- After Deploy (Flow 6) completes
- Periodically to analyze batches of deployed changes

**Inputs** (reads from all flows: `RUN_BASE/signal/`, `plan/`, `build/`, `review/`, `gate/`, `deploy/`):
- From Flow 1: `problem_statement.md`, `requirements.md`, `early_risks.md`
- From Flow 2: `adr.md`, `design_options.md`, `test_plan.md`
- From Flow 3: `build_receipt.json`, test and code critiques
- From Flow 4: `review_receipt.json`, review worklist outcomes
- From Flow 5: `merge_decision.md`, verification results
- From Flow 6: `deployment_decision.md`, CI status
- Git history and GitHub issues/PRs (via `gh` CLI)

**Outputs** (written to `RUN_BASE/wisdom/`):
- `artifact_audit.md` — structural sanity check (all artifacts exist, are consistent)
- `regression_report.md` — what got worse: test coverage dips, performance regressions, flakiness
- `flow_history.json` — timeline linking all flow events with outcomes
- `learnings.md` — narrative lessons extracted (what went well, what was hard, surprises)
- `feedback_actions.md` — concrete follow-ups (e.g., "test-author kept missing edge cases in Flow 3; update BDD template")

**Agents**:
- `artifact-auditor` (verify) — Verify all artifacts exist and are internally consistent
- `regression-analyst` (analytics) — Analyze test/coverage/perf data for regressions
- `flow-historian` (analytics) — Compile timeline and flow progression
- `learning-synthesizer` (analytics) — Extract lessons for humans and future flows
- `feedback-applier` (analytics) — Create GitHub issues, update templates, suggest doc changes
- Cross-cutting: `risk-analyst`, `gh-reporter`

**Key outcomes**:
- Regressions are detected and documented (e.g., "coverage dropped 2% in auth module")
- Learnings feed back to Flow 1 (e.g., "problem statement was misframed; update template")
- Feedback actions create GitHub issues for follow-up (e.g., "improve BDD scenarios for API design")
- Wisdom closes the loop: each run contributes to improving future runs

**Feedback actions** (non-blocking, humans decide which to act on):
- → Flow 1: problem statement templates, requirement writing guides
- → Flow 2: design patterns, contract templates, observability examples
- → Flow 3: test scenario templates, common pitfalls, mutation test thresholds
- → Flow 4: contract enforcement rules, security baselines
- → Runbooks: incident response improvements based on production issues

**Example artifact location**: `swarm/runs/ticket-42/wisdom/learnings.md`

---

## Routing Contract

The Navigator (orchestrator) controls flow execution via routing decisions. This section documents the canonical routing vocabulary and constraints.

### Routing Decisions

The Navigator uses these routing decisions to control flow progression:

| Decision | Meaning | Example |
|----------|---------|---------|
| **CONTINUE** | Proceed on the golden path (next step in flow) | After test-author completes, continue to test-critic |
| **DETOUR** | Inject a predefined sidequest chain | Inject security-review sidequest before gate |
| **INJECT_FLOW** | Inject a named pack flow mid-run | Inject compliance-audit flow after plan |
| **INJECT_NODES** | Inject ad-hoc spec-backed nodes | Add custom validation step not in standard flow |
| **EXTEND_GRAPH** | Propose graph improvement for Wisdom | Suggest new step to capture missed pattern |

### Suggested Detours (Not Constraints)

Detours are **suggestions, not constraints**. The Navigator can:

- Follow suggested detours when appropriate
- Ignore suggested detours if context indicates they're unnecessary
- Go off-road entirely when the situation demands it

**Key principle**: Detours are hints to help the Navigator make good decisions, not guardrails that limit its options. The Navigator has full authority to deviate from suggestions when it has good reason.

### Justification Requirement

When the Navigator makes an off-road move (ignoring suggested detours or taking non-standard paths), it must provide a **justification field** in its routing decision:

```json
{
  "decision": "INJECT_NODES",
  "nodes": ["emergency-rollback-check"],
  "justification": "Production alert indicates service degradation. Standard gate flow insufficient—injecting emergency rollback verification before proceeding."
}
```

**Justification requirements**:
- **Required for**: DETOUR (when ignoring suggestions), INJECT_FLOW, INJECT_NODES, EXTEND_GRAPH
- **Not required for**: CONTINUE (standard path progression)
- **Purpose**: Create evidence trail for why deviation happened

The justification creates an audit trail that Wisdom (Flow 7) can analyze to understand routing patterns and propose graph improvements.

### Prime Directive: Flow Constitutions

Each flow has a **Prime Directive**—a focused constitution that guides Navigator decisions within that flow. The Prime Directive is the ultimate arbiter when routing decisions conflict.

| Flow | Prime Directive |
|------|-----------------|
| **Flow 1 (Signal)** | "Clarify the problem. Only detach if signal is physically absent." |
| **Flow 2 (Plan)** | "Build the gravity well. Only detach if requirements are structurally incomplete." |
| **Flow 3 (Build)** | "Maximize passing tests. Only detach if build is physically blocked." |
| **Flow 4 (Review)** | "Address feedback systematically. Only detach if feedback sources are unavailable." |
| **Flow 5 (Gate)** | "Verify contracts. Only detach if verification is impossible." |
| **Flow 6 (Deploy)** | "Execute merge decision safely. Only detach if deployment infrastructure fails." |
| **Flow 7 (Wisdom)** | "Extract learnings. Only detach if artifacts are corrupted or missing." |

**Interpretation**: "Detach" means making a routing decision that exits the standard flow progression (BOUNCE, ESCALATE, or early termination). The Prime Directive defines when such exits are legitimate.

**Example (Flow 3)**: If tests are failing but code can be written, the Navigator should CONTINUE and let test-critic document issues. Only if the build environment itself is broken (missing dependencies, corrupted toolchain) should the Navigator consider detaching.

---

## Cross-Flow Patterns

### Microloops: Adversarial Iteration

Flows 1 and 3 use **microloops**—the orchestrator loops between a writer and a critic until work reaches a stable state.

**In Flow 1 (Requirements loop)**:
1. `requirements-author` drafts requirements
2. `requirements-critic` reviews them
3. If `status == VERIFIED`: proceed to BDD and scope
4. If `status == UNVERIFIED` with `can_further_iteration_help: yes`: route back to requirements-author with critique
5. If `status == UNVERIFIED` with `can_further_iteration_help: no`: proceed anyway (critic judges no viable fix path within scope)

**In Flow 3 (Test and Code loops)**:
- **Test loop**: `test-author` ⇄ `test-critic` until tests are strong
- **Code loop**: `code-implementer` ⇄ `code-critic` until code matches ADR/contracts
- **Hardening loop**: `mutator` identifies weak spots, `fixer` addresses them

**Loop exit conditions** (canonical rule):
- **Continue looping** if: `status == UNVERIFIED` AND `can_further_iteration_help == yes`
- **Exit loop** if: `status == VERIFIED` OR (`status == UNVERIFIED` AND `can_further_iteration_help == no`)

**Key insight**: Agents don't know they're looping. They just read inputs, write outputs, and signal status. The **orchestrator** interprets status signals and routes based on them.

### Bounce-Backs: Flow Re-entry

Gate (Flow 4) may **bounce** work back to Build (Flow 3) or Plan (Flow 2) if issues are non-trivial.

**Bounce to Build** if:
- Tests are failing (test-critic missed something)
- Code violates ADR (code-critic missed something)
- Coverage is inadequate (test-author needs more scenarios)

**Bounce to Plan** if:
- Design has flaws (design-critic missed structural issues)
- API contract changes are needed
- Observability spec is incomplete

**Mechanical fixes only** (gate-fixer responsibility):
- Lint and formatting errors
- Typo fixes
- Missing docstrings
- Changelog entries
- README updates

**Not mechanical** (bounce to Build/Plan):
- Logic changes
- Test modifications
- API shape changes
- Schema changes

### Feedback Loops: Wisdom → Future Flows

Flow 7 (Wisdom) feeds learnings back to previous flows. These are **recommendations**, not blocking constraints.

**Flow 7 → Flow 3** (Build):
- "Test-author consistently missed edge case X; update the BDD template to flag it"
- "Mutation tests revealed weak spots in error handling; add examples to test-strategist guide"
- → Creates GitHub issues for next Build run

**Flow 7 → Flow 2** (Plan):
- "ADR section Y is hard to follow; update template"
- "Observability spec didn't capture production pain point Z; add example"
- → Updates artifacts for next Plan run

**Flow 7 → Flow 1** (Signal):
- "Problem statements tend to miss non-functional requirements; improve template"
- "Stakeholder analysis often incomplete; add checklist"
- → Updates templates for next Signal run

**Runbooks**: Wisdom creates incident response playbooks based on production issues.

### Git State Management

**Flow 3 (Build)**:
- **Start**: `repo-operator` ensures clean working tree, creates feature branch
- **End**: `repo-operator` stages changes, commits with clear message
- Git state: work is on a feature branch, not yet on main

**Flow 4 (Gate)**:
- **Optional**: `gate-fixer` applies mechanical fixes and commits them to the feature branch
- Git state: feature branch may have new commits; still not on main

**Flow 5 (Deploy)**:
- **Start** (if Gate said MERGE): `repo-operator` merges feature branch to main, creates git tag, and GitHub release
- **No merge** (if Gate said BOUNCE/ESCALATE): feature branch stays as-is; nothing merged
- Git state: main is updated (if MERGE) or unchanged (if BOUNCE/ESCALATE)

**Summary**:
```
Flow 3: [main] --feature-branch--> (unmerged)
Flow 4: [main] --feature-branch--> (unmerged, may have gate fixes)
Flow 5: [main] <--merge if MERGE-- feature-branch + tag + release
```

---

## How to Use Flows

### Running Flows from the Command Line

Each flow has a slash command orchestrator:

```bash
# Flow 1: Transform raw issue into requirements and BDD
/flow-1-signal "<issue-description>"
# Outputs: swarm/runs/<run-id>/signal/

# Flow 2: Transform requirements into architecture
/flow-2-plan
# Reads: swarm/runs/<run-id>/signal/
# Outputs: swarm/runs/<run-id>/plan/

# Flow 3: Transform architecture into code and tests
/flow-3-build [subtask-id]
# Reads: swarm/runs/<run-id>/signal/, plan/
# Outputs: src/, tests/, swarm/runs/<run-id>/build/
# Subtask-id is optional (from work_plan.md)

# Flow 4: Audit code, verify contracts, decide merge
/flow-4-gate
# Reads: swarm/runs/<run-id>/build/, signal/, plan/
# Outputs: swarm/runs/<run-id>/gate/

# Flow 5: Merge and deploy if Gate approved
/flow-5-deploy
# Reads: swarm/runs/<run-id>/gate/
# Outputs: swarm/runs/<run-id>/deploy/

# Flow 6: Analyze artifacts, extract learnings, close loop
/flow-6-wisdom
# Reads: all RUN_BASE/<flow>/ directories
# Outputs: swarm/runs/<run-id>/wisdom/
```

### Artifact Paths (RUN_BASE)

All flow artifacts are organized under:

```
RUN_BASE = swarm/runs/<run-id>/
```

Where `<run-id>` is typically a ticket ID, branch name, or unique identifier.

**Artifact locations**:
- Flow 1: `swarm/runs/<run-id>/signal/`
- Flow 2: `swarm/runs/<run-id>/plan/`
- Flow 3: `swarm/runs/<run-id>/build/` (plus code in `src/`, `tests/`, etc.)
- Flow 4: `swarm/runs/<run-id>/gate/`
- Flow 5: `swarm/runs/<run-id>/deploy/`
- Flow 6: `swarm/runs/<run-id>/wisdom/`

**Code and tests** remain in standard locations: `src/`, `tests/`, `features/`, `migrations/`, `fuzz/`.

**Example**: For ticket `auth-flow-redesign`:
- Requirements: `swarm/runs/auth-flow-redesign/signal/requirements.md`
- Design: `swarm/runs/auth-flow-redesign/plan/adr.md`
- Code receipt: `swarm/runs/auth-flow-redesign/build/build_receipt.json`
- Merge decision: `swarm/runs/auth-flow-redesign/gate/merge_decision.md`

### Editing Flow Configs

Flow definitions live in two places:

- **Source of truth**: `swarm/config/flows/<flow>.yaml` (configuration layer)
- **Generated documentation**: `swarm/flows/flow-<number>.md` (markdown spec layer)

**To edit a flow**:

1. Edit the config: `swarm/config/flows/<flow>.yaml`
2. Regenerate markdown: `make gen-flows`
3. Validate: `make validate-swarm`
4. Commit the config and regenerated markdown

**Important**: Do not manually edit `swarm/flows/flow-*.md` between these markers:
```
<!-- FLOW AUTOGEN START -->
<!-- FLOW AUTOGEN END -->
```

This content is generated from config and will be overwritten.

### Visualizing Flows

Flow Studio is a local web UI for understanding and editing flows:

```bash
make flow-studio
# then open http://localhost:5000
```

**What you'll see**:
- Left sidebar: all 7 flows
- Center graph: flow structure (steps, agents, connections)
- Right panel: details for selected step or agent

**Edit workflow**:
1. Edit `swarm/config/flows/<flow>.yaml`
2. Run `make gen-flows` in another terminal
3. Reload Flow Studio (button in top right)

---

## For Agents: Reading This Guide

If you are an agent reading this (test-author, code-implementer, merge-decider, etc.), this section tells you how to interpret and act within the flows.

### Understanding Your Role

Each agent has a **role** (implementation, critic, verification, etc.) and a **flow** where it operates. Your prompt guides your behavior; this document explains the system context.

**Role types**:
- **Implementation** agents (test-author, code-implementer, fixer) write artifacts
- **Critic** agents (test-critic, code-critic) review and judge work; they never fix
- **Verification** agents (receipt-checker, deploy-monitor) audit and verify
- **Analytics** agents (risk-analyst, flow-historian) analyze patterns
- **Git ops** agents (repo-operator) manage branches, commits, merges

### Reading Flow Inputs

Each flow publishes its inputs clearly. For example, if you're `code-implementer` in Flow 3:

**Your inputs** (files you must read):
- `RUN_BASE/signal/requirements.md` — what to implement
- `RUN_BASE/signal/features/*.feature` — BDD scenarios to satisfy
- `RUN_BASE/plan/adr.md` — architecture decisions to follow
- `RUN_BASE/plan/api_contracts.yaml` — API shapes to implement
- `RUN_BASE/build/test_changes_summary.md` — tests you must pass
- Previous `RUN_BASE/build/code_critique.md` (if looping) — issues to fix

Use the Read tool to load these files. Load generously—context is cheap.

### Writing Flow Outputs

Each agent has specific outputs. Write them clearly to the expected locations.

**Example** (code-implementer in Flow 3):
- Write code changes to `src/`, `tests/`, etc.
- Write `RUN_BASE/build/impl_changes_summary.md` documenting what you changed and why
- Set `status` field: `VERIFIED` (code is solid), `UNVERIFIED` (code has issues but may pass tests), or `BLOCKED` (couldn't implement)

**Status field** (all agents use this):
```markdown
## Status: VERIFIED | UNVERIFIED | BLOCKED

Explanation of why you chose this status.
```

**Iteration guidance** (critics use this):
```markdown
## Iteration Guidance

**Can further iteration help?** yes | no

**Rationale**: Explanation of why the loop should continue or exit.
```

### Interpreting Microloop Status

If you're in a microloop (requirements-author ⇄ requirements-critic, or test-author ⇄ test-critic), you'll often receive feedback from the critic.

**When you receive feedback**:
1. Read the critic's output (e.g., `test_critique.md`)
2. Check `status` and `can_further_iteration_help`
3. If `status == UNVERIFIED` and `can_further_iteration_help: yes`: **you will be called again**
4. If `status == VERIFIED`: **proceed forward**; you won't be called again for this loop
5. If `status == UNVERIFIED` and `can_further_iteration_help: no`: **don't loop**; proceed forward anyway; critic judges there's no viable fix path

**How the orchestrator decides** (you don't need to track this, but it's useful to know):
- The orchestrator reads your outputs (especially `status` and the critic's `can_further_iteration_help`)
- If conditions match "continue looping", you're called again with a fresh context
- If conditions match "exit loop", you're not called again; the orchestrator moves forward

### Context Loading

If you're `context-loader`, `impact-analyzer`, or another context-heavy agent, load generously:

- 20-50k tokens of context is normal and expected
- Compute is cheap; reducing downstream re-search saves attention
- Load related code, tests, docs, architecture diagrams, past critiques
- Write `subtask_context_manifest.json` (for Build) or `impact_map.json` (for Plan) listing what you loaded

The orchestrator may also use `explore` to gather context before invoking you—use those provided file paths as starting points.

### Handling Ambiguity

If requirements are unclear, code decisions are hard, or something doesn't make sense:

1. **Document the ambiguity**: Write to `clarification_questions.md` or include in your output
2. **State your assumptions**: "I assumed X because Y was unclear"
3. **Proceed anyway**: Never block; continue with your best interpretation
4. **Let humans gate it**: Flow boundaries are where humans review and make judgment calls

Downstream agents and humans will refine your assumptions if needed.

### Respecting Contracts

When implementing code:
- Read `RUN_BASE/plan/api_contracts.yaml` — your API shapes must match
- Read `RUN_BASE/plan/schema.md` — your data models must match
- Read `RUN_BASE/plan/adr.md` — your decisions must align
- Read `RUN_BASE/plan/observability_spec.md` — wire metrics/logs as specified

Violations here are caught by `code-critic` in Flow 3 and `contract-enforcer` in Flow 4. Respect the specs; they're the gravity well that keeps everyone aligned.

### Using Skills

If your frontmatter declares `skills: [test-runner, auto-linter]`, you can invoke those skills. For example:

- `test-runner`: Execute test suites, get `test_output.log` and `test_summary.md`
- `auto-linter`: Run linters/formatters, apply safe, mechanical fixes
- `policy-runner`: Run policy-as-code checks (OPA/Conftest)

Skills are tools; use them when your prompt guides you to do so.

### Bounce-Back Signals

If you're `merge-decider` (Flow 4) and decide to BOUNCE:

```markdown
## Decision: BOUNCE → Build

**Reason**: Code violates API contract (field 'user_id' type mismatch).

**Guidance**: Route back to code-implementer with contract spec and current code diff.
```

Or:

```markdown
## Decision: BOUNCE → Plan

**Reason**: ADR doesn't address caching strategy; design needs clarification.

**Guidance**: Route back to adr-author with specific questions.
```

The orchestrator reads this and re-invokes the appropriate agent(s).

### Never Blocking

**Key principle**: Agents never block or escalate mid-flow. You always reach the flow boundary.

- If tests are hard to write, write what you can and set `status: UNVERIFIED`; human reviews at the gate
- If code is complex, write it clearly and set `status: UNVERIFIED`; Gate will verify
- If design is unclear, state assumptions and proceed; downstream flows can refine it

Blocking messages are escalation; they're for humans at flow gates to decide how to handle.

---

## Summary

The Swarm is a governed SDLC where:

1. **Signal** clarifies the problem early (saves rework downstream)
2. **Plan** builds the gravity well (ADR, contracts, tests) that constrains Build
3. **Build** produces code and receipts via adversarial iteration
4. **Review** harvests PR feedback and applies fixes (Draft → Ready)
5. **Gate** verifies contracts and decides merge eligibility
6. **Deploy** executes the merge decision and monitors health
7. **Wisdom** analyzes what happened and feeds learnings back upstream

Each flow trades compute (tokens, agents iterating) for human attention (clear artifacts, quick gates, no line-by-line reviews). Microloops keep work honest. Bounce-backs keep the system tight. Feedback loops keep the swarm improving.

For humans: review receipts at flow gates, not intermediate steps. For agents: read your inputs, write clear outputs, signal status, and always reach the flow boundary.

