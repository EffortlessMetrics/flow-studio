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
        HandoffEnvelope, RunState,
        InterruptionFrame, ResumePoint, InjectedNode,
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
    )
"""

from __future__ import annotations

import secrets
import string
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

# Event ID generation: prefer ulid for time-ordered IDs, fall back to uuid4
try:
    import ulid

    def _generate_event_id() -> str:
        """Generate a globally unique event ID using ULID."""
        return str(ulid.new())
except ImportError:
    import uuid

    def _generate_event_id() -> str:
        """Generate a globally unique event ID using UUID4."""
        return str(uuid.uuid4())

# Type aliases
RunId = str
BackendId = Literal[
    "claude-harness",
    "claude-agent-sdk",
    "claude-step-orchestrator",
    "gemini-cli",
    "gemini-step-orchestrator",
    "custom-cli",
]


class RunStatus(str, Enum):
    """Status of a run's execution lifecycle."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"
    PARTIAL = "partial"  # Interrupted mid-run, resumable from saved cursor


class SDLCStatus(str, Enum):
    """Status reflecting SDLC health/quality outcome."""

    OK = "ok"
    WARNING = "warning"
    ERROR = "error"
    UNKNOWN = "unknown"
    PARTIAL = "partial"  # Interrupted mid-run, work is incomplete


class RoutingDecision(str, Enum):
    """Routing decision types for stepwise execution."""

    ADVANCE = "advance"
    LOOP = "loop"
    TERMINATE = "terminate"
    BRANCH = "branch"


class DecisionType(str, Enum):
    """How the routing decision was made - for auditability."""

    EXPLICIT = "explicit"  # Step output specified next_step_id directly
    EXIT_CONDITION = "exit_condition"  # Microloop termination (VERIFIED, max_iterations)
    DETERMINISTIC = "deterministic"  # Single outgoing edge or edge with condition=true
    CEL = "cel"  # Edge conditions evaluated against step context
    LLM_TIEBREAKER = "llm_tiebreaker"  # LLM chose among valid edges
    LLM_ANALYSIS = "llm_analysis"  # LLM performed deeper analysis
    ERROR = "error"  # Routing failed


@dataclass
class RoutingFactor:
    """A factor considered during LLM routing analysis."""

    name: str
    impact: str  # "strongly_favors", "favors", "neutral", "against", "strongly_against"
    evidence: Optional[str] = None
    weight: float = 0.5


@dataclass
class EdgeOption:
    """An edge option considered during routing."""

    edge_id: str
    target_node: str
    edge_type: str = "sequence"
    priority: int = 50
    evaluated_result: Optional[bool] = None
    score: Optional[float] = None  # LLM-assigned feasibility score


@dataclass
class Elimination:
    """Record of why an edge was eliminated."""

    edge_id: str
    reason_code: str  # condition_false, priority_lower, exit_condition_met, etc.
    detail: str = ""


@dataclass
class LLMReasoning:
    """Structured output from LLM routing analysis."""

    model_used: str = ""
    prompt_hash: str = ""
    response_time_ms: int = 0
    factors_considered: List[RoutingFactor] = field(default_factory=list)
    option_scores: Dict[str, float] = field(default_factory=dict)  # edge_id -> score
    primary_justification: str = ""
    risks_identified: List[Dict[str, str]] = field(default_factory=list)
    assumptions_made: List[str] = field(default_factory=list)


@dataclass
class CELEvaluation:
    """CEL expression evaluation results."""

    expressions_evaluated: List[Dict[str, Any]] = field(default_factory=list)
    context_variables: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MicroloopContext:
    """Context for microloop routing decisions."""

    iteration: int = 1
    max_iterations: int = 3
    loop_target: str = ""
    exit_status: str = ""
    can_further_iteration_help: bool = True
    status_history: List[str] = field(default_factory=list)


@dataclass
class DecisionMetrics:
    """Metrics about the routing decision process."""

    total_time_ms: int = 0
    edges_total: int = 0
    edges_eliminated: int = 0
    llm_calls: int = 0
    cel_evaluations: int = 0


# =============================================================================
# WP4: Simplified Routing Explanation for Audit Trail
# =============================================================================
# The WP4 routing_explanation.schema.json uses a simpler format optimized for
# audit trails. This coexists with the more detailed RoutingExplanation below.


@dataclass
class WP4EliminationEntry:
    """Entry in the WP4 elimination log.

    Attributes:
        edge_id: ID of the eliminated edge.
        reason: Why this edge was eliminated.
        stage: At which stage the edge was eliminated.
    """

    edge_id: str
    reason: str
    stage: str  # "condition", "constraint", "priority", "llm_tiebreak"


