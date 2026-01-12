"""
port.py - Transport port interface for stepwise execution.

This module defines the abstract contract that all step execution transports
must implement. The contract is designed around the WP6 per-step session pattern:

1. Transport.open_session() - Create a session for a step
2. Session.work() - Execute the work phase
3. Session.finalize() - Extract structured handoff envelope
4. Session.route() - Determine next step routing

Transports can implement these with different backends:
- Claude Agent SDK (primary, full-featured)
- Claude CLI (debugging, fallback)
- Gemini CLI (alternative provider)
- Stub (testing, CI)

Each transport declares its capabilities so the orchestrator can adapt.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
    AsyncContextManager,
    Callable,
    Dict,
    List,
    Literal,
    Optional,
    Protocol,
    Tuple,
    runtime_checkable,
)

if TYPE_CHECKING:
    from swarm.runtime.claude_sdk import (
        FinalizePhaseResult,
        PostToolUseHook,
        PreToolUseHook,
        RoutePhaseResult,
        StepSessionResult,
        WorkPhaseResult,
    )


@dataclass
class TransportCapabilities:
    """Declares what features a transport supports.

    Used by the orchestrator to adapt its behavior based on transport features.
    Transports that don't support a feature should gracefully degrade.

    Attributes:
        supports_output_format: Whether transport supports structured JSON output
            via output_format parameter. If True, finalize/route can use schema
            validation instead of parsing from markdown fences.
        supports_interrupts: Whether transport supports mid-execution interrupts.
            If True, sessions can be interrupted and partial results recovered.
        supports_hooks: Whether transport supports pre/post tool hooks.
            If True, hooks can be registered for foot-gun blocking and telemetry.
        supports_hot_context: Whether transport preserves context across phases.
            If True, work/finalize/route share conversation state.
        supports_streaming: Whether transport supports event streaming.
            If True, events can be consumed as they arrive.
        supports_rewind: Whether transport supports rewinding to checkpoints.
            Reserved for future use.
        max_context_tokens: Maximum context window size (0 = unlimited/unknown).
        provider_name: Human-readable provider name for logging/receipts.

        supports_native_tools: Whether transport has Claude-style native tool calls.
            If True, the transport can invoke tools directly via the model's
            native tool-calling mechanism (function calls, tool_use blocks).
        supports_tool_observation: Whether we can observe tool calls happening.
            If True, tool invocations are visible in the event stream (e.g.,
            JSONL events for Gemini CLI, tool_use events for Claude SDK).
        supports_tool_interception: Whether we can block/modify tool calls.
            If True, pre-tool hooks can prevent or modify tool execution.
            Requires supports_hooks=True for hook registration.
        supports_project_context: Whether transport loads project context files.
            If True, transport automatically loads CLAUDE.md, settings.json,
            and similar project configuration into the model's context.
        structured_output_fallback: Strategy when output_format is unavailable.
            - "none": Transport has native structured output; no fallback needed.
            - "microloop": Use iterative prompting to extract structured output.
            - "best-effort": Parse JSON from markdown fences (may fail).
    """

    supports_output_format: bool = False
    supports_interrupts: bool = False
    supports_hooks: bool = False
    supports_hot_context: bool = True
    supports_streaming: bool = True
    supports_rewind: bool = False
    max_context_tokens: int = 0
    provider_name: str = "unknown"

    # Tooling model capabilities
    supports_native_tools: bool = False
    supports_tool_observation: bool = False
    supports_tool_interception: bool = False

    # Settings integration
    supports_project_context: bool = False

    # Structured output fallback strategy
    structured_output_fallback: Literal["none", "microloop", "best-effort"] = "none"


@runtime_checkable
class StepSessionProtocol(Protocol):
    """Protocol for a single step's execution session.

    A step session manages the execution of one step through its three phases:
    1. Work: Agent performs its task (tools enabled, streaming)
    2. Finalize: Extract structured handoff envelope (tools disabled, structured output)
    3. Route: Determine next step (tools disabled, structured output)

    The session preserves "hot context" between phases where supported,
    so the model remembers what it accomplished in the work phase when
    asked to formalize the handoff.

    Usage:
        async with transport.open_session(ctx) as session:
            work = await session.work(prompt="Implement feature X")
            envelope = await session.finalize()
            if not session.is_terminal:
                routing = await session.route()
            result = session.get_result()
    """

    @property
    def session_id(self) -> str:
        """Unique identifier for this session."""
        ...

    @property
    def is_terminal(self) -> bool:
        """Whether this is a terminal step (no routing needed)."""
        ...

    async def work(
        self,
        prompt: str,
        tools: Optional[List[str]] = None,
    ) -> "WorkPhaseResult":
        """Execute the work phase.

        Args:
            prompt: The work prompt for the agent.
            tools: Optional list of allowed tools (None = all tools).

        Returns:
            WorkPhaseResult with success, output, events, token_counts, etc.

        Raises:
            RuntimeError: If work phase already completed.
        """
        ...

    async def finalize(
        self,
        handoff_path: Optional[Path] = None,
    ) -> "FinalizePhaseResult":
        """Extract structured handoff envelope.

        This phase uses structured output (output_format) when available
        to ensure reliable JSON extraction.

        Args:
            handoff_path: Optional path hint for handoff storage.

        Returns:
            FinalizePhaseResult with parsed envelope dict.

        Raises:
            RuntimeError: If work phase not completed.
        """
        ...

    async def route(
        self,
        routing_config: Optional[Dict[str, Any]] = None,
    ) -> "RoutePhaseResult":
        """Determine next step routing.

        This phase uses structured output (output_format) when available
        to ensure reliable JSON extraction.

        For terminal steps, this returns immediately with TERMINATE decision.

        Args:
            routing_config: Optional routing configuration from step spec.

        Returns:
            RoutePhaseResult with parsed routing signal dict.

        Raises:
            RuntimeError: If work phase not completed.
        """
        ...

    def get_result(self) -> "StepSessionResult":
        """Get combined result from all phases.

        Returns:
            StepSessionResult combining work, finalize, route results
            with timing and telemetry data.
        """
        ...

    async def interrupt(self) -> None:
        """Interrupt the current phase execution.

        If the transport supports interrupts, this will:
        1. Stop the current phase gracefully
        2. Preserve partial results for recovery
        3. Mark the session as interrupted

        If the transport doesn't support interrupts, this is a no-op.
        """
        ...


@runtime_checkable
class TransportProtocol(Protocol):
    """Protocol for step execution transports.

    A transport is a factory for step sessions. It handles:
    - SDK/CLI initialization and configuration
    - Session creation with proper options
    - Capability declaration for orchestrator adaptation

    Transports are stateless factories - all state lives in sessions.

    Usage:
        transport = ClaudeSDKTransport(repo_root=Path("/repo"))
        print(transport.capabilities.supports_output_format)  # True

        async with transport.open_session(
            step_id="1",
            flow_key="build",
            run_id="run-123",
        ) as session:
            result = await session.work(prompt="...")
    """

    @property
    def capabilities(self) -> TransportCapabilities:
        """Declare transport capabilities.

        Returns:
            TransportCapabilities describing what this transport supports.
        """
        ...

    @property
    def is_available(self) -> bool:
        """Check if this transport is available for use.

        Returns:
            True if the transport can be used (SDK installed, CLI in PATH, etc.)
        """
        ...

    def open_session(
        self,
        step_id: str,
        flow_key: str,
        run_id: str,
        *,
        system_prompt_append: Optional[str] = None,
        is_terminal: bool = False,
        pre_tool_hooks: Optional[List["PreToolUseHook"]] = None,
        post_tool_hooks: Optional[List["PostToolUseHook"]] = None,
    ) -> AsyncContextManager["StepSessionProtocol"]:
        """Create a new step session.

        Args:
            step_id: The step identifier.
            flow_key: The flow key (signal, plan, build, etc.).
            run_id: The run identifier.
            system_prompt_append: Optional persona/context for system prompt.
            is_terminal: Whether this is a terminal step.
            pre_tool_hooks: Optional pre-tool-use hooks (if supported).
            post_tool_hooks: Optional post-tool-use hooks (if supported).

        Returns:
            Async context manager yielding a StepSessionProtocol instance.
        """
        ...


# =============================================================================
# Capability Presets for Common Transports
# =============================================================================

CLAUDE_SDK_CAPABILITIES = TransportCapabilities(
    supports_output_format=True,
    supports_interrupts=True,
    supports_hooks=True,
    supports_hot_context=True,
    supports_streaming=True,
    supports_rewind=False,
    max_context_tokens=200000,
    provider_name="claude-sdk",
    # Tooling model
    supports_native_tools=True,
    supports_tool_observation=True,
    supports_tool_interception=True,
    # Settings integration
    supports_project_context=True,
    # Structured output fallback
    structured_output_fallback="none",  # Has native support
)

CLAUDE_CLI_CAPABILITIES = TransportCapabilities(
    supports_output_format=False,  # CLI doesn't have output_format
    supports_interrupts=False,  # Subprocess can be killed but no graceful interrupt
    supports_hooks=False,  # No hook integration
    supports_hot_context=False,  # Each CLI call is stateless
    supports_streaming=True,  # stream-json output
    supports_rewind=False,
    max_context_tokens=200000,
    provider_name="claude-cli",
    # Tooling model
    supports_native_tools=False,
    supports_tool_observation=False,
    supports_tool_interception=False,
    # Settings integration
    supports_project_context=True,  # Reads CLAUDE.md and settings files
    # Structured output fallback
    structured_output_fallback="best-effort",
)

GEMINI_CLI_CAPABILITIES = TransportCapabilities(
    supports_output_format=False,  # Gemini CLI doesn't support this
    supports_interrupts=False,
    supports_hooks=False,
    supports_hot_context=False,
    supports_streaming=True,  # JSON streaming
    supports_rewind=False,
    max_context_tokens=1000000,  # Gemini has larger context
    provider_name="gemini-cli",
    # Tooling model
    supports_native_tools=False,
    supports_tool_observation=True,  # JSONL events expose tool calls
    supports_tool_interception=False,
    # Settings integration
    supports_project_context=False,
    # Structured output fallback
    structured_output_fallback="microloop",
)

STUB_CAPABILITIES = TransportCapabilities(
    supports_output_format=True,  # Stubs can simulate anything
    supports_interrupts=True,
    supports_hooks=True,
    supports_hot_context=True,
    supports_streaming=True,
    supports_rewind=False,
    max_context_tokens=0,  # Unlimited for stubs
    provider_name="stub",
    # Tooling model
    supports_native_tools=True,
    supports_tool_observation=True,
    supports_tool_interception=True,
    # Settings integration
    supports_project_context=True,
    # Structured output fallback
    structured_output_fallback="none",
)
