"""
Tests for station_library.py and routing infrastructure.

These tests verify:
1. StationLibrary loading and lookup
2. Default pack stations
3. EXTEND_GRAPH validation
4. InjectedNodeSpec handling
"""

import pytest
from pathlib import Path
from typing import Dict, Any

from swarm.runtime.station_library import (
    StationLibrary,
    StationSpec,
    load_station_library,
    station_spec_to_dict,
    station_spec_from_dict,
    DEFAULT_STATIONS,
)
from swarm.runtime.types import (
    InjectedNodeSpec,
    RunState,
    RoutingSignal,
    RoutingDecision,
    injected_node_spec_to_dict,
    injected_node_spec_from_dict,
    run_state_to_dict,
    run_state_from_dict,
)


# =============================================================================
# StationSpec Tests
# =============================================================================


class TestStationSpec:
    """Tests for StationSpec dataclass."""

    def test_station_spec_creation(self):
        """Test creating a StationSpec."""
        spec = StationSpec(
            station_id="test-station",
            name="Test Station",
            description="A test station",
            category="sidequest",
            agent_key="test-agent",
        )

        assert spec.station_id == "test-station"
        assert spec.name == "Test Station"
        assert spec.category == "sidequest"
        assert spec.agent_key == "test-agent"
        assert spec.pack_origin == "default"

    def test_station_spec_serialization(self):
        """Test StationSpec round-trip serialization."""
        spec = StationSpec(
            station_id="test-station",
            name="Test Station",
            description="A test station",
            category="worker",
            agent_key="test-agent",
            tags=["test", "example"],
        )

        data = station_spec_to_dict(spec)
        restored = station_spec_from_dict(data)

        assert restored.station_id == spec.station_id
        assert restored.name == spec.name
        assert restored.category == spec.category
        assert restored.tags == spec.tags


# =============================================================================
# StationLibrary Tests
# =============================================================================


class TestStationLibrary:
    """Tests for StationLibrary registry."""

    def test_empty_library(self):
        """Test empty library has no stations."""
        library = StationLibrary()
        assert len(library.list_all_stations()) == 0
        assert not library.has_station("clarifier")

    def test_load_default_pack(self):
        """Test loading default pack stations."""
        library = StationLibrary()
        count = library.load_default_pack()

        assert count == len(DEFAULT_STATIONS)
        assert library.has_station("clarifier")
        assert library.has_station("research")
        assert library.has_station("code-implementer")

    def test_get_station(self):
        """Test retrieving a station by ID."""
        library = StationLibrary()
        library.load_default_pack()

        clarifier = library.get_station("clarifier")
        assert clarifier is not None
        assert clarifier.station_id == "clarifier"
        assert clarifier.category == "sidequest"
        assert "clarifier" in clarifier.tags or "sidequest" in clarifier.tags

    def test_get_nonexistent_station(self):
        """Test getting a station that doesn't exist."""
        library = StationLibrary()
        library.load_default_pack()

        assert library.get_station("nonexistent") is None

    def test_get_stations_by_category(self):
        """Test filtering stations by category."""
        library = StationLibrary()
        library.load_default_pack()

        sidequests = library.get_stations_by_category("sidequest")
        assert len(sidequests) > 0
        assert all(s.category == "sidequest" for s in sidequests)

        workers = library.get_stations_by_category("worker")
        assert len(workers) > 0
        assert all(s.category == "worker" for s in workers)

    def test_get_stations_by_tag(self):
        """Test filtering stations by tag."""
        library = StationLibrary()
        library.load_default_pack()

        sidequest_tagged = library.get_stations_by_tag("sidequest")
        assert len(sidequest_tagged) > 0

    def test_validate_target(self):
        """Test EXTEND_GRAPH target validation."""
        library = StationLibrary()
        library.load_default_pack()

        # Valid targets
        assert library.validate_target("clarifier")
        assert library.validate_target("research")
        assert library.validate_target("code-implementer")

        # Invalid targets
        assert not library.validate_target("nonexistent")
        assert not library.validate_target("")

    def test_list_station_ids(self):
        """Test listing all station IDs."""
        library = StationLibrary()
        library.load_default_pack()

        ids = library.list_station_ids()
        assert "clarifier" in ids
        assert "research" in ids
        assert len(ids) == len(DEFAULT_STATIONS)

    def test_library_serialization(self):
        """Test serializing library state."""
        library = StationLibrary()
        library.load_default_pack()

        data = library.to_dict()
        assert "stations" in data
        assert "categories" in data
        assert "tags" in data
        assert "clarifier" in data["stations"]


