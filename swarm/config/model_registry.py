"""Model context window registry for budget computation and policy-based allocation.

Provides:
1. Context window sizes for known models (fraction-based budget computation)
2. Model tier aliases (haiku, sonnet, opus) as canonical SDK values
3. Group-based model policy (category → tier via user-configurable policy)
4. Model resolution for StationSpecs (inherit → resolved tier alias)

The model policy system uses tier aliases (haiku, sonnet, opus) as the canonical
output, not full model IDs. This allows the SDK to handle version tracking and
ensures automatic upgrades when new model versions are released.

For determinism in specific runs, set environment variables:
- ANTHROPIC_DEFAULT_HAIKU_MODEL
- ANTHROPIC_DEFAULT_SONNET_MODEL
- ANTHROPIC_DEFAULT_OPUS_MODEL
"""

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Dict, Optional, Literal
import json

# Type aliases for clarity
ModelTier = Literal["haiku", "sonnet", "opus", "inherit"]
StationCategory = Literal["shaping", "spec", "design", "implementation",
                          "critic", "verification", "analytics", "reporter",
                          "infra", "router", "wisdom"]

# Valid tier aliases that the SDK accepts
VALID_TIERS = frozenset(["haiku", "sonnet", "opus"])

# Policy file location
_POLICY_PATH = Path(__file__).parent / "model_policy.json"


@dataclass
class ModelSpec:
    """Specification for a model's context window."""
    model_id: str
    context_tokens: int
    description: str = ""

    @property
    def context_chars(self) -> int:
        """Approximate character count (4 chars per token)."""
        return self.context_tokens * 4


@dataclass
class BudgetFractions:
    """Fraction-based budget configuration."""
    history_total: float = 0.25      # 25% of window
    history_recent: float = 0.075    # 7.5% for recent step
    history_older: float = 0.025     # 2.5% per older step


# Built-in model specs
BUILTIN_MODELS: Dict[str, ModelSpec] = {
    "claude-sonnet-4-5-20250929": ModelSpec("claude-sonnet-4-5-20250929", 200000, "Claude Sonnet 4.5"),
    "claude-haiku-4-5-20251001": ModelSpec("claude-haiku-4-5-20251001", 200000, "Claude Haiku 4.5"),
    "claude-opus-4-5-20251101": ModelSpec("claude-opus-4-5-20251101", 200000, "Claude Opus 4.5"),
    "gemini-3-pro-preview": ModelSpec("gemini-3-pro-preview", 1048576, "Gemini 3 Pro"),
    "gemini-3-flash-preview": ModelSpec("gemini-3-flash-preview", 1048576, "Gemini 3 Flash"),
}

DEFAULT_FRACTIONS = BudgetFractions()


def get_model_spec(model_id: str) -> Optional[ModelSpec]:
    """Get model spec by ID."""
    return BUILTIN_MODELS.get(model_id)


def get_model_context_tokens(model_id: str, default: int = 200000) -> int:
    """Get context window size in tokens for a model."""
    model = get_model_spec(model_id)
    return model.context_tokens if model else default


def compute_model_budgets(
    model_id: str,
    fractions: Optional[BudgetFractions] = None,
) -> Dict[str, int]:
    """Compute budget values for a model ID using fractions.

    Args:
        model_id: Model identifier
        fractions: Optional custom fractions, defaults to DEFAULT_FRACTIONS

    Returns:
        Dict with context_budget_chars, history_max_recent_chars,
        history_max_older_chars computed from model window.
    """
    model = get_model_spec(model_id)
    if not model:
        # Fallback to hardcoded defaults for unknown models
        return {
            "context_budget_chars": 200000,
            "history_max_recent_chars": 60000,
            "history_max_older_chars": 10000,
        }

    f = fractions or DEFAULT_FRACTIONS
    context_chars = model.context_chars

    return {
        "context_budget_chars": int(context_chars * f.history_total),
        "history_max_recent_chars": int(context_chars * f.history_recent),
        "history_max_older_chars": int(context_chars * f.history_older),
    }


def list_known_models() -> Dict[str, ModelSpec]:
    """Return all known model specs."""
    return dict(BUILTIN_MODELS)


# =============================================================================
# Model Policy System
# =============================================================================

