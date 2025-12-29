"""
engine.py - ClaudeStepEngine implementation.

This is the main Claude step engine that implements LifecycleCapableEngine
with support for stub, sdk, and cli modes.
"""

from __future__ import annotations

import json
import logging
import shlex
import shutil
import subprocess
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
from swarm.runtime.diff_scanner import (
    file_changes_to_dict,
    scan_file_changes,
    scan_file_changes_sync,
)
from swarm.runtime.path_helpers import (
    ensure_handoff_dir,
    ensure_llm_dir,
    ensure_receipts_dir,
    handoff_envelope_path as make_handoff_envelope_path,
    receipt_path as make_receipt_path,
    transcript_path as make_transcript_path,
)
from swarm.runtime.resolvers import (
    build_finalization_prompt,
    load_envelope_writer_prompt,
)
from swarm.runtime.types import (
    HandoffEnvelope,
    RoutingDecision,
    RoutingSignal,
    RunEvent,
    handoff_envelope_to_dict,
)

# Use the unified SDK adapter - ONLY import from claude_sdk
from swarm.runtime.claude_sdk import (
    SDK_AVAILABLE as CLAUDE_SDK_AVAILABLE,
    check_sdk_available as check_claude_sdk_available,
    create_high_trust_options,
    get_sdk_module,
    # WP6: Per-step session pattern
    ClaudeSDKClient,
    create_tool_policy_hook,
    is_blocked_command,
    WorkPhaseResult,
    FinalizePhaseResult,
    RoutePhaseResult,
    StepSessionResult,
    TelemetryData,
    HANDOFF_ENVELOPE_SCHEMA,
    ROUTING_SIGNAL_SCHEMA,
    # Hook factory functions for guardrails and telemetry
    create_dangerous_command_hook,
    create_telemetry_hook,
    create_file_access_audit_hook,
)

from ..async_utils import run_async_safely
from ..base import LifecycleCapableEngine
from ..models import (
    FinalizationResult,
    HistoryTruncationInfo,
    RoutingContext,
    StepContext,
    StepResult,
)

from .envelope import create_fallback_envelope, write_envelope_to_disk, write_handoff_envelope
from .prompt_builder import build_prompt, load_agent_persona
from .router import check_microloop_termination, route_step_stub, run_router_session
from .spec_adapter import try_compile_from_spec

# ContextPack support for hydration phase
from swarm.runtime.context_pack import build_context_pack, ContextPack

logger = logging.getLogger(__name__)


