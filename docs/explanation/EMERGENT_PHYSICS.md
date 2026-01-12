# Emergent Physics: The Laws That Fell Out

These are the constraints that emerged from building Flow Studio—things that behave like physical laws even when nobody wrote them down. They aren't principles (which are negotiable); they're physics (which aren't).

## Law 1: Scarcity Inversion Changes Governance

**The Physics:**
Generation is abundant; review attention is scarce.

**What This Means:**
Traditional governance protects code changes (reviews, approvals).
AgOps governance protects **review capacity** (bounded cockpits, evidence existence, anti-Goodhart panels).

> The governed resource is no longer code correctness alone; it's *human verification throughput*.

## Law 2: Mold-Stamping Makes Drift Catastrophic

**The Physics:**
In normal engineering, a bad pattern slows you down.
In AgOps, a bad pattern gets copied at machine speed.

**What This Means:**
> **Prompt debt compounds faster than code debt.**
> Because prompts are upstream of generation *and* verification behavior.

## Law 3: Absence is the Default Failure Mode

**The Physics:**
The most common failure isn't "wrong," it's "missing."
- "Tests ran" but no log
- "Receipt exists" but isn't fresh
- "Evidence" but not linked

**What This Means:**
> **Existence + freshness > claims.**
> Unknown must stay unknown. "Implied pass" is the silent killer.

## Law 4: Authority Lines Are Encoded

**The Physics:**
The system doesn't stop where tasks are hard; it stops where **authority is required**.

**What This Means:**
That's org design as code:
- What requires a human decision
- What can be safely defaulted
- What must be fail-closed at a boundary

> Your "NEEDS_HUMAN" boundary is your org chart.

## Law 5: Review Becomes Piloting

**The Physics:**
The reviewer becomes a sensor fusion operator:
- Evidence freshness
- Panel synthesis
- Risk-calibrated verification escalation
- Hotspot navigation

**What This Means:**
> You are creating a new literacy: *evidence operations*.
> Without teaching it, trust collapses socially even if the system is correct.

## Law 6: Authorship Moves Upstream

**The Physics:**
Developers resist because pride attaches to implementation.

**What This Means:**
In AgOps, pride moves to:
- Intent quality (REQ/BDD/NFR)
- Boundary choices (ADRs/contracts)
- Verification design (panels, mutation, invariants)

> The system must reward "good intent writing" the way repos used to reward "good code."

## Law 7: Internal Gates Are Traffic Routing

**The Physics:**
Inside the work plane, "quality controls" are mostly routing:
- Route to fixer
- Route to critic
- Rerun executor

**What This Means:**
The only *real* gates are publish boundaries (merge/push/secrets/destructive ops).

> If a team insists on mid-flow approvals, they are fighting the physics.

## Law 8: Panels Reduce Goodhart But Move the Attack Surface

**The Physics:**
A panel is harder to game than a single metric.

**What This Means:**
But systems can optimize for "looks good on panel" unless humans can escalate verification (more tests, mutation testing, adversarial probes).

> Panels buy time; escalated verification preserves judgment.

## Law 9: Non-Determinism is a Sensor

**The Physics:**
Variation across runs is signal, not just noise.

**What This Means:**
If repeated attempts yield wildly different outputs, your spec/prompt is underconstrained.

> **Stochasticity is a diagnostic tool** (like mutation testing for generation).

## Law 10: Forgetfulness is Error Correction

**The Physics:**
Session amnesia isn't just "prevent drift." It's a control strategy.

**What This Means:**
Each step resets accumulated bad assumptions, forcing the system back to on-disk truth.

> Fresh sessions are a *reset vector*. Long sessions are hidden state.

## Law 11: The Warmth Paradox is Stability

**The Physics:**
The emotional stability of the system depends on a split:
- Ruthless about artifacts (prove it)
- Protective of humans (remove toil, make review accessible)

**What This Means:**
> Psychological trust is part of the system.
> Cockpit UX is a safety mechanism, not marketing.

## Law 12: Verification Stack is the Asset

**The Physics:**
If code is cheap to regenerate, the real capital is:
- The verification pipeline
- The evidence contracts
- The boundary truth enforcement
- The receipts taxonomy

**What This Means:**
> Teams should treat verification infrastructure as the crown jewel, not the codebase.

---

## The Plant Constraints (Non-Negotiable)

These are the "constraints of the plant"—physics you cannot negotiate:

| Constraint | Description |
|------------|-------------|
| Sessions forget | Context resets; disk is memory |
| Models are stochastic | Same input → different outputs |
| Humans don't scale to diff-reading | 70k-100k LOC PRs are unreadable |
| Evidence can be faked unless mechanically anchored | Claims without commands are narrative |
| Optional gates decay | If it can be skipped, it will be |
| Boundaries are where risk concentrates | Publish gates matter; internal gates don't |

---

## What Goes Where

### Physics belong in:
- Validators
- Receipts
- Stop/resume semantics
- Publish gates
- Capability matrices

### Principles belong in:
- Pack docs
- Agent templates
- Flow command conventions
- Examples

> The emergent insight: enforce physics *without* turning principles into bureaucracy—but only if you keep the planes separate.

---

## See Also
- [META_LEARNINGS.md](./META_LEARNINGS.md) - What we learned building this
- [TRUST_HIERARCHY.md](./TRUTH_HIERARCHY.md) - Evidence levels
- [BOUNDARY_PHYSICS.md](./BOUNDARY_PHYSICS.md) - Sandbox/publish model