class TestLoadStationLibrary:
    """Tests for load_station_library convenience function."""

    def test_load_without_repo(self):
        """Test loading library without repo path."""
        library = load_station_library(None)

        # Should have default stations
        assert library.has_station("clarifier")
        assert library.has_station("code-implementer")

    def test_load_with_repo(self, tmp_path: Path):
        """Test loading library with repo path (no custom stations)."""
        library = load_station_library(tmp_path)

        # Should still have defaults
        assert library.has_station("clarifier")


# =============================================================================
# InjectedNodeSpec Tests
# =============================================================================


class TestInjectedNodeSpec:
    """Tests for InjectedNodeSpec dataclass."""

    def test_injected_node_spec_creation(self):
        """Test creating an InjectedNodeSpec."""
        spec = InjectedNodeSpec(
            node_id="sq-clarifier-0",
            station_id="clarifier",
            agent_key="clarifier",
            role="Sidequest clarifier step 1/1",
            sidequest_origin="clarifier",
            sequence_index=0,
            total_in_sequence=1,
        )

        assert spec.node_id == "sq-clarifier-0"
        assert spec.station_id == "clarifier"
        assert spec.sidequest_origin == "clarifier"
        assert spec.sequence_index == 0

    def test_injected_node_spec_serialization(self):
        """Test InjectedNodeSpec round-trip serialization."""
        spec = InjectedNodeSpec(
            node_id="sq-research-1",
            station_id="research",
            template_id="context-loader",
            agent_key="context-loader",
            role="Research step 2/3",
            params={"query": "find all API endpoints"},
            sidequest_origin="research",
            sequence_index=1,
            total_in_sequence=3,
        )

        data = injected_node_spec_to_dict(spec)
        restored = injected_node_spec_from_dict(data)

        assert restored.node_id == spec.node_id
        assert restored.station_id == spec.station_id
        assert restored.template_id == spec.template_id
        assert restored.params == spec.params
        assert restored.sequence_index == spec.sequence_index
        assert restored.total_in_sequence == spec.total_in_sequence


# =============================================================================
# RunState Injected Node Tests
# =============================================================================


class TestRunStateInjectedNodes:
    """Tests for RunState injected node handling."""

    def test_register_injected_node(self):
        """Test registering an injected node."""
        state = RunState(
            run_id="test-run",
            flow_key="build",
        )

        spec = InjectedNodeSpec(
            node_id="sq-clarifier-0",
            station_id="clarifier",
        )

        state.register_injected_node(spec)

        assert "sq-clarifier-0" in state.injected_nodes
        assert "sq-clarifier-0" in state.injected_node_specs
        assert state.get_injected_node_spec("sq-clarifier-0") == spec

    def test_register_multiple_nodes(self):
        """Test registering multiple injected nodes (multi-step sidequest)."""
        state = RunState(
            run_id="test-run",
            flow_key="build",
        )

        # Inject a 3-step sidequest
        for i in range(3):
            spec = InjectedNodeSpec(
                node_id=f"sq-research-{i}",
                station_id="research" if i == 0 else "context-loader",
                sequence_index=i,
                total_in_sequence=3,
                sidequest_origin="research",
            )
            state.register_injected_node(spec)

        assert len(state.injected_nodes) == 3
        assert len(state.injected_node_specs) == 3

        # Verify sequence
        for i in range(3):
            spec = state.get_injected_node_spec(f"sq-research-{i}")
            assert spec.sequence_index == i
            assert spec.total_in_sequence == 3

    def test_get_nonexistent_spec(self):
        """Test getting spec for non-injected node returns None."""
        state = RunState(
            run_id="test-run",
            flow_key="build",
        )

        assert state.get_injected_node_spec("nonexistent") is None

    def test_run_state_serialization_with_injected_nodes(self):
        """Test RunState round-trip with injected nodes."""
        state = RunState(
            run_id="test-run",
            flow_key="build",
        )

        # Register some injected nodes
        for i in range(2):
            spec = InjectedNodeSpec(
                node_id=f"sq-test-{i}",
                station_id="test-station",
                sequence_index=i,
                total_in_sequence=2,
            )
            state.register_injected_node(spec)

        # Serialize
        data = run_state_to_dict(state)

        # Verify serialization structure
        assert "injected_node_specs" in data
        assert len(data["injected_node_specs"]) == 2
        assert "sq-test-0" in data["injected_node_specs"]

        # Deserialize
        restored = run_state_from_dict(data)

        # Verify restoration
        assert len(restored.injected_node_specs) == 2
        assert restored.get_injected_node_spec("sq-test-0") is not None
        assert restored.get_injected_node_spec("sq-test-1") is not None

        spec0 = restored.get_injected_node_spec("sq-test-0")
        assert spec0.sequence_index == 0
        assert spec0.total_in_sequence == 2


