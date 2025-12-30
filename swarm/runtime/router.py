"""
router.py - Bounded, auditable, deterministic-first routing for stepwise execution

This module implements the graph-constrained routing system as defined in ADR-004.
The routing system determines the next node in a flow execution by following a strict
priority order:

1. Explicit routing - step output specifies next_step_id
2. Exit conditions - exit_on rules (VERIFIED, max_iterations)
3. Deterministic edges - single outgoing edge, or edge with condition=true
4. CEL evaluation - evaluate edge conditions against step context
5. LLM tie-breaker - only if multiple edges remain valid

The key principle is: graph constraints are always enforced. The router can never
route to an edge not defined in the flow graph. LLM is only a tie-breaker when
deterministic rules do not resolve.

Primary Entry Points:

    route_from_step(flow_graph, current_node, step_output, context)
        The main entry point for stepwise routing. Returns a RoutingResult with
        the selected edge, decision method, and WP4-compliant audit trail.

    attach_routing_audit(envelope, routing_result)
        Attach routing explanation to a HandoffEnvelope for audit trail.

Legacy/Internal Classes:

    SmartRouter - Graph-constrained router with LLM tie-breaker (internal)
    StepRouter - WP4-compliant bounded, auditable router (internal)

Usage:
    from swarm.runtime.router import (
        route_from_step,
        attach_routing_audit,
        RoutingContext,
        RoutingResult,
        FlowGraph,
        Edge,
    )

    # Load flow graph from spec
    graph = FlowGraph.from_dict(flow_spec)

    # Create routing context
    context = RoutingContext(
        run_id="run-123",
        flow_key="build",
        current_node="code-implementer",
    )

    # Route to next step
    result = route_from_step(
        flow_graph=graph,
        current_node="code-implementer",
        step_output={"status": "VERIFIED"},
        context=context,
    )

    # Attach audit trail to envelope
    attach_routing_audit(envelope, result)

    # Execute next step or handle termination
    if not result.terminate:
        execute_step(result.edge.to_node)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# =============================================================================
# Core Data Types
# =============================================================================


class DecisionType(str, Enum):
    """Type of routing decision made."""

    EXPLICIT = "explicit"  # Step output specified next_step_id
    EXIT_CONDITION = "exit_condition"  # Exit condition (VERIFIED, max_iterations) met
    DETERMINISTIC = "deterministic"  # Single edge or edge with condition=true
    CEL = "cel"  # CEL expression evaluation
    LLM_TIEBREAKER = "llm_tiebreaker"  # LLM resolved tie between valid edges
    FLOW_COMPLETE = "flow_complete"  # No valid edges, flow is complete
    ERROR = "error"  # Routing error occurred


@dataclass
class ConditionEval:
    """Result of evaluating a single edge condition."""

    edge_id: str
    expression: str
    result: bool
    error: Optional[str] = None
    evaluated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class RouteDecision:
    """The result of a routing decision.

    Attributes:
        next_node_id: The ID of the next node to execute, or None if flow is complete.
        decision_type: How the routing decision was made.
        reasoning: Human-readable explanation of the decision.
        evaluated_conditions: List of condition evaluations performed.
        confidence: Confidence score for the decision (0.0 to 1.0).
        needs_human: Whether human review is recommended.
        loop_count: Current iteration count for microloop tracking.
    """

    next_node_id: Optional[str]
    decision_type: DecisionType
    reasoning: str
    evaluated_conditions: List[ConditionEval] = field(default_factory=list)
    confidence: float = 1.0
    needs_human: bool = False
    loop_count: int = 0


@dataclass
class StepOutput:
    """Output from a step execution relevant to routing.

    Attributes:
        status: The step's execution status (e.g., 'VERIFIED', 'UNVERIFIED', 'BLOCKED').
        next_step_id: Explicit next step if step declares it.
        proposed_action: Routing action hint from the step (PROCEED, RERUN, BOUNCE, FIX_ENV).
        can_further_iteration_help: Critic's judgment about iteration viability.
        custom_fields: Additional fields for CEL evaluation.
    """

    status: str = "UNKNOWN"
    next_step_id: Optional[str] = None
    proposed_action: Optional[str] = None
    can_further_iteration_help: Optional[bool] = None
    custom_fields: Dict[str, Any] = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        """Get a field value for CEL evaluation."""
        if key == "status":
            return self.status
        if key == "next_step_id":
            return self.next_step_id
        if key == "proposed_action":
            return self.proposed_action
        if key == "can_further_iteration_help":
            return self.can_further_iteration_help
        return self.custom_fields.get(key, default)


@dataclass
class RouteContext:
    """Context for routing decisions.

    Attributes:
        run_id: The current run identifier.
        flow_key: The flow being executed.
        iteration_counts: Map of node_id to iteration count for microloop tracking.
        max_iterations_default: Safety fuse (not steering) - default if not specified per-node.
            Actual loop exit should be driven by stall detection and critic judgment.
        previous_outputs: Map of step_id to their outputs for context.
        annotations: Arbitrary context annotations.
    """

    run_id: str
    flow_key: str
    iteration_counts: Dict[str, int] = field(default_factory=dict)
    max_iterations_default: int = 50  # Safety fuse, use stall detection for steering
    previous_outputs: Dict[str, StepOutput] = field(default_factory=dict)
    annotations: Dict[str, Any] = field(default_factory=dict)

    def get_iteration_count(self, node_id: str) -> int:
        """Get the current iteration count for a node."""
        return self.iteration_counts.get(node_id, 0)

    def increment_iteration(self, node_id: str) -> int:
        """Increment and return the iteration count for a node."""
        current = self.iteration_counts.get(node_id, 0)
        self.iteration_counts[node_id] = current + 1
        return current + 1


# =============================================================================
# Graph Types (matching flow_graph.schema.json)
# =============================================================================


@dataclass
class EdgeCondition:
    """Condition for edge traversal.

    Supports both simple field comparison and CEL expressions.
    """

    field: Optional[str] = None
    operator: str = "equals"
    value: Any = None
    expression: Optional[str] = None  # CEL or simple expression


@dataclass
class Edge:
    """An edge in the flow graph."""

    edge_id: str
    from_node: str  # 'from' in schema
    to_node: str  # 'to' in schema
    condition: Optional[EdgeCondition] = None
    priority: int = 50
    edge_type: str = "sequence"  # sequence, loop, branch, detour, injection, subflow

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Edge":
        """Create an Edge from a dictionary (flow_graph.schema.json format)."""
        condition = None
        if "condition" in data:
            cond_data = data["condition"]
            condition = EdgeCondition(
                field=cond_data.get("field"),
                operator=cond_data.get("operator", "equals"),
                value=cond_data.get("value"),
                expression=cond_data.get("expression"),
            )

        return cls(
            edge_id=data.get("edge_id", ""),
            from_node=data.get("from", ""),
            to_node=data.get("to", ""),
            condition=condition,
            priority=data.get("priority", 50),
            edge_type=data.get("type", "sequence"),
        )


@dataclass
class NodeConfig:
    """Configuration for a node relevant to routing."""

    node_id: str
    template_id: str
    max_iterations: Optional[int] = None
    exit_on: Optional[Dict[str, Any]] = None  # Exit conditions for microloops

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "NodeConfig":
        """Create a NodeConfig from a dictionary."""
        params = data.get("params", {})
        overrides = data.get("overrides", {})

        # Exit conditions can come from overrides or params
        exit_on = overrides.get("exit_on") or params.get("exit_on")
        max_iterations = overrides.get("max_iterations") or params.get("max_iterations")

        return cls(
            node_id=data.get("node_id", ""),
            template_id=data.get("template_id", ""),
            max_iterations=max_iterations,
            exit_on=exit_on,
        )


@dataclass
class FlowGraph:
    """A flow graph for routing decisions.

    Attributes:
        graph_id: Unique identifier for the graph.
        nodes: Map of node_id to NodeConfig.
        edges: List of edges in the graph.
        policy: Graph-level policy settings.
    """

    graph_id: str
    nodes: Dict[str, NodeConfig]
    edges: List[Edge]
    policy: Dict[str, Any] = field(default_factory=dict)

    def get_outgoing_edges(self, node_id: str) -> List[Edge]:
        """Get all edges originating from a node."""
        return [e for e in self.edges if e.from_node == node_id]

    def get_node(self, node_id: str) -> Optional[NodeConfig]:
        """Get a node by ID."""
        return self.nodes.get(node_id)

    def get_max_loop_iterations(self) -> int:
        """Get the default max loop iterations from policy."""
        return self.policy.get("max_loop_iterations", 5)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FlowGraph":
        """Create a FlowGraph from a dictionary (flow_graph.schema.json format)."""
        nodes = {}
        for node_data in data.get("nodes", []):
            node = NodeConfig.from_dict(node_data)
            nodes[node.node_id] = node

        edges = [Edge.from_dict(e) for e in data.get("edges", [])]

        return cls(
            graph_id=data.get("id", ""),
            nodes=nodes,
            edges=edges,
            policy=data.get("policy", {}),
        )


# =============================================================================
# CEL Expression Evaluator (Simple Implementation)
# =============================================================================


class CELEvaluator:
    """Simple CEL-like expression evaluator.

    Supports a subset of CEL for edge condition evaluation:
    - Comparisons: ==, !=, <, >, <=, >=
    - Boolean logic: &&, ||, !
    - String operations: contains, startsWith, endsWith
    - Field access: status, iteration_count, context.field

    For production use, consider using cel-python or similar library.
    """

    def __init__(self):
        self._operators = {
            "equals": lambda a, b: a == b,
            "not_equals": lambda a, b: a != b,
            "in": lambda a, b: a in b if isinstance(b, (list, tuple, set)) else False,
            "not_in": lambda a, b: a not in b if isinstance(b, (list, tuple, set)) else True,
            "contains": lambda a, b: b in a if isinstance(a, str) else False,
            "gt": lambda a, b: a > b if a is not None and b is not None else False,
            "lt": lambda a, b: a < b if a is not None and b is not None else False,
            "gte": lambda a, b: a >= b if a is not None and b is not None else False,
            "lte": lambda a, b: a <= b if a is not None and b is not None else False,
            "matches": lambda a, b: bool(re.search(b, a)) if isinstance(a, str) else False,
        }

    def evaluate_condition(
        self,
        condition: EdgeCondition,
        context: Dict[str, Any],
    ) -> Tuple[bool, Optional[str]]:
        """Evaluate an edge condition against context.

        Args:
            condition: The edge condition to evaluate.
            context: Context dictionary for variable resolution.

        Returns:
            Tuple of (result, error_message or None).
        """
        try:
            # If there's a CEL expression, evaluate it
            if condition.expression:
                return self._evaluate_expression(condition.expression, context)

            # Otherwise, use simple field comparison
            if condition.field is None:
                # No condition means always true (unconditional edge)
                return True, None

            field_value = self._resolve_field(condition.field, context)
            operator = condition.operator
            expected_value = condition.value

            if operator not in self._operators:
                return False, f"Unknown operator: {operator}"

            op_func = self._operators[operator]
            result = op_func(field_value, expected_value)
            return result, None

        except Exception as e:
            logger.debug("Condition evaluation error: %s", e)
            return False, str(e)

    def _resolve_field(self, field_path: str, context: Dict[str, Any]) -> Any:
        """Resolve a field path in the context.

        Supports dot notation: 'context.has_errors', 'output.severity'
        """
        parts = field_path.split(".")
        value = context

        for part in parts:
            if isinstance(value, dict):
                value = value.get(part)
            elif hasattr(value, part):
                value = getattr(value, part)
            elif hasattr(value, "get"):
                value = value.get(part)
            else:
                return None

            if value is None:
                return None

        return value

    def _evaluate_expression(
        self,
        expression: str,
        context: Dict[str, Any],
    ) -> Tuple[bool, Optional[str]]:
        """Evaluate a CEL-like expression.

        Supports simple expressions like:
        - status == 'VERIFIED'
        - iteration_count >= 3
        - status == 'VERIFIED' || can_further_iteration_help == false
        """
        try:
            # Normalize the expression
            expr = expression.strip()

            # Handle || (OR) - check if any sub-expression is true
            if "||" in expr:
                parts = [p.strip() for p in expr.split("||")]
                for part in parts:
                    result, err = self._evaluate_simple_expression(part, context)
                    if err is None and result:
                        return True, None
                return False, None

            # Handle && (AND) - check if all sub-expressions are true
            if "&&" in expr:
                parts = [p.strip() for p in expr.split("&&")]
                for part in parts:
                    result, err = self._evaluate_simple_expression(part, context)
                    if err is not None or not result:
                        return False, err
                return True, None

            # Simple expression
            return self._evaluate_simple_expression(expr, context)

        except Exception as e:
            return False, str(e)

    def _evaluate_simple_expression(
        self,
        expr: str,
        context: Dict[str, Any],
    ) -> Tuple[bool, Optional[str]]:
        """Evaluate a simple comparison expression."""
        # Supported operators: ==, !=, >=, <=, >, <
        operators_re = r"(==|!=|>=|<=|>|<)"
        match = re.split(operators_re, expr)

        if len(match) != 3:
            return False, f"Invalid expression: {expr}"

        left = match[0].strip()
        operator = match[1]
        right = match[2].strip()

        # Resolve left side
        left_value = self._resolve_value(left, context)

        # Resolve right side
        right_value = self._resolve_value(right, context)

        # Compare
        if operator == "==":
            return left_value == right_value, None
        elif operator == "!=":
            return left_value != right_value, None
        elif operator == ">=":
            return left_value >= right_value, None
        elif operator == "<=":
            return left_value <= right_value, None
        elif operator == ">":
            return left_value > right_value, None
        elif operator == "<":
            return left_value < right_value, None

        return False, f"Unknown operator: {operator}"

    def _resolve_value(self, value_str: str, context: Dict[str, Any]) -> Any:
        """Resolve a value from string representation or context."""
        value_str = value_str.strip()

        # String literal
        if (value_str.startswith("'") and value_str.endswith("'")) or (
            value_str.startswith('"') and value_str.endswith('"')
        ):
            return value_str[1:-1]

        # Boolean
        if value_str.lower() == "true":
            return True
        if value_str.lower() == "false":
            return False

        # Numeric
        try:
            if "." in value_str:
                return float(value_str)
            return int(value_str)
        except ValueError:
            pass

        # Context field
        return self._resolve_field(value_str, context)


# =============================================================================
# SmartRouter
# =============================================================================


class SmartRouter:
    """Graph-constrained router with LLM tie-breaker.

    Implements the routing strategy from ADR-004:
    1. Explicit routing - step output specifies next_step_id
    2. Exit conditions - exit_on rules (VERIFIED, max_iterations)
    3. Deterministic edges - single outgoing edge, or edge with condition=true
    4. CEL evaluation - evaluate edge conditions against step context
    5. LLM tie-breaker - only if multiple edges remain valid

    The router never creates edges not in the graph. All routing decisions
    are constrained to valid graph edges.
    """

    def __init__(
        self,
        llm_tiebreaker: Optional[Callable[[List[Edge], RouteContext], str]] = None,
        confidence_threshold: float = 0.7,
    ):
        """Initialize the SmartRouter.

        Args:
            llm_tiebreaker: Optional callable for LLM tie-breaking.
                Takes (valid_edges, context) and returns target node_id.
                If not provided, uses first edge by priority as fallback.
            confidence_threshold: Confidence threshold below which needs_human
                is set to True.
        """
        self._cel_evaluator = CELEvaluator()
        self._llm_tiebreaker = llm_tiebreaker
        self._confidence_threshold = confidence_threshold

    def route(
        self,
        current_node: str,
        graph: FlowGraph,
        step_output: StepOutput,
        context: RouteContext,
    ) -> RouteDecision:
        """Determine the next node based on routing priority.

        Args:
            current_node: The ID of the current node.
            graph: The flow graph defining valid transitions.
            step_output: Output from the current step execution.
            context: Routing context including iteration counts.

        Returns:
            RouteDecision with the next node and decision metadata.
        """
        logger.debug("Routing from %s with status=%s", current_node, step_output.status)

        # Get all outgoing edges from current node
        all_edges = graph.get_outgoing_edges(current_node)

        if not all_edges:
            # No outgoing edges = flow complete
            return RouteDecision(
                next_node_id=None,
                decision_type=DecisionType.FLOW_COMPLETE,
                reasoning=f"No outgoing edges from {current_node}",
            )

        # Build evaluation context
        eval_context = self._build_eval_context(current_node, graph, step_output, context)

        # Priority 1: Explicit routing from step output
        if step_output.next_step_id:
            result = self._try_explicit_routing(step_output.next_step_id, all_edges, eval_context)
            if result:
                return result

        # Priority 2: Exit conditions (VERIFIED, max_iterations)
        result = self._check_exit_conditions(current_node, graph, step_output, context, all_edges)
        if result:
            return result

        # Priority 3: Deterministic edges
        result = self._try_deterministic_routing(all_edges, eval_context)
        if result:
            return result

        # Priority 4: CEL evaluation
        valid_edges, evaluated = self._evaluate_edge_conditions(all_edges, eval_context)

        if len(valid_edges) == 0:
            # No valid edges found - flow complete or error
            return RouteDecision(
                next_node_id=None,
                decision_type=DecisionType.FLOW_COMPLETE,
                reasoning="No edge conditions matched",
                evaluated_conditions=evaluated,
            )

        if len(valid_edges) == 1:
            # Single valid edge after CEL evaluation
            edge = valid_edges[0]
            return RouteDecision(
                next_node_id=edge.to_node,
                decision_type=DecisionType.CEL,
                reasoning=f"Single edge matched: {edge.edge_id}",
                evaluated_conditions=evaluated,
            )

        # Priority 5: LLM tie-breaker
        return self._invoke_llm_tiebreaker(valid_edges, context, evaluated)

    def evaluate_edge_condition(
        self,
        edge: Edge,
        context: Dict[str, Any],
    ) -> Tuple[bool, Optional[str]]:
        """Evaluate a single edge condition.

        Args:
            edge: The edge whose condition to evaluate.
            context: Evaluation context dictionary.

        Returns:
            Tuple of (result, error_message or None).
        """
        if edge.condition is None:
            # No condition = always valid
            return True, None

        return self._cel_evaluator.evaluate_condition(edge.condition, context)

    def get_valid_edges(
        self,
        node: str,
        graph: FlowGraph,
        context: Dict[str, Any],
    ) -> List[Edge]:
        """Get all valid edges from a node given the context.

        Args:
            node: The node ID to check edges from.
            graph: The flow graph.
            context: Evaluation context dictionary.

        Returns:
            List of edges whose conditions evaluate to true.
        """
        all_edges = graph.get_outgoing_edges(node)
        valid = []

        for edge in all_edges:
            result, _ = self.evaluate_edge_condition(edge, context)
            if result:
                valid.append(edge)

        return valid

    def invoke_llm_tiebreaker(
        self,
        valid_edges: List[Edge],
        context: RouteContext,
    ) -> str:
        """Invoke the LLM to break a tie between valid edges.

        Args:
            valid_edges: List of valid edges to choose from.
            context: The routing context.

        Returns:
            The target node_id chosen by the LLM.

        Raises:
            ValueError: If LLM returns invalid edge.
        """
        if not valid_edges:
            raise ValueError("No valid edges to choose from")

        if self._llm_tiebreaker:
            chosen_id = self._llm_tiebreaker(valid_edges, context)

            # Validate the choice
            valid_targets = {e.to_node for e in valid_edges}
            if chosen_id not in valid_targets:
                logger.warning(
                    "LLM returned invalid target %s, falling back to first edge", chosen_id
                )
                # Fall back to first edge by priority
                chosen_id = self._get_default_edge(valid_edges).to_node

            return chosen_id

        # No LLM tiebreaker configured, use priority-based fallback
        return self._get_default_edge(valid_edges).to_node

    # =========================================================================
    # Private Methods
    # =========================================================================

    def _build_eval_context(
        self,
        current_node: str,
        graph: FlowGraph,
        step_output: StepOutput,
        context: RouteContext,
    ) -> Dict[str, Any]:
        """Build the evaluation context for CEL expressions."""
        node_config = graph.get_node(current_node)
        iteration_count = context.get_iteration_count(current_node)
        max_iterations = (
            node_config.max_iterations
            if node_config and node_config.max_iterations
            else graph.get_max_loop_iterations()
        )

        return {
            "status": step_output.status,
            "next_step_id": step_output.next_step_id,
            "proposed_action": step_output.proposed_action,
            "can_further_iteration_help": step_output.can_further_iteration_help,
            "iteration_count": iteration_count,
            "max_iterations": max_iterations,
            "run_id": context.run_id,
            "flow_key": context.flow_key,
            "context": context.annotations,
            "output": step_output.custom_fields,
            **step_output.custom_fields,
        }

    def _try_explicit_routing(
        self,
        target_id: str,
        edges: List[Edge],
        eval_context: Dict[str, Any],
    ) -> Optional[RouteDecision]:
        """Try explicit routing if step output specifies next_step_id."""
        # Validate that target is a valid edge
        valid_targets = {e.to_node for e in edges}
        if target_id in valid_targets:
            return RouteDecision(
                next_node_id=target_id,
                decision_type=DecisionType.EXPLICIT,
                reasoning=f"Step output explicitly requested: {target_id}",
            )

        logger.warning("Explicit target %s is not a valid edge, ignoring", target_id)
        return None

    def _check_exit_conditions(
        self,
        current_node: str,
        graph: FlowGraph,
        step_output: StepOutput,
        context: RouteContext,
        edges: List[Edge],
    ) -> Optional[RouteDecision]:
        """Check exit conditions for microloops."""
        node_config = graph.get_node(current_node)
        iteration_count = context.get_iteration_count(current_node)
        max_iterations = (
            node_config.max_iterations
            if node_config and node_config.max_iterations
            else graph.get_max_loop_iterations()
        )

        exit_reason = None

        # Check status-based exit (VERIFIED = done)
        if step_output.status == "VERIFIED":
            exit_reason = "status=VERIFIED"

        # Check iteration limit
        elif iteration_count >= max_iterations:
            exit_reason = f"max_iterations={max_iterations}"

        # Check can_further_iteration_help
        elif step_output.can_further_iteration_help is False:
            exit_reason = "can_further_iteration_help=false"

        # Check node-specific exit_on conditions
        elif node_config and node_config.exit_on:
            exit_on = node_config.exit_on

            # Check status values
            if "status" in exit_on:
                status_values = exit_on["status"]
                if isinstance(status_values, list) and step_output.status in status_values:
                    exit_reason = f"exit_on.status={step_output.status}"
                elif isinstance(status_values, str) and step_output.status == status_values:
                    exit_reason = f"exit_on.status={step_output.status}"

        if exit_reason:
            # Find non-loop edge (exit edge)
            exit_edges = [e for e in edges if e.edge_type != "loop"]
            if exit_edges:
                # Take highest priority exit edge
                exit_edge = self._get_default_edge(exit_edges)
                return RouteDecision(
                    next_node_id=exit_edge.to_node,
                    decision_type=DecisionType.EXIT_CONDITION,
                    reasoning=f"Exit condition met: {exit_reason}",
                    loop_count=iteration_count,
                )
            else:
                # No exit edge, flow complete
                return RouteDecision(
                    next_node_id=None,
                    decision_type=DecisionType.EXIT_CONDITION,
                    reasoning=f"Exit condition met ({exit_reason}), no exit edge",
                    loop_count=iteration_count,
                )

        # Increment iteration count for loop edges
        loop_edges = [e for e in edges if e.edge_type == "loop"]
        if loop_edges:
            context.increment_iteration(current_node)

        return None

    def _try_deterministic_routing(
        self,
        edges: List[Edge],
        eval_context: Dict[str, Any],
    ) -> Optional[RouteDecision]:
        """Try deterministic routing (single edge or unconditional edge)."""
        # Single edge = deterministic
        if len(edges) == 1:
            edge = edges[0]
            # Still check condition if present
            if edge.condition:
                result, err = self.evaluate_edge_condition(edge, eval_context)
                if not result:
                    return RouteDecision(
                        next_node_id=None,
                        decision_type=DecisionType.FLOW_COMPLETE,
                        reasoning=f"Single edge condition failed: {err}",
                        evaluated_conditions=[
                            ConditionEval(
                                edge_id=edge.edge_id,
                                expression=str(edge.condition.expression or edge.condition.field),
                                result=False,
                                error=err,
                            )
                        ],
                    )

            return RouteDecision(
                next_node_id=edge.to_node,
                decision_type=DecisionType.DETERMINISTIC,
                reasoning=f"Single outgoing edge: {edge.edge_id}",
            )

        # Check for unconditional edges
        unconditional = [e for e in edges if e.condition is None]
        if len(unconditional) == 1:
            edge = unconditional[0]
            return RouteDecision(
                next_node_id=edge.to_node,
                decision_type=DecisionType.DETERMINISTIC,
                reasoning=f"Single unconditional edge: {edge.edge_id}",
            )

        return None

    def _evaluate_edge_conditions(
        self,
        edges: List[Edge],
        eval_context: Dict[str, Any],
    ) -> Tuple[List[Edge], List[ConditionEval]]:
        """Evaluate conditions for all edges."""
        valid_edges = []
        evaluated = []

        # Sort edges by priority (higher first)
        sorted_edges = sorted(edges, key=lambda e: e.priority, reverse=True)

        for edge in sorted_edges:
            expression_str = ""
            if edge.condition:
                expression_str = (
                    edge.condition.expression
                    or f"{edge.condition.field} {edge.condition.operator} {edge.condition.value}"
                )

            result, err = self.evaluate_edge_condition(edge, eval_context)

            evaluated.append(
                ConditionEval(
                    edge_id=edge.edge_id,
                    expression=expression_str or "(unconditional)",
                    result=result,
                    error=err,
                )
            )

            if result:
                valid_edges.append(edge)

        return valid_edges, evaluated

    def _invoke_llm_tiebreaker(
        self,
        valid_edges: List[Edge],
        context: RouteContext,
        evaluated: List[ConditionEval],
    ) -> RouteDecision:
        """Invoke LLM tie-breaker for multiple valid edges."""
        try:
            chosen_target = self.invoke_llm_tiebreaker(valid_edges, context)

            # Determine confidence based on whether LLM was actually used
            confidence = 0.9 if self._llm_tiebreaker else 0.7
            needs_human = confidence < self._confidence_threshold

            return RouteDecision(
                next_node_id=chosen_target,
                decision_type=DecisionType.LLM_TIEBREAKER,
                reasoning=f"LLM chose {chosen_target} from {len(valid_edges)} valid edges",
                evaluated_conditions=evaluated,
                confidence=confidence,
                needs_human=needs_human,
            )
        except Exception as e:
            logger.warning("LLM tie-breaker failed: %s", e)

            # Fallback to default edge
            default_edge = self._get_default_edge(valid_edges)
            return RouteDecision(
                next_node_id=default_edge.to_node,
                decision_type=DecisionType.ERROR,
                reasoning=f"LLM tie-breaker failed ({e}), using default: {default_edge.edge_id}",
                evaluated_conditions=evaluated,
                confidence=0.5,
                needs_human=True,
            )

    def _get_default_edge(self, edges: List[Edge]) -> Edge:
        """Get the default edge by priority."""
        if not edges:
            raise ValueError("No edges to select from")

        # Sort by priority (higher first), then by edge_id for determinism
        sorted_edges = sorted(edges, key=lambda e: (-e.priority, e.edge_id))
        return sorted_edges[0]


# =============================================================================
# Convenience Functions
# =============================================================================


def create_router(
    llm_tiebreaker: Optional[Callable[[List[Edge], RouteContext], str]] = None,
) -> SmartRouter:
    """Create a SmartRouter with optional LLM tie-breaker.

    Args:
        llm_tiebreaker: Optional callable for LLM tie-breaking.

    Returns:
        Configured SmartRouter instance.
    """
    return SmartRouter(llm_tiebreaker=llm_tiebreaker)


def route_step(
    current_node: str,
    graph: FlowGraph,
    step_output: StepOutput,
    context: RouteContext,
    router: Optional[SmartRouter] = None,
) -> RouteDecision:
    """Convenience function for routing a step.

    Args:
        current_node: The current node ID.
        graph: The flow graph.
        step_output: The step output.
        context: The routing context.
        router: Optional router instance. If not provided, creates a new one.

    Returns:
        The routing decision.
    """
    if router is None:
        router = SmartRouter()

    return router.route(current_node, graph, step_output, context)


# =============================================================================
# WP4: StepRouter - Bounded, Auditable, Cheap Routing
# =============================================================================


@dataclass
class RoutingResult:
    """Result of a routing decision with full audit trail.

    Implements the WP4 RoutingExplanation schema for bounded, auditable,
    and cheap routing decisions.

    Attributes:
        edge: The selected edge to follow, or None if flow terminates.
        method: How the decision was made (deterministic, llm_tiebreak, no_candidates).
        terminate: Whether the flow should terminate.
        needs_human: Whether human review is recommended.
        explanation: Full structured explanation for audit trail.
    """

    edge: Optional[Edge] = None
    method: str = "deterministic"
    terminate: bool = False
    needs_human: bool = False
    explanation: Optional[Dict[str, Any]] = None


@dataclass
class RunContext:
    """Context for routing decisions during flow execution.

    Provides access to step output, iteration counts, and flow state
    needed for routing decisions.

    Attributes:
        run_id: The unique run identifier.
        flow_key: The flow being executed.
        step_output: Output from the current step.
        iteration_counts: Map of node_id to iteration count for microloop tracking.
        max_iterations: Safety fuse for microloops (not steering - use stall detection).
        annotations: Additional context data.
    """

    run_id: str
    flow_key: str
    step_output: Dict[str, Any]
    iteration_counts: Dict[str, int] = field(default_factory=dict)
    max_iterations: int = 50  # Safety fuse, use stall detection for steering
    annotations: Dict[str, Any] = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        """Get a value from step output or annotations."""
        if key in self.step_output:
            return self.step_output[key]
        return self.annotations.get(key, default)


class StepRouter:
    """Bounded, auditable, cheap router for stepwise flow execution.

    Implements WP4 routing strategy:
    1. Get candidate edges from adjacency only (graph-constrained)
    2. Apply exit conditions (microloop termination)
    3. Apply CEL/condition evaluation
    4. Decision logic:
       - 0 candidates -> terminate with needs_human=True
       - 1 candidate -> deterministic selection
       - >1 candidates -> LLM tiebreaker

    The router is designed to be:
    - **Bounded**: Only considers edges in the graph, with finite candidates
    - **Auditable**: Produces structured explanation for every decision
    - **Cheap**: Uses LLM only when truly needed (tiebreaker for multiple valid edges)

    Usage:
        router = StepRouter()
        result = router.route(current_node, flow_graph, context)

        # Check the result
        if result.terminate:
            handle_flow_completion(result.needs_human)
        else:
            execute_step(result.edge.to_node)

        # Store audit trail
        envelope.routing_audit = result.explanation
    """

    def __init__(
        self,
        llm_tiebreaker: Optional[Callable[[List[Edge], RunContext], Tuple[str, str]]] = None,
    ):
        """Initialize the StepRouter.

        Args:
            llm_tiebreaker: Optional callable for LLM tie-breaking.
                Takes (valid_edges, context) and returns (target_node_id, reasoning).
                If not provided, uses priority-based fallback.
        """
        self._cel_evaluator = CELEvaluator()
        self._llm_tiebreaker = llm_tiebreaker

    def route(
        self,
        current_node: str,
        flow_graph: FlowGraph,
        context: RunContext,
    ) -> RoutingResult:
        """Route from current node to next step.

        Implements the deterministic-first routing strategy:
        1. Get adjacent edges from graph
        2. Filter by exit conditions (microloop termination)
        3. Filter by CEL conditions
        4. Decision: 0 -> terminate, 1 -> deterministic, >1 -> LLM tiebreak

        Args:
            current_node: The ID of the current node.
            flow_graph: The flow graph defining valid transitions.
            context: Routing context with step output and flow state.

        Returns:
            RoutingResult with selected edge and full audit trail.
        """
        import time

        start_time = time.time()

        elimination_log: List[Dict[str, Any]] = []

        # Step 1: Get candidate edges from adjacency only
        candidates = self.get_adjacent_edges(current_node, flow_graph)
        edges_considered = len(candidates)

        if not candidates:
            # No outgoing edges = flow complete
            elapsed_ms = (time.time() - start_time) * 1000
            return RoutingResult(
                edge=None,
                method="no_candidates",
                terminate=True,
                needs_human=False,
                explanation=self._build_explanation(
                    decision="Flow complete - no outgoing edges",
                    candidates_evaluated=0,
                    elimination_log=elimination_log,
                    selected_edge="",
                    method="no_candidates",
                    edges_considered=edges_considered,
                    time_ms=elapsed_ms,
                ),
            )

        # Step 2: Apply exit conditions (microloop termination)
        candidates, exit_eliminations = self.filter_exit_conditions(
            candidates, context, flow_graph, current_node
        )
        elimination_log.extend(exit_eliminations)

        # Step 3: Apply CEL/condition evaluation
        candidates, cel_eliminations = self.filter_conditions(candidates, context, current_node)
        elimination_log.extend(cel_eliminations)

        # Step 4: Decision logic
        elapsed_ms = (time.time() - start_time) * 1000

        if len(candidates) == 0:
            # No valid edges after filtering
            return RoutingResult(
                edge=None,
                method="no_candidates",
                terminate=True,
                needs_human=True,
                explanation=self._build_explanation(
                    decision="No valid edges after condition evaluation",
                    candidates_evaluated=edges_considered,
                    elimination_log=elimination_log,
                    selected_edge="",
                    method="no_candidates",
                    edges_considered=edges_considered,
                    time_ms=elapsed_ms,
                ),
            )

        elif len(candidates) == 1:
            # Single valid edge - deterministic
            edge = candidates[0]
            return RoutingResult(
                edge=edge,
                method="deterministic",
                terminate=False,
                needs_human=False,
                explanation=self._build_explanation(
                    decision=f"Single valid edge: {edge.edge_id}",
                    candidates_evaluated=edges_considered,
                    elimination_log=elimination_log,
                    selected_edge=edge.edge_id,
                    method="deterministic",
                    edges_considered=edges_considered,
                    time_ms=elapsed_ms,
                ),
            )

        else:
            # Multiple valid edges - need tiebreaker
            return self.llm_tiebreak(
                candidates, context, elimination_log, edges_considered, start_time
            )

    def get_adjacent_edges(self, node_id: str, flow_graph: FlowGraph) -> List[Edge]:
        """Get all edges originating from a node.

        Args:
            node_id: The source node ID.
            flow_graph: The flow graph.

        Returns:
            List of edges originating from the node, sorted by priority.
        """
        edges = flow_graph.get_outgoing_edges(node_id)
        # Sort by priority (higher first) for deterministic ordering
        return sorted(edges, key=lambda e: (-e.priority, e.edge_id))

    def filter_exit_conditions(
        self,
        candidates: List[Edge],
        context: RunContext,
        flow_graph: FlowGraph,
        current_node: str,
    ) -> Tuple[List[Edge], List[Dict[str, Any]]]:
        """Apply exit conditions to filter candidates.

        Checks for microloop termination conditions:
        - Status == VERIFIED
        - max_iterations reached
        - can_further_iteration_help == false

        Args:
            candidates: List of candidate edges.
            context: Routing context.
            flow_graph: The flow graph.
            current_node: Current node ID.

        Returns:
            Tuple of (remaining_candidates, elimination_log).
        """
        elimination_log: List[Dict[str, Any]] = []

        node_config = flow_graph.get_node(current_node)
        iteration_count = context.iteration_counts.get(current_node, 0)
        max_iterations = (
            node_config.max_iterations
            if node_config and node_config.max_iterations
            else context.max_iterations
        )

        status = context.get("status", "")
        can_help = context.get("can_further_iteration_help", True)

        # Check exit conditions
        exit_triggered = False
        exit_reason = ""

        if status.upper() == "VERIFIED":
            exit_triggered = True
            exit_reason = "status=VERIFIED"
        elif iteration_count >= max_iterations:
            exit_triggered = True
            exit_reason = f"max_iterations={max_iterations}"
        elif can_help is False or (
            isinstance(can_help, str) and can_help.lower() in ("no", "false")
        ):
            exit_triggered = True
            exit_reason = "can_further_iteration_help=false"

        if exit_triggered:
            # Filter out loop edges when exit condition is met
            remaining = []
            for edge in candidates:
                if edge.edge_type == "loop":
                    elimination_log.append(
                        {
                            "edge_id": edge.edge_id,
                            "reason": f"Exit condition met: {exit_reason}",
                            "stage": "condition",
                        }
                    )
                else:
                    remaining.append(edge)
            return remaining, elimination_log

        return candidates, elimination_log

    def filter_conditions(
        self,
        candidates: List[Edge],
        context: RunContext,
        current_node: str,
    ) -> Tuple[List[Edge], List[Dict[str, Any]]]:
        """Apply CEL/condition evaluation to filter candidates.

        Args:
            candidates: List of candidate edges.
            context: Routing context.
            current_node: The current node ID (for iteration count lookup).

        Returns:
            Tuple of (remaining_candidates, elimination_log).
        """
        elimination_log: List[Dict[str, Any]] = []
        remaining = []

        # Build evaluation context from RunContext
        eval_context = {
            "status": context.get("status", ""),
            "can_further_iteration_help": context.get("can_further_iteration_help", True),
            "iteration_count": context.iteration_counts.get(current_node, 0),
            "run_id": context.run_id,
            "flow_key": context.flow_key,
            **context.step_output,
            **context.annotations,
        }

        for edge in candidates:
            if edge.condition is None:
                # No condition = always valid
                remaining.append(edge)
                continue

            result, error = self._cel_evaluator.evaluate_condition(edge.condition, eval_context)

            if result:
                remaining.append(edge)
            else:
                elimination_log.append(
                    {
                        "edge_id": edge.edge_id,
                        "reason": error or "Condition evaluated to false",
                        "stage": "condition",
                    }
                )

        return remaining, elimination_log

    def llm_tiebreak(
        self,
        candidates: List[Edge],
        context: RunContext,
        elimination_log: List[Dict[str, Any]],
        edges_considered: int,
        start_time: float,
    ) -> RoutingResult:
        """Use LLM to break tie between multiple valid edges.

        Args:
            candidates: List of valid candidate edges (>1).
            context: Routing context.
            elimination_log: Accumulated elimination log.
            edges_considered: Total edges initially considered.
            start_time: Start time for metrics.

        Returns:
            RoutingResult with selected edge and LLM reasoning.
        """
        import time

        if self._llm_tiebreaker:
            try:
                target_id, reasoning = self._llm_tiebreaker(candidates, context)

                # Validate the choice
                valid_targets = {e.to_node: e for e in candidates}
                selected_edge = valid_targets.get(target_id)

                if selected_edge is None:
                    logger.warning(
                        "LLM returned invalid target %s, using priority fallback", target_id
                    )
                    selected_edge = candidates[0]  # Already sorted by priority
                    reasoning = "LLM returned invalid target, using priority fallback"

                # Log eliminated edges
                for edge in candidates:
                    if edge.edge_id != selected_edge.edge_id:
                        elimination_log.append(
                            {
                                "edge_id": edge.edge_id,
                                "reason": "Not selected by LLM tiebreaker",
                                "stage": "llm_tiebreak",
                            }
                        )

                elapsed_ms = (time.time() - start_time) * 1000
                return RoutingResult(
                    edge=selected_edge,
                    method="llm_tiebreak",
                    terminate=False,
                    needs_human=False,
                    explanation=self._build_explanation(
                        decision=f"LLM selected: {selected_edge.edge_id}",
                        candidates_evaluated=edges_considered,
                        elimination_log=elimination_log,
                        selected_edge=selected_edge.edge_id,
                        method="llm_tiebreak",
                        llm_reasoning=reasoning,
                        edges_considered=edges_considered,
                        time_ms=elapsed_ms,
                    ),
                )

            except Exception as e:
                logger.warning("LLM tiebreaker failed: %s", e)
                # Fall through to priority-based fallback

        # Priority-based fallback (no LLM)
        selected_edge = candidates[0]  # Already sorted by priority
        for edge in candidates[1:]:
            elimination_log.append(
                {
                    "edge_id": edge.edge_id,
                    "reason": f"Lower priority than {selected_edge.edge_id}",
                    "stage": "priority",
                }
            )

        elapsed_ms = (time.time() - start_time) * 1000
        return RoutingResult(
            edge=selected_edge,
            method="deterministic",  # Priority-based is still deterministic
            terminate=False,
            needs_human=True,  # Flag for review since we didn't use LLM
            explanation=self._build_explanation(
                decision=f"Priority fallback: {selected_edge.edge_id}",
                candidates_evaluated=edges_considered,
                elimination_log=elimination_log,
                selected_edge=selected_edge.edge_id,
                method="deterministic",
                edges_considered=edges_considered,
                time_ms=elapsed_ms,
            ),
        )

    def _build_explanation(
        self,
        decision: str,
        candidates_evaluated: int,
        elimination_log: List[Dict[str, Any]],
        selected_edge: str,
        method: str,
        edges_considered: int,
        time_ms: float,
        llm_reasoning: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Build structured explanation for audit trail.

        Follows the WP4 routing_explanation.schema.json format.

        Returns:
            Dict matching routing_explanation.schema.json.
        """
        explanation: Dict[str, Any] = {
            "decision": decision,
            "candidates_evaluated": candidates_evaluated,
            "elimination_log": elimination_log,
            "selected_edge": selected_edge,
            "method": method,
            "metrics": {
                "edges_considered": edges_considered,
                "time_ms": round(time_ms, 2),
            },
        }

        if llm_reasoning:
            explanation["llm_reasoning"] = llm_reasoning

        return explanation


