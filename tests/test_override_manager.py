"""
Test suite for override manager (swarm/tools/override_manager.py).

Tests the ability to create, list, revoke, and check selftest step overrides
with proper audit trail and expiration handling.

Coverage:
1. Creating overrides with valid parameters (step_id, reason, approver)
2. Listing active overrides
3. Revoking overrides
4. Checking if a step has an active override
5. Edge cases: expired overrides, invalid format, missing fields
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

# Import the module under test
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "swarm" / "tools"))
from override_manager import Override, OverrideManager


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def override_file(tmp_path):
    """Create a temporary override config file path."""
    config_dir = tmp_path / ".claude" / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir / "overrides.json"


@pytest.fixture
def manager(override_file):
    """Create an OverrideManager with a temporary config file."""
    return OverrideManager(config_file=override_file)


@pytest.fixture
def manager_with_overrides(manager):
    """Create a manager with some pre-existing overrides."""
    manager.create_override(
        step_id="core-checks",
        reason="Known CI flakiness",
        approver="alice@example.com",
        hours=24
    )
    manager.create_override(
        step_id="policy-tests",
        reason="Policy engine migration",
        approver="bob@example.com",
        hours=48
    )
    return manager


# ============================================================================
# Happy Path Tests - Creating Overrides
# ============================================================================


class TestCreateOverride:
    """Tests for creating overrides with valid parameters."""

    def test_create_override_basic(self, manager):
        """Create an override with minimal required parameters."""
        override = manager.create_override(
            step_id="core-checks",
            reason="CI flakiness during deploy",
            approver="alice@example.com"
        )

        assert override.step_id == "core-checks"
        assert override.reason == "CI flakiness during deploy"
        assert override.approver == "alice@example.com"
        assert override.status == "APPROVED"

    def test_create_override_custom_hours(self, manager):
        """Create an override with custom expiration hours."""
        override = manager.create_override(
            step_id="policy-tests",
            reason="Policy engine maintenance",
            approver="bob@example.com",
            hours=72
        )

        # Parse expiration and verify it's approximately 72 hours from now
        expires = datetime.fromisoformat(override.expires_at)
        created = datetime.fromisoformat(override.created_at)
        duration = expires - created

        assert abs(duration.total_seconds() - (72 * 3600)) < 60  # Within 1 minute

    def test_create_override_persists_to_file(self, manager, override_file):
        """Override is persisted to the config file."""
        manager.create_override(
            step_id="agents-governance",
            reason="Agent migration",
            approver="charlie@example.com"
        )

        # Verify file exists and contains the override
        assert override_file.exists()
        data = json.loads(override_file.read_text(encoding="utf-8"))
        assert "overrides" in data
        assert len(data["overrides"]) == 1
        assert data["overrides"][0]["step_id"] == "agents-governance"

    def test_create_override_sets_timestamps(self, manager):
        """Override has valid ISO format timestamps."""
        before = datetime.now(timezone.utc)
        override = manager.create_override(
            step_id="bdd",
            reason="BDD test refactor",
            approver="dev@example.com"
        )
        after = datetime.now(timezone.utc)

        # Parse timestamps
        created = datetime.fromisoformat(override.created_at)
        expires = datetime.fromisoformat(override.expires_at)

        # Verify created_at is within the test window
        assert before <= created <= after

        # Verify expires_at is ~24 hours after created_at (default)
        duration = expires - created
        assert abs(duration.total_seconds() - (24 * 3600)) < 60

    def test_create_override_revokes_existing(self, manager):
        """Creating a new override for same step_id revokes the old one."""
        # Create first override
        first = manager.create_override(
            step_id="core-checks",
            reason="First reason",
            approver="alice@example.com"
        )

        # Create second override for same step
        second = manager.create_override(
            step_id="core-checks",
            reason="Updated reason",
            approver="bob@example.com"
        )

        # Load all overrides and check statuses
        all_overrides = manager.load_overrides()

        # Should have 2 overrides total
        assert len(all_overrides) == 2

        # First should be REVOKED
        first_loaded = next(o for o in all_overrides if o.reason == "First reason")
        assert first_loaded.status == "REVOKED"

        # Second should be APPROVED
        second_loaded = next(o for o in all_overrides if o.reason == "Updated reason")
        assert second_loaded.status == "APPROVED"


# ============================================================================
# Happy Path Tests - Listing Overrides
# ============================================================================


class TestListOverrides:
    """Tests for listing active overrides."""

    def test_list_empty_when_no_overrides(self, manager):
        """Empty list when no overrides exist."""
        overrides = manager.list_overrides()
        assert overrides == []

    def test_list_returns_active_overrides(self, manager_with_overrides):
        """Returns all active (APPROVED, not expired) overrides."""
        overrides = manager_with_overrides.list_overrides()

        assert len(overrides) == 2
        step_ids = {o.step_id for o in overrides}
        assert step_ids == {"core-checks", "policy-tests"}

    def test_list_excludes_revoked_overrides(self, manager):
        """Revoked overrides are not included in list."""
        # Create and then revoke an override
        manager.create_override(
            step_id="core-checks",
            reason="Temporary",
            approver="alice@example.com"
        )
        manager.revoke_override("core-checks")

        # Create a new active one
        manager.create_override(
            step_id="policy-tests",
            reason="Active override",
            approver="bob@example.com"
        )

        overrides = manager.list_overrides()
        assert len(overrides) == 1
        assert overrides[0].step_id == "policy-tests"

    def test_list_excludes_expired_overrides(self, manager, override_file):
        """Expired overrides are not included in list."""
        # Create an override that's already expired
        now = datetime.now(timezone.utc)
        expired_override = {
            "step_id": "old-step",
            "reason": "Old reason",
            "approver": "old@example.com",
            "created_at": (now - timedelta(hours=48)).isoformat(),
            "expires_at": (now - timedelta(hours=24)).isoformat(),
            "status": "APPROVED"
        }
        override_file.write_text(json.dumps({"overrides": [expired_override]}))

        # Add a fresh active override
        manager.create_override(
            step_id="fresh-step",
            reason="Fresh reason",
            approver="fresh@example.com"
        )

        overrides = manager.list_overrides()
        assert len(overrides) == 1
        assert overrides[0].step_id == "fresh-step"


# ============================================================================
# Happy Path Tests - Revoking Overrides
# ============================================================================


class TestRevokeOverride:
    """Tests for revoking overrides."""

    def test_revoke_existing_override(self, manager):
        """Successfully revoke an existing active override."""
        manager.create_override(
            step_id="core-checks",
            reason="Temporary skip",
            approver="alice@example.com"
        )

        result = manager.revoke_override("core-checks")
        assert result is True

        # Verify it's no longer active
        assert not manager.is_override_active("core-checks")

    def test_revoke_nonexistent_override(self, manager):
        """Revoking a non-existent override returns False."""
        result = manager.revoke_override("nonexistent-step")
        assert result is False

    def test_revoke_already_revoked_override(self, manager):
        """Revoking an already revoked override returns False."""
        manager.create_override(
            step_id="core-checks",
            reason="Temporary skip",
            approver="alice@example.com"
        )
        manager.revoke_override("core-checks")

        # Second revoke should return False
        result = manager.revoke_override("core-checks")
        assert result is False

    def test_revoke_persists_to_file(self, manager, override_file):
        """Revocation is persisted to the config file."""
        manager.create_override(
            step_id="core-checks",
            reason="Temporary",
            approver="alice@example.com"
        )
        manager.revoke_override("core-checks")

        # Reload from file and verify status
        data = json.loads(override_file.read_text(encoding="utf-8"))
        assert data["overrides"][0]["status"] == "REVOKED"


# ============================================================================
# Happy Path Tests - Checking Active Overrides
# ============================================================================


class TestIsOverrideActive:
    """Tests for checking if a step has an active override."""

    def test_active_override_returns_true(self, manager):
        """Returns True for active override."""
        manager.create_override(
            step_id="core-checks",
            reason="CI flakiness",
            approver="alice@example.com"
        )

        assert manager.is_override_active("core-checks") is True

    def test_no_override_returns_false(self, manager):
        """Returns False when no override exists."""
        assert manager.is_override_active("nonexistent-step") is False

    def test_revoked_override_returns_false(self, manager):
        """Returns False for revoked override."""
        manager.create_override(
            step_id="core-checks",
            reason="Temporary",
            approver="alice@example.com"
        )
        manager.revoke_override("core-checks")

        assert manager.is_override_active("core-checks") is False

    def test_expired_override_returns_false(self, manager, override_file):
        """Returns False for expired override."""
        # Create an expired override directly in the file
        now = datetime.now(timezone.utc)
        expired_override = {
            "step_id": "expired-step",
            "reason": "Old reason",
            "approver": "old@example.com",
            "created_at": (now - timedelta(hours=48)).isoformat(),
            "expires_at": (now - timedelta(hours=24)).isoformat(),
            "status": "APPROVED"
        }
        override_file.write_text(json.dumps({"overrides": [expired_override]}))

        assert manager.is_override_active("expired-step") is False


# ============================================================================
# Edge Cases - Expired Overrides
# ============================================================================


class TestExpiredOverrides:
    """Tests for handling expired overrides."""

    def test_override_just_before_expiry(self, manager, override_file):
        """Override active just before expiry time."""
        now = datetime.now(timezone.utc)
        almost_expired = {
            "step_id": "almost-expired",
            "reason": "About to expire",
            "approver": "alice@example.com",
            "created_at": (now - timedelta(hours=23, minutes=59)).isoformat(),
            "expires_at": (now + timedelta(minutes=1)).isoformat(),
            "status": "APPROVED"
        }
        override_file.write_text(json.dumps({"overrides": [almost_expired]}))

        assert manager.is_override_active("almost-expired") is True

    def test_override_just_after_expiry(self, manager, override_file):
        """Override inactive just after expiry time."""
        now = datetime.now(timezone.utc)
        just_expired = {
            "step_id": "just-expired",
            "reason": "Just expired",
            "approver": "alice@example.com",
            "created_at": (now - timedelta(hours=24, minutes=1)).isoformat(),
            "expires_at": (now - timedelta(seconds=1)).isoformat(),
            "status": "APPROVED"
        }
        override_file.write_text(json.dumps({"overrides": [just_expired]}))

        assert manager.is_override_active("just-expired") is False


# ============================================================================
# Edge Cases - Invalid Format
# ============================================================================


class TestInvalidFormat:
    """Tests for handling invalid file formats."""

    def test_corrupted_json_file(self, manager, override_file):
        """Handle corrupted JSON file gracefully."""
        override_file.write_text("not valid json {{{}}")

        # Should return empty list, not raise exception
        overrides = manager.load_overrides()
        assert overrides == []

    def test_missing_overrides_key(self, manager, override_file):
        """Handle JSON without 'overrides' key."""
        override_file.write_text(json.dumps({"other_key": []}))

        overrides = manager.load_overrides()
        assert overrides == []

    def test_invalid_datetime_format(self, manager, override_file):
        """Handle invalid datetime in expires_at."""
        invalid_override = {
            "step_id": "bad-date",
            "reason": "Bad date format",
            "approver": "alice@example.com",
            "created_at": "2024-01-01T00:00:00+00:00",
            "expires_at": "not-a-date",
            "status": "APPROVED"
        }
        override_file.write_text(json.dumps({"overrides": [invalid_override]}))

        # is_override_active should return False (not crash)
        assert manager.is_override_active("bad-date") is False

        # list_overrides should exclude it
        overrides = manager.list_overrides()
        assert len(overrides) == 0

    def test_empty_file(self, manager, override_file):
        """Handle empty config file."""
        override_file.write_text("")

        overrides = manager.load_overrides()
        assert overrides == []


# ============================================================================
# Edge Cases - Missing Fields
# ============================================================================


class TestMissingFields:
    """Tests for handling overrides with missing fields."""

    def test_override_missing_status_field(self, manager, override_file):
        """Override without status field cannot be loaded."""
        incomplete_override = {
            "step_id": "incomplete",
            "reason": "Missing status",
            "approver": "alice@example.com",
            "created_at": "2024-01-01T00:00:00+00:00",
            "expires_at": "2024-01-02T00:00:00+00:00"
            # Missing: "status"
        }
        override_file.write_text(json.dumps({"overrides": [incomplete_override]}))

        # load_overrides should handle this gracefully
        overrides = manager.load_overrides()
        # Should return empty list due to TypeError when creating Override
        assert overrides == []

    def test_config_file_does_not_exist(self, tmp_path):
        """Handle case where config file doesn't exist yet."""
        non_existent = tmp_path / "non_existent" / "overrides.json"
        manager = OverrideManager(config_file=non_existent)

        # Should return empty list, not raise exception
        overrides = manager.load_overrides()
        assert overrides == []

        # Should be able to create override (creates parent dirs)
        override = manager.create_override(
            step_id="new-step",
            reason="First override",
            approver="alice@example.com"
        )
        assert override.step_id == "new-step"
        assert non_existent.exists()


