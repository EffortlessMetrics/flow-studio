"""
orchestrator.py - GeminiStepOrchestrator for multi-call stepwise flow execution

This module provides an orchestration layer that enables step-by-step flow execution
using the Gemini CLI backend. Unlike the standard backend execution which runs an
entire flow in one call, the orchestrator iterates through each step of a flow,
making separate Gemini CLI calls per step with context handoff between steps.

Design Philosophy:
    - Finer-grained control: Each step is a separate CLI invocation
    - Context continuity: Previous step outputs are included in subsequent prompts
    - Observable execution: Events are logged per-step for debugging
    - Type-safe: Uses existing RunSpec, RunSummary, RunEvent types
    - Spec-first routing: FlowSpec from swarm/spec/flows defines routing

Usage:
    from swarm.runtime.orchestrator import GeminiStepOrchestrator
    from swarm.runtime.backends import GeminiCliBackend
    from swarm.runtime import storage

    backend = GeminiCliBackend()
    orchestrator = GeminiStepOrchestrator(backend, storage)
    run_id = orchestrator.run_stepwise_flow("build", spec)
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from swarm.config.flow_registry import (
    FlowDefinition,
    FlowRegistry,
    StepDefinition,
    StepRouting,
    get_flow_spec_id,
)

from . import storage as storage_module
from .context_pack import ContextPack, build_context_pack
from .engines import (
    FinalizationResult,
    GeminiStepEngine,
    LifecycleCapableEngine,
    RoutingContext,
    StepContext,
    StepEngine,
)
from .flow_loader import EnrichedStepDefinition, enrich_step_definition_with_flow
from .types import (
    RunEvent,
    RunId,
    RunSpec,
    RunStatus,
    RunSummary,
    SDLCStatus,
    RoutingDecision,
    RoutingSignal,
    HandoffEnvelope,
    RunState,
    generate_run_id,
    handoff_envelope_to_dict,
)

# Spec-first imports for FlowSpec routing
try:
    from swarm.spec.loader import load_flow, load_station
    from swarm.spec.types import FlowSpec, RoutingKind, StationSpec
    SPEC_AVAILABLE = True
except ImportError:
    SPEC_AVAILABLE = False
    FlowSpec = None
    RoutingKind = None
    StationSpec = None

# Module logger
logger = logging.getLogger(__name__)


class GeminiStepOrchestrator:
    """Orchestrator for stepwise flow execution using a pluggable StepEngine.

    This class enables multi-call flow execution where each step in a flow
    is executed as a separate LLM invocation. This provides:

    - Finer-grained observability (events per step)
    - Context handoff between steps (previous outputs inform next step)
    - Better error isolation (failures are step-scoped)
    - Teaching mode support (can pause/resume at step boundaries)
    - Engine-agnostic: supports GeminiStepEngine, ClaudeStepEngine, etc.

    The orchestrator coordinates:
    1. Run creation and metadata persistence
    2. Flow definition loading from flow_registry
    3. Per-step context building and engine invocation
    4. Event aggregation into run's events.jsonl

    Attributes:
        _engine: The StepEngine instance for executing steps.
        _repo_root: Root path of the repository.
    """

    def __init__(
        self,
        engine: StepEngine,
        repo_root: Optional[Path] = None,
        use_spec_bridge: bool = False,
    ):
        """Initialize the orchestrator.

        Args:
            engine: StepEngine instance for executing steps.
            repo_root: Repository root path. Defaults to auto-detection.
            use_spec_bridge: If True, load flows from JSON specs (swarm/specs/flows/*.json)
                           instead of YAML registry (swarm/config/flows/*.yaml).
                           This enables "Graph IR is the map" mode.
        """
        self._engine = engine
        self._repo_root = repo_root or Path(__file__).resolve().parents[2]
        self._flow_registry = FlowRegistry.get_instance()
        self._use_spec_bridge = use_spec_bridge
        self._spec_bridge = None
        if use_spec_bridge:
            from swarm.runtime.spec_system.bridge import SpecBridge
            self._spec_bridge = SpecBridge(repo_root=self._repo_root)
        self._lock = threading.Lock()
        # Stop request tracking for graceful interruption
        # Using threading.Event for true cross-thread safety
        self._stop_requests: Dict[RunId, threading.Event] = {}
        # Cache for loaded FlowSpecs (spec-first routing)
        self._flow_spec_cache: Dict[str, Any] = {}
        # Cache for loaded StationSpecs (verification)
        self._station_spec_cache: Dict[str, Any] = {}

    def request_stop(self, run_id: RunId) -> bool:
        """Request graceful stop of a running run.

        The run will:
        1. Complete or abort the current step
        2. Write PARTIAL status to run_state
        3. Emit run_stop_requested event
        4. Save cursor for later resumption

        This is safe to call from any thread (uses threading.Event,
        which is thread-safe unlike asyncio.Event).

        Args:
            run_id: The run to stop.

        Returns:
            True if stop was signaled, False if run not found/not async.
        """
        with self._lock:
            if run_id not in self._stop_requests:
                # Create event for future runs or runs not yet tracked
                self._stop_requests[run_id] = threading.Event()

        self._stop_requests[run_id].set()
        logger.info("Stop requested for run %s", run_id)
        return True

    def clear_stop_request(self, run_id: RunId) -> None:
        """Clear any pending stop request for a run.

        Call this when resuming a run to clear stale stop requests.

        Args:
            run_id: The run to clear stop for.
        """
        if run_id in self._stop_requests:
            self._stop_requests[run_id].clear()

    def _is_stop_requested(self, run_id: RunId) -> bool:
        """Check if stop has been requested for a run.

        Args:
            run_id: The run to check.

        Returns:
            True if stop was requested, False otherwise.
        """
        if run_id not in self._stop_requests:
            return False
        return self._stop_requests[run_id].is_set()

    # =========================================================================
    # SPEC-FIRST ROUTING SUPPORT
    # =========================================================================

    def _load_flow_spec(self, flow_key: str) -> Optional[Any]:
        """Load FlowSpec from swarm/spec/flows/{flow_id}.yaml.

        Uses caching to avoid repeated file I/O.

        Args:
            flow_key: The flow key (e.g., "build", "plan").

        Returns:
            Loaded FlowSpec or None if not available.
        """
        if not SPEC_AVAILABLE:
            logger.debug("Spec module not available, skipping FlowSpec load")
            return None

        if flow_key in self._flow_spec_cache:
            return self._flow_spec_cache[flow_key]

        # Map flow_key to spec flow_id (e.g., "build" -> "3-build")
        flow_id = get_flow_spec_id(flow_key)

        try:
            flow_spec = load_flow(flow_id, self._repo_root)
            self._flow_spec_cache[flow_key] = flow_spec
            logger.debug("Loaded FlowSpec for %s (id=%s)", flow_key, flow_id)
            return flow_spec
        except FileNotFoundError:
            logger.debug("FlowSpec not found for %s", flow_key)
            self._flow_spec_cache[flow_key] = None
            return None
        except Exception as e:
            logger.warning("Failed to load FlowSpec for %s: %s", flow_key, e)
            self._flow_spec_cache[flow_key] = None
            return None

    def _load_station_spec(self, station_id: str) -> Optional[Any]:
        """Load StationSpec from swarm/spec/stations/{station_id}.yaml.

        Uses caching to avoid repeated file I/O.

        Args:
            station_id: The station identifier (e.g., "code-implementer").

        Returns:
            Loaded StationSpec or None if not available.
        """
        if not SPEC_AVAILABLE:
            return None

        if station_id in self._station_spec_cache:
            return self._station_spec_cache[station_id]

        try:
            station_spec = load_station(station_id, self._repo_root)
            self._station_spec_cache[station_id] = station_spec
            logger.debug("Loaded StationSpec for %s", station_id)
            return station_spec
        except FileNotFoundError:
            logger.debug("StationSpec not found for %s", station_id)
            self._station_spec_cache[station_id] = None
            return None
        except Exception as e:
            logger.warning("Failed to load StationSpec for %s: %s", station_id, e)
            self._station_spec_cache[station_id] = None
            return None

    def _get_macro_routing(
        self,
        flow_key: str,
        success: bool,
    ) -> Tuple[Optional[str], str]:
        """Get macro-routing decision from FlowSpec's on_complete/on_failure.

        Args:
            flow_key: The flow that completed.
            success: Whether the flow succeeded.

        Returns:
            Tuple of (next_flow_key or None, reason string).
        """
        flow_spec = self._load_flow_spec(flow_key)
        if flow_spec is None:
            return None, "no_flow_spec"

        # Check FlowSpec for on_complete/on_failure
        # These are optional attributes in FlowSpec YAML
        spec_data = None
        try:
            # Try to read the raw YAML to get on_complete/on_failure
            import yaml
            spec_root = self._repo_root / "swarm" / "spec"
            flow_id = get_flow_spec_id(flow_key)
            flow_path = spec_root / "flows" / f"{flow_id}.yaml"

            if flow_path.exists():
                with open(flow_path, "r", encoding="utf-8") as f:
                    spec_data = yaml.safe_load(f)
        except Exception as e:
            logger.debug("Failed to read FlowSpec YAML for %s: %s", flow_key, e)

        if spec_data is None:
            return None, "no_spec_data"

        if success:
            on_complete = spec_data.get("on_complete", {})
            next_flow = on_complete.get("next_flow")
            reason = on_complete.get("reason", "flow_complete")
            if next_flow:
                return next_flow, reason
        else:
            on_failure = spec_data.get("on_failure", {})
            next_flow = on_failure.get("next_flow")
            reason = on_failure.get("reason", "flow_failed")
            if next_flow:
                return next_flow, reason

        return None, "no_macro_route_defined"

    def _get_spec_step_routing(
        self,
        flow_key: str,
        step_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Get step routing configuration from FlowSpec.

        Args:
            flow_key: The flow key.
            step_id: The step identifier.

        Returns:
            Routing configuration dict or None if not found.
        """
        flow_spec = self._load_flow_spec(flow_key)
        if flow_spec is None:
            return None

        # Find step in FlowSpec
        for step in flow_spec.steps:
            if step.id == step_id:
                routing = step.routing
                return {
                    "kind": routing.kind.value if hasattr(routing.kind, 'value') else str(routing.kind),
                    "next": routing.next,
                    "loop_target": routing.loop_target,
                    "loop_condition_field": routing.loop_condition_field,
                    "loop_success_values": list(routing.loop_success_values),
                    "max_iterations": routing.max_iterations,
                    "branches": dict(routing.branches) if routing.branches else {},
                }

        return None

    # =========================================================================
    # VERIFICATION EXECUTION
    # =========================================================================

    def _run_verification(
        self,
        run_id: RunId,
        flow_key: str,
        step_id: str,
        station_id: str,
        handoff_envelope: HandoffEnvelope,
    ) -> Dict[str, Any]:
        """Run verification checks from station spec's verify block.

        Checks required_artifacts and runs verification_commands.

        Args:
            run_id: The run identifier.
            flow_key: The flow key.
            step_id: The step identifier.
            station_id: The station that executed the step.
            handoff_envelope: The step's handoff envelope.

        Returns:
            Dict with verification results:
            - passed: bool
            - artifact_checks: List of (artifact, exists)
            - command_checks: List of (command, passed, output)
            - gate_status_on_fail: Status to set if verification fails
        """
        result: Dict[str, Any] = {
            "passed": True,
            "artifact_checks": [],
            "command_checks": [],
            "gate_status_on_fail": "UNVERIFIED",
        }

        # Emit verification_started event
        storage_module.append_event(
            run_id,
            RunEvent(
                run_id=run_id,
                ts=datetime.now(timezone.utc),
                kind="verification_started",
                flow_key=flow_key,
                step_id=step_id,
                payload={
                    "station_id": station_id,
                },
            ),
        )

        station_spec = self._load_station_spec(station_id)
        if station_spec is None:
            logger.debug("No StationSpec for %s, skipping verification", station_id)
            # Emit verification_passed (vacuously true)
            storage_module.append_event(
                run_id,
                RunEvent(
                    run_id=run_id,
                    ts=datetime.now(timezone.utc),
                    kind="verification_passed",
                    flow_key=flow_key,
                    step_id=step_id,
                    payload={
                        "station_id": station_id,
                        "reason": "no_station_spec",
                    },
                ),
            )
            return result

        # Get verify block from raw YAML (not in dataclass yet)
        try:
            import yaml
            station_path = self._repo_root / "swarm" / "spec" / "stations" / f"{station_id}.yaml"
            if station_path.exists():
                with open(station_path, "r", encoding="utf-8") as f:
                    station_data = yaml.safe_load(f)
                verify_block = station_data.get("verify", {})
            else:
                verify_block = {}
        except Exception as e:
            logger.debug("Failed to read verify block for %s: %s", station_id, e)
            verify_block = {}

        if not verify_block:
            # Emit verification_passed (vacuously true)
            storage_module.append_event(
                run_id,
                RunEvent(
                    run_id=run_id,
                    ts=datetime.now(timezone.utc),
                    kind="verification_passed",
                    flow_key=flow_key,
                    step_id=step_id,
                    payload={
                        "station_id": station_id,
                        "reason": "no_verify_block",
                    },
                ),
            )
            return result

        result["gate_status_on_fail"] = verify_block.get("gate_status_on_fail", "UNVERIFIED")
        run_base = self._repo_root / "swarm" / "runs" / run_id

        # Check required_artifacts
        required_artifacts = verify_block.get("required_artifacts", [])
        for artifact_path in required_artifacts:
            full_path = run_base / artifact_path
            exists = full_path.exists()
            result["artifact_checks"].append((artifact_path, exists))
            if not exists:
                result["passed"] = False
                logger.debug("Verification failed: artifact missing: %s", artifact_path)

        # Run verification_commands
        required_commands = verify_block.get("required_commands", [])
        for cmd_spec in required_commands:
            if isinstance(cmd_spec, str):
                command = cmd_spec
                success_pattern = None
                timeout_seconds = 60
            else:
                command = cmd_spec.get("command", "")
                success_pattern = cmd_spec.get("success_pattern")
                timeout_seconds = cmd_spec.get("timeout_seconds", 60)

            if not command:
                continue

            # Skip skill-based commands for now (would need skill runner)
            if command in ("test-runner", "auto-linter", "policy-runner"):
                logger.debug("Skipping skill-based verification command: %s", command)
                result["command_checks"].append((command, True, "skipped_skill"))
                continue

            try:
                proc_result = subprocess.run(
                    command,
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=timeout_seconds,
                    cwd=str(self._repo_root),
                )
                output = proc_result.stdout + proc_result.stderr
                passed = proc_result.returncode == 0

                # Check success pattern if specified
                if passed and success_pattern:
                    passed = bool(re.search(success_pattern, output, re.IGNORECASE))

                result["command_checks"].append((command, passed, output[:500]))
                if not passed:
                    result["passed"] = False
                    logger.debug("Verification command failed: %s", command)

            except subprocess.TimeoutExpired:
                result["command_checks"].append((command, False, "timeout"))
                result["passed"] = False
                logger.debug("Verification command timed out: %s", command)
            except Exception as e:
                result["command_checks"].append((command, False, str(e)))
                result["passed"] = False
                logger.debug("Verification command error: %s: %s", command, e)

        # Emit verification_passed or verification_failed
        if result["passed"]:
            storage_module.append_event(
                run_id,
                RunEvent(
                    run_id=run_id,
                    ts=datetime.now(timezone.utc),
                    kind="verification_passed",
                    flow_key=flow_key,
                    step_id=step_id,
                    payload={
                        "station_id": station_id,
                        "artifact_checks": result["artifact_checks"],
                        "command_checks": [
                            (c, p, o[:100]) for c, p, o in result["command_checks"]
                        ],
                    },
                ),
            )
        else:
            storage_module.append_event(
                run_id,
                RunEvent(
                    run_id=run_id,
                    ts=datetime.now(timezone.utc),
                    kind="verification_failed",
                    flow_key=flow_key,
                    step_id=step_id,
                    payload={
                        "station_id": station_id,
                        "gate_status_on_fail": result["gate_status_on_fail"],
                        "artifact_checks": result["artifact_checks"],
                        "command_checks": [
                            (c, p, o[:100]) for c, p, o in result["command_checks"]
                        ],
                    },
                ),
            )

        return result

    # =========================================================================
    # FLOW EXECUTION METHODS
    # =========================================================================

    def run_stepwise_flow(
        self,
        flow_key: str,
        spec: RunSpec,
        start_step: Optional[str] = None,
        end_step: Optional[str] = None,
        resume: bool = False,
    ) -> RunId:
        """Execute a flow step-by-step, one Gemini CLI call per step.

        Creates a new run, iterates through flow steps, and calls the Gemini
        CLI for each step with accumulated context from previous steps.

        Args:
            flow_key: The flow to execute (e.g., "build", "plan").
            spec: Run specification with params and initiator info.
            start_step: Optional step ID to start from (skip earlier steps).
            end_step: Optional step ID to stop at (skip later steps).
            resume: Whether to resume from existing run_state.json.

        Returns:
            The generated run ID.

        Raises:
            ValueError: If flow_key is invalid or has no steps defined.
        """
        # Validate flow exists - use spec bridge if enabled, otherwise YAML registry
        if self._use_spec_bridge and self._spec_bridge:
            flow_def = self._spec_bridge.get_flow(flow_key)
            if not flow_def:
                raise ValueError(f"Unknown flow (spec bridge): {flow_key}")
        else:
            flow_def = self._flow_registry.get_flow(flow_key)
            if not flow_def:
                raise ValueError(f"Unknown flow: {flow_key}")

        if not flow_def.steps:
            raise ValueError(f"Flow '{flow_key}' has no steps defined")

        # Create run
        run_id = generate_run_id()
        now = datetime.now(timezone.utc)

        # Ensure flow_keys includes our flow
        flow_keys = spec.flow_keys if spec.flow_keys else [flow_key]
        if flow_key not in flow_keys:
            flow_keys = [flow_key] + list(flow_keys)

        # Create updated spec with flow_keys, preserving the backend ID
        run_spec = RunSpec(
            flow_keys=flow_keys,
            profile_id=spec.profile_id,
            backend=spec.backend,
            initiator=spec.initiator,
            params={**spec.params, "stepwise": True, "resume": resume},
        )

        # Persist initial state
        storage_module.create_run_dir(run_id)
        storage_module.write_spec(run_id, run_spec)

        # Initialize or load run state
        if resume:
            # Try to load existing run state for resumption
            existing_state = storage_module.read_run_state(run_id)
            if existing_state and existing_state.flow_key == flow_key:
                # Resume from saved state
                run_state = existing_state
                logger.info("Resuming run %s from step %s", run_id, existing_state.current_step_id)
            else:
                # Create fresh state if resume requested but no valid state found
                run_state = RunState(
                    run_id=run_id,
                    flow_key=flow_key,
                    status="running",
                    timestamp=datetime.now(timezone.utc),
                )
                storage_module.write_run_state(run_id, run_state)
        else:
            # Create fresh run state
            run_state = RunState(
                run_id=run_id,
                flow_key=flow_key,
                status="pending",
                timestamp=datetime.now(timezone.utc),
            )
            storage_module.write_run_state(run_id, run_state)

        summary = RunSummary(
            id=run_id,
            spec=run_spec,
            status=RunStatus.PENDING,
            sdlc_status=SDLCStatus.UNKNOWN,
            created_at=now,
            updated_at=now,
        )
        storage_module.write_summary(run_id, summary)

        # Log run creation
        storage_module.append_event(
            run_id,
            RunEvent(
                run_id=run_id,
                ts=now,
                kind="run_created",
                flow_key=flow_key,
                payload={
                    "flows": flow_keys,
                    "backend": spec.backend,
                    "initiator": spec.initiator,
                    "stepwise": True,
                },
            ),
        )

        # Execute in background thread
        thread = threading.Thread(
            target=self._execute_stepwise,
            args=(run_id, flow_key, flow_def, run_spec, run_state, start_step, end_step),
            daemon=True,
        )
        thread.start()

        return run_id

    def _execute_stepwise(
        self,
        run_id: RunId,
        flow_key: str,
        flow_def: FlowDefinition,
        spec: RunSpec,
        run_state: RunState,
        start_step: Optional[str],
        end_step: Optional[str],
    ) -> None:
        """Execute the stepwise flow in a background thread.

        Uses routing configuration to determine step traversal, supporting:
        - Linear progression between steps
        - Microloop patterns (author/critic iteration)
        - Branch routing based on step results

        Args:
            run_id: The run identifier.
            flow_key: The flow being executed.
            flow_def: The flow definition with steps.
            spec: The run specification.
            start_step: Optional step ID to start from.
            end_step: Optional step ID to stop at.
        """
        now = datetime.now(timezone.utc)

        # Update status to running
        storage_module.update_summary(run_id, {
            "status": RunStatus.RUNNING.value,
            "started_at": now.isoformat(),
            "updated_at": now.isoformat(),
        })

        storage_module.append_event(
            run_id,
            RunEvent(
                run_id=run_id,
                ts=now,
                kind="run_started",
                flow_key=flow_key,
                payload={"mode": "stepwise", "routing_enabled": True, "resume": run_state.current_step_id is not None},
            ),
        )

        # Update run state to running
        storage_module.update_run_state(run_id, {"status": "running"})

        # Determine starting step
        if start_step:
            current_step = self._get_step_by_id(flow_def, start_step)
            if not current_step:
                # Fall back to first step
                current_step = flow_def.steps[0] if flow_def.steps else None
        elif run_state.current_step_id:
            # Resume from saved step
            current_step = self._get_step_by_id(flow_def, run_state.current_step_id)
            if not current_step:
                # Fall back to first step if saved step not found
                current_step = flow_def.steps[0] if flow_def.steps else None
        else:
            current_step = flow_def.steps[0] if flow_def.steps else None

        # Restore loop state from saved state
        loop_state = dict(run_state.loop_state)

        error_msg = None
        final_status = RunStatus.SUCCEEDED
        sdlc_status = SDLCStatus.OK

        # Track step history for context building
        step_history: List[Dict[str, Any]] = []

        # Reconstruct step history from saved handoff envelopes
        for step_id, envelope in run_state.handoff_envelopes.items():
            step_history.append({
                "step_id": envelope.step_id,
                "status": envelope.status,
                "output": envelope.summary,
            })

        # Track total steps executed for safety limit
        total_steps_executed = 0
        max_total_steps = len(flow_def.steps) * 10  # Safety limit

        try:
            while current_step is not None:
                # Safety limit check
                total_steps_executed += 1
                if total_steps_executed > max_total_steps:
                    logger.error(
                        "Safety limit reached: %d steps executed, aborting",
                        total_steps_executed,
                    )
                    final_status = RunStatus.FAILED
                    sdlc_status = SDLCStatus.ERROR
                    error_msg = f"Safety limit reached: {total_steps_executed} steps"
                    break

                # Build routing context for microloop metadata
                routing_ctx = self._build_routing_context(current_step, loop_state)

                # Execute the current step (pass run_state for context pack)
                step_result = self._execute_single_step(
                    run_id=run_id,
                    flow_key=flow_key,
                    flow_def=flow_def,
                    step=current_step,
                    spec=spec,
                    history=step_history,
                    routing_ctx=routing_ctx,
                    run_state=run_state,
                )

                # Add to history for next step's context
                step_history.append(step_result)

                # =======================================================
                # ROUTING LIFT: Prefer engine's handoff/routing when available
                # =======================================================
                # Priority order for handoff envelope:
                # 1. Engine's handoff_envelope (from lifecycle-capable engines)
                # 2. Create new envelope with orchestrator-generated routing
                #
                # Priority order for routing signal:
                # 1. Engine's routing_signal (from lifecycle-capable engines)
                # 2. Orchestrator's _create_routing_signal() (deterministic fallback)
                # =======================================================

                # Check if lifecycle-capable engine already provided envelope
                if "handoff_envelope" in step_result and step_result["handoff_envelope"]:
                    handoff_envelope = step_result["handoff_envelope"]
                    logger.debug(
                        "Using engine-provided handoff envelope for step %s",
                        current_step.id,
                    )
                    # Engine's envelope may not have routing_signal yet - add it
                    if handoff_envelope.routing_signal is None:
                        if "routing_signal" in step_result and step_result["routing_signal"]:
                            handoff_envelope.routing_signal = step_result["routing_signal"]
                        else:
                            handoff_envelope.routing_signal = self._create_routing_signal(
                                current_step, step_result, loop_state
                            )
                else:
                    # Create new envelope - prefer engine's routing signal
                    routing_signal = step_result.get("routing_signal")
                    if routing_signal is None:
                        routing_signal = self._create_routing_signal(
                            current_step, step_result, loop_state
                        )

                    handoff_envelope = HandoffEnvelope(
                        step_id=current_step.id,
                        flow_key=flow_key,
                        run_id=run_id,
                        routing_signal=routing_signal,
                        summary=step_result.get("output", "")[:2000],  # Limit to 2k chars
                        status=step_result.get("status", "succeeded"),
                        error=step_result.get("error"),
                        duration_ms=step_result.get("duration_ms", 0),
                        timestamp=datetime.now(timezone.utc),
                    )

                # =========================================================
                # VERIFICATION: Run verification from station spec
                # =========================================================
                # Get station ID from step (for FlowSpec, station is explicit)
                station_id = None
                flow_spec = self._load_flow_spec(flow_key)
                if flow_spec:
                    for spec_step in flow_spec.steps:
                        if spec_step.id == current_step.id:
                            station_id = spec_step.station
                            break

                if station_id:
                    verification_result = self._run_verification(
                        run_id=run_id,
                        flow_key=flow_key,
                        step_id=current_step.id,
                        station_id=station_id,
                        handoff_envelope=handoff_envelope,
                    )

                    # Update handoff envelope with verification results
                    handoff_envelope.verification_passed = verification_result["passed"]
                    handoff_envelope.verification_details = {
                        "artifact_checks": verification_result["artifact_checks"],
                        "command_checks": [
                            (c, p, o[:100]) for c, p, o in verification_result.get("command_checks", [])
                        ],
                        "gate_status_on_fail": verification_result.get("gate_status_on_fail", "UNVERIFIED"),
                    }
                    handoff_envelope.station_id = station_id

                # Store handoff envelope in run state (in-memory for next step's context)
                run_state.handoff_envelopes[current_step.id] = handoff_envelope

                # =========================================================
                # ATOMIC COMMIT: Use commit_step_completion for crash safety
                # =========================================================
                # This ensures envelope is written to disk before run_state is
                # updated. On crash recovery, we can reconstruct run_state from
                # envelope files on disk.
                storage_module.commit_step_completion(
                    run_id=run_id,
                    flow_key=flow_key,
                    envelope=handoff_envelope,
                    run_state_updates={
                        "current_step_id": current_step.id,
                        "step_index": current_step.index,
                        "loop_state": dict(loop_state),
                        "status": "running",
                    },
                )

                # Check for step failure
                if step_result.get("status") == "failed":
                    final_status = RunStatus.FAILED
                    sdlc_status = SDLCStatus.ERROR
                    error_msg = step_result.get("error", f"Step {current_step.id} failed")
                    break

                # Check end_step condition
                if end_step and current_step.id == end_step:
                    logger.info("Reached end_step %s, stopping execution", end_step)
                    break

                # Route to next step using RoutingSignal from handoff envelope
                next_step_id, route_reason = self._route(
                    flow_def=flow_def,
                    current_step=current_step,
                    result=step_result,
                    loop_state=loop_state,
                    run_id=run_id,
                    flow_key=flow_key,
                    handoff_envelope=handoff_envelope,
                )

                # Update routing context with decision and update receipt
                if routing_ctx:
                    routing_ctx.reason = route_reason
                    routing = current_step.routing
                    if next_step_id is None:
                        routing_ctx.decision = "terminate"
                    elif routing and routing.loop_target and next_step_id == routing.loop_target:
                        routing_ctx.decision = "loop"
                    else:
                        routing_ctx.decision = "advance"

                    agent_key = current_step.agents[0] if current_step.agents else "unknown"
                    self._update_receipt_routing(
                        run_id, flow_key, current_step.id, agent_key, routing_ctx
                    )

                # Emit routing decision event with routing signal details
                storage_module.append_event(
                    run_id,
                    RunEvent(
                        run_id=run_id,
                        ts=datetime.now(timezone.utc),
                        kind="route_decision",
                        flow_key=flow_key,
                        step_id=current_step.id,
                        payload={
                            "from_step": current_step.id,
                            "to_step": next_step_id,
                            "reason": route_reason,
                            "loop_state": dict(loop_state),
                            "decision": routing_ctx.decision if routing_ctx else "unknown",
                            "confidence": handoff_envelope.routing_signal.confidence,
                            "needs_human": handoff_envelope.routing_signal.needs_human,
                        },
                    ),
                )

                if next_step_id is None:
                    # Flow complete
                    logger.info("Flow complete: %s", route_reason)
                    break

                # Get the next step definition
                current_step = self._get_step_by_id(flow_def, next_step_id)
                if current_step is None:
                    logger.error("Next step '%s' not found in flow", next_step_id)
                    final_status = RunStatus.FAILED
                    sdlc_status = SDLCStatus.ERROR
                    error_msg = f"Invalid routing: step '{next_step_id}' not found"
                    break

        except Exception as e:
            logger.exception("Error in stepwise execution for run %s", run_id)
            final_status = RunStatus.FAILED
            sdlc_status = SDLCStatus.ERROR
            error_msg = str(e)

        # =========================================================
        # MACRO-ROUTING: Check on_complete/on_failure for flow transition
        # =========================================================
        flow_succeeded = (final_status == RunStatus.SUCCEEDED)
        next_flow_key, macro_reason = self._get_macro_routing(flow_key, flow_succeeded)

        if next_flow_key:
            # Emit macro_route event
            storage_module.append_event(
                run_id,
                RunEvent(
                    run_id=run_id,
                    ts=datetime.now(timezone.utc),
                    kind="macro_route",
                    flow_key=flow_key,
                    payload={
                        "from_flow": flow_key,
                        "to_flow": next_flow_key,
                        "reason": macro_reason,
                        "flow_succeeded": flow_succeeded,
                        "loop_count": 0,
                    },
                ),
            )
            logger.info(
                "Macro-route: %s -> %s (reason: %s)",
                flow_key, next_flow_key, macro_reason,
            )

        # Update flow transition history in run state
        run_state.flow_transition_history.append({
            "from_flow": flow_key,
            "to_flow": next_flow_key,
            "reason": macro_reason,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "flow_succeeded": flow_succeeded,
        })

        # Update final status
        completed_at = datetime.now(timezone.utc)
        storage_module.update_summary(run_id, {
            "status": final_status.value,
            "sdlc_status": sdlc_status.value,
            "completed_at": completed_at.isoformat(),
            "updated_at": completed_at.isoformat(),
            "error": error_msg,
        })

        storage_module.append_event(
            run_id,
            RunEvent(
                run_id=run_id,
                ts=completed_at,
                kind="run_completed",
                flow_key=flow_key,
                payload={
                    "status": final_status.value,
                    "error": error_msg,
                    "steps_completed": len(step_history),
                    "total_steps_executed": total_steps_executed,
                    "loop_state_final": dict(loop_state),
                    "next_flow": next_flow_key,
                    "macro_route_reason": macro_reason,
                    "flow_transition_history": run_state.flow_transition_history,
                },
            ),
        )

    def _filter_steps(
        self,
        steps: Tuple[StepDefinition, ...],
        start_step: Optional[str],
        end_step: Optional[str],
    ) -> List[StepDefinition]:
        """Filter steps to the requested range.

        Args:
            steps: Tuple of all step definitions in the flow.
            start_step: Optional step ID to start from (inclusive).
            end_step: Optional step ID to stop at (inclusive).

        Returns:
            List of steps to execute.
        """
        result = list(steps)

        if start_step:
            # Find start index
            start_idx = None
            for i, step in enumerate(result):
                if step.id == start_step:
                    start_idx = i
                    break
            if start_idx is not None:
                result = result[start_idx:]

        if end_step:
            # Find end index
            end_idx = None
            for i, step in enumerate(result):
                if step.id == end_step:
                    end_idx = i
                    break
            if end_idx is not None:
                result = result[: end_idx + 1]

        return result

    def _get_step_by_id(
        self,
        flow_def: FlowDefinition,
        step_id: str,
    ) -> Optional[StepDefinition]:
        """Find a step by ID in the flow definition.

        Args:
            flow_def: The flow definition containing steps.
            step_id: The step ID to find.

        Returns:
            The StepDefinition if found, None otherwise.
        """
        for step in flow_def.steps:
            if step.id == step_id:
                return step
        return None

    def _read_receipt_field(
        self,
        run_id: str,
        flow_key: str,
        step_id: str,
        agent_key: str,
        field_name: str,
    ) -> Optional[str]:
        """Read a field from a step's receipt file.

        This method provides backward compatibility with receipt-based routing
        while we transition to RoutingSignal-based routing via handoff envelopes.

        Args:
            run_id: The run identifier.
            flow_key: The flow key (e.g., "build").
            step_id: The step identifier.
            agent_key: The agent key.
            field_name: The field to read from the receipt.

        Returns:
            The field value as a string, or None if not found.
        """
        run_base = self._repo_root / "swarm" / "runs" / run_id / flow_key
        receipt_path = run_base / "receipts" / f"{step_id}-{agent_key}.json"

        if not receipt_path.exists():
            logger.debug("Receipt not found: %s", receipt_path)
            return None

        try:
            with open(receipt_path) as f:
                receipt = json.load(f)
            value = receipt.get(field_name)
            if value is not None:
                return str(value)
            return None
        except Exception as e:
            logger.debug("Failed to read receipt field %s: %s", field_name, e)
            return None

    def _create_routing_signal(
        self,
        step: StepDefinition,
        result: Dict[str, Any],
        loop_state: Dict[str, int],
    ) -> RoutingSignal:
        """Create a RoutingSignal from step result and routing config.

        Uses spec-first routing when FlowSpec is available, otherwise
        falls back to config-based routing.

        Args:
            step: The step that was executed.
            result: The step execution result dictionary.
            loop_state: Dictionary tracking iteration counts per microloop.

        Returns:
            A RoutingSignal with the routing decision.
        """
        # =========================================================
        # SPEC-FIRST ROUTING: Try FlowSpec first
        # =========================================================
        flow_key = result.get("flow_key", "")
        spec_routing = self._get_spec_step_routing(flow_key, step.id) if flow_key else None

        if spec_routing:
            return self._create_routing_signal_from_spec(
                step, result, loop_state, spec_routing
            )

        # =========================================================
        # FALLBACK: Config-based routing
        # =========================================================
        routing = step.routing

        # Default routing signal - advance to next step
        decision = RoutingDecision.ADVANCE
        next_step_id = None
        reason = "step_complete"
        confidence = 1.0
        needs_human = False

        if routing is None:
            # No routing config: fall back to linear progression
            # Find next step by index
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
            # Check loop iteration count
            loop_key = f"{step.id}:{routing.loop_target}"
            current_iter = loop_state.get(loop_key, 0)

            # Safety check: max iterations
            if current_iter >= routing.max_iterations:
                if routing.next:
                    next_step_id = routing.next
                    reason = f"max_iterations_reached:{routing.max_iterations}"
                else:
                    decision = RoutingDecision.TERMINATE
                    reason = f"flow_complete_max_iterations:{routing.max_iterations}"

            # Check loop condition from receipt (will be replaced by RoutingSignal in future)
            if routing.loop_condition_field:
                agent_key = step.agents[0] if step.agents else "unknown"
                field_value = self._read_receipt_field(
                    result.get("run_id", ""),
                    result.get("flow_key", ""),
                    step.id,
                    agent_key,
                    routing.loop_condition_field
                )

                if field_value and field_value in routing.loop_success_values:
                    # Condition met, exit loop
                    if routing.next:
                        next_step_id = routing.next
                        reason = f"loop_exit_condition_met:{field_value}"
                    else:
                        decision = RoutingDecision.TERMINATE
                        reason = f"flow_complete_condition_met:{field_value}"

                # Check can_further_iteration_help field as fallback
                can_iterate = self._read_receipt_field(
                    result.get("run_id", ""),
                    result.get("flow_key", ""),
                    step.id,
                    agent_key,
                    "can_further_iteration_help"
                )
                if can_iterate and can_iterate.lower() == "no":
                    # Critic says no further iteration will help
                    if routing.next:
                        next_step_id = routing.next
                        reason = "loop_exit_no_further_help"
                    else:
                        decision = RoutingDecision.TERMINATE
                        reason = "flow_complete_no_further_help"

            # Loop back to target
            if next_step_id is None and routing.loop_target:
                next_step_id = routing.loop_target
                reason = f"loop_iteration:{current_iter + 1}"
                decision = RoutingDecision.LOOP

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

        return RoutingSignal(
            decision=decision,
            next_step_id=next_step_id,
            reason=reason,
            confidence=confidence,
            needs_human=needs_human,
        )

    def _create_routing_signal_from_spec(
        self,
        step: StepDefinition,
        result: Dict[str, Any],
        loop_state: Dict[str, int],
        spec_routing: Dict[str, Any],
    ) -> RoutingSignal:
        """Create a RoutingSignal using FlowSpec routing configuration.

        Supports routing kinds: linear, microloop, branch, terminal.
        Supports exit_on conditions for microloops.

        Args:
            step: The step that was executed.
            result: The step execution result dictionary.
            loop_state: Dictionary tracking iteration counts per microloop.
            spec_routing: Routing configuration from FlowSpec.

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
            decision = RoutingDecision.TERMINATE
            reason = "terminal_step"
            return RoutingSignal(
                decision=decision,
                next_step_id=None,
                reason=reason,
                confidence=confidence,
                needs_human=needs_human,
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

            # Check exit_on conditions from FlowSpec YAML
            flow_key = result.get("flow_key", "")
            exit_on = self._get_spec_exit_on(flow_key, step.id)

            if exit_on:
                # Check status condition
                status_values = exit_on.get("status", [])
                step_status = result.get("status", "")
                if status_values and step_status in status_values:
                    exit_condition_met = True
                    reason = f"exit_on_status:{step_status}"

                # Check can_further_iteration_help condition
                if exit_on.get("can_further_iteration_help") is False:
                    agent_key = step.agents[0] if step.agents else "unknown"
                    can_iterate = self._read_receipt_field(
                        result.get("run_id", ""),
                        flow_key,
                        step.id,
                        agent_key,
                        "can_further_iteration_help"
                    )
                    if can_iterate and can_iterate.lower() == "no":
                        exit_condition_met = True
                        reason = "exit_on_no_further_help"

            # Check max iterations
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

        return RoutingSignal(
            decision=decision,
            next_step_id=next_step_id,
            reason=reason,
            confidence=confidence,
            needs_human=needs_human,
            loop_count=loop_count,
            exit_condition_met=exit_condition_met,
        )

    def _get_spec_exit_on(
        self,
        flow_key: str,
        step_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Get exit_on conditions from FlowSpec step routing.

        Args:
            flow_key: The flow key.
            step_id: The step identifier.

        Returns:
            Dict with exit_on conditions or None.
        """
        try:
            import yaml
            spec_root = self._repo_root / "swarm" / "spec"
            flow_id = get_flow_spec_id(flow_key)
            flow_path = spec_root / "flows" / f"{flow_id}.yaml"

            if not flow_path.exists():
                return None

            with open(flow_path, "r", encoding="utf-8") as f:
                spec_data = yaml.safe_load(f)

            for step in spec_data.get("steps", []):
                if step.get("id") == step_id:
                    routing = step.get("routing", {})
                    return routing.get("exit_on")

            return None
        except Exception as e:
            logger.debug("Failed to read exit_on for %s/%s: %s", flow_key, step_id, e)
            return None

    def _route(
        self,
        flow_def: FlowDefinition,
        current_step: StepDefinition,
        result: Dict[str, Any],
        loop_state: Dict[str, int],
        run_id: RunId,
        flow_key: str,
        handoff_envelope: Optional[HandoffEnvelope] = None,
    ) -> Tuple[Optional[str], str]:
        """Determine the next step based on routing config and result.

        Supports three routing patterns:
        - linear: Simple sequential flow to the next step
        - microloop: Loops back to a target step until a condition is met
        - branch: Chooses next step based on result values

        When a HandoffEnvelope is provided, uses its RoutingSignal for routing
        decisions. Otherwise, falls back to receipt-based routing for backward
        compatibility.

        Args:
            flow_def: The flow definition with all steps.
            current_step: The step that just completed.
            result: The step execution result dictionary.
            loop_state: Dictionary tracking iteration counts per step.
            run_id: The run identifier (for reading receipts).
            flow_key: The flow key (for reading receipts).
            handoff_envelope: Optional HandoffEnvelope with routing signal.
                If provided, uses its RoutingSignal for routing decisions.

        Returns:
            Tuple of (next_step_id or None if flow is complete, reason string).
        """
        routing = current_step.routing

        # =========================================================
        # ROUTING SIGNAL PATH: Use handoff envelope if available
        # =========================================================
        # This is the preferred path - uses the RoutingSignal from the
        # handoff envelope instead of parsing receipts.
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

            # If signal didn't provide a clear path, log and fall through
            logger.debug(
                "RoutingSignal did not resolve routing for step %s (decision=%s), falling back",
                current_step.id,
                signal.decision,
            )

        # =========================================================
        # FALLBACK PATH: Receipt-based routing (backward compatibility)
        # =========================================================

        # No routing config: fall back to linear progression
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
            # Check loop iteration count
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
            if routing.loop_condition_field:
                agent_key = current_step.agents[0] if current_step.agents else "unknown"
                field_value = self._read_receipt_field(
                    run_id, flow_key, current_step.id, agent_key, routing.loop_condition_field
                )

                if field_value and field_value in routing.loop_success_values:
                    # Condition met, exit loop
                    if routing.next:
                        return routing.next, f"loop_exit_condition_met:{field_value}"
                    return None, f"flow_complete_condition_met:{field_value}"

                # Check can_further_iteration_help field as fallback
                can_iterate = self._read_receipt_field(
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

    def _build_routing_context(
        self,
        current_step: StepDefinition,
        loop_state: Dict[str, int],
    ) -> Optional["RoutingContext"]:
        """Build routing context for inclusion in receipts.

        Args:
            current_step: The step being executed.
            loop_state: Dictionary tracking iteration counts per microloop.

        Returns:
            RoutingContext if the step has microloop routing, None otherwise.
        """
        from .engines import RoutingContext

        routing = current_step.routing
        if routing is None or routing.kind != "microloop":
            return None

        loop_key = f"{current_step.id}:{routing.loop_target}"
        current_iter = loop_state.get(loop_key, 0)

        return RoutingContext(
            loop_iteration=current_iter,
            max_iterations=routing.max_iterations,
            decision="pending",
            reason="",
        )

    def _update_receipt_routing(
        self,
        run_id: str,
        flow_key: str,
        step_id: str,
        agent_key: str,
        routing_ctx: "RoutingContext",
    ) -> None:
        """Update receipt with final routing decision.

        Args:
            run_id: The run identifier.
            flow_key: The flow key.
            step_id: The step identifier.
            agent_key: The agent key.
            routing_ctx: The routing context with decision info.
        """
        run_base = self._repo_root / "swarm" / "runs" / run_id / flow_key
        receipt_path = run_base / "receipts" / f"{step_id}-{agent_key}.json"

        if not receipt_path.exists():
            return

        try:
            import json
            with open(receipt_path) as f:
                receipt = json.load(f)

            receipt["routing"] = {
                "loop_iteration": routing_ctx.loop_iteration,
                "max_iterations": routing_ctx.max_iterations,
                "decision": routing_ctx.decision,
                "reason": routing_ctx.reason,
            }

            with open(receipt_path, "w") as f:
                json.dump(receipt, f, indent=2)
        except Exception:
            pass  # Graceful failure

    def _read_receipt_field(
        self,
        run_id: str,
        flow_key: str,
        step_id: str,
        agent_key: str,
        field_name: str,
    ) -> Optional[str]:
        """Read a specific field from a receipt file.

        Used by the _route method to extract receipt fields for routing decisions.

        Args:
            run_id: The run identifier.
            flow_key: The flow key (e.g., "build").
            step_id: The step identifier.
            agent_key: The agent key.
            field_name: The field to extract from the receipt.

        Returns:
            The field value as a string if found, None otherwise.
        """
        from swarm.runtime.resolvers import read_receipt_field
        return read_receipt_field(
            self._repo_root, run_id, flow_key, step_id, agent_key, field_name
        )

    def _execute_single_step(
        self,
        run_id: RunId,
        flow_key: str,
        flow_def: FlowDefinition,
        step: StepDefinition,
        spec: RunSpec,
        history: List[Dict[str, Any]],
        routing_ctx: Optional["RoutingContext"] = None,
        run_state: Optional[RunState] = None,
    ) -> Dict[str, Any]:
        """Execute a single step via the configured StepEngine.

        Builds a StepContext including previous step outputs, delegates to the
        engine, persists emitted events, and returns a dict suitable for
        inclusion in subsequent step history.

        This method implements a four-phase execution model:
        1. Hydration: Build ContextPack with upstream artifacts and envelopes
        2. Enrichment: Load prompts via EnrichedStepDefinition
        3. Execution: Delegate to engine with enriched context
        4. Finalization: Engine produces HandoffEnvelope (JIT finalization)

        Args:
            run_id: The run identifier.
            flow_key: The flow being executed.
            flow_def: The flow definition.
            step: The step to execute.
            spec: The run specification.
            history: List of previous step results for context.
            routing_ctx: Optional routing context for microloop metadata.
            run_state: Optional RunState for building context pack with
                in-memory handoff envelopes.

        Returns:
            Dictionary with step execution result:
            - step_id: The step ID
            - status: "succeeded" or "failed"
            - error: Error message if failed
            - output: Summary of step output
            - run_id: The run identifier (for routing)
            - flow_key: The flow key (for routing)
        """
        step_start = datetime.now(timezone.utc)

        # Log step start (orchestrator-level event)
        storage_module.append_event(
            run_id,
            RunEvent(
                run_id=run_id,
                ts=step_start,
                kind="step_start",
                flow_key=flow_key,
                step_id=step.id,
                agent_key=step.agents[0] if step.agents else None,
                payload={
                    "role": step.role,
                    "agents": list(step.agents),
                    "step_index": step.index,
                    "engine": self._engine.engine_id,
                },
            ),
        )

        result: Dict[str, Any] = {
            "step_id": step.id,
            "step_index": step.index,
            "agents": list(step.agents),
            "started_at": step_start.isoformat(),
            "run_id": run_id,
            "flow_key": flow_key,
        }

        status = "failed"
        error: Optional[str] = None
        output = ""
        duration_ms = 0

        try:
            # Build step execution context for the engine
            ctx = StepContext(
                repo_root=self._repo_root,
                run_id=run_id,
                flow_key=flow_key,
                step_id=step.id,
                step_index=step.index,
                total_steps=len(flow_def.steps),
                spec=spec,
                flow_title=flow_def.title,
                step_role=step.role,
                step_agents=tuple(step.agents),
                history=history,
                extra={},
                teaching_notes=step.teaching_notes,
                routing=routing_ctx,
            )

            # =========================================================
            # PHASE 1: Hydration - Build ContextPack
            # =========================================================
            # The ContextPack consolidates upstream artifacts and previous
            # handoff envelopes for this step's context.
            context_pack = build_context_pack(ctx, run_state, self._repo_root)

            logger.debug(
                "Built context pack for step %s: %d artifacts, %d prior envelopes",
                step.id,
                len(context_pack.upstream_artifacts),
                len(context_pack.previous_envelopes),
            )

            # =========================================================
            # PHASE 2: Enrichment - Load Prompts
            # =========================================================
            # EnrichedStepDefinition adds orchestrator and agent prompts
            # from swarm/prompts/ and .claude/agents/ directories.
            enriched_step = enrich_step_definition_with_flow(
                step, flow_key, self._repo_root
            )

            # Store enriched prompts in extra for engine access
            ctx.extra["orchestrator_prompt"] = enriched_step.orchestrator_prompt
            ctx.extra["agent_prompts"] = enriched_step.agent_prompts
            ctx.extra["context_pack"] = context_pack

            # Add routing config to extra for lifecycle-capable engines
            if step.routing:
                ctx.extra["routing"] = {
                    "kind": step.routing.kind,
                    "next": step.routing.next,
                    "loop_target": step.routing.loop_target,
                    "loop_condition_field": step.routing.loop_condition_field,
                    "loop_success_values": list(step.routing.loop_success_values),
                    "max_iterations": step.routing.max_iterations,
                }

            # =========================================================
            # PHASE 3: Execution - Delegate to Engine
            # =========================================================
            # Check if engine supports explicit lifecycle control
            if isinstance(self._engine, LifecycleCapableEngine):
                # LIFECYCLE-CAPABLE ENGINE: Explicit phase control
                # This path gives the orchestrator control over when
                # finalization and routing happen.
                logger.debug(
                    "Using lifecycle-capable engine for step %s",
                    step.id,
                )

                # Phase 3a: Work - Execute the step's primary task
                step_result, work_events, work_summary = self._engine.run_worker(ctx)

                # Persist work phase events
                for event in work_events:
                    storage_module.append_event(run_id, event)

                # Phase 3b: Finalization - Extract handoff state
                finalization_result = self._engine.finalize_step(
                    ctx, step_result, work_summary
                )

                # Persist finalization events
                for event in finalization_result.events:
                    storage_module.append_event(run_id, event)

                # Phase 3c: Routing - Determine next step
                routing_signal: Optional[RoutingSignal] = None
                if finalization_result.handoff_data:
                    routing_signal = self._engine.route_step(
                        ctx, finalization_result.handoff_data
                    )

                    # Store routing signal in result for _execute_stepwise
                    if routing_signal:
                        result["routing_signal"] = routing_signal

                # Store envelope in result for later use
                if finalization_result.envelope:
                    result["handoff_envelope"] = finalization_result.envelope

                status = step_result.status
                error = step_result.error
                output = step_result.output
                duration_ms = step_result.duration_ms

            else:
                # LEGACY ENGINE: Monolithic run_step() call
                # The engine handles finalization and routing internally
                # (or relies on orchestrator-generated routing).
                step_result, engine_events = self._engine.run_step(ctx)

                # Persist engine-emitted events
                for event in engine_events:
                    storage_module.append_event(run_id, event)

                status = step_result.status
                error = step_result.error
                output = step_result.output
                duration_ms = step_result.duration_ms

        except Exception as e:
            logger.warning("Step %s failed: %s", step.id, e)
            status = "failed"
            error = str(e)

        step_end = datetime.now(timezone.utc)

        # If engine didn't populate duration, fall back to wall-clock
        if not duration_ms:
            duration_ms = int((step_end - step_start).total_seconds() * 1000)

        result.update({
            "status": status,
            "error": error,
            "output": output,
            "completed_at": step_end.isoformat(),
            "duration_ms": duration_ms,
        })

        # Log step completion (orchestrator-level event)
        storage_module.append_event(
            run_id,
            RunEvent(
                run_id=run_id,
                ts=step_end,
                kind="step_end" if status == "succeeded" else "step_error",
                flow_key=flow_key,
                step_id=step.id,
                agent_key=step.agents[0] if step.agents else None,
                payload={
                    "status": status,
                    "duration_ms": duration_ms,
                    "error": error,
                    "engine": self._engine.engine_id,
                },
            ),
        )

        return result

    def get_step_status(
        self,
        run_id: RunId,
        step_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Get the status of a specific step in a run.

        Searches the run's events for step_start and step_end events
        for the given step_id.

        Args:
            run_id: The run identifier.
            step_id: The step identifier.

        Returns:
            Dictionary with step status, or None if step not found.
        """
        events = storage_module.read_events(run_id)

        step_start = None
        step_end = None

        for event in events:
            if event.step_id != step_id:
                continue
            if event.kind == "step_start":
                step_start = event
            elif event.kind in ("step_end", "step_error"):
                step_end = event

        if not step_start:
            return None

        result = {
            "step_id": step_id,
            "started_at": step_start.ts.isoformat(),
            "status": "running" if not step_end else (
                "succeeded" if step_end.kind == "step_end" else "failed"
            ),
        }

        if step_end:
            result["completed_at"] = step_end.ts.isoformat()
            duration = step_end.payload.get("duration_ms")
            if duration is not None:
                result["duration_ms"] = duration
            if step_end.kind == "step_error":
                error = step_end.payload.get("error")
                if error is not None:
                    result["error"] = error

        return result

    # =========================================================================
    # ASYNC-NATIVE METHODS
    # =========================================================================
    # These methods provide async-first execution for WebUI and CLI integration.
    # They support proper cancellation handling for clean PARTIAL save-points.

    async def run_stepwise_flow_async(
        self,
        flow_key: str,
        spec: RunSpec,
        start_step: Optional[str] = None,
        end_step: Optional[str] = None,
        resume: bool = False,
    ) -> RunId:
        """Async version of run_stepwise_flow.

        Unlike the sync version which spawns a background thread, this method
        executes the flow directly in the current async context. This enables:
        - Proper cancellation via asyncio.CancelledError
        - Clean PARTIAL save-points on interruption
        - WebUI/CLI integration without thread management

        Args:
            flow_key: The flow to execute (e.g., "build", "plan").
            spec: Run specification with params and initiator info.
            start_step: Optional step ID to start from (skip earlier steps).
            end_step: Optional step ID to stop at (skip later steps).
            resume: Whether to resume from existing run_state.json.

        Returns:
            The generated run ID.

        Raises:
            ValueError: If flow_key is invalid or has no steps defined.
            asyncio.CancelledError: If execution is cancelled (PARTIAL saved).
        """
        # Validate flow exists - use spec bridge if enabled, otherwise YAML registry
        if self._use_spec_bridge and self._spec_bridge:
            flow_def = self._spec_bridge.get_flow(flow_key)
            if not flow_def:
                raise ValueError(f"Unknown flow (spec bridge): {flow_key}")
        else:
            flow_def = self._flow_registry.get_flow(flow_key)
            if not flow_def:
                raise ValueError(f"Unknown flow: {flow_key}")

        if not flow_def.steps:
            raise ValueError(f"Flow '{flow_key}' has no steps defined")

        # Create run
        run_id = generate_run_id()
        now = datetime.now(timezone.utc)

        # Ensure flow_keys includes our flow
        flow_keys = spec.flow_keys if spec.flow_keys else [flow_key]
        if flow_key not in flow_keys:
            flow_keys = [flow_key] + list(flow_keys)

        # Create updated spec with flow_keys
        run_spec = RunSpec(
            flow_keys=flow_keys,
            profile_id=spec.profile_id,
            backend=spec.backend,
            initiator=spec.initiator,
            params={**spec.params, "stepwise": True, "resume": resume, "async": True},
        )

        # Persist initial state
        storage_module.create_run_dir(run_id)
        storage_module.write_spec(run_id, run_spec)

        # Initialize or load run state
        if resume:
            existing_state = storage_module.read_run_state(run_id)
            if existing_state and existing_state.flow_key == flow_key:
                run_state = existing_state
                logger.info("Resuming run %s from step %s", run_id, existing_state.current_step_id)
            else:
                run_state = RunState(
                    run_id=run_id,
                    flow_key=flow_key,
                    status="running",
                    timestamp=datetime.now(timezone.utc),
                )
                storage_module.write_run_state(run_id, run_state)
        else:
            run_state = RunState(
                run_id=run_id,
                flow_key=flow_key,
                status="pending",
                timestamp=datetime.now(timezone.utc),
            )
            storage_module.write_run_state(run_id, run_state)

        summary = RunSummary(
            id=run_id,
            spec=run_spec,
            status=RunStatus.PENDING,
            sdlc_status=SDLCStatus.UNKNOWN,
            created_at=now,
            updated_at=now,
        )
        storage_module.write_summary(run_id, summary)

        # Log run creation
        storage_module.append_event(
            run_id,
            RunEvent(
                run_id=run_id,
                ts=now,
                kind="run_created",
                flow_key=flow_key,
                payload={
                    "flows": flow_keys,
                    "backend": spec.backend,
                    "initiator": spec.initiator,
                    "stepwise": True,
                    "async": True,
                },
            ),
        )

        # Execute directly (no background thread)
        await self._execute_stepwise_async(
            run_id, flow_key, flow_def, run_spec, run_state, start_step, end_step
        )

        return run_id

    async def _execute_stepwise_async(
        self,
        run_id: RunId,
        flow_key: str,
        flow_def: FlowDefinition,
        spec: RunSpec,
        run_state: RunState,
        start_step: Optional[str],
        end_step: Optional[str],
    ) -> None:
        """Async version of _execute_stepwise with cancellation handling.

        Supports asyncio.CancelledError for clean interruption:
        - Catches cancellation at step boundaries
        - Attempts to finalize current step if interrupted mid-work
        - Writes PARTIAL status to run_state for resumability

        Args:
            run_id: The run identifier.
            flow_key: The flow being executed.
            flow_def: The flow definition with steps.
            spec: The run specification.
            run_state: The current run state (for resume support).
            start_step: Optional step ID to start from.
            end_step: Optional step ID to stop at.
        """
        now = datetime.now(timezone.utc)

        # Update status to running
        storage_module.update_summary(run_id, {
            "status": RunStatus.RUNNING.value,
            "started_at": now.isoformat(),
            "updated_at": now.isoformat(),
        })

        storage_module.append_event(
            run_id,
            RunEvent(
                run_id=run_id,
                ts=now,
                kind="run_started",
                flow_key=flow_key,
                payload={
                    "mode": "stepwise_async",
                    "routing_enabled": True,
                    "resume": run_state.current_step_id is not None,
                },
            ),
        )

        storage_module.update_run_state(run_id, {"status": "running"})

        # Determine starting step
        if start_step:
            current_step = self._get_step_by_id(flow_def, start_step)
            if not current_step:
                current_step = flow_def.steps[0] if flow_def.steps else None
        elif run_state.current_step_id:
            current_step = self._get_step_by_id(flow_def, run_state.current_step_id)
            if not current_step:
                current_step = flow_def.steps[0] if flow_def.steps else None
        else:
            current_step = flow_def.steps[0] if flow_def.steps else None

        loop_state = dict(run_state.loop_state)
        error_msg = None
        final_status = RunStatus.SUCCEEDED
        sdlc_status = SDLCStatus.OK
        step_history: List[Dict[str, Any]] = []

        # Reconstruct step history from saved handoff envelopes
        for step_id, envelope in run_state.handoff_envelopes.items():
            step_history.append({
                "step_id": envelope.step_id,
                "status": envelope.status,
                "output": envelope.summary,
            })

        total_steps_executed = 0
        max_total_steps = len(flow_def.steps) * 10
        cancelled = False

        try:
            while current_step is not None:
                # Check for stop request at step boundary (before starting step)
                if self._is_stop_requested(run_id):
                    logger.info(
                        "Stop requested for %s at step boundary (before %s)",
                        run_id, current_step.id,
                    )
                    # Emit stop event
                    storage_module.append_event(
                        run_id,
                        RunEvent(
                            run_id=run_id,
                            ts=datetime.now(timezone.utc),
                            kind="run_stop_requested",
                            flow_key=flow_key,
                            step_id=current_step.id,
                            payload={"reason": "operator_stop"},
                        ),
                    )
                    # Save PARTIAL state with cursor for resumption
                    storage_module.update_run_state(run_id, {
                        "status": "partial",
                        "current_step_id": current_step.id,
                        "loop_state": dict(loop_state),
                    })
                    final_status = RunStatus.PARTIAL
                    sdlc_status = SDLCStatus.PARTIAL
                    error_msg = f"Stopped at step boundary before {current_step.id}"
                    break

                # Safety limit check
                total_steps_executed += 1
                if total_steps_executed > max_total_steps:
                    logger.error(
                        "Safety limit reached: %d steps executed, aborting",
                        total_steps_executed,
                    )
                    final_status = RunStatus.FAILED
                    sdlc_status = SDLCStatus.ERROR
                    error_msg = f"Safety limit reached: {total_steps_executed} steps"
                    break

                # Build routing context
                routing_ctx = self._build_routing_context(current_step, loop_state)

                # Execute the current step (async)
                try:
                    step_result = await self._execute_single_step_async(
                        run_id=run_id,
                        flow_key=flow_key,
                        flow_def=flow_def,
                        step=current_step,
                        spec=spec,
                        history=step_history,
                        routing_ctx=routing_ctx,
                        run_state=run_state,
                    )
                except asyncio.CancelledError:
                    # Cancellation during step execution
                    logger.warning(
                        "Cancellation during step %s, attempting PARTIAL save",
                        current_step.id,
                    )
                    cancelled = True
                    final_status = RunStatus.CANCELED
                    sdlc_status = SDLCStatus.PARTIAL
                    error_msg = f"Cancelled during step {current_step.id}"

                    # Write PARTIAL state
                    storage_module.update_run_state(run_id, {
                        "status": "partial",
                        "current_step_id": current_step.id,
                        "loop_state": dict(loop_state),
                    })
                    break

                # Add to history
                step_history.append(step_result)

                # =======================================================
                # ROUTING LIFT: Prefer engine's handoff/routing when available
                # =======================================================
                # (Same logic as sync version - see sync _execute_stepwise)

                # Check if lifecycle-capable engine already provided envelope
                if "handoff_envelope" in step_result and step_result["handoff_envelope"]:
                    handoff_envelope = step_result["handoff_envelope"]
                    logger.debug(
                        "Using engine-provided handoff envelope for step %s (async)",
                        current_step.id,
                    )
                    # Engine's envelope may not have routing_signal yet - add it
                    if handoff_envelope.routing_signal is None:
                        if "routing_signal" in step_result and step_result["routing_signal"]:
                            handoff_envelope.routing_signal = step_result["routing_signal"]
                        else:
                            handoff_envelope.routing_signal = self._create_routing_signal(
                                current_step, step_result, loop_state
                            )
                else:
                    # Create new envelope - prefer engine's routing signal
                    routing_signal = step_result.get("routing_signal")
                    if routing_signal is None:
                        routing_signal = self._create_routing_signal(
                            current_step, step_result, loop_state
                        )

                    handoff_envelope = HandoffEnvelope(
                        step_id=current_step.id,
                        flow_key=flow_key,
                        run_id=run_id,
                        routing_signal=routing_signal,
                        summary=step_result.get("output", "")[:2000],
                        status=step_result.get("status", "succeeded"),
                        error=step_result.get("error"),
                        duration_ms=step_result.get("duration_ms", 0),
                        timestamp=datetime.now(timezone.utc),
                    )

                run_state.handoff_envelopes[current_step.id] = handoff_envelope

                # Atomic commit
                storage_module.commit_step_completion(
                    run_id=run_id,
                    flow_key=flow_key,
                    envelope=handoff_envelope,
                    run_state_updates={
                        "current_step_id": current_step.id,
                        "step_index": current_step.index,
                        "loop_state": dict(loop_state),
                        "status": "running",
                    },
                )

                # Check for step failure
                if step_result.get("status") == "failed":
                    final_status = RunStatus.FAILED
                    sdlc_status = SDLCStatus.ERROR
                    error_msg = step_result.get("error", f"Step {current_step.id} failed")
                    break

                # Check end_step condition
                if end_step and current_step.id == end_step:
                    logger.info("Reached end_step %s, stopping execution", end_step)
                    break

                # Route to next step
                next_step_id, route_reason = self._route(
                    flow_def=flow_def,
                    current_step=current_step,
                    result=step_result,
                    loop_state=loop_state,
                    run_id=run_id,
                    flow_key=flow_key,
                    handoff_envelope=handoff_envelope,
                )

                # Update routing context
                if routing_ctx:
                    routing_ctx.reason = route_reason
                    routing = current_step.routing
                    if next_step_id is None:
                        routing_ctx.decision = "terminate"
                    elif routing and routing.loop_target and next_step_id == routing.loop_target:
                        routing_ctx.decision = "loop"
                    else:
                        routing_ctx.decision = "advance"

                    agent_key = current_step.agents[0] if current_step.agents else "unknown"
                    self._update_receipt_routing(
                        run_id, flow_key, current_step.id, agent_key, routing_ctx
                    )

                # Emit routing decision event
                storage_module.append_event(
                    run_id,
                    RunEvent(
                        run_id=run_id,
                        ts=datetime.now(timezone.utc),
                        kind="route_decision",
                        flow_key=flow_key,
                        step_id=current_step.id,
                        payload={
                            "from_step": current_step.id,
                            "to_step": next_step_id,
                            "reason": route_reason,
                            "loop_state": dict(loop_state),
                            "decision": routing_ctx.decision if routing_ctx else "unknown",
                            "confidence": handoff_envelope.routing_signal.confidence,
                            "needs_human": handoff_envelope.routing_signal.needs_human,
                        },
                    ),
                )

                if next_step_id is None:
                    logger.info("Flow complete: %s", route_reason)
                    break

                current_step = self._get_step_by_id(flow_def, next_step_id)
                if current_step is None:
                    logger.error("Next step '%s' not found in flow", next_step_id)
                    final_status = RunStatus.FAILED
                    sdlc_status = SDLCStatus.ERROR
                    error_msg = f"Invalid routing: step '{next_step_id}' not found"
                    break

                # Yield control to allow cancellation checks
                await asyncio.sleep(0)

        except asyncio.CancelledError:
            logger.warning("Run %s cancelled at step boundary", run_id)
            cancelled = True
            final_status = RunStatus.CANCELED
            sdlc_status = SDLCStatus.PARTIAL
            error_msg = "Run cancelled"

            storage_module.update_run_state(run_id, {
                "status": "partial",
                "loop_state": dict(loop_state),
            })

        except Exception as e:
            logger.exception("Error in async stepwise execution for run %s", run_id)
            final_status = RunStatus.FAILED
            sdlc_status = SDLCStatus.ERROR
            error_msg = str(e)

        # Update final status
        completed_at = datetime.now(timezone.utc)
        storage_module.update_summary(run_id, {
            "status": final_status.value,
            "sdlc_status": sdlc_status.value,
            "completed_at": completed_at.isoformat(),
            "updated_at": completed_at.isoformat(),
            "error": error_msg,
        })

        storage_module.append_event(
            run_id,
            RunEvent(
                run_id=run_id,
                ts=completed_at,
                kind="run_completed" if not cancelled else "run_cancelled",
                flow_key=flow_key,
                payload={
                    "status": final_status.value,
                    "error": error_msg,
                    "steps_completed": len(step_history),
                    "total_steps_executed": total_steps_executed,
                    "loop_state_final": dict(loop_state),
                    "cancelled": cancelled,
                },
            ),
        )

        # Re-raise CancelledError if we were cancelled
        if cancelled:
            raise asyncio.CancelledError(error_msg)

    async def _execute_single_step_async(
        self,
        run_id: RunId,
        flow_key: str,
        flow_def: FlowDefinition,
        step: StepDefinition,
        spec: RunSpec,
        history: List[Dict[str, Any]],
        routing_ctx: Optional["RoutingContext"] = None,
        run_state: Optional[RunState] = None,
    ) -> Dict[str, Any]:
        """Async version of _execute_single_step.

        Uses engine's async methods when available, otherwise falls back
        to running sync methods in a thread pool.

        Args:
            run_id: The run identifier.
            flow_key: The flow being executed.
            flow_def: The flow definition.
            step: The step to execute.
            spec: The run specification.
            history: List of previous step results.
            routing_ctx: Optional routing context for microloop metadata.
            run_state: Optional RunState for building context pack.

        Returns:
            Dictionary with step execution result.
        """
        step_start = datetime.now(timezone.utc)

        # Log step start
        storage_module.append_event(
            run_id,
            RunEvent(
                run_id=run_id,
                ts=step_start,
                kind="step_start",
                flow_key=flow_key,
                step_id=step.id,
                agent_key=step.agents[0] if step.agents else None,
                payload={
                    "role": step.role,
                    "agents": list(step.agents),
                    "step_index": step.index,
                    "engine": self._engine.engine_id,
                    "async": True,
                },
            ),
        )

        result: Dict[str, Any] = {
            "step_id": step.id,
            "step_index": step.index,
            "agents": list(step.agents),
            "started_at": step_start.isoformat(),
            "run_id": run_id,
            "flow_key": flow_key,
        }

        status = "failed"
        error: Optional[str] = None
        output = ""
        duration_ms = 0

        try:
            # Build step context
            ctx = StepContext(
                repo_root=self._repo_root,
                run_id=run_id,
                flow_key=flow_key,
                step_id=step.id,
                step_index=step.index,
                total_steps=len(flow_def.steps),
                spec=spec,
                flow_title=flow_def.title,
                step_role=step.role,
                step_agents=tuple(step.agents),
                history=history,
                extra={},
                teaching_notes=step.teaching_notes,
                routing=routing_ctx,
            )

            # Build context pack
            context_pack = build_context_pack(ctx, run_state, self._repo_root)

            logger.debug(
                "Built context pack for step %s: %d artifacts, %d prior envelopes",
                step.id,
                len(context_pack.upstream_artifacts),
                len(context_pack.previous_envelopes),
            )

            # Enrich step definition
            enriched_step = enrich_step_definition_with_flow(
                step, flow_key, self._repo_root
            )

            ctx.extra["orchestrator_prompt"] = enriched_step.orchestrator_prompt
            ctx.extra["agent_prompts"] = enriched_step.agent_prompts
            ctx.extra["context_pack"] = context_pack

            if step.routing:
                ctx.extra["routing"] = {
                    "kind": step.routing.kind,
                    "next": step.routing.next,
                    "loop_target": step.routing.loop_target,
                    "loop_condition_field": step.routing.loop_condition_field,
                    "loop_success_values": list(step.routing.loop_success_values),
                    "max_iterations": step.routing.max_iterations,
                }

            # Check for lifecycle-capable engine with async support
            if isinstance(self._engine, LifecycleCapableEngine):
                # Check if engine has async methods
                if hasattr(self._engine, 'run_worker_async'):
                    # Use native async methods
                    step_result, work_events, work_summary = await self._engine.run_worker_async(ctx)
                else:
                    # Fall back to sync methods in thread pool
                    loop = asyncio.get_event_loop()
                    step_result, work_events, work_summary = await loop.run_in_executor(
                        None, self._engine.run_worker, ctx
                    )

                # Persist work events
                for event in work_events:
                    storage_module.append_event(run_id, event)

                # Finalization
                if hasattr(self._engine, 'finalize_step_async'):
                    finalization_result = await self._engine.finalize_step_async(
                        ctx, step_result, work_summary
                    )
                else:
                    loop = asyncio.get_event_loop()
                    finalization_result = await loop.run_in_executor(
                        None, self._engine.finalize_step, ctx, step_result, work_summary
                    )

                for event in finalization_result.events:
                    storage_module.append_event(run_id, event)

                # Routing
                routing_signal: Optional[RoutingSignal] = None
                if finalization_result.handoff_data:
                    if hasattr(self._engine, 'route_step_async'):
                        routing_signal = await self._engine.route_step_async(
                            ctx, finalization_result.handoff_data
                        )
                    else:
                        loop = asyncio.get_event_loop()
                        routing_signal = await loop.run_in_executor(
                            None, self._engine.route_step, ctx, finalization_result.handoff_data
                        )

                    if routing_signal:
                        result["routing_signal"] = routing_signal

                if finalization_result.envelope:
                    result["handoff_envelope"] = finalization_result.envelope

                status = step_result.status
                error = step_result.error
                output = step_result.output
                duration_ms = step_result.duration_ms

            else:
                # Legacy engine - use run_step
                if hasattr(self._engine, 'run_step_async'):
                    step_result, engine_events = await self._engine.run_step_async(ctx)
                else:
                    loop = asyncio.get_event_loop()
                    step_result, engine_events = await loop.run_in_executor(
                        None, self._engine.run_step, ctx
                    )

                for event in engine_events:
                    storage_module.append_event(run_id, event)

                status = step_result.status
                error = step_result.error
                output = step_result.output
                duration_ms = step_result.duration_ms

        except asyncio.CancelledError:
            # Re-raise cancellation
            raise

        except Exception as e:
            logger.warning("Step %s failed: %s", step.id, e)
            status = "failed"
            error = str(e)

        step_end = datetime.now(timezone.utc)

        if not duration_ms:
            duration_ms = int((step_end - step_start).total_seconds() * 1000)

        result.update({
            "status": status,
            "error": error,
            "output": output,
            "completed_at": step_end.isoformat(),
            "duration_ms": duration_ms,
        })

        # Log step completion
        storage_module.append_event(
            run_id,
            RunEvent(
                run_id=run_id,
                ts=step_end,
                kind="step_end" if status == "succeeded" else "step_error",
                flow_key=flow_key,
                step_id=step.id,
                agent_key=step.agents[0] if step.agents else None,
                payload={
                    "status": status,
                    "duration_ms": duration_ms,
                    "error": error,
                    "engine": self._engine.engine_id,
                    "async": True,
                },
            ),
        )

        return result


def get_orchestrator(
    engine: Optional[StepEngine] = None,
    repo_root: Optional[Path] = None,
) -> GeminiStepOrchestrator:
    """Factory function to create a stepwise orchestrator.

    Args:
        engine: Optional StepEngine instance. Creates GeminiStepEngine if None.
        repo_root: Optional repository root path.

    Returns:
        Configured GeminiStepOrchestrator instance.
    """
    if repo_root is None:
        repo_root = Path(__file__).resolve().parents[2]

    if engine is None:
        engine = GeminiStepEngine(repo_root)

    return GeminiStepOrchestrator(engine=engine, repo_root=repo_root)
