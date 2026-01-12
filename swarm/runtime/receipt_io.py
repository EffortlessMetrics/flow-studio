"""
receipt_io.py - Unified step receipt writing.

This module provides a single entry point for writing step receipts,
ensuring consistent schema across all execution paths (stub, sdk, cli)
and both execution modes (legacy, session).

Every step execution MUST write exactly one receipt at end-of-step.

The receipt contract:
- mode: "stub" | "sdk" | "cli"
- execution_mode: "legacy" | "session"
- execution_mode_requested: What was requested (for fallback tracking)
- execution_mode_effective: What actually ran
- fallback_reason: Why execution_mode differs (optional)
- engine: Engine identifier
- provider: Provider name
- model: Model used (or "unknown")
- step_id, flow_key, run_id, agent_key: Identifiers
- started_at, completed_at: ISO timestamps
- duration_ms: Execution duration
- status: "succeeded" | "failed"
- tokens: Token counts dict (prompt, completion, total)
- transcript_path: Relative path from run_base
- handoff_envelope_path: Relative path if envelope written (optional)
- routing_signal: Routing decision dict (optional)
- error: Error message (optional)
- context_truncation: Truncation info (optional)
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from swarm.runtime.path_helpers import ensure_receipts_dir, receipt_path

logger = logging.getLogger(__name__)


@dataclass
class StepReceiptData:
    """Data for a step receipt.

    All required fields must be provided. Optional fields can be None.
    """

    # Engine/mode info
    engine: str
    mode: str  # stub | sdk | cli
    execution_mode: str  # legacy | session
    provider: str

    # Identifiers
    step_id: str
    flow_key: str
    run_id: str
    agent_key: str

    # Timing
    started_at: datetime
    completed_at: datetime
    duration_ms: int

    # Status
    status: str  # succeeded | failed

    # Model/tokens
    model: str = "unknown"
    tokens: Dict[str, int] = field(
        default_factory=lambda: {"prompt": 0, "completion": 0, "total": 0}
    )

    # Paths
    transcript_path: Optional[str] = None
    handoff_envelope_path: Optional[str] = None

    # Routing
    routing_signal: Optional[Dict[str, Any]] = None

    # Fallback tracking
    execution_mode_requested: Optional[str] = None
    execution_mode_effective: Optional[str] = None
    fallback_reason: Optional[str] = None

    # Error/truncation
    error: Optional[str] = None
    context_truncation: Optional[Dict[str, Any]] = None

    # Additional data
    extra: Dict[str, Any] = field(default_factory=dict)

    # Audit trail fields (Wave 3: git_sha + workspace_root)
    git_sha: Optional[str] = None  # Git HEAD commit at step execution
    git_branch: Optional[str] = None  # Git branch at step execution
    workspace_root: Optional[str] = None  # Absolute path to workspace root

    # Tool calls (Wave 4: unified tool call capture)
    tool_calls: Optional[list] = None  # List of NormalizedToolCall dicts

    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dict."""
        result: Dict[str, Any] = {
            "engine": self.engine,
            "mode": self.mode,
            "execution_mode": self.execution_mode,
            "provider": self.provider,
            "model": self.model,
            "step_id": self.step_id,
            "flow_key": self.flow_key,
            "run_id": self.run_id,
            "agent_key": self.agent_key,
            "started_at": _format_iso(self.started_at),
            "completed_at": _format_iso(self.completed_at),
            "duration_ms": self.duration_ms,
            "status": self.status,
            "tokens": self.tokens,
        }

        # Add optional fields if present
        if self.transcript_path:
            result["transcript_path"] = self.transcript_path
        if self.handoff_envelope_path:
            result["handoff_envelope_path"] = self.handoff_envelope_path
        if self.routing_signal:
            result["routing_signal"] = self.routing_signal
        if self.execution_mode_requested:
            result["execution_mode_requested"] = self.execution_mode_requested
        if self.execution_mode_effective:
            result["execution_mode_effective"] = self.execution_mode_effective
        if self.fallback_reason:
            result["fallback_reason"] = self.fallback_reason
        if self.error:
            result["error"] = self.error
        if self.context_truncation:
            result["context_truncation"] = self.context_truncation

        # Audit trail fields (Wave 3)
        if self.git_sha:
            result["git_sha"] = self.git_sha
        if self.git_branch:
            result["git_branch"] = self.git_branch
        if self.workspace_root:
            result["workspace_root"] = self.workspace_root

        # Tool calls (Wave 4)
        if self.tool_calls:
            result["tool_calls"] = self.tool_calls

        # Merge extra data
        if self.extra:
            result.update(self.extra)

        return result


