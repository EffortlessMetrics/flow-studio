# Narrow Trust: Trust Narrowly, Verify Broadly

> **Status:** Living document
> **Purpose:** Define the trust model for agentic systems

## The Inversion

Traditional thinking: "Bigger model = more trust"
AgOps thinking: "Narrower scope = more trust"

> A haiku model with evidence beats an opus model without evidence.

Trust isn't about capability. It's about **scope + verification**.

## The Trust Equation

```
Trust = (Scope Narrowness) × (Evidence Quality) × (Verification Depth)
```

### Scope Narrowness
- One job per agent
- Clear inputs and outputs
- Bounded responsibilities
- No scope creep

### Evidence Quality
- Measured, not claimed
- Reproducible
- Pointed to artifacts
- Forensically verifiable

### Verification Depth
- Independent verification
- Adversarial review
- Multiple evidence sources
- Panel thinking

## Why Narrow Trust Works

### Models are Generalists
LLMs can do many things. This is a bug, not a feature, for trust.
- Generalist = unpredictable
- Specialist = predictable

### Narrow Scope = Predictable Behavior
When an agent does ONE thing:
- You know what to expect
- You know what to verify
- Deviations are obvious
- Failures are bounded

### Broad Scope = Unpredictable Behavior
When an agent does MANY things:
- Anything might happen
- Verification is expensive
- Deviations are hidden
- Failures cascade

## The Trust Matrix

| Scope | Evidence | Trust Level | Verification Needed |
|-------|----------|-------------|---------------------|
| Narrow | Strong | HIGH | Minimal escalation |
| Narrow | Weak | MEDIUM | Targeted verification escalation |
| Broad | Strong | MEDIUM | Comprehensive verification escalation |
| Broad | Weak | LOW | Full verification escalation (mutation tests, fuzz tests, adversarial probes) |

The same model in a narrow scope with strong evidence is more trusted than a "better" model in a broad scope without evidence. When doubt exists, escalate verification (more tests, scanners, adversarial pressure)—don't fall back to manual code reading.

## Narrow Trust in Practice

### Agent Design
- One responsibility per agent
- Explicit input/output contracts
- Clear "when stuck" guidance
- No multi-tasking

### Verification Design
- Critics verify single aspects
- Scanners check single dimensions
- Gates aggregate narrow checks
- No "general approval"

### Evidence Design
- Specific claims, specific evidence
- One measurement per claim
- No bundled assertions
- "Not measured" is explicit

## The Anti-Pattern: Broad Trust

What broad trust looks like:
- "The AI reviewed the code and it looks good"
- "Claude said it's secure"
- "The agent handled everything"

Why it fails:
- No way to verify "everything"
- No evidence for specific claims
- No scope for focused review
- Trust is all-or-nothing

## The Pattern: Narrow Trust

What narrow trust looks like:
- "code-critic found 3 issues at specific lines"
- "security-scanner reported 0 high-severity findings"
- "test-parser shows 42 passed, 0 failed"

Why it works:
- Each claim is verifiable
- Each scope is bounded
- Each piece aggregates into whole
- Trust is compositional

## Compositional Trust

Narrow trust composes:
```
Total Trust = Π(narrow trust for each aspect)
```

- Tests verified by test-parser ✓
- Security verified by security-scanner ✓
- Style verified by lint-scanner ✓
- Logic verified by code-critic ✓
- **Composite: HIGH trust**

Broad trust doesn't compose:
```
Trust = "AI said it's fine"
```
- Everything in one claim
- No decomposition
- No independent verification
- **Result: LOW trust**

## The Model Capability Inversion

| Scenario | Trust Level |
|----------|-------------|
| Opus doing 10 things without evidence | LOW |
| Haiku doing 1 thing with evidence | HIGH |
| Sonnet doing 3 things with partial evidence | MEDIUM |

Capability doesn't determine trust. Scope + evidence does.

## The Rule

> Trust is not about how smart the model is.
> Trust is about how narrow the scope and how strong the evidence.
> Narrow scope + strong evidence = high trust, regardless of model.

## Implications

### For Agent Design
Design agents to be trusted, not to be capable.
Narrow scope > broad capability.

### For Verification
Verify specifically, not generally.
Many narrow checks > one broad check.

### For Review
Review evidence, not output.
Check claims individually, not holistically.

### For Model Selection
Choose models for the task, not for "trust."
Haiku is fine if scope is narrow and evidence is strong.
