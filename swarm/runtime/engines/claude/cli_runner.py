"""
cli_runner.py - CLI execution for ClaudeStepEngine.

This module provides CLI-based step execution using the Claude CLI
with `--output-format stream-json`.
"""

from __future__ import annotations

import json
import shlex
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from swarm.runtime.path_helpers import (
    ensure_llm_dir,
    ensure_receipts_dir,
)
from swarm.runtime.path_helpers import (
    receipt_path as make_receipt_path,
)
from swarm.runtime.path_helpers import (
    transcript_path as make_transcript_path,
)
from swarm.runtime.types import RunEvent

from ..models import (
    HistoryTruncationInfo,
    StepContext,
    StepResult,
)


def run_step_cli(
    ctx: StepContext,
    cli_cmd: str,
    engine_id: str,
    provider: Optional[str],
    build_prompt_fn: Callable[
        [StepContext], Tuple[str, Optional[HistoryTruncationInfo], Optional[str]]
    ],
    timeout: int = 300,
) -> Tuple[StepResult, Iterable[RunEvent]]:
    """Execute a step using the Claude CLI.

    Args:
        ctx: Step execution context.
        cli_cmd: CLI command (e.g., "claude").
        engine_id: Engine identifier for receipts.
        provider: Provider name for receipts.
        build_prompt_fn: Function to build prompt.
        timeout: Execution timeout in seconds.

    Returns:
        Tuple of (StepResult, events).
    """
    events: List[RunEvent] = []
    start_time = datetime.now(timezone.utc)
    agent_key = ctx.step_agents[0] if ctx.step_agents else "unknown"

    ensure_llm_dir(ctx.run_base)
    ensure_receipts_dir(ctx.run_base)

    t_path = make_transcript_path(ctx.run_base, ctx.step_id, agent_key, "claude")
    r_path = make_receipt_path(ctx.run_base, ctx.step_id, agent_key)

    prompt, truncation_info, _ = build_prompt_fn(ctx)

    args = [
        cli_cmd,
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

    stdout_data, stderr_data = process.communicate(input=prompt, timeout=timeout)

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
                        token_counts["total"] = token_counts["prompt"] + token_counts["completion"]
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
        "engine": engine_id,
        "mode": "cli",
        "execution_mode": "legacy",
        "provider": provider,
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
