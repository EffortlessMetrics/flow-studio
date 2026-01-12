#!/usr/bin/env python3
"""
selftest.py - Main selftest orchestrator

Orchestrates execution of selftest steps with support for:
- Composable, layered execution
- Degraded mode (only KERNEL steps block)
- Step-by-step or range execution
- Detailed reporting and machine-parseable output

## CLI Usage

Run full selftest (fail on KERNEL or GOVERNANCE):
  uv run swarm/tools/selftest.py

Show selftest plan:
  uv run swarm/tools/selftest.py --plan

Run with degraded mode (only KERNEL failures block):
  uv run swarm/tools/selftest.py --degraded

Run only one step:
  uv run swarm/tools/selftest.py --step core-checks

Run all steps up to a specific step:
  uv run swarm/tools/selftest.py --until devex-contract

Verbose output with timing:
  uv run swarm/tools/selftest.py --verbose

Run and output JSON report:
  uv run swarm/tools/selftest.py --json > report.json

Run kernel smoke checks only:
  uv run swarm/tools/selftest.py --kernel-only

## Exit Codes

0   All executed steps passed
1   One or more steps failed (blocking tier)
2   Configuration error or invalid arguments

## Output Format

Default: Human-readable text with per-step status (PASS / FAIL / SKIP)
--json: Machine-parseable JSON report with timing, commands, output

## Modes

- default: Run all steps, fail on KERNEL or GOVERNANCE failures
- --degraded: Run all steps, fail only on KERNEL failures
- --kernel-only: Run only KERNEL tier steps
- --step <id>: Run only the specified step
- --until <id>: Run steps in order up to and including <id>
- --plan: Show the execution plan without running
"""

import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class StepStatus(str, Enum):
    """
    Unified step status vocabulary used throughout the selftest system.

    This enum provides a single source of truth for step status values:
    - PASS: Step completed successfully (exit code 0)
    - FAIL: Step failed (non-zero exit code)
    - SKIP: Step was explicitly skipped (user request or dependency failure)
    - TIMEOUT: Step exceeded time limit
    """
    PASS = "PASS"
    FAIL = "FAIL"
    SKIP = "SKIP"
    TIMEOUT = "TIMEOUT"

# Import selftest config
try:
    from selftest_config import (
        EXECUTION_WAVES,
        SELFTEST_STEPS,
        SelfTestCategory,
        SelfTestSeverity,
        SelfTestStep,
        SelfTestTier,
        get_step_by_id,
        get_steps_in_order,
        validate_step_list,
        validate_wave_definitions,
    )
except ImportError:
    print("Error: Could not import selftest_config module", file=sys.stderr)
    sys.exit(2)

# Import centralized paths
try:
    from selftest_paths import DEGRADATIONS_LOG_PATH, parse_skip_steps
except ImportError:
    print("Error: Could not import selftest_paths module", file=sys.stderr)
    sys.exit(2)

# Import schema and artifact manager
try:
    from artifact_manager import ArtifactManager
    from selftest_report_schema import (
        SelfTestReport,
        SelfTestReportMetadata,
        SelfTestStepResult,
        SelfTestSummary,
    )
except ImportError:
    print("Error: Could not import selftest_report_schema or artifact_manager modules", file=sys.stderr)
    sys.exit(2)

# Import observability backend manager (optional, graceful fallback if not available)
try:
    from observability_backends import BackendManager
    OBSERVABILITY_AVAILABLE = True
except ImportError:
    OBSERVABILITY_AVAILABLE = False
    # No-op backend manager
    class BackendManager:
        def __init__(self, *args, **kwargs):
            pass
        def emit_run_started(self, *args, **kwargs):
            pass
        def emit_step_completed(self, *args, **kwargs):
            pass
        def emit_step_failed(self, *args, **kwargs):
            pass
        def emit_run_completed(self, *args, **kwargs):
            pass
        def close(self):
            pass

# Import metrics (optional, graceful fallback if not available)
try:
    from selftest_metrics import SelftestMetrics
    METRICS_AVAILABLE = True
except ImportError:
    METRICS_AVAILABLE = False
    # No-op metrics class
    class SelftestMetrics:
        def __init__(self, *args, **kwargs):
            pass
        def step_started(self, *args, **kwargs):
            pass
        def step_completed(self, *args, **kwargs):
            pass
        def degradation_logged(self, *args, **kwargs):
            pass
        def run_completed(self, *args, **kwargs):
            pass


# Frozen JSONL schema for degradation logging (AC-SELFTEST-DEGRADATION-TRACKED)
DEGRADATION_LOG_SCHEMA = {
    "version": "1.1",
    "required_fields": [
        "timestamp",  # ISO 8601 UTC timestamp
        "step_id",  # Unique step identifier (e.g., "agents-governance")
        "step_name",  # Human-readable step description
        "tier",  # Selftest tier: "kernel", "governance", "optional"
        "status",  # StepStatus value: "PASS", "FAIL", "SKIP", "TIMEOUT"
        "reason",  # Why step ended in this status (e.g., "nonzero_exit", "timeout")
        "message",  # Failure output from step (stderr or stdout)
        "severity",  # Severity level: "critical", "warning", "info"
        "remediation",  # Suggested fix command
    ],
    "example": {
        "timestamp": "2025-12-01T10:15:22+00:00",
        "step_id": "agents-governance",
        "step_name": "Agent definitions linting and formatting",
        "tier": "governance",
        "status": "FAIL",
        "reason": "nonzero_exit",
        "message": "Agent 'foo-bar' not found in registry",
        "severity": "warning",
        "remediation": "Run: uv run swarm/tools/selftest.py --step agents-governance for details",
    },
}


