"""
engine_runner.py - Step execution with engine abstraction.

This module provides a clean interface for executing steps via different
engine types (lifecycle-capable vs single-phase). It encapsulates the
execution logic and produces a unified result type.

The engine runner:
1. Executes the step via the appropriate engine method
2. Captures progress evidence (file changes)
3. Tracks timing
4. Returns a unified result for the orchestrator

Usage:
    from swarm.runtime.stepwise.engine_runner import run_step, StepRunResult

    result = run_step(
        ctx=step_context,
        engine=engine,
        repo_root=repo_root,
    )
    # result.step_result, result.events, result.duration_ms, etc.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from swarm.runtime.diff_scanner import scan_file_changes_sync
from swarm.runtime.engines import StepContext, StepEngine
from swarm.runtime.engines.base import LifecycleCapableEngine
from swarm.runtime.types import RunEvent, RoutingSignal

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


@dataclass
class ProgressEvidence:
    """Evidence of progress captured after step execution.

    Used for stall detection and forensics.
    """

    file_count: int = 0
    line_count: int = 0
    files_summary: str = ""
    has_changes: bool = False
    files: List[Dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for event payloads."""
        return {
            "file_count": self.file_count,
            "line_count": self.line_count,
            "files_summary": self.files_summary,
            "has_changes": self.has_changes,
        }


@dataclass
class StepRunResult:
    """Result of step execution.

    Contains all outputs from running a step, including the step result,
    events, timing, and optional lifecycle-specific data.
    """

    # Core result
    step_result: Any

    # Events emitted during execution
    events: List[RunEvent] = field(default_factory=list)

    # Timing
    duration_ms: int = 0
    started_at: Optional[datetime] = None

    # Progress evidence for forensics/stall detection
    progress_evidence: Optional[ProgressEvidence] = None

    # Lifecycle-specific (only for LifecycleCapableEngine)
    handoff_data: Optional[Dict[str, Any]] = None
    routing_signal: Optional[RoutingSignal] = None

    # Execution mode
    is_lifecycle_execution: bool = False


def run_step(
    ctx: StepContext,
    engine: StepEngine,
    repo_root: Path,
    capture_progress: bool = True,
) -> StepRunResult:
    """Execute a step using the appropriate engine method.

    This function abstracts over different engine types:
    - LifecycleCapableEngine: Three-phase execution (work, finalize, route)
    - StepEngine: Single-phase execution

    Args:
        ctx: The step context with all execution parameters.
        engine: The engine to use for execution.
        repo_root: Repository root path for file change scanning.
        capture_progress: Whether to capture progress evidence (file changes).

    Returns:
        StepRunResult with step_result, events, timing, and optional lifecycle data.
    """
    step_start = time.monotonic()
    step_start_time = datetime.now(timezone.utc)

    progress_evidence: Optional[ProgressEvidence] = None
    handoff_data: Optional[Dict[str, Any]] = None
    routing_signal: Optional[RoutingSignal] = None
    is_lifecycle = False

    if isinstance(engine, LifecycleCapableEngine):
        is_lifecycle = True

        # Phase 1: Work (The Grind)
        step_result, work_events, work_summary = engine.run_worker(ctx)

        # Capture progress evidence after work, before finalize
        if capture_progress:
            progress_evidence = _capture_progress_evidence(repo_root)

        # Phase 2: Finalize (JIT extraction while context is hot)
        fin_result = engine.finalize_step(ctx, step_result, work_summary)

        # Phase 3: Route (fresh session for routing decision)
        handoff_data = fin_result.handoff_data or {}
        routing_signal = engine.route_step(ctx, handoff_data)

        # Combine events from work and finalization phases
        events = list(work_events) + fin_result.events
    else:
        # Fallback to single-phase execution for non-lifecycle engines
        step_result, events = engine.run_step(ctx)

        # Capture progress evidence after execution
        if capture_progress:
            progress_evidence = _capture_progress_evidence(repo_root)

    # Calculate step duration
    duration_ms = int((time.monotonic() - step_start) * 1000)
    step_result.duration_ms = duration_ms

    return StepRunResult(
        step_result=step_result,
        events=list(events),
        duration_ms=duration_ms,
        started_at=step_start_time,
        progress_evidence=progress_evidence,
        handoff_data=handoff_data,
        routing_signal=routing_signal,
        is_lifecycle_execution=is_lifecycle,
    )


def _capture_progress_evidence(repo_root: Path) -> ProgressEvidence:
    """Capture file change evidence for stall detection.

    Args:
        repo_root: Repository root path.

    Returns:
        ProgressEvidence with file change summary.
    """
    file_changes = scan_file_changes_sync(repo_root)
    return ProgressEvidence(
        file_count=file_changes.file_count,
        line_count=file_changes.total_insertions + file_changes.total_deletions,
        files_summary=file_changes.summary,
        has_changes=file_changes.has_changes,
        files=[
            {"path": f.path, "status": f.status}
            for f in file_changes.files[:20]  # Limit to 20 for payload size
        ],
    )


def emit_step_execution_events(
    run_id: str,
    flow_key: str,
    step_id: str,
    step_index: int,
    iteration: int,
    result: StepRunResult,
) -> List[RunEvent]:
    """Generate events for step execution.

    Creates the standard events emitted during step execution:
    - file_changes: Progress evidence for forensics
    - lifecycle_phases_completed: For lifecycle engines
    - step_timing: Duration and timing info

    Args:
        run_id: The run identifier.
        flow_key: The flow key.
        step_id: The step identifier.
        step_index: Step index in the flow.
        iteration: Current iteration count.
        result: The StepRunResult from run_step().

    Returns:
        List of RunEvent to be persisted.
    """
    events: List[RunEvent] = []
    now = datetime.now(timezone.utc)

    # File changes event (for forensics)
    if result.progress_evidence is not None:
        events.append(
            RunEvent(
                run_id=run_id,
                ts=now,
                kind="file_changes",
                flow_key=flow_key,
                step_id=step_id,
                payload={
                    "progress_evidence": result.progress_evidence.to_dict(),
                    "files": result.progress_evidence.files,
                },
            )
        )

    # Lifecycle phases event (for lifecycle engines)
    if result.is_lifecycle_execution:
        events.append(
            RunEvent(
                run_id=run_id,
                ts=now,
                kind="lifecycle_phases_completed",
                flow_key=flow_key,
                step_id=step_id,
                payload={
                    "phases": ["work", "finalize", "route"],
                    "has_routing_signal": result.routing_signal is not None,
                    "has_handoff_data": bool(result.handoff_data),
                },
            )
        )

    # Step timing event
    events.append(
        RunEvent(
            run_id=run_id,
            ts=now,
            kind="step_timing",
            flow_key=flow_key,
            step_id=step_id,
            payload={
                "duration_ms": result.duration_ms,
                "started_at": result.started_at.isoformat() if result.started_at else None,
                "step_index": step_index,
                "iteration": iteration,
            },
        )
    )

    return events


__all__ = [
    "ProgressEvidence",
    "StepRunResult",
    "run_step",
    "emit_step_execution_events",
]
