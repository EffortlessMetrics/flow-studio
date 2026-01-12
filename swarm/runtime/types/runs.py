"""Run types for execution lifecycle and event tracking.

This module contains types for representing runs, run specifications,
run summaries, and run events.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from ._ids import BackendId, RunId, _generate_event_id
from ._time import _datetime_to_iso, _iso_to_datetime


class RunStatus(str, Enum):
    """Status of a run's execution lifecycle."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"
    PARTIAL = "partial"  # Interrupted mid-run, resumable from saved cursor
    STOPPING = "stopping"  # Graceful shutdown in progress
    STOPPED = "stopped"  # Clean stop with savepoint (distinct from failed)
    PAUSING = "pausing"  # Waiting for current step to complete before pause
    PAUSED = "paused"  # Paused at a clean boundary, resumable


class SDLCStatus(str, Enum):
    """Status reflecting SDLC health/quality outcome."""

    OK = "ok"
    WARNING = "warning"
    ERROR = "error"
    UNKNOWN = "unknown"
    PARTIAL = "partial"  # Interrupted mid-run, work is incomplete


@dataclass
class RunSpec:
    """Specification for starting a new run.

    Captures the intent of what should be executed, including which flows
    to run, which profile to use, which backend to execute on, and any
    additional parameters needed by the backend.

    Attributes:
        flow_keys: List of flow keys to execute (e.g., ["signal", "build"]).
        profile_id: Optional profile ID from profile_registry.
        backend: Backend identifier for execution.
        initiator: Source of the run ("cli", "flow-studio", "api", "ci").
        params: Arbitrary per-backend extra parameters.
        no_human_mid_flow: If True, rewrite PAUSE intents to DETOUR for
            autonomous execution (autopilot mode).
    """

    flow_keys: List[str]
    profile_id: Optional[str] = None
    backend: BackendId = "claude-harness"
    initiator: str = "cli"
    params: Dict[str, Any] = field(default_factory=dict)
    no_human_mid_flow: bool = False


@dataclass
class RunSummary:
    """Summary of a run's current state.

    Provides a comprehensive view of a run including its specification,
    status, timing, errors, artifacts, and teaching/exemplar metadata.

    Attributes:
        id: Unique run identifier.
        spec: The original run specification.
        status: Current execution status.
        sdlc_status: SDLC quality/health outcome.
        created_at: When the run was created.
        updated_at: When the run was last updated.
        started_at: When execution actually started (None if pending).
        completed_at: When execution finished (None if not complete).
        error: Error message if failed (None otherwise).
        artifacts: Dictionary of produced artifacts by flow/step.
        is_exemplar: Whether this run is marked as a teaching example.
        tags: List of tags for categorization and filtering.
    """

    id: RunId
    spec: "RunSpec"
    status: RunStatus
    sdlc_status: SDLCStatus
    created_at: datetime
    updated_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error: Optional[str] = None
    artifacts: Dict[str, Any] = field(default_factory=dict)
    is_exemplar: bool = False
    tags: List[str] = field(default_factory=list)
    title: Optional[str] = None  # Human-readable run title
    path: Optional[str] = None  # Filesystem path to run directory
    description: Optional[str] = None  # Human-readable run description


@dataclass
class RunEvent:
    """A single event in a run's timeline.

    Represents an observable occurrence during run execution, enabling
    streaming updates, debugging, and audit trails.

    Attributes:
        run_id: The run this event belongs to.
        ts: Timestamp of the event.
        kind: Event type. Standard types include:
              - "tool_start", "tool_end": Tool invocation lifecycle
              - "step_start", "step_end": Step execution lifecycle
              - "log", "error": General logging and error reporting
              - "verification_started": Spec verification check initiated
              - "verification_passed": Spec verification succeeded
              - "verification_failed": Spec verification failed
              - "macro_route": Flow transition event (macro-routing)
        flow_key: The flow this event occurred in.
        event_id: Globally unique identifier for this event (ULID or UUID4).
        seq: Monotonic sequence number within the run (assigned by storage layer).
        step_id: Optional step identifier within the flow.
        agent_key: Optional agent that produced this event.
        payload: Arbitrary event-specific data. For verification events,
                 may include "station_id", "checks", "passed", "failed".
                 For macro_route events, may include "from_flow", "to_flow",
                 "reason", "loop_count".
    """

    # Required fields (no defaults)
    run_id: RunId
    ts: datetime
    kind: str
    flow_key: str
    # V1 event contract: unique ID and sequence (defaults for backwards compat)
    event_id: str = field(default_factory=_generate_event_id)
    seq: int = 0  # Assigned by storage layer before write
    # Optional fields
    step_id: Optional[str] = None
    agent_key: Optional[str] = None
    payload: Dict[str, Any] = field(default_factory=dict)


@dataclass
class BackendCapabilities:
    """Describes what a backend can do.

    Used to communicate backend features to the UI and orchestration
    layers so they can adapt behavior accordingly.

    Attributes:
        id: Backend identifier.
        label: Human-readable backend name.
        supports_streaming: Whether the backend can stream events.
        supports_events: Whether the backend emits structured events.
        supports_cancel: Whether runs can be canceled mid-execution.
        supports_replay: Whether past runs can be replayed.
    """

    id: BackendId
    label: str
    supports_streaming: bool = False
    supports_events: bool = True
    supports_cancel: bool = False
    supports_replay: bool = False


