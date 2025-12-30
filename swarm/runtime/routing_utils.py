"""
routing_utils.py - Centralized routing decision parsing.

This module provides the single source of truth for parsing routing decisions.
All routing-related code should import from here instead of maintaining
separate decision mapping tables.

Decision Vocabulary:
- Canonical: advance, loop, terminate, branch
- Aliases: proceed/continue/next, rerun/retry/repeat, blocked/stop/end/exit, route/switch/redirect
"""

from __future__ import annotations

import logging
from typing import Dict

from swarm.runtime.types import RoutingDecision

logger = logging.getLogger(__name__)


# =============================================================================
# CANONICAL DECISION MAPPINGS - THE SINGLE SOURCE OF TRUTH
# =============================================================================

# Primary canonical values
CANONICAL_MAP: Dict[str, RoutingDecision] = {
    "advance": RoutingDecision.ADVANCE,
    "loop": RoutingDecision.LOOP,
    "terminate": RoutingDecision.TERMINATE,
    "branch": RoutingDecision.BRANCH,
}

# Aliases that map to canonical values
ALIAS_MAP: Dict[str, RoutingDecision] = {
    # ADVANCE aliases
    "proceed": RoutingDecision.ADVANCE,
    "continue": RoutingDecision.ADVANCE,
    "next": RoutingDecision.ADVANCE,
    # LOOP aliases
    "rerun": RoutingDecision.LOOP,
    "retry": RoutingDecision.LOOP,
    "repeat": RoutingDecision.LOOP,
    # TERMINATE aliases
    "blocked": RoutingDecision.TERMINATE,
    "stop": RoutingDecision.TERMINATE,
    "end": RoutingDecision.TERMINATE,
    "exit": RoutingDecision.TERMINATE,
    # BRANCH aliases
    "route": RoutingDecision.BRANCH,
    "switch": RoutingDecision.BRANCH,
    "redirect": RoutingDecision.BRANCH,
}

# Combined map for fast lookup
_COMBINED_MAP: Dict[str, RoutingDecision] = {**CANONICAL_MAP, **ALIAS_MAP}


def parse_routing_decision(decision_str: str) -> RoutingDecision:
    """Parse a routing decision string into a RoutingDecision enum.

    Handles both canonical values (advance, loop, terminate, branch) and
    common aliases from external sources (proceed, rerun, blocked, route).

    Args:
        decision_str: The routing decision string (case-insensitive).

    Returns:
        The corresponding RoutingDecision enum value.
        Defaults to ADVANCE if unrecognized.
    """
    decision_lower = decision_str.lower().strip()

    if decision_lower in CANONICAL_MAP:
        return CANONICAL_MAP[decision_lower]

    if decision_lower in ALIAS_MAP:
        logger.debug(
            "Mapped routing decision alias '%s' -> %s",
            decision_str,
            ALIAS_MAP[decision_lower].value,
        )
        return ALIAS_MAP[decision_lower]

    logger.warning(
        "Unknown routing decision '%s', defaulting to ADVANCE",
        decision_str,
    )
    return RoutingDecision.ADVANCE


def is_valid_decision(decision_str: str) -> bool:
    """Check if a decision string is a valid canonical or alias value.

    Args:
        decision_str: The routing decision string to validate.

    Returns:
        True if the decision is recognized, False otherwise.
    """
    return decision_str.lower().strip() in _COMBINED_MAP


def get_canonical_value(decision: RoutingDecision) -> str:
    """Get the canonical string value for a RoutingDecision enum.

    Args:
        decision: The RoutingDecision enum value.

    Returns:
        The canonical string value (e.g., "advance", "loop").
    """
    return decision.value
