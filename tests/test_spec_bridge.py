"""
Tests for spec_bridge.py - Pack JSON to FlowDefinition conversion.

These tests verify that:
1. JSON pack specs are correctly converted to FlowDefinition
2. Edge analysis correctly identifies routing patterns
3. Step ordering is inferred correctly from graph topology
4. Microloop patterns are preserved through conversion
"""

import json
import pytest
from pathlib import Path

from swarm.runtime.spec_bridge import (
    flow_spec_to_definition,
    load_flow_from_json,
    load_flow_from_pack,
    analyze_node_edges,
    infer_step_order,
    PackFlowRegistry,
    FLOW_INDEX_MAP,
)
from swarm.config.pack_registry import (
    FlowSpecData,
    FlowNode,
    FlowEdge,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def repo_root():
    """Get the repository root."""
    return Path(__file__).resolve().parents[1]


@pytest.fixture
def build_flow_json(repo_root):
    """Load the build flow JSON spec."""
    json_path = repo_root / "swarm" / "packs" / "flows" / "build.json"
    if json_path.exists():
        with open(json_path) as f:
            return json.load(f)
    pytest.skip("build.json not found")


@pytest.fixture
def simple_linear_spec():
    """Create a simple linear flow spec for testing."""
    return FlowSpecData(
        id="test-linear",
        name="Test Linear",
        description="A simple linear flow",
        version=1,
        nodes=[
            FlowNode(node_id="step-1", template_id="agent-1", params={}, overrides={}),
            FlowNode(node_id="step-2", template_id="agent-2", params={}, overrides={}),
            FlowNode(node_id="step-3", template_id="agent-3", params={}, overrides={}),
        ],
        edges=[
            FlowEdge(edge_id="e1", from_node="step-1", to_node="step-2", edge_type="sequence", priority=50),
            FlowEdge(edge_id="e2", from_node="step-2", to_node="step-3", edge_type="sequence", priority=50),
        ],
        policy={"max_loop_iterations": 10},
        pack_origin="test",
    )


@pytest.fixture
def microloop_spec():
    """Create a flow spec with microloop pattern."""
    return FlowSpecData(
        id="test-microloop",
        name="Test Microloop",
        description="A flow with author-critic microloop",
        version=1,
        nodes=[
            FlowNode(node_id="author", template_id="author-agent", params={}, overrides={}),
            FlowNode(node_id="critic", template_id="critic-agent", params={}, overrides={"exit_on": {"status": ["VERIFIED"]}}),
            FlowNode(node_id="final", template_id="final-agent", params={}, overrides={}),
        ],
        edges=[
            FlowEdge(edge_id="e1", from_node="author", to_node="critic", edge_type="sequence", priority=50),
            FlowEdge(edge_id="e2-loop", from_node="critic", to_node="author", edge_type="loop", priority=40, condition={"expression": "status != 'VERIFIED'"}),
            FlowEdge(edge_id="e2-exit", from_node="critic", to_node="final", edge_type="sequence", priority=50, condition={"expression": "status == 'VERIFIED'"}),
        ],
        policy={"max_loop_iterations": 50, "suggested_sidequests": ["clarifier"]},
        pack_origin="test",
    )


# =============================================================================
# Basic Conversion Tests
# =============================================================================


class TestFlowSpecToDefinition:
    """Test flow_spec_to_definition conversion."""

    def test_linear_flow_conversion(self, simple_linear_spec):
        """Test converting a simple linear flow."""
        flow_def = flow_spec_to_definition(simple_linear_spec, flow_index=99)

        assert flow_def.key == "test-linear"
        assert flow_def.title == "Test Linear"
        assert flow_def.index == 99
        assert len(flow_def.steps) == 3

        # Check step order
        step_ids = [s.id for s in flow_def.steps]
        assert step_ids == ["step-1", "step-2", "step-3"]

        # Check routing
        assert flow_def.steps[0].routing.kind == "linear"
        assert flow_def.steps[0].routing.next == "step-2"
        assert flow_def.steps[1].routing.next == "step-3"

    def test_microloop_conversion(self, microloop_spec):
        """Test converting a flow with microloop."""
        flow_def = flow_spec_to_definition(microloop_spec)

        # Find the critic step
        critic_step = next((s for s in flow_def.steps if s.id == "critic"), None)
        assert critic_step is not None

        # Check microloop routing
        assert critic_step.routing.kind == "microloop"
        assert critic_step.routing.loop_target == "author"
        assert "VERIFIED" in critic_step.routing.loop_success_values

    def test_cross_cutting_agents(self, microloop_spec):
        """Test that suggested_sidequests become cross_cutting."""
        flow_def = flow_spec_to_definition(microloop_spec)

        assert "clarifier" in flow_def.cross_cutting

    def test_flow_index_inference(self):
        """Test that flow index is inferred from flow key."""
        spec = FlowSpecData(
            id="build",
            name="Build Flow",
            description="",
            version=1,
            nodes=[FlowNode(node_id="n1", template_id="t1", params={}, overrides={})],
            edges=[],
            policy={},
            pack_origin="test",
        )

        flow_def = flow_spec_to_definition(spec)
        assert flow_def.index == 3  # build is flow 3


# =============================================================================
# Edge Analysis Tests
# =============================================================================


class TestEdgeAnalysis:
    """Test edge analysis for routing patterns."""

    def test_sequence_only(self):
        """Test node with only sequence edges."""
        edges = [
            FlowEdge(edge_id="e1", from_node="a", to_node="b", edge_type="sequence", priority=50),
        ]

        analysis = analyze_node_edges("a", edges)

        assert analysis.loop_edge is None
        assert len(analysis.sequence_edges) == 1
        assert analysis.sequence_edges[0].to_node == "b"

    def test_loop_detection(self):
        """Test detection of loop edges."""
        edges = [
            FlowEdge(edge_id="e1", from_node="critic", to_node="author", edge_type="loop", priority=40),
            FlowEdge(edge_id="e2", from_node="critic", to_node="final", edge_type="sequence", priority=50),
        ]

        analysis = analyze_node_edges("critic", edges)

        assert analysis.loop_edge is not None
        assert analysis.loop_edge.to_node == "author"


# =============================================================================
# Step Ordering Tests
# =============================================================================


class TestStepOrdering:
    """Test step ordering from graph topology."""

    def test_linear_ordering(self):
        """Test ordering of linear sequence."""
        nodes = [
            FlowNode(node_id="c", template_id="", params={}, overrides={}),
            FlowNode(node_id="a", template_id="", params={}, overrides={}),
            FlowNode(node_id="b", template_id="", params={}, overrides={}),
        ]
        edges = [
            FlowEdge(edge_id="e1", from_node="a", to_node="b", edge_type="sequence", priority=50),
            FlowEdge(edge_id="e2", from_node="b", to_node="c", edge_type="sequence", priority=50),
        ]

        order = infer_step_order(nodes, edges)

        # a should come first (no incoming), then b, then c
        assert order == ["a", "b", "c"]

    def test_loop_edges_ignored(self):
        """Test that loop edges don't affect ordering."""
        nodes = [
            FlowNode(node_id="author", template_id="", params={}, overrides={}),
            FlowNode(node_id="critic", template_id="", params={}, overrides={}),
        ]
        edges = [
            FlowEdge(edge_id="e1", from_node="author", to_node="critic", edge_type="sequence", priority=50),
            FlowEdge(edge_id="e2", from_node="critic", to_node="author", edge_type="loop", priority=40),
        ]

        order = infer_step_order(nodes, edges)

        # Loop edge should not create cycle in ordering
        assert order[0] == "author"
        assert order[1] == "critic"


# =============================================================================
# Integration Tests
# =============================================================================


class TestPackFlowRegistry:
    """Test PackFlowRegistry as drop-in replacement."""

    def test_load_flow(self, repo_root):
        """Test loading a flow from pack."""
        registry = PackFlowRegistry(repo_root)

        flow_def = registry.get_flow("build")

        # Skip if pack doesn't have build flow
        if flow_def is None:
            pytest.skip("build flow not in pack")

        assert flow_def.key == "build"
        assert len(flow_def.steps) > 0

    def test_flow_order(self, repo_root):
        """Test flow_order property."""
        registry = PackFlowRegistry(repo_root)

        order = registry.flow_order

        # Should be in SDLC order
        for i, key in enumerate(order[:-1]):
            if key in FLOW_INDEX_MAP and order[i + 1] in FLOW_INDEX_MAP:
                assert FLOW_INDEX_MAP[key] < FLOW_INDEX_MAP[order[i + 1]]


class TestLoadFlowFromJson:
    """Test loading flow directly from JSON file."""

    def test_load_build_flow(self, repo_root):
        """Test loading build.json."""
        json_path = repo_root / "swarm" / "packs" / "flows" / "build.json"

        if not json_path.exists():
            pytest.skip("build.json not found")

        flow_def = load_flow_from_json(json_path)

        assert flow_def is not None
        assert flow_def.key == "build"
        assert "context-loader" in [s.id for s in flow_def.steps]


# =============================================================================
# Real Flow Tests
# =============================================================================


class TestRealFlowConversion:
    """Test conversion of real pack flow specs."""

    def test_build_flow_has_microloops(self, repo_root, build_flow_json):
        """Verify build flow preserves microloop patterns."""
        flow_def = load_flow_from_json(
            repo_root / "swarm" / "packs" / "flows" / "build.json"
        )

        # Find test-critic step
        test_critic = next((s for s in flow_def.steps if s.id == "test-critic"), None)

        if test_critic is None:
            pytest.skip("test-critic not in build flow")

        # Should have microloop routing
        assert test_critic.routing is not None
        assert test_critic.routing.kind == "microloop"
        assert test_critic.routing.loop_target == "test-author"

    def test_all_pack_flows_convert(self, repo_root):
        """Test that all pack flows can be converted."""
        flows_dir = repo_root / "swarm" / "packs" / "flows"

        if not flows_dir.exists():
            pytest.skip("packs/flows directory not found")

        for json_file in flows_dir.glob("*.json"):
            flow_def = load_flow_from_json(json_file)
            assert flow_def is not None, f"Failed to convert {json_file.name}"
            assert len(flow_def.steps) > 0, f"No steps in {json_file.name}"
