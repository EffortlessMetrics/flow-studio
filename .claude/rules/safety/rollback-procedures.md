# Rollback Procedures: Undo When Things Go Wrong

**"Fast recovery beats perfect prevention."**

When something breaks in production, the priority is restoring service, not assigning blame. This rule defines how to roll back changes safely.

## Rollback Triggers

### When to Roll Back Immediately

| Trigger | Severity | Response Time |
|---------|----------|---------------|
| **Failed deployment** | CI red after merge | < 15 minutes |
| **Production incident** | SEV1 (service down) | < 5 minutes |
| **Production incident** | SEV2 (degraded) | < 30 minutes |
| **Security issue** | Exposed secrets | IMMEDIATE |
| **Security issue** | Vulnerability in prod | < 1 hour |
| **Bad merge** | Broke functionality | < 1 hour |

### How to Identify the Bad Change

```bash
# Find the merge commit
git log --oneline --merges -10

# Show what changed in a commit
git show <sha> --stat

# Find when a file was last modified
git log --oneline -5 -- path/to/broken/file

# Compare current state to known-good
git diff <known-good-sha> HEAD -- path/to/file
```

## Rollback Types

### 1. Git Revert (Preferred for Upstream)

Creates a new commit that undoes changes. **This is the preferred method for upstream/production.**

```bash
# Revert a single commit
git revert <sha>

# Revert a merge commit (specify which parent to keep)
git revert -m 1 <merge-sha>

# Revert multiple commits (oldest to newest)
git revert <oldest-sha>^..<newest-sha>

# Push the revert
git push origin main
```

**When to use:**
- Any rollback on upstream/main
- Shared branches
- When you want to preserve history

**Advantages:**
- Preserves full history
- Safe for shared branches
- Easy to "revert the revert" later
- Creates audit trail

### 2. Git Reset (Shadow Fork Only)

Rewrites history by moving HEAD backward. **ONLY use in the shadow fork, NEVER on upstream.**

```bash
# In shadow fork only:
git reset --hard <sha>
git push --force origin feature-branch
```

**When to use:**
- Inside the shadow fork during Flows 1-5
- Cleaning up messy work before publish

**BLOCKED on upstream:**
```bash
# NEVER do this to upstream:
git reset --hard <sha>
git push --force upstream main   # BLOCKED
```

### 3. Feature Disable (Fastest Response)

Keep the code deployed but disable at runtime. **Fastest way to stop the bleeding.**

```bash
# Via environment variable
export FEATURE_X_ENABLED=false

# Via config file
echo '{"feature_x": false}' > config/features.json

# Via feature flag service
curl -X POST https://flags.example.com/api/flags/feature_x/disable
```

**When to use:**
- Fastest possible response needed (SEV1)
- Code itself is fine, just behavior is wrong
- Need time to investigate root cause

**Requirements:**
- Feature must have been built with disable capability
- Config/flag must be external to the codebase

### 4. Data Rollback (Last Resort)

Restore from backup when data is corrupted. **Requires careful reconciliation.**

```bash
# Stop writes to affected tables
# (Application-specific commands)

# Restore from backup
pg_restore -d database backup_file.dump

# Or point-in-time recovery
pg_restore -d database --target-time="2024-01-15 10:00:00"
```

**When to use:**
- Data corruption
- Cascading deletes
- Schema migration failure

**CRITICAL:** Requires reconciliation of any data written between backup and now.

## Rollback Checklist

Execute in order. Do not skip steps.

### 1. Identify the Bad Change
```bash
# Find the commit SHA
git log --oneline -20
# Note: <bad-sha> = __________
```

### 2. Assess Blast Radius
- [ ] What systems are affected?
- [ ] Are other services dependent on this?
- [ ] Is data at risk?
- [ ] Who needs to be notified?

### 3. Choose Rollback Type

