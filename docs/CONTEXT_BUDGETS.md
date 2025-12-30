# Context Budgets

This document explains the philosophy behind context budgets in stepwise execution.

---

## Quick Reference

### Budget Presets

| Preset | Total Budget | Recent Step | Older Steps | Best For |
|--------|-------------|-------------|-------------|----------|
| **Lean** | 100,000 | 30,000 | 5,000 | Fast iteration, 128k models, small changes |
| **Balanced** (default) | 200,000 | 60,000 | 10,000 | Most use cases, 200k models |
| **Heavy** | 400,000 | 120,000 | 20,000 | Context-heavy flows, large codebases, 200k+ models |

### When to Tune

- **Seeing `[CONTEXT_TRUNCATED]` in prompts?** Increase `context_budget_chars`
- **Prompts tiny compared to window?** Lower budgets to save cost
- **Context-loader missing files?** Bump `history_max_recent_chars`
- **Using small models (128k)?** Switch to Lean preset

---

## Context Packs: Per-Step Briefings, Not Logs

**Context is regenerated per step, not accumulated.**

Each step receives a **curated context pack**—a fresh briefing assembled specifically for that step's execution. This is fundamentally different from a "growing log" model:

| Model | How It Works | Problem |
|-------|--------------|---------|
| **Growing Log** (wrong) | Each step sees all previous output, accumulating forever | Context window explodes; model loses focus |
| **Per-Step Briefing** (correct) | Each step gets a curated pack: teaching notes + relevant history + upstream artifacts | Focused execution; manageable window |

### What Goes Into a Context Pack

The **Curator** (or ContextPackBuilder) assembles each step's context:

1. **Teaching Notes** (always included, never truncated)
   - Step objectives, inputs, outputs
   - Emphasizes, constraints
   - From flow config YAML

2. **Relevant History** (budget-constrained)
   - Most recent step: full output (up to `history_max_recent_chars`)
   - Older steps: summarized/truncated (up to `history_max_older_chars` each)
   - Selected by **priority**, not just recency

3. **Upstream Artifacts** (if configured)
   - Key outputs from previous flows
   - Referenced by path, not inlined

4. **Scent Trail** (if configured)
   - Breadcrumb hints about overall flow state
   - Minimal metadata, not full history

### The Curator's Role

The Curator decides **what each step needs to know**, not **everything that happened**. This is deliberate curation, not mindless accumulation.

```
Step N Context Pack = Curator(
  teaching_notes: step.teaching,       // Always included
  recent_history: history[-1],         // Full detail
  older_history: summarize(history[:-1]),  // Condensed
  upstream: select_relevant(artifacts),    // Curated
  budget: runtime_config.budgets       // Bounded
)
```

This model enables **long flows** (20+ steps) without context explosion. Each step operates with focused context, not a polluted window.

---

## The Curator Pattern

### The Problem

Workers shouldn't waste tokens searching for context. Context preparation is logistics, not intelligence.

When an expensive model (Sonnet) spends its first 500 tokens grepping for relevant files, that's wasted compute. The model is doing janitorial work—gathering files, checking what exists, summarizing prior history—instead of the actual cognitive task it was invoked for.

This is a fundamental mismatch:
- **High-capability models** are optimized for reasoning, synthesis, and generation
- **Context gathering** is mechanical work that doesn't require advanced reasoning
- **Burning expensive tokens on logistics** is pure waste

### The Solution

Use a cheap model (Haiku) as a **Curator** to prepare context before the expensive model (Sonnet) executes.

The Curator is a logistics specialist:
- Reads the flow state and upcoming step requirements
- Gathers relevant files from the codebase
- Summarizes history and upstream artifacts
- Packs everything into a `ContextPack` ready for the Worker

The Worker receives a fully-prepared briefing and can immediately start its real job.

### The Workflow

```
Orchestrator: "Next step is Test-Author"
     │
     ▼
Curator (Haiku): "I see requirements.json and impl_summary.md in the
                  handoff. I'll grab relevant code files (src/user.ts,
                  src/user.test.ts) and pack them into the ContextPack."
     │
     ▼
Worker (Sonnet): Starts with exactly the files it needs.
                 Zero time wasted searching.
                 Immediately writes tests.
```

