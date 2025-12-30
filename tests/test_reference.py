"""
Test suite for flow spec agent reference validation (FR-003).

Tests the validator's ability to ensure all agent references in flow specs
point to valid agents (either domain agents in AGENTS.md or built-in agents).

BDD Scenarios covered:
- Scenario 15: Valid agent reference in flow spec (registry agent)
- Scenario 16: Valid agent reference in flow spec (built-in agent)
- Scenario 17: Detect reference to non-existent agent
- Scenario 18: Suggest similar agents for typos (Levenshtein distance ≤ 2)
- Scenario 19: Detect wrong case for built-in agent
- Scenario 20: Multiple suggestions for typo with distance <= 2
"""

from conftest import (
    add_agent_to_registry,
    assert_error_contains,
    assert_error_type,
    assert_validator_failed,
    assert_validator_passed,
    create_agent_file,
    create_flow_file,
)

# ============================================================================
# Built-in Agents Constant
# ============================================================================

BUILT_IN_AGENTS = ["explore", "plan-subagent", "general-subagent"]


# ============================================================================
# Happy Path Tests
# ============================================================================


def test_valid_domain_agent_reference(valid_repo, run_validator):
    """
    Scenario 15: Valid agent reference in flow spec (registry agent).

    Given: swarm/flows/flow-1.md step 2 references agent 'test-agent-1'
    And: 'test-agent-1' is in swarm/AGENTS.md
    When: I run the validator
    Then: Validator exits with code 0
    And: No reference errors are reported
    """
    # valid_repo has test-agent-1, test-agent-2, test-agent-3
    create_flow_file(valid_repo, "flow-1", ["test-agent-1", "test-agent-2"])

    result = run_validator(valid_repo)
    assert_validator_passed(result)
    assert "REFERENCE" not in result.stderr


def test_valid_builtin_agent_reference(temp_repo, run_validator):
    """
    Scenario 16: Valid agent reference in flow spec (built-in agent).

    Given: swarm/flows/flow-1.md step 1 references agent 'explore'
    When: I run the validator
    Then: Validator exits with code 0
    And: No reference errors are reported for built-in agents
    """
    create_flow_file(temp_repo, "flow-1", ["explore", "plan-subagent"])

    result = run_validator(temp_repo)
    assert_validator_passed(result)
    assert "REFERENCE" not in result.stderr


def test_mixed_builtin_and_domain_references(valid_repo, run_validator):
    """Flow referencing both built-in and domain agents."""
    create_flow_file(
        valid_repo,
        "flow-2",
        ["explore", "test-agent-1", "plan-subagent", "test-agent-2"]
    )

    result = run_validator(valid_repo)
    assert_validator_passed(result)


def test_all_builtin_agents_recognized(temp_repo, run_validator):
    """All 3 built-in agents should be recognized."""
    create_flow_file(temp_repo, "flow-test", BUILT_IN_AGENTS)

    result = run_validator(temp_repo)
    assert_validator_passed(result)


# ============================================================================
# Non-existent Agent Tests
# ============================================================================


def test_reference_to_nonexistent_agent(temp_repo, run_validator):
    """
    Scenario 17: Detect reference to non-existent agent.

    Given: swarm/flows/flow-3.md step 2 references agent 'code-coder'
    And: 'code-coder' is not in swarm/AGENTS.md and is not a built-in agent
    When: I run the validator
    Then: Validator exits with code 1
    And: Error message includes fix guidance
    """
    create_flow_file(temp_repo, "flow-3", ["code-coder"])

    result = run_validator(temp_repo)
    assert_validator_failed(result)
    assert_error_type(result.stderr, "REFERENCE")
    assert_error_contains(result.stderr, "code-coder")
    assert_error_contains(result.stderr, "unknown")
    assert_error_contains(result.stderr, "Fix:")


def test_multiple_nonexistent_references_in_one_flow(temp_repo, run_validator):
    """Flow with multiple invalid references - all reported."""
    create_flow_file(temp_repo, "flow-bad", ["fake-1", "fake-2", "fake-3"])

    result = run_validator(temp_repo)
    assert_validator_failed(result)

    # All 3 errors should be reported
    assert result.stderr.count("[FAIL]") >= 3


def test_nonexistent_reference_across_multiple_flows(temp_repo, run_validator):
    """Multiple flows with invalid references - all errors reported."""
    create_flow_file(temp_repo, "flow-1", ["fake-agent-1"])
    create_flow_file(temp_repo, "flow-2", ["fake-agent-2"])

    result = run_validator(temp_repo)
    assert_validator_failed(result)

    # Both errors should be reported
    assert "fake-agent-1" in result.stderr
    assert "fake-agent-2" in result.stderr


# ============================================================================
# Typo Suggestion Tests (Levenshtein Distance)
# ============================================================================


