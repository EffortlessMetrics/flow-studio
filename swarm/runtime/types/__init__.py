"""
types.py - Core type definitions for the RunService architecture

This module provides the foundational data types for the swarm runtime system.
It defines the contracts for representing runs, events, specifications, and
backend capabilities used throughout the RunService and its components.

All types use dataclasses with full type annotations to ensure consistency
and enable static type checking across the runtime layer.

Usage:
    from swarm.runtime.types import (
        RunId, BackendId, RunStatus, SDLCStatus,
        RoutingDecision, DecisionType, RoutingSignal, RoutingExplanation,
        RoutingFactor, EdgeOption, Elimination, LLMReasoning,
        CELEvaluation, MicroloopContext, DecisionMetrics,
        # WP4: Bounded, auditable, cheap routing types
        WP4EliminationEntry, WP4RoutingMetrics, WP4RoutingExplanation,
        wp4_routing_explanation_to_dict, wp4_routing_explanation_from_dict,
        # Assumption and decision logging types
        ConfidenceLevel, AssumptionStatus, AssumptionEntry, DecisionLogEntry,
        # Observation and justification types (V3 routing)
        ObservationType, ObservationPriority, ObservationEntry,
        WhyNowJustification,
        # Station opinion types (non-binding witness statements)
        StationOpinionKind, StationOpinion,
        # Skip justification for high-friction skip semantics
        SkipJustification,
        assumption_entry_to_dict, assumption_entry_from_dict,
        decision_log_entry_to_dict, decision_log_entry_from_dict,
        HandoffEnvelope, RunState,
        InterruptionFrame, ResumePoint, InjectedNode, InjectedNodeSpec,
        RunSpec, RunSummary, RunEvent, BackendCapabilities,
        generate_run_id,
        run_spec_to_dict, run_spec_from_dict,
        run_summary_to_dict, run_summary_from_dict,
        run_event_to_dict, run_event_from_dict,
        routing_signal_to_dict, routing_signal_from_dict,
        routing_explanation_to_dict, routing_explanation_from_dict,
        handoff_envelope_to_dict, handoff_envelope_from_dict,
        run_state_to_dict, run_state_from_dict,
        interruption_frame_to_dict, interruption_frame_from_dict,
        resume_point_to_dict, resume_point_from_dict,
        injected_node_to_dict, injected_node_from_dict,
        injected_node_spec_to_dict, injected_node_spec_from_dict,
        # Macro navigation types (between-flow routing)
        MacroAction, GateVerdict, FlowOutcome, FlowResult,
        MacroRoutingRule, MacroPolicy, HumanPolicy, RunPlanSpec,
        MacroRoutingDecision,
        flow_result_to_dict, flow_result_from_dict,
        macro_routing_rule_to_dict, macro_routing_rule_from_dict,
        macro_policy_to_dict, macro_policy_from_dict,
        human_policy_to_dict, human_policy_from_dict,
        run_plan_spec_to_dict, run_plan_spec_from_dict,
        macro_routing_decision_to_dict, macro_routing_decision_from_dict,
        # Normalized tool call representation (cross-transport)
        NormalizedToolCall, truncate_output,
        normalized_tool_call_from_sdk_events,
        normalized_tool_call_from_gemini_events,
        normalized_tool_call_from_stub,
        normalized_tool_call_from_kernel_execution,
    )
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Literal, Optional, TypedDict

# Import from submodules (these are re-exported for backwards compatibility)
from ._ids import BackendId, RunId, _generate_event_id, generate_run_id
from ._time import _datetime_to_iso, _iso_to_datetime
from .routing import (
    CELEvaluation,
    DecisionMetrics,
    DecisionType,
    EdgeOption,
    Elimination,
    LLMReasoning,
    MicroloopContext,
    RoutingCandidate,
    RoutingDecision,
    RoutingExplanation,
    RoutingFactor,
    RoutingMode,
    RoutingSignal,
    SkipJustification,
    StallContext,
    WhyNowJustification,
    WP4EliminationEntry,
    WP4RoutingExplanation,
    WP4RoutingMetrics,
    routing_candidate_from_dict,
    routing_candidate_to_dict,
    routing_explanation_from_dict,
    routing_explanation_to_dict,
    routing_signal_from_dict,
    routing_signal_to_dict,
    wp4_routing_explanation_from_dict,
    wp4_routing_explanation_to_dict,
)
from .audit import (
    AssumptionEntry,
    AssumptionStatus,
    ConfidenceLevel,
    DecisionLogEntry,
    ObservationEntry,
    ObservationPriority,
    ObservationType,
    StationOpinion,
    StationOpinionKind,
    assumption_entry_from_dict,
    assumption_entry_to_dict,
    decision_log_entry_from_dict,
    decision_log_entry_to_dict,
)
from .tool_call import (
    NormalizedToolCall,
    from_gemini_events as normalized_tool_call_from_gemini_events,
    from_kernel_execution as normalized_tool_call_from_kernel_execution,
    from_sdk_events as normalized_tool_call_from_sdk_events,
    from_stub as normalized_tool_call_from_stub,
    truncate_output,
)


def _get_default_flow_sequence() -> List[str]:
    """Get the default SDLC flow sequence from the registry.

    This function is used as a default_factory for RunPlanSpec to avoid
    hardcoding flow lists. Uses lazy import to prevent circular dependencies.
    Returns only SDLC flows (excludes demo/test flows).
    """
    try:
        from swarm.config.flow_registry import get_sdlc_flow_keys
        return get_sdlc_flow_keys()
    except ImportError:
        # Fallback if registry not available
        return ["signal", "plan", "build", "review", "gate", "deploy", "wisdom"]


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


# Note: RoutingDecision, DecisionType, RoutingMode imported from .routing
# Note: ConfidenceLevel, AssumptionStatus, ObservationType, ObservationPriority,
# StationOpinionKind, StationOpinion, ObservationEntry, AssumptionEntry,
# DecisionLogEntry imported from .audit
# Note: RoutingFactor, EdgeOption, Elimination, LLMReasoning, CELEvaluation,
# MicroloopContext, DecisionMetrics, WP4*, RoutingExplanation, RoutingSignal,
# RoutingCandidate, routing_candidate_to/from_dict are imported from .routing


@dataclass
class HandoffEnvelope:
    """Durable per-step handoff artifact for cross-step communication.

    Serves as a compression layer containing the routing signal, artifact
    pointers, and a summary (1-2k chars max) for efficient context
    handoff between steps.

    Attributes:
        step_id: The step ID that produced this envelope.
        flow_key: The flow key this step belongs to.
        run_id: The run ID.
        routing_signal: The routing decision signal for this step.
        summary: Compressed summary of step output (1-2k chars max).
        artifacts: Map of artifact names to their file paths (relative to RUN_BASE).
        file_changes: Forensic file mutation scan results (authoritative, not agent-reported).
        status: Execution status of the step.
        error: Error message if the step failed.
        duration_ms: Execution duration in milliseconds.
        timestamp: ISO 8601 timestamp when this envelope was created.
        station_id: Station identifier for spec traceability.
        station_version: Version of the station spec used.
        prompt_hash: Hash of the prompt template for reproducibility.
        verification_passed: Whether spec verification passed for this step.
        verification_details: Detailed verification results and diagnostics.
        assumptions_made: List of assumptions made during this step's execution.
        decisions_made: List of decisions logged during this step's execution.
        observations: Shadow telemetry for Wisdom Stream analysis.
        station_opinions: Non-binding witness statements from the station about what
            should happen next. These are suggestions the orchestrator may corroborate
            via forensics and charter alignment, not executable intent.
    """

    step_id: str
    flow_key: str
    run_id: str
    routing_signal: RoutingSignal
    summary: str
    artifacts: Dict[str, str] = field(default_factory=dict)
    file_changes: Dict[str, Any] = field(default_factory=dict)
    status: str = "succeeded"
    error: Optional[str] = None
    duration_ms: int = 0
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    # Spec traceability fields
    station_id: Optional[str] = None
    station_version: Optional[int] = None
    prompt_hash: Optional[str] = None
    verification_passed: bool = True
    verification_details: Dict[str, Any] = field(default_factory=dict)
    # Routing audit trail (optional, populated when routing includes explanation)
    routing_audit: Optional[Dict[str, Any]] = None
    # Assumption and decision logging (structured JSONL-compatible records)
    assumptions_made: List[AssumptionEntry] = field(default_factory=list)
    decisions_made: List[DecisionLogEntry] = field(default_factory=list)
    # Observations for Wisdom Stream (shadow telemetry for learning)
    observations: List[ObservationEntry] = field(default_factory=list)
    # Station opinions: non-binding witness statements for orchestrator corroboration
    # These are suggestions the station thinks should happen, but the orchestrator
    # decides whether to act on them after forensic verification and charter alignment.
    station_opinions: List[StationOpinion] = field(default_factory=list)


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
    spec: RunSpec
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


# -----------------------------------------------------------------------------
# Serialization Helpers
# -----------------------------------------------------------------------------
# Note: generate_run_id is imported from ._ids
# Note: _datetime_to_iso, _iso_to_datetime are imported from ._time


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
        initiator=data.get("initiator", "unknown"),
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
        "status": summary.status.value,
        "sdlc_status": summary.sdlc_status.value,
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
    now = datetime.now(timezone.utc)
    return RunSummary(
        id=data.get("id", ""),
        spec=run_spec_from_dict(data.get("spec", {})),
        status=RunStatus(data.get("status", "pending")),
        sdlc_status=SDLCStatus(data.get("sdlc_status", "unknown")),
        created_at=_iso_to_datetime(data.get("created_at")) or now,
        updated_at=_iso_to_datetime(data.get("updated_at")) or now,
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
        "event_id": event.event_id,
        "seq": event.seq,
        "run_id": event.run_id,
        "ts": _datetime_to_iso(event.ts),
        "kind": event.kind,
        "flow_key": event.flow_key,
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
        Provides backwards compatibility for events missing event_id or seq
        fields by generating a new event_id or defaulting seq to 0.
    """
    return RunEvent(
        run_id=data.get("run_id", ""),
        ts=_iso_to_datetime(data.get("ts")) or datetime.now(timezone.utc),
        kind=data.get("kind", "unknown"),
        flow_key=data.get("flow_key", ""),
        event_id=data.get("event_id", _generate_event_id()),
        seq=data.get("seq", 0),
        step_id=data.get("step_id"),
        agent_key=data.get("agent_key"),
        payload=dict(data.get("payload", {})),
    )


