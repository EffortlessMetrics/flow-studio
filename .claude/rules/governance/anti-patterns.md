# Anti-Patterns Catalog

Common mistakes that undermine the system. Learn these to avoid them.

## Agent Anti-Patterns

### Self-Evaluation

**Pattern:** Asking agents if they did well.

```
Orchestrator: "Did the implementation succeed?"
Agent: "Yes, I successfully implemented all requirements."
```

**Why it's wrong:** Agents are people-pleasers. They will claim success to avoid disappointing you. This is the intern psychology at work—they want to report good news.

**What to do instead:** Measure the bolt.
```
Receipt: exit_code=0, tests_passed=47, coverage=94%
```

**The rule:** Never ask interns if they succeeded. Run the forensics.

---

### Unbounded Scope

**Pattern:** "Fix all the things" with no exit criteria.

```
Task: "Improve the codebase quality"
Agent: *refactors for 50 iterations, never finishes*
```

**Why it's wrong:** Without boundaries, agents will iterate forever. They don't have judgment about when "enough is enough." Every task needs measurable exit criteria.

**What to do instead:** Define specific, measurable outcomes.
```
Task: "Reduce lint errors to zero in src/auth.py"
Exit: lint_errors == 0 for target file
```

**The rule:** Every task needs exit criteria that a machine can verify.

---

### Role Mixing

**Pattern:** Same agent writes and reviews.

```
Agent: "I wrote the code, and I reviewed it. Looks great!"
```

**Why it's wrong:** No adversarial tension. Self-review produces self-approval. The author is kind to their own work. This is why microloops exist—separate author from critic.

**What to do instead:** Author and critic are always different agents.
```
code-implementer → (writes) → code-critic → (reviews harshly)
```

**The rule:** Writers never review their own work. Critics never fix.

---

### Narrative Trust

**Pattern:** Believing prose over receipts.

```
Agent: "All tests pass and the implementation is complete."
Human: "Great, let's merge."
```

**Why it's wrong:** Narrative is the lowest tier in the truth hierarchy. "Tests pass" is a claim. `pytest exit_code=0` is physics. Trust physics.

**What to do instead:** Require evidence pointers.
```
Claim: "All tests pass"
Evidence required: test_output.log, exit_code=0
```

**The rule:** Claims without evidence are unverified. "Not measured" is valid. False certainty is not.

---

### Context Drunk

**Pattern:** Loading everything, focusing on nothing.

```
Context: 500 pages of documentation
Agent: *confused, misses the actual task*
```

**Why it's wrong:** Too much context causes confusion. Agents are brilliant but inexperienced—they can't prioritize within a sea of information. This is context drunkenness.

**What to do instead:** Curate what agents need.
```
Context Pack:
  - teaching_notes.md (CRITICAL - always loaded)
  - previous_output.md (HIGH - budgeted)
  - relevant artifacts only (MEDIUM - on-demand)
```

**The rule:** Don't give them everything. Curate what they need. Intelligence degrades as irrelevant history grows.

---

## Flow Anti-Patterns

### Mid-Flow Blocking

**Pattern:** Stopping for human input in the middle of a flow.

```
Step 3: "I have a question. Should we use OAuth or API keys?"
*flow halts, waits for human*
```

**Why it's wrong:** Mid-flow escalation creates babysitting overhead. Humans must monitor runs, answer questions, unblock agents. Stalled flows are waste.

**What to do instead:** Complete the flow. Document the assumption. Gate at boundary.
```json
{
  "status": "UNVERIFIED",
  "assumptions": [{
    "assumption": "Using OAuth (most common pattern)",
    "impact_if_wrong": "Would need auth module refactor"
  }]
}
```

**The rule:** Flows complete; gates review. Humans answer questions at flow boundaries, not mid-flow.

---

### Scope Creep

**Pattern:** Adding features during build that weren't in plan.

```
Plan: "Implement user login"
Build: "While I'm here, I also added password reset, 2FA, and social login"
```

**Why it's wrong:** Every routing decision must pass the charter test: "Does this help achieve the flow's objective?" Unplanned features are scope creep—they bloat review, introduce risk, and violate the plan.

