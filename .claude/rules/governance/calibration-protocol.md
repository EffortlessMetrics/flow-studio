# Calibration Protocol: Continuous Improvement

The system should be smarter on Friday than Monday. Automatically.

## The Learning Loop

```
       Runs
        │
        ▼
┌───────────────────┐
│  Flow 7 (Wisdom)  │
│  Extract Signals  │
└─────────┬─────────┘
          │
          ▼
┌───────────────────┐
│  Pattern Detection │
│  (3+ = pattern)   │
└─────────┬─────────┘
          │
          ▼
┌───────────────────┐
│  Propose Change   │
│  (prompt/flow/    │
│   agent)          │
└─────────┬─────────┘
          │
          ▼
┌───────────────────┐
│  Test Against     │
│  Historical Runs  │
└─────────┬─────────┘
          │
          ▼
┌───────────────────┐
│  Deploy with      │
│  Monitoring       │
└───────────────────┘
```

## Feedback Loops

### Flow 7 (Wisdom) Responsibilities

Flow 7 closes the learning loop by analyzing completed runs:

| Input | Analysis | Output |
|-------|----------|--------|
| Completed runs | What worked, what didn't | Learnings summary |
| Failure patterns | Root cause clustering | Prompt improvement proposals |
| Recurring detours | Pattern frequency | Flow modification proposals |
| Escaped bugs | Where verification failed | Gap analysis |

### Failure Patterns → Prompt Improvements

When the same failure occurs 3+ times:

```json
{
  "pattern_id": "missing-error-handling",
  "occurrences": [
    { "run_id": "run-001", "step": "build-step-3", "description": "No try/catch" },
    { "run_id": "run-005", "step": "build-step-3", "description": "Missing error boundary" },
    { "run_id": "run-008", "step": "build-step-3", "description": "Unhandled exception" }
  ],
  "root_cause": "code-implementer prompt lacks explicit error handling requirement",
  "proposed_fix": {
    "type": "prompt_update",
    "target": "code-implementer",
    "change": "Add explicit requirement: 'All functions that can fail MUST have error handling'"
  }
}
```

### Recurring Detours → Flow Modifications

When the same detour fires frequently:

```json
{
  "pattern_id": "frequent-lint-detour",
  "detour_type": "lint-fix",
  "frequency": "15 of last 20 runs",
  "proposal": {
    "type": "flow_modification",
    "change": "Add lint-check step before code-critic",
    "rationale": "Pre-emptive linting reduces 75% of detours"
  }
}
```

### Escaped Bugs → Verification Gaps

When bugs reach production:

```json
{
  "escaped_bug": {
    "description": "Null reference in user lookup",
    "detected_at": "production",
    "should_have_caught": "gate"
  },
  "gap_analysis": {
    "tests": "No null case in test suite",
    "coverage": "Line covered but branch not tested",
    "recommendation": "Add branch coverage requirement to gate"
  }
}
```

## Calibration Signals

### Primary Metrics

Track these signals to calibrate system performance:

| Signal | What It Measures | Target |
|--------|------------------|--------|
| **Detour rate by flow** | How often flows go off-road | < 20% |
| **Human intervention rate** | How often humans must intervene | < 5% |
| **Average run cost** | Compute spend per completed run | Trend down |
| **Time to merged PR** | Signal → approved merge | Trend down |

### Secondary Metrics

| Signal | What It Reveals |
|--------|-----------------|
| Runs requiring human intervention | What the system can't handle |
| Detour frequency by type | What keeps breaking |
| Time to approval | Where humans spend review time |
| Gate false positives | Unnecessary bounces |
| Gate false negatives | Escaped issues |

### Signal Collection

Signals are collected in:
```
swarm/calibration/
├── signals.jsonl           # Append-only signal log
├── patterns.json           # Detected patterns (3+ occurrences)
├── proposals/              # Change proposals
│   ├── prompt-001.json
│   └── flow-002.json
└── experiments/            # A/B test results
    └── exp-001.json
```

## Pattern Detection

### The 3+ Rule

A pattern exists when:
- Same failure type occurs 3+ times
- Same detour fires 3+ times
- Same human intervention type 3+ times

Below 3 occurrences: noise.
At 3+ occurrences: pattern requiring action.

### Pattern Schema

```json
{
  "pattern_id": "string",
  "type": "failure | detour | intervention | escape",
  "occurrences": [
    {
      "run_id": "string",
      "timestamp": "ISO8601",
      "details": {}
    }
  ],
  "first_seen": "ISO8601",
  "last_seen": "ISO8601",
  "count": "number",
  "status": "new | proposed | testing | deployed | rejected"
}
```

## Improvement Process

### 1. Collect Signals

Flow 7 extracts signals from every completed run:
- What detours fired?
- What human interventions occurred?
- What escaped to gate or beyond?
- What took longer than expected?

