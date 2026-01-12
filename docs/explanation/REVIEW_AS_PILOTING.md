# Review as Piloting: The New Review Skill

Traditional code review is diff-reading. In Flow Studio, review becomes **evidence piloting**—a fundamentally different skill.

## The Shift

| Traditional Review | Evidence Piloting |
|-------------------|-------------------|
| Read every line of the diff | Read the cockpit (PR description) |
| Judge code quality | Judge evidence quality |
| Proofreading | Sensor fusion |
| Completeness via coverage | Completeness via panel synthesis |
| Speed limited by diff size | Speed limited by evidence quality |

## What Reviewers Actually Do

### 1. Evidence Freshness Evaluation
- Are receipts from the current commit?
- Do timestamps align with claimed work?
- Is evidence stale or missing?

### 2. Panel Synthesis
Review multiple signals together:
- Test results (pass/fail/skip counts)
- Coverage metrics (if measured)
- Lint/security scan results
- Critic concerns and resolutions

Panel conflicts are red flags:
- "Tests pass" + "No test output" = investigate
- "High coverage" + "Low mutation score" = weak tests
- "Clean lint" + "No lint log" = unknown

### 3. Risk-Calibrated Verification Escalation
Not every change needs deep verification. Calibrate by:
- **Risk of change** - Auth code vs. logging code
- **Novelty** - New patterns vs. established patterns
- **Evidence quality** - Strong evidence = less escalation needed

When doubt exists, the answer is deeper verification (mutation testing, fuzz testing, targeted tests), not manual code reading.

### 4. Hotspot Navigation
Focus on high-risk areas:
- Security boundaries
- Data validation
- Error handling
- State mutations

Use evidence panel to identify where to look.

## The 90-Second / 10-Minute Protocol

### 90-Second Pass (Most PRs)
1. Read cockpit summary (30s)
2. Check evidence panel exists and is fresh (30s)
3. Verify panel is green or concerns are documented (30s)

If all pass → approve.

### 10-Minute Pass (Flagged PRs)
1. 90-second pass first
2. Read critic concerns in detail (2m)
3. Escalate verification on 2-3 hotspots: request targeted tests, mutation analysis, or adversarial probes (5m)
4. Verify evidence matches claims (2m)

If concerns remain → request deeper verification, not manual reading.

## What "Not Measured" Means

The system explicitly marks unmeasured things:

```json
{
  "security_scan": {
    "measured": false,
    "reason": "No security scanner configured"
  }
}
```

**"Not measured" is honest.** It means:
- We didn't check this
- You should decide if that matters
- It's not a claim of safety

**"Implied pass" is dangerous.** Absence of evidence ≠ evidence of absence.

## Panel Reading Skills

### Quality Panel
| Metric | Healthy | Investigate |
|--------|---------|-------------|
| Tests | Pass count > 0 | All skip, or no output |
| Coverage | Any % with log | % without log |
| Lint | 0 errors with log | Errors, or no log |
| Security | 0 vulns with log | Vulns, or no log |

### Velocity Panel (for leads)
| Metric | Healthy | Investigate |
|--------|---------|-------------|
| Cycle time | Consistent | Spikes |
| Revision count | 1-3 | 5+ |
| Evidence coverage | All panels filled | Gaps |

## Anti-Patterns

### Rubber-Stamping
Reading the cockpit without checking evidence freshness.
**Fix:** Always verify timestamp alignment.

### Diff Regression
Falling back to reading the whole diff "just in case."
**Fix:** Trust the panel; escalate verification on hotspots only.

### Panel Theater
Approving because panels are green without checking they're real.
**Fix:** Verify evidence paths resolve.

### Goodhart Optimization
System gaming the panel metrics.
**Fix:** Periodic verification escalation (mutation tests, seeded faults); canary failures.

## The New Skill Stack

Traditional reviewer skills:
- Code quality judgment
- Style consistency
- Logic verification

Evidence pilot skills:
- Panel interpretation
- Evidence provenance
- Risk calibration
- Sensor fusion
- "Not measured" interpretation

## Trust Refresh Ritual

To prevent rubber-stamping at scale:
- Every N PRs: escalated verification on hotspots (mutation tests, fuzz tests, adversarial probes)
- Every N PRs: seeded fault/canary to verify critics catch it
- Track panel drift vs incident rate

Not a gate. Not a ceremony. Just periodic recalibration through deeper verification, not manual reading.

---

## See Also
- [ATTENTION_ARBITRAGE.md](./ATTENTION_ARBITRAGE.md) - Why this matters economically
- [panel-thinking.md](../../.claude/rules/governance/panel-thinking.md) - Anti-Goodhart panels
- [evidence-discipline.md](../../.claude/rules/governance/evidence-discipline.md) - What counts as evidence