This separation of concerns means:
- Haiku does the mechanical file gathering (cheap)
- Sonnet does the cognitive work (expensive but focused)
- No tokens wasted on grep/find/ls by the expensive model

### The Cognitive Pipeline

The Curator pattern fits into a larger cognitive pipeline where each stage uses the appropriate model tier:

| Stage | Role | Responsibility | Context Scope | Model Tier |
|-------|------|----------------|---------------|------------|
| **Prep** | Curator (Haiku) | Logistics—gather files, summarize history | Wide (scan codebase) | Cheap |
| **Work** | Worker (Sonnet) | Execution—write code/tests | Deep (specific files) | Expensive |
| **Verify** | Forensic Analyst | Truth—semantic diff interpretation | Narrow (diffs, logs) | Medium |
| **Route** | Navigator (Sonnet) | Strategy—decide path | Wide (graph, summary) | Expensive |
| **Commit** | Kernel (Python) | Physics—update ledger | None (pure mechanics) | None |

Each stage operates at a different scope:
- **Wide scope** (Curator, Navigator): Needs to see the forest, not every tree
- **Deep scope** (Worker): Needs full detail on specific files
- **Narrow scope** (Forensic): Needs precise view of what changed

### Cost-Benefit Analysis

The economics are compelling:

| Activity | Without Curator | With Curator |
|----------|-----------------|--------------|
| Context gathering | Sonnet spends 30-60s, 2k tokens searching | Haiku spends 10s, 500 tokens |
| Worker start | Delayed, context polluted with search noise | Immediate, clean context |
| Cost per step | ~$0.15 wasted on logistics | ~$0.01 on Haiku curation |
| Total savings | — | ~$0.14 per step, cleaner outputs |

**Spending 10 seconds and a few cents on Haiku curation saves minutes and dollars on Sonnet re-searching.**

Over a 20-step flow, this adds up to meaningful cost reduction and, more importantly, cleaner execution. The Worker never sees grep output, file listings, or search artifacts—just the prepared context it needs.

### Implementation Notes

The Curator pattern is implemented in `swarm/runtime/curator.py`:

```python
class ContextCurator:
    """Prepares ContextPacks using a cheap model."""

    def prepare(self, step: StepConfig, history: List[StepOutput]) -> ContextPack:
        # 1. Read step requirements (inputs, emphasizes)
        # 2. Identify relevant files from history and codebase
        # 3. Summarize older history items
        # 4. Pack into ContextPack with token budget
        ...
```

Key design decisions:
- Curator runs **synchronously before each step** (adds ~10s latency, saves much more)
- Curator uses **teaching notes** to understand what files matter
- Curator outputs a **ContextPack** that the Worker receives as its entire context
- Curator failures are **non-fatal**—fall back to basic history selection

### When to Use the Curator

The Curator pattern is most valuable when:
- Steps have complex context requirements (multiple files, cross-module dependencies)
- The codebase is large (>100 files)
- Flows are long (10+ steps)
- Cost optimization matters

For simple flows with small codebases, the overhead of Curator invocation may not be worth it. The pattern can be disabled per-profile or per-flow via `curator_enabled: false` in config.

---

## The Core Distinction

**Budgets control INPUT context selection, not OUTPUT generation limits.**

| Concern | What It Is | How It Works |
|---------|-----------|--------------|
| **INPUT budget** | How much history/context to include in prompts | Prioritize recent steps, summarize older ones |
| **OUTPUT** | What agents generate | Agents write complete outputs; no truncation |

This distinction is critical: budgets shape *what goes into the prompt*, not *how much the model can say*.

---

## Why This Matters

LLMs can drift or lose focus with unbounded context. Budgets ensure:

1. **Most recent/relevant context is prioritized** - Recent step outputs get more tokens
2. **Older context is summarized or omitted** - Older steps get fewer chars, with truncation notes
3. **Prompt size stays manageable** - Total history is bounded
4. **Teaching notes have priority** - Step-specific guidance is never truncated

