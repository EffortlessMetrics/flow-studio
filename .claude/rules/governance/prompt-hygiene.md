# Prompt Hygiene

**"Vague prompts produce vague work."**

This rule defines how to write effective prompts for agents. Prompts are not suggestions; they are contracts.

## Teaching Notes Structure

Every agent prompt follows the teaching notes format. Required sections:

| Section | Purpose | Omission Risk |
|---------|---------|---------------|
| **Objective** | Single sentence: what this step accomplishes | Agent wanders |
| **Inputs** | Explicit paths to consumed artifacts | Agent invents data |
| **Outputs** | Explicit paths to produced artifacts | Artifacts get lost |
| **Behavior** | Role-specific instructions | Role confusion |
| **Success Criteria** | Measurable completion conditions | Agent claims "done" prematurely |
| **When Stuck** | Escape hatches for edge cases | Agent blocks unnecessarily |

### Minimal Valid Teaching Note

```markdown
## Objective
Implement the authentication module per ADR-005.

## Inputs
- `RUN_BASE/plan/adr.md` - Architecture decisions
- `RUN_BASE/plan/work_plan.md` - Task breakdown

## Outputs
- `src/auth.py` - Authentication implementation
- `tests/test_auth.py` - Unit tests
- `RUN_BASE/build/impl_notes.md` - Assumptions and decisions

## Behavior
- Follow ADR-005 OAuth2 specification
- Write tests before implementation
- Document assumptions in impl_notes.md

## Success Criteria
- All work_plan.md items marked complete
- pytest tests/test_auth.py exits 0
- No new lint errors (ruff check src/auth.py exits 0)

## When Stuck
- Ambiguous requirement: Document assumption, proceed with UNVERIFIED
- Missing dependency: Set BLOCKED with specific package name
- Test failure: Document failure, request iteration
```

## Context Loading Order

Prompts are assembled from context with strict priority:

| Priority | Content | Drop Policy |
|----------|---------|-------------|
| **CRITICAL** | Teaching notes, step spec | Never drop |
| **HIGH** | Previous step output | Truncate if over budget |
| **MEDIUM** | Referenced artifacts | Load on-demand |
| **LOW** | History summary, scent trail | Drop first |

### Budget Awareness

```markdown
## Context Budget
- Max input: 25000 tokens
- Priority order: teaching_notes > previous_step > artifacts > history
- If over budget: Drop history, then truncate artifacts
```

Agents do not decide what to load. The kernel loads based on priority. Prompts declare what matters.

## Banned Patterns

These patterns produce unreliable behavior. They are banned.

### Vague Instructions

| Banned | Why | Alternative |
|--------|-----|-------------|
| "Do your best" | Unmeasurable | "Ensure all tests pass" |
| "Be thorough" | Unmeasurable | "Check each requirement in spec.md" |
| "Consider carefully" | No output | "Document decision in ADR format" |
| "Make sure it works" | No criteria | "Exit code 0 on `pytest tests/`" |

### Unbounded Scope

| Banned | Why | Alternative |
|--------|-----|-------------|
| "Fix everything" | Infinite scope | "Fix items 1-5 in work_plan.md" |
| "Improve the code" | No definition | "Reduce cyclomatic complexity below 10" |
| "Clean up" | No boundary | "Remove unused imports per ruff output" |
| "Make it production-ready" | Undefined | "Add error handling per contracts.md" |

### Self-Evaluation Requests

| Banned | Why | Alternative |
|--------|-----|-------------|
| "Did you do a good job?" | Agents say yes | Run tests, check exit code |
| "Are you confident?" | Agents say yes | Cite evidence or set UNVERIFIED |
| "Rate your work" | Self-serving | Critic agent evaluates |
| "Is this complete?" | Agents say yes | Check against success criteria |

### Hedging Language

| Banned | Why | Alternative |
|--------|-----|-------------|
| "Try to" | Implies optional | "Do X" |
| "Maybe" | Implies optional | "If X then Y, else Z" |
| "If possible" | Ambiguous | "If X fails, set BLOCKED with reason" |
| "Consider" | No commitment | "Evaluate and document decision" |
| "Attempt to" | Implies failure OK | "Do X or set status to UNVERIFIED" |

## Required Patterns

Every prompt MUST include:

### Concrete Success Criteria

```markdown
## Success Criteria
- `pytest tests/ -v` exits 0
- Coverage > 80% (evidence: coverage.json)
- No HIGH severity lint errors (evidence: ruff_output.log)
- All items in work_plan.md addressed
```

Not:
```markdown
## Success Criteria
- Tests pass
- Good coverage
- Code is clean
```

### Explicit Artifact Paths

```markdown
## Outputs
- `src/auth/oauth.py` - OAuth2 implementation
- `tests/test_oauth.py` - OAuth2 tests
- `RUN_BASE/build/receipts/step-3-code.json` - Execution receipt
```

