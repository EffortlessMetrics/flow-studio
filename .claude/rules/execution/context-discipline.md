# Context Discipline

**"Intelligence degrades as irrelevant history grows."**

## Law of Session Amnesia

Each step starts fresh. Prior chat is NOT a dependency.

### The Problem
- Long conversations accumulate irrelevant context
- Models drift from instructions over time
- "Context pollution" causes inconsistent behavior

### The Solution
- Context is rehydrated from **artifacts**, not conversation
- A curator chooses *small* context; workers run with "fresh eyes"
- Disk is memory; chat is ephemeral

## Context Loading Hierarchy

### What Gets Loaded (Priority Order)

1. **Teaching Notes** - Step-specific instructions (always loaded)
2. **Recent Step Output** - Previous step's key output (budgeted)
3. **Relevant Artifacts** - Files referenced by teaching notes (on-demand)
4. **History Summary** - Compressed previous steps (if budget allows)

### What Does NOT Get Loaded

- Full conversation transcripts
- Irrelevant file contents
- Previous step's internal reasoning
- Abandoned approaches

## Budget Enforcement

Context budgets are enforced per flow:

```yaml
context_budgets:
  signal:
    history_chars: 15000
    recent_step_chars: 8000
  build:
    history_chars: 20000
    recent_step_chars: 10000
```

When budget is exceeded:
1. Drop LOW priority items first
2. Preserve CRITICAL items (teaching notes, specs)
3. Truncate MEDIUM items (history summaries)
4. Never truncate step's own teaching notes

## Rehydration Pattern

Steps receive a **Context Pack**, not raw history:

```
Context Pack Contents:
├── teaching_notes.md      # What this step must do
├── previous_output.md     # Key output from prior step
├── artifacts/             # Referenced files (lazy-loaded)
│   ├── spec.md
│   └── adr.md
└── scent_trail.md         # Breadcrumbs to prior decisions
```

The **scent trail** answers: "What decisions led here?"

## The Rule

> Context discipline + disk-based resumption.
> Load only what's needed; rely on artifacts for continuity, not chat history.

## Heavy Context Loading Exception

Some agents are designed to load large context:

- `context-loader` - Loads 20-50k tokens intentionally
- `impact-analyzer` - Needs broad codebase view

These agents compress context for downstream consumers.
Compute is cheap; reducing downstream re-search saves attention.