The goal is **focused execution**: each step gets the context it needs without drowning in irrelevant history.

---

## What Budgets Are NOT

Budgets are NOT:

- **Generation caps** - Agents write complete outputs; we don't cut them off mid-thought
- **Token limits on responses** - If a step hits a generation limit, that's a hard failure, not graceful degradation
- **Reasons to truncate receipts** - Receipts capture full agent output

If you find yourself thinking "let's cap output to save tokens," stop. Shape the flow with **context selection** and **teaching notes**, not output truncation.

---

## Current Defaults

From `swarm/config/runtime.yaml`:

```yaml
defaults:
  # For 200k token models (~800k chars context window)
  # Reserve ~25% for history, leaving ample room for CLAUDE.md, agents, and completion
  context_budget_chars: 200000    # ~50k tokens of history (INPUT selection)
  history_max_recent_chars: 60000   # Most recent step gets rich detail (~15k tokens)
  history_max_older_chars: 10000    # Older steps get meaningful summaries (~2.5k tokens each)
  timeout_seconds: 30             # Execution timeout (quality gate, not output cap)
```

### Budget Sizing Rationale

These defaults are sized for **200k token context windows** (Claude Sonnet 4, etc.):

| Budget | Characters | ~Tokens | % of Window | Purpose |
|--------|------------|---------|-------------|---------|
| Total history | 200,000 | ~50k | ~25% | Leave ample room for CLAUDE.md (~40k tokens), agent prompts, and completion |
| Recent step | 60,000 | ~15k | ~7.5% | Detailed output from immediately preceding step |
| Older steps | 10,000 each | ~2.5k each | varies | Meaningful summaries, not tweet-sized fragments |

**Key insight**: The ~25% allocation balances context needs with the reality that CLAUDE.md and agent definitions consume significant window space. This leaves room for the complete instruction set while providing enough history for continuity.

### Tuning for Different Model Sizes

If targeting smaller context windows, scale proportionally:

| Model Window | Suggested `context_budget_chars` | Recent | Older |
|--------------|----------------------------------|--------|-------|
| 200k tokens | 200,000 (default) | 60,000 | 10,000 |
| 128k tokens | 125,000 | 40,000 | 7,500 |
| 32k tokens | 30,000 | 10,000 | 2,500 |

Override in `runtime.yaml` or via environment variables.

---

## How History Selection Works

The engines (`GeminiStepEngine`, `ClaudeStepEngine`) read budget values from config and apply them in `_build_prompt()`:

1. **Config-driven** - Budgets come from `runtime_config.py` which reads `runtime.yaml`
2. **Reverse iteration** - Process history most-recent-first
3. **Per-step truncation** - Recent step: up to 60k chars; older steps: up to 10k chars each
4. **Global budget check** - Stop adding steps when total exceeds 200k chars
5. **Truncation note** - Insert message if older steps were omitted

This ensures each step sees relevant recent context without prompt explosion.

---

## Teaching Notes: High-Priority Context

Teaching notes (`inputs`, `outputs`, `emphasizes`, `constraints`) are injected into prompts **before history** and are **never truncated**. They define what each step should focus on.

See flow YAML files in `swarm/config/flows/` for per-step teaching notes.

---

## Budget Philosophy Summary

| Principle | Implementation |
|-----------|----------------|
| Budget for selection, not truncation | Character budgets on history, not generation limits |
| Agents write complete outputs | No max_tokens caps in normal operation |
| Recent context prioritized | Most recent step gets ~15k tokens |
| Older context still meaningful | Older steps get ~2.5k tokens, not 200 chars |
| Teaching notes sacred | Never truncated, always included |
| Failure is explicit | If generation somehow truncates, that's a failure to investigate |
| Config-driven | All values read from runtime.yaml, not hardcoded |

---

## Configuration Reference

### Runtime Config Functions

```python
from swarm.config.runtime_config import (
    get_context_budget_chars,      # Total history budget (default: 200000)
    get_history_max_recent_chars,  # Recent step max (default: 60000)
    get_history_max_older_chars,   # Older step max (default: 10000)
)
```