### 2. Identify Patterns

Weekly (or continuous) pattern detection:
- Group by failure type
- Count occurrences
- Promote to pattern at 3+

### 3. Propose Change

For each pattern, propose ONE of:

| Change Type | When to Use | Example |
|-------------|-------------|---------|
| **Prompt update** | Agent behavior needs adjustment | Add requirement to teaching notes |
| **Flow modification** | Step sequence needs change | Add pre-emptive step |
| **Agent addition** | New capability needed | Add specialized fixer agent |
| **Detour addition** | New known fix pattern | Add to detour catalog |

### 4. Test Against Historical Runs

Before deploying:
- Replay affected runs with proposed change
- Compare outcomes (success rate, detour rate, cost)
- Require improvement on target metric

```json
{
  "experiment_id": "exp-001",
  "change": "prompt-001",
  "baseline_runs": ["run-001", "run-005", "run-008"],
  "baseline_outcomes": {
    "success_rate": 0.33,
    "detour_rate": 0.67
  },
  "experiment_outcomes": {
    "success_rate": 0.67,
    "detour_rate": 0.33
  },
  "improvement": {
    "success_rate": "+34%",
    "detour_rate": "-34%"
  },
  "recommendation": "deploy"
}
```

### 5. Deploy with Monitoring

After deployment:
- Monitor target metric for 1 week
- Compare to pre-change baseline
- Rollback if regression detected

## What to Track

### Dashboard Metrics

| Metric | Calculation | Review Frequency |
|--------|-------------|------------------|
| Detour rate by flow | detours / total_steps | Weekly |
| Human intervention rate | interventions / total_runs | Weekly |
| Average run cost | total_cost / completed_runs | Weekly |
| Time to merged PR | merged_at - signal_at | Per run |
| Pattern detection rate | patterns_found / week | Weekly |
| Change success rate | successful_changes / proposed | Monthly |

### Trend Analysis

Track week-over-week:
- Is detour rate decreasing?
- Is human intervention rate decreasing?
- Is run cost stable or decreasing?
- Is time to merge stable or decreasing?

Regression on any metric triggers investigation.

## Anti-Patterns

### Changing Prompts Without Evidence

**Wrong:**
```
"I think the code-implementer should be more careful about error handling"
→ Update prompt
```

**Right:**
```
"Pattern detected: 5 runs failed due to missing error handling"
→ Propose change
→ Test against historical runs
→ Deploy if improvement confirmed
```

### Optimizing for Speed Over Trust

**Wrong:**
```
"Runs take too long, let's skip the critic step"
```

**Right:**
```
"Runs take too long. Where is time spent?"
→ Analyze step durations
→ Identify bottleneck
→ Optimize bottleneck without reducing verification
```

### Ignoring Recurring Failures

**Wrong:**
```
"That detour fires a lot, but it works"
```

**Right:**
```
"That detour fires 15/20 runs"
→ Pattern detected
→ Propose pre-emptive fix
→ Reduce detour rate
```

### Over-Fitting to Recent Failures

**Wrong:**
```
"Last run had a weird edge case, add handling for it"
```

**Right:**
```
"Wait for 3+ occurrences before treating as pattern"
→ Single occurrence = noise
→ 3+ occurrences = signal
```

## The Rule

> Changes require evidence. Patterns require 3+ occurrences.
> Test before deploy. Monitor after deploy.
> The system learns from runs, not from opinions.

## Calibration Cadence

| Activity | Frequency | Owner |
|----------|-----------|-------|
| Signal collection | Per run | Flow 7 |
| Pattern detection | Weekly | Wisdom analysis |
| Change proposal | When pattern detected | Flow 7 |
| Historical testing | Before deploy | Automated |
| Deployment | After test passes | Human approval |
| Monitoring | 1 week post-deploy | Automated |
| Trend review | Weekly | Human |

## The Economics

Calibration is an investment:
- **Cost:** Analysis compute, historical replay, monitoring
- **Return:** Reduced detour rate, reduced intervention, lower run cost

Break-even typically occurs when:
- A single prevented human intervention saves 30+ minutes
- A single prevented detour saves ~$0.50 in compute
- Pattern-based improvements compound over runs

## Current Implementation Status

| Component | Status | Location |
|-----------|--------|----------|
| Signal collection | Designed | This spec |
| Pattern detection | Designed | This spec |
| Change proposals | Designed | This spec |
| Historical replay | Aspirational | Not implemented |
| Monitoring | Aspirational | Not implemented |

---

## See Also
- [flow-charters.md](./flow-charters.md) - Flow 7 (Wisdom) charter
- [evidence-discipline.md](./evidence-discipline.md) - What counts as evidence
- [detour-catalog.md](../execution/detour-catalog.md) - Known fix patterns
- [off-road-logging.md](../artifacts/off-road-logging.md) - Routing decision audit trail
