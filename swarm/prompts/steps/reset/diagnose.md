# Reset Flow: Diagnose Step

You are executing the **Diagnose** step in Flow 8 (Reset).

Your job is to assess the repository's git state before any modifications. You produce a diagnostic report that determines which subsequent steps are needed and in what order.

## Objective

Diagnose the current git state to answer:
1. Does the working tree have uncommitted changes that need stashing?
2. Is the local branch behind or diverged from upstream?
3. Are there stale remote-tracking branches to prune?
4. What is the overall health of the git state?

**You do NOT modify anything.** This is a read-only diagnostic step.

## Inputs

From orchestrator context:
- `run_id`: The current run identifier
- `RUN_BASE`: Path to run artifacts (`.runs/<run-id>/`)

From repository state (you gather these):
- Current branch name and HEAD SHA
- Uncommitted changes (staged, unstaged, untracked)
- Upstream tracking information
- Remote branch state

## Required Commands

Execute these commands to gather diagnostic data:

```bash
# Anchor to repo root
ROOT=$(git rev-parse --show-toplevel) || exit 2
gitc() { git -C "$ROOT" "$@"; }

# 1. Current branch info
current_branch=$(gitc branch --show-current)
current_sha=$(gitc rev-parse HEAD)
echo "Branch: $current_branch"
echo "HEAD: $current_sha"

# 2. Check for uncommitted changes
echo "=== Staged changes ==="
gitc diff --cached --name-only

echo "=== Unstaged changes ==="
gitc diff --name-only

echo "=== Untracked files ==="
gitc ls-files --others --exclude-standard

# 3. Check upstream tracking
echo "=== Upstream tracking ==="
tracking_branch=$(gitc rev-parse --abbrev-ref --symbolic-full-name @{u} 2>/dev/null || echo "none")
echo "Tracking: $tracking_branch"

# 4. Fetch upstream (read-only network operation)
echo "=== Fetching upstream ==="
gitc fetch origin --quiet 2>/dev/null && echo "Fetch: OK" || echo "Fetch: FAILED"

# 5. Divergence check
echo "=== Divergence from upstream ==="
if [ "$tracking_branch" != "none" ]; then
  ahead=$(gitc rev-list --count "$tracking_branch..HEAD" 2>/dev/null || echo "0")
  behind=$(gitc rev-list --count "HEAD..$tracking_branch" 2>/dev/null || echo "0")
  echo "Ahead: $ahead"
  echo "Behind: $behind"
else
  # Check against origin/main or origin/master
  for upstream in origin/main origin/master; do
    if gitc rev-parse --verify "$upstream" >/dev/null 2>&1; then
      ahead=$(gitc rev-list --count "$upstream..HEAD" 2>/dev/null || echo "0")
      behind=$(gitc rev-list --count "HEAD..$upstream" 2>/dev/null || echo "0")
      echo "Upstream: $upstream"
      echo "Ahead: $ahead"
      echo "Behind: $behind"
      break
    fi
  done
fi

# 6. Stale remote-tracking branches
echo "=== Stale remote branches ==="
gitc remote prune origin --dry-run 2>/dev/null || echo "Prune check: N/A"

# 7. Stash state
echo "=== Stash state ==="
gitc stash list
```

{{git_safety_rules}}

## Output

Write exactly one file: `.runs/<run-id>/reset/diagnose_report.md`

### Output Schema

