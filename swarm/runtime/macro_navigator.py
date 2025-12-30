"""
macro_navigator.py - Between-Flow Routing Decisions

This module implements the MacroNavigator for making intelligent routing
decisions BETWEEN flows, complementing the within-flow micro-navigation
handled by Navigator.

The MacroNavigator:
- Evaluates flow outcomes to determine next flow
- Applies routing rules (bounces, retries, skips)
- Enforces constraints (e.g., "never deploy unless gate verified")
- Tracks flow execution history for loop detection

Design Philosophy:
    - Traditional tooling handles flow execution
    - MacroNavigator receives flow results and run state
    - Makes routing decisions based on policy rules
    - Respects hard constraints even when rules suggest otherwise

Usage:
    from swarm.runtime.macro_navigator import (
        MacroNavigator,
        extract_flow_result,
        ConstraintEvaluator,
    )

    # Initialize with run plan
    navigator = MacroNavigator(run_plan)

    # After each flow completes, get routing decision
    flow_result = extract_flow_result(flow_key, run_state, artifacts_path)
    decision = navigator.route_after_flow(
        completed_flow=flow_key,
        flow_result=flow_result,
        run_state=run_state,
    )

    # Apply the decision
    if decision.action == MacroAction.ADVANCE:
        next_flow = decision.next_flow
    elif decision.action == MacroAction.GOTO:
        next_flow = decision.next_flow  # Non-sequential jump
    elif decision.action == MacroAction.REPEAT:
        next_flow = completed_flow  # Re-run same flow
    elif decision.action == MacroAction.PAUSE:
        # Wait for human intervention
        ...
    elif decision.action == MacroAction.TERMINATE:
        # End the run
        ...

Constraint DSL:
    The module supports a simple constraint DSL with these patterns:

    1. "never {action} unless {condition}"
       Example: "never deploy unless gate verdict is MERGE"

    2. "max {N} {action_type}"
       Example: "max 3 bounces from gate to build"

    3. "require {action} after {flow}"
       Example: "require human approval after flow 4"
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from swarm.runtime.types import (
    FlowOutcome,
    FlowResult,
    GateVerdict,
    HumanPolicy,
    MacroAction,
    MacroPolicy,
    MacroRoutingDecision,
    RunPlanSpec,
    RunState,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Constraint Types and Evaluator
# =============================================================================


class ConstraintType(str, Enum):
    """Types of constraints supported by the DSL."""

    NEVER_UNLESS = "never_unless"  # "never {action} unless {condition}"
    MAX_COUNT = "max_count"  # "max {N} {action_type}"
    REQUIRE_AFTER = "require_after"  # "require {action} after {flow}"


@dataclass
class ParsedConstraint:
    """A parsed constraint ready for evaluation.

    Attributes:
        constraint_type: The type of constraint.
        raw_text: The original constraint string.
        action: The action being constrained (e.g., "deploy", "bounces").
        condition: The condition that must be met (for NEVER_UNLESS).
        count: The maximum count (for MAX_COUNT).
        source_flow: The source flow for tracking (for MAX_COUNT bounces).
        target_flow: The target flow for tracking (for MAX_COUNT bounces).
        trigger_flow: The flow after which action is required (for REQUIRE_AFTER).
    """

    constraint_type: ConstraintType
    raw_text: str
    action: str = ""
    condition: str = ""
    count: int = 0
    source_flow: Optional[str] = None
    target_flow: Optional[str] = None
    trigger_flow: Optional[str] = None


@dataclass
class ConstraintViolation:
    """Details of a constraint violation.

    Attributes:
        constraint: The constraint that was violated.
        message: Human-readable violation message.
        context: Additional context about the violation.
        suggested_action: The suggested MacroAction to take.
    """

    constraint: ParsedConstraint
    message: str
    context: Dict[str, Any] = field(default_factory=dict)
    suggested_action: MacroAction = MacroAction.PAUSE


@dataclass
class ConstraintContext:
    """Context for constraint evaluation.

    This provides all the information needed to evaluate constraints
    against the current state of the run.

    Attributes:
        completed_flow: The flow that just completed.
        flow_result: Result of the completed flow.
        next_flow: The proposed next flow (from routing rules).
        flow_execution_counts: Counts of how many times each flow has run.
        routing_history: History of routing decisions.
        bounce_counts: Counts of bounces between flow pairs.
    """

    completed_flow: str
    flow_result: FlowResult
    next_flow: Optional[str] = None
    flow_execution_counts: Dict[str, int] = field(default_factory=dict)
    routing_history: List[Dict[str, Any]] = field(default_factory=list)
    bounce_counts: Dict[str, int] = field(default_factory=dict)


class ConstraintEvaluator:
    """Evaluates constraints against run context.

    The ConstraintEvaluator parses constraint strings into structured
    ParsedConstraint objects and evaluates them against the current
    run context to detect violations.

    Supported constraint patterns:

    1. "never {action} unless {condition}"
       - "never deploy unless gate verdict is MERGE"
       - "never deploy unless gate verdict is MERGE or MERGE_WITH_CONDITIONS"
       - "never skip gate flow"

    2. "max {N} {action_type}"
       - "max 3 bounces from gate to build"
       - "max 2 bounces between gate and build"
       - "max 1 bounces from gate to plan"

    3. "require {action} after {flow}"
       - "require human approval after gate"
       - "require human approval after flow 4"

    Example:
        evaluator = ConstraintEvaluator()

        # Parse constraints from run plan
        constraints = [
            evaluator.parse_constraint(c)
            for c in run_plan.constraints
        ]

        # Check for violations
        context = ConstraintContext(
            completed_flow="gate",
            flow_result=flow_result,
            next_flow="deploy",
        )

        for constraint in constraints:
            is_valid, violation = evaluator.evaluate(constraint, context)
            if not is_valid:
                print(violation.message)
    """

    # Regex patterns for constraint parsing
    NEVER_UNLESS_PATTERN = re.compile(
        r"^never\s+(?P<action>\w+(?:\s+\w+)*)\s+unless\s+(?P<condition>.+)$",
        re.IGNORECASE,
    )
    # Pattern for "never {action}" without unless (absolute prohibition)
    NEVER_ALWAYS_PATTERN = re.compile(
        r"^never\s+(?P<action>\w+(?:\s+\w+)*)$",
        re.IGNORECASE,
    )
    MAX_COUNT_PATTERN = re.compile(
        r"^max\s+(?P<count>\d+)\s+(?P<action>\w+)\s+"
        r"(?:from\s+(?P<source>\w+)\s+to\s+(?P<target>\w+)|"
        r"between\s+(?P<flow1>\w+)\s+and\s+(?P<flow2>\w+))$",
        re.IGNORECASE,
    )
    REQUIRE_AFTER_PATTERN = re.compile(
        r"^require\s+(?P<action>.+?)\s+after\s+(?P<flow>flow\s*\d+|\w+)$",
        re.IGNORECASE,
    )

    # Flow name normalization (support "flow 4" -> "gate")
    FLOW_NUMBER_MAP = {
        "1": "signal",
        "2": "plan",
        "3": "build",
        "4": "gate",
        "5": "deploy",
        "6": "wisdom",
    }

    def parse_constraint(self, constraint_str: str) -> ParsedConstraint:
        """Parse a constraint string into a structured ParsedConstraint.

        Args:
            constraint_str: The constraint string to parse.

        Returns:
            ParsedConstraint ready for evaluation.

        Raises:
            ValueError: If the constraint string cannot be parsed.
        """
        constraint_str = constraint_str.strip()

        # Try "never ... unless ..." pattern
        match = self.NEVER_UNLESS_PATTERN.match(constraint_str)
        if match:
            return ParsedConstraint(
                constraint_type=ConstraintType.NEVER_UNLESS,
                raw_text=constraint_str,
                action=match.group("action").lower(),
                condition=match.group("condition"),
            )

        # Try "never ..." pattern without unless (absolute prohibition)
        match = self.NEVER_ALWAYS_PATTERN.match(constraint_str)
        if match:
            return ParsedConstraint(
                constraint_type=ConstraintType.NEVER_UNLESS,
                raw_text=constraint_str,
                action=match.group("action").lower(),
                condition="",  # Empty condition = never allowed
            )

        # Try "max N ..." pattern
        match = self.MAX_COUNT_PATTERN.match(constraint_str)
        if match:
            source = match.group("source") or match.group("flow1")
            target = match.group("target") or match.group("flow2")
            return ParsedConstraint(
                constraint_type=ConstraintType.MAX_COUNT,
                raw_text=constraint_str,
                action=match.group("action").lower(),
                count=int(match.group("count")),
                source_flow=self._normalize_flow_name(source) if source else None,
                target_flow=self._normalize_flow_name(target) if target else None,
            )

        # Try "require ... after ..." pattern
        match = self.REQUIRE_AFTER_PATTERN.match(constraint_str)
        if match:
            trigger = match.group("flow")
            return ParsedConstraint(
                constraint_type=ConstraintType.REQUIRE_AFTER,
                raw_text=constraint_str,
                action=match.group("action").lower(),
                trigger_flow=self._normalize_flow_name(trigger),
            )

        # If no pattern matches, raise an error
        raise ValueError(f"Cannot parse constraint: {constraint_str!r}")

    def _normalize_flow_name(self, flow_ref: str) -> str:
        """Normalize a flow reference to a flow key.

        Args:
            flow_ref: A flow reference like "gate", "flow 4", "4".

        Returns:
            Normalized flow key (e.g., "gate").
        """
        flow_ref = flow_ref.strip().lower()

        # Handle "flow N" format
        if flow_ref.startswith("flow"):
            num = flow_ref.replace("flow", "").strip()
            return self.FLOW_NUMBER_MAP.get(num, flow_ref)

        # Handle bare number
        if flow_ref.isdigit():
            return self.FLOW_NUMBER_MAP.get(flow_ref, flow_ref)

        return flow_ref

    def evaluate(
        self,
        constraint: ParsedConstraint,
        context: ConstraintContext,
    ) -> Tuple[bool, Optional[ConstraintViolation]]:
        """Evaluate a constraint against the current context.

        Args:
            constraint: The parsed constraint to evaluate.
            context: The current run context.

        Returns:
            Tuple of (is_valid, violation). If is_valid is True,
            violation will be None.
        """
        if constraint.constraint_type == ConstraintType.NEVER_UNLESS:
            return self._evaluate_never_unless(constraint, context)
        elif constraint.constraint_type == ConstraintType.MAX_COUNT:
            return self._evaluate_max_count(constraint, context)
        elif constraint.constraint_type == ConstraintType.REQUIRE_AFTER:
            return self._evaluate_require_after(constraint, context)
        else:
            # Unknown constraint type - log warning and pass
            logger.warning("Unknown constraint type: %s", constraint.constraint_type)
            return True, None

    def _evaluate_never_unless(
        self,
        constraint: ParsedConstraint,
        context: ConstraintContext,
    ) -> Tuple[bool, Optional[ConstraintViolation]]:
        """Evaluate a 'never ... unless ...' constraint.

        Examples:
        - "never deploy unless gate verdict is MERGE"
        - "never skip gate flow"
        """
        action = constraint.action
        condition = constraint.condition

        # Check if the action is relevant to the current routing decision
        if action == "deploy":
            # Only relevant if we're about to advance to deploy
            if context.next_flow != "deploy":
                return True, None

            # Parse the condition
            return self._check_gate_condition(constraint, condition, context)

        elif action == "skip gate flow" or action == "skip gate":
            # Check if we're skipping gate
            if context.completed_flow == "build" and context.next_flow == "deploy":
                # We're skipping gate!
                return False, ConstraintViolation(
                    constraint=constraint,
                    message="Cannot skip gate flow - gate is required before deploy",
                    context={
                        "completed_flow": context.completed_flow,
                        "next_flow": context.next_flow,
                    },
                    suggested_action=MacroAction.TERMINATE,
                )
            return True, None

        # Default: constraint doesn't apply to current context
        return True, None

    def _check_gate_condition(
        self,
        constraint: ParsedConstraint,
        condition: str,
        context: ConstraintContext,
    ) -> Tuple[bool, Optional[ConstraintViolation]]:
        """Check a gate-related condition.

        Supports conditions like:
        - "gate verdict is MERGE"
        - "gate verdict is MERGE or MERGE_WITH_CONDITIONS"
        """
        condition_lower = condition.lower()

        # Parse condition for gate verdict
        if "gate verdict" in condition_lower:
            flow_result = context.flow_result
            gate_verdict = flow_result.gate_verdict

            # Extract allowed verdicts from condition
            allowed_verdicts = self._extract_allowed_verdicts(condition)

            if gate_verdict is None:
                # No gate verdict available
                return False, ConstraintViolation(
                    constraint=constraint,
                    message="Cannot deploy: no gate verdict available",
                    context={"gate_verdict": None},
                    suggested_action=MacroAction.PAUSE,
                )

            if gate_verdict not in allowed_verdicts:
                return False, ConstraintViolation(
                    constraint=constraint,
                    message=(
                        f"Cannot deploy: gate verdict is {gate_verdict.value}, "
                        f"but must be one of {[v.value for v in allowed_verdicts]}"
                    ),
                    context={
                        "gate_verdict": gate_verdict.value,
                        "allowed_verdicts": [v.value for v in allowed_verdicts],
                    },
                    suggested_action=MacroAction.TERMINATE,
                )

            return True, None

        # Unknown condition format
        logger.warning("Unknown condition format in constraint: %s", condition)
        return True, None

    def _extract_allowed_verdicts(self, condition: str) -> List[GateVerdict]:
        """Extract allowed verdicts from a condition string."""
        allowed = []
        condition_upper = condition.upper()

        for verdict in GateVerdict:
            if verdict.value in condition_upper:
                allowed.append(verdict)

        return allowed if allowed else [GateVerdict.MERGE]

    def _evaluate_max_count(
        self,
        constraint: ParsedConstraint,
        context: ConstraintContext,
    ) -> Tuple[bool, Optional[ConstraintViolation]]:
        """Evaluate a 'max N ...' constraint.

        Examples:
        - "max 3 bounces from gate to build"
        - "max 2 bounces between gate and build"
        """
        action = constraint.action
        max_count = constraint.count
        source = constraint.source_flow
        target = constraint.target_flow

        if action == "bounces" and source and target:
            # Count bounces between source and target flows
            bounce_key = f"{source}->{target}"
            alt_key = f"{target}->{source}"

            current_count = context.bounce_counts.get(bounce_key, 0) + context.bounce_counts.get(
                alt_key, 0
            )

            if current_count >= max_count:
                return False, ConstraintViolation(
                    constraint=constraint,
                    message=(
                        f"Exceeded maximum bounces ({max_count}) between "
                        f"{source} and {target}. Current count: {current_count}"
                    ),
                    context={
                        "source_flow": source,
                        "target_flow": target,
                        "max_count": max_count,
                        "current_count": current_count,
                    },
                    suggested_action=MacroAction.TERMINATE,
                )

            return True, None

        # Unknown action type
        logger.warning("Unknown max count action: %s", action)
        return True, None

    def _evaluate_require_after(
        self,
        constraint: ParsedConstraint,
        context: ConstraintContext,
    ) -> Tuple[bool, Optional[ConstraintViolation]]:
        """Evaluate a 'require ... after ...' constraint.

        Examples:
        - "require human approval after gate"
        - "require human approval after flow 4"
        """
        action = constraint.action
        trigger_flow = constraint.trigger_flow

        # Only relevant if we just completed the trigger flow
        if context.completed_flow != trigger_flow:
            return True, None

        if "human approval" in action:
            # Signal that human approval is required
            return False, ConstraintViolation(
                constraint=constraint,
                message=f"Human approval required after {trigger_flow}",
                context={
                    "trigger_flow": trigger_flow,
                    "action_required": action,
                },
                suggested_action=MacroAction.PAUSE,
            )

        # Unknown required action
        logger.warning("Unknown required action: %s", action)
        return True, None

    def get_violation_message(self, violation: ConstraintViolation) -> str:
        """Get a human-readable violation message.

        Args:
            violation: The constraint violation.

        Returns:
            Human-readable message describing the violation.
        """
        parts = [violation.message]

        if violation.context:
            details = []
            for key, value in violation.context.items():
                details.append(f"  {key}: {value}")
            if details:
                parts.append("Details:")
                parts.extend(details)

        parts.append(f"Constraint: {violation.constraint.raw_text}")
        parts.append(f"Suggested action: {violation.suggested_action.value}")

        return "\n".join(parts)


# =============================================================================
# Flow Result Extraction
# =============================================================================


def extract_flow_result(
    flow_key: str,
    run_state: RunState,
    artifacts_base: Optional[Path] = None,
) -> FlowResult:
    """Extract FlowResult from run state and artifacts.

    This function examines the completed flow's state and artifacts
    to produce a structured FlowResult for routing decisions.

    Args:
        flow_key: The flow that completed.
        run_state: Current run state with handoff envelopes.
        artifacts_base: Optional path to flow artifacts.

    Returns:
        FlowResult with outcome, status, and relevant details.
    """
    # Default to succeeded outcome
    outcome = FlowOutcome.SUCCEEDED
    status = ""
    gate_verdict = None
    bounce_target = None
    error = None
    artifacts: Dict[str, str] = {}
    issues: List[str] = []
    recommendations: List[str] = []

    # Check handoff envelopes for this flow
    flow_envelopes = {
        step_id: env
        for step_id, env in run_state.handoff_envelopes.items()
        if env.flow_key == flow_key
    }

    # Aggregate status from envelopes
    for step_id, envelope in flow_envelopes.items():
        if envelope.status == "failed":
            outcome = FlowOutcome.FAILED
            error = envelope.error
            break
        elif envelope.status == "partial":
            outcome = FlowOutcome.PARTIAL

        # Collect artifacts
        for name, path in envelope.artifacts.items():
            artifacts[f"{step_id}/{name}"] = path

        # Extract status from routing signal
        if envelope.routing_signal and envelope.routing_signal.reason:
            # Look for status patterns
            reason = envelope.routing_signal.reason.upper()
            if "VERIFIED" in reason:
                status = "VERIFIED"
            elif "UNVERIFIED" in reason:
                status = "UNVERIFIED"
            elif "BLOCKED" in reason:
                status = "BLOCKED"

    # Special handling for gate flow
    if flow_key == "gate":
        gate_verdict = _extract_gate_verdict(flow_envelopes, artifacts_base)
        if gate_verdict in (GateVerdict.BOUNCE_BUILD, GateVerdict.BOUNCE_PLAN):
            outcome = FlowOutcome.BOUNCED
            bounce_target = "build" if gate_verdict == GateVerdict.BOUNCE_BUILD else "plan"

    return FlowResult(
        flow_key=flow_key,
        outcome=outcome,
        status=status,
        gate_verdict=gate_verdict,
        bounce_target=bounce_target,
        error=error,
        artifacts=artifacts,
        duration_ms=0,  # Would be computed from envelope timestamps
        issues=issues,
        recommendations=recommendations,
    )


def _extract_gate_verdict(
    flow_envelopes: Dict[str, Any],
    artifacts_base: Optional[Path],
) -> Optional[GateVerdict]:
    """Extract gate verdict from gate flow artifacts.

    Looks for merge_decision.md and parses the verdict field.

    Args:
        flow_envelopes: Handoff envelopes for the gate flow.
        artifacts_base: Path to flow artifacts.

    Returns:
        GateVerdict if found, None otherwise.
    """
    # Try to find verdict in envelope routing signals
    for step_id, envelope in flow_envelopes.items():
        if "merge-decider" in step_id or "decision" in step_id.lower():
            # Check routing signal for verdict hints
            if envelope.routing_signal:
                reason = envelope.routing_signal.reason.upper()
                if "MERGE_WITH_CONDITIONS" in reason:
                    return GateVerdict.MERGE_WITH_CONDITIONS
                elif "MERGE" in reason:
                    return GateVerdict.MERGE
                elif "BOUNCE_BUILD" in reason or "BOUNCE TO BUILD" in reason:
                    return GateVerdict.BOUNCE_BUILD
                elif "BOUNCE_PLAN" in reason or "BOUNCE TO PLAN" in reason:
                    return GateVerdict.BOUNCE_PLAN
                elif "ESCALATE" in reason:
                    return GateVerdict.ESCALATE
                elif "BLOCK" in reason:
                    return GateVerdict.BLOCK

    # Fallback: try to read merge_decision.md if path provided
    if artifacts_base:
        decision_path = artifacts_base / "gate" / "merge_decision.md"
        if decision_path.exists():
            try:
                content = decision_path.read_text()
                # Parse verdict from Machine Summary section
                if "verdict:" in content.lower():
                    for line in content.split("\n"):
                        if "verdict:" in line.lower():
                            verdict_str = line.split(":")[-1].strip().upper()
                            try:
                                return GateVerdict(verdict_str)
                            except ValueError:
                                pass
            except Exception as e:
                logger.warning("Failed to read merge_decision.md: %s", e)

    return None


# =============================================================================
# MacroNavigator
# =============================================================================


class MacroNavigator:
    """Between-flow routing decisions.

    The MacroNavigator makes routing decisions after each flow completes.
    It evaluates the flow result against routing rules and constraints
    to determine what flow to execute next.

    Key responsibilities:
    - Evaluate flow outcomes against routing rules
    - Enforce hard constraints (e.g., never deploy without gate approval)
    - Track flow execution history for loop detection
    - Respect max_repeats and max_total_flows limits

    Example:
        run_plan = RunPlanSpec.default()
        navigator = MacroNavigator(run_plan)

        # After gate flow completes
        flow_result = extract_flow_result("gate", run_state, artifacts_path)
        decision = navigator.route_after_flow("gate", flow_result, run_state)

        if decision.action == MacroAction.GOTO:
            # Gate bounced - jump to target flow
            next_flow = decision.next_flow
        elif decision.action == MacroAction.ADVANCE:
            # Proceed to deploy
            next_flow = decision.next_flow
    """

    def __init__(
        self,
        run_plan: RunPlanSpec,
        flow_execution_counts: Optional[Dict[str, int]] = None,
        bounce_counts: Optional[Dict[str, int]] = None,
    ):
        """Initialize the MacroNavigator.

        Args:
            run_plan: The run plan specification with policies and constraints.
            flow_execution_counts: Optional initial execution counts per flow.
            bounce_counts: Optional initial bounce counts between flow pairs.
        """
        self._run_plan = run_plan
        self._flow_execution_counts: Dict[str, int] = flow_execution_counts or {}
        self._total_flow_executions = sum(self._flow_execution_counts.values())
        self._routing_history: List[Dict[str, Any]] = []
        self._bounce_counts: Dict[str, int] = bounce_counts or {}
        self._constraint_evaluator = ConstraintEvaluator()
        self._parsed_constraints: List[ParsedConstraint] = []

        # Parse constraints from run plan
        for constraint_str in run_plan.constraints:
            try:
                parsed = self._constraint_evaluator.parse_constraint(constraint_str)
                self._parsed_constraints.append(parsed)
                logger.debug("Parsed constraint: %s -> %s", constraint_str, parsed)
            except ValueError as e:
                logger.warning("Failed to parse constraint '%s': %s", constraint_str, e)

    @property
    def run_plan(self) -> RunPlanSpec:
        """Get the run plan specification."""
        return self._run_plan

    @property
    def flow_execution_counts(self) -> Dict[str, int]:
        """Get execution counts per flow."""
        return self._flow_execution_counts.copy()

    @property
    def total_flow_executions(self) -> int:
        """Get total number of flow executions."""
        return self._total_flow_executions

    @property
    def bounce_counts(self) -> Dict[str, int]:
        """Get bounce counts between flow pairs."""
        return self._bounce_counts.copy()

    @property
    def parsed_constraints(self) -> List[ParsedConstraint]:
        """Get the parsed constraints."""
        return list(self._parsed_constraints)

    def route_after_flow(
        self,
        completed_flow: str,
        flow_result: FlowResult,
        run_state: RunState,
    ) -> MacroRoutingDecision:
        """Make routing decision after a flow completes.

        This is the main entry point for routing decisions. It:
        1. Records the flow execution
        2. Checks hard constraints
        3. Evaluates routing rules
        4. Applies human policy
        5. Returns the routing decision

        Args:
            completed_flow: The flow key that just completed.
            flow_result: Structured result of the completed flow.
            run_state: Current run state.

        Returns:
            MacroRoutingDecision with action, target, and explanation.
        """
        # Record this execution
        self._record_execution(completed_flow)

        # Check global limits
        if self._total_flow_executions >= self._run_plan.max_total_flows:
            return MacroRoutingDecision(
                action=MacroAction.TERMINATE,
                reason=f"Exceeded max total flows ({self._run_plan.max_total_flows})",
                warnings=["Safety limit reached - terminating run"],
            )

        # Check per-flow repeat limits
        flow_count = self._flow_execution_counts.get(completed_flow, 0)
        if flow_count > self._run_plan.macro_policy.max_repeats_per_flow:
            return MacroRoutingDecision(
                action=MacroAction.TERMINATE,
                reason=f"Flow '{completed_flow}' exceeded max repeats "
                f"({self._run_plan.macro_policy.max_repeats_per_flow})",
                warnings=[f"Flow {completed_flow} repeated too many times"],
            )

        # Evaluate routing rules first to get proposed next_flow
        rule_decision = self._evaluate_routing_rules(flow_result)

        # If routing rules suggest a jump (bounce), record it
        if rule_decision and rule_decision.action == MacroAction.GOTO:
            self._record_bounce(completed_flow, rule_decision.next_flow)

        # Determine the proposed next flow
        proposed_next_flow: Optional[str] = None
        if rule_decision:
            proposed_next_flow = rule_decision.next_flow
        else:
            # Would use default advance
            sequence = self._run_plan.flow_sequence
            if completed_flow in sequence:
                idx = sequence.index(completed_flow)
                if idx + 1 < len(sequence):
                    proposed_next_flow = sequence[idx + 1]

        # Check hard constraints with knowledge of proposed next flow
        constraint_result = self._check_constraints(completed_flow, flow_result, proposed_next_flow)
        if constraint_result:
            return constraint_result

        # Apply the routing rule decision if one matched
        if rule_decision:
            return rule_decision

        # Apply human policy
        human_decision = self._apply_human_policy(completed_flow)
        if human_decision:
            return human_decision

        # Default: advance to next flow in sequence
        return self._default_advance(completed_flow)

    def _record_execution(self, flow_key: str) -> None:
        """Record a flow execution for tracking."""
        self._flow_execution_counts[flow_key] = self._flow_execution_counts.get(flow_key, 0) + 1
        self._total_flow_executions += 1

        self._routing_history.append(
            {
                "flow": flow_key,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "execution_number": self._flow_execution_counts[flow_key],
            }
        )

    def _record_bounce(self, from_flow: str, to_flow: Optional[str]) -> None:
        """Record a bounce between flows for constraint tracking.

        Args:
            from_flow: The flow that bounced.
            to_flow: The target flow of the bounce.
        """
        if to_flow is None:
            return

        bounce_key = f"{from_flow}->{to_flow}"
        self._bounce_counts[bounce_key] = self._bounce_counts.get(bounce_key, 0) + 1

        logger.debug(
            "Recorded bounce %s: count now %d",
            bounce_key,
            self._bounce_counts[bounce_key],
        )

    def _check_constraints(
        self,
        completed_flow: str,
        flow_result: FlowResult,
        proposed_next_flow: Optional[str] = None,
    ) -> Optional[MacroRoutingDecision]:
        """Check hard constraints that override routing rules.

        Evaluates all parsed constraints against the current context to
        detect any violations. If a constraint is violated, returns the
        appropriate MacroRoutingDecision (PAUSE or TERMINATE).

        Args:
            completed_flow: The flow that completed.
            flow_result: Result of the completed flow.
            proposed_next_flow: The proposed next flow (from routing rules).

        Returns:
            MacroRoutingDecision if constraint violated, None otherwise.
        """
        if not self._parsed_constraints:
            return None

        # Build constraint context
        context = ConstraintContext(
            completed_flow=completed_flow,
            flow_result=flow_result,
            next_flow=proposed_next_flow,
            flow_execution_counts=self._flow_execution_counts.copy(),
            routing_history=list(self._routing_history),
            bounce_counts=self._bounce_counts.copy(),
        )

        # Evaluate each constraint
        violations: List[ConstraintViolation] = []
        constraints_checked: List[str] = []

        for constraint in self._parsed_constraints:
            is_valid, violation = self._constraint_evaluator.evaluate(constraint, context)
            constraints_checked.append(constraint.raw_text)

            if not is_valid and violation is not None:
                violations.append(violation)
                logger.warning(
                    "Constraint violation: %s",
                    self._constraint_evaluator.get_violation_message(violation),
                )

        # If any violations, return the most severe action
        if violations:
            # Sort by severity: TERMINATE > PAUSE
            severity_order = {MacroAction.TERMINATE: 0, MacroAction.PAUSE: 1}
            violations.sort(key=lambda v: severity_order.get(v.suggested_action, 2))

            most_severe = violations[0]

            # Combine all violation messages
            all_messages = [v.message for v in violations]
            combined_reason = "; ".join(all_messages)

            return MacroRoutingDecision(
                action=most_severe.suggested_action,
                reason=f"Constraint violation: {combined_reason}",
                constraints_checked=constraints_checked,
                warnings=[f"Violated: {v.constraint.raw_text}" for v in violations],
            )

        return None

    def _evaluate_routing_rules(
        self,
        flow_result: FlowResult,
    ) -> Optional[MacroRoutingDecision]:
        """Evaluate routing rules against flow result.

        Args:
            flow_result: Result of the completed flow.

        Returns:
            MacroRoutingDecision if a rule matched, None otherwise.
        """
        policy = self._run_plan.macro_policy

        for rule in policy.routing_rules:
            if not rule.can_fire():
                logger.debug(
                    "Rule %s exhausted (uses: %d/%d)",
                    rule.rule_id,
                    rule.uses,
                    rule.max_uses,
                )
                continue

            if rule.matches(flow_result):
                rule.record_use()
                logger.info(
                    "Rule %s matched: %s -> %s",
                    rule.rule_id,
                    rule.action.value,
                    rule.target_flow or "(no target)",
                )

                return MacroRoutingDecision(
                    action=rule.action,
                    next_flow=rule.target_flow,
                    reason=rule.description or f"Rule {rule.rule_id} matched",
                    rule_applied=rule.rule_id,
                )

        return None

    def _apply_human_policy(
        self,
        completed_flow: str,
    ) -> Optional[MacroRoutingDecision]:
        """Apply human interaction policy.

        Args:
            completed_flow: The flow that completed.

        Returns:
            MacroRoutingDecision if human pause required, None otherwise.
        """
        human_policy = self._run_plan.human_policy

        # Check if this flow requires approval
        if completed_flow in human_policy.require_approval_flows:
            return MacroRoutingDecision(
                action=MacroAction.PAUSE,
                reason=f"Flow '{completed_flow}' requires human approval",
            )

        # Check per_flow mode
        if human_policy.mode == "per_flow" and human_policy.allow_pause_between_flows:
            return MacroRoutingDecision(
                action=MacroAction.PAUSE,
                reason="Per-flow review mode - awaiting human approval",
            )

        return None

    def _default_advance(
        self,
        completed_flow: str,
    ) -> MacroRoutingDecision:
        """Get default advance decision (next flow in sequence).

        Args:
            completed_flow: The flow that completed.

        Returns:
            MacroRoutingDecision to advance to next flow or terminate.
        """
        sequence = self._run_plan.flow_sequence

        if completed_flow not in sequence:
            return MacroRoutingDecision(
                action=MacroAction.TERMINATE,
                reason=f"Flow '{completed_flow}' not in sequence",
                warnings=[f"Unknown flow: {completed_flow}"],
            )

        idx = sequence.index(completed_flow)
        if idx + 1 >= len(sequence):
            return MacroRoutingDecision(
                action=MacroAction.TERMINATE,
                reason="All flows in sequence completed",
            )

        next_flow = sequence[idx + 1]
        return MacroRoutingDecision(
            action=MacroAction.ADVANCE,
            next_flow=next_flow,
            reason=f"Advancing from '{completed_flow}' to '{next_flow}'",
        )

    def get_routing_history(self) -> List[Dict[str, Any]]:
        """Get the routing history for audit purposes.

        Returns:
            List of routing events with timestamps and decisions.
        """
        return list(self._routing_history)

    def reset_rule_uses(self) -> None:
        """Reset all rule usage counters.

        Call this when starting a fresh run with the same navigator.
        """
        for rule in self._run_plan.macro_policy.routing_rules:
            rule.uses = 0

    def to_dict(self) -> Dict[str, Any]:
        """Serialize navigator state for persistence.

        Returns:
            Dictionary with navigator state.
        """
        return {
            "flow_execution_counts": dict(self._flow_execution_counts),
            "total_flow_executions": self._total_flow_executions,
            "routing_history": list(self._routing_history),
            "bounce_counts": dict(self._bounce_counts),
        }

    @classmethod
    def from_dict(
        cls,
        data: Dict[str, Any],
        run_plan: RunPlanSpec,
    ) -> "MacroNavigator":
        """Restore navigator from serialized state.

        Args:
            data: Serialized navigator state.
            run_plan: Run plan specification.

        Returns:
            Restored MacroNavigator instance.
        """
        navigator = cls(
            run_plan=run_plan,
            flow_execution_counts=dict(data.get("flow_execution_counts", {})),
            bounce_counts=dict(data.get("bounce_counts", {})),
        )
        navigator._total_flow_executions = data.get(
            "total_flow_executions",
            sum(navigator._flow_execution_counts.values()),
        )
        navigator._routing_history = list(data.get("routing_history", []))
        return navigator


# =============================================================================
# Convenience Functions
# =============================================================================


def create_default_navigator() -> MacroNavigator:
    """Create a MacroNavigator with default SDLC configuration.

    Returns:
        MacroNavigator configured for standard signal -> wisdom flow.
    """
    return MacroNavigator(RunPlanSpec.default())


def create_autopilot_navigator() -> MacroNavigator:
    """Create a MacroNavigator for autonomous (no human) execution.

    Returns:
        MacroNavigator configured for autopilot mode.
    """
    run_plan = RunPlanSpec(
        flow_sequence=["signal", "plan", "build", "gate", "deploy", "wisdom"],
        macro_policy=MacroPolicy.default(),
        human_policy=HumanPolicy.autopilot(),
        constraints=[
            "never deploy unless gate verdict is MERGE or MERGE_WITH_CONDITIONS",
            "never skip gate flow",
        ],
        max_total_flows=20,
    )
    return MacroNavigator(run_plan)


def create_supervised_navigator() -> MacroNavigator:
    """Create a MacroNavigator for supervised (human-in-loop) execution.

    Returns:
        MacroNavigator configured for supervised mode with pauses.
    """
    run_plan = RunPlanSpec(
        flow_sequence=["signal", "plan", "build", "gate", "deploy", "wisdom"],
        macro_policy=MacroPolicy.default(),
        human_policy=HumanPolicy.supervised(),
        constraints=[
            "never deploy unless gate verdict is MERGE or MERGE_WITH_CONDITIONS",
            "never skip gate flow",
        ],
        max_total_flows=20,
    )
    return MacroNavigator(run_plan)


__all__ = [
    # Core navigator
    "MacroNavigator",
    "extract_flow_result",
    # Constraint evaluation
    "ConstraintEvaluator",
    "ConstraintType",
    "ParsedConstraint",
    "ConstraintViolation",
    "ConstraintContext",
    # Factory functions
    "create_default_navigator",
    "create_autopilot_navigator",
    "create_supervised_navigator",
]
