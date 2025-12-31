"""
service.py - RunService orchestrator

This module provides the central RunService singleton that coordinates
run execution across backends. All consumers (Flow Studio, CLI, API)
should use RunService rather than calling backends directly.

Usage:
    from swarm.runtime.service import RunService, get_run_service

    service = RunService.get_instance()
    # or
    service = get_run_service()

    run_id = service.start_run(spec)
    summary = service.get_run(run_id)
    runs = service.list_runs()
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional

from . import storage
from .backends import (
    ClaudeHarnessBackend,
    GeminiCliBackend,
    RunBackend,
)
from .storage import EXAMPLES_DIR
from ..config.flow_registry import get_flow_order
from .types import (
    BackendCapabilities,
    BackendId,
    RunEvent,
    RunId,
    RunSpec,
    RunStatus,
    RunSummary,
    SDLCStatus,
)

# Module logger
logger = logging.getLogger(__name__)


class RunService:
    """Central service for managing runs across all backends.

    This is a singleton that provides a unified interface for:
    - Starting runs (delegates to appropriate backend)
    - Querying run status and history
    - Listing available backends
    - Managing run lifecycle

    Flow Studio, CLI, and other consumers should use this service
    rather than accessing backends or storage directly.
    """

    _instance: Optional["RunService"] = None

    def __init__(self, repo_root: Optional[Path] = None):
        """Initialize the service.

        Args:
            repo_root: Repository root path. Defaults to auto-detection.
        """
        self._repo_root = repo_root or Path(__file__).resolve().parents[2]
        self._backends: dict[BackendId, RunBackend] = {
            "claude-harness": ClaudeHarnessBackend(self._repo_root),
            "gemini-cli": GeminiCliBackend(self._repo_root),
            # Agent SDK backend will be added when implemented
        }

    @classmethod
    def get_instance(cls, repo_root: Optional[Path] = None) -> "RunService":
        """Get the singleton instance."""
        if cls._instance is None:
            cls._instance = cls(repo_root)
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Reset the singleton (for testing)."""
        cls._instance = None

    # =========================================================================
    # Backend Management
    # =========================================================================

    def list_backends(self) -> List[BackendCapabilities]:
        """List available backends and their capabilities."""
        return [b.capabilities() for b in self._backends.values()]

    def get_backend(self, backend_id: BackendId) -> Optional[RunBackend]:
        """Get a specific backend by ID."""
        return self._backends.get(backend_id)

    # =========================================================================
    # Run Lifecycle
    # =========================================================================

    def start_run(self, spec: RunSpec) -> RunId:
        """Start a new run.

        Args:
            spec: Run specification including flows, backend, and params.

        Returns:
            The generated run ID.

        Raises:
            ValueError: If the specified backend is not available.
        """
        backend = self._backends.get(spec.backend)
        if not backend:
            available = list(self._backends.keys())
            raise ValueError(
                f"Backend '{spec.backend}' not available. Available backends: {available}"
            )

        return backend.start(spec)

    def cancel_run(self, run_id: RunId) -> bool:
        """Cancel a running run.

        Attempts to cancel across all backends that support cancellation.

        Returns:
            True if the run was cancelled, False otherwise.
        """
        for backend in self._backends.values():
            if backend.capabilities().supports_cancel:
                if backend.cancel(run_id):
                    return True
        return False

    # =========================================================================
    # Run Queries
    # =========================================================================

    def get_run(self, run_id: RunId) -> Optional[RunSummary]:
        """Get a run summary by ID.

        Checks storage first, then queries backends.
        """
        # Try storage first (works for all backends)
        summary = storage.read_summary(run_id)
        if summary:
            return summary

        # Fall back to querying backends
        for backend in self._backends.values():
            summary = backend.get_summary(run_id)
            if summary:
                return summary

        return None

    def list_runs(
        self,
        flow_key: Optional[str] = None,
        include_legacy: bool = True,
        include_examples: bool = True,
    ) -> List[RunSummary]:
        """List all known runs.

        Args:
            flow_key: Optional filter by flow key.
            include_legacy: Include runs without meta.json (legacy runs).
            include_examples: Include curated example runs from swarm/examples/.

        Returns:
            List of run summaries, sorted by creation time (newest first),
            with examples sorted first.
        """
        summaries: List[RunSummary] = []
        seen_ids: set[str] = set()

        # Include example runs first (for teaching mode prioritization)
        if include_examples:
            for rid in storage.discover_example_runs():
                if rid in seen_ids:
                    continue
                summary = self._create_legacy_summary(rid, is_example=True)
                if summary:
                    if flow_key is None or flow_key in summary.spec.flow_keys:
                        summaries.append(summary)
                        seen_ids.add(rid)

        # Get runs from storage (new-style with meta.json)
        for rid in storage.list_runs():
            if rid in seen_ids:
                continue
            summary = storage.read_summary(rid)
            if summary:
                if flow_key is None or flow_key in summary.spec.flow_keys:
                    summaries.append(summary)
                    seen_ids.add(rid)

        # Include legacy runs if requested
        if include_legacy:
            for rid in storage.discover_legacy_runs():
                if rid in seen_ids:
                    continue
                # Create minimal summary for legacy runs
                summary = self._create_legacy_summary(rid, is_example=False)
                if summary:
                    if flow_key is None or flow_key in summary.spec.flow_keys:
                        summaries.append(summary)
                        seen_ids.add(rid)

        # Sort: examples first (by created_at), then others by created_at desc
        def sort_key(s: RunSummary) -> tuple:
            is_example = "example" in s.tags
            return (0 if is_example else 1, -s.created_at.timestamp())

        summaries.sort(key=sort_key)
        return summaries

    def _create_legacy_summary(
        self,
        run_id: RunId,
        is_example: bool = False,
    ) -> Optional[RunSummary]:
        """Create a summary for a legacy run (no meta.json).

        Args:
            run_id: The run identifier.
            is_example: If True, look in examples/ dir; otherwise runs/ dir.

        Returns:
            RunSummary if valid run found, None otherwise.
        """
        from datetime import datetime, timezone

        # Determine correct path based on type
        if is_example:
            run_path = EXAMPLES_DIR / run_id
        else:
            run_path = storage.get_run_path(run_id)

        if not run_path.exists():
            return None

        # Detect which flows have artifacts (from registry, includes review)
        flow_keys = []
        for flow_dir in get_flow_order():
            if (run_path / flow_dir).exists():
                flow_keys.append(flow_dir)

        if not flow_keys:
            return None

        # Use directory mtime as creation time
        try:
            mtime = run_path.stat().st_mtime
            created_at = datetime.fromtimestamp(mtime, tz=timezone.utc)
        except Exception:
            created_at = datetime.now(timezone.utc)

        # Build tags based on run type
        tags = ["example"] if is_example else ["legacy"]

        # Check for run.json metadata (old-style)
        run_json_path = run_path / "run.json"
        title = None
        description = None
        if run_json_path.exists():
            try:
                import json

                with open(run_json_path) as f:
                    meta = json.load(f)
                title = meta.get("title")
                description = meta.get("description")
                extra_tags = meta.get("tags", [])
                tags.extend(extra_tags)
            except Exception as e:
                logger.warning("Failed to read legacy run metadata for %s: %s", run_id, e)

        return RunSummary(
            id=run_id,
            spec=RunSpec(
                flow_keys=flow_keys,
                profile_id=None,
                backend="claude-harness",
                initiator="example" if is_example else "legacy",
            ),
            status=RunStatus.SUCCEEDED,  # Assume completed
            sdlc_status=SDLCStatus.UNKNOWN,
            created_at=created_at,
            updated_at=created_at,
            completed_at=created_at,
            tags=tags,
            title=title,
            path=str(run_path),
            description=description,
        )

    def get_events(self, run_id: RunId) -> List[RunEvent]:
        """Get all events for a run."""
        return storage.read_events(run_id)

    # =========================================================================
    # Teaching / Exemplar Management
    # =========================================================================

    def mark_exemplar(self, run_id: RunId, is_exemplar: bool = True) -> bool:
        """Mark or unmark a run as an exemplar.

        Exemplar runs are highlighted in teaching mode.
        """
        summary = self.get_run(run_id)
        if not summary:
            return False

        storage.update_summary(run_id, {"is_exemplar": is_exemplar})
        return True

    def add_tag(self, run_id: RunId, tag: str) -> bool:
        """Add a tag to a run."""
        summary = self.get_run(run_id)
        if not summary:
            return False

        tags = list(summary.tags)
        if tag not in tags:
            tags.append(tag)
            storage.update_summary(run_id, {"tags": tags})
        return True

    def remove_tag(self, run_id: RunId, tag: str) -> bool:
        """Remove a tag from a run."""
        summary = self.get_run(run_id)
        if not summary:
            return False

        tags = [t for t in summary.tags if t != tag]
        storage.update_summary(run_id, {"tags": tags})
        return True

    def list_exemplars(self) -> List[RunSummary]:
        """List all exemplar runs (for teaching mode)."""
        return [s for s in self.list_runs() if s.is_exemplar]


# Module-level convenience function
def get_run_service() -> RunService:
    """Get the RunService singleton instance."""
    return RunService.get_instance()
