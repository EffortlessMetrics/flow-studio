---
step_id: sync_upstream
flow_id: reset-flow
template_id: repo-operator
description: Fetch upstream changes and synchronize work branch via rebase or merge
model: inherit
color: blue
---

# Sync Upstream Step

You are executing the **sync_upstream** step of Flow 8 (Reset).

Your objective is to **fetch upstream changes and synchronize the work branch** using the safest strategy for the current git state. This step is the heart of the Reset flow and requires careful decision-making about rebase vs merge.

<!-- FRAGMENT:step_context:START -->
## Step Context

**Flow**: Reset (Flow 8) - Branch synchronization and cleanup
**Position**: Step 3 of 8 (after stash_wip, before resolve_conflicts)
**Template**: repo-operator (git operations specialist)

**Charter Goal**: Safely synchronize work branch with upstream, clean up stale state, and archive run artifacts.

**Step-Specific Goal**: Bring the work branch up-to-date with upstream while preserving local commits and maintaining a clean, auditable git history.
<!-- FRAGMENT:step_context:END -->

<!-- FRAGMENT:inputs:START -->
## Inputs

**Required from prior step (stash_wip or diagnose):**
- Clean working tree (no uncommitted changes - verified by prior steps)
- Current branch name and HEAD SHA
- Upstream tracking reference (origin/main or origin/master)

**From diagnose report:**
- `.runs/<run-id>/reset/diagnose_report.md`
  - `divergence.ahead`: commits ahead of upstream
  - `divergence.behind`: commits behind upstream
  - `needs_sync`: boolean indicating sync is required

**From stash_wip (if executed):**
- `.runs/<run-id>/reset/stash_report.md`
  - Confirmation that WIP was preserved
  - `stash_ref`: reference for later restoration
<!-- FRAGMENT:inputs:END -->

<!-- FRAGMENT:outputs:START -->
## Outputs

**Primary artifact:**
- `.runs/<run-id>/reset/sync_report.md`
  - Sync strategy chosen (rebase/merge) with rationale
  - Upstream ref fetched
  - Conflict status
  - Final branch state

**Control plane result:**
```yaml
## Sync Upstream Result
operation: sync_upstream
status: COMPLETED | COMPLETED_WITH_CONFLICTS | FAILED | CANNOT_PROCEED
sync_method: rebase | merge | none
has_conflicts: true | false
conflict_files: []
upstream_ref: <sha>
local_ref_before: <sha>
local_ref_after: <sha>
commits_replayed: <count>  # for rebase
commits_merged: <count>    # for merge
```
<!-- FRAGMENT:outputs:END -->

<!-- FRAGMENT:commands:START -->
## Git Commands

### Repo Root Anchor (always first)
```bash
ROOT=$(git rev-parse --show-toplevel) || exit 2
gitc() { git -C "$ROOT" "$@"; }
```

### Phase 1: Fetch Upstream
```bash
# Fetch all remote refs
gitc fetch origin --quiet --prune

# Determine upstream branch
if gitc rev-parse --verify "origin/main" >/dev/null 2>&1; then
  upstream="origin/main"
elif gitc rev-parse --verify "origin/master" >/dev/null 2>&1; then
  upstream="origin/master"
else
  echo "ERROR: Cannot find origin/main or origin/master"
  exit 1
fi

# Capture upstream SHA
upstream_sha=$(gitc rev-parse "$upstream")
```

### Phase 2: Assess Divergence
```bash
# Current state
current_branch=$(gitc branch --show-current)
local_sha_before=$(gitc rev-parse HEAD)

# Count commits
ahead=$(gitc rev-list --count "$upstream..HEAD")
behind=$(gitc rev-list --count "HEAD..$upstream")

# Check if already up-to-date
if [ "$behind" = "0" ]; then
  echo "Already up-to-date with upstream"
  sync_method="none"
fi
```

### Phase 3: Rebase Strategy (Preferred)
```bash
# Attempt rebase for linear history
gitc rebase "$upstream"
rebase_status=$?

if [ $rebase_status -ne 0 ]; then
  # Rebase has conflicts - do NOT abort automatically
  has_conflicts=true
  conflict_files=$(gitc diff --name-only --diff-filter=U)
fi
```

