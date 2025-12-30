"""
resilient_db.py - Resilient DuckDB wrapper for Flow Studio API.

This module provides a resilient layer over StatsDB that:
1. Automatically checks and rebuilds the DB from events.jsonl on startup
2. Detects DB file deletion and triggers rebuild
3. Wraps all DB operations to never crash the API (500 errors from DB issues)
4. Enforces single-writer pattern (kernel writes JSONL, tailer owns DB writes)

Design Philosophy:
    - The events.jsonl is the append-only journal (authoritative ledger)
    - The DuckDB is a projection/cache that can be deleted and rebuilt
    - The API should never return 500 due to DB issues
    - If DB is unavailable, return empty results with appropriate metadata

Usage:
    from swarm.runtime.resilient_db import get_resilient_db

    db = get_resilient_db()
    stats = db.get_run_stats_safe(run_id)  # Never raises, returns None on error
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, TypeVar

from . import storage as storage_module
from .db import (
    PROJECTION_VERSION,
    Fact,
    RoutingDecisionRecord,
    RunStats,
    StatsDB,
    StepStats,
    ToolBreakdown,
    close_stats_db,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")


@dataclass
class DBHealthStatus:
    """Health status of the database."""

    healthy: bool
    projection_version: int = PROJECTION_VERSION
    last_check: Optional[datetime] = None
    last_rebuild: Optional[datetime] = None
    rebuild_count: int = 0
    error_count: int = 0
    last_error: Optional[str] = None
    db_path: Optional[str] = None
    db_exists: bool = False
    needs_rebuild: bool = False


@dataclass
class ResilientDBConfig:
    """Configuration for resilient database wrapper."""

    db_path: Optional[Path] = None
    auto_rebuild: bool = True
    health_check_interval_sec: float = 30.0
    max_consecutive_errors: int = 5
    rebuild_on_error: bool = True
    runs_dir: Optional[Path] = None


class ResilientStatsDB:
    """Resilient wrapper around StatsDB.

    Provides:
    - Automatic schema version checking and rebuild on startup
    - Detection of DB file deletion and auto-rebuild
    - Error handling that never crashes the API
    - Health monitoring and status reporting

    All query methods have _safe variants that never raise exceptions.
    """

    def __init__(self, config: Optional[ResilientDBConfig] = None):
        """Initialize the resilient database wrapper.

        Args:
            config: Configuration options. If None, uses defaults.
        """
        self.config = config or ResilientDBConfig()
        self._db: Optional[StatsDB] = None
        self._lock = threading.RLock()
        self._health = DBHealthStatus(healthy=False)
        self._consecutive_errors = 0
        self._initialized = False
        self._shutdown = False

        # Resolve paths
        if self.config.db_path is None:
            self.config.db_path = Path("swarm/runs/.stats.duckdb")
        if self.config.runs_dir is None:
            self.config.runs_dir = storage_module.RUNS_DIR

        self._health.db_path = str(self.config.db_path)

    def initialize(self) -> DBHealthStatus:
        """Initialize the database, checking version and rebuilding if needed.

        This should be called once on application startup. It:
        1. Checks if the DB file exists
        2. Verifies the projection version matches
        3. Triggers rebuild from events.jsonl if needed
        4. Sets the healthy flag

        Returns:
            Current health status after initialization.
        """
        with self._lock:
            if self._initialized:
                return self._health

            try:
                logger.info(
                    "Initializing resilient DB at %s (projection_version=%d)",
                    self.config.db_path,
                    PROJECTION_VERSION,
                )

                # Create StatsDB instance directly (not using global singleton)
                # This allows better control for testing and isolation
                self._db = StatsDB(self.config.db_path)

                # Trigger connection to perform version check
                _ = self._db.connection

                # Check if DB file exists
                self._health.db_exists = (
                    self.config.db_path.exists() if self.config.db_path else True
                )

                # Check rebuild status
                if self.config.auto_rebuild and self._db.needs_rebuild:
                    self._health.needs_rebuild = True
                    logger.info("DB needs rebuild, triggering from events.jsonl...")
                    self._trigger_rebuild()

                self._health.healthy = True
                self._health.last_check = datetime.now(timezone.utc)
                self._initialized = True
                self._consecutive_errors = 0

                logger.info(
                    "Resilient DB initialized successfully (healthy=%s, rebuild_count=%d)",
                    self._health.healthy,
                    self._health.rebuild_count,
                )

            except Exception as e:
                logger.error("Failed to initialize resilient DB: %s", e)
                self._health.healthy = False
                self._health.last_error = str(e)
                self._health.error_count += 1

            return self._health

    def _trigger_rebuild(self) -> Dict[str, Any]:
        """Trigger a rebuild of the database from events.jsonl.

        Returns:
            Dict with rebuild statistics including:
            - success: bool indicating if rebuild succeeded
            - runs_processed: total runs attempted
            - runs_succeeded: runs that succeeded
            - events_ingested: total events ingested
            - errors: list of error dicts
        """
        try:
            if self._db is None:
                return {
                    "success": False,
                    "runs_processed": 0,
                    "runs_succeeded": 0,
                    "events_ingested": 0,
                    "errors": [{"error": "DB not initialized"}],
                }

            logger.info("Starting DB rebuild from events.jsonl...")
            stats = self._db.rebuild_all_from_events(runs_dir=self.config.runs_dir)

            self._health.rebuild_count += 1
            self._health.last_rebuild = datetime.now(timezone.utc)
            self._health.needs_rebuild = False

            runs_succeeded = stats.get("runs_succeeded", 0)
            events_ingested = stats.get("events_ingested", 0)
            errors = stats.get("errors", [])

            logger.info(
                "DB rebuild complete: %d runs, %d events, %d errors",
                runs_succeeded,
                events_ingested,
                len(errors),
            )

            return {
                "success": len(errors) == 0,
                "runs_processed": stats.get("runs_processed", runs_succeeded),
                "runs_succeeded": runs_succeeded,
                "events_ingested": events_ingested,
                "errors": errors,
            }

        except Exception as e:
            logger.error("DB rebuild failed: %s", e)
            self._health.last_error = str(e)
            self._health.error_count += 1
            return {
                "success": False,
                "runs_processed": 0,
                "runs_succeeded": 0,
                "events_ingested": 0,
                "errors": [{"error": str(e)}],
            }

    def check_health(self) -> DBHealthStatus:
        """Check database health and trigger rebuild if needed.

        This method:
        1. Checks if the DB file still exists
        2. If deleted, triggers auto-rebuild
        3. Updates health status

        Returns:
            Current health status.
        """
        with self._lock:
            try:
                # Check if DB file was deleted
                if self.config.db_path and not self.config.db_path.exists():
                    logger.warning(
                        "DB file deleted at %s, triggering rebuild...", self.config.db_path
                    )
                    self._health.db_exists = False
                    self._health.needs_rebuild = True

                    # Close existing connection if any
                    if self._db:
                        try:
                            self._db.close()
                        except Exception:
                            pass
                    self._db = None
                    self._initialized = False

                    # Re-initialize (will create new DB and rebuild)
                    return self.initialize()

                self._health.db_exists = True
                self._health.last_check = datetime.now(timezone.utc)
                self._consecutive_errors = 0

            except Exception as e:
                logger.error("Health check failed: %s", e)
                self._health.last_error = str(e)
                self._health.error_count += 1
                self._consecutive_errors += 1

                # If too many consecutive errors, mark unhealthy
                if self._consecutive_errors >= self.config.max_consecutive_errors:
                    self._health.healthy = False

            return self._health

    def _safe_operation(
        self,
        operation: Callable[[], T],
        operation_name: str,
        default: T,
    ) -> T:
        """Execute a database operation safely, returning default on error.

        Args:
            operation: Callable that performs the DB operation.
            operation_name: Name for logging.
            default: Default value to return on error.

        Returns:
            Result of operation, or default on error.
        """
        if not self._initialized:
            self.initialize()

        try:
            return operation()
        except Exception as e:
            logger.warning("DB operation '%s' failed (returning default): %s", operation_name, e)
            self._health.error_count += 1
            self._health.last_error = str(e)
            self._consecutive_errors += 1

            # Check if we need to rebuild
            if self.config.rebuild_on_error and self._consecutive_errors >= 3:
                logger.info("Multiple consecutive errors, checking health...")
                self.check_health()

            return default

    # =========================================================================
    # Safe Query Methods (never raise exceptions)
    # =========================================================================

    def get_run_stats_safe(self, run_id: str) -> Optional[RunStats]:
        """Get run statistics safely, returning None on error."""
        return self._safe_operation(
            lambda: self._db.get_run_stats(run_id) if self._db else None,
            f"get_run_stats({run_id})",
            None,
        )

    def get_step_stats_safe(self, run_id: str) -> List[StepStats]:
        """Get step statistics safely, returning empty list on error."""
        return self._safe_operation(
            lambda: self._db.get_step_stats(run_id) if self._db else [],
            f"get_step_stats({run_id})",
            [],
        )

    def get_tool_breakdown_safe(self, run_id: str) -> List[ToolBreakdown]:
        """Get tool breakdown safely, returning empty list on error."""
        return self._safe_operation(
            lambda: self._db.get_tool_breakdown(run_id) if self._db else [],
            f"get_tool_breakdown({run_id})",
            [],
        )

    def get_recent_runs_safe(self, limit: int = 20) -> List[RunStats]:
        """Get recent runs safely, returning empty list on error."""
        return self._safe_operation(
            lambda: self._db.get_recent_runs(limit) if self._db else [],
            f"get_recent_runs({limit})",
            [],
        )

    def get_file_changes_safe(self, run_id: str) -> List[Dict[str, Any]]:
        """Get file changes safely, returning empty list on error."""
        return self._safe_operation(
            lambda: self._db.get_file_changes(run_id) if self._db else [],
            f"get_file_changes({run_id})",
            [],
        )

    def get_facts_for_run_safe(self, run_id: str) -> List[Fact]:
        """Get facts for a run safely, returning empty list on error."""
        return self._safe_operation(
            lambda: self._db.get_facts_for_run(run_id) if self._db else [],
            f"get_facts_for_run({run_id})",
            [],
        )

    def get_facts_by_marker_type_safe(self, run_id: str, marker_type: str) -> List[Fact]:
        """Get facts by marker type safely, returning empty list on error."""
        return self._safe_operation(
            lambda: self._db.get_facts_by_marker_type(run_id, marker_type) if self._db else [],
            f"get_facts_by_marker_type({run_id}, {marker_type})",
            [],
        )

    def get_routing_decisions_safe(self, run_id: str) -> List[RoutingDecisionRecord]:
        """Get routing decisions for a run safely, returning empty list on error."""
        return self._safe_operation(
            lambda: self._db.get_routing_decisions(run_id) if self._db else [],
            f"get_routing_decisions({run_id})",
            [],
        )

    def get_routing_decisions_by_flow_safe(
        self, run_id: str, flow_id: str
    ) -> List[RoutingDecisionRecord]:
        """Get routing decisions for a flow safely, returning empty list on error."""
        return self._safe_operation(
            lambda: self._db.get_routing_decisions_by_flow(run_id, flow_id) if self._db else [],
            f"get_routing_decisions_by_flow({run_id}, {flow_id})",
            [],
        )

    def get_routing_decision_summary_safe(self, run_id: str) -> Dict[str, Any]:
        """Get routing decision summary safely, returning empty dict on error."""
        return self._safe_operation(
            lambda: self._db.get_routing_decision_summary(run_id)
            if self._db
            else {
                "total_decisions": 0,
                "by_decision": {},
                "by_routing_mode": {},
                "by_routing_source": {},
                "needs_human_count": 0,
                "terminations": 0,
            },
            f"get_routing_decision_summary({run_id})",
            {
                "total_decisions": 0,
                "by_decision": {},
                "by_routing_mode": {},
                "by_routing_source": {},
                "needs_human_count": 0,
                "terminations": 0,
            },
        )

    # =========================================================================
    # Write Methods (delegate to underlying DB)
    # =========================================================================

    def ingest_events_safe(self, events: List[Dict[str, Any]], run_id: str) -> int:
        """Ingest events safely, returning 0 on error."""
        return self._safe_operation(
            lambda: self._db.ingest_events(events, run_id) if self._db else 0,
            f"ingest_events({run_id})",
            0,
        )

    def rebuild_from_events_safe(self, run_id: str) -> Dict[str, Any]:
        """Rebuild projection for a run safely."""
        return self._safe_operation(
            lambda: self._db.rebuild_from_events(run_id, self.config.runs_dir)
            if self._db
            else {"success": False, "error": "DB not initialized"},
            f"rebuild_from_events({run_id})",
            {"success": False, "error": "Operation failed"},
        )

    def rebuild_all_safe(self) -> Dict[str, Any]:
        """Rebuild projection for all runs safely.

        This method provides a safe wrapper around the full database rebuild,
        updating health status and returning detailed statistics.

        Returns:
            Dict with rebuild statistics including runs_processed, runs_succeeded,
            events_ingested, and any errors encountered.
        """
        if not self._initialized:
            self.initialize()

        try:
            if self._db is None:
                return {
                    "success": False,
                    "runs_processed": 0,
                    "runs_succeeded": 0,
                    "events_ingested": 0,
                    "errors": [{"error": "DB not initialized"}],
                }

            # _trigger_rebuild now returns detailed stats
            return self._trigger_rebuild()

        except Exception as e:
            logger.error("Failed to rebuild all: %s", e)
            self._health.error_count += 1
            self._health.last_error = str(e)
            return {
                "success": False,
                "runs_processed": 0,
                "runs_succeeded": 0,
                "events_ingested": 0,
                "errors": [{"error": str(e)}],
            }

    # =========================================================================
    # Raw DB Access (for when you need full control)
    # =========================================================================

    @property
    def db(self) -> Optional[StatsDB]:
        """Get the underlying StatsDB instance.

        Returns None if not initialized. Use this when you need to call
        methods not wrapped by the safe variants.
        """
        if not self._initialized:
            self.initialize()
        return self._db

    @property
    def health(self) -> DBHealthStatus:
        """Get current health status."""
        return self._health

    def close(self) -> None:
        """Close the database connection."""
        with self._lock:
            self._shutdown = True
            if self._db:
                self._db.close()
                self._db = None
            close_stats_db()
            self._initialized = False
            self._health.healthy = False


# =============================================================================
# Global Instance (Singleton Pattern)
# =============================================================================

_global_resilient_db: Optional[ResilientStatsDB] = None
_global_resilient_db_lock = threading.Lock()


def get_resilient_db(config: Optional[ResilientDBConfig] = None) -> ResilientStatsDB:
    """Get the global ResilientStatsDB instance.

    Creates and initializes a new instance if one doesn't exist.

    Args:
        config: Optional configuration. Only used on first call.

    Returns:
        The ResilientStatsDB instance.
    """
    global _global_resilient_db

    with _global_resilient_db_lock:
        if _global_resilient_db is None:
            _global_resilient_db = ResilientStatsDB(config)
            _global_resilient_db.initialize()

        return _global_resilient_db


def close_resilient_db() -> None:
    """Close the global ResilientStatsDB instance."""
    global _global_resilient_db

    with _global_resilient_db_lock:
        if _global_resilient_db is not None:
            _global_resilient_db.close()
            _global_resilient_db = None


def check_db_health() -> DBHealthStatus:
    """Check the health of the global database.

    This can be called periodically to detect DB deletion and
    trigger auto-rebuild.

    Returns:
        Current health status.
    """
    db = get_resilient_db()
    return db.check_health()


# =============================================================================
# API Integration Helpers
# =============================================================================


def db_health_response() -> Dict[str, Any]:
    """Get database health as an API response dictionary.

    Returns:
        Dict suitable for JSON serialization with health info.
    """
    health = check_db_health()
    return {
        "db_healthy": health.healthy,
        "db_exists": health.db_exists,
        "projection_version": health.projection_version,
        "rebuild_count": health.rebuild_count,
        "error_count": health.error_count,
        "last_error": health.last_error,
        "last_check": health.last_check.isoformat() if health.last_check else None,
        "last_rebuild": health.last_rebuild.isoformat() if health.last_rebuild else None,
    }
