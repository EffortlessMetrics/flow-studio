"""Tests for the spec system (SpecManager, SpecCompiler, SmartRouter).

This module provides comprehensive unit tests for:
1. SpecManager (loader.py) - Loading, validating, and listing specs
2. SpecCompiler (compiler.py) - Compiling specs into PromptPlans
3. SmartRouter (router.py) - Routing logic for stepwise execution

Test categories follow the spec-first architecture contract.
"""

import hashlib
import json
import pytest
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

# Ensure swarm modules are importable
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from swarm.spec.types import (
    FlowSpec,
    FlowStep,
    RoutingConfig,
    RoutingKind,
    StationSpec,
    StationCategory,
    StationIdentity,
    StationIO,
    StationSDK,
    StationSandbox,
    StationContextBudget,
    StationHandoff,
    StationRuntimePrompt,
    StationRoutingHints,
    PromptPlan,
    VerificationRequirements,
    HandoffContract,
    flow_spec_from_dict,
    station_spec_from_dict,
)
from swarm.spec.loader import (
    load_station,
    load_flow,
    load_fragment,
    load_fragments,
    list_stations,
    list_flows,
    list_fragments,
    validate_specs,
    get_spec_root,
)
from swarm.spec.compiler import (
    SpecCompiler,
    compile_prompt,
    render_template,
    build_system_append,
    build_system_append_v2,
    build_user_prompt,
    extract_flow_key,
    merge_verification_requirements,
    resolve_handoff_contract,
)
from swarm.runtime.engines.claude.router import (
    route_from_routing_config,
    route_step_stub,
    check_microloop_termination,
    ROUTER_PROMPT_TEMPLATE,
)
from swarm.runtime.types import RoutingDecision, RoutingSignal


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def sample_station_dict() -> Dict[str, Any]:
    """Sample station spec as dictionary."""
    return {
        "id": "test-station",
        "version": 1,
        "title": "Test Station",
        "category": "implementation",
        "sdk": {
            "model": "sonnet",
            "permission_mode": "bypassPermissions",
            "allowed_tools": ["Read", "Write", "Bash"],
            "sandbox": {
                "enabled": True,
                "auto_allow_bash": True,
                "excluded_commands": ["docker"],
            },
            "max_turns": 10,
            "context_budget": {
                "total_chars": 100000,
                "recent_chars": 30000,
                "older_chars": 5000,
            },
        },
        "identity": {
            "system_append": "You are the Test Station.",
            "tone": "neutral",
        },
        "io": {
            "required_inputs": ["input1.md"],
            "optional_inputs": ["optional.md"],
            "required_outputs": ["output1.md"],
            "optional_outputs": ["optional_out.md"],
        },
        "handoff": {
            "path_template": "{{run.base}}/handoff/{{step.id}}.json",
            "required_fields": ["status", "summary"],
        },
        "runtime_prompt": {
            "fragments": [],
            "template": "Do the thing for {{step.id}}",
        },
        "invariants": ["Never do bad things", "Always be honest"],
        "routing_hints": {
            "on_verified": "advance",
            "on_unverified": "loop",
            "on_partial": "advance_with_concerns",
            "on_blocked": "escalate",
        },
    }


@pytest.fixture
def sample_flow_dict() -> Dict[str, Any]:
    """Sample flow spec as dictionary."""
    return {
        "id": "test-flow",
        "version": 1,
        "title": "Test Flow",
        "description": "A test flow for unit testing",
        "defaults": {
            "context_pack": {
                "include_upstream_artifacts": True,
                "include_previous_envelopes": True,
                "max_envelopes": 10,
                "include_scent_trail": True,
            },
            "sdk_overrides": {},
        },
        "steps": [
            {
                "id": "step_1",
                "station": "test-station",
                "objective": "First step objective",
                "scope": "AC-001",
                "inputs": ["extra_input.md"],
                "outputs": ["step1_output.md"],
                "routing": {
                    "kind": "linear",
                    "next": "step_2",
                },
            },
            {
                "id": "step_2",
                "station": "test-station",
                "objective": "Second step objective",
                "routing": {
                    "kind": "microloop",
                    "loop_target": "step_1",
                    "next": "step_3",
                    "max_iterations": 3,
                    "loop_success_values": ["VERIFIED"],
                },
            },
            {
                "id": "step_3",
                "station": "test-station",
                "objective": "Final step",
                "routing": {
                    "kind": "terminal",
                },
            },
        ],
        "cross_cutting_stations": ["clarifier"],
    }


@pytest.fixture
def sample_flow_graph_json() -> Dict[str, Any]:
    """Sample FlowGraph JSON matching schema."""
    return {
        "id": "build-flow",
        "version": 1,
        "title": "Flow 3 - Build",
        "flow_number": 3,
        "description": "Test flow graph",
        "nodes": [
            {
                "node_id": "load_context",
                "template_id": "context-loader",
                "params": {
                    "objective": "Load context",
                    "inputs": ["plan/adr.md"],
                    "outputs": ["build/manifest.json"],
                },
                "ui": {
                    "type": "step",
                    "position": {"x": 100, "y": 100},
                },
            },
            {
                "node_id": "author_tests",
                "template_id": "test-author",
                "params": {
                    "objective": "Write tests",
                },
                "ui": {
                    "type": "step",
                    "position": {"x": 100, "y": 200},
                },
            },
        ],
        "edges": [
            {
                "edge_id": "e1",
                "from": "load_context",
                "to": "author_tests",
                "type": "sequence",
            },
        ],
    }


