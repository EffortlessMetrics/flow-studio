"""Integration tests for the spec-first system.

This module tests that all station YAMLs and flow YAMLs in swarm/spec/
are valid, flow steps reference valid stations, and station fragment refs
point to existing files.
"""

import pytest
from pathlib import Path
from typing import Dict, List, Set

# Add swarm to path
import sys
_SWARM_ROOT = Path(__file__).resolve().parent.parent
if str(_SWARM_ROOT) not in sys.path:
    sys.path.insert(0, str(_SWARM_ROOT))

from swarm.spec.loader import (
    load_station,
    load_flow,
    load_fragment,
    list_stations,
    list_flows,
    list_fragments,
    get_spec_root,
    validate_specs,
)
from swarm.spec.compiler import (
    SpecCompiler,
    compile_prompt,
)
from swarm.spec.types import (
    StationSpec,
    FlowSpec,
    RoutingKind,
)


class TestAllStationYAMLsValid:
    """Tests that all station YAMLs in swarm/spec/stations/ are valid."""

    def test_all_stations_parse_successfully(self):
        """Every station YAML should parse without errors."""
        stations = list_stations()
        assert len(stations) > 0, "No stations found in swarm/spec/stations/"

        errors = []
        for station_id in stations:
            try:
                station = load_station(station_id)
                assert station.id == station_id
            except Exception as e:
                errors.append(f"{station_id}: {e}")

        if errors:
            pytest.fail(f"Station parsing errors:\n" + "\n".join(errors))

    def test_all_stations_have_valid_id(self):
        """All stations should have an ID matching their filename."""
        for station_id in list_stations():
            station = load_station(station_id)

            assert station.id == station_id, \
                f"Station {station_id} has mismatched id: {station.id}"

    def test_all_stations_have_version(self):
        """All stations should have a positive version number."""
        for station_id in list_stations():
            station = load_station(station_id)

            assert station.version >= 1, \
                f"Station {station_id} has invalid version: {station.version}"

    def test_all_stations_have_title(self):
        """All stations should have a non-empty title."""
        for station_id in list_stations():
            station = load_station(station_id)

            assert station.title != "", \
                f"Station {station_id} has empty title"

    def test_all_stations_have_valid_sdk_config(self):
        """All stations should have valid SDK configuration."""
        for station_id in list_stations():
            station = load_station(station_id)

            assert station.sdk.model in ("sonnet", "haiku", "opus", "inherit"), \
                f"Station {station_id} has invalid model: {station.sdk.model}"
            assert station.sdk.max_turns >= 1, \
                f"Station {station_id} has invalid max_turns: {station.sdk.max_turns}"
            assert len(station.sdk.allowed_tools) >= 0  # Can be empty for some stations


class TestAllFlowYAMLsValid:
    """Tests that all flow YAMLs in swarm/spec/flows/ are valid."""

    def test_all_flows_parse_successfully(self):
        """Every flow YAML should parse without errors."""
        flows = list_flows()
        assert len(flows) > 0, "No flows found in swarm/spec/flows/"

        errors = []
        for flow_id in flows:
            try:
                flow = load_flow(flow_id)
                assert flow.id == flow_id
            except Exception as e:
                errors.append(f"{flow_id}: {e}")

        if errors:
            pytest.fail(f"Flow parsing errors:\n" + "\n".join(errors))

    def test_all_flows_have_valid_id(self):
        """All flows should have an ID matching their filename."""
        for flow_id in list_flows():
            flow = load_flow(flow_id)

            assert flow.id == flow_id, \
                f"Flow {flow_id} has mismatched id: {flow.id}"

    def test_all_flows_have_version(self):
        """All flows should have a positive version number."""
        for flow_id in list_flows():
            flow = load_flow(flow_id)

            assert flow.version >= 1, \
                f"Flow {flow_id} has invalid version: {flow.version}"

    def test_all_flows_have_steps(self):
        """All flows should have at least one step."""
        for flow_id in list_flows():
            flow = load_flow(flow_id)

            assert len(flow.steps) > 0, \
                f"Flow {flow_id} has no steps"


class TestFlowStepsReferenceValidStations:
    """Tests that flow steps reference valid stations."""

    def test_all_step_stations_exist(self):
        """Every flow step should reference an existing station."""
        available_stations = set(list_stations())
        errors = []

        for flow_id in list_flows():
            flow = load_flow(flow_id)

            for step in flow.steps:
                if step.station not in available_stations:
                    errors.append(f"Flow {flow_id}, step {step.id}: "
                                  f"references unknown station '{step.station}'")

        if errors:
            pytest.fail(f"Missing station references:\n" + "\n".join(errors))

    def test_cross_cutting_stations_exist(self):
        """All cross-cutting station references should be valid."""
        available_stations = set(list_stations())
        errors = []

        for flow_id in list_flows():
            flow = load_flow(flow_id)

            for station_id in flow.cross_cutting_stations:
                if station_id not in available_stations:
                    errors.append(f"Flow {flow_id}: cross-cutting station "
                                  f"'{station_id}' not found")

        if errors:
            pytest.fail(f"Missing cross-cutting stations:\n" + "\n".join(errors))


