"""Tests for prompt_builder.py - Scent Trail and Agentic Step Prompt Loading.

This module tests the industrialized SDLC integrations in prompt_builder.py:
1. Scent trail loading from .runs/_wisdom/latest.md
2. Agentic step prompt loading with priority fallback
3. ContextPack-based context building

## Test Coverage

### Scent Trail Loading (3 tests)
1. test_load_scent_trail_returns_none_when_no_file - Missing file returns None
2. test_load_scent_trail_returns_content_when_file_exists - File exists returns content
3. test_load_scent_trail_tries_both_paths - Tests both .runs/ and swarm/runs/ paths

### Agentic Step Prompt Loading (3 tests)
4. test_load_agent_persona_from_agentic_steps - Loads from swarm/prompts/agentic_steps/ first
5. test_load_agent_persona_fallback_to_claude_agents - Falls back to .claude/agents/
6. test_load_agent_persona_strips_frontmatter - Frontmatter is properly stripped

### ContextPack Context Building (3 tests)
7. test_build_context_from_pack_empty_envelopes - Empty ContextPack returns empty
8. test_build_context_from_pack_with_envelopes - Builds structured context from envelopes
9. test_build_context_from_pack_truncates_long_summaries - Summary truncation works

## Patterns Used

- Uses tmpdir pytest fixture for file system operations
- Uses pytest.mark.parametrize for multiple test cases
- Follows existing test patterns from test_claude_stepwise_backend.py
- Imports from swarm.runtime.engines.claude.prompt_builder
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, Any

import pytest

# Add repo root to path for imports
repo_root = Path(__file__).resolve().parents[1]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from swarm.runtime.engines.claude.prompt_builder import (
    load_scent_trail,
    load_agent_persona,
    build_context_from_pack,
    build_artifact_pointers,
)
from swarm.runtime.context_pack import ContextPack
from swarm.runtime.types import HandoffEnvelope, RoutingSignal, RoutingDecision, RunSpec
from swarm.runtime.engines import StepContext
from datetime import datetime, timezone


def make_test_step_context(tmp_path, **overrides):
    """Helper to create a minimal StepContext for tests."""
    defaults = {
        "repo_root": tmp_path,
        "run_id": "test-run",
        "flow_key": "build",
        "step_id": "test-step",
        "step_index": 1,
        "total_steps": 5,
        "spec": RunSpec(flow_keys=["build"]),
        "flow_title": "Build Flow",
        "step_role": "Implement feature",
        "step_agents": ("code-implementer",),
        "history": [],
        "extra": {},
    }
    defaults.update(overrides)
    return StepContext(**defaults)


# =============================================================================
# Scent Trail Loading Tests
# =============================================================================


def test_load_scent_trail_returns_none_when_no_file(tmp_path):
    """Test that load_scent_trail returns None when no wisdom file exists."""
    result = load_scent_trail(tmp_path)
    assert result is None


def test_load_scent_trail_returns_content_when_file_exists(tmp_path):
    """Test that load_scent_trail returns content when wisdom file exists."""
    # Create wisdom file in new path
    wisdom_dir = tmp_path / ".runs" / "_wisdom"
    wisdom_dir.mkdir(parents=True)
    wisdom_file = wisdom_dir / "latest.md"
    wisdom_content = "# Lessons Learned\n\nAlways check for null pointers."
    wisdom_file.write_text(wisdom_content, encoding="utf-8")

    result = load_scent_trail(tmp_path)
    assert result is not None
    assert result == wisdom_content.strip()


def test_load_scent_trail_tries_both_paths(tmp_path):
    """Test that load_scent_trail tries both new and legacy paths."""
    # Create wisdom file in legacy path only
    legacy_wisdom_dir = tmp_path / "swarm" / "runs" / "_wisdom"
    legacy_wisdom_dir.mkdir(parents=True)
    legacy_file = legacy_wisdom_dir / "latest.md"
    legacy_content = "# Legacy Wisdom\n\nOld path still works."
    legacy_file.write_text(legacy_content, encoding="utf-8")

    result = load_scent_trail(tmp_path)
    assert result is not None
    assert result == legacy_content.strip()

    # Now create file in new path (should take precedence)
    new_wisdom_dir = tmp_path / ".runs" / "_wisdom"
    new_wisdom_dir.mkdir(parents=True)
    new_file = new_wisdom_dir / "latest.md"
    new_content = "# New Wisdom\n\nNew path takes precedence."
    new_file.write_text(new_content, encoding="utf-8")

    result = load_scent_trail(tmp_path)
    assert result is not None
    assert result == new_content.strip()


def test_load_scent_trail_handles_empty_file(tmp_path):
    """Test that load_scent_trail returns None for empty files."""
    wisdom_dir = tmp_path / ".runs" / "_wisdom"
    wisdom_dir.mkdir(parents=True)
    wisdom_file = wisdom_dir / "latest.md"
    wisdom_file.write_text("", encoding="utf-8")

    result = load_scent_trail(tmp_path)
    assert result is None


# =============================================================================
# Agentic Step Prompt Loading Tests
# =============================================================================


def test_load_agent_persona_from_agentic_steps(tmp_path):
    """Test that load_agent_persona loads from swarm/prompts/agentic_steps/ first."""
    # Create agentic_steps prompt
    agentic_dir = tmp_path / "swarm" / "prompts" / "agentic_steps"
    agentic_dir.mkdir(parents=True)
    agentic_file = agentic_dir / "code-implementer.md"
    agentic_content = """---
