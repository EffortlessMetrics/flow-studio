"""Tests for the evolution module.

This module tests the evolution loop functionality including:
- EvolutionPatch dataclass serialization
- Patch generation from wisdom artifacts
- Patch validation
- Patch application (dry-run and actual)
"""

import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
import tempfile
import shutil

import sys
_SWARM_ROOT = Path(__file__).resolve().parent.parent
if str(_SWARM_ROOT) not in sys.path:
    sys.path.insert(0, str(_SWARM_ROOT))

from swarm.runtime.evolution import (
    EvolutionPatch,
    PatchType,
    ConfidenceLevel,
    PatchValidationResult,
    PatchApplicationResult,
    generate_evolution_patch,
    apply_evolution_patch,
    validate_evolution_patch,
    list_pending_patches,
)


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
def wisdom_dir(temp_dir):
    """Create a mock wisdom directory with test artifacts."""
    wisdom = temp_dir / "runs" / "test-run" / "wisdom"
    wisdom.mkdir(parents=True)
    return wisdom


@pytest.fixture
def repo_root(temp_dir):
    """Create a mock repository root."""
    # Create spec directories
    (temp_dir / "swarm" / "spec" / "flows").mkdir(parents=True)
    (temp_dir / "swarm" / "spec" / "stations").mkdir(parents=True)
    (temp_dir / ".git").mkdir()
    return temp_dir


# =============================================================================
# EvolutionPatch Tests
# =============================================================================


class TestEvolutionPatch:
    """Tests for EvolutionPatch dataclass."""

    def test_create_patch(self):
        """Test creating an evolution patch."""
        patch = EvolutionPatch(
            id="FLOW-PATCH-001",
            target_file="swarm/spec/flows/3-build.yaml",
            patch_type=PatchType.FLOW_SPEC,
            content='[{"op": "add", "path": "/steps/-", "value": {"id": "test"}}]',
            confidence=ConfidenceLevel.HIGH,
            reasoning="Navigator suggested adding security scan",
            evidence=["run-001/events.jsonl"],
            source_run_id="test-run",
        )

        assert patch.id == "FLOW-PATCH-001"
        assert patch.patch_type == PatchType.FLOW_SPEC
        assert patch.confidence == ConfidenceLevel.HIGH
        assert patch.human_review_required is True

    def test_patch_to_dict(self):
        """Test serializing patch to dictionary."""
        patch = EvolutionPatch(
            id="PACK-001",
            target_file=".claude/agents/test.md",
            patch_type=PatchType.AGENT_PROMPT,
            content="+ Add this line",
            confidence=ConfidenceLevel.MEDIUM,
            reasoning="Fix typo",
        )

        data = patch.to_dict()

        assert data["id"] == "PACK-001"
        assert data["patch_type"] == "agent_prompt"
        assert data["confidence"] == "medium"
        assert "created_at" in data

    def test_patch_from_dict(self):
        """Test deserializing patch from dictionary."""
        data = {
            "id": "STATION-TUNE-001",
            "target_file": "swarm/spec/stations/code-implementer.yaml",
            "patch_type": "station_spec",
            "content": "+ Add tool",
            "confidence": "high",
            "reasoning": "Improve Rust support",
            "evidence": ["run-123"],
            "risk": "low",
        }

        patch = EvolutionPatch.from_dict(data)

        assert patch.id == "STATION-TUNE-001"
        assert patch.patch_type == PatchType.STATION_SPEC
        assert patch.confidence == ConfidenceLevel.HIGH
        assert patch.evidence == ["run-123"]


# =============================================================================
# Patch Generation Tests
# =============================================================================