# =============================================================================
# Integration: Store Routing Audit Trail
# =============================================================================


def store_routing_audit(
    envelope: Any,  # HandoffEnvelope
    routing_result: RoutingResult,
) -> None:
    """Store routing explanation on the handoff envelope.

    This function updates the envelope with the routing audit trail
    for persistence and later analysis.

    Args:
        envelope: The HandoffEnvelope to update.
        routing_result: The routing result with explanation.
    """
    if routing_result.explanation:
        envelope.routing_audit = routing_result.explanation


def emit_routing_event(
    run_id: str,
    flow_key: str,
    step_id: str,
    routing_result: RoutingResult,
    append_event_fn: Optional[Callable] = None,
) -> None:
    """Emit a routing decision event to the events table.

    This function creates a route_decision event that can be ingested
    by the DuckDB projection for UI rendering.

    Args:
        run_id: The run identifier.
        flow_key: The flow key.
        step_id: The step that produced the routing decision.
        routing_result: The routing result with explanation.
        append_event_fn: Optional function to append events (for testing).
    """
    from datetime import datetime, timezone

    if append_event_fn is None:
        from .storage import append_event
        from .types import RunEvent

        append_event_fn = append_event

        event = RunEvent(
            run_id=run_id,
            ts=datetime.now(timezone.utc),
            kind="route_decision",
            flow_key=flow_key,
            step_id=step_id,
            payload={
                "method": routing_result.method,
                "selected_edge": routing_result.edge.edge_id if routing_result.edge else "",
                "target_node": routing_result.edge.to_node if routing_result.edge else "",
                "terminate": routing_result.terminate,
                "needs_human": routing_result.needs_human,
                "explanation": routing_result.explanation,
            },
        )
        append_event_fn(run_id, event)


