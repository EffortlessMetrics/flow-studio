"""
Tests for swarm/runtime/state_builder.py - RunState rebuilder from events.

Tests cover:
- rebuild_run_state: Core state reconstruction from events
- Event type handlers: Each event kind is applied correctly
- verify_run_state: State verification against stored state
- recover_run_state: Crash recovery functionality
- Edge cases: Missing events, malformed data, partial runs
"""

from datetime import datetime, timezone

import pytest

from swarm.runtime import storage
from swarm.runtime.state_builder import (
    rebuild_run_state,
    recover_run_state,
    verify_run_state,
    _apply_event,
)
from swarm.runtime.types import (
    HandoffEnvelope,
    RoutingDecision,
    RoutingSignal,
    RunEvent,
    RunState,
    handoff_envelope_to_dict,
)


class TestRebuildRunState:
    """Test core state reconstruction from events."""

    def test_rebuild_from_run_started(self, tmp_path):
        """Should initialize state from run_started event."""
        run_id = "test-rebuild-001"
        now = datetime.now(timezone.utc)

        event = RunEvent(
            run_id=run_id,
            ts=now,
            kind="run_started",
            flow_key="signal",
            payload={"flow_key": "signal", "flow_index": 1},
        )
        storage.append_event(run_id, event, runs_dir=tmp_path)

        state = rebuild_run_state(run_id, runs_dir=tmp_path)

        assert state.run_id == run_id
        assert state.flow_key == "signal"
        assert state.status == "running"
        assert state.current_flow_index == 1

    def test_rebuild_with_step_events(self, tmp_path):
        """Should track step progression through events."""
        run_id = "test-rebuild-002"
        now = datetime.now(timezone.utc)

        events = [
            RunEvent(
                run_id=run_id,
                ts=now,
                kind="run_started",
                flow_key="build",
                payload={"flow_key": "build", "flow_index": 3},
            ),
            RunEvent(
                run_id=run_id,
                ts=now,
                kind="step_started",
                flow_key="build",
                step_id="1",
                payload={"step_index": 0},
            ),
            RunEvent(
                run_id=run_id,
                ts=now,
                kind="step_completed",
                flow_key="build",
                step_id="1",
                payload={"next_step_index": 1},
            ),
            RunEvent(
                run_id=run_id,
                ts=now,
                kind="step_started",
                flow_key="build",
                step_id="2",
                payload={"step_index": 1},
            ),
        ]

        for event in events:
            storage.append_event(run_id, event, runs_dir=tmp_path)

        state = rebuild_run_state(run_id, runs_dir=tmp_path)

        assert state.current_step_id == "2"
        assert state.step_index == 1
        assert "1" in state.completed_nodes

    def test_rebuild_with_envelope(self, tmp_path):
        """Should reconstruct handoff envelopes from step_completed events."""
        run_id = "test-rebuild-003"
        now = datetime.now(timezone.utc)

        # Create a simple envelope
        envelope = HandoffEnvelope(
            step_id="1",
            flow_key="signal",
            run_id=run_id,
            routing_signal=RoutingSignal(
                decision=RoutingDecision.ADVANCE,
                next_step_id="2",
            ),
            summary="Step 1 completed successfully",
            status="succeeded",
        )

        events = [
            RunEvent(
                run_id=run_id,
                ts=now,
                kind="run_started",
                flow_key="signal",
                payload={"flow_key": "signal"},
            ),
            RunEvent(
                run_id=run_id,
                ts=now,
                kind="step_completed",
                flow_key="signal",
                step_id="1",
                payload={
                    "envelope": handoff_envelope_to_dict(envelope),
                    "next_step_index": 1,
                },
            ),
        ]

        for event in events:
            storage.append_event(run_id, event, runs_dir=tmp_path)

        state = rebuild_run_state(run_id, runs_dir=tmp_path)

        assert "1" in state.handoff_envelopes
        assert state.handoff_envelopes["1"].summary == "Step 1 completed successfully"

    def test_rebuild_run_completed(self, tmp_path):
        """Should mark run as succeeded on run_completed event."""
        run_id = "test-rebuild-004"
        now = datetime.now(timezone.utc)

        events = [
            RunEvent(
                run_id=run_id,
                ts=now,
                kind="run_started",
                flow_key="signal",
                payload={"flow_key": "signal"},
            ),
            RunEvent(
                run_id=run_id,
                ts=now,
                kind="run_completed",
                flow_key="signal",
                payload={"status": "succeeded"},
            ),
        ]

        for event in events:
            storage.append_event(run_id, event, runs_dir=tmp_path)

        state = rebuild_run_state(run_id, runs_dir=tmp_path)

        assert state.status == "succeeded"

    def test_rebuild_run_failed(self, tmp_path):
        """Should mark run as failed on run_failed event."""
        run_id = "test-rebuild-005"
        now = datetime.now(timezone.utc)

        events = [
            RunEvent(
                run_id=run_id,
                ts=now,
                kind="run_started",
                flow_key="signal",
                payload={"flow_key": "signal"},
            ),
            RunEvent(
                run_id=run_id,
                ts=now,
                kind="run_failed",
                flow_key="signal",
                payload={"error": "Something went wrong"},
            ),
        ]

        for event in events:
            storage.append_event(run_id, event, runs_dir=tmp_path)

        state = rebuild_run_state(run_id, runs_dir=tmp_path)

        assert state.status == "failed"

    def test_rebuild_no_events_raises(self, tmp_path):
        """Should raise FileNotFoundError when no events exist."""
        with pytest.raises(FileNotFoundError, match="No events found"):
            rebuild_run_state("nonexistent-run", runs_dir=tmp_path)