class TestGenerateEvolutionPatch:
    """Tests for generate_evolution_patch function."""

    def test_generate_from_flow_evolution_patch(self, wisdom_dir):
        """Test generating patches from flow_evolution.patch file."""
        # Create flow_evolution.patch
        patch_data = {
            "schema_version": "flow_evolution_v1",
            "run_id": "test-run",
            "generated_at": "2025-01-01T00:00:00Z",
            "patches": [
                {
                    "id": "FLOW-PATCH-001",
                    "target_flow": "swarm/spec/flows/3-build.yaml",
                    "reason": "Add security scan step",
                    "evidence": ["run-001/events.jsonl"],
                    "operations": [
                        {"op": "add", "path": "/steps/-", "value": {"id": "security"}}
                    ],
                    "risk": "low",
                    "human_review_required": True,
                }
            ],
        }

        (wisdom_dir / "flow_evolution.patch").write_text(
            json.dumps(patch_data), encoding="utf-8"
        )

        patches = generate_evolution_patch(wisdom_dir)

        assert len(patches) == 1
        assert patches[0].id == "FLOW-PATCH-001"
        assert patches[0].patch_type == PatchType.FLOW_SPEC
        assert patches[0].target_file == "swarm/spec/flows/3-build.yaml"
        assert len(patches[0].operations) == 1

    def test_generate_from_station_tuning(self, wisdom_dir):
        """Test generating patches from station_tuning.md file."""
        # Create station_tuning.md
        content = """# Station Tuning Suggestions (Run test-run)

## Station: code-implementer

**Pattern observed:** Repeated Rust test failures
**Evidence:**
- run-001: tool_telemetry shows cargo test failed
- run-002: tool_telemetry shows cargo test failed

**Proposed tuning:**

File: `swarm/spec/stations/code-implementer.yaml`
```diff
  tools:
    - Read
    - Write
+   - rust-analyzer
```

**Risk:** Low

---

## Station: test-author

**Pattern observed:** (none detected)
"""

        (wisdom_dir / "station_tuning.md").write_text(content, encoding="utf-8")

        patches = generate_evolution_patch(wisdom_dir)

        assert len(patches) == 1
        assert patches[0].id == "STATION-TUNE-001"
        assert patches[0].patch_type == PatchType.STATION_SPEC
        assert "code-implementer" in patches[0].target_file
        assert "+   - rust-analyzer" in patches[0].content

    def test_generate_from_pack_improvements(self, wisdom_dir):
        """Test generating patches from pack_improvements.md file."""
        # Create pack_improvements.md
        content = """# Pack Improvements

### PACK-001: Fix typo in clarifier prompt

**Pattern observed:** Typo in instruction text
**Evidence:** Manual review
**Risk:** Low
**Rationale:** Simple fix improves readability

**File:** `.claude/agents/clarifier.md`
```diff
- You are the clarifer agent.
+ You are the clarifier agent.
```
"""

        (wisdom_dir / "pack_improvements.md").write_text(content, encoding="utf-8")

        patches = generate_evolution_patch(wisdom_dir)

        assert len(patches) == 1
        assert patches[0].id == "PACK-001"
        assert patches[0].patch_type == PatchType.AGENT_PROMPT
        assert patches[0].target_file == ".claude/agents/clarifier.md"
        assert "clarifier" in patches[0].content

    def test_generate_from_feedback_actions_evolution_section(self, wisdom_dir):
        """Test generating patches from Evolution Suggestions section."""
        # Create feedback_actions.md with Evolution Suggestions
        content = """# Feedback Actions (Run test-run)

## Outcome Snapshot
- issue_drafts: 2
- suggestions: 3

## Evolution Suggestions

### Station: clarifier
- Issue: Low clarification acceptance rate
- Suggestion: Add fallback research step
- Confidence: medium
- Evidence: run-abc123/wisdom/learnings.md

### Station: code-implementer
- Issue: Repeated test failures on Rust
- Suggestion: Add rust-analyzer to tools
- Confidence: high
- Evidence: run-def456/events.jsonl

## Issues Created
None.
"""

        (wisdom_dir / "feedback_actions.md").write_text(content, encoding="utf-8")

        patches = generate_evolution_patch(wisdom_dir)

        assert len(patches) == 2
        assert patches[0].id == "EVOLUTION-001"
        assert patches[0].target_file == "swarm/spec/stations/clarifier.yaml"
        assert "fallback research" in patches[0].reasoning

    def test_generate_empty_directory(self, wisdom_dir):
        """Test generating patches from empty directory."""
        patches = generate_evolution_patch(wisdom_dir)
        assert len(patches) == 0

    def test_generate_nonexistent_directory(self, temp_dir):
        """Test generating patches from nonexistent directory."""
        patches = generate_evolution_patch(temp_dir / "nonexistent")
        assert len(patches) == 0


