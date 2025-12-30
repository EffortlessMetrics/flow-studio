"""
engines/ - Step engine abstraction for pluggable LLM backends.

This package provides the step engine interface and implementations:

Interfaces:
- StepEngine: Base interface for all engines
- LifecycleCapableEngine: Extended interface with explicit lifecycle phases

Models:
- StepContext: Input context for step execution
- StepResult: Output from step execution
- RoutingContext: Microloop state and routing decisions
- HistoryTruncationInfo: Context budget tracking
- FinalizationResult: JIT finalization output

Engines:
- GeminiStepEngine: Executes steps via Gemini CLI
- ClaudeStepEngine: Executes steps via Claude SDK/CLI with lifecycle support

Factory:
- get_step_engine(): Create engine by ID
- list_available_engines(): List available engines with metadata

Usage:
    >>> from swarm.runtime.engines import get_step_engine, StepContext
    >>> engine = get_step_engine("claude-step", Path.cwd(), mode="sdk")
    >>> result, events = engine.run_step(ctx)
"""

from .base import LifecycleCapableEngine, StepEngine
from .claude import ClaudeStepEngine
from .factory import get_step_engine, list_available_engines
from .gemini import GeminiStepEngine
from .models import (
    FinalizationResult,
    HistoryTruncationInfo,
    RoutingContext,
    StepContext,
    StepResult,
)

__all__ = [
    # Interfaces
    "StepEngine",
    "LifecycleCapableEngine",
    # Models
    "StepContext",
    "StepResult",
    "RoutingContext",
    "HistoryTruncationInfo",
    "FinalizationResult",
    # Factory
    "get_step_engine",
    "list_available_engines",
    # Engines
    "GeminiStepEngine",
    "ClaudeStepEngine",
]
