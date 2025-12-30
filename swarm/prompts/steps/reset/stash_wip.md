# Stash WIP Step

You are executing the **stash_wip** step in Flow 8 (Reset).

## Objective

Safely preserve any work-in-progress changes before branch synchronization operations. Your single task is to stash all uncommitted work (staged, unstaged, and untracked) with a descriptive message that enables reliable recovery.

## Context

This step is part of the Reset flow, which handles branch synchronization and cleanup. You are called **only when the preceding diagnose step indicates uncommitted changes exist**.

## Inputs

From the diagnose step result (via envelope or context):

```yaml
diagnose_result:
  has_uncommitted_changes: true
  has_staged: true | false
  has_unstaged: true | false
  has_untracked: true | false
  current_branch: "<branch-name>"
  run_id: "<run-id>"
```

Optional context:
- `.runs/<run-id>/reset/diagnose_report.md` (detailed state from diagnose)

## Outputs

1. **Stash reference** - The stash identifier for later restoration
2. **Stash report** - Written to `.runs/<run-id>/reset/stash_report.md`
3. **Structured result** - Control plane block for orchestrator routing

---

## Procedure

### Step 1: Verify Preconditions

```bash
ROOT=$(git rev-parse --show-toplevel) || exit 2
gitc() { git -C "$ROOT" "$@"; }

# Confirm there are changes to stash
has_changes=false
if ! gitc diff --cached --quiet || ! gitc diff --quiet; then
  has_changes=true
fi
if [ -n "$(gitc ls-files --others --exclude-standard)" ]; then
  has_changes=true
fi

if [ "$has_changes" = "false" ]; then
  echo "No changes to stash - step will be skipped"
fi
```

If no changes exist, set `status: SKIPPED` and exit early.

### Step 2: Inventory What Will Be Stashed

Before stashing, record exactly what will be preserved:

```bash
# Staged files
staged_files=$(gitc diff --cached --name-only)
staged_count=$(echo "$staged_files" | grep -c . || echo "0")

# Unstaged modified files
unstaged_files=$(gitc diff --name-only)
unstaged_count=$(echo "$unstaged_files" | grep -c . || echo "0")

# Untracked files
untracked_files=$(gitc ls-files --others --exclude-standard)
untracked_count=$(echo "$untracked_files" | grep -c . || echo "0")

total_files=$((staged_count + unstaged_count + untracked_count))
```

### Step 3: Create Descriptive Stash

{{stash_safety}}

```bash
# Generate timestamp and descriptive message
timestamp=$(date +%Y%m%d_%H%M%S)
branch=$(gitc branch --show-current)
stash_msg="WIP: Flow 8 reset on ${branch} - ${timestamp} - ${total_files} files"

# Create stash with untracked files included
gitc stash push --include-untracked -m "$stash_msg"
stash_exit_code=$?

if [ $stash_exit_code -ne 0 ]; then
  echo "ERROR: Stash operation failed with exit code $stash_exit_code"
  exit 1
fi
```

### Step 4: Verify Stash Was Created

```bash
# Get the stash reference and SHA
stash_ref="stash@{0}"
stash_sha=$(gitc stash list -1 --format="%H" 2>/dev/null || echo "")

# Verify stash exists
if [ -z "$stash_sha" ]; then
  echo "ERROR: Stash was not created"
  exit 1
fi

# Verify working directory is now clean
if ! gitc diff --cached --quiet || ! gitc diff --quiet; then
  echo "WARNING: Tracked changes remain after stash"
fi

# Verify stash contents match what we inventoried
stash_contents=$(gitc stash show --name-only "$stash_ref")
```

### Step 5: Write Stash Report

Write to `.runs/<run-id>/reset/stash_report.md`:

```markdown
# Stash Report

## Summary
- **Stash Reference:** stash@{0}
- **Stash SHA:** <sha>
- **Stash Message:** <message>
- **Created:** <ISO-8601 timestamp>

## Files Stashed

### Staged (<count>)
<list or "none">

### Unstaged (<count>)
<list or "none">

### Untracked (<count>)
<list or "none">

## Recovery Commands

To view stash contents:
```bash
git stash show -p stash@{0}
```

To apply stash (without removing):
```bash
git stash apply stash@{0}
```

To restore and remove stash:
```bash
git stash pop stash@{0}
```

## Notes
- Stash created as part of Flow 8 Reset
- Will be restored in restore_wip step after sync
- <any warnings or observations>
```

