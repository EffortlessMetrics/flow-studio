"""
db.py - DuckDB-based stats and telemetry storage for Flow Studio.

This module provides a high-performance local database for storing:
- Run metadata and status
- Step execution telemetry
- Tool call statistics
- File change tracking

Design Philosophy:
    - The orchestrator writes to events.jsonl (append-only, crash-safe)
    - This module mirrors events.jsonl into DuckDB for fast queries
    - TypeScript UI queries DuckDB via a small API, not JSONL parsing
    - DuckDB is ephemeral/rebuildable from events.jsonl if needed

Usage:
    from swarm.runtime.db import StatsDB

    db = StatsDB(db_path)
    db.record_step_start(run_id, flow_key, step_id, agent_key)
    db.record_tool_call(run_id, step_id, tool_name, duration_ms, success)
    db.record_step_end(run_id, step_id, status, tokens, routing_signal)

    # Query for UI
    stats = db.get_run_stats(run_id)
    tool_breakdown = db.get_tool_breakdown(run_id)
"""

from __future__ import annotations

import json
import logging
import os
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

logger = logging.getLogger(__name__)

# =============================================================================
# Projection-Only Mode
# =============================================================================
# When enabled, direct record_* calls are no-ops. Only ingest_events() should
# mutate projection tables. This ensures DuckDB is a pure projection of
# events.jsonl, fully rebuildable from disk.
#
# Configuration is evaluated at StatsDB construction time, not import time,
# allowing tests to set env vars after import and before creating the instance.

# Thread-local flag to indicate we're inside ingest_events()
# When True, record_* calls are allowed even in projection-only mode
_ingestion_context = threading.local()


def _is_in_ingestion_context() -> bool:
    """Check if we're currently inside ingest_events()."""
    return getattr(_ingestion_context, "active", False)


# =============================================================================
# Event Kind Canonicalization
# =============================================================================
# Canonical event kinds and aliases for backwards compatibility.
# The alias map rewrites legacy names to canonical during ingestion.
#
# Canonical names follow the pattern: {entity}_{action}
#   - run_created, run_started, run_completed
#   - step_start, step_end
#   - tool_start, tool_end
#   - file_changes, route_decision

# Canonical event kinds (the "truth" names)
CANONICAL_EVENT_KINDS = frozenset(
    {
        # Run lifecycle
        "run_created",
        "run_started",
        "run_completed",
        "run_stop_requested",
        # Step lifecycle
        "step_start",
        "step_end",
        # Tool lifecycle
        "tool_start",
        "tool_end",
        # Data events
        "file_changes",
        "route_decision",
    }
)

# Alias map: legacy_name -> canonical_name
# Entries map to canonical names; missing keys mean name is already canonical
EVENT_KIND_ALIASES: Dict[str, str] = {
    # Run aliases
    "run_start": "run_started",
    "run_end": "run_completed",
    "run_cancelled": "run_completed",  # Status indicates actual outcome
    "run_failed": "run_completed",  # Status indicates actual outcome
    # Step aliases
    "step_complete": "step_end",
    "step_error": "step_end",  # Status indicates actual outcome
}


def normalize_event_kind(kind: str) -> str:
    """Normalize an event kind to its canonical form.

    Args:
        kind: The event kind string (may be legacy alias).

    Returns:
        The canonical event kind.
    """
    return EVENT_KIND_ALIASES.get(kind, kind)


# Lazy import to avoid hard dependency at module load time
_duckdb = None


def _get_duckdb():
    """Lazy import of duckdb module."""
    global _duckdb
    if _duckdb is None:
        try:
            import duckdb

            _duckdb = duckdb
        except ImportError:
            logger.warning("DuckDB not available - stats will not be persisted")
            return None
    return _duckdb


def _check_projection_version(db_path: Path) -> bool:
    """Check if the projection version matches and handle mismatch.

    This function implements the schema resilience pattern:
    1. Open the existing DB (if any) and read _projection_meta.projection_version
    2. If version matches PROJECTION_VERSION, return True (DB is compatible)
    3. If version mismatches or DB doesn't exist, rename old DB and return False

    The caller is responsible for rebuilding from events.jsonl when this returns False.

    Args:
        db_path: Path to the DuckDB file.

    Returns:
        True if DB is compatible and can be used as-is.
        False if DB was renamed/missing and needs rebuild.
    """
    duckdb = _get_duckdb()
    if duckdb is None:
        return False

    if not db_path.exists():
        logger.debug("No existing DB at %s, will create fresh", db_path)
        return False

    # Try to read the projection version from existing DB
    try:
        conn = duckdb.connect(str(db_path), read_only=True)
        try:
            # Check if _projection_meta table exists
            result = conn.execute(
                "SELECT COUNT(*) FROM information_schema.tables "
                "WHERE table_name = '_projection_meta'"
            ).fetchone()

            if result[0] == 0:
                # Table doesn't exist - old schema, needs rebuild
                logger.info("DB at %s missing _projection_meta table, will rebuild", db_path)
                conn.close()
                _rename_old_db(db_path)
                return False

            # Read version
            result = conn.execute(
                "SELECT value FROM _projection_meta WHERE key = 'projection_version'"
            ).fetchone()

            if result is None:
                logger.info("DB at %s missing projection_version, will rebuild", db_path)
                conn.close()
                _rename_old_db(db_path)
                return False

            stored_version = int(result[0])
            if stored_version != PROJECTION_VERSION:
                logger.info(
                    "Projection version mismatch: DB has v%d, code expects v%d. Rebuilding.",
                    stored_version,
                    PROJECTION_VERSION,
                )
                conn.close()
                _rename_old_db(db_path)
                return False

            # Version matches, DB is compatible
            conn.close()
            return True

        except Exception as e:
            logger.warning("Error reading projection version from %s: %s", db_path, e)
            try:
                conn.close()
            except Exception:
                pass
            _rename_old_db(db_path)
            return False

    except Exception as e:
        logger.warning("Error opening DB at %s: %s", db_path, e)
        _rename_old_db(db_path)
        return False


def _rename_old_db(db_path: Path) -> None:
    """Rename old DB file to stats.db.old.<timestamp>.

    Args:
        db_path: Path to the DuckDB file to rename.
    """
    if not db_path.exists():
        return

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    old_path = db_path.parent / f"{db_path.name}.old.{timestamp}"

    try:
        db_path.rename(old_path)
        logger.info("Renamed old DB to %s", old_path)
    except OSError as e:
        logger.warning("Failed to rename old DB %s: %s", db_path, e)
        # Try to delete if rename failed
        try:
            db_path.unlink()
            logger.info("Deleted old DB at %s", db_path)
        except OSError as e2:
            logger.error("Failed to delete old DB %s: %s", db_path, e2)


def _set_projection_version(conn, version: int) -> None:
    """Store the projection version in _projection_meta.

    Args:
        conn: Active DuckDB connection.
        version: The projection version to store.
    """
    conn.execute(
        """
        INSERT INTO _projection_meta (key, value, updated_at)
        VALUES ('projection_version', ?, now())
        ON CONFLICT (key) DO UPDATE SET
            value = excluded.value,
            updated_at = excluded.updated_at
    """,
        [str(version)],
    )


# =============================================================================
# Schema Definitions
# =============================================================================

SCHEMA_VERSION = 2

# =============================================================================
# Projection Version (Schema Resilience)
# =============================================================================
# The projection version tracks breaking changes to the DuckDB projection layer.
# Unlike SCHEMA_VERSION (which is stored in the DB and used for migrations),
# PROJECTION_VERSION is used to detect when a full rebuild from events.jsonl
# is required.
#
# Increment this when:
# - Adding new tables that need data from existing events
# - Changing column types in ways that require re-ingestion
# - Modifying how events are projected into tables
#
# DO NOT increment for:
# - Adding new indexes (additive, non-breaking)
# - Adding nullable columns with defaults (additive, non-breaking)
#
# When PROJECTION_VERSION mismatches the stored version in _projection_meta:
# 1. The old DB file is renamed to stats.db.old.<timestamp>
# 2. A fresh DB is created with the new version
# 3. Data is rebuilt from events.jsonl (empty projection if no events exist)

PROJECTION_VERSION = 2

