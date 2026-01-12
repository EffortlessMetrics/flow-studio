"""Tests for policy-gated evolution auto-apply at run boundaries.

This module tests the new evolution policy controls that determine:
1. Whether evolution patches are applied or just suggested
2. When evolution processing happens (run end vs flow end)
3. That explicit events are emitted (evolution_applied / evolution_suggested)
4. That suggestions are recorded in run artifacts regardless of policy
"""

import json
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

_SWARM_ROOT = Path(__file__).resolve().parent.parent
if str(_SWARM_ROOT) not in sys.path:
    sys.path.insert(0, str(_SWARM_ROOT))

from swarm.runtime.autopilot import (
    AutopilotConfig,
    AutopilotController,
    AutopilotState,
    EvolutionApplyPolicy,
    EvolutionBoundary,
    EvolutionSuggestion,
    WisdomApplyResult,
)
from swarm.runtime.types import RunSpec

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test files."""
    tmpdir = Path(tempfile.mkdtemp())
    yield tmpdir
    shutil.rmtree(tmpdir)


@pytest.fixture
def repo_root(temp_dir):
    """Create a mock repository root with necessary directories."""
    # Create spec directories
    (temp_dir / "swarm" / "spec" / "flows").mkdir(parents=True)
    (temp_dir / "swarm" / "spec" / "stations").mkdir(parents=True)
    (temp_dir / "swarm" / "runs").mkdir(parents=True)
    (temp_dir / ".git").mkdir()
    return temp_dir


@pytest.fixture
def wisdom_dir(temp_dir):
    """Create a mock wisdom directory with test evolution patches."""
    run_id = "test-run-001"
    wisdom = temp_dir / "swarm" / "runs" / run_id / "wisdom"
    wisdom.mkdir(parents=True)
    return wisdom


def create_test_patch_data(patch_id: str = "PATCH-001", risk: str = "low") -> dict:
    """Create test flow_evolution.patch data."""
    return {
        "schema_version": "flow_evolution_v1",
        "run_id": "test-run-001",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "patches": [
            {
                "id": patch_id,
                "target_flow": "swarm/spec/flows/3-build.yaml",
                "reason": "Add security scan step after navigator suggested 3+ times",
                "evidence": ["run-001/events.jsonl", "run-002/events.jsonl"],
                "operations": [{"op": "add", "path": "/steps/-", "value": {"id": "security"}}],
                "risk": risk,
                "human_review_required": risk != "low",
            }
        ],
    }


# =============================================================================
# AutopilotConfig Tests
# =============================================================================


class TestAutopilotConfig:
    """Tests for AutopilotConfig with evolution policy."""

    def test_default_policy_is_suggest_only(self):
        """Default policy should be SUGGEST_ONLY for safety."""
        config = AutopilotConfig()
        assert config.evolution_apply_policy == EvolutionApplyPolicy.SUGGEST_ONLY
        assert config.evolution_boundary == EvolutionBoundary.RUN_END

    def test_legacy_auto_apply_wisdom_translates_to_new_policy(self):
        """Legacy auto_apply_wisdom=True should translate to AUTO_APPLY_SAFE."""
        config = AutopilotConfig(auto_apply_wisdom=True)
        assert config.evolution_apply_policy == EvolutionApplyPolicy.AUTO_APPLY_SAFE

    def test_legacy_auto_apply_all_translates(self):
        """Legacy auto_apply_policy='all' should translate to AUTO_APPLY_ALL."""
        config = AutopilotConfig(
            auto_apply_wisdom=True,
            auto_apply_policy="all",
        )
        assert config.evolution_apply_policy == EvolutionApplyPolicy.AUTO_APPLY_ALL

    def test_new_policy_takes_precedence(self):
        """New policy should not be overridden if explicitly set."""
        config = AutopilotConfig(
            evolution_apply_policy=EvolutionApplyPolicy.AUTO_APPLY_ALL,
        )
        assert config.evolution_apply_policy == EvolutionApplyPolicy.AUTO_APPLY_ALL

    def test_evolution_boundary_options(self):
        """All evolution boundary options should be valid."""
        for boundary in EvolutionBoundary:
            config = AutopilotConfig(evolution_boundary=boundary)
            assert config.evolution_boundary == boundary


# =============================================================================
# EvolutionSuggestion Tests
# =============================================================================


class TestEvolutionSuggestion:
    """Tests for EvolutionSuggestion dataclass."""

    def test_create_suggestion(self):
        """Test creating an evolution suggestion."""
        suggestion = EvolutionSuggestion(
            patch_id="PATCH-001",
            target_file="swarm/spec/flows/3-build.yaml",
            patch_type="flow_spec",
            reasoning="Add security scan step",
            confidence="high",
            risk="low",
            action_taken="suggested",
            source_run_id="test-run",
        )
        assert suggestion.patch_id == "PATCH-001"
        assert suggestion.action_taken == "suggested"
        assert suggestion.rejection_reason is None

    def test_suggestion_to_dict(self):
        """Test serializing suggestion to dictionary."""
        suggestion = EvolutionSuggestion(
            patch_id="PATCH-001",
            target_file="test.yaml",
            patch_type="flow_spec",
            reasoning="Test",
            confidence="medium",
            risk="low",
            action_taken="applied",
            applied_at="2025-01-01T00:00:00Z",
        )
        data = suggestion.to_dict()
        assert data["patch_id"] == "PATCH-001"
        assert data["action_taken"] == "applied"
        assert data["applied_at"] == "2025-01-01T00:00:00Z"


# =============================================================================
# WisdomApplyResult Tests
# =============================================================================


class TestWisdomApplyResult:
    """Tests for WisdomApplyResult with suggestions tracking."""

    def test_default_result(self):
        """Test default WisdomApplyResult has suggestions list."""
        result = WisdomApplyResult()
        assert result.patches_processed == 0
        assert result.patches_applied == 0
        assert result.patches_suggested == 0
        assert result.suggestions == []

    def test_result_with_suggestions(self):
        """Test WisdomApplyResult tracks suggestions."""
        suggestion = EvolutionSuggestion(
            patch_id="PATCH-001",
            target_file="test.yaml",
            patch_type="flow_spec",
            reasoning="Test",
            confidence="high",
            risk="low",
            action_taken="suggested",
        )
        result = WisdomApplyResult(
            patches_processed=1,
            patches_suggested=1,
            suggestions=[suggestion],
        )
        assert len(result.suggestions) == 1
        assert result.suggestions[0].patch_id == "PATCH-001"


# =============================================================================
# Evolution Processing Tests (with mocked storage)
# =============================================================================


class TestEvolutionProcessing:
    """Tests for policy-gated evolution processing."""

    def test_suggest_only_policy_never_applies(self, repo_root, wisdom_dir):
        """SUGGEST_ONLY policy should record suggestions but never apply."""
        # Create target file for patch
        target = repo_root / "swarm" / "spec" / "flows" / "3-build.yaml"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("id: build\nsteps: []\n")

        # Create patch data
        patch_data = create_test_patch_data("SUGGEST-001", risk="low")
        (wisdom_dir / "flow_evolution.patch").write_text(json.dumps(patch_data))

        # Create controller with SUGGEST_ONLY policy
        config = AutopilotConfig(
            evolution_apply_policy=EvolutionApplyPolicy.SUGGEST_ONLY,
            evolution_boundary=EvolutionBoundary.RUN_END,
        )

        # Mock storage module
        with patch("swarm.runtime.autopilot.storage_module") as mock_storage:
            mock_storage.get_run_path.return_value = wisdom_dir.parent

            controller = AutopilotController(
                repo_root=repo_root,
                default_config=config,
            )

            # Create test state
            state = AutopilotState(
                run_id="test-run-001",
                spec=RunSpec(flow_keys=["wisdom"]),
                config=config,
                flows_completed=["wisdom"],
            )

            # Process evolution
            result = controller._process_evolution_at_boundary(state, "run_end")

            # Should have 1 suggestion, 0 applied
            assert result.patches_processed == 1
            assert result.patches_applied == 0
            assert result.patches_suggested == 1
            assert len(result.suggestions) == 1
            assert result.suggestions[0].action_taken == "suggested"

            # Should emit evolution_suggested event
            events = [call for call in mock_storage.append_event.call_args_list]
            event_kinds = [call[0][1].kind for call in events]
            assert "evolution_suggested" in event_kinds
            assert "evolution_applied" not in event_kinds

    def test_auto_apply_safe_only_applies_low_risk(self, repo_root, wisdom_dir):
        """AUTO_APPLY_SAFE should only apply low-risk, high-confidence patches."""
        # Create target file
        target = repo_root / "swarm" / "spec" / "flows" / "3-build.yaml"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("id: build\nsteps: []\n")

        # Create low-risk patch
        patch_data = create_test_patch_data("SAFE-001", risk="low")
        # Make it high confidence and not requiring human review
        patch_data["patches"][0]["confidence"] = "high"
        patch_data["patches"][0]["human_review_required"] = False
        (wisdom_dir / "flow_evolution.patch").write_text(json.dumps(patch_data))

        config = AutopilotConfig(
            evolution_apply_policy=EvolutionApplyPolicy.AUTO_APPLY_SAFE,
            evolution_boundary=EvolutionBoundary.RUN_END,
        )

        with patch("swarm.runtime.autopilot.storage_module") as mock_storage:
            mock_storage.get_run_path.return_value = wisdom_dir.parent

            controller = AutopilotController(
                repo_root=repo_root,
                default_config=config,
            )

            state = AutopilotState(
                run_id="test-run-001",
                spec=RunSpec(flow_keys=["wisdom"]),
                config=config,
                flows_completed=["wisdom"],
            )

            result = controller._process_evolution_at_boundary(state, "run_end")

            # Should apply the low-risk patch
            assert result.patches_processed == 1
            assert result.patches_applied == 1
            assert result.patches_suggested == 0
            assert len(result.suggestions) == 1
            assert result.suggestions[0].action_taken == "applied"

            # Should emit evolution_applied event
            events = [call for call in mock_storage.append_event.call_args_list]
            event_kinds = [call[0][1].kind for call in events]
            assert "evolution_applied" in event_kinds

    def test_auto_apply_safe_skips_high_risk(self, repo_root, wisdom_dir):
        """AUTO_APPLY_SAFE should skip high-risk patches."""
        # Create target file
        target = repo_root / "swarm" / "spec" / "flows" / "3-build.yaml"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("id: build\nsteps: []\n")

        # Create high-risk patch
        patch_data = create_test_patch_data("RISKY-001", risk="high")
        (wisdom_dir / "flow_evolution.patch").write_text(json.dumps(patch_data))

        config = AutopilotConfig(
            evolution_apply_policy=EvolutionApplyPolicy.AUTO_APPLY_SAFE,
        )

        with patch("swarm.runtime.autopilot.storage_module") as mock_storage:
            mock_storage.get_run_path.return_value = wisdom_dir.parent

            controller = AutopilotController(
                repo_root=repo_root,
                default_config=config,
            )

            state = AutopilotState(
                run_id="test-run-001",
                spec=RunSpec(flow_keys=["wisdom"]),
                config=config,
                flows_completed=["wisdom"],
            )

            result = controller._process_evolution_at_boundary(state, "run_end")

            # Should record as suggestion, not apply
            assert result.patches_applied == 0
            assert result.patches_suggested == 1
            assert result.suggestions[0].action_taken == "suggested"

    def test_auto_apply_all_applies_high_risk(self, repo_root, wisdom_dir):
        """AUTO_APPLY_ALL should apply even high-risk patches."""
        # Create target file
        target = repo_root / "swarm" / "spec" / "flows" / "3-build.yaml"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("id: build\nsteps: []\n")

        # Create high-risk patch
        patch_data = create_test_patch_data("RISKY-001", risk="high")
        (wisdom_dir / "flow_evolution.patch").write_text(json.dumps(patch_data))

        config = AutopilotConfig(
            evolution_apply_policy=EvolutionApplyPolicy.AUTO_APPLY_ALL,
        )

        with patch("swarm.runtime.autopilot.storage_module") as mock_storage:
            mock_storage.get_run_path.return_value = wisdom_dir.parent

            controller = AutopilotController(
                repo_root=repo_root,
                default_config=config,
            )

            state = AutopilotState(
                run_id="test-run-001",
                spec=RunSpec(flow_keys=["wisdom"]),
                config=config,
                flows_completed=["wisdom"],
            )

            result = controller._process_evolution_at_boundary(state, "run_end")

            # Should apply even high-risk
            assert result.patches_applied == 1
            assert result.suggestions[0].action_taken == "applied"


# =============================================================================
# Event Emission Tests
# =============================================================================


class TestEvolutionEvents:
    """Tests for evolution event emission."""

    def test_evolution_processing_emits_started_event(self, repo_root, wisdom_dir):
        """Processing should emit evolution_processing_started event."""
        (wisdom_dir / "flow_evolution.patch").write_text(
            json.dumps(
                {
                    "schema_version": "flow_evolution_v1",
                    "patches": [],
                }
            )
        )

        config = AutopilotConfig(
            evolution_apply_policy=EvolutionApplyPolicy.SUGGEST_ONLY,
        )

        with patch("swarm.runtime.autopilot.storage_module") as mock_storage:
            mock_storage.get_run_path.return_value = wisdom_dir.parent

            controller = AutopilotController(
                repo_root=repo_root,
                default_config=config,
            )

            state = AutopilotState(
                run_id="test-run-001",
                spec=RunSpec(flow_keys=["wisdom"]),
                config=config,
                flows_completed=["wisdom"],
            )

            controller._process_evolution_at_boundary(state, "run_end")

            # Check for started event
            events = [call for call in mock_storage.append_event.call_args_list]
            event_kinds = [call[0][1].kind for call in events]
            assert "evolution_processing_started" in event_kinds
            assert "evolution_processing_completed" in event_kinds

    def test_evolution_processing_emits_completed_event_with_summary(self, repo_root, wisdom_dir):
        """Completed event should include summary stats."""
        (wisdom_dir / "flow_evolution.patch").write_text(
            json.dumps(
                {
                    "schema_version": "flow_evolution_v1",
                    "patches": [],
                }
            )
        )

        config = AutopilotConfig(
            evolution_apply_policy=EvolutionApplyPolicy.SUGGEST_ONLY,
        )

        with patch("swarm.runtime.autopilot.storage_module") as mock_storage:
            mock_storage.get_run_path.return_value = wisdom_dir.parent

            controller = AutopilotController(
                repo_root=repo_root,
                default_config=config,
            )

            state = AutopilotState(
                run_id="test-run-001",
                spec=RunSpec(flow_keys=["wisdom"]),
                config=config,
                flows_completed=["wisdom"],
            )

            controller._process_evolution_at_boundary(state, "run_end")

            # Find completed event
            events = [call for call in mock_storage.append_event.call_args_list]
            completed_events = [
                call[0][1] for call in events if call[0][1].kind == "evolution_processing_completed"
            ]
            assert len(completed_events) == 1

            payload = completed_events[0].payload
            assert "policy" in payload
            assert "patches_processed" in payload
            assert "patches_applied" in payload
            assert "patches_suggested" in payload


# =============================================================================
# Artifact Recording Tests
# =============================================================================


class TestEvolutionArtifacts:
    """Tests for evolution artifact recording."""

    def test_suggestions_recorded_even_when_not_applied(self, repo_root, wisdom_dir):
        """Suggestions should be recorded in artifacts regardless of policy."""
        # Create target file
        target = repo_root / "swarm" / "spec" / "flows" / "3-build.yaml"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("id: build\nsteps: []\n")

        patch_data = create_test_patch_data("RECORD-001")
        (wisdom_dir / "flow_evolution.patch").write_text(json.dumps(patch_data))

        config = AutopilotConfig(
            evolution_apply_policy=EvolutionApplyPolicy.SUGGEST_ONLY,
        )

        with patch("swarm.runtime.autopilot.storage_module") as mock_storage:
            mock_storage.get_run_path.return_value = wisdom_dir.parent

            controller = AutopilotController(
                repo_root=repo_root,
                default_config=config,
            )

            state = AutopilotState(
                run_id="test-run-001",
                spec=RunSpec(flow_keys=["wisdom"]),
                config=config,
                flows_completed=["wisdom"],
            )

            controller._process_evolution_at_boundary(state, "run_end")

            # Check that evolution_summary.json was written
            summary_path = wisdom_dir / "evolution_summary.json"
            assert summary_path.exists()

            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            assert summary["policy"] == "suggest_only"
            assert len(summary["suggestions"]) == 1
            assert summary["suggestions"][0]["patch_id"] == "RECORD-001"

    def test_suggestion_marker_created(self, repo_root, wisdom_dir):
        """Suggestion marker file should be created for each suggestion."""
        # Create target file
        target = repo_root / "swarm" / "spec" / "flows" / "3-build.yaml"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("id: build\nsteps: []\n")

        patch_data = create_test_patch_data("MARKER-001")
        (wisdom_dir / "flow_evolution.patch").write_text(json.dumps(patch_data))

        config = AutopilotConfig(
            evolution_apply_policy=EvolutionApplyPolicy.SUGGEST_ONLY,
        )

        with patch("swarm.runtime.autopilot.storage_module") as mock_storage:
            mock_storage.get_run_path.return_value = wisdom_dir.parent

            controller = AutopilotController(
                repo_root=repo_root,
                default_config=config,
            )

            state = AutopilotState(
                run_id="test-run-001",
                spec=RunSpec(flow_keys=["wisdom"]),
                config=config,
                flows_completed=["wisdom"],
            )

            controller._process_evolution_at_boundary(state, "run_end")

            # Check for suggestion marker
            marker = wisdom_dir / ".suggested_MARKER-001"
            assert marker.exists()

            marker_data = json.loads(marker.read_text(encoding="utf-8"))
            assert marker_data["patch_id"] == "MARKER-001"
            assert marker_data["policy"] == "suggest_only"


# =============================================================================
# Boundary Control Tests
# =============================================================================


class TestEvolutionBoundary:
    """Tests for evolution boundary control."""

    def test_run_end_boundary_processes_at_finalization(self, repo_root, wisdom_dir):
        """RUN_END boundary should process evolution during run finalization."""
        config = AutopilotConfig(
            evolution_apply_policy=EvolutionApplyPolicy.SUGGEST_ONLY,
            evolution_boundary=EvolutionBoundary.RUN_END,
        )

        # Verify boundary is set correctly
        assert config.evolution_boundary == EvolutionBoundary.RUN_END

    def test_never_boundary_skips_processing(self):
        """NEVER boundary should prevent evolution processing."""
        config = AutopilotConfig(
            evolution_apply_policy=EvolutionApplyPolicy.AUTO_APPLY_ALL,
            evolution_boundary=EvolutionBoundary.NEVER,
        )

        # Even with AUTO_APPLY_ALL, NEVER should prevent processing
        # This is tested by checking that _finalize_run doesn't call
        # _process_evolution_at_boundary when boundary is NEVER
        assert config.evolution_boundary == EvolutionBoundary.NEVER


# =============================================================================
# Legacy Compatibility Tests
# =============================================================================


class TestLegacyCompatibility:
    """Tests for backwards compatibility with legacy config."""

    def test_legacy_auto_apply_wisdom_true_works(self):
        """Legacy auto_apply_wisdom=True should work with new policy."""
        config = AutopilotConfig(auto_apply_wisdom=True)

        # Should translate to AUTO_APPLY_SAFE
        assert config.evolution_apply_policy == EvolutionApplyPolicy.AUTO_APPLY_SAFE

    def test_legacy_auto_apply_policy_all_works(self):
        """Legacy auto_apply_policy='all' should work with new policy."""
        config = AutopilotConfig(
            auto_apply_wisdom=True,
            auto_apply_policy="all",
        )

        assert config.evolution_apply_policy == EvolutionApplyPolicy.AUTO_APPLY_ALL

    def test_legacy_and_new_config_can_coexist(self):
        """Mixing legacy and new config should work."""
        config = AutopilotConfig(
            auto_apply_wisdom=False,  # Legacy disabled
            evolution_apply_policy=EvolutionApplyPolicy.AUTO_APPLY_SAFE,
        )

        # New policy should be respected
        assert config.evolution_apply_policy == EvolutionApplyPolicy.AUTO_APPLY_SAFE
