"""
shadow_fork.py - Shadow Fork isolation layer for safe speculative execution.

This module provides git branch isolation for speculative flow execution.
All file operations happen in a shadow branch, never touching main until
explicitly bridged by Flow 6. Failed runs can discard the shadow branch
without affecting the main branch.

Design Philosophy:
    - Shadow branches provide safe isolation for speculative work
    - Pushes are blocked by default via pre-push hook
    - Only Flow 6 (Deploy) can bridge changes to main
    - Checkpoints enable rollback within a shadow session
    - Cleanup handles both success and failure scenarios

Usage:
    from swarm.runtime.shadow_fork import ShadowFork

    # Create a shadow fork for speculative execution
    fork = ShadowFork(repo_root=Path("."))
    shadow_branch = fork.create(base_branch="main")

    # Work happens in shadow branch...

    # Checkpoint for potential rollback
    commit_sha = fork.commit_checkpoint("WIP: tests passing")

    # If something goes wrong, rollback
    fork.rollback_to(commit_sha)

    # When ready (Flow 6 only), bridge to main
    fork.allow_push()
    fork.bridge_to_main()

    # Cleanup (always call, success or failure)
    fork.cleanup(success=True)
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple

# Module logger
logger = logging.getLogger(__name__)

# Constants
SHADOW_BRANCH_PREFIX = "shadow/"
MARKER_FILE = ".shadow_fork_active"
PRE_PUSH_HOOK_MARKER = "# SHADOW_FORK_PUSH_GUARD"


@dataclass
class ShadowFork:
    """Git branch isolation layer for safe speculative execution.

    All file operations happen in a shadow branch, protecting main from
    incomplete or failed runs. Pushes are blocked by default until
    explicitly allowed by Flow 6.

    Attributes:
        repo_root: Path to the repository root.
        shadow_branch: Name of the created shadow branch (None if not created).
        original_branch: Name of the branch before shadow fork (None if not created).
        base_branch: The branch to create shadow from (default: main).
        _push_allowed: Internal flag tracking if push is allowed.
    """

    repo_root: Path
    shadow_branch: Optional[str] = None
    original_branch: Optional[str] = None
    base_branch: str = "main"
    _push_allowed: bool = field(default=False, repr=False)

    def _run_git(
        self,
        args: list[str],
        timeout: float = 30.0,
        check: bool = True,
    ) -> Tuple[bool, str, str]:
        """Run a git command and return (success, stdout, stderr).

        Args:
            args: Git command arguments (without 'git' prefix).
            timeout: Command timeout in seconds.
            check: If True, log errors for failed commands.

        Returns:
            Tuple of (success, stdout, stderr).
        """
        try:
            result = subprocess.run(
                ["git"] + args,
                cwd=str(self.repo_root),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            success = result.returncode == 0
            if not success and check:
                logger.warning(
                    "Git command failed: git %s\nstderr: %s",
                    " ".join(args),
                    result.stderr.strip(),
                )
            return success, result.stdout.strip(), result.stderr.strip()
        except subprocess.TimeoutExpired:
            logger.error("Git command timed out: git %s", " ".join(args))
            return False, "", f"Git command timed out after {timeout}s"
        except FileNotFoundError:
            logger.error("Git not found in PATH")
            return False, "", "Git not found in PATH"
        except Exception as e:
            logger.error("Git command failed: %s", e)
            return False, "", f"Git command failed: {e}"

    def _get_current_branch(self) -> Optional[str]:
        """Get the current branch name.

        Returns:
            Current branch name, or None if not on a branch.
        """
        success, stdout, _ = self._run_git(
            ["rev-parse", "--abbrev-ref", "HEAD"],
            check=False,
        )
        if success and stdout and stdout != "HEAD":
            return stdout
        return None

    def _get_marker_path(self) -> Path:
        """Get the path to the shadow fork marker file."""
        return self.repo_root / MARKER_FILE

    def _get_pre_push_hook_path(self) -> Path:
        """Get the path to the pre-push hook."""
        return self.repo_root / ".git" / "hooks" / "pre-push"

    def _is_shadow_active(self) -> bool:
        """Check if a shadow fork is currently active."""
        return self._get_marker_path().exists()

    def _generate_shadow_branch_name(self) -> str:
        """Generate a timestamped shadow branch name.

        Returns:
            Branch name in format: shadow/YYYYMMDD-HHMMSS-ffffff (with microseconds)
        """
        now = datetime.now(timezone.utc)
        timestamp = now.strftime("%Y%m%d-%H%M%S-%f")
        return f"{SHADOW_BRANCH_PREFIX}{timestamp}"

    def create(self, base_branch: str = "main") -> str:
        """Create a shadow branch for isolated speculative execution.

        Creates a new branch from the specified base branch, installs
        a push guard hook, and creates a marker file to track state.

        Args:
            base_branch: The branch to create shadow from (default: main).

        Returns:
            Name of the created shadow branch.

        Raises:
            RuntimeError: If shadow fork creation fails.
        """
        # Check if already in a shadow fork
        if self._is_shadow_active():
            marker_path = self._get_marker_path()
            try:
                content = marker_path.read_text().strip()
                raise RuntimeError(
                    f"Shadow fork already active. Existing shadow: {content}. "
                    "Call cleanup() before creating a new shadow fork."
                )
            except IOError:
                # Marker exists but unreadable - continue with cleanup
                self._cleanup_marker()

        # Save current branch before switching
        current = self._get_current_branch()
        if current is None:
            raise RuntimeError("Not on a branch. Cannot create shadow fork.")
        self.original_branch = current
        self.base_branch = base_branch

        # Check for uncommitted changes that would be lost
        success, stdout, _ = self._run_git(["status", "--porcelain"])
        if success and stdout:
            logger.warning(
                "Working tree has uncommitted changes. "
                "These will be carried into the shadow branch."
            )

        # Ensure base branch exists
        success, _, stderr = self._run_git(
            ["rev-parse", "--verify", base_branch],
            check=False,
        )
        if not success:
            raise RuntimeError(
                f"Base branch '{base_branch}' does not exist: {stderr}"
            )

        # Generate shadow branch name
        self.shadow_branch = self._generate_shadow_branch_name()

        # Create and switch to shadow branch
        success, _, stderr = self._run_git(
            ["checkout", "-b", self.shadow_branch, base_branch]
        )
        if not success:
            raise RuntimeError(
                f"Failed to create shadow branch '{self.shadow_branch}': {stderr}"
            )

        # Install push guard
        self.block_upstream_push()

        # Create marker file
        marker_path = self._get_marker_path()
        try:
            marker_content = (
                f"shadow_branch={self.shadow_branch}\n"
                f"original_branch={self.original_branch}\n"
                f"base_branch={self.base_branch}\n"
                f"created_at={datetime.now(timezone.utc).isoformat()}\n"
            )
            marker_path.write_text(marker_content)
        except IOError as e:
            # Rollback: delete shadow branch and return to original
            self._run_git(["checkout", self.original_branch], check=False)
            self._run_git(["branch", "-D", self.shadow_branch], check=False)
            raise RuntimeError(f"Failed to create marker file: {e}")

        logger.info(
            "Created shadow fork '%s' from '%s'",
            self.shadow_branch,
            base_branch,
        )
        return self.shadow_branch

    def get_diff(self) -> str:
        """Get diff of shadow branch against base branch.

        Returns:
            Git diff output as string, or empty string on error.
        """
        if self.shadow_branch is None:
            logger.warning("No shadow branch active")
            return ""

        # Get diff against base branch
        success, stdout, stderr = self._run_git(
            ["diff", f"{self.base_branch}...{self.shadow_branch}"]
        )
        if not success:
            logger.error("Failed to get diff: %s", stderr)
            return ""
        return stdout

    def commit_checkpoint(self, message: str) -> str:
        """Create a checkpoint commit in the shadow branch.

        This allows rolling back to a known-good state if subsequent
        operations fail.

        Args:
            message: Commit message for the checkpoint.

        Returns:
            SHA of the checkpoint commit.

        Raises:
            RuntimeError: If checkpoint creation fails.
        """
        if self.shadow_branch is None:
            raise RuntimeError("No shadow branch active")

        # Stage all changes
        success, _, stderr = self._run_git(["add", "-A"])
        if not success:
            raise RuntimeError(f"Failed to stage changes: {stderr}")

        # Check if there are changes to commit
        success, stdout, _ = self._run_git(
            ["diff", "--cached", "--quiet"],
            check=False,
        )
        if success:
            # No changes to commit, return current HEAD
            success, sha, _ = self._run_git(["rev-parse", "HEAD"])
            if success:
                logger.info("No changes to checkpoint, returning current HEAD")
                return sha
            raise RuntimeError("Failed to get current HEAD")

        # Create checkpoint commit
        success, _, stderr = self._run_git(
            ["commit", "-m", f"[checkpoint] {message}"]
        )
        if not success:
            raise RuntimeError(f"Failed to create checkpoint: {stderr}")

        # Get the commit SHA
        success, sha, stderr = self._run_git(["rev-parse", "HEAD"])
        if not success:
            raise RuntimeError(f"Failed to get checkpoint SHA: {stderr}")

        logger.info("Created checkpoint at %s: %s", sha[:8], message)
        return sha

    def rollback_to(self, commit_sha: str) -> bool:
        """Rollback the shadow branch to a checkpoint commit.

        Args:
            commit_sha: SHA of the checkpoint commit to rollback to.

        Returns:
            True if rollback succeeded, False otherwise.
        """
        if self.shadow_branch is None:
            logger.error("No shadow branch active")
            return False

        # Verify the commit exists
        success, _, _ = self._run_git(
            ["rev-parse", "--verify", commit_sha],
            check=False,
        )
        if not success:
            logger.error("Commit %s does not exist", commit_sha)
            return False

        # Hard reset to the checkpoint
        # This discards all changes after the checkpoint
        success, _, stderr = self._run_git(["reset", "--hard", commit_sha])
        if not success:
            logger.error("Failed to rollback: %s", stderr)
            return False

        logger.info("Rolled back to checkpoint %s", commit_sha[:8])
        return True

    def bridge_to_main(self) -> bool:
        """Merge shadow branch changes to main (Flow 6 only).

        This should only be called from Flow 6 (Deploy) after all
        gates have passed. Requires push to be allowed first.

        Returns:
            True if bridge succeeded, False otherwise.
        """
        if self.shadow_branch is None:
            logger.error("No shadow branch active")
            return False

        if not self._push_allowed:
            logger.error(
                "Push not allowed. Call allow_push() before bridging to main."
            )
            return False

        # Switch to base branch
        success, _, stderr = self._run_git(["checkout", self.base_branch])
        if not success:
            logger.error("Failed to switch to base branch: %s", stderr)
            return False

        # Merge shadow branch
        success, _, stderr = self._run_git(
            ["merge", "--no-ff", self.shadow_branch, "-m",
             f"Merge {self.shadow_branch} into {self.base_branch}"]
        )
        if not success:
            logger.error("Failed to merge shadow branch: %s", stderr)
            # Abort merge to clear conflict state (best effort)
            self._run_git(["merge", "--abort"], check=False)
            # Try to return to shadow branch
            self._run_git(["checkout", self.shadow_branch], check=False)
            return False

        logger.info(
            "Bridged shadow '%s' to '%s'",
            self.shadow_branch,
            self.base_branch,
        )
        return True

    def block_upstream_push(self) -> None:
        """Install pre-push hook to block pushes to upstream.

        This is called automatically during create() but can be
        called again if the hook is removed.
        """
        hook_path = self._get_pre_push_hook_path()

        # Create hooks directory if needed
        hook_path.parent.mkdir(parents=True, exist_ok=True)

        # Check if hook already exists
        existing_content = ""
        if hook_path.exists():
            try:
                existing_content = hook_path.read_text()
            except IOError:
                pass  # Hook unreadable - will be recreated

        # Check if our guard is already installed
        if PRE_PUSH_HOOK_MARKER in existing_content:
            logger.debug("Push guard already installed")
            return

        # Create or append to hook
        hook_script = f"""
{PRE_PUSH_HOOK_MARKER}
# Block pushes while shadow fork is active
if [ -f "{MARKER_FILE}" ]; then
    echo "ERROR: Push blocked by shadow fork isolation."
    echo "Shadow fork is active. Use allow_push() before pushing."
    exit 1
