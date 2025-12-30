"""
utility_flow_injection.py - Utility flow detection and injection for stepwise orchestrator.

This module implements injection detection for utility flows (e.g., Reset/Flow 8).
Utility flows are defined with:
- `is_utility_flow: true` in metadata
- `injection_trigger` (e.g., "upstream_diverged", "lint_failure", "security_concern")
- `on_complete.next_flow: "return"` (stack-frame pattern for resumption)

The orchestrator uses this module to:
1. Load and index utility flows from pack specs
2. Detect when injection triggers fire (based on step outputs, git status, verification)
3. Inject the utility flow using an interruption stack (stack-frame pattern)
4. Handle "return" semantics when utility flow completes

Usage:
    from swarm.runtime.utility_flow_injection import (
        UtilityFlowRegistry,
        InjectionTriggerDetector,
        UtilityFlowInjector,
        detect_injection_triggers,
    )

    # Initialize
    registry = UtilityFlowRegistry(repo_root)
    detector = InjectionTriggerDetector(registry)
    injector = UtilityFlowInjector(registry)

    # After step completion, check for triggers
    triggered = detector.check_triggers(step_result, run_state, git_status)

    # If triggered, inject utility flow
    if triggered:
        first_node_id = injector.inject_utility_flow(
            triggered.flow_id,
            run_state,
            current_node,
        )
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

from swarm.config.flow_registry import FlowDefinition
from swarm.runtime.types import (
    InjectedNodeSpec,
    InterruptionFrame,
    RunState,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Injection Trigger Types
# =============================================================================


class InjectionTrigger:
    """Known injection trigger types for utility flows.

    These are the canonical triggers that utility flows can define.
    Each trigger has detection logic in InjectionTriggerDetector.
    """

    UPSTREAM_DIVERGED = "upstream_diverged"
    LINT_FAILURE = "lint_failure"
    SECURITY_CONCERN = "security_concern"
    DEPENDENCY_UPDATE = "dependency_update"
    CONFLICT_DETECTED = "conflict_detected"
    TEST_FLAKE = "test_flake"
    ENV_SETUP_FAILURE = "env_setup_failure"


@dataclass
class UtilityFlowMetadata:
    """Metadata for a utility flow loaded from pack specs.

    Attributes:
        flow_id: The flow identifier (e.g., "reset-flow").
        flow_number: Flow number (8+ for utility flows).
        injection_trigger: The trigger condition (e.g., "upstream_diverged").
        on_complete_next_flow: What to do when complete ("return" or flow ID).
        on_complete_reason: Reason message for completion.
        on_failure_next_flow: What to do on failure ("pause" typically).
        pass_artifacts: Artifacts to pass back to the interrupted flow.
        description: Human-readable description.
        node_ids: Ordered list of node IDs in the flow.
        first_node_id: ID of the first node to execute.
    """

    flow_id: str
    flow_number: int
    injection_trigger: str
    on_complete_next_flow: str = "return"
    on_complete_reason: str = ""
    on_failure_next_flow: str = "pause"
    pass_artifacts: List[str] = field(default_factory=list)
    description: str = ""
    node_ids: List[str] = field(default_factory=list)
    first_node_id: str = ""


@dataclass
class TriggerDetectionResult:
    """Result of checking injection triggers.

    Attributes:
        triggered: Whether a trigger condition was detected.
        flow_id: ID of the utility flow to inject (if triggered).
        trigger_type: The type of trigger that fired.
        evidence: Evidence data supporting the trigger detection.
        priority: Priority of this trigger (higher = more urgent).
        reason: Human-readable reason for the trigger.
    """

    triggered: bool
    flow_id: Optional[str] = None
    trigger_type: Optional[str] = None
    evidence: Dict[str, Any] = field(default_factory=dict)
    priority: int = 50
    reason: str = ""


@dataclass
class FlowInjectionResult:
    """Result of injecting a utility flow.

    Attributes:
        injected: Whether injection succeeded.
        first_node_id: ID of the first node to execute.
        total_steps: Total number of steps in the utility flow.
        interruption_frame: The frame pushed to the interruption stack.
        error: Error message if injection failed.
    """

    injected: bool
    first_node_id: Optional[str] = None
    total_steps: int = 0
    interruption_frame: Optional[InterruptionFrame] = None
    error: Optional[str] = None


# =============================================================================
# Utility Flow Registry
# =============================================================================


class UtilityFlowRegistry:
    """Registry of utility flows loaded from pack specs.

    Loads and indexes utility flows (is_utility_flow=true) from the
    swarm/spec/flows/ directory. Provides lookup by trigger type.

    Usage:
        registry = UtilityFlowRegistry(repo_root)
        reset_flow = registry.get_by_trigger("upstream_diverged")
    """

    def __init__(self, repo_root: Path):
        """Initialize the registry.

        Args:
            repo_root: Repository root path.
        """
        self._repo_root = repo_root
        self._flows_by_id: Dict[str, UtilityFlowMetadata] = {}
        self._flows_by_trigger: Dict[str, List[UtilityFlowMetadata]] = {}
        self._loaded = False

    def load(self) -> None:
        """Load utility flows from pack specs.

        Scans swarm/spec/flows/*.graph.json for flows with
        is_utility_flow=true in metadata.
        """
        if self._loaded:
            return

        spec_dir = self._repo_root / "swarm" / "spec" / "flows"
        if not spec_dir.exists():
            logger.warning("Spec flows directory not found: %s", spec_dir)
            self._loaded = True
            return

        for spec_file in spec_dir.glob("*.graph.json"):
            try:
                self._load_flow_spec(spec_file)
            except Exception as e:
                logger.warning("Failed to load flow spec %s: %s", spec_file, e)

        self._loaded = True
        logger.info(
            "Loaded %d utility flows with %d unique triggers",
            len(self._flows_by_id),
            len(self._flows_by_trigger),
        )

    def _load_flow_spec(self, spec_file: Path) -> None:
        """Load a single flow spec file.

        Args:
            spec_file: Path to the *.graph.json file.
        """
        with open(spec_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Check if this is a utility flow
        metadata = data.get("metadata", {})
        if not metadata.get("is_utility_flow", False):
            return

        injection_trigger = metadata.get("injection_trigger")
        if not injection_trigger:
            logger.warning(
                "Utility flow %s missing injection_trigger, skipping",
                spec_file.name,
            )
            return

        # Extract flow metadata
        flow_id = data.get("id", spec_file.stem)
        flow_number = data.get("flow_number", 8)

        # Extract on_complete behavior
        on_complete = data.get("on_complete", {})
        on_complete_next_flow = on_complete.get("next_flow", "return")
        on_complete_reason = on_complete.get("reason", "")
        pass_artifacts = on_complete.get("pass_artifacts", [])

        # Extract on_failure behavior
        on_failure = data.get("on_failure", {})
        on_failure_next_flow = on_failure.get("next_flow", "pause")

        # Extract node ordering
        nodes = data.get("nodes", [])
        node_ids = [n.get("node_id") for n in nodes if n.get("node_id")]

        # Determine first node from edges or node order
        first_node_id = self._determine_first_node(nodes, data.get("edges", []))

        flow_meta = UtilityFlowMetadata(
            flow_id=flow_id,
            flow_number=flow_number,
            injection_trigger=injection_trigger,
            on_complete_next_flow=on_complete_next_flow,
            on_complete_reason=on_complete_reason,
            on_failure_next_flow=on_failure_next_flow,
            pass_artifacts=pass_artifacts,
            description=data.get("description", ""),
            node_ids=node_ids,
            first_node_id=first_node_id,
        )

        # Index by ID and trigger
        self._flows_by_id[flow_id] = flow_meta

        if injection_trigger not in self._flows_by_trigger:
            self._flows_by_trigger[injection_trigger] = []
        self._flows_by_trigger[injection_trigger].append(flow_meta)

        logger.debug(
            "Loaded utility flow %s with trigger '%s' (%d nodes)",
            flow_id,
            injection_trigger,
            len(node_ids),
        )

    def _determine_first_node(
        self,
        nodes: List[Dict[str, Any]],
        edges: List[Dict[str, Any]],
    ) -> str:
        """Determine the first node to execute.

        Uses topological sort based on edges, or falls back to first node.

        Args:
            nodes: List of node definitions.
            edges: List of edge definitions.

        Returns:
            Node ID of the first node.
        """
        if not nodes:
            return ""

        # Find nodes that have no incoming edges (entry points)
        all_node_ids = {n.get("node_id") for n in nodes if n.get("node_id")}
        nodes_with_incoming = {
            e.get("to") for e in edges if e.get("to") in all_node_ids
        }
        entry_nodes = all_node_ids - nodes_with_incoming

        if entry_nodes:
            # Return first entry node (alphabetically for determinism)
            return sorted(entry_nodes)[0]

        # Fall back to first node in definition order
        return nodes[0].get("node_id", "")

    def get_by_id(self, flow_id: str) -> Optional[UtilityFlowMetadata]:
        """Get utility flow by ID.

        Args:
            flow_id: The flow identifier.

        Returns:
            UtilityFlowMetadata if found, None otherwise.
        """
        self.load()
        return self._flows_by_id.get(flow_id)

    def get_by_trigger(self, trigger: str) -> Optional[UtilityFlowMetadata]:
        """Get utility flow by trigger type.

        If multiple flows have the same trigger, returns the first one
        (typically there should only be one per trigger).

        Args:
            trigger: The injection trigger type.

        Returns:
            UtilityFlowMetadata if found, None otherwise.
        """
        self.load()
        flows = self._flows_by_trigger.get(trigger, [])
        return flows[0] if flows else None

    def get_all_by_trigger(self, trigger: str) -> List[UtilityFlowMetadata]:
        """Get all utility flows for a trigger type.

        Args:
            trigger: The injection trigger type.

        Returns:
            List of matching utility flows (may be empty).
        """
        self.load()
        return list(self._flows_by_trigger.get(trigger, []))

    def list_triggers(self) -> List[str]:
        """List all known injection triggers.

        Returns:
            List of trigger type strings.
        """
        self.load()
        return list(self._flows_by_trigger.keys())

    def list_flows(self) -> List[UtilityFlowMetadata]:
        """List all utility flows.

        Returns:
            List of all UtilityFlowMetadata.
        """
        self.load()
        return list(self._flows_by_id.values())


# =============================================================================
# Injection Trigger Detection
# =============================================================================


class InjectionTriggerDetector:
    """Detects when injection triggers fire based on execution context.

    Analyzes step results, git status, and verification results to
    determine if a utility flow should be injected.

    Usage:
        detector = InjectionTriggerDetector(registry)
        result = detector.check_triggers(step_result, run_state, git_status)
        if result.triggered:
            # Inject the utility flow
            injector.inject_utility_flow(result.flow_id, ...)
    """

    def __init__(
        self,
        registry: UtilityFlowRegistry,
        custom_detectors: Optional[Dict[str, Callable]] = None,
    ):
        """Initialize the detector.

        Args:
            registry: UtilityFlowRegistry for looking up flows.
            custom_detectors: Optional dict of custom detector functions.
                Each detector is (context) -> TriggerDetectionResult.
        """
        self._registry = registry
        self._custom_detectors = custom_detectors or {}

        # Built-in trigger detectors
        self._detectors: Dict[str, Callable] = {
            InjectionTrigger.UPSTREAM_DIVERGED: self._detect_upstream_diverged,
            InjectionTrigger.LINT_FAILURE: self._detect_lint_failure,
            InjectionTrigger.SECURITY_CONCERN: self._detect_security_concern,
            InjectionTrigger.CONFLICT_DETECTED: self._detect_conflict,
            InjectionTrigger.TEST_FLAKE: self._detect_test_flake,
            InjectionTrigger.ENV_SETUP_FAILURE: self._detect_env_setup_failure,
        }

        # Merge custom detectors
        self._detectors.update(self._custom_detectors)

    def check_triggers(
        self,
        step_result: Dict[str, Any],
        run_state: RunState,
        git_status: Optional[Dict[str, Any]] = None,
        verification_result: Optional[Dict[str, Any]] = None,
        file_changes: Optional[Dict[str, Any]] = None,
    ) -> TriggerDetectionResult:
        """Check all injection triggers against current context.

        Evaluates each known trigger type against the step execution
        context and returns the highest-priority triggered result.

        Args:
            step_result: Result from step execution.
            run_state: Current run state.
            git_status: Optional git status information.
            verification_result: Optional verification check results.
            file_changes: Optional file changes from diff scanner.

        Returns:
            TriggerDetectionResult (triggered=False if no triggers fire).
        """
        # Build detection context
        context = {
            "step_result": step_result,
            "run_state": run_state,
            "git_status": git_status or {},
            "verification_result": verification_result or {},
            "file_changes": file_changes or {},
        }

        # Check each trigger type
        results: List[TriggerDetectionResult] = []

        for trigger_type, detector_fn in self._detectors.items():
            # Only check triggers that have registered utility flows
            if not self._registry.get_by_trigger(trigger_type):
                continue

            try:
                result = detector_fn(context)
                if result.triggered:
                    results.append(result)
            except Exception as e:
                logger.warning(
                    "Trigger detector for '%s' failed: %s",
                    trigger_type,
                    e,
                )

        # Return highest-priority result
        if results:
            results.sort(key=lambda r: -r.priority)
            return results[0]

        return TriggerDetectionResult(triggered=False)

    def check_specific_trigger(
        self,
        trigger_type: str,
        context: Dict[str, Any],
    ) -> TriggerDetectionResult:
        """Check a specific trigger type.

        Args:
            trigger_type: The trigger type to check.
            context: Detection context dict.

        Returns:
            TriggerDetectionResult for this trigger.
        """
        detector_fn = self._detectors.get(trigger_type)
        if not detector_fn:
            return TriggerDetectionResult(
                triggered=False,
                reason=f"No detector for trigger type: {trigger_type}",
            )

        try:
            return detector_fn(context)
        except Exception as e:
            logger.warning("Trigger detector failed: %s", e)
            return TriggerDetectionResult(triggered=False, reason=str(e))

    # -------------------------------------------------------------------------
    # Built-in Trigger Detectors
    # -------------------------------------------------------------------------

    def _detect_upstream_diverged(
        self,
        context: Dict[str, Any],
    ) -> TriggerDetectionResult:
        """Detect if work branch has diverged from upstream.

        Checks:
        - git_status.behind_count > 0
        - git_status.diverged = True
        - Step output mentioning "diverged" or "out of sync"
        """
        git_status = context.get("git_status", {})

        # Check git status fields
        behind_count = git_status.get("behind_count", 0)
        diverged = git_status.get("diverged", False)

        if diverged or behind_count > 0:
            flow = self._registry.get_by_trigger(InjectionTrigger.UPSTREAM_DIVERGED)
            return TriggerDetectionResult(
                triggered=True,
                flow_id=flow.flow_id if flow else None,
                trigger_type=InjectionTrigger.UPSTREAM_DIVERGED,
                evidence={
                    "behind_count": behind_count,
                    "diverged": diverged,
                },
                priority=80,  # High priority - sync before continuing
                reason=f"Branch diverged from upstream (behind by {behind_count} commits)",
            )

        # Check step output for divergence signals
        step_result = context.get("step_result", {})
        output = step_result.get("output", "")
        if isinstance(output, str):
            output_lower = output.lower()
            if "diverged" in output_lower or "out of sync" in output_lower:
                flow = self._registry.get_by_trigger(InjectionTrigger.UPSTREAM_DIVERGED)
                return TriggerDetectionResult(
                    triggered=True,
                    flow_id=flow.flow_id if flow else None,
                    trigger_type=InjectionTrigger.UPSTREAM_DIVERGED,
                    evidence={"output_signal": True},
                    priority=75,
                    reason="Step output indicates branch divergence",
                )

        return TriggerDetectionResult(triggered=False)

    def _detect_lint_failure(
        self,
        context: Dict[str, Any],
    ) -> TriggerDetectionResult:
        """Detect lint/format failures that can be auto-fixed.

        Checks:
        - verification_result with lint failures
        - Step output mentioning lint/format errors
        """
        verification = context.get("verification_result", {})

        # Check verification checks for lint failures
        checks = verification.get("checks", [])
        lint_failures = [
            c
            for c in checks
            if not c.get("passed", True)
            and any(
                keyword in c.get("name", "").lower()
                for keyword in ["lint", "format", "style", "eslint", "prettier", "black", "ruff"]
            )
        ]

        if lint_failures:
            flow = self._registry.get_by_trigger(InjectionTrigger.LINT_FAILURE)
            return TriggerDetectionResult(
                triggered=True,
                flow_id=flow.flow_id if flow else None,
                trigger_type=InjectionTrigger.LINT_FAILURE,
                evidence={
                    "failed_checks": [c.get("name") for c in lint_failures],
                },
                priority=60,  # Medium-high - auto-fixable
                reason=f"Lint failures detected: {len(lint_failures)} check(s)",
            )

        return TriggerDetectionResult(triggered=False)

    def _detect_security_concern(
        self,
        context: Dict[str, Any],
    ) -> TriggerDetectionResult:
        """Detect security concerns requiring review.

        Checks:
        - verification_result with security failures
        - File changes touching sensitive paths
        """
        verification = context.get("verification_result", {})
        file_changes = context.get("file_changes", {})

        # Check for security check failures
        checks = verification.get("checks", [])
        security_failures = [
            c
            for c in checks
            if not c.get("passed", True)
            and any(
                keyword in c.get("name", "").lower()
                for keyword in ["security", "vuln", "cve", "audit", "secret"]
            )
        ]

        if security_failures:
            flow = self._registry.get_by_trigger(InjectionTrigger.SECURITY_CONCERN)
            return TriggerDetectionResult(
                triggered=True,
                flow_id=flow.flow_id if flow else None,
                trigger_type=InjectionTrigger.SECURITY_CONCERN,
                evidence={
                    "failed_checks": [c.get("name") for c in security_failures],
                },
                priority=90,  # Very high - security is critical
                reason="Security check failures detected",
            )

        # Check for sensitive file changes
        sensitive_patterns = ["secret", "credential", "auth", "password", "key", ".env"]
        all_files = (
            file_changes.get("modified", [])
            + file_changes.get("added", [])
            + file_changes.get("deleted", [])
        )
        sensitive_files = [
            f
            for f in all_files
            if any(p in f.lower() for p in sensitive_patterns)
        ]

        if sensitive_files:
            flow = self._registry.get_by_trigger(InjectionTrigger.SECURITY_CONCERN)
            return TriggerDetectionResult(
                triggered=True,
                flow_id=flow.flow_id if flow else None,
                trigger_type=InjectionTrigger.SECURITY_CONCERN,
                evidence={"sensitive_files": sensitive_files},
                priority=85,
                reason=f"Sensitive files modified: {len(sensitive_files)}",
            )

        return TriggerDetectionResult(triggered=False)

    def _detect_conflict(
        self,
        context: Dict[str, Any],
    ) -> TriggerDetectionResult:
        """Detect merge/rebase conflicts.

        Checks:
        - git_status.has_conflicts
        - Step output mentioning conflicts
        """
        git_status = context.get("git_status", {})

        if git_status.get("has_conflicts", False):
            flow = self._registry.get_by_trigger(InjectionTrigger.CONFLICT_DETECTED)
            return TriggerDetectionResult(
                triggered=True,
                flow_id=flow.flow_id if flow else None,
                trigger_type=InjectionTrigger.CONFLICT_DETECTED,
                evidence={"git_conflicts": True},
                priority=85,
                reason="Git conflicts detected",
            )

        # Check step output
        step_result = context.get("step_result", {})
        output = step_result.get("output", "")
        if isinstance(output, str) and "conflict" in output.lower():
            flow = self._registry.get_by_trigger(InjectionTrigger.CONFLICT_DETECTED)
            return TriggerDetectionResult(
                triggered=True,
                flow_id=flow.flow_id if flow else None,
                trigger_type=InjectionTrigger.CONFLICT_DETECTED,
                evidence={"output_signal": True},
                priority=80,
                reason="Step output indicates conflicts",
            )

        return TriggerDetectionResult(triggered=False)

    def _detect_test_flake(
        self,
        context: Dict[str, Any],
    ) -> TriggerDetectionResult:
        """Detect flaky test failures.

        Checks:
        - verification_result with test failures marked as flaky
        - Repeated test failures with same test name
        """
        verification = context.get("verification_result", {})
        run_state: RunState = context.get("run_state")

        # Check for flaky test markers
        checks = verification.get("checks", [])
        flaky_tests = [
            c
            for c in checks
            if not c.get("passed", True) and c.get("flaky", False)
        ]

        if flaky_tests:
            flow = self._registry.get_by_trigger(InjectionTrigger.TEST_FLAKE)
            return TriggerDetectionResult(
                triggered=True,
                flow_id=flow.flow_id if flow else None,
                trigger_type=InjectionTrigger.TEST_FLAKE,
                evidence={"flaky_tests": [c.get("name") for c in flaky_tests]},
                priority=50,  # Medium - flakes should be investigated
                reason=f"Flaky test failures: {len(flaky_tests)}",
            )

        return TriggerDetectionResult(triggered=False)

    def _detect_env_setup_failure(
        self,
        context: Dict[str, Any],
    ) -> TriggerDetectionResult:
        """Detect environment setup failures.

        Checks:
        - Step output mentioning env/setup failures
        - Verification failures for setup steps
        """
        step_result = context.get("step_result", {})
        output = step_result.get("output", "")

        if isinstance(output, str):
            output_lower = output.lower()
            env_signals = [
                "environment setup failed",
                "dependency install failed",
                "missing dependency",
                "pip install failed",
                "npm install failed",
                "cargo build failed",
            ]
            for signal in env_signals:
                if signal in output_lower:
                    flow = self._registry.get_by_trigger(InjectionTrigger.ENV_SETUP_FAILURE)
                    return TriggerDetectionResult(
                        triggered=True,
                        flow_id=flow.flow_id if flow else None,
                        trigger_type=InjectionTrigger.ENV_SETUP_FAILURE,
                        evidence={"signal": signal},
                        priority=70,
                        reason=f"Environment setup failure: {signal}",
                    )

        return TriggerDetectionResult(triggered=False)


# =============================================================================
# Utility Flow Injector
# =============================================================================


class UtilityFlowInjector:
    """Injects utility flows using the interruption stack pattern.

    Implements the stack-frame execution model where:
    1. Current flow context is pushed to the interruption stack
    2. Utility flow nodes are injected and executed
    3. On utility flow completion, stack is popped and original flow resumes

    The "return" semantics (on_complete.next_flow: "return") are handled
    by checking the interruption stack during routing.

    Usage:
        injector = UtilityFlowInjector(registry)
        result = injector.inject_utility_flow(
            flow_id="reset-flow",
            run_state=run_state,
            current_node="build-step-3",
        )
        if result.injected:
            # Execute result.first_node_id next
            ...
    """

    # Maximum nested utility flow depth
    MAX_UTILITY_FLOW_DEPTH = 5

    def __init__(self, registry: UtilityFlowRegistry):
        """Initialize the injector.

        Args:
            registry: UtilityFlowRegistry for looking up flow metadata.
        """
        self._registry = registry

    def inject_utility_flow(
        self,
        flow_id: str,
        run_state: RunState,
        current_node: str,
        injection_reason: str = "",
        injection_evidence: Optional[Dict[str, Any]] = None,
    ) -> FlowInjectionResult:
        """Inject a utility flow for execution.

        Pushes the current context onto the interruption stack and
        registers the utility flow's nodes for execution.

        Args:
            flow_id: ID of the utility flow to inject.
            run_state: RunState to modify.
            current_node: Current node (for resume point).
            injection_reason: Reason for the injection.
            injection_evidence: Evidence supporting the injection.

        Returns:
            FlowInjectionResult with injection status and first node ID.
        """
        # Load flow metadata
        flow_meta = self._registry.get_by_id(flow_id)
        if flow_meta is None:
            return FlowInjectionResult(
                injected=False,
                error=f"Unknown utility flow: {flow_id}",
            )

        # Check depth limit
        current_depth = run_state.get_interruption_depth()
        if current_depth >= self.MAX_UTILITY_FLOW_DEPTH:
            logger.warning(
                "MAX_UTILITY_FLOW_DEPTH (%d) reached, rejecting injection of '%s'. "
                "Current depth: %d",
                self.MAX_UTILITY_FLOW_DEPTH,
                flow_id,
                current_depth,
            )
            return FlowInjectionResult(
                injected=False,
                error=f"Max utility flow depth ({self.MAX_UTILITY_FLOW_DEPTH}) exceeded",
            )

        # Validate we have nodes to inject
        if not flow_meta.node_ids or not flow_meta.first_node_id:
            return FlowInjectionResult(
                injected=False,
                error=f"Utility flow {flow_id} has no nodes defined",
            )

        total_steps = len(flow_meta.node_ids)

        # Push resume point (where to continue after utility flow completes)
        run_state.push_resume(
            current_node,
            {
                "utility_flow_id": flow_id,
                "injection_reason": injection_reason,
            },
        )

        # Push interruption frame with utility flow tracking
        run_state.push_interruption(
            reason=f"Utility flow: {flow_meta.description or flow_id}",
            return_node=current_node,
            context_snapshot={
                "utility_flow_id": flow_id,
                "injection_reason": injection_reason,
                "injection_evidence": injection_evidence or {},
                "on_complete_next_flow": flow_meta.on_complete_next_flow,
                "pass_artifacts": flow_meta.pass_artifacts,
            },
            current_step_index=0,
            total_steps=total_steps,
            sidequest_id=flow_id,  # Reuse sidequest_id field for utility flow ID
        )

        # Inject node specs for ALL nodes in the utility flow
        first_node_id = None
        for i, node_id in enumerate(flow_meta.node_ids):
            # Create unique injected node ID
            injected_node_id = f"uf-{flow_id}-{node_id}"

            # Create full execution spec
            spec = InjectedNodeSpec(
                node_id=injected_node_id,
                station_id=node_id,  # Use node_id as station_id
                template_id=None,
                agent_key=node_id,
                role=f"Utility flow {flow_id} step {i + 1}/{total_steps}: {node_id}",
                params={
                    "utility_flow_id": flow_id,
                    "original_node_id": node_id,
                    "step_index": i,
                },
                sidequest_origin=flow_id,
                sequence_index=i,
                total_in_sequence=total_steps,
            )

            # Register the spec
            run_state.register_injected_node(spec)

            if i == 0:
                first_node_id = injected_node_id

        logger.info(
            "Utility flow injected: %s (%d steps, first=%s, resume_at=%s)",
            flow_id,
            total_steps,
            first_node_id,
            current_node,
        )

        # Get the interruption frame we just pushed
        interruption_frame = run_state.peek_interruption()

        return FlowInjectionResult(
            injected=True,
            first_node_id=first_node_id,
            total_steps=total_steps,
            interruption_frame=interruption_frame,
        )

    def check_utility_flow_completion(
        self,
        run_state: RunState,
    ) -> Optional[str]:
        """Check if a utility flow has completed and return resume node.

        Implements "return" semantics - when a utility flow with
        on_complete.next_flow="return" completes, this returns the
        node to resume at from the interruption stack.

        Args:
            run_state: Current run state.

        Returns:
            Node ID to resume at, or None if no utility flow completion.
        """
        if not run_state.is_interrupted():
            return None

        top_frame = run_state.peek_interruption()
        if top_frame is None:
            return None

        # Check if this is a utility flow frame
        context = top_frame.context_snapshot or {}
        utility_flow_id = context.get("utility_flow_id")
        if not utility_flow_id:
            return None

        # Check if all steps are complete
        current_step_index = top_frame.current_step_index
        total_steps = top_frame.total_steps

        if current_step_index < total_steps - 1:
            # More steps remain - advance to next utility flow step
            next_step_index = current_step_index + 1

            # Find the next node ID from the flow metadata
            flow_meta = self._registry.get_by_id(utility_flow_id)
            if flow_meta and next_step_index < len(flow_meta.node_ids):
                next_node_id = f"uf-{utility_flow_id}-{flow_meta.node_ids[next_step_index]}"

                # Update frame step index
                top_frame.current_step_index = next_step_index

                logger.info(
                    "Utility flow %s advancing to step %d/%d: %s",
                    utility_flow_id,
                    next_step_index + 1,
                    total_steps,
                    next_node_id,
                )
                return next_node_id

        # Utility flow complete - check on_complete behavior
        on_complete_next_flow = context.get("on_complete_next_flow", "return")

        if on_complete_next_flow == "return":
            # Pop the interruption and resume stacks
            resume_point = run_state.pop_resume()
            run_state.pop_interruption()

            if resume_point:
                logger.info(
                    "Utility flow %s complete, returning to: %s",
                    utility_flow_id,
                    resume_point.node_id,
                )
                return resume_point.node_id

            return top_frame.return_node

        elif on_complete_next_flow == "pause":
            # Pause for human intervention
            logger.info(
                "Utility flow %s complete, pausing for human intervention",
                utility_flow_id,
            )
            return None

        else:
            # Specific flow to continue to
            logger.info(
                "Utility flow %s complete, continuing to flow: %s",
                utility_flow_id,
                on_complete_next_flow,
            )
            # Pop stacks but don't return to original - let caller handle flow transition
            run_state.pop_resume()
            run_state.pop_interruption()
            return None


# =============================================================================
# Convenience Functions
# =============================================================================


def detect_injection_triggers(
    step_result: Dict[str, Any],
    run_state: RunState,
    repo_root: Path,
    git_status: Optional[Dict[str, Any]] = None,
    verification_result: Optional[Dict[str, Any]] = None,
    file_changes: Optional[Dict[str, Any]] = None,
) -> TriggerDetectionResult:
    """Convenience function to detect injection triggers.

    Creates a registry and detector, then checks all triggers.

    Args:
        step_result: Result from step execution.
        run_state: Current run state.
        repo_root: Repository root path.
        git_status: Optional git status information.
        verification_result: Optional verification check results.
        file_changes: Optional file changes from diff scanner.

    Returns:
        TriggerDetectionResult.
    """
    registry = UtilityFlowRegistry(repo_root)
    detector = InjectionTriggerDetector(registry)
    return detector.check_triggers(
        step_result=step_result,
        run_state=run_state,
        git_status=git_status,
        verification_result=verification_result,
        file_changes=file_changes,
    )


def create_injection_components(
    repo_root: Path,
) -> tuple[UtilityFlowRegistry, InjectionTriggerDetector, UtilityFlowInjector]:
    """Create all injection detection/execution components.

    Args:
        repo_root: Repository root path.

    Returns:
        Tuple of (registry, detector, injector).
    """
    registry = UtilityFlowRegistry(repo_root)
    detector = InjectionTriggerDetector(registry)
    injector = UtilityFlowInjector(registry)
    return registry, detector, injector


__all__ = [
    # Trigger types
    "InjectionTrigger",
    # Data classes
    "UtilityFlowMetadata",
    "TriggerDetectionResult",
    "FlowInjectionResult",
    # Main classes
    "UtilityFlowRegistry",
    "InjectionTriggerDetector",
    "UtilityFlowInjector",
    # Convenience functions
    "detect_injection_triggers",
    "create_injection_components",
]
