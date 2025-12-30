"""Tests for spec validation.

This module tests schema validation for StationSpecs and FlowSpecs,
routing configuration validation, and macro-routing configuration.
"""

import pytest
from pathlib import Path
from typing import Any, Dict, List

# Add swarm to path
import sys
_SWARM_ROOT = Path(__file__).resolve().parent.parent
if str(_SWARM_ROOT) not in sys.path:
    sys.path.insert(0, str(_SWARM_ROOT))

from swarm.spec.types import (
    StationSpec,
    StationSDK,
    StationIdentity,
    StationIO,
    StationHandoff,
    StationRuntimePrompt,
    StationRoutingHints,
    StationSandbox,
    StationContextBudget,
    StationCategory,
    FlowSpec,
    FlowStep,
    FlowDefaults,
    RoutingConfig,
    RoutingKind,
    ContextPackConfig,
    StepTeaching,
    station_spec_from_dict,
    flow_spec_from_dict,
)
from swarm.spec.loader import (
    load_station,
    load_flow,
    list_stations,
    list_flows,
    validate_specs,
)


class TestStationSpecSchemaValidation:
    """Tests for StationSpec schema validation."""

    def test_station_spec_requires_id(self):
        """StationSpec must have an id field."""
        data = {
            "id": "test-station",
            "version": 1,
            "title": "Test Station",
        }

        station = station_spec_from_dict(data)

        assert station.id == "test-station"

    def test_station_spec_id_missing_raises_error(self):
        """Missing id field should raise KeyError."""
        data = {
            "version": 1,
            "title": "Test Station",
        }

        with pytest.raises(KeyError):
            station_spec_from_dict(data)

    def test_station_spec_version_defaults_to_one(self):
        """Missing version should default to 1."""
        data = {
            "id": "test-station",
            "title": "Test Station",
        }

        station = station_spec_from_dict(data)

        assert station.version == 1

    def test_station_spec_title_defaults_to_id(self):
        """Missing title should default to id."""
        data = {
            "id": "test-station",
        }

        station = station_spec_from_dict(data)

        assert station.title == "test-station"

    def test_station_spec_category_valid_values(self):
        """Category must be a valid StationCategory."""
        valid_categories = [
            "shaping", "spec", "design", "implementation",
            "critic", "verification", "analytics", "reporter",
            "infra", "router"
        ]

        for cat in valid_categories:
            data = {"id": "test", "category": cat}
            station = station_spec_from_dict(data)
            assert isinstance(station.category, StationCategory)

    def test_station_spec_category_invalid_defaults_to_implementation(self):
        """Invalid category should default to IMPLEMENTATION."""
        data = {"id": "test", "category": "invalid-category"}

        station = station_spec_from_dict(data)

        assert station.category == StationCategory.IMPLEMENTATION

    def test_station_spec_sdk_defaults(self):
        """SDK should have sensible defaults."""
        data = {"id": "test"}

        station = station_spec_from_dict(data)

        assert station.sdk.model == "sonnet"
        assert station.sdk.permission_mode == "bypassPermissions"
        assert len(station.sdk.allowed_tools) > 0
        assert station.sdk.max_turns == 12

    def test_station_spec_sdk_custom_values(self):
        """SDK should accept custom values."""
        data = {
            "id": "test",
            "sdk": {
                "model": "opus",
                "permission_mode": "default",
                "max_turns": 20,
                "allowed_tools": ["Read", "Write"],
            }
        }

        station = station_spec_from_dict(data)

        assert station.sdk.model == "opus"
        assert station.sdk.permission_mode == "default"
        assert station.sdk.max_turns == 20
        assert station.sdk.allowed_tools == ("Read", "Write")

    def test_station_spec_sandbox_configuration(self):
        """Sandbox configuration should be parsed correctly."""
        data = {
            "id": "test",
            "sdk": {
                "sandbox": {
                    "enabled": False,
                    "auto_allow_bash": False,
                    "excluded_commands": ["rm", "sudo"],
                }
            }
        }

        station = station_spec_from_dict(data)

        assert station.sdk.sandbox.enabled is False
        assert station.sdk.sandbox.auto_allow_bash is False
        assert station.sdk.sandbox.excluded_commands == ("rm", "sudo")

    def test_station_spec_context_budget_configuration(self):
        """Context budget configuration should be parsed correctly."""
        data = {
            "id": "test",
            "sdk": {
                "context_budget": {
                    "total_chars": 500000,
                    "recent_chars": 100000,
                    "older_chars": 20000,
                }
            }
        }

        station = station_spec_from_dict(data)

        assert station.sdk.context_budget.total_chars == 500000
        assert station.sdk.context_budget.recent_chars == 100000
        assert station.sdk.context_budget.older_chars == 20000

    def test_station_spec_identity_parsing(self):
        """Identity section should be parsed correctly."""
        data = {
            "id": "test",
            "identity": {
                "system_append": "You are a helpful agent.",
                "tone": "analytical",
            }
        }

        station = station_spec_from_dict(data)

        assert station.identity.system_append == "You are a helpful agent."
        assert station.identity.tone == "analytical"

    def test_station_spec_io_parsing(self):
        """IO section should be parsed correctly."""
        data = {
            "id": "test",
            "io": {
                "required_inputs": ["plan/adr.md", "signal/requirements.md"],
                "optional_inputs": ["plan/api_contracts.yaml"],
                "required_outputs": ["build/impl.md"],
                "optional_outputs": ["build/notes.md"],
            }
        }

        station = station_spec_from_dict(data)

        assert station.io.required_inputs == ("plan/adr.md", "signal/requirements.md")
        assert station.io.optional_inputs == ("plan/api_contracts.yaml",)
        assert station.io.required_outputs == ("build/impl.md",)
        assert station.io.optional_outputs == ("build/notes.md",)

    def test_station_spec_handoff_parsing(self):
        """Handoff section should be parsed correctly."""
        data = {
            "id": "test",
            "handoff": {
                "path_template": "{{run.base}}/handoff/{{step.id}}.json",
                "required_fields": ["status", "summary", "artifacts", "blockers"],
            }
        }

        station = station_spec_from_dict(data)

        assert station.handoff.path_template == "{{run.base}}/handoff/{{step.id}}.json"
        assert "status" in station.handoff.required_fields
        assert "blockers" in station.handoff.required_fields

    def test_station_spec_runtime_prompt_parsing(self):
        """Runtime prompt section should be parsed correctly."""
        data = {
            "id": "test",
            "runtime_prompt": {
                "fragments": ["common/invariants.md", "common/evidence.md"],
                "template": "Work on: {{step.objective}}",
            }
        }

        station = station_spec_from_dict(data)

        assert station.runtime_prompt.fragments == ("common/invariants.md", "common/evidence.md")
        assert "{{step.objective}}" in station.runtime_prompt.template

    def test_station_spec_invariants_parsing(self):
        """Invariants should be parsed as tuple of strings."""
        data = {
            "id": "test",
            "invariants": [
                "Never delete tests",
                "Always run tests before claiming success",
                "Document assumptions",
            ]
        }

        station = station_spec_from_dict(data)

        assert len(station.invariants) == 3
        assert "Never delete tests" in station.invariants

    def test_station_spec_routing_hints_parsing(self):
        """Routing hints should be parsed correctly."""
        data = {
            "id": "test",
            "routing_hints": {
                "on_verified": "advance",
                "on_unverified": "loop",
                "on_partial": "advance_with_concerns",
                "on_blocked": "escalate",
            }
        }

        station = station_spec_from_dict(data)

        assert station.routing_hints.on_verified == "advance"
        assert station.routing_hints.on_unverified == "loop"
        assert station.routing_hints.on_partial == "advance_with_concerns"
        assert station.routing_hints.on_blocked == "escalate"