# =============================================================================
# Patch Validation Tests
# =============================================================================


class TestValidateEvolutionPatch:
    """Tests for validate_evolution_patch function."""

    def test_validate_valid_patch(self, repo_root):
        """Test validating a valid patch."""
        # Create target file
        target = repo_root / "swarm" / "spec" / "stations" / "test-station.yaml"
        target.write_text("id: test-station\nversion: 1\n", encoding="utf-8")

        patch = EvolutionPatch(
            id="TEST-001",
            target_file="swarm/spec/stations/test-station.yaml",
            patch_type=PatchType.STATION_SPEC,
            content="+ new_field: value",
            confidence=ConfidenceLevel.HIGH,
            reasoning="Add new field",
        )

        result = validate_evolution_patch(patch, repo_root=repo_root)

        assert result.valid is True
        assert result.target_exists is True
        assert result.target_etag is not None
        assert len(result.errors) == 0

    def test_validate_missing_target(self, repo_root):
        """Test validating patch with missing target file."""
        patch = EvolutionPatch(
            id="TEST-001",
            target_file="swarm/spec/stations/nonexistent.yaml",
            patch_type=PatchType.STATION_SPEC,
            content="+ new line",
            confidence=ConfidenceLevel.HIGH,
            reasoning="Test",
        )

        result = validate_evolution_patch(patch, repo_root=repo_root)

        assert result.valid is False
        assert result.target_exists is False
        assert any("does not exist" in e for e in result.errors)

    def test_validate_empty_patch(self, repo_root):
        """Test validating patch with no content."""
        target = repo_root / "swarm" / "spec" / "stations" / "test.yaml"
        target.write_text("id: test\n", encoding="utf-8")

        patch = EvolutionPatch(
            id="TEST-001",
            target_file="swarm/spec/stations/test.yaml",
            patch_type=PatchType.STATION_SPEC,
            content="",
            confidence=ConfidenceLevel.HIGH,
            reasoning="Empty patch",
        )

        result = validate_evolution_patch(patch, repo_root=repo_root)

        assert result.valid is False
        assert any("no content" in e.lower() for e in result.errors)

    def test_validate_json_patch_operations(self, repo_root):
        """Test validating JSON patch operations."""
        target = repo_root / "swarm" / "spec" / "flows" / "test.yaml"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("id: test\nsteps: []\n", encoding="utf-8")

        patch = EvolutionPatch(
            id="TEST-001",
            target_file="swarm/spec/flows/test.yaml",
            patch_type=PatchType.FLOW_SPEC,
            content="",
            confidence=ConfidenceLevel.HIGH,
            reasoning="Add step",
            operations=[
                {"op": "add", "path": "/steps/-", "value": {"id": "new"}},
                {"op": "replace", "path": "/title", "value": "New Title"},
            ],
        )

        result = validate_evolution_patch(patch, repo_root=repo_root)

        assert result.valid is True
        assert len(result.preview) == 2

    def test_validate_invalid_json_patch_operation(self, repo_root):
        """Test validating invalid JSON patch operation."""
        target = repo_root / "swarm" / "spec" / "flows" / "test.yaml"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("id: test\n", encoding="utf-8")

        patch = EvolutionPatch(
            id="TEST-001",
            target_file="swarm/spec/flows/test.yaml",
            patch_type=PatchType.FLOW_SPEC,
            content="",
            confidence=ConfidenceLevel.HIGH,
            reasoning="Invalid op",
            operations=[
                {"op": "invalid_op", "path": "/foo"},  # Invalid operation
                {"path": "/bar"},  # Missing op
            ],
        )

        result = validate_evolution_patch(patch, repo_root=repo_root)

        assert result.valid is False
        assert any("invalid op" in e.lower() for e in result.errors)

    def test_validate_adds_warnings_for_high_risk(self, repo_root):
        """Test that high risk patches get warnings."""
        target = repo_root / "swarm" / "spec" / "stations" / "test.yaml"
        target.write_text("id: test\n", encoding="utf-8")

        patch = EvolutionPatch(
            id="TEST-001",
            target_file="swarm/spec/stations/test.yaml",
            patch_type=PatchType.STATION_SPEC,
            content="+ change",
            confidence=ConfidenceLevel.LOW,
            reasoning="Risky change",
            risk="high",
        )

        result = validate_evolution_patch(patch, repo_root=repo_root)

        assert len(result.warnings) > 0
        assert any("high-risk" in w.lower() for w in result.warnings)


