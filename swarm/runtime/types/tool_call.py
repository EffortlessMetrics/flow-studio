"""Normalized tool call representation for unified receipts.

This module provides a transport-agnostic representation of tool calls that
can be used in receipts regardless of which transport executed the step.

Different transports have different tool visibility:
- Claude SDK: Full ToolUseEvent/ToolResultEvent with all details
- Gemini CLI: JSONL events with tool_use/tool_result
- Claude CLI: No structured tool events (limited visibility)

The NormalizedToolCall provides a single format for receipts, enabling
consistent auditing and replay analysis across all transports.

Usage:
    from swarm.runtime.types.tool_call import (
        NormalizedToolCall,
        from_sdk_events,
        from_gemini_events,
        from_stub,
        truncate_output,
    )

    # From Claude SDK events
    tool_call = from_sdk_events(tool_use_event, tool_result_event)

    # From Gemini CLI JSONL events
    tool_call = from_gemini_events(tool_use_dict, tool_result_dict)

    # For stub/mock execution
    tool_call = from_stub("Read", {"file_path": "/path/to/file"})

    # Serialize for receipt
    receipt_data = tool_call.to_dict()
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional


def truncate_output(output: str, max_chars: int = 2000) -> str:
    """Truncate output to a maximum number of characters.

    Large tool outputs (e.g., reading a big file, grep results) can bloat
    receipts. This function truncates while preserving useful information.

    Args:
        output: The output string to truncate.
        max_chars: Maximum characters to retain. Defaults to 2000.

    Returns:
        Truncated string with indicator if truncation occurred.

    Example:
        >>> truncate_output("x" * 5000, max_chars=100)
        'xxxx... [truncated, 5000 chars total]'
    """
    if not output:
        return ""

    if len(output) <= max_chars:
        return output

    # Keep first portion and add truncation indicator
    truncation_indicator = f"... [truncated, {len(output)} chars total]"
    available_chars = max_chars - len(truncation_indicator)

    if available_chars <= 0:
        return truncation_indicator

    return output[:available_chars] + truncation_indicator


@dataclass
class NormalizedToolCall:
    """Normalized representation of a tool call across all transports.

    This is the single format used in receipts regardless of which
    transport executed the step. It captures the essential information
    about a tool invocation for auditing and replay.

    Attributes:
        tool_name: Name of the tool (e.g., "Write", "Read", "Bash", "Edit").
        tool_input: Tool arguments as a dictionary.
        tool_output: Result text (truncated if large). None if not available.
        success: Whether the tool execution succeeded.
        duration_ms: Execution duration in milliseconds.
        blocked: Whether the tool call was blocked by policy.
        blocked_reason: Reason for blocking if blocked is True.
        source: How this tool call was captured:
            - "sdk": From Claude SDK ToolUseEvent/ToolResultEvent
            - "cli-observed": Parsed from CLI output/JSONL
            - "kernel-executed": Tool executed directly by kernel
            - "stub": Synthetic/mock tool call
        timestamp: ISO 8601 timestamp when the tool was invoked.

    Example:
        >>> tool_call = NormalizedToolCall(
        ...     tool_name="Bash",
        ...     tool_input={"command": "ls -la"},
        ...     tool_output="total 42\\ndrwxr-xr-x ...",
        ...     success=True,
        ...     duration_ms=150,
        ...     source="sdk",
        ... )
        >>> receipt_data = tool_call.to_dict()
    """

    tool_name: str
    tool_input: Dict[str, Any]
    tool_output: Optional[str] = None
    success: bool = True
    duration_ms: int = 0
    blocked: bool = False
    blocked_reason: Optional[str] = None
    source: str = "unknown"
    timestamp: Optional[str] = None

    def __post_init__(self) -> None:
        """Set timestamp if not provided."""
        if self.timestamp is None:
            self.timestamp = datetime.now(timezone.utc).isoformat() + "Z"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization.

        Returns:
            Dictionary representation suitable for JSON serialization.
        """
        result: Dict[str, Any] = {
            "tool_name": self.tool_name,
            "tool_input": self.tool_input,
            "success": self.success,
            "duration_ms": self.duration_ms,
            "source": self.source,
            "timestamp": self.timestamp,
        }

        # Only include optional fields if they have values
        if self.tool_output is not None:
            result["tool_output"] = self.tool_output

        if self.blocked:
            result["blocked"] = True
            if self.blocked_reason:
                result["blocked_reason"] = self.blocked_reason

        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "NormalizedToolCall":
        """Create NormalizedToolCall from a dictionary.

        Args:
            data: Dictionary with tool call fields.

        Returns:
            Parsed NormalizedToolCall instance.
        """
        return cls(
            tool_name=data.get("tool_name", "unknown"),
            tool_input=data.get("tool_input", {}),
            tool_output=data.get("tool_output"),
            success=data.get("success", True),
            duration_ms=data.get("duration_ms", 0),
            blocked=data.get("blocked", False),
            blocked_reason=data.get("blocked_reason"),
            source=data.get("source", "unknown"),
            timestamp=data.get("timestamp"),
        )