def get_selftest_plan_json(steps: Optional[List[SelfTestStep]] = None) -> Dict[str, Any]:
    """
    Get selftest plan as JSON structure with AC ID traceability.

    Args:
        steps: List of steps to include in plan. If None, uses all steps.

    Returns:
        Dict with version, steps array (including ac_ids), and summary
    """
    if steps is None:
        steps = SELFTEST_STEPS

    return {
        "version": "1.0",
        "steps": [
            {
                "id": step.id,
                "tier": step.tier.value,
                "severity": step.severity.value,
                "category": step.category.value,
                "description": step.description,
                "ac_ids": step.ac_ids or [],
                "depends_on": step.dependencies or [],
            }
            for step in steps
        ],
        "summary": {
            "total": len(steps),
            "by_tier": {
                "kernel": sum(1 for s in steps if s.tier == SelfTestTier.KERNEL),
                "governance": sum(1 for s in steps if s.tier == SelfTestTier.GOVERNANCE),
                "optional": sum(1 for s in steps if s.tier == SelfTestTier.OPTIONAL),
            },
        },
    }


class SelfTestResult:
    """
    Result of running a single selftest step.

    Uses the StepStatus enum to provide a unified status vocabulary:
    - status: The step's outcome (PASS, FAIL, SKIP, TIMEOUT)
    - reason: Optional explanation for the status (e.g., "skipped_by_user", "timeout", "nonzero_exit")
    """

    step: SelfTestStep
    status: StepStatus
    reason: Optional[str]
    duration_ms: int
    stdout: str
    stderr: str
    exit_code: int
    timestamp_start: float
    timestamp_end: float
    severity: SelfTestSeverity
    category: SelfTestCategory

    def __init__(self, step: SelfTestStep) -> None:
        self.step = step
        self.status = StepStatus.FAIL  # Default until proven otherwise
        self.reason = None
        self.duration_ms = 0
        self.stdout = ""
        self.stderr = ""
        self.exit_code = -1
        self.timestamp_start = 0.0
        self.timestamp_end = 0.0
        self.severity = step.severity
        self.category = step.category

    @property
    def passed(self) -> bool:
        """Backward compatibility: True if status is PASS."""
        return self.status == StepStatus.PASS

    @property
    def skipped(self) -> bool:
        """Backward compatibility: True if status is SKIP."""
        return self.status == StepStatus.SKIP

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result = {
            "step_id": self.step.id,
            "description": self.step.description,
            "tier": self.step.tier.value,
            "severity": self.severity.value,
            "category": self.category.value,
            "status": self.status.value,
            "exit_code": self.exit_code,
            "duration_ms": self.duration_ms,
            "command": self.step.full_command(),
            "timestamp_start": self.timestamp_start,
            "timestamp_end": self.timestamp_end,
        }
        if self.reason:
            result["reason"] = self.reason
        return result


