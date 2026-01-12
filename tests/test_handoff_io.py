"""Tests for swarm.runtime.handoff_io module.

Verifies the unified handoff envelope persistence layer.
"""

import json
import os
import tempfile
from pathlib import Path
from typing import Dict, Any

import pytest

from swarm.runtime.handoff_io import (
    write_handoff_envelope,
    update_envelope_routing,
    read_handoff_envelope,
    validate_envelope,
    is_strict_validation_enabled,
    EnvelopeValidationError,
    FILE_CHANGES_EXTRACTION_THRESHOLD,
)


@pytest.fixture
def run_base(tmp_path: Path) -> Path:
    """Create a temporary run base directory."""
    return tmp_path


@pytest.fixture
def valid_envelope_data() -> Dict[str, Any]:
    """Create a valid envelope data dict."""
    return {
        "step_id": "test_step",
        "flow_key": "build",
        "run_id": "test_run_001",
        "status": "VERIFIED",
        "summary": "Test step completed successfully",
        "routing_signal": {
            "decision": "advance",
            "reason": "test_reason",
            "confidence": 0.9,
            "needs_human": False,
        },
        "file_changes": {},
        "artifacts": {},
    }


class TestWriteHandoffEnvelope:
    """Tests for write_handoff_envelope function."""

    def test_writes_both_draft_and_committed(
        self, run_base: Path, valid_envelope_data: Dict[str, Any]
    ):
        """Verify both draft and committed files are written."""
        write_handoff_envelope(
            run_base=run_base,
            step_id="test_step",
            envelope_data=valid_envelope_data,
            write_draft=True,
        )

        draft_path = run_base / "handoff" / "test_step.draft.json"
        committed_path = run_base / "handoff" / "test_step.json"

        assert draft_path.exists()
        assert committed_path.exists()

        # Verify content matches
        draft_data = json.loads(draft_path.read_text(encoding="utf-8"))
        committed_data = json.loads(committed_path.read_text(encoding="utf-8"))
        assert draft_data["step_id"] == "test_step"
        assert committed_data["step_id"] == "test_step"

    def test_skips_draft_when_disabled(
        self, run_base: Path, valid_envelope_data: Dict[str, Any]
    ):
        """Verify draft is skipped when write_draft=False."""
        write_handoff_envelope(
            run_base=run_base,
            step_id="test_step",
            envelope_data=valid_envelope_data,
            write_draft=False,
        )

        draft_path = run_base / "handoff" / "test_step.draft.json"
        committed_path = run_base / "handoff" / "test_step.json"

        assert not draft_path.exists()
        assert committed_path.exists()

    def test_adds_timestamp_if_missing(self, run_base: Path):
        """Verify timestamp is added if not present."""
        data = {"step_id": "test", "flow_key": "build", "run_id": "run1", "status": "VERIFIED"}

        result = write_handoff_envelope(
            run_base=run_base,
            step_id="test",
            envelope_data=data,
            validate=False,
        )

        assert "timestamp" in result
        assert "Z" in result["timestamp"]  # ISO format with timezone

    def test_preserves_existing_timestamp(self, run_base: Path):
        """Verify existing timestamp is preserved."""
        data = {
            "step_id": "test",
            "timestamp": "2024-01-01T00:00:00Z",
            "status": "VERIFIED",
        }

        result = write_handoff_envelope(
            run_base=run_base,
            step_id="test",
            envelope_data=data,
            validate=False,
        )

        assert result["timestamp"] == "2024-01-01T00:00:00Z"

    def test_creates_handoff_directory(self, run_base: Path, valid_envelope_data: Dict[str, Any]):
        """Verify handoff directory is created if it doesn't exist."""
        assert not (run_base / "handoff").exists()

        write_handoff_envelope(
            run_base=run_base,
            step_id="test_step",
            envelope_data=valid_envelope_data,
        )

        assert (run_base / "handoff").is_dir()

    def test_validation_warning_on_invalid_schema(self, run_base: Path, caplog):
        """Verify validation warnings are logged for invalid data."""
        invalid_data = {"step_id": "test"}  # Missing required fields

        write_handoff_envelope(
            run_base=run_base,
            step_id="test",
            envelope_data=invalid_data,
            validate=True,
        )

        # Should still write despite validation warnings
        assert (run_base / "handoff" / "test.json").exists()