fi
{PRE_PUSH_HOOK_MARKER}_END
"""

        try:
            if existing_content:
                # Append to existing hook
                new_content = existing_content + "\n" + hook_script
            else:
                # Create new hook with shebang
                new_content = "#!/bin/sh\n" + hook_script

            hook_path.write_text(new_content)
            # Make hook executable (Unix-like systems)
            hook_path.chmod(0o755)
            logger.debug("Installed push guard hook")
        except IOError as e:
            logger.warning("Failed to install push guard: %s", e)

    def allow_push(self) -> None:
        """Remove push block for Flow 6 deployment.

        This removes the push guard from the pre-push hook,
        allowing pushes to upstream.
        """
        self._push_allowed = True

        hook_path = self._get_pre_push_hook_path()
        if not hook_path.exists():
            return

        try:
            content = hook_path.read_text()
        except IOError:
            return

        # Remove our guard section
        if PRE_PUSH_HOOK_MARKER not in content:
            return

        # Remove everything between markers
        lines = content.split("\n")
        new_lines = []
        in_guard = False

        for line in lines:
            if PRE_PUSH_HOOK_MARKER in line and "_END" not in line:
                in_guard = True
                continue
            if f"{PRE_PUSH_HOOK_MARKER}_END" in line:
                in_guard = False
                continue
            if not in_guard:
                new_lines.append(line)

        new_content = "\n".join(new_lines)

        # Remove empty hooks
        if new_content.strip() in ("", "#!/bin/sh"):
            try:
                hook_path.unlink()
                logger.debug("Removed empty push hook")
            except IOError:
                pass  # Hook deletion failed - not critical
        else:
            try:
                hook_path.write_text(new_content)
                logger.debug("Removed push guard from hook")
            except IOError as e:
                logger.warning("Failed to update push hook: %s", e)

    def _cleanup_marker(self) -> None:
        """Remove the marker file."""
        marker_path = self._get_marker_path()
        try:
            if marker_path.exists():
                marker_path.unlink()
                logger.debug("Removed marker file")
        except IOError as e:
            logger.warning("Failed to remove marker file: %s", e)

    def cleanup(self, success: bool) -> None:
        """Clean up shadow branch and related artifacts.

        Args:
            success: If True, the shadow fork completed successfully
                     and changes were bridged. If False, discard the
                     shadow branch.
        """
        if self.shadow_branch is None:
            logger.debug("No shadow branch to clean up")
            self._cleanup_marker()
            return

        # Remove push guard if installed
        self.allow_push()

        if success:
            # Changes were bridged, delete shadow branch
            current = self._get_current_branch()
            if current == self.shadow_branch:
                # Switch to base branch first
                self._run_git(["checkout", self.base_branch], check=False)

            self._run_git(["branch", "-D", self.shadow_branch], check=False)
            logger.info("Cleaned up successful shadow fork '%s'", self.shadow_branch)
        else:
            # Failed run, restore original branch and delete shadow
            current = self._get_current_branch()
            if current == self.shadow_branch:
                # Switch back to original branch
                if self.original_branch:
                    self._run_git(["checkout", self.original_branch], check=False)
                else:
                    self._run_git(["checkout", self.base_branch], check=False)

            # Delete shadow branch
            self._run_git(["branch", "-D", self.shadow_branch], check=False)
            logger.info(
                "Discarded failed shadow fork '%s', restored to '%s'",
                self.shadow_branch,
                self.original_branch or self.base_branch,
            )

        # Remove marker file
        self._cleanup_marker()

        # Reset state
        self.shadow_branch = None
        self.original_branch = None
        self._push_allowed = False


def load_shadow_state(repo_root: Path) -> Optional[ShadowFork]:
    """Load existing shadow fork state from marker file.

    This is useful for resuming a shadow fork session after a restart.

    Args:
        repo_root: Path to the repository root.

    Returns:
        ShadowFork instance with loaded state, or None if no active fork.
    """
    marker_path = repo_root / MARKER_FILE
    if not marker_path.exists():
        return None

    try:
        content = marker_path.read_text()
    except IOError:
        return None

    # Parse marker file
    state = {}
    for line in content.strip().split("\n"):
        if "=" in line:
            key, value = line.split("=", 1)
            state[key.strip()] = value.strip()

    fork = ShadowFork(
        repo_root=repo_root,
        shadow_branch=state.get("shadow_branch"),
        original_branch=state.get("original_branch"),
        base_branch=state.get("base_branch", "main"),
    )

    logger.info("Loaded shadow fork state: %s", fork.shadow_branch)
    return fork
