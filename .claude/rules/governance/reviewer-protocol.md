# Reviewer Protocol

How humans review AI-generated work. This is the new skill that replaces line-by-line code review.

## The Shift

**Old review:** Read every line, understand the logic, approve if it looks correct.
**New review:** Verify evidence exists, check panel agreement, escalate verification where doubt exists.

The system did the grinding. You do the judgment.

## The Three Questions

Every reviewer should be able to answer these in under 5 minutes:

### 1. Does evidence exist and is it fresh?

Check:
- [ ] Receipts exist for each step
- [ ] Receipts are from this commit (not stale)
- [ ] Test output was captured (not just claimed)
- [ ] Coverage numbers are present
- [ ] Lint/security scans ran

**Red flag:** "Tests passed" without captured output. That's narrative, not evidence.

### 2. Does the panel of metrics agree?

Check:
- [ ] Tests pass AND coverage is reasonable
- [ ] Lint clean AND no new complexity warnings
- [ ] Security scan clean AND no new dependencies with issues
- [ ] All metrics point the same direction

**Red flag:** High coverage but tests are trivial (mutation score would catch this).
**Red flag:** Tests pass but lint has errors (rushed work).
**Red flag:** Any metric that's "not measured" without explanation.

### 3. Where would I escalate verification?

If doubt exists, the answer is *more verification*, not manual inspection. The hotspots list guides where to deepen:

- [ ] Hotspots list exists
- [ ] Hotspots make sense (high-change or high-risk areas)
- [ ] For doubt areas: escalate verification (mutation testing, fuzz testing, targeted integration tests)
- [ ] If escalation is impractical, document the risk surface

**Red flag:** No hotspots list (system didn't identify risk areas).
**Red flag:** Hotspots are all trivial files (risk assessment failed).

**The posture:** You don't read code to verify it. You audit evidence. When evidence is insufficient, you request *more evidence*, not manual review.

## Decision Matrix

| Evidence | Panel | Escalation Need | Decision |
|----------|-------|-----------------|----------|
| Fresh, complete | Agrees | None | **Approve** |
| Fresh, complete | Agrees | Doubt in area | Escalate verification there |
| Fresh, complete | Contradicts | - | Investigate contradictions |
| Stale or missing | - | - | **Request new run** |
| Complete | "Not measured" | - | Evaluate what's missing, escalate or accept risk |

## What You're NOT Doing

### Not reading every line
The system generated potentially thousands of lines. You cannot review them all. That's the old model.

### Not understanding all implementation details
You understand the *behavior* from evidence. Implementation details are the machine's job.

### Not trusting agent claims
"I implemented the feature" means nothing. Show me the receipt.

### Not approving based on vibes
"Looks good" is not a review. Evidence agreement is a review.

## The 90-Second Protocol

For low-risk changes:

1. **30 sec:** Evidence exists? Fresh?
2. **30 sec:** Panel metrics agree?
3. **30 sec:** Scan hotspots list—any need escalation?

If all green, approve. You've verified more than most line-by-line reviews catch.

## The 10-Minute Protocol

For high-risk changes:

1. **2 min:** Full evidence inventory. What's measured? What's not?
2. **3 min:** Panel deep-dive. Any contradictions? Any warnings?
3. **5 min:** Hotspot triage—which areas need deeper verification? Request targeted tests or scans for doubt areas.

Document any concerns. If concerns are addressed or verification escalated, approve.

## Trust Calibration

Periodically verify that your trust is calibrated:

- **Seeded failures:** Occasionally have the system introduce a known bug. Did escalation catch it?
- **Verification depth:** For random runs, request full verification (mutation, fuzz, integration). Did evidence match reality?
- **Panel accuracy:** When bugs escape, were they in areas marked "not measured" or where verification wasn't escalated?

Trust but verify. Then verify your verification.

## The Psychology

### Pride moves from "I found the bug" to "I verified the evidence"
The old pride: catching subtle bugs in code review.
The new pride: maintaining a verification system that catches bugs automatically.

### "I didn't read the code" is not shameful
It's efficient. You reviewed the evidence that proves the code works. That's better than reading code and hoping.

### Skepticism is correct
Don't trust agents. Don't trust claims. Trust physics (exit codes), trust receipts (captured output), trust panels (multi-metric agreement).

## Remember

The question is not "is this good code?"

The question is "does the evidence prove this code does what it should?"

If yes, approve. The system did the work. You verified the receipts.
