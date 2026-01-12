# Explanation Documents

This directory contains teaching documents that explain the **why** behind Flow Studio's design.

These are "textbook" documents—they teach concepts. For the actual rules that are
enforced, see `.claude/rules/`.

## Document Index

### Core Concepts

| Document | Purpose |
|----------|---------|
| [ATTENTION_ARBITRAGE.md](./ATTENTION_ARBITRAGE.md) | The economic engine (trade tokens for senior attention) |
| [TRUTH_HIERARCHY.md](./TRUTH_HIERARCHY.md) | What counts as evidence (physics > receipts > narrative) |
| [BOUNDARY_PHYSICS.md](./BOUNDARY_PHYSICS.md) | Why isolation enables autonomy (sandbox + publish gates) |
| [ADVERSARIAL_LOOPS.md](./ADVERSARIAL_LOOPS.md) | How opposition creates reliability (author ⇄ critic) |
| [OPERATING_MODEL.md](./OPERATING_MODEL.md) | The PM/IC organization (kernel/navigator/agents) |
| [NAVIGATOR_PROTOCOL.md](./NAVIGATOR_PROTOCOL.md) | How routing decisions are made (deterministic-first, LLM-fallback) |
| [PORTS_AND_ADAPTERS.md](./PORTS_AND_ADAPTERS.md) | Engine-agnostic architecture (transport abstraction) |
| [CLAIMS_VS_EVIDENCE.md](./CLAIMS_VS_EVIDENCE.md) | The Sheriff pattern (forensics over narrative) |
| [OBSERVABLE_BY_DEFAULT.md](./OBSERVABLE_BY_DEFAULT.md) | Everything leaves a trace (receipts + artifacts) |
| [FORENSICS_OVER_TESTIMONY.md](./FORENSICS_OVER_TESTIMONY.md) | Legal epistemology applied to AI trust |
| [FORENSIC_SCANNERS.md](./FORENSIC_SCANNERS.md) | The Sheriff's tools (diff scanner, test parser) |
| [NARROW_TRUST.md](./NARROW_TRUST.md) | The trust equation (scope x evidence x verification) |
| [CLAIMS_REGISTER.md](./CLAIMS_REGISTER.md) | Meta-honesty: what's implemented vs aspirational |
| [WISDOM_PIPELINE.md](./WISDOM_PIPELINE.md) | How learnings become rules (governance evolution) |
| [SCARCITY_AS_DESIGN.md](./SCARCITY_AS_DESIGN.md) | Why token limits are features, not bugs (constraint-driven design) |
| [CONTEXT_DISCIPLINE.md](./CONTEXT_DISCIPLINE.md) | Why session amnesia is a feature (rehydration over conversation) |
| [SCENT_TRAIL.md](./SCENT_TRAIL.md) | Decision breadcrumbs between steps (how agents know "how we got here") |
| [COMPRESSION_AS_VALUE.md](./COMPRESSION_AS_VALUE.md) | Why throwing away context is the job (context compression) |
| [STAGED_PUBLICATION.md](./STAGED_PUBLICATION.md) | The draft/publish paradigm (lab vs journal) |

### Meta-Learnings & Emergent Physics

| Document | Purpose |
|----------|---------|
| [META_LEARNINGS.md](./META_LEARNINGS.md) | What we learned building this system (15 implementation lessons) |
| [EMERGENT_PHYSICS.md](./EMERGENT_PHYSICS.md) | The laws that fell out (12 non-negotiable constraints) |
| [TRUST_COMPILER.md](./TRUST_COMPILER.md) | The synthesis: what this system actually is |
| [VALIDATOR_AS_LAW.md](./VALIDATOR_AS_LAW.md) | Why pack-check is the constitution |
| [REVIEW_AS_PILOTING.md](./REVIEW_AS_PILOTING.md) | The new review skill (evidence auditing, not diff-reading) |

## The Core Philosophy

These documents encode Steven Zimmerman's AI-native development vision:

### The Economic Thesis
> Code generation is fast, good, and cheap. The bottleneck is trust.

### The Trade
> Spend compute to save senior engineer attention.

### The Posture
> Autonomy inside containment; gated publishing at exits.

## Reading Paths

### Path A: Physics Foundation (for architects)
Start here to understand the underlying constraints:
1. **ATTENTION_ARBITRAGE.md** - The economic engine
2. **EMERGENT_PHYSICS.md** - The 12 laws that emerged
3. **TRUTH_HIERARCHY.md** - What counts as evidence
4. **BOUNDARY_PHYSICS.md** - Why isolation enables autonomy
5. **OPERATING_MODEL.md** - The PM/IC organization
6. **TRUST_COMPILER.md** - What this system actually is

