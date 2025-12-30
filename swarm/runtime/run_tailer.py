"""
run_tailer.py - Incremental event ingestion from events.jsonl

This module provides crash-safe incremental ingestion that:
- Reads events.jsonl from last known byte offset
- Ingests idempotently (skips existing event_ids)
- Only advances offset after successful ingest
- Supports async watching for live updates

Design Philosophy:
    - Disk (events.jsonl) is the source of truth
    - DuckDB is a projection that can be rebuilt or tailed
    - Offsets are persisted to enable incremental processing
    - Crash mid-ingest does NOT advance offset (crash-safe)

Usage:
    from swarm.runtime.run_tailer import RunTailer
    from swarm.runtime.db import get_stats_db

    tailer = RunTailer(get_stats_db(), RUNS_DIR)
    new_count = tailer.tail_run(run_id)

    # Or watch for live updates
    async for count in tailer.watch_run(run_id):
        print(f"Ingested {count} new events")
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, AsyncIterator, Dict, List, Optional

if TYPE_CHECKING:
    from .db import StatsDB

from .storage import RUNS_DIR, list_runs

logger = logging.getLogger(__name__)


class TailerError(Exception):
    """Error during event tailing."""

    pass


class RunTailer:
    """Incremental event ingestion with crash-safe offsets.

    Reads events.jsonl from the last ingested position, processes
    new events idempotently, and only advances the offset after
    successful ingestion.

    The key invariant is: if the process crashes mid-ingestion,
    the offset is NOT advanced, so on restart we re-read and
    re-ingest (idempotently) from the correct position.

    Thread-safe for concurrent tail_run() calls on different run_ids.
    Not safe for concurrent calls on the same run_id.

    Attributes:
        _db: StatsDB instance for ingestion and offset tracking.
        _runs_dir: Base directory containing run subdirectories.
    """

    def __init__(
        self,
        db: "StatsDB",
        runs_dir: Path = RUNS_DIR,
    ):
        """Initialize the tailer.

        Args:
            db: StatsDB instance for ingestion and offset tracking.
            runs_dir: Base directory for runs. Defaults to swarm/runs/.
        """
        self._db = db
        self._runs_dir = runs_dir

    def tail_run(self, run_id: str) -> int:
        """Tail events.jsonl from last offset for a single run.

        Reads from the last ingested byte offset, parses new events,
        ingests them idempotently, and advances the offset only after
        successful ingestion.

        Args:
            run_id: The run identifier.

        Returns:
            Number of newly ingested events (0 if no new events or file missing).

        Raises:
            TailerError: If ingestion fails (offset will NOT be advanced).
        """
        events_file = self._runs_dir / run_id / "events.jsonl"

        if not events_file.exists():
            logger.debug("No events.jsonl for run %s", run_id)
            return 0

        # Get last ingestion state
        last_offset, last_seq = self._db.get_ingestion_offset(run_id)

        # Check if file has grown
        file_size = events_file.stat().st_size
        if file_size <= last_offset:
            # No new data
            return 0

        # Read new events from offset
        new_events: List[Dict] = []
        new_offset = last_offset
        max_seq = last_seq

        try:
            with events_file.open("rb") as f:
                f.seek(last_offset)
                for line in f:
                    # CRITICAL: Only advance offset for complete lines (ending with \n).
                    # If the last line is partial (mid-write), we must NOT advance past it.
                    # On restart, we'll re-read from the same position and get the complete line.
                    if not line.endswith(b"\n"):
                        # Partial line - stop here, don't advance offset
                        logger.debug(
                            "Stopping at partial line in %s (len=%d bytes)",
                            run_id,
                            len(line),
                        )
                        break

                    new_offset += len(line)
                    line_str = line.decode("utf-8").strip()
                    if not line_str:
                        continue
                    try:
                        event = json.loads(line_str)
                        new_events.append(event)
                        max_seq = max(max_seq, event.get("seq", 0))
                    except json.JSONDecodeError as e:
                        # Complete line but invalid JSON - this is a real error, log and skip
                        logger.warning(
                            "Skipping malformed event in %s at offset %d: %s",
                            run_id,
                            new_offset - len(line),
                            e,
                        )
        except (OSError, IOError) as e:
            logger.error("Failed to read events.jsonl for %s: %s", run_id, e)
            return 0

        if not new_events:
            return 0

        # Ingest events (idempotent - skips existing event_ids)
        try:
            ingested_count = self._db.ingest_events(new_events, run_id)
        except Exception as e:
            # CRITICAL: Do NOT advance offset on failure
            logger.error(
                "Failed to ingest %d events for %s: %s",
                len(new_events),
                run_id,
                e,
            )
            raise TailerError(f"Ingestion failed for {run_id}") from e

        # Only advance offset after successful ingest
        self._db.set_ingestion_offset(run_id, new_offset, max_seq)

        logger.debug(
            "Tailed %d events for %s (offset %d->%d, seq %d->%d, ingested %d new)",
            len(new_events),
            run_id,
            last_offset,
            new_offset,
            last_seq,
            max_seq,
            ingested_count,
        )

        return ingested_count

    def tail_all_runs(self) -> Dict[str, int]:
        """Tail all known runs.

        Iterates through all runs in runs_dir and tails each one.
        Errors are logged but do not stop processing of other runs.

        Returns:
            Dict mapping run_id to count of newly ingested events.
            Only includes runs that had new events.
        """
        results: Dict[str, int] = {}

        for run_id in list_runs(self._runs_dir):
            try:
                count = self.tail_run(run_id)
                if count > 0:
                    results[run_id] = count
            except TailerError:
                pass  # Already logged

        return results

    async def watch_run(
        self,
        run_id: str,
        poll_interval_ms: int = 500,
        stop_on_complete: bool = True,
    ) -> AsyncIterator[int]:
        """Async generator that yields new event counts as they arrive.

        Polls events.jsonl at the specified interval and yields the
        count of newly ingested events each time new data is found.

        Args:
            run_id: The run identifier.
            poll_interval_ms: Polling interval in milliseconds.
            stop_on_complete: If True, stop when run reaches terminal status.

        Yields:
            Count of newly ingested events (only when > 0).
        """
        while True:
            try:
                count = self.tail_run(run_id)
                if count > 0:
                    yield count
            except TailerError:
                pass  # Continue watching despite errors

            if stop_on_complete:
                # Check if run is complete
                stats = self._db.get_run_stats(run_id)
                if stats and stats.status in ("succeeded", "failed", "canceled"):
                    # Do one final tail to catch any remaining events
                    try:
                        final_count = self.tail_run(run_id)
                        if final_count > 0:
                            yield final_count
                    except TailerError:
                        pass
                    return

            await asyncio.sleep(poll_interval_ms / 1000)

    async def watch_active_runs(
        self,
        poll_interval_ms: int = 1000,
    ) -> AsyncIterator[Dict[str, int]]:
        """Watch all active runs for new events.

        An active run is one that exists and may still be producing events.
        This method polls all runs at the specified interval.

        Args:
            poll_interval_ms: Polling interval in milliseconds.

        Yields:
            Dict of run_id -> new event count (only runs with new events).
        """
        while True:
            results = self.tail_all_runs()
            if results:
                yield results
            await asyncio.sleep(poll_interval_ms / 1000)


def get_tailer(
    db: Optional["StatsDB"] = None,
    runs_dir: Optional[Path] = None,
) -> RunTailer:
    """Factory function to create a RunTailer.

    Args:
        db: Optional StatsDB instance. Creates default if None.
        runs_dir: Optional runs directory. Defaults to swarm/runs/.

    Returns:
        Configured RunTailer instance.
    """
    from .db import get_stats_db

    if db is None:
        db = get_stats_db()
    if runs_dir is None:
        runs_dir = RUNS_DIR

    return RunTailer(db, runs_dir)
