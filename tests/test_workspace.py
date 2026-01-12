"""
test_workspace.py - Integration tests for workspace abstraction.

Tests the Workspace abstraction, boundary enforcement, and StepContext integration.
"""

from pathlib import Path

import pytest

from swarm.runtime.workspace import (
    RealWorkspace,
    ShadowForkWorkspace,
    ForensicsSnapshot,
    PromotionResult,
    create_workspace,
)
from swarm.runtime.boundary_enforcement import (
    BoundaryScanner,
    WorkspaceState,
    Violation,
    ViolationType,
    ViolationSeverity,
)
from swarm.runtime.engines.models import StepContext
from swarm.runtime.types import RunSpec


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def temp_repo(tmp_path: Path) -> Path:
    """Create a temporary git repository."""
    repo = tmp_path / "repo"
    repo.mkdir()

    # Initialize git repo
    import subprocess

    subprocess.run(["git", "init"], cwd=str(repo), capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=str(repo),
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=str(repo),
        capture_output=True,
    )

    # Create initial commit
    (repo / "README.md").write_text("# Test Repo")
    subprocess.run(["git", "add", "."], cwd=str(repo), capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=str(repo),
        capture_output=True,
    )

    return repo


@pytest.fixture
def run_spec() -> RunSpec:
    """Create a minimal run spec."""
    return RunSpec(
        flow_keys=["build"],
        initiator="test",
    )


# =============================================================================
# RealWorkspace Tests
# =============================================================================


class TestRealWorkspace:
    """Tests for RealWorkspace."""

    def test_root_returns_repo_root(self, temp_repo: Path):
        """Test that root() returns the repo root path."""
        workspace = RealWorkspace(repo_root=temp_repo, run_id="test-run")
        assert workspace.root() == temp_repo.resolve()

    def test_is_shadow_returns_false(self, temp_repo: Path):
        """Test that is_shadow() returns False for real workspace."""
        workspace = RealWorkspace(repo_root=temp_repo, run_id="test-run")
        assert workspace.is_shadow() is False

    def test_run_base_calculation(self, temp_repo: Path):
        """Test that run_base is calculated correctly."""
        workspace = RealWorkspace(repo_root=temp_repo, run_id="test-run")
        expected = temp_repo / "swarm" / "runs" / "test-run"
        assert workspace.run_base == expected

    def test_snapshot_forensics_returns_snapshot(self, temp_repo: Path):
        """Test that snapshot_forensics() returns a ForensicsSnapshot."""
        workspace = RealWorkspace(repo_root=temp_repo, run_id="test-run")
        snapshot = workspace.snapshot_forensics()

        assert isinstance(snapshot, ForensicsSnapshot)
        assert snapshot.workspace_type == "real"
        assert snapshot.workspace_root == str(temp_repo.resolve())

    def test_promote_is_noop(self, temp_repo: Path):
        """Test that promote() is a no-op for real workspace."""
        workspace = RealWorkspace(repo_root=temp_repo, run_id="test-run")
        result = workspace.promote()

        assert isinstance(result, PromotionResult)
        assert result.success is True
        assert "no promotion needed" in result.summary.lower()

    def test_cleanup_is_noop(self, temp_repo: Path):
        """Test that cleanup() is a no-op for real workspace."""
        workspace = RealWorkspace(repo_root=temp_repo, run_id="test-run")
        # Should not raise
        workspace.cleanup(success=True)
        workspace.cleanup(success=False)


# =============================================================================
# ShadowForkWorkspace Tests
# =============================================================================


