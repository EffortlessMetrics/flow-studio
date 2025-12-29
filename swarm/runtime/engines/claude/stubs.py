"""
stubs.py - Stub implementations for ClaudeStepEngine.

This module provides zero-cost stub implementations for testing and CI.
All stub methods simulate execution without calling real LLM APIs.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from swarm.runtime.diff_scanner import (
    file_changes_to_dict,
    scan_file_changes_sync,
)
from swarm.runtime.path_helpers import (
    ensure_llm_dir,
    ensure_receipts_dir,
    receipt_path as make_receipt_path,
    transcript_path as make_transcript_path,
)
from swarm.runtime.handoff_io import write_handoff_envelope
from swarm.runtime.types import (
    HandoffEnvelope,
    RoutingDecision,
    RoutingSignal,
    RunEvent,
    handoff_envelope_to_dict,
)

from ..models import (
    FinalizationResult,
    HistoryTruncationInfo,
    StepContext,
    StepResult,
)

logger = logging.getLogger(__name__)


def run_worker_stub(
    ctx: StepContext,
    engine_id: str,
) -> Tuple[StepResult, List[RunEvent], str]:
    """Stub implementation of run_worker.

    Args:
        ctx: Step execution context.
        engine_id: Engine identifier for receipts.

    Returns:
        Tuple of (StepResult, events, work_summary).
    """
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

    work_summary = f"[STUB:{engine_id}] Step {ctx.step_id} work phase completed successfully"

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


def finalize_step_stub(
    ctx: StepContext,
    step_result: StepResult,
    work_summary: str,
    engine_id: str,
    provider: Optional[str] = None,
) -> FinalizationResult:
    """Stub implementation of finalize_step.

    Args:
        ctx: Step execution context.
        step_result: Result from work phase.
        work_summary: Summary from work phase.
        engine_id: Engine identifier for receipts.
        provider: Optional provider name.

    Returns:
        FinalizationResult with handoff data and envelope.
    """
    events: List[RunEvent] = []
    agent_key = ctx.step_agents[0] if ctx.step_agents else None

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
        "routing_signal": {
            "decision": RoutingDecision.ADVANCE.value,
            "reason": "stub_finalization",
            "confidence": 1.0,
            "needs_human": False,
        },
    }

    # Write using unified IO (handles draft + committed + validation)
    write_handoff_envelope(
        run_base=ctx.run_base,
        step_id=ctx.step_id,
        envelope_data=handoff_data,
        write_draft=True,
        validate=True,
    )

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

    # Write receipt for lifecycle mode (run_worker + finalize_step)
    ensure_receipts_dir(ctx.run_base)
    r_path = make_receipt_path(ctx.run_base, ctx.step_id, agent_key or "unknown")
    receipt = {
        "engine": engine_id,
        "mode": "stub",
        "provider": provider or "none",
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


def finalize_from_existing_handoff(
    ctx: StepContext,
    step_result: StepResult,
    work_summary: str,
    handoff_path: Path,
) -> FinalizationResult:
    """Create FinalizationResult from handoff written during work phase.

    Args:
        ctx: Step execution context.
        step_result: Result from work phase.
        work_summary: Summary from work phase.
        handoff_path: Path to existing handoff file.

    Returns:
        FinalizationResult with parsed handoff data.
    """
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


def run_step_stub(
    ctx: StepContext,
    engine_id: str,
    provider: Optional[str],
    build_prompt_fn: Callable[[StepContext], Tuple[str, Optional[HistoryTruncationInfo], Optional[str]]],
) -> Tuple[StepResult, Iterable[RunEvent]]:
    """Execute a step in stub mode.

    Args:
        ctx: Step execution context.
        engine_id: Engine identifier for receipts.
        provider: Provider name for receipts.
        build_prompt_fn: Function to build prompt (for truncation info).

    Returns:
        Tuple of (StepResult, events).
    """
    start_time = datetime.now(timezone.utc)
    agent_key = ctx.step_agents[0] if ctx.step_agents else "unknown"

    ensure_llm_dir(ctx.run_base)
    ensure_receipts_dir(ctx.run_base)

    t_path = make_transcript_path(ctx.run_base, ctx.step_id, agent_key, "claude")
    r_path = make_receipt_path(ctx.run_base, ctx.step_id, agent_key)

    _, truncation_info, _ = build_prompt_fn(ctx)

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
        "engine": engine_id,
        "mode": "stub",
        "provider": provider or "none",
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
                "engine_id": engine_id,
                "mode": "stub",
                "provider": provider or "none",
                "transcript_path": str(t_path.relative_to(ctx.run_base)),
                "receipt_path": str(r_path.relative_to(ctx.run_base)),
            },
        )
    ]

    result = StepResult(
        step_id=ctx.step_id,
        status="succeeded",
        output=f"[STUB:{engine_id}] Step {ctx.step_id} completed successfully",
        duration_ms=duration_ms,
        artifacts={
            "transcript_path": str(t_path),
            "receipt_path": str(r_path),
        },
    )

    return result, events


def make_failed_result(
    ctx: StepContext, error: str
) -> Tuple[StepResult, Iterable[RunEvent]]:
    """Create a failed result for error cases.

    Args:
        ctx: Step execution context.
        error: Error message.

    Returns:
        Tuple of (failed StepResult, empty events).
    """
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
