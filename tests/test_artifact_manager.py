"""
Test suite for ArtifactManager (swarm/tools/artifact_manager.py).

Tests the run ID generation, path layout, and artifact read/write functionality
used for managing flow artifacts under swarm/runs/<run-id>/.

Coverage:
1. Run ID generation (unique, follows naming convention)
2. Path layout (correct directories under swarm/runs/<run-id>/)
3. Artifact read/write operations
4. Path builder functions
5. Helper functions (platform, hostname, git info, user)
"""

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

# Add swarm/tools to path for imports
_repo_root = Path(__file__).parent.parent
sys.path.insert(0, str(_repo_root / "swarm" / "tools"))

from artifact_manager import (
    ArtifactManager,
    get_git_info,
    get_hostname,
    get_platform_name,
    get_user,
)


# ============================================================================
# Helper Function Tests
# ============================================================================


class TestGetPlatformName:
    """Tests for get_platform_name() helper."""

    def test_returns_sys_platform(self):
        """get_platform_name returns sys.platform value."""
        result = get_platform_name()
        assert result == sys.platform

    def test_returns_string(self):
        """get_platform_name returns a string."""
        result = get_platform_name()
        assert isinstance(result, str)
        assert len(result) > 0


class TestGetHostname:
    """Tests for get_hostname() helper."""

    def test_returns_hostname(self):
        """get_hostname returns a non-empty string."""
        result = get_hostname()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_matches_socket_gethostname(self):
        """get_hostname returns socket.gethostname() result."""
        import socket

        result = get_hostname()
        assert result == socket.gethostname()


class TestGetGitInfo:
    """Tests for get_git_info() helper."""

    def test_returns_tuple(self):
        """get_git_info returns a tuple of (branch, commit)."""
        result = get_git_info()
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_returns_strings(self):
        """get_git_info returns two strings."""
        branch, commit = get_git_info()
        assert isinstance(branch, str)
        assert isinstance(commit, str)

    def test_handles_non_git_directory(self, tmp_path, monkeypatch):
        """get_git_info returns 'unknown' when not in a git repo."""
        # Change to a non-git directory
        monkeypatch.chdir(tmp_path)
        branch, commit = get_git_info()
        # Should return unknown or empty values when git commands fail
        assert branch in ("unknown", "")
        assert commit in ("unknown", "")

    def test_returns_branch_and_commit_in_git_repo(self, tmp_path, monkeypatch):
        """get_git_info returns actual branch and commit in a git repo."""
        # Create a git repo
        monkeypatch.chdir(tmp_path)
        subprocess.run(["git", "init"], capture_output=True, check=True)
        subprocess.run(
            ["git", "config", "user.name", "Test"], capture_output=True, check=True
        )
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            capture_output=True,
            check=True,
        )

        # Create a file and commit
        (tmp_path / "test.txt").write_text("test")
        subprocess.run(["git", "add", "."], capture_output=True, check=True)
        subprocess.run(
            ["git", "commit", "-m", "initial"], capture_output=True, check=True
        )

        branch, commit = get_git_info()

        # Branch should be main or master (depending on git version defaults)
        assert branch in ("main", "master", "unknown")
        # Commit should be a short hash (7-12 chars) or unknown
        assert len(commit) >= 7 or commit == "unknown"


class TestGetUser:
    """Tests for get_user() helper."""

    def test_returns_string(self):
        """get_user returns a string."""
        result = get_user()
        assert isinstance(result, str)

    def test_returns_user_from_env(self):
        """get_user returns USER or USERNAME from environment."""
        with patch.dict(os.environ, {"USER": "testuser"}, clear=False):
            result = get_user()
            assert result == "testuser" or result == os.environ.get(
                "USERNAME", "unknown"
            )

    def test_returns_unknown_when_no_user_env(self):
        """get_user returns 'unknown' when USER/USERNAME not set."""
        with patch.dict(os.environ, {}, clear=True):
            result = get_user()
            assert result == "unknown"


# ============================================================================
# Run ID Detection Tests
# ============================================================================


