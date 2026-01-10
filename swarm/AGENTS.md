# Swarm Agent Registry

> Minimal viable swarm: 54 domain agents across 7 flows + 3 built-in infra.
> Domain agents live under `.claude/agents/*.md`.
> Built-in infra agents are native to Claude Code and have no `.claude/agents` files.

<!-- META:AGENT_COUNTS -->
**Total: 73 agents** (3 built-in + 70 domain)
<!-- /META:AGENT_COUNTS -->

---

## Orchestration Model

The swarm has **two execution levels**:

### 1. Orchestrator (top-level Claude)

- Can call **all agents**: built-in (`explore`, `plan-subagent`, `general-subagent`) and domain (`.claude/agents/*.md`)
- Interprets agent outputs (status, recommended_next) to decide routing
- Controls microloop iteration in Flows 1, 3
- May use `explore` to gather context before invoking domain agents

### 2. All Agents (built-in and domain)

- **Built-in agents** (`explore`, `plan-subagent`, `general-subagent`): provided by Claude Code, no local definition files
- **Domain agents**: defined in `.claude/agents/*.md` with frontmatter + prompt
- All agents inherit full tooling from the main Claude Code session (no `tools:` restriction)
- Behavior is constrained by prompts, not tool denial—prompts specify what agents may/must not do
- All agents use Skills when declared in frontmatter
- All agents read inputs from files, write outputs to files

### Current Implementation Constraint

Due to Claude Code limitations, **domain agents currently cannot call other agents** (including built-ins). This is a runtime constraint, not a design requirement. If agent→agent calls become available, the swarm would work fine with them—the orchestrator would simply have more delegation options.

For now: agents are pure tool-users. Only the orchestrator coordinates multiple agents.

---

## Agent Philosophy

- **Agents never block**: Document concerns in receipts and continue.
- **Critics never fix**: Critics write harsh receipts; implementers apply fixes.
- **Multi-path completion**: Report VERIFIED/UNVERIFIED/BLOCKED states, not fake success.

---

## All Agents