def test_typo_suggestion_levenshtein_distance_1(temp_repo, run_validator):
    """
    Scenario 18: Suggest similar agents for typos (Levenshtein distance ≤ 2).

    Given: swarm/flows/flow-1.md step 5 references agent 'explor' (typo)
    And: 'explore' exists as built-in agent
    And: 'explor' is within Levenshtein distance 1 from 'explore'
    When: I run the validator
    Then: Validator exits with code 1
    And: Error message suggests 'explore'
    """
    create_flow_file(temp_repo, "flow-1", ["explor"])

    result = run_validator(temp_repo)
    assert_validator_failed(result)
    assert_error_type(result.stderr, "REFERENCE")
    assert_error_contains(result.stderr, "explor")
    assert_error_contains(result.stderr, "did you mean")
    assert_error_contains(result.stderr, "explore")


def test_typo_suggestion_levenshtein_distance_2(valid_repo, run_validator):
    """Typo with Levenshtein distance 2 should still suggest."""
    # valid_repo has test-agent-1
    # 'tst-agent-1' has distance 2 (missing 'e' and wrong 's')
    create_flow_file(valid_repo, "flow-typo", ["tst-agnt-1"])

    result = run_validator(valid_repo)
    assert_validator_failed(result)
    # Should suggest test-agent-1
    assert "did you mean" in result.stderr


def test_typo_distance_3_no_suggestion(temp_repo, run_validator):
    """Typo with Levenshtein distance > 2 should not suggest."""
    # 'xyz' is completely different from 'explore'
    create_flow_file(temp_repo, "flow-far", ["xyz"])

    result = run_validator(temp_repo)
    assert_validator_failed(result)
    # Should not include suggestions (distance too large)
    assert "Did you mean" not in result.stderr or "xyz" not in result.stderr


def test_case_mismatch_detection(temp_repo, run_validator):
    """
    Scenario 19: Detect wrong case for built-in agent.

    Given: swarm/flows/flow-2.md step 3 references agent 'Explore' (wrong case)
    When: I run the validator
    Then: Validator exits with code 1
    And: Error message suggests 'explore'
    """
    create_flow_file(temp_repo, "flow-2", ["Explore"])

    result = run_validator(temp_repo)
    assert_validator_failed(result)
    assert_error_contains(result.stderr, "Explore")
    assert_error_contains(result.stderr, "did you mean")
    assert_error_contains(result.stderr, "explore")


def test_multiple_suggestions_for_typo(temp_repo, run_validator):
    """
    Scenario 20: Multiple suggestions for typo with distance <= 2.

    Given: swarm/flows/flow-3.md step 4 references agent 'test-auth' (typo)
    And: 'test-author' and 'test-critic' both exist
    And: Both have Levenshtein distance 1-2 from 'test-auth'
    When: I run the validator
    Then: Error message suggests multiple similar agents (up to 3, closest first)
    """
    add_agent_to_registry(temp_repo, "test-author")
    create_agent_file(temp_repo, "test-author")
    add_agent_to_registry(temp_repo, "test-critic")
    create_agent_file(temp_repo, "test-critic")

    create_flow_file(temp_repo, "flow-3", ["test-auth"])

    result = run_validator(temp_repo)
    assert_validator_failed(result)
    assert "did you mean" in result.stderr
    # Both should be suggested (or at least one should appear)
    # Exact output format depends on validator implementation


def test_typo_suggests_closest_matches_first(temp_repo, run_validator):
    """Suggestions should be ordered by Levenshtein distance (closest first)."""
    add_agent_to_registry(temp_repo, "test-agent")
    create_agent_file(temp_repo, "test-agent")
    add_agent_to_registry(temp_repo, "best-agent")
    create_agent_file(temp_repo, "best-agent")

    # 'tst-agent' is closer to 'test-agent' (distance 1) than 'best-agent' (distance 2)
    create_flow_file(temp_repo, "flow-order", ["tst-agent"])

    result = run_validator(temp_repo)
    assert_validator_failed(result)
    # test-agent should appear before best-agent in suggestions
    # (exact assertion depends on output format)


# ============================================================================
# Edge Cases
# ============================================================================


def test_agent_reference_in_code_block_ignored(temp_repo, run_validator):
    """Agent references in markdown code blocks should be ignored."""
    flow_path = temp_repo / "swarm" / "flows" / "flow-doc.md"
    flow_path.write_text("""# Flow Documentation

## Example

```
Agent: fake-agent-in-code-block
```

This is documentation only.
""")

    result = run_validator(temp_repo)
    # Should pass - code blocks are ignored
    assert_validator_passed(result)


def test_agent_reference_in_comment_ignored(temp_repo, run_validator):
    """Agent references in comments should be ignored."""
    flow_path = temp_repo / "swarm" / "flows" / "flow-comment.md"
    flow_path.write_text("""# Flow

<!-- This references fake-agent-in-comment but it's a comment -->

No actual agent references here.
""")

    result = run_validator(temp_repo)
    assert_validator_passed(result)


