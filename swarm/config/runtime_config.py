"""Runtime configuration registry for stepwise backends.

Provides centralized configuration for engine modes and settings.
Environment variables take precedence over YAML config.

Usage:
    from swarm.config.runtime_config import get_engine_mode, is_stub_mode

    mode = get_engine_mode("gemini")  # Returns "stub" or "cli"
    if is_stub_mode("claude"):
        # Use stub implementation

Provider and engine configuration:
    from swarm.config.runtime_config import (
        get_engine_provider,
        get_engine_env,
        get_provider_base_url,
        get_engine_required_env_keys,
    )

    provider = get_engine_provider("claude")  # Returns "anthropic"
    env = get_engine_env("claude-glm")  # Returns {"ANTHROPIC_BASE_URL": "..."}
    url = get_provider_base_url("anthropic_compat")  # Returns base URL or None
    keys = get_engine_required_env_keys("claude")  # Returns ["ANTHROPIC_API_KEY"]
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

# Module logger for budget validation warnings
logger = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).parent / "runtime.yaml"
_cached_config: Optional[Dict[str, Any]] = None

# =============================================================================
# Context Budget Guardrails (v2.5.0)
# =============================================================================

# Minimum: 10k chars (~2.5k tokens) - enough for at least one meaningful step
BUDGET_MIN_CHARS = 10_000

# Maximum: 600k chars (~150k tokens) - safe upper bound for 200k token windows
BUDGET_MAX_CHARS = 600_000

# Warning threshold: log warning above this (5M chars = likely config error)
BUDGET_WARN_THRESHOLD = 5_000_000


def _clamp_budget_value(
    value: int,
    name: str,
    min_val: int = BUDGET_MIN_CHARS,
    max_val: int = BUDGET_MAX_CHARS,
    warn_threshold: int = BUDGET_WARN_THRESHOLD,
) -> int:
    """Clamp a budget value to sanity bounds with logging.

    Args:
        value: The budget value to validate
        name: Human-readable name for logging (e.g., "context_budget_chars")
        min_val: Minimum allowed value
        max_val: Maximum allowed value
        warn_threshold: Threshold above which to log a warning

    Returns:
        Clamped value within [min_val, max_val]
    """
    original = value

    # Check for wildly wrong values (e.g., 5M chars)
    if value > warn_threshold:
        logger.warning(
            "Budget '%s' has suspiciously large value %d chars (>%d). "
            "This may indicate a configuration error. Clamping to %d.",
            name,
            value,
            warn_threshold,
            max_val,
        )
        value = max_val

    # Clamp to bounds
    if value < min_val:
        logger.warning(
            "Budget '%s' value %d chars is below minimum %d. Clamping to %d.",
            name,
            original,
            min_val,
            min_val,
        )
        value = min_val
    elif value > max_val:
        logger.warning(
            "Budget '%s' value %d chars exceeds maximum %d. Clamping to %d.",
            name,
            original,
            max_val,
            max_val,
        )
        value = max_val

    return value


@dataclass
class ContextBudgetConfig:
    """Resolved context budget configuration values.

    This represents the final effective budgets after cascade resolution:
    Step override > Flow override > Profile override > Global defaults
    """
    context_budget_chars: int
    history_max_recent_chars: int
    history_max_older_chars: int
    source: str = "default"  # "default" | "profile" | "flow" | "step"


def _load_config() -> Dict[str, Any]:
    """Load runtime.yaml configuration, with caching."""
    global _cached_config
    if _cached_config is not None:
        return _cached_config

    if _CONFIG_PATH.exists():
        with open(_CONFIG_PATH) as f:
            _cached_config = yaml.safe_load(f)
    else:
        _cached_config = _default_config()

    return _cached_config


def _default_config() -> Dict[str, Any]:
    """Return default configuration if runtime.yaml doesn't exist."""
    return {
        "version": "1.1",
        "providers": {
            "anthropic": {
                "base_url": None,
                "description": "Anthropic Claude API",
            },
            "anthropic_compat": {
                "base_url": None,
                "description": "Anthropic-compatible API (GLM/Z.AI, etc.)",
            },
        },
        "engines": {
            "gemini": {"mode": "stub"},
            "claude": {
                "mode": "stub",
                "execution": "legacy",
                "provider": "anthropic",
                "env_keys": ["ANTHROPIC_API_KEY"],
            },
            "claude-glm": {
                "mode": "sdk",
                "provider": "anthropic_compat",
                "env_keys": ["ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL"],
                "env": {"ANTHROPIC_BASE_URL": "https://api.z.ai/api/anthropic"},
            },
        },
        "defaults": {
            "stub_mode": True,
            "context_budget_chars": 400000,  # ~100k tokens for 200k window
            "history_max_recent_chars": 120000,  # ~30k tokens for recent step
            "history_max_older_chars": 20000,  # ~5k tokens for older steps
            "timeout_seconds": 30,
        },
        "features": {
            "stepwise_execution": True,
            "context_handoff": True,
            "write_transcripts": True,
            "write_receipts": True,
        },
        "flows": {
            "signal": {"recommended_backends": ["claude-harness", "gemini-step-orchestrator"]},
            "plan": {"recommended_backends": ["claude-harness", "gemini-step-orchestrator"]},
            "build": {"recommended_backends": ["claude-harness", "gemini-step-orchestrator", "claude-step-orchestrator"]},
            "gate": {"recommended_backends": ["claude-harness", "claude-step-orchestrator"]},
            "deploy": {"recommended_backends": ["claude-harness"]},
            "wisdom": {"recommended_backends": ["claude-harness"]},
        },
    }


