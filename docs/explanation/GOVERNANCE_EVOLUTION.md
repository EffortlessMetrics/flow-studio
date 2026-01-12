# Governance Evolution: How Rules Improve

The governance system isn't static. It evolves through structured learning cycles.

## The Evolution Pipeline

```
Observation → Pattern → Proposal → Review → Application → Validation
    (Wisdom)   (Wisdom)   (Wisdom)   (Human)   (Rules)     (Runs)
```

## Stage 1: Observation

Flow 7 (Wisdom) observes patterns across runs:

### What Gets Observed
- Recurring failure signatures
- Frequent detour patterns
- Escalation rates by step
- Time/cost distributions
- Evidence quality trends

### Observation Artifacts
```
RUN_BASE/wisdom/observations/
├── failure_patterns.jsonl     # Recurring failures
├── detour_frequency.json      # Detour statistics
├── escalation_log.jsonl       # Human intervention patterns
└── quality_trends.json        # Evidence quality over time
```

### Example Observation
```json
{
  "pattern_id": "lint-before-critic",
  "observation": "Lint errors cause DETOUR in 75% of build runs",
  "frequency": "15 of 20 runs",
  "evidence_runs": ["run-001", "run-002", "run-003", "..."],
  "first_observed": "2024-01-01",
  "last_observed": "2024-01-15"
}
```

## Stage 2: Pattern Recognition

Wisdom identifies actionable patterns:

### Pattern Types

| Type | Description | Example |
|------|-------------|---------|
| **Preventable** | Could be avoided with earlier check | Lint errors → pre-emptive linting |
| **Optimizable** | Could be faster/cheaper | Redundant file reads → caching |
| **Structural** | Flow design issue | Missing step → add step |
| **Policy** | Rule enforcement gap | Missing evidence → stricter gate |

### Pattern Confidence

| Confidence | Criteria |
|------------|----------|
| HIGH | > 10 occurrences, consistent signature |
| MEDIUM | 5-10 occurrences, some variation |
| LOW | < 5 occurrences, needs more data |

## Stage 3: Proposal Generation

Wisdom generates concrete proposals:

### Proposal Schema
```json
{
  "proposal_id": "prop-001",
  "pattern_id": "lint-before-critic",
  "confidence": "HIGH",
  "proposed_change": {
    "type": "add_step",
    "target": "flow: build",
    "change": "Add auto-linter step before code-critic",
    "rationale": "Reduces DETOUR rate by catching lint issues early"
  },
  "expected_impact": {
    "detour_reduction": "~75%",
    "cost_increase": "~5% (one extra step)",
    "net_benefit": "Positive (fewer iterations)"
  },
  "evidence": {
    "runs_analyzed": 20,
    "pattern_frequency": "75%",
    "confidence_interval": "65-85%"
  }
}
```

### Proposal Types

| Type | Example |
|------|---------|
| `add_step` | Insert pre-emptive check |
| `modify_step` | Change step behavior |
| `add_detour` | New known-fix pattern |
| `update_policy` | Change gate criteria |
| `update_prompt` | Improve agent instructions |

## Stage 4: Human Review

Proposals are reviewed by humans:

### Review Criteria
1. **Evidence quality** - Is the pattern real?
2. **Cost/benefit** - Does the change pay off?
3. **Risk** - What could go wrong?
4. **Reversibility** - Can we undo it?

### Review Decisions
- **APPROVE** - Implement the change
- **REJECT** - Not worth it / bad idea
- **DEFER** - Need more evidence
- **MODIFY** - Approve with changes

### Review Artifact
```json
{
  "proposal_id": "prop-001",
  "decision": "APPROVE",
  "reviewer": "human",
  "reviewed_at": "2024-01-20",
  "notes": "Good catch. Implement as suggested.",
  "modifications": null
}
```

## Stage 5: Application

Approved changes are applied:

### Change Implementation

| Change Type | Implementation |
|-------------|----------------|
| `add_step` | Update flow spec, add agent if needed |
| `modify_step` | Update teaching notes |
| `add_detour` | Update detour catalog |
| `update_policy` | Update gate rules |
| `update_prompt` | Update agent prompt |

### Application Tracking
```json
{
  "proposal_id": "prop-001",
  "applied_at": "2024-01-21",
  "changes_made": [
    "flows/build.md: Added step 2b (auto-linter)",
    "detour-catalog.md: Updated lint-fix routing"
  ],
  "rollback_commit": "abc123"
}
```

## Stage 6: Validation

Changes are monitored for effectiveness:

### Validation Metrics

| Metric | Before | After | Target |
|--------|--------|-------|--------|
| DETOUR rate | 75% | ? | < 20% |
| Step count | 5 | 6 | 6 |
| Total cost | $X | ? | < $X * 1.1 |

### Validation Outcome

After N runs:
- **SUCCESS** - Metrics improved as expected
- **PARTIAL** - Some improvement, not as much as expected
- **FAILURE** - No improvement or regression
- **ROLLBACK** - Regression, reverting change

## Example Evolution Cycle

### The Pattern
```
Observation: "Lint errors cause 75% of DETOUR decisions in build flow"
Pattern: Preventable - lint check could catch these before critic
```

### The Proposal
```
Proposal: Add auto-linter step before code-critic
Expected: Reduce DETOUR rate from 75% to < 20%
Cost: One extra step (~5% more tokens)
```

### The Review
```
Decision: APPROVE
Rationale: Clear win - small cost for big DETOUR reduction
```

### The Application
```
Change: Added step 2b (auto-linter) to build flow
Commit: def456
Rollback: abc123
```

### The Validation
```
After 10 runs:
- DETOUR rate: 75% → 12% ✓
- Step count: 5 → 6 ✓
- Total cost: +8% (acceptable)

Status: SUCCESS
```

## Governance Artifacts

```
swarm/governance/
├── observations/           # Raw observations from Wisdom
│   └── 2024-Q1/
├── proposals/              # Generated proposals
│   ├── pending/
│   ├── approved/
│   └── rejected/
├── applications/           # Applied changes
│   └── 2024-Q1/
└── validations/            # Validation results
    └── 2024-Q1/
```

## The Rule

> Governance evolves through evidence, not opinion.
> Every change is proposed, reviewed, applied, and validated.
> Failed changes are rolled back.

---

## See Also
- [WISDOM_PIPELINE.md](./WISDOM_PIPELINE.md) - Flow 7 details
- [META_LEARNINGS.md](./META_LEARNINGS.md) - What we learned
- [VALIDATOR_AS_LAW.md](./VALIDATOR_AS_LAW.md) - How rules become law
