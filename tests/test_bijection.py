"""
Test suite for agent registry bijection validation (FR-001).

Tests the validator's ability to ensure correspondence between
swarm/AGENTS.md entries and .claude/agents/*.md files.

TRANSITION MODE: During the architecture transition from .claude/agents/ to
swarm/config/agents/, we only enforce file→registry bijection (orphaned files
must be registered). Registry→file is intentionally skipped (registered agents
don't need .claude/agents/ files during migration).

BDD Scenarios covered:
- Scenario 1: Agent registry matches implementation files (happy path)
- Scenario 2: Registry→file check skipped in transition mode (was: detect missing file)
- Scenario 3: Detect orphaned .claude/agents file without registry entry
- Scenario 4: Detect filename/registry key mismatch (orphan detection)
- Scenario 5: Report all file→registry errors in single run
"""

from conftest import (
    add_agent_to_registry,
    assert_error_contains,
    assert_error_type,
    assert_validator_failed,
    assert_validator_passed,
    create_agent_file,
    parse_errors,
)

# ============================================================================
# Happy Path Tests
# ============================================================================


def test_valid_bijection(valid_repo, run_validator):
    """
    Scenario 1: Agent registry matches implementation files (happy path).

    Given: 3 agents in swarm/AGENTS.md
    And: 3 matching .claude/agents/*.md files
    When: I run the validator
    Then: Validator exits with code 0
    And: No agent-related errors are reported
    """
    result = run_validator(valid_repo)
    assert_validator_passed(result)
    assert "BIJECTION" not in result.stderr


def test_empty_registry_no_agents(temp_repo, run_validator):
    """Valid state: empty registry with no agent files."""
    result = run_validator(temp_repo)
    assert_validator_passed(result)


# ============================================================================
# Missing Agent File Tests (TRANSITION MODE: Now expected to pass)
# ============================================================================


def test_missing_agent_file(temp_repo, run_validator):
    """
    TRANSITION MODE: Registry→file check is skipped.

    Previously: Validator would fail when agent in registry has no file.
    Now: Validator passes because we only check file→registry direction.

    The new architecture uses swarm/config/agents/ as the source of truth.
    """
    # Add agent to registry but don't create file
    add_agent_to_registry(temp_repo, "foo-bar")

    result = run_validator(temp_repo)
    # TRANSITION: Registry→file check skipped, so validation passes
    assert_validator_passed(result)


def test_multiple_missing_agent_files(temp_repo, run_validator):
    """TRANSITION MODE: Multiple agents in registry with no files should pass."""
    add_agent_to_registry(temp_repo, "agent-1")
    add_agent_to_registry(temp_repo, "agent-2")
    add_agent_to_registry(temp_repo, "agent-3")

    result = run_validator(temp_repo)
    # TRANSITION: Registry→file check skipped
    assert_validator_passed(result)


# ============================================================================
# Orphaned Agent File Tests
# ============================================================================


def test_orphaned_agent_file(temp_repo, run_validator):
    """
    Scenario 3: Detect orphaned .claude/agents file without registry entry.

    Given: .claude/agents/baz.md exists with valid frontmatter
    And: swarm/AGENTS.md does not contain entry for 'baz'
    When: I run the validator
    Then: Validator exits with code 1
    And: Error message explains orphan and suggests fix
    """
    # Create agent file without registry entry
    create_agent_file(temp_repo, "baz")

    result = run_validator(temp_repo)
    assert_validator_failed(result)
    assert_error_type(result.stderr, "BIJECTION")
    assert_error_contains(result.stderr, "baz")
    assert_error_contains(result.stderr, "AGENTS.md")
    assert_error_contains(result.stderr, "Fix:")


def test_multiple_orphaned_agent_files(temp_repo, run_validator):
    """Multiple orphaned agent files."""
    create_agent_file(temp_repo, "orphan-1")
    create_agent_file(temp_repo, "orphan-2")
    create_agent_file(temp_repo, "orphan-3")

    result = run_validator(temp_repo)
    assert_validator_failed(result)

    errors = parse_errors(result.stderr)
    # Should report errors for all 3 orphans
    assert len(errors) >= 3


# ============================================================================
# Filename Mismatch Tests
# ============================================================================


def test_filename_key_mismatch(temp_repo, run_validator):
    """
    Scenario 4: Detect filename/registry key mismatch.

    Given: swarm/AGENTS.md contains entry for agent 'foo-bar' at line 42
    And: .claude/agents/foobar.md exists (wrong name)
    When: I run the validator
    Then: Validator exits with code 1
    And: Error message explains mismatch
    """
    # Add agent to registry with hyphen
    add_agent_to_registry(temp_repo, "foo-bar")

    # Create agent file without hyphen (mismatch)
    create_agent_file(temp_repo, "foobar")

    result = run_validator(temp_repo)
    assert_validator_failed(result)
    assert_error_type(result.stderr, "BIJECTION")


def test_case_sensitive_matching(temp_repo, run_validator):
    """Agent keys must match exactly (case-sensitive)."""
    # Registry: "TestAgent"
    add_agent_to_registry(temp_repo, "TestAgent")

    # File: "testagent.md" (wrong case)
    create_agent_file(temp_repo, "testagent")

    result = run_validator(temp_repo)
    assert_validator_failed(result)


def test_exact_name_match_required(temp_repo, run_validator):
    """Agent key must match filename exactly."""
    # Registry: "test-agent"
    add_agent_to_registry(temp_repo, "test-agent")

    # File: "test_agent.md" (underscore instead of hyphen)
    agents_dir = temp_repo / ".claude" / "agents"
    agent_file = agents_dir / "test_agent.md"
    agent_file.write_text("""---
name: test_agent
description: Test agent
model: inherit
---

Agent prompt.
""")

    result = run_validator(temp_repo)
    assert_validator_failed(result)


