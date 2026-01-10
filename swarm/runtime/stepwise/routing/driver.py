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

from swarm.runtime.sidequest_catalog import SidequestCatalog, load_default_catalog
from swarm.runtime.types import (
    RoutingDecision,
    RoutingMode,
    RoutingSignal,
    RoutingCandidate,
)

# Import from dedicated utility_candidates module to avoid circular imports
# This module is the single source of truth for utility flow candidate generation
from .utility_candidates import (
    INJECT_PREFIX,
    get_utility_flow_detector,
    set_utility_flow_registry,
    clear_utility_flow_caches,
    get_utility_flow_candidates as _get_utility_flow_candidates,
)

if TYPE_CHECKING:
    from swarm.config.flow_registry import FlowDefinition, StepDefinition
    from swarm.runtime.router import FlowGraph
    from swarm.runtime.types import RunSpec, RunState

logger = logging.getLogger(__name__)


# =============================================================================
# Module-level sidequest catalog (lazy-loaded singleton)
# =============================================================================

_sidequest_catalog: Optional[SidequestCatalog] = None


def get_sidequest_catalog() -> SidequestCatalog:
    """Get the module-level sidequest catalog (lazy-loaded).

    Returns:
        The default SidequestCatalog instance.
    """
    global _sidequest_catalog
    if _sidequest_catalog is None:
        _sidequest_catalog = load_default_catalog()
    return _sidequest_catalog