### Path B: Meta-Learning (for system designers)
Start here to understand how the system was built:
1. **META_LEARNINGS.md** - The 15 implementation lessons
2. **VALIDATOR_AS_LAW.md** - Why pack-check is the constitution
3. **WISDOM_PIPELINE.md** - How learnings become rules
4. **CLAIMS_REGISTER.md** - What's implemented vs aspirational
5. **CLAIMS_VS_EVIDENCE.md** - The Sheriff pattern

### Path C: Operations (for reviewers and operators)
Start here to understand how to use the system:
1. **REVIEW_AS_PILOTING.md** - The new review skill
2. **OBSERVABLE_BY_DEFAULT.md** - Everything leaves a trace
3. **FORENSICS_OVER_TESTIMONY.md** - Legal epistemology applied to AI trust
4. **FORENSIC_SCANNERS.md** - The Sheriff's tools
5. **STAGED_PUBLICATION.md** - The draft/publish paradigm

### Path D: Complete Reading Order (for newcomers)
The full sequence from first principles:
1. **ATTENTION_ARBITRAGE.md** - Understand the core economic trade
2. **OPERATING_MODEL.md** - Understand the hierarchy (kernel/navigator/agents)
3. **NAVIGATOR_PROTOCOL.md** - Understand how routing decisions are made
4. **TRUTH_HIERARCHY.md** - Understand what counts as evidence
5. **BOUNDARY_PHYSICS.md** - Understand containment
6. **ADVERSARIAL_LOOPS.md** - Understand microloops
7. **CLAIMS_VS_EVIDENCE.md** - Understand the Sheriff pattern
8. **OBSERVABLE_BY_DEFAULT.md** - Everything leaves a trace
9. **FORENSICS_OVER_TESTIMONY.md** - Legal epistemology applied to AI trust
10. **FORENSIC_SCANNERS.md** - The tools that implement forensics
11. **NARROW_TRUST.md** - Understand the trust equation
12. **PORTS_AND_ADAPTERS.md** - Understand the transport layer
13. **WISDOM_PIPELINE.md** - Understand how the factory improves itself
14. **SCARCITY_AS_DESIGN.md** - Understand why limits are features
15. **CONTEXT_DISCIPLINE.md** - Understand session amnesia and rehydration
16. **SCENT_TRAIL.md** - Understand decision provenance between steps
17. **COMPRESSION_AS_VALUE.md** - Understand why context compression creates value
18. **STAGED_PUBLICATION.md** - Understand the draft/publish paradigm
19. **CLAIMS_REGISTER.md** - See what's actually implemented vs designed
20. **META_LEARNINGS.md** - What we learned building this
21. **EMERGENT_PHYSICS.md** - The laws that fell out
22. **TRUST_COMPILER.md** - The synthesis
23. **VALIDATOR_AS_LAW.md** - Why pack-check is law
24. **REVIEW_AS_PILOTING.md** - The new review skill

## The Implementation Gap

These teaching documents describe the **design philosophy**. Not all capabilities are fully implemented.

**To understand what's actually shipped:**
- [CLAIMS_REGISTER.md](./CLAIMS_REGISTER.md) is the source of truth for implemented vs aspirational
- [.claude/rules/README.md](../../.claude/rules/README.md) shows which rules are enforced
- The capability registry (`specs/capabilities.yaml`) binds claims to evidence

**The rule:** Claims require evidence. "Not measured" is valid. False certainty is not.

## Related Documents

- [docs/AGOPS_MANIFESTO.md](../AGOPS_MANIFESTO.md) - The full AgOps philosophy
- [docs/ROUTING_PROTOCOL.md](../ROUTING_PROTOCOL.md) - V3 routing specification
- [docs/LEXICON.md](../LEXICON.md) - Canonical vocabulary
- [.claude/rules/](../../.claude/rules/) - Enforced rules

## Flow Studio vs DemoSwarm

Two repos, same AgOps philosophy, different focus:

| Aspect | Flow Studio (this repo) | DemoSwarm (sister repo) |
|--------|------------------------|-------------------------|
| **Focus** | Factory physics | Agent craft |
| **Teaches** | Orchestration, routing, receipts | Agent design, prompts, roles |
| **Contains** | Kernel, transports, flows 1-7 | Portable `.claude/` pack |
| **Use case** | Run the full SDLC pipeline | Embed agents in your repo |

**Flow Studio** is where you learn how the factory works: how steps route, how evidence flows, how the kernel enforces physics.

**DemoSwarm** is where you learn how agents work: how to design prompts, define roles, and craft behavioral contracts.

Both share the core AgOps principles:
- Trade compute for attention
- Evidence over narrative
- Containment enables autonomy
- Receipts are the audit trail