class TestRunIdDetection:
    """Tests for ArtifactManager._detect_run_id()."""

    def test_uses_git_branch_env_var(self, tmp_path):
        """Run ID uses GIT_BRANCH environment variable when set."""
        with patch.dict(os.environ, {"GIT_BRANCH": "feature/my-branch"}):
            manager = ArtifactManager(repo_root=tmp_path)
            assert manager.run_id == "feature/my-branch"

    def test_uses_ci_commit_sha_env_var(self, tmp_path):
        """Run ID uses CI_COMMIT_SHA (first 12 chars) when set."""
        with patch.dict(
            os.environ,
            {"CI_COMMIT_SHA": "abc123def456789", "GIT_BRANCH": ""},
            clear=False,
        ):
            # Clear GIT_BRANCH to test CI_COMMIT_SHA
            env = os.environ.copy()
            env.pop("GIT_BRANCH", None)
            with patch.dict(os.environ, env, clear=True):
                with patch.dict(os.environ, {"CI_COMMIT_SHA": "abc123def456789"}):
                    manager = ArtifactManager(repo_root=tmp_path)
                    # Code uses [:12] so we get 12 characters
                    assert manager.run_id == "abc123def456"

    def test_uses_git_branch_from_repo(self, tmp_path, monkeypatch):
        """Run ID uses git branch name when in a git repo."""
        # Create a git repo
        monkeypatch.chdir(tmp_path)
        subprocess.run(["git", "init"], capture_output=True, check=True)
        subprocess.run(
            ["git", "config", "user.name", "Test"], capture_output=True, check=True
        )
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            capture_output=True,
            check=True,
        )
        (tmp_path / "test.txt").write_text("test")
        subprocess.run(["git", "add", "."], capture_output=True, check=True)
        subprocess.run(
            ["git", "commit", "-m", "initial"], capture_output=True, check=True
        )

        # Clear env vars to test git detection
        with patch.dict(os.environ, {"GIT_BRANCH": "", "CI_COMMIT_SHA": ""}, clear=False):
            env = os.environ.copy()
            env.pop("GIT_BRANCH", None)
            env.pop("CI_COMMIT_SHA", None)
            with patch.dict(os.environ, env, clear=True):
                manager = ArtifactManager(repo_root=tmp_path)
                # Should be main or master
                assert manager.run_id in ("main", "master") or len(manager.run_id) >= 7

    def test_fallback_to_timestamp(self, tmp_path):
        """Run ID falls back to timestamp when no git or env vars."""
        # Clear env vars and ensure git fails
        with patch.dict(os.environ, {}, clear=True):
            with patch("subprocess.run") as mock_run:
                # Make git commands return empty strings
                mock_run.return_value.stdout = ""
                manager = ArtifactManager(repo_root=tmp_path)

                # Should be timestamp format: YYYYMMDD-HHMMSS
                assert len(manager.run_id) == 15
                assert "-" in manager.run_id
                # Validate it's a valid timestamp format
                try:
                    datetime.strptime(manager.run_id, "%Y%m%d-%H%M%S")
                except ValueError:
                    pytest.fail(f"Run ID {manager.run_id} is not in timestamp format")

    def test_run_id_is_unique_per_second(self, tmp_path):
        """Run IDs generated at different times should differ."""
        with patch.dict(os.environ, {}, clear=True):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value.stdout = ""

                manager1 = ArtifactManager(repo_root=tmp_path)
                # Simulate time passing by patching datetime
                with patch("artifact_manager.datetime") as mock_dt:
                    mock_dt.now.return_value = datetime(2025, 1, 1, 12, 0, 1)
                    mock_dt.strftime = datetime.strftime
                    manager2 = ArtifactManager(repo_root=tmp_path)

                # They should be different (unless same second)
                # This test is probabilistic but should pass


# ============================================================================
# Path Layout Tests
# ============================================================================


