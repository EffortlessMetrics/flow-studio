"""Tests for context budget guardrails (v2.5.0).

Tests the sanity bounds validation in ContextBudgetResolver and
truncation tracking in step engines.
"""

import pytest
from pathlib import Path
import sys

_SWARM_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_SWARM_ROOT))

from swarm.config.runtime_config import (
    ContextBudgetResolver,
    ContextBudgetConfig,
    BUDGET_MIN_CHARS,
    BUDGET_MAX_CHARS,
    BUDGET_WARN_THRESHOLD,
    _clamp_budget_value,
)
from swarm.runtime.engines import HistoryTruncationInfo


class TestBudgetClamping:
    """Tests for budget value clamping."""

    def test_clamp_value_within_bounds(self):
        """Values within bounds are unchanged."""
        assert _clamp_budget_value(100_000, "test") == 100_000
        assert _clamp_budget_value(200_000, "test") == 200_000
        assert _clamp_budget_value(BUDGET_MIN_CHARS, "test") == BUDGET_MIN_CHARS
        assert _clamp_budget_value(BUDGET_MAX_CHARS, "test") == BUDGET_MAX_CHARS

    def test_clamp_value_below_minimum(self, caplog):
        """Values below minimum are clamped up."""
        result = _clamp_budget_value(5_000, "test")
        assert result == BUDGET_MIN_CHARS
        assert "below minimum" in caplog.text

    def test_clamp_value_above_maximum(self, caplog):
        """Values above maximum are clamped down."""
        result = _clamp_budget_value(1_000_000, "test")
        assert result == BUDGET_MAX_CHARS
        assert "exceeds maximum" in caplog.text

    def test_clamp_wildly_wrong_value(self, caplog):
        """Wildly wrong values trigger warning and clamp."""
        result = _clamp_budget_value(10_000_000, "test")  # 10M chars
        assert result == BUDGET_MAX_CHARS
        assert "suspiciously large" in caplog.text

    def test_constants_have_sensible_values(self):
        """Verify constants are sensible."""
        assert BUDGET_MIN_CHARS == 10_000
        assert BUDGET_MAX_CHARS == 600_000
        assert BUDGET_WARN_THRESHOLD == 5_000_000
        assert BUDGET_MIN_CHARS < BUDGET_MAX_CHARS
        assert BUDGET_MAX_CHARS < BUDGET_WARN_THRESHOLD


class TestResolverGuardrails:
    """Tests for ContextBudgetResolver validation."""

    def test_resolve_clamps_to_bounds(self):
        """Resolver clamps resolved values to sanity bounds."""
        resolver = ContextBudgetResolver()
        result = resolver.resolve()

        assert result.context_budget_chars >= BUDGET_MIN_CHARS
        assert result.context_budget_chars <= BUDGET_MAX_CHARS
        assert result.history_max_recent_chars >= BUDGET_MIN_CHARS
        assert result.history_max_recent_chars <= BUDGET_MAX_CHARS
        assert result.history_max_older_chars >= BUDGET_MIN_CHARS
        assert result.history_max_older_chars <= BUDGET_MAX_CHARS

    def test_resolve_enforces_relational_constraints(self):
        """recent_max and older_max don't exceed total."""
        resolver = ContextBudgetResolver()
        result = resolver.resolve()

        assert result.history_max_recent_chars <= result.context_budget_chars
        assert result.history_max_older_chars <= result.context_budget_chars


class TestHistoryTruncationInfo:
    """Tests for HistoryTruncationInfo dataclass."""

    def test_truncation_note_when_not_truncated(self):
        """No note when all steps included."""
        info = HistoryTruncationInfo(
            steps_included=5,
            steps_total=5,
            chars_used=50_000,
            budget_chars=200_000,
            truncated=False,
        )
        assert info.truncation_note == ""

    def test_truncation_note_when_truncated(self):
        """Machine-readable note when steps omitted."""
        info = HistoryTruncationInfo(
            steps_included=7,
            steps_total=19,
            chars_used=200_000,
            budget_chars=200_000,
            truncated=True,
        )
        note = info.truncation_note
        assert "[CONTEXT_TRUNCATED]" in note
        assert "7 of 19" in note
        assert "12 omitted" in note

    def test_to_dict_returns_all_fields(self):
        """to_dict() includes all fields for receipt serialization."""
        info = HistoryTruncationInfo(
            steps_included=5,
            steps_total=10,
            chars_used=50_000,
            budget_chars=200_000,
            truncated=True,
        )
        d = info.to_dict()
        assert d["steps_included"] == 5
        assert d["steps_total"] == 10
        assert d["chars_used"] == 50_000
        assert d["budget_chars"] == 200_000
        assert d["truncated"] is True

    def test_to_dict_when_not_truncated(self):
        """to_dict() works when not truncated."""
        info = HistoryTruncationInfo(
            steps_included=3,
            steps_total=3,
            chars_used=15_000,
            budget_chars=200_000,
            truncated=False,
        )
        d = info.to_dict()
        assert d["truncated"] is False


