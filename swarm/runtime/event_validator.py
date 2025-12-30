"""
event_validator.py - Event stream contract validation

Validates event streams against the v1 contract:
- Monotonic (run_id, seq) ordering - no duplicates, no regressions
- Required lifecycle events present (run_created/run_started)
- Step lifecycle pairing (start → end|error)
- Tool pairing (if tool_use_id available)

Usage:
    from swarm.runtime.event_validator import validate_event_stream

    violations = validate_event_stream(run_id, events)
    if violations:
        for v in violations:
            print(f"[{v.kind}] {v.message}")

CLI:
    python -m swarm.runtime.db doctor <run_id>
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set

from .db import normalize_event_kind

if TYPE_CHECKING:
    from .db import StatsDB

logger = logging.getLogger(__name__)


@dataclass
class EventContractViolation:
    """A violation of the event contract.

    Attributes:
        run_id: The run where the violation occurred.
        kind: Type of violation (ordering, missing_event, pairing, schema).
        message: Human-readable description of the violation.
        event_id: The event_id of the problematic event (if applicable).
        seq: The sequence number of the problematic event (if applicable).
        severity: Either "error" (contract broken) or "warning" (anomaly).
    """

    run_id: str
    kind: str  # "ordering", "missing_event", "pairing", "schema"
    message: str
    event_id: Optional[str] = None
    seq: Optional[int] = None
    severity: str = "error"  # "error" or "warning"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result = {
            "run_id": self.run_id,
            "kind": self.kind,
            "message": self.message,
            "severity": self.severity,
        }
        if self.event_id:
            result["event_id"] = self.event_id
        if self.seq is not None:
            result["seq"] = self.seq
        return result


def validate_event_stream(
    run_id: str,
    events: List[Dict[str, Any]],
    strict: bool = False,
) -> List[EventContractViolation]:
    """Validate event stream against v1 contract.

    Checks:
    1. Monotonic seq ordering (no duplicates, warns on gaps)
    2. Required lifecycle events (run_created or run_started)
    3. Step lifecycle pairing (start → end|error)
    4. Tool pairing (tool_start → tool_end, if tool_use_id available)

    Args:
        run_id: The run identifier.
        events: List of event dicts (from events.jsonl or DB).
        strict: If True, warnings become errors.

    Returns:
        List of violations found. Empty list means valid.
    """
    violations: List[EventContractViolation] = []

    if not events:
        return violations

    # === 1. Monotonic seq ordering ===
    seen_seqs: Set[int] = set()
    prev_seq = -1

    for event in events:
        seq = event.get("seq", 0)
        event_id = event.get("event_id", "?")

        # Check for duplicates
        if seq in seen_seqs:
            violations.append(
                EventContractViolation(
                    run_id=run_id,
                    kind="ordering",
                    message=f"Duplicate seq: {seq}",
                    event_id=event_id,
                    seq=seq,
                )
            )
        seen_seqs.add(seq)

        # Check for gaps (warning, not error - can happen on crash recovery)
        if seq > 0 and prev_seq >= 0 and seq != prev_seq + 1:
            gap_size = seq - prev_seq - 1
            violations.append(
                EventContractViolation(
                    run_id=run_id,
                    kind="ordering",
                    message=f"Seq gap: expected {prev_seq + 1}, got {seq} (gap of {gap_size})",
                    seq=seq,
                    severity="warning" if not strict else "error",
                )
            )

        # Check for regression (seq going backwards)
        if seq > 0 and prev_seq > 0 and seq < prev_seq:
            violations.append(
                EventContractViolation(
                    run_id=run_id,
                    kind="ordering",
                    message=f"Seq regression: {prev_seq} → {seq}",
                    event_id=event_id,
                    seq=seq,
                )
            )

        prev_seq = seq

    # === 2. Required lifecycle events ===
    # Normalize event kinds to canonical forms for consistent checking
    kinds = {normalize_event_kind(e.get("kind", "")) for e in events}

    # run_created or run_started should exist (canonical names)
    if "run_created" not in kinds and "run_started" not in kinds:
        violations.append(
            EventContractViolation(
                run_id=run_id,
                kind="missing_event",
                message="Missing run_created/run_started event",
                severity="warning" if not strict else "error",
            )
        )

    # === 3. Step lifecycle pairing ===
    step_starts: Dict[str, Dict[str, Any]] = {}  # step_id -> start event
    step_ends: Set[str] = set()  # step_ids with end/error

    for event in events:
        kind = normalize_event_kind(event.get("kind", ""))
        step_id = event.get("step_id")
        event_id = event.get("event_id", "?")

        if kind == "step_start" and step_id:
            if step_id in step_starts and step_id not in step_ends:
                # Double start without end
                violations.append(
                    EventContractViolation(
                        run_id=run_id,
                        kind="pairing",
                        message=f"step_start for '{step_id}' without prior step_end",
                        event_id=event_id,
                    )
                )
            step_starts[step_id] = event

        elif kind == "step_end" and step_id:  # Canonical: step_complete/step_error -> step_end
            step_ends.add(step_id)
            if step_id not in step_starts:
                violations.append(
                    EventContractViolation(
                        run_id=run_id,
                        kind="pairing",
                        message=f"step_end for '{step_id}' without step_start",
                        event_id=event_id,
                    )
                )

    # Check for orphan starts (started but never ended)
    # Only flag if run is complete (use canonical name after normalization)
    run_complete = "run_completed" in kinds
    if run_complete:
        orphan_starts = set(step_starts.keys()) - step_ends
        for step_id in orphan_starts:
            start_event = step_starts[step_id]
            violations.append(
                EventContractViolation(
                    run_id=run_id,
                    kind="pairing",
                    message=f"step_start for '{step_id}' without step_end (run is complete)",
                    event_id=start_event.get("event_id"),
                    severity="warning" if not strict else "error",
                )
            )

    # === 4. Tool pairing (optional - only if tool_use_id available) ===
    tool_starts: Dict[str, Dict[str, Any]] = {}  # tool_use_id -> start event
    tool_ends: Set[str] = set()

    for event in events:
        kind = normalize_event_kind(event.get("kind", ""))
        payload = event.get("payload", {})
        tool_use_id = payload.get("tool_use_id")
        event_id = event.get("event_id", "?")

        if tool_use_id:
            if kind == "tool_start":
                tool_starts[tool_use_id] = event
            elif kind == "tool_end":
                tool_ends.add(tool_use_id)
                if tool_use_id not in tool_starts:
                    violations.append(
                        EventContractViolation(
                            run_id=run_id,
                            kind="pairing",
                            message=f"tool_end for '{tool_use_id}' without tool_start",
                            event_id=event_id,
                            severity="warning",
                        )
                    )

    # Check for orphan tool starts (only if run complete and we have any tool tracking)
    if run_complete and tool_starts:
        orphan_tool_starts = set(tool_starts.keys()) - tool_ends
        for tool_use_id in orphan_tool_starts:
            start_event = tool_starts[tool_use_id]
            violations.append(
                EventContractViolation(
                    run_id=run_id,
                    kind="pairing",
                    message=f"tool_start for '{tool_use_id}' without tool_end (run is complete)",
                    event_id=start_event.get("event_id"),
                    severity="warning",
                )
            )

    return violations


def validate_run_from_disk(
    run_id: str,
    runs_dir: Path,
    strict: bool = False,
) -> List[EventContractViolation]:
    """Validate events for a run from events.jsonl on disk.

    Args:
        run_id: The run identifier.
        runs_dir: Base directory containing runs.
        strict: If True, warnings become errors.

    Returns:
        List of violations found.
    """
    events_file = runs_dir / run_id / "events.jsonl"

    if not events_file.exists():
        return [
            EventContractViolation(
                run_id=run_id,
                kind="schema",
                message=f"events.jsonl not found: {events_file}",
            )
        ]

    events: List[Dict[str, Any]] = []
    try:
        with events_file.open("r", encoding="utf-8") as f:
            for line_no, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError as e:
                    # Malformed JSON is a validation error
                    return [
                        EventContractViolation(
                            run_id=run_id,
                            kind="schema",
                            message=f"Malformed JSON at line {line_no}: {e}",
                        )
                    ]
    except (OSError, IOError) as e:
        return [
            EventContractViolation(
                run_id=run_id,
                kind="schema",
                message=f"Failed to read events.jsonl: {e}",
            )
        ]

    return validate_event_stream(run_id, events, strict)


def validate_run_from_db(
    run_id: str,
    db: "StatsDB",
    strict: bool = False,
) -> List[EventContractViolation]:
    """Validate events for a run from DuckDB.

    Args:
        run_id: The run identifier.
        db: StatsDB instance.
        strict: If True, warnings become errors.

    Returns:
        List of violations found.
    """
    if db.connection is None:
        return [
            EventContractViolation(
                run_id=run_id,
                kind="schema",
                message="Database not available",
            )
        ]

    # Query raw events ordered by seq
    try:
        result = db.connection.execute(
            """
            SELECT event_id, seq, kind, step_id, payload
            FROM events
            WHERE run_id = ?
            ORDER BY seq
            """,
            [run_id],
        ).fetchall()
    except Exception as e:
        return [
            EventContractViolation(
                run_id=run_id,
                kind="schema",
                message=f"Failed to query events: {e}",
            )
        ]

    if not result:
        return [
            EventContractViolation(
                run_id=run_id,
                kind="missing_event",
                message=f"No events found in database for run {run_id}",
                severity="warning",
            )
        ]

    events = []
    for row in result:
        event_id, seq, kind, step_id, payload = row
        # Handle payload - it might be a string or already a dict
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except (json.JSONDecodeError, TypeError):
                payload = {}
        elif payload is None:
            payload = {}

        events.append(
            {
                "event_id": event_id,
                "seq": seq,
                "kind": kind,
                "step_id": step_id,
                "payload": payload,
            }
        )

    return validate_event_stream(run_id, events, strict)


def format_violations(violations: List[EventContractViolation]) -> str:
    """Format violations for human-readable output.

    Args:
        violations: List of violations to format.

    Returns:
        Formatted string suitable for CLI output.
    """
    if not violations:
        return ""

    lines = []
    for v in violations:
        icon = "✗" if v.severity == "error" else "⚠"
        lines.append(f"  {icon} [{v.kind}] {v.message}")
        if v.event_id:
            lines.append(f"      event_id: {v.event_id}")
        if v.seq is not None:
            lines.append(f"      seq: {v.seq}")

    return "\n".join(lines)