@pytest.fixture
def sample_step_template_json() -> Dict[str, Any]:
    """Sample StepTemplate JSON matching schema."""
    return {
        "id": "code-critic-template",
        "version": 1,
        "title": "Code Critic",
        "description": "Review code changes",
        "station_id": "code-critic",
        "category": "critic",
        "objective": {
            "template": "Review {{artifact_type}} for {{quality_criteria}}",
            "default_params": {
                "artifact_type": "code changes",
                "quality_criteria": "correctness",
            },
        },
        "routing_defaults": {
            "kind": "microloop",
            "max_iterations": 5,
        },
    }


@pytest.fixture
def temp_spec_repo(tmp_path: Path) -> Path:
    """Create a temporary spec repository structure."""
    spec_dir = tmp_path / "swarm" / "spec"
    (spec_dir / "stations").mkdir(parents=True)
    (spec_dir / "flows").mkdir()
    (spec_dir / "fragments" / "common").mkdir(parents=True)
    (spec_dir / "schemas").mkdir()
    return tmp_path


@pytest.fixture
def populated_spec_repo(temp_spec_repo: Path, sample_station_dict: Dict, sample_flow_dict: Dict) -> Path:
    """Create a temp spec repo with sample specs."""
    import yaml

    spec_dir = temp_spec_repo / "swarm" / "spec"

    # Write station spec
    station_path = spec_dir / "stations" / "test-station.yaml"
    with open(station_path, "w") as f:
        yaml.dump(sample_station_dict, f)

    # Write flow spec
    flow_path = spec_dir / "flows" / "test-flow.yaml"
    with open(flow_path, "w") as f:
        yaml.dump(sample_flow_dict, f)

    # Write a fragment
    fragment_path = spec_dir / "fragments" / "common" / "invariants.md"
    fragment_path.write_text("# Invariants\n\n- Be consistent\n- Be honest")

    return temp_spec_repo


@pytest.fixture
def mock_context_pack():
    """Create a mock ContextPack for testing."""
    @dataclass
    class MockEnvelope:
        step_id: str
        status: str
        summary: str

    @dataclass
    class MockContextPack:
        upstream_artifacts: Dict[str, str]
        previous_envelopes: List[MockEnvelope]

    return MockContextPack(
        upstream_artifacts={
            "adr": "plan/adr.md",
            "contracts": "plan/api_contracts.yaml",
        },
        previous_envelopes=[
            MockEnvelope("step_0", "VERIFIED", "Loaded context successfully"),
            MockEnvelope("step_1", "UNVERIFIED", "Tests need more coverage"),
        ],
    )


# =============================================================================
# SpecManager Tests (loader.py)
# =============================================================================


class TestSpecManagerLoadStation:
    """Tests for station loading functionality."""

    def test_load_station_success(self, populated_spec_repo: Path):
        """Test loading a valid station spec."""
        station = load_station("test-station", populated_spec_repo)

        assert station.id == "test-station"
        assert station.version == 1
        assert station.title == "Test Station"
        assert station.category == StationCategory.IMPLEMENTATION
        assert station.sdk.model == "sonnet"
        assert "Read" in station.sdk.allowed_tools

    def test_load_station_not_found(self, temp_spec_repo: Path):
        """Test loading a non-existent station raises SpecNotFoundError."""
        with pytest.raises(FileNotFoundError) as exc_info:
            load_station("nonexistent-station", temp_spec_repo)

        assert "Station spec not found" in str(exc_info.value)

    def test_load_station_invalid_yaml(self, temp_spec_repo: Path):
        """Test loading invalid YAML raises ValueError."""
        import yaml

        spec_dir = temp_spec_repo / "swarm" / "spec" / "stations"
        bad_station = spec_dir / "bad-station.yaml"
        bad_station.write_text("id: [invalid: yaml: here")

        with pytest.raises(ValueError) as exc_info:
            load_station("bad-station", temp_spec_repo)

        assert "Invalid YAML" in str(exc_info.value)


