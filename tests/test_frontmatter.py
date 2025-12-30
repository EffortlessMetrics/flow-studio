"""
Test suite for agent frontmatter validation (FR-002).

Tests the validator's ability to ensure valid YAML frontmatter in agent files
with required fields, proper name matching, and swarm design constraints.

BDD Scenarios covered:
- Scenario 6: Valid frontmatter passes validation
- Scenario 7: Detect missing required field 'name'
- Scenario 8: Detect mismatch between name field and filename
- Scenario 9: Detect malformed YAML syntax
- Scenario 10: Detect invalid model value
- Scenario 11: Detect disallowed field 'tools'
- Scenario 12: Detect disallowed field 'permissionMode'
- Scenario 13: Valid skills list in frontmatter
- Scenario 14: Detect invalid skills format (not a list)
"""

import pytest

from conftest import (
    add_agent_to_registry,
    assert_error_contains,
    assert_error_type,
    assert_validator_failed,
    assert_validator_passed,
    create_agent_with_invalid_yaml,
    create_skill_file,
)

# ============================================================================
# Happy Path Tests
# ============================================================================


def test_valid_frontmatter(valid_repo, run_validator):
    """
    Scenario 6: Valid frontmatter passes validation.

    Given: .claude/agents/test-agent.md contains valid YAML frontmatter
    When: I run the validator
    Then: Validator exits with code 0
    And: No frontmatter errors are reported
    """
    result = run_validator(valid_repo)
    assert_validator_passed(result)
    assert "FRONTMATTER" not in result.stderr


def test_minimal_valid_frontmatter(temp_repo, run_validator):
    """Minimal valid frontmatter with only required fields."""
    add_agent_to_registry(temp_repo, "minimal-agent")

    agent_file = temp_repo / ".claude" / "agents" / "minimal-agent.md"
    agent_file.write_text("""---
name: minimal-agent
description: Minimal test agent
color: green
model: inherit
---

Agent prompt.
""")

    result = run_validator(temp_repo)
    assert_validator_passed(result)


# ============================================================================
# Missing Required Fields Tests
# ============================================================================


def test_missing_required_field_name(temp_repo, run_validator):
    """
    Scenario 7: Detect missing required field 'name'.

    Given: .claude/agents/test.md contains invalid frontmatter without 'name' field
    When: I run the validator
    Then: Validator exits with code 1
    And: Error message indicates missing 'name' field with fix
    """
    add_agent_to_registry(temp_repo, "test")

    agent_file = temp_repo / ".claude" / "agents" / "test.md"
    agent_file.write_text("""---
description: Test agent without name field
model: inherit
---

Agent prompt.
""")

    result = run_validator(temp_repo)
    assert_validator_failed(result)
    assert_error_type(result.stderr, "FRONTMATTER")
    assert_error_contains(result.stderr, "name")
    assert_error_contains(result.stderr, "Fix:")


def test_missing_required_field_description(temp_repo, run_validator):
    """Missing required field 'description'."""
    add_agent_to_registry(temp_repo, "no-desc")

    agent_file = temp_repo / ".claude" / "agents" / "no-desc.md"
    agent_file.write_text("""---
name: no-desc
model: inherit
---

Agent prompt.
""")

    result = run_validator(temp_repo)
    assert_validator_failed(result)
    assert_error_type(result.stderr, "FRONTMATTER")
    assert_error_contains(result.stderr, "description")


def test_missing_required_field_model(temp_repo, run_validator):
    """Missing required field 'model'."""
    add_agent_to_registry(temp_repo, "no-model")

    agent_file = temp_repo / ".claude" / "agents" / "no-model.md"
    agent_file.write_text("""---
name: no-model
description: Test agent without model field
---

Agent prompt.
""")

    result = run_validator(temp_repo)
    assert_validator_failed(result)
    assert_error_type(result.stderr, "FRONTMATTER")
    assert_error_contains(result.stderr, "model")


# ============================================================================
# Name-Filename Mismatch Tests
# ============================================================================


