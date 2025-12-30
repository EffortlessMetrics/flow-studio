"""
routing.py - Fallback routing logic for stepwise execution.

This module provides the routing decision logic that determines the next step
after each step execution. It supports:

1. Spec-first routing: Uses FlowSpec from swarm/spec/flows/
2. Config-based routing: Falls back to YAML config from flow_registry
3. HandoffEnvelope routing: Uses RoutingSignal from step finalization
4. Elephant Protocol: Stall detection based on progress derivatives

Routing Kinds:
- linear: Simple sequential flow to next step
- microloop: Loops back until condition is met or max iterations reached
- branch: Routes based on step result status
- terminal: Ends the flow

Stall Detection (Elephant Protocol):
We don't use budget caps. We use stall detection. If the derivative of progress
is positive (error changes, diff grows), we keep spending tokens. We only stop
on stalls (identical errors, no diff change).

The routing module is stateless - loop state and receipt reading are passed in.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Tuple

from swarm.config.flow_registry import FlowDefinition, StepDefinition
from swarm.runtime.types import (
    HandoffEnvelope,
    RoutingCandidate,
    RoutingDecision,
    RoutingSignal,
    RunState,
)

if TYPE_CHECKING:
    from swarm.runtime.engines.models import RoutingContext

logger = logging.getLogger(__name__)


# =============================================================================
# Elephant Protocol: Progress Tracking and Stall Detection Types
# =============================================================================


@dataclass
class ProgressDelta:
    """Captures measurable progress between iterations.

    Attributes:
        lines_added: Total lines of code added.
        lines_removed: Total lines of code removed.
        files_changed: Number of files modified.
        tests_added: Number of new tests (if detectable).
        tests_fixed: Number of tests that went from failing to passing.
        error_signature: Hash of the error output for comparison.
        status: The step status (VERIFIED, UNVERIFIED, BLOCKED).
    """

    lines_added: int = 0
    lines_removed: int = 0
    files_changed: int = 0
    tests_added: int = 0
    tests_fixed: int = 0
    error_signature: str = ""
    status: str = ""

    @property
    def has_meaningful_change(self) -> bool:
        """Check if there was any meaningful progress.

        Returns True if:
        - Code was changed (lines added/removed, files modified)
        - Tests were added or fixed
        - The error signature changed (different error)
        """
        return (
            self.lines_added > 0
            or self.lines_removed > 0
            or self.files_changed > 0
            or self.tests_added > 0
            or self.tests_fixed > 0
        )

    @property
    def net_lines(self) -> int:
        """Net change in lines of code."""
        return self.lines_added - self.lines_removed


@dataclass
class ProgressEvidence:
    """Evidence of progress (or lack thereof) for a single iteration.

    Attributes:
        evidence_id: Unique identifier for this evidence record.
        step_id: The step that produced this evidence.
        iteration: Which iteration of the microloop this represents.
        delta: The measurable changes in this iteration.
        timestamp: When this evidence was captured.
        test_output_hash: Hash of test output for comparison.
        previous_error_hash: Hash of previous iteration's errors.
        current_error_hash: Hash of current iteration's errors.
    """

    evidence_id: str
    step_id: str
    iteration: int
    delta: ProgressDelta
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    test_output_hash: str = ""
    previous_error_hash: str = ""
    current_error_hash: str = ""

    def errors_changed(self) -> bool:
        """Check if the error signature changed from previous iteration."""
        if not self.previous_error_hash:
            return True  # First iteration, treat as changed
        return self.previous_error_hash != self.current_error_hash


@dataclass
class StallAnalysis:
    """Analysis of stall condition for routing decisions.

    Attributes:
        is_stalled: Whether the run has stalled.
        stall_type: Category of stall detected.
        stall_count: Number of consecutive stalled iterations.
        reason: Human-readable explanation of the stall.
        recommendation: Suggested action (escalate_to_human, try_detour, terminate).
        evidence_ids: IDs of the evidence records that contributed to detection.
        confidence: Confidence level of the stall detection (0.0 to 1.0).
    """

    is_stalled: bool = False
    stall_type: str = ""
    stall_count: int = 0
    reason: str = ""
    recommendation: str = ""
    evidence_ids: List[str] = field(default_factory=list)
    confidence: float = 0.0


# =============================================================================
# Elephant Protocol: Stall Detection Functions
# =============================================================================


def compute_error_signature(error_output: str) -> str:
    """Compute a stable hash of error output for comparison.

    Normalizes the error output by:
    - Stripping leading/trailing whitespace
    - Removing line numbers (which may change)
    - Lowercasing for consistency

    Args:
        error_output: The raw error output string.

    Returns:
        A hex digest representing the error signature.
    """
    if not error_output:
        return ""

    # Normalize: strip, lowercase, remove common variable parts
    normalized = error_output.strip().lower()

    # Remove line numbers (patterns like ":123:" or "line 123")
    import re

    normalized = re.sub(r":\d+:", ":<LINE>:", normalized)
    normalized = re.sub(r"line \d+", "line <LINE>", normalized)

    # Hash the normalized output
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]


def detect_stall(
    current_step_id: str,
    progress_history: List[ProgressEvidence],
    max_stall_iterations: int = 3,
) -> Tuple[bool, Optional[StallAnalysis]]:
    """Detect if the run has stalled based on progress evidence.

    The Elephant Protocol: We don't use budget caps. We use stall detection.
    If the derivative of progress is positive (error changes, diff grows),
    we keep spending tokens. We only stop on stalls (identical errors, no diff change).

    Stall Indicators:
    - No file changes for N iterations
    - Same test failures for N iterations
    - Zero progress delta (no lines added/removed, no tests added)
    - Same error signature repeating

    Args:
        current_step_id: The current step being evaluated.
        progress_history: List of ProgressEvidence from recent iterations.
        max_stall_iterations: How many iterations with no progress before stall.

    Returns:
        Tuple of (is_stalled, StallAnalysis with details if stalled).
    """
    if len(progress_history) < max_stall_iterations:
        # Not enough history to detect a stall
        return False, None

    # Get the most recent N entries for the current step
    step_history = [e for e in progress_history if e.step_id == current_step_id]
    if len(step_history) < max_stall_iterations:
        return False, None

    recent = step_history[-max_stall_iterations:]

    # Check for stall conditions
    stall_indicators = []
    evidence_ids = [e.evidence_id for e in recent]

    # Indicator 1: No file changes for N iterations
    no_file_changes = all(e.delta.files_changed == 0 for e in recent)
    if no_file_changes:
        stall_indicators.append("no_file_changes")

    # Indicator 2: Same error signature repeating
    error_hashes = [e.current_error_hash for e in recent if e.current_error_hash]
    if len(error_hashes) >= max_stall_iterations:
        unique_errors = set(error_hashes)
        if len(unique_errors) == 1:
            stall_indicators.append("same_error_repeating")

    # Indicator 3: Zero net progress (no lines added/removed)
    zero_net_progress = all(
        e.delta.lines_added == 0 and e.delta.lines_removed == 0 for e in recent
    )
    if zero_net_progress:
        stall_indicators.append("zero_line_changes")

    # Indicator 4: No meaningful change at all
    no_meaningful_change = all(not e.delta.has_meaningful_change for e in recent)
    if no_meaningful_change:
        stall_indicators.append("no_meaningful_change")

    # Indicator 5: Test output hash is identical
    test_hashes = [e.test_output_hash for e in recent if e.test_output_hash]
    if len(test_hashes) >= max_stall_iterations:
        unique_tests = set(test_hashes)
        if len(unique_tests) == 1:
            stall_indicators.append("same_test_failures")

    # Determine if stalled based on indicator combination
    is_stalled = False
    stall_type = ""
    confidence = 0.0

    # Strong stall: multiple indicators present
    if len(stall_indicators) >= 3:
        is_stalled = True
        stall_type = "severe_stall"
        confidence = 0.95
    elif len(stall_indicators) >= 2:
        is_stalled = True
        stall_type = "moderate_stall"
        confidence = 0.8
    elif "same_error_repeating" in stall_indicators and "no_file_changes" in stall_indicators:
        is_stalled = True
        stall_type = "error_loop_stall"
        confidence = 0.9
    elif "no_meaningful_change" in stall_indicators:
        # This alone is a strong signal
        is_stalled = True
        stall_type = "progress_stall"
        confidence = 0.85

    if not is_stalled:
        return False, None

    # Determine recommendation based on stall severity
    recommendation = "try_detour"
    if stall_type == "severe_stall":
        recommendation = "escalate_to_human"
    elif stall_type == "error_loop_stall":
        recommendation = "inject_clarifier"

    reason = (
        f"Stall detected after {max_stall_iterations} iterations: "
        f"{', '.join(stall_indicators)}"
    )

    analysis = StallAnalysis(
        is_stalled=True,
        stall_type=stall_type,
        stall_count=max_stall_iterations,
        reason=reason,
        recommendation=recommendation,
        evidence_ids=evidence_ids,
        confidence=confidence,
    )

    logger.warning(
        "Elephant Protocol: %s detected for step %s - %s",
        stall_type,
        current_step_id,
        reason,
    )

    return True, analysis


def record_progress_evidence(
    run_state: RunState,
    step_id: str,
    iteration: int,
    file_changes: Optional[Dict[str, Any]] = None,
    test_output: Optional[str] = None,
    error_output: Optional[str] = None,
    status: str = "",
) -> ProgressEvidence:
    """Record progress evidence for stall detection.

    Creates a ProgressEvidence record and appends it to the run state's
    progress history. This should be called after each step execution.

    Args:
        run_state: The current run state to update.
        step_id: The step that produced this evidence.
        iteration: Which iteration of the microloop this represents.
        file_changes: Dict with file change information (from diff_scanner).
        test_output: Raw test output string.
        error_output: Raw error output string.
        status: The step status (VERIFIED, UNVERIFIED, BLOCKED).

    Returns:
        The created ProgressEvidence record.
    """
    import secrets

    # Initialize progress history if not present
    if not hasattr(run_state, "progress_evidence_history"):
        run_state.progress_evidence_history = []  # type: ignore[attr-defined]

    # Get previous error hash for comparison
    previous_error_hash = ""
    history: List[ProgressEvidence] = getattr(run_state, "progress_evidence_history", [])
    step_history = [e for e in history if e.step_id == step_id]
    if step_history:
        previous_error_hash = step_history[-1].current_error_hash

    # Extract metrics from file_changes
    lines_added = 0
    lines_removed = 0
    files_changed = 0

    if file_changes:
        lines_added = file_changes.get("total_insertions", 0)
        lines_removed = file_changes.get("total_deletions", 0)
        files_list = file_changes.get("files", [])
        files_changed = len(files_list) if isinstance(files_list, list) else 0

    # Compute hashes
    current_error_hash = compute_error_signature(error_output or "")
    test_output_hash = compute_error_signature(test_output or "")

    # Create delta
    delta = ProgressDelta(
        lines_added=lines_added,
        lines_removed=lines_removed,
        files_changed=files_changed,
        tests_added=0,  # Could be extracted from test output if needed
        tests_fixed=0,  # Could be computed by comparing test results
        error_signature=current_error_hash,
        status=status,
    )

    # Create evidence record
    evidence = ProgressEvidence(
        evidence_id=f"ev-{secrets.token_hex(8)}",
        step_id=step_id,
        iteration=iteration,
        delta=delta,
        timestamp=datetime.now(timezone.utc),
        test_output_hash=test_output_hash,
        previous_error_hash=previous_error_hash,
        current_error_hash=current_error_hash,
    )

    # Append to history
    run_state.progress_evidence_history.append(evidence)  # type: ignore[attr-defined]

    logger.debug(
        "Recorded progress evidence for step %s iteration %d: "
        "files=%d, +%d/-%d lines, errors_changed=%s",
        step_id,
        iteration,
        files_changed,
        lines_added,
        lines_removed,
        evidence.errors_changed(),
    )

    return evidence


def create_stall_routing_signal(
    stall_analysis: StallAnalysis,
    routing: Optional[Any] = None,
) -> RoutingSignal:
    """Create a RoutingSignal for a stall condition.

    Args:
        stall_analysis: The stall analysis results.
        routing: Optional routing config from the step.

    Returns:
        RoutingSignal forcing termination or detour based on stall severity.
    """
    # Determine decision based on recommendation
    decision = RoutingDecision.TERMINATE
    next_step_id = None

    if stall_analysis.recommendation == "try_detour":
        decision = RoutingDecision.BRANCH
        # Could set next_step_id to a clarifier step if available
    elif stall_analysis.recommendation == "inject_clarifier":
        decision = RoutingDecision.BRANCH
        # Could inject a clarification step

    # If we have a next step from routing config, use it for termination
    if routing and hasattr(routing, "next") and routing.next:
        next_step_id = routing.next
        decision = RoutingDecision.ADVANCE

    reason = f"Elephant Protocol: {stall_analysis.reason}"

    # Build deterministic candidate ID for audit trail
    candidate_id = f"stall:{decision.value}:{next_step_id or 'none'}"

    return RoutingSignal(
        decision=decision,
        next_step_id=next_step_id,
        reason=reason,
        confidence=stall_analysis.confidence,
        needs_human=stall_analysis.recommendation == "escalate_to_human",
        exit_condition_met=True,
        routing_source="elephant_protocol_stall",
        chosen_candidate_id=candidate_id,
        routing_candidates=[
            RoutingCandidate(
                candidate_id=candidate_id,
                action=decision.value,
                target_node=next_step_id,
                reason=reason,
                priority=100,
                source="stall_detection",
            )
        ],
    )


# Type for receipt field reader function
ReceiptReader = Callable[[str, str, str, str, str], Optional[str]]


def create_routing_signal(
    step: StepDefinition,
    result: Dict[str, Any],
    loop_state: Dict[str, int],
    receipt_reader: Optional[ReceiptReader] = None,
    spec_routing: Optional[Dict[str, Any]] = None,
    spec_exit_on: Optional[Dict[str, Any]] = None,
    run_state: Optional[RunState] = None,
) -> RoutingSignal:
    """Create a RoutingSignal from step result and routing config.

    Uses spec-first routing when spec_routing is available, otherwise
    falls back to config-based routing from step.routing.

    Supports Elephant Protocol stall detection when run_state is provided
    with progress_evidence_history.

    Args:
        step: The step that was executed.
        result: The step execution result dictionary.
        loop_state: Dictionary tracking iteration counts per microloop.
        receipt_reader: Optional function to read receipt fields.
            Signature: (run_id, flow_key, step_id, agent_key, field_name) -> Optional[str]
        spec_routing: Optional routing config from FlowSpec.
        spec_exit_on: Optional exit_on conditions from FlowSpec.
        run_state: Optional run state for stall detection (Elephant Protocol).

    Returns:
        A RoutingSignal with the routing decision.
    """
    # Use spec-first if available
    if spec_routing:
        return _create_routing_signal_from_spec(
            step, result, loop_state, spec_routing, spec_exit_on, receipt_reader, run_state
        )

    # Fall back to config-based routing
    return _create_routing_signal_from_config(step, result, loop_state, receipt_reader, run_state)


def _create_routing_signal_from_config(
    step: StepDefinition,
    result: Dict[str, Any],
    loop_state: Dict[str, int],
    receipt_reader: Optional[ReceiptReader] = None,
    run_state: Optional[RunState] = None,
) -> RoutingSignal:
    """Create a RoutingSignal using config-based routing.

    Args:
        step: The step that was executed.
        result: The step execution result dictionary.
        loop_state: Dictionary tracking iteration counts.
        receipt_reader: Optional function to read receipt fields.
        run_state: Optional run state for stall detection (Elephant Protocol).

    Returns:
        A RoutingSignal with the routing decision.
    """
    routing = step.routing

    # Default values
    decision = RoutingDecision.ADVANCE
    next_step_id = None
    reason = "step_complete"
    confidence = 1.0
    needs_human = False

    if routing is None:
        # No routing config: fall back to linear progression
        # Find next step by index using flow_def from step
        if hasattr(step, "flow_def") and step.flow_def:
            for s in step.flow_def.steps:
                if s.index == step.index + 1:
                    next_step_id = s.id
                    reason = "linear_default"
                    break
        if next_step_id is None:
            decision = RoutingDecision.TERMINATE
            reason = "flow_complete_no_routing"

    elif routing.kind == "linear":
        if routing.next:
            next_step_id = routing.next
            reason = "linear_explicit"
        else:
            decision = RoutingDecision.TERMINATE
            reason = "flow_complete_linear"

    elif routing.kind == "microloop":
        result_signal = _handle_microloop_routing(
            step, result, loop_state, routing, receipt_reader, run_state
        )
        return result_signal

    elif routing.kind == "branch":
        # Branch routing based on result values
        if routing.branches and result.get("status"):
            branch_key = result.get("status")
            if branch_key in routing.branches:
                next_step_id = routing.branches[branch_key]
                reason = f"branch:{branch_key}"

        # Fallback to next
        if next_step_id is None and routing.next:
            next_step_id = routing.next
            reason = "branch_fallback"

    # Build deterministic candidate ID for audit trail
    candidate_id = f"{decision.value}:{next_step_id or 'none'}"

    return RoutingSignal(
        decision=decision,
        next_step_id=next_step_id,
        reason=reason,
        confidence=confidence,
        needs_human=needs_human,
        routing_source="config_routing",
        chosen_candidate_id=candidate_id,
        routing_candidates=[
            RoutingCandidate(
                candidate_id=candidate_id,
                action=decision.value,
                target_node=next_step_id,
                reason=reason,
                priority=50,
                source="routing_config",
            )
        ],
    )


def _handle_microloop_routing(
    step: StepDefinition,
    result: Dict[str, Any],
    loop_state: Dict[str, int],
    routing: Any,  # StepRouting
    receipt_reader: Optional[ReceiptReader] = None,
    run_state: Optional[RunState] = None,
) -> RoutingSignal:
    """Handle microloop routing logic with Elephant Protocol stall detection.

    Args:
        step: The step that was executed.
        result: The step execution result dictionary.
        loop_state: Dictionary tracking iteration counts.
        routing: The step's routing configuration.
        receipt_reader: Optional function to read receipt fields.
        run_state: Optional run state for progress tracking and stall detection.

    Returns:
        RoutingSignal for the microloop.
    """
    decision = RoutingDecision.ADVANCE
    next_step_id = None
    reason = "step_complete"

    # Check loop iteration count
    loop_key = f"{step.id}:{routing.loop_target}"
    current_iter = loop_state.get(loop_key, 0)

    # =========================================================================
    # Elephant Protocol: Stall Detection
    # =========================================================================
    # Check for stall BEFORE checking max iterations. If we're stalled,
    # continuing to loop is wasteful regardless of iteration count.
    if run_state is not None:
        progress_history: List[ProgressEvidence] = getattr(
            run_state, "progress_evidence_history", []
        )
        if progress_history:
            is_stalled, stall_analysis = detect_stall(
                current_step_id=step.id,
                progress_history=progress_history,
                max_stall_iterations=3,  # Default: 3 iterations without progress = stall
            )

            if is_stalled and stall_analysis:
                # Force exit from the loop due to stall
                logger.info(
                    "Elephant Protocol: Forcing loop exit for step %s due to %s",
                    step.id,
                    stall_analysis.stall_type,
                )
                return create_stall_routing_signal(stall_analysis, routing)

    # Safety check: max iterations (safety fuse, not steering mechanism)
    if current_iter >= routing.max_iterations:
        if routing.next:
            next_step_id = routing.next
            reason = f"max_iterations_reached:{routing.max_iterations}"
        else:
            decision = RoutingDecision.TERMINATE
            reason = f"flow_complete_max_iterations:{routing.max_iterations}"
        candidate_id = f"microloop:max_iter:{next_step_id or 'exit'}"
        return RoutingSignal(
            decision=decision,
            next_step_id=next_step_id,
            reason=reason,
            confidence=1.0,
            needs_human=False,
            routing_source="microloop_routing",
            chosen_candidate_id=candidate_id,
            routing_candidates=[RoutingCandidate(
                candidate_id=candidate_id,
                action=decision.value if hasattr(decision, 'value') else str(decision),
                target_node=next_step_id,
                reason=reason,
                priority=60,
                source="microloop_state",
            )],
        )

    # Check loop condition from receipt
    if routing.loop_condition_field and receipt_reader:
        agent_key = step.agents[0] if step.agents else "unknown"
        run_id = result.get("run_id", "")
        flow_key = result.get("flow_key", "")

        field_value = receipt_reader(
            run_id, flow_key, step.id, agent_key, routing.loop_condition_field
        )

        if field_value and field_value in routing.loop_success_values:
            # Condition met, exit loop
            if routing.next:
                next_step_id = routing.next
                reason = f"loop_exit_condition_met:{field_value}"
            else:
                decision = RoutingDecision.TERMINATE
                reason = f"flow_complete_condition_met:{field_value}"
            candidate_id = f"microloop:exit:{next_step_id or 'complete'}"
            return RoutingSignal(
                decision=decision,
                next_step_id=next_step_id,
                reason=reason,
                confidence=1.0,
                needs_human=False,
                routing_source="microloop_routing",
                chosen_candidate_id=candidate_id,
                routing_candidates=[RoutingCandidate(
                    candidate_id=candidate_id,
                    action=decision.value if hasattr(decision, 'value') else str(decision),
                    target_node=next_step_id,
                    reason=reason,
                    priority=60,
                    source="microloop_state",
                )],
            )

        # Check can_further_iteration_help field as fallback
        can_iterate = receipt_reader(
            run_id, flow_key, step.id, agent_key, "can_further_iteration_help"
        )
        if can_iterate and can_iterate.lower() == "no":
            # Critic says no further iteration will help
            if routing.next:
                next_step_id = routing.next
                reason = "loop_exit_no_further_help"
            else:
                decision = RoutingDecision.TERMINATE
                reason = "flow_complete_no_further_help"
            candidate_id = f"microloop:no_help:{next_step_id or 'complete'}"
            return RoutingSignal(
                decision=decision,
                next_step_id=next_step_id,
                reason=reason,
                confidence=1.0,
                needs_human=False,
                routing_source="microloop_routing",
                chosen_candidate_id=candidate_id,
                routing_candidates=[RoutingCandidate(
                    candidate_id=candidate_id,
                    action=decision.value if hasattr(decision, 'value') else str(decision),
                    target_node=next_step_id,
                    reason=reason,
                    priority=60,
                    source="microloop_state",
                )],
            )

    # Loop back to target
    if routing.loop_target:
        next_step_id = routing.loop_target
        reason = f"loop_iteration:{current_iter + 1}"
        decision = RoutingDecision.LOOP

    # Determine decision type for candidate ID
    decision_type = "loop" if decision == RoutingDecision.LOOP else "advance"
    candidate_id = f"microloop:{decision_type}:{next_step_id or 'exit'}"

    return RoutingSignal(
        decision=decision,
        next_step_id=next_step_id,
        reason=reason,
        confidence=1.0,
        needs_human=False,
        routing_source="microloop_routing",
        chosen_candidate_id=candidate_id,
        routing_candidates=[RoutingCandidate(
            candidate_id=candidate_id,
            action=decision.value if hasattr(decision, 'value') else str(decision),
            target_node=next_step_id,
            reason=reason,
            priority=60,
            source="microloop_state",
        )],
    )


def _create_routing_signal_from_spec(
    step: StepDefinition,
    result: Dict[str, Any],
    loop_state: Dict[str, int],
    spec_routing: Dict[str, Any],
    spec_exit_on: Optional[Dict[str, Any]] = None,
    receipt_reader: Optional[ReceiptReader] = None,
    run_state: Optional[RunState] = None,
) -> RoutingSignal:
    """Create a RoutingSignal using FlowSpec routing configuration.

    Supports routing kinds: linear, microloop, branch, terminal.
    Supports exit_on conditions for microloops.
    Supports Elephant Protocol stall detection for microloops.

    Args:
        step: The step that was executed.
        result: The step execution result dictionary.
        loop_state: Dictionary tracking iteration counts per microloop.
        spec_routing: Routing configuration from FlowSpec.
        spec_exit_on: Optional exit_on conditions from FlowSpec.
        receipt_reader: Optional function to read receipt fields.
        run_state: Optional run state for stall detection (Elephant Protocol).

    Returns:
        A RoutingSignal with the routing decision.
    """
    kind = spec_routing.get("kind", "linear")
    decision = RoutingDecision.ADVANCE
    next_step_id = None
    reason = "step_complete"
    confidence = 1.0
    needs_human = False
    loop_count = 0
    exit_condition_met = False

    if kind == "terminal":
        candidate_id = "spec:terminate:terminal_step"
        return RoutingSignal(
            decision=RoutingDecision.TERMINATE,
            next_step_id=None,
            reason="terminal_step",
            confidence=confidence,
            needs_human=needs_human,
            routing_source="spec_routing",
            chosen_candidate_id=candidate_id,
            routing_candidates=[RoutingCandidate(
                candidate_id=candidate_id,
                action="terminate",
                target_node=None,
                reason="terminal_step",
                priority=70,
                source="flow_spec",
            )],
        )

    elif kind == "linear":
        next_step_id = spec_routing.get("next")
        if next_step_id:
            reason = "linear_via_spec"
        else:
            decision = RoutingDecision.TERMINATE
            reason = "flow_complete_via_spec"

    elif kind == "microloop":
        loop_target = spec_routing.get("loop_target")
        next_after_loop = spec_routing.get("next")
        max_iterations = spec_routing.get("max_iterations", 3)

        loop_key = f"{step.id}:{loop_target}" if loop_target else step.id
        current_iter = loop_state.get(loop_key, 0)
        loop_count = current_iter

        # =====================================================================
        # Elephant Protocol: Stall Detection (before other exit conditions)
        # =====================================================================
        if run_state is not None:
            progress_history: List[ProgressEvidence] = getattr(
                run_state, "progress_evidence_history", []
            )
            if progress_history:
                is_stalled, stall_analysis = detect_stall(
                    current_step_id=step.id,
                    progress_history=progress_history,
                    max_stall_iterations=3,
                )

                if is_stalled and stall_analysis:
                    logger.info(
                        "Elephant Protocol (spec): Forcing loop exit for step %s due to %s",
                        step.id,
                        stall_analysis.stall_type,
                    )
                    # Create a routing signal with stall info but preserve spec behavior
                    stall_signal = create_stall_routing_signal(stall_analysis, None)
                    # Override next_step_id with spec's next if available
                    if next_after_loop:
                        stall_signal.next_step_id = next_after_loop
                        stall_signal.decision = RoutingDecision.ADVANCE
                    return stall_signal

        # Check exit_on conditions from FlowSpec
        if spec_exit_on:
            # Check status condition
            status_values = spec_exit_on.get("status", [])
            step_status = result.get("status", "")
            if status_values and step_status in status_values:
                exit_condition_met = True
                reason = f"exit_on_status:{step_status}"

            # Check can_further_iteration_help condition
            if spec_exit_on.get("can_further_iteration_help") is False and receipt_reader:
                agent_key = step.agents[0] if step.agents else "unknown"
                run_id = result.get("run_id", "")
                flow_key = result.get("flow_key", "")

                can_iterate = receipt_reader(
                    run_id, flow_key, step.id, agent_key, "can_further_iteration_help"
                )
                if can_iterate and can_iterate.lower() == "no":
                    exit_condition_met = True
                    reason = "exit_on_no_further_help"

        # Check max iterations (safety fuse, not steering mechanism)
        if current_iter >= max_iterations:
            exit_condition_met = True
            reason = f"max_iterations_reached:{max_iterations}"

        if exit_condition_met:
            if next_after_loop:
                next_step_id = next_after_loop
                decision = RoutingDecision.ADVANCE
            else:
                decision = RoutingDecision.TERMINATE
        else:
            # Loop back
            if loop_target:
                next_step_id = loop_target
                decision = RoutingDecision.LOOP
                reason = f"loop_iteration:{current_iter + 1}"

    elif kind == "branch":
        branches = spec_routing.get("branches", {})
        step_status = result.get("status", "")

        if branches and step_status in branches:
            next_step_id = branches[step_status]
            reason = f"branch_via_spec:{step_status}"
            decision = RoutingDecision.BRANCH
        else:
            # Default/fallback
            next_step_id = spec_routing.get("next")
            if next_step_id:
                reason = "branch_default_via_spec"
            else:
                decision = RoutingDecision.TERMINATE
                reason = "flow_complete_branch_via_spec"

    # Build candidate ID based on decision type
    decision_name = decision.value if hasattr(decision, "value") else str(decision)
    candidate_id = f"spec:{decision_name}:{next_step_id or 'complete'}"

    return RoutingSignal(
        decision=decision,
        next_step_id=next_step_id,
        reason=reason,
        confidence=confidence,
        needs_human=needs_human,
        loop_count=loop_count,
        exit_condition_met=exit_condition_met,
        routing_source="spec_routing",
        chosen_candidate_id=candidate_id,
        routing_candidates=[
            RoutingCandidate(
                candidate_id=candidate_id,
                action=decision_name,
                target_node=next_step_id,
                reason=reason,
                priority=70,
                source="flow_spec",
            )
        ],
    )


def route_step(
    flow_def: FlowDefinition,
    current_step: StepDefinition,
    result: Dict[str, Any],
    loop_state: Dict[str, int],
    run_id: str,
    flow_key: str,
    handoff_envelope: Optional[HandoffEnvelope] = None,
    receipt_reader: Optional[ReceiptReader] = None,
) -> Tuple[Optional[str], str]:
    """Determine the next step based on routing config and result.

    Supports three routing patterns:
    - linear: Simple sequential flow to the next step
    - microloop: Loops back to a target step until a condition is met
    - branch: Chooses next step based on result values

    When a HandoffEnvelope is provided, uses its RoutingSignal for routing
    decisions. Otherwise, falls back to receipt-based routing.

    Args:
        flow_def: The flow definition with all steps.
        current_step: The step that just completed.
        result: The step execution result dictionary.
        loop_state: Dictionary tracking iteration counts per step.
        run_id: The run identifier (for reading receipts).
        flow_key: The flow key (for reading receipts).
        handoff_envelope: Optional HandoffEnvelope with routing signal.
        receipt_reader: Optional function to read receipt fields.

    Returns:
        Tuple of (next_step_id or None if flow is complete, reason string).
    """
    routing = current_step.routing

    # Use handoff envelope if available
    if handoff_envelope is not None:
        signal = handoff_envelope.routing_signal
        if signal.decision == RoutingDecision.TERMINATE:
            return None, signal.reason or "flow_complete_via_signal"
        elif signal.decision == RoutingDecision.ADVANCE:
            next_step_id = signal.next_step_id
            if next_step_id is None and routing and routing.next:
                next_step_id = routing.next
            return next_step_id, signal.reason or "advance_via_signal"
        elif signal.decision == RoutingDecision.LOOP:
            if routing and routing.loop_target:
                loop_key = f"{current_step.id}:{routing.loop_target}"
                current_iter = loop_state.get(loop_key, 0)
                loop_state[loop_key] = current_iter + 1
                return routing.loop_target, signal.reason or f"loop_iteration:{current_iter + 1}"
        elif signal.decision == RoutingDecision.BRANCH:
            next_step_id = signal.next_step_id
            if next_step_id:
                return next_step_id, signal.reason or "branch_via_signal"

        # Signal didn't resolve, fall through
        logger.debug(
            "RoutingSignal did not resolve routing for step %s (decision=%s), falling back",
            current_step.id,
            signal.decision,
        )

    # Fallback: receipt-based routing
    if routing is None:
        # Default linear behavior: find next step by index
        next_step = None
        for step in flow_def.steps:
            if step.index == current_step.index + 1:
                next_step = step
                break
        if next_step:
            return next_step.id, "linear_default"
        return None, "flow_complete_no_routing"

    # Handle routing based on kind
    if routing.kind == "linear":
        if routing.next:
            return routing.next, "linear_explicit"
        return None, "flow_complete_linear"

    elif routing.kind == "microloop":
        return _route_microloop(current_step, routing, loop_state, run_id, flow_key, receipt_reader)

    elif routing.kind == "branch":
        # Branch routing based on result values
        if routing.branches and result.get("status"):
            branch_key = result.get("status")
            if branch_key in routing.branches:
                return routing.branches[branch_key], f"branch:{branch_key}"

        # Fallback to next
        if routing.next:
            return routing.next, "branch_fallback"
        return None, "flow_complete_branch"

    # Unknown routing kind, fall back to linear
    logger.warning("Unknown routing kind '%s', falling back to linear", routing.kind)
    if routing.next:
        return routing.next, "unknown_kind_fallback"
    return None, "flow_complete_unknown"


def _route_microloop(
    current_step: StepDefinition,
    routing: Any,  # StepRouting
    loop_state: Dict[str, int],
    run_id: str,
    flow_key: str,
    receipt_reader: Optional[ReceiptReader] = None,
) -> Tuple[Optional[str], str]:
    """Handle microloop routing.

    Args:
        current_step: The step that just completed.
        routing: The step's routing configuration.
        loop_state: Dictionary tracking iteration counts.
        run_id: The run identifier.
        flow_key: The flow key.
        receipt_reader: Optional function to read receipt fields.

    Returns:
        Tuple of (next_step_id or None, reason string).
    """
    loop_key = f"{current_step.id}:{routing.loop_target}"
    current_iter = loop_state.get(loop_key, 0)

    # Safety check: max iterations
    if current_iter >= routing.max_iterations:
        logger.warning(
            "Microloop %s reached max iterations (%d), exiting to next step",
            loop_key,
            routing.max_iterations,
        )
        if routing.next:
            return routing.next, f"max_iterations_reached:{routing.max_iterations}"
        return None, f"flow_complete_max_iterations:{routing.max_iterations}"

    # Check loop condition from receipt
    if routing.loop_condition_field and receipt_reader:
        agent_key = current_step.agents[0] if current_step.agents else "unknown"
        field_value = receipt_reader(
            run_id, flow_key, current_step.id, agent_key, routing.loop_condition_field
        )

        if field_value and field_value in routing.loop_success_values:
            # Condition met, exit loop
            if routing.next:
                return routing.next, f"loop_exit_condition_met:{field_value}"
            return None, f"flow_complete_condition_met:{field_value}"

        # Check can_further_iteration_help field as fallback
        can_iterate = receipt_reader(
            run_id, flow_key, current_step.id, agent_key, "can_further_iteration_help"
        )
        if can_iterate and can_iterate.lower() == "no":
            # Critic says no further iteration will help
            if routing.next:
                return routing.next, "loop_exit_no_further_help"
            return None, "flow_complete_no_further_help"

    # Loop back to target
    if routing.loop_target:
        loop_state[loop_key] = current_iter + 1
        return routing.loop_target, f"loop_iteration:{current_iter + 1}"

    # Fallback to next if no loop target
    if routing.next:
        return routing.next, "microloop_no_target"
    return None, "flow_complete_microloop_fallback"


def build_routing_context(
    current_step: StepDefinition,
    loop_state: Dict[str, int],
) -> "RoutingContext":
    """Build a RoutingContext for inclusion in step execution context.

    Args:
        current_step: The step being executed.
        loop_state: Dictionary tracking iteration counts.

    Returns:
        RoutingContext with loop state information.
    """
    from swarm.runtime.engines.models import RoutingContext

    routing = current_step.routing

    if routing is None:
        return RoutingContext(
            loop_iteration=0,
            max_iterations=None,
            decision="advance",
            reason="no_routing_config",
        )

    if routing.kind != "microloop":
        return RoutingContext(
            loop_iteration=0,
            max_iterations=None,
            decision="advance",
            reason=f"routing_kind:{routing.kind}",
        )

    loop_key = f"{current_step.id}:{routing.loop_target}"
    current_iter = loop_state.get(loop_key, 0)

    return RoutingContext(
        loop_iteration=current_iter,
        max_iterations=routing.max_iterations,
        decision="pending",
        reason="",
    )


# =============================================================================
# Forensic Priority Shaping Helper Functions
# =============================================================================


def _detect_forensic_problems(forensic_verdict: Dict[str, Any]) -> bool:
    """Check if forensic verdict indicates problems requiring priority shaping.

    Problems are detected when:
    - recommendation is REJECT (major discrepancies)
    - recommendation is VERIFY (minor discrepancies worth checking)
    - reward_hacking_flags are present (specific gaming patterns detected)
    - critical severity discrepancies exist

    Args:
        forensic_verdict: Dict containing forensic analysis results.

    Returns:
        True if problems detected that warrant priority shaping.
    """
    # Check for REJECT or VERIFY recommendation (not TRUST)
    recommendation = forensic_verdict.get("recommendation", "TRUST")
    if recommendation in ("REJECT", "VERIFY"):
        return True

    # Check for reward hacking flags
    reward_hacking_flags = forensic_verdict.get("reward_hacking_flags", [])
    if reward_hacking_flags:
        return True

    # Check for critical discrepancies
    if _count_critical_discrepancies(forensic_verdict) > 0:
        return True

    return False


def _count_critical_discrepancies(forensic_verdict: Dict[str, Any]) -> int:
    """Count the number of critical severity discrepancies.

    Args:
        forensic_verdict: Dict containing forensic analysis results.

    Returns:
        Number of critical discrepancies.
    """
    discrepancies = forensic_verdict.get("discrepancies", [])
    return sum(
        1 for d in discrepancies
        if isinstance(d, dict) and d.get("severity") == "critical"
    )


def _build_forensic_evidence_pointers(forensic_verdict: Dict[str, Any]) -> List[str]:
    """Build evidence pointers from forensic verdict for candidate transparency.

    Creates a list of human-readable evidence strings that explain why
    forensic shaping was applied. These are attached to affected candidates
    so the Navigator (and audit logs) can see the reasoning.

    Args:
        forensic_verdict: Dict containing forensic analysis results.

    Returns:
        List of evidence pointer strings.
    """
    evidence: List[str] = []

    # Add recommendation as evidence
    recommendation = forensic_verdict.get("recommendation", "TRUST")
    if recommendation != "TRUST":
        evidence.append(f"forensic_verdict:{recommendation}")

    # Add reward hacking flags
    reward_hacking_flags = forensic_verdict.get("reward_hacking_flags", [])
    for flag in reward_hacking_flags[:3]:  # Limit to first 3 flags
        evidence.append(f"reward_hacking:{flag}")

    # Add critical discrepancy categories
    discrepancies = forensic_verdict.get("discrepancies", [])
    critical_categories = set()
    for d in discrepancies:
        if isinstance(d, dict) and d.get("severity") == "critical":
            category = d.get("category", "unknown")
            critical_categories.add(category)

    for category in list(critical_categories)[:2]:  # Limit to first 2 categories
        evidence.append(f"critical_discrepancy:{category}")

    # Add confidence if below threshold
    confidence = forensic_verdict.get("confidence", 1.0)
    if confidence < 0.5:
        evidence.append(f"low_confidence:{confidence:.2f}")

    return evidence


# =============================================================================
# Candidate-Set Pattern: Generate routing candidates from graph and context
# =============================================================================


def generate_routing_candidates(
    step: StepDefinition,
    step_result: Dict[str, Any],
    flow_def: FlowDefinition,
    loop_state: Dict[str, int],
    run_state: Optional[RunState] = None,
    sidequest_options: Optional[List[Dict[str, Any]]] = None,
    forensic_verdict: Optional[Dict[str, Any]] = None,
) -> List[RoutingCandidate]:
    """Generate routing candidates for Navigator to choose from.

    The candidate-set pattern: Python generates candidates from the graph
    and context. Navigator intelligently chooses among them. Python validates
    the choice and executes.

    This keeps intelligence bounded while preserving graph constraints.
    All candidates are valid options from the graph - the Navigator cannot
    "hallucinate" a step that doesn't exist.

    IMPORTANT: Candidate IDs are DETERMINISTIC and derived from semantics:
    - advance:<target_step_id>
    - loop:<loop_target>:iter_<n>
    - terminate
    - repeat:<step_id>
    - escalate
    - detour:<sidequest_id>

    This enables:
    - Reproducible routing decisions for debugging
    - Reliable UI display of chosen vs rejected candidates
    - Consistent resume/replay behavior

    Forensic Priority Shaping:
    When forensic_verdict indicates problems (REJECT verdict, reward_hacking_flags,
    critical discrepancies), candidate priorities are adjusted:
    - ADVANCE candidates: demoted by 30-40 points
    - REPEAT candidates: promoted by 20 points
    - ESCALATE candidates: promoted by 30 points

    This ensures that problematic steps don't blindly advance, instead encouraging
    retry or human review when forensic evidence contradicts worker claims.

    Args:
        step: The current step definition.
        step_result: Result from step execution (status, output, etc.).
        flow_def: The flow definition containing all steps.
        loop_state: Microloop iteration state.
        run_state: Optional run state for stall detection.
        sidequest_options: Optional list of available sidequests/detours.
        forensic_verdict: Optional forensic verdict dict with:
            - recommendation: "TRUST", "VERIFY", or "REJECT"
            - reward_hacking_flags: List of detected reward hacking patterns
            - discrepancies: List of claim vs evidence discrepancies
            - confidence: Confidence score (0.0-1.0)

    Returns:
        List of RoutingCandidate objects, sorted by priority (highest first).
        The first candidate is typically the default choice.
    """
    candidates: List[RoutingCandidate] = []
    routing = step.routing
    status = step_result.get("status", "")

    # ==========================================================================
    # Candidate 1: ADVANCE to next step (if available)
    # ==========================================================================
    if routing and routing.next:
        is_default = status in ("VERIFIED", "verified")
        candidates.append(
            RoutingCandidate(
                candidate_id=f"advance:{routing.next}",  # Deterministic ID
                action="advance",
                target_node=routing.next,
                reason="Advance to next step in sequence",
                priority=80 if is_default else 40,
                source="graph_edge",
                is_default=is_default,
            )
        )

    # ==========================================================================
    # Candidate 2: LOOP back (for microloops)
    # ==========================================================================
    if routing and routing.kind == "microloop" and routing.loop_target:
        loop_key = f"{step.id}:{routing.loop_target}"
        current_iter = loop_state.get(loop_key, 0)

        # Check if we can iterate
        can_iterate = True
        can_iterate_val = step_result.get("can_further_iteration_help")
        if can_iterate_val is not None:
            can_iterate = str(can_iterate_val).lower() not in ("no", "false")

        # Check if under max iterations
        under_max = current_iter < routing.max_iterations

        if under_max and can_iterate and status in ("PARTIAL", "partial", "UNVERIFIED", "unverified"):
            is_default = True
            candidates.append(
                RoutingCandidate(
                    candidate_id=f"loop:{routing.loop_target}:iter_{current_iter + 1}",  # Deterministic ID
                    action="loop",
                    target_node=routing.loop_target,
                    reason=f"Loop back for iteration {current_iter + 1} (max: {routing.max_iterations})",
                    priority=90 if is_default else 60,
                    source="graph_edge",
                    evidence_pointers=[f"iteration:{current_iter}", f"status:{status}"],
                    is_default=is_default,
                )
            )

    # ==========================================================================
    # Candidate 3: TERMINATE (if at terminal step or no next)
    # ==========================================================================
    if routing is None or (routing.kind == "linear" and routing.next is None):
        is_default = status in ("VERIFIED", "verified")
        candidates.append(
            RoutingCandidate(
                candidate_id="terminate",  # Deterministic ID
                action="terminate",
                target_node=None,
                reason="Flow complete - no more steps",
                priority=70 if is_default else 30,
                source="graph_edge",
                is_default=is_default,
            )
        )

    # ==========================================================================
    # Candidate 4: REPEAT current step (if PARTIAL and can retry)
    # ==========================================================================
    if status in ("PARTIAL", "partial"):
        candidates.append(
            RoutingCandidate(
                candidate_id=f"repeat:{step.id}",  # Deterministic ID
                action="repeat",
                target_node=step.id,
                reason="Repeat current step (partial completion)",
                priority=50,
                source="fast_path",
                evidence_pointers=[f"status:{status}"],
                is_default=False,
            )
        )

    # ==========================================================================
    # Candidate 5: ESCALATE (if BLOCKED)
    # ==========================================================================
    if status in ("BLOCKED", "blocked"):
        candidates.append(
            RoutingCandidate(
                candidate_id="escalate",  # Deterministic ID
                action="escalate",
                target_node=None,
                reason="Escalate - step is blocked and cannot proceed",
                priority=100,  # Highest priority when blocked
                source="fast_path",
                evidence_pointers=[f"status:{status}"],
                is_default=True,
            )
        )

    # ==========================================================================
    # Candidate 6+: DETOUR options (from sidequest catalog)
    # ==========================================================================
    if sidequest_options:
        for sq in sidequest_options:
            sq_id = sq.get("sidequest_id", sq.get("id", "unknown"))
            sq_name = sq.get("name", sq_id)
            sq_priority = sq.get("priority", 30)
            candidates.append(
                RoutingCandidate(
                    candidate_id=f"detour:{sq_id}",  # Deterministic ID
                    action="detour",
                    target_node=f"sq-{sq_id}-0",  # First step of sidequest
                    reason=f"Detour: {sq_name}",
                    priority=sq_priority,
                    source="detour_catalog",
                    is_default=False,
                )
            )

    # ==========================================================================
    # FORENSIC PRIORITY SHAPING: Adjust priorities based on forensic verdict
    # ==========================================================================
    # When forensic evidence indicates problems (REJECT verdict, reward_hacking_flags,
    # critical discrepancies), we shape candidate priorities to discourage blind
    # advancement and encourage retry or human escalation.
    #
    # Priority adjustments:
    # - ADVANCE candidates: demoted by 30-40 points (don't blindly proceed)
    # - REPEAT candidates: promoted by 20 points (give another chance)
    # - ESCALATE candidates: promoted by 30 points (human review may be needed)
    #
    # This implements "forensics over narrative" - actual evidence trumps claims.
    if forensic_verdict is not None:
        forensic_problems_detected = _detect_forensic_problems(forensic_verdict)

        if forensic_problems_detected:
            # Build evidence pointers from forensic verdict for transparency
            forensic_evidence = _build_forensic_evidence_pointers(forensic_verdict)

            logger.info(
                "Forensic priority shaping: problems detected (recommendation=%s, flags=%d, critical=%d)",
                forensic_verdict.get("recommendation", "unknown"),
                len(forensic_verdict.get("reward_hacking_flags", [])),
                _count_critical_discrepancies(forensic_verdict),
            )

            for candidate in candidates:
                if candidate.action == "advance":
                    # Demote ADVANCE candidates: don't blindly proceed when evidence is bad
                    # Stronger demotion for REJECT verdict (40 points) vs VERIFY (30 points)
                    demotion = 40 if forensic_verdict.get("recommendation") == "REJECT" else 30
                    candidate.priority = max(0, candidate.priority - demotion)
                    candidate.evidence_pointers = (candidate.evidence_pointers or []) + forensic_evidence
                    logger.debug(
                        "Forensic shaping: demoted %s by %d points (new priority=%d)",
                        candidate.candidate_id,
                        demotion,
                        candidate.priority,
                    )

                elif candidate.action == "repeat":
                    # Promote REPEAT candidates: give the step another chance to fix issues
                    candidate.priority += 20
                    candidate.evidence_pointers = (candidate.evidence_pointers or []) + forensic_evidence
                    logger.debug(
                        "Forensic shaping: promoted %s by 20 points (new priority=%d)",
                        candidate.candidate_id,
                        candidate.priority,
                    )

                elif candidate.action == "escalate":
                    # Promote ESCALATE candidates: human review is valuable when evidence is suspect
                    candidate.priority += 30
                    candidate.evidence_pointers = (candidate.evidence_pointers or []) + forensic_evidence
                    logger.debug(
                        "Forensic shaping: promoted %s by 30 points (new priority=%d)",
                        candidate.candidate_id,
                        candidate.priority,
                    )

    # Sort by priority (highest first)
    candidates.sort(key=lambda c: c.priority, reverse=True)

    # Mark the highest priority as default if none explicitly set
    if candidates and not any(c.is_default for c in candidates):
        candidates[0].is_default = True

    return candidates


__all__ = [
    # Routing signal creation
    "create_routing_signal",
    "route_step",
    "build_routing_context",
    "ReceiptReader",
    # Elephant Protocol: Stall detection types
    "ProgressDelta",
    "ProgressEvidence",
    "StallAnalysis",
    # Elephant Protocol: Stall detection functions
    "detect_stall",
    "record_progress_evidence",
    "create_stall_routing_signal",
    "compute_error_signature",
    # Candidate-set pattern
    "generate_routing_candidates",
]
