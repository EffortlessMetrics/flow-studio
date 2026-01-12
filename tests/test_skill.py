"""
Test suite for skill file existence validation (FR-004).

Tests the validator's ability to ensure all skills declared in agent frontmatter
point to existing skill files with valid YAML frontmatter.

BDD Scenarios covered:
- Scenario 21: Valid skill declared in agent frontmatter
- Scenario 22: Detect missing skill file
- Scenario 23: Agent declares multiple skills, one missing
- Scenario 24: Skill file exists with malformed YAML in frontmatter
"""

import sys

import pytest

from conftest import (
    add_agent_to_registry,
    assert_error_contains,
    assert_error_type,
    assert_validator_failed,
    assert_validator_passed,
    create_agent_file,
    create_skill_file,
)

# ============================================================================
# Happy Path Tests
# ============================================================================


def test_valid_single_skill(temp_repo, run_validator):
    """
    Scenario 21: Valid skill declared in agent frontmatter.

    Given: .claude/agents/test-agent.md declares skill 'test-runner'
    And: .claude/skills/test-runner/SKILL.md exists with valid YAML
    When: I run the validator
    Then: Validator exits with code 0
    And: No skill errors are reported
    """
    # Create skill
    create_skill_file(temp_repo, "test-runner", valid=True)

    # Create agent that uses the skill
    add_agent_to_registry(temp_repo, "test-agent")
    agent_file = temp_repo / ".claude" / "agents" / "test-agent.md"
    agent_file.write_text("""---
name: test-agent
description: Test agent with skill
color: green
model: inherit
skills: [test-runner]
---

Agent uses test-runner skill.
""")

    result = run_validator(temp_repo)
    assert_validator_passed(result)
    assert "SKILL" not in result.stderr


def test_valid_multiple_skills(temp_repo, run_validator):
    """Agent with multiple valid skills."""
    # Create skills
    create_skill_file(temp_repo, "test-runner", valid=True)
    create_skill_file(temp_repo, "auto-linter", valid=True)
    create_skill_file(temp_repo, "policy-runner", valid=True)

    # Create agent
    add_agent_to_registry(temp_repo, "multi-skill")
    agent_file = temp_repo / ".claude" / "agents" / "multi-skill.md"
    agent_file.write_text("""---
name: multi-skill
description: Agent with multiple skills
color: green
model: inherit
skills: [test-runner, auto-linter, policy-runner]
---

Agent uses multiple skills.
""")

    result = run_validator(temp_repo)
    assert_validator_passed(result)


def test_agent_without_skills_field(temp_repo, run_validator):
    """Agent without skills field should pass (skills are optional)."""
    add_agent_to_registry(temp_repo, "no-skills")
    create_agent_file(temp_repo, "no-skills")

    result = run_validator(temp_repo)
    assert_validator_passed(result)


def test_agent_with_empty_skills_list(temp_repo, run_validator):
    """Agent with empty skills list should pass."""
    add_agent_to_registry(temp_repo, "empty-skills")
    agent_file = temp_repo / ".claude" / "agents" / "empty-skills.md"
    agent_file.write_text("""---
name: empty-skills
description: Agent with no skills
color: green
model: inherit
skills: []
---

No skills declared.
""")

    result = run_validator(temp_repo)
    assert_validator_passed(result)


# ============================================================================
# Missing Skill File Tests
# ============================================================================


def test_missing_skill_file(temp_repo, run_validator):
    """
    Scenario 22: Detect missing skill file.

    Given: .claude/agents/test-agent.md declares skill 'fake-skill'
    And: .claude/skills/fake-skill/SKILL.md does not exist
    When: I run the validator
    Then: Validator exits with code 1
    And: Error message explains the problem and suggests fix
    """
    add_agent_to_registry(temp_repo, "test-agent")
    agent_file = temp_repo / ".claude" / "agents" / "test-agent.md"
    agent_file.write_text("""---
name: test-agent
description: Test agent
model: inherit
skills: [fake-skill]
---

Agent declares non-existent skill.
""")

    result = run_validator(temp_repo)
    assert_validator_failed(result)
    assert_error_type(result.stderr, "SKILL")
    assert_error_contains(result.stderr, "fake-skill")
    assert_error_contains(result.stderr, "does not exist")
    assert_error_contains(result.stderr, "Fix:")


def test_multiple_missing_skills(temp_repo, run_validator):
    """Agent declares multiple skills, all missing."""
    add_agent_to_registry(temp_repo, "multi-missing")
    agent_file = temp_repo / ".claude" / "agents" / "multi-missing.md"
    agent_file.write_text("""---
name: multi-missing
description: Test agent
model: inherit
skills: [fake-1, fake-2, fake-3]
---

All skills are missing.
""")

    result = run_validator(temp_repo)
    assert_validator_failed(result)

    # All 3 missing skills should be reported
    assert "fake-1" in result.stderr
    assert "fake-2" in result.stderr
    assert "fake-3" in result.stderr


