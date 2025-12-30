"""History priority classification for smarter context selection.

This module provides priority-based classification of history items to enable
intelligent truncation when context budgets are exceeded. Instead of blindly
dropping oldest history first, we can drop low-value items before high-value ones.

Priority Levels (highest to lowest):
    CRITICAL (3): Gating decisions, critics, core implementation outputs
    HIGH (2): Requirements, design specs, ADRs, verification reports
    MEDIUM (1): Cross-cutting analysis, context loading, risk assessment
    LOW (0): Preprocessing, communication, utility, post-flight analysis

Usage:
    from swarm.runtime.history_priority import (
        HistoryPriority,
        classify_history_item,
        prioritize_history,
    )

    # Classify a single item
    priority = classify_history_item(history_item)

    # Sort history by priority (highest first, then by recency)
    sorted_history = prioritize_history(ctx.history)

Design Philosophy:
    - Critical path agents (decisions, critics, implementations) are preserved
    - Foundation context (requirements, ADRs) is kept when possible
    - Utility and post-flight outputs are dropped first when budget is tight
    - Recency is secondary to importance: a critical old step beats a low-value recent one
"""

from __future__ import annotations

import logging
from enum import IntEnum
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)


class HistoryPriority(IntEnum):
    """Priority levels for history items.

    Higher values = higher priority = more likely to be kept.
    """

    # Drop first - utility, post-flight, communication
    LOW = 0

    # Consider dropping - preprocessing, shaping, supplementary
    MEDIUM = 1

    # Usually keep - foundation specs, core path agents
    HIGH = 2

    # Always keep - final decisions, critics, core implementations
    CRITICAL = 3


# =============================================================================
# Agent Classification Rules
# =============================================================================

# P1 - CRITICAL: Gating decisions, critics, core implementation
CRITICAL_AGENT_PATTERNS = frozenset(
    {
        # Final decision makers
        "merge-decider",
        "deploy-decider",
        # Critics (harsh reviews that shape quality)
        "requirements-critic",
        "design-critic",
        "test-critic",
        "code-critic",
        "ux-critic",
        # Core implementation agents
        "code-implementer",
        "test-author",
        # Self-review (completion proof)
        "self-reviewer",
    }
)

# P2 - HIGH: Foundation specs, verification, design
HIGH_AGENT_PATTERNS = frozenset(
    {
        # Requirements foundation
        "requirements-author",
        "bdd-author",
        # Design and architecture
        "adr-author",
        "interface-designer",
        "observability-designer",
        "design-optioneer",
        "work-planner",
        "test-strategist",
        # Gate verification
        "receipt-checker",
        "contract-enforcer",
        "security-scanner",
        "coverage-enforcer",
        "gate-fixer",
        # Deployment verification
        "smoke-verifier",
        "deploy-monitor",
    }
)

# P3 - MEDIUM: Cross-cutting analysis, context, risk
MEDIUM_AGENT_PATTERNS = frozenset(
    {
        # Cross-cutting agents
        "clarifier",
        "risk-analyst",
        "policy-analyst",
        # Analysis and context
        "impact-analyzer",
        "context-loader",
        # Fixers (important but not decision-making)
        "fixer",
        "mutator",
    }
)

# P4 - LOW: Preprocessing, communication, utility, post-flight
LOW_AGENT_PATTERNS = frozenset(
    {
        # Early preprocessing
        "signal-normalizer",
        "problem-framer",
        "scope-assessor",
        # Communication
        "gh-reporter",
        # Documentation (supplementary)
        "doc-writer",
        # Post-flight analysis
        "flow-historian",
        "artifact-auditor",
        "regression-analyst",
        "learning-synthesizer",
        "feedback-applier",
        # Utility
        "swarm-ops",
        "ux-implementer",
        # Git operations (mechanical)
        "repo-operator",
    }
)


# =============================================================================
# Artifact Classification Rules
# =============================================================================

# High-value artifact patterns (boost priority)
HIGH_VALUE_ARTIFACTS = frozenset(
    {
        "decision",
        "critique",
        "requirements",
        "adr",
        "contracts",
        "receipt",
        "build_receipt",
    }
)

# Low-value artifact patterns (reduce priority)
LOW_VALUE_ARTIFACTS = frozenset(
    {
        "summary",
        "history",
        "learnings",
        "feedback",
        "audit",
    }
)