class TestModelRegistry:
    """Tests for model registry and budget computation."""

    def test_builtin_models_available(self):
        """Built-in models should be available without config."""
        from swarm.config.model_registry import list_known_models, get_model_spec

        models = list_known_models()
        assert "claude-sonnet-4-5-20250929" in models
        assert "gemini-3-flash-preview" in models

        claude = get_model_spec("claude-sonnet-4-5-20250929")
        assert claude is not None
        assert claude.context_tokens == 200000

    def test_model_context_chars_computation(self):
        """context_chars should be tokens * 4."""
        from swarm.config.model_registry import get_model_spec

        model = get_model_spec("claude-sonnet-4-5-20250929")
        assert model.context_chars == model.context_tokens * 4

    def test_budget_computation_for_200k_model(self):
        """200k token model computes correct budgets."""
        from swarm.config.model_registry import compute_model_budgets

        budgets = compute_model_budgets("claude-sonnet-4-5-20250929")
        # 200k tokens * 4 chars = 800k chars * 0.25 = 200k chars
        assert budgets["context_budget_chars"] == 200000
        # 800k * 0.075 = 60k
        assert budgets["history_max_recent_chars"] == 60000
        # 800k * 0.025 = 20k
        assert budgets["history_max_older_chars"] == 20000

    def test_budget_computation_for_1m_model(self):
        """1M token model computes larger budgets."""
        from swarm.config.model_registry import compute_model_budgets

        budgets = compute_model_budgets("gemini-3-flash-preview")
        # 1M tokens * 4 chars = 4M chars * 0.25 = 1M chars
        assert budgets["context_budget_chars"] == 1048576

    def test_unknown_model_falls_back_to_defaults(self):
        """Unknown model uses hardcoded defaults."""
        from swarm.config.model_registry import compute_model_budgets

        budgets = compute_model_budgets("unknown-model-xyz")
        assert budgets["context_budget_chars"] == 200000
        assert budgets["history_max_recent_chars"] == 60000
        assert budgets["history_max_older_chars"] == 10000


class TestHistoryTruncationInfoPriority:
    """Tests for priority-aware truncation info (v2.5.0)."""

    def test_priority_aware_default_true(self):
        """priority_aware defaults to True in new code."""
        info = HistoryTruncationInfo(
            steps_included=5,
            steps_total=10,
            chars_used=50_000,
            budget_chars=200_000,
            truncated=True,
        )
        assert info.priority_aware is True

    def test_priority_distribution_in_note(self):
        """Truncation note includes priority distribution when truncated."""
        info = HistoryTruncationInfo(
            steps_included=5,
            steps_total=10,
            chars_used=50_000,
            budget_chars=200_000,
            truncated=True,
            priority_aware=True,
            priority_distribution={"CRITICAL": 2, "HIGH": 2, "MEDIUM": 1, "LOW": 0},
        )
        note = info.truncation_note
        assert "[Priority:" in note
        assert "CRITICAL=2" in note
        assert "HIGH=2" in note
        assert "MEDIUM=1" in note
        assert "LOW=0" in note

    def test_priority_distribution_in_dict(self):
        """to_dict includes priority_distribution when present."""
        info = HistoryTruncationInfo(
            steps_included=5,
            steps_total=10,
            chars_used=50_000,
            budget_chars=200_000,
            truncated=True,
            priority_aware=True,
            priority_distribution={"CRITICAL": 2, "HIGH": 2, "MEDIUM": 1, "LOW": 0},
        )
        d = info.to_dict()
        assert d["priority_aware"] is True
        assert d["priority_distribution"] == {"CRITICAL": 2, "HIGH": 2, "MEDIUM": 1, "LOW": 0}

    def test_priority_distribution_omitted_when_none(self):
        """to_dict omits priority_distribution when None."""
        info = HistoryTruncationInfo(
            steps_included=5,
            steps_total=5,
            chars_used=50_000,
            budget_chars=200_000,
            truncated=False,
        )
        d = info.to_dict()
        assert "priority_distribution" not in d

    def test_no_priority_note_when_not_truncated(self):
        """Priority info not in note when not truncated."""
        info = HistoryTruncationInfo(
            steps_included=5,
            steps_total=5,
            chars_used=50_000,
            budget_chars=200_000,
            truncated=False,
            priority_aware=True,
            priority_distribution={"CRITICAL": 2, "HIGH": 2, "MEDIUM": 1, "LOW": 0},
        )
        note = info.truncation_note
        assert note == ""  # No note when not truncated


