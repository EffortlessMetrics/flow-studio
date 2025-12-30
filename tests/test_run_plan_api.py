"""
Tests for run_plan_api.py - RunPlanSpec CRUD and autopilot orchestration.

These tests verify:
1. RunPlanAPI CRUD operations
2. Default plan creation
3. Plan validation
4. Plan serialization/persistence
5. Plan cloning
"""

import pytest
from pathlib import Path
from datetime import datetime, timezone

from swarm.runtime.run_plan_api import (
    RunPlanAPI,
    StoredPlan,
    PlanMetadata,
    create_run_plan_api,
    load_run_plan,
    list_run_plans,
    stored_plan_to_dict,
    stored_plan_from_dict,
    plan_metadata_to_dict,
    plan_metadata_from_dict,
)
from swarm.runtime.types import (
    RunPlanSpec,
    MacroPolicy,
    HumanPolicy,
)


# =============================================================================
# PlanMetadata Tests
# =============================================================================


class TestPlanMetadata:
    """Tests for PlanMetadata dataclass."""

    def test_metadata_creation(self):
        """Test creating plan metadata."""
        meta = PlanMetadata(
            plan_id="test-plan",
            name="Test Plan",
            description="A test plan",
            created_by="tester",
            tags=["test", "example"],
        )

        assert meta.plan_id == "test-plan"
        assert meta.name == "Test Plan"
        assert meta.created_by == "tester"
        assert "test" in meta.tags
        assert meta.is_default == False

    def test_metadata_serialization(self):
        """Test PlanMetadata round-trip serialization."""
        meta = PlanMetadata(
            plan_id="test-plan",
            name="Test Plan",
            description="A test plan",
            tags=["test"],
        )

        data = plan_metadata_to_dict(meta)
        restored = plan_metadata_from_dict(data)

        assert restored.plan_id == meta.plan_id
        assert restored.name == meta.name
        assert restored.tags == meta.tags


# =============================================================================
# StoredPlan Tests
# =============================================================================


class TestStoredPlan:
    """Tests for StoredPlan dataclass."""

    def test_stored_plan_creation(self):
        """Test creating a stored plan."""
        plan = StoredPlan(
            metadata=PlanMetadata(
                plan_id="test-plan",
                name="Test Plan",
            ),
            spec=RunPlanSpec.default(),
        )

        assert plan.metadata.plan_id == "test-plan"
        assert len(plan.spec.flow_sequence) > 0

    def test_stored_plan_serialization(self):
        """Test StoredPlan round-trip serialization."""
        plan = StoredPlan(
            metadata=PlanMetadata(
                plan_id="test-plan",
                name="Test Plan",
                tags=["test"],
            ),
            spec=RunPlanSpec(
                flow_sequence=["signal", "build"],
                max_total_flows=10,
            ),
        )

        data = stored_plan_to_dict(plan)
        restored = stored_plan_from_dict(data)

        assert restored.metadata.plan_id == plan.metadata.plan_id
        assert restored.spec.flow_sequence == plan.spec.flow_sequence
        assert restored.spec.max_total_flows == plan.spec.max_total_flows


# =============================================================================
# RunPlanAPI Tests
# =============================================================================


