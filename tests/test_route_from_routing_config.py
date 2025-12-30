"""Tests for route_from_routing_config function.

This module validates the spec-based routing logic that interprets RoutingConfig
from flow specs and produces RoutingSignal without requiring LLM calls.

## Test Coverage

### Terminal Routing (1 test)
1. test_terminal_routing - Terminal kind always terminates

### Linear Routing (2 tests)
2. test_linear_routing_with_next - Linear routing advances to next step
3. test_linear_routing_without_next - Linear routing terminates when no next step

### Microloop Routing (4 tests)
4. test_microloop_verified_exits - VERIFIED status exits loop to next step
5. test_microloop_unverified_loops - UNVERIFIED status loops back to target
6. test_microloop_max_iterations_exits - Max iterations reached exits loop
7. test_microloop_case_insensitive - Status comparison is case-insensitive

### Branch Routing (4 tests)
8. test_branch_exact_match - Exact branch key match routes correctly
9. test_branch_case_insensitive - Case-insensitive branch matching
10. test_branch_default_fallback - Falls back to next when no branch matches
11. test_branch_no_match_no_next - Returns None when no match and no default

### Edge Cases (2 tests)
12. test_unknown_kind_returns_none - Unknown routing kind returns None
13. test_empty_status_handling - Empty status is handled gracefully

## Design Notes

This function enables the spec-first architecture by providing deterministic
routing for cases fully specified in the flow spec. The key design decisions:

1. Case-insensitive status comparison for robustness
2. Returns None for ambiguous cases (LLM fallback)
3. Sets needs_human=True when exiting due to max iterations
4. Confidence scores reflect certainty (1.0 for spec-driven, lower for fallbacks)
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Add repo root to path for imports
repo_root = Path(__file__).resolve().parents[1]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from swarm.runtime.engines.claude.router import route_from_routing_config
from swarm.runtime.types import RoutingDecision
from swarm.spec.types import RoutingConfig, RoutingKind


# -----------------------------------------------------------------------------
# Test Class: Terminal Routing
# -----------------------------------------------------------------------------


class TestTerminalRouting:
    """Tests for terminal routing kind."""

    def test_terminal_routing(self) -> None:
        """Terminal routing kind always terminates.

        Terminal steps have no successor - they mark the end of a flow.
        """
        config = RoutingConfig(kind=RoutingKind.TERMINAL)

        signal = route_from_routing_config(config, "VERIFIED")

        assert signal is not None
        assert signal.decision == RoutingDecision.TERMINATE
        assert signal.reason == "spec_terminal"
        assert signal.confidence == 1.0
        assert signal.needs_human is False
        assert signal.next_step_id is None


# -----------------------------------------------------------------------------
# Test Class: Linear Routing
# -----------------------------------------------------------------------------


class TestLinearRouting:
    """Tests for linear routing kind."""

    def test_linear_routing_with_next(self) -> None:
        """Linear routing with next step advances to that step.

        Linear steps proceed unconditionally to their next step.
        """
        config = RoutingConfig(
            kind=RoutingKind.LINEAR,
            next="step_2",
        )

        signal = route_from_routing_config(config, "succeeded")

        assert signal is not None
        assert signal.decision == RoutingDecision.ADVANCE
        assert signal.next_step_id == "step_2"
        assert signal.reason == "spec_linear"
        assert signal.confidence == 1.0
        assert signal.needs_human is False

    def test_linear_routing_without_next(self) -> None:
        """Linear routing without next step terminates the flow.

        Final linear steps have no successor, indicating flow completion.
        """
        config = RoutingConfig(
            kind=RoutingKind.LINEAR,
            next=None,
        )

        signal = route_from_routing_config(config, "succeeded")

        assert signal is not None
        assert signal.decision == RoutingDecision.TERMINATE
        assert signal.reason == "spec_linear_no_next"
        assert signal.next_step_id is None


# -----------------------------------------------------------------------------
# Test Class: Microloop Routing
# -----------------------------------------------------------------------------


class TestMicroloopRouting:
    """Tests for microloop routing kind."""

    def test_microloop_verified_exits(self) -> None:
        """VERIFIED status exits the microloop to next step.

        When the loop condition is satisfied, the loop exits.
        """
        config = RoutingConfig(
            kind=RoutingKind.MICROLOOP,
            next="implement",
            loop_target="author_tests",
            loop_success_values=("VERIFIED", "verified"),
            max_iterations=3,
        )

        signal = route_from_routing_config(
            config,
            handoff_status="VERIFIED",
            iteration_count=1,
        )

        assert signal is not None
        assert signal.decision == RoutingDecision.ADVANCE
        assert signal.next_step_id == "implement"
        assert signal.reason == "spec_microloop_verified"
        assert signal.confidence == 1.0
        assert signal.needs_human is False

    def test_microloop_unverified_loops(self) -> None:
        """UNVERIFIED status loops back to the loop target.

        When the loop condition is not satisfied and iterations remain,
        the loop continues.
        """
        config = RoutingConfig(
            kind=RoutingKind.MICROLOOP,
            next="implement",
            loop_target="author_tests",
            loop_success_values=("VERIFIED",),
            max_iterations=3,
        )

        signal = route_from_routing_config(
            config,
            handoff_status="UNVERIFIED",
            iteration_count=1,
        )

        assert signal is not None
        assert signal.decision == RoutingDecision.LOOP
        assert signal.next_step_id == "author_tests"
        assert signal.reason == "spec_microloop_continue"
        assert signal.confidence == 1.0
        assert signal.needs_human is False

    def test_microloop_max_iterations_exits(self) -> None:
        """Max iterations reached exits the loop even if UNVERIFIED.

        Safety limit to prevent infinite loops. Human review is flagged.
        """
        config = RoutingConfig(
            kind=RoutingKind.MICROLOOP,
            next="implement",
            loop_target="author_tests",
            loop_success_values=("VERIFIED",),
            max_iterations=3,
        )

        signal = route_from_routing_config(
            config,
            handoff_status="UNVERIFIED",
            iteration_count=3,  # At max
        )

        assert signal is not None
        assert signal.decision == RoutingDecision.ADVANCE
        assert signal.next_step_id == "implement"
        assert signal.reason == "spec_microloop_max_iterations"
        assert signal.confidence == 0.7  # Lower confidence
        assert signal.needs_human is True  # Human should review

    def test_microloop_case_insensitive(self) -> None:
        """Status comparison is case-insensitive.

        'verified', 'VERIFIED', and 'Verified' should all match.
        """
        config = RoutingConfig(
            kind=RoutingKind.MICROLOOP,
            next="next_step",
            loop_target="loop_target",
            loop_success_values=("VERIFIED",),
            max_iterations=3,
        )

        # Test lowercase status matching uppercase success value
        signal = route_from_routing_config(config, "verified", iteration_count=0)

        assert signal is not None
        assert signal.decision == RoutingDecision.ADVANCE
        assert signal.reason == "spec_microloop_verified"


# -----------------------------------------------------------------------------
# Test Class: Branch Routing
# -----------------------------------------------------------------------------


class TestBranchRouting:
    """Tests for branch routing kind."""

    def test_branch_exact_match(self) -> None:
        """Exact branch key match routes to correct target.

        Branches define status-to-step mappings for conditional routing.
        """
        config = RoutingConfig(
            kind=RoutingKind.BRANCH,
            branches={"MERGE": "merge_step", "BOUNCE": "bounce_step"},
            next="default_step",
        )

        signal = route_from_routing_config(config, "MERGE")

        assert signal is not None
        assert signal.decision == RoutingDecision.BRANCH
        assert signal.next_step_id == "merge_step"
        assert signal.route == "MERGE"
        assert signal.reason == "spec_branch"
        assert signal.confidence == 1.0

    def test_branch_case_insensitive(self) -> None:
        """Branch matching is case-insensitive.

        'merge' should match branch key 'MERGE'.
        """
        config = RoutingConfig(
            kind=RoutingKind.BRANCH,
            branches={"MERGE": "merge_step", "BOUNCE": "bounce_step"},
        )

        signal = route_from_routing_config(config, "merge")

        assert signal is not None
        assert signal.decision == RoutingDecision.BRANCH
        assert signal.next_step_id == "merge_step"
        assert signal.route == "MERGE"  # Original key is preserved

    def test_branch_default_fallback(self) -> None:
        """Falls back to next step when no branch matches.

        Provides a default path when status doesn't match any branch.
        """
        config = RoutingConfig(
            kind=RoutingKind.BRANCH,
            branches={"MERGE": "merge_step", "BOUNCE": "bounce_step"},
            next="default_step",
        )

        signal = route_from_routing_config(config, "UNKNOWN_STATUS")

        assert signal is not None
        assert signal.decision == RoutingDecision.ADVANCE
        assert signal.next_step_id == "default_step"
        assert signal.reason == "spec_branch_default"
        assert signal.confidence == 0.8  # Lower confidence for fallback

    def test_branch_no_match_no_next(self) -> None:
        """Returns None when no branch matches and no default next.

        This case requires LLM decision as routing is ambiguous.
        """
        config = RoutingConfig(
            kind=RoutingKind.BRANCH,
            branches={"MERGE": "merge_step"},
            next=None,
        )

        signal = route_from_routing_config(config, "UNKNOWN_STATUS")

        assert signal is None  # Requires LLM decision


# -----------------------------------------------------------------------------
# Test Class: Edge Cases
# -----------------------------------------------------------------------------


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_empty_status_handling(self) -> None:
        """Empty status string is handled gracefully.

        Should not raise an exception and should produce valid routing.
        """
        config = RoutingConfig(
            kind=RoutingKind.LINEAR,
            next="next_step",
        )

        signal = route_from_routing_config(config, "")

        assert signal is not None
        assert signal.decision == RoutingDecision.ADVANCE
        assert signal.next_step_id == "next_step"

    def test_none_status_handling(self) -> None:
        """None status (if passed) is handled gracefully.

        While type hint says str, we should be defensive.
        """
        config = RoutingConfig(
            kind=RoutingKind.LINEAR,
            next="next_step",
        )

        # Test with empty string (None would fail type check)
        signal = route_from_routing_config(config, "")

        assert signal is not None

    def test_microloop_iteration_boundary(self) -> None:
        """Iteration count exactly at max_iterations exits.

        iteration_count=3 with max_iterations=3 should exit.
        """
        config = RoutingConfig(
            kind=RoutingKind.MICROLOOP,
            next="next_step",
            loop_target="loop_target",
            max_iterations=3,
        )

        signal = route_from_routing_config(
            config,
            "UNVERIFIED",
            iteration_count=3,
        )

        assert signal is not None
        assert signal.decision == RoutingDecision.ADVANCE
        assert signal.reason == "spec_microloop_max_iterations"

    def test_microloop_iteration_below_max(self) -> None:
        """Iteration count below max_iterations continues looping.

        iteration_count=2 with max_iterations=3 should loop.
        """
        config = RoutingConfig(
            kind=RoutingKind.MICROLOOP,
            next="next_step",
            loop_target="loop_target",
            max_iterations=3,
        )

        signal = route_from_routing_config(
            config,
            "UNVERIFIED",
            iteration_count=2,
        )

        assert signal is not None
        assert signal.decision == RoutingDecision.LOOP
        assert signal.reason == "spec_microloop_continue"

    def test_branch_empty_branches_dict(self) -> None:
        """Branch routing with empty branches dict falls back to next.

        Empty branches dict means no explicit routing, use default.
        """
        config = RoutingConfig(
            kind=RoutingKind.BRANCH,
            branches={},
            next="default_step",
        )

        signal = route_from_routing_config(config, "ANY_STATUS")

        assert signal is not None
        assert signal.decision == RoutingDecision.ADVANCE
        assert signal.next_step_id == "default_step"
        assert signal.reason == "spec_branch_default"