@dataclass
class ModelPolicy:
    """Loaded model policy configuration."""
    user_primary: str  # User's preferred model (sonnet or opus)
    tiers: Dict[str, str]  # tier_name → resolved_alias
    group_assignments: Dict[str, str]  # category → tier_name


@lru_cache(maxsize=1)
def _load_policy_from_disk() -> dict:
    """Load the raw policy JSON from disk (cached)."""
    if _POLICY_PATH.exists():
        with open(_POLICY_PATH, 'r') as f:
            return json.load(f)
    return {}


def load_model_policy() -> ModelPolicy:
    """Load the model policy configuration.

    Returns:
        ModelPolicy with user preferences and group assignments.
        Falls back to sensible defaults if policy file is missing.
    """
    raw = _load_policy_from_disk()

    # Extract user preferences
    user_prefs = raw.get("user_preferences", {})
    user_primary = user_prefs.get("primary_model", "sonnet")

    # Extract tier mappings
    tiers = raw.get("tiers", {
        "primary": "inherit_user_primary",
        "economy": "haiku",
        "standard": "sonnet",
        "elite": "opus",
        "edge": "sonnet"
    })

    # Extract group assignments
    group_assignments = raw.get("group_assignments", {
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
        "wisdom": "elite"
    })

    return ModelPolicy(
        user_primary=user_primary,
        tiers=tiers,
        group_assignments=group_assignments
    )


def reload_model_policy() -> ModelPolicy:
    """Force reload of model policy from disk.

    Use this after modifying model_policy.json programmatically.
    """
    _load_policy_from_disk.cache_clear()
    return load_model_policy()


def resolve_tier_alias(tier_name: str, policy: Optional[ModelPolicy] = None) -> str:
    """Resolve a tier name to a canonical SDK alias.

    Args:
        tier_name: Tier name from policy (primary, economy, standard, elite, edge)
        policy: Optional pre-loaded policy, will load if not provided

    Returns:
        Canonical tier alias (haiku, sonnet, or opus)
    """
    if policy is None:
        policy = load_model_policy()

    # Get the tier definition
    tier_def = policy.tiers.get(tier_name, tier_name)

    # Handle user primary resolution
    if tier_def == "inherit_user_primary":
        return policy.user_primary

    # If it's already a valid tier, return it
    if tier_def in VALID_TIERS:
        return tier_def

    # Fallback to sonnet for unknown tiers
    return "sonnet"


# =============================================================================
# Model Tier Mapping (for backward compatibility with context budget computation)
# =============================================================================

# Short tier names map to specific model IDs (used for context budget computation)
# Note: For SDK calls, prefer tier aliases directly. This mapping is for internal use.
MODEL_TIER_MAPPING: Dict[str, str] = {
    # Claude tiers - used for context window lookups
    "haiku": "claude-haiku-4-5-20251001",
    "sonnet": "claude-sonnet-4-5-20250929",
    "opus": "claude-opus-4-5-20251101",
    # Full model IDs pass through (validation happens at SDK level)
}


def resolve_model_tier(model_value: str) -> str:
    """Resolve a model tier name to a full model ID.

    DEPRECATED: For SDK calls, use tier aliases directly (haiku, sonnet, opus).
    This function is kept for backward compatibility with context budget computation.

    Args:
        model_value: Either a tier name (haiku, sonnet, opus) or a full model ID.

    Returns:
        Full model ID string suitable for context budget lookup.

    Examples:
        >>> resolve_model_tier("sonnet")
        'claude-sonnet-4-20250514'
        >>> resolve_model_tier("claude-3-opus-20240229")
        'claude-3-opus-20240229'
    """
    return MODEL_TIER_MAPPING.get(model_value.lower(), model_value)


# =============================================================================
# Station Class Model Defaults
# =============================================================================

# Each station category has a default model tier
# These defaults are used when a station's model is "inherit"
STATION_CLASS_DEFAULTS: Dict[str, str] = {
    # Curator-class stations (fast, low-stakes work)
    "shaping": "haiku",      # Signal normalization, problem framing
    "reporter": "haiku",     # Report generation, summaries

    # Worker-class stations (main implementation work)
    "spec": "sonnet",        # Requirements authoring
    "design": "sonnet",      # ADR, interface design
    "implementation": "sonnet",  # Code/test writing

    # Critic-class stations (verification, review)
    "critic": "sonnet",      # Code/test critique
    "verification": "sonnet", # Gate checks, contract enforcement

    # Navigator-class stations (routing decisions)
    "router": "sonnet",      # Routing resolution

    # Analytics-class stations (wisdom, learning)
    "analytics": "sonnet",   # Pattern analysis, regression detection

    # Infra-class stations (git, CI operations)
    "infra": "haiku",        # Mechanical operations
}