class TestShadowForkWorkspace:
    """Tests for ShadowForkWorkspace."""

    def test_is_shadow_returns_true(self, temp_repo: Path):
        """Test that is_shadow() returns True for shadow workspace."""
        workspace = ShadowForkWorkspace(repo_root=temp_repo, run_id="test-run")
        assert workspace.is_shadow() is True

    def test_root_returns_repo_root(self, temp_repo: Path):
        """Test that root() returns the repo root (same location, different branch)."""
        workspace = ShadowForkWorkspace(repo_root=temp_repo, run_id="test-run")
        assert workspace.root() == temp_repo.resolve()

    def test_run_base_calculation(self, temp_repo: Path):
        """Test that run_base is calculated correctly."""
        workspace = ShadowForkWorkspace(repo_root=temp_repo, run_id="test-run")
        expected = temp_repo / "swarm" / "runs" / "test-run"
        assert workspace.run_base == expected

    def test_record_boundary_violation(self, temp_repo: Path):
        """Test recording boundary violations."""
        workspace = ShadowForkWorkspace(repo_root=temp_repo, run_id="test-run")

        workspace.record_boundary_violation(
            path="/outside/path",
            operation="write",
            step_id="test-step",
        )

        violations = workspace.get_boundary_violations()
        assert len(violations) == 1
        assert violations[0].path == "/outside/path"
        assert violations[0].operation == "write"
        assert violations[0].step_id == "test-step"


# =============================================================================
# Factory Function Tests
# =============================================================================


class TestCreateWorkspace:
    """Tests for create_workspace factory function."""

    def test_creates_real_workspace_for_deploy(self, temp_repo: Path):
        """Test that deploy flow gets a real workspace."""
        workspace = create_workspace(
            repo_root=temp_repo,
            run_id="test-run",
            flow_key="deploy",
        )
        assert isinstance(workspace, RealWorkspace)
        assert workspace.is_shadow() is False

    def test_explicit_shadow_mode_false(self, temp_repo: Path):
        """Test explicit shadow_mode=False creates real workspace."""
        workspace = create_workspace(
            repo_root=temp_repo,
            run_id="test-run",
            flow_key="build",
            shadow_mode=False,
        )
        assert isinstance(workspace, RealWorkspace)

    def test_explicit_shadow_mode_true(self, temp_repo: Path):
        """Test explicit shadow_mode=True creates shadow workspace."""
        workspace = create_workspace(
            repo_root=temp_repo,
            run_id="test-run",
            flow_key="deploy",
            shadow_mode=True,
        )
        assert isinstance(workspace, ShadowForkWorkspace)


# =============================================================================
# BoundaryScanner Tests
# =============================================================================


class TestBoundaryScanner:
    """Tests for BoundaryScanner."""

    def test_capture_state(self, temp_repo: Path):
        """Test capturing workspace state."""
        workspace = RealWorkspace(repo_root=temp_repo, run_id="test-run")
        scanner = BoundaryScanner(
            workspace=workspace,
            step_id="test-step",
            repo_root=temp_repo,
        )

        state = scanner.capture_state()

        assert isinstance(state, WorkspaceState)
        assert state.timestamp  # Should have a timestamp
        assert isinstance(state.changed_files, set)

    def test_scan_with_no_changes(self, temp_repo: Path):
        """Test scanning with no changes reports no violations."""
        workspace = RealWorkspace(repo_root=temp_repo, run_id="test-run")
        scanner = BoundaryScanner(
            workspace=workspace,
            step_id="test-step",
            repo_root=temp_repo,
        )

        violations = scanner.scan()

        # No changes = no violations
        assert len(violations) == 0

    def test_detect_secret_exposure_pattern(self, temp_repo: Path):
        """Test that secret exposure patterns are detected."""
        workspace = RealWorkspace(repo_root=temp_repo, run_id="test-run")

        # Create a file with secret pattern
        (temp_repo / ".env").write_text("SECRET=test")

        scanner = BoundaryScanner(
            workspace=workspace,
            step_id="test-step",
            repo_root=temp_repo,
        )

        # Capture state with the new file
        import subprocess
        subprocess.run(["git", "add", ".env"], cwd=str(temp_repo), capture_output=True)

        violations = scanner.scan()

        # Should detect secret exposure
        secret_violations = [
            v for v in violations
            if v.type == ViolationType.SECRET_EXPOSURE
        ]
        assert len(secret_violations) > 0