CREATE_TABLES_SQL = """
-- Schema version tracking
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Projection version tracking (for schema resilience / rebuild-from-events)
CREATE TABLE IF NOT EXISTS _projection_meta (
    key VARCHAR PRIMARY KEY,
    value VARCHAR NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Runs table: one row per run
CREATE TABLE IF NOT EXISTS runs (
    run_id VARCHAR PRIMARY KEY,
    flow_keys VARCHAR[],  -- Array of flow keys executed
    profile_id VARCHAR,
    engine_id VARCHAR,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    status VARCHAR,  -- running, succeeded, failed, cancelled
    total_steps INTEGER DEFAULT 0,
    completed_steps INTEGER DEFAULT 0,
    total_tokens INTEGER DEFAULT 0,
    total_duration_ms INTEGER DEFAULT 0,
    metadata JSON
);

-- Steps table: one row per step execution
CREATE SEQUENCE IF NOT EXISTS steps_id_seq;
CREATE TABLE IF NOT EXISTS steps (
    id INTEGER PRIMARY KEY DEFAULT nextval('steps_id_seq'),
    run_id VARCHAR NOT NULL,
    flow_key VARCHAR NOT NULL,
    step_id VARCHAR NOT NULL,
    step_index INTEGER,
    agent_key VARCHAR,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    status VARCHAR,  -- running, succeeded, failed, skipped
    duration_ms INTEGER DEFAULT 0,
    prompt_tokens INTEGER DEFAULT 0,
    completion_tokens INTEGER DEFAULT 0,
    total_tokens INTEGER DEFAULT 0,
    handoff_status VARCHAR,  -- VERIFIED, UNVERIFIED, PARTIAL, BLOCKED
    routing_decision VARCHAR,  -- advance, loop, terminate, branch
    routing_next_step VARCHAR,
    routing_confidence FLOAT,
    error_message VARCHAR,
    UNIQUE(run_id, flow_key, step_id, started_at)
);

-- Tool calls table: one row per tool invocation
CREATE SEQUENCE IF NOT EXISTS tool_calls_id_seq;
CREATE TABLE IF NOT EXISTS tool_calls (
    id INTEGER PRIMARY KEY DEFAULT nextval('tool_calls_id_seq'),
    run_id VARCHAR NOT NULL,
    step_id VARCHAR NOT NULL,
    tool_name VARCHAR NOT NULL,
    phase VARCHAR,  -- work, finalization, routing
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    duration_ms INTEGER DEFAULT 0,
    success BOOLEAN DEFAULT TRUE,
    target_path VARCHAR,  -- For file operations
    diff_lines_added INTEGER,
    diff_lines_removed INTEGER,
    exit_code INTEGER,  -- For bash operations
    error_message VARCHAR
);

-- File changes table: aggregated file modifications per step
CREATE SEQUENCE IF NOT EXISTS file_changes_id_seq;
CREATE TABLE IF NOT EXISTS file_changes (
    id INTEGER PRIMARY KEY DEFAULT nextval('file_changes_id_seq'),
    run_id VARCHAR NOT NULL,
    step_id VARCHAR NOT NULL,
    file_path VARCHAR NOT NULL,
    change_type VARCHAR,  -- created, modified, deleted
    lines_added INTEGER DEFAULT 0,
    lines_removed INTEGER DEFAULT 0,
    timestamp TIMESTAMP,
    UNIQUE(run_id, step_id, file_path)
);

-- Create indexes for common queries
CREATE INDEX IF NOT EXISTS idx_steps_run_id ON steps(run_id);
CREATE INDEX IF NOT EXISTS idx_steps_flow_step ON steps(flow_key, step_id);
CREATE INDEX IF NOT EXISTS idx_tool_calls_run_id ON tool_calls(run_id);
CREATE INDEX IF NOT EXISTS idx_tool_calls_step_id ON tool_calls(step_id);
CREATE INDEX IF NOT EXISTS idx_file_changes_run_id ON file_changes(run_id);

-- Events table: raw event storage for idempotent ingestion
CREATE TABLE IF NOT EXISTS events (
    event_id VARCHAR PRIMARY KEY,
    seq INTEGER NOT NULL,
    run_id VARCHAR NOT NULL,
    ts TIMESTAMP NOT NULL,
    kind VARCHAR NOT NULL,
    flow_key VARCHAR NOT NULL,
    step_id VARCHAR,
    agent_key VARCHAR,
    payload JSON,
    ingested_at TIMESTAMP DEFAULT (now())
);

CREATE INDEX IF NOT EXISTS idx_events_run_seq ON events(run_id, seq);
CREATE INDEX IF NOT EXISTS idx_events_run_kind ON events(run_id, kind);

-- Ingestion state table: offset tracking for incremental ingestion
CREATE TABLE IF NOT EXISTS ingestion_state (
    run_id VARCHAR PRIMARY KEY,
    last_offset INTEGER NOT NULL DEFAULT 0,
    last_seq INTEGER NOT NULL DEFAULT 0,
    updated_at TIMESTAMP DEFAULT (now())
);

-- Facts table: inventory marker extraction (REQ_*, SOL_*, TRC_*, etc.)
CREATE SEQUENCE IF NOT EXISTS facts_id_seq;
CREATE TABLE IF NOT EXISTS facts (
    id INTEGER PRIMARY KEY DEFAULT nextval('facts_id_seq'),
    fact_id VARCHAR UNIQUE,
    run_id VARCHAR NOT NULL,
    step_id VARCHAR NOT NULL,
    flow_key VARCHAR NOT NULL,
    agent_key VARCHAR,
    marker_type VARCHAR,  -- REQ, SOL, TRC, ASM, DEC, etc.
    marker_id VARCHAR,    -- e.g., REQ_001
    fact_type VARCHAR,    -- requirement, solution, trace, assumption, decision
    content TEXT,
    priority VARCHAR,     -- MUST, SHOULD, NICE_TO_HAVE
    status VARCHAR,       -- verified, unverified, deprecated
    evidence TEXT,
    created_at TIMESTAMP,
    extracted_at TIMESTAMP DEFAULT (now()),
    metadata JSON,
    UNIQUE(run_id, step_id, marker_id)
);

CREATE INDEX IF NOT EXISTS idx_facts_run_id ON facts(run_id);
CREATE INDEX IF NOT EXISTS idx_facts_marker_type ON facts(run_id, marker_type);
CREATE INDEX IF NOT EXISTS idx_facts_marker_id ON facts(marker_id);

-- Routing decisions table: one row per routing decision after each step
CREATE SEQUENCE IF NOT EXISTS routing_decisions_id_seq;
CREATE TABLE IF NOT EXISTS routing_decisions (
    id INTEGER PRIMARY KEY DEFAULT nextval('routing_decisions_id_seq'),
    run_id VARCHAR NOT NULL,
    step_seq INTEGER NOT NULL,  -- Sequence number within the run
    flow_id VARCHAR NOT NULL,
    station_id VARCHAR NOT NULL,  -- Step/node that made the decision
    routing_mode VARCHAR,  -- deterministic, llm_tiebreak, etc.
    routing_source VARCHAR,  -- navigator/fast_path/deterministic_fallback
    chosen_candidate_id VARCHAR,  -- Selected edge ID
    candidate_count INTEGER DEFAULT 0,  -- Number of candidate edges evaluated
    decision VARCHAR NOT NULL,  -- advance/loop/repeat/detour/terminate/escalate
    target_node VARCHAR,  -- Next node to execute (nullable for terminate)
    timestamp TIMESTAMP NOT NULL,
    terminate BOOLEAN DEFAULT FALSE,  -- Whether flow should terminate
    needs_human BOOLEAN DEFAULT FALSE,  -- Whether human review is recommended
    explanation JSON,  -- Full structured explanation for audit trail
    UNIQUE(run_id, step_seq, station_id, timestamp)
);

CREATE INDEX IF NOT EXISTS idx_routing_decisions_run_id ON routing_decisions(run_id);
CREATE INDEX IF NOT EXISTS idx_routing_decisions_flow ON routing_decisions(run_id, flow_id);
CREATE INDEX IF NOT EXISTS idx_routing_decisions_station ON routing_decisions(station_id);
CREATE INDEX IF NOT EXISTS idx_routing_decisions_decision ON routing_decisions(decision);
"""


# =============================================================================
# Data Classes for Type Safety
# =============================================================================


@dataclass
class RunStats:
    """Aggregated statistics for a run."""

    run_id: str
    flow_keys: List[str]
    status: str
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    total_steps: int
    completed_steps: int
    total_tokens: int
    total_duration_ms: int
    tool_call_count: int = 0
    file_change_count: int = 0


@dataclass
class StepStats:
    """Statistics for a single step."""

    step_id: str
    flow_key: str
    agent_key: Optional[str]
    status: str
    duration_ms: int
    total_tokens: int
    handoff_status: Optional[str]
    routing_decision: Optional[str]
    tool_calls: int = 0


@dataclass
class ToolBreakdown:
    """Breakdown of tool usage."""

    tool_name: str
    call_count: int
    total_duration_ms: int
    success_rate: float
    avg_duration_ms: float


@dataclass
class Fact:
    """A structured fact extracted from agent output (inventory marker).

    Facts represent requirements, solutions, traces, assumptions, and decisions
    extracted from agent outputs using REQ_*, SOL_*, TRC_*, ASM_*, DEC_* markers.
    """

    fact_id: str
    run_id: str
    step_id: str
    flow_key: str
    agent_key: Optional[str]
    marker_type: str  # REQ, SOL, TRC, ASM, DEC
    marker_id: str  # e.g., REQ_001
    fact_type: str  # requirement, solution, trace, assumption, decision
    content: str
    priority: Optional[str] = None  # MUST, SHOULD, NICE_TO_HAVE
    status: Optional[str] = None  # verified, unverified, deprecated
    evidence: Optional[str] = None
    created_at: Optional[datetime] = None
    extracted_at: Optional[datetime] = None
    metadata: Optional[Dict[str, Any]] = field(default_factory=dict)


