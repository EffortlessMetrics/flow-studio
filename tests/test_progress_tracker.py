"""
Tests for the ProgressTracker (Elephant Protocol) module.

The Elephant Protocol: Progress is measured by the derivative (velocity),
not the budget. If error signatures remain identical, velocity is zero
and we're stalled. If they change, velocity is positive and we continue.
"""

import pytest
from datetime import datetime

from swarm.runtime.progress_tracker import (
    ProgressTracker,
    StallInfo,
    compute_error_signature,
    normalize_error_output,
    extract_error_category,
    build_stall_context,
    should_suggest_sidequest,
    create_tracker,
    tracker_to_dict,
    tracker_from_dict,
    stall_info_to_dict,
    stall_info_from_dict,
)


class TestNormalization:
    """Tests for error output normalization."""

    def test_normalize_removes_timestamps(self):
        """Timestamps should be removed from normalized output."""
        error = "2024-01-15T10:30:45 ERROR: Something failed at 2024-01-15 11:00:00"
        normalized = normalize_error_output(error)
        assert "2024-01-15" not in normalized
        assert "10:30:45" not in normalized

    def test_normalize_removes_line_numbers(self):
        """Line numbers should be removed from normalized output."""
        error = "Error at line 42, column 15:23"
        normalized = normalize_error_output(error)
        assert "line 42" not in normalized.lower()
        assert ":15:23" not in normalized

    def test_normalize_removes_memory_addresses(self):
        """Memory addresses should be removed from normalized output."""
        error = "Object at 0x7f8b4c5d6e00 crashed"
        normalized = normalize_error_output(error)
        assert "0x7f8b4c5d6e00" not in normalized

    def test_normalize_removes_uuids(self):
        """UUIDs should be removed from normalized output."""
        error = "Run 123e4567-e89b-12d3-a456-426614174000 failed"
        normalized = normalize_error_output(error)
        assert "123e4567-e89b-12d3-a456-426614174000" not in normalized

    def test_normalize_collapses_whitespace(self):
        """Multiple whitespace should be collapsed to single space."""
        error = "Error    with   multiple    spaces"
        normalized = normalize_error_output(error)
        assert "    " not in normalized
        assert "  " not in normalized

    def test_normalize_lowercases(self):
        """Output should be lowercased for comparison."""
        error = "TypeError: CANNOT Find Attribute"
        normalized = normalize_error_output(error)
        assert normalized == normalized.lower()

    def test_normalize_strips_whitespace(self):
        """Leading/trailing whitespace should be stripped."""
        error = "  Error message  \n\t"
        normalized = normalize_error_output(error)
        assert not normalized.startswith(" ")
        assert not normalized.endswith(" ")


class TestSignatureComputation:
    """Tests for error signature computation."""

    def test_identical_errors_same_signature(self):
        """Identical errors should produce the same signature."""
        error1 = "TypeError: foo has no attribute 'bar'"
        error2 = "TypeError: foo has no attribute 'bar'"
        sig1 = compute_error_signature(error1)
        sig2 = compute_error_signature(error2)
        assert sig1 == sig2

    def test_different_errors_different_signature(self):
        """Different errors should produce different signatures."""
        error1 = "TypeError: foo has no attribute 'bar'"
        error2 = "KeyError: 'baz' not found in dictionary"
        sig1 = compute_error_signature(error1)
        sig2 = compute_error_signature(error2)
        assert sig1 != sig2

    def test_same_error_different_timestamps_same_signature(self):
        """Same error with different timestamps should have same signature."""
        error1 = "2024-01-15T10:00:00 TypeError: foo has no attribute 'bar'"
        error2 = "2024-01-16T15:30:00 TypeError: foo has no attribute 'bar'"
        sig1 = compute_error_signature(error1)
        sig2 = compute_error_signature(error2)
        assert sig1 == sig2

    def test_same_error_different_line_numbers_same_signature(self):
        """Same error with different line numbers should have same signature."""
        error1 = "File test.py, line 42: TypeError: foo"
        error2 = "File test.py, line 99: TypeError: foo"
        sig1 = compute_error_signature(error1)
        sig2 = compute_error_signature(error2)
        assert sig1 == sig2

    def test_signature_length(self):
        """Signature should be 16 characters (truncated SHA256)."""
        error = "Some error message"
        sig = compute_error_signature(error)
        assert len(sig) == 16

    def test_signature_is_hex(self):
        """Signature should be a valid hex string."""
        error = "Some error message"
        sig = compute_error_signature(error)
        int(sig, 16)  # Should not raise ValueError