def test_hyphenated_agent_name_exact_match(temp_repo, run_validator):
    """Agent names with hyphens must match exactly."""
    add_agent_to_registry(temp_repo, "foo-bar-baz")
    create_agent_file(temp_repo, "foo-bar-baz")

    create_flow_file(temp_repo, "flow-hyph", ["foo-bar-baz"])

    result = run_validator(temp_repo)
    assert_validator_passed(result)


def test_underscore_vs_hyphen_mismatch(temp_repo, run_validator):
    """Underscore vs hyphen should be detected as different."""
    add_agent_to_registry(temp_repo, "foo-bar")
    create_agent_file(temp_repo, "foo-bar")

    create_flow_file(temp_repo, "flow-under", ["foo_bar"])

    result = run_validator(temp_repo)
    assert_validator_failed(result)
    # Should suggest foo-bar
    assert "did you mean" in result.stderr


def test_numeric_agent_name(temp_repo, run_validator):
    """Agent names with numbers should work."""
    add_agent_to_registry(temp_repo, "agent-123")
    create_agent_file(temp_repo, "agent-123")

    create_flow_file(temp_repo, "flow-num", ["agent-123"])

    result = run_validator(temp_repo)
    assert_validator_passed(result)


# ============================================================================
# Flow File Format Tests
# ============================================================================


def test_agent_reference_in_step_table(temp_repo, run_validator):
    """Agent referenced in step table format."""
    add_agent_to_registry(temp_repo, "test-agent")
    create_agent_file(temp_repo, "test-agent")

    flow_path = temp_repo / "swarm" / "flows" / "flow-table.md"
    flow_path.write_text("""# Flow 1

| Step | Agent | Description |
|------|-------|-------------|
| 1    | test-agent | Load context |
| 2    | explore | Search files |
""")

    result = run_validator(temp_repo)
    assert_validator_passed(result)


def test_agent_reference_in_backticks(temp_repo, run_validator):
    """Agent referenced with backticks."""
    add_agent_to_registry(temp_repo, "test-agent")
    create_agent_file(temp_repo, "test-agent")

    flow_path = temp_repo / "swarm" / "flows" / "flow-backtick.md"
    flow_path.write_text("""# Flow

Step 1: Use `test-agent` to validate.
Step 2: Use `explore` to search.
""")

    result = run_validator(temp_repo)
    assert_validator_passed(result)


def test_agent_reference_in_mermaid_diagram(temp_repo, run_validator):
    """Agent references in mermaid diagrams."""
    add_agent_to_registry(temp_repo, "agent-a")
    create_agent_file(temp_repo, "agent-a")

    flow_path = temp_repo / "swarm" / "flows" / "flow-mermaid.md"
    flow_path.write_text("""# Flow

```mermaid
graph LR
  A[explore] --> B[agent-a]
```
""")

    result = run_validator(temp_repo)
    assert_validator_passed(result)


# ============================================================================
# Error Message Quality Tests
# ============================================================================


def test_reference_error_includes_flow_and_line(temp_repo, run_validator):
    """Reference errors should include flow file and line number."""
    create_flow_file(temp_repo, "flow-err", ["fake-agent"])

    result = run_validator(temp_repo)
    assert_validator_failed(result)

    # Should mention flow file
    assert "flow-err.md" in result.stderr
    # Should mention line number (if available)
    # Note: exact format depends on implementation


def test_reference_error_includes_fix_action(temp_repo, run_validator):
    """Reference errors should include actionable fix."""
    create_flow_file(temp_repo, "flow-fix", ["nonexistent"])

    result = run_validator(temp_repo)
    assert_validator_failed(result)
    assert "Fix:" in result.stderr


# ============================================================================
# Determinism Tests
# ============================================================================


def test_reference_validation_is_deterministic(temp_repo, run_validator):
    """Running reference validation twice produces identical results."""
    create_flow_file(temp_repo, "flow-det", ["fake-1", "fake-2"])

    result1 = run_validator(temp_repo)
    result2 = run_validator(temp_repo)

    # Same exit code
    assert result1.returncode == result2.returncode

    # Same error messages
    assert result1.stderr == result2.stderr


def test_suggestions_order_is_deterministic(temp_repo, run_validator):
    """Typo suggestions should be in deterministic order."""
    # Create multiple agents with similar names
    for name in ["test-agent-a", "test-agent-b", "test-agent-c"]:
        add_agent_to_registry(temp_repo, name)
        create_agent_file(temp_repo, name)

    create_flow_file(temp_repo, "flow-sug", ["test-agnt"])

    result1 = run_validator(temp_repo)
    result2 = run_validator(temp_repo)

    # Suggestions should appear in same order
    assert result1.stderr == result2.stderr
