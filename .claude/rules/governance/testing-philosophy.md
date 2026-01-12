# Testing Philosophy

**"Tests are evidence, not ceremony."**

"Tests pass" without proof of effectiveness is narrative, not physics.

## The Core Principle

A test is evidence only if it would **fail when the requirement isn't met**.

If you can't point to a test that would fail if the requirement wasn't met, the requirement isn't tested.

## What Makes Tests Trustworthy

### Mutation Testing

Tests that don't catch mutations are hollow.

| Mutation | Test Response | Meaning |
|----------|---------------|---------|
| Delete a line | Test fails | Test catches the behavior |
| Change `>` to `>=` | Test fails | Test catches boundary |
| Flip boolean | Test fails | Test catches logic |
| Return null | Test fails | Test catches error path |
| Any mutation | Test passes | **Test is hollow** |

**The rule**: If mutants survive, tests don't actually verify behavior.

### Coverage with Assertions

Executed code is not tested code.

```python
# BAD: Coverage without assertion
def test_process_order():
    order = create_order()
    process_order(order)  # Executes 100 lines
    # No assertion - what did we verify?

# GOOD: Coverage with assertion
def test_process_order():
    order = create_order()
    result = process_order(order)
    assert result.status == "completed"
    assert result.total == 150.00
    assert len(result.line_items) == 3
```

**The rule**: Every executed path needs an assertion that would fail if behavior changed.

### Failure Modes Tested

Happy path coverage is not coverage.

| Test Type | What It Proves |
|-----------|---------------|
| Happy path only | Code works when everything's right |
| Edge cases | Code handles boundaries |
| Error paths | Code fails gracefully |
| Concurrent cases | Code handles race conditions |

**The rule**: If you only test success, you don't know what failure looks like.

### BDD Scenarios as Test Cases

Specifications should trace directly to tests.

```gherkin
# Spec
Scenario: User cannot withdraw more than balance
  Given a user with balance $100
  When they attempt to withdraw $150
  Then the withdrawal is rejected
  And the balance remains $100
```

```python
# Test that traces to spec
def test_overdraft_rejected():
    """Traces to: User cannot withdraw more than balance"""
    user = create_user(balance=100)
    result = user.withdraw(150)
    assert result.rejected
    assert user.balance == 100
```

**The rule**: Every BDD scenario has a corresponding test. Every test traces to a requirement.

## Verification Escalation

When in doubt, add tests. Never add manual review.

| Signal | Response |
|--------|----------|
| "I think it works" | Add test that proves it |
| "Edge case might fail" | Add test for that edge case |
| "Not sure about concurrent access" | Add concurrency test |
| "Reviewer should check" | Wrong. Add test. |

### Escalation Ladder

1. **Unit tests** - Fast, isolated, deterministic
2. **Integration tests** - Boundary verification
3. **Mutation testing** - Test effectiveness
4. **Fuzz testing** - Edge case discovery
5. **Property-based testing** - Invariant verification

**The rule**: Doubt escalates to tests, not to humans.

## Quality Signals

### Mutation Score

Mutation score measures test effectiveness:

| Score | Meaning | Action |
|-------|---------|--------|
| 90%+ | Tests catch most changes | Good coverage |
| 70-90% | Some blind spots | Review surviving mutants |
| < 70% | Tests are weak | Major test gaps |

### Assertion Density

Assertions per test indicate thoroughness:

| Density | Meaning |
|---------|---------|
| 0 assertions | Hollow test (not evidence) |
| 1 assertion | Minimal verification |
| 3-5 assertions | Thorough verification |
| 10+ assertions | Consider splitting test |

## Anti-Patterns

### Coverage Gaming

```python
# ANTI-PATTERN: Execute without assert
def test_all_paths():
    for input in all_inputs:
        function(input)  # 100% coverage, 0% verification
```

**Problem**: Counts as coverage but proves nothing.

### Trivial Tests

```python
# ANTI-PATTERN: Testing language features
def test_getter():
    user = User(name="Alice")
    assert user.name == "Alice"  # Tests Python, not your code
```

**Problem**: Passes regardless of business logic correctness.

### Flaky Tests

```python
# ANTI-PATTERN: Non-deterministic test
def test_timing():
    start = time.time()
    slow_operation()
    assert time.time() - start < 1.0  # Fails randomly
```

**Problem**: Non-deterministic tests are not evidence. They're noise.

### Test Rot

```python
# ANTI-PATTERN: Test passes but doesn't reflect behavior
def test_old_behavior():
    # This test was written for v1
    # Code is now v3
    # Test still passes but tests nothing relevant
    assert True
```

**Problem**: Tests that pass regardless of current behavior are false confidence.

## The Test Evidence Panel

Never evaluate test quality on a single metric:

| Metric | Purpose | Gaming Risk |
|--------|---------|-------------|
| Pass rate | Basic correctness | Trivial tests |
| Line coverage | Code exercised | Coverage without assertion |
| Branch coverage | Paths exercised | Same as above |
| Mutation score | Test effectiveness | Computationally expensive |
| Assertion count | Verification depth | Verbose tests |

**Panel insight**: High coverage + low mutation score = hollow tests

## Evidence in Receipts

Test results in receipts must include:

```json
{
  "tests": {
    "measured": true,
    "passed": 42,
    "failed": 0,
    "skipped": 2,
    "evidence": "RUN_BASE/build/test_output.log"
  },
  "coverage": {
    "measured": true,
    "line_percent": 87,
    "branch_percent": 72,
    "evidence": "RUN_BASE/build/coverage.json"
  },
  "mutation": {
    "measured": true,
    "score_percent": 78,
    "mutants_killed": 156,
    "mutants_survived": 44,
    "evidence": "RUN_BASE/build/mutation_report.html"
  }
}
```

If mutation testing wasn't run, say so:

```json
{
  "mutation": {
    "measured": false,
    "reason": "Mutation testing not configured for this project"
  }
}
```

## The Rule

> Tests are evidence only when they would fail if requirements aren't met.
> "Tests pass" means nothing without mutation score, assertion density, and failure mode coverage.
> When in doubt, write more tests. Never defer to manual review.

---

## See Also
- [evidence-discipline.md](./evidence-discipline.md) - What counts as evidence
- [panel-thinking.md](./panel-thinking.md) - Multi-metric evaluation
- [truth-hierarchy.md](./truth-hierarchy.md) - Evidence levels
