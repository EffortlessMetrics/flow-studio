"""
utility_candidates.py - Utility flow candidate generation for routing.

This module provides functions to generate INJECT_FLOW routing candidates
from utility flow triggers. It is the single source of truth for utility
flow candidate generation, avoiding circular imports between driver and
navigator modules.

The candidate-set pattern requires:
1. Python generates the full candidate set (including utility flows)
2. Navigator chooses from that set
3. Python applies the choice

This module provides the candidate generation (step 1) which is consumed
by both driver.py (for enrichment after routing) and navigator.py (for
candidates BEFORE Navigator sees them).

## Merge Behavior Contract

Utility flow candidates are added to the routing candidate list with these
guarantees:

1. **Never default**: Utility candidates always have `is_default=False`.
   Navigator must explicitly choose them; they're never auto-selected.

2. **Appended after normal candidates**: Utility candidates are added after
   graph-derived candidates, but ordering is not a selection signal.

3. **Deduplicated by candidate_id**: If a utility candidate's ID already
   exists in the list, it is not added again.

4. **Navigator chooses by content**: The Navigator evaluates all candidates
   by their reason/evidence, not by list position.

## Strict Mode

Set `SWARM_STRICT_REPO_ROOT=1` to enforce explicit `repo_root` in all calls.
When strict mode is enabled, `repo_root=None` raises `ValueError` instead of
falling back to CWD. Use this in CI to catch missing repo_root early.

Usage:
    from swarm.runtime.stepwise.routing.utility_candidates import (
        get_utility_flow_candidates,
        get_utility_flow_registry,
        get_utility_flow_detector,
        clear_utility_flow_caches,
    )

    # Get candidates for Navigator's candidate set
    candidates = get_utility_flow_candidates(
        step_result=result,
        run_state=state,
        git_status=git_status,
        repo_root=repo_root,  # Required in strict mode
    )
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional
from typing_extensions import TypedDict

from swarm.runtime.types import RoutingCandidate
from swarm.runtime.utility_flow_injection import (
    UtilityFlowRegistry,
    InjectionTriggerDetector,
)

if TYPE_CHECKING:
    from swarm.runtime.types import RunState

logger = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================

# Source identifier for utility flow candidates (stable key for audit/UI)
UTILITY_SOURCE = "utility_flow_detector"

# Prefix for inject_flow candidate IDs
INJECT_PREFIX = "inject_flow:"


# =============================================================================
# Typed Git Status
# =============================================================================


class GitStatus(TypedDict, total=False):
    """Typed git status information for utility flow trigger evaluation.

    All fields are optional to support partial git status queries.

    Attributes:
        behind_count: Number of commits behind upstream.
        diverged: Whether the branch has diverged from upstream.
        has_conflicts: Whether there are unresolved merge conflicts.
        ahead_count: Number of commits ahead of upstream.
        branch: Current branch name.
        upstream: Upstream branch name (e.g., 'origin/main').
    """

    behind_count: int
    diverged: bool
    has_conflicts: bool
    ahead_count: int
    branch: str
    upstream: str


# =============================================================================
# Strict Mode
# =============================================================================


def _is_strict_mode() -> bool:
    """Check if strict repo_root mode is enabled.

    Returns:
        True if SWARM_STRICT_REPO_ROOT is set to a truthy value.
    """
    strict_env = os.environ.get("SWARM_STRICT_REPO_ROOT", "").lower()
    return strict_env in ("1", "true", "yes", "on")


# =============================================================================
# Module-level caches (keyed by repo_root for multi-repo support)
# =============================================================================

_utility_flow_registries: Dict[str, UtilityFlowRegistry] = {}
_utility_flow_detectors: Dict[str, InjectionTriggerDetector] = {}

# Track whether we've warned about missing repo_root (once per process)
_warned_missing_repo_root = False


def _get_cache_key(repo_root: Path) -> str:
    """Get cache key for a repo_root path.

    Args:
        repo_root: Repository root path. Must be provided.

    Returns:
        Resolved path as string for use as cache key.
    """
    return str(repo_root.resolve())


def _validate_repo_root(repo_root: Optional[Path], context: str) -> Optional[Path]:
    """Validate repo_root and enforce strict mode if enabled.

    Args:
        repo_root: Repository root path (may be None).
        context: Description of the calling context for error messages.

    Returns:
        The validated repo_root, or None if not provided and not strict.

    Raises:
        ValueError: If strict mode is enabled and repo_root is None.
    """
    global _warned_missing_repo_root

    if repo_root is not None:
        return repo_root

    if _is_strict_mode():
        raise ValueError(
            f"repo_root is required in strict mode ({context}). "
            "Either pass repo_root explicitly or unset SWARM_STRICT_REPO_ROOT."
        )

    # Legacy path: warn once, then allow CWD fallback
    if not _warned_missing_repo_root:
        logger.warning(
            "repo_root not provided to %s; using CWD fallback. "
            "This is deprecated. Set SWARM_STRICT_REPO_ROOT=1 to enforce.",
            context,
        )
        _warned_missing_repo_root = True

    return None


def get_utility_flow_registry(repo_root: Optional[Path] = None) -> UtilityFlowRegistry:
    """Get utility flow registry for a repo (lazy-loaded, cached by repo_root).

    The cache is keyed by resolved repo_root path to support multiple repos
    in the same process without cross-contamination.

    When repo_root is None:
    - In strict mode (SWARM_STRICT_REPO_ROOT=1): raises ValueError
    - Otherwise: uses CWD as fallback (deprecated, logs warning once)

    Args:
        repo_root: Repository root path. Required in strict mode.

    Returns:
        The UtilityFlowRegistry instance for this repo.

    Raises:
        ValueError: If strict mode is enabled and repo_root is None.
    """
    validated_root = _validate_repo_root(repo_root, "get_utility_flow_registry")
    actual_root = validated_root or Path.cwd()
    cache_key = _get_cache_key(actual_root)

    if cache_key not in _utility_flow_registries:
        _utility_flow_registries[cache_key] = UtilityFlowRegistry(actual_root)

    return _utility_flow_registries[cache_key]


def get_utility_flow_detector(repo_root: Optional[Path] = None) -> InjectionTriggerDetector:
    """Get utility flow detector for a repo (lazy-loaded, cached by repo_root).

    The cache is keyed by resolved repo_root path to support multiple repos
    in the same process without cross-contamination.

    When repo_root is None:
    - In strict mode (SWARM_STRICT_REPO_ROOT=1): raises ValueError
    - Otherwise: uses CWD as fallback (deprecated, logs warning once)

    Args:
        repo_root: Repository root path. Required in strict mode.

    Returns:
        The InjectionTriggerDetector instance for this repo.

    Raises:
        ValueError: If strict mode is enabled and repo_root is None.
    """
    validated_root = _validate_repo_root(repo_root, "get_utility_flow_detector")
    actual_root = validated_root or Path.cwd()
    cache_key = _get_cache_key(actual_root)

    if cache_key not in _utility_flow_detectors:
        registry = get_utility_flow_registry(actual_root)
        _utility_flow_detectors[cache_key] = InjectionTriggerDetector(registry)

    return _utility_flow_detectors[cache_key]


def set_utility_flow_registry(
    registry: UtilityFlowRegistry,
    repo_root: Optional[Path] = None,
) -> None:
    """Set a custom utility flow registry (for testing or custom configuration).

    Args:
        registry: The UtilityFlowRegistry to use.
        repo_root: The repo_root to associate with this registry. Required in strict mode.

    Raises:
        ValueError: If strict mode is enabled and repo_root is None.
    """
    validated_root = _validate_repo_root(repo_root, "set_utility_flow_registry")
    actual_root = validated_root or Path.cwd()
    cache_key = _get_cache_key(actual_root)

    _utility_flow_registries[cache_key] = registry
    _utility_flow_detectors[cache_key] = InjectionTriggerDetector(registry)


def clear_utility_flow_caches() -> None:
    """Clear all utility flow caches.

    Call this in test setup/teardown to ensure test isolation.
    Without this, cached registries/detectors from previous tests
    may cause cross-test contamination.

    Also resets the missing-repo_root warning flag.
    """
    global _warned_missing_repo_root
    _utility_flow_registries.clear()
    _utility_flow_detectors.clear()
    _warned_missing_repo_root = False


# =============================================================================
# Step result conversion helper
# =============================================================================


def _step_result_to_dict(step_result: Any) -> Dict[str, Any]:
    """Convert a step result to a dictionary for routing logic.

    The step_result can be:
    - A dict: returned as-is
    - A StepResult dataclass: converted to dict with status, output, etc.
    - An object with to_dict(): uses that method
    - Any other object: extracts common attributes

    This ensures routing logic always receives the status, output, and
    other fields needed for routing decisions.

    Args:
        step_result: The result from step execution (any type).

    Returns:
        A dictionary with at minimum 'status' key if available.
    """
    if isinstance(step_result, dict):
        return step_result

    # Try to_dict() method first (common pattern for dataclasses with custom serialization)
    if hasattr(step_result, "to_dict") and callable(step_result.to_dict):
        return step_result.to_dict()

    # Extract common attributes from StepResult or similar objects
    result: Dict[str, Any] = {}
    for attr in (
        "status",
        "output",
        "error",
        "duration_ms",
        "step_id",
        "artifacts",
        "can_further_iteration_help",
    ):
        if hasattr(step_result, attr):
            result[attr] = getattr(step_result, attr)
    return result


# =============================================================================
# Utility Flow Candidates
# =============================================================================


def get_utility_flow_candidates(
    step_result: Any,
    run_state: "RunState",
    git_status: Optional[GitStatus] = None,
    repo_root: Optional[Path] = None,
) -> List[RoutingCandidate]:
    """Get applicable utility flows as INJECT_FLOW candidates.

    Evaluates utility flow triggers (e.g., upstream_diverged) against the
    current context and returns matching utility flows as RoutingCandidate
    objects with action="inject_flow".

    This is parallel to sidequest candidate generation but for whole-flow
    injection rather than single-step detours.

    When repo_root is None:
    - In strict mode (SWARM_STRICT_REPO_ROOT=1): raises ValueError
    - Otherwise: returns empty list (no candidates)

    Args:
        step_result: The result from step execution.
        run_state: Current run state.
        git_status: Optional typed git status information (see GitStatus TypedDict).
        repo_root: Repository root path. Required in strict mode.

    Returns:
        List of RoutingCandidate objects for applicable utility flows.
        Returns empty list if repo_root is None in non-strict mode.

    Raises:
        ValueError: If strict mode is enabled and repo_root is None.
    """
    # In non-strict mode with no repo_root, return empty (no candidates)
    # This is safer than guessing CWD for candidate generation
    if repo_root is None:
        if _is_strict_mode():
            raise ValueError(
                "repo_root is required in strict mode (get_utility_flow_candidates). "
                "Either pass repo_root explicitly or unset SWARM_STRICT_REPO_ROOT."
            )
        logger.debug(
            "get_utility_flow_candidates called without repo_root; returning empty list"
        )
        return []

    detector = get_utility_flow_detector(repo_root)

    # Convert step_result to dict for trigger evaluation
    result_dict = _step_result_to_dict(step_result)

    # Check all triggers
    trigger_result = detector.check_triggers(
        step_result=result_dict,
        run_state=run_state,
        git_status=git_status,
    )

    candidates: List[RoutingCandidate] = []

    if trigger_result.triggered and trigger_result.flow_id:
        # Build evidence pointers from trigger evidence (stable keys for UI/audit)
        evidence_pointers = [
            f"trigger:{trigger_result.trigger_type}",
            *[f"{key}:{value}" for key, value in trigger_result.evidence.items()],
        ]

        candidates.append(
            RoutingCandidate(
                candidate_id=f"{INJECT_PREFIX}{trigger_result.flow_id}",
                action="inject_flow",
                target_node=trigger_result.flow_id,
                reason=trigger_result.reason,
                priority=trigger_result.priority,
                source=UTILITY_SOURCE,
                evidence_pointers=evidence_pointers,
                is_default=False,  # Never auto-select; Navigator must choose
            )
        )

        logger.info(
            "Utility flow detector: found trigger '%s' -> inject_flow:%s (priority=%d)",
            trigger_result.trigger_type,
            trigger_result.flow_id,
            trigger_result.priority,
        )

    return candidates


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    # Constants
    "UTILITY_SOURCE",
    "INJECT_PREFIX",
    # Types
    "GitStatus",
    # Cache management
    "get_utility_flow_registry",
    "get_utility_flow_detector",
    "set_utility_flow_registry",
    "clear_utility_flow_caches",
    # Candidate generation
    "get_utility_flow_candidates",
]