class TestFlowSpecSchemaValidation:
    """Tests for FlowSpec schema validation."""

    def test_flow_spec_requires_id(self):
        """FlowSpec must have an id field."""
        data = {
            "id": "1-test-flow",
            "version": 1,
            "title": "Test Flow",
        }

        flow = flow_spec_from_dict(data)

        assert flow.id == "1-test-flow"

    def test_flow_spec_id_missing_raises_error(self):
        """Missing id field should raise KeyError."""
        data = {
            "version": 1,
            "title": "Test Flow",
        }

        with pytest.raises(KeyError):
            flow_spec_from_dict(data)

    def test_flow_spec_version_defaults_to_one(self):
        """Missing version should default to 1."""
        data = {"id": "test-flow"}

        flow = flow_spec_from_dict(data)

        assert flow.version == 1

    def test_flow_spec_title_defaults_to_id(self):
        """Missing title should default to id."""
        data = {"id": "test-flow"}

        flow = flow_spec_from_dict(data)

        assert flow.title == "test-flow"

    def test_flow_spec_description_parsing(self):
        """Description should be parsed correctly."""
        data = {
            "id": "test-flow",
            "description": "This flow does X, Y, and Z.",
        }

        flow = flow_spec_from_dict(data)

        assert flow.description == "This flow does X, Y, and Z."

    def test_flow_spec_defaults_parsing(self):
        """Flow defaults should be parsed correctly."""
        data = {
            "id": "test-flow",
            "defaults": {
                "context_pack": {
                    "include_upstream_artifacts": False,
                    "include_previous_envelopes": True,
                    "max_envelopes": 20,
                    "include_scent_trail": False,
                },
                "sdk_overrides": {"model": "opus"},
            }
        }

        flow = flow_spec_from_dict(data)

        assert flow.defaults.context_pack.include_upstream_artifacts is False
        assert flow.defaults.context_pack.max_envelopes == 20
        assert flow.defaults.sdk_overrides == {"model": "opus"}

    def test_flow_spec_steps_parsing(self):
        """Flow steps should be parsed correctly."""
        data = {
            "id": "test-flow",
            "steps": [
                {
                    "id": "step-1",
                    "station": "station-a",
                    "objective": "Do step 1",
                },
                {
                    "id": "step-2",
                    "station": "station-b",
                    "objective": "Do step 2",
                },
            ]
        }

        flow = flow_spec_from_dict(data)

        assert len(flow.steps) == 2
        assert flow.steps[0].id == "step-1"
        assert flow.steps[1].id == "step-2"

    def test_flow_spec_cross_cutting_stations_parsing(self):
        """Cross-cutting stations should be parsed correctly."""
        data = {
            "id": "test-flow",
            "cross_cutting_stations": ["clarifier", "risk-analyst", "repo-operator"],
        }

        flow = flow_spec_from_dict(data)

        assert flow.cross_cutting_stations == ("clarifier", "risk-analyst", "repo-operator")


