"""
Tests for parallel step execution (fork/join patterns).

These tests verify the ParallelExecutor correctly handles:
- Concurrent execution of multiple steps
- Batched execution with configurable batch size
- Various join strategies (all_complete, all_verified, any_verified, quorum)
- Failure policies (continue_all, fail_fast, best_effort)
- Context injection for parallel branches
- Result aggregation and status computation
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple
from unittest.mock import MagicMock, patch

import pytest

from swarm.runtime.stepwise.parallel import (
    AggregateStatus,
    BranchResult,
    ExecutionPolicy,
    FailurePolicy,
    ForkConfig,
    ForkResult,
    IsolationMode,
    JoinConfig,
    JoinStrategy,
    ParallelContext,
    ParallelExecutor,
    create_fork_contexts,
)


@dataclass
class MockStepResult:
    """Mock step result for testing."""

    status: str = "VERIFIED"
    output: str = "Mock output"
    duration_ms: int = 100
    artifacts: Optional[List[Dict[str, Any]]] = None
    concerns: Optional[List[Dict[str, Any]]] = None


class MockStepEngine:
    """Mock step engine for testing parallel execution."""

    def __init__(
        self,
        results: Optional[Dict[str, MockStepResult]] = None,
        delay_ms: int = 0,
        error_steps: Optional[List[str]] = None,
    ):
        """Initialize mock engine.

        Args:
            results: Dict of step_id -> result to return.
            delay_ms: Simulated delay per step execution.
            error_steps: List of step IDs that should raise exceptions.
        """
        self._results = results or {}
        self._delay_ms = delay_ms
        self._error_steps = error_steps or []
        self._execution_log: List[Tuple[str, datetime]] = []

    def run_step(self, ctx: Any) -> Tuple[MockStepResult, Iterable[Any]]:
        """Execute a step."""
        step_id = ctx.step_id
        self._execution_log.append((step_id, datetime.now(timezone.utc)))

        # Simulate delay
        if self._delay_ms > 0:
            import time

            time.sleep(self._delay_ms / 1000.0)

        # Simulate error
        if step_id in self._error_steps:
            raise RuntimeError(f"Simulated error in step {step_id}")

        # Return configured result or default
        result = self._results.get(step_id, MockStepResult())
        return result, []

    @property
    def execution_log(self) -> List[Tuple[str, datetime]]:
        """Get the execution log."""
        return self._execution_log


class TestForkConfig:
    """Tests for ForkConfig."""

    def test_from_dict_basic(self):
        """Test creating ForkConfig from dictionary."""
        data = {
            "targets": ["step1", "step2", "step3"],
            "execution_policy": "concurrent",
            "failure_policy": "continue_all",
        }
        config = ForkConfig.from_dict(data)

        assert config.targets == ["step1", "step2", "step3"]
        assert config.execution_policy == ExecutionPolicy.CONCURRENT
        assert config.failure_policy == FailurePolicy.CONTINUE_ALL
        assert config.isolation == IsolationMode.ISOLATED  # default

    def test_from_dict_with_batch(self):
        """Test ForkConfig with batch execution."""
        data = {
            "targets": ["a", "b", "c", "d"],
            "execution_policy": "batch",
            "batch_size": 2,
        }
        config = ForkConfig.from_dict(data)

        assert config.execution_policy == ExecutionPolicy.BATCH
        assert config.batch_size == 2


class TestJoinConfig:
    """Tests for JoinConfig."""

    def test_from_dict_basic(self):
        """Test creating JoinConfig from dictionary."""
        data = {
            "strategy": "all_verified",
            "merge_artifacts": True,
            "aggregate_status": "worst",
        }
        config = JoinConfig.from_dict(data)

        assert config.strategy == JoinStrategy.ALL_VERIFIED
        assert config.merge_artifacts is True
        assert config.aggregate_status == AggregateStatus.WORST

    def test_from_dict_with_quorum(self):
        """Test JoinConfig with quorum strategy."""
        data = {
            "strategy": "quorum",
            "quorum_count": 3,
        }
        config = JoinConfig.from_dict(data)

        assert config.strategy == JoinStrategy.QUORUM
        assert config.quorum_count == 3


class TestParallelExecutor:
    """Tests for ParallelExecutor."""

    @pytest.fixture
    def mock_engine(self):
        """Create a mock engine."""
        return MockStepEngine()

    @pytest.fixture
    def executor(self, mock_engine):
        """Create a parallel executor with mock engine."""
        return ParallelExecutor(engine=mock_engine, max_workers=4)

    def test_concurrent_execution(self, executor, mock_engine):
        """Test that steps execute concurrently."""
        fork_config = ForkConfig(
            targets=["step1", "step2", "step3", "step4"],
            execution_policy=ExecutionPolicy.CONCURRENT,
        )

        # Create mock contexts
        contexts = [MagicMock(step_id=t) for t in fork_config.targets]

        # Execute fork synchronously
        result = executor.execute_fork_sync(
            run_id="test-run",
            fork_config=fork_config,
            contexts=contexts,
        )

        # Verify all branches completed
        assert len(result.branch_results) == 4
        assert all(br.status == "VERIFIED" for br in result.branch_results)

        # Verify execution order is logged
        assert len(mock_engine.execution_log) == 4

    def test_batched_execution(self, mock_engine):
        """Test batched execution."""
        mock_engine._delay_ms = 10  # Small delay to see batching
        executor = ParallelExecutor(engine=mock_engine, max_workers=2)

        fork_config = ForkConfig(
            targets=["a", "b", "c", "d"],
            execution_policy=ExecutionPolicy.BATCH,
            batch_size=2,
        )

        contexts = [MagicMock(step_id=t) for t in fork_config.targets]

        result = executor.execute_fork_sync(
            run_id="test-run",
            fork_config=fork_config,
            contexts=contexts,
        )

        assert len(result.branch_results) == 4
        assert result.aggregate_status == "VERIFIED"

    def test_failure_policy_continue_all(self, mock_engine):
        """Test continue_all failure policy."""
        mock_engine._error_steps = ["step2"]
        executor = ParallelExecutor(engine=mock_engine, max_workers=4)

        fork_config = ForkConfig(
            targets=["step1", "step2", "step3"],
            failure_policy=FailurePolicy.CONTINUE_ALL,
        )

        contexts = [MagicMock(step_id=t) for t in fork_config.targets]

        result = executor.execute_fork_sync(
            run_id="test-run",
            fork_config=fork_config,
            contexts=contexts,
        )

        # All branches should complete (even with error)
        assert len(result.branch_results) == 3

        # One should be failed
        failed = [br for br in result.branch_results if br.error is not None]
        assert len(failed) == 1
        assert failed[0].step_id == "step2"

    def test_aggregate_status_worst(self, mock_engine):
        """Test worst status aggregation."""
        mock_engine._results = {
            "step1": MockStepResult(status="VERIFIED"),
            "step2": MockStepResult(status="UNVERIFIED"),
            "step3": MockStepResult(status="VERIFIED"),
        }
        executor = ParallelExecutor(engine=mock_engine, max_workers=4)

        fork_config = ForkConfig(targets=["step1", "step2", "step3"])
        join_config = JoinConfig(aggregate_status=AggregateStatus.WORST)

        contexts = [MagicMock(step_id=t) for t in fork_config.targets]

        result = executor.execute_fork_sync(
            run_id="test-run",
            fork_config=fork_config,
            contexts=contexts,
            join_config=join_config,
        )

        # Should be UNVERIFIED (worst of the three)
        assert result.aggregate_status == "UNVERIFIED"

    def test_aggregate_status_best(self, mock_engine):
        """Test best status aggregation."""
        mock_engine._results = {
            "step1": MockStepResult(status="BLOCKED"),
            "step2": MockStepResult(status="VERIFIED"),
            "step3": MockStepResult(status="UNVERIFIED"),
        }
        executor = ParallelExecutor(engine=mock_engine, max_workers=4)

        fork_config = ForkConfig(targets=["step1", "step2", "step3"])
        join_config = JoinConfig(aggregate_status=AggregateStatus.BEST)

        contexts = [MagicMock(step_id=t) for t in fork_config.targets]

        result = executor.execute_fork_sync(
            run_id="test-run",
            fork_config=fork_config,
            contexts=contexts,
            join_config=join_config,
        )

        # Should be VERIFIED (best of the three)
        assert result.aggregate_status == "VERIFIED"

    def test_merge_artifacts(self, mock_engine):
        """Test artifact merging."""
        mock_engine._results = {
            "step1": MockStepResult(
                status="VERIFIED",
                artifacts=[{"path": "audit1.md", "action": "created"}],
            ),
            "step2": MockStepResult(
                status="VERIFIED",
                artifacts=[{"path": "audit2.md", "action": "created"}],
            ),
        }
        executor = ParallelExecutor(engine=mock_engine, max_workers=4)

        fork_config = ForkConfig(targets=["step1", "step2"])
        join_config = JoinConfig(merge_artifacts=True)

        contexts = [MagicMock(step_id=t) for t in fork_config.targets]

        result = executor.execute_fork_sync(
            run_id="test-run",
            fork_config=fork_config,
            contexts=contexts,
            join_config=join_config,
        )

        # Should have merged artifacts from both branches
        assert len(result.merged_artifacts) == 2
        paths = [a["path"] for a in result.merged_artifacts]
        assert "audit1.md" in paths
        assert "audit2.md" in paths

    def test_merge_concerns(self, mock_engine):
        """Test concern merging."""
        mock_engine._results = {
            "step1": MockStepResult(
                status="UNVERIFIED",
                concerns=[{"concern": "Missing tests", "severity": "medium"}],
            ),
            "step2": MockStepResult(
                status="VERIFIED",
                concerns=[{"concern": "Deprecated API", "severity": "low"}],
            ),
        }
        executor = ParallelExecutor(engine=mock_engine, max_workers=4)

        fork_config = ForkConfig(targets=["step1", "step2"])
        join_config = JoinConfig(merge_concerns=True)

        contexts = [MagicMock(step_id=t) for t in fork_config.targets]

        result = executor.execute_fork_sync(
            run_id="test-run",
            fork_config=fork_config,
            contexts=contexts,
            join_config=join_config,
        )

        # Should have merged concerns from both branches
        assert len(result.merged_concerns) == 2

    def test_fork_id_generation(self, executor):
        """Test that fork IDs are unique."""
        fork_config = ForkConfig(targets=["a", "b"])
        contexts = [MagicMock(step_id=t) for t in fork_config.targets]

        result1 = executor.execute_fork_sync("run1", fork_config, contexts)
        result2 = executor.execute_fork_sync("run2", fork_config, contexts)

        assert result1.fork_id != result2.fork_id
        assert result1.fork_id.startswith("fork-")
        assert result2.fork_id.startswith("fork-")

    def test_duration_tracking(self, mock_engine):
        """Test that duration is tracked correctly."""
        mock_engine._delay_ms = 50
        executor = ParallelExecutor(engine=mock_engine, max_workers=4)

        fork_config = ForkConfig(targets=["step1", "step2"])
        contexts = [MagicMock(step_id=t) for t in fork_config.targets]

        result = executor.execute_fork_sync(
            run_id="test-run",
            fork_config=fork_config,
            contexts=contexts,
        )

        # Total duration should be at least the delay (parallel execution)
        assert result.total_duration_ms >= 50

        # Each branch should have duration tracked
        for br in result.branch_results:
            assert br.duration_ms >= 50


class TestGateFlowParallel:
    """Integration tests for Gate flow parallel execution."""

    def test_gate_flow_config_has_parallel_section(self):
        """Test that gate.yaml has parallel configuration."""
        import yaml
        from pathlib import Path

        gate_path = (
            Path(__file__).parent.parent
            / "swarm"
            / "config"
            / "flows"
            / "gate.yaml"
        )

        with open(gate_path) as f:
            config = yaml.safe_load(f)

        # Check parallel section exists
        assert "parallel" in config
        parallel = config["parallel"]

        # Check fork configuration
        assert parallel["fork_point"] == "receipt"
        assert set(parallel["fork_config"]["targets"]) == {
            "contract",
            "security",
            "coverage",
            "policy_check",
        }

        # Check join configuration
        assert parallel["join_point"] == "gate_fix"
        assert parallel["join_config"]["strategy"] == "all_complete"

    def test_gate_flow_steps_have_parallel_markers(self):
        """Test that gate flow steps have parallel_branch markers."""
        import yaml
        from pathlib import Path

        gate_path = (
            Path(__file__).parent.parent
            / "swarm"
            / "config"
            / "flows"
            / "gate.yaml"
        )

        with open(gate_path) as f:
            config = yaml.safe_load(f)

        steps = {s["id"]: s for s in config["steps"]}

        # Fork step should have fork routing
        assert steps["receipt"]["routing"]["kind"] == "fork"
        assert set(steps["receipt"]["routing"]["fork_targets"]) == {
            "contract",
            "security",
            "coverage",
            "policy_check",
        }

        # Parallel branches should have parallel_branch marker
        for branch_id in ["contract", "security", "coverage", "policy_check"]:
            assert steps[branch_id].get("parallel_branch") is True

        # Join step should have join routing
        assert steps["gate_fix"]["routing"]["kind"] == "join"
        assert steps["gate_fix"].get("join_point") is True


class TestCreateForkContexts:
    """Tests for create_fork_contexts utility."""

    def test_creates_contexts_for_each_target(self):
        """Test that contexts are created for each fork target."""
        from swarm.runtime.engines.models import RoutingContext, StepContext
        from swarm.runtime.types import RunSpec
        from pathlib import Path

        base_ctx = StepContext(
            repo_root=Path("/test"),
            run_id="test-run",
            flow_key="gate",
            step_id="receipt",
            step_index=1,
            total_steps=6,
            spec=MagicMock(spec=RunSpec),
            flow_title="Gate Flow",
            step_role="Receipt check",
        )

        fork_config = ForkConfig(
            targets=["contract", "security", "coverage"],
        )

        step_configs = {
            "contract": {"role": "contract-check", "agents": ["contract-enforcer"]},
            "security": {"role": "security-scan", "agents": ["security-scanner"]},
            "coverage": {"role": "coverage-check", "agents": ["coverage-enforcer"]},
        }

        contexts = create_fork_contexts(base_ctx, fork_config, step_configs)

        assert len(contexts) == 3
        assert contexts[0].step_id == "contract"
        assert contexts[1].step_id == "security"
        assert contexts[2].step_id == "coverage"
        assert contexts[0].step_role == "contract-check"