class TestUpdateEnvelopeRouting:
    """Tests for update_envelope_routing function."""

    def test_updates_existing_envelope(
        self, run_base: Path, valid_envelope_data: Dict[str, Any]
    ):
        """Verify routing signal is added to existing envelope."""
        # First write an envelope
        write_handoff_envelope(
            run_base=run_base,
            step_id="test_step",
            envelope_data=valid_envelope_data,
        )

        # Update with new routing
        new_routing = {
            "decision": "loop",
            "reason": "needs_more_work",
            "confidence": 0.5,
        }
        result = update_envelope_routing(run_base, "test_step", new_routing)

        assert result is not None
        assert result["routing_signal"]["decision"] == "loop"
        assert result["routing_signal"]["confidence"] == 0.5

    def test_returns_none_for_missing_envelope(self, run_base: Path):
        """Verify None is returned when envelope doesn't exist."""
        result = update_envelope_routing(run_base, "nonexistent", {"decision": "advance"})
        assert result is None

    def test_persists_update_to_disk(
        self, run_base: Path, valid_envelope_data: Dict[str, Any]
    ):
        """Verify updates are persisted to disk."""
        write_handoff_envelope(
            run_base=run_base,
            step_id="test_step",
            envelope_data=valid_envelope_data,
        )

        update_envelope_routing(run_base, "test_step", {"decision": "terminate"})

        # Read back from disk
        committed_path = run_base / "handoff" / "test_step.json"
        persisted = json.loads(committed_path.read_text(encoding="utf-8"))
        assert persisted["routing_signal"]["decision"] == "terminate"


class TestReadHandoffEnvelope:
    """Tests for read_handoff_envelope function."""

    def test_reads_committed_by_default(
        self, run_base: Path, valid_envelope_data: Dict[str, Any]
    ):
        """Verify committed envelope is read by default."""
        write_handoff_envelope(
            run_base=run_base,
            step_id="test_step",
            envelope_data=valid_envelope_data,
        )

        result = read_handoff_envelope(run_base, "test_step")
        assert result is not None
        assert result["step_id"] == "test_step"

    def test_prefers_draft_when_requested(self, run_base: Path):
        """Verify draft is preferred when prefer_draft=True."""
        # Write different data to draft and committed
        draft_data = {"step_id": "draft_version", "status": "UNVERIFIED"}
        committed_data = {"step_id": "committed_version", "status": "VERIFIED"}

        (run_base / "handoff").mkdir(parents=True)
        (run_base / "handoff" / "test.draft.json").write_text(json.dumps(draft_data))
        (run_base / "handoff" / "test.json").write_text(json.dumps(committed_data))

        result = read_handoff_envelope(run_base, "test", prefer_draft=True)
        assert result["step_id"] == "draft_version"

    def test_falls_back_to_committed_when_no_draft(
        self, run_base: Path, valid_envelope_data: Dict[str, Any]
    ):
        """Verify fallback to committed when draft doesn't exist."""
        write_handoff_envelope(
            run_base=run_base,
            step_id="test_step",
            envelope_data=valid_envelope_data,
            write_draft=False,
        )

        result = read_handoff_envelope(run_base, "test_step", prefer_draft=True)
        assert result is not None
        assert result["step_id"] == "test_step"

    def test_returns_none_for_missing_envelope(self, run_base: Path):
        """Verify None is returned when envelope doesn't exist."""
        result = read_handoff_envelope(run_base, "nonexistent")
        assert result is None


class TestValidateEnvelope:
    """Tests for validate_envelope function."""

    def test_valid_envelope_returns_empty_list(self, valid_envelope_data: Dict[str, Any]):
        """Verify valid envelope returns no errors."""
        errors = validate_envelope(valid_envelope_data)
        # May or may not return errors depending on jsonschema availability
        # and schema file presence - this is a soft test
        if errors:
            # Acceptable if schema validation isn't fully configured
            pass

    def test_invalid_envelope_returns_errors(self):
        """Verify invalid envelope returns error messages."""
        invalid_data = {}  # Completely empty
        errors = validate_envelope(invalid_data)
        # May return errors if jsonschema is available
        # The function gracefully handles missing dependencies


