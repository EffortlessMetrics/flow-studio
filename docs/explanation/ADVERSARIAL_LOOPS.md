# Adversarial Loops: How Opposition Creates Reliability

> **Status:** Living document
> **Purpose:** Teaching doc for microloop patterns

## The Sycophancy Problem

LLMs are trained to be helpful. This creates a failure mode:

- They want to please
- They want to agree
- They want to say "yes"

When the same agent writes code AND evaluates it, you get:
- "My code looks correct to me"
- Blind spots go unnoticed
- Errors compound

## The Solution: Adversarial Structure

Flow Studio uses **adversarial loops** where different agents have
**opposing incentives**:

| Role | Incentive | Bias |
|------|-----------|------|
| **Author** | Complete the work | "It's good enough" |
| **Critic** | Find problems | "Something is wrong" |

Neither is objective. But their **opposition creates objectivity**.

## The Author ⇄ Critic Pattern

### Flow 1: Requirements Loop
```
requirements-author  ⟷  requirements-critic
    "I captured         "You missed
     the requirements"   edge case X"
```

### Flow 3: Test Loop
```
test-author  ⟷  test-critic
    "Tests cover        "Test at line 42
     all paths"          doesn't test
                         the failure case"
```

### Flow 3: Code Loop
```
code-implementer  ⟷  code-critic
    "Implementation      "Input validation
     is complete"         missing at line 87"
```

## Why Critics Never Fix

**The Rule:** Critics write harsh reports. They NEVER fix the code.

**Why:**
1. **Separation of concerns** - Creation and verification are different skills
2. **No half-measures** - If critic fixes, they might half-fix and move on
3. **Clear accountability** - Author owns the fix; critic owns the critique
4. **Fresh perspective** - Fixer sees critique, not their own prior work

**What happens if critic fixes:**
- Critic invests ego in fix
- Critique quality degrades
- No clear handoff
- Same blind spots persist

## Loop Exit Conditions

Loops don't run forever. They exit when:

### 1. VERIFIED Status
Critic finds no issues. Work meets spec.
```json
{
  "status": "VERIFIED",
  "concerns": [],
  "routing": {
    "recommendation": "CONTINUE",
    "can_further_iteration_help": false
  }
}
```

### 2. No Viable Fix Path
Critic finds issues BUT further iteration won't help.
```json
{
  "status": "UNVERIFIED",
  "concerns": [...],
  "routing": {
    "recommendation": "CONTINUE",
    "can_further_iteration_help": false,
    "reason": "Issues require architectural change beyond this step's scope"
  }
}
```

### 3. Iteration Limit
Too many loops without progress.
```json
{
  "loop_iteration": 3,
  "max_iterations": 3,
  "routing": {
    "recommendation": "CONTINUE",
    "reason": "Iteration limit reached; advancing with documented concerns"
  }
}
```

### 4. Repeated Failure
Same error twice in a row indicates stuck condition.
```json
{
  "routing": {
    "recommendation": "DETOUR",
    "reason": "Repeated failure signature; routing to known fix pattern"
  }
}
```

## Critique Quality Standards

Good critiques are:

### Specific
❌ "The code has issues"
✅ "Function `validate_token` at `src/auth.py:42` lacks error handling
   for expired tokens"

### Cited
❌ "Tests are incomplete"
✅ "Test `test_login_success` at `tests/test_auth.py:15` only tests happy
   path; no test for invalid credentials"

### Actionable
❌ "Security could be better"
✅ "Add input validation before database query at `src/db.py:87` to
   prevent SQL injection"

### Rated
```json
{
  "severity": "HIGH",
  "effort": "SMALL",
  "description": "Missing input validation",
  "recommendation": "Add validation function call before line 87"
}
```

## The Mutual Distrust Model

The system assumes:

- **Authors will claim success prematurely** → Critics verify
- **Critics will over-criticize** → Evidence requirements bound critique
- **Both might be wrong** → Forensic tools provide ground truth

No single agent is trusted. The **structure** creates reliability.

## When to Escalate vs Loop

### Loop (Continue Iteration)
- Specific, fixable issues found
- Author has context to fix
- Iteration budget remains
- Fix is within step's scope

### Escalate (Exit Loop)
- Issues require human decision
- Architectural change needed
- Blocked by external dependency
- Repeated failure pattern

## Microloop Mechanics

The kernel manages loops:

```python
while loop_iteration < max_iterations:
    # Author phase
    author_result = run_author(context)

    # Critic phase
    critic_result = run_critic(author_result)

    if critic_result.status == "VERIFIED":
        break  # Exit: success

    if not critic_result.can_further_iteration_help:
        break  # Exit: no viable fix path

    if critic_result.matches_previous_failure():
        route_to_detour()
        break  # Exit: stuck, try different approach

    loop_iteration += 1
    context = prepare_next_iteration(critic_result)
```

## The Economics

Why adversarial loops are worth the extra compute:

| Without Loops | With Loops |
|---------------|------------|
| 1 pass, hope it's right | Iterate until verified |
| Bugs found in review | Bugs found before review |
| Human debugs | Agent debugs |
| Hours of senior time | Minutes of compute |

**Trade compute for attention.** Loops spend compute so seniors don't
spend time debugging obvious issues.
