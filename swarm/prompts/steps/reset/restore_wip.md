---
name: restore_wip
flow: reset
step_id: restore_wip
template_id: repo-operator
description: Pop stashed work-in-progress changes and verify they apply cleanly to the synchronized branch
model: inherit
---

<!-- FRAGMENT_START: restore_wip.objective -->
## Objective

Pop stashed work-in-progress changes from the previous `stash_wip` step and verify they apply cleanly to the now-synchronized branch. This step ensures no work is lost during the reset process.

**Prime directive:** Restore WIP safely. Never drop a stash until verified. If conflicts occur, preserve both versions.
<!-- FRAGMENT_END: restore_wip.objective -->

<!-- FRAGMENT_START: restore_wip.inputs -->
## Inputs

From orchestrator context:
- `run_id`: Current run identifier
- `stash_ref`: Stash reference from `stash_wip` step (e.g., `stash@{0}`)
- `stash_sha`: SHA of the stash commit for verification
- `files_stashed`: Count of files that were stashed

From previous step envelope (stash_wip):
- `RUN_BASE/reset/stash_report.md`: Details of what was stashed

From run state:
- Current branch (should be synchronized with upstream after `sync_upstream`)
- Current HEAD SHA (post-rebase/merge)
<!-- FRAGMENT_END: restore_wip.inputs -->

<!-- FRAGMENT_START: restore_wip.outputs -->
## Outputs

### Artifacts (always written)

- `RUN_BASE/reset/restore_wip_report.md`: Detailed report of the restore operation

### Control Plane Result

```yaml
## Repo Operator Result
operation: restore_wip
status: COMPLETED | COMPLETED_WITH_CONFLICTS | SKIPPED | FAILED
stash_applied: true | false
stash_ref_used: <stash@{N}> | null
files_restored: <count>
stash_conflicts: [] | [<paths>]
conflict_resolution_applied: true | false
stash_dropped: true | false
ready_for_next_step: true | false
```
<!-- FRAGMENT_END: restore_wip.outputs -->

<!-- FRAGMENT_START: restore_wip.procedure -->
## Procedure

### Step 0: Check if restore is needed

Skip this step if no stash was created:

```bash
ROOT=$(git rev-parse --show-toplevel) || exit 2
gitc() { git -C "$ROOT" "$@"; }

# Check if our WIP stash exists
stash_exists=$(gitc stash list | grep -c "WIP: Flow 8 reset" || echo "0")

if [ "$stash_exists" -eq 0 ]; then
  echo "No WIP stash found - skipping restore"
  # Return SKIPPED status
  exit 0
fi
```

### Step 1: Identify the correct stash

Locate the stash created by `stash_wip`:

```bash
# Find our specific stash by message pattern
stash_ref=$(gitc stash list --format="%gd %s" | grep "WIP: Flow 8 reset" | head -1 | cut -d' ' -f1)

if [ -z "$stash_ref" ]; then
  echo "ERROR: Cannot find WIP stash from stash_wip step"
  exit 1
fi

# Verify stash contents before applying
echo "Stash contents:"
gitc stash show "$stash_ref" --stat
```

### Step 2: Attempt stash pop (apply + drop)

**CRITICAL: Use `git stash pop` for automatic drop on success, but be prepared for conflicts.**

```bash
# Attempt to pop the stash
gitc stash pop "$stash_ref" 2>&1
pop_exit_code=$?

if [ $pop_exit_code -eq 0 ]; then
  echo "Stash applied cleanly"
  stash_applied=true
  stash_conflicts=()
  stash_dropped=true  # pop drops on success
else
  echo "Stash pop had conflicts"
  stash_applied=false
  # Stash NOT dropped when conflicts occur
  stash_dropped=false

  # Identify conflicting files
  stash_conflicts=$(gitc diff --name-only --diff-filter=U)
fi
```

### Step 3: Handle stash pop conflicts

If conflicts occurred during pop, the stash is NOT dropped automatically. Resolve conflicts carefully:

