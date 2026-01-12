"""
Checkpoint & Resume Protocol

Every step leaves a checkpoint. Runs are resumable by default.

Checkpoint invariant: After each step completes:
1. Receipt written to disk
2. Artifacts persisted
3. Handoff envelope committed
4. State is resumable

Resume logic:
1. Find last completed checkpoint
2. If status == succeeded -> resume from next step
3. If status == failed -> retry failed step

This module implements the resume-protocol.md specification, providing:
- Checkpoint discovery from receipt files
- Resume point calculation
- Partial state detection
- Graceful interrupt handling
"""

from __future__ import annotations

import json
import logging
import os
import signal
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from swarm.runtime.path_helpers import (
    HANDOFF_DIR,
    LLM_DIR,
    RECEIPTS_DIR,
    handoff_envelope_path,
    list_receipts,
    parse_receipt_filename,
    receipt_path,
)

logger = logging.getLogger(__name__)


@dataclass
class Checkpoint:
    """A resumable checkpoint state.

    Represents a completed (or partially completed) step execution
    that can be used as a resume point.

    Attributes:
        step_id: The step identifier.
        flow_key: The flow this step belongs to.
        run_id: The run identifier.
        step_index: The numeric index of the step in the flow.
        status: The completion status (succeeded, failed, interrupted).
        receipt_path: Path to the receipt file.
        envelope_path: Optional path to the handoff envelope.
        completed_at: ISO timestamp of completion.
    """

    step_id: str
    flow_key: str
    run_id: str
    step_index: int
    status: str  # succeeded, failed, interrupted
    receipt_path: Path
    envelope_path: Optional[Path] = None
    completed_at: Optional[str] = None


@dataclass
class ResumePoint:
    """Where to resume execution.

    Contains all information needed to resume a flow from
    a specific point.

    Attributes:
        flow_key: The flow to resume.
        step_id: The step to resume from.
        step_index: The numeric index of the resume step.
        action: What to do: "continue", "retry", "start_fresh".
        reason: Human-readable explanation.
        last_checkpoint: The checkpoint used to determine resume point.
    """

    flow_key: str
    step_id: str
    step_index: int
    action: str  # "continue", "retry", "start_fresh"
    reason: str
    last_checkpoint: Optional[Checkpoint] = None


@dataclass
class PartialState:
    """State from a partially completed step.

    When a step fails mid-execution, some artifacts may have been
    written. This tracks what was preserved and recommends a recovery
    strategy.

    Attributes:
        artifacts_found: List of artifact paths that exist.
        partial_transcript: Path to partial transcript if it exists.
        uncommitted_changes: Whether there are uncommitted git changes.
        recovery_strategy: Recommended strategy for recovery.
    """

    artifacts_found: List[Path]
    partial_transcript: Optional[Path]
    uncommitted_changes: bool
    recovery_strategy: str  # "resume_with_partial", "retry_from_scratch", "escalate"


@dataclass
class InterruptState:
    """State captured during graceful shutdown.

    When a SIGINT/SIGTERM is received, we capture current state
    before exiting to enable clean resume.

    Attributes:
        interrupted_at: ISO timestamp of interruption.
        step_id: The step that was interrupted.
        flow_key: The flow that was running.
        partial_work: Description of partial work if any.
        artifacts_flushed: List of artifacts that were written before shutdown.
        can_resume_cleanly: Whether a clean resume is possible.
    """

    interrupted_at: str
    step_id: str
    flow_key: str
    partial_work: Optional[str]
    artifacts_flushed: List[str]
    can_resume_cleanly: bool


