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

import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from swarm.config.runtime_config import (
    get_cli_path,
    get_context_budget_chars,
    get_engine_mode,
    get_engine_provider,
    get_history_max_older_chars,
    get_history_max_recent_chars,
    get_resolved_context_budgets,
)
from swarm.runtime.path_helpers import (
    ensure_llm_dir,
    ensure_handoff_dir,
    ensure_receipts_dir,
    handoff_envelope_path as make_handoff_envelope_path,
    receipt_path as make_receipt_path,
    transcript_path as make_transcript_path,
)
from swarm.runtime.types import (
    RoutingDecision,
    RoutingSignal,
    RunEvent,
)

# Use the unified SDK adapter - ONLY import from claude_sdk
from swarm.runtime.claude_sdk import (
    check_sdk_available as check_claude_sdk_available,
    ClaudeSDKClient,
    create_tool_policy_hook,
    TelemetryData,
    create_dangerous_command_hook,
    create_telemetry_hook,
)

from ..async_utils import run_async_safely
from ..base import LifecycleCapableEngine
from ..models import (
    FinalizationResult,
    HistoryTruncationInfo,
    StepContext,
    StepResult,
)

# Import from specialized modules
from .prompt_builder import build_prompt, load_agent_persona
from .router import route_step_stub
from .stubs import (
    run_worker_stub,
    finalize_step_stub,
    finalize_from_existing_handoff,
    run_step_stub,
    make_failed_result,
)
from .cli_runner import run_step_cli
from .sdk_runner import (
    run_worker_async,
    finalize_step_async,
    route_step_async,
)

# ContextPack support for hydration phase
from swarm.runtime.context_pack import build_context_pack

logger = logging.getLogger(__name__)


