"""Handoff types for cross-step communication.

This module contains the HandoffEnvelope type and its serialization functions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ._time import _datetime_to_iso, _iso_to_datetime
from .audit import (
    AssumptionEntry,
    DecisionLogEntry,
    ObservationEntry,
    StationOpinion,
    assumption_entry_from_dict,
    assumption_entry_to_dict,
    decision_log_entry_from_dict,
    decision_log_entry_to_dict,
)
from .routing import (
    RoutingSignal,
    routing_explanation_to_dict,
    routing_signal_from_dict,
    routing_signal_to_dict,
)


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


# =============================================================================
# Serialization Functions
# =============================================================================


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
        # Spec traceability
        "station_id": envelope.station_id,
        "station_version": envelope.station_version,
        "prompt_hash": envelope.prompt_hash,
        "verification_passed": envelope.verification_passed,
        "verification_details": dict(envelope.verification_details),
    }

    # Include routing audit if present
    if envelope.routing_audit:
        result["routing_audit"] = envelope.routing_audit
    elif envelope.routing_signal.explanation:
        # Auto-populate routing audit from explanation if not explicitly set
        result["routing_audit"] = routing_explanation_to_dict(
            envelope.routing_signal.explanation
        )

    # Serialize assumptions and decisions
    if envelope.assumptions_made:
        result["assumptions_made"] = [
            assumption_entry_to_dict(a) for a in envelope.assumptions_made
        ]
    else:
        result["assumptions_made"] = []

    if envelope.decisions_made:
        result["decisions_made"] = [
            decision_log_entry_to_dict(d) for d in envelope.decisions_made
        ]
    else:
        result["decisions_made"] = []

    # Serialize observations
    if envelope.observations:
        result["observations"] = [
            {
                "type": obs.type.value,
                "observation": obs.observation,
                "reason": obs.reason,
                "suggested_action": obs.suggested_action,
                "target_flow": obs.target_flow,
                "priority": obs.priority.value,
            }
            for obs in envelope.observations
        ]
    else:
        result["observations"] = []

    # Serialize station opinions
    if envelope.station_opinions:
        result["station_opinions"] = [dict(op) for op in envelope.station_opinions]
    else:
        result["station_opinions"] = []

    return result


def handoff_envelope_from_dict(data: Dict[str, Any]) -> HandoffEnvelope:
    """Parse HandoffEnvelope from a dictionary.

    Args:
        data: Dictionary with HandoffEnvelope fields.

    Returns:
        Parsed HandoffEnvelope instance.
    """
    from .audit import ObservationPriority, ObservationType

    routing_signal = routing_signal_from_dict(data.get("routing_signal", {}))

    # Parse assumptions
    assumptions_made = [
        assumption_entry_from_dict(a) for a in data.get("assumptions_made", [])
    ]

    # Parse decisions
    decisions_made = [
        decision_log_entry_from_dict(d) for d in data.get("decisions_made", [])
    ]

    # Parse observations
    observations = []
    for obs in data.get("observations", []):
        observations.append(
            ObservationEntry(
                type=ObservationType(obs.get("type", "action_taken")),
                observation=obs.get("observation", ""),
                reason=obs.get("reason"),
                suggested_action=obs.get("suggested_action"),
                target_flow=obs.get("target_flow"),
                priority=ObservationPriority(obs.get("priority", "low")),
            )
        )

    # Parse station opinions (TypedDict, so just cast)
    station_opinions: List[StationOpinion] = []
    for op in data.get("station_opinions", []):
        station_opinions.append(
            StationOpinion(
                kind=op.get("kind", "flag_concern"),
                suggested_action=op.get("suggested_action", ""),
                reason=op.get("reason", ""),
                evidence_paths=op.get("evidence_paths", []),
                confidence=op.get("confidence", 0.5),
            )
        )

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
        station_id=data.get("station_id"),
        station_version=data.get("station_version"),
        prompt_hash=data.get("prompt_hash"),
        verification_passed=data.get("verification_passed", True),
        verification_details=dict(data.get("verification_details", {})),
        routing_audit=data.get("routing_audit"),
        assumptions_made=assumptions_made,
        decisions_made=decisions_made,
        observations=observations,
        station_opinions=station_opinions,
    )
