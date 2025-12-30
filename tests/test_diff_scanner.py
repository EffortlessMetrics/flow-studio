"""
Tests for the diff_scanner module.

These tests verify the forensic file change detection functionality
that captures all file mutations during step execution.
"""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone

from swarm.runtime.diff_scanner import (
    FileDiff,
    FileChanges,
    file_diff_to_dict,
    file_diff_from_dict,
    file_changes_to_dict,
    file_changes_from_dict,
    scan_file_changes_sync,
    _parse_status_line,
    _parse_numstat_line,
    _run_git_command,
    create_file_changes_event,
)


class TestFileDiff:
    """Tests for the FileDiff dataclass."""

    def test_basic_creation(self):
        """Test creating a basic FileDiff."""
        diff = FileDiff(
            path="src/main.py",
            status="M",
            insertions=10,
            deletions=5,
        )
        assert diff.path == "src/main.py"
        assert diff.status == "M"
        assert diff.insertions == 10
        assert diff.deletions == 5
        assert diff.old_path is None

    def test_rename_detection(self):
        """Test rename detection property."""
        regular = FileDiff(path="a.py", status="M")
        assert not regular.is_rename

        rename = FileDiff(path="b.py", status="R100", old_path="a.py")
        assert rename.is_rename

    def test_serialization_roundtrip(self):
        """Test dict serialization and deserialization."""
        original = FileDiff(
            path="src/lib.py",
            status="A",
            insertions=50,
            deletions=0,
        )
        as_dict = file_diff_to_dict(original)
        restored = file_diff_from_dict(as_dict)

        assert restored.path == original.path
        assert restored.status == original.status
        assert restored.insertions == original.insertions
        assert restored.deletions == original.deletions


class TestFileChanges:
    """Tests for the FileChanges dataclass."""

    def test_empty_changes(self):
        """Test empty file changes detection."""
        changes = FileChanges()
        assert not changes.has_changes
        assert changes.file_count == 0
        assert changes.summary == "No changes detected"

    def test_has_changes_with_files(self):
        """Test has_changes with tracked files."""
        changes = FileChanges(
            files=[FileDiff(path="a.py", status="M")],
            total_insertions=10,
            total_deletions=5,
        )
        assert changes.has_changes
        assert changes.file_count == 1

    def test_has_changes_with_untracked(self):
        """Test has_changes with untracked files."""
        changes = FileChanges(untracked=["new_file.py"])
        assert changes.has_changes
        assert changes.file_count == 1

    def test_summary_format(self):
        """Test human-readable summary generation."""
        changes = FileChanges(
            files=[
                FileDiff(path="a.py", status="M", insertions=10, deletions=2),
                FileDiff(path="b.py", status="A", insertions=50, deletions=0),
            ],
            total_insertions=60,
            total_deletions=2,
            untracked=["c.py"],
        )
        summary = changes.summary
        assert "2 files changed" in summary
        assert "+60" in summary
        assert "-2" in summary
        assert "1 untracked" in summary

    def test_error_summary(self):
        """Test summary when scan failed."""
        changes = FileChanges(scan_error="Not a git repository")
        assert "Scan error:" in changes.summary
        assert "Not a git repository" in changes.summary

    def test_serialization_roundtrip(self):
        """Test dict serialization and deserialization."""
        original = FileChanges(
            files=[FileDiff(path="a.py", status="M", insertions=5, deletions=3)],
            total_insertions=5,
            total_deletions=3,
            untracked=["b.py"],
            staged=["c.py"],
        )
        as_dict = file_changes_to_dict(original)
        restored = file_changes_from_dict(as_dict)

        assert len(restored.files) == 1
        assert restored.files[0].path == "a.py"
        assert restored.total_insertions == 5
        assert restored.total_deletions == 3
        assert "b.py" in restored.untracked
        assert "c.py" in restored.staged


class TestParseNumstatLine:
    """Tests for _parse_numstat_line helper."""

    def test_regular_file(self):
        """Test parsing regular file with insertions and deletions."""
        result = _parse_numstat_line("10\t5\tsrc/main.py")
        assert result == (10, 5, "src/main.py")

    def test_binary_file(self):
        """Test parsing binary file (shows - for counts)."""
        result = _parse_numstat_line("-\t-\timage.png")
        assert result == (0, 0, "image.png")

    def test_invalid_line(self):
        """Test parsing invalid line."""
        assert _parse_numstat_line("invalid") is None
        assert _parse_numstat_line("") is None


