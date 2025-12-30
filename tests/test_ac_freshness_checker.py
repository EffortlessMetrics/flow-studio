"""
Test the AC freshness checker script.

Validates that check_selftest_ac_freshness.py correctly detects:
- Missing ACs in Matrix from Gherkin
- Missing ACs in Config from Matrix
- Orphaned ACs in Config
- All-OK scenarios
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest


SCRIPT_PATH = Path("swarm/tools/check_selftest_ac_freshness.py")


def test_script_exists():
    """Verify the AC freshness checker script exists."""
    assert SCRIPT_PATH.exists(), f"Script not found: {SCRIPT_PATH}"
    assert SCRIPT_PATH.is_file(), f"Script is not a file: {SCRIPT_PATH}"


def test_script_is_executable():
    """Verify the script has executable permissions."""
    import os
    assert os.access(SCRIPT_PATH, os.X_OK), f"Script is not executable: {SCRIPT_PATH}"


def test_freshness_check_passes():
    """
    Verify the script exits 0 when all checks pass.

    In the current state of the repo, all 6 ACs should be aligned
    across Gherkin, Matrix, and Config.
    """
    result = subprocess.run(
        ["uv", "run", str(SCRIPT_PATH)],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, (
        f"Expected exit code 0, got {result.returncode}\n"
        f"stdout: {result.stdout}\n"
        f"stderr: {result.stderr}"
    )
    assert "[PASS] AC Matrix Freshness Check" in result.stdout
    # Check for success message (AC count may change as new ACs are added)
    assert "ACs OK" in result.stdout


def test_json_output_structure():
    """Verify JSON output has correct structure."""
    result = subprocess.run(
        ["uv", "run", str(SCRIPT_PATH), "--json"],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, f"Expected exit code 0, got {result.returncode}"

    data = json.loads(result.stdout)

    # Verify top-level structure
    assert "status" in data
    assert "total_acs" in data
    assert "checks" in data
    assert "counts" in data

    # Verify status is PASS
    assert data["status"] == "PASS"

    # Verify checks structure
    assert "gherkin_to_matrix" in data["checks"]
    assert "matrix_to_config" in data["checks"]
    assert "config_to_matrix" in data["checks"]

    # Verify each check has pass and missing/orphaned
    for check_name in ["gherkin_to_matrix", "matrix_to_config", "config_to_matrix"]:
        check = data["checks"][check_name]
        assert "pass" in check
        assert check["pass"] is True, f"Check {check_name} failed: {check}"

    # Verify counts - gherkin has 6 core ACs, matrix and config have 11
    # (includes 2 stepwise, 1 provider-env, 1 gc-health, 1 wisdom-smoke)
    assert data["counts"]["gherkin"] == 6
    assert data["counts"]["matrix"] == 11
    assert data["counts"]["config"] == 11


def test_verbose_output_includes_ac_details():
    """Verify --verbose flag includes per-AC details."""
    result = subprocess.run(
        ["uv", "run", str(SCRIPT_PATH), "--verbose"],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "Detailed AC Status:" in result.stdout

    # Verify all 6 known ACs are listed
    expected_acs = [
        "AC-SELFTEST-KERNEL-FAST",
        "AC-SELFTEST-INTROSPECTABLE",
        "AC-SELFTEST-INDIVIDUAL-STEPS",
        "AC-SELFTEST-DEGRADED",
        "AC-SELFTEST-FAILURE-HINTS",
        "AC-SELFTEST-DEGRADATION-TRACKED",
    ]

    for ac in expected_acs:
        assert ac in result.stdout, f"Expected AC {ac} in verbose output"


def test_json_verbose_includes_ac_array():
    """Verify --json --verbose includes 'acs' array."""
    result = subprocess.run(
        ["uv", "run", str(SCRIPT_PATH), "--json", "--verbose"],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0

    data = json.loads(result.stdout)

    assert "acs" in data, "Expected 'acs' array in verbose JSON output"
    assert isinstance(data["acs"], list)
    # 11 ACs: 6 core + 2 stepwise + 1 provider-env + 1 gc-health + 1 wisdom-smoke
    assert len(data["acs"]) == 11

    # Verify each AC entry has correct structure
    for ac_info in data["acs"]:
        assert "id" in ac_info
        assert "status" in ac_info
        assert "sources" in ac_info
        assert isinstance(ac_info["sources"], list)

        # All ACs should be OK (aligned across all layers)
        assert ac_info["status"] in ["OK", "OK_NO_GHERKIN"]


def test_all_acs_are_bidirectionally_consistent():
    """
    Verify all ACs are properly aligned across sources.

    - Gherkin ACs (those with BDD scenarios) should all be in Matrix
    - Matrix ACs should all be in Config
    - Config should not have orphaned ACs (not in Matrix)

    Note: Matrix/Config may have more ACs than Gherkin (e.g., stepwise ACs
    that are tested via unit tests, not BDD scenarios).
    """
    result = subprocess.run(
        ["uv", "run", str(SCRIPT_PATH), "--json"],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0

    data = json.loads(result.stdout)

    # Gherkin ACs should be subset of Matrix ACs
    assert data["counts"]["gherkin"] <= data["counts"]["matrix"]
    # Matrix and Config should match
    assert data["counts"]["matrix"] == data["counts"]["config"]

    # All checks should pass
    assert data["checks"]["gherkin_to_matrix"]["pass"] is True
    assert data["checks"]["matrix_to_config"]["pass"] is True
    assert data["checks"]["config_to_matrix"]["pass"] is True

    # No missing or orphaned ACs
    assert len(data["checks"]["gherkin_to_matrix"]["missing"]) == 0
    assert len(data["checks"]["matrix_to_config"]["missing"]) == 0
    assert len(data["checks"]["config_to_matrix"]["orphaned"]) == 0


def test_parse_functions_are_idempotent():
    """
    Verify the parser functions can be imported and called directly.

    This ensures the script can be used as a library module.
    """
    sys.path.insert(0, str(Path("swarm/tools")))

    from check_selftest_ac_freshness import (
        parse_gherkin_acs,
        parse_matrix_acs,
        parse_config_acs,
    )

    gherkin_acs = parse_gherkin_acs()
    matrix_acs = parse_matrix_acs()
    config_acs = parse_config_acs()

    # All should return sets
    assert isinstance(gherkin_acs, set)
    assert isinstance(matrix_acs, set)
    assert isinstance(config_acs, set)

    # Gherkin ACs should be subset of Matrix (some ACs only have unit tests)
    assert gherkin_acs.issubset(matrix_acs)
    # Matrix and Config should match
    assert matrix_acs == config_acs

    # Gherkin has 6 core ACs, Matrix/Config have 11 (includes stepwise, provider-env, gc-health, wisdom-smoke)
    assert len(gherkin_acs) == 6
    assert len(matrix_acs) == 11


def test_help_flag():
    """Verify --help flag works."""
    result = subprocess.run(
        ["uv", "run", str(SCRIPT_PATH), "--help"],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "Validate AC matrix consistency" in result.stdout
    assert "--json" in result.stdout
    assert "--verbose" in result.stdout


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
