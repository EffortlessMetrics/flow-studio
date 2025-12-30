"""Tool profile registry for station tool access configuration.

Provides:
1. Tool profile definitions (allowed tools per profile)
2. Station category to profile mapping
3. Profile resolution for StationSpecs
"""

from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml

# Cache for loaded profiles
_profiles_cache: Optional[Dict] = None
_config_path: Optional[Path] = None


def _get_config_path() -> Path:
    """Get the path to tool_profiles.yaml."""
    return Path(__file__).parent / "tool_profiles.yaml"


def _load_profiles() -> Dict:
    """Load and cache tool profiles from YAML."""
    global _profiles_cache, _config_path

    config_path = _get_config_path()

    # Return cached if unchanged
    if _profiles_cache is not None and _config_path == config_path:
        return _profiles_cache

    with config_path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)

    _profiles_cache = data
    _config_path = config_path
    return data


# Fallback profiles (used if YAML loading fails)
FALLBACK_PROFILES: Dict[str, Tuple[str, ...]] = {
    "read_only": ("Read", "Grep", "Glob"),
    "read_write": ("Read", "Write", "Edit", "Grep", "Glob"),
    "full_access": ("Read", "Write", "Edit", "Bash", "Grep", "Glob", "Task", "TodoWrite"),
    "critic": ("Read", "Grep", "Glob", "Write"),
    "reporter": ("Read", "Grep", "Glob", "Write"),
}

FALLBACK_CATEGORY_DEFAULTS: Dict[str, str] = {
    "shaping": "read_only",
    "spec": "read_write",
    "design": "read_write",
    "implementation": "read_write",
    "critic": "critic",
    "verification": "read_only",
    "analytics": "read_only",
    "reporter": "reporter",
    "infra": "full_access",
    "router": "read_only",
}


def get_profile_tools(profile_name: str) -> Tuple[str, ...]:
    """Get the tools for a profile.

    Args:
        profile_name: Profile name (e.g., "read_write", "full_access").

    Returns:
        Tuple of tool names available in this profile.

    Examples:
        >>> get_profile_tools("read_only")
        ('Read', 'Grep', 'Glob')
    """
    try:
        data = _load_profiles()
        profile = data.get("profiles", {}).get(profile_name, {})
        tools = profile.get("tools", [])
        return tuple(tools) if tools else FALLBACK_PROFILES.get(profile_name, ())
    except Exception:
        return FALLBACK_PROFILES.get(profile_name, ())


def get_category_default_profile(category: str) -> str:
    """Get the default tool profile for a station category.

    Args:
        category: Station category from StationSpec.category.

    Returns:
        Profile name (e.g., "read_write").

    Examples:
        >>> get_category_default_profile("implementation")
        'read_write'
        >>> get_category_default_profile("critic")
        'critic'
    """
    try:
        data = _load_profiles()
        defaults = data.get("category_defaults", {})
        return defaults.get(category.lower(), "read_write")
    except Exception:
        return FALLBACK_CATEGORY_DEFAULTS.get(category.lower(), "read_write")


def resolve_tool_profile(profile_value: str, category: Optional[str] = None) -> Tuple[str, ...]:
    """Resolve a station's tool profile to actual tool names.

    This is the main entry point for tool profile resolution in the SpecCompiler.
    It handles:
    1. "inherit" → looks up category default, then resolves to tools
    2. profile names → resolves to tool tuple
    3. Returns fallback if profile not found

    Args:
        profile_value: Profile value from StationSpec.sdk.tool_profile.
        category: Station category (required for "inherit" resolution).

    Returns:
        Tuple of tool names.

    Examples:
        >>> resolve_tool_profile("inherit", "implementation")
        ('Read', 'Write', 'Edit', 'Grep', 'Glob')
        >>> resolve_tool_profile("read_only")
        ('Read', 'Grep', 'Glob')
    """
    profile_lower = profile_value.lower()

    # Handle "inherit" by looking up category default
    if profile_lower == "inherit":
        if category:
            profile_name = get_category_default_profile(category)
            return get_profile_tools(profile_name)
        # No category, use read_write as safest default
        return get_profile_tools("read_write")

    # Direct profile lookup
    return get_profile_tools(profile_value)


def list_profiles() -> List[str]:
    """List all available profile names.

    Returns:
        List of profile names.
    """
    try:
        data = _load_profiles()
        return list(data.get("profiles", {}).keys())
    except Exception:
        return list(FALLBACK_PROFILES.keys())


def get_profile_metadata(profile_name: str) -> Dict:
    """Get full metadata for a profile (description, use_cases, etc.).

    Args:
        profile_name: Profile name.

    Returns:
        Dict with profile metadata, or empty dict if not found.
    """
    try:
        data = _load_profiles()
        return data.get("profiles", {}).get(profile_name, {})
    except Exception:
        return {}
