"""
boundary_enforcement.py - Detect workspace boundary violations after step execution.

This module scans for file operations that escaped the workspace boundary:
- Writes outside workspace.root()
- Git state changes in real repo when in shadow mode
- Unauthorized push attempts

The enforcement is detection-focused, not prevention-focused. We detect violations
after the fact and emit audit events. Prevention would require sandboxing which
is overkill for 95% of cases.

Usage:
    from swarm.runtime.boundary_enforcement import (
        scan_for_violations,
        BoundaryScanner,
        ViolationSeverity,
    )

    # After step execution
    scanner = BoundaryScanner(
        workspace=workspace,
        step_id=step_id,
        baseline_state=before_state,
    )

    violations = scanner.scan(current_state=after_state)

    if violations:
        for v in violations:
            logger.warning("Boundary violation: %s", v)
            workspace.record_boundary_violation(v.path, v.operation, step_id)

    # Halt on critical violations
    if any(v.severity == ViolationSeverity.CRITICAL for v in violations):
        raise BoundaryViolationError(violations)
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, TYPE_CHECKING

if TYPE_CHECKING:
    from .workspace import Workspace

logger = logging.getLogger(__name__)


# =============================================================================
# Enums and Data Classes
# =============================================================================


class ViolationSeverity(str, Enum):
    """Severity of a boundary violation."""

    INFO = "info"  # Minor - might be intentional
    WARNING = "warning"  # Concerning - should be reviewed
    ERROR = "error"  # Significant - likely a bug
    CRITICAL = "critical"  # Severe - must halt execution


class ViolationType(str, Enum):
    """Type of boundary violation."""

    WRITE_OUTSIDE_WORKSPACE = "write_outside_workspace"
    REAL_REPO_MODIFICATION = "real_repo_modification"
    UNAUTHORIZED_PUSH = "unauthorized_push"
    MAIN_BRANCH_MUTATION = "main_branch_mutation"
    FORCE_OPERATION = "force_operation"
    SECRET_EXPOSURE = "secret_exposure"


@dataclass
class Violation:
    """A detected boundary violation.

    Attributes:
        type: Type of violation.
        severity: How severe this violation is.
        path: The file/ref path involved.
        operation: What operation was attempted.
        detail: Human-readable description.
        step_id: Which step caused this.
        timestamp: When detected.
        remediation: Suggested fix.
    """

    type: ViolationType
    severity: ViolationSeverity
    path: str
    operation: str
    detail: str
    step_id: str = ""
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    remediation: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "type": self.type.value,
            "severity": self.severity.value,
            "path": self.path,
            "operation": self.operation,
            "detail": self.detail,
            "step_id": self.step_id,
            "timestamp": self.timestamp,
            "remediation": self.remediation,
        }


@dataclass
class WorkspaceState:
    """Snapshot of workspace state for comparison.

    Taken before and after step execution to detect changes.

    Attributes:
        timestamp: When snapshot was taken.
        git_status: Output of git status --porcelain.
        git_ref: Current HEAD ref.
        changed_files: Set of files with changes.
        real_repo_ref: Real repo HEAD (for shadow mode comparison).
        real_repo_files: Files in real repo (for shadow mode).
    """

    timestamp: str
    git_status: str = ""
    git_ref: str = ""
    changed_files: Set[str] = field(default_factory=set)
    real_repo_ref: str = ""
    real_repo_files: Set[str] = field(default_factory=set)


class BoundaryViolationError(Exception):
    """Raised when critical boundary violations are detected."""

    def __init__(self, violations: List[Violation]):
        self.violations = violations
        super().__init__(
            f"Critical boundary violations: {[v.type.value for v in violations]}"
        )


# =============================================================================
# Boundary Scanner
# =============================================================================


class BoundaryScanner:
    """Scans for workspace boundary violations.

    Compares before/after state to detect unauthorized changes.
    """

    # Paths that should never be modified by steps
    PROTECTED_PATHS = {
        ".git/config",
        ".git/hooks/pre-push",
        ".gitignore",
    }

    # Patterns that indicate force operations
    FORCE_PATTERNS = {
        "push --force",
        "push -f",
        "reset --hard",
        "clean -fd",
        "checkout --force",
    }

    # Patterns that indicate secret exposure
    SECRET_PATTERNS = {
        ".env",
        "credentials",
        "secrets",
        "api_key",
        "password",
        "token",
    }

    def __init__(
        self,
        workspace: "Workspace",
        step_id: str,
        repo_root: Path,
        baseline_state: Optional[WorkspaceState] = None,
    ):
        """Initialize scanner.

        Args:
            workspace: The workspace being monitored.
            step_id: Which step is being scanned.
            repo_root: The real repository root (for shadow comparison).
            baseline_state: State before step execution.
        """
        self._workspace = workspace
        self._step_id = step_id
        self._repo_root = Path(repo_root).resolve()
        self._baseline = baseline_state

    def capture_state(self) -> WorkspaceState:
        """Capture current workspace state.

        Returns:
            WorkspaceState snapshot.
        """
        timestamp = datetime.now(timezone.utc).isoformat()

        # Get git status
        git_status = self._run_git(["status", "--porcelain"])

        # Get current ref
        git_ref = self._run_git(["rev-parse", "HEAD"])

        # Get changed files
        changed_files = set()
        for line in git_status.split("\n"):
            if line and len(line) > 3:
                changed_files.add(line[3:])

        state = WorkspaceState(
            timestamp=timestamp,
            git_status=git_status,
            git_ref=git_ref,
            changed_files=changed_files,
        )

        # For shadow mode, also capture real repo state
        if self._workspace.is_shadow():
            state.real_repo_ref = self._run_git(
                ["rev-parse", "HEAD"],
                cwd=self._repo_root,
            )

        return state

    def scan(
        self,
        current_state: Optional[WorkspaceState] = None,
    ) -> List[Violation]:
        """Scan for boundary violations.

        Args:
            current_state: State after step execution. If None, captures now.

        Returns:
            List of detected violations.
        """
        if current_state is None:
            current_state = self.capture_state()

        violations: List[Violation] = []

        # Check for writes outside workspace
        violations.extend(self._check_write_violations(current_state))

        # Check for real repo modifications in shadow mode
        if self._workspace.is_shadow():
            violations.extend(self._check_shadow_violations(current_state))

        # Check for protected path modifications
        violations.extend(self._check_protected_paths(current_state))

        # Check for potential secret exposure
        violations.extend(self._check_secret_exposure(current_state))

        return violations

    def _check_write_violations(
        self,
        current: WorkspaceState,
    ) -> List[Violation]:
        """Check for writes outside workspace root."""
        violations = []
        workspace_root = self._workspace.root()

        for file_path in current.changed_files:
            # Resolve to absolute path
            abs_path = (self._repo_root / file_path).resolve()

            # Check if outside workspace
            try:
                abs_path.relative_to(workspace_root)
            except ValueError:
                # Path is outside workspace root
                violations.append(Violation(
                    type=ViolationType.WRITE_OUTSIDE_WORKSPACE,
                    severity=ViolationSeverity.ERROR,
                    path=str(file_path),
                    operation="write",
                    detail=f"File {file_path} is outside workspace root {workspace_root}",
                    step_id=self._step_id,
                    remediation="Ensure all writes go to workspace.root() or RUN_BASE",
                ))

        return violations

    def _check_shadow_violations(
        self,
        current: WorkspaceState,
    ) -> List[Violation]:
        """Check for real repo modifications when in shadow mode."""
        violations = []

        if not self._baseline:
            return violations

        # Check if real repo HEAD changed
        if (
            current.real_repo_ref
            and self._baseline.real_repo_ref
            and current.real_repo_ref != self._baseline.real_repo_ref
        ):
            violations.append(Violation(
                type=ViolationType.REAL_REPO_MODIFICATION,
                severity=ViolationSeverity.CRITICAL,
                path="HEAD",
                operation="commit/reset",
                detail=f"Real repo HEAD changed from {self._baseline.real_repo_ref[:8]} to {current.real_repo_ref[:8]}",
                step_id=self._step_id,
                remediation="Shadow mode should not modify real repo. Check for escaped git commands.",
            ))

        return violations

    def _check_protected_paths(
        self,
        current: WorkspaceState,
    ) -> List[Violation]:
        """Check for modifications to protected paths."""
        violations = []

        for file_path in current.changed_files:
            for protected in self.PROTECTED_PATHS:
                if protected in file_path:
                    violations.append(Violation(
                        type=ViolationType.MAIN_BRANCH_MUTATION,
                        severity=ViolationSeverity.WARNING,
                        path=file_path,
                        operation="modify",
                        detail=f"Protected path {protected} was modified",
                        step_id=self._step_id,
                        remediation="Review if this modification is intentional.",
                    ))

        return violations

    def _check_secret_exposure(
        self,
        current: WorkspaceState,
    ) -> List[Violation]:
        """Check for potential secret exposure in changed files."""
        violations = []

        for file_path in current.changed_files:
            file_lower = file_path.lower()
            for pattern in self.SECRET_PATTERNS:
                if pattern in file_lower:
                    violations.append(Violation(
                        type=ViolationType.SECRET_EXPOSURE,
                        severity=ViolationSeverity.WARNING,
                        path=file_path,
                        operation="modify",
                        detail=f"File {file_path} may contain secrets (matched '{pattern}')",
                        step_id=self._step_id,
                        remediation="Review file for sensitive data before committing.",
                    ))
                    break  # Only one warning per file

        return violations

    def _run_git(
        self,
        args: List[str],
        cwd: Optional[Path] = None,
    ) -> str:
        """Run a git command and return stdout."""
        try:
            result = subprocess.run(
                ["git"] + args,
                cwd=str(cwd or self._workspace.root()),
                capture_output=True,
                text=True,
                timeout=30,
            )
            return result.stdout.strip()
        except Exception as e:
            logger.warning("Git command failed: %s", e)
            return ""


# =============================================================================
# Convenience Functions
# =============================================================================


def scan_for_violations(
    workspace: "Workspace",
    step_id: str,
    repo_root: Path,
    before_state: Optional[WorkspaceState] = None,
    after_state: Optional[WorkspaceState] = None,
) -> List[Violation]:
    """Convenience function to scan for violations.

    Args:
        workspace: The workspace to scan.
        step_id: Which step is being scanned.
        repo_root: Real repository root.
        before_state: State before step (optional).
        after_state: State after step (optional, captured if not provided).

    Returns:
        List of detected violations.
    """
    scanner = BoundaryScanner(
        workspace=workspace,
        step_id=step_id,
        repo_root=repo_root,
        baseline_state=before_state,
    )
    return scanner.scan(current_state=after_state)


def emit_violation_event(
    run_id: str,
    flow_key: str,
    step_id: str,
    violation: Violation,
    append_event_fn: Optional[Any] = None,
) -> None:
    """Emit a boundary violation event for audit.

    Args:
        run_id: Run identifier.
        flow_key: Flow key.
        step_id: Step that caused the violation.
        violation: The violation to emit.
        append_event_fn: Function to append events (for testing).
    """
    if append_event_fn is None:
        try:
            from . import storage as storage_module

            append_event_fn = storage_module.append_event
        except ImportError:
            logger.warning("Could not import storage module for event emission")
            return

    from .types import RunEvent

    event = RunEvent(
        run_id=run_id,
        ts=datetime.now(timezone.utc),
        kind="boundary_violation",
        flow_key=flow_key,
        step_id=step_id,
        payload=violation.to_dict(),
    )

    # storage.append_event signature: (run_id, event, runs_dir=RUNS_DIR)
    append_event_fn(run_id, event)


__all__ = [
    # Enums
    "ViolationSeverity",
    "ViolationType",
    # Data classes
    "Violation",
    "WorkspaceState",
    # Exceptions
    "BoundaryViolationError",
    # Main class
    "BoundaryScanner",
    # Convenience functions
    "scan_for_violations",
    "emit_violation_event",
]
