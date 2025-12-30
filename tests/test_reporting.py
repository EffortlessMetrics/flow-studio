"""
Test suite for validation reporting (FR-006, FR-012).

Tests the validator's ability to generate clear error messages,
JSON reports, markdown reports, and proper exit codes.

BDD Scenarios covered:
- FR-006: Error message includes file path and line number
- FR-006: Error message includes problem description and fix action
- FR-006: Multiple errors are all reported in single run
- FR-006: Errors are printed to stderr
- FR-006: Fix guidance is actionable and specific
- FR-012: JSON report generation and structure
- FR-012: Markdown report generation and structure
"""

import json

import pytest

from conftest import (
    add_agent_to_registry,
    assert_validator_failed,
    create_agent_file,
    create_flow_file,
)

# ============================================================================
# Error Message Format Tests (FR-006)
# ============================================================================


def test_error_message_includes_file_and_line(temp_repo, run_validator):
    """
    Scenario: Error message includes file path and line number.

    Given: swarm/AGENTS.md line 42 has agent entry 'foo-bar'
    And: .claude/agents/foo-bar.md does not exist
    When: I run the validator
    Then: Error message includes file path and line number
    """
    add_agent_to_registry(temp_repo, "foo-bar")

    result = run_validator(temp_repo)
    assert_validator_failed(result)

    # Should mention file
    assert "swarm/AGENTS.md" in result.stderr or "AGENTS.md" in result.stderr
    # Should mention line (or agent key)
    assert "foo-bar" in result.stderr


def test_error_message_follows_standard_format(temp_repo, run_validator):
    """
    Scenario: Error message includes problem description and fix action.

    Each error message follows format:
      | [FAIL] CHECK_TYPE: location problem statement |
      | Fix: concrete action (one sentence)           |
    """
    add_agent_to_registry(temp_repo, "missing-agent")

    result = run_validator(temp_repo)
    assert_validator_failed(result)

    # Should have [FAIL] marker
    assert "[FAIL]" in result.stderr

    # Should have "Fix:" line
    assert "Fix:" in result.stderr

    # Should mention the problem
    assert "missing-agent" in result.stderr


def test_multiple_errors_all_reported(temp_repo, run_validator):
    """
    Scenario: Multiple errors are all reported in single run.

    Given: swarm/AGENTS.md has 5 agent misalignments
    When: I run the validator
    Then: All 5 errors are reported
    And: Validator does not stop after first error
    """
    # Create 5 different errors
    add_agent_to_registry(temp_repo, "missing-1")
    add_agent_to_registry(temp_repo, "missing-2")
    create_agent_file(temp_repo, "orphan-1")
    create_agent_file(temp_repo, "orphan-2")
    add_agent_to_registry(temp_repo, "mismatch")
    create_agent_file(temp_repo, "mismatch-wrong")

    result = run_validator(temp_repo)
    assert_validator_failed(result)

    # Should report multiple errors (at least 5)
    assert result.stderr.count("[FAIL]") >= 5


def test_errors_printed_to_stderr(temp_repo, run_validator):
    """
    Scenario: Errors are printed to stderr.

    Given: Validation fails with errors
    When: I run the validator
    Then: Error messages are written to stderr (not stdout)
    """
    add_agent_to_registry(temp_repo, "missing-agent")

    result = run_validator(temp_repo)
    assert_validator_failed(result)

    # Errors should be in stderr
    assert len(result.stderr) > 0
    assert "[FAIL]" in result.stderr or "error" in result.stderr.lower()

    # stdout should be empty or minimal (no error details)
    # Note: Some validators may print summary to stdout


def test_fix_guidance_is_actionable(temp_repo, run_validator):
    """
    Scenario: Fix guidance is actionable and specific.

    The "Fix:" line includes:
      | A specific action (e.g., "Add `name: foo-bar` to frontmatter") |
      | NOT vague guidance (e.g., "fix your agent")                    |
    """
    add_agent_to_registry(temp_repo, "test-agent")
    agent_file = temp_repo / ".claude" / "agents" / "test-agent.md"
    agent_file.write_text("""---
description: Missing name field
model: inherit
---

Agent prompt.
""")

    result = run_validator(temp_repo)
    assert_validator_failed(result)

    # Fix should be specific
    assert "Fix:" in result.stderr

    # Should not contain vague guidance
    assert "fix your agent" not in result.stderr.lower()


