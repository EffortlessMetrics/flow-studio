# Scent Trail: Decision Provenance

> **Status:** Living document
> **Purpose:** Explain how agents know "how we got here" without re-litigating settled decisions

## The Problem

Step 5 of a flow receives control. The agent looks at its inputs and wonders:

- "Why are we using OAuth instead of API keys?"
- "Was the auth library chosen, or should I evaluate options?"
- "Is the 24-hour session timeout a requirement or a guess?"

Without decision history, the agent has two bad options:
1. **Assume and risk contradiction** - Work against prior decisions
2. **Re-derive everything** - Waste tokens re-analyzing settled questions

Both are expensive. One causes inconsistency. The other wastes 5-10x tokens.

## The Physics

### Session Amnesia is a Feature

Each step starts fresh. Prior chat history is NOT carried forward.
This is intentional - context pollution degrades intelligence.

But "how we got here" is different from "what was said."
Decisions are the subset of history worth preserving.

### Decisions Have Persistence Value

Some choices matter beyond the step that made them:

| Decision Type | Persistence Value | Example |
|---------------|-------------------|---------|
| Architectural | HIGH | "Use OAuth not API keys" |
| Technology | HIGH | "Use existing auth library" |
| Assumption | MEDIUM | "Users have email addresses" |
| Approach | MEDIUM | "Optimize for readability over performance" |
| Variable naming | NONE | "Call it `user_id` not `userId`" |

The scent trail captures HIGH and MEDIUM persistence decisions.
LOW and NONE stay where they're made.

## The Solution: Compact Breadcrumbs

The scent trail is a JSON file passed between steps:

```json
{
  "scent_trail": {
    "flow_objective": "Implement user authentication",
    "decisions": [
      {
        "step": "signal-step-2",
        "decision": "Use OAuth over API keys",
        "rationale": "User requested 'standard login flow'",
        "alternatives_rejected": ["API keys", "Magic links"],
        "confidence": "HIGH"
      }
    ],
    "assumptions_in_effect": [
      {
        "assumption": "Users have email addresses",
        "made_at": "signal-step-1",
        "impact_if_wrong": "Would need alternative identifier"
      }
    ],
    "open_questions": [
      "Session duration not specified; using 24h default"
    ]
  }
}
```