### Environment Variable Overrides

You can override any default via the standard config mechanism. Edit `runtime.yaml` directly or use environment variables through the config system.

---

## Configurability (v2.4.0)

Starting in v2.4.0, context budgets can be overridden at multiple levels, enabling fine-grained control for different flows and steps.

### Override Hierarchy

Budget values are resolved in priority order (highest to lowest):

1. **Step-level override** - Most specific; set per-step in flow YAML
2. **Flow-level override** - Applies to all steps in a flow
3. **Profile-level override** - Applies when a profile is active
4. **Global defaults** - Values in `runtime.yaml`

Higher-priority overrides completely replace lower-priority values (no merging).

### Per-Profile Overrides

Set budget overrides in your profile YAML (`swarm/profiles/<profile-id>.swarm_profile.yaml`):

```yaml
# Profile with larger budgets for context-heavy work
profile_id: "heavy-context"
description: "Profile for large codebase analysis"

budget_overrides:
  context_budget_chars: 300000      # ~75k tokens
  history_max_recent_chars: 100000  # ~25k tokens
  history_max_older_chars: 15000    # ~3.75k tokens
```

When this profile is active, all flows use these budgets unless further overridden.

### Per-Flow Overrides

Set budget overrides in flow config (`swarm/config/flows/<flow>.yaml`):

```yaml
# swarm/config/flows/build.yaml
flow: build
description: "Plan -> Draft flow"

budget_overrides:
  context_budget_chars: 250000      # Build flow needs more context
  history_max_recent_chars: 80000

steps:
  - id: "0"
    agent: context-loader
    # ...
```

Build flow is a good candidate for larger budgets due to its context-heavy nature.

### Per-Step Overrides

Set budget overrides on individual steps within a flow:

```yaml
# swarm/config/flows/build.yaml
steps:
  - id: "0"
    agent: context-loader
    budget_overrides:
      context_budget_chars: 300000    # Context loader needs maximum history
      history_max_recent_chars: 100000

  - id: "1"
    agent: test-author
    # Uses flow-level or global defaults
```

This is useful when specific agents (like `context-loader` or `impact-analyzer`) benefit from seeing more history.

### Flow Studio UI

Flow Studio provides a visual interface for editing budget overrides:

1. Select a flow in the sidebar
2. Click on a step in the canvas
3. Use the "Context Budget" section in the step inspector
4. Changes are saved to the flow YAML

The UI shows effective budgets (after hierarchy resolution) and highlights overrides.

### When to Override Budgets

**Increase budgets for:**
- `context-loader` steps that need comprehensive codebase understanding
- `impact-analyzer` steps analyzing large changesets
- Build flow when working with complex multi-file changes
- Profiles targeting large codebases

**Decrease budgets for:**
- Fast iteration on small changes
- Steps that need only immediate context (critics, fixers)
- Profiles targeting smaller context window models

---

## Why ~50k Tokens (v2.4.0 Philosophy)

The v2.4.0 default of ~50k tokens (~200k chars) for history represents a deliberate balance:

### Window Allocation Model

For a 200k token context window:

| Component | ~Tokens | % of Window |
|-----------|---------|-------------|
| CLAUDE.md + agent instructions | ~40k | ~20% |
| Teaching notes + step config | ~10k | ~5% |
| **History budget** | **~50k** | **~25%** |
| Completion headroom | ~100k | ~50% |

### Rationale

1. **CLAUDE.md is substantial**: The root CLAUDE.md and swarm-level instructions can consume 30-50k tokens. Previous 100k history budgets risked prompt truncation.

2. **Agent prompts add up**: Each agent definition adds tokens. With 48 agents and rich prompts, this is non-trivial.

3. **Completion needs room**: Complex outputs (code, tests, ADRs) need generation headroom. 50% reserved ensures no truncation.

4. **Flexibility via overrides**: The lower default is safe for all flows; heavy-context flows can override upward.

5. **Works across models**: 50k history works well for 128k and 200k windows. Previous defaults were too aggressive for smaller windows.

