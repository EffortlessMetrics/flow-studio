# Prune Branches Step (Flow 8 - Reset)

SDK User Prompt for the `prune_branches` step in Flow 8 (Reset).

---

## Objective

Clean up stale remote-tracking branches and merged local branches safely, maintaining repository hygiene while strictly protecting critical branches.

---

## Inputs

| Input | Source | Description |
|-------|--------|-------------|
| `current_branch` | `git branch --show-current` | The currently checked-out branch (never delete) |
| `protected_branches` | Configuration / {{branch_protection_rules}} | List of branches that must never be deleted |
| `run_id` | Orchestrator context | Current run identifier |

### Input Validation

Before proceeding, verify:

1. **Current branch is known**: `git branch --show-current` returns a value
2. **Protected branches list is loaded**: At minimum includes `main`, `master`, `develop`
3. **Repository state is clean**: No uncommitted changes (enforced by prior steps)

---

## Outputs

| Output | Path | Description |
|--------|------|-------------|
| `prune_report.md` | `.runs/<run-id>/reset/prune_report.md` | Detailed log of pruning operations |
| Prune Branches Result | Control plane block | Structured result for orchestrator routing |

### Output Artifacts

Write `.runs/<run-id>/reset/prune_report.md` with:

- Branches deleted (local)
- Remote-tracking refs pruned
- Branches kept (with reason: protected, current, unmerged)
- Any errors encountered

---

## CRITICAL SAFETY RULES

**These rules are non-negotiable. Violating them can cause irreversible data loss.**

### 1. NEVER Delete Protected Branches

{{branch_protection_rules}}

Protected branches include:
- `main` - Primary production branch
- `master` - Legacy production branch
- `develop` - Integration branch
- `release/*` - Release preparation branches
- `hotfix/*` - Critical fix branches

### 2. NEVER Delete Current Branch

The currently checked-out branch cannot be safely deleted. Always check:

```bash
current_branch=$(git branch --show-current)
# NEVER delete $current_branch
```

### 3. Use Safe Delete ONLY

```bash
# CORRECT: Safe delete (fails if unmerged)
git branch -d <branch-name>

# FORBIDDEN: Force delete (destroys unmerged work)
git branch -D <branch-name>  # NEVER USE
```

**Why `-d` not `-D`?**
- `-d` (lowercase) only deletes if the branch is fully merged
- `-D` (uppercase) force-deletes regardless of merge status
- Using `-D` can permanently lose unmerged commits

### 4. Check Protected List Before Any Deletion

Before deleting any branch, ALWAYS verify:

```bash
is_protected() {
  local branch="$1"
  case "$branch" in
    main|master|develop|release/*|hotfix/*)
      return 0  # Protected - DO NOT DELETE
      ;;
    *)
      return 1  # Not protected - may delete if merged
      ;;
  esac
}

# Usage
if is_protected "$branch"; then
  echo "SKIP: $branch is protected"
  continue
fi
```

---

## Commands

### Prune Stale Remote-Tracking References

```bash
# Dry run first
git remote prune origin --dry-run

# Execute prune
git remote prune origin
```

This removes local references to branches that no longer exist on the remote.

### Find and Delete Merged Local Branches

```bash
# Find branches merged into main/master
git branch --merged origin/main | grep -v -E '^\*|main|master|develop|release|hotfix'

# Safe delete each (respecting protection)
git branch -d <branch-name>
```

---

## Pattern: swarm/* Branches Cleanup

The swarm creates temporary branches for operations. Clean these up when merged:

```bash
# Find swarm-created branches
swarm_branches=$(git branch --list 'swarm/*' --merged origin/main)

# Also clean run branches
run_branches=$(git branch --list 'run/*' --merged origin/main)

# Safe delete after verification
for branch in $swarm_branches $run_branches; do
  branch=$(echo "$branch" | xargs)  # trim whitespace

  # Skip if empty or protected
  [ -z "$branch" ] && continue
  is_protected "$branch" && continue

  # Skip current branch
  [ "$branch" = "$current_branch" ] && continue

  # Safe delete
  git branch -d "$branch" 2>/dev/null && echo "Deleted: $branch"
done
```

---

## Complete Procedure

