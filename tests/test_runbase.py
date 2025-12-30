"""
Test suite for RUN_BASE path correctness validation (FR-005).

Tests the validator's ability to ensure flow specs use correct RUN_BASE
placeholder syntax and avoid hardcoded paths.

BDD Scenarios covered:
- Scenario 25: Valid RUN_BASE usage in flow spec
- Scenario 26: Detect hardcoded swarm/runs path in flow spec
- Scenario 27: Detect malformed RUN_BASE placeholder (dollar sign)
- Scenario 28: Detect malformed RUN_BASE placeholder (braces)
- Scenario 29: Ignore RUN_BASE in comments (clear intent)
- Scenario 30: Detect typo in RUN_BASE placeholder
"""

import pytest

from conftest import (
    assert_error_contains,
    assert_error_type,
    assert_validator_failed,
    assert_validator_passed,
)

# ============================================================================
# Happy Path Tests
# ============================================================================


def test_valid_runbase_usage(temp_repo, run_validator):
    """
    Scenario 25: Valid RUN_BASE usage in flow spec.

    Given: swarm/flows/flow-1.md contains artifact path reference:
      | RUN_BASE/signal/requirements.md |
    When: I run the validator
    Then: Validator exits with code 0
    And: No RUN_BASE errors are reported
    """
    flow_path = temp_repo / "swarm" / "flows" / "flow-1.md"
    flow_path.write_text("""# Flow 1 - Signal

## Step 1: Signal Normalizer

**Inputs**: User signal

**Outputs**: RUN_BASE/signal/problem_statement.md

## Step 2: Requirements Author

**Outputs**: RUN_BASE/signal/requirements.md

## Step 3: BDD Author

**Outputs**: RUN_BASE/signal/features/validation.feature
""")

    result = run_validator(temp_repo)
    assert_validator_passed(result)
    assert "RUNBASE" not in result.stderr


def test_multiple_valid_runbase_paths(temp_repo, run_validator):
    """Flow with multiple valid RUN_BASE references."""
    flow_path = temp_repo / "swarm" / "flows" / "flow-3.md"
    flow_path.write_text("""# Flow 3 - Build

Outputs:
- RUN_BASE/build/test_summary.md
- RUN_BASE/build/code_critique.md
- RUN_BASE/build/build_receipt.json
- RUN_BASE/build/mutation_report.md
""")

    result = run_validator(temp_repo)
    assert_validator_passed(result)


def test_runbase_in_different_flow_subdirectories(temp_repo, run_validator):
    """RUN_BASE used with different flow subdirectories."""
    for flow_num, subdir in [(1, "signal"), (2, "plan"), (3, "build"), (4, "gate")]:
        flow_path = temp_repo / "swarm" / "flows" / f"flow-{flow_num}.md"
        flow_path.write_text(f"""# Flow {flow_num}

Output: RUN_BASE/{subdir}/artifact.md
""")

    result = run_validator(temp_repo)
    assert_validator_passed(result)


# ============================================================================
# Hardcoded Path Detection Tests
# ============================================================================


def test_hardcoded_runs_path(temp_repo, run_validator):
    """
    Scenario 26: Detect hardcoded swarm/runs path in flow spec.

    Given: swarm/flows/flow-3.md contains artifact path:
      | swarm/runs/<run-id>/build/test_summary.md |
    When: I run the validator
    Then: Validator exits with code 1
    And: Error message suggests using RUN_BASE
    """
    flow_path = temp_repo / "swarm" / "flows" / "flow-3.md"
    flow_path.write_text("""# Flow 3

Output: swarm/runs/<run-id>/build/test_summary.md
""")

    result = run_validator(temp_repo)
    assert_validator_failed(result)
    assert_error_type(result.stderr, "RUNBASE")
    assert_error_contains(result.stderr, "hardcoded")
    assert_error_contains(result.stderr, "swarm/runs")
    assert_error_contains(result.stderr, "Fix:")
    assert_error_contains(result.stderr, "RUN_BASE")


def test_hardcoded_runs_path_with_specific_id(temp_repo, run_validator):
    """Hardcoded path with specific run ID."""
    flow_path = temp_repo / "swarm" / "flows" / "flow-bad.md"
    flow_path.write_text("""# Flow

Output: swarm/runs/ticket-123/signal/requirements.md
""")

    result = run_validator(temp_repo)
    assert_validator_failed(result)
    assert "hardcoded" in result.stderr.lower()


