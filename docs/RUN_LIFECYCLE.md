# Run Lifecycle

This document describes how runs are created, executed, discovered, and cleaned up in the demo swarm system.

---

## Overview

Runs are the primary unit of SDLC execution. Each run executes one or more flows (signal, plan, build, gate, deploy, wisdom) and stores all artifacts in a dedicated directory under `swarm/runs/<run-id>/`.

A run progresses through three phases:

1. **Birth** - Created by a backend, metadata initialized atomically
2. **Life** - Flows execute, artifacts written, events streamed
3. **End** - Retention policy applied, old/corrupt runs cleaned up

---

## Birth (Run Creation)

### How Runs Start

When a backend's `start(spec: RunSpec)` method is called:

1. A unique `run_id` is generated with format `run-YYYYMMDD-HHMMSS-<random>`
2. The run directory is created at `swarm/runs/<run-id>/`
3. Three files are written atomically:
   - `spec.json` - The RunSpec (flows, backend, initiator, params)
   - `meta.json` - The RunSummary (status, timestamps, artifacts)
   - `events.jsonl` - Initial `run_created` event

### Atomic Writes

All metadata writes use the `_atomic_write_json()` pattern from `swarm/runtime/storage.py`:

```python
# 1. Write to temp file in same directory
fd, tmp_path = tempfile.mkstemp(suffix=".tmp", prefix=path.name + ".", dir=parent)

# 2. Write content and fsync to ensure durability
with os.fdopen(fd, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=indent)
    f.flush()
    os.fsync(f.fileno())

# 3. Atomic rename (POSIX guarantee)
os.replace(tmp_path, path)
```

This pattern prevents partial writes if the process is killed mid-write.

### Thread Safety

Concurrent updates to the same run are protected by per-run locks:

```python
_RUN_LOCKS: Dict[RunId, threading.Lock] = {}

def _get_run_lock(run_id: RunId) -> threading.Lock:
    with _RUN_LOCKS_LOCK:
        if run_id not in _RUN_LOCKS:
            _RUN_LOCKS[run_id] = threading.Lock()
        return _RUN_LOCKS[run_id]
```

Both `update_summary()` and `append_event()` acquire this lock before modifying files.

---

## Life (Run Execution)

### Status Transitions

Runs transition through these statuses:

```
PENDING -> RUNNING -> SUCCEEDED | FAILED | CANCELED
```

The `sdlc_status` field tracks semantic outcome:

- `unknown` - Not yet determined
- `ok` - All flows passed
- `blocked` - Waiting on external input
- `failed` - Flow failed with errors

### Flow Discovery

Flow Studio discovers runs via the `/api/runs` endpoint with pagination:

```
GET /api/runs?limit=100&offset=0
```

Returns:
- `runs[]` - Array of RunSummary objects
- `total_count` - Total runs available
- `has_more` - Whether more pages exist

Runs are sorted with examples first, then active runs by timestamp (newest first).

### Artifact Streaming

During execution, stepwise backends write:

**LLM Transcripts** (`llm/*.jsonl`):
```
RUN_BASE/<flow>/llm/<step>-<agent>-<engine>.jsonl
```
Contains the full conversation (system, user, assistant messages) for each step.

**Receipts** (`receipts/*.json`):
```
RUN_BASE/<flow>/receipts/<step>-<agent>.json
```
Structured summaries of step execution results.

### Event Stream

Events are appended to `events.jsonl` throughout execution:

```jsonl
{"kind": "run_created", "ts": "...", "flow_key": "signal", ...}
{"kind": "run_started", "ts": "...", "flow_key": "signal", ...}
{"kind": "step_start", "ts": "...", "flow_key": "signal", "step_id": "normalize", ...}
{"kind": "step_end", "ts": "...", "flow_key": "signal", "step_id": "normalize", ...}
{"kind": "route_decision", "ts": "...", "from_step": "normalize", "to_step": "frame", ...}
...
{"kind": "run_succeeded", "ts": "...", ...}
```

Event types include:
- `run_created`, `run_started`, `run_succeeded`, `run_failed`
- `flow_start`, `flow_end`
- `step_start`, `step_end`
- `route_decision` (stepwise routing between steps)
- `log` (debug/info messages)

---

## End (Run Cleanup)

### Retention Policy

Run cleanup is governed by `swarm/config/runs_retention.yaml`:

| Setting | Default | Description |
|---------|---------|-------------|
| `default_retention_days` | 30 | Keep runs for this many days |
| `max_count` | 300 | Maximum runs to keep |
| `preserve_examples` | true | Never delete example runs |

### Preserved Patterns

Certain runs are never deleted:

**Named runs:**
- `demo-health-check`
- `demo-run`

**Prefix patterns:**
- `stepwise-*` - Stepwise demo runs
- `baseline-*` - Baseline snapshots

**Tagged runs:**
- Runs with `pinned` or `golden` tags

### Quarantine for Corrupt Runs

Runs with invalid `meta.json` (JSON parse errors, missing required fields) are moved to `swarm/runs/_corrupt/` rather than deleted, allowing manual recovery.

---

## Storage Layout

