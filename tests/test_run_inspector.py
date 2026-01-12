#!/usr/bin/env python3
"""
Tests for swarm/tools/run_inspector.py - Run Inspector for Flow Studio.

This module provides Flow Studio with the ability to:
1. Discover available runs (active + examples)
2. Check artifact status for a specific (run_id, flow, step)
3. Compute flow-level and run-level summaries
4. Compare runs and compute timelines

## Test Coverage

### Listing Runs (5 tests)
1. test_list_runs_empty_directories - Returns empty list when no runs exist
2. test_list_runs_active_only - Lists runs from swarm/runs/ directory
3. test_list_runs_examples_only - Lists runs from swarm/examples/ directory
4. test_list_runs_combined - Lists both active and example runs, examples first
5. test_list_runs_with_metadata - Includes title, description, tags from run.json

### Run Path Resolution (4 tests)
6. test_get_run_path_example - Returns path for example run
7. test_get_run_path_active - Returns path for active run
8. test_get_run_path_prefers_example - Examples take precedence over active
9. test_get_run_path_not_found - Returns None for non-existent run

### Step Status (6 tests)
10. test_get_step_status_all_present - COMPLETE when all required artifacts exist
11. test_get_step_status_partial - PARTIAL when some required artifacts missing
12. test_get_step_status_missing - MISSING when no required artifacts exist
13. test_get_step_status_not_applicable - N/A when no required artifacts defined
14. test_get_step_status_with_optional - Tracks optional artifacts separately
15. test_get_step_status_nonexistent_run - Handles missing run gracefully

### Flow Status (5 tests)
16. test_get_flow_status_not_started - NOT_STARTED when flow directory missing
17. test_get_flow_status_in_progress - IN_PROGRESS when no decision artifact
18. test_get_flow_status_done - DONE when decision artifact present
19. test_get_flow_status_includes_steps - Includes step statuses
20. test_get_flow_status_unknown_flow - Handles unknown flow gracefully

### Run Summary (4 tests)
21. test_get_run_summary_complete - Returns all 7 flows in SDLC order
22. test_get_run_summary_example_type - Correctly identifies example runs
23. test_get_run_summary_active_type - Correctly identifies active runs
24. test_get_run_summary_unknown_run - Handles unknown run gracefully

### SDLC Bar (3 tests)
25. test_get_sdlc_bar_format - Returns list of flow summaries
26. test_get_sdlc_bar_order - Flows in correct SDLC order
27. test_get_sdlc_bar_status_values - Status values are valid enums

### Run Comparison (4 tests)
28. test_compare_flows_improved - Detects improved steps
29. test_compare_flows_regressed - Detects regressed steps
30. test_compare_flows_unchanged - Detects unchanged steps
31. test_compare_flows_summary - Summary counts are correct

### Timeline and Timing (5 tests)
32. test_get_run_timeline_empty - Returns empty list when no history
33. test_get_run_timeline_events_format - Parses new event format
34. test_get_run_timeline_legacy_format - Parses legacy execution_timeline format
35. test_get_run_timing_from_history - Computes timing from events
36. test_get_flow_timing - Returns timing for specific flow

### Serialization (2 tests)
37. test_to_dict_dataclass - Converts dataclasses to dicts
38. test_to_dict_enum - Converts enums to values

### Edge Cases (3 tests)
39. test_hidden_directories_ignored - Ignores .git, .hidden directories
40. test_malformed_run_json - Handles invalid JSON in run.json
41. test_malformed_catalog - Handles missing/invalid artifact catalog
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Add repo root to path so swarm imports work
repo_root = Path(__file__).resolve().parents[1]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

import pytest

from swarm.tools.run_inspector import (
    ArtifactResult,
    ArtifactStatus,
    FlowEvent,
    FlowResult,
    FlowStatus,
    FlowTiming,
    RunInspector,
    RunResult,
    RunTiming,
    StepResult,
    StepStatus,
    StepTiming,
)
from swarm.runtime import storage
from swarm.runtime import service as runtime_service
from swarm.runtime.service import RunService


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------


def _write_dummy_run(runs_dir: Path, run_id: str, flows: dict = None) -> Path:
    """
    Create a minimal valid run structure with meta.json.

    This helper writes the necessary files so that both RunInspector and
    RunService recognize the run as valid.

    Args:
        runs_dir: Base directory for runs (tmp_path based).
        run_id: Run identifier.
        flows: Optional dict mapping flow_key -> list of artifact filenames.

    Returns:
        Path to the created run directory.
    """
    from datetime import datetime, timezone
    from swarm.runtime.types import (
        RunSpec,
        RunStatus,
        RunSummary,
        SDLCStatus,
    )

    run_path = runs_dir / run_id
    run_path.mkdir(parents=True, exist_ok=True)

    # Write meta.json (required by RunService)
    now = datetime.now(timezone.utc)
    summary = RunSummary(
        id=run_id,
        spec=RunSpec(flow_keys=["signal"], backend="claude-harness", initiator="test"),
        status=RunStatus.PENDING,
        sdlc_status=SDLCStatus.UNKNOWN,
        created_at=now,
        updated_at=now,
    )
    storage.write_summary(run_id, summary, runs_dir=runs_dir)

    # Write flow artifacts if specified
    if flows:
        for flow_key, artifacts in flows.items():
            flow_dir = run_path / flow_key
            flow_dir.mkdir(exist_ok=True)
            for artifact in artifacts:
                (flow_dir / artifact).write_text(f"# {artifact}")

    return run_path


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------


@pytest.fixture
def isolated_runs_env(tmp_path, monkeypatch):
    """
    Fixture that isolates tests from real swarm/runs/ and swarm/examples/.

    Creates temporary directories and monkeypatches storage.RUNS_DIR and
    storage.EXAMPLES_DIR. Also resets RunService singleton before and after.

    Forces RunInspector.list_runs() to use the legacy implementation which
    respects the repo_root parameter.

    Yields a dict with runs_dir, examples_dir, and repo_root paths.
    """
    runs_dir = tmp_path / "swarm" / "runs"
    examples_dir = tmp_path / "swarm" / "examples"
    meta_dir = tmp_path / "swarm" / "meta"

    runs_dir.mkdir(parents=True)
    examples_dir.mkdir(parents=True)
    meta_dir.mkdir(parents=True)

    # Monkeypatch storage module globals
    monkeypatch.setattr(storage, "RUNS_DIR", runs_dir)
    monkeypatch.setattr(storage, "EXAMPLES_DIR", examples_dir)

    # Also patch the locally-imported EXAMPLES_DIR in service module
    monkeypatch.setattr(runtime_service, "EXAMPLES_DIR", examples_dir)

    # Force RunInspector.list_runs() to use the legacy implementation
    def mock_list_runs(self):
        return self._list_runs_legacy()

    monkeypatch.setattr(RunInspector, "list_runs", mock_list_runs)

    # Reset RunService singleton before test
    RunService.reset()

    yield {
        "runs_dir": runs_dir,
        "examples_dir": examples_dir,
        "repo_root": tmp_path,
    }

    # Reset RunService singleton after test
    RunService.reset()


@pytest.fixture
def temp_repo(tmp_path, monkeypatch):
    """Create a temporary repo structure with runs and examples directories.

    Also monkeypatches storage.RUNS_DIR and storage.EXAMPLES_DIR to isolate
    from real filesystem state.

    Forces RunInspector.list_runs() to use the legacy implementation which
    respects the repo_root parameter.
    """
    runs_dir = tmp_path / "swarm" / "runs"
    examples_dir = tmp_path / "swarm" / "examples"
    meta_dir = tmp_path / "swarm" / "meta"

    runs_dir.mkdir(parents=True)
    examples_dir.mkdir(parents=True)
    meta_dir.mkdir(parents=True)

    # Monkeypatch storage module globals for isolation
    monkeypatch.setattr(storage, "RUNS_DIR", runs_dir)
    monkeypatch.setattr(storage, "EXAMPLES_DIR", examples_dir)

    # Also patch the locally-imported EXAMPLES_DIR in service module
    monkeypatch.setattr(runtime_service, "EXAMPLES_DIR", examples_dir)

    # Force RunInspector.list_runs() to use the legacy implementation
    # by making RunService unavailable via import
    def mock_list_runs(self):
        return self._list_runs_legacy()

    monkeypatch.setattr(RunInspector, "list_runs", mock_list_runs)

    # Reset RunService singleton before test
    RunService.reset()

    yield tmp_path

    # Reset RunService singleton after test
    RunService.reset()


@pytest.fixture
def inspector(temp_repo):
    """Create a RunInspector instance with the temp repo."""
    return RunInspector(repo_root=temp_repo)


@pytest.fixture
def sample_catalog():
    """Return a sample artifact catalog for testing."""
    return {
        "version": "1.0.0",
        "flows": {
            "signal": {
                "title": "Flow 1 - Signal",
                "decision_artifact": "problem_statement.md",
                "steps": {
                    "normalize": {
                        "required": ["issue_normalized.md", "context_brief.md"],
                        "optional": ["related_links.json"],
                    },
                    "frame": {
                        "required": ["problem_statement.md"],
                        "optional": [],
                    },
                },
            },
            "build": {
                "title": "Flow 3 - Build",
                "decision_artifact": "build_receipt.json",
                "steps": {
                    "branch": {
                        "required": [],
                        "optional": [],
                        "note": "Git operation only",
                    },
                    "author_tests": {
                        "required": ["test_changes_summary.md"],
                        "optional": ["fuzz_changes_summary.md"],
                    },
                },
            },
        },
    }


@pytest.fixture
def inspector_with_catalog(temp_repo, sample_catalog):
    """Create a RunInspector with a sample catalog."""
    meta_dir = temp_repo / "swarm" / "meta"
    catalog_path = meta_dir / "artifact_catalog.json"
    catalog_path.write_text(json.dumps(sample_catalog))
    return RunInspector(repo_root=temp_repo)


def create_run(base_dir, run_id, run_type="active", metadata=None, flows=None):
    """
    Helper to create a synthetic run directory.

    Args:
        base_dir: The repo root path
        run_id: Run identifier
        run_type: "active" or "example"
        metadata: Optional dict for run.json (title, description, tags)
        flows: Optional dict mapping flow_key -> list of artifact filenames
    """
    if run_type == "active":
        run_dir = base_dir / "swarm" / "runs" / run_id
    else:
        run_dir = base_dir / "swarm" / "examples" / run_id

    run_dir.mkdir(parents=True, exist_ok=True)

    if metadata:
        run_json = run_dir / "run.json"
        run_json.write_text(json.dumps(metadata))

    if flows:
        for flow_key, artifacts in flows.items():
            flow_dir = run_dir / flow_key
            flow_dir.mkdir(exist_ok=True)
            for artifact in artifacts:
                (flow_dir / artifact).write_text(f"# {artifact}")

    return run_dir


# -----------------------------------------------------------------------------
# Listing Runs Tests
# -----------------------------------------------------------------------------


class TestListRuns:
    """Tests for listing runs from swarm/runs/ and swarm/examples/."""

    def test_list_runs_empty_directories(self, inspector):
        """Returns empty list when no runs exist."""
        runs = inspector.list_runs()
        assert runs == [], "Expected empty list when no runs exist"

    def test_list_runs_active_only(self, temp_repo, inspector):
        """Lists runs from swarm/runs/ directory."""
        create_run(temp_repo, "my-feature", run_type="active")
        create_run(temp_repo, "another-run", run_type="active")

        runs = inspector.list_runs()

        assert len(runs) == 2, f"Expected 2 runs, got {len(runs)}"
        run_ids = {r["run_id"] for r in runs}
        assert run_ids == {"my-feature", "another-run"}
        for run in runs:
            assert run["run_type"] == "active"

    def test_list_runs_examples_only(self, temp_repo, inspector):
        """Lists runs from swarm/examples/ directory."""
        create_run(temp_repo, "health-check", run_type="example")
        create_run(temp_repo, "demo-baseline", run_type="example")

        runs = inspector.list_runs()

        assert len(runs) == 2, f"Expected 2 runs, got {len(runs)}"
        run_ids = {r["run_id"] for r in runs}
        assert run_ids == {"health-check", "demo-baseline"}
        for run in runs:
            assert run["run_type"] == "example"

    def test_list_runs_combined(self, temp_repo, inspector):
        """Lists both active and example runs, examples first."""
        create_run(temp_repo, "health-check", run_type="example")
        create_run(temp_repo, "my-feature", run_type="active")
        create_run(temp_repo, "demo-baseline", run_type="example")

        runs = inspector.list_runs()

        assert len(runs) == 3, f"Expected 3 runs, got {len(runs)}"

        # Examples should come first
        assert runs[0]["run_type"] == "example"
        assert runs[1]["run_type"] == "example"
        assert runs[2]["run_type"] == "active"

    def test_list_runs_with_metadata(self, temp_repo, inspector):
        """Includes title, description, tags from run.json."""
        metadata = {
            "title": "Health Check Baseline",
            "description": "Complete end-to-end example",
            "tags": ["baseline", "complete"],
        }
        create_run(temp_repo, "health-check", run_type="example", metadata=metadata)

        runs = inspector.list_runs()

        assert len(runs) == 1
        run = runs[0]
        assert run["title"] == "Health Check Baseline"
        assert run["description"] == "Complete end-to-end example"
        assert run["tags"] == ["baseline", "complete"]


# -----------------------------------------------------------------------------
# Run Path Resolution Tests
# -----------------------------------------------------------------------------


class TestGetRunPath:
    """Tests for resolving run paths."""

    def test_get_run_path_example(self, temp_repo, inspector):
        """Returns path for example run."""
        create_run(temp_repo, "health-check", run_type="example")

        path = inspector.get_run_path("health-check")

        assert path is not None
        assert path.exists()
        assert "examples" in str(path)

    def test_get_run_path_active(self, temp_repo, inspector):
        """Returns path for active run."""
        create_run(temp_repo, "my-feature", run_type="active")

        path = inspector.get_run_path("my-feature")

        assert path is not None
        assert path.exists()
        assert "runs" in str(path)

    def test_get_run_path_prefers_example(self, temp_repo, inspector):
        """Examples take precedence over active runs with same name."""
        create_run(temp_repo, "duplicate", run_type="example")
        create_run(temp_repo, "duplicate", run_type="active")

        path = inspector.get_run_path("duplicate")

        assert path is not None
        assert "examples" in str(path), "Should prefer example over active"

    def test_get_run_path_not_found(self, inspector):
        """Returns None for non-existent run."""
        path = inspector.get_run_path("nonexistent-run")
        assert path is None


# -----------------------------------------------------------------------------
# Step Status Tests
# -----------------------------------------------------------------------------


class TestGetStepStatus:
    """Tests for checking step artifact status."""

    def test_get_step_status_all_present(self, temp_repo, inspector_with_catalog):
        """COMPLETE when all required artifacts exist."""
        create_run(
            temp_repo,
            "test-run",
            run_type="active",
            flows={
                "signal": ["issue_normalized.md", "context_brief.md"],
            },
        )

        result = inspector_with_catalog.get_step_status("test-run", "signal", "normalize")

        assert result.status == StepStatus.COMPLETE
        assert result.required_present == 2
        assert result.required_total == 2

    def test_get_step_status_partial(self, temp_repo, inspector_with_catalog):
        """PARTIAL when some required artifacts missing."""
        create_run(
            temp_repo,
            "test-run",
            run_type="active",
            flows={
                "signal": ["issue_normalized.md"],  # Missing context_brief.md
            },
        )

        result = inspector_with_catalog.get_step_status("test-run", "signal", "normalize")

        assert result.status == StepStatus.PARTIAL
        assert result.required_present == 1
        assert result.required_total == 2

    def test_get_step_status_missing(self, temp_repo, inspector_with_catalog):
        """MISSING when no required artifacts exist."""
        create_run(
            temp_repo,
            "test-run",
            run_type="active",
            flows={
                "signal": [],  # Empty flow directory
            },
        )

        result = inspector_with_catalog.get_step_status("test-run", "signal", "normalize")

        assert result.status == StepStatus.MISSING
        assert result.required_present == 0
        assert result.required_total == 2

    def test_get_step_status_not_applicable(self, temp_repo, inspector_with_catalog):
        """N/A when no required artifacts defined."""
        create_run(
            temp_repo,
            "test-run",
            run_type="active",
            flows={
                "build": [],
            },
        )

        result = inspector_with_catalog.get_step_status("test-run", "build", "branch")

        assert result.status == StepStatus.NOT_APPLICABLE
        assert result.required_total == 0
        assert result.note == "Git operation only"

    def test_get_step_status_with_optional(self, temp_repo, inspector_with_catalog):
        """Tracks optional artifacts separately."""
        create_run(
            temp_repo,
            "test-run",
            run_type="active",
            flows={
                "signal": [
                    "issue_normalized.md",
                    "context_brief.md",
                    "related_links.json",
                ],
            },
        )

        result = inspector_with_catalog.get_step_status("test-run", "signal", "normalize")

        assert result.status == StepStatus.COMPLETE
        assert result.optional_present == 1
        assert result.optional_total == 1

    def test_get_step_status_nonexistent_run(self, inspector_with_catalog):
        """Handles missing run gracefully."""
        result = inspector_with_catalog.get_step_status(
            "nonexistent", "signal", "normalize"
        )

        assert result.status == StepStatus.MISSING
        assert result.required_present == 0


# -----------------------------------------------------------------------------
# Flow Status Tests
# -----------------------------------------------------------------------------


class TestGetFlowStatus:
    """Tests for checking flow status."""

    def test_get_flow_status_not_started(self, temp_repo, inspector_with_catalog):
        """NOT_STARTED when flow directory missing."""
        create_run(temp_repo, "test-run", run_type="active", flows={})

        result = inspector_with_catalog.get_flow_status("test-run", "signal")

        assert result.status == FlowStatus.NOT_STARTED
        assert result.decision_present is False

    def test_get_flow_status_in_progress(self, temp_repo, inspector_with_catalog):
        """IN_PROGRESS when no decision artifact."""
        create_run(
            temp_repo,
            "test-run",
            run_type="active",
            flows={
                "signal": ["issue_normalized.md"],  # No problem_statement.md
            },
        )

        result = inspector_with_catalog.get_flow_status("test-run", "signal")

        assert result.status == FlowStatus.IN_PROGRESS
        assert result.decision_present is False

    def test_get_flow_status_done(self, temp_repo, inspector_with_catalog):
        """DONE when decision artifact present."""
        create_run(
            temp_repo,
            "test-run",
            run_type="active",
            flows={
                "signal": ["problem_statement.md"],
            },
        )

        result = inspector_with_catalog.get_flow_status("test-run", "signal")

        assert result.status == FlowStatus.DONE
        assert result.decision_present is True
        assert result.decision_artifact == "problem_statement.md"

    def test_get_flow_status_includes_steps(self, temp_repo, inspector_with_catalog):
        """Includes step statuses."""
        create_run(
            temp_repo,
            "test-run",
            run_type="active",
            flows={
                "signal": ["problem_statement.md"],
            },
        )

        result = inspector_with_catalog.get_flow_status("test-run", "signal")

        assert "normalize" in result.steps
        assert "frame" in result.steps
        assert isinstance(result.steps["normalize"], StepResult)

    def test_get_flow_status_unknown_flow(self, temp_repo, inspector_with_catalog):
        """Handles unknown flow gracefully."""
        create_run(temp_repo, "test-run", run_type="active", flows={})

        result = inspector_with_catalog.get_flow_status("test-run", "unknown")

        assert result.status == FlowStatus.NOT_STARTED
        assert result.title == "Unknown"


# -----------------------------------------------------------------------------
# Run Summary Tests
# -----------------------------------------------------------------------------


class TestGetRunSummary:
    """Tests for getting complete run summaries."""

    def test_get_run_summary_complete(self, temp_repo, inspector_with_catalog):
        """Returns all 7 flows in SDLC order."""
        create_run(temp_repo, "test-run", run_type="active", flows={})

        result = inspector_with_catalog.get_run_summary("test-run")

        assert isinstance(result, RunResult)
        assert list(result.flows.keys()) == [
            "signal",
            "plan",
            "build",
            "review",
            "gate",
            "deploy",
            "wisdom",
        ]

    def test_get_run_summary_example_type(self, temp_repo, inspector_with_catalog):
        """Correctly identifies example runs."""
        create_run(temp_repo, "health-check", run_type="example", flows={})

        result = inspector_with_catalog.get_run_summary("health-check")

        assert result.run_type == "example"

    def test_get_run_summary_active_type(self, temp_repo, inspector_with_catalog):
        """Correctly identifies active runs."""
        create_run(temp_repo, "my-feature", run_type="active", flows={})

        result = inspector_with_catalog.get_run_summary("my-feature")

        assert result.run_type == "active"

    def test_get_run_summary_unknown_run(self, inspector_with_catalog):
        """Handles unknown run gracefully."""
        result = inspector_with_catalog.get_run_summary("nonexistent")

        assert result.run_type == "unknown"
        assert result.path == ""


# -----------------------------------------------------------------------------
# SDLC Bar Tests
# -----------------------------------------------------------------------------


class TestGetSdlcBar:
    """Tests for SDLC bar data generation."""

    def test_get_sdlc_bar_format(self, temp_repo, inspector_with_catalog):
        """Returns list of flow summaries."""
        create_run(temp_repo, "test-run", run_type="active", flows={})

        result = inspector_with_catalog.get_sdlc_bar("test-run")

        assert isinstance(result, list)
        assert len(result) == 7
        for flow in result:
            assert "flow_key" in flow
            assert "title" in flow
            assert "status" in flow
            assert "decision_artifact" in flow
            assert "decision_present" in flow

    def test_get_sdlc_bar_order(self, temp_repo, inspector_with_catalog):
        """Flows in correct SDLC order."""
        create_run(temp_repo, "test-run", run_type="active", flows={})

        result = inspector_with_catalog.get_sdlc_bar("test-run")

        flow_keys = [f["flow_key"] for f in result]
        assert flow_keys == ["signal", "plan", "build", "review", "gate", "deploy", "wisdom"]

    def test_get_sdlc_bar_status_values(self, temp_repo, inspector_with_catalog):
        """Status values are valid enums."""
        create_run(
            temp_repo,
            "test-run",
            run_type="active",
            flows={
                "signal": ["problem_statement.md"],
            },
        )

        result = inspector_with_catalog.get_sdlc_bar("test-run")

        valid_statuses = {"not_started", "in_progress", "done"}
        for flow in result:
            assert flow["status"] in valid_statuses


# -----------------------------------------------------------------------------
# Run Comparison Tests
# -----------------------------------------------------------------------------


class TestCompareFlows:
    """Tests for comparing runs."""

    def test_compare_flows_improved(self, temp_repo, inspector_with_catalog):
        """Detects improved steps."""
        # Run A: missing artifacts
        create_run(
            temp_repo,
            "run-a",
            run_type="active",
            flows={"signal": []},
        )
        # Run B: has artifacts
        create_run(
            temp_repo,
            "run-b",
            run_type="active",
            flows={"signal": ["issue_normalized.md", "context_brief.md"]},
        )

        result = inspector_with_catalog.compare_flows("run-a", "run-b", "signal")

        assert result["summary"]["improved"] >= 1

    def test_compare_flows_regressed(self, temp_repo, inspector_with_catalog):
        """Detects regressed steps."""
        # Run A: has artifacts
        create_run(
            temp_repo,
            "run-a",
            run_type="active",
            flows={"signal": ["issue_normalized.md", "context_brief.md"]},
        )
        # Run B: missing artifacts
        create_run(
            temp_repo,
            "run-b",
            run_type="active",
            flows={"signal": []},
        )

        result = inspector_with_catalog.compare_flows("run-a", "run-b", "signal")

        assert result["summary"]["regressed"] >= 1

    def test_compare_flows_unchanged(self, temp_repo, inspector_with_catalog):
        """Detects unchanged steps."""
        # Both runs have same artifacts
        for run_id in ["run-a", "run-b"]:
            create_run(
                temp_repo,
                run_id,
                run_type="active",
                flows={"signal": ["issue_normalized.md", "context_brief.md"]},
            )

        result = inspector_with_catalog.compare_flows("run-a", "run-b", "signal")

        # At least normalize step should be unchanged
        assert result["summary"]["unchanged"] >= 1

    def test_compare_flows_summary(self, temp_repo, inspector_with_catalog):
        """Summary counts are correct."""
        create_run(temp_repo, "run-a", run_type="active", flows={"signal": []})
        create_run(temp_repo, "run-b", run_type="active", flows={"signal": []})

        result = inspector_with_catalog.compare_flows("run-a", "run-b", "signal")

        summary = result["summary"]
        total = summary["improved"] + summary["regressed"] + summary["unchanged"]
        assert total == len(result["steps"])


# -----------------------------------------------------------------------------
# Timeline and Timing Tests
# -----------------------------------------------------------------------------


class TestGetRunTimeline:
    """Tests for timeline and timing data."""

    def test_get_run_timeline_empty(self, temp_repo, inspector):
        """Returns empty list when no history."""
        create_run(temp_repo, "test-run", run_type="active", flows={})

        result = inspector.get_run_timeline("test-run")

        assert result == []

    def test_get_run_timeline_events_format(self, temp_repo, inspector):
        """Parses new event format."""
        run_dir = create_run(temp_repo, "test-run", run_type="active", flows={})
        wisdom_dir = run_dir / "wisdom"
        wisdom_dir.mkdir(exist_ok=True)

        history = {
            "events": [
                {
                    "ts": "2025-01-15T10:00:00Z",
                    "flow": "signal",
                    "step": None,
                    "status": "started",
                    "duration_ms": None,
                    "note": None,
                },
                {
                    "ts": "2025-01-15T10:05:00Z",
                    "flow": "signal",
                    "step": None,
                    "status": "completed",
                    "duration_ms": 300000,
                    "note": "All steps passed",
                },
            ]
        }
        (wisdom_dir / "flow_history.json").write_text(json.dumps(history))

        result = inspector.get_run_timeline("test-run")

        assert len(result) == 2
        assert isinstance(result[0], FlowEvent)
        assert result[0].flow == "signal"
        assert result[0].status == "started"
        assert result[1].status == "completed"

    def test_get_run_timeline_legacy_format(self, temp_repo, inspector):
        """Parses legacy execution_timeline format."""
        run_dir = create_run(temp_repo, "test-run", run_type="active", flows={})
        wisdom_dir = run_dir / "wisdom"
        wisdom_dir.mkdir(exist_ok=True)

        history = {
            "execution_timeline": [
                {
                    "flow": "signal",
                    "start_time": "2025-01-15T10:00:00Z",
                    "end_time": "2025-01-15T10:05:00Z",
                    "duration_minutes": 5,
                    "decision": "approved",
                    "decision_artifact": "problem_statement.md",
                }
            ]
        }
        (wisdom_dir / "flow_history.json").write_text(json.dumps(history))

        result = inspector.get_run_timeline("test-run")

        assert len(result) == 2  # started + completed events
        assert result[0].status == "started"
        assert result[1].status == "completed"

    def test_get_run_timing_from_history(self, temp_repo, inspector):
        """Computes timing from events."""
        run_dir = create_run(temp_repo, "test-run", run_type="active", flows={})
        wisdom_dir = run_dir / "wisdom"
        wisdom_dir.mkdir(exist_ok=True)

        history = {
            "events": [
                {"ts": "2025-01-15T10:00:00Z", "flow": "signal", "status": "started"},
                {"ts": "2025-01-15T10:05:00Z", "flow": "signal", "status": "completed"},
            ]
        }
        (wisdom_dir / "flow_history.json").write_text(json.dumps(history))

        result = inspector.get_run_timing("test-run")

        assert result is not None
        assert isinstance(result, RunTiming)
        assert "signal" in result.flows
        assert result.flows["signal"].duration_seconds == 300.0

    def test_get_flow_timing(self, temp_repo, inspector):
        """Returns timing for specific flow."""
        run_dir = create_run(temp_repo, "test-run", run_type="active", flows={})
        wisdom_dir = run_dir / "wisdom"
        wisdom_dir.mkdir(exist_ok=True)

        history = {
            "events": [
                {"ts": "2025-01-15T10:00:00Z", "flow": "signal", "status": "started"},
                {"ts": "2025-01-15T10:05:00Z", "flow": "signal", "status": "completed"},
            ]
        }
        (wisdom_dir / "flow_history.json").write_text(json.dumps(history))

        result = inspector.get_flow_timing("test-run", "signal")

        assert result is not None
        assert isinstance(result, FlowTiming)
        assert result.flow_key == "signal"


# -----------------------------------------------------------------------------
# Serialization Tests
# -----------------------------------------------------------------------------


class TestToDict:
    """Tests for JSON serialization."""

    def test_to_dict_dataclass(self, inspector):
        """Converts dataclasses to dicts."""
        step_result = StepResult(
            step_id="normalize",
            status=StepStatus.COMPLETE,
            required_present=2,
            required_total=2,
            optional_present=0,
            optional_total=1,
            artifacts=[],
            note=None,
        )

        result = inspector.to_dict(step_result)

        assert isinstance(result, dict)
        assert result["step_id"] == "normalize"
        assert result["status"] == "complete"

    def test_to_dict_enum(self, inspector):
        """Converts enums to values."""
        result = inspector.to_dict(StepStatus.COMPLETE)
        assert result == "complete"

        result = inspector.to_dict(FlowStatus.DONE)
        assert result == "done"


# -----------------------------------------------------------------------------
# Edge Case Tests
# -----------------------------------------------------------------------------


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_hidden_directories_ignored(self, temp_repo, inspector):
        """Ignores .git, .hidden directories."""
        # Create hidden directories
        (temp_repo / "swarm" / "runs" / ".hidden").mkdir(parents=True)
        (temp_repo / "swarm" / "runs" / ".git").mkdir(parents=True)
        # Create a valid run
        create_run(temp_repo, "valid-run", run_type="active")

        runs = inspector.list_runs()

        assert len(runs) == 1
        assert runs[0]["run_id"] == "valid-run"

    def test_malformed_run_json(self, temp_repo, inspector):
        """Handles invalid JSON in run.json."""
        run_dir = temp_repo / "swarm" / "runs" / "bad-json"
        run_dir.mkdir(parents=True)
        (run_dir / "run.json").write_text("{ not valid json }")

        runs = inspector.list_runs()

        # Should still list the run, just without metadata
        assert len(runs) == 1
        assert runs[0]["run_id"] == "bad-json"
        assert "title" not in runs[0]

    def test_malformed_catalog(self, temp_repo):
        """Handles missing/invalid artifact catalog."""
        # Create inspector without catalog
        inspector = RunInspector(repo_root=temp_repo)

        assert inspector.catalog == {"flows": {}}

        # Should still work, just with no step definitions
        create_run(temp_repo, "test-run", run_type="active", flows={})
        result = inspector.get_step_status("test-run", "signal", "normalize")

        assert result.status == StepStatus.NOT_APPLICABLE


# -----------------------------------------------------------------------------
# Integration with Real Catalog (Isolated)
# -----------------------------------------------------------------------------


class TestIntegrationWithRealCatalog:
    """
    Integration tests using the actual artifact catalog from the repo.

    These tests use isolated runs/examples directories but load the real
    artifact catalog to verify it parses correctly and has expected structure.
    """

    def test_real_catalog_loads(self):
        """Verify the real artifact catalog loads correctly.

        This test loads the catalog from the real repo but does not discover
        any runs, so it does not need filesystem isolation.
        """
        # Use real repo root to load real catalog, but don't list runs
        inspector = RunInspector()

        # Should have flows defined
        assert "flows" in inspector.catalog
        flows = inspector.catalog.get("flows", {})

        # Should have all 7 flows
        expected_flows = {"signal", "plan", "build", "review", "gate", "deploy", "wisdom"}
        actual_flows = set(flows.keys())
        assert expected_flows == actual_flows, (
            f"Expected flows {expected_flows}, got {actual_flows}"
        )

    def test_example_runs_discoverable(self, isolated_runs_env):
        """Verify example runs can be discovered in isolated environment.

        Creates example runs in isolated examples/ directory and verifies
        they are discoverable by RunInspector.
        """
        env = isolated_runs_env
        examples_dir = env["examples_dir"]
        repo_root = env["repo_root"]

        # Create an example run with flow artifacts
        example_path = examples_dir / "health-check"
        example_path.mkdir(parents=True)
        (example_path / "signal").mkdir()
        (example_path / "signal" / "problem_statement.md").write_text("# Problem")

        # Create inspector pointing to isolated environment
        inspector = RunInspector(repo_root=repo_root)
        runs = inspector.list_runs()

        # Should find the example we created
        example_ids = [r["run_id"] for r in runs if r["run_type"] == "example"]
        assert "health-check" in example_ids, (
            f"Expected 'health-check' in examples, got {example_ids}"
        )

    def test_active_and_example_runs_combined(self, isolated_runs_env):
        """Verify both active and example runs are listed correctly."""
        env = isolated_runs_env
        runs_dir = env["runs_dir"]
        examples_dir = env["examples_dir"]
        repo_root = env["repo_root"]

        # Create an example run
        example_path = examples_dir / "demo-example"
        example_path.mkdir(parents=True)
        (example_path / "signal").mkdir()

        # Create an active run using the helper
        _write_dummy_run(runs_dir, "active-feature", flows={"signal": []})

        # Create inspector and list runs
        inspector = RunInspector(repo_root=repo_root)
        runs = inspector.list_runs()

        # Should have exactly 2 runs
        assert len(runs) == 2, f"Expected 2 runs, got {len(runs)}: {runs}"

        # Examples should come first
        assert runs[0]["run_type"] == "example"
        assert runs[0]["run_id"] == "demo-example"
        assert runs[1]["run_type"] == "active"
        assert runs[1]["run_id"] == "active-feature"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
