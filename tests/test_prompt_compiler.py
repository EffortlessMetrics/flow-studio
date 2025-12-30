"""Tests for the prompt compiler with fragment injection."""

import pytest
from pathlib import Path
from unittest.mock import patch
import tempfile
import os

from swarm.prompts.compiler import (
    compile_prompt,
    compile_prompt_with_metadata,
    compile_step_prompt,
    find_fragment_markers,
    get_fragment_dirs,
    get_fragment_usage,
    list_fragments,
    load_fragment,
    validate_all_prompts,
    validate_prompt,
    clear_cache,
    MAX_FRAGMENT_DEPTH,
)


@pytest.fixture
def temp_repo(tmp_path):
    """Create a temporary repository structure for testing."""
    # Create fragment directories
    fragments_dir = tmp_path / "swarm" / "prompts" / "fragments"
    fragments_dir.mkdir(parents=True)

    spec_fragments = tmp_path / "swarm" / "spec" / "fragments"
    spec_fragments.mkdir(parents=True)

    prompts_dir = tmp_path / "swarm" / "prompts" / "agentic_steps"
    prompts_dir.mkdir(parents=True)

    # Create test fragments
    (fragments_dir / "test_fragment.md").write_text(
        "This is a test fragment.\n\nWith multiple lines."
    )

    (fragments_dir / "nested_outer.md").write_text(
        "Outer fragment with {{nested_inner}} inside."
    )

    (fragments_dir / "nested_inner.md").write_text(
        "Inner fragment content."
    )

    (spec_fragments / "common" / "status_model.md").parent.mkdir(parents=True, exist_ok=True)
    (spec_fragments / "common" / "status_model.md").write_text(
        "Status model from spec fragments."
    )

    # Create test prompt
    (prompts_dir / "test-agent.md").write_text(
        """---
name: test-agent
description: A test agent
---

You are the test agent.

{{test_fragment}}

## Guidelines

{{common/status_model}}

End of prompt.
"""
    )

    # Create prompt with missing fragment
    (prompts_dir / "broken-agent.md").write_text(
        """---
name: broken-agent
---

{{missing_fragment}}
"""
    )

    # Create prompt with circular reference
    (fragments_dir / "circular_a.md").write_text("A references {{circular_b}}")
    (fragments_dir / "circular_b.md").write_text("B references {{circular_a}}")

    (prompts_dir / "circular-agent.md").write_text("{{circular_a}}")

    # Create prompt with explicit fragment syntax
    (prompts_dir / "explicit-agent.md").write_text(
        """---
name: explicit-agent
---

Using explicit syntax: {{fragment:test_fragment}}

And path syntax: {{fragment:common/status_model}}
"""
    )

    # Clear cache before each test
    clear_cache()

    return tmp_path


class TestLoadFragment:
    """Tests for fragment loading."""

    def test_load_simple_fragment(self, temp_repo):
        """Test loading a simple fragment by name."""
        content = load_fragment("test_fragment", temp_repo)
        assert "This is a test fragment" in content

    def test_load_fragment_with_extension(self, temp_repo):
        """Test loading fragment with .md extension."""
        content = load_fragment("test_fragment.md", temp_repo)
        assert "This is a test fragment" in content

    def test_load_fragment_from_spec_dir(self, temp_repo):
        """Test loading fragment from spec/fragments fallback."""
        content = load_fragment("common/status_model", temp_repo)
        assert "Status model from spec fragments" in content

    def test_fragment_not_found(self, temp_repo):
        """Test error when fragment doesn't exist."""
        with pytest.raises(FileNotFoundError) as exc_info:
            load_fragment("nonexistent_fragment", temp_repo)
        assert "nonexistent_fragment" in str(exc_info.value)

    def test_fragment_caching(self, temp_repo):
        """Test that fragments are cached."""
        # Load twice, should use cache
        content1 = load_fragment("test_fragment", temp_repo)
        content2 = load_fragment("test_fragment", temp_repo)
        assert content1 == content2