name: code-implementer
---

You are the Code Implementer.

## Behavior
Write production-quality code."""
    agentic_file.write_text(agentic_content, encoding="utf-8")

    # Use monkeypatch to mock flow_loader.load_agent_step_prompt
    from unittest.mock import patch
    with patch("swarm.runtime.engines.claude.prompt_builder.load_agent_step_prompt") as mock_load:
        expected_body = "You are the Code Implementer.\n\n## Behavior\nWrite production-quality code."
        mock_load.return_value = expected_body

        result = load_agent_persona(tmp_path, "code-implementer")

        assert result is not None
        assert "You are the Code Implementer" in result
        mock_load.assert_called_once_with("code-implementer", tmp_path)


def test_load_agent_persona_fallback_to_claude_agents(tmp_path):
    """Test that load_agent_persona falls back to .claude/agents/ when agentic_steps not found."""
    # Create .claude/agents file only
    claude_dir = tmp_path / ".claude" / "agents"
    claude_dir.mkdir(parents=True)
    claude_file = claude_dir / "test-critic.md"
    claude_content = """---
name: test-critic
description: Test critic agent
---

You are the Test Critic.

## Role
Review test coverage."""
    claude_file.write_text(claude_content, encoding="utf-8")

    # Mock flow_loader to return None (simulating agentic_steps not found)
    from unittest.mock import patch
    with patch("swarm.runtime.engines.claude.prompt_builder.load_agent_step_prompt") as mock_load:
        mock_load.return_value = None

        result = load_agent_persona(tmp_path, "test-critic")

        assert result is not None
        assert "You are the Test Critic" in result
        assert "## Role" in result
        assert "Review test coverage" in result


def test_load_agent_persona_strips_frontmatter(tmp_path):
    """Test that load_agent_persona strips YAML frontmatter from .claude/agents files."""
    claude_dir = tmp_path / ".claude" / "agents"
    claude_dir.mkdir(parents=True)
    claude_file = claude_dir / "test-agent.md"
    claude_content = """---
name: test-agent
model: sonnet
tools: [Read, Write]
---

Agent body starts here.