```bash
if [ ${#stash_conflicts[@]} -gt 0 ]; then
  echo "Resolving stash pop conflicts..."

  for conflict_file in $stash_conflicts; do
    echo "Conflict in: $conflict_file"

    # Strategy: Keep BOTH versions where possible
    # WIP changes are precious - we don't want to lose them

    # Check conflict type
    if gitc diff --check "$conflict_file" 2>&1 | grep -q "conflict"; then

      # For code files: attempt 3-way merge preserving both sides
      # The stashed version contains our WIP work
      # The current version contains the rebased/merged upstream

      # Option 1: Use union merge for additive changes
      if git merge-file --union "$conflict_file" "$conflict_file" "$conflict_file"; then
        gitc add "$conflict_file"
        echo "Union merged: $conflict_file"
      else
        # Option 2: Keep stash version (our WIP is more important)
        gitc checkout --theirs "$conflict_file"  # 'theirs' is the stash in pop
        gitc add "$conflict_file"
        echo "Kept stash version: $conflict_file"

        # Also save the current version for reference
        current_backup="${conflict_file}.upstream-version"
        gitc show HEAD:"$conflict_file" > "$current_backup" 2>/dev/null || true
        echo "Saved upstream version to: $current_backup"
      fi
    fi
  done

  # Mark conflicts as resolved
  conflict_resolution_applied=true
fi
```

### Step 4: Verify restored files

After resolving any conflicts, verify the restored state:

```bash
# List all files that were restored/modified
restored_files=$(gitc status --porcelain | wc -l)

# Verify no unresolved conflict markers
if gitc diff --check 2>&1 | grep -q "leftover conflict marker"; then
  echo "ERROR: Unresolved conflict markers remain"
  unresolved_markers=true
else
  unresolved_markers=false
fi

# Compare restored state to original stash contents
# (This is informational, not blocking)
echo "Restored state verification:"
gitc status --short
```

### Step 5: Drop stash only after verification

**CRITICAL: Only drop the stash after confirming restore was successful.**

```bash
if [ "$stash_applied" = true ] || [ "$conflict_resolution_applied" = true ]; then
  if [ "$unresolved_markers" = false ]; then
    # Safe to drop - stash was applied successfully
    if [ "$stash_dropped" = false ]; then
      # Only need to drop if pop didn't auto-drop (i.e., conflicts occurred)
      gitc stash drop "$stash_ref"
      stash_dropped=true
      echo "Stash dropped after successful restore"
    fi
  else
    # DO NOT drop - there are still issues
    stash_dropped=false
    echo "WARNING: Stash NOT dropped due to unresolved markers"
  fi
fi
```
<!-- FRAGMENT_END: restore_wip.procedure -->

<!-- FRAGMENT_START: restore_wip.safety -->
## Safety Invariants

1. **Never drop stash until verified**: The stash contains precious WIP work. Only drop after confirming files are correctly restored.

2. **Preserve both versions on conflict**: When stash conflicts with rebased code:
   - Prefer the stash version (our WIP work)
   - Save the upstream version as `.upstream-version` backup
   - Log what was chosen and why

3. **No destructive operations**:
   - No `git stash drop` before verification
   - No `git checkout --force`
   - No `git clean` that could delete WIP files

4. **Conflict markers must be resolved**: Never leave conflict markers in files. Either resolve them or keep stash intact.

5. **Audit trail**: Write detailed report of what was restored, any conflicts encountered, and how they were resolved.
<!-- FRAGMENT_END: restore_wip.safety -->

<!-- FRAGMENT_START: restore_wip.conflict_handling -->
## Conflict Handling Strategy

### Types of Stash Pop Conflicts

| Conflict Type | Resolution Strategy | Rationale |
|---------------|---------------------|-----------|
| Same line modified | Keep stash (WIP) version | WIP work is more valuable than upstream |
| File deleted upstream | Restore from stash | Don't lose WIP work |
| File renamed upstream | Apply stash to new path | Preserve both work and rename |
| Binary file conflict | Keep stash version | Cannot merge binaries |

### Resolution Procedure

1. **Identify conflict type** using `git diff --check`
2. **Attempt union merge** for additive changes (both sides can coexist)
3. **Prefer stash version** when union merge fails (WIP is precious)
4. **Save backup** of the discarded version for manual review
5. **Log resolution** in the report artifact

### Post-Resolution Verification

```bash
# Ensure no conflict markers remain
git diff --check || echo "Clean - no conflict markers"

# Ensure all files are staged or clean
git status --porcelain | grep -v "^[MADRCU? ]" && echo "WARNING: Unexpected status"
```
<!-- FRAGMENT_END: restore_wip.conflict_handling -->

<!-- FRAGMENT_START: restore_wip.output_schema -->
## Output Schema

### Handoff Envelope Fields