def test_name_filename_mismatch(temp_repo, run_validator):
    """
    Scenario 8: Detect mismatch between name field and filename.

    Given: .claude/agents/test.md contains frontmatter with name: 'test-foo'
    When: I run the validator
    Then: Validator exits with code 1
    And: Error message explains mismatch and suggests fix
    """
    add_agent_to_registry(temp_repo, "test")

    agent_file = temp_repo / ".claude" / "agents" / "test.md"
    agent_file.write_text("""---
name: test-foo
description: Test agent with mismatched name
model: inherit
---

Agent prompt.
""")

    result = run_validator(temp_repo)
    assert_validator_failed(result)
    assert_error_type(result.stderr, "FRONTMATTER")
    assert_error_contains(result.stderr, "test-foo")
    assert_error_contains(result.stderr, "test.md")


def test_name_case_sensitive(temp_repo, run_validator):
    """Name field must match filename case-sensitively."""
    add_agent_to_registry(temp_repo, "TestAgent")

    agent_file = temp_repo / ".claude" / "agents" / "TestAgent.md"
    agent_file.write_text("""---
name: testagent
description: Test agent with wrong case
model: inherit
---

Agent prompt.
""")

    result = run_validator(temp_repo)
    assert_validator_failed(result)


# ============================================================================
# Malformed YAML Tests
# ============================================================================


def test_malformed_yaml_unclosed_quote(temp_repo, run_validator):
    """
    Scenario 9: Detect malformed YAML syntax.

    Given: .claude/agents/bad.md contains frontmatter with unclosed quote
    When: I run the validator
    Then: Validator exits with code 1
    And: Error message indicates YAML syntax error with line number
    """
    add_agent_to_registry(temp_repo, "bad")
    create_agent_with_invalid_yaml(temp_repo, "bad", "unclosed_quote")

    result = run_validator(temp_repo)
    assert_validator_failed(result)
    assert_error_type(result.stderr, "FRONTMATTER")
    assert_error_contains(result.stderr, "bad.md")


def test_malformed_yaml_invalid_indent(temp_repo, run_validator):
    """Invalid YAML indentation."""
    add_agent_to_registry(temp_repo, "bad-indent")
    create_agent_with_invalid_yaml(temp_repo, "bad-indent", "invalid_indent")

    result = run_validator(temp_repo)
    assert_validator_failed(result)
    assert_error_type(result.stderr, "FRONTMATTER")


def test_malformed_yaml_missing_delimiter(temp_repo, run_validator):
    """Missing closing --- delimiter."""
    add_agent_to_registry(temp_repo, "bad-delim")
    create_agent_with_invalid_yaml(temp_repo, "bad-delim", "missing_delimiter")

    result = run_validator(temp_repo)
    assert_validator_failed(result)
    assert_error_type(result.stderr, "FRONTMATTER")


def test_empty_frontmatter(temp_repo, run_validator):
    """Frontmatter block with no fields."""
    add_agent_to_registry(temp_repo, "empty")

    agent_file = temp_repo / ".claude" / "agents" / "empty.md"
    agent_file.write_text("""---
---

Agent prompt.
""")

    result = run_validator(temp_repo)
    assert_validator_failed(result)


# ============================================================================
# Invalid Model Value Tests
# ============================================================================


def test_invalid_model_value(temp_repo, run_validator):
    """
    Scenario 10: Detect invalid model value.

    Given: .claude/agents/test.md contains frontmatter with model: 'claude-sonnet'
    When: I run the validator
    Then: Validator exits with code 1
    And: Error message indicates invalid model value and valid options
    """
    add_agent_to_registry(temp_repo, "bad-model")

    agent_file = temp_repo / ".claude" / "agents" / "bad-model.md"
    agent_file.write_text("""---
name: bad-model
description: Test agent with invalid model
model: claude-sonnet
---

Agent prompt.
""")

    result = run_validator(temp_repo)
    assert_validator_failed(result)
    assert_error_type(result.stderr, "FRONTMATTER")
    assert_error_contains(result.stderr, "model")


def test_valid_model_values(temp_repo, run_validator):
    """All valid model values should pass."""
    valid_models = ["inherit", "haiku", "sonnet"]

    for i, model in enumerate(valid_models):
        agent_name = f"agent-{model}"
        add_agent_to_registry(temp_repo, agent_name)

        agent_file = temp_repo / ".claude" / "agents" / f"{agent_name}.md"
        agent_file.write_text(f"""---
name: {agent_name}
description: Test agent with model {model}
color: green
model: {model}
---

Agent prompt.
""")

    result = run_validator(temp_repo)
    assert_validator_passed(result)