@dataclass
class WP4RoutingMetrics:
    """Metrics for WP4 routing explanation.

    Attributes:
        edges_considered: Total number of edges initially considered.
        time_ms: Time taken for routing decision in milliseconds.
        llm_tokens_used: Tokens used for LLM tiebreaker (if applicable).
    """

    edges_considered: int = 0
    time_ms: float = 0.0
    llm_tokens_used: int = 0


@dataclass
class WP4RoutingExplanation:
    """WP4-compliant routing explanation for bounded, auditable, cheap routing.

    This dataclass matches the WP4 routing_explanation.schema.json format,
    providing a simpler structure optimized for audit trails.

    Attributes:
        decision: Human-readable summary of the routing decision.
        method: How the decision was made (deterministic, llm_tiebreak, no_candidates).
        selected_edge: ID of the selected edge (or empty string if flow terminates).
        candidates_evaluated: Number of candidate edges that were evaluated.
        elimination_log: Log of edges eliminated during routing and why.
        llm_reasoning: LLM's explanation when llm_tiebreak was used.
        metrics: Timing and cost metrics for the routing decision.
    """

    decision: str
    method: str  # "deterministic", "llm_tiebreak", "no_candidates"
    selected_edge: str
    candidates_evaluated: int = 0
    elimination_log: List[WP4EliminationEntry] = field(default_factory=list)
    llm_reasoning: Optional[str] = None
    metrics: Optional[WP4RoutingMetrics] = None


@dataclass
class RoutingExplanation:
    """Structured explanation of routing decisions for auditability.

    Context-efficient JSON format capturing how and why routing decisions
    were made, including LLM reasoning when applicable.
    """

    decision_type: DecisionType
    selected_target: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    confidence: float = 1.0
    reasoning_summary: str = ""
    available_edges: List[EdgeOption] = field(default_factory=list)
    elimination_log: List[Elimination] = field(default_factory=list)
    llm_reasoning: Optional[LLMReasoning] = None
    cel_evaluation: Optional[CELEvaluation] = None
    microloop_context: Optional[MicroloopContext] = None
    metrics: Optional[DecisionMetrics] = None


