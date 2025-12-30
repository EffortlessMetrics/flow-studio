"""
parallel.py - Parallel step execution for fork/join patterns.

This module provides parallel execution capabilities for the stepwise orchestrator,
enabling multiple agents to run concurrently when steps are marked as forkable.

Key features:
- Fork: Execute multiple steps in parallel
- Join: Aggregate results with configurable strategies
- Isolation: Each branch gets isolated context
- Failure handling: Continue, fail-fast, or best-effort policies

Usage:
    from swarm.runtime.stepwise.parallel import ParallelExecutor, ForkConfig, JoinConfig

    executor = ParallelExecutor(engine, max_workers=4)

    # Execute steps in parallel
    results = await executor.execute_fork(
        run_id="run-123",
        fork_config=ForkConfig(
            targets=["receipt", "contract", "security", "coverage"],
            execution_policy="concurrent",
            failure_policy="continue_all",
        ),
        contexts=step_contexts,  # One StepContext per target
    )

    # Join results
    joined = executor.join_results(
        results=results,
        join_config=JoinConfig(
            strategy="all_complete",
            merge_artifacts=True,
        ),
    )
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Dict,
    List,
    Optional,
    Tuple,
)

if TYPE_CHECKING:
    from swarm.runtime.engines import StepContext, StepEngine, StepResult
    from swarm.runtime.types import RunEvent, RunId

logger = logging.getLogger(__name__)


class ExecutionPolicy(str, Enum):
    """How to execute parallel branches."""

    CONCURRENT = "concurrent"  # All at once
    BATCH = "batch"  # In configurable batches


class FailurePolicy(str, Enum):
    """How to handle failures in parallel execution."""

    CONTINUE_ALL = "continue_all"  # Run all regardless of failures
    FAIL_FAST = "fail_fast"  # Stop on first failure
    BEST_EFFORT = "best_effort"  # Continue but mark as partial


class IsolationMode(str, Enum):
    """Context isolation between parallel branches."""

    SHARED = "shared"  # Branches can see each other's artifacts
    ISOLATED = "isolated"  # Each branch has own context


class JoinStrategy(str, Enum):
    """How to aggregate parallel results."""

    ALL_COMPLETE = "all_complete"  # Wait for all branches
    ALL_VERIFIED = "all_verified"  # Require all VERIFIED
    ANY_VERIFIED = "any_verified"  # Proceed when one succeeds
    FIRST_COMPLETE = "first_complete"  # Use first result
    QUORUM = "quorum"  # Require majority


class AggregateStatus(str, Enum):
    """How to determine final status from parallel results."""

    WORST = "worst"  # Lowest status (BLOCKED < PARTIAL < UNVERIFIED < VERIFIED)
    BEST = "best"  # Highest status
    MAJORITY = "majority"  # Mode of statuses


# Status ordering for worst/best aggregation
STATUS_ORDER = {
    "BLOCKED": 0,
    "PARTIAL": 1,
    "UNVERIFIED": 2,
    "VERIFIED": 3,
}


@dataclass
class ForkConfig:
    """Configuration for parallel execution (fork)."""

    targets: List[str]  # Node IDs to execute in parallel
    execution_policy: ExecutionPolicy = ExecutionPolicy.CONCURRENT
    batch_size: int = 4  # For batch policy
    isolation: IsolationMode = IsolationMode.ISOLATED
    failure_policy: FailurePolicy = FailurePolicy.CONTINUE_ALL

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ForkConfig":
        """Create ForkConfig from dictionary."""
        return cls(
            targets=data.get("targets", []),
            execution_policy=ExecutionPolicy(
                data.get("execution_policy", "concurrent")
            ),
            batch_size=data.get("batch_size", 4),
            isolation=IsolationMode(data.get("isolation", "isolated")),
            failure_policy=FailurePolicy(data.get("failure_policy", "continue_all")),
        )


@dataclass
class JoinConfig:
    """Configuration for aggregating parallel results (join)."""

    strategy: JoinStrategy = JoinStrategy.ALL_COMPLETE
    quorum_count: Optional[int] = None  # For quorum strategy
    timeout_seconds: int = 3600  # 1 hour default
    merge_artifacts: bool = True
    merge_concerns: bool = True
    aggregate_status: AggregateStatus = AggregateStatus.WORST

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "JoinConfig":
        """Create JoinConfig from dictionary."""
        return cls(
            strategy=JoinStrategy(data.get("strategy", "all_complete")),
            quorum_count=data.get("quorum_count"),
            timeout_seconds=data.get("timeout_seconds", 3600),
            merge_artifacts=data.get("merge_artifacts", True),
            merge_concerns=data.get("merge_concerns", True),
            aggregate_status=AggregateStatus(data.get("aggregate_status", "worst")),
        )


@dataclass
class BranchResult:
    """Result from a single parallel branch."""

    step_id: str
    status: str  # VERIFIED, UNVERIFIED, BLOCKED, PARTIAL
    summary: str
    artifacts: List[Dict[str, Any]] = field(default_factory=list)
    concerns: List[Dict[str, Any]] = field(default_factory=list)
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None
    duration_ms: int = 0
    error: Optional[str] = None

    # Full step result for downstream processing
    step_result: Optional[Any] = None
    events: List[Any] = field(default_factory=list)


@dataclass
class ForkResult:
    """Aggregated result from parallel execution."""

    fork_id: str
    branch_results: List[BranchResult]
    aggregate_status: str
    total_duration_ms: int
    started_at: datetime
    completed_at: datetime
    merged_artifacts: List[Dict[str, Any]] = field(default_factory=list)
    merged_concerns: List[Dict[str, Any]] = field(default_factory=list)
    join_strategy_used: str = "all_complete"
    failed_branches: List[str] = field(default_factory=list)
    skipped_branches: List[str] = field(default_factory=list)


@dataclass
class ParallelContext:
    """Context injected into each parallel branch."""

    fork_id: str
    branch_index: int
    total_branches: int
    sibling_step_ids: List[str]
    join_point: Optional[str] = None
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class ParallelExecutor:
    """Executor for parallel step execution.

    This class manages the parallel execution of multiple steps,
    handling fork/join patterns with configurable policies.
    """

    def __init__(
        self,
        engine: "StepEngine",
        max_workers: int = 8,
        event_emitter: Optional[Callable[[str, "RunEvent"], None]] = None,
    ):
        """Initialize the parallel executor.

        Args:
            engine: StepEngine for executing individual steps.
            max_workers: Maximum concurrent workers.
            event_emitter: Optional callback for emitting events.
        """
        self._engine = engine
        self._max_workers = max_workers
        self._event_emitter = event_emitter
        self._executor = ThreadPoolExecutor(max_workers=max_workers)

    def shutdown(self) -> None:
        """Shutdown the executor."""
        self._executor.shutdown(wait=True)

    def execute_fork_sync(
        self,
        run_id: "RunId",
        fork_config: ForkConfig,
        contexts: List["StepContext"],
        join_config: Optional[JoinConfig] = None,
    ) -> ForkResult:
        """Execute fork synchronously (blocking).

        Args:
            run_id: The run identifier.
            fork_config: Fork configuration.
            contexts: List of StepContext, one per target.
            join_config: Optional join configuration.

        Returns:
            ForkResult with aggregated results.
        """
        # Use asyncio.run() to execute the async version
        return asyncio.get_event_loop().run_until_complete(
            self.execute_fork(run_id, fork_config, contexts, join_config)
        )

    async def execute_fork(
        self,
        run_id: "RunId",
        fork_config: ForkConfig,
        contexts: List["StepContext"],
        join_config: Optional[JoinConfig] = None,
    ) -> ForkResult:
        """Execute multiple steps in parallel.

        Args:
            run_id: The run identifier.
            fork_config: Fork configuration.
            contexts: List of StepContext, one per target.
            join_config: Optional join configuration.

        Returns:
            ForkResult with aggregated results.
        """
        fork_id = f"fork-{uuid.uuid4().hex[:8]}"
        started_at = datetime.now(timezone.utc)
        join_cfg = join_config or JoinConfig()

        logger.info(
            "Starting fork %s with %d branches: %s",
            fork_id,
            len(fork_config.targets),
            fork_config.targets,
        )

        # Emit fork_started event
        self._emit_event(
            run_id,
            {
                "kind": "fork_started",
                "fork_id": fork_id,
                "targets": fork_config.targets,
                "execution_policy": fork_config.execution_policy.value,
                "failure_policy": fork_config.failure_policy.value,
            },
        )

        # Create parallel context for each branch
        parallel_contexts = [
            ParallelContext(
                fork_id=fork_id,
                branch_index=i,
                total_branches=len(fork_config.targets),
                sibling_step_ids=fork_config.targets,
                started_at=started_at,
            )
            for i in range(len(fork_config.targets))
        ]

        # Execute based on policy
        if fork_config.execution_policy == ExecutionPolicy.CONCURRENT:
            results = await self._execute_concurrent(
                run_id, fork_config, contexts, parallel_contexts
            )
        else:
            results = await self._execute_batched(
                run_id, fork_config, contexts, parallel_contexts
            )

        completed_at = datetime.now(timezone.utc)

        # Join results
        fork_result = self._join_results(
            fork_id=fork_id,
            results=results,
            join_config=join_cfg,
            started_at=started_at,
            completed_at=completed_at,
        )

        # Emit fork_completed event
        self._emit_event(
            run_id,
            {
                "kind": "fork_completed",
                "fork_id": fork_id,
                "aggregate_status": fork_result.aggregate_status,
                "total_duration_ms": fork_result.total_duration_ms,
                "branch_count": len(results),
                "failed_count": len(fork_result.failed_branches),
            },
        )

        return fork_result

    async def _execute_concurrent(
        self,
        run_id: "RunId",
        fork_config: ForkConfig,
        contexts: List["StepContext"],
        parallel_contexts: List[ParallelContext],
    ) -> List[BranchResult]:
        """Execute all branches concurrently."""
        loop = asyncio.get_event_loop()

        # Create tasks for each branch
        tasks = []
        for i, (ctx, parallel_ctx) in enumerate(zip(contexts, parallel_contexts)):
            task = loop.run_in_executor(
                self._executor,
                self._execute_branch,
                run_id,
                fork_config.targets[i],
                ctx,
                parallel_ctx,
            )
            tasks.append(task)

        # Handle failure policy
        if fork_config.failure_policy == FailurePolicy.FAIL_FAST:
            # Use asyncio.gather with return_exceptions=False
            # First failure will raise and cancel others
            results = []
            for coro in asyncio.as_completed(tasks):
                try:
                    result = await coro
                    results.append(result)
                    if result.error is not None:
                        # Cancel remaining tasks
                        for task in tasks:
                            if not task.done():
                                task.cancel()
                        break
                except asyncio.CancelledError:
                    pass
            return results
        else:
            # Wait for all with return_exceptions=True
            raw_results = await asyncio.gather(*tasks, return_exceptions=True)
            results = []
            for i, result in enumerate(raw_results):
                if isinstance(result, Exception):
                    results.append(
                        BranchResult(
                            step_id=fork_config.targets[i],
                            status="BLOCKED",
                            summary=f"Exception: {result}",
                            error=str(result),
                            completed_at=datetime.now(timezone.utc),
                        )
                    )
                else:
                    results.append(result)
            return results

    async def _execute_batched(
        self,
        run_id: "RunId",
        fork_config: ForkConfig,
        contexts: List["StepContext"],
        parallel_contexts: List[ParallelContext],
    ) -> List[BranchResult]:
        """Execute branches in batches."""
        results = []
        batch_size = fork_config.batch_size

        for batch_start in range(0, len(contexts), batch_size):
            batch_end = min(batch_start + batch_size, len(contexts))
            batch_contexts = contexts[batch_start:batch_end]
            batch_parallel = parallel_contexts[batch_start:batch_end]
            batch_targets = fork_config.targets[batch_start:batch_end]

            logger.debug(
                "Executing batch %d-%d of %d",
                batch_start,
                batch_end,
                len(contexts),
            )

            loop = asyncio.get_event_loop()
            tasks = [
                loop.run_in_executor(
                    self._executor,
                    self._execute_branch,
                    run_id,
                    batch_targets[i],
                    batch_contexts[i],
                    batch_parallel[i],
                )
                for i in range(len(batch_contexts))
            ]

            batch_results = await asyncio.gather(*tasks, return_exceptions=True)

            for i, result in enumerate(batch_results):
                if isinstance(result, Exception):
                    results.append(
                        BranchResult(
                            step_id=batch_targets[i],
                            status="BLOCKED",
                            summary=f"Exception: {result}",
                            error=str(result),
                            completed_at=datetime.now(timezone.utc),
                        )
                    )
                else:
                    results.append(result)

            # Check failure policy for batch-level failures
            if fork_config.failure_policy == FailurePolicy.FAIL_FAST:
                for r in results:
                    if r.error is not None:
                        logger.warning("Fail-fast triggered, stopping batch execution")
                        return results

        return results

    def _execute_branch(
        self,
        run_id: "RunId",
        step_id: str,
        ctx: "StepContext",
        parallel_ctx: ParallelContext,
    ) -> BranchResult:
        """Execute a single branch (runs in thread pool).

        Args:
            run_id: The run identifier.
            step_id: The step ID for this branch.
            ctx: StepContext for execution.
            parallel_ctx: ParallelContext for this branch.

        Returns:
            BranchResult with execution results.
        """
        started_at = datetime.now(timezone.utc)

        try:
            logger.debug(
                "Branch %d/%d starting: %s",
                parallel_ctx.branch_index + 1,
                parallel_ctx.total_branches,
                step_id,
            )

            # Inject parallel context into step context
            # This allows the step to know it's running in parallel
            ctx_with_parallel = self._inject_parallel_context(ctx, parallel_ctx)

            # Execute the step
            step_result, events = self._engine.run_step(ctx_with_parallel)

            completed_at = datetime.now(timezone.utc)
            duration_ms = int((completed_at - started_at).total_seconds() * 1000)

            # Extract artifacts and concerns from result
            artifacts = []
            concerns = []
            summary = ""

            if hasattr(step_result, "output") and step_result.output:
                summary = step_result.output[:500]  # Truncate for summary

            if hasattr(step_result, "artifacts"):
                artifacts = step_result.artifacts or []

            if hasattr(step_result, "concerns"):
                concerns = step_result.concerns or []

            logger.debug(
                "Branch %d/%d completed: %s -> %s (%dms)",
                parallel_ctx.branch_index + 1,
                parallel_ctx.total_branches,
                step_id,
                step_result.status,
                duration_ms,
            )

            return BranchResult(
                step_id=step_id,
                status=step_result.status,
                summary=summary,
                artifacts=artifacts,
                concerns=concerns,
                started_at=started_at,
                completed_at=completed_at,
                duration_ms=duration_ms,
                step_result=step_result,
                events=list(events),
            )

        except Exception as e:
            completed_at = datetime.now(timezone.utc)
            duration_ms = int((completed_at - started_at).total_seconds() * 1000)

            logger.error(
                "Branch %d/%d failed: %s -> %s",
                parallel_ctx.branch_index + 1,
                parallel_ctx.total_branches,
                step_id,
                e,
            )

            return BranchResult(
                step_id=step_id,
                status="BLOCKED",
                summary=f"Execution failed: {e}",
                started_at=started_at,
                completed_at=completed_at,
                duration_ms=duration_ms,
                error=str(e),
            )

    def _inject_parallel_context(
        self,
        ctx: "StepContext",
        parallel_ctx: ParallelContext,
    ) -> "StepContext":
        """Inject parallel context into step context.

        This modifies the context to include parallel execution metadata
        that can be used by the step and persisted to the handoff envelope.

        Args:
            ctx: Original StepContext.
            parallel_ctx: ParallelContext to inject.

        Returns:
            Modified StepContext with parallel context.
        """
        import dataclasses

        # If ctx is not a dataclass (e.g., mock), return as-is
        if not dataclasses.is_dataclass(ctx):
            return ctx

        # Create a shallow copy of the context
        from dataclasses import replace

        # Add parallel context to the routing or metadata
        routing_with_parallel = {}
        if ctx.routing is not None and hasattr(ctx.routing, "__dict__"):
            routing_with_parallel = dict(ctx.routing.__dict__)
        routing_with_parallel["parallel_context"] = {
            "fork_id": parallel_ctx.fork_id,
            "branch_index": parallel_ctx.branch_index,
            "total_branches": parallel_ctx.total_branches,
            "sibling_step_ids": parallel_ctx.sibling_step_ids,
            "started_at": parallel_ctx.started_at.isoformat(),
        }

        # Create new routing context with parallel info
        from swarm.runtime.engines.models import RoutingContext

        new_routing = RoutingContext(
            kind=ctx.routing.kind if ctx.routing else "linear",
            next_step_id=ctx.routing.next_step_id if ctx.routing else None,
            loop_target=ctx.routing.loop_target if ctx.routing else None,
            max_iterations=ctx.routing.max_iterations if ctx.routing else None,
            parallel_context=routing_with_parallel.get("parallel_context"),
        )

        return replace(ctx, routing=new_routing)

    def _join_results(
        self,
        fork_id: str,
        results: List[BranchResult],
        join_config: JoinConfig,
        started_at: datetime,
        completed_at: datetime,
    ) -> ForkResult:
        """Join results from parallel branches.

        Args:
            fork_id: The fork identifier.
            results: List of BranchResult from each branch.
            join_config: Join configuration.
            started_at: When the fork started.
            completed_at: When all branches completed.

        Returns:
            ForkResult with aggregated data.
        """
        # Collect statuses
        statuses = [r.status for r in results]
        failed_branches = [r.step_id for r in results if r.error is not None]
        skipped_branches: List[str] = []

        # Aggregate status based on strategy
        aggregate_status = self._compute_aggregate_status(
            statuses, join_config.aggregate_status
        )

        # Merge artifacts if configured
        merged_artifacts: List[Dict[str, Any]] = []
        if join_config.merge_artifacts:
            for r in results:
                for artifact in r.artifacts:
                    artifact_with_source = dict(artifact)
                    artifact_with_source["source_branch"] = r.step_id
                    merged_artifacts.append(artifact_with_source)

        # Merge concerns if configured
        merged_concerns: List[Dict[str, Any]] = []
        if join_config.merge_concerns:
            for r in results:
                for concern in r.concerns:
                    concern_with_source = dict(concern)
                    concern_with_source["source_branch"] = r.step_id
                    merged_concerns.append(concern_with_source)

        # Calculate total duration
        total_duration_ms = int((completed_at - started_at).total_seconds() * 1000)

        return ForkResult(
            fork_id=fork_id,
            branch_results=results,
            aggregate_status=aggregate_status,
            total_duration_ms=total_duration_ms,
            started_at=started_at,
            completed_at=completed_at,
            merged_artifacts=merged_artifacts,
            merged_concerns=merged_concerns,
            join_strategy_used=join_config.strategy.value,
            failed_branches=failed_branches,
            skipped_branches=skipped_branches,
        )

    def _compute_aggregate_status(
        self,
        statuses: List[str],
        strategy: AggregateStatus,
    ) -> str:
        """Compute aggregate status from individual branch statuses.

        Args:
            statuses: List of status strings.
            strategy: Aggregation strategy.

        Returns:
            Aggregate status string.
        """
        if not statuses:
            return "BLOCKED"

        if strategy == AggregateStatus.WORST:
            # Return the lowest status
            return min(statuses, key=lambda s: STATUS_ORDER.get(s, 0))
        elif strategy == AggregateStatus.BEST:
            # Return the highest status
            return max(statuses, key=lambda s: STATUS_ORDER.get(s, 0))
        else:  # MAJORITY
            # Return the most common status
            from collections import Counter

            counter = Counter(statuses)
            return counter.most_common(1)[0][0]

    def _emit_event(self, run_id: "RunId", payload: Dict[str, Any]) -> None:
        """Emit an event via the configured emitter."""
        if self._event_emitter is not None:
            from swarm.runtime.types import RunEvent

            event = RunEvent(
                run_id=run_id,
                ts=datetime.now(timezone.utc),
                kind=payload.get("kind", "parallel_event"),
                flow_key="",
                step_id=None,
                payload=payload,
            )
            self._event_emitter(run_id, event)


def create_fork_contexts(
    base_context: "StepContext",
    fork_config: ForkConfig,
    step_configs: Dict[str, Dict[str, Any]],
) -> List["StepContext"]:
    """Create StepContext for each fork target.

    This utility function helps create the list of contexts needed
    for parallel execution.

    Args:
        base_context: The base context to clone.
        fork_config: Fork configuration with targets.
        step_configs: Optional per-step configuration overrides.

    Returns:
        List of StepContext, one per fork target.
    """
    from dataclasses import replace

    contexts = []
    for target in fork_config.targets:
        config = step_configs.get(target, {})
        ctx = replace(
            base_context,
            step_id=target,
            step_role=config.get("role", target),
            step_agents=tuple(config.get("agents", [target])),
        )
        contexts.append(ctx)

    return contexts


__all__ = [
    "AggregateStatus",
    "BranchResult",
    "ExecutionPolicy",
    "FailurePolicy",
    "ForkConfig",
    "ForkResult",
    "IsolationMode",
    "JoinConfig",
    "JoinStrategy",
    "ParallelContext",
    "ParallelExecutor",
    "create_fork_contexts",
]