# =============================================================================
# route_from_step: Primary Routing Entry Point
# =============================================================================


@dataclass
class StepOutputData:
    """Normalized step output for routing decisions.

    Extracts routing-relevant fields from step execution output.

    Attributes:
        status: The step's execution status (e.g., 'VERIFIED', 'UNVERIFIED').
        can_further_iteration_help: Critic's judgment about iteration viability.
        next_step_id: Explicit next step if specified by the step.
        proposed_action: Optional routing hint from step (PROCEED, RERUN, BOUNCE).
        custom_fields: Additional fields from the step output.
    """

    status: str = "UNKNOWN"
    can_further_iteration_help: Optional[bool] = None
    next_step_id: Optional[str] = None
    proposed_action: Optional[str] = None
    custom_fields: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StepOutputData":
        """Create StepOutputData from a dictionary (handoff data)."""
        # Handle can_further_iteration_help which may be bool or string
        can_help = data.get("can_further_iteration_help")
        if isinstance(can_help, str):
            can_help = can_help.lower() in ("yes", "true", "1")

        return cls(
            status=data.get("status", "UNKNOWN"),
            can_further_iteration_help=can_help,
            next_step_id=data.get("next_step_id"),
            proposed_action=data.get("proposed_action"),
            custom_fields={
                k: v
                for k, v in data.items()
                if k
                not in ("status", "can_further_iteration_help", "next_step_id", "proposed_action")
            },
        )


