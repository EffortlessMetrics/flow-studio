# Attention Arbitrage: The Economic Engine

> **Status:** Living document
> **Purpose:** Name the core economic trade that makes AgOps work

## The Insight

The bottleneck in software development isn't code generation. It's trust.

More specifically: **senior engineer attention** is the scarce resource.

AgOps is an arbitrage: trade **cheap attention** (model tokens) for **expensive attention** (senior engineer minutes).

## The Trade

| Resource | Cost | Abundance |
|----------|------|-----------|
| Model tokens | ~$0.01/1K | Infinite |
| Junior dev hours | ~$50/hr | Limited |
| Senior dev hours | ~$150+/hr | Scarce |
| Senior dev *focused* hours | Priceless | Rare |

The arbitrage:
- Spend ~$30 on a background run with 50 agent calls
- Produce a PR with evidence, receipts, and hotspot analysis
- Senior reviews in 30 minutes instead of building from scratch in 5 days

## Why This Works

### Model Attention is Cheap
- Haiku: ~$0.25/M input tokens
- Sonnet: ~$3/M input tokens
- Opus: ~$15/M input tokens
- A full flow run: $2-20

### Senior Attention is Expensive
- Not just salary: opportunity cost
- Not just time: context switching cost
- Not just focus: decision fatigue cost

### The Multiplier
One hour of senior attention saved = 10+ hours of value created downstream.

Because senior attention is the bottleneck for:
- Architecture decisions
- Code review approval
- Production deployments
- Incident response

## What We're Actually Trading

### Cheap Attention (Spend Freely)
- Model reasoning tokens
- Iteration cycles
- Exploratory analysis
- Verbose receipts
- Multiple critic passes

### Expensive Attention (Conserve Ruthlessly)
- Senior review time
- Decision-making energy
- Context-building effort
- Trust-verification work

## The DevLT Metric

**Developer Lead Time (DevLT)**: Minutes of senior attention required to approve a change.

Traditional development:
- Senior reads all code: 2-4 hours
- Senior debugs issues: 1-2 hours
- Senior verifies claims: 30-60 minutes
- **Total: 4-7 hours**

AgOps development:
- Senior reviews PR cockpit: 10 minutes
- Senior checks evidence/receipts: 10 minutes
- Senior escalates verification on hotspots (requests targeted tests, not reads code): 10 minutes
- **Total: 30 minutes**

**10x reduction in senior attention** for the same (or better) confidence.

## The Arbitrage Mechanics

### 1. Front-load Compute
Spend tokens early:
- Heavy context loading (20-50k tokens)
- Multiple iteration loops
- Adversarial critic passes
- Exhaustive evidence capture

### 2. Produce Review Surfaces
Convert compute into reviewable artifacts:
- PR cockpit summary
- Hotspot analysis
- Evidence pointers
- Risk assessment

### 3. Enable Verification Without Reading
Senior verifies by:
- Checking receipts (not reading code)
- Reviewing evidence (not re-running tests)
- Escalating verification on hotspots when doubt exists (requesting targeted tests, mutation analysis, adversarial probes—not reading code)

## When the Arbitrage Fails

The trade breaks down when:

### Evidence is Missing
No receipts = senior must verify manually = no savings

### Quality is Low
Multiple revision cycles = senior attention multiplied = negative arbitrage

### Scope is Wrong
Wasted work = senior redirects = attention spent on waste

### Trust is Broken
Past failures = senior reviews everything = no leverage

## The Investment Mindset

Think of model tokens as investment:
- Cheap to spend
- Compounds into trust
- Pays dividends in saved attention

Think of senior attention as capital:
- Expensive to deploy
- Should only go to high-leverage decisions
- Wasted attention = wasted capital

## The Rule

> Spend tokens freely to save attention ruthlessly.
> Every dollar of compute should save ten dollars of senior time.
> The goal is not "AI does the work" --- it's "senior reviews in minutes, not hours."

## Why "Arbitrage"?

Arbitrage = exploiting a price difference between markets.

Here:
- Market A: Model tokens (cheap, abundant)
- Market B: Senior attention (expensive, scarce)

The opportunity: most orgs treat these as unrelated. AgOps connects them, enabling the trade.

## The Compound Effect

Each successful run:
- Builds trust in the system
- Reduces future review time
- Trains the team on evidence-based review
- Creates reusable patterns

The arbitrage gets *better* over time, not worse.