# =============================================================================
# Patch Application Tests
# =============================================================================


class TestApplyEvolutionPatch:
    """Tests for apply_evolution_patch function."""

    def test_apply_dry_run(self, repo_root):
        """Test applying patch in dry-run mode."""
        target = repo_root / "swarm" / "spec" / "stations" / "test.yaml"
        target.write_text("id: test\nversion: 1\n", encoding="utf-8")

        patch = EvolutionPatch(
            id="TEST-001",
            target_file="swarm/spec/stations/test.yaml",
            patch_type=PatchType.STATION_SPEC,
            content="+ new_field: value",
            confidence=ConfidenceLevel.HIGH,
            reasoning="Add field",
        )

        result = apply_evolution_patch(patch, dry_run=True, repo_root=repo_root)

        assert result.success is True
        assert result.dry_run is True
        # File should not be modified
        assert "new_field" not in target.read_text(encoding="utf-8")

    def test_apply_json_patch(self, repo_root):
        """Test applying JSON patch operations."""
        target = repo_root / "swarm" / "spec" / "flows" / "test.yaml"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("id: test\nversion: 1\nsteps: []\n", encoding="utf-8")

        patch = EvolutionPatch(
            id="TEST-001",
            target_file="swarm/spec/flows/test.yaml",
            patch_type=PatchType.FLOW_SPEC,
            content="",
            confidence=ConfidenceLevel.HIGH,
            reasoning="Add step",
            operations=[
                {"op": "add", "path": "/steps/-", "value": {"id": "new_step"}}
            ],
        )

        result = apply_evolution_patch(patch, dry_run=False, repo_root=repo_root)

        assert result.success is True
        assert result.dry_run is False

        # Verify file was modified
        import yaml
        updated = yaml.safe_load(target.read_text(encoding="utf-8"))
        assert len(updated["steps"]) == 1
        assert updated["steps"][0]["id"] == "new_step"

    def test_apply_creates_backup(self, repo_root):
        """Test that backup is created when applying patch."""
        target = repo_root / "swarm" / "spec" / "stations" / "test.yaml"
        target.write_text("id: test\nversion: 1\n", encoding="utf-8")

        patch = EvolutionPatch(
            id="TEST-001",
            target_file="swarm/spec/stations/test.yaml",
            patch_type=PatchType.STATION_SPEC,
            content="",
            confidence=ConfidenceLevel.HIGH,
            reasoning="Change",
            operations=[{"op": "add", "path": "/new_field", "value": "test"}],
        )

        result = apply_evolution_patch(
            patch, dry_run=False, repo_root=repo_root, create_backup=True
        )

        assert result.success is True
        assert result.backup_path is not None
        assert Path(result.backup_path).exists()

    def test_apply_invalid_patch_fails(self, repo_root):
        """Test that invalid patch application fails gracefully."""
        patch = EvolutionPatch(
            id="TEST-001",
            target_file="swarm/spec/stations/nonexistent.yaml",
            patch_type=PatchType.STATION_SPEC,
            content="+ change",
            confidence=ConfidenceLevel.HIGH,
            reasoning="Test",
        )

        result = apply_evolution_patch(patch, dry_run=False, repo_root=repo_root)

        assert result.success is False
        assert len(result.errors) > 0