```
swarm/runs/<run-id>/
  meta.json          # RunSummary: status, timestamps, artifacts map
  spec.json          # RunSpec: flow_keys, backend, initiator, params
  events.jsonl       # RunEvent stream (newline-delimited JSON)
  signal/            # Flow 1 artifacts
    issue_normalized.md
    problem_statement.md
    requirements.md
    ...
  plan/              # Flow 2 artifacts
    adr.md
    contracts.md
    work_plan.md
    ...
  build/             # Flow 3 artifacts
    test_summary.md
    impl_changes_summary.md
    receipts/        # Step receipts
    llm/             # LLM transcripts
    ...
  gate/              # Flow 4 artifacts
  deploy/            # Flow 5 artifacts
  wisdom/            # Flow 6 artifacts
```

### Key Files

**meta.json** (RunSummary):
```json
{
  "id": "run-20251209-120839-8f9in1",
  "spec": { ... },
  "status": "running",
  "sdlc_status": "unknown",
  "created_at": "2025-12-09T12:08:39.514758+00:00Z",
  "updated_at": "2025-12-09T12:08:39.920578+00:00Z",
  "started_at": "2025-12-09T12:08:39.920578+00:00Z",
  "completed_at": null,
  "error": null,
  "artifacts": {},
  "is_exemplar": false,
  "tags": []
}
```

**spec.json** (RunSpec):
```json
{
  "flow_keys": ["signal"],
  "profile_id": null,
  "backend": "claude-step-orchestrator",
  "initiator": "test",
  "params": {
    "title": "Test Claude Stepwise Run"
  }
}
```

---

## Configuration Reference

### runs_retention.yaml

```yaml
version: "1.0"

policy:
  enabled: true
  default_retention_days: 30
  strict_mode: false

runs:
  max_count: 300
  max_total_size_mb: 2000
  preserve:
    named_runs:
      - "demo-health-check"
      - "demo-run"
    prefixes:
      - "stepwise-"
      - "baseline-"
    tags:
      - "pinned"
      - "golden"
  preserve_examples: true

flows:
  signal:
    retention_days: 30
  plan:
    retention_days: 30
  build:
    retention_days: 30
  gate:
    retention_days: 60    # Audit trails kept longer
  deploy:
    retention_days: 60    # Deployment records kept longer
  wisdom:
    retention_days: 60    # Learnings kept longer

features:
  dry_run: false
  log_deletions: true
  archive_before_delete: false
  quarantine_corrupt: true
```

### Environment Overrides

| Variable | Effect |
|----------|--------|
| `SWARM_RUNS_RETENTION_DAYS` | Override `default_retention_days` |
| `SWARM_RUNS_MAX_COUNT` | Override `max_count` |
| `SWARM_RUNS_DRY_RUN` | Set to `1` for dry-run mode |

---

## Make Targets

| Target | Description |
|--------|-------------|
| `make runs-list` | Show run statistics and retention eligibility |
| `make runs-list-v` | Verbose: show individual runs with age/size |
| `make runs-prune-dry` | Preview what would be deleted (dry run) |
| `make runs-prune` | Apply retention policy, delete old runs |
| `make runs-quarantine-dry` | Preview corrupt runs to quarantine |
| `make runs-quarantine` | Move corrupt runs to `_corrupt/` |
| `make runs-clean` | Delete all `run-*` directories (preserves golden examples) |
| `make runs-gc-help` | Show full garbage collection help |

---

## Troubleshooting

### Stale Runs Accumulating

If runs are not being cleaned up:

1. Check retention is enabled:
   ```bash
   grep "enabled:" swarm/config/runs_retention.yaml
   ```

2. Preview what would be deleted:
   ```bash
   make runs-prune-dry
   ```

3. Run cleanup manually:
   ```bash
   make runs-prune
   ```

### Corrupt Metadata

If Flow Studio shows runs as "corrupt" or fails to load:

1. Check for quarantine candidates:
   ```bash
   make runs-quarantine-dry
   ```

2. Move corrupt runs to quarantine:
   ```bash
   make runs-quarantine
   ```

3. Examine corrupt runs manually:
   ```bash
   ls swarm/runs/_corrupt/
   cat swarm/runs/_corrupt/<run-id>/meta.json
   ```

### Flow Studio Lag

If Flow Studio is slow to list runs:

1. Check run count:
   ```bash
   make runs-list
   ```

2. If count exceeds 300, reduce:
   ```bash
   make runs-prune
   ```

3. The `/api/runs` endpoint supports pagination. Use `?limit=50` for faster initial loads.

### Legacy Runs (No meta.json)

Runs created before the RunService may lack metadata. These are detected by `discover_legacy_runs()` and shown with `has_meta: false`. They function normally but lack timing/status data.

---

## See Also

- [FLOW_STUDIO.md](./FLOW_STUDIO.md) - Flow visualization UI
- [STEPWISE_BACKENDS.md](./STEPWISE_BACKENDS.md) - Backend execution details
- `swarm/runtime/storage.py` - Low-level storage functions
- `swarm/runtime/backends.py` - Backend implementations
- `swarm/tools/runs_gc.py` - Garbage collection tool