def test_partial_missing_skills(temp_repo, run_validator):
    """
    Scenario 23: Agent declares multiple skills, one missing.

    Given: .claude/agents/multi-skill.md declares skills [test-runner, fake-skill, auto-linter]
    And: 'test-runner' and 'auto-linter' exist, but 'fake-skill' does not
    When: I run the validator
    Then: Validator exits with code 1
    And: Error is reported for 'fake-skill'
    And: The other two skills pass validation
    """
    # Create valid skills
    create_skill_file(temp_repo, "test-runner", valid=True)
    create_skill_file(temp_repo, "auto-linter", valid=True)

    # Create agent with one invalid skill
    add_agent_to_registry(temp_repo, "partial")
    agent_file = temp_repo / ".claude" / "agents" / "partial.md"
    agent_file.write_text("""---
name: partial
description: Partially valid skills
model: inherit
skills: [test-runner, fake-skill, auto-linter]
---

One skill is missing.
""")

    result = run_validator(temp_repo)
    assert_validator_failed(result)

    # Only fake-skill should be reported as error
    assert "fake-skill" in result.stderr
    # test-runner and auto-linter should not appear in errors


def test_missing_skill_directory(temp_repo, run_validator):
    """Skill directory exists but SKILL.md file is missing."""
    add_agent_to_registry(temp_repo, "test-agent")
    agent_file = temp_repo / ".claude" / "agents" / "test-agent.md"
    agent_file.write_text("""---
name: test-agent
description: Test agent
model: inherit
skills: [incomplete-skill]
---

Skill directory exists but file doesn't.
""")

    # Create skill directory but not the file
    skill_dir = temp_repo / ".claude" / "skills" / "incomplete-skill"
    skill_dir.mkdir(parents=True)

    result = run_validator(temp_repo)
    assert_validator_failed(result)
    assert "incomplete-skill" in result.stderr


# ============================================================================
# Malformed Skill YAML Tests
# ============================================================================


def test_skill_with_malformed_yaml(temp_repo, run_validator):
    """
    Scenario 24: Skill file exists with malformed YAML in frontmatter.

    Given: .claude/skills/test-runner/SKILL.md contains malformed YAML
    And: .claude/agents/test-agent.md declares this skill
    When: I run the validator
    Then: Validator exits with code 1
    And: Error message indicates YAML parse error
    """
    # Create skill with malformed YAML
    create_skill_file(temp_repo, "bad-skill", valid=False)

    # Create agent that uses the skill
    add_agent_to_registry(temp_repo, "test-agent")
    agent_file = temp_repo / ".claude" / "agents" / "test-agent.md"
    agent_file.write_text("""---
name: test-agent
description: Test agent
model: inherit
skills: [bad-skill]
---

Uses skill with malformed YAML.
""")

    result = run_validator(temp_repo)
    assert_validator_failed(result)
    assert_error_type(result.stderr, "SKILL")
    assert_error_contains(result.stderr, "bad-skill")
    assert_error_contains(result.stderr, "malformed")


def test_skill_missing_required_frontmatter_field(temp_repo, run_validator):
    """Skill file with missing required frontmatter fields."""
    add_agent_to_registry(temp_repo, "test-agent")
    agent_file = temp_repo / ".claude" / "agents" / "test-agent.md"
    agent_file.write_text("""---
name: test-agent
description: Test agent
model: inherit
skills: [incomplete-frontmatter]
---

Skill has incomplete frontmatter.
""")

    # Create skill with incomplete frontmatter (missing description)
    skill_dir = temp_repo / ".claude" / "skills" / "incomplete-frontmatter"
    skill_dir.mkdir(parents=True)
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text("""---
name: incomplete-frontmatter
---

Missing description field.
""")

    result = run_validator(temp_repo)
    assert_validator_failed(result)


def test_skill_with_empty_frontmatter(temp_repo, run_validator):
    """Skill file with empty frontmatter block."""
    add_agent_to_registry(temp_repo, "test-agent")
    agent_file = temp_repo / ".claude" / "agents" / "test-agent.md"
    agent_file.write_text("""---
name: test-agent
description: Test agent
model: inherit
skills: [empty-frontmatter]
---

Skill has empty frontmatter.
""")

    # Create skill with empty frontmatter
    skill_dir = temp_repo / ".claude" / "skills" / "empty-frontmatter"
    skill_dir.mkdir(parents=True)
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text("""---
---

Empty frontmatter.
""")

    result = run_validator(temp_repo)
    assert_validator_failed(result)


