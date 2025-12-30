"""
storage.py - Disk I/O helpers for run metadata and events.

This module provides functions for persisting and loading run data from disk.
The storage layout is:

    swarm/runs/
      <run_id>/
        meta.json          # RunSummary serialized
        spec.json          # RunSpec serialized
        events.jsonl       # newline-delimited RunEvent objects
        run_state.json     # RunState serialized (durable program counter)
        <flow_key>/        # existing artifact directories (signal/, plan/, etc.)
          handoff/        # HandoffEnvelope JSON files for each step
            <step_id>.json

Usage:
    from swarm.runtime.storage import (
        RUNS_DIR,
        get_run_path, run_exists, create_run_dir,
        write_spec, read_spec,
        write_summary, read_summary, update_summary, finalize_run_success,
        append_event, read_events,
        query_navigator_events, summarize_navigator_events,  # For Wisdom analysis
        write_run_state, read_run_state, update_run_state,
        write_envelope, read_envelope, list_envelopes,
        commit_step_completion,
        list_runs, discover_legacy_runs,
    )
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from .types import (
    HandoffEnvelope,
    RunEvent,
    RunId,
    RunSpec,
    RunState,
    RunSummary,
    handoff_envelope_from_dict,
    handoff_envelope_to_dict,
    run_event_from_dict,
    run_event_to_dict,
    run_spec_from_dict,
    run_spec_to_dict,
    run_state_from_dict,
    run_state_to_dict,
    run_summary_from_dict,
    run_summary_to_dict,
)

# Module logger
logger = logging.getLogger(__name__)

# Default directories
RUNS_DIR = Path(__file__).parent.parent / "runs"
EXAMPLES_DIR = Path(__file__).parent.parent / "examples"

# File names
META_FILE = "meta.json"
SPEC_FILE = "spec.json"
EVENTS_FILE = "events.jsonl"
RUN_STATE_FILE = "run_state.json"
LEGACY_META_FILE = "run.json"  # Old-style optional metadata

# -----------------------------------------------------------------------------
# Per-run locking for thread safety
# -----------------------------------------------------------------------------
# Backends execute runs in background threads, and update_summary is a
# read-modify-write operation. Without locking, concurrent updates can cause
# lost updates. This provides in-process locking; cross-process locking is
# out of scope for now.

_RUN_LOCKS: Dict[RunId, threading.Lock] = {}
_RUN_LOCKS_LOCK = threading.Lock()

# -----------------------------------------------------------------------------
# Per-run sequence tracking for monotonic event ordering
# -----------------------------------------------------------------------------
# Each run has a monotonically increasing sequence counter that is assigned
# to events before writing. This enables reliable ordering even when timestamps
# have limited precision or clock skew occurs.

_run_sequences: Dict[str, int] = {}
_seq_lock = threading.Lock()


def _next_seq(run_id: str) -> int:
    """Get the next monotonic sequence number for a run.

    Thread-safe counter that increments on each call for a given run_id.
    Sequence numbers start at 1 and increase monotonically.

    Args:
        run_id: The unique run identifier.

    Returns:
        The next sequence number for this run.
    """
    with _seq_lock:
        seq = _run_sequences.get(run_id, 0) + 1
        _run_sequences[run_id] = seq
        return seq


def _init_seq_from_disk(run_id: str, run_dir: Path) -> None:
    """Initialize sequence counter from existing events.jsonl.

    This function handles recovery scenarios where a run is being resumed
    after a restart. It scans existing events to find the highest sequence
    number and initializes the counter to continue from there.

    Args:
        run_id: The unique run identifier.
        run_dir: Path to the run directory.
    """
    events_file = run_dir / EVENTS_FILE
    if not events_file.exists():
        return

    max_seq = 0
    try:
        with open(events_file, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    try:
                        event = json.loads(line)
                        max_seq = max(max_seq, event.get("seq", 0))
                    except json.JSONDecodeError:
                        continue
    except (OSError, IOError):
        pass

    if max_seq > 0:
        with _seq_lock:
            # Only update if disk has higher seq than in-memory
            current = _run_sequences.get(run_id, 0)
            if max_seq > current:
                _run_sequences[run_id] = max_seq
                logger.debug("Recovered sequence counter for run '%s': max_seq=%d", run_id, max_seq)


def _get_run_lock(run_id: RunId) -> threading.Lock:
    """Get or create a lock for a specific run ID.

    Thread-safe lock registry for per-run synchronization.

    Args:
        run_id: The unique run identifier.

    Returns:
        A threading.Lock specific to this run ID.
    """
    with _RUN_LOCKS_LOCK:
        lock = _RUN_LOCKS.get(run_id)
        if lock is None:
            lock = threading.Lock()
            _RUN_LOCKS[run_id] = lock
        return lock


# -----------------------------------------------------------------------------
# Atomic File I/O Helpers
# -----------------------------------------------------------------------------


def _atomic_write_json(path: Path, data: Any, indent: int = 2) -> None:
    """Write JSON data to a file atomically.

    Uses a temporary file + os.replace pattern to ensure atomicity.
    This prevents partial writes if the process is killed mid-write.

    Args:
        path: Destination file path.
        data: JSON-serializable data.
        indent: JSON indentation level.
    """
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)

    # Write to temp file in same directory (ensures same filesystem for rename)
    fd, tmp_path = tempfile.mkstemp(
        suffix=".tmp",
        prefix=path.name + ".",
        dir=parent,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=indent, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())  # Ensure data is on disk

        # Atomic rename (POSIX guarantees)
        os.replace(tmp_path, path)
    except Exception:
        # Clean up temp file on failure
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _load_json_safe(path: Path, run_id: str, file_type: str = "file") -> Optional[Dict[str, Any]]:
    """Load JSON file with graceful error handling.

    Returns None on parse errors instead of raising, to allow callers
    to handle corrupt files gracefully.

    Args:
        path: Path to JSON file.
        run_id: Run identifier for logging.
        file_type: Description of file type for logging (e.g., "summary", "spec").

    Returns:
        Parsed JSON dict, or None if file doesn't exist or is corrupt.
    """
    if not path.exists():
        return None

    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        logger.warning(
            "Corrupt %s for run '%s' at %s: %s (marking as corrupt)", file_type, run_id, path, e
        )
        return None
    except (OSError, IOError) as e:
        logger.warning("Failed to read %s for run '%s' at %s: %s", file_type, run_id, path, e)
        return None


# -----------------------------------------------------------------------------
# Path Helpers
# -----------------------------------------------------------------------------


def get_run_path(run_id: RunId, runs_dir: Path = RUNS_DIR) -> Path:
    """Get the path for a run directory.

    Args:
        run_id: The unique run identifier.
        runs_dir: Base directory for runs. Defaults to RUNS_DIR.

    Returns:
        Path to the run directory.

    Example:
        >>> get_run_path("run-20251208-143022-abc123")
        PosixPath('/path/to/swarm/runs/run-20251208-143022-abc123')
    """
    return runs_dir / run_id


def find_run_path(run_id: RunId) -> Optional[Path]:
    """Find a run's path, checking both runs/ and examples/ directories.

    Checks examples first (committed/curated), then active runs.

    Args:
        run_id: The unique run identifier.

    Returns:
        Path to the run directory, or None if not found.
    """
    # Check examples first (committed, curated)
    example_path = EXAMPLES_DIR / run_id
    if example_path.exists() and example_path.is_dir():
        return example_path

    # Check active runs
    runs_path = RUNS_DIR / run_id
    if runs_path.exists() and runs_path.is_dir():
        return runs_path

    return None


def get_run_type(run_id: RunId) -> Optional[str]:
    """Determine the type of a run (example or active).

    Args:
        run_id: The unique run identifier.

    Returns:
        "example" if in examples/, "active" if in runs/, None if not found.
    """
    example_path = EXAMPLES_DIR / run_id
    if example_path.exists() and example_path.is_dir():
        return "example"

    runs_path = RUNS_DIR / run_id
    if runs_path.exists() and runs_path.is_dir():
        return "active"

    return None


def run_exists(run_id: RunId, runs_dir: Path = RUNS_DIR) -> bool:
    """Check if a run exists on disk.

    A run is considered to exist if its meta.json file exists.

    Args:
        run_id: The unique run identifier.
        runs_dir: Base directory for runs. Defaults to RUNS_DIR.

    Returns:
        True if the run exists (has meta.json), False otherwise.
    """
    run_path = get_run_path(run_id, runs_dir)
    return (run_path / META_FILE).exists()


def create_run_dir(run_id: RunId, runs_dir: Path = RUNS_DIR) -> Path:
    """Create the run directory structure.

    Creates the run directory if it doesn't exist. Does not create
    flow subdirectories (those are created by agents as needed).

    Also initializes the sequence counter from existing events.jsonl if
    present, enabling recovery after restarts.

    Args:
        run_id: The unique run identifier.
        runs_dir: Base directory for runs. Defaults to RUNS_DIR.

    Returns:
        Path to the created run directory.

    Example:
        >>> path = create_run_dir("run-20251208-143022-abc123")
        >>> path.exists()
        True
    """
    run_path = get_run_path(run_id, runs_dir)
    run_path.mkdir(parents=True, exist_ok=True)

    # Initialize sequence counter from disk for recovery scenarios
    _init_seq_from_disk(run_id, run_path)

    return run_path


# -----------------------------------------------------------------------------
# RunSpec I/O
# -----------------------------------------------------------------------------


def write_spec(run_id: RunId, spec: RunSpec, runs_dir: Path = RUNS_DIR) -> Path:
    """Write RunSpec to spec.json atomically.

    Uses atomic write (temp file + rename) to prevent partial writes.

    Args:
        run_id: The unique run identifier.
        spec: The RunSpec to persist.
        runs_dir: Base directory for runs. Defaults to RUNS_DIR.

    Returns:
        Path to the written spec.json file.
    """
    run_path = create_run_dir(run_id, runs_dir)
    spec_path = run_path / SPEC_FILE

    data = run_spec_to_dict(spec)
    _atomic_write_json(spec_path, data)

    return spec_path


def read_spec(run_id: RunId, runs_dir: Path = RUNS_DIR) -> Optional[RunSpec]:
    """Read RunSpec from spec.json with graceful error handling.

    Args:
        run_id: The unique run identifier.
        runs_dir: Base directory for runs. Defaults to RUNS_DIR.

    Returns:
        The RunSpec if it exists and is valid, None otherwise.
    """
    run_path = get_run_path(run_id, runs_dir)
    spec_path = run_path / SPEC_FILE

    data = _load_json_safe(spec_path, run_id, "spec")
    if data is None:
        return None

    try:
        return run_spec_from_dict(data)
    except (KeyError, TypeError) as e:
        logger.warning("Invalid spec data for run '%s' at %s: %s", run_id, spec_path, e)
        return None


# -----------------------------------------------------------------------------
# RunSummary I/O
# -----------------------------------------------------------------------------


def write_summary(run_id: RunId, summary: RunSummary, runs_dir: Path = RUNS_DIR) -> Path:
    """Write RunSummary to meta.json atomically.

    Uses atomic write (temp file + rename) to prevent partial writes.

    Args:
        run_id: The unique run identifier.
        summary: The RunSummary to persist.
        runs_dir: Base directory for runs. Defaults to RUNS_DIR.

    Returns:
        Path to the written meta.json file.
    """
    run_path = create_run_dir(run_id, runs_dir)
    meta_path = run_path / META_FILE

    data = run_summary_to_dict(summary)
    _atomic_write_json(meta_path, data)

    return meta_path


def read_summary(run_id: RunId, runs_dir: Path = RUNS_DIR) -> Optional[RunSummary]:
    """Read RunSummary from meta.json with graceful error handling.

    Returns None for missing or corrupt files, allowing callers to
    skip or quarantine bad runs.

    Args:
        run_id: The unique run identifier.
        runs_dir: Base directory for runs. Defaults to RUNS_DIR.

    Returns:
        The RunSummary if it exists and is valid, None otherwise.
    """
    run_path = get_run_path(run_id, runs_dir)
    meta_path = run_path / META_FILE

    data = _load_json_safe(meta_path, run_id, "summary")
    if data is None:
        return None

    try:
        return run_summary_from_dict(data)
    except (KeyError, TypeError) as e:
        logger.warning("Invalid summary data for run '%s' at %s: %s", run_id, meta_path, e)
        return None


def update_summary(run_id: RunId, updates: Dict[str, Any], runs_dir: Path = RUNS_DIR) -> RunSummary:
    """Partial update of RunSummary fields.

    Reads the existing summary, applies updates, and writes back.
    Only updates fields that are present in the updates dict.

    This function is thread-safe via per-run locking to prevent lost updates
    when multiple threads update the same run concurrently.

    Args:
        run_id: The unique run identifier.
        updates: Dictionary of fields to update. Supports top-level fields
                 like "status", "sdlc_status", "error", "completed_at", etc.
        runs_dir: Base directory for runs. Defaults to RUNS_DIR.

    Returns:
        The updated RunSummary.

    Raises:
        FileNotFoundError: If the run's meta.json doesn't exist.

    Example:
        >>> update_summary("run-123", {"status": "succeeded", "completed_at": "2025-01-08T12:00:00Z"})
    """
    lock = _get_run_lock(run_id)
    with lock:
        summary = read_summary(run_id, runs_dir)
        if summary is None:
            raise FileNotFoundError(f"Run not found: {run_id}")

        # Convert to dict, apply updates, convert back
        data = run_summary_to_dict(summary)

        for key, value in updates.items():
            if key in data:
                data[key] = value

        updated_summary = run_summary_from_dict(data)
        write_summary(run_id, updated_summary, runs_dir)

        return updated_summary


def finalize_run_success(
    run_id: RunId,
    sdlc_status: str = "ok",
    runs_dir: Path = RUNS_DIR,
) -> RunSummary:
    """Finalize a run as succeeded with consistent status updates.

    This is the canonical way to mark a run as successfully completed.
    It ensures that both meta.json and run_state.json are updated
    consistently with the completion timestamp.

    Use this function in backends after all flows complete successfully
    to avoid duplicating status update logic.

    Args:
        run_id: The unique run identifier.
        sdlc_status: The SDLC quality status (default: "ok").
                     Valid values: "ok", "warning", "error", "unknown".
        runs_dir: Base directory for runs. Defaults to RUNS_DIR.

    Returns:
        The updated RunSummary.

    Raises:
        FileNotFoundError: If the run's meta.json doesn't exist.

    Example:
        >>> from swarm.runtime import storage
        >>> storage.finalize_run_success("run-123")
        >>> summary = storage.read_summary("run-123")
        >>> print(summary.status)  # "succeeded"
    """
    from datetime import datetime, timezone
    from .types import RunStatus, SDLCStatus

    now = datetime.now(timezone.utc)

    # Map string to enum value
    sdlc_enum = SDLCStatus.OK
    if sdlc_status == "warning":
        sdlc_enum = SDLCStatus.WARNING
    elif sdlc_status == "error":
        sdlc_enum = SDLCStatus.ERROR
    elif sdlc_status == "unknown":
        sdlc_enum = SDLCStatus.UNKNOWN

    # Update summary with success status
    updated_summary = update_summary(
        run_id,
        {
            "status": RunStatus.SUCCEEDED.value,
            "sdlc_status": sdlc_enum.value,
            "completed_at": now.isoformat(),
            "updated_at": now.isoformat(),
        },
        runs_dir,
    )

    # Also emit a run_completed event for observability
    append_event(
        run_id,
        RunEvent(
            run_id=run_id,
            ts=now,
            kind="run_completed",
            flow_key="",
            payload={
                "status": RunStatus.SUCCEEDED.value,
                "sdlc_status": sdlc_enum.value,
            },
        ),
        runs_dir,
    )

    logger.debug(
        "Finalized run %s as succeeded (sdlc_status=%s)",
        run_id,
        sdlc_status,
    )

    return updated_summary


# -----------------------------------------------------------------------------
# RunEvent I/O (JSONL - newline-delimited JSON)
# -----------------------------------------------------------------------------


def append_event(run_id: RunId, event: RunEvent, runs_dir: Path = RUNS_DIR) -> None:
    """Append a RunEvent to events.jsonl.

    Uses JSONL (newline-delimited JSON) format for append-friendly streaming.
    Creates the file if it doesn't exist.

    This function is thread-safe via per-run locking to ensure atomic appends
    when multiple threads emit events for the same run.

    The storage layer assigns a monotonically increasing sequence number to
    each event before writing. This ensures reliable ordering even when
    timestamps have limited precision.

    Args:
        run_id: The unique run identifier.
        event: The RunEvent to append.
        runs_dir: Base directory for runs. Defaults to RUNS_DIR.
    """
    lock = _get_run_lock(run_id)
    with lock:
        run_path = create_run_dir(run_id, runs_dir)
        events_path = run_path / EVENTS_FILE

        try:
            # Assign monotonic sequence number before serialization
            event.seq = _next_seq(run_id)

            data = run_event_to_dict(event)
            line = json.dumps(data, ensure_ascii=False)

            with open(events_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
                f.flush()  # Ensure data reaches OS buffer
        except (OSError, IOError) as e:
            logger.warning(
                "Failed to append event for run '%s' at %s: %s",
                run_id,
                events_path,
                e,
            )
            # Don't re-raise - event logging is non-critical
        except (TypeError, ValueError) as e:
            logger.warning(
                "Failed to serialize event for run '%s': %s",
                run_id,
                e,
            )
            # Don't re-raise - malformed events shouldn't crash the run


def read_events(run_id: RunId, runs_dir: Path = RUNS_DIR) -> List[RunEvent]:
    """Read all events from events.jsonl.

    Args:
        run_id: The unique run identifier.
        runs_dir: Base directory for runs. Defaults to RUNS_DIR.

    Returns:
        List of RunEvent objects in chronological order.
        Returns empty list if file doesn't exist or is empty.
    """
    run_path = get_run_path(run_id, runs_dir)
    events_path = run_path / EVENTS_FILE

    if not events_path.exists():
        return []

    events: List[RunEvent] = []
    try:
        with open(events_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    events.append(run_event_from_dict(data))
                except (json.JSONDecodeError, KeyError, TypeError):
                    # Skip malformed lines
                    continue
    except OSError:
        return []

    return events


# Navigator event types for Wisdom analysis
NAVIGATOR_EVENT_TYPES = frozenset(
    {
        "graph_patch_suggested",  # EXTEND_GRAPH - map gap detected
        "detour_taken",  # Sidequest invoked
        "navigation_decision",  # Navigator route choice
        "sidequest_start",  # Sidequest execution started
        "sidequest_complete",  # Sidequest finished
        "loop_stall_detected",  # Progress signature unchanged across loops
    }
)


def query_navigator_events(
    run_id: RunId,
    event_types: Optional[List[str]] = None,
    runs_dir: Path = RUNS_DIR,
) -> List[RunEvent]:
    """Query Navigator-related events for Wisdom analysis.

    This function filters events to those relevant for learning:
    - EXTEND_GRAPH (graph_patch_suggested) for Tier 2 flow topology learning
    - DETOUR (detour_taken, sidequest_*) for Tier 1 tactical learning
    - LOOP_STALL for stall detection patterns

    Args:
        run_id: The unique run identifier.
        event_types: Optional list of specific event types to filter.
                     If None, returns all navigator event types.
        runs_dir: Base directory for runs. Defaults to RUNS_DIR.

    Returns:
        List of RunEvent objects matching the criteria.
    """
    all_events = read_events(run_id, runs_dir)

    filter_types = set(event_types) if event_types else NAVIGATOR_EVENT_TYPES

    return [e for e in all_events if e.event_type in filter_types]


def summarize_navigator_events(
    run_id: RunId,
    runs_dir: Path = RUNS_DIR,
) -> Dict[str, Any]:
    """Summarize Navigator events for Wisdom process analysis.

    Returns a structured summary suitable for process-analyst to consume.

    Args:
        run_id: The unique run identifier.
        runs_dir: Base directory for runs. Defaults to RUNS_DIR.

    Returns:
        Dictionary with counts and details for Wisdom analysis:
        - map_gaps: List of EXTEND_GRAPH events with target info
        - detours: List of sidequests invoked with frequency
        - stalls: List of stall detection events
        - tier_summary: Preliminary tier classification
    """
    events = query_navigator_events(run_id, runs_dir=runs_dir)

    # Initialize summary
    summary: Dict[str, Any] = {
        "map_gaps": [],
        "detours": [],
        "stalls": [],
        "tier_summary": {
            "tier1_candidates": 0,
            "tier2_candidates": 0,
            "tier3_candidates": 0,
        },
    }

    # Track sidequest frequency
    sidequest_counts: Dict[str, int] = {}

    for event in events:
        payload = event.payload or {}

        if event.event_type == "graph_patch_suggested":
            summary["map_gaps"].append(
                {
                    "flow_key": event.flow_key,
                    "step_id": event.step_id,
                    "from_node": payload.get("from_node"),
                    "to_node": payload.get("to_node"),
                    "reason": payload.get("reason"),
                    "patch": payload.get("patch"),
                }
            )

        elif event.event_type in ("detour_taken", "sidequest_start"):
            sidequest_id = payload.get("sidequest_id", "unknown")
            sidequest_counts[sidequest_id] = sidequest_counts.get(sidequest_id, 0) + 1

        elif event.event_type == "loop_stall_detected":
            summary["stalls"].append(
                {
                    "flow_key": event.flow_key,
                    "step_id": event.step_id,
                    "consecutive_loops": payload.get("consecutive_loops"),
                    "progress_signature": payload.get("progress_signature"),
                }
            )

    # Build detour summary with frequency
    for sidequest_id, count in sidequest_counts.items():
        summary["detours"].append(
            {
                "sidequest_id": sidequest_id,
                "invocation_count": count,
            }
        )

    # Preliminary tier classification
    # Tier 2: 3+ occurrences of same map gap pattern
    summary["tier_summary"]["tier2_candidates"] = len(summary["map_gaps"])
    summary["tier_summary"]["tier1_candidates"] = len(summary["detours"])

    return summary


# -----------------------------------------------------------------------------
# Run Listing
# -----------------------------------------------------------------------------


def list_runs(runs_dir: Path = RUNS_DIR) -> List[RunId]:
    """List all run IDs that have meta.json files.

    Only returns runs that have been properly initialized with a meta.json.
    Sorted by run ID (which includes timestamp for chronological ordering).

    Args:
        runs_dir: Base directory for runs. Defaults to RUNS_DIR.

    Returns:
        List of run IDs with meta.json files, sorted alphabetically.
    """
    if not runs_dir.exists():
        return []

    run_ids: List[RunId] = []
    for entry in runs_dir.iterdir():
        if entry.is_dir() and (entry / META_FILE).exists():
            run_ids.append(entry.name)

    return sorted(run_ids)


def discover_legacy_runs(runs_dir: Path = RUNS_DIR) -> List[RunId]:
    """Find runs that have flow artifacts but no meta.json (legacy runs).

    Legacy runs are directories under runs/ that contain flow subdirectories
    (signal/, plan/, build/, etc.) but lack a meta.json file. These were
    created before the RunService was introduced.

    Args:
        runs_dir: Base directory for runs. Defaults to RUNS_DIR.

    Returns:
        List of run IDs that appear to be legacy runs.
    """
    if not runs_dir.exists():
        return []

    # Known flow keys that indicate a valid run directory
    flow_keys = {"signal", "plan", "build", "gate", "deploy", "wisdom"}

    legacy_runs: List[RunId] = []
    for entry in runs_dir.iterdir():
        if not entry.is_dir():
            continue

        # Skip if already has meta.json (not legacy)
        if (entry / META_FILE).exists():
            continue

        # Check if any flow subdirectory exists
        has_flow_artifacts = any((entry / flow_key).is_dir() for flow_key in flow_keys)

        if has_flow_artifacts:
            legacy_runs.append(entry.name)

    return sorted(legacy_runs)


def discover_example_runs() -> List[RunId]:
    """Find curated example runs in swarm/examples/.

    Example runs are committed to the repo for teaching/demonstration.
    They are always treated as legacy (no meta.json expected).

    Returns:
        List of run IDs from examples/, sorted alphabetically.
    """
    if not EXAMPLES_DIR.exists():
        return []

    # Known flow keys that indicate a valid run directory
    flow_keys = {"signal", "plan", "build", "gate", "deploy", "wisdom"}

    example_runs: List[RunId] = []
    for entry in EXAMPLES_DIR.iterdir():
        if not entry.is_dir() or entry.name.startswith("."):
            continue

        # Check if any flow subdirectory exists
        has_flow_artifacts = any((entry / flow_key).is_dir() for flow_key in flow_keys)

        if has_flow_artifacts:
            example_runs.append(entry.name)

    return sorted(example_runs)


def list_all_runs(include_examples: bool = True) -> List[Dict[str, Any]]:
    """List all known runs with their metadata.

    Returns unified list of runs from both runs/ and examples/ directories,
    with type and basic metadata for each.

    Args:
        include_examples: Whether to include example runs. Defaults to True.

    Returns:
        List of dicts with run_id, run_type, path, and has_meta fields.
        Sorted with examples first, then active runs alphabetically.
    """
    results: List[Dict[str, Any]] = []
    seen: set[str] = set()

    # Examples first (curated, committed)
    if include_examples:
        for run_id in discover_example_runs():
            if run_id in seen:
                continue
            seen.add(run_id)
            run_path = EXAMPLES_DIR / run_id
            results.append(
                {
                    "run_id": run_id,
                    "run_type": "example",
                    "path": str(run_path),
                    "has_meta": (run_path / META_FILE).exists(),
                }
            )

    # New-style runs with meta.json
    for run_id in list_runs():
        if run_id in seen:
            continue
        seen.add(run_id)
        run_path = RUNS_DIR / run_id
        results.append(
            {
                "run_id": run_id,
                "run_type": "active",
                "path": str(run_path),
                "has_meta": True,
            }
        )

    # Legacy runs without meta.json
    for run_id in discover_legacy_runs():
        if run_id in seen:
            continue
        seen.add(run_id)
        run_path = RUNS_DIR / run_id
        results.append(
            {
                "run_id": run_id,
                "run_type": "active",
                "path": str(run_path),
                "has_meta": False,
            }
        )

    # Sort: examples first, then by run_id
    results.sort(key=lambda r: (0 if r["run_type"] == "example" else 1, r["run_id"]))
    return results


# -----------------------------------------------------------------------------
# RunState I/O (for durable program counter)
# -----------------------------------------------------------------------------


def write_run_state(run_id: RunId, state: RunState, runs_dir: Path = RUNS_DIR) -> Path:
    """Write RunState to run_state.json atomically.

    Uses atomic write (temp file + rename) to prevent partial writes.

    Args:
        run_id: The unique run identifier.
        state: The RunState to persist.
        runs_dir: Base directory for runs. Defaults to RUNS_DIR.

    Returns:
        Path to the written run_state.json file.
    """
    run_path = create_run_dir(run_id, runs_dir)
    state_path = run_path / RUN_STATE_FILE

    data = run_state_to_dict(state)
    _atomic_write_json(state_path, data)

    return state_path


def read_run_state(run_id: RunId, runs_dir: Path = RUNS_DIR) -> Optional[RunState]:
    """Read RunState from run_state.json with graceful error handling.

    Includes crash recovery logic: if handoff_envelopes is empty but envelope
    files exist on disk, reconstructs the envelope map from the files. This
    handles the case where the process crashed after writing envelope files
    but before updating run_state.json.

    Args:
        run_id: The unique run identifier.
        runs_dir: Base directory for runs. Defaults to RUNS_DIR.

    Returns:
        The RunState if it exists and is valid, None otherwise.
    """
    run_path = get_run_path(run_id, runs_dir)
    state_path = run_path / RUN_STATE_FILE

    data = _load_json_safe(state_path, run_id, "run_state")
    if data is None:
        return None

    try:
        state = run_state_from_dict(data)

        # Crash recovery: reconstruct handoff_envelopes from disk if empty
        if not state.handoff_envelopes and state.flow_key:
            disk_envelopes = list_envelopes(run_id, state.flow_key, runs_dir)
            if disk_envelopes:
                logger.info(
                    "Recovered %d envelope(s) from disk for run '%s' flow '%s'",
                    len(disk_envelopes),
                    run_id,
                    state.flow_key,
                )
                state.handoff_envelopes.update(disk_envelopes)

        return state
    except (KeyError, TypeError) as e:
        logger.warning("Invalid run_state data for run '%s' at %s: %s", run_id, state_path, e)
        return None


def update_run_state(run_id: RunId, updates: Dict[str, Any], runs_dir: Path = RUNS_DIR) -> RunState:
    """Partial update of RunState fields.

    Reads the existing state, applies updates, and writes back.
    Only updates fields that are present in the updates dict.

    This function is thread-safe via per-run locking to prevent lost updates
    when multiple threads update the same run concurrently.

    Args:
        run_id: The unique run identifier.
        updates: Dictionary of fields to update. Supports top-level fields
                 like "current_step_id", "step_index", "status", etc.
        runs_dir: Base directory for runs. Defaults to RUNS_DIR.

    Returns:
        The updated RunState.

    Raises:
        FileNotFoundError: If the run's run_state.json doesn't exist.
    """
    lock = _get_run_lock(run_id)
    with lock:
        state = read_run_state(run_id, runs_dir)
        if state is None:
            raise FileNotFoundError(f"Run state not found: {run_id}")

        # Convert to dict, apply updates, convert back
        data = run_state_to_dict(state)

        for key, value in updates.items():
            if key in data:
                data[key] = value

        updated_state = run_state_from_dict(data)
        write_run_state(run_id, updated_state, runs_dir)

        return updated_state


# -----------------------------------------------------------------------------
# HandoffEnvelope I/O (for per-step handoff artifacts)
# -----------------------------------------------------------------------------


def write_envelope(
    run_id: RunId,
    flow_key: str,
    step_id: str,
    envelope: HandoffEnvelope,
    runs_dir: Path = RUNS_DIR,
) -> Path:
    """Write HandoffEnvelope to handoff/<step_id>.json atomically.

    Uses atomic write (temp file + rename) to prevent partial writes.
    The envelope is written to: .runs/<run_id>/<flow_key>/handoff/<step_id>.json

    Args:
        run_id: The unique run identifier.
        flow_key: The flow key (e.g., "signal", "build").
        step_id: The step identifier.
        envelope: The HandoffEnvelope to persist.
        runs_dir: Base directory for runs. Defaults to RUNS_DIR.

    Returns:
        Path to the written envelope JSON file.
    """
    run_path = get_run_path(run_id, runs_dir)
    flow_path = run_path / flow_key
    handoff_dir = flow_path / "handoff"
    envelope_path = handoff_dir / f"{step_id}.json"

    # Create handoff directory if it doesn't exist
    handoff_dir.mkdir(parents=True, exist_ok=True)

    data = handoff_envelope_to_dict(envelope)
    _atomic_write_json(envelope_path, data)

    return envelope_path


def read_envelope(
    run_id: RunId,
    flow_key: str,
    step_id: str,
    runs_dir: Path = RUNS_DIR,
) -> Optional[HandoffEnvelope]:
    """Read HandoffEnvelope from handoff/<step_id>.json with graceful error handling.

    Args:
        run_id: The unique run identifier.
        flow_key: The flow key (e.g., "signal", "build").
        step_id: The step identifier.
        runs_dir: Base directory for runs. Defaults to RUNS_DIR.

    Returns:
        The HandoffEnvelope if it exists and is valid, None otherwise.
    """
    run_path = get_run_path(run_id, runs_dir)
    flow_path = run_path / flow_key
    envelope_path = flow_path / "handoff" / f"{step_id}.json"

    data = _load_json_safe(envelope_path, run_id, "envelope")
    if data is None:
        return None

    try:
        return handoff_envelope_from_dict(data)
    except (KeyError, TypeError) as e:
        logger.warning(
            "Invalid envelope data for run '%s', step '%s' at %s: %s",
            run_id,
            step_id,
            envelope_path,
            e,
        )
        return None


def list_envelopes(
    run_id: RunId,
    flow_key: str,
    runs_dir: Path = RUNS_DIR,
) -> Dict[str, HandoffEnvelope]:
    """Read all HandoffEnvelope objects for a flow.

    Args:
        run_id: The unique run identifier.
        flow_key: The flow key (e.g., "signal", "build").
        runs_dir: Base directory for runs. Defaults to RUNS_DIR.

    Returns:
        Dictionary mapping step_id to HandoffEnvelope for all envelopes found.
        Returns empty dict if no envelopes exist.
    """
    run_path = get_run_path(run_id, runs_dir)
    flow_path = run_path / flow_key
    handoff_dir = flow_path / "handoff"

    if not handoff_dir.exists():
        return {}

    envelopes: Dict[str, HandoffEnvelope] = {}
    for entry in handoff_dir.iterdir():
        if not entry.is_file() or not entry.suffix == ".json":
            continue

        step_id = entry.stem
        envelope = read_envelope(run_id, flow_key, step_id, runs_dir)
        if envelope:
            envelopes[step_id] = envelope

    return envelopes


# -----------------------------------------------------------------------------
# Atomic Step Completion Protocol
# -----------------------------------------------------------------------------


def commit_step_completion(
    run_id: RunId,
    flow_key: str,
    envelope: HandoffEnvelope,
    run_state_updates: Dict[str, Any],
    runs_dir: Path = RUNS_DIR,
) -> None:
    """Atomic commit of step completion: envelope + run_state update.

    This function ensures durability of step completion by following a
    specific order of operations:

    1. Write envelope to <flow>/handoff/<step_id>.json (immutable once written)
    2. Update run_state.json with envelope reference + step_index bump

    This ordering ensures that if the process crashes between steps, we can
    recover by reading envelopes from disk and reconstructing the
    run_state.handoff_envelopes map. The envelope files serve as the
    durable source of truth.

    Thread-safe via per-run locking.

    Args:
        run_id: The unique run identifier.
        flow_key: The flow key (e.g., "signal", "build").
        envelope: The HandoffEnvelope to persist.
        run_state_updates: Dictionary of fields to update in run_state.json.
            Typically includes "step_index", "current_step_id", "status", etc.
            The envelope reference is automatically added to handoff_envelopes.
        runs_dir: Base directory for runs. Defaults to RUNS_DIR.

    Raises:
        FileNotFoundError: If the run's run_state.json doesn't exist.

    Example:
        >>> commit_step_completion(
        ...     run_id="run-20251208-143022-abc123",
        ...     flow_key="build",
        ...     envelope=my_envelope,
        ...     run_state_updates={
        ...         "step_index": 3,
        ...         "current_step_id": "4",
        ...         "status": "running",
        ...     },
        ... )
    """
    lock = _get_run_lock(run_id)
    with lock:
        # Step 1: Write envelope to disk (immutable artifact)
        step_id = envelope.step_id
        write_envelope(run_id, flow_key, step_id, envelope, runs_dir)

        # Step 2: Read current run_state
        state = read_run_state(run_id, runs_dir)
        if state is None:
            raise FileNotFoundError(f"Run state not found: {run_id}")

        # Step 3: Build updated state with envelope reference
        data = run_state_to_dict(state)

        # Add envelope to handoff_envelopes map
        if "handoff_envelopes" not in data:
            data["handoff_envelopes"] = {}
        data["handoff_envelopes"][step_id] = handoff_envelope_to_dict(envelope)

        # Apply caller-provided updates
        for key, value in run_state_updates.items():
            if key in data:
                data[key] = value

        # Update timestamp (using datetime from .types module via run_state_from_dict)
        from datetime import datetime as dt
        from datetime import timezone as tz

        data["timestamp"] = dt.now(tz.utc).isoformat() + "Z"

        # Step 4: Write updated run_state atomically
        updated_state = run_state_from_dict(data)
        write_run_state(run_id, updated_state, runs_dir)