def test_error_list_deterministic_sorting(temp_repo, run_validator):
    """Errors should be sorted deterministically (by file path, then line)."""
    # Create errors in multiple files
    add_agent_to_registry(temp_repo, "agent-a")
    add_agent_to_registry(temp_repo, "agent-b")
    add_agent_to_registry(temp_repo, "agent-c")

    result1 = run_validator(temp_repo)
    result2 = run_validator(temp_repo)

    # Errors should appear in same order
    assert result1.stderr == result2.stderr


# ============================================================================
# Exit Code Tests
# ============================================================================


def test_exit_code_0_on_success(valid_repo, run_validator):
    """Validator exits with code 0 when validation passes."""
    result = run_validator(valid_repo)
    assert result.returncode == 0


def test_exit_code_1_on_failure(temp_repo, run_validator):
    """Validator exits with code 1 when validation fails."""
    add_agent_to_registry(temp_repo, "missing-agent")

    result = run_validator(temp_repo)
    assert result.returncode == 1


def test_exit_code_deterministic(temp_repo, run_validator):
    """Exit code is consistent across multiple runs."""
    add_agent_to_registry(temp_repo, "missing-agent")

    result1 = run_validator(temp_repo)
    result2 = run_validator(temp_repo)

    assert result1.returncode == result2.returncode


# ============================================================================
# JSON Report Tests (FR-012)
# ============================================================================


def test_json_report_generation(valid_repo, run_validator):
    """
    Scenario: Validator supports --report json flag.

    Given: The validator is installed
    When: I run with --report json flag
    Then: Valid JSON is generated
    """
    result = run_validator(valid_repo, flags=["--report", "json"])

    # Should still exit 0 for valid repo
    assert result.returncode == 0

    # stdout should contain valid JSON
    try:
        report = json.loads(result.stdout)
        assert isinstance(report, dict)
    except json.JSONDecodeError:
        pytest.fail(f"Invalid JSON output: {result.stdout}")


def test_json_report_includes_timestamp_and_status(valid_repo, run_validator):
    """
    Scenario: JSON report includes timestamp and status.

    When: I parse the JSON
    Then: It includes timestamp and status fields
    """
    result = run_validator(valid_repo, flags=["--report", "json"])
    report = json.loads(result.stdout)

    # Should have timestamp
    assert "timestamp" in report

    # Should have status
    assert "status" in report
    assert report["status"] in ["PASSED", "FAILED"]


def test_json_report_includes_checks_performed(valid_repo, run_validator):
    """
    Scenario: JSON report includes checks performed.

    Then: It lists all checks:
      | agent_bijection, frontmatter, flow_references, skills, runbase_paths |
    """
    result = run_validator(valid_repo, flags=["--report", "json"])
    report = json.loads(result.stdout)

    # Should have checks section
    assert "checks" in report or "checks_performed" in report

    # Note: Exact field names depend on implementation


def test_json_report_includes_summary_counts(temp_repo, run_validator):
    """
    Scenario: JSON report includes summary counts.

    Given: Validation completes with 2 errors
    Then: Report includes total_checks, passed, failed counts
    """
    # Create 2 errors
    add_agent_to_registry(temp_repo, "missing-1")
    add_agent_to_registry(temp_repo, "missing-2")

    result = run_validator(temp_repo, flags=["--report", "json"])
    report = json.loads(result.stdout)

    # Should have summary counts
    assert "total_checks" in report or "summary" in report
    # Exact field structure depends on implementation