def test_model_value_case_sensitive(temp_repo, run_validator):
    """Model values must be lowercase."""
    add_agent_to_registry(temp_repo, "wrong-case")

    agent_file = temp_repo / ".claude" / "agents" / "wrong-case.md"
    agent_file.write_text("""---
name: wrong-case
description: Test agent
model: Inherit
---

Agent prompt.
""")

    result = run_validator(temp_repo)
    assert_validator_failed(result)


# ============================================================================
# Disallowed Fields Tests (Swarm Design Constraints)
# ============================================================================


def test_disallowed_field_tools(temp_repo, run_validator):
    """
    Scenario 11: Detect 'tools' field (swarm design guideline).

    Two-layer design:
    - Layer 1 (Claude Code platform): supports 'tools' field
    - Layer 2 (Swarm design): intentionally omits it

    Given: .claude/agents/test.md contains frontmatter with tools field
    When: I run the validator (default mode)
    Then: Validator passes with WARNING (not error)
    And: When I run with --strict
    Then: Validator fails with ERROR
    """
    add_agent_to_registry(temp_repo, "with-tools")

    agent_file = temp_repo / ".claude" / "agents" / "with-tools.md"
    agent_file.write_text("""---
name: with-tools
description: Test agent with tools field (swarm guideline: omit)
color: green
model: inherit
tools: [Read, Write, Bash]
---

Agent prompt.
""")

    # Default mode: passes with warning
    result = run_validator(temp_repo)
    assert_validator_passed(result)  # Should pass (warnings don't fail)
    assert "tools" in result.stderr or "tools" in result.stdout  # Warning should be mentioned

    # Strict mode: fails with error
    result_strict = run_validator(temp_repo, flags=["--strict"])
    assert_validator_failed(result_strict)
    assert_error_type(result_strict.stderr, "FRONTMATTER")
    assert_error_contains(result_strict.stderr, "tools")


def test_disallowed_field_permission_mode(temp_repo, run_validator):
    """
    Scenario 12: Detect 'permissionMode' field (swarm design guideline).

    Two-layer design:
    - Layer 1 (Claude Code platform): supports 'permissionMode' field
    - Layer 2 (Swarm design): intentionally omits it

    Given: .claude/agents/test.md contains frontmatter with permissionMode field
    When: I run the validator (default mode)
    Then: Validator passes with WARNING (not error)
    And: When I run with --strict
    Then: Validator fails with ERROR
    """
    add_agent_to_registry(temp_repo, "with-perm")

    agent_file = temp_repo / ".claude" / "agents" / "with-perm.md"
    agent_file.write_text("""---
name: with-perm
description: Test agent with permissionMode field (swarm guideline: omit)
color: green
model: inherit
permissionMode: default
---

Agent prompt.
""")

    # Default mode: passes with warning
    result = run_validator(temp_repo)
    assert_validator_passed(result)  # Should pass (warnings don't fail)
    assert "permissionMode" in result.stderr or "permissionMode" in result.stdout  # Warning should be mentioned

    # Strict mode: fails with error
    result_strict = run_validator(temp_repo, flags=["--strict"])
    assert_validator_failed(result_strict)
    assert_error_type(result_strict.stderr, "FRONTMATTER")
    assert_error_contains(result_strict.stderr, "permissionMode")


# ============================================================================
# Skills Field Tests
# ============================================================================


def test_valid_skills_list(temp_repo, run_validator):
    """
    Scenario 13: Valid skills list in frontmatter.

    Given: .claude/agents/test-agent.md contains frontmatter with skills: [test-runner, auto-linter]
    And: Both skills exist
    When: I run the validator
    Then: Validator exits with code 0
    """
    # Create skills
    create_skill_file(temp_repo, "test-runner")
    create_skill_file(temp_repo, "auto-linter")

    # Create agent with skills
    add_agent_to_registry(temp_repo, "skilled-agent")

    agent_file = temp_repo / ".claude" / "agents" / "skilled-agent.md"
    agent_file.write_text("""---
name: skilled-agent
description: Test agent with skills
color: green
model: inherit
skills: [test-runner, auto-linter]
---

Agent prompt.
""")

    result = run_validator(temp_repo)
    assert_validator_passed(result)