# =============================================================================
# Factory Functions
# =============================================================================


def from_sdk_events(
    tool_use_event: Any,
    tool_result_event: Optional[Any] = None,
    *,
    duration_ms: int = 0,
    blocked: bool = False,
    blocked_reason: Optional[str] = None,
    max_output_chars: int = 2000,
) -> NormalizedToolCall:
    """Create NormalizedToolCall from Claude SDK events.

    The Claude SDK emits ToolUseEvent when a tool is invoked and
    ToolResultEvent when the result is available. This factory
    combines both into a normalized representation.

    Args:
        tool_use_event: The ToolUseEvent from Claude SDK. Expected to have:
            - tool_name or name: Tool name
            - input or args: Tool input parameters
            - id or tool_use_id: Optional tool use ID
        tool_result_event: Optional ToolResultEvent with result. Expected to have:
            - tool_result or result: The result text
            - success: Boolean indicating success
        duration_ms: Execution duration if known (often calculated externally).
        blocked: Whether the tool was blocked by policy.
        blocked_reason: Reason for blocking.
        max_output_chars: Maximum characters to retain in output.

    Returns:
        NormalizedToolCall with source="sdk".

    Example:
        >>> # In SDK event processing loop:
        >>> if event_type == "ToolUseEvent":
        ...     pending_tool_use = event
        >>> elif event_type == "ToolResultEvent":
        ...     tool_call = from_sdk_events(pending_tool_use, event)
        ...     tool_calls.append(tool_call)
    """
    # Extract tool name
    tool_name = getattr(
        tool_use_event,
        "tool_name",
        getattr(tool_use_event, "name", "unknown"),
    )

    # Extract tool input
    tool_input = getattr(
        tool_use_event,
        "input",
        getattr(tool_use_event, "args", {}),
    )
    if not isinstance(tool_input, dict):
        tool_input = {"value": tool_input} if tool_input else {}

    # Extract result from tool_result_event if provided
    tool_output: Optional[str] = None
    success = True

    if tool_result_event is not None:
        raw_result = getattr(
            tool_result_event,
            "tool_result",
            getattr(tool_result_event, "result", None),
        )
        if raw_result is not None:
            tool_output = truncate_output(str(raw_result), max_output_chars)

        success = getattr(tool_result_event, "success", True)

    return NormalizedToolCall(
        tool_name=tool_name,
        tool_input=tool_input,
        tool_output=tool_output,
        success=success,
        duration_ms=duration_ms,
        blocked=blocked,
        blocked_reason=blocked_reason,
        source="sdk",
    )


