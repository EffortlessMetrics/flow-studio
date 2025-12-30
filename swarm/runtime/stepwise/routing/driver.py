"""
driver.py - Main routing driver for stepwise execution.

This module provides the route_step() function that determines the next step
after each step execution. It implements the priority-based routing strategy:

1. Fast-path (obvious deterministic cases)
2. Deterministic fallback (if routing_mode == DETERMINISTIC_ONLY)
3. Navigator (if available, for ASSIST/AUTHORITATIVE modes)
4. Envelope fallback (legacy RoutingSignal from step finalization)
5. Escalate (if nothing else works)

The driver is the single entry point for routing decisions in stepwise
orchestration. It coordinates between different routing strategies and
produces a RoutingOutcome with full audit trail.

Usage:
    outcome = route_step(
        step=step_def,
        step_result=result,
        run_state=state,
        loop_state=loops,
        iteration=iter_count,
        routing_mode=RoutingMode.ASSIST,
    )
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from swarm.runtime.types import (
    RoutingDecision,
    RoutingMode,
    RoutingSignal,
    RoutingCandidate,
)

if TYPE_CHECKING:
    from swarm.config.flow_registry import FlowDefinition, StepDefinition
    from swarm.runtime.router import FlowGraph
    from swarm.runtime.types import RunSpec, RunState

logger = logging.getLogger(__name__)


# =============================================================================
# Routing Outcome
# =============================================================================


@dataclass
class RoutingOutcome:
    """The result of a routing decision.

    Encapsulates the complete routing decision with all audit information
    needed for debugging and wisdom analysis.

    Attributes:
        decision: The routing decision type (ADVANCE, LOOP, TERMINATE, BRANCH, SKIP).
        next_step_id: ID of the next step to execute, or None if terminating.
        reason: Human-readable explanation of the routing decision.
        confidence: Confidence score for this decision (0.0 to 1.0).
        needs_human: Whether human intervention is required.
        routing_source: How this decision was made (fast_path, deterministic,
            navigator, envelope_fallback, escalate).
        chosen_candidate_id: ID of the candidate chosen (for audit trail).
        candidates: List of candidates that were evaluated.
        loop_iteration: Current loop iteration count (for microloops).
        exit_condition_met: Whether the exit condition was satisfied.
        timestamp: When this routing decision was made.
        signal: The underlying RoutingSignal (if available).
        raw_envelope_signal: Signal from envelope fallback (if used).
    """

    decision: RoutingDecision
    next_step_id: Optional[str] = None
    reason: str = ""
    confidence: float = 1.0
    needs_human: bool = False
    routing_source: str = "unknown"
    chosen_candidate_id: Optional[str] = None
    candidates: List[RoutingCandidate] = field(default_factory=list)
    loop_iteration: int = 0
    exit_condition_met: bool = False
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    signal: Optional[RoutingSignal] = None
    raw_envelope_signal: Optional[RoutingSignal] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "decision": self.decision.value if hasattr(self.decision, "value") else str(self.decision),
            "next_step_id": self.next_step_id,
            "reason": self.reason,
            "confidence": self.confidence,
            "needs_human": self.needs_human,
            "routing_source": self.routing_source,
            "chosen_candidate_id": self.chosen_candidate_id,
            "candidates": [
                {
                    "candidate_id": c.candidate_id,
                    "action": c.action,
                    "target_node": c.target_node,
                    "reason": c.reason,
                    "priority": c.priority,
                    "source": c.source,
                }
                for c in self.candidates
            ],
            "loop_iteration": self.loop_iteration,
            "exit_condition_met": self.exit_condition_met,
            "timestamp": self.timestamp.isoformat(),
        }

    def to_event_payload(self) -> Dict[str, Any]:
        """Convert to event payload for step_routed events.

        Returns a dictionary suitable for use as the payload in a step_routed
        RunEvent. This provides the canonical format for routing audit trail.
        """
        payload: Dict[str, Any] = {
            "next_step_id": self.next_step_id,
            "reason": self.reason,
            "routing_source": self.routing_source,
        }

        if self.chosen_candidate_id:
            payload["chosen_candidate_id"] = self.chosen_candidate_id

        if self.candidates:
            payload["candidate_count"] = len(self.candidates)
            payload["candidate_ids"] = [c.candidate_id for c in self.candidates]

        payload["decision"] = (
            self.decision.value if hasattr(self.decision, "value") else str(self.decision)
        )
        payload["confidence"] = self.confidence
        payload["loop_count"] = self.loop_iteration
        payload["exit_condition_met"] = self.exit_condition_met

        return payload

    @classmethod
    def from_signal(
        cls,
        signal: RoutingSignal,
        routing_source: str = "signal",
    ) -> "RoutingOutcome":
        """Create RoutingOutcome from a RoutingSignal.

        This is the preferred way to convert legacy RoutingSignal results
        into the new RoutingOutcome format.
        """
        return cls(
            decision=signal.decision,
            next_step_id=signal.next_step_id,
            reason=signal.reason,
            confidence=signal.confidence,
            needs_human=signal.needs_human,
            routing_source=routing_source,
            chosen_candidate_id=signal.chosen_candidate_id,
            candidates=signal.routing_candidates or [],
            loop_iteration=signal.loop_count,
            exit_condition_met=signal.exit_condition_met,
            signal=signal,
        )

    @classmethod
    def from_tuple(
        cls,
        next_step_id: Optional[str],
        reason: str,
        routing_source: str,
        signal: Optional[RoutingSignal] = None,
        candidates: Optional[List[Dict[str, Any]]] = None,
    ) -> "RoutingOutcome":
        """Create RoutingOutcome from orchestrator tuple format.

        Bridges the gap between the orchestrator's tuple returns and the
        new RoutingOutcome type. This allows gradual migration.
        """
        # Infer decision from next_step_id
        if next_step_id is None:
            decision = RoutingDecision.TERMINATE
        elif "loop" in reason.lower() or "retry" in reason.lower():
            decision = RoutingDecision.LOOP
        else:
            decision = RoutingDecision.ADVANCE

        # Extract fields from signal if available
        confidence = 1.0
        needs_human = False
        chosen_candidate_id = None
        loop_iteration = 0
        exit_condition_met = False
        routing_candidates: List[RoutingCandidate] = []

        if signal is not None:
            decision = signal.decision
            confidence = signal.confidence
            needs_human = signal.needs_human
            chosen_candidate_id = signal.chosen_candidate_id
            loop_iteration = signal.loop_count
            exit_condition_met = signal.exit_condition_met
            routing_candidates = signal.routing_candidates or []

        # Convert dict candidates to RoutingCandidate if provided
        if candidates and not routing_candidates:
            for c in candidates:
                routing_candidates.append(
                    RoutingCandidate(
                        candidate_id=c.get("candidate_id", ""),
                        action=c.get("action", "advance"),
                        target_node=c.get("target_node"),
                        reason=c.get("reason", ""),
                        priority=c.get("priority", 0),
                        source=c.get("source", "unknown"),
                        is_default=c.get("is_default", False),
                    )
                )

        return cls(
            decision=decision,
            next_step_id=next_step_id,
            reason=reason,
            confidence=confidence,
            needs_human=needs_human,
            routing_source=routing_source,
            chosen_candidate_id=chosen_candidate_id,
            candidates=routing_candidates,
            loop_iteration=loop_iteration,
            exit_condition_met=exit_condition_met,
            signal=signal,
        )


# =============================================================================
# Fast-Path Routing
# =============================================================================


def _try_fast_path(
    step: "StepDefinition",
    step_result: Any,
    loop_state: Dict[str, int],
    iteration: int,
) -> Optional[RoutingOutcome]:
    """Try fast-path routing for obvious deterministic cases.

    Fast-path handles cases that don't require LLM or complex evaluation:
    - Terminal steps (no outgoing edges)
    - Single outgoing edge with no conditions
    - VERIFIED status with explicit next step
    - Max iterations reached

    Args:
        step: The step that was executed.
        step_result: The result from step execution.
        loop_state: Dictionary tracking iteration counts per microloop.
        iteration: Current iteration count.

    Returns:
        RoutingOutcome if fast-path applies, None otherwise.
    """
    # TODO: Implement fast-path logic
    # For now, return None to fall through to other strategies
    logger.debug("Fast-path routing: checking for obvious cases")

    # Check if step has no routing config (terminal)
    routing = getattr(step, "routing", None)
    if routing is None:
        # Check if this is the last step in the flow
        flow_def = getattr(step, "flow_def", None)
        if flow_def:
            max_index = max(s.index for s in flow_def.steps) if flow_def.steps else 0
            if step.index >= max_index:
                logger.debug("Fast-path: terminal step (last in flow)")
                return RoutingOutcome(
                    decision=RoutingDecision.TERMINATE,
                    next_step_id=None,
                    reason="terminal_step_last_in_flow",
                    confidence=1.0,
                    routing_source="fast_path",
                    chosen_candidate_id="fast_path:terminate:last_step",
                    exit_condition_met=True,
                )

    # Check for explicit next_step_id in result
    if isinstance(step_result, dict):
        explicit_next = step_result.get("next_step_id")
        if explicit_next:
            logger.debug("Fast-path: explicit next_step_id in result")
            return RoutingOutcome(
                decision=RoutingDecision.ADVANCE,
                next_step_id=explicit_next,
                reason="explicit_next_step_id",
                confidence=1.0,
                routing_source="fast_path",
                chosen_candidate_id=f"fast_path:advance:{explicit_next}",
            )

    return None


# =============================================================================
# Deterministic Routing
# =============================================================================


def _try_deterministic(
    step: "StepDefinition",
    step_result: Any,
    run_state: "RunState",
    loop_state: Dict[str, int],
    iteration: int,
    flow_graph: Optional["FlowGraph"] = None,
    flow_def: Optional["FlowDefinition"] = None,
) -> Optional[RoutingOutcome]:
    """Try deterministic routing via CEL/condition evaluation.

    Deterministic routing handles:
    - Single outgoing edge (no choice needed)
    - Edge conditions that evaluate to single valid candidate
    - Microloop exit conditions (VERIFIED, max_iterations)

    Args:
        step: The step that was executed.
        step_result: The result from step execution.
        run_state: Current run state.
        loop_state: Dictionary tracking iteration counts.
        iteration: Current iteration count.
        flow_graph: Optional flow graph for edge evaluation.
        flow_def: Optional flow definition for step lookup.

    Returns:
        RoutingOutcome if deterministic routing resolves, None otherwise.
    """
    # TODO: Implement deterministic routing logic
    # This will use the existing _routing_legacy functions
    logger.debug("Deterministic routing: evaluating edges and conditions")

    # Import here to avoid circular imports
    from swarm.runtime.stepwise._routing_legacy import create_routing_signal

    # Try to create a routing signal using existing logic
    try:
        signal = create_routing_signal(
            step=step,
            result=step_result if isinstance(step_result, dict) else {},
            loop_state=loop_state,
            run_state=run_state,
        )

        if signal:
            return RoutingOutcome(
                decision=signal.decision,
                next_step_id=signal.next_step_id,
                reason=signal.reason,
                confidence=signal.confidence,
                needs_human=signal.needs_human,
                routing_source="deterministic",
                chosen_candidate_id=signal.chosen_candidate_id,
                candidates=signal.routing_candidates or [],
                exit_condition_met=signal.exit_condition_met,
                signal=signal,
            )
    except Exception as e:
        logger.warning("Deterministic routing failed: %s", e)

    return None


# =============================================================================
# Navigator Routing
# =============================================================================


def _try_navigator(
    step: "StepDefinition",
    step_result: Any,
    run_state: "RunState",
    loop_state: Dict[str, int],
    iteration: int,
    routing_mode: RoutingMode,
    run_id: Optional[str] = None,
    flow_key: Optional[str] = None,
    flow_graph: Optional["FlowGraph"] = None,
    flow_def: Optional["FlowDefinition"] = None,
    spec: Optional["RunSpec"] = None,
    run_base: Optional[Path] = None,
    navigation_orchestrator: Optional[Any] = None,
) -> Optional[RoutingOutcome]:
    """Try Navigator-based routing for intelligent decisions.

    Navigator routing is used when:
    - Multiple valid edges exist (tie-breaking)
    - Complex conditions require LLM analysis
    - AUTHORITATIVE mode allows proposing detours/injections

    Args:
        step: The step that was executed.
        step_result: The result from step execution.
        run_state: Current run state.
        loop_state: Dictionary tracking iteration counts.
        iteration: Current iteration count.
        routing_mode: Current routing mode (ASSIST or AUTHORITATIVE).
        run_id: The run identifier.
        flow_key: The flow being executed.
        flow_graph: The flow graph for edge constraints.
        flow_def: The flow definition.
        spec: The run specification.
        run_base: Base path for run artifacts.
        navigation_orchestrator: The Navigator orchestrator instance.

    Returns:
        RoutingOutcome if Navigator provides a decision, None otherwise.
    """
    # Navigator is only used in ASSIST or AUTHORITATIVE modes
    if routing_mode == RoutingMode.DETERMINISTIC_ONLY:
        logger.debug("Navigator routing skipped: DETERMINISTIC_ONLY mode")
        return None

    if navigation_orchestrator is None:
        logger.debug("Navigator routing skipped: no orchestrator available")
        return None

    # TODO: Implement Navigator-based routing
    # This will call the navigation_orchestrator to get a routing decision
    logger.debug("Navigator routing: requesting intelligent routing decision")

    return None


# =============================================================================
# Envelope Fallback
# =============================================================================


def _try_envelope_fallback(
    step: "StepDefinition",
    step_result: Any,
) -> Optional[RoutingOutcome]:
    """Try envelope fallback using RoutingSignal from step finalization.

    This is the legacy path that uses the RoutingSignal emitted by
    step finalization. It's used when newer routing strategies don't apply.

    Args:
        step: The step that was executed.
        step_result: The result from step execution (may contain envelope).

    Returns:
        RoutingOutcome from envelope signal, None otherwise.
    """
    logger.debug("Envelope fallback: checking for RoutingSignal in result")

    # Check if step_result has an envelope with routing_signal
    if isinstance(step_result, dict):
        envelope = step_result.get("envelope")
        if envelope and hasattr(envelope, "routing_signal"):
            signal = envelope.routing_signal
            if signal:
                logger.debug("Envelope fallback: using signal from envelope")
                return RoutingOutcome(
                    decision=signal.decision,
                    next_step_id=signal.next_step_id,
                    reason=signal.reason,
                    confidence=signal.confidence,
                    needs_human=signal.needs_human,
                    routing_source="envelope_fallback",
                    chosen_candidate_id=signal.chosen_candidate_id,
                    candidates=signal.routing_candidates or [],
                    exit_condition_met=signal.exit_condition_met,
                    signal=signal,
                    raw_envelope_signal=signal,
                )

    return None


# =============================================================================
# Escalate (Last Resort)
# =============================================================================


def _escalate(
    step: "StepDefinition",
    step_result: Any,
    reason: str,
) -> RoutingOutcome:
    """Escalate when no routing strategy can determine next step.

    This is the last resort when all routing strategies fail.
    It terminates the flow and flags for human intervention.

    Args:
        step: The step that was executed.
        step_result: The result from step execution.
        reason: Why escalation is needed.

    Returns:
        RoutingOutcome with TERMINATE and needs_human=True.
    """
    logger.warning("Routing escalation: %s (step: %s)", reason, step.id)

    return RoutingOutcome(
        decision=RoutingDecision.TERMINATE,
        next_step_id=None,
        reason=f"escalate:{reason}",
        confidence=0.0,
        needs_human=True,
        routing_source="escalate",
        chosen_candidate_id="escalate:no_route",
        exit_condition_met=False,
    )


# =============================================================================
# Main Driver Function
# =============================================================================


def route_step(
    *,
    step: "StepDefinition",
    step_result: Any,
    run_state: "RunState",
    loop_state: Dict[str, int],
    iteration: int,
    routing_mode: "RoutingMode",
    # Optional for navigator path
    run_id: Optional[str] = None,
    flow_key: Optional[str] = None,
    flow_graph: Optional["FlowGraph"] = None,
    flow_def: Optional["FlowDefinition"] = None,
    spec: Optional["RunSpec"] = None,
    run_base: Optional[Path] = None,
    navigation_orchestrator: Optional[Any] = None,
) -> "RoutingOutcome":
    """Route to next step using appropriate strategy.

    This is the main entry point for routing decisions in stepwise orchestration.
    It implements the priority-based routing strategy:

    1. Fast-path (obvious deterministic cases)
    2. Deterministic fallback (if routing_mode == DETERMINISTIC_ONLY)
    3. Navigator (if available, for ASSIST/AUTHORITATIVE modes)
    4. Envelope fallback (legacy path)
    5. Escalate (if nothing else works)

    Args:
        step: The step that was executed.
        step_result: The result from step execution.
        run_state: Current run state (for resume, detours).
        loop_state: Dictionary tracking iteration counts per microloop.
        iteration: Current iteration count.
        routing_mode: Controls Navigator behavior (DETERMINISTIC_ONLY, ASSIST, AUTHORITATIVE).
        run_id: Optional run identifier (for navigator context).
        flow_key: Optional flow key (for navigator context).
        flow_graph: Optional flow graph (for edge constraints).
        flow_def: Optional flow definition (for step lookup).
        spec: Optional run specification.
        run_base: Optional base path for run artifacts.
        navigation_orchestrator: Optional Navigator orchestrator instance.

    Returns:
        RoutingOutcome with the routing decision and full audit trail.

    Strategy Priority:
        1. Fast-path: Handles obvious cases without LLM (terminal, single edge, explicit next)
        2. Deterministic: Uses CEL/condition evaluation (required in DETERMINISTIC_ONLY mode)
        3. Navigator: Uses LLM-based routing (for tie-breaking, complex decisions)
        4. Envelope fallback: Uses legacy RoutingSignal from step finalization
        5. Escalate: Terminates with needs_human=True when no route found
    """
    logger.debug(
        "route_step called: step=%s, mode=%s, iteration=%d",
        step.id,
        routing_mode.value if hasattr(routing_mode, "value") else routing_mode,
        iteration,
    )

    # 1. Fast-path: Obvious deterministic cases
    outcome = _try_fast_path(step, step_result, loop_state, iteration)
    if outcome:
        logger.debug("Routing via fast-path: %s", outcome.reason)
        return outcome

    # 2. Deterministic fallback (required in DETERMINISTIC_ONLY mode)
    if routing_mode == RoutingMode.DETERMINISTIC_ONLY:
        outcome = _try_deterministic(
            step, step_result, run_state, loop_state, iteration,
            flow_graph=flow_graph, flow_def=flow_def,
        )
        if outcome:
            logger.debug("Routing via deterministic: %s", outcome.reason)
            return outcome
        # In DETERMINISTIC_ONLY mode, we must not use Navigator
        # Fall through to envelope fallback

    # 3. Navigator (for ASSIST/AUTHORITATIVE modes)
    if routing_mode in (RoutingMode.ASSIST, RoutingMode.AUTHORITATIVE):
        outcome = _try_navigator(
            step, step_result, run_state, loop_state, iteration,
            routing_mode=routing_mode,
            run_id=run_id,
            flow_key=flow_key,
            flow_graph=flow_graph,
            flow_def=flow_def,
            spec=spec,
            run_base=run_base,
            navigation_orchestrator=navigation_orchestrator,
        )
        if outcome:
            logger.debug("Routing via navigator: %s", outcome.reason)
            return outcome

    # 4. Envelope fallback (legacy path)
    outcome = _try_envelope_fallback(step, step_result)
    if outcome:
        logger.debug("Routing via envelope fallback: %s", outcome.reason)
        return outcome

    # 5. Try deterministic as final attempt before escalation
    # (for ASSIST/AUTHORITATIVE modes that didn't find Navigator route)
    if routing_mode != RoutingMode.DETERMINISTIC_ONLY:
        outcome = _try_deterministic(
            step, step_result, run_state, loop_state, iteration,
            flow_graph=flow_graph, flow_def=flow_def,
        )
        if outcome:
            logger.debug("Routing via deterministic (final attempt): %s", outcome.reason)
            return outcome

    # 6. Escalate: No routing strategy could determine next step
    return _escalate(
        step, step_result,
        reason="no_routing_strategy_matched",
    )
