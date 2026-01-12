"""
Transport ports for stepwise execution.

This module defines the abstract contract for step execution transports,
enabling different backends (Claude SDK, Claude CLI, Gemini CLI) to be
used interchangeably.

The key abstraction is:
- Transport: Creates step sessions for executing steps
- StepSession: Executes Work -> Finalize -> Route phases for a single step

Design Principles:
1. Transport is replaceable without changing kernel/orchestrator code
2. Result types are stable (WorkPhaseResult, FinalizePhaseResult, RoutePhaseResult)
3. Each transport declares its capabilities (interrupts, hooks, output_format support)
4. Transports can gracefully degrade when features aren't supported
"""

from .port import (
    CLAUDE_CLI_CAPABILITIES,
    CLAUDE_SDK_CAPABILITIES,
    GEMINI_CLI_CAPABILITIES,
    STUB_CAPABILITIES,
    StepSessionProtocol,
    TransportCapabilities,
    TransportProtocol,
)
from .claude_sdk_transport import (
    ClaudeSDKTransport,
    ClaudeSDKTransportSession,
    create_claude_sdk_transport,
)

__all__ = [
    # Protocols
    "TransportProtocol",
    "TransportCapabilities",
    "StepSessionProtocol",
    # Capability presets
    "CLAUDE_SDK_CAPABILITIES",
    "CLAUDE_CLI_CAPABILITIES",
    "GEMINI_CLI_CAPABILITIES",
    "STUB_CAPABILITIES",
    # Claude SDK transport
    "ClaudeSDKTransport",
    "ClaudeSDKTransportSession",
    "create_claude_sdk_transport",
]