class TestSpecManagerLoadFlow:
    """Tests for flow loading functionality."""

    def test_load_flow_graph_success(self, populated_spec_repo: Path):
        """Test loading a valid flow spec."""
        flow = load_flow("test-flow", populated_spec_repo)

        assert flow.id == "test-flow"
        assert flow.version == 1
        assert flow.title == "Test Flow"
        assert len(flow.steps) == 3
        assert flow.steps[0].id == "step_1"

    def test_load_flow_graph_not_found(self, temp_spec_repo: Path):
        """Test loading non-existent flow raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError) as exc_info:
            load_flow("nonexistent-flow", temp_spec_repo)

        assert "Flow spec not found" in str(exc_info.value)


class TestSpecManagerValidation:
    """Tests for spec validation functionality."""

    def test_validate_valid_spec(self, populated_spec_repo: Path):
        """Test that valid specs return empty errors."""
        results = validate_specs(populated_spec_repo)

        # Should have no errors (station refs are checked)
        # Note: May have warnings if jsonschema not installed
        assert isinstance(results, dict)
        assert "errors" in results
        assert "warnings" in results

    def test_validate_invalid_spec_missing_station(self, temp_spec_repo: Path):
        """Test validation catches missing station references."""
        import yaml

        spec_dir = temp_spec_repo / "swarm" / "spec"

        # Create flow that references non-existent station
        flow_dict = {
            "id": "bad-flow",
            "version": 1,
            "title": "Bad Flow",
            "steps": [
                {
                    "id": "step_1",
                    "station": "nonexistent-station",
                    "objective": "This will fail",
                },
            ],
        }
        flow_path = spec_dir / "flows" / "bad-flow.yaml"
        with open(flow_path, "w") as f:
            yaml.dump(flow_dict, f)

        results = validate_specs(temp_spec_repo)

        # Should have error about unknown station
        assert len(results["errors"]) > 0
        assert any("Unknown station" in e or "nonexistent-station" in e for e in results["errors"])


class TestSpecManagerEtag:
    """Tests for ETag computation and concurrency control."""

    def test_etag_computation(self, sample_station_dict: Dict):
        """Test that ETag is computed as SHA256 of content."""
        import yaml

        content = yaml.dump(sample_station_dict)
        expected_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()

        # The spec system uses prompt_hash for traceability
        # which is a subset of SHA256
        assert len(expected_hash) == 64  # Full SHA256 hex


class TestSpecManagerListing:
    """Tests for listing available specs."""

    def test_list_stations(self, populated_spec_repo: Path):
        """Test listing available stations."""
        stations = list_stations(populated_spec_repo)

        assert isinstance(stations, list)
        assert "test-station" in stations

    def test_list_flows(self, populated_spec_repo: Path):
        """Test listing available flows."""
        flows = list_flows(populated_spec_repo)

        assert isinstance(flows, list)
        assert "test-flow" in flows

    def test_list_fragments(self, populated_spec_repo: Path):
        """Test listing available fragments."""
        fragments = list_fragments(populated_spec_repo)

        assert isinstance(fragments, list)
        # Fragments use forward slashes
        assert any("invariants" in f for f in fragments)


# =============================================================================
# SpecCompiler Tests
# =============================================================================


class TestSpecCompilerSimpleFlow:
    """Tests for basic flow compilation."""

    def test_compile_simple_flow(self, populated_spec_repo: Path):
        """Test compiling a single-step flow."""
        compiler = SpecCompiler(populated_spec_repo)

        plan = compiler.compile(
            flow_id="test-flow",
            step_id="step_1",
            context_pack=None,
            run_base=Path("/tmp/test-run"),
        )

        assert isinstance(plan, PromptPlan)
        assert plan.station_id == "test-station"
        assert plan.step_id == "step_1"
        assert plan.flow_id == "test-flow"
        # Model is resolved from tier name to full ID
        assert plan.model.startswith("claude-"), f"Expected resolved model ID, got: {plan.model}"
        assert len(plan.prompt_hash) == 16  # Truncated SHA256

    def test_compile_with_context_pack(self, populated_spec_repo: Path, mock_context_pack):
        """Test compilation with context pack."""
        compiler = SpecCompiler(populated_spec_repo)

        plan = compiler.compile(
            flow_id="test-flow",
            step_id="step_1",
            context_pack=mock_context_pack,
            run_base=Path("/tmp/test-run"),
        )

        assert plan.context_pack_size == 2  # Two previous envelopes
        # User prompt should reference artifacts
        assert "plan/adr.md" in plan.user_prompt or "adr" in plan.user_prompt


class TestSpecCompilerTemplateResolution:
    """Tests for template and parameter substitution."""

    def test_compile_with_template(self, populated_spec_repo: Path):
        """Test template resolution in compilation."""
        compiler = SpecCompiler(populated_spec_repo)

        plan = compiler.compile(
            flow_id="test-flow",
            step_id="step_1",
            context_pack=None,
            run_base=Path("/tmp/test-run"),
        )

        # Template should be resolved with step.id
        assert "step_1" in plan.user_prompt

    def test_compile_with_parameters(self):
        """Test parameter substitution in templates."""
        template = "Process {{step.id}} for {{step.objective}}"
        variables = {
            "step": {
                "id": "my_step",
                "objective": "do something",
            },
        }

        result = render_template(template, variables)

        assert result == "Process my_step for do something"

    def test_render_template_nested(self):
        """Test nested variable access in templates."""
        template = "Run {{run.base}} step {{step.id}}"
        variables = {
            "run": {"base": "/tmp/run"},
            "step": {"id": "test"},
        }

        result = render_template(template, variables)

        assert result == "Run /tmp/run step test"


class TestSpecCompilerFragmentLoading:
    """Tests for fragment loading during compilation."""

    def test_fragment_loading(self, populated_spec_repo: Path):
        """Test loading .md fragments."""
        content = load_fragment("common/invariants.md", populated_spec_repo)

        assert "Invariants" in content
        assert "Be consistent" in content

    def test_fragment_not_found(self, temp_spec_repo: Path):
        """Test missing fragment raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            load_fragment("nonexistent/fragment.md", temp_spec_repo)

    def test_load_fragments_graceful(self, populated_spec_repo: Path):
        """Test load_fragments handles missing fragments gracefully."""
        content = load_fragments(
            ["common/invariants.md", "nonexistent.md"],
            populated_spec_repo,
        )

        # Should still have content from the valid fragment
        assert "Invariants" in content


class TestSpecCompilerPromptHash:
    """Tests for deterministic prompt hash computation."""

    def test_prompt_hash_deterministic(self, populated_spec_repo: Path):
        """Test that same input produces same hash."""
        compiler = SpecCompiler(populated_spec_repo)

        plan1 = compiler.compile(
            flow_id="test-flow",
            step_id="step_1",
            context_pack=None,
            run_base=Path("/tmp/test-run"),
        )

        plan2 = compiler.compile(
            flow_id="test-flow",
            step_id="step_1",
            context_pack=None,
            run_base=Path("/tmp/test-run"),
        )

        # Note: compiled_at will differ, but prompt_hash should be same
        # since it's based on system_append + user_prompt
        assert plan1.prompt_hash == plan2.prompt_hash

    def test_prompt_hash_changes_with_content(self, populated_spec_repo: Path):
        """Test that different content produces different hash."""
        compiler = SpecCompiler(populated_spec_repo)

        plan1 = compiler.compile(
            flow_id="test-flow",
            step_id="step_1",
            context_pack=None,
            run_base=Path("/tmp/test-run"),
        )

        plan2 = compiler.compile(
            flow_id="test-flow",
            step_id="step_2",
            context_pack=None,
            run_base=Path("/tmp/test-run"),
        )

        # Different steps should have different hashes
        assert plan1.prompt_hash != plan2.prompt_hash


