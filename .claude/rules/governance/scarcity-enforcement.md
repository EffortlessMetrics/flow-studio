# Scarcity Enforcement: Budgets as Design

Token limits and context budgets aren't bugs—they're features that enforce discipline.

## The Scarcity Principle

Resources are deliberately constrained to:
- Force prioritization
- Prevent context pollution
- Encourage compression
- Maintain focus

## Token Budgets

### Per-Step Budgets

| Step Type | Input Budget | Output Budget |
|-----------|--------------|---------------|
| Shaping | 20k tokens | 5k tokens |
| Implementation | 30k tokens | 10k tokens |
| Critic | 25k tokens | 5k tokens |
| Gate | 20k tokens | 3k tokens |

### Budget Overflow Handling

When input exceeds budget:
1. Drop LOW priority items first
2. Truncate MEDIUM priority items
3. Never truncate CRITICAL items (teaching notes, current step spec)
4. Log what was dropped

```json
{
  "budget_overflow": {
    "requested": 45000,
    "allowed": 30000,
    "dropped": [
      { "item": "history_summary", "tokens": 10000, "priority": "LOW" },
      { "item": "old_artifacts", "tokens": 5000, "priority": "MEDIUM" }
    ]
  }
}
```

## Context Budget Hierarchy

What gets loaded (priority order):

| Priority | Content | Never Drop |
|----------|---------|------------|
| CRITICAL | Teaching notes, step spec | Yes |
| HIGH | Previous step output | No |
| MEDIUM | Referenced artifacts | No |
| LOW | History summary | No |

## The Two-Reasons Rule

Spawn an agent for **exactly two reasons**:

| Reason | Description | Example |
|--------|-------------|---------|
| **Work** | Something needs changing | Code author, test writer |
| **Compression** | Context needs compressing | Impact analyzer, context loader |

### Valid Spawning

| Agent | Reason | Justification |
|-------|--------|---------------|
| `code-implementer` | Work | Writes code |
| `test-author` | Work | Writes tests |
| `impact-analyzer` | Compression | Reads 50k, produces 2k summary |
| `context-loader` | Compression | Reads codebase, produces map |

### Invalid Spawning

| Anti-Pattern | Problem |
|--------------|---------|
| "Coordinator" that routes | That's the orchestrator's job |
| "Validator" that checks boolean | That's a skill/shim |
| "Approver" that rubber-stamps | No cognitive work |
| "Forwarder" that passes data | Zero value-add |

### Spawning Cost

Each spawn costs:
- Fresh context window (~2k tokens overhead)
- Prompt overhead for role definition
- Handoff serialization

**Don't spawn unless:**
1. There's work product at the end, OR
2. You're compressing information that would pollute caller's context

## Context Discipline

### Session Amnesia (Enforced)

Each step starts fresh. Prior chat is NOT a dependency.

**Rehydration sources:**
- Artifacts on disk (primary)
- Handoff envelopes (structured)
- Scent trail (decisions)

**NOT rehydration sources:**
- Conversation history
- Previous step's reasoning
- Abandoned approaches

### Context Pack Structure

```
Context Pack:
├── teaching_notes.md      # CRITICAL - never drop
├── previous_output.md     # HIGH - may truncate
├── artifacts/             # MEDIUM - on-demand
│   ├── spec.md
│   └── adr.md
└── scent_trail.json       # LOW - decisions only
```

## Enforcement Mechanisms

### Budget Enforcement

```python
def load_context(step, budget):
    loaded = 0
    pack = {}

    # CRITICAL: Always load
    pack['teaching_notes'] = load_teaching_notes(step)
    loaded += count_tokens(pack['teaching_notes'])

    # HIGH: Load if budget allows
    if loaded + estimate('previous') <= budget:
        pack['previous'] = load_previous_output(step)
        loaded += count_tokens(pack['previous'])

    # MEDIUM/LOW: Load remainder
    for item in ['artifacts', 'history']:
        if loaded + estimate(item) <= budget:
            pack[item] = load_item(item)
            loaded += count_tokens(pack[item])

    return pack, budget - loaded
```

### Spawn Validation

```python
def validate_spawn(reason, agent_type):
    if reason not in ['work', 'compression']:
        raise InvalidSpawnReason(f"Invalid reason: {reason}")

    if reason == 'work' and not has_output(agent_type):
        raise InvalidSpawn("Work agents must produce artifacts")

    if reason == 'compression' and not compresses_context(agent_type):
        raise InvalidSpawn("Compression agents must reduce context")
```

## The Rule

> Scarcity is a feature, not a bug.
> Budgets enforce discipline.
> Two reasons only for spawning agents.

## Metrics to Track

| Metric | Healthy | Investigate |
|--------|---------|-------------|
| Budget utilization | 60-90% | < 50% or > 95% |
| Spawn count per step | 0-2 | > 3 |
| Context overflow events | Rare | Frequent |
| Compression ratio | > 5:1 | < 2:1 |

---

## See Also
- [context-discipline.md](../execution/context-discipline.md) - Session amnesia rules
- [agent-behavioral-contracts.md](./agent-behavioral-contracts.md) - Role definitions
- [SCARCITY_AS_DESIGN.md](../../docs/explanation/SCARCITY_AS_DESIGN.md) - Teaching doc