### When Previous Defaults Made Sense

The v2.3.0 defaults (100k tokens / 400k chars) were appropriate when:
- CLAUDE.md was smaller
- Agent prompts were minimal
- Only 200k+ token windows were targeted

If your setup matches these conditions, increase budgets via profile or flow overrides.

---

## Migration from v2.3

If upgrading from v2.3.x, note the following default changes:

| Setting | v2.3.x | v2.4.0 | Change |
|---------|--------|--------|--------|
| `context_budget_chars` | 400,000 | 200,000 | -50% |
| `history_max_recent_chars` | 120,000 | 60,000 | -50% |
| `history_max_older_chars` | 20,000 | 10,000 | -50% |

### Why the Change

The v2.3 defaults allocated ~50% of the context window to history, which worked for simple setups but caused issues as:
- CLAUDE.md grew with more comprehensive documentation
- Agent prompt complexity increased
- Users targeted varied context window sizes

The v2.4 defaults (~25% for history) provide a safer baseline that works across configurations.

### Preserving v2.3 Behavior

To restore v2.3 budget behavior, create a profile or update `runtime.yaml`:

```yaml
# In runtime.yaml or profile YAML
budget_overrides:
  context_budget_chars: 400000
  history_max_recent_chars: 120000
  history_max_older_chars: 20000
```

Or override at the flow level for context-heavy flows like Build.

### Recommended Approach

Start with v2.4 defaults and override upward only where needed. Monitor for context truncation warnings in transcripts. The configurability features let you tune precisely rather than using one-size-fits-all settings.

---

## Guardrails (v2.5.0)

Starting in v2.5.0, the context budget system includes defensive guardrails to prevent
misconfigured budgets from causing runtime issues.

### Sanity Bounds

All budget values are validated and clamped to sanity bounds:

| Setting | Minimum | Maximum | Warning Threshold |
|---------|---------|---------|-------------------|
| All budget values | 10,000 chars | 600,000 chars | 5,000,000 chars |

- **Minimum (10k chars)**: Ensures at least one meaningful history step can be included
- **Maximum (600k chars)**: Safe upper bound for 200k token context windows
- **Warning threshold**: Values above 5M chars trigger a warning log

### Relational Constraints

The resolver enforces these invariants:
- `history_max_recent_chars <= context_budget_chars`
- `history_max_older_chars <= context_budget_chars`

If violated, values are clamped with a warning.

### Truncation Warnings

When history is truncated due to budget constraints, engines add a machine-readable
warning to the prompt and receipt:

```
[CONTEXT_TRUNCATED] Included 7 of 19 history steps (12 omitted, budget: 200,000/200,000 chars)
```

---

## Priority-Aware History Selection (v2.5.0)

Starting in v2.5.0, history truncation uses **priority-based selection** instead of simple recency.
When the context budget is exceeded, low-value items are dropped before high-value items.

### Priority Levels

History items are classified into four tiers based on the agent that produced them:

| Priority | Value | Agents | Role |
|----------|-------|--------|------|
| **CRITICAL** | 3 | merge-decider, deploy-decider, critics (requirements/design/test/code/ux), code-implementer, test-author, self-reviewer | Final decisions, harsh reviews, core implementation |
| **HIGH** | 2 | requirements-author, bdd-author, adr-author, interface-designer, observability-designer, design-optioneer, work-planner, test-strategist, receipt-checker, contract-enforcer, security-scanner, coverage-enforcer, gate-fixer, smoke-verifier, deploy-monitor | Foundation specs, verification, design |
| **MEDIUM** | 1 | clarifier, risk-analyst, policy-analyst, impact-analyzer, context-loader, fixer, mutator | Cross-cutting analysis, context loading |
| **LOW** | 0 | signal-normalizer, problem-framer, scope-assessor, gh-reporter, doc-writer, flow-historian, artifact-auditor, regression-analyst, learning-synthesizer, feedback-applier, swarm-ops, ux-implementer, repo-operator | Preprocessing, communication, utility, post-flight |

### How It Works

