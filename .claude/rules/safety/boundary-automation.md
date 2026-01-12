# Boundary Automation: Publish Gate Enforcement

Boundaries are where risk concentrates. Enforcement happens **only at the publish boundary** (Flow 6), not inside the shadow fork.

## The Shadow Fork Model

```
┌─────────────────────────────────────────┐
│     SHADOW FORK (Flows 1-5)             │
│     FULL AUTONOMY                       │
│                                         │
│   - All git operations permitted        │
│   - Force push, reset, rebase: OK       │
│   - Delete branches: OK                 │
│   - No restrictions on work             │
│                                         │
│   Agents work blind to upstream.        │
│   This is an isolated sandbox.          │
└─────────────────────────────────────────┘
                    │
                    │ Flow 8 (Rebase) - deliberate sync
                    ▼
┌─────────────────────────────────────────┐
│     PUBLISH BOUNDARY (Flow 6)           │
│     RESTRICTED                          │
│                                         │
│   - Secrets scanning before push        │
│   - Evidence verification               │
│   - No force push to upstream           │
│   - Human approval for merge            │
└─────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────┐
│     UPSTREAM (main repo)                │
│     PROTECTED                           │
│                                         │
│   - Receives merge from Flow 6          │
│   - Branch protection enforced          │
│   - CI/CD runs on merged code           │
└─────────────────────────────────────────┘
```

## What's Checked at Publish Boundary

### Secrets Scanning (Flow 6 only)

Before pushing to upstream, scan for:
```
# API Keys
/sk-[A-Za-z0-9]{48}/  (OpenAI)
/AKIA[A-Z0-9]{16}/   (AWS)
/ghp_[A-Za-z0-9]{36}/ (GitHub)

# Credentials in code
/password\s*=\s*['""][^'""]+['""]/
/secret\s*=\s*['""][^'""]+['""]/

# Private Keys
/-----BEGIN (RSA |DSA |EC )?PRIVATE KEY-----/
```

**Action:** Block push, require removal.

### Evidence Verification (Flow 5-6)

Before merge recommendation:
- [ ] Test receipt exists and is fresh
- [ ] Lint receipt exists (or explicitly not measured)
- [ ] All HIGH severity concerns addressed
- [ ] Work artifacts exist

### Upstream Push Restrictions (Flow 6 only)

At publish boundary ONLY:
```bash
# BLOCKED when pushing to upstream:
git push upstream main --force     # NEVER
git push upstream main --force-with-lease  # NEVER

# REQUIRES APPROVAL:
git push upstream main             # Gate approval needed
```

## What's NOT Restricted

### Inside the Shadow Fork (Flows 1-5)

All of these are **permitted** inside the fork:
```bash
git reset --hard HEAD~5
git push --force origin feature-branch
git push --force origin main        # It's just the fork's main
git rebase -i main
git clean -fd
git branch -D any-branch
git checkout -B new-branch
```

**Why:** The fork is isolated. These operations don't affect upstream.

## Enforcement Points

### Flow 5 (Gate)
- Evidence verification
- Recommend merge or bounce
- Check for upstream divergence → may inject Flow 8

### Flow 6 (Deploy)
- Secrets scan on final diff
- Execute merge to upstream
- Verify CI passes
- Record audit trail

### Flow 8 (Rebase)
- Fetch upstream
- Rebase work onto upstream/main
- Resolve conflicts
- Prepare clean merge

## The Rule

> Inside the shadow fork: **full autonomy**.
> At publish boundary: **strict verification**.
> Flow 8 bridges the gap **deliberately**.

No restrictions apply inside the fork. Restrictions only matter when touching upstream.

---

## See Also
- [git-safety.md](./git-safety.md) - Git operations by zone
- [sandbox-and-permissions.md](./sandbox-and-permissions.md) - Containment model
- [BOUNDARY_PHYSICS.md](../../docs/explanation/BOUNDARY_PHYSICS.md) - Teaching doc
