"""
factory.py - Step engine factory functions.

Provides centralized engine instantiation based on pack configuration.

This factory uses resolve_runtime() from pack_registry to determine engine
settings through the pack hierarchy:
1. CLI overrides
2. Environment variables
3. Repo pack (.swarm/pack.yaml)
4. Baseline pack (swarm/packs/baseline/)

Each resolved setting includes provenance showing where it came from.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from swarm.config.pack_registry import resolve_runtime

from .base import StepEngine
from .claude import ClaudeStepEngine
from .gemini import GeminiStepEngine

logger = logging.getLogger(__name__)


def get_step_engine(
    engine_id: str,
    repo_root: Path,
    mode: Optional[str] = None,
    execution: Optional[str] = None,
    cli_overrides: Optional[Dict[str, Any]] = None,
) -> StepEngine:
    """Get a step engine by ID with pack-aware configuration.

    This factory function resolves engine settings through the pack hierarchy:
    1. Explicit overrides (mode, execution parameters)
    2. cli_overrides dict
    3. Environment variables
    4. Repo pack (.swarm/pack.yaml)
    5. Baseline pack (swarm/packs/baseline/)

    Engine IDs:
    - "gemini-step" or "gemini": GeminiStepEngine
    - "claude-step" or "claude": ClaudeStepEngine

    Args:
        engine_id: Engine identifier ("gemini-step", "claude-step", etc.)
        repo_root: Repository root path.
        mode: Optional mode override ("stub", "sdk", "cli").
              If None, reads from pack hierarchy.
        execution: Optional execution pattern override ("legacy", "session").
              If None, reads from pack hierarchy.
        cli_overrides: Optional dict of CLI overrides for pack resolution.

    Returns:
        Configured StepEngine instance.

    Raises:
        ValueError: If engine_id is not recognized.

    Example:
        >>> engine = get_step_engine("claude-step", Path.cwd(), mode="sdk", execution="session")
        >>> result, events = engine.run_step(ctx)
    """
    engine_id_lower = engine_id.lower()

    # Resolve configuration from pack hierarchy
    resolved = resolve_runtime(repo_root=repo_root, cli_overrides=cli_overrides)

    if engine_id_lower in ("gemini-step", "gemini"):
        gemini_settings = resolved.engines.get("gemini")
        resolved_mode = mode or (gemini_settings.mode if gemini_settings else "stub")

        logger.debug(
            "get_step_engine(gemini): mode=%s (source=%s)",
            resolved_mode,
            gemini_settings.mode_source if gemini_settings else "default",
        )

        return GeminiStepEngine(repo_root)

    if engine_id_lower in ("claude-step", "claude"):
        claude_settings = resolved.engines.get("claude")

        # Use explicit overrides, then pack-resolved values
        resolved_mode = mode or (claude_settings.mode if claude_settings else "stub")
        resolved_execution = execution or (
            claude_settings.execution if claude_settings else "legacy"
        )

        logger.debug(
            "get_step_engine(claude): mode=%s (source=%s), execution=%s (source=%s)",
            resolved_mode,
            claude_settings.mode_source if claude_settings else "override",
            resolved_execution,
            claude_settings.execution_source if claude_settings else "override",
        )

        return ClaudeStepEngine(
            repo_root,
            mode=resolved_mode,
            execution=resolved_execution,
        )

    raise ValueError(f"Unknown engine ID: {engine_id}. Valid options: gemini-step, claude-step")


def list_available_engines(
    repo_root: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    """List available step engines with their resolved configuration.

    This function resolves settings from the pack hierarchy and includes
    provenance information showing where each setting came from.

    Args:
        repo_root: Optional repository root for pack resolution.

    Returns:
        List of dicts with engine metadata:
        - id: Engine identifier
        - label: Human-readable label
        - modes: Available modes for this engine
        - resolved_mode: Current resolved mode from pack hierarchy
        - resolved_execution: Current resolved execution pattern (claude only)
        - mode_source: Where the mode came from (cli, env, repo, baseline, default)
        - execution_source: Where the execution came from (claude only)
        - provider: Provider name
    """
    # Resolve configuration from pack hierarchy
    resolved = resolve_runtime(repo_root=repo_root)

    gemini_settings = resolved.engines.get("gemini")
    claude_settings = resolved.engines.get("claude")

    return [
        {
            "id": "gemini-step",
            "label": "Gemini CLI",
            "modes": ["stub", "cli"],
            "resolved_mode": gemini_settings.mode if gemini_settings else "stub",
            "mode_source": gemini_settings.mode_source if gemini_settings else "default",
            "provider": "gemini",
        },
        {
            "id": "claude-step",
            "label": "Claude Agent SDK/CLI",
            "modes": ["stub", "sdk", "cli"],
            "execution_modes": ["legacy", "session"],
            "resolved_mode": claude_settings.mode if claude_settings else "stub",
            "resolved_execution": claude_settings.execution if claude_settings else "legacy",
            "mode_source": claude_settings.mode_source if claude_settings else "default",
            "execution_source": claude_settings.execution_source if claude_settings else "default",
            "provider": claude_settings.provider if claude_settings else "anthropic",
            "provider_source": claude_settings.provider_source if claude_settings else "default",
        },
    ]
