"""
progress_tracker.py - Progress Tracker for Stall Detection (Elephant Protocol)

The Elephant Protocol: Progress is measured by the derivative (velocity),
not the budget. If error signatures remain identical, velocity is zero
and we're stalled. If they change, velocity is positive and we continue.

This module provides a ProgressTracker that:
1. Computes normalized error signatures from output text
2. Tracks consecutive identical signatures across iterations
3. Detects stalls when the same signature appears N times in a row
4. Provides velocity metrics for routing decisions

Design Philosophy:
    - Pure traditional tooling - no LLM calls needed
    - Error normalization removes noise (timestamps, line numbers, paths)
    - Velocity = unique signatures / total iterations (0.0 = stalled, 1.0 = progressing)
    - Integrates with routing driver to inform candidate generation

Usage:
    from swarm.runtime.progress_tracker import (
        ProgressTracker,
        StallInfo,
        compute_error_signature,
    )

    # Create tracker for a microloop
    tracker = ProgressTracker(stall_threshold=3)

    # After each iteration, record the error output
    tracker.record_iteration("TypeError: foo has no attribute 'bar'")

    # Check if we're stalled
    if tracker.is_stalled():
        # Trigger a sidequest or escalate
        pass

    # Get velocity for routing decisions
    velocity = tracker.get_velocity()  # 0.0-1.0, lower = more stalled

    # Get stall info for routing explanation
    stall_info = tracker.get_stall_info()
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# =============================================================================
# Normalization Patterns
# =============================================================================

# Patterns to remove during normalization (noise that varies but doesn't indicate progress)
NOISE_PATTERNS = [
    # Timestamps in various formats
    r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}",  # ISO timestamps
    r"\d{2}:\d{2}:\d{2}",  # Time only
    r"\d+\.\d+s",  # Duration in seconds
    # Line numbers (vary across runs)
    r"line \d+",
    r":\d+:\d+",  # :line:col
    r"\[\d+\]",  # Array indices
    # File paths (normalize to basename)
    r"[A-Za-z]:\\[^\s]+",  # Windows paths
    r"/[^\s]+/",  # Unix paths (middle parts)
    # Memory addresses and hex values
    r"0x[0-9a-fA-F]+",
    r"at 0x[0-9a-fA-F]+",
    # UUIDs and run IDs
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    r"run-[a-z0-9]+",
    # Process IDs
    r"pid[=:\s]\d+",
    r"process \d+",
    # Iteration/attempt counters
    r"attempt \d+",
    r"iteration \d+",
    r"try \d+",
]

# Compiled patterns for efficiency
_NOISE_REGEX = re.compile("|".join(NOISE_PATTERNS), re.IGNORECASE)


# =============================================================================
# Data Types
# =============================================================================


@dataclass
class StallInfo:
    """Information about stall detection state.

    Attributes:
        is_stalled: Whether the tracker considers progress stalled.
        stall_count: Number of consecutive identical signatures.
        velocity: Progress velocity (0.0 = fully stalled, 1.0 = every iteration different).
        last_signature: Most recent error signature (for debugging).
        unique_signatures: Number of unique signatures seen in tracking window.
        total_iterations: Total iterations recorded.
        stall_started_at: When the stall began (if stalled).
        recommendation: Suggested action based on stall state.
    """

    is_stalled: bool = False
    stall_count: int = 0
    velocity: float = 1.0
    last_signature: str = ""
    unique_signatures: int = 0
    total_iterations: int = 0
    stall_started_at: Optional[datetime] = None
    recommendation: str = "continue"  # continue, investigate, escalate


def stall_info_to_dict(info: StallInfo) -> Dict[str, Any]:
    """Convert StallInfo to dictionary for serialization."""
    result = {
        "is_stalled": info.is_stalled,
        "stall_count": info.stall_count,
        "velocity": round(info.velocity, 3),
        "last_signature": info.last_signature,
        "unique_signatures": info.unique_signatures,
        "total_iterations": info.total_iterations,
        "recommendation": info.recommendation,
    }
    if info.stall_started_at:
        result["stall_started_at"] = info.stall_started_at.isoformat()
    return result


def stall_info_from_dict(data: Dict[str, Any]) -> StallInfo:
    """Parse StallInfo from dictionary."""
    stall_started_at = None
    if "stall_started_at" in data and data["stall_started_at"]:
        stall_started_at = datetime.fromisoformat(data["stall_started_at"])

    return StallInfo(
        is_stalled=data.get("is_stalled", False),
        stall_count=data.get("stall_count", 0),
        velocity=data.get("velocity", 1.0),
        last_signature=data.get("last_signature", ""),
        unique_signatures=data.get("unique_signatures", 0),
        total_iterations=data.get("total_iterations", 0),
        stall_started_at=stall_started_at,
        recommendation=data.get("recommendation", "continue"),
    )


# =============================================================================
# Signature Computation
# =============================================================================


def normalize_error_output(error_output: str) -> str:
    """Normalize error output by removing noise.

    Removes timestamps, line numbers, file paths, memory addresses,
    and other elements that vary between runs but don't indicate
    different errors.

    Args:
        error_output: Raw error text from test/build output.

    Returns:
        Normalized error text suitable for signature computation.
    """
    # Lowercase for case-insensitive matching
    normalized = error_output.lower()

    # Strip leading/trailing whitespace
    normalized = normalized.strip()

    # Remove noise patterns
    normalized = _NOISE_REGEX.sub("", normalized)

    # Collapse multiple whitespace to single space
    normalized = re.sub(r"\s+", " ", normalized)

    # Strip again after substitutions
    normalized = normalized.strip()

    return normalized


def compute_error_signature(error_output: str) -> str:
    """Compute a normalized signature from error output.

    The signature is a short hash that represents the "essence" of an error,
    ignoring noise like timestamps, line numbers, and file paths.

    Args:
        error_output: Raw error text from test/build output.

    Returns:
        16-character hex signature (SHA256 truncated).
    """
    normalized = normalize_error_output(error_output)
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]


def extract_error_category(error_output: str) -> str:
    """Extract the error category/type from error output.

    Identifies common error patterns for classification.

    Args:
        error_output: Raw error text.

    Returns:
        Error category string (e.g., "type_error", "import_error", "assertion").
    """
    lower = error_output.lower()

    # Python exceptions
    if "typeerror" in lower:
        return "type_error"
    if "importerror" in lower or "modulenotfounderror" in lower:
        return "import_error"
    if "attributeerror" in lower:
        return "attribute_error"
    if "nameerror" in lower:
        return "name_error"
    if "assertionerror" in lower:
        return "assertion_error"
    if "valueerror" in lower:
        return "value_error"
    if "keyerror" in lower:
        return "key_error"
    if "indexerror" in lower:
        return "index_error"
    if "syntaxerror" in lower:
        return "syntax_error"
    if "runtimeerror" in lower:
        return "runtime_error"

    # Test framework patterns
    if "failed" in lower and "test" in lower:
        return "test_failure"
    if "assertion" in lower:
        return "assertion"
    if "timeout" in lower:
        return "timeout"
    if "flaky" in lower or "intermittent" in lower:
        return "flaky"

    # Build/compile patterns
    if "compile" in lower and "error" in lower:
        return "compile_error"
    if "linker" in lower or "undefined reference" in lower:
        return "linker_error"
    if "missing" in lower and "dependency" in lower:
        return "dependency"

    # Generic
    if "error" in lower:
        return "generic_error"
    if "exception" in lower:
        return "exception"
    if "failed" in lower:
        return "failure"

    return "unknown"


# =============================================================================
# Progress Tracker
# =============================================================================


@dataclass
class ProgressTracker:
    """Track progress velocity for stall detection (Elephant Protocol).

    The Elephant Protocol: Progress is measured by the derivative (velocity),
    not the budget. If error signatures remain identical, velocity is zero
    and we're stalled. If they change, velocity is positive and we continue.

    The tracker maintains a history of error signatures and detects when
    the same signature appears consecutively, indicating no progress is
    being made despite continued iteration.

    Attributes:
        error_signatures: History of error signatures.
        stall_threshold: Number of identical signatures before declaring stall.
        _timestamps: Timestamp for each recorded iteration.
        _categories: Error category for each iteration (optional).
    """

    error_signatures: List[str] = field(default_factory=list)
    stall_threshold: int = 3  # Number of identical signatures before stall

    # Internal tracking
    _timestamps: List[datetime] = field(default_factory=list, repr=False)
    _categories: List[str] = field(default_factory=list, repr=False)
    _stall_started_at: Optional[datetime] = field(default=None, repr=False)

    def compute_signature(self, error_output: str) -> str:
        """Compute normalized signature from error output.

        This is a convenience method wrapping the module-level function.

        Args:
            error_output: Raw error text.

        Returns:
            16-character hex signature.
        """
        return compute_error_signature(error_output)

    def record_iteration(self, error_output: str) -> None:
        """Record an iteration's error output.

        Args:
            error_output: Raw error text from this iteration.
        """
        sig = self.compute_signature(error_output)
        self.error_signatures.append(sig)
        self._timestamps.append(datetime.now(timezone.utc))
        self._categories.append(extract_error_category(error_output))

        # Track when stall started
        if self.is_stalled() and self._stall_started_at is None:
            # Stall started on the first repeated signature
            stall_count = self.get_stall_count()
            if stall_count >= self.stall_threshold and len(self._timestamps) >= stall_count:
                self._stall_started_at = self._timestamps[-stall_count]
        elif not self.is_stalled():
            self._stall_started_at = None

    def record_success(self) -> None:
        """Record a successful iteration (no error).

        This breaks the stall pattern since success is a different outcome.
        """
        # Use a special signature for success
        success_sig = "SUCCESS_" + hashlib.sha256(b"success").hexdigest()[:8]
        self.error_signatures.append(success_sig)
        self._timestamps.append(datetime.now(timezone.utc))
        self._categories.append("success")
        self._stall_started_at = None

    def is_stalled(self) -> bool:
        """Check if we're stalled (same error N times).

        Returns:
            True if the last N signatures are identical.
        """
        if len(self.error_signatures) < self.stall_threshold:
            return False
        recent = self.error_signatures[-self.stall_threshold :]
        return len(set(recent)) == 1

    def get_stall_count(self) -> int:
        """Get count of consecutive identical signatures.

        Returns:
            Number of consecutive identical signatures at the end.
        """
        if not self.error_signatures:
            return 0
        last_sig = self.error_signatures[-1]
        count = 0
        for sig in reversed(self.error_signatures):
            if sig == last_sig:
                count += 1
            else:
                break
        return count

    def get_velocity(self) -> float:
        """Get progress velocity.

        Velocity is the ratio of unique signatures to total iterations
        in the recent window (stall_threshold iterations).

        Returns:
            0.0 = stalled (all same), 1.0 = maximum progress (all different).
        """
        if len(self.error_signatures) < 2:
            return 1.0
        # Use recent window for velocity calculation
        window = min(len(self.error_signatures), self.stall_threshold)
        recent = self.error_signatures[-window:]
        unique = len(set(recent))
        return unique / len(recent)

    def get_stall_info(self) -> StallInfo:
        """Get comprehensive stall information.

        Returns:
            StallInfo with all stall detection metrics.
        """
        is_stalled = self.is_stalled()
        stall_count = self.get_stall_count()
        velocity = self.get_velocity()

        # Determine recommendation
        if not is_stalled:
            recommendation = "continue"
        elif stall_count >= self.stall_threshold * 2:
            recommendation = "escalate"
        else:
            recommendation = "investigate"

        return StallInfo(
            is_stalled=is_stalled,
            stall_count=stall_count,
            velocity=velocity,
            last_signature=self.error_signatures[-1] if self.error_signatures else "",
            unique_signatures=len(set(self.error_signatures)),
            total_iterations=len(self.error_signatures),
            stall_started_at=self._stall_started_at,
            recommendation=recommendation,
        )

    def get_error_category(self) -> Optional[str]:
        """Get the error category of the most recent iteration.

        Returns:
            Error category string, or None if no iterations recorded.
        """
        if not self._categories:
            return None
        return self._categories[-1]

    def get_signature_history(self) -> List[Tuple[str, str, datetime]]:
        """Get full history of signatures with categories and timestamps.

        Returns:
            List of (signature, category, timestamp) tuples.
        """
        result = []
        for i in range(len(self.error_signatures)):
            sig = self.error_signatures[i]
            cat = self._categories[i] if i < len(self._categories) else "unknown"
            ts = self._timestamps[i] if i < len(self._timestamps) else datetime.now(timezone.utc)
            result.append((sig, cat, ts))
        return result

    def reset(self) -> None:
        """Reset the tracker (e.g., after successful resolution)."""
        self.error_signatures.clear()
        self._timestamps.clear()
        self._categories.clear()
        self._stall_started_at = None

    def __len__(self) -> int:
        """Return number of iterations recorded."""
        return len(self.error_signatures)


# =============================================================================
# Integration with Routing
# =============================================================================


def build_stall_context(tracker: ProgressTracker) -> Dict[str, Any]:
    """Build stall context for sidequest evaluation.

    Creates a context dictionary that can be passed to the sidequest
    catalog's trigger evaluation.

    Args:
        tracker: ProgressTracker with recorded iterations.

    Returns:
        Dictionary with stall signals for sidequest triggers.
    """
    info = tracker.get_stall_info()
    return {
        "stall_signals": {
            "is_stalled": info.is_stalled,
            "stall_count": info.stall_count,
            "velocity": info.velocity,
            "same_failure_signature": info.stall_count >= 2,
        },
        "error_category": tracker.get_error_category() or "unknown",
    }


def should_suggest_sidequest(tracker: ProgressTracker) -> Tuple[bool, str]:
    """Determine if a sidequest should be suggested based on stall state.

    Args:
        tracker: ProgressTracker with recorded iterations.

    Returns:
        Tuple of (should_suggest, reason).
    """
    info = tracker.get_stall_info()

    if not info.is_stalled:
        return False, "Not stalled"

    if info.recommendation == "escalate":
        return True, f"Stalled for {info.stall_count} iterations with same error, escalation recommended"

    if info.recommendation == "investigate":
        return True, f"Stalled for {info.stall_count} iterations, investigation sidequest suggested"

    return False, "No sidequest needed"


# =============================================================================
# Factory Functions
# =============================================================================


def create_tracker(stall_threshold: int = 3) -> ProgressTracker:
    """Create a new ProgressTracker with the specified threshold.

    Args:
        stall_threshold: Number of identical signatures before declaring stall.

    Returns:
        New ProgressTracker instance.
    """
    return ProgressTracker(stall_threshold=stall_threshold)


def tracker_to_dict(tracker: ProgressTracker) -> Dict[str, Any]:
    """Serialize ProgressTracker to dictionary.

    Args:
        tracker: ProgressTracker to serialize.

    Returns:
        Dictionary representation.
    """
    return {
        "error_signatures": list(tracker.error_signatures),
        "stall_threshold": tracker.stall_threshold,
        "timestamps": [ts.isoformat() for ts in tracker._timestamps],
        "categories": list(tracker._categories),
        "stall_started_at": (
            tracker._stall_started_at.isoformat() if tracker._stall_started_at else None
        ),
    }


def tracker_from_dict(data: Dict[str, Any]) -> ProgressTracker:
    """Deserialize ProgressTracker from dictionary.

    Args:
        data: Dictionary representation.

    Returns:
        ProgressTracker instance.
    """
    tracker = ProgressTracker(
        error_signatures=list(data.get("error_signatures", [])),
        stall_threshold=data.get("stall_threshold", 3),
    )
    tracker._timestamps = [
        datetime.fromisoformat(ts) for ts in data.get("timestamps", [])
    ]
    tracker._categories = list(data.get("categories", []))
    if data.get("stall_started_at"):
        tracker._stall_started_at = datetime.fromisoformat(data["stall_started_at"])
    return tracker
