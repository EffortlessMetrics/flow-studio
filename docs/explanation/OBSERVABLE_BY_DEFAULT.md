# Observable by Default: If It Happened, There's a Receipt

> **Status:** Living document
> **Purpose:** Define the observability requirement for agentic work

## The Principle

> Unobserved work is untrusted work.

If an agent did something and there's no artifact proving it, it didn't happen for trust purposes.

## Why Observability Matters

### The Black Box Problem
Traditional AI systems:
- Input -> [Black Box] -> Output
- What happened inside? Unknown.
- How did it decide? Unknown.
- Can we verify? No.

### The Glass Box Solution
AgOps systems:
- Input -> [Observed Steps] -> Output
- Every step produces artifacts
- Every decision is logged
- Everything is verifiable

## What "Observable" Means

### Artifacts Exist
Every step produces:
- Receipt (what happened)
- Handoff (what's next)
- Evidence (proof of claims)

### Decisions are Logged
Every routing decision:
- What was decided
- Why it was decided
- What alternatives existed
- What evidence was used

### Claims are Anchored
Every claim points to:
- A command that was run
- An output that was captured
- A file that was produced

## The Observability Stack

### Level 1: Existence
Did the step run?
- Receipt exists: yes
- Receipt missing: no proof

### Level 2: Outcome
What was the result?
- Status field: succeeded/failed
- Duration: how long
- Tokens: how much compute

### Level 3: Evidence
What proves the claims?
- Evidence pointers in receipt
- Artifact files on disk
- Command outputs captured

### Level 4: Reasoning
Why was this decision made?
- Routing logs
- Scent trail
- Handoff recommendations

## Observable vs Hidden

| Observable (Good) | Hidden (Bad) |
|-------------------|--------------|
| Receipt with status | Status in memory only |
| Test output file | "Tests passed" claim |
| Diff summary artifact | "Code changed" claim |
| Routing decision log | Implicit next step |
| Evidence path | Unanchored assertion |

## The Artifact Trail

A complete run produces:
```
RUN_BASE/
├── signal/
│   ├── receipts/          # What happened
│   ├── handoffs/          # What's next
│   └── artifacts/         # Evidence
├── plan/
│   ├── receipts/
│   ├── handoffs/
│   └── artifacts/
├── build/
│   ├── receipts/
│   ├── handoffs/
│   ├── llm/               # Transcripts
│   └── artifacts/
└── ...
```

Every step, every flow, every decision: observable.

## Silent Failures are Forbidden

### Bad: Silent Skip
```python
if condition:
    skip_step()  # No artifact, no log
```

### Good: Observed Skip
```python
if condition:
    write_receipt(status="skipped", reason="condition X")
```

The difference: one leaves a trace, one doesn't.

## The Debugging Dividend

Observable systems are debuggable:
- "What happened?" -> Read receipts
- "Why did it fail?" -> Check evidence
- "What was the reasoning?" -> Read handoffs
- "Where did it go wrong?" -> Trace artifacts

Hidden systems are mysteries:
- "What happened?" -> Re-run and watch
- "Why did it fail?" -> Guess
- "What was the reasoning?" -> Unknown
- "Where did it go wrong?" -> Unknown

## Observability as Trust Infrastructure

Observability enables:
- **Verification**: Check claims against evidence
- **Debugging**: Trace failures to root cause
- **Learning**: Extract patterns from runs
- **Auditing**: Prove what happened
- **Improvement**: Identify optimization opportunities

Without observability, none of these work.

## The Rule

> Every step produces a receipt.
> Every claim has an evidence pointer.
> Every decision is logged.
> If there's no artifact, it didn't happen.

## Implementation

### Receipts
Written by `receipt_io.py` after every step.

### Handoffs
Written by finalization phase of each step.

### Transcripts
Written by engine during LLM execution.

### Routing Logs
Written by Navigator after every decision.

### Evidence
Captured by forensic scanners, stored as artifacts.

## The Cost

Observability has overhead:
- Disk space for artifacts
- Tokens for finalization
- Time for writing

The cost is worth it:
- Debug time saved: 10x
- Trust gained: priceless
- Learning enabled: compounding
