# Git Safety in the Shadow Fork Model

Agents operate in an **isolated shadow fork**, blind to upstream. This changes everything about git safety.

## The Two Zones

### Inside the Shadow Fork (Flows 1-5)
**HIGH AUTONOMY** - All git operations are permitted.

The shadow fork is an isolated copy. Agents can:
- `git reset --hard` freely
- `git push --force` to any branch in the fork
- `git rebase` and restructure history
- Delete branches
- Clean the working tree

None of this affects upstream. The fork is a sandbox.

### At the Publish Boundary (Flow 6 Deploy)
**RESTRICTED** - Only safe operations to upstream.

When pushing to `upstream/main` or merging to protected branches:
- No force push
- No history rewriting
- Conflict resolution required
- Human approval for merge

## Operations by Zone

### Inside Shadow Fork (Default-Allow)

```bash
# ALL of these are SAFE inside the fork:
git reset --hard HEAD~3
git push --force origin feature-branch
git rebase -i main
git clean -fd
git branch -D old-branch
git checkout -B feature --track origin/main
```

**Why it's safe:** The fork is isolated. These operations only affect the local copy. Flow 8 (Rebase) handles deliberate sync to upstream.

### At Publish Boundary (Restricted)

```bash
# These require approval at Flow 6:
git push upstream main           # Pushing to upstream protected branch
git push origin main --force     # Force pushing main (even in fork)

# These are BLOCKED at boundary:
git push upstream main --force   # NEVER - destroys upstream history
```

## Protected Branches Clarified

| Branch | In Fork (origin) | At Upstream | Notes |
|--------|------------------|-------------|-------|
| `main` | Restructure OK | PROTECTED | Fork main is just a local branch |
| `feature/*` | Full autonomy | Full autonomy | Feature branches are always free |
| `upstream/main` | N/A | NEVER TOUCH | This is the real protected branch |

**Key insight:** "Protected branches" means `upstream/*`, not branches in the fork.

## Flow 8: The Deliberate Sync

Flow 8 (Reset/Rebase) is the **only** path from fork to upstream:

1. Fetch upstream changes
2. Rebase fork work onto upstream
3. Resolve conflicts (with escalation ladder)
4. Push to upstream (gated at Flow 6)

This is deliberate, logged, and audited. It's not an accident.

## Conflict Resolution (Flow 8 Only)

Conflicts only matter when syncing to upstream:

1. **Auto-merge**: Whitespace, imports → auto-resolve
2. **Structured merge**: Code conflicts → attempt resolution
3. **Human escalate**: Semantic conflicts → document and escalate

Inside the fork, there are no conflicts (single agent, single branch).

## What repo-operator Does

### During Flows 1-4 (Inside Fork)
- Full git autonomy
- Create/delete branches freely
- Reset, rebase, restructure as needed
- Force push to feature branches

### During Flow 5 (Gate)
- Audit git state
- Verify branch is clean
- Check for upstream divergence
- Recommend Flow 8 if needed

### During Flow 6 (Deploy)
- Execute merge to upstream
- No force operations
- Verify merge succeeded
- Record audit trail

### During Flow 8 (Rebase)
- Fetch upstream
- Rebase onto upstream/main
- Resolve conflicts (with escalation)
- Prepare for merge

## The Rule

> Inside the shadow fork: full autonomy.
> At the publish boundary: strict controls.
> Flow 8 bridges the gap deliberately.

## Upstream Divergence Handling

If upstream changes during Flows 1-4:
- Agents are **blind** (working on T-0 snapshot)
- Work continues unaffected
- Divergence detected at Flow 5 (Gate)
- Flow 8 injected if merge would conflict

This is by design. The shadow fork isolates agents from upstream churn.

---

## See Also
- [sandbox-and-permissions.md](./sandbox-and-permissions.md) - The containment model
- [boundary-automation.md](./boundary-automation.md) - Publish gate checks
- [BOUNDARY_PHYSICS.md](../../docs/explanation/BOUNDARY_PHYSICS.md) - Teaching doc