| Situation | Rollback Type |
|-----------|---------------|
| Code bug in production | Git Revert |
| Feature causing issues | Feature Disable |
| Security exposure | Git Revert + rotate secrets |
| Data corruption | Data Rollback |
| Shadow fork cleanup | Git Reset |

### 4. Execute Rollback

**For Git Revert:**
```bash
git fetch origin
git checkout main
git pull origin main
git revert <bad-sha>
git push origin main
```

**For Feature Disable:**
```bash
# Disable the feature via config/flags
# Verify feature is disabled
curl https://app.example.com/health | jq '.features.x'
```

### 5. Verify Rollback Succeeded
- [ ] CI is green
- [ ] Health checks pass
- [ ] Affected functionality works
- [ ] Error rates returned to baseline
- [ ] No new errors in logs

```bash
# Check CI status
gh run list --limit 5

# Check for errors
grep -i error /var/log/app/current.log | tail -20
```

### 6. Communicate Status
- [ ] Update incident channel
- [ ] Notify affected teams
- [ ] Update status page (if public-facing)

### 7. Post-Mortem
- [ ] Schedule post-mortem within 48 hours
- [ ] Document: what happened, why, how fixed, how to prevent
- [ ] Create follow-up tickets

## What Cannot Be Rolled Back

Some actions are irreversible. Plan accordingly.

| Action | Why Irreversible | Mitigation |
|--------|------------------|------------|
| **Sent notifications** | Emails, SMS, push already delivered | Test in staging, staged rollout |
| **External API calls** | Third-party state changed | Idempotency keys, dry-run mode |
| **Published packages** | npm, PyPI don't allow re-publish of same version | Bump version, deprecate bad version |
| **Deleted data** | Gone without backup | Soft deletes, backups, retention policies |
| **Leaked secrets** | Attacker may have copied | Rotate immediately, assume compromised |

## Prevention: Design for Rollback

### Staged Rollouts
```bash
# Deploy to 1% first
kubectl set image deployment/app app=image:v2 --record
kubectl rollout pause deployment/app

# Check metrics, then continue
kubectl rollout resume deployment/app
```

### Canary Deployments
- Deploy new version alongside old
- Route small percentage of traffic to new
- Compare error rates
- Full rollout only if metrics are healthy

### Feature Flags for Risky Changes
```python
# Wrap risky code in flags
if feature_flags.is_enabled("new_payment_flow"):
    return new_payment_flow(request)
else:
    return legacy_payment_flow(request)
```

### Database Migration Safety
```sql
-- Backward-compatible migrations only
-- Add column (safe):
ALTER TABLE users ADD COLUMN new_field TEXT;

-- Drop column (unsafe, do later):
-- ALTER TABLE users DROP COLUMN old_field;
```

### Rollback Readiness Checklist
Before deploying, verify:
- [ ] Revert commit identified (what to revert if needed)
- [ ] Feature flag exists for new functionality
- [ ] Database migrations are backward-compatible
- [ ] Monitoring alerts configured
- [ ] On-call engineer aware of deployment

## The Rule

> Prefer reversible actions.
> Design for rollback from the start.
> When in doubt, revert first, investigate second.

## Decision Tree

```
Is production broken?
│
├─ YES: Is it a security issue?
│       │
│       ├─ YES (secrets exposed) → IMMEDIATE: Rotate secrets + Git Revert
│       │
│       └─ NO → Can you disable via feature flag?
│               │
│               ├─ YES → Feature Disable (fastest)
│               │
│               └─ NO → Git Revert
│
└─ NO: Is it a shadow fork issue?
       │
       ├─ YES → Git Reset (fork only)
       │
       └─ NO → Plan fix in next release
```

---

## See Also
- [git-safety.md](./git-safety.md) - Git operations by zone
- [boundary-automation.md](./boundary-automation.md) - Publish gate checks
- [sandbox-and-permissions.md](./sandbox-and-permissions.md) - Containment model
