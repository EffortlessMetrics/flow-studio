"""Tests for incremental event tailer.

These tests verify that:
1. Tailing empty files returns 0
2. Tailing ingests new events and advances offset
3. Tailing is idempotent (same events twice = 0 new on second)
4. Crash mid-ingest does NOT advance offset
5. Incremental tailing only processes new events
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from swarm.runtime.db import StatsDB
from swarm.runtime.run_tailer import RunTailer, TailerError


class TestRunTailer:
    """Tests for RunTailer crash safety and idempotency."""

    @pytest.fixture
    def setup_run(self, tmp_path):
        """Create a test run directory with DB."""
        runs_dir = tmp_path / "runs"
        runs_dir.mkdir()

        run_id = "test-run-001"
        run_dir = runs_dir / run_id
        run_dir.mkdir()

        # Create meta.json (required by list_runs)
        meta = run_dir / "meta.json"
        meta.write_text(json.dumps({"id": run_id, "status": "running"}))

        db_path = runs_dir / ".stats.duckdb"
        db = StatsDB(db_path)

        return {
            "runs_dir": runs_dir,
            "run_dir": run_dir,
            "run_id": run_id,
            "db": db,
            "db_path": db_path,
        }

    def test_tail_missing_file(self, setup_run):
        """Tailing non-existent events.jsonl returns 0."""
        tailer = RunTailer(setup_run["db"], setup_run["runs_dir"])
        count = tailer.tail_run(setup_run["run_id"])

        assert count == 0
        setup_run["db"].close()

    def test_tail_empty_file(self, setup_run):
        """Tailing empty events.jsonl returns 0."""
        events_file = setup_run["run_dir"] / "events.jsonl"
        events_file.touch()

        tailer = RunTailer(setup_run["db"], setup_run["runs_dir"])
        count = tailer.tail_run(setup_run["run_id"])

        assert count == 0
        setup_run["db"].close()

    def test_tail_new_events(self, setup_run):
        """Tailing ingests new events and advances offset."""
        events_file = setup_run["run_dir"] / "events.jsonl"

        events = [
            {
                "event_id": "evt-1",
                "seq": 1,
                "run_id": setup_run["run_id"],
                "kind": "run_start",
                "flow_key": "build",
                "ts": "2025-01-01T00:00:00Z",
                "payload": {"flow_keys": ["build"]},
            },
            {
                "event_id": "evt-2",
                "seq": 2,
                "run_id": setup_run["run_id"],
                "kind": "step_start",
                "flow_key": "build",
                "step_id": "1",
                "ts": "2025-01-01T00:00:01Z",
                "payload": {"step_index": 0},
            },
        ]

        with events_file.open("w") as f:
            for event in events:
                f.write(json.dumps(event) + "\n")

        tailer = RunTailer(setup_run["db"], setup_run["runs_dir"])
        count = tailer.tail_run(setup_run["run_id"])

        assert count == 2

        # Verify offset was advanced
        offset, seq = setup_run["db"].get_ingestion_offset(setup_run["run_id"])
        assert offset > 0
        assert seq == 2

        setup_run["db"].close()

    def test_tail_idempotent(self, setup_run):
        """Tailing same file twice ingests 0 the second time."""
        events_file = setup_run["run_dir"] / "events.jsonl"

        events = [
            {
                "event_id": "evt-1",
                "seq": 1,
                "run_id": setup_run["run_id"],
                "kind": "run_start",
                "flow_key": "build",
                "ts": "2025-01-01T00:00:00Z",
                "payload": {},
            },
        ]

        with events_file.open("w") as f:
            for event in events:
                f.write(json.dumps(event) + "\n")

        tailer = RunTailer(setup_run["db"], setup_run["runs_dir"])

        # First tail
        count1 = tailer.tail_run(setup_run["run_id"])
        assert count1 == 1

        # Second tail - offset already at end, no new data
        count2 = tailer.tail_run(setup_run["run_id"])
        assert count2 == 0

        setup_run["db"].close()

    def test_crash_mid_ingest_no_offset_advance(self, setup_run):
        """If ingestion fails, offset must NOT advance."""
        events_file = setup_run["run_dir"] / "events.jsonl"

        events = [
            {
                "event_id": "evt-1",
                "seq": 1,
                "run_id": setup_run["run_id"],
                "kind": "run_start",
                "flow_key": "build",
                "ts": "2025-01-01T00:00:00Z",
                "payload": {},
            },
        ]

        with events_file.open("w") as f:
            for event in events:
                f.write(json.dumps(event) + "\n")

        tailer = RunTailer(setup_run["db"], setup_run["runs_dir"])

        # Mock ingest_events to raise
        with patch.object(
            setup_run["db"], "ingest_events", side_effect=RuntimeError("DB error")
        ):
            with pytest.raises(TailerError):
                tailer.tail_run(setup_run["run_id"])

        # Verify offset was NOT advanced
        offset, seq = setup_run["db"].get_ingestion_offset(setup_run["run_id"])
        assert offset == 0
        assert seq == 0

        setup_run["db"].close()

    def test_incremental_tail(self, setup_run):
        """Tailing picks up only new events after initial tail."""
        events_file = setup_run["run_dir"] / "events.jsonl"

        # Initial events
        with events_file.open("w") as f:
            f.write(
                json.dumps(
                    {
                        "event_id": "evt-1",
                        "seq": 1,
                        "run_id": setup_run["run_id"],
                        "kind": "run_start",
                        "flow_key": "build",
                        "ts": "2025-01-01T00:00:00Z",
                        "payload": {},
                    }
                )
                + "\n"
            )

        tailer = RunTailer(setup_run["db"], setup_run["runs_dir"])
        count1 = tailer.tail_run(setup_run["run_id"])
        assert count1 == 1

        # Append more events
        with events_file.open("a") as f:
            f.write(
                json.dumps(
                    {
                        "event_id": "evt-2",
                        "seq": 2,
                        "run_id": setup_run["run_id"],
                        "kind": "step_start",
                        "flow_key": "build",
                        "step_id": "1",
                        "ts": "2025-01-01T00:00:01Z",
                        "payload": {},
                    }
                )
                + "\n"
            )

        # Second tail picks up only new events
        count2 = tailer.tail_run(setup_run["run_id"])
        assert count2 == 1

        # Third tail - no new events
        count3 = tailer.tail_run(setup_run["run_id"])
        assert count3 == 0

        setup_run["db"].close()

    def test_tail_all_runs(self, setup_run):
        """tail_all_runs processes all runs in directory."""
        # Create a second run
        run2_id = "test-run-002"
        run2_dir = setup_run["runs_dir"] / run2_id
        run2_dir.mkdir()

        # Write meta.json for both runs (required by list_runs)
        meta1 = setup_run["run_dir"] / "meta.json"
        meta2 = run2_dir / "meta.json"
        meta1.write_text(json.dumps({"id": setup_run["run_id"], "status": "running"}))
        meta2.write_text(json.dumps({"id": run2_id, "status": "running"}))

        # Write events to both runs
        events_file1 = setup_run["run_dir"] / "events.jsonl"
        events_file2 = run2_dir / "events.jsonl"

        with events_file1.open("w") as f:
            f.write(
                json.dumps(
                    {
                        "event_id": "evt-1",
                        "seq": 1,
                        "run_id": setup_run["run_id"],
                        "kind": "run_start",
                        "flow_key": "build",
                        "ts": "2025-01-01T00:00:00Z",
                        "payload": {"flow_keys": ["build"]},
                    }
                )
                + "\n"
            )

        with events_file2.open("w") as f:
            f.write(
                json.dumps(
                    {
                        "event_id": "evt-2",
                        "seq": 1,
                        "run_id": run2_id,
                        "kind": "run_start",
                        "flow_key": "plan",
                        "ts": "2025-01-01T00:00:00Z",
                        "payload": {"flow_keys": ["plan"]},
                    }
                )
                + "\n"
            )

        tailer = RunTailer(setup_run["db"], setup_run["runs_dir"])
        results = tailer.tail_all_runs()

        assert len(results) == 2
        assert setup_run["run_id"] in results
        assert run2_id in results
        assert results[setup_run["run_id"]] == 1
        assert results[run2_id] == 1

        setup_run["db"].close()

    def test_malformed_json_skipped(self, setup_run):
        """Malformed JSON lines are skipped without failing."""
        events_file = setup_run["run_dir"] / "events.jsonl"

        with events_file.open("w") as f:
            # Valid event
            f.write(
                json.dumps(
                    {
                        "event_id": "evt-1",
                        "seq": 1,
                        "run_id": setup_run["run_id"],
                        "kind": "run_start",
                        "flow_key": "build",
                        "ts": "2025-01-01T00:00:00Z",
                        "payload": {},
                    }
                )
                + "\n"
            )
            # Malformed line
            f.write("this is not valid json\n")
            # Another valid event
            f.write(
                json.dumps(
                    {
                        "event_id": "evt-2",
                        "seq": 2,
                        "run_id": setup_run["run_id"],
                        "kind": "step_start",
                        "flow_key": "build",
                        "step_id": "1",
                        "ts": "2025-01-01T00:00:01Z",
                        "payload": {},
                    }
                )
                + "\n"
            )

        tailer = RunTailer(setup_run["db"], setup_run["runs_dir"])
        count = tailer.tail_run(setup_run["run_id"])

        # Both valid events should be ingested
        assert count == 2

        setup_run["db"].close()


class TestTailerAsync:
    """Tests for async tailer methods."""

    @pytest.fixture
    def setup_run(self, tmp_path):
        """Create a test run directory with DB."""
        runs_dir = tmp_path / "runs"
        runs_dir.mkdir()

        run_id = "test-run-async"
        run_dir = runs_dir / run_id
        run_dir.mkdir()

        # Create meta.json (required by list_runs)
        meta = run_dir / "meta.json"
        meta.write_text(json.dumps({"id": run_id, "status": "running"}))

        db_path = runs_dir / ".stats.duckdb"
        db = StatsDB(db_path)

        return {
            "runs_dir": runs_dir,
            "run_dir": run_dir,
            "run_id": run_id,
            "db": db,
        }

    def test_watch_run_yields_counts(self, setup_run):
        """watch_run yields event counts as they arrive."""
        events_file = setup_run["run_dir"] / "events.jsonl"

        # Write initial events
        with events_file.open("w") as f:
            f.write(
                json.dumps(
                    {
                        "event_id": "evt-1",
                        "seq": 1,
                        "run_id": setup_run["run_id"],
                        "kind": "run_start",
                        "flow_key": "build",
                        "ts": "2025-01-01T00:00:00Z",
                        "payload": {"flow_keys": ["build"]},
                    }
                )
                + "\n"
            )

        async def run_test():
            tailer = RunTailer(setup_run["db"], setup_run["runs_dir"])

            # Collect first yield
            counts = []
            async for count in tailer.watch_run(
                setup_run["run_id"], poll_interval_ms=50, stop_on_complete=False
            ):
                counts.append(count)
                if len(counts) >= 1:
                    break

            return counts

        counts = asyncio.run(run_test())
        assert counts[0] == 1

        setup_run["db"].close()

    def test_watch_run_stops_on_complete(self, setup_run):
        """watch_run stops when run reaches terminal status."""
        events_file = setup_run["run_dir"] / "events.jsonl"

        # Write events including run_completed
        events = [
            {
                "event_id": "evt-1",
                "seq": 1,
                "run_id": setup_run["run_id"],
                "kind": "run_start",
                "flow_key": "build",
                "ts": "2025-01-01T00:00:00Z",
                "payload": {"flow_keys": ["build"]},
            },
            {
                "event_id": "evt-2",
                "seq": 2,
                "run_id": setup_run["run_id"],
                "kind": "run_completed",
                "flow_key": "build",
                "ts": "2025-01-01T00:00:01Z",
                "payload": {"status": "succeeded"},
            },
        ]

        with events_file.open("w") as f:
            for event in events:
                f.write(json.dumps(event) + "\n")

        async def run_test():
            tailer = RunTailer(setup_run["db"], setup_run["runs_dir"])

            # watch_run should stop after seeing completed status
            counts = []
            async for count in tailer.watch_run(
                setup_run["run_id"], poll_interval_ms=50, stop_on_complete=True
            ):
                counts.append(count)

            return counts

        counts = asyncio.run(run_test())

        # Should have yielded at least once
        assert len(counts) >= 1
        assert sum(counts) == 2  # Total events ingested

        setup_run["db"].close()