# =============================================================================
# Integration Tests
# =============================================================================


class TestRoutingInfrastructureIntegration:
    """Integration tests for the routing infrastructure."""

    def test_sidequest_node_id_format(self):
        """Test that sidequest nodes use the correct ID format."""
        state = RunState(run_id="test", flow_key="build")

        # The format should be: sq-{sidequest_id}-{step_index}
        spec = InjectedNodeSpec(
            node_id="sq-clarifier-0",
            station_id="clarifier",
            sidequest_origin="clarifier",
        )
        state.register_injected_node(spec)

        # Verify the node can be looked up
        assert state.get_injected_node_spec("sq-clarifier-0") is not None

        # Verify the sidequest origin is tracked
        retrieved = state.get_injected_node_spec("sq-clarifier-0")
        assert retrieved.sidequest_origin == "clarifier"

    def test_station_library_provides_agents(self):
        """Test that station library provides agent keys for nodes."""
        library = StationLibrary()
        library.load_default_pack()

        # Get a station
        clarifier = library.get_station("clarifier")
        assert clarifier is not None

        # Verify it has an agent key
        assert clarifier.agent_key is not None
        assert clarifier.agent_key == "clarifier"

    def test_full_sidequest_injection_flow(self):
        """Test the complete flow of injecting a sidequest."""
        # 1. Create run state
        state = RunState(run_id="test-run", flow_key="build")

        # 2. Simulate sidequest injection (what apply_detour_request does)
        sidequest_id = "research"
        total_steps = 2

        for i in range(total_steps):
            spec = InjectedNodeSpec(
                node_id=f"sq-{sidequest_id}-{i}",
                station_id="context-loader" if i == 0 else "research",
                agent_key="context-loader" if i == 0 else "research",
                role=f"Sidequest {sidequest_id} step {i+1}/{total_steps}",
                params={"objective": "Gather context"},
                sidequest_origin=sidequest_id,
                sequence_index=i,
                total_in_sequence=total_steps,
            )
            state.register_injected_node(spec)

        # 3. Verify all nodes are registered
        assert len(state.injected_nodes) == 2
        assert len(state.injected_node_specs) == 2

        # 4. Verify nodes can be resolved
        first = state.get_injected_node_spec("sq-research-0")
        assert first is not None
        assert first.sequence_index == 0

        second = state.get_injected_node_spec("sq-research-1")
        assert second is not None
        assert second.sequence_index == 1

        # 5. Verify serialization preserves everything
        data = run_state_to_dict(state)
        restored = run_state_from_dict(data)

        assert len(restored.injected_node_specs) == 2
        assert restored.get_injected_node_spec("sq-research-0").sequence_index == 0
        assert restored.get_injected_node_spec("sq-research-1").sequence_index == 1
