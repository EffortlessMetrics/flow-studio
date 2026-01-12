# Epic: Flow Completeness - All 8 Flows Operational

## Vision
Complete implementation of all 8 flows with full traceability.

## Flow Status Matrix

| Flow | Spec | Agents | Status |
|------|------|--------|--------|
| 1. Signal | OK | 6/6 | Complete |
| 2. Plan | OK | 8/8 | AC Matrix Gap |
| 3. Build | OK | 9/9 | Complete |
| 4. Review | OK | 11/11 | Examples Missing |
| 5. Gate | OK | 6/6 | Complete |
| 6. Deploy | OK | 3/3 | Complete |
| 7. Wisdom | OK | 13/13 | Complete |
| 8. Reset | OK | 0/8 | Agents Missing |

## Implementation Tasks

### Task 1: AC Matrix Generation (#14)
Create ac-matrix-author agent to generate acceptance criteria matrix.
Links requirements to test coverage.

### Task 2: Flow 8 Reset Agents (#13)
Implement 8 agents:
- reset-diagnose
- reset-stash-wip
- reset-sync-upstream
- reset-resolve-conflicts
- reset-restore-wip
- reset-prune-branches
- reset-archive-run
- reset-verify-clean

### Task 3: Review Flow Examples (#20)
Create complete example artifacts for review flow.

### Task 4: Traceability Chain Validation
Create validation tool for REQ -> AC -> Test chain.

## Acceptance Criteria

- [ ] Flow 8 all 8 agents implemented
- [ ] AC Matrix generated in Flow 2
- [ ] Review examples complete
- [ ] Traceability validation passes

## Related Issues
- #13 Flow 8 Reset Agents
- #14 AC Matrix Generation
- #20 Review Flow Examples
