"""
test_parser.py - Unified test output parser for forensic verification.

This module parses raw test output from various frameworks (pytest, JUnit XML,
Playwright traces) into a standardized TestSummary format. The Navigator uses
this for forensic verification and stall detection.

Design Philosophy:
    - Parse raw output, not agent claims
    - Extract error signatures for the Elephant Protocol stall detection
    - Support multiple frameworks without external dependencies
    - Produce consistent output regardless of input format

Usage:
    from swarm.runtime.test_parser import (
        TestSummary, parse_pytest_output, parse_junit_xml, parse_playwright_trace
    )

    # Parse pytest console output
    summary = parse_pytest_output(raw_output)

    # Parse JUnit XML file
    summary = parse_junit_xml(Path("test-results.xml"))

    # Parse Playwright trace
    summary = parse_playwright_trace(Path("trace.zip"))

    # Access unified fields
    print(f"Total: {summary.total}, Passed: {summary.passed}, Failed: {summary.failed}")
    print(f"Error signatures: {summary.error_signatures}")
"""

from __future__ import annotations

import hashlib
import json
import re
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from swarm.runtime.forensic_types import (
    FailureType,
    TestFailure,
    TestFramework,
    TestParseResult,
    test_failure_from_dict,
    test_failure_to_dict,
    test_parse_result_from_dict,
    test_parse_result_to_dict,
)


@dataclass
class TestSummary:
    """Standardized test summary for Navigator forensic verification.

    This structure provides a unified view of test results regardless of the
    source format (pytest, JUnit, Playwright). The error_signatures field
    enables the Elephant Protocol to detect stalled loops that produce
    the same failures repeatedly.

    Attributes:
        total: Total number of tests discovered/executed.
        passed: Number of tests that passed.
        failed: Number of tests that failed.
        skipped: Number of tests that were skipped.
        error_signatures: Unique error patterns for stall detection.
            Each signature is a normalized hash of error message + test name,
            enabling detection of repeated failures across iterations.
        duration_ms: Total test execution duration in milliseconds.
        source_format: Framework that produced this output ("pytest", "junit", "playwright").
        raw_output_path: Path to the raw test output file (if applicable).
        errors: Number of tests that errored (distinct from failures).
        failures: Detailed information about each test failure.
        coverage_percent: Code coverage percentage if available.
    """

    total: int
    passed: int
    failed: int
    skipped: int
    error_signatures: List[str] = field(default_factory=list)
    duration_ms: int = 0
    source_format: str = "unknown"
    raw_output_path: Optional[Path] = None
    errors: int = 0
    failures: List[TestFailure] = field(default_factory=list)
    coverage_percent: Optional[float] = None

    @property
    def success_rate(self) -> float:
        """Calculate success rate as a percentage."""
        if self.total == 0:
            return 0.0
        return (self.passed / self.total) * 100.0

    @property
    def all_passed(self) -> bool:
        """Check if all tests passed (no failures or errors)."""
        return self.failed == 0 and self.errors == 0

    @property
    def has_failures(self) -> bool:
        """Check if there are any failures or errors."""
        return self.failed > 0 or self.errors > 0

    def to_test_parse_result(self) -> TestParseResult:
        """Convert to TestParseResult for compatibility with forensic_types."""
        framework = TestFramework.UNKNOWN
        if self.source_format == "pytest":
            framework = TestFramework.PYTEST
        elif self.source_format == "junit":
            framework = TestFramework.JUNIT
        elif self.source_format == "jest":
            framework = TestFramework.JEST
        elif self.source_format == "playwright":
            # Playwright uses Jest-like output format
            framework = TestFramework.JEST

        return TestParseResult(
            total_tests=self.total,
            passed=self.passed,
            failed=self.failed,
            skipped=self.skipped,
            errors=self.errors,
            failures=self.failures,
            duration_ms=self.duration_ms,
            coverage_percent=self.coverage_percent,
            test_framework=framework,
            raw_output_path=str(self.raw_output_path) if self.raw_output_path else None,
        )