# ============================================================================
# Multiple Overrides Behavior
# ============================================================================


class TestMultipleOverrides:
    """Tests for managing multiple overrides."""

    def test_multiple_step_overrides(self, manager):
        """Can have overrides for multiple different steps."""
        steps = ["core-checks", "policy-tests", "agents-governance", "bdd"]

        for i, step in enumerate(steps):
            manager.create_override(
                step_id=step,
                reason=f"Reason for {step}",
                approver=f"approver-{i}@example.com"
            )

        overrides = manager.list_overrides()
        assert len(overrides) == 4
        step_ids = {o.step_id for o in overrides}
        assert step_ids == set(steps)

    def test_revoke_one_of_many(self, manager):
        """Revoking one override doesn't affect others."""
        manager.create_override("step-1", "Reason 1", "alice@example.com")
        manager.create_override("step-2", "Reason 2", "bob@example.com")
        manager.create_override("step-3", "Reason 3", "charlie@example.com")

        manager.revoke_override("step-2")

        overrides = manager.list_overrides()
        assert len(overrides) == 2
        step_ids = {o.step_id for o in overrides}
        assert step_ids == {"step-1", "step-3"}


# ============================================================================
# Override Dataclass Tests
# ============================================================================


class TestOverrideDataclass:
    """Tests for the Override dataclass."""

    def test_override_creation(self):
        """Override dataclass can be created with all fields."""
        override = Override(
            step_id="test-step",
            reason="Test reason",
            approver="test@example.com",
            created_at="2024-01-01T00:00:00+00:00",
            expires_at="2024-01-02T00:00:00+00:00",
            status="APPROVED"
        )

        assert override.step_id == "test-step"
        assert override.reason == "Test reason"
        assert override.approver == "test@example.com"
        assert override.status == "APPROVED"

    def test_override_equality(self):
        """Two overrides with same fields are equal."""
        override1 = Override(
            step_id="test-step",
            reason="Test reason",
            approver="test@example.com",
            created_at="2024-01-01T00:00:00+00:00",
            expires_at="2024-01-02T00:00:00+00:00",
            status="APPROVED"
        )
        override2 = Override(
            step_id="test-step",
            reason="Test reason",
            approver="test@example.com",
            created_at="2024-01-01T00:00:00+00:00",
            expires_at="2024-01-02T00:00:00+00:00",
            status="APPROVED"
        )

        assert override1 == override2


