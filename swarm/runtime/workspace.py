"""
workspace.py - Workspace abstraction for step execution isolation.

This module provides a single abstraction for "where does this step execute?"
that supports both real repo operations and shadow fork isolation.

Design Philosophy:
    - Steps always use `workspace.root()` to determine working directory
    - The orchestrator decides which Workspace implementation to use
    - Shadow mode is the default for speculative flows (Build/Review/Gate)
    - Real mode is used for Deploy (which actually merges)
    - Boundary enforcement detects escapes from workspace scope

The Workspace abstraction enables:
    - SIGKILL safety: shadow work can be discarded without corruption
    - Boundary enforcement: detect writes outside workspace scope
    - Promotion semantics: explicit bridge from shadow to real
    - Forensics: diff, status, and audit trail

Usage:
    from swarm.runtime.workspace import (
        Workspace,
        RealWorkspace,
        ShadowForkWorkspace,
        create_workspace,
    )

    # Create workspace based on flow context
    workspace = create_workspace(
        repo_root=repo_root,
        run_id=run_id,
        flow_key=flow_key,
        shadow_mode=True,  # Default for Build/Review/Gate
    )

    # Step execution uses workspace.root()
    step_ctx = StepContext(
        repo_root=workspace.root(),  # May be shadow branch location
        ...
    )

    # After step, capture forensics
    forensics = workspace.snapshot_forensics()

    # Only Flow 6 promotes to real repo
    if flow_key == "deploy" and promote_decision:
        result = workspace.promote(commit_message="...")

    # Cleanup
    workspace.cleanup(success=success)
"""

from __future__ import annotations

import logging
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .shadow_fork import ShadowFork, load_shadow_state

logger = logging.getLogger(__name__)


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class ForensicsSnapshot:
    """Snapshot of workspace state for audit and debugging.

    Attributes:
        timestamp: When the snapshot was taken.
        workspace_root: The workspace root path.
        workspace_type: "real" or "shadow".
        branch: Current git branch.
        status: Git status summary.
        diff_stats: Diff statistics (files changed, insertions, deletions).
        file_changes: Categorized file changes (added, modified, deleted).
        upstream_divergence: Commits behind/ahead of upstream.
    """

    timestamp: str
    workspace_root: str
    workspace_type: str
    branch: str = ""
    status: str = ""
    diff_stats: Dict[str, int] = field(default_factory=dict)
    file_changes: Dict[str, List[str]] = field(default_factory=dict)
    upstream_divergence: Dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "timestamp": self.timestamp,
            "workspace_root": self.workspace_root,
            "workspace_type": self.workspace_type,
            "branch": self.branch,
            "status": self.status,
            "diff_stats": self.diff_stats,
            "file_changes": self.file_changes,
            "upstream_divergence": self.upstream_divergence,
        }


@dataclass
class PromotionResult:
    """Result of promoting changes from shadow to real workspace.

    Attributes:
        success: Whether promotion succeeded.
        commit_sha: The commit SHA after promotion (if successful).
        error: Error message if promotion failed.
        summary: Human-readable summary of what was promoted.
    """

    success: bool
    commit_sha: str = ""
    error: str = ""
    summary: str = ""


@dataclass
class BoundaryViolation:
    """A detected boundary violation (file write outside workspace).

    Attributes:
        path: The violating path.
        operation: What was attempted (write, delete, etc.).
        timestamp: When the violation was detected.
        step_id: Which step caused the violation.
    """

    path: str
    operation: str
    timestamp: str
    step_id: str = ""


# =============================================================================
# Abstract Workspace Interface
# =============================================================================


class Workspace(ABC):
    """Abstract workspace interface for step execution.

    Every step receives a Workspace and uses `root()` for file operations.
    This abstraction allows transparent switching between real and shadow modes.
    """

    @abstractmethod
    def root(self) -> Path:
        """Get the workspace root path.

        Returns:
            Path to use for all file operations in this step.
        """
        ...

    @abstractmethod
    def snapshot_forensics(self) -> ForensicsSnapshot:
        """Capture current workspace state for audit.

        Returns:
            ForensicsSnapshot with diff, status, and change summary.
        """
        ...

    @abstractmethod
    def promote(self, commit_message: str = "") -> PromotionResult:
        """Promote changes to the real repository.

        This is only valid for shadow workspaces. Real workspaces
        return success immediately (no-op).

        Args:
            commit_message: Message for the merge/promotion commit.

        Returns:
            PromotionResult with success status and details.
        """
        ...

    @abstractmethod
    def cleanup(self, success: bool) -> None:
        """Clean up workspace resources.

        Args:
            success: Whether the flow succeeded. Shadow workspaces
                may keep successful branches but delete failed ones.
        """
        ...

    @abstractmethod
    def is_shadow(self) -> bool:
        """Check if this is a shadow workspace.

        Returns:
            True if this is a shadow fork workspace.
        """
        ...

    @property
    @abstractmethod
    def run_base(self) -> Path:
        """Get the RUN_BASE path for artifacts.

        Returns:
            Path to swarm/runs/<run_id>/ for this workspace.
        """
        ...