def set_sidequest_catalog(catalog: SidequestCatalog) -> None:
    """Set a custom sidequest catalog (for testing or custom configuration).

    Args:
        catalog: The SidequestCatalog to use.
    """
    global _sidequest_catalog
    _sidequest_catalog = catalog




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
        """Convert to event payload for route_decision events.

        Returns a dictionary suitable for use as the payload in a route_decision
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
# Helper: Convert StepResult to dict
# =============================================================================


def _step_result_to_dict(step_result: Any) -> Dict[str, Any]:
    """Convert a step result to a dictionary for routing logic.

    The step_result can be:
    - A dict: returned as-is
    - A StepResult dataclass: converted to dict with status, output, etc.
    - An object with to_dict(): uses that method
    - Any other object: extracts common attributes

    This ensures routing logic always receives the status, output, and
    other fields needed for routing decisions (e.g., microloop exit conditions).

    Args:
        step_result: The result from step execution (any type).

    Returns:
        A dictionary with at minimum 'status' key if available.
    """
    if isinstance(step_result, dict):
        return step_result

    # Try to_dict() method first (common pattern for dataclasses with custom serialization)
    if hasattr(step_result, "to_dict") and callable(step_result.to_dict):
        return step_result.to_dict()

    # Extract common attributes from StepResult or similar objects
    result: Dict[str, Any] = {}
    for attr in (
        "status",
        "output",
        "error",
        "duration_ms",
        "step_id",
        "artifacts",
        "can_further_iteration_help",
    ):
        if hasattr(step_result, attr):
            result[attr] = getattr(step_result, attr)
    return result


# =============================================================================
# Sidequest Integration
# =============================================================================


def _build_sidequest_context(
    step_result: Any,
    loop_state: Dict[str, int],
    step_id: str,
) -> Dict[str, Any]:
    """Build context dictionary for sidequest trigger evaluation.

    Extracts relevant signals from step result for sidequest trigger matching:
    - verification_passed: Whether the step passed verification
    - failure_type: Type of failure if applicable (e.g., "environment", "test")
    - changed_paths: List of file paths changed during the step
    - stall_signals: Stall detection signals from progress tracking
    - iteration: Current loop iteration count

    Args:
        step_result: The result from step execution (any type).
        loop_state: Dictionary tracking iteration counts per microloop.
        step_id: The current step ID.

    Returns:
        Context dictionary for sidequest trigger evaluation.
    """
    result_dict = _step_result_to_dict(step_result)

    # Extract verification status
    status = result_dict.get("status", "")
    verification_passed = status.upper() == "VERIFIED"

    # Extract failure type if present
    failure_type = result_dict.get("failure_type")
    if failure_type is None:
        # Try to infer from error category
        error_category = result_dict.get("error_category", "")
        if "import" in error_category.lower() or "module" in error_category.lower():
            failure_type = "environment"
        elif "test" in error_category.lower():
            failure_type = "test"

    # Extract changed paths from file_changes or changed_files
    changed_paths: List[str] = []
    if hasattr(step_result, "changed_files"):
        changed_paths = step_result.changed_files or []
    elif hasattr(step_result, "file_changes"):
        file_changes = step_result.file_changes
        if isinstance(file_changes, dict):
            files = file_changes.get("files", [])
            if isinstance(files, list):
                changed_paths = [f.get("path", f) if isinstance(f, dict) else str(f) for f in files]
    elif "changed_files" in result_dict:
        changed_paths = result_dict.get("changed_files", [])

    # Build stall signals from loop state
    # Count iterations for this step across all loop targets
    stall_count = 0
    for key, count in loop_state.items():
        if key.startswith(f"{step_id}:"):
            stall_count = max(stall_count, count)

    # Check for same failure signature (would need progress history for full check)
    same_failure_signature = False
    if hasattr(step_result, "error_signature"):
        # If we have an error signature, this could be used for stall detection
        # For now, just note that we have one
        pass

    stall_signals = {
        "stall_count": stall_count,
        "same_failure_signature": same_failure_signature,
        "is_stalled": stall_count >= 3,  # Simple threshold
    }

    # Get iteration count from loop state
    iteration = stall_count

    # Check for ambiguity signals
    has_ambiguity = result_dict.get("has_ambiguity", False)
    context_insufficient = result_dict.get("context_insufficient", False)

    return {
        "verification_passed": verification_passed,
        "failure_type": failure_type,
        "changed_paths": changed_paths,
        "stall_signals": stall_signals,
        "iteration": iteration,
        "has_ambiguity": has_ambiguity,
        "context_insufficient": context_insufficient,
        "status": status,
        "error_category": result_dict.get("error_category", ""),
    }


def _get_sidequest_candidates(
    step_result: Any,
    loop_state: Dict[str, int],
    step_id: str,
    run_id: Optional[str] = None,
) -> List[RoutingCandidate]:
    """Get applicable sidequests as routing candidates.

    Evaluates sidequest triggers against the current context and returns
    matching sidequests as RoutingCandidate objects with action="detour".

    Args:
        step_result: The result from step execution.
        loop_state: Dictionary tracking iteration counts per microloop.
        step_id: The current step ID.
        run_id: Optional run ID for usage tracking.

    Returns:
        List of RoutingCandidate objects for applicable sidequests.
    """
    catalog = get_sidequest_catalog()

    # Build context for sidequest evaluation
    context = _build_sidequest_context(step_result, loop_state, step_id)

    # Get applicable sidequests from catalog
    applicable = catalog.get_applicable_sidequests(context, run_id=run_id)

    # Convert to routing candidates
    candidates: List[RoutingCandidate] = []
    for sq in applicable:
        station_id = sq.get_station_id()
        candidates.append(
            RoutingCandidate(
                candidate_id=f"detour:{sq.sidequest_id}",
                action="detour",
                target_node=station_id,
                reason=sq.description,
                priority=sq.priority,
                source="detour_catalog",
                evidence_pointers=[
                    f"trigger_mode:{sq.trigger_mode}",
                    f"cost_hint:{sq.cost_hint}",
                ] + [f"tag:{tag}" for tag in sq.tags[:3]],  # Include up to 3 tags
                is_default=False,
            )
        )

    if candidates:
        logger.debug(
            "Sidequest catalog: found %d applicable sidequests for step %s: %s",
            len(candidates),
            step_id,
            [c.candidate_id for c in candidates],
        )

    return candidates


def record_sidequest_selection(
    sidequest_id: str,
    run_id: Optional[str] = None,
) -> None:
    """Record that a sidequest was selected for usage tracking.

    Call this when a sidequest candidate is chosen by the routing decision
    to track usage and enforce max_uses_per_run limits.

    Args:
        sidequest_id: The ID of the selected sidequest.
        run_id: Optional run ID for per-run tracking.
    """
    catalog = get_sidequest_catalog()
    catalog.record_usage(sidequest_id, run_id=run_id)
    logger.debug(
        "Recorded sidequest selection: %s (run_id=%s)",
        sidequest_id,
        run_id,
    )


# =============================================================================
# Utility Flow Injection (INJECT_FLOW candidates)
# =============================================================================
# Functions are imported from utility_candidates.py to avoid circular imports:
# - INJECT_PREFIX (constant for inject_flow candidate ID prefix)
# - _get_utility_flow_candidates (aliased from get_utility_flow_candidates)
# - get_utility_flow_registry
# - get_utility_flow_detector
# - set_utility_flow_registry
# - clear_utility_flow_caches


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
    logger.debug("Deterministic routing: evaluating edges and conditions")

    # Import here to avoid circular imports
    from swarm.runtime.stepwise._routing_legacy import create_routing_signal

    # Convert step_result to dict to ensure routing logic sees status, output, etc.
    result_dict = _step_result_to_dict(step_result)

    # Try to create a routing signal using existing logic
    try:
        signal = create_routing_signal(
            step=step,
            result=result_dict,
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
    # Utility flow detection
    git_status: Optional[Dict[str, Any]] = None,
    repo_root: Optional[Path] = None,
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
        git_status: Git status for utility flow detection (behind_count, diverged).
        repo_root: Repository root path for utility flow registry.

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

    # Validate required parameters for Navigator routing
    if run_id is None:
        logger.debug("Navigator routing skipped: run_id required")
        return None
    if flow_key is None:
        logger.debug("Navigator routing skipped: flow_key required")
        return None
    if flow_graph is None:
        logger.debug("Navigator routing skipped: flow_graph required")
        return None
    if flow_def is None:
        logger.debug("Navigator routing skipped: flow_def required")
        return None
    if spec is None:
        logger.debug("Navigator routing skipped: spec required")
        return None
    if run_base is None:
        logger.debug("Navigator routing skipped: run_base required")
        return None

    logger.debug("Navigator routing: requesting intelligent routing decision")

    # Import here to avoid circular imports
    from .navigator import route_via_navigator

    try:
        return route_via_navigator(
            step=step,
            step_result=step_result,
            run_state=run_state,
            loop_state=loop_state,
            iteration=iteration,
            routing_mode=routing_mode,
            navigation_orchestrator=navigation_orchestrator,
            run_id=run_id,
            flow_key=flow_key,
            flow_graph=flow_graph,
            flow_def=flow_def,
            spec=spec,
            run_base=run_base,
            git_status=git_status,
            repo_root=repo_root,
        )
    except Exception as e:
        # Log with explicit exception type and context for debugging
        logger.warning(
            "Navigator routing failed: type=%s step=%s run_id=%s flow=%s error=%s",
            type(e).__name__,
            step.id,
            run_id,
            flow_key,
            str(e),
        )
        # Return None to allow fallback to deterministic routing.
        # The audit trail will show routing_source != "navigator*" which
        # indicates Navigator was attempted but failed.
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
# Loop State Management
# =============================================================================


def _update_loop_state_if_looping(
    outcome: RoutingOutcome,
    step: "StepDefinition",
    loop_state: Dict[str, int],
) -> None:
    """Update loop_state in-place when routing decision is LOOP.

    This ensures microloop iteration counters are properly incremented.
    Without this, the driver would return LOOP decisions but the counter
    wouldn't increment, risking infinite loops.

    The loop_key format is "{step_id}:{loop_target}" to match legacy behavior.

    Args:
        outcome: The routing outcome to check.
        step: The step that was executed.
        loop_state: Dictionary tracking iteration counts (mutated in-place).
    """
    if outcome.decision != RoutingDecision.LOOP:
        return

    # Determine loop_target from step routing config
    routing = getattr(step, "routing", None)
    if routing is None:
        return

    loop_target = getattr(routing, "loop_target", None)
    if loop_target is None:
        # Fallback: use next_step_id from outcome as loop target
        loop_target = outcome.next_step_id
    if loop_target is None:
        return

    # Compute loop key (matches legacy format)
    loop_key = f"{step.id}:{loop_target}"

    # Increment iteration count
    current_iter = loop_state.get(loop_key, 0)
    loop_state[loop_key] = current_iter + 1

    # Update outcome with current loop iteration
    outcome.loop_iteration = current_iter + 1

    logger.debug(
        "Loop state updated: %s -> %d",
        loop_key,
        loop_state[loop_key],
    )


# =============================================================================
# Sidequest Injection Helpers
# =============================================================================


def _enrich_outcome_with_sidequests(
    outcome: RoutingOutcome,
    step: "StepDefinition",
    step_result: Any,
    loop_state: Dict[str, int],
    run_id: Optional[str] = None,
) -> RoutingOutcome:
    """Enrich routing outcome with applicable sidequest candidates.

    This adds sidequest candidates to the outcome's candidate list without
    changing the routing decision. The sidequests are available as options
    for the Navigator or for audit trail purposes.

    Args:
        outcome: The routing outcome to enrich.
        step: The step that was executed.
        step_result: The result from step execution.
        loop_state: Dictionary tracking iteration counts per microloop.
        run_id: Optional run ID for usage tracking.

    Returns:
        The enriched RoutingOutcome (same object, mutated).
    """
    # Get applicable sidequest candidates
    sidequest_candidates = _get_sidequest_candidates(
        step_result=step_result,
        loop_state=loop_state,
        step_id=step.id,
        run_id=run_id,
    )

    if sidequest_candidates:
        # Add sidequest candidates to outcome
        existing_ids = {c.candidate_id for c in outcome.candidates}
        for sq_candidate in sidequest_candidates:
            if sq_candidate.candidate_id not in existing_ids:
                outcome.candidates.append(sq_candidate)

        logger.debug(
            "Enriched routing outcome with %d sidequest candidates for step %s",
            len(sidequest_candidates),
            step.id,
        )

    return outcome


def _track_sidequest_if_selected(
    outcome: RoutingOutcome,
    run_id: Optional[str] = None,
) -> None:
    """Track sidequest usage if a sidequest was selected.

    Checks if the chosen candidate is a sidequest (detour:*) and records
    usage to enforce max_uses_per_run limits.

    Args:
        outcome: The routing outcome to check.
        run_id: Optional run ID for per-run tracking.
    """
    chosen_id = outcome.chosen_candidate_id
    if chosen_id and chosen_id.startswith("detour:"):
        # Extract sidequest ID from candidate ID (format: "detour:<sidequest_id>")
        sidequest_id = chosen_id[7:]  # Remove "detour:" prefix
        record_sidequest_selection(sidequest_id, run_id=run_id)


# =============================================================================
# Utility Flow Injection Helpers
# =============================================================================


def _enrich_outcome_with_utility_flows(
    outcome: RoutingOutcome,
    step: "StepDefinition",
    step_result: Any,
    run_state: "RunState",
    git_status: Optional[Dict[str, Any]] = None,
    repo_root: Optional[Path] = None,
) -> RoutingOutcome:
    """Enrich routing outcome with applicable utility flow candidates.

    This adds utility flow (INJECT_FLOW) candidates to the outcome's candidate
    list without changing the routing decision. These are available as options
    for the Navigator when conditions like upstream divergence are detected.

    Args:
        outcome: The routing outcome to enrich.
        step: The step that was executed.
        step_result: The result from step execution.
        run_state: Current run state.
        git_status: Optional git status information.
        repo_root: Repository root path.

    Returns:
        The enriched RoutingOutcome (same object, mutated).
    """
    # Get applicable utility flow candidates
    utility_flow_candidates = _get_utility_flow_candidates(
        step_result=step_result,
        run_state=run_state,
        git_status=git_status,
        repo_root=repo_root,
    )

    if utility_flow_candidates:
        # Add utility flow candidates to outcome
        existing_ids = {c.candidate_id for c in outcome.candidates}
        for uf_candidate in utility_flow_candidates:
            if uf_candidate.candidate_id not in existing_ids:
                outcome.candidates.append(uf_candidate)

        logger.debug(
            "Enriched routing outcome with %d utility flow candidates for step %s",
            len(utility_flow_candidates),
            step.id,
        )

    return outcome


def _track_utility_flow_if_selected(
    outcome: RoutingOutcome,
    run_id: Optional[str] = None,
) -> None:
    """Track utility flow selection if one was selected.

    Checks if the chosen candidate is a utility flow (inject_flow:*) and
    logs the selection. Audit trail is handled by the routing journal
    (routing outcome already includes the chosen_candidate_id and candidates).

    Args:
        outcome: The routing outcome to check.
        run_id: Optional run ID for tracking.
    """
    chosen_id = outcome.chosen_candidate_id
    if chosen_id and chosen_id.startswith(INJECT_PREFIX):
        # Extract flow ID from candidate ID (format: "inject_flow:<flow_id>")
        flow_id = chosen_id[len(INJECT_PREFIX):]
        logger.info(
            "Utility flow injection selected: %s (run_id=%s)",
            flow_id,
            run_id,
        )


def _finalize_outcome(
    outcome: RoutingOutcome,
    step: "StepDefinition",
    step_result: Any,
    run_state: "RunState",
    loop_state: Dict[str, int],
    run_id: Optional[str] = None,
    git_status: Optional[Dict[str, Any]] = None,
    repo_root: Optional[Path] = None,
) -> RoutingOutcome:
    """Finalize routing outcome with enrichments and tracking.

    This is a convenience function that applies all outcome enrichments
    (sidequests, utility flows) and tracking in one place.

    Args:
        outcome: The routing outcome to finalize.
        step: The step that was executed.
        step_result: The result from step execution.
        run_state: Current run state.
        loop_state: Dictionary tracking iteration counts per microloop.
        run_id: Optional run ID for tracking.
        git_status: Optional git status for utility flow detection.
        repo_root: Optional repository root path.

    Returns:
        The finalized RoutingOutcome.
    """
    # Enrich with sidequest candidates
    _enrich_outcome_with_sidequests(outcome, step, step_result, loop_state, run_id)

    # Enrich with utility flow candidates
    _enrich_outcome_with_utility_flows(
        outcome, step, step_result, run_state, git_status, repo_root
    )

    # Update loop state if looping
    _update_loop_state_if_looping(outcome, step, loop_state)

    # Track selections for audit trail
    _track_sidequest_if_selected(outcome, run_id)
    _track_utility_flow_if_selected(outcome, run_id)

    return outcome


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
    # Optional for utility flow detection
    git_status: Optional[Dict[str, Any]] = None,
    repo_root: Optional[Path] = None,
) -> "RoutingOutcome":
    """Route to next step using appropriate strategy.

    This is the main entry point for routing decisions in stepwise orchestration.
    It implements the priority-based routing strategy:

    1. Fast-path (obvious deterministic cases)
    2. Deterministic fallback (if routing_mode == DETERMINISTIC_ONLY)
    3. Navigator (if available, for ASSIST/AUTHORITATIVE modes)
    4. Envelope fallback (legacy path)
    5. Escalate (if nothing else works)

    Sidequest Integration:
    Applicable sidequests are automatically added to the routing candidate set
    based on step result context (verification status, failure type, changed paths,
    stall signals). When a sidequest is selected, usage is tracked to enforce
    max_uses_per_run limits.

    Utility Flow Integration:
    Applicable utility flows (e.g., reset when diverged) are automatically added
    to the routing candidate set based on git status and step results. When a
    utility flow is selected, the flow is injected via the stack-frame pattern.

    Args:
        step: The step that was executed.
        step_result: The result from step execution.
        run_state: Current run state (for resume, detours).
        loop_state: Dictionary tracking iteration counts per microloop.
        iteration: Current iteration count.
        routing_mode: Controls Navigator behavior (DETERMINISTIC_ONLY, ASSIST, AUTHORITATIVE).
        run_id: Optional run identifier (for navigator context and sidequest tracking).
        flow_key: Optional flow key (for navigator context).
        flow_graph: Optional flow graph (for edge constraints).
        flow_def: Optional flow definition (for step lookup).
        spec: Optional run specification.
        run_base: Optional base path for run artifacts.
        navigation_orchestrator: Optional Navigator orchestrator instance.
        git_status: Optional git status for utility flow detection (behind_count, diverged).
        repo_root: Optional repository root path for utility flow registry.

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

    # Common finalization args for all paths
    finalize_args = {
        "step": step,
        "step_result": step_result,
        "run_state": run_state,
        "loop_state": loop_state,
        "run_id": run_id,
        "git_status": git_status,
        "repo_root": repo_root,
    }

    # 1. Fast-path: Obvious deterministic cases
    outcome = _try_fast_path(step, step_result, loop_state, iteration)
    if outcome:
        logger.debug("Routing via fast-path: %s", outcome.reason)
        return _finalize_outcome(outcome, **finalize_args)

    # 2. Deterministic fallback (required in DETERMINISTIC_ONLY mode)
    if routing_mode == RoutingMode.DETERMINISTIC_ONLY:
        outcome = _try_deterministic(
            step, step_result, run_state, loop_state, iteration,
            flow_graph=flow_graph, flow_def=flow_def,
        )
        if outcome:
            logger.debug("Routing via deterministic: %s", outcome.reason)
            return _finalize_outcome(outcome, **finalize_args)
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
            git_status=git_status,
            repo_root=repo_root,
        )
        if outcome:
            logger.debug("Routing via navigator: %s", outcome.reason)
            # Navigator path may already include sidequests via navigator.py
            # But we still enrich to ensure consistency and add utility flows
            return _finalize_outcome(outcome, **finalize_args)

    # 4. Envelope fallback (legacy path)
    outcome = _try_envelope_fallback(step, step_result)
    if outcome:
        logger.debug("Routing via envelope fallback: %s", outcome.reason)
        return _finalize_outcome(outcome, **finalize_args)

    # 5. Try deterministic as final attempt before escalation
    # (for ASSIST/AUTHORITATIVE modes that didn't find Navigator route)
    if routing_mode != RoutingMode.DETERMINISTIC_ONLY:
        outcome = _try_deterministic(
            step, step_result, run_state, loop_state, iteration,
            flow_graph=flow_graph, flow_def=flow_def,
        )
        if outcome:
            logger.debug("Routing via deterministic (final attempt): %s", outcome.reason)
            return _finalize_outcome(outcome, **finalize_args)

    # 6. Escalate: No routing strategy could determine next step
    outcome = _escalate(
        step, step_result,
        reason="no_routing_strategy_matched",
    )
    return _finalize_outcome(outcome, **finalize_args)