def test_summary_to_dict(summary: TestSummary) -> Dict[str, Any]:
    """Convert TestSummary to dictionary for serialization."""
    result: Dict[str, Any] = {
        "total": summary.total,
        "passed": summary.passed,
        "failed": summary.failed,
        "skipped": summary.skipped,
        "error_signatures": summary.error_signatures,
        "duration_ms": summary.duration_ms,
        "source_format": summary.source_format,
        "errors": summary.errors,
        "failures": [test_failure_to_dict(f) for f in summary.failures],
    }
    if summary.raw_output_path:
        result["raw_output_path"] = str(summary.raw_output_path)
    if summary.coverage_percent is not None:
        result["coverage_percent"] = summary.coverage_percent
    return result


def test_summary_from_dict(data: Dict[str, Any]) -> TestSummary:
    """Parse TestSummary from dictionary."""
    failures = [test_failure_from_dict(f) for f in data.get("failures", [])]
    raw_path = data.get("raw_output_path")
    return TestSummary(
        total=data.get("total", 0),
        passed=data.get("passed", 0),
        failed=data.get("failed", 0),
        skipped=data.get("skipped", 0),
        error_signatures=data.get("error_signatures", []),
        duration_ms=data.get("duration_ms", 0),
        source_format=data.get("source_format", "unknown"),
        raw_output_path=Path(raw_path) if raw_path else None,
        errors=data.get("errors", 0),
        failures=failures,
        coverage_percent=data.get("coverage_percent"),
    )


def _compute_error_signature(test_name: str, error_message: str) -> str:
    """Compute a stable error signature for stall detection.

    The signature is a hash of normalized test name + error message.
    This enables the Elephant Protocol to detect when the same
    failures are occurring across multiple iterations.

    Args:
        test_name: Fully qualified test name.
        error_message: Error message from the failure.

    Returns:
        SHA-256 hash prefix (16 chars) as the signature.
    """
    # Normalize: lowercase, strip whitespace, remove line numbers
    normalized_name = test_name.lower().strip()
    normalized_msg = re.sub(r"line \d+", "line N", error_message.lower().strip())
    # Remove file paths that might vary
    normalized_msg = re.sub(r"(/[^\s]+)+", "<path>", normalized_msg)
    # Remove memory addresses
    normalized_msg = re.sub(r"0x[0-9a-f]+", "0xADDR", normalized_msg)

    combined = f"{normalized_name}::{normalized_msg}"
    return hashlib.sha256(combined.encode()).hexdigest()[:16]


def _detect_failure_type(error_message: str, stack_trace: Optional[str] = None) -> FailureType:
    """Detect the type of failure from error message and stack trace."""
    msg_lower = error_message.lower()
    trace_lower = (stack_trace or "").lower()

    if "timeout" in msg_lower or "timed out" in msg_lower:
        return FailureType.TIMEOUT
    if "assert" in msg_lower or "expected" in msg_lower:
        return FailureType.ASSERTION
    if "setup" in trace_lower or "setup" in msg_lower:
        return FailureType.SETUP
    if "teardown" in trace_lower or "teardown" in msg_lower:
        return FailureType.TEARDOWN
    if "error" in msg_lower or "exception" in msg_lower:
        return FailureType.EXCEPTION

    return FailureType.UNKNOWN


def _extract_expected_actual(error_message: str) -> Tuple[Optional[str], Optional[str]]:
    """Extract expected and actual values from assertion error message."""
    # Common patterns:
    # "assert X == Y" -> expected=Y, actual=X
    # "Expected X but got Y" -> expected=X, actual=Y
    # "AssertionError: expected 401, got 500"

    patterns = [
        # Pattern: "expected X, got Y" or "Expected X but got Y"
        r"expected[:\s]+([^\s,]+)[,\s]+(?:but\s+)?got[:\s]+([^\s]+)",
        # Pattern: "assert X == Y"
        r"assert\s+(\S+)\s*==\s*(\S+)",
        # Pattern: "X != Y"
        r"(\S+)\s*!=\s*(\S+)",
    ]

    for pattern in patterns:
        match = re.search(pattern, error_message, re.IGNORECASE)
        if match:
            if "expected" in pattern.lower():
                return match.group(1), match.group(2)  # expected, actual
            else:
                return match.group(2), match.group(1)  # actual, expected (swap for assert)

    return None, None


# =============================================================================
# Pytest Parser
# =============================================================================