@dataclass
class RoutingDecisionRecord:
    """A routing decision record for UI queries.

    Captures the routing decision made after each step execution,
    including the method used, candidates evaluated, and the chosen path.
    """

    run_id: str
    step_seq: int
    flow_id: str
    station_id: str
    routing_mode: Optional[str]  # deterministic, llm_tiebreak, etc.
    routing_source: Optional[str]  # navigator/fast_path/deterministic_fallback
    chosen_candidate_id: Optional[str]  # Selected edge ID
    candidate_count: int
    decision: str  # advance/loop/repeat/detour/terminate/escalate
    target_node: Optional[str]  # Next node to execute
    timestamp: datetime
    terminate: bool = False
    needs_human: bool = False
    explanation: Optional[Dict[str, Any]] = None


# =============================================================================
# StatsDB Class
# =============================================================================


class StatsDB:
    """DuckDB-backed statistics database for Flow Studio.

    Thread-safe wrapper around DuckDB for recording and querying
    execution statistics. Supports concurrent writes from multiple
    step executions.

    Attributes:
        db_path: Path to the DuckDB database file.
        connection: Active DuckDB connection (lazy initialized).
    """

    def __init__(
        self,
        db_path: Optional[Path] = None,
        projection_only: Optional[bool] = None,
        projection_strict: Optional[bool] = None,
    ):
        """Initialize the stats database.

        Args:
            db_path: Path to the DuckDB file. If None, uses in-memory database.
            projection_only: If True, direct record_* calls are no-ops.
                Defaults to SWARM_DB_PROJECTION_ONLY env var (default: true).
            projection_strict: If True, direct record_* calls raise RuntimeError.
                Defaults to SWARM_DB_PROJECTION_STRICT env var (default: false).
        """
        self.db_path = db_path
        self._connection = None
        self._lock = threading.RLock()
        self._initialized = False
        self._version_checked = False
        self._needs_rebuild = False

        # Capture projection config at construction time (not import time)
        # This allows tests to set env vars after import but before construction
        if projection_only is None:
            projection_only = os.environ.get("SWARM_DB_PROJECTION_ONLY", "true").lower() == "true"
        if projection_strict is None:
            projection_strict = (
                os.environ.get("SWARM_DB_PROJECTION_STRICT", "false").lower() == "true"
            )

        self._projection_only = projection_only
        self._projection_strict = projection_strict

    def _projection_guard(self, method_name: str) -> bool:
        """Check if direct projection writes are allowed.

        In projection-only mode, direct record_* calls are skipped (or raise in
        strict mode). This ensures all DB state comes from event ingestion.

        Calls from within ingest_events() are always allowed.

        Args:
            method_name: Name of the calling method for logging.

        Returns:
            True if write should proceed, False if should be skipped.

        Raises:
            RuntimeError: In strict mode when direct writes are attempted.
        """
        # Always allow calls from ingestion context
        if _is_in_ingestion_context():
            return True

        if not self._projection_only:
            return True  # Legacy mode, allow direct writes

        if self._projection_strict:
            raise RuntimeError(
                f"Direct DB write via {method_name}() blocked in projection-only mode. "
                "Use event emission + ingest_events() instead. "
                "Set SWARM_DB_PROJECTION_ONLY=false to disable this check."
            )

        logger.debug("Projection-only mode: skipping direct %s() call", method_name)
        return False

    @property
    def connection(self):
        """Get or create the DuckDB connection.

        On first access, performs projection version check. If the stored version
        doesn't match PROJECTION_VERSION, the old DB is renamed and a fresh one
        is created. The _needs_rebuild flag is set to signal that the caller
        should rebuild from events.jsonl.
        """
        if self._connection is None:
            duckdb = _get_duckdb()
            if duckdb is None:
                return None

            with self._lock:
                if self._connection is None:
                    if self.db_path:
                        # Check projection version before connecting
                        if not self._version_checked:
                            self._version_checked = True
                            is_compatible = _check_projection_version(self.db_path)
                            if not is_compatible:
                                self._needs_rebuild = True
                                logger.info(
                                    "Projection version mismatch or missing DB. "
                                    "Will rebuild from events.jsonl."
                                )

                        self.db_path.parent.mkdir(parents=True, exist_ok=True)
                        self._connection = duckdb.connect(str(self.db_path))
                    else:
                        self._connection = duckdb.connect(":memory:")

                    if not self._initialized:
                        self._init_schema()
                        self._initialized = True

        return self._connection

    def _init_schema(self):
        """Initialize the database schema."""
        if self.connection is None:
            return

        with self._lock:
            self.connection.execute(CREATE_TABLES_SQL)

            # Check/set schema version
            result = self.connection.execute(
                "SELECT version FROM schema_version ORDER BY version DESC LIMIT 1"
            ).fetchone()

            if result is None:
                self.connection.execute(
                    "INSERT INTO schema_version (version) VALUES (?)", [SCHEMA_VERSION]
                )

            # Set projection version (for schema resilience)
            _set_projection_version(self.connection, PROJECTION_VERSION)

            logger.debug(
                "StatsDB schema initialized (schema_version=%d, projection_version=%d)",
                SCHEMA_VERSION,
                PROJECTION_VERSION,
            )

    @contextmanager
    def _transaction(self) -> Iterator[Any]:
        """Context manager for database operations.

        DuckDB auto-commits by default, so we just need locking for thread safety.
        """
        if self.connection is None:
            yield None
            return

        with self._lock:
            try:
                yield self.connection
            except Exception as e:
                logger.warning("Database operation failed: %s", e)
                raise

    def close(self):
        """Close the database connection."""
        if self._connection is not None:
            with self._lock:
                self._connection.close()
                self._connection = None

    # =========================================================================
    # Raw Event Storage (Idempotent)
    # =========================================================================

    def _insert_raw_event(self, event: Dict[str, Any]) -> bool:
        """Insert raw event if not already present. Returns True if inserted."""
        try:
            # Use RETURNING to detect if insert happened (empty result = conflict/no insert)
            result = self.connection.execute(
                """
                INSERT INTO events (event_id, seq, run_id, ts, kind, flow_key, step_id, agent_key, payload)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (event_id) DO NOTHING
                RETURNING event_id
            """,
                [
                    event.get("event_id"),
                    event.get("seq", 0),
                    event["run_id"],
                    event["ts"],
                    event["kind"],
                    event["flow_key"],
                    event.get("step_id"),
                    event.get("agent_key"),
                    json.dumps(event.get("payload", {})),
                ],
            )
            return len(result.fetchall()) > 0
        except Exception as e:
            logger.warning(f"Failed to insert event {event.get('event_id')}: {e}")
            return False

    def get_ingestion_offset(self, run_id: str) -> Tuple[int, int]:
        """Get (byte_offset, last_seq) for incremental ingestion."""
        if self.connection is None:
            return (0, 0)

        with self._lock:
            result = self.connection.execute(
                "SELECT last_offset, last_seq FROM ingestion_state WHERE run_id = ?", [run_id]
            ).fetchone()
            return (result[0], result[1]) if result else (0, 0)

    def set_ingestion_offset(self, run_id: str, offset: int, seq: int) -> None:
        """Update ingestion offset after successful tail."""
        if self.connection is None:
            return

        with self._lock:
            self.connection.execute(
                """
                INSERT INTO ingestion_state (run_id, last_offset, last_seq, updated_at)
                VALUES (?, ?, ?, now())
                ON CONFLICT (run_id) DO UPDATE SET
                    last_offset = excluded.last_offset,
                    last_seq = excluded.last_seq,
                    updated_at = excluded.updated_at
            """,
                [run_id, offset, seq],
            )

    # =========================================================================
    # Write Operations
    # =========================================================================

    def record_run_start(
        self,
        run_id: str,
        flow_keys: List[str],
        profile_id: Optional[str] = None,
        engine_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        ts: Optional[datetime] = None,
    ):
        """Record the start of a new run.

        Note: In projection-only mode, this is a no-op. Use event emission
        + ingest_events() instead.

        Args:
            ts: Optional timestamp from event. If None, uses current time.
                For replay/rebuild, always pass the event timestamp.
        """
        if self.connection is None:
            return
        if not self._projection_guard("record_run_start"):
            return

        started_at = ts if ts is not None else datetime.now(timezone.utc)
        with self._transaction() as conn:
            conn.execute(
                """
                INSERT INTO runs (run_id, flow_keys, profile_id, engine_id, started_at, status, metadata)
                VALUES (?, ?, ?, ?, ?, 'running', ?)
                ON CONFLICT (run_id) DO UPDATE SET
                    flow_keys = EXCLUDED.flow_keys,
                    started_at = EXCLUDED.started_at,
                    status = 'running'
                """,
                [run_id, flow_keys, profile_id, engine_id, started_at, json.dumps(metadata or {})],
            )

    def record_run_end(
        self,
        run_id: str,
        status: str,
        total_steps: int,
        completed_steps: int,
        total_tokens: int,
        total_duration_ms: int,
        ts: Optional[datetime] = None,
    ):
        """Record the completion of a run.

        Note: In projection-only mode, this is a no-op. Use event emission
        + ingest_events() instead.

        Args:
            ts: Optional timestamp from event. If None, uses current time.
        """
        if self.connection is None:
            return
        if not self._projection_guard("record_run_end"):
            return

        completed_at = ts if ts is not None else datetime.now(timezone.utc)
        with self._transaction() as conn:
            conn.execute(
                """
                UPDATE runs SET
                    completed_at = ?,
                    status = ?,
                    total_steps = ?,
                    completed_steps = ?,
                    total_tokens = ?,
                    total_duration_ms = ?
                WHERE run_id = ?
                """,
                [
                    completed_at,
                    status,
                    total_steps,
                    completed_steps,
                    total_tokens,
                    total_duration_ms,
                    run_id,
                ],
            )

    def record_step_start(
        self,
        run_id: str,
        flow_key: str,
        step_id: str,
        step_index: int,
        agent_key: Optional[str] = None,
        ts: Optional[datetime] = None,
    ):
        """Record the start of a step execution.

        Note: In projection-only mode, this is a no-op. Use event emission
        + ingest_events() instead.

        Args:
            ts: Optional timestamp from event. If None, uses current time.
        """
        if self.connection is None:
            return
        if not self._projection_guard("record_step_start"):
            return

        started_at = ts if ts is not None else datetime.now(timezone.utc)
        with self._transaction() as conn:
            conn.execute(
                """
                INSERT INTO steps (run_id, flow_key, step_id, step_index, agent_key, started_at, status)
                VALUES (?, ?, ?, ?, ?, ?, 'running')
                """,
                [run_id, flow_key, step_id, step_index, agent_key, started_at],
            )

    def record_step_end(
        self,
        run_id: str,
        flow_key: str,
        step_id: str,
        status: str,
        duration_ms: int,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        handoff_status: Optional[str] = None,
        routing_decision: Optional[str] = None,
        routing_next_step: Optional[str] = None,
        routing_confidence: Optional[float] = None,
        error_message: Optional[str] = None,
        ts: Optional[datetime] = None,
    ):
        """Record the completion of a step execution.

        Note: In projection-only mode, this is a no-op. Use event emission
        + ingest_events() instead.

        Args:
            ts: Optional timestamp from event. If None, uses current time.
        """
        if self.connection is None:
            return
        if not self._projection_guard("record_step_end"):
            return

        completed_at = ts if ts is not None else datetime.now(timezone.utc)
        with self._transaction() as conn:
            conn.execute(
                """
                UPDATE steps SET
                    completed_at = ?,
                    status = ?,
                    duration_ms = ?,
                    prompt_tokens = ?,
                    completion_tokens = ?,
                    total_tokens = ?,
                    handoff_status = ?,
                    routing_decision = ?,
                    routing_next_step = ?,
                    routing_confidence = ?,
                    error_message = ?
                WHERE run_id = ? AND flow_key = ? AND step_id = ? AND status = 'running'
                """,
                [
                    completed_at,
                    status,
                    duration_ms,
                    prompt_tokens,
                    completion_tokens,
                    prompt_tokens + completion_tokens,
                    handoff_status,
                    routing_decision,
                    routing_next_step,
                    routing_confidence,
                    error_message,
                    run_id,
                    flow_key,
                    step_id,
                ],
            )

    def record_tool_call(
        self,
        run_id: str,
        step_id: str,
        tool_name: str,
        phase: str = "work",
        duration_ms: int = 0,
        success: bool = True,
        target_path: Optional[str] = None,
        diff_lines_added: Optional[int] = None,
        diff_lines_removed: Optional[int] = None,
        exit_code: Optional[int] = None,
        error_message: Optional[str] = None,
        ts: Optional[datetime] = None,
    ):
        """Record a tool call.

        Note: In projection-only mode, this is a no-op. Use event emission
        + ingest_events() instead.

        Args:
            ts: Optional timestamp from event. If None, uses current time.
        """
        if self.connection is None:
            return
        if not self._projection_guard("record_tool_call"):
            return

        tool_ts = ts if ts is not None else datetime.now(timezone.utc)
        with self._transaction() as conn:
            conn.execute(
                """
                INSERT INTO tool_calls (
                    run_id, step_id, tool_name, phase, started_at, completed_at,
                    duration_ms, success, target_path, diff_lines_added, diff_lines_removed,
                    exit_code, error_message
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    run_id,
                    step_id,
                    tool_name,
                    phase,
                    tool_ts,
                    tool_ts,
                    duration_ms,
                    success,
                    target_path,
                    diff_lines_added,
                    diff_lines_removed,
                    exit_code,
                    error_message,
                ],
            )

    def record_file_change(
        self,
        run_id: str,
        step_id: str,
        file_path: str,
        change_type: str,
        lines_added: int = 0,
        lines_removed: int = 0,
        ts: Optional[datetime] = None,
    ):
        """Record a file change.

        Note: In projection-only mode, this is a no-op. Use event emission
        + ingest_events() instead.

        Args:
            ts: Optional timestamp from event. If None, uses current time.
        """
        if self.connection is None:
            return
        if not self._projection_guard("record_file_change"):
            return

        change_ts = ts if ts is not None else datetime.now(timezone.utc)
        with self._transaction() as conn:
            conn.execute(
                """
                INSERT INTO file_changes (run_id, step_id, file_path, change_type, lines_added, lines_removed, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (run_id, step_id, file_path) DO UPDATE SET
                    change_type = EXCLUDED.change_type,
                    lines_added = file_changes.lines_added + EXCLUDED.lines_added,
                    lines_removed = file_changes.lines_removed + EXCLUDED.lines_removed
                """,
                [run_id, step_id, file_path, change_type, lines_added, lines_removed, change_ts],
            )

    def record_routing_decision(
        self,
        run_id: str,
        step_seq: int,
        flow_id: str,
        station_id: str,
        decision: str,
        routing_mode: Optional[str] = None,
        routing_source: Optional[str] = None,
        chosen_candidate_id: Optional[str] = None,
        candidate_count: int = 0,
        target_node: Optional[str] = None,
        terminate: bool = False,
        needs_human: bool = False,
        explanation: Optional[Dict[str, Any]] = None,
        ts: Optional[datetime] = None,
    ):
        """Record a routing decision.

        Captures the routing decision made after a step execution for
        audit trail and UI visualization.

        Note: In projection-only mode, this is a no-op. Use event emission
        + ingest_events() instead.

        Args:
            run_id: The run this decision belongs to.
            step_seq: Sequence number of the step within the run.
            flow_id: The flow key (signal, plan, build, etc.).
            station_id: The step/node that made the decision.
            decision: The routing decision (advance/loop/repeat/detour/terminate/escalate).
            routing_mode: How the decision was made (deterministic, llm_tiebreak, etc.).
            routing_source: Source of the routing (navigator/fast_path/deterministic_fallback).
            chosen_candidate_id: The selected edge ID.
            candidate_count: Number of candidate edges evaluated.
            target_node: The next node to execute (None for terminate).
            terminate: Whether the flow should terminate.
            needs_human: Whether human review is recommended.
            explanation: Full structured explanation for audit trail.
            ts: Optional timestamp from event. If None, uses current time.
        """
        if self.connection is None:
            return
        if not self._projection_guard("record_routing_decision"):
            return

        decision_ts = ts if ts is not None else datetime.now(timezone.utc)
        with self._transaction() as conn:
            conn.execute(
                """
                INSERT INTO routing_decisions (
                    run_id, step_seq, flow_id, station_id, routing_mode, routing_source,
                    chosen_candidate_id, candidate_count, decision, target_node,
                    timestamp, terminate, needs_human, explanation
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (run_id, step_seq, station_id, timestamp) DO UPDATE SET
                    routing_mode = EXCLUDED.routing_mode,
                    routing_source = EXCLUDED.routing_source,
                    chosen_candidate_id = EXCLUDED.chosen_candidate_id,
                    candidate_count = EXCLUDED.candidate_count,
                    decision = EXCLUDED.decision,
                    target_node = EXCLUDED.target_node,
                    terminate = EXCLUDED.terminate,
                    needs_human = EXCLUDED.needs_human,
                    explanation = EXCLUDED.explanation
                """,
                [
                    run_id,
                    step_seq,
                    flow_id,
                    station_id,
                    routing_mode,
                    routing_source,
                    chosen_candidate_id,
                    candidate_count,
                    decision,
                    target_node,
                    decision_ts,
                    terminate,
                    needs_human,
                    json.dumps(explanation) if explanation else None,
                ],
            )

    def ingest_fact(
        self,
        run_id: str,
        step_id: str,
        flow_key: str,
        marker_type: str,
        marker_id: str,
        fact_type: str,
        content: str,
        agent_key: Optional[str] = None,
        priority: Optional[str] = None,
        status: Optional[str] = None,
        evidence: Optional[str] = None,
        created_at: Optional[datetime] = None,
        metadata: Optional[Dict[str, Any]] = None,
        ts: Optional[datetime] = None,
    ) -> Optional[str]:
        """Ingest a fact (inventory marker) into the facts table.

        Facts represent structured information extracted from agent outputs
        using markers like REQ_001, SOL_002, TRC_003, ASM_001, DEC_001.

        Note: In projection-only mode, this is a no-op unless called from
        within ingest_events() context.

        Args:
            run_id: The run this fact belongs to.
            step_id: The step that produced this fact.
            flow_key: The flow (signal, plan, build, gate, deploy, wisdom).
            marker_type: The marker prefix (REQ, SOL, TRC, ASM, DEC, etc.).
            marker_id: The full marker ID (e.g., REQ_001).
            fact_type: Human-readable type (requirement, solution, trace, etc.).
            content: The fact content/description.
            agent_key: The agent that produced this fact.
            priority: Priority level (MUST, SHOULD, NICE_TO_HAVE).
            status: Fact status (verified, unverified, deprecated).
            evidence: Supporting evidence or references.
            created_at: When the fact was originally created.
            metadata: Additional structured metadata.
            ts: Timestamp for extraction (defaults to now).

        Returns:
            The generated fact_id if successful, None otherwise.
        """
        if self.connection is None:
            return None
        if not self._projection_guard("ingest_fact"):
            return None

        import uuid

        fact_id = f"fact_{uuid.uuid4().hex[:12]}"
        extracted_at = ts if ts is not None else datetime.now(timezone.utc)

        with self._transaction() as conn:
            try:
                conn.execute(
                    """
                    INSERT INTO facts (
                        fact_id, run_id, step_id, flow_key, agent_key,
                        marker_type, marker_id, fact_type, content,
                        priority, status, evidence, created_at, extracted_at, metadata
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT (run_id, step_id, marker_id) DO UPDATE SET
                        content = EXCLUDED.content,
                        priority = EXCLUDED.priority,
                        status = EXCLUDED.status,
                        evidence = EXCLUDED.evidence,
                        metadata = EXCLUDED.metadata,
                        extracted_at = EXCLUDED.extracted_at
                    """,
                    [
                        fact_id,
                        run_id,
                        step_id,
                        flow_key,
                        agent_key,
                        marker_type,
                        marker_id,
                        fact_type,
                        content,
                        priority,
                        status,
                        evidence,
                        created_at,
                        extracted_at,
                        json.dumps(metadata or {}),
                    ],
                )
                return fact_id
            except Exception as e:
                logger.warning("Failed to ingest fact %s: %s", marker_id, e)
                return None

    # =========================================================================
    # Batch Operations
    # =========================================================================

    def ingest_events(self, events: List[Dict[str, Any]], run_id: str) -> int:
        """Batch ingest events from events.jsonl format (idempotent).

        This is the primary interface for the event sink pattern.
        First inserts raw events into the events table (dedup by event_id),
        then updates projections (runs, steps, tool_calls, file_changes).

        This method sets the ingestion context flag, allowing internal
        record_* calls to proceed even in projection-only mode.

        Args:
            events: List of event dicts (from events.jsonl).
            run_id: The run ID these events belong to.

        Returns:
            Number of newly ingested events (events that were not already present).
        """
        if self.connection is None:
            return 0

        # Set ingestion context to allow record_* calls
        _ingestion_context.active = True
        try:
            return self._ingest_events_internal(events, run_id)
        finally:
            _ingestion_context.active = False

    def _parse_event_ts(self, ts_str: Any) -> Optional[datetime]:
        """Parse event timestamp string to datetime.

        Args:
            ts_str: ISO format timestamp string, datetime, or None.

        Returns:
            Parsed datetime in UTC, or None if parsing fails.
        """
        if ts_str is None:
            return None
        if isinstance(ts_str, datetime):
            return ts_str
        if not isinstance(ts_str, str):
            return None

        try:
            # Handle ISO format with or without timezone
            if ts_str.endswith("Z"):
                ts_str = ts_str[:-1] + "+00:00"
            dt = datetime.fromisoformat(ts_str)
            # Ensure UTC timezone
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except (ValueError, TypeError):
            return None

    def _ingest_events_internal(self, events: List[Dict[str, Any]], run_id: str) -> int:
        """Internal implementation of ingest_events."""
        newly_ingested = 0

        for event in events:
            # Ensure run_id is set on the event for raw storage
            event_with_run = {**event, "run_id": run_id}

            # Insert raw event first (idempotent - skips if event_id exists)
            if not self._insert_raw_event(event_with_run):
                # Event already exists, skip projection updates
                continue

            newly_ingested += 1

            # Parse event timestamp - CRITICAL: use event's ts, not "now"
            # This ensures replays and rebuilds produce identical projections
            event_ts = self._parse_event_ts(event.get("ts"))

            # Normalize event kind to canonical form (handles legacy aliases)
            raw_kind = event.get("kind", "")
            kind = normalize_event_kind(raw_kind)
            payload = event.get("payload", {})
            step_id = event.get("step_id", "")
            flow_key = event.get("flow_key", "")

            if kind == "step_start":
                self.record_step_start(
                    run_id=run_id,
                    flow_key=flow_key,
                    step_id=step_id,
                    step_index=payload.get("step_index", 0),
                    agent_key=payload.get("agent_key"),
                    ts=event_ts,
                )

            elif kind == "step_end":  # Canonical: step_complete/step_error -> step_end
                self.record_step_end(
                    run_id=run_id,
                    flow_key=flow_key,
                    step_id=step_id,
                    status=payload.get("status", "succeeded"),
                    duration_ms=payload.get("duration_ms", 0),
                    prompt_tokens=payload.get("prompt_tokens", 0),
                    completion_tokens=payload.get("completion_tokens", 0),
                    handoff_status=payload.get("handoff_status"),
                    routing_decision=payload.get("routing_decision"),
                    routing_next_step=payload.get("routing_next_step"),
                    routing_confidence=payload.get("routing_confidence"),
                    error_message=payload.get("error"),
                    ts=event_ts,
                )

            elif kind == "tool_start":
                # We'll update on tool_end
                pass

            elif kind == "tool_end":
                self.record_tool_call(
                    run_id=run_id,
                    step_id=step_id,
                    tool_name=payload.get("tool", "unknown"),
                    phase=payload.get("phase", "work"),
                    duration_ms=payload.get("duration_ms", 0),
                    success=payload.get("success", True),
                    target_path=payload.get("target_path"),
                    diff_lines_added=payload.get("diff_lines_added"),
                    diff_lines_removed=payload.get("diff_lines_removed"),
                    exit_code=payload.get("exit_code"),
                    error_message=payload.get("error"),
                    ts=event_ts,
                )

            elif kind == "file_changes":
                # File changes from DiffScanner (forensic truth)
                files = payload.get("files", [])
                for fc in files:
                    self.record_file_change(
                        run_id=run_id,
                        step_id=step_id,
                        file_path=fc.get("path", ""),
                        change_type=fc.get("status", "modified"),
                        lines_added=fc.get("insertions", 0),
                        lines_removed=fc.get("deletions", 0),
                        ts=event_ts,
                    )

            elif kind == "route_decision":
                # Routing decisions from the router/navigator
                # Extract explanation if present (may contain nested elimination_log, metrics)
                explanation = payload.get("explanation")

                # Map the method field to routing_mode
                method = payload.get("method", "")
                routing_mode = method if method else None

                # Determine routing_source based on method
                # - "deterministic" -> "fast_path" or "deterministic_fallback"
                # - "llm_tiebreak" -> "navigator"
                # - "no_candidates" -> "deterministic_fallback"
                routing_source = None
                if method == "deterministic":
                    routing_source = "fast_path"
                elif method == "llm_tiebreak":
                    routing_source = "navigator"
                elif method == "no_candidates":
                    routing_source = "deterministic_fallback"

                # Extract candidate count from explanation if available
                candidate_count = 0
                if explanation and isinstance(explanation, dict):
                    candidate_count = explanation.get("candidates_evaluated", 0)

                # Derive decision from method and terminate flag
                terminate = payload.get("terminate", False)
                decision = "terminate" if terminate else "advance"
                if method == "llm_tiebreak":
                    decision = "advance"  # LLM chose a path to advance

                self.record_routing_decision(
                    run_id=run_id,
                    step_seq=event.get("seq", 0),
                    flow_id=flow_key,
                    station_id=step_id,
                    decision=decision,
                    routing_mode=routing_mode,
                    routing_source=routing_source,
                    chosen_candidate_id=payload.get("selected_edge"),
                    candidate_count=candidate_count,
                    target_node=payload.get("target_node"),
                    terminate=terminate,
                    needs_human=payload.get("needs_human", False),
                    explanation=explanation,
                    ts=event_ts,
                )

            elif kind == "run_started":  # Canonical: run_start -> run_started
                # Run initialization
                flow_keys = payload.get("flow_keys", [])
                self.record_run_start(
                    run_id=run_id,
                    flow_keys=flow_keys,
                    profile_id=payload.get("profile_id"),
                    engine_id=payload.get("engine"),
                    metadata=payload.get("metadata"),
                    ts=event_ts,
                )

            elif kind == "run_completed":
                # Run completion
                self.record_run_end(
                    run_id=run_id,
                    status=payload.get("status", "completed"),
                    total_steps=payload.get("total_steps", 0),
                    completed_steps=payload.get("steps_completed", 0),
                    total_tokens=payload.get("total_tokens", 0),
                    total_duration_ms=payload.get("duration_ms", 0),
                    ts=event_ts,
                )

        return newly_ingested

    # =========================================================================
    # Query Operations (for TypeScript UI)
    # =========================================================================

    def get_run_stats(self, run_id: str) -> Optional[RunStats]:
        """Get aggregated statistics for a run."""
        if self.connection is None:
            return None

        with self._lock:
            result = self.connection.execute(
                """
                SELECT
                    r.run_id,
                    r.flow_keys,
                    r.status,
                    r.started_at,
                    r.completed_at,
                    r.total_steps,
                    r.completed_steps,
                    r.total_tokens,
                    r.total_duration_ms,
                    (SELECT COUNT(*) FROM tool_calls WHERE run_id = r.run_id) as tool_call_count,
                    (SELECT COUNT(*) FROM file_changes WHERE run_id = r.run_id) as file_change_count
                FROM runs r
                WHERE r.run_id = ?
                """,
                [run_id],
            ).fetchone()

            if result is None:
                return None

            return RunStats(
                run_id=result[0],
                flow_keys=result[1] or [],
                status=result[2],
                started_at=result[3],
                completed_at=result[4],
                total_steps=result[5] or 0,
                completed_steps=result[6] or 0,
                total_tokens=result[7] or 0,
                total_duration_ms=result[8] or 0,
                tool_call_count=result[9] or 0,
                file_change_count=result[10] or 0,
            )

    def get_step_stats(self, run_id: str) -> List[StepStats]:
        """Get statistics for all steps in a run."""
        if self.connection is None:
            return []

        with self._lock:
            results = self.connection.execute(
                """
                SELECT
                    s.step_id,
                    s.flow_key,
                    s.agent_key,
                    s.status,
                    s.duration_ms,
                    s.total_tokens,
                    s.handoff_status,
                    s.routing_decision,
                    (SELECT COUNT(*) FROM tool_calls WHERE run_id = s.run_id AND step_id = s.step_id) as tool_calls
                FROM steps s
                WHERE s.run_id = ?
                ORDER BY s.step_index
                """,
                [run_id],
            ).fetchall()

            return [
                StepStats(
                    step_id=row[0],
                    flow_key=row[1],
                    agent_key=row[2],
                    status=row[3],
                    duration_ms=row[4] or 0,
                    total_tokens=row[5] or 0,
                    handoff_status=row[6],
                    routing_decision=row[7],
                    tool_calls=row[8] or 0,
                )
                for row in results
            ]

    def get_tool_breakdown(self, run_id: str) -> List[ToolBreakdown]:
        """Get breakdown of tool usage for a run."""
        if self.connection is None:
            return []

        with self._lock:
            results = self.connection.execute(
                """
                SELECT
                    tool_name,
                    COUNT(*) as call_count,
                    SUM(duration_ms) as total_duration_ms,
                    AVG(CASE WHEN success THEN 1.0 ELSE 0.0 END) as success_rate,
                    AVG(duration_ms) as avg_duration_ms
                FROM tool_calls
                WHERE run_id = ?
                GROUP BY tool_name
                ORDER BY call_count DESC
                """,
                [run_id],
            ).fetchall()

            return [
                ToolBreakdown(
                    tool_name=row[0],
                    call_count=row[1],
                    total_duration_ms=row[2] or 0,
                    success_rate=row[3] or 1.0,
                    avg_duration_ms=row[4] or 0.0,
                )
                for row in results
            ]

    def get_recent_runs(self, limit: int = 20) -> List[RunStats]:
        """Get recent runs for the UI dashboard."""
        if self.connection is None:
            return []

        with self._lock:
            results = self.connection.execute(
                """
                SELECT
                    r.run_id,
                    r.flow_keys,
                    r.status,
                    r.started_at,
                    r.completed_at,
                    r.total_steps,
                    r.completed_steps,
                    r.total_tokens,
                    r.total_duration_ms,
                    (SELECT COUNT(*) FROM tool_calls WHERE run_id = r.run_id) as tool_call_count,
                    (SELECT COUNT(*) FROM file_changes WHERE run_id = r.run_id) as file_change_count
                FROM runs r
                ORDER BY r.started_at DESC
                LIMIT ?
                """,
                [limit],
            ).fetchall()

            return [
                RunStats(
                    run_id=row[0],
                    flow_keys=row[1] or [],
                    status=row[2],
                    started_at=row[3],
                    completed_at=row[4],
                    total_steps=row[5] or 0,
                    completed_steps=row[6] or 0,
                    total_tokens=row[7] or 0,
                    total_duration_ms=row[8] or 0,
                    tool_call_count=row[9] or 0,
                    file_change_count=row[10] or 0,
                )
                for row in results
            ]

    def get_file_changes(self, run_id: str) -> List[Dict[str, Any]]:
        """Get file changes for a run."""
        if self.connection is None:
            return []

        with self._lock:
            results = self.connection.execute(
                """
                SELECT file_path, change_type, lines_added, lines_removed, step_id, timestamp
                FROM file_changes
                WHERE run_id = ?
                ORDER BY timestamp
                """,
                [run_id],
            ).fetchall()

            return [
                {
                    "file_path": row[0],
                    "change_type": row[1],
                    "lines_added": row[2],
                    "lines_removed": row[3],
                    "step_id": row[4],
                    "timestamp": row[5].isoformat() if row[5] else None,
                }
                for row in results
            ]

    def get_facts_for_run(self, run_id: str) -> List[Fact]:
        """Get all facts extracted for a run.

        Args:
            run_id: The run ID to query.

        Returns:
            List of Fact objects for the run, ordered by step_id and marker_id.
        """
        if self.connection is None:
            return []

        with self._lock:
            results = self.connection.execute(
                """
                SELECT
                    fact_id, run_id, step_id, flow_key, agent_key,
                    marker_type, marker_id, fact_type, content,
                    priority, status, evidence, created_at, extracted_at, metadata
                FROM facts
                WHERE run_id = ?
                ORDER BY step_id, marker_id
                """,
                [run_id],
            ).fetchall()

            return [
                Fact(
                    fact_id=row[0],
                    run_id=row[1],
                    step_id=row[2],
                    flow_key=row[3],
                    agent_key=row[4],
                    marker_type=row[5],
                    marker_id=row[6],
                    fact_type=row[7],
                    content=row[8],
                    priority=row[9],
                    status=row[10],
                    evidence=row[11],
                    created_at=row[12],
                    extracted_at=row[13],
                    metadata=json.loads(row[14]) if row[14] else {},
                )
                for row in results
            ]

    def get_facts_by_marker_type(self, run_id: str, marker_type: str) -> List[Fact]:
        """Get facts for a run filtered by marker type.

        Args:
            run_id: The run ID to query.
            marker_type: The marker type to filter by (REQ, SOL, TRC, ASM, DEC, etc.).

        Returns:
            List of Fact objects matching the marker type, ordered by marker_id.
        """
        if self.connection is None:
            return []

        with self._lock:
            results = self.connection.execute(
                """
                SELECT
                    fact_id, run_id, step_id, flow_key, agent_key,
                    marker_type, marker_id, fact_type, content,
                    priority, status, evidence, created_at, extracted_at, metadata
                FROM facts
                WHERE run_id = ? AND marker_type = ?
                ORDER BY marker_id
                """,
                [run_id, marker_type],
            ).fetchall()

            return [
                Fact(
                    fact_id=row[0],
                    run_id=row[1],
                    step_id=row[2],
                    flow_key=row[3],
                    agent_key=row[4],
                    marker_type=row[5],
                    marker_id=row[6],
                    fact_type=row[7],
                    content=row[8],
                    priority=row[9],
                    status=row[10],
                    evidence=row[11],
                    created_at=row[12],
                    extracted_at=row[13],
                    metadata=json.loads(row[14]) if row[14] else {},
                )
                for row in results
            ]

    def get_routing_decisions(self, run_id: str) -> List[RoutingDecisionRecord]:
        """Get all routing decisions for a run.

        Args:
            run_id: The run ID to query.

        Returns:
            List of RoutingDecisionRecord objects for the run, ordered by step_seq.
        """
        if self.connection is None:
            return []

        with self._lock:
            results = self.connection.execute(
                """
                SELECT
                    run_id, step_seq, flow_id, station_id, routing_mode, routing_source,
                    chosen_candidate_id, candidate_count, decision, target_node,
                    timestamp, terminate, needs_human, explanation
                FROM routing_decisions
                WHERE run_id = ?
                ORDER BY step_seq, timestamp
                """,
                [run_id],
            ).fetchall()

            return [
                RoutingDecisionRecord(
                    run_id=row[0],
                    step_seq=row[1],
                    flow_id=row[2],
                    station_id=row[3],
                    routing_mode=row[4],
                    routing_source=row[5],
                    chosen_candidate_id=row[6],
                    candidate_count=row[7] or 0,
                    decision=row[8],
                    target_node=row[9],
                    timestamp=row[10],
                    terminate=row[11] or False,
                    needs_human=row[12] or False,
                    explanation=json.loads(row[13]) if row[13] else None,
                )
                for row in results
            ]

    def get_routing_decisions_by_flow(
        self, run_id: str, flow_id: str
    ) -> List[RoutingDecisionRecord]:
        """Get routing decisions for a specific flow within a run.

        Args:
            run_id: The run ID to query.
            flow_id: The flow ID to filter by (signal, plan, build, etc.).

        Returns:
            List of RoutingDecisionRecord objects for the flow, ordered by step_seq.
        """
        if self.connection is None:
            return []

        with self._lock:
            results = self.connection.execute(
                """
                SELECT
                    run_id, step_seq, flow_id, station_id, routing_mode, routing_source,
                    chosen_candidate_id, candidate_count, decision, target_node,
                    timestamp, terminate, needs_human, explanation
                FROM routing_decisions
                WHERE run_id = ? AND flow_id = ?
                ORDER BY step_seq, timestamp
                """,
                [run_id, flow_id],
            ).fetchall()

            return [
                RoutingDecisionRecord(
                    run_id=row[0],
                    step_seq=row[1],
                    flow_id=row[2],
                    station_id=row[3],
                    routing_mode=row[4],
                    routing_source=row[5],
                    chosen_candidate_id=row[6],
                    candidate_count=row[7] or 0,
                    decision=row[8],
                    target_node=row[9],
                    timestamp=row[10],
                    terminate=row[11] or False,
                    needs_human=row[12] or False,
                    explanation=json.loads(row[13]) if row[13] else None,
                )
                for row in results
            ]

    def get_routing_decision_summary(self, run_id: str) -> Dict[str, Any]:
        """Get a summary of routing decisions for a run.

        Useful for UI dashboards to show routing statistics at a glance.

        Args:
            run_id: The run ID to query.

        Returns:
            Dict with summary statistics:
            - total_decisions: Total number of routing decisions
            - by_decision: Count by decision type (advance, loop, terminate, etc.)
            - by_routing_mode: Count by routing mode (deterministic, llm_tiebreak, etc.)
            - by_routing_source: Count by routing source (navigator, fast_path, etc.)
            - needs_human_count: Number of decisions flagged for human review
            - terminations: Number of terminate decisions
        """
        if self.connection is None:
            return {
                "total_decisions": 0,
                "by_decision": {},
                "by_routing_mode": {},
                "by_routing_source": {},
                "needs_human_count": 0,
                "terminations": 0,
            }

        with self._lock:
            # Get total and by-decision counts
            total_result = self.connection.execute(
                "SELECT COUNT(*) FROM routing_decisions WHERE run_id = ?",
                [run_id],
            ).fetchone()
            total_decisions = total_result[0] if total_result else 0

            decision_counts = self.connection.execute(
                """
                SELECT decision, COUNT(*) as count
                FROM routing_decisions
                WHERE run_id = ?
                GROUP BY decision
                """,
                [run_id],
            ).fetchall()
            by_decision = {row[0]: row[1] for row in decision_counts}

            mode_counts = self.connection.execute(
                """
                SELECT routing_mode, COUNT(*) as count
                FROM routing_decisions
                WHERE run_id = ? AND routing_mode IS NOT NULL
                GROUP BY routing_mode
                """,
                [run_id],
            ).fetchall()
            by_routing_mode = {row[0]: row[1] for row in mode_counts}

            source_counts = self.connection.execute(
                """
                SELECT routing_source, COUNT(*) as count
                FROM routing_decisions
                WHERE run_id = ? AND routing_source IS NOT NULL
                GROUP BY routing_source
                """,
                [run_id],
            ).fetchall()
            by_routing_source = {row[0]: row[1] for row in source_counts}

            needs_human_result = self.connection.execute(
                "SELECT COUNT(*) FROM routing_decisions WHERE run_id = ? AND needs_human = TRUE",
                [run_id],
            ).fetchone()
            needs_human_count = needs_human_result[0] if needs_human_result else 0

            terminate_result = self.connection.execute(
                "SELECT COUNT(*) FROM routing_decisions WHERE run_id = ? AND terminate = TRUE",
                [run_id],
            ).fetchone()
            terminations = terminate_result[0] if terminate_result else 0

            return {
                "total_decisions": total_decisions,
                "by_decision": by_decision,
                "by_routing_mode": by_routing_mode,
                "by_routing_source": by_routing_source,
                "needs_human_count": needs_human_count,
                "terminations": terminations,
            }

    # =========================================================================
    # Schema Resilience: Rebuild from Events
    # =========================================================================

    def rebuild_from_events(
        self,
        run_id: str,
        runs_dir: Optional[Path] = None,
    ) -> Dict[str, Any]:
        """Rebuild projection for a single run from its events.jsonl.

        This method re-ingests all events from a run's events.jsonl file
        into the DuckDB projection tables. It's used when:
        - Projection version mismatch is detected
        - User requests a rebuild
        - Recovering from corruption

        The events.jsonl is the authoritative ledger; DuckDB is disposable.

        Args:
            run_id: The run ID to rebuild.
            runs_dir: Base directory for runs. Defaults to RUNS_DIR from storage.

        Returns:
            Dict with rebuild statistics:
            - events_ingested: Number of events processed
            - success: True if rebuild completed
            - error: Error message if failed
        """
        from . import storage as storage_module

        if runs_dir is None:
            runs_dir = storage_module.RUNS_DIR

        result = {
            "run_id": run_id,
            "events_ingested": 0,
            "success": False,
            "error": None,
        }

        run_path = runs_dir / run_id
        events_file = run_path / storage_module.EVENTS_FILE

        if not events_file.exists():
            # No events file is fine - empty projection
            logger.debug("No events.jsonl for run %s, projection will be empty", run_id)
            result["success"] = True
            return result

        try:
            # Read and parse events
            events: List[Dict[str, Any]] = []
            with events_file.open("r", encoding="utf-8") as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                        events.append(event)
                    except json.JSONDecodeError as e:
                        logger.warning(
                            "Skipping malformed event at line %d in %s: %s",
                            line_num,
                            events_file,
                            e,
                        )

            if events:
                # Ingest events into DuckDB (idempotent)
                count = self.ingest_events(events, run_id)
                result["events_ingested"] = count
                logger.info("Rebuilt projection for run %s: %d events ingested", run_id, count)

            result["success"] = True

        except Exception as e:
            result["error"] = str(e)
            logger.warning("Failed to rebuild projection for run %s: %s", run_id, e)

        return result

    def rebuild_all_from_events(
        self,
        runs_dir: Optional[Path] = None,
        run_ids: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Rebuild projections for all runs from their events.jsonl files.

        This method scans the runs directory and rebuilds projections for
        each run that has an events.jsonl file. Use this after a projection
        version bump to repopulate the entire database.

        Args:
            runs_dir: Base directory for runs. Defaults to RUNS_DIR from storage.
            run_ids: Optional list of specific run IDs to rebuild.
                     If None, rebuilds all runs found in runs_dir.

        Returns:
            Dict with rebuild statistics:
            - runs_processed: Number of runs processed
            - runs_succeeded: Number of runs successfully rebuilt
            - events_ingested: Total events ingested
            - errors: List of any errors encountered
        """
        from . import storage as storage_module

        if runs_dir is None:
            runs_dir = storage_module.RUNS_DIR

        stats = {
            "runs_processed": 0,
            "runs_succeeded": 0,
            "events_ingested": 0,
            "errors": [],
        }

        # Get list of run IDs to process
        if run_ids is None:
            if not runs_dir.exists():
                logger.warning("Runs directory does not exist: %s", runs_dir)
                return stats

            run_ids = [
                d.name for d in runs_dir.iterdir() if d.is_dir() and not d.name.startswith(".")
            ]

        logger.info("Rebuilding projections for %d runs", len(run_ids))

        for run_id in run_ids:
            result = self.rebuild_from_events(run_id, runs_dir)
            stats["runs_processed"] += 1

            if result["success"]:
                stats["runs_succeeded"] += 1
                stats["events_ingested"] += result["events_ingested"]
            else:
                stats["errors"].append(
                    {
                        "run_id": run_id,
                        "error": result.get("error", "Unknown error"),
                    }
                )

        logger.info(
            "Rebuild complete: %d/%d runs, %d events, %d errors",
            stats["runs_succeeded"],
            stats["runs_processed"],
            stats["events_ingested"],
            len(stats["errors"]),
        )

        # Clear the needs_rebuild flag after successful rebuild
        self._needs_rebuild = False

        return stats

    @property
    def needs_rebuild(self) -> bool:
        """Check if the database needs to be rebuilt from events.jsonl.

        This is set to True when:
        - Projection version mismatch is detected
        - Database was missing and freshly created

        After calling rebuild_all_from_events(), this is set to False.
        """
        return self._needs_rebuild


# =============================================================================
# Global Instance (Singleton Pattern)
# =============================================================================

_global_db: Optional[StatsDB] = None
_global_db_lock = threading.Lock()


def get_stats_db(
    db_path: Optional[Path] = None,
    auto_rebuild: bool = True,
) -> StatsDB:
    """Get the global StatsDB instance.

    Creates a new instance if one doesn't exist, or if a different
    db_path is requested. If the projection version mismatches, the
    old database is renamed and a rebuild from events.jsonl is triggered.

    Args:
        db_path: Path to the DuckDB file. If None, uses default location.
        auto_rebuild: If True (default), automatically rebuild from
            events.jsonl when projection version mismatch is detected.

    Returns:
        The StatsDB instance.
    """
    global _global_db

    with _global_db_lock:
        if _global_db is None:
            if db_path is None:
                # Default to .runs/.stats.duckdb
                db_path = Path("swarm/runs/.stats.duckdb")
            _global_db = StatsDB(db_path)

            # Trigger connection to perform version check
            _ = _global_db.connection

            # Auto-rebuild if needed
            if auto_rebuild and _global_db.needs_rebuild:
                logger.info("Projection version mismatch detected, rebuilding from events.jsonl...")
                stats = _global_db.rebuild_all_from_events()
                logger.info(
                    "Auto-rebuild complete: %d runs, %d events",
                    stats.get("runs_succeeded", 0),
                    stats.get("events_ingested", 0),
                )

        return _global_db


def close_stats_db():
    """Close the global StatsDB instance."""
    global _global_db

    with _global_db_lock:
        if _global_db is not None:
            _global_db.close()
            _global_db = None


# =============================================================================
# Disk-as-Truth Recovery: Rebuild DuckDB from events.jsonl
# =============================================================================


def rebuild_stats_db(
    runs_dir: Optional[Path] = None,
    db_path: Optional[Path] = None,
    run_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Rebuild the DuckDB stats database from disk artifacts.

    This function implements the "disk-as-truth" principle:
    - events.jsonl is the append-only journal (durable, crash-safe)
    - DuckDB is a projection that can be rebuilt at any time

    The rebuild process:
    1. Scan runs_dir for run directories (or use provided run_ids)
    2. For each run, read events.jsonl
    3. Parse events and call ingest_events to populate DuckDB
    4. Read handoff envelopes for additional routing/status data

    Args:
        runs_dir: Path to the runs directory. Defaults to swarm/runs/.
        db_path: Path to the DuckDB file. If None, uses default.
        run_ids: Optional list of specific run IDs to rebuild.
                 If None, rebuilds all runs found in runs_dir.

    Returns:
        Dict with rebuild statistics:
        - runs_processed: Number of runs processed
        - events_ingested: Total events ingested
        - errors: List of any errors encountered
    """
    from . import storage as storage_module

    if runs_dir is None:
        runs_dir = storage_module.RUNS_DIR

    if db_path is None:
        db_path = runs_dir / ".stats.duckdb"

    # Create fresh database (drop existing)
    if db_path.exists():
        logger.info("Removing existing stats database: %s", db_path)
        db_path.unlink()

    db = StatsDB(db_path)

    stats = {
        "runs_processed": 0,
        "events_ingested": 0,
        "envelopes_processed": 0,
        "errors": [],
    }

    # Get list of run IDs to process
    if run_ids is None:
        # Scan runs directory
        if not runs_dir.exists():
            logger.warning("Runs directory does not exist: %s", runs_dir)
            return stats

        run_ids = [d.name for d in runs_dir.iterdir() if d.is_dir() and not d.name.startswith(".")]

    logger.info("Rebuilding stats DB from %d runs", len(run_ids))

    for run_id in run_ids:
        try:
            run_path = runs_dir / run_id
            events_file = run_path / storage_module.EVENTS_FILE

            if not events_file.exists():
                logger.debug("No events.jsonl for run %s, skipping", run_id)
                continue

            # Read and parse events
            events: List[Dict[str, Any]] = []
            with events_file.open("r", encoding="utf-8") as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                        events.append(event)
                    except json.JSONDecodeError as e:
                        stats["errors"].append(
                            {
                                "run_id": run_id,
                                "file": "events.jsonl",
                                "line": line_num,
                                "error": str(e),
                            }
                        )

            if events:
                # Ingest events into DuckDB
                db.ingest_events(events, run_id)
                stats["events_ingested"] += len(events)

            # Also process handoff envelopes for routing info
            # Set ingestion context to allow record_* calls (projection-only mode)
            _ingestion_context.active = True
            try:
                for flow_dir in run_path.iterdir():
                    if not flow_dir.is_dir() or flow_dir.name.startswith("."):
                        continue

                    handoff_dir = flow_dir / "handoff"
                    if not handoff_dir.exists():
                        continue

                    for envelope_file in handoff_dir.glob("*.json"):
                        try:
                            with envelope_file.open("r", encoding="utf-8") as f:
                                envelope_data = json.load(f)

                            # Record file changes from envelope if present
                            file_changes = envelope_data.get("file_changes", {})
                            if file_changes and "files" in file_changes:
                                step_id = envelope_data.get("step_id", envelope_file.stem)
                                for fc in file_changes.get("files", []):
                                    db.record_file_change(
                                        run_id=run_id,
                                        step_id=step_id,
                                        file_path=fc.get("path", ""),
                                        change_type=fc.get("status", "modified"),
                                        lines_added=fc.get("insertions", 0),
                                        lines_removed=fc.get("deletions", 0),
                                    )

                            stats["envelopes_processed"] += 1

                        except (json.JSONDecodeError, IOError) as e:
                            stats["errors"].append(
                                {
                                    "run_id": run_id,
                                    "file": str(envelope_file),
                                    "error": str(e),
                                }
                            )
            finally:
                _ingestion_context.active = False

            stats["runs_processed"] += 1

        except Exception as e:
            logger.warning("Error processing run %s: %s", run_id, e)
            stats["errors"].append(
                {
                    "run_id": run_id,
                    "error": str(e),
                }
            )

    db.close()

    logger.info(
        "Rebuild complete: %d runs, %d events, %d envelopes, %d errors",
        stats["runs_processed"],
        stats["events_ingested"],
        stats["envelopes_processed"],
        len(stats["errors"]),
    )

    return stats


# =============================================================================
# CLI Entry Point
# =============================================================================


def main():
    """CLI entry point for stats database operations.

    Usage:
        python -m swarm.runtime.db rebuild [--runs-dir PATH] [--db-path PATH]
        python -m swarm.runtime.db stats <run_id>
        python -m swarm.runtime.db doctor <run_id> [--strict] [--from-disk]
    """
    import argparse
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="Flow Studio Stats Database CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Rebuild command
    rebuild_parser = subparsers.add_parser(
        "rebuild",
        help="Rebuild DuckDB from events.jsonl (disk-as-truth)",
    )
    rebuild_parser.add_argument(
        "--runs-dir",
        type=Path,
        default=None,
        help="Path to runs directory (default: swarm/runs/)",
    )
    rebuild_parser.add_argument(
        "--db-path",
        type=Path,
        default=None,
        help="Path to DuckDB file (default: <runs-dir>/.stats.duckdb)",
    )
    rebuild_parser.add_argument(
        "--run-id",
        action="append",
        dest="run_ids",
        help="Specific run ID to rebuild (can be repeated)",
    )

    # Stats command
    stats_parser = subparsers.add_parser(
        "stats",
        help="Show statistics for a run",
    )
    stats_parser.add_argument("run_id", help="Run ID to query")

    # Doctor command (event contract validation)
    doctor_parser = subparsers.add_parser(
        "doctor",
        help="Validate event stream contract for a run",
    )
    doctor_parser.add_argument("run_id", help="Run ID to validate")
    doctor_parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat warnings as errors",
    )
    doctor_parser.add_argument(
        "--from-disk",
        action="store_true",
        help="Read events from disk (events.jsonl) instead of DB",
    )
    doctor_parser.add_argument(
        "--runs-dir",
        type=Path,
        default=None,
        help="Path to runs directory (for --from-disk mode)",
    )

    args = parser.parse_args()

    if args.command == "rebuild":
        print("Rebuilding stats database...")
        result = rebuild_stats_db(
            runs_dir=args.runs_dir,
            db_path=args.db_path,
            run_ids=args.run_ids,
        )
        print("\nRebuild complete:")
        print(f"  Runs processed: {result['runs_processed']}")
        print(f"  Events ingested: {result['events_ingested']}")
        print(f"  Envelopes processed: {result['envelopes_processed']}")
        if result["errors"]:
            print(f"  Errors: {len(result['errors'])}")
            for err in result["errors"][:5]:
                print(f"    - {err}")
        sys.exit(0)

    elif args.command == "stats":
        db = get_stats_db()
        run_stats = db.get_run_stats(args.run_id)
        if run_stats is None:
            print(f"Run not found: {args.run_id}")
            sys.exit(1)

        print(f"Run: {run_stats.run_id}")
        print(f"  Status: {run_stats.status}")
        print(f"  Flows: {', '.join(run_stats.flow_keys)}")
        print(f"  Steps: {run_stats.completed_steps}/{run_stats.total_steps}")
        print(f"  Tokens: {run_stats.total_tokens}")
        print(f"  Duration: {run_stats.total_duration_ms}ms")
        print(f"  Tool calls: {run_stats.tool_call_count}")
        print(f"  File changes: {run_stats.file_change_count}")
        sys.exit(0)

    elif args.command == "doctor":
        from .event_validator import (
            format_violations,
            validate_run_from_db,
            validate_run_from_disk,
        )
        from .storage import RUNS_DIR

        runs_dir = args.runs_dir or RUNS_DIR

        if args.from_disk:
            violations = validate_run_from_disk(args.run_id, runs_dir, strict=args.strict)
        else:
            db = get_stats_db()
            violations = validate_run_from_db(args.run_id, db, strict=args.strict)

        errors = [v for v in violations if v.severity == "error"]
        warnings = [v for v in violations if v.severity == "warning"]

        if not violations:
            print(f"✓ Run {args.run_id}: event stream valid")
            sys.exit(0)

        print(f"Run {args.run_id}: {len(errors)} error(s), {len(warnings)} warning(s)")
        print(format_violations(violations))

        # Exit with error code if there are errors
        sys.exit(1 if errors else 0)

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
