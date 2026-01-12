# Epic: Routing System - Complete Candidate-Set Navigation

## Vision
Implement the Constitutional Separation of Powers for routing:
- Python Kernel (Legislative/Executive): Generates candidate sets, enforces topology
- Navigator LLM (Judicial): Interprets context, selects from candidates
- Disk (Historical Record): Immutable audit trail

## Current State vs Target

| Component | Status | Gap |
|-----------|--------|-----|
| DiffScanner | Complete | None |
| TestParser | Complete | None |
| ForensicComparator | Complete | Needs confidence score |
| ProgressTracker | Referenced | Not fully wired to driver |
| FlowGraph | Complete | No macro-level validation |
| RoutingCandidate | Complete | None |
| SidequestCatalog | **6 defaults exist** | Not wired to routing driver |
| EXTEND_GRAPH | Types exist | No persistence layer |
| InterruptionStack | Complete | None |

## Key Files

```
swarm/runtime/
├── types/routing.py        # RoutingSignal, RoutingCandidate (725 lines)
├── navigator.py            # LLM-based navigation
├── macro_navigator.py      # Between-flow routing
├── sidequest_catalog.py    # 6 default sidequests (715 lines)
├── forensic_types.py       # ForensicVerdict, EvidenceBundle
├── forensic_comparator.py  # Narrative vs Evidence comparison
├── diff_scanner.py         # Git diff analysis
├── test_parser.py          # Test output parsing
└── stepwise/
    └── routing/driver.py   # Unified routing driver
```

## Existing Sidequests (in DEFAULT_SIDEQUESTS)

| ID | Station | Trigger | Priority |
|----|---------|---------|----------|
| `clarifier` | clarifier | has_ambiguity OR stall_count >= 2 | 70 |
| `env-doctor` | fixer | failure_type == "environment" | 80 |
| `test-triage` | test-critic | !verification_passed AND same_failure | 60 |
| `security-audit` | security-scanner | path matches auth/*, security/* | 90 |
| `contract-check` | contract-enforcer | path matches api/*, schema* | 75 |
| `context-refresh` | context-loader | stall_count >= 3 | 55 |

## Implementation Tasks

### Task 1: Wire SidequestCatalog to Routing Driver (#12)
**Status:** Sidequests exist in `DEFAULT_SIDEQUESTS`, need to wire to routing driver.

```python
# In routing driver, add:
from swarm.runtime.sidequest_catalog import load_default_catalog, sidequests_to_navigator_options

catalog = load_default_catalog()
applicable = catalog.get_applicable_sidequests(context, run_id=run_state.run_id)

# Add to candidate set:
for sq in applicable:
    candidates.append(RoutingCandidate(
        candidate_id=f"detour:{sq.sidequest_id}",
        action="detour",
        target_node=sq.get_station_id(),
        priority=sq.priority,
        source="detour_catalog",
    ))
```

### Task 2: EXTEND_GRAPH Persistence (#11)
**Files:** `swarm/runtime/storage.py`, new `swarm/runtime/graph_proposals.py`

```python
def persist_graph_proposal(run_id: RunId, proposal: GraphExtensionProposal) -> Path:
    proposals_dir = get_run_path(run_id) / "routing" / "proposals"
    proposals_dir.mkdir(parents=True, exist_ok=True)
    path = proposals_dir / f"{proposal.proposal_id}.json"
    _atomic_write_json(path, proposal.to_dict())
    return path
```

### Task 3: MacroFlow Graph Validation (#16)
**Files:** `swarm/runtime/macro_navigator.py`

Define valid flow-to-flow transitions:
- signal -> plan -> build -> review -> gate -> deploy -> wisdom
- Flow 8 (reset) can be injected from Flow 3 when upstream diverges

### Task 4: Forensic Confidence Score (#19)
**Files:** `swarm/runtime/forensic_types.py`

Add numeric 0.0-1.0 confidence to ForensicVerdict:
- 1.0: All tests pass, diff matches narrative
- 0.5: Partial match, some concerns
- 0.0: Complete mismatch (reward hacking)

### Task 5: Progress Tracker Integration (#22)
**Files:** `swarm/runtime/progress_tracker.py` (new)

```python
@dataclass
class ProgressTracker:
    error_signatures: List[str] = field(default_factory=list)

    def record_iteration(self, error_signature: str) -> None:
        self.error_signatures.append(error_signature)

    def is_stalled(self, window: int = 3) -> bool:
        if len(self.error_signatures) < window:
            return False
        return len(set(self.error_signatures[-window:])) == 1
```

## Acceptance Criteria

- [x] 6 default sidequests defined (**DONE** in `DEFAULT_SIDEQUESTS`)
- [ ] Sidequests wired to routing driver candidate generation
- [ ] EXTEND_GRAPH proposals persisted to `RUN_BASE/routing/proposals/`
- [ ] MacroFlow graph validates flow-to-flow transitions
- [ ] Forensic confidence is numeric 0.0-1.0
- [ ] Stall detection triggers after configurable window (default: 3)

## Test Plan

```bash
# Unit tests
uv run pytest tests/test_sidequest_catalog.py -v
uv run pytest tests/test_routing_driver.py -v

# Integration tests
make stepwise-sdlc-stub  # Verify routing decisions logged
```

## Related Issues
- #11 EXTEND_GRAPH Persistence
- #12 Wire SidequestCatalog to Driver
- #16 MacroFlow Graph Validation
- #19 Forensic Confidence Score
- #22 Progress Tracker Integration