# =============================================================================
# List Pending Patches Tests
# =============================================================================


class TestListPendingPatches:
    """Tests for list_pending_patches function."""

    def test_list_pending_patches(self, temp_dir):
        """Test listing pending patches across runs."""
        runs_root = temp_dir / "runs"

        # Create run with patches
        wisdom1 = runs_root / "run-001" / "wisdom"
        wisdom1.mkdir(parents=True)
        patch_data = {
            "schema_version": "flow_evolution_v1",
            "patches": [
                {"id": "PATCH-001", "target_flow": "test.yaml", "reason": "Test"}
            ],
        }
        (wisdom1 / "flow_evolution.patch").write_text(json.dumps(patch_data))

        # Create run without patches
        wisdom2 = runs_root / "run-002" / "wisdom"
        wisdom2.mkdir(parents=True)

        pending = list_pending_patches(runs_root)

        assert len(pending) == 1
        run_id, patches = pending[0]
        assert run_id == "run-001"
        assert len(patches) == 1

    def test_list_pending_patches_excludes_applied(self, temp_dir):
        """Test that applied patches are excluded."""
        runs_root = temp_dir / "runs"
        wisdom = runs_root / "run-001" / "wisdom"
        wisdom.mkdir(parents=True)

        patch_data = {
            "schema_version": "flow_evolution_v1",
            "patches": [
                {"id": "PATCH-001", "target_flow": "test.yaml", "reason": "Test"}
            ],
        }
        (wisdom / "flow_evolution.patch").write_text(json.dumps(patch_data))

        # Mark as applied
        (wisdom / ".applied_PATCH-001").write_text("{}")

        pending = list_pending_patches(runs_root)

        # Should have no pending patches (the one patch was applied)
        assert len(pending) == 0 or all(len(p) == 0 for _, p in pending)

    def test_list_pending_patches_empty_runs_dir(self, temp_dir):
        """Test listing patches when runs directory is empty."""
        runs_root = temp_dir / "runs"
        runs_root.mkdir()

        pending = list_pending_patches(runs_root)

        assert len(pending) == 0


# =============================================================================
# Integration Tests
# =============================================================================


class TestEvolutionIntegration:
    """Integration tests for the evolution loop."""

    def test_full_evolution_cycle(self, repo_root):
        """Test the complete evolution cycle: generate -> validate -> apply."""
        # Setup: create wisdom artifacts
        runs_root = repo_root / "swarm" / "runs"
        wisdom_dir = runs_root / "test-run" / "wisdom"
        wisdom_dir.mkdir(parents=True)

        # Create target file
        target = repo_root / "swarm" / "spec" / "stations" / "test-station.yaml"
        target.write_text("id: test-station\nversion: 1\ntools:\n  - Read\n")

        # Create station tuning artifact
        tuning_content = """# Station Tuning

## Station: test-station

**Pattern observed:** Missing tool
**Evidence:** run-001

**Proposed tuning:**

File: `swarm/spec/stations/test-station.yaml`
```diff
  tools:
    - Read
+   - Write
```

**Risk:** Low
"""
        (wisdom_dir / "station_tuning.md").write_text(tuning_content)

        # Generate patches
        patches = generate_evolution_patch(wisdom_dir, run_id="test-run")
        assert len(patches) >= 1

        patch = patches[0]

        # Validate
        validation = validate_evolution_patch(patch, repo_root=repo_root)
        assert validation.valid is True

        # Apply (dry run first)
        dry_result = apply_evolution_patch(patch, dry_run=True, repo_root=repo_root)
        assert dry_result.success is True
        assert dry_result.dry_run is True

        # List pending (should show this patch)
        pending = list_pending_patches(runs_root)
        assert len(pending) == 1