Step 5 reads this and knows:
- OAuth was decided in step 2 (don't re-evaluate)
- Auth library was chosen per ADR-005 (don't question it)
- 24h session is a default, not a requirement (may need clarification)

## What Gets Recorded

### Add to Trail

Non-trivial choices with downstream impact:

| Category | Example | Why Record |
|----------|---------|------------|
| Architectural | "Use event sourcing" | Affects all downstream code |
| Technology | "Use PostgreSQL" | Affects queries, migrations |
| Approach | "Fail fast with exceptions" | Affects error handling pattern |
| Assumption | "Single-tenant deployment" | Affects security model |
| Interpretation | "Login means OAuth" | Affects auth implementation |

### Do NOT Add

Mechanical or step-local choices:

| Category | Example | Why Skip |
|----------|---------|----------|
| Variable names | "`user_id` vs `userId`" | Doesn't affect other steps |
| Formatting | "4 spaces vs tabs" | Linter handles it |
| Import order | "stdlib before third-party" | Style guide handles it |
| Internal structure | "Helper function vs inline" | Step-local |

The filter: "Would a future step need to know this?"

## The Consumption Protocol

Agents receiving a scent trail should:

1. **Read before starting** - Know the decision landscape
2. **Respect prior decisions** - Don't re-litigate without cause
3. **Add new decisions** - Extend the trail for downstream
4. **Flag conflicts** - When current findings contradict prior decisions

### Example: Respecting Prior Decisions

```markdown
## Context
Per scent trail: OAuth selected (signal-step-2), auth library mandated (plan-step-3).

## My Work
Implementing the OAuth callback handler using the auth library...

## Decision Added
Using PKCE flow for security (alternatives: implicit flow - rejected per OWASP)
```

The agent doesn't waste tokens on "should we use OAuth?" - that's settled.

## Conflict Handling

Sometimes current analysis reveals problems with prior decisions.

### The Wrong Response: Silent Override

Agent finds that the target API only supports API keys.
Agent implements API keys without mentioning OAuth decision.
Result: Inconsistency between documented decision and implementation.

### The Right Response: Flag and Document

```json
{
  "conflict": {
    "prior_decision": "Use OAuth (signal-step-2)",
    "current_finding": "Target API requires API key auth",
    "recommendation": "Escalate - fundamental assumption invalid",
    "impact": "Significant rework if we proceed with OAuth"
  }
}
```

The conflict becomes visible. A human or upstream step can resolve it.

## The Economics

### Cost: ~500-1000 tokens per step

The scent trail adds to every step's context:
- Storage: ~1-2KB per run
- Context load: ~500-1000 tokens per step

For a 20-step flow: ~10-20k extra tokens total.

### Savings: 5-10x in re-litigation prevention

Without scent trail, each step might spend:
- 2-3k tokens re-evaluating settled decisions
- Additional tokens when contradicting prior choices
- Human time resolving inconsistencies

For a 20-step flow: ~40-60k tokens in re-litigation.

### Net: 3-5x token savings + consistency

The math is clear. Small upfront cost. Large downstream savings.
Plus: consistent decisions, traceable provenance, debuggable runs.

## File Placement

Scent trails live at:
```
RUN_BASE/<flow>/scent_trail.json
```

Updated after each step that makes decisions.
Read by each step before starting.

## The Context Pack

The scent trail is one of four elements in each step's context:

```
Context Pack:
  teaching_notes.md      # What to do (instructions)
  previous_output.md     # What just happened (recent history)
  scent_trail.json       # How we got here (decisions)
  artifacts/             # Referenced files (evidence)
```

Teaching notes say "what." Previous output says "what's recent."
Scent trail says "what's settled."

## Anti-Patterns

### Recording Everything

Bad scent trail:
```json
{
  "decisions": [
    { "decision": "Named variable 'config'" },
    { "decision": "Put imports at top" },
    { "decision": "Used f-strings" },
    // 50 more trivial entries
  ]
}
```

This is noise, not signal. Future steps drown in irrelevant details.

### Recording Nothing

Empty scent trail. Step 5 re-derives OAuth decision.
Step 6 contradicts it. Step 7 assumes API keys.
Inconsistent output. Wasted tokens. Confused humans.

### Silent Override

Agent finds conflict but doesn't flag it.
Implements something different.
Breaks consistency. Loses trust. Hard to debug.

## The Rule

> Every step receives and updates the scent trail.
> Prior decisions are respected unless explicitly revisited.
> Conflicts are flagged, not silently overridden.

## What This Means

### For Agent Design

Agents should:
- Read scent trail in preamble
- Reference prior decisions when relevant
- Add significant decisions to trail
- Flag conflicts explicitly

### For Debugging

When output is inconsistent:
- Check scent trail for decision history
- Look for missing decisions (why wasn't this recorded?)
- Look for silent overrides (why was this contradicted?)

### For Humans

Scent trail is a decision audit:
- What was decided?
- When was it decided?
- Why was it decided?
- What alternatives were rejected?

Faster debugging. Clearer reviews. Traceable reasoning.

## Related Documents

- [CONTEXT_BUDGETS.md](../CONTEXT_BUDGETS.md) - How budgets control input context
- [COMPRESSION_AS_VALUE.md](./COMPRESSION_AS_VALUE.md) - Why less context is better
- [SCARCITY_AS_DESIGN.md](./SCARCITY_AS_DESIGN.md) - Why limits are features
- [.claude/rules/artifacts/scent-trail.md](../../.claude/rules/artifacts/scent-trail.md) - Enforcement rules
