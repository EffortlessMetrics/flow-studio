# verify_clean - Step-Specific SDK User Prompt

<!-- FRAGMENT: step_header -->
Flow: 8-reset
Step ID: verify_clean
Station: repo-operator
Position: Final step (after archive_run)
<!-- /FRAGMENT: step_header -->

## Objective

Verify that the git repository is in a clean, synchronized state and ready for continued work. This is the final gate of Flow 8 (Reset), confirming that all reset operations completed successfully.

## Context

This step executes after the following reset steps have completed:
- **diagnose**: Assessed initial git state (divergence, uncommitted changes, stale tracking)
- **stash_wip**: Preserved any work-in-progress (if applicable)
- **sync_upstream**: Fetched and rebased/merged with upstream
- **resolve_conflicts**: Resolved any merge/rebase conflicts (if applicable)
- **restore_wip**: Restored stashed WIP changes (if applicable)
- **prune_branches**: Cleaned stale remote-tracking and merged branches
- **archive_run**: Archived old run artifacts

## Inputs

<!-- FRAGMENT: inputs -->
### Required Inputs
| Path | Description |
|------|-------------|
| `.runs/<run-id>/reset/diagnose_report.md` | Initial state diagnosis |
| `.runs/<run-id>/reset/sync_report.md` | Upstream sync results |

### Conditional Inputs (from previous steps)
| Path | Condition | Description |
|------|-----------|-------------|
| `.runs/<run-id>/reset/stash_report.md` | If WIP was stashed | Stash operation details |
| `.runs/<run-id>/reset/resolve_report.md` | If conflicts occurred | Conflict resolution details |
| `.runs/<run-id>/reset/restore_report.md` | If WIP was restored | WIP restoration details |
| `.runs/<run-id>/reset/prune_report.md` | Always | Branch cleanup results |
| `.runs/<run-id>/reset/archive_report.md` | Always | Run archival results |
<!-- /FRAGMENT: inputs -->

## Outputs

<!-- FRAGMENT: outputs -->
### Primary Output
| Path | Description |
|------|-------------|
| `.runs/<run-id>/reset/verify_report.md` | Final clean state verification report |

### Control Plane Output
| Field | Description |
|-------|-------------|
| `status` | VERIFIED (clean) or UNVERIFIED (issues remain) |
| `is_clean` | Boolean: no uncommitted changes |
| `is_synced` | Boolean: not behind upstream |
| `ready_for_work` | Boolean: can safely continue development |
| `remaining_issues` | Array of any unresolved problems |
<!-- /FRAGMENT: outputs -->

## Verification Checklist

Execute these checks in order and document each result:

### 1. No Uncommitted Changes

```bash
ROOT=$(git rev-parse --show-toplevel) || exit 2
gitc() { git -C "$ROOT" "$@"; }

# Check staged changes
staged=$(gitc diff --cached --name-only)
if [ -n "$staged" ]; then
  echo "FAIL: Staged changes exist"
  echo "$staged"
fi

# Check unstaged changes (tracked files)
unstaged=$(gitc diff --name-only)
if [ -n "$unstaged" ]; then
  echo "FAIL: Unstaged changes exist"
  echo "$unstaged"
fi
```

### 2. On Correct Branch

```bash
# Verify we're on the expected branch (work branch or main)
current_branch=$(gitc branch --show-current)
echo "Current branch: $current_branch"

# Check if branch has expected upstream tracking
tracking=$(gitc rev-parse --abbrev-ref --symbolic-full-name @{upstream} 2>/dev/null || echo "none")
echo "Tracking: $tracking"
```

### 3. Up to Date with Upstream

