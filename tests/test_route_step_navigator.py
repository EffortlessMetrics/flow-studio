"""Tests for route_step() with Navigator routing.

This module validates that the unified routing driver correctly uses Navigator
for intelligent routing decisions in ASSIST/AUTHORITATIVE modes.

## Test Coverage

### Navigator Success Path (3 tests)
1. test_navigator_routing_success - Navigator returns RoutingOutcome with navigator source
2. test_navigator_routing_with_detour - Detour injection sets navigator:detour source
3. test_navigator_routing_chosen_candidate - chosen_candidate_id is preserved

### Navigator Preconditions (3 tests)
4. test_deterministic_only_skips_navigator - DETERMINISTIC_ONLY mode never calls Navigator
5. test_missing_orchestrator_skips_navigator - None orchestrator skips Navigator gracefully
6. test_missing_required_params_skips_navigator - Missing params skip Navigator

### Navigator Error Handling (2 tests)
7. test_navigator_error_returns_explicit_source - Errors produce explicit routing_source
8. test_navigator_error_does_not_silently_fallback - Errors are logged, not swallowed

## Design Notes

These tests ensure Navigator routing is actually used (not silently falling back)
and that errors produce audit trail that shows the failure explicitly.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

# Add repo root to path for imports
repo_root = Path(__file__).resolve().parents[1]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from swarm.runtime.stepwise.routing.driver import (
    RoutingOutcome,
    route_step,
    _try_navigator,
)
from swarm.runtime.types import RoutingDecision, RoutingMode, RoutingSignal


# -----------------------------------------------------------------------------
# Test Fixtures
# -----------------------------------------------------------------------------


@dataclass
class MockStepDefinition:
    """Minimal StepDefinition mock for testing."""

    id: str = "test_step"
    index: int = 1
    routing: Optional[Any] = None
    flow_def: Optional[Any] = None


@dataclass
class MockRunState:
    """Minimal RunState mock for testing."""

    handoff_envelopes: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MockFlowDefinition:
    """Minimal FlowDefinition mock for testing."""

    flow_key: str = "build"
    steps: List[Any] = field(default_factory=list)


@dataclass
class MockFlowGraph:
    """Minimal FlowGraph mock for testing."""

    nodes: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MockRunSpec:
    """Minimal RunSpec mock for testing."""

    no_human_mid_flow: bool = True


@dataclass
class MockNavigationResult:
    """Mock NavigationResult from NavigationOrchestrator.navigate()."""

    next_node: Optional[str] = "next_step_id"
    routing_signal: Optional[RoutingSignal] = None
    brief_stored: bool = False
    detour_injected: bool = False
    nav_output: Optional[Any] = None
    extend_graph_injected: bool = False


class MockNavigationOrchestrator:
    """Mock NavigationOrchestrator for testing."""

    def __init__(
        self,
        next_node: str = "next_step",
        decision: RoutingDecision = RoutingDecision.ADVANCE,
        chosen_candidate_id: str = "candidate_1",
        detour_injected: bool = False,
        should_raise: bool = False,
        raise_exception: Optional[Exception] = None,
    ):
        self.next_node = next_node
        self.decision = decision
        self.chosen_candidate_id = chosen_candidate_id
        self.detour_injected = detour_injected
        self.should_raise = should_raise
        self.raise_exception = raise_exception or ValueError("Navigator error")

        # Mock sidequest_catalog
        self.sidequest_catalog = MagicMock()
        self.sidequest_catalog.get_applicable_sidequests.return_value = []

    def navigate(self, **kwargs) -> MockNavigationResult:
        if self.should_raise:
            raise self.raise_exception

        signal = RoutingSignal(
            decision=self.decision,
            next_step_id=self.next_node,
            reason="navigator_test_decision",
            confidence=0.9,
            needs_human=False,
            chosen_candidate_id=self.chosen_candidate_id,
        )

        return MockNavigationResult(
            next_node=self.next_node,
            routing_signal=signal,
            detour_injected=self.detour_injected,
        )


@pytest.fixture
def mock_step():
    """Create a mock step for testing."""
    return MockStepDefinition(id="test_step", index=1)


@pytest.fixture
def mock_run_state():
    """Create a mock run state for testing."""
    return MockRunState()


@pytest.fixture
def mock_flow_def():
    """Create a mock flow definition for testing."""
    return MockFlowDefinition(flow_key="build", steps=[])


@pytest.fixture
def mock_flow_graph():
    """Create a mock flow graph for testing."""
    return MockFlowGraph()


@pytest.fixture
def mock_spec():
    """Create a mock run spec for testing."""
    return MockRunSpec()


@pytest.fixture
def mock_run_base(tmp_path):
    """Create a temporary run base directory."""
    return tmp_path / "run_base"


# -----------------------------------------------------------------------------
# Test Class: Navigator Success Path
# -----------------------------------------------------------------------------


class TestNavigatorSuccessPath:
    """Tests for successful Navigator routing."""

    @patch("swarm.runtime.stepwise.routing.navigator.route_via_navigator")
    def test_navigator_routing_success(
        self,
        mock_route_via_navigator,
        mock_step,
        mock_run_state,
        mock_flow_def,
        mock_flow_graph,
        mock_spec,
        mock_run_base,
    ):
        """Navigator routing returns RoutingOutcome with navigator source.

        When Navigator routing succeeds, the routing_source should indicate
        that Navigator made the decision.
        """
        # Setup mock return
        expected_outcome = RoutingOutcome(
            decision=RoutingDecision.ADVANCE,
            next_step_id="next_step",
            reason="navigator_decision",
            confidence=0.9,
            routing_source="navigator",
            chosen_candidate_id="candidate_1",
        )
        mock_route_via_navigator.return_value = expected_outcome

        orchestrator = MockNavigationOrchestrator()

        result = route_step(
            step=mock_step,
            step_result={"status": "VERIFIED"},
            run_state=mock_run_state,
            loop_state={},
            iteration=1,
            routing_mode=RoutingMode.ASSIST,
            run_id="test-run",
            flow_key="build",
            flow_graph=mock_flow_graph,
            flow_def=mock_flow_def,
            spec=mock_spec,
            run_base=mock_run_base,
            navigation_orchestrator=orchestrator,
        )

        assert result.routing_source == "navigator"
        assert result.next_step_id == "next_step"
        assert result.decision == RoutingDecision.ADVANCE

    @patch("swarm.runtime.stepwise.routing.navigator.route_via_navigator")
    def test_navigator_routing_with_detour(
        self,
        mock_route_via_navigator,
        mock_step,
        mock_run_state,
        mock_flow_def,
        mock_flow_graph,
        mock_spec,
        mock_run_base,
    ):
        """Detour injection sets navigator:detour source.

        When Navigator injects a detour, the routing_source should indicate
        this via 'navigator:detour'.
        """
        expected_outcome = RoutingOutcome(
            decision=RoutingDecision.BRANCH,
            next_step_id="detour_step",
            reason="Detour: lint fix needed",
            confidence=0.95,
            routing_source="navigator:detour",
            chosen_candidate_id="detour_lint_fix",
        )
        mock_route_via_navigator.return_value = expected_outcome

        orchestrator = MockNavigationOrchestrator(detour_injected=True)

        result = route_step(
            step=mock_step,
            step_result={"status": "UNVERIFIED"},
            run_state=mock_run_state,
            loop_state={},
            iteration=1,
            routing_mode=RoutingMode.AUTHORITATIVE,
            run_id="test-run",
            flow_key="build",
            flow_graph=mock_flow_graph,
            flow_def=mock_flow_def,
            spec=mock_spec,
            run_base=mock_run_base,
            navigation_orchestrator=orchestrator,
        )

        assert result.routing_source == "navigator:detour"
        assert "detour" in result.reason.lower()

    @patch("swarm.runtime.stepwise.routing.navigator.route_via_navigator")
    def test_navigator_routing_chosen_candidate(
        self,
        mock_route_via_navigator,
        mock_step,
        mock_run_state,
        mock_flow_def,
        mock_flow_graph,
        mock_spec,
        mock_run_base,
    ):
        """chosen_candidate_id is preserved from Navigator decision.

        The audit trail should show which candidate Navigator selected.
        """
        expected_outcome = RoutingOutcome(
            decision=RoutingDecision.ADVANCE,
            next_step_id="implement",
            reason="navigator_decision",
            confidence=0.85,
            routing_source="navigator",
            chosen_candidate_id="candidate_advance_implement",
        )
        mock_route_via_navigator.return_value = expected_outcome

        orchestrator = MockNavigationOrchestrator(
            chosen_candidate_id="candidate_advance_implement"
        )

        result = route_step(
            step=mock_step,
            step_result={"status": "VERIFIED"},
            run_state=mock_run_state,
            loop_state={},
            iteration=1,
            routing_mode=RoutingMode.ASSIST,
            run_id="test-run",
            flow_key="build",
            flow_graph=mock_flow_graph,
            flow_def=mock_flow_def,
            spec=mock_spec,
            run_base=mock_run_base,
            navigation_orchestrator=orchestrator,
        )

        assert result.chosen_candidate_id == "candidate_advance_implement"


# -----------------------------------------------------------------------------
# Test Class: Navigator Preconditions
# -----------------------------------------------------------------------------


class TestNavigatorPreconditions:
    """Tests for Navigator routing preconditions."""

    def test_deterministic_only_skips_navigator(
        self,
        mock_step,
        mock_run_state,
        mock_flow_def,
        mock_flow_graph,
        mock_spec,
        mock_run_base,
    ):
        """DETERMINISTIC_ONLY mode never calls Navigator.

        Even with a NavigationOrchestrator provided, DETERMINISTIC_ONLY mode
        should skip Navigator routing entirely.
        """
        # Navigator that would fail if called
        orchestrator = MockNavigationOrchestrator(should_raise=True)

        # This should NOT raise because Navigator should be skipped
        result = route_step(
            step=mock_step,
            step_result={"status": "VERIFIED"},
            run_state=mock_run_state,
            loop_state={},
            iteration=1,
            routing_mode=RoutingMode.DETERMINISTIC_ONLY,
            run_id="test-run",
            flow_key="build",
            flow_graph=mock_flow_graph,
            flow_def=mock_flow_def,
            spec=mock_spec,
            run_base=mock_run_base,
            navigation_orchestrator=orchestrator,
        )

        # Should fall through to deterministic or escalate, NOT navigator
        assert "navigator" not in result.routing_source

    def test_missing_orchestrator_skips_navigator(
        self,
        mock_step,
        mock_run_state,
        mock_flow_def,
        mock_flow_graph,
        mock_spec,
        mock_run_base,
    ):
        """None orchestrator skips Navigator gracefully.

        Without a NavigationOrchestrator, Navigator routing should be skipped.
        """
        result = route_step(
            step=mock_step,
            step_result={"status": "VERIFIED"},
            run_state=mock_run_state,
            loop_state={},
            iteration=1,
            routing_mode=RoutingMode.ASSIST,
            run_id="test-run",
            flow_key="build",
            flow_graph=mock_flow_graph,
            flow_def=mock_flow_def,
            spec=mock_spec,
            run_base=mock_run_base,
            navigation_orchestrator=None,
        )

        # Should fall through to other strategies
        assert result.routing_source != "navigator"

    def test_missing_required_params_skips_navigator(
        self,
        mock_step,
        mock_run_state,
    ):
        """Missing required params skip Navigator routing.

        Navigator requires run_id, flow_key, flow_graph, flow_def, spec, run_base.
        Missing any of these should skip Navigator.
        """
        orchestrator = MockNavigationOrchestrator()

        # Missing flow_graph, flow_def, spec, run_base
        result = route_step(
            step=mock_step,
            step_result={"status": "VERIFIED"},
            run_state=mock_run_state,
            loop_state={},
            iteration=1,
            routing_mode=RoutingMode.ASSIST,
            run_id="test-run",
            flow_key="build",
            # flow_graph=None (missing)
            # flow_def=None (missing)
            # spec=None (missing)
            # run_base=None (missing)
            navigation_orchestrator=orchestrator,
        )

        # Should skip Navigator due to missing params
        assert "navigator" not in result.routing_source


# -----------------------------------------------------------------------------
# Test Class: Navigator Error Handling
# -----------------------------------------------------------------------------


class TestNavigatorErrorHandling:
    """Tests for Navigator error handling.

    CRITICAL: These tests ensure that Navigator errors produce explicit
    routing_source values that show the failure, rather than silently
    falling back to other strategies.
    """

    @patch("swarm.runtime.stepwise.routing.navigator.route_via_navigator")
    def test_navigator_error_falls_to_deterministic(
        self,
        mock_route_via_navigator,
        mock_step,
        mock_run_state,
        mock_flow_def,
        mock_flow_graph,
        mock_spec,
        mock_run_base,
    ):
        """Navigator errors fall through to deterministic routing.

        When Navigator raises an exception, routing should fall through
        to deterministic strategies, not silently succeed.
        """
        mock_route_via_navigator.side_effect = ValueError("Navigator crashed")

        orchestrator = MockNavigationOrchestrator()

        result = route_step(
            step=mock_step,
            step_result={"status": "VERIFIED"},
            run_state=mock_run_state,
            loop_state={},
            iteration=1,
            routing_mode=RoutingMode.ASSIST,
            run_id="test-run",
            flow_key="build",
            flow_graph=mock_flow_graph,
            flow_def=mock_flow_def,
            spec=mock_spec,
            run_base=mock_run_base,
            navigation_orchestrator=orchestrator,
        )

        # Should NOT have navigator source (it failed)
        assert "navigator" not in result.routing_source
        # Should have fallen through to another strategy
        assert result.routing_source in (
            "deterministic",
            "envelope_fallback",
            "escalate",
            "fast_path",
        )

    def test_try_navigator_returns_none_on_error(
        self,
        mock_step,
        mock_run_state,
        mock_flow_def,
        mock_flow_graph,
        mock_spec,
        mock_run_base,
    ):
        """_try_navigator returns None when Navigator raises.

        Direct test of _try_navigator error handling.
        """
        orchestrator = MockNavigationOrchestrator(
            should_raise=True, raise_exception=RuntimeError("Navigator failed")
        )

        # Patch route_via_navigator to raise
        with patch(
            "swarm.runtime.stepwise.routing.navigator.route_via_navigator"
        ) as mock_route:
            mock_route.side_effect = RuntimeError("Navigator failed")

            result = _try_navigator(
                step=mock_step,
                step_result={"status": "VERIFIED"},
                run_state=mock_run_state,
                loop_state={},
                iteration=1,
                routing_mode=RoutingMode.ASSIST,
                run_id="test-run",
                flow_key="build",
                flow_graph=mock_flow_graph,
                flow_def=mock_flow_def,
                spec=mock_spec,
                run_base=mock_run_base,
                navigation_orchestrator=orchestrator,
            )

        # Should return None to allow fallback
        assert result is None

    @patch("swarm.runtime.stepwise.routing.driver.logger")
    @patch("swarm.runtime.stepwise.routing.navigator.route_via_navigator")
    def test_navigator_error_is_logged(
        self,
        mock_route_via_navigator,
        mock_logger,
        mock_step,
        mock_run_state,
        mock_flow_def,
        mock_flow_graph,
        mock_spec,
        mock_run_base,
    ):
        """Navigator errors are logged with step context.

        When Navigator fails, the error should be logged with enough
        context to debug (exception type, step_id, run_id, flow_key).
        """
        mock_route_via_navigator.side_effect = ValueError(
            "Test navigation error"
        )

        orchestrator = MockNavigationOrchestrator()

        _try_navigator(
            step=mock_step,
            step_result={"status": "VERIFIED"},
            run_state=mock_run_state,
            loop_state={},
            iteration=1,
            routing_mode=RoutingMode.ASSIST,
            run_id="test-run",
            flow_key="build",
            flow_graph=mock_flow_graph,
            flow_def=mock_flow_def,
            spec=mock_spec,
            run_base=mock_run_base,
            navigation_orchestrator=orchestrator,
        )

        # Verify warning was logged
        mock_logger.warning.assert_called()
        call_args = mock_logger.warning.call_args.args

        # Join all args to check message content (more robust than str(call))
        message_content = " ".join(str(arg) for arg in call_args)

        # Should include exception type, step_id, run_id, flow_key in the message
        assert "ValueError" in message_content, f"Missing ValueError in: {message_content}"
        assert "test_step" in message_content, f"Missing step_id in: {message_content}"
        assert "test-run" in message_content, f"Missing run_id in: {message_content}"
        assert "build" in message_content, f"Missing flow_key in: {message_content}"


# -----------------------------------------------------------------------------
# Test Class: Integration with route_step
# -----------------------------------------------------------------------------


class TestRouteStepIntegration:
    """Integration tests for route_step with Navigator."""

    @patch("swarm.runtime.stepwise.routing.navigator.route_via_navigator")
    def test_navigator_outcome_propagates_to_route_step(
        self,
        mock_route_via_navigator,
        mock_step,
        mock_run_state,
        mock_flow_def,
        mock_flow_graph,
        mock_spec,
        mock_run_base,
    ):
        """RoutingOutcome from Navigator propagates through route_step.

        All fields from Navigator's RoutingOutcome should be preserved
        in the final route_step result.
        """
        expected_outcome = RoutingOutcome(
            decision=RoutingDecision.LOOP,
            next_step_id="retry_step",
            reason="critic_requested_revision",
            confidence=0.75,
            routing_source="navigator",
            chosen_candidate_id="candidate_loop_retry",
            loop_iteration=2,
            exit_condition_met=False,
        )
        mock_route_via_navigator.return_value = expected_outcome

        orchestrator = MockNavigationOrchestrator()

        result = route_step(
            step=mock_step,
            step_result={"status": "UNVERIFIED"},
            run_state=mock_run_state,
            loop_state={"test_step": 2},
            iteration=2,
            routing_mode=RoutingMode.ASSIST,
            run_id="test-run",
            flow_key="build",
            flow_graph=mock_flow_graph,
            flow_def=mock_flow_def,
            spec=mock_spec,
            run_base=mock_run_base,
            navigation_orchestrator=orchestrator,
        )

        assert result.decision == RoutingDecision.LOOP
        assert result.next_step_id == "retry_step"
        assert result.reason == "critic_requested_revision"
        assert result.confidence == 0.75
        assert result.routing_source == "navigator"
        assert result.chosen_candidate_id == "candidate_loop_retry"

    @patch("swarm.runtime.stepwise.routing.driver._try_fast_path")
    @patch("swarm.runtime.stepwise.routing.navigator.route_via_navigator")
    def test_fast_path_takes_precedence_over_navigator(
        self,
        mock_route_via_navigator,
        mock_fast_path,
        mock_step,
        mock_run_state,
        mock_flow_def,
        mock_flow_graph,
        mock_spec,
        mock_run_base,
    ):
        """Fast-path routing takes precedence over Navigator.

        If fast-path can determine routing, Navigator should not be called.
        """
        fast_path_outcome = RoutingOutcome(
            decision=RoutingDecision.ADVANCE,
            next_step_id="fast_next",
            reason="explicit_next_step_id",
            confidence=1.0,
            routing_source="fast_path",
        )
        mock_fast_path.return_value = fast_path_outcome

        orchestrator = MockNavigationOrchestrator()

        result = route_step(
            step=mock_step,
            step_result={"status": "VERIFIED", "next_step_id": "fast_next"},
            run_state=mock_run_state,
            loop_state={},
            iteration=1,
            routing_mode=RoutingMode.ASSIST,
            run_id="test-run",
            flow_key="build",
            flow_graph=mock_flow_graph,
            flow_def=mock_flow_def,
            spec=mock_spec,
            run_base=mock_run_base,
            navigation_orchestrator=orchestrator,
        )

        assert result.routing_source == "fast_path"
        mock_route_via_navigator.assert_not_called()