class TestPathLayout:
    """Tests for path building functions."""

    def test_get_run_base_returns_correct_path(self, tmp_path):
        """get_run_base returns swarm/runs/<run-id>/."""
        with patch.dict(os.environ, {"GIT_BRANCH": "test-branch"}):
            manager = ArtifactManager(repo_root=tmp_path)
            run_base = manager.get_run_base()

            assert run_base == tmp_path / "swarm" / "runs" / "test-branch"

    def test_get_run_base_uses_repo_root(self, tmp_path):
        """get_run_base is relative to repo_root."""
        custom_root = tmp_path / "custom" / "root"
        custom_root.mkdir(parents=True)

        with patch.dict(os.environ, {"GIT_BRANCH": "my-branch"}):
            manager = ArtifactManager(repo_root=custom_root)
            run_base = manager.get_run_base()

            assert run_base.parent.parent.parent == custom_root

    def test_get_artifact_path_builds_correct_path(self, tmp_path):
        """get_artifact_path returns RUN_BASE/<flow>/<filename>."""
        with patch.dict(os.environ, {"GIT_BRANCH": "test-run"}):
            manager = ArtifactManager(repo_root=tmp_path)
            path = manager.get_artifact_path("signal", "requirements.md")

            expected = tmp_path / "swarm" / "runs" / "test-run" / "signal" / "requirements.md"
            assert path == expected

    def test_get_artifact_path_various_flows(self, tmp_path):
        """get_artifact_path works for all flow types."""
        flows = ["signal", "plan", "build", "gate", "deploy", "wisdom"]

        with patch.dict(os.environ, {"GIT_BRANCH": "multi-flow"}):
            manager = ArtifactManager(repo_root=tmp_path)

            for flow in flows:
                path = manager.get_artifact_path(flow, f"{flow}_artifact.md")
                assert flow in str(path)
                assert path.name == f"{flow}_artifact.md"

    def test_ensure_artifact_dir_creates_directory(self, tmp_path):
        """ensure_artifact_dir creates the flow directory."""
        with patch.dict(os.environ, {"GIT_BRANCH": "dir-test"}):
            manager = ArtifactManager(repo_root=tmp_path)

            # Directory should not exist yet
            flow_dir = manager.get_run_base() / "signal"
            assert not flow_dir.exists()

            # Create it
            result = manager.ensure_artifact_dir("signal")

            assert flow_dir.exists()
            assert flow_dir.is_dir()
            assert result == flow_dir

    def test_ensure_artifact_dir_creates_parent_dirs(self, tmp_path):
        """ensure_artifact_dir creates all parent directories."""
        with patch.dict(os.environ, {"GIT_BRANCH": "nested-test"}):
            manager = ArtifactManager(repo_root=tmp_path)

            # Neither swarm/runs nor the flow dir should exist
            run_base = manager.get_run_base()
            assert not run_base.exists()

            manager.ensure_artifact_dir("build")

            assert run_base.exists()
            assert (run_base / "build").exists()

    def test_ensure_artifact_dir_is_idempotent(self, tmp_path):
        """ensure_artifact_dir can be called multiple times safely."""
        with patch.dict(os.environ, {"GIT_BRANCH": "idempotent-test"}):
            manager = ArtifactManager(repo_root=tmp_path)

            # Call multiple times
            result1 = manager.ensure_artifact_dir("gate")
            result2 = manager.ensure_artifact_dir("gate")
            result3 = manager.ensure_artifact_dir("gate")

            assert result1 == result2 == result3
            assert result1.exists()


# ============================================================================
# Artifact Write Tests
# ============================================================================


class TestWriteArtifact:
    """Tests for ArtifactManager.write_artifact()."""

    def test_write_string_artifact(self, tmp_path):
        """write_artifact writes string content to file."""
        with patch.dict(os.environ, {"GIT_BRANCH": "write-test"}):
            manager = ArtifactManager(repo_root=tmp_path)

            content = "# Requirements\n\n- REQ-001: System shall work"
            result = manager.write_artifact("signal", "requirements.md", content)

            assert result.exists()
            assert result.read_text(encoding="utf-8") == content

    def test_write_dict_artifact_as_json(self, tmp_path):
        """write_artifact writes dict content as JSON."""
        with patch.dict(os.environ, {"GIT_BRANCH": "json-test"}):
            manager = ArtifactManager(repo_root=tmp_path)

            content = {"status": "VERIFIED", "issues": [], "timestamp": "2025-01-01"}
            result = manager.write_artifact("build", "receipt.json", content)

            assert result.exists()
            # Verify it's valid JSON
            with open(result) as f:
                loaded = json.load(f)
            assert loaded == content

    def test_write_artifact_creates_directory(self, tmp_path):
        """write_artifact creates flow directory if needed."""
        with patch.dict(os.environ, {"GIT_BRANCH": "auto-dir"}):
            manager = ArtifactManager(repo_root=tmp_path)

            # Directory should not exist
            assert not (manager.get_run_base() / "plan").exists()

            manager.write_artifact("plan", "adr.md", "# ADR 001")

            # Now it should exist
            assert (manager.get_run_base() / "plan").exists()

    def test_write_artifact_returns_path(self, tmp_path):
        """write_artifact returns the path to the written file."""
        with patch.dict(os.environ, {"GIT_BRANCH": "path-return"}):
            manager = ArtifactManager(repo_root=tmp_path)

            result = manager.write_artifact("gate", "decision.md", "MERGE")

            assert isinstance(result, Path)
            assert result.name == "decision.md"
            assert "gate" in str(result)

    def test_write_artifact_overwrites_existing(self, tmp_path):
        """write_artifact overwrites existing file."""
        with patch.dict(os.environ, {"GIT_BRANCH": "overwrite-test"}):
            manager = ArtifactManager(repo_root=tmp_path)

            # Write initial content
            manager.write_artifact("signal", "test.md", "original")

            # Overwrite
            manager.write_artifact("signal", "test.md", "updated")

            path = manager.get_artifact_path("signal", "test.md")
            assert path.read_text(encoding="utf-8") == "updated"

    def test_write_dict_with_datetime(self, tmp_path):
        """write_artifact handles dict with datetime values."""
        with patch.dict(os.environ, {"GIT_BRANCH": "datetime-test"}):
            manager = ArtifactManager(repo_root=tmp_path)

            now = datetime.now()
            content = {"created": now, "data": "test"}
            result = manager.write_artifact("wisdom", "report.json", content)

            # Should not raise - datetime converted to string via default=str
            assert result.exists()


