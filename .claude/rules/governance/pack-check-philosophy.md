# Pack-Check Philosophy: Competence Over Compliance

Pack-check validates **competence properties**, not schema compliance. This is the anti-bureaucracy stance.

## The Problem with Schema Validation

Traditional validation enforces structure:
- "Must have exactly these fields"
- "Must use this enum value"
- "Must follow this format"

This creates:
- Template-filling behavior
- Compliance theater
- Checkbox ticking
- Form over substance

## The Solution: Competence Properties

Pack-check asks: "Can this agent do its job well?"

Not: "Does it have the right fields?"
But: "Does it have what it needs to succeed?"

## What Pack-Check Validates

### Agent Competence

| Check | Question | Not Checking |
|-------|----------|--------------|
| Single job | Does it do one thing? | Specific wording |
| Clear inputs | Does it know what it reads? | Input format |
| Clear outputs | Does it know what it produces? | Output schema |
| Stuck handling | Does it know what to do when blocked? | Specific actions |
| Handoff | Does it pass context forward? | Handoff format |

### Flow Competence

| Check | Question | Not Checking |
|-------|----------|--------------|
| Connectivity | Do steps connect? | Step ordering |
| Agent coverage | Are agents defined? | Agent count |
| Artifact paths | Are paths valid? | Specific names |

### Structural Integrity

| Check | Question | Not Checking |
|-------|----------|--------------|
| Bijection | Do agents match registry? | Registry format |
| References | Do references resolve? | Reference style |
| Frontmatter | Are required fields present? | Field values |

## What Pack-Check Does NOT Validate

### ❌ Specific Enumerations
```yaml
# Not this:
status: must be one of [VERIFIED, UNVERIFIED, BLOCKED]
```

### ❌ Output Schemas
```yaml
# Not this:
output: must match HandoffEnvelope schema
```

### ❌ Template Compliance
```yaml
# Not this:
prompt: must have ## Inputs, ## Outputs, ## Behavior sections
```

### ❌ Stylistic Preferences
```yaml
# Not this:
description: must be under 100 characters
```

## Validation Levels

### Level 1: Structure (Always)
- Files exist where expected
- YAML/Markdown parses
- Required directories present

### Level 2: Integrity (Always)
- References resolve (FR-001, FR-003)
- No dangling pointers
- Bijection maintained

### Level 3: Competence (Default)
- Agents have clear purpose
- Inputs/outputs declared
- Stuck handling present
- Handoff exists

### Level 4: Style (Optional, --strict)
- Prompt sections present
- Naming conventions
- Documentation complete

## The Warning-First Approach

Pack-check prefers warnings over errors:

```
WARNING: Agent 'code-critic' missing ## When Stuck section
  → Agent may not handle edge cases gracefully
  → Consider adding stuck handling guidance

ERROR: Agent 'code-critic' not found in registry
  → This will break flow execution
  → Add to AGENTS.md or remove reference
```

Warnings don't block. They inform.
Errors block. They prevent breakage.

## The Rule

> Validate competence, not compliance.
> Warn about gaps, error on breakage.
> Form follows function, not the reverse.

## Anti-Patterns

### ❌ Schema Religion
"If it doesn't match the schema, reject it"

**Problem:** Encourages template-filling, discourages thinking

### ❌ Enumeration Enforcement
"Status must be exactly VERIFIED, UNVERIFIED, or BLOCKED"

**Problem:** Prevents graceful evolution, breaks on new states

### ❌ Format Policing
"All descriptions must be sentence case with period"

**Problem:** Wastes attention on irrelevant details

## The Competence Checklist

For a new agent, ask:
1. Does it have one clear job? (Single responsibility)
2. Does it know its inputs? (Can it start?)
3. Does it know its outputs? (Can it finish?)
4. Does it know what to do when stuck? (Graceful degradation)
5. Does it hand off properly? (Continuity)

If yes to all five: competent.
If no to any: needs work.

## Current Implementation

See `swarm/tools/validate_swarm.py` for validation rules.
FR-001 through FR-006 implement this philosophy.

## The Economics

Schema validation is cheap but low-value.
Competence validation is harder but high-value.

We optimize for: agents that work well.
Not for: agents that look right.