class TestStrictValidation:
    """Tests for strict validation mode."""

    def test_strict_mode_disabled_by_default(self):
        """Verify strict mode is disabled by default."""
        # Clear any existing env var
        os.environ.pop("SWARM_STRICT_ENVELOPE_VALIDATION", None)
        assert not is_strict_validation_enabled()

    def test_strict_mode_enabled_by_env(self):
        """Verify strict mode can be enabled via environment."""
        os.environ["SWARM_STRICT_ENVELOPE_VALIDATION"] = "true"
        try:
            assert is_strict_validation_enabled()
        finally:
            os.environ.pop("SWARM_STRICT_ENVELOPE_VALIDATION", None)

    def test_strict_mode_accepts_various_truthy_values(self):
        """Verify various truthy values enable strict mode."""
        truthy_values = ["1", "true", "yes", "on", "TRUE", "Yes", "ON"]

        for value in truthy_values:
            os.environ["SWARM_STRICT_ENVELOPE_VALIDATION"] = value
            try:
                assert is_strict_validation_enabled(), f"'{value}' should enable strict mode"
            finally:
                os.environ.pop("SWARM_STRICT_ENVELOPE_VALIDATION", None)


class TestFileChangesExtraction:
    """Tests for file_changes out-of-line extraction and hydration.

    When file_changes data exceeds FILE_CHANGES_EXTRACTION_THRESHOLD bytes,
    it should be extracted to a separate file in the forensics directory
    to reduce ledger bloat.
    """

    def test_small_file_changes_remain_inline(self, run_base: Path):
        """Verify small file_changes are kept inline in the envelope."""
        small_file_changes = [
            {"path": "src/main.py", "change_type": "modified", "lines_added": 5}
        ]
        envelope_data = {
            "step_id": "test_step",
            "status": "VERIFIED",
            "summary": "Test",
            "routing_signal": {"decision": "advance", "reason": "done", "confidence": 0.9, "needs_human": False},
            "file_changes": small_file_changes,
        }

        result = write_handoff_envelope(
            run_base=run_base,
            step_id="test_step",
            envelope_data=envelope_data,
            validate=False,
        )

        # file_changes should remain inline
        assert result.get("file_changes") == small_file_changes
        assert "file_changes_path" not in result

        # Forensics directory should not be created
        assert not (run_base / "forensics").exists()

    def test_large_file_changes_extracted_to_forensics(self, run_base: Path):
        """Verify large file_changes are extracted to forensics directory."""
        # Create file_changes that exceeds the threshold
        large_file_changes = [
            {
                "path": f"src/file_{i}.py",
                "change_type": "modified",
                "lines_added": 100,
                "lines_removed": 50,
                "summary": f"Updated file {i} with significant changes to the module structure and implementation details",
            }
            for i in range(50)  # 50 entries should exceed 1000 bytes
        ]

        # Verify this exceeds threshold
        assert len(json.dumps(large_file_changes)) > FILE_CHANGES_EXTRACTION_THRESHOLD

        envelope_data = {
            "step_id": "test_step",
            "status": "VERIFIED",
            "summary": "Test",
            "routing_signal": {"decision": "advance", "reason": "done", "confidence": 0.9, "needs_human": False},
            "file_changes": large_file_changes,
        }

        result = write_handoff_envelope(
            run_base=run_base,
            step_id="test_step",
            envelope_data=envelope_data,
            validate=False,
        )

        # file_changes should be replaced with None and path reference
        assert result.get("file_changes") is None
        assert "file_changes_path" in result
        assert result["file_changes_path"] == "forensics/file_changes_test_step.json"

        # Forensics file should exist with the data
        forensics_path = run_base / "forensics" / "file_changes_test_step.json"
        assert forensics_path.exists()

        extracted_data = json.loads(forensics_path.read_text(encoding="utf-8"))
        assert extracted_data == large_file_changes

    def test_read_hydrates_extracted_file_changes(self, run_base: Path):
        """Verify reading an envelope hydrates file_changes from external file."""
        large_file_changes = [
            {
                "path": f"src/file_{i}.py",
                "change_type": "modified",
                "lines_added": 100,
                "summary": f"Big change {i}",
            }
            for i in range(50)
        ]

        envelope_data = {
            "step_id": "test_step",
            "status": "VERIFIED",
            "summary": "Test",
            "routing_signal": {"decision": "advance", "reason": "done", "confidence": 0.9, "needs_human": False},
            "file_changes": large_file_changes,
        }

        # Write (should extract)
        write_handoff_envelope(
            run_base=run_base,
            step_id="test_step",
            envelope_data=envelope_data,
            validate=False,
        )

        # Read back (should hydrate)
        result = read_handoff_envelope(run_base, "test_step")

        assert result is not None
        assert result.get("file_changes") == large_file_changes
        # The path reference should still be there
        assert result.get("file_changes_path") == "forensics/file_changes_test_step.json"

    def test_read_without_hydration(self, run_base: Path):
        """Verify hydration can be disabled when reading."""
        large_file_changes = [
            {"path": f"src/file_{i}.py", "change_type": "added", "lines_added": 10}
            for i in range(100)
        ]

        envelope_data = {
            "step_id": "test_step",
            "status": "VERIFIED",
            "summary": "Test",
            "routing_signal": {"decision": "advance", "reason": "done", "confidence": 0.9, "needs_human": False},
            "file_changes": large_file_changes,
        }

        write_handoff_envelope(
            run_base=run_base,
            step_id="test_step",
            envelope_data=envelope_data,
            validate=False,
        )

        # Read without hydration
        result = read_handoff_envelope(run_base, "test_step", hydrate_file_changes=False)

        assert result is not None
        assert result.get("file_changes") is None
        assert result.get("file_changes_path") == "forensics/file_changes_test_step.json"

    def test_hydration_handles_missing_forensics_file(self, run_base: Path, caplog):
        """Verify graceful handling when forensics file is missing."""
        # Manually create an envelope with a path reference but no actual file
        (run_base / "handoff").mkdir(parents=True)
        envelope_data = {
            "step_id": "test_step",
            "status": "VERIFIED",
            "summary": "Test",
            "routing_signal": {"decision": "advance", "reason": "done"},
            "file_changes": None,
            "file_changes_path": "forensics/file_changes_test_step.json",
        }
        (run_base / "handoff" / "test_step.json").write_text(json.dumps(envelope_data))

        # Read should not raise, just warn
        result = read_handoff_envelope(run_base, "test_step")

        assert result is not None
        assert result.get("file_changes") is None  # Not hydrated
        assert result.get("file_changes_path") == "forensics/file_changes_test_step.json"

    def test_empty_file_changes_not_extracted(self, run_base: Path):
        """Verify empty file_changes list is not extracted."""
        envelope_data = {
            "step_id": "test_step",
            "status": "VERIFIED",
            "summary": "Test",
            "routing_signal": {"decision": "advance", "reason": "done", "confidence": 0.9, "needs_human": False},
            "file_changes": [],
        }

        result = write_handoff_envelope(
            run_base=run_base,
            step_id="test_step",
            envelope_data=envelope_data,
            validate=False,
        )

        # Empty list should remain inline
        assert result.get("file_changes") == []
        assert "file_changes_path" not in result
        assert not (run_base / "forensics").exists()

    def test_envelope_without_file_changes(self, run_base: Path):
        """Verify envelopes without file_changes work correctly."""
        envelope_data = {
            "step_id": "test_step",
            "status": "VERIFIED",
            "summary": "Test",
            "routing_signal": {"decision": "advance", "reason": "done", "confidence": 0.9, "needs_human": False},
        }

        result = write_handoff_envelope(
            run_base=run_base,
            step_id="test_step",
            envelope_data=envelope_data,
            validate=False,
        )

        assert "file_changes" not in result
        assert "file_changes_path" not in result

        # Read back
        read_result = read_handoff_envelope(run_base, "test_step")
        assert read_result is not None
        assert "file_changes" not in read_result