def parse_pytest_output(raw: str, raw_output_path: Optional[Path] = None) -> TestSummary:
    """Parse pytest console output into a standardized TestSummary.

    Handles both verbose and summary output formats. Extracts:
    - Test counts from the summary line (e.g., "5 passed, 2 failed in 1.23s")
    - Failure details from FAILURES section
    - Duration from timing information

    Args:
        raw: Raw pytest console output as string.
        raw_output_path: Optional path to the raw output file for reference.

    Returns:
        TestSummary with parsed test results.
    """
    summary = TestSummary(
        total=0,
        passed=0,
        failed=0,
        skipped=0,
        source_format="pytest",
        raw_output_path=raw_output_path,
    )

    if not raw or not raw.strip():
        return summary

    lines = raw.split("\n")

    # Parse summary line patterns. Common pytest formats:
    # "====== 13 passed, 2 failed in 3.45s ======"
    # "===== 5 passed, 1 skipped, 2 failed in 1.23s ====="
    # "5 passed in 1.23s"
    # Note: parts can appear in any order

    for line in lines:
        # Look for lines with "passed" and timing info (likely summary lines)
        if "passed" in line.lower() and ("in " in line or "==" in line):
            # Extract all counts using individual patterns
            passed_match = re.search(r"(\d+)\s+passed", line, re.IGNORECASE)
            failed_match = re.search(r"(\d+)\s+failed", line, re.IGNORECASE)
            skipped_match = re.search(r"(\d+)\s+skipped", line, re.IGNORECASE)
            error_match = re.search(r"(\d+)\s+error(?:s)?", line, re.IGNORECASE)
            xfailed_match = re.search(r"(\d+)\s+xfailed", line, re.IGNORECASE)
            xpassed_match = re.search(r"(\d+)\s+xpassed", line, re.IGNORECASE)
            duration_match = re.search(r"in\s+([\d.]+)s", line, re.IGNORECASE)

            if passed_match:
                summary.passed = int(passed_match.group(1))
            if failed_match:
                summary.failed = int(failed_match.group(1))
            if skipped_match:
                summary.skipped = int(skipped_match.group(1))
            if error_match:
                summary.errors = int(error_match.group(1))
            if xfailed_match:
                summary.skipped += int(xfailed_match.group(1))
            if xpassed_match:
                summary.passed += int(xpassed_match.group(1))
            if duration_match:
                summary.duration_ms = int(float(duration_match.group(1)) * 1000)

            # If we found at least passed, this is likely the summary line
            if passed_match:
                break

    summary.total = summary.passed + summary.failed + summary.skipped + summary.errors

    # Parse FAILURES section for detailed failure info
    in_failures = False
    current_test_name = ""
    current_error_lines: List[str] = []
    current_file = ""
    current_line = 0

    failure_header_pattern = re.compile(r"_{5,}\s+(\S+)\s+_{5,}")
    file_line_pattern = re.compile(r"(\S+\.py):(\d+):")

    for line in lines:
        if "= FAILURES =" in line or "= ERRORS =" in line:
            in_failures = True
            continue

        if in_failures:
            # Check for new failure header
            header_match = failure_header_pattern.search(line)
            if header_match:
                # Save previous failure
                if current_test_name and current_error_lines:
                    error_msg = "\n".join(current_error_lines).strip()
                    failure_type = _detect_failure_type(error_msg)
                    expected, actual = _extract_expected_actual(error_msg)

                    failure = TestFailure(
                        test_name=current_test_name,
                        error_message=error_msg[:2000],  # Truncate for sanity
                        test_file=current_file or None,
                        test_line=current_line or None,
                        failure_type=failure_type,
                        expected=expected,
                        actual=actual,
                    )
                    summary.failures.append(failure)
                    summary.error_signatures.append(
                        _compute_error_signature(current_test_name, error_msg)
                    )

                current_test_name = header_match.group(1)
                current_error_lines = []
                current_file = ""
                current_line = 0
                continue

            # Check for file:line reference
            file_match = file_line_pattern.search(line)
            if file_match and not current_file:
                current_file = file_match.group(1)
                current_line = int(file_match.group(2))

            current_error_lines.append(line)

            # Check for end of failures section
            if line.startswith("=") and "short test summary" in line.lower():
                in_failures = False

    # Save last failure
    if current_test_name and current_error_lines:
        error_msg = "\n".join(current_error_lines).strip()
        failure_type = _detect_failure_type(error_msg)
        expected, actual = _extract_expected_actual(error_msg)

        failure = TestFailure(
            test_name=current_test_name,
            error_message=error_msg[:2000],
            test_file=current_file or None,
            test_line=current_line or None,
            failure_type=failure_type,
            expected=expected,
            actual=actual,
        )
        summary.failures.append(failure)
        summary.error_signatures.append(
            _compute_error_signature(current_test_name, error_msg)
        )

    # Deduplicate error signatures
    summary.error_signatures = list(dict.fromkeys(summary.error_signatures))

    return summary