def from_gemini_events(
    tool_use_dict: Dict[str, Any],
    tool_result_dict: Optional[Dict[str, Any]] = None,
    *,
    max_output_chars: int = 2000,
) -> NormalizedToolCall:
    """Create NormalizedToolCall from Gemini CLI JSONL events.

    Gemini CLI emits JSONL events that can be parsed into dictionaries.
    This factory handles the Gemini-specific event format.

    Args:
        tool_use_dict: Dictionary from parsed tool_use JSONL event.
            Expected keys:
            - "name" or "tool_name": Tool name
            - "args" or "input": Tool arguments
            - "timestamp": Optional ISO timestamp
        tool_result_dict: Optional dictionary from tool_result event.
            Expected keys:
            - "result" or "output": Result text
            - "success" or "is_error": Success indicator
            - "duration_ms": Optional execution duration
        max_output_chars: Maximum characters to retain in output.

    Returns:
        NormalizedToolCall with source="cli-observed".

    Example:
        >>> with open("llm_events.jsonl") as f:
        ...     events = [json.loads(line) for line in f]
        >>> tool_use = events[0]  # {"type": "tool_use", "name": "Read", ...}
        >>> tool_result = events[1]  # {"type": "tool_result", ...}
        >>> tool_call = from_gemini_events(tool_use, tool_result)
    """
    # Extract tool name
    tool_name = tool_use_dict.get("name") or tool_use_dict.get("tool_name", "unknown")

    # Extract tool input
    tool_input = tool_use_dict.get("args") or tool_use_dict.get("input", {})
    if not isinstance(tool_input, dict):
        tool_input = {"value": tool_input} if tool_input else {}

    # Extract timestamp
    timestamp = tool_use_dict.get("timestamp")

    # Extract result from tool_result_dict if provided
    tool_output: Optional[str] = None
    success = True
    duration_ms = 0

    if tool_result_dict is not None:
        raw_result = tool_result_dict.get("result") or tool_result_dict.get("output")
        if raw_result is not None:
            tool_output = truncate_output(str(raw_result), max_output_chars)

        # Handle both "success" and "is_error" conventions
        if "success" in tool_result_dict:
            success = bool(tool_result_dict["success"])
        elif "is_error" in tool_result_dict:
            success = not bool(tool_result_dict["is_error"])

        duration_ms = tool_result_dict.get("duration_ms", 0)

    return NormalizedToolCall(
        tool_name=tool_name,
        tool_input=tool_input,
        tool_output=tool_output,
        success=success,
        duration_ms=duration_ms,
        source="cli-observed",
        timestamp=timestamp,
    )


def from_stub(
    tool_name: str,
    tool_input: Dict[str, Any],
    *,
    tool_output: Optional[str] = None,
    success: bool = True,
) -> NormalizedToolCall:
    """Create NormalizedToolCall for stub/mock execution.

    Use this factory when creating synthetic tool calls for:
    - Testing and development
    - Dry-run or simulation modes
    - Replaying recorded tool calls

    Args:
        tool_name: Name of the tool (e.g., "Read", "Write", "Bash").
        tool_input: Tool arguments dictionary.
        tool_output: Optional simulated output.
        success: Whether the simulated call succeeded.

    Returns:
        NormalizedToolCall with source="stub".

    Example:
        >>> # For testing receipt generation
        >>> tool_call = from_stub(
        ...     "Write",
        ...     {"file_path": "/tmp/test.txt", "content": "hello"},
        ...     tool_output="File written successfully",
        ... )
    """
    return NormalizedToolCall(
        tool_name=tool_name,
        tool_input=tool_input,
        tool_output=tool_output,
        success=success,
        duration_ms=0,
        source="stub",
    )


def from_kernel_execution(
    tool_name: str,
    tool_input: Dict[str, Any],
    tool_output: Optional[str] = None,
    success: bool = True,
    duration_ms: int = 0,
) -> NormalizedToolCall:
    """Create NormalizedToolCall for kernel-executed tools.

    Some tools may be executed directly by the orchestration kernel
    rather than by the LLM. This factory marks such calls appropriately.

    Args:
        tool_name: Name of the tool.
        tool_input: Tool arguments dictionary.
        tool_output: Result of the tool execution.
        success: Whether the execution succeeded.
        duration_ms: Execution duration in milliseconds.

    Returns:
        NormalizedToolCall with source="kernel-executed".
    """
    return NormalizedToolCall(
        tool_name=tool_name,
        tool_input=tool_input,
        tool_output=tool_output,
        success=success,
        duration_ms=duration_ms,
        source="kernel-executed",
    )