def reset_config() -> None:
    """Reset cached config (for testing)."""
    global _cached_config
    _cached_config = None


def get_engine_mode(engine: str) -> str:
    """Get mode for an engine, respecting environment variable overrides.

    Environment variable precedence (highest to lowest):
    1. SWARM_<ENGINE>_STEP_ENGINE_MODE (e.g., SWARM_CLAUDE_STEP_ENGINE_MODE)
    2. SWARM_GEMINI_STUB (legacy, for gemini only) - "1" means stub mode
    3. SWARM_STEP_ENGINE_STUB (global override) - "1" means stub mode for all
    4. Config file value
    5. Default: "stub"

    Args:
        engine: Engine identifier ("gemini" or "claude").

    Returns:
        Engine mode string. Valid modes vary by engine:
        - gemini: "stub" or "cli"
        - claude: "stub", "sdk", or "cli"
    """
    # 1. Check engine-specific mode env var (highest priority)
    engine_upper = engine.upper()
    mode_env_var = f"SWARM_{engine_upper}_STEP_ENGINE_MODE"
    mode_value = os.environ.get(mode_env_var)
    if mode_value:
        return mode_value.lower()

    # 2. Check legacy SWARM_GEMINI_STUB for gemini (backward compatibility)
    if engine.lower() == "gemini":
        legacy_stub = os.environ.get("SWARM_GEMINI_STUB")
        if legacy_stub is not None:
            return "stub" if legacy_stub == "1" else "real"

    # 3. Check global stub override
    global_stub = os.environ.get("SWARM_STEP_ENGINE_STUB")
    if global_stub is not None:
        return "stub" if global_stub == "1" else "real"

    # 4. Check config file
    config = _load_config()
    engines = config.get("engines", {})
    engine_config = engines.get(engine.lower(), {})
    config_mode = engine_config.get("mode")
    if config_mode:
        return config_mode.lower()

    # 5. Default to stub for CI safety
    return "stub"


def is_stub_mode(engine: str) -> bool:
    """Check if an engine should run in stub mode.

    Args:
        engine: Engine identifier ("gemini" or "claude").

    Returns:
        True if the engine should use stub mode.
    """
    return get_engine_mode(engine) == "stub"


# Valid execution modes
VALID_EXECUTION_MODES = ("legacy", "session")


def get_engine_execution(engine: str) -> str:
    """Get execution pattern for an engine, respecting environment variable overrides.

    The execution pattern is orthogonal to mode (stub/sdk/cli). It controls
    how steps are executed:
    - legacy: Traditional run_step() lifecycle (work, finalize, route separately)
    - session: WP6 per-step session pattern (single session for all phases)

    Environment variable precedence (highest to lowest):
    1. SWARM_<ENGINE>_EXECUTION (e.g., SWARM_CLAUDE_EXECUTION)
    2. Config file value
    3. Default: "legacy"

    Args:
        engine: Engine identifier ("gemini" or "claude").

    Returns:
        Execution pattern string: "legacy" or "session".
        Logs a warning and returns "legacy" if invalid value is configured.
    """
    # 1. Check engine-specific execution env var (highest priority)
    engine_upper = engine.upper()
    exec_env_var = f"SWARM_{engine_upper}_EXECUTION"
    exec_value = os.environ.get(exec_env_var)
    if exec_value:
        exec_lower = exec_value.lower()
        if exec_lower not in VALID_EXECUTION_MODES:
            logger.warning(
                "Invalid %s value '%s' (valid: %s). Falling back to 'legacy'.",
                exec_env_var,
                exec_value,
                ", ".join(VALID_EXECUTION_MODES),
            )
            return "legacy"
        return exec_lower

    # 2. Check config file
    config = _load_config()
    engines = config.get("engines", {})
    engine_config = engines.get(engine.lower(), {})
    config_execution = engine_config.get("execution")
    if config_execution:
        exec_lower = config_execution.lower()
        if exec_lower not in VALID_EXECUTION_MODES:
            logger.warning(
                "Invalid execution value '%s' in config for engine '%s' (valid: %s). "
                "Falling back to 'legacy'.",
                config_execution,
                engine,
                ", ".join(VALID_EXECUTION_MODES),
            )
            return "legacy"
        return exec_lower

    # 3. Default to legacy for backwards compatibility
    return "legacy"


