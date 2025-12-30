"""
models.py - Data models for step engine abstraction.

This module defines the core data types used by step engines:
- StepContext: Input context for step execution
- StepResult: Output from step execution
- RoutingContext: Microloop state and routing decisions
- HistoryTruncationInfo: Context budget tracking
- FinalizationResult: JIT finalization output

These are pure data structures with no dependencies on engine implementations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from swarm.config.flow_registry import TeachingNotes
from swarm.runtime.types import HandoffEnvelope, RunEvent, RunSpec

if TYPE_CHECKING:
    pass  # Future type imports if needed


@dataclass
class RoutingContext:
    """Routing metadata for inclusion in receipts.

    Captures microloop state, routing decisions, and parallel execution context
    for observability.

    Attributes:
        loop_iteration: Current iteration count for the microloop (0-indexed).
        max_iterations: Maximum iterations allowed for the microloop.
        decision: Routing decision made ("loop", "advance", "terminate", "pending", "fork", "join").
        reason: Human-readable reason for the routing decision.
        kind: Routing kind ("linear", "microloop", "branch", "fork").
        next_step_id: Target step for advance/branch decisions.
        loop_target: Target step for loop decisions.
        parallel_context: Context for parallel execution (fork/join patterns).
    """

    loop_iteration: int = 0
    max_iterations: Optional[int] = None
    decision: str = "advance"  # "loop" | "advance" | "terminate" | "pending" | "fork" | "join"
    reason: str = ""
    kind: str = "linear"  # "linear" | "microloop" | "branch" | "fork"
    next_step_id: Optional[str] = None
    loop_target: Optional[str] = None
    parallel_context: Optional[Dict[str, Any]] = None


@dataclass
class StepContext:
    """Context provided to an engine for executing a single step.

    Contains all the information an engine needs to execute a step,
    including flow/step metadata, run specification, and history from
    previous steps for context building.

    Attributes:
        repo_root: Repository root path.
        run_id: The run identifier.
        flow_key: The flow being executed (signal, plan, build, etc.).
        step_id: The step identifier within the flow.
        step_index: 1-based step index within the flow.
        total_steps: Total number of steps in the flow.
        spec: The run specification.
        flow_title: Human-readable flow title.
        step_role: Description of what this step does.
        step_agents: Tuple of agent keys assigned to this step.
        history: List of previous step results for context.
        extra: Additional context-specific data.
        teaching_notes: Optional teaching notes for the step.
        routing: Optional routing context for microloop state.
    """

    repo_root: Path
    run_id: str
    flow_key: str
    step_id: str
    step_index: int
    total_steps: int
    spec: RunSpec
    flow_title: str
    step_role: str
    step_agents: Tuple[str, ...] = ()
    history: List[Dict[str, Any]] = field(default_factory=list)
    extra: Dict[str, Any] = field(default_factory=dict)
    teaching_notes: Optional[TeachingNotes] = None
    routing: Optional[RoutingContext] = None

    @property
    def run_base(self) -> Path:
        """Get the RUN_BASE path for this step's artifacts."""
        return Path(self.repo_root) / "swarm" / "runs" / self.run_id / self.flow_key


@dataclass
class HistoryTruncationInfo:
    """Metadata about history truncation during prompt building.

    Used to track and report when history is dropped due to budget constraints.
    This enables monitoring, debugging, and tuning of context budgets.

    Attributes:
        steps_included: Number of history steps included in the prompt.
        steps_total: Total number of history steps available.
        chars_used: Characters used for history.
        budget_chars: Total character budget allowed.
        truncated: Whether any steps were omitted.
        priority_aware: Whether priority-based selection was used.
        priority_distribution: Counts of included items by priority level.
    """

    steps_included: int
    steps_total: int
    chars_used: int
    budget_chars: int
    truncated: bool = False
    priority_aware: bool = True
    priority_distribution: Optional[Dict[str, int]] = None

    @property
    def truncation_note(self) -> str:
        """Generate a machine-readable truncation note.

        Returns:
            Empty string if no truncation, otherwise a formatted note.
        """
        if not self.truncated:
            return ""
        omitted = self.steps_total - self.steps_included
        note = (
            f"[CONTEXT_TRUNCATED] Included {self.steps_included} of "
            f"{self.steps_total} history steps ({omitted} omitted, "
            f"budget: {self.chars_used:,}/{self.budget_chars:,} chars)"
        )
        if self.priority_aware and self.priority_distribution:
            dist = self.priority_distribution
            note += (
                f" [Priority: CRITICAL={dist.get('CRITICAL', 0)}, "
                f"HIGH={dist.get('HIGH', 0)}, MEDIUM={dist.get('MEDIUM', 0)}, "
                f"LOW={dist.get('LOW', 0)}]"
            )
        return note

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict for JSON serialization in receipts."""
        result: Dict[str, Any] = {
            "steps_included": self.steps_included,
            "steps_total": self.steps_total,
            "chars_used": self.chars_used,
            "budget_chars": self.budget_chars,
            "truncated": self.truncated,
            "priority_aware": self.priority_aware,
        }
        if self.priority_distribution:
            result["priority_distribution"] = self.priority_distribution
        return result


@dataclass
class StepResult:
    """Result of executing a single step.

    Attributes:
        step_id: The step identifier.
        status: Execution status ("succeeded", "failed", "skipped").
        output: Summary text describing what happened.
        error: Error message if failed.
        duration_ms: Execution duration in milliseconds.
        artifacts: Optional dict of artifact paths/metadata produced.
    """

    step_id: str
    status: str  # "succeeded" | "failed" | "skipped"
    output: str
    error: Optional[str] = None
    duration_ms: int = 0
    artifacts: Optional[Dict[str, Any]] = None


@dataclass
class FinalizationResult:
    """Result from the finalization phase.

    Attributes:
        handoff_data: Raw handoff JSON from the agent's draft file (if available).
        envelope: Structured HandoffEnvelope (if successfully created).
        work_summary: Summary of the step's work output.
        events: Events emitted during finalization.
    """

    handoff_data: Optional[Dict[str, Any]] = None
    envelope: Optional[HandoffEnvelope] = None
    work_summary: str = ""
    events: List[RunEvent] = field(default_factory=list)
