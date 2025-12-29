"""
SSE event streaming endpoints for Flow Studio API.

Provides Server-Sent Events (SSE) streaming for:
- Run events (step progress, status changes, logs)
- Real-time updates during flow execution
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/runs", tags=["events"])


# =============================================================================
# Event Types
# =============================================================================


class EventType:
    """Standard event types for SSE streaming."""

    # Connection events
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    HEARTBEAT = "heartbeat"

    # Run lifecycle events
    RUN_STARTED = "run:started"
    RUN_PAUSED = "run:paused"
    RUN_RESUMED = "run:resumed"
    RUN_COMPLETED = "run:completed"
    RUN_FAILED = "run:failed"
    RUN_CANCELED = "run:canceled"
    RUN_INTERRUPTED = "run:interrupted"

    # Step events
    STEP_STARTED = "step:started"
    STEP_PROGRESS = "step:progress"
    STEP_COMPLETED = "step:completed"
    STEP_FAILED = "step:failed"
    STEP_SKIPPED = "step:skipped"

    # Artifact events
    ARTIFACT_CREATED = "artifact:created"
    ARTIFACT_UPDATED = "artifact:updated"

    # LLM events
    LLM_STARTED = "llm:started"
    LLM_TOKEN = "llm:token"
    LLM_COMPLETED = "llm:completed"

    # Error events
    ERROR = "error"


# =============================================================================
# Event Formatting
# =============================================================================


def format_sse_event(
    event_type: str,
    data: Dict[str, Any],
    event_id: Optional[str] = None,
    retry: Optional[int] = None,
) -> str:
    """Format an SSE event according to the spec.

    SSE format:
        id: <event_id>
        event: <event_type>
        retry: <milliseconds>
        data: <json_data>

    Args:
        event_type: Event type name.
        data: Event data (will be JSON serialized).
        event_id: Optional event ID for resumption.
        retry: Optional retry interval in milliseconds.

    Returns:
        Formatted SSE event string.
    """
    lines = []

    if event_id:
        lines.append(f"id: {event_id}")

    if event_type:
        lines.append(f"event: {event_type}")

    if retry:
        lines.append(f"retry: {retry}")

    # Add timestamp if not present
    if "timestamp" not in data:
        data["timestamp"] = datetime.now(timezone.utc).isoformat()

    lines.append(f"data: {json.dumps(data)}")
    lines.append("")  # Empty line terminates event

    return "\n".join(lines) + "\n"


# =============================================================================
# Event Generation
# =============================================================================


async def read_events_file(
    events_file: Path,
    last_position: int = 0,
) -> tuple[list[Dict[str, Any]], int]:
    """Read new events from the events file.

    Args:
        events_file: Path to events.jsonl file.
        last_position: Last read position in file.

    Returns:
        Tuple of (events list, new position).
    """
    events = []

    if not events_file.exists():
        return events, last_position

    try:
        with open(events_file, "r", encoding="utf-8") as f:
            f.seek(last_position)
            for line in f:
                line = line.strip()
                if line:
                    try:
                        event = json.loads(line)
                        events.append(event)
                    except json.JSONDecodeError:
                        logger.warning("Invalid JSON in events file: %s", line)
            new_position = f.tell()
    except Exception as e:
        logger.warning("Error reading events file: %s", e)
        new_position = last_position

    return events, new_position


async def generate_run_events(
    run_id: str,
    runs_root: Path,
    poll_interval: float = 1.0,
    heartbeat_interval: float = 15.0,
) -> AsyncGenerator[str, None]:
    """Generate SSE events for a run.

    Yields SSE-formatted events as they occur:
    1. Initial connection event
    2. Events from events.jsonl file (incrementally)
    3. Heartbeat events (every heartbeat_interval seconds)
    4. Completion event when run ends

    Args:
        run_id: Run identifier.
        runs_root: Root directory for runs.
        poll_interval: How often to poll for new events.
        heartbeat_interval: How often to send heartbeat.

    Yields:
        SSE-formatted event strings.
    """
    run_dir = runs_root / run_id
    events_file = run_dir / "events.jsonl"
    state_file = run_dir / "run_state.json"

    # Track file position for incremental reading
    last_position = 0
    last_heartbeat = datetime.now(timezone.utc)
    event_counter = 0

    # Send connection event
    event_counter += 1
    yield format_sse_event(
        EventType.CONNECTED,
        {"run_id": run_id, "message": "Connected to event stream"},
        event_id=str(event_counter),
    )

    while True:
        try:
            # Check if run exists
            if not state_file.exists():
                yield format_sse_event(
                    EventType.ERROR,
                    {"error": "run_not_found", "message": f"Run '{run_id}' not found"},
                )
                break

            # Read current state
            state = json.loads(state_file.read_text(encoding="utf-8"))
            status = state.get("status", "pending")

            # Read new events from file
            events, last_position = await read_events_file(events_file, last_position)

            for event in events:
                event_counter += 1
                event_type = event.pop("event", "message")
                yield format_sse_event(
                    event_type,
                    event,
                    event_id=str(event_counter),
                )

            # Send heartbeat if interval elapsed
            now = datetime.now(timezone.utc)
            if (now - last_heartbeat).total_seconds() >= heartbeat_interval:
                event_counter += 1
                yield format_sse_event(
                    EventType.HEARTBEAT,
                    {
                        "run_id": run_id,
                        "status": status,
                        "current_step": state.get("current_step"),
                    },
                    event_id=str(event_counter),
                )
                last_heartbeat = now

            # Check for terminal states
            if status in ("succeeded", "failed", "canceled"):
                event_counter += 1

                # Map status to event type
                status_to_event = {
                    "succeeded": EventType.RUN_COMPLETED,
                    "failed": EventType.RUN_FAILED,
                    "canceled": EventType.RUN_CANCELED,
                }

                yield format_sse_event(
                    status_to_event[status],
                    {
                        "run_id": run_id,
                        "status": status,
                        "completed_at": state.get("completed_at"),
                        "error": state.get("error"),
                    },
                    event_id=str(event_counter),
                )
                break

            # Wait before next poll
            await asyncio.sleep(poll_interval)

        except asyncio.CancelledError:
            # Client disconnected
            logger.debug("SSE client disconnected for run %s", run_id)
            break
        except Exception as e:
            logger.error("Error in event stream for run %s: %s", run_id, e)
            yield format_sse_event(
                EventType.ERROR,
                {"error": "stream_error", "message": str(e)},
            )
            await asyncio.sleep(5)  # Back off on error


# =============================================================================
# SSE Endpoint
# =============================================================================


@router.get("/{run_id}/events")
async def stream_run_events(run_id: str, request: Request):
    """Stream Server-Sent Events for a run.

    Provides a real-time event stream for monitoring run progress.
    Events include step progress, status changes, and artifacts.

    Args:
        run_id: Run identifier.
        request: FastAPI request object for disconnect detection.

    Returns:
        StreamingResponse with SSE content type.

    Example events:
        event: connected
        data: {"run_id": "abc123", "message": "Connected to event stream"}

        event: step:started
        data: {"step_id": "init", "station_id": "repo-operator"}

        event: step:completed
        data: {"step_id": "init", "status": "VERIFIED"}

        event: heartbeat
        data: {"run_id": "abc123", "status": "running"}

        event: run:completed
        data: {"run_id": "abc123", "status": "succeeded"}
    """
    # Get runs root from spec manager
    from ..server import get_spec_manager

    manager = get_spec_manager()
    runs_root = manager.runs_root

    # Verify run exists
    run_dir = runs_root / run_id
    if not run_dir.exists():
        raise HTTPException(
            status_code=404,
            detail={
                "error": "run_not_found",
                "message": f"Run '{run_id}' not found",
                "details": {"run_id": run_id},
            },
        )

    async def event_stream():
        async for event in generate_run_events(run_id, runs_root):
            # Check if client disconnected
            if await request.is_disconnected():
                break
            yield event

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )


# =============================================================================
# Event Writing Utilities
# =============================================================================


async def write_event(
    run_id: str,
    runs_root: Path,
    event_type: str,
    data: Dict[str, Any],
) -> None:
    """Write an event to a run's events file.

    Args:
        run_id: Run identifier.
        runs_root: Root directory for runs.
        event_type: Event type name.
        data: Event data.
    """
    events_file = runs_root / run_id / "events.jsonl"
    events_file.parent.mkdir(parents=True, exist_ok=True)

    event = {
        "event": event_type,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **data,
    }

    with open(events_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(event) + "\n")


def write_event_sync(
    run_id: str,
    runs_root: Path,
    event_type: str,
    data: Dict[str, Any],
) -> None:
    """Synchronous version of write_event.

    Args:
        run_id: Run identifier.
        runs_root: Root directory for runs.
        event_type: Event type name.
        data: Event data.
    """
    events_file = runs_root / run_id / "events.jsonl"
    events_file.parent.mkdir(parents=True, exist_ok=True)

    event = {
        "event": event_type,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **data,
    }

    with open(events_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(event) + "\n")
