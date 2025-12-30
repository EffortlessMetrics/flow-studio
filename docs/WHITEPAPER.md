# Self-Governing CI: An Agentic SDLC for AI-Assisted Engineering

> A framework for trading compute to save senior engineer attention

---

## Executive Summary

**The Problem**: LLM-based development tools generate code without governance. Teams lack control planes, audit trails, and repeatable decision-making. Senior engineers spend time reviewing vibes instead of topology.

**The Solution**: Self-governing CI treats the SDLC as a deterministic pipeline. Agents are narrow workers on an assembly line; flows are conveyor belts with explicit contracts; receipts replace trust.

**The Outcome**: Auditable, repeatable, traceable engineering decisions. When something breaks in production, you trace the decision back to the spec it was following, not the prompt that generated it.

---

## 1. The Problem

### 1.1 Senior Engineer Attention is Scarce

- Staff+ engineers are bottlenecks: reviewing PRs, designing systems, debugging incidents
- Context switching costs ~23 minutes per interruption (research citation)
- "Quick review" requests multiply across teams, consuming the scarcest resource

### 1.2 Current LLM Integration Patterns Fall Short

- **Vibe coding**: "I prompted it and it looks okay" -- no audit trail, no repeatability
- **Agent swarms without governance**: Agents coordinate via chat, drift without physics
- **Single-shot generation**: Code appears but no one knows why decisions were made
- **Human-in-every-loop**: Defeats the purpose; engineer attention still consumed

### 1.3 The Missing Control Plane

- CI/CD governs deployment but not design decisions
- No equivalent of "branch protection rules" for AI-generated code logic
- Receipts (build artifacts, test results, reviews) exist but aren't connected
- Teams need a control plane that trades compute for attention

---

## 2. Core Philosophy

### 2.1 Attention Arbitrage

- Spend tokens/time/disk freely if it saves senior engineer attention later
- A 50KB build receipt takes 2 minutes to review; re-reading 300 lines takes 30 minutes
- Favor verbose receipts over minimalist diffs
- Measure DevLT (Dev Lead Time) = time humans actively care about a change

### 2.2 Schema Gravity

- LLMs drift; physics (contracts, policies, mutation tests) pulls them back
- Success isn't "the LLM understood the spec"; it's "the tests forced compliance"
- You can't debug vibes, but you can debug "test failed because API contract says max_length=255"
- Humans review topology (ADR, test plan, receipts), not every line of generated code

### 2.3 Oppositional Validation

- Creation and verification stay separated: author vs critic vs mutator
- Trust comes from their friction; the trusted artifact is the receipt of the fight
- Critics never fix; they write harsh assessments with explicit status
- If the same agent writes and approves code, you're back to vibes

### 2.4 Narrow Agents, Complete Flows

- Agents are infinite interns managed via flows, not chat
- Give a context slice and a narrow task; accept bounce-backs, fix the brief, rerun
- A narrow task with clear success criteria (tests pass, critic approves) is debuggable
- "Just implement this feature" is not debuggable

---

## 3. Architecture

### 3.1 The Seven Flows

| Flow | Question | Outputs | Key Agents |
|------|----------|---------|------------|
| **Signal** (1) | What problem are we solving? | Requirements, BDD, risk assessment | signal-normalizer, problem-framer, requirements-author/critic |
| **Plan** (2) | How should we solve it? | ADR, contracts, observability spec, test/work plans | adr-author, interface-designer, test-strategist, design-critic |
| **Build** (3) | Does the implementation satisfy the design? | Code, tests, receipts | test-author/critic, code-implementer/critic, mutator, fixer |
| **Review** (4) | Is the implementation correct? | Review feedback, approval status | self-reviewer, peer-reviewer, review-synthesizer |
| **Gate** (5) | Is it safe to merge? | Audit report, merge recommendation | receipt-checker, contract-enforcer, security-scanner, merge-decider |
| **Deploy** (6) | Did deployment succeed? | Deployment log, verification report | deploy-monitor, smoke-verifier, deploy-decider |
| **Wisdom** (7) | What did we learn? | Regressions, learnings, feedback actions | artifact-auditor, regression-analyst, learning-synthesizer, feedback-applier |

