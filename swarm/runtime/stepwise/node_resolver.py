"""
node_resolver.py - Node resolution for stepwise execution.

This module handles resolution of node IDs to executable contexts, supporting
both regular flow graph nodes and dynamically injected nodes (sidequests,
utility flows).

Key concepts:
- ResolvedNode: Unified representation for any executable node
- Injected nodes: Dynamically added during execution (take precedence)
- Sequential fallback: If no routing target, advance to next step

The resolver is the bridge between node IDs (strings) and executable
contexts (ResolvedNode with role, agents, routing config).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from swarm.config.flow_registry import FlowDefinition
    from swarm.runtime.types import RunState

    from .models import ResolvedNode

logger = logging.getLogger(__name__)


def resolve_node(
    node_id: str,
    flow_def: "FlowDefinition",
    run_state: "RunState",
) -> Optional["ResolvedNode"]:
    """Resolve a node_id to an executable ResolvedNode.

    This function handles both:
    1. Regular flow graph nodes (from FlowDefinition)
    2. Dynamically injected nodes (from run_state.injected_node_specs)

    Injected nodes take precedence - if a node_id exists in both
    the flow and as an injected node, the injected version is used.

    Args:
        node_id: The node ID to resolve.
        flow_def: The flow definition containing regular steps.
        run_state: RunState containing injected node specs.

    Returns:
        ResolvedNode if found, None otherwise.
    """
    # Import here to avoid circular imports
    from .models import ResolvedNode

    # First, check injected nodes (they take precedence)
    injected_spec = run_state.get_injected_node_spec(node_id)
    if injected_spec is not None:
        return ResolvedNode(
            node_id=node_id,
            step_id=node_id,
            role=injected_spec.station_id,
            agents=(injected_spec.agent_key or injected_spec.station_id,),
            index=-1,  # Injected nodes don't have a flow index
            is_injected=True,
            injected_spec=injected_spec,
            routing=None,
        )

    # Then check regular flow steps
    for step in flow_def.steps:
        if step.id == node_id:
            return ResolvedNode(
                node_id=node_id,
                step_id=step.id,
                role=step.role or step.id,
                agents=tuple(step.agents) if step.agents else (),
                index=step.index,
                is_injected=False,
                injected_spec=None,
                routing=step.routing,
            )

    # Node not found
    logger.warning("Could not resolve node_id: %s", node_id)
    return None


def get_next_node_id(
    current_node_id: str,
    nav_result_node: Optional[str],
    flow_def: "FlowDefinition",
    run_state: "RunState",
) -> Optional[str]:
    """Determine the next node_id to execute.

    Priority order:
    1. Navigator-provided next node (if valid)
    2. Resume from interruption stack (if sidequest complete)
    3. Sequential next step in flow
    4. None (flow complete)

    Args:
        current_node_id: The current node that just executed.
        nav_result_node: Navigator's suggested next node.
        flow_def: The flow definition.
        run_state: Current run state.

    Returns:
        Next node_id to execute, or None if flow is complete.
    """
    # If navigator provided a target, validate and use it
    if nav_result_node:
        resolved = resolve_node(nav_result_node, flow_def, run_state)
        if resolved is not None:
            return nav_result_node
        else:
            logger.warning(
                "Navigator target %s could not be resolved, falling back",
                nav_result_node,
            )

    # Check if we're resuming from a sidequest
    if run_state.peek_resume() is not None:
        # There's a resume point - sidequest handling will pop it
        # This is handled by check_and_handle_detour_completion in navigate()
        pass

    # For injected nodes, check if there's a next in sequence
    if current_node_id.startswith("sq-"):
        # This is a sidequest node - next node determined by sidequest cursor
        # The navigate() call handles this via check_and_handle_detour_completion
        return None

    # For regular nodes, find sequential next
    current_idx = None
    for i, step in enumerate(flow_def.steps):
        if step.id == current_node_id:
            current_idx = i
            break

    if current_idx is not None and current_idx + 1 < len(flow_def.steps):
        return flow_def.steps[current_idx + 1].id

    # No next step - flow complete
    return None


def find_step_index(step_id: str, flow_def: "FlowDefinition") -> Optional[int]:
    """Find the index of a step in the flow definition.

    Args:
        step_id: The step ID to find.
        flow_def: The flow definition.

    Returns:
        Step index if found, None otherwise.
    """
    for i, step in enumerate(flow_def.steps):
        if step.id == step_id:
            return i
    return None


__all__ = [
    "resolve_node",
    "get_next_node_id",
    "find_step_index",
]