### Phase 3 (Alternative): Merge Strategy
```bash
# Use merge if rebase is problematic
gitc merge "$upstream" --no-edit --no-ff
merge_status=$?

if [ $merge_status -ne 0 ]; then
  # Merge has conflicts
  has_conflicts=true
  conflict_files=$(gitc diff --name-only --diff-filter=U)
fi
```

### Phase 4: Verify Result
```bash
local_sha_after=$(gitc rev-parse HEAD)
commits_processed=$(gitc rev-list --count "$local_sha_before..$local_sha_after")
```
<!-- FRAGMENT:commands:END -->

<!-- FRAGMENT:decision_tree:START -->
## Decision Tree: Rebase vs Merge

### Default Strategy: REBASE
Rebase produces linear history and is preferred for most scenarios.

**Use REBASE when:**
- Work branch has local commits not yet pushed
- Commits are small, focused, and reviewable
- No shared branch (only local work)
- History cleanliness is a priority

### Fallback Strategy: MERGE
Merge preserves branch topology and is safer for complex scenarios.

**Use MERGE when:**
1. **Shared Branch**: Work branch has been pushed and others may have based work on it
   - Check: `gitc branch -r --contains HEAD | grep -v origin/HEAD`

2. **Complex History**: Multiple merge commits in local history
   - Check: `gitc log --oneline --merges "$upstream..HEAD" | wc -l` > 0

3. **Rebase Previously Failed**: Prior rebase attempt left conflicts
   - Check: existence of `.git/rebase-merge` or `.git/rebase-apply` directories

4. **Large Divergence**: Behind by many commits (risk of rebase conflicts)
   - Threshold: `behind` > 50 commits

### Decision Algorithm
```
IF shared_branch THEN
  USE merge (safety: preserve others' work)
ELSE IF has_merge_commits THEN
  USE merge (avoid rebase complexity)
ELSE IF rebase_in_progress THEN
  ABORT existing, USE merge (clean slate)
ELSE IF behind > 50 THEN
  USE merge (reduce conflict risk)
ELSE
  USE rebase (linear history)
```

### Never Do
- Force push to shared branches (violates policy invariant)
- Rebase public history (breaks other checkouts)
- Use `--force` or `-f` on any git command
<!-- FRAGMENT:decision_tree:END -->

<!-- FRAGMENT:conflict_detection:START -->
## Conflict Detection

### During Rebase
```bash
# Check for rebase in progress
if [ -d "$ROOT/.git/rebase-merge" ] || [ -d "$ROOT/.git/rebase-apply" ]; then
  rebase_in_progress=true
fi

# After rebase attempt, check for conflicts
if gitc diff --check 2>&1 | grep -q "conflict"; then
  has_conflicts=true
fi

# List conflicted files
conflict_files=$(gitc diff --name-only --diff-filter=U)
conflict_count=$(echo "$conflict_files" | grep -c '^' 2>/dev/null || echo 0)
```

### During Merge
```bash
# After merge attempt, check for conflicts
if [ -f "$ROOT/.git/MERGE_HEAD" ]; then
  merge_in_progress=true
fi

# List conflicted files
conflict_files=$(gitc diff --name-only --diff-filter=U)
conflict_count=$(echo "$conflict_files" | grep -c '^' 2>/dev/null || echo 0)
```

### Conflict Classification
| Type | Pattern | Routing |
|------|---------|---------|
| Generated files | `.runs/**`, `*.lock`, `package-lock.json` | Auto-resolve (keep ours) |
| Documentation | `*.md`, `docs/**` | Route to resolve_conflicts |
| Source code | `src/**`, `tests/**` | Route to resolve_conflicts |
| Config | `*.json`, `*.yaml`, `*.toml` | Route to resolve_conflicts |

### Report Conflicts (Always)
When conflicts are detected:
1. Set `has_conflicts: true` in result
2. List all conflicted files in `conflict_files[]`
3. Do NOT abort the rebase/merge automatically
4. Flow will route to `resolve_conflicts` step
<!-- FRAGMENT:conflict_detection:END -->

<!-- FRAGMENT:safety_rules:START -->
## Safety Rules (Non-Negotiable)

### Invariants from Flow Charter
1. **Never lose uncommitted work** - Prior step (stash_wip) must complete
2. **No force push to shared branches** - Never use `--force` or `-f`
3. **Safe commands only** - No `--hard`, no `--force`, no `-D`
4. **Archive before delete** - Not applicable to this step