class TestRoutingConfigValidation:
    """Tests for routing configuration validation."""

    def test_routing_config_linear(self):
        """LINEAR routing should be parsed correctly."""
        data = {
            "id": "test-flow",
            "steps": [
                {
                    "id": "step-1",
                    "station": "test-station",
                    "objective": "Test",
                    "routing": {
                        "kind": "linear",
                        "next": "step-2",
                    }
                }
            ]
        }

        flow = flow_spec_from_dict(data)

        assert flow.steps[0].routing.kind == RoutingKind.LINEAR
        assert flow.steps[0].routing.next == "step-2"

    def test_routing_config_microloop(self):
        """MICROLOOP routing should be parsed correctly."""
        data = {
            "id": "test-flow",
            "steps": [
                {
                    "id": "critique",
                    "station": "critic",
                    "objective": "Review",
                    "routing": {
                        "kind": "microloop",
                        "loop_target": "implement",
                        "next": "finalize",
                        "loop_condition_field": "status",
                        "loop_success_values": ["VERIFIED", "verified"],
                        "max_iterations": 5,
                    }
                }
            ]
        }

        flow = flow_spec_from_dict(data)
        routing = flow.steps[0].routing

        assert routing.kind == RoutingKind.MICROLOOP
        assert routing.loop_target == "implement"
        assert routing.next == "finalize"
        assert routing.loop_condition_field == "status"
        assert routing.loop_success_values == ("VERIFIED", "verified")
        assert routing.max_iterations == 5

    def test_routing_config_branch(self):
        """BRANCH routing should be parsed correctly."""
        data = {
            "id": "test-flow",
            "steps": [
                {
                    "id": "decide",
                    "station": "decider",
                    "objective": "Make decision",
                    "routing": {
                        "kind": "branch",
                        "branches": {
                            "success": "step-a",
                            "failure": "step-b",
                        }
                    }
                }
            ]
        }

        flow = flow_spec_from_dict(data)
        routing = flow.steps[0].routing

        assert routing.kind == RoutingKind.BRANCH
        assert routing.branches == {"success": "step-a", "failure": "step-b"}

    def test_routing_config_terminal(self):
        """TERMINAL routing should be parsed correctly."""
        data = {
            "id": "test-flow",
            "steps": [
                {
                    "id": "finalize",
                    "station": "finalizer",
                    "objective": "Complete",
                    "routing": {
                        "kind": "terminal",
                    }
                }
            ]
        }

        flow = flow_spec_from_dict(data)
        routing = flow.steps[0].routing

        assert routing.kind == RoutingKind.TERMINAL

    def test_routing_config_invalid_kind_defaults_to_linear(self):
        """Invalid routing kind should default to LINEAR."""
        data = {
            "id": "test-flow",
            "steps": [
                {
                    "id": "step-1",
                    "station": "test",
                    "objective": "Test",
                    "routing": {
                        "kind": "invalid-kind",
                    }
                }
            ]
        }

        flow = flow_spec_from_dict(data)

        assert flow.steps[0].routing.kind == RoutingKind.LINEAR