class CheckpointManager:
    """Manages checkpoints and resume logic.

    This class provides the core checkpoint/resume functionality:
    - Discovering checkpoints from receipts
    - Finding resume points for interrupted runs
    - Detecting partial state from failed steps
    - Creating new checkpoints

    The checkpoint invariant ensures that after each step:
    1. Receipt is written to disk
    2. Artifacts are persisted
    3. Handoff envelope is committed (if finalization occurred)
    4. State is resumable

    Usage:
        manager = CheckpointManager(run_base)
        resume_point = manager.find_resume_point("build")
        if resume_point.action == "continue":
            # Resume from next step
            pass
        elif resume_point.action == "retry":
            # Retry the failed step
            pass
    """

    def __init__(self, run_base: Path):
        """Initialize checkpoint manager.

        Args:
            run_base: The run base directory (e.g., swarm/runs/<run_id>).
        """
        self.run_base = Path(run_base)

    def list_checkpoints(self, flow_key: str) -> List[Checkpoint]:
        """List all checkpoints for a flow, sorted by step index.

        Scans the receipts directory for the given flow and builds
        Checkpoint objects from each receipt file.

        Args:
            flow_key: The flow key (e.g., "build", "signal").

        Returns:
            List of Checkpoint objects sorted by step_index.
        """
        flow_base = self.run_base / flow_key
        receipt_files = list_receipts(flow_base)

        checkpoints: List[Checkpoint] = []
        for r_path in receipt_files:
            checkpoint = self._load_checkpoint_from_receipt(r_path, flow_key)
            if checkpoint is not None:
                checkpoints.append(checkpoint)

        # Sort by step_index
        checkpoints.sort(key=lambda c: c.step_index)
        return checkpoints

    def get_last_checkpoint(self, flow_key: str) -> Optional[Checkpoint]:
        """Get the most recent checkpoint.

        Returns the checkpoint with the highest step_index for the flow.

        Args:
            flow_key: The flow key.

        Returns:
            The last Checkpoint, or None if no checkpoints exist.
        """
        checkpoints = self.list_checkpoints(flow_key)
        if not checkpoints:
            return None
        return checkpoints[-1]

    def find_resume_point(self, flow_key: str) -> ResumePoint:
        """Determine where to resume execution.

        Logic:
        1. Find last completed checkpoint
        2. If succeeded -> resume from step_index + 1 (CONTINUE)
        3. If failed -> retry same step (RETRY)
        4. If no checkpoints -> start from step 0 (START_FRESH)

        Args:
            flow_key: The flow key.

        Returns:
            ResumePoint indicating where and how to resume.
        """
        last_checkpoint = self.get_last_checkpoint(flow_key)

        if last_checkpoint is None:
            return ResumePoint(
                flow_key=flow_key,
                step_id="step-0",
                step_index=0,
                action="start_fresh",
                reason="No checkpoints found; starting from beginning",
                last_checkpoint=None,
            )

        if last_checkpoint.status == "succeeded":
            next_index = last_checkpoint.step_index + 1
            return ResumePoint(
                flow_key=flow_key,
                step_id=f"step-{next_index}",
                step_index=next_index,
                action="continue",
                reason=f"Last step '{last_checkpoint.step_id}' succeeded; advancing to next",
                last_checkpoint=last_checkpoint,
            )
        else:
            # Failed or interrupted - retry the same step
            return ResumePoint(
                flow_key=flow_key,
                step_id=last_checkpoint.step_id,
                step_index=last_checkpoint.step_index,
                action="retry",
                reason=f"Last step '{last_checkpoint.step_id}' {last_checkpoint.status}; retrying",
                last_checkpoint=last_checkpoint,
            )

    def check_partial_state(
        self, flow_key: str, step_id: str
    ) -> Optional[PartialState]:
        """Check for partial artifacts from an incomplete step.

        When a step fails mid-execution, some artifacts may have been
        written. This method detects:
        - Partial transcripts in llm/ directory
        - Any written artifacts
        - Uncommitted git changes

        Args:
            flow_key: The flow key.
            step_id: The step to check.

        Returns:
            PartialState if any partial artifacts found, None otherwise.
        """
        flow_base = self.run_base / flow_key
        artifacts_found: List[Path] = []
        partial_transcript: Optional[Path] = None

        # Check for partial transcript
        llm_dir = flow_base / LLM_DIR
        if llm_dir.exists():
            for entry in llm_dir.iterdir():
                if entry.is_file() and entry.name.startswith(f"{step_id}-"):
                    partial_transcript = entry
                    artifacts_found.append(entry)
                    break

        # Check for handoff envelope (even draft)
        handoff_path = handoff_envelope_path(flow_base, step_id)
        if handoff_path.exists():
            artifacts_found.append(handoff_path)

        # Check for draft handoff
        draft_path = handoff_path.with_suffix(".draft.json")
        if draft_path.exists():
            artifacts_found.append(draft_path)

        # Check for uncommitted git changes
        uncommitted_changes = self._check_uncommitted_changes()

        if not artifacts_found and not uncommitted_changes:
            return None

        # Determine recovery strategy
        if uncommitted_changes and not artifacts_found:
            # Git changes but no artifacts - might be partial work
            recovery_strategy = "retry_from_scratch"
        elif artifacts_found and not uncommitted_changes:
            # Artifacts exist, no git changes - can try to resume
            recovery_strategy = "resume_with_partial"
        elif artifacts_found and uncommitted_changes:
            # Both - complex state, may need human decision
            recovery_strategy = "escalate"
        else:
            recovery_strategy = "retry_from_scratch"

        return PartialState(
            artifacts_found=artifacts_found,
            partial_transcript=partial_transcript,
            uncommitted_changes=uncommitted_changes,
            recovery_strategy=recovery_strategy,
        )

    def create_checkpoint(
        self,
        receipt: Dict[str, Any],
        envelope: Optional[Dict[str, Any]] = None,
    ) -> Checkpoint:
        """Create a checkpoint from receipt and envelope.

        This is called after step completion to create a Checkpoint
        object from the step's receipt and optional handoff envelope.

        Args:
            receipt: The step receipt dict.
            envelope: Optional handoff envelope dict.

        Returns:
            Checkpoint object representing the completed step.
        """
        flow_key = receipt.get("flow_key", "")
        step_id = receipt.get("step_id", "")
        run_id = receipt.get("run_id", "")
        agent_key = receipt.get("agent_key", "")
        status = receipt.get("status", "unknown")
        completed_at = receipt.get("completed_at")

        # Extract step index from step_id if possible
        step_index = self._extract_step_index(step_id)

        # Construct receipt path
        flow_base = self.run_base / flow_key
        r_path = receipt_path(flow_base, step_id, agent_key)

        # Construct envelope path if envelope provided
        envelope_path: Optional[Path] = None
        if envelope is not None:
            envelope_path = handoff_envelope_path(flow_base, step_id)

        return Checkpoint(
            step_id=step_id,
            flow_key=flow_key,
            run_id=run_id,
            step_index=step_index,
            status=status,
            receipt_path=r_path,
            envelope_path=envelope_path,
            completed_at=completed_at,
        )

    def validate_checkpoint(self, checkpoint: Checkpoint) -> Tuple[bool, str]:
        """Validate that a checkpoint is complete and usable.

        A valid checkpoint requires:
        1. Receipt file exists
        2. Receipt is valid JSON with required fields
        3. If envelope_path is set, envelope file exists

        Args:
            checkpoint: The checkpoint to validate.

        Returns:
            Tuple of (is_valid, message).
        """
        # Check receipt exists
        if not checkpoint.receipt_path.exists():
            return False, f"Receipt file not found: {checkpoint.receipt_path}"

        # Check receipt is valid JSON
        try:
            with checkpoint.receipt_path.open() as f:
                receipt = json.load(f)
        except json.JSONDecodeError as e:
            return False, f"Receipt is not valid JSON: {e}"

        # Check required receipt fields
        required_fields = ["step_id", "flow_key", "status"]
        for field_name in required_fields:
            if field_name not in receipt:
                return False, f"Receipt missing required field: {field_name}"

        # Check envelope if path is set
        if checkpoint.envelope_path is not None:
            if not checkpoint.envelope_path.exists():
                return False, f"Envelope file not found: {checkpoint.envelope_path}"

            try:
                with checkpoint.envelope_path.open() as f:
                    json.load(f)
            except json.JSONDecodeError as e:
                return False, f"Envelope is not valid JSON: {e}"

        return True, "Checkpoint is valid"

    def _load_checkpoint_from_receipt(
        self, r_path: Path, flow_key: str
    ) -> Optional[Checkpoint]:
        """Load a Checkpoint from a receipt file.

        Args:
            r_path: Path to the receipt file.
            flow_key: The flow key.

        Returns:
            Checkpoint if receipt is valid, None otherwise.
        """
        try:
            with r_path.open() as f:
                receipt = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load receipt %s: %s", r_path, e)
            return None

        step_id = receipt.get("step_id", "")
        run_id = receipt.get("run_id", "")
        status = receipt.get("status", "unknown")
        completed_at = receipt.get("completed_at")

        step_index = self._extract_step_index(step_id)

        # Check for envelope
        flow_base = self.run_base / flow_key
        env_path = handoff_envelope_path(flow_base, step_id)
        envelope_path = env_path if env_path.exists() else None

        return Checkpoint(
            step_id=step_id,
            flow_key=flow_key,
            run_id=run_id,
            step_index=step_index,
            status=status,
            receipt_path=r_path,
            envelope_path=envelope_path,
            completed_at=completed_at,
        )

    def _extract_step_index(self, step_id: str) -> int:
        """Extract numeric step index from step_id.

        Handles various step_id formats:
        - "step-0" -> 0
        - "1" -> 1
        - "implement" -> 0 (fallback)

        Args:
            step_id: The step identifier.

        Returns:
            The numeric index, or 0 if not extractable.
        """
        # Try "step-N" format
        if step_id.startswith("step-"):
            try:
                return int(step_id[5:])
            except ValueError:
                pass

        # Try pure numeric
        try:
            return int(step_id)
        except ValueError:
            pass

        # Fallback - can't determine index
        return 0

    def _check_uncommitted_changes(self) -> bool:
        """Check if there are uncommitted git changes.

        Returns:
            True if uncommitted changes exist, False otherwise.
        """
        try:
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                capture_output=True,
                text=True,
                cwd=self.run_base,
                timeout=5,
            )
            # If there's any output, there are uncommitted changes
            return bool(result.stdout.strip())
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            # Can't determine - assume no changes
            return False


