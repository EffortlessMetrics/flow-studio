# Epic: Execution Engine - Shadow Fork and Safety

## Vision
Implement the Vacuum Chamber physics: agents execute in complete isolation, unable to affect production until explicitly bridged in Flow 6.

## Current State (Dangerous)

- Agent -> Bash/Edit/Write -> REAL FILESYSTEM
- No isolation layer
- sandbox_enabled = False
- Full host access

## Target Architecture (Safe)

- Agent -> ShadowFork -> Isolated Branch
- Flow 6 Bridge -> Production
- Git worktree isolation
- Automatic rollback on failure

## Implementation Tasks

### Task 1: Shadow Fork Infrastructure (#7)
Create swarm/runtime/shadow_fork.py:
- ShadowFork class with create(), get_cwd(), get_diff()
- commit_checkpoint() for rollback points
- rollback_to() for recovery
- bridge_to_main() for Flow 6 only
- destroy() for cleanup

### Task 2: Engine Integration
Update session_runner.py to use shadow fork working directory.
Create checkpoints before each step.
Rollback on failure.

### Task 3: Orchestrator Integration
Create shadow fork for entire run.
Pass shadow fork to step execution.
Cleanup on completion.

### Task 4: Flow 6 Bridge
Create ProductionBridge class.
Verify changes match Gate audit.
Create PR from shadow branch.

### Task 5: Rollback Semantics
Create RollbackManager class.
Manage rollback points per step.
Enable step-level rollback.

### Task 6: Capability-Based Tool Policy
Extend tool policy with shadow fork awareness.
Constrain file operations to shadow fork.
Block git push from shadow.

## Acceptance Criteria

- [ ] Shadow fork created for each run
- [ ] All file ops constrained to shadow fork
- [ ] Rollback on step failure automatic
- [ ] Flow 6 is only bridge to production
- [ ] Cleanup automatic on completion

## Related Issues
- #7 Shadow Fork Isolation
- #21 Amnesia Protocol Documentation