# ============================================================================
# Multiple Errors Tests
# ============================================================================


def test_multiple_bijection_errors(temp_repo, run_validator):
    """
    TRANSITION MODE: Report file→registry errors in single run.

    Note: Missing file errors (registry→file) are now skipped in transition mode.
    Only orphaned file errors (file→registry) are reported.
    """
    # This would be an error with full bijection, but skipped in transition mode
    add_agent_to_registry(temp_repo, "agent-missing")

    # Error 1: Orphaned file (still detected)
    create_agent_file(temp_repo, "agent-orphan")

    # Error 2: Name mismatch creates an orphan (still detected)
    add_agent_to_registry(temp_repo, "agent-mismatch")
    create_agent_file(temp_repo, "agentmismatch")

    result = run_validator(temp_repo)
    assert_validator_failed(result)

    # TRANSITION: Only 2 errors now (orphan + mismatch orphan)
    assert result.stderr.count("[FAIL]") >= 2


def test_mixed_valid_and_invalid_agents(valid_repo, run_validator):
    """TRANSITION MODE: Orphan detected, missing file ignored."""
    # valid_repo has 3 valid agents

    # Missing file: skipped in transition mode
    add_agent_to_registry(valid_repo, "invalid-missing")

    # Orphaned file: still detected
    create_agent_file(valid_repo, "invalid-orphan")

    result = run_validator(valid_repo)
    assert_validator_failed(result)

    errors = parse_errors(result.stderr)
    # TRANSITION: Only 1 error (orphan), missing file check skipped
    assert len(errors) >= 1


# ============================================================================
# Edge Cases
# ============================================================================


def test_agent_with_special_characters_in_name(temp_repo, run_validator):
    """Agent names with hyphens, numbers, etc."""
    agent_name = "test-agent-123-special"
    add_agent_to_registry(temp_repo, agent_name)
    create_agent_file(temp_repo, agent_name)

    result = run_validator(temp_repo)
    assert_validator_passed(result)


def test_empty_agents_directory(temp_repo, run_validator):
    """TRANSITION MODE: Registry has agents but no files - should pass.

    Previously this would fail (missing files). Now registry→file check is
    skipped during transition, so validation passes.
    """
    add_agent_to_registry(temp_repo, "agent-1")
    add_agent_to_registry(temp_repo, "agent-2")

    result = run_validator(temp_repo)
    # TRANSITION: Registry→file check skipped
    assert_validator_passed(result)


def test_agents_md_with_only_comments(temp_repo, run_validator):
    """AGENTS.md with comments but no agents - should pass."""
    agents_md = temp_repo / "swarm" / "AGENTS.md"
    agents_md.write_text("""# Agent Registry

## Comments only, no actual agent entries

This is a placeholder file.
""")

    result = run_validator(temp_repo)
    assert_validator_passed(result)


def test_very_long_agent_name(temp_repo, run_validator):
    """Agent with very long name (edge case)."""
    long_name = "test-agent-with-very-long-name-that-exceeds-typical-limits-but-is-still-valid"
    add_agent_to_registry(temp_repo, long_name)
    create_agent_file(temp_repo, long_name)

    result = run_validator(temp_repo)
    assert_validator_passed(result)


# ============================================================================
# Error Message Quality Tests
# ============================================================================


def test_error_message_includes_file_and_line(temp_repo, run_validator):
    """Error messages include file path for orphaned files."""
    # Use orphaned file (file→registry check still runs)
    create_agent_file(temp_repo, "orphan-agent")

    result = run_validator(temp_repo)
    assert_validator_failed(result)

    # Should mention the orphan file path
    assert "orphan-agent" in result.stderr


def test_error_message_includes_fix_action(temp_repo, run_validator):
    """Error messages include actionable fix guidance."""
    # Use orphaned file (file→registry check still runs)
    create_agent_file(temp_repo, "orphan-agent")

    result = run_validator(temp_repo)
    assert_validator_failed(result)

    # Should include "Fix:" line
    assert "Fix:" in result.stderr


def test_error_message_format(temp_repo, run_validator):
    """Error messages follow standard format: [FAIL] TYPE: location problem -> Fix: action."""
    create_agent_file(temp_repo, "orphan-agent")

    result = run_validator(temp_repo)
    assert_validator_failed(result)

    # Check format
    assert "[FAIL] BIJECTION:" in result.stderr or "[FAIL]" in result.stderr
    assert "Fix:" in result.stderr


# ============================================================================
# Performance Tests
# ============================================================================


def test_bijection_check_performance(valid_repo, run_validator):
    """Bijection validation should be fast (part of < 10s total budget)."""
    import time

    start = time.time()
    result = run_validator(valid_repo)
    elapsed = time.time() - start

    assert_validator_passed(result)
    # Bijection check should be fast. CI runs on noisy shared runners, and Windows
    # subprocess startup is significantly slower, so we keep a 10s guardrail.
    # Locally this typically runs in ~0.2-0.5s on Unix, ~2-5s on Windows.
    assert elapsed < 10.0, f"bijection check too slow: {elapsed:.3f}s (target <10.0s)"


# ============================================================================
# Determinism Tests
# ============================================================================


def test_bijection_validation_is_deterministic(temp_repo, run_validator):
    """Running validation twice produces identical results."""
    add_agent_to_registry(temp_repo, "agent-1")
    create_agent_file(temp_repo, "orphan-agent")

    result1 = run_validator(temp_repo)
    result2 = run_validator(temp_repo)

    # Same exit code
    assert result1.returncode == result2.returncode

    # Same error messages (deterministic order)
    assert result1.stderr == result2.stderr