# JIT Finalization prompt template (for fallback separate-call finalization)
JIT_FINALIZATION_PROMPT = """
---
Your work session is complete. Now create a structured handoff for the next step.

Use the `Write` tool to create a file at: {handoff_path}

The file MUST be valid JSON with this exact structure:
```json
{{
  "step_id": "{step_id}",
  "flow_key": "{flow_key}",
  "run_id": "{run_id}",
  "status": "VERIFIED | UNVERIFIED | PARTIAL | BLOCKED",
  "summary": "2-paragraph summary of what you accomplished and any issues encountered",
  "artifacts": {{
    "artifact_name": "relative/path/from/run_base"
  }},
  "proposed_next_step": "step_id or null if flow should terminate",
  "notes_for_next_step": "What the next agent should know",
  "confidence": 0.0 to 1.0
}}
```

Guidelines:
- status: VERIFIED if you completed the task successfully, UNVERIFIED if tests fail or work is incomplete, PARTIAL if some work done but blocked, BLOCKED if you cannot proceed
- summary: Be concise but include what changed, what was tested, any concerns
- artifacts: List ALL files you created or modified (paths relative to run base)
- proposed_next_step: Based on your status and the flow spec, where should we go next?
- confidence: How confident are you in this handoff? (1.0 = very confident)

Write the file now.
---
"""


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
        try:
            context_pack = build_context_pack(
                ctx=ctx,
                run_state=None,  # Not using in-memory run state
                repo_root=self.repo_root,
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
            return self._run_worker_stub(ctx)

        if not self._check_sdk_available():
            logger.warning("SDK not available for run_worker, falling back to stub")
            return self._run_worker_stub(ctx)

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
            return self._run_worker_stub(ctx)

        if not self._check_sdk_available():
            logger.warning("SDK not available for run_worker_async, falling back to stub")
            return self._run_worker_stub(ctx)

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
            return self._finalize_from_existing_handoff(
                ctx, step_result, work_summary, handoff_path
            )

        logger.debug(
            "Handoff not found after work phase for step %s, running fallback finalization",
            ctx.step_id,
        )

        if self.stub_mode or self._mode == "stub":
            return self._finalize_step_stub(ctx, step_result, work_summary)

        if not self._check_sdk_available():
            logger.warning("SDK not available for finalize_step, falling back to stub")
            return self._finalize_step_stub(ctx, step_result, work_summary)

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
            return self._finalize_from_existing_handoff(
                ctx, step_result, work_summary, handoff_path
            )

        logger.debug(
            "Handoff not found after work phase for step %s, running fallback finalization",
            ctx.step_id,
        )

        if self.stub_mode or self._mode == "stub":
            return self._finalize_step_stub(ctx, step_result, work_summary)

        if not self._check_sdk_available():
            logger.warning("SDK not available for finalize_step_async, falling back to stub")
            return self._finalize_step_stub(ctx, step_result, work_summary)

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
            return self._run_step_stub(ctx)

        if self._mode == "cli":
            if self._check_cli_available():
                logger.debug("ClaudeStepEngine using CLI for step %s", ctx.step_id)
                try:
                    return self._run_step_cli(ctx)
                except Exception as e:
                    logger.warning("CLI execution failed for step %s: %s", ctx.step_id, e)
                    return self._make_failed_result(ctx, f"CLI execution failed: {e}")
            else:
                logger.debug(
                    "ClaudeStepEngine CLI not available for step %s, falling back to stub",
                    ctx.step_id,
                )
                return self._run_step_stub(ctx)

        if self._mode == "sdk":
            if self._check_sdk_available():
                logger.debug("ClaudeStepEngine using SDK for step %s", ctx.step_id)
                try:
                    return self._run_step_sdk(ctx)
                except Exception as e:
                    logger.warning("SDK execution failed for step %s: %s", ctx.step_id, e)
                    return self._make_failed_result(ctx, f"SDK execution failed: {e}")
            else:
                logger.debug(
                    "ClaudeStepEngine SDK not available for step %s, falling back to stub",
                    ctx.step_id,
                )
                return self._run_step_stub(ctx)

        # Default: try SDK, then CLI, then stub
        if self._check_sdk_available():
            logger.debug("ClaudeStepEngine using SDK for step %s (auto-detected)", ctx.step_id)
            try:
                return self._run_step_sdk(ctx)
            except Exception as e:
                logger.warning("SDK execution failed for step %s: %s", ctx.step_id, e)
                return self._make_failed_result(ctx, f"SDK execution failed: {e}")

        if self._check_cli_available():
            logger.debug("ClaudeStepEngine using CLI for step %s (auto-detected)", ctx.step_id)
            try:
                return self._run_step_cli(ctx)
            except Exception as e:
                logger.warning("CLI execution failed for step %s: %s", ctx.step_id, e)
                return self._make_failed_result(ctx, f"CLI execution failed: {e}")

        logger.debug("ClaudeStepEngine using stub for step %s (no execution backend)", ctx.step_id)
        return self._run_step_stub(ctx)

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
            result, events = self._run_step_stub(ctx)
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
        # Set up pre/post tool hooks for guardrails and telemetry
        pre_hooks = []
        post_hooks = []

        # Add dangerous command blocking hook
        pre_hooks.append(create_dangerous_command_hook())

        # Add telemetry hooks
        telemetry_pre, telemetry_post = create_telemetry_hook()
        pre_hooks.append(telemetry_pre)
        post_hooks.append(telemetry_post)

        # Optional: Add file access auditing (useful for debug/compliance)
        # audit_log = []
        # post_hooks.append(create_file_access_audit_hook(audit_log))

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
            handoff_dir = ctx.run_base / "handoff"
            handoff_path = handoff_dir / f"{ctx.step_id}.draft.json"
            handoff_dir.mkdir(parents=True, exist_ok=True)

            finalize_result = await session.finalize(handoff_path=handoff_path)

            if finalize_result.success and finalize_result.envelope:
                # Write handoff to disk
                with handoff_path.open("w", encoding="utf-8") as f:
                    json.dump(finalize_result.envelope, f, indent=2)

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
                            "status": finalize_result.envelope.get("status", "unknown"),
                            "handoff_path": str(handoff_path),
                        },
                    )
                )

            # Phase 3: Route (determine next step)
            routing_signal: Optional[RoutingSignal] = None
            if not is_step_terminal:
                route_result = await session.route(routing_config=routing_config)

                if route_result.success and route_result.signal:
                    # Convert dict to RoutingSignal
                    signal_data = route_result.signal
                    decision_str = signal_data.get("decision", "advance").lower()
                    decision_map = {
                        "advance": RoutingDecision.ADVANCE,
                        "loop": RoutingDecision.LOOP,
                        "terminate": RoutingDecision.TERMINATE,
                        "branch": RoutingDecision.BRANCH,
                    }
                    routing_signal = RoutingSignal(
                        decision=decision_map.get(decision_str, RoutingDecision.ADVANCE),
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
                "route": route_result.success if not is_step_terminal else None,
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
    # INTERNAL STUB IMPLEMENTATIONS
    # =========================================================================

    def _run_worker_stub(
        self, ctx: StepContext
    ) -> Tuple[StepResult, List[RunEvent], str]:
        """Stub implementation of run_worker."""
        start_time = datetime.now(timezone.utc)
        agent_key = ctx.step_agents[0] if ctx.step_agents else "unknown"

        ensure_llm_dir(ctx.run_base)
        ensure_receipts_dir(ctx.run_base)

        t_path = make_transcript_path(ctx.run_base, ctx.step_id, agent_key, "claude")
        transcript_messages = [
            {
                "timestamp": start_time.isoformat() + "Z",
                "role": "system",
                "content": f"[STUB WORKER] Executing step {ctx.step_id} with agent {agent_key}",
            },
            {
                "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
                "role": "assistant",
                "content": f"[STUB] Completed step {ctx.step_id}. Work phase done.",
            },
        ]
        with t_path.open("w", encoding="utf-8") as f:
            for msg in transcript_messages:
                f.write(json.dumps(msg) + "\n")

        end_time = datetime.now(timezone.utc)
        duration_ms = int((end_time - start_time).total_seconds() * 1000)

        work_summary = f"[STUB:{self.engine_id}] Step {ctx.step_id} work phase completed successfully"

        result = StepResult(
            step_id=ctx.step_id,
            status="succeeded",
            output=work_summary,
            duration_ms=duration_ms,
            artifacts={
                "transcript_path": str(t_path),
                "token_counts": {"prompt": 0, "completion": 0, "total": 0},
                "model": "claude-stub",
            },
        )

        events: List[RunEvent] = [
            RunEvent(
                run_id=ctx.run_id,
                ts=start_time,
                kind="log",
                flow_key=ctx.flow_key,
                step_id=ctx.step_id,
                agent_key=agent_key,
                payload={
                    "message": f"[STUB WORKER] Step {ctx.step_id} executed",
                    "mode": "stub",
                },
            )
        ]

        return result, events, work_summary

    def _finalize_step_stub(
        self,
        ctx: StepContext,
        step_result: StepResult,
        work_summary: str,
    ) -> FinalizationResult:
        """Stub implementation of finalize_step."""
        events: List[RunEvent] = []
        agent_key = ctx.step_agents[0] if ctx.step_agents else None

        handoff_dir = ctx.run_base / "handoff"
        handoff_dir.mkdir(parents=True, exist_ok=True)

        file_changes = scan_file_changes_sync(ctx.repo_root)
        file_changes_dict = file_changes_to_dict(file_changes)

        if file_changes.has_changes:
            logger.debug("Diff scan for step %s: %s", ctx.step_id, file_changes.summary)
            events.append(
                RunEvent(
                    run_id=ctx.run_id,
                    ts=datetime.now(timezone.utc),
                    kind="file_changes",
                    flow_key=ctx.flow_key,
                    step_id=ctx.step_id,
                    agent_key=agent_key,
                    payload=file_changes_dict,
                )
            )

        handoff_data: Dict[str, Any] = {
            "step_id": ctx.step_id,
            "flow_key": ctx.flow_key,
            "run_id": ctx.run_id,
            "status": "VERIFIED" if step_result.status == "succeeded" else "UNVERIFIED",
            "summary": work_summary[:500]
            if work_summary
            else f"[STUB] Step {ctx.step_id} completed",
            "can_further_iteration_help": "no",
            "artifacts": [],
            "file_changes": file_changes_dict,
            "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
        }

        handoff_path = handoff_dir / f"{ctx.step_id}.draft.json"
        with handoff_path.open("w", encoding="utf-8") as f:
            json.dump(handoff_data, f, indent=2)

        envelope = HandoffEnvelope(
            step_id=ctx.step_id,
            flow_key=ctx.flow_key,
            run_id=ctx.run_id,
            routing_signal=RoutingSignal(
                decision=RoutingDecision.ADVANCE,
                reason="stub_finalization",
                confidence=1.0,
                needs_human=False,
            ),
            summary=handoff_data["summary"],
            file_changes=file_changes_dict,
            status=handoff_data["status"],
            duration_ms=step_result.duration_ms,
            timestamp=datetime.now(timezone.utc),
        )

        envelope_path = make_handoff_envelope_path(ctx.run_base, ctx.step_id)
        envelope_path.parent.mkdir(parents=True, exist_ok=True)
        with envelope_path.open("w", encoding="utf-8") as f:
            json.dump(handoff_envelope_to_dict(envelope), f, indent=2)

        # Write receipt for lifecycle mode (run_worker + finalize_step)
        ensure_receipts_dir(ctx.run_base)
        r_path = make_receipt_path(ctx.run_base, ctx.step_id, agent_key or "unknown")
        receipt = {
            "engine": self.engine_id,
            "mode": "stub",
            "provider": self._provider or "none",
            "model": "claude-stub",
            "step_id": ctx.step_id,
            "flow_key": ctx.flow_key,
            "run_id": ctx.run_id,
            "agent_key": agent_key or "unknown",
            "started_at": datetime.now(timezone.utc).isoformat() + "Z",
            "completed_at": datetime.now(timezone.utc).isoformat() + "Z",
            "duration_ms": step_result.duration_ms,
            "status": step_result.status,
            "tokens": {"prompt": 0, "completion": 0, "total": 0},
            "lifecycle_mode": True,
        }
        with r_path.open("w", encoding="utf-8") as f:
            json.dump(receipt, f, indent=2)

        return FinalizationResult(
            handoff_data=handoff_data,
            envelope=envelope,
            work_summary=work_summary,
            events=events,
        )

    def _finalize_from_existing_handoff(
        self,
        ctx: StepContext,
        step_result: StepResult,
        work_summary: str,
        handoff_path: Path,
    ) -> FinalizationResult:
        """Create FinalizationResult from handoff written during work phase."""
        events: List[RunEvent] = []
        agent_key = ctx.step_agents[0] if ctx.step_agents else "unknown"

        handoff_data: Optional[Dict[str, Any]] = None
        try:
            handoff_data = json.loads(handoff_path.read_text(encoding="utf-8"))
            logger.debug(
                "Read inline handoff from %s: status=%s",
                handoff_path,
                handoff_data.get("status"),
            )
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to parse inline handoff file %s: %s", handoff_path, e)

        file_changes = scan_file_changes_sync(ctx.repo_root)
        file_changes_dict = file_changes_to_dict(file_changes)

        if file_changes.has_changes:
            logger.debug("Diff scan for step %s: %s", ctx.step_id, file_changes.summary)
            events.append(
                RunEvent(
                    run_id=ctx.run_id,
                    ts=datetime.now(timezone.utc),
                    kind="file_changes",
                    flow_key=ctx.flow_key,
                    step_id=ctx.step_id,
                    agent_key=agent_key,
                    payload=file_changes_dict,
                )
            )

        events.append(
            RunEvent(
                run_id=ctx.run_id,
                ts=datetime.now(timezone.utc),
                kind="log",
                flow_key=ctx.flow_key,
                step_id=ctx.step_id,
                agent_key=agent_key,
                payload={
                    "message": f"Inline finalization: handoff read from {handoff_path}",
                    "mode": "inline",
                },
            )
        )

        envelope: Optional[HandoffEnvelope] = None
        if handoff_data:
            status_str = handoff_data.get("status", "UNVERIFIED")
            envelope = HandoffEnvelope(
                step_id=ctx.step_id,
                flow_key=ctx.flow_key,
                run_id=ctx.run_id,
                routing_signal=None,
                summary=handoff_data.get("summary", work_summary[:500]),
                status=status_str.lower() if isinstance(status_str, str) else "unverified",
                error=step_result.error,
                duration_ms=step_result.duration_ms,
                timestamp=datetime.now(timezone.utc),
                artifacts=handoff_data.get("artifacts"),
                file_changes=file_changes_dict,
            )
        else:
            envelope = HandoffEnvelope(
                step_id=ctx.step_id,
                flow_key=ctx.flow_key,
                run_id=ctx.run_id,
                routing_signal=None,
                summary=work_summary[:500] if work_summary else f"Step {ctx.step_id} completed",
                status="verified" if step_result.status == "succeeded" else "unverified",
                error=step_result.error,
                duration_ms=step_result.duration_ms,
                timestamp=datetime.now(timezone.utc),
                file_changes=file_changes_dict,
            )

        envelope_path = make_handoff_envelope_path(ctx.run_base, ctx.step_id)
        ensure_handoff_dir(ctx.run_base)
        with envelope_path.open("w", encoding="utf-8") as f:
            json.dump(handoff_envelope_to_dict(envelope), f, indent=2)

        events.append(
            RunEvent(
                run_id=ctx.run_id,
                ts=datetime.now(timezone.utc),
                kind="log",
                flow_key=ctx.flow_key,
                step_id=ctx.step_id,
                agent_key=agent_key,
                payload={
                    "message": f"Handoff envelope written to {envelope_path}",
                    "status": envelope.status,
                },
            )
        )

        return FinalizationResult(
            handoff_data=handoff_data,
            envelope=envelope,
            work_summary=work_summary,
            events=events,
        )

    def _run_step_stub(self, ctx: StepContext) -> Tuple[StepResult, Iterable[RunEvent]]:
        """Execute a step in stub mode."""
        start_time = datetime.now(timezone.utc)
        agent_key = ctx.step_agents[0] if ctx.step_agents else "unknown"

        ensure_llm_dir(ctx.run_base)
        ensure_receipts_dir(ctx.run_base)

        t_path = make_transcript_path(ctx.run_base, ctx.step_id, agent_key, "claude")
        r_path = make_receipt_path(ctx.run_base, ctx.step_id, agent_key)

        _, truncation_info, _ = self._build_prompt(ctx)

        transcript_messages = [
            {
                "timestamp": start_time.isoformat() + "Z",
                "role": "system",
                "content": f"Executing step {ctx.step_id} with agent {agent_key}",
            },
            {
                "timestamp": start_time.isoformat() + "Z",
                "role": "user",
                "content": f"Step role: {ctx.step_role}",
            },
            {
                "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
                "role": "assistant",
                "content": f"[STUB] Completed step {ctx.step_id}. "
                f"In production, this would contain the actual Claude response.",
            },
        ]
        with t_path.open("w", encoding="utf-8") as f:
            for msg in transcript_messages:
                f.write(json.dumps(msg) + "\n")

        end_time = datetime.now(timezone.utc)
        duration_ms = int((end_time - start_time).total_seconds() * 1000)

        receipt = {
            "engine": self.engine_id,
            "mode": "stub",
            "provider": self._provider or "none",
            "model": "claude-stub",
            "step_id": ctx.step_id,
            "flow_key": ctx.flow_key,
            "run_id": ctx.run_id,
            "agent_key": agent_key,
            "started_at": start_time.isoformat() + "Z",
            "completed_at": end_time.isoformat() + "Z",
            "duration_ms": duration_ms,
            "status": "succeeded",
            "tokens": {"prompt": 0, "completion": 0, "total": 0},
            "transcript_path": str(t_path.relative_to(ctx.run_base)),
        }
        if truncation_info:
            receipt["context_truncation"] = truncation_info.to_dict()

        with r_path.open("w", encoding="utf-8") as f:
            json.dump(receipt, f, indent=2)

        events: List[RunEvent] = [
            RunEvent(
                run_id=ctx.run_id,
                ts=start_time,
                kind="log",
                flow_key=ctx.flow_key,
                step_id=ctx.step_id,
                agent_key=agent_key,
                payload={
                    "message": f"ClaudeStepEngine stub executed step {ctx.step_id}",
                    "engine_id": self.engine_id,
                    "mode": "stub",
                    "provider": self._provider or "none",
                    "transcript_path": str(t_path.relative_to(ctx.run_base)),
                    "receipt_path": str(r_path.relative_to(ctx.run_base)),
                },
            )
        ]

        result = StepResult(
            step_id=ctx.step_id,
            status="succeeded",
            output=f"[STUB:{self.engine_id}] Step {ctx.step_id} completed successfully",
            duration_ms=duration_ms,
            artifacts={
                "transcript_path": str(t_path),
                "receipt_path": str(r_path),
            },
        )

        return result, events

    def _make_failed_result(
        self, ctx: StepContext, error: str
    ) -> Tuple[StepResult, Iterable[RunEvent]]:
        """Create a failed result for error cases."""
        return (
            StepResult(
                step_id=ctx.step_id,
                status="failed",
                output="",
                error=error,
                duration_ms=0,
            ),
            [],
        )

    # =========================================================================
    # INTERNAL ASYNC IMPLEMENTATIONS
    # =========================================================================

    async def _run_worker_async(
        self, ctx: StepContext
    ) -> Tuple[StepResult, List[RunEvent], str]:
        """Async implementation of run_worker."""
        sdk = get_sdk_module()
        query = sdk.query

        start_time = datetime.now(timezone.utc)
        agent_key = ctx.step_agents[0] if ctx.step_agents else "unknown"
        events: List[RunEvent] = []

        ensure_llm_dir(ctx.run_base)
        ensure_receipts_dir(ctx.run_base)

        # Try spec-based prompt compilation first, fall back to legacy
        spec_result = try_compile_from_spec(ctx, self.repo_root)

        if spec_result:
            # Use spec-based prompts
            prompt, agent_persona, plan = spec_result
            logger.debug(
                "Using spec-based prompt for step %s (hash=%s, station=%s v%d)",
                ctx.step_id,
                plan.prompt_hash,
                plan.station_id,
                plan.station_version,
            )
            truncation_info = None  # Spec compilation handles context management
        else:
            # Fall back to legacy prompt builder
            logger.debug(
                "Spec not available for step %s, using legacy prompt builder",
                ctx.step_id,
            )
            prompt, truncation_info, agent_persona = self._build_prompt(ctx)

        cwd = str(ctx.repo_root) if ctx.repo_root else str(Path.cwd())

        options = create_high_trust_options(
            cwd=cwd,
            permission_mode="bypassPermissions",
            system_prompt_append=agent_persona,
        )

        # DEPRECATED: Direct stats recording is a no-op in projection-only mode.
        # The correct flow is: events.jsonl -> tailer -> ingest_events() -> DB.
        # These calls are retained for backwards compatibility with legacy mode.
        if self._stats_db:
            try:
                self._stats_db.record_step_start(
                    run_id=ctx.run_id,
                    flow_key=ctx.flow_key,
                    step_id=ctx.step_id,
                    step_index=ctx.step_index,
                    agent_key=agent_key,
                )
            except Exception as db_err:
                logger.debug("Failed to record step start: %s", db_err)

        raw_events: List[Dict[str, Any]] = []
        full_assistant_text: List[str] = []
        token_counts: Dict[str, int] = {"prompt": 0, "completion": 0, "total": 0}
        model_name = "claude-sonnet-4-20250514"
        pending_tool_inputs: Dict[str, Tuple[str, Dict[str, Any]]] = {}

        try:
            async for event in query(
                prompt=prompt,
                options=options,
            ):
                now = datetime.now(timezone.utc)
                event_dict: Dict[str, Any] = {"timestamp": now.isoformat() + "Z"}
                event_type = getattr(event, "type", None) or type(event).__name__

                if event_type == "AssistantMessageEvent" or hasattr(event, "message"):
                    message = getattr(event, "message", event)
                    role = getattr(message, "role", "assistant")
                    content = getattr(message, "content", "")

                    if isinstance(content, list):
                        text_parts = []
                        for block in content:
                            if hasattr(block, "text"):
                                text_parts.append(block.text)
                            elif hasattr(block, "content"):
                                text_parts.append(str(block.content))
                        content = "\n".join(text_parts)

                    event_dict["role"] = role
                    event_dict["content"] = content
                    event_dict["type"] = "message"

                    if role == "assistant" and content:
                        full_assistant_text.append(content)

                    events.append(
                        RunEvent(
                            run_id=ctx.run_id,
                            ts=now,
                            kind="assistant_message" if role == "assistant" else "user_message",
                            flow_key=ctx.flow_key,
                            step_id=ctx.step_id,
                            agent_key=agent_key,
                            payload={"role": role, "content": content[:500]},
                        )
                    )

                elif event_type == "ToolUseEvent" or hasattr(event, "tool_name"):
                    tool_name = getattr(event, "tool_name", getattr(event, "name", "unknown"))
                    tool_input = getattr(event, "input", getattr(event, "args", {}))
                    tool_use_id = getattr(event, "id", getattr(event, "tool_use_id", None))

                    event_dict["type"] = "tool_use"
                    event_dict["tool"] = tool_name
                    event_dict["input"] = tool_input

                    if tool_use_id and isinstance(tool_input, dict):
                        pending_tool_inputs[tool_use_id] = (tool_name, tool_input)

                    events.append(
                        RunEvent(
                            run_id=ctx.run_id,
                            ts=now,
                            kind="tool_start",
                            flow_key=ctx.flow_key,
                            step_id=ctx.step_id,
                            agent_key=agent_key,
                            payload={"tool": tool_name, "input": str(tool_input)[:200]},
                        )
                    )

                elif event_type == "ToolResultEvent" or hasattr(event, "tool_result"):
                    result = getattr(event, "tool_result", getattr(event, "result", ""))
                    success = getattr(event, "success", True)
                    tool_name = getattr(event, "tool_name", "unknown")
                    tool_use_id = getattr(event, "tool_use_id", getattr(event, "id", None))

                    tool_input: Dict[str, Any] = {}
                    if tool_use_id and tool_use_id in pending_tool_inputs:
                        stored_name, tool_input = pending_tool_inputs.pop(tool_use_id)
                        if tool_name == "unknown":
                            tool_name = stored_name

                    event_dict["type"] = "tool_result"
                    event_dict["tool"] = tool_name
                    event_dict["success"] = success
                    event_dict["output"] = str(result)[:500]

                    events.append(
                        RunEvent(
                            run_id=ctx.run_id,
                            ts=now,
                            kind="tool_end",
                            flow_key=ctx.flow_key,
                            step_id=ctx.step_id,
                            agent_key=agent_key,
                            payload={
                                "tool": tool_name,
                                "success": success,
                                "output": str(result)[:200],
                            },
                        )
                    )

                    # DEPRECATED: Direct stats recording (no-op in projection-only mode).
                    # Retained for backwards compatibility with legacy mode.
                    if self._stats_db:
                        try:
                            target_path = None
                            if tool_name in ("Edit", "Write", "Read"):
                                target_path = str(tool_input.get("file_path", ""))[:500]
                            self._stats_db.record_tool_call(
                                run_id=ctx.run_id,
                                step_id=ctx.step_id,
                                tool_name=tool_name,
                                phase="work",
                                success=success,
                                target_path=target_path,
                            )
                        except Exception as db_err:
                            logger.debug("Failed to record tool call: %s", db_err)

                        if tool_name in ("Write", "Edit") and success:
                            try:
                                target_path = str(tool_input.get("file_path", ""))
                                if target_path:
                                    change_type = "created" if tool_name == "Write" else "modified"
                                    self._stats_db.record_file_change(
                                        run_id=ctx.run_id,
                                        step_id=ctx.step_id,
                                        file_path=target_path,
                                        change_type=change_type,
                                    )
                            except Exception as db_err:
                                logger.debug("Failed to record file change: %s", db_err)

                elif event_type == "ResultEvent" or hasattr(event, "result"):
                    result = getattr(event, "result", event)
                    event_dict["type"] = "result"

                    usage = getattr(result, "usage", None)
                    if usage:
                        token_counts["prompt"] = getattr(usage, "input_tokens", 0)
                        token_counts["completion"] = getattr(usage, "output_tokens", 0)
                        token_counts["total"] = token_counts["prompt"] + token_counts["completion"]
                        event_dict["usage"] = token_counts

                    result_model = getattr(result, "model", None)
                    if result_model:
                        model_name = result_model

                else:
                    event_dict["type"] = event_type
                    if hasattr(event, "__dict__"):
                        for k, v in event.__dict__.items():
                            if not k.startswith("_"):
                                try:
                                    json.dumps(v)
                                    event_dict[k] = v
                                except (TypeError, ValueError):
                                    event_dict[k] = str(v)

                raw_events.append(event_dict)

            status = "succeeded"
            error = None

        except Exception as e:
            logger.warning("SDK worker query failed for step %s: %s", ctx.step_id, e)
            status = "failed"
            error = str(e)
            raw_events.append(
                {
                    "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
                    "type": "error",
                    "error": str(e),
                }
            )

        end_time = datetime.now(timezone.utc)
        duration_ms = int((end_time - start_time).total_seconds() * 1000)

        work_summary = "".join(full_assistant_text)

        if len(work_summary) > 2000:
            output_text = work_summary[:2000] + "... (truncated)"
        elif work_summary:
            output_text = work_summary
        else:
            output_text = f"Step {ctx.step_id} work phase completed. Events: {len(raw_events)}"

        t_path = make_transcript_path(ctx.run_base, ctx.step_id, agent_key, "claude")
        with t_path.open("w", encoding="utf-8") as f:
            for event in raw_events:
                f.write(json.dumps(event) + "\n")

        result = StepResult(
            step_id=ctx.step_id,
            status=status,
            output=output_text,
            error=error,
            duration_ms=duration_ms,
            artifacts={
                "transcript_path": str(t_path),
                "token_counts": token_counts,
                "model": model_name,
            },
        )

        return result, events, work_summary

    async def _finalize_step_async(
        self,
        ctx: StepContext,
        step_result: StepResult,
        work_summary: str,
    ) -> FinalizationResult:
        """Async implementation of finalize_step."""
        sdk = get_sdk_module()
        query = sdk.query

        events: List[RunEvent] = []
        raw_events: List[Dict[str, Any]] = []
        agent_key = ctx.step_agents[0] if ctx.step_agents else "unknown"

        handoff_dir = ctx.run_base / "handoff"
        handoff_path = handoff_dir / f"{ctx.step_id}.draft.json"
        handoff_dir.mkdir(parents=True, exist_ok=True)

        cwd = str(ctx.repo_root) if ctx.repo_root else str(Path.cwd())

        options = create_high_trust_options(
            cwd=cwd,
            permission_mode="bypassPermissions",
        )

        finalization_prompt = self._build_finalization_prompt(
            ctx=ctx,
            handoff_path=handoff_path,
            work_summary=work_summary,
            step_result=step_result,
        )

        try:
            logger.debug("Starting JIT finalization for step %s", ctx.step_id)

            async for event in query(
                prompt=finalization_prompt,
                options=options,
            ):
                now = datetime.now(timezone.utc)
                event_dict = {"timestamp": now.isoformat() + "Z", "phase": "finalization"}

                event_type = getattr(event, "type", None) or type(event).__name__

                if event_type == "AssistantMessageEvent" or hasattr(event, "message"):
                    message = getattr(event, "message", event)
                    content = getattr(message, "content", "")
                    if isinstance(content, list):
                        text_parts = [
                            getattr(b, "text", str(getattr(b, "content", "")))
                            for b in content
                        ]
                        content = "\n".join(text_parts)
                    event_dict["type"] = "message"
                    event_dict["content"] = content[:500]

                elif event_type == "ToolUseEvent" or hasattr(event, "tool_name"):
                    tool_name = getattr(event, "tool_name", getattr(event, "name", "unknown"))
                    event_dict["type"] = "tool_use"
                    event_dict["tool"] = tool_name

                elif event_type == "ToolResultEvent" or hasattr(event, "tool_result"):
                    event_dict["type"] = "tool_result"
                    event_dict["success"] = getattr(event, "success", True)

                else:
                    event_dict["type"] = event_type

                raw_events.append(event_dict)

            logger.debug("JIT finalization complete for step %s", ctx.step_id)

        except Exception as fin_error:
            logger.warning("JIT finalization failed for step %s: %s", ctx.step_id, fin_error)
            raw_events.append(
                {
                    "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
                    "phase": "finalization",
                    "type": "error",
                    "error": str(fin_error),
                }
            )

        # Read handoff draft
        handoff_data: Optional[Dict[str, Any]] = None
        if handoff_path.exists():
            try:
                handoff_data = json.loads(handoff_path.read_text(encoding="utf-8"))
                logger.debug(
                    "Handoff extracted from %s: status=%s",
                    handoff_path,
                    handoff_data.get("status"),
                )
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("Failed to parse handoff file %s: %s", handoff_path, e)
        else:
            logger.warning("Handoff file not created by agent: %s", handoff_path)

        # Scan for file changes
        file_changes = await scan_file_changes(ctx.repo_root)
        file_changes_dict = file_changes_to_dict(file_changes)

        if file_changes.has_changes:
            logger.debug("Diff scan for step %s: %s", ctx.step_id, file_changes.summary)
            events.append(
                RunEvent(
                    run_id=ctx.run_id,
                    ts=datetime.now(timezone.utc),
                    kind="file_changes",
                    flow_key=ctx.flow_key,
                    step_id=ctx.step_id,
                    agent_key=agent_key,
                    payload=file_changes_dict,
                )
            )

        # Create envelope
        envelope: Optional[HandoffEnvelope] = None
        try:
            envelope = await write_handoff_envelope(
                ctx=ctx,
                step_result=step_result,
                routing_signal=None,
                work_summary=work_summary,
                file_changes=file_changes_dict,
            )
            if envelope:
                logger.debug(
                    "Handoff envelope created for step %s: status=%s",
                    ctx.step_id,
                    envelope.status,
                )
                raw_events.append(
                    {
                        "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
                        "phase": "envelope",
                        "type": "handoff_envelope_written",
                        "envelope_path": str(
                            make_handoff_envelope_path(ctx.run_base, ctx.step_id)
                        ),
                        "status": envelope.status,
                    }
                )
        except Exception as envelope_error:
            logger.warning(
                "Failed to write handoff envelope for step %s: %s",
                ctx.step_id,
                envelope_error,
            )
            raw_events.append(
                {
                    "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
                    "phase": "envelope",
                    "type": "error",
                    "error": str(envelope_error),
                }
            )

        return FinalizationResult(
            handoff_data=handoff_data,
            envelope=envelope,
            work_summary=work_summary,
            events=events,
        )

    async def _route_step_async(
        self,
        ctx: StepContext,
        handoff_data: Dict[str, Any],
    ) -> Optional[RoutingSignal]:
        """Async implementation of route_step."""
        cwd = str(ctx.repo_root) if ctx.repo_root else str(Path.cwd())

        try:
            routing_signal = await run_router_session(
                handoff_data=handoff_data,
                ctx=ctx,
                cwd=cwd,
            )
            if routing_signal:
                logger.debug(
                    "Router decision for step %s: %s -> %s (confidence=%.2f)",
                    ctx.step_id,
                    routing_signal.decision.value,
                    routing_signal.next_step_id,
                    routing_signal.confidence,
                )
            return routing_signal

        except Exception as route_error:
            logger.warning("Router session failed for step %s: %s", ctx.step_id, route_error)
            return None

    def _build_finalization_prompt(
        self,
        ctx: StepContext,
        handoff_path: Path,
        work_summary: str,
        step_result: StepResult,
    ) -> str:
        """Build the finalization prompt using resolvers module."""
        try:
            template = load_envelope_writer_prompt(ctx.repo_root)
            if template:
                prompt = build_finalization_prompt(
                    step_id=ctx.step_id,
                    step_output=work_summary,
                    artifacts_changed=[],
                    flow_key=ctx.flow_key,
                    run_id=ctx.run_id,
                    status=step_result.status,
                    error=step_result.error,
                    duration_ms=step_result.duration_ms,
                    template=template,
                )
                handoff_instruction = f"""
---
After analyzing the above, use the `Write` tool to create a file at:
{handoff_path}

The file must be valid JSON matching the HandoffEnvelope schema.
---
"""
                return prompt + handoff_instruction
        except Exception as e:
            logger.debug("Failed to load resolver template, using fallback: %s", e)

        finalization_prompt = JIT_FINALIZATION_PROMPT.format(
            handoff_path=str(handoff_path),
            step_id=ctx.step_id,
            flow_key=ctx.flow_key,
            run_id=ctx.run_id,
        )

        truncated_summary = work_summary[:4000] if len(work_summary) > 4000 else work_summary
        return f"""
## Work Session Summary
{truncated_summary}

{finalization_prompt}
"""

    # =========================================================================
    # CLI EXECUTION
    # =========================================================================

    def _run_step_cli(self, ctx: StepContext) -> Tuple[StepResult, Iterable[RunEvent]]:
        """Execute a step using the Claude CLI."""
        events: List[RunEvent] = []
        start_time = datetime.now(timezone.utc)
        agent_key = ctx.step_agents[0] if ctx.step_agents else "unknown"

        ensure_llm_dir(ctx.run_base)
        ensure_receipts_dir(ctx.run_base)

        t_path = make_transcript_path(ctx.run_base, ctx.step_id, agent_key, "claude")
        r_path = make_receipt_path(ctx.run_base, ctx.step_id, agent_key)

        prompt, truncation_info, _ = self._build_prompt(ctx)

        args = [
            self._cli_cmd,
            "-p",
            "--output-format",
            "stream-json",
        ]

        cmd = " ".join(shlex.quote(a) for a in args)
        cwd = str(ctx.repo_root) if ctx.repo_root else str(Path.cwd())

        process = subprocess.Popen(
            cmd,
            cwd=cwd,
            shell=True,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        raw_events: List[Dict[str, Any]] = []
        full_assistant_text: List[str] = []
        token_counts: Dict[str, int] = {"prompt": 0, "completion": 0, "total": 0}
        model_name = "claude-sonnet-4-20250514"

        stdout_data, stderr_data = process.communicate(input=prompt, timeout=300)

        if stdout_data:
            for line in stdout_data.strip().split("\n"):
                line = line.strip()
                if not line:
                    continue

                try:
                    event_data = json.loads(line)
                    raw_events.append(event_data)

                    event_type = event_data.get("type", "unknown")

                    if event_type == "message":
                        role = event_data.get("role", "assistant")
                        content = event_data.get("content", "")
                        if role == "assistant" and content:
                            full_assistant_text.append(content)

                        events.append(
                            RunEvent(
                                run_id=ctx.run_id,
                                ts=datetime.now(timezone.utc),
                                kind="assistant_message" if role == "assistant" else "user_message",
                                flow_key=ctx.flow_key,
                                step_id=ctx.step_id,
                                agent_key=agent_key,
                                payload={"role": role, "content": content[:500]},
                            )
                        )

                    elif event_type == "tool_use":
                        tool_name = event_data.get("tool") or event_data.get("name", "unknown")
                        tool_input = event_data.get("input") or event_data.get("args", {})
                        events.append(
                            RunEvent(
                                run_id=ctx.run_id,
                                ts=datetime.now(timezone.utc),
                                kind="tool_start",
                                flow_key=ctx.flow_key,
                                step_id=ctx.step_id,
                                agent_key=agent_key,
                                payload={"tool": tool_name, "input": str(tool_input)[:200]},
                            )
                        )

                    elif event_type == "tool_result":
                        tool_name = event_data.get("tool") or event_data.get("name", "unknown")
                        result = event_data.get("output") or event_data.get("result", "")
                        success = event_data.get("success", True)
                        events.append(
                            RunEvent(
                                run_id=ctx.run_id,
                                ts=datetime.now(timezone.utc),
                                kind="tool_end",
                                flow_key=ctx.flow_key,
                                step_id=ctx.step_id,
                                agent_key=agent_key,
                                payload={
                                    "tool": tool_name,
                                    "success": success,
                                    "output": str(result)[:200],
                                },
                            )
                        )

                    elif event_type == "result":
                        usage = event_data.get("usage", {})
                        if usage:
                            token_counts["prompt"] = usage.get("input_tokens", 0)
                            token_counts["completion"] = usage.get("output_tokens", 0)
                            token_counts["total"] = (
                                token_counts["prompt"] + token_counts["completion"]
                            )
                        if event_data.get("model"):
                            model_name = event_data["model"]

                except json.JSONDecodeError:
                    raw_events.append({"type": "text", "message": line})
                    events.append(
                        RunEvent(
                            run_id=ctx.run_id,
                            ts=datetime.now(timezone.utc),
                            kind="log",
                            flow_key=ctx.flow_key,
                            step_id=ctx.step_id,
                            payload={"message": line},
                        )
                    )

        end_time = datetime.now(timezone.utc)
        duration_ms = int((end_time - start_time).total_seconds() * 1000)

        if process.returncode != 0:
            status = "failed"
            error = stderr_data[:500] if stderr_data else f"Exit code {process.returncode}"
        else:
            status = "succeeded"
            error = None

        with t_path.open("w", encoding="utf-8") as f:
            for event in raw_events:
                if "timestamp" not in event:
                    event["timestamp"] = datetime.now(timezone.utc).isoformat() + "Z"
                f.write(json.dumps(event) + "\n")

        receipt = {
            "engine": self.engine_id,
            "mode": "cli",
            "provider": self._provider,
            "model": model_name,
            "step_id": ctx.step_id,
            "flow_key": ctx.flow_key,
            "run_id": ctx.run_id,
            "agent_key": agent_key,
            "started_at": start_time.isoformat() + "Z",
            "completed_at": end_time.isoformat() + "Z",
            "duration_ms": duration_ms,
            "status": status,
            "tokens": token_counts,
            "transcript_path": str(t_path.relative_to(ctx.run_base)),
        }
        if error:
            receipt["error"] = error
        if truncation_info:
            receipt["context_truncation"] = truncation_info.to_dict()

        with r_path.open("w", encoding="utf-8") as f:
            json.dump(receipt, f, indent=2)

        combined_text = "".join(full_assistant_text)
        if len(combined_text) > 2000:
            output_text = combined_text[:2000] + "... (truncated)"
        elif combined_text:
            output_text = combined_text
        else:
            output_text = f"Step {ctx.step_id} completed via CLI. Events: {len(raw_events)}"

        result = StepResult(
            step_id=ctx.step_id,
            status=status,
            output=output_text,
            error=error,
            duration_ms=duration_ms,
            artifacts={
                "transcript_path": str(t_path),
                "receipt_path": str(r_path),
            },
        )

        return result, events

    def _run_step_sdk(self, ctx: StepContext) -> Tuple[StepResult, Iterable[RunEvent]]:
        """Execute a step using the Claude Agent SDK."""
        # Use run_async_safely instead of the problematic get_event_loop pattern
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