Not:
```markdown
## Outputs
- Implementation code
- Tests
- Receipt
```

### Evidence Requirements

```markdown
## Evidence
Capture these for VERIFIED status:
- Test output: `pytest tests/ -v 2>&1 | tee RUN_BASE/build/test_output.log`
- Lint output: `ruff check src/ 2>&1 | tee RUN_BASE/build/lint_output.log`
- Diff summary: `git diff --stat > RUN_BASE/build/diff_summary.txt`
```

Not:
```markdown
## Evidence
- Run tests
- Check linting
- Review changes
```

### Escape Hatches

```markdown
## When Stuck
| Situation | Action | Status |
|-----------|--------|--------|
| Ambiguous requirement | Document assumption in impl_notes.md | UNVERIFIED |
| Missing input file | Cite missing path | BLOCKED |
| Test failure after 3 attempts | Document failure, cite test output | UNVERIFIED |
| Dependency conflict | Document in concerns, proceed | UNVERIFIED |
```

Not:
```markdown
## When Stuck
Ask for help.
```

## Anti-Patterns with Examples

### Context Pollution

Loading irrelevant history wastes tokens and confuses the agent.

**Bad:**
```markdown
## Context
Load the entire conversation history so you understand what happened.
```

**Good:**
```markdown
## Context
Previous step produced: `RUN_BASE/plan/work_plan.md`
Scent trail: OAuth2 approach selected (ADR-005), using existing auth library
```

**Rule:** Load artifacts, not conversation. Scent trail provides decision history.

### Role Confusion

Mixing roles produces poor work in both domains.

**Bad:**
```markdown
## Behavior
Implement the code, then review it yourself to make sure it's correct.
Write tests and verify they're comprehensive enough.
```

**Good:**
```markdown
## Behavior (Implementer)
Implement the code per spec. Write tests. Set status to UNVERIFIED.

---

## Behavior (Critic - separate agent)
Review implementation against spec. Cite file:line for every issue.
State whether iteration can help. Never fix the code.
```

**Rule:** One agent, one job. Critics never fix. Implementers never self-review.

### Narrative Over Evidence

Asking for explanations instead of receipts produces prose, not proof.

**Bad:**
```markdown
## Outputs
- Explanation of what you implemented
- Summary of how you tested it
- Description of any issues you found
```

**Good:**
```markdown
## Outputs
- `src/auth.py` - Implementation (artifact)
- `RUN_BASE/build/test_output.log` - pytest output (evidence)
- `RUN_BASE/build/concerns.json` - Structured issues with file:line (evidence)
```

**Rule:** Evidence is files and exit codes. Narrative is not evidence.

### Open-Ended Questions

Questions invite rambling. Statements invite compliance.

**Bad:**
```markdown
## Behavior
What do you think is the best approach for implementing authentication?
How should we handle error cases?
```

**Good:**
```markdown
## Behavior
Implement authentication using OAuth2 per ADR-005.
Handle errors by returning structured error responses per contracts.md.
```

**Rule:** Prompts are instructions, not conversations.

### Missing Constraints

Unconstrained work expands to fill available context.

**Bad:**
```markdown
## Behavior
Refactor the authentication module to improve quality.
```

**Good:**
```markdown
## Behavior
Refactor `src/auth.py`:
- Extract `validate_token()` to `src/auth/validators.py`
- Add type hints to all public functions
- Do NOT modify `src/auth/legacy.py` (out of scope)
```

**Rule:** Define what is in scope AND what is out of scope.

## The Rule

> Prompts are contracts, not suggestions.
> Concrete beats vague. Binary beats hedged. Evidence beats narrative.
> Every prompt has: objective, inputs, outputs, criteria, escape hatches.

## Validation Checklist

Before deploying a prompt, verify:

- [ ] Objective is one sentence, binary pass/fail
- [ ] All inputs have explicit paths
- [ ] All outputs have explicit paths
- [ ] Success criteria are measurable (exit codes, file existence, counts)
- [ ] Evidence requirements specify capture commands
- [ ] When Stuck covers: ambiguity, missing input, repeated failure
- [ ] No banned phrases (search for: "try to", "if possible", "be thorough")
- [ ] No self-evaluation requests
- [ ] No open-ended questions
- [ ] Scope is bounded (explicit out-of-scope items)

## See Also

- [teaching-notes-contract.md](../artifacts/teaching-notes-contract.md) - Full teaching notes spec
- [context-discipline.md](../execution/context-discipline.md) - Context loading rules
- [evidence-discipline.md](./evidence-discipline.md) - What counts as evidence
- [agent-behavioral-contracts.md](./agent-behavioral-contracts.md) - Role family rules