class TestListFragments:
    """Tests for listing available fragments."""

    def test_list_all_fragments(self, temp_repo):
        """Test listing all available fragments."""
        fragments = list_fragments(temp_repo)
        assert "test_fragment" in fragments
        assert "nested_outer" in fragments
        assert "nested_inner" in fragments

    def test_list_includes_subdirs(self, temp_repo):
        """Test that fragments in subdirectories are listed."""
        fragments = list_fragments(temp_repo)
        # common/status_model should be in the list
        assert "common/status_model" in fragments


class TestFindFragmentMarkers:
    """Tests for finding fragment markers in content."""

    def test_find_simple_markers(self):
        """Test finding simple fragment markers."""
        content = "Start {{fragment_one}} middle {{fragment_two}} end"
        markers = find_fragment_markers(content)
        assert "fragment_one" in markers
        assert "fragment_two" in markers

    def test_find_path_markers(self):
        """Test finding path-style fragment markers."""
        content = "{{common/invariants}} and {{microloop/critic_never_fixes}}"
        markers = find_fragment_markers(content)
        assert "common/invariants" in markers
        assert "microloop/critic_never_fixes" in markers

    def test_no_markers(self):
        """Test content with no markers."""
        content = "Just plain text with no markers."
        markers = find_fragment_markers(content)
        assert markers == []

    def test_invalid_markers_ignored(self):
        """Test that invalid markers are not matched."""
        content = "{{}} and {{ spaces }} and {{with.dots}}"
        markers = find_fragment_markers(content)
        # Only valid patterns should match
        assert len(markers) == 0 or all("." not in m and m.strip() for m in markers)


class TestCompilePrompt:
    """Tests for prompt compilation."""

    def test_compile_simple_prompt(self, temp_repo):
        """Test compiling a prompt with fragment injection."""
        prompt_path = temp_repo / "swarm" / "prompts" / "agentic_steps" / "test-agent.md"
        result = compile_prompt(str(prompt_path), temp_repo)

        assert "You are the test agent" in result
        assert "This is a test fragment" in result
        assert "Status model from spec fragments" in result
        assert "{{test_fragment}}" not in result  # Marker replaced
        assert "{{common/status_model}}" not in result  # Marker replaced

    def test_compile_with_metadata(self, temp_repo):
        """Test compilation returns metadata."""
        prompt_path = temp_repo / "swarm" / "prompts" / "agentic_steps" / "test-agent.md"
        result = compile_prompt_with_metadata(str(prompt_path), temp_repo)

        assert result.content
        assert result.source_path
        assert result.content_hash
        assert "test_fragment" in result.fragments_used
        assert "common/status_model" in result.fragments_used

    def test_compile_explicit_syntax(self, temp_repo):
        """Test compiling a prompt with explicit {{fragment:name}} syntax."""
        prompt_path = temp_repo / "swarm" / "prompts" / "agentic_steps" / "explicit-agent.md"
        result = compile_prompt(str(prompt_path), temp_repo)

        assert "This is a test fragment" in result
        assert "Status model from spec fragments" in result
        assert "{{fragment:test_fragment}}" not in result  # Marker replaced
        assert "{{fragment:common/status_model}}" not in result  # Marker replaced

    def test_find_explicit_markers(self):
        """Test finding explicit {{fragment:name}} markers."""
        content = "Text {{fragment:git_safety_rules}} and {{fragment:common/invariants}}"
        markers = find_fragment_markers(content)
        assert "git_safety_rules" in markers
        assert "common/invariants" in markers

    def test_compile_nested_fragments(self, temp_repo):
        """Test compilation handles nested fragments."""
        # Create a prompt that uses the nested fragment
        prompt_path = temp_repo / "swarm" / "prompts" / "agentic_steps" / "nested-test.md"
        prompt_path.write_text("Start {{nested_outer}} end")

        result = compile_prompt(str(prompt_path), temp_repo)

        assert "Outer fragment" in result
        assert "Inner fragment content" in result
        assert "{{nested_inner}}" not in result  # Nested marker also replaced

    def test_compile_missing_fragment(self, temp_repo):
        """Test compilation handles missing fragments gracefully."""
        prompt_path = temp_repo / "swarm" / "prompts" / "agentic_steps" / "broken-agent.md"
        result = compile_prompt(str(prompt_path), temp_repo)

        assert "[FRAGMENT NOT FOUND: missing_fragment]" in result

    def test_compile_circular_reference(self, temp_repo):
        """Test compilation detects circular references."""
        prompt_path = temp_repo / "swarm" / "prompts" / "agentic_steps" / "circular-agent.md"
        result = compile_prompt(str(prompt_path), temp_repo)

        assert "[CIRCULAR REFERENCE:" in result

    def test_compile_nonexistent_prompt(self, temp_repo):
        """Test error when prompt file doesn't exist."""
        with pytest.raises(FileNotFoundError):
            compile_prompt("nonexistent.md", temp_repo)

    def test_compile_caching(self, temp_repo):
        """Test that compiled prompts are cached."""
        prompt_path = temp_repo / "swarm" / "prompts" / "agentic_steps" / "test-agent.md"

        result1 = compile_prompt_with_metadata(str(prompt_path), temp_repo)
        result2 = compile_prompt_with_metadata(str(prompt_path), temp_repo)

        # Should get the same cached result
        assert result1.content_hash == result2.content_hash
        assert result1.compiled_at == result2.compiled_at