def parse_routing_decision(decision_str: str) -> RoutingDecision:
    """Parse a routing decision string into a RoutingDecision enum.

    Handles both canonical values (advance, loop, terminate, branch) and
    common aliases from external sources (proceed, rerun, blocked, route).

    Args:
        decision_str: The routing decision string (case-insensitive).

    Returns:
        The corresponding RoutingDecision enum value.
        Defaults to ADVANCE if unrecognized.
    """
    decision_lower = decision_str.lower().strip()

    # Canonical mappings
    canonical_map = {
        "advance": RoutingDecision.ADVANCE,
        "loop": RoutingDecision.LOOP,
        "terminate": RoutingDecision.TERMINATE,
        "branch": RoutingDecision.BRANCH,
    }

    if decision_lower in canonical_map:
        return canonical_map[decision_lower]

    # Common aliases
    alias_map = {
        "proceed": RoutingDecision.ADVANCE,
        "continue": RoutingDecision.ADVANCE,
        "next": RoutingDecision.ADVANCE,
        "rerun": RoutingDecision.LOOP,
        "retry": RoutingDecision.LOOP,
        "repeat": RoutingDecision.LOOP,
        "blocked": RoutingDecision.TERMINATE,
        "stop": RoutingDecision.TERMINATE,
        "end": RoutingDecision.TERMINATE,
        "exit": RoutingDecision.TERMINATE,
        "route": RoutingDecision.BRANCH,
        "switch": RoutingDecision.BRANCH,
        "redirect": RoutingDecision.BRANCH,
    }

    if decision_lower in alias_map:
        logger.debug(
            "Mapped routing decision alias '%s' -> %s",
            decision_str,
            alias_map[decision_lower].value,
        )
        return alias_map[decision_lower]

    logger.warning(
        "Unknown routing decision '%s', defaulting to ADVANCE",
        decision_str,
    )
    return RoutingDecision.ADVANCE


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
        profile_id: Optional[str] = None,
        enable_stats_db: bool = True,
    ):
        """Initialize the Claude step engine.

        Args:
            repo_root: Repository root path.
            mode: Override mode selection ("stub", "sdk", or "cli").
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
            "ClaudeStepEngine initialized: mode=%s, provider=%s, cli_cmd=%s, stats_db=%s",
            self._mode,
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
            logger.debug(
                "Claude CLI not available at '%s', will use stub mode", self._cli_cmd
            )

        return self._cli_available

    def _get_resolved_budgets(
        self, flow_key: Optional[str] = None, step_id: Optional[str] = None
    ):
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
            logger.debug("ContextPack already populated for step %s, skipping hydration", ctx.step_id)
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

    def run_worker(
        self, ctx: StepContext
    ) -> Tuple[StepResult, List[RunEvent], str]:
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

    async def run_worker_async(
        self, ctx: StepContext
    ) -> Tuple[StepResult, List[RunEvent], str]:
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
            return finalize_from_existing_handoff(
                ctx, step_result, work_summary, handoff_path
            )

        logger.debug(
            "Handoff not found after work phase for step %s, running fallback finalization",
            ctx.step_id,
        )

        if self.stub_mode or self._mode == "stub":
            return finalize_step_stub(ctx, step_result, work_summary, self.engine_id, self._provider)

        if not self._check_sdk_available():
            logger.warning("SDK not available for finalize_step, falling back to stub")
            return finalize_step_stub(ctx, step_result, work_summary, self.engine_id, self._provider)

        return run_async_safely(
            self._finalize_step_async(ctx, step_result, work_summary)
        )

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
            return finalize_from_existing_handoff(
                ctx, step_result, work_summary, handoff_path
            )

        logger.debug(
            "Handoff not found after work phase for step %s, running fallback finalization",
            ctx.step_id,
        )

        if self.stub_mode or self._mode == "stub":
            return finalize_step_stub(ctx, step_result, work_summary, self.engine_id, self._provider)

        if not self._check_sdk_available():
            logger.warning("SDK not available for finalize_step_async, falling back to stub")
            return finalize_step_stub(ctx, step_result, work_summary, self.engine_id, self._provider)

        return await self._finalize_step_async(ctx, step_result, work_summary)

    def route_step(
        self,
        ctx: StepContext,
        handoff_data: Dict[str, Any],
    ) -> Optional[RoutingSignal]:
        """Determine next step via routing resolver."""
        if self.stub_mode or self._mode == "stub":
            return route_step_stub(ctx, handoff_data)

        if not self._check_sdk_available():
            logger.warning("SDK not available for route_step, falling back to stub")
            return route_step_stub(ctx, handoff_data)

        return run_async_safely(self._route_step_async(ctx, handoff_data))

    async def route_step_async(
        self,
        ctx: StepContext,
        handoff_data: Dict[str, Any],
    ) -> Optional[RoutingSignal]:
        """Async version of route_step."""
        if self.stub_mode or self._mode == "stub":
            return route_step_stub(ctx, handoff_data)

        if not self._check_sdk_available():
            logger.warning("SDK not available for route_step_async, falling back to stub")
            return route_step_stub(ctx, handoff_data)

        return await self._route_step_async(ctx, handoff_data)

    def run_step(self, ctx: StepContext) -> Tuple[StepResult, Iterable[RunEvent]]:
        """Execute a step using Claude Agent SDK, CLI, or stub mode.

        This is the combined lifecycle method that runs:
        1. Hydration (ContextPack assembly)
        2. Work execution
        3. Finalization (JIT handoff)
        4. Routing decision
        """
        # Hydrate context before execution
        ctx = self._hydrate_context(ctx)

        if self._mode == "stub":
            logger.debug("ClaudeStepEngine using stub for step %s (explicit stub mode)", ctx.step_id)
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
    # WP6: PER-STEP SESSION PATTERN
    # =========================================================================

    async def execute_step_session(
        self,
        ctx: StepContext,
        is_terminal: bool = False,
    ) -> Tuple[StepResult, Iterable[RunEvent], Optional[RoutingSignal]]:
        """Execute a step using the new per-step session pattern (WP6).

        This method implements the SDK alignment pattern where each step gets ONE
        session that handles all phases in sequence with hot context preserved:
        1. Work phase: Agent performs its task
        2. Finalize phase: Extract structured handoff envelope
        3. Route phase: Determine next step (if not terminal)

        Benefits over run_step():
        - Preserves hot context between phases (no re-prompting)
        - Uses structured output_format for reliable JSON extraction
        - Implements high-trust tool policy with foot-gun blocking
        - Enables mid-step interrupts for observability

        Args:
            ctx: Step execution context.
            is_terminal: Whether this is the last step in the flow.

        Returns:
            Tuple of (StepResult, events, routing_signal).
        """
        # Hydrate context before execution
        ctx = self._hydrate_context(ctx)

        if self._mode == "stub" or not self._check_sdk_available():
            logger.debug(
                "execute_step_session falling back to stub for step %s (mode=%s, sdk=%s)",
                ctx.step_id,
                self._mode,
                self._check_sdk_available(),
            )
            result, events = run_step_stub(ctx, self.engine_id, self._provider, self._build_prompt)
            return result, events, None

        return await self._execute_step_session_sdk(ctx, is_terminal)

    async def _execute_step_session_sdk(
        self,
        ctx: StepContext,
        is_terminal: bool = False,
    ) -> Tuple[StepResult, Iterable[RunEvent], Optional[RoutingSignal]]:
        """Internal SDK implementation of execute_step_session.

        Uses ClaudeSDKClient for the per-step session pattern.
        """
        start_time = datetime.now(timezone.utc)
        agent_key = ctx.step_agents[0] if ctx.step_agents else "unknown"
        events: List[RunEvent] = []

        ensure_llm_dir(ctx.run_base)
        ensure_receipts_dir(ctx.run_base)

        # Load agent persona for system prompt
        agent_persona = None
        try:
            agent_persona = load_agent_persona(agent_key, ctx.repo_root)
        except Exception as e:
            logger.debug("Could not load agent persona for %s: %s", agent_key, e)

        # Create SDK client with high-trust tool policy and hooks
        pre_hooks = []
        post_hooks = []

        # Add dangerous command blocking hook
        pre_hooks.append(create_dangerous_command_hook())

        # Add telemetry hooks
        telemetry_pre, telemetry_post = create_telemetry_hook()
        pre_hooks.append(telemetry_pre)
        post_hooks.append(telemetry_post)

        client = ClaudeSDKClient(
            repo_root=ctx.repo_root,
            model=None,  # Use default model
            tool_policy_hook=create_tool_policy_hook(),
            pre_tool_hooks=pre_hooks,
            post_tool_hooks=post_hooks,
        )

        # Build the work prompt
        prompt, truncation_info, _ = self._build_prompt(ctx)

        # Determine routing config from context
        routing_config = ctx.extra.get("routing", {})
        is_step_terminal = is_terminal or routing_config.get("kind") == "terminal"

        # Execute step session
        async with client.step_session(
            step_id=ctx.step_id,
            flow_key=ctx.flow_key,
            run_id=ctx.run_id,
            system_prompt_append=agent_persona,
            is_terminal=is_step_terminal,
        ) as session:
            # Phase 1: Work
            work_result = await session.work(prompt=prompt)

            events.append(
                RunEvent(
                    run_id=ctx.run_id,
                    ts=datetime.now(timezone.utc),
                    kind="work_phase_complete",
                    flow_key=ctx.flow_key,
                    step_id=ctx.step_id,
                    agent_key=agent_key,
                    payload={
                        "success": work_result.success,
                        "tool_calls": len(work_result.tool_calls),
                        "output_chars": len(work_result.output),
                        "mode": "session",
                    },
                )
            )

            # Phase 2: Finalize (extract structured handoff envelope)
            ensure_handoff_dir(ctx.run_base)
            draft_handoff_path = ctx.run_base / "handoff" / f"{ctx.step_id}.draft.json"
            committed_handoff_path = make_handoff_envelope_path(ctx.run_base, ctx.step_id)

            finalize_result = await session.finalize(handoff_path=draft_handoff_path)

            if finalize_result.success and finalize_result.envelope:
                # Enrich envelope with file_changes if available from work phase
                envelope_data = dict(finalize_result.envelope)
                if hasattr(work_result, 'file_changes') and work_result.file_changes:
                    envelope_data["file_changes"] = work_result.file_changes

                # Write draft envelope (for debugging)
                with draft_handoff_path.open("w", encoding="utf-8") as f:
                    json.dump(envelope_data, f, indent=2)

                # Write committed envelope at canonical path (for hydration)
                with committed_handoff_path.open("w", encoding="utf-8") as f:
                    json.dump(envelope_data, f, indent=2)

                logger.debug(
                    "Wrote handoff envelope for step %s: draft=%s, committed=%s",
                    ctx.step_id,
                    draft_handoff_path,
                    committed_handoff_path,
                )

                events.append(
                    RunEvent(
                        run_id=ctx.run_id,
                        ts=datetime.now(timezone.utc),
                        kind="finalize_phase_complete",
                        flow_key=ctx.flow_key,
                        step_id=ctx.step_id,
                        agent_key=agent_key,
                        payload={
                            "success": True,
                            "status": envelope_data.get("status", "unknown"),
                            "handoff_path": str(committed_handoff_path),
                            "has_file_changes": "file_changes" in envelope_data,
                        },
                    )
                )

            # Phase 3: Route (determine next step)
            routing_signal: Optional[RoutingSignal] = None
            route_result = None
            if not is_step_terminal:
                route_result = await session.route(routing_config=routing_config)

                if route_result.success and route_result.signal:
                    # Convert dict to RoutingSignal using centralized parser
                    signal_data = route_result.signal
                    decision_str = signal_data.get("decision", "advance")
                    routing_signal = RoutingSignal(
                        decision=parse_routing_decision(decision_str),
                        next_step_id=signal_data.get("next_step_id"),
                        route=signal_data.get("route"),
                        reason=signal_data.get("reason", ""),
                        confidence=float(signal_data.get("confidence", 0.7)),
                        needs_human=bool(signal_data.get("needs_human", False)),
                    )

                    events.append(
                        RunEvent(
                            run_id=ctx.run_id,
                            ts=datetime.now(timezone.utc),
                            kind="route_phase_complete",
                            flow_key=ctx.flow_key,
                            step_id=ctx.step_id,
                            agent_key=agent_key,
                            payload={
                                "decision": routing_signal.decision.value,
                                "next_step_id": routing_signal.next_step_id,
                                "confidence": routing_signal.confidence,
                            },
                        )
                    )

            # Get combined session result
            session_result = session.get_result()

        end_time = datetime.now(timezone.utc)
        duration_ms = int((end_time - start_time).total_seconds() * 1000)

        # Write transcript
        t_path = make_transcript_path(ctx.run_base, ctx.step_id, agent_key, "claude")
        with t_path.open("w", encoding="utf-8") as f:
            for evt in work_result.events:
                f.write(json.dumps(evt) + "\n")

        # Write receipt
        r_path = make_receipt_path(ctx.run_base, ctx.step_id, agent_key)
        receipt = {
            "engine": self.engine_id,
            "mode": "session",
            "session_id": session_result.session_id,
            "provider": self._provider or "claude-sdk",
            "model": work_result.model,
            "step_id": ctx.step_id,
            "flow_key": ctx.flow_key,
            "run_id": ctx.run_id,
            "agent_key": agent_key,
            "started_at": start_time.isoformat() + "Z",
            "completed_at": end_time.isoformat() + "Z",
            "duration_ms": duration_ms,
            "status": "succeeded" if work_result.success else "failed",
            "tokens": work_result.token_counts,
            "tool_calls": len(work_result.tool_calls),
            "phases": {
                "work": work_result.success,
                "finalize": finalize_result.success if finalize_result else False,
                "route": route_result.success if route_result else None,
            },
            "transcript_path": str(t_path.relative_to(ctx.run_base)),
        }

        # Include telemetry data from session result
        if session_result.telemetry:
            receipt["telemetry"] = {
                phase: telem.to_dict() if isinstance(telem, TelemetryData) else telem
                for phase, telem in session_result.telemetry.items()
            }

        if truncation_info:
            receipt["context_truncation"] = truncation_info.to_dict()
        if work_result.error:
            receipt["error"] = work_result.error

        with r_path.open("w", encoding="utf-8") as f:
            json.dump(receipt, f, indent=2)

        # Build StepResult
        output_text = work_result.output
        if len(output_text) > 2000:
            output_text = output_text[:2000] + "... (truncated)"

        step_result = StepResult(
            step_id=ctx.step_id,
            status="succeeded" if work_result.success else "failed",
            output=output_text,
            error=work_result.error,
            duration_ms=duration_ms,
            artifacts={
                "transcript_path": str(t_path),
                "receipt_path": str(r_path),
                "session_id": session_result.session_id,
                "token_counts": work_result.token_counts,
                "model": work_result.model,
            },
        )

        # Add handoff artifacts if available
        if finalize_result and finalize_result.success:
            step_result.artifacts["handoff_path"] = str(handoff_path)
            if finalize_result.envelope:
                step_result.artifacts["handoff"] = {
                    "status": finalize_result.envelope.get("status"),
                    "confidence": finalize_result.envelope.get("confidence"),
                }

        return step_result, events, routing_signal

    def execute_step_session_sync(
        self,
        ctx: StepContext,
        is_terminal: bool = False,
    ) -> Tuple[StepResult, Iterable[RunEvent], Optional[RoutingSignal]]:
        """Synchronous wrapper for execute_step_session.

        For callers that need synchronous execution.
        """
        return run_async_safely(self.execute_step_session(ctx, is_terminal))

    # =========================================================================
    # INTERNAL ASYNC IMPLEMENTATIONS (delegate to sdk_runner)
    # =========================================================================

    async def _run_worker_async(
        self, ctx: StepContext
    ) -> Tuple[StepResult, List[RunEvent], str]:
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
    ) -> Optional[RoutingSignal]:
        """Async implementation of route_step."""
        # Prefer self.repo_root but fall back to ctx.repo_root
        effective_repo_root = self.repo_root or ctx.repo_root
        return await route_step_async(
            ctx=ctx,
            handoff_data=handoff_data,
            repo_root=effective_repo_root,
        )

    def _run_step_sdk(self, ctx: StepContext) -> Tuple[StepResult, Iterable[RunEvent]]:
        """Execute a step using the Claude Agent SDK."""
        return run_async_safely(self._run_step_sdk_async(ctx))

    async def _run_step_sdk_async(
        self, ctx: StepContext
    ) -> Tuple[StepResult, Iterable[RunEvent]]:
        """Execute a step using the Claude Agent SDK (async implementation).

        This is a combined implementation that handles work + finalization + routing
        in a single flow for backwards compatibility with run_step().
        """
        # For run_step(), we use the lifecycle methods but combine them
        step_result, events, work_summary = await self._run_worker_async(ctx)

        if step_result.status == "failed":
            return step_result, events

        # Finalize
        finalization = await self.finalize_step_async(ctx, step_result, work_summary)
        events.extend(finalization.events)

        # Route if we have handoff data
        if finalization.handoff_data:
            routing_signal = await self.route_step_async(ctx, finalization.handoff_data)
            if routing_signal and finalization.envelope:
                # Update envelope with routing signal
                finalization.envelope.routing_signal = routing_signal

        # Update result with finalization artifacts
        if step_result.artifacts is None:
            step_result.artifacts = {}

        if finalization.envelope:
            envelope_path = make_handoff_envelope_path(ctx.run_base, ctx.step_id)
            if envelope_path.exists():
                step_result.artifacts["handoff_envelope_path"] = str(envelope_path)

        if finalization.handoff_data:
            step_result.artifacts["handoff"] = {
                "status": finalization.handoff_data.get("status"),
                "proposed_next_step": finalization.handoff_data.get("proposed_next_step"),
            }

        return step_result, events