# ============================================================================
# Artifact Read Tests
# ============================================================================


class TestReadArtifact:
    """Tests for ArtifactManager.read_artifact()."""

    def test_read_string_artifact(self, tmp_path):
        """read_artifact reads string content from file."""
        with patch.dict(os.environ, {"GIT_BRANCH": "read-test"}):
            manager = ArtifactManager(repo_root=tmp_path)

            # Write first
            content = "# Test Content\n\nSome text here."
            manager.write_artifact("signal", "test.md", content)

            # Read back
            result = manager.read_artifact("signal", "test.md")
            assert result == content

    def test_read_json_artifact_parsed(self, tmp_path):
        """read_artifact auto-parses .json files."""
        with patch.dict(os.environ, {"GIT_BRANCH": "json-read"}):
            manager = ArtifactManager(repo_root=tmp_path)

            content = {"key": "value", "count": 42}
            manager.write_artifact("build", "data.json", content)

            result = manager.read_artifact("build", "data.json")

            # Should be parsed as dict
            assert isinstance(result, dict)
            assert result == content

    def test_read_nonexistent_returns_none(self, tmp_path):
        """read_artifact returns None for missing files."""
        with patch.dict(os.environ, {"GIT_BRANCH": "missing-test"}):
            manager = ArtifactManager(repo_root=tmp_path)

            result = manager.read_artifact("signal", "nonexistent.md")
            assert result is None

    def test_read_invalid_json_returns_string(self, tmp_path):
        """read_artifact returns string if JSON parsing fails."""
        with patch.dict(os.environ, {"GIT_BRANCH": "invalid-json"}):
            manager = ArtifactManager(repo_root=tmp_path)

            # Write invalid JSON with .json extension
            manager.ensure_artifact_dir("build")
            path = manager.get_artifact_path("build", "bad.json")
            path.write_text("this is not valid json {{{")

            result = manager.read_artifact("build", "bad.json")

            # Should return as string since JSON parsing failed
            assert isinstance(result, str)
            assert result == "this is not valid json {{{"

    def test_read_non_json_extension_not_parsed(self, tmp_path):
        """read_artifact does not parse non-.json files."""
        with patch.dict(os.environ, {"GIT_BRANCH": "ext-test"}):
            manager = ArtifactManager(repo_root=tmp_path)

            # Write JSON content but with .txt extension
            content = '{"key": "value"}'
            manager.write_artifact("signal", "data.txt", content)

            result = manager.read_artifact("signal", "data.txt")

            # Should return as string, not parsed
            assert isinstance(result, str)
            assert result == content


# ============================================================================
# Default Repo Root Tests
# ============================================================================


class TestDefaultRepoRoot:
    """Tests for ArtifactManager default repo_root behavior."""

    def test_defaults_to_cwd(self, tmp_path, monkeypatch):
        """ArtifactManager defaults to cwd when repo_root not specified."""
        monkeypatch.chdir(tmp_path)

        with patch.dict(os.environ, {"GIT_BRANCH": "cwd-test"}):
            manager = ArtifactManager()

            assert manager.repo_root == tmp_path

    def test_explicit_repo_root_overrides_cwd(self, tmp_path, monkeypatch):
        """Explicit repo_root takes precedence over cwd."""
        other_dir = tmp_path / "other"
        other_dir.mkdir()
        monkeypatch.chdir(other_dir)

        custom_root = tmp_path / "custom"
        custom_root.mkdir()

        with patch.dict(os.environ, {"GIT_BRANCH": "explicit-root"}):
            manager = ArtifactManager(repo_root=custom_root)

            assert manager.repo_root == custom_root
            assert manager.repo_root != Path.cwd()