class TestRouteDecisionEvents:
    """Test route_decision event handling."""

    def test_loop_state_updated(self, tmp_path):
        """Should update loop_state from route_decision events."""
        run_id = "test-route-001"
        now = datetime.now(timezone.utc)

        events = [
            RunEvent(
                run_id=run_id,
                ts=now,
                kind="run_started",
                flow_key="build",
                payload={"flow_key": "build"},
            ),
            RunEvent(
                run_id=run_id,
                ts=now,
                kind="route_decision",
                flow_key="build",
                step_id="3",
                payload={
                    "loop_id": "test-critic-loop",
                    "loop_count": 2,
                    "decision": "CONTINUE",
                },
            ),
        ]

        for event in events:
            storage.append_event(run_id, event, runs_dir=tmp_path)

        state = rebuild_run_state(run_id, runs_dir=tmp_path)

        assert state.loop_state.get("test-critic-loop") == 2

    def test_next_node_updated(self, tmp_path):
        """Should update current_step_id from route_decision next_node."""
        run_id = "test-route-002"
        now = datetime.now(timezone.utc)

        events = [
            RunEvent(
                run_id=run_id,
                ts=now,
                kind="run_started",
                flow_key="build",
                payload={"flow_key": "build"},
            ),
            RunEvent(
                run_id=run_id,
                ts=now,
                kind="route_decision",
                flow_key="build",
                payload={"next_node": "5", "decision": "CONTINUE"},
            ),
        ]

        for event in events:
            storage.append_event(run_id, event, runs_dir=tmp_path)

        state = rebuild_run_state(run_id, runs_dir=tmp_path)

        assert state.current_step_id == "5"