| Key | Flows | Role Family | Color | Source | Short Role |
|-----|-------|-------------|-------|--------|------------|
| explore | all | infra | cyan | built-in | Fast Haiku read-only search (Glob/Grep/Read/Bash). |
| plan-subagent | plan | infra | cyan | built-in | High-level repo analyzer for complex architecture. |
| general-subagent | (implicit) | infra | cyan | built-in | Generic Task worker. |
| clarifier | 1, 2, 3 | shaping | yellow | project/user | Detect ambiguities, draft clarification questions. |
| risk-analyst | 1, 2, 4, 6 | analytics | orange | project/user | Identify risk patterns (security, compliance, data, performance). |
| policy-analyst | 2, 4 | analytics | orange | project/user | Interpret policy docs vs change, assess policy implications. |
| forensic-analyst | 3, 4, 5 | analytics | orange | project/user | Translate raw diffs and logs into semantic summaries for routing decisions. |
| repo-operator | 3, 5 | implementation | green | project/user | Git workflows: branch, commit, merge, tag. Safe Bash only. |
| gh-reporter | all | reporter | pink | project/user | Post summaries to GitHub issues/PRs at flow boundaries. |
| swarm-ops | (utility) | infra | cyan | project/user | Guide for agent operations: model changes, adding agents, inspecting flows. |
| ux-critic | (utility) | critic | red | project/user | Inspect Flow Studio screens and produce structured JSON critiques. |
| ux-implementer | (utility) | implementation | green | project/user | Apply UX critique fixes to Flow Studio code and run tests. |
| run-prep | review | implementation | green | project/user | Establish run directory and flow infrastructure. Creates RUN_BASE/<flow>/ structure. |
| pr-creator | review | implementation | green | project/user | Create Draft PR if missing. Idempotent: skips if PR already exists. |
| pr-feedback-harvester | review | analytics | orange | project/user | Pull all bot/human feedback from PR. Non-blocking: returns what's available now. |
| review-worklist-writer | review | shaping | yellow | project/user | Cluster PR feedback into actionable Work Items with stable RW-NNN IDs. |
| test-executor | review | verification | blue | project/user | Execute test suites to verify fixes. Uses test-runner skill. |
| pr-commenter | review | reporter | pink | project/user | Post idempotent summary comments to PR. Updates existing comments. |
| pr-status-manager | review | implementation | green | project/user | Flip Draft PR to Ready when review complete. Keeps Draft if incomplete. |
| review-cleanup | review | verification | blue | project/user | Write review_receipt.json and finalize review artifacts. Update run index. |
| build-cleanup | review | verification | blue | project/user | Reseal build receipt if code changed during review. Update checksums. |
| secrets-sanitizer | review | verification | blue | project/user | Scan staged surface for secrets. Emit Gate Result (safe_to_commit, safe_to_publish). |
| gh-issue-manager | review | reporter | pink | project/user | Update GitHub issue board. Link PRs to issues, update labels and status. |
| signal-normalizer | signal | shaping | yellow | project/user | Parse raw input, find related context → issue_normalized.md, context_brief.md. |
| problem-framer | signal | shaping | yellow | project/user | Synthesize normalized signal → problem_statement.md. |
| requirements-author | signal | spec | purple | project/user | Write functional + non-functional requirements → requirements.md. |
| requirements-critic | signal | critic | red | project/user | Verify requirements are testable, consistent → requirements_critique.md. |
| bdd-author | signal | spec | purple | project/user | Turn requirements into BDD scenarios → features/*.feature. |
| scope-assessor | signal | shaping | yellow | project/user | Stakeholders, risks, T-shirt size → stakeholders.md, early_risks.md, scope_estimate.md. |
| impact-analyzer | plan | analytics | orange | project/user | Map affected services/modules/files → impact_map.json. |
| design-optioneer | plan | design | purple | project/user | Propose 2-3 architecture options with trade-offs → design_options.md. |
| adr-author | plan | design | purple | project/user | Write ADR for chosen design → adr.md. |
| interface-designer | plan | spec | purple | project/user | API contracts, data models, migrations → api_contracts.yaml, schema.md. |
| observability-designer | plan | spec | purple | project/user | Metrics, logs, traces, SLOs, alerts → observability_spec.md. |
| test-strategist | plan | spec | purple | project/user | Map BDD scenarios to test types → test_plan.md. |
| work-planner | plan | design | purple | project/user | Break design into subtasks, define rollout strategy → work_plan.md. |
| design-critic | plan | critic | red | project/user | Validate design vs constraints → design_validation.md. Never fixes. |
| context-loader | build | implementation | green | project/user | Load relevant code/tests/specs for subtask → subtask_context_manifest.json. |
| test-author | build | implementation | green | project/user | Write/update tests → tests/*, test_changes_summary.md. |
| test-critic | build | critic | red | project/user | Harsh review vs BDD/spec → test_critique.md. |
| code-implementer | build | implementation | green | project/user | Write code to pass tests, following ADR → src/*, impl_changes_summary.md. |
| code-critic | build | critic | red | project/user | Harsh review vs ADR/contracts → code_critique.md. |
| mutator | build | verification | blue | project/user | Run mutation tests → mutation_report.md. |
| fixer | build | implementation | green | project/user | Apply targeted fixes from critics/mutation → fix_summary.md. |
| doc-writer | build | implementation | green | project/user | Update inline docs, READMEs, API docs → doc_updates.md. |
| self-reviewer | build | verification | blue | project/user | Final review → self_review.md, build_receipt.json. |
| receipt-checker | gate | verification | blue | project/user | Verify build_receipt.json exists and is complete → receipt_audit.md. |
| contract-enforcer | gate | verification | blue | project/user | Check API changes vs contracts → contract_compliance.md. |
| security-scanner | gate | verification | blue | project/user | Run SAST, secret scans → security_scan.md. |
| coverage-enforcer | gate | verification | blue | project/user | Verify test coverage meets thresholds → coverage_audit.md. |
| gate-fixer | gate | implementation | green | project/user | Mechanical fixes only (lint/format/docs) → gate_fix_summary.md. |
| merge-decider | gate | verification | blue | project/user | Synthesize all checks → merge_decision.md (MERGE/BOUNCE/ESCALATE). |
| deploy-monitor | deploy | verification | blue | project/user | Watch CI/deployment events → verification_report.md. |
| smoke-verifier | deploy | verification | blue | project/user | Health checks, artifact verification → verification_report.md. |
| deploy-decider | deploy | verification | blue | project/user | Verify operationalization FRs (FR-OP-001..005) → deployment_decision.md (STABLE/NOT_DEPLOYED/BLOCKED/INVESTIGATE). |
| artifact-auditor | wisdom | verification | blue | project/user | Verify all expected artifacts from Flows 1-5 exist → artifact_audit.md. |
| solution-analyst | wisdom | analytics | orange | project/user | Requirement/implementation alignment → solution_analysis.md. |
| quality-analyst | wisdom | analytics | orange | project/user | Code health and complexity → quality_report.md. |
| maintainability-analyst | wisdom | analytics | orange | project/user | Naming, modularity, DRY, coupling → maintainability_analysis.md. |
| process-analyst | wisdom | analytics | orange | project/user | Flow efficiency, iterations, bounces → process_analysis.md, friction_log.md. |
| regression-analyst | wisdom | analytics | orange | project/user | Tests, coverage, issues, blame → regression_report.md. |
| pattern-analyst | wisdom | analytics | orange | project/user | Cross-run patterns and trends → pattern_report.md. |
| signal-quality-analyst | wisdom | analytics | orange | project/user | Feedback accuracy analysis → signal_quality_report.md. |
| flow-historian | wisdom | analytics | orange | project/user | Compile timeline → flow_history.json. |
| learning-synthesizer | wisdom | analytics | orange | project/user | Extract lessons from receipts, critiques → learnings.md. |
| feedback-applier | wisdom | analytics | orange | project/user | Create issues, suggest doc updates → feedback_actions.md. |
| traceability-auditor | wisdom | verification | blue | project/user | Run-level coherence and spec traceability → traceability_audit.md. |
| wisdom-cleanup | wisdom | verification | blue | project/user | Finalize wisdom_receipt.json, update run index. |
| reset-diagnose | reset | analytics | orange | project/user | Analyze upstream divergence, identify conflicts, assess severity. |
| reset-stash-wip | reset | implementation | green | project/user | Stash work-in-progress changes safely before reset operations. |
| reset-sync-upstream | reset | implementation | green | project/user | Fetch upstream changes without merging. Update remote tracking refs. |
| reset-resolve-conflicts | reset | implementation | green | project/user | Resolve merge/rebase conflicts. Apply safe resolution strategies. |
| reset-restore-wip | reset | implementation | green | project/user | Restore stashed work-in-progress after successful reset. |
| reset-prune-branches | reset | implementation | green | project/user | Clean up old shadow branches and stale remote tracking refs. |
| reset-archive-run | reset | verification | blue | project/user | Archive current run state before reset. Preserve audit trail. |
| reset-verify-clean | reset | verification | blue | project/user | Verify clean state after reset. Validate repo integrity. |

---

## Summary

<!-- META:AGENT_COUNTS -->
**Total: 73 agents** (3 built-in + 70 domain)
<!-- /META:AGENT_COUNTS -->

| Category | Count | Notes |
|----------|-------|-------|
| Built-in (orchestrator-only) | 3 | `explore`, `plan-subagent`, `general-subagent` |
| Cross-cutting | 5 | Used across multiple flows |
| Utility | 3 | `swarm-ops`, `ux-critic`, `ux-implementer` |
| Flow 1 (Signal) | 6 | |
| Flow 2 (Plan) | 8 | |
| Flow 3 (Build) | 9 | |
| Flow 4 (Review) | 11 | |
| Flow 5 (Gate) | 6 | |
| Flow 6 (Deploy) | 3 | |
| Flow 7 (Wisdom) | 13 | |
| Flow 8 (Reset) | 8 | Shadow fork reset/rebase operations |

### Agent Categories

- **shaping**: Problem framing, clarification
- **spec**: Requirements, BDD, contracts, observability, test plans
- **design**: Architecture options, ADRs, trade-offs, impact mapping
- **impl**: Code, tests, docs, fixes
- **critic**: Harsh reviews in microloops (never fix)
- **verify**: Receipt audits, contract checks, security scans, coverage
- **deploy**: CI monitoring, smoke tests
- **analytics**: Test analysis, regressions, learnings, flow history
- **reporter**: GitHub issue/PR summaries
- **git**: Branch, commit, merge, tag operations

### Key Principles

1. **All agents are orchestrator-only**: Only top-level Claude calls agents (built-in or domain)
2. **Agents currently can't call agents**: Due to Claude Code limitations, not design (runtime constraint)
3. Agents never block; document concerns and continue
4. Critics never fix; they write harsh receipts
5. Multi-path completion: VERIFIED/UNVERIFIED/BLOCKED states
6. Microloops in Flow 1 (requirements) and Flow 3 (tests, code)
7. Human reviews receipts at flow boundaries

---

## Flow Details

### Flow 1: Signal → Spec (6 agents)
**Question**: What problem, for whom?
**Agents**: signal-normalizer, problem-framer, requirements-author, requirements-critic, bdd-author, scope-assessor
**Cross-cutting**: clarifier, risk-analyst, gh-reporter

### Flow 2: Spec → Design (8 agents)
**Question**: What architecture solves it?
**Agents**: impact-analyzer, design-optioneer, adr-author, interface-designer, observability-designer, test-strategist, work-planner, design-critic
**Cross-cutting**: clarifier, risk-analyst, policy-analyst, gh-reporter

### Flow 3: Design → Code (9 agents)
**Question**: Does implementation match design?
**Agents**: context-loader, test-author, test-critic, code-implementer, code-critic, mutator, fixer, doc-writer, self-reviewer
**Microloops**: test-author ⇄ test-critic, code-implementer ⇄ code-critic
**Cross-cutting**: clarifier, repo-operator, gh-reporter

### Flow 4: Draft → Ready (Review) (11 agents)
**Question**: Is this PR ready for gate review?
**Agents**: run-prep, pr-creator, pr-feedback-harvester, review-worklist-writer, test-executor, pr-commenter, pr-status-manager, review-cleanup, build-cleanup, secrets-sanitizer, gh-issue-manager
**Microloop**: worklist_loop (resolve work items until pending_blocking == 0)
**Cross-cutting**: repo-operator, gh-reporter, policy-analyst, risk-analyst

### Flow 5: Review → Gate (6 agents)
**Question**: Is this merge-eligible?
**Agents**: receipt-checker, contract-enforcer, security-scanner, coverage-enforcer, gate-fixer, merge-decider
**Cross-cutting**: risk-analyst, policy-analyst, gh-reporter

### Flow 6: Gate → Prod (3 agents)
**Question**: Is deployment healthy?
**Agents**: deploy-monitor, smoke-verifier, deploy-decider
**Cross-cutting**: repo-operator, gh-reporter

### Flow 7: Prod → Wisdom (13 agents)
**Question**: What did we learn?
**Agents**: artifact-auditor, solution-analyst, quality-analyst, maintainability-analyst, process-analyst, regression-analyst, pattern-analyst, signal-quality-analyst, flow-historian, learning-synthesizer, feedback-applier, traceability-auditor, wisdom-cleanup
**Cross-cutting**: risk-analyst, gh-reporter

### Flow 8: Reset/Rebase (8 agents)
**Question**: How do we sync with upstream safely?
**Agents**: reset-diagnose, reset-stash-wip, reset-sync-upstream, reset-resolve-conflicts, reset-restore-wip, reset-prune-branches, reset-archive-run, reset-verify-clean
**Cross-cutting**: repo-operator
**Note**: Invoked via INJECT_FLOW when shadow fork diverges from upstream
