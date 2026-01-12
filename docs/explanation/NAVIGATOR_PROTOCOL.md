# Navigator Protocol: The Routing Brain

> **Status:** Living document
> **Purpose:** Explain how routing decisions happen when deterministic rules fail

## The Problem

Routing has two failure modes:

**Failure Mode 1: Pure Deterministic**
Hardcoded rules can't handle edge cases. What happens when tests pass but a critic finds a HIGH severity concern? Rules become a tangled mess of special cases.

**Failure Mode 2: Pure LLM**
Let the model decide everything. This creates inconsistent decisions, expensive calls for simple questions, unbounded vocabulary, and no auditability.

The solution is a hybrid: deterministic rules first, LLM routing only when necessary.

## The 5-Tier Priority System

The kernel resolves routing in this order:

```
1. Fast-Path (No LLM)      -> Deterministic, instant
2. Deterministic Checks    -> Rules-based, no judgment
3. Navigator (LLM)         -> Structured input, bounded output
4. Envelope Fallback       -> Legacy compatibility
5. Escalate               -> Human required
```

Each tier is a gate. Only if a tier can't decide does the next tier run.

### Tier 1: Fast-Path

Obvious cases that need no judgment:

| Condition | Decision |
|-----------|----------|
| Terminal step reached | TERMINATE |
| Explicit `next_step_id` in envelope | ADVANCE to that step |
| VERIFIED status | ADVANCE to next |
| Microloop exit condition met | EXIT loop |

These are the golden path. 80% of routing ends here.

### Tier 2: Deterministic Checks

Rules that can be computed without judgment:

| Condition | Decision |
|-----------|----------|
| Iteration count >= max | ADVANCE with warning |
| Same failure signature twice | DETOUR to known fix |
| Graph constraint violated | REJECT decision |

Still no LLM. Pattern matching and counters.

### Tier 3: Navigator

When deterministic rules don't apply, invoke the Navigator - but with structured forensics, not raw context.

### Tier 4-5: Fallback and Escalate

Legacy envelope-based routing. If all else fails, escalate to human.

## Why Navigator Sees Forensics, Not Narrative

The Navigator receives a compact forensic summary:

```json
{
  "step_completed": "build-step-3",
  "agent": "code-implementer",
  "status": "UNVERIFIED",
  "forensics": {
    "tests": { "passed": 42, "failed": 2 },
    "lint": { "errors": 0 },
    "concerns": [
      { "severity": "HIGH", "description": "Missing error handling" }
    ]
  },
  "iteration": { "current": 2, "max": 3 }
}
```

### The Physics

**The Navigator sees measurements, not story.**

| If Navigator saw... | Problem |
|---------------------|---------|
| Full agent output | 10k+ tokens of prose to parse |
| Agent's explanation | Sycophantic framing |
| Conversation history | Context pollution |

| Navigator actually sees... | Benefit |
|----------------------------|---------|
| Structured JSON | Consistent parsing |
| Measured values | Objective facts |

The forensic summary is the "crime scene photo" - physical evidence, not testimony.

## The Bounded Decision Vocabulary

Navigator outputs from a closed set:

| Decision | When | Example |
|----------|------|---------|
| **CONTINUE** | Ready to advance | Tests pass, no HIGH concerns |
| **LOOP** | Needs iteration | Critic found fixable issues |
| **DETOUR** | Known fix pattern | Lint errors -> auto-linter |
| **INJECT_FLOW** | Need another flow | Upstream diverged -> Flow 8 |
| **INJECT_NODES** | Novel requirement | Ad-hoc steps needed |
| **ESCALATE** | Cannot proceed | Human decision required |
| **TERMINATE** | Flow complete | Terminal step reached |

### What This Means

**Decisions are bounded. The vocabulary is closed.**

The Navigator cannot invent new decision types like "MAYBE_CONTINUE" or "TRY_AGAIN_HARDER". This makes output parsing trivial, logging consistent, and behavior auditable.

The kernel validates every decision: Is it in vocabulary? Does the next step exist? Does the detour target exist? Invalid decisions are rejected and logged.

## Signature Matching: Known Problems, Known Solutions

Before invoking complex judgment, check if this is a known pattern:

| Signature | Detour | Why |
|-----------|--------|-----|
| `lint_errors` | auto-linter | Mechanical fix |
| `missing_import` | import-fixer | Common mistake |
| `type_mismatch` | type-annotator | Mechanical fix |
| `upstream_diverged` | Flow 8 (Rebase) | Deliberate sync |

### The Physics

**Known problems deserve known solutions. Skip the discovery phase.**

Generic iteration is expensive - full agent cycles, same problem "discovered" again, tokens burned on solved patterns. Signature matching short-circuits: pattern recognized, solution applied, back to main path.

## The Goal-Alignment Test

Every Navigator decision passes this filter:

> "Does this help achieve the flow's objective?"

Each flow has a charter defining its goal. The Navigator checks:
- Does this decision serve the goal?
- Is it within scope (not a non-goal)?
- Will it help answer the key question?

### What This Means

**Drift from charter is rejected.**

If Build flow's goal is "implement the planned work" and Navigator proposes "refactor the auth module while we're here" - that's scope creep. The charter says refactoring unrelated code is a non-goal. Decision rejected.

This prevents yak shaving, scope creep, and mission drift. The charter is the constitution.

## Why Navigator Uses Economy Tier

The Navigator runs on haiku (economy tier), not sonnet or opus.

| Property | Why Economy Works |
|----------|-------------------|
| Decisions bounded | 7 possible outputs, not open-ended |
| Input structured | JSON, not prose |
| Judgment low | Evidence-based, not creative |
| Speed matters | Routing is latency-sensitive |
| Volume high | Many routing decisions per run |

### The Physics

**Complex reasoning happens in agents. Navigator just routes.**

The Navigator doesn't need to understand code. It reads forensics:
- 2 tests failed + 2nd iteration + same signature -> DETOUR
- 0 failures + VERIFIED status -> CONTINUE
- 3rd iteration + HIGH concern unaddressed -> ESCALATE

This is classification, not creativity. A fast, cheap model excels here.

Model allocation: Opus for wisdom synthesis. Sonnet for implementation. Haiku for routing.

## Off-Road Logging

Every non-CONTINUE decision is an "off-road" event. All are logged:

```
RUN_BASE/<flow>/routing/decisions.jsonl

{"step_id": "build-step-3", "decision": "DETOUR",
 "detour_target": "auto-linter", "reason": "5 fixable lint errors"}
```

**The golden path is implicit. Deviations are explicit.**

CONTINUE decisions don't need logging. But every LOOP, DETOUR, INJECT, or ESCALATE creates an audit record. Why did this run take 12 iterations? Check the routing log.

## The Rule

> Navigator routes based on forensics, not narrative.
> Decisions are bounded, validated, and logged.
> When in doubt, escalate - never guess.

## Implications

**For System Design:** Build systems that produce forensics. Good routing needs good measurements.

**For Agent Design:** Agents produce evidence. Navigator routes. Separation of concerns.

**For Trust:** Routing is auditable. Every decision has forensic input that can be reviewed.

**For Cost:** Routing is cheap work that happens often. Use cheap models.

## See Also
- [FORENSICS_OVER_TESTIMONY.md](./FORENSICS_OVER_TESTIMONY.md) - Why forensics, not narrative
- [NARROW_TRUST.md](./NARROW_TRUST.md) - Why narrow scope enables trust
- [SCARCITY_AS_DESIGN.md](./SCARCITY_AS_DESIGN.md) - Why budget constraints are features
