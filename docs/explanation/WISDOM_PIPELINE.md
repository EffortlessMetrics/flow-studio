# Wisdom Pipeline: How the System Learns

> **Status**: Design document (pipeline not yet implemented)
> **Purpose**: Define how learnings become rules

## The Feedback Loop

Flow 7 (Wisdom) analyzes completed runs and extracts:
- Patterns that worked
- Patterns that failed
- Optimization opportunities
- New failure modes

But how do these become improvements?

## The Pipeline Stages

### Stage 1: Observation

Wisdom agents produce observations:

```json
{
  "type": "pattern_detected",
  "pattern": "lint-then-test reduces iteration count",
  "evidence": ["run-123", "run-456", "run-789"],
  "confidence": "HIGH"
}
```

These observations flow to `RUN_BASE/wisdom/observations.jsonl` during Flow 7 execution.
The `learning-synthesizer` agent extracts patterns from receipts and critiques across all
flows, producing structured observations alongside the narrative `learnings.md`.

### Stage 2: Proposal

Observations become proposals:

```json
{
  "type": "rule_proposal",
  "target": ".claude/rules/execution/microloop-rules.md",
  "change": "Add lint step before test in build flow",
  "rationale": "3 runs showed 40% fewer iterations",
  "evidence_refs": ["run-123/wisdom/observations.jsonl:15"]
}
```

The `feedback-applier` agent is responsible for converting learnings into actionable items.
Currently, it produces `feedback_actions.md` with human-readable recommendations. The
proposal schema above represents the **aspirational** machine-readable format for automated
rule evolution.

### Stage 3: Review

Proposals require human review:
- Is the pattern real or coincidence?
- Does it generalize beyond the evidence?
- Are there counterexamples?
- What's the blast radius if wrong?

This is where the **Truth Hierarchy** (see [TRUTH_HIERARCHY.md](./TRUTH_HIERARCHY.md)) applies:
- Evidence (Level 1-2) supports the proposal
- Intent (Level 3) defines what we want to change
- Narrative (Level 5) is advisory, not authoritative

### Stage 4: Application

Approved proposals become:
- Rule file changes (versioned in git)
- Teaching note updates
- Flow spec modifications
- Agent prompt adjustments

### Stage 5: Validation

After application:
- Monitor for regressions
- Compare before/after metrics
- Rollback if degradation detected

The `wisdom_aggregate_runs.py` tool (see [WISDOM_SCHEMA.md](../WISDOM_SCHEMA.md)) can
compare metrics across runs to detect regressions introduced by rule changes.

## What Can Be Changed

### Safe to Automate (with review)

| Target | Example | Risk |
|--------|---------|------|
| Teaching note refinements | Add example to clarify edge case | Low |
| Example additions | New sample in runbook | Low |
| Threshold adjustments | Increase lint warning tolerance | Low |
| Warning additions | New check for common mistake | Low |

### Requires Careful Review

| Target | Example | Risk |
|--------|---------|------|
| Flow step ordering | Move lint before test | Medium |
| Agent role changes | Expand critic scope | Medium |
| Routing logic | Add new detour trigger | Medium |
| Exit conditions | Change microloop exit criteria | Medium |

### Requires Explicit Approval

| Target | Example | Risk |
|--------|---------|------|
| New flows | Add Flow 9 for incident response | High |
| New agents | Add security-hardener agent | High |
| Validation rule changes | FR-006 for new constraint | High |
| Safety boundary changes | Modify Gate bounce conditions | High |

## The Versioning Contract

All rule changes:
- Committed to git with rationale
- Linked to originating observation
- Tagged with confidence level
- Reversible via git revert

```
commit abc123
Author: wisdom-pipeline <automated>
Date:   2025-01-15

    chore(rules): add lint-before-test guidance to microloop-rules

    Observation: lint-then-test reduces iteration count by ~40%
    Evidence: run-123, run-456, run-789
    Confidence: HIGH
    Proposal: swarm/runs/run-789/wisdom/proposals/001-lint-before-test.json

    This change can be reverted with: git revert abc123
```

## Current State

| Component | Status | Location |
|-----------|--------|----------|
| Observation collection | **Implemented** | Flow 7 `learning-synthesizer` |
| Observation format | **Implemented** | `observations.jsonl` |
| Proposal generation | **Aspirational** | `feedback-applier` produces markdown |
| Human review UI | **Not implemented** | Manual artifact inspection |
| Automated application | **Not implemented** | Manual git commits |
| Regression monitoring | **Partial** | `wisdom_aggregate_runs.py` |