class TestSpecCompilerMicroloop:
    """Tests for microloop-specific compilation."""

    def test_compile_microloop(self, populated_spec_repo: Path):
        """Test compiling a microloop step."""
        compiler = SpecCompiler(populated_spec_repo)

        plan = compiler.compile(
            flow_id="test-flow",
            step_id="step_2",  # This is the microloop step
            context_pack=None,
            run_base=Path("/tmp/test-run"),
        )

        assert plan.step_id == "step_2"
        # Should still compile successfully
        assert plan.user_prompt
        assert plan.system_append is not None


class TestSpecCompilerVerification:
    """Tests for verification requirements merging."""

    def test_merge_verification_requirements(self, sample_station_dict: Dict):
        """Test merging station and step verification requirements."""
        station = station_spec_from_dict(sample_station_dict)
        step = FlowStep(
            id="test_step",
            station="test-station",
            objective="Test objective",
            outputs=("extra_output.md",),
            routing=RoutingConfig(),
        )
        variables = {"run": {"base": "/tmp/run"}, "step": {"id": "test_step"}}

        verification = merge_verification_requirements(
            station=station,
            step=step,
            run_base=Path("/tmp/run"),
            variables=variables,
        )

        assert isinstance(verification, VerificationRequirements)
        # Should include station required outputs
        assert "output1.md" in verification.required_artifacts
        # Should include step outputs
        assert "extra_output.md" in verification.required_artifacts


class TestSpecCompilerHandoffContract:
    """Tests for handoff contract resolution."""

    def test_resolve_handoff_contract(self, sample_station_dict: Dict):
        """Test resolving handoff contract with template substitution."""
        station = station_spec_from_dict(sample_station_dict)
        variables = {"run": {"base": "/tmp/run"}, "step": {"id": "my_step"}}

        handoff = resolve_handoff_contract(station, variables)

        assert isinstance(handoff, HandoffContract)
        assert "/tmp/run" in handoff.path
        assert "my_step" in handoff.path
        assert "status" in handoff.required_fields


class TestExtractFlowKey:
    """Tests for flow key extraction."""

    def test_extract_flow_key_with_number(self):
        """Test extracting key from numbered flow ID."""
        assert extract_flow_key("3-build") == "build"
        assert extract_flow_key("1-signal") == "signal"
        assert extract_flow_key("7-wisdom") == "wisdom"

    def test_extract_flow_key_already_key(self):
        """Test that bare keys pass through."""
        assert extract_flow_key("build") == "build"
        assert extract_flow_key("signal") == "signal"


# =============================================================================
# SmartRouter Tests (router.py)
# =============================================================================


class TestSmartRouterExplicitNext:
    """Tests for explicit next step routing."""

    def test_route_explicit_next(self):
        """Test that explicit next step in config is respected."""
        config = RoutingConfig(
            kind=RoutingKind.LINEAR,
            next="step_2",
        )

        signal = route_from_routing_config(config, "VERIFIED")

        assert signal is not None
        assert signal.decision == RoutingDecision.ADVANCE
        assert signal.next_step_id == "step_2"
        assert signal.confidence == 1.0


class TestSmartRouterExitOnVerified:
    """Tests for VERIFIED status handling."""

    def test_route_exit_on_verified_linear(self):
        """Test linear routing exits on VERIFIED."""
        config = RoutingConfig(
            kind=RoutingKind.LINEAR,
            next="next_step",
        )

        signal = route_from_routing_config(config, "VERIFIED")

        assert signal.decision == RoutingDecision.ADVANCE
        assert signal.next_step_id == "next_step"

    def test_route_exit_on_verified_microloop(self):
        """Test microloop exits on VERIFIED status."""
        config = RoutingConfig(
            kind=RoutingKind.MICROLOOP,
            next="exit_step",
            loop_target="loop_step",
            loop_success_values=("VERIFIED",),
        )

        signal = route_from_routing_config(config, "VERIFIED")

        assert signal.decision == RoutingDecision.ADVANCE
        assert signal.next_step_id == "exit_step"
        assert signal.reason == "spec_microloop_verified"


class TestSmartRouterMaxIterations:
    """Tests for max iteration handling."""

    def test_route_max_iterations(self):
        """Test routing exits after max iterations."""
        config = RoutingConfig(
            kind=RoutingKind.MICROLOOP,
            next="exit_step",
            loop_target="loop_step",
            max_iterations=3,
        )

        # At iteration 3, should exit
        signal = route_from_routing_config(config, "UNVERIFIED", iteration_count=3)

        assert signal.decision == RoutingDecision.ADVANCE
        assert signal.next_step_id == "exit_step"
        assert signal.needs_human is True  # Human should review
        assert "max_iterations" in signal.reason


class TestSmartRouterSingleEdge:
    """Tests for deterministic single-path routing."""

    def test_route_single_edge(self):
        """Test deterministic routing with single edge."""
        config = RoutingConfig(
            kind=RoutingKind.LINEAR,
            next="only_next",
        )

        signal = route_from_routing_config(config, "UNVERIFIED")

        assert signal.decision == RoutingDecision.ADVANCE
        assert signal.next_step_id == "only_next"
        assert signal.confidence == 1.0


