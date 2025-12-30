"""Tests for ClaudeStepEngine ContextPack hydration.

This module tests the hydration phase of the industrialized SDLC lifecycle:
1. ContextPack building when not already populated
2. ContextPack skipping when already populated
3. Hydration integration with run_worker()

## Test Coverage

### Hydration Phase (4 tests)
1. test_hydrate_context_builds_context_pack - Builds ContextPack when not populated
2. test_hydrate_context_skips_when_already_populated - Skips when context_pack exists
3. test_hydrate_context_handles_build_failure - Gracefully handles ContextPack build failure
4. test_run_worker_calls_hydrate_context - Verifies run_worker calls hydration

## Patterns Used

- Uses unittest.mock for patching internal methods
- Uses tmpdir pytest fixture for file system operations
- Follows existing test patterns from test_claude_stepwise_backend.py
- Imports from swarm.runtime.engines.claude.engine
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add repo root to path for imports
repo_root = Path(__file__).resolve().parents[1]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from swarm.runtime.engines.claude.engine import ClaudeStepEngine
from swarm.runtime.engines import StepContext
from swarm.runtime.context_pack import ContextPack
from swarm.runtime.types import HandoffEnvelope, RunSpec
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
# Hydration Phase Tests
# =============================================================================


def test_hydrate_context_builds_context_pack(tmp_path):
    """Test that _hydrate_context builds ContextPack when not already populated."""
    engine = ClaudeStepEngine(repo_root=tmp_path, mode="stub", enable_stats_db=False)

    # Create StepContext without context_pack
    ctx = make_test_step_context(tmp_path)

    # Mock build_context_pack to return a simple ContextPack
    with patch("swarm.runtime.engines.claude.engine.build_context_pack") as mock_build:
        mock_pack = ContextPack(
            run_id="test-run",
            flow_key="build",
            step_id="test-step",
            previous_envelopes=[],
            upstream_artifacts={"test": "test.md"},
        )
        mock_build.return_value = mock_pack

        hydrated_ctx = engine._hydrate_context(ctx)

        # Verify build_context_pack was called
        mock_build.assert_called_once()
        call_kwargs = mock_build.call_args[1]
        assert call_kwargs["ctx"] == ctx
        assert call_kwargs["repo_root"] == tmp_path

        # Verify context_pack was injected
        assert "context_pack" in hydrated_ctx.extra
        assert hydrated_ctx.extra["context_pack"] == mock_pack


def test_hydrate_context_skips_when_already_populated():
    """Test that _hydrate_context skips building when context_pack already exists."""
    engine = ClaudeStepEngine(mode="stub", enable_stats_db=False)

    # Create StepContext with pre-populated context_pack
    existing_pack = ContextPack(
        run_id="test-run",
        flow_key="build",
        step_id="test-step",
        previous_envelopes=[],
        upstream_artifacts={"existing": "artifact.md"},
    )
    ctx = make_test_step_context(Path.cwd(), extra={"context_pack": existing_pack})

    # Mock build_context_pack to verify it's NOT called
    with patch("swarm.runtime.engines.claude.engine.build_context_pack") as mock_build:
        hydrated_ctx = engine._hydrate_context(ctx)

        # Verify build_context_pack was NOT called
        mock_build.assert_not_called()

        # Verify existing context_pack is preserved
        assert "context_pack" in hydrated_ctx.extra
        assert hydrated_ctx.extra["context_pack"] == existing_pack


def test_hydrate_context_handles_build_failure(tmp_path):
    """Test that _hydrate_context handles ContextPack build failure gracefully."""
    engine = ClaudeStepEngine(repo_root=tmp_path, mode="stub", enable_stats_db=False)

    ctx = make_test_step_context(tmp_path)

    # Mock build_context_pack to raise an exception
    with patch("swarm.runtime.engines.claude.engine.build_context_pack") as mock_build:
        mock_build.side_effect = Exception("ContextPack build failed")

        # Should not raise exception, but log warning and continue
        hydrated_ctx = engine._hydrate_context(ctx)

        # Verify context_pack was NOT injected (fallback to raw history)
        assert "context_pack" not in hydrated_ctx.extra or hydrated_ctx.extra.get("context_pack") is None


def test_hydrate_context_populates_envelopes_and_artifacts(tmp_path):
    """Test that _hydrate_context populates both envelopes and artifacts in ContextPack."""
    engine = ClaudeStepEngine(repo_root=tmp_path, mode="stub", enable_stats_db=False)

    ctx = make_test_step_context(
        tmp_path,
        step_id="test-step-2",
        step_index=2,
        step_role="Review code",
        step_agents=("code-critic",),
    )

    # Mock build_context_pack to return a populated ContextPack
    with patch("swarm.runtime.engines.claude.engine.build_context_pack") as mock_build:
        mock_envelope = HandoffEnvelope(
            step_id="test-step-1",
            flow_key="build",
            run_id="test-run",
            routing_signal=None,
            summary="Previous step completed",
            status="verified",
            duration_ms=1000,
            timestamp=datetime.now(timezone.utc),
        )
        mock_pack = ContextPack(
            run_id="test-run",
            flow_key="build",
            step_id="test-step-2",
            previous_envelopes=[mock_envelope],
            upstream_artifacts={
                "design_doc": "plan/design.md",
                "test_plan": "plan/test_plan.md",
            },
        )
        mock_build.return_value = mock_pack

        hydrated_ctx = engine._hydrate_context(ctx)

        # Verify ContextPack has envelopes and artifacts
        context_pack = hydrated_ctx.extra.get("context_pack")
        assert context_pack is not None
        assert len(context_pack.previous_envelopes) == 1
        assert context_pack.previous_envelopes[0].step_id == "test-step-1"
        assert len(context_pack.upstream_artifacts) == 2
        assert "design_doc" in context_pack.upstream_artifacts
        assert "test_plan" in context_pack.upstream_artifacts


# =============================================================================
# Integration with run_worker
# =============================================================================


def test_run_worker_calls_hydrate_context(tmp_path):
    """Test that run_worker calls _hydrate_context before execution."""
    engine = ClaudeStepEngine(repo_root=tmp_path, mode="stub", enable_stats_db=False)

    ctx = make_test_step_context(tmp_path)

    # Create run_base directory
    ctx.run_base.mkdir(parents=True, exist_ok=True)

    # Spy on _hydrate_context
    with patch.object(engine, "_hydrate_context", wraps=engine._hydrate_context) as mock_hydrate:
        # Execute run_worker
        result, events, work_summary = engine.run_worker(ctx)

        # Verify _hydrate_context was called
        mock_hydrate.assert_called_once()
        assert mock_hydrate.call_args[0][0] == ctx

        # Verify result is returned
        assert result is not None
        assert result.step_id == "test-step"


def test_run_worker_stub_executes_with_hydrated_context(tmp_path):
    """Test that run_worker in stub mode executes successfully with hydrated context."""
    engine = ClaudeStepEngine(repo_root=tmp_path, mode="stub", enable_stats_db=False)

    ctx = make_test_step_context(tmp_path)

    # Create run_base directory
    ctx.run_base.mkdir(parents=True, exist_ok=True)

    # Mock build_context_pack to return a ContextPack
    with patch("swarm.runtime.engines.claude.engine.build_context_pack") as mock_build:
        mock_pack = ContextPack(
            run_id="test-run",
            flow_key="build",
            step_id="test-step",
            previous_envelopes=[],
            upstream_artifacts={"test": "test.md"},
        )
        mock_build.return_value = mock_pack

        result, events, work_summary = engine.run_worker(ctx)

        # Verify successful execution
        assert result.status == "succeeded"
        assert result.step_id == "test-step"
        assert len(events) > 0


# =============================================================================
# Integration with run_step (combined lifecycle)
# =============================================================================


def test_run_step_calls_hydrate_context(tmp_path):
    """Test that run_step calls _hydrate_context before execution."""
    engine = ClaudeStepEngine(repo_root=tmp_path, mode="stub", enable_stats_db=False)

    ctx = make_test_step_context(tmp_path)

    # Create run_base directory
    ctx.run_base.mkdir(parents=True, exist_ok=True)

    # Spy on _hydrate_context
    with patch.object(engine, "_hydrate_context", wraps=engine._hydrate_context) as mock_hydrate:
        # Execute run_step (combined lifecycle)
        result, events = engine.run_step(ctx)

        # Verify _hydrate_context was called
        mock_hydrate.assert_called_once()

        # Verify result is returned
        assert result is not None
        assert result.step_id == "test-step"


def test_hydrate_context_preserves_extra_fields(tmp_path):
    """Test that _hydrate_context preserves other fields in ctx.extra."""
    engine = ClaudeStepEngine(repo_root=tmp_path, mode="stub", enable_stats_db=False)

    # Create StepContext with existing extra fields
    ctx = make_test_step_context(
        tmp_path,
        extra={"custom_field": "custom_value", "another_field": 123},
    )

    with patch("swarm.runtime.engines.claude.engine.build_context_pack") as mock_build:
        mock_pack = ContextPack(
            run_id="test-run",
            flow_key="build",
            step_id="test-step",
            previous_envelopes=[],
            upstream_artifacts={},
        )
        mock_build.return_value = mock_pack

        hydrated_ctx = engine._hydrate_context(ctx)

        # Verify existing fields are preserved
        assert hydrated_ctx.extra.get("custom_field") == "custom_value"
        assert hydrated_ctx.extra.get("another_field") == 123
        # And context_pack is added
        assert "context_pack" in hydrated_ctx.extra
