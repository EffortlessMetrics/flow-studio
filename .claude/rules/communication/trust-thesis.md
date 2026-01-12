# The Trust Thesis

The central insight that shapes everything we build and say.

## The Thesis

**Code generation is cheap. Trust is expensive.**

Or more precisely:

> The bottleneck in AI-assisted development is not "can it write code"—it's "can a human verify and trust the output faster than doing it themselves."

## What "Working Code" Means

**"Working" is defined operationally, not narratively.**

| Claim | Meaning |
|-------|---------|
| "Working code" | Gate passed + receipts exist + panel agrees |
| "Tests pass" | pytest exit code 0 + captured output in receipt |
| "Implementation complete" | Work plan items addressed + evidence captured |

If it isn't captured in a receipt, it's **unknown**, not "worked."

**Never say:**
- "Plausible implementation" (weak, implies doubt)
- "Better than most juniors" (inflammatory comparison, heat not signal)
- "High-quality code" (unverifiable, marketing speak)

**Always say:**
- "Working implementation" (defined by gate + receipts)
- "Code that passes the panel" (measurable)
- "Implementation with evidence" (auditable)

## Why This Matters

### The Old World
- Code is expensive to produce
- Once produced, code is assumed correct until proven otherwise
- Review focuses on "is this good code?"
- Trust is granted by authorship ("Sarah wrote this, so it's probably fine")

### The New World
- Code is cheap to produce (1,000+ tokens/second, ~$0.01 per function)
- Code is assumed suspect until verified
- Review focuses on "what evidence proves this works?"
- Trust is granted by verification ("receipts show tests passed, coverage is 94%, no security issues")

## The Inversion

| Resource | Old Scarcity | New Scarcity |
|----------|--------------|--------------|
| Code production | High (developer hours) | Low (compute) |
| Code verification | Low (assumed correct) | High (must be proven) |
| Developer time | Spent on implementation | Spent on verification |
| Trust | Default granted | Must be earned with evidence |

## What This Means for Design

Every feature must answer: **Does this make trust cheaper?**

### Features that make trust cheaper
- Receipts (proof of what happened)
- Evidence panels (multi-metric verification)
- Hotspot lists (where to focus review)
- Explicit unknowns (what wasn't measured)
- Adversarial loops (critics that actually critique)

### Features that don't make trust cheaper
- Faster generation (trust is the bottleneck, not speed)
- More code (more code = more to verify)
- Prettier output (cosmetics don't affect trust)
- Chat interfaces (conversation doesn't produce evidence)

## The Economic Equation

```
Old: Cost = Developer Hours × Hourly Rate
New: Cost = Compute + Verification Time × Hourly Rate
```

**The budget:** ~$30 per full run (7 flows, all steps). This buys a reviewable trust bundle.

```
New: Cost ≈ $30 + (30 min review × Hourly Rate)
```

**Therefore: Minimize verification time.** The $30 is fixed. The human time is the variable we optimize.

Everything we build—flows, receipts, evidence panels, hotspot lists—exists to minimize the time a human spends verifying.

### The Trade (Concrete)

| Approach | Cost | Output |
|----------|------|--------|
| Developer implements | ~5 days salary | Code + implicit verification |
| Flow Studio full run | ~$30 | Code + tests + receipts + evidence panel + explicit unknowns |

No hedging. No "costs vary." If the numbers change, update the numbers.

## The Trust Stack

Trust is built in layers:

| Layer | Source | Trust Level |
|-------|--------|-------------|
| Physics | Exit codes, file hashes, git status | Highest |
| Receipts | Captured command output, logs | High |
| Evidence | Test results, coverage, lint | High |
| Artifacts | Generated code, diffs | Medium |
| Narrative | Agent claims, explanations | Lowest |

When layers conflict, higher layers win. This is not negotiable.

## Implications for Communication

### When explaining features
Don't say: "Generates high-quality code"
Say: "Produces code with receipts that prove it works"

### When addressing skeptics
Don't say: "The AI is really good now"
Say: "We don't trust the AI either. We trust the evidence."

### When describing value
Don't say: "Saves development time"
Say: "30-minute review instead of week-long implementation"

### When positioning the system
Don't say: "AI-powered development platform"
Say: "Trust infrastructure that happens to generate code"

## The Product Is Trust

The output of Flow Studio is not code. It's trust.

- Code is a side effect
- Receipts are the product
- Evidence panels are the interface
- Verification time is the metric

Everything else is implementation detail.

## Remember

When someone asks "why should I use this?", the answer is:

> "Because you'll spend 30 minutes reviewing evidence instead of a week writing code you're not sure works."

That's the trust thesis in one sentence.
