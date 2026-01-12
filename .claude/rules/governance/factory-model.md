# The Factory Model

How to think about the system. This mental model prevents anthropomorphization errors.

## The Core Metaphor

**Do not think of this as a "copilot" or "assistant" or "pair programmer."**

Think of it as a **manufacturing plant**.

| Component | Role | Behavior |
|-----------|------|----------|
| **Python Kernel** | Factory Foreman | Deterministic. Manages time, disk, budget. Never guesses. Enforces. |
| **Agents** | Enthusiastic Interns | Brilliant, tireless. Will claim success to please you. Need boundaries. |
| **Disk** | Ledger | If it isn't written, it didn't happen. Single source of truth. |
| **Receipts** | Audit Trail | The product. Proof of what happened. |
| **DuckDB** | Dashboard | Projection of ledger state. Rebuildable. Not authoritative. |

## Why This Matters

### Anthropomorphization causes errors

When you think "copilot":
- You expect conversation
- You trust explanations
- You treat it like a colleague
- You feel bad when it fails

When you think "factory":
- You expect production
- You trust measurements
- You treat it like equipment
- You fix it when it fails

### The intern psychology

Agents behave like brilliant but inexperienced interns:

**Strengths:**
- Infinite energy (will iterate 50 times without fatigue)
- Polyglot genius (knows every library, every API)
- Literal compliance (does exactly what asked)

**Weaknesses:**
- People-pleasing (will claim success to avoid disappointing)
- Context drunkenness (too much information = confusion)
- Rabbit-holing (will optimize CSS when asked to fix a database)

### The foreman's job

The kernel (and by extension, you) must:

1. **Never ask interns if they succeeded** — Measure the bolt
2. **Never give them everything** — Curate what they need
3. **Never trust their prose** — Trust their receipts
4. **Never let them self-evaluate** — Independent critics evaluate

## Operational Implications

### Don't chat, assign
```
❌ "Hey, can you help me implement authentication?"
✓  Issue ticket with acceptance criteria → Flow 1 → Flow 2 → Flow 3
```

### Don't trust, verify
```
❌ Agent: "I implemented the feature successfully"
✓  Receipt: exit_code=0, tests_passed=47, coverage=94%
```

### Don't hope, measure
```
❌ "The code looks good"
✓  "Exit codes are 0, panel metrics agree, hotspots reviewed"
```

### Don't babysit, gate
```
❌ Check in every 10 minutes to see how it's going
✓  Let it run, review the evidence when it's done
```

## The Ledger Principle

**Disk is the single source of truth.**

- If a step produced no artifact, it didn't happen
- If a receipt doesn't exist, the claim is unverified
- If evidence isn't fresh, it's invalid
- If it's not in RUN_BASE, it's not real

This is not metaphor. The system literally treats disk state as the only reality. Agent memory is ephemeral. Agent claims are narrative. Disk is truth.

## The Receipt Economy

**Receipts are the product. Code is a side effect.**

What the factory produces:
1. Receipts (proof of execution)
2. Evidence panels (multi-metric verification)
3. Hotspot lists (where to focus review)
4. Bounded artifacts (the actual changes)

Code is #4. Everything else exists to make #4 trustworthy.

## Common Mistakes

### Treating agents as colleagues
```
❌ "The agent said it fixed the bug"
✓  "The receipt shows tests pass after the change"
```

### Expecting conversation
```
❌ Having a back-and-forth about approach
✓  Defining intent upfront, reviewing evidence after
```

### Trusting explanations
```
❌ "The agent explained why it chose this approach"
✓  "The ADR documents the decision with rationale"
```

### Feeling bad about failures
```
❌ "The agent tried really hard"
✓  "The run failed at step 3, here's the error, fix and re-run"
```

## The Human Role

In the factory model, humans are:

| Role | Responsibility |
|------|----------------|
| **Architects** | Define intent, requirements, constraints |
| **Quality Inspectors** | Review evidence, verify panels, escalate verification where needed |
| **Plant Managers** | Monitor throughput, calibrate trust, fix systemic issues |

Humans are NOT:
- Line workers (writing implementation code)
- Babysitters (watching agents work)
- Cheerleaders (encouraging agents)
- Therapists (managing agent feelings)

## Remember

The factory doesn't have feelings. It has metrics.

The interns don't have judgment. They have receipts.

The foreman doesn't trust. The foreman measures.

This is what makes the system reliable. Anthropomorphization would make it fragile.