class TestValidatePrompt:
    """Tests for prompt validation."""

    def test_validate_valid_prompt(self, temp_repo):
        """Test validation of prompt with all fragments present."""
        prompt_path = temp_repo / "swarm" / "prompts" / "agentic_steps" / "test-agent.md"
        missing = validate_prompt(str(prompt_path), temp_repo)

        assert missing == []

    def test_validate_missing_fragment(self, temp_repo):
        """Test validation detects missing fragments."""
        prompt_path = temp_repo / "swarm" / "prompts" / "agentic_steps" / "broken-agent.md"
        missing = validate_prompt(str(prompt_path), temp_repo)

        assert "missing_fragment" in missing

    def test_validate_nonexistent_prompt(self, temp_repo):
        """Test validation of nonexistent prompt."""
        missing = validate_prompt("nonexistent.md", temp_repo)
        assert any("PROMPT_NOT_FOUND" in m for m in missing)

    def test_validate_all_prompts(self, temp_repo):
        """Test validating all prompts in a directory."""
        results = validate_all_prompts(
            "swarm/prompts/agentic_steps",
            temp_repo
        )

        # Should find the broken agent
        assert any("broken-agent.md" in k for k in results.keys())


class TestFragmentUsage:
    """Tests for fragment usage reporting."""

    def test_get_fragment_usage(self, temp_repo):
        """Test getting fragment usage report."""
        usage = get_fragment_usage(temp_repo)

        # test_fragment should be used by test-agent.md
        if "test_fragment" in usage:
            assert any("test-agent.md" in p for p in usage["test_fragment"])


class TestGetFragmentDirs:
    """Tests for fragment directory discovery."""

    def test_get_fragment_dirs(self, temp_repo):
        """Test getting fragment directories."""
        dirs = get_fragment_dirs(temp_repo)

        assert len(dirs) >= 1
        assert all(d.exists() for d in dirs)


class TestDeepNesting:
    """Tests for deeply nested fragment handling."""

    def test_max_depth_exceeded(self, temp_repo):
        """Test that deep nesting raises RecursionError."""
        fragments_dir = temp_repo / "swarm" / "prompts" / "fragments"

        # Create a chain of fragments deeper than MAX_FRAGMENT_DEPTH
        for i in range(MAX_FRAGMENT_DEPTH + 2):
            if i == MAX_FRAGMENT_DEPTH + 1:
                (fragments_dir / f"deep_{i}.md").write_text("End of chain")
            else:
                (fragments_dir / f"deep_{i}.md").write_text(f"Level {i} {{{{deep_{i+1}}}}}")

        prompt_path = temp_repo / "swarm" / "prompts" / "agentic_steps" / "deep-test.md"
        prompt_path.write_text("{{deep_0}}")

        with pytest.raises(RecursionError):
            compile_prompt(str(prompt_path), temp_repo)


class TestClearCache:
    """Tests for cache clearing."""

    def test_clear_cache(self, temp_repo):
        """Test that clearing cache works."""
        # Load something to populate cache
        load_fragment("test_fragment", temp_repo)

        # Clear and verify we can still load (just testing it doesn't error)
        clear_cache()
        content = load_fragment("test_fragment", temp_repo)
        assert content