# Note: routing_explanation_to/from_dict, wp4_routing_explanation_to/from_dict
# are imported from .routing
# Note: assumption_entry_to/from_dict, decision_log_entry_to/from_dict
# are imported from .audit
# Note: routing_signal_to/from_dict are imported from .routing


# -----------------------------------------------------------------------------
# HandoffEnvelope Serialization
# -----------------------------------------------------------------------------


def handoff_envelope_to_dict(envelope: HandoffEnvelope) -> Dict[str, Any]:
    """Convert HandoffEnvelope to a dictionary for serialization.

    Args:
        envelope: The HandoffEnvelope to convert.

    Returns:
        Dictionary representation suitable for JSON/YAML serialization.
    """
    result = {
        "step_id": envelope.step_id,
        "flow_key": envelope.flow_key,
        "run_id": envelope.run_id,
        "routing_signal": routing_signal_to_dict(envelope.routing_signal),
        "summary": envelope.summary,
        "artifacts": dict(envelope.artifacts),
        "file_changes": dict(envelope.file_changes),
        "status": envelope.status,
        "error": envelope.error,
        "duration_ms": envelope.duration_ms,
        "timestamp": _datetime_to_iso(envelope.timestamp),
        # Spec traceability fields
        "station_id": envelope.station_id,
        "station_version": envelope.station_version,
        "prompt_hash": envelope.prompt_hash,
        "verification_passed": envelope.verification_passed,
        "verification_details": dict(envelope.verification_details),
    }

    # Include routing audit trail if the routing signal has an explanation
    if envelope.routing_signal.explanation:
        result["routing_audit"] = routing_explanation_to_dict(envelope.routing_signal.explanation)
    elif envelope.routing_audit:
        result["routing_audit"] = envelope.routing_audit

    # Include assumptions and decisions if present
    if envelope.assumptions_made:
        result["assumptions_made"] = [
            assumption_entry_to_dict(a) for a in envelope.assumptions_made
        ]
    if envelope.decisions_made:
        result["decisions_made"] = [decision_log_entry_to_dict(d) for d in envelope.decisions_made]

    # Include station opinions if present (non-binding witness statements)
    if envelope.station_opinions:
        result["station_opinions"] = list(envelope.station_opinions)

    return result