def test_invalid_skills_format_not_list(temp_repo, run_validator):
    """
    Scenario 14: Detect invalid skills format (not a list).

    Given: .claude/agents/test.md contains frontmatter with skills: test-runner (scalar)
    When: I run the validator
    Then: Validator exits with code 1
    And: Error message indicates skills must be a list
    """
    add_agent_to_registry(temp_repo, "bad-skills")

    agent_file = temp_repo / ".claude" / "agents" / "bad-skills.md"
    agent_file.write_text("""---
name: bad-skills
description: Test agent with invalid skills format
model: inherit
skills: test-runner
---

Agent prompt.
""")

    result = run_validator(temp_repo)
    assert_validator_failed(result)
    assert_error_type(result.stderr, "FRONTMATTER")
    assert_error_contains(result.stderr, "skills")


def test_empty_skills_list(temp_repo, run_validator):
    """Empty skills list should be valid."""
    add_agent_to_registry(temp_repo, "no-skills")

    agent_file = temp_repo / ".claude" / "agents" / "no-skills.md"
    agent_file.write_text("""---
name: no-skills
description: Test agent with empty skills
color: green
model: inherit
skills: []
---

Agent prompt.
""")

    result = run_validator(temp_repo)
    assert_validator_passed(result)


def test_skills_field_omitted(temp_repo, run_validator):
    """Skills field is optional - omitting it should be valid."""
    add_agent_to_registry(temp_repo, "no-skills-field")

    agent_file = temp_repo / ".claude" / "agents" / "no-skills-field.md"
    agent_file.write_text("""---
name: no-skills-field
description: Test agent without skills field
color: green
model: inherit
---

Agent prompt.
""")

    result = run_validator(temp_repo)
    assert_validator_passed(result)


# ============================================================================
# Error Message Quality Tests
# ============================================================================


def test_frontmatter_error_includes_line_number(temp_repo, run_validator):
    """Frontmatter errors should include line number."""
    add_agent_to_registry(temp_repo, "bad")
    create_agent_with_invalid_yaml(temp_repo, "bad", "unclosed_quote")

    result = run_validator(temp_repo)
    assert_validator_failed(result)

    # Should include line number
    assert "line" in result.stderr.lower()


def test_frontmatter_error_includes_fix(temp_repo, run_validator):
    """Frontmatter errors should include actionable fix."""
    add_agent_to_registry(temp_repo, "missing-name")

    agent_file = temp_repo / ".claude" / "agents" / "missing-name.md"
    agent_file.write_text("""---
description: Test
model: inherit
---

Prompt.
""")

    result = run_validator(temp_repo)
    assert_validator_failed(result)
    assert "Fix:" in result.stderr


# ============================================================================
# Multiple Frontmatter Errors Tests
# ============================================================================


def test_multiple_frontmatter_errors_all_reported(temp_repo, run_validator):
    """Multiple frontmatter errors in different files - all reported."""
    # Agent 1: missing name
    add_agent_to_registry(temp_repo, "agent1")
    (temp_repo / ".claude" / "agents" / "agent1.md").write_text("""---
description: Test
model: inherit
---
Prompt.
""")

    # Agent 2: invalid model
    add_agent_to_registry(temp_repo, "agent2")
    (temp_repo / ".claude" / "agents" / "agent2.md").write_text("""---
name: agent2
description: Test
model: invalid
---
Prompt.
""")

    # Agent 3: disallowed tools
    add_agent_to_registry(temp_repo, "agent3")
    (temp_repo / ".claude" / "agents" / "agent3.md").write_text("""---
name: agent3
description: Test
model: inherit
tools: [Read]
---
Prompt.
""")

    result = run_validator(temp_repo)
    assert_validator_failed(result)

    # All 3 errors should be reported
    assert result.stderr.count("[FAIL]") >= 3


# ============================================================================
# Edge Cases
# ============================================================================