# =============================================================================
# StepContext Integration Tests
# =============================================================================


class TestStepContextWorkspaceIntegration:
    """Tests for StepContext workspace integration."""

    def test_run_base_uses_workspace_when_available(self, temp_repo: Path, run_spec: RunSpec):
        """Test that run_base uses workspace.run_base when workspace is set."""
        workspace = RealWorkspace(repo_root=temp_repo, run_id="test-run")

        ctx = StepContext(
            repo_root=temp_repo,
            run_id="test-run",
            flow_key="build",
            step_id="test-step",
            step_index=1,
            total_steps=1,
            spec=run_spec,
            flow_title="Build",
            step_role="Test step",
            workspace=workspace,
        )

        assert ctx.run_base == workspace.run_base

    def test_run_base_fallback_without_workspace(self, temp_repo: Path, run_spec: RunSpec):
        """Test that run_base falls back to calculation when no workspace."""
        ctx = StepContext(
            repo_root=temp_repo,
            run_id="test-run",
            flow_key="build",
            step_id="test-step",
            step_index=1,
            total_steps=1,
            spec=run_spec,
            flow_title="Build",
            step_role="Test step",
            workspace=None,
        )

        expected = temp_repo / "swarm" / "runs" / "test-run" / "build"
        assert ctx.run_base == expected

    def test_is_shadow_mode_with_shadow_workspace(self, temp_repo: Path, run_spec: RunSpec):
        """Test is_shadow_mode returns True with shadow workspace."""
        workspace = ShadowForkWorkspace(repo_root=temp_repo, run_id="test-run")

        ctx = StepContext(
            repo_root=temp_repo,
            run_id="test-run",
            flow_key="build",
            step_id="test-step",
            step_index=1,
            total_steps=1,
            spec=run_spec,
            flow_title="Build",
            step_role="Test step",
            workspace=workspace,
        )

        assert ctx.is_shadow_mode is True

    def test_is_shadow_mode_with_real_workspace(self, temp_repo: Path, run_spec: RunSpec):
        """Test is_shadow_mode returns False with real workspace."""
        workspace = RealWorkspace(repo_root=temp_repo, run_id="test-run")

        ctx = StepContext(
            repo_root=temp_repo,
            run_id="test-run",
            flow_key="build",
            step_id="test-step",
            step_index=1,
            total_steps=1,
            spec=run_spec,
            flow_title="Build",
            step_role="Test step",
            workspace=workspace,
        )

        assert ctx.is_shadow_mode is False

    def test_is_shadow_mode_without_workspace(self, temp_repo: Path, run_spec: RunSpec):
        """Test is_shadow_mode returns False when no workspace."""
        ctx = StepContext(
            repo_root=temp_repo,
            run_id="test-run",
            flow_key="build",
            step_id="test-step",
            step_index=1,
            total_steps=1,
            spec=run_spec,
            flow_title="Build",
            step_role="Test step",
            workspace=None,
        )

        assert ctx.is_shadow_mode is False


# =============================================================================
# Violation Tests
# =============================================================================


class TestViolation:
    """Tests for Violation data class."""

    def test_to_dict(self):
        """Test serialization to dict."""
        violation = Violation(
            type=ViolationType.WRITE_OUTSIDE_WORKSPACE,
            severity=ViolationSeverity.ERROR,
            path="/some/path",
            operation="write",
            detail="Wrote outside workspace",
            step_id="test-step",
            remediation="Fix it",
        )

        d = violation.to_dict()

        assert d["type"] == "write_outside_workspace"
        assert d["severity"] == "error"
        assert d["path"] == "/some/path"
        assert d["operation"] == "write"
        assert d["step_id"] == "test-step"
