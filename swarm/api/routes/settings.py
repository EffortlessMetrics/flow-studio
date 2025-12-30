"""
Settings endpoints for Flow Studio API.

Provides REST endpoints for:
- Model policy management (GET/POST /api/settings/model-policy)
- Policy cache refresh (POST /api/settings/model-policy/reload)
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/settings", tags=["settings"])


# =============================================================================
# Pydantic Models
# =============================================================================


class UserPreferences(BaseModel):
    """User preferences for model policy."""

    primary_model: str = Field(
        default="sonnet",
        description="User's preferred model tier for 'primary' tier work (sonnet or opus)",
    )
    comment: Optional[str] = Field(
        default=None,
        description="Optional comment about the preference",
    )

    @field_validator("primary_model")
    @classmethod
    def validate_primary_model(cls, v: str) -> str:
        """Validate that primary_model is a valid tier."""
        valid_tiers = {"sonnet", "opus"}
        if v.lower() not in valid_tiers:
            raise ValueError(f"primary_model must be one of {valid_tiers}, got '{v}'")
        return v.lower()


class TierDefinitions(BaseModel):
    """Model tier definitions."""

    primary: str = Field(default="inherit_user_primary")
    economy: str = Field(default="haiku")
    standard: str = Field(default="sonnet")
    elite: str = Field(default="opus")
    edge: str = Field(default="sonnet")


class GroupAssignments(BaseModel):
    """Category to tier group assignments."""

    shaping: str = Field(default="economy")
    spec: str = Field(default="standard")
    design: str = Field(default="primary")
    implementation: str = Field(default="primary")
    critic: str = Field(default="edge")
    verification: str = Field(default="economy")
    analytics: str = Field(default="standard")
    reporter: str = Field(default="economy")
    infra: str = Field(default="economy")
    router: str = Field(default="primary")
    wisdom: str = Field(default="elite")


class ModelPolicyResponse(BaseModel):
    """Response for GET /api/settings/model-policy."""

    user_preferences: Dict[str, Any]
    tiers: Dict[str, str]
    group_assignments: Dict[str, str]
    version: int = Field(default=1)
    description: Optional[str] = None
    tier_descriptions: Optional[Dict[str, str]] = None
    upgrade_notes: Optional[Dict[str, str]] = None


class ModelPolicyUpdateRequest(BaseModel):
    """Request for POST /api/settings/model-policy."""

    user_preferences: Optional[UserPreferences] = None
    tiers: Optional[Dict[str, str]] = None
    group_assignments: Optional[Dict[str, str]] = None

    @field_validator("tiers")
    @classmethod
    def validate_tiers(cls, v: Optional[Dict[str, str]]) -> Optional[Dict[str, str]]:
        """Validate tier values are valid aliases or special tokens."""
        if v is None:
            return v
        valid_values = {"haiku", "sonnet", "opus", "inherit_user_primary"}
        for tier_name, tier_value in v.items():
            if tier_value.lower() not in valid_values:
                raise ValueError(
                    f"Tier '{tier_name}' has invalid value '{tier_value}'. "
                    f"Must be one of {valid_values}"
                )
        return {k: v.lower() for k, v in v.items()}

    @field_validator("group_assignments")
    @classmethod
    def validate_group_assignments(
        cls, v: Optional[Dict[str, str]]
    ) -> Optional[Dict[str, str]]:
        """Validate group assignments reference valid tier names."""
        if v is None:
            return v
        # Valid tier names that can be assigned
        valid_tier_names = {"primary", "economy", "standard", "elite", "edge"}
        for group, tier_name in v.items():
            if tier_name.lower() not in valid_tier_names:
                raise ValueError(
                    f"Group '{group}' assigned to invalid tier '{tier_name}'. "
                    f"Must be one of {valid_tier_names}"
                )
        return {k: v.lower() for k, v in v.items()}


class ModelPolicyReloadResponse(BaseModel):
    """Response for POST /api/settings/model-policy/reload."""

    success: bool
    message: str
    policy: Optional[ModelPolicyResponse] = None


# =============================================================================
# Helper Functions
# =============================================================================


def _get_policy_path() -> Path:
    """Get the path to model_policy.json."""
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / ".git").exists():
            return parent / "swarm" / "config" / "model_policy.json"
    raise RuntimeError("Could not find repository root")


def _load_policy_raw() -> Dict[str, Any]:
    """Load the raw policy JSON from disk."""
    policy_path = _get_policy_path()
    if policy_path.exists():
        with open(policy_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_policy_raw(policy: Dict[str, Any]) -> None:
    """Save the policy JSON to disk."""
    policy_path = _get_policy_path()
    with open(policy_path, "w", encoding="utf-8") as f:
        json.dump(policy, f, indent=2)
        f.write("\n")  # Add trailing newline


# =============================================================================
# Endpoints
# =============================================================================


@router.get("/model-policy", response_model=ModelPolicyResponse)
async def get_model_policy():
    """Get the current model policy configuration.

    Returns the user preferences, tier definitions, and group assignments
    that control model allocation across station categories.

    Returns:
        ModelPolicyResponse with current policy settings.

    Raises:
        500: If policy file cannot be read.
    """
    try:
        raw = _load_policy_raw()

        return ModelPolicyResponse(
            user_preferences=raw.get("user_preferences", {"primary_model": "sonnet"}),
            tiers=raw.get(
                "tiers",
                {
                    "primary": "inherit_user_primary",
                    "economy": "haiku",
                    "standard": "sonnet",
                    "elite": "opus",
                    "edge": "sonnet",
                },
            ),
            group_assignments=raw.get(
                "group_assignments",
                {
                    "shaping": "economy",
                    "spec": "standard",
                    "design": "primary",
                    "implementation": "primary",
                    "critic": "edge",
                    "verification": "economy",
                    "analytics": "standard",
                    "reporter": "economy",
                    "infra": "economy",
                    "router": "primary",
                    "wisdom": "elite",
                },
            ),
            version=raw.get("version", 1),
            description=raw.get("description"),
            tier_descriptions=raw.get("tier_descriptions"),
            upgrade_notes=raw.get("upgrade_notes"),
        )

    except Exception as e:
        logger.error("Failed to load model policy: %s", e, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "error": "policy_read_error",
                "message": f"Failed to load model policy: {str(e)}",
                "details": {},
            },
        )


@router.post("/model-policy", response_model=ModelPolicyResponse)
async def update_model_policy(request: ModelPolicyUpdateRequest):
    """Update the model policy configuration.

    Merges the provided updates with the existing policy. Only fields
    that are provided will be updated; other fields are preserved.

    Args:
        request: Partial policy update with user_preferences, tiers,
            and/or group_assignments.

    Returns:
        Updated ModelPolicyResponse with new policy settings.

    Raises:
        400: If validation fails.
        500: If policy file cannot be written.
    """
    try:
        # Load existing policy
        existing = _load_policy_raw()

        # Merge updates
        if request.user_preferences is not None:
            existing_prefs = existing.get("user_preferences", {})
            update_prefs = request.user_preferences.model_dump(exclude_none=True)
            existing["user_preferences"] = {**existing_prefs, **update_prefs}

        if request.tiers is not None:
            existing_tiers = existing.get("tiers", {})
            existing["tiers"] = {**existing_tiers, **request.tiers}

        if request.group_assignments is not None:
            existing_groups = existing.get("group_assignments", {})
            existing["group_assignments"] = {**existing_groups, **request.group_assignments}

        # Save updated policy
        _save_policy_raw(existing)

        # Clear the model_registry cache so changes take effect
        try:
            from swarm.config.model_registry import _load_policy_from_disk

            _load_policy_from_disk.cache_clear()
        except Exception as cache_err:
            logger.warning("Could not clear policy cache: %s", cache_err)

        # Return updated policy
        return ModelPolicyResponse(
            user_preferences=existing.get("user_preferences", {"primary_model": "sonnet"}),
            tiers=existing.get(
                "tiers",
                {
                    "primary": "inherit_user_primary",
                    "economy": "haiku",
                    "standard": "sonnet",
                    "elite": "opus",
                    "edge": "sonnet",
                },
            ),
            group_assignments=existing.get(
                "group_assignments",
                {
                    "shaping": "economy",
                    "spec": "standard",
                    "design": "primary",
                    "implementation": "primary",
                    "critic": "edge",
                    "verification": "economy",
                    "analytics": "standard",
                    "reporter": "economy",
                    "infra": "economy",
                    "router": "primary",
                    "wisdom": "elite",
                },
            ),
            version=existing.get("version", 1),
            description=existing.get("description"),
            tier_descriptions=existing.get("tier_descriptions"),
            upgrade_notes=existing.get("upgrade_notes"),
        )

    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "validation_error",
                "message": str(e),
                "details": {},
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to update model policy: %s", e, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "error": "policy_write_error",
                "message": f"Failed to update model policy: {str(e)}",
                "details": {},
            },
        )


@router.post("/model-policy/reload", response_model=ModelPolicyReloadResponse)
async def reload_model_policy():
    """Force reload of the model policy from disk.

    Clears the policy cache and reloads from model_policy.json.
    Use this after external modifications to the policy file.

    Returns:
        ModelPolicyReloadResponse with success status and reloaded policy.

    Raises:
        500: If reload fails.
    """
    try:
        # Clear the cache
        from swarm.config.model_registry import _load_policy_from_disk, load_model_policy

        _load_policy_from_disk.cache_clear()

        # Reload and return
        policy = load_model_policy()

        # Get the full raw policy for response
        raw = _load_policy_raw()

        return ModelPolicyReloadResponse(
            success=True,
            message="Model policy reloaded successfully",
            policy=ModelPolicyResponse(
                user_preferences=raw.get("user_preferences", {"primary_model": "sonnet"}),
                tiers=raw.get(
                    "tiers",
                    {
                        "primary": "inherit_user_primary",
                        "economy": "haiku",
                        "standard": "sonnet",
                        "elite": "opus",
                        "edge": "sonnet",
                    },
                ),
                group_assignments=raw.get(
                    "group_assignments",
                    {
                        "shaping": "economy",
                        "spec": "standard",
                        "design": "primary",
                        "implementation": "primary",
                        "critic": "edge",
                        "verification": "economy",
                        "analytics": "standard",
                        "reporter": "economy",
                        "infra": "economy",
                        "router": "primary",
                        "wisdom": "elite",
                    },
                ),
                version=raw.get("version", 1),
                description=raw.get("description"),
                tier_descriptions=raw.get("tier_descriptions"),
                upgrade_notes=raw.get("upgrade_notes"),
            ),
        )

    except Exception as e:
        logger.error("Failed to reload model policy: %s", e, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "error": "policy_reload_error",
                "message": f"Failed to reload model policy: {str(e)}",
                "details": {},
            },
        )