class TestFlowEvents:
    """Test flow lifecycle events."""

    def test_flow_started(self, tmp_path):
        """Should update flow tracking on flow_started event."""
        run_id = "test-flow-001"
        now = datetime.now(timezone.utc)

        events = [
            RunEvent(
                run_id=run_id,
                ts=now,
                kind="run_started",
                flow_key="signal",
                payload={"flow_key": "signal", "flow_index": 1},
            ),
            RunEvent(
                run_id=run_id,
                ts=now,
                kind="flow_completed",
                flow_key="signal",
                payload={"outcome": "succeeded"},
            ),
            RunEvent(
                run_id=run_id,
                ts=now,
                kind="flow_started",
                flow_key="plan",
                payload={"flow_key": "plan", "flow_index": 2},
            ),
        ]

        for event in events:
            storage.append_event(run_id, event, runs_dir=tmp_path)

        state = rebuild_run_state(run_id, runs_dir=tmp_path)

        assert state.flow_key == "plan"
        assert state.current_flow_index == 2
        assert state.step_index == 0  # Reset for new flow
        assert len(state.flow_transition_history) >= 2

    def test_macro_route(self, tmp_path):
        """Should handle macro_route events for flow transitions."""
        run_id = "test-flow-002"
        now = datetime.now(timezone.utc)

        events = [
            RunEvent(
                run_id=run_id,
                ts=now,
                kind="run_started",
                flow_key="gate",
                payload={"flow_key": "gate", "flow_index": 5},
            ),
            RunEvent(
                run_id=run_id,
                ts=now,
                kind="macro_route",
                flow_key="gate",
                payload={
                    "action": "goto",
                    "from_flow": "gate",
                    "to_flow": "build",
                    "reason": "BOUNCE_BUILD",
                    "loop_count": 1,
                },
            ),
        ]

        for event in events:
            storage.append_event(run_id, event, runs_dir=tmp_path)

        state = rebuild_run_state(run_id, runs_dir=tmp_path)

        assert state.flow_key == "build"
        # Check transition was recorded
        assert any(
            t.get("reason") == "BOUNCE_BUILD"
            for t in state.flow_transition_history
        )


class TestDetourEvents:
    """Test detour (interruption) event handling."""

    def test_flow_paused(self, tmp_path):
        """Should push interruption frame on flow_paused event."""
        run_id = "test-detour-001"
        now = datetime.now(timezone.utc)

        events = [
            RunEvent(
                run_id=run_id,
                ts=now,
                kind="run_started",
                flow_key="build",
                payload={"flow_key": "build"},
            ),
            RunEvent(
                run_id=run_id,
                ts=now,
                kind="step_started",
                flow_key="build",
                step_id="3",
                payload={"step_index": 2},
            ),
            RunEvent(
                run_id=run_id,
                ts=now,
                kind="flow_paused",
                flow_key="build",
                payload={
                    "reason": "human_review",
                    "return_node": "3",
                },
            ),
        ]

        for event in events:
            storage.append_event(run_id, event, runs_dir=tmp_path)

        state = rebuild_run_state(run_id, runs_dir=tmp_path)

        assert state.status == "paused"
        assert state.is_interrupted()
        frame = state.peek_interruption()
        assert frame is not None
        assert frame.reason == "human_review"
        assert frame.return_node == "3"

    def test_detour_started_completed(self, tmp_path):
        """Should handle detour lifecycle correctly."""
        run_id = "test-detour-002"
        now = datetime.now(timezone.utc)

        events = [
            RunEvent(
                run_id=run_id,
                ts=now,
                kind="run_started",
                flow_key="build",
                payload={"flow_key": "build"},
            ),
            RunEvent(
                run_id=run_id,
                ts=now,
                kind="step_started",
                flow_key="build",
                step_id="5",
                payload={"step_index": 4},
            ),
            RunEvent(
                run_id=run_id,
                ts=now,
                kind="detour_started",
                flow_key="build",
                payload={
                    "reason": "lint_fix_sidequest",
                    "return_node": "5",
                    "sidequest_id": "sq-lint-fix",
                    "total_steps": 2,
                },
            ),
            RunEvent(
                run_id=run_id,
                ts=now,
                kind="detour_completed",
                flow_key="build",
                payload={"sidequest_id": "sq-lint-fix"},
            ),
        ]

        for event in events:
            storage.append_event(run_id, event, runs_dir=tmp_path)

        state = rebuild_run_state(run_id, runs_dir=tmp_path)

        # After detour completed, interruption stack should be empty
        assert not state.is_interrupted()
        # Should have returned to step 5
        assert state.current_step_id == "5"

    def test_node_injected(self, tmp_path):
        """Should register injected nodes."""
        run_id = "test-detour-003"
        now = datetime.now(timezone.utc)

        events = [
            RunEvent(
                run_id=run_id,
                ts=now,
                kind="run_started",
                flow_key="build",
                payload={"flow_key": "build"},
            ),
            RunEvent(
                run_id=run_id,
                ts=now,
                kind="node_injected",
                flow_key="build",
                payload={
                    "node_id": "sq-lint-fix-0",
                    "spec": {
                        "node_id": "sq-lint-fix-0",
                        "station_id": "lint-fixer",
                        "agent_key": "auto-linter",
                        "sidequest_origin": "sq-lint-fix",
                        "sequence_index": 0,
                        "total_in_sequence": 1,
                    },
                },
            ),
        ]

        for event in events:
            storage.append_event(run_id, event, runs_dir=tmp_path)

        state = rebuild_run_state(run_id, runs_dir=tmp_path)

        assert "sq-lint-fix-0" in state.injected_nodes
        spec = state.get_injected_node_spec("sq-lint-fix-0")
        assert spec is not None
        assert spec.station_id == "lint-fixer"
        assert spec.sidequest_origin == "sq-lint-fix"


