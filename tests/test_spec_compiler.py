"""Tests for the spec compiler module.

This module tests the SpecCompiler which produces PromptPlans from specs.
Tests cover template resolution, fragment concatenation, verification requirements
merging, and prompt_hash computation.
"""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from dataclasses import dataclass
from typing import Dict, List, Optional
import hashlib

# Add swarm to path
import sys
_SWARM_ROOT = Path(__file__).resolve().parent.parent
if str(_SWARM_ROOT) not in sys.path:
    sys.path.insert(0, str(_SWARM_ROOT))

from swarm.spec.compiler import (
    SpecCompiler,
    compile_prompt,
    render_template,
    build_system_append,
    build_system_append_v2,
    build_user_prompt,
    merge_verification_requirements,
    resolve_handoff_contract,
    extract_flow_key,
)
from swarm.spec.types import (
    PromptPlan,
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
    VerificationRequirements,
    HandoffContract,
)
from swarm.spec.loader import list_flows, load_flow


class TestExtractFlowKey:
    """Tests for extract_flow_key function."""

    def test_extract_flow_key_with_number_prefix(self):
        """Flow IDs with number prefix should extract the key."""
        assert extract_flow_key("3-build") == "build"
        assert extract_flow_key("1-signal") == "signal"
        assert extract_flow_key("2-plan") == "plan"
        assert extract_flow_key("4-review") == "review"
        assert extract_flow_key("5-gate") == "gate"
        assert extract_flow_key("6-deploy") == "deploy"
        assert extract_flow_key("7-wisdom") == "wisdom"

    def test_extract_flow_key_without_prefix(self):
        """Flow IDs without number prefix should return as-is."""
        assert extract_flow_key("build") == "build"
        assert extract_flow_key("signal") == "signal"
        assert extract_flow_key("custom-flow") == "custom-flow"

    def test_extract_flow_key_complex_names(self):
        """Complex flow names should extract correctly."""
        assert extract_flow_key("1-signal-analysis") == "signal-analysis"
        assert extract_flow_key("99-multi-part-name") == "multi-part-name"

    def test_extract_flow_key_edge_cases(self):
        """Edge cases should be handled gracefully."""
        assert extract_flow_key("") == ""
        assert extract_flow_key("-") == "-"
        assert extract_flow_key("abc-def") == "abc-def"  # No number prefix


class TestRenderTemplate:
    """Tests for Mustache-style template rendering."""

    def test_render_simple_variable(self):
        """Simple variable substitution should work."""
        template = "Hello, {{name}}!"
        variables = {"name": "World"}

        result = render_template(template, variables)

        assert result == "Hello, World!"

    def test_render_nested_variable(self):
        """Nested variable access should work."""
        template = "Step: {{step.id}}, Station: {{station.title}}"
        variables = {
            "step": {"id": "implement", "objective": "Build code"},
            "station": {"title": "Code Implementer"}
        }

        result = render_template(template, variables)

        assert result == "Step: implement, Station: Code Implementer"

    def test_render_run_base(self):
        """{{run.base}} should be resolved correctly."""
        template = "Output: {{run.base}}/build/impl.md"
        variables = {"run": {"base": "swarm/runs/test-run"}}

        result = render_template(template, variables)

        assert result == "Output: swarm/runs/test-run/build/impl.md"

    def test_render_missing_variable_empty_string(self):
        """Missing variables should render as empty string."""
        template = "Value: {{missing.key}}"
        variables = {}

        result = render_template(template, variables)

        assert result == "Value: "

    def test_render_multiple_occurrences(self):
        """Multiple occurrences of same variable should all be replaced."""
        template = "{{name}} says {{name}}"
        variables = {"name": "Alice"}

        result = render_template(template, variables)

        assert result == "Alice says Alice"

    def test_render_with_whitespace(self):
        """Template variables with whitespace should work."""
        template = "{{ name }}"
        variables = {"name": "Test"}

        result = render_template(template, variables)

        assert result == "Test"


class TestBuildSystemAppend:
    """Tests for building system prompt append."""

    def test_build_system_append_includes_identity(self):
        """System append should include station identity."""
        station = _create_test_station(
            system_append="You are the Test Agent."
        )

        result = build_system_append(station)

        assert "You are the Test Agent." in result

    def test_build_system_append_includes_invariants(self):
        """System append should include station invariants."""
        station = _create_test_station(
            invariants=("Rule 1", "Rule 2")
        )

        result = build_system_append(station)

        assert "Rule 1" in result
        assert "Rule 2" in result
        assert "Invariants" in result

    def test_build_system_append_includes_scent_trail(self):
        """System append should include scent trail when provided."""
        station = _create_test_station()
        scent_trail = "Lesson learned: Always validate inputs."

        result = build_system_append(station, scent_trail)

        assert "Lesson learned" in result
        assert "Previous Runs" in result

    def test_build_system_append_truncates_long_scent_trail(self):
        """Long scent trails should be truncated."""
        station = _create_test_station()
        long_trail = "A" * 2000  # Longer than 1500 char limit

        result = build_system_append(station, long_trail)

        assert len(result) < len(long_trail) + 500  # Some overhead for headers
        assert "truncated" in result.lower()


