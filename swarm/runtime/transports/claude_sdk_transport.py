"""
claude_sdk_transport.py - Claude Agent SDK transport adapter.

This module implements the TransportProtocol for the Claude Agent SDK,
wrapping the existing StepSessionClient to provide a stable interface.

This is the primary transport for Flow Studio, offering:
- Full output_format support for reliable JSON extraction
- Pre/Post tool hooks for foot-gun blocking and telemetry
- Hot context preservation across Work -> Finalize -> Route phases
- Interrupt capability for mid-step cancellation

Usage:
    from swarm.runtime.transports import ClaudeSDKTransport

    transport = ClaudeSDKTransport(repo_root=Path("/repo"))
    if transport.is_available:
        async with transport.open_session(
            step_id="1",
            flow_key="build",
            run_id="run-123",
        ) as session:
            work = await session.work(prompt="Implement feature X")
            envelope = await session.finalize()
            routing = await session.route()
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
    AsyncIterator,
    Dict,
    List,
    Optional,
)

from .port import (
    CLAUDE_SDK_CAPABILITIES,
    StepSessionProtocol,
    TransportCapabilities,
    TransportProtocol,
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

logger = logging.getLogger(__name__)


class ClaudeSDKTransportSession:
    """Claude SDK implementation of StepSessionProtocol.

    Wraps StepSession from claude_sdk.py to provide the stable transport interface.
    """

    def __init__(
        self,
        inner_session: Any,  # StepSession from claude_sdk.py
        is_terminal: bool = False,
    ):
        """Initialize the transport session.

        Args:
            inner_session: The underlying StepSession from claude_sdk.py.
            is_terminal: Whether this is a terminal step.
        """
        self._inner = inner_session
        self._is_terminal = is_terminal

    @property
    def session_id(self) -> str:
        """Unique identifier for this session."""
        return self._inner.session_id

    @property
    def is_terminal(self) -> bool:
        """Whether this is a terminal step (no routing needed)."""
        return self._is_terminal

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
        """
        return await self._inner.work(prompt=prompt, tools=tools)

    async def finalize(
        self,
        handoff_path: Optional[Path] = None,
    ) -> "FinalizePhaseResult":
        """Extract structured handoff envelope.

        Args:
            handoff_path: Optional path hint for handoff storage.

        Returns:
            FinalizePhaseResult with parsed envelope dict.
        """
        return await self._inner.finalize(handoff_path=handoff_path)

    async def route(
        self,
        routing_config: Optional[Dict[str, Any]] = None,
    ) -> "RoutePhaseResult":
        """Determine next step routing.

        Args:
            routing_config: Optional routing configuration from step spec.

        Returns:
            RoutePhaseResult with parsed routing signal dict.
        """
        return await self._inner.route(routing_config=routing_config)

    def get_result(self) -> "StepSessionResult":
        """Get combined result from all phases.

        Returns:
            StepSessionResult combining work, finalize, route results.
        """
        return self._inner.get_result()

    async def interrupt(self) -> None:
        """Interrupt the current phase execution.

        Note: The underlying StepSession doesn't have direct interrupt support,
        but this could be wired to SDK-level cancellation in the future.
        """
        # TODO: Wire to SDK cancellation when available
        logger.debug("Interrupt requested for session %s", self.session_id)


class ClaudeSDKTransport:
    """Claude Agent SDK transport implementation.

    This transport wraps the StepSessionClient to provide a stable interface
    for stepwise execution. It's the primary transport for Flow Studio.

    Capabilities:
    - output_format: True (uses JSON schemas for finalize/route)
    - interrupts: True (SDK supports async cancellation)
    - hooks: True (pre/post tool hooks for guardrails)
    - hot_context: True (preserves context across phases)
    - streaming: True (event streaming during work phase)
    """

    def __init__(
        self,
        repo_root: Optional[Path] = None,
        model: Optional[str] = None,
    ):
        """Initialize the Claude SDK transport.

        Args:
            repo_root: Repository root for cwd setting.
            model: Model override (uses DEFAULT_MODEL if not specified).
        """
        self._repo_root = repo_root or Path.cwd()
        self._model = model
        self._sdk_available: Optional[bool] = None

    @property
    def capabilities(self) -> TransportCapabilities:
        """Declare transport capabilities.

        Returns:
            TransportCapabilities for Claude SDK.
        """
        return CLAUDE_SDK_CAPABILITIES

    @property
    def is_available(self) -> bool:
        """Check if Claude SDK is available.

        Returns:
            True if claude_code_sdk is installed and importable.
        """
        if self._sdk_available is None:
            try:
                from swarm.runtime.claude_sdk import SDK_AVAILABLE

                self._sdk_available = SDK_AVAILABLE
            except ImportError:
                self._sdk_available = False
        return self._sdk_available

    @asynccontextmanager
    async def open_session(
        self,
        step_id: str,
        flow_key: str,
        run_id: str,
        *,
        system_prompt_append: Optional[str] = None,
        is_terminal: bool = False,
        pre_tool_hooks: Optional[List["PreToolUseHook"]] = None,
        post_tool_hooks: Optional[List["PostToolUseHook"]] = None,
    ) -> AsyncIterator[ClaudeSDKTransportSession]:
        """Create a new step session.

        Args:
            step_id: The step identifier.
            flow_key: The flow key (signal, plan, build, etc.).
            run_id: The run identifier.
            system_prompt_append: Optional persona/context for system prompt.
            is_terminal: Whether this is a terminal step.
            pre_tool_hooks: Optional pre-tool-use hooks.
            post_tool_hooks: Optional post-tool-use hooks.

        Yields:
            ClaudeSDKTransportSession wrapping the underlying StepSession.

        Raises:
            RuntimeError: If Claude SDK is not available.
        """
        if not self.is_available:
            raise RuntimeError(
                "Claude SDK transport not available. "
                "Install claude-code-sdk or use a different transport."
            )

        # Import here to avoid circular imports and allow graceful degradation
        from swarm.runtime.claude_sdk import (
            StepSessionClient,
            create_tool_policy_hook,
        )

        # Create the underlying client
        client = StepSessionClient(
            repo_root=self._repo_root,
            model=self._model,
            tool_policy_hook=create_tool_policy_hook(),
            pre_tool_hooks=pre_tool_hooks or [],
            post_tool_hooks=post_tool_hooks or [],
        )

        # Use the client's step_session context manager
        async with client.step_session(
            step_id=step_id,
            flow_key=flow_key,
            run_id=run_id,
            system_prompt_append=system_prompt_append,
            is_terminal=is_terminal,
        ) as inner_session:
            # Wrap in our transport session
            yield ClaudeSDKTransportSession(
                inner_session=inner_session,
                is_terminal=is_terminal,
            )


# =============================================================================
# Factory Function
# =============================================================================


def create_claude_sdk_transport(
    repo_root: Optional[Path] = None,
    model: Optional[str] = None,
) -> ClaudeSDKTransport:
    """Factory function to create Claude SDK transport.

    Args:
        repo_root: Repository root for cwd setting.
        model: Model override.

    Returns:
        Configured ClaudeSDKTransport instance.
    """
    return ClaudeSDKTransport(repo_root=repo_root, model=model)
