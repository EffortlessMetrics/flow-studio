"""
engine.py - ClaudeStepEngine implementation.

This is the main Claude step engine that implements LifecycleCapableEngine
with support for stub, sdk, and cli modes.

The heavy lifting is delegated to specialized modules:
- stubs.py: Zero-cost stub implementations for testing/CI
- cli_runner.py: CLI-based execution
- sdk_runner.py: SDK-based async execution
- prompt_builder.py: Prompt construction
- envelope.py: Handoff envelope management
- router.py: Routing logic
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from swarm.config.runtime_config import (
    get_cli_path,
    get_context_budget_chars,
    get_engine_execution,
    get_engine_mode,
    get_engine_provider,
    get_history_max_older_chars,
    get_history_max_recent_chars,
    get_resolved_context_budgets,
)

# Use the unified SDK adapter
from swarm.runtime.claude_sdk import check_sdk_available as check_claude_sdk_available

# ContextPack support for hydration phase
from swarm.runtime.context_pack import build_context_pack
from swarm.runtime.path_helpers import (
    handoff_envelope_path as make_handoff_envelope_path,
)
from swarm.runtime.receipt_io import make_receipt_data, write_step_receipt
from swarm.runtime.types import (
    RoutingSignal,
    RunEvent,
)

from ..async_utils import run_async_safely
from ..base import LifecycleCapableEngine
from ..models import (
    FinalizationResult,
    HistoryTruncationInfo,
    StepContext,
    StepResult,
)
from .cli_runner import run_step_cli

# Import from specialized modules
from .prompt_builder import build_prompt
from .router import route_step_stub
from .sdk_runner import (
    finalize_step_async,
    route_step_async,
    run_worker_async,
)
from .session_runner import (
    execute_step_session as _execute_step_session,
)
from .session_runner import (
    execute_step_session_sync as _execute_step_session_sync,
)
from .stubs import (
    finalize_from_existing_handoff,
    finalize_step_stub,
    make_failed_result,
    run_step_stub,
    run_worker_stub,
)

logger = logging.getLogger(__name__)


class ClaudeStepEngine(LifecycleCapableEngine):
    """Step engine using Claude Agent SDK or CLI.

    This engine supports three modes:
    - stub: Returns synthetic results without calling real API (default, for CI/testing)
    - sdk: Uses the Claude Agent SDK to execute steps with real LLM calls
    - cli: Uses the Claude CLI (`claude --output-format stream-json`) for execution

    Mode is controlled by:
    1. SWARM_CLAUDE_STEP_ENGINE_MODE env var (stub, sdk, or cli)
    2. Config file swarm/config/runtime.yaml
    3. Default: stub

    Lifecycle Methods (for orchestrator control):
    - run_worker(): Execute work phase only (prompt -> LLM -> output)
    - finalize_step(): JIT finalization to extract handoff state
    - route_step(): Determine next step via routing resolver
    - run_step(): Convenience method that calls all phases in sequence
    """

    @property
    def HISTORY_BUDGET_CHARS(self) -> int:
        """Total budget for all previous step history (global default)."""
        return get_context_budget_chars()

    @property
    def RECENT_STEP_MAX_CHARS(self) -> int:
        """Max chars for the most recent step output (global default)."""
        return get_history_max_recent_chars()

    @property
    def OLDER_STEP_MAX_CHARS(self) -> int:
        """Max chars for older step outputs (global default)."""
        return get_history_max_older_chars()

    # Tool mappings by step type
    ANALYSIS_TOOLS = ["Read", "Grep", "Glob"]
    BUILD_TOOLS = ["Read", "Write", "Edit", "Bash", "Grep", "Glob"]
    DEFAULT_TOOLS = ["Read", "Write", "Edit", "Bash", "Grep", "Glob"]

    # Step ID patterns for tool selection
    ANALYSIS_STEP_PATTERNS = ["context", "analyze", "assess", "review", "audit", "check"]
    BUILD_STEP_PATTERNS = ["implement", "author", "write", "fix", "create", "mutate"]

    def __init__(
        self,
        repo_root: Optional[Path] = None,
        mode: Optional[str] = None,
        execution: Optional[str] = None,
        profile_id: Optional[str] = None,
        enable_stats_db: bool = True,
    ):
        """Initialize the Claude step engine.

        Args:
            repo_root: Repository root path.
            mode: Override mode selection ("stub", "sdk", or "cli").
                  If None, reads from config/environment.
            execution: Override execution pattern ("legacy" or "session").
                  If None, reads from config/environment.
            profile_id: Optional profile ID for flow-aware budget resolution.
            enable_stats_db: Whether to record stats to DuckDB. Default True.
        """
        self.repo_root = repo_root
        self._profile_id = profile_id

        # Determine mode: override > config > default
        if mode:
            self._mode = mode
        else:
            self._mode = get_engine_mode("claude")

        # Determine execution pattern: override > config > default
        if execution:
            self._execution = execution
        else:
            self._execution = get_engine_execution("claude")

        self.stub_mode = self._mode == "stub"
        self._sdk_available: Optional[bool] = None
        self._cli_available: Optional[bool] = None

        # Provider configuration
        self._provider = get_engine_provider("claude")
        self._cli_cmd = get_cli_path("claude")

        # Stats database for telemetry
        self._stats_db = None
        if enable_stats_db:
            try:
                from swarm.runtime.db import get_stats_db

                self._stats_db = get_stats_db()
            except Exception as e:
                logger.debug("StatsDB not available: %s", e)

        logger.debug(
            "ClaudeStepEngine initialized: mode=%s, execution=%s, provider=%s, cli_cmd=%s, stats_db=%s",
            self._mode,
            self._execution,
            self._provider,
            self._cli_cmd,
            self._stats_db is not None,
        )

    @property
    def engine_id(self) -> str:
        return "claude-step"

    def _check_sdk_available(self) -> bool:
        """Check if the Claude Code SDK is available.

        Uses the unified claude_sdk adapter for consistent SDK access.
        Caches the result after first check.

        Returns:
            True if claude_code_sdk can be imported, False otherwise.
        """
        if self._sdk_available is None:
            self._sdk_available = check_claude_sdk_available()
            if not self._sdk_available:
                logger.debug("claude_code_sdk not available (via adapter)")
        return self._sdk_available

    def _check_cli_available(self) -> bool:
        """Check if the Claude CLI is available.

        Returns:
            True if the CLI executable can be found, False otherwise.
        """
        if self._cli_available is not None:
            return self._cli_available

        self._cli_available = shutil.which(self._cli_cmd) is not None
        if not self._cli_available:
            logger.debug("Claude CLI not available at '%s', will use stub mode", self._cli_cmd)

        return self._cli_available

    def _get_resolved_budgets(self, flow_key: Optional[str] = None, step_id: Optional[str] = None):
        """Get resolved budgets for the given flow/step context."""
        return get_resolved_context_budgets(
            flow_key=flow_key,
            step_id=step_id,
            profile_id=self._profile_id,
        )

    def _hydrate_context(self, ctx: StepContext) -> StepContext:
        """Hydrate step context with ContextPack if not already populated.

        This implements the "Hydrate" phase of the industrialized lifecycle:
        1. Build ContextPack from previous envelopes and upstream artifacts
        2. Inject into ctx.extra["context_pack"]
        3. Return the hydrated context

        The ContextPack provides structured context (summaries, artifacts, routing)
        instead of raw history, enabling higher-fidelity context handoff.

        Args:
            ctx: The step context to hydrate.

        Returns:
            The hydrated StepContext with context_pack populated.
        """
        # Skip if already hydrated
        if ctx.extra.get("context_pack"):
            logger.debug(
                "ContextPack already populated for step %s, skipping hydration", ctx.step_id
            )
            return ctx

        # Build ContextPack
        # Prefer self.repo_root but fall back to ctx.repo_root
        effective_repo_root = self.repo_root or ctx.repo_root
        try:
            context_pack = build_context_pack(
                ctx=ctx,
                run_state=None,  # Not using in-memory run state
                repo_root=effective_repo_root,
            )

            # Inject into context
            if ctx.extra is None:
                ctx.extra = {}
            ctx.extra["context_pack"] = context_pack

            logger.debug(
                "Hydrated context for step %s: %d envelopes, %d artifacts",
                ctx.step_id,
                len(context_pack.previous_envelopes),
                len(context_pack.upstream_artifacts),
            )

        except Exception as e:
            logger.warning("Failed to build ContextPack for step %s: %s", ctx.step_id, e)
            # Continue without ContextPack - fallback to raw history

        return ctx

    def _get_tools_for_step(self, ctx: StepContext) -> List[str]:
        """Determine which tools to allow for a step based on its type."""
        step_id_lower = ctx.step_id.lower()
        step_role_lower = ctx.step_role.lower()

        for pattern in self.ANALYSIS_STEP_PATTERNS:
            if pattern in step_id_lower or pattern in step_role_lower:
                return self.ANALYSIS_TOOLS

        for pattern in self.BUILD_STEP_PATTERNS:
            if pattern in step_id_lower or pattern in step_role_lower:
                return self.BUILD_TOOLS

        return self.DEFAULT_TOOLS

    def _build_prompt(
        self, ctx: StepContext
    ) -> Tuple[str, Optional[HistoryTruncationInfo], Optional[str]]:
        """Build a context-aware prompt for a step.

        Delegates to prompt_builder module.
        """
        return build_prompt(ctx, self.repo_root, self._profile_id)

    # =========================================================================
    # PUBLIC LIFECYCLE METHODS
    # =========================================================================

    def run_worker(self, ctx: StepContext) -> Tuple[StepResult, List[RunEvent], str]:
        """Execute the work phase only (no finalization or routing).

        This method implements automatic context hydration:
        1. If ctx.extra["context_pack"] is not set, builds ContextPack from disk
        2. Executes the work phase with hydrated context
        3. Returns (StepResult, events, work_summary)
        """
        # Hydrate context before execution
        ctx = self._hydrate_context(ctx)

        if self.stub_mode or self._mode == "stub":
            return run_worker_stub(ctx, self.engine_id)

        if not self._check_sdk_available():
            logger.warning("SDK not available for run_worker, falling back to stub")
            return run_worker_stub(ctx, self.engine_id)

        return run_async_safely(self._run_worker_async(ctx))

    async def run_worker_async(self, ctx: StepContext) -> Tuple[StepResult, List[RunEvent], str]:
        """Async version of run_worker for async-native orchestration.

        Implements automatic context hydration before execution.
        """
        # Hydrate context before execution
        ctx = self._hydrate_context(ctx)

        if self.stub_mode or self._mode == "stub":
            return run_worker_stub(ctx, self.engine_id)

        if not self._check_sdk_available():
            logger.warning("SDK not available for run_worker_async, falling back to stub")
            return run_worker_stub(ctx, self.engine_id)

        return await self._run_worker_async(ctx)

    def finalize_step(
        self,
        ctx: StepContext,
        step_result: StepResult,
        work_summary: str,
    ) -> FinalizationResult:
        """Execute JIT finalization to extract handoff state."""
        # Check if handoff was already written during work phase
        handoff_dir = ctx.run_base / "handoff"
        handoff_path = handoff_dir / f"{ctx.step_id}.draft.json"

        if handoff_path.exists():
            logger.debug(
                "Handoff already written during work phase for step %s (inline finalization)",
                ctx.step_id,
            )
            return finalize_from_existing_handoff(ctx, step_result, work_summary, handoff_path)

        logger.debug(
            "Handoff not found after work phase for step %s, running fallback finalization",
            ctx.step_id,
        )

        if self.stub_mode or self._mode == "stub":
            return finalize_step_stub(
                ctx, step_result, work_summary, self.engine_id, self._provider
            )

        if not self._check_sdk_available():
            logger.warning("SDK not available for finalize_step, falling back to stub")
            return finalize_step_stub(
                ctx, step_result, work_summary, self.engine_id, self._provider
            )

        return run_async_safely(self._finalize_step_async(ctx, step_result, work_summary))

    async def finalize_step_async(
        self,
        ctx: StepContext,
        step_result: StepResult,
        work_summary: str,
    ) -> FinalizationResult:
        """Async version of finalize_step."""
        handoff_dir = ctx.run_base / "handoff"
        handoff_path = handoff_dir / f"{ctx.step_id}.draft.json"

        if handoff_path.exists():
            logger.debug(
                "Handoff already written during work phase for step %s (inline finalization)",
                ctx.step_id,
            )
            return finalize_from_existing_handoff(ctx, step_result, work_summary, handoff_path)

        logger.debug(
            "Handoff not found after work phase for step %s, running fallback finalization",
            ctx.step_id,
        )

        if self.stub_mode or self._mode == "stub":
            return finalize_step_stub(
                ctx, step_result, work_summary, self.engine_id, self._provider
            )

        if not self._check_sdk_available():
            logger.warning("SDK not available for finalize_step_async, falling back to stub")
            return finalize_step_stub(
                ctx, step_result, work_summary, self.engine_id, self._provider
            )

        return await self._finalize_step_async(ctx, step_result, work_summary)

    def route_step(
        self,
        ctx: StepContext,
        handoff_data: Dict[str, Any],
        spec_model: Optional[str] = None,
    ) -> Optional[RoutingSignal]:
        """Determine next step via routing resolver.

        Args:
            ctx: Step execution context.
            handoff_data: Parsed handoff data from finalization.
            spec_model: Model from spec for consistent model usage across phases.
        """
        if self.stub_mode or self._mode == "stub":
            return route_step_stub(ctx, handoff_data)

        if not self._check_sdk_available():
            logger.warning("SDK not available for route_step, falling back to stub")
            return route_step_stub(ctx, handoff_data)

        return run_async_safely(self._route_step_async(ctx, handoff_data, spec_model=spec_model))

    async def route_step_async(
        self,
        ctx: StepContext,
        handoff_data: Dict[str, Any],
        spec_model: Optional[str] = None,
    ) -> Optional[RoutingSignal]:
        """Async version of route_step.

        Args:
            ctx: Step execution context.
            handoff_data: Parsed handoff data from finalization.
            spec_model: Model from spec for consistent model usage across phases.
        """
        if self.stub_mode or self._mode == "stub":
            return route_step_stub(ctx, handoff_data)

        if not self._check_sdk_available():
            logger.warning("SDK not available for route_step_async, falling back to stub")
            return route_step_stub(ctx, handoff_data)

        return await self._route_step_async(ctx, handoff_data, spec_model=spec_model)

    def run_step(self, ctx: StepContext) -> Tuple[StepResult, Iterable[RunEvent]]:
        """Execute a step using Claude Agent SDK, CLI, or stub mode.

        This is the combined lifecycle method that runs:
        1. Hydration (ContextPack assembly)
        2. Work execution
        3. Finalization (JIT handoff)
        4. Routing decision

        Execution pattern is controlled by the `execution` config:
        - legacy: Runs each phase separately (hydrate, work, finalize, route)
        - session: Uses WP6 per-step session pattern (single session for all phases)
        """
        # Hydrate context before execution
        ctx = self._hydrate_context(ctx)

        # Session execution dispatch: execution=session AND mode=sdk AND SDK available
        if self._execution == "session" and self._mode == "sdk":
            if self._check_sdk_available():
                logger.debug(
                    "ClaudeStepEngine using session execution for step %s",
                    ctx.step_id,
                )
                try:
                    result, events, routing_signal = self.execute_step_session_sync(ctx)
                    # Session execution returns routing_signal separately;
                    # for run_step() compatibility, we just return result and events
                    return result, events
                except Exception as e:
                    logger.warning(
                        "Session execution failed for step %s: %s, falling back to legacy",
                        ctx.step_id,
                        e,
                    )
                    # Fall through to legacy execution
            else:
                logger.info(
                    "Session execution requested but SDK not available for step %s, "
                    "falling back to legacy mode",
                    ctx.step_id,
                )

        # Legacy execution modes
        if self._mode == "stub":
            logger.debug(
                "ClaudeStepEngine using stub for step %s (explicit stub mode)", ctx.step_id
            )
            return run_step_stub(ctx, self.engine_id, self._provider, self._build_prompt)

        if self._mode == "cli":
            if self._check_cli_available():
                logger.debug("ClaudeStepEngine using CLI for step %s", ctx.step_id)
                try:
                    return run_step_cli(
                        ctx, self._cli_cmd, self.engine_id, self._provider, self._build_prompt
                    )
                except Exception as e:
                    logger.warning("CLI execution failed for step %s: %s", ctx.step_id, e)
                    return make_failed_result(ctx, f"CLI execution failed: {e}")
            else:
                logger.debug(
                    "ClaudeStepEngine CLI not available for step %s, falling back to stub",
                    ctx.step_id,
                )
                return run_step_stub(ctx, self.engine_id, self._provider, self._build_prompt)

        if self._mode == "sdk":
            if self._check_sdk_available():
                logger.debug("ClaudeStepEngine using SDK for step %s", ctx.step_id)
                try:
                    return self._run_step_sdk(ctx)
                except Exception as e:
                    logger.warning("SDK execution failed for step %s: %s", ctx.step_id, e)
                    return make_failed_result(ctx, f"SDK execution failed: {e}")
            else:
                logger.debug(
                    "ClaudeStepEngine SDK not available for step %s, falling back to stub",
                    ctx.step_id,
                )
                return run_step_stub(ctx, self.engine_id, self._provider, self._build_prompt)

        # Default: try SDK, then CLI, then stub
        if self._check_sdk_available():
            logger.debug("ClaudeStepEngine using SDK for step %s (auto-detected)", ctx.step_id)
            try:
                return self._run_step_sdk(ctx)
            except Exception as e:
                logger.warning("SDK execution failed for step %s: %s", ctx.step_id, e)
                return make_failed_result(ctx, f"SDK execution failed: {e}")

        if self._check_cli_available():
            logger.debug("ClaudeStepEngine using CLI for step %s (auto-detected)", ctx.step_id)
            try:
                return run_step_cli(
                    ctx, self._cli_cmd, self.engine_id, self._provider, self._build_prompt
                )
            except Exception as e:
                logger.warning("CLI execution failed for step %s: %s", ctx.step_id, e)
                return make_failed_result(ctx, f"CLI execution failed: {e}")

        logger.debug("ClaudeStepEngine using stub for step %s (no execution backend)", ctx.step_id)
        return run_step_stub(ctx, self.engine_id, self._provider, self._build_prompt)

    # =========================================================================
    # WP6: PER-STEP SESSION PATTERN (delegated to session_runner)
    # =========================================================================

    async def execute_step_session(
        self,
        ctx: StepContext,
        is_terminal: bool = False,
    ) -> Tuple[StepResult, Iterable[RunEvent], Optional[RoutingSignal]]:
        """Execute a step using the new per-step session pattern (WP6).

        Delegates to session_runner module. See session_runner.execute_step_session
        for full documentation.
        """
        return await _execute_step_session(self, ctx, is_terminal)

    def execute_step_session_sync(
        self,
        ctx: StepContext,
        is_terminal: bool = False,
    ) -> Tuple[StepResult, Iterable[RunEvent], Optional[RoutingSignal]]:
        """Synchronous wrapper for execute_step_session."""
        return _execute_step_session_sync(self, ctx, is_terminal)

    # =========================================================================
    # INTERNAL ASYNC IMPLEMENTATIONS (delegate to sdk_runner)
    # =========================================================================

    async def _run_worker_async(self, ctx: StepContext) -> Tuple[StepResult, List[RunEvent], str]:
        """Async implementation of run_worker."""
        # Prefer self.repo_root but fall back to ctx.repo_root
        effective_repo_root = self.repo_root or ctx.repo_root
        return await run_worker_async(
            ctx=ctx,
            repo_root=effective_repo_root,
            profile_id=self._profile_id,
            build_prompt_fn=self._build_prompt,
            stats_db=self._stats_db,
        )

    async def _finalize_step_async(
        self,
        ctx: StepContext,
        step_result: StepResult,
        work_summary: str,
    ) -> FinalizationResult:
        """Async implementation of finalize_step."""
        # Prefer self.repo_root but fall back to ctx.repo_root
        effective_repo_root = self.repo_root or ctx.repo_root
        return await finalize_step_async(
            ctx=ctx,
            step_result=step_result,
            work_summary=work_summary,
            repo_root=effective_repo_root,
        )

    async def _route_step_async(
        self,
        ctx: StepContext,
        handoff_data: Dict[str, Any],
        spec_model: Optional[str] = None,
    ) -> Optional[RoutingSignal]:
        """Async implementation of route_step."""
        # Prefer self.repo_root but fall back to ctx.repo_root
        effective_repo_root = self.repo_root or ctx.repo_root
        return await route_step_async(
            ctx=ctx,
            handoff_data=handoff_data,
            repo_root=effective_repo_root,
            spec_model=spec_model,
        )

    def _run_step_sdk(self, ctx: StepContext) -> Tuple[StepResult, Iterable[RunEvent]]:
        """Execute a step using the Claude Agent SDK."""
        return run_async_safely(self._run_step_sdk_async(ctx))

    async def _run_step_sdk_async(self, ctx: StepContext) -> Tuple[StepResult, Iterable[RunEvent]]:
        """Execute a step using the Claude Agent SDK (async implementation).

        This is a combined implementation that handles work + finalization + routing
        in a single flow for backwards compatibility with run_step().
        """
        from datetime import datetime, timezone

        start_time = datetime.now(timezone.utc)
        agent_key = ctx.step_agents[0] if ctx.step_agents else "unknown"
        routing_signal = None

        # For run_step(), we use the lifecycle methods but combine them
        step_result, events, work_summary = await self._run_worker_async(ctx)

        if step_result.status == "failed":
            # Write receipt even for failed steps
            end_time = datetime.now(timezone.utc)
            receipt_data = make_receipt_data(
                engine=self.engine_id,
                mode=self._mode,
                execution_mode="legacy",
                provider=self._provider or "claude-sdk",
                step_id=ctx.step_id,
                flow_key=ctx.flow_key,
                run_id=ctx.run_id,
                agent_key=agent_key,
                started_at=start_time,
                completed_at=end_time,
                duration_ms=step_result.duration_ms,
                status=step_result.status,
                model=step_result.artifacts.get("model", "unknown")
                if step_result.artifacts
                else "unknown",
                tokens=step_result.artifacts.get("token_counts") if step_result.artifacts else None,
                transcript_path=step_result.artifacts.get("transcript_path")
                if step_result.artifacts
                else None,
                error=step_result.error,
            )
            write_step_receipt(ctx.run_base, receipt_data)
            return step_result, events

        # Finalize
        finalization = await self.finalize_step_async(ctx, step_result, work_summary)
        events.extend(finalization.events)

        # Route if we have handoff data
        if finalization.handoff_data:
            # Extract spec model from work phase for consistent model usage in routing
            spec_model = step_result.artifacts.get("spec_model") if step_result.artifacts else None
            routing_signal = await self.route_step_async(
                ctx, finalization.handoff_data, spec_model=spec_model
            )
            if routing_signal and finalization.envelope:
                # Update envelope with routing signal
                finalization.envelope.routing_signal = routing_signal

        # Update result with finalization artifacts
        if step_result.artifacts is None:
            step_result.artifacts = {}

        envelope_path_str = None
        if finalization.envelope:
            envelope_path = make_handoff_envelope_path(ctx.run_base, ctx.step_id)
            if envelope_path.exists():
                step_result.artifacts["handoff_envelope_path"] = str(envelope_path)
                envelope_path_str = str(envelope_path.relative_to(ctx.run_base))

        if finalization.handoff_data:
            step_result.artifacts["handoff"] = {
                "status": finalization.handoff_data.get("status"),
                "proposed_next_step": finalization.handoff_data.get("proposed_next_step"),
            }

        # Write receipt for legacy SDK execution
        end_time = datetime.now(timezone.utc)
        routing_signal_dict = None
        if routing_signal:
            routing_signal_dict = {
                "decision": routing_signal.decision.value
                if hasattr(routing_signal.decision, "value")
                else str(routing_signal.decision),
                "next_step_id": routing_signal.next_step_id,
                "reason": routing_signal.reason,
                "confidence": routing_signal.confidence,
                "needs_human": routing_signal.needs_human,
            }

        receipt_data = make_receipt_data(
            engine=self.engine_id,
            mode=self._mode,
            execution_mode="legacy",
            provider=self._provider or "claude-sdk",
            step_id=ctx.step_id,
            flow_key=ctx.flow_key,
            run_id=ctx.run_id,
            agent_key=agent_key,
            started_at=start_time,
            completed_at=end_time,
            duration_ms=step_result.duration_ms,
            status=step_result.status,
            model=step_result.artifacts.get("model", "unknown")
            if step_result.artifacts
            else "unknown",
            tokens=step_result.artifacts.get("token_counts") if step_result.artifacts else None,
            transcript_path=step_result.artifacts.get("transcript_path")
            if step_result.artifacts
            else None,
            handoff_envelope_path=envelope_path_str,
            routing_signal=routing_signal_dict,
            error=step_result.error,
        )
        r_path = write_step_receipt(ctx.run_base, receipt_data)
        step_result.artifacts["receipt_path"] = str(r_path)

        return step_result, events