```json
{
  "status": "VERIFIED | UNVERIFIED | BLOCKED",
  "summary": "Restored N files from stash. No conflicts / Resolved M conflicts.",
  "routing_signal": {
    "decision": "advance",
    "next_step": "prune_branches",
    "confidence": "high",
    "reason": "WIP restored successfully, ready for cleanup"
  },
  "artifacts": [
    {
      "path": "reset/restore_wip_report.md",
      "action": "created",
      "description": "Detailed restore operation report"
    }
  ],
  "file_changes": [
    {
      "path": "<restored-file>",
      "change_type": "modified",
      "summary": "Restored from stash"
    }
  ],
  "concerns": [
    {
      "concern": "Stash conflict required manual resolution",
      "severity": "medium",
      "recommendation": "Review restored files for correctness"
    }
  ],
  "assumptions": [
    {
      "assumption": "Stash version preferred over rebased version in conflicts",
      "why": "WIP work is more valuable than mechanical rebase results",
      "impact_if_wrong": "May need to re-integrate upstream changes manually"
    }
  ]
}
```

### Control Plane Result Block

```markdown
## Repo Operator Result
operation: restore_wip
status: COMPLETED | COMPLETED_WITH_CONFLICTS | SKIPPED | FAILED
stash_applied: true | false
stash_ref_used: stash@{0}
files_restored: 5
stash_conflicts:
  - src/auth.ts
  - tests/auth.test.ts
conflict_resolution_applied: true
resolution_strategy: prefer_stash_with_backup
stash_dropped: true
ready_for_next_step: true
```

### Status Semantics

| Status | Meaning | Next Action |
|--------|---------|-------------|
| `COMPLETED` | Stash applied cleanly, no conflicts | Proceed to prune_branches |
| `COMPLETED_WITH_CONFLICTS` | Stash applied, conflicts resolved | Proceed with caution, review recommended |
| `SKIPPED` | No stash to restore (stash_wip was skipped) | Proceed to prune_branches |
| `FAILED` | Could not restore stash (stash corrupted, missing) | Pause for human intervention |
<!-- FRAGMENT_END: restore_wip.output_schema -->

<!-- FRAGMENT_START: restore_wip.artifact_template -->
## Artifact Template: restore_wip_report.md

```markdown
# WIP Restore Report

## Summary
- **Status:** COMPLETED | COMPLETED_WITH_CONFLICTS | SKIPPED | FAILED
- **Stash Reference:** stash@{0}
- **Files Restored:** N
- **Conflicts Resolved:** M

## Stash Details
- **Message:** WIP: Flow 8 reset - 20241230_143000
- **Created At:** <timestamp from stash>
- **Files in Stash:**
  - path/to/file1.ts (modified)
  - path/to/file2.ts (new file)
  - path/to/file3.ts (modified)

## Restore Operation
- **Git Command:** `git stash pop stash@{0}`
- **Exit Code:** 0 | 1
- **Duration:** Xms

## Conflicts (if any)
| File | Conflict Type | Resolution | Backup Saved |
|------|---------------|------------|--------------|
| src/auth.ts | Same line modified | Kept stash version | src/auth.ts.upstream-version |
| tests/auth.test.ts | New function added | Union merged | No |

## Verification
- **Conflict Markers Remaining:** None
- **Untracked Files:** None unexpected
- **Stash Dropped:** Yes / No (reason if no)

## Post-Restore State
```
git status --short
M  src/auth.ts
M  tests/auth.test.ts
A  src/new-feature.ts
```

## Notes
- <Any observations or warnings>
- <Files that may need manual review>
```
<!-- FRAGMENT_END: restore_wip.artifact_template -->

<!-- FRAGMENT_START: restore_wip.handoff -->
## Handoff

After completing the restore operation, provide a clear handoff:

**When COMPLETED (clean apply):**
> "Restored 5 files from stash (stash@{0}). Clean apply, no conflicts. Stash dropped. Ready to proceed to prune_branches."

**When COMPLETED_WITH_CONFLICTS:**
> "Restored 5 files from stash. Resolved 2 conflicts using prefer-stash strategy. Backup versions saved as .upstream-version files. Stash dropped after verification. Review restored files before proceeding."

**When SKIPPED:**
> "No stash to restore - stash_wip step was skipped (no uncommitted changes at diagnose). Proceeding to prune_branches."

**When FAILED:**
> "Could not restore stash: stash@{0} not found or corrupted. Original WIP may be lost. Recommend checking reflog for recovery options. BLOCKED pending human review."
<!-- FRAGMENT_END: restore_wip.handoff -->
