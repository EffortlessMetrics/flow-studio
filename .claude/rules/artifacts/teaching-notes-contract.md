# Teaching Notes Contract

Teaching notes are the "step instructions" — they tell an agent what to do for a specific step.

## Purpose

Teaching notes provide:
- Step-specific context (what this step does)
- Behavioral guidance (how to do it)
- Success criteria (what "done" looks like)
- Failure handling (what to do when stuck)

## Required Sections

Every teaching note MUST include:

### 1. Objective
What this step accomplishes. One sentence.

```markdown
## Objective
Implement the code changes specified in the work plan.
```

### 2. Inputs
What artifacts this step consumes. With paths.

```markdown
## Inputs
- Work plan: `RUN_BASE/plan/work_plan.md`
- ADR: `RUN_BASE/plan/adr.md`
- Contracts: `RUN_BASE/plan/contracts.md`
```

### 3. Outputs
What artifacts this step produces. With paths.

```markdown
## Outputs
- Modified source files (in `src/`)
- New/modified tests (in `tests/`)
- Implementation notes: `RUN_BASE/build/impl_notes.md`
```

### 4. Success Criteria
How to know when the step is complete.

```markdown
## Success Criteria
- All work plan items addressed
- Tests pass locally
- No new lint errors introduced
```

### 5. Behavior Guidelines
Role-specific instructions.

```markdown
## Behavior
- Follow the ADR architecture decisions
- Implement minimal code to satisfy requirements
- Write tests for new functionality
- Document any assumptions made
```

### 6. When Stuck
What to do if the step cannot complete normally.

```markdown
## When Stuck
- If requirements are ambiguous: Document assumption, proceed with UNVERIFIED
- If dependency is missing: Set BLOCKED with specific missing item
- If tests fail unexpectedly: Document failure, request iteration
```

## Optional Sections

### Context Budget
Token budget for this step.

```markdown
## Context Budget
- Max input context: 20000 tokens
- Priority: teaching_notes > previous_step > artifacts
```

### Iteration Hints
For steps in microloops.

```markdown
## Iteration
- Max iterations: 3
- Exit when: Critic finds no HIGH severity issues
- On repeated failure: Route to auto-linter
```

### Evidence Requirements
What evidence must be captured.

```markdown
## Evidence
- Capture: test output, lint output, diff summary
- Required for: VERIFIED status
```

## Teaching Notes Location

Teaching notes are defined in flow specs:
```
swarm/flows/<flow-key>.md
```

And may be augmented per-step in:
```
swarm/config/flows/<flow-key>/steps/<step-id>.yaml
```

## Loading Order

When a step runs, teaching notes are assembled:
1. Flow-level defaults
2. Step-specific overrides
3. Runtime context (run_id, previous outputs)

## The Rule

> Teaching notes are the contract between kernel and agent.
> Required sections ensure agents know what to do.
> When Stuck section ensures graceful degradation.

## Anti-Patterns

### Vague Objective
```markdown
## Objective
Do the thing.
```

### Clear Objective
```markdown
## Objective
Implement user authentication using OAuth2 as specified in ADR-005.
```

### Missing Inputs
```markdown
## Inputs
The usual files.
```

### Explicit Inputs
```markdown
## Inputs
- `RUN_BASE/plan/adr.md` - Architecture decisions
- `RUN_BASE/plan/work_plan.md` - Implementation tasks
```

### No Stuck Handling
(Section omitted entirely)

### Explicit Stuck Handling
```markdown
## When Stuck
- Document the blocker
- Set status to BLOCKED or UNVERIFIED
- Include what would unblock
```
