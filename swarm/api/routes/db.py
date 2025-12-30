"""
Database management endpoints for Flow Studio API.

Provides endpoints for:
- Checking database health
- Triggering manual rebuild from events.jsonl
- Querying database statistics
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/db", tags=["database"])


# =============================================================================
# Pydantic Models
# =============================================================================


class DBHealthResponse(BaseModel):
    """Database health status response."""

    healthy: bool
    projection_version: int
    db_exists: bool
    rebuild_count: int = 0
    error_count: int = 0
    last_error: Optional[str] = None
    last_check: Optional[str] = None
    last_rebuild: Optional[str] = None
    db_path: Optional[str] = None


class DBRebuildRequest(BaseModel):
    """Request to rebuild the database."""

    run_ids: Optional[List[str]] = Field(
        None, description="Specific run IDs to rebuild. If None, rebuilds all runs."
    )
    force: bool = Field(False, description="Force rebuild even if DB is healthy.")


class DBRebuildResponse(BaseModel):
    """Response after database rebuild."""

    success: bool
    runs_processed: int = 0
    runs_succeeded: int = 0
    events_ingested: int = 0
    errors: List[Dict[str, Any]] = Field(default_factory=list)
    duration_ms: int = 0
    timestamp: str


class DBStatsResponse(BaseModel):
    """Database statistics response."""

    total_runs: int = 0
    total_steps: int = 0
    total_tool_calls: int = 0
    total_file_changes: int = 0
    total_events: int = 0
    total_facts: int = 0
    projection_version: int = 0
    schema_version: int = 0


# =============================================================================
# Endpoints
# =============================================================================


@router.get("/health", response_model=DBHealthResponse)
async def get_db_health():
    """Get detailed database health status.

    Returns comprehensive health information including:
    - Whether the database is healthy
    - Current projection version
    - Rebuild and error counts
    - Last error message if any

    This endpoint never fails - it returns degraded status info on errors.
    """
    try:
        from swarm.runtime.resilient_db import check_db_health

        health = check_db_health()
        return DBHealthResponse(
            healthy=health.healthy,
            projection_version=health.projection_version,
            db_exists=health.db_exists,
            rebuild_count=health.rebuild_count,
            error_count=health.error_count,
            last_error=health.last_error,
            last_check=health.last_check.isoformat() if health.last_check else None,
            last_rebuild=health.last_rebuild.isoformat() if health.last_rebuild else None,
            db_path=health.db_path,
        )
    except Exception as e:
        logger.error("Failed to get DB health: %s", e)
        return DBHealthResponse(
            healthy=False,
            projection_version=0,
            db_exists=False,
            last_error=str(e),
        )


@router.post("/rebuild", response_model=DBRebuildResponse)
async def rebuild_database(request: DBRebuildRequest):
    """Trigger a database rebuild from events.jsonl files.

    This endpoint rebuilds the DuckDB projection from the authoritative
    events.jsonl files. Use this when:
    - Database was corrupted
    - Schema version was bumped
    - Database file was deleted

    The rebuild is idempotent - running it multiple times is safe.

    All operations are routed through the ResilientStatsDB wrapper to ensure
    consistent health tracking and error handling.

    Args:
        request: Rebuild request with optional run_ids filter and force flag.

    Returns:
        Rebuild statistics including runs processed and events ingested.
    """
    import time

    start_time = time.time()

    try:
        from swarm.runtime.resilient_db import check_db_health, get_resilient_db

        db = get_resilient_db()

        # Perform health check before rebuild (keeps health status coherent)
        check_db_health()

        # Check if rebuild is needed
        if not request.force and db.health.healthy and not db.health.needs_rebuild:
            return DBRebuildResponse(
                success=True,
                runs_processed=0,
                runs_succeeded=0,
                events_ingested=0,
                errors=[],
                duration_ms=0,
                timestamp=datetime.now(timezone.utc).isoformat(),
            )

        # Perform rebuild through the wrapper (not through db.db directly)
        if request.run_ids:
            # Rebuild specific runs using wrapper method
            total_stats: Dict[str, Any] = {
                "runs_processed": 0,
                "runs_succeeded": 0,
                "events_ingested": 0,
                "errors": [],
            }
            for run_id in request.run_ids:
                result = db.rebuild_from_events_safe(run_id)
                total_stats["runs_processed"] += 1
                if result.get("success"):
                    total_stats["runs_succeeded"] += 1
                    total_stats["events_ingested"] += result.get("events_ingested", 0)
                else:
                    total_stats["errors"].append(
                        {
                            "run_id": run_id,
                            "error": result.get("error", "Unknown error"),
                        }
                    )
            stats = total_stats
        else:
            # Rebuild all runs using wrapper method
            stats = db.rebuild_all_safe()

        duration_ms = int((time.time() - start_time) * 1000)

        return DBRebuildResponse(
            success=len(stats.get("errors", [])) == 0,
            runs_processed=stats.get("runs_processed", 0),
            runs_succeeded=stats.get("runs_succeeded", 0),
            events_ingested=stats.get("events_ingested", 0),
            errors=stats.get("errors", []),
            duration_ms=duration_ms,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to rebuild database: %s", e)
        duration_ms = int((time.time() - start_time) * 1000)
        return DBRebuildResponse(
            success=False,
            errors=[{"error": str(e)}],
            duration_ms=duration_ms,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )


@router.get("/stats", response_model=DBStatsResponse)
async def get_db_stats():
    """Get database statistics.

    Returns counts of all major entities in the database.
    Useful for monitoring and debugging.

    Performs a health check to ensure DB status stays coherent.
    """
    try:
        from swarm.runtime.db import PROJECTION_VERSION, SCHEMA_VERSION
        from swarm.runtime.resilient_db import check_db_health, get_resilient_db

        # Perform health check to keep status coherent
        check_db_health()

        db = get_resilient_db()
        stats_db = db.db

        if stats_db is None or stats_db.connection is None:
            return DBStatsResponse(
                projection_version=PROJECTION_VERSION,
                schema_version=SCHEMA_VERSION,
            )

        conn = stats_db.connection

        # Query counts from each table
        def safe_count(table: str) -> int:
            try:
                result = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
                return result[0] if result else 0
            except Exception:
                return 0

        return DBStatsResponse(
            total_runs=safe_count("runs"),
            total_steps=safe_count("steps"),
            total_tool_calls=safe_count("tool_calls"),
            total_file_changes=safe_count("file_changes"),
            total_events=safe_count("events"),
            total_facts=safe_count("facts"),
            projection_version=PROJECTION_VERSION,
            schema_version=SCHEMA_VERSION,
        )

    except Exception as e:
        logger.error("Failed to get DB stats: %s", e)
        from swarm.runtime.db import PROJECTION_VERSION, SCHEMA_VERSION

        return DBStatsResponse(
            projection_version=PROJECTION_VERSION,
            schema_version=SCHEMA_VERSION,
        )


@router.post("/ingest/{run_id}")
async def ingest_run_events(run_id: str):
    """Manually trigger event ingestion for a specific run.

    This reads events.jsonl for the specified run and ingests any
    new events into the database. Useful for debugging or when
    the automatic tailer misses events.

    Args:
        run_id: The run ID to ingest events for.

    Returns:
        Dict with ingestion statistics.
    """
    try:
        from swarm.runtime.resilient_db import get_resilient_db

        db = get_resilient_db()
        result = db.rebuild_from_events_safe(run_id)

        return {
            "run_id": run_id,
            "success": result.get("success", False),
            "events_ingested": result.get("events_ingested", 0),
            "error": result.get("error"),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    except Exception as e:
        logger.error("Failed to ingest events for run %s: %s", run_id, e)
        return {
            "run_id": run_id,
            "success": False,
            "events_ingested": 0,
            "error": str(e),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