def find_resume_point(run_base: Path, flow_key: str) -> ResumePoint:
    """Main entry point for finding resume point.

    Convenience function that creates a CheckpointManager and
    finds the resume point for the given flow.

    Args:
        run_base: The run base directory.
        flow_key: The flow key.

    Returns:
        ResumePoint indicating where to resume.
    """
    manager = CheckpointManager(run_base)
    return manager.find_resume_point(flow_key)


def can_resume(run_base: Path, flow_key: str) -> bool:
    """Check if a run can be resumed.

    A run can be resumed if:
    1. At least one checkpoint exists
    2. The last checkpoint is valid

    Args:
        run_base: The run base directory.
        flow_key: The flow key.

    Returns:
        True if the run can be resumed.
    """
    manager = CheckpointManager(run_base)
    last_checkpoint = manager.get_last_checkpoint(flow_key)

    if last_checkpoint is None:
        return False

    is_valid, _ = manager.validate_checkpoint(last_checkpoint)
    return is_valid


def get_resume_context(run_base: Path, flow_key: str) -> Dict[str, Any]:
    """Get context needed to resume (last envelope, artifacts, etc.)

    Returns a dict with all context needed to resume execution:
    - resume_point: Where to resume
    - last_envelope: Contents of last handoff envelope
    - partial_state: Any partial artifacts found
    - checkpoints: List of all checkpoints

    Args:
        run_base: The run base directory.
        flow_key: The flow key.

    Returns:
        Dict with resume context.
    """
    manager = CheckpointManager(run_base)
    resume_point = manager.find_resume_point(flow_key)

    context: Dict[str, Any] = {
        "resume_point": {
            "step_id": resume_point.step_id,
            "step_index": resume_point.step_index,
            "action": resume_point.action,
            "reason": resume_point.reason,
        },
        "last_envelope": None,
        "partial_state": None,
        "checkpoints": [],
    }

    # Load last envelope if available
    if resume_point.last_checkpoint and resume_point.last_checkpoint.envelope_path:
        env_path = resume_point.last_checkpoint.envelope_path
        if env_path.exists():
            try:
                with env_path.open() as f:
                    context["last_envelope"] = json.load(f)
            except (json.JSONDecodeError, OSError):
                pass

    # Check for partial state if retrying
    if resume_point.action == "retry":
        partial = manager.check_partial_state(flow_key, resume_point.step_id)
        if partial:
            context["partial_state"] = {
                "artifacts_found": [str(p) for p in partial.artifacts_found],
                "partial_transcript": (
                    str(partial.partial_transcript) if partial.partial_transcript else None
                ),
                "uncommitted_changes": partial.uncommitted_changes,
                "recovery_strategy": partial.recovery_strategy,
            }

    # Include all checkpoints
    for cp in manager.list_checkpoints(flow_key):
        context["checkpoints"].append(
            {
                "step_id": cp.step_id,
                "step_index": cp.step_index,
                "status": cp.status,
                "completed_at": cp.completed_at,
            }
        )

    return context


