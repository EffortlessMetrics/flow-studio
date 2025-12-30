"""Tests for flow registry module.

This module tests the flow_registry module which provides the single source
of truth for flow ordering, step definitions, and agent positions.
"""

import pytest
from pathlib import Path

# Import the flow registry
import sys
_SWARM_ROOT = Path(__file__).resolve().parent.parent
if str(_SWARM_ROOT) not in sys.path:
    sys.path.insert(0, str(_SWARM_ROOT))

from swarm.config.flow_registry import (
    FlowRegistry,
    FlowDefinition,
    StepDefinition,
    get_flow_keys,
    get_flow_index,
    get_flow_order,
    get_flow_titles,
    get_flow_descriptions,
    get_flow_steps,
    get_step_index,
    get_agent_position,
    get_total_flows,
    get_total_steps,
    get_sdlc_flow_keys,
    get_total_sdlc_flows,
)


class TestFlowRegistryBasics:
    """Test basic flow registry operations."""

    def test_get_flow_keys_returns_ordered_list(self):
        """Flow keys should be returned in order (SDLC + demo flows)."""
        keys = get_flow_keys()

        assert isinstance(keys, list)
        # All flows (SDLC + demo) should be returned
        assert len(keys) >= 7  # At least 7 SDLC flows
        # SDLC flows should be first and in order
        assert keys[:7] == ["signal", "plan", "build", "review", "gate", "deploy", "wisdom"]

    def test_get_sdlc_flow_keys_returns_only_sdlc(self):
        """SDLC flow keys should not include demo/utility flows."""
        keys = get_sdlc_flow_keys()

        assert isinstance(keys, list)
        assert len(keys) >= 6  # At least signal, plan, build, gate, deploy, wisdom
        # Demo/utility flows should not be in SDLC keys
        assert "reset" not in keys
        assert "stepwise-demo" not in keys

    def test_get_flow_order_is_alias(self):
        """get_flow_order should return same result as get_flow_keys."""
        assert get_flow_order() == get_flow_keys()

    def test_get_flow_index_returns_correct_values(self):
        """Each flow should have the correct 1-based index."""
        assert get_flow_index("signal") == 1
        assert get_flow_index("plan") == 2
        assert get_flow_index("build") == 3
        assert get_flow_index("review") == 4
        assert get_flow_index("gate") == 5
        assert get_flow_index("deploy") == 6
        assert get_flow_index("wisdom") == 7

    def test_get_flow_index_unknown_flow(self):
        """Unknown flow should return 99 (sentinel value)."""
        assert get_flow_index("nonexistent") == 99
        assert get_flow_index("") == 99

    def test_get_total_flows(self):
        """Total flows should match registry (SDLC + demo flows)."""
        total = get_total_flows()
        assert total >= 7  # At least 7 SDLC flows
        assert total == len(get_flow_keys())

    def test_get_total_sdlc_flows(self):
        """Total SDLC flows should match sdlc_flow_keys count."""
        assert get_total_sdlc_flows() == len(get_sdlc_flow_keys())
        assert get_total_sdlc_flows() >= 6  # At least core flows


class TestFlowTitlesAndDescriptions:
    """Test flow metadata retrieval."""

    def test_get_flow_titles_returns_all_flows(self):
        """Flow titles should be available for all flows."""
        titles = get_flow_titles()

        assert isinstance(titles, dict)
        assert len(titles) == get_total_flows()  # All flows including demo
        assert "signal" in titles
        assert "build" in titles
        assert "wisdom" in titles

    def test_get_flow_titles_content(self):
        """Flow titles should be meaningful strings."""
        titles = get_flow_titles()

        for key, title in titles.items():
            assert isinstance(title, str)
            assert len(title) > 0

    def test_get_flow_descriptions_returns_all_flows(self):
        """Flow descriptions should be available for all flows."""
        descriptions = get_flow_descriptions()

        assert isinstance(descriptions, dict)
        assert len(descriptions) == get_total_flows()  # All flows including demo

    def test_get_flow_descriptions_content(self):
        """Flow descriptions should be meaningful strings."""
        descriptions = get_flow_descriptions()

        for key, desc in descriptions.items():
            assert isinstance(desc, str)
            assert len(desc) > 0