# =============================================================================
# Serialization Functions
# =============================================================================


def run_spec_to_dict(spec: RunSpec) -> Dict[str, Any]:
    """Convert RunSpec to a dictionary for serialization.

    Args:
        spec: The RunSpec to convert.

    Returns:
        Dictionary representation suitable for JSON/YAML serialization.
    """
    return {
        "flow_keys": list(spec.flow_keys),
        "profile_id": spec.profile_id,
        "backend": spec.backend,
        "initiator": spec.initiator,
        "params": dict(spec.params),
        "no_human_mid_flow": spec.no_human_mid_flow,
    }


def run_spec_from_dict(data: Dict[str, Any]) -> RunSpec:
    """Parse RunSpec from a dictionary.

    Args:
        data: Dictionary with RunSpec fields.

    Returns:
        Parsed RunSpec instance.
    """
    return RunSpec(
        flow_keys=list(data.get("flow_keys", [])),
        profile_id=data.get("profile_id"),
        backend=data.get("backend", "claude-harness"),
        initiator=data.get("initiator", "cli"),
        params=dict(data.get("params", {})),
        no_human_mid_flow=data.get("no_human_mid_flow", False),
    )


def run_summary_to_dict(summary: RunSummary) -> Dict[str, Any]:
    """Convert RunSummary to a dictionary for serialization.

    Args:
        summary: The RunSummary to convert.

    Returns:
        Dictionary representation suitable for JSON/YAML serialization.
    """
    return {
        "id": summary.id,
        "spec": run_spec_to_dict(summary.spec),
        "status": summary.status.value
        if isinstance(summary.status, RunStatus)
        else summary.status,
        "sdlc_status": summary.sdlc_status.value
        if isinstance(summary.sdlc_status, SDLCStatus)
        else summary.sdlc_status,
        "created_at": _datetime_to_iso(summary.created_at),
        "updated_at": _datetime_to_iso(summary.updated_at),
        "started_at": _datetime_to_iso(summary.started_at),
        "completed_at": _datetime_to_iso(summary.completed_at),
        "error": summary.error,
        "artifacts": dict(summary.artifacts),
        "is_exemplar": summary.is_exemplar,
        "tags": list(summary.tags),
        "title": summary.title,
        "path": summary.path,
        "description": summary.description,
    }


def run_summary_from_dict(data: Dict[str, Any]) -> RunSummary:
    """Parse RunSummary from a dictionary.

    Args:
        data: Dictionary with RunSummary fields.

    Returns:
        Parsed RunSummary instance.
    """
    status_value = data.get("status", "pending")
    status = RunStatus(status_value) if isinstance(status_value, str) else status_value

    sdlc_status_value = data.get("sdlc_status", "unknown")
    sdlc_status = (
        SDLCStatus(sdlc_status_value)
        if isinstance(sdlc_status_value, str)
        else sdlc_status_value
    )

    return RunSummary(
        id=data.get("id", ""),
        spec=run_spec_from_dict(data.get("spec", {})),
        status=status,
        sdlc_status=sdlc_status,
        created_at=_iso_to_datetime(data.get("created_at")) or datetime.now(timezone.utc),
        updated_at=_iso_to_datetime(data.get("updated_at")) or datetime.now(timezone.utc),
        started_at=_iso_to_datetime(data.get("started_at")),
        completed_at=_iso_to_datetime(data.get("completed_at")),
        error=data.get("error"),
        artifacts=dict(data.get("artifacts", {})),
        is_exemplar=data.get("is_exemplar", False),
        tags=list(data.get("tags", [])),
        title=data.get("title"),
        path=data.get("path"),
        description=data.get("description"),
    )


def run_event_to_dict(event: RunEvent) -> Dict[str, Any]:
    """Convert RunEvent to a dictionary for serialization.

    Args:
        event: The RunEvent to convert.

    Returns:
        Dictionary representation suitable for JSON/YAML serialization.
    """
    return {
        "run_id": event.run_id,
        "ts": _datetime_to_iso(event.ts),
        "kind": event.kind,
        "flow_key": event.flow_key,
        "event_id": event.event_id,
        "seq": event.seq,
        "step_id": event.step_id,
        "agent_key": event.agent_key,
        "payload": dict(event.payload),
    }


def run_event_from_dict(data: Dict[str, Any]) -> RunEvent:
    """Parse RunEvent from a dictionary.

    Args:
        data: Dictionary with RunEvent fields.

    Returns:
        Parsed RunEvent instance.

    Note:
        Provides backwards compatibility for events missing the new event_id
        and seq fields by generating a new event_id if missing.
    """
    return RunEvent(
        run_id=data.get("run_id", ""),
        ts=_iso_to_datetime(data.get("ts")) or datetime.now(timezone.utc),
        kind=data.get("kind", ""),
        flow_key=data.get("flow_key", ""),
        # V1 event contract: provide backwards compatible defaults
        event_id=data.get("event_id") or _generate_event_id(),
        seq=data.get("seq", 0),
        step_id=data.get("step_id"),
        agent_key=data.get("agent_key"),
        payload=dict(data.get("payload", {})),
    )