# =============================================================================
# Graceful Shutdown Support
# =============================================================================


class InterruptHandler:
    """Handles graceful shutdown on SIGINT/SIGTERM.

    This class sets up signal handlers to capture interrupt state
    before exiting, enabling clean resume of interrupted runs.

    Usage:
        handler = InterruptHandler(run_base, flow_key, step_id)
        handler.install()
        try:
            # Do work
            pass
        finally:
            handler.uninstall()
    """

    def __init__(
        self,
        run_base: Path,
        flow_key: str,
        step_id: str,
        on_interrupt: Optional[Callable[[InterruptState], None]] = None,
    ):
        """Initialize interrupt handler.

        Args:
            run_base: The run base directory.
            flow_key: The current flow key.
            step_id: The current step ID.
            on_interrupt: Optional callback for custom interrupt handling.
        """
        self.run_base = Path(run_base)
        self.flow_key = flow_key
        self.step_id = step_id
        self.on_interrupt = on_interrupt
        self._original_sigint: Any = None
        self._original_sigterm: Any = None
        self._partial_work: Optional[str] = None
        self._artifacts_flushed: List[str] = []

    def set_partial_work(self, description: str) -> None:
        """Set description of current partial work.

        Called during execution to track what work is in progress.

        Args:
            description: Description of partial work.
        """
        self._partial_work = description

    def add_flushed_artifact(self, artifact_path: str) -> None:
        """Record an artifact that has been safely flushed to disk.

        Args:
            artifact_path: Path to the flushed artifact.
        """
        self._artifacts_flushed.append(artifact_path)

    def install(self) -> None:
        """Install signal handlers.

        Replaces SIGINT and SIGTERM handlers with our graceful
        shutdown handler.
        """
        self._original_sigint = signal.signal(signal.SIGINT, self._handle_signal)
        self._original_sigterm = signal.signal(signal.SIGTERM, self._handle_signal)

    def uninstall(self) -> None:
        """Restore original signal handlers."""
        if self._original_sigint is not None:
            signal.signal(signal.SIGINT, self._original_sigint)
        if self._original_sigterm is not None:
            signal.signal(signal.SIGTERM, self._original_sigterm)

    def _handle_signal(self, signum: int, frame: Any) -> None:
        """Handle SIGINT/SIGTERM by capturing state and exiting.

        Args:
            signum: The signal number.
            frame: The current stack frame.
        """
        logger.info("Received signal %d, initiating graceful shutdown", signum)

        # Determine if we can resume cleanly
        can_resume = len(self._artifacts_flushed) > 0 or self._partial_work is None

        state = InterruptState(
            interrupted_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            step_id=self.step_id,
            flow_key=self.flow_key,
            partial_work=self._partial_work,
            artifacts_flushed=self._artifacts_flushed,
            can_resume_cleanly=can_resume,
        )

        # Save interrupt state
        try:
            save_interrupt_state(state, self.run_base)
        except Exception as e:
            logger.error("Failed to save interrupt state: %s", e)

        # Call custom handler if provided
        if self.on_interrupt:
            try:
                self.on_interrupt(state)
            except Exception as e:
                logger.error("Error in interrupt callback: %s", e)

        # Exit with appropriate code
        # Use 130 for SIGINT (128 + 2), 143 for SIGTERM (128 + 15)
        exit_code = 128 + signum
        logger.info("Exiting with code %d after graceful shutdown", exit_code)
        os._exit(exit_code)