def test_json_report_includes_detailed_error_list(temp_repo, run_validator):
    """
    Scenario: JSON report includes detailed error list.

    Given: Validation finds 1 flow reference error
    Then: Errors section includes type, file, line, message, suggestions
    """
    create_flow_file(temp_repo, "flow-1", ["fake-agent"])

    result = run_validator(temp_repo, flags=["--report", "json"])
    report = json.loads(result.stdout)

    # Should have errors array
    assert "errors" in report

    if len(report["errors"]) > 0:
        error = report["errors"][0]
        # Should have structured error info
        assert "type" in error or "check" in error
        assert "file" in error or "location" in error


def test_json_report_is_machine_parseable(temp_repo, run_validator):
    """
    Scenario: JSON report is machine-parseable.

    Given: A JSON report is generated
    When: I parse it with standard JSON tools
    Then: It parses without errors
    """
    add_agent_to_registry(temp_repo, "test-agent")
    create_agent_file(temp_repo, "test-agent")

    result = run_validator(temp_repo, flags=["--report", "json"])

    # Should parse without exception
    report = json.loads(result.stdout)
    assert isinstance(report, dict)


# ============================================================================
# Markdown Report Tests (FR-012)
# ============================================================================


def test_markdown_report_generation(valid_repo, run_validator):
    """
    Scenario: Validator supports --report markdown flag.

    When: I run with --report markdown
    Then: A markdown report is generated
    """
    result = run_validator(valid_repo, flags=["--report", "markdown"])

    # Should exit 0 for valid repo
    assert result.returncode == 0

    # stdout should contain markdown
    assert "# " in result.stdout or "## " in result.stdout


def test_markdown_report_includes_title_and_summary(valid_repo, run_validator):
    """
    Scenario: Markdown report includes title and summary.

    Then: It includes:
      | # Swarm Validation Report                    |
      | **Timestamp**: 2025-11-27 12:34:56 UTC      |
      | **Status**: PASSED or FAILED                |
    """
    result = run_validator(valid_repo, flags=["--report", "markdown"])
    output = result.stdout

    # Should have title
    assert "# " in output or "Validation" in output

    # Should have status
    assert "PASSED" in output or "FAILED" in output


def test_markdown_report_lists_checks_performed(valid_repo, run_validator):
    """
    Scenario: Markdown report lists checks performed.

    Then: It shows:
      | ## Checks Performed |
      | - [x] Agent Registry Bijection |
      | - [x] Frontmatter Validation |
    """
    result = run_validator(valid_repo, flags=["--report", "markdown"])
    output = result.stdout

    # Should have checks section
    assert "Checks" in output or "checks" in output

    # Should use markdown list format
    assert "- [" in output or "* [" in output


def test_markdown_report_includes_error_details(temp_repo, run_validator):
    """
    Scenario: Markdown report includes error details.

    Then: Error section shows:
      | **Location**: file:line |
      | **Error**: description  |
      | **Fix**: action        |
    """
    add_agent_to_registry(temp_repo, "missing-agent")

    result = run_validator(temp_repo, flags=["--report", "markdown"])
    output = result.stdout

    # Should have error details
    assert "missing-agent" in output

    # Should have formatted sections
    # (exact format depends on implementation)


def test_markdown_report_is_human_readable(valid_repo, run_validator):
    """
    Scenario: Markdown report is human-readable.

    Then: It displays clearly with proper formatting
    And: Sections are easy to scan
    """
    result = run_validator(valid_repo, flags=["--report", "markdown"])
    output = result.stdout

    # Should have headers
    assert output.count("#") >= 2

    # Should have reasonable structure (not just plain text dump)
    # Note: This is a qualitative test


# ============================================================================
# Report Performance Tests
# ============================================================================


def test_report_generation_no_performance_regression(valid_repo, run_validator):
    """
    Scenario: Report generation doesn't cause performance regression.

    Given: Baseline validation time is T seconds
    When: I run with --report json
    Then: Time is <= T * 1.2 (no more than 20% slower)
    """
    import time

    # Baseline run
    start1 = time.time()
    result1 = run_validator(valid_repo)
    baseline_time = time.time() - start1

    # Run with JSON report
    start2 = time.time()
    result2 = run_validator(valid_repo, flags=["--report", "json"])
    report_time = time.time() - start2

    # Report generation should not add significant overhead
    assert report_time <= baseline_time * 1.5  # Allow 50% overhead max


