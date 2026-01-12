"""Routing types for within-flow navigation.

This module contains types related to routing decisions made by the Navigator
during stepwise flow execution. These are "micro-routing" types for within-flow
decisions, as opposed to "macro-routing" types for between-flow decisions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Any, Dict, List, Optional, TypedDict

from ._time import _datetime_to_iso, _iso_to_datetime

if TYPE_CHECKING:
    pass  # Future use for type-only imports


class RoutingDecision(str, Enum):
    """Routing decision types for stepwise execution."""

    ADVANCE = "advance"
    LOOP = "loop"
    TERMINATE = "terminate"
    BRANCH = "branch"
    SKIP = "skip"


class DecisionType(str, Enum):
    """How the routing decision was made - for auditability."""

    EXPLICIT = "explicit"  # Step output specified next_step_id directly
    EXIT_CONDITION = "exit_condition"  # Microloop termination (VERIFIED, max_iterations)
    DETERMINISTIC = "deterministic"  # Single outgoing edge or edge with condition=true
    CEL = "cel"  # Edge conditions evaluated against step context
    LLM_TIEBREAKER = "llm_tiebreaker"  # LLM chose among valid edges
    LLM_ANALYSIS = "llm_analysis"  # LLM performed deeper analysis
    ERROR = "error"  # Routing failed


class RoutingMode(str, Enum):
    """Routing mode controlling Navigator behavior in the orchestrator.

    This enum controls the balance between deterministic Python routing
    and intelligent Navigator-based routing:

    - DETERMINISTIC_ONLY: No LLM routing calls. Used for CI, debugging,
      and reproducibility. Python fast-path handles all routing.

    - ASSIST (default): Python gates + candidates, Navigator chooses.
      Fast-path handles obvious cases. Navigator handles complex routing.
      Python can override only via hard gates.

    - AUTHORITATIVE: Navigator can propose EXTEND_GRAPH and detours
      more freely. Python still enforces invariants and stack rules,
      but Navigator has more latitude to innovate.
    """

    DETERMINISTIC_ONLY = "deterministic_only"
    ASSIST = "assist"
    AUTHORITATIVE = "authoritative"


class SkipJustification(TypedDict):
    """High-friction justification required when decision is 'skip'.

    Skipping is subtractive (removing expected verification) and requires explicit
    justification to create an audit trail. Detouring (additive) should be cheap;
    skipping requires friction.

    All fields are required to ensure proper accountability when nodes are skipped.

    Attributes:
        skip_reason: Why this node is being skipped.
        why_not_needed_for_exit: Why this node is not needed to satisfy the
            flow's exit criteria.
        replacement_assurance: What replaces this node's verification (e.g., a
            different step, pre-existing artifact, or external validation).
    """

    skip_reason: str
    why_not_needed_for_exit: str
    replacement_assurance: str


@dataclass
class WhyNowJustification:
    """Structured justification for routing deviations (DETOUR, INJECT_FLOW, INJECT_NODES).

    Required when routing goes off the golden path. Creates forensic trail for
    Wisdom analysis and debugging.

    Attributes:
        trigger: What triggered this deviation (e.g., "Tests failed with Method Not Found").
        relevance_to_charter: How this deviation serves the flow's charter goal.
        analysis: Root cause analysis (optional but recommended).
        alternatives_considered: Other options evaluated before choosing this deviation.
        expected_outcome: What this deviation is expected to accomplish.
    """

    trigger: str
    relevance_to_charter: str
    analysis: Optional[str] = None
    alternatives_considered: List[str] = field(default_factory=list)
    expected_outcome: Optional[str] = None


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
    """Context for microloop routing decisions.

    Note: max_iterations is a safety fuse, not a steering mechanism.
    Actual loop exit should be driven by:
    1. VERIFIED status from critic
    2. Stall detection via ProgressTracker (same failure signature repeating)
    3. can_further_iteration_help == False from critic

    The high default (50) ensures loops don't terminate prematurely
    while the fuse prevents infinite loops.
    """

    iteration: int = 1
    max_iterations: int = 50  # Safety fuse, not steering - use stall detection
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


@dataclass
class StallContext:
    """Context from ProgressTracker for stall detection (Elephant Protocol).

    Captures stall detection signals from the ProgressTracker to inform
    routing decisions and provide audit trail for why sidequests were
    triggered or escalations occurred.

    The Elephant Protocol: Progress is measured by velocity (the derivative),
    not budget. If error signatures remain identical, velocity is zero
    and we're stalled.

    Attributes:
        is_stalled: Whether the tracker considers progress stalled.
        stall_count: Number of consecutive identical error signatures.
        velocity: Progress velocity (0.0 = fully stalled, 1.0 = all different).
        last_signature: Most recent error signature (for debugging/audit).
        recommendation: Suggested action (continue, investigate, escalate).
        triggered_sidequest: If stall triggered a sidequest, which one.
    """

    is_stalled: bool = False
    stall_count: int = 0
    velocity: float = 1.0
    last_signature: str = ""
    recommendation: str = "continue"  # continue, investigate, escalate
    triggered_sidequest: Optional[str] = None  # sidequest_id if triggered


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
    stall_context: Optional[StallContext] = None  # Elephant Protocol stall detection


@dataclass
class RoutingCandidate:
    """A candidate routing decision for the Navigator to choose from.

    The candidate-set pattern: Python generates candidates from the graph,
    Navigator intelligently chooses among them, Python validates and executes.

    This keeps intelligence bounded while preserving graph constraints.

    Attributes:
        candidate_id: Unique identifier for this candidate.
        action: The routing action (advance, loop, detour, escalate, repeat).
        target_node: Target node ID for advance/loop/detour.
        reason: Human-readable explanation of why this is a candidate.
        priority: Priority score (0-100, higher = more likely default).
        source: Where this candidate came from (graph_edge, fast_path, detour_catalog).
        evidence_pointers: References to evidence supporting this candidate.
        is_default: Whether this is the default/suggested choice.
    """

    candidate_id: str
    action: str  # "advance" | "loop" | "detour" | "escalate" | "repeat" | "terminate"
    target_node: Optional[str] = None
    reason: str = ""
    priority: int = 50
    source: str = "graph_edge"  # "graph_edge" | "fast_path" | "detour_catalog" | "extend_graph"
    evidence_pointers: List[str] = field(default_factory=list)
    is_default: bool = False


@dataclass
class RoutingSignal:
    """Normalized routing decision signal for stepwise flow execution.

    Encapsulates the judgment about where to go next in a flow, providing
    structured, machine-readable routing decisions instead of fragile receipt
    field parsing.

    Attributes:
        decision: The routing decision (advance, loop, terminate, branch, skip).
        next_step_id: The ID of the next step to execute (for advance/branch).
        route: Named route identifier (for branch routing).
        reason: Human-readable explanation for the routing decision.
        confidence: Confidence score for this decision (0.0 to 1.0).
        needs_human: Whether human intervention is required before proceeding.
        next_flow: Flow key for macro-routing (flow transitions).
        loop_count: Current iteration count for microloop tracking.
        exit_condition_met: Whether the termination condition has been met.
        chosen_candidate_id: ID of the candidate chosen by Navigator.
        routing_candidates: Pre-computed candidates available for this decision.
        routing_source: How this decision was made (navigator, fast_path, etc.).
        skip_justification: High-friction justification required for SKIP decisions.
            Skipping is subtractive and requires explicit audit trail.
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
    # Candidate-set pattern fields (audit trail for Navigator decisions)
    chosen_candidate_id: Optional[str] = None  # ID of selected candidate
    routing_candidates: List[RoutingCandidate] = field(default_factory=list)  # Available candidates
    routing_source: str = "navigator"  # "navigator" | "fast_path" | "deterministic_fallback" | "config_default"
    # Structured routing explanation (optional, for audit/debug)
    explanation: Optional[RoutingExplanation] = None
    # Why-now justification for off-path routing (required for DETOUR/INJECT_*)
    why_now: Optional[WhyNowJustification] = None
    # High-friction skip justification (required for SKIP decisions)
    skip_justification: Optional[SkipJustification] = None