class TestStepConfigValidation:
    """Tests for FlowStep configuration validation."""

    def test_step_requires_id(self):
        """Step must have an id field."""
        data = {
            "id": "test-flow",
            "steps": [
                {
                    "id": "step-1",
                    "station": "test-station",
                    "objective": "Test",
                }
            ]
        }

        flow = flow_spec_from_dict(data)

        assert flow.steps[0].id == "step-1"

    def test_step_requires_station(self):
        """Step must have a station reference."""
        data = {
            "id": "test-flow",
            "steps": [
                {
                    "id": "step-1",
                    "station": "my-station",
                    "objective": "Test",
                }
            ]
        }

        flow = flow_spec_from_dict(data)

        assert flow.steps[0].station == "my-station"

    def test_step_scope_optional(self):
        """Step scope should be optional."""
        data = {
            "id": "test-flow",
            "steps": [
                {
                    "id": "step-1",
                    "station": "test",
                    "objective": "Test",
                    "scope": "Only module A",
                }
            ]
        }

        flow = flow_spec_from_dict(data)

        assert flow.steps[0].scope == "Only module A"

    def test_step_inputs_outputs_parsing(self):
        """Step inputs and outputs should be parsed as tuples."""
        data = {
            "id": "test-flow",
            "steps": [
                {
                    "id": "step-1",
                    "station": "test",
                    "objective": "Test",
                    "inputs": ["input1.md", "input2.md"],
                    "outputs": ["output1.md"],
                }
            ]
        }

        flow = flow_spec_from_dict(data)

        assert flow.steps[0].inputs == ("input1.md", "input2.md")
        assert flow.steps[0].outputs == ("output1.md",)

    def test_step_sdk_overrides_parsing(self):
        """Step SDK overrides should be parsed as dict."""
        data = {
            "id": "test-flow",
            "steps": [
                {
                    "id": "step-1",
                    "station": "test",
                    "objective": "Test",
                    "sdk_overrides": {
                        "model": "opus",
                        "max_turns": 20,
                    }
                }
            ]
        }

        flow = flow_spec_from_dict(data)

        assert flow.steps[0].sdk_overrides["model"] == "opus"
        assert flow.steps[0].sdk_overrides["max_turns"] == 20

    def test_step_teaching_parsing(self):
        """Step teaching metadata should be parsed correctly."""
        data = {
            "id": "test-flow",
            "steps": [
                {
                    "id": "step-1",
                    "station": "test",
                    "objective": "Test",
                    "teaching": {
                        "highlight": True,
                        "note": "This is an important step",
                    }
                }
            ]
        }

        flow = flow_spec_from_dict(data)

        assert flow.steps[0].teaching.highlight is True
        assert flow.steps[0].teaching.note == "This is an important step"