def _format_iso(dt: datetime) -> str:
    """Format datetime as ISO string with Z suffix."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")


def write_step_receipt(
    run_base: Path,
    receipt_data: StepReceiptData,
) -> Path:
    """Write a step receipt to the receipts directory.

    This is the single entry point for writing receipts. All execution
    paths (stub, sdk, cli) should use this function.

    Args:
        run_base: The run base directory (e.g., swarm/runs/<run_id>/<flow_key>).
        receipt_data: The receipt data to write.

    Returns:
        Path to the written receipt file.
    """
    ensure_receipts_dir(run_base)
    r_path = receipt_path(run_base, receipt_data.step_id, receipt_data.agent_key)

    receipt_dict = receipt_data.to_dict()

    with r_path.open("w", encoding="utf-8") as f:
        json.dump(receipt_dict, f, indent=2)

    logger.debug(
        "Wrote step receipt for %s/%s: %s",
        receipt_data.step_id,
        receipt_data.agent_key,
        r_path,
    )

    return r_path


def write_step_receipt_dict(
    run_base: Path,
    step_id: str,
    agent_key: str,
    receipt_dict: Dict[str, Any],
) -> Path:
    """Write a step receipt from a raw dict.

    This is a convenience function for callers that already have a dict.
    Prefer write_step_receipt() with StepReceiptData for type safety.

    Args:
        run_base: The run base directory.
        step_id: The step identifier.
        agent_key: The agent key.
        receipt_dict: The receipt data as a dict.

    Returns:
        Path to the written receipt file.
    """
    ensure_receipts_dir(run_base)
    r_path = receipt_path(run_base, step_id, agent_key)

    with r_path.open("w", encoding="utf-8") as f:
        json.dump(receipt_dict, f, indent=2)

    logger.debug(
        "Wrote step receipt (dict) for %s/%s: %s",
        step_id,
        agent_key,
        r_path,
    )

    return r_path


def make_receipt_data(
    *,
    engine: str,
    mode: str,
    execution_mode: str,
    provider: str,
    step_id: str,
    flow_key: str,
    run_id: str,
    agent_key: str,
    started_at: datetime,
    completed_at: datetime,
    duration_ms: int,
    status: str,
    model: str = "unknown",
    tokens: Optional[Dict[str, int]] = None,
    transcript_path: Optional[str] = None,
    handoff_envelope_path: Optional[str] = None,
    routing_signal: Optional[Dict[str, Any]] = None,
    execution_mode_requested: Optional[str] = None,
    execution_mode_effective: Optional[str] = None,
    fallback_reason: Optional[str] = None,
    error: Optional[str] = None,
    context_truncation: Optional[Dict[str, Any]] = None,
    # Audit trail fields (Wave 3)
    git_sha: Optional[str] = None,
    git_branch: Optional[str] = None,
    workspace_root: Optional[str] = None,
    # Tool calls (Wave 4)
    tool_calls: Optional[list] = None,
    **extra,
) -> StepReceiptData:
    """Factory function to create StepReceiptData with defaults.

    All keyword arguments are passed to StepReceiptData.
    Extra kwargs are placed in the extra dict.

    Returns:
        StepReceiptData instance.
    """
    return StepReceiptData(
        engine=engine,
        mode=mode,
        execution_mode=execution_mode,
        provider=provider,
        step_id=step_id,
        flow_key=flow_key,
        run_id=run_id,
        agent_key=agent_key,
        started_at=started_at,
        completed_at=completed_at,
        duration_ms=duration_ms,
        status=status,
        model=model,
        tokens=tokens or {"prompt": 0, "completion": 0, "total": 0},
        transcript_path=transcript_path,
        handoff_envelope_path=handoff_envelope_path,
        routing_signal=routing_signal,
        execution_mode_requested=execution_mode_requested,
        execution_mode_effective=execution_mode_effective,
        fallback_reason=fallback_reason,
        error=error,
        context_truncation=context_truncation,
        git_sha=git_sha,
        git_branch=git_branch,
        workspace_root=workspace_root,
        tool_calls=tool_calls,
        extra=extra,
    )


def capture_git_info(repo_root: Path) -> Dict[str, Optional[str]]:
    """Capture git SHA and branch at step execution time.

    This is a pure telemetry capture - it doesn't block on errors.
    If git info can't be captured, returns None values.

    Args:
        repo_root: Repository root path.

    Returns:
        Dict with 'git_sha' and 'git_branch' keys (may be None).
    """
    import subprocess

    result: Dict[str, Optional[str]] = {"git_sha": None, "git_branch": None}

    try:
        # Get current commit SHA
        sha_proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if sha_proc.returncode == 0:
            result["git_sha"] = sha_proc.stdout.strip()

        # Get current branch
        branch_proc = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if branch_proc.returncode == 0:
            result["git_branch"] = branch_proc.stdout.strip()

    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        logger.debug("Could not capture git info: %s", e)

    return result


__all__ = [
    "StepReceiptData",
    "write_step_receipt",
    "write_step_receipt_dict",
    "make_receipt_data",
    "capture_git_info",
]