def test_agent_with_multiline_description(temp_repo, run_validator):
    """Multiline description in frontmatter."""
    add_agent_to_registry(temp_repo, "multiline")

    agent_file = temp_repo / ".claude" / "agents" / "multiline.md"
    agent_file.write_text("""---
name: multiline
description: |
  This is a multiline
  description for testing
color: green
model: inherit
---

Agent prompt.
""")

    result = run_validator(temp_repo)
    assert_validator_passed(result)


def test_agent_with_extra_optional_fields(temp_repo, run_validator):
    """Agent with additional optional fields (not in spec but not disallowed)."""
    add_agent_to_registry(temp_repo, "extra")

    agent_file = temp_repo / ".claude" / "agents" / "extra.md"
    agent_file.write_text("""---
name: extra
description: Test agent with extra fields
model: inherit
custom_field: some_value
---

Agent prompt.
""")

    # Extra fields not explicitly disallowed should be ignored
    result = run_validator(temp_repo)
    # This test documents current behavior - may need adjustment based on validator design


# ============================================================================
# Color Schema Validation Tests (FR-002, CRITICAL GAP)
# ============================================================================


def test_missing_required_field_color(temp_repo, run_validator):
    """
    CRITICAL: Test detection of missing 'color' field.

    Given: Agent file exists but frontmatter lacks 'color' field
    And: AGENTS.md has role_family defined
    When: I run the validator
    Then: Validator fails with COLOR error
    And: Error suggests correct color for the role_family
    """
    add_agent_to_registry(temp_repo, "no-color-agent", role_family="critic")

    agent_file = temp_repo / ".claude" / "agents" / "no-color-agent.md"
    agent_file.write_text("""---
name: no-color-agent
description: Test agent without color field
model: inherit
---

Agent prompt.
""")

    result = run_validator(temp_repo)
    assert_validator_failed(result)
    assert_error_type(result.stderr, "COLOR")
    assert_error_contains(result.stderr, "color")
    # Should suggest the correct color for critic role_family
    assert_error_contains(result.stderr, "red")


def test_color_yellow_for_shaping_role_family(temp_repo, run_validator):
    """
    Valid color for shaping role family is yellow.

    Given: Agent with role_family: shaping
    When: color: yellow
    Then: Validation passes
    """
    add_agent_to_registry(temp_repo, "signal-normalizer", role_family="shaping")

    agent_file = temp_repo / ".claude" / "agents" / "signal-normalizer.md"
    agent_file.write_text("""---
name: signal-normalizer
description: Test shaping agent
model: inherit
color: yellow
---

Agent prompt.
""")

    result = run_validator(temp_repo)
    assert_validator_passed(result)


def test_color_purple_for_spec_role_family(temp_repo, run_validator):
    """
    Valid color for spec role family is purple.

    Given: Agent with role_family: spec
    When: color: purple
    Then: Validation passes
    """
    add_agent_to_registry(temp_repo, "requirements-author", role_family="spec")

    agent_file = temp_repo / ".claude" / "agents" / "requirements-author.md"
    agent_file.write_text("""---
name: requirements-author
description: Test spec agent
model: inherit
color: purple
---

Agent prompt.
""")

    result = run_validator(temp_repo)
    assert_validator_passed(result)


def test_color_green_for_implementation_role_family(temp_repo, run_validator):
    """
    Valid color for implementation role family is green.

    Given: Agent with role_family: implementation
    When: color: green
    Then: Validation passes
    """
    add_agent_to_registry(temp_repo, "code-implementer", role_family="implementation")

    agent_file = temp_repo / ".claude" / "agents" / "code-implementer.md"
    agent_file.write_text("""---
name: code-implementer
description: Test implementation agent
model: inherit
color: green
---

Agent prompt.
""")

    result = run_validator(temp_repo)
    assert_validator_passed(result)


def test_color_red_for_critic_role_family(temp_repo, run_validator):
    """
    Valid color for critic role family is red.

    Given: Agent with role_family: critic
    When: color: red
    Then: Validation passes
    """
    add_agent_to_registry(temp_repo, "test-critic", role_family="critic")

    agent_file = temp_repo / ".claude" / "agents" / "test-critic.md"
    agent_file.write_text("""---
name: test-critic
description: Test critic agent
model: inherit
color: red
---

Agent prompt.
""")

    result = run_validator(temp_repo)
    assert_validator_passed(result)