def handoff_envelope_from_dict(data: Dict[str, Any]) -> HandoffEnvelope:
    """Parse HandoffEnvelope from a dictionary.

    Args:
        data: Dictionary with HandoffEnvelope fields.

    Returns:
        Parsed HandoffEnvelope instance.

    Note:
        Provides backwards compatibility for envelopes missing the new
        spec traceability fields (station_id, station_version, prompt_hash,
        verification_passed, verification_details, routing_audit) and
        assumption/decision logging fields (assumptions_made, decisions_made).
    """
    routing_signal_data = data.get("routing_signal", {})
    routing_signal = routing_signal_from_dict(routing_signal_data)

    # Parse routing_audit if present (store as raw dict for flexibility)
    routing_audit = data.get("routing_audit")

    # Parse assumptions and decisions if present (backward compatible)
    assumptions_made = [assumption_entry_from_dict(a) for a in data.get("assumptions_made", [])]
    decisions_made = [decision_log_entry_from_dict(d) for d in data.get("decisions_made", [])]

    # Parse station opinions if present (backward compatible)
    # StationOpinion is a TypedDict, so we just pass the dicts through
    station_opinions: List[StationOpinion] = list(data.get("station_opinions", []))

    return HandoffEnvelope(
        step_id=data.get("step_id", ""),
        flow_key=data.get("flow_key", ""),
        run_id=data.get("run_id", ""),
        routing_signal=routing_signal,
        summary=data.get("summary", ""),
        artifacts=dict(data.get("artifacts", {})),
        file_changes=dict(data.get("file_changes", {})),
        status=data.get("status", "succeeded"),
        error=data.get("error"),
        duration_ms=data.get("duration_ms", 0),
        timestamp=_iso_to_datetime(data.get("timestamp")) or datetime.now(timezone.utc),
        # Spec traceability fields (backward compatible defaults)
        station_id=data.get("station_id"),
        station_version=data.get("station_version"),
        prompt_hash=data.get("prompt_hash"),
        verification_passed=data.get("verification_passed", True),
        verification_details=dict(data.get("verification_details", {})),
        routing_audit=routing_audit,
        # Assumption and decision logging (backward compatible)
        assumptions_made=assumptions_made,
        decisions_made=decisions_made,
        # Station opinions (backward compatible)
        station_opinions=station_opinions,
    )


# -----------------------------------------------------------------------------
# RunState Serialization (for durable program counter with detour support)
# -----------------------------------------------------------------------------


@dataclass
class InterruptionFrame:
    """Frame representing an interruption point in the execution stack.

    When a run is interrupted (for a detour, human intervention, or pause),
    an InterruptionFrame is pushed to the stack to enable resumption.

    Attributes:
        reason: Human-readable reason for the interruption.
        interrupted_at: Timestamp when the interruption occurred.
        return_node: Node ID to return to after the detour completes.
        context_snapshot: Snapshot of execution context at interruption time.
        current_step_index: For multi-step sidequests, tracks the current step
            (0-indexed). Incremented after each sidequest step completes.
        total_steps: Total number of steps in the sidequest. When
            current_step_index == total_steps, the sidequest is complete.
        sidequest_id: ID of the sidequest being executed (for catalog lookup).
    """

    reason: str
    interrupted_at: datetime
    return_node: str
    context_snapshot: Dict[str, Any] = field(default_factory=dict)
    current_step_index: int = 0
    total_steps: int = 1
    sidequest_id: Optional[str] = None


@dataclass
class ResumePoint:
    """A saved resume point for continuation after interruption.

    Resume points allow the orchestrator to continue execution from
    a specific node with restored context after a detour completes.

    Attributes:
        node_id: Node ID to resume execution at.
        saved_context: Execution context saved at the resume point.
    """

    node_id: str
    saved_context: Dict[str, Any] = field(default_factory=dict)


@dataclass
class InjectedNode:
    """Specification for a dynamically injected node.

    Injected nodes are added to the execution graph at runtime,
    typically for detour handling or dynamic workflow modifications.

    Attributes:
        node_id: Unique identifier for the injected node.
        agent_key: The agent to execute at this node.
        role: Human-readable role/purpose of this node.
        insert_after: Node ID after which to insert this node.
        insert_before: Node ID before which to insert this node (alternative).
        params: Additional parameters for the node execution.
        routing_override: Optional routing to use instead of default.
    """

    node_id: str
    agent_key: str
    role: str = ""
    insert_after: Optional[str] = None
    insert_before: Optional[str] = None
    params: Dict[str, Any] = field(default_factory=dict)
    routing_override: Optional[Dict[str, Any]] = None


@dataclass
class InjectedNodeSpec:
    """Full execution specification for a dynamically injected node.

    Unlike InjectedNode which just tracks node_id and insertion point,
    InjectedNodeSpec contains everything needed to execute the node:
    the station/template to run, parameters, and traceability.

    Attributes:
        node_id: Unique identifier for this injected node (e.g., "sq-clarifier-0").
        station_id: Station identifier to execute (resolved from pack registry).
        template_id: Optional template ID if different from station_id.
        agent_key: Agent key to execute at this node.
        role: Human-readable role/purpose.
        params: Additional parameters for execution.
        sidequest_origin: Sidequest ID if this was injected by a sidequest.
        sequence_index: For multi-step sidequests, the step index (0-based).
        total_in_sequence: Total steps in the sequence this belongs to.
    """

    node_id: str
    station_id: str
    template_id: Optional[str] = None
    agent_key: Optional[str] = None
    role: str = ""
    params: Dict[str, Any] = field(default_factory=dict)
    sidequest_origin: Optional[str] = None
    sequence_index: int = 0
    total_in_sequence: int = 1