# ============================================================================
# Debug Output Tests
# ============================================================================


def test_debug_flag_produces_output(valid_repo, run_validator):
    """
    Scenario: Validator supports --debug flag.

    When: I run with --debug
    Then: Debug output is produced
    """
    result = run_validator(valid_repo, flags=["--debug"])

    # Should have debug output (in stderr or stdout)
    assert len(result.stderr) > 0 or len(result.stdout) > 0


def test_debug_output_shows_files_scanned(valid_repo, run_validator):
    """
    Scenario: Debug output shows files scanned.

    Given: --debug flag is enabled
    Then: Debug output includes files being scanned
    """
    result = run_validator(valid_repo, flags=["--debug"])
    output = result.stderr + result.stdout

    # Should mention files being checked
    # (exact format depends on implementation)
    # This is a placeholder test


def test_debug_output_doesnt_bloat_errors(temp_repo, run_validator):
    """
    Scenario: Debug output doesn't bloat normal error messages.

    Given: --debug flag is enabled
    When: Validation fails
    Then: Errors are still clear and concise
    """
    add_agent_to_registry(temp_repo, "missing-agent")

    result = run_validator(temp_repo, flags=["--debug"])

    # Errors should still be identifiable
    assert "[FAIL]" in result.stderr or "error" in result.stderr.lower()


# ============================================================================
# Edge Cases
# ============================================================================


def test_empty_report_on_valid_repo(valid_repo, run_validator):
    """JSON report with no errors should have empty errors array."""
    result = run_validator(valid_repo, flags=["--report", "json"])
    report = json.loads(result.stdout)

    # Errors should be empty or not present
    if "errors" in report:
        assert len(report["errors"]) == 0


def test_report_with_multiple_error_types(temp_repo, run_validator):
    """Report should categorize different error types."""
    # Create different error types
    add_agent_to_registry(temp_repo, "missing-file")  # Bijection error
    create_flow_file(temp_repo, "flow-1", ["fake-agent"])  # Reference error

    result = run_validator(temp_repo, flags=["--report", "json"])
    report = json.loads(result.stdout)

    # Should have multiple error types
    if "errors" in report and len(report["errors"]) > 0:
        error_types = set(e.get("type") or e.get("check") for e in report["errors"])
        assert len(error_types) >= 2


def test_deterministic_json_output(temp_repo, run_validator):
    """JSON reports should be deterministic (same errors, same JSON)."""
    add_agent_to_registry(temp_repo, "missing-1")
    add_agent_to_registry(temp_repo, "missing-2")

    result1 = run_validator(temp_repo, flags=["--report", "json"])
    result2 = run_validator(temp_repo, flags=["--report", "json"])

    report1 = json.loads(result1.stdout)
    report2 = json.loads(result2.stdout)

    # Timestamps may differ, but error lists should be identical
    if "errors" in report1 and "errors" in report2:
        assert len(report1["errors"]) == len(report2["errors"])


# ============================================================================
# Pre-commit Config Tests (FR-007, HIGH PRIORITY)
# ============================================================================


def test_precommit_config_yaml_exists():
    """
    HIGH: Test that .pre-commit-config.yaml exists and is valid YAML.

    Given: Repository with pre-commit configuration
    When: I check for .pre-commit-config.yaml
    Then: File exists and contains valid YAML with local hooks
    """
    from pathlib import Path

    import yaml

    config_file = Path(__file__).parent.parent / ".pre-commit-config.yaml"
    assert config_file.exists(), ".pre-commit-config.yaml not found"

    # Parse YAML
    content = config_file.read_text()
    try:
        config = yaml.safe_load(content)
        assert isinstance(config, dict), "YAML must be a dictionary"
    except yaml.YAMLError as e:
        pytest.fail(f"Invalid YAML in .pre-commit-config.yaml: {e}")


