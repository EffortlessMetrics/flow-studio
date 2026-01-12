# Context Discipline: Why Forgetfulness is a Feature

> **Status:** Living document
> **Purpose:** Explain session amnesia, rehydration, and the economics of focused context

## The Problem

Long conversations accumulate irrelevant context.

A 50-step flow with full conversation history would include:
- Abandoned approaches from step 3
- Misunderstandings resolved in step 7
- Tangential explorations from step 12
- Stale assumptions invalidated in step 20

By step 50, the model is reasoning against a pile of noise. Instructions from
step 1 are buried under 49 steps of accumulated history. The model drifts from
its instructions because those instructions are lost in the noise.

This is **context pollution**. It causes:
- Inconsistent behavior (different parts of history suggest different actions)
- Instruction drift (early guidance buried under later noise)
- Degraded reasoning (signal-to-noise ratio collapses)
- Token waste (paying to process irrelevant history)

## The Physics

**Intelligence degrades as irrelevant history grows.**

This isn't a model flaw to be fixed. It's a fundamental property of attention:
limited context window means every irrelevant token crowds out a relevant one.

The longer the conversation, the worse the reasoning. Not because models are bad,
but because attention is finite and history is noisy.

## The Solution: Session Amnesia

Each step starts fresh. Prior chat is NOT a dependency.

This seems counterintuitive. Shouldn't steps remember what happened before?
Yes, but through **artifacts**, not conversation.

| Memory Type | Stored In | Survives Session Reset |
|-------------|-----------|------------------------|
| Conversation | Chat context | No |
| Decisions | Scent trail | Yes |
| Outputs | Disk artifacts | Yes |
| State | Handoff envelopes | Yes |

**Disk is memory. Chat is ephemeral.**

## What This Means: The Rehydration Pattern

Steps don't inherit conversation. They receive a **Context Pack**:

```
Context Pack:
├── teaching_notes.md      # What this step must do
├── previous_output.md     # Key output from prior step
├── artifacts/             # Referenced files (lazy-loaded)
│   ├── spec.md
│   └── adr.md
└── scent_trail.json       # How we got here
```

### Context Pack Components

| Component | Purpose | Token Budget |
|-----------|---------|--------------|
| Teaching Notes | Step-specific instructions | Always loaded (CRITICAL) |
| Previous Output | What just happened | Budgeted (HIGH) |
| Artifacts | Referenced files | On-demand (MEDIUM) |
| Scent Trail | Decision breadcrumbs | If budget allows (LOW) |

The **scent trail** answers: "What decisions led here?" It's a compressed
record of key choices, not a replay of reasoning.

## The Priority Hierarchy

When context must be loaded, priority determines what survives:

| Priority | Content | Drop Behavior |
|----------|---------|---------------|
| CRITICAL | Teaching notes, step spec | Never drop |
| HIGH | Previous step output | Drop last |
| MEDIUM | Referenced artifacts | Truncate if needed |
| LOW | History summary, scent trail | Drop first |

### Budget Overflow Handling

When input exceeds the token budget:

1. Drop LOW priority items first (history summary)
2. Truncate MEDIUM priority items (old artifacts)
3. Preserve HIGH priority items (previous output)
4. Never truncate CRITICAL items (teaching notes)

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

## Why Forgetfulness is Error Correction

Session amnesia isn't losing information. It's resetting the error vector.

Conversation history accumulates errors: misunderstandings from early steps,
abandoned approaches still in context, stale assumptions later corrected.
Each step adds its own noise. By step N, the model reasons against N steps
of accumulated error.

Fresh context acts as error correction. Each step starts from curated,
validated artifacts. Stale assumptions don't persist. Abandoned approaches
don't pollute. Only decisions that produced artifacts survive.

The artifact is the checkpoint; the conversation is the scratch pad.

## The Economics

Focused context = peak reasoning density.

### Token Efficiency

| Approach | Tokens Used | Signal/Noise Ratio |
|----------|-------------|-------------------|
| Full conversation history | 100k+ | Low (mostly noise) |
| Curated context pack | 10-20k | High (all signal) |

Smaller, focused context means:
- Every token contributes to reasoning
- Less compute per step
- Faster iteration cycles
- Better outcomes

### The Compound Effect

Error correction compounds: Step 1 starts clean, Step 2 inherits only Step 1's
artifacts (validated), Step 3 inherits Step 2's artifacts (not Step 1's reasoning).
By step 50, you've had 49 error-correction resets versus 49 steps of accumulated noise.

## The Two Reasons Rule

Spawn an agent for **exactly two reasons**:

| Reason | Description | Example |
|--------|-------------|---------|
| **Work** | Something needs changing | `code-implementer`, `test-author` |
| **Compression** | Context needs compressing | `context-loader`, `impact-analyzer` |

If neither applies, don't spawn. The operation belongs in the current context
or in a lightweight shim.

**Valid spawning:** `code-implementer` (work: writes code), `test-author` (work: writes tests),
`impact-analyzer` (compression: reads 50k, produces 5k), `context-loader` (compression: builds map).

**Invalid spawning:** "Coordinator" that routes (orchestrator's job), "Validator" that checks
boolean (skill/shim), "Approver" that rubber-stamps (no cognitive work), "Forwarder" that
passes data (zero value-add).

Each spawn costs ~2k tokens overhead. Unnecessary agents dilute focus.

## Heavy Context Loading: The Exception

Some agents intentionally load large context:

| Agent | Input | Output | Purpose |
|-------|-------|--------|---------|
| `context-loader` | 20-50k | 5k | Build codebase map |
| `impact-analyzer` | 30k | 3k | Assess change impact |

These agents exist to **compress** context for downstream consumers. They're
the funnel, not the norm. Compute is cheap; reducing downstream re-search
saves attention. A `context-loader` that reads 50k and produces 5k saves
every downstream agent from reading the same 50k.

## Rehydration vs Conversation History

| Conversation History | Rehydration |
|---------------------|-------------|
| Everything that was said | What matters now |
| Includes abandoned paths | Only successful outputs |
| Accumulates noise | Fresh each step |
| Grows unbounded | Budget-controlled |

**Rehydration sources:** Artifacts on disk, handoff envelopes, scent trail.

**NOT rehydration sources:** Conversation transcripts, previous step's internal
reasoning, exploration and abandoned approaches.

## The Rule

> Context discipline + disk-based resumption.
> Load only what's needed; rely on artifacts for continuity, not chat history.

Each step is a fresh start with curated input. The model gets exactly what it
needs to do its job, nothing more.

## Related Documents

- [SCARCITY_AS_DESIGN.md](./SCARCITY_AS_DESIGN.md) - Why limits are features
- [COMPRESSION_AS_VALUE.md](./COMPRESSION_AS_VALUE.md) - The art of throwing away
- [.claude/rules/execution/context-discipline.md](../../.claude/rules/execution/context-discipline.md) - Enforced rule
- [.claude/rules/governance/scarcity-enforcement.md](../../.claude/rules/governance/scarcity-enforcement.md) - Budget enforcement
