# Budget Discipline: The $30 Run

A full 7-flow run costs $30. Not "around $30." Not "typically $30." $30.

## The Economic Thesis

Compute is cheap. Attention is expensive.

| Resource | Cost |
|----------|------|
| Full 7-flow run | $30 |
| Senior engineer hour | $150-300 |
| 5 days grinding on implementation | $6,000-12,000 |

The math: $30 compute that produces a reviewable PR beats $6,000 of developer time. Every time.

## Budget Allocation by Flow

| Flow | Budget | Typical Spend | Notes |
|------|--------|---------------|-------|
| Signal (Flow 1) | $2 | $1-2 | Shaping is cheap (haiku) |
| Plan (Flow 2) | $4 | $3-4 | ADR/contracts need judgment (sonnet) |
| Build (Flow 3) | $12 | $8-12 | Implementation + microloops |
| Review (Flow 4) | $4 | $2-4 | Feedback harvesting |
| Gate (Flow 5) | $3 | $2-3 | Audit and verification |
| Deploy (Flow 6) | $2 | $1-2 | Mechanical ops |
| Wisdom (Flow 7) | $3 | $2-3 | Synthesis (opus, but brief) |
| **Total** | **$30** | **$20-30** | |

Flow 3 gets 40% of budget. That's where the work happens.

## What Gets Tracked

Every step writes cost data to its receipt:

```json
{
  "cost": {
    "tokens_in": 15000,
    "tokens_out": 3000,
    "model": "sonnet",
    "cost_usd": 0.09,
    "cumulative_run_usd": 4.25
  }
}
```

### Tracking Locations

| Artifact | Path | Purpose |
|----------|------|---------|
| Step receipt | `RUN_BASE/<flow>/receipts/<step>.json` | Per-step cost |
| Run summary | `RUN_BASE/run_summary.json` | Cumulative cost |
| Cost log | `RUN_BASE/cost.jsonl` | Append-only ledger |

## Abort Rules

### Hard Limits

| Condition | Action |
|-----------|--------|
| Run exceeds $45 | ABORT |
| Single step exceeds $5 | ABORT (unless Wisdom/opus) |
| Flow exceeds 2x budget | ABORT |

### Soft Limits

| Condition | Action |
|-----------|--------|
| Run at $30 with flows remaining | WARN, continue if near completion |
| Microloop iteration 4+ | Evaluate: is progress being made? |
| Same error twice in a row | Route to detour, don't burn tokens |

## When to Continue vs Abort

### Continue

- Cumulative cost < $30
- Progress is measurable (receipts show movement)
- Remaining flows are cheap (Gate, Deploy, Wisdom)

### Abort

- Cumulative cost > $45 (hard stop)
- Three consecutive failures at same step
- Microloop stuck with no forensic change
- Token burn with no artifact production

## Diminishing Returns Detection

The kernel tracks cost-per-artifact:

```json
{
  "cost_efficiency": {
    "cost_usd": 2.50,
    "artifacts_produced": 5,
    "cost_per_artifact": 0.50
  }
}
```

### Red Flags

| Signal | Meaning |
|--------|---------|
| Cost/artifact > $2 | Inefficient; investigate |
| Tokens spent, no artifacts | Spinning; abort step |
| Same step, 3x retries | Stuck; route to detour or escalate |

## Cost Monitoring During Run

The kernel emits cost events:

```json
{"event": "cost_checkpoint", "run_id": "abc123", "cumulative_usd": 12.50, "percent_budget": 42}
{"event": "budget_warning", "run_id": "abc123", "cumulative_usd": 28.00, "message": "Approaching limit"}
{"event": "budget_exceeded", "run_id": "abc123", "cumulative_usd": 46.00, "action": "ABORT"}
```

## The Rule

> $30 buys a complete run with receipts.
> Track every dollar. Abort on waste.
> Compute is cheap; throwing it away is still waste.

## Anti-Patterns

### Runaway Costs
```
Step iterates 10 times
No artifact change between iterations
Cost: $8 for nothing
```
**Fix:** Fuse detection. Abort after 3 iterations with no forensic delta.

### Premature Optimization
```
"Let's use haiku everywhere to save money"
Result: Poor quality, more iterations, higher total cost
```
**Fix:** Use the model policy. Sonnet for judgment work. Haiku for mechanical work.

### Cost Blindness
```
Run completes
No cost tracking
"It probably cost around $20?"
```
**Fix:** Every receipt has cost data. No exceptions.

### Budget Padding
```
"Budget is $30 but we'll say $50 to be safe"
Result: Waste tolerance increases. Discipline erodes.
```
**Fix:** State the real budget. $30. If it costs more, that's a bug to fix.

## Optimization Levers

When runs cost too much:

| Lever | Effect | Trade-off |
|-------|--------|-----------|
| Reduce microloop limit | Fewer iterations | May miss issues |
| Switch to haiku for critics | Cheaper reviews | May miss subtle bugs |
| Compress context harder | Less input tokens | May lose context |
| Skip Wisdom flow | Save $3 | No learnings extracted |

Use levers deliberately. Track the impact.

## Current Implementation

Cost tracking implemented in:
- `swarm/runtime/receipt_io.py` - Receipt cost fields
- `swarm/runtime/cost_tracker.py` - Cumulative tracking
- `swarm/runtime/kernel.py` - Abort enforcement

---

## See Also
- [model-policy.md](./model-policy.md) - Cost by model tier
- [scarcity-enforcement.md](./scarcity-enforcement.md) - Token budgets
- [microloop-rules.md](../execution/microloop-rules.md) - Iteration limits