# =============================================================================
# Real Workspace Implementation
# =============================================================================


class RealWorkspace(Workspace):
    """Workspace that operates directly on the real repository.

    This is the simplest workspace - it just wraps the repo root.
    Used for Deploy flow where we actually want to merge.
    """

    def __init__(
        self,
        repo_root: Path,
        run_id: str,
    ):
        """Initialize real workspace.

        Args:
            repo_root: Path to the repository root.
            run_id: Run identifier for RUN_BASE calculation.
        """
        self._repo_root = Path(repo_root).resolve()
        self._run_id = run_id

    def root(self) -> Path:
        """Get the repository root."""
        return self._repo_root

    def snapshot_forensics(self) -> ForensicsSnapshot:
        """Capture git state for audit."""
        timestamp = datetime.now(timezone.utc).isoformat()

        # Get current branch
        branch = self._run_git(["rev-parse", "--abbrev-ref", "HEAD"])

        # Get status
        status = self._run_git(["status", "--porcelain"])

        # Parse status for file changes
        file_changes = self._parse_status(status)

        # Get diff stats
        diff_stats = self._get_diff_stats()

        return ForensicsSnapshot(
            timestamp=timestamp,
            workspace_root=str(self._repo_root),
            workspace_type="real",
            branch=branch,
            status=status,
            diff_stats=diff_stats,
            file_changes=file_changes,
        )

    def promote(self, commit_message: str = "") -> PromotionResult:
        """No-op for real workspace - already in real repo."""
        return PromotionResult(
            success=True,
            summary="Real workspace - no promotion needed",
        )

    def cleanup(self, success: bool) -> None:
        """No-op for real workspace - nothing to clean up."""
        pass

    def is_shadow(self) -> bool:
        """Real workspace is not a shadow."""
        return False

    @property
    def run_base(self) -> Path:
        """Get RUN_BASE path."""
        return self._repo_root / "swarm" / "runs" / self._run_id

    def _run_git(self, args: List[str]) -> str:
        """Run a git command and return stdout."""
        try:
            result = subprocess.run(
                ["git"] + args,
                cwd=str(self._repo_root),
                capture_output=True,
                text=True,
                timeout=30,
            )
            return result.stdout.strip()
        except Exception as e:
            logger.warning("Git command failed: %s", e)
            return ""

    def _parse_status(self, status: str) -> Dict[str, List[str]]:
        """Parse git status into categorized changes."""
        changes: Dict[str, List[str]] = {
            "added": [],
            "modified": [],
            "deleted": [],
            "untracked": [],
        }

        for line in status.split("\n"):
            if not line:
                continue
            code = line[:2]
            path = line[3:]

            if "A" in code:
                changes["added"].append(path)
            elif "M" in code:
                changes["modified"].append(path)
            elif "D" in code:
                changes["deleted"].append(path)
            elif "?" in code:
                changes["untracked"].append(path)

        return changes

    def _get_diff_stats(self) -> Dict[str, int]:
        """Get diff statistics."""
        try:
            result = subprocess.run(
                ["git", "diff", "--stat", "--cached"],
                cwd=str(self._repo_root),
                capture_output=True,
                text=True,
                timeout=30,
            )
            # Parse last line like "3 files changed, 10 insertions(+), 5 deletions(-)"
            lines = result.stdout.strip().split("\n")
            if lines:
                last_line = lines[-1]
                stats = {
                    "files_changed": 0,
                    "insertions": 0,
                    "deletions": 0,
                }
                # Simple parsing
                if "file" in last_line:
                    parts = last_line.split(",")
                    for part in parts:
                        if "file" in part:
                            stats["files_changed"] = int(part.split()[0])
                        elif "insertion" in part:
                            stats["insertions"] = int(part.split()[0])
                        elif "deletion" in part:
                            stats["deletions"] = int(part.split()[0])
                return stats
        except Exception:
            pass  # Git diff stat parsing failed - return empty stats
        return {}


# =============================================================================
# Shadow Fork Workspace Implementation
# =============================================================================