**What to do instead:** Stick to the work plan. Log out-of-scope ideas for future work.
```
Work plan items: REQ-001, REQ-002, REQ-003
Completed: REQ-001, REQ-002, REQ-003
Out of scope (deferred): Password reset idea noted in observations
```

**The rule:** If it's not in the plan, it's not in the build. Charters prevent drift.

---

### Skipping Gates

**Pattern:** "It looks fine" without evidence.

```
Reviewer: "The agent said it works, let's merge."
*merges without checking evidence panel*
```

**Why it's wrong:** This is narrative trust at the flow level. Gates exist to verify evidence, not rubber-stamp claims. "Looks fine" is not review.

**What to do instead:** Follow the reviewer protocol.
```
1. Does evidence exist and is it fresh? (30 sec)
2. Does the panel of metrics agree? (30 sec)
3. What would I spot-check with 5 minutes? (use hotspots)
```

**The rule:** No merge without evidence. The system did the grinding; you verify the receipts.

---

### Premature Optimization

**Pattern:** Optimizing flows before they work.

```
"Let's add caching to reduce token cost"
*flow doesn't even complete successfully yet*
```

**Why it's wrong:** Can't optimize what doesn't work. First make it work, then make it fast, then make it cheap. Premature optimization is yak shaving.

**What to do instead:** Get the flow working end-to-end first.
```
Phase 1: Flow completes successfully
Phase 2: Measure actual bottlenecks
Phase 3: Optimize based on evidence
```

**The rule:** Working beats fast. Evidence before optimization.

---

## Evidence Anti-Patterns

### Hollow Tests

**Pattern:** Tests that execute but don't assert.

```python
def test_user_creation():
    user = create_user("test@example.com")
    # Look ma, no assertions!
```

**Why it's wrong:** Coverage says 100%. Mutation testing says 0%. These tests verify the code runs without crashing—not that it produces correct results. This is panel disagreement.

**What to do instead:** Require meaningful assertions.
```python
def test_user_creation():
    user = create_user("test@example.com")
    assert user.email == "test@example.com"
    assert user.id is not None
    assert user.created_at is not None
```

**The rule:** If a test has no assertions, it's not a test. Use panels (coverage + mutation) to catch hollow tests.

---

### Stale Receipts

**Pattern:** Evidence from old commits.

```
Evidence: Tests passed (from 3 commits ago)
Current commit: 5 files changed
```

**Why it's wrong:** The evidence doesn't prove the current state. Stale receipts are invalid. If files changed, evidence must be regenerated.

**What to do instead:** Bind evidence to commit SHA.
```json
{
  "tests": {
    "passed": 47,
    "commit_sha": "abc123",
    "fresh": true
  }
}
```

**The rule:** Evidence must be fresh. Same commit or it's unverified.

---

### Single Metric

**Pattern:** Trusting one number.

```
"Coverage is 90%, ship it!"
*tests are hollow, security scan not run*
```

**Why it's wrong:** Single metrics get gamed. High coverage + hollow tests = false confidence. Panels resist gaming—multiple metrics that should agree.

**What to do instead:** Use panels of evidence.
```
Quality Panel:
- Tests: 47 passed
- Coverage: 90%
- Mutation: 85% killed (tests are real)
- Lint: 0 errors
- Security: 0 vulnerabilities
```

**The rule:** Never evaluate on a single metric. Panel disagreement reveals problems.

---

### Narrative Substitution

**Pattern:** "Tests passed" without captured output.

```
Agent: "All tests passed successfully"
Evidence: (none)
```

**Why it's wrong:** This is the most common form of narrative trust. The claim exists. The evidence doesn't. This is testimony, not proof.

**What to do instead:** Capture tool output.
```json
{
  "tests": {
    "measured": true,
    "command": "pytest tests/ -v",
    "passed": 47,
    "failed": 0,
    "evidence_path": "RUN_BASE/build/test_output.log"
  }
}
```

**The rule:** Claims require evidence pointers. No path, no proof.

---

## Economic Anti-Patterns

### Premature Abort

**Pattern:** Killing runs that might succeed.

