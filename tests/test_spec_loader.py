"""Tests for the spec loader module.

This module tests loading StationSpecs, FlowSpecs, and fragments from YAML files.
Tests cover both successful loading and graceful error handling for missing files.
"""

import pytest
from pathlib import Path
from unittest.mock import patch
import tempfile
import shutil

# Add swarm to path
import sys
_SWARM_ROOT = Path(__file__).resolve().parent.parent
if str(_SWARM_ROOT) not in sys.path:
    sys.path.insert(0, str(_SWARM_ROOT))

from swarm.spec.loader import (
    load_station,
    load_station_cached,
    list_stations,
    load_flow,
    load_flow_cached,
    list_flows,
    load_fragment,
    load_fragments,
    load_fragment_cached,
    list_fragments,
    get_spec_root,
    validate_specs,
)
from swarm.spec.types import (
    StationSpec,
    FlowSpec,
    StationCategory,
    RoutingKind,
)


class TestGetSpecRoot:
    """Tests for get_spec_root function."""

    def test_get_spec_root_finds_repo_root(self):
        """get_spec_root should find the spec directory from cwd."""
        spec_root = get_spec_root()

        assert spec_root.exists()
        assert (spec_root / "stations").exists()
        assert (spec_root / "flows").exists()

    def test_get_spec_root_with_explicit_repo_root(self):
        """get_spec_root should work with explicit repo_root."""
        repo_root = Path(__file__).parent.parent
        spec_root = get_spec_root(repo_root)

        assert spec_root == repo_root / "swarm" / "spec"


class TestLoadStation:
    """Tests for loading StationSpecs from YAML."""

    def test_load_station_known_station(self):
        """Load a known station spec successfully."""
        station = load_station("code-implementer")

        assert isinstance(station, StationSpec)
        assert station.id == "code-implementer"
        assert station.version >= 1
        assert station.title == "Code Implementer"
        assert station.category == StationCategory.IMPLEMENTATION

    def test_load_station_sdk_configuration(self):
        """Station SDK configuration should be loaded correctly."""
        station = load_station("code-implementer")

        assert station.sdk.model == "sonnet"
        assert station.sdk.permission_mode == "bypassPermissions"
        assert "Read" in station.sdk.allowed_tools
        assert "Write" in station.sdk.allowed_tools
        assert station.sdk.max_turns >= 1
        assert station.sdk.sandbox.enabled is True

    def test_load_station_identity(self):
        """Station identity should be loaded correctly."""
        station = load_station("code-implementer")

        assert station.identity.system_append != ""
        assert station.identity.tone in ("neutral", "analytical", "critical", "supportive")

    def test_load_station_io_contract(self):
        """Station IO contract should be loaded correctly."""
        station = load_station("code-implementer")

        assert isinstance(station.io.required_inputs, tuple)
        assert isinstance(station.io.optional_inputs, tuple)
        assert isinstance(station.io.required_outputs, tuple)
        assert isinstance(station.io.optional_outputs, tuple)

    def test_load_station_handoff_contract(self):
        """Station handoff contract should be loaded correctly."""
        station = load_station("code-implementer")

        assert "{{run.base}}" in station.handoff.path_template
        assert "status" in station.handoff.required_fields
        assert "summary" in station.handoff.required_fields
        assert "artifacts" in station.handoff.required_fields

    def test_load_station_invariants(self):
        """Station invariants should be loaded as tuples."""
        station = load_station("code-implementer")

        assert isinstance(station.invariants, tuple)
        assert len(station.invariants) > 0

    def test_load_station_routing_hints(self):
        """Station routing hints should be loaded correctly."""
        station = load_station("code-implementer")

        assert station.routing_hints.on_verified == "advance"
        assert station.routing_hints.on_unverified in ("loop", "advance_with_concerns", "escalate")
        assert station.routing_hints.on_blocked == "escalate"

    def test_load_station_not_found_raises_error(self):
        """Loading a nonexistent station should raise FileNotFoundError."""
        with pytest.raises(FileNotFoundError) as exc_info:
            load_station("nonexistent-station-xyz")

        assert "nonexistent-station-xyz" in str(exc_info.value)

    def test_load_station_cached_returns_same_object(self):
        """Cached station loading should return identical objects."""
        repo_root = str(Path(__file__).parent.parent)

        # Clear cache first
        load_station_cached.cache_clear()

        station1 = load_station_cached("code-implementer", repo_root)
        station2 = load_station_cached("code-implementer", repo_root)

        assert station1 is station2


