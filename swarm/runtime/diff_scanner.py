"""
diff_scanner.py - Git-based file change detection for forensic step analysis.

This module provides deterministic file mutation detection that captures ALL
changes made during a step, not just those reported by tool telemetry. This
ensures "forensics over narrative" - the system records what actually happened,
not just what the agent claimed to do.

Design Philosophy:
    - Tool telemetry misses: bash scripts, formatters, generators, indirect edits
    - Git diff captures everything: insertions, deletions, modifications, renames
    - Post-step scanning is authoritative; agent narrative is supplementary
    - Results go into HandoffEnvelope.file_changes for durability

Usage:
    from swarm.runtime.diff_scanner import scan_file_changes, FileChanges

    # After step execution, before finalization commit
    changes = await scan_file_changes(repo_root)

    # Or synchronously
    changes = scan_file_changes_sync(repo_root)

    # Include in envelope
    envelope.file_changes = file_changes_to_dict(changes)
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Module logger
logger = logging.getLogger(__name__)


@dataclass
class FileDiff:
    """Single file change record.

    Attributes:
        path: Relative path from repo root.
        status: Git status code (A=added, M=modified, D=deleted, R=renamed, etc.)
        insertions: Number of lines added.
        deletions: Number of lines removed.
        old_path: Original path for renames (None if not a rename).
    """

    path: str
    status: str  # A, M, D, R, C, U, etc.
    insertions: int = 0
    deletions: int = 0
    old_path: Optional[str] = None

    @property
    def is_rename(self) -> bool:
        """Check if this is a rename operation."""
        return self.status.startswith("R")

    @property
    def is_binary(self) -> bool:
        """Check if this is a binary file change (no line counts)."""
        return self.insertions == 0 and self.deletions == 0 and self.status == "M"


@dataclass
class FileChanges:
    """Complete file change scan result for a step.

    Attributes:
        files: List of individual file changes.
        total_insertions: Sum of all insertions across files.
        total_deletions: Sum of all deletions across files.
        untracked: List of untracked file paths.
        staged: List of staged file paths (in index but not committed).
        scan_error: Error message if scan failed (None on success).
    """

    files: List[FileDiff] = field(default_factory=list)
    total_insertions: int = 0
    total_deletions: int = 0
    untracked: List[str] = field(default_factory=list)
    staged: List[str] = field(default_factory=list)
    scan_error: Optional[str] = None

    @property
    def has_changes(self) -> bool:
        """Check if any file changes were detected."""
        return len(self.files) > 0 or len(self.untracked) > 0 or len(self.staged) > 0

    @property
    def file_count(self) -> int:
        """Total number of changed files (tracked + untracked)."""
        return len(self.files) + len(self.untracked)

    @property
    def summary(self) -> str:
        """Human-readable summary of changes."""
        if self.scan_error:
            return f"Scan error: {self.scan_error}"
        if not self.has_changes:
            return "No changes detected"
        parts = []
        if self.files:
            parts.append(f"{len(self.files)} files changed")
        if self.total_insertions:
            parts.append(f"+{self.total_insertions}")
        if self.total_deletions:
            parts.append(f"-{self.total_deletions}")
        if self.untracked:
            parts.append(f"{len(self.untracked)} untracked")
        return ", ".join(parts)


def file_diff_to_dict(diff: FileDiff) -> Dict[str, Any]:
    """Convert FileDiff to dictionary for serialization."""
    result = {
        "path": diff.path,
        "status": diff.status,
        "insertions": diff.insertions,
        "deletions": diff.deletions,
    }
    if diff.old_path:
        result["old_path"] = diff.old_path
    return result


def file_diff_from_dict(data: Dict[str, Any]) -> FileDiff:
    """Parse FileDiff from dictionary."""
    return FileDiff(
        path=data.get("path", ""),
        status=data.get("status", "M"),
        insertions=data.get("insertions", 0),
        deletions=data.get("deletions", 0),
        old_path=data.get("old_path"),
    )


def file_changes_to_dict(changes: FileChanges) -> Dict[str, Any]:
    """Convert FileChanges to dictionary for serialization."""
    return {
        "files": [file_diff_to_dict(f) for f in changes.files],
        "total_insertions": changes.total_insertions,
        "total_deletions": changes.total_deletions,
        "untracked": changes.untracked,
        "staged": changes.staged,
        "scan_error": changes.scan_error,
        "summary": changes.summary,
    }


def file_changes_from_dict(data: Dict[str, Any]) -> FileChanges:
    """Parse FileChanges from dictionary."""
    files = [file_diff_from_dict(f) for f in data.get("files", [])]
    return FileChanges(
        files=files,
        total_insertions=data.get("total_insertions", 0),
        total_deletions=data.get("total_deletions", 0),
        untracked=data.get("untracked", []),
        staged=data.get("staged", []),
        scan_error=data.get("scan_error"),
    )


def _run_git_command(
    args: List[str],
    cwd: Path,
    timeout: float = 30.0,
) -> Tuple[bool, str, str]:
    """Run a git command and return (success, stdout, stderr).

    Args:
        args: Git command arguments (without 'git' prefix).
        cwd: Working directory for the command.
        timeout: Command timeout in seconds.

    Returns:
        Tuple of (success, stdout, stderr).
    """
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.returncode == 0, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return False, "", f"Git command timed out after {timeout}s"
    except FileNotFoundError:
        return False, "", "Git not found in PATH"
    except Exception as e:
        return False, "", f"Git command failed: {e}"


def _parse_numstat_line(line: str) -> Optional[Tuple[int, int, str]]:
    """Parse a line from git diff --numstat output.

    Format: <insertions>\t<deletions>\t<path>
    Binary files show: -\t-\t<path>

    Returns:
        Tuple of (insertions, deletions, path) or None if parse fails.
    """
    parts = line.split("\t", 2)
    if len(parts) != 3:
        return None

    ins_str, del_str, path = parts

    # Binary files have "-" for counts
    if ins_str == "-" or del_str == "-":
        return 0, 0, path

    try:
        return int(ins_str), int(del_str), path
    except ValueError:
        return None


def _parse_status_line(line: str) -> Optional[Tuple[str, str, Optional[str]]]:
    """Parse a line from git status --porcelain output.

    Format: XY <path>
    For renames: XY <old_path> -> <new_path>

    Note: The XY status is 2 characters, but when Y is a space, the
    separator space may visually merge with Y. We handle both cases:
    - "M  path" (explicit separator after XY)
    - "M path" (Y is space, appears as single separator)

    Returns:
        Tuple of (status, path, old_path) or None if parse fails.
    """
    if len(line) < 3:
        return None

    # Extract the 2-character status code
    status = line[:2]

    # The path starts after the status and any separator space
    # Position 2 might be a space separator, or the path might start at 2
    if len(line) > 2 and line[2] == " ":
        rest = line[3:]
    else:
        rest = line[2:].lstrip(" ")

    if not rest:
        return None

    status = status.strip()

    # Handle renames
    if " -> " in rest:
        old_path, new_path = rest.split(" -> ", 1)
        return status, new_path, old_path

    return status, rest, None


def scan_file_changes_sync(
    repo_root: Path,
    include_untracked: bool = True,
    include_staged: bool = True,
) -> FileChanges:
    """Synchronously scan for file changes in a git repository.

    This function captures all file mutations since the last commit,
    including unstaged changes, staged changes, and untracked files.

    Args:
        repo_root: Path to the repository root.
        include_untracked: Whether to include untracked files.
        include_staged: Whether to include staged files separately.

    Returns:
        FileChanges with complete mutation information.
    """
    result = FileChanges()

    # Verify we're in a git repo
    success, _, stderr = _run_git_command(["rev-parse", "--git-dir"], repo_root)
    if not success:
        result.scan_error = f"Not a git repository: {stderr.strip()}"
        return result

    # Get file changes with numstat (insertions/deletions)
    # This shows both staged and unstaged changes
    success, stdout, stderr = _run_git_command(
        ["diff", "HEAD", "--numstat", "--find-renames"],
        repo_root,
    )

    if not success:
        # HEAD might not exist (empty repo), try without HEAD
        success, stdout, stderr = _run_git_command(
            ["diff", "--numstat", "--find-renames"],
            repo_root,
        )

    numstat_map: Dict[str, Tuple[int, int]] = {}
    if success and stdout.strip():
        for line in stdout.strip().split("\n"):
            parsed = _parse_numstat_line(line)
            if parsed:
                ins, dels, path = parsed
                numstat_map[path] = (ins, dels)

    # Get porcelain status for comprehensive file list
    success, stdout, stderr = _run_git_command(
        ["status", "--porcelain", "-uall"],  # -uall shows all untracked
        repo_root,
    )

    if not success:
        result.scan_error = f"Failed to get git status: {stderr.strip()}"
        return result

    tracked_files: List[FileDiff] = []
    untracked_files: List[str] = []
    staged_files: List[str] = []
    total_ins = 0
    total_dels = 0

    if stdout.strip():
        for line in stdout.strip().split("\n"):
            parsed = _parse_status_line(line)
            if not parsed:
                continue

            status, path, old_path = parsed

            # Untracked files have "??" status
            if status == "??":
                if include_untracked:
                    untracked_files.append(path)
                continue

            # Determine if staged (first char is not space/?)
            index_status = status[0] if status else " "
            # worktree_status would be status[1], but currently unused

            if include_staged and index_status not in (" ", "?"):
                staged_files.append(path)

            # Get line counts from numstat
            ins, dels = numstat_map.get(path, (0, 0))
            total_ins += ins
            total_dels += dels

            # Map git status to simplified status code
            # First non-space character indicates the primary operation
            simplified_status = "M"  # default
            for char in status:
                if char != " ":
                    simplified_status = char
                    break

            tracked_files.append(
                FileDiff(
                    path=path,
                    status=simplified_status,
                    insertions=ins,
                    deletions=dels,
                    old_path=old_path,
                )
            )

    result.files = tracked_files
    result.total_insertions = total_ins
    result.total_deletions = total_dels
    result.untracked = untracked_files
    result.staged = staged_files

    return result


async def scan_file_changes(
    repo_root: Path,
    include_untracked: bool = True,
    include_staged: bool = True,
) -> FileChanges:
    """Asynchronously scan for file changes in a git repository.

    This is an async wrapper around scan_file_changes_sync that runs
    the git commands in a thread pool to avoid blocking the event loop.

    Args:
        repo_root: Path to the repository root.
        include_untracked: Whether to include untracked files.
        include_staged: Whether to include staged files separately.

    Returns:
        FileChanges with complete mutation information.
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,  # Use default executor
        lambda: scan_file_changes_sync(repo_root, include_untracked, include_staged),
    )


def create_file_changes_event(
    run_id: str,
    flow_key: str,
    step_id: str,
    agent_key: Optional[str],
    changes: FileChanges,
) -> Dict[str, Any]:
    """Create a file_changes event payload for events.jsonl.

    Args:
        run_id: The run identifier.
        flow_key: The flow key.
        step_id: The step identifier.
        agent_key: The agent key (optional).
        changes: The scanned file changes.

    Returns:
        Event dictionary ready for append to events.jsonl.
    """
    from datetime import datetime, timezone

    return {
        "run_id": run_id,
        "ts": datetime.now(timezone.utc).isoformat() + "Z",
        "kind": "file_changes",
        "flow_key": flow_key,
        "step_id": step_id,
        "agent_key": agent_key,
        "payload": file_changes_to_dict(changes),
    }
