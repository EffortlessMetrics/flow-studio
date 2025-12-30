"""
forensic_types.py - Python dataclasses for forensic verification and progress evidence.

This module implements the "Forensics Over Narrative" philosophy: disk state is truth,
agent claims are hypotheses to verify. The types here formalize what DiffScanner captures
and how the Elephant Protocol detects stalls.

Design Philosophy:
    - Agent claims are narrative; forensic scans are reality
    - Markers bind evidence to claims, enabling verification
    - Progress deltas detect stalls: activity without meaningful change
    - The Elephant Protocol triggers when stall_indicator is true across iterations
    - Every dataclass has to_dict() and from_dict() for serialization

Schemas:
    - forensic_verification.schema.json: ForensicMarker, DiffScanResult, TestParseResult
    - progress_evidence.schema.json: StateSnapshot, ProgressDelta, ProgressEvidence

Usage:
    from swarm.runtime.forensic_types import (
        ForensicMarker, DiffScanResult, TestParseResult, ForensicVerification,
        StateSnapshot, ProgressDelta, ProgressEvidence,
        compute_stall_indicator, compute_evidence_hash,
    )

    # After step execution
    verification = ForensicVerification(
        scan_id="run-123-build-impl-1703847600000",
        timestamp=datetime.now(timezone.utc).isoformat() + "Z",
        scan_type="diff_scan",
        source=ScanSource(step_id="impl", flow_key="build", run_id="run-123"),
        diff_result=diff_result,
        markers=[marker],
    )

    # For stall detection
    is_stalled = compute_stall_indicator(delta)
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Union

# Import FileDiff for compatibility with diff_scanner.py
from swarm.runtime.diff_scanner import FileDiff, file_diff_from_dict, file_diff_to_dict


# =============================================================================
# Enums for type-safe field values
# =============================================================================


class MarkerType(str, Enum):
    """Type of forensic evidence a marker represents."""

    DIFF_SCAN = "diff_scan"
    TEST_RESULT = "test_result"
    ARTIFACT_HASH = "artifact_hash"
    COVERAGE_REPORT = "coverage_report"
    LINT_RESULT = "lint_result"
    SECURITY_SCAN = "security_scan"


class ScanType(str, Enum):
    """Type of forensic scan performed."""

    DIFF_SCAN = "diff_scan"
    TEST_PARSE = "test_parse"
    ARTIFACT_VERIFY = "artifact_verify"


class VerificationStatus(str, Enum):
    """Overall verification status for a forensic scan."""

    VERIFIED = "VERIFIED"
    UNVERIFIED = "UNVERIFIED"
    DISCREPANCY = "DISCREPANCY"
    ERROR = "ERROR"


class FailureType(str, Enum):
    """Category of test failure."""

    ASSERTION = "assertion"
    EXCEPTION = "exception"
    TIMEOUT = "timeout"
    SETUP = "setup"
    TEARDOWN = "teardown"
    UNKNOWN = "unknown"


class TestFramework(str, Enum):
    """Test framework that produced test output."""

    PYTEST = "pytest"
    JEST = "jest"
    MOCHA = "mocha"
    JUNIT = "junit"
    CARGO_TEST = "cargo_test"
    GO_TEST = "go_test"
    RSPEC = "rspec"
    UNKNOWN = "unknown"


class StallType(str, Enum):
    """Category of stall detected by the Elephant Protocol."""

    NO_FILE_CHANGES = "no_file_changes"
    SAME_TEST_FAILURES = "same_test_failures"
    ZERO_PROGRESS_DELTA = "zero_progress_delta"
    HIGH_CHURN_LOW_PROGRESS = "high_churn_low_progress"
    REPEATED_CLAIM_PATTERN = "repeated_claim_pattern"
    COVERAGE_PLATEAU = "coverage_plateau"
    CLAIMS_WITHOUT_EVIDENCE = "claims_without_evidence"


class RecommendedAction(str, Enum):
    """Recommended action based on stall analysis."""

    CONTINUE = "continue"
    BREAK_LOOP = "break_loop"
    ESCALATE_TO_HUMAN = "escalate_to_human"
    INJECT_CLARIFIER = "inject_clarifier"
    BOUNCE_TO_PREVIOUS_FLOW = "bounce_to_previous_flow"
    TERMINATE_WITH_STATUS = "terminate_with_status"


# =============================================================================
# Supporting dataclasses
# =============================================================================


@dataclass
class ScanSource:
    """Context identifying where a forensic scan originated.

    Attributes:
        step_id: Step identifier where the scan was triggered.
        flow_key: Flow key (signal, plan, build, review, gate, deploy, wisdom).
        run_id: Unique run identifier.
        agent_key: Agent that executed the step (optional).
        station_id: Station template ID if applicable.
    """

    step_id: str
    flow_key: str
    run_id: str
    agent_key: Optional[str] = None
    station_id: Optional[str] = None


def scan_source_to_dict(source: ScanSource) -> Dict[str, Any]:
    """Convert ScanSource to dictionary for serialization."""
    result: Dict[str, Any] = {
        "step_id": source.step_id,
        "flow_key": source.flow_key,
        "run_id": source.run_id,
    }
    if source.agent_key:
        result["agent_key"] = source.agent_key
    if source.station_id:
        result["station_id"] = source.station_id
    return result


def scan_source_from_dict(data: Dict[str, Any]) -> ScanSource:
    """Parse ScanSource from dictionary."""
    return ScanSource(
        step_id=data.get("step_id", ""),
        flow_key=data.get("flow_key", ""),
        run_id=data.get("run_id", ""),
        agent_key=data.get("agent_key"),
        station_id=data.get("station_id"),
    )


@dataclass
class TestFailure:
    """Detailed information about a single test failure.

    Attributes:
        test_name: Fully qualified test name.
        error_message: Error message from the test failure.
        test_file: Path to the test file.
        test_line: Line number where the test is defined.
        stack_trace: Full stack trace if available.
        failure_type: Category of failure.
        expected: Expected value in assertion failures.
        actual: Actual value in assertion failures.
        duration_ms: Time spent on this test before failure.
    """

    test_name: str
    error_message: str
    test_file: Optional[str] = None
    test_line: Optional[int] = None
    stack_trace: Optional[str] = None
    failure_type: FailureType = FailureType.UNKNOWN
    expected: Optional[str] = None
    actual: Optional[str] = None
    duration_ms: Optional[int] = None


def test_failure_to_dict(failure: TestFailure) -> Dict[str, Any]:
    """Convert TestFailure to dictionary for serialization."""
    result: Dict[str, Any] = {
        "test_name": failure.test_name,
        "error_message": failure.error_message,
    }
    if failure.test_file:
        result["test_file"] = failure.test_file
    if failure.test_line is not None:
        result["test_line"] = failure.test_line
    if failure.stack_trace:
        result["stack_trace"] = failure.stack_trace
    if failure.failure_type != FailureType.UNKNOWN:
        result["failure_type"] = failure.failure_type.value
    if failure.expected:
        result["expected"] = failure.expected
    if failure.actual:
        result["actual"] = failure.actual
    if failure.duration_ms is not None:
        result["duration_ms"] = failure.duration_ms
    return result


def test_failure_from_dict(data: Dict[str, Any]) -> TestFailure:
    """Parse TestFailure from dictionary."""
    failure_type = FailureType.UNKNOWN
    if "failure_type" in data:
        try:
            failure_type = FailureType(data["failure_type"])
        except ValueError:
            pass
    return TestFailure(
        test_name=data.get("test_name", ""),
        error_message=data.get("error_message", ""),
        test_file=data.get("test_file"),
        test_line=data.get("test_line"),
        stack_trace=data.get("stack_trace"),
        failure_type=failure_type,
        expected=data.get("expected"),
        actual=data.get("actual"),
        duration_ms=data.get("duration_ms"),
    )


@dataclass
class ModeChange:
    """File mode change information."""

    old_mode: str
    new_mode: str


def mode_change_to_dict(mode: ModeChange) -> Dict[str, str]:
    """Convert ModeChange to dictionary."""
    return {"old_mode": mode.old_mode, "new_mode": mode.new_mode}


def mode_change_from_dict(data: Dict[str, Any]) -> ModeChange:
    """Parse ModeChange from dictionary."""
    return ModeChange(
        old_mode=data.get("old_mode", ""),
        new_mode=data.get("new_mode", ""),
    )


# =============================================================================
# Core forensic dataclasses
# =============================================================================


@dataclass
class ForensicMarker:
    """Binds forensic evidence to agent claims.

    This is the core mechanism for "Forensics Over Narrative": each marker
    compares what the agent claimed to do (narrative) versus what forensics
    actually found (reality).

    Attributes:
        marker_id: Unique identifier for this marker.
        marker_type: Type of evidence (diff_scan, test_result, artifact_hash, etc.).
        evidence_hash: SHA256 hash of the evidence payload for integrity.
        claim: What the agent claimed (e.g., "Created file src/auth.py").
        reality: What forensics actually found (e.g., "File src/auth.py exists").
        match: Whether claim matches reality (true = verified).
        discrepancy: Explanation of gap between claim and reality (if match is false).
        confidence: Confidence score (0-1) in the match determination.
        evidence_path: Path to the evidence artifact if stored separately.
        timestamp: When this marker was created.
    """

    marker_id: str
    marker_type: MarkerType
    evidence_hash: str
    claim: str
    reality: str
    match: bool
    discrepancy: Optional[str] = None
    confidence: float = 1.0
    evidence_path: Optional[str] = None
    timestamp: Optional[str] = None


def forensic_marker_to_dict(marker: ForensicMarker) -> Dict[str, Any]:
    """Convert ForensicMarker to dictionary for serialization."""
    result: Dict[str, Any] = {
        "marker_id": marker.marker_id,
        "marker_type": marker.marker_type.value if isinstance(marker.marker_type, MarkerType) else marker.marker_type,
        "evidence_hash": marker.evidence_hash,
        "claim": marker.claim,
        "reality": marker.reality,
        "match": marker.match,
        "confidence": marker.confidence,
    }
    if marker.discrepancy:
        result["discrepancy"] = marker.discrepancy
    if marker.evidence_path:
        result["evidence_path"] = marker.evidence_path
    if marker.timestamp:
        result["timestamp"] = marker.timestamp
    return result


def forensic_marker_from_dict(data: Dict[str, Any]) -> ForensicMarker:
    """Parse ForensicMarker from dictionary."""
    marker_type = MarkerType.DIFF_SCAN
    if "marker_type" in data:
        try:
            marker_type = MarkerType(data["marker_type"])
        except ValueError:
            pass
    return ForensicMarker(
        marker_id=data.get("marker_id", ""),
        marker_type=marker_type,
        evidence_hash=data.get("evidence_hash", ""),
        claim=data.get("claim", ""),
        reality=data.get("reality", ""),
        match=data.get("match", False),
        discrepancy=data.get("discrepancy"),
        confidence=data.get("confidence", 1.0),
        evidence_path=data.get("evidence_path"),
        timestamp=data.get("timestamp"),
    )


@dataclass
class DiffScanResult:
    """Results from scanning git diff for file mutations.

    Matches the FileChanges dataclass from diff_scanner.py but with
    schema-aligned naming and additional fields.

    Attributes:
        files: List of individual file changes detected by git.
        total_insertions: Sum of all line insertions across files.
        total_deletions: Sum of all line deletions across files.
        untracked: List of untracked file paths.
        staged: List of staged file paths.
        scan_error: Error message if scan failed.
        scan_hash: SHA256 hash of the serialized scan result.
        summary: Human-readable summary of changes.
        head_commit: Git HEAD commit SHA at time of scan.
        base_commit: Base commit SHA used for diff comparison.
    """

    files: List[FileDiff] = field(default_factory=list)
    total_insertions: int = 0
    total_deletions: int = 0
    untracked: List[str] = field(default_factory=list)
    staged: List[str] = field(default_factory=list)
    scan_error: Optional[str] = None
    scan_hash: str = ""
    summary: Optional[str] = None
    head_commit: Optional[str] = None
    base_commit: Optional[str] = None

    def __post_init__(self) -> None:
        """Compute scan_hash if not provided."""
        if not self.scan_hash:
            self.scan_hash = self._compute_hash()

    def _compute_hash(self) -> str:
        """Compute SHA256 hash of the scan result for integrity verification."""
        data = {
            "files": [file_diff_to_dict(f) for f in self.files],
            "total_insertions": self.total_insertions,
            "total_deletions": self.total_deletions,
            "untracked": sorted(self.untracked),
            "staged": sorted(self.staged),
        }
        json_str = json.dumps(data, sort_keys=True)
        return hashlib.sha256(json_str.encode()).hexdigest()


def diff_scan_result_to_dict(result: DiffScanResult) -> Dict[str, Any]:
    """Convert DiffScanResult to dictionary for serialization."""
    output: Dict[str, Any] = {
        "files": [file_diff_to_dict(f) for f in result.files],
        "total_insertions": result.total_insertions,
        "total_deletions": result.total_deletions,
        "untracked": result.untracked,
        "staged": result.staged,
        "scan_hash": result.scan_hash,
    }
    if result.scan_error:
        output["scan_error"] = result.scan_error
    if result.summary:
        output["summary"] = result.summary
    if result.head_commit:
        output["head_commit"] = result.head_commit
    if result.base_commit:
        output["base_commit"] = result.base_commit
    return output


def diff_scan_result_from_dict(data: Dict[str, Any]) -> DiffScanResult:
    """Parse DiffScanResult from dictionary."""
    files = [file_diff_from_dict(f) for f in data.get("files", [])]
    return DiffScanResult(
        files=files,
        total_insertions=data.get("total_insertions", 0),
        total_deletions=data.get("total_deletions", 0),
        untracked=data.get("untracked", []),
        staged=data.get("staged", []),
        scan_error=data.get("scan_error"),
        scan_hash=data.get("scan_hash", ""),
        summary=data.get("summary"),
        head_commit=data.get("head_commit"),
        base_commit=data.get("base_commit"),
    )


@dataclass
class TestParseResult:
    """Parsed test output for forensic verification.

    Captures the actual test execution results, not agent claims about tests.
    This enables verification that tests actually passed/failed as claimed.

    Attributes:
        total_tests: Total number of tests discovered/executed.
        passed: Number of tests that passed.
        failed: Number of tests that failed.
        skipped: Number of tests that were skipped.
        errors: Number of tests that errored (distinct from failures).
        failures: Detailed information about each test failure.
        duration_ms: Total test execution duration in milliseconds.
        coverage_percent: Code coverage percentage if available.
        test_framework: Framework that produced this output.
        raw_output_hash: SHA256 hash of the raw test output.
        raw_output_path: Path to the raw test output file.
    """

    total_tests: int
    passed: int
    failed: int
    skipped: int
    errors: int = 0
    failures: List[TestFailure] = field(default_factory=list)
    duration_ms: int = 0
    coverage_percent: Optional[float] = None
    test_framework: TestFramework = TestFramework.UNKNOWN
    raw_output_hash: Optional[str] = None
    raw_output_path: Optional[str] = None


def test_parse_result_to_dict(result: TestParseResult) -> Dict[str, Any]:
    """Convert TestParseResult to dictionary for serialization."""
    output: Dict[str, Any] = {
        "total_tests": result.total_tests,
        "passed": result.passed,
        "failed": result.failed,
        "skipped": result.skipped,
        "errors": result.errors,
        "failures": [test_failure_to_dict(f) for f in result.failures],
        "duration_ms": result.duration_ms,
    }
    if result.coverage_percent is not None:
        output["coverage_percent"] = result.coverage_percent
    if result.test_framework != TestFramework.UNKNOWN:
        output["test_framework"] = result.test_framework.value
    if result.raw_output_hash:
        output["raw_output_hash"] = result.raw_output_hash
    if result.raw_output_path:
        output["raw_output_path"] = result.raw_output_path
    return output


def test_parse_result_from_dict(data: Dict[str, Any]) -> TestParseResult:
    """Parse TestParseResult from dictionary."""
    test_framework = TestFramework.UNKNOWN
    if "test_framework" in data:
        try:
            test_framework = TestFramework(data["test_framework"])
        except ValueError:
            pass
    failures = [test_failure_from_dict(f) for f in data.get("failures", [])]
    return TestParseResult(
        total_tests=data.get("total_tests", 0),
        passed=data.get("passed", 0),
        failed=data.get("failed", 0),
        skipped=data.get("skipped", 0),
        errors=data.get("errors", 0),
        failures=failures,
        duration_ms=data.get("duration_ms", 0),
        coverage_percent=data.get("coverage_percent"),
        test_framework=test_framework,
        raw_output_hash=data.get("raw_output_hash"),
        raw_output_path=data.get("raw_output_path"),
    )


@dataclass
class ScanMetadata:
    """Metadata about a forensic scan operation."""

    scanner_version: Optional[str] = None
    scan_duration_ms: Optional[int] = None
    repo_root: Optional[str] = None
    git_version: Optional[str] = None
    triggered_by: Optional[str] = None
    previous_scan_id: Optional[str] = None


def scan_metadata_to_dict(meta: ScanMetadata) -> Dict[str, Any]:
    """Convert ScanMetadata to dictionary."""
    result: Dict[str, Any] = {}
    if meta.scanner_version:
        result["scanner_version"] = meta.scanner_version
    if meta.scan_duration_ms is not None:
        result["scan_duration_ms"] = meta.scan_duration_ms
    if meta.repo_root:
        result["repo_root"] = meta.repo_root
    if meta.git_version:
        result["git_version"] = meta.git_version
    if meta.triggered_by:
        result["triggered_by"] = meta.triggered_by
    if meta.previous_scan_id:
        result["previous_scan_id"] = meta.previous_scan_id
    return result


def scan_metadata_from_dict(data: Dict[str, Any]) -> ScanMetadata:
    """Parse ScanMetadata from dictionary."""
    return ScanMetadata(
        scanner_version=data.get("scanner_version"),
        scan_duration_ms=data.get("scan_duration_ms"),
        repo_root=data.get("repo_root"),
        git_version=data.get("git_version"),
        triggered_by=data.get("triggered_by"),
        previous_scan_id=data.get("previous_scan_id"),
    )


@dataclass
class ForensicVerification:
    """Complete forensic verification record.

    This is the top-level structure for forensic evidence collection.
    It binds scan results to agent claims via markers.

    Attributes:
        scan_id: Unique identifier for this scan.
        timestamp: ISO 8601 timestamp when the scan was performed.
        scan_type: Type of scan (diff_scan, test_parse, artifact_verify).
        source: Context identifying where this scan originated.
        markers: Forensic markers binding evidence to agent claims.
        diff_result: Results from a diff_scan operation.
        test_result: Results from parsing test output.
        verification_status: Overall verification status.
        discrepancy_summary: Summary of any discrepancies found.
        metadata: Additional metadata about the scan.
    """

    scan_id: str
    timestamp: str
    scan_type: ScanType
    source: ScanSource
    markers: List[ForensicMarker] = field(default_factory=list)
    diff_result: Optional[DiffScanResult] = None
    test_result: Optional[TestParseResult] = None
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED
    discrepancy_summary: Optional[str] = None
    metadata: Optional[ScanMetadata] = None


def forensic_verification_to_dict(verification: ForensicVerification) -> Dict[str, Any]:
    """Convert ForensicVerification to dictionary for serialization."""
    result: Dict[str, Any] = {
        "scan_id": verification.scan_id,
        "timestamp": verification.timestamp,
        "scan_type": verification.scan_type.value if isinstance(verification.scan_type, ScanType) else verification.scan_type,
        "source": scan_source_to_dict(verification.source),
        "markers": [forensic_marker_to_dict(m) for m in verification.markers],
    }
    if verification.diff_result:
        result["diff_result"] = diff_scan_result_to_dict(verification.diff_result)
    if verification.test_result:
        result["test_result"] = test_parse_result_to_dict(verification.test_result)
    result["verification_status"] = verification.verification_status.value
    if verification.discrepancy_summary:
        result["discrepancy_summary"] = verification.discrepancy_summary
    if verification.metadata:
        result["metadata"] = scan_metadata_to_dict(verification.metadata)
    return result


def forensic_verification_from_dict(data: Dict[str, Any]) -> ForensicVerification:
    """Parse ForensicVerification from dictionary."""
    scan_type = ScanType.DIFF_SCAN
    if "scan_type" in data:
        try:
            scan_type = ScanType(data["scan_type"])
        except ValueError:
            pass

    verification_status = VerificationStatus.UNVERIFIED
    if "verification_status" in data:
        try:
            verification_status = VerificationStatus(data["verification_status"])
        except ValueError:
            pass

    diff_result = None
    if "diff_result" in data:
        diff_result = diff_scan_result_from_dict(data["diff_result"])

    test_result = None
    if "test_result" in data:
        test_result = test_parse_result_from_dict(data["test_result"])

    metadata = None
    if "metadata" in data:
        metadata = scan_metadata_from_dict(data["metadata"])

    return ForensicVerification(
        scan_id=data.get("scan_id", ""),
        timestamp=data.get("timestamp", ""),
        scan_type=scan_type,
        source=scan_source_from_dict(data.get("source", {})),
        markers=[forensic_marker_from_dict(m) for m in data.get("markers", [])],
        diff_result=diff_result,
        test_result=test_result,
        verification_status=verification_status,
        discrepancy_summary=data.get("discrepancy_summary"),
        metadata=metadata,
    )


# =============================================================================
# Progress Evidence dataclasses (for Elephant Protocol stall detection)
# =============================================================================


@dataclass
class GitState:
    """Git working tree state."""

    head_sha: Optional[str] = None
    branch: Optional[str] = None
    staged_count: int = 0
    unstaged_count: int = 0
    untracked_count: int = 0


def git_state_to_dict(state: GitState) -> Dict[str, Any]:
    """Convert GitState to dictionary."""
    result: Dict[str, Any] = {
        "staged_count": state.staged_count,
        "unstaged_count": state.unstaged_count,
        "untracked_count": state.untracked_count,
    }
    if state.head_sha:
        result["head_sha"] = state.head_sha
    if state.branch:
        result["branch"] = state.branch
    return result


def git_state_from_dict(data: Dict[str, Any]) -> GitState:
    """Parse GitState from dictionary."""
    return GitState(
        head_sha=data.get("head_sha"),
        branch=data.get("branch"),
        staged_count=data.get("staged_count", 0),
        unstaged_count=data.get("unstaged_count", 0),
        untracked_count=data.get("untracked_count", 0),
    )


@dataclass
class StateSnapshot:
    """Point-in-time snapshot of measurable repository/artifact state.

    All counts are objectively measurable from disk, not agent claims.
    This enables the "Forensics Over Narrative" principle: disk state is truth.

    Attributes:
        captured_at: ISO 8601 timestamp when this snapshot was taken.
        file_count: Number of tracked files in scope.
        line_count: Total lines across tracked files.
        test_count: Number of test cases (from test discovery).
        test_pass_count: Number of passing tests.
        test_fail_count: Number of failing tests.
        test_skip_count: Number of skipped tests.
        coverage_percent: Code coverage percentage (from coverage tool).
        lint_error_count: Number of lint errors.
        type_error_count: Number of type errors.
        artifact_hashes: Map of artifact path to SHA-256 hash.
        artifact_sizes: Map of artifact path to size in bytes.
        git_state: Git working tree state.
        custom_metrics: Extensible key-value pairs for flow-specific metrics.
    """

    captured_at: str
    file_count: int = 0
    line_count: int = 0
    test_count: int = 0
    test_pass_count: int = 0
    test_fail_count: int = 0
    test_skip_count: int = 0
    coverage_percent: Optional[float] = None
    lint_error_count: int = 0
    type_error_count: int = 0
    artifact_hashes: Dict[str, str] = field(default_factory=dict)
    artifact_sizes: Dict[str, int] = field(default_factory=dict)
    git_state: Optional[GitState] = None
    custom_metrics: Dict[str, Union[str, int, float, bool]] = field(default_factory=dict)


def state_snapshot_to_dict(snapshot: StateSnapshot) -> Dict[str, Any]:
    """Convert StateSnapshot to dictionary for serialization."""
    result: Dict[str, Any] = {
        "captured_at": snapshot.captured_at,
        "file_count": snapshot.file_count,
        "line_count": snapshot.line_count,
        "test_count": snapshot.test_count,
        "test_pass_count": snapshot.test_pass_count,
        "test_fail_count": snapshot.test_fail_count,
        "test_skip_count": snapshot.test_skip_count,
        "lint_error_count": snapshot.lint_error_count,
        "type_error_count": snapshot.type_error_count,
    }
    if snapshot.coverage_percent is not None:
        result["coverage_percent"] = snapshot.coverage_percent
    if snapshot.artifact_hashes:
        result["artifact_hashes"] = snapshot.artifact_hashes
    if snapshot.artifact_sizes:
        result["artifact_sizes"] = snapshot.artifact_sizes
    if snapshot.git_state:
        result["git_state"] = git_state_to_dict(snapshot.git_state)
    if snapshot.custom_metrics:
        result["custom_metrics"] = snapshot.custom_metrics
    return result


def state_snapshot_from_dict(data: Dict[str, Any]) -> StateSnapshot:
    """Parse StateSnapshot from dictionary."""
    git_state = None
    if "git_state" in data:
        git_state = git_state_from_dict(data["git_state"])

    return StateSnapshot(
        captured_at=data.get("captured_at", ""),
        file_count=data.get("file_count", 0),
        line_count=data.get("line_count", 0),
        test_count=data.get("test_count", 0),
        test_pass_count=data.get("test_pass_count", 0),
        test_fail_count=data.get("test_fail_count", 0),
        test_skip_count=data.get("test_skip_count", 0),
        coverage_percent=data.get("coverage_percent"),
        lint_error_count=data.get("lint_error_count", 0),
        type_error_count=data.get("type_error_count", 0),
        artifact_hashes=data.get("artifact_hashes", {}),
        artifact_sizes=data.get("artifact_sizes", {}),
        git_state=git_state,
        custom_metrics=data.get("custom_metrics", {}),
    )


@dataclass
class ArtifactChange:
    """Record of a single artifact change."""

    path: str
    change_type: str  # "added", "modified", "deleted"
    size_delta: Optional[int] = None
    content_similarity: Optional[float] = None


def artifact_change_to_dict(change: ArtifactChange) -> Dict[str, Any]:
    """Convert ArtifactChange to dictionary."""
    result: Dict[str, Any] = {
        "path": change.path,
        "change_type": change.change_type,
    }
    if change.size_delta is not None:
        result["size_delta"] = change.size_delta
    if change.content_similarity is not None:
        result["content_similarity"] = change.content_similarity
    return result


def artifact_change_from_dict(data: Dict[str, Any]) -> ArtifactChange:
    """Parse ArtifactChange from dictionary."""
    return ArtifactChange(
        path=data.get("path", ""),
        change_type=data.get("change_type", "modified"),
        size_delta=data.get("size_delta"),
        content_similarity=data.get("content_similarity"),
    )


@dataclass
class ProgressDelta:
    """Computed difference between before and after states.

    This is the derivative of progress. Positive values mean forward motion,
    zero means stall. The Elephant Protocol triggers when stall_indicator
    is true across multiple iterations.

    Attributes:
        files_added: Number of new files created.
        files_modified: Number of existing files modified.
        files_deleted: Number of files deleted.
        lines_added: Total lines added across all files.
        lines_removed: Total lines removed across all files.
        net_lines: Net line change (can be negative).
        tests_added: Number of new test cases.
        tests_removed: Number of test cases removed.
        test_pass_delta: Change in number of passing tests.
        test_fail_delta: Change in number of failing tests.
        coverage_delta: Change in coverage percentage.
        lint_error_delta: Change in lint errors.
        type_error_delta: Change in type errors.
        artifacts_changed: List of artifacts that changed.
        custom_deltas: Computed deltas for custom metrics.
        has_meaningful_change: True if step made observable forward progress.
        stall_indicator: True if this delta indicates a stall condition.
        stall_reason: Explanation if stall_indicator is true.
        progress_score: Normalized score from -1 (regression) to 1 (progress).
    """

    has_meaningful_change: bool
    stall_indicator: bool
    files_added: int = 0
    files_modified: int = 0
    files_deleted: int = 0
    lines_added: int = 0
    lines_removed: int = 0
    net_lines: int = 0
    tests_added: int = 0
    tests_removed: int = 0
    test_pass_delta: int = 0
    test_fail_delta: int = 0
    coverage_delta: Optional[float] = None
    lint_error_delta: int = 0
    type_error_delta: int = 0
    artifacts_changed: List[ArtifactChange] = field(default_factory=list)
    custom_deltas: Dict[str, float] = field(default_factory=dict)
    stall_reason: Optional[str] = None
    progress_score: Optional[float] = None


def progress_delta_to_dict(delta: ProgressDelta) -> Dict[str, Any]:
    """Convert ProgressDelta to dictionary for serialization."""
    result: Dict[str, Any] = {
        "has_meaningful_change": delta.has_meaningful_change,
        "stall_indicator": delta.stall_indicator,
        "files_added": delta.files_added,
        "files_modified": delta.files_modified,
        "files_deleted": delta.files_deleted,
        "lines_added": delta.lines_added,
        "lines_removed": delta.lines_removed,
        "net_lines": delta.net_lines,
        "tests_added": delta.tests_added,
        "tests_removed": delta.tests_removed,
        "test_pass_delta": delta.test_pass_delta,
        "test_fail_delta": delta.test_fail_delta,
        "lint_error_delta": delta.lint_error_delta,
        "type_error_delta": delta.type_error_delta,
    }
    if delta.coverage_delta is not None:
        result["coverage_delta"] = delta.coverage_delta
    if delta.artifacts_changed:
        result["artifacts_changed"] = [artifact_change_to_dict(a) for a in delta.artifacts_changed]
    if delta.custom_deltas:
        result["custom_deltas"] = delta.custom_deltas
    if delta.stall_reason:
        result["stall_reason"] = delta.stall_reason
    if delta.progress_score is not None:
        result["progress_score"] = delta.progress_score
    return result


def progress_delta_from_dict(data: Dict[str, Any]) -> ProgressDelta:
    """Parse ProgressDelta from dictionary."""
    artifacts_changed = [
        artifact_change_from_dict(a) for a in data.get("artifacts_changed", [])
    ]
    return ProgressDelta(
        has_meaningful_change=data.get("has_meaningful_change", False),
        stall_indicator=data.get("stall_indicator", False),
        files_added=data.get("files_added", 0),
        files_modified=data.get("files_modified", 0),
        files_deleted=data.get("files_deleted", 0),
        lines_added=data.get("lines_added", 0),
        lines_removed=data.get("lines_removed", 0),
        net_lines=data.get("net_lines", 0),
        tests_added=data.get("tests_added", 0),
        tests_removed=data.get("tests_removed", 0),
        test_pass_delta=data.get("test_pass_delta", 0),
        test_fail_delta=data.get("test_fail_delta", 0),
        coverage_delta=data.get("coverage_delta"),
        lint_error_delta=data.get("lint_error_delta", 0),
        type_error_delta=data.get("type_error_delta", 0),
        artifacts_changed=artifacts_changed,
        custom_deltas=data.get("custom_deltas", {}),
        stall_reason=data.get("stall_reason"),
        progress_score=data.get("progress_score"),
    )


@dataclass
class ForensicBinding:
    """Links evidence to a ForensicMarker for independent verification."""

    marker_id: str
    binding_type: str = "primary"  # primary, secondary, audit_trail
    verification_status: str = "pending"  # pending, verified, failed, skipped
    verification_timestamp: Optional[str] = None
    discrepancies: List[Dict[str, Any]] = field(default_factory=list)


def forensic_binding_to_dict(binding: ForensicBinding) -> Dict[str, Any]:
    """Convert ForensicBinding to dictionary."""
    result: Dict[str, Any] = {
        "marker_id": binding.marker_id,
        "binding_type": binding.binding_type,
        "verification_status": binding.verification_status,
    }
    if binding.verification_timestamp:
        result["verification_timestamp"] = binding.verification_timestamp
    if binding.discrepancies:
        result["discrepancies"] = binding.discrepancies
    return result


def forensic_binding_from_dict(data: Dict[str, Any]) -> ForensicBinding:
    """Parse ForensicBinding from dictionary."""
    return ForensicBinding(
        marker_id=data.get("marker_id", ""),
        binding_type=data.get("binding_type", "primary"),
        verification_status=data.get("verification_status", "pending"),
        verification_timestamp=data.get("verification_timestamp"),
        discrepancies=data.get("discrepancies", []),
    )


@dataclass
class StallAnalysis:
    """Analysis of whether the run is stalled.

    The Elephant Protocol uses this to detect and break loops that generate
    activity without progress.

    Attributes:
        is_stalled: Whether this step indicates a stall condition.
        stall_type: Category of stall detected.
        stall_duration_iterations: How many iterations have shown stall indicators.
        stall_duration_ms: How long (wall clock) the stall has persisted.
        elephant_protocol_trigger: Whether this triggered Elephant Protocol intervention.
        recommended_action: What to do based on stall analysis.
        evidence_chain: Evidence IDs showing the stall pattern.
        break_attempt_count: How many times we've tried to break this stall.
        last_meaningful_progress_at: When last meaningful progress was detected.
    """

    is_stalled: bool
    stall_type: Optional[StallType] = None
    stall_duration_iterations: int = 0
    stall_duration_ms: int = 0
    elephant_protocol_trigger: bool = False
    recommended_action: RecommendedAction = RecommendedAction.CONTINUE
    evidence_chain: List[str] = field(default_factory=list)
    break_attempt_count: int = 0
    last_meaningful_progress_at: Optional[str] = None


def stall_analysis_to_dict(analysis: StallAnalysis) -> Dict[str, Any]:
    """Convert StallAnalysis to dictionary."""
    result: Dict[str, Any] = {
        "is_stalled": analysis.is_stalled,
        "stall_duration_iterations": analysis.stall_duration_iterations,
        "stall_duration_ms": analysis.stall_duration_ms,
        "elephant_protocol_trigger": analysis.elephant_protocol_trigger,
        "recommended_action": analysis.recommended_action.value,
        "break_attempt_count": analysis.break_attempt_count,
    }
    if analysis.stall_type:
        result["stall_type"] = analysis.stall_type.value
    if analysis.evidence_chain:
        result["evidence_chain"] = analysis.evidence_chain
    if analysis.last_meaningful_progress_at:
        result["last_meaningful_progress_at"] = analysis.last_meaningful_progress_at
    return result


def stall_analysis_from_dict(data: Dict[str, Any]) -> StallAnalysis:
    """Parse StallAnalysis from dictionary."""
    stall_type = None
    if "stall_type" in data:
        try:
            stall_type = StallType(data["stall_type"])
        except ValueError:
            pass

    recommended_action = RecommendedAction.CONTINUE
    if "recommended_action" in data:
        try:
            recommended_action = RecommendedAction(data["recommended_action"])
        except ValueError:
            pass

    return StallAnalysis(
        is_stalled=data.get("is_stalled", False),
        stall_type=stall_type,
        stall_duration_iterations=data.get("stall_duration_iterations", 0),
        stall_duration_ms=data.get("stall_duration_ms", 0),
        elephant_protocol_trigger=data.get("elephant_protocol_trigger", False),
        recommended_action=recommended_action,
        evidence_chain=data.get("evidence_chain", []),
        break_attempt_count=data.get("break_attempt_count", 0),
        last_meaningful_progress_at=data.get("last_meaningful_progress_at"),
    )


@dataclass
class IterationContext:
    """Context for evidence captured during microloop iterations."""

    iteration_number: int
    loop_key: Optional[str] = None
    previous_evidence_id: Optional[str] = None


def iteration_context_to_dict(ctx: IterationContext) -> Dict[str, Any]:
    """Convert IterationContext to dictionary."""
    result: Dict[str, Any] = {"iteration_number": ctx.iteration_number}
    if ctx.loop_key:
        result["loop_key"] = ctx.loop_key
    if ctx.previous_evidence_id:
        result["previous_evidence_id"] = ctx.previous_evidence_id
    return result


def iteration_context_from_dict(data: Dict[str, Any]) -> IterationContext:
    """Parse IterationContext from dictionary."""
    return IterationContext(
        iteration_number=data.get("iteration_number", 1),
        loop_key=data.get("loop_key"),
        previous_evidence_id=data.get("previous_evidence_id"),
    )


@dataclass
class ProgressEvidenceMetadata:
    """Metadata about progress evidence capture."""

    captured_by: str = "kernel"  # kernel, orchestrator, post_hoc_audit, manual
    capture_duration_ms: int = 0
    schema_version: str = "1.0.0"


def progress_evidence_metadata_to_dict(meta: ProgressEvidenceMetadata) -> Dict[str, Any]:
    """Convert ProgressEvidenceMetadata to dictionary."""
    return {
        "captured_by": meta.captured_by,
        "capture_duration_ms": meta.capture_duration_ms,
        "schema_version": meta.schema_version,
    }


def progress_evidence_metadata_from_dict(data: Dict[str, Any]) -> ProgressEvidenceMetadata:
    """Parse ProgressEvidenceMetadata from dictionary."""
    return ProgressEvidenceMetadata(
        captured_by=data.get("captured_by", "kernel"),
        capture_duration_ms=data.get("capture_duration_ms", 0),
        schema_version=data.get("schema_version", "1.0.0"),
    )


@dataclass
class ProgressEvidence:
    """Before/after state proof for Elephant Protocol stall detection.

    This captures the measurable state before and after a step executes,
    enabling detection of runs that generate activity without meaningful
    progress toward exit criteria.

    Attributes:
        evidence_id: Unique identifier (format: pev-YYYYMMDD-HHMMSS-random).
        step_id: Step that produced this evidence.
        flow_key: Flow this evidence belongs to.
        run_id: Run identifier.
        timestamp: ISO 8601 timestamp when evidence was captured.
        state_before: Snapshot before step execution.
        state_after: Snapshot after step execution.
        delta: Computed difference between states.
        forensic_binding: Reference to ForensicMarker for verification.
        stall_analysis: Analysis of stall conditions.
        iteration_context: Context for microloop iterations.
        metadata: Capture metadata.
    """

    evidence_id: str
    step_id: str
    flow_key: str
    run_id: str
    timestamp: str
    state_before: StateSnapshot
    state_after: StateSnapshot
    delta: ProgressDelta
    forensic_binding: Optional[ForensicBinding] = None
    stall_analysis: Optional[StallAnalysis] = None
    iteration_context: Optional[IterationContext] = None
    metadata: Optional[ProgressEvidenceMetadata] = None


def progress_evidence_to_dict(evidence: ProgressEvidence) -> Dict[str, Any]:
    """Convert ProgressEvidence to dictionary for serialization."""
    result: Dict[str, Any] = {
        "evidence_id": evidence.evidence_id,
        "step_id": evidence.step_id,
        "flow_key": evidence.flow_key,
        "run_id": evidence.run_id,
        "timestamp": evidence.timestamp,
        "state_before": state_snapshot_to_dict(evidence.state_before),
        "state_after": state_snapshot_to_dict(evidence.state_after),
        "delta": progress_delta_to_dict(evidence.delta),
    }
    if evidence.forensic_binding:
        result["forensic_binding"] = forensic_binding_to_dict(evidence.forensic_binding)
    if evidence.stall_analysis:
        result["stall_analysis"] = stall_analysis_to_dict(evidence.stall_analysis)
    if evidence.iteration_context:
        result["iteration_context"] = iteration_context_to_dict(evidence.iteration_context)
    if evidence.metadata:
        result["metadata"] = progress_evidence_metadata_to_dict(evidence.metadata)
    return result


def progress_evidence_from_dict(data: Dict[str, Any]) -> ProgressEvidence:
    """Parse ProgressEvidence from dictionary."""
    forensic_binding = None
    if "forensic_binding" in data:
        forensic_binding = forensic_binding_from_dict(data["forensic_binding"])

    stall_analysis = None
    if "stall_analysis" in data:
        stall_analysis = stall_analysis_from_dict(data["stall_analysis"])

    iteration_context = None
    if "iteration_context" in data:
        iteration_context = iteration_context_from_dict(data["iteration_context"])

    metadata = None
    if "metadata" in data:
        metadata = progress_evidence_metadata_from_dict(data["metadata"])

    return ProgressEvidence(
        evidence_id=data.get("evidence_id", ""),
        step_id=data.get("step_id", ""),
        flow_key=data.get("flow_key", ""),
        run_id=data.get("run_id", ""),
        timestamp=data.get("timestamp", ""),
        state_before=state_snapshot_from_dict(data.get("state_before", {})),
        state_after=state_snapshot_from_dict(data.get("state_after", {})),
        delta=progress_delta_from_dict(data.get("delta", {})),
        forensic_binding=forensic_binding,
        stall_analysis=stall_analysis,
        iteration_context=iteration_context,
        metadata=metadata,
    )


# =============================================================================
# Utility functions
# =============================================================================


def compute_stall_indicator(delta: ProgressDelta) -> bool:
    """Compute whether a delta indicates a stall condition.

    The Elephant Protocol uses this to detect runs that generate activity
    without making meaningful progress. A stall is indicated when:

    1. No file changes (files_added + files_modified == 0)
    2. Zero progress (no tests added, no pass delta, no coverage delta)
    3. High churn with low progress (many modifications but negative progress)
    4. Same test failures repeating (test_fail_delta == 0 with failed > 0)

    Args:
        delta: The ProgressDelta to analyze.

    Returns:
        True if this delta indicates a stall condition.
    """
    # No file changes at all
    no_file_changes = (delta.files_added + delta.files_modified) == 0

    # Zero meaningful progress indicators
    zero_progress = (
        delta.tests_added == 0
        and delta.test_pass_delta <= 0
        and (delta.coverage_delta is None or delta.coverage_delta <= 0)
        and delta.lint_error_delta >= 0
        and delta.type_error_delta >= 0
    )

    # High churn with no forward motion
    high_churn = (delta.lines_added + delta.lines_removed) > 100
    low_net_progress = abs(delta.net_lines) < 10

    # Check for stall conditions
    if no_file_changes:
        return True

    if zero_progress and not delta.files_added:
        return True

    if high_churn and low_net_progress and zero_progress:
        return True

    return False


def compute_evidence_hash(verification: ForensicVerification) -> str:
    """Compute SHA256 hash of a ForensicVerification record.

    This creates an integrity hash over the entire verification record,
    enabling tamper detection in the audit trail.

    Args:
        verification: The ForensicVerification to hash.

    Returns:
        SHA256 hex digest of the verification record.
    """
    data = forensic_verification_to_dict(verification)
    # Remove mutable metadata that shouldn't affect the hash
    if "metadata" in data:
        del data["metadata"]
    json_str = json.dumps(data, sort_keys=True)
    return hashlib.sha256(json_str.encode()).hexdigest()


def compute_delta(before: StateSnapshot, after: StateSnapshot) -> ProgressDelta:
    """Compute ProgressDelta from two StateSnapshots.

    This calculates the difference between before and after states,
    determining whether meaningful progress was made.

    Args:
        before: State snapshot before step execution.
        after: State snapshot after step execution.

    Returns:
        ProgressDelta with computed differences and stall indicators.
    """
    # Compute file changes by comparing artifact hashes
    files_added = 0
    files_modified = 0
    files_deleted = 0
    artifacts_changed: List[ArtifactChange] = []

    before_files = set(before.artifact_hashes.keys())
    after_files = set(after.artifact_hashes.keys())

    # Files added
    for path in after_files - before_files:
        files_added += 1
        size_delta = after.artifact_sizes.get(path, 0)
        artifacts_changed.append(ArtifactChange(path=path, change_type="added", size_delta=size_delta))

    # Files deleted
    for path in before_files - after_files:
        files_deleted += 1
        size_delta = -before.artifact_sizes.get(path, 0)
        artifacts_changed.append(ArtifactChange(path=path, change_type="deleted", size_delta=size_delta))

    # Files modified (hash changed)
    for path in before_files & after_files:
        if before.artifact_hashes[path] != after.artifact_hashes[path]:
            files_modified += 1
            size_delta = after.artifact_sizes.get(path, 0) - before.artifact_sizes.get(path, 0)
            artifacts_changed.append(ArtifactChange(path=path, change_type="modified", size_delta=size_delta))

    # Compute other deltas
    lines_added = max(0, after.line_count - before.line_count)
    lines_removed = max(0, before.line_count - after.line_count)
    net_lines = after.line_count - before.line_count

    tests_added = max(0, after.test_count - before.test_count)
    tests_removed = max(0, before.test_count - after.test_count)
    test_pass_delta = after.test_pass_count - before.test_pass_count
    test_fail_delta = after.test_fail_count - before.test_fail_count

    coverage_delta = None
    if before.coverage_percent is not None and after.coverage_percent is not None:
        coverage_delta = after.coverage_percent - before.coverage_percent

    lint_error_delta = after.lint_error_count - before.lint_error_count
    type_error_delta = after.type_error_count - before.type_error_count

    # Compute custom deltas
    custom_deltas: Dict[str, float] = {}
    all_custom_keys = set(before.custom_metrics.keys()) | set(after.custom_metrics.keys())
    for key in all_custom_keys:
        before_val = before.custom_metrics.get(key, 0)
        after_val = after.custom_metrics.get(key, 0)
        if isinstance(before_val, (int, float)) and isinstance(after_val, (int, float)):
            custom_deltas[key] = float(after_val) - float(before_val)

    # Determine meaningful change
    has_meaningful_change = (
        files_added > 0
        or files_modified > 0
        or tests_added > 0
        or test_pass_delta > 0
        or (coverage_delta is not None and coverage_delta > 0)
        or lint_error_delta < 0
        or type_error_delta < 0
    )

    # Build delta
    delta = ProgressDelta(
        has_meaningful_change=has_meaningful_change,
        stall_indicator=False,  # Will be computed
        files_added=files_added,
        files_modified=files_modified,
        files_deleted=files_deleted,
        lines_added=lines_added,
        lines_removed=lines_removed,
        net_lines=net_lines,
        tests_added=tests_added,
        tests_removed=tests_removed,
        test_pass_delta=test_pass_delta,
        test_fail_delta=test_fail_delta,
        coverage_delta=coverage_delta,
        lint_error_delta=lint_error_delta,
        type_error_delta=type_error_delta,
        artifacts_changed=artifacts_changed,
        custom_deltas=custom_deltas,
    )

    # Compute stall indicator
    delta.stall_indicator = compute_stall_indicator(delta)

    # Set stall reason if stalled
    if delta.stall_indicator:
        if (delta.files_added + delta.files_modified) == 0:
            delta.stall_reason = "No file changes detected"
        elif not has_meaningful_change:
            delta.stall_reason = "No meaningful progress metrics improved"
        else:
            delta.stall_reason = "High churn with low net progress"

    # Compute progress score (-1 to 1)
    progress_score = 0.0
    if has_meaningful_change:
        # Positive factors
        progress_score += min(0.3, files_added * 0.1)
        progress_score += min(0.2, files_modified * 0.05)
        progress_score += min(0.2, tests_added * 0.1)
        progress_score += min(0.2, max(0, test_pass_delta) * 0.05)
        if coverage_delta and coverage_delta > 0:
            progress_score += min(0.1, coverage_delta * 0.02)
        # Negative factors
        if lint_error_delta > 0:
            progress_score -= min(0.1, lint_error_delta * 0.02)
        if type_error_delta > 0:
            progress_score -= min(0.1, type_error_delta * 0.02)
        if test_fail_delta > 0:
            progress_score -= min(0.2, test_fail_delta * 0.1)
    else:
        progress_score = -0.5 if delta.stall_indicator else 0.0

    delta.progress_score = max(-1.0, min(1.0, progress_score))

    return delta


def generate_evidence_id() -> str:
    """Generate a unique evidence ID in format: pev-YYYYMMDD-HHMMSS-random."""
    import secrets

    now = datetime.now(timezone.utc)
    date_part = now.strftime("%Y%m%d")
    time_part = now.strftime("%H%M%S")
    random_part = secrets.token_hex(3)  # 6 hex chars
    return f"pev-{date_part}-{time_part}-{random_part}"


def generate_marker_id() -> str:
    """Generate a unique marker ID in format: fm-xxxxxxxx."""
    import secrets

    return f"fm-{secrets.token_hex(4)}"