class TestPriorityAwarePromptBuilding:
    """Integration tests for priority-aware history selection in prompts."""

    @pytest.fixture
    def tmp_repo(self, tmp_path: Path) -> Path:
        """Create a temporary repo structure."""
        runs_dir = tmp_path / "swarm" / "runs"
        runs_dir.mkdir(parents=True)
        return tmp_path

    def test_critical_items_kept_over_low(self, tmp_repo: Path):
        """When budget is tight, CRITICAL items are kept over LOW items."""
        from swarm.runtime.engines import GeminiStepEngine, StepContext
        from swarm.runtime.types import RunSpec

        engine = GeminiStepEngine(tmp_repo)
        engine.stub_mode = True

        # Create history with mixed priorities
        history = [
            # LOW priority (will be dropped first)
            {"step_id": "s1", "agent_key": "gh-reporter", "status": "succeeded", "output": "A" * 10000},
            # CRITICAL priority (should be kept)
            {"step_id": "s2", "agent_key": "code-implementer", "status": "succeeded", "output": "B" * 10000},
            # LOW priority (will be dropped first)
            {"step_id": "s3", "agent_key": "doc-writer", "status": "succeeded", "output": "C" * 10000},
            # CRITICAL priority (should be kept)
            {"step_id": "s4", "agent_key": "merge-decider", "status": "succeeded", "output": "D" * 10000},
        ]

        spec = RunSpec(
            flow_keys=["build"],
            profile_id=None,
            backend="test",
            initiator="test",
        )

        ctx = StepContext(
            repo_root=tmp_repo,
            run_id="test-run",
            flow_key="build",
            step_id="test_step",
            step_index=5,
            total_steps=5,
            spec=spec,
            flow_title="Test Flow",
            step_role="Test step",
            step_agents=("test-agent",),
            history=history,
            extra={},
        )

        prompt, truncation_info, _ = engine._build_prompt(ctx)

        # CRITICAL items (code-implementer, merge-decider) should be in prompt
        assert "s2" in prompt  # code-implementer
        assert "s4" in prompt  # merge-decider

        # Truncation info should show priority-aware selection
        if truncation_info and truncation_info.priority_distribution:
            # Should have more CRITICAL than LOW items included
            dist = truncation_info.priority_distribution
            assert dist.get("CRITICAL", 0) >= dist.get("LOW", 0)

    def test_chronological_order_preserved_in_output(self, tmp_repo: Path):
        """Even with priority sorting, final output is chronological."""
        from swarm.runtime.engines import ClaudeStepEngine, StepContext
        from swarm.runtime.types import RunSpec

        engine = ClaudeStepEngine(tmp_repo, mode="stub")

        # History in chronological order
        history = [
            {"step_id": "step_1", "agent_key": "risk-analyst", "status": "succeeded", "output": "Risk analysis"},
            {"step_id": "step_2", "agent_key": "code-implementer", "status": "succeeded", "output": "Implementation"},
            {"step_id": "step_3", "agent_key": "code-critic", "status": "succeeded", "output": "Critique"},
        ]

        spec = RunSpec(
            flow_keys=["build"],
            profile_id=None,
            backend="test",
            initiator="test",
        )

        ctx = StepContext(
            repo_root=tmp_repo,
            run_id="test-run",
            flow_key="build",
            step_id="final_step",
            step_index=4,
            total_steps=4,
            spec=spec,
            flow_title="Test Flow",
            step_role="Test step",
            step_agents=("test-agent",),
            history=history,
            extra={},
        )

        prompt, _, _ = engine._build_prompt(ctx)

        # Find positions in prompt - chronological order should be maintained
        pos_1 = prompt.find("step_1")
        pos_2 = prompt.find("step_2")
        pos_3 = prompt.find("step_3")

        # All should be present and in order
        assert pos_1 < pos_2 < pos_3, "History should appear in chronological order"