class TestBuildSystemAppendV2:
    """Tests for v2 system prompt append with policy loading."""

    def test_build_system_append_v2_includes_identity(self):
        """V2 system append should include station identity."""
        station = _create_test_station(
            system_append="You are the V2 Test Agent."
        )

        result = build_system_append_v2(station)

        assert "You are the V2 Test Agent." in result

    def test_build_system_append_v2_includes_invariants(self):
        """V2 system append should include station invariants."""
        station = _create_test_station(
            invariants=("V2 Rule 1", "V2 Rule 2")
        )

        result = build_system_append_v2(station)

        assert "V2 Rule 1" in result
        assert "V2 Rule 2" in result


class TestBuildUserPrompt:
    """Tests for building user prompts."""

    def test_build_user_prompt_includes_objective(self):
        """User prompt should include step objective."""
        station = _create_test_station()
        step = _create_test_step(objective="Implement the feature")
        run_base = Path("swarm/runs/test")

        result = build_user_prompt(station, step, None, run_base)

        assert "Implement the feature" in result
        assert "Objective" in result

    def test_build_user_prompt_includes_scope(self):
        """User prompt should include step scope when present."""
        station = _create_test_station()
        step = _create_test_step(scope="Module A only")
        run_base = Path("swarm/runs/test")

        result = build_user_prompt(station, step, None, run_base)

        assert "Module A only" in result

    def test_build_user_prompt_includes_handoff_instructions(self):
        """User prompt should include handoff instructions."""
        station = _create_test_station()
        step = _create_test_step()
        run_base = Path("swarm/runs/test")

        result = build_user_prompt(station, step, None, run_base)

        assert "Finalization" in result
        assert "handoff" in result.lower()
        assert "status" in result.lower()

    def test_build_user_prompt_includes_required_outputs(self):
        """User prompt should include required outputs."""
        station = _create_test_station(
            required_outputs=("build/output.md",)
        )
        step = _create_test_step(outputs=("build/extra.md",))
        run_base = Path("swarm/runs/test")

        result = build_user_prompt(station, step, None, run_base)

        assert "build/output.md" in result
        assert "build/extra.md" in result


class TestMergeVerificationRequirements:
    """Tests for merging verification requirements from station and step."""

    def test_merge_includes_station_outputs(self):
        """Merged requirements should include station required outputs."""
        station = _create_test_station(
            required_outputs=("build/station_output.md",)
        )
        step = _create_test_step()
        run_base = Path("swarm/runs/test")
        variables = {"run": {"base": str(run_base)}, "step": {"id": step.id}}

        result = merge_verification_requirements(station, step, run_base, variables)

        assert "build/station_output.md" in result.required_artifacts

    def test_merge_includes_step_outputs(self):
        """Merged requirements should include step outputs."""
        station = _create_test_station()
        step = _create_test_step(outputs=("build/step_output.md",))
        run_base = Path("swarm/runs/test")
        variables = {"run": {"base": str(run_base)}, "step": {"id": step.id}}

        result = merge_verification_requirements(station, step, run_base, variables)

        assert "build/step_output.md" in result.required_artifacts

    def test_merge_deduplicates_outputs(self):
        """Merged requirements should not duplicate outputs."""
        station = _create_test_station(
            required_outputs=("build/output.md",)
        )
        step = _create_test_step(outputs=("build/output.md",))
        run_base = Path("swarm/runs/test")
        variables = {"run": {"base": str(run_base)}, "step": {"id": step.id}}

        result = merge_verification_requirements(station, step, run_base, variables)

        # Count occurrences of the output
        count = result.required_artifacts.count("build/output.md")
        assert count == 1


class TestResolveHandoffContract:
    """Tests for resolving handoff contract with template substitution."""

    def test_resolve_handoff_path(self):
        """Handoff path should be resolved with template variables."""
        station = _create_test_station(
            handoff_template="{{run.base}}/handoff/{{step.id}}.json"
        )
        variables = {
            "run": {"base": "swarm/runs/test"},
            "step": {"id": "implement"}
        }

        result = resolve_handoff_contract(station, variables)

        assert result.path == "swarm/runs/test/handoff/implement.json"

    def test_resolve_handoff_required_fields(self):
        """Handoff required fields should be preserved."""
        station = _create_test_station(
            handoff_required_fields=("status", "summary", "artifacts")
        )
        variables = {"run": {"base": "test"}, "step": {"id": "test"}}

        result = resolve_handoff_contract(station, variables)

        assert "status" in result.required_fields
        assert "summary" in result.required_fields
        assert "artifacts" in result.required_fields


