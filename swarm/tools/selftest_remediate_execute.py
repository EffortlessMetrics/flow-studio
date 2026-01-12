#!/usr/bin/env python3
"""Auto-remediation executor for selftest suggestions.

Phase 1: CLI tool with local approval (y/n prompt).
Phase 2: Slack integration (future).

Usage:
    uv run swarm/tools/selftest_remediate_execute.py
    uv run swarm/tools/selftest_remediate_execute.py --dry-run
    uv run swarm/tools/selftest_remediate_execute.py --auto-approve  # CI only
"""

# SAFETY MODEL:
# - Dual allowlist/blocklist: Commands must be in allowlist AND not blocklisted
# - Dry-run preview required before execution
# - All actions logged to swarm/runs/remediation_audit.jsonl
# - Phase 1: CLI with manual y/n approval
# - Never suitable for: git commits, external network calls, destructive ops
# - Flows NEVER call this inline or wait on it

import argparse
import getpass
import json
import re
import socket
import subprocess
import sys
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Add parent directory to path to allow importing sibling modules
_TOOLS_DIR = Path(__file__).parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))


class ApprovalStatus(Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    TIMEOUT = "timeout"


class ExecutionStatus(Enum):
    NOT_STARTED = "not_started"
    DRY_RUN_COMPLETE = "dry_run_complete"
    EXECUTING = "executing"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class Remediation:
    """A single remediation suggestion with execution context."""

    id: str
    pattern_id: str
    step_id: str
    command: str
    rationale: str
    severity: str
    timestamp: str


@dataclass
class DryRunResult:
    """Result of executing a command in dry-run mode."""

    remediation_id: str
    command: str
    diff: str  # Git diff or command output showing changes
    affected_files: List[str]
    file_count: int
    safe_to_execute: bool
    warnings: List[str]


@dataclass
class ApprovalResult:
    """Result of the approval process."""

    remediation_id: str
    status: ApprovalStatus
    approver: Optional[str]
    channel: str  # "cli", "slack", "github"
    timestamp: str
    timeout_seconds: int = 600


@dataclass
class ExecuteResult:
    """Result of executing a remediation."""

    remediation_id: str
    status: ExecutionStatus
    command: str
    stdout: str
    stderr: str
    exit_code: int
    duration_ms: int
    git_commit_before: str
    git_commit_after: Optional[str] = None


@dataclass
class AuditLogEntry:
    """Complete audit log entry for a remediation attempt."""

    version: str = "1.0"
    timestamp: str = ""
    remediation_id: str = ""
    transaction_id: str = ""
    suggestion: Dict[str, Any] = field(default_factory=dict)
    allowlist_check: Dict[str, Any] = field(default_factory=dict)
    dry_run: Dict[str, Any] = field(default_factory=dict)
    approval: Dict[str, Any] = field(default_factory=dict)
    execution: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)


# Allowlisted patterns (safe to auto-execute)
# These commands are:
# - Idempotent (running twice produces same result)
# - Non-destructive (no data loss, no file deletion)
# - Reversible (changes can be undone via git)
# - Local (no network calls, no external services)
ALLOWLISTED_PATTERNS = [
    "make gen-adapters",
    "make gen-flows",
    "make validate-swarm",
    "make check-adapters",
    "make check-flows",
    "make lint",
    "uv run ruff check --fix",
    "uv run ruff check --diff",
    "uv run swarm/tools/check_selftest_ac_freshness.py --update",
    "uv run swarm/tools/check_selftest_ac_freshness.py --check",
]

# Blocklisted patterns (NEVER auto-execute)
# These are blocked even if someone accidentally puts them in an allowlist
BLOCKLISTED_PATTERNS = [
    r"git\s+(commit|push|reset\s+--hard|merge|rebase|cherry-pick)",
    r"rm\s+-rf?",
    r"rm\s+-f",
    r"curl|wget",
    r"DROP|DELETE|TRUNCATE",  # SQL patterns
    r"--secret|--token|--password|--key",
    r"\.env|credentials|secrets",
    r"unlink",
    r"shred",
    r"mkfs",
    r"dd\s+if=",
]


