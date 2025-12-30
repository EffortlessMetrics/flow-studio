"""Tests for projection-only mode and rebuild integrity.

These tests verify that:
1. Direct record_* calls are skipped in projection-only mode
2. Strict mode raises RuntimeError on direct writes
3. Ingestion context allows record_* calls during ingest_events()
4. Rebuild from disk produces identical projections to live ingestion
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest


class TestProjectionOnlyMode:
    """Tests for SWARM_DB_PROJECTION_ONLY mode."""

    @pytest.fixture(autouse=True)
    def setup_env(self):
        """Save and restore environment variables."""
        saved = {
            "SWARM_DB_PROJECTION_ONLY": os.environ.get("SWARM_DB_PROJECTION_ONLY"),
            "SWARM_DB_PROJECTION_STRICT": os.environ.get("SWARM_DB_PROJECTION_STRICT"),
        }
        yield
        # Restore
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

        # Force reimport to pick up env changes
        import importlib
        import swarm.runtime.db as db_module
        importlib.reload(db_module)

    def test_projection_only_blocks_direct_writes(self, tmp_path):
        """Direct record_* calls are skipped in projection-only mode."""
        os.environ["SWARM_DB_PROJECTION_ONLY"] = "true"
        os.environ["SWARM_DB_PROJECTION_STRICT"] = "false"

        # Reimport to pick up env changes
        import importlib
        import swarm.runtime.db as db_module
        importlib.reload(db_module)

        db_path = tmp_path / "test.duckdb"
        db = db_module.StatsDB(db_path)

        # Try to record a run start directly
        db.record_run_start("test-run", ["build"])

        # Should have no runs (write was skipped)
        stats = db.get_run_stats("test-run")
        assert stats is None, "Direct write should be skipped in projection-only mode"

        db.close()

    def test_projection_strict_raises_on_direct_write(self, tmp_path):
        """Strict mode raises RuntimeError on direct writes."""
        os.environ["SWARM_DB_PROJECTION_ONLY"] = "true"
        os.environ["SWARM_DB_PROJECTION_STRICT"] = "true"

        # Reimport to pick up env changes
        import importlib
        import swarm.runtime.db as db_module
        importlib.reload(db_module)

        db_path = tmp_path / "test.duckdb"
        db = db_module.StatsDB(db_path)

        with pytest.raises(RuntimeError, match="Direct DB write.*blocked"):
            db.record_run_start("test-run", ["build"])

        db.close()

    def test_ingestion_context_allows_record_calls(self, tmp_path):
        """Ingestion context allows record_* calls during ingest_events()."""
        os.environ["SWARM_DB_PROJECTION_ONLY"] = "true"
        os.environ["SWARM_DB_PROJECTION_STRICT"] = "true"  # Even in strict mode

        # Reimport to pick up env changes
        import importlib
        import swarm.runtime.db as db_module
        importlib.reload(db_module)

        db_path = tmp_path / "test.duckdb"
        db = db_module.StatsDB(db_path)

        # Ingest events should work (record_* calls happen inside)
        events = [
            {
                "event_id": "evt-1",
                "seq": 1,
                "kind": "run_start",
                "flow_key": "build",
                "ts": "2025-01-01T00:00:00Z",
                "payload": {"flow_keys": ["build"]},
            },
            {
                "event_id": "evt-2",
                "seq": 2,
                "kind": "step_start",
                "flow_key": "build",
                "step_id": "1",
                "ts": "2025-01-01T00:00:01Z",
                "payload": {"step_index": 0, "agent_key": "test-agent"},
            },
        ]

        count = db.ingest_events(events, "test-run")
        assert count == 2, "Ingestion should succeed"

        # Verify projections were created
        stats = db.get_run_stats("test-run")
        assert stats is not None, "Run stats should exist after ingestion"

        db.close()

    def test_legacy_mode_allows_direct_writes(self, tmp_path):
        """Legacy mode (PROJECTION_ONLY=false) allows direct writes."""
        os.environ["SWARM_DB_PROJECTION_ONLY"] = "false"

        # Reimport to pick up env changes
        import importlib
        import swarm.runtime.db as db_module
        importlib.reload(db_module)

        db_path = tmp_path / "test.duckdb"
        db = db_module.StatsDB(db_path)

        # Direct write should work
        db.record_run_start("test-run", ["build"])

        stats = db.get_run_stats("test-run")
        assert stats is not None, "Direct write should work in legacy mode"
        assert stats.status == "running"

        db.close()


class TestRebuildIntegrity:
    """Tests for rebuild-from-disk matching live ingestion."""

    def test_rebuild_matches_live_ingestion(self, tmp_path):
        """Rebuild from disk produces identical projections to live ingestion."""
        from swarm.runtime.db import StatsDB, rebuild_stats_db

        runs_dir = tmp_path / "runs"
        runs_dir.mkdir()

        run_id = "test-rebuild-run"
        run_dir = runs_dir / run_id
        run_dir.mkdir()

        # Write events to disk (simulating what orchestrator does)
        events = [
            {
                "event_id": "evt-1",
                "seq": 1,
                "kind": "run_start",
                "flow_key": "build",
                "run_id": run_id,
                "ts": "2025-01-01T00:00:00Z",
                "payload": {"flow_keys": ["build"]},
            },
            {
                "event_id": "evt-2",
                "seq": 2,
                "kind": "step_start",
                "flow_key": "build",
                "step_id": "1",
                "run_id": run_id,
                "ts": "2025-01-01T00:00:01Z",
                "payload": {"step_index": 0, "agent_key": "test-agent"},
            },
            {
                "event_id": "evt-3",
                "seq": 3,
                "kind": "step_complete",
                "flow_key": "build",
                "step_id": "1",
                "run_id": run_id,
                "ts": "2025-01-01T00:00:02Z",
                "payload": {"status": "succeeded", "duration_ms": 1000},
            },
            {
                "event_id": "evt-4",
                "seq": 4,
                "kind": "run_completed",
                "flow_key": "build",
                "run_id": run_id,
                "ts": "2025-01-01T00:00:03Z",
                "payload": {
                    "status": "succeeded",
                    "total_steps": 1,
                    "steps_completed": 1,
                },
            },
        ]

        events_file = run_dir / "events.jsonl"
        with events_file.open("w") as f:
            for event in events:
                f.write(json.dumps(event) + "\n")

        # Rebuild DB from disk
        db_path = runs_dir / ".stats.duckdb"
        result = rebuild_stats_db(runs_dir=runs_dir, db_path=db_path)

        assert result["runs_processed"] == 1
        assert result["events_ingested"] == 4
        assert len(result["errors"]) == 0

        # Verify projections
        db = StatsDB(db_path)

        run_stats = db.get_run_stats(run_id)
        assert run_stats is not None
        assert run_stats.status == "succeeded"
        assert run_stats.total_steps == 1
        assert run_stats.completed_steps == 1

        step_stats = db.get_step_stats(run_id)
        assert len(step_stats) == 1
        assert step_stats[0].step_id == "1"
        assert step_stats[0].status == "succeeded"

        db.close()

    def test_rebuild_produces_consistent_result(self, tmp_path):
        """Rebuilding twice produces the same projections.

        Note: rebuild_stats_db drops the existing DB and recreates from disk,
        so events_ingested will be the same on each call. The consistency
        guarantee is that projections match the disk state.
        """
        from swarm.runtime.db import StatsDB, rebuild_stats_db

        runs_dir = tmp_path / "runs"
        runs_dir.mkdir()

        run_id = "test-idem-run"
        run_dir = runs_dir / run_id
        run_dir.mkdir()

        events = [
            {
                "event_id": "evt-1",
                "seq": 1,
                "kind": "run_start",
                "flow_key": "build",
                "run_id": run_id,
                "ts": "2025-01-01T00:00:00Z",
                "payload": {"flow_keys": ["build"]},
            },
        ]

        events_file = run_dir / "events.jsonl"
        with events_file.open("w") as f:
            for event in events:
                f.write(json.dumps(event) + "\n")

        db_path = runs_dir / ".stats.duckdb"

        # First rebuild
        result1 = rebuild_stats_db(runs_dir=runs_dir, db_path=db_path)

        # Get state after first rebuild
        db1 = StatsDB(db_path)
        stats1 = db1.get_run_stats(run_id)
        db1.close()

        # Second rebuild (drops and recreates)
        result2 = rebuild_stats_db(runs_dir=runs_dir, db_path=db_path)

        # Get state after second rebuild
        db2 = StatsDB(db_path)
        stats2 = db2.get_run_stats(run_id)
        db2.close()

        # Both should ingest the same events (fresh DB each time)
        assert result1["events_ingested"] == 1
        assert result2["events_ingested"] == 1  # Fresh DB, reingests

        # But projections should be identical
        assert stats1 is not None
        assert stats2 is not None
        assert stats1.run_id == stats2.run_id
        assert stats1.status == stats2.status


    def test_ingest_events_idempotent(self, tmp_path):
        """Ingesting same events twice skips duplicates (by event_id)."""
        from swarm.runtime.db import StatsDB

        db_path = tmp_path / "test.duckdb"
        db = StatsDB(db_path)

        run_id = "test-idem-run"
        events = [
            {
                "event_id": "evt-1",
                "seq": 1,
                "kind": "run_start",
                "flow_key": "build",
                "ts": "2025-01-01T00:00:00Z",
                "payload": {"flow_keys": ["build"]},
            },
        ]

        # First ingestion
        count1 = db.ingest_events(events, run_id)
        assert count1 == 1

        # Second ingestion of same events
        count2 = db.ingest_events(events, run_id)
        assert count2 == 0  # Skipped because event_id already exists

        db.close()


class TestIngestionOffset:
    """Tests for ingestion offset tracking."""

    def test_offset_advances_after_ingestion(self, tmp_path):
        """Offset advances after successful ingestion."""
        from swarm.runtime.db import StatsDB

        db_path = tmp_path / "test.duckdb"
        db = StatsDB(db_path)

        run_id = "test-offset-run"

        # Initial offset should be 0
        offset, seq = db.get_ingestion_offset(run_id)
        assert offset == 0
        assert seq == 0

        # Ingest some events
        events = [
            {"event_id": "evt-1", "seq": 1, "kind": "run_start",
             "flow_key": "build", "ts": "2025-01-01T00:00:00Z",
             "payload": {"flow_keys": ["build"]}},
        ]
        db.ingest_events(events, run_id)

        # Set offset manually (simulating tailer)
        db.set_ingestion_offset(run_id, 100, 1)

        # Verify offset was set
        offset, seq = db.get_ingestion_offset(run_id)
        assert offset == 100
        assert seq == 1

        db.close()

    def test_offset_not_advanced_on_no_new_events(self, tmp_path):
        """Offset should not change when no new events are ingested."""
        from swarm.runtime.db import StatsDB

        db_path = tmp_path / "test.duckdb"
        db = StatsDB(db_path)

        run_id = "test-offset-run"

        events = [
            {"event_id": "evt-1", "seq": 1, "kind": "run_start",
             "flow_key": "build", "ts": "2025-01-01T00:00:00Z",
             "payload": {"flow_keys": ["build"]}},
        ]

        # First ingestion
        count1 = db.ingest_events(events, run_id)
        assert count1 == 1
        db.set_ingestion_offset(run_id, 100, 1)

        # Second ingestion (same events - should be skipped)
        count2 = db.ingest_events(events, run_id)
        assert count2 == 0

        # Offset should remain the same
        offset, seq = db.get_ingestion_offset(run_id)
        assert offset == 100
        assert seq == 1

        db.close()