class TestCheckpointEvents:
    """Test checkpoint event handling."""

    def test_checkpoint_restores_state(self, tmp_path):
        """Should merge state snapshot from checkpoint events."""
        run_id = "test-checkpoint-001"
        now = datetime.now(timezone.utc)

        events = [
            RunEvent(
                run_id=run_id,
                ts=now,
                kind="run_started",
                flow_key="build",
                payload={"flow_key": "build"},
            ),
            RunEvent(
                run_id=run_id,
                ts=now,
                kind="checkpoint",
                flow_key="build",
                payload={
                    "state_snapshot": {
                        "step_index": 5,
                        "current_step_id": "6",
                        "loop_state": {"critic-loop": 3},
                    },
                },
            ),
        ]

        for event in events:
            storage.append_event(run_id, event, runs_dir=tmp_path)

        state = rebuild_run_state(run_id, runs_dir=tmp_path)

        assert state.step_index == 5
        assert state.current_step_id == "6"
        assert state.loop_state.get("critic-loop") == 3


class TestVerifyRunState:
    """Test state verification against stored state."""

    def test_verify_matching_states(self, tmp_path):
        """Should return True when stored state matches rebuilt state."""
        run_id = "test-verify-001"
        now = datetime.now(timezone.utc)

        # Create events
        events = [
            RunEvent(
                run_id=run_id,
                ts=now,
                kind="run_started",
                flow_key="signal",
                payload={"flow_key": "signal", "flow_index": 1},
            ),
            RunEvent(
                run_id=run_id,
                ts=now,
                kind="step_started",
                flow_key="signal",
                step_id="1",
                payload={"step_index": 0},
            ),
        ]

        for event in events:
            storage.append_event(run_id, event, runs_dir=tmp_path)

        # Create matching stored state
        state = RunState(
            run_id=run_id,
            flow_key="signal",
            status="running",
            current_step_id="1",
            step_index=0,
            current_flow_index=1,
        )
        storage.write_run_state(run_id, state, runs_dir=tmp_path)

        assert verify_run_state(run_id, runs_dir=tmp_path) is True

    def test_verify_mismatched_status(self, tmp_path):
        """Should return False when status differs."""
        run_id = "test-verify-002"
        now = datetime.now(timezone.utc)

        # Create events that lead to "running" status
        event = RunEvent(
            run_id=run_id,
            ts=now,
            kind="run_started",
            flow_key="signal",
            payload={"flow_key": "signal"},
        )
        storage.append_event(run_id, event, runs_dir=tmp_path)

        # Create stored state with different status
        state = RunState(
            run_id=run_id,
            flow_key="signal",
            status="paused",  # Mismatch!
        )
        storage.write_run_state(run_id, state, runs_dir=tmp_path)

        assert verify_run_state(run_id, runs_dir=tmp_path) is False

    def test_verify_no_stored_state_but_events_exist(self, tmp_path):
        """Should return False when events exist but no stored state."""
        run_id = "test-verify-003"
        now = datetime.now(timezone.utc)

        event = RunEvent(
            run_id=run_id,
            ts=now,
            kind="run_started",
            flow_key="signal",
            payload={"flow_key": "signal"},
        )
        storage.append_event(run_id, event, runs_dir=tmp_path)

        # No stored state written
        assert verify_run_state(run_id, runs_dir=tmp_path) is False

    def test_verify_no_events_no_state(self, tmp_path):
        """Should return True when neither events nor state exist."""
        # Nothing exists - this is consistent
        assert verify_run_state("nonexistent-run", runs_dir=tmp_path) is True