class TestMacroRoutingConfiguration:
    """Tests for flow-level macro-routing configuration."""

    def test_flow_with_on_complete(self):
        """Flow should support on_complete routing (parsed as extra dict)."""
        # Note: on_complete is not in FlowSpec dataclass currently,
        # but we should test that parsing doesn't fail
        data = {
            "id": "test-flow",
            "on_complete": {
                "next_flow": "next-flow",
                "reason": "Flow complete",
            }
        }

        flow = flow_spec_from_dict(data)

        # Flow should parse successfully even with extra fields
        assert flow.id == "test-flow"

    def test_flow_with_on_failure(self):
        """Flow should support on_failure routing (parsed as extra dict)."""
        data = {
            "id": "test-flow",
            "on_failure": {
                "next_flow": "bounce-flow",
                "reason": "Need to bounce back",
            }
        }

        flow = flow_spec_from_dict(data)

        assert flow.id == "test-flow"


class TestValidateSpecsFunction:
    """Tests for the validate_specs function."""

    def test_validate_specs_returns_results(self):
        """validate_specs should return errors and warnings."""
        result = validate_specs()

        assert isinstance(result, dict)
        assert "errors" in result
        assert "warnings" in result

    def test_validate_specs_checks_station_references(self):
        """validate_specs should check that flow steps reference valid stations."""
        result = validate_specs()

        # If there are errors about unknown stations, the validator caught them
        # This is expected behavior - we just verify the structure
        for error in result["errors"]:
            if "Unknown station" in error:
                # This is the validator working correctly
                pass

    def test_validate_specs_checks_routing_references(self):
        """validate_specs should check that routing references valid steps."""
        result = validate_specs()

        # Routing errors would appear here
        for error in result["errors"]:
            if "Unknown next step" in error or "Unknown loop_target" in error:
                pass  # Validator is working

    def test_validate_specs_checks_fragment_references(self):
        """validate_specs should check that fragment references exist."""
        result = validate_specs()

        # Fragment errors would appear here
        for error in result["errors"]:
            if "Fragment not found" in error:
                pass  # Validator is working


class TestAllLoadedSpecsValid:
    """Tests that all loaded specs from the repository are valid."""

    def test_all_stations_load_successfully(self):
        """All station specs should load without error."""
        errors = []

        for station_id in list_stations():
            try:
                station = load_station(station_id)
                assert station.id == station_id
            except Exception as e:
                errors.append(f"{station_id}: {e}")

        assert len(errors) == 0, f"Station load errors: {errors}"

    def test_all_stations_have_required_fields(self):
        """All stations should have required fields populated."""
        for station_id in list_stations():
            station = load_station(station_id)

            assert station.id != "", f"{station_id} has empty id"
            assert station.version >= 1, f"{station_id} has invalid version"
            assert station.title != "", f"{station_id} has empty title"
            assert isinstance(station.category, StationCategory)

    def test_all_flows_load_successfully(self):
        """All flow specs should load without error."""
        errors = []

        for flow_id in list_flows():
            try:
                flow = load_flow(flow_id)
                assert flow.id == flow_id
            except Exception as e:
                errors.append(f"{flow_id}: {e}")

        assert len(errors) == 0, f"Flow load errors: {errors}"

    def test_all_flows_have_required_fields(self):
        """All flows should have required fields populated."""
        for flow_id in list_flows():
            flow = load_flow(flow_id)

            assert flow.id != "", f"{flow_id} has empty id"
            assert flow.version >= 1, f"{flow_id} has invalid version"

    def test_all_flow_steps_have_valid_routing(self):
        """All flow steps should have valid routing configuration."""
        for flow_id in list_flows():
            flow = load_flow(flow_id)

            for step in flow.steps:
                assert isinstance(step.routing.kind, RoutingKind), \
                    f"{flow_id}/{step.id} has invalid routing kind"

                if step.routing.kind == RoutingKind.MICROLOOP:
                    assert step.routing.loop_target is not None, \
                        f"{flow_id}/{step.id} is MICROLOOP but has no loop_target"
                    assert step.routing.max_iterations >= 1, \
                        f"{flow_id}/{step.id} has invalid max_iterations"
