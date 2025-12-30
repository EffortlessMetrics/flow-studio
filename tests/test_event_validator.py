"""Tests for event stream contract validation.

These tests verify that the validator:
1. Detects duplicate seq values
2. Warns on seq gaps
3. Detects missing lifecycle events
4. Detects unpaired step_start/step_end events
5. Handles tool pairing when tool_use_id is available
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from swarm.runtime.event_validator import (
    EventContractViolation,
    validate_event_stream,
    validate_run_from_disk,
)


class TestSeqOrdering:
    """Tests for sequence ordering validation."""

    def test_valid_monotonic_seq(self):
        """Valid monotonic sequence passes validation."""
        events = [
            {"event_id": "evt-1", "seq": 1, "kind": "run_start", "payload": {}},
            {"event_id": "evt-2", "seq": 2, "kind": "step_start", "step_id": "1", "payload": {}},
            {"event_id": "evt-3", "seq": 3, "kind": "step_end", "step_id": "1", "payload": {}},
        ]
        violations = validate_event_stream("test-run", events)

        # No ordering violations
        ordering_violations = [v for v in violations if v.kind == "ordering"]
        assert len(ordering_violations) == 0

    def test_duplicate_seq(self):
        """Duplicate seq values are detected as errors."""
        events = [
            {"event_id": "evt-1", "seq": 1, "kind": "run_start", "payload": {}},
            {"event_id": "evt-2", "seq": 2, "kind": "step_start", "step_id": "1", "payload": {}},
            {"event_id": "evt-3", "seq": 2, "kind": "step_end", "step_id": "1", "payload": {}},  # Duplicate!
        ]
        violations = validate_event_stream("test-run", events)

        duplicates = [v for v in violations if v.kind == "ordering" and "Duplicate" in v.message]
        assert len(duplicates) == 1
        assert duplicates[0].seq == 2
        assert duplicates[0].severity == "error"

    def test_seq_gap_warning(self):
        """Seq gaps are detected as warnings (not errors by default)."""
        events = [
            {"event_id": "evt-1", "seq": 1, "kind": "run_start", "payload": {}},
            {"event_id": "evt-2", "seq": 5, "kind": "step_start", "step_id": "1", "payload": {}},  # Gap!
        ]
        violations = validate_event_stream("test-run", events)

        gaps = [v for v in violations if v.kind == "ordering" and "gap" in v.message]
        assert len(gaps) == 1
        assert gaps[0].severity == "warning"

    def test_seq_gap_error_in_strict_mode(self):
        """Seq gaps become errors in strict mode."""
        events = [
            {"event_id": "evt-1", "seq": 1, "kind": "run_start", "payload": {}},
            {"event_id": "evt-2", "seq": 5, "kind": "step_start", "step_id": "1", "payload": {}},  # Gap!
        ]
        violations = validate_event_stream("test-run", events, strict=True)

        gaps = [v for v in violations if v.kind == "ordering" and "gap" in v.message]
        assert len(gaps) == 1
        assert gaps[0].severity == "error"

    def test_seq_regression(self):
        """Seq going backwards is detected as error."""
        events = [
            {"event_id": "evt-1", "seq": 5, "kind": "run_start", "payload": {}},
            {"event_id": "evt-2", "seq": 3, "kind": "step_start", "step_id": "1", "payload": {}},  # Regression!
        ]
        violations = validate_event_stream("test-run", events)

        regressions = [v for v in violations if v.kind == "ordering" and "regression" in v.message]
        assert len(regressions) == 1
        assert regressions[0].severity == "error"


class TestLifecycleEvents:
    """Tests for lifecycle event validation."""

    def test_missing_run_start(self):
        """Missing run_start/run_created is detected."""
        events = [
            {"event_id": "evt-1", "seq": 1, "kind": "step_start", "step_id": "1", "payload": {}},
            {"event_id": "evt-2", "seq": 2, "kind": "step_end", "step_id": "1", "payload": {}},
        ]
        violations = validate_event_stream("test-run", events)

        missing = [v for v in violations if v.kind == "missing_event"]
        assert len(missing) == 1
        assert "run_" in missing[0].message

    def test_run_start_present(self):
        """run_start present passes validation."""
        events = [
            {"event_id": "evt-1", "seq": 1, "kind": "run_start", "payload": {}},
        ]
        violations = validate_event_stream("test-run", events)

        missing = [v for v in violations if v.kind == "missing_event"]
        assert len(missing) == 0


class TestStepPairing:
    """Tests for step lifecycle pairing validation."""

    def test_valid_step_pairing(self):
        """Matched step_start/step_end passes validation."""
        events = [
            {"event_id": "evt-1", "seq": 1, "kind": "run_start", "payload": {}},
            {"event_id": "evt-2", "seq": 2, "kind": "step_start", "step_id": "1", "payload": {}},
            {"event_id": "evt-3", "seq": 3, "kind": "step_end", "step_id": "1", "payload": {}},
            {"event_id": "evt-4", "seq": 4, "kind": "run_completed", "payload": {}},
        ]
        violations = validate_event_stream("test-run", events)

        pairing = [v for v in violations if v.kind == "pairing"]
        assert len(pairing) == 0

    def test_step_end_without_start(self):
        """step_end without step_start is detected."""
        events = [
            {"event_id": "evt-1", "seq": 1, "kind": "run_start", "payload": {}},
            {"event_id": "evt-2", "seq": 2, "kind": "step_end", "step_id": "1", "payload": {}},  # No start!
        ]
        violations = validate_event_stream("test-run", events)

        pairing = [v for v in violations if v.kind == "pairing"]
        assert len(pairing) == 1
        assert "without step_start" in pairing[0].message

    def test_step_start_without_end_incomplete_run(self):
        """Orphan step_start is NOT flagged if run is not complete."""
        events = [
            {"event_id": "evt-1", "seq": 1, "kind": "run_start", "payload": {}},
            {"event_id": "evt-2", "seq": 2, "kind": "step_start", "step_id": "1", "payload": {}},
            # No step_end, no run_completed
        ]
        violations = validate_event_stream("test-run", events)

        pairing = [v for v in violations if v.kind == "pairing" and "without step_end" in v.message]
        assert len(pairing) == 0  # Not flagged because run is not complete

    def test_step_start_without_end_complete_run(self):
        """Orphan step_start is flagged if run is complete."""
        events = [
            {"event_id": "evt-1", "seq": 1, "kind": "run_start", "payload": {}},
            {"event_id": "evt-2", "seq": 2, "kind": "step_start", "step_id": "1", "payload": {}},
            {"event_id": "evt-3", "seq": 3, "kind": "run_completed", "payload": {}},  # Run complete!
        ]
        violations = validate_event_stream("test-run", events)

        pairing = [v for v in violations if v.kind == "pairing" and "without step_end" in v.message]
        assert len(pairing) == 1

    def test_double_step_start(self):
        """Double step_start without end is detected."""
        events = [
            {"event_id": "evt-1", "seq": 1, "kind": "run_start", "payload": {}},
            {"event_id": "evt-2", "seq": 2, "kind": "step_start", "step_id": "1", "payload": {}},
            {"event_id": "evt-3", "seq": 3, "kind": "step_start", "step_id": "1", "payload": {}},  # Double!
        ]
        violations = validate_event_stream("test-run", events)

        pairing = [v for v in violations if v.kind == "pairing"]
        assert len(pairing) == 1
        assert "without prior step_end" in pairing[0].message


class TestToolPairing:
    """Tests for tool call pairing validation."""

    def test_valid_tool_pairing(self):
        """Matched tool_start/tool_end passes validation."""
        events = [
            {"event_id": "evt-1", "seq": 1, "kind": "run_start", "payload": {}},
            {"event_id": "evt-2", "seq": 2, "kind": "tool_start", "payload": {"tool_use_id": "t1"}},
            {"event_id": "evt-3", "seq": 3, "kind": "tool_end", "payload": {"tool_use_id": "t1"}},
            {"event_id": "evt-4", "seq": 4, "kind": "run_completed", "payload": {}},
        ]
        violations = validate_event_stream("test-run", events)

        tool_pairing = [v for v in violations if v.kind == "pairing" and "tool_" in v.message]
        assert len(tool_pairing) == 0

    def test_tool_end_without_start(self):
        """tool_end without tool_start is detected (warning)."""
        events = [
            {"event_id": "evt-1", "seq": 1, "kind": "run_start", "payload": {}},
            {"event_id": "evt-2", "seq": 2, "kind": "tool_end", "payload": {"tool_use_id": "t1"}},  # No start!
            {"event_id": "evt-3", "seq": 3, "kind": "run_completed", "payload": {}},
        ]
        violations = validate_event_stream("test-run", events)

        tool_pairing = [v for v in violations if v.kind == "pairing" and "tool_end" in v.message]
        assert len(tool_pairing) == 1
        assert tool_pairing[0].severity == "warning"


class TestValidateFromDisk:
    """Tests for disk-based validation."""

    def test_missing_events_file(self, tmp_path):
        """Missing events.jsonl is detected."""
        runs_dir = tmp_path / "runs"
        runs_dir.mkdir()
        run_dir = runs_dir / "test-run"
        run_dir.mkdir()
        # No events.jsonl created

        violations = validate_run_from_disk("test-run", runs_dir)

        assert len(violations) == 1
        assert violations[0].kind == "schema"
        assert "not found" in violations[0].message

    def test_valid_events_file(self, tmp_path):
        """Valid events.jsonl passes validation."""
        runs_dir = tmp_path / "runs"
        runs_dir.mkdir()
        run_dir = runs_dir / "test-run"
        run_dir.mkdir()

        events = [
            {"event_id": "evt-1", "seq": 1, "kind": "run_start", "payload": {}},
            {"event_id": "evt-2", "seq": 2, "kind": "step_start", "step_id": "1", "payload": {}},
            {"event_id": "evt-3", "seq": 3, "kind": "step_end", "step_id": "1", "payload": {}},
            {"event_id": "evt-4", "seq": 4, "kind": "run_completed", "payload": {}},
        ]

        events_file = run_dir / "events.jsonl"
        with events_file.open("w") as f:
            for event in events:
                f.write(json.dumps(event) + "\n")

        violations = validate_run_from_disk("test-run", runs_dir)

        # Should be valid (no violations except possible warnings)
        errors = [v for v in violations if v.severity == "error"]
        assert len(errors) == 0

    def test_malformed_json(self, tmp_path):
        """Malformed JSON in events.jsonl is detected."""
        runs_dir = tmp_path / "runs"
        runs_dir.mkdir()
        run_dir = runs_dir / "test-run"
        run_dir.mkdir()

        events_file = run_dir / "events.jsonl"
        events_file.write_text('{"valid": true}\nthis is not json\n')

        violations = validate_run_from_disk("test-run", runs_dir)

        assert len(violations) == 1
        assert violations[0].kind == "schema"
        assert "Malformed JSON" in violations[0].message