# =============================================================================
# JUnit XML Parser
# =============================================================================


def parse_junit_xml(xml_path: Path) -> TestSummary:
    """Parse JUnit XML test results into a standardized TestSummary.

    JUnit XML is a common format used by many test frameworks:
    - pytest with --junitxml
    - Jest with jest-junit
    - Cargo with cargo2junit
    - Maven/Gradle JUnit tests

    Args:
        xml_path: Path to the JUnit XML file.

    Returns:
        TestSummary with parsed test results.
    """
    summary = TestSummary(
        total=0,
        passed=0,
        failed=0,
        skipped=0,
        source_format="junit",
        raw_output_path=xml_path,
    )

    if not xml_path.exists():
        return summary

    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
    except ET.ParseError:
        return summary

    # Handle both <testsuites> and <testsuite> root elements
    if root.tag == "testsuites":
        testsuites = root.findall("testsuite")
    elif root.tag == "testsuite":
        testsuites = [root]
    else:
        return summary

    total_time = 0.0

    for testsuite in testsuites:
        # Extract suite-level attributes
        suite_tests = int(testsuite.get("tests", 0))
        suite_failures = int(testsuite.get("failures", 0))
        suite_errors = int(testsuite.get("errors", 0))
        suite_skipped = int(testsuite.get("skipped", 0))
        suite_time = float(testsuite.get("time", 0))

        summary.total += suite_tests
        summary.failed += suite_failures
        summary.errors += suite_errors
        summary.skipped += suite_skipped
        total_time += suite_time

        # Parse individual test cases for failure details
        for testcase in testsuite.findall("testcase"):
            test_name = testcase.get("name", "")
            classname = testcase.get("classname", "")
            full_name = f"{classname}::{test_name}" if classname else test_name
            test_time = float(testcase.get("time", 0))

            # Check for failure or error
            failure = testcase.find("failure")
            error = testcase.find("error")
            skipped = testcase.find("skipped")

            if failure is not None:
                error_msg = failure.get("message", "")
                stack_trace = failure.text or ""
                failure_type = _detect_failure_type(error_msg, stack_trace)
                expected, actual = _extract_expected_actual(error_msg)

                test_failure = TestFailure(
                    test_name=full_name,
                    error_message=error_msg[:2000],
                    stack_trace=stack_trace[:5000] if stack_trace else None,
                    failure_type=failure_type,
                    expected=expected,
                    actual=actual,
                    duration_ms=int(test_time * 1000),
                )
                summary.failures.append(test_failure)
                summary.error_signatures.append(
                    _compute_error_signature(full_name, error_msg)
                )

            elif error is not None:
                error_msg = error.get("message", "")
                stack_trace = error.text or ""
                failure_type = _detect_failure_type(error_msg, stack_trace)

                test_failure = TestFailure(
                    test_name=full_name,
                    error_message=error_msg[:2000],
                    stack_trace=stack_trace[:5000] if stack_trace else None,
                    failure_type=failure_type,
                    duration_ms=int(test_time * 1000),
                )
                summary.failures.append(test_failure)
                summary.error_signatures.append(
                    _compute_error_signature(full_name, error_msg)
                )

    # Calculate passed from total - failures - errors - skipped
    summary.passed = max(0, summary.total - summary.failed - summary.errors - summary.skipped)
    summary.duration_ms = int(total_time * 1000)

    # Deduplicate error signatures
    summary.error_signatures = list(dict.fromkeys(summary.error_signatures))

    return summary


# =============================================================================
# Playwright Trace Parser
# =============================================================================