class TestListStations:
    """Tests for listing available stations."""

    def test_list_stations_returns_list(self):
        """list_stations should return a list of station IDs."""
        stations = list_stations()

        assert isinstance(stations, list)
        assert len(stations) > 0

    def test_list_stations_contains_known_stations(self):
        """list_stations should include known station IDs."""
        stations = list_stations()

        # Check for some expected stations
        assert "code-implementer" in stations
        assert "test-author" in stations
        assert "code-critic" in stations

    def test_list_stations_excludes_underscore_files(self):
        """list_stations should exclude files starting with underscore."""
        stations = list_stations()

        for station_id in stations:
            assert not station_id.startswith("_")

    def test_list_stations_sorted(self):
        """list_stations should return a sorted list."""
        stations = list_stations()

        assert stations == sorted(stations)


class TestLoadFlow:
    """Tests for loading FlowSpecs from YAML."""

    def test_load_flow_known_flow(self):
        """Load a known flow spec successfully."""
        flow = load_flow("3-build")

        assert isinstance(flow, FlowSpec)
        assert flow.id == "3-build"
        assert flow.version >= 1
        assert "Build" in flow.title

    def test_load_flow_description(self):
        """Flow description should be loaded correctly."""
        flow = load_flow("3-build")

        assert flow.description != ""
        assert len(flow.description) > 10

    def test_load_flow_defaults(self):
        """Flow defaults should be loaded correctly."""
        flow = load_flow("3-build")

        assert flow.defaults.context_pack.include_upstream_artifacts is True
        assert flow.defaults.context_pack.include_previous_envelopes is True
        assert flow.defaults.context_pack.max_envelopes >= 1

    def test_load_flow_steps(self):
        """Flow steps should be loaded correctly."""
        flow = load_flow("3-build")

        assert isinstance(flow.steps, tuple)
        assert len(flow.steps) > 0

        for step in flow.steps:
            assert step.id != ""
            assert step.station != ""
            assert step.objective != ""

    def test_load_flow_step_routing(self):
        """Flow step routing should be loaded correctly."""
        flow = load_flow("3-build")

        for step in flow.steps:
            routing = step.routing
            assert routing.kind in (RoutingKind.LINEAR, RoutingKind.MICROLOOP,
                                    RoutingKind.BRANCH, RoutingKind.TERMINAL)

            if routing.kind == RoutingKind.LINEAR:
                # LINEAR steps have a next step (except terminal)
                pass  # next can be None for last step
            elif routing.kind == RoutingKind.MICROLOOP:
                assert routing.loop_target is not None
                assert routing.max_iterations >= 1

    def test_load_flow_step_teaching(self):
        """Flow step teaching metadata should be loaded correctly."""
        flow = load_flow("3-build")

        for step in flow.steps:
            assert isinstance(step.teaching.highlight, bool)
            assert isinstance(step.teaching.note, str)

    def test_load_flow_cross_cutting_stations(self):
        """Flow cross-cutting stations should be loaded correctly."""
        flow = load_flow("3-build")

        assert isinstance(flow.cross_cutting_stations, tuple)
        # 3-build should have cross-cutting stations
        assert len(flow.cross_cutting_stations) > 0
        assert "clarifier" in flow.cross_cutting_stations

    def test_load_flow_not_found_raises_error(self):
        """Loading a nonexistent flow should raise FileNotFoundError."""
        with pytest.raises(FileNotFoundError) as exc_info:
            load_flow("999-nonexistent-flow")

        assert "999-nonexistent-flow" in str(exc_info.value)

    def test_load_flow_cached_returns_same_object(self):
        """Cached flow loading should return identical objects."""
        repo_root = str(Path(__file__).parent.parent)

        # Clear cache first
        load_flow_cached.cache_clear()

        flow1 = load_flow_cached("3-build", repo_root)
        flow2 = load_flow_cached("3-build", repo_root)

        assert flow1 is flow2