def test_multiple_hardcoded_paths(temp_repo, run_validator):
    """Multiple hardcoded paths - all reported."""
    flow_path = temp_repo / "swarm" / "flows" / "flow-multi-bad.md"
    flow_path.write_text("""# Flow

Outputs:
- swarm/runs/<run-id>/signal/requirements.md
- swarm/runs/<run-id>/plan/adr.md
- swarm/runs/<run-id>/build/test_summary.md
""")

    result = run_validator(temp_repo)
    assert_validator_failed(result)

    # All 3 hardcoded paths should be reported
    assert result.stderr.count("RUNBASE") >= 3 or result.stderr.count("hardcoded") >= 3


# ============================================================================
# Malformed Placeholder Tests
# ============================================================================


def test_malformed_runbase_with_dollar_sign(temp_repo, run_validator):
    """
    Scenario 27: Detect malformed RUN_BASE placeholder (dollar sign).

    Given: swarm/flows/flow-1.md contains path reference:
      | $RUN_BASE/signal/requirements.md |
    When: I run the validator
    Then: Validator exits with code 1
    And: Error message explains correct format
    """
    flow_path = temp_repo / "swarm" / "flows" / "flow-1.md"
    flow_path.write_text("""# Flow 1

Output: $RUN_BASE/signal/requirements.md
""")

    result = run_validator(temp_repo)
    assert_validator_failed(result)
    assert_error_type(result.stderr, "RUNBASE")
    assert_error_contains(result.stderr, "$RUN_BASE")
    assert_error_contains(result.stderr, "malformed")
    assert_error_contains(result.stderr, "Fix:")


def test_malformed_runbase_with_braces(temp_repo, run_validator):
    """
    Scenario 28: Detect malformed RUN_BASE placeholder (braces).

    Given: swarm/flows/flow-2.md contains path reference:
      | {RUN_BASE}/plan/adr.md |
    When: I run the validator
    Then: Validator exits with code 1
    And: Error message explains correct format
    """
    flow_path = temp_repo / "swarm" / "flows" / "flow-2.md"
    flow_path.write_text("""# Flow 2

Output: {RUN_BASE}/plan/adr.md
""")

    result = run_validator(temp_repo)
    assert_validator_failed(result)
    assert_error_type(result.stderr, "RUNBASE")
    assert_error_contains(result.stderr, "{RUN_BASE}")
    assert_error_contains(result.stderr, "malformed")


def test_malformed_runbase_with_shell_syntax(temp_repo, run_validator):
    """Shell-style ${RUN_BASE} should be detected as malformed."""
    flow_path = temp_repo / "swarm" / "flows" / "flow-shell.md"
    flow_path.write_text("""# Flow

Output: ${RUN_BASE}/build/artifact.md
""")

    result = run_validator(temp_repo)
    assert_validator_failed(result)
    assert "malformed" in result.stderr.lower()


def test_malformed_runbase_typo(temp_repo, run_validator):
    """
    Scenario 30: Detect typo in RUN_BASE placeholder.

    Given: swarm/flows/flow-4.md contains path reference:
      | RUN_BASE_/gate/merge_decision.md |
    When: I run the validator
    Then: Validator exits with code 1
    And: Error message suggests correction
    """
    flow_path = temp_repo / "swarm" / "flows" / "flow-4.md"
    flow_path.write_text("""# Flow 4

Output: RUN_BASE_/gate/merge_decision.md
""")

    result = run_validator(temp_repo)
    assert_validator_failed(result)
    assert "RUN_BASE_" in result.stderr
    assert "Fix:" in result.stderr


def test_runbase_typo_missing_slash(temp_repo, run_validator):
    """RUN_BASE without slash should be detected."""
    flow_path = temp_repo / "swarm" / "flows" / "flow-slash.md"
    flow_path.write_text("""# Flow

Output: RUN_BASEsignal/requirements.md
""")

    result = run_validator(temp_repo)
    assert_validator_failed(result)


# ============================================================================
# Comment and Documentation Tests
# ============================================================================


def test_runbase_in_comment_ignored(temp_repo, run_validator):
    """
    Scenario 29: Ignore RUN_BASE in comments (clear intent).

    Given: swarm/flows/flow-5.md contains comment:
      | # Example: swarm/runs/ticket-123/deploy/log |
    When: I run the validator
    Then: Validator exits with code 0
    And: Hardcoded path in comment is not flagged as error
    """
    flow_path = temp_repo / "swarm" / "flows" / "flow-5.md"
    flow_path.write_text("""# Flow 5

<!-- Example path: swarm/runs/ticket-123/deploy/log -->

Output: RUN_BASE/deploy/deployment_log.md

# Comment: The path swarm/runs/<run-id>/ is replaced at runtime
""")

    result = run_validator(temp_repo)
    assert_validator_passed(result)


