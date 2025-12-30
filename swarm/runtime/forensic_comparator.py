"""
forensic_comparator.py - Semantic Handoff Injection for Navigator claim verification.

This module implements "Forensics Over Narrative" for the Navigator routing decision:
it compares worker's handoff claims against actual evidence (DiffScanner, TestSummary)
to catch "reward hacking" (e.g., deleted tests, fake progress).

Design Philosophy:
    - Worker claims in HandoffEnvelope are hypotheses, not facts
    - DiffScanner results are authoritative (what actually changed)
    - TestParseResult shows actual test outcomes (not claimed outcomes)
    - ForensicVerdict gives Navigator confidence signal for routing decisions

Usage:
    from swarm.runtime.forensic_comparator import (
        ForensicVerdict,
        compare_claim_vs_evidence,
        build_forensic_verdict,
        forensic_verdict_to_dict,
        forensic_verdict_from_dict,
    )

    # Compare handoff claims against forensic evidence
    verdict = compare_claim_vs_evidence(
        handoff=envelope,
        diff_result=diff_scan_result,
        test_summary=test_parse_result,
    )

    if verdict.recommendation == "REJECT":
        # Navigator should flag this for review
        ...

Integration:
    The Navigator receives ForensicVerdict in its context and uses it to inform
    routing decisions. This is NOT blocking validation - the flow continues,
    but the Navigator has signal about claim reliability.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

# Import forensic types for evidence comparison
from swarm.runtime.forensic_types import (
    DiffScanResult,
    TestParseResult,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Verdict types
# =============================================================================


class VerdictRecommendation(str, Enum):
    """Recommendation based on claim-vs-evidence comparison."""

    TRUST = "TRUST"  # Claims align with evidence; proceed normally
    VERIFY = "VERIFY"  # Minor discrepancies; Navigator should double-check
    REJECT = "REJECT"  # Major discrepancies; likely reward hacking


class RewardHackingFlag(str, Enum):
    """Specific reward hacking patterns detected."""

    TEST_COUNT_DECREASED = "test_count_decreased"
    COVERAGE_DROPPED = "coverage_dropped"
    TESTS_DELETED = "tests_deleted"
    CLAIMED_PASS_BUT_FAILED = "claimed_pass_but_failed"
    CLAIMED_PROGRESS_NO_DIFF = "claimed_progress_no_diff"
    CLAIMED_VERIFIED_WITH_FAILURES = "claimed_verified_with_failures"
    FILE_CHANGES_MISMATCH = "file_changes_mismatch"
    UNVERIFIED_CLAIMS_HIGH_CONFIDENCE = "unverified_claims_high_confidence"


class DiscrepancySeverity(str, Enum):
    """Severity of a discrepancy between claim and evidence."""

    INFO = "info"  # Minor, expected variance
    WARNING = "warning"  # Notable mismatch, should review
    CRITICAL = "critical"  # Major mismatch, likely intentional


# =============================================================================
# Discrepancy and Verdict dataclasses
# =============================================================================


@dataclass
class Discrepancy:
    """A single discrepancy between claim and evidence.

    Attributes:
        category: What type of discrepancy this is.
        claim: What the worker claimed.
        evidence: What forensics actually found.
        severity: How serious this discrepancy is.
        details: Additional context about the mismatch.
    """

    category: str
    claim: str
    evidence: str
    severity: DiscrepancySeverity = DiscrepancySeverity.INFO
    details: Optional[str] = None


def discrepancy_to_dict(d: Discrepancy) -> Dict[str, Any]:
    """Convert Discrepancy to dictionary."""
    result: Dict[str, Any] = {
        "category": d.category,
        "claim": d.claim,
        "evidence": d.evidence,
        "severity": d.severity.value,
    }
    if d.details:
        result["details"] = d.details
    return result


def discrepancy_from_dict(data: Dict[str, Any]) -> Discrepancy:
    """Parse Discrepancy from dictionary."""
    severity = DiscrepancySeverity.INFO
    if "severity" in data:
        try:
            severity = DiscrepancySeverity(data["severity"])
        except ValueError:
            pass
    return Discrepancy(
        category=data.get("category", ""),
        claim=data.get("claim", ""),
        evidence=data.get("evidence", ""),
        severity=severity,
        details=data.get("details"),
    )


@dataclass
class ForensicVerdict:
    """Result of comparing handoff claims against forensic evidence.

    This is the key output for Navigator routing decisions. It provides:
    - claim_verified: Quick boolean for "are claims trustworthy?"
    - confidence: How confident are we in this verdict (0.0-1.0)
    - discrepancies: List of specific mismatches found
    - reward_hacking_flags: Specific patterns suggesting gaming
    - recommendation: TRUST, VERIFY, or REJECT

    The Navigator uses this to:
    1. Decide whether to trust routing suggestions in the handoff
    2. Flag suspicious patterns for wisdom/audit
    3. Adjust confidence in continuation decisions

    Attributes:
        claim_verified: True if claims substantially match evidence.
        confidence: Confidence score for this verdict (0.0-1.0).
        discrepancies: List of discrepancies found between claim and evidence.
        reward_hacking_flags: List of specific reward hacking patterns detected.
        recommendation: Overall recommendation (TRUST, VERIFY, REJECT).
        summary: Human-readable summary of the verdict.
        timestamp: When this verdict was produced.
        evidence_hashes: Hashes of the evidence used for verification.
    """

    claim_verified: bool
    confidence: float
    discrepancies: List[Discrepancy] = field(default_factory=list)
    reward_hacking_flags: List[RewardHackingFlag] = field(default_factory=list)
    recommendation: VerdictRecommendation = VerdictRecommendation.TRUST
    summary: str = ""
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat() + "Z"
    )
    evidence_hashes: Dict[str, str] = field(default_factory=dict)


def forensic_verdict_to_dict(verdict: ForensicVerdict) -> Dict[str, Any]:
    """Convert ForensicVerdict to dictionary for serialization."""
    return {
        "claim_verified": verdict.claim_verified,
        "confidence": verdict.confidence,
        "discrepancies": [discrepancy_to_dict(d) for d in verdict.discrepancies],
        "reward_hacking_flags": [f.value for f in verdict.reward_hacking_flags],
        "recommendation": verdict.recommendation.value,
        "summary": verdict.summary,
        "timestamp": verdict.timestamp,
        "evidence_hashes": verdict.evidence_hashes,
    }


def forensic_verdict_from_dict(data: Dict[str, Any]) -> ForensicVerdict:
    """Parse ForensicVerdict from dictionary."""
    discrepancies = [discrepancy_from_dict(d) for d in data.get("discrepancies", [])]

    reward_hacking_flags = []
    for flag_str in data.get("reward_hacking_flags", []):
        try:
            reward_hacking_flags.append(RewardHackingFlag(flag_str))
        except ValueError:
            pass

    recommendation = VerdictRecommendation.TRUST
    if "recommendation" in data:
        try:
            recommendation = VerdictRecommendation(data["recommendation"])
        except ValueError:
            pass

    return ForensicVerdict(
        claim_verified=data.get("claim_verified", True),
        confidence=data.get("confidence", 1.0),
        discrepancies=discrepancies,
        reward_hacking_flags=reward_hacking_flags,
        recommendation=recommendation,
        summary=data.get("summary", ""),
        timestamp=data.get("timestamp", ""),
        evidence_hashes=data.get("evidence_hashes", {}),
    )


# =============================================================================
# Comparison logic
# =============================================================================


def _extract_handoff_claims(handoff: Dict[str, Any]) -> Dict[str, Any]:
    """Extract verifiable claims from a handoff envelope.

    Returns structured claims that can be compared against evidence.
    """
    claims: Dict[str, Any] = {}

    # Status claim
    claims["status"] = handoff.get("status", "unknown")

    # Test-related claims from summary
    summary = handoff.get("summary", "")
    claims["summary"] = summary
    claims["claimed_tests_pass"] = any(
        phrase in summary.lower()
        for phrase in ["tests pass", "all tests pass", "tests passing", "tests green"]
    )
    claims["claimed_verified"] = handoff.get("status") == "VERIFIED"

    # File changes claim
    file_changes = handoff.get("file_changes", {})
    if file_changes:
        claims["claimed_files_modified"] = file_changes.get("files_modified", 0)
        claims["claimed_lines_added"] = file_changes.get("lines_added", 0)
        claims["claimed_lines_removed"] = file_changes.get("lines_removed", 0)
    else:
        # Check for summary mentions of file changes
        claims["claimed_has_changes"] = any(
            phrase in summary.lower()
            for phrase in ["modified", "created", "updated", "added", "changed"]
        )

    # Confidence claim
    confidence = handoff.get("confidence")
    if isinstance(confidence, str):
        claims["claimed_confidence"] = confidence
    elif isinstance(confidence, float):
        claims["claimed_confidence"] = (
            "high" if confidence > 0.8 else "medium" if confidence > 0.5 else "low"
        )

    # Progress claim
    claims["claimed_progress"] = handoff.get("can_further_iteration_help") is False

    return claims


def _compute_evidence_hash(
    diff_result: Optional[DiffScanResult],
    test_summary: Optional[TestParseResult],
) -> Dict[str, str]:
    """Compute hashes of evidence for integrity verification."""
    hashes: Dict[str, str] = {}

    if diff_result:
        hashes["diff_scan"] = diff_result.scan_hash

    if test_summary:
        # Create a hash of the test summary
        test_data = {
            "total": test_summary.total_tests,
            "passed": test_summary.passed,
            "failed": test_summary.failed,
            "skipped": test_summary.skipped,
        }
        test_json = json.dumps(test_data, sort_keys=True)
        hashes["test_summary"] = hashlib.sha256(test_json.encode()).hexdigest()[:16]

    return hashes


def compare_claim_vs_evidence(
    handoff: Dict[str, Any],
    diff_result: Optional[DiffScanResult] = None,
    test_summary: Optional[TestParseResult] = None,
) -> ForensicVerdict:
    """Compare handoff claims against forensic evidence.

    This is the core function for Semantic Handoff Injection. It:
    1. Extracts claims from the handoff envelope
    2. Compares against DiffScanner and TestSummary evidence
    3. Detects discrepancies and reward hacking patterns
    4. Produces a ForensicVerdict for Navigator routing decisions

    Args:
        handoff: HandoffEnvelope as a dictionary.
        diff_result: DiffScanResult from scanning actual file changes.
        test_summary: TestParseResult from parsing actual test output.

    Returns:
        ForensicVerdict with comparison results and recommendation.

    Note:
        This function is non-blocking. It produces signal for the Navigator
        but does not stop flow execution.
    """
    claims = _extract_handoff_claims(handoff)
    discrepancies: List[Discrepancy] = []
    reward_flags: List[RewardHackingFlag] = []

    # ==========================================================================
    # Test-related verification
    # ==========================================================================

    if test_summary is not None:
        # Check: claimed tests pass but evidence shows failures
        if claims.get("claimed_tests_pass") and test_summary.failed > 0:
            discrepancies.append(
                Discrepancy(
                    category="test_outcome",
                    claim="tests pass",
                    evidence=f"{test_summary.failed} tests failed",
                    severity=DiscrepancySeverity.CRITICAL,
                    details=f"Claimed tests pass but {test_summary.failed} failures found",
                )
            )
            reward_flags.append(RewardHackingFlag.CLAIMED_PASS_BUT_FAILED)

        # Check: claimed VERIFIED status but tests are failing
        if claims.get("claimed_verified") and test_summary.failed > 0:
            discrepancies.append(
                Discrepancy(
                    category="status_mismatch",
                    claim="status=VERIFIED",
                    evidence=f"{test_summary.failed} tests still failing",
                    severity=DiscrepancySeverity.CRITICAL,
                    details="VERIFIED status claimed but test failures present",
                )
            )
            reward_flags.append(RewardHackingFlag.CLAIMED_VERIFIED_WITH_FAILURES)

        # Check: test count decreased (possible test deletion)
        # This requires comparing against previous test count if available
        # For now, flag if we have very few tests and the envelope claims progress
        if test_summary.total_tests == 0 and claims.get("claimed_progress"):
            discrepancies.append(
                Discrepancy(
                    category="test_count",
                    claim="made progress",
                    evidence="0 tests found",
                    severity=DiscrepancySeverity.WARNING,
                    details="Progress claimed but no tests in suite",
                )
            )

        # Check: test count in handoff doesn't match actual
        handoff_test_count = handoff.get("test_count")
        if handoff_test_count is not None:
            if handoff_test_count > test_summary.total_tests:
                discrepancies.append(
                    Discrepancy(
                        category="test_count",
                        claim=f"{handoff_test_count} tests",
                        evidence=f"{test_summary.total_tests} tests found",
                        severity=DiscrepancySeverity.WARNING,
                        details="Test count in handoff exceeds actual",
                    )
                )
                reward_flags.append(RewardHackingFlag.TEST_COUNT_DECREASED)

        # Check: coverage dropped (if coverage is available)
        handoff_coverage = handoff.get("coverage_percent")
        if handoff_coverage is not None and test_summary.coverage_percent is not None:
            if handoff_coverage > test_summary.coverage_percent + 5:  # 5% tolerance
                discrepancies.append(
                    Discrepancy(
                        category="coverage",
                        claim=f"{handoff_coverage}% coverage",
                        evidence=f"{test_summary.coverage_percent}% actual",
                        severity=DiscrepancySeverity.WARNING,
                        details="Claimed coverage exceeds actual",
                    )
                )
                reward_flags.append(RewardHackingFlag.COVERAGE_DROPPED)

    # ==========================================================================
    # Diff-related verification
    # ==========================================================================

    if diff_result is not None:
        actual_files_changed = len(diff_result.files) + len(diff_result.untracked)
        actual_has_changes = diff_result.total_insertions > 0 or diff_result.total_deletions > 0

        # Check: claimed progress but no actual file changes
        if claims.get("claimed_progress") and not actual_has_changes and actual_files_changed == 0:
            discrepancies.append(
                Discrepancy(
                    category="file_changes",
                    claim="made progress",
                    evidence="no file changes detected",
                    severity=DiscrepancySeverity.CRITICAL,
                    details="Progress claimed but git diff shows no changes",
                )
            )
            reward_flags.append(RewardHackingFlag.CLAIMED_PROGRESS_NO_DIFF)

        # Check: claimed file changes don't match actual
        claimed_files = claims.get("claimed_files_modified", 0)
        if claimed_files > 0 and actual_files_changed == 0:
            discrepancies.append(
                Discrepancy(
                    category="file_changes",
                    claim=f"{claimed_files} files modified",
                    evidence="0 files changed in diff",
                    severity=DiscrepancySeverity.CRITICAL,
                    details="File change count mismatch",
                )
            )
            reward_flags.append(RewardHackingFlag.FILE_CHANGES_MISMATCH)

        # Check: summary mentions changes but no actual changes
        if claims.get("claimed_has_changes") and not actual_has_changes:
            discrepancies.append(
                Discrepancy(
                    category="file_changes",
                    claim="mentions file modifications",
                    evidence="no insertions or deletions",
                    severity=DiscrepancySeverity.WARNING,
                    details="Summary implies changes but diff is empty",
                )
            )

    # ==========================================================================
    # Confidence/status verification
    # ==========================================================================

    # Check: high confidence claim with unverified critical data
    if claims.get("claimed_confidence") == "high":
        if discrepancies and any(d.severity == DiscrepancySeverity.CRITICAL for d in discrepancies):
            discrepancies.append(
                Discrepancy(
                    category="confidence",
                    claim="high confidence",
                    evidence="critical discrepancies found",
                    severity=DiscrepancySeverity.WARNING,
                    details="High confidence claimed despite evidence issues",
                )
            )
            reward_flags.append(RewardHackingFlag.UNVERIFIED_CLAIMS_HIGH_CONFIDENCE)

    # ==========================================================================
    # Compute verdict
    # ==========================================================================

    # Count severity levels
    critical_count = sum(1 for d in discrepancies if d.severity == DiscrepancySeverity.CRITICAL)
    warning_count = sum(1 for d in discrepancies if d.severity == DiscrepancySeverity.WARNING)

    # Determine recommendation
    if critical_count > 0 or len(reward_flags) >= 2:
        recommendation = VerdictRecommendation.REJECT
        claim_verified = False
        confidence = max(0.3, 1.0 - (critical_count * 0.25) - (warning_count * 0.1))
    elif warning_count > 1 or len(reward_flags) == 1:
        recommendation = VerdictRecommendation.VERIFY
        claim_verified = False
        confidence = max(0.5, 1.0 - (warning_count * 0.15))
    else:
        recommendation = VerdictRecommendation.TRUST
        claim_verified = len(discrepancies) == 0
        confidence = 1.0 - (len(discrepancies) * 0.05)

    # Build summary
    if discrepancies:
        summary_parts = [f"{len(discrepancies)} discrepancies found"]
        if reward_flags:
            summary_parts.append(f"{len(reward_flags)} reward hacking patterns")
        summary = "; ".join(summary_parts)
    else:
        summary = "Claims align with forensic evidence"

    # Compute evidence hashes
    evidence_hashes = _compute_evidence_hash(diff_result, test_summary)

    verdict = ForensicVerdict(
        claim_verified=claim_verified,
        confidence=confidence,
        discrepancies=discrepancies,
        reward_hacking_flags=reward_flags,
        recommendation=recommendation,
        summary=summary,
        evidence_hashes=evidence_hashes,
    )

    logger.debug(
        "ForensicVerdict: recommendation=%s, confidence=%.2f, discrepancies=%d, flags=%s",
        recommendation.value,
        confidence,
        len(discrepancies),
        [f.value for f in reward_flags],
    )

    return verdict


def build_forensic_verdict(
    handoff: Dict[str, Any],
    diff_result: Optional[DiffScanResult] = None,
    test_summary: Optional[TestParseResult] = None,
    previous_test_summary: Optional[TestParseResult] = None,
) -> ForensicVerdict:
    """Build a ForensicVerdict with optional historical comparison.

    This is an extended version of compare_claim_vs_evidence that can also
    detect regression patterns by comparing against previous test state.

    Args:
        handoff: HandoffEnvelope as a dictionary.
        diff_result: DiffScanResult from scanning actual file changes.
        test_summary: TestParseResult from parsing actual test output.
        previous_test_summary: TestParseResult from the previous iteration
            (for detecting test count/coverage regression).

    Returns:
        ForensicVerdict with comparison results and recommendation.
    """
    # Start with basic comparison
    verdict = compare_claim_vs_evidence(handoff, diff_result, test_summary)

    # Add regression checks if we have previous state
    if previous_test_summary is not None and test_summary is not None:
        # Check: test count decreased
        if test_summary.total_tests < previous_test_summary.total_tests:
            tests_removed = previous_test_summary.total_tests - test_summary.total_tests
            verdict.discrepancies.append(
                Discrepancy(
                    category="test_regression",
                    claim="iteration made progress",
                    evidence=f"{tests_removed} tests removed since last iteration",
                    severity=DiscrepancySeverity.CRITICAL,
                    details="Test count decreased - possible test deletion",
                )
            )
            if RewardHackingFlag.TEST_COUNT_DECREASED not in verdict.reward_hacking_flags:
                verdict.reward_hacking_flags.append(RewardHackingFlag.TEST_COUNT_DECREASED)
            if RewardHackingFlag.TESTS_DELETED not in verdict.reward_hacking_flags:
                verdict.reward_hacking_flags.append(RewardHackingFlag.TESTS_DELETED)

        # Check: coverage dropped
        if (
            previous_test_summary.coverage_percent is not None
            and test_summary.coverage_percent is not None
            and test_summary.coverage_percent < previous_test_summary.coverage_percent - 2
        ):
            drop = previous_test_summary.coverage_percent - test_summary.coverage_percent
            verdict.discrepancies.append(
                Discrepancy(
                    category="coverage_regression",
                    claim="iteration made progress",
                    evidence=f"coverage dropped {drop:.1f}%",
                    severity=DiscrepancySeverity.WARNING,
                    details="Coverage decreased - may indicate deleted tests or code",
                )
            )
            if RewardHackingFlag.COVERAGE_DROPPED not in verdict.reward_hacking_flags:
                verdict.reward_hacking_flags.append(RewardHackingFlag.COVERAGE_DROPPED)

        # Recompute recommendation after regression checks
        critical_count = sum(
            1 for d in verdict.discrepancies if d.severity == DiscrepancySeverity.CRITICAL
        )
        if critical_count > 0 or len(verdict.reward_hacking_flags) >= 2:
            verdict.recommendation = VerdictRecommendation.REJECT
            verdict.claim_verified = False
            verdict.confidence = min(verdict.confidence, 0.4)
        elif len(verdict.reward_hacking_flags) == 1:
            verdict.recommendation = VerdictRecommendation.VERIFY
            verdict.claim_verified = False
            verdict.confidence = min(verdict.confidence, 0.6)

    return verdict


# =============================================================================
# Exports
# =============================================================================


__all__ = [
    # Enums
    "VerdictRecommendation",
    "RewardHackingFlag",
    "DiscrepancySeverity",
    # Dataclasses
    "Discrepancy",
    "ForensicVerdict",
    # Serialization
    "discrepancy_to_dict",
    "discrepancy_from_dict",
    "forensic_verdict_to_dict",
    "forensic_verdict_from_dict",
    # Core functions
    "compare_claim_vs_evidence",
    "build_forensic_verdict",
]
