# Why Flow Studio

> **Context:** This document describes the core patterns implemented by **Flow Studio**.
>
> Flow Studio is the orchestration layer, UI, and runtime harness in this repo.
> For a portable `.claude/` pack to use in your own repo, see our sister repo:
> [`EffortlessMetrics/demo-swarm`](https://github.com/EffortlessMetrics/demo-swarm).

This repo demonstrates **three core ideas** that distinguish it from typical agent demos.

> **Haven't seen it work yet?** Run `make demo-run` and explore `swarm/runs/demo-health-check/`. See [DEMO_RUN.md](../DEMO_RUN.md) for a 2-minute walkthrough.

## 1. Flows as First-Class Spec

Most agent systems treat orchestration as an ad-hoc conversation. This swarm treats **flows** as first-class architectural artifacts—the same way you'd treat a system design document or RFC.

**What that means**:

- Each flow (`signal`, `plan`, `build`, `review`, `gate`, `deploy`, `wisdom`) is a **spec** with:
  - **Mermaid diagram** showing the DAG of steps
  - **Agent roster** listing who does what
  - **RUN_BASE paths** specifying where artifacts go
  - **Microloop patterns** defining when writers and critics iterate
  - No ambiguity about "what should happen"

- Flows are **config-driven** (YAML in `swarm/config/flows/`) and **portable**: a GitLab org can implement the same spec differently than GitHub.

- Adapters (`.claude/commands/`) are the **implementation layer**: how this swarm specifically runs on Claude Code.

**Why this matters for a demo**:

You're not watching agents riff in chat. You're watching **a deterministic flow** execute step-by-step, with every decision traced back to the spec. That's how you **debug agentic flows without guessing**.

---

## 2. Selftest as a Governance Gate

Most demos skip testing entirely or treat it as a nice-to-have. This swarm makes testing the **load-bearing wall** of development.

**What that means**:

- **Three tiers** of validation:
  - **KERNEL**: Core Python checks (must pass; ~300ms)
  - **GOVERNANCE**: Swarm-specific alignment (agent colors, skill files, flow references)
  - **OPTIONAL**: Advanced checks (coverage thresholds, mutation testing)

- **Failures are diagnosable**: Running `make selftest-doctor` separates harness issues from actual service issues. You know what to fix.

- **One golden command**: `make dev-check` is your pre-commit gate. It runs everything locally—no CI required to know if you're safe.

**Why this matters for a demo**:

The demo swarm isn't just "see agents work"; it's "see agents work *within governance*". You can show people how to build agentic systems that **fail clearly** instead of silently breaking.

---

## 3. Agent Surfaces Are Structured

Most agent demos hide the mechanics. This swarm exposes them deliberately.

**What that means**:

- **RUN_BASE artifact layout**:
  ```
  swarm/runs/<run-id>/
    signal/         ← Flow 1 outputs
    plan/           ← Flow 2 outputs
    build/          ← Flow 3 outputs
    review/         ← Flow 4 outputs
    gate/           ← Flow 5 outputs
    deploy/         ← Flow 6 outputs
    wisdom/         ← Flow 7 outputs
  ```

- **All inputs/outputs are on disk** — not hidden in agent state, traces, or logs. You can inspect `build_receipt.json`, read `merge_recommendation.md`, compare `test_output.log` before/after.

- **Agents are declared explicitly**:
  - 45 domain agents (Flow 1–6 specific)
  - 3 built-in infrastructure agents
  - 5 cross-cutting agents (clarifier, risk-analyst, etc.)
  - Each has a `.claude/agents/<key>.md` file with its prompt

**Why this matters for a demo**:

You're not trusting magic. You can walk through the artifacts, see what each agent was asked to do, and understand exactly where decisions came from. **Receipts aren't hidden.**

---

## 4. Agents Always Complete Flows

Most agent systems escalate or block when they encounter ambiguity. This swarm requires **agents to always complete their assigned flow**—documenting concerns, not halting execution.

**What that means**:

- **Document and continue**: When an agent encounters ambiguity, it:
  1. States its assumptions explicitly
  2. Documents questions in `clarification_questions.md`
  3. Proceeds with its best interpretation
  4. Never blocks or escalates mid-flow

- **Critics control loop exit**: In microloops (writer ⇄ critic), the critic decides when to stop:
  - `Status: VERIFIED` → loop complete, work approved
  - `Status: UNVERIFIED` + `can_further_iteration_help: no` → loop exits, concerns documented
  - The critic's judgment about iteration viability determines exit—not a loop counter

- **Humans review at boundaries**: Flow artifacts (receipts, critiques, recommendations) are the review surface. Humans decide whether to proceed, rerun, or intervene—but only at flow boundaries, not mid-execution.

**Example: Ambiguous Problem Statement in Flow 1**

```
Input: "Add caching"

What a blocking agent would do:
  → Ask: "What kind of caching? Redis? In-memory? For which endpoints?"
  → Halt until human responds

What this swarm does:
  → requirements-author writes requirements assuming "in-memory response cache for API endpoints"
  → requirements-critic marks UNVERIFIED, notes ambiguity
  → clarification_questions.md captures: "Clarify caching scope: in-memory vs distributed? Which endpoints?"
  → Flow completes with documented assumptions
  → Human reviews signal/ artifacts, decides whether to rerun with clarification
```

**Why this matters for a demo**:

This pattern shifts the burden from "interrupt the agent chain to ask questions" to "review the output and decide if it needs refinement." The swarm produces **complete, reviewable work** even under uncertainty—exactly what you want from a team of interns.

---

## The Demo Philosophy

**Code generation is faster than human review. The bottleneck is trust.**

Open-weight models now produce junior-or-better code, faster than you can read it, cheap enough to run repeatedly. Just like programmers stopped reading assembly, developers stop grinding on first-draft implementation—the job moves up the stack.

When quality is already acceptable and generation outpaces review, **verification becomes the limiting reagent**. Flow Studio uses that leverage to run research, planning, multi-pass implementation, tests, and hardening loops—then publishes a PR cockpit (quality events + hotspots + evidence) so developers can spend their time on architecture and decisions, not grind.

**How this works:**
- Let agents iterate (microloops) until tests pass and critics approve
- Heavy upfront context loading (20–50k tokens) prevents downstream re-search
- Harsh critics catch bugs before they reach Gate/Deploy
- Agents never block; they document concerns and continue
- Humans review **receipts** (structured outputs), not intermediate steps

The result: **auditable, repeatable, traceable decisions**—the opposite of "vibes-based engineering." See [MARKET_SNAPSHOT.md](./MARKET_SNAPSHOT.md) for current data points.

---

## What You Get in Flow Studio

### Runnable Swarm

```bash
make dev-check        # Validate swarm health locally
make demo-run         # Populate example artifacts
make flow-studio      # Visualize flows (http://localhost:5000)
```

### Example Artifacts

`swarm/examples/health-check/` contains a **complete, curated run** of all 7 flows showing "add a health check endpoint" flowing through:
- Signal → problem statement, BDD scenarios
- Plan → ADR, contracts, observability spec
- Build → code + tests with microloop receipts
- Review → pre-gate review
- Gate → audit verdict, merge recommendation
- Deploy → deployment verification, smoke tests
- Wisdom → regressions detected, learnings extracted

### Reference Material

- **Flows**: `swarm/flows/flow-*.md` — The abstract specs
- **Agents**: `swarm/AGENTS.md` + `.claude/agents/` — The roster and prompts
- **Config**: `swarm/config/` — YAML definitions
- **Validation**: `swarm/tools/validate_swarm.py` — What "good" means

---

## Flow Studio vs demo-swarm

**Flow Studio** (this repo) is the orchestration layer:
- Python kernel that manages state and routing
- Stepwise execution with durable receipts
- Flow Studio UI for visualization
- Steps as first-class execution units

**demo-swarm** (sister repo) is the portable agent pack:
- `.claude/` directory you copy into your own repo
- Agent definitions for Claude Code
- Works with Claude Code directly, no kernel required

Flow Studio grew out of demo-swarm. If you want to add agentic SDLC to your existing repo, start with [demo-swarm](https://github.com/EffortlessMetrics/demo-swarm). If you want the full orchestration layer with stepwise execution and UI, use Flow Studio.

---

## Scope and Safety: What Flow Studio Does (and Doesn't)

Flow Studio is a **reference implementation**, not production infrastructure. Understanding its boundaries helps you evaluate whether to adopt it and what to extend.

### What's In Flow Studio

**Flows 1–4: Fully Local**
- Git + files only—no external services required
- Works immediately after clone
- All 4 flows produce artifacts in `swarm/runs/<run-id>/`

**Flows 5–6: GitHub Integration**
- Uses `gh` CLI for merge, release, deployment verification
- Graceful fallback: dry-run mode when not in a GitHub context
- Extension guides in `swarm/infrastructure/` for k8s, observability

**Steps and Stations**
- 7 flows with 40+ steps total
- Steps are the execution units; stations define the work
- Agentic steps invoke Claude Code SDK; deterministic steps run Python
- All config-backed (`swarm/spec/stations/`) with YAML definitions

**Validation and Governance**
- Selftest system (16 steps across KERNEL/GOVERNANCE/OPTIONAL tiers)
- Validator enforcing FR-001–FR-005 (bijection, colors, references, skills, paths)
- CI integration via `make dev-check`

### What's Out of Scope

**Production Kubernetes Deployment**
- No Helm charts, no k8s manifests
- `swarm/infrastructure/flow-5-extensions.md` documents patterns for adopters

**Org-Level Governance**
- Branch protection rules (requires GitHub org admin access)
- SLA dashboards and alerting
- Policy-as-code enforcement at organization level
- These are documented patterns, not running infrastructure

**External Integrations**
- No Datadog, Prometheus, or observability platform hooks
- No Slack/PagerDuty/incident management
- Extension points documented in `swarm/infrastructure/flow-6-extensions.md`

**Step Isolation**
- Each step runs in its own context (fresh Claude session or Python process)
- The kernel manages state transitions and routing between steps
- This isolation enables stepwise observability and resume

### Critical Invariants

These invariants are non-negotiable design constraints that distinguish Flow Studio from typical agent systems:

1. **Steps always complete** -- No mid-flow blocking or escalation. Document concerns in receipts; humans review at flow boundaries.

2. **Auto-remediation is out-of-band** -- Remediation executors (like `selftest_remediate_execute.py`) are separate tools that humans/CI invoke explicitly. Flows never call them inline.

3. **SaaS integrations are explicitly out-of-scope** -- Flow Studio uses only local files, git, and GitHub. Datadog, Prometheus, Slack, etc. are documented as extension patterns in `swarm/infrastructure/` but not implemented here.

> For detailed remediation architecture, see [`docs/designs/AUTO_REMEDIATION_DESIGN.md`](designs/AUTO_REMEDIATION_DESIGN.md).

> For implementation details on step behavior and flow patterns, see [`CLAUDE.md` Key Patterns](../CLAUDE.md#key-patterns).

### How to Extend Flow Studio

1. **Clone and validate**:
   ```bash
   git clone <this-repo>
   make dev-check  # Ensure baseline works
   ```

2. **Customize stations**: Edit `swarm/spec/stations/<key>.yaml`

3. **Add your flows**: Create flow spec in `swarm/flows/` + wire into the kernel

4. **Integrate your infra**: Use `swarm/infrastructure/` guides as starting points

5. **Enforce governance**: Enable `pre-commit install` and add branch protection in your org

Flow Studio is designed to be **forked and extended**, not used as-is.

---

## Further Reading

- **Full architecture**: [ARCHITECTURE.md](../ARCHITECTURE.md)
- **Development guide**: [CLAUDE.md](../CLAUDE.md)
- **Philosophy & positioning**: [swarm/positioning.md](../swarm/positioning.md)
- **AgOps manifesto**: [AGOPS_MANIFESTO.md](./AGOPS_MANIFESTO.md)
- **Selftest deep dive**: [SELFTEST_SYSTEM.md](./SELFTEST_SYSTEM.md)
- **Sister repo (portable pack)**: [EffortlessMetrics/demo-swarm](https://github.com/EffortlessMetrics/demo-swarm)