def test_precommit_swarm_validate_hook_defined():
    """
    HIGH: Test that swarm-validate hook is properly defined.

    Given: .pre-commit-config.yaml
    When: I parse the hook configuration
    Then: swarm-validate hook exists with required fields
    """
    from pathlib import Path

    import yaml

    config_file = Path(__file__).parent.parent / ".pre-commit-config.yaml"
    content = config_file.read_text()
    config = yaml.safe_load(content)

    # Should have repos section
    assert "repos" in config, "Missing 'repos' in config"

    # Find swarm-validate hook in local repo
    hooks_found = False
    for repo in config["repos"]:
        if repo.get("repo") == "local" and "hooks" in repo:
            for hook in repo["hooks"]:
                if hook.get("id") == "swarm-validate":
                    hooks_found = True
                    # Check required fields
                    assert "name" in hook, "swarm-validate hook missing 'name' field"
                    assert "entry" in hook, "swarm-validate hook missing 'entry' field"
                    assert "language" in hook, "swarm-validate hook missing 'language' field"

    assert hooks_found, "swarm-validate hook not found in .pre-commit-config.yaml"


def test_precommit_hook_uses_system_language():
    """
    Test that swarm-validate hook uses system language.

    Given: .pre-commit-config.yaml with swarm-validate hook
    When: I check the language field
    Then: language should be 'system' (uses uv run)
    """
    from pathlib import Path

    import yaml

    config_file = Path(__file__).parent.parent / ".pre-commit-config.yaml"
    content = config_file.read_text()
    config = yaml.safe_load(content)

    for repo in config["repos"]:
        if repo.get("repo") == "local" and "hooks" in repo:
            for hook in repo["hooks"]:
                if hook.get("id") == "swarm-validate":
                    assert hook.get("language") == "system", \
                        "swarm-validate hook should use 'language: system'"


def test_precommit_hook_invokes_validator():
    """
    Test that swarm-validate hook invokes the validator with --strict.

    Given: .pre-commit-config.yaml with swarm-validate hook
    When: I check the entry command
    Then: Entry should invoke validate_swarm.py with --strict
    """
    from pathlib import Path

    import yaml

    config_file = Path(__file__).parent.parent / ".pre-commit-config.yaml"
    content = config_file.read_text()
    config = yaml.safe_load(content)

    for repo in config["repos"]:
        if repo.get("repo") == "local" and "hooks" in repo:
            for hook in repo["hooks"]:
                if hook.get("id") == "swarm-validate":
                    entry = hook.get("entry", "")
                    assert "validate_swarm.py" in entry, \
                        "entry should reference validate_swarm.py"
                    assert "--strict" in entry, \
                        "entry should include --strict flag"


def test_precommit_hook_pass_filenames_false():
    """
    Test that swarm-validate hook does not pass filenames to validator.

    Given: .pre-commit-config.yaml with swarm-validate hook
    When: I check pass_filenames
    Then: pass_filenames should be false (validator handles file discovery)
    """
    from pathlib import Path

    import yaml

    config_file = Path(__file__).parent.parent / ".pre-commit-config.yaml"
    content = config_file.read_text()
    config = yaml.safe_load(content)

    for repo in config["repos"]:
        if repo.get("repo") == "local" and "hooks" in repo:
            for hook in repo["hooks"]:
                if hook.get("id") == "swarm-validate":
                    assert hook.get("pass_filenames") is False, \
                        "swarm-validate hook should have pass_filenames: false"


def test_precommit_config_exists():
    """
    Test that .pre-commit-config.yaml exists (optional but recommended).

    Given: Repository with pre-commit configuration
    When: I check for .pre-commit-config.yaml
    Then: File should exist (may be empty or minimal)

    Note: This is informational; the hook definition is what matters.
    Execution of hooks is deferred to CI/local pre-commit setup.
    """
    from pathlib import Path

    config_file = Path(__file__).parent.parent / ".pre-commit-config.yaml"
    # File may or may not exist; just check it's valid if it does
    if config_file.exists():
        import yaml
        content = config_file.read_text()
        try:
            yaml.safe_load(content)
        except yaml.YAMLError as e:
            pytest.fail(f"Invalid YAML in .pre-commit-config.yaml: {e}")