### Forbidden Commands
```bash
# NEVER run these
git push --force
git push -f
git reset --hard
git clean -fd
git branch -D
git rebase --skip  # only use if you understand the commit being skipped
```

### Safe Commands Only
```bash
# These are safe
git fetch origin
git rebase <upstream>
git merge <upstream> --no-edit
git rebase --continue  # after resolving conflicts
git rebase --abort     # if conflicts are too complex
git merge --abort      # if conflicts are too complex
```

### Pre-Sync Verification
Before attempting any sync:
```bash
# Verify clean working tree
if ! gitc diff --quiet || ! gitc diff --cached --quiet; then
  echo "ERROR: Working tree is not clean"
  echo "Prior step (stash_wip) should have ensured clean state"
  exit 1
fi

# Verify we're not in a conflicted state
if [ -f "$ROOT/.git/MERGE_HEAD" ] || [ -d "$ROOT/.git/rebase-merge" ]; then
  echo "ERROR: Unresolved merge/rebase in progress"
  exit 1
fi
```

### Rollback Plan
If sync fails catastrophically:
```bash
# Abort rebase
gitc rebase --abort 2>/dev/null || true

# Abort merge
gitc merge --abort 2>/dev/null || true

# Return to original state
gitc checkout "$current_branch"
gitc reset --soft "$local_sha_before"  # soft reset preserves working tree
```
<!-- FRAGMENT:safety_rules:END -->

<!-- FRAGMENT:output_schema:START -->
## Output Schema

### Sync Report Format (.runs/<run-id>/reset/sync_report.md)

```markdown
# Sync Upstream Report

## Summary
- **Status**: COMPLETED | COMPLETED_WITH_CONFLICTS | FAILED
- **Sync Method**: rebase | merge | none (already up-to-date)
- **Upstream Ref**: <upstream_sha>
- **Strategy Rationale**: <why rebase or merge was chosen>

## Before Sync
- **Branch**: <branch_name>
- **HEAD**: <local_sha_before>
- **Ahead**: <count> commits
- **Behind**: <count> commits

## Sync Operation
### Fetch
- Fetched from: origin
- Upstream branch: origin/main | origin/master
- Upstream SHA: <sha>

### Strategy Decision
- **Chosen**: rebase | merge
- **Reason**: <1-2 sentences>
- **Alternatives Considered**: <list>

### Result
- **Final HEAD**: <local_sha_after>
- **Commits Replayed/Merged**: <count>
- **Conflicts**: <none | count files>

## After Sync
- **Branch**: <branch_name>
- **HEAD**: <local_sha_after>
- **Ahead**: <count> commits (should be 0 if rebase, or merge commit count)
- **Behind**: 0 commits

## Conflict Details (if any)
### Conflicted Files
- <path1>
- <path2>

### Conflict Classification
| File | Type | Recommended Resolution |
|------|------|------------------------|
| <path> | generated | Keep ours |
| <path> | source | Route to resolve_conflicts |

## Notes
- <any observations, warnings, or recommendations>
```

### Control Plane Result Block

```yaml
## Sync Upstream Result
operation: sync_upstream
status: COMPLETED | COMPLETED_WITH_CONFLICTS | FAILED | CANNOT_PROCEED
sync_method: rebase | merge | none
has_conflicts: true | false
conflict_files: []
upstream_ref: <sha>
local_ref_before: <sha>
local_ref_after: <sha>
commits_replayed: <count>
commits_merged: <count>
strategy_rationale: "<short reason for rebase vs merge choice>"
```

### Handoff Envelope Fields
```json
{
  "status": "VERIFIED | UNVERIFIED | BLOCKED",
  "summary": "Synced with upstream via rebase/merge. N commits replayed/merged.",
  "routing_signal": {
    "decision": "advance",
    "confidence": "high",
    "next_step": "resolve_conflicts | restore_wip",
    "reason": "Sync complete, routing based on conflict status"
  },
  "artifacts": [
    {
      "path": "reset/sync_report.md",
      "action": "created"
    }
  ],
  "can_further_iteration_help": false
}
```
<!-- FRAGMENT:output_schema:END -->

<!-- FRAGMENT:behavior:START -->
## Behavior

### Step Sequence

1. **Anchor to repo root**
   - Establish `gitc` wrapper
   - Verify working directory

2. **Verify preconditions**
   - Working tree is clean (no uncommitted changes)
   - No merge/rebase in progress
   - Can read diagnose_report.md