class TestRunPlanAPI:
    """Tests for RunPlanAPI CRUD operations."""

    def test_api_creates_plans_directory(self, tmp_path: Path):
        """Test that API creates plans directory on init."""
        api = RunPlanAPI(tmp_path)
        plans_dir = tmp_path / "swarm" / "plans"
        assert plans_dir.exists()

    def test_api_creates_default_plans(self, tmp_path: Path):
        """Test that API creates default plans on init."""
        api = RunPlanAPI(tmp_path)
        plans = api.list_plans()

        # Should have the 4 default plans
        plan_ids = [p.plan_id for p in plans]
        assert "default-autopilot" in plan_ids
        assert "default-supervised" in plan_ids
        assert "build-only" in plan_ids
        assert "signal-to-gate" in plan_ids

    def test_create_plan(self, tmp_path: Path):
        """Test creating a new plan."""
        api = RunPlanAPI(tmp_path)

        plan = api.create_plan(
            plan_id="my-custom-plan",
            name="My Custom Plan",
            description="A custom test plan",
            flow_sequence=["signal", "build", "gate"],
            human_policy="autopilot",
            max_total_flows=15,
            tags=["custom", "test"],
        )

        assert plan.metadata.plan_id == "my-custom-plan"
        assert plan.metadata.name == "My Custom Plan"
        assert plan.spec.flow_sequence == ["signal", "build", "gate"]
        assert plan.spec.max_total_flows == 15
        assert plan.metadata.is_default == False

    def test_create_duplicate_plan_fails(self, tmp_path: Path):
        """Test that creating a duplicate plan raises error."""
        api = RunPlanAPI(tmp_path)

        api.create_plan(plan_id="unique-plan", name="Unique")

        with pytest.raises(ValueError, match="Plan already exists"):
            api.create_plan(plan_id="unique-plan", name="Duplicate")

    def test_load_plan(self, tmp_path: Path):
        """Test loading a plan by ID."""
        api = RunPlanAPI(tmp_path)

        # Load a default plan
        plan = api.load_plan("default-autopilot")

        assert plan is not None
        assert plan.metadata.plan_id == "default-autopilot"
        assert plan.metadata.is_default == True
        assert len(plan.spec.flow_sequence) == 6  # Full SDLC

    def test_load_nonexistent_plan(self, tmp_path: Path):
        """Test loading a plan that doesn't exist."""
        api = RunPlanAPI(tmp_path)
        plan = api.load_plan("nonexistent")
        assert plan is None

    def test_save_plan(self, tmp_path: Path):
        """Test saving/updating a plan."""
        api = RunPlanAPI(tmp_path)

        # Create a plan
        plan = api.create_plan(plan_id="update-test", name="Original")
        original_updated_at = plan.metadata.updated_at

        # Modify and save
        plan.spec.max_total_flows = 99
        import time
        time.sleep(0.01)  # Ensure timestamp difference
        api.save_plan(plan)

        # Reload and verify
        reloaded = api.load_plan("update-test")
        assert reloaded.spec.max_total_flows == 99
        assert reloaded.metadata.updated_at > original_updated_at

    def test_delete_plan(self, tmp_path: Path):
        """Test deleting a user plan."""
        api = RunPlanAPI(tmp_path)

        # Create and then delete
        api.create_plan(plan_id="delete-me", name="To Delete")
        assert api.load_plan("delete-me") is not None

        result = api.delete_plan("delete-me")
        assert result == True
        assert api.load_plan("delete-me") is None

    def test_cannot_delete_default_plan(self, tmp_path: Path):
        """Test that default plans cannot be deleted."""
        api = RunPlanAPI(tmp_path)

        result = api.delete_plan("default-autopilot")
        assert result == False
        assert api.load_plan("default-autopilot") is not None

    def test_list_plans(self, tmp_path: Path):
        """Test listing all plans."""
        api = RunPlanAPI(tmp_path)

        # Add some custom plans
        api.create_plan(plan_id="custom-1", name="Custom 1")
        api.create_plan(plan_id="custom-2", name="Custom 2")

        plans = api.list_plans()

        # Should have defaults + customs
        assert len(plans) >= 6

        # Default plans should be first (sorted by is_default desc, then name)
        default_plans = [p for p in plans if p.is_default]
        assert len(default_plans) == 4

    def test_clone_plan(self, tmp_path: Path):
        """Test cloning an existing plan."""
        api = RunPlanAPI(tmp_path)

        # Clone a default plan
        cloned = api.clone_plan(
            source_id="default-autopilot",
            new_id="my-autopilot-clone",
            new_name="My Autopilot Clone",
        )

        assert cloned is not None
        assert cloned.metadata.plan_id == "my-autopilot-clone"
        assert cloned.metadata.name == "My Autopilot Clone"
        assert cloned.metadata.is_default == False

        # Spec should match source
        original = api.load_plan("default-autopilot")
        assert cloned.spec.flow_sequence == original.spec.flow_sequence

    def test_clone_nonexistent_plan(self, tmp_path: Path):
        """Test cloning a plan that doesn't exist."""
        api = RunPlanAPI(tmp_path)
        result = api.clone_plan("nonexistent", "new-id")
        assert result is None

    def test_get_spec(self, tmp_path: Path):
        """Test getting just the spec from a plan."""
        api = RunPlanAPI(tmp_path)

        spec = api.get_spec("default-autopilot")

        assert spec is not None
        assert isinstance(spec, RunPlanSpec)
        assert len(spec.flow_sequence) == 6

    def test_validate_plan_valid(self, tmp_path: Path):
        """Test validating a valid plan."""
        api = RunPlanAPI(tmp_path)

        plan = StoredPlan(
            metadata=PlanMetadata(plan_id="valid", name="Valid"),
            spec=RunPlanSpec(
                flow_sequence=["signal", "build", "gate"],
                max_total_flows=20,
            ),
        )

        errors = api.validate_plan(plan)
        assert len(errors) == 0

    def test_validate_plan_invalid_flow(self, tmp_path: Path):
        """Test validating a plan with invalid flow."""
        api = RunPlanAPI(tmp_path)

        plan = StoredPlan(
            metadata=PlanMetadata(plan_id="invalid", name="Invalid"),
            spec=RunPlanSpec(
                flow_sequence=["signal", "unknown-flow", "build"],
                max_total_flows=20,
            ),
        )

        errors = api.validate_plan(plan)
        assert len(errors) > 0
        assert any("unknown-flow" in e for e in errors)

    def test_validate_plan_empty_sequence(self, tmp_path: Path):
        """Test validating a plan with empty sequence."""
        api = RunPlanAPI(tmp_path)

        plan = StoredPlan(
            metadata=PlanMetadata(plan_id="empty", name="Empty"),
            spec=RunPlanSpec(
                flow_sequence=[],
                max_total_flows=20,
            ),
        )

        errors = api.validate_plan(plan)
        assert len(errors) > 0
        assert any("empty" in e.lower() for e in errors)


