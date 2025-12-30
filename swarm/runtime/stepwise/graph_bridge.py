"""
graph_bridge.py - Bridge between flow_registry FlowDefinition and router FlowGraph

This module provides conversion utilities to transform FlowDefinition objects
(from the flow_registry config layer) into FlowGraph objects (from the router
execution layer). This bridge enables the Navigator to work with flow definitions
loaded from YAML configuration while using the routing infrastructure designed
for graph-based execution.

The primary use case is stepwise orchestration: when the orchestrator loads a
FlowDefinition and needs to provide it to the NavigationOrchestrator for routing
decisions, this module performs the necessary translation.

Key Concepts:
- FlowDefinition: Config-layer representation of a flow with steps and metadata
- FlowGraph: Execution-layer representation with nodes, edges, and routing policy
- StepRouting: Per-step routing configuration (next, loop_target, max_iterations)

The conversion:
1. Creates a NodeConfig for each step in the flow
2. Creates sequence edges based on routing.next configuration
3. Creates loop edges based on routing.loop_target configuration
4. Assigns edge priorities (sequence=50, loop=40) for deterministic routing

Usage:
    from swarm.config.flow_registry import FlowRegistry
    from swarm.runtime.stepwise.graph_bridge import build_flow_graph_from_definition

    registry = FlowRegistry.instance()
    flow_def = registry.get_flow("build")
    flow_graph = build_flow_graph_from_definition(flow_def)
"""

from __future__ import annotations

from typing import Dict, List

from swarm.config.flow_registry import FlowDefinition
from swarm.runtime.router import Edge, FlowGraph, NodeConfig

__all__ = ["build_flow_graph_from_definition"]


def build_flow_graph_from_definition(flow_def: FlowDefinition) -> FlowGraph:
    """Build a FlowGraph from FlowDefinition for Navigator context.

    Converts the flow_registry FlowDefinition to the router.FlowGraph
    format that NavigationOrchestrator expects.

    This function creates a graph representation suitable for routing decisions:
    - Each step becomes a NodeConfig with its routing constraints
    - Sequence edges connect steps following routing.next
    - Loop edges enable microloop patterns via routing.loop_target

    Args:
        flow_def: The flow definition from flow_registry.

    Returns:
        FlowGraph suitable for Navigator routing.

    Example:
        >>> flow_def = FlowRegistry.instance().get_flow("build")
        >>> graph = build_flow_graph_from_definition(flow_def)
        >>> print(graph.graph_id)
        'Plan -> Draft'
        >>> print(len(graph.nodes))
        12
    """
    nodes: Dict[str, NodeConfig] = {}
    edges: List[Edge] = []

    for step in flow_def.steps:
        # Create node config
        node_config = NodeConfig(
            node_id=step.id,
            template_id=step.role or step.id,
            max_iterations=step.routing.max_iterations if step.routing else None,
        )
        nodes[step.id] = node_config

        # Create edges based on routing config
        if step.routing:
            # Add edge to next step
            if step.routing.next:
                edges.append(
                    Edge(
                        edge_id=f"{step.id}->{step.routing.next}",
                        from_node=step.id,
                        to_node=step.routing.next,
                        edge_type="sequence",
                        priority=50,
                    )
                )

            # Add loop edge if configured
            if step.routing.loop_target:
                edges.append(
                    Edge(
                        edge_id=f"{step.id}->{step.routing.loop_target}:loop",
                        from_node=step.id,
                        to_node=step.routing.loop_target,
                        edge_type="loop",
                        priority=40,
                    )
                )

    return FlowGraph(
        graph_id=flow_def.title or "flow",
        nodes=nodes,
        edges=edges,
        policy={"max_loop_iterations": 50},  # Safety fuse
    )