def parse_playwright_trace(trace_path: Path) -> TestSummary:
    """Parse Playwright trace archive into a standardized TestSummary.

    Playwright traces are ZIP archives containing test execution data.
    We extract the test results from the trace's resources.json or
    the test-results.json if available.

    Args:
        trace_path: Path to the Playwright trace ZIP file or directory.

    Returns:
        TestSummary with parsed test results.
    """
    summary = TestSummary(
        total=0,
        passed=0,
        failed=0,
        skipped=0,
        source_format="playwright",
        raw_output_path=trace_path,
    )

    if not trace_path.exists():
        return summary

    # Handle both ZIP archives and directories
    if trace_path.is_file() and trace_path.suffix == ".zip":
        summary = _parse_playwright_zip(trace_path, summary)
    elif trace_path.is_dir():
        summary = _parse_playwright_directory(trace_path, summary)
    elif trace_path.suffix == ".json":
        # Direct JSON file (test-results.json or report.json)
        summary = _parse_playwright_json(trace_path, summary)

    return summary


def _parse_playwright_zip(zip_path: Path, summary: TestSummary) -> TestSummary:
    """Parse Playwright trace from ZIP archive."""
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            # Look for test results in common locations
            for name in ["test-results.json", "report.json", "resources.json"]:
                try:
                    with zf.open(name) as f:
                        data = json.load(f)
                        return _process_playwright_data(data, summary)
                except (KeyError, json.JSONDecodeError):
                    continue
    except zipfile.BadZipFile:
        pass

    return summary


def _parse_playwright_directory(dir_path: Path, summary: TestSummary) -> TestSummary:
    """Parse Playwright trace from directory."""
    # Look for common result files
    for name in ["test-results.json", "report.json", "results.json"]:
        json_file = dir_path / name
        if json_file.exists():
            return _parse_playwright_json(json_file, summary)

    return summary


def _parse_playwright_json(json_path: Path, summary: TestSummary) -> TestSummary:
    """Parse Playwright JSON results file."""
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return _process_playwright_data(data, summary)
    except (json.JSONDecodeError, IOError):
        return summary


def _process_playwright_data(data: Dict[str, Any], summary: TestSummary) -> TestSummary:
    """Process Playwright JSON data structure."""
    # Handle Playwright HTML Reporter format
    if "suites" in data:
        return _process_playwright_suites(data.get("suites", []), summary)

    # Handle Playwright JSON Reporter format
    if "results" in data:
        for result in data.get("results", []):
            _process_playwright_result(result, summary)
        return summary

    # Handle direct test array
    if isinstance(data, list):
        for item in data:
            _process_playwright_result(item, summary)
        return summary

    return summary


def _process_playwright_suites(suites: List[Dict[str, Any]], summary: TestSummary) -> TestSummary:
    """Process Playwright test suites recursively."""
    for suite in suites:
        # Process nested suites
        if "suites" in suite:
            _process_playwright_suites(suite["suites"], summary)

        # Process specs/tests in this suite
        for spec in suite.get("specs", []):
            for test in spec.get("tests", []):
                _process_playwright_test(test, spec.get("title", ""), summary)

    return summary


def _process_playwright_test(
    test: Dict[str, Any], spec_title: str, summary: TestSummary
) -> None:
    """Process a single Playwright test result."""
    summary.total += 1

    status = test.get("status", "").lower()
    expected_status = test.get("expectedStatus", "passed").lower()

    if status == "passed" or status == expected_status:
        summary.passed += 1
    elif status == "failed" or status == "timedOut":
        summary.failed += 1

        # Extract failure details from results
        results = test.get("results", [])
        if results:
            result = results[0]  # Use first result
            error = result.get("error", {})
            error_msg = error.get("message", "") or str(error)
            stack_trace = error.get("stack", "")

            test_name = f"{spec_title}::{test.get('title', 'unknown')}"
            failure_type = _detect_failure_type(error_msg, stack_trace)

            if status == "timedOut":
                failure_type = FailureType.TIMEOUT

            failure = TestFailure(
                test_name=test_name,
                error_message=error_msg[:2000],
                stack_trace=stack_trace[:5000] if stack_trace else None,
                failure_type=failure_type,
                duration_ms=result.get("duration", 0),
            )
            summary.failures.append(failure)
            summary.error_signatures.append(
                _compute_error_signature(test_name, error_msg)
            )
    elif status == "skipped":
        summary.skipped += 1

    # Add duration
    for result in test.get("results", []):
        summary.duration_ms += result.get("duration", 0)