class ShadowForkWorkspace(Workspace):
    """Workspace that operates in an isolated shadow branch.

    This wraps ShadowFork to provide the Workspace interface.
    All operations happen in the shadow branch, protecting main.
    """

    def __init__(
        self,
        repo_root: Path,
        run_id: str,
        base_branch: str = "main",
        shadow_fork: Optional[ShadowFork] = None,
    ):
        """Initialize shadow fork workspace.

        Args:
            repo_root: Path to the repository root.
            run_id: Run identifier for RUN_BASE and branch naming.
            base_branch: Branch to create shadow from.
            shadow_fork: Existing ShadowFork to wrap (for recovery).
        """
        self._repo_root = Path(repo_root).resolve()
        self._run_id = run_id
        self._base_branch = base_branch

        if shadow_fork:
            self._fork = shadow_fork
        else:
            self._fork = ShadowFork(
                repo_root=self._repo_root,
                base_branch=base_branch,
            )

        self._created = False
        self._boundary_violations: List[BoundaryViolation] = []

    def create(self) -> str:
        """Create the shadow branch.

        Returns:
            Name of the created shadow branch.
        """
        if not self._created and not self._fork.shadow_branch:
            branch_name = self._fork.create(self._base_branch)
            self._created = True
            return branch_name
        return self._fork.shadow_branch or ""

    def root(self) -> Path:
        """Get the repository root (same location, different branch)."""
        # Shadow fork uses same repo location but different branch
        return self._repo_root

    def snapshot_forensics(self) -> ForensicsSnapshot:
        """Capture shadow workspace state for audit."""
        timestamp = datetime.now(timezone.utc).isoformat()

        # Get diff stat from base (get_diff() returns str, not tuple)
        if self._fork.shadow_branch:
            diff_stat = self._run_git([
                "diff", "--stat", f"{self._base_branch}...{self._fork.shadow_branch}"
            ])
        else:
            diff_stat = ""

        # Get upstream divergence
        divergence = self._get_divergence()

        return ForensicsSnapshot(
            timestamp=timestamp,
            workspace_root=str(self._repo_root),
            workspace_type="shadow",
            branch=self._fork.shadow_branch or "",
            status=self._run_git(["status", "--porcelain"]),
            diff_stats=self._parse_diff_stat(diff_stat),
            file_changes=self._get_file_changes(),
            upstream_divergence=divergence,
        )

    def promote(self, commit_message: str = "") -> PromotionResult:
        """Promote shadow changes to main.

        This allows push and bridges to main.

        Args:
            commit_message: Message for the merge commit.

        Returns:
            PromotionResult with details.
        """
        if not self._fork.shadow_branch:
            return PromotionResult(
                success=False,
                error="No shadow branch to promote",
            )

        try:
            # Allow push
            self._fork.allow_push()

            # Bridge to main (returns bool, not tuple)
            bridge_success = self._fork.bridge_to_main()

            if bridge_success:
                # Get the resulting commit SHA
                commit_sha = self._run_git(["rev-parse", "HEAD"])
                return PromotionResult(
                    success=True,
                    commit_sha=commit_sha,
                    summary=f"Promoted {self._fork.shadow_branch} to {self._base_branch}",
                )
            else:
                return PromotionResult(
                    success=False,
                    error="Bridge to main failed - check git logs for details",
                )

        except Exception as e:
            return PromotionResult(
                success=False,
                error=str(e),
            )

    def cleanup(self, success: bool) -> None:
        """Clean up shadow branch.

        Args:
            success: If True, may keep the branch. If False, deletes it.
        """
        if self._fork.shadow_branch:
            self._fork.cleanup(success=success)

    def is_shadow(self) -> bool:
        """Shadow fork workspace is always a shadow."""
        return True

    @property
    def run_base(self) -> Path:
        """Get RUN_BASE path."""
        return self._repo_root / "swarm" / "runs" / self._run_id

    def checkpoint(self, message: str) -> str:
        """Create a checkpoint commit.

        Args:
            message: Checkpoint commit message.

        Returns:
            Commit SHA of the checkpoint (empty string on failure).
        """
        # commit_checkpoint returns str (the SHA), raises on failure
        try:
            sha = self._fork.commit_checkpoint(message)
            return sha
        except Exception:
            return ""

    def rollback(self, commit_sha: str) -> bool:
        """Rollback to a checkpoint.

        Args:
            commit_sha: SHA of the checkpoint to roll back to.

        Returns:
            True if rollback succeeded.
        """
        # rollback_to returns bool directly
        return self._fork.rollback_to(commit_sha)

    def record_boundary_violation(
        self,
        path: str,
        operation: str,
        step_id: str = "",
    ) -> None:
        """Record a boundary violation.

        Args:
            path: The violating path.
            operation: What was attempted.
            step_id: Which step caused it.
        """
        violation = BoundaryViolation(
            path=path,
            operation=operation,
            timestamp=datetime.now(timezone.utc).isoformat(),
            step_id=step_id,
        )
        self._boundary_violations.append(violation)
        logger.warning(
            "Boundary violation: %s attempted %s on %s",
            step_id or "unknown",
            operation,
            path,
        )

    def get_boundary_violations(self) -> List[BoundaryViolation]:
        """Get recorded boundary violations."""
        return list(self._boundary_violations)

    def _run_git(self, args: List[str]) -> str:
        """Run a git command and return stdout."""
        try:
            result = subprocess.run(
                ["git"] + args,
                cwd=str(self._repo_root),
                capture_output=True,
                text=True,
                timeout=30,
            )
            return result.stdout.strip()
        except Exception as e:
            logger.warning("Git command failed: %s", e)
            return ""

    def _parse_diff_stat(self, diff_stat: str) -> Dict[str, int]:
        """Parse diff --stat output."""
        stats = {"files_changed": 0, "insertions": 0, "deletions": 0}
        if not diff_stat:
            return stats

        lines = diff_stat.strip().split("\n")
        if lines:
            last_line = lines[-1]
            if "file" in last_line:
                parts = last_line.split(",")
                for part in parts:
                    if "file" in part:
                        stats["files_changed"] = int(part.split()[0])
                    elif "insertion" in part:
                        stats["insertions"] = int(part.split()[0])
                    elif "deletion" in part:
                        stats["deletions"] = int(part.split()[0])
        return stats

    def _get_file_changes(self) -> Dict[str, List[str]]:
        """Get categorized file changes."""
        status = self._run_git(["status", "--porcelain"])
        changes: Dict[str, List[str]] = {
            "added": [],
            "modified": [],
            "deleted": [],
            "untracked": [],
        }

        for line in status.split("\n"):
            if not line:
                continue
            code = line[:2]
            path = line[3:]

            if "A" in code:
                changes["added"].append(path)
            elif "M" in code:
                changes["modified"].append(path)
            elif "D" in code:
                changes["deleted"].append(path)
            elif "?" in code:
                changes["untracked"].append(path)

        return changes

    def _get_divergence(self) -> Dict[str, int]:
        """Get upstream divergence info."""
        try:
            # Get ahead/behind counts
            result = self._run_git([
                "rev-list",
                "--left-right",
                "--count",
                f"{self._base_branch}...HEAD",
            ])
            if result:
                parts = result.split()
                if len(parts) == 2:
                    return {
                        "behind": int(parts[0]),
                        "ahead": int(parts[1]),
                    }
        except Exception:
            pass  # Git divergence check failed - assume no divergence
        return {"behind": 0, "ahead": 0}


