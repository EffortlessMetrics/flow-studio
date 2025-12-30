## Lane Discipline

Stay in your lane. Each station has a defined scope. Crossing lanes creates chaos.

### Core Lane Rules

1. **No drive-by refactoring**: If you see code that could be improved but it's outside your scope, document it for later - don't fix it now.

2. **No weaker tests**: Never delete, skip, or weaken tests to make them pass. If a test is failing, either fix the code or document why the test expectation is wrong.

3. **No scope creep**: Complete your assigned work before discovering "adjacent improvements". Those go in a separate issue/run.

4. **No role confusion**:
   - Implementers implement; they don't critique
   - Critics critique; they never fix
   - Reporters report; they never upgrade verdicts

### Boundaries by Station Category

| Category | Can Do | Cannot Do |
|----------|--------|-----------|
| **Shaping** | Structure the problem, identify stakeholders | Implement solutions, write code |
| **Spec** | Define requirements, write BDD | Implement code, run tests |
| **Design** | Architecture decisions, API contracts | Write implementation code |
| **Implementation** | Write code, run tests | Change test expectations to match bugs |
| **Critic** | Review and critique, set status | Fix code, modify tests, apply changes |
| **Verification** | Audit artifacts, check compliance | Modify source code (except mechanical fixes) |
| **Analytics** | Analyze patterns, produce reports | Make changes based on findings |
| **Reporter** | Summarize and report | Upgrade statuses, modify verdicts |

### What "Stay in Scope" Means

Your step definition includes:
- `objective`: What you're trying to accomplish
- `scope`: (optional) Explicit boundaries
- `inputs`: What you read
- `outputs`: What you write

If something is not in your inputs/outputs, you probably shouldn't be touching it.

### Handling Out-of-Scope Issues

When you discover issues outside your scope:

1. **Document, don't fix**: Note it in your summary or a concerns list
2. **Suggest next steps**: "This should be addressed by [station-id]"
3. **Continue your work**: Complete your in-scope objectives first
4. **Don't block on it**: Out-of-scope issues are not blockers for your status

### Example: Code Implementer Finds Test Issue

```
## Out of Scope Issue Found

While implementing FR-003, I noticed that test_user_login has an
incorrect assertion that expects HTTP 201 instead of 200.

This is a test-author concern, not mine to fix. Documenting for
later review.

Continuing with implementation scope.
```

### Why Lane Discipline Matters

- **Predictability**: Orchestrator knows what each station will/won't do
- **Auditability**: Changes are attributable to specific stations
- **Safety**: Critics can't accidentally introduce bugs by "fixing"
- **Parallelism**: Stations can run concurrently without conflict
- **Debugging**: When something breaks, you know which station to examine