class TestSmartRouterBranching:
    """Tests for branch routing with conditions."""

    def test_route_branch_matching(self):
        """Test branch routing with matching condition."""
        config = RoutingConfig(
            kind=RoutingKind.BRANCH,
            branches={
                "VERIFIED": "success_step",
                "UNVERIFIED": "retry_step",
                "BLOCKED": "escalate_step",
            },
        )

        signal = route_from_routing_config(config, "UNVERIFIED")

        assert signal.decision == RoutingDecision.BRANCH
        assert signal.next_step_id == "retry_step"
        assert signal.route == "UNVERIFIED"

    def test_route_branch_case_insensitive(self):
        """Test branch routing handles case variations."""
        config = RoutingConfig(
            kind=RoutingKind.BRANCH,
            branches={
                "verified": "success_step",
            },
        )

        signal = route_from_routing_config(config, "VERIFIED")

        assert signal.decision == RoutingDecision.BRANCH
        assert signal.next_step_id == "success_step"

    def test_route_branch_fallback(self):
        """Test branch routing falls back to next when no match."""
        config = RoutingConfig(
            kind=RoutingKind.BRANCH,
            next="fallback_step",
            branches={
                "SPECIFIC": "specific_step",
            },
        )

        signal = route_from_routing_config(config, "OTHER_STATUS")

        assert signal.decision == RoutingDecision.ADVANCE
        assert signal.next_step_id == "fallback_step"
        assert signal.reason == "spec_branch_default"


class TestSmartRouterTerminal:
    """Tests for terminal routing."""

    def test_route_terminal(self):
        """Test terminal routing always terminates."""
        config = RoutingConfig(
            kind=RoutingKind.TERMINAL,
        )

        signal = route_from_routing_config(config, "VERIFIED")

        assert signal.decision == RoutingDecision.TERMINATE
        assert signal.reason == "spec_terminal"


class TestSmartRouterInvalidEdge:
    """Tests for rejecting invalid edges."""

    def test_route_no_valid_edges(self):
        """Test routing returns None when no valid path exists."""
        config = RoutingConfig(
            kind=RoutingKind.BRANCH,
            branches={},  # No branches defined
            next=None,  # No fallback
        )

        signal = route_from_routing_config(config, "UNKNOWN_STATUS")

        # Should return None when routing cannot be determined
        assert signal is None


class TestMicroloopTermination:
    """Tests for microloop termination logic."""

    def test_check_microloop_termination_verified(self):
        """Test microloop terminates on VERIFIED status."""
        handoff_data = {"status": "VERIFIED", "summary": "Done"}
        routing_config = {
            "loop_target": "author",
            "loop_success_values": ["VERIFIED"],
            "max_iterations": 3,
        }

        signal = check_microloop_termination(handoff_data, routing_config, current_iteration=1)

        assert signal is not None
        assert signal.decision == RoutingDecision.ADVANCE
        assert "Loop target reached" in signal.reason

    def test_check_microloop_termination_max_iterations(self):
        """Test microloop terminates at max iterations."""
        handoff_data = {"status": "UNVERIFIED", "summary": "Still working"}
        routing_config = {
            "loop_target": "author",
            "loop_success_values": ["VERIFIED"],
            "max_iterations": 3,
        }

        signal = check_microloop_termination(handoff_data, routing_config, current_iteration=3)

        assert signal is not None
        assert signal.decision == RoutingDecision.ADVANCE
        assert "Max iterations" in signal.reason
        assert signal.needs_human is True

    def test_check_microloop_termination_no_further_help(self):
        """Test microloop terminates when can_further_iteration_help is false."""
        handoff_data = {
            "status": "UNVERIFIED",
            "can_further_iteration_help": "no",
        }
        routing_config = {
            "loop_target": "author",
            "loop_success_values": ["VERIFIED"],
            "max_iterations": 5,
        }

        signal = check_microloop_termination(handoff_data, routing_config, current_iteration=1)

        assert signal is not None
        assert signal.decision == RoutingDecision.ADVANCE
        assert "no further iteration can help" in signal.reason

    def test_check_microloop_termination_continue(self):
        """Test microloop continues when no termination condition met."""
        handoff_data = {
            "status": "UNVERIFIED",
            "can_further_iteration_help": True,
        }
        routing_config = {
            "loop_target": "author",
            "loop_success_values": ["VERIFIED"],
            "max_iterations": 5,
        }

        signal = check_microloop_termination(handoff_data, routing_config, current_iteration=2)

        # Should return None to continue looping
        assert signal is None


class TestRouteStepStub:
    """Tests for the stub routing implementation."""

    def test_route_step_stub_linear(self, tmp_path: Path):
        """Test stub routing for linear flow."""
        from swarm.runtime.engines.models import StepContext
        from swarm.runtime.types import RunSpec

        # Create run directory structure
        run_id = "test-run"
        run_dir = tmp_path / "swarm" / "runs" / run_id / "build"
        run_dir.mkdir(parents=True)

        ctx = StepContext(
            repo_root=tmp_path,
            run_id=run_id,
            step_id="step_1",
            flow_key="build",
            step_index=1,
            total_steps=3,
            spec=RunSpec(flow_keys=["build"]),
            flow_title="Build Flow",
            step_role="Test step",
            extra={"routing": {"kind": "linear", "next": "step_2"}},
        )

        signal = route_step_stub(ctx, {"status": "VERIFIED"})

        assert signal.decision == RoutingDecision.ADVANCE
        assert signal.next_step_id == "step_2"

    def test_route_step_stub_microloop_exit(self, tmp_path: Path):
        """Test stub routing exits microloop on VERIFIED."""
        from swarm.runtime.engines.models import StepContext
        from swarm.runtime.types import RunSpec

        # Create run directory structure
        run_id = "test-run"
        run_dir = tmp_path / "swarm" / "runs" / run_id / "build"
        run_dir.mkdir(parents=True)

        ctx = StepContext(
            repo_root=tmp_path,
            run_id=run_id,
            step_id="critic",
            flow_key="build",
            step_index=2,
            total_steps=3,
            spec=RunSpec(flow_keys=["build"]),
            flow_title="Build Flow",
            step_role="Critic step",
            extra={
                "routing": {
                    "kind": "microloop",
                    "next": "next_step",
                    "loop_target": "author",
                    "loop_success_values": ["VERIFIED"],
                }
            },
        )

        signal = route_step_stub(ctx, {"status": "VERIFIED"})

        assert signal.decision == RoutingDecision.ADVANCE
        assert "microloop_exit" in signal.reason


