"""
preflight.py - Unified preflight orchestrator for environment validation.

Runs all environment checks before expensive stepwise work, providing early
failure detection and clear diagnostics. Integrates existing validation tools:
- selftest_doctor.py: Harness health diagnostics
- provider_env_check.py: Provider credential validation
- path_helpers.py: RUN_BASE directory validation

Usage:
    from swarm.runtime.preflight import (
        PreflightOrchestrator,
        run_preflight,
        PreflightResult,
    )

    # Quick check with defaults
    result = run_preflight(run_spec, backend="claude-step-orchestrator")
    if not result.passed:
        print("Preflight failed:", result.blocking_issues)

    # Full orchestrator access
    orchestrator = PreflightOrchestrator(repo_root=Path("/path/to/repo"))
    result = orchestrator.run_all_checks(run_spec, backend="gemini-step-orchestrator")
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class CheckStatus(str, Enum):
    """Status of an individual preflight check."""

    PASSED = "passed"
    WARNING = "warning"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class CheckResult:
    """Result of a single preflight check.

    Attributes:
        name: Human-readable check name.
        status: Check status (passed, warning, failed, skipped).
        message: Detailed message about the check result.
        duration_ms: Time taken to run the check in milliseconds.
        details: Additional structured details about the check.
        fix_hint: Suggested fix if the check failed.
    """

    name: str
    status: CheckStatus
    message: str
    duration_ms: int = 0
    details: Dict[str, Any] = field(default_factory=dict)
    fix_hint: Optional[str] = None


@dataclass
class PreflightResult:
    """Aggregate result of all preflight checks.

    Attributes:
        passed: True if all required checks passed (no blocking issues).
        checks: List of individual check results.
        blocking_issues: List of issues that prevent execution.
        warnings: List of non-blocking warnings.
        total_duration_ms: Total time for all checks.
        timestamp: When the preflight was run.
        run_id: Run ID if available.
        backend: Backend that was checked.
    """

    passed: bool
    checks: List[CheckResult] = field(default_factory=list)
    blocking_issues: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    total_duration_ms: int = 0
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    run_id: Optional[str] = None
    backend: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "passed": self.passed,
            "checks": [
                {
                    "name": c.name,
                    "status": c.status.value,
                    "message": c.message,
                    "duration_ms": c.duration_ms,
                    "details": c.details,
                    "fix_hint": c.fix_hint,
                }
                for c in self.checks
            ],
            "blocking_issues": self.blocking_issues,
            "warnings": self.warnings,
            "total_duration_ms": self.total_duration_ms,
            "timestamp": self.timestamp.isoformat(),
            "run_id": self.run_id,
            "backend": self.backend,
        }


class PreflightOrchestrator:
    """Unified preflight orchestrator for environment validation.

    Runs all environment checks before expensive work:
    1. check_harness_health() - Python/Rust/Git state
    2. check_credentials() - Provider API keys/tokens
    3. check_repo_health() - Git state, clean tree, writable workspace
    4. check_paths() - RUN_BASE directories exist and writable
    5. check_backend_availability() - SDK/CLI available for selected backend

    Attributes:
        repo_root: Repository root path.
        skip_checks: Set of check names to skip.
    """

    def __init__(
        self,
        repo_root: Optional[Path] = None,
        skip_checks: Optional[List[str]] = None,
    ):
        """Initialize the preflight orchestrator.

        Args:
            repo_root: Repository root path. Defaults to auto-detection.
            skip_checks: List of check names to skip (e.g., ["credentials"]).
        """
        self._repo_root = repo_root or Path(__file__).resolve().parents[2]
        self._skip_checks = set(skip_checks or [])

    def _time_check(self, check_fn: Callable[[], CheckResult]) -> CheckResult:
        """Run a check function and measure duration.

        Args:
            check_fn: Function that returns a CheckResult.

        Returns:
            CheckResult with duration_ms populated.
        """
        import time

        start = time.perf_counter()
        try:
            result = check_fn()
        except Exception as e:
            result = CheckResult(
                name=check_fn.__name__ if hasattr(check_fn, "__name__") else "unknown",
                status=CheckStatus.FAILED,
                message=f"Check raised exception: {e}",
            )
        end = time.perf_counter()
        result.duration_ms = int((end - start) * 1000)
        return result

    def check_harness_health(self) -> CheckResult:
        """Check harness health using SelfTestDoctor diagnostics.

        Validates:
        - Python environment (version, virtualenv)
        - Rust toolchain (if Cargo.toml exists)
        - Git state (in repo, git available)

        Returns:
            CheckResult with harness health status.
        """
        try:
            from swarm.tools.selftest_doctor import SelfTestDoctor

            doctor = SelfTestDoctor()
            results = doctor.diagnose()

            harness = results.get("harness", {})
            summary = results.get("summary", "UNKNOWN")
            recommendations = results.get("recommendations", [])

            # Map summary to status
            if summary == "HEALTHY":
                status = CheckStatus.PASSED
                message = "Harness is healthy"
            elif summary == "SERVICE_ISSUE":
                # Service issues are warnings, not blocking
                status = CheckStatus.WARNING
                message = "Service has issues but harness is OK"
            else:
                # HARNESS_ISSUE
                status = CheckStatus.FAILED
                message = f"Harness issue detected: {', '.join(recommendations[:2])}"

            return CheckResult(
                name="harness_health",
                status=status,
                message=message,
                details={
                    "harness": harness,
                    "summary": summary,
                    "recommendations": recommendations,
                },
                fix_hint=recommendations[0] if recommendations else None,
            )

        except ImportError:
            return CheckResult(
                name="harness_health",
                status=CheckStatus.WARNING,
                message="SelfTestDoctor not available, skipping harness check",
                details={"error": "import_error"},
            )
        except Exception as e:
            return CheckResult(
                name="harness_health",
                status=CheckStatus.WARNING,
                message=f"Harness check failed: {e}",
                details={"error": str(e)},
            )

    def check_credentials(
        self,
        backend: Optional[str] = None,
        required_providers: Optional[List[str]] = None,
    ) -> CheckResult:
        """Check credentials using provider_env_check infrastructure.

        Validates that required API keys/tokens are present for the
        specified backend or providers.

        Args:
            backend: Optional backend ID to check. If provided, only checks
                credentials required for that specific backend.
            required_providers: List of provider IDs to check.
                If None and no backend specified, checks all configured non-stub engines.

        Returns:
            CheckResult with credential status.
        """
        try:
            from swarm.config.runtime_config import (
                get_available_engines,
                get_engine_env,
                get_engine_mode,
                get_engine_required_env_keys,
            )

            missing_keys: List[str] = []
            checked_engines: Dict[str, str] = {}

            # Map backends to their engine IDs
            backend_to_engine = {
                "claude-harness": "claude",
                "claude-agent-sdk": "claude",
                "claude-step-orchestrator": "claude",
                "gemini-cli": "gemini",
                "gemini-step-orchestrator": "gemini",
            }

            # Determine which engines to check
            if backend:
                # Only check the engine for the specified backend
                engine_id = backend_to_engine.get(backend)
                if engine_id:
                    engines_to_check = [engine_id]
                else:
                    # Unknown backend - check all engines
                    engines_to_check = get_available_engines()
            else:
                # Check all configured engines
                engines_to_check = get_available_engines()

            for engine_id in engines_to_check:
                mode = get_engine_mode(engine_id)

                # Skip stub engines - they don't need credentials
                if mode == "stub":
                    checked_engines[engine_id] = "stub"
                    continue

                # Get required env keys for this engine
                required_keys = get_engine_required_env_keys(engine_id)
                engine_env = get_engine_env(engine_id)

                engine_missing = []
                for key in required_keys:
                    # Check system environment first
                    if os.environ.get(key):
                        continue
                    # Check engine-specific env config
                    if key in engine_env and engine_env[key]:
                        continue
                    # Key is missing
                    engine_missing.append(key)
                    missing_keys.append(f"{engine_id}:{key}")

                if engine_missing:
                    checked_engines[engine_id] = "missing"
                else:
                    checked_engines[engine_id] = "ok"

            if missing_keys:
                return CheckResult(
                    name="credentials",
                    status=CheckStatus.FAILED,
                    message=f"Missing credentials: {', '.join(missing_keys)}",
                    details={
                        "missing_keys": missing_keys,
                        "checked_engines": checked_engines,
                        "backend": backend,
                    },
                    fix_hint=f"Set environment variables: {', '.join(set(k.split(':')[1] for k in missing_keys))}",
                )

            return CheckResult(
                name="credentials",
                status=CheckStatus.PASSED,
                message="All required credentials are present",
                details={"checked_engines": checked_engines, "backend": backend},
            )

        except ImportError as e:
            return CheckResult(
                name="credentials",
                status=CheckStatus.WARNING,
                message=f"Credential check not available: {e}",
                details={"error": "import_error"},
            )
        except Exception as e:
            return CheckResult(
                name="credentials",
                status=CheckStatus.WARNING,
                message=f"Credential check failed: {e}",
                details={"error": str(e)},
            )

    def check_repo_health(self) -> CheckResult:
        """Check repository health.

        Validates:
        - Git is available and we're in a git repository
        - Working tree status (clean/dirty)
        - Workspace is writable

        Returns:
            CheckResult with repo health status.
        """
        details: Dict[str, Any] = {}
        warnings: List[str] = []

        # Check git is available
        try:
            result = subprocess.run(
                ["git", "--version"],
                capture_output=True,
                timeout=5,
                cwd=str(self._repo_root),
            )
            if result.returncode != 0:
                return CheckResult(
                    name="repo_health",
                    status=CheckStatus.FAILED,
                    message="Git is not available",
                    fix_hint="Install git",
                )
            details["git_version"] = result.stdout.decode().strip()
        except FileNotFoundError:
            return CheckResult(
                name="repo_health",
                status=CheckStatus.FAILED,
                message="Git is not installed",
                fix_hint="Install git: https://git-scm.com/downloads",
            )
        except Exception as e:
            return CheckResult(
                name="repo_health",
                status=CheckStatus.FAILED,
                message=f"Git check failed: {e}",
            )

        # Check we're in a git repository
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--is-inside-work-tree"],
                capture_output=True,
                timeout=5,
                cwd=str(self._repo_root),
            )
            if result.returncode != 0:
                return CheckResult(
                    name="repo_health",
                    status=CheckStatus.FAILED,
                    message="Not inside a git repository",
                    fix_hint="Run from inside the repository root",
                )
            details["is_git_repo"] = True
        except Exception as e:
            return CheckResult(
                name="repo_health",
                status=CheckStatus.FAILED,
                message=f"Git repo check failed: {e}",
            )

        # Check for uncommitted changes (warning, not blocking)
        try:
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                capture_output=True,
                timeout=5,
                cwd=str(self._repo_root),
            )
            if result.returncode == 0:
                output = result.stdout.decode().strip()
                if output:
                    details["has_uncommitted_changes"] = True
                    details["uncommitted_count"] = len(output.split("\n"))
                    warnings.append("Repository has uncommitted changes")
                else:
                    details["has_uncommitted_changes"] = False
        except Exception:
            pass  # Non-fatal

        # Check workspace is writable
        test_file = self._repo_root / ".preflight_test"
        try:
            test_file.write_text("test")
            test_file.unlink()
            details["workspace_writable"] = True
        except Exception as e:
            return CheckResult(
                name="repo_health",
                status=CheckStatus.FAILED,
                message=f"Workspace is not writable: {e}",
                fix_hint="Check file permissions on the repository",
            )

        status = CheckStatus.WARNING if warnings else CheckStatus.PASSED
        message = warnings[0] if warnings else "Repository is healthy"

        return CheckResult(
            name="repo_health",
            status=status,
            message=message,
            details=details,
        )

    def check_paths(self, run_id: Optional[str] = None) -> CheckResult:
        """Check RUN_BASE paths exist and are writable.

        Validates:
        - swarm/runs/ directory exists (or can be created)
        - If run_id provided, checks that run directory is accessible

        Args:
            run_id: Optional run ID to check specific run directory.

        Returns:
            CheckResult with path status.
        """
        runs_dir = self._repo_root / "swarm" / "runs"
        details: Dict[str, Any] = {"runs_dir": str(runs_dir)}

        # Check swarm/runs/ exists or can be created
        try:
            if not runs_dir.exists():
                runs_dir.mkdir(parents=True, exist_ok=True)
                details["created_runs_dir"] = True
            else:
                details["created_runs_dir"] = False

            # Check it's writable
            test_file = runs_dir / ".preflight_test"
            test_file.write_text("test")
            test_file.unlink()
            details["runs_dir_writable"] = True
        except Exception as e:
            return CheckResult(
                name="paths",
                status=CheckStatus.FAILED,
                message=f"Cannot write to swarm/runs/: {e}",
                details=details,
                fix_hint="Check permissions on swarm/runs/ directory",
            )

        # If run_id provided, check specific run directory
        if run_id:
            run_dir = runs_dir / run_id
            details["run_dir"] = str(run_dir)
            try:
                run_dir.mkdir(parents=True, exist_ok=True)
                test_file = run_dir / ".preflight_test"
                test_file.write_text("test")
                test_file.unlink()
                details["run_dir_writable"] = True
            except Exception as e:
                return CheckResult(
                    name="paths",
                    status=CheckStatus.FAILED,
                    message=f"Cannot write to run directory: {e}",
                    details=details,
                    fix_hint="Check permissions on run directory",
                )

        return CheckResult(
            name="paths",
            status=CheckStatus.PASSED,
            message="RUN_BASE paths are accessible and writable",
            details=details,
        )

    def check_backend_availability(self, backend: str) -> CheckResult:
        """Check if the selected backend is available.

        Validates:
        - For SDK backends: SDK package is importable
        - For CLI backends: CLI executable is in PATH

        Args:
            backend: Backend ID (e.g., "claude-step-orchestrator", "gemini-cli").

        Returns:
            CheckResult with backend availability status.
        """
        details: Dict[str, Any] = {"backend": backend}

        # Map backends to their requirements
        backend_requirements = {
            "claude-harness": {"type": "cli", "cli": "claude", "package": None},
            "claude-agent-sdk": {"type": "sdk", "cli": None, "package": "anthropic"},
            "claude-step-orchestrator": {"type": "sdk", "cli": None, "package": "anthropic"},
            "gemini-cli": {"type": "cli", "cli": "gemini", "package": None},
            "gemini-step-orchestrator": {"type": "cli", "cli": "gemini", "package": None},
        }

        requirements = backend_requirements.get(backend)
        if requirements is None:
            # Unknown backend - assume it's available
            return CheckResult(
                name="backend_availability",
                status=CheckStatus.WARNING,
                message=f"Unknown backend '{backend}', assuming available",
                details=details,
            )

        details["requirements"] = requirements

        # Check SDK availability
        if requirements["package"]:
            try:
                __import__(requirements["package"])
                details["package_available"] = True
            except ImportError:
                return CheckResult(
                    name="backend_availability",
                    status=CheckStatus.FAILED,
                    message=f"Required package '{requirements['package']}' is not installed",
                    details=details,
                    fix_hint=f"pip install {requirements['package']}",
                )

        # Check CLI availability
        if requirements["cli"]:
            cli_path = shutil.which(requirements["cli"])
            if cli_path:
                details["cli_path"] = cli_path
                details["cli_available"] = True
            else:
                # Check if we're in stub mode - CLI not required
                try:
                    from swarm.config.runtime_config import is_stub_mode

                    engine = requirements["cli"]
                    if is_stub_mode(engine):
                        details["cli_available"] = False
                        details["stub_mode"] = True
                        return CheckResult(
                            name="backend_availability",
                            status=CheckStatus.PASSED,
                            message=f"Backend '{backend}' running in stub mode (CLI not required)",
                            details=details,
                        )
                except ImportError:
                    pass

                return CheckResult(
                    name="backend_availability",
                    status=CheckStatus.FAILED,
                    message=f"CLI '{requirements['cli']}' not found in PATH",
                    details=details,
                    fix_hint=f"Install {requirements['cli']} CLI or set SWARM_{requirements['cli'].upper()}_CLI",
                )

        return CheckResult(
            name="backend_availability",
            status=CheckStatus.PASSED,
            message=f"Backend '{backend}' is available",
            details=details,
        )

    def run_all_checks(
        self,
        run_spec: Optional[Any] = None,
        backend: Optional[str] = None,
        run_id: Optional[str] = None,
    ) -> PreflightResult:
        """Run all preflight checks.

        Args:
            run_spec: Optional RunSpec for context.
            backend: Backend to check. Defaults to spec.backend or "claude-harness".
            run_id: Optional run ID for path checks.

        Returns:
            PreflightResult with aggregate status.
        """
        import time

        start_time = time.perf_counter()

        # Determine backend
        if backend is None:
            if run_spec and hasattr(run_spec, "backend"):
                backend = run_spec.backend
            else:
                backend = "claude-harness"

        checks: List[CheckResult] = []
        blocking_issues: List[str] = []
        warnings: List[str] = []

        # Run checks in sequence
        # Note: Using default args to capture variables in lambdas correctly
        check_functions: List[Tuple[str, Callable[[], CheckResult]]] = [
            ("harness", lambda: self.check_harness_health()),
            ("credentials", lambda b=backend: self.check_credentials(backend=b)),
            ("repo", lambda: self.check_repo_health()),
            ("paths", lambda r=run_id: self.check_paths(r)),
            ("backend", lambda b=backend: self.check_backend_availability(b)),
        ]

        for check_name, check_fn in check_functions:
            if check_name in self._skip_checks:
                checks.append(
                    CheckResult(
                        name=check_name,
                        status=CheckStatus.SKIPPED,
                        message="Skipped by configuration",
                    )
                )
                continue

            result = self._time_check(check_fn)
            checks.append(result)

            if result.status == CheckStatus.FAILED:
                blocking_issues.append(f"{result.name}: {result.message}")
            elif result.status == CheckStatus.WARNING:
                warnings.append(f"{result.name}: {result.message}")

        end_time = time.perf_counter()
        total_duration_ms = int((end_time - start_time) * 1000)

        passed = len(blocking_issues) == 0

        return PreflightResult(
            passed=passed,
            checks=checks,
            blocking_issues=blocking_issues,
            warnings=warnings,
            total_duration_ms=total_duration_ms,
            run_id=run_id,
            backend=backend,
        )


def run_preflight(
    run_spec: Optional[Any] = None,
    backend: Optional[str] = None,
    run_id: Optional[str] = None,
    repo_root: Optional[Path] = None,
    skip_preflight: bool = False,
    skip_checks: Optional[List[str]] = None,
) -> PreflightResult:
    """Convenience entry point for running preflight checks.

    Args:
        run_spec: Optional RunSpec for context.
        backend: Backend to check. Defaults to spec.backend or "claude-harness".
        run_id: Optional run ID for path checks.
        repo_root: Optional repository root path.
        skip_preflight: If True, skip all checks and return a passing result.
        skip_checks: List of specific check names to skip.

    Returns:
        PreflightResult with aggregate status.

    Example:
        # Quick check
        result = run_preflight(spec, backend="claude-step-orchestrator")
        if not result.passed:
            print("Preflight failed:", result.blocking_issues)
            sys.exit(1)

        # Skip preflight in CI
        result = run_preflight(spec, skip_preflight=True)
    """
    if skip_preflight:
        return PreflightResult(
            passed=True,
            checks=[
                CheckResult(
                    name="preflight",
                    status=CheckStatus.SKIPPED,
                    message="Preflight skipped by --skip-preflight flag",
                )
            ],
            warnings=["Preflight was skipped"],
            run_id=run_id,
            backend=backend,
        )

    orchestrator = PreflightOrchestrator(repo_root=repo_root, skip_checks=skip_checks)
    return orchestrator.run_all_checks(run_spec, backend, run_id)


def inject_env_doctor_sidequest(
    run_state: Any,
    preflight_result: PreflightResult,
) -> bool:
    """Inject an env-doctor sidequest to try to fix preflight issues.

    This is called when preflight fails and we want to attempt automatic
    remediation before giving up.

    Args:
        run_state: The RunState to inject the sidequest into.
        preflight_result: The failed preflight result.

    Returns:
        True if a sidequest was injected, False otherwise.
    """
    # Only inject if we have blocking issues that might be fixable
    if not preflight_result.blocking_issues:
        return False

    # Check if env-doctor sidequest exists in catalog
    try:
        from swarm.runtime.sidequest_catalog import get_sidequest

        sidequest = get_sidequest("env-doctor")
        if sidequest is None:
            logger.debug("env-doctor sidequest not found in catalog")
            return False
    except ImportError:
        logger.debug("sidequest_catalog not available")
        return False

    # Inject the sidequest
    try:
        from swarm.runtime.types import InjectedNodeSpec

        node_spec = InjectedNodeSpec(
            node_id="sq-env-doctor-0",
            station_id="env-doctor",
            role="Diagnose and fix environment issues",
            params={
                "blocking_issues": preflight_result.blocking_issues,
                "warnings": preflight_result.warnings,
                "checks": [
                    c.to_dict()
                    if hasattr(c, "to_dict")
                    else {"name": c.name, "status": c.status.value, "message": c.message}
                    for c in preflight_result.checks
                ],
            },
            sidequest_origin="preflight",
        )

        run_state.register_injected_node(node_spec)
        logger.info("Injected env-doctor sidequest to fix preflight issues")
        return True

    except Exception as e:
        logger.warning("Failed to inject env-doctor sidequest: %s", e)
        return False


__all__ = [
    "CheckStatus",
    "CheckResult",
    "PreflightResult",
    "PreflightOrchestrator",
    "run_preflight",
    "inject_env_doctor_sidequest",
]
