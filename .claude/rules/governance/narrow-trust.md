# Narrow Trust: Scope as a Risk Lever

Trust is not binary. It's a function of scope, evidence, and verification depth.

## The Trust Equation

```
Trust = (Scope Narrowness) × (Evidence Quality) × (Verification Depth)
```

### Why This Matters

A narrow agent with strong evidence is more trustworthy than a broad agent with weak evidence.
This is why single-job agents exist: narrowness is a trust multiplier.

## The Trust Matrix

| Scope | Evidence | Trust Level | Example |
|-------|----------|-------------|---------|
| Narrow | Strong | HIGH | Linter with exit codes |
| Narrow | Weak | MEDIUM | Code author with no tests |
| Broad | Strong | MEDIUM | Full-stack agent with coverage |
| Broad | Weak | LOW | "Do everything" with narrative |

## Scope Narrowness

Narrow scope means:
- Single responsibility (one job)
- Bounded blast radius (contained failure modes)
- Clear success criteria (measurable outcomes)
- Limited authority (constrained permissions)

### Examples

| Agent | Scope | Why |
|-------|-------|-----|
| `lint-fixer` | Narrow | Only fixes lint errors; no other changes |
| `test-author` | Narrow | Only writes tests; doesn't modify source |
| `code-implementer` | Medium | Writes code but bounded by work plan |
| `general-agent` | Broad | Can do anything; lowest default trust |

## Evidence Quality

Evidence quality tiers:

| Tier | Evidence Type | Trust Contribution |
|------|---------------|-------------------|
| Physics | Exit codes, file hashes, git status | Highest |
| Receipts | Captured logs, test output, scan results | High |
| Artifacts | Generated files, diffs | Medium |
| Narrative | Agent prose, claims | Lowest |

## Verification Depth

Verification depth means:
- How many independent checks confirm the claim?
- How reproducible is the evidence?
- How recent is the evidence?

### Verification Levels

| Level | Description | Example |
|-------|-------------|---------|
| 0 | No verification | "I did it" |
| 1 | Self-reported | Receipt exists |
| 2 | Tool-verified | Tool ran and captured output |
| 3 | Cross-verified | Multiple tools agree |
| 4 | Human-verified | Human spot-checked |

## The Rule

> Prefer narrow scope with strong evidence over broad scope with weak evidence.

When routing work:
1. Choose the narrowest agent that can do the job
2. Require evidence proportional to scope
3. Verify proportional to risk

## Applying Narrow Trust

### At Agent Design
- Give agents single jobs
- Define clear input/output contracts
- Specify what they CANNOT do

### At Flow Routing
- Route to specialists, not generalists
- Require evidence before advancing
- Match agent scope to task scope

### At Gate Review
- Weight evidence by source (physics > narrative)
- Discount broad claims without narrow proof
- Require verification depth for high-risk changes

## Anti-Patterns

### Trust Inflation
```
Agent claims: "All requirements implemented"
Evidence: None
Action: Trust anyway
```

**Problem:** Broad claim without narrow evidence.

### Scope Creep
```
Task: Fix lint errors
Agent: Also refactored auth module
```

**Problem:** Exceeded narrow scope without authorization.

### Evidence Substitution
```
Required: Test output
Provided: "Tests passed" in narrative
```

**Problem:** Narrative substituted for physics.

## The Two Reasons Rule

Spawn an agent for exactly two reasons:

| Reason | Description |
|--------|-------------|
| **Work** | Something needs changing (code, docs, tests) |
| **Compression** | Context needs compressing (read lots, produce map) |

If neither applies, don't spawn. Extra agents dilute focus and waste context.

## Enforcement

Narrow trust is enforced through:
- Agent behavioral contracts (single job)
- Evidence discipline (receipts required)
- Gate policies (evidence before merge)
- Routing rules (scope-appropriate agents)

---

## See Also
- [agent-behavioral-contracts.md](./agent-behavioral-contracts.md) - Role family definitions
- [evidence-discipline.md](./evidence-discipline.md) - What counts as evidence
- [truth-hierarchy.md](./truth-hierarchy.md) - Evidence levels