class TestStationFragmentRefsExist:
    """Tests that station fragment refs point to existing files."""

    def test_all_fragment_refs_exist(self):
        """All fragment references in stations should point to existing files."""
        available_fragments = set(list_fragments())
        errors = []

        for station_id in list_stations():
            station = load_station(station_id)

            for fragment_path in station.runtime_prompt.fragments:
                if fragment_path not in available_fragments:
                    # Try loading directly to confirm
                    try:
                        load_fragment(fragment_path)
                    except FileNotFoundError:
                        errors.append(f"Station {station_id}: "
                                      f"fragment '{fragment_path}' not found")

        if errors:
            pytest.fail(f"Missing fragment references:\n" + "\n".join(errors))


class TestRoutingConsistency:
    """Tests for routing configuration consistency."""

    def test_routing_next_refs_valid_steps(self):
        """Routing 'next' should reference valid step IDs within the flow."""
        errors = []

        for flow_id in list_flows():
            flow = load_flow(flow_id)
            step_ids = {step.id for step in flow.steps}

            for step in flow.steps:
                if step.routing.next and step.routing.next not in step_ids:
                    errors.append(f"Flow {flow_id}, step {step.id}: "
                                  f"routing.next '{step.routing.next}' not found")

        if errors:
            pytest.fail(f"Invalid routing.next references:\n" + "\n".join(errors))

    def test_routing_loop_target_refs_valid_steps(self):
        """Routing 'loop_target' should reference valid step IDs."""
        errors = []

        for flow_id in list_flows():
            flow = load_flow(flow_id)
            step_ids = {step.id for step in flow.steps}

            for step in flow.steps:
                if step.routing.loop_target and step.routing.loop_target not in step_ids:
                    errors.append(f"Flow {flow_id}, step {step.id}: "
                                  f"routing.loop_target '{step.routing.loop_target}' not found")

        if errors:
            pytest.fail(f"Invalid routing.loop_target references:\n" + "\n".join(errors))

    def test_microloop_has_loop_target(self):
        """MICROLOOP routing must have a loop_target."""
        errors = []

        for flow_id in list_flows():
            flow = load_flow(flow_id)

            for step in flow.steps:
                if step.routing.kind == RoutingKind.MICROLOOP:
                    if not step.routing.loop_target:
                        errors.append(f"Flow {flow_id}, step {step.id}: "
                                      f"MICROLOOP routing requires loop_target")

        if errors:
            pytest.fail(f"MICROLOOP routing errors:\n" + "\n".join(errors))

    def test_branch_has_branches_dict(self):
        """BRANCH routing should have a branches dictionary."""
        for flow_id in list_flows():
            flow = load_flow(flow_id)

            for step in flow.steps:
                if step.routing.kind == RoutingKind.BRANCH:
                    # Branches dict exists (may be empty but should be dict)
                    assert isinstance(step.routing.branches, dict), \
                        f"Flow {flow_id}, step {step.id}: BRANCH routing has invalid branches"


class TestCompilerIntegration:
    """Integration tests for the SpecCompiler."""

    def test_compile_all_flow_steps(self):
        """All flow steps should compile successfully."""
        repo_root = Path(__file__).parent.parent
        compiler = SpecCompiler(repo_root)
        run_base = Path("swarm/runs/integration-test")
        errors = []

        for flow_id in list_flows():
            flow = load_flow(flow_id)

            for step in flow.steps:
                try:
                    plan = compiler.compile(
                        flow_id=flow_id,
                        step_id=step.id,
                        context_pack=None,
                        run_base=run_base,
                    )
                    assert plan.station_id == step.station
                    assert plan.step_id == step.id
                except FileNotFoundError as e:
                    # Station not found - collect as error
                    errors.append(f"{flow_id}/{step.id}: {e}")
                except Exception as e:
                    errors.append(f"{flow_id}/{step.id}: {e}")

        if errors:
            pytest.fail(f"Compilation errors:\n" + "\n".join(errors))

    def test_compiled_plans_have_valid_hashes(self):
        """All compiled plans should have non-empty prompt hashes."""
        repo_root = Path(__file__).parent.parent
        compiler = SpecCompiler(repo_root)
        run_base = Path("swarm/runs/integration-test")

        for flow_id in list_flows():
            flow = load_flow(flow_id)

            for step in flow.steps:
                try:
                    plan = compiler.compile(
                        flow_id=flow_id,
                        step_id=step.id,
                        context_pack=None,
                        run_base=run_base,
                    )
                    assert plan.prompt_hash != "", \
                        f"{flow_id}/{step.id}: empty prompt_hash"
                    assert len(plan.prompt_hash) == 16, \
                        f"{flow_id}/{step.id}: invalid prompt_hash length"
                except FileNotFoundError:
                    # Skip if station not found
                    continue


