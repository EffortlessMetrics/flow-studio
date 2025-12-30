"""
types.py - Core types for stepwise orchestration.

This module provides the step transaction abstraction that encapsulates
all inputs and outputs for a single step execution. This enables:
- Clear contract between orchestrator and step execution
- Easier testing (mock inputs, assert outputs)
- Serialization for debugging and audit trails

Types:
    StepTxnInput: All inputs needed to execute a step
    StepTxnOutput: All outputs from step execution
    VerificationResult: Result of running verification checks
    VerificationCheck: Individual check result (artifact or command)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from swarm.config.flow_registry import FlowDefinition, StepDefinition
from swarm.runtime.types import (
    HandoffEnvelope,
    RoutingSignal,
    RunEvent,
    RunSpec,
    RunState,
)


@dataclass
class VerificationCheck:
    """Result of a single verification check.

    Attributes:
        check_type: "artifact" or "command"
        name: Artifact name or command string
        passed: Whether the check passed
        output: Output message or error details
    """

    check_type: str  # "artifact" | "command"
    name: str
    passed: bool
    output: str = ""


@dataclass
class VerificationResult:
    """Result of running all verification checks for a step.

    Attributes:
        passed: Overall pass/fail (all checks must pass)
        artifact_checks: List of artifact existence checks
        command_checks: List of command execution checks
        gate_status_on_fail: Status to set if verification fails
        events: Events emitted during verification
    """

    passed: bool = True
    artifact_checks: List[VerificationCheck] = field(default_factory=list)
    command_checks: List[VerificationCheck] = field(default_factory=list)
    gate_status_on_fail: str = "UNVERIFIED"
    events: List[RunEvent] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict for JSON serialization."""
        return {
            "passed": self.passed,
            "artifact_checks": [
                {"name": c.name, "passed": c.passed, "output": c.output}
                for c in self.artifact_checks
            ],
            "command_checks": [
                {"name": c.name, "passed": c.passed, "output": c.output}
                for c in self.command_checks
            ],
            "gate_status_on_fail": self.gate_status_on_fail,
        }


@dataclass
class StepTxnInput:
    """All inputs needed to execute a single step.

    This dataclass encapsulates the complete input context for step execution,
    enabling the orchestrator to prepare everything before invoking the engine.

    Attributes:
        repo_root: Repository root path.
        run_id: The run identifier.
        flow_key: The flow being executed (signal, plan, build, etc.).
        flow_def: The flow definition from registry.
        step: The step definition being executed.
        spec: The run specification.
        history: Previous step outputs for context building.
        run_state: Current run state (for resume, detours).
        routing_ctx: Optional routing context for microloop state.
    """

    repo_root: Path
    run_id: str
    flow_key: str
    flow_def: FlowDefinition
    step: StepDefinition
    spec: RunSpec
    history: List[Dict[str, Any]] = field(default_factory=list)
    run_state: Optional[RunState] = None
    routing_ctx: Optional["RoutingContext"] = None

    @property
    def run_base(self) -> Path:
        """Get the RUN_BASE path for this step's artifacts."""
        return self.repo_root / "swarm" / "runs" / self.run_id / self.flow_key

    @property
    def step_id(self) -> str:
        """Convenience accessor for step ID."""
        return self.step.id

    @property
    def step_index(self) -> int:
        """Convenience accessor for step index."""
        return self.step.index

    @property
    def total_steps(self) -> int:
        """Total steps in the flow."""
        return len(self.flow_def.steps)


@dataclass
class StepTxnOutput:
    """All outputs from a single step execution.

    This dataclass encapsulates everything produced by step execution,
    including the handoff envelope, routing decision, and events.

    Attributes:
        step_id: The step that was executed.
        status: Execution status ("succeeded", "failed", "skipped").
        output: Summary text describing what happened.
        error: Error message if failed.
        duration_ms: Execution duration in milliseconds.
        envelope: Structured handoff envelope from finalization.
        routing_signal: Routing decision for next step.
        verification: Verification result (if verification ran).
        events: All events emitted during step execution.
    """

    step_id: str
    status: str = "succeeded"  # "succeeded" | "failed" | "skipped"
    output: str = ""
    error: Optional[str] = None
    duration_ms: int = 0
    envelope: Optional[HandoffEnvelope] = None
    routing_signal: Optional[RoutingSignal] = None
    verification: Optional[VerificationResult] = None
    events: List[RunEvent] = field(default_factory=list)

    def to_history_entry(self) -> Dict[str, Any]:
        """Convert to a history entry for context building.

        Returns:
            Dict suitable for inclusion in step history.
        """
        entry: Dict[str, Any] = {
            "step_id": self.step_id,
            "status": self.status,
            "output": self.output,
            "duration_ms": self.duration_ms,
        }
        if self.error:
            entry["error"] = self.error
        if self.envelope:
            entry["summary"] = self.envelope.summary
            entry["artifacts"] = self.envelope.artifacts
        return entry


# Re-export RoutingContext from engines.models for convenience
from swarm.runtime.engines.models import RoutingContext

__all__ = [
    "VerificationCheck",
    "VerificationResult",
    "StepTxnInput",
    "StepTxnOutput",
    "RoutingContext",
]