# =============================================================================
# Serialization Functions
# =============================================================================


def routing_candidate_to_dict(candidate: RoutingCandidate) -> Dict[str, Any]:
    """Convert RoutingCandidate to dict for serialization."""
    return {
        "candidate_id": candidate.candidate_id,
        "action": candidate.action,
        "target_node": candidate.target_node,
        "reason": candidate.reason,
        "priority": candidate.priority,
        "source": candidate.source,
        "evidence_pointers": candidate.evidence_pointers,
        "is_default": candidate.is_default,
    }


def routing_candidate_from_dict(data: Dict[str, Any]) -> RoutingCandidate:
    """Create RoutingCandidate from dict."""
    return RoutingCandidate(
        candidate_id=data.get("candidate_id", ""),
        action=data.get("action", "advance"),
        target_node=data.get("target_node"),
        reason=data.get("reason", ""),
        priority=data.get("priority", 50),
        source=data.get("source", "graph_edge"),
        evidence_pointers=data.get("evidence_pointers", []),
        is_default=data.get("is_default", False),
    )


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

    if explanation.stall_context:
        sc = explanation.stall_context
        result["stall_context"] = {
            "is_stalled": sc.is_stalled,
            "stall_count": sc.stall_count,
            "velocity": sc.velocity,
            "last_signature": sc.last_signature,
            "recommendation": sc.recommendation,
            "triggered_sidequest": sc.triggered_sidequest,
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

    stall_context = None
    if "stall_context" in data:
        sc_data = data["stall_context"]
        stall_context = StallContext(
            is_stalled=sc_data.get("is_stalled", False),
            stall_count=sc_data.get("stall_count", 0),
            velocity=sc_data.get("velocity", 1.0),
            last_signature=sc_data.get("last_signature", ""),
            recommendation=sc_data.get("recommendation", "continue"),
            triggered_sidequest=sc_data.get("triggered_sidequest"),
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
        stall_context=stall_context,
    )


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
        "decision": signal.decision.value
        if isinstance(signal.decision, RoutingDecision)
        else signal.decision,
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

    if signal.skip_justification:
        result["skip_justification"] = dict(signal.skip_justification)

    return result


def routing_signal_from_dict(data: Dict[str, Any]) -> RoutingSignal:
    """Parse RoutingSignal from a dictionary.

    Args:
        data: Dictionary with RoutingSignal fields.

    Returns:
        Parsed RoutingSignal instance.

    Note:
        Provides backwards compatibility for signals missing the new
        next_flow, loop_count, exit_condition_met, explanation, or
        skip_justification fields.
    """
    decision_value = data.get("decision", "advance")
    decision = (
        RoutingDecision(decision_value) if isinstance(decision_value, str) else decision_value
    )

    explanation = None
    if "explanation" in data:
        explanation = routing_explanation_from_dict(data["explanation"])

    # Parse skip_justification if present (TypedDict, so cast from dict)
    skip_justification: Optional[SkipJustification] = None
    if "skip_justification" in data:
        sj = data["skip_justification"]
        skip_justification = SkipJustification(
            skip_reason=sj.get("skip_reason", ""),
            why_not_needed_for_exit=sj.get("why_not_needed_for_exit", ""),
            replacement_assurance=sj.get("replacement_assurance", ""),
        )

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
        skip_justification=skip_justification,
    )
