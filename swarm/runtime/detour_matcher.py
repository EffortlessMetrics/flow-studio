"""
Automatic Detour Routing: Signature Matching

When a failure signature is detected, route to known fixes
instead of generic iteration. This saves tokens and time.

Known signatures:
- lint_errors -> auto-linter skill
- missing_import -> import-fixer
- type_mismatch -> type-annotator
- test_fixture_missing -> test-setup
- upstream_diverged -> Flow 8 (Reset)

The core principle: Known problems deserve known solutions.
Match signatures to detours before generic iteration.
Detours are cheap; re-discovery is expensive.

Usage:
    from swarm.runtime.detour_matcher import (
        DetourMatcher,
        create_detour_matcher,
        should_detour,
        get_detour_routing_decision,
    )

    matcher = create_detour_matcher()
    match = matcher.match(forensics, step_id)
    if match.matched:
        routing = get_detour_routing_decision(match)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


# =============================================================================
# Detour Target Enumeration
# =============================================================================


class DetourTarget(Enum):
    """Known detour targets.

    Each target corresponds to a skill or flow that can handle a specific
    class of failures automatically.
    """

    AUTO_LINTER = "auto-linter"
    IMPORT_FIXER = "import-fixer"
    TYPE_ANNOTATOR = "type-annotator"
    TEST_FIXTURE = "test-fixture-fixer"
    DEP_RESOLVER = "dependency-resolver"
    CONFLICT_RESOLVER = "conflict-resolver"
    FLOW_8_RESET = "flow-8-reset"


# =============================================================================
# Built-in Signature Patterns
# =============================================================================

# Lint error patterns - match common linter output formats
LINT_ERROR_PATTERNS = [
    r"error:\s+.*lint",
    r"\d+\s+error(s)?\s+found",
    r"eslint.*error",
    r"flake8.*E\d{3}",
    r"clippy.*error",
    r"ruff.*error",
    r"black.*would reformat",
    r"isort.*ERROR",
    r"mypy:\s+error",
    r"pylint.*E\d{4}",
]

# Import error patterns - missing module or import failures
IMPORT_ERROR_PATTERNS = [
    r"ImportError:\s+No module named",
    r"ModuleNotFoundError:",
    r"Cannot find module",
    r"Module not found:",
    r"import\s+error",
    r"No module named\s+'[^']+'",
    r"cannot import name\s+'[^']+'",
]

# Type error patterns - type checking failures
TYPE_ERROR_PATTERNS = [
    r"TypeError:",
    r"type.*mismatch",
    r"mypy.*error",
    r"Expected.*got",
    r"Argument.*has incompatible type",
    r"Incompatible types",
    r"Type\s+error",
    r"pyright.*error",
]

# Test fixture patterns - missing pytest fixtures or test setup
TEST_FIXTURE_PATTERNS = [
    r"fixture\s+'[^']+'\s+not found",
    r"FixtureNotFoundError",
    r"fixture.*does not exist",
    r"Unknown fixture",
    r"conftest.*fixture",
]

# Dependency patterns - missing package dependencies
DEPENDENCY_ERROR_PATTERNS = [
    r"ModuleNotFoundError:\s+No module named\s+'(?!\.)",  # External module, not relative
    r"Could not find a version that satisfies",
    r"No matching distribution found",
    r"Package.*not found",
    r"pip.*ERROR",
    r"npm ERR!.*not found",
    r"cannot resolve.*dependency",
]

# Git conflict patterns
CONFLICT_PATTERNS = [
    r"CONFLICT.*Merge conflict",
    r"<<<<<<< HEAD",
    r"=======",
    r">>>>>>> ",
    r"Automatic merge failed",
    r"fix conflicts and then commit",
]

# Upstream divergence patterns - needs Flow 8 Reset
UPSTREAM_DIVERGENCE_PATTERNS = [
    r"Your branch is behind",
    r"diverged.*commits",
    r"cannot be fast-forwarded",
    r"have diverged",
    r"branch.*is behind.*by\s+\d+\s+commit",
]


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class FailureSignature:
    """A recognizable failure pattern.

    Attributes:
        signature_id: Unique identifier for this signature (e.g., "lint-errors").
        name: Human-readable name (e.g., "Lint Errors").
        patterns: List of regex patterns to match against error output.
        detour_target: The DetourTarget to route to when matched.
        max_attempts: Maximum detour attempts before escalating (default: 2).
        description: Human-readable description of the signature.
        priority: Higher priority signatures are checked first (default: 50).
        fixable_check: Optional callable to check if errors are auto-fixable.
    """

    signature_id: str
    name: str
    patterns: List[str]
    detour_target: DetourTarget
    max_attempts: int = 2
    description: str = ""
    priority: int = 50
    fixable_check: Optional[Callable[[Dict[str, Any]], bool]] = None

    def __post_init__(self) -> None:
        """Compile regex patterns for efficient matching."""
        self._compiled_patterns = [
            re.compile(p, re.IGNORECASE | re.MULTILINE) for p in self.patterns
        ]

    def matches(self, text: str) -> bool:
        """Check if any pattern matches the given text.

        Args:
            text: The text to search for pattern matches.

        Returns:
            True if any pattern matches, False otherwise.
        """
        for pattern in self._compiled_patterns:
            if pattern.search(text):
                return True
        return False


@dataclass
class SignatureMatch:
    """Result of signature matching.

    Attributes:
        matched: Whether a signature was matched.
        signature_id: The matched signature ID (if matched).
        detour_target: The target to route to (if matched).
        confidence: Confidence level (HIGH, MEDIUM, LOW).
        evidence: Description of what triggered the match.
        attempt_number: Current attempt number for this signature/step.
        fixable: Whether the issue appears auto-fixable.
        max_attempts: Maximum attempts allowed for this signature.
    """

    matched: bool
    signature_id: Optional[str] = None
    detour_target: Optional[DetourTarget] = None
    confidence: str = "LOW"
    evidence: Optional[str] = None
    attempt_number: int = 1
    fixable: bool = True
    max_attempts: int = 2

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "matched": self.matched,
            "signature_id": self.signature_id,
            "detour_target": self.detour_target.value if self.detour_target else None,
            "confidence": self.confidence,
            "evidence": self.evidence,
            "attempt_number": self.attempt_number,
            "fixable": self.fixable,
            "max_attempts": self.max_attempts,
        }


@dataclass
class DetourAttempt:
    """Tracks detour attempts per signature per step.

    Attributes:
        signature_id: The signature being tracked.
        step_id: The step where this signature was encountered.
        attempts: Number of detour attempts made.
        last_attempt: ISO timestamp of last attempt.
        resolved: Whether the issue was resolved by detour.
        first_seen: ISO timestamp when first encountered.
    """

    signature_id: str
    step_id: str
    attempts: int = 0
    last_attempt: Optional[str] = None
    resolved: bool = False
    first_seen: Optional[str] = None

    def record_attempt(self) -> None:
        """Record a new attempt."""
        now = datetime.now(timezone.utc).isoformat()
        if self.first_seen is None:
            self.first_seen = now
        self.attempts += 1
        self.last_attempt = now

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "signature_id": self.signature_id,
            "step_id": self.step_id,
            "attempts": self.attempts,
            "last_attempt": self.last_attempt,
            "resolved": self.resolved,
            "first_seen": self.first_seen,
        }


# =============================================================================
# Detour Matcher
# =============================================================================


class DetourMatcher:
    """Matches failure signatures to known detours.

    The matcher maintains a registry of known failure signatures and tracks
    detour attempts per signature/step combination to enforce attempt limits.

    Usage:
        matcher = DetourMatcher()
        match = matcher.match(forensics, step_id="build-step-3")
        if match.matched:
            if not matcher.check_attempt_limit(match.signature_id, step_id):
                # Route to detour target
                matcher.record_attempt(match.signature_id, step_id)
    """

    def __init__(self) -> None:
        """Initialize the detour matcher with default signatures."""
        self._signatures: Dict[str, FailureSignature] = {}
        self._attempt_tracker: Dict[str, DetourAttempt] = {}
        self._register_default_signatures()

    def _register_default_signatures(self) -> None:
        """Register built-in failure signatures."""
        # Lint errors - highest priority, most common
        self.register_signature(
            FailureSignature(
                signature_id="lint-errors",
                name="Lint Errors",
                patterns=LINT_ERROR_PATTERNS,
                detour_target=DetourTarget.AUTO_LINTER,
                max_attempts=2,
                description="Lint/formatting errors detected in code",
                priority=90,
                fixable_check=self._check_lint_fixable,
            )
        )

        # Import errors - often easy to fix
        self.register_signature(
            FailureSignature(
                signature_id="import-errors",
                name="Import Errors",
                patterns=IMPORT_ERROR_PATTERNS,
                detour_target=DetourTarget.IMPORT_FIXER,
                max_attempts=2,
                description="Missing or incorrect import statements",
                priority=85,
            )
        )

        # Type errors - common in typed Python
        self.register_signature(
            FailureSignature(
                signature_id="type-errors",
                name="Type Errors",
                patterns=TYPE_ERROR_PATTERNS,
                detour_target=DetourTarget.TYPE_ANNOTATOR,
                max_attempts=2,
                description="Type checking errors (mypy, pyright, etc.)",
                priority=80,
            )
        )

        # Test fixture errors
        self.register_signature(
            FailureSignature(
                signature_id="fixture-errors",
                name="Test Fixture Errors",
                patterns=TEST_FIXTURE_PATTERNS,
                detour_target=DetourTarget.TEST_FIXTURE,
                max_attempts=2,
                description="Missing or misconfigured test fixtures",
                priority=75,
            )
        )

        # Dependency errors
        self.register_signature(
            FailureSignature(
                signature_id="dependency-errors",
                name="Dependency Errors",
                patterns=DEPENDENCY_ERROR_PATTERNS,
                detour_target=DetourTarget.DEP_RESOLVER,
                max_attempts=2,
                description="Missing package dependencies",
                priority=70,
            )
        )

        # Git conflict errors
        self.register_signature(
            FailureSignature(
                signature_id="conflict-errors",
                name="Git Conflict Errors",
                patterns=CONFLICT_PATTERNS,
                detour_target=DetourTarget.CONFLICT_RESOLVER,
                max_attempts=2,
                description="Git merge conflicts detected",
                priority=95,  # High priority - blocks progress
            )
        )

        # Upstream divergence - needs Flow 8
        self.register_signature(
            FailureSignature(
                signature_id="upstream-diverged",
                name="Upstream Divergence",
                patterns=UPSTREAM_DIVERGENCE_PATTERNS,
                detour_target=DetourTarget.FLOW_8_RESET,
                max_attempts=1,  # Only try reset once
                description="Branch has diverged from upstream",
                priority=100,  # Highest priority - architectural issue
            )
        )

    def _check_lint_fixable(self, forensics: Dict[str, Any]) -> bool:
        """Check if lint errors appear to be auto-fixable.

        Args:
            forensics: The forensic data from step execution.

        Returns:
            True if errors appear fixable, False otherwise.
        """
        lint_data = forensics.get("lint", {})
        if isinstance(lint_data, dict):
            errors = lint_data.get("errors", 0)
            fixable = lint_data.get("fixable", errors)
            # If fixable count is provided and equals error count, all are fixable
            if errors > 0 and fixable >= errors:
                return True
            # If no fixable count, assume fixable
            if errors > 0 and "fixable" not in lint_data:
                return True
        return True  # Default to fixable

    def register_signature(self, signature: FailureSignature) -> None:
        """Register a custom failure signature.

        Args:
            signature: The FailureSignature to register.
        """
        self._signatures[signature.signature_id] = signature
        logger.debug("Registered signature: %s", signature.signature_id)

    def get_signature(self, signature_id: str) -> Optional[FailureSignature]:
        """Get a registered signature by ID.

        Args:
            signature_id: The signature ID to look up.

        Returns:
            The FailureSignature if found, None otherwise.
        """
        return self._signatures.get(signature_id)

    def list_signatures(self) -> List[FailureSignature]:
        """List all registered signatures sorted by priority.

        Returns:
            List of FailureSignature objects, sorted by priority descending.
        """
        return sorted(self._signatures.values(), key=lambda s: -s.priority)

    def match(self, forensics: Dict[str, Any], step_id: str) -> SignatureMatch:
        """Match forensic data against known signatures.

        Checks forensic data from step execution against all registered
        signatures. Returns the highest-priority match found.

        Args:
            forensics: Dict with keys like 'lint', 'tests', 'git_status', 'error_output'.
            step_id: Current step for attempt tracking.

        Returns:
            SignatureMatch with detour recommendation if matched.
        """
        # Build searchable text from forensics
        search_text = self._build_search_text(forensics)

        # Check signatures in priority order
        for signature in self.list_signatures():
            match = self._match_signature(signature, forensics, search_text, step_id)
            if match.matched:
                logger.info(
                    "Matched signature %s for step %s: %s",
                    signature.signature_id,
                    step_id,
                    match.evidence,
                )
                return match

        # No match found
        return SignatureMatch(matched=False)

    def _build_search_text(self, forensics: Dict[str, Any]) -> str:
        """Build searchable text from forensic data.

        Extracts all text content from forensics for pattern matching.

        Args:
            forensics: The forensic data dictionary.

        Returns:
            Combined text for pattern searching.
        """
        parts: List[str] = []

        # Error output is primary source
        if "error_output" in forensics:
            parts.append(str(forensics["error_output"]))

        # Test failures
        test_failures = forensics.get("test_failures", [])
        if isinstance(test_failures, list):
            for failure in test_failures:
                if isinstance(failure, dict):
                    parts.append(failure.get("type", ""))
                    parts.append(failure.get("message", ""))
                else:
                    parts.append(str(failure))

        # Lint output
        lint_data = forensics.get("lint", {})
        if isinstance(lint_data, dict):
            parts.append(lint_data.get("output", ""))
            errors = lint_data.get("errors", [])
            if isinstance(errors, list):
                for err in errors:
                    if isinstance(err, dict):
                        parts.append(err.get("message", ""))
                        parts.append(err.get("rule", ""))
                    else:
                        parts.append(str(err))

        # Git status
        git_status = forensics.get("git_status", {})
        if isinstance(git_status, dict):
            parts.append(git_status.get("output", ""))
            conflicts = git_status.get("conflicts", [])
            if isinstance(conflicts, list):
                parts.extend([str(c) for c in conflicts])

        # Generic output fields
        for key in ("stdout", "stderr", "output", "message"):
            if key in forensics:
                parts.append(str(forensics[key]))

        return "\n".join(parts)

    def _match_signature(
        self,
        signature: FailureSignature,
        forensics: Dict[str, Any],
        search_text: str,
        step_id: str,
    ) -> SignatureMatch:
        """Match a single signature against forensics.

        Args:
            signature: The signature to match.
            forensics: Original forensic data.
            search_text: Pre-built search text.
            step_id: Current step ID.

        Returns:
            SignatureMatch result.
        """
        # Try pattern matching on search text
        if signature.matches(search_text):
            # Check if fixable
            fixable = True
            if signature.fixable_check:
                fixable = signature.fixable_check(forensics)

            # Get attempt info
            attempt_key = f"{step_id}:{signature.signature_id}"
            attempt = self._attempt_tracker.get(attempt_key)
            attempt_num = (attempt.attempts if attempt else 0) + 1

            # Determine confidence based on pattern match strength
            confidence = self._determine_confidence(signature, forensics, search_text)

            return SignatureMatch(
                matched=True,
                signature_id=signature.signature_id,
                detour_target=signature.detour_target,
                confidence=confidence,
                evidence=f"Pattern matched: {signature.name} ({signature.description})",
                attempt_number=attempt_num,
                fixable=fixable,
                max_attempts=signature.max_attempts,
            )

        # Also check structured forensics for specific signatures
        match = self._match_structured_forensics(signature, forensics, step_id)
        if match:
            return match

        return SignatureMatch(matched=False)

    def _match_structured_forensics(
        self,
        signature: FailureSignature,
        forensics: Dict[str, Any],
        step_id: str,
    ) -> Optional[SignatureMatch]:
        """Match signature against structured forensic data.

        Some signatures can be detected from structured data directly,
        not just text patterns.

        Args:
            signature: The signature to match.
            forensics: The forensic data.
            step_id: Current step ID.

        Returns:
            SignatureMatch if matched, None otherwise.
        """
        attempt_key = f"{step_id}:{signature.signature_id}"
        attempt = self._attempt_tracker.get(attempt_key)
        attempt_num = (attempt.attempts if attempt else 0) + 1

        # Lint errors from structured data
        if signature.signature_id == "lint-errors":
            lint_data = forensics.get("lint", {})
            if isinstance(lint_data, dict):
                errors = lint_data.get("errors", 0)
                if isinstance(errors, int) and errors > 0:
                    fixable = lint_data.get("fixable", errors)
                    return SignatureMatch(
                        matched=True,
                        signature_id=signature.signature_id,
                        detour_target=signature.detour_target,
                        confidence="HIGH",
                        evidence=f"Lint errors: {errors} ({fixable} fixable)",
                        attempt_number=attempt_num,
                        fixable=fixable >= errors if isinstance(fixable, int) else True,
                        max_attempts=signature.max_attempts,
                    )

        # Upstream divergence from git status
        if signature.signature_id == "upstream-diverged":
            git_status = forensics.get("git_status", {})
            if isinstance(git_status, dict):
                behind = git_status.get("behind_upstream", 0)
                diverged = git_status.get("diverged", False)
                if behind > 0 or diverged:
                    return SignatureMatch(
                        matched=True,
                        signature_id=signature.signature_id,
                        detour_target=signature.detour_target,
                        confidence="HIGH",
                        evidence=f"Upstream divergence: behind by {behind} commits",
                        attempt_number=attempt_num,
                        fixable=True,
                        max_attempts=signature.max_attempts,
                    )

        # Git conflicts from git status
        if signature.signature_id == "conflict-errors":
            git_status = forensics.get("git_status", {})
            if isinstance(git_status, dict):
                conflicts = git_status.get("conflicts", [])
                if isinstance(conflicts, list) and len(conflicts) > 0:
                    return SignatureMatch(
                        matched=True,
                        signature_id=signature.signature_id,
                        detour_target=signature.detour_target,
                        confidence="HIGH",
                        evidence=f"Git conflicts: {len(conflicts)} files",
                        attempt_number=attempt_num,
                        fixable=True,
                        max_attempts=signature.max_attempts,
                    )

        # Test fixture errors from test failures
        if signature.signature_id == "fixture-errors":
            test_failures = forensics.get("test_failures", [])
            if isinstance(test_failures, list):
                for failure in test_failures:
                    if isinstance(failure, dict):
                        ftype = failure.get("type", "")
                        if "fixture" in ftype.lower():
                            fixture_name = failure.get("fixture", "unknown")
                            return SignatureMatch(
                                matched=True,
                                signature_id=signature.signature_id,
                                detour_target=signature.detour_target,
                                confidence="HIGH",
                                evidence=f"Missing fixture: {fixture_name}",
                                attempt_number=attempt_num,
                                fixable=True,
                                max_attempts=signature.max_attempts,
                            )

        return None

    def _determine_confidence(
        self,
        signature: FailureSignature,
        forensics: Dict[str, Any],
        search_text: str,
    ) -> str:
        """Determine confidence level for a match.

        Args:
            signature: The matched signature.
            forensics: The forensic data.
            search_text: The search text used for matching.

        Returns:
            Confidence level: "HIGH", "MEDIUM", or "LOW".
        """
        # Count how many patterns match
        match_count = sum(
            1 for p in signature._compiled_patterns if p.search(search_text)
        )

        # Multiple pattern matches = high confidence
        if match_count >= 2:
            return "HIGH"

        # Structured data confirmation = high confidence
        if signature.signature_id == "lint-errors":
            lint_data = forensics.get("lint", {})
            if isinstance(lint_data, dict) and lint_data.get("errors", 0) > 0:
                return "HIGH"

        if signature.signature_id == "upstream-diverged":
            git_status = forensics.get("git_status", {})
            if isinstance(git_status, dict) and git_status.get("behind_upstream", 0) > 0:
                return "HIGH"

        # Single pattern match = medium confidence
        if match_count == 1:
            return "MEDIUM"

        return "LOW"

    def record_attempt(self, signature_id: str, step_id: str) -> int:
        """Record a detour attempt, return attempt count.

        Args:
            signature_id: The signature being attempted.
            step_id: The step where this is occurring.

        Returns:
            The new attempt count after recording.
        """
        attempt_key = f"{step_id}:{signature_id}"
        if attempt_key not in self._attempt_tracker:
            self._attempt_tracker[attempt_key] = DetourAttempt(
                signature_id=signature_id,
                step_id=step_id,
            )

        self._attempt_tracker[attempt_key].record_attempt()
        count = self._attempt_tracker[attempt_key].attempts
        logger.debug(
            "Recorded detour attempt: %s for step %s (attempt %d)",
            signature_id,
            step_id,
            count,
        )
        return count

    def check_attempt_limit(self, signature_id: str, step_id: str) -> bool:
        """Check if attempt limit reached for this signature/step.

        Args:
            signature_id: The signature to check.
            step_id: The step to check.

        Returns:
            True if limit has been reached (no more attempts allowed).
        """
        signature = self._signatures.get(signature_id)
        if not signature:
            return True  # Unknown signature, don't attempt

        attempt_key = f"{step_id}:{signature_id}"
        attempt = self._attempt_tracker.get(attempt_key)
        if not attempt:
            return False  # No attempts yet

        return attempt.attempts >= signature.max_attempts

    def get_attempt_count(self, signature_id: str, step_id: str) -> int:
        """Get current attempt count for a signature/step.

        Args:
            signature_id: The signature to check.
            step_id: The step to check.

        Returns:
            Current attempt count (0 if none).
        """
        attempt_key = f"{step_id}:{signature_id}"
        attempt = self._attempt_tracker.get(attempt_key)
        return attempt.attempts if attempt else 0

    def mark_resolved(self, signature_id: str, step_id: str) -> None:
        """Mark a signature as resolved (detour worked).

        Args:
            signature_id: The signature that was resolved.
            step_id: The step where it was resolved.
        """
        attempt_key = f"{step_id}:{signature_id}"
        if attempt_key in self._attempt_tracker:
            self._attempt_tracker[attempt_key].resolved = True
            logger.info(
                "Marked signature resolved: %s for step %s",
                signature_id,
                step_id,
            )

    def get_detour_instruction(self, match: SignatureMatch) -> Dict[str, Any]:
        """Get routing instruction for a matched signature.

        Produces a routing decision dict suitable for the routing driver.

        Args:
            match: The SignatureMatch result.

        Returns:
            Dict with routing decision information.
        """
        if not match.matched or not match.signature_id:
            return {
                "decision": "CONTINUE",
                "reason": "No signature matched",
            }

        signature = self._signatures.get(match.signature_id)
        if not signature:
            return {
                "decision": "CONTINUE",
                "reason": f"Unknown signature: {match.signature_id}",
            }

        return {
            "decision": "DETOUR",
            "detour_id": match.signature_id,
            "detour_target": match.detour_target.value if match.detour_target else None,
            "reason": match.evidence or f"Matched signature: {signature.name}",
            "signature": {
                "type": match.signature_id,
                "fixable": match.fixable,
            },
            "attempt_number": match.attempt_number,
            "max_attempts": match.max_attempts,
            "confidence": match.confidence,
        }

    def reset_attempts(self, step_id: Optional[str] = None) -> None:
        """Reset attempt tracking.

        Args:
            step_id: If provided, only reset attempts for this step.
                    Otherwise, reset all attempts.
        """
        if step_id:
            keys_to_remove = [
                k for k in self._attempt_tracker if k.startswith(f"{step_id}:")
            ]
            for key in keys_to_remove:
                del self._attempt_tracker[key]
            logger.debug("Reset attempts for step: %s", step_id)
        else:
            self._attempt_tracker.clear()
            logger.debug("Reset all detour attempts")

    def get_attempt_summary(self) -> Dict[str, Any]:
        """Get summary of all tracked attempts.

        Returns:
            Dict with attempt statistics.
        """
        return {
            "total_tracked": len(self._attempt_tracker),
            "attempts": {
                k: v.to_dict() for k, v in self._attempt_tracker.items()
            },
        }


# =============================================================================
# Factory and Convenience Functions
# =============================================================================


# Module-level singleton instance
_default_matcher: Optional[DetourMatcher] = None


def create_detour_matcher() -> DetourMatcher:
    """Factory function for detour matcher with defaults.

    Returns:
        A new DetourMatcher instance with default signatures registered.
    """
    return DetourMatcher()


def get_default_matcher() -> DetourMatcher:
    """Get the default singleton matcher instance.

    Returns:
        The shared DetourMatcher instance.
    """
    global _default_matcher
    if _default_matcher is None:
        _default_matcher = create_detour_matcher()
    return _default_matcher


def set_default_matcher(matcher: DetourMatcher) -> None:
    """Set a custom matcher as the default.

    Args:
        matcher: The DetourMatcher to use as default.
    """
    global _default_matcher
    _default_matcher = matcher


def should_detour(
    forensics: Dict[str, Any],
    step_id: str,
    matcher: Optional[DetourMatcher] = None,
) -> Optional[SignatureMatch]:
    """Convenience function to check if detour is recommended.

    Args:
        forensics: Forensic data from step execution.
        step_id: Current step identifier.
        matcher: Optional matcher instance (uses default if not provided).

    Returns:
        SignatureMatch if a detour is recommended and attempt limit not reached,
        None otherwise.
    """
    if matcher is None:
        matcher = get_default_matcher()

    match = matcher.match(forensics, step_id)
    if not match.matched:
        return None

    # Check attempt limit
    if match.signature_id and matcher.check_attempt_limit(match.signature_id, step_id):
        logger.warning(
            "Detour limit reached for %s at step %s",
            match.signature_id,
            step_id,
        )
        return None

    return match


def get_detour_routing_decision(match: SignatureMatch) -> Dict[str, Any]:
    """Convert a signature match to a routing decision.

    Produces a routing decision dict compatible with the routing driver.

    Args:
        match: The SignatureMatch to convert.

    Returns:
        Dict with routing decision fields.
    """
    if not match.matched:
        return {
            "decision": "CONTINUE",
            "reason": "No detour match",
        }

    return {
        "decision": "DETOUR",
        "detour_id": match.signature_id,
        "detour_target": match.detour_target.value if match.detour_target else None,
        "reason": match.evidence or f"Matched signature: {match.signature_id}",
        "signature": {
            "id": match.signature_id,
            "fixable": match.fixable,
        },
        "return_to": None,  # Filled in by caller with current step
        "attempt_number": match.attempt_number,
        "max_attempts": match.max_attempts,
        "confidence": match.confidence,
    }


def record_detour_attempt(
    signature_id: str,
    step_id: str,
    matcher: Optional[DetourMatcher] = None,
) -> int:
    """Record a detour attempt using the default matcher.

    Args:
        signature_id: The signature being attempted.
        step_id: The step where this is occurring.
        matcher: Optional matcher instance (uses default if not provided).

    Returns:
        The new attempt count after recording.
    """
    if matcher is None:
        matcher = get_default_matcher()
    return matcher.record_attempt(signature_id, step_id)


def mark_detour_resolved(
    signature_id: str,
    step_id: str,
    matcher: Optional[DetourMatcher] = None,
) -> None:
    """Mark a detour as resolved using the default matcher.

    Args:
        signature_id: The signature that was resolved.
        step_id: The step where it was resolved.
        matcher: Optional matcher instance (uses default if not provided).
    """
    if matcher is None:
        matcher = get_default_matcher()
    matcher.mark_resolved(signature_id, step_id)


# =============================================================================
# Integration with Routing Driver
# =============================================================================


def check_for_detour(
    forensics: Dict[str, Any],
    step_id: str,
    return_step: str,
    matcher: Optional[DetourMatcher] = None,
) -> Optional[Dict[str, Any]]:
    """Check for detour opportunity and produce routing decision if found.

    This is the main integration point with the routing driver. Call this
    after step failure to check if a known fix pattern applies.

    Args:
        forensics: Forensic data from step execution.
        step_id: Current step identifier.
        return_step: Step to return to after detour completes.
        matcher: Optional matcher instance (uses default if not provided).

    Returns:
        Routing decision dict if detour recommended, None otherwise.
    """
    match = should_detour(forensics, step_id, matcher)
    if match is None:
        return None

    # Record the attempt
    if match.signature_id:
        record_detour_attempt(match.signature_id, step_id, matcher)

    # Build routing decision
    decision = get_detour_routing_decision(match)
    decision["return_to"] = return_step

    logger.info(
        "Detour recommended: %s -> %s (return to %s)",
        match.signature_id,
        decision.get("detour_target"),
        return_step,
    )

    return decision
