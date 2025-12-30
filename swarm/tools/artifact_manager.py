#!/usr/bin/env python3
"""
Artifact Manager

Manages run IDs and artifact paths for selftest reports and flow artifacts.
"""

import json
import os
import socket
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple, Union


def get_platform_name() -> str:
    """Return platform name: linux, darwin, win32"""
    return sys.platform


def get_hostname() -> str:
    """Return hostname"""
    return socket.gethostname()


def get_git_info() -> Tuple[str, str]:
    """Return (branch, commit_sha)"""
    try:
        branch = subprocess.run(
            "git rev-parse --abbrev-ref HEAD",
            shell=True,
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.strip()

        commit = subprocess.run(
            "git rev-parse --short HEAD",
            shell=True,
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.strip()

        return branch or "unknown", commit or "unknown"
    except Exception:
        return "unknown", "unknown"


def get_user() -> str:
    """Return username from $USER or $USERNAME"""
    return os.environ.get("USER") or os.environ.get("USERNAME") or "unknown"


class ArtifactManager:
    """Manages artifact paths and run ID detection."""

    def __init__(self, repo_root: Optional[Path] = None):
        self.repo_root = repo_root or Path.cwd()
        self.run_id = self._detect_run_id()

    def _detect_run_id(self) -> str:
        """Detect run ID from environment or git."""
        # Try in order:
        # 1. GIT_BRANCH env var (CI/CD)
        # 2. CI_COMMIT_SHA env var (CI/CD)
        # 3. git rev-parse --short HEAD
        # 4. Fallback to timestamp-based ID

        # Try environment variables (CI/CD)
        if os.environ.get("GIT_BRANCH"):
            return os.environ["GIT_BRANCH"]

        if os.environ.get("CI_COMMIT_SHA"):
            return os.environ["CI_COMMIT_SHA"][:12]

        # Try git
        try:
            branch = subprocess.run(
                "git rev-parse --abbrev-ref HEAD",
                shell=True,
                capture_output=True,
                text=True,
                timeout=5,
            ).stdout.strip()

            if branch and branch != "HEAD":
                return branch

            # Fallback to commit hash
            commit = subprocess.run(
                "git rev-parse --short HEAD",
                shell=True,
                capture_output=True,
                text=True,
                timeout=5,
            ).stdout.strip()

            if commit:
                return commit
        except Exception:
            pass

        # Fallback to timestamp
        return datetime.now().strftime("%Y%m%d-%H%M%S")

    def get_run_base(self) -> Path:
        """Return RUN_BASE path: swarm/runs/<run-id>/"""
        return self.repo_root / "swarm" / "runs" / self.run_id

    def get_artifact_path(self, flow: str, filename: str) -> Path:
        """Return artifact path: RUN_BASE/<flow>/<filename>"""
        return self.get_run_base() / flow / filename

    def ensure_artifact_dir(self, flow: str) -> Path:
        """Create artifact directory if needed."""
        path = self.get_run_base() / flow
        path.mkdir(parents=True, exist_ok=True)
        return path

    def write_artifact(self, flow: str, filename: str, content: Union[str, dict]) -> Path:
        """Write artifact to disk."""
        path = self.get_artifact_path(flow, filename)
        self.ensure_artifact_dir(flow)

        if isinstance(content, dict):
            with open(path, "w", encoding="utf-8") as f:
                json.dump(content, f, indent=2, default=str)
        else:
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)

        return path

    def read_artifact(self, flow: str, filename: str) -> Optional[Union[str, dict]]:
        """Read artifact from disk."""
        path = self.get_artifact_path(flow, filename)

        if not path.exists():
            return None

        with open(path, "r", encoding="utf-8") as f:
            content = f.read()

        # Auto-parse JSON if extension is .json
        if filename.endswith(".json"):
            try:
                return json.loads(content)
            except json.JSONDecodeError:
                return content

        return content
