"""
autopilot.py - Autonomous flow chaining for end-to-end SDLC execution.

This module provides the AutopilotController for executing flows 1→6 (signal→wisdom)
without mid-flow human intervention. When enabled:

1. Flows are executed sequentially in SDLC order
2. PAUSE intents are automatically rewritten to DETOUR (clarifier sidequest)
3. Human review happens only at the end of the full run

The autopilot respects FlowGraph macro-routing when available but defaults to
sequential SDLC flow order when not.

Usage:
    from swarm.runtime.autopilot import AutopilotController

    controller = AutopilotController()
    run_id = controller.start(issue_ref="owner/repo#123")

    # Run to completion (blocking)
    result = controller.run_to_completion(run_id)

    # Or tick incrementally (non-blocking)
    while not controller.is_complete(run_id):
        controller.tick(run_id)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from swarm.config.flow_registry import FlowRegistry
from swarm.runtime import storage as storage_module
from swarm.runtime.types import (
    RunEvent,
    RunId,
    RunSpec,
    generate_run_id,
)

logger = logging.getLogger(__name__)


class AutopilotStatus(str, Enum):
    """Status of an autopilot run."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"
    STOPPING = "stopping"  # Graceful shutdown in progress
    STOPPED = "stopped"  # Clean stop with savepoint (distinct from failed)
    PAUSING = "pausing"  # Waiting for current flow to complete before pause
    PAUSED = "paused"  # Paused at a clean boundary, resumable


class EvolutionApplyPolicy(str, Enum):
    """Policy controlling when evolution patches are applied.

    Attributes:
        SUGGEST_ONLY: Generate suggestions but never auto-apply. Default.
        AUTO_APPLY_SAFE: Auto-apply patches marked as safe (low risk, high confidence).
        AUTO_APPLY_ALL: Auto-apply all patches regardless of risk level.
    """

    SUGGEST_ONLY = "suggest_only"
    AUTO_APPLY_SAFE = "auto_apply_safe"
    AUTO_APPLY_ALL = "auto_apply_all"


class EvolutionBoundary(str, Enum):
    """When evolution patches can be processed.

    Attributes:
        RUN_END: Only at the end of a complete autopilot run.
        FLOW_END: At the end of each flow (wisdom flow specifically).
        NEVER: Never process evolution patches.
    """

    RUN_END = "run_end"
    FLOW_END = "flow_end"
    NEVER = "never"


@dataclass
class EvolutionSuggestion:
    """A recorded evolution suggestion, whether applied or not.

    Attributes:
        patch_id: Unique identifier for the patch.
        target_file: File that would be modified.
        patch_type: Type of patch (flow_spec, station_spec, etc.).
        reasoning: Why this patch was suggested.
        confidence: Confidence level (high, medium, low).
        risk: Risk level (low, medium, high).
        action_taken: What happened (suggested, applied, rejected).
        rejection_reason: If rejected, why.
        applied_at: Timestamp if applied.
        source_run_id: Run that generated this suggestion.
    """

    patch_id: str
    target_file: str
    patch_type: str
    reasoning: str
    confidence: str
    risk: str
    action_taken: str  # "suggested", "applied", "rejected"
    rejection_reason: Optional[str] = None
    applied_at: Optional[str] = None
    source_run_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "patch_id": self.patch_id,
            "target_file": self.target_file,
            "patch_type": self.patch_type,
            "reasoning": self.reasoning,
            "confidence": self.confidence,
            "risk": self.risk,
            "action_taken": self.action_taken,
            "rejection_reason": self.rejection_reason,
            "applied_at": self.applied_at,
            "source_run_id": self.source_run_id,
        }


@dataclass
class AutopilotConfig:
    """Configuration for autopilot behavior.

    Attributes:
        auto_apply_wisdom: Whether to auto-apply wisdom patches at run end.
            Deprecated: Use evolution_apply_policy instead.
        auto_apply_policy: Policy for auto-apply ('safe' or 'all').
            Deprecated: Use evolution_apply_policy instead.
        auto_apply_patch_types: List of patch types to auto-apply.
        evolution_apply_policy: Policy controlling evolution patch application.
        evolution_boundary: When evolution patches can be processed.
    """

    auto_apply_wisdom: bool = False
    auto_apply_policy: str = "safe"
    auto_apply_patch_types: List[str] = field(
        default_factory=lambda: ["flow_evolution", "station_tuning"]
    )
    # New policy-gated evolution fields
    evolution_apply_policy: EvolutionApplyPolicy = EvolutionApplyPolicy.SUGGEST_ONLY
    evolution_boundary: EvolutionBoundary = EvolutionBoundary.RUN_END

    def __post_init__(self):
        """Normalize deprecated fields to new policy."""
        # If legacy auto_apply_wisdom is True, translate to new policy
        if (
            self.auto_apply_wisdom
            and self.evolution_apply_policy == EvolutionApplyPolicy.SUGGEST_ONLY
        ):
            if self.auto_apply_policy == "all":
                self.evolution_apply_policy = EvolutionApplyPolicy.AUTO_APPLY_ALL
            else:
                self.evolution_apply_policy = EvolutionApplyPolicy.AUTO_APPLY_SAFE


