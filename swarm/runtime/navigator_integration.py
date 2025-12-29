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
from typing import Any, Callable, Dict, List, Optional, Tuple

from .navigator import (
    Navigator,
    NavigatorInput,
    NavigatorOutput,
    NextStepBrief,
    RouteIntent,
    RouteProposal,
    EdgeCandidate,
    VerificationSummary,
    FileChangesSummary,
    StallSignals,
    ProgressTracker,
    extract_candidate_edges_from_graph,
    navigator_output_to_dict,
)
from .sidequest_catalog import (
    SidequestCatalog,
    SidequestDefinition,
    load_default_catalog,
    sidequests_to_navigator_options,
)
from .types import (
    HandoffEnvelope,
    RunState,
    RoutingDecision,
    RoutingSignal,
    RunEvent,
)
from .router import FlowGraph

logger = logging.getLogger(__name__)


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
) -> NavigatorInput:
    """Build NavigatorInput from step execution context.

    This function collects outputs from traditional tooling and
    packages them for the Navigator.
    """
    # Extract candidate edges from graph
    candidate_edges = extract_candidate_edges_from_graph(flow_graph, current_node)

    # Build context for sidequest trigger evaluation
    trigger_context = {
        "verification_passed": verification_result.get("passed", True) if verification_result else True,
        "stall_signals": {
            "is_stalled": stall_signals.is_stalled if stall_signals else False,
            "stall_count": stall_signals.stall_count if stall_signals else 0,
            "same_failure_signature": stall_signals.same_failure_signature if stall_signals else False,
        } if stall_signals else {},
        "changed_paths": (
            file_changes.get("modified", []) +
            file_changes.get("added", []) +
            file_changes.get("deleted", [])
        ) if file_changes else [],
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
    )


# =============================================================================
# Decision Application (Navigator Output → RunState)
# =============================================================================


def navigator_to_routing_signal(
    nav_output: NavigatorOutput,
) -> RoutingSignal:
    """Convert NavigatorOutput to RoutingSignal.

    This bridges the Navigator's decision format with the existing
    routing infrastructure.
    """
    intent = nav_output.route.intent

    if intent == RouteIntent.TERMINATE:
        return RoutingSignal(
            decision=RoutingDecision.TERMINATE,
            next_step_id=None,
            reason=nav_output.route.reasoning,
            confidence=nav_output.route.confidence,
            needs_human=nav_output.signals.needs_human,
            exit_condition_met=True,
        )
    elif intent == RouteIntent.LOOP:
        return RoutingSignal(
            decision=RoutingDecision.LOOP,
            next_step_id=nav_output.route.target_node,
            reason=nav_output.route.reasoning,
            confidence=nav_output.route.confidence,
            needs_human=nav_output.signals.needs_human,
        )
    elif intent == RouteIntent.PAUSE:
        return RoutingSignal(
            decision=RoutingDecision.TERMINATE,  # Pause = terminate with needs_human
            next_step_id=None,
            reason=nav_output.route.reasoning,
            confidence=nav_output.route.confidence,
            needs_human=True,
        )
    elif intent == RouteIntent.DETOUR:
        # Detour is handled separately; return advance to current position
        return RoutingSignal(
            decision=RoutingDecision.ADVANCE,
            next_step_id=nav_output.route.target_node,
            reason=f"Detour requested: {nav_output.route.reasoning}",
            confidence=nav_output.route.confidence,
            needs_human=nav_output.signals.needs_human,
        )
    else:  # ADVANCE
        return RoutingSignal(
            decision=RoutingDecision.ADVANCE,
            next_step_id=nav_output.route.target_node,
            reason=nav_output.route.reasoning,
            confidence=nav_output.route.confidence,
            needs_human=nav_output.signals.needs_human,
        )


def apply_detour_request(
    nav_output: NavigatorOutput,
    run_state: RunState,
    sidequest_catalog: SidequestCatalog,
    current_node: str,
) -> Optional[str]:
    """Apply a detour request to RunState.

    If Navigator requested a detour, this:
    1. Pushes current position to resume stack
    2. Pushes interruption frame
    3. Returns the sidequest station to execute

    Args:
        nav_output: Navigator output with detour request.
        run_state: RunState to modify.
        sidequest_catalog: Catalog to look up sidequest details.
        current_node: Current node (for resume point).

    Returns:
        Station ID to execute for the detour, or None if no detour.
    """
    if nav_output.detour_request is None:
        return None

    detour = nav_output.detour_request
    sidequest = sidequest_catalog.get_by_id(detour.sidequest_id)

    if sidequest is None:
        logger.warning("Unknown sidequest requested: %s", detour.sidequest_id)
        return None

    # Push resume point (where to continue after detour)
    resume_at = detour.resume_at or current_node
    run_state.push_resume(resume_at, {
        "detour_reason": detour.objective,
        "sidequest_id": detour.sidequest_id,
    })

    # Push interruption frame
    run_state.push_interruption(
        reason=f"Sidequest: {sidequest.name} - {detour.objective}",
        return_node=resume_at,
        context_snapshot={
            "sidequest_id": detour.sidequest_id,
            "objective": detour.objective,
            "priority": detour.priority,
        },
    )

    # Add sidequest node to injected nodes
    sidequest_node_id = f"sidequest-{detour.sidequest_id}-{run_state.step_index}"
    run_state.add_injected_node(sidequest_node_id)

    # Record usage in catalog
    sidequest_catalog.record_usage(detour.sidequest_id, run_state.run_id)

    logger.info(
        "Detour injected: %s (station=%s, resume_at=%s)",
        detour.sidequest_id, sidequest.station_id, resume_at,
    )

    return sidequest.station_id


def check_and_handle_detour_completion(
    run_state: RunState,
) -> Optional[str]:
    """Check if we should resume from a completed detour.

    If the interruption stack has frames and the current detour is
    complete, pop and return the resume node.

    Returns:
        Resume node ID, or None if no resume needed.
    """
    if not run_state.is_interrupted():
        return None

    # Check if current sidequest is complete (marked in completed_nodes)
    top_frame = run_state.peek_interruption()
    if top_frame is None:
        return None

    # For now, assume we resume after one step
    # More sophisticated: check if sidequest produced expected outputs
    resume_point = run_state.pop_resume()
    run_state.pop_interruption()

    if resume_point:
        logger.info("Resuming from detour to node: %s", resume_point.node_id)
        return resume_point.node_id

    return top_frame.return_node


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
    ):
        """Initialize NavigationOrchestrator.

        Args:
            repo_root: Repository root path.
            navigator: Navigator instance. If None, uses deterministic fallback.
            sidequest_catalog: Sidequest catalog. If None, uses default.
            progress_tracker: Progress tracker. If None, creates new one.
        """
        self._repo_root = repo_root or Path.cwd()
        self._navigator = navigator or Navigator()
        self._sidequest_catalog = sidequest_catalog or load_default_catalog()
        self._progress_tracker = progress_tracker or ProgressTracker()

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

        Returns:
            NavigationResult with routing decision and artifacts.
        """
        # Check if resuming from a completed detour
        resume_node = check_and_handle_detour_completion(run_state)
        if resume_node:
            # Return resume routing
            return NavigationResult(
                next_node=resume_node,
                routing_signal=RoutingSignal(
                    decision=RoutingDecision.ADVANCE,
                    next_step_id=resume_node,
                    reason="Resuming from completed detour",
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
        )

        # Run Navigator
        nav_output = self._navigator.navigate(nav_input)

        # Apply detour if requested
        detour_station = None
        detour_injected = False
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
        )

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