# ============================================================================
# Edge Cases
# ============================================================================


def test_skill_name_with_hyphens(temp_repo, run_validator):
    """Skill names with hyphens should work."""
    create_skill_file(temp_repo, "test-runner-v2", valid=True)

    add_agent_to_registry(temp_repo, "test-agent")
    agent_file = temp_repo / ".claude" / "agents" / "test-agent.md"
    agent_file.write_text("""---
name: test-agent
description: Test agent
color: green
model: inherit
skills: [test-runner-v2]
---

Uses hyphenated skill name.
""")

    result = run_validator(temp_repo)
    assert_validator_passed(result)


def test_skill_name_with_numbers(temp_repo, run_validator):
    """Skill names with numbers should work."""
    create_skill_file(temp_repo, "skill-123", valid=True)

    add_agent_to_registry(temp_repo, "test-agent")
    agent_file = temp_repo / ".claude" / "agents" / "test-agent.md"
    agent_file.write_text("""---
name: test-agent
description: Test agent
color: green
model: inherit
skills: [skill-123]
---

Uses numeric skill name.
""")

    result = run_validator(temp_repo)
    assert_validator_passed(result)


def test_multiple_agents_using_same_skill(temp_repo, run_validator):
    """Multiple agents can use the same skill."""
    create_skill_file(temp_repo, "shared-skill", valid=True)

    for i in range(1, 4):
        agent_name = f"agent-{i}"
        add_agent_to_registry(temp_repo, agent_name)
        agent_file = temp_repo / ".claude" / "agents" / f"{agent_name}.md"
        agent_file.write_text(f"""---
name: {agent_name}
description: Agent {i}
color: green
model: inherit
skills: [shared-skill]
---

Shares skill with other agents.
""")

    result = run_validator(temp_repo)
    assert_validator_passed(result)


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Windows file system is case-insensitive; skill path lookup finds 'test-runner' for 'Test-Runner'"
)
def test_case_sensitive_skill_matching(temp_repo, run_validator):
    """Skill names should be case-sensitive.

    Note: This test is skipped on Windows because NTFS is case-insensitive,
    so the skill file lookup will find 'test-runner' when looking for 'Test-Runner'.
    """
    create_skill_file(temp_repo, "test-runner", valid=True)

    add_agent_to_registry(temp_repo, "test-agent")
    agent_file = temp_repo / ".claude" / "agents" / "test-agent.md"
    agent_file.write_text("""---
name: test-agent
description: Test agent
color: green
model: inherit
skills: [Test-Runner]
---

Wrong case for skill name.
""")

    result = run_validator(temp_repo)
    assert_validator_failed(result)
    assert "Test-Runner" in result.stderr


# ============================================================================
# Error Message Quality Tests
# ============================================================================


def test_skill_error_includes_agent_name(temp_repo, run_validator):
    """Skill errors should mention which agent declared the skill."""
    add_agent_to_registry(temp_repo, "my-agent")
    agent_file = temp_repo / ".claude" / "agents" / "my-agent.md"
    agent_file.write_text("""---
name: my-agent
description: Test agent
model: inherit
skills: [missing-skill]
---

Agent.
""")

    result = run_validator(temp_repo)
    assert_validator_failed(result)
    assert "my-agent" in result.stderr
    assert "missing-skill" in result.stderr


def test_skill_error_includes_fix_action(temp_repo, run_validator):
    """Skill errors should include actionable fix guidance."""
    add_agent_to_registry(temp_repo, "test-agent")
    agent_file = temp_repo / ".claude" / "agents" / "test-agent.md"
    agent_file.write_text("""---
name: test-agent
description: Test agent
model: inherit
skills: [fake-skill]
---

Agent.
""")

    result = run_validator(temp_repo)
    assert_validator_failed(result)
    assert "Fix:" in result.stderr


# ============================================================================
# Determinism Tests
# ============================================================================


def test_skill_validation_is_deterministic(temp_repo, run_validator):
    """Running skill validation twice produces identical results."""
    add_agent_to_registry(temp_repo, "test-agent")
    agent_file = temp_repo / ".claude" / "agents" / "test-agent.md"
    agent_file.write_text("""---
name: test-agent
description: Test agent
model: inherit
skills: [missing-1, missing-2]
---

Agent with missing skills.
""")

    result1 = run_validator(temp_repo)
    result2 = run_validator(temp_repo)

    # Same exit code
    assert result1.returncode == result2.returncode

    # Same error messages (deterministic order)
    assert result1.stderr == result2.stderr