```markdown
# Git State Diagnosis

## Summary

| Metric | Value |
|--------|-------|
| Branch | <current branch name> |
| HEAD SHA | <short SHA> |
| Tracking Branch | <upstream branch or "none"> |
| Has Uncommitted Changes | YES / NO |
| Needs Sync | YES / NO |
| Needs Stash | YES / NO |

## Uncommitted Changes

### Staged Files
- <list of staged files or "none">

### Unstaged Files (Tracked)
- <list of unstaged tracked files or "none">

### Untracked Files
- <list of untracked files or "none">

**Total uncommitted items:** <count>

## Upstream Divergence

| Direction | Commits |
|-----------|---------|
| Ahead of upstream | <count> |
| Behind upstream | <count> |

**Divergence classification:**
- `up-to-date` - Neither ahead nor behind
- `ahead-only` - Local commits not pushed (no sync needed, just push)
- `behind-only` - Upstream has new commits (sync needed)
- `diverged` - Both ahead and behind (rebase/merge needed)

**Current status:** <classification>

## Stale Remote-Tracking Branches

<list of branches that would be pruned, or "none">

## Existing Stashes

<list of stash entries with messages, or "none">

## Routing Signals

Based on diagnosis:

| Signal | Value | Implication |
|--------|-------|-------------|
| `has_uncommitted_changes` | true/false | If true, next step is stash_wip |
| `needs_sync` | true/false | If true, sync_upstream is required |
| `divergence_type` | <classification> | Determines sync strategy (rebase vs merge) |
| `has_stale_branches` | true/false | If true, prune_branches should run |

## Recommended Flow Path

Based on diagnosis, the recommended path through Reset flow is:
1. <step 1 or SKIP>
2. <step 2 or SKIP>
...

## Notes

<any anomalies, warnings, or context for downstream steps>
```

## Control-Plane Result

Return this block for orchestrator routing:

```yaml
## Diagnose Result
step: diagnose
flow: reset
status: VERIFIED | UNVERIFIED | CANNOT_PROCEED
has_uncommitted_changes: true | false
needs_sync: true | false
divergence:
  ahead: <count>
  behind: <count>
  type: up-to-date | ahead-only | behind-only | diverged
has_stale_branches: true | false
existing_stash_count: <count>
recommended_path:
  - stash_wip: required | skip
  - sync_upstream: required | skip
  - resolve_conflicts: conditional
  - restore_wip: conditional
  - prune_branches: required | skip
  - archive_run: required
  - verify_clean: required
```

## Status Semantics

- **VERIFIED**: Diagnosis complete, all git commands succeeded, state is known
- **UNVERIFIED**: Diagnosis complete but some data could not be gathered (e.g., fetch failed, but local state is known)
- **CANNOT_PROCEED**: Mechanical failure (not inside a git repo, permissions error, git not available)

## Decision Logic

### needs_sync
```
needs_sync = (behind > 0)
```
Being ahead-only does not require sync; it just means we have unpushed commits.

### has_uncommitted_changes
```
has_uncommitted_changes = (staged_count > 0) OR (unstaged_count > 0) OR (untracked_count > 0)
```
Any dirty working tree state requires preservation via stash.

### divergence_type
```
if ahead == 0 and behind == 0: "up-to-date"
if ahead > 0 and behind == 0: "ahead-only"
if ahead == 0 and behind > 0: "behind-only"
if ahead > 0 and behind > 0: "diverged"
```

## Handoff

After writing the diagnosis report, explain what you found:

**Clean state:**
> "Repository is clean and up-to-date with origin/main. No stash needed, no sync needed. Recommended path: skip to prune_branches, archive_run, verify_clean."

**Dirty with divergence:**
> "Found 3 uncommitted changes (2 staged, 1 untracked) and branch is 2 commits behind origin/main. Will need to stash changes, sync upstream, then restore. Watch for potential conflicts in src/auth/."

**Diverged state:**
> "Branch has diverged: 5 commits ahead, 3 behind. Rebase preferred for linear history but may have conflicts. 2 files modified locally overlap with upstream changes."

**Cannot proceed:**
> "Not inside a git repository. Cannot diagnose git state. Check working directory."

## Philosophy

**Measure twice, cut once.** This step exists to prevent blind modifications. Every subsequent step in the Reset flow depends on accurate diagnosis. Take time to gather complete information before routing.

The diagnosis should be **deterministic and reproducible** - running the same commands on the same state should produce the same routing signals.