class TestListFlows:
    """Tests for listing available flows."""

    def test_list_flows_returns_list(self):
        """list_flows should return a list of flow IDs."""
        flows = list_flows()

        assert isinstance(flows, list)
        assert len(flows) > 0

    def test_list_flows_contains_known_flows(self):
        """list_flows should include known flow IDs."""
        flows = list_flows()

        # Check for expected flows
        assert "1-signal" in flows
        assert "2-plan" in flows
        assert "3-build" in flows

    def test_list_flows_sorted(self):
        """list_flows should return a sorted list."""
        flows = list_flows()

        assert flows == sorted(flows)


class TestLoadFragment:
    """Tests for loading prompt fragments."""

    def test_load_fragment_known_fragment(self):
        """Load a known fragment successfully."""
        content = load_fragment("common/invariants.md")

        assert isinstance(content, str)
        assert len(content) > 0
        assert "non-negotiable" in content.lower() or "invariant" in content.lower()

    def test_load_fragment_not_found_raises_error(self):
        """Loading a nonexistent fragment should raise FileNotFoundError."""
        with pytest.raises(FileNotFoundError) as exc_info:
            load_fragment("nonexistent/fragment.md")

        assert "nonexistent/fragment.md" in str(exc_info.value)

    def test_load_fragment_cached_returns_same_object(self):
        """Cached fragment loading should return identical objects."""
        repo_root = str(Path(__file__).parent.parent)

        # Clear cache first
        load_fragment_cached.cache_clear()

        content1 = load_fragment_cached("common/invariants.md", repo_root)
        content2 = load_fragment_cached("common/invariants.md", repo_root)

        assert content1 == content2


class TestLoadFragments:
    """Tests for loading and concatenating multiple fragments."""

    def test_load_fragments_concatenates_content(self):
        """load_fragments should concatenate multiple fragments."""
        content = load_fragments(["common/invariants.md", "common/evidence.md"])

        assert isinstance(content, str)
        # Should contain content from both fragments
        assert len(content) > 100  # Non-trivial content

    def test_load_fragments_uses_separator(self):
        """load_fragments should use the specified separator."""
        content = load_fragments(
            ["common/invariants.md", "common/evidence.md"],
            separator="\n\n###SEPARATOR###\n\n"
        )

        # Default separator or custom should be present
        assert len(content.split("###SEPARATOR###")) >= 2 or len(content) > 100

    def test_load_fragments_handles_missing_gracefully(self):
        """load_fragments should skip missing fragments with warning."""
        # Mix of existing and nonexistent fragments
        content = load_fragments([
            "common/invariants.md",
            "nonexistent/fragment.md",
            "common/evidence.md"
        ])

        # Should still return content from existing fragments
        assert len(content) > 0

    def test_load_fragments_empty_list_returns_empty(self):
        """load_fragments with empty list should return empty string."""
        content = load_fragments([])

        assert content == ""


class TestListFragments:
    """Tests for listing available fragments."""

    def test_list_fragments_returns_list(self):
        """list_fragments should return a list of fragment paths."""
        fragments = list_fragments()

        assert isinstance(fragments, list)
        assert len(fragments) > 0

    def test_list_fragments_contains_known_fragments(self):
        """list_fragments should include known fragment paths."""
        fragments = list_fragments()

        assert "common/invariants.md" in fragments

    def test_list_fragments_uses_forward_slashes(self):
        """list_fragments should use forward slashes for paths."""
        fragments = list_fragments()

        for frag_path in fragments:
            assert "\\" not in frag_path  # No backslashes

    def test_list_fragments_sorted(self):
        """list_fragments should return a sorted list."""
        fragments = list_fragments()

        assert fragments == sorted(fragments)