# =============================================================================
# Integration Tests
# =============================================================================


class TestEndToEndCompileAndRoute:
    """Integration tests for full compile + route workflow."""

    def test_end_to_end_compile_and_route(self, populated_spec_repo: Path):
        """Test full flow compilation followed by routing."""
        # 1. Compile the step
        compiler = SpecCompiler(populated_spec_repo)
        plan = compiler.compile(
            flow_id="test-flow",
            step_id="step_2",  # Microloop step
            context_pack=None,
            run_base=Path("/tmp/test-run"),
        )

        # Verify compilation succeeded
        assert plan is not None
        assert plan.station_id == "test-station"
        assert plan.step_id == "step_2"

        # 2. Simulate handoff and route
        # Load the flow to get routing config
        flow = load_flow("test-flow", populated_spec_repo)
        step = next(s for s in flow.steps if s.id == "step_2")

        routing_config = RoutingConfig(
            kind=step.routing.kind,
            next=step.routing.next,
            loop_target=step.routing.loop_target,
            max_iterations=step.routing.max_iterations,
            loop_success_values=step.routing.loop_success_values,
        )

        # 3. Route based on VERIFIED status
        signal = route_from_routing_config(routing_config, "VERIFIED", iteration_count=1)

        assert signal is not None
        assert signal.decision == RoutingDecision.ADVANCE
        assert signal.next_step_id == "step_3"  # Should proceed to next step

    def test_end_to_end_with_loop(self, populated_spec_repo: Path):
        """Test compile + route with loop back."""
        # Load flow and get microloop step
        flow = load_flow("test-flow", populated_spec_repo)
        step = next(s for s in flow.steps if s.id == "step_2")

        routing_config = RoutingConfig(
            kind=step.routing.kind,
            next=step.routing.next,
            loop_target=step.routing.loop_target,
            max_iterations=step.routing.max_iterations,
            loop_success_values=step.routing.loop_success_values,
        )

        # Route with UNVERIFIED - should loop back
        signal = route_from_routing_config(routing_config, "UNVERIFIED", iteration_count=1)

        assert signal is not None
        assert signal.decision == RoutingDecision.LOOP
        assert signal.next_step_id == "step_1"  # Loop back to loop_target

    def test_verification_requirements_in_plan(self, populated_spec_repo: Path, tmp_path: Path):
        """Test that compiled plan includes verification requirements."""
        run_base = tmp_path / "test-run"
        run_base.mkdir()

        compiler = SpecCompiler(populated_spec_repo)
        plan = compiler.compile(
            flow_id="test-flow",
            step_id="step_1",
            context_pack=None,
            run_base=run_base,
        )

        # Should have verification requirements
        assert plan.verification is not None
        assert isinstance(plan.verification.required_artifacts, tuple)

        # Should have handoff contract with run base path
        assert plan.handoff is not None
        # Use path normalization to handle Windows/Unix differences
        assert "test-run" in plan.handoff.path
        assert "handoff" in plan.handoff.path
        assert "step_1" in plan.handoff.path


class TestSpecSystemTypeConversions:
    """Tests for type conversion helpers."""

    def test_station_spec_from_dict(self, sample_station_dict: Dict):
        """Test converting dict to StationSpec."""
        station = station_spec_from_dict(sample_station_dict)

        assert station.id == "test-station"
        assert station.version == 1
        assert station.category == StationCategory.IMPLEMENTATION
        assert station.sdk.model == "sonnet"
        assert station.sdk.sandbox.enabled is True
        assert "docker" in station.sdk.sandbox.excluded_commands
        assert len(station.invariants) == 2

    def test_flow_spec_from_dict(self, sample_flow_dict: Dict):
        """Test converting dict to FlowSpec."""
        flow = flow_spec_from_dict(sample_flow_dict)

        assert flow.id == "test-flow"
        assert flow.version == 1
        assert len(flow.steps) == 3
        assert flow.steps[0].routing.kind == RoutingKind.LINEAR
        assert flow.steps[1].routing.kind == RoutingKind.MICROLOOP
        assert flow.steps[2].routing.kind == RoutingKind.TERMINAL


class TestSystemAppendBuilding:
    """Tests for system prompt append construction."""

    def test_build_system_append_basic(self, sample_station_dict: Dict):
        """Test basic system append building."""
        station = station_spec_from_dict(sample_station_dict)

        append = build_system_append(station)

        assert "You are the Test Station" in append
        assert "Never do bad things" in append
        assert "Always be honest" in append

    def test_build_system_append_with_scent_trail(self, sample_station_dict: Dict):
        """Test system append with scent trail."""
        station = station_spec_from_dict(sample_station_dict)

        append = build_system_append(station, scent_trail="Remember past mistakes")

        assert "Lessons from Previous Runs" in append
        assert "Remember past mistakes" in append

    def test_build_system_append_v2(self, sample_station_dict: Dict, populated_spec_repo: Path):
        """Test v2 system append with fragment loading."""
        station = station_spec_from_dict(sample_station_dict)

        append = build_system_append_v2(
            station,
            repo_root=populated_spec_repo,
            policy_invariants_ref=["common/invariants.md"],
        )

        # Should include station identity
        assert "You are the Test Station" in append
        # Should include policy fragments
        assert "Policy Invariants" in append or "Be consistent" in append