@dataclass
class RoutingContext:
    """Context for routing decisions during flow execution.

    Provides the execution context needed to make routing decisions,
    including run identity, iteration tracking, and flow state.

    Attributes:
        run_id: The unique run identifier.
        flow_key: The flow being executed.
        current_node: The current node/step ID.
        iteration_counts: Map of node_id to iteration count for microloop tracking.
        max_iterations: Safety fuse for microloops (not steering - use stall detection).
        annotations: Additional context data (e.g., from previous steps).
    """

    run_id: str
    flow_key: str
    current_node: str
    iteration_counts: Dict[str, int] = field(default_factory=dict)
    max_iterations: int = 50  # Safety fuse, use stall detection for steering
    annotations: Dict[str, Any] = field(default_factory=dict)


def route_from_step(
    flow_graph: FlowGraph,
    current_node: str,
    step_output: Dict[str, Any],
    context: RoutingContext,
    llm_tiebreaker: Optional[Callable[[List[Edge], RoutingContext], Tuple[str, str]]] = None,
) -> RoutingResult:
    """Route from current step to next step using bounded, auditable routing.

    This is the primary entry point for stepwise routing. Implements the
    deterministic-first routing strategy:

    1. **Deterministic routing** (cheap, auditable):
       - Single outgoing edge: always selected
       - Edge with condition=true: unconditional edge
       - Exit conditions: VERIFIED status, max_iterations, can_further_iteration_help=false

    2. **CEL evaluation** (cheap, auditable):
       - Evaluate edge conditions against step context
       - Example: `status == "VERIFIED"`, `can_further_iteration_help == false`

    3. **LLM tiebreaker** (expensive, only when needed):
       - Only invoked when multiple edges pass deterministic checks
       - Generates structured reasoning for audit trail

    Args:
        flow_graph: The flow graph defining valid transitions.
        current_node: The ID of the current node/step.
        step_output: Output from the step execution (handoff data).
        context: Routing context with run identity and flow state.
        llm_tiebreaker: Optional callable for LLM tie-breaking.
            Takes (valid_edges, context) and returns (target_node_id, reasoning).

    Returns:
        RoutingResult with:
        - edge: The selected edge (or None if flow terminates)
        - method: How decision was made (deterministic, llm_tiebreak, no_candidates)
        - terminate: Whether flow should end
        - needs_human: Whether human review is recommended
        - explanation: WP4-compliant structured audit trail

    Example:
        >>> graph = FlowGraph.from_dict(flow_spec)
        >>> context = RoutingContext(
        ...     run_id="run-123",
        ...     flow_key="build",
        ...     current_node="code-implementer",
        ... )
        >>> result = route_from_step(
        ...     flow_graph=graph,
        ...     current_node="code-implementer",
        ...     step_output={"status": "VERIFIED"},
        ...     context=context,
        ... )
        >>> if not result.terminate:
        ...     execute_step(result.edge.to_node)

    Note:
        The result.explanation field contains a WP4-compliant dictionary
        matching routing_explanation.schema.json for audit trail storage.
    """
    # Build run context for StepRouter
    run_ctx = RunContext(
        run_id=context.run_id,
        flow_key=context.flow_key,
        step_output=step_output,
        iteration_counts=context.iteration_counts,
        max_iterations=context.max_iterations,
        annotations=context.annotations,
    )

    # Adapt llm_tiebreaker signature if provided
    adapted_tiebreaker = None
    if llm_tiebreaker:

        def adapted_tiebreaker(edges: List[Edge], ctx: RunContext) -> Tuple[str, str]:
            # Convert RunContext back to RoutingContext for caller's tiebreaker
            routing_ctx = RoutingContext(
                run_id=ctx.run_id,
                flow_key=ctx.flow_key,
                current_node=current_node,
                iteration_counts=ctx.iteration_counts,
                max_iterations=ctx.max_iterations,
                annotations=ctx.annotations,
            )
            return llm_tiebreaker(edges, routing_ctx)

    # Create router and route
    router = StepRouter(llm_tiebreaker=adapted_tiebreaker)
    result = router.route(current_node, flow_graph, run_ctx)

    return result


