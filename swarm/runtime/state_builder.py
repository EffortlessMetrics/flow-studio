"""
state_builder.py - RunState rebuilder from events.jsonl.

This module provides functionality to reconstruct RunState from the event log
alone, enabling crash recovery and state verification. The event log serves
as the source of truth, and this module replays events to rebuild the
program counter.

The core principle: if events.jsonl exists, the RunState can always be
reconstructed. This is essential for durability and enables:

1. Crash recovery: If run_state.json is missing or corrupted, rebuild from events
2. State verification: Compare rebuilt state against stored state for integrity
3. Debugging: Trace through events to understand execution history
4. Migration: Upgrade state schema by replaying events through new handlers

Usage:
    from swarm.runtime.state_builder import rebuild_run_state, verify_run_state

    # Rebuild state from events alone
    state = rebuild_run_state("run-20251208-143022-abc123")

    # Verify stored state matches event log
    is_valid = verify_run_state("run-20251208-143022-abc123")
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from .storage import (
    RUNS_DIR,
    read_events,
    read_run_state,
)
from .types import (
    HandoffEnvelope,
    InterruptionFrame,
    ResumePoint,
    RunEvent,
    RunId,
    RunState,
    handoff_envelope_from_dict,
    interruption_frame_from_dict,
    resume_point_from_dict,
    injected_node_spec_from_dict,
)

# Module logger
logger = logging.getLogger(__name__)


class StateRebuilderError(Exception):
    """Raised when state rebuilding fails."""

    pass


def rebuild_run_state(
    run_id: RunId,
    runs_dir: Path = RUNS_DIR,
) -> RunState:
    """Rebuild RunState by replaying all events from events.jsonl.

    This function reads all events from the event log and applies them
    in order to reconstruct the RunState. It is the canonical way to
    recover state after a crash or verify state integrity.

    The rebuilt state will match what would have been stored in
    run_state.json if all events had been processed correctly.

    Args:
        run_id: The unique run identifier.
        runs_dir: Base directory for runs. Defaults to RUNS_DIR.

    Returns:
        The reconstructed RunState.

    Raises:
        StateRebuilderError: If events cannot be read or are malformed.
        FileNotFoundError: If no events exist for the run.

    Example:
        >>> state = rebuild_run_state("run-20251208-143022-abc123")
        >>> print(state.status)  # "running" or "succeeded" etc.
        >>> print(state.flow_key)  # "build" etc.
    """
    events = read_events(run_id, runs_dir)

    if not events:
        raise FileNotFoundError(f"No events found for run: {run_id}")

    # Initialize empty state - will be populated from events
    state = RunState(
        run_id=run_id,
        flow_key="",
        status="pending",
    )

    # Replay all events in order
    for event in events:
        state = _apply_event(state, event)

    return state


def _apply_event(state: RunState, event: RunEvent) -> RunState:
    """Apply a single event to the state.

    This is the core state transition function. Each event type has
    specific effects on the RunState fields.

    Args:
        state: The current RunState.
        event: The event to apply.

    Returns:
        The updated RunState.
    """
    kind = event.kind
    payload = event.payload or {}

    # Update timestamp from event
    state.timestamp = event.ts

    # Apply event based on kind
    if kind == "run_started":
        state = _apply_run_started(state, event, payload)

    elif kind == "step_started":
        state = _apply_step_started(state, event, payload)

    elif kind == "step_completed":
        state = _apply_step_completed(state, event, payload)

    elif kind == "route_decision":
        state = _apply_route_decision(state, event, payload)

    elif kind == "checkpoint":
        state = _apply_checkpoint(state, event, payload)

    elif kind == "flow_paused":
        state = _apply_flow_paused(state, event, payload)

    elif kind == "run_stopped":
        state = _apply_run_stopped(state, event, payload)

    elif kind == "run_completed":
        state = _apply_run_completed(state, event, payload)

    elif kind == "run_failed":
        state = _apply_run_failed(state, event, payload)

    elif kind == "flow_started":
        state = _apply_flow_started(state, event, payload)

    elif kind == "flow_completed":
        state = _apply_flow_completed(state, event, payload)

    elif kind == "macro_route":
        state = _apply_macro_route(state, event, payload)

    elif kind == "detour_started":
        state = _apply_detour_started(state, event, payload)

    elif kind == "detour_completed":
        state = _apply_detour_completed(state, event, payload)

    elif kind == "node_injected":
        state = _apply_node_injected(state, event, payload)

    # Log unhandled event types at debug level (they may be informational)
    else:
        logger.debug(
            "Unhandled event kind '%s' for run '%s' at step '%s'",
            kind,
            state.run_id,
            event.step_id,
        )

    return state


def _apply_run_started(
    state: RunState,
    event: RunEvent,
    payload: Dict[str, Any],
) -> RunState:
    """Apply run_started event.

    Sets the initial run state including flow_key, status, and flow index.
    """
    state.status = "running"
    state.flow_key = payload.get("flow_key", event.flow_key) or ""
    state.current_flow_index = payload.get("flow_index", 1)

    # Record flow transition if this is the first flow
    if state.flow_key:
        state.flow_transition_history.append({
            "flow_key": state.flow_key,
            "flow_index": state.current_flow_index,
            "action": "started",
            "timestamp": event.ts.isoformat() if event.ts else None,
        })

    return state


def _apply_step_started(
    state: RunState,
    event: RunEvent,
    payload: Dict[str, Any],
) -> RunState:
    """Apply step_started event.

    Updates current step tracking.
    """
    state.current_step_id = event.step_id or payload.get("step_id")
    state.step_index = payload.get("step_index", state.step_index)

    # Update flow_key if provided (for cross-flow navigation)
    if event.flow_key:
        state.flow_key = event.flow_key

    return state


def _apply_step_completed(
    state: RunState,
    event: RunEvent,
    payload: Dict[str, Any],
) -> RunState:
    """Apply step_completed event.

    Records the completed step and updates envelope if provided.
    """
    step_id = event.step_id or payload.get("step_id")

    if step_id:
        # Mark node as completed
        state.mark_node_completed(step_id)

        # If envelope data is in payload, parse and store it
        envelope_data = payload.get("envelope")
        if envelope_data:
            try:
                envelope = handoff_envelope_from_dict(envelope_data)
                state.handoff_envelopes[step_id] = envelope
            except (KeyError, TypeError) as e:
                logger.warning(
                    "Failed to parse envelope for step '%s': %s",
                    step_id,
                    e,
                )

        # Update step_index if provided
        if "next_step_index" in payload:
            state.step_index = payload["next_step_index"]

    return state


def _apply_route_decision(
    state: RunState,
    event: RunEvent,
    payload: Dict[str, Any],
) -> RunState:
    """Apply route_decision event.

    Updates routing-related state including loop counts.
    """
    # Update loop state if this is a loop decision
    loop_id = payload.get("loop_id")
    if loop_id:
        loop_count = payload.get("loop_count", 0)
        state.loop_state[loop_id] = loop_count

    # Handle next step/node if specified
    next_node = payload.get("next_node") or payload.get("next_step_id")
    if next_node:
        state.current_step_id = next_node

    # Handle step index updates
    if "step_index" in payload:
        state.step_index = payload["step_index"]

    return state


def _apply_checkpoint(
    state: RunState,
    event: RunEvent,
    payload: Dict[str, Any],
) -> RunState:
    """Apply checkpoint event.

    Checkpoints are markers for recovery; they may contain full state snapshots.
    """
    # If checkpoint contains a full state snapshot, merge it
    snapshot = payload.get("state_snapshot")
    if snapshot:
        # Merge selective fields from snapshot
        if "step_index" in snapshot:
            state.step_index = snapshot["step_index"]
        if "current_step_id" in snapshot:
            state.current_step_id = snapshot["current_step_id"]
        if "loop_state" in snapshot:
            state.loop_state.update(snapshot["loop_state"])

    return state


def _apply_flow_paused(
    state: RunState,
    event: RunEvent,
    payload: Dict[str, Any],
) -> RunState:
    """Apply flow_paused event.

    Pushes an interruption frame for later resumption.
    """
    state.status = "paused"

    reason = payload.get("reason", "paused")
    return_node = payload.get("return_node") or state.current_step_id or ""

    # Push interruption frame
    state.push_interruption(
        reason=reason,
        return_node=return_node,
        context_snapshot=payload.get("context", {}),
    )

    return state


def _apply_run_stopped(
    state: RunState,
    event: RunEvent,
    payload: Dict[str, Any],
) -> RunState:
    """Apply run_stopped event.

    Marks the run as cleanly stopped.
    """
    state.status = "stopped"
    return state


def _apply_run_completed(
    state: RunState,
    event: RunEvent,
    payload: Dict[str, Any],
) -> RunState:
    """Apply run_completed event.

    Marks the run as successfully completed.
    """
    state.status = payload.get("status", "succeeded")
    return state


def _apply_run_failed(
    state: RunState,
    event: RunEvent,
    payload: Dict[str, Any],
) -> RunState:
    """Apply run_failed event.

    Marks the run as failed.
    """
    state.status = "failed"
    return state


def _apply_flow_started(
    state: RunState,
    event: RunEvent,
    payload: Dict[str, Any],
) -> RunState:
    """Apply flow_started event.

    Updates flow tracking when a new flow begins.
    """
    state.flow_key = event.flow_key or payload.get("flow_key", state.flow_key)
    state.current_flow_index = payload.get("flow_index", state.current_flow_index)
    state.step_index = 0  # Reset step index for new flow
    state.current_step_id = None

    # Record flow transition
    state.flow_transition_history.append({
        "flow_key": state.flow_key,
        "flow_index": state.current_flow_index,
        "action": "started",
        "timestamp": event.ts.isoformat() if event.ts else None,
    })

    return state


def _apply_flow_completed(
    state: RunState,
    event: RunEvent,
    payload: Dict[str, Any],
) -> RunState:
    """Apply flow_completed event.

    Records flow completion in transition history.
    """
    flow_key = event.flow_key or payload.get("flow_key", state.flow_key)

    # Record flow transition
    state.flow_transition_history.append({
        "flow_key": flow_key,
        "flow_index": state.current_flow_index,
        "action": "completed",
        "outcome": payload.get("outcome", "succeeded"),
        "timestamp": event.ts.isoformat() if event.ts else None,
    })

    return state


def _apply_macro_route(
    state: RunState,
    event: RunEvent,
    payload: Dict[str, Any],
) -> RunState:
    """Apply macro_route event.

    Handles flow transitions and between-flow routing.
    """
    action = payload.get("action")
    next_flow = payload.get("to_flow") or payload.get("next_flow")

    if next_flow:
        state.flow_key = next_flow

    if "flow_index" in payload:
        state.current_flow_index = payload["flow_index"]

    # Record in transition history
    state.flow_transition_history.append({
        "flow_key": next_flow or state.flow_key,
        "from_flow": payload.get("from_flow"),
        "action": action or "advance",
        "reason": payload.get("reason"),
        "loop_count": payload.get("loop_count"),
        "timestamp": event.ts.isoformat() if event.ts else None,
    })

    return state


def _apply_detour_started(
    state: RunState,
    event: RunEvent,
    payload: Dict[str, Any],
) -> RunState:
    """Apply detour_started event.

    Pushes interruption frame for detour handling.
    """
    reason = payload.get("reason", "detour")
    return_node = payload.get("return_node") or state.current_step_id or ""
    sidequest_id = payload.get("sidequest_id")
    total_steps = payload.get("total_steps", 1)

    state.push_interruption(
        reason=reason,
        return_node=return_node,
        context_snapshot=payload.get("context", {}),
        current_step_index=0,
        total_steps=total_steps,
        sidequest_id=sidequest_id,
    )

    return state


def _apply_detour_completed(
    state: RunState,
    event: RunEvent,
    payload: Dict[str, Any],
) -> RunState:
    """Apply detour_completed event.

    Pops interruption frame and restores execution context.
    """
    frame = state.pop_interruption()

    if frame:
        # Restore to return node if specified
        if frame.return_node:
            state.current_step_id = frame.return_node

        # Restore context if present
        if frame.context_snapshot:
            # Selectively restore context fields
            if "step_index" in frame.context_snapshot:
                state.step_index = frame.context_snapshot["step_index"]

    return state


def _apply_node_injected(
    state: RunState,
    event: RunEvent,
    payload: Dict[str, Any],
) -> RunState:
    """Apply node_injected event.

    Registers a dynamically injected node.
    """
    node_id = payload.get("node_id")
    if not node_id:
        return state

    # Add to injected nodes list
    state.add_injected_node(node_id)

    # If full spec is provided, register it
    spec_data = payload.get("spec")
    if spec_data:
        try:
            spec = injected_node_spec_from_dict(spec_data)
            state.register_injected_node(spec)
        except (KeyError, TypeError) as e:
            logger.warning(
                "Failed to parse injected node spec for '%s': %s",
                node_id,
                e,
            )

    return state


def verify_run_state(
    run_id: RunId,
    runs_dir: Path = RUNS_DIR,
) -> bool:
    """Verify that stored run_state.json matches event-rebuilt state.

    This function compares the stored state against state rebuilt from
    the event log. Discrepancies indicate potential data corruption or
    incomplete event recording.

    Args:
        run_id: The unique run identifier.
        runs_dir: Base directory for runs. Defaults to RUNS_DIR.

    Returns:
        True if states match, False otherwise.

    Note:
        Returns True if no stored state exists (nothing to verify against).
        Returns False if events exist but no stored state exists.
    """
    stored_state = read_run_state(run_id, runs_dir)

    try:
        rebuilt_state = rebuild_run_state(run_id, runs_dir)
    except FileNotFoundError:
        # No events to rebuild from - this is OK if no state either
        return stored_state is None

    if stored_state is None:
        # Events exist but no stored state - this is a discrepancy
        logger.warning(
            "Run '%s' has events but no stored state - state may need recovery",
            run_id,
        )
        return False

    # Compare key fields
    mismatches: List[str] = []

    if stored_state.run_id != rebuilt_state.run_id:
        mismatches.append(f"run_id: {stored_state.run_id} vs {rebuilt_state.run_id}")

    if stored_state.flow_key != rebuilt_state.flow_key:
        mismatches.append(f"flow_key: {stored_state.flow_key} vs {rebuilt_state.flow_key}")

    if stored_state.status != rebuilt_state.status:
        mismatches.append(f"status: {stored_state.status} vs {rebuilt_state.status}")

    if stored_state.step_index != rebuilt_state.step_index:
        mismatches.append(f"step_index: {stored_state.step_index} vs {rebuilt_state.step_index}")

    if stored_state.current_step_id != rebuilt_state.current_step_id:
        mismatches.append(
            f"current_step_id: {stored_state.current_step_id} vs {rebuilt_state.current_step_id}"
        )

    if stored_state.current_flow_index != rebuilt_state.current_flow_index:
        mismatches.append(
            f"current_flow_index: {stored_state.current_flow_index} vs {rebuilt_state.current_flow_index}"
        )

    # Compare completed nodes (order-independent)
    stored_completed = set(stored_state.completed_nodes)
    rebuilt_completed = set(rebuilt_state.completed_nodes)
    if stored_completed != rebuilt_completed:
        mismatches.append(
            f"completed_nodes: {stored_completed} vs {rebuilt_completed}"
        )

    # Compare injected nodes (order-independent)
    stored_injected = set(stored_state.injected_nodes)
    rebuilt_injected = set(rebuilt_state.injected_nodes)
    if stored_injected != rebuilt_injected:
        mismatches.append(
            f"injected_nodes: {stored_injected} vs {rebuilt_injected}"
        )

    if mismatches:
        logger.warning(
            "State verification failed for run '%s':\n  %s",
            run_id,
            "\n  ".join(mismatches),
        )
        return False

    return True


def recover_run_state(
    run_id: RunId,
    runs_dir: Path = RUNS_DIR,
    force: bool = False,
) -> Optional[RunState]:
    """Attempt to recover RunState from events if stored state is missing/corrupt.

    This function provides crash recovery by rebuilding state from events.
    It is safe to call even if the stored state is valid (use force=True
    to always rebuild).

    Args:
        run_id: The unique run identifier.
        runs_dir: Base directory for runs. Defaults to RUNS_DIR.
        force: If True, always rebuild even if stored state is valid.

    Returns:
        The recovered RunState, or None if recovery failed.

    Note:
        Does NOT write the recovered state to disk. Caller should use
        storage.write_run_state() if they want to persist the recovery.
    """
    if not force:
        stored_state = read_run_state(run_id, runs_dir)
        if stored_state is not None:
            return stored_state

    try:
        return rebuild_run_state(run_id, runs_dir)
    except FileNotFoundError:
        logger.warning(
            "Cannot recover state for run '%s': no events found",
            run_id,
        )
        return None
    except Exception as e:
        logger.error(
            "Failed to recover state for run '%s': %s",
            run_id,
            e,
        )
        return None