class SelfTestRunner:
    """Orchestrates selftest execution."""

    degraded: bool
    kernel_only: bool
    verbose: bool
    json_output: bool
    json_v2: bool
    write_report: bool
    artifact_manager: Optional[ArtifactManager]
    results: List[SelfTestResult]
    failed_steps: List[str]
    kernel_failed: List[str]
    governance_failed: List[str]
    optional_failed: List[str]
    skipped_steps: List[str]
    degradation_log_path: str
    metrics: SelftestMetrics
    backends: BackendManager
    run_id: str
    run_start_time: float
    skip_steps: set

    def __init__(
        self,
        degraded: bool = False,
        kernel_only: bool = False,
        verbose: bool = False,
        json_output: bool = False,
        json_v2: bool = False,
        write_report: bool = True,
        skip_steps: Optional[set] = None,
    ) -> None:
        self.degraded = degraded
        self.kernel_only = kernel_only
        self.verbose = verbose
        self.json_output = json_output
        self.json_v2 = json_v2
        self.write_report = write_report
        # Initialize skip_steps from parameter or environment variable
        self.skip_steps = skip_steps if skip_steps is not None else parse_skip_steps(
            os.environ.get("SELFTEST_SKIP_STEPS", "")
        )
        self.artifact_manager = ArtifactManager() if write_report else None
        self.results: List[SelfTestResult] = []
        self.failed_steps: List[str] = []
        # Tier-aware metadata for status API
        self.kernel_failed: List[str] = []
        self.governance_failed: List[str] = []
        self.optional_failed: List[str] = []
        self.skipped_steps: List[str] = []
        # Use centralized path constant to ensure consistency with BDD tests
        self.degradation_log_path = str(DEGRADATIONS_LOG_PATH)
        # Initialize metrics collector
        self.metrics = SelftestMetrics()
        # Initialize observability backends (suppress warnings in JSON mode to avoid corrupting output)
        if json_output or json_v2:
            import logging
            old_level = logging.getLogger().level
            logging.getLogger().setLevel(logging.ERROR)
            self.backends = BackendManager()
            logging.getLogger().setLevel(old_level)
        else:
            self.backends = BackendManager()
        # Generate run_id for observability tracking
        self.run_id = f"selftest-{int(time.time())}"
        self.run_start_time = 0.0

    def print_header(self) -> None:
        """Print test header."""
        if self.json_output or self.json_v2:
            return
        print("=" * 70)
        print("SELFTEST RUNNER")
        print("=" * 70)
        if self.degraded:
            print("Mode: DEGRADED (only KERNEL failures block)")
        elif self.kernel_only:
            print("Mode: KERNEL-ONLY")
        else:
            print("Mode: STRICT (KERNEL and GOVERNANCE failures block)")
        print()

    def print_footer(self) -> None:
        """Print test footer with summary."""
        if self.json_output or self.json_v2:
            return
        print()
        print("=" * 70)
        print("SELFTEST SUMMARY")
        print("=" * 70)

        passed = sum(1 for r in self.results if r.passed)
        failed = sum(1 for r in self.results if not r.passed and not r.skipped)
        skipped = sum(1 for r in self.results if r.skipped)
        total = len(self.results)

        print(f"Passed:  {passed}/{total}")
        print(f"Failed:  {failed}/{total}")
        print(f"Skipped: {skipped}/{total}")

        if self.failed_steps:
            print("\nFailed steps:")
            for step_id in self.failed_steps:
                print(f"  - {step_id}")

            # Add actionable hints for failures
            print("\nHints for resolution:")
            if self.kernel_failed:
                print("  [!] KERNEL failure(s): This blocks all merges")
                for step_id in self.kernel_failed:
                    print(f"    Run: uv run swarm/tools/selftest.py --step {step_id}")
            if self.governance_failed:
                if self.kernel_failed:
                    print()
                print("  [*] GOVERNANCE failure(s): Run any of:")
                for step_id in self.governance_failed:
                    print(f"    Run: uv run swarm/tools/selftest.py --step {step_id}")
                if not self.kernel_failed:
                    print("  [*] Or try: uv run swarm/tools/selftest.py --degraded to work around governance failures")
            print("  [>] See: docs/SELFTEST_SYSTEM.md for more information")
            print("  [>] Run: uv run swarm/tools/selftest.py --plan to see all steps")

        total_ms = sum(r.duration_ms for r in self.results)
        print(f"\nTotal time: {total_ms / 1000:.2f}s")

        # Print health status (for kernel-smoke)
        if self.kernel_only:
            print()
            if failed == 0:
                print("Status: HEALTHY")
            else:
                print("Status: BROKEN")

        # Add severity and category breakdowns
        summary_dict = self._build_summary()

        print("\nBreakdown by Severity:")
        for sev in ["critical", "warning", "info"]:
            counts = summary_dict["by_severity"].get(sev, {})
            print(f"  {sev:10s}: {counts.get('passed', 0):2d} passed, {counts.get('failed', 0):2d} failed")

        print("\nBreakdown by Category:")
        for cat in ["security", "performance", "correctness", "governance"]:
            counts = summary_dict["by_category"].get(cat, {})
            print(f"  {cat:12s}: {counts.get('passed', 0):2d} passed, {counts.get('failed', 0):2d} failed")

    def show_plan(self, steps: List[SelfTestStep]) -> None:
        """Show execution plan without running (human-readable or JSON format)."""
        if self.json_output or self.json_v2:
            self.show_plan_json(steps)
        else:
            self.show_plan_text(steps)

    def show_plan_text(self, steps: List[SelfTestStep]) -> None:
        """Show execution plan in human-readable format."""
        print("=" * 70)
        print("SELFTEST PLAN")
        print("=" * 70)
        print()
        for i, step in enumerate(steps, 1):
            tier_str = step.tier.value.upper()
            severity_str = step.severity.value.upper()
            category_str = step.category.value.upper()
            deps_str = f" (depends: {', '.join(step.dependencies)})" if step.dependencies else ""
            print(f"[{i}] {step.id:20s} [{tier_str:10s}] [{severity_str:8s}] [{category_str:12s}] {step.description}{deps_str}")
        print()
        print(f"Total steps: {len(steps)}")
        print()

    def show_plan_json(self, steps: List[SelfTestStep]) -> None:
        """Show execution plan in JSON format."""
        plan_data = get_selftest_plan_json(steps)
        print(json.dumps(plan_data, indent=2))

    def log_degradation(self, result: SelfTestResult) -> None:
        """
        Log a governance/optional failure in degraded mode to persistent log.

        The log entry includes:
        - timestamp: ISO 8601 UTC timestamp
        - step_id: Step identifier
        - step_name: Human-readable description
        - tier: Selftest tier (governance, optional)
        - status: StepStatus value (FAIL, TIMEOUT)
        - reason: Why the step ended up in this status
        - message: Error output (stderr or stdout)
        - severity: Step severity level
        - remediation: Suggested fix command
        """
        if not self.degraded:
            return  # Only log in degraded mode

        if result.step.tier == SelfTestTier.KERNEL:
            return  # Don't log kernel failures (they still block)

        try:
            log_entry = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "step_id": result.step.id,
                "step_name": result.step.description,
                "tier": result.step.tier.value,
                "status": result.status.value,
                "reason": result.reason or "unknown",
                "message": result.stderr or result.stdout or "(no output)",
                "severity": result.severity.value,
                "remediation": f"Run: uv run swarm/tools/selftest.py --step {result.step.id} for details",
            }

            with open(self.degradation_log_path, "a") as f:
                f.write(json.dumps(log_entry) + "\n")

            # Emit degradation metric
            self.metrics.degradation_logged(
                step_id=result.step.id,
                tier=result.step.tier.value,
                severity=result.severity.value,
            )
        except Exception as e:
            if self.verbose:
                print(f"Warning: Failed to log degradation for {result.step.id}: {e}", file=sys.stderr)

    def run_step(self, step: SelfTestStep, all_results: Dict[str, SelfTestResult]) -> SelfTestResult:  # noqa: C901
        """
        Execute a single selftest step.

        Returns:
            SelfTestResult with status and output
        """
        result = SelfTestResult(step)

        # Check for explicit skip via skip_steps (first-class skip semantics)
        if step.id in self.skip_steps:
            result.status = StepStatus.SKIP
            result.reason = "skipped_by_user"
            result.exit_code = 0
            result.stdout = "Step skipped via SELFTEST_SKIP_STEPS or --skip-steps"
            self.skipped_steps.append(step.id)
            if not self.json_output and not self.json_v2:
                print(f"SKIP {step.id:20s} (requested via SELFTEST_SKIP_STEPS)")
            return result

        # Check dependencies
        if step.dependencies:
            for dep_id in step.dependencies:
                dep_result = all_results.get(dep_id)
                if dep_result is None or not dep_result.passed:
                    result.status = StepStatus.SKIP
                    result.reason = f"dependency_failed:{dep_id}"
                    result.exit_code = 0
                    self.skipped_steps.append(step.id)
                    if self.verbose:
                        print(f"SKIP {step.id:20s} (dependency {dep_id} failed)")
                    return result

        # Check for override
        try:
            from override_manager import OverrideManager
            override_mgr = OverrideManager()
            if override_mgr.is_override_active(step.id):
                if not self.json_output and not self.json_v2:
                    print(f"SKIP {step.id:20s} (override active)")
                result.status = StepStatus.SKIP
                result.reason = "override_active"
                result.exit_code = 0
                self.skipped_steps.append(step.id)
                return result
        except ImportError:
            pass  # Override manager not available

        # Emit step start metric
        self.metrics.step_started(
            step_id=step.id,
            tier=step.tier.value,
        )

        # Run the step
        if not self.json_output and not self.json_v2:
            print(f"RUN  {step.id:20s} ... ", end="", flush=True)

        result.timestamp_start = time.time()
        try:
            # Use Popen with start_new_session=True to create a new process group.
            # This ensures we can kill all child processes on timeout, not just the shell.
            proc = subprocess.Popen(
                step.full_command(),
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,  # Create new process group for proper cleanup
            )
            try:
                stdout, stderr = proc.communicate(timeout=step.timeout)
                result.exit_code = proc.returncode
                result.stdout = stdout
                result.stderr = stderr
                if proc.returncode == 0:
                    result.status = StepStatus.PASS
                else:
                    result.status = StepStatus.FAIL
                    result.reason = "nonzero_exit"
            except subprocess.TimeoutExpired:
                # Kill the entire process group, not just the shell
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except (ProcessLookupError, OSError):
                    # Process may have already terminated
                    proc.kill()
                proc.wait()  # Clean up zombie process
                result.status = StepStatus.TIMEOUT
                result.reason = "timeout"
                result.exit_code = -1
                result.stderr = f"Command timed out after {step.timeout} seconds"
        except Exception as e:
            result.status = StepStatus.FAIL
            result.reason = "exception"
            result.exit_code = -1
            result.stderr = str(e)
        finally:
            result.timestamp_end = time.time()
            result.duration_ms = int((result.timestamp_end - result.timestamp_start) * 1000)

        # Emit step completion metric
        self.metrics.step_completed(
            step_id=step.id,
            tier=step.tier.value,
            passed=result.passed,
            duration_seconds=result.duration_ms / 1000.0,
            exit_code=result.exit_code,
            severity=step.severity.value,
        )

        # Print result
        if not self.json_output and not self.json_v2:
            if result.status == StepStatus.PASS:
                print(f"PASS ({result.duration_ms}ms)")
            elif result.status == StepStatus.TIMEOUT:
                print(f"TIMEOUT ({result.duration_ms}ms)")
            else:
                print(f"FAIL ({result.duration_ms}ms)")

        if self.verbose and result.status in (StepStatus.FAIL, StepStatus.TIMEOUT):
            if result.stdout:
                print(f"  stdout: {result.stdout[:200]}")
            if result.stderr:
                print(f"  stderr: {result.stderr[:200]}")

        return result

    def _get_git_branch(self) -> str:
        """Get current git branch name."""
        try:
            result = subprocess.run(
                "git rev-parse --abbrev-ref HEAD",
                shell=True,
                capture_output=True,
                text=True,
                timeout=5,
            )
            return result.stdout.strip() if result.returncode == 0 else "unknown"
        except Exception:
            return os.environ.get("GIT_BRANCH", "unknown")

    def _get_git_commit(self) -> str:
        """Get current git commit hash."""
        try:
            result = subprocess.run(
                "git rev-parse --short HEAD",
                shell=True,
                capture_output=True,
                text=True,
                timeout=5,
            )
            return result.stdout.strip() if result.returncode == 0 else "unknown"
        except Exception:
            return os.environ.get("CI_COMMIT_SHA", "unknown")

    def _build_summary(self) -> Dict[str, Any]:
        """Build summary dictionary with severity and category breakdowns."""
        summary = {
            "passed": sum(1 for r in self.results if r.passed),
            "failed": sum(1 for r in self.results if not r.passed and not r.skipped),
            "skipped": sum(1 for r in self.results if r.skipped),
            "mode": "degraded" if self.degraded else "kernel-only" if self.kernel_only else "strict",
            "kernel_ok": len(self.kernel_failed) == 0,
            "governance_ok": len(self.governance_failed) == 0,
            "optional_ok": len(self.optional_failed) == 0,
            "failed_steps": self.failed_steps,
            "skipped_steps": self.skipped_steps,
            "kernel_failed": self.kernel_failed,
            "governance_failed": self.governance_failed,
            "optional_failed": self.optional_failed,
            "by_severity": {},
            "by_category": {},
        }

        # Build severity breakdown
        for severity in SelfTestSeverity:
            severity_results = [r for r in self.results if r.severity == severity]
            summary["by_severity"][severity.value] = {
                "passed": sum(1 for r in severity_results if r.passed),
                "failed": sum(1 for r in severity_results if not r.passed and not r.skipped),
                "total": len(severity_results),
            }

        # Build category breakdown
        for category in SelfTestCategory:
            category_results = [r for r in self.results if r.category == category]
            summary["by_category"][category.value] = {
                "passed": sum(1 for r in category_results if r.passed),
                "failed": sum(1 for r in category_results if not r.passed and not r.skipped),
                "total": len(category_results),
            }

        return summary

    def _build_hints(self) -> List[str]:
        """
        Build actionable hints for operators based on current results.

        Returns:
            List of hint strings with specific rerun commands and guidance.
        """
        hints: List[str] = []

        # Per-step hints for any failure / timeout
        for result in self.results:
            if result.status in (StepStatus.FAIL, StepStatus.TIMEOUT):
                hints.append(
                    f"Run: uv run swarm/tools/selftest.py --step {result.step.id} --verbose"
                )

        # Mode-level hints
        if self.degraded and (self.governance_failed or self.optional_failed):
            hints.append(
                "Governance checks failed in degraded mode; see selftest_degradations.log"
            )
        elif not self.degraded and self.governance_failed:
            hints.append(
                "Try: uv run swarm/tools/selftest.py --degraded to work around governance failures"
            )

        # Kernel failure hints (always critical)
        if self.kernel_failed:
            hints.append(
                "KERNEL failure(s) block all merges; fix before proceeding"
            )

        # Documentation hint
        if hints:
            hints.append("See: docs/selftest.md for detailed troubleshooting")

        return hints

    def build_summary(self) -> Dict[str, Any]:
        """
        Build a stable summary object suitable for /platform/status and JSON reports.

        This public method provides the canonical summary shape used by:
        - /platform/status endpoint (FastAPI)
        - JSON output mode
        - Dashboard integrations

        Returns:
            Dict with mode, tier status flags, failure lists, and actionable hints.
        """
        summary = self._build_summary()
        summary["hints"] = self._build_hints()
        return summary

    def _build_full_report(self) -> Dict[str, Any]:
        """Build complete v2 format report object with metadata, summary, and results."""
        metadata = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "hostname": socket.gethostname(),
            "platform": sys.platform,
            "git_branch": self._get_git_branch(),
            "git_commit": self._get_git_commit(),
            "user": os.environ.get("USER", "unknown"),
            "mode": "degraded" if self.degraded else "kernel-only" if self.kernel_only else "strict",
        }

        # Build step results
        step_results = []
        for result in self.results:
            step_results.append({
                "step_id": result.step.id,
                "description": result.step.description,
                "tier": result.step.tier.value,
                "severity": result.severity.value,
                "category": result.category.value,
                "status": "PASS" if result.passed else "SKIP" if result.skipped else "FAIL",
                "exit_code": result.exit_code,
                "duration_ms": result.duration_ms,
                "command": result.step.full_command(),
                "timestamp_start": result.timestamp_start,
                "timestamp_end": result.timestamp_end,
            })

        # Build summary using canonical build_summary() for consistency
        # This ensures CLI JSON, report file, and /platform/status all share the same shape
        summary = self.build_summary()
        # Add additional fields that are report-specific
        summary["total"] = len(self.results)
        summary["total_duration_ms"] = int(sum(r.duration_ms for r in self.results))

        return {
            "version": "2.0",
            "metadata": metadata,
            "summary": summary,
            "results": step_results,
        }

    def run(self, steps: List[SelfTestStep]) -> int:
        """
        Run selftest steps.

        Returns:
            Exit code: 0 = all pass, 1 = failure, 2 = config error
        """
        self.print_header()

        # Record run start time
        self.run_start_time = time.time()

        # Emit run started event to observability backends
        tier = "kernel" if self.kernel_only else "degraded" if self.degraded else "strict"
        self.backends.emit_run_started(self.run_id, tier, self.run_start_time)

        # Validate step config
        errors = validate_step_list()
        if errors:
            print("ERROR: Invalid selftest configuration:", file=sys.stderr)
            for error in errors:
                print(f"  - {error}", file=sys.stderr)
            return 2

        all_results = {}
        for step in steps:
            result = self.run_step(step, all_results)
            self.results.append(result)
            all_results[step.id] = result

            # Emit step completed event to observability backends
            step_result = "PASS" if result.passed else "SKIP" if result.skipped else "FAIL"
            self.backends.emit_step_completed(
                step.id,
                result.duration_ms,
                step_result,
                step.tier.value
            )

            # Determine if we should continue
            if not result.passed and not result.skipped:
                should_block = step.tier == SelfTestTier.KERNEL

                # Emit step failed event to observability backends
                error_msg = result.stderr or result.stdout or "(no output)"
                self.backends.emit_step_failed(
                    step.id,
                    step.severity.value,
                    error_msg,
                    step.tier.value
                )

                # Track tier-aware failures for status API
                if step.tier == SelfTestTier.KERNEL:
                    self.kernel_failed.append(step.id)
                elif step.tier == SelfTestTier.GOVERNANCE:
                    self.governance_failed.append(step.id)
                elif step.tier == SelfTestTier.OPTIONAL:
                    self.optional_failed.append(step.id)

                if self.degraded and not should_block:
                    # In degraded mode, only KERNEL failures block
                    self.log_degradation(result)
                    if self.verbose:
                        print(f"  (warning: {step.id} failed, but non-blocking in degraded mode)")
                else:
                    # In strict mode, KERNEL and GOVERNANCE failures block
                    self.failed_steps.append(step.id)
                    if step.tier in (SelfTestTier.KERNEL, SelfTestTier.GOVERNANCE):
                        if not self.degraded or should_block:
                            pass  # Will be counted as failure below

        # Summarize
        self.print_footer()

        # JSON output
        if self.json_output or self.json_v2:
            if self.json_v2:
                # Build and output v2 format with severity/category breakdown
                report = self._build_full_report()
                print(json.dumps(report, indent=2))
            else:
                # Legacy format (unchanged for backward compatibility)
                report = {
                    "mode": "degraded" if self.degraded else "kernel-only" if self.kernel_only else "strict",
                    "passed": sum(1 for r in self.results if r.passed),
                    "failed": sum(1 for r in self.results if not r.passed and not r.skipped),
                    "skipped": sum(1 for r in self.results if r.skipped),
                    "total": len(self.results),
                    "total_time_ms": int(sum(r.duration_ms for r in self.results)),
                    "results": [r.to_dict() for r in self.results],
                }
                print(json.dumps(report, indent=2))

        # Write JSON report to disk if requested
        if self.write_report and self.artifact_manager:
            try:
                # Build metadata
                metadata = SelfTestReportMetadata(
                    run_id=self.artifact_manager.run_id,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    hostname=socket.gethostname(),
                    platform=sys.platform,
                    git_branch=self._get_git_branch(),
                    git_commit=self._get_git_commit(),
                    user=os.environ.get("USER", "unknown"),
                    mode="degraded" if self.degraded else "kernel-only" if self.kernel_only else "strict",
                )

                # Build step results
                step_results = []
                for result in self.results:
                    step_results.append(SelfTestStepResult(
                        step_id=result.step.id,
                        description=result.step.description,
                        tier=result.step.tier.value,
                        severity=result.severity.value,
                        category=result.category.value,
                        status="PASS" if result.passed else "SKIP" if result.skipped else "FAIL",
                        exit_code=result.exit_code,
                        duration_ms=result.duration_ms,
                        command=result.step.full_command(),
                        timestamp_start=result.timestamp_start,
                        timestamp_end=result.timestamp_end,
                        stdout=result.stdout[:500] if result.stdout else None,
                        stderr=result.stderr[:500] if result.stderr else None,
                    ))

                # Build summary
                summary_dict = self._build_summary()
                summary = SelfTestSummary(
                    passed=summary_dict["passed"],
                    failed=summary_dict["failed"],
                    skipped=summary_dict["skipped"],
                    total=len(self.results),
                    critical_passed=summary_dict["by_severity"].get("critical", {}).get("passed", 0),
                    critical_failed=summary_dict["by_severity"].get("critical", {}).get("failed", 0),
                    warning_passed=summary_dict["by_severity"].get("warning", {}).get("passed", 0),
                    warning_failed=summary_dict["by_severity"].get("warning", {}).get("failed", 0),
                    info_passed=summary_dict["by_severity"].get("info", {}).get("passed", 0),
                    info_failed=summary_dict["by_severity"].get("info", {}).get("failed", 0),
                    category_security_passed=summary_dict["by_category"].get("security", {}).get("passed", 0),
                    category_security_failed=summary_dict["by_category"].get("security", {}).get("failed", 0),
                    category_performance_passed=summary_dict["by_category"].get("performance", {}).get("passed", 0),
                    category_performance_failed=summary_dict["by_category"].get("performance", {}).get("failed", 0),
                    category_correctness_passed=summary_dict["by_category"].get("correctness", {}).get("passed", 0),
                    category_correctness_failed=summary_dict["by_category"].get("correctness", {}).get("failed", 0),
                    category_governance_passed=summary_dict["by_category"].get("governance", {}).get("passed", 0),
                    category_governance_failed=summary_dict["by_category"].get("governance", {}).get("failed", 0),
                    total_duration_ms=int(sum(r.duration_ms for r in self.results)),
                )

                # Create and write report
                report = SelfTestReport(metadata=metadata, results=step_results, summary=summary)
                report_path = self.artifact_manager.write_artifact("build", "selftest_report.json", report.to_dict())

                if not self.json_output and not self.json_v2:
                    print(f"\nReport written to: {report_path}")

            except Exception as e:
                if not self.json_output and not self.json_v2:
                    print(f"Warning: Failed to write report: {e}", file=sys.stderr)

        # Calculate run metrics
        run_duration_seconds = time.time() - self.run_start_time

        # Calculate governance pass rate
        governance_steps = [r for r in self.results if r.step.tier == SelfTestTier.GOVERNANCE]
        if governance_steps:
            governance_passed = sum(1 for r in governance_steps if r.passed)
            governance_pass_rate = (governance_passed / len(governance_steps)) * 100.0
        else:
            governance_pass_rate = 100.0

        # Determine overall status
        if len(self.kernel_failed) > 0:
            overall_status = "BROKEN"
        elif len(self.governance_failed) > 0 or len(self.optional_failed) > 0:
            overall_status = "DEGRADED"
        else:
            overall_status = "HEALTHY"

        # Emit run completion metrics
        mode = "degraded" if self.degraded else "kernel-only" if self.kernel_only else "strict"
        self.metrics.run_completed(
            mode=mode,
            duration_seconds=run_duration_seconds,
            governance_pass_rate=governance_pass_rate,
            overall_status=overall_status,
        )

        # Emit run completed event to observability backends
        run_result = "PASS" if not self.failed_steps else "FAIL"
        run_duration_ms = int(run_duration_seconds * 1000)
        summary = self._build_summary()
        self.backends.emit_run_completed(self.run_id, run_result, run_duration_ms, summary)

        # Close all backends
        self.backends.close()

        # Determine exit code
        if not self.failed_steps:
            return 0

        # In degraded mode, only KERNEL failures cause exit code 1
        if self.degraded:
            blocking_failures = [
                step_id
                for step_id in self.failed_steps
                if get_step_by_id(step_id) and get_step_by_id(step_id).tier == SelfTestTier.KERNEL
            ]
            return 1 if blocking_failures else 0

        # In strict mode, KERNEL or GOVERNANCE failures cause exit code 1
        return 1


