"""
models.py - Core model dataclasses for stepwise orchestration.

This module provides the core data models used by the stepwise orchestrator,
extracted for modularity and reuse. These dataclasses encapsulate execution
results, node resolution, and routing outcomes.

Types:
    FlowStepwiseSummary: Lightweight summary of a single flow's stepwise execution.
    FlowExecutionResult: Result of a single flow execution including macro routing.
    ResolvedNode: Resolved execution context for a node (regular or injected).
    RoutingOutcome: Unified return type for all routing strategies.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from swarm.runtime.types import (
    InjectedNodeSpec,
    MacroRoutingDecision,
    RunId,
    RunStatus,
    SDLCStatus,
)

if TYPE_CHECKING:
    from swarm.runtime.types import FlowResult, RoutingSignal

__all__ = [
    "FlowStepwiseSummary",
    "FlowExecutionResult",
    "ResolvedNode",
    "RoutingOutcome",
]


@dataclass
class FlowStepwiseSummary:
    """Lightweight summary of a single flow's stepwise execution.

    This is used internally by the orchestrator to capture essential
    execution metrics without requiring the full RunSummary structure.

    Attributes:
        run_id: The run identifier.
        status: The execution status.
        sdlc_status: The SDLC quality/health outcome.
        flow_key: The flow that was executed.
        completed_steps: List of step IDs that were completed.
        duration_ms: Total execution duration in milliseconds.
    """

    run_id: RunId
    status: RunStatus
    sdlc_status: SDLCStatus
    flow_key: str
    completed_steps: List[str]
    duration_ms: int


@dataclass
class FlowExecutionResult:
    """Result of a single flow execution including macro routing decision.

    Returned by run_stepwise_flow() when a MacroNavigator is provided,
    enabling callers to get routing guidance for the next flow.

    Attributes:
        run_id: The run identifier.
        summary: The FlowStepwiseSummary with execution details.
        macro_decision: Optional macro routing decision for next flow.
        flow_result: Optional structured flow result for routing context.
    """

    run_id: RunId
    summary: Optional["FlowStepwiseSummary"] = None
    macro_decision: Optional[MacroRoutingDecision] = None
    flow_result: Optional["FlowResult"] = None


@dataclass
class ResolvedNode:
    """Resolved execution context for a node.

    This is the unified representation for both regular flow nodes
    and dynamically injected nodes.

    Attributes:
        node_id: The node identifier.
        step_id: Step ID (same as node_id for compatibility).
        role: The role/station to execute.
        agents: List of agent keys to run.
        index: Position in flow (or -1 for injected nodes).
        is_injected: Whether this is a dynamically injected node.
        injected_spec: Full spec if this is an injected node.
        routing: Routing configuration if from flow definition.
    """

    node_id: str
    step_id: str
    role: str
    agents: Tuple[str, ...]
    index: int = -1
    is_injected: bool = False
    injected_spec: Optional[InjectedNodeSpec] = None
    routing: Optional[Any] = None  # StepRouting from flow_registry


@dataclass(frozen=True)
class RoutingOutcome:
    """Unified return type for all routing strategies.

    Every routing path (fast-path, deterministic, navigator, envelope fallback)
    returns this type. This ensures consistent audit trail coverage and makes
    the step loop readable.

    Attributes:
        next_step_id: The next step to execute, or None if flow is complete.
        reason: Human-readable explanation of the routing decision.
        routing_source: Which strategy made the decision (fast_path, deterministic_fallback, navigator, envelope).
        chosen_candidate_id: ID of the chosen routing candidate (for audit trail).
        candidate_set_path: Path to the full candidate set artifact file.
        routing_signal: Full RoutingSignal if available.
        candidates_summary: Lightweight summary of candidates (ids + priorities).
    """

    next_step_id: Optional[str]
    reason: str
    routing_source: str
    chosen_candidate_id: Optional[str] = None
    candidate_set_path: Optional[str] = None
    routing_signal: Optional["RoutingSignal"] = None
    candidates_summary: List[Dict[str, Any]] = field(default_factory=list)