def get_station_class_default(category: str) -> str:
    """Get the default model tier for a station category.

    Uses the policy system to resolve category → tier.

    Args:
        category: Station category from StationSpec.category.

    Returns:
        Model tier alias (haiku, sonnet, or opus).

    Examples:
        >>> get_station_class_default("implementation")
        'sonnet'
        >>> get_station_class_default("shaping")
        'haiku'
    """
    # First check static defaults for backward compatibility
    static_default = STATION_CLASS_DEFAULTS.get(category.lower())

    # Then use policy system for group-based resolution
    policy = load_model_policy()
    tier_name = policy.group_assignments.get(category.lower())

    if tier_name:
        return resolve_tier_alias(tier_name, policy)

    # Fallback to static defaults
    return static_default or "sonnet"


def resolve_station_model(
    model_value: str,
    category: Optional[str] = None,
    *,
    return_tier_alias: bool = True
) -> str:
    """Resolve a station's model specification to a tier alias or full model ID.

    This is the main entry point for model resolution in the SpecCompiler.
    It handles:
    1. "inherit" → looks up category via policy → returns tier alias
    2. tier names (haiku/sonnet/opus) → returns as-is (SDK handles versioning)
    3. full model IDs → pass through unchanged (escape hatch for pinning)

    Args:
        model_value: Model value from StationSpec.sdk.model.
        category: Station category (required for "inherit" resolution).
        return_tier_alias: If True (default), return tier aliases for SDK.
            If False, resolve to full model IDs (for context budget computation).

    Returns:
        Model identifier suitable for SDK calls (tier alias by default).

    Raises:
        ValueError: If model_value is "inherit" but no category provided.

    Examples:
        >>> resolve_station_model("inherit", "implementation")
        'sonnet'
        >>> resolve_station_model("haiku", "implementation")
        'haiku'
        >>> resolve_station_model("claude-3-opus-20240229")
        'claude-3-opus-20240229'
        >>> resolve_station_model("inherit", "implementation", return_tier_alias=False)
        'claude-sonnet-4-20250514'
    """
    model_lower = model_value.lower()

    # Handle "inherit" by looking up category via policy
    if model_lower == "inherit":
        if not category:
            raise ValueError(
                "Cannot resolve 'inherit' model without a category. "
                "Pass the station category to enable group-based defaults."
            )
        tier = get_station_class_default(category)

        if return_tier_alias:
            return tier
        return resolve_model_tier(tier)

    # If it's already a valid tier alias, return it (or resolve for budget computation)
    if model_lower in VALID_TIERS:
        if return_tier_alias:
            return model_lower
        return resolve_model_tier(model_value)

    # Full model ID - pass through unchanged
    return model_value


def resolve_station_model_for_sdk(model_value: str, category: Optional[str] = None) -> str:
    """Resolve a station's model to a tier alias for SDK calls.

    Convenience wrapper that always returns tier aliases (haiku, sonnet, opus).
    The SDK handles version resolution based on env vars or defaults.

    Args:
        model_value: Model value from StationSpec.sdk.model.
        category: Station category (required for "inherit" resolution).

    Returns:
        Tier alias (haiku, sonnet, opus) or full model ID if explicitly pinned.

    Examples:
        >>> resolve_station_model_for_sdk("inherit", "implementation")
        'sonnet'
        >>> resolve_station_model_for_sdk("opus", "critic")
        'opus'
    """
    return resolve_station_model(model_value, category, return_tier_alias=True)


def resolve_station_model_for_budget(model_value: str, category: Optional[str] = None) -> str:
    """Resolve a station's model to a full model ID for budget computation.

    Convenience wrapper that always resolves to full model IDs for
    context window lookup.

    Args:
        model_value: Model value from StationSpec.sdk.model.
        category: Station category (required for "inherit" resolution).

    Returns:
        Full model ID suitable for context budget computation.

    Examples:
        >>> resolve_station_model_for_budget("inherit", "implementation")
        'claude-sonnet-4-20250514'
    """
    return resolve_station_model(model_value, category, return_tier_alias=False)