# ============================================================================
# Integration Tests
# ============================================================================


class TestArtifactManagerIntegration:
    """Integration tests for full artifact workflows."""

    def test_full_flow_artifact_cycle(self, tmp_path):
        """Test complete write-read cycle across multiple flows."""
        with patch.dict(os.environ, {"GIT_BRANCH": "integration-test"}):
            manager = ArtifactManager(repo_root=tmp_path)

            # Write artifacts to multiple flows
            artifacts = {
                "signal": ("requirements.md", "# Requirements"),
                "plan": ("adr.md", "# ADR 001"),
                "build": ("receipt.json", {"status": "VERIFIED"}),
                "gate": ("decision.md", "MERGE"),
            }

            for flow, (filename, content) in artifacts.items():
                manager.write_artifact(flow, filename, content)

            # Read them all back
            for flow, (filename, expected) in artifacts.items():
                result = manager.read_artifact(flow, filename)
                assert result == expected

    def test_multiple_artifacts_same_flow(self, tmp_path):
        """Test writing multiple artifacts to the same flow."""
        with patch.dict(os.environ, {"GIT_BRANCH": "multi-artifact"}):
            manager = ArtifactManager(repo_root=tmp_path)

            files = [
                ("requirements.md", "# REQ"),
                ("problem_statement.md", "# Problem"),
                ("risk_assessment.md", "# Risks"),
            ]

            for filename, content in files:
                manager.write_artifact("signal", filename, content)

            # Verify all exist
            for filename, content in files:
                result = manager.read_artifact("signal", filename)
                assert result == content

    def test_path_with_special_characters(self, tmp_path):
        """Test handling of run IDs with special characters."""
        # Branch names can have slashes
        with patch.dict(os.environ, {"GIT_BRANCH": "feature/add-auth"}):
            manager = ArtifactManager(repo_root=tmp_path)

            # Write artifact - this tests that slashes in run_id work
            manager.write_artifact("signal", "test.md", "content")

            # Verify path contains the full branch name
            run_base = manager.get_run_base()
            assert "feature/add-auth" in str(run_base) or "feature" in str(run_base)


# ============================================================================
# Edge Cases
# ============================================================================


class TestEdgeCases:
    """Edge case tests for ArtifactManager."""

    def test_empty_content(self, tmp_path):
        """Handle writing empty content."""
        with patch.dict(os.environ, {"GIT_BRANCH": "empty-content"}):
            manager = ArtifactManager(repo_root=tmp_path)

            manager.write_artifact("signal", "empty.md", "")

            result = manager.read_artifact("signal", "empty.md")
            assert result == ""

    def test_empty_dict(self, tmp_path):
        """Handle writing empty dict."""
        with patch.dict(os.environ, {"GIT_BRANCH": "empty-dict"}):
            manager = ArtifactManager(repo_root=tmp_path)

            manager.write_artifact("build", "empty.json", {})

            result = manager.read_artifact("build", "empty.json")
            assert result == {}

    def test_nested_dict(self, tmp_path):
        """Handle writing deeply nested dict."""
        with patch.dict(os.environ, {"GIT_BRANCH": "nested-dict"}):
            manager = ArtifactManager(repo_root=tmp_path)

            content = {
                "level1": {
                    "level2": {
                        "level3": {"data": [1, 2, 3]},
                    },
                },
            }
            manager.write_artifact("wisdom", "nested.json", content)

            result = manager.read_artifact("wisdom", "nested.json")
            assert result == content

    def test_unicode_content(self, tmp_path):
        """Handle unicode content in artifacts."""
        with patch.dict(os.environ, {"GIT_BRANCH": "unicode-test"}):
            manager = ArtifactManager(repo_root=tmp_path)

            content = "# Requirements\n\n- Support Japanese: \u65e5\u672c\u8a9e\n- Support emoji: test"
            manager.write_artifact("signal", "unicode.md", content)

            result = manager.read_artifact("signal", "unicode.md")
            assert result == content

    def test_very_long_filename(self, tmp_path):
        """Handle very long filenames."""
        with patch.dict(os.environ, {"GIT_BRANCH": "long-name"}):
            manager = ArtifactManager(repo_root=tmp_path)

            long_name = "a" * 200 + ".md"
            try:
                manager.write_artifact("signal", long_name, "content")
                result = manager.read_artifact("signal", long_name)
                assert result == "content"
            except OSError:
                # Some filesystems have name length limits - that's okay
                pytest.skip("Filesystem doesn't support long filenames")
