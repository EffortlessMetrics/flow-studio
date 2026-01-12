# Incident Response Protocol

**"When things go wrong, fix forward with evidence."**

Incidents are inevitable. This protocol ensures they are handled consistently, documented thoroughly, and learned from systematically.

## Severity Levels

| Severity | Description | Response Time | Examples |
|----------|-------------|---------------|----------|
| **SEV1** | Production down, data loss, security breach | Immediate | Secrets leaked, upstream corrupted, service outage |
| **SEV2** | Degraded service, blocked deployments | Same-day | CI pipeline broken, deploys failing, major feature broken |
| **SEV3** | Bug affecting users, failed runs | Next business day | Flow failures, incorrect outputs, flaky tests |
| **SEV4** | Minor issue, cosmetic | Normal backlog | Typos, minor UI issues, non-blocking warnings |

### Severity Decision Tree

```
Is production affected?
├── Yes → Is data lost or security compromised?
│         ├── Yes → SEV1
│         └── No → SEV2
└── No → Are users blocked?
          ├── Yes → SEV2
          └── No → Is it affecting correctness?
                    ├── Yes → SEV3
                    └── No → SEV4
```

## Response Protocol

### 1. Detect

How was the incident discovered?

| Detection Source | Action |
|------------------|--------|
| Monitoring alert | Acknowledge alert, check dashboard |
| User report | Confirm reproduction, gather details |
| Failed run | Check receipts, identify failing step |
| Audit discovery | Document finding, assess scope |
| Routine check | Escalate based on severity |

**Capture immediately:**
- Timestamp of discovery
- Who/what detected it
- Initial symptoms observed

### 2. Contain

Stop the bleeding. Prioritize containment over diagnosis.

| Incident Type | Containment Action |
|---------------|-------------------|
| Security breach | Revoke credentials, isolate affected systems |
| Production down | Revert to last known good, enable maintenance mode |
| Blocked deployments | Pause pipeline, notify stakeholders |
| Failed runs | Mark run as failed, prevent downstream effects |
| Data corruption | Stop writes, snapshot current state |

**Containment checklist:**
- [ ] Immediate harm stopped
- [ ] Scope of impact identified
- [ ] Stakeholders notified (SEV1/SEV2)
- [ ] Containment action documented

### 3. Diagnose

What went wrong? Follow the evidence.

**Evidence sources (priority order):**
1. **Physics**: Exit codes, file states, git status
2. **Receipts**: Step receipts, command outputs, logs
3. **Artifacts**: Generated files, diffs, handoff envelopes
4. **Narrative**: Agent claims, user reports

**Diagnosis steps:**
```
1. Identify the failing component
   └── Which flow? Which step? Which agent?

2. Check the evidence trail
   └── Receipt exists? Status? Evidence fresh?

3. Reproduce if possible
   └── Same inputs → same failure?

4. Trace backward
   └── What was the last successful state?

5. Identify root cause
   └── Not just proximate cause
```

### 4. Fix

Implement the solution. Prefer reversible fixes.

| Fix Type | When to Use |
|----------|-------------|
| **Revert** | Known-good state exists, low risk |
| **Hotfix** | Small, targeted fix, urgent |
| **Full fix** | Root cause addressed, time available |
| **Workaround** | Temporary mitigation, buy time |

**Fix requirements:**
- [ ] Fix addresses root cause (or documents why not)
- [ ] Fix is tested before deployment
- [ ] Rollback plan exists
- [ ] Change is documented

### 5. Verify

Confirm the fix works. Trust physics, not narrative.

**Verification checklist:**
- [ ] Original failure no longer reproduces
- [ ] Related functionality still works
- [ ] Evidence shows fix is effective
- [ ] No new issues introduced

**For Flow Studio runs:**
```bash
# Re-run the failing flow
make stepwise-<flow> RUN_ID=<new-run-id>

# Verify receipt shows success
cat RUN_BASE/<flow>/receipts/<step>-<agent>.json

# Check evidence panel
# All metrics should agree
```

### 6. Document

Create the post-mortem. This is mandatory for SEV1/SEV2.

## Incident Capture Template

During the incident, capture:

```markdown
## Incident Timeline

| Time | Event | Evidence |
|------|-------|----------|
| HH:MM | Incident detected | <how> |
| HH:MM | Containment started | <action> |
| HH:MM | Root cause identified | <finding> |
| HH:MM | Fix deployed | <change> |
| HH:MM | Verification complete | <evidence> |

## Commands Run

```bash
# Include actual commands and their output
command_1
# output...

command_2
# output...
```

## Decisions Made

| Decision | Rationale | Alternative Considered |
|----------|-----------|------------------------|
| ... | ... | ... |

## Who Was Involved

| Role | Person | Contribution |
|------|--------|--------------|
| Incident Commander | ... | ... |
| Technical Lead | ... | ... |
| ... | ... | ... |
```