# ============================================================================
# Default Config Path Tests
# ============================================================================


class TestDefaultConfigPath:
    """Tests for default configuration behavior."""

    def test_default_config_path(self):
        """Manager uses default config path when none specified."""
        manager = OverrideManager()
        assert manager.config_file == Path(".claude/config/overrides.json")

    def test_creates_parent_directories(self, tmp_path):
        """Manager creates parent directories if they don't exist."""
        config_file = tmp_path / "deeply" / "nested" / "path" / "overrides.json"
        manager = OverrideManager(config_file=config_file)

        # Parent directories should be created
        assert config_file.parent.exists()


# ============================================================================
# Audit Trail Tests
# ============================================================================


class TestAuditTrail:
    """Tests for audit trail preservation."""

    def test_all_overrides_preserved_in_file(self, manager, override_file):
        """All override history is preserved, including revoked ones."""
        # Create multiple overrides for same step
        manager.create_override("step-1", "First", "alice@example.com")
        manager.create_override("step-1", "Second", "bob@example.com")
        manager.create_override("step-1", "Third", "charlie@example.com")

        # All three should be in the file
        data = json.loads(override_file.read_text(encoding="utf-8"))
        assert len(data["overrides"]) == 3

        # First two should be REVOKED, third APPROVED
        statuses = [o["status"] for o in data["overrides"]]
        assert statuses == ["REVOKED", "REVOKED", "APPROVED"]

    def test_revoked_overrides_not_deleted(self, manager, override_file):
        """Revoked overrides remain in the file for audit purposes."""
        manager.create_override("step-1", "Original", "alice@example.com")
        manager.revoke_override("step-1")

        # Override should still be in file, just with REVOKED status
        data = json.loads(override_file.read_text(encoding="utf-8"))
        assert len(data["overrides"]) == 1
        assert data["overrides"][0]["status"] == "REVOKED"
        assert data["overrides"][0]["reason"] == "Original"