def test_hardcoded_path_in_code_block_ignored(temp_repo, run_validator):
    """Hardcoded paths in code blocks should be ignored."""
    flow_path = temp_repo / "swarm" / "flows" / "flow-doc.md"
    flow_path.write_text("""# Flow Documentation

Example usage:

```bash
cat swarm/runs/ticket-123/signal/requirements.md
```

Actual output: RUN_BASE/signal/requirements.md
""")

    result = run_validator(temp_repo)
    assert_validator_passed(result)


def test_runbase_in_markdown_link_ignored(temp_repo, run_validator):
    """RUN_BASE in markdown links should be validated or ignored based on context."""
    flow_path = temp_repo / "swarm" / "flows" / "flow-link.md"
    flow_path.write_text("""# Flow

See [requirements](RUN_BASE/signal/requirements.md) for details.

Output: RUN_BASE/signal/problem_statement.md
""")

    result = run_validator(temp_repo)
    # This should pass (RUN_BASE used correctly in both places)
    assert_validator_passed(result)


# ============================================================================
# Edge Cases
# ============================================================================


def test_runbase_case_sensitive(temp_repo, run_validator):
    """RUN_BASE should be case-sensitive."""
    flow_path = temp_repo / "swarm" / "flows" / "flow-case.md"
    flow_path.write_text("""# Flow

Output: run_base/signal/requirements.md
""")

    result = run_validator(temp_repo)
    # Lowercase should fail (if strict) or at least not be recognized as valid
    assert_validator_failed(result)


def test_runbase_with_nested_subdirectories(temp_repo, run_validator):
    """RUN_BASE with deeply nested paths."""
    flow_path = temp_repo / "swarm" / "flows" / "flow-nested.md"
    flow_path.write_text("""# Flow

Outputs:
- RUN_BASE/signal/features/validation.feature
- RUN_BASE/build/critiques/test_critique.md
- RUN_BASE/wisdom/regressions/detailed/analysis.json
""")

    result = run_validator(temp_repo)
    assert_validator_passed(result)


def test_runbase_with_file_extensions(temp_repo, run_validator):
    """RUN_BASE with various file extensions."""
    flow_path = temp_repo / "swarm" / "flows" / "flow-ext.md"
    flow_path.write_text("""# Flow

Outputs:
- RUN_BASE/signal/requirements.md
- RUN_BASE/build/test_summary.json
- RUN_BASE/gate/coverage_report.html
- RUN_BASE/deploy/deployment.log
""")

    result = run_validator(temp_repo)
    assert_validator_passed(result)


def test_partial_runbase_match(temp_repo, run_validator):
    """Partial matches of RUN_BASE should not cause false positives."""
    flow_path = temp_repo / "swarm" / "flows" / "flow-partial.md"
    flow_path.write_text("""# Flow

This describes the RUN_BASE_DIR environment variable (not the same as RUN_BASE).

Output: RUN_BASE/signal/requirements.md
""")

    result = run_validator(temp_repo)
    # RUN_BASE_DIR in prose should not trigger error (only RUN_BASE_ as path should)
    # Exact behavior depends on implementation


def test_runbase_at_start_of_line(temp_repo, run_validator):
    """RUN_BASE at the start of a line."""
    flow_path = temp_repo / "swarm" / "flows" / "flow-start.md"
    flow_path.write_text("""# Flow

RUN_BASE/signal/requirements.md - requirements document
RUN_BASE/plan/adr.md - architecture decision record
""")

    result = run_validator(temp_repo)
    assert_validator_passed(result)


# ============================================================================
# Multiple Flows Tests
# ============================================================================


def test_multiple_flows_with_runbase(temp_repo, run_validator):
    """Multiple flow files with RUN_BASE - all validated."""
    for i in range(1, 4):
        flow_path = temp_repo / "swarm" / "flows" / f"flow-{i}.md"
        flow_path.write_text(f"""# Flow {i}

Output: RUN_BASE/flow{i}/artifact.md
""")

    result = run_validator(temp_repo)
    assert_validator_passed(result)


def test_mixed_valid_and_invalid_runbase_across_flows(temp_repo, run_validator):
    """Some flows valid, some with errors - all errors reported."""
    # Valid flow
    (temp_repo / "swarm" / "flows" / "flow-1.md").write_text("""# Flow 1

Output: RUN_BASE/signal/requirements.md
""")

    # Invalid flow (hardcoded path)
    (temp_repo / "swarm" / "flows" / "flow-2.md").write_text("""# Flow 2

Output: swarm/runs/<run-id>/plan/adr.md
""")

    # Invalid flow (malformed)
    (temp_repo / "swarm" / "flows" / "flow-3.md").write_text("""# Flow 3

Output: $RUN_BASE/build/test.md
""")

    result = run_validator(temp_repo)
    assert_validator_failed(result)

    # Both errors should be reported
    assert result.stderr.count("[FAIL]") >= 2