@dataclass
class WisdomApplyResult:
    """Result of auto-applying wisdom patches.

    Attributes:
        patches_processed: Total patches considered.
        patches_applied: Number of patches successfully applied.
        patches_rejected: Number of patches rejected due to validation.
        patches_skipped: Number of patches skipped (already applied/rejected).
        patches_suggested: Number of patches recorded as suggestions only.
        applied_patch_ids: IDs of successfully applied patches.
        rejected_patch_ids: IDs of rejected patches with reasons.
        suggestions: All evolution suggestions recorded (applied or not).
    """

    patches_processed: int = 0
    patches_applied: int = 0
    patches_rejected: int = 0
    patches_skipped: int = 0
    patches_suggested: int = 0
    applied_patch_ids: List[str] = field(default_factory=list)
    rejected_patch_ids: List[Dict[str, str]] = field(default_factory=list)
    suggestions: List[EvolutionSuggestion] = field(default_factory=list)


@dataclass
class AutopilotResult:
    """Result of an autopilot run.

    Attributes:
        run_id: The unique run identifier.
        status: Final status of the autopilot run.
        flows_completed: List of flow keys that completed successfully.
        flows_failed: List of flow keys that failed.
        current_flow: The flow that was running when the run ended.
        error: Error message if the run failed.
        wisdom_artifacts: Paths to wisdom output artifacts.
        duration_ms: Total execution time in milliseconds.
        wisdom_apply_result: Result of auto-applying wisdom patches (if enabled).
    """

    run_id: RunId
    status: AutopilotStatus
    flows_completed: List[str] = field(default_factory=list)
    flows_failed: List[str] = field(default_factory=list)
    current_flow: Optional[str] = None
    error: Optional[str] = None
    wisdom_artifacts: Dict[str, str] = field(default_factory=dict)
    duration_ms: int = 0
    wisdom_apply_result: Optional[WisdomApplyResult] = None


@dataclass
class AutopilotState:
    """Internal state for an autopilot run.

    Tracks progress through the flow chain and accumulates results.
    """

    run_id: RunId
    spec: RunSpec
    config: AutopilotConfig = field(default_factory=AutopilotConfig)
    status: AutopilotStatus = AutopilotStatus.PENDING
    current_flow_index: int = 0
    flows_to_execute: List[str] = field(default_factory=list)
    flows_completed: List[str] = field(default_factory=list)
    flows_failed: List[str] = field(default_factory=list)
    flow_transition_history: List[Dict[str, Any]] = field(default_factory=list)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error: Optional[str] = None
    wisdom_apply_result: Optional[WisdomApplyResult] = None