@dataclass
class RoutingSignal:
    """Normalized routing decision signal for stepwise flow execution.

    Encapsulates the judgment about where to go next in a flow, providing
    structured, machine-readable routing decisions instead of fragile receipt
    field parsing.

    Attributes:
        decision: The routing decision (advance, loop, terminate, branch).
        next_step_id: The ID of the next step to execute (for advance/branch).
        route: Named route identifier (for branch routing).
        reason: Human-readable explanation for the routing decision.
        confidence: Confidence score for this decision (0.0 to 1.0).
        needs_human: Whether human intervention is required before proceeding.
        next_flow: Flow key for macro-routing (flow transitions).
        loop_count: Current iteration count for microloop tracking.
        exit_condition_met: Whether the termination condition has been met.
    """

    decision: RoutingDecision
    next_step_id: Optional[str] = None
    route: Optional[str] = None
    reason: str = ""
    confidence: float = 1.0
    needs_human: bool = False
    # Macro-routing and microloop tracking fields
    next_flow: Optional[str] = None
    loop_count: int = 0
    exit_condition_met: bool = False
    # Structured routing explanation (optional, for audit/debug)
    explanation: Optional[RoutingExplanation] = None


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
    """

    flow_keys: List[str]
    profile_id: Optional[str] = None
    backend: BackendId = "claude-harness"
    initiator: str = "cli"
    params: Dict[str, Any] = field(default_factory=dict)


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
# Run ID Generation
# -----------------------------------------------------------------------------


def generate_run_id() -> RunId:
    """Generate a unique run ID.

    Creates IDs in the format: run-YYYYMMDD-HHMMSS-xxxxxx
    where xxxxxx is a random 6-character alphanumeric suffix.

    Returns:
        A unique run identifier string.

    Example:
        >>> run_id = generate_run_id()
        >>> run_id  # e.g., "run-20251208-143022-abc123"
    """
    now = datetime.now(timezone.utc)
    timestamp = now.strftime("%Y%m%d-%H%M%S")
    suffix = "".join(
        secrets.choice(string.ascii_lowercase + string.digits) for _ in range(6)
    )
    return f"run-{timestamp}-{suffix}"


# -----------------------------------------------------------------------------
# Serialization Helpers
# -----------------------------------------------------------------------------


def _datetime_to_iso(dt: Optional[datetime]) -> Optional[str]:
    """Convert datetime to ISO format string with Z suffix."""
    if dt is None:
        return None
    return dt.isoformat() + "Z" if not dt.isoformat().endswith("Z") else dt.isoformat()


def _iso_to_datetime(iso_str: Optional[str]) -> Optional[datetime]:
    """Parse ISO format string to datetime."""
    if iso_str is None:
        return None
    # Remove Z suffix if present for parsing
    if iso_str.endswith("Z"):
        iso_str = iso_str[:-1]
    return datetime.fromisoformat(iso_str)


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


# -----------------------------------------------------------------------------
# RoutingSignal Serialization
# -----------------------------------------------------------------------------


def routing_explanation_to_dict(explanation: RoutingExplanation) -> Dict[str, Any]:
    """Convert RoutingExplanation to a dictionary for serialization.

    Args:
        explanation: The RoutingExplanation to convert.

    Returns:
        Dictionary representation suitable for JSON serialization.
    """
    result: Dict[str, Any] = {
        "decision_type": explanation.decision_type.value,
        "selected_target": explanation.selected_target,
        "timestamp": _datetime_to_iso(explanation.timestamp),
        "confidence": explanation.confidence,
        "reasoning_summary": explanation.reasoning_summary,
    }

    if explanation.available_edges:
        result["available_edges"] = [
            {
                "edge_id": e.edge_id,
                "target_node": e.target_node,
                "edge_type": e.edge_type,
                "priority": e.priority,
                "evaluated_result": e.evaluated_result,
                "score": e.score,
            }
            for e in explanation.available_edges
        ]

    if explanation.elimination_log:
        result["elimination_log"] = [
            {"edge_id": e.edge_id, "reason_code": e.reason_code, "detail": e.detail}
            for e in explanation.elimination_log
        ]

    if explanation.llm_reasoning:
        llm = explanation.llm_reasoning
        result["llm_reasoning"] = {
            "model_used": llm.model_used,
            "prompt_hash": llm.prompt_hash,
            "response_time_ms": llm.response_time_ms,
            "factors_considered": [
                {"name": f.name, "impact": f.impact, "evidence": f.evidence, "weight": f.weight}
                for f in llm.factors_considered
            ],
            "option_scores": dict(llm.option_scores),
            "primary_justification": llm.primary_justification,
            "risks_identified": llm.risks_identified,
            "assumptions_made": llm.assumptions_made,
        }

    if explanation.cel_evaluation:
        result["cel_evaluation"] = {
            "expressions_evaluated": explanation.cel_evaluation.expressions_evaluated,
            "context_variables": explanation.cel_evaluation.context_variables,
        }

    if explanation.microloop_context:
        mc = explanation.microloop_context
        result["microloop_context"] = {
            "iteration": mc.iteration,
            "max_iterations": mc.max_iterations,
            "loop_target": mc.loop_target,
            "exit_status": mc.exit_status,
            "can_further_iteration_help": mc.can_further_iteration_help,
            "status_history": mc.status_history,
        }

    if explanation.metrics:
        result["metrics"] = {
            "total_time_ms": explanation.metrics.total_time_ms,
            "edges_total": explanation.metrics.edges_total,
            "edges_eliminated": explanation.metrics.edges_eliminated,
            "llm_calls": explanation.metrics.llm_calls,
            "cel_evaluations": explanation.metrics.cel_evaluations,
        }

    return result


def routing_explanation_from_dict(data: Dict[str, Any]) -> RoutingExplanation:
    """Parse RoutingExplanation from a dictionary.

    Args:
        data: Dictionary with RoutingExplanation fields.

    Returns:
        Parsed RoutingExplanation instance.
    """
    available_edges = [
        EdgeOption(
            edge_id=e.get("edge_id", ""),
            target_node=e.get("target_node", ""),
            edge_type=e.get("edge_type", "sequence"),
            priority=e.get("priority", 50),
            evaluated_result=e.get("evaluated_result"),
            score=e.get("score"),
        )
        for e in data.get("available_edges", [])
    ]

    elimination_log = [
        Elimination(
            edge_id=e.get("edge_id", ""),
            reason_code=e.get("reason_code", ""),
            detail=e.get("detail", ""),
        )
        for e in data.get("elimination_log", [])
    ]

    llm_reasoning = None
    if "llm_reasoning" in data:
        llm_data = data["llm_reasoning"]
        llm_reasoning = LLMReasoning(
            model_used=llm_data.get("model_used", ""),
            prompt_hash=llm_data.get("prompt_hash", ""),
            response_time_ms=llm_data.get("response_time_ms", 0),
            factors_considered=[
                RoutingFactor(
                    name=f.get("name", ""),
                    impact=f.get("impact", "neutral"),
                    evidence=f.get("evidence"),
                    weight=f.get("weight", 0.5),
                )
                for f in llm_data.get("factors_considered", [])
            ],
            option_scores=dict(llm_data.get("option_scores", {})),
            primary_justification=llm_data.get("primary_justification", ""),
            risks_identified=llm_data.get("risks_identified", []),
            assumptions_made=llm_data.get("assumptions_made", []),
        )

    cel_evaluation = None
    if "cel_evaluation" in data:
        cel_data = data["cel_evaluation"]
        cel_evaluation = CELEvaluation(
            expressions_evaluated=cel_data.get("expressions_evaluated", []),
            context_variables=cel_data.get("context_variables", {}),
        )

    microloop_context = None
    if "microloop_context" in data:
        mc_data = data["microloop_context"]
        microloop_context = MicroloopContext(
            iteration=mc_data.get("iteration", 1),
            max_iterations=mc_data.get("max_iterations", 3),
            loop_target=mc_data.get("loop_target", ""),
            exit_status=mc_data.get("exit_status", ""),
            can_further_iteration_help=mc_data.get("can_further_iteration_help", True),
            status_history=mc_data.get("status_history", []),
        )

    metrics = None
    if "metrics" in data:
        m_data = data["metrics"]
        metrics = DecisionMetrics(
            total_time_ms=m_data.get("total_time_ms", 0),
            edges_total=m_data.get("edges_total", 0),
            edges_eliminated=m_data.get("edges_eliminated", 0),
            llm_calls=m_data.get("llm_calls", 0),
            cel_evaluations=m_data.get("cel_evaluations", 0),
        )

    return RoutingExplanation(
        decision_type=DecisionType(data.get("decision_type", "deterministic")),
        selected_target=data.get("selected_target", ""),
        timestamp=_iso_to_datetime(data.get("timestamp")) or datetime.now(timezone.utc),
        confidence=data.get("confidence", 1.0),
        reasoning_summary=data.get("reasoning_summary", ""),
        available_edges=available_edges,
        elimination_log=elimination_log,
        llm_reasoning=llm_reasoning,
        cel_evaluation=cel_evaluation,
        microloop_context=microloop_context,
        metrics=metrics,
    )


# -----------------------------------------------------------------------------
# WP4 Routing Explanation Serialization
# -----------------------------------------------------------------------------


def wp4_routing_explanation_to_dict(explanation: WP4RoutingExplanation) -> Dict[str, Any]:
    """Convert WP4RoutingExplanation to a dictionary for serialization.

    Args:
        explanation: The WP4RoutingExplanation to convert.

    Returns:
        Dictionary representation matching routing_explanation.schema.json.
    """
    result: Dict[str, Any] = {
        "decision": explanation.decision,
        "method": explanation.method,
        "selected_edge": explanation.selected_edge,
        "candidates_evaluated": explanation.candidates_evaluated,
    }

    if explanation.elimination_log:
        result["elimination_log"] = [
            {
                "edge_id": e.edge_id,
                "reason": e.reason,
                "stage": e.stage,
            }
            for e in explanation.elimination_log
        ]

    if explanation.llm_reasoning:
        result["llm_reasoning"] = explanation.llm_reasoning

    if explanation.metrics:
        result["metrics"] = {
            "edges_considered": explanation.metrics.edges_considered,
            "time_ms": explanation.metrics.time_ms,
        }
        if explanation.metrics.llm_tokens_used:
            result["metrics"]["llm_tokens_used"] = explanation.metrics.llm_tokens_used

    return result


def wp4_routing_explanation_from_dict(data: Dict[str, Any]) -> WP4RoutingExplanation:
    """Parse WP4RoutingExplanation from a dictionary.

    Args:
        data: Dictionary with WP4RoutingExplanation fields.

    Returns:
        Parsed WP4RoutingExplanation instance.
    """
    elimination_log = [
        WP4EliminationEntry(
            edge_id=e.get("edge_id", ""),
            reason=e.get("reason", ""),
            stage=e.get("stage", "condition"),
        )
        for e in data.get("elimination_log", [])
    ]

    metrics = None
    if "metrics" in data:
        m = data["metrics"]
        metrics = WP4RoutingMetrics(
            edges_considered=m.get("edges_considered", 0),
            time_ms=m.get("time_ms", 0.0),
            llm_tokens_used=m.get("llm_tokens_used", 0),
        )

    return WP4RoutingExplanation(
        decision=data.get("decision", ""),
        method=data.get("method", "deterministic"),
        selected_edge=data.get("selected_edge", ""),
        candidates_evaluated=data.get("candidates_evaluated", 0),
        elimination_log=elimination_log,
        llm_reasoning=data.get("llm_reasoning"),
        metrics=metrics,
    )


def routing_signal_to_dict(signal: RoutingSignal) -> Dict[str, Any]:
    """Convert RoutingSignal to a dictionary for serialization.

    Args:
        signal: The RoutingSignal to convert.

    Returns:
        Dictionary representation suitable for JSON/YAML serialization.
    """
    result = {
        "decision": signal.decision.value if isinstance(signal.decision, RoutingDecision) else signal.decision,
        "next_step_id": signal.next_step_id,
        "route": signal.route,
        "reason": signal.reason,
        "confidence": signal.confidence,
        "needs_human": signal.needs_human,
        "next_flow": signal.next_flow,
        "loop_count": signal.loop_count,
        "exit_condition_met": signal.exit_condition_met,
    }

    if signal.explanation:
        result["explanation"] = routing_explanation_to_dict(signal.explanation)

    return result


def routing_signal_from_dict(data: Dict[str, Any]) -> RoutingSignal:
    """Parse RoutingSignal from a dictionary.

    Args:
        data: Dictionary with RoutingSignal fields.

    Returns:
        Parsed RoutingSignal instance.

    Note:
        Provides backwards compatibility for signals missing the new
        next_flow, loop_count, exit_condition_met, or explanation fields.
    """
    decision_value = data.get("decision", "advance")
    decision = RoutingDecision(decision_value) if isinstance(decision_value, str) else decision_value

    explanation = None
    if "explanation" in data:
        explanation = routing_explanation_from_dict(data["explanation"])

    return RoutingSignal(
        decision=decision,
        next_step_id=data.get("next_step_id"),
        route=data.get("route"),
        reason=data.get("reason", ""),
        confidence=data.get("confidence", 1.0),
        needs_human=data.get("needs_human", False),
        next_flow=data.get("next_flow"),
        loop_count=data.get("loop_count", 0),
        exit_condition_met=data.get("exit_condition_met", False),
        explanation=explanation,
    )


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
        verification_passed, verification_details, routing_audit).
    """
    routing_signal_data = data.get("routing_signal", {})
    routing_signal = routing_signal_from_dict(routing_signal_data)

    # Parse routing_audit if present (store as raw dict for flexibility)
    routing_audit = data.get("routing_audit")

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
    """

    reason: str
    interrupted_at: datetime
    return_node: str
    context_snapshot: Dict[str, Any] = field(default_factory=dict)


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
    completed_nodes: List[str] = field(default_factory=list)

    # -------------------------------------------------------------------------
    # Detour Stack Operations
    # -------------------------------------------------------------------------

    def push_interruption(
        self,
        reason: str,
        return_node: str,
        context_snapshot: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Push an interruption frame onto the stack.

        Call this when pausing execution for a detour. The return_node
        specifies where to continue after the detour completes.

        Args:
            reason: Human-readable reason for the interruption.
            return_node: Node ID to return to after detour.
            context_snapshot: Optional context to restore on resume.
        """
        frame = InterruptionFrame(
            reason=reason,
            interrupted_at=datetime.now(timezone.utc),
            return_node=return_node,
            context_snapshot=context_snapshot or {},
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
            interruption_frame_to_dict(frame)
            for frame in state.interruption_stack
        ],
        "resume_stack": [
            resume_point_to_dict(point)
            for point in state.resume_stack
        ],
        "injected_nodes": list(state.injected_nodes),
        "completed_nodes": list(state.completed_nodes),
        # Schema-compatible aliases
        "artifacts": {
            step_id: env.artifacts if hasattr(env, 'artifacts') else {}
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
        interruption_frame_from_dict(frame_data)
        for frame_data in interruption_stack_data
    ]

    # Parse resume stack
    resume_stack_data = data.get("resume_stack", [])
    resume_stack = [
        resume_point_from_dict(point_data)
        for point_data in resume_stack_data
    ]

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
        completed_nodes=list(data.get("completed_nodes", [])),
    )