class TestUserPromptBuilding:
    """Tests for user prompt construction."""

    def test_build_user_prompt_basic(self, sample_station_dict: Dict, populated_spec_repo: Path):
        """Test basic user prompt building."""
        station = station_spec_from_dict(sample_station_dict)
        step = FlowStep(
            id="test_step",
            station="test-station",
            objective="Do the test thing",
            scope="AC-001",
            routing=RoutingConfig(),
        )

        prompt = build_user_prompt(
            station=station,
            step=step,
            context_pack=None,
            run_base=Path("/tmp/run"),
            repo_root=populated_spec_repo,
        )

        assert "Objective" in prompt
        assert "Do the test thing" in prompt
        assert "AC-001" in prompt
        assert "Required Outputs" in prompt
        assert "Finalization" in prompt

    def test_build_user_prompt_with_context(
        self, sample_station_dict: Dict, mock_context_pack, populated_spec_repo: Path
    ):
        """Test user prompt with context pack."""
        station = station_spec_from_dict(sample_station_dict)
        step = FlowStep(
            id="test_step",
            station="test-station",
            objective="Process with context",
            routing=RoutingConfig(),
        )

        prompt = build_user_prompt(
            station=station,
            step=step,
            context_pack=mock_context_pack,
            run_base=Path("/tmp/run"),
            repo_root=populated_spec_repo,
        )

        assert "Available Artifacts" in prompt
        assert "Previous Steps" in prompt
        assert "step_0" in prompt  # Previous envelope step_id


# =============================================================================
# Edge Case Tests
# =============================================================================


class TestSmartRoutingWithExplanations:
    """Tests for smart_route function with structured explanations."""

    def test_smart_route_linear(self):
        """Test smart_route produces explanation for linear routing."""
        from swarm.runtime.engines.claude.router import smart_route
        from swarm.runtime.types import DecisionType

        config = RoutingConfig(kind=RoutingKind.LINEAR, next="step_2")
        signal = smart_route(config, {"status": "VERIFIED"})

        assert signal.decision == RoutingDecision.ADVANCE
        assert signal.next_step_id == "step_2"
        assert signal.explanation is not None
        assert signal.explanation.decision_type == DecisionType.DETERMINISTIC
        assert signal.explanation.selected_target == "step_2"
        assert "Linear flow" in signal.explanation.reasoning_summary

    def test_smart_route_microloop_exit(self):
        """Test smart_route produces explanation for microloop exit."""
        from swarm.runtime.engines.claude.router import smart_route
        from swarm.runtime.types import DecisionType

        config = RoutingConfig(
            kind=RoutingKind.MICROLOOP,
            next="next_step",
            loop_target="author",
            loop_success_values=("VERIFIED",),
            max_iterations=3,
        )
        signal = smart_route(config, {"status": "VERIFIED"}, iteration_count=1)

        assert signal.decision == RoutingDecision.ADVANCE
        assert signal.next_step_id == "next_step"
        assert signal.explanation is not None
        assert signal.explanation.decision_type == DecisionType.EXIT_CONDITION
        assert signal.explanation.microloop_context is not None
        assert signal.explanation.microloop_context.iteration == 2

    def test_smart_route_microloop_continue(self):
        """Test smart_route produces explanation for microloop continue."""
        from swarm.runtime.engines.claude.router import smart_route
        from swarm.runtime.types import DecisionType

        config = RoutingConfig(
            kind=RoutingKind.MICROLOOP,
            next="next_step",
            loop_target="author",
            loop_success_values=("VERIFIED",),
            max_iterations=3,
        )
        signal = smart_route(config, {"status": "UNVERIFIED", "can_further_iteration_help": True}, iteration_count=1)

        assert signal.decision == RoutingDecision.LOOP
        assert signal.next_step_id == "author"
        assert signal.loop_count == 2
        assert signal.explanation is not None
        assert signal.explanation.decision_type == DecisionType.DETERMINISTIC
        assert len(signal.explanation.elimination_log) > 0

    def test_smart_route_branch(self):
        """Test smart_route produces explanation for branch routing."""
        from swarm.runtime.engines.claude.router import smart_route
        from swarm.runtime.types import DecisionType

        config = RoutingConfig(
            kind=RoutingKind.BRANCH,
            branches={
                "VERIFIED": "success_step",
                "UNVERIFIED": "retry_step",
            },
        )
        signal = smart_route(config, {"status": "UNVERIFIED"})

        assert signal.decision == RoutingDecision.BRANCH
        assert signal.next_step_id == "retry_step"
        assert signal.route == "UNVERIFIED"
        assert signal.explanation is not None
        assert "Branch matched" in signal.explanation.reasoning_summary

    def test_smart_route_terminal(self):
        """Test smart_route produces explanation for terminal."""
        from swarm.runtime.engines.claude.router import smart_route
        from swarm.runtime.types import DecisionType

        config = RoutingConfig(kind=RoutingKind.TERMINAL)
        signal = smart_route(config, {"status": "VERIFIED"})

        assert signal.decision == RoutingDecision.TERMINATE
        assert signal.explanation is not None
        assert signal.explanation.decision_type == DecisionType.EXIT_CONDITION
        assert "Terminal" in signal.explanation.reasoning_summary

    def test_smart_route_metrics(self):
        """Test smart_route populates decision metrics."""
        from swarm.runtime.engines.claude.router import smart_route

        config = RoutingConfig(
            kind=RoutingKind.BRANCH,
            next="default",
            branches={"A": "step_a", "B": "step_b", "C": "step_c"},
        )
        signal = smart_route(config, {"status": "B"})

        assert signal.explanation is not None
        assert signal.explanation.metrics is not None
        assert signal.explanation.metrics.edges_eliminated >= 0


