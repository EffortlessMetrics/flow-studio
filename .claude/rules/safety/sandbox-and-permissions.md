# Sandbox and Permissions

**"Autonomy requires isolation."**

## Why bypassPermissions is Acceptable Here

Flow Studio uses `bypassPermissions` intentionally because safety is enforced
at the **boundary layer**, not through constant prompts.

### The Inversion

Traditional tooling assumes the environment is unsafe:
- Model has secrets access
- Model can push to upstream
- Every action needs human approval

Flow Studio inverts this:
- **Make the environment safe**
- **Remove friction inside the sandbox**
- **Gate publishing at exits**

## Containment Checklist

bypassPermissions is ONLY acceptable when ALL of these are true:

### Workspace
- [ ] Dedicated working directory (cloned repo, not home directory)
- [ ] Non-admin user
- [ ] No credentials in environment or dotfiles

### Repository
- [ ] Secrets are NOT in-tree
- [ ] Git remotes are controlled
- [ ] Publishing goes through boundary agents

### Network
- [ ] Restricted if possible
- [ ] If unrestricted: no tokens, no internal endpoints

### Publishing
- [ ] Branch protection + required checks (ideal)
- [ ] Otherwise: explicit manual confirmation to push/merge

## The Boundary Model

```
┌─────────────────────────────────────────┐
│          SANDBOX (High Autonomy)        │
│                                         │
│   - Full tool access                    │
│   - No permission prompts               │
│   - Fast iteration                      │
│   - Destructive ops allowed             │
│                                         │
├─────────────────────────────────────────┤
│          BOUNDARY (Gated Exits)         │
│                                         │
│   - Secrets scanning                    │
│   - Surface anomaly detection           │
│   - Destructive git ops blocked         │
│   - Human approval for publish          │
│                                         │
└─────────────────────────────────────────┘
```

## What Boundaries Enforce

### Git Operations
- `git push --force` → BLOCKED
- `git reset --hard` → ASK
- `git clean -fd` → ASK
- Push to main/master → ASK

### Secrets
- `.env*` files → BLOCKED read/write
- `secrets/**` → BLOCKED
- `~/.ssh/**` → BLOCKED
- `~/.aws/**` → BLOCKED
- Credentials in output → Redacted

### Publishing
- `npm publish` → ASK
- `docker push` → ASK
- API posts → Boundary agent review

## Shadow Fork Pattern

Autonomous work happens in an isolated fork:

1. **T-0 Snapshot**: Fork from upstream at start of run
2. **Blind Operation**: Swarm works on T-0 state, blind to upstream changes
3. **Deliberate Merge**: Flow 8 (Rebase) handles upstream integration
4. **Promotion**: Clean work gets pushed/merged

This prevents:
- Race conditions with other contributors
- Merge conflicts during work
- Premature publication

## The Rule

> Engineering is default-allow inside the sandbox.
> Publishing is fail-closed at boundaries using mechanical checks and receipts.

## Current Enforcement

See `.claude/settings.json` for:
- `denyRead` patterns (secrets, credentials)
- `denyWrite` patterns (same)
- `askBefore` patterns (destructive ops)
