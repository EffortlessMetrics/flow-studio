"""
Test suite for run_flow_dry.py.

Tests the dry-run checker for swarm flows which parses flow specs,
extracts artifact references, and reports whether artifacts exist.
"""

import pytest
from pathlib import Path
import sys

# Import the module under test
sys.path.insert(0, str(Path(__file__).parent.parent / "swarm" / "tools"))
from run_flow_dry import parse_flow, extract_artifacts, run_flow, main


# ============================================================================
# Unit Tests - parse_flow
# ============================================================================


def test_parse_flow_extracts_steps_table(tmp_path):
    """
    parse_flow extracts rows from Steps table.

    Given: A flow spec with a valid Steps table
    When: I call parse_flow
    Then: Rows are extracted as column lists
    """
    flow_file = tmp_path / "flow-test.md"
    flow_file.write_text("""# Flow Test

## Overview

This is a test flow.

## Steps

| Step | Node | Type | Responsibility |
|------|------|------|----------------|
| 1 | signal-normalizer | agent | Produce `input.md` |
| 2 | problem-framer | agent | Produce `output.md` |

## Notes

More content here.
""")

    rows = parse_flow(flow_file)

    # Parser includes separator row (------) and data rows
    # Filter to get actual data rows (those with numeric step)
    data_rows = [r for r in rows if r[1].isdigit()]
    assert len(data_rows) == 2
    # Each row should have step, node, type, responsibility columns
    assert data_rows[0][1] == "1"
    assert data_rows[0][2] == "signal-normalizer"
    assert data_rows[1][1] == "2"
    assert data_rows[1][2] == "problem-framer"


def test_parse_flow_empty_table(tmp_path):
    """
    parse_flow handles flow spec with no Steps table.

    Given: A flow spec without a Steps table
    When: I call parse_flow
    Then: Empty list is returned
    """
    flow_file = tmp_path / "flow-empty.md"
    flow_file.write_text("""# Flow Empty

## Overview

No steps table here.
""")

    rows = parse_flow(flow_file)

    assert rows == []


# ============================================================================
# Unit Tests - extract_artifacts
# ============================================================================


def test_extract_artifacts_finds_backticked_names():
    """
    extract_artifacts finds backticked artifact names.

    Given: A responsibility string with backticked filenames
    When: I call extract_artifacts
    Then: All backticked names are extracted
    """
    responsibility = "Produce `requirements.md` and validate `input.json`"

    artifacts = extract_artifacts(responsibility)

    assert artifacts == ["requirements.md", "input.json"]


def test_extract_artifacts_handles_no_backticks():
    """
    extract_artifacts handles text without backticks.

    Given: A responsibility string without backticks
    When: I call extract_artifacts
    Then: Empty list is returned
    """
    responsibility = "Do something without specific files"

    artifacts = extract_artifacts(responsibility)

    assert artifacts == []


def test_extract_artifacts_handles_paths():
    """
    extract_artifacts handles full paths in backticks.

    Given: A responsibility string with backticked paths
    When: I call extract_artifacts
    Then: Full paths are extracted
    """
    responsibility = "Write to `RUN_BASE/signal/output.md`"

    artifacts = extract_artifacts(responsibility)

    assert artifacts == ["RUN_BASE/signal/output.md"]


# ============================================================================
# Integration Tests - run_flow
# ============================================================================


def test_run_flow_missing_flow_file(tmp_path, monkeypatch):
    """
    run_flow reports missing flow file.

    Given: A non-existent flow file
    When: I call run_flow
    Then: Returns error message and False
    """
    # Patch FLOW_DIR to use tmp_path
    import run_flow_dry
    monkeypatch.setattr(run_flow_dry, "FLOW_DIR", tmp_path)
    monkeypatch.setattr(run_flow_dry, "OUT_DIR", tmp_path / "reports")

    result, ok = run_flow("flow-nonexistent")

    assert ok is False
    assert "missing" in result.lower()


def test_run_flow_writes_report(tmp_path, monkeypatch):
    """
    run_flow writes a report file.

    Given: A valid flow file exists
    When: I call run_flow
    Then: A report file is written
    """
    import run_flow_dry

    # Create flow directory and file
    flows_dir = tmp_path / "flows"
    flows_dir.mkdir()
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()

    flow_file = flows_dir / "flow-test.md"
    flow_file.write_text("""# Flow Test

| Step | Node | Type | Responsibility |
|------|------|------|----------------|
| 1 | test-agent | agent | Produce `existing.md` |
""")

    # Create the artifact so it reports OK
    (tmp_path / "existing.md").write_text("content")

    monkeypatch.setattr(run_flow_dry, "FLOW_DIR", flows_dir)
    monkeypatch.setattr(run_flow_dry, "OUT_DIR", reports_dir)

    report_path, ok = run_flow("flow-test")

    assert isinstance(report_path, Path)
    assert report_path.exists()
    assert "flow-test" in report_path.name
    assert report_path.suffix == ".txt"


# ============================================================================
# Integration Tests - main (uses argparse, tested via run_flow directly)
# ============================================================================


def test_run_flow_with_artifacts_missing(tmp_path, monkeypatch):
    """
    run_flow reports missing artifacts.

    Given: A flow file that references non-existent artifacts
    When: I call run_flow
    Then: Returns report path and False (not ok)
    """
    import run_flow_dry

    # Create flow directory and file
    flows_dir = tmp_path / "flows"
    flows_dir.mkdir()
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()

    flow_file = flows_dir / "flow-test.md"
    flow_file.write_text("""# Flow Test

| Step | Node | Type | Responsibility |
|------|------|------|----------------|
| 1 | test-agent | agent | Produce `nonexistent.md` |
""")

    monkeypatch.setattr(run_flow_dry, "FLOW_DIR", flows_dir)
    monkeypatch.setattr(run_flow_dry, "OUT_DIR", reports_dir)

    report_path, ok = run_flow("flow-test")

    assert isinstance(report_path, Path)
    assert ok is False  # artifact does not exist
    # Report should contain MISSING
    report_content = report_path.read_text(encoding="utf-8")
    assert "MISSING" in report_content


def test_run_flow_with_all_artifacts_present(tmp_path, monkeypatch):
    """
    run_flow returns ok=True when all artifacts exist.

    Given: A flow file that references existing artifacts
    When: I call run_flow
    Then: Returns report path and True (ok)
    """
    import run_flow_dry

    # Create flow directory and file
    flows_dir = tmp_path / "flows"
    flows_dir.mkdir()
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()

    flow_file = flows_dir / "flow-test.md"
    flow_file.write_text("""# Flow Test

| Step | Node | Type | Responsibility |
|------|------|------|----------------|
| 1 | test-agent | agent | Produce `existing.md` |
""")

    # Create the artifact (relative to cwd, which we'll change)
    (tmp_path / "existing.md").write_text("content")

    monkeypatch.setattr(run_flow_dry, "FLOW_DIR", flows_dir)
    monkeypatch.setattr(run_flow_dry, "OUT_DIR", reports_dir)
    monkeypatch.chdir(tmp_path)  # Change cwd so relative path resolves

    report_path, ok = run_flow("flow-test")

    assert isinstance(report_path, Path)
    assert ok is True