def test_color_blue_for_verification_role_family(temp_repo, run_validator):
    """
    Valid color for verification role family is blue.

    Given: Agent with role_family: verification
    When: color: blue
    Then: Validation passes
    """
    add_agent_to_registry(temp_repo, "receipt-checker", role_family="verification")

    agent_file = temp_repo / ".claude" / "agents" / "receipt-checker.md"
    agent_file.write_text("""---
name: receipt-checker
description: Test verification agent
model: inherit
color: blue
---

Agent prompt.
""")

    result = run_validator(temp_repo)
    assert_validator_passed(result)


def test_color_orange_for_analytics_role_family(temp_repo, run_validator):
    """
    Valid color for analytics role family is orange.

    Given: Agent with role_family: analytics
    When: color: orange
    Then: Validation passes
    """
    add_agent_to_registry(temp_repo, "risk-analyst", role_family="analytics")

    agent_file = temp_repo / ".claude" / "agents" / "risk-analyst.md"
    agent_file.write_text("""---
name: risk-analyst
description: Test analytics agent
model: inherit
color: orange
---

Agent prompt.
""")

    result = run_validator(temp_repo)
    assert_validator_passed(result)


def test_color_pink_for_reporter_role_family(temp_repo, run_validator):
    """
    Valid color for reporter role family is pink.

    Given: Agent with role_family: reporter
    When: color: pink
    Then: Validation passes
    """
    add_agent_to_registry(temp_repo, "gh-reporter", role_family="reporter")

    agent_file = temp_repo / ".claude" / "agents" / "gh-reporter.md"
    agent_file.write_text("""---
name: gh-reporter
description: Test reporter agent
model: inherit
color: pink
---

Agent prompt.
""")

    result = run_validator(temp_repo)
    assert_validator_passed(result)


def test_color_cyan_for_infra_role_family(temp_repo, run_validator):
    """
    Valid color for infra role family is cyan.

    Given: Agent with role_family: infra
    When: color: cyan
    Then: Validation passes
    """
    add_agent_to_registry(temp_repo, "explore-agent", role_family="infra")

    agent_file = temp_repo / ".claude" / "agents" / "explore-agent.md"
    agent_file.write_text("""---
name: explore-agent
description: Test infra agent
model: inherit
color: cyan
---

Agent prompt.
""")

    result = run_validator(temp_repo)
    assert_validator_passed(result)


def test_color_mismatch_red_critic_gets_blue(temp_repo, run_validator):
    """
    CRITICAL: Test color mismatch detection.

    Given: Agent with role_family: critic (expects red)
    When: color: blue (wrong)
    Then: Validator fails with COLOR error
    And: Error suggests correct color (red)
    """
    add_agent_to_registry(temp_repo, "test-critic-wrong", role_family="critic")

    agent_file = temp_repo / ".claude" / "agents" / "test-critic-wrong.md"
    agent_file.write_text("""---
name: test-critic-wrong
description: Test critic agent with wrong color
model: inherit
color: blue
---

Agent prompt.
""")

    result = run_validator(temp_repo)
    assert_validator_failed(result)
    assert_error_type(result.stderr, "COLOR")
    assert_error_contains(result.stderr, "blue")
    assert_error_contains(result.stderr, "red")


def test_color_mismatch_implementation_gets_red(temp_repo, run_validator):
    """
    Test color mismatch: implementation agent with wrong color.

    Given: Agent with role_family: implementation (expects green)
    When: color: red
    Then: Validator fails with clear mismatch error
    """
    add_agent_to_registry(temp_repo, "code-implementer-wrong", role_family="implementation")

    agent_file = temp_repo / ".claude" / "agents" / "code-implementer-wrong.md"
    agent_file.write_text("""---
name: code-implementer-wrong
description: Test implementer with wrong color
model: inherit
color: red
---

Agent prompt.
""")

    result = run_validator(temp_repo)
    assert_validator_failed(result)
    assert_error_type(result.stderr, "COLOR")


