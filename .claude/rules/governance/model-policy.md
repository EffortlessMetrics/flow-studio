# Model Policy: Compute Allocation by Role

Different agent roles have different compute needs. Model policy allocates the right model to each role family.

## The Principle

> Match model capability to task complexity.
> Don't waste expensive models on simple tasks.
> Don't handicap complex tasks with weak models.

## Model Tiers

| Tier | Model | Use Case | Cost |
|------|-------|----------|------|
| **Elite** | opus | Wisdom, complex synthesis | $$$$|
| **Standard** | sonnet | Most work, good balance | $$ |
| **Economy** | haiku | Fast, simple tasks | $ |
| **Primary** | (inherit) | Use parent's model | - |

## Role Family Assignments

| Role Family | Default Model | Rationale |
|-------------|---------------|-----------|
| **Shaping** (yellow) | haiku | Normalization is mechanical |
| **Spec/Design** (purple) | sonnet | Requires judgment |
| **Implementation** (green) | sonnet | Requires reasoning |
| **Critic** (red) | sonnet | Requires careful analysis |
| **Verification** (blue) | haiku | Mostly mechanical checks |
| **Analytics** (orange) | sonnet | Requires pattern recognition |
| **Reporter** (pink) | haiku | Summarization is straightforward |
| **Infrastructure** (cyan) | haiku | Git ops are mechanical |
| **Wisdom** (special) | opus | Requires deep synthesis |
| **Navigator** | haiku | Fast routing decisions |

## Policy Rationale

### Why Wisdom Gets Opus
- Synthesizes across entire runs
- Extracts non-obvious patterns
- Proposes rule changes
- Highest judgment requirement

### Why Shaping Gets Haiku
- Normalizing input format
- Extracting structure
- Low judgment requirement
- High volume

### Why Critics Get Sonnet
- Must find subtle issues
- Needs to understand intent
- Medium-high judgment
- Quality over speed

### Why Navigator Gets Haiku
- Decisions are bounded
- Input is structured (forensics)
- Speed matters
- Low judgment (evidence-based)

## Override Mechanism

Per-agent overrides in `swarm/config/agents/<key>.yaml`:
```yaml
name: special-agent
model: opus  # Override family default
```

Flow-level overrides in flow spec:
```yaml
steps:
  - id: critical-step
    model_override: opus
```

## Cost Control

Model policy is a cost lever:
- Haiku: ~$0.25/M input, $1.25/M output
- Sonnet: ~$3/M input, $15/M output
- Opus: ~$15/M input, $75/M output

A run with 50 steps:
- All Opus: ~$50-100
- Mixed policy: ~$5-15
- All Haiku: ~$1-3

## The Rule

> Allocate model by role, not by step.
> Override only when necessary.
> Default to the cheapest model that works.

## Policy Enforcement

Model policy is defined in:
```
swarm/config/model_policy.json
```

Schema:
```json
{
  "tiers": {
    "primary": "inherit",
    "economy": "haiku",
    "standard": "sonnet",
    "elite": "opus"
  },
  "role_families": {
    "shaping": "economy",
    "spec": "standard",
    "implementation": "standard",
    "critic": "standard",
    "verification": "economy",
    "analytics": "standard",
    "reporter": "economy",
    "infra": "economy",
    "wisdom": "elite",
    "router": "economy"
  }
}
```

## Monitoring

Track model usage to optimize policy:
- Tokens per role family
- Cost per flow
- Quality correlation with model

Adjust policy based on evidence, not intuition.

## Current Implementation

See `swarm/config/model_policy.json` for current assignments.
Validation ensures agent models are valid values.
