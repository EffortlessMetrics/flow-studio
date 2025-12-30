"""
orchestrator.py - Navigator-Mandatory Stepwise Orchestrator

This module provides the stepwise orchestrator that coordinates flow execution
with the Navigator as the ONLY source of truth for routing decisions. The
Python kernel is a "dumb executor" that interprets Navigator signals.

Routing Priority:
1. Fast-path heuristics (RETRY on PARTIAL, VERIFIED->advance, etc.)
2. Navigator-based routing (intelligent decisions via NavigationOrchestrator)
3. Envelope-first fallback (legacy path, only when Navigator explicitly disabled)

Key Design Principles:
- Navigator makes all intelligent routing decisions
- Fast-path handles obvious deterministic cases without LLM calls
- Python kernel enforces graph constraints and detour limits
- All routing decisions are logged for auditability

The orchestrator coordinates:
1. Run lifecycle (create/resume)
2. Step iteration loop with fast-path + Navigator routing
3. Detour/INJECT_FLOW handling via interruption stack
4. Event persistence for observability

The heavy lifting is done by:
- NavigationOrchestrator: Intelligent routing decisions
- spec_facade: Loading and caching specs
- routing: Fallback routing signals
- receipt_compat: Reading/writing receipt fields
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from swarm.config.flow_registry import (
    FlowDefinition,
    FlowRegistry,
    StepDefinition,
)
from swarm.runtime import storage as storage_module
from swarm.runtime.engines import StepContext, StepEngine

# A3: Envelope-first routing imports
from swarm.runtime.handoff_io import (
    read_routing_from_envelope,
    update_envelope_routing,
)

# Macro navigation imports (between-flow routing)
from swarm.runtime.macro_navigator import (
    MacroNavigator,
    extract_flow_result,
)
from swarm.runtime.router import Edge, FlowGraph, NodeConfig  # For Navigator integration
from swarm.runtime.routing_utils import parse_routing_decision

# Forensic comparator imports for candidate priority shaping
from swarm.runtime.forensic_comparator import (
    compare_claim_vs_evidence,
    forensic_verdict_to_dict,
)
from swarm.runtime.forensic_types import (
    diff_scan_result_from_dict,
)

from swarm.runtime.types import (
    FlowResult,
    InjectedNodeSpec,
    MacroAction,
    MacroRoutingDecision,
    RoutingCandidate,
    RoutingDecision,
    RoutingMode,
    RoutingSignal,
    RunEvent,
    RunId,
    RunPlanSpec,
    RunSpec,
    RunState,
    RunStatus,
    SDLCStatus,
    generate_run_id,
    handoff_envelope_to_dict,
)

# Modular stepwise components
from .engine_runner import emit_step_execution_events, run_step as run_step_via_engine
from .envelope import ensure_step_envelope
from .graph_bridge import build_flow_graph_from_definition
from .models import FlowExecutionResult, FlowStepwiseSummary, ResolvedNode
from .node_resolver import find_step_index, get_next_node_id, resolve_node
from .receipt_compat import read_receipt_field, update_receipt_routing
from .routing import (
    build_routing_context,
    create_routing_signal,
    generate_routing_candidates,
    RoutingOutcome,
)
from .spec_facade import SpecFacade

# Utility flow injection imports
from swarm.runtime.utility_flow_injection import (
    InjectionTriggerDetector,
    TriggerDetectionResult,
    UtilityFlowInjector,
    UtilityFlowRegistry,
)

if TYPE_CHECKING:
    from swarm.runtime.navigator_integration import NavigationOrchestrator
    from swarm.runtime.preflight import PreflightResult

logger = logging.getLogger(__name__)

# Maximum nested detour depth (prevents runaway sidequests)
MAX_DETOUR_DEPTH = 10


# Note: FlowStepwiseSummary, FlowExecutionResult, ResolvedNode are now imported from .models


class StepwiseOrchestrator:
    """Thin orchestrator for stepwise flow execution.

    This class coordinates step-by-step flow execution while delegating
    the actual work to focused modules. It provides:

    - Run creation and metadata persistence
    - Flow definition loading from flow_registry
    - Per-step context building and engine invocation
    - Event aggregation into run's events.jsonl

    Attributes:
        _engine: The StepEngine instance for executing steps.
        _repo_root: Root path of the repository.
        _spec_facade: Facade for loading FlowSpec/StationSpec.
    """

    def __init__(
        self,
        engine: StepEngine,
        repo_root: Optional[Path] = None,
        use_spec_bridge: bool = False,
        use_pack_specs: bool = False,
        navigation_orchestrator: Optional["NavigationOrchestrator"] = None,
        skip_preflight: bool = False,
        routing_mode: RoutingMode = RoutingMode.ASSIST,
    ):
        """Initialize the orchestrator.

        Navigator-Mandatory Design:
            The Navigator is the ONLY source of truth for routing decisions.
            Python kernel is a "dumb executor" that interprets Navigator signals.

            Routing modes control Navigator behavior:
            - DETERMINISTIC_ONLY: No LLM routing calls (CI, debugging)
            - ASSIST (default): Fast-path + Navigator for complex routing
            - AUTHORITATIVE: Navigator has more latitude for innovation

            Routing priority (in ASSIST/AUTHORITATIVE modes):
            1. Fast-path heuristics (RETRY on PARTIAL, VERIFIED->advance, etc.)
            2. Navigator-based routing (intelligent decisions via candidate-set)
            3. ESCALATE if Navigator unavailable and mode requires it

        Candidate-Set Pattern:
            Python generates routing candidates from the graph and context.
            Navigator intelligently chooses among candidates.
            Python validates the choice and executes.
            This keeps intelligence bounded while preserving graph constraints.

        Args:
            engine: StepEngine instance for executing steps.
            repo_root: Repository root path. Defaults to auto-detection.
            use_spec_bridge: If True, load flows from JSON specs (legacy path).
            use_pack_specs: If True, load flows from pack JSON specs (new path).
                Takes precedence over use_spec_bridge when enabled.
            navigation_orchestrator: NavigationOrchestrator for intelligent
                routing decisions. A default is created if not provided.
                Only set to a custom instance for testing or specialized routing.
            skip_preflight: If True, skip preflight environment checks.
                Useful for CI or when environment is known to be valid.
            routing_mode: Controls Navigator behavior. Defaults to ASSIST.
                - DETERMINISTIC_ONLY: No LLM calls, fast-path only
                - ASSIST: Fast-path + Navigator chooses among candidates
                - AUTHORITATIVE: Navigator can propose EXTEND_GRAPH freely
        """
        self._engine = engine
        self._repo_root = repo_root or Path(__file__).resolve().parents[3]
        self._flow_registry = FlowRegistry.get_instance()
        self._use_spec_bridge = use_spec_bridge
        self._use_pack_specs = use_pack_specs
        self._spec_facade = SpecFacade(self._repo_root, use_pack_specs=use_pack_specs)
        self._lock = threading.Lock()
        self._skip_preflight = skip_preflight
        self._routing_mode = routing_mode

        # Navigation orchestrator for intelligent routing
        # Only create NavigationOrchestrator if routing mode requires it
        if routing_mode == RoutingMode.DETERMINISTIC_ONLY:
            # Deterministic mode - no Navigator, fast-path only
            self._navigation_orchestrator: Optional["NavigationOrchestrator"] = None
            logger.info("Orchestrator initialized in DETERMINISTIC_ONLY mode (no Navigator)")
        elif navigation_orchestrator is None:
            # Create default Navigator for ASSIST/AUTHORITATIVE modes
            from swarm.runtime.navigator_integration import NavigationOrchestrator

            self._navigation_orchestrator = NavigationOrchestrator(repo_root=self._repo_root)
            logger.info("Orchestrator initialized in %s mode with Navigator", routing_mode.value)
        else:
            self._navigation_orchestrator = navigation_orchestrator
            logger.info("Orchestrator initialized in %s mode with custom Navigator", routing_mode.value)

        # Stop request tracking for graceful interruption
        self._stop_requests: Dict[RunId, threading.Event] = {}

        # Utility flow injection components
        self._utility_flow_registry = UtilityFlowRegistry(self._repo_root)
        self._injection_detector = InjectionTriggerDetector(self._utility_flow_registry)
        self._utility_flow_injector = UtilityFlowInjector(self._utility_flow_registry)

    def request_stop(self, run_id: RunId) -> bool:
        """Request graceful stop of a running run.

        Args:
            run_id: The run to stop.

        Returns:
            True if stop was signaled, False if run not found.
        """
        with self._lock:
            if run_id not in self._stop_requests:
                self._stop_requests[run_id] = threading.Event()

        self._stop_requests[run_id].set()
        logger.info("Stop requested for run %s", run_id)
        return True

    def clear_stop_request(self, run_id: RunId) -> None:
        """Clear any pending stop request for a run."""
        if run_id in self._stop_requests:
            self._stop_requests[run_id].clear()

    def _is_stop_requested(self, run_id: RunId) -> bool:
        """Check if stop has been requested for a run."""
        if run_id not in self._stop_requests:
            return False
        return self._stop_requests[run_id].is_set()

    def _load_flow_definition(self, flow_key: str) -> Optional[FlowDefinition]:
        """Load flow definition from appropriate source.

        If use_pack_specs is enabled, loads from pack JSON specs.
        Otherwise falls back to the YAML-based flow registry.

        Args:
            flow_key: The flow to load (e.g., "build", "signal").

        Returns:
            FlowDefinition if found, None otherwise.
        """
        # Try pack specs first if enabled
        if self._use_pack_specs:
            flow_def = self._spec_facade.load_flow_definition(flow_key)
            if flow_def is not None:
                logger.debug("Loaded flow %s from pack specs", flow_key)
                return flow_def
            # Fall back to legacy if pack doesn't have it
            logger.debug("Flow %s not in pack, falling back to registry", flow_key)

        # Use legacy flow registry
        return self._flow_registry.get_flow(flow_key)

    def _run_preflight(
        self,
        run_id: RunId,
        spec: Optional[RunSpec],
        backend: str,
    ) -> "PreflightResult":
        """Run preflight environment checks before execution.

        Args:
            run_id: The run ID (for path checks).
            spec: The run specification.
            backend: Backend to check.

        Returns:
            PreflightResult with aggregate status.
        """
        from swarm.runtime.preflight import PreflightResult, run_preflight

        # Skip preflight if configured
        if self._skip_preflight:
            logger.debug("Preflight checks skipped (skip_preflight=True)")
            return PreflightResult(
                passed=True,
                warnings=["Preflight checks were skipped"],
                run_id=run_id,
                backend=backend,
            )

        # Run preflight checks
        result = run_preflight(
            run_spec=spec,
            backend=backend,
            run_id=run_id,
            repo_root=self._repo_root,
            skip_preflight=False,
        )

        # Log preflight result
        if result.passed:
            logger.info(
                "Preflight passed (%d checks, %d warnings) in %dms",
                len(result.checks),
                len(result.warnings),
                result.total_duration_ms,
            )
        else:
            logger.warning(
                "Preflight failed with %d blocking issue(s): %s",
                len(result.blocking_issues),
                "; ".join(result.blocking_issues[:3]),  # First 3 issues
            )

        # Emit preflight event
        storage_module.append_event(
            run_id,
            RunEvent(
                run_id=run_id,
                ts=datetime.now(timezone.utc),
                kind="preflight_completed",
                flow_key="",
                step_id=None,
                payload={
                    "passed": result.passed,
                    "blocking_issues": result.blocking_issues,
                    "warnings": result.warnings,
                    "duration_ms": result.total_duration_ms,
                    "checks": [{"name": c.name, "status": c.status.value} for c in result.checks],
                },
            ),
        )

        return result

    def run_stepwise_flow(
        self,
        flow_key: str,
        spec: RunSpec,
        resume: bool = False,
        run_id: Optional[RunId] = None,
        macro_navigator: Optional[MacroNavigator] = None,
    ) -> RunId:
        """Execute a flow step by step.

        Args:
            flow_key: The flow to execute (e.g., "build", "plan").
            spec: The run specification.
            resume: Whether to resume an existing run.
            run_id: Optional run ID for resuming.
            macro_navigator: Optional MacroNavigator for between-flow routing.
                If provided, the flow result and routing decision will be
                computed at flow completion.

        Returns:
            The run ID.

        Note:
            For full macro routing support with flow result and decision,
            use run_stepwise_flow_with_routing() instead.
        """
        result = self.run_stepwise_flow_with_routing(
            flow_key=flow_key,
            spec=spec,
            resume=resume,
            run_id=run_id,
            macro_navigator=macro_navigator,
        )
        return result.run_id

    def run_stepwise_flow_with_routing(
        self,
        flow_key: str,
        spec: RunSpec,
        resume: bool = False,
        run_id: Optional[RunId] = None,
        macro_navigator: Optional[MacroNavigator] = None,
        run_state: Optional[RunState] = None,
    ) -> FlowExecutionResult:
        """Execute a flow step by step with macro routing support.

        This is the full-featured version of run_stepwise_flow() that returns
        a FlowExecutionResult with the macro routing decision for the next flow.

        Args:
            flow_key: The flow to execute (e.g., "build", "plan").
            spec: The run specification.
            resume: Whether to resume an existing run.
            run_id: Optional run ID for resuming.
            macro_navigator: Optional MacroNavigator for between-flow routing.
                If provided, route_after_flow() is called at flow completion.
            run_state: Optional existing RunState for resumption or tracking.

        Returns:
            FlowExecutionResult with run_id, summary, and optional macro_decision.

        Example:
            # Run a single flow with macro routing
            navigator = create_default_navigator()
            result = orchestrator.run_stepwise_flow_with_routing(
                flow_key="build",
                spec=RunSpec(flow_keys=["build"], initiator="cli"),
                macro_navigator=navigator,
            )

            # Check the routing decision
            if result.macro_decision:
                if result.macro_decision.action == MacroAction.ADVANCE:
                    next_flow = result.macro_decision.next_flow
                elif result.macro_decision.action == MacroAction.PAUSE:
                    # Wait for human intervention
                    pass
        """
        # Generate or use provided run ID
        if run_id is None:
            run_id = generate_run_id()

        # Initialize stop tracking
        with self._lock:
            if run_id not in self._stop_requests:
                self._stop_requests[run_id] = threading.Event()

        if resume:
            self.clear_stop_request(run_id)

        # Run preflight checks before expensive work
        backend = spec.backend if spec else "claude-harness"
        preflight_result = self._run_preflight(run_id, spec, backend)
        if not preflight_result.passed:
            # Preflight failed - attempt to inject env-doctor sidequest or halt
            # For now, create a temporary run_state for potential sidequest injection
            temp_run_state = RunState(run_id=run_id, flow_key=flow_key, status="pending")

            from swarm.runtime.preflight import inject_env_doctor_sidequest

            if inject_env_doctor_sidequest(temp_run_state, preflight_result):
                logger.info("Preflight failed but env-doctor sidequest injected")
                # Continue with the sidequest handling
                if run_state is None:
                    run_state = temp_run_state
                else:
                    # Copy injected nodes to provided run_state
                    for node_id, node_spec in temp_run_state.injected_node_specs.items():
                        run_state.register_injected_node(node_spec)
            else:
                # No sidequest available - halt with clear error
                error_msg = (
                    f"Preflight failed with {len(preflight_result.blocking_issues)} blocking issue(s): "
                    f"{'; '.join(preflight_result.blocking_issues)}"
                )
                logger.error(error_msg)
                raise RuntimeError(error_msg)

        # Load flow definition - use pack specs if enabled
        flow_def = self._load_flow_definition(flow_key)
        if flow_def is None:
            raise ValueError(f"Unknown flow: {flow_key}")

        # Create run directory and initial state
        storage_module.init_run(run_id, flow_key, spec)

        # Use provided run_state or create new one
        if run_state is None:
            run_state = RunState(
                run_id=run_id,
                flow_key=flow_key,
                status="running",
            )

        # Emit run_started event
        storage_module.append_event(
            run_id,
            RunEvent(
                run_id=run_id,
                ts=datetime.now(timezone.utc),
                kind="run_started",
                flow_key=flow_key,
                step_id=None,
                payload={"spec": spec.__dict__ if hasattr(spec, "__dict__") else {}},
            ),
        )

        # Execute steps
        try:
            summary = self._execute_stepwise(
                run_id, flow_key, flow_def, spec, resume=resume, run_state=run_state
            )

            # Perform macro routing if navigator provided
            macro_decision: Optional[MacroRoutingDecision] = None
            flow_result: Optional[FlowResult] = None

            if macro_navigator is not None:
                # Extract flow result for routing decision
                artifacts_base = self._repo_root / "swarm" / "runs" / run_id
                flow_result = extract_flow_result(
                    flow_key=flow_key,
                    run_state=run_state,
                    artifacts_base=artifacts_base,
                )

                # Get macro routing decision
                macro_decision = macro_navigator.route_after_flow(
                    completed_flow=flow_key,
                    flow_result=flow_result,
                    run_state=run_state,
                )

                # Log the macro routing decision
                logger.info(
                    "MacroNavigator: Flow '%s' completed -> %s (next: %s, reason: %s)",
                    flow_key,
                    macro_decision.action.value,
                    macro_decision.next_flow or "(none)",
                    macro_decision.reason,
                )

                # Emit macro_route event for audit trail
                storage_module.append_event(
                    run_id,
                    RunEvent(
                        run_id=run_id,
                        ts=datetime.now(timezone.utc),
                        kind="macro_route",
                        flow_key=flow_key,
                        step_id=None,
                        payload={
                            "action": macro_decision.action.value,
                            "next_flow": macro_decision.next_flow,
                            "reason": macro_decision.reason,
                            "rule_applied": macro_decision.rule_applied,
                            "confidence": macro_decision.confidence,
                        },
                    ),
                )

                # Update run_state with the routing decision for audit trail
                run_state.flow_transition_history.append(
                    {
                        "from_flow": flow_key,
                        "to_flow": macro_decision.next_flow,
                        "action": macro_decision.action.value,
                        "reason": macro_decision.reason,
                        "rule_applied": macro_decision.rule_applied,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                )

                # Handle PAUSE case - update run state status
                if macro_decision.action == MacroAction.PAUSE:
                    run_state.status = "paused"
                    logger.info(
                        "MacroNavigator: PAUSE requested - stopping execution for human intervention. Reason: %s",
                        macro_decision.reason,
                    )
                    storage_module.append_event(
                        run_id,
                        RunEvent(
                            run_id=run_id,
                            ts=datetime.now(timezone.utc),
                            kind="flow_paused",
                            flow_key=flow_key,
                            step_id=None,
                            payload={
                                "reason": macro_decision.reason,
                                "awaiting_human": True,
                            },
                        ),
                    )

            return FlowExecutionResult(
                run_id=run_id,
                summary=summary,
                macro_decision=macro_decision,
                flow_result=flow_result,
            )

        except Exception as e:
            logger.error("Run %s failed: %s", run_id, e)
            storage_module.append_event(
                run_id,
                RunEvent(
                    run_id=run_id,
                    ts=datetime.now(timezone.utc),
                    kind="run_failed",
                    flow_key=flow_key,
                    step_id=None,
                    payload={"error": str(e)},
                ),
            )
            raise

    def run_autopilot(
        self,
        spec: RunSpec,
        plan_id: Optional[str] = None,
        run_plan: Optional[RunPlanSpec] = None,
        run_id: Optional[RunId] = None,
    ) -> RunId:
        """Execute multiple flows in autopilot mode using MacroNavigator.

        This method orchestrates the full SDLC by:
        1. Loading the run plan (flow sequence + policies)
        2. Executing flows sequentially
        3. Using MacroNavigator for between-flow routing
        4. Handling bounces, retries, and termination

        Args:
            spec: The run specification.
            plan_id: ID of a stored run plan to use.
            run_plan: Explicit RunPlanSpec (overrides plan_id).
            run_id: Optional run ID (generates if not provided).

        Returns:
            The run ID.

        Example:
            # Run full SDLC with autopilot
            run_id = orchestrator.run_autopilot(
                spec=RunSpec(flow_keys=["signal"], initiator="cli"),
                plan_id="default-autopilot",
            )
        """
        # Generate run ID
        if run_id is None:
            run_id = generate_run_id()

        # Load run plan - use explicit plan, or create default
        if run_plan is None:
            # Note: load_run_plan would be implemented in run_plan_api module
            # For now, we always use default if no explicit plan provided
            run_plan = RunPlanSpec.default()

        # Create MacroNavigator
        macro_nav = MacroNavigator(run_plan)

        # Initialize stop tracking
        with self._lock:
            if run_id not in self._stop_requests:
                self._stop_requests[run_id] = threading.Event()

        # Emit run_started event
        storage_module.append_event(
            run_id,
            RunEvent(
                run_id=run_id,
                ts=datetime.now(timezone.utc),
                kind="autopilot_started",
                flow_key="",
                step_id=None,
                payload={
                    "plan_id": plan_id,
                    "flow_sequence": run_plan.flow_sequence,
                    "human_policy": run_plan.human_policy.mode,
                },
            ),
        )

        # Track overall run state
        artifacts_base = self._repo_root / "swarm" / "runs" / run_id
        current_flow_idx = 0

        # Create a shared run state for macro-level tracking
        run_state = RunState(
            run_id=run_id,
            flow_key=run_plan.flow_sequence[0] if run_plan.flow_sequence else "",
            status="running",
        )

        try:
            while current_flow_idx < len(run_plan.flow_sequence):
                # Check for stop request
                if self._is_stop_requested(run_id):
                    logger.info("Stop requested, pausing autopilot at flow %d", current_flow_idx)
                    storage_module.append_event(
                        run_id,
                        RunEvent(
                            run_id=run_id,
                            ts=datetime.now(timezone.utc),
                            kind="autopilot_stopped",
                            flow_key=run_plan.flow_sequence[current_flow_idx],
                            step_id=None,
                            payload={"flow_index": current_flow_idx},
                        ),
                    )
                    break

                flow_key = run_plan.flow_sequence[current_flow_idx]
                run_state.flow_key = flow_key
                run_state.current_flow_index = current_flow_idx + 1  # 1-indexed for display

                logger.info(
                    "Autopilot: Starting flow %d/%d: %s",
                    current_flow_idx + 1,
                    len(run_plan.flow_sequence),
                    flow_key,
                )

                # Get flow definition - use pack specs if enabled
                flow_def = self._load_flow_definition(flow_key)
                if flow_def is None:
                    logger.error("Unknown flow in sequence: %s", flow_key)
                    break

                # Create run directory for this flow
                storage_module.init_run(run_id, flow_key, spec)

                # Emit flow_started event
                storage_module.append_event(
                    run_id,
                    RunEvent(
                        run_id=run_id,
                        ts=datetime.now(timezone.utc),
                        kind="flow_started",
                        flow_key=flow_key,
                        step_id=None,
                        payload={"flow_index": current_flow_idx},
                    ),
                )

                # Execute the flow
                try:
                    self._execute_stepwise(
                        run_id=run_id,
                        flow_key=flow_key,
                        flow_def=flow_def,
                        spec=spec,
                        run_state=run_state,
                    )
                except Exception as e:
                    logger.error("Flow %s failed: %s", flow_key, e)
                    storage_module.append_event(
                        run_id,
                        RunEvent(
                            run_id=run_id,
                            ts=datetime.now(timezone.utc),
                            kind="flow_failed",
                            flow_key=flow_key,
                            step_id=None,
                            payload={"error": str(e)},
                        ),
                    )
                    break

                # Extract flow result for MacroNavigator
                flow_result = extract_flow_result(
                    flow_key=flow_key,
                    run_state=run_state,
                    artifacts_base=artifacts_base,
                )

                # Get macro routing decision
                macro_decision = macro_nav.route_after_flow(
                    completed_flow=flow_key,
                    flow_result=flow_result,
                    run_state=run_state,
                )

                # Emit macro routing event
                storage_module.append_event(
                    run_id,
                    RunEvent(
                        run_id=run_id,
                        ts=datetime.now(timezone.utc),
                        kind="macro_route",
                        flow_key=flow_key,
                        step_id=None,
                        payload={
                            "action": macro_decision.action.value,
                            "next_flow": macro_decision.next_flow,
                            "reason": macro_decision.reason,
                            "rule_applied": macro_decision.rule_applied,
                        },
                    ),
                )

                # Apply the decision
                if macro_decision.action == MacroAction.TERMINATE:
                    logger.info("Autopilot: Terminating - %s", macro_decision.reason)
                    break

                elif macro_decision.action == MacroAction.PAUSE:
                    logger.info("Autopilot: Pausing for human - %s", macro_decision.reason)
                    storage_module.append_event(
                        run_id,
                        RunEvent(
                            run_id=run_id,
                            ts=datetime.now(timezone.utc),
                            kind="autopilot_paused",
                            flow_key=flow_key,
                            step_id=None,
                            payload={"reason": macro_decision.reason},
                        ),
                    )
                    break

                elif macro_decision.action == MacroAction.GOTO:
                    # Jump to a specific flow (e.g., bounce from gate to build)
                    target_flow = macro_decision.next_flow
                    if target_flow:
                        try:
                            target_idx = run_plan.flow_sequence.index(target_flow)
                            current_flow_idx = target_idx
                            logger.info("Autopilot: GOTO %s (index %d)", target_flow, target_idx)

                            # Record flow transition
                            run_state.flow_transition_history.append(
                                {
                                    "from_flow": flow_key,
                                    "to_flow": target_flow,
                                    "action": "goto",
                                    "reason": macro_decision.reason,
                                    "timestamp": datetime.now(timezone.utc).isoformat(),
                                }
                            )
                        except ValueError:
                            logger.error("GOTO target %s not in sequence", target_flow)
                            break
                    else:
                        logger.error("GOTO action without target flow")
                        break

                elif macro_decision.action == MacroAction.REPEAT:
                    # Re-run the same flow
                    logger.info("Autopilot: REPEAT %s", flow_key)
                    run_state.flow_transition_history.append(
                        {
                            "from_flow": flow_key,
                            "to_flow": flow_key,
                            "action": "repeat",
                            "reason": macro_decision.reason,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        }
                    )
                    # Don't increment current_flow_idx

                elif macro_decision.action == MacroAction.SKIP:
                    # Skip to next flow
                    current_flow_idx += 1
                    logger.info("Autopilot: SKIP to flow %d", current_flow_idx)

                else:  # ADVANCE
                    # Normal advancement to next flow
                    current_flow_idx += 1
                    if current_flow_idx < len(run_plan.flow_sequence):
                        next_flow = run_plan.flow_sequence[current_flow_idx]
                        run_state.flow_transition_history.append(
                            {
                                "from_flow": flow_key,
                                "to_flow": next_flow,
                                "action": "advance",
                                "reason": macro_decision.reason,
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                            }
                        )

            # Emit autopilot_completed event
            storage_module.append_event(
                run_id,
                RunEvent(
                    run_id=run_id,
                    ts=datetime.now(timezone.utc),
                    kind="autopilot_completed",
                    flow_key="",
                    step_id=None,
                    payload={
                        "flows_executed": current_flow_idx,
                        "total_flows": len(run_plan.flow_sequence),
                        "routing_history": macro_nav.get_routing_history(),
                    },
                ),
            )

            return run_id

        except Exception as e:
            logger.error("Autopilot run %s failed: %s", run_id, e)
            storage_module.append_event(
                run_id,
                RunEvent(
                    run_id=run_id,
                    ts=datetime.now(timezone.utc),
                    kind="autopilot_failed",
                    flow_key="",
                    step_id=None,
                    payload={"error": str(e)},
                ),
            )
            raise

    def _execute_stepwise(
        self,
        run_id: RunId,
        flow_key: str,
        flow_def: FlowDefinition,
        spec: RunSpec,
        resume: bool = False,
        run_state: Optional[RunState] = None,
        start_step: Optional[str] = None,
        end_step: Optional[str] = None,
    ) -> FlowStepwiseSummary:
        """Execute flow steps sequentially.

        Args:
            run_id: The run identifier.
            flow_key: The flow key.
            flow_def: The flow definition.
            spec: The run specification.
            resume: Whether resuming an existing run.
            run_state: Optional existing run state for resumption.
            start_step: Optional step ID to start from.
            end_step: Optional step ID to stop at.

        Returns:
            FlowStepwiseSummary with final status.
        """
        history: List[Dict[str, Any]] = []
        loop_state: Dict[str, int] = {}
        current_step_idx = 0
        steps = flow_def.steps

        # Use provided run_state or current_step_idx from start_step
        if run_state is not None:
            current_step_idx = run_state.step_index
        elif start_step is not None:
            for i, s in enumerate(steps):
                if s.id == start_step:
                    current_step_idx = i
                    break

        if not steps:
            return FlowStepwiseSummary(
                run_id=run_id,
                status=RunStatus.SUCCEEDED,
                sdlc_status=SDLCStatus.OK,
                flow_key=flow_key,
                completed_steps=[],
                duration_ms=0,
            )

        # Build FlowGraph for Navigator from flow definition
        flow_graph = build_flow_graph_from_definition(flow_def)

        # Use provided run_state or create new one for Navigator
        if run_state is None:
            run_state = RunState(
                run_id=run_id,
                flow_key=flow_key,
                current_step_id=steps[0].id if steps else None,
                step_index=current_step_idx,
                loop_state=loop_state,
                status="running",
            )

        # Track iteration count per step for stall detection
        iteration_counts: Dict[str, int] = {}

        while current_step_idx < len(steps):
            # Check for end_step boundary
            if end_step is not None:
                current_step = steps[current_step_idx]
                if current_step.id == end_step:
                    logger.info("Reached end_step %s, stopping execution", end_step)
                    break
            # Check for stop request
            if self._is_stop_requested(run_id):
                logger.info("Stop requested, pausing run %s at step %d", run_id, current_step_idx)
                storage_module.append_event(
                    run_id,
                    RunEvent(
                        run_id=run_id,
                        ts=datetime.now(timezone.utc),
                        kind="run_stopped",
                        flow_key=flow_key,
                        step_id=steps[current_step_idx].id,
                        payload={"step_index": current_step_idx},
                    ),
                )
                break

            step = steps[current_step_idx]

            # For injected nodes, resolve via the node resolver
            current_node_id = run_state.current_step_id or step.id
            resolved = resolve_node(current_node_id, flow_def, run_state)

            # If we resolved to an injected node, use its details
            if resolved and resolved.is_injected:
                # Create a synthetic step context for the injected node
                step_role = resolved.role
                step_agents = resolved.agents
            else:
                step_role = step.role
                step_agents = tuple(step.agents) if step.agents else ()

            # Update RunState with current position
            run_state.current_step_id = step.id
            run_state.step_index = current_step_idx

            # Track iteration for this step
            iteration_counts[step.id] = iteration_counts.get(step.id, 0) + 1
            current_iteration = iteration_counts[step.id]

            # Build routing context for this step
            routing_ctx = build_routing_context(step, loop_state)

            # Build step context
            ctx = StepContext(
                repo_root=self._repo_root,
                run_id=run_id,
                flow_key=flow_key,
                step_id=current_node_id,  # Use current_node_id instead of step.id
                step_index=resolved.index if resolved else step.index,
                total_steps=len(steps),
                spec=spec,
                flow_title=flow_def.title,
                step_role=step_role,  # Use resolved role
                step_agents=step_agents,  # Use resolved agents
                history=history,
                routing=routing_ctx,
            )

            # Execute step via engine runner (handles lifecycle vs single-phase)
            engine_result = run_step_via_engine(
                ctx=ctx,
                engine=self._engine,
                repo_root=self._repo_root,
            )

            # Extract results for downstream use
            step_result = engine_result.step_result
            events = engine_result.events

            # Emit standard execution events (file_changes, lifecycle, timing)
            execution_events = emit_step_execution_events(
                run_id=run_id,
                flow_key=flow_key,
                step_id=step.id,
                step_index=current_step_idx,
                iteration=current_iteration,
                result=engine_result,
            )
            for event in execution_events:
                storage_module.append_event(run_id, event)

            # Persist step-generated events
            for event in events:
                storage_module.append_event(run_id, event)

            # Add to history
            history.append(
                {
                    "step_id": step.id,
                    "status": step_result.status,
                    "output": step_result.output,
                    "duration_ms": step_result.duration_ms,
                }
            )

            # Mark node as completed in RunState
            run_state.mark_node_completed(step.id)

            run_base = self._repo_root / "swarm" / "runs" / run_id / flow_key

            # ENVELOPE INVARIANT: Guarantee envelope exists after step execution
            # See envelope.py for detailed documentation of this invariant.
            ensure_step_envelope(
                run_base=run_base,
                step_id=step.id,
                step_result=step_result,
                flow_key=flow_key,
                run_id=run_id,
            )

            # =================================================================
            # UTILITY FLOW INJECTION DETECTION
            # =================================================================
            # After step completion, check if injection triggers fire.
            # If a trigger is detected, inject the utility flow using
            # stack-frame execution pattern.
            # =================================================================
            injection_result = self._check_and_inject_utility_flow(
                run_id=run_id,
                flow_key=flow_key,
                step=step,
                step_result=step_result,
                run_state=run_state,
            )

            if injection_result is not None:
                # Utility flow was injected - redirect to it
                next_step_id = injection_result
                reason = "utility_flow_injected"
                routing_source = "utility_flow_injection"

                # Emit injection event
                storage_module.append_event(
                    run_id,
                    RunEvent(
                        run_id=run_id,
                        ts=datetime.now(timezone.utc),
                        kind="utility_flow_injected",
                        flow_key=flow_key,
                        step_id=step.id,
                        payload={
                            "injected_node_id": next_step_id,
                            "trigger_detected": True,
                        },
                    ),
                )

                # Skip normal routing - go directly to the injected utility flow
                # Find the step index for the injected node (it's -1 for injected nodes)
                # The node is resolved via _resolve_node in the next iteration
                current_step_idx = 0  # Reset to allow re-iteration
                run_state.current_step_id = next_step_id
                continue

            # Check if resuming from completed utility flow
            resume_node = self._check_utility_flow_completion(run_state)
            if resume_node is not None:
                # Utility flow completed - resume at the interrupted node
                next_step_id = resume_node
                reason = "utility_flow_completed:return"
                routing_source = "utility_flow_return"

                # Emit resumption event
                storage_module.append_event(
                    run_id,
                    RunEvent(
                        run_id=run_id,
                        ts=datetime.now(timezone.utc),
                        kind="utility_flow_resumed",
                        flow_key=flow_key,
                        step_id=step.id,
                        payload={
                            "resume_node_id": next_step_id,
                        },
                    ),
                )

                # Find the step index for the resume node
                for i, s in enumerate(steps):
                    if s.id == next_step_id:
                        current_step_idx = i
                        break
                continue

            # =================================================================
            # ROUTING DECISION: Candidate-Set Pattern with RoutingMode
            # =================================================================
            # Python generates candidates, Navigator chooses, Python validates.
            # All routing paths produce a RoutingOutcome for consistent audit trail.
            #
            # Routing modes:
            # - DETERMINISTIC_ONLY: Fast-path only, no LLM calls
            # - ASSIST: Fast-path + Navigator chooses among candidates
            # - AUTHORITATIVE: Navigator can propose EXTEND_GRAPH freely
            # =================================================================

            routing_outcome: Optional[RoutingOutcome] = None

            # Step 1: Always try fast-path for obvious deterministic cases
            fast_path_result = self._try_fast_path_routing(
                step=step,
                step_result=step_result,
                run_state=run_state,
                loop_state=loop_state,
                iteration=current_iteration,
            )

            if fast_path_result is not None:
                # Fast-path handled the routing deterministically
                next_step_id, reason, routing_source, routing_signal_used = fast_path_result
                routing_outcome = RoutingOutcome.from_tuple(
                    next_step_id=next_step_id,
                    reason=reason,
                    routing_source=routing_source,
                    signal=routing_signal_used,
                )
                logger.debug(
                    "Fast-path routing for step %s: next=%s, reason=%s",
                    step.id,
                    routing_outcome.next_step_id,
                    routing_outcome.reason,
                )
            elif self._routing_mode == RoutingMode.DETERMINISTIC_ONLY:
                # Deterministic mode: Fall back to config-based routing
                # No Navigator calls - used for CI and reproducibility
                next_step_id, reason, routing_source, routing_signal_used = self._route_via_config_fallback(
                    step=step,
                    step_result=step_result,
                    flow_def=flow_def,
                    loop_state=loop_state,
                )
                routing_outcome = RoutingOutcome.from_tuple(
                    next_step_id=next_step_id,
                    reason=reason,
                    routing_source=routing_source,
                    signal=routing_signal_used,
                )
                logger.debug(
                    "Deterministic routing for step %s: next=%s, reason=%s",
                    step.id,
                    routing_outcome.next_step_id,
                    routing_outcome.reason,
                )
            elif self._navigation_orchestrator is not None:
                # Navigator-based routing (ASSIST or AUTHORITATIVE mode)
                # Generate candidates, let Navigator choose
                next_step_id, reason, routing_source, routing_candidates_used = self._route_via_navigator(
                    run_id=run_id,
                    flow_key=flow_key,
                    step=step,
                    step_result=step_result,
                    flow_graph=flow_graph,
                    run_state=run_state,
                    iteration=current_iteration,
                    spec=spec,
                    run_base=run_base,
                    flow_def=flow_def,
                    loop_state=loop_state,
                )
                routing_outcome = RoutingOutcome.from_tuple(
                    next_step_id=next_step_id,
                    reason=reason,
                    routing_source=routing_source,
                    candidates=routing_candidates_used,
                )
            else:
                # Navigator required but not available - ESCALATE
                # This is a hard failure in ASSIST/AUTHORITATIVE modes
                logger.error(
                    "Navigator unavailable for step %s in %s mode - ESCALATING",
                    step.id,
                    self._routing_mode.value,
                )
                routing_outcome = RoutingOutcome.from_tuple(
                    next_step_id=None,
                    reason=f"escalate:navigator_unavailable:{self._routing_mode.value}",
                    routing_source="escalate",
                )

            # Extract next_step_id and reason from outcome for downstream use
            next_step_id = routing_outcome.next_step_id
            reason = routing_outcome.reason

            # Update routing context with decision
            routing_ctx.decision = "advance" if next_step_id else "terminate"
            routing_ctx.reason = reason

            # Update receipt with routing info
            if step.agents:
                update_receipt_routing(
                    self._repo_root, run_id, flow_key, step.id, step.agents[0], routing_ctx
                )

            # Emit routing event with canonical payload from RoutingOutcome
            storage_module.append_event(
                run_id,
                RunEvent(
                    run_id=run_id,
                    ts=datetime.now(timezone.utc),
                    kind="step_routed",
                    flow_key=flow_key,
                    step_id=step.id,
                    payload=routing_outcome.to_event_payload(),
                ),
            )

            if next_step_id is None:
                # Flow complete
                break

            # Find next step by ID
            found = False
            for i, s in enumerate(steps):
                if s.id == next_step_id:
                    current_step_idx = i
                    found = True
                    break

            if not found:
                logger.error("Next step %s not found in flow", next_step_id)
                break

        # Emit run_completed event
        storage_module.append_event(
            run_id,
            RunEvent(
                run_id=run_id,
                ts=datetime.now(timezone.utc),
                kind="run_completed",
                flow_key=flow_key,
                step_id=None,
                payload={"steps_completed": len(history)},
            ),
        )

        return FlowStepwiseSummary(
            run_id=run_id,
            status=RunStatus.SUCCEEDED,
            sdlc_status=SDLCStatus.OK,
            flow_key=flow_key,
            completed_steps=[h["step_id"] for h in history],
            duration_ms=sum(h.get("duration_ms", 0) for h in history),
        )

    # Note: _build_flow_graph_from_definition, _resolve_node, _get_next_node_id
    # have been extracted to graph_bridge.py and node_resolver.py

    def _route_via_navigator(
        self,
        run_id: RunId,
        flow_key: str,
        step: StepDefinition,
        step_result: Any,
        flow_graph: FlowGraph,
        run_state: RunState,
        iteration: int,
        spec: RunSpec,
        run_base: Path,
        flow_def: FlowDefinition,
        loop_state: Dict[str, int],
    ) -> Tuple[Optional[str], str, str, List[Dict[str, Any]]]:
        """Route using NavigationOrchestrator with candidate-set pattern.

        Generates routing candidates from the graph, passes them to Navigator,
        and validates the chosen candidate. This implements the candidate-set
        pattern where Python generates options and Navigator intelligently chooses.

        Args:
            run_id: The run identifier.
            flow_key: The flow key.
            step: The current step definition.
            step_result: Result from step execution.
            flow_graph: The FlowGraph for edge candidates.
            run_state: Current run state (modified in place).
            iteration: Current iteration count for this step.
            spec: The run specification.
            run_base: Path to the run base directory.
            flow_def: The flow definition for candidate generation.
            loop_state: Microloop iteration state.

        Returns:
            Tuple of (next_step_id, reason, routing_source, routing_candidates).
        """
        # Build step result dict for Navigator
        step_result_dict = {
            "status": step_result.status,
            "output": step_result.output,
            "duration_ms": step_result.duration_ms,
        }

        # Get file changes from step result if available
        file_changes = None
        if hasattr(step_result, "file_changes"):
            file_changes = step_result.file_changes

        # Get verification result if available
        verification_result = None
        if hasattr(step_result, "verification_result"):
            verification_result = step_result.verification_result

        # Try to read previous envelope for context
        previous_envelope = None
        if step.id in run_state.handoff_envelopes:
            previous_envelope = run_state.handoff_envelopes[step.id]

        # =================================================================
        # FORENSIC VERDICT COMPUTATION: Compare claims vs evidence
        # =================================================================
        # Compute forensic verdict BEFORE generating candidates so that
        # priority shaping can be applied. This implements "forensics over
        # narrative" - actual evidence (diff scan, test results) trumps
        # claims in the handoff envelope.
        #
        # The verdict is used to:
        # 1. Shape candidate priorities (demote ADVANCE, promote REPEAT/ESCALATE)
        # 2. Provide evidence pointers for transparency
        # 3. Inform Navigator's routing decision
        forensic_verdict: Optional[Dict[str, Any]] = None
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

                # Convert to dict for candidate generation
                forensic_verdict = forensic_verdict_to_dict(verdict)

                logger.debug(
                    "Forensic verdict for step %s: recommendation=%s, confidence=%.2f, flags=%s",
                    step.id,
                    verdict.recommendation.value,
                    verdict.confidence,
                    [f.value for f in verdict.reward_hacking_flags],
                )

            except Exception as e:
                logger.warning(
                    "Failed to compute forensic verdict for step %s: %s",
                    step.id,
                    e,
                )

        # =================================================================
        # CANDIDATE-SET PATTERN: Generate routing candidates from graph
        # =================================================================
        # Python generates candidates, Navigator chooses, Python validates.
        # This keeps intelligence bounded while preserving graph constraints.
        #
        # Forensic verdict is passed to enable priority shaping:
        # - REJECT verdict: demote ADVANCE by 40, promote REPEAT/ESCALATE
        # - VERIFY verdict: demote ADVANCE by 30, promote REPEAT/ESCALATE
        # - reward_hacking_flags: trigger priority shaping

        # Get sidequest options for detour candidates
        sidequest_options = None
        if self._navigation_orchestrator is not None:
            catalog = self._navigation_orchestrator.sidequest_catalog
            trigger_context = {
                "verification_passed": verification_result.get("passed", True)
                if verification_result
                else True,
                "iteration": iteration,
            }
            applicable = catalog.get_applicable_sidequests(trigger_context, run_id)
            sidequest_options = [
                {
                    "sidequest_id": sq.sidequest_id,
                    "name": sq.description,
                    "priority": sq.priority,
                }
                for sq in applicable
            ]

        # Generate routing candidates with forensic priority shaping
        candidates = generate_routing_candidates(
            step=step,
            step_result=step_result_dict,
            flow_def=flow_def,
            loop_state=loop_state,
            run_state=run_state,
            sidequest_options=sidequest_options,
            forensic_verdict=forensic_verdict,
        )

        # Convert RoutingCandidate objects to dicts for Navigator
        routing_candidates = [
            {
                "candidate_id": c.candidate_id,
                "action": c.action,
                "target_node": c.target_node,
                "reason": c.reason,
                "priority": c.priority,
                "source": c.source,
                "is_default": c.is_default,
            }
            for c in candidates
        ]

        logger.debug(
            "Generated %d routing candidates for step %s: %s",
            len(routing_candidates),
            step.id,
            [c["candidate_id"] for c in routing_candidates],
        )

        # Call NavigationOrchestrator.navigate() with candidates
        nav_result = self._navigation_orchestrator.navigate(
            run_id=run_id,
            flow_key=flow_key,
            current_node=step.id,
            iteration=iteration,
            flow_graph=flow_graph,
            step_result=step_result_dict,
            verification_result=verification_result,
            file_changes=file_changes,
            run_state=run_state,
            context_digest="",  # TODO: Implement context digest
            previous_envelope=previous_envelope,
            no_human_mid_flow=spec.no_human_mid_flow,
            routing_candidates=routing_candidates,
        )

        # Extract routing decision from NavigationResult
        next_step_id = nav_result.next_node
        routing_signal = nav_result.routing_signal

        reason = routing_signal.reason or "navigator_decision"
        routing_source = "navigator"

        # If detour was injected, note it in the reason
        if nav_result.detour_injected:
            routing_source = "navigator:detour"
            reason = f"Detour: {reason}"
        elif nav_result.extend_graph_injected:
            routing_source = "navigator:extend_graph"
            reason = f"Extend graph: {reason}"

        # Persist routing decision to envelope for consistency
        # Include candidate-set pattern audit trail
        #
        # CANDIDATE STORAGE PATTERN: To prevent journal bloat, full candidate
        # lists are written to separate artifact files. Only summary info
        # (count, IDs, path) is stored in the routing_dict for the envelope.
        candidate_set_path: Optional[str] = None
        if routing_candidates:
            try:
                # Ensure routing directory exists
                routing_dir = run_base / "routing"
                routing_dir.mkdir(parents=True, exist_ok=True)

                # Write candidates to separate artifact file
                candidate_file = routing_dir / f"candidates_step_{step.id}.json"
                candidate_set_path = f"routing/candidates_step_{step.id}.json"

                with open(candidate_file, "w", encoding="utf-8") as f:
                    json.dump(
                        {
                            "step_id": step.id,
                            "candidate_count": len(routing_candidates),
                            "candidates": routing_candidates,
                        },
                        f,
                        indent=2,
                    )
                logger.debug(
                    "Wrote %d routing candidates to %s",
                    len(routing_candidates),
                    candidate_file,
                )
            except Exception as e:
                logger.warning(
                    "Failed to write routing candidates to artifact file: %s", e
                )
                # Fall back to not storing the path if write fails
                candidate_set_path = None

        routing_dict = {
            "decision": routing_signal.decision.value
            if hasattr(routing_signal.decision, "value")
            else str(routing_signal.decision),
            "next_step_id": next_step_id,
            "reason": reason,
            "confidence": routing_signal.confidence,
            "needs_human": routing_signal.needs_human,
            # Candidate-set pattern audit trail (summary only, not full list)
            "chosen_candidate_id": routing_signal.chosen_candidate_id,
            "candidate_count": len(routing_candidates),
            "candidate_ids": [c.get("candidate_id") for c in routing_candidates],
            "candidate_set_path": candidate_set_path,
            "routing_source": routing_source,
        }
        updated = update_envelope_routing(
            run_base=run_base,
            step_id=step.id,
            routing_signal=routing_dict,
        )
        if updated:
            logger.debug(
                "Navigator: Persisted routing to envelope for step %s: "
                "next=%s, chosen_candidate=%s, candidates=%d",
                step.id,
                next_step_id,
                routing_signal.chosen_candidate_id,
                len(routing_candidates),
            )

        return next_step_id, reason, routing_source, routing_candidates

    def _route_via_config_fallback(
        self,
        step: StepDefinition,
        step_result: Any,
        flow_def: FlowDefinition,
        loop_state: Dict[str, int],
    ) -> Tuple[Optional[str], str, str, Optional["RoutingSignal"]]:
        """Route using config-based deterministic fallback.

        This is the deterministic routing path used in DETERMINISTIC_ONLY mode.
        It uses the flow definition's routing config without any LLM calls.

        IMPORTANT: Creates a RoutingSignal with routing_source="deterministic_fallback"
        to ensure complete audit trail coverage. No routing decision is "dark".

        Routing logic:
        1. If status is VERIFIED in microloop -> exit to next step
        2. If status is PARTIAL/UNVERIFIED in microloop -> retry (if under max)
        3. If max iterations reached -> advance to next
        4. Linear routing -> advance to next step

        Args:
            step: The current step definition.
            step_result: Result from step execution.
            flow_def: The flow definition.
            loop_state: Microloop iteration state.

        Returns:
            Tuple of (next_step_id, reason, routing_source, routing_signal).
            The routing_signal contains the full audit trail with chosen_candidate_id.
        """
        from swarm.runtime.types import RoutingCandidate, RoutingDecision, RoutingSignal

        routing = step.routing
        status = step_result.status if hasattr(step_result, "status") else ""
        routing_source = "deterministic_fallback"

        def _create_deterministic_signal(
            decision: RoutingDecision,
            next_step_id: Optional[str],
            reason: str,
            loop_count: int = 0,
            exit_condition_met: bool = False,
        ) -> "RoutingSignal":
            """Create a RoutingSignal for deterministic fallback with proper audit trail."""
            # Generate deterministic candidate_id based on decision and target
            if decision == RoutingDecision.LOOP:
                candidate_id = f"loop:{next_step_id}:iter_{loop_count}"
            elif decision == RoutingDecision.ADVANCE and next_step_id:
                candidate_id = f"advance:{next_step_id}"
            elif decision == RoutingDecision.TERMINATE:
                candidate_id = "terminate"
            else:
                candidate_id = f"{decision.value}:{next_step_id or 'none'}"

            # Create the routing candidate that was implicitly chosen
            chosen_candidate = RoutingCandidate(
                candidate_id=candidate_id,
                action=decision.value,
                target_node=next_step_id,
                reason=reason,
                priority=100,  # Deterministic decisions are highest priority
                source="deterministic_fallback",
                is_default=True,
            )

            return RoutingSignal(
                decision=decision,
                next_step_id=next_step_id,
                reason=reason,
                confidence=1.0,  # Deterministic decisions have full confidence
                needs_human=False,
                loop_count=loop_count,
                exit_condition_met=exit_condition_met,
                chosen_candidate_id=candidate_id,
                routing_candidates=[chosen_candidate],
                routing_source="deterministic_fallback",
            )

        # Handle microloop routing
        if routing and routing.kind == "microloop" and routing.loop_target:
            loop_key = f"{step.id}:{routing.loop_target}"
            current_iter = loop_state.get(loop_key, 0)

            # VERIFIED -> exit loop
            if status in ("VERIFIED", "verified"):
                reason = f"config_verified_exit:iter_{current_iter}"
                signal = _create_deterministic_signal(
                    decision=RoutingDecision.ADVANCE,
                    next_step_id=routing.next,
                    reason=reason,
                    loop_count=current_iter,
                    exit_condition_met=True,
                )
                return (routing.next, reason, routing_source, signal)

            # PARTIAL/UNVERIFIED -> check if can iterate
            can_iterate = True  # Default to true
            if status in ("PARTIAL", "partial", "UNVERIFIED", "unverified"):
                # Check can_further_iteration_help
                if hasattr(step_result, "output") and isinstance(step_result.output, dict):
                    can_iterate_val = step_result.output.get("can_further_iteration_help")
                    if can_iterate_val is not None:
                        can_iterate = str(can_iterate_val).lower() not in ("no", "false")

                # Under max iterations and can iterate -> retry
                if current_iter < routing.max_iterations and can_iterate:
                    loop_state[loop_key] = current_iter + 1
                    next_iter = current_iter + 1
                    reason = f"config_loop_retry:iter_{next_iter}"
                    signal = _create_deterministic_signal(
                        decision=RoutingDecision.LOOP,
                        next_step_id=routing.loop_target,
                        reason=reason,
                        loop_count=next_iter,
                        exit_condition_met=False,
                    )
                    return (routing.loop_target, reason, routing_source, signal)

            # Max iterations or can't iterate -> exit
            if current_iter >= routing.max_iterations or not can_iterate:
                reason = f"config_loop_exit:max_{routing.max_iterations}:iter_{current_iter}"
                signal = _create_deterministic_signal(
                    decision=RoutingDecision.ADVANCE,
                    next_step_id=routing.next,
                    reason=reason,
                    loop_count=current_iter,
                    exit_condition_met=True,
                )
                return (routing.next, reason, routing_source, signal)

        # Handle linear routing
        if routing and routing.kind == "linear":
            if routing.next:
                reason = "config_linear_advance"
                signal = _create_deterministic_signal(
                    decision=RoutingDecision.ADVANCE,
                    next_step_id=routing.next,
                    reason=reason,
                )
                return (routing.next, reason, routing_source, signal)
            else:
                reason = "config_flow_complete"
                signal = _create_deterministic_signal(
                    decision=RoutingDecision.TERMINATE,
                    next_step_id=None,
                    reason=reason,
                    exit_condition_met=True,
                )
                return (None, reason, routing_source, signal)

        # No routing config -> try sequential
        current_idx = None
        for i, s in enumerate(flow_def.steps):
            if s.id == step.id:
                current_idx = i
                break

        if current_idx is not None and current_idx + 1 < len(flow_def.steps):
            next_step = flow_def.steps[current_idx + 1].id
            reason = "config_sequential_advance"
            signal = _create_deterministic_signal(
                decision=RoutingDecision.ADVANCE,
                next_step_id=next_step,
                reason=reason,
            )
            return (next_step, reason, routing_source, signal)

        # No next step -> flow complete
        reason = "config_flow_complete"
        signal = _create_deterministic_signal(
            decision=RoutingDecision.TERMINATE,
            next_step_id=None,
            reason=reason,
            exit_condition_met=True,
        )
        return (None, reason, routing_source, signal)

    def _route_via_envelope_fallback(
        self,
        run_id: RunId,
        flow_key: str,
        step: StepDefinition,
        step_result: Any,
        flow_def: FlowDefinition,
        loop_state: Dict[str, int],
        run_base: Path,
    ) -> Tuple[Optional[str], str, str]:
        """Route using envelope-first fallback (legacy path).

        This is the original A3 envelope-first routing algorithm used when
        NavigationOrchestrator is not available.

        Args:
            run_id: The run identifier.
            flow_key: The flow key.
            step: The current step definition.
            step_result: Result from step execution.
            flow_def: The flow definition.
            loop_state: Microloop iteration state.
            run_base: Path to the run base directory.

        Returns:
            Tuple of (next_step_id, reason, routing_source).
        """
        # Try envelope-first routing
        envelope_routing = read_routing_from_envelope(run_base, step.id)
        routing_source = "envelope"

        if envelope_routing is not None:
            # Use routing from committed envelope (session mode path)
            decision_str = envelope_routing.get("decision", "advance")
            decision = parse_routing_decision(decision_str)

            if decision == RoutingDecision.TERMINATE:
                next_step_id = None
                reason = envelope_routing.get("reason", "terminate_via_envelope")
            elif decision == RoutingDecision.LOOP:
                # Handle loop: use loop_target from routing config
                routing = step.routing
                if routing and routing.loop_target:
                    loop_key = f"{step.id}:{routing.loop_target}"
                    current_iter = loop_state.get(loop_key, 0)
                    loop_state[loop_key] = current_iter + 1
                    next_step_id = routing.loop_target
                    reason = envelope_routing.get("reason", f"loop_via_envelope:{current_iter + 1}")
                else:
                    next_step_id = envelope_routing.get("next_step_id")
                    reason = envelope_routing.get("reason", "loop_via_envelope")
            else:
                # ADVANCE or BRANCH
                next_step_id = envelope_routing.get("next_step_id")
                reason = envelope_routing.get("reason", "advance_via_envelope")

                # If no next_step_id in envelope, fall back to routing config
                if next_step_id is None and step.routing and step.routing.next:
                    next_step_id = step.routing.next

            logger.debug(
                "A3: Using envelope routing for step %s: decision=%s, next=%s",
                step.id,
                decision_str,
                next_step_id,
            )
        else:
            # Fallback: Use create_routing_signal for proper decision semantics
            routing_source = "fallback"

            result_dict = {
                "run_id": run_id,
                "flow_key": flow_key,
                "status": step_result.status,
            }

            # Create receipt reader for routing
            def make_receipt_reader():
                repo_root = self._repo_root
                return lambda r, f, s, a, field: read_receipt_field(repo_root, r, f, s, a, field)

            # Create a proper RoutingSignal using create_routing_signal
            # This preserves LOOP/BRANCH/ADVANCE/TERMINATE semantics
            routing_signal = create_routing_signal(
                step=step,
                result=result_dict,
                loop_state=loop_state,
                receipt_reader=make_receipt_reader(),
            )

            # Extract next_step_id and reason from the signal
            next_step_id = routing_signal.next_step_id
            reason = routing_signal.reason or "fallback_routing"

            # Handle loop state updates for LOOP decisions
            if routing_signal.decision == RoutingDecision.LOOP:
                routing = step.routing
                if routing and routing.loop_target:
                    loop_key = f"{step.id}:{routing.loop_target}"
                    current_iter = loop_state.get(loop_key, 0)
                    loop_state[loop_key] = current_iter + 1
                    next_step_id = routing.loop_target
                    reason = f"loop_via_fallback:{current_iter + 1}"

            # Persist routing decision to envelope for consistency
            # Use the proper decision from the RoutingSignal
            routing_dict = {
                "decision": routing_signal.decision.value
                if hasattr(routing_signal.decision, "value")
                else str(routing_signal.decision),
                "next_step_id": next_step_id,
                "reason": reason,
                "confidence": routing_signal.confidence,
                "needs_human": routing_signal.needs_human,
                "loop_count": routing_signal.loop_count,
                "exit_condition_met": routing_signal.exit_condition_met,
            }
            updated = update_envelope_routing(
                run_base=run_base,
                step_id=step.id,
                routing_signal=routing_dict,
            )
            if updated:
                logger.debug(
                    "A3: Persisted fallback routing to envelope for step %s (decision=%s)",
                    step.id,
                    routing_dict["decision"],
                )

        return next_step_id, reason, routing_source

    def _try_fast_path_routing(
        self,
        step: StepDefinition,
        step_result: Any,
        run_state: RunState,
        loop_state: Dict[str, int],
        iteration: int,
    ) -> Optional[Tuple[Optional[str], str, str, Optional["RoutingSignal"]]]:
        """Try fast-path routing for obvious cases without calling Navigator.

        Fast-path handles deterministic routing decisions that don't need
        Navigator intelligence. This saves LLM calls and latency.

        Fast-path cases:
        1. RETRY on PARTIAL/UNVERIFIED in microloop (before max iterations)
        2. LINEAR advance when verification passed
        3. TERMINATE when at terminal node with no next step

        Returns None if fast-path doesn't apply (Navigator should handle).

        IMPORTANT: Fast-path ALWAYS creates a RoutingSignal with routing_source="fast_path"
        to ensure complete audit trail coverage. No routing decision is "dark".

        Args:
            step: The current step definition.
            step_result: Result from step execution.
            run_state: Current run state.
            loop_state: Loop iteration tracking.
            iteration: Current iteration count.

        Returns:
            Tuple of (next_step_id, reason, routing_source, routing_signal) or None.
            The routing_signal contains the full audit trail with chosen_candidate_id.
        """
        from swarm.runtime.types import RoutingCandidate, RoutingDecision, RoutingSignal

        routing = step.routing
        status = step_result.status if hasattr(step_result, "status") else ""

        def _create_fast_path_signal(
            decision: RoutingDecision,
            next_step_id: Optional[str],
            reason: str,
            loop_count: int = 0,
            exit_condition_met: bool = False,
        ) -> "RoutingSignal":
            """Create a RoutingSignal for fast-path decisions with proper audit trail.

            This ensures fast-path decisions are not "dark spots" in the audit trail.
            The chosen_candidate_id is deterministically derived from the decision.
            """
            # Generate deterministic candidate_id based on decision and target
            if decision == RoutingDecision.LOOP:
                candidate_id = f"loop:{next_step_id}:iter_{loop_count}"
            elif decision == RoutingDecision.ADVANCE and next_step_id:
                candidate_id = f"advance:{next_step_id}"
            elif decision == RoutingDecision.TERMINATE:
                candidate_id = "terminate"
            else:
                candidate_id = f"{decision.value}:{next_step_id or 'none'}"

            # Create the routing candidate that was implicitly chosen
            chosen_candidate = RoutingCandidate(
                candidate_id=candidate_id,
                action=decision.value,
                target_node=next_step_id,
                reason=reason,
                priority=100,  # Fast-path is highest priority (deterministic)
                source="fast_path",
                is_default=True,
            )

            return RoutingSignal(
                decision=decision,
                next_step_id=next_step_id,
                reason=reason,
                confidence=1.0,  # Fast-path decisions are deterministic
                needs_human=False,
                loop_count=loop_count,
                exit_condition_met=exit_condition_met,
                chosen_candidate_id=candidate_id,
                routing_candidates=[chosen_candidate],
                routing_source="fast_path",
            )

        # Case 1: RETRY in microloop when PARTIAL or UNVERIFIED
        # This is the most common fast-path - no need to ask Navigator
        if routing and routing.kind == "microloop" and routing.loop_target:
            loop_key = f"{step.id}:{routing.loop_target}"
            current_iter = loop_state.get(loop_key, 0)

            # Check if we should retry (not at max iterations yet)
            if current_iter < routing.max_iterations:
                # PARTIAL or UNVERIFIED -> retry deterministically
                if status in ("PARTIAL", "partial", "UNVERIFIED", "unverified"):
                    # Check if there's a "can_further_iteration_help" in the output
                    can_iterate = True
                    if hasattr(step_result, "output") and isinstance(step_result.output, dict):
                        can_iterate_val = step_result.output.get("can_further_iteration_help")
                        if can_iterate_val is not None:
                            can_iterate = str(can_iterate_val).lower() not in ("no", "false")

                    if can_iterate:
                        # Fast-path: retry the loop
                        loop_state[loop_key] = current_iter + 1
                        next_iter = current_iter + 1
                        reason = f"fast_path_retry:{status}:iter_{next_iter}"
                        signal = _create_fast_path_signal(
                            decision=RoutingDecision.LOOP,
                            next_step_id=routing.loop_target,
                            reason=reason,
                            loop_count=next_iter,
                            exit_condition_met=False,
                        )
                        return (routing.loop_target, reason, "fast_path", signal)

            # Max iterations reached -> advance to next
            if current_iter >= routing.max_iterations:
                if routing.next:
                    reason = f"fast_path_max_iterations:{routing.max_iterations}"
                    signal = _create_fast_path_signal(
                        decision=RoutingDecision.ADVANCE,
                        next_step_id=routing.next,
                        reason=reason,
                        loop_count=current_iter,
                        exit_condition_met=True,
                    )
                    return (routing.next, reason, "fast_path", signal)
                else:
                    reason = "fast_path_terminate_max_iterations"
                    signal = _create_fast_path_signal(
                        decision=RoutingDecision.TERMINATE,
                        next_step_id=None,
                        reason=reason,
                        loop_count=current_iter,
                        exit_condition_met=True,
                    )
                    return (None, reason, "fast_path", signal)

        # Case 2: VERIFIED in microloop -> exit to next step
        if routing and routing.kind == "microloop" and routing.next:
            if status in ("VERIFIED", "verified"):
                reason = "fast_path_verified_exit"
                loop_key = f"{step.id}:{routing.loop_target}" if routing.loop_target else step.id
                current_iter = loop_state.get(loop_key, 0)
                signal = _create_fast_path_signal(
                    decision=RoutingDecision.ADVANCE,
                    next_step_id=routing.next,
                    reason=reason,
                    loop_count=current_iter,
                    exit_condition_met=True,
                )
                return (routing.next, reason, "fast_path", signal)

        # Case 3: LINEAR routing with VERIFIED status
        if routing and routing.kind == "linear" and routing.next:
            if status in ("VERIFIED", "verified"):
                reason = "fast_path_linear_advance"
                signal = _create_fast_path_signal(
                    decision=RoutingDecision.ADVANCE,
                    next_step_id=routing.next,
                    reason=reason,
                )
                return (routing.next, reason, "fast_path", signal)

        # Case 4: Terminal step (no routing or no next step)
        if routing is None or (routing.kind == "linear" and routing.next is None):
            if status in ("VERIFIED", "verified"):
                reason = "fast_path_flow_complete"
                signal = _create_fast_path_signal(
                    decision=RoutingDecision.TERMINATE,
                    next_step_id=None,
                    reason=reason,
                    exit_condition_met=True,
                )
                return (None, reason, "fast_path", signal)

        # Case 5: Resuming from detour - check interruption stack
        if run_state.is_interrupted():
            top_frame = run_state.peek_interruption()
            if top_frame is not None:
                # If this is a sidequest step completing, check if we should
                # advance to next sidequest step or resume
                current_node = run_state.current_step_id or step.id
                if current_node.startswith("sq-"):
                    # This is a sidequest node - let Navigator handle resumption
                    # to properly manage multi-step sidequests
                    return None

        # No fast-path applies - let Navigator handle it
        return None

    # =========================================================================
    # Utility Flow Injection Methods
    # =========================================================================

    def _check_and_inject_utility_flow(
        self,
        run_id: RunId,
        flow_key: str,
        step: StepDefinition,
        step_result: Any,
        run_state: RunState,
        git_status: Optional[Dict[str, Any]] = None,
        verification_result: Optional[Dict[str, Any]] = None,
        file_changes: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """Check for injection triggers and inject utility flow if triggered.

        This method implements the utility flow injection detection:
        1. Check all known injection triggers against current context
        2. If a trigger fires, inject the corresponding utility flow
        3. Return the first node ID of the injected flow to execute

        The injection uses the stack-frame pattern:
        - Current flow context is pushed to the interruption stack
        - Utility flow nodes are registered for execution
        - On utility flow completion, stack is popped and original flow resumes

        Args:
            run_id: The run identifier.
            flow_key: Current flow key.
            step: The step that just completed.
            step_result: Result from step execution.
            run_state: Current run state (modified in place).
            git_status: Optional git status information.
            verification_result: Optional verification check results.
            file_changes: Optional file changes from diff scanner.

        Returns:
            First node ID of the injected utility flow, or None if no injection.
        """
        # Skip injection detection for utility flow nodes (prevent infinite loops)
        current_node = run_state.current_step_id or step.id
        if current_node.startswith("uf-") or current_node.startswith("sq-"):
            return None

        # Build step result dict for detector
        step_result_dict = {
            "status": step_result.status if hasattr(step_result, "status") else "",
            "output": step_result.output if hasattr(step_result, "output") else "",
        }

        # Check injection triggers
        trigger_result = self._injection_detector.check_triggers(
            step_result=step_result_dict,
            run_state=run_state,
            git_status=git_status,
            verification_result=verification_result,
            file_changes=file_changes,
        )

        if not trigger_result.triggered:
            return None

        if trigger_result.flow_id is None:
            logger.warning(
                "Trigger '%s' fired but no flow_id provided, skipping injection",
                trigger_result.trigger_type,
            )
            return None

        logger.info(
            "Injection trigger '%s' detected at step %s, injecting utility flow '%s'",
            trigger_result.trigger_type,
            step.id,
            trigger_result.flow_id,
        )

        # Inject the utility flow
        injection_result = self._utility_flow_injector.inject_utility_flow(
            flow_id=trigger_result.flow_id,
            run_state=run_state,
            current_node=step.id,
            injection_reason=trigger_result.reason,
            injection_evidence=trigger_result.evidence,
        )

        if not injection_result.injected:
            logger.warning(
                "Failed to inject utility flow '%s': %s",
                trigger_result.flow_id,
                injection_result.error,
            )
            return None

        logger.info(
            "Utility flow '%s' injected: first_node=%s, total_steps=%d",
            trigger_result.flow_id,
            injection_result.first_node_id,
            injection_result.total_steps,
        )

        return injection_result.first_node_id

    def _check_utility_flow_completion(
        self,
        run_state: RunState,
    ) -> Optional[str]:
        """Check if a utility flow has completed and return resume node.

        Implements "return" semantics - when a utility flow with
        on_complete.next_flow="return" completes, this returns the
        node to resume at from the interruption stack.

        This is called after each step to check if:
        1. We're currently executing a utility flow
        2. All utility flow steps have completed
        3. The utility flow specifies "return" behavior

        Args:
            run_state: Current run state.

        Returns:
            Node ID to resume at, or None if no utility flow completion.
        """
        return self._utility_flow_injector.check_utility_flow_completion(run_state)

    def get_utility_flow_registry(self) -> UtilityFlowRegistry:
        """Get the utility flow registry for inspection.

        Returns:
            The UtilityFlowRegistry instance.
        """
        return self._utility_flow_registry


# Backwards compatibility alias
GeminiStepOrchestrator = StepwiseOrchestrator


def get_orchestrator(
    engine: Optional[StepEngine] = None,
    repo_root: Optional[Path] = None,
    use_pack_specs: bool = False,
    skip_preflight: bool = False,
    routing_mode: RoutingMode = RoutingMode.ASSIST,
) -> StepwiseOrchestrator:
    """Factory function to create a stepwise orchestrator.

    Args:
        engine: Optional StepEngine instance. Creates GeminiStepEngine if None.
        repo_root: Optional repository root path.
        use_pack_specs: If True, use pack JSON specs instead of YAML registry.
        skip_preflight: If True, skip preflight environment checks.
            Useful for CI or when environment is known to be valid.
        routing_mode: Controls Navigator behavior. Defaults to ASSIST.
            - DETERMINISTIC_ONLY: No LLM calls, fast-path + config only
            - ASSIST: Fast-path + Navigator chooses among candidates
            - AUTHORITATIVE: Navigator can propose EXTEND_GRAPH freely

    Returns:
        Configured StepwiseOrchestrator instance.
    """
    from swarm.runtime.engines import GeminiStepEngine

    if repo_root is None:
        repo_root = Path(__file__).resolve().parents[3]

    if engine is None:
        engine = GeminiStepEngine(repo_root)

    return StepwiseOrchestrator(
        engine=engine,
        repo_root=repo_root,
        use_pack_specs=use_pack_specs,
        skip_preflight=skip_preflight,
        routing_mode=routing_mode,
    )


__all__ = [
    "FlowExecutionResult",
    "ResolvedNode",
    "StepwiseOrchestrator",
    "GeminiStepOrchestrator",
    "get_orchestrator",
]
