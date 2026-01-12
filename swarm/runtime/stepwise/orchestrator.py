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

import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from swarm.config.flow_registry import (
    FlowDefinition,
    FlowRegistry,
    StepDefinition,
)
from swarm.runtime import storage as storage_module
from swarm.runtime.engines import StepContext, StepEngine


# Macro navigation imports (between-flow routing)
from swarm.runtime.macro_navigator import (
    MacroNavigator,
    extract_flow_result,
)
from swarm.runtime.router import FlowGraph  # For Navigator integration


from swarm.runtime.types import (
    FlowResult,
    InjectedNodeSpec,
    MacroAction,
    MacroRoutingDecision,
    RoutingMode,
    RunEvent,
    RunId,
    RunPlanSpec,
    RunSpec,
    RunState,
    RunStatus,
    SDLCStatus,
    generate_run_id,
)

# Modular stepwise components
from .engine_runner import emit_step_execution_events, run_step as run_step_via_engine
from .envelope import ensure_step_envelope
from .graph_bridge import build_flow_graph_from_definition
from .models import FlowExecutionResult, FlowStepwiseSummary, ResolvedNode
from .node_resolver import resolve_node
from .receipt_compat import update_receipt_routing
from .routing import (
    build_routing_context,
    RoutingOutcome,
    route_step,
)
from .spec_facade import SpecFacade

# Utility flow injection imports
from swarm.runtime.utility_flow_injection import (
    InjectionTriggerDetector,
    TriggerDetectionResult,
    UtilityFlowInjector,
    UtilityFlowRegistry,
)

# Sentinel for unset cached value (distinguishes None from "not computed")
_GIT_STATUS_UNSET = object()

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

        # Git status cache for utility flow detection
        # Cache is per-run (cleared on run completion or can be invalidated)
        self._cached_git_status: Any = _GIT_STATUS_UNSET

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
            # ROUTING DECISION: Single call to unified routing driver
            # =================================================================
            # The routing driver encapsulates all routing strategies:
            # 1. Fast-path (obvious deterministic cases)
            # 2. Deterministic (if DETERMINISTIC_ONLY mode)
            # 3. Navigator (if ASSIST/AUTHORITATIVE)
            # 4. Envelope fallback
            # 5. Escalate (last resort)
            # =================================================================

            routing_outcome = route_step(
                step=step,
                step_result=step_result,
                run_state=run_state,
                loop_state=loop_state,
                iteration=current_iteration,
                routing_mode=self._routing_mode,
                run_id=run_id,
                flow_key=flow_key,
                flow_graph=flow_graph,
                flow_def=flow_def,
                spec=spec,
                run_base=run_base,
                navigation_orchestrator=self._navigation_orchestrator,
                # Utility flow detection inputs
                repo_root=self._repo_root,
                git_status=self._get_git_status(),
            )

            logger.debug(
                "Routing for step %s: next=%s, reason=%s, source=%s",
                step.id,
                routing_outcome.next_step_id,
                routing_outcome.reason,
                routing_outcome.routing_source,
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
                    kind="route_decision",
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
    #
    # Note: Legacy routing methods (_try_fast_path_routing, _route_via_config_fallback,
    # _route_via_navigator, _route_via_envelope_fallback) have been consolidated into
    # the unified routing driver at swarm/runtime/stepwise/routing/driver.py.
    # The orchestrator now calls route_step() for all routing decisions.

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

    # =========================================================================
    # Git Status for Utility Flow Detection
    # =========================================================================

    def _get_git_status(self) -> Optional[Dict[str, Any]]:
        """Get git status for utility flow detection (cached per-run).

        Returns the git status containing divergence information needed for
        utility flow triggers (e.g., upstream_diverged). Results are cached
        to avoid repeated subprocess calls.

        The cache is per-process instance. For multi-run scenarios, call
        invalidate_git_status_cache() between runs if the git state may change.

        Returns:
            Dict with git status fields, or None if unavailable:
            - behind_count: Number of commits behind upstream
            - diverged: Whether branch has diverged from upstream
            - ahead_count: Number of commits ahead of upstream
            - branch: Current branch name
            - upstream: Upstream branch name
        """
        # Return cached value if already computed
        if self._cached_git_status is not _GIT_STATUS_UNSET:
            return self._cached_git_status

        # Skip computation in DETERMINISTIC_ONLY mode (no utility flow injection)
        if self._routing_mode == RoutingMode.DETERMINISTIC_ONLY:
            self._cached_git_status = None
            return None

        try:
            # Local import to avoid circular imports and keep git as optional dep
            import subprocess

            # Get current branch
            branch_result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True,
                text=True,
                cwd=self._repo_root,
                timeout=5,
            )
            if branch_result.returncode != 0:
                logger.debug("git rev-parse failed: %s", branch_result.stderr)
                self._cached_git_status = None
                return None

            branch = branch_result.stdout.strip()

            # Get upstream tracking branch
            upstream_result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", f"{branch}@{{upstream}}"],
                capture_output=True,
                text=True,
                cwd=self._repo_root,
                timeout=5,
            )
            if upstream_result.returncode != 0:
                # No upstream configured - not diverged
                self._cached_git_status = {
                    "branch": branch,
                    "upstream": None,
                    "behind_count": 0,
                    "ahead_count": 0,
                    "diverged": False,
                }
                return self._cached_git_status

            upstream = upstream_result.stdout.strip()

            # Fetch to get latest upstream state (silent, best-effort)
            subprocess.run(
                ["git", "fetch", "--quiet"],
                capture_output=True,
                cwd=self._repo_root,
                timeout=30,
            )

            # Get ahead/behind counts using rev-list
            left_right_result = subprocess.run(
                ["git", "rev-list", "--count", "--left-right", f"{upstream}...HEAD"],
                capture_output=True,
                text=True,
                cwd=self._repo_root,
                timeout=5,
            )
            if left_right_result.returncode != 0:
                logger.debug("git rev-list failed: %s", left_right_result.stderr)
                self._cached_git_status = None
                return None

            counts = left_right_result.stdout.strip().split()
            behind_count = int(counts[0]) if len(counts) > 0 else 0
            ahead_count = int(counts[1]) if len(counts) > 1 else 0

            # Diverged = both behind AND ahead (not just behind)
            diverged = behind_count > 0 and ahead_count > 0

            self._cached_git_status = {
                "branch": branch,
                "upstream": upstream,
                "behind_count": behind_count,
                "ahead_count": ahead_count,
                "diverged": diverged,
            }

            logger.debug(
                "Git status: branch=%s upstream=%s behind=%d ahead=%d diverged=%s",
                branch, upstream, behind_count, ahead_count, diverged,
            )

            return self._cached_git_status

        except subprocess.TimeoutExpired:
            logger.debug("git status check timed out")
            self._cached_git_status = None
            return None
        except FileNotFoundError:
            logger.debug("git command not found")
            self._cached_git_status = None
            return None
        except Exception as e:
            logger.debug("git status unavailable: %s", e)
            self._cached_git_status = None
            return None

    def invalidate_git_status_cache(self) -> None:
        """Invalidate the cached git status.

        Call this between runs or when git state may have changed (e.g., after
        user pulls/merges). The next call to _get_git_status() will recompute.
        """
        self._cached_git_status = _GIT_STATUS_UNSET


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