class AutopilotController:
    """Controller for autonomous flow chaining.

    The AutopilotController manages end-to-end SDLC execution by:
    1. Creating a run with no_human_mid_flow=True
    2. Executing flows in sequence (signal -> plan -> build -> gate -> deploy -> wisdom)
    3. Handling flow transitions and failures
    4. Collecting wisdom artifacts at the end
    5. Optionally auto-applying wisdom patches at run boundary

    Example:
        controller = AutopilotController()
        run_id = controller.start(
            issue_ref="owner/repo#123",
            auto_apply_wisdom=True,
        )
        result = controller.run_to_completion(run_id)
        print(f"Completed with status: {result.status}")
        if result.wisdom_apply_result:
            print(f"Applied {result.wisdom_apply_result.patches_applied} patches")
    """

    def __init__(
        self,
        repo_root: Optional[Path] = None,
        orchestrator: Optional[Any] = None,
        default_config: Optional[AutopilotConfig] = None,
    ):
        """Initialize the autopilot controller.

        Args:
            repo_root: Repository root path. Defaults to auto-detection.
            orchestrator: Optional orchestrator instance to use for flow execution.
                If not provided, will import and use GeminiStepOrchestrator.
            default_config: Default configuration for autopilot runs.
        """
        self._repo_root = repo_root or Path(__file__).resolve().parents[2]
        self._flow_registry = FlowRegistry.get_instance()
        self._orchestrator = orchestrator
        self._states: Dict[RunId, AutopilotState] = {}
        self._default_config = default_config or AutopilotConfig()

    def _get_orchestrator(self) -> Any:
        """Lazily load the orchestrator to avoid circular imports."""
        if self._orchestrator is None:
            from swarm.runtime.engines.stub import StubStepEngine
            from swarm.runtime.orchestrator import GeminiStepOrchestrator

            engine = StubStepEngine()
            self._orchestrator = GeminiStepOrchestrator(
                engine=engine,
                repo_root=self._repo_root,
            )
        return self._orchestrator

    def _get_sdlc_flows(self) -> List[str]:
        """Get the ordered list of SDLC flows to execute."""
        return self._flow_registry.sdlc_flow_keys

    def start(
        self,
        issue_ref: Optional[str] = None,
        flow_keys: Optional[List[str]] = None,
        profile_id: Optional[str] = None,
        backend: str = "claude-step-orchestrator",
        initiator: str = "autopilot",
        params: Optional[Dict[str, Any]] = None,
        auto_apply_wisdom: Optional[bool] = None,
        auto_apply_policy: Optional[str] = None,
        auto_apply_patch_types: Optional[List[str]] = None,
    ) -> RunId:
        """Start an autopilot run.

        Creates a new run configured for autonomous execution with all SDLC
        flows (or a custom subset) scheduled for sequential execution.

        Args:
            issue_ref: Optional issue reference (e.g., "owner/repo#123") to
                use for issue ingestion in Flow 1.
            flow_keys: Optional list of specific flows to execute. Defaults
                to all SDLC flows in order.
            profile_id: Optional profile ID to use.
            backend: Backend to use for execution.
            initiator: Source identifier for the run.
            params: Additional parameters passed to the run spec.
            auto_apply_wisdom: Whether to auto-apply wisdom patches at run end.
                Defaults to the controller's default config.
            auto_apply_policy: Policy for auto-apply ('safe' or 'all').
                Defaults to the controller's default config.
            auto_apply_patch_types: List of patch types to auto-apply.
                Defaults to the controller's default config.

        Returns:
            The run ID for the new autopilot run.
        """
        run_id = generate_run_id()
        flows = flow_keys or self._get_sdlc_flows()

        # Build autopilot config, merging with defaults
        config = AutopilotConfig(
            auto_apply_wisdom=(
                auto_apply_wisdom
                if auto_apply_wisdom is not None
                else self._default_config.auto_apply_wisdom
            ),
            auto_apply_policy=(
                auto_apply_policy
                if auto_apply_policy is not None
                else self._default_config.auto_apply_policy
            ),
            auto_apply_patch_types=(
                auto_apply_patch_types
                if auto_apply_patch_types is not None
                else self._default_config.auto_apply_patch_types
            ),
        )

        # Create run spec with no_human_mid_flow enabled
        spec = RunSpec(
            flow_keys=flows,
            profile_id=profile_id,
            backend=backend,
            initiator=initiator,
            params={
                **(params or {}),
                "autopilot": True,
                "issue_ref": issue_ref,
                "auto_apply_wisdom": config.auto_apply_wisdom,
                "auto_apply_policy": config.auto_apply_policy,
            },
            no_human_mid_flow=True,  # Key: enables PAUSE->DETOUR rewriting
        )

        # Initialize autopilot state
        state = AutopilotState(
            run_id=run_id,
            spec=spec,
            config=config,
            flows_to_execute=list(flows),
            current_flow_index=0,
        )
        self._states[run_id] = state

        # Create run directory and persist spec
        storage_module.create_run_dir(run_id)
        storage_module.write_spec(run_id, spec)

        # Emit autopilot_started event
        now = datetime.now(timezone.utc)
        storage_module.append_event(
            run_id,
            RunEvent(
                run_id=run_id,
                ts=now,
                kind="autopilot_started",
                flow_key=flows[0] if flows else "",
                payload={
                    "flows": flows,
                    "issue_ref": issue_ref,
                    "no_human_mid_flow": True,
                },
            ),
        )

        logger.info(
            "Autopilot run %s started with flows: %s",
            run_id,
            ", ".join(flows),
        )

        return run_id

    def tick(self, run_id: RunId) -> bool:
        """Advance the autopilot run by executing the next flow.

        Each tick executes one complete flow. Call repeatedly until
        is_complete() returns True.

        Args:
            run_id: The autopilot run to advance.

        Returns:
            True if the tick completed successfully, False if the run
            failed or is already complete.

        Raises:
            ValueError: If run_id is not a known autopilot run.
        """
        state = self._states.get(run_id)
        if state is None:
            raise ValueError(f"Unknown autopilot run: {run_id}")

        # Check if already complete or terminal
        if state.status in (
            AutopilotStatus.SUCCEEDED,
            AutopilotStatus.FAILED,
            AutopilotStatus.CANCELED,
            AutopilotStatus.STOPPED,
        ):
            return False

        # Check if stopping or pausing - handle graceful shutdown
        if state.status == AutopilotStatus.STOPPING:
            self._finalize_stop(state)
            return False

        if state.status == AutopilotStatus.PAUSING:
            self._finalize_pause(state)
            return False

        if state.status == AutopilotStatus.PAUSED:
            return False  # Don't advance while paused

        # Start if pending
        if state.status == AutopilotStatus.PENDING:
            state.status = AutopilotStatus.RUNNING
            state.started_at = datetime.now(timezone.utc)

        # Check if all flows completed
        if state.current_flow_index >= len(state.flows_to_execute):
            self._finalize_run(state, success=True)
            return False

        # Execute current flow
        flow_key = state.flows_to_execute[state.current_flow_index]
        logger.info(
            "Autopilot run %s executing flow %d/%d: %s",
            run_id,
            state.current_flow_index + 1,
            len(state.flows_to_execute),
            flow_key,
        )

        try:
            # Record flow start
            now = datetime.now(timezone.utc)
            storage_module.append_event(
                run_id,
                RunEvent(
                    run_id=run_id,
                    ts=now,
                    kind="autopilot_flow_started",
                    flow_key=flow_key,
                    payload={
                        "flow_index": state.current_flow_index,
                        "total_flows": len(state.flows_to_execute),
                    },
                ),
            )

            # Execute flow using the orchestrator
            orchestrator = self._get_orchestrator()
            orchestrator.run_stepwise_flow(
                flow_key=flow_key,
                spec=state.spec,
                run_id=run_id,
                resume=False,
            )

            # Mark flow as completed
            state.flows_completed.append(flow_key)
            state.flow_transition_history.append(
                {
                    "from_flow": flow_key,
                    "to_flow": (
                        state.flows_to_execute[state.current_flow_index + 1]
                        if state.current_flow_index + 1 < len(state.flows_to_execute)
                        else None
                    ),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "status": "succeeded",
                }
            )

            # Emit flow completed event
            storage_module.append_event(
                run_id,
                RunEvent(
                    run_id=run_id,
                    ts=datetime.now(timezone.utc),
                    kind="autopilot_flow_completed",
                    flow_key=flow_key,
                    payload={"status": "succeeded"},
                ),
            )

            # Advance to next flow
            state.current_flow_index += 1
            return True

        except Exception as e:
            logger.error(
                "Autopilot run %s flow %s failed: %s",
                run_id,
                flow_key,
                e,
            )

            state.flows_failed.append(flow_key)
            state.error = str(e)

            # Emit flow failed event
            storage_module.append_event(
                run_id,
                RunEvent(
                    run_id=run_id,
                    ts=datetime.now(timezone.utc),
                    kind="autopilot_flow_failed",
                    flow_key=flow_key,
                    payload={"error": str(e)},
                ),
            )

            self._finalize_run(state, success=False)
            return False

    def run_to_completion(self, run_id: RunId) -> AutopilotResult:
        """Run the autopilot to completion.

        Blocking call that executes all flows in sequence until the run
        completes (successfully or with failure).

        Args:
            run_id: The autopilot run to complete.

        Returns:
            AutopilotResult with final status and collected artifacts.
        """
        while not self.is_complete(run_id):
            success = self.tick(run_id)
            if not success:
                break

        return self.get_result(run_id)

    def is_complete(self, run_id: RunId) -> bool:
        """Check if an autopilot run is complete.

        Args:
            run_id: The autopilot run to check.

        Returns:
            True if the run has finished (success, failure, canceled, or stopped).
        """
        state = self._states.get(run_id)
        if state is None:
            return True  # Unknown runs are considered complete

        return state.status in (
            AutopilotStatus.SUCCEEDED,
            AutopilotStatus.FAILED,
            AutopilotStatus.CANCELED,
            AutopilotStatus.STOPPED,
        )

    def is_paused(self, run_id: RunId) -> bool:
        """Check if an autopilot run is paused.

        Args:
            run_id: The autopilot run to check.

        Returns:
            True if the run is paused and can be resumed.
        """
        state = self._states.get(run_id)
        if state is None:
            return False

        return state.status in (AutopilotStatus.PAUSED,)

    def is_resumable(self, run_id: RunId) -> bool:
        """Check if an autopilot run can be resumed.

        Args:
            run_id: The autopilot run to check.

        Returns:
            True if the run is stopped or paused and can be resumed.
        """
        state = self._states.get(run_id)
        if state is None:
            return False

        return state.status in (AutopilotStatus.PAUSED, AutopilotStatus.STOPPED)

    def get_result(self, run_id: RunId) -> AutopilotResult:
        """Get the result of an autopilot run.

        Args:
            run_id: The autopilot run to get results for.

        Returns:
            AutopilotResult with status and collected data.
        """
        state = self._states.get(run_id)
        if state is None:
            return AutopilotResult(
                run_id=run_id,
                status=AutopilotStatus.FAILED,
                error="Unknown autopilot run",
            )

        # Calculate duration
        duration_ms = 0
        if state.started_at:
            end_time = state.completed_at or datetime.now(timezone.utc)
            duration_ms = int((end_time - state.started_at).total_seconds() * 1000)

        # Collect wisdom artifacts if wisdom flow completed
        wisdom_artifacts = {}
        if "wisdom" in state.flows_completed:
            wisdom_dir = storage_module.get_run_path(run_id) / "wisdom"
            if wisdom_dir.exists():
                for artifact in wisdom_dir.glob("*.md"):
                    wisdom_artifacts[artifact.stem] = str(artifact)

        return AutopilotResult(
            run_id=run_id,
            status=state.status,
            flows_completed=list(state.flows_completed),
            flows_failed=list(state.flows_failed),
            current_flow=(
                state.flows_to_execute[state.current_flow_index]
                if state.current_flow_index < len(state.flows_to_execute)
                else None
            ),
            error=state.error,
            wisdom_artifacts=wisdom_artifacts,
            duration_ms=duration_ms,
            wisdom_apply_result=state.wisdom_apply_result,
        )

    def cancel(self, run_id: RunId) -> bool:
        """Cancel an autopilot run.

        Args:
            run_id: The autopilot run to cancel.

        Returns:
            True if the run was canceled, False if already complete.
        """
        state = self._states.get(run_id)
        if state is None:
            return False

        if state.status in (
            AutopilotStatus.SUCCEEDED,
            AutopilotStatus.FAILED,
            AutopilotStatus.CANCELED,
            AutopilotStatus.STOPPED,
        ):
            return False

        state.status = AutopilotStatus.CANCELED
        state.completed_at = datetime.now(timezone.utc)

        # Emit canceled event
        storage_module.append_event(
            run_id,
            RunEvent(
                run_id=run_id,
                ts=datetime.now(timezone.utc),
                kind="autopilot_canceled",
                flow_key=state.flows_to_execute[state.current_flow_index]
                if state.current_flow_index < len(state.flows_to_execute)
                else "",
                payload={},
            ),
        )

        logger.info("Autopilot run %s canceled", run_id)
        return True

    def stop(self, run_id: RunId, reason: str = "user_initiated") -> bool:
        """Stop an autopilot run gracefully with savepoint.

        Unlike cancel, stop creates a clean savepoint that can be resumed.
        The run will complete its current flow (if any) then stop.

        Args:
            run_id: The autopilot run to stop.
            reason: Reason for stopping.

        Returns:
            True if stop was initiated, False if run is already complete.
        """
        state = self._states.get(run_id)
        if state is None:
            return False

        if state.status in (
            AutopilotStatus.SUCCEEDED,
            AutopilotStatus.FAILED,
            AutopilotStatus.CANCELED,
            AutopilotStatus.STOPPED,
        ):
            return False

        # Set to stopping - will be finalized in next tick
        state.status = AutopilotStatus.STOPPING
        state.error = f"Stop requested: {reason}"

        # Emit stopping event
        storage_module.append_event(
            run_id,
            RunEvent(
                run_id=run_id,
                ts=datetime.now(timezone.utc),
                kind="autopilot_stopping",
                flow_key=state.flows_to_execute[state.current_flow_index]
                if state.current_flow_index < len(state.flows_to_execute)
                else "",
                payload={"reason": reason},
            ),
        )

        logger.info("Autopilot run %s stopping: %s", run_id, reason)
        return True

    def pause(self, run_id: RunId) -> bool:
        """Pause an autopilot run at the next flow boundary.

        The run will complete its current flow (if any) then pause.
        Can be resumed later with resume().

        Args:
            run_id: The autopilot run to pause.

        Returns:
            True if pause was initiated, False if run cannot be paused.
        """
        state = self._states.get(run_id)
        if state is None:
            return False

        if state.status not in (AutopilotStatus.RUNNING, AutopilotStatus.PENDING):
            return False

        # Set to pausing - will be finalized in next tick
        state.status = AutopilotStatus.PAUSING

        # Emit pausing event
        storage_module.append_event(
            run_id,
            RunEvent(
                run_id=run_id,
                ts=datetime.now(timezone.utc),
                kind="autopilot_pausing",
                flow_key=state.flows_to_execute[state.current_flow_index]
                if state.current_flow_index < len(state.flows_to_execute)
                else "",
                payload={},
            ),
        )

        logger.info("Autopilot run %s pausing", run_id)
        return True

    def resume(self, run_id: RunId) -> bool:
        """Resume a paused or stopped autopilot run.

        Continues execution from the saved flow index.

        Args:
            run_id: The autopilot run to resume.

        Returns:
            True if resume was successful, False if run cannot be resumed.
        """
        state = self._states.get(run_id)
        if state is None:
            return False

        if state.status not in (AutopilotStatus.PAUSED, AutopilotStatus.STOPPED):
            return False

        previous_status = state.status
        state.status = AutopilotStatus.RUNNING

        # Emit resumed event
        storage_module.append_event(
            run_id,
            RunEvent(
                run_id=run_id,
                ts=datetime.now(timezone.utc),
                kind="autopilot_resumed",
                flow_key=state.flows_to_execute[state.current_flow_index]
                if state.current_flow_index < len(state.flows_to_execute)
                else "",
                payload={"previous_status": previous_status.value},
            ),
        )

        logger.info("Autopilot run %s resumed from %s", run_id, previous_status.value)
        return True

    def _finalize_stop(self, state: AutopilotState) -> None:
        """Finalize a stopping run into stopped state.

        Creates a clean savepoint with stop report.

        Args:
            state: The autopilot state to finalize.
        """
        state.status = AutopilotStatus.STOPPED
        state.completed_at = datetime.now(timezone.utc)

        # Write stop report
        self._write_autopilot_stop_report(state)

        # Emit stopped event
        storage_module.append_event(
            state.run_id,
            RunEvent(
                run_id=state.run_id,
                ts=datetime.now(timezone.utc),
                kind="autopilot_stopped",
                flow_key=state.flows_to_execute[state.current_flow_index]
                if state.current_flow_index < len(state.flows_to_execute)
                else "",
                payload={
                    "flows_completed": state.flows_completed,
                    "flows_remaining": state.flows_to_execute[state.current_flow_index :],
                    "reason": state.error or "unknown",
                },
            ),
        )

        logger.info("Autopilot run %s stopped", state.run_id)

    def _finalize_pause(self, state: AutopilotState) -> None:
        """Finalize a pausing run into paused state.

        Args:
            state: The autopilot state to finalize.
        """
        state.status = AutopilotStatus.PAUSED

        # Emit paused event
        storage_module.append_event(
            state.run_id,
            RunEvent(
                run_id=state.run_id,
                ts=datetime.now(timezone.utc),
                kind="autopilot_paused",
                flow_key=state.flows_to_execute[state.current_flow_index]
                if state.current_flow_index < len(state.flows_to_execute)
                else "",
                payload={
                    "flows_completed": state.flows_completed,
                    "flows_remaining": state.flows_to_execute[state.current_flow_index :],
                },
            ),
        )

        logger.info("Autopilot run %s paused", state.run_id)

    def _write_autopilot_stop_report(self, state: AutopilotState) -> None:
        """Write stop_report.md for an autopilot run.

        Args:
            state: The autopilot state to report on.
        """
        run_path = storage_module.get_run_path(state.run_id)
        report_path = run_path / "stop_report.md"

        now = datetime.now(timezone.utc).isoformat()
        current_flow = (
            state.flows_to_execute[state.current_flow_index]
            if state.current_flow_index < len(state.flows_to_execute)
            else None
        )
        remaining_flows = state.flows_to_execute[state.current_flow_index :]

        lines = [
            "# Autopilot Stop Report",
            "",
            f"**Run ID:** {state.run_id}",
            f"**Stopped At:** {now}",
            f"**Reason:** {state.error or 'Unknown'}",
            "",
            "## Execution State",
            "",
            f"- **Current Flow Index:** {state.current_flow_index}",
            f"- **Current Flow:** {current_flow or 'None'}",
            f"- **Total Flows:** {len(state.flows_to_execute)}",
            "",
            "## Completed Flows",
            "",
        ]

        if state.flows_completed:
            for flow in state.flows_completed:
                lines.append(f"- {flow}")
        else:
            lines.append("- None")

        lines.extend(
            [
                "",
                "## Remaining Flows (not executed)",
                "",
            ]
        )

        if remaining_flows:
            for flow in remaining_flows:
                lines.append(f"- {flow}")
        else:
            lines.append("- None (all flows completed)")

        lines.extend(
            [
                "",
                "## Flow Transition History",
                "",
            ]
        )

        if state.flow_transition_history:
            for transition in state.flow_transition_history:
                lines.append(
                    f"- {transition.get('from_flow', '?')} -> "
                    f"{transition.get('to_flow', '?')} "
                    f"({transition.get('status', '?')}) "
                    f"at {transition.get('timestamp', '?')}"
                )
        else:
            lines.append("- No transitions recorded")

        lines.extend(
            [
                "",
                "## Resume Instructions",
                "",
                "To resume this run from the stopped state:",
                "1. Call `controller.resume(run_id)` to continue from the current flow",
                "2. Or use the API: `POST /api/runs/{run_id}/resume`",
                "",
            ]
        )

        report_content = "\n".join(lines)
        report_path.write_text(report_content, encoding="utf-8")

        logger.debug("Wrote stop report to %s", report_path)

    def _finalize_run(self, state: AutopilotState, success: bool) -> None:
        """Finalize an autopilot run.

        This method:
        1. Sets final status
        2. Processes evolution patches at run boundary (if configured and wisdom completed)
        3. Emits completion events

        Evolution processing is policy-gated:
        - SUGGEST_ONLY (default): Record suggestions, emit evolution_suggested events
        - AUTO_APPLY_SAFE: Apply only safe patches (low risk, high confidence)
        - AUTO_APPLY_ALL: Apply all valid patches

        Args:
            state: The autopilot state to finalize.
            success: Whether the run completed successfully.
        """
        state.status = AutopilotStatus.SUCCEEDED if success else AutopilotStatus.FAILED
        state.completed_at = datetime.now(timezone.utc)

        # Process evolution at run boundary if:
        # - Evolution boundary is RUN_END (or legacy auto_apply_wisdom is True)
        # - Run completed successfully
        # - Wisdom flow completed
        should_process_evolution = (
            success
            and "wisdom" in state.flows_completed
            and (
                state.config.evolution_boundary == EvolutionBoundary.RUN_END
                or state.config.auto_apply_wisdom  # Legacy compatibility
            )
        )

        if should_process_evolution:
            state.wisdom_apply_result = self._process_evolution_at_boundary(state, "run_end")

        # Emit completion event
        evolution_summary = None
        if state.wisdom_apply_result:
            evolution_summary = {
                "policy": state.config.evolution_apply_policy.value,
                "patches_processed": state.wisdom_apply_result.patches_processed,
                "patches_applied": state.wisdom_apply_result.patches_applied,
                "patches_suggested": state.wisdom_apply_result.patches_suggested,
                "patches_rejected": state.wisdom_apply_result.patches_rejected,
                "patches_skipped": state.wisdom_apply_result.patches_skipped,
                "applied_patch_ids": state.wisdom_apply_result.applied_patch_ids,
            }

        storage_module.append_event(
            state.run_id,
            RunEvent(
                run_id=state.run_id,
                ts=datetime.now(timezone.utc),
                kind="autopilot_completed",
                flow_key=state.flows_completed[-1] if state.flows_completed else "",
                payload={
                    "status": state.status.value,
                    "flows_completed": state.flows_completed,
                    "flows_failed": state.flows_failed,
                    "error": state.error,
                    "evolution_summary": evolution_summary,
                    # Legacy field for backwards compatibility
                    "wisdom_auto_apply": evolution_summary,
                },
            ),
        )

        logger.info(
            "Autopilot run %s completed with status: %s",
            state.run_id,
            state.status.value,
        )

    def _process_evolution_at_boundary(
        self,
        state: AutopilotState,
        boundary: str,
    ) -> WisdomApplyResult:
        """Process evolution patches at a flow or run boundary.

        Policy-gated evolution processing. Based on the evolution_apply_policy:
        - SUGGEST_ONLY: Record suggestions, emit evolution_suggested events, never apply
        - AUTO_APPLY_SAFE: Apply only safe patches (low risk, high confidence)
        - AUTO_APPLY_ALL: Apply all valid patches

        This is the new policy-gated implementation that replaces the legacy
        _auto_apply_wisdom_patches behavior.

        Args:
            state: The autopilot state containing config and run info.
            boundary: The boundary type ("flow_end" or "run_end").

        Returns:
            WisdomApplyResult with summary of processed patches.
        """
        import json

        from swarm.runtime.evolution import (
            PatchType,
            apply_evolution_patch,
            generate_evolution_patch,
            validate_evolution_patch,
        )

        result = WisdomApplyResult()
        run_id = state.run_id
        config = state.config
        policy = config.evolution_apply_policy

        wisdom_dir = storage_module.get_run_path(run_id) / "wisdom"
        if not wisdom_dir.exists():
            logger.warning(
                "Wisdom directory not found for evolution processing: %s",
                wisdom_dir,
            )
            return result

        # Emit evolution processing started event
        storage_module.append_event(
            run_id,
            RunEvent(
                run_id=run_id,
                ts=datetime.now(timezone.utc),
                kind="evolution_processing_started",
                flow_key="wisdom",
                payload={
                    "policy": policy.value,
                    "boundary": boundary,
                    "patch_types": config.auto_apply_patch_types,
                },
            ),
        )

        # Map patch type strings to PatchType enum
        type_mapping = {
            "flow_evolution": [PatchType.FLOW_SPEC],
            "station_tuning": [PatchType.STATION_SPEC],
        }

        target_types: List[PatchType] = []
        for pt_str in config.auto_apply_patch_types:
            target_types.extend(type_mapping.get(pt_str, []))

        # Generate patches from wisdom artifacts
        patches = generate_evolution_patch(wisdom_dir, run_id=run_id)

        for patch in patches:
            if patch.patch_type not in target_types:
                continue

            result.patches_processed += 1

            # Check if already applied or rejected
            applied_marker = wisdom_dir / f".applied_{patch.id}"
            rejected_marker = wisdom_dir / f".rejected_{patch.id}"

            if applied_marker.exists() or rejected_marker.exists():
                result.patches_skipped += 1
                continue

            # Create suggestion record
            suggestion = EvolutionSuggestion(
                patch_id=patch.id,
                target_file=patch.target_file,
                patch_type=patch.patch_type.value,
                reasoning=patch.reasoning,
                confidence=patch.confidence.value,
                risk=patch.risk,
                action_taken="suggested",
                source_run_id=run_id,
            )

            # Validate patch
            validation = validate_evolution_patch(patch, repo_root=self._repo_root)

            # Determine if we should apply based on policy
            should_apply = False

            if policy == EvolutionApplyPolicy.AUTO_APPLY_ALL:
                should_apply = validation.valid
            elif policy == EvolutionApplyPolicy.AUTO_APPLY_SAFE:
                # Safe mode: only apply low-risk, high-confidence patches
                # that don't require human review
                is_safe = (
                    patch.risk == "low"
                    and patch.confidence.value == "high"
                    and not patch.human_review_required
                )
                should_apply = validation.valid and is_safe
            # SUGGEST_ONLY: should_apply remains False

            if not validation.valid:
                suggestion.action_taken = "rejected"
                suggestion.rejection_reason = "; ".join(validation.errors)
                result.patches_rejected += 1
                result.rejected_patch_ids.append(
                    {
                        "patch_id": patch.id,
                        "reason": "; ".join(validation.errors),
                    }
                )

                # Write rejection marker
                rejected_marker.write_text(
                    json.dumps(
                        {
                            "rejected_at": datetime.now(timezone.utc).isoformat(),
                            "patch_id": patch.id,
                            "reason": "; ".join(validation.errors),
                            "policy": policy.value,
                            "auto_rejected": True,
                        }
                    )
                )

                # Emit evolution_rejected event
                storage_module.append_event(
                    run_id,
                    RunEvent(
                        run_id=run_id,
                        ts=datetime.now(timezone.utc),
                        kind="evolution_rejected",
                        flow_key="wisdom",
                        payload={
                            "patch_id": patch.id,
                            "target_file": patch.target_file,
                            "patch_type": patch.patch_type.value,
                            "reason": "; ".join(validation.errors),
                            "policy": policy.value,
                        },
                    ),
                )
                result.suggestions.append(suggestion)
                continue

            if not should_apply:
                # Record as suggestion only
                result.patches_suggested += 1

                # Write suggestion marker for tracking
                suggestion_marker = wisdom_dir / f".suggested_{patch.id}"
                suggestion_marker.write_text(
                    json.dumps(
                        {
                            "suggested_at": datetime.now(timezone.utc).isoformat(),
                            "patch_id": patch.id,
                            "target_file": patch.target_file,
                            "reasoning": patch.reasoning,
                            "confidence": patch.confidence.value,
                            "risk": patch.risk,
                            "policy": policy.value,
                            "boundary": boundary,
                        }
                    )
                )

                # Emit evolution_suggested event (not applied, just recorded)
                storage_module.append_event(
                    run_id,
                    RunEvent(
                        run_id=run_id,
                        ts=datetime.now(timezone.utc),
                        kind="evolution_suggested",
                        flow_key="wisdom",
                        payload={
                            "patch_id": patch.id,
                            "target_file": patch.target_file,
                            "patch_type": patch.patch_type.value,
                            "reasoning": patch.reasoning,
                            "confidence": patch.confidence.value,
                            "risk": patch.risk,
                            "policy": policy.value,
                            "boundary": boundary,
                        },
                    ),
                )

                logger.info(
                    "Evolution suggestion recorded: %s for %s (policy: %s)",
                    patch.id,
                    patch.target_file,
                    policy.value,
                )
                result.suggestions.append(suggestion)
                continue

            # Apply the patch
            try:
                apply_result = apply_evolution_patch(
                    patch,
                    dry_run=False,
                    repo_root=self._repo_root,
                    create_backup=True,
                )

                if apply_result.success:
                    now = datetime.now(timezone.utc)
                    suggestion.action_taken = "applied"
                    suggestion.applied_at = now.isoformat()

                    result.patches_applied += 1
                    result.applied_patch_ids.append(patch.id)

                    # Write applied marker
                    applied_marker.write_text(
                        json.dumps(
                            {
                                "applied_at": now.isoformat(),
                                "patch_id": patch.id,
                                "changes_made": apply_result.changes_made,
                                "backup_path": apply_result.backup_path,
                                "policy": policy.value,
                                "boundary": boundary,
                                "auto_applied": True,
                            }
                        )
                    )

                    # Emit evolution_applied event
                    storage_module.append_event(
                        run_id,
                        RunEvent(
                            run_id=run_id,
                            ts=now,
                            kind="evolution_applied",
                            flow_key="wisdom",
                            payload={
                                "patch_id": patch.id,
                                "target_file": patch.target_file,
                                "patch_type": patch.patch_type.value,
                                "changes_made": apply_result.changes_made,
                                "backup_path": apply_result.backup_path,
                                "policy": policy.value,
                                "boundary": boundary,
                            },
                        ),
                    )

                    logger.info(
                        "Evolution applied: %s to %s (policy: %s)",
                        patch.id,
                        patch.target_file,
                        policy.value,
                    )
                else:
                    suggestion.action_taken = "rejected"
                    suggestion.rejection_reason = "; ".join(apply_result.errors)
                    result.patches_rejected += 1
                    result.rejected_patch_ids.append(
                        {
                            "patch_id": patch.id,
                            "reason": "; ".join(apply_result.errors),
                        }
                    )

                    # Emit evolution_rejected event
                    storage_module.append_event(
                        run_id,
                        RunEvent(
                            run_id=run_id,
                            ts=datetime.now(timezone.utc),
                            kind="evolution_rejected",
                            flow_key="wisdom",
                            payload={
                                "patch_id": patch.id,
                                "target_file": patch.target_file,
                                "reason": "; ".join(apply_result.errors),
                                "policy": policy.value,
                            },
                        ),
                    )

                result.suggestions.append(suggestion)

            except Exception as e:
                logger.error(
                    "Failed to apply evolution patch %s: %s",
                    patch.id,
                    e,
                )
                suggestion.action_taken = "rejected"
                suggestion.rejection_reason = f"Application failed: {e}"
                result.patches_rejected += 1
                result.rejected_patch_ids.append(
                    {
                        "patch_id": patch.id,
                        "reason": f"Application failed: {e}",
                    }
                )
                result.suggestions.append(suggestion)

        # Write evolution summary to artifacts
        self._write_evolution_summary(run_id, result, wisdom_dir, policy, boundary)

        # Emit evolution processing completed event
        storage_module.append_event(
            run_id,
            RunEvent(
                run_id=run_id,
                ts=datetime.now(timezone.utc),
                kind="evolution_processing_completed",
                flow_key="wisdom",
                payload={
                    "policy": policy.value,
                    "boundary": boundary,
                    "patches_processed": result.patches_processed,
                    "patches_applied": result.patches_applied,
                    "patches_suggested": result.patches_suggested,
                    "patches_rejected": result.patches_rejected,
                    "patches_skipped": result.patches_skipped,
                    "applied_patch_ids": result.applied_patch_ids,
                },
            ),
        )

        logger.info(
            "Evolution processing completed for run %s: "
            "%d processed, %d applied, %d suggested, %d rejected, %d skipped",
            run_id,
            result.patches_processed,
            result.patches_applied,
            result.patches_suggested,
            result.patches_rejected,
            result.patches_skipped,
        )

        return result

    def _write_evolution_summary(
        self,
        run_id: str,
        result: WisdomApplyResult,
        wisdom_dir: Path,
        policy: EvolutionApplyPolicy,
        boundary: str,
    ) -> None:
        """Write evolution summary to run artifacts.

        Creates an evolution_summary.json file in the wisdom directory
        that records all suggestions, whether applied or not.

        Args:
            run_id: The run identifier.
            result: The WisdomApplyResult to record.
            wisdom_dir: Path to the wisdom directory.
            policy: The evolution policy that was applied.
            boundary: The boundary type.
        """
        import json

        summary = {
            "run_id": run_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "policy": policy.value,
            "boundary": boundary,
            "summary": {
                "patches_processed": result.patches_processed,
                "patches_applied": result.patches_applied,
                "patches_suggested": result.patches_suggested,
                "patches_rejected": result.patches_rejected,
                "patches_skipped": result.patches_skipped,
            },
            "applied_patch_ids": result.applied_patch_ids,
            "rejected_patch_ids": result.rejected_patch_ids,
            "suggestions": [s.to_dict() for s in result.suggestions],
        }

        summary_path = wisdom_dir / "evolution_summary.json"
        summary_path.write_text(
            json.dumps(summary, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        logger.info(
            "Evolution summary written to %s",
            summary_path,
        )

    def _auto_apply_wisdom_patches(
        self,
        state: AutopilotState,
    ) -> WisdomApplyResult:
        """Auto-apply wisdom patches at run boundary.

        This is called during finalization when auto_apply_wisdom is enabled
        and the wisdom flow completed successfully.

        This method now delegates to _process_evolution_at_boundary for
        policy-gated evolution processing.

        Args:
            state: The autopilot state containing config and run info.

        Returns:
            WisdomApplyResult with summary of applied patches.
        """
        return self._process_evolution_at_boundary(state, "run_end")


__all__ = [
    "AutopilotConfig",
    "AutopilotController",
    "AutopilotResult",
    "AutopilotStatus",
    "EvolutionApplyPolicy",
    "EvolutionBoundary",
    "EvolutionSuggestion",
    "WisdomApplyResult",
]