def is_session_execution(engine: str) -> bool:
    """Check if an engine should use the WP6 session execution pattern.

    Args:
        engine: Engine identifier ("gemini" or "claude").

    Returns:
        True if the engine should use session execution.
    """
    return get_engine_execution(engine) == "session"


def get_cli_path(engine: str) -> str:
    """Get CLI path for an engine, with env var override.

    Environment variable precedence:
    1. SWARM_<ENGINE>_CLI (e.g., SWARM_GEMINI_CLI)
    2. Config file cli_path value
    3. Default: engine name (e.g., "gemini", "claude")

    Args:
        engine: Engine identifier ("gemini" or "claude").

    Returns:
        CLI path string.
    """
    # 1. Check engine-specific CLI env var
    engine_upper = engine.upper()
    cli_env_var = f"SWARM_{engine_upper}_CLI"
    cli_value = os.environ.get(cli_env_var)
    if cli_value:
        return cli_value

    # 2. Check config file
    config = _load_config()
    engines = config.get("engines", {})
    engine_config = engines.get(engine.lower(), {})
    cli_path = engine_config.get("cli_path")
    if cli_path:
        return cli_path

    # 3. Default to engine name
    return engine.lower()


def get_default(key: str, fallback: Any = None) -> Any:
    """Get a default setting value.

    Args:
        key: Setting key (e.g., "context_budget_chars", "timeout_seconds").
        fallback: Value to return if key not found.

    Returns:
        Setting value or fallback.
    """
    config = _load_config()
    defaults = config.get("defaults", {})
    return defaults.get(key, fallback)


def is_feature_enabled(feature: str) -> bool:
    """Check if a feature is enabled.

    Args:
        feature: Feature name (e.g., "stepwise_execution", "write_transcripts").

    Returns:
        True if the feature is enabled, False otherwise.
    """
    config = _load_config()
    features = config.get("features", {})
    return features.get(feature, False)


def get_context_budget_chars() -> int:
    """Get the context budget for history in characters.

    Returns the global default. For resolved values that consider profile/flow/step
    overrides, use get_resolved_context_budgets() instead.
    """
    return get_default("context_budget_chars", 200000)


def get_history_max_recent_chars() -> int:
    """Get max chars for most recent step.

    Returns the global default. For resolved values that consider profile/flow/step
    overrides, use get_resolved_context_budgets() instead.
    """
    return get_default("history_max_recent_chars", 60000)


def get_history_max_older_chars() -> int:
    """Get max chars for older steps.

    Returns the global default. For resolved values that consider profile/flow/step
    overrides, use get_resolved_context_budgets() instead.
    """
    return get_default("history_max_older_chars", 10000)


def get_timeout_seconds() -> int:
    """Get default timeout for engine execution.

    Returns:
        Timeout in seconds (default: 30).
    """
    return get_default("timeout_seconds", 30)


