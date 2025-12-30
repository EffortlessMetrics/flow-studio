"""
session_runner.py - WP6 per-step session execution pattern.

This module implements the SDK alignment pattern where each step gets ONE
session that handles all phases in sequence with hot context preserved:
1. Work phase: Agent performs its task
2. Finalize phase: Extract structured handoff envelope
3. Route phase: Determine next step (if not terminal)

Benefits over the traditional run_step() approach:
- Preserves hot context between phases (no re-prompting)
- Uses structured output_format for reliable JSON extraction
- Implements high-trust tool policy with foot-gun blocking
- Enables mid-step interrupts for observability
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Iterable, List, Optional, Tuple

from swarm.runtime.claude_sdk import (
    ClaudeSDKClient,
    TelemetryData,
    create_dangerous_command_hook,
    create_telemetry_hook,
    create_tool_policy_hook,
)
from swarm.runtime.handoff_io import (
    update_envelope_routing,
    write_handoff_envelope,
)
from swarm.runtime.path_helpers import (
    ensure_llm_dir,
    ensure_receipts_dir,
)
from swarm.runtime.path_helpers import (
    handoff_envelope_path as make_handoff_envelope_path,
)
from swarm.runtime.path_helpers import (
    receipt_path as make_receipt_path,
)
from swarm.runtime.path_helpers import (
    transcript_path as make_transcript_path,
)
from swarm.runtime.routing_utils import parse_routing_decision
from swarm.runtime.types import (
    RoutingSignal,
    RunEvent,
)

from ..async_utils import run_async_safely
from ..models import StepContext, StepResult
from .prompt_builder import load_agent_persona
from .stubs import run_step_stub

if TYPE_CHECKING:
    from .engine import ClaudeStepEngine

logger = logging.getLogger(__name__)


async def execute_step_session(
    engine: "ClaudeStepEngine",
    ctx: StepContext,
    is_terminal: bool = False,
) -> Tuple[StepResult, Iterable[RunEvent], Optional[RoutingSignal]]:
    """Execute a step using the new per-step session pattern (WP6).

    This method implements the SDK alignment pattern where each step gets ONE
    session that handles all phases in sequence with hot context preserved:
    1. Work phase: Agent performs its task
    2. Finalize phase: Extract structured handoff envelope
    3. Route phase: Determine next step (if not terminal)

    Args:
        engine: The ClaudeStepEngine instance.
        ctx: Step execution context.
        is_terminal: Whether this is the last step in the flow.

    Returns:
        Tuple of (StepResult, events, routing_signal).
    """
    # Hydrate context before execution
    ctx = engine._hydrate_context(ctx)

    if engine._mode == "stub" or not engine._check_sdk_available():
        logger.debug(
            "execute_step_session falling back to stub for step %s (mode=%s, sdk=%s)",
            ctx.step_id,
            engine._mode,
            engine._check_sdk_available(),
        )
        result, events = run_step_stub(
            ctx, engine.engine_id, engine._provider, engine._build_prompt
        )
        return result, events, None

    return await _execute_step_session_sdk(engine, ctx, is_terminal)


async def _execute_step_session_sdk(
    engine: "ClaudeStepEngine",
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
    prompt, truncation_info, _ = engine._build_prompt(ctx)

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
        draft_handoff_path = ctx.run_base / "handoff" / f"{ctx.step_id}.draft.json"
        committed_handoff_path = make_handoff_envelope_path(ctx.run_base, ctx.step_id)

        finalize_result = await session.finalize(handoff_path=draft_handoff_path)

        if finalize_result.success and finalize_result.envelope:
            # Enrich envelope with file_changes if available from work phase
            envelope_data = dict(finalize_result.envelope)
            if hasattr(work_result, "file_changes") and work_result.file_changes:
                envelope_data["file_changes"] = work_result.file_changes

            # Write envelope using unified IO (handles draft + committed)
            write_handoff_envelope(
                run_base=ctx.run_base,
                step_id=ctx.step_id,
                envelope_data=envelope_data,
                write_draft=True,
                validate=True,
            )

            logger.debug(
                "Wrote handoff envelope for step %s via handoff_io",
                ctx.step_id,
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

                # Persist routing_signal into committed envelope using unified IO
                if finalize_result and finalize_result.success:
                    routing_dict = {
                        "decision": routing_signal.decision.value,
                        "next_step_id": routing_signal.next_step_id,
                        "route": routing_signal.route,
                        "reason": routing_signal.reason,
                        "confidence": routing_signal.confidence,
                        "needs_human": routing_signal.needs_human,
                    }
                    updated = update_envelope_routing(
                        run_base=ctx.run_base,
                        step_id=ctx.step_id,
                        routing_signal=routing_dict,
                    )
                    if updated:
                        logger.debug(
                            "Updated envelope routing_signal for step %s via handoff_io",
                            ctx.step_id,
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
        "engine": engine.engine_id,
        "mode": engine._mode,
        "execution_mode": "session",
        "session_id": session_result.session_id,
        "provider": engine._provider or "claude-sdk",
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
        step_result.artifacts["handoff_path"] = str(committed_handoff_path)
        if finalize_result.envelope:
            step_result.artifacts["handoff"] = {
                "status": finalize_result.envelope.get("status"),
                "confidence": finalize_result.envelope.get("confidence"),
            }

    return step_result, events, routing_signal


def execute_step_session_sync(
    engine: "ClaudeStepEngine",
    ctx: StepContext,
    is_terminal: bool = False,
) -> Tuple[StepResult, Iterable[RunEvent], Optional[RoutingSignal]]:
    """Synchronous wrapper for execute_step_session.

    For callers that need synchronous execution.
    """
    return run_async_safely(execute_step_session(engine, ctx, is_terminal))