**Implemented**: Wisdom flows produce observations and learnings.

**Aspirational**: Observation -> Proposal -> Rule pipeline with governance.

## The Governance Question

Who approves rule changes?

| Model | Pros | Cons |
|-------|------|------|
| **Fully automated** | Fast iteration | Risky; no human oversight |
| **Human-in-loop** | Safe; current assumption | Slow; bottleneck |
| **Tiered by risk** | Balanced | Requires risk classification |

**Recommendation**: Tier by blast radius.

### Tier 1: Auto-apply with notification

- Teaching note refinements
- Example additions
- Warning additions

Human is notified but doesn't need to approve. Changes can be reverted if problematic.

### Tier 2: Propose, human approves

- Threshold adjustments
- Flow step reordering
- Routing logic changes

System generates proposal with evidence. Human reviews and approves via PR.

### Tier 3: Explicit approval + review period

- New flows or agents
- Safety boundary changes
- Validation rule changes

Requires explicit human approval plus a review period before activation.

## Why This Matters

### Without a Wisdom Pipeline

- Learnings stay in artifacts
- Same mistakes repeat across runs
- Improvement requires manual effort
- Institutional knowledge is lost

### With a Wisdom Pipeline

- System compounds learning
- Patterns become codified rules
- Factory gets smarter over time
- Knowledge survives personnel changes

This is the "self-patching" capability—but with governance.

## Connection to Routing Protocol

The Wisdom Pipeline integrates with the V3 routing model (see [ROUTING_PROTOCOL.md](../ROUTING_PROTOCOL.md)):

- **EXTEND_GRAPH** proposals originate from Wisdom observations
- High-frequency detours become candidates for golden path changes
- Off-road patterns that succeed consistently suggest new standard routes

```
Observation (many runs)
    -> Pattern detected
    -> EXTEND_GRAPH proposal
    -> Human review
    -> Flow spec change
    -> New golden path
```

## The Factory Improvement Loop

```
┌─────────────────────────────────────────────────────────────────┐
│                        Run N                                     │
│  Flow 1 -> Flow 2 -> Flow 3 -> Flow 4 -> Flow 5 -> Flow 6 -> Flow 7
│                                                              │
│                                                    Observations
│                                                              │
└──────────────────────────────────────────────────────────────┼──┘
                                                               │
                                                               v
┌─────────────────────────────────────────────────────────────────┐
│                    Wisdom Pipeline                               │
│                                                                  │
│  Observations -> Proposals -> Review -> Application -> Validation│
│                                                                  │
└──────────────────────────────────────────────────────────────┼──┘
                                                               │
                                                               v
┌─────────────────────────────────────────────────────────────────┐
│                        Run N+1                                   │
│  (Now with improved rules, teaching notes, and routing)          │
│  Flow 1 -> Flow 2 -> ...                                         │
└─────────────────────────────────────────────────────────────────┘
```

## Implementation Roadmap

### Phase 1: Structured Observations (Current)

- `learning-synthesizer` produces `observations.jsonl`
- Manual review of `learnings.md`
- Manual creation of issues/PRs for improvements

### Phase 2: Proposal Generation

- `feedback-applier` produces machine-readable proposals
- Proposals include target file, diff, rationale, evidence
- Dashboard for reviewing pending proposals

### Phase 3: Governance Tiers

- Classify proposals by blast radius
- Auto-apply Tier 1 with notification
- PR workflow for Tier 2
- Approval + review period for Tier 3

### Phase 4: Regression Monitoring

- Automated before/after metrics comparison
- Alert on degradation after rule change
- One-click rollback capability

## Related Documents

- [WISDOM_SCHEMA.md](../WISDOM_SCHEMA.md) - Schema for wisdom summaries and aggregation
- [ROUTING_PROTOCOL.md](../ROUTING_PROTOCOL.md) - V3 routing and EXTEND_GRAPH
- [TRUTH_HIERARCHY.md](./TRUTH_HIERARCHY.md) - Evidence hierarchy for validating proposals
- [flow-wisdom.md](../../swarm/flows/flow-wisdom.md) - Flow 7 specification
