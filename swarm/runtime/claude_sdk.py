"""
claude_sdk.py - Unified Claude SDK adapter with deterministic options.

This module is the ONLY place that imports the Claude Code SDK package(s).
It provides:
1. Clean imports with fallback handling
2. A single "options builder" that enforces High-Trust design
3. Helper functions for common SDK operations
4. StepSessionClient - Per-step session pattern with Work -> Finalize -> Route phases
5. Structured output schemas for HandoffEnvelope and RoutingSignal
6. NormalizedToolCall integration for unified tool call tracking

Usage:
    from swarm.runtime.claude_sdk import (
        SDK_AVAILABLE,
        create_high_trust_options,
        create_options_from_plan,
        query_with_options,
        get_sdk_module,
        StepSessionClient,  # Per-step session orchestrator (Work -> Finalize -> Route)
        HANDOFF_ENVELOPE_SCHEMA,
        ROUTING_SIGNAL_SCHEMA,
        _dict_to_normalized_tool_call,  # Backward compatibility helper
    )

Design Principles:
    - Single import point for SDK
    - Options always set: cwd, permission_mode, system_prompt preset
    - Explicit tool surface policy
    - Project-only settings by default
    - High-trust tool policy: broad access with foot-gun blocking
    - Per-step sessions: Work -> Finalize -> Route in single hot context
    - Normalized tool calls for consistent receipt format across transports
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
    AsyncIterator,
    Callable,
    Dict,
    List,
    Optional,
    Protocol,
    Tuple,
    Union,
)

if TYPE_CHECKING:
    from swarm.spec.types import PromptPlan

from swarm.runtime.types.tool_call import (
    NormalizedToolCall,
    truncate_output,
)

# Module logger
logger = logging.getLogger(__name__)

# =============================================================================
# Sandbox Configuration (NOT IMPLEMENTED)
# =============================================================================
# IMPORTANT: Sandbox enforcement is NOT currently implemented in the SDK.
# These settings are preserved for future SDK support, but currently only
# affect logging output. Commands have full host access regardless of settings.
#
# When the SDK adds sandbox support, we can enable actual enforcement.
# Until then, treat all execution as unsandboxed.

# Intentionally defaults to False to avoid false sense of safety
SANDBOX_ENABLED = os.environ.get("SWARM_SANDBOX_ENABLED", "false").lower() == "true"
ALLOW_UNSANDBOXED = os.environ.get("SWARM_ALLOW_UNSANDBOXED", "true").lower() == "true"

# Preserved for future SDK support
DEFAULT_SANDBOX_ALLOWED_COMMANDS = [
    "git",
    "npm",
    "npx",
    "pnpm",
    "uv",
    "pip",
    "pytest",
    "cargo",
    "rustc",
    "make",
    "python",
    "node",
]

# Warning flag to log sandbox status on first use
_SANDBOX_WARNING_LOGGED = False


# =============================================================================
# Hook Protocols for Guardrails and Telemetry
# =============================================================================


class PreToolUseHook(Protocol):
    """Protocol for hooks called before tool execution.

    PreToolUse hooks can:
    - Inspect the tool call before execution
    - Block the tool call by returning (False, reason)
    - Allow the tool call by returning (True, None)
    - Modify context (via side effects) for telemetry

    Example:
        >>> def my_pre_hook(tool_name, tool_input, context):
        ...     if tool_name == "Bash" and "rm -rf" in tool_input.get("command", ""):
        ...         return (False, "Dangerous command blocked")
        ...     context["tool_start_time"] = time.time()
        ...     return (True, None)
    """

    def __call__(
        self,
        tool_name: str,
        tool_input: Dict[str, Any],
        context: Dict[str, Any],
    ) -> Tuple[bool, Optional[str]]:
        """Called before tool execution.

        Args:
            tool_name: Name of the tool being called (e.g., "Bash", "Edit").
            tool_input: Input parameters for the tool.
            context: Mutable context dict for passing data to post-hook.

        Returns:
            Tuple of (allow, reason). If allow is False, tool is blocked with reason.
        """
        ...


class PostToolUseHook(Protocol):
    """Protocol for hooks called after tool execution.

    PostToolUse hooks can:
    - Inspect the tool result
    - Record metrics/telemetry
    - Log or audit tool usage

    Example:
        >>> def my_post_hook(tool_name, tool_input, result, context):
        ...     elapsed = time.time() - context.get("tool_start_time", 0)
        ...     logger.info(f"Tool {tool_name} completed in {elapsed:.2f}s")
    """

    def __call__(
        self,
        tool_name: str,
        tool_input: Dict[str, Any],
        result: Any,
        success: bool,
        context: Dict[str, Any],
    ) -> None:
        """Called after tool execution.

        Args:
            tool_name: Name of the tool that was called.
            tool_input: Input parameters that were passed.
            result: The tool result (may be truncated).
            success: Whether the tool execution succeeded.
            context: Context dict shared with pre-hook.
        """
        ...


@dataclass
class TelemetryData:
    """Telemetry data collected during a session phase.

    Attributes:
        phase: The phase name (work, finalize, route).
        start_time: When the phase started (ISO timestamp).
        end_time: When the phase ended (ISO timestamp).
        duration_ms: Total duration in milliseconds.
        tool_calls: Number of tool calls made.
        tool_timings: Dict of tool_name -> list of call durations (ms).
        prompt_tokens: Input tokens used.
        completion_tokens: Output tokens used.
        model: Model used for this phase.
        errors: List of errors encountered.
    """

    phase: str
    start_time: str
    end_time: str = ""
    duration_ms: int = 0
    tool_calls: int = 0
    tool_timings: Dict[str, List[float]] = field(default_factory=dict)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    model: str = ""
    errors: List[str] = field(default_factory=list)

    def record_tool_call(self, tool_name: str, duration_ms: float) -> None:
        """Record a tool call timing."""
        self.tool_calls += 1
        if tool_name not in self.tool_timings:
            self.tool_timings[tool_name] = []
        self.tool_timings[tool_name].append(duration_ms)

    def finalize(self, end_time: Optional[datetime] = None) -> None:
        """Finalize telemetry with end time and duration."""
        end = end_time or datetime.now(timezone.utc)
        self.end_time = end.isoformat() + "Z"
        # Parse start_time to calculate duration
        try:
            start_str = self.start_time.rstrip("Z")
            start = datetime.fromisoformat(start_str)
            # Make start timezone-aware if it isn't
            if start.tzinfo is None:
                start = start.replace(tzinfo=timezone.utc)
            self.duration_ms = int((end - start).total_seconds() * 1000)
        except (ValueError, TypeError):
            pass

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "phase": self.phase,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_ms": self.duration_ms,
            "tool_calls": self.tool_calls,
            "tool_timings": self.tool_timings,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "model": self.model,
            "errors": self.errors,
        }


# =============================================================================
# JSON Schema Definitions for output_format Structured Output
# =============================================================================

# JSON Schema for HandoffEnvelope structured output
HANDOFF_ENVELOPE_SCHEMA = {
    "type": "object",
    "properties": {
        "step_id": {"type": "string", "description": "The step identifier"},
        "flow_key": {
            "type": "string",
            "description": "The flow key (signal, plan, build, gate, deploy, wisdom)",
        },
        "run_id": {"type": "string", "description": "The run identifier"},
        "timestamp": {"type": "string", "description": "ISO 8601 timestamp"},
        "status": {
            "type": "string",
            "enum": ["VERIFIED", "UNVERIFIED", "PARTIAL", "BLOCKED"],
            "description": "Step completion status",
        },
        "summary": {
            "type": "string",
            "description": "2-paragraph summary of accomplishments and issues",
        },
        "artifacts": {
            "type": "object",
            "additionalProperties": {"type": "string"},
            "description": "Map of artifact names to relative file paths",
        },
        "confidence": {
            "type": "number",
            "minimum": 0.0,
            "maximum": 1.0,
            "description": "Confidence score 0.0 to 1.0",
        },
        "can_further_iteration_help": {
            "type": "string",
            "enum": ["yes", "no"],
            "description": "Whether another iteration could improve results",
        },
        "assumptions": {
            "type": "array",
            "items": {"type": "string"},
            "description": "List of assumptions made during the step",
        },
        "concerns": {
            "type": "array",
            "items": {"type": "string"},
            "description": "List of concerns or issues identified",
        },
    },
    "required": ["step_id", "flow_key", "run_id", "status", "summary"],
    "additionalProperties": True,
}

# JSON Schema for RoutingSignal structured output
ROUTING_SIGNAL_SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {
            "type": "string",
            "enum": ["advance", "loop", "terminate", "branch"],
            "description": "Routing decision type",
        },
        "next_step_id": {
            "type": ["string", "null"],
            "description": "The ID of the next step to execute, or null",
        },
        "route": {
            "type": ["string", "null"],
            "description": "The route name for branch decisions",
        },
        "reason": {
            "type": "string",
            "description": "Brief explanation for this routing decision",
        },
        "confidence": {
            "type": "number",
            "minimum": 0.0,
            "maximum": 1.0,
            "description": "Confidence in the routing decision",
        },
        "needs_human": {
            "type": "boolean",
            "description": "Whether human review is recommended",
        },
        "reasoning": {
            "type": "object",
            "properties": {
                "factors_considered": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "impact": {
                                "type": "string",
                                "enum": [
                                    "strongly_favors",
                                    "favors",
                                    "neutral",
                                    "against",
                                    "strongly_against",
                                ],
                            },
                            "evidence": {"type": "string"},
                            "weight": {"type": "number"},
                        },
                    },
                },
                "option_scores": {
                    "type": "object",
                    "additionalProperties": {"type": "number"},
                },
                "primary_justification": {"type": "string"},
                "risks_identified": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "risk": {"type": "string"},
                            "severity": {"type": "string", "enum": ["low", "medium", "high"]},
                            "mitigation": {"type": "string"},
                        },
                    },
                },
                "assumptions_made": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "description": "Detailed reasoning for the routing decision",
        },
    },
    "required": ["decision", "reason", "confidence"],
    "additionalProperties": True,
}


# =============================================================================
# SDK Availability Detection
# =============================================================================

SDK_AVAILABLE: bool = False
_sdk_module: Optional[Any] = None
_sdk_import_error: Optional[str] = None

try:
    import claude_code_sdk

    _sdk_module = claude_code_sdk
    SDK_AVAILABLE = True
    logger.debug("claude_code_sdk imported successfully")
except ImportError as e:
    _sdk_import_error = str(e)
    logger.debug("claude_code_sdk not available: %s", e)


def get_sdk_module() -> Any:
    """Get the Claude Code SDK module.

    Returns:
        The claude_code_sdk module.

    Raises:
        ImportError: If SDK is not available.
    """
    if not SDK_AVAILABLE:
        raise ImportError(
            f"Claude Code SDK is not available: {_sdk_import_error}. "
            "Install with: pip install claude-code-sdk"
        )
    return _sdk_module


def check_sdk_available() -> bool:
    """Check if the Claude Code SDK is available.

    Returns:
        True if SDK can be imported, False otherwise.
    """
    return SDK_AVAILABLE


# =============================================================================
# Options Builder
# =============================================================================

# Default model for step execution
DEFAULT_MODEL = "claude-sonnet-4-20250514"

# System prompt preset for Claude Code behavior
SYSTEM_PROMPT_PRESET = "claude_code"


def create_high_trust_options(
    cwd: Optional[Union[str, Path]] = None,
    permission_mode: str = "bypassPermissions",
    model: Optional[str] = None,
    system_prompt_append: Optional[str] = None,
    max_thinking_tokens: Optional[int] = None,
    max_turns: Optional[int] = None,
    sandboxed: Optional[bool] = None,
) -> Any:
    """Create ClaudeCodeOptions with High-Trust settings.

    This function enforces the design principles for agentic execution:
    - bypassPermissions mode for "hands-off" construction
    - Project-only settings (CLAUDE.md visibility)
    - System prompt preset for consistent Claude Code behavior
    - Explicit tool surface
    - Sandbox control for command containment

    MANDATORY SETTINGS (always enforced):
    - setting_sources=["project"]: Loads CLAUDE.md and .claude/skills
    - permission_mode: Controls file/command permissions
    - system_prompt preset: "claude_code" for consistent behavior

    SANDBOX BEHAVIOR:
    - If sandboxed is None, uses SWARM_SANDBOX_ENABLED env var (default True)
    - If sandboxed is False, requires SWARM_ALLOW_UNSANDBOXED=true
    - Sandbox limits command execution to a safe subset

    Args:
        cwd: Working directory for the SDK session (REQUIRED for reliable execution).
        permission_mode: Permission mode ("bypassPermissions" by default).
        model: Model override (uses DEFAULT_MODEL if not specified).
        system_prompt_append: Optional text to append to system prompt (persona, context).
        max_thinking_tokens: Optional max tokens for extended thinking.
        max_turns: Optional max conversation turns within this query (default: unlimited).
        sandboxed: Enable sandbox containment. None uses SWARM_SANDBOX_ENABLED env var.

    Returns:
        ClaudeCodeOptions instance configured for high-trust execution.

    Raises:
        ImportError: If SDK is not available.
    """
    sdk = get_sdk_module()

    # ALWAYS use system prompt preset for consistent Claude Code behavior
    # This ensures the agent behaves like Claude Code (tools, file ops, etc.)
    system_prompt: Dict[str, Any] = {
        "type": "preset",
        "preset": SYSTEM_PROMPT_PRESET,
    }
    if system_prompt_append:
        system_prompt["append"] = system_prompt_append

    # Build options dict with MANDATORY settings
    # CRITICAL: These settings are required for reliable agentic execution
    options_kwargs: Dict[str, Any] = {
        # 1. Permission mode: "bypassPermissions" for autonomous execution
        "permission_mode": permission_mode,
        # 2. Setting sources: ["project"] ensures CLAUDE.md and skills are loaded
        "setting_sources": ["project"],
        # 3. System prompt: preset for Claude Code behavior
        "system_prompt": system_prompt,
    }

    # Working directory (strongly recommended)
    if cwd:
        options_kwargs["cwd"] = str(cwd)
    else:
        logger.warning(
            "create_high_trust_options called without cwd - "
            "execution may fail or use unexpected working directory"
        )

    # Optional overrides
    if model:
        options_kwargs["model"] = model

    if max_thinking_tokens is not None:
        options_kwargs["max_thinking_tokens"] = max_thinking_tokens

    if max_turns is not None:
        options_kwargs["max_turns"] = max_turns

    # Handle sandbox configuration
    # NOTE: Sandbox enforcement is NOT currently implemented in the SDK.
    # This code path exists for future SDK support only.
    global _SANDBOX_WARNING_LOGGED

    if sandboxed is None:
        sandboxed = SANDBOX_ENABLED

    # Log honest sandbox status (once per process)
    if not _SANDBOX_WARNING_LOGGED:
        logger.info(
            "Sandbox status: NOT IMPLEMENTED. Commands have full host access. "
            "SWARM_SANDBOX_ENABLED=%s has no effect until SDK adds support.",
            SANDBOX_ENABLED,
        )
        _SANDBOX_WARNING_LOGGED = True

    # Preserved for future SDK support - currently no-op
    # When SDK adds sandboxSettings, uncomment this:
    # options_kwargs["sandboxSettings"] = {
    #     "enabled": sandboxed,
    #     "allowedCommands": DEFAULT_SANDBOX_ALLOWED_COMMANDS,
    # }

    return sdk.ClaudeCodeOptions(**options_kwargs)


def create_options_from_plan(
    plan: "PromptPlan",
    cwd: Optional[Union[str, Path]] = None,
) -> Any:
    """Create ClaudeCodeOptions from a compiled PromptPlan.

    This function maps spec-defined settings from a PromptPlan to SDK options,
    enabling the spec-first architecture where execution parameters are derived
    from machine-readable contracts rather than filesystem configuration.

    The PromptPlan contains all SDK configuration needed for execution:
    - model: The model to use (e.g., "sonnet", "opus")
    - permission_mode: Permission mode for the SDK session
    - allowed_tools: Tools available to the agent (informational in high-trust mode)
    - max_turns: Maximum conversation turns
    - sandbox_enabled: Sandbox configuration (prepared for future SDK support)
    - system_append: Text to append to the system prompt

    Args:
        plan: A compiled PromptPlan containing SDK configuration.
        cwd: Optional working directory override. If not specified, uses plan.cwd.

    Returns:
        ClaudeCodeOptions instance configured from the PromptPlan.

    Raises:
        RuntimeError: If the Claude SDK is not available.

    Example:
        >>> from swarm.spec.types import PromptPlan
        >>> plan = compile_prompt_plan(station, flow, step, ctx)
        >>> options = create_options_from_plan(plan)
        >>> async for event in sdk.query(prompt=plan.user_prompt, options=options):
        ...     process(event)
    """
    if not SDK_AVAILABLE:
        raise RuntimeError(
            f"Claude SDK not available: {_sdk_import_error}. "
            "Install with: pip install claude-code-sdk"
        )
    sdk = _sdk_module

    # Determine effective cwd - prefer explicit parameter, then plan.cwd
    effective_cwd: Optional[str] = None
    if cwd is not None:
        effective_cwd = str(cwd)
    elif plan.cwd:
        effective_cwd = plan.cwd

    # Build system prompt with preset and optional append
    system_prompt: Dict[str, Any] = {
        "type": "preset",
        "preset": SYSTEM_PROMPT_PRESET,
    }
    if plan.system_append:
        system_prompt["append"] = plan.system_append

    # Map permission mode from plan (with fallback)
    permission_mode = plan.permission_mode or "bypassPermissions"

    # Build options with MANDATORY settings from spec
    options_kwargs: Dict[str, Any] = {
        # 1. Permission mode from plan (or default)
        "permission_mode": permission_mode,
        # 2. Setting sources: ["project"] ensures CLAUDE.md and skills are loaded
        "setting_sources": ["project"],
        # 3. System prompt: preset + append from plan
        "system_prompt": system_prompt,
    }

    # Working directory
    if effective_cwd:
        options_kwargs["cwd"] = effective_cwd
    else:
        logger.warning(
            "create_options_from_plan called without cwd and plan.cwd is empty - "
            "execution may fail or use unexpected working directory"
        )

    # Model from plan (map short names to full model IDs if needed)
    if plan.model:
        # The plan.model may be a short name like "sonnet" or full ID
        # For now, pass through - the SDK handles model resolution
        options_kwargs["model"] = plan.model

    # Max turns from plan
    if plan.max_turns:
        options_kwargs["max_turns"] = plan.max_turns

    # NOTE: allowed_tools is informational in high-trust mode.
    # The agent has full toolbox access via bypassPermissions.
    # allowed_tools is preserved in the PromptPlan for:
    # 1. Documentation of intended tool surface
    # 2. Future SDK support for tool restrictions
    # 3. Audit/compliance logging
    #
    # For now, we log the intended tools but don't restrict.
    if plan.allowed_tools:
        logger.debug(
            "PromptPlan specifies allowed_tools=%s (informational only in high-trust mode)",
            plan.allowed_tools,
        )

    # NOTE: sandbox_enabled is prepared for future SDK support.
    # Currently no-op, same as create_high_trust_options().
    if plan.sandbox_enabled:
        logger.debug(
            "PromptPlan specifies sandbox_enabled=True (not enforced until SDK adds support)"
        )

    return sdk.ClaudeCodeOptions(**options_kwargs)


# =============================================================================
# Query Helpers
# =============================================================================


async def query_with_options(
    prompt: str,
    options: Any,
) -> AsyncIterator[Any]:
    """Execute a query with the provided options.

    This is a thin wrapper around sdk.query() that provides:
    - Consistent error handling
    - Logging
    - Type hints

    Args:
        prompt: The prompt to send to the SDK.
        options: ClaudeCodeOptions instance.

    Yields:
        SDK events from the query response.

    Raises:
        ImportError: If SDK is not available.
    """
    sdk = get_sdk_module()

    async for event in sdk.query(prompt=prompt, options=options):
        yield event


async def query_simple(
    prompt: str,
    cwd: Optional[Union[str, Path]] = None,
    permission_mode: str = "bypassPermissions",
) -> AsyncIterator[Any]:
    """Execute a simple query with default high-trust options.

    Convenience function for common use cases.

    Args:
        prompt: The prompt to send.
        cwd: Optional working directory.
        permission_mode: Permission mode (default: bypassPermissions).

    Yields:
        SDK events from the query response.
    """
    options = create_high_trust_options(
        cwd=cwd,
        permission_mode=permission_mode,
    )

    async for event in query_with_options(prompt, options):
        yield event


# =============================================================================
# Event Processing Helpers
# =============================================================================


def extract_text_from_event(event: Any) -> Optional[str]:
    """Extract text content from an SDK event.

    Handles different event types and content structures.

    Args:
        event: An SDK event object.

    Returns:
        Extracted text or None if no text content.
    """
    if not event:
        return None

    # Check for direct message attribute
    if hasattr(event, "message"):
        return str(event.message)

    # Check for content blocks
    if hasattr(event, "content"):
        content = event.content
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            texts = []
            for block in content:
                if hasattr(block, "text"):
                    texts.append(block.text)
                elif isinstance(block, dict) and "text" in block:
                    texts.append(block["text"])
            if texts:
                return "\n".join(texts)

    return None


def is_result_message(event: Any) -> bool:
    """Check if an event is a ResultMessage.

    Args:
        event: An SDK event object.

    Returns:
        True if event is a ResultMessage.
    """
    return type(event).__name__ == "ResultMessage"


def is_assistant_message(event: Any) -> bool:
    """Check if an event is an AssistantMessage.

    Args:
        event: An SDK event object.

    Returns:
        True if event is an AssistantMessage.
    """
    return type(event).__name__ == "AssistantMessage"


def is_tool_use(event: Any) -> bool:
    """Check if an event contains tool use.

    Args:
        event: An SDK event object.

    Returns:
        True if event contains tool use content.
    """
    if not hasattr(event, "content"):
        return False

    content = event.content
    if not isinstance(content, list):
        return False

    for block in content:
        if hasattr(block, "type") and block.type == "tool_use":
            return True
        if isinstance(block, dict) and block.get("type") == "tool_use":
            return True

    return False


def extract_usage_from_event(event: Any) -> Dict[str, int]:
    """Extract token usage from a ResultMessage event.

    Args:
        event: A ResultMessage event.

    Returns:
        Dict with prompt/completion/total token counts.
    """
    usage = {"prompt": 0, "completion": 0, "total": 0}

    if not hasattr(event, "total_cost_usd"):
        # Not a ResultMessage, try other attributes
        if hasattr(event, "usage"):
            raw = event.usage
            if hasattr(raw, "input_tokens"):
                usage["prompt"] = raw.input_tokens
            if hasattr(raw, "output_tokens"):
                usage["completion"] = raw.output_tokens
            usage["total"] = usage["prompt"] + usage["completion"]
        return usage

    # ResultMessage structure
    if hasattr(event, "total_input_tokens"):
        usage["prompt"] = event.total_input_tokens
    if hasattr(event, "total_output_tokens"):
        usage["completion"] = event.total_output_tokens
    usage["total"] = usage["prompt"] + usage["completion"]

    return usage


def extract_model_from_event(event: Any) -> Optional[str]:
    """Extract model name from an event.

    Args:
        event: An SDK event object.

    Returns:
        Model name string or None.
    """
    if hasattr(event, "model"):
        return event.model
    return None


# =============================================================================
# Structured Output Schemas (for output_format)
# =============================================================================

# JSON Schema for HandoffEnvelope structured output
HANDOFF_ENVELOPE_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "step_id": {
            "type": "string",
            "description": "The step ID that produced this envelope",
        },
        "flow_key": {
            "type": "string",
            "description": "The flow key (signal, plan, build, gate, deploy, wisdom)",
        },
        "run_id": {
            "type": "string",
            "description": "The run identifier",
        },
        "status": {
            "type": "string",
            "enum": ["VERIFIED", "UNVERIFIED", "PARTIAL", "BLOCKED"],
            "description": "Execution status: VERIFIED (complete), UNVERIFIED (tests fail or incomplete), PARTIAL (some work done but blocked), BLOCKED (cannot proceed)",
        },
        "summary": {
            "type": "string",
            "description": "2-paragraph summary of what was accomplished and any issues encountered (max 2000 chars)",
            "maxLength": 2000,
        },
        "artifacts": {
            "type": "object",
            "additionalProperties": {"type": "string"},
            "description": "Map of artifact names to relative paths from run base",
        },
        "file_changes": {
            "type": "object",
            "description": "Files created/modified/deleted during this step",
            "properties": {
                "created": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "modified": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "deleted": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
        },
        "proposed_next_step": {
            "type": ["string", "null"],
            "description": "The step_id that should execute next, or null if flow should terminate",
        },
        "notes_for_next_step": {
            "type": "string",
            "description": "Context the next agent should know",
        },
        "confidence": {
            "type": "number",
            "minimum": 0.0,
            "maximum": 1.0,
            "description": "Confidence in this handoff (1.0 = very confident)",
        },
        "can_further_iteration_help": {
            "type": "string",
            "enum": ["yes", "no"],
            "description": "For microloops: can another iteration improve the result?",
        },
        "timestamp": {
            "type": "string",
            "format": "date-time",
            "description": "ISO 8601 timestamp",
        },
    },
    "required": ["step_id", "flow_key", "run_id", "status", "summary", "confidence"],
}

# JSON Schema for RoutingSignal structured output
ROUTING_SIGNAL_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "decision": {
            "type": "string",
            "enum": ["advance", "loop", "terminate", "branch"],
            "description": "Routing decision: advance (next step), loop (back to target), terminate (end flow), branch (conditional route)",
        },
        "next_step_id": {
            "type": ["string", "null"],
            "description": "The step_id to execute next (for advance/loop/branch)",
        },
        "route": {
            "type": ["string", "null"],
            "description": "Named route identifier for branch routing",
        },
        "reason": {
            "type": "string",
            "description": "Human-readable explanation for this decision (max 300 chars)",
            "maxLength": 300,
        },
        "confidence": {
            "type": "number",
            "minimum": 0.0,
            "maximum": 1.0,
            "description": "Confidence in this routing decision",
        },
        "needs_human": {
            "type": "boolean",
            "description": "Whether human review is required before proceeding",
        },
        "factors_considered": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "maxLength": 50},
                    "impact": {
                        "type": "string",
                        "enum": [
                            "strongly_favors",
                            "favors",
                            "neutral",
                            "against",
                            "strongly_against",
                        ],
                    },
                    "evidence": {"type": "string", "maxLength": 100},
                    "weight": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                },
            },
            "description": "Factors considered in the routing decision",
        },
        "risks_identified": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "risk": {"type": "string", "maxLength": 100},
                    "severity": {"type": "string", "enum": ["low", "medium", "high"]},
                    "mitigation": {"type": "string", "maxLength": 100},
                },
            },
            "description": "Risks identified during routing analysis",
        },
    },
    "required": ["decision", "reason", "confidence", "needs_human"],
}


# =============================================================================
# High-Trust Tool Policy
# =============================================================================

# Blocked commands/patterns that are obvious foot-guns
# These are patterns that should NEVER be executed in agentic mode
BLOCKED_COMMAND_PATTERNS: List[str] = [
    # Destructive git operations
    r"git\s+push\s+.*--force",
    r"git\s+push\s+-f\b",
    r"git\s+reset\s+--hard",
    r"git\s+clean\s+-fd",
    r"git\s+checkout\s+--\s+\.",  # Discard all changes
    r"git\s+branch\s+-D",  # Force delete branch
    # Destructive file operations
    r"rm\s+-rf\s+/",
    r"rm\s+-rf\s+\*",
    r"rm\s+-rf\s+~",
    r"rm\s+-rf\s+\$HOME",
    r"del\s+/s\s+/q\s+[cC]:\\",  # Windows recursive delete
    r"rmdir\s+/s\s+/q\s+[cC]:\\",
    # Dangerous system commands
    r":(){ :|:& };:",  # Fork bomb
    r"chmod\s+-R\s+777\s+/",
    r"chown\s+-R\s+.*\s+/",
    # Environment destruction
    r"unset\s+PATH",
    r"export\s+PATH\s*=\s*$",
]

# Compiled patterns for efficiency
_BLOCKED_PATTERNS_COMPILED: List[re.Pattern[str]] = []


def _get_blocked_patterns() -> List[re.Pattern[str]]:
    """Get compiled blocked command patterns (lazy initialization)."""
    global _BLOCKED_PATTERNS_COMPILED
    if not _BLOCKED_PATTERNS_COMPILED:
        _BLOCKED_PATTERNS_COMPILED = [
            re.compile(pattern, re.IGNORECASE) for pattern in BLOCKED_COMMAND_PATTERNS
        ]
    return _BLOCKED_PATTERNS_COMPILED


def is_blocked_command(command: str) -> Tuple[bool, Optional[str]]:
    """Check if a command matches any blocked pattern.

    Args:
        command: The command string to check.

    Returns:
        Tuple of (is_blocked, matched_pattern) where matched_pattern is the
        pattern that matched if blocked, None otherwise.
    """
    for pattern in _get_blocked_patterns():
        if pattern.search(command):
            return True, pattern.pattern
    return False, None


def create_tool_policy_hook(
    allow_write: bool = True,
    allow_bash: bool = True,
    blocked_paths: Optional[List[str]] = None,
) -> Callable[[str, Dict[str, Any]], Tuple[bool, Optional[str]]]:
    """Create a tool policy hook for can_use_tool validation.

    This implements the high-trust tool policy:
    - Broad access by default (don't revert to tiny allowlists)
    - Block obvious foot-guns via pattern matching
    - Optionally restrict certain paths

    Args:
        allow_write: Whether to allow Write/Edit tools.
        allow_bash: Whether to allow Bash tool.
        blocked_paths: Optional list of path prefixes to block.

    Returns:
        A callable that takes (tool_name, tool_input) and returns
        (allow, reason) where allow is True if the tool use is permitted.

    Example:
        >>> hook = create_tool_policy_hook(blocked_paths=["/etc", "/usr"])
        >>> hook("Bash", {"command": "rm -rf /"})
        (False, 'Command matches blocked pattern: rm\\s+-rf\\s+/')
    """
    blocked_path_list = blocked_paths or []

    def tool_policy_hook(tool_name: str, tool_input: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """Tool policy hook for can_use_tool validation."""
        # Check tool-level permissions
        if tool_name in ("Write", "Edit") and not allow_write:
            return False, "Write operations not permitted in this context"

        if tool_name == "Bash" and not allow_bash:
            return False, "Bash commands not permitted in this context"

        # Check blocked command patterns for Bash
        if tool_name == "Bash":
            command = tool_input.get("command", "")
            is_blocked, pattern = is_blocked_command(command)
            if is_blocked:
                return False, f"Command matches blocked pattern: {pattern}"

        # Check blocked paths for file operations
        if tool_name in ("Read", "Write", "Edit", "Glob", "Grep"):
            file_path = tool_input.get("file_path") or tool_input.get("path", "")
            for blocked in blocked_path_list:
                if file_path.startswith(blocked):
                    return False, f"Path {file_path} is in blocked path: {blocked}"

        # Default: allow
        return True, None

    return tool_policy_hook


# =============================================================================
# Step Session Result Types
# =============================================================================


@dataclass
class WorkPhaseResult:
    """Result from the work phase of a step session.

    Attributes:
        success: Whether the work phase completed successfully.
        output: Concatenated assistant text output.
        events: List of raw SDK events captured during work.
        token_counts: Token usage statistics.
        model: Model name used.
        error: Error message if work phase failed.
        tool_calls: List of NormalizedToolCall instances made during work.
    """

    success: bool
    output: str
    events: List[Dict[str, Any]] = field(default_factory=list)
    token_counts: Dict[str, int] = field(
        default_factory=lambda: {"prompt": 0, "completion": 0, "total": 0}
    )
    model: str = "unknown"
    error: Optional[str] = None
    tool_calls: List[NormalizedToolCall] = field(default_factory=list)


@dataclass
class FinalizePhaseResult:
    """Result from the finalize phase of a step session.

    Attributes:
        envelope: Parsed handoff envelope data.
        raw_output: Raw structured output from SDK.
        success: Whether finalization succeeded.
        error: Error message if finalization failed.
    """

    envelope: Optional[Dict[str, Any]] = None
    raw_output: Optional[str] = None
    success: bool = False
    error: Optional[str] = None


@dataclass
class RoutePhaseResult:
    """Result from the route phase of a step session.

    Attributes:
        signal: Parsed routing signal data.
        raw_output: Raw structured output from SDK.
        success: Whether routing succeeded.
        error: Error message if routing failed.
    """

    signal: Optional[Dict[str, Any]] = None
    raw_output: Optional[str] = None
    success: bool = False
    error: Optional[str] = None


@dataclass
class StepSessionResult:
    """Combined result from all phases of a step session.

    Attributes:
        work: Result from work phase.
        finalize: Result from finalize phase (may be None if inline).
        route: Result from route phase (may be None if terminal).
        duration_ms: Total session duration in milliseconds.
        session_id: Unique session identifier.
        telemetry: Telemetry data for each phase.
    """

    work: WorkPhaseResult
    finalize: Optional[FinalizePhaseResult] = None
    route: Optional[RoutePhaseResult] = None
    duration_ms: int = 0
    session_id: str = ""
    telemetry: Dict[str, TelemetryData] = field(default_factory=dict)


# =============================================================================
# StepSessionClient - Per-Step Session Pattern
# =============================================================================


class StepSessionClient:
    """Client for per-step SDK sessions with Work -> Finalize -> Route pattern.

    This client implements the SDK alignment pattern where each step gets ONE
    session that handles all phases:
    1. Work phase: Agent does its task
    2. Finalize phase: Extract structured handoff envelope via output_format
    3. Route phase: Determine next step via output_format (if not terminal)

    Benefits:
    - Preserves hot context within a step (no context loss between phases)
    - Enables interrupts mid-step for observability
    - Uses structured output_format for reliable JSON extraction
    - Implements high-trust tool policy with foot-gun blocking
    - Supports PreToolUse/PostToolUse hooks for guardrails
    - Collects telemetry data for each phase

    Example:
        >>> client = StepSessionClient(repo_root=Path("/repo"))
        >>> async with client.step_session(ctx) as session:
        ...     work = await session.work(prompt="Implement feature X")
        ...     envelope = await session.finalize()
        ...     routing = await session.route()
        >>> result = session.get_result()
        >>> print(result.telemetry)
    """

    def __init__(
        self,
        repo_root: Optional[Path] = None,
        model: Optional[str] = None,
        tool_policy_hook: Optional[
            Callable[[str, Dict[str, Any]], Tuple[bool, Optional[str]]]
        ] = None,
        pre_tool_hooks: Optional[List[PreToolUseHook]] = None,
        post_tool_hooks: Optional[List[PostToolUseHook]] = None,
    ):
        """Initialize the Claude SDK client.

        Args:
            repo_root: Repository root for cwd setting.
            model: Model override (uses DEFAULT_MODEL if not specified).
            tool_policy_hook: Optional hook for tool policy validation (legacy).
            pre_tool_hooks: Optional list of pre-tool-use hooks for guardrails.
            post_tool_hooks: Optional list of post-tool-use hooks for telemetry.
        """
        self.repo_root = repo_root or Path.cwd()
        self.model = model or DEFAULT_MODEL
        self.tool_policy_hook = tool_policy_hook or create_tool_policy_hook()
        self.pre_tool_hooks: List[PreToolUseHook] = pre_tool_hooks or []
        self.post_tool_hooks: List[PostToolUseHook] = post_tool_hooks or []
        self._sdk_available: Optional[bool] = None

    def _check_sdk(self) -> bool:
        """Check and cache SDK availability."""
        if self._sdk_available is None:
            self._sdk_available = check_sdk_available()
        return self._sdk_available

    @asynccontextmanager
    async def step_session(
        self,
        step_id: str,
        flow_key: str,
        run_id: str,
        system_prompt_append: Optional[str] = None,
        is_terminal: bool = False,
    ):
        """Create a step session context manager.

        Each step gets ONE session that handles Work -> Finalize -> Route.
        The session preserves context between phases (hot context).

        Args:
            step_id: The step identifier.
            flow_key: The flow key (signal, plan, build, etc.).
            run_id: The run identifier.
            system_prompt_append: Optional persona/context to append to system prompt.
            is_terminal: Whether this is a terminal step (no routing needed).

        Yields:
            A StepSession instance for executing the step phases.
        """
        import secrets
        import string

        session_id = "".join(
            secrets.choice(string.ascii_lowercase + string.digits) for _ in range(8)
        )

        session = StepSession(
            client=self,
            step_id=step_id,
            flow_key=flow_key,
            run_id=run_id,
            session_id=session_id,
            system_prompt_append=system_prompt_append,
            is_terminal=is_terminal,
        )

        logger.debug(
            "Starting step session %s for step %s (flow=%s, run=%s, terminal=%s)",
            session_id,
            step_id,
            flow_key,
            run_id,
            is_terminal,
        )

        try:
            yield session
        finally:
            # Log session completion
            logger.debug(
                "Step session %s completed for step %s (work=%s, finalize=%s, route=%s)",
                session_id,
                step_id,
                session._work_completed,
                session._finalize_completed,
                session._route_completed,
            )


class StepSession:
    """A single step's execution session.

    Handles the Work -> Finalize -> Route pattern within a single hot context.
    Each phase builds on the previous phase's context.

    Supports:
    - PreToolUse/PostToolUse hooks for guardrails and telemetry
    - Structured output via output_format for finalize/route phases
    - Telemetry collection for each phase
    """

    def __init__(
        self,
        client: "StepSessionClient",
        step_id: str,
        flow_key: str,
        run_id: str,
        session_id: str,
        system_prompt_append: Optional[str] = None,
        is_terminal: bool = False,
    ):
        """Initialize the step session.

        Args:
            client: The parent StepSessionClient.
            step_id: The step identifier.
            flow_key: The flow key.
            run_id: The run identifier.
            session_id: Unique session identifier.
            system_prompt_append: Optional system prompt append.
            is_terminal: Whether this is a terminal step.
        """
        self.client = client
        self.step_id = step_id
        self.flow_key = flow_key
        self.run_id = run_id
        self.session_id = session_id
        self.system_prompt_append = system_prompt_append
        self.is_terminal = is_terminal

        # Phase completion tracking
        self._work_completed = False
        self._finalize_completed = False
        self._route_completed = False

        # Accumulated results
        self._work_result: Optional[WorkPhaseResult] = None
        self._finalize_result: Optional[FinalizePhaseResult] = None
        self._route_result: Optional[RoutePhaseResult] = None

        # Conversation state for hot context
        self._conversation_history: List[Dict[str, Any]] = []

        # Start time for duration tracking
        self._start_time = datetime.now(timezone.utc)

        # Telemetry data per phase
        self._telemetry: Dict[str, TelemetryData] = {}

        # Active tool context for hook communication
        self._tool_context: Dict[str, Any] = {}

    async def work(
        self,
        prompt: str,
        tools: Optional[List[str]] = None,
    ) -> WorkPhaseResult:
        """Execute the work phase of the step.

        The agent performs its primary task based on the prompt.
        Collects telemetry and invokes hooks for each tool call.

        Args:
            prompt: The step objective/prompt.
            tools: Optional list of tools to make available.

        Returns:
            WorkPhaseResult with output, events, and tool calls.
        """
        if self._work_completed:
            raise RuntimeError("Work phase already completed for this session")

        # Initialize telemetry for this phase
        telemetry = TelemetryData(
            phase="work",
            start_time=datetime.now(timezone.utc).isoformat() + "Z",
        )
        self._telemetry["work"] = telemetry

        if not self.client._check_sdk():
            self._work_result = WorkPhaseResult(
                success=False,
                output="",
                error="Claude SDK not available",
            )
            telemetry.errors.append("Claude SDK not available")
            telemetry.finalize()
            self._work_completed = True
            return self._work_result

        sdk = get_sdk_module()

        options = create_high_trust_options(
            cwd=str(self.client.repo_root),
            permission_mode="bypassPermissions",
            model=self.client.model,
            system_prompt_append=self.system_prompt_append,
        )

        events: List[Dict[str, Any]] = []
        full_text: List[str] = []
        tool_calls: List[NormalizedToolCall] = []
        token_counts: Dict[str, int] = {"prompt": 0, "completion": 0, "total": 0}
        model_name = self.client.model or "unknown"
        # Track pending tool calls: tool_use_id -> (NormalizedToolCall, context_dict)
        pending_tool_calls: Dict[str, Tuple[NormalizedToolCall, Dict[str, Any]]] = {}

        try:
            async for event in sdk.query(prompt=prompt, options=options):
                event_type = getattr(event, "type", None) or type(event).__name__
                now = datetime.now(timezone.utc)

                event_dict: Dict[str, Any] = {
                    "timestamp": now.isoformat() + "Z",
                    "phase": "work",
                    "type": event_type,
                }

                if event_type == "AssistantMessageEvent" or hasattr(event, "message"):
                    message = getattr(event, "message", event)
                    content = getattr(message, "content", "")
                    if isinstance(content, list):
                        text_parts = []
                        for block in content:
                            if hasattr(block, "text"):
                                text_parts.append(block.text)
                        content = "\n".join(text_parts)
                    if content:
                        full_text.append(content)
                    event_dict["content"] = content[:500] if content else ""

                elif event_type == "ToolUseEvent" or hasattr(event, "tool_name"):
                    tool_name = getattr(event, "tool_name", getattr(event, "name", "unknown"))
                    tool_input = getattr(event, "input", getattr(event, "args", {}))
                    if not isinstance(tool_input, dict):
                        tool_input = {"value": tool_input} if tool_input else {}
                    tool_use_id = getattr(
                        event, "id", getattr(event, "tool_use_id", str(time.time()))
                    )

                    # Initialize tool context for this call
                    tool_ctx: Dict[str, Any] = {
                        "tool_name": tool_name,
                        "tool_input": tool_input,
                        "tool_start_time": time.time(),
                        "step_id": self.step_id,
                        "session_id": self.session_id,
                    }

                    # Apply tool policy hook (legacy)
                    blocked = False
                    blocked_reason: Optional[str] = None
                    if self.client.tool_policy_hook and isinstance(tool_input, dict):
                        allowed, reason = self.client.tool_policy_hook(tool_name, tool_input)
                        if not allowed:
                            blocked = True
                            blocked_reason = reason
                            logger.warning(
                                "Tool use blocked by policy: %s - %s",
                                tool_name,
                                reason,
                            )
                            event_dict["blocked"] = True
                            event_dict["block_reason"] = reason

                    # Apply pre-tool-use hooks
                    if not blocked and isinstance(tool_input, dict):
                        for hook in self.client.pre_tool_hooks:
                            try:
                                allowed, reason = hook(tool_name, tool_input, tool_ctx)
                                if not allowed:
                                    blocked = True
                                    blocked_reason = reason
                                    logger.warning(
                                        "Tool use blocked by pre-hook: %s - %s",
                                        tool_name,
                                        reason,
                                    )
                                    event_dict["blocked"] = True
                                    event_dict["block_reason"] = reason
                                    break
                            except Exception as hook_err:
                                logger.debug("Pre-tool-use hook failed: %s", hook_err)

                    # Create NormalizedToolCall and store for later matching with result
                    tool_call = NormalizedToolCall(
                        tool_name=tool_name,
                        tool_input=tool_input,
                        source="sdk",
                        timestamp=now.isoformat() + "Z",
                        blocked=blocked,
                        blocked_reason=blocked_reason,
                    )
                    pending_tool_calls[tool_use_id] = (tool_call, tool_ctx)

                    event_dict["tool"] = tool_name

                elif event_type == "ToolResultEvent" or hasattr(event, "tool_result"):
                    tool_use_id = getattr(event, "tool_use_id", getattr(event, "id", None))
                    success = getattr(event, "success", True)
                    result = getattr(event, "tool_result", getattr(event, "result", ""))

                    event_dict["success"] = success

                    # Get pending tool call and context, then calculate duration
                    pending = pending_tool_calls.pop(tool_use_id, None)
                    if pending:
                        tool_call, tool_ctx = pending
                        start_time = tool_ctx.get("tool_start_time", 0)
                        duration_ms = int((time.time() - start_time) * 1000) if start_time else 0

                        # Update the NormalizedToolCall with result details
                        tool_call.tool_output = truncate_output(str(result), max_chars=2000)
                        tool_call.success = success
                        tool_call.duration_ms = duration_ms

                        # Add to completed tool calls list
                        tool_calls.append(tool_call)

                        tool_name = tool_call.tool_name
                        tool_input = tool_ctx.get("tool_input", {})
                    else:
                        tool_name = "unknown"
                        tool_input = {}
                        duration_ms = 0

                    # Record telemetry
                    telemetry.record_tool_call(tool_name, float(duration_ms))

                    # Apply post-tool-use hooks
                    if pending:
                        for hook in self.client.post_tool_hooks:
                            try:
                                hook(tool_name, tool_input, result, success, tool_ctx)
                            except Exception as hook_err:
                                logger.debug("Post-tool-use hook failed: %s", hook_err)

                elif event_type == "ResultEvent" or hasattr(event, "result"):
                    result = getattr(event, "result", event)
                    usage = getattr(result, "usage", None)
                    if usage:
                        token_counts["prompt"] = getattr(usage, "input_tokens", 0)
                        token_counts["completion"] = getattr(usage, "output_tokens", 0)
                        token_counts["total"] = token_counts["prompt"] + token_counts["completion"]
                        telemetry.prompt_tokens = token_counts["prompt"]
                        telemetry.completion_tokens = token_counts["completion"]
                    if hasattr(result, "model"):
                        model_name = result.model
                        telemetry.model = model_name

                events.append(event_dict)

            # Store conversation context for subsequent phases
            self._conversation_history.append(
                {
                    "role": "user",
                    "content": prompt,
                }
            )
            self._conversation_history.append(
                {
                    "role": "assistant",
                    "content": "".join(full_text),
                }
            )

            self._work_result = WorkPhaseResult(
                success=True,
                output="".join(full_text),
                events=events,
                token_counts=token_counts,
                model=model_name,
                tool_calls=tool_calls,
            )

        except Exception as e:
            logger.warning("Work phase failed for session %s: %s", self.session_id, e)
            telemetry.errors.append(str(e))
            self._work_result = WorkPhaseResult(
                success=False,
                output="",
                error=str(e),
                events=events,
            )

        telemetry.finalize()
        self._work_completed = True
        return self._work_result

    async def finalize(
        self,
        handoff_path: Optional[Path] = None,
    ) -> FinalizePhaseResult:
        """Execute the finalize phase to extract handoff envelope.

        Uses structured output_format for reliable JSON extraction when SDK supports it.
        Falls back to prompt-based extraction otherwise.

        This phase uses a follow-up turn in the same session to preserve hot context
        from the work phase, enabling the model to accurately summarize its work.

        Args:
            handoff_path: Optional path where agent should write handoff file.

        Returns:
            FinalizePhaseResult with parsed envelope data.
        """
        if not self._work_completed:
            raise RuntimeError("Work phase must complete before finalize")

        if self._finalize_completed:
            raise RuntimeError("Finalize phase already completed for this session")

        # Initialize telemetry for this phase
        telemetry = TelemetryData(
            phase="finalize",
            start_time=datetime.now(timezone.utc).isoformat() + "Z",
        )
        self._telemetry["finalize"] = telemetry

        if not self.client._check_sdk():
            self._finalize_result = FinalizePhaseResult(
                success=False,
                error="Claude SDK not available",
            )
            telemetry.errors.append("Claude SDK not available")
            telemetry.finalize()
            self._finalize_completed = True
            return self._finalize_result

        # Build finalization prompt
        work_summary = self._work_result.output[:4000] if self._work_result else ""

        finalization_prompt = f"""
Your work session is complete. Now create a structured handoff for the next step.

## Work Session Summary
{work_summary}

## Your Task
Analyze your work and produce a HandoffEnvelope JSON with:
- step_id: "{self.step_id}"
- flow_key: "{self.flow_key}"
- run_id: "{self.run_id}"
- status: VERIFIED (task complete), UNVERIFIED (incomplete), PARTIAL (blocked), or BLOCKED
- summary: 2-paragraph summary of accomplishments and issues
- artifacts: map of artifact names to relative paths
- confidence: 0.0 to 1.0
- can_further_iteration_help: "yes" or "no" (for microloops)

Output ONLY the JSON object, no markdown or explanation.
"""

        sdk = get_sdk_module()

        # Try to use output_format for structured output if SDK supports it
        # The SDK may support output_format as a parameter to query()
        # If not available, fall back to prompt-based extraction
        options_kwargs: Dict[str, Any] = {
            "cwd": str(self.client.repo_root),
            "permission_mode": "bypassPermissions",
            "setting_sources": ["project"],
            "system_prompt": {
                "type": "preset",
                "preset": "claude_code",
            },
        }

        if self.client.model:
            options_kwargs["model"] = self.client.model

        # Check if SDK supports output_format parameter
        sdk_has_output_format = hasattr(sdk, "ClaudeCodeOptions") and "output_format" in str(
            getattr(sdk.ClaudeCodeOptions, "__init__", lambda: None).__doc__ or ""
        )

        if sdk_has_output_format:
            # Use structured output format for reliable JSON extraction
            options_kwargs["output_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "HandoffEnvelope",
                    "schema": HANDOFF_ENVELOPE_SCHEMA,
                    "strict": True,
                },
            }
            logger.debug("Using output_format for finalize phase")

        try:
            options = sdk.ClaudeCodeOptions(**options_kwargs)
        except TypeError:
            # output_format not supported, use basic options
            logger.debug("output_format not supported, using prompt-based extraction")
            options = create_high_trust_options(
                cwd=str(self.client.repo_root),
                permission_mode="bypassPermissions",
                model=self.client.model,
            )

        try:
            response_text = ""
            async for event in sdk.query(prompt=finalization_prompt, options=options):
                if hasattr(event, "message"):
                    message = getattr(event, "message", event)
                    content = getattr(message, "content", "")
                    if isinstance(content, list):
                        for block in content:
                            if hasattr(block, "text"):
                                response_text += block.text
                    elif content:
                        response_text += content

                # Track token usage
                if hasattr(event, "result"):
                    result = getattr(event, "result", event)
                    usage = getattr(result, "usage", None)
                    if usage:
                        telemetry.prompt_tokens = getattr(usage, "input_tokens", 0)
                        telemetry.completion_tokens = getattr(usage, "output_tokens", 0)
                    if hasattr(result, "model"):
                        telemetry.model = result.model

            # Parse JSON from response
            envelope = self._parse_json_response(response_text)

            # Ensure required fields are present
            if envelope:
                envelope.setdefault("step_id", self.step_id)
                envelope.setdefault("flow_key", self.flow_key)
                envelope.setdefault("run_id", self.run_id)
                envelope.setdefault("timestamp", datetime.now(timezone.utc).isoformat() + "Z")

            self._finalize_result = FinalizePhaseResult(
                envelope=envelope,
                raw_output=response_text,
                success=envelope is not None,
                error=None if envelope else "Failed to parse envelope JSON",
            )

        except Exception as e:
            logger.warning("Finalize phase failed for session %s: %s", self.session_id, e)
            telemetry.errors.append(str(e))
            self._finalize_result = FinalizePhaseResult(
                success=False,
                error=str(e),
            )

        telemetry.finalize()
        self._finalize_completed = True
        return self._finalize_result

    async def route(
        self,
        routing_config: Optional[Dict[str, Any]] = None,
    ) -> RoutePhaseResult:
        """Execute the route phase to determine next step.

        Uses structured output_format for reliable JSON extraction when SDK supports it.
        Falls back to prompt-based extraction otherwise.

        This phase uses a follow-up turn in the same session to preserve hot context,
        enabling the model to make informed routing decisions based on its work.

        Args:
            routing_config: Optional routing configuration from flow spec.

        Returns:
            RoutePhaseResult with parsed routing signal.
        """
        if not self._work_completed:
            raise RuntimeError("Work phase must complete before route")

        if self._route_completed:
            raise RuntimeError("Route phase already completed for this session")

        # Initialize telemetry for this phase
        telemetry = TelemetryData(
            phase="route",
            start_time=datetime.now(timezone.utc).isoformat() + "Z",
        )
        self._telemetry["route"] = telemetry

        if self.is_terminal:
            # Terminal steps don't need routing
            self._route_result = RoutePhaseResult(
                signal={
                    "decision": "terminate",
                    "reason": "Terminal step",
                    "confidence": 1.0,
                    "needs_human": False,
                },
                success=True,
            )
            telemetry.finalize()
            self._route_completed = True
            return self._route_result

        if not self.client._check_sdk():
            self._route_result = RoutePhaseResult(
                success=False,
                error="Claude SDK not available",
            )
            telemetry.errors.append("Claude SDK not available")
            telemetry.finalize()
            self._route_completed = True
            return self._route_result

        # Build routing context
        handoff_summary = ""
        if self._finalize_result and self._finalize_result.envelope:
            handoff_summary = json.dumps(self._finalize_result.envelope, indent=2)
        elif self._work_result:
            handoff_summary = self._work_result.output[:2000]

        routing_prompt = f"""
Analyze the handoff and determine the next step.

## Handoff
```json
{handoff_summary}
```

## Routing Config
{json.dumps(routing_config or {}, indent=2)}

## Decision Logic
- If status is VERIFIED and work is complete: "advance" to next step
- If status is UNVERIFIED and can_further_iteration_help is "yes": "loop" back
- If status is UNVERIFIED and can_further_iteration_help is "no": "advance" (exit with concerns)
- If max iterations reached: "advance" (exit with documented concerns)
- If terminal condition: "terminate"

Output ONLY a JSON object with: decision, next_step_id, reason, confidence, needs_human
"""

        sdk = get_sdk_module()

        # Try to use output_format for structured output if SDK supports it
        options_kwargs: Dict[str, Any] = {
            "cwd": str(self.client.repo_root),
            "permission_mode": "bypassPermissions",
            "setting_sources": ["project"],
            "system_prompt": {
                "type": "preset",
                "preset": "claude_code",
            },
        }

        if self.client.model:
            options_kwargs["model"] = self.client.model

        # Check if SDK supports output_format parameter
        sdk_has_output_format = hasattr(sdk, "ClaudeCodeOptions") and "output_format" in str(
            getattr(sdk.ClaudeCodeOptions, "__init__", lambda: None).__doc__ or ""
        )

        if sdk_has_output_format:
            # Use structured output format for reliable JSON extraction
            options_kwargs["output_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "RoutingSignal",
                    "schema": ROUTING_SIGNAL_SCHEMA,
                    "strict": True,
                },
            }
            logger.debug("Using output_format for route phase")

        try:
            options = sdk.ClaudeCodeOptions(**options_kwargs)
        except TypeError:
            # output_format not supported, use basic options
            logger.debug("output_format not supported, using prompt-based extraction")
            options = create_high_trust_options(
                cwd=str(self.client.repo_root),
                permission_mode="bypassPermissions",
                model=self.client.model,
            )

        try:
            response_text = ""
            async for event in sdk.query(prompt=routing_prompt, options=options):
                if hasattr(event, "message"):
                    message = getattr(event, "message", event)
                    content = getattr(message, "content", "")
                    if isinstance(content, list):
                        for block in content:
                            if hasattr(block, "text"):
                                response_text += block.text
                    elif content:
                        response_text += content

                # Track token usage
                if hasattr(event, "result"):
                    result = getattr(event, "result", event)
                    usage = getattr(result, "usage", None)
                    if usage:
                        telemetry.prompt_tokens = getattr(usage, "input_tokens", 0)
                        telemetry.completion_tokens = getattr(usage, "output_tokens", 0)
                    if hasattr(result, "model"):
                        telemetry.model = result.model

            # Parse JSON from response
            signal = self._parse_json_response(response_text)

            # Ensure required fields are present with defaults
            if signal:
                signal.setdefault("confidence", 0.7)
                signal.setdefault("needs_human", False)

            self._route_result = RoutePhaseResult(
                signal=signal,
                raw_output=response_text,
                success=signal is not None,
                error=None if signal else "Failed to parse routing signal JSON",
            )

        except Exception as e:
            logger.warning("Route phase failed for session %s: %s", self.session_id, e)
            telemetry.errors.append(str(e))
            self._route_result = RoutePhaseResult(
                success=False,
                error=str(e),
            )

        telemetry.finalize()
        self._route_completed = True
        return self._route_result

    def get_result(self) -> StepSessionResult:
        """Get the combined result from all completed phases.

        Returns:
            StepSessionResult with all phase results, duration, and telemetry.
        """
        end_time = datetime.now(timezone.utc)
        duration_ms = int((end_time - self._start_time).total_seconds() * 1000)

        return StepSessionResult(
            work=self._work_result
            or WorkPhaseResult(success=False, output="", error="Work not completed"),
            finalize=self._finalize_result,
            route=self._route_result,
            duration_ms=duration_ms,
            session_id=self.session_id,
            telemetry=self._telemetry,
        )

    def _parse_json_response(self, response: str) -> Optional[Dict[str, Any]]:
        """Parse JSON from SDK response, handling markdown code blocks.

        Args:
            response: Raw response text that may contain JSON.

        Returns:
            Parsed JSON dict or None if parsing failed.
        """
        if not response:
            return None

        # Try to extract JSON from markdown code blocks
        json_text = response.strip()

        if "```json" in json_text:
            start = json_text.find("```json") + 7
            end = json_text.find("```", start)
            if end > start:
                json_text = json_text[start:end].strip()
        elif "```" in json_text:
            start = json_text.find("```") + 3
            end = json_text.find("```", start)
            if end > start:
                json_text = json_text[start:end].strip()

        # Try to parse
        try:
            return json.loads(json_text)
        except json.JSONDecodeError:
            # Try to find JSON object in the text
            brace_start = json_text.find("{")
            brace_end = json_text.rfind("}") + 1
            if brace_start >= 0 and brace_end > brace_start:
                try:
                    return json.loads(json_text[brace_start:brace_end])
                except json.JSONDecodeError:
                    pass

        logger.debug("Failed to parse JSON from response: %s", response[:200])
        return None


# =============================================================================
# Backward Compatibility Helpers
# =============================================================================


def _dict_to_normalized_tool_call(d: Dict[str, Any]) -> NormalizedToolCall:
    """Convert legacy dict format to NormalizedToolCall.

    This helper enables gradual migration from the old dict-based tool call
    tracking to the new NormalizedToolCall format. Use it when consuming
    tool calls from older code paths or external sources.

    Args:
        d: Dictionary with legacy tool call fields. Supports both old keys
           ("tool", "input", "output") and new keys ("tool_name", "tool_input",
           "tool_output").

    Returns:
        NormalizedToolCall instance with fields mapped from the dictionary.

    Example:
        >>> old_tool_call = {
        ...     "tool": "Bash",
        ...     "input": {"command": "ls -la"},
        ...     "output": "total 42...",
        ...     "timestamp": "2024-01-01T00:00:00Z",
        ... }
        >>> normalized = _dict_to_normalized_tool_call(old_tool_call)
        >>> normalized.tool_name
        'Bash'
    """
    return NormalizedToolCall(
        tool_name=d.get("tool", d.get("tool_name", "unknown")),
        tool_input=d.get("input", d.get("tool_input", {})),
        tool_output=d.get("output", d.get("tool_output")),
        success=d.get("success", True),
        duration_ms=d.get("duration_ms", 0),
        blocked=d.get("blocked", False),
        blocked_reason=d.get("blocked_reason"),
        source=d.get("source", "sdk"),
        timestamp=d.get("timestamp"),
    )


# =============================================================================
# Hook Factory Functions for Common Guardrails and Telemetry
# =============================================================================


def create_dangerous_command_hook(
    blocked_patterns: Optional[List[str]] = None,
) -> PreToolUseHook:
    """Create a pre-tool-use hook that blocks dangerous shell commands.

    This hook inspects Bash tool calls and blocks commands matching dangerous patterns.
    Used for safety guardrails in agentic execution.

    Args:
        blocked_patterns: List of regex patterns to block. Defaults to common dangerous
            commands like 'rm -rf', 'git push --force', etc.

    Returns:
        A PreToolUseHook that blocks dangerous commands.

    Example:
        >>> hook = create_dangerous_command_hook()
        >>> client = StepSessionClient(pre_tool_hooks=[hook])
    """
    if blocked_patterns is None:
        blocked_patterns = [
            r"rm\s+-rf\s+/",  # rm -rf / (root deletion)
            r"rm\s+-rf\s+\*",  # rm -rf * (wildcard deletion)
            r"git\s+push\s+.*--force",  # Force push
            r"git\s+reset\s+--hard",  # Hard reset
            r"chmod\s+-R\s+777",  # Overly permissive chmod
            r"sudo\s+rm",  # sudo rm commands
            r":(){ :|:& };:",  # Fork bomb
            r"mkfs\.",  # Filesystem formatting
            r"dd\s+if=/dev/zero",  # Disk overwrite
        ]

    compiled_patterns = [re.compile(p, re.IGNORECASE) for p in blocked_patterns]

    def hook(
        tool_name: str,
        tool_input: Dict[str, Any],
        context: Dict[str, Any],
    ) -> Tuple[bool, Optional[str]]:
        if tool_name != "Bash":
            return (True, None)

        command = tool_input.get("command", "")
        for pattern in compiled_patterns:
            if pattern.search(command):
                return (False, f"Dangerous command pattern blocked: {pattern.pattern}")

        return (True, None)

    return hook


def create_telemetry_hook() -> Tuple[PreToolUseHook, PostToolUseHook]:
    """Create pre/post hook pair for collecting tool execution telemetry.

    Returns:
        Tuple of (pre_hook, post_hook) for tool timing telemetry.

    Example:
        >>> pre_hook, post_hook = create_telemetry_hook()
        >>> client = StepSessionClient(
        ...     pre_tool_hooks=[pre_hook],
        ...     post_tool_hooks=[post_hook],
        ... )
    """

    def pre_hook(
        tool_name: str,
        tool_input: Dict[str, Any],
        context: Dict[str, Any],
    ) -> Tuple[bool, Optional[str]]:
        context["tool_start_time"] = time.time()
        context["tool_input"] = tool_input
        return (True, None)

    def post_hook(
        tool_name: str,
        tool_input: Dict[str, Any],
        result: Any,
        success: bool,
        context: Dict[str, Any],
    ) -> None:
        start_time = context.get("tool_start_time", 0)
        duration_ms = (time.time() - start_time) * 1000 if start_time else 0
        logger.debug(
            "Tool %s completed in %.2f ms (success=%s)",
            tool_name,
            duration_ms,
            success,
        )

    return pre_hook, post_hook


def create_file_access_audit_hook(
    audit_log: Optional[List[Dict[str, Any]]] = None,
) -> PostToolUseHook:
    """Create a post-tool-use hook that audits file access.

    Records all Read, Write, and Edit tool calls to an audit log.

    Args:
        audit_log: Optional list to append audit entries to. If None, logs to logger.

    Returns:
        A PostToolUseHook for file access auditing.

    Example:
        >>> audit_log = []
        >>> hook = create_file_access_audit_hook(audit_log)
        >>> client = StepSessionClient(post_tool_hooks=[hook])
        >>> # After execution:
        >>> for entry in audit_log:
        ...     print(f"{entry['tool']}: {entry['path']}")
    """

    def hook(
        tool_name: str,
        tool_input: Dict[str, Any],
        result: Any,
        success: bool,
        context: Dict[str, Any],
    ) -> None:
        if tool_name not in ("Read", "Write", "Edit"):
            return

        file_path = tool_input.get("file_path", tool_input.get("path", ""))
        entry = {
            "tool": tool_name,
            "path": file_path,
            "success": success,
            "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
            "session_id": context.get("session_id", ""),
            "step_id": context.get("step_id", ""),
        }

        if audit_log is not None:
            audit_log.append(entry)
        else:
            logger.info(
                "File access audit: %s %s (success=%s)",
                tool_name,
                file_path,
                success,
            )

    return hook


def create_token_budget_hook(
    max_prompt_tokens: int = 100000,
    max_completion_tokens: int = 50000,
    on_budget_exceeded: Optional[Callable[[str, int, int], None]] = None,
) -> PostToolUseHook:
    """Create a hook that tracks token budget consumption.

    Note: This hook tracks tokens at the tool result level. For full budget tracking,
    also monitor the ResultEvent token counts in each phase.

    Args:
        max_prompt_tokens: Maximum prompt tokens allowed.
        max_completion_tokens: Maximum completion tokens allowed.
        on_budget_exceeded: Optional callback when budget is exceeded.
            Called with (budget_type, current_value, max_value).

    Returns:
        A PostToolUseHook for token budget tracking.
    """
    token_counts = {"prompt": 0, "completion": 0}

    def hook(
        tool_name: str,
        tool_input: Dict[str, Any],
        result: Any,
        success: bool,
        context: Dict[str, Any],
    ) -> None:
        # Estimate tokens from tool result if available
        # This is a rough estimate; actual tokens come from ResultEvent
        if isinstance(result, str):
            estimated_tokens = len(result) // 4  # Rough char-to-token ratio
            token_counts["completion"] += estimated_tokens

            if token_counts["completion"] > max_completion_tokens:
                if on_budget_exceeded:
                    on_budget_exceeded(
                        "completion",
                        token_counts["completion"],
                        max_completion_tokens,
                    )
                else:
                    logger.warning(
                        "Token budget exceeded: completion=%d > max=%d",
                        token_counts["completion"],
                        max_completion_tokens,
                    )

    return hook


# =============================================================================
# Backward Compatibility Alias
# =============================================================================
# Preserve the old name for existing code that imports ClaudeSDKClient.
# New code should use StepSessionClient directly.
ClaudeSDKClient = StepSessionClient