```diagram
Title: The Seven-Flow SDLC Pipeline

Layout: Left-to-right flow with 7 boxes
Boxes: Signal → Plan → Build → Review → Gate → Deploy → Wisdom

Each box shows:
- Flow number (1-7)
- Key question it answers
- Primary outputs

Arrows between boxes show artifact dependencies:
- Signal outputs feed Plan inputs
- Plan outputs feed Build inputs
- Build receipt required for Gate
- Gate decision required for Deploy
- Deploy artifacts feed Wisdom analysis

Color coding by flow type:
- Yellow/Purple: Specification (Signal, Plan)
- Green: Implementation (Build)
- Blue: Verification (Gate, Deploy)
- Orange: Analytics (Wisdom)
```

### 3.2 The Three Tiers (KERNEL/GOVERNANCE/OPTIONAL)

- **KERNEL**: Core checks that must pass; failure = repo is broken (Python lint, compile)
- **GOVERNANCE**: Swarm contracts; important but can be deferred with `--degraded` mode
- **OPTIONAL**: Nice-to-have checks; informational only, never block
- Philosophy: Fail fast, fail clearly; decomposable for partial progress

```diagram
Title: Selftest Tier Pyramid

Layout: Pyramid with 3 tiers, narrow at top

Top tier (smallest): KERNEL
- "Must pass, always"
- Examples: lint, compile, core tests
- Exit code 1 if fails

Middle tier: GOVERNANCE
- "Should pass, deferrable"
- Examples: API compat, migrations, docs
- Can run with --degraded

Bottom tier (largest): OPTIONAL
- "Nice to have"
- Examples: coverage thresholds, extras
- Never blocks

Arrow on side: "Blocking severity increases upward"
```

### 3.3 Spec vs Adapter Separation

- **Spec layer** (`swarm/flows/*.md`): Defines abstract roles and artifacts (what)
- **Adapter layer** (`.claude/`): Platform-specific implementation (how)
- Flows 1-4: 1:1 mapping between spec role and adapter agent
- Flows 5-6: Spec roles are abstract; adapters fan out to multiple platform-specific agents
- Benefit: Portable spec (GitLab/Bitbucket can implement differently)

---

## 4. How It Works

### 4.1 Microloops: Writer-Critic Iteration

- Requirements author writes; requirements critic reviews; loop until VERIFIED or no viable fix path
- Test author writes; test critic reviews; loop until VERIFIED or blocked
- Code implementer writes; code critic reviews; loop until VERIFIED or blocked
- Exit conditions are explicit: `Status: VERIFIED` or `can_further_iteration_help: no`
- No hard iteration caps; critic judgment determines exit, not loop counters

```diagram
Title: Writer-Critic Microloop

Layout: Circular flow between two actors

Left actor: Writer (e.g., requirements-author)
Right actor: Critic (e.g., requirements-critic)

Flow:
1. Writer produces artifact
2. Critic reviews, returns VERIFIED or UNVERIFIED
3. If UNVERIFIED + can_iterate: loop back to Writer
4. If VERIFIED or can_iterate=no: exit loop

Exit conditions shown as decision diamond:
- VERIFIED → proceed to next step
- UNVERIFIED + no viable fix → document and proceed
- Never: hard iteration cap (critic judgment determines exit)
```

### 4.2 Receipts and Audit Trails

- Every flow produces structured artifacts in `RUN_BASE/<flow>/`
- `build_receipt.json`: Machine-readable summary of all build verification
- `merge_recommendation.md`: Gate's decision with rationale
- `learnings.md`: Wisdom flow's extracted patterns
- Receipts are the trusted output; humans review structure, not every line

### 4.3 Bounce-Backs vs Blocking