class TestErrorCategoryExtraction:
    """Tests for error category extraction."""

    def test_extract_type_error(self):
        """TypeError should be categorized correctly."""
        error = "TypeError: 'NoneType' object is not callable"
        category = extract_error_category(error)
        assert category == "type_error"

    def test_extract_import_error(self):
        """ImportError should be categorized correctly."""
        error = "ImportError: No module named 'nonexistent'"
        category = extract_error_category(error)
        assert category == "import_error"

    def test_extract_module_not_found(self):
        """ModuleNotFoundError should be categorized as import error."""
        error = "ModuleNotFoundError: No module named 'foo'"
        category = extract_error_category(error)
        assert category == "import_error"

    def test_extract_assertion_error(self):
        """AssertionError should be categorized correctly."""
        error = "AssertionError: expected True, got False"
        category = extract_error_category(error)
        assert category == "assertion_error"

    def test_extract_test_failure(self):
        """Test failures should be categorized correctly."""
        error = "FAILED test_something - assert x == y"
        category = extract_error_category(error)
        assert category == "test_failure"

    def test_extract_timeout(self):
        """Timeout errors should be categorized correctly."""
        error = "TimeoutError: Connection timeout after 30s"
        category = extract_error_category(error)
        assert category == "timeout"

    def test_extract_unknown(self):
        """Unknown errors should be categorized as unknown."""
        error = "Something went wrong somehow"
        category = extract_error_category(error)
        assert category == "unknown"


class TestProgressTracker:
    """Tests for the ProgressTracker class."""

    def test_create_tracker_default_threshold(self):
        """Creating a tracker should use default threshold of 3."""
        tracker = ProgressTracker()
        assert tracker.stall_threshold == 3

    def test_create_tracker_custom_threshold(self):
        """Creating a tracker should respect custom threshold."""
        tracker = ProgressTracker(stall_threshold=5)
        assert tracker.stall_threshold == 5

    def test_record_iteration_adds_signature(self):
        """Recording an iteration should add a signature."""
        tracker = ProgressTracker()
        assert len(tracker.error_signatures) == 0
        tracker.record_iteration("TypeError: foo")
        assert len(tracker.error_signatures) == 1

    def test_not_stalled_initially(self):
        """Tracker should not be stalled initially."""
        tracker = ProgressTracker()
        assert not tracker.is_stalled()

    def test_not_stalled_with_different_errors(self):
        """Tracker should not be stalled with different errors."""
        tracker = ProgressTracker(stall_threshold=3)
        tracker.record_iteration("TypeError: foo")
        tracker.record_iteration("KeyError: bar")
        tracker.record_iteration("ValueError: baz")
        assert not tracker.is_stalled()

    def test_stalled_with_same_error(self):
        """Tracker should detect stall with same error repeated."""
        tracker = ProgressTracker(stall_threshold=3)
        error = "TypeError: foo has no attribute 'bar'"
        tracker.record_iteration(error)
        tracker.record_iteration(error)
        tracker.record_iteration(error)
        assert tracker.is_stalled()

    def test_stall_count_increments(self):
        """Stall count should increment with repeated signatures."""
        tracker = ProgressTracker(stall_threshold=3)
        error = "TypeError: foo"

        tracker.record_iteration(error)
        assert tracker.get_stall_count() == 1

        tracker.record_iteration(error)
        assert tracker.get_stall_count() == 2

        tracker.record_iteration(error)
        assert tracker.get_stall_count() == 3

    def test_stall_count_resets_with_different_error(self):
        """Stall count should reset when a different error occurs."""
        tracker = ProgressTracker(stall_threshold=3)
        error1 = "TypeError: foo"
        error2 = "KeyError: bar"

        tracker.record_iteration(error1)
        tracker.record_iteration(error1)
        assert tracker.get_stall_count() == 2

        tracker.record_iteration(error2)
        assert tracker.get_stall_count() == 1  # Reset to new error

    def test_velocity_full_when_all_different(self):
        """Velocity should be 1.0 when all errors are different."""
        tracker = ProgressTracker(stall_threshold=3)
        tracker.record_iteration("Error 1")
        tracker.record_iteration("Error 2")
        tracker.record_iteration("Error 3")
        assert tracker.get_velocity() == 1.0

    def test_velocity_zero_when_all_same(self):
        """Velocity should be low when all errors are the same."""
        tracker = ProgressTracker(stall_threshold=3)
        error = "Same error"
        tracker.record_iteration(error)
        tracker.record_iteration(error)
        tracker.record_iteration(error)
        # All 3 are the same, so unique = 1, velocity = 1/3
        assert tracker.get_velocity() == pytest.approx(1/3, rel=0.01)

    def test_velocity_partial(self):
        """Velocity should be partial when some errors are same."""
        tracker = ProgressTracker(stall_threshold=3)
        tracker.record_iteration("Error A")
        tracker.record_iteration("Error B")
        tracker.record_iteration("Error A")
        # 2 unique out of 3, velocity = 2/3
        assert tracker.get_velocity() == pytest.approx(2/3, rel=0.01)

    def test_record_success_breaks_stall(self):
        """Recording success should break a stall pattern."""
        tracker = ProgressTracker(stall_threshold=3)
        error = "Same error"
        tracker.record_iteration(error)
        tracker.record_iteration(error)
        tracker.record_success()
        assert not tracker.is_stalled()

    def test_reset_clears_history(self):
        """Reset should clear all tracking history."""
        tracker = ProgressTracker(stall_threshold=3)
        tracker.record_iteration("Error 1")
        tracker.record_iteration("Error 2")
        tracker.reset()
        assert len(tracker.error_signatures) == 0
        assert not tracker.is_stalled()

    def test_len_returns_iteration_count(self):
        """len(tracker) should return number of iterations."""
        tracker = ProgressTracker()
        assert len(tracker) == 0
        tracker.record_iteration("Error 1")
        assert len(tracker) == 1
        tracker.record_iteration("Error 2")
        assert len(tracker) == 2


