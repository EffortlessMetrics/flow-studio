# Flow Charters: The Constitution for Scope Control

Flow charters define the objective, boundaries, and exit criteria for each flow. They prevent scope creep and keep work focused.

## Purpose

Every flow has a charter that answers:
- What is this flow trying to achieve?
- What questions must be answered before exit?
- What is explicitly out of scope?
- When is the flow "done"?

## Charter Schema

```yaml
flow_charter:
  flow_key: "build"

  goal: |
    Transform the approved plan into working, tested code.

  key_question: |
    Does the implementation satisfy the requirements with evidence?

  exit_criteria:
    - All work plan items addressed
    - Tests pass (or failures documented)
    - No HIGH severity critic concerns unaddressed
    - Handoff envelope complete with evidence

  non_goals:
    - Refactoring unrelated code
    - Adding features not in requirements
    - Optimizing performance (unless specified)
    - Updating documentation beyond code comments

  prime_directive: |
    Complete the planned work with evidence. Do not expand scope.
```

## Flow Charters by Flow

### Flow 1: Signal
```yaml
goal: Transform raw input into structured requirements
key_question: Do we understand what needs to be built?
exit_criteria:
  - Problem statement clear
  - Requirements enumerated
  - BDD scenarios drafted
  - Initial risks identified
non_goals:
  - Solving the problem
  - Making architectural decisions
  - Writing code
```

### Flow 2: Plan
```yaml
goal: Design the solution architecture and work breakdown
key_question: Do we have a viable, reviewable plan?
exit_criteria:
  - ADR documents key decisions
  - Contracts define interfaces
  - Work plan is actionable
  - Test plan covers requirements
non_goals:
  - Implementing the solution
  - Writing production code
  - Running tests
```

### Flow 3: Build
```yaml
goal: Implement the planned work with tests
key_question: Does the code work and have evidence?
exit_criteria:
  - Work plan items complete
  - Tests pass
  - Critics have reviewed
  - Evidence captured in receipts
non_goals:
  - Refactoring unrelated code
  - Adding unplanned features
  - Premature optimization
```

### Flow 4: Review
```yaml
goal: Harvest feedback and apply fixes in the shadow fork
key_question: Is feedback addressed and work ready for gate?
exit_criteria:
  - All actionable feedback addressed
  - Fixes applied and verified
  - Review receipt produced
non_goals:
  - Implementing new features
  - Major refactoring
  - Scope expansion from feedback
```

**Note:** PR status (Draft/Ready) is informational output, not a control point. Flow 4 completes when work items are resolved, regardless of PR status.

### Flow 5: Gate
```yaml
goal: Audit and decide merge-worthiness
key_question: Is this change safe and correct to merge?
exit_criteria:
  - Evidence reviewed
  - Policy checks pass
  - Merge recommendation made
non_goals:
  - Fixing issues (bounce to Build)
  - Implementing changes
  - Expanding requirements
```

### Flow 6: Deploy
```yaml
goal: Merge approved changes and verify deployment
key_question: Is the change successfully deployed and healthy?
exit_criteria:
  - Merge complete
  - CI passes
  - Health checks green
  - Audit trail recorded
non_goals:
  - Fixing deployment issues (escalate)
  - Feature work
  - Rollback (separate flow)
```

### Flow 7: Wisdom
```yaml
goal: Extract learnings and close feedback loops
key_question: What did we learn and how do we improve?
exit_criteria:
  - Artifacts analyzed
  - Patterns identified
  - Recommendations produced
  - Feedback routed
non_goals:
  - Implementing improvements (propose only)
  - Current run changes
  - Blocking future work
```

## Using Charters in Routing

The Navigator checks decisions against the charter:

```python
def is_goal_aligned(decision, charter):
    # Does this help achieve the flow's goal?
    if decision.action in charter.non_goals:
        return False, "Action is explicitly out of scope"
    if not helps_answer_key_question(decision, charter):
        return False, "Action doesn't help answer key question"
    return True, None
```

## The Rule

> Every routing decision passes the charter test:
> "Does this help achieve the flow's objective?"
> If not in service of the goal, reject or escalate.

## Charter Violations

When work drifts from charter:

### Detected Drift
```json
{
  "violation": "scope_creep",
  "action": "Refactoring auth module",
  "charter_check": "Refactoring unrelated code is a non-goal",
  "recommendation": "Defer to separate task"
}
```

### Resolution
- Log the drift in observations
- Either: reject the action, or
- Escalate for human decision

## The Economics

Charters prevent:
- Unbounded scope expansion
- Yak shaving
- "While I'm here" changes
- Review burden from unrelated changes

Focused flows are:
- Faster to complete
- Easier to review
- Simpler to debug
- Cheaper to run