class TestRecoverRunState:
    """Test crash recovery functionality."""

    def test_recover_returns_stored_state_if_exists(self, tmp_path):
        """Should return stored state without force flag."""
        run_id = "test-recover-001"

        # Create stored state
        state = RunState(
            run_id=run_id,
            flow_key="build",
            status="running",
            step_index=5,
        )
        storage.write_run_state(run_id, state, runs_dir=tmp_path)

        recovered = recover_run_state(run_id, runs_dir=tmp_path)

        assert recovered is not None
        assert recovered.step_index == 5

    def test_recover_rebuilds_when_no_stored_state(self, tmp_path):
        """Should rebuild from events when no stored state exists."""
        run_id = "test-recover-002"
        now = datetime.now(timezone.utc)

        events = [
            RunEvent(
                run_id=run_id,
                ts=now,
                kind="run_started",
                flow_key="signal",
                payload={"flow_key": "signal"},
            ),
            RunEvent(
                run_id=run_id,
                ts=now,
                kind="step_started",
                flow_key="signal",
                step_id="2",
                payload={"step_index": 1},
            ),
        ]

        for event in events:
            storage.append_event(run_id, event, runs_dir=tmp_path)

        recovered = recover_run_state(run_id, runs_dir=tmp_path)

        assert recovered is not None
        assert recovered.flow_key == "signal"
        assert recovered.current_step_id == "2"

    def test_recover_force_rebuilds(self, tmp_path):
        """Should rebuild from events when force=True even if stored state exists."""
        run_id = "test-recover-003"
        now = datetime.now(timezone.utc)

        # Create stored state with stale data
        stale_state = RunState(
            run_id=run_id,
            flow_key="signal",
            status="running",
            step_index=0,
        )
        storage.write_run_state(run_id, stale_state, runs_dir=tmp_path)

        # Create events showing more progress
        events = [
            RunEvent(
                run_id=run_id,
                ts=now,
                kind="run_started",
                flow_key="signal",
                payload={"flow_key": "signal"},
            ),
            RunEvent(
                run_id=run_id,
                ts=now,
                kind="step_completed",
                flow_key="signal",
                step_id="1",
                payload={"next_step_index": 1},
            ),
            RunEvent(
                run_id=run_id,
                ts=now,
                kind="step_started",
                flow_key="signal",
                step_id="2",
                payload={"step_index": 1},
            ),
            RunEvent(
                run_id=run_id,
                ts=now,
                kind="run_completed",
                flow_key="signal",
                payload={"status": "succeeded"},
            ),
        ]

        for event in events:
            storage.append_event(run_id, event, runs_dir=tmp_path)

        recovered = recover_run_state(run_id, runs_dir=tmp_path, force=True)

        assert recovered is not None
        assert recovered.status == "succeeded"  # From events, not stale state
        assert recovered.step_index == 1

    def test_recover_returns_none_when_no_events(self, tmp_path):
        """Should return None when no events exist and no stored state."""
        recovered = recover_run_state("nonexistent-run", runs_dir=tmp_path)
        assert recovered is None


class TestApplyEventDirect:
    """Test _apply_event function directly for edge cases."""

    def test_unhandled_event_kind_logged(self):
        """Should handle unknown event kinds gracefully."""
        state = RunState(run_id="test", flow_key="signal", status="running")
        now = datetime.now(timezone.utc)

        event = RunEvent(
            run_id="test",
            ts=now,
            kind="some_unknown_event_type",
            flow_key="signal",
        )

        # Should not raise, just log and return unchanged state
        result = _apply_event(state, event)

        assert result.run_id == "test"
        assert result.status == "running"

    def test_run_stopped_event(self):
        """Should handle run_stopped event."""
        state = RunState(run_id="test", flow_key="signal", status="running")
        now = datetime.now(timezone.utc)

        event = RunEvent(
            run_id="test",
            ts=now,
            kind="run_stopped",
            flow_key="signal",
            payload={},
        )

        result = _apply_event(state, event)

        assert result.status == "stopped"