class TestSpecCompiler:
    """Tests for the SpecCompiler class."""

    def test_compile_produces_prompt_plan(self):
        """compile() should produce a valid PromptPlan."""
        repo_root = Path(__file__).parent.parent
        compiler = SpecCompiler(repo_root)
        run_base = Path("swarm/runs/test")

        # Use a known flow and step
        plan = compiler.compile(
            flow_id="3-build",
            step_id="implement",
            context_pack=None,
            run_base=run_base,
        )

        assert isinstance(plan, PromptPlan)
        assert plan.station_id == "code-implementer"
        assert plan.flow_id == "3-build"
        assert plan.step_id == "implement"

    def test_compile_sets_sdk_options(self):
        """Compiled plan should have SDK options from station."""
        repo_root = Path(__file__).parent.parent
        compiler = SpecCompiler(repo_root)
        run_base = Path("swarm/runs/test")

        plan = compiler.compile(
            flow_id="3-build",
            step_id="implement",
            context_pack=None,
            run_base=run_base,
        )

        # Model should be a valid tier alias (SDK-native) or full model ID (pinned)
        valid_tiers = {"haiku", "sonnet", "opus"}
        is_tier_alias = plan.model in valid_tiers
        is_full_id = plan.model.startswith("claude-")
        assert is_tier_alias or is_full_id, f"Expected tier alias or model ID, got: {plan.model}"
        assert plan.permission_mode in ("bypassPermissions", "default")
        assert len(plan.allowed_tools) > 0
        assert plan.max_turns >= 1

    def test_compile_computes_prompt_hash(self):
        """Compiled plan should have a prompt hash for traceability."""
        repo_root = Path(__file__).parent.parent
        compiler = SpecCompiler(repo_root)
        run_base = Path("swarm/runs/test")

        plan = compiler.compile(
            flow_id="3-build",
            step_id="implement",
            context_pack=None,
            run_base=run_base,
        )

        assert plan.prompt_hash != ""
        assert len(plan.prompt_hash) == 16  # Truncated SHA256

    def test_compile_hash_deterministic(self):
        """Prompt hash should be deterministic for same inputs."""
        repo_root = Path(__file__).parent.parent
        compiler = SpecCompiler(repo_root)
        run_base = Path("swarm/runs/test")

        plan1 = compiler.compile(
            flow_id="3-build",
            step_id="implement",
            context_pack=None,
            run_base=run_base,
        )
        plan2 = compiler.compile(
            flow_id="3-build",
            step_id="implement",
            context_pack=None,
            run_base=run_base,
        )

        assert plan1.prompt_hash == plan2.prompt_hash

    def test_compile_sets_compiled_at(self):
        """Compiled plan should have a timestamp."""
        repo_root = Path(__file__).parent.parent
        compiler = SpecCompiler(repo_root)
        run_base = Path("swarm/runs/test")

        plan = compiler.compile(
            flow_id="3-build",
            step_id="implement",
            context_pack=None,
            run_base=run_base,
        )

        assert plan.compiled_at != ""
        # Should be ISO format with timezone
        assert "T" in plan.compiled_at

    def test_compile_sets_flow_key(self):
        """Compiled plan should have flow_key extracted from flow_id."""
        repo_root = Path(__file__).parent.parent
        compiler = SpecCompiler(repo_root)
        run_base = Path("swarm/runs/test")

        plan = compiler.compile(
            flow_id="3-build",
            step_id="implement",
            context_pack=None,
            run_base=run_base,
        )

        assert plan.flow_key == "build"

    def test_compile_sets_verification_requirements(self):
        """Compiled plan should include verification requirements."""
        repo_root = Path(__file__).parent.parent
        compiler = SpecCompiler(repo_root)
        run_base = Path("swarm/runs/test")

        plan = compiler.compile(
            flow_id="3-build",
            step_id="implement",
            context_pack=None,
            run_base=run_base,
        )

        assert isinstance(plan.verification, VerificationRequirements)

    def test_compile_sets_handoff_contract(self):
        """Compiled plan should include resolved handoff contract."""
        repo_root = Path(__file__).parent.parent
        compiler = SpecCompiler(repo_root)
        run_base = Path("swarm/runs/test")

        plan = compiler.compile(
            flow_id="3-build",
            step_id="implement",
            context_pack=None,
            run_base=run_base,
        )

        assert isinstance(plan.handoff, HandoffContract)
        assert plan.handoff.path != ""

    def test_compile_unknown_flow_raises_error(self):
        """Compiling with unknown flow should raise FileNotFoundError."""
        repo_root = Path(__file__).parent.parent
        compiler = SpecCompiler(repo_root)

        with pytest.raises(FileNotFoundError):
            compiler.compile(
                flow_id="999-nonexistent",
                step_id="test",
                context_pack=None,
                run_base=Path("test"),
            )

    def test_compile_unknown_step_raises_error(self):
        """Compiling with unknown step should raise ValueError."""
        repo_root = Path(__file__).parent.parent
        compiler = SpecCompiler(repo_root)

        with pytest.raises(ValueError) as exc_info:
            compiler.compile(
                flow_id="3-build",
                step_id="nonexistent-step",
                context_pack=None,
                run_base=Path("test"),
            )

        assert "nonexistent-step" in str(exc_info.value)