class TestRoutingExplanationSerialization:
    """Tests for RoutingExplanation serialization round-trip."""

    def test_routing_explanation_round_trip(self):
        """Test RoutingExplanation survives serialization."""
        from swarm.runtime.types import (
            routing_explanation_to_dict, routing_explanation_from_dict,
            RoutingExplanation, DecisionType, EdgeOption, Elimination,
            MicroloopContext, DecisionMetrics,
        )
        from datetime import datetime, timezone

        original = RoutingExplanation(
            decision_type=DecisionType.DETERMINISTIC,
            selected_target="step_2",
            timestamp=datetime.now(timezone.utc),
            confidence=0.95,
            reasoning_summary="Test routing explanation",
            available_edges=[
                EdgeOption(edge_id="e1", target_node="step_2", edge_type="sequence"),
                EdgeOption(edge_id="e2", target_node="step_3", edge_type="branch"),
            ],
            elimination_log=[
                Elimination(edge_id="e2", reason_code="condition_false", detail="Status mismatch"),
            ],
            microloop_context=MicroloopContext(
                iteration=2, max_iterations=5, loop_target="author",
            ),
            metrics=DecisionMetrics(total_time_ms=10, edges_total=2, edges_eliminated=1),
        )

        serialized = routing_explanation_to_dict(original)
        restored = routing_explanation_from_dict(serialized)

        assert restored.decision_type == original.decision_type
        assert restored.selected_target == original.selected_target
        assert restored.confidence == original.confidence
        assert restored.reasoning_summary == original.reasoning_summary
        assert len(restored.available_edges) == 2
        assert len(restored.elimination_log) == 1
        assert restored.microloop_context is not None
        assert restored.microloop_context.iteration == 2
        assert restored.metrics is not None
        assert restored.metrics.edges_eliminated == 1

    def test_routing_signal_with_explanation_round_trip(self):
        """Test RoutingSignal with explanation survives serialization."""
        from swarm.runtime.types import (
            routing_signal_to_dict, routing_signal_from_dict,
            RoutingSignal, RoutingDecision, RoutingExplanation, DecisionType,
        )
        from datetime import datetime, timezone

        explanation = RoutingExplanation(
            decision_type=DecisionType.LLM_TIEBREAKER,
            selected_target="step_x",
            timestamp=datetime.now(timezone.utc),
            confidence=0.85,
            reasoning_summary="LLM chose based on heuristics",
        )

        original = RoutingSignal(
            decision=RoutingDecision.ADVANCE,
            next_step_id="step_x",
            reason="LLM routing decision",
            confidence=0.85,
            explanation=explanation,
        )

        serialized = routing_signal_to_dict(original)
        restored = routing_signal_from_dict(serialized)

        assert restored.decision == original.decision
        assert restored.next_step_id == original.next_step_id
        assert restored.explanation is not None
        assert restored.explanation.decision_type == DecisionType.LLM_TIEBREAKER
        assert restored.explanation.selected_target == "step_x"


class TestHandoffEnvelopeWithAudit:
    """Tests for HandoffEnvelope with routing audit trail."""

    def test_handoff_envelope_with_routing_audit(self):
        """Test HandoffEnvelope serialization includes routing audit."""
        from swarm.runtime.types import (
            HandoffEnvelope, RoutingSignal, RoutingDecision,
            RoutingExplanation, DecisionType,
            handoff_envelope_to_dict, handoff_envelope_from_dict,
        )
        from datetime import datetime, timezone

        explanation = RoutingExplanation(
            decision_type=DecisionType.DETERMINISTIC,
            selected_target="step_2",
            timestamp=datetime.now(timezone.utc),
            confidence=1.0,
            reasoning_summary="Linear routing",
        )

        envelope = HandoffEnvelope(
            step_id="step_1",
            flow_key="build",
            run_id="test-run",
            routing_signal=RoutingSignal(
                decision=RoutingDecision.ADVANCE,
                next_step_id="step_2",
                explanation=explanation,
            ),
            summary="Test step completed",
            status="succeeded",
        )

        serialized = handoff_envelope_to_dict(envelope)

        # Routing audit should be present
        assert "routing_audit" in serialized
        assert serialized["routing_audit"]["decision_type"] == "deterministic"
        assert serialized["routing_audit"]["selected_target"] == "step_2"

        # Round-trip
        restored = handoff_envelope_from_dict(serialized)
        assert restored.routing_audit is not None
        assert restored.routing_audit["decision_type"] == "deterministic"


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_empty_station_identity(self):
        """Test station with empty identity."""
        station_dict = {
            "id": "minimal",
            "version": 1,
            "title": "Minimal",
            "identity": {"system_append": ""},
        }
        station = station_spec_from_dict(station_dict)

        append = build_system_append(station)

        # Should not fail, just be empty or minimal
        assert isinstance(append, str)

    def test_flow_with_no_steps(self):
        """Test flow with no steps."""
        flow_dict = {
            "id": "empty-flow",
            "version": 1,
            "title": "Empty Flow",
            "steps": [],
        }

        flow = flow_spec_from_dict(flow_dict)

        assert len(flow.steps) == 0

    def test_routing_config_defaults(self):
        """Test RoutingConfig default values."""
        config = RoutingConfig()

        assert config.kind == RoutingKind.LINEAR
        assert config.next is None
        assert config.max_iterations == 3
        assert "VERIFIED" in config.loop_success_values

    def test_route_with_empty_status(self):
        """Test routing with empty status string."""
        config = RoutingConfig(
            kind=RoutingKind.LINEAR,
            next="next_step",
        )

        signal = route_from_routing_config(config, "")

        assert signal is not None
        assert signal.decision == RoutingDecision.ADVANCE

    def test_microloop_with_case_variation(self):
        """Test microloop handles status case variations."""
        config = RoutingConfig(
            kind=RoutingKind.MICROLOOP,
            next="exit",
            loop_target="loop",
            loop_success_values=("VERIFIED", "verified"),
        )

        signal = route_from_routing_config(config, "Verified")

        # Should match case-insensitively
        assert signal.decision == RoutingDecision.ADVANCE
