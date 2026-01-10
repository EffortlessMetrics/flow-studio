# Flow 8 - Reset (Utility Flow)

Execute Flow 8 (Reset/Rebase) to synchronize your work branch with upstream.

## When to Use

This is a **utility flow** that should be invoked when:
- Your work branch has diverged from upstream (main/master)
- You need to integrate upstream changes before continuing work
- Git status shows you're behind the remote

**Note:** This flow is typically **injected automatically** by the orchestrator during Build/Review/Gate flows when divergence is detected. Direct invocation is for manual sync scenarios.

## Flow Steps

1. **diagnose** - Analyze divergence and identify potential conflicts
2. **stash_wip** - Preserve uncommitted work
3. **sync_upstream** - Fetch upstream changes
4. **resolve_conflicts** - Resolve any merge conflicts (may iterate)
5. **restore_wip** - Restore stashed changes
6. **prune_branches** - Clean up stale branches
7. **archive_run** - Archive run artifacts if needed
8. **verify_clean** - Verify repository is in clean state

## Execution Instructions

When this command is invoked:

1. **Verify Prerequisites**
   - Determine `run-id` from context (current branch name or ticket ID)
   - Set `RUN_BASE = swarm/runs/<run-id>`
   - Ensure `RUN_BASE/reset/` directory exists

2. **Execute Steps in Order**
   Call each agent in sequence, respecting routing decisions:

   ```
   reset-diagnose    → RUN_BASE/reset/divergence_report.md
   reset-stash-wip   → RUN_BASE/reset/stash_manifest.md
   reset-sync-upstream → RUN_BASE/reset/sync_report.md
   reset-resolve-conflicts → RUN_BASE/reset/conflict_resolution.md (may loop)
   reset-restore-wip → RUN_BASE/reset/restore_report.md
   reset-prune-branches → RUN_BASE/reset/prune_report.md
   reset-archive-run → RUN_BASE/reset/archive_manifest.md
   reset-verify-clean → RUN_BASE/reset/reset_receipt.json
   ```

3. **Handle Microloop** (resolve_conflicts step)
   - Loop while status is UNVERIFIED and iterations < 3
   - Exit when VERIFIED or NO_CONFLICTS or max iterations reached

4. **Produce Final Receipt**
   The `reset-verify-clean` agent produces `reset_receipt.json` with:
   - Overall status (VERIFIED/UNVERIFIED/BLOCKED)
   - Per-step status summary
   - Sync summary (commits integrated, conflicts resolved)
   - WIP summary (stash/restore status)
   - Verification results

## Safe Git Commands Only

All git operations must be safe:
- ✅ `git fetch`, `git stash`, `git merge`, `git checkout`, `git branch -d`
- ❌ `git push --force`, `git reset --hard`, `git clean -fd`

## On Failure

If the flow fails:
- Document the failure point in artifacts
- Set overall status to BLOCKED or UNVERIFIED
- **Pause for human intervention** (don't auto-retry)
- The interrupted flow will NOT resume until reset succeeds

## Return Semantics

When invoked via INJECT_FLOW (automatic injection):
- On success: Return to the interrupted step in the original flow
- On failure: Pause execution until human resolves the issue

When invoked directly (manual execution):
- On success: Flow completes, user decides next action
- On failure: Report failure, user decides how to proceed