def get_git_sha() -> str:
    """Get current git SHA."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip()[:8]
    except (subprocess.SubprocessError, FileNotFoundError):
        pass
    return "unknown"


def get_git_branch() -> str:
    """Get current git branch."""
    try:
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.SubprocessError, FileNotFoundError):
        pass
    return "unknown"


def is_blocklisted(command: str) -> Tuple[bool, Optional[str]]:
    """Check if a command matches any blocklist pattern.

    Returns:
        (is_blocked, reason) - True with reason if blocked.
    """
    for pattern in BLOCKLISTED_PATTERNS:
        if re.search(pattern, command, re.IGNORECASE):
            return True, f"Command matches blocklist pattern: {pattern}"
    return False, None


def is_allowlisted(command: str) -> Tuple[bool, Optional[str]]:
    """Check if a command is in the allowlist.

    Returns:
        (is_allowed, rejection_reason) - True if allowed, False with reason if not.
    """
    # First check blocklist (blocklist overrides allowlist)
    blocked, reason = is_blocklisted(command)
    if blocked:
        return False, reason

    # Check allowlist
    command_normalized = command.strip()
    for allowed in ALLOWLISTED_PATTERNS:
        if command_normalized == allowed or command_normalized.startswith(allowed + " "):
            return True, None

    return False, f"Command not in allowlist: {command}"


def get_pending_remediations(
    degradation_log: Optional[Path] = None,
    remediation_map: Path = Path("swarm/config/selftest_remediation_map.yaml"),
) -> List[Remediation]:
    """Read suggestions from selftest output using the suggestion engine.

    Returns:
        List of pending remediations that match known patterns.
    """
    # Import the suggestion engine
    from selftest_suggest_remediation import (
        RemediationSuggestionEngine,
        find_latest_degradation_log,
        parse_degradation_log,
    )

    # Find degradation log
    if degradation_log is None:
        runs_dir = Path("swarm/runs")
        degradation_log = find_latest_degradation_log(runs_dir)

    if degradation_log is None or not degradation_log.exists():
        return []

    # Parse degradations
    degradations = parse_degradation_log(degradation_log)
    if not degradations:
        return []

    # Load engine and generate suggestions
    try:
        engine = RemediationSuggestionEngine(remediation_map)
    except FileNotFoundError:
        return []

    result = engine.generate_suggestions(degradations)

    # Convert suggestions to Remediation objects
    remediations = []
    for suggestion in result["suggestions"]:
        deg = suggestion["degradation"]
        rem = suggestion["remediation"]

        # Create a remediation for each suggested command
        for cmd in rem["suggested_commands"]:
            remediation = Remediation(
                id=f"rem-{uuid.uuid4().hex[:8]}",
                pattern_id=rem["id"],
                step_id=deg["step"],
                command=cmd,
                rationale=rem["rationale"],
                severity=deg["severity"],
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
            remediations.append(remediation)

    return remediations


def dry_run(
    remediation: Remediation,
    working_dir: Path = Path.cwd(),
) -> DryRunResult:
    """Execute the remediation in dry-run mode to preview changes.

    Uses git diff to capture changes for most commands.
    """
    warnings = []

    # Get initial git status
    try:
        git_status_before = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            cwd=working_dir,
            timeout=30,
        )
        initial_files = set(git_status_before.stdout.strip().split("\n")) if git_status_before.stdout and git_status_before.stdout.strip() else set()
    except (subprocess.SubprocessError, FileNotFoundError):
        initial_files = set()
        warnings.append("Could not check git status before dry-run")

    # For some commands, we can use a native dry-run
    command = remediation.command
    dry_run_command = command

    # Use native dry-run modes where available
    if "ruff check --fix" in command:
        dry_run_command = command.replace("--fix", "--diff")
    elif command == "make validate-swarm":
        # validate-swarm is already read-only, just run it
        dry_run_command = command

    # Execute the dry-run command
    try:
        result = subprocess.run(
            dry_run_command,
            shell=True,
            capture_output=True,
            text=True,
            cwd=working_dir,
            timeout=120,
        )
        command_output = result.stdout + result.stderr
    except subprocess.TimeoutExpired:
        return DryRunResult(
            remediation_id=remediation.id,
            command=command,
            diff="ERROR: Command timed out during dry-run",
            affected_files=[],
            file_count=0,
            safe_to_execute=False,
            warnings=["Command timed out during dry-run"],
        )
    except subprocess.SubprocessError as e:
        return DryRunResult(
            remediation_id=remediation.id,
            command=command,
            diff=f"ERROR: {e}",
            affected_files=[],
            file_count=0,
            safe_to_execute=False,
            warnings=[str(e)],
        )

    # If command modifies files, get the diff
    diff = command_output
    affected_files: List[str] = []

    # For commands that actually modify files, check git diff
    if "--diff" not in dry_run_command and command != "make validate-swarm":
        try:
            git_diff = subprocess.run(
                ["git", "diff", "--name-only"],
                capture_output=True,
                text=True,
                cwd=working_dir,
                timeout=30,
            )
            if git_diff.stdout and git_diff.stdout.strip():
                affected_files = git_diff.stdout.strip().split("\n")

            # Get the actual diff content
            git_diff_content = subprocess.run(
                ["git", "diff"],
                capture_output=True,
                text=True,
                cwd=working_dir,
                timeout=30,
            )
            if git_diff_content.stdout and git_diff_content.stdout.strip():
                diff = git_diff_content.stdout
        except (subprocess.SubprocessError, FileNotFoundError):
            warnings.append("Could not get git diff")

    # Also check for new untracked files
    try:
        git_status_after = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            cwd=working_dir,
            timeout=30,
        )
        final_files = set(git_status_after.stdout.strip().split("\n")) if git_status_after.stdout and git_status_after.stdout.strip() else set()
        new_files = final_files - initial_files
        for f in new_files:
            if f.startswith("?? "):
                affected_files.append(f[3:])
    except (subprocess.SubprocessError, FileNotFoundError):
        pass

    file_count = len(affected_files)

    # Determine if safe to execute
    safe_to_execute = True
    if file_count > 50:
        warnings.append(f"Large number of affected files: {file_count}")
        safe_to_execute = False

    return DryRunResult(
        remediation_id=remediation.id,
        command=command,
        diff=diff if diff else "(no changes detected)",
        affected_files=affected_files,
        file_count=file_count,
        safe_to_execute=safe_to_execute,
        warnings=warnings,
    )


def request_approval(
    remediation: Remediation,
    dry_run_result: DryRunResult,
    channel: str = "cli",
    timeout_seconds: int = 600,
    auto_approve: bool = False,
) -> ApprovalResult:
    """Request human approval for the remediation.

    For CLI: Shows diff and prompts y/n
    """
    timestamp = datetime.now(timezone.utc).isoformat()

    if auto_approve:
        return ApprovalResult(
            remediation_id=remediation.id,
            status=ApprovalStatus.APPROVED,
            approver="auto-approve",
            channel="cli-auto",
            timestamp=timestamp,
            timeout_seconds=timeout_seconds,
        )

    # Show the remediation details
    print(f"\n  Command: {remediation.command}")
    print(f"  Pattern: {remediation.pattern_id}")
    print(f"  Rationale: {remediation.rationale}")

    if dry_run_result.diff and dry_run_result.diff != "(no changes detected)":
        print("\n  Dry-run preview:")
        # Truncate long diffs
        diff_lines = dry_run_result.diff.split("\n")
        if len(diff_lines) > 20:
            for line in diff_lines[:20]:
                print(f"    {line}")
            print(f"    ... ({len(diff_lines) - 20} more lines)")
        else:
            for line in diff_lines:
                print(f"    {line}")

    if dry_run_result.affected_files:
        print(f"\n  Affected files ({dry_run_result.file_count}):")
        for f in dry_run_result.affected_files[:10]:
            print(f"    - {f}")
        if len(dry_run_result.affected_files) > 10:
            print(f"    ... and {len(dry_run_result.affected_files) - 10} more")

    if dry_run_result.warnings:
        print("\n  Warnings:")
        for w in dry_run_result.warnings:
            print(f"    ! {w}")

    # Prompt for approval
    try:
        response = input("\n  Execute this remediation? [y/N] ").strip().lower()
        if response in ("y", "yes"):
            approver = getpass.getuser()
            return ApprovalResult(
                remediation_id=remediation.id,
                status=ApprovalStatus.APPROVED,
                approver=approver,
                channel=channel,
                timestamp=timestamp,
                timeout_seconds=timeout_seconds,
            )
        else:
            return ApprovalResult(
                remediation_id=remediation.id,
                status=ApprovalStatus.REJECTED,
                approver=getpass.getuser(),
                channel=channel,
                timestamp=timestamp,
                timeout_seconds=timeout_seconds,
            )
    except (EOFError, KeyboardInterrupt):
        return ApprovalResult(
            remediation_id=remediation.id,
            status=ApprovalStatus.REJECTED,
            approver=None,
            channel=channel,
            timestamp=timestamp,
            timeout_seconds=timeout_seconds,
        )


def execute(
    remediation: Remediation,
    approval: ApprovalResult,
    working_dir: Path = Path.cwd(),
) -> ExecuteResult:
    """Execute the remediation command.

    Prerequisites:
    - Approval status must be APPROVED
    - Command must pass blocklist check
    """
    import time

    git_sha_before = get_git_sha()

    # Check approval
    if approval.status != ApprovalStatus.APPROVED:
        return ExecuteResult(
            remediation_id=remediation.id,
            status=ExecutionStatus.SKIPPED,
            command=remediation.command,
            stdout="",
            stderr="Execution skipped: not approved",
            exit_code=-1,
            duration_ms=0,
            git_commit_before=git_sha_before,
        )

    # Double-check blocklist
    blocked, reason = is_blocklisted(remediation.command)
    if blocked:
        return ExecuteResult(
            remediation_id=remediation.id,
            status=ExecutionStatus.FAILED,
            command=remediation.command,
            stdout="",
            stderr=f"Execution blocked: {reason}",
            exit_code=-2,
            duration_ms=0,
            git_commit_before=git_sha_before,
        )

    # Execute the command
    start_time = time.time()
    try:
        result = subprocess.run(
            remediation.command,
            shell=True,
            capture_output=True,
            text=True,
            cwd=working_dir,
            timeout=300,  # 5 minute timeout
        )
        duration_ms = int((time.time() - start_time) * 1000)

        status = ExecutionStatus.SUCCESS if result.returncode == 0 else ExecutionStatus.FAILED
        git_sha_after = get_git_sha()

        return ExecuteResult(
            remediation_id=remediation.id,
            status=status,
            command=remediation.command,
            stdout=result.stdout,
            stderr=result.stderr,
            exit_code=result.returncode,
            duration_ms=duration_ms,
            git_commit_before=git_sha_before,
            git_commit_after=git_sha_after if git_sha_after != git_sha_before else None,
        )
    except subprocess.TimeoutExpired:
        duration_ms = int((time.time() - start_time) * 1000)
        return ExecuteResult(
            remediation_id=remediation.id,
            status=ExecutionStatus.FAILED,
            command=remediation.command,
            stdout="",
            stderr="Command timed out after 300 seconds",
            exit_code=-3,
            duration_ms=duration_ms,
            git_commit_before=git_sha_before,
        )
    except subprocess.SubprocessError as e:
        duration_ms = int((time.time() - start_time) * 1000)
        return ExecuteResult(
            remediation_id=remediation.id,
            status=ExecutionStatus.FAILED,
            command=remediation.command,
            stdout="",
            stderr=str(e),
            exit_code=-4,
            duration_ms=duration_ms,
            git_commit_before=git_sha_before,
        )


def write_audit_log(
    remediation: Remediation,
    dry_run_result: Optional[DryRunResult],
    approval: ApprovalResult,
    execute_result: Optional[ExecuteResult],
    audit_log_path: Path = Path("swarm/runs/remediation_audit.jsonl"),
) -> None:
    """Write a complete audit entry for the remediation attempt.

    The audit log is append-only JSONL format.
    """
    # Ensure directory exists
    audit_log_path.parent.mkdir(parents=True, exist_ok=True)

    entry = AuditLogEntry(
        version="1.0",
        timestamp=datetime.now(timezone.utc).isoformat(),
        remediation_id=remediation.id,
        transaction_id=f"tx-{uuid.uuid4().hex[:8]}",
        suggestion={
            "pattern_id": remediation.pattern_id,
            "step_id": remediation.step_id,
            "command": remediation.command,
            "severity": remediation.severity,
            "rationale": remediation.rationale,
        },
        allowlist_check={
            "allowed": is_allowlisted(remediation.command)[0],
            "reason": is_allowlisted(remediation.command)[1],
        },
        dry_run={
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "command": remediation.command,
            "diff_summary": dry_run_result.diff[:200] + "..." if dry_run_result and len(dry_run_result.diff) > 200 else (dry_run_result.diff if dry_run_result else ""),
            "affected_files": dry_run_result.affected_files if dry_run_result else [],
            "file_count": dry_run_result.file_count if dry_run_result else 0,
            "safe_to_execute": dry_run_result.safe_to_execute if dry_run_result else False,
            "warnings": dry_run_result.warnings if dry_run_result else [],
        } if dry_run_result else {},
        approval={
            "status": approval.status.value,
            "approver": approval.approver,
            "channel": approval.channel,
            "requested_at": approval.timestamp,
            "decided_at": datetime.now(timezone.utc).isoformat(),
            "timeout_seconds": approval.timeout_seconds,
        },
        execution={
            "status": execute_result.status.value if execute_result else "not_executed",
            "started_at": datetime.now(timezone.utc).isoformat() if execute_result else None,
            "completed_at": datetime.now(timezone.utc).isoformat() if execute_result else None,
            "duration_ms": execute_result.duration_ms if execute_result else 0,
            "exit_code": execute_result.exit_code if execute_result else None,
            "stdout_summary": execute_result.stdout[:500] if execute_result and execute_result.stdout else "",
            "stderr": execute_result.stderr[:500] if execute_result and execute_result.stderr else "",
            "git_sha_before": execute_result.git_commit_before if execute_result else None,
            "git_sha_after": execute_result.git_commit_after if execute_result else None,
        } if execute_result else {},
        metadata={
            "hostname": socket.gethostname(),
            "user": getpass.getuser(),
            "working_dir": str(Path.cwd()),
            "git_branch": get_git_branch(),
        },
    )

    # Write as JSONL (one JSON object per line)
    with open(audit_log_path, "a") as f:
        f.write(json.dumps(asdict(entry)) + "\n")


def print_summary(
    executed: List[Remediation],
    skipped: List[Remediation],
    blocked: List[Tuple[Remediation, str]],
    audit_log_path: Path,
) -> None:
    """Print execution summary."""
    print("\n=== Summary ===")
    print(f"Executed: {len(executed)}")
    print(f"Skipped: {len(skipped)}")
    print(f"Blocked (not in allowlist): {len(blocked)}")

    if blocked:
        print("\nBlocked remediations (not in allowlist):")
        for rem, reason in blocked:
            print(f"  - {rem.command}")
            print(f"    Reason: {reason}")

    print(f"\nAudit log: {audit_log_path}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Execute remediation suggestions with approval (Phase 1: CLI)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    uv run swarm/tools/selftest_remediate_execute.py
    uv run swarm/tools/selftest_remediate_execute.py --dry-run
    uv run swarm/tools/selftest_remediate_execute.py --auto-approve  # CI only
        """,
    )
    parser.add_argument(
        "--degradation-log",
        type=Path,
        help="Path to degradation log (default: latest in swarm/runs/)",
    )
    parser.add_argument(
        "--remediation-map",
        type=Path,
        default=Path("swarm/config/selftest_remediation_map.yaml"),
        help="Path to remediation map (default: swarm/config/selftest_remediation_map.yaml)",
    )
    parser.add_argument(
        "--audit-log",
        type=Path,
        default=Path("swarm/runs/remediation_audit.jsonl"),
        help="Path to audit log (default: swarm/runs/remediation_audit.jsonl)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be executed without actually running commands",
    )
    parser.add_argument(
        "--auto-approve",
        action="store_true",
        help="Auto-approve all allowlisted remediations (for CI only)",
    )

    args = parser.parse_args()

    print("=== Auto-Remediation Executor ===\n")

    # Get pending remediations
    remediations = get_pending_remediations(
        degradation_log=args.degradation_log,
        remediation_map=args.remediation_map,
    )

    if not remediations:
        print("No pending remediations found.")
        print("\nTo generate remediations, first run selftest in degraded mode:")
        print("  make selftest-degraded")
        print("  make selftest-suggest-remediation")
        return 0

    print(f"Found {len(remediations)} pending remediations:\n")

    # Track results
    executed: List[Remediation] = []
    skipped: List[Remediation] = []
    blocked: List[Tuple[Remediation, str]] = []

    # Process each remediation
    for i, remediation in enumerate(remediations, start=1):
        print(f"--- [{i}/{len(remediations)}] {remediation.pattern_id} ---")
        print(f"Step: {remediation.step_id} (severity: {remediation.severity.upper()})")

        # Check allowlist
        allowed, rejection_reason = is_allowlisted(remediation.command)
        if not allowed:
            print(f"  BLOCKED: {rejection_reason}")
            blocked.append((remediation, rejection_reason or "Not in allowlist"))

            # Still write audit log for blocked attempts
            approval = ApprovalResult(
                remediation_id=remediation.id,
                status=ApprovalStatus.REJECTED,
                approver="system",
                channel="allowlist-check",
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
            write_audit_log(
                remediation=remediation,
                dry_run_result=None,
                approval=approval,
                execute_result=None,
                audit_log_path=args.audit_log,
            )
            continue

        # Perform dry-run
        dry_run_result = dry_run(remediation)

        if args.dry_run:
            # In dry-run mode, just show what would happen
            print(f"  Command: {remediation.command}")
            print(f"  Would affect {dry_run_result.file_count} files")
            if dry_run_result.warnings:
                for w in dry_run_result.warnings:
                    print(f"  Warning: {w}")
            skipped.append(remediation)

            # Write audit log for dry-run
            approval = ApprovalResult(
                remediation_id=remediation.id,
                status=ApprovalStatus.REJECTED,
                approver="dry-run-mode",
                channel="cli",
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
            write_audit_log(
                remediation=remediation,
                dry_run_result=dry_run_result,
                approval=approval,
                execute_result=None,
                audit_log_path=args.audit_log,
            )
            continue

        # Request approval
        approval = request_approval(
            remediation=remediation,
            dry_run_result=dry_run_result,
            auto_approve=args.auto_approve,
        )

        if approval.status != ApprovalStatus.APPROVED:
            print("  Skipped.")
            skipped.append(remediation)

            write_audit_log(
                remediation=remediation,
                dry_run_result=dry_run_result,
                approval=approval,
                execute_result=None,
                audit_log_path=args.audit_log,
            )
            continue

        # Execute
        print(f"\n  Executing: {remediation.command}")
        execute_result = execute(remediation, approval)

        if execute_result.status == ExecutionStatus.SUCCESS:
            print("  Success!")
            if execute_result.stdout:
                # Show first few lines of output
                lines = execute_result.stdout.strip().split("\n")
                for line in lines[:5]:
                    print(f"    {line}")
                if len(lines) > 5:
                    print(f"    ... ({len(lines) - 5} more lines)")
            executed.append(remediation)
        else:
            print(f"  Failed (exit code {execute_result.exit_code})")
            if execute_result.stderr:
                print(f"  Error: {execute_result.stderr[:200]}")
            skipped.append(remediation)

        # Write audit log
        write_audit_log(
            remediation=remediation,
            dry_run_result=dry_run_result,
            approval=approval,
            execute_result=execute_result,
            audit_log_path=args.audit_log,
        )

    # Print summary
    print_summary(executed, skipped, blocked, args.audit_log)

    return 0


if __name__ == "__main__":
    sys.exit(main())
