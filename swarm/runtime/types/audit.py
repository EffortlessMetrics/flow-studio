"""Audit types for assumption and decision logging.

This module contains types for tracking assumptions made during flow execution,
decisions logged for audit trails, and observations for the Wisdom Stream.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Literal, Optional, TypedDict

from ._time import _datetime_to_iso, _iso_to_datetime


class ConfidenceLevel(str, Enum):
    """Confidence level for assumptions."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class AssumptionStatus(str, Enum):
    """Status of an assumption through its lifecycle."""

    ACTIVE = "active"  # Assumption is currently in effect
    RESOLVED = "resolved"  # Assumption was confirmed or clarified
    INVALIDATED = "invalidated"  # Assumption was proven wrong


class ObservationType(str, Enum):
    """Types of observations for the Wisdom Stream."""

    ACTION_TAKEN = "action_taken"  # Logged for audit trail
    ACTION_DEFERRED = "action_deferred"  # Noticed but didn't act (due to charter)
    OPTIMIZATION_OPPORTUNITY = "optimization_opportunity"  # Suggestion for spec evolution
    PATTERN_DETECTED = "pattern_detected"  # Recurring behavior worth codifying


class ObservationPriority(str, Enum):
    """Priority levels for observations."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


# Station Opinion types - non-binding witness statements for orchestrator corroboration
StationOpinionKind = Literal[
    "suggest_detour",
    "suggest_repeat",
    "suggest_subflow_injection",
    "suggest_defer_to_wisdom",
    "flag_concern",
]


class StationOpinion(TypedDict, total=False):
    """A non-binding witness statement from a station about what it thinks should happen.

    This is signal for the orchestrator to corroborate via forensics and charter
    alignment, not executable intent. Stations express opinions; orchestrators decide.

    Required keys:
        kind: Type of opinion (suggest_detour, suggest_repeat, suggest_subflow_injection,
              suggest_defer_to_wisdom, flag_concern).
        suggested_action: What the station thinks should happen.
        reason: Why the station thinks this action is appropriate.

    Optional keys:
        evidence_paths: File paths or artifact references supporting this opinion.
        confidence: Confidence score (0-1) in this opinion.
    """

    kind: StationOpinionKind  # type: ignore[misc]
    suggested_action: str
    reason: str
    evidence_paths: List[str]
    confidence: float


@dataclass
class ObservationEntry:
    """Something a station noticed during execution, part of the Wisdom Stream.

    Observations capture things that may not have been acted upon but should be
    considered by Flow 7 (Wisdom) for learning and spec evolution.

    Attributes:
        type: Type of observation (action_taken, action_deferred, optimization_opportunity, pattern_detected).
        observation: What was observed.
        reason: Why action was taken or deferred.
        suggested_action: What Wisdom should consider doing with this observation.
        target_flow: If applicable, which flow this observation is most relevant to.
        priority: How urgently Wisdom should process this.
    """

    type: ObservationType
    observation: str
    reason: Optional[str] = None
    suggested_action: Optional[str] = None
    target_flow: Optional[str] = None
    priority: ObservationPriority = ObservationPriority.LOW


@dataclass
class AssumptionEntry:
    """A structured record of an assumption made during flow execution.

    Assumptions are made when agents face ambiguity and need to proceed
    with their best interpretation. This captures the assumption, its
    rationale, and potential impact if wrong.

    Attributes:
        assumption_id: Unique identifier for this assumption (auto-generated if not provided).
        flow_introduced: Flow key where this assumption was first made.
        step_introduced: Step ID where this assumption was first made.
        agent: Agent key that made this assumption.
        statement: The assumption statement itself.
        rationale: Why this assumption was made (evidence, context).
        impact_if_wrong: What would need to change if assumption is incorrect.
        confidence: Confidence level (high/medium/low).
        status: Current status (active/resolved/invalidated).
        tags: Optional categorization tags (e.g., ["architecture", "requirements"]).
        timestamp: When this assumption was recorded.
        resolution_note: Explanation when status changes to resolved/invalidated.
    """

    assumption_id: str
    flow_introduced: str
    step_introduced: str
    agent: str
    statement: str
    rationale: str
    impact_if_wrong: str
    confidence: ConfidenceLevel = ConfidenceLevel.MEDIUM
    status: AssumptionStatus = AssumptionStatus.ACTIVE
    tags: List[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    resolution_note: Optional[str] = None


@dataclass
class DecisionLogEntry:
    """A structured record of a decision made during flow execution.

    Decisions are significant choices made by agents that affect the
    direction of work. This captures the decision, its context, and
    traceability information.

    Attributes:
        decision_id: Unique identifier for this decision (auto-generated if not provided).
        flow: Flow key where this decision was made.
        step: Step ID where this decision was made.
        agent: Agent key that made this decision.
        decision_type: Category of decision (e.g., "design", "implementation", "routing").
        subject: What the decision is about (e.g., "API design", "test strategy").
        decision: The actual decision made.
        rationale: Why this decision was made.
        supporting_evidence: Evidence that supports this decision.
        conditions: Conditions under which this decision applies.
        assumptions_applied: IDs of assumptions that influenced this decision.
        timestamp: When this decision was recorded.
    """

    decision_id: str
    flow: str
    step: str
    agent: str
    decision_type: str
    subject: str
    decision: str
    rationale: str
    supporting_evidence: List[str] = field(default_factory=list)
    conditions: List[str] = field(default_factory=list)
    assumptions_applied: List[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# =============================================================================
# Serialization Functions
# =============================================================================


def assumption_entry_to_dict(entry: AssumptionEntry) -> Dict[str, Any]:
    """Convert AssumptionEntry to a dictionary for serialization.

    Args:
        entry: The AssumptionEntry to convert.

    Returns:
        Dictionary representation suitable for JSON/JSONL serialization.
    """
    return {
        "assumption_id": entry.assumption_id,
        "flow_introduced": entry.flow_introduced,
        "step_introduced": entry.step_introduced,
        "agent": entry.agent,
        "statement": entry.statement,
        "rationale": entry.rationale,
        "impact_if_wrong": entry.impact_if_wrong,
        "confidence": entry.confidence.value
        if isinstance(entry.confidence, ConfidenceLevel)
        else entry.confidence,
        "status": entry.status.value
        if isinstance(entry.status, AssumptionStatus)
        else entry.status,
        "tags": list(entry.tags),
        "timestamp": _datetime_to_iso(entry.timestamp),
        "resolution_note": entry.resolution_note,
    }


def assumption_entry_from_dict(data: Dict[str, Any]) -> AssumptionEntry:
    """Parse AssumptionEntry from a dictionary.

    Args:
        data: Dictionary with AssumptionEntry fields.

    Returns:
        Parsed AssumptionEntry instance.
    """
    confidence_value = data.get("confidence", "medium")
    confidence = (
        ConfidenceLevel(confidence_value) if isinstance(confidence_value, str) else confidence_value
    )

    status_value = data.get("status", "active")
    status = AssumptionStatus(status_value) if isinstance(status_value, str) else status_value

    return AssumptionEntry(
        assumption_id=data.get("assumption_id", ""),
        flow_introduced=data.get("flow_introduced", ""),
        step_introduced=data.get("step_introduced", ""),
        agent=data.get("agent", ""),
        statement=data.get("statement", ""),
        rationale=data.get("rationale", ""),
        impact_if_wrong=data.get("impact_if_wrong", ""),
        confidence=confidence,
        status=status,
        tags=list(data.get("tags", [])),
        timestamp=_iso_to_datetime(data.get("timestamp")) or datetime.now(timezone.utc),
        resolution_note=data.get("resolution_note"),
    )


def decision_log_entry_to_dict(entry: DecisionLogEntry) -> Dict[str, Any]:
    """Convert DecisionLogEntry to a dictionary for serialization.

    Args:
        entry: The DecisionLogEntry to convert.

    Returns:
        Dictionary representation suitable for JSON/JSONL serialization.
    """
    return {
        "decision_id": entry.decision_id,
        "flow": entry.flow,
        "step": entry.step,
        "agent": entry.agent,
        "decision_type": entry.decision_type,
        "subject": entry.subject,
        "decision": entry.decision,
        "rationale": entry.rationale,
        "supporting_evidence": list(entry.supporting_evidence),
        "conditions": list(entry.conditions),
        "assumptions_applied": list(entry.assumptions_applied),
        "timestamp": _datetime_to_iso(entry.timestamp),
    }


def decision_log_entry_from_dict(data: Dict[str, Any]) -> DecisionLogEntry:
    """Parse DecisionLogEntry from a dictionary.

    Args:
        data: Dictionary with DecisionLogEntry fields.

    Returns:
        Parsed DecisionLogEntry instance.
    """
    return DecisionLogEntry(
        decision_id=data.get("decision_id", ""),
        flow=data.get("flow", ""),
        step=data.get("step", ""),
        agent=data.get("agent", ""),
        decision_type=data.get("decision_type", ""),
        subject=data.get("subject", ""),
        decision=data.get("decision", ""),
        rationale=data.get("rationale", ""),
        supporting_evidence=list(data.get("supporting_evidence", [])),
        conditions=list(data.get("conditions", [])),
        assumptions_applied=list(data.get("assumptions_applied", [])),
        timestamp=_iso_to_datetime(data.get("timestamp")) or datetime.now(timezone.utc),
    )