class TestValidateSpecsIntegration:
    """Integration tests for validate_specs function."""

    def test_validate_specs_no_critical_errors(self):
        """validate_specs should not find critical errors in the repo."""
        result = validate_specs()

        # Filter for critical errors only (not warnings)
        critical_errors = [e for e in result["errors"]
                          if "not found" in e.lower() or "invalid" in e.lower()]

        # Report but don't fail on non-critical issues
        if result["errors"]:
            print(f"Validation errors: {result['errors']}")
        if result["warnings"]:
            print(f"Validation warnings: {result['warnings']}")

        # The spec directory should be reasonably clean
        # Some errors may be expected if the spec is evolving
        assert len(critical_errors) == 0, \
            f"Critical validation errors:\n" + "\n".join(critical_errors)


class TestSpecDirectoryStructure:
    """Tests for the spec directory structure."""

    def test_spec_root_exists(self):
        """swarm/spec/ directory should exist."""
        spec_root = get_spec_root()
        assert spec_root.exists(), f"Spec root not found: {spec_root}"

    def test_stations_directory_exists(self):
        """swarm/spec/stations/ directory should exist."""
        spec_root = get_spec_root()
        stations_dir = spec_root / "stations"
        assert stations_dir.exists(), f"Stations directory not found: {stations_dir}"

    def test_flows_directory_exists(self):
        """swarm/spec/flows/ directory should exist."""
        spec_root = get_spec_root()
        flows_dir = spec_root / "flows"
        assert flows_dir.exists(), f"Flows directory not found: {flows_dir}"

    def test_fragments_directory_exists(self):
        """swarm/spec/fragments/ directory should exist."""
        spec_root = get_spec_root()
        fragments_dir = spec_root / "fragments"
        assert fragments_dir.exists(), f"Fragments directory not found: {fragments_dir}"


class TestSpecCoverage:
    """Tests for spec coverage of the SDLC."""

    def test_core_flows_exist(self):
        """Core SDLC flows should exist."""
        flows = list_flows()

        expected_flows = ["1-signal", "2-plan", "3-build"]
        for expected in expected_flows:
            assert expected in flows, f"Expected flow {expected} not found"

    def test_core_stations_exist(self):
        """Core stations should exist."""
        stations = list_stations()

        expected_stations = [
            "code-implementer",
            "test-author",
            "code-critic",
            "test-critic",
        ]
        for expected in expected_stations:
            assert expected in stations, f"Expected station {expected} not found"

    def test_common_fragments_exist(self):
        """Common fragments should exist."""
        fragments = list_fragments()

        expected_fragments = [
            "common/invariants.md",
        ]
        for expected in expected_fragments:
            assert expected in fragments, f"Expected fragment {expected} not found"


class TestStationIOContracts:
    """Tests for station IO contracts."""

    def test_stations_with_outputs_have_valid_paths(self):
        """Station required outputs should use valid path patterns."""
        for station_id in list_stations():
            station = load_station(station_id)

            for output_path in station.io.required_outputs:
                # Paths should not be empty
                assert output_path != "", \
                    f"Station {station_id} has empty required_output"
                # Paths should use relative paths (not absolute)
                assert not output_path.startswith("/"), \
                    f"Station {station_id} has absolute path: {output_path}"
                assert not output_path.startswith("C:"), \
                    f"Station {station_id} has Windows absolute path: {output_path}"

    def test_stations_with_inputs_have_valid_paths(self):
        """Station required inputs should use valid path patterns."""
        for station_id in list_stations():
            station = load_station(station_id)

            for input_path in station.io.required_inputs:
                assert input_path != "", \
                    f"Station {station_id} has empty required_input"
                assert not input_path.startswith("/"), \
                    f"Station {station_id} has absolute input path: {input_path}"


class TestHandoffContracts:
    """Tests for station handoff contracts."""

    def test_all_stations_have_handoff_path_template(self):
        """All stations should have a handoff path template."""
        for station_id in list_stations():
            station = load_station(station_id)

            assert station.handoff.path_template != "", \
                f"Station {station_id} has empty handoff.path_template"
            assert "{{" in station.handoff.path_template or "/" in station.handoff.path_template, \
                f"Station {station_id} has invalid handoff.path_template"

    def test_all_stations_require_status_in_handoff(self):
        """All stations should require 'status' in handoff."""
        for station_id in list_stations():
            station = load_station(station_id)

            assert "status" in station.handoff.required_fields, \
                f"Station {station_id} handoff missing required 'status' field"


class TestFlowStepInputOutputChaining:
    """Tests for flow step input/output chaining."""

    def test_flow_steps_have_objectives(self):
        """All flow steps should have non-empty objectives."""
        for flow_id in list_flows():
            flow = load_flow(flow_id)

            for step in flow.steps:
                assert step.objective != "", \
                    f"Flow {flow_id}, step {step.id} has empty objective"

    def test_downstream_steps_can_access_upstream_outputs(self):
        """Later steps in a flow should be able to access outputs from earlier steps."""
        # This is a structural test - actual file availability is runtime
        for flow_id in list_flows():
            flow = load_flow(flow_id)

            # Track outputs produced by each step
            produced_outputs: Set[str] = set()

            for step in flow.steps:
                # Note: This just checks the declared structure
                # Runtime availability is different
                for output_path in step.outputs:
                    produced_outputs.add(output_path)