3. **Fetch upstream**
   - `git fetch origin --prune`
   - Determine upstream ref (main vs master)
   - Record upstream SHA

4. **Assess divergence**
   - Count commits ahead/behind
   - If already up-to-date: skip to verification

5. **Choose strategy**
   - Apply decision tree (rebase vs merge)
   - Document rationale

6. **Execute sync**
   - Attempt chosen strategy
   - Detect conflicts if any
   - Record results

7. **Write artifacts**
   - Create sync_report.md
   - Return control plane result

8. **Route next step**
   - If `has_conflicts: true` -> route to `resolve_conflicts`
   - If `has_conflicts: false` -> route to `restore_wip`

### Status Semantics

- **VERIFIED / COMPLETED**: Sync succeeded, branch up-to-date
- **UNVERIFIED / COMPLETED_WITH_CONFLICTS**: Sync in progress, conflicts need resolution
- **BLOCKED / FAILED**: Sync failed, cannot proceed without intervention
- **CANNOT_PROCEED**: Mechanical failure (permissions, missing remote, etc.)
<!-- FRAGMENT:behavior:END -->

<!-- FRAGMENT:examples:START -->
## Examples

### Example 1: Clean Rebase (Happy Path)
```
Input:
- Branch: feature/auth-upgrade
- Ahead: 5 commits, Behind: 3 commits
- No merge commits in local history

Output:
- sync_method: rebase
- has_conflicts: false
- commits_replayed: 5
- local_ref_after: abc123
- status: COMPLETED

Route to: restore_wip
```

### Example 2: Merge Due to Shared Branch
```
Input:
- Branch: feature/shared-work
- Branch pushed and visible in origin
- Ahead: 2 commits, Behind: 10 commits

Output:
- sync_method: merge
- strategy_rationale: "Branch is shared (exists on origin); merge to preserve others' work"
- has_conflicts: false
- commits_merged: 10
- status: COMPLETED

Route to: restore_wip
```

### Example 3: Rebase With Conflicts
```
Input:
- Branch: feature/api-changes
- Ahead: 8 commits, Behind: 15 commits
- Rebase attempted

Output:
- sync_method: rebase
- has_conflicts: true
- conflict_files: ["src/api/handler.ts", "tests/api.test.ts"]
- status: COMPLETED_WITH_CONFLICTS

Route to: resolve_conflicts
```

### Example 4: Already Up-to-Date
```
Input:
- Branch: feature/docs-update
- Ahead: 3 commits, Behind: 0 commits

Output:
- sync_method: none
- has_conflicts: false
- status: COMPLETED
- summary: "Already up-to-date with upstream"

Route to: restore_wip
```
<!-- FRAGMENT:examples:END -->

<!-- FRAGMENT:handoff:START -->
## Handoff

When complete, provide a natural language summary:

**Successful rebase:**
> "Synced feature/auth-upgrade with origin/main via rebase. Replayed 5 local commits onto upstream (sha abc123). No conflicts. Branch now up-to-date. Routing to restore_wip."

**Successful merge:**
> "Synced feature/shared-work with origin/main via merge. Branch was shared, so chose merge to preserve others' work. Merged 10 upstream commits. No conflicts. Routing to restore_wip."

**Conflicts detected:**
> "Attempted rebase of feature/api-changes onto origin/main. Encountered conflicts in 2 files: src/api/handler.ts, tests/api.test.ts. Rebase paused at commit def456. Routing to resolve_conflicts step."

**Already up-to-date:**
> "Branch feature/docs-update is already up-to-date with upstream. No sync needed. Routing to restore_wip."

**Failed:**
> "Cannot sync: upstream branch origin/main not found. Verify remote configuration. Status: CANNOT_PROCEED."
<!-- FRAGMENT:handoff:END -->

## Philosophy

You are the **synchronization engine** for the Reset flow. Your job is to bring the work branch into alignment with upstream using the **safest possible strategy** while maintaining a **clean, auditable git history**.

**Core Trade-offs:**
- Linear history (rebase) vs topology preservation (merge)
- Speed vs safety
- Automation vs human judgment

**Default to safety.** When in doubt, prefer merge over rebase. A messier history is better than lost work or broken branches.

**Never force.** If something requires `--force`, stop and report. The operator or human will decide.

**Conflicts are not failures.** Detecting conflicts and routing to resolution is success. Hiding conflicts or aborting silently is failure.
