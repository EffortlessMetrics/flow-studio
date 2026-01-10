# Epic: Data Plane - Complete Event Sourcing Implementation

## Vision
The Data Plane must implement **pure event sourcing** where `events.jsonl` is the single source of truth and all other state (RunState, DuckDB) is derivable.

## Key Files

```
swarm/runtime/
├── storage.py           # Core storage layer (1270 lines)
│   ├── _atomic_write_json()   # Temp + os.replace pattern
│   ├── append_event()         # Append-only event log
│   ├── write_run_state()      # State persistence
│   └── commit_step_completion() # Atomic envelope + state
├── types/runs.py        # RunState, RunEvent, RunSpec (335 lines)
├── run_tailer.py        # DuckDB projection service
└── db.py                # DuckDB connection management
```

## Current Architecture

```
WRITE PATH (Current):
  Orchestrator
       │
       ├─── append_event() ───► events.jsonl (append-only, atomic)
       │
       └─── write_run_state() ─► run_state.json (INDEPENDENT, NOT derived!)
                                       │
                                       └── Uses _atomic_write_json():
                                           1. tempfile.mkstemp()
                                           2. json.dump() + os.fsync()
                                           3. os.replace() (atomic)

READ PATH:
  events.jsonl ──► RunTailer ──► DuckDB (projection)
                        │
                        └──► UI (via REST API / SSE)
```

## Target Architecture

```
SINGLE WRITE PATH (Target):
  Orchestrator ─── append_event() ───► events.jsonl
                          │
                          ├──► derive_run_state() ──► RunState (cache)
                          │
                          └──► project_to_db() ──► DuckDB

CRASH RECOVERY:
  events.jsonl ──► rebuild_run_state() ──► run_state.json
                          │
                          └──► rebuild_db() ──► DuckDB
```

## Implementation Tasks

### Task 1: Event Schema Formalization (#18)
**Files:** `swarm/schemas/event.schema.json`, `swarm/runtime/storage.py`

```python
# Event types that must be schema-validated:
EVENT_TYPES = [
    "run_started",        # Initialize run
    "step_started",       # Step execution begins
    "step_completed",     # Step finished (with status)
    "route_decision",     # Navigator made routing choice
    "checkpoint",         # Explicit resume point
    "flow_paused",        # Flow temporarily paused
    "run_stopped",        # Orderly shutdown
    "run_completed",      # All flows finished
    "run_failed",         # Unrecoverable error
]
```

### Task 2: RunState Derivation (#9)
**Files:** `swarm/runtime/state_builder.py` (new)

```python
def rebuild_run_state(run_id: RunId) -> RunState:
    """Rebuild RunState by replaying events.jsonl."""
    events = read_events(run_id)
    state = RunState(run_id=run_id, flow_key="", status="pending")

    for event in events:
        if event.kind == "run_started":
            state.flow_key = event.flow_key
            state.status = "running"
        elif event.kind == "step_completed":
            state.step_index = event.payload.get("step_index", 0) + 1
        elif event.kind == "route_decision":
            state.current_step_id = event.payload.get("next_step_id")
        elif event.kind in ("run_stopped", "flow_paused"):
            state.status = "paused"
        elif event.kind == "run_completed":
            state.status = "completed"

    return state
```

### Task 3: Checkpoint Events (#10)
**Files:** `swarm/runtime/storage.py`

```python
def create_checkpoint(run_id: RunId, label: str) -> str:
    """Create named checkpoint for explicit resume point."""
    checkpoint_id = f"cp-{label}-{uuid.uuid4().hex[:8]}"
    append_event(run_id, RunEvent(
        kind="checkpoint",
        payload={"checkpoint_id": checkpoint_id, "label": label},
        step_id=None,
        flow_key=None,
    ))
    return checkpoint_id

def resume_from_checkpoint(run_id: RunId, checkpoint_id: str) -> RunState:
    """Resume run from specific checkpoint, replaying only to that point."""
    events = read_events(run_id)
    state = RunState(run_id=run_id, flow_key="", status="pending")

    for event in events:
        state = _apply_event(state, event)
        if (event.kind == "checkpoint" and
            event.payload.get("checkpoint_id") == checkpoint_id):
            break

    return state
```

### Task 4: Atomic Commit Protocol
**Files:** `swarm/runtime/storage.py`

Existing `commit_step_completion()` needs enhancement:
- Write envelope first (recoverable)
- Append event to events.jsonl
- Update run_state.json (cache only)
- If any step fails, previous steps are durable

### Task 5: Tailer Robustness
**Files:** `swarm/runtime/run_tailer.py`

```python
class RunTailer:
    """Background service that projects events.jsonl to DuckDB."""

    def __init__(self, run_id: RunId, db_path: Path):
        self.run_id = run_id
        self.db = duckdb.connect(str(db_path))
        self._position = 0  # Last read position

    def tail_once(self) -> int:
        """Process new events since last position."""
        events_path = get_events_path(self.run_id)
        new_events = self._read_new_events(events_path)

        for event in new_events:
            self._insert_event(event)

        return len(new_events)
```

## Test Plan

### Unit Tests
```bash
# State derivation
uv run pytest tests/test_state_builder.py -v

# Checkpoint operations
uv run pytest tests/test_checkpoint.py -v

# Event schema validation
uv run pytest tests/test_event_schema.py -v
```

### Integration Tests
```bash
# Crash recovery simulation
uv run pytest tests/integration/test_crash_recovery.py -v

# Concurrent access
uv run pytest tests/integration/test_concurrent_writes.py -v

# Rebuild consistency
uv run pytest tests/integration/test_rebuild_db.py -v
```

### Chaos Tests
```bash
# Random process kills during step execution
make test-chaos-kill

# Filesystem corruption detection
make test-chaos-corrupt

# Verify: events.jsonl → RunState → matches original state
```

## Acceptance Criteria

- [ ] events.jsonl is single source of truth
- [ ] run_state.json is derivable cache only (can be deleted and rebuilt)
- [ ] Crash at any point (SIGKILL) leaves consistent state
- [ ] `--resume <run_id>` picks up exactly at last checkpoint
- [ ] No event can be lost or corrupted silently
- [ ] `make rebuild-db` reconstructs DuckDB from events.jsonl alone

## CLI Commands

```bash
# Resume interrupted run
swarm run --resume abc123

# Rebuild state from events
swarm rebuild-state abc123

# Rebuild DuckDB from events
swarm rebuild-db abc123

# Verify state consistency
swarm verify-state abc123
```

## Related Issues
- #9 Make RunState Rebuildable from Events
- #10 Implement Explicit Resume/Checkpoint API
- #18 Add Event Schema Validation