- Agents never block or escalate mid-flow
- Document ambiguities in `clarification_questions.md`
- Document concerns in critiques/receipts
- State assumptions explicitly; continue with best interpretation
- Always reach the flow boundary; humans review receipts and decide whether to rerun
- Gate bounces to Build or Plan if issues are non-trivial; gate fixes are mechanical only

---

## 5. Operational Proof

### 5.1 What's Built and Working

- 56 agents (3 built-in infrastructure + 53 domain agents across 7 flows)
- 4 skills (test-runner, auto-linter, policy-runner, heal_selftest)
- 16-step selftest system with three-tier governance
- Flow Studio visualization (http://localhost:5000)
- CI integration with `make dev-check` as single entrypoint

### 5.2 Test Coverage

- Validator enforces FR-001 through FR-005 (bijection, frontmatter, references, skills, paths)
- Selftest validates all governance steps in < 2 seconds baseline
- Incremental mode (`--check-modified`) achieves > 50% speedup on typical changes
- AC traceability chain: Config -> Plan API -> Status API -> Flow Studio UI

### 5.3 Metrics and Observability

- JSON mode output for dashboard integration (`--json`, `--json-v2`)
- Degradation log (`selftest_degradations.log`) for tracking governance failures over time
- Exit code contract: 0 = pass, 1 = fail, 2 = fatal error
- `/platform/status` API for programmatic health checks

---

## 6. Adoption Path

### 6.1 Drop-in Selftest (30 minutes)

- Clone repo, run `make dev-check` to validate baseline
- Selftest provides immediate governance without flow complexity
- Demonstrates: fail fast, fail clearly, diagnosable failures
- No external dependencies; works immediately on clone

### 6.2 Flow Studio Visualization (1 hour)

- Run `make flow-studio` to see flows as interactive graph
- Explore agents, steps, and their relationships
- Study golden runs (`swarm/examples/health-check/`) for artifact shapes
- Understand the pipeline before customizing

### 6.3 Full Swarm Integration (2-3 weeks)

- Week 1: Configure agents for your domain (edit `swarm/config/agents/`)
- Week 2: Customize flows for your SDLC (edit `swarm/config/flows/`)
- Week 3: Integrate with CI/CD and enable branch protection
- Result: Self-governing pipeline with receipts and audit trails

---

## 7. Differentiation

### 7.1 vs. Blocking Agents

- Blocking agents halt on ambiguity, requiring human intervention mid-flow
- This swarm: Agents document concerns and continue; humans review at flow boundaries
- Trade-off: Complete work with documented assumptions vs. perfect work never delivered
- Philosophy: Receipts over perfection; humans gate topology, not every decision

### 7.2 vs. Vibe-Based Engineering

- Vibe-based: "I prompted it and it looks okay"
- This swarm: "I defined the schema/ADR/mutation thresholds, and the swarm ground until green"
- You still need judgment to set up the gravity well (contracts, tests, thresholds)
- Once set, agents do the grinding; you review the receipts

### 7.3 vs. Traditional CI/CD

- Traditional CI/CD: Governs artifact deployment, not design decisions
- This swarm: Extends governance to Signal (problem framing) through Wisdom (learnings)
- CI/CD is the enforcement layer; flows are the decision-making layer
- Receipts connect design decisions to deployment outcomes

---

## 7.5 Where This Does *Not* Fit

This framework assumes certain baseline capabilities. It's not the right choice if:

- **Highly dynamic, no-CI shops:** If teams can't keep any CI green, selftest will just add noise. Prerequisite: at least one repo with a passing test suite.

- **No single SDLC surface:** If orgs have three+ competing SDLC systems (Jira, Linear, spreadsheets, chat), this should land behind one of them, not as a fourth control plane.

- **Pure infra / no product code:** Repos that are almost entirely Terraform/Helm may need different flows; this specimen is code-first with Python/Rust assumptions.

- **"Move fast, break things" culture:** If the org explicitly deprioritizes governance for speed, the friction this adds won't be welcome. This is for teams that *want* audit trails.

### Preconditions Table

| Dimension | Expectation |
|-----------|-------------|
| CI | Exists, runs on PR |
| Tests | At least a basic pytest/cargo test suite |
| Culture | Willing to break builds on KERNEL failures |
| Ownership | Someone owns CI failures (they are not ignored) |

---

## 8. Future Vision

### 8.1 Phase 4-5 Roadmap

- Multi-platform generation (Claude, OpenAI, Gemini adapters from single spec)
- Config-driven agent generation (YAML -> adapter files automatically)
- Template-based prompt management (edit once, regenerate for all platforms)
- Incremental adoption: Phase 0 works today; generation is optional optimization

### 8.2 Cross-Org Scaling

- Org-level governance (branch protection rules, SLA dashboards)
- Policy-as-code enforcement at organization level
- Shared agent libraries across teams
- Central wisdom extraction from multiple swarms

### 8.3 Infrastructure Extensions

- Kubernetes deployment verification (canary, rollback triggers)
- Observability platform integration (Datadog, Prometheus, Grafana)
- Incident management hooks (PagerDuty, Slack, issue correlation)
- See `swarm/infrastructure/flow-5-extensions.md` and `flow-6-extensions.md`

---

## Appendix A: Glossary

| Term | Definition |
|------|------------|
| **Agent** | Narrow worker with specific role; reads inputs, writes outputs, uses tools |
| **Flow** | Deterministic pipeline from input to output; sequence of steps with agents |
| **Receipt** | Structured artifact proving work was done; audit trail for decisions |
| **Microloop** | Writer-critic iteration until VERIFIED or no viable fix path |
| **Bounce-back** | Gate returning work to earlier flow for non-trivial fixes |
| **RUN_BASE** | Root directory for run artifacts: `swarm/runs/<run-id>/` |
| **Gravity well** | Contracts, tests, policies that pull LLM output back to compliance |
| **DevLT** | Dev Lead Time: time humans actively care about a change |
| **KERNEL** | Selftest tier: core checks that must always pass |
| **GOVERNANCE** | Selftest tier: swarm contracts; can be deferred with `--degraded` |

---

## Appendix B: Quick Reference

### Essential Commands

```bash
# Validate swarm health
make dev-check

# Run complete selftest
make selftest

# Fast kernel check (~300ms)
make kernel-smoke

# Visualize flows
make flow-studio

# Populate example run
make demo-run
```

### Key Files

| Path | Purpose |
|------|---------|
| `swarm/AGENTS.md` | Agent registry (source of truth) |
| `swarm/flows/flow-*.md` | Flow specifications |
| `swarm/positioning.md` | Philosophy and axioms |
| `.claude/agents/*.md` | Agent definitions (frontmatter + prompt) |
| `swarm/config/` | YAML configuration for agents and flows |
| `swarm/examples/health-check/` | Complete golden run |

```diagram
Title: Swarm vs Traditional CI

Layout: Side-by-side comparison

Left side: "Traditional CI"
- Single lane: lint → test → build → deploy
- All-or-nothing: any failure blocks
- No visibility into decision rationale

Right side: "Swarm CI"
- Three lanes:
  - Selftest (KERNEL/GOVERNANCE/OPTIONAL tiers)
  - Validator (FR-001 through FR-005)
  - Flow Studio (visual spec explorer)
- Graceful degradation: KERNEL blocks, GOVERNANCE warns
- Full audit trail: receipts, critiques, decisions traced to specs

Outcome callout: "Specimen repo where CI can't accidentally drift from the spec"
```

### Flow Outputs

```
RUN_BASE/
  signal/     # Problem statement, requirements, BDD, risk
  plan/       # ADR, contracts, observability, test/work plans
  build/      # Code, tests, receipts, critiques
  gate/       # Audit, security, merge recommendation
  deploy/     # Deployment log, verification report
  wisdom/     # Regressions, learnings, feedback actions
```

---

**Document Version**: 1.0
**Last Updated**: 2025-12-01
**Source Repository**: flow-studio