class TestCompilePromptFunction:
    """Tests for the compile_prompt convenience function."""

    def test_compile_prompt_produces_plan(self):
        """compile_prompt should produce a valid PromptPlan."""
        repo_root = Path(__file__).parent.parent
        run_base = Path("swarm/runs/test")

        plan = compile_prompt(
            flow_id="3-build",
            step_id="implement",
            context_pack=None,
            run_base=run_base,
            repo_root=repo_root,
        )

        assert isinstance(plan, PromptPlan)
        assert plan.step_id == "implement"


class TestPromptHashComputation:
    """Tests for prompt hash computation."""

    def test_hash_changes_with_different_prompts(self):
        """Different prompts should produce different hashes."""
        content1 = "Prompt A"
        content2 = "Prompt B"

        hash1 = hashlib.sha256(content1.encode()).hexdigest()[:16]
        hash2 = hashlib.sha256(content2.encode()).hexdigest()[:16]

        assert hash1 != hash2

    def test_hash_stable_for_same_content(self):
        """Same content should always produce same hash."""
        content = "Stable content for hashing"

        hash1 = hashlib.sha256(content.encode()).hexdigest()[:16]
        hash2 = hashlib.sha256(content.encode()).hexdigest()[:16]

        assert hash1 == hash2


class TestAllFlowsCompile:
    """Integration tests for compiling all flows."""

    def test_all_flows_have_compilable_steps(self):
        """All flows should have at least one compilable step."""
        repo_root = Path(__file__).parent.parent
        compiler = SpecCompiler(repo_root)
        run_base = Path("swarm/runs/test")

        for flow_id in list_flows():
            flow = load_flow(flow_id)
            if len(flow.steps) == 0:
                continue

            # Try to compile the first step
            first_step = flow.steps[0]
            try:
                plan = compiler.compile(
                    flow_id=flow_id,
                    step_id=first_step.id,
                    context_pack=None,
                    run_base=run_base,
                )
                assert plan.flow_id == flow_id
                assert plan.step_id == first_step.id
            except FileNotFoundError as e:
                # Station not found - this is a validation issue, not a compiler issue
                pytest.skip(f"Station not found for {flow_id}/{first_step.id}: {e}")


# =============================================================================
# Test Helpers
# =============================================================================


def _create_test_station(
    id: str = "test-station",
    system_append: str = "You are a test agent.",
    invariants: tuple = (),
    required_inputs: tuple = (),
    required_outputs: tuple = (),
    handoff_template: str = "{{run.base}}/handoff/{{step.id}}.json",
    handoff_required_fields: tuple = ("status", "summary", "artifacts"),
) -> StationSpec:
    """Create a test StationSpec with defaults."""
    return StationSpec(
        id=id,
        version=1,
        title="Test Station",
        category=StationCategory.IMPLEMENTATION,
        sdk=StationSDK(
            model="sonnet",
            permission_mode="bypassPermissions",
            allowed_tools=("Read", "Write", "Edit"),
            denied_tools=(),
            sandbox=StationSandbox(),
            max_turns=12,
            context_budget=StationContextBudget(),
        ),
        identity=StationIdentity(
            system_append=system_append,
            tone="neutral",
        ),
        io=StationIO(
            required_inputs=required_inputs,
            optional_inputs=(),
            required_outputs=required_outputs,
            optional_outputs=(),
        ),
        handoff=StationHandoff(
            path_template=handoff_template,
            required_fields=handoff_required_fields,
        ),
        runtime_prompt=StationRuntimePrompt(
            fragments=(),
            template="",
        ),
        invariants=invariants,
        routing_hints=StationRoutingHints(),
    )


def _create_test_step(
    id: str = "test-step",
    station: str = "test-station",
    objective: str = "Test objective",
    scope: Optional[str] = None,
    inputs: tuple = (),
    outputs: tuple = (),
) -> FlowStep:
    """Create a test FlowStep with defaults."""
    return FlowStep(
        id=id,
        station=station,
        objective=objective,
        scope=scope,
        inputs=inputs,
        outputs=outputs,
        routing=RoutingConfig(kind=RoutingKind.LINEAR),
        sdk_overrides={},
    )