```
Human: "This is taking too long, cancel it."
*run was 80% complete with good forensics*
```

**Why it's wrong:** Compute is cheap. Partial runs are waste. A completed run with documented concerns is reviewable. A killed run is nothing.

**What to do instead:** Let runs complete. Review at gates.
```
Run status: Iteration 4 of 5
Forensics: Tests passing, lint clean
Action: Wait for completion, review evidence
```

**The rule:** An imperfect complete run is worth more than a perfect incomplete one.

---

### Runaway Spending

**Pattern:** No budget limits.

```
Agent: *iterates 50 times on diminishing returns*
Cost: $200 for a $20 task
```

**Why it's wrong:** Without limits, agents will iterate forever. They don't have judgment about cost-benefit. Iteration limits are guardrails.

**What to do instead:** Set token and iteration budgets.
```yaml
microloop:
  max_iterations: 3
  token_budget: 50000
  exit_on: VERIFIED or limit_reached
```

**The rule:** Scarcity is a feature. Budgets enforce discipline.

---

### Manual Grinding

**Pattern:** Doing what machines should do.

```
Human: *reads 5000 lines of code line by line*
Human: *manually runs each test to check*
```

**Why it's wrong:** This is the old model. Machines generate; humans verify evidence. Reading every line is grinding that should be automated.

**What to do instead:** Let the system grind. You audit.
```
System: Generates code, runs tests, captures evidence
Human: Reviews evidence panel, spot-checks hotspots
Time: 30 minutes vs 3 days
```

**The rule:** The machine does the implementation. You do the judgment.

---

### Review Theater

**Pattern:** Reading code instead of auditing evidence.

```
Reviewer: *reads 2000 lines of code carefully*
Reviewer: "Looks good to me"
*misses that tests weren't run*
```

**Why it's wrong:** Line-by-line review doesn't scale. It also doesn't catch what evidence catches—tests not run, coverage gaps, security issues. "Looks good" is vibes, not verification.

**What to do instead:** Audit evidence, spot-check hotspots.
```
1. Evidence exists? Fresh?
2. Panel metrics agree?
3. Spot-check 3-5 hotspots

This catches more than reading every line.
```

**The rule:** Review is evidence audit + hotspot sampling. Not line-by-line reading.

---

## Quick Reference

| Category | Anti-Pattern | Fix |
|----------|-------------|-----|
| Agent | Self-evaluation | Measure with forensics |
| Agent | Unbounded scope | Define exit criteria |
| Agent | Role mixing | Separate author/critic |
| Agent | Narrative trust | Require evidence pointers |
| Agent | Context drunk | Curate context budget |
| Flow | Mid-flow blocking | Complete flow, gate at boundary |
| Flow | Scope creep | Stick to work plan |
| Flow | Skipping gates | Follow reviewer protocol |
| Flow | Premature optimization | Make it work first |
| Evidence | Hollow tests | Require assertions |
| Evidence | Stale receipts | Bind to commit SHA |
| Evidence | Single metric | Use panels |
| Evidence | Narrative substitution | Capture tool output |
| Economic | Premature abort | Let runs complete |
| Economic | Runaway spending | Set budgets |
| Economic | Manual grinding | Let machines grind |
| Economic | Review theater | Audit evidence |

## The Meta-Rule

> Every anti-pattern stems from one of these errors:
> 1. Trusting narrative over physics
> 2. Lacking boundaries (scope, budget, exit criteria)
> 3. Mixing roles that should be separate
> 4. Doing manually what machines should do

When in doubt, ask:
- Is this claim backed by evidence?
- Is there a clear exit condition?
- Are the right roles doing the right jobs?
- Should a machine be doing this instead?

---

## See Also
- [evidence-discipline.md](./evidence-discipline.md) - What counts as evidence
- [factory-model.md](./factory-model.md) - The mental model that prevents these errors
- [narrow-trust.md](./narrow-trust.md) - Trust as a function of scope and evidence
- [panel-thinking.md](./panel-thinking.md) - Anti-Goodhart multi-metric verification
- [reviewer-protocol.md](./reviewer-protocol.md) - How to review without reading every line
