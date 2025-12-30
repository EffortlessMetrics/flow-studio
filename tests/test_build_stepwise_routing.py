"""Tests for Build flow stepwise routing logic.

This module validates the `route_step` function with synthetic step results
and receipts. It proves the routing logic works for Build microloops without needing
real LLM execution.

## Test Coverage

### Microloop Routing (4 tests)
1. test_verified_exits_loop - When status=VERIFIED, loop exits to next step
2. test_unverified_can_help_loops_back - When status=UNVERIFIED and can_help=yes, loops back
3. test_unverified_cannot_help_exits - When status=UNVERIFIED and can_help=no, exits loop
4. test_max_iterations_limits_loops - After max iterations, exits even if can_help=yes

### Linear Routing (2 tests)
5. test_linear_routing_advances - Linear steps advance to next step
6. test_linear_routing_flow_complete - Final linear step terminates flow

### Loop State Tracking (2 tests)
7. test_loop_state_increments - Loop counter increments on each iteration
8. test_loop_state_resets_on_different_loop - Different loops have independent counters

## Patterns Used

- Uses synthetic step results (no real engine execution)
- Uses synthetic receipts written to temp directories
- Tests the `route_step` function directly from the stepwise routing module
- Follows existing test patterns from test_gemini_stepwise_backend.py
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Optional
from unittest.mock import MagicMock

import pytest

# Add repo root to path for imports
repo_root = Path(__file__).resolve().parents[1]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from swarm.config.flow_registry import (
    FlowDefinition,
    FlowRegistry,
    StepDefinition,
    StepRouting,
    TeachingNotes,
)
from swarm.runtime.stepwise import route_step, read_receipt_field


# -----------------------------------------------------------------------------
# Fixtures and Helpers
# -----------------------------------------------------------------------------


@pytest.fixture
def tmp_repo(tmp_path: Path) -> Path:
    """Create a temporary repo structure for testing."""
    runs_dir = tmp_path / "swarm" / "runs"
    runs_dir.mkdir(parents=True)
    return tmp_path


def make_receipt_reader(tmp_repo: Path) -> Callable[..., Optional[str]]:
    """Create a receipt_reader callable bound to a repo root.

    Returns a function with signature:
        (run_id, flow_key, step_id, agent_key, field_name) -> Optional[str]
    """
    def reader(
        run_id: str,
        flow_key: str,
        step_id: str,
        agent_key: str,
        field_name: str,
    ) -> Optional[str]:
        return read_receipt_field(
            repo_root=tmp_repo,
            run_id=run_id,
            flow_key=flow_key,
            step_id=step_id,
            agent_key=agent_key,
            field_name=field_name,
        )
    return reader


@pytest.fixture
def build_flow_def() -> FlowDefinition:
    """Create a mock Build flow definition with test/code microloops.

    Mimics the real Build flow structure:
    - author_tests -> critique_tests (microloop)
    - implement -> critique_code (microloop)
    """
    # Test microloop: author_tests <-> critique_tests
    author_tests = StepDefinition(
        id="author_tests",
        index=1,
        agents=("test-author",),
        role="Write tests for the current subtask",
        routing=StepRouting(
            kind="linear",
            next="critique_tests",
        ),
    )

    critique_tests = StepDefinition(
        id="critique_tests",
        index=2,
        agents=("test-critic",),
        role="Harsh review of tests vs BDD/spec",
        routing=StepRouting(
            kind="microloop",
            loop_target="author_tests",
            loop_condition_field="status",
            loop_success_values=("VERIFIED", "verified"),
            next="implement",
            max_iterations=3,
        ),
    )

    # Code microloop: implement <-> critique_code
    implement = StepDefinition(
        id="implement",
        index=3,
        agents=("code-implementer",),
        role="Write code to pass tests, follow ADR",
        routing=StepRouting(
            kind="linear",
            next="critique_code",
        ),
    )

    critique_code = StepDefinition(
        id="critique_code",
        index=4,
        agents=("code-critic",),
        role="Harsh review of code vs ADR/contracts",
        routing=StepRouting(
            kind="microloop",
            loop_target="implement",
            loop_condition_field="status",
            loop_success_values=("VERIFIED", "verified"),
            next="commit",
            max_iterations=3,
        ),
    )

    commit = StepDefinition(
        id="commit",
        index=5,
        agents=("repo-operator",),
        role="Stage changes, commit to feature branch",
        routing=StepRouting(
            kind="linear",
            next=None,  # Final step
        ),
    )

    return FlowDefinition(
        key="build",
        index=3,
        title="Flow 3 - Plan → Code (Build)",
        short_title="Build",
        description="Implement via adversarial microloops",
        steps=(author_tests, critique_tests, implement, critique_code, commit),
    )


def write_receipt(
    tmp_repo: Path,
    run_id: str,
    flow_key: str,
    step_id: str,
    agent_key: str,
    status: str = "succeeded",
    can_further_iteration_help: Optional[str] = None,
) -> Path:
    """Write a synthetic receipt file for testing routing decisions.

    Args:
        tmp_repo: Temporary repo root path.
        run_id: Run identifier.
        flow_key: Flow key (e.g., "build").
        step_id: Step identifier (e.g., "critique_tests").
        agent_key: Agent key (e.g., "test-critic").
        status: Receipt status field - used for loop exit condition.
        can_further_iteration_help: Optional fallback field.

    Returns:
        Path to the created receipt file.
    """
    run_base = tmp_repo / "swarm" / "runs" / run_id / flow_key
    receipts_dir = run_base / "receipts"
    receipts_dir.mkdir(parents=True, exist_ok=True)

    receipt = {
        "engine": "test-engine",
        "mode": "stub",
        "provider": "test",
        "model": "test-model",
        "step_id": step_id,
        "flow_key": flow_key,
        "run_id": run_id,
        "agent_key": agent_key,
        "started_at": datetime.now(timezone.utc).isoformat() + "Z",
        "completed_at": datetime.now(timezone.utc).isoformat() + "Z",
        "duration_ms": 100,
        "status": status,  # This is the routing field checked by orchestrator
        "tokens": {"prompt": 0, "completion": 0, "total": 0},
    }

    if can_further_iteration_help is not None:
        receipt["can_further_iteration_help"] = can_further_iteration_help

    receipt_path = receipts_dir / f"{step_id}-{agent_key}.json"
    with receipt_path.open("w", encoding="utf-8") as f:
        json.dump(receipt, f, indent=2)

    return receipt_path


# -----------------------------------------------------------------------------
# Test Class: Microloop Routing
# -----------------------------------------------------------------------------


class TestMicroloopRouting:
    """Tests for microloop routing decisions."""

    def test_verified_exits_loop(
        self,
        build_flow_def: FlowDefinition,
        tmp_repo: Path,
    ) -> None:
        """When status=VERIFIED in receipt, loop exits to next step.

        The routing logic should check the receipt's status field against
        loop_success_values and advance to the next step when matched.
        """
        run_id = "test-verified-exit"

        # Write receipt with VERIFIED status
        write_receipt(
            tmp_repo=tmp_repo,
            run_id=run_id,
            flow_key="build",
            step_id="critique_tests",
            agent_key="test-critic",
            status="VERIFIED",
        )

        # Get the critique_tests step (has microloop routing)
        critique_step = build_flow_def.steps[1]
        assert critique_step.id == "critique_tests"

        # Call route_step
        loop_state: Dict[str, int] = {}
        result = {}  # Step result (not used for receipt-based routing)

        next_step_id, reason = route_step(
            flow_def=build_flow_def,
            current_step=critique_step,
            result=result,
            loop_state=loop_state,
            run_id=run_id,
            flow_key="build",
            receipt_reader=make_receipt_reader(tmp_repo),
        )

        # Should exit to next step (implement)
        assert next_step_id == "implement", (
            f"Expected next step 'implement', got '{next_step_id}'"
        )
        assert "loop_exit_condition_met" in reason or "VERIFIED" in reason, (
            f"Expected reason to indicate condition met, got '{reason}'"
        )

    def test_unverified_can_help_loops_back(
        self,
        build_flow_def: FlowDefinition,
        tmp_repo: Path,
    ) -> None:
        """When status=UNVERIFIED and can_further_iteration_help=yes, loops back.

        The routing logic should check the fallback field and loop back to
        the target step when further iteration can help.
        """
        run_id = "test-unverified-loop"

        # Write receipt with UNVERIFIED status and can_help=yes
        write_receipt(
            tmp_repo=tmp_repo,
            run_id=run_id,
            flow_key="build",
            step_id="critique_tests",
            agent_key="test-critic",
            status="UNVERIFIED",
            can_further_iteration_help="yes",
        )

        # Get the critique_tests step
        critique_step = build_flow_def.steps[1]

        # Call route_step with fresh loop state
        loop_state: Dict[str, int] = {}
        result = {}

        next_step_id, reason = route_step(
            flow_def=build_flow_def,
            current_step=critique_step,
            result=result,
            loop_state=loop_state,
            run_id=run_id,
            flow_key="build",
            receipt_reader=make_receipt_reader(tmp_repo),
        )

        # Should loop back to author_tests
        assert next_step_id == "author_tests", (
            f"Expected loop back to 'author_tests', got '{next_step_id}'"
        )
        assert "loop_iteration" in reason, (
            f"Expected reason to indicate loop iteration, got '{reason}'"
        )

        # Loop state should be incremented
        loop_key = "critique_tests:author_tests"
        assert loop_state.get(loop_key) == 1, (
            f"Expected loop count 1, got {loop_state.get(loop_key)}"
        )

    def test_unverified_cannot_help_exits(
        self,
        build_flow_def: FlowDefinition,
        tmp_repo: Path,
    ) -> None:
        """When status=UNVERIFIED and can_further_iteration_help=no, exits loop.

        The routing logic should exit the loop when the critic explicitly
        judges that no further iteration will help.
        """
        run_id = "test-unverified-no-help"

        # Write receipt with UNVERIFIED status but can_help=no
        write_receipt(
            tmp_repo=tmp_repo,
            run_id=run_id,
            flow_key="build",
            step_id="critique_tests",
            agent_key="test-critic",
            status="UNVERIFIED",
            can_further_iteration_help="no",
        )

        # Get the critique_tests step
        critique_step = build_flow_def.steps[1]

        # Call route_step
        loop_state: Dict[str, int] = {}
        result = {}

        next_step_id, reason = route_step(
            flow_def=build_flow_def,
            current_step=critique_step,
            result=result,
            loop_state=loop_state,
            run_id=run_id,
            flow_key="build",
            receipt_reader=make_receipt_reader(tmp_repo),
        )

        # Should exit to next step despite UNVERIFIED
        assert next_step_id == "implement", (
            f"Expected exit to 'implement', got '{next_step_id}'"
        )
        assert "no_further_help" in reason, (
            f"Expected reason to indicate no further help, got '{reason}'"
        )

    def test_max_iterations_limits_loops(
        self,
        build_flow_def: FlowDefinition,
        tmp_repo: Path,
    ) -> None:
        """After max_iterations reached, exits loop even if can_help=yes.

        This is a safety limit to prevent infinite loops.
        """
        run_id = "test-max-iterations"

        # Write receipt with UNVERIFIED status (would normally loop)
        write_receipt(
            tmp_repo=tmp_repo,
            run_id=run_id,
            flow_key="build",
            step_id="critique_tests",
            agent_key="test-critic",
            status="UNVERIFIED",
            can_further_iteration_help="yes",
        )

        # Get the critique_tests step
        critique_step = build_flow_def.steps[1]
        assert critique_step.routing is not None
        max_iter = critique_step.routing.max_iterations  # Should be 3

        # Simulate loop state at max iterations
        loop_key = "critique_tests:author_tests"
        loop_state: Dict[str, int] = {loop_key: max_iter}
        result = {}

        next_step_id, reason = route_step(
            flow_def=build_flow_def,
            current_step=critique_step,
            result=result,
            loop_state=loop_state,
            run_id=run_id,
            flow_key="build",
            receipt_reader=make_receipt_reader(tmp_repo),
        )

        # Should exit to next step due to max iterations
        assert next_step_id == "implement", (
            f"Expected exit to 'implement' after max iterations, got '{next_step_id}'"
        )
        assert "max_iterations" in reason, (
            f"Expected reason to mention max_iterations, got '{reason}'"
        )


# -----------------------------------------------------------------------------
# Test Class: Linear Routing
# -----------------------------------------------------------------------------


class TestLinearRouting:
    """Tests for linear routing decisions."""

    def test_linear_routing_advances(
        self,
        build_flow_def: FlowDefinition,
        tmp_repo: Path,
    ) -> None:
        """Linear routing advances to the specified next step.

        Linear steps should simply proceed to routing.next.
        """
        run_id = "test-linear-advance"

        # Get author_tests step (has linear routing)
        author_step = build_flow_def.steps[0]
        assert author_step.id == "author_tests"
        assert author_step.routing is not None
        assert author_step.routing.kind == "linear"

        # Call route_step
        loop_state: Dict[str, int] = {}
        result = {"status": "succeeded"}

        next_step_id, reason = route_step(
            flow_def=build_flow_def,
            current_step=author_step,
            result=result,
            loop_state=loop_state,
            run_id=run_id,
            flow_key="build",
            receipt_reader=make_receipt_reader(tmp_repo),
        )

        # Should advance to critique_tests
        assert next_step_id == "critique_tests", (
            f"Expected advance to 'critique_tests', got '{next_step_id}'"
        )
        assert "linear" in reason, (
            f"Expected reason to indicate linear routing, got '{reason}'"
        )

    def test_linear_routing_flow_complete(
        self,
        build_flow_def: FlowDefinition,
        tmp_repo: Path,
    ) -> None:
        """Final linear step with no next terminates the flow.

        When a linear step has no next step, the flow should complete.
        """
        run_id = "test-linear-complete"

        # Get commit step (final step with no next)
        commit_step = build_flow_def.steps[4]
        assert commit_step.id == "commit"
        assert commit_step.routing is not None
        assert commit_step.routing.next is None

        # Call route_step
        loop_state: Dict[str, int] = {}
        result = {"status": "succeeded"}

        next_step_id, reason = route_step(
            flow_def=build_flow_def,
            current_step=commit_step,
            result=result,
            loop_state=loop_state,
            run_id=run_id,
            flow_key="build",
            receipt_reader=make_receipt_reader(tmp_repo),
        )

        # Should return None to indicate flow complete
        assert next_step_id is None, (
            f"Expected None for flow complete, got '{next_step_id}'"
        )
        assert "complete" in reason.lower(), (
            f"Expected reason to indicate completion, got '{reason}'"
        )


# -----------------------------------------------------------------------------
# Test Class: Loop State Tracking
# -----------------------------------------------------------------------------


class TestLoopStateTracking:
    """Tests for loop state management."""

    def test_loop_state_increments(
        self,
        build_flow_def: FlowDefinition,
        tmp_repo: Path,
    ) -> None:
        """Loop counter increments on each iteration.

        Each call to route_step that loops back should increment the counter.
        """
        run_id = "test-loop-increment"

        # Write receipt that will cause a loop
        write_receipt(
            tmp_repo=tmp_repo,
            run_id=run_id,
            flow_key="build",
            step_id="critique_tests",
            agent_key="test-critic",
            status="UNVERIFIED",
            can_further_iteration_help="yes",
        )

        critique_step = build_flow_def.steps[1]
        loop_key = "critique_tests:author_tests"
        loop_state: Dict[str, int] = {}
        result = {}
        receipt_reader = make_receipt_reader(tmp_repo)

        # First iteration
        next_step_id, reason = route_step(
            flow_def=build_flow_def,
            current_step=critique_step,
            result=result,
            loop_state=loop_state,
            run_id=run_id,
            flow_key="build",
            receipt_reader=receipt_reader,
        )

        assert loop_state.get(loop_key) == 1, "First iteration should set count to 1"

        # Second iteration (simulate coming back to critique_tests)
        next_step_id, reason = route_step(
            flow_def=build_flow_def,
            current_step=critique_step,
            result=result,
            loop_state=loop_state,
            run_id=run_id,
            flow_key="build",
            receipt_reader=receipt_reader,
        )

        assert loop_state.get(loop_key) == 2, "Second iteration should increment to 2"

    def test_loop_state_independent_loops(
        self,
        build_flow_def: FlowDefinition,
        tmp_repo: Path,
    ) -> None:
        """Different loops have independent counters.

        The test microloop and code microloop should track separately.
        """
        run_id = "test-independent-loops"

        # Write receipts for both microloops
        write_receipt(
            tmp_repo=tmp_repo,
            run_id=run_id,
            flow_key="build",
            step_id="critique_tests",
            agent_key="test-critic",
            status="UNVERIFIED",
            can_further_iteration_help="yes",
        )
        write_receipt(
            tmp_repo=tmp_repo,
            run_id=run_id,
            flow_key="build",
            step_id="critique_code",
            agent_key="code-critic",
            status="UNVERIFIED",
            can_further_iteration_help="yes",
        )

        critique_tests = build_flow_def.steps[1]
        critique_code = build_flow_def.steps[3]

        loop_state: Dict[str, int] = {}
        result = {}
        receipt_reader = make_receipt_reader(tmp_repo)

        # Iterate test loop twice
        route_step(
            flow_def=build_flow_def,
            current_step=critique_tests,
            result=result,
            loop_state=loop_state,
            run_id=run_id,
            flow_key="build",
            receipt_reader=receipt_reader,
        )
        route_step(
            flow_def=build_flow_def,
            current_step=critique_tests,
            result=result,
            loop_state=loop_state,
            run_id=run_id,
            flow_key="build",
            receipt_reader=receipt_reader,
        )

        # Iterate code loop once
        route_step(
            flow_def=build_flow_def,
            current_step=critique_code,
            result=result,
            loop_state=loop_state,
            run_id=run_id,
            flow_key="build",
            receipt_reader=receipt_reader,
        )

        # Verify independent tracking
        test_loop_key = "critique_tests:author_tests"
        code_loop_key = "critique_code:implement"

        assert loop_state.get(test_loop_key) == 2, (
            f"Test loop should be at 2, got {loop_state.get(test_loop_key)}"
        )
        assert loop_state.get(code_loop_key) == 1, (
            f"Code loop should be at 1, got {loop_state.get(code_loop_key)}"
        )


# -----------------------------------------------------------------------------
# Test Class: Edge Cases
# -----------------------------------------------------------------------------


class TestRoutingEdgeCases:
    """Tests for edge cases and fallback behavior."""

    def test_no_routing_config_falls_back_to_linear(
        self,
        tmp_repo: Path,
    ) -> None:
        """Step with no routing config falls back to linear progression.

        If a step has no routing attribute, route_step should find
        the next step by index.
        """
        run_id = "test-no-routing"

        # Create a simple flow with no routing config
        step1 = StepDefinition(
            id="step1",
            index=1,
            agents=("agent1",),
            role="First step",
            routing=None,  # No routing config
        )
        step2 = StepDefinition(
            id="step2",
            index=2,
            agents=("agent2",),
            role="Second step",
            routing=None,
        )

        flow = FlowDefinition(
            key="test",
            index=99,
            title="Test Flow",
            short_title="Test",
            description="Test flow",
            steps=(step1, step2),
        )

        loop_state: Dict[str, int] = {}
        result = {}

        next_step_id, reason = route_step(
            flow_def=flow,
            current_step=step1,
            result=result,
            loop_state=loop_state,
            run_id=run_id,
            flow_key="test",
            receipt_reader=make_receipt_reader(tmp_repo),
        )

        assert next_step_id == "step2", (
            f"Expected fallback to step2 by index, got '{next_step_id}'"
        )
        assert "default" in reason.lower() or "linear" in reason.lower(), (
            f"Expected default/linear reason, got '{reason}'"
        )

    def test_missing_receipt_loops_back(
        self,
        build_flow_def: FlowDefinition,
        tmp_repo: Path,
    ) -> None:
        """When receipt is missing, microloop should loop back (conservative).

        If the receipt file doesn't exist, we can't check the condition,
        so we should loop back rather than incorrectly exiting.
        """
        run_id = "test-missing-receipt"

        # Don't write any receipt - it should be missing
        # But ensure the directory structure exists
        run_base = tmp_repo / "swarm" / "runs" / run_id / "build"
        run_base.mkdir(parents=True, exist_ok=True)

        critique_step = build_flow_def.steps[1]
        loop_state: Dict[str, int] = {}
        result = {}

        next_step_id, reason = route_step(
            flow_def=build_flow_def,
            current_step=critique_step,
            result=result,
            loop_state=loop_state,
            run_id=run_id,
            flow_key="build",
            receipt_reader=make_receipt_reader(tmp_repo),
        )

        # Should loop back since we can't verify exit condition
        assert next_step_id == "author_tests", (
            f"Expected loop back when receipt missing, got '{next_step_id}'"
        )
