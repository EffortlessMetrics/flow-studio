"""
navigator_integration.py - Wire Navigator into orchestrator loop

This module provides integration functions that bridge the Navigator
with the existing orchestrator infrastructure. It handles:

1. Building NavigatorInput from step execution results
2. Applying NavigatorOutput to RunState (including detours)
3. Converting Navigator decisions to routing signals
4. Storing Navigator artifacts (briefs, audit trails)

The integration follows the principle: traditional tooling does heavy
lifting, Navigator makes smart decisions, kernel enforces constraints.

Usage:
    from swarm.runtime.navigator_integration import (
        build_navigation_context,
        apply_navigator_decision,
        NavigationOrchestrator,
    )

    # After step execution and verification
    nav_context = build_navigation_context(
        step_result=step_result,
        verification_result=verification_result,
        flow_graph=flow_graph,
        run_state=run_state,
        context_pack=context_pack,
    )

    nav_output = navigator.navigate(nav_context)
    next_step = apply_navigator_decision(nav_output, run_state, flow_graph)
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

# Import MAX_DETOUR_DEPTH from orchestrator
from swarm.runtime.stepwise.orchestrator import MAX_DETOUR_DEPTH

from .navigator import (
    DetourRequest,
    FileChangesSummary,
    Navigator,
    NavigatorInput,
    NavigatorOutput,
    NextStepBrief,
    ProgressTracker,
    ProposedEdge,
    RouteIntent,
    RouteProposal,
    StallSignals,
    UtilityFlowRequest,
    VerificationSummary,
    extract_candidate_edges_from_graph,
    navigator_output_to_dict,
)
from .router import FlowGraph
from .sidequest_catalog import (
    SidequestCatalog,
    load_default_catalog,
)
from .spec_evolution import persist_routing_proposal
from .station_library import StationLibrary, load_station_library
from .types import (
    HandoffEnvelope,
    InjectedNodeSpec,
    RoutingCandidate,
    RoutingDecision,
    RoutingSignal,
    RunEvent,
    RunState,
    handoff_envelope_to_dict,
)

# Forensic comparator imports for Semantic Handoff Injection
from .forensic_comparator import (
    compare_claim_vs_evidence,
    forensic_verdict_to_dict,
)
from .forensic_types import (
    DiffScanResult,
    diff_scan_result_from_dict,
)
# Utility flow injection imports for INJECT_FLOW handling
from .utility_flow_injection import (
    UtilityFlowRegistry,
    UtilityFlowInjector,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Detour Depth Utilities
# =============================================================================


def get_current_detour_depth(run_state: RunState) -> int:
    """Get the current detour nesting depth from run state.

    This is a convenience wrapper around run_state.get_interruption_depth()
    that provides a semantic name for the detour depth concept.

    Args:
        run_state: The current run state with interruption stack.

    Returns:
        The number of nested detours currently active (0 if none).
    """
    return run_state.get_interruption_depth()


# =============================================================================
# No-Human-Mid-Flow Policy: PAUSE → DETOUR Rewriting
# =============================================================================


def rewrite_pause_to_detour(
    nav_output: NavigatorOutput,
    sidequest_catalog: SidequestCatalog,
) -> NavigatorOutput:
    """Rewrite PAUSE intent to DETOUR for no-human-mid-flow policy.

    When autopilot mode is enabled (no_human_mid_flow=True), the run
    should never block on a human. Instead of pausing, PAUSE intents
    are rewritten to trigger the clarifier sidequest, which:

    1. Loads context (ADR, specs, requirements)
    2. Attempts to answer the blocking question using existing context
    3. Documents assumptions if the answer cannot be found definitively
    4. Never blocks - continues with best interpretation

    Args:
        nav_output: Navigator output with PAUSE intent.
        sidequest_catalog: Catalog to look up the clarifier sidequest.

    Returns:
        Modified NavigatorOutput with DETOUR intent targeting clarifier,
        or the original nav_output if PAUSE cannot be rewritten.
    """
    if nav_output.route.intent != RouteIntent.PAUSE:
        return nav_output

    # Get clarifier sidequest
    clarifier = sidequest_catalog.get_by_id("clarifier")
    if clarifier is None:
        logger.warning(
            "No clarifier sidequest found in catalog, cannot rewrite PAUSE to DETOUR. "
            "The run will block on human input."
        )
        return nav_output

    # Deep copy to avoid mutating the original
    from copy import deepcopy

    rewritten = deepcopy(nav_output)

    # Rewrite intent to DETOUR
    rewritten.route.intent = RouteIntent.DETOUR
    original_reason = nav_output.route.reasoning
    rewritten.route.reasoning = f"Auto-clarify (no_human_mid_flow): {original_reason}"

    # Create detour request for clarifier sidequest
    rewritten.detour_request = DetourRequest(
        sidequest_id="clarifier",
        objective=f"Clarify: {original_reason}",
        priority=80,  # High priority - clarification is blocking
    )

    # Clear needs_human since we're handling it via sidequest
    rewritten.signals.needs_human = False

    logger.info(
        "Rewrote PAUSE → DETOUR (clarifier) for no_human_mid_flow policy: %s",
        original_reason,
    )

    return rewritten


# =============================================================================
# Context Building (Traditional Tooling → Navigator Input)
# =============================================================================


def extract_verification_summary(
    verification_result: Optional[Dict[str, Any]],
) -> Optional[VerificationSummary]:
    """Extract VerificationSummary from verification result.

    Converts raw verification output to compact Navigator input.
    """
    if verification_result is None:
        return None

    checks = verification_result.get("checks", [])
    passed_checks = [c for c in checks if c.get("passed", True)]
    failed_checks = [c for c in checks if not c.get("passed", True)]

    failure_summary = ""
    if failed_checks:
        failure_msgs = [c.get("message", c.get("name", "unknown")) for c in failed_checks[:3]]
        failure_summary = "; ".join(failure_msgs)
        if len(failed_checks) > 3:
            failure_summary += f" (+{len(failed_checks) - 3} more)"

    return VerificationSummary(
        passed=verification_result.get("passed", True),
        checks_run=len(checks),
        checks_passed=len(passed_checks),
        checks_failed=len(failed_checks),
        failure_summary=failure_summary,
        artifacts_verified=verification_result.get("artifacts_verified", []),
        commands_run=verification_result.get("commands_run", []),
    )


def extract_file_changes_summary(
    file_changes: Optional[Dict[str, Any]],
) -> Optional[FileChangesSummary]:
    """Extract FileChangesSummary from file changes data.

    Converts raw diff/file mutation data to compact Navigator input.
    """
    if file_changes is None:
        return None

    # Extract from various possible formats
    modified = file_changes.get("modified", [])
    added = file_changes.get("added", [])
    deleted = file_changes.get("deleted", [])

    # Check for sensitive paths
    sensitive_patterns = ["auth", "security", "secret", "credential", "password", "key"]
    all_paths = modified + added + deleted
    sensitive_paths = []
    for path in all_paths:
        path_lower = path.lower()
        if any(pattern in path_lower for pattern in sensitive_patterns):
            sensitive_paths.append(path)

    # Compute change signature for stall detection
    import hashlib

    sig_input = "|".join(sorted(all_paths))
    change_signature = hashlib.sha256(sig_input.encode()).hexdigest()[:16]

    return FileChangesSummary(
        files_modified=len(modified),
        files_added=len(added),
        files_deleted=len(deleted),
        lines_added=file_changes.get("lines_added", 0),
        lines_removed=file_changes.get("lines_removed", 0),
        sensitive_paths_touched=sensitive_paths,
        change_signature=change_signature,
    )


def build_navigation_context(
    run_id: str,
    flow_key: str,
    current_node: str,
    iteration: int,
    flow_graph: FlowGraph,
    step_result: Dict[str, Any],
    verification_result: Optional[Dict[str, Any]],
    file_changes: Optional[Dict[str, Any]],
    stall_signals: Optional[StallSignals],
    context_digest: str,
    previous_envelope: Optional[HandoffEnvelope],
    sidequest_catalog: Optional[SidequestCatalog] = None,
    routing_candidates: Optional[List[Dict[str, Any]]] = None,
    forensic_verdict: Optional[Dict[str, Any]] = None,
) -> NavigatorInput:
    """Build NavigatorInput from step execution context.

    This function collects outputs from traditional tooling and
    packages them for the Navigator.

    Args:
        run_id: Run identifier.
        flow_key: Flow key.
        current_node: Current node/step ID.
        iteration: Current iteration count.
        flow_graph: The flow graph for edge candidates.
        step_result: Step execution result.
        verification_result: Verification check results.
        file_changes: File changes from diff scanner.
        stall_signals: Stall detection signals.
        context_digest: Compressed context summary.
        previous_envelope: Previous step's handoff envelope.
        sidequest_catalog: Catalog to look up sidequests.
        routing_candidates: Pre-computed routing candidates from kernel.
        forensic_verdict: ForensicVerdict comparing claims vs evidence
            (Semantic Handoff Injection). See forensic_comparator.py.
    """
    # Extract candidate edges from graph
    candidate_edges = extract_candidate_edges_from_graph(flow_graph, current_node)

    # Build context for sidequest trigger evaluation
    trigger_context = {
        "verification_passed": verification_result.get("passed", True)
        if verification_result
        else True,
        "stall_signals": {
            "is_stalled": stall_signals.is_stalled if stall_signals else False,
            "stall_count": stall_signals.stall_count if stall_signals else 0,
            "same_failure_signature": stall_signals.same_failure_signature
            if stall_signals
            else False,
        }
        if stall_signals
        else {},
        "changed_paths": (
            file_changes.get("modified", [])
            + file_changes.get("added", [])
            + file_changes.get("deleted", [])
        )
        if file_changes
        else [],
        "iteration": iteration,
    }

    # Get applicable sidequests
    sidequest_options = []
    if sidequest_catalog:
        applicable = sidequest_catalog.get_applicable_sidequests(trigger_context, run_id)
        from .navigator import SidequestOption

        sidequest_options = [
            SidequestOption(
                sidequest_id=sq.sidequest_id,
                station_template=sq.station_id,
                trigger_description=sq.description,
                objective_template=sq.objective_template,
                priority=sq.priority,
                cost_hint=sq.cost_hint,
            )
            for sq in applicable
        ]

    return NavigatorInput(
        run_id=run_id,
        flow_key=flow_key,
        current_node=current_node,
        iteration=iteration,
        candidate_edges=candidate_edges,
        sidequest_options=sidequest_options,
        verification=extract_verification_summary(verification_result),
        file_changes=extract_file_changes_summary(file_changes),
        stall_signals=stall_signals,
        context_digest=context_digest,
        previous_step_summary=previous_envelope.summary if previous_envelope else "",
        previous_step_status=step_result.get("status", ""),
        worker_suggested_route=step_result.get("next_step_id"),
        routing_candidates=routing_candidates or [],
        forensic_verdict=forensic_verdict,
    )


# =============================================================================
# Decision Application (Navigator Output → RunState)
# =============================================================================


def navigator_to_routing_signal(
    nav_output: NavigatorOutput,
    routing_candidates: Optional[List[RoutingCandidate]] = None,
) -> RoutingSignal:
    """Convert NavigatorOutput to RoutingSignal.

    This bridges the Navigator's decision format with the existing
    routing infrastructure. Includes chosen_candidate_id from the
    candidate-set pattern for full audit trail.

    Args:
        nav_output: The Navigator's output decision.
        routing_candidates: Optional list of candidates that were presented to Navigator.
            If not provided, a single candidate representing the chosen route is created.
    """
    intent = nav_output.route.intent
    target_node = nav_output.route.target_node
    reasoning = nav_output.route.reasoning
    chosen_candidate_id = nav_output.chosen_candidate_id

    # If no candidates provided, create one representing the chosen route
    if routing_candidates is None:
        # Generate a candidate_id if none provided by Navigator
        if not chosen_candidate_id:
            if intent == RouteIntent.TERMINATE:
                chosen_candidate_id = "terminate"
            elif intent == RouteIntent.LOOP:
                chosen_candidate_id = f"loop:{target_node}"
            elif intent == RouteIntent.PAUSE:
                chosen_candidate_id = "pause"
            elif intent == RouteIntent.DETOUR:
                chosen_candidate_id = f"detour:{target_node}"
            else:  # ADVANCE
                chosen_candidate_id = f"advance:{target_node}"

        # Create the implicit candidate
        routing_candidates = [
            RoutingCandidate(
                candidate_id=chosen_candidate_id,
                action=intent.value if intent != RouteIntent.PAUSE else "terminate",
                target_node=target_node,
                reason=reasoning,
                priority=90,  # Navigator decisions have high priority
                source="navigator",
                is_default=False,
            )
        ]

    # Common fields for all routing decisions
    common_fields = {
        "confidence": nav_output.route.confidence,
        "needs_human": nav_output.signals.needs_human,
        "chosen_candidate_id": chosen_candidate_id,
        "routing_candidates": routing_candidates,
        "routing_source": "navigator",
    }

    if intent == RouteIntent.TERMINATE:
        return RoutingSignal(
            decision=RoutingDecision.TERMINATE,
            next_step_id=None,
            reason=reasoning,
            exit_condition_met=True,
            **common_fields,
        )
    elif intent == RouteIntent.LOOP:
        return RoutingSignal(
            decision=RoutingDecision.LOOP,
            next_step_id=target_node,
            reason=reasoning,
            **common_fields,
        )
    elif intent == RouteIntent.PAUSE:
        return RoutingSignal(
            decision=RoutingDecision.TERMINATE,  # Pause = terminate with needs_human
            next_step_id=None,
            reason=reasoning,
            needs_human=True,  # Override common_fields
            chosen_candidate_id=chosen_candidate_id,
            routing_candidates=routing_candidates,
            routing_source="navigator",
            confidence=nav_output.route.confidence,
        )
    elif intent == RouteIntent.DETOUR:
        # Detour is handled separately; return advance to current position
        return RoutingSignal(
            decision=RoutingDecision.ADVANCE,
            next_step_id=target_node,
            reason=f"Detour requested: {reasoning}",
            **common_fields,
        )
    else:  # ADVANCE
        return RoutingSignal(
            decision=RoutingDecision.ADVANCE,
            next_step_id=target_node,
            reason=reasoning,
            **common_fields,
        )


def apply_detour_request(
    nav_output: NavigatorOutput,
    run_state: RunState,
    sidequest_catalog: SidequestCatalog,
    current_node: str,
) -> Optional[str]:
    """Apply a detour request to RunState.

    If Navigator requested a detour, this:
    1. Validates detour depth against MAX_DETOUR_DEPTH
    2. Pushes current position to resume stack
    3. Pushes interruption frame with multi-step tracking
    4. Injects node specs for ALL steps in the sidequest
    5. Returns the first sidequest station to execute

    For multi-step sidequests, nodes are injected as:
    - sq-<sidequest_id>-0
    - sq-<sidequest_id>-1
    - ... etc

    Each node has a full InjectedNodeSpec so the orchestrator
    can resolve it to an execution context.

    Args:
        nav_output: Navigator output with detour request.
        run_state: RunState to modify.
        sidequest_catalog: Catalog to look up sidequest details.
        current_node: Current node (for resume point).

    Returns:
        First node ID to execute for the detour, or None if:
        - No detour request in nav_output
        - Unknown sidequest ID
        - Maximum detour depth would be exceeded
    """
    if nav_output.detour_request is None:
        return None

    detour = nav_output.detour_request

    # Check detour depth BEFORE attempting to push interruption
    current_depth = get_current_detour_depth(run_state)
    if current_depth >= MAX_DETOUR_DEPTH:
        logger.warning(
            "MAX_DETOUR_DEPTH (%d) reached, rejecting detour request for sidequest '%s'. "
            "Current depth: %d. This prevents runaway nested sidequests. "
            "Consider increasing MAX_DETOUR_DEPTH if legitimate deep nesting is required.",
            MAX_DETOUR_DEPTH,
            detour.sidequest_id,
            current_depth,
        )
        return None

    sidequest = sidequest_catalog.get_by_id(detour.sidequest_id)

    if sidequest is None:
        logger.warning("Unknown sidequest requested: %s", detour.sidequest_id)
        return None

    # Get steps from sidequest (handles both single and multi-step)
    steps = sidequest.to_steps() if hasattr(sidequest, "to_steps") else []
    if not steps:
        # Fallback for simple sidequests
        steps = [type("Step", (), {"station_id": sidequest.station_id, "template_id": None})()]

    total_steps = len(steps)

    # Push resume point (where to continue after detour)
    resume_at = detour.resume_at or current_node
    run_state.push_resume(
        resume_at,
        {
            "detour_reason": detour.objective,
            "sidequest_id": detour.sidequest_id,
        },
    )

    # Push interruption frame with multi-step tracking
    run_state.push_interruption(
        reason=f"Sidequest: {sidequest.name} - {detour.objective}",
        return_node=resume_at,
        context_snapshot={
            "sidequest_id": detour.sidequest_id,
            "objective": detour.objective,
            "priority": detour.priority,
        },
        current_step_index=0,  # Starting at first step
        total_steps=total_steps,
        sidequest_id=detour.sidequest_id,
    )

    # Inject node specs for ALL steps in the sidequest
    first_node_id = None
    for i, step in enumerate(steps):
        node_id = f"sq-{detour.sidequest_id}-{i}"

        # Get station_id from step (handle different step formats)
        station_id = (
            getattr(step, "station_id", None)
            or getattr(step, "template_id", None)
            or sidequest.station_id
        )
        template_id = getattr(step, "template_id", None)

        # Create full execution spec for this node
        spec = InjectedNodeSpec(
            node_id=node_id,
            station_id=station_id,
            template_id=template_id,
            agent_key=station_id,  # Default to station_id as agent key
            role=f"Sidequest {detour.sidequest_id} step {i + 1}/{total_steps}",
            params={
                "objective": detour.objective,
                "step_index": i,
            },
            sidequest_origin=detour.sidequest_id,
            sequence_index=i,
            total_in_sequence=total_steps,
        )

        # Register the spec (this also adds to injected_nodes list)
        run_state.register_injected_node(spec)

        if i == 0:
            first_node_id = node_id

    # Record usage in catalog
    sidequest_catalog.record_usage(detour.sidequest_id, run_state.run_id)

    logger.info(
        "Detour injected: %s (%d steps, first=%s, resume_at=%s)",
        detour.sidequest_id,
        total_steps,
        first_node_id,
        resume_at,
    )

    return first_node_id


def check_and_handle_detour_completion(
    run_state: RunState,
    sidequest_catalog: Optional[SidequestCatalog] = None,
) -> Optional[str]:
    """Check if we should resume from a completed detour.

    If the interruption stack has frames and the current detour is
    complete, pop and return the resume node based on ReturnBehavior.

    For multi-step sidequests, this function tracks progress using
    the current_step_index field on InterruptionFrame. When a step
    completes:
    - If more steps remain: increment index and return next step's station
    - If all steps complete: pop frame and resume original flow

    Args:
        run_state: Current run state with interruption/resume stacks.
        sidequest_catalog: Optional catalog to look up return behavior.

    Returns:
        Resume node ID, or None if no resume needed.
    """
    if not run_state.is_interrupted():
        return None

    # Check if current sidequest is complete
    top_frame = run_state.peek_interruption()
    if top_frame is None:
        return None

    # Get sidequest info from frame fields (new durable cursor approach)
    # Fall back to context_snapshot for backwards compatibility with existing state
    sidequest_id = top_frame.sidequest_id
    if sidequest_id is None:
        sidequest_id = top_frame.context_snapshot.get("sidequest_id")
    current_step_index = top_frame.current_step_index
    # total_steps is available on top_frame but not needed for advance logic

    # Check if multi-step sidequest has more steps
    if sidequest_catalog and sidequest_id:
        sidequest = sidequest_catalog.get_by_id(sidequest_id)
        if sidequest and sidequest.is_multi_step:
            steps = sidequest.to_steps()
            if current_step_index < len(steps) - 1:
                # More steps remain - advance to next step
                next_step_index = current_step_index + 1

                # Use the injected node ID format
                next_node_id = f"sq-{sidequest_id}-{next_step_index}"

                # Update the frame's step index directly (durable cursor)
                top_frame.current_step_index = next_step_index

                logger.info(
                    "Multi-step sidequest %s advancing to step %d/%d: %s",
                    sidequest_id,
                    next_step_index + 1,
                    len(steps),
                    next_node_id,
                )
                return next_node_id

    # Sidequest is complete - apply return behavior
    resume_point = run_state.pop_resume()
    run_state.pop_interruption()

    # Determine return node based on return_behavior
    if sidequest_catalog and sidequest_id:
        sidequest = sidequest_catalog.get_by_id(sidequest_id)
        if sidequest:
            return_behavior = sidequest.return_behavior

            if return_behavior.mode == "bounce_to" and return_behavior.target_node:
                logger.info(
                    "Sidequest %s bouncing to: %s",
                    sidequest_id,
                    return_behavior.target_node,
                )
                return return_behavior.target_node

            elif return_behavior.mode == "halt":
                logger.info("Sidequest %s halting flow", sidequest_id)
                return None

            elif return_behavior.mode == "conditional" and return_behavior.condition:
                # TODO: Evaluate CEL condition against current context
                # For now, fall back to resume
                logger.debug("Conditional return not yet implemented, resuming")

    # Default: resume mode
    if resume_point:
        logger.info("Resuming from detour to node: %s", resume_point.node_id)
        return resume_point.node_id

    return top_frame.return_node


def apply_extend_graph_request(
    nav_output: NavigatorOutput,
    run_state: RunState,
    current_node: str,
    station_library: Optional[List[str]] = None,
) -> Optional[str]:
    """Apply an EXTEND_GRAPH request from Navigator.

    When Navigator encounters a map gap (needs a transition not in the graph),
    this function:
    1. Validates the target exists in the station/template library
    2. Creates a run-local injected node
    3. Pushes resume point
    4. Returns the station to execute

    Args:
        nav_output: Navigator output with proposed_edge.
        run_state: RunState to modify.
        current_node: Current node (for resume point).
        station_library: Optional list of valid station/template IDs.

    Returns:
        Station/template ID to execute, or None if request is invalid.
    """
    if nav_output.proposed_edge is None:
        return None

    proposed = nav_output.proposed_edge
    target_id = proposed.to_node

    # If proposed_node has explicit target, use that
    if proposed.proposed_node:
        explicit_target = proposed.proposed_node.get_target_id()
        if explicit_target:
            target_id = explicit_target

    if not target_id:
        logger.warning("EXTEND_GRAPH request has no target")
        return None

    # Validate target exists in library (if library provided)
    if station_library and target_id not in station_library:
        logger.warning(
            "EXTEND_GRAPH target %s not in station library, rejecting",
            target_id,
        )
        return None

    # Generate injected node ID
    injected_node_id = f"inj-{target_id}-{run_state.step_index}"

    # Push resume point if this is a return edge
    if proposed.is_return:
        run_state.push_resume(
            current_node,
            {
                "extend_graph_reason": proposed.why,
                "injected_node_id": injected_node_id,
            },
        )

        # Push interruption frame for map gap
        run_state.push_interruption(
            reason=f"Map gap: {proposed.why}",
            return_node=current_node,
            context_snapshot={
                "injected_node_id": injected_node_id,
                "proposed_edge": {
                    "from_node": proposed.from_node,
                    "to_node": target_id,
                    "edge_type": proposed.edge_type,
                    "priority": proposed.priority,
                },
                "objective": proposed.proposed_node.objective if proposed.proposed_node else "",
            },
        )

    # Add to injected nodes
    run_state.add_injected_node(injected_node_id)

    logger.info(
        "EXTEND_GRAPH: Injected node %s (target=%s, resume=%s)",
        injected_node_id,
        target_id,
        proposed.is_return,
    )

    return target_id


def emit_graph_patch_suggested_event(
    run_id: str,
    flow_key: str,
    step_id: str,
    proposed_edge: ProposedEdge,
    append_event_fn: Optional[Callable] = None,
) -> None:
    """Emit a graph_patch_suggested event for UI patch workflow.

    When Navigator proposes a map gap via EXTEND_GRAPH, this event
    allows the UI to show the suggestion and optionally apply it
    to the flow spec.

    Args:
        run_id: Run identifier.
        flow_key: Flow key.
        step_id: Step that triggered the suggestion.
        proposed_edge: The proposed edge/node.
        append_event_fn: Function to append events (for testing).
    """
    if append_event_fn is None:
        from . import storage as storage_module

        append_event_fn = storage_module.append_event

    patch_payload = {
        "op": "add",
        "path": "/edges/-",
        "value": {
            "edge_id": f"suggested-{proposed_edge.from_node}-{proposed_edge.to_node}",
            "from": proposed_edge.from_node,
            "to": proposed_edge.to_node,
            "type": proposed_edge.edge_type,
            "priority": proposed_edge.priority,
        },
    }

    if proposed_edge.proposed_node:
        # Also suggest adding the node
        node_patch = {
            "op": "add",
            "path": "/nodes/-",
            "value": {
                "node_id": proposed_edge.proposed_node.node_id
                or f"suggested-{proposed_edge.to_node}",
                "template_id": proposed_edge.proposed_node.template_id or proposed_edge.to_node,
                "station_id": proposed_edge.proposed_node.station_id,
            },
        }
        patch_payload = [node_patch, patch_payload]

    event = RunEvent(
        run_id=run_id,
        ts=datetime.now(timezone.utc),
        kind="graph_patch_suggested",
        flow_key=flow_key,
        step_id=step_id,
        payload={
            "reason": proposed_edge.why,
            "patch": patch_payload,
            "is_return": proposed_edge.is_return,
            "injected_for_run": True,
        },
    )

    append_event_fn(run_id, event)


# =============================================================================
# Utility Flow Injection (INJECT_FLOW)
# =============================================================================


@dataclass
class UtilityFlowInjectionResult:
    """Result of utility flow injection.

    Attributes:
        flow_id: The injected utility flow ID.
        first_node_id: The first node to execute in the utility flow.
    """

    flow_id: str
    first_node_id: str


def apply_utility_flow_injection(
    nav_output: NavigatorOutput,
    run_state: "RunState",
    run_id: str,
    flow_key: str,
    step_id: str,
    repo_root: Path,
    append_event_fn: Optional[Callable] = None,
) -> Optional[UtilityFlowInjectionResult]:
    """Apply utility flow injection if Navigator chose INJECT_FLOW.

    When Navigator selects a utility flow (e.g., reset when diverged), this
    function uses the stack-frame pattern to inject the utility flow. The
    current flow is interrupted and will resume after the utility flow
    completes.

    This is similar to apply_detour_request but for whole flows rather
    than single-step sidequests.

    Args:
        nav_output: Navigator output with utility_flow_request.
        run_state: Current run state (will be mutated to push flow stack).
        run_id: Run identifier.
        flow_key: Current flow key.
        step_id: Step that triggered injection.
        repo_root: Repository root path.
        append_event_fn: Function to append events (for testing).

    Returns:
        UtilityFlowInjectionResult with flow_id and first_node_id if injection
        occurred, None otherwise.
    """
    if nav_output.utility_flow_request is None:
        return None

    request = nav_output.utility_flow_request

    if append_event_fn is None:
        from . import storage as storage_module

        append_event_fn = storage_module.append_event

    # Use the injector from utility_flow_injection module
    registry = UtilityFlowRegistry(repo_root)
    injector = UtilityFlowInjector(registry)

    # Perform the injection
    result = injector.inject_utility_flow(
        flow_id=request.flow_id,
        run_state=run_state,
        current_node=step_id,
        injection_reason=request.reason,
    )

    if not result.injected:
        logger.warning(
            "Utility flow injection failed: flow_id=%s, reason=%s",
            request.flow_id,
            result.error,
        )
        return None

    # Emit utility_flow_injected event for audit trail
    event = RunEvent(
        run_id=run_id,
        ts=datetime.now(timezone.utc),
        kind="utility_flow_injected",
        flow_key=flow_key,
        step_id=step_id,
        payload={
            "utility_flow_id": request.flow_id,
            "reason": request.reason,
            "priority": request.priority,
            "resume_at": request.resume_at or step_id,
            "pass_artifacts": request.pass_artifacts,
            "interruption_depth": run_state.get_interruption_depth(),
        },
    )
    append_event_fn(run_id, event)

    logger.info(
        "INJECT_FLOW: Injected utility flow %s (reason: %s, resume_at: %s, first_node: %s)",
        request.flow_id,
        request.reason,
        request.resume_at or step_id,
        result.first_node_id,
    )

    return UtilityFlowInjectionResult(
        flow_id=request.flow_id,
        first_node_id=result.first_node_id,
    )


# =============================================================================
# Brief Storage
# =============================================================================


def store_next_step_brief(
    run_id: str,
    flow_key: str,
    step_id: str,
    brief: NextStepBrief,
    repo_root: Path,
) -> str:
    """Store NextStepBrief as an artifact.

    The brief is stored so the next step can read it as part of
    its context pack.

    Returns:
        Path to the stored brief file.
    """
    run_base = repo_root / "swarm" / "runs" / run_id
    brief_dir = run_base / flow_key / "nav"
    brief_dir.mkdir(parents=True, exist_ok=True)

    brief_file = brief_dir / f"{step_id}-brief.json"
    brief_data = {
        "objective": brief.objective,
        "focus_areas": brief.focus_areas,
        "context_pointers": brief.context_pointers,
        "warnings": brief.warnings,
        "constraints": brief.constraints,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    with open(brief_file, "w") as f:
        json.dump(brief_data, f, indent=2)

    return str(brief_file)


def load_next_step_brief(
    run_id: str,
    flow_key: str,
    step_id: str,
    repo_root: Path,
) -> Optional[NextStepBrief]:
    """Load NextStepBrief from artifact.

    Returns:
        The brief if found, None otherwise.
    """
    run_base = repo_root / "swarm" / "runs" / run_id
    brief_file = run_base / flow_key / "nav" / f"{step_id}-brief.json"

    if not brief_file.exists():
        return None

    try:
        with open(brief_file, "r") as f:
            data = json.load(f)

        return NextStepBrief(
            objective=data.get("objective", ""),
            focus_areas=data.get("focus_areas", []),
            context_pointers=data.get("context_pointers", []),
            warnings=data.get("warnings", []),
            constraints=data.get("constraints", []),
        )
    except Exception as e:
        logger.warning("Failed to load brief from %s: %s", brief_file, e)
        return None


# =============================================================================
# Navigation Orchestrator (High-Level Integration)
# =============================================================================


@dataclass
class NavigationResult:
    """Result of navigation decision."""

    next_node: Optional[str]
    routing_signal: RoutingSignal
    brief_stored: bool
    detour_injected: bool
    nav_output: NavigatorOutput
    extend_graph_injected: bool = False
    utility_flow_injected: bool = False
    utility_flow_id: Optional[str] = None


class NavigationOrchestrator:
    """High-level orchestrator for navigation decisions.

    This class encapsulates the full navigation flow:
    1. Build context from traditional tooling outputs
    2. Call Navigator for intelligent decision
    3. Apply decision to RunState
    4. Return routing result

    Usage:
        nav_orch = NavigationOrchestrator(repo_root=repo_root)

        result = nav_orch.navigate(
            run_id=run_id,
            flow_key=flow_key,
            current_node=current_node,
            flow_graph=flow_graph,
            step_result=step_result,
            verification_result=verification_result,
            run_state=run_state,
        )

        next_step = result.next_node
        routing_signal = result.routing_signal
    """

    def __init__(
        self,
        repo_root: Optional[Path] = None,
        navigator: Optional[Navigator] = None,
        sidequest_catalog: Optional[SidequestCatalog] = None,
        progress_tracker: Optional[ProgressTracker] = None,
        station_library: Optional[StationLibrary] = None,
    ):
        """Initialize NavigationOrchestrator.

        Args:
            repo_root: Repository root path.
            navigator: Navigator instance. If None, uses deterministic fallback.
            sidequest_catalog: Sidequest catalog. If None, uses default.
            progress_tracker: Progress tracker. If None, creates new one.
            station_library: Station library for EXTEND_GRAPH validation.
                If None, loads default + repo pack.
        """
        self._repo_root = repo_root or Path.cwd()
        self._navigator = navigator or Navigator()
        self._sidequest_catalog = sidequest_catalog or load_default_catalog()
        self._progress_tracker = progress_tracker or ProgressTracker()
        self._station_library = station_library or load_station_library(self._repo_root)

    def navigate(
        self,
        run_id: str,
        flow_key: str,
        current_node: str,
        iteration: int,
        flow_graph: FlowGraph,
        step_result: Dict[str, Any],
        verification_result: Optional[Dict[str, Any]],
        file_changes: Optional[Dict[str, Any]],
        run_state: RunState,
        context_digest: str = "",
        previous_envelope: Optional[HandoffEnvelope] = None,
        no_human_mid_flow: bool = False,
        routing_candidates: Optional[List[Dict[str, Any]]] = None,
    ) -> NavigationResult:
        """Execute navigation decision.

        Args:
            run_id: Run identifier.
            flow_key: Flow key.
            current_node: Current node/step ID.
            iteration: Current iteration count.
            flow_graph: The flow graph for edge candidates.
            step_result: Step execution result.
            verification_result: Verification check results.
            file_changes: File changes from diff scanner.
            run_state: Current run state.
            context_digest: Compressed context summary.
            previous_envelope: Previous step's handoff envelope.
            no_human_mid_flow: If True, rewrite PAUSE intents to DETOUR
                targeting the clarifier sidequest. This enables fully
                autonomous flow execution without human intervention.
            routing_candidates: Pre-computed routing candidates from the kernel.
                Navigator chooses from these via chosen_candidate_id.
                Each dict has: candidate_id, action, target_node, reason, priority.

        Returns:
            NavigationResult with routing decision and artifacts.
        """
        # Check if resuming from a completed detour
        resume_node = check_and_handle_detour_completion(run_state, self._sidequest_catalog)
        if resume_node:
            # Create audit trail for detour resume
            candidate_id = f"detour_resume:{resume_node}"
            chosen_candidate = RoutingCandidate(
                candidate_id=candidate_id,
                action="advance",
                target_node=resume_node,
                reason="Resuming from completed detour",
                priority=100,  # Detour resume is deterministic
                source="detour_resume",
                is_default=True,
            )

            # Return resume routing
            return NavigationResult(
                next_node=resume_node,
                routing_signal=RoutingSignal(
                    decision=RoutingDecision.ADVANCE,
                    next_step_id=resume_node,
                    reason="Resuming from completed detour",
                    confidence=1.0,
                    chosen_candidate_id=candidate_id,
                    routing_candidates=[chosen_candidate],
                    routing_source="detour_resume",
                ),
                brief_stored=False,
                detour_injected=False,
                nav_output=NavigatorOutput(
                    route=RouteProposal(
                        intent=RouteIntent.ADVANCE,
                        target_node=resume_node,
                        reasoning="Resume from detour",
                    ),
                    next_step_brief=NextStepBrief(objective="Continue after detour"),
                ),
            )

        # Record iteration for stall detection
        stall_signals = self._progress_tracker.record_iteration(
            node_id=current_node,
            file_changes=extract_file_changes_summary(file_changes),
            verification=extract_verification_summary(verification_result),
            step_output=step_result,
        )

        # =================================================================
        # SEMANTIC HANDOFF INJECTION: Compute forensic verdict
        # =================================================================
        # Compare worker claims (in handoff envelope) against actual evidence
        # (diff scan, test results). This enables Navigator to detect
        # "reward hacking" - e.g., deleted tests, fake progress claims.
        forensic_verdict = None
        if previous_envelope is not None:
            try:
                # Convert handoff envelope to dict for comparison
                handoff_dict = handoff_envelope_to_dict(previous_envelope)

                # Convert file_changes dict to DiffScanResult if available
                diff_result = None
                if file_changes:
                    try:
                        diff_result = diff_scan_result_from_dict(file_changes)
                    except Exception as e:
                        logger.debug(
                            "Could not convert file_changes to DiffScanResult: %s",
                            e,
                        )

                # Compute forensic verdict comparing claims vs evidence
                verdict = compare_claim_vs_evidence(
                    handoff=handoff_dict,
                    diff_result=diff_result,
                    test_summary=None,  # TODO: wire in test_summary when available
                )

                # Convert to dict for NavigatorInput
                forensic_verdict = forensic_verdict_to_dict(verdict)

                logger.debug(
                    "Forensic verdict for step %s: recommendation=%s, confidence=%.2f, flags=%s",
                    current_node,
                    verdict.recommendation.value,
                    verdict.confidence,
                    [f.value for f in verdict.reward_hacking_flags],
                )

            except Exception as e:
                logger.warning(
                    "Failed to compute forensic verdict for step %s: %s",
                    current_node,
                    e,
                )

        # Build navigation context
        nav_input = build_navigation_context(
            run_id=run_id,
            flow_key=flow_key,
            current_node=current_node,
            iteration=iteration,
            flow_graph=flow_graph,
            step_result=step_result,
            verification_result=verification_result,
            file_changes=file_changes,
            stall_signals=stall_signals,
            context_digest=context_digest,
            previous_envelope=previous_envelope,
            sidequest_catalog=self._sidequest_catalog,
            routing_candidates=routing_candidates,
            forensic_verdict=forensic_verdict,
        )

        # Run Navigator
        nav_output = self._navigator.navigate(nav_input)

        # =================================================================
        # CANDIDATE VALIDATION: Verify chosen_candidate_id is valid
        # =================================================================
        # If routing candidates were provided, Navigator must choose one.
        # EXTEND_GRAPH intent is exempt (it's proposing something new).
        if routing_candidates and nav_output.chosen_candidate_id:
            valid_ids = {c["candidate_id"] for c in routing_candidates}
            chosen_id = nav_output.chosen_candidate_id

            if chosen_id not in valid_ids:
                # Allow "extend_graph" as a special value for EXTEND_GRAPH intent
                # EXTEND_GRAPH is special: Navigator is proposing something NEW that
                # doesn't exist in the candidate set (that's the whole point).
                if nav_output.route.intent == RouteIntent.EXTEND_GRAPH:
                    logger.debug(
                        "Navigator chose EXTEND_GRAPH (not in candidate set): %s",
                        chosen_id,
                    )
                # INJECT_FLOW must now be in candidate set - utility flow candidates
                # are generated BEFORE Navigator sees them via route_via_navigator().
                # If we reach this branch, it's a bug - utility candidates weren't generated.
                elif nav_output.route.intent == RouteIntent.INJECT_FLOW:
                    logger.warning(
                        "Navigator chose INJECT_FLOW candidate '%s' but it was not in "
                        "the candidate set (valid: %s). This indicates utility flow "
                        "candidates weren't generated - check git_status/repo_root params. "
                        "Falling back to default candidate.",
                        chosen_id,
                        list(valid_ids),
                    )
                    # Fall back to the default candidate
                    default_candidate = next(
                        (c for c in routing_candidates if c.get("is_default")),
                        routing_candidates[0] if routing_candidates else None,
                    )
                    if default_candidate:
                        nav_output.chosen_candidate_id = default_candidate["candidate_id"]
                        nav_output.route.target_node = default_candidate.get("target_node")
                        nav_output.route.reasoning = (
                            f"Fallback to default (INJECT_FLOW candidate missing): "
                            f"{default_candidate.get('reason', '')}"
                        )
                else:
                    logger.warning(
                        "Navigator chose invalid candidate_id '%s' (valid: %s). "
                        "Falling back to default candidate.",
                        chosen_id,
                        list(valid_ids),
                    )
                    # Fall back to the default candidate
                    default_candidate = next(
                        (c for c in routing_candidates if c.get("is_default")),
                        routing_candidates[0] if routing_candidates else None,
                    )
                    if default_candidate:
                        nav_output.chosen_candidate_id = default_candidate["candidate_id"]
                        nav_output.route.target_node = default_candidate.get("target_node")
                        nav_output.route.reasoning = (
                            f"Fallback to default: {default_candidate.get('reason', '')}"
                        )

        # Apply no-human-mid-flow policy: rewrite PAUSE → DETOUR
        if no_human_mid_flow and nav_output.route.intent == RouteIntent.PAUSE:
            nav_output = rewrite_pause_to_detour(nav_output, self._sidequest_catalog)

        # Apply detour if requested
        detour_station = None
        detour_injected = False
        extend_graph_target = None
        extend_graph_injected = False

        if nav_output.route.intent == RouteIntent.DETOUR and nav_output.detour_request:
            detour_station = apply_detour_request(
                nav_output=nav_output,
                run_state=run_state,
                sidequest_catalog=self._sidequest_catalog,
                current_node=current_node,
            )
            if detour_station:
                detour_injected = True
                # Override next node to be the detour station
                nav_output.route.target_node = detour_station

        elif nav_output.route.intent == RouteIntent.EXTEND_GRAPH and nav_output.proposed_edge:
            # Handle map gap - Navigator is proposing an edge not in the graph
            extend_graph_target = apply_extend_graph_request(
                nav_output=nav_output,
                run_state=run_state,
                current_node=current_node,
                station_library=self._station_library.list_station_ids(),
            )
            if extend_graph_target:
                extend_graph_injected = True
                # Override next node to be the injected target
                nav_output.route.target_node = extend_graph_target

                # Emit graph_patch_suggested event for UI
                emit_graph_patch_suggested_event(
                    run_id=run_id,
                    flow_key=flow_key,
                    step_id=current_node,
                    proposed_edge=nav_output.proposed_edge,
                )

                # Persist proposal to disk for durable artifact
                if self._repo_root and run_id:
                    run_base = self._repo_root / "swarm" / "runs" / run_id
                    try:
                        proposal_path = persist_routing_proposal(
                            run_base=run_base,
                            flow_key=flow_key,
                            step_id=current_node,
                            proposed_edge=nav_output.proposed_edge,
                            why_now=getattr(nav_output.route, "why_now", None),
                            routing_reason=getattr(nav_output.route, "explanation", None) or "",
                        )
                        logger.info("EXTEND_GRAPH proposal persisted to %s", proposal_path)
                    except Exception as e:
                        logger.warning("Failed to persist EXTEND_GRAPH proposal: %s", e)

        # Handle utility flow injection (INJECT_FLOW)
        utility_flow_injected = False
        utility_flow_id = None

        if nav_output.route.intent == RouteIntent.INJECT_FLOW and nav_output.utility_flow_request:
            # Handle utility flow injection (e.g., reset when diverged)
            injection_result = apply_utility_flow_injection(
                nav_output=nav_output,
                run_state=run_state,
                run_id=run_id,
                flow_key=flow_key,
                step_id=current_node,
                repo_root=self._repo_root,
            )
            if injection_result:
                utility_flow_injected = True
                utility_flow_id = injection_result.flow_id
                # Set next node to the first step of the utility flow
                # This is deterministic - we don't leave target_node as None
                nav_output.route.target_node = injection_result.first_node_id
                logger.info(
                    "INJECT_FLOW: Switching to utility flow '%s' (first_node: %s), "
                    "current flow '%s' will resume later",
                    utility_flow_id,
                    injection_result.first_node_id,
                    flow_key,
                )

        # Convert to routing signal
        routing_signal = navigator_to_routing_signal(nav_output)

        # Store brief for next step
        brief_stored = False
        if nav_output.route.target_node and nav_output.next_step_brief:
            try:
                store_next_step_brief(
                    run_id=run_id,
                    flow_key=flow_key,
                    step_id=nav_output.route.target_node,
                    brief=nav_output.next_step_brief,
                    repo_root=self._repo_root,
                )
                brief_stored = True
            except Exception as e:
                logger.warning("Failed to store brief: %s", e)

        # Reset stall tracker if verification passed
        if verification_result and verification_result.get("passed", False):
            self._progress_tracker.reset(current_node)

        return NavigationResult(
            next_node=nav_output.route.target_node,
            routing_signal=routing_signal,
            brief_stored=brief_stored,
            detour_injected=detour_injected,
            nav_output=nav_output,
            extend_graph_injected=extend_graph_injected,
            utility_flow_injected=utility_flow_injected,
            utility_flow_id=utility_flow_id,
        )

    @property
    def sidequest_catalog(self) -> SidequestCatalog:
        """Get the sidequest catalog for external use."""
        return self._sidequest_catalog

    @property
    def station_library(self) -> StationLibrary:
        """Get the station library for external use."""
        return self._station_library

    def validate_extend_graph_target(self, target_id: str) -> bool:
        """Validate that a target is valid for EXTEND_GRAPH.

        Args:
            target_id: The proposed target station/template ID.

        Returns:
            True if the target exists in the station library.
        """
        return self._station_library.validate_target(target_id)

    def reset(self, run_id: Optional[str] = None) -> None:
        """Reset state for a new run.

        Args:
            run_id: Run ID to reset. If None, resets all.
        """
        self._progress_tracker.clear_all()
        self._sidequest_catalog.reset_usage(run_id)


# =============================================================================
# Event Emission
# =============================================================================


def emit_navigation_event(
    run_id: str,
    flow_key: str,
    step_id: str,
    nav_output: NavigatorOutput,
    append_event_fn: Optional[Callable] = None,
) -> None:
    """Emit a navigation decision event.

    Args:
        run_id: Run identifier.
        flow_key: Flow key.
        step_id: Step that produced the navigation decision.
        nav_output: Navigator output.
        append_event_fn: Function to append events (for testing).
    """
    if append_event_fn is None:
        from . import storage as storage_module

        append_event_fn = storage_module.append_event

    event = RunEvent(
        run_id=run_id,
        ts=datetime.now(timezone.utc),
        kind="navigation_decision",
        flow_key=flow_key,
        step_id=step_id,
        payload=navigator_output_to_dict(nav_output),
    )

    append_event_fn(run_id, event)