def _run_step_in_process(step_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Run a single step in an isolated subprocess.

    This is a module-level function to work with ProcessPoolExecutor.
    Takes a serialized step dict, runs it, and returns serialized result.
    """
    step = get_step_by_id(step_data["id"])
    if step is None:
        return {
            "step_id": step_data["id"],
            "passed": False,
            "skipped": False,
            "exit_code": -1,
            "duration_ms": 0,
            "stdout": "",
            "stderr": f"Unknown step: {step_data['id']}",
            "timestamp_start": time.time(),
            "timestamp_end": time.time(),
        }

    timestamp_start = time.time()
    try:
        # Use Popen with start_new_session=True for proper timeout handling.
        # This ensures child processes are killed when timeout fires.
        proc = subprocess.Popen(
            step.full_command(),
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,  # Create new process group for proper cleanup
        )
        try:
            stdout, stderr = proc.communicate(timeout=step.timeout)
            exit_code = proc.returncode
            passed = proc.returncode == 0
        except subprocess.TimeoutExpired:
            # Kill the entire process group, not just the shell
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (ProcessLookupError, OSError):
                # Process may have already terminated
                proc.kill()
            proc.wait()  # Clean up zombie process
            exit_code = -1
            stdout = ""
            stderr = f"Command timed out after {step.timeout} seconds"
            passed = False
    except Exception as e:
        exit_code = -1
        stdout = ""
        stderr = str(e)
        passed = False

    timestamp_end = time.time()
    duration_ms = int((timestamp_end - timestamp_start) * 1000)

    return {
        "step_id": step.id,
        "passed": passed,
        "skipped": False,
        "exit_code": exit_code,
        "duration_ms": duration_ms,
        "stdout": stdout,
        "stderr": stderr,
        "timestamp_start": timestamp_start,
        "timestamp_end": timestamp_end,
        "tier": step.tier.value,
        "severity": step.severity.value,
        "category": step.category.value,
        "description": step.description,
    }


class DistributedSelfTestRunner:
    """
    Runs selftest with parallel execution using ProcessPoolExecutor.

    Executes steps in waves, where steps within a wave run in parallel.
    Wave 0 (KERNEL) always runs first and alone. Subsequent waves run
    in parallel where dependencies allow.
    """

    max_workers: int
    verbose: bool
    json_output: bool
    json_v2: bool
    wave_results: List[Dict[str, Any]]
    all_results: List[Dict[str, Any]]
    failed_steps: List[str]
    kernel_failed: List[str]
    governance_failed: List[str]
    optional_failed: List[str]
    run_id: str

    def __init__(
        self,
        max_workers: int = 4,
        verbose: bool = False,
        json_output: bool = False,
        json_v2: bool = False,
    ) -> None:
        self.max_workers = max_workers
        self.verbose = verbose
        self.json_output = json_output
        self.json_v2 = json_v2
        self.wave_results: List[Dict[str, Any]] = []
        self.all_results: List[Dict[str, Any]] = []
        self.failed_steps: List[str] = []
        self.kernel_failed: List[str] = []
        self.governance_failed: List[str] = []
        self.optional_failed: List[str] = []
        self.run_id = f"distributed-{int(time.time())}"

    def _print(self, msg: str) -> None:
        """Print if not in JSON mode."""
        if not self.json_output and not self.json_v2:
            print(msg)

    def _get_git_info(self) -> Tuple[str, str]:
        """Get current git branch and commit."""
        branch = "unknown"
        commit = "unknown"
        try:
            result = subprocess.run(
                "git rev-parse --abbrev-ref HEAD",
                shell=True, capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                branch = result.stdout.strip()

            result = subprocess.run(
                "git rev-parse --short HEAD",
                shell=True, capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                commit = result.stdout.strip()
        except Exception:
            pass
        return branch, commit

    def run_wave(self, wave_idx: int, step_ids: List[str]) -> Dict[str, Any]:
        """
        Execute a wave of steps, potentially in parallel.

        Returns:
            Dict with wave metadata and results.
        """
        wave_start = time.time()
        wave_results = []
        step_data_list = [{"id": sid} for sid in step_ids]

        if len(step_ids) == 1:
            # Single step, run directly (no pool overhead)
            self._print(f"Wave {wave_idx}: Running {step_ids[0]}...")
            result = _run_step_in_process(step_data_list[0])
            wave_results.append(result)
            status = "PASS" if result["passed"] else "FAIL"
            self._print(f"  {result['step_id']:20s} {status} ({result['duration_ms']}ms)")
        else:
            # Multiple steps, run in parallel
            self._print(f"Wave {wave_idx}: Running {len(step_ids)} steps in parallel...")
            with ProcessPoolExecutor(max_workers=self.max_workers) as executor:
                futures = {
                    executor.submit(_run_step_in_process, sd): sd
                    for sd in step_data_list
                }
                for future in as_completed(futures):
                    try:
                        result = future.result(timeout=60)
                        wave_results.append(result)
                        status = "PASS" if result["passed"] else "FAIL"
                        self._print(f"  {result['step_id']:20s} {status} ({result['duration_ms']}ms)")
                    except Exception as e:
                        step_data = futures[future]
                        error_result = {
                            "step_id": step_data["id"],
                            "passed": False,
                            "skipped": False,
                            "exit_code": -1,
                            "duration_ms": 0,
                            "stdout": "",
                            "stderr": str(e),
                            "timestamp_start": wave_start,
                            "timestamp_end": time.time(),
                        }
                        wave_results.append(error_result)
                        self._print(f"  {step_data['id']:20s} ERROR ({str(e)[:50]})")

        wave_duration_ms = int((time.time() - wave_start) * 1000)
        all_passed = all(r["passed"] for r in wave_results)

        # Track failures by tier
        for result in wave_results:
            if not result["passed"] and not result.get("skipped", False):
                self.failed_steps.append(result["step_id"])
                tier = result.get("tier", "")
                if tier == "kernel":
                    self.kernel_failed.append(result["step_id"])
                elif tier == "governance":
                    self.governance_failed.append(result["step_id"])
                elif tier == "optional":
                    self.optional_failed.append(result["step_id"])

        return {
            "wave": wave_idx,
            "steps": step_ids,
            "duration_ms": wave_duration_ms,
            "all_passed": all_passed,
            "parallel": len(step_ids) > 1,
            "results": wave_results,
        }

    def run_distributed(self) -> Dict[str, Any]:
        """
        Run selftest with wave-based parallel execution.

        Returns:
            Dict with execution results including waves and summary.
        """
        # Validate wave definitions
        wave_errors = validate_wave_definitions()
        if wave_errors:
            self._print("ERROR: Invalid wave definitions:")
            for error in wave_errors:
                self._print(f"  - {error}")
            return {"status": "ERROR", "errors": wave_errors}

        self._print("=" * 70)
        self._print("DISTRIBUTED SELFTEST RUNNER")
        self._print(f"Workers: {self.max_workers}")
        self._print("=" * 70)
        self._print("")

        total_start = time.time()

        for wave_idx, wave_steps in enumerate(EXECUTION_WAVES):
            wave_result = self.run_wave(wave_idx, wave_steps)
            self.wave_results.append(wave_result)
            self.all_results.extend(wave_result["results"])

            # If KERNEL wave fails, stop immediately
            if wave_idx == 0 and not wave_result["all_passed"]:
                self._print("")
                self._print("KERNEL failure detected - aborting run")
                break

            # For other waves, complete the wave but record failures
            self._print("")

        total_duration_ms = int((time.time() - total_start) * 1000)

        # Calculate sequential estimate (sum of all step durations)
        sequential_estimate_ms = sum(r["duration_ms"] for r in self.all_results)

        # Calculate speedup
        if total_duration_ms > 0:
            speedup = sequential_estimate_ms / total_duration_ms
            speedup_str = f"{speedup:.1f}x"
        else:
            speedup_str = "N/A"

        # Build summary
        passed = sum(1 for r in self.all_results if r["passed"])
        failed = sum(1 for r in self.all_results if not r["passed"] and not r.get("skipped", False))
        skipped = sum(1 for r in self.all_results if r.get("skipped", False))

        summary = {
            "total_steps": len(self.all_results),
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
            "sequential_estimate_ms": sequential_estimate_ms,
            "actual_duration_ms": total_duration_ms,
            "speedup": speedup_str,
            "status": "PASS" if failed == 0 else "FAIL",
            "workers": self.max_workers,
        }

        # Print summary
        self._print("=" * 70)
        self._print("DISTRIBUTED SELFTEST SUMMARY")
        self._print("=" * 70)
        self._print(f"Passed:  {passed}/{len(self.all_results)}")
        self._print(f"Failed:  {failed}/{len(self.all_results)}")
        self._print(f"Skipped: {skipped}/{len(self.all_results)}")
        self._print("")
        self._print(f"Sequential estimate: {sequential_estimate_ms}ms")
        self._print(f"Actual duration:     {total_duration_ms}ms")
        self._print(f"Speedup:             {speedup_str}")
        self._print("")

        if self.failed_steps:
            self._print("Failed steps:")
            for step_id in self.failed_steps:
                self._print(f"  - {step_id}")
            self._print("")

        # Get git info
        git_branch, git_commit = self._get_git_info()

        result = {
            "version": "2.0",
            "execution_mode": "distributed",
            "run_id": self.run_id,
            "metadata": {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "workers": self.max_workers,
                "git_branch": git_branch,
                "git_commit": git_commit,
                "hostname": socket.gethostname(),
                "platform": sys.platform,
            },
            "waves": self.wave_results,
            "summary": summary,
        }

        return result

    def run(self) -> int:
        """
        Run distributed selftest and return exit code.

        Returns:
            0 if all steps pass, 1 if any fail, 2 if config error.
        """
        result = self.run_distributed()

        if result.get("status") == "ERROR":
            return 2

        # Output JSON if requested
        if self.json_output or self.json_v2:
            print(json.dumps(result, indent=2))

        # Determine exit code
        if result["summary"]["failed"] > 0:
            # Any KERNEL failure is fatal
            if self.kernel_failed:
                return 1
            # GOVERNANCE/OPTIONAL failures also cause exit code 1 in strict mode
            return 1

        return 0


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Selftest orchestrator for composable, layered testing",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--plan",
        action="store_true",
        help="Show selftest plan without running",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="Show all available steps and exit",
    )
    parser.add_argument(
        "--step",
        type=str,
        metavar="ID",
        help="Run only the specified step",
    )
    parser.add_argument(
        "--until",
        type=str,
        metavar="ID",
        help="Run all steps up to and including the specified step",
    )
    parser.add_argument(
        "--degraded",
        action="store_true",
        help="Degraded mode: only KERNEL failures block; GOVERNANCE/OPTIONAL become warnings",
    )
    parser.add_argument(
        "--kernel-only",
        action="store_true",
        help="Run only KERNEL tier steps (fastest)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Verbose output with timing and stderr",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output machine-parseable JSON report",
    )
    parser.add_argument(
        "--json-v2",
        action="store_true",
        help="Output machine-parseable JSON with severity/category breakdown",
    )
    parser.add_argument(
        "--skip-report",
        action="store_true",
        help="Skip writing JSON report to disk",
    )
    parser.add_argument(
        "--distributed",
        action="store_true",
        help="Run steps in parallel where possible (wave-based execution)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        metavar="N",
        help="Number of parallel workers for distributed mode (default: 4)",
    )
    parser.add_argument(
        "--skip-steps",
        type=str,
        metavar="STEPS",
        help="Comma-separated list of step IDs to skip (also honors SELFTEST_SKIP_STEPS env var)",
    )

    args = parser.parse_args()

    # Merge --skip-steps with SELFTEST_SKIP_STEPS env var using shared parser
    all_skip_steps = parse_skip_steps(os.environ.get("SELFTEST_SKIP_STEPS", ""))
    if args.skip_steps:
        all_skip_steps |= parse_skip_steps(args.skip_steps)
    # Export combined skip list back to env for subprocesses
    if all_skip_steps:
        os.environ["SELFTEST_SKIP_STEPS"] = ",".join(sorted(all_skip_steps))

    # Handle list/plan modes
    if args.list:
        runner = SelfTestRunner()
        runner.show_plan(SELFTEST_STEPS)
        return 0

    # Determine which steps to run
    try:
        if args.step:
            steps = [get_step_by_id(args.step)]
            if steps[0] is None:
                print(f"ERROR: Unknown step id: {args.step}", file=sys.stderr)
                return 2
        elif args.until:
            steps = get_steps_in_order(until_id=args.until)
        elif args.kernel_only:
            steps = get_steps_in_order(filter_tier=SelfTestTier.KERNEL)
        else:
            steps = get_steps_in_order()
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    # Handle plan mode
    if args.plan:
        runner = SelfTestRunner(json_output=args.json, write_report=False)
        runner.show_plan(steps)
        return 0

    # Handle distributed mode
    if args.distributed:
        # Distributed mode runs all steps using wave-based parallelization
        # It does not support --step, --until, or --degraded flags
        if args.step or args.until or args.degraded or args.kernel_only:
            print("ERROR: --distributed cannot be combined with --step, --until, --degraded, or --kernel-only", file=sys.stderr)
            return 2

        runner = DistributedSelfTestRunner(
            max_workers=args.workers,
            verbose=args.verbose,
            json_output=args.json,
            json_v2=args.json_v2,
        )
        return runner.run()

    # Run sequential selftest
    runner = SelfTestRunner(
        degraded=args.degraded,
        kernel_only=args.kernel_only,
        verbose=args.verbose,
        json_output=args.json,
        json_v2=args.json_v2,
        write_report=not args.skip_report,
        skip_steps=all_skip_steps,
    )
    return runner.run(steps)


if __name__ == "__main__":
    sys.exit(main())
