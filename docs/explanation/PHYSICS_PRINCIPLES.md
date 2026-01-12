# Physics Principles: The Laws of Flow Studio

This document indexes the non-negotiable constraints ("physics") that govern Flow Studio.
These aren't guidelines—they're laws enforced by the runtime.

## The 12 Laws

### Law 1: Scarcity Inversion
**Generation is cheap; review attention is expensive.**

The system optimizes for human verification throughput, not code generation speed.

| Aspect | Reference |
|--------|-----------|
| Teaching | [ATTENTION_ARBITRAGE.md](./ATTENTION_ARBITRAGE.md) |
| Teaching | [EMERGENT_PHYSICS.md](./EMERGENT_PHYSICS.md) |
| Enforcement | Model policy allocates expensive models to judgment tasks |

### Law 2: Mold-Stamping Risk
**Bad patterns replicate at machine speed.**

Prompt debt compounds faster than code debt because prompts are upstream of generation.

| Aspect | Reference |
|--------|-----------|
| Teaching | [META_LEARNINGS.md](./META_LEARNINGS.md) |
| Enforcement | Pack-check validates agent competence |

### Law 3: Existence Over Claims
**Absence is the default failure mode.**

Unknown ≠ pass. "Not measured" is honest; implied pass is dangerous.

| Aspect | Reference |
|--------|-----------|
| Teaching | [CLAIMS_VS_EVIDENCE.md](./CLAIMS_VS_EVIDENCE.md) |
| Enforcement | [evidence-discipline.md](../../.claude/rules/governance/evidence-discipline.md) |
| Enforcement | [forensics-over-testimony.md](../../.claude/rules/governance/forensics-over-testimony.md) |

### Law 4: Truth Hierarchy
**Physics > Receipts > Intent > Artifacts > Narrative.**

When sources conflict, higher levels win. Exit codes beat prose.

| Aspect | Reference |
|--------|-----------|
| Teaching | [TRUTH_HIERARCHY.md](./TRUTH_HIERARCHY.md) |
| Enforcement | [truth-hierarchy.md](../../.claude/rules/governance/truth-hierarchy.md) |

### Law 5: Session Amnesia
**Each step starts fresh; disk is memory.**

Context resets prevent drift. Artifacts are the API, not conversation history.

| Aspect | Reference |
|--------|-----------|
| Teaching | [EMERGENT_PHYSICS.md](./EMERGENT_PHYSICS.md) |
| Enforcement | [context-discipline.md](../../.claude/rules/execution/context-discipline.md) |

### Law 6: Narrow Trust
**Trust = Scope × Evidence × Verification.**

Narrow scope with strong evidence beats broad scope with weak evidence.

| Aspect | Reference |
|--------|-----------|
| Teaching | [NARROW_TRUST.md](./NARROW_TRUST.md) |
| Enforcement | [narrow-trust.md](../../.claude/rules/governance/narrow-trust.md) |

### Law 7: Boundary Physics
**Autonomy inside; gates at exits.**

Work can be destructive inside the sandbox. Publishing is fail-closed.

| Aspect | Reference |
|--------|-----------|
| Teaching | [BOUNDARY_PHYSICS.md](./BOUNDARY_PHYSICS.md) |
| Enforcement | [sandbox-and-permissions.md](../../.claude/rules/safety/sandbox-and-permissions.md) |

### Law 8: Internal Gates Are Routing
**Only publish boundaries are real gates.**

Mid-flow "quality controls" are traffic routing, not barricades.

| Aspect | Reference |
|--------|-----------|
| Teaching | [EMERGENT_PHYSICS.md](./EMERGENT_PHYSICS.md) |
| Enforcement | [fix-forward-vocabulary.md](../../.claude/rules/governance/fix-forward-vocabulary.md) |

### Law 9: Panel Defense
**Multi-metric panels resist gaming.**

Single metrics get Goodharted. Panels + escalated verification preserve judgment.

| Aspect | Reference |
|--------|-----------|
| Teaching | [EMERGENT_PHYSICS.md](./EMERGENT_PHYSICS.md) |
| Enforcement | [panel-thinking.md](../../.claude/rules/governance/panel-thinking.md) |

### Law 10: Non-Determinism as Signal
**Variation across runs is diagnostic.**

If repeated attempts yield wildly different outputs, the spec is underconstrained.

| Aspect | Reference |
|--------|-----------|
| Teaching | [META_LEARNINGS.md](./META_LEARNINGS.md) |
| Application | Run twice, diff receipts |

### Law 11: Validator Supremacy
**The validator is the constitution.**

What fails the build is the real spec. Documentation is explanation.

| Aspect | Reference |
|--------|-----------|
| Teaching | [VALIDATOR_AS_LAW.md](./VALIDATOR_AS_LAW.md) |
| Enforcement | Pack-check, FR-001 through FR-007 |

### Law 12: Verification as Asset
**The verification stack is the crown jewel.**

Code is cheap to regenerate. Evidence contracts, receipts, and gates are the durable value.

| Aspect | Reference |
|--------|-----------|
| Teaching | [TRUST_COMPILER.md](./TRUST_COMPILER.md) |
| Teaching | [META_LEARNINGS.md](./META_LEARNINGS.md) |

---

## Plant Constraints (Non-Negotiable)

These are environmental facts, not design choices:

| Constraint | Implication |
|------------|-------------|
| Sessions forget | Disk is memory; context resets |
| Models are stochastic | Same input → different outputs |
| Humans don't scale | 100k-LOC PRs are unreadable by humans |
| Evidence can be faked | Only physics (exit codes, hashes) is trustworthy |
| Optional gates decay | If it can be skipped, it will be |
| Boundaries concentrate risk | Publish gates matter; internal gates don't |

---

## Quick Reference

### Where Physics Are Enforced

| Physics | Enforcement Point |
|---------|-------------------|
| Truth hierarchy | Navigator routing, gate decisions |
| Session amnesia | Step boundaries, context pack |
| Narrow trust | Agent design, routing decisions |
| Boundary physics | Sandbox config, publish gates |
| Validator supremacy | CI/CD gates, pack-check |

### Where Physics Are Taught

| Physics | Teaching Doc |
|---------|--------------|
| All 12 laws | [EMERGENT_PHYSICS.md](./EMERGENT_PHYSICS.md) |
| Implementation lessons | [META_LEARNINGS.md](./META_LEARNINGS.md) |
| Core synthesis | [TRUST_COMPILER.md](./TRUST_COMPILER.md) |
| Validator authority | [VALIDATOR_AS_LAW.md](./VALIDATOR_AS_LAW.md) |
| Review transformation | [REVIEW_AS_PILOTING.md](./REVIEW_AS_PILOTING.md) |

---

## See Also
- [AGOPS_MANIFESTO.md](../AGOPS_MANIFESTO.md) - The full philosophy
- [.claude/rules/](../../.claude/rules/) - Enforcement layer
- [ARCHITECTURE.md](../ARCHITECTURE.md) - System structure
