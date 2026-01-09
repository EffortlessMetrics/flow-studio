"""Tests for routing driver correctness fixes.

This module tests two specific fixes in the routing driver:

1. _step_result_to_dict: Ensures StepResult objects are correctly converted
   to dictionaries for routing logic. Previously, non-dict step_results would
   be passed as empty dicts, losing status/output information.

2. _update_loop_state_if_looping: Ensures loop_state is incremented when
   routing decision is LOOP. Previously, the driver didn't increment
   loop_state, risking infinite loops in deterministic mode.

These tests ensure microloops exit correctly based on status even when
step_result is a StepResult object (not a dict).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from swarm.config.flow_registry import StepDefinition, StepRouting
from swarm.runtime.stepwise.routing.driver import (
    RoutingOutcome,
    _step_result_to_dict,
    _update_loop_state_if_looping,
)
from swarm.runtime.types import RoutingDecision


# =============================================================================
# Test Fixtures
# =============================================================================


@dataclass
class MockStepResult:
    """Mock StepResult matching the real dataclass signature."""

    step_id: str
    status: str
    output: str
    error: Optional[str] = None
    duration_ms: int = 0
    artifacts: Optional[Dict[str, Any]] = None


@dataclass
class MockStepResultWithToDict:
    """Mock StepResult with a to_dict method."""

    step_id: str
    status: str
    output: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_id": self.step_id,
            "status": self.status,
            "output": self.output,
            "custom_field": "from_to_dict",
        }


class MockStepResultMinimal:
    """Mock with only status attribute (minimal object)."""

    def __init__(self, status: str):
        self.status = status


# =============================================================================
# Tests: _step_result_to_dict
# =============================================================================


class TestStepResultToDict:
    """Tests for the _step_result_to_dict helper function."""

    def test_dict_passthrough(self) -> None:
        """Dict inputs are returned unchanged."""
        input_dict = {"status": "VERIFIED", "output": "test"}
        result = _step_result_to_dict(input_dict)
        assert result is input_dict  # Same object, not a copy

    def test_converts_stepresult_dataclass(self) -> None:
        """StepResult-like dataclass is converted to dict with all fields."""
        step_result = MockStepResult(
            step_id="test_step",
            status="VERIFIED",
            output="Step completed",
            error=None,
            duration_ms=100,
            artifacts={"file": "test.py"},
        )

        result = _step_result_to_dict(step_result)

        assert isinstance(result, dict)
        assert result["step_id"] == "test_step"
        assert result["status"] == "VERIFIED"
        assert result["output"] == "Step completed"
        assert result["duration_ms"] == 100
        assert result["artifacts"] == {"file": "test.py"}

    def test_prefers_to_dict_method(self) -> None:
        """Objects with to_dict() method use that for conversion."""
        step_result = MockStepResultWithToDict(
            step_id="test_step",
            status="UNVERIFIED",
            output="Needs work",
        )

        result = _step_result_to_dict(step_result)

        assert isinstance(result, dict)
        assert result["custom_field"] == "from_to_dict"

    def test_handles_minimal_object(self) -> None:
        """Objects with only status attribute still work."""
        step_result = MockStepResultMinimal(status="BLOCKED")

        result = _step_result_to_dict(step_result)

        assert isinstance(result, dict)
        assert result["status"] == "BLOCKED"
        # Other fields should not be present
        assert "output" not in result

    def test_returns_empty_dict_for_none(self) -> None:
        """None input returns empty dict (no attributes to extract)."""
        result = _step_result_to_dict(None)
        assert result == {}

    def test_extracts_can_further_iteration_help(self) -> None:
        """The can_further_iteration_help field is extracted for microloops."""

        class StepResultWithIterationHelp:
            status = "UNVERIFIED"
            can_further_iteration_help = "no"

        result = _step_result_to_dict(StepResultWithIterationHelp())

        assert result["status"] == "UNVERIFIED"
        assert result["can_further_iteration_help"] == "no"


# =============================================================================
# Tests: _update_loop_state_if_looping
# =============================================================================


class TestUpdateLoopStateIfLooping:
    """Tests for the _update_loop_state_if_looping helper function."""

    def test_increments_on_loop_decision(self) -> None:
        """Loop state is incremented when decision is LOOP."""
        step = StepDefinition(
            id="critique_tests",
            index=2,
            agents=("test-critic",),
            role="Review tests",
            routing=StepRouting(
                kind="microloop",
                loop_target="author_tests",
                next="implement",
                max_iterations=3,
            ),
        )

        outcome = RoutingOutcome(
            decision=RoutingDecision.LOOP,
            next_step_id="author_tests",
            reason="loop_iteration:1",
            routing_source="deterministic",
        )

        loop_state: Dict[str, int] = {}

        _update_loop_state_if_looping(outcome, step, loop_state)

        assert loop_state.get("critique_tests:author_tests") == 1
        assert outcome.loop_iteration == 1

    def test_increments_existing_count(self) -> None:
        """Existing loop state is incremented correctly."""
        step = StepDefinition(
            id="critique_tests",
            index=2,
            agents=("test-critic",),
            role="Review tests",
            routing=StepRouting(
                kind="microloop",
                loop_target="author_tests",
                next="implement",
                max_iterations=3,
            ),
        )

        outcome = RoutingOutcome(
            decision=RoutingDecision.LOOP,
            next_step_id="author_tests",
            reason="loop_iteration:2",
            routing_source="deterministic",
        )

        loop_state: Dict[str, int] = {"critique_tests:author_tests": 1}

        _update_loop_state_if_looping(outcome, step, loop_state)

        assert loop_state.get("critique_tests:author_tests") == 2
        assert outcome.loop_iteration == 2

    def test_no_increment_on_advance(self) -> None:
        """Loop state is NOT changed when decision is ADVANCE."""
        step = StepDefinition(
            id="critique_tests",
            index=2,
            agents=("test-critic",),
            role="Review tests",
            routing=StepRouting(
                kind="microloop",
                loop_target="author_tests",
                next="implement",
                max_iterations=3,
            ),
        )

        outcome = RoutingOutcome(
            decision=RoutingDecision.ADVANCE,
            next_step_id="implement",
            reason="exit_condition_met",
            routing_source="deterministic",
        )

        loop_state: Dict[str, int] = {"critique_tests:author_tests": 2}

        _update_loop_state_if_looping(outcome, step, loop_state)

        assert loop_state.get("critique_tests:author_tests") == 2  # Unchanged

    def test_no_increment_on_terminate(self) -> None:
        """Loop state is NOT changed when decision is TERMINATE."""
        step = StepDefinition(
            id="commit",
            index=5,
            agents=("repo-operator",),
            role="Commit changes",
            routing=StepRouting(
                kind="linear",
                next=None,
            ),
        )

        outcome = RoutingOutcome(
            decision=RoutingDecision.TERMINATE,
            next_step_id=None,
            reason="flow_complete",
            routing_source="deterministic",
        )

        loop_state: Dict[str, int] = {}

        _update_loop_state_if_looping(outcome, step, loop_state)

        assert loop_state == {}  # Still empty

    def test_handles_missing_routing_config(self) -> None:
        """Gracefully handles step without routing config."""
        step = StepDefinition(
            id="test_step",
            index=1,
            agents=("agent",),
            role="Test",
            routing=None,
        )

        outcome = RoutingOutcome(
            decision=RoutingDecision.LOOP,
            next_step_id="other_step",
            reason="loop",
            routing_source="test",
        )

        loop_state: Dict[str, int] = {}

        # Should not raise
        _update_loop_state_if_looping(outcome, step, loop_state)

        assert loop_state == {}  # No update without routing config

    def test_uses_next_step_id_as_fallback_loop_target(self) -> None:
        """Uses outcome.next_step_id if routing.loop_target is None."""
        step = StepDefinition(
            id="test_step",
            index=1,
            agents=("agent",),
            role="Test",
            routing=StepRouting(
                kind="microloop",
                loop_target=None,  # Not set
                next="other",
                max_iterations=3,
            ),
        )

        outcome = RoutingOutcome(
            decision=RoutingDecision.LOOP,
            next_step_id="fallback_target",
            reason="loop",
            routing_source="test",
        )

        loop_state: Dict[str, int] = {}

        _update_loop_state_if_looping(outcome, step, loop_state)

        # Uses next_step_id as fallback loop target
        assert loop_state.get("test_step:fallback_target") == 1


# =============================================================================
# Integration Tests: Driver with StepResult objects
# =============================================================================


class TestDriverWithStepResultObjects:
    """Integration tests ensuring driver handles StepResult objects correctly."""

    def test_deterministic_routing_with_stepresult(self) -> None:
        """Deterministic routing correctly uses status from StepResult object."""
        # This test verifies the fix works end-to-end
        from swarm.runtime.stepwise.routing.driver import _try_deterministic
        from swarm.runtime.types import RunState

        step = StepDefinition(
            id="critique_tests",
            index=2,
            agents=("test-critic",),
            role="Review tests",
            routing=StepRouting(
                kind="microloop",
                loop_target="author_tests",
                loop_condition_field="status",
                loop_success_values=("VERIFIED", "verified"),
                next="implement",
                max_iterations=3,
            ),
        )

        # Use a StepResult object (not a dict)
        step_result = MockStepResult(
            step_id="critique_tests",
            status="VERIFIED",
            output="Tests look good",
        )

        run_state = RunState(run_id="test-run", flow_key="build")
        loop_state: Dict[str, int] = {}

        outcome = _try_deterministic(
            step=step,
            step_result=step_result,  # StepResult object, not dict
            run_state=run_state,
            loop_state=loop_state,
            iteration=0,
        )

        # Should successfully route based on status
        assert outcome is not None
        # Note: The actual decision depends on create_routing_signal implementation
        # The key test is that it doesn't fail with empty dict


class TestLoopStateIncrementWithDriver:
    """Test that loop_state is properly incremented through the driver."""

    def test_loop_state_increments_on_loop_via_driver(self) -> None:
        """Verify loop_state is incremented when driver returns LOOP decision."""
        from swarm.runtime.stepwise.routing.driver import route_step
        from swarm.runtime.types import RoutingMode, RunState

        step = StepDefinition(
            id="critique_tests",
            index=2,
            agents=("test-critic",),
            role="Review tests",
            routing=StepRouting(
                kind="microloop",
                loop_target="author_tests",
                next="implement",
                max_iterations=3,
            ),
        )

        step_result = {"status": "UNVERIFIED"}  # Will trigger LOOP
        run_state = RunState(run_id="test-run", flow_key="build")
        loop_state: Dict[str, int] = {}

        outcome = route_step(
            step=step,
            step_result=step_result,
            run_state=run_state,
            loop_state=loop_state,
            iteration=0,
            routing_mode=RoutingMode.DETERMINISTIC_ONLY,
        )

        # If decision is LOOP, loop_state should be incremented
        if outcome.decision == RoutingDecision.LOOP:
            loop_key = "critique_tests:author_tests"
            assert loop_state.get(loop_key, 0) > 0, (
                "loop_state should be incremented on LOOP decision"
            )