class TestStallInfo:
    """Tests for StallInfo dataclass and get_stall_info method."""

    def test_get_stall_info_not_stalled(self):
        """StallInfo should reflect non-stalled state."""
        tracker = ProgressTracker(stall_threshold=3)
        tracker.record_iteration("Error 1")
        tracker.record_iteration("Error 2")
        info = tracker.get_stall_info()

        assert not info.is_stalled
        assert info.stall_count == 1
        assert info.velocity == 1.0  # All different
        assert info.recommendation == "continue"

    def test_get_stall_info_stalled(self):
        """StallInfo should reflect stalled state."""
        tracker = ProgressTracker(stall_threshold=3)
        error = "Same error"
        tracker.record_iteration(error)
        tracker.record_iteration(error)
        tracker.record_iteration(error)
        info = tracker.get_stall_info()

        assert info.is_stalled
        assert info.stall_count == 3
        assert info.recommendation == "investigate"

    def test_get_stall_info_escalate_recommendation(self):
        """StallInfo should recommend escalate when deeply stalled."""
        tracker = ProgressTracker(stall_threshold=3)
        error = "Same error"
        # Stall for 2x threshold
        for _ in range(6):
            tracker.record_iteration(error)
        info = tracker.get_stall_info()

        assert info.is_stalled
        assert info.stall_count == 6
        assert info.recommendation == "escalate"

    def test_stall_info_last_signature(self):
        """StallInfo should include the last signature."""
        tracker = ProgressTracker()
        tracker.record_iteration("Test error")
        info = tracker.get_stall_info()

        assert info.last_signature != ""
        assert len(info.last_signature) == 16


