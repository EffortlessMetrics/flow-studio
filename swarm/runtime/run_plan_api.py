"""
run_plan_api.py - CRUD API for RunPlanSpec management.

This module provides a persistent API for managing run plans:
- Create new run plans with custom flow sequences and policies
- Load/save plans to disk (YAML format)
- List available plans
- Clone and modify existing plans
- Validate plans before execution

Plans are stored in: swarm/plans/<plan_id>.yaml

Usage:
    from swarm.runtime.run_plan_api import (
        RunPlanAPI,
        create_run_plan,
        load_run_plan,
        list_run_plans,
    )

    # Create API instance
    api = RunPlanAPI(repo_root)

    # Create a new plan
    plan = api.create_plan(
        plan_id="my-autopilot",
        flow_sequence=["signal", "plan", "build", "gate"],
        human_policy="autopilot",
    )

    # Load existing plan
    plan = api.load_plan("my-autopilot")

    # List all plans
    plans = api.list_plans()
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from .types import (
    HumanPolicy,
    MacroAction,
    MacroPolicy,
    RunPlanSpec,
    run_plan_spec_from_dict,
    run_plan_spec_to_dict,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Plan Metadata
# =============================================================================


@dataclass
class PlanMetadata:
    """Metadata for a stored run plan.

    Attributes:
        plan_id: Unique identifier for the plan.
        name: Human-readable name.
        description: What this plan does.
        created_at: When the plan was created.
        updated_at: When the plan was last modified.
        created_by: Who created the plan (user/system).
        tags: Tags for filtering/search.
        is_default: Whether this is a system default plan.
    """

    plan_id: str
    name: str
    description: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    created_by: str = "system"
    tags: List[str] = field(default_factory=list)
    is_default: bool = False


def plan_metadata_to_dict(meta: PlanMetadata) -> Dict[str, Any]:
    """Convert PlanMetadata to dictionary."""
    return {
        "plan_id": meta.plan_id,
        "name": meta.name,
        "description": meta.description,
        "created_at": meta.created_at.isoformat(),
        "updated_at": meta.updated_at.isoformat(),
        "created_by": meta.created_by,
        "tags": list(meta.tags),
        "is_default": meta.is_default,
    }


def plan_metadata_from_dict(data: Dict[str, Any]) -> PlanMetadata:
    """Parse PlanMetadata from dictionary."""
    created_at = data.get("created_at")
    if isinstance(created_at, str):
        created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    else:
        created_at = datetime.now(timezone.utc)

    updated_at = data.get("updated_at")
    if isinstance(updated_at, str):
        updated_at = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
    else:
        updated_at = datetime.now(timezone.utc)

    return PlanMetadata(
        plan_id=data.get("plan_id", ""),
        name=data.get("name", ""),
        description=data.get("description", ""),
        created_at=created_at,
        updated_at=updated_at,
        created_by=data.get("created_by", "system"),
        tags=list(data.get("tags", [])),
        is_default=data.get("is_default", False),
    )


# =============================================================================
# Stored Plan
# =============================================================================


@dataclass
class StoredPlan:
    """A run plan with metadata for storage.

    Attributes:
        metadata: Plan metadata (id, name, timestamps).
        spec: The actual RunPlanSpec.
    """

    metadata: PlanMetadata
    spec: RunPlanSpec


def stored_plan_to_dict(plan: StoredPlan) -> Dict[str, Any]:
    """Convert StoredPlan to dictionary for YAML serialization."""
    return {
        "metadata": plan_metadata_to_dict(plan.metadata),
        "spec": run_plan_spec_to_dict(plan.spec),
    }


def stored_plan_from_dict(data: Dict[str, Any]) -> StoredPlan:
    """Parse StoredPlan from dictionary."""
    return StoredPlan(
        metadata=plan_metadata_from_dict(data.get("metadata", {})),
        spec=run_plan_spec_from_dict(data.get("spec", {})),
    )


# =============================================================================
# Default Plans
# =============================================================================


def create_default_autopilot_plan() -> StoredPlan:
    """Create the default autopilot plan (no human intervention)."""
    return StoredPlan(
        metadata=PlanMetadata(
            plan_id="default-autopilot",
            name="Default Autopilot",
            description="Full SDLC flow with no human intervention until completion",
            created_by="system",
            tags=["default", "autopilot", "full-sdlc"],
            is_default=True,
        ),
        spec=RunPlanSpec(
            flow_sequence=["signal", "plan", "build", "gate", "deploy", "wisdom"],
            macro_policy=MacroPolicy.default(),
            human_policy=HumanPolicy.autopilot(),
            constraints=[
                "never deploy unless gate verdict is MERGE or MERGE_WITH_CONDITIONS",
                "never skip gate flow",
                "max 3 bounces between gate and build",
            ],
            max_total_flows=20,
        ),
    )


def create_default_supervised_plan() -> StoredPlan:
    """Create the default supervised plan (human review after each flow)."""
    return StoredPlan(
        metadata=PlanMetadata(
            plan_id="default-supervised",
            name="Default Supervised",
            description="Full SDLC flow with human review after each flow",
            created_by="system",
            tags=["default", "supervised", "full-sdlc"],
            is_default=True,
        ),
        spec=RunPlanSpec(
            flow_sequence=["signal", "plan", "build", "gate", "deploy", "wisdom"],
            macro_policy=MacroPolicy.default(),
            human_policy=HumanPolicy.supervised(),
            constraints=[
                "never deploy unless gate verdict is MERGE or MERGE_WITH_CONDITIONS",
                "never skip gate flow",
            ],
            max_total_flows=20,
        ),
    )


def create_build_only_plan() -> StoredPlan:
    """Create a plan that only runs the build flow."""
    return StoredPlan(
        metadata=PlanMetadata(
            plan_id="build-only",
            name="Build Only",
            description="Run only the build flow (for incremental development)",
            created_by="system",
            tags=["default", "build", "incremental"],
            is_default=True,
        ),
        spec=RunPlanSpec(
            flow_sequence=["build"],
            macro_policy=MacroPolicy(
                allow_flow_repeat=True,
                max_repeats_per_flow=5,
                routing_rules=[],
                default_action=MacroAction.TERMINATE,
            ),
            human_policy=HumanPolicy.autopilot(),
            constraints=[],
            max_total_flows=10,
        ),
    )


def create_signal_to_gate_plan() -> StoredPlan:
    """Create a plan that runs signal through gate (no deploy)."""
    return StoredPlan(
        metadata=PlanMetadata(
            plan_id="signal-to-gate",
            name="Signal to Gate",
            description="Run signal through gate, stop before deploy",
            created_by="system",
            tags=["default", "pre-deploy", "review"],
            is_default=True,
        ),
        spec=RunPlanSpec(
            flow_sequence=["signal", "plan", "build", "gate"],
            macro_policy=MacroPolicy.default(),
            human_policy=HumanPolicy.autopilot(),
            constraints=[
                "max 3 bounces between gate and build",
            ],
            max_total_flows=15,
        ),
    )


DEFAULT_PLANS = [
    create_default_autopilot_plan,
    create_default_supervised_plan,
    create_build_only_plan,
    create_signal_to_gate_plan,
]


# =============================================================================
# RunPlanAPI
# =============================================================================


class RunPlanAPI:
    """CRUD API for RunPlanSpec management.

    Provides persistent storage and retrieval of run plans with
    validation and default plan support.

    Plans are stored in: {repo_root}/swarm/plans/<plan_id>.yaml

    Usage:
        api = RunPlanAPI(repo_root)

        # Create a new plan
        plan = api.create_plan(
            plan_id="my-plan",
            name="My Custom Plan",
            flow_sequence=["signal", "build"],
        )

        # Load and modify
        plan = api.load_plan("my-plan")
        plan.spec.max_total_flows = 30
        api.save_plan(plan)

        # List all plans
        for meta in api.list_plans():
            print(meta.plan_id, meta.name)
    """

    def __init__(self, repo_root: Path):
        """Initialize the API.

        Args:
            repo_root: Repository root path.
        """
        self._repo_root = repo_root
        self._plans_dir = repo_root / "swarm" / "plans"
        self._cache: Dict[str, StoredPlan] = {}

        # Ensure plans directory exists
        self._plans_dir.mkdir(parents=True, exist_ok=True)

        # Initialize default plans if they don't exist
        self._ensure_default_plans()

    def _ensure_default_plans(self) -> None:
        """Ensure default plans exist on disk."""
        for plan_factory in DEFAULT_PLANS:
            plan = plan_factory()
            plan_path = self._plans_dir / f"{plan.metadata.plan_id}.yaml"
            if not plan_path.exists():
                self._write_plan(plan)
                logger.info("Created default plan: %s", plan.metadata.plan_id)

    def _plan_path(self, plan_id: str) -> Path:
        """Get the file path for a plan."""
        return self._plans_dir / f"{plan_id}.yaml"

    def _write_plan(self, plan: StoredPlan) -> None:
        """Write a plan to disk."""
        plan_path = self._plan_path(plan.metadata.plan_id)
        data = stored_plan_to_dict(plan)

        with open(plan_path, "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)

        # Update cache
        self._cache[plan.metadata.plan_id] = plan

    def _read_plan(self, plan_id: str) -> Optional[StoredPlan]:
        """Read a plan from disk."""
        plan_path = self._plan_path(plan_id)

        if not plan_path.exists():
            return None

        try:
            with open(plan_path, "r") as f:
                data = yaml.safe_load(f)

            plan = stored_plan_from_dict(data)
            self._cache[plan_id] = plan
            return plan
        except Exception as e:
            logger.warning("Failed to load plan %s: %s", plan_id, e)
            return None

    def create_plan(
        self,
        plan_id: str,
        name: Optional[str] = None,
        description: str = "",
        flow_sequence: Optional[List[str]] = None,
        human_policy: str = "autopilot",  # "autopilot" or "supervised"
        max_total_flows: int = 20,
        constraints: Optional[List[str]] = None,
        tags: Optional[List[str]] = None,
    ) -> StoredPlan:
        """Create a new run plan.

        Args:
            plan_id: Unique identifier for the plan.
            name: Human-readable name (defaults to plan_id).
            description: Plan description.
            flow_sequence: List of flow keys to execute.
            human_policy: "autopilot" or "supervised".
            max_total_flows: Maximum flow executions allowed.
            constraints: List of constraint strings.
            tags: Tags for categorization.

        Returns:
            The created StoredPlan.

        Raises:
            ValueError: If plan_id already exists.
        """
        if self._plan_path(plan_id).exists():
            raise ValueError(f"Plan already exists: {plan_id}")

        # Build the spec
        hp = HumanPolicy.autopilot() if human_policy == "autopilot" else HumanPolicy.supervised()

        spec = RunPlanSpec(
            flow_sequence=flow_sequence or ["signal", "plan", "build", "gate", "deploy", "wisdom"],
            macro_policy=MacroPolicy.default(),
            human_policy=hp,
            constraints=constraints or [],
            max_total_flows=max_total_flows,
        )

        plan = StoredPlan(
            metadata=PlanMetadata(
                plan_id=plan_id,
                name=name or plan_id,
                description=description,
                created_by="user",
                tags=tags or [],
                is_default=False,
            ),
            spec=spec,
        )

        self._write_plan(plan)
        logger.info("Created plan: %s", plan_id)

        return plan

    def load_plan(self, plan_id: str) -> Optional[StoredPlan]:
        """Load a plan by ID.

        Args:
            plan_id: The plan identifier.

        Returns:
            StoredPlan if found, None otherwise.
        """
        # Check cache first
        if plan_id in self._cache:
            return self._cache[plan_id]

        return self._read_plan(plan_id)

    def save_plan(self, plan: StoredPlan) -> None:
        """Save a plan (create or update).

        Args:
            plan: The plan to save.
        """
        plan.metadata.updated_at = datetime.now(timezone.utc)
        self._write_plan(plan)
        logger.info("Saved plan: %s", plan.metadata.plan_id)

    def delete_plan(self, plan_id: str) -> bool:
        """Delete a plan.

        Args:
            plan_id: The plan to delete.

        Returns:
            True if deleted, False if not found.
        """
        plan_path = self._plan_path(plan_id)

        if not plan_path.exists():
            return False

        # Don't allow deleting default plans
        plan = self.load_plan(plan_id)
        if plan and plan.metadata.is_default:
            logger.warning("Cannot delete default plan: %s", plan_id)
            return False

        plan_path.unlink()
        self._cache.pop(plan_id, None)
        logger.info("Deleted plan: %s", plan_id)

        return True

    def list_plans(self) -> List[PlanMetadata]:
        """List all available plans.

        Returns:
            List of plan metadata (not full specs, for efficiency).
        """
        plans = []

        for plan_path in self._plans_dir.glob("*.yaml"):
            plan_id = plan_path.stem
            plan = self.load_plan(plan_id)
            if plan:
                plans.append(plan.metadata)

        # Sort: defaults first, then by name
        plans.sort(key=lambda m: (not m.is_default, m.name))

        return plans

    def clone_plan(
        self,
        source_id: str,
        new_id: str,
        new_name: Optional[str] = None,
    ) -> Optional[StoredPlan]:
        """Clone an existing plan with a new ID.

        Args:
            source_id: ID of the plan to clone.
            new_id: ID for the new plan.
            new_name: Optional new name (defaults to "Copy of {source_name}").

        Returns:
            The cloned plan, or None if source not found.
        """
        source = self.load_plan(source_id)
        if source is None:
            return None

        if self._plan_path(new_id).exists():
            raise ValueError(f"Plan already exists: {new_id}")

        # Deep copy the spec
        import copy

        new_spec = copy.deepcopy(source.spec)

        new_plan = StoredPlan(
            metadata=PlanMetadata(
                plan_id=new_id,
                name=new_name or f"Copy of {source.metadata.name}",
                description=source.metadata.description,
                created_by="user",
                tags=list(source.metadata.tags),
                is_default=False,
            ),
            spec=new_spec,
        )

        self._write_plan(new_plan)
        logger.info("Cloned plan %s to %s", source_id, new_id)

        return new_plan

    def get_spec(self, plan_id: str) -> Optional[RunPlanSpec]:
        """Get just the RunPlanSpec for a plan.

        Convenience method for when you only need the spec.

        Args:
            plan_id: The plan identifier.

        Returns:
            RunPlanSpec if found, None otherwise.
        """
        plan = self.load_plan(plan_id)
        return plan.spec if plan else None

    def validate_plan(self, plan: StoredPlan) -> List[str]:
        """Validate a plan for correctness.

        Args:
            plan: The plan to validate.

        Returns:
            List of validation errors (empty if valid).
        """
        errors = []

        # Check flow sequence
        valid_flows = {"signal", "plan", "build", "gate", "deploy", "wisdom"}
        for flow in plan.spec.flow_sequence:
            if flow not in valid_flows:
                errors.append(f"Unknown flow in sequence: {flow}")

        # Check for empty sequence
        if not plan.spec.flow_sequence:
            errors.append("Flow sequence cannot be empty")

        # Check max_total_flows
        if plan.spec.max_total_flows < 1:
            errors.append("max_total_flows must be at least 1")

        if plan.spec.max_total_flows > 100:
            errors.append("max_total_flows exceeds maximum (100)")

        # Check routing rules
        for rule in plan.spec.macro_policy.routing_rules:
            if rule.max_uses < 1:
                errors.append(f"Rule {rule.rule_id} has invalid max_uses")

        return errors


# =============================================================================
# Convenience Functions
# =============================================================================


def create_run_plan_api(repo_root: Optional[Path] = None) -> RunPlanAPI:
    """Create a RunPlanAPI instance.

    Args:
        repo_root: Repository root. If None, uses current directory.

    Returns:
        Configured RunPlanAPI instance.
    """
    if repo_root is None:
        repo_root = Path.cwd()

    return RunPlanAPI(repo_root)


def load_run_plan(plan_id: str, repo_root: Optional[Path] = None) -> Optional[RunPlanSpec]:
    """Load a run plan spec by ID.

    Convenience function for quick plan loading.

    Args:
        plan_id: The plan identifier.
        repo_root: Repository root.

    Returns:
        RunPlanSpec if found, None otherwise.
    """
    api = create_run_plan_api(repo_root)
    return api.get_spec(plan_id)


def list_run_plans(repo_root: Optional[Path] = None) -> List[PlanMetadata]:
    """List all available run plans.

    Args:
        repo_root: Repository root.

    Returns:
        List of plan metadata.
    """
    api = create_run_plan_api(repo_root)
    return api.list_plans()


__all__ = [
    "RunPlanAPI",
    "StoredPlan",
    "PlanMetadata",
    "create_run_plan_api",
    "load_run_plan",
    "list_run_plans",
    "stored_plan_to_dict",
    "stored_plan_from_dict",
    "plan_metadata_to_dict",
    "plan_metadata_from_dict",
]