def test_invalid_color_value(temp_repo, run_validator):
    """
    Test detection of invalid color value.

    Given: Agent with color: purple-ish (invalid)
    When: I run the validator
    Then: Validator fails with COLOR error
    And: Error lists valid color options
    """
    add_agent_to_registry(temp_repo, "bad-color", role_family="critic")

    agent_file = temp_repo / ".claude" / "agents" / "bad-color.md"
    agent_file.write_text("""---
name: bad-color
description: Agent with invalid color
model: inherit
color: purple-ish
---

Agent prompt.
""")

    result = run_validator(temp_repo)
    assert_validator_failed(result)
    assert_error_type(result.stderr, "COLOR")
    assert_error_contains(result.stderr, "purple-ish")


def test_color_field_is_case_insensitive(temp_repo, run_validator):
    """
    Color values should be case-insensitive.

    Given: Agent with color: RED (uppercase)
    When: Expected color is red (lowercase)
    Then: Validation passes (case-insensitive match)
    """
    add_agent_to_registry(temp_repo, "case-color", role_family="critic")

    agent_file = temp_repo / ".claude" / "agents" / "case-color.md"
    agent_file.write_text("""---
name: case-color
description: Test case insensitivity
model: inherit
color: RED
---

Agent prompt.
""")

    result = run_validator(temp_repo)
    # Should pass because validator normalizes to lowercase
    assert_validator_passed(result)


def test_yaml_tilde_null_in_description(temp_repo, run_validator):
    """
    HIGH PRIORITY: YAML tilde (~) should be recognized as null value.

    Spec: YAML standard defines ~ as null.

    Given: Agent with description: ~ (null)
    When: I run the validator
    Then: Validator should gracefully handle tilde null (either accept as empty or reject as missing field)
    And: Does NOT crash with AttributeError

    CURRENT BUG: Validator crashes with "'NoneType' object has no attribute 'strip'"
    This indicates tilde values are parsed as None but not checked before string operations.

    Mutation: If tilde null-safety handling is missing, test fails (as expected).
    """
    add_agent_to_registry(temp_repo, "tilde-agent")

    agent_file = temp_repo / ".claude" / "agents" / "tilde-agent.md"
    agent_file.write_text("""---
name: tilde-agent
description: ~
model: inherit
color: green
---

Agent prompt.
""")

    result = run_validator(temp_repo)
    # Should either:
    # 1. Pass if validator accepts null description, OR
    # 2. Fail with FRONTMATTER error (missing description requirement)
    # But should NOT crash (return code 2 = crash)
    assert result.returncode in [0, 1], f"Validator crashed with return code {result.returncode}. Error: {result.stderr}"


def test_yaml_tilde_null_in_model(temp_repo, run_validator):
    """
    HIGH PRIORITY: YAML tilde (~) in model field should be handled.

    Given: Agent with model: ~ (null)
    When: I run the validator
    Then: Validator should reject with FRONTMATTER error (model is required)
    And: Does NOT crash

    CURRENT BUG: Validator crashes instead of gracefully handling null.

    Mutation: Null-safety check prevents this crash.
    """
    add_agent_to_registry(temp_repo, "tilde-model")

    agent_file = temp_repo / ".claude" / "agents" / "tilde-model.md"
    agent_file.write_text("""---
name: tilde-model
description: Test agent
model: ~
color: green
---

Agent prompt.
""")

    result = run_validator(temp_repo)
    # Should fail (model required) but NOT crash
    # Validator should handle tilde gracefully
    assert result.returncode in [0, 1], f"Validator crashed with return code {result.returncode}"


def test_frontmatter_model_uppercase_inherit(temp_repo, run_validator):
    """
    MEDIUM PRIORITY: Model values should support uppercase variants.

    Given: Agent with model: INHERIT (uppercase)
    When: I run the validator
    Then: Validator either accepts INHERIT or requires lowercase
    And: Behavior is documented in error message
    """
    add_agent_to_registry(temp_repo, "uppercase-model")

    agent_file = temp_repo / ".claude" / "agents" / "uppercase-model.md"
    agent_file.write_text("""---
name: uppercase-model
description: Test uppercase model
model: INHERIT
color: green
---

Agent prompt.
""")

    result = run_validator(temp_repo)
    # Check if validator accepts INHERIT or requires inherit
    # Either is acceptable, but behavior should be clear
    if result.returncode == 0:
        # Validator accepts uppercase
        pass
    else:
        # Validator rejects uppercase, should provide clear error
        assert "model" in result.stderr.lower() or "inherit" in result.stderr.lower()