class TestSerialization:
    """Tests for StallInfo and ProgressTracker serialization."""

    def test_stall_info_to_dict(self):
        """StallInfo should serialize to dict correctly."""
        info = StallInfo(
            is_stalled=True,
            stall_count=3,
            velocity=0.333,
            last_signature="abc123",
            recommendation="investigate",
        )
        data = stall_info_to_dict(info)

        assert data["is_stalled"] is True
        assert data["stall_count"] == 3
        assert data["velocity"] == pytest.approx(0.333, rel=0.01)
        assert data["last_signature"] == "abc123"
        assert data["recommendation"] == "investigate"

    def test_stall_info_from_dict(self):
        """StallInfo should deserialize from dict correctly."""
        data = {
            "is_stalled": True,
            "stall_count": 5,
            "velocity": 0.2,
            "last_signature": "def456",
            "recommendation": "escalate",
        }
        info = stall_info_from_dict(data)

        assert info.is_stalled is True
        assert info.stall_count == 5
        assert info.velocity == 0.2
        assert info.last_signature == "def456"
        assert info.recommendation == "escalate"

    def test_tracker_to_dict(self):
        """ProgressTracker should serialize to dict correctly."""
        tracker = ProgressTracker(stall_threshold=5)
        tracker.record_iteration("Error 1")
        tracker.record_iteration("Error 2")

        data = tracker_to_dict(tracker)

        assert data["stall_threshold"] == 5
        assert len(data["error_signatures"]) == 2
        assert len(data["timestamps"]) == 2
        assert len(data["categories"]) == 2

    def test_tracker_from_dict(self):
        """ProgressTracker should deserialize from dict correctly."""
        tracker = ProgressTracker(stall_threshold=4)
        tracker.record_iteration("Error A")
        tracker.record_iteration("Error B")

        data = tracker_to_dict(tracker)
        restored = tracker_from_dict(data)

        assert restored.stall_threshold == 4
        assert len(restored.error_signatures) == 2
        assert restored.error_signatures == tracker.error_signatures

    def test_tracker_roundtrip(self):
        """ProgressTracker should survive serialization roundtrip."""
        tracker = ProgressTracker(stall_threshold=3)
        error = "Repeated error"
        tracker.record_iteration(error)
        tracker.record_iteration(error)
        tracker.record_iteration("Different error")
        tracker.record_iteration(error)

        data = tracker_to_dict(tracker)
        restored = tracker_from_dict(data)

        assert restored.get_stall_count() == tracker.get_stall_count()
        assert restored.get_velocity() == pytest.approx(tracker.get_velocity(), rel=0.01)
        assert restored.is_stalled() == tracker.is_stalled()


class TestRoutingIntegration:
    """Tests for integration with routing driver."""

    def test_build_stall_context(self):
        """build_stall_context should produce correct context for sidequests."""
        tracker = ProgressTracker(stall_threshold=3)
        error = "Same error"
        tracker.record_iteration(error)
        tracker.record_iteration(error)
        tracker.record_iteration(error)

        context = build_stall_context(tracker)

        assert "stall_signals" in context
        assert context["stall_signals"]["is_stalled"] is True
        assert context["stall_signals"]["stall_count"] == 3
        assert context["stall_signals"]["same_failure_signature"] is True

    def test_build_stall_context_not_stalled(self):
        """build_stall_context should work when not stalled."""
        tracker = ProgressTracker(stall_threshold=3)
        tracker.record_iteration("Error 1")
        tracker.record_iteration("Error 2")

        context = build_stall_context(tracker)

        assert context["stall_signals"]["is_stalled"] is False

    def test_should_suggest_sidequest_not_stalled(self):
        """Should not suggest sidequest when not stalled."""
        tracker = ProgressTracker(stall_threshold=3)
        tracker.record_iteration("Error 1")

        should_suggest, reason = should_suggest_sidequest(tracker)
        assert not should_suggest

    def test_should_suggest_sidequest_stalled(self):
        """Should suggest sidequest when stalled."""
        tracker = ProgressTracker(stall_threshold=3)
        error = "Same error"
        tracker.record_iteration(error)
        tracker.record_iteration(error)
        tracker.record_iteration(error)

        should_suggest, reason = should_suggest_sidequest(tracker)
        assert should_suggest
        assert "investigate" in reason.lower() or "stalled" in reason.lower()

    def test_should_suggest_sidequest_escalate(self):
        """Should suggest sidequest with escalation when deeply stalled."""
        tracker = ProgressTracker(stall_threshold=3)
        error = "Same error"
        for _ in range(6):  # 2x threshold
            tracker.record_iteration(error)

        should_suggest, reason = should_suggest_sidequest(tracker)
        assert should_suggest
        assert "escalat" in reason.lower()