class TestFlowSteps:
    """Test step-level operations."""

    def test_get_flow_steps_returns_list(self):
        """Flow steps should return a list of StepDefinition objects."""
        steps = get_flow_steps("build")

        assert isinstance(steps, list)
        assert len(steps) > 0
        assert all(isinstance(s, StepDefinition) for s in steps)

    def test_get_flow_steps_ordered(self):
        """Steps should have sequential indices starting at 1."""
        steps = get_flow_steps("build")

        indices = [s.index for s in steps]
        assert indices == list(range(1, len(steps) + 1))

    def test_get_flow_steps_have_agents(self):
        """Each step should have at least one agent."""
        steps = get_flow_steps("build")

        for step in steps:
            assert isinstance(step.agents, tuple)
            assert len(step.agents) >= 1

    def test_get_flow_steps_unknown_flow(self):
        """Unknown flow should return empty list."""
        steps = get_flow_steps("nonexistent")
        assert steps == []

    def test_get_step_index_returns_correct_values(self):
        """Step index should return 1-based position within flow."""
        # First step
        assert get_step_index("build", "branch") == 1
        # Second step
        assert get_step_index("build", "load_context") == 2

    def test_get_step_index_unknown_step(self):
        """Unknown step should return 0."""
        assert get_step_index("build", "nonexistent") == 0

    def test_get_step_index_unknown_flow(self):
        """Unknown flow should return 0."""
        assert get_step_index("nonexistent", "branch") == 0

    def test_get_total_steps(self):
        """Total steps should match actual step count."""
        for flow_key in get_sdlc_flow_keys():
            steps = get_flow_steps(flow_key)
            assert get_total_steps(flow_key) == len(steps)

    def test_get_total_steps_unknown_flow(self):
        """Unknown flow should return 0 steps."""
        assert get_total_steps("nonexistent") == 0


class TestAgentPositions:
    """Test agent position lookups."""

    def test_get_agent_position_known_agent(self):
        """Known agent should return position tuple(s)."""
        positions = get_agent_position("context-loader")

        assert isinstance(positions, list)
        assert len(positions) >= 1

        # Check tuple structure
        flow_key, step_id, flow_idx, step_idx = positions[0]
        assert flow_key == "build"
        assert step_id == "load_context"
        assert flow_idx == 3  # build is flow 3
        assert step_idx == 2  # load_context is step 2

    def test_get_agent_position_unknown_agent(self):
        """Unknown agent should return empty list."""
        positions = get_agent_position("nonexistent-agent")
        assert positions == []

    def test_get_agent_position_repo_operator(self):
        """repo-operator appears in multiple flows/steps."""
        positions = get_agent_position("repo-operator")

        assert isinstance(positions, list)
        # repo-operator is used in build flow at least (branch and commit steps)
        assert len(positions) >= 2

    def test_agent_positions_are_consistent(self):
        """Agent positions should be consistent with flow/step data."""
        # Pick a known agent
        positions = get_agent_position("context-loader")

        for flow_key, step_id, flow_idx, step_idx in positions:
            # Verify flow index matches
            assert get_flow_index(flow_key) == flow_idx
            # Verify step index matches
            assert get_step_index(flow_key, step_id) == step_idx


class TestFlowDefinition:
    """Test FlowDefinition dataclass."""

    def test_flow_definition_fields(self):
        """FlowDefinition should have all expected fields."""
        registry = FlowRegistry.get_instance()
        flow = registry.get_flow("build")

        assert flow is not None
        assert isinstance(flow, FlowDefinition)
        assert flow.key == "build"
        assert flow.index == 3
        assert isinstance(flow.title, str)
        assert isinstance(flow.short_title, str)
        assert isinstance(flow.description, str)
        assert isinstance(flow.steps, tuple)

    def test_flow_definition_steps_are_step_definitions(self):
        """FlowDefinition.steps should contain StepDefinition objects."""
        registry = FlowRegistry.get_instance()
        flow = registry.get_flow("build")

        for step in flow.steps:
            assert isinstance(step, StepDefinition)
            assert isinstance(step.id, str)
            assert isinstance(step.index, int)
            assert isinstance(step.agents, tuple)
            assert isinstance(step.role, str)


class TestStepDefinition:
    """Test StepDefinition dataclass."""

    def test_step_definition_fields(self):
        """StepDefinition should have all expected fields."""
        steps = get_flow_steps("build")
        step = steps[0]

        assert isinstance(step.id, str)
        assert isinstance(step.index, int)
        assert isinstance(step.agents, tuple)
        assert isinstance(step.role, str)

    def test_step_agents_are_strings(self):
        """Step agents should all be strings."""
        for flow_key in get_sdlc_flow_keys():
            for step in get_flow_steps(flow_key):
                for agent in step.agents:
                    assert isinstance(agent, str)
                    assert len(agent) > 0