This should be returned."""
    claude_file.write_text(claude_content, encoding="utf-8")

    from unittest.mock import patch
    with patch("swarm.runtime.engines.claude.prompt_builder.load_agent_step_prompt") as mock_load:
        mock_load.return_value = None

        result = load_agent_persona(tmp_path, "test-agent")

        assert result is not None
        assert "---" not in result
        assert "name:" not in result
        assert "Agent body starts here" in result


def test_load_agent_persona_returns_none_when_not_found(tmp_path):
    """Test that load_agent_persona returns None when agent not found anywhere."""
    from unittest.mock import patch
    with patch("swarm.runtime.engines.claude.prompt_builder.load_agent_step_prompt") as mock_load:
        mock_load.return_value = None

        result = load_agent_persona(tmp_path, "nonexistent-agent")

        assert result is None


# =============================================================================
# ContextPack Context Building Tests
# =============================================================================


def test_build_context_from_pack_empty_envelopes():
    """Test that build_context_from_pack returns empty for ContextPack with no envelopes."""
    context_pack = ContextPack(
        run_id="test-run",
        flow_key="build",
        step_id="test-step",
        previous_envelopes=[],
        upstream_artifacts={},
    )

    lines, chars_used = build_context_from_pack(context_pack)

    assert lines == []
    assert chars_used == 0


def test_build_context_from_pack_with_envelopes():
    """Test that build_context_from_pack builds structured context from envelopes."""
    envelope1 = HandoffEnvelope(
        step_id="test-step-1",
        flow_key="build",
        run_id="test-run",
        routing_signal=RoutingSignal(
            decision=RoutingDecision.ADVANCE,
            reason="Tests passed",
            confidence=0.9,
            needs_human=False,
        ),
        summary="Implemented feature X successfully. All tests pass.",
        status="verified",
        duration_ms=1500,
        timestamp=datetime.now(timezone.utc),
        artifacts={"test_file": "tests/test_feature.py"},
        file_changes={
            "summary": "2 files modified: src/feature.py, tests/test_feature.py",
            "added": ["tests/test_feature.py"],
            "modified": ["src/feature.py"],
        },
    )

    envelope2 = HandoffEnvelope(
        step_id="test-step-2",
        flow_key="build",
        run_id="test-run",
        routing_signal=None,
        summary="Code review completed. Minor issues noted.",
        status="unverified",
        duration_ms=800,
        timestamp=datetime.now(timezone.utc),
    )

    context_pack = ContextPack(
        run_id="test-run",
        flow_key="build",
        step_id="test-step",
        previous_envelopes=[envelope1, envelope2],
        upstream_artifacts={"design_doc": "plan/design.md"},
    )

    lines, chars_used = build_context_from_pack(context_pack)

    # Verify structure
    assert len(lines) > 0
    assert chars_used > 0

    # Join lines for easier assertion
    context_text = "\n".join(lines)

    # Verify envelope 1 content
    assert "test-step-1" in context_text
    assert "[OK]" in context_text  # verified status emoji
    assert "Implemented feature X successfully" in context_text
    assert "advance" in context_text  # Routing decision is lowercase
    assert "Tests passed" in context_text
    assert "2 files modified" in context_text
    assert "test_file" in context_text

    # Verify envelope 2 content
    assert "test-step-2" in context_text
    assert "[?]" in context_text  # unverified status emoji
    assert "Code review completed" in context_text


def test_build_context_from_pack_truncates_long_summaries():
    """Test that build_context_from_pack truncates very long summaries."""
    long_summary = "A" * 3000  # 3000 chars, exceeds default 2000 char limit

    envelope = HandoffEnvelope(
        step_id="long-step",
        flow_key="build",
        run_id="test-run",
        routing_signal=None,
        summary=long_summary,
        status="verified",
        duration_ms=1000,
        timestamp=datetime.now(timezone.utc),
    )

    context_pack = ContextPack(
        run_id="test-run",
        flow_key="build",
        step_id="test-step",
        previous_envelopes=[envelope],
        upstream_artifacts={},
    )

    lines, chars_used = build_context_from_pack(context_pack, max_summary_chars=2000)

    context_text = "\n".join(lines)

    # Verify truncation
    assert "... (truncated)" in context_text
    # The summary in context should be shorter than original
    assert len(context_text) < len(long_summary)


def test_build_artifact_pointers_empty():
    """Test that build_artifact_pointers returns empty for ContextPack with no artifacts."""
    context_pack = ContextPack(
        run_id="test-run",
        flow_key="build",
        step_id="test-step",
        previous_envelopes=[],
        upstream_artifacts={},
    )

    lines = build_artifact_pointers(context_pack)

    assert lines == []


def test_build_artifact_pointers_with_artifacts():
    """Test that build_artifact_pointers formats upstream artifacts correctly."""
    context_pack = ContextPack(
        run_id="test-run",
        flow_key="build",
        step_id="test-step",
        previous_envelopes=[],
        upstream_artifacts={
            "design_doc": "plan/design.md",
            "test_plan": "plan/test_plan.md",
            "requirements": "signal/requirements.md",
        },
    )

    lines = build_artifact_pointers(context_pack)

    assert len(lines) > 0

    # Join lines for easier assertion
    pointer_text = "\n".join(lines)

    assert "## Available Upstream Artifacts" in pointer_text
    assert "design_doc" in pointer_text
    assert "plan/design.md" in pointer_text
    assert "test_plan" in pointer_text
    assert "plan/test_plan.md" in pointer_text
    assert "requirements" in pointer_text
    assert "signal/requirements.md" in pointer_text
    assert "Use the `Read` tool" in pointer_text


# =============================================================================
# Integration Test: Full Prompt Building
# =============================================================================


def test_build_prompt_injects_scent_trail_when_available(tmp_path):
    """Test that build_prompt injects scent trail into the prompt when available."""
    from swarm.runtime.engines.claude.prompt_builder import build_prompt

    # Create wisdom file
    wisdom_dir = tmp_path / ".runs" / "_wisdom"
    wisdom_dir.mkdir(parents=True)
    wisdom_file = wisdom_dir / "latest.md"
    wisdom_content = "# Key Lesson\n\nAlways validate inputs before processing."
    wisdom_file.write_text(wisdom_content, encoding="utf-8")

    # Create minimal StepContext
    ctx = make_test_step_context(tmp_path)

    prompt, truncation_info, persona = build_prompt(ctx, tmp_path)

    # Verify scent trail is injected
    assert "Wisdom from Previous Runs" in prompt
    assert "Always validate inputs before processing" in prompt


def test_build_prompt_handles_missing_scent_trail_gracefully(tmp_path):
    """Test that build_prompt works normally when no scent trail exists."""
    from swarm.runtime.engines.claude.prompt_builder import build_prompt

    ctx = make_test_step_context(tmp_path)

    prompt, truncation_info, persona = build_prompt(ctx, tmp_path)

    # Should not contain scent trail section
    assert "Wisdom from Previous Runs" not in prompt
    # But should still contain normal sections
    assert "Build Flow" in prompt
    assert "test-step" in prompt
