# Scent Trail: Decision Provenance

How does an agent know "how we got here"? The scent trail provides breadcrumbs of prior decisions.

## The Problem

Without decision history:
- Agents re-litigate settled decisions
- Context for "why this approach" is lost
- Same debates happen every step
- Wasted tokens on redundant reasoning

## The Solution: Scent Trail

A scent trail is a compact summary of:
- Key decisions made
- Why they were made
- What alternatives were rejected
- What assumptions are in effect

## Scent Trail Schema

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
      },
      {
        "step": "plan-step-3",
        "decision": "Use existing auth library",
        "rationale": "ADR-005 mandates no custom crypto",
        "alternatives_rejected": ["Custom JWT implementation"],
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

## When to Update Scent Trail

### Add Decision
When a non-trivial choice is made:
- Architectural decision
- Technology choice
- Approach selection
- Assumption adoption

### Don't Add
Trivial or mechanical choices:
- Variable naming
- Formatting
- Import ordering

## Scent Trail in Context Pack

The scent trail is included in the Context Pack for each step:

```
Context Pack:
  teaching_notes.md      # What to do
  previous_output.md     # What just happened
  scent_trail.json       # How we got here
  artifacts/             # Referenced files
```

## Consuming Scent Trail

Agents should:
1. Read scent trail before starting
2. Respect prior decisions unless explicitly revisiting
3. Add new decisions to trail
4. Flag conflicts with prior decisions

### Example Usage

```markdown
## Context
Per scent trail, we're using OAuth (decided in signal-step-2)
with the auth library (decided in plan-step-3).

## My Work
Implementing the OAuth callback handler...

## Decision Added
Using PKCE flow for security (alternatives: implicit flow - rejected per OWASP guidelines)
```

## Conflict Handling

When current analysis conflicts with prior decision:

### Don't Silently Override
Bad: Just do it differently

### Do Flag and Document
Good:
```json
{
  "conflict": {
    "prior_decision": "Use OAuth",
    "current_finding": "API requires API key auth",
    "recommendation": "Escalate - fundamental assumption invalid",
    "impact": "Significant rework if we proceed with OAuth"
  }
}
```

## File Placement

Scent trails are written to:
```
RUN_BASE/<flow>/scent_trail.json
```

Updated after each step that makes decisions.

## The Rule

> Every step receives and updates the scent trail.
> Prior decisions are respected unless explicitly revisited.
> Conflicts are flagged, not silently overridden.

## Economics

Scent trail costs:
- Storage: ~1-2KB per run
- Context: ~500-1000 tokens per step

Scent trail saves:
- Re-litigation: 5-10x token savings
- Consistency: Fewer contradictions
- Debugging: Clear decision history
