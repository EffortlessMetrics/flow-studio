#!/usr/bin/env python3
"""
Unit tests for gen_adapters.py model precedence logic.

Verifies that:
  1. `model: inherit` is preserved as-is through the pipeline
  2. Per-platform overrides only apply when they explicitly set `model`
  3. `model_tier` is metadata only (not used by the generator)
"""

import tempfile
from pathlib import Path

from gen_adapters import (
    AgentConfig,
    PlatformConfig,
    get_platform_agent_override,
    render_frontmatter,
)


def create_test_platform(tmp_dir: Path) -> PlatformConfig:
    """Create a minimal test platform config."""
    agents_dir = tmp_dir / ".claude" / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)

    return PlatformConfig(
        name="claude",
        agents_dir=agents_dir,
        models={},
    )


def create_template() -> str:
    """Create a minimal test template."""
    return """---
name: {name}
description: {description}
color: {color}
model: {model}
---

You are the **{name}**.
"""


class TestModelInheritPreservation:
    """Test that model: inherit survives the pipeline untouched."""

    def test_inherit_from_config_no_override(self):
        """When config has model: inherit and no override, output should have model: inherit."""
        agent = AgentConfig(
            key="example",
            short_role="Do something",
            model="inherit",
            color="blue",
            model_tier="balanced",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            platform = create_test_platform(Path(tmpdir))
            template = create_template()

            fm = render_frontmatter(agent, platform, template, "claude")
            assert "model: inherit" in fm, f"Expected 'model: inherit' in:\n{fm}"

    def test_inherit_with_tier_metadata_ignored(self):
        """model_tier should be metadata only; shouldn't affect output."""
        agent = AgentConfig(
            key="example",
            short_role="Do something",
            model="inherit",
            color="blue",
            model_tier="fast",  # Explicitly set to "fast"
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            platform = create_test_platform(Path(tmpdir))
            template = create_template()

            fm = render_frontmatter(agent, platform, template, "claude")
            # Even with model_tier="fast", output should still have model: inherit
            assert "model: inherit" in fm, f"Expected 'model: inherit' in:\n{fm}"
            assert "fast" not in fm, f"model_tier should not appear in frontmatter:\n{fm}"

    def test_explicit_model_preserved(self):
        """When config has model: haiku, output should have model: haiku."""
        agent = AgentConfig(
            key="example",
            short_role="Do something",
            model="haiku",
            color="blue",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            platform = create_test_platform(Path(tmpdir))
            template = create_template()

            fm = render_frontmatter(agent, platform, template, "claude")
            assert "model: haiku" in fm, f"Expected 'model: haiku' in:\n{fm}"

    def test_explicit_sonnet_preserved(self):
        """When config has model: sonnet, output should have model: sonnet."""
        agent = AgentConfig(
            key="example",
            short_role="Do something",
            model="sonnet",
            color="blue",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            platform = create_test_platform(Path(tmpdir))
            template = create_template()

            fm = render_frontmatter(agent, platform, template, "claude")
            assert "model: sonnet" in fm, f"Expected 'model: sonnet' in:\n{fm}"


class TestPerPlatformOverrides:
    """Test that per-platform overrides only apply when explicitly set."""

    def test_override_takes_precedence_over_config(self):
        """Per-platform override['model'] should override config['model']."""
        agent = AgentConfig(
            key="example",
            short_role="Do something",
            model="haiku",
            color="blue",
            platforms={"claude": {"model": "sonnet"}},
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            platform = create_test_platform(Path(tmpdir))
            template = create_template()

            fm = render_frontmatter(agent, platform, template, "claude")
            assert "model: sonnet" in fm, f"Expected 'model: sonnet' in:\n{fm}"

    def test_override_inherit_to_explicit(self):
        """Per-platform override can change inherit to explicit model."""
        agent = AgentConfig(
            key="example",
            short_role="Do something",
            model="inherit",
            color="blue",
            platforms={"claude": {"model": "opus"}},
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            platform = create_test_platform(Path(tmpdir))
            template = create_template()

            fm = render_frontmatter(agent, platform, template, "claude")
            assert "model: opus" in fm, f"Expected 'model: opus' in:\n{fm}"

    def test_override_explicit_to_inherit(self):
        """Per-platform override can force inherit even if config has explicit model."""
        agent = AgentConfig(
            key="example",
            short_role="Do something",
            model="haiku",
            color="blue",
            platforms={"claude": {"model": "inherit"}},
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            platform = create_test_platform(Path(tmpdir))
            template = create_template()

            fm = render_frontmatter(agent, platform, template, "claude")
            assert "model: inherit" in fm, f"Expected 'model: inherit' in:\n{fm}"

    def test_override_other_fields_ignored_for_model(self):
        """Override with model_tier but no model should not affect output."""
        agent = AgentConfig(
            key="example",
            short_role="Do something",
            model="inherit",
            color="blue",
            platforms={"claude": {"model_tier": "fast"}},  # Only model_tier, no model
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            platform = create_test_platform(Path(tmpdir))
            template = create_template()

            fm = render_frontmatter(agent, platform, template, "claude")
            assert "model: inherit" in fm, f"Expected 'model: inherit' in:\n{fm}"


class TestGetPlatformAgentOverride:
    """Test the override lookup helper."""

    def test_override_exists(self):
        """Should return override dict when present."""
        agent = AgentConfig(
            key="example",
            short_role="Do something",
            model="inherit",
            color="blue",
            platforms={"claude": {"model": "sonnet"}},
        )

        override = get_platform_agent_override(agent, "claude")
        assert override == {"model": "sonnet"}

    def test_override_missing(self):
        """Should return empty dict when no override."""
        agent = AgentConfig(
            key="example",
            short_role="Do something",
            model="inherit",
            color="blue",
        )

        override = get_platform_agent_override(agent, "claude")
        assert override == {}

    def test_override_for_different_platform(self):
        """Should return empty dict for platform not in overrides."""
        agent = AgentConfig(
            key="example",
            short_role="Do something",
            model="inherit",
            color="blue",
            platforms={"openai": {"model": "gpt-4"}},
        )

        override = get_platform_agent_override(agent, "claude")
        assert override == {}


class TestDefaultFallbacks:
    """Test default behavior when fields are missing."""

    def test_missing_model_defaults_to_inherit(self):
        """When agent.model is None, should default to inherit."""
        agent = AgentConfig(
            key="example",
            short_role="Do something",
            model=None,  # Explicitly None
            color="blue",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            platform = create_test_platform(Path(tmpdir))
            template = create_template()

            fm = render_frontmatter(agent, platform, template, "claude")
            assert "model: inherit" in fm, f"Expected 'model: inherit' in:\n{fm}"

    def test_empty_string_model_defaults_to_inherit(self):
        """When agent.model is empty string, should default to inherit."""
        agent = AgentConfig(
            key="example",
            short_role="Do something",
            model="",  # Empty string
            color="blue",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            platform = create_test_platform(Path(tmpdir))
            template = create_template()

            fm = render_frontmatter(agent, platform, template, "claude")
            assert "model: inherit" in fm, f"Expected 'model: inherit' in:\n{fm}"


if __name__ == "__main__":
    # Simple test runner for quick validation
    import sys

    test_classes = [
        TestModelInheritPreservation,
        TestPerPlatformOverrides,
        TestGetPlatformAgentOverride,
        TestDefaultFallbacks,
    ]

    total = 0
    passed = 0

    for test_class in test_classes:
        instance = test_class()
        for method_name in dir(instance):
            if method_name.startswith("test_"):
                total += 1
                try:
                    method = getattr(instance, method_name)
                    method()
                    print(f"[OK] {test_class.__name__}.{method_name}")
                    passed += 1
                except AssertionError as e:
                    print(f"[FAIL] {test_class.__name__}.{method_name}")
                    print(f"  {e}")
                except Exception as e:
                    print(f"[FAIL] {test_class.__name__}.{method_name} (ERROR)")
                    print(f"  {e}")

    print(f"\n{passed}/{total} tests passed")
    sys.exit(0 if passed == total else 1)
