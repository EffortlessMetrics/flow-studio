"""
test_flow_reset.py - Smoke tests for Flow 8 (Reset) integration.

Tests that Flow 8 is properly registered, configured, and loadable.
"""

import pytest

from swarm.config.flow_registry import (
    FlowRegistry,
    get_flow_index,
    get_flow_steps,
    get_sdlc_flow_keys,
    get_flow_keys,
)


class TestFlow8Reset:
    """Tests for Flow 8 (Reset) integration."""

    @pytest.fixture(autouse=True)
    def reset_registry(self):
        """Reset registry between tests."""
        FlowRegistry.reset()
        yield
        FlowRegistry.reset()

    def test_reset_flow_registered(self):
        """Test that reset flow is registered in the flow registry."""
        registry = FlowRegistry.get_instance()
        reset_flow = registry.get_flow("reset")

        assert reset_flow is not None
        assert reset_flow.key == "reset"
        assert reset_flow.index == 8

    def test_reset_flow_is_utility_not_sdlc(self):
        """Test that reset flow is marked as utility, not core SDLC."""
        registry = FlowRegistry.get_instance()
        reset_flow = registry.get_flow("reset")

        assert reset_flow is not None
        assert reset_flow.is_sdlc is False

        # Should not appear in SDLC flow keys
        sdlc_keys = get_sdlc_flow_keys()
        assert "reset" not in sdlc_keys

        # But should appear in all flow keys
        all_keys = get_flow_keys()
        assert "reset" in all_keys

    def test_reset_flow_has_eight_steps(self):
        """Test that reset flow has exactly 8 steps."""
        steps = get_flow_steps("reset")
        assert len(steps) == 8

    def test_reset_flow_step_ids(self):
        """Test that reset flow has the expected step IDs."""
        steps = get_flow_steps("reset")
        step_ids = [s.id for s in steps]

        expected_ids = [
            "diagnose",
            "stash_wip",
            "sync_upstream",
            "resolve_conflicts",
            "restore_wip",
            "prune_branches",
            "archive_run",
            "verify_clean",
        ]

        assert step_ids == expected_ids

    def test_reset_flow_step_agents(self):
        """Test that each reset step has the correct agent."""
        steps = get_flow_steps("reset")

        expected_agents = {
            "diagnose": ("reset-diagnose",),
            "stash_wip": ("reset-stash-wip",),
            "sync_upstream": ("reset-sync-upstream",),
            "resolve_conflicts": ("reset-resolve-conflicts",),
            "restore_wip": ("reset-restore-wip",),
            "prune_branches": ("reset-prune-branches",),
            "archive_run": ("reset-archive-run",),
            "verify_clean": ("reset-verify-clean",),
        }

        for step in steps:
            assert step.agents == expected_agents[step.id], (
                f"Step {step.id} has wrong agents: {step.agents}"
            )

    def test_reset_flow_routing_configuration(self):
        """Test that routing is configured correctly for reset flow."""
        steps = get_flow_steps("reset")
        steps_by_id = {s.id: s for s in steps}

        # diagnose should route to stash_wip
        diagnose = steps_by_id["diagnose"]
        assert diagnose.routing is not None
        assert diagnose.routing.kind == "linear"
        assert diagnose.routing.next == "stash_wip"

        # resolve_conflicts has microloop routing
        resolve = steps_by_id["resolve_conflicts"]
        assert resolve.routing is not None
        assert resolve.routing.kind == "microloop"
        assert resolve.routing.loop_target == "resolve_conflicts"
        assert resolve.routing.next == "restore_wip"
        assert "VERIFIED" in resolve.routing.loop_success_values

        # verify_clean is the final step (no next)
        verify = steps_by_id["verify_clean"]
        assert verify.routing is not None
        assert verify.routing.kind == "linear"
        assert verify.routing.next is None

    def test_reset_flow_teaching_notes(self):
        """Test that teaching notes are present on reset steps."""
        steps = get_flow_steps("reset")

        for step in steps:
            assert step.teaching_notes is not None, (
                f"Step {step.id} is missing teaching_notes"
            )
            assert len(step.teaching_notes.inputs) > 0 or step.id == "diagnose", (
                f"Step {step.id} should have input specifications"
            )
            assert len(step.teaching_notes.outputs) > 0, (
                f"Step {step.id} should have output specifications"
            )

    def test_reset_flow_cross_cutting_agents(self):
        """Test that cross-cutting agents are configured."""
        registry = FlowRegistry.get_instance()
        reset_flow = registry.get_flow("reset")

        assert reset_flow is not None
        assert "clarifier" in reset_flow.cross_cutting
        assert "repo-operator" in reset_flow.cross_cutting

    def test_reset_flow_index_helper(self):
        """Test the get_flow_index helper for reset."""
        assert get_flow_index("reset") == 8

    def test_reset_agent_positions(self):
        """Test that reset agents have correct positions in registry."""
        registry = FlowRegistry.get_instance()

        # Check reset-diagnose is at position (reset, diagnose, 8, 1)
        diagnose_positions = registry.get_agent_positions("reset-diagnose")
        assert len(diagnose_positions) == 1
        flow_key, step_id, flow_idx, step_idx = diagnose_positions[0]
        assert flow_key == "reset"
        assert step_id == "diagnose"
        assert flow_idx == 8
        assert step_idx == 1

        # Check reset-verify-clean is at position (reset, verify_clean, 8, 8)
        verify_positions = registry.get_agent_positions("reset-verify-clean")
        assert len(verify_positions) == 1
        flow_key, step_id, flow_idx, step_idx = verify_positions[0]
        assert flow_key == "reset"
        assert step_id == "verify_clean"
        assert flow_idx == 8
        assert step_idx == 8


class TestFlow8AsUtilityFlow:
    """Tests for Flow 8 as a utility/injected flow."""

    @pytest.fixture(autouse=True)
    def reset_registry(self):
        """Reset registry between tests."""
        FlowRegistry.reset()
        yield
        FlowRegistry.reset()

    def test_utility_flows_excluded_from_sdlc_count(self):
        """Test that utility flows don't count toward SDLC total."""
        registry = FlowRegistry.get_instance()

        # Should have 7 SDLC flows (signal through wisdom)
        assert registry.get_total_sdlc_flows() == 7

        # Total flows includes utilities
        assert registry.get_total_flows() >= 8

    def test_reset_flow_can_be_injected(self):
        """Test that reset flow has properties suitable for injection."""
        registry = FlowRegistry.get_instance()
        reset_flow = registry.get_flow("reset")

        # A utility flow should be injectable
        assert reset_flow is not None
        assert reset_flow.is_sdlc is False
        # The flow should be fully specified for execution
        assert len(reset_flow.steps) > 0
        # Each step should have an agent
        for step in reset_flow.steps:
            assert len(step.agents) > 0