# =============================================================================
# Convenience Function Tests
# =============================================================================


class TestConvenienceFunctions:
    """Tests for module-level convenience functions."""

    def test_create_run_plan_api(self, tmp_path: Path):
        """Test creating API via convenience function."""
        api = create_run_plan_api(tmp_path)
        assert isinstance(api, RunPlanAPI)

    def test_load_run_plan(self, tmp_path: Path):
        """Test loading plan via convenience function."""
        # First create the API to ensure defaults exist
        create_run_plan_api(tmp_path)

        spec = load_run_plan("default-autopilot", tmp_path)
        assert spec is not None
        assert isinstance(spec, RunPlanSpec)

    def test_list_run_plans(self, tmp_path: Path):
        """Test listing plans via convenience function."""
        # First create the API to ensure defaults exist
        create_run_plan_api(tmp_path)

        plans = list_run_plans(tmp_path)
        assert len(plans) >= 4


# =============================================================================
# Default Plan Tests
# =============================================================================


class TestDefaultPlans:
    """Tests for the default plans."""

    def test_default_autopilot_plan(self, tmp_path: Path):
        """Test default-autopilot plan configuration."""
        api = RunPlanAPI(tmp_path)
        plan = api.load_plan("default-autopilot")

        assert plan is not None
        assert plan.spec.flow_sequence == ["signal", "plan", "build", "gate", "deploy", "wisdom"]
        assert plan.spec.human_policy.mode == "run_end"
        assert plan.spec.max_total_flows == 20

    def test_default_supervised_plan(self, tmp_path: Path):
        """Test default-supervised plan configuration."""
        api = RunPlanAPI(tmp_path)
        plan = api.load_plan("default-supervised")

        assert plan is not None
        assert plan.spec.human_policy.mode == "per_flow"

    def test_build_only_plan(self, tmp_path: Path):
        """Test build-only plan configuration."""
        api = RunPlanAPI(tmp_path)
        plan = api.load_plan("build-only")

        assert plan is not None
        assert plan.spec.flow_sequence == ["build"]
        assert plan.spec.max_total_flows == 10

    def test_signal_to_gate_plan(self, tmp_path: Path):
        """Test signal-to-gate plan configuration."""
        api = RunPlanAPI(tmp_path)
        plan = api.load_plan("signal-to-gate")

        assert plan is not None
        assert plan.spec.flow_sequence == ["signal", "plan", "build", "gate"]
        assert "deploy" not in plan.spec.flow_sequence