class TestFactoryFunction:
    """Tests for factory functions."""

    def test_create_tracker_default(self):
        """create_tracker should create with default threshold."""
        tracker = create_tracker()
        assert tracker.stall_threshold == 3

    def test_create_tracker_custom_threshold(self):
        """create_tracker should respect custom threshold."""
        tracker = create_tracker(stall_threshold=7)
        assert tracker.stall_threshold == 7


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_empty_error_string(self):
        """Empty error string should be handled gracefully."""
        tracker = ProgressTracker()
        tracker.record_iteration("")
        assert len(tracker) == 1

    def test_very_long_error_string(self):
        """Very long error strings should be handled."""
        tracker = ProgressTracker()
        long_error = "x" * 100000  # 100KB error message
        tracker.record_iteration(long_error)
        assert len(tracker) == 1
        assert len(tracker.error_signatures[-1]) == 16  # Still valid signature

    def test_unicode_in_error(self):
        """Unicode characters in errors should be handled."""
        tracker = ProgressTracker()
        tracker.record_iteration("Error: \u2603 snowman failed \U0001F4A5")
        assert len(tracker) == 1

    def test_signature_history(self):
        """get_signature_history should return correct data."""
        tracker = ProgressTracker()
        tracker.record_iteration("Error 1")
        tracker.record_iteration("Error 2")

        history = tracker.get_signature_history()

        assert len(history) == 2
        for sig, category, ts in history:
            assert isinstance(sig, str)
            assert isinstance(category, str)
            assert isinstance(ts, datetime)

    def test_error_category_accessor(self):
        """get_error_category should return most recent category."""
        tracker = ProgressTracker()
        assert tracker.get_error_category() is None

        tracker.record_iteration("ImportError: no module")
        assert tracker.get_error_category() == "import_error"

        tracker.record_iteration("TypeError: not callable")
        assert tracker.get_error_category() == "type_error"

    def test_below_threshold_not_stalled(self):
        """Should not be stalled when below threshold even with same errors."""
        tracker = ProgressTracker(stall_threshold=5)
        error = "Same error"
        tracker.record_iteration(error)
        tracker.record_iteration(error)
        tracker.record_iteration(error)
        tracker.record_iteration(error)
        # Only 4 same errors, threshold is 5
        assert not tracker.is_stalled()

    def test_exactly_at_threshold_is_stalled(self):
        """Should be stalled when exactly at threshold."""
        tracker = ProgressTracker(stall_threshold=5)
        error = "Same error"
        for _ in range(5):
            tracker.record_iteration(error)
        assert tracker.is_stalled()


class TestStallContextIntegration:
    """Tests for StallContext in RoutingExplanation."""

    def test_stall_context_in_routing_explanation(self):
        """StallContext should integrate with RoutingExplanation."""
        from swarm.runtime.types import (
            RoutingExplanation,
            StallContext,
            DecisionType,
            routing_explanation_to_dict,
            routing_explanation_from_dict,
        )

        stall_ctx = StallContext(
            is_stalled=True,
            stall_count=3,
            velocity=0.333,
            last_signature="abc123def456",
            recommendation="investigate",
            triggered_sidequest="clarifier",
        )

        explanation = RoutingExplanation(
            decision_type=DecisionType.EXIT_CONDITION,
            selected_target="clarifier-station",
            stall_context=stall_ctx,
        )

        # Serialize and deserialize
        data = routing_explanation_to_dict(explanation)
        assert "stall_context" in data
        assert data["stall_context"]["is_stalled"] is True
        assert data["stall_context"]["triggered_sidequest"] == "clarifier"

        restored = routing_explanation_from_dict(data)
        assert restored.stall_context is not None
        assert restored.stall_context.is_stalled is True
        assert restored.stall_context.stall_count == 3
        assert restored.stall_context.triggered_sidequest == "clarifier"

    def test_routing_explanation_without_stall_context(self):
        """RoutingExplanation should work without StallContext."""
        from swarm.runtime.types import (
            RoutingExplanation,
            DecisionType,
            routing_explanation_to_dict,
            routing_explanation_from_dict,
        )

        explanation = RoutingExplanation(
            decision_type=DecisionType.DETERMINISTIC,
            selected_target="next-step",
        )

        data = routing_explanation_to_dict(explanation)
        assert "stall_context" not in data

        restored = routing_explanation_from_dict(data)
        assert restored.stall_context is None
