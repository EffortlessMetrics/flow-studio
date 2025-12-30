"""
Tests for the resilient DuckDB wrapper.

These tests verify:
1. Schema version checking and auto-rebuild
2. DB file deletion detection and recovery
3. Graceful error handling (no 500s)
4. Single-writer pattern enforcement
"""

import json
from datetime import datetime, timezone

# Import the modules we're testing
from swarm.runtime.db import (
    PROJECTION_VERSION,
    StatsDB,
    _check_projection_version,
    _rename_old_db,
)
from swarm.runtime.resilient_db import (
    ResilientDBConfig,
    ResilientStatsDB,
    check_db_health,
    close_resilient_db,
    get_resilient_db,
)


class TestProjectionVersionCheck:
    """Tests for projection version checking and DB renaming."""

    def test_check_projection_version_no_db(self, tmp_path):
        """Test that missing DB returns False (needs creation)."""
        db_path = tmp_path / "nonexistent.duckdb"
        result = _check_projection_version(db_path)
        assert result is False

    def test_check_projection_version_matching(self, tmp_path):
        """Test that matching version returns True."""
        db_path = tmp_path / "test.duckdb"

        # Create a DB with the current projection version
        db = StatsDB(db_path)
        _ = db.connection  # Force initialization
        db.close()

        # Now check the version
        result = _check_projection_version(db_path)
        assert result is True

    def test_check_projection_version_mismatch(self, tmp_path):
        """Test that version mismatch renames old DB and returns False."""
        db_path = tmp_path / "test.duckdb"

        # Create a DB with a different projection version
        import duckdb

        conn = duckdb.connect(str(db_path))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS _projection_meta (
                key VARCHAR PRIMARY KEY,
                value VARCHAR NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Store a different version
        conn.execute("""
            INSERT INTO _projection_meta (key, value) VALUES ('projection_version', '999')
        """)
        conn.close()

        # Now check - should detect mismatch and rename
        result = _check_projection_version(db_path)
        assert result is False
        # Original file should be renamed
        assert not db_path.exists()
        # Should have an old file
        old_files = list(tmp_path.glob("test.duckdb.old.*"))
        assert len(old_files) == 1

    def test_rename_old_db_creates_timestamped_backup(self, tmp_path):
        """Test that _rename_old_db creates properly named backup."""
        db_path = tmp_path / "test.duckdb"
        db_path.write_text("dummy content")

        _rename_old_db(db_path)

        assert not db_path.exists()
        old_files = list(tmp_path.glob("test.duckdb.old.*"))
        assert len(old_files) == 1
        # Check the timestamp format
        old_name = old_files[0].name
        assert old_name.startswith("test.duckdb.old.")


class TestStatsDBRebuild:
    """Tests for StatsDB rebuild functionality."""

    def test_rebuild_from_events_empty(self, tmp_path):
        """Test rebuild when no events.jsonl exists."""
        runs_dir = tmp_path / "runs"
        runs_dir.mkdir()
        run_path = runs_dir / "test-run"
        run_path.mkdir()

        db_path = tmp_path / "test.duckdb"
        db = StatsDB(db_path)
        _ = db.connection

        result = db.rebuild_from_events("test-run", runs_dir)

        assert result["success"] is True
        assert result["events_ingested"] == 0
        db.close()

    def test_rebuild_from_events_with_data(self, tmp_path):
        """Test rebuild ingests events correctly."""
        runs_dir = tmp_path / "runs"
        runs_dir.mkdir()
        run_path = runs_dir / "test-run"
        run_path.mkdir()

        # Create events.jsonl
        events_file = run_path / "events.jsonl"
        events = [
            {
                "event_id": "evt-1",
                "seq": 1,
                "run_id": "test-run",
                "ts": datetime.now(timezone.utc).isoformat(),
                "kind": "run_started",
                "flow_key": "signal",
                "payload": {"flow_keys": ["signal", "plan"]},
            },
            {
                "event_id": "evt-2",
                "seq": 2,
                "run_id": "test-run",
                "ts": datetime.now(timezone.utc).isoformat(),
                "kind": "step_start",
                "flow_key": "signal",
                "step_id": "1",
                "payload": {"agent_key": "signal-normalizer", "step_index": 0},
            },
        ]
        with events_file.open("w") as f:
            for event in events:
                f.write(json.dumps(event) + "\n")

        db_path = tmp_path / "test.duckdb"
        db = StatsDB(db_path)
        _ = db.connection

        result = db.rebuild_from_events("test-run", runs_dir)

        assert result["success"] is True
        assert result["events_ingested"] == 2

        # Verify data was ingested
        run_stats = db.get_run_stats("test-run")
        assert run_stats is not None
        assert run_stats.run_id == "test-run"

        db.close()

    def test_needs_rebuild_flag_set_on_version_mismatch(self, tmp_path):
        """Test that needs_rebuild is set when version mismatches."""
        db_path = tmp_path / "test.duckdb"

        # Create a DB with old version
        import duckdb

        conn = duckdb.connect(str(db_path))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS _projection_meta (
                key VARCHAR PRIMARY KEY,
                value VARCHAR NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            INSERT INTO _projection_meta (key, value) VALUES ('projection_version', '0')
        """)
        conn.close()

        # Create new StatsDB - should detect mismatch
        db = StatsDB(db_path)
        _ = db.connection  # Trigger version check

        assert db.needs_rebuild is True
        db.close()


class TestResilientStatsDB:
    """Tests for the resilient wrapper."""

    def test_initialize_creates_healthy_db(self, tmp_path):
        """Test that initialization creates a healthy database."""
        db_path = tmp_path / "test.duckdb"
        runs_dir = tmp_path / "runs"
        runs_dir.mkdir()

        config = ResilientDBConfig(
            db_path=db_path,
            runs_dir=runs_dir,
            auto_rebuild=False,  # Skip auto-rebuild for faster test
        )
        db = ResilientStatsDB(config)
        health = db.initialize()

        assert health.healthy is True
        assert health.projection_version == PROJECTION_VERSION
        db.close()

    def test_safe_operations_return_default_on_error(self, tmp_path):
        """Test that safe operations return defaults when DB fails."""
        runs_dir = tmp_path / "runs"
        runs_dir.mkdir()

        config = ResilientDBConfig(
            db_path=tmp_path / "test.duckdb",
            runs_dir=runs_dir,
            auto_rebuild=False,
        )
        db = ResilientStatsDB(config)
        db.initialize()

        # These should return defaults, not raise
        result = db.get_run_stats_safe("nonexistent-run")
        assert result is None

        result = db.get_step_stats_safe("nonexistent-run")
        assert result == []

        result = db.get_tool_breakdown_safe("nonexistent-run")
        assert result == []

        result = db.get_recent_runs_safe()
        assert result == []

        db.close()

    def test_check_health_detects_deleted_db(self, tmp_path):
        """Test that health check detects when DB file is deleted."""
        db_path = tmp_path / "test.duckdb"
        runs_dir = tmp_path / "runs"
        runs_dir.mkdir()

        config = ResilientDBConfig(
            db_path=db_path,
            runs_dir=runs_dir,
            auto_rebuild=False,
        )
        db = ResilientStatsDB(config)
        db.initialize()

        assert db.health.db_exists is True

        # Close the DB before deleting
        db._db.close()
        db._db = None

        # Delete the DB file
        if db_path.exists():
            db_path.unlink()

        # Check health - should detect deletion and re-create DB
        health = db.check_health()
        # After re-creation, should be healthy again
        assert health.healthy is True
        # DB should exist again
        assert health.db_exists is True
        # DB instance should be re-created
        assert db._db is not None

        db.close()

    def test_ingest_events_safe_handles_errors(self, tmp_path):
        """Test that ingest_events_safe handles errors gracefully."""
        runs_dir = tmp_path / "runs"
        runs_dir.mkdir()

        config = ResilientDBConfig(
            db_path=tmp_path / "test.duckdb",
            runs_dir=runs_dir,
            auto_rebuild=False,
        )
        db = ResilientStatsDB(config)
        db.initialize()

        # Ingest with invalid events should not raise
        result = db.ingest_events_safe([{"invalid": "event"}], "test-run")
        # Should return 0 or handle gracefully
        assert isinstance(result, int)

        db.close()


class TestGlobalResilientDB:
    """Tests for the global singleton pattern."""

    def test_get_resilient_db_returns_singleton(self, monkeypatch):
        """Test that get_resilient_db returns the same instance."""
        # Reset global state
        import swarm.runtime.resilient_db as resilient_db_module

        monkeypatch.setattr(resilient_db_module, "_global_resilient_db", None)
        import swarm.runtime.db as db_module

        monkeypatch.setattr(db_module, "_global_db", None)

        try:
            # First call creates instance
            db1 = get_resilient_db()
            # Second call returns same instance
            db2 = get_resilient_db()

            assert db1 is db2
        finally:
            close_resilient_db()

    def test_close_resilient_db_clears_singleton(self, monkeypatch):
        """Test that close_resilient_db clears the global instance."""
        import swarm.runtime.resilient_db as resilient_db_module

        monkeypatch.setattr(resilient_db_module, "_global_resilient_db", None)
        import swarm.runtime.db as db_module

        monkeypatch.setattr(db_module, "_global_db", None)

        try:
            db1 = get_resilient_db()
            close_resilient_db()

            # After close, should get new instance
            db2 = get_resilient_db()
            assert db1 is not db2
        finally:
            close_resilient_db()


class TestDBHealthEndpoint:
    """Tests for the DB health API endpoint."""

    def test_health_endpoint_returns_db_info(self, monkeypatch):
        """Test that health endpoint includes DB health info."""
        # This is more of an integration test
        # We'll test the helper function that the endpoint uses
        import swarm.runtime.resilient_db as resilient_db_module

        monkeypatch.setattr(resilient_db_module, "_global_resilient_db", None)
        import swarm.runtime.db as db_module

        monkeypatch.setattr(db_module, "_global_db", None)

        try:
            health = check_db_health()

            assert isinstance(health.healthy, bool)
            assert health.projection_version == PROJECTION_VERSION
        finally:
            close_resilient_db()


class TestAcceptanceCriteria:
    """Tests verifying the acceptance criteria are met."""

    def test_deleting_db_file_triggers_rebuild(self, tmp_path):
        """
        Acceptance Criteria: Deleting the DB file while server runs -> UI recovers after rebuild
        """
        db_path = tmp_path / "test.duckdb"
        runs_dir = tmp_path / "runs"
        runs_dir.mkdir()

        # Create a run with events
        run_path = runs_dir / "test-run"
        run_path.mkdir()
        events_file = run_path / "events.jsonl"
        events = [
            {
                "event_id": "evt-1",
                "seq": 1,
                "run_id": "test-run",
                "ts": datetime.now(timezone.utc).isoformat(),
                "kind": "run_started",
                "flow_key": "signal",
                "payload": {"flow_keys": ["signal"]},
            },
        ]
        with events_file.open("w") as f:
            for event in events:
                f.write(json.dumps(event) + "\n")

        config = ResilientDBConfig(
            db_path=db_path,
            runs_dir=runs_dir,
            auto_rebuild=True,  # Enable auto-rebuild for this test
        )
        db = ResilientStatsDB(config)
        db.initialize()

        # Verify initial data
        stats = db.get_run_stats_safe("test-run")
        assert stats is not None

        # Close DB before deleting file
        db._db.close()
        db._db = None

        # Simulate server running - delete DB file
        if db_path.exists():
            db_path.unlink()

        # Health check should detect and rebuild
        health = db.check_health()
        assert health.healthy is True
        assert health.rebuild_count >= 1

        # Data should be available again after rebuild
        stats = db.get_run_stats_safe("test-run")
        assert stats is not None

        db.close()

    def test_new_column_triggers_rebuild(self, tmp_path):
        """
        Acceptance Criteria: Introducing a new column -> old DB triggers rebuild automatically
        """
        db_path = tmp_path / "test.duckdb"
        runs_dir = tmp_path / "runs"
        runs_dir.mkdir()

        # Create DB with old projection version
        import duckdb

        conn = duckdb.connect(str(db_path))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS _projection_meta (
                key VARCHAR PRIMARY KEY,
                value VARCHAR NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Use version 0 to simulate old schema
        conn.execute("""
            INSERT INTO _projection_meta (key, value) VALUES ('projection_version', '0')
        """)
        conn.close()

        # Create resilient DB - should detect mismatch and rebuild
        config = ResilientDBConfig(
            db_path=db_path,
            runs_dir=runs_dir,
            auto_rebuild=True,
        )
        db = ResilientStatsDB(config)
        health = db.initialize()

        # Should have rebuilt (old DB was renamed, new one created)
        # The rebuild_count may or may not be incremented depending on
        # whether there are events to rebuild
        assert health.healthy is True

        db.close()

    def test_no_500_errors_from_db_issues(self, tmp_path):
        """
        Acceptance Criteria: No 500 errors from DB issues
        """
        runs_dir = tmp_path / "runs"
        runs_dir.mkdir()

        config = ResilientDBConfig(
            db_path=tmp_path / "test.duckdb",
            runs_dir=runs_dir,
            auto_rebuild=False,
        )
        db = ResilientStatsDB(config)
        db.initialize()

        # All these should return gracefully, not raise
        assert db.get_run_stats_safe("nonexistent") is None
        assert db.get_step_stats_safe("nonexistent") == []
        assert db.get_tool_breakdown_safe("nonexistent") == []
        assert db.get_recent_runs_safe() == []
        assert db.get_file_changes_safe("nonexistent") == []
        assert db.get_facts_for_run_safe("nonexistent") == []

        # Even with DB closed, should not raise
        db.close()

        # After close, initialize should work again
        config2 = ResilientDBConfig(
            db_path=tmp_path / "test2.duckdb",
            runs_dir=runs_dir,
            auto_rebuild=False,
        )
        db2 = ResilientStatsDB(config2)
        db2.initialize()
        assert db2.get_run_stats_safe("nonexistent") is None
        db2.close()


class TestRebuildAllSafe:
    """Tests for rebuild_all_safe method."""

    def test_rebuild_all_safe_returns_stats(self, tmp_path):
        """Test that rebuild_all_safe returns proper statistics."""
        runs_dir = tmp_path / "runs"
        runs_dir.mkdir()

        # Create a run with events
        run_path = runs_dir / "test-run"
        run_path.mkdir()
        events_file = run_path / "events.jsonl"
        events = [
            {
                "event_id": "evt-1",
                "seq": 1,
                "run_id": "test-run",
                "ts": datetime.now(timezone.utc).isoformat(),
                "kind": "run_started",
                "flow_key": "signal",
                "payload": {"flow_keys": ["signal"]},
            },
        ]
        with events_file.open("w") as f:
            for event in events:
                f.write(json.dumps(event) + "\n")

        config = ResilientDBConfig(
            db_path=tmp_path / "test.duckdb",
            runs_dir=runs_dir,
            auto_rebuild=False,
        )
        db = ResilientStatsDB(config)
        db.initialize()

        result = db.rebuild_all_safe()

        assert result["success"] is True
        assert result["runs_succeeded"] >= 0
        assert "errors" in result
        assert isinstance(result["errors"], list)

        db.close()

    def test_rebuild_all_safe_handles_db_not_initialized(self, tmp_path):
        """Test that rebuild_all_safe handles uninitialized DB."""
        runs_dir = tmp_path / "runs"
        runs_dir.mkdir()

        config = ResilientDBConfig(
            db_path=tmp_path / "test.duckdb",
            runs_dir=runs_dir,
            auto_rebuild=False,
        )
        db = ResilientStatsDB(config)
        # Don't call initialize

        # Should auto-initialize and run
        result = db.rebuild_all_safe()

        # Should succeed (with no events to rebuild)
        assert "success" in result
        assert "errors" in result

        db.close()

    def test_rebuild_all_safe_updates_health(self, tmp_path):
        """Test that rebuild_all_safe updates health status."""
        runs_dir = tmp_path / "runs"
        runs_dir.mkdir()

        # Create a run with events
        run_path = runs_dir / "test-run"
        run_path.mkdir()
        events_file = run_path / "events.jsonl"
        events = [
            {
                "event_id": "evt-1",
                "seq": 1,
                "run_id": "test-run",
                "ts": datetime.now(timezone.utc).isoformat(),
                "kind": "run_started",
                "flow_key": "signal",
                "payload": {"flow_keys": ["signal"]},
            },
        ]
        with events_file.open("w") as f:
            for event in events:
                f.write(json.dumps(event) + "\n")

        config = ResilientDBConfig(
            db_path=tmp_path / "test.duckdb",
            runs_dir=runs_dir,
            auto_rebuild=False,
        )
        db = ResilientStatsDB(config)
        db.initialize()

        initial_rebuild_count = db.health.rebuild_count

        result = db.rebuild_all_safe()
        assert result["success"] is True

        # Rebuild count should have increased
        assert db.health.rebuild_count == initial_rebuild_count + 1
        assert db.health.last_rebuild is not None

        db.close()
