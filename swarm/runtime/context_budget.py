"""
Context Budget Enforcement

Token limits and context budgets are features, not bugs.
This module enforces budget constraints to prevent context pollution.

Budget hierarchy (priority order):
- CRITICAL: Teaching notes, step spec (never drop)
- HIGH: Previous step output (may truncate)
- MEDIUM: Referenced artifacts (on-demand)
- LOW: History summary (drop first)

Usage:
    from swarm.runtime.context_budget import (
        Priority,
        BudgetConfig,
        ContentItem,
        BudgetResult,
        ContextBudgetEnforcer,
        enforce_context_budget,
        log_budget_overflow,
    )

    # Simple usage
    result = enforce_context_budget(
        teaching_notes=notes,
        previous_output=prev,
        artifacts={"adr.md": content},
        history=summary,
        budget=30000,
    )

    # Advanced usage with enforcer
    enforcer = ContextBudgetEnforcer(budget=30000)
    items = [
        create_content_item("teaching_notes", notes, Priority.CRITICAL),
        create_content_item("previous", prev, Priority.HIGH),
    ]
    result = enforcer.enforce(items)

See:
    - docs/CONTEXT_BUDGETS.md for philosophy
    - .claude/rules/governance/scarcity-enforcement.md for specification
    - swarm/runtime/history_priority.py for history-level priority
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import IntEnum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

# Module logger
logger = logging.getLogger(__name__)


# =============================================================================
# Priority Levels
# =============================================================================


class Priority(IntEnum):
    """Content priority levels for budget enforcement.

    Higher values = higher priority = less likely to be dropped.

    Mapping to scarcity-enforcement.md hierarchy:
        CRITICAL (4): Teaching notes, step spec - never drop
        HIGH (3): Previous step output - may truncate
        MEDIUM (2): Referenced artifacts - on-demand, drop before HIGH
        LOW (1): History summary - drop first
    """

    LOW = 1  # Drop first: history summary, older context
    MEDIUM = 2  # On-demand: referenced artifacts
    HIGH = 3  # May truncate: previous step output
    CRITICAL = 4  # Never drop: teaching notes, step spec


# =============================================================================
# Configuration
# =============================================================================


# Default budgets by step type (from scarcity-enforcement.md)
_BUDGET_DEFAULTS: Dict[str, Dict[str, int]] = {
    "shaping": {"input": 20000, "output": 5000},
    "implementation": {"input": 30000, "output": 10000},
    "critic": {"input": 25000, "output": 5000},
    "gate": {"input": 20000, "output": 3000},
}


@dataclass
class BudgetConfig:
    """Budget configuration for a step type.

    Attributes:
        input_budget: Maximum tokens for input context (default 30k)
        output_budget: Maximum tokens for output generation (default 10k)

    Note:
        These are GUIDANCE values, not hard limits. The enforcer uses
        input_budget for context selection. Output is not truncated.
    """

    input_budget: int = 30000
    output_budget: int = 10000

    @classmethod
    def for_step_type(cls, step_type: str) -> "BudgetConfig":
        """Get budget config for a step type.

        Args:
            step_type: One of "shaping", "implementation", "critic", "gate"

        Returns:
            BudgetConfig with appropriate limits
        """
        defaults = _BUDGET_DEFAULTS.get(step_type, {"input": 30000, "output": 10000})
        return cls(input_budget=defaults["input"], output_budget=defaults["output"])


# =============================================================================
# Content Items
# =============================================================================


@dataclass
class ContentItem:
    """A piece of content with priority and token count.

    ContentItems are the atomic units of context budget enforcement.
    Each item has content, a priority level, and metadata about whether
    it was truncated or dropped during enforcement.

    Attributes:
        key: Identifier for this content (e.g., "teaching_notes", "adr.md")
        content: The actual text content
        priority: Priority level for budget decisions
        tokens: Token count (computed lazily if not provided)
        truncated: Whether this item was truncated to fit budget
        dropped: Whether this item was dropped entirely
        original_tokens: Original token count before truncation
    """

    key: str
    content: str
    priority: Priority
    tokens: int = 0
    truncated: bool = False
    dropped: bool = False
    original_tokens: int = 0

    def __post_init__(self) -> None:
        """Track original tokens for overflow reporting."""
        if self.original_tokens == 0:
            self.original_tokens = self.tokens


# =============================================================================
# Budget Result
# =============================================================================


@dataclass
class BudgetResult:
    """Result of budget enforcement.

    Contains the final state after applying budget constraints, including
    which items were loaded, which were dropped, and overflow metadata.

    Attributes:
        loaded_items: Items included in context (may be truncated)
        dropped_items: Items excluded due to budget constraints
        total_tokens: Total tokens in loaded items
        budget: Original budget limit
        overflow: Whether budget was exceeded (items dropped or truncated)
        overflow_report: Detailed report when overflow occurred
    """

    loaded_items: List[ContentItem]
    dropped_items: List[ContentItem]
    total_tokens: int
    budget: int
    overflow: bool
    overflow_report: Optional[Dict[str, Any]] = None

    def get_loaded_content(self) -> Dict[str, str]:
        """Get map of key -> content for loaded items."""
        return {item.key: item.content for item in self.loaded_items}

    def get_truncation_note(self) -> Optional[str]:
        """Generate machine-readable truncation note if overflow occurred.

        Format matches CONTEXT_BUDGETS.md specification:
        [CONTEXT_TRUNCATED] Included X of Y items (Z dropped, budget: A/B tokens)
        """
        if not self.overflow:
            return None

        total_items = len(self.loaded_items) + len(self.dropped_items)
        dropped_count = len(self.dropped_items)
        truncated_count = sum(1 for item in self.loaded_items if item.truncated)

        # Build the note with proper formatting
        base = f"Included {len(self.loaded_items)} of {total_items} items"
        details = []
        if dropped_count > 0:
            details.append(f"{dropped_count} dropped")
        if truncated_count > 0:
            details.append(f"{truncated_count} truncated")
        details.append(f"budget: {self.total_tokens}/{self.budget} tokens")

        if details:
            return f"[CONTEXT_TRUNCATED] {base} ({', '.join(details)})"
        return f"[CONTEXT_TRUNCATED] {base}"


# =============================================================================
# Token Counting
# =============================================================================


def _get_tiktoken_encoder(model: str = "gpt-4"):
    """Lazy-load tiktoken encoder with fallback.

    Args:
        model: Model name for encoding (default gpt-4)

    Returns:
        Tiktoken encoder or None if unavailable
    """
    try:
        import tiktoken

        try:
            return tiktoken.encoding_for_model(model)
        except KeyError:
            # Fall back to cl100k_base for unknown models
            return tiktoken.get_encoding("cl100k_base")
    except ImportError:
        logger.debug("tiktoken not available, using character-based estimation")
        return None


def count_tokens_tiktoken(text: str, model: str = "gpt-4") -> int:
    """Count tokens using tiktoken.

    Args:
        text: Text to count tokens for
        model: Model name for encoding

    Returns:
        Token count
    """
    encoder = _get_tiktoken_encoder(model)
    if encoder is None:
        # Fallback: estimate ~4 chars per token
        return len(text) // 4

    return len(encoder.encode(text))


def count_tokens_chars(text: str) -> int:
    """Estimate tokens from character count.

    Uses the common heuristic of ~4 characters per token.
    This is a fallback when tiktoken is not available.

    Args:
        text: Text to estimate tokens for

    Returns:
        Estimated token count
    """
    return len(text) // 4


# =============================================================================
# Context Budget Enforcer
# =============================================================================


class ContextBudgetEnforcer:
    """Enforces context budgets for step execution.

    The enforcer applies budget constraints by:
    1. Sorting items by priority (CRITICAL first, LOW last)
    2. Loading items in priority order until budget is exhausted
    3. Optionally truncating HIGH priority items if they don't fit
    4. Never dropping or truncating CRITICAL items
    5. Logging overflow events for observability

    Example:
        >>> enforcer = ContextBudgetEnforcer(budget=30000)
        >>> items = [
        ...     ContentItem("notes", notes_text, Priority.CRITICAL),
        ...     ContentItem("prev", prev_text, Priority.HIGH),
        ... ]
        >>> result = enforcer.enforce(items)
        >>> if result.overflow:
        ...     print(result.get_truncation_note())
    """

    def __init__(
        self,
        budget: int,
        model: str = "gpt-4",
        token_counter: Optional[Callable[[str], int]] = None,
    ):
        """Initialize the enforcer.

        Args:
            budget: Maximum tokens for input context
            model: Model name for tiktoken encoding
            token_counter: Optional custom token counter function
        """
        self.budget = budget
        self.model = model
        self._token_counter = token_counter or (lambda t: count_tokens_tiktoken(t, model))
        self._encoder = None  # Lazy load

    def count_tokens(self, text: str) -> int:
        """Count tokens in text.

        Uses the configured token counter, which defaults to tiktoken
        with fallback to character-based estimation.

        Args:
            text: Text to count tokens for

        Returns:
            Token count
        """
        if not text:
            return 0
        return self._token_counter(text)

    def enforce(self, items: List[ContentItem]) -> BudgetResult:
        """Enforce budget on content items.

        Items are processed in priority order:
        1. CRITICAL items are always loaded (budget overflow is allowed)
        2. HIGH items are loaded, with optional truncation
        3. MEDIUM items are loaded if budget allows
        4. LOW items are loaded only if significant budget remains

        Args:
            items: List of ContentItem objects to process

        Returns:
            BudgetResult with loaded/dropped items and metadata
        """
        # Count tokens for items that don't have counts
        for item in items:
            if item.tokens == 0:
                item.tokens = self.count_tokens(item.content)
                item.original_tokens = item.tokens

        # Load items by priority
        loaded, dropped = self._load_by_priority(items)

        # Calculate totals
        total_tokens = sum(item.tokens for item in loaded)
        overflow = len(dropped) > 0 or any(item.truncated for item in loaded)

        # Build overflow report if needed
        overflow_report = None
        if overflow:
            overflow_report = self._build_overflow_report(loaded, dropped)

        return BudgetResult(
            loaded_items=loaded,
            dropped_items=dropped,
            total_tokens=total_tokens,
            budget=self.budget,
            overflow=overflow,
            overflow_report=overflow_report,
        )

    def _load_by_priority(
        self, items: List[ContentItem]
    ) -> Tuple[List[ContentItem], List[ContentItem]]:
        """Load items by priority until budget is exhausted.

        Priority loading rules:
        - CRITICAL: Always loaded, even if over budget
        - HIGH: Loaded if fits, truncated if partially fits
        - MEDIUM: Loaded only if fits completely
        - LOW: Loaded only if significant headroom remains

        Args:
            items: Items to load

        Returns:
            Tuple of (loaded_items, dropped_items)
        """
        # Sort by priority (highest first), preserving original order within priority
        sorted_items = sorted(
            enumerate(items), key=lambda x: (-x[1].priority.value, x[0])
        )

        loaded: List[ContentItem] = []
        dropped: List[ContentItem] = []
        used_tokens = 0

        for _idx, item in sorted_items:
            remaining = self.budget - used_tokens

            if item.priority == Priority.CRITICAL:
                # CRITICAL items are always loaded
                loaded.append(item)
                used_tokens += item.tokens

            elif item.priority == Priority.HIGH:
                if item.tokens <= remaining:
                    # Fits completely
                    loaded.append(item)
                    used_tokens += item.tokens
                elif remaining >= 100:  # At least some meaningful space
                    # Truncate to fit
                    truncated = self._truncate_item(item, remaining)
                    loaded.append(truncated)
                    used_tokens += truncated.tokens
                else:
                    # No room even for truncated version
                    item.dropped = True
                    dropped.append(item)

            elif item.priority == Priority.MEDIUM:
                if item.tokens <= remaining:
                    # Fits completely
                    loaded.append(item)
                    used_tokens += item.tokens
                else:
                    # Medium items are not truncated, just dropped
                    item.dropped = True
                    dropped.append(item)

            else:  # Priority.LOW
                # LOW items only loaded if significant headroom
                if item.tokens <= remaining and remaining >= self.budget * 0.1:
                    loaded.append(item)
                    used_tokens += item.tokens
                else:
                    item.dropped = True
                    dropped.append(item)

        return loaded, dropped

    def _truncate_item(self, item: ContentItem, max_tokens: int) -> ContentItem:
        """Truncate an item to fit within max_tokens.

        Truncation preserves the beginning of the content and adds
        a truncation marker at the end.

        Args:
            item: Item to truncate
            max_tokens: Maximum tokens for truncated content

        Returns:
            New ContentItem with truncated content
        """
        if max_tokens <= 0:
            return ContentItem(
                key=item.key,
                content="[TRUNCATED: No budget remaining]",
                priority=item.priority,
                tokens=10,
                truncated=True,
                dropped=False,
                original_tokens=item.original_tokens,
            )

        # Reserve tokens for truncation marker
        marker = "\n\n... [TRUNCATED]"
        marker_tokens = self.count_tokens(marker)
        available_tokens = max_tokens - marker_tokens

        if available_tokens <= 0:
            return ContentItem(
                key=item.key,
                content="[TRUNCATED]",
                priority=item.priority,
                tokens=5,
                truncated=True,
                dropped=False,
                original_tokens=item.original_tokens,
            )

        # Binary search for approximate truncation point
        # Start with character estimate and refine
        chars_per_token = len(item.content) / max(item.tokens, 1)
        estimated_chars = int(available_tokens * chars_per_token)

        # Adjust to not break mid-word
        truncated_content = item.content[:estimated_chars]
        last_space = truncated_content.rfind(" ")
        if last_space > estimated_chars * 0.8:  # Only use if not too far back
            truncated_content = truncated_content[:last_space]

        truncated_content += marker
        new_tokens = self.count_tokens(truncated_content)

        return ContentItem(
            key=item.key,
            content=truncated_content,
            priority=item.priority,
            tokens=new_tokens,
            truncated=True,
            dropped=False,
            original_tokens=item.original_tokens,
        )

    def _build_overflow_report(
        self, loaded: List[ContentItem], dropped: List[ContentItem]
    ) -> Dict[str, Any]:
        """Build detailed overflow report.

        Format matches scarcity-enforcement.md budget_overflow schema.
        """
        total_requested = sum(item.original_tokens for item in loaded + dropped)

        return {
            "requested": total_requested,
            "allowed": self.budget,
            "loaded": [
                {
                    "item": item.key,
                    "tokens": item.tokens,
                    "original_tokens": item.original_tokens,
                    "priority": item.priority.name,
                    "truncated": item.truncated,
                }
                for item in loaded
            ],
            "dropped": [
                {
                    "item": item.key,
                    "tokens": item.original_tokens,
                    "priority": item.priority.name,
                }
                for item in dropped
            ],
        }


# =============================================================================
# Budget Configuration Helpers
# =============================================================================


def get_budget_for_step(step_type: str, flow_key: str) -> BudgetConfig:
    """Get budget configuration for a step type.

    Resolves budget from the configuration hierarchy:
    1. Step-level override
    2. Flow-level override
    3. Profile-level override
    4. Global defaults

    Args:
        step_type: Type of step ("shaping", "implementation", "critic", "gate")
        flow_key: Flow key for flow-level overrides

    Returns:
        BudgetConfig with resolved limits
    """
    try:
        from swarm.config.runtime_config import get_resolved_context_budgets

        config = get_resolved_context_budgets(flow_key=flow_key)
        # Convert from chars to tokens (approximate 4 chars per token)
        input_budget = config.context_budget_chars // 4
        return BudgetConfig(input_budget=input_budget)
    except ImportError:
        logger.debug("runtime_config not available, using step type defaults")

    return BudgetConfig.for_step_type(step_type)


def create_content_item(
    key: str,
    content: str,
    priority: Priority,
    token_counter: Optional[Callable[[str], int]] = None,
) -> ContentItem:
    """Create a content item with token count.

    Convenience function to create ContentItem with automatic token counting.

    Args:
        key: Identifier for this content
        content: The text content
        priority: Priority level
        token_counter: Optional custom token counter

    Returns:
        ContentItem with tokens counted
    """
    counter = token_counter or count_tokens_tiktoken
    tokens = counter(content) if content else 0

    return ContentItem(
        key=key,
        content=content,
        priority=priority,
        tokens=tokens,
        original_tokens=tokens,
    )


# =============================================================================
# Main Entry Point
# =============================================================================


def enforce_context_budget(
    teaching_notes: str,
    previous_output: Optional[str],
    artifacts: Dict[str, str],
    history: Optional[str],
    budget: int,
    model: str = "gpt-4",
) -> BudgetResult:
    """Main entry point for context budget enforcement.

    This function provides a simple interface for common use cases,
    automatically assigning priorities based on content type:
    - teaching_notes: CRITICAL (never dropped)
    - previous_output: HIGH (may be truncated)
    - artifacts: MEDIUM (dropped before previous_output)
    - history: LOW (dropped first)

    Args:
        teaching_notes: Step-specific instructions (required)
        previous_output: Output from previous step (optional)
        artifacts: Map of artifact name -> content (optional)
        history: Historical context summary (optional)
        budget: Maximum tokens for input context

    Returns:
        BudgetResult with enforcement outcome

    Example:
        >>> result = enforce_context_budget(
        ...     teaching_notes="## Objective\\nImplement auth...",
        ...     previous_output="Step 2 produced: ...",
        ...     artifacts={"adr.md": "# ADR-001..."},
        ...     history="Previous flow: Signal...",
        ...     budget=30000,
        ... )
        >>> print(result.total_tokens)
        >>> if result.overflow:
        ...     print(result.get_truncation_note())
    """
    items: List[ContentItem] = []

    # Teaching notes are CRITICAL - never dropped
    if teaching_notes:
        items.append(
            create_content_item("teaching_notes", teaching_notes, Priority.CRITICAL)
        )

    # Previous output is HIGH - may be truncated
    if previous_output:
        items.append(
            create_content_item("previous_output", previous_output, Priority.HIGH)
        )

    # Artifacts are MEDIUM - dropped before previous output
    for name, content in artifacts.items():
        if content:
            items.append(create_content_item(f"artifact:{name}", content, Priority.MEDIUM))

    # History is LOW - dropped first
    if history:
        items.append(create_content_item("history", history, Priority.LOW))

    enforcer = ContextBudgetEnforcer(budget=budget, model=model)
    return enforcer.enforce(items)


# =============================================================================
# Budget Overflow Logging
# =============================================================================


@dataclass
class BudgetOverflowEvent:
    """Event logged when budget is exceeded.

    Captures all relevant context for debugging and observability.

    Attributes:
        step_id: The step that experienced overflow
        flow_key: The flow being executed
        requested: Total tokens requested
        allowed: Budget limit that was enforced
        dropped: List of dropped item descriptions
        timestamp: When the overflow occurred (ISO format)
    """

    step_id: str
    flow_key: str
    requested: int
    allowed: int
    dropped: List[Dict[str, Any]]
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


def log_budget_overflow(event: BudgetOverflowEvent, run_base: Path) -> Path:
    """Log a budget overflow event to the run directory.

    Events are appended to a JSONL file for time-series analysis.
    This enables tracking of budget pressure across runs.

    Args:
        event: The overflow event to log
        run_base: Base path for run artifacts (RUN_BASE/<flow>/)

    Returns:
        Path to the log file

    Example:
        >>> event = BudgetOverflowEvent(
        ...     step_id="implement",
        ...     flow_key="build",
        ...     requested=45000,
        ...     allowed=30000,
        ...     dropped=[{"item": "history", "tokens": 15000}],
        ... )
        >>> log_budget_overflow(event, Path("swarm/runs/abc/build"))
    """
    # Ensure log directory exists
    log_dir = run_base / "budget_logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    log_file = log_dir / "overflow_events.jsonl"

    # Append event as JSONL
    event_dict = {
        "step_id": event.step_id,
        "flow_key": event.flow_key,
        "requested": event.requested,
        "allowed": event.allowed,
        "dropped": event.dropped,
        "timestamp": event.timestamp,
    }

    with open(log_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(event_dict) + "\n")

    logger.info(
        "Budget overflow logged: step=%s, requested=%d, allowed=%d, dropped=%d items",
        event.step_id,
        event.requested,
        event.allowed,
        len(event.dropped),
    )

    return log_file


def log_budget_result(
    result: BudgetResult,
    step_id: str,
    flow_key: str,
    run_base: Path,
) -> Optional[Path]:
    """Log budget result if overflow occurred.

    Convenience function that creates and logs an overflow event
    from a BudgetResult if overflow occurred.

    Args:
        result: The budget enforcement result
        step_id: Current step ID
        flow_key: Current flow key
        run_base: Base path for run artifacts

    Returns:
        Path to log file if overflow was logged, None otherwise
    """
    if not result.overflow:
        return None

    event = BudgetOverflowEvent(
        step_id=step_id,
        flow_key=flow_key,
        requested=result.overflow_report.get("requested", 0) if result.overflow_report else 0,
        allowed=result.budget,
        dropped=result.overflow_report.get("dropped", []) if result.overflow_report else [],
    )

    return log_budget_overflow(event, run_base)


# =============================================================================
# Integration with ContextPack
# =============================================================================


def apply_budget_to_context_pack(
    teaching_notes_content: str,
    previous_envelope_content: Optional[str],
    artifact_contents: Dict[str, str],
    history_summary: Optional[str],
    budget: int,
    step_id: str,
    flow_key: str,
    run_base: Optional[Path] = None,
) -> Tuple[Dict[str, str], Optional[BudgetResult]]:
    """Apply budget enforcement to context pack contents.

    This function is designed to integrate with context_pack.py's
    build_context_pack function. It takes the raw content that would
    be loaded into a context pack and returns budgeted content.

    Args:
        teaching_notes_content: Rendered teaching notes
        previous_envelope_content: Serialized previous envelope
        artifact_contents: Map of artifact name -> content
        history_summary: Compressed history summary
        budget: Token budget to enforce
        step_id: Step ID for logging
        flow_key: Flow key for logging
        run_base: Optional run base for overflow logging

    Returns:
        Tuple of (budgeted_content_dict, budget_result)
        - budgeted_content_dict maps keys to budgeted content
        - budget_result contains enforcement metadata (None if no enforcement needed)

    Example:
        >>> contents, result = apply_budget_to_context_pack(
        ...     teaching_notes_content="## Objective...",
        ...     previous_envelope_content="...",
        ...     artifact_contents={"adr.md": "..."},
        ...     history_summary="...",
        ...     budget=30000,
        ...     step_id="implement",
        ...     flow_key="build",
        ... )
        >>> if result and result.overflow:
        ...     print(f"Context truncated: {result.get_truncation_note()}")
    """
    result = enforce_context_budget(
        teaching_notes=teaching_notes_content,
        previous_output=previous_envelope_content,
        artifacts=artifact_contents,
        history=history_summary,
        budget=budget,
    )

    # Log overflow if it occurred and run_base is provided
    if result.overflow and run_base:
        log_budget_result(result, step_id, flow_key, run_base)

    return result.get_loaded_content(), result


# =============================================================================
# Priority Helpers (Integration with history_priority.py)
# =============================================================================


def priority_from_history_priority(history_priority_value: int) -> Priority:
    """Convert history_priority.HistoryPriority to context_budget.Priority.

    This enables integration between the history-level priority system
    (which classifies history items by agent) and the budget-level
    priority system (which classifies content by type).

    Args:
        history_priority_value: Integer value from HistoryPriority enum

    Returns:
        Corresponding Priority enum value

    Note:
        HistoryPriority uses 0-3 (LOW=0, MEDIUM=1, HIGH=2, CRITICAL=3)
        Priority uses 1-4 (LOW=1, MEDIUM=2, HIGH=3, CRITICAL=4)
    """
    mapping = {
        0: Priority.LOW,
        1: Priority.MEDIUM,
        2: Priority.HIGH,
        3: Priority.CRITICAL,
    }
    return mapping.get(history_priority_value, Priority.MEDIUM)


def classify_content_priority(key: str) -> Priority:
    """Classify content priority based on key/name.

    This provides a default priority classification for content types
    when not explicitly specified. It aligns with scarcity-enforcement.md.

    Args:
        key: Content identifier (e.g., "teaching_notes", "adr.md")

    Returns:
        Appropriate Priority level
    """
    key_lower = key.lower()

    # CRITICAL: Core step guidance
    if any(term in key_lower for term in ["teaching_notes", "step_spec", "objective"]):
        return Priority.CRITICAL

    # HIGH: Recent context and key artifacts
    if any(
        term in key_lower
        for term in [
            "previous",
            "recent",
            "envelope",
            "adr",
            "requirements",
            "decision",
            "critique",
        ]
    ):
        return Priority.HIGH

    # LOW: Historical and summary content
    if any(
        term in key_lower
        for term in ["history", "summary", "older", "archive", "learnings"]
    ):
        return Priority.LOW

    # MEDIUM: Default for artifacts and other content
    return Priority.MEDIUM
