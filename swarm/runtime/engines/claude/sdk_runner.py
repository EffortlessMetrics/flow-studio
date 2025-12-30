"""
sdk_runner.py - SDK execution helpers for ClaudeStepEngine.

This module provides SDK-based step execution using the Claude Agent SDK.
It contains helper functions for event processing and query execution.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Tuple

from swarm.runtime.claude_sdk import (
    create_high_trust_options,
    create_options_from_plan,
    get_sdk_module,
)
from swarm.runtime.diff_scanner import (
    file_changes_to_dict,
    scan_file_changes,
)
from swarm.runtime.path_helpers import (
    ensure_llm_dir,
    ensure_receipts_dir,
)
from swarm.runtime.path_helpers import (
    handoff_envelope_path as make_handoff_envelope_path,
)
from swarm.runtime.path_helpers import (
    transcript_path as make_transcript_path,
)
from swarm.runtime.resolvers import (
    build_finalization_prompt as build_finalization_prompt_from_template,
)
from swarm.runtime.resolvers import (
    load_envelope_writer_prompt,
)
from swarm.runtime.types import (
    HandoffEnvelope,
    RoutingSignal,
    RunEvent,
)

from ..models import (
    FinalizationResult,
    HistoryTruncationInfo,
    StepContext,
    StepResult,
)
from .envelope import write_handoff_envelope
from .router import run_router_session
from .spec_adapter import try_compile_from_spec

if TYPE_CHECKING:
    pass

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


def build_finalization_prompt(
    ctx: StepContext,
    handoff_path: Path,
    work_summary: str,
    step_result: StepResult,
    repo_root: Optional[Path] = None,
) -> str:
    """Build the finalization prompt using resolvers module.

    Args:
        ctx: Step execution context.
        handoff_path: Path where handoff should be written.
        work_summary: Summary from work phase.
        step_result: Result from work phase.
        repo_root: Repository root path.

    Returns:
        Formatted finalization prompt.
    """
    try:
        template = load_envelope_writer_prompt(repo_root)
        if template:
            prompt = build_finalization_prompt_from_template(
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


async def run_worker_async(
    ctx: StepContext,
    repo_root: Optional[Path],
    profile_id: Optional[str],
    build_prompt_fn: Callable[
        [StepContext], Tuple[str, Optional[HistoryTruncationInfo], Optional[str]]
    ],
    stats_db: Optional[Any] = None,
) -> Tuple[StepResult, List[RunEvent], str]:
    """Async implementation of run_worker.

    Args:
        ctx: Step execution context.
        repo_root: Repository root path.
        profile_id: Profile ID for prompt building.
        build_prompt_fn: Function to build prompt.
        stats_db: Optional stats database for telemetry.

    Returns:
        Tuple of (StepResult, events, work_summary).
    """
    sdk = get_sdk_module()
    query = sdk.query

    start_time = datetime.now(timezone.utc)
    agent_key = ctx.step_agents[0] if ctx.step_agents else "unknown"
    events: List[RunEvent] = []

    ensure_llm_dir(ctx.run_base)
    ensure_receipts_dir(ctx.run_base)

    # Try spec-based prompt compilation first, fall back to legacy
    spec_result = try_compile_from_spec(ctx, repo_root)
    plan = None  # Track plan for later use in envelope creation

    if spec_result:
        # Use spec-based prompts and SDK options from PromptPlan
        prompt, agent_persona, plan = spec_result
        logger.info(
            "Spec-based execution for step %s: hash=%s, station=%s v%d, model=%s",
            plan.step_id,
            plan.prompt_hash,
            plan.station_id,
            plan.station_version,
            plan.model,
        )
        logger.debug(
            "PromptPlan SDK options: permission_mode=%s, max_turns=%d, sandbox=%s, tools=%s",
            plan.permission_mode,
            plan.max_turns,
            plan.sandbox_enabled,
            plan.allowed_tools[:3] if plan.allowed_tools else [],  # Log first 3 tools
        )
        truncation_info = None  # Spec compilation handles context management

        # Write PromptReceipt for audit trail
        from swarm.spec.types import create_prompt_receipt

        receipt = create_prompt_receipt(plan)
        receipt_path = ctx.run_base / "receipts" / f"prompt_receipt_{ctx.step_id}.json"
        receipt_path.parent.mkdir(parents=True, exist_ok=True)

        receipt_dict = {
            "prompt_hash": receipt.prompt_hash,
            "fragment_manifest": list(receipt.fragment_manifest),
            "context_pack_hash": receipt.context_pack_hash,
            "model_tier": receipt.model_tier,
            "tool_profile": list(receipt.tool_profile),
            "compiled_at": receipt.compiled_at,
            "compiler_version": receipt.compiler_version,
            "station_id": receipt.station_id,
            "flow_id": receipt.flow_id,
            "step_id": receipt.step_id,
        }

        with open(receipt_path, "w", encoding="utf-8") as f:
            json.dump(receipt_dict, f, indent=2)

        logger.debug(
            "PromptReceipt written to %s for step %s",
            receipt_path,
            ctx.step_id,
        )

        # Use create_options_from_plan to wire all PromptPlan SDK options
        cwd = str(repo_root) if repo_root else str(Path.cwd())
        options = create_options_from_plan(plan, cwd=cwd)

        # Log verification and handoff contracts for traceability
        if plan.verification.required_artifacts:
            logger.debug(
                "Step %s verification: required_artifacts=%s",
                ctx.step_id,
                plan.verification.required_artifacts,
            )
        if plan.handoff.path:
            logger.debug(
                "Step %s handoff: path=%s, required_fields=%s",
                ctx.step_id,
                plan.handoff.path,
                plan.handoff.required_fields,
            )
    else:
        # Fall back to legacy prompt builder
        logger.debug(
            "Spec not available for step %s, using legacy prompt builder",
            ctx.step_id,
        )
        prompt, truncation_info, agent_persona = build_prompt_fn(ctx)

        cwd = str(repo_root) if repo_root else str(Path.cwd())
        options = create_high_trust_options(
            cwd=cwd,
            permission_mode="bypassPermissions",
            system_prompt_append=agent_persona,
        )

    # DEPRECATED: Direct stats recording is a no-op in projection-only mode.
    if stats_db:
        try:
            stats_db.record_step_start(
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
                if stats_db:
                    try:
                        target_path = None
                        if tool_name in ("Edit", "Write", "Read"):
                            target_path = str(tool_input.get("file_path", ""))[:500]
                        stats_db.record_tool_call(
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
                                stats_db.record_file_change(
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

    # Build artifacts dict with optional spec traceability
    artifacts: Dict[str, Any] = {
        "transcript_path": str(t_path),
        "token_counts": token_counts,
        "model": model_name,
    }

    # Add spec traceability if plan was used
    if plan:
        artifacts["spec_based"] = True
        artifacts["spec_model"] = plan.model  # Preserve spec model for finalize/route phases
        artifacts["prompt_hash"] = plan.prompt_hash
        artifacts["station_id"] = plan.station_id
        artifacts["station_version"] = plan.station_version
        artifacts["flow_id"] = plan.flow_id
        artifacts["flow_version"] = plan.flow_version
        # Include handoff path from spec for envelope validation
        if plan.handoff.path:
            artifacts["spec_handoff_path"] = plan.handoff.path
        # Include verification requirements for downstream validation
        if plan.verification.required_artifacts:
            artifacts["spec_required_artifacts"] = list(plan.verification.required_artifacts)
    else:
        artifacts["spec_based"] = False

    result = StepResult(
        step_id=ctx.step_id,
        status=status,
        output=output_text,
        error=error,
        duration_ms=duration_ms,
        artifacts=artifacts,
    )

    return result, events, work_summary


async def finalize_step_async(
    ctx: StepContext,
    step_result: StepResult,
    work_summary: str,
    repo_root: Optional[Path] = None,
) -> FinalizationResult:
    """Async implementation of finalize_step.

    Args:
        ctx: Step execution context.
        step_result: Result from work phase.
        work_summary: Summary from work phase.
        repo_root: Repository root path.

    Returns:
        FinalizationResult with handoff data and envelope.
    """
    sdk = get_sdk_module()
    query = sdk.query

    events: List[RunEvent] = []
    raw_events: List[Dict[str, Any]] = []
    agent_key = ctx.step_agents[0] if ctx.step_agents else "unknown"

    handoff_dir = ctx.run_base / "handoff"
    handoff_path = handoff_dir / f"{ctx.step_id}.draft.json"
    handoff_dir.mkdir(parents=True, exist_ok=True)

    cwd = str(repo_root) if repo_root else str(Path.cwd())

    # Extract spec model from work phase artifacts for consistent model usage
    spec_model = None
    if step_result.artifacts:
        spec_model = step_result.artifacts.get("spec_model")

    options = create_high_trust_options(
        cwd=cwd,
        permission_mode="bypassPermissions",
        model=spec_model,  # Use spec model if available, otherwise SDK default
    )

    finalization_prompt = build_finalization_prompt(
        ctx=ctx,
        handoff_path=handoff_path,
        work_summary=work_summary,
        step_result=step_result,
        repo_root=repo_root,
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
                        getattr(b, "text", str(getattr(b, "content", ""))) for b in content
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
    file_changes = await scan_file_changes(repo_root)
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
                    "envelope_path": str(make_handoff_envelope_path(ctx.run_base, ctx.step_id)),
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


async def route_step_async(
    ctx: StepContext,
    handoff_data: Dict[str, Any],
    repo_root: Optional[Path] = None,
    spec_model: Optional[str] = None,
) -> Optional[RoutingSignal]:
    """Async implementation of route_step.

    Args:
        ctx: Step execution context.
        handoff_data: Parsed handoff data.
        repo_root: Repository root path.
        spec_model: Model from spec to use for routing session.

    Returns:
        RoutingSignal if determined, None if routing failed.
    """
    cwd = str(repo_root) if repo_root else str(Path.cwd())

    try:
        routing_signal = await run_router_session(
            handoff_data=handoff_data,
            ctx=ctx,
            cwd=cwd,
            model=spec_model,
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