## Post-Mortem Requirements

### Mandatory Elements

1. **Summary**: One paragraph describing what happened
2. **Impact**: Who was affected, for how long, what was the scope
3. **Timeline**: Chronological events with timestamps
4. **Root Cause**: Not proximate cause, but underlying issue
5. **Contributing Factors**: What made this possible
6. **Action Items**: Specific, owned, with deadlines
7. **Prevention Measures**: How to prevent recurrence

### The Blameless Rule

> Focus on systems, not people.
> "The deploy script failed" not "John broke the deploy"
> "The validation didn't catch this" not "Nobody reviewed properly"

**Questions to ask:**
- What system allowed this to happen?
- What signal was missed?
- What would have prevented this?
- What would have detected this earlier?

**Questions to avoid:**
- Who made the mistake?
- Why didn't someone catch this?
- Whose fault is this?

### Root Cause Analysis

Find the root cause, not just the proximate cause.

| Level | Example |
|-------|---------|
| **Symptom** | Tests failed in CI |
| **Proximate cause** | Test file was missing import |
| **Contributing factor** | No import validation in pre-commit |
| **Root cause** | New dependency added without updating test fixtures |
| **Systemic issue** | Dependency changes don't trigger test fixture review |

Use the "5 Whys" technique:
1. Why did tests fail? → Missing import
2. Why was import missing? → New dependency not in test requirements
3. Why wasn't it in test requirements? → Added to main but not test
4. Why wasn't this caught? → No pre-commit check for import consistency
5. Why no pre-commit check? → Import validation not part of standard checks

**Root cause:** Import validation missing from pre-commit hooks.

## Flow Studio Specific Incidents

### Failed Run

```
1. Check receipt for failing step
   → RUN_BASE/<flow>/receipts/<step>-<agent>.json

2. Check status field
   → "succeeded" | "failed" | "interrupted"

3. If failed, check error field
   → Error message and stack trace

4. Check transcript for context
   → RUN_BASE/<flow>/llm/<step>-<agent>-<engine>.jsonl

5. Check handoff envelope
   → RUN_BASE/<flow>/handoffs/<step>-<agent>.json
   → Look at concerns[] and routing.reason
```

### Stuck Run

```
1. Identify the stuck step
   → Which step has no receipt or incomplete receipt?

2. Check for BLOCKED status
   → RUN_BASE/<flow>/handoffs/*.json
   → Look for "status": "BLOCKED"

3. Check for missing inputs
   → Does previous step's output exist?
   → Are required artifacts present?

4. Check routing decisions
   → RUN_BASE/<flow>/routing/decisions.jsonl
   → Was there an ESCALATE that wasn't handled?

5. Check iteration limits
   → Microloop at max iterations?
   → Same failure signature repeated?
```

### Wrong Output

```
1. Check evidence panel
   → Do all metrics agree?
   → Any "not measured" that should have been measured?

2. Verify inputs were correct
   → Check previous flow outputs
   → Check teaching notes loaded correctly

3. Check scent trail
   → RUN_BASE/<flow>/scent_trail.json
   → Were prior decisions correct?

4. Check assumptions
   → Handoff envelope assumptions[] field
   → Were assumptions valid?

5. Compare to spec
   → Does output match requirements?
   → Were requirements correctly interpreted?
```

### Security Incident

```
1. IMMEDIATE: Revoke any exposed credentials
   → Rotate API keys, tokens, passwords

2. Assess scope
   → What was exposed?
   → For how long?
   → Who had access?

3. Check boundary logs
   → Did secrets scan run?
   → What slipped through?

4. Audit recent publishes
   → git log of upstream pushes
   → Any suspicious commits?

5. Notify stakeholders
   → Security team
   → Affected users
   → Legal if required
```

## Action Item Template

Every action item must have:

```markdown
- [ ] **Action**: <specific action to take>
  - **Owner**: <person responsible>
  - **Deadline**: <date>
  - **Verification**: <how we know it's done>
  - **Status**: pending | in-progress | complete
```

## The Rule

> Detect fast. Contain immediately. Diagnose thoroughly.
> Fix with evidence. Verify with physics. Document for learning.
> Blame systems, not people. Prevent recurrence, not just repeat.

---

## See Also
- [boundary-automation.md](./boundary-automation.md) - Publish gate enforcement
- [git-safety.md](./git-safety.md) - Git operations safety
- [sandbox-and-permissions.md](./sandbox-and-permissions.md) - Containment model
- [../governance/evidence-discipline.md](../governance/evidence-discipline.md) - Evidence requirements
- [../governance/truth-hierarchy.md](../governance/truth-hierarchy.md) - Evidence levels