```bash
# Fetch latest (should be no-op if sync_upstream ran)
gitc fetch origin --quiet

# Check ahead/behind counts
upstream="origin/main"
if ! gitc rev-parse --verify "$upstream" >/dev/null 2>&1; then
  upstream="origin/master"
fi

ahead=$(gitc rev-list --count "$upstream..HEAD" 2>/dev/null || echo "unknown")
behind=$(gitc rev-list --count "HEAD..$upstream" 2>/dev/null || echo "unknown")

echo "Ahead of upstream: $ahead commits"
echo "Behind upstream: $behind commits"

if [ "$behind" != "0" ] && [ "$behind" != "unknown" ]; then
  echo "WARN: Still behind upstream by $behind commits"
fi
```

### 4. WIP Restored (if applicable)

```bash
# Check stash list for any remaining Flow 8 stashes
remaining_stashes=$(gitc stash list | grep -c "WIP: Flow 8 reset" || echo "0")
if [ "$remaining_stashes" != "0" ]; then
  echo "WARN: $remaining_stashes WIP stash(es) not restored"
  gitc stash list | grep "WIP: Flow 8 reset"
fi
```

### 5. No Untracked Files That Shouldn't Be There

```bash
# Check for unexpected untracked files
untracked=$(gitc ls-files --others --exclude-standard)

# Filter out expected untracked files
unexpected_untracked=""
while IFS= read -r file; do
  [ -z "$file" ] && continue

  # Skip expected untracked patterns
  case "$file" in
    .runs/*) continue ;;           # Run artifacts (gitignored but checked)
    *.log) continue ;;             # Log files
    *.tmp) continue ;;             # Temp files
    *~) continue ;;                # Editor backups
    .DS_Store) continue ;;         # macOS junk
    Thumbs.db) continue ;;         # Windows junk
    __pycache__/*) continue ;;     # Python cache
    node_modules/*) continue ;;    # Node modules
    *.pyc) continue ;;             # Python bytecode
    .env.local) continue ;;        # Local env files
    *)
      unexpected_untracked="$unexpected_untracked$file\n"
      ;;
  esac
done <<< "$untracked"

if [ -n "$unexpected_untracked" ]; then
  echo "WARN: Unexpected untracked files:"
  echo -e "$unexpected_untracked"
fi
```

### 6. No Conflict Markers

```bash
# Verify no unresolved conflict markers in tracked files
conflict_files=$(gitc diff --check 2>&1 | grep -c "conflict" || echo "0")
if [ "$conflict_files" != "0" ]; then
  echo "FAIL: Unresolved conflict markers detected"
  gitc diff --check 2>&1 | head -20
fi
```

### 7. Git State Consistency

```bash
# Verify not in middle of rebase/merge/cherry-pick
if [ -d "$ROOT/.git/rebase-merge" ] || [ -d "$ROOT/.git/rebase-apply" ]; then
  echo "FAIL: Rebase in progress"
fi

if [ -f "$ROOT/.git/MERGE_HEAD" ]; then
  echo "FAIL: Merge in progress"
fi

if [ -f "$ROOT/.git/CHERRY_PICK_HEAD" ]; then
  echo "FAIL: Cherry-pick in progress"
fi
```

## Output Schema

<!-- FRAGMENT: output_schema -->
### Machine Summary (YAML format in verify_report.md)

```yaml
## Machine Summary
status: VERIFIED | UNVERIFIED | BLOCKED

## Verification Results
is_clean: true | false
is_synced: true | false
ready_for_work: true | false

## Branch State
current_branch: <name>
current_sha: <sha>
tracking_upstream: <upstream-ref> | null
ahead_of_upstream: <count>
behind_upstream: <count>

## Uncommitted Changes
staged_files: [] | [<paths>]
unstaged_files: [] | [<paths>]
untracked_files: [] | [<paths>]  # Only unexpected ones

## WIP Status
wip_stashes_remaining: <count>
wip_restored_successfully: true | false | not_applicable

## Git State
in_rebase: false
in_merge: false
in_cherry_pick: false
has_conflict_markers: false

## Remaining Issues
remaining_issues:
  - category: uncommitted | unsync | wip | conflict | other
    description: <what's wrong>
    severity: blocking | warning
    remediation: <how to fix>

## Notes
notes:
  - <non-blocking observations>
```