def classify_history_item(item: Dict[str, Any]) -> HistoryPriority:
    """Classify a history item by priority based on agent and content.

    Classification is based on:
    1. Agent key (primary classifier)
    2. Step ID patterns (secondary)
    3. Output artifact patterns (tertiary)

    Args:
        item: A history item dict with keys like 'step_id', 'agent_key', 'output'

    Returns:
        HistoryPriority level for this item
    """
    # Extract identifiers
    # Try agent_key first, then first element of agents list
    agent_key_raw = item.get("agent_key")
    if not agent_key_raw:
        agents_list = item.get("agents")
        if isinstance(agents_list, list) and agents_list:
            agent_key_raw = agents_list[0]
    agent_key = str(agent_key_raw or "").lower()
    step_id = str(item.get("step_id", "")).lower()
    output = str(item.get("output", ""))[:1000].lower()  # Sample output for patterns

    # Primary classification: exact agent match
    if agent_key:
        if agent_key in CRITICAL_AGENT_PATTERNS:
            return HistoryPriority.CRITICAL
        if agent_key in HIGH_AGENT_PATTERNS:
            return HistoryPriority.HIGH
        if agent_key in MEDIUM_AGENT_PATTERNS:
            return HistoryPriority.MEDIUM
        if agent_key in LOW_AGENT_PATTERNS:
            return HistoryPriority.LOW

    # Secondary classification: step_id patterns
    # Critics and deciders
    if any(p in step_id for p in ["critic", "decider", "decision"]):
        return HistoryPriority.CRITICAL
    if any(p in step_id for p in ["implement", "author", "test"]):
        return HistoryPriority.HIGH
    if any(p in step_id for p in ["analyze", "assess", "load", "risk"]):
        return HistoryPriority.MEDIUM
    if any(p in step_id for p in ["normalize", "frame", "report", "history"]):
        return HistoryPriority.LOW

    # Tertiary classification: artifact patterns in output
    for artifact in HIGH_VALUE_ARTIFACTS:
        if artifact in output:
            return HistoryPriority.HIGH

    for artifact in LOW_VALUE_ARTIFACTS:
        if artifact in output:
            return HistoryPriority.LOW

    # Default: MEDIUM (safe middle ground)
    return HistoryPriority.MEDIUM


def prioritize_history(
    history: List[Dict[str, Any]],
    preserve_order_within_priority: bool = True,
) -> List[Tuple[HistoryPriority, int, Dict[str, Any]]]:
    """Sort history items by priority, then by recency.

    Returns a list of tuples: (priority, original_index, item)
    sorted by priority descending, then original index ascending (most recent last).

    Args:
        history: List of history item dicts
        preserve_order_within_priority: If True, items with same priority
            maintain their original order (chronological). If False, no
            order guarantee within priority level.

    Returns:
        List of (priority, original_index, item) tuples, sorted for optimal inclusion.
        Iterate from start to include highest-priority items first.
    """
    decorated = [(classify_history_item(item), idx, item) for idx, item in enumerate(history)]

    # Sort by:
    # 1. Priority descending (CRITICAL=3 first, LOW=0 last)
    # 2. Index ascending (earlier items first within same priority)
    #    This ensures chronological order within each priority tier
    if preserve_order_within_priority:
        decorated.sort(key=lambda x: (-x[0], x[1]))
    else:
        decorated.sort(key=lambda x: -x[0])

    return decorated


def get_priority_label(priority: HistoryPriority) -> str:
    """Get human-readable label for a priority level."""
    labels = {
        HistoryPriority.CRITICAL: "CRITICAL",
        HistoryPriority.HIGH: "HIGH",
        HistoryPriority.MEDIUM: "MEDIUM",
        HistoryPriority.LOW: "LOW",
    }
    return labels.get(priority, "UNKNOWN")


def summarize_priority_distribution(history: List[Dict[str, Any]]) -> Dict[str, int]:
    """Get counts of items at each priority level.

    Useful for debugging and observability.

    Args:
        history: List of history item dicts

    Returns:
        Dict mapping priority labels to counts
    """
    counts = {
        "CRITICAL": 0,
        "HIGH": 0,
        "MEDIUM": 0,
        "LOW": 0,
    }

    for item in history:
        priority = classify_history_item(item)
        label = get_priority_label(priority)
        counts[label] += 1

    return counts