```bash
ROOT=$(git rev-parse --show-toplevel) || exit 2
gitc() { git -C "$ROOT" "$@"; }

# 1. Get current branch (NEVER delete)
current_branch=$(gitc branch --show-current)

# 2. Define protected branches
protected_branches=("main" "master" "develop")

# 3. Protection check function
is_protected() {
  local branch="$1"
  for protected in "${protected_branches[@]}"; do
    [ "$branch" = "$protected" ] && return 0
  done
  case "$branch" in
    release/*|hotfix/*) return 0 ;;
  esac
  return 1
}

# 4. Prune stale remote-tracking branches
echo "Pruning stale remote-tracking references..."
pruned_remotes=$(gitc remote prune origin 2>&1)
remote_prune_count=$(echo "$pruned_remotes" | grep -c "pruned" || echo "0")

# 5. Find merged local branches
echo "Finding merged local branches..."
upstream="origin/main"
if ! gitc rev-parse --verify "$upstream" >/dev/null 2>&1; then
  upstream="origin/master"
fi

merged_branches=$(gitc branch --merged "$upstream" | grep -v -E '^\*|main|master|develop|release|hotfix')

# 6. Delete merged branches (with safety checks)
deleted_branches=()
protected_skipped=()
unmerged_skipped=()

for branch in $merged_branches; do
  branch=$(echo "$branch" | xargs)  # trim whitespace

  # Skip empty
  [ -z "$branch" ] && continue

  # Skip current branch
  if [ "$branch" = "$current_branch" ]; then
    protected_skipped+=("$branch (current)")
    continue
  fi

  # Skip protected branches
  if is_protected "$branch"; then
    protected_skipped+=("$branch (protected)")
    continue
  fi

  # Attempt safe delete (-d, NOT -D)
  if gitc branch -d "$branch" 2>/dev/null; then
    deleted_branches+=("$branch")
  else
    unmerged_skipped+=("$branch (unmerged)")
  fi
done
```

---

## Output Schema

### Prune Report Format (`.runs/<run-id>/reset/prune_report.md`)

```markdown
# Branch Prune Report

## Summary
- Remote refs pruned: <count>
- Local branches deleted: <count>
- Branches protected: <count>
- Branches skipped (unmerged): <count>

## Remote Refs Pruned
<list of pruned remote-tracking refs>

## Local Branches Deleted
<list of deleted branches with merge status>

## Branches Kept
### Protected
<list with protection reason>

### Current Branch
- <current_branch> (cannot delete checked-out branch)

### Unmerged
<list of branches with unmerged changes - preserved>

## Errors
<any errors encountered, or "None">

## Timestamp
<ISO-8601 timestamp>
```

### Control Plane Result Block

```yaml
## Prune Branches Result
operation: prune_branches
status: COMPLETED | COMPLETED_WITH_CONCERNS | FAILED
remote_refs_pruned: <count>
local_branches_deleted:
  - <branch-name>
  - <branch-name>
protected_branches_skipped:
  - <branch-name>: <reason>
current_branch: <name>
unmerged_branches_preserved:
  - <branch-name>
errors: [] | [<error descriptions>]
```

### Status Semantics

| Status | Meaning |
|--------|---------|
| `COMPLETED` | All pruning operations succeeded, no issues |
| `COMPLETED_WITH_CONCERNS` | Some branches could not be deleted (unmerged), logged for review |
| `FAILED` | Git command failures (not safety blocks) |

---

## Error Handling

### Branch Deletion Refused

If `git branch -d` refuses deletion:

```
error: The branch 'feature-xyz' is not fully merged.
```

**Response**: Log as `unmerged_branches_preserved`, do NOT escalate to `-D`.

### Remote Prune Errors

If `git remote prune` fails:

```bash
# Retry with fetch first
gitc fetch origin --prune
```

### Permission Errors

If branch deletion fails due to permissions:

```
error: unable to delete 'refs/heads/branch-name': permission denied
```

**Response**: Log error, continue with remaining branches, set `status: COMPLETED_WITH_CONCERNS`.

---

## Handoff

After completing the prune operation, provide:

1. **The control plane result block** (for orchestrator routing)
2. **A prose summary** explaining what happened

*Example prose:*

> "Pruned 3 stale remote-tracking refs and deleted 5 merged local branches (feature/auth, feature/api, run/issue-42, swarm/temp-1, swarm/temp-2). Protected 3 branches (main, develop, hotfix/urgent-fix). Current branch 'run/current-work' preserved. No errors encountered."

---

## Safety Checklist

Before this step completes, verify:

- [ ] No protected branches were deleted
- [ ] Current branch was not deleted
- [ ] Only `-d` (safe delete) was used, never `-D`
- [ ] All deletions logged to prune_report.md
- [ ] Control plane result block emitted

---

## Fragment Dependencies

This prompt references:

- `{{branch_protection_rules}}` - Full branch protection specification
- `{{git_safety_rules}}` - Core git safety invariants
- `{{output_schema_header}}` - Standard output format requirements