1. **Sort by priority first**: History items are sorted by priority (CRITICAL first, LOW last)
2. **Preserve chronological order within priority**: Items with the same priority maintain their original order
3. **Include highest-value items first**: Iterate through sorted items, including until budget is exhausted
4. **Generate truncation metadata**: Track what was included and the priority distribution

### Truncation Note Format

When truncation occurs, a machine-readable note is added to the prompt:

```
[CONTEXT_TRUNCATED] Included 7 of 19 history steps (12 omitted, budget: 200,000/200,000 chars) [Priority: CRITICAL=3, HIGH=2, MEDIUM=2, LOW=0]
```

### Receipt Metadata

Receipts include priority distribution in `context_truncation`:

```json
{
  "context_truncation": {
    "steps_included": 7,
    "steps_total": 19,
    "chars_used": 200000,
    "budget_chars": 200000,
    "truncated": true,
    "priority_aware": true,
    "priority_distribution": {
      "CRITICAL": 3,
      "HIGH": 2,
      "MEDIUM": 2,
      "LOW": 0
    }
  }
}
```

### Unknown Agents

Agents not in the classification lists are handled via fallback:
1. **Step ID patterns**: Keywords like "critic", "decider" → CRITICAL; "author", "implement" → HIGH
2. **Output patterns**: Keywords like "decision", "critique" → HIGH; "summary", "history" → LOW
3. **Default**: MEDIUM (safe middle ground)

This ensures new agents are retained but can be dropped before critical items if needed.

### Design Philosophy

- **Critical path preservation**: Decisions and implementations are always kept
- **Foundation context retained**: Specs and design docs are kept when possible
- **Utility is expendable**: Preprocessing and post-flight analysis can be dropped first
- **Recency is secondary**: A critical old step beats a low-value recent one

See `swarm/runtime/history_priority.py` for the classification implementation.

---

## Troubleshooting

### Symptom: Frequent `[CONTEXT_TRUNCATED]` warnings

**Root Cause:** Total history budget is being hit.

**Solutions:**
1. If late in a long flow: Expected behavior
2. If early in a flow: Increase `context_budget_chars`
3. If caused by one large step: Check why that step generates so much output

### Symptom: Step outputs appear truncated with "... (truncated)"

**Root Cause:** Individual step output exceeded per-step limits.

**Solutions:**
1. For most recent step: Increase `history_max_recent_chars`
2. For older steps: Increase `history_max_older_chars`

### Common Mistakes

| Mistake | Why It's Wrong | Correct Approach |
|---------|---------------|------------------|
| Setting budget = model window | Leaves no room for CLAUDE.md/completion | Budget should be ~25% of window |
| Same budgets for all flows | Build needs more history than Deploy | Use flow-level overrides |
| Ignoring truncation notes | May miss important context | Review transcripts periodically |

---

## Observability: Checking Budget Effectiveness

### Reading Receipts

Each step produces a receipt JSON at `RUN_BASE/<flow>/receipts/<step_id>-<agent>.json`:

```json
{
  "engine": "claude-step",
  "step_id": "frame",
  "context_truncation": {
    "steps_included": 7,
    "steps_total": 19,
    "chars_used": 200000,
    "budget_chars": 200000,
    "truncated": true
  }
}
```

### Budget Binding Detection

A budget is "binding" when it's actively limiting context:
1. **Truncation notes present:** Budget is binding
2. **`truncated: true` in receipts:** History was dropped

---

## See Also

- [FLOW_STUDIO.md](./FLOW_STUDIO.md) - Visual interface for editing budget overrides (v2.4.0+)
- [LONG_RUNNING_HARNESSES.md](./LONG_RUNNING_HARNESSES.md) - Context handoff details
- [STEPWISE_BACKENDS.md](./STEPWISE_BACKENDS.md) - Stepwise execution guide
- [STEPWISE_CONTRACT.md](./STEPWISE_CONTRACT.md) - Behavioral invariants
- `swarm/runtime/engines.py` - Budget implementation in `_build_prompt()`
- `swarm/config/runtime.yaml` - Default budget values
- `swarm/config/runtime_config.py` - Config accessor functions