def capture_interrupt_state(
    run_base: Path, flow_key: str, step_id: str
) -> InterruptState:
    """Capture state during graceful shutdown (SIGINT/SIGTERM).

    This creates an InterruptState snapshot of the current execution
    state for later resume.

    Args:
        run_base: The run base directory.
        flow_key: The current flow key.
        step_id: The current step ID.

    Returns:
        InterruptState with current execution state.
    """
    flow_base = Path(run_base) / flow_key
    artifacts_flushed: List[str] = []

    # Check what artifacts exist
    receipts_dir = flow_base / RECEIPTS_DIR
    if receipts_dir.exists():
        for entry in receipts_dir.iterdir():
            if entry.is_file() and entry.name.endswith(".json"):
                artifacts_flushed.append(str(entry))

    llm_dir = flow_base / LLM_DIR
    if llm_dir.exists():
        for entry in llm_dir.iterdir():
            if entry.is_file():
                artifacts_flushed.append(str(entry))

    handoff_dir = flow_base / HANDOFF_DIR
    if handoff_dir.exists():
        for entry in handoff_dir.iterdir():
            if entry.is_file():
                artifacts_flushed.append(str(entry))

    # Determine if clean resume is possible
    can_resume = len(artifacts_flushed) > 0

    return InterruptState(
        interrupted_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        step_id=step_id,
        flow_key=flow_key,
        partial_work=None,
        artifacts_flushed=artifacts_flushed,
        can_resume_cleanly=can_resume,
    )