class TestRegistrySingleton:
    """Test FlowRegistry singleton behavior."""

    def test_get_instance_returns_same_object(self):
        """get_instance should return the same registry instance."""
        FlowRegistry.reset()  # Clean state

        instance1 = FlowRegistry.get_instance()
        instance2 = FlowRegistry.get_instance()

        assert instance1 is instance2

        FlowRegistry.reset()  # Cleanup

    def test_reset_clears_singleton(self):
        """reset should clear the singleton instance."""
        FlowRegistry.reset()  # Clean state

        instance1 = FlowRegistry.get_instance()
        FlowRegistry.reset()
        instance2 = FlowRegistry.get_instance()

        assert instance1 is not instance2

        FlowRegistry.reset()  # Cleanup


class TestCrossCuttingAgents:
    """Test cross-cutting agent handling."""

    def test_cross_cutting_agent_has_positions(self):
        """Cross-cutting agents should appear in the registry."""
        # risk-analyst is a cross-cutting agent defined in signal.yaml
        positions = get_agent_position("risk-analyst")
        assert len(positions) > 0, "cross-cutting agent should have positions"

    def test_cross_cutting_agent_position_structure(self):
        """Cross-cutting agent positions should have None step_id and 0 step_idx."""
        positions = get_agent_position("risk-analyst")
        assert len(positions) > 0

        for flow_key, step_id, flow_idx, step_idx in positions:
            # Cross-cutting agents have step_id=None and step_idx=0
            assert step_id is None, f"cross-cutting step_id should be None, got {step_id}"
            assert step_idx == 0, f"cross-cutting step_idx should be 0, got {step_idx}"
            # But they still have valid flow info
            assert flow_key in get_flow_keys()
            assert flow_idx > 0

    def test_cross_cutting_agents_in_multiple_flows(self):
        """Cross-cutting agents may appear in multiple flows."""
        # clarifier and gh-reporter are defined in multiple flows' cross_cutting
        positions = get_agent_position("clarifier")

        flow_keys = {p[0] for p in positions}
        # clarifier is cross-cutting in signal and build (and possibly more)
        # It's also a step-attached agent in build flow
        assert len(flow_keys) >= 1, "clarifier should appear in at least one flow"

    def test_gh_reporter_has_cross_cutting_positions(self):
        """gh-reporter should appear as cross-cutting in some flows."""
        positions = get_agent_position("gh-reporter")
        assert len(positions) > 0, "gh-reporter should have positions"

        # gh-reporter appears both as cross-cutting and step-attached
        cross_cutting_positions = [p for p in positions if p[1] is None]
        assert len(cross_cutting_positions) > 0, "gh-reporter should have cross-cutting positions"


class TestFlowRegistryIntegration:
    """Integration tests for flow registry."""

    def test_all_sdlc_flows_have_steps(self):
        """Every SDLC flow should have at least one step defined."""
        for flow_key in get_sdlc_flow_keys():
            steps = get_flow_steps(flow_key)
            assert len(steps) > 0, f"Flow {flow_key} has no steps"

    def test_flow_indices_are_unique(self):
        """Each flow should have a unique index."""
        indices = [get_flow_index(key) for key in get_flow_keys()]
        assert len(indices) == len(set(indices))

    def test_flow_indices_are_sequential(self):
        """Flow indices should be sequential starting from 1."""
        indices = sorted(get_flow_index(key) for key in get_flow_keys())
        # Indices should be sequential 1, 2, 3, ... up to total flows
        expected = list(range(1, get_total_flows() + 1))
        assert indices == expected

    def test_all_step_agents_exist_in_index(self):
        """All agents mentioned in steps should be findable via get_agent_position."""
        seen_agents = set()

        for flow_key in get_sdlc_flow_keys():
            for step in get_flow_steps(flow_key):
                for agent in step.agents:
                    seen_agents.add(agent)

        # Each agent should have at least one position
        for agent in seen_agents:
            positions = get_agent_position(agent)
            assert len(positions) > 0, f"Agent {agent} has no positions"

    def test_build_flow_structure(self):
        """Build flow should have expected structure."""
        steps = get_flow_steps("build")
        step_ids = [s.id for s in steps]

        # Check key steps exist
        assert "branch" in step_ids
        assert "load_context" in step_ids
        assert "implement" in step_ids
        assert "commit" in step_ids

    def test_context_loader_position_formula(self):
        """Verify the F3.2 formula: context-loader is Flow 3, Step 2."""
        positions = get_agent_position("context-loader")

        assert len(positions) >= 1
        flow_key, step_id, flow_idx, step_idx = positions[0]

        # The "F3.2" formula
        assert f"F{flow_idx}.{step_idx}" == "F3.2"
