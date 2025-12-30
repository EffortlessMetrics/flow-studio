"""
spec_bridge.py - Bridge between pack JSON specs and orchestrator FlowDefinition.

This module converts FlowSpecData (from pack registry JSON) to FlowDefinition
(used by the orchestrator). This enables the orchestrator to consume the new
JSON-based pack specs while maintaining backwards compatibility with YAML.

The key transformation is converting the graph-based JSON format (nodes + edges)
to the step-based FlowDefinition format (steps with routing).

Usage:
    from swarm.runtime.spec_bridge import (
        flow_spec_to_definition,
        load_flow_from_pack,
    )

    # Convert a loaded FlowSpecData
    flow_def = flow_spec_to_definition(flow_spec_data, flow_index=3)

    # Or load directly from pack
    flow_def = load_flow_from_pack("build", repo_root)
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from swarm.config.flow_registry import (
    EngineProfile,
    FlowDefinition,
    StepDefinition,
    StepRouting,
    TeachingNotes,
)
from swarm.config.pack_registry import (
    FlowEdge,
    FlowNode,
    FlowSpecData,
    PackRegistry,
)

logger = logging.getLogger(__name__)


# Flow key to index mapping (standard SDLC order)
FLOW_INDEX_MAP = {
    "signal": 1,
    "plan": 2,
    "build": 3,
    "gate": 4,
    "deploy": 5,
    "wisdom": 6,
    "review": 7,  # Optional review flow
}


@dataclass
class EdgeAnalysis:
    """Analysis of edges for a single node to determine routing."""

    node_id: str
    outgoing_edges: List[FlowEdge]
    loop_edge: Optional[FlowEdge] = None
    exit_edge: Optional[FlowEdge] = None
    sequence_edges: List[FlowEdge] = None

    def __post_init__(self):
        if self.sequence_edges is None:
            self.sequence_edges = []


def analyze_node_edges(node_id: str, edges: List[FlowEdge]) -> EdgeAnalysis:
    """Analyze outgoing edges from a node to determine routing pattern.

    Args:
        node_id: The node to analyze.
        edges: All edges in the flow.

    Returns:
        EdgeAnalysis with categorized edges.
    """
    outgoing = [e for e in edges if e.from_node == node_id]

    loop_edge = None
    exit_edge = None
    sequence_edges = []

    for edge in outgoing:
        if edge.edge_type == "loop":
            loop_edge = edge
        elif edge.edge_type == "branch":
            # Branch edges are handled separately
            sequence_edges.append(edge)
        else:  # sequence
            # Check if this is an exit edge (has condition checking for VERIFIED)
            if edge.condition and "VERIFIED" in str(edge.condition):
                exit_edge = edge
            else:
                sequence_edges.append(edge)

    return EdgeAnalysis(
        node_id=node_id,
        outgoing_edges=outgoing,
        loop_edge=loop_edge,
        exit_edge=exit_edge,
        sequence_edges=sequence_edges,
    )


def infer_step_order(nodes: List[FlowNode], edges: List[FlowEdge]) -> List[str]:
    """Infer step execution order from graph topology.

    Uses topological sort on sequence edges to determine the natural
    execution order. Loop edges are not considered for ordering.

    Args:
        nodes: List of flow nodes.
        edges: List of flow edges.

    Returns:
        Ordered list of node IDs.
    """
    # Build adjacency for sequence edges only
    node_ids = {n.node_id for n in nodes}
    in_degree: Dict[str, int] = {n: 0 for n in node_ids}
    adjacency: Dict[str, List[str]] = {n: [] for n in node_ids}

    for edge in edges:
        # Only consider sequence edges for ordering
        if edge.edge_type == "sequence":
            if edge.to_node in in_degree:
                in_degree[edge.to_node] += 1
            if edge.from_node in adjacency:
                adjacency[edge.from_node].append(edge.to_node)

    # Find nodes with no incoming edges (start nodes)
    queue = [n for n, deg in in_degree.items() if deg == 0]
    result = []

    while queue:
        # Sort for deterministic ordering
        queue.sort()
        node = queue.pop(0)
        result.append(node)

        for neighbor in adjacency.get(node, []):
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    # If we couldn't order all nodes, fall back to node list order
    if len(result) != len(node_ids):
        logger.warning(
            "Could not fully order nodes via topology, using definition order. "
            "Ordered: %d, Total: %d",
            len(result),
            len(node_ids),
        )
        # Add any missing nodes in their original order
        for node in nodes:
            if node.node_id not in result:
                result.append(node.node_id)

    return result


def node_to_routing(
    node: FlowNode,
    edge_analysis: EdgeAnalysis,
    step_order: List[str],
) -> StepRouting:
    """Convert node edges to StepRouting configuration.

    Determines the routing pattern (linear, microloop, branch) based on
    the edge types and conditions.

    Args:
        node: The flow node.
        edge_analysis: Analyzed edges for this node.
        step_order: Ordered list of step IDs.

    Returns:
        StepRouting configuration.
    """
    # Determine routing kind based on edges
    if edge_analysis.loop_edge:
        # This is a microloop pattern
        loop_target = edge_analysis.loop_edge.to_node

        # Find the exit edge (sequence edge after loop)
        next_step = None
        if edge_analysis.exit_edge:
            next_step = edge_analysis.exit_edge.to_node
        elif edge_analysis.sequence_edges:
            # Use highest priority sequence edge
            seq_edges = sorted(edge_analysis.sequence_edges, key=lambda e: -e.priority)
            next_step = seq_edges[0].to_node if seq_edges else None

        # Extract exit condition from loop edge
        loop_condition_field = "status"
        loop_success_values = ("VERIFIED",)

        if edge_analysis.loop_edge.condition:
            cond = edge_analysis.loop_edge.condition
            if hasattr(cond, "expression"):
                expr = cond.expression
                # Parse simple expressions like "status != 'VERIFIED'"
                if "VERIFIED" in expr:
                    loop_success_values = ("VERIFIED",)

        return StepRouting(
            kind="microloop",
            next=next_step,
            loop_target=loop_target,
            loop_condition_field=loop_condition_field,
            loop_success_values=loop_success_values,
            max_iterations=50,  # Safety fuse
        )

    elif len(edge_analysis.sequence_edges) > 1:
        # Multiple sequence edges = branch
        branches = {}
        for edge in edge_analysis.sequence_edges:
            if edge.condition:
                # Use condition as branch key
                cond_key = str(edge.condition) if edge.condition else "default"
                branches[cond_key] = edge.to_node

        return StepRouting(
            kind="branch",
            branches=branches,
        )

    else:
        # Linear routing
        next_step = None
        if edge_analysis.sequence_edges:
            next_step = edge_analysis.sequence_edges[0].to_node
        else:
            # Find next in order
            try:
                current_idx = step_order.index(node.node_id)
                if current_idx + 1 < len(step_order):
                    next_step = step_order[current_idx + 1]
            except ValueError:
                pass

        return StepRouting(
            kind="linear",
            next=next_step,
        )


def node_to_step(
    node: FlowNode,
    index: int,
    routing: StepRouting,
) -> StepDefinition:
    """Convert FlowNode to StepDefinition.

    Args:
        node: The flow node to convert.
        index: 1-based step index.
        routing: Pre-computed routing configuration.

    Returns:
        StepDefinition for the orchestrator.
    """
    # Use template_id as the agent key (station -> agent mapping)
    agent_key = node.template_id or node.node_id

    # Extract role from params or use template_id
    role = node.params.get("role", "") if node.params else ""
    if not role:
        role = f"Execute {agent_key}"

    # Extract teaching notes from params if present
    teaching_notes = None
    if node.params:
        tn_data = node.params.get("teaching_notes", {})
        if tn_data:
            teaching_notes = TeachingNotes(
                inputs=tuple(tn_data.get("inputs", [])),
                outputs=tuple(tn_data.get("outputs", [])),
                emphasizes=tuple(tn_data.get("emphasizes", [])),
                constraints=tuple(tn_data.get("constraints", [])),
            )

    # Extract engine profile from overrides if present
    engine_profile = None
    if node.overrides:
        ep_data = node.overrides.get("engine_profile", {})
        if ep_data:
            engine_profile = EngineProfile(
                engine=ep_data.get("engine", "claude-step"),
                mode=ep_data.get("mode", "stub"),
                model=ep_data.get("model"),
                timeout_ms=ep_data.get("timeout_ms", 300000),
            )

    return StepDefinition(
        id=node.node_id,
        index=index,
        agents=(agent_key,),
        role=role,
        teaching_notes=teaching_notes,
        routing=routing,
        engine_profile=engine_profile,
    )


def flow_spec_to_definition(
    spec: FlowSpecData,
    flow_index: Optional[int] = None,
) -> FlowDefinition:
    """Convert FlowSpecData (pack JSON) to FlowDefinition (orchestrator).

    This is the main bridge function that transforms the graph-based JSON
    spec format into the step-based format used by the orchestrator.

    Args:
        spec: The FlowSpecData from pack registry.
        flow_index: Optional explicit flow index. If None, inferred from spec.id.

    Returns:
        FlowDefinition suitable for the orchestrator.

    Example:
        >>> from swarm.config.pack_registry import PackRegistry
        >>> registry = PackRegistry(repo_root)
        >>> registry.load()
        >>> spec = registry.get_flow("build")
        >>> flow_def = flow_spec_to_definition(spec)
    """
    # Determine flow index
    if flow_index is None:
        flow_index = FLOW_INDEX_MAP.get(spec.id, 99)

    # Get step order from topology
    step_order = infer_step_order(spec.nodes, spec.edges)

    # Build node lookup
    node_lookup = {n.node_id: n for n in spec.nodes}

    # Convert nodes to steps
    steps: List[StepDefinition] = []
    for idx, node_id in enumerate(step_order, start=1):
        node = node_lookup.get(node_id)
        if node is None:
            logger.warning("Node %s in order but not in nodes list", node_id)
            continue

        # Analyze edges for this node
        edge_analysis = analyze_node_edges(node_id, spec.edges)

        # Convert to routing
        routing = node_to_routing(node, edge_analysis, step_order)

        # Convert to step
        step = node_to_step(node, idx, routing)
        steps.append(step)

    # Extract cross-cutting from policy
    cross_cutting = ()
    if spec.policy and hasattr(spec.policy, "suggested_sidequests"):
        cross_cutting = tuple(spec.policy.suggested_sidequests or [])
    elif isinstance(spec.policy, dict):
        cross_cutting = tuple(spec.policy.get("suggested_sidequests", []))

    # Build short title from name
    short_title = spec.name.split("→")[0].strip() if "→" in spec.name else spec.name

    return FlowDefinition(
        key=spec.id,
        index=flow_index,
        title=spec.name,
        short_title=short_title,
        description=spec.description,
        steps=tuple(steps),
        cross_cutting=cross_cutting,
        is_sdlc=spec.id in FLOW_INDEX_MAP,
    )


def load_flow_from_pack(
    flow_key: str,
    repo_root: Path,
) -> Optional[FlowDefinition]:
    """Load a flow definition from the pack registry.

    Convenience function that loads the pack, retrieves the flow spec,
    and converts it to FlowDefinition.

    Args:
        flow_key: The flow to load (e.g., "build", "signal").
        repo_root: Repository root path.

    Returns:
        FlowDefinition if found, None otherwise.

    Example:
        >>> flow_def = load_flow_from_pack("build", Path.cwd())
        >>> print(flow_def.title)
        'Plan → Draft'
    """
    try:
        registry = PackRegistry(repo_root)
        registry.load()

        spec = registry.get_flow(flow_key)
        if spec is None:
            logger.debug("Flow %s not found in pack registry", flow_key)
            return None

        return flow_spec_to_definition(spec)

    except Exception as e:
        logger.warning("Failed to load flow %s from pack: %s", flow_key, e)
        return None


def load_flow_from_json(
    json_path: Path,
    flow_index: Optional[int] = None,
) -> Optional[FlowDefinition]:
    """Load a flow definition directly from a JSON file.

    Args:
        json_path: Path to the flow JSON file.
        flow_index: Optional explicit flow index.

    Returns:
        FlowDefinition if successful, None otherwise.
    """
    try:
        with open(json_path) as f:
            data = json.load(f)

        # Parse nodes
        nodes = []
        for node_data in data.get("nodes", []):
            nodes.append(
                FlowNode(
                    node_id=node_data.get("node_id", ""),
                    template_id=node_data.get("template_id", ""),
                    params=node_data.get("params", {}),
                    overrides=node_data.get("overrides", {}),
                )
            )

        # Parse edges
        edges = []
        for edge_data in data.get("edges", []):
            edges.append(
                FlowEdge(
                    edge_id=edge_data.get("edge_id", ""),
                    from_node=edge_data.get("from", ""),
                    to_node=edge_data.get("to", ""),
                    edge_type=edge_data.get("type", "sequence"),
                    priority=edge_data.get("priority", 50),
                    condition=edge_data.get("condition"),
                )
            )

        # Create FlowSpecData
        spec = FlowSpecData(
            id=data.get("id", json_path.stem),
            name=data.get("name", ""),
            description=data.get("description", ""),
            version=data.get("version", 1),
            nodes=nodes,
            edges=edges,
            policy=data.get("policy", {}),
            pack_origin="file",
        )

        return flow_spec_to_definition(spec, flow_index)

    except Exception as e:
        logger.warning("Failed to load flow from %s: %s", json_path, e)
        return None


class PackFlowRegistry:
    """Flow registry that loads from pack JSON specs.

    Drop-in replacement for FlowRegistry that uses the new pack system
    instead of the YAML configuration.

    Usage:
        registry = PackFlowRegistry(repo_root)
        flow_def = registry.get_flow("build")
    """

    def __init__(self, repo_root: Path):
        """Initialize the registry.

        Args:
            repo_root: Repository root path.
        """
        self._repo_root = repo_root
        self._pack_registry = PackRegistry(repo_root)
        self._pack_registry.load()
        self._flow_cache: Dict[str, FlowDefinition] = {}
        self._agent_index: Dict[str, List[Tuple[str, Optional[str], int, int]]] = {}
        self._loaded = False

    def _ensure_loaded(self) -> None:
        """Lazily load all flows and build agent index."""
        if self._loaded:
            return

        for flow_key in FLOW_INDEX_MAP:
            flow_def = self._load_flow(flow_key)
            if flow_def:
                self._index_agents(flow_def)

        self._loaded = True

    def _load_flow(self, flow_key: str) -> Optional[FlowDefinition]:
        """Load and cache a flow definition."""
        if flow_key in self._flow_cache:
            return self._flow_cache[flow_key]

        spec = self._pack_registry.get_flow(flow_key)
        if spec is None:
            return None

        flow_def = flow_spec_to_definition(spec)
        self._flow_cache[flow_key] = flow_def
        return flow_def

    def _index_agents(self, flow_def: FlowDefinition) -> None:
        """Build agent reverse index for a flow."""
        for step in flow_def.steps:
            for agent in step.agents:
                if agent not in self._agent_index:
                    self._agent_index[agent] = []
                self._agent_index[agent].append((flow_def.key, step.id, flow_def.index, step.index))

        for agent in flow_def.cross_cutting:
            if agent not in self._agent_index:
                self._agent_index[agent] = []
            self._agent_index[agent].append((flow_def.key, None, flow_def.index, 0))

    @property
    def flow_order(self) -> List[str]:
        """Return list of flow keys in SDLC order."""
        self._ensure_loaded()
        return sorted(self._flow_cache.keys(), key=lambda k: FLOW_INDEX_MAP.get(k, 99))

    @property
    def flows(self) -> List[FlowDefinition]:
        """Return all flow definitions in order."""
        self._ensure_loaded()
        return [self._flow_cache[k] for k in self.flow_order if k in self._flow_cache]

    def get_flow(self, key: str) -> Optional[FlowDefinition]:
        """Get flow by key."""
        return self._load_flow(key)

    def get_index(self, key: str) -> int:
        """Get numeric index for flow key (1-6)."""
        return FLOW_INDEX_MAP.get(key, 99)

    def get_steps(self, flow_key: str) -> List[StepDefinition]:
        """Get steps for a flow."""
        flow = self.get_flow(flow_key)
        return list(flow.steps) if flow else []

    def get_step_index(self, flow_key: str, step_id: str) -> int:
        """Get 1-based step index within a flow."""
        flow = self.get_flow(flow_key)
        if not flow:
            return 0
        for step in flow.steps:
            if step.id == step_id:
                return step.index
        return 0

    def get_agent_positions(self, agent_key: str) -> List[Tuple[str, Optional[str], int, int]]:
        """Get all positions for an agent."""
        self._ensure_loaded()
        return self._agent_index.get(agent_key, [])


__all__ = [
    "flow_spec_to_definition",
    "load_flow_from_pack",
    "load_flow_from_json",
    "PackFlowRegistry",
    "FLOW_INDEX_MAP",
]