class ContextBudgetResolver:
    """Resolves context budgets through the cascade hierarchy.

    Resolution order (highest to lowest priority):
    1. Step-level override (from engine_profile.context_budgets in step config)
    2. Flow-level override (from per-flow YAML context_budgets section)
    3. Profile-level override (from profile's runtime_settings.context_budgets)
    4. Global defaults (from runtime.yaml defaults section)
    """

    def __init__(self, profile_id: Optional[str] = None):
        self._profile_id = profile_id
        self._profile_budgets: Optional["ContextBudgetOverride"] = None
        if profile_id:
            self._profile_budgets = self._load_profile_budgets(profile_id)

    def _load_profile_budgets(self, profile_id: str) -> Optional["ContextBudgetOverride"]:
        """Load context budget overrides from a profile."""
        try:
            from swarm.config.profile_registry import load_profile
            profile = load_profile(profile_id)
            if profile and hasattr(profile, 'runtime_settings') and profile.runtime_settings:
                return profile.runtime_settings.context_budgets
        except Exception:
            pass
        return None

    def _load_flow_budgets(self, flow_key: str) -> Optional["ContextBudgetOverride"]:
        """Load context budget overrides from a flow definition."""
        try:
            from swarm.config.flow_registry import FlowRegistry
            registry = FlowRegistry.get_instance()
            flow_def = registry.get_flow(flow_key)
            if flow_def and hasattr(flow_def, 'context_budgets'):
                return flow_def.context_budgets
        except Exception:
            pass
        return None

    def _load_step_budgets(self, flow_key: str, step_id: str) -> Optional["ContextBudgetOverride"]:
        """Load context budget overrides from a step's engine profile."""
        try:
            from swarm.config.flow_registry import FlowRegistry
            registry = FlowRegistry.get_instance()
            flow_def = registry.get_flow(flow_key)
            if flow_def:
                for step in flow_def.steps:
                    if step.id == step_id and step.engine_profile and hasattr(step.engine_profile, 'context_budgets') and step.engine_profile.context_budgets:
                        return step.engine_profile.context_budgets
        except Exception:
            pass
        return None

    def resolve(
        self,
        flow_key: Optional[str] = None,
        step_id: Optional[str] = None,
    ) -> ContextBudgetConfig:
        """Resolve effective budgets at the given level.

        Args:
            flow_key: Optional flow key for flow-level resolution
            step_id: Optional step ID for step-level resolution (requires flow_key)

        Returns:
            ContextBudgetConfig with resolved values and source indicator
        """
        # Start with global defaults
        result = ContextBudgetConfig(
            context_budget_chars=get_default("context_budget_chars", 200000),
            history_max_recent_chars=get_default("history_max_recent_chars", 60000),
            history_max_older_chars=get_default("history_max_older_chars", 10000),
            source="default",
        )

        # Apply profile override if available
        if self._profile_budgets:
            if self._profile_budgets.context_budget_chars is not None:
                result.context_budget_chars = self._profile_budgets.context_budget_chars
            if self._profile_budgets.history_max_recent_chars is not None:
                result.history_max_recent_chars = self._profile_budgets.history_max_recent_chars
            if self._profile_budgets.history_max_older_chars is not None:
                result.history_max_older_chars = self._profile_budgets.history_max_older_chars
            result.source = "profile"

        # Apply flow override if available
        if flow_key:
            flow_budgets = self._load_flow_budgets(flow_key)
            if flow_budgets:
                if flow_budgets.context_budget_chars is not None:
                    result.context_budget_chars = flow_budgets.context_budget_chars
                if flow_budgets.history_max_recent_chars is not None:
                    result.history_max_recent_chars = flow_budgets.history_max_recent_chars
                if flow_budgets.history_max_older_chars is not None:
                    result.history_max_older_chars = flow_budgets.history_max_older_chars
                result.source = "flow"

        # Apply step override if available
        if flow_key and step_id:
            step_budgets = self._load_step_budgets(flow_key, step_id)
            if step_budgets:
                if step_budgets.context_budget_chars is not None:
                    result.context_budget_chars = step_budgets.context_budget_chars
                if step_budgets.history_max_recent_chars is not None:
                    result.history_max_recent_chars = step_budgets.history_max_recent_chars
                if step_budgets.history_max_older_chars is not None:
                    result.history_max_older_chars = step_budgets.history_max_older_chars
                result.source = "step"

        # === Guardrails: Validate and clamp resolved values ===
        result.context_budget_chars = _clamp_budget_value(
            result.context_budget_chars,
            "context_budget_chars",
        )
        result.history_max_recent_chars = _clamp_budget_value(
            result.history_max_recent_chars,
            "history_max_recent_chars",
        )
        result.history_max_older_chars = _clamp_budget_value(
            result.history_max_older_chars,
            "history_max_older_chars",
        )

        # Enforce relational constraints:
        # recent_max and older_max must not exceed total budget
        if result.history_max_recent_chars > result.context_budget_chars:
            logger.warning(
                "history_max_recent_chars (%d) exceeds context_budget_chars (%d). "
                "Clamping to total budget.",
                result.history_max_recent_chars,
                result.context_budget_chars,
            )
            result.history_max_recent_chars = result.context_budget_chars

        if result.history_max_older_chars > result.context_budget_chars:
            logger.warning(
                "history_max_older_chars (%d) exceeds context_budget_chars (%d). "
                "Clamping to total budget.",
                result.history_max_older_chars,
                result.context_budget_chars,
            )
            result.history_max_older_chars = result.context_budget_chars

        return result