@dataclass
class RunState:
    """Durable program counter for stepwise flow execution with detour support.

    Tracks current execution state of a run, enabling resumption
    from any step after process restart. Supports interruption stacks
    for nested detours and resume points for continuation.

    The detour mechanism allows:
    - Pausing execution at any point
    - Injecting additional nodes into the flow
    - Resuming from where execution left off
    - Nested detours (detour within a detour)

    Attributes:
        run_id: The run identifier.
        flow_key: The flow being executed.
        current_step_id: The ID of current step being executed.
        step_index: The 0-based index of current step in the flow.
        loop_state: Dictionary tracking iteration counts per microloop.
        handoff_envelopes: Map of step_id to HandoffEnvelope for completed steps.
        status: Current run status (pending, running, succeeded, failed, canceled,
                paused, interrupted).
        timestamp: ISO 8601 timestamp when this state was last updated.
        current_flow_index: 1-based index of the current flow (1=signal, 6=wisdom).
        flow_transition_history: Ordered list of flow transitions with metadata.
        interruption_stack: Stack of interruption frames for nested detours.
        resume_stack: Stack of resume points for continuation after interruption.
        injected_nodes: List of dynamically injected node IDs.
        injected_node_specs: Map of node_id to InjectedNodeSpec for execution details.
        completed_nodes: List of node IDs that have completed execution.
    """

    run_id: str
    flow_key: str
    current_step_id: Optional[str] = None
    step_index: int = 0
    loop_state: Dict[str, int] = field(default_factory=dict)
    handoff_envelopes: Dict[str, HandoffEnvelope] = field(default_factory=dict)
    status: str = "pending"
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    # Flow tracking fields for macro-routing
    current_flow_index: int = 1
    flow_transition_history: List[Dict[str, Any]] = field(default_factory=list)
    # Detour support: interruption and resume stacks
    interruption_stack: List[InterruptionFrame] = field(default_factory=list)
    resume_stack: List[ResumePoint] = field(default_factory=list)
    injected_nodes: List[str] = field(default_factory=list)
    injected_node_specs: Dict[str, InjectedNodeSpec] = field(default_factory=dict)
    completed_nodes: List[str] = field(default_factory=list)

    # -------------------------------------------------------------------------
    # Detour Stack Operations
    # -------------------------------------------------------------------------

    def push_interruption(
        self,
        reason: str,
        return_node: str,
        context_snapshot: Optional[Dict[str, Any]] = None,
        current_step_index: int = 0,
        total_steps: int = 1,
        sidequest_id: Optional[str] = None,
    ) -> None:
        """Push an interruption frame onto the stack.

        Call this when pausing execution for a detour. The return_node
        specifies where to continue after the detour completes.

        Args:
            reason: Human-readable reason for the interruption.
            return_node: Node ID to return to after detour.
            context_snapshot: Optional context to restore on resume.
            current_step_index: For multi-step sidequests, the current step.
            total_steps: Total number of steps in the sidequest.
            sidequest_id: ID of the sidequest being executed.
        """
        frame = InterruptionFrame(
            reason=reason,
            interrupted_at=datetime.now(timezone.utc),
            return_node=return_node,
            context_snapshot=context_snapshot or {},
            current_step_index=current_step_index,
            total_steps=total_steps,
            sidequest_id=sidequest_id,
        )
        self.interruption_stack.append(frame)
        self.timestamp = datetime.now(timezone.utc)

    def pop_interruption(self) -> Optional[InterruptionFrame]:
        """Pop the most recent interruption frame from the stack.

        Returns:
            The popped InterruptionFrame, or None if stack is empty.
        """
        if not self.interruption_stack:
            return None
        frame = self.interruption_stack.pop()
        self.timestamp = datetime.now(timezone.utc)
        return frame

    def peek_interruption(self) -> Optional[InterruptionFrame]:
        """Peek at the top of the interruption stack without popping.

        Returns:
            The top InterruptionFrame, or None if stack is empty.
        """
        if not self.interruption_stack:
            return None
        return self.interruption_stack[-1]

    def push_resume(
        self,
        node_id: str,
        saved_context: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Push a resume point onto the stack.

        Call this when saving a point to return to after completing
        injected nodes or detour processing.

        Args:
            node_id: Node ID to resume at.
            saved_context: Context to restore when resuming.
        """
        point = ResumePoint(
            node_id=node_id,
            saved_context=saved_context or {},
        )
        self.resume_stack.append(point)
        self.timestamp = datetime.now(timezone.utc)

    def pop_resume(self) -> Optional[ResumePoint]:
        """Pop the most recent resume point from the stack.

        Returns:
            The popped ResumePoint, or None if stack is empty.
        """
        if not self.resume_stack:
            return None
        point = self.resume_stack.pop()
        self.timestamp = datetime.now(timezone.utc)
        return point

    def peek_resume(self) -> Optional[ResumePoint]:
        """Peek at the top of the resume stack without popping.

        Returns:
            The top ResumePoint, or None if stack is empty.
        """
        if not self.resume_stack:
            return None
        return self.resume_stack[-1]

    def add_injected_node(self, node_id: str) -> None:
        """Add a dynamically injected node ID to the list.

        Args:
            node_id: The ID of the injected node.
        """
        if node_id not in self.injected_nodes:
            self.injected_nodes.append(node_id)
            self.timestamp = datetime.now(timezone.utc)

    def register_injected_node(self, spec: InjectedNodeSpec) -> None:
        """Register an injected node with its full execution spec.

        Args:
            spec: The full specification for the injected node.
        """
        self.injected_node_specs[spec.node_id] = spec
        if spec.node_id not in self.injected_nodes:
            self.injected_nodes.append(spec.node_id)
        self.timestamp = datetime.now(timezone.utc)

    def get_injected_node_spec(self, node_id: str) -> Optional[InjectedNodeSpec]:
        """Get the execution spec for an injected node.

        Args:
            node_id: The node ID to look up.

        Returns:
            InjectedNodeSpec if found, None otherwise.
        """
        return self.injected_node_specs.get(node_id)

    def mark_node_completed(self, node_id: str) -> None:
        """Mark a node as completed.

        Args:
            node_id: The ID of the completed node.
        """
        if node_id not in self.completed_nodes:
            self.completed_nodes.append(node_id)
            self.timestamp = datetime.now(timezone.utc)

    def is_node_completed(self, node_id: str) -> bool:
        """Check if a node has been completed.

        Args:
            node_id: The node ID to check.

        Returns:
            True if the node has been completed.
        """
        return node_id in self.completed_nodes

    def is_interrupted(self) -> bool:
        """Check if the run is currently in an interrupted state.

        Returns:
            True if there are pending interruptions on the stack.
        """
        return len(self.interruption_stack) > 0

    def get_interruption_depth(self) -> int:
        """Get the current depth of nested interruptions.

        Returns:
            The number of interruption frames on the stack.
        """
        return len(self.interruption_stack)


def interruption_frame_to_dict(frame: InterruptionFrame) -> Dict[str, Any]:
    """Convert InterruptionFrame to a dictionary for serialization.

    Args:
        frame: The InterruptionFrame to convert.

    Returns:
        Dictionary representation suitable for JSON serialization.
    """
    return {
        "reason": frame.reason,
        "interrupted_at": _datetime_to_iso(frame.interrupted_at),
        "return_node": frame.return_node,
        "context_snapshot": dict(frame.context_snapshot),
        "current_step_index": frame.current_step_index,
        "total_steps": frame.total_steps,
        "sidequest_id": frame.sidequest_id,
    }


def interruption_frame_from_dict(data: Dict[str, Any]) -> InterruptionFrame:
    """Parse InterruptionFrame from a dictionary.

    Args:
        data: Dictionary with InterruptionFrame fields.

    Returns:
        Parsed InterruptionFrame instance.
    """
    return InterruptionFrame(
        reason=data.get("reason", ""),
        interrupted_at=_iso_to_datetime(data.get("interrupted_at")) or datetime.now(timezone.utc),
        return_node=data.get("return_node", ""),
        context_snapshot=dict(data.get("context_snapshot", {})),
        current_step_index=data.get("current_step_index", 0),
        total_steps=data.get("total_steps", 1),
        sidequest_id=data.get("sidequest_id"),
    )


def resume_point_to_dict(point: ResumePoint) -> Dict[str, Any]:
    """Convert ResumePoint to a dictionary for serialization.

    Args:
        point: The ResumePoint to convert.

    Returns:
        Dictionary representation suitable for JSON serialization.
    """
    return {
        "node_id": point.node_id,
        "saved_context": dict(point.saved_context),
    }


def resume_point_from_dict(data: Dict[str, Any]) -> ResumePoint:
    """Parse ResumePoint from a dictionary.

    Args:
        data: Dictionary with ResumePoint fields.

    Returns:
        Parsed ResumePoint instance.
    """
    return ResumePoint(
        node_id=data.get("node_id", ""),
        saved_context=dict(data.get("saved_context", {})),
    )


def injected_node_to_dict(node: InjectedNode) -> Dict[str, Any]:
    """Convert InjectedNode to a dictionary for serialization.

    Args:
        node: The InjectedNode to convert.

    Returns:
        Dictionary representation suitable for JSON serialization.
    """
    return {
        "node_id": node.node_id,
        "agent_key": node.agent_key,
        "role": node.role,
        "insert_after": node.insert_after,
        "insert_before": node.insert_before,
        "params": dict(node.params),
        "routing_override": node.routing_override,
    }


def injected_node_from_dict(data: Dict[str, Any]) -> InjectedNode:
    """Parse InjectedNode from a dictionary.

    Args:
        data: Dictionary with InjectedNode fields.

    Returns:
        Parsed InjectedNode instance.
    """
    return InjectedNode(
        node_id=data.get("node_id", ""),
        agent_key=data.get("agent_key", ""),
        role=data.get("role", ""),
        insert_after=data.get("insert_after"),
        insert_before=data.get("insert_before"),
        params=dict(data.get("params", {})),
        routing_override=data.get("routing_override"),
    )


def injected_node_spec_to_dict(spec: InjectedNodeSpec) -> Dict[str, Any]:
    """Convert InjectedNodeSpec to dictionary for serialization."""
    return {
        "node_id": spec.node_id,
        "station_id": spec.station_id,
        "template_id": spec.template_id,
        "agent_key": spec.agent_key,
        "role": spec.role,
        "params": dict(spec.params),
        "sidequest_origin": spec.sidequest_origin,
        "sequence_index": spec.sequence_index,
        "total_in_sequence": spec.total_in_sequence,
    }


def injected_node_spec_from_dict(data: Dict[str, Any]) -> InjectedNodeSpec:
    """Parse InjectedNodeSpec from dictionary."""
    return InjectedNodeSpec(
        node_id=data.get("node_id", ""),
        station_id=data.get("station_id", ""),
        template_id=data.get("template_id"),
        agent_key=data.get("agent_key"),
        role=data.get("role", ""),
        params=dict(data.get("params", {})),
        sidequest_origin=data.get("sidequest_origin"),
        sequence_index=data.get("sequence_index", 0),
        total_in_sequence=data.get("total_in_sequence", 1),
    )


def run_state_to_dict(state: RunState) -> Dict[str, Any]:
    """Convert RunState to a dictionary for serialization.

    Args:
        state: The RunState to convert.

    Returns:
        Dictionary representation suitable for JSON serialization.
    """
    return {
        "run_id": state.run_id,
        "flow_key": state.flow_key,
        # Also include flow_id for schema compatibility
        "flow_id": state.flow_key,
        "current_step_id": state.current_step_id,
        # Also include current_node for schema compatibility
        "current_node": state.current_step_id,
        "step_index": state.step_index,
        "loop_state": dict(state.loop_state),
        "handoff_envelopes": {
            step_id: handoff_envelope_to_dict(env)
            for step_id, env in state.handoff_envelopes.items()
        },
        "status": state.status,
        "timestamp": _datetime_to_iso(state.timestamp),
        # Flow tracking fields
        "current_flow_index": state.current_flow_index,
        "flow_transition_history": list(state.flow_transition_history),
        # Detour support fields
        "interruption_stack": [
            interruption_frame_to_dict(frame) for frame in state.interruption_stack
        ],
        "resume_stack": [resume_point_to_dict(point) for point in state.resume_stack],
        "injected_nodes": list(state.injected_nodes),
        "injected_node_specs": {
            node_id: injected_node_spec_to_dict(spec)
            for node_id, spec in state.injected_node_specs.items()
        },
        "completed_nodes": list(state.completed_nodes),
        # Schema-compatible aliases
        "artifacts": {
            step_id: env.artifacts if hasattr(env, "artifacts") else {}
            for step_id, env in state.handoff_envelopes.items()
        },
    }


def run_state_from_dict(data: Dict[str, Any]) -> RunState:
    """Parse RunState from a dictionary.

    Args:
        data: Dictionary with RunState fields.

    Returns:
        Parsed RunState instance.

    Note:
        Provides backwards compatibility for states missing the new
        detour support fields (interruption_stack, resume_stack, etc.).
    """
    envelopes_data = data.get("handoff_envelopes", {})
    handoff_envelopes = {
        step_id: handoff_envelope_from_dict(env_data)
        for step_id, env_data in envelopes_data.items()
    }

    # Parse interruption stack
    interruption_stack_data = data.get("interruption_stack", [])
    interruption_stack = [
        interruption_frame_from_dict(frame_data) for frame_data in interruption_stack_data
    ]

    # Parse resume stack
    resume_stack_data = data.get("resume_stack", [])
    resume_stack = [resume_point_from_dict(point_data) for point_data in resume_stack_data]

    # Parse injected node specs
    injected_node_specs_data = data.get("injected_node_specs", {})
    injected_node_specs = {
        node_id: injected_node_spec_from_dict(spec_data)
        for node_id, spec_data in injected_node_specs_data.items()
    }

    # Handle both flow_key and flow_id for compatibility
    flow_key = data.get("flow_key") or data.get("flow_id", "")

    # Handle both current_step_id and current_node for compatibility
    current_step_id = data.get("current_step_id") or data.get("current_node")

    return RunState(
        run_id=data.get("run_id", ""),
        flow_key=flow_key,
        current_step_id=current_step_id,
        step_index=data.get("step_index", 0),
        loop_state=dict(data.get("loop_state", {})),
        handoff_envelopes=handoff_envelopes,
        status=data.get("status", "pending"),
        timestamp=_iso_to_datetime(data.get("timestamp")) or datetime.now(timezone.utc),
        # Flow tracking fields (backward compatible defaults)
        current_flow_index=data.get("current_flow_index", 1),
        flow_transition_history=list(data.get("flow_transition_history", [])),
        # Detour support fields (backward compatible defaults)
        interruption_stack=interruption_stack,
        resume_stack=resume_stack,
        injected_nodes=list(data.get("injected_nodes", [])),
        injected_node_specs=injected_node_specs,
        completed_nodes=list(data.get("completed_nodes", [])),
    )


# =============================================================================
# Macro Navigation Types (Between-Flow Routing)
# =============================================================================
# These types support intelligent routing decisions BETWEEN flows, complementing
# the within-flow micro-navigation handled by Navigator.


class MacroAction(str, Enum):
    """Action to take between flows."""

    ADVANCE = "advance"  # Proceed to next flow in sequence
    REPEAT = "repeat"  # Re-run the same flow (e.g., after bounce)
    GOTO = "goto"  # Jump to a specific flow (non-sequential)
    SKIP = "skip"  # Skip a flow (e.g., skip deploy if not ready)
    TERMINATE = "terminate"  # End the run (success or failure)
    PAUSE = "pause"  # Pause for human intervention between flows


class GateVerdict(str, Enum):
    """Gate (Flow 4) decision outcomes.

    These map to the merge-decider agent's output in merge_decision.md.
    """

    MERGE = "MERGE"  # Approved for deployment
    MERGE_WITH_CONDITIONS = "MERGE_WITH_CONDITIONS"  # Approved with monitoring
    BOUNCE_BUILD = "BOUNCE_BUILD"  # Fixable issues, return to build
    BOUNCE_PLAN = "BOUNCE_PLAN"  # Design issues, return to plan
    ESCALATE = "ESCALATE"  # Needs human decision
    BLOCK = "BLOCK"  # Hard blocker, cannot proceed


class FlowOutcome(str, Enum):
    """Outcome status of a completed flow."""

    SUCCEEDED = "succeeded"  # Flow completed successfully
    FAILED = "failed"  # Flow failed with error
    PARTIAL = "partial"  # Flow partially completed
    BOUNCED = "bounced"  # Flow bounced to earlier flow
    SKIPPED = "skipped"  # Flow was skipped


@dataclass
class FlowResult:
    """Result of a completed flow for macro-routing decisions.

    This captures the outcome of a flow in a structured way that the
    MacroNavigator can use to decide between-flow routing.

    Attributes:
        flow_key: The flow that completed.
        outcome: Overall outcome status.
        status: Detailed status from the flow's receipt/envelope.
        gate_verdict: For gate flow, the merge decision.
        bounce_target: For bounced flows, where to bounce to.
        error: Error message if the flow failed.
        artifacts: Map of key artifacts produced.
        duration_ms: Flow execution time.
        issues: List of issues that may affect routing.
        recommendations: Agent recommendations for next steps.
    """

    flow_key: str
    outcome: FlowOutcome
    status: str = ""  # VERIFIED, UNVERIFIED, BLOCKED, etc.
    gate_verdict: Optional[GateVerdict] = None
    bounce_target: Optional[str] = None  # "build", "plan", etc.
    error: Optional[str] = None
    artifacts: Dict[str, str] = field(default_factory=dict)
    duration_ms: int = 0
    issues: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)


@dataclass
class MacroRoutingRule:
    """A single routing rule for macro-navigation.

    Rules are evaluated in order; first matching rule is applied.

    Attributes:
        rule_id: Unique identifier for this rule.
        condition: CEL-like condition, e.g., "gate.verdict == 'BOUNCE_BUILD'".
        action: Action to take when condition matches.
        target_flow: For "goto" action, the flow to jump to.
        max_uses: Maximum times this rule can fire (prevents infinite loops).
        uses: Current usage count (tracked at runtime).
        description: Human-readable description of what this rule does.
    """

    rule_id: str
    condition: str
    action: MacroAction
    target_flow: Optional[str] = None
    max_uses: int = 3  # Safety limit to prevent infinite loops
    uses: int = 0
    description: str = ""

    def matches(self, flow_result: "FlowResult") -> bool:
        """Evaluate if this rule matches the flow result.

        Simple condition evaluation - production would use proper CEL.
        For now, supports patterns like:
            - "outcome == 'failed'"
            - "gate.verdict == 'BOUNCE_BUILD'"
            - "flow == 'gate' and status == 'UNVERIFIED'"
        """
        ctx = {
            "flow": flow_result.flow_key,
            "outcome": flow_result.outcome.value,
            "status": flow_result.status,
            "gate.verdict": (flow_result.gate_verdict.value if flow_result.gate_verdict else None),
            "bounce_target": flow_result.bounce_target,
            "has_error": flow_result.error is not None,
        }

        # Very simple condition parsing (would use CEL in production)
        try:
            # Handle simple equality conditions
            condition = self.condition.strip()
            if " == " in condition:
                parts = condition.split(" == ")
                if len(parts) == 2:
                    key = parts[0].strip()
                    value = parts[1].strip().strip("'\"")
                    return str(ctx.get(key, "")) == value
            if " and " in condition.lower():
                # Handle simple AND conditions
                sub_conditions = condition.lower().split(" and ")
                results = []
                for sub in sub_conditions:
                    sub = sub.strip()
                    if " == " in sub:
                        parts = sub.split(" == ")
                        if len(parts) == 2:
                            key = parts[0].strip()
                            value = parts[1].strip().strip("'\"")
                            results.append(str(ctx.get(key, "")).lower() == value.lower())
                return all(results)
            return False
        except Exception:
            return False

    def can_fire(self) -> bool:
        """Check if this rule can still fire (hasn't exceeded max_uses)."""
        return self.uses < self.max_uses

    def record_use(self) -> None:
        """Record that this rule was used."""
        self.uses += 1


@dataclass
class MacroPolicy:
    """Policy for between-flow routing decisions.

    Defines rules for when to loop, skip, or retry flows based on
    their outcomes. This is distinct from within-flow routing (Navigator).

    Attributes:
        allow_flow_repeat: Whether flows can be re-run.
        max_repeats_per_flow: Maximum times a single flow can repeat.
        routing_rules: Ordered list of condition-based routing rules.
        default_action: Action when no rules match (usually advance).
        strict_gate: If True, never skip gate even if other flows failed.
    """

    allow_flow_repeat: bool = True
    max_repeats_per_flow: int = 3
    routing_rules: List[MacroRoutingRule] = field(default_factory=list)
    default_action: MacroAction = MacroAction.ADVANCE
    strict_gate: bool = True  # Always run gate, never skip

    @classmethod
    def default(cls) -> "MacroPolicy":
        """Create a default macro policy with standard SDLC rules."""
        return cls(
            allow_flow_repeat=True,
            max_repeats_per_flow=3,
            routing_rules=[
                # Gate bounces go back to the target flow
                MacroRoutingRule(
                    rule_id="gate-bounce-build",
                    condition="gate.verdict == 'BOUNCE_BUILD'",
                    action=MacroAction.GOTO,
                    target_flow="build",
                    max_uses=2,
                    description="Gate bounced to build for fixable issues",
                ),
                MacroRoutingRule(
                    rule_id="gate-bounce-plan",
                    condition="gate.verdict == 'BOUNCE_PLAN'",
                    action=MacroAction.GOTO,
                    target_flow="plan",
                    max_uses=1,
                    description="Gate bounced to plan for design issues",
                ),
                # Escalation pauses for human
                MacroRoutingRule(
                    rule_id="gate-escalate",
                    condition="gate.verdict == 'ESCALATE'",
                    action=MacroAction.PAUSE,
                    description="Gate escalated to human for decision",
                ),
                # Hard block terminates
                MacroRoutingRule(
                    rule_id="gate-block",
                    condition="gate.verdict == 'BLOCK'",
                    action=MacroAction.TERMINATE,
                    description="Gate blocked - cannot proceed",
                ),
                # Flow failures terminate by default
                MacroRoutingRule(
                    rule_id="flow-failed",
                    condition="outcome == 'failed'",
                    action=MacroAction.TERMINATE,
                    description="Flow failed with error",
                ),
            ],
            default_action=MacroAction.ADVANCE,
            strict_gate=True,
        )


@dataclass
class HumanPolicy:
    """Policy for human interaction boundaries.

    Controls when and how humans are involved in the flow execution.
    Distinct from the no_human_mid_flow flag which is about within-flow
    interaction; this is about between-flow interaction.

    Attributes:
        mode: "per_flow" (pause after each flow) or "run_end" (only at end).
        allow_pause_mid_flow: Always False - mid-flow pause uses DETOUR.
        allow_pause_between_flows: True for per_flow mode, enables review.
        end_boundary: Where human review happens ("flow_end" or "run_end").
        require_approval_flows: Flows that require explicit human approval.
    """

    mode: str = "run_end"  # "per_flow" or "run_end"
    allow_pause_mid_flow: bool = False  # Always False - use DETOUR instead
    allow_pause_between_flows: bool = False  # True for per_flow mode
    end_boundary: str = "run_end"  # "flow_end" or "run_end"
    require_approval_flows: List[str] = field(default_factory=list)

    @classmethod
    def autopilot(cls) -> "HumanPolicy":
        """Autopilot mode: no human intervention until run end."""
        return cls(
            mode="run_end",
            allow_pause_mid_flow=False,
            allow_pause_between_flows=False,
            end_boundary="run_end",
            require_approval_flows=[],
        )

    @classmethod
    def supervised(cls) -> "HumanPolicy":
        """Supervised mode: pause after each flow for review."""
        return cls(
            mode="per_flow",
            allow_pause_mid_flow=False,
            allow_pause_between_flows=True,
            end_boundary="flow_end",
            require_approval_flows=["gate", "deploy"],
        )


@dataclass
class RunPlanSpec:
    """Macro orchestration policy for flow chaining.

    This is the top-level specification for how flows should be chained
    together during a run. It combines flow sequencing, routing policies,
    and human interaction policies.

    Attributes:
        flow_sequence: Default chain of flows (signal -> wisdom).
        macro_policy: Rules for between-flow routing (looping, retrying).
        human_policy: When humans are involved.
        constraints: Hard constraints that cannot be violated.
        max_total_flows: Safety limit on total flow executions per run.
    """

    flow_sequence: List[str] = field(
        default_factory=_get_default_flow_sequence  # From registry, includes review
    )
    macro_policy: MacroPolicy = field(default_factory=MacroPolicy.default)
    human_policy: HumanPolicy = field(default_factory=HumanPolicy.autopilot)
    constraints: List[str] = field(default_factory=list)
    max_total_flows: int = 20  # Safety limit to prevent infinite loops

    @classmethod
    def default(cls) -> "RunPlanSpec":
        """Create a default RunPlanSpec with standard SDLC configuration."""
        return cls(
            flow_sequence=_get_default_flow_sequence(),  # From registry, includes review
            macro_policy=MacroPolicy.default(),
            human_policy=HumanPolicy.autopilot(),
            constraints=[
                "never deploy unless gate verdict is MERGE or MERGE_WITH_CONDITIONS",
                "never skip gate flow",
                "max 3 bounces between gate and build",
            ],
            max_total_flows=20,
        )


@dataclass
class MacroRoutingDecision:
    """Decision from MacroNavigator about between-flow routing.

    Attributes:
        action: The routing action to take.
        next_flow: The flow to execute next (if advancing/goto).
        reason: Human-readable explanation for the decision.
        rule_applied: The routing rule that triggered this decision.
        confidence: Confidence in this routing decision (0.0 to 1.0).
        constraints_checked: Constraints that were verified.
        warnings: Any warnings about this routing decision.
    """

    action: MacroAction
    next_flow: Optional[str] = None
    reason: str = ""
    rule_applied: Optional[str] = None  # rule_id of the applied rule
    confidence: float = 1.0
    constraints_checked: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


# =============================================================================
# Macro Types Serialization
# =============================================================================


def flow_result_to_dict(result: FlowResult) -> Dict[str, Any]:
    """Convert FlowResult to dictionary for serialization."""
    return {
        "flow_key": result.flow_key,
        "outcome": result.outcome.value,
        "status": result.status,
        "gate_verdict": result.gate_verdict.value if result.gate_verdict else None,
        "bounce_target": result.bounce_target,
        "error": result.error,
        "artifacts": dict(result.artifacts),
        "duration_ms": result.duration_ms,
        "issues": list(result.issues),
        "recommendations": list(result.recommendations),
    }


def flow_result_from_dict(data: Dict[str, Any]) -> FlowResult:
    """Parse FlowResult from dictionary."""
    gate_verdict = None
    if data.get("gate_verdict"):
        gate_verdict = GateVerdict(data["gate_verdict"])

    return FlowResult(
        flow_key=data.get("flow_key", ""),
        outcome=FlowOutcome(data.get("outcome", "succeeded")),
        status=data.get("status", ""),
        gate_verdict=gate_verdict,
        bounce_target=data.get("bounce_target"),
        error=data.get("error"),
        artifacts=dict(data.get("artifacts", {})),
        duration_ms=data.get("duration_ms", 0),
        issues=list(data.get("issues", [])),
        recommendations=list(data.get("recommendations", [])),
    )


def macro_routing_rule_to_dict(rule: MacroRoutingRule) -> Dict[str, Any]:
    """Convert MacroRoutingRule to dictionary."""
    return {
        "rule_id": rule.rule_id,
        "condition": rule.condition,
        "action": rule.action.value,
        "target_flow": rule.target_flow,
        "max_uses": rule.max_uses,
        "uses": rule.uses,
        "description": rule.description,
    }


def macro_routing_rule_from_dict(data: Dict[str, Any]) -> MacroRoutingRule:
    """Parse MacroRoutingRule from dictionary."""
    return MacroRoutingRule(
        rule_id=data.get("rule_id", ""),
        condition=data.get("condition", ""),
        action=MacroAction(data.get("action", "advance")),
        target_flow=data.get("target_flow"),
        max_uses=data.get("max_uses", 3),
        uses=data.get("uses", 0),
        description=data.get("description", ""),
    )


def macro_policy_to_dict(policy: MacroPolicy) -> Dict[str, Any]:
    """Convert MacroPolicy to dictionary."""
    return {
        "allow_flow_repeat": policy.allow_flow_repeat,
        "max_repeats_per_flow": policy.max_repeats_per_flow,
        "routing_rules": [macro_routing_rule_to_dict(r) for r in policy.routing_rules],
        "default_action": policy.default_action.value,
        "strict_gate": policy.strict_gate,
    }


def macro_policy_from_dict(data: Dict[str, Any]) -> MacroPolicy:
    """Parse MacroPolicy from dictionary."""
    return MacroPolicy(
        allow_flow_repeat=data.get("allow_flow_repeat", True),
        max_repeats_per_flow=data.get("max_repeats_per_flow", 3),
        routing_rules=[macro_routing_rule_from_dict(r) for r in data.get("routing_rules", [])],
        default_action=MacroAction(data.get("default_action", "advance")),
        strict_gate=data.get("strict_gate", True),
    )


def human_policy_to_dict(policy: HumanPolicy) -> Dict[str, Any]:
    """Convert HumanPolicy to dictionary."""
    return {
        "mode": policy.mode,
        "allow_pause_mid_flow": policy.allow_pause_mid_flow,
        "allow_pause_between_flows": policy.allow_pause_between_flows,
        "end_boundary": policy.end_boundary,
        "require_approval_flows": list(policy.require_approval_flows),
    }


def human_policy_from_dict(data: Dict[str, Any]) -> HumanPolicy:
    """Parse HumanPolicy from dictionary."""
    return HumanPolicy(
        mode=data.get("mode", "run_end"),
        allow_pause_mid_flow=data.get("allow_pause_mid_flow", False),
        allow_pause_between_flows=data.get("allow_pause_between_flows", False),
        end_boundary=data.get("end_boundary", "run_end"),
        require_approval_flows=list(data.get("require_approval_flows", [])),
    )


def run_plan_spec_to_dict(spec: RunPlanSpec) -> Dict[str, Any]:
    """Convert RunPlanSpec to dictionary."""
    return {
        "flow_sequence": list(spec.flow_sequence),
        "macro_policy": macro_policy_to_dict(spec.macro_policy),
        "human_policy": human_policy_to_dict(spec.human_policy),
        "constraints": list(spec.constraints),
        "max_total_flows": spec.max_total_flows,
    }


def run_plan_spec_from_dict(data: Dict[str, Any]) -> RunPlanSpec:
    """Parse RunPlanSpec from dictionary."""
    return RunPlanSpec(
        flow_sequence=list(data.get("flow_sequence", [])),
        macro_policy=macro_policy_from_dict(data.get("macro_policy", {})),
        human_policy=human_policy_from_dict(data.get("human_policy", {})),
        constraints=list(data.get("constraints", [])),
        max_total_flows=data.get("max_total_flows", 20),
    )


def macro_routing_decision_to_dict(decision: MacroRoutingDecision) -> Dict[str, Any]:
    """Convert MacroRoutingDecision to dictionary."""
    return {
        "action": decision.action.value,
        "next_flow": decision.next_flow,
        "reason": decision.reason,
        "rule_applied": decision.rule_applied,
        "confidence": decision.confidence,
        "constraints_checked": list(decision.constraints_checked),
        "warnings": list(decision.warnings),
    }


def macro_routing_decision_from_dict(data: Dict[str, Any]) -> MacroRoutingDecision:
    """Parse MacroRoutingDecision from dictionary."""
    return MacroRoutingDecision(
        action=MacroAction(data.get("action", "advance")),
        next_flow=data.get("next_flow"),
        reason=data.get("reason", ""),
        rule_applied=data.get("rule_applied"),
        confidence=data.get("confidence", 1.0),
        constraints_checked=list(data.get("constraints_checked", [])),
        warnings=list(data.get("warnings", [])),
    )