class TestParseStatusLine:
    """Tests for _parse_status_line helper."""

    def test_modified_staged(self):
        """Test parsing staged modification (M in first column)."""
        result = _parse_status_line("M  src/main.py")
        assert result is not None
        status, path, old_path = result
        assert status == "M"
        assert path == "src/main.py"
        assert old_path is None

    def test_modified_unstaged(self):
        """Test parsing unstaged modification (M in second column)."""
        result = _parse_status_line(" M src/main.py")
        assert result is not None
        status, path, old_path = result
        assert status == "M"
        assert path == "src/main.py"

    def test_untracked(self):
        """Test parsing untracked file."""
        result = _parse_status_line("?? new_file.py")
        assert result is not None
        status, path, old_path = result
        assert status == "??"
        assert path == "new_file.py"

    def test_rename(self):
        """Test parsing renamed file."""
        result = _parse_status_line("R  old.py -> new.py")
        assert result is not None
        status, path, old_path = result
        assert status == "R"
        assert path == "new.py"
        assert old_path == "old.py"

    def test_added(self):
        """Test parsing added file."""
        result = _parse_status_line("A  new_feature.py")
        assert result is not None
        status, path, _ = result
        assert status == "A"

    def test_deleted(self):
        """Test parsing deleted file."""
        result = _parse_status_line("D  removed.py")
        assert result is not None
        status, path, _ = result
        assert status == "D"

    def test_short_line(self):
        """Test handling too-short lines."""
        assert _parse_status_line("") is None
        assert _parse_status_line("M") is None
        assert _parse_status_line("M ") is None

    def test_merged_space_handling(self):
        """Test handling when Y status is space (appears as single space)."""
        # When Y=' ' (no worktree change), format may appear as "M path"
        # instead of "M  path"
        result = _parse_status_line("M swarm/runtime/engines.py")
        assert result is not None
        status, path, _ = result
        assert status == "M"
        assert path == "swarm/runtime/engines.py"


class TestRunGitCommand:
    """Tests for _run_git_command helper."""

    def test_successful_command(self, tmp_path):
        """Test running successful git command."""
        # Create a git repo
        (tmp_path / ".git").mkdir()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="test output",
                stderr="",
            )
            success, stdout, stderr = _run_git_command(["status"], tmp_path)

        assert success is True
        assert stdout == "test output"
        assert stderr == ""

    def test_failed_command(self, tmp_path):
        """Test handling failed git command."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1,
                stdout="",
                stderr="fatal: not a git repository",
            )
            success, stdout, stderr = _run_git_command(["status"], tmp_path)

        assert success is False
        assert "not a git repository" in stderr

    def test_git_not_found(self, tmp_path):
        """Test handling when git is not installed."""
        with patch("subprocess.run", side_effect=FileNotFoundError()):
            success, stdout, stderr = _run_git_command(["status"], tmp_path)

        assert success is False
        assert "Git not found" in stderr


class TestScanFileChanges:
    """Tests for scan_file_changes_sync function."""

    def test_not_a_git_repo(self, tmp_path):
        """Test scanning a non-git directory."""
        changes = scan_file_changes_sync(tmp_path)
        assert changes.scan_error is not None
        assert "not a git repository" in changes.scan_error.lower()

    def test_clean_repo(self, tmp_path):
        """Test scanning a clean git repo with no changes."""
        with patch("swarm.runtime.diff_scanner._run_git_command") as mock_git:
            # Simulate git commands
            def git_responses(args, cwd, **kwargs):
                if args == ["rev-parse", "--git-dir"]:
                    return True, ".git", ""
                elif args[0] == "diff":
                    return True, "", ""  # No changes
                elif args[0] == "status":
                    return True, "", ""  # No changes
                return True, "", ""

            mock_git.side_effect = git_responses

            changes = scan_file_changes_sync(tmp_path)
            assert changes.scan_error is None
            assert not changes.has_changes

    def test_with_modifications(self, tmp_path):
        """Test scanning repo with modifications."""
        with patch("swarm.runtime.diff_scanner._run_git_command") as mock_git:
            def git_responses(args, cwd, **kwargs):
                if args == ["rev-parse", "--git-dir"]:
                    return True, ".git", ""
                elif args[0:2] == ["diff", "HEAD"]:
                    return True, "10\t5\tsrc/main.py\n", ""
                elif args[0] == "status":
                    return True, " M src/main.py\n?? new_file.py\n", ""
                return True, "", ""

            mock_git.side_effect = git_responses

            changes = scan_file_changes_sync(tmp_path)
            assert changes.scan_error is None
            assert changes.has_changes
            assert len(changes.files) == 1
            assert changes.files[0].path == "src/main.py"
            assert changes.files[0].insertions == 10
            assert changes.files[0].deletions == 5
            assert "new_file.py" in changes.untracked


class TestCreateFileChangesEvent:
    """Tests for create_file_changes_event function."""

    def test_event_structure(self):
        """Test that created event has correct structure."""
        changes = FileChanges(
            files=[FileDiff(path="a.py", status="M", insertions=5, deletions=2)],
            total_insertions=5,
            total_deletions=2,
        )

        event = create_file_changes_event(
            run_id="run-123",
            flow_key="build",
            step_id="1",
            agent_key="code-implementer",
            changes=changes,
        )

        assert event["run_id"] == "run-123"
        assert event["kind"] == "file_changes"
        assert event["flow_key"] == "build"
        assert event["step_id"] == "1"
        assert event["agent_key"] == "code-implementer"
        assert "ts" in event
        assert "payload" in event
        assert event["payload"]["total_insertions"] == 5