def save_interrupt_state(state: InterruptState, run_base: Path) -> Path:
    """Save interrupt state for later resume.

    Writes the interrupt state to a JSON file in the run base
    directory.

    Args:
        state: The interrupt state to save.
        run_base: The run base directory.

    Returns:
        Path to the saved interrupt state file.
    """
    run_base = Path(run_base)
    flow_base = run_base / state.flow_key

    # Ensure directory exists
    flow_base.mkdir(parents=True, exist_ok=True)

    # Write interrupt state
    interrupt_path = flow_base / "interrupt_state.json"
    interrupt_data = {
        "interrupted_at": state.interrupted_at,
        "step_id": state.step_id,
        "flow_key": state.flow_key,
        "partial_work": state.partial_work,
        "artifacts_flushed": state.artifacts_flushed,
        "can_resume_cleanly": state.can_resume_cleanly,
    }

    with interrupt_path.open("w", encoding="utf-8") as f:
        json.dump(interrupt_data, f, indent=2)

    logger.info("Saved interrupt state to %s", interrupt_path)
    return interrupt_path


def load_interrupt_state(run_base: Path, flow_key: str) -> Optional[InterruptState]:
    """Load saved interrupt state if it exists.

    Args:
        run_base: The run base directory.
        flow_key: The flow key.

    Returns:
        InterruptState if saved state exists, None otherwise.
    """
    interrupt_path = Path(run_base) / flow_key / "interrupt_state.json"

    if not interrupt_path.exists():
        return None

    try:
        with interrupt_path.open() as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to load interrupt state: %s", e)
        return None

    return InterruptState(
        interrupted_at=data.get("interrupted_at", ""),
        step_id=data.get("step_id", ""),
        flow_key=data.get("flow_key", ""),
        partial_work=data.get("partial_work"),
        artifacts_flushed=data.get("artifacts_flushed", []),
        can_resume_cleanly=data.get("can_resume_cleanly", False),
    )


def clear_interrupt_state(run_base: Path, flow_key: str) -> bool:
    """Clear saved interrupt state after successful resume.

    Args:
        run_base: The run base directory.
        flow_key: The flow key.

    Returns:
        True if state was cleared, False if it didn't exist.
    """
    interrupt_path = Path(run_base) / flow_key / "interrupt_state.json"

    if not interrupt_path.exists():
        return False

    try:
        interrupt_path.unlink()
        logger.info("Cleared interrupt state at %s", interrupt_path)
        return True
    except OSError as e:
        logger.warning("Failed to clear interrupt state: %s", e)
        return False


__all__ = [
    # Data classes
    "Checkpoint",
    "ResumePoint",
    "PartialState",
    "InterruptState",
    # Manager class
    "CheckpointManager",
    # Entry point functions
    "find_resume_point",
    "can_resume",
    "get_resume_context",
    # Interrupt handling
    "InterruptHandler",
    "capture_interrupt_state",
    "save_interrupt_state",
    "load_interrupt_state",
    "clear_interrupt_state",
]