def convert_to_wp4_explanation(
    routing_result: RoutingResult,
) -> Dict[str, Any]:
    """Convert RoutingResult explanation to WP4RoutingExplanation format.

    This function normalizes the internal explanation format to match
    the WP4 routing_explanation.schema.json for consistent audit trails.

    Args:
        routing_result: The routing result with explanation.

    Returns:
        Dictionary matching WP4RoutingExplanation schema.
    """
    from swarm.runtime.types import (
        WP4EliminationEntry,
        WP4RoutingExplanation,
        WP4RoutingMetrics,
        wp4_routing_explanation_to_dict,
    )

    if not routing_result.explanation:
        # Return minimal explanation
        return wp4_routing_explanation_to_dict(
            WP4RoutingExplanation(
                decision="No explanation available",
                method=routing_result.method,
                selected_edge=routing_result.edge.edge_id if routing_result.edge else "",
                candidates_evaluated=0,
            )
        )

    explanation = routing_result.explanation

    # Convert elimination log entries
    elimination_log = [
        WP4EliminationEntry(
            edge_id=entry.get("edge_id", ""),
            reason=entry.get("reason", ""),
            stage=entry.get("stage", "condition"),
        )
        for entry in explanation.get("elimination_log", [])
    ]

    # Build metrics
    metrics_data = explanation.get("metrics", {})
    metrics = WP4RoutingMetrics(
        edges_considered=metrics_data.get("edges_considered", 0),
        time_ms=metrics_data.get("time_ms", 0.0),
        llm_tokens_used=metrics_data.get("llm_tokens_used", 0),
    )

    wp4_explanation = WP4RoutingExplanation(
        decision=explanation.get("decision", ""),
        method=explanation.get("method", routing_result.method),
        selected_edge=explanation.get("selected_edge", ""),
        candidates_evaluated=explanation.get("candidates_evaluated", 0),
        elimination_log=elimination_log,
        llm_reasoning=explanation.get("llm_reasoning"),
        metrics=metrics,
    )

    return wp4_routing_explanation_to_dict(wp4_explanation)


def attach_routing_audit(
    envelope: Any,  # HandoffEnvelope
    routing_result: RoutingResult,
    use_wp4_format: bool = True,
) -> None:
    """Attach routing explanation to a HandoffEnvelope for audit trail.

    This function updates the envelope's routing_audit field with
    the structured explanation from the routing decision.

    Args:
        envelope: The HandoffEnvelope to update.
        routing_result: The routing result with explanation.
        use_wp4_format: If True, convert to WP4RoutingExplanation format.
            If False, use the raw explanation dictionary.

    Example:
        >>> result = route_from_step(graph, node, output, context)
        >>> attach_routing_audit(envelope, result)
        >>> # envelope.routing_audit now contains the structured explanation
    """
    if routing_result.explanation:
        if use_wp4_format:
            envelope.routing_audit = convert_to_wp4_explanation(routing_result)
        else:
            envelope.routing_audit = routing_result.explanation
