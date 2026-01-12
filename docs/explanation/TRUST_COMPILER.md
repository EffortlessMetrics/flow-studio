# The Trust Compiler: What This System Actually Is

Flow Studio isn't a code generator. It's a **trust compiler**—a system that transforms intent into auditable, bounded evidence surfaces.

## The Compiler Metaphor

Traditional compilers:
```
Source Code → Compiler → Executable
```

Trust compilers:
```
Intent + Constraints → Agents + Flows → Trust Bundle
```

Where a **trust bundle** is:
- Reconciled claims
- Freshness-checked evidence
- Mechanically anchored proofs
- Bounded artifact surface

## Why "Trust Compiler"?

### Code is Cheap; Trust is Expensive

In an AI-native world:
- Generation costs tokens (cheap, abundant)
- Verification costs compute (cheap, abundant)
- Review costs attention (expensive, scarce)

The system's job isn't to produce code. It's to produce **reviewable trust bundles** that minimize attention cost.

### The Output Isn't Code

The primary output is:
1. **Evidence panel** - What was measured
2. **Cockpit view** - Human-readable summary
3. **Receipt trail** - Audit provenance
4. **Bounded artifact** - The actual change

Code is a side effect. Trust is the product.

## The Compilation Pipeline

```
┌──────────────────────────────────────────────────────────────┐
│ INPUTS                                                       │
│   Intent (requirements, specs, ADRs)                         │
│   Constraints (contracts, policies, charters)                │
│   Context (codebase, history, patterns)                      │
└──────────────────────────────────────────────────────────────┘
                           ↓
┌──────────────────────────────────────────────────────────────┐
│ COMPILATION (Stochastic)                                     │
│   Agents execute steps                                       │
│   Flows orchestrate work                                     │
│   Critics verify quality                                     │
│   Microloops iterate to convergence                          │
└──────────────────────────────────────────────────────────────┘
                           ↓
┌──────────────────────────────────────────────────────────────┐
│ LINKING (Deterministic)                                      │
│   Validators check constraints                               │
│   Evidence collectors anchor claims                          │
│   Receipts capture provenance                                │
│   Forensic scanners measure reality                          │
└──────────────────────────────────────────────────────────────┘
                           ↓
┌──────────────────────────────────────────────────────────────┐
│ OUTPUT                                                       │
│   Trust bundle (evidence + artifacts + receipts)             │
│   Cockpit view (human-readable summary)                      │
│   Bounded change (the actual PR)                             │
└──────────────────────────────────────────────────────────────┘
```

## Plane Separation

### Control Plane (Decisions, Routing)
- Language is fine; models are good at it
- Prose handoffs work
- Navigator uses judgment

### State Plane (Artifacts, Persistence)
- Language is a liability; schema wins
- JSON envelopes required
- Receipts are structured

> The model can reason in prose. The artifacts must persist in structure.

## What "Compilation" Means Here

### Compilation Stages

| Stage | Traditional Compiler | Trust Compiler |
|-------|---------------------|----------------|
| Lexing | Tokenize source | Parse requirements |
| Parsing | Build AST | Build work plan |
| Semantic Analysis | Type checking | Constraint validation |
| Optimization | Code optimization | Evidence compression |
| Code Generation | Emit machine code | Emit bounded artifact |
| Linking | Resolve symbols | Validate evidence graph |

### Evidence Graph (The Linker's Job)

The "linking" phase builds an evidence graph:

```
specs/capabilities.yaml (canonical)
        │
        ├──→ CAPABILITIES.md (generated view)
        ├──→ Validator FR-007 (schema + invariants)
        ├──→ BDD .feature @cap tags (cross-refs)
        └──→ Evidence pointers (code/tests)
                    │
                    └──→ Kernel truth (files exist, commands run)
```

The linker ensures:
- Every pointer resolves
- No circular authority
- Anchored in kernel truth (exit codes, file hashes)

## What the System Optimizes

Not:
- Code aesthetics
- Implementation elegance
- Speed of generation

But:
- Evidence quality
- Review accessibility
- Audit completeness
- Trust throughput

> The north star metric is **quality per DevLT** (developer-lead-time per quality unit).

## Trust Budget Accounting

Every step has a trust budget:

| Cost | Description |
|------|-------------|
| +Evidence | Anchored measurement adds trust |
| +Verification | Independent check adds trust |
| -Narrative | Unanchored claim costs trust |
| -Staleness | Old evidence degrades trust |

The "compilation" succeeds when the trust bundle is above threshold.

## Why This Framing Matters

### For Architecture
- Verification infrastructure is the crown jewel
- Evidence contracts are the API
- Receipts are the artifact, not the code

### For Operations
- Review is piloting, not proofreading
- Absence is the enemy, not wrongness
- Freshness is a first-class property

### For Culture
- Pride moves upstream (intent > implementation)
- "Not measured" is honest
- Trust is earned through evidence, not claimed

## The One-Line Summary

> You're not building "a swarm that writes code."
> You're building a **compiler that emits trust**.

---

## See Also
- [META_LEARNINGS.md](./META_LEARNINGS.md) - What we learned building this
- [EMERGENT_PHYSICS.md](./EMERGENT_PHYSICS.md) - The laws that emerged
- [ATTENTION_ARBITRAGE.md](./ATTENTION_ARBITRAGE.md) - The economics
