"""
base.py - Abstract base classes for step engines.

This module defines the interface contracts for step execution:
- StepEngine: Base interface for all engines
- LifecycleCapableEngine: Extended interface with explicit lifecycle phases

Engines implement these ABCs to provide pluggable LLM backends.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, Iterable, List, Optional, Tuple

from swarm.runtime.types import RoutingSignal, RunEvent

from .models import FinalizationResult, StepContext, StepResult


class StepEngine(ABC):
    """Abstract base class for step execution engines.

    Engines are responsible for:
    - Taking a StepContext with all necessary metadata
    - Executing the step using their underlying LLM/CLI
    - Returning a StepResult and stream of RunEvents

    Engines do NOT own:
    - Flow traversal (that's the orchestrator's job)
    - Run lifecycle management (that's the backend's job)
    - Event persistence (that's the caller's job)
    """

    @property
    @abstractmethod
    def engine_id(self) -> str:
        """Unique identifier for this engine (e.g., 'gemini-step', 'claude-step')."""
        ...

    @abstractmethod
    def run_step(self, ctx: StepContext) -> Tuple[StepResult, Iterable[RunEvent]]:
        """Execute a step and return result + events.

        Args:
            ctx: Step execution context including flow/step metadata and history.

        Returns:
            Tuple of (StepResult, iterable of RunEvents produced during execution).
            Events should be yielded in chronological order.
        """
        ...


class LifecycleCapableEngine(StepEngine):
    """Engine that supports explicit lifecycle phase control.

    Extends StepEngine with methods for orchestrator-controlled lifecycle:
    - run_worker(): Execute the work phase only
    - finalize_step(): JIT finalization to extract handoff state
    - route_step(): Determine next step via routing resolver

    The orchestrator can call these methods individually for fine-grained control,
    or use run_step() which calls all phases in sequence.
    """

    @abstractmethod
    def run_worker(self, ctx: StepContext) -> Tuple[StepResult, List[RunEvent], str]:
        """Execute the work phase only (no finalization or routing).

        The work phase:
        1. Builds the prompt from context
        2. Executes the LLM query
        3. Collects assistant output and events

        Args:
            ctx: Step execution context.

        Returns:
            Tuple of (StepResult, events, work_summary).
            work_summary is the raw assistant output for finalization.
        """
        ...

    @abstractmethod
    def finalize_step(
        self,
        ctx: StepContext,
        step_result: StepResult,
        work_summary: str,
    ) -> FinalizationResult:
        """Execute JIT finalization to extract handoff state.

        The finalization phase:
        1. Injects finalization prompt to the LLM session
        2. Agent writes handoff draft file
        3. Reads and parses the draft
        4. Creates structured HandoffEnvelope

        Args:
            ctx: Step execution context.
            step_result: Result from run_worker phase.
            work_summary: Raw assistant output from work phase.

        Returns:
            FinalizationResult with handoff data and envelope.
        """
        ...

    @abstractmethod
    def route_step(
        self,
        ctx: StepContext,
        handoff_data: Dict[str, Any],
    ) -> Optional[RoutingSignal]:
        """Determine next step via routing resolver.

        The routing phase:
        1. Checks deterministic termination conditions (microloop exit)
        2. If needed, runs lightweight LLM router session
        3. Parses routing decision into RoutingSignal

        Args:
            ctx: Step execution context with routing configuration.
            handoff_data: Parsed handoff data from finalization.

        Returns:
            RoutingSignal if routing was determined, None if routing failed.
        """
        ...
