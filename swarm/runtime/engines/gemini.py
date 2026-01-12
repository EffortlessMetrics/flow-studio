"""
gemini.py - Gemini CLI step engine implementation.

This module implements the GeminiStepEngine which executes steps
via the Gemini CLI with JSONL output.
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
    get_history_max_older_chars,
    get_history_max_recent_chars,
    get_resolved_context_budgets,
    is_stub_mode,
)
from swarm.runtime.history_priority import (
    HistoryPriority,
    get_priority_label,
    prioritize_history,
)
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
from swarm.runtime.types.tool_call import (
    NormalizedToolCall,
    from_gemini_events,
    truncate_output,
)

from .base import StepEngine
from .models import HistoryTruncationInfo, StepContext, StepResult

logger = logging.getLogger(__name__)


class GeminiStepEngine(StepEngine):
    """Step engine using Gemini CLI.

    Executes steps by invoking the Gemini CLI with step-specific prompts.
    Maps Gemini JSONL output to RunEvents.

    Configuration via environment:
        SWARM_GEMINI_CLI: Path to gemini CLI (default: "gemini")
        SWARM_GEMINI_STUB: Set to "1" to use stub mode for testing

    Context budgets are read from runtime.yaml via runtime_config.py.
    See docs/CONTEXT_BUDGETS.md for the full philosophy.
    """

    @property
    def HISTORY_BUDGET_CHARS(self) -> int:
        """Total budget for all previous step history (global default).

        Note: For flow-aware budgets, use _get_resolved_budgets() instead.
        """
        return get_context_budget_chars()

    @property
    def RECENT_STEP_MAX_CHARS(self) -> int:
        """Max chars for the most recent step output (global default).

        Note: For flow-aware budgets, use _get_resolved_budgets() instead.
        """
        return get_history_max_recent_chars()

    @property
    def OLDER_STEP_MAX_CHARS(self) -> int:
        """Max chars for older step outputs (global default).

        Note: For flow-aware budgets, use _get_resolved_budgets() instead.
        """
        return get_history_max_older_chars()

    def __init__(self, repo_root: Path, profile_id: Optional[str] = None):
        """Initialize the Gemini step engine.

        Args:
            repo_root: Repository root path.
            profile_id: Optional profile ID for flow-aware budget resolution.
        """
        self.repo_root = repo_root
        self._profile_id = profile_id
        self.gemini_cmd = get_cli_path("gemini")
        self.stub_mode = is_stub_mode("gemini")
        self.cli_available = shutil.which(self.gemini_cmd) is not None

    def _get_resolved_budgets(self, flow_key: Optional[str] = None, step_id: Optional[str] = None):
        """Get resolved budgets for the given flow/step context.

        Uses the ContextBudgetResolver to cascade through step, flow, profile,
        and global defaults to determine effective budget values.

        Args:
            flow_key: Optional flow key for flow-level resolution.
            step_id: Optional step ID for step-level resolution.

        Returns:
            ContextBudgetConfig with resolved values.
        """
        return get_resolved_context_budgets(
            flow_key=flow_key,
            step_id=step_id,
            profile_id=self._profile_id,
        )

    @property
    def engine_id(self) -> str:
        return "gemini-step"

    def run_step(self, ctx: StepContext) -> Tuple[StepResult, Iterable[RunEvent]]:
        """Execute a step via Gemini CLI.

        Args:
            ctx: Step execution context.

        Returns:
            Tuple of (StepResult, list of RunEvents).
        """
        events: List[RunEvent] = []
        start_time = datetime.now(timezone.utc)

        # Build prompt from context (returns tuple with truncation info and None)
        prompt, truncation_info, _ = self._build_prompt(ctx)

        # Stub mode for testing
        if self.stub_mode or not self.cli_available:
            logger.debug(
                "GeminiStepEngine using stub for step %s (stub_mode=%s, cli_available=%s)",
                ctx.step_id,
                self.stub_mode,
                self.cli_available,
            )
            end_time = datetime.now(timezone.utc)
            duration_ms = int((end_time - start_time).total_seconds() * 1000)

            result = StepResult(
                step_id=ctx.step_id,
                status="succeeded",
                output=f"[STUB] Step {ctx.step_id} completed successfully",
                duration_ms=duration_ms,
            )
            return result, events

        # Real execution via Gemini CLI
        try:
            output, cli_events = self._execute_gemini(ctx, prompt, truncation_info)
            events.extend(cli_events)

            end_time = datetime.now(timezone.utc)
            duration_ms = int((end_time - start_time).total_seconds() * 1000)

            result = StepResult(
                step_id=ctx.step_id,
                status="succeeded",
                output=output,
                duration_ms=duration_ms,
            )

        except Exception as e:
            logger.warning("Step %s failed: %s", ctx.step_id, e)
            end_time = datetime.now(timezone.utc)
            duration_ms = int((end_time - start_time).total_seconds() * 1000)

            result = StepResult(
                step_id=ctx.step_id,
                status="failed",
                output="",
                error=str(e),
                duration_ms=duration_ms,
            )

        return result, events

    def _build_prompt(self, ctx: StepContext) -> Tuple[str, Optional[HistoryTruncationInfo], None]:
        """Build a context-aware prompt for a step.

        Uses context budgeting to prevent prompts from growing unboundedly.
        Budget values are read from runtime.yaml (see docs/CONTEXT_BUDGETS.md):
        - Total history budget: HISTORY_BUDGET_CHARS (default: 200k chars)
        - Most recent step: RECENT_STEP_MAX_CHARS (default: 60k chars)
        - Older steps: OLDER_STEP_MAX_CHARS (default: 10k chars)
        - Stops adding history when budget is exceeded, adds truncation note

        Args:
            ctx: Step execution context.

        Returns:
            Tuple of (formatted prompt string, truncation info or None, None).
            Third element is None for API consistency with ClaudeStepEngine.
        """
        lines = [
            f"# Flow: {ctx.flow_title}",
            f"# Step: {ctx.step_id} (Step {ctx.step_index} of {ctx.total_steps})",
            f"# Run ID: {ctx.run_id}",
            "",
            "## Step Role",
            ctx.step_role,
            "",
        ]

        # Agent assignments
        if ctx.step_agents:
            lines.append("## Assigned Agents")
            for agent in ctx.step_agents:
                lines.append(f"- {agent}")
            lines.append("")

        # Teaching notes (scoped context for this step)
        if ctx.teaching_notes:
            tn = ctx.teaching_notes

            if tn.inputs:
                lines.append("## Expected Inputs")
                lines.append("Read the following files/artifacts for this step:")
                for input_path in tn.inputs:
                    lines.append(f"- {input_path}")
                lines.append("")

            if tn.outputs:
                lines.append("## Expected Outputs")
                lines.append("Produce the following files/artifacts:")
                for output_path in tn.outputs:
                    lines.append(f"- {output_path}")
                lines.append("")

            if tn.emphasizes:
                lines.append("## Key Behaviors")
                lines.append("Focus on these patterns and behaviors:")
                for emphasis in tn.emphasizes:
                    lines.append(f"- {emphasis}")
                lines.append("")

            if tn.constraints:
                lines.append("## Constraints")
                lines.append("Observe these limitations:")
                for constraint in tn.constraints:
                    lines.append(f"- {constraint}")
                lines.append("")

        # RUN_BASE instructions
        lines.extend(
            [
                "## Output Location",
                f"Write outputs to: {ctx.run_base}/",
                "Follow RUN_BASE conventions for all artifacts.",
                "",
            ]
        )

        # Previous step context with priority-aware budget management
        truncation_info: Optional[HistoryTruncationInfo] = None

        if ctx.history:
            lines.append("## Previous Steps Context")
            lines.append("The following steps have already been completed:")
            lines.append("")

            # Get resolved budgets for this step's context
            budgets = self._get_resolved_budgets(ctx.flow_key, ctx.step_id)
            history_budget = budgets.context_budget_chars
            recent_max = budgets.history_max_recent_chars
            older_max = budgets.history_max_older_chars

            # Sort history by priority (CRITICAL first, then HIGH, MEDIUM, LOW)
            # Within same priority, maintain chronological order
            prioritized = prioritize_history(ctx.history)
            total_steps = len(ctx.history)

            # Track which items we include and their priorities
            included_items: List[Tuple[int, Dict[str, Any], List[str]]] = []
            priority_counts: Dict[str, int] = {
                "CRITICAL": 0,
                "HIGH": 0,
                "MEDIUM": 0,
                "LOW": 0,
            }
            chars_used = 0

            # Most recent step index for determining output limits
            most_recent_idx = total_steps - 1 if total_steps > 0 else -1

            # Process by priority order, including highest-value items first
            for priority, orig_idx, prev in prioritized:
                is_most_recent = orig_idx == most_recent_idx
                step_lines: List[str] = []

                status_emoji = "[OK]" if prev.get("status") == "succeeded" else "[FAIL]"
                priority_label = get_priority_label(priority)
                step_lines.append(f"### Step: {prev.get('step_id')} {status_emoji}")

                if prev.get("output"):
                    output = str(prev.get("output"))
                    # CRITICAL items get full recent budget, others based on recency
                    if priority >= HistoryPriority.CRITICAL:
                        max_chars = recent_max
                    elif is_most_recent:
                        max_chars = recent_max
                    else:
                        max_chars = older_max
                    if len(output) > max_chars:
                        output = output[:max_chars] + "... (truncated)"
                    step_lines.append(f"Output: {output}")

                if prev.get("error"):
                    error = str(prev.get("error"))
                    max_error = 200
                    if len(error) > max_error:
                        error = error[:max_error] + "... (truncated)"
                    step_lines.append(f"Error: {error}")

                step_lines.append("")

                # Calculate chars for this step
                step_text = "\n".join(step_lines)
                step_chars = len(step_text)

                # Check if adding this step would exceed budget
                if chars_used + step_chars > history_budget:
                    # Budget exceeded - skip lower priority items
                    continue

                # Include this item
                included_items.append((orig_idx, prev, step_lines))
                priority_counts[priority_label] += 1
                chars_used += step_chars

            # Sort included items back to chronological order for output
            included_items.sort(key=lambda x: x[0])

            # Build history lines in chronological order
            history_lines: List[str] = []
            for _, _, step_lines in included_items:
                history_lines.extend(step_lines)

            steps_included = len(included_items)

            # Track truncation metadata with priority information
            truncated = steps_included < total_steps
            truncation_info = HistoryTruncationInfo(
                steps_included=steps_included,
                steps_total=total_steps,
                chars_used=chars_used,
                budget_chars=history_budget,
                truncated=truncated,
                priority_aware=True,
                priority_distribution=priority_counts,
            )

            # Add machine-readable truncation warning if we didn't include all steps
            if truncated:
                truncation_warning = truncation_info.truncation_note
                history_lines.insert(0, truncation_warning + "\n")

                # Log for observability
                logger.debug(
                    "History truncation: %s (flow=%s, step=%s)",
                    truncation_warning,
                    ctx.flow_key,
                    ctx.step_id,
                )

            lines.extend(history_lines)

        # Instructions
        lines.extend(
            [
                "## Instructions",
                "1. Execute the step role as described above",
                "2. Use the assigned agent's capabilities and perspective",
                "3. Read any required inputs from previous steps or RUN_BASE",
                "4. Write all outputs to the correct RUN_BASE location",
                "5. Be concise and focused on the specific step",
                "",
            ]
        )

        return "\n".join(lines), truncation_info, None

    def _execute_gemini(
        self,
        ctx: StepContext,
        prompt: str,
        truncation_info: Optional[HistoryTruncationInfo] = None,
    ) -> Tuple[str, List[RunEvent]]:
        """Execute Gemini CLI and capture output.

        Captures assistant content from Gemini JSONL output and writes:
        - Transcript JSONL to RUN_BASE/llm/<step_id>-gemini.jsonl
        - Receipt JSON to RUN_BASE/receipts/<step_id>-gemini.json

        Args:
            ctx: Step execution context.
            prompt: The prompt to send to Gemini.
            truncation_info: Optional history truncation metadata for context budgets.

        Returns:
            Tuple of (actual assistant output text, list of events).

        Raises:
            RuntimeError: If execution fails.
        """
        events: List[RunEvent] = []
        start_time = datetime.now(timezone.utc)

        args = [
            self.gemini_cmd,
            "--output-format",
            "stream-json",
            "--prompt",
            prompt,
        ]
        cmd = " ".join(shlex.quote(a) for a in args)

        process = subprocess.Popen(
            cmd,
            cwd=str(self.repo_root),
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        # Collect raw events for transcript and track assistant content
        raw_events: List[Dict[str, Any]] = []
        full_assistant_text: List[str] = []
        token_counts: Dict[str, int] = {"prompt": 0, "completion": 0, "total": 0}

        # Track tool calls for normalized receipts
        tool_calls: List[NormalizedToolCall] = []
        pending_tool_use: Optional[Dict[str, Any]] = None

        if process.stdout:
            for line in process.stdout:
                line = line.strip()
                if not line:
                    continue

                # Try to parse and map to event
                try:
                    event_data = json.loads(line)
                    # Store raw event for transcript
                    raw_events.append(event_data)

                    # Extract assistant content from message events
                    event_type = event_data.get("type", "")
                    if event_type == "message":
                        role = event_data.get("role", "")
                        if role == "assistant":
                            content = event_data.get("content", "")
                            if content:
                                full_assistant_text.append(content)

                    # Track tool calls for normalized receipts
                    if event_type == "tool_use":
                        # Store pending tool_use to match with result
                        pending_tool_use = event_data
                    elif event_type == "tool_result":
                        # Create normalized tool call from pending use + result
                        if pending_tool_use is not None:
                            tool_call = from_gemini_events(
                                pending_tool_use,
                                event_data,
                            )
                            tool_calls.append(tool_call)
                            pending_tool_use = None
                        else:
                            # tool_result without matching tool_use
                            # Create a tool call with just the result info
                            tool_call = from_gemini_events(
                                {
                                    "name": event_data.get("tool") or event_data.get("name") or "unknown",
                                    "args": {},
                                },
                                event_data,
                            )
                            tool_calls.append(tool_call)

                    # Extract token counts if available (standard format)
                    if "usage" in event_data:
                        usage = event_data["usage"]
                        if "prompt_tokens" in usage:
                            token_counts["prompt"] = usage["prompt_tokens"]
                        if "completion_tokens" in usage:
                            token_counts["completion"] = usage["completion_tokens"]
                        if "total_tokens" in usage:
                            token_counts["total"] = usage["total_tokens"]
                    # Some Gemini responses use different keys
                    if "promptTokenCount" in event_data:
                        token_counts["prompt"] = event_data["promptTokenCount"]
                    if "candidatesTokenCount" in event_data:
                        token_counts["completion"] = event_data["candidatesTokenCount"]
                    if "totalTokenCount" in event_data:
                        token_counts["total"] = event_data["totalTokenCount"]

                    event = self._map_gemini_event(ctx, event_data)
                    if event:
                        events.append(event)
                except json.JSONDecodeError:
                    # Log as text event and include in raw events
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

        _, stderr = process.communicate()
        end_time = datetime.now(timezone.utc)
        duration_ms = int((end_time - start_time).total_seconds() * 1000)

        if process.returncode != 0:
            error_msg = stderr[:500] if stderr else f"Exit code {process.returncode}"
            raise RuntimeError(f"Gemini CLI failed: {error_msg}")

        # Write transcript JSONL to RUN_BASE/llm/<step_id>-gemini.jsonl
        self._write_transcript(ctx, raw_events)

        # Write receipt JSON to RUN_BASE/receipts/<step_id>-gemini.json
        status = "succeeded"
        self._write_receipt(
            ctx,
            start_time,
            end_time,
            duration_ms,
            status,
            token_counts,
            truncation_info,
            tool_calls,
        )

        # Build the actual assistant output text
        combined_text = "".join(full_assistant_text)
        if len(combined_text) > 2000:
            output_text = combined_text[:2000] + "... (truncated)"
        elif combined_text:
            output_text = combined_text
        else:
            # Fallback if no assistant content was captured
            output_text = f"Step {ctx.step_id} completed. Output lines: {len(raw_events)}"

        return output_text, events

    def _write_transcript(self, ctx: StepContext, raw_events: List[Dict[str, Any]]) -> Path:
        """Write transcript JSONL to RUN_BASE/llm/<step_id>-<agent_key>-gemini.jsonl.

        Args:
            ctx: Step execution context.
            raw_events: List of raw Gemini events to write.

        Returns:
            Path to the transcript file.
        """
        agent_key = ctx.step_agents[0] if ctx.step_agents else "unknown"
        ensure_llm_dir(ctx.run_base)

        t_path = make_transcript_path(ctx.run_base, ctx.step_id, agent_key, "gemini")
        with t_path.open("w", encoding="utf-8") as f:
            for event in raw_events:
                # Add timestamp if not present
                if "timestamp" not in event:
                    event["timestamp"] = datetime.now(timezone.utc).isoformat() + "Z"
                f.write(json.dumps(event) + "\n")

        logger.debug("Wrote transcript to %s", t_path)
        return t_path

    def _write_receipt(
        self,
        ctx: StepContext,
        start_time: datetime,
        end_time: datetime,
        duration_ms: int,
        status: str,
        token_counts: Dict[str, int],
        truncation_info: Optional[HistoryTruncationInfo] = None,
        tool_calls: Optional[List[NormalizedToolCall]] = None,
    ) -> Path:
        """Write receipt JSON to RUN_BASE/receipts/<step_id>-<agent_key>.json.

        Args:
            ctx: Step execution context.
            start_time: When execution started.
            end_time: When execution completed.
            duration_ms: Execution duration in milliseconds.
            status: Execution status.
            token_counts: Token usage counts.
            truncation_info: Optional history truncation metadata for context budgets.
            tool_calls: Optional list of normalized tool calls observed during execution.

        Returns:
            Path to the receipt file.
        """
        agent_key = ctx.step_agents[0] if ctx.step_agents else "unknown"
        ensure_receipts_dir(ctx.run_base)

        r_path = make_receipt_path(ctx.run_base, ctx.step_id, agent_key)
        t_path = make_transcript_path(ctx.run_base, ctx.step_id, agent_key, "gemini")

        # Determine mode for receipt
        mode = "stub" if (self.stub_mode or not self.cli_available) else "cli"

        receipt = {
            "engine": self.engine_id,
            "mode": mode,
            "provider": "gemini",
            "model": "gemini",
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

        # Add context truncation info if provided
        if truncation_info:
            receipt["context_truncation"] = truncation_info.to_dict()

        # Add normalized tool calls if any were observed
        if tool_calls:
            receipt["tool_calls"] = [tc.to_dict() for tc in tool_calls]

        with r_path.open("w", encoding="utf-8") as f:
            json.dump(receipt, f, indent=2)

        logger.debug("Wrote receipt to %s", r_path)
        return r_path

    def _map_gemini_event(
        self,
        ctx: StepContext,
        gemini_event: Dict[str, Any],
    ) -> Optional[RunEvent]:
        """Map Gemini JSONL event to RunEvent.

        Args:
            ctx: Step execution context.
            gemini_event: Raw event from Gemini CLI.

        Returns:
            Mapped RunEvent or None if event should be skipped.
        """
        event_type = gemini_event.get("type", "unknown")
        now = datetime.now(timezone.utc)

        # Map event types
        if event_type == "message":
            role = gemini_event.get("role", "assistant")
            kind = "assistant_message" if role == "assistant" else "user_message"
        elif event_type == "tool_use":
            kind = "tool_start"
        elif event_type == "tool_result":
            kind = "tool_end"
        elif event_type == "error":
            kind = "error"
        elif event_type == "result":
            kind = "step_complete"
        elif event_type == "init":
            kind = "backend_init"
        elif event_type == "text":
            kind = "log"
        else:
            kind = event_type

        # Build payload
        payload: Dict[str, Any] = {}
        if event_type == "message":
            payload = {
                "role": gemini_event.get("role"),
                "content": gemini_event.get("content", ""),
            }
        elif event_type == "tool_use":
            payload = {
                "tool": gemini_event.get("tool") or gemini_event.get("name"),
                "input": gemini_event.get("input") or gemini_event.get("args"),
            }
        elif event_type == "tool_result":
            payload = {
                "tool": gemini_event.get("tool") or gemini_event.get("name"),
                "success": gemini_event.get("success", False),
                "output": gemini_event.get("output") or gemini_event.get("result"),
            }
        elif event_type == "text":
            payload = {"message": gemini_event.get("message")}
        elif event_type == "error":
            payload = {"error": gemini_event.get("error") or gemini_event.get("message")}
        else:
            payload = gemini_event

        return RunEvent(
            run_id=ctx.run_id,
            ts=now,
            kind=kind,
            flow_key=ctx.flow_key,
            step_id=ctx.step_id,
            agent_key=ctx.step_agents[0] if ctx.step_agents else None,
            payload=payload,
        )
