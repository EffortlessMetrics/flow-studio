# Validator as Law: The Authority Model

In Flow Studio, the validator is the closest thing to law. This document explains why.

## The Problem

Three sources of truth compete in any system:
1. **Documentation** - What humans wrote
2. **LLM narrative** - What agents claim
3. **Validation** - What actually passes checks

In traditional systems, documentation wins conflicts (humans trust docs).
In AI-native systems, this creates drift because:
- LLMs hallucinate and contradict themselves
- Humans make judgment calls inconsistently
- Docs drift from reality without anyone noticing

## The Solution: Validator Supremacy

The validator is the closest thing to law because it is:
- **Deterministic** - Same input, same verdict
- **Unambiguous** - Pass or fail, no "maybe"
- **Always consulted** - CI gates on it

> If the validator rejects it, it's not valid—regardless of what docs say or agents claim.

## How Validation Encodes the Constitution

Each Functional Requirement (FR) encodes a constitutional principle:

| FR | Principle Encoded |
|----|-------------------|
| FR-001: Bijection | Single source of truth for agents |
| FR-002: Frontmatter | Required metadata for routing |
| FR-003: Flow References | No orphan agents |
| FR-004: Skills | Declared capabilities exist |
| FR-005: RUN_BASE | Portable artifact paths |
| FR-006: Prompt Sections | Competent agent documentation |
| FR-007: Capability Registry | Evidence discipline |

## The Authority Hierarchy

```
Level 1: Validator verdict (deterministic, final)
   ↑ overrides
Level 2: Configuration files (YAML, frontmatter)
   ↑ overrides
Level 3: Documentation (explanatory prose)
   ↑ overrides
Level 4: Agent narrative (LLM claims)
```

When sources conflict, higher levels win.

## Pack-Check Philosophy

The validator doesn't enforce schema compliance (bureaucracy). It validates **competence properties**:

### What We Check
- Can the agent do its job? (inputs/outputs defined)
- Does it know what to do when stuck? (graceful degradation)
- Does it hand off properly? (continuity)

### What We Don't Check
- Specific field enumerations
- Output schema conformance
- Stylistic preferences
- Template compliance

> Validate competence, not compliance. Form follows function.

## Warning-First, Error-Second

The validator prefers warnings over errors:

```
WARNING: Agent 'code-critic' missing ## When Stuck section
  → Agent may not handle edge cases gracefully

ERROR: Agent 'code-critic' not found in registry
  → This will break flow execution
```

**Warnings inform.** They don't block.
**Errors block.** They prevent breakage.

## The Override Path

**There isn't one.**

If the validator rejects something:
1. Fix the thing
2. Or change the validation rule (with justification)

You cannot override individual validation results. This is by design.

## Why This Matters

### For Operators
- If validator passes → safe to merge
- If validator fails → not safe to merge
- No judgment calls required at the gate

### For Contributors
- Learn the constitution through error messages
- Validation failures are teaching moments
- The validator is the fastest path to "doing it right"

### For the System
- Drift is mechanically prevented
- Physics are enforced, not suggested
- The "real spec" is what breaks the build

## The Inversion

Traditional: "Document the rules, hope people follow them"
AgOps: "Encode the rules, let the validator enforce them"

> The canonical meaning of a rule is "what fails the build," not what the docs say.

---

## See Also
- [VALIDATION_RULES.md](../VALIDATION_RULES.md) - The FRs in detail
- [pack-check-philosophy.md](../../.claude/rules/governance/pack-check-philosophy.md) - Competence over compliance
- [truth-hierarchy.md](../../.claude/rules/governance/truth-hierarchy.md) - Evidence levels