### Repo Operator Result (Control Plane)

```yaml
## Repo Operator Result
operation: verify_clean
status: VERIFIED | UNVERIFIED | BLOCKED
is_clean: true | false
is_synced: true | false
remaining_issues:
  uncommitted_files: [] | [<paths>]
  behind_upstream: <count>
  wip_not_restored: true | false
  conflict_markers: true | false
ready_for_work: true | false
```
<!-- /FRAGMENT: output_schema -->

## Routing Signal

<!-- FRAGMENT: routing_signal -->
### Status Determination

| Condition | Status | ready_for_work |
|-----------|--------|----------------|
| All checks pass, no issues | VERIFIED | true |
| Minor warnings only (untracked files) | VERIFIED | true |
| Uncommitted changes exist | UNVERIFIED | false |
| Behind upstream | UNVERIFIED | false |
| WIP stashes not restored | UNVERIFIED | false |
| Conflict markers present | UNVERIFIED | false |
| Git operation in progress | UNVERIFIED | false |
| Cannot read inputs or run git | BLOCKED | false |

### Routing Decision

```yaml
routing_signal:
  decision: terminate | loop
  confidence: high | medium | low

  # For VERIFIED (clean state)
  next_flow: "return"  # Return to interrupted flow
  reason: "Reset complete, git state verified clean"

  # For UNVERIFIED (issues remain)
  next_step: null
  can_further_iteration_help: <based on issue type>
  blockers:
    - type: <blocker_type>
      description: <what's blocking>
      recoverable: true | false
```

### Exit Criteria Mapping

From reset-flow.graph.json `charter.exit_criteria`:
1. "Work branch is rebased or merged with upstream" -> Check `behind_upstream == 0`
2. "No untracked or uncommitted changes that could cause conflicts" -> Check `is_clean == true`
3. "Stale run artifacts are archived" -> Check archive_report.md exists
4. "Git state is verified clean" -> This step's overall status
<!-- /FRAGMENT: routing_signal -->

## Handoff

After completing verification, provide a natural language handoff:

```markdown
## Handoff

**What I did:** Final verification of git state after reset operations.

**State summary:**
- Branch: <branch> at <sha>
- Clean: <yes/no> (staged: <n>, unstaged: <n>, untracked: <n>)
- Synced: <yes/no> (ahead: <n>, behind: <n>)
- WIP: <restored/not-applicable/not-restored>

**What's left:** <None - ready for work / List of remaining issues>

**Recommendation:** <Return to interrupted flow / Address remaining issues>

**Reasoning:** <1-2 sentences explaining the verification outcome>
```

## Safety Invariants

<!-- FRAGMENT: invariants -->
From reset-flow.graph.json `policy.invariants`:
- **Never lose uncommitted work**: If uncommitted changes exist at this stage, flag as UNVERIFIED, do not discard
- **No force push to shared branches**: This step is read-only verification
- **Safe commands only**: All commands are read-only (`git status`, `git diff`, `git log`, etc.)
- **Archive before delete**: Verification only; no deletions performed in this step
<!-- /FRAGMENT: invariants -->

## Error Handling

| Error Type | Handling |
|------------|----------|
| Cannot determine repo root | BLOCKED, `ready_for_work: false` |
| Git commands fail | BLOCKED, `ready_for_work: false` |
| Input reports missing | UNVERIFIED (proceed with available info, note missing reports) |
| Conflicting reports (diagnose vs actual) | UNVERIFIED, document discrepancy |

## Philosophy

This is the **final gate** before returning control to the interrupted flow. The verification must be:

1. **Complete**: Check all aspects of git cleanliness
2. **Honest**: Report actual state, not assumed state
3. **Actionable**: If issues exist, clearly describe what needs fixing
4. **Non-destructive**: Pure verification, no modifications

The goal is to answer: "Is it safe to continue working on this repository?"

If yes -> VERIFIED, return to interrupted flow
If no -> UNVERIFIED, with clear explanation of remaining issues