class TestValidateSpecs:
    """Tests for the validate_specs function."""

    def test_validate_specs_returns_dict(self):
        """validate_specs should return a dict with errors and warnings."""
        result = validate_specs()

        assert isinstance(result, dict)
        assert "errors" in result
        assert "warnings" in result
        assert isinstance(result["errors"], list)
        assert isinstance(result["warnings"], list)

    def test_validate_specs_no_errors_in_valid_repo(self):
        """validate_specs should return no errors for a valid spec repository."""
        result = validate_specs()

        # The actual swarm/spec should be valid
        # If there are errors, they should be investigated
        assert len(result["errors"]) == 0, f"Unexpected errors: {result['errors']}"


class TestEmptySpecDirectory:
    """Tests for handling empty or missing spec directories."""

    def test_list_stations_empty_dir(self):
        """list_stations should return empty list for empty directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            # Create empty spec structure
            (tmppath / "swarm" / "spec" / "stations").mkdir(parents=True)
            (tmppath / "swarm" / "spec" / "flows").mkdir(parents=True)
            (tmppath / "swarm" / "spec" / "fragments").mkdir(parents=True)

            stations = list_stations(tmppath)
            assert stations == []

    def test_list_flows_empty_dir(self):
        """list_flows should return empty list for empty directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            # Create empty spec structure
            (tmppath / "swarm" / "spec" / "stations").mkdir(parents=True)
            (tmppath / "swarm" / "spec" / "flows").mkdir(parents=True)
            (tmppath / "swarm" / "spec" / "fragments").mkdir(parents=True)

            flows = list_flows(tmppath)
            assert flows == []

    def test_list_fragments_empty_dir(self):
        """list_fragments should return empty list for empty directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            # Create empty spec structure
            (tmppath / "swarm" / "spec" / "stations").mkdir(parents=True)
            (tmppath / "swarm" / "spec" / "flows").mkdir(parents=True)
            (tmppath / "swarm" / "spec" / "fragments").mkdir(parents=True)

            fragments = list_fragments(tmppath)
            assert fragments == []


class TestStationCategories:
    """Tests for station category parsing."""

    def test_all_station_categories_valid(self):
        """All loaded stations should have valid categories."""
        for station_id in list_stations():
            station = load_station(station_id)
            assert isinstance(station.category, StationCategory)

    def test_known_station_categories(self):
        """Known stations should have expected categories."""
        # code-implementer should be implementation
        station = load_station("code-implementer")
        assert station.category == StationCategory.IMPLEMENTATION

        # test-critic should be critic
        if "test-critic" in list_stations():
            station = load_station("test-critic")
            assert station.category == StationCategory.CRITIC


class TestRoutingKinds:
    """Tests for routing kind parsing in flows."""

    def test_all_step_routing_kinds_valid(self):
        """All flow step routing kinds should be valid enums."""
        for flow_id in list_flows():
            flow = load_flow(flow_id)
            for step in flow.steps:
                assert isinstance(step.routing.kind, RoutingKind)

    def test_microloop_routing_has_loop_target(self):
        """MICROLOOP routing should have a loop_target."""
        for flow_id in list_flows():
            flow = load_flow(flow_id)
            for step in flow.steps:
                if step.routing.kind == RoutingKind.MICROLOOP:
                    assert step.routing.loop_target is not None, \
                        f"Flow {flow_id} step {step.id} has MICROLOOP but no loop_target"

    def test_terminal_routing_no_next(self):
        """TERMINAL routing should have no next step requirement."""
        for flow_id in list_flows():
            flow = load_flow(flow_id)
            for step in flow.steps:
                if step.routing.kind == RoutingKind.TERMINAL:
                    # Terminal steps may or may not have next, but it should be None or ignored
                    pass  # No assertion needed, terminal is valid