def _process_playwright_result(result: Dict[str, Any], summary: TestSummary) -> None:
    """Process a single Playwright result entry (JSON Reporter format)."""
    summary.total += 1

    status = result.get("status", "").lower()
    if status == "passed":
        summary.passed += 1
    elif status in ("failed", "timedout"):
        summary.failed += 1

        test_name = result.get("title", result.get("name", "unknown"))
        error = result.get("error", {})
        error_msg = error.get("message", "") if isinstance(error, dict) else str(error)
        stack_trace = error.get("stack", "") if isinstance(error, dict) else ""

        failure_type = _detect_failure_type(error_msg, stack_trace)
        if status == "timedout":
            failure_type = FailureType.TIMEOUT

        failure = TestFailure(
            test_name=test_name,
            error_message=error_msg[:2000],
            stack_trace=stack_trace[:5000] if stack_trace else None,
            failure_type=failure_type,
            duration_ms=result.get("duration", 0),
        )
        summary.failures.append(failure)
        summary.error_signatures.append(
            _compute_error_signature(test_name, error_msg)
        )
    elif status == "skipped":
        summary.skipped += 1

    summary.duration_ms += result.get("duration", 0)


# =============================================================================
# Unified Parser Interface
# =============================================================================


def parse_test_output(
    source: str | Path,
    format_hint: Optional[str] = None,
) -> TestSummary:
    """Parse test output with automatic format detection.

    This is the main entry point for parsing test results. It attempts
    to auto-detect the format based on file extension or content.

    Args:
        source: Either a raw string (for pytest output) or a Path to a file.
        format_hint: Optional hint for format ("pytest", "junit", "playwright").
            If not provided, will attempt auto-detection.

    Returns:
        TestSummary with parsed test results.
    """
    # Handle Path input
    if isinstance(source, Path):
        if not source.exists():
            return TestSummary(
                total=0, passed=0, failed=0, skipped=0, source_format="unknown"
            )

        # Auto-detect from extension
        ext = source.suffix.lower()
        if format_hint == "junit" or ext == ".xml":
            return parse_junit_xml(source)
        elif format_hint == "playwright" or ext == ".zip":
            return parse_playwright_trace(source)
        elif ext == ".json":
            # Could be Playwright JSON or other format
            return parse_playwright_trace(source)
        else:
            # Try to read as text and parse as pytest
            try:
                content = source.read_text(encoding="utf-8")
                return parse_pytest_output(content, source)
            except (IOError, UnicodeDecodeError):
                return TestSummary(
                    total=0, passed=0, failed=0, skipped=0, source_format="unknown"
                )

    # Handle string input (assumed pytest)
    return parse_pytest_output(source)


def compare_summaries(before: TestSummary, after: TestSummary) -> Dict[str, Any]:
    """Compare two test summaries to detect stall conditions.

    This is used by the Elephant Protocol to detect loops that
    produce the same failures repeatedly.

    Args:
        before: Previous test summary.
        after: Current test summary.

    Returns:
        Dict with comparison results including:
        - is_stalled: True if same failures are occurring
        - new_failures: Signatures of new failures
        - resolved_failures: Signatures of resolved failures
        - persistent_failures: Signatures appearing in both
    """
    before_sigs = set(before.error_signatures)
    after_sigs = set(after.error_signatures)

    persistent = before_sigs & after_sigs
    new_failures = after_sigs - before_sigs
    resolved = before_sigs - after_sigs

    # Detect stall: same failures, no progress
    is_stalled = (
        len(persistent) > 0
        and len(new_failures) == 0
        and len(resolved) == 0
        and after.failed >= before.failed
    )

    return {
        "is_stalled": is_stalled,
        "new_failures": list(new_failures),
        "resolved_failures": list(resolved),
        "persistent_failures": list(persistent),
        "before_total": before.total,
        "after_total": after.total,
        "before_passed": before.passed,
        "after_passed": after.passed,
        "progress_delta": after.passed - before.passed,
    }