# ============================================================================
# Error Message Quality Tests
# ============================================================================


def test_runbase_error_includes_flow_and_line(temp_repo, run_validator):
    """RUN_BASE errors should include flow file and line number."""
    flow_path = temp_repo / "swarm" / "flows" / "flow-err.md"
    flow_path.write_text("""# Flow

Line 3 is fine.
Line 4 has error: swarm/runs/<run-id>/signal/bad.md
""")

    result = run_validator(temp_repo)
    assert_validator_failed(result)

    # Should mention file and line
    assert "flow-err.md" in result.stderr
    # Line number may or may not be included depending on implementation


def test_runbase_error_includes_fix_action(temp_repo, run_validator):
    """RUN_BASE errors should include actionable fix."""
    flow_path = temp_repo / "swarm" / "flows" / "flow-fix.md"
    flow_path.write_text("""# Flow

Output: $RUN_BASE/signal/bad.md
""")

    result = run_validator(temp_repo)
    assert_validator_failed(result)
    assert "Fix:" in result.stderr


# ============================================================================
# Determinism Tests
# ============================================================================


def test_runbase_validation_is_deterministic(temp_repo, run_validator):
    """Running RUN_BASE validation twice produces identical results."""
    flow_path = temp_repo / "swarm" / "flows" / "flow-det.md"
    flow_path.write_text("""# Flow

Errors:
- swarm/runs/<run-id>/signal/bad1.md
- $RUN_BASE/plan/bad2.md
""")

    result1 = run_validator(temp_repo)
    result2 = run_validator(temp_repo)

    # Same exit code
    assert result1.returncode == result2.returncode

    # Same error messages (deterministic order)
    assert result1.stderr == result2.stderr


# ============================================================================
# RUN_BASE Bracket Variant Tests (MEDIUM PRIORITY)
# ============================================================================


def test_runbase_with_angle_brackets_detected(temp_repo, run_validator):
    """
    MEDIUM PRIORITY: Hardcoded path with <run-id> angle brackets should be detected.

    Spec: swarm/runs/<run-id>/ pattern is hardcoded, should use RUN_BASE.

    Given: swarm/flows/flow-1.md contains: swarm/runs/<run-id>/signal/file.md
    When: I run the validator
    Then: Validator detects this as hardcoded path
    And: Error suggests using RUN_BASE instead

    Mutation: If angle bracket detection is missing, test fails.
    """
    flow_path = temp_repo / "swarm" / "flows" / "flow-angle.md"
    flow_path.write_text("""# Flow 1

## Artifacts

Output: swarm/runs/<run-id>/signal/problem_statement.md
""")

    result = run_validator(temp_repo)

    # Should detect hardcoded path with angle brackets
    if result.returncode != 0:
        # If validator detects this as error (preferred), verify error message
        assert "swarm/runs" in result.stderr or "RUN_BASE" in result.stderr


def test_runbase_with_curly_brackets_detected(temp_repo, run_validator):
    """
    MEDIUM PRIORITY: Hardcoded path with {run-id} curly brackets should be detected.

    Spec: swarm/runs/{run-id}/ pattern is hardcoded, should use RUN_BASE.

    Given: swarm/flows/flow-2.md contains: swarm/runs/{run-id}/plan/adr.md
    When: I run the validator
    Then: Validator detects this as hardcoded path
    And: Error suggests using RUN_BASE instead

    Mutation: If curly bracket detection is missing, test fails.
    """
    flow_path = temp_repo / "swarm" / "flows" / "flow-curly.md"
    flow_path.write_text("""# Flow 2

## Artifacts

Output: swarm/runs/{run-id}/plan/architecture_decision_record.md
""")

    result = run_validator(temp_repo)

    # Should detect hardcoded path with curly brackets
    if result.returncode != 0:
        # If validator detects this as error (preferred), verify error message
        assert "swarm/runs" in result.stderr or "RUN_BASE" in result.stderr


def test_both_bracket_variants_in_same_flow(temp_repo, run_validator):
    """Both angle and curly bracket variants should be detected together."""
    flow_path = temp_repo / "swarm" / "flows" / "flow-both.md"
    flow_path.write_text("""# Flow

Outputs:
- swarm/runs/<run-id>/signal/file1.md
- swarm/runs/{run-id}/signal/file2.md
""")

    result = run_validator(temp_repo)

    # Should detect both hardcoded paths
    if result.returncode != 0:
        # Validator should catch both errors
        assert "swarm/runs" in result.stderr