# =============================================================================
# Factory Function
# =============================================================================


def create_workspace(
    repo_root: Path,
    run_id: str,
    flow_key: str,
    shadow_mode: Optional[bool] = None,
    base_branch: str = "main",
) -> Workspace:
    """Create appropriate workspace for flow execution.

    Args:
        repo_root: Path to the repository root.
        run_id: Run identifier.
        flow_key: Which flow is executing (affects shadow mode decision).
        shadow_mode: Explicit shadow mode setting. If None, uses flow heuristics.
        base_branch: Branch to create shadow from.

    Returns:
        Appropriate Workspace implementation.
    """
    # Determine shadow mode based on flow if not explicitly set
    if shadow_mode is None:
        # Deploy flow operates on real repo (it actually merges)
        # All other flows use shadow for safety
        shadow_mode = flow_key not in ("deploy",)

    if shadow_mode:
        workspace = ShadowForkWorkspace(
            repo_root=repo_root,
            run_id=run_id,
            base_branch=base_branch,
        )
        # Create the shadow branch immediately
        workspace.create()
        logger.info(
            "Created shadow workspace for flow %s (run %s)",
            flow_key,
            run_id,
        )
        return workspace
    else:
        logger.info(
            "Created real workspace for flow %s (run %s)",
            flow_key,
            run_id,
        )
        return RealWorkspace(repo_root=repo_root, run_id=run_id)


def recover_workspace(
    repo_root: Path,
    run_id: str,
) -> Optional[Workspace]:
    """Recover workspace from existing shadow state.

    Used for crash recovery - loads shadow state from marker file.

    Args:
        repo_root: Path to the repository root.
        run_id: Run identifier.

    Returns:
        Recovered Workspace or None if no shadow state exists.
    """
    shadow_state = load_shadow_state(repo_root)
    if shadow_state:
        return ShadowForkWorkspace(
            repo_root=repo_root,
            run_id=run_id,
            base_branch=shadow_state.base_branch,
            shadow_fork=shadow_state,
        )
    return None


__all__ = [
    # Data classes
    "ForensicsSnapshot",
    "PromotionResult",
    "BoundaryViolation",
    # Abstract interface
    "Workspace",
    # Implementations
    "RealWorkspace",
    "ShadowForkWorkspace",
    # Factory
    "create_workspace",
    "recover_workspace",
]
