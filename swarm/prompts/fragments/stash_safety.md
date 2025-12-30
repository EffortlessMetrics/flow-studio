# Stash Safety Rules

Guidelines for safe git stash operations to prevent data loss.

## Core Principles

1. **Always include untracked files** when stashing work-in-progress
2. **Use descriptive messages** for every stash
3. **Verify stash contents** before any operation
4. **Never drop stash** until changes are verified elsewhere

## Safe Stash Commands

### Creating a Stash

```bash
# ALWAYS include untracked files and use a message
git stash push --include-untracked -m "WIP: descriptive message about changes"

# For complete safety, include ignored files too
git stash push --all -m "WIP: complete working state including ignored files"
```

### Verifying Stash Contents

Before applying or dropping:

```bash
# List all stashes with messages
git stash list

# Show summary of stash contents
git stash show stash@{0}

# Show full diff of stash contents
git stash show -p stash@{0}

# Show untracked files in stash
git stash show --include-untracked stash@{0}
```

### Applying a Stash

```bash
# Apply without removing from stash list (safe default)
git stash apply stash@{0}

# Verify changes are correct before dropping
git status
git diff

# Only then drop the stash
git stash drop stash@{0}
```

### Recovery Patterns

If stash was accidentally dropped:

```bash
# Find dangling commits (stashes are commits)
git fsck --unreachable | grep commit

# Or use reflog
git reflog | grep -i stash

# Recover using the SHA
git stash apply <sha>
```

## Anti-Patterns

| Dangerous | Safe Alternative |
|-----------|------------------|
| `git stash` (no message) | `git stash push -m "description"` |
| `git stash pop` | `git stash apply` then verify then `git stash drop` |
| `git stash drop` (unverified) | Verify with `git stash show -p` first |
| `git stash clear` | Never use; drop stashes individually after verification |

## Stash Workflow Checklist

Before stashing:
- [ ] Note current branch: `git branch --show-current`
- [ ] Review what will be stashed: `git status`

When stashing:
- [ ] Include untracked: `--include-untracked`
- [ ] Add descriptive message: `-m "WIP: ..."`

Before applying:
- [ ] Verify correct stash: `git stash show -p stash@{n}`
- [ ] Check target branch is correct
- [ ] Check for potential conflicts

After applying:
- [ ] Verify changes are correct: `git status && git diff`
- [ ] Only then drop the stash

## Stash Message Convention

Format: `WIP: <context> - <what was being worked on>`

Examples:
- `WIP: feature/auth - implementing password reset flow`
- `WIP: hotfix - partial fix for memory leak, need to test`
- `WIP: interrupted by urgent bug - was refactoring UserService`