def get_resolved_context_budgets(
    flow_key: Optional[str] = None,
    step_id: Optional[str] = None,
    profile_id: Optional[str] = None,
) -> ContextBudgetConfig:
    """Convenience function to resolve context budgets.

    This is the primary entry point for callers who need resolved budgets.
    """
    resolver = ContextBudgetResolver(profile_id)
    return resolver.resolve(flow_key, step_id)


# Default fallback backend when no flow-specific config exists
_DEFAULT_BACKEND = "claude-harness"


def get_flow_recommended_backends(flow_key: str) -> List[str]:
    """Return recommended backends for a flow.

    Args:
        flow_key: Flow key (signal, plan, build, gate, deploy, wisdom).

    Returns:
        List of backend IDs in preference order.
        Falls back to ["claude-harness"] if not configured.
    """
    config = _load_config()
    flows = config.get("flows", {})
    flow_config = flows.get(flow_key.lower(), {})
    recommended = flow_config.get("recommended_backends")

    if recommended and isinstance(recommended, list) and len(recommended) > 0:
        return recommended

    # Fallback to default backend
    return [_DEFAULT_BACKEND]


def get_default_backend_for_flow(flow_key: str) -> str:
    """Return the default (first recommended) backend for a flow.

    Args:
        flow_key: Flow key (signal, plan, build, gate, deploy, wisdom).

    Returns:
        First recommended backend ID, or "claude-harness" as fallback.
    """
    backends = get_flow_recommended_backends(flow_key)
    return backends[0] if backends else _DEFAULT_BACKEND


# Provider and engine configuration helpers


def get_engine_provider(engine_id: str) -> str:
    """Get the provider ID for an engine.

    Args:
        engine_id: Engine identifier (e.g., "claude", "claude-glm", "gemini").

    Returns:
        Provider ID string (e.g., "anthropic", "anthropic_compat").
        Returns empty string if no provider is configured for the engine.
    """
    config = _load_config()
    engines = config.get("engines", {})
    engine_config = engines.get(engine_id.lower(), {})
    return engine_config.get("provider", "")


def get_engine_env(engine_id: str) -> Dict[str, str]:
    """Get environment variable overrides for an engine.

    These are static env vars defined in the engine config,
    which can be used to configure the provider (e.g., base URL).

    Args:
        engine_id: Engine identifier (e.g., "claude-glm").

    Returns:
        Dictionary of environment variable name -> value.
        Returns empty dict if no env overrides are configured.
    """
    config = _load_config()
    engines = config.get("engines", {})
    engine_config = engines.get(engine_id.lower(), {})
    env = engine_config.get("env", {})
    # Ensure we return a dict of strings
    return {str(k): str(v) for k, v in env.items()} if env else {}


def get_provider_base_url(provider_id: str) -> Optional[str]:
    """Get the base URL for a provider.

    Args:
        provider_id: Provider identifier (e.g., "anthropic", "anthropic_compat").

    Returns:
        Base URL string if configured, None otherwise.
        For "anthropic", this typically returns None (uses default Anthropic API).
        For "anthropic_compat", this may be set via config or ANTHROPIC_BASE_URL env.
    """
    config = _load_config()
    providers = config.get("providers", {})
    provider_config = providers.get(provider_id.lower(), {})
    return provider_config.get("base_url")


def get_engine_required_env_keys(engine_id: str) -> List[str]:
    """Get the list of required environment variable names for an engine.

    These are the env vars that must be set for the engine to function
    (e.g., API keys, base URLs).

    Args:
        engine_id: Engine identifier (e.g., "claude", "claude-glm").

    Returns:
        List of environment variable names.
        Returns empty list if no env keys are required.
    """
    config = _load_config()
    engines = config.get("engines", {})
    engine_config = engines.get(engine_id.lower(), {})
    env_keys = engine_config.get("env_keys", [])
    return list(env_keys) if env_keys else []


def get_available_providers() -> List[str]:
    """Get list of all configured provider IDs.

    Returns:
        List of provider ID strings.
    """
    config = _load_config()
    providers = config.get("providers", {})
    return list(providers.keys())


def get_available_engines() -> List[str]:
    """Get list of all configured engine IDs.

    Returns:
        List of engine ID strings.
    """
    config = _load_config()
    engines = config.get("engines", {})
    return list(engines.keys())