---

## Safety Invariants

{{git_safety_rules}}

### Stash-Specific Invariants

1. **NEVER lose uncommitted work**
   - Always use `--include-untracked` flag
   - Always provide descriptive message
   - Verify stash was created before proceeding

2. **NEVER drop stash automatically**
   - Only the `restore_wip` step may drop stash
   - Only after verifying changes were applied successfully

3. **NEVER skip inventory**
   - Always record what files will be stashed
   - Enables verification during restore

4. **NEVER use `git stash pop` directly**
   - Use `git stash apply` followed by verification
   - Only drop after confirming successful restore

5. **Preserve stash message format**
   - Include: branch name, timestamp, file count
   - Enables identification if multiple stashes accumulate

---

## Output Schema

{{output_schema_header}}

### Stash WIP Result Block

```yaml
## Stash WIP Result
step: stash_wip
flow: reset
status: COMPLETED | SKIPPED | FAILED | CANNOT_PROCEED
stash_created: true | false
stash_ref: "stash@{0}" | null
stash_sha: "<sha>" | null
stash_message: "<message>" | null
files_stashed:
  staged: <count>
  unstaged: <count>
  untracked: <count>
  total: <count>
working_directory_clean: true | false
artifacts_written:
  - ".runs/<run-id>/reset/stash_report.md"
```

### Status Semantics

- **COMPLETED**: Stash created successfully, working directory is clean
- **SKIPPED**: No changes to stash (valid when diagnose showed changes but they disappeared)
- **FAILED**: Stash command failed (exit code non-zero)
- **CANNOT_PROCEED**: Mechanical failure (git unavailable, permissions)

---

## Routing Signal

After completing this step:

```yaml
routing_signal:
  decision: CONTINUE
  next_step: sync_upstream
  confidence: 1.0
  context:
    stash_ref: "<stash@{0}>"
    restore_required: true
```

The `restore_required: true` flag tells downstream steps that `restore_wip` must be executed after sync operations complete.

---

## Error Handling

### Stash Fails to Create

```bash
# If stash command returns non-zero
if [ $stash_exit_code -ne 0 ]; then
  # Check if it's because nothing to stash
  if gitc diff --cached --quiet && gitc diff --quiet && \
     [ -z "$(gitc ls-files --others --exclude-standard)" ]; then
    # Actually clean - report SKIPPED
    status="SKIPPED"
  else
    # Real failure
    status="FAILED"
    # Capture error output for report
  fi
fi
```

### Working Directory Not Clean After Stash

If tracked changes remain after stash (should not happen):

1. Log the unexpected state in stash_report.md
2. Set `working_directory_clean: false`
3. Continue with COMPLETED status (sync may still work)
4. The `restore_wip` step will handle reconciliation

### Git Unavailable

```yaml
## Stash WIP Result
step: stash_wip
flow: reset
status: CANNOT_PROCEED
reason: "git command not available or repository not initialized"
stash_created: false
```

---

## Handoff

After emitting the result block, provide context:

*Stash created:*
> "Stashed 15 files (3 staged, 8 unstaged, 4 untracked) as stash@{0} with SHA abc1234. Working directory is now clean. Ready for sync_upstream step. Stash will be restored in restore_wip step."

*Skipped (no changes):*
> "No uncommitted changes found despite diagnose indicating changes existed. They may have been committed or discarded between steps. Proceeding to sync_upstream. restore_required: false."

*Failed:*
> "Stash operation failed. Error: <error message>. Cannot proceed with reset flow - uncommitted work would be lost during sync operations. Investigate git state manually."

---

## Example Execution

Given diagnose result:
```yaml
has_uncommitted_changes: true
has_staged: true
has_unstaged: true
has_untracked: true
current_branch: "feat/auth"
```

Expected output:
```yaml
## Stash WIP Result
step: stash_wip
flow: reset
status: COMPLETED
stash_created: true
stash_ref: "stash@{0}"
stash_sha: "a1b2c3d4e5f6..."
stash_message: "WIP: Flow 8 reset on feat/auth - 20240115_143022 - 15 files"
files_stashed:
  staged: 3
  unstaged: 8
  untracked: 4
  total: 15
working_directory_clean: true
artifacts_written:
  - ".runs/feat-auth/reset/stash_report.md"
```
