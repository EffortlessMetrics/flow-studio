# Documentation Philosophy

How we write about Flow Studio. These aren't style preferences—they're the difference between being understood and being ignored.

> Structure follows the inverted pyramid (Steven's editorial background): lead with conclusion, proof before philosophy.

## The Core Principle

**Show the shift, not the tool.**

We're not selling software. We're explaining an inevitable transition. The tool is evidence that the transition is here.

## The Historical Frame

Always position this as part of a progression:

```
Punchcards → Assembly → High-level languages → Now
```

Each transition:
- Made skilled craft mechanical
- Moved humans to higher-leverage work
- Was resisted by those who identified with the old craft
- Became obviously correct in hindsight

The skeptic who says "real engineers write code" is positioned alongside "real programmers use assembly." That's the frame. Never argue against it—just place it in history.

## The Bottleneck Shift

The old bottleneck: "Can it write code?"
The new bottleneck: "Can a human trust it in 30 minutes?"

Everything we build addresses the new bottleneck. Generation is solved. Verification is the constraint.

## Economics: No Hedging

State budgets, not disclaimers. This is engineering documentation, not financial disclosure.

### The Rules

1. **State the budget**: ~$30 per full run (7 flows, all steps)
2. **Point to receipts for actuals**: If you track costs, show the data
3. **Do NOT write price-disclaimer paragraphs**: "Costs vary by model and workload" is heat, not signal
4. **The invariant**: Compute is more elastic than senior review time. That's the trade.

### Example

| Approach | Cost | Output |
|----------|------|--------|
| Developer implements | ~5 days salary | Code + implicit verification |
| Flow Studio full run | **~$30** | Code + tests + receipts + evidence panel + hotspots |

Not: "Costs may vary significantly depending on model selection, token usage patterns, and workload characteristics..."

### Why This Matters

Hedging signals uncertainty. We're not uncertain about the economics—we've run it. If the numbers change, update the numbers. Don't preemptively excuse them.

## README Structure

Proven structure for technical READMEs that convert skeptics:

| Section | Time | Purpose |
|---------|------|---------|
| The Shift | 5 sec | Hook with historical inevitability |
| The Math | 15 sec | Concrete economics (~$30 vs 5 days) |
| See It Work | 30 sec | Proof before explanation |
| What You Get | 45 sec | Artifacts, not features |
| How to Think | 60 sec | Mental model (factory, not copilot) |
| Everything else | 2+ min | Progressive disclosure |

**Key principle:** If they stop reading at any point, they got value.

## What We Never Do

### Don't claim revolution
- Wrong: "Revolutionary AI-powered development platform"
- Right: "The job is moving up the stack. Again."

### Don't fight the skeptic
- Wrong: "AI won't replace developers"
- Right: "Just like every transition before"

### Don't lead with philosophy
- Wrong: Open with mental models and manifestos
- Right: Open with the shift and the math

### Don't hide the proof
- Wrong: Quick start buried after philosophy
- Right: "See It Work" in the first scroll

### Don't use marketing language
- Wrong: "Seamlessly integrate AI into your workflow"
- Right: "The machine does the implementation. You do the judgment."

## What We Always Do

### Lead with the shift
The first line should make them feel the ground moving.

### Show the math immediately
Concrete numbers. ~$30 vs 5 days. 30 minutes vs a week.

### Provide proof early
"See It Work" before "How It Works."

### Use tables for scannability
Senior engineers at 11pm should get it in 30 seconds.

### Position humans as moving up, not out
- Architecture over implementation
- Intent over syntax
- Judgment over grinding

### End sections with one-line anchors
- "The receipts are the product. The code is a side effect."
- "Just like every transition before."
- "The system did the grinding; you do the judgment."

## The Trust Thesis

This is the core message that appears everywhere:

> Code generation is cheap. Trust is expensive.
> The verification stack is the crown jewel, not the codebase.

When in doubt, return to this. Every feature, every flow, every design decision exists to make trust cheaper.

## Voice

- **Industrial, not corporate** — Factory floor, not boardroom
- **Concrete, not abstract** — Exit codes, not "robust validation"
- **Respectful of time** — Scannable tables, clear hierarchy
- **Confident, not boastful** — State facts, let them conclude

## The Test

Before publishing any documentation, ask:

1. Does a skeptical senior engineer get value in 30 seconds?
2. Is the historical frame present (up the stack, not replacement)?
3. Is the math concrete ($30/run, 30 minutes review—not "faster" or "varies")?
4. Is proof before philosophy?
5. Ruthless concision, concrete nouns, binary tone?
