"""
bridge.py - Bridge between JSON FlowGraph specs and runtime FlowDefinition.

This module provides the glue between:
- Source of truth: JSON FlowGraph specs in swarm/specs/flows/*.json
- Runtime consumer: GeminiStepOrchestrator expecting FlowDefinition

The bridge:
1. Loads FlowGraph from JSON via SpecManager
2. Topologically sorts nodes based on edges
3. Converts nodes to StepDefinition-compatible format
4. Returns a FlowDefinition-compatible object

This enables "Graph IR is the map" - the JSON specs are the single runtime truth,
while maintaining backward compatibility with existing orchestrator code.

Usage:
    from swarm.runtime.spec_system.bridge import SpecBridge

    bridge = SpecBridge(repo_root=Path("."))
    flow_def = bridge.get_flow("signal")
    # flow_def is FlowDefinition-compatible
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class TeachingNotes:
    """Teaching notes for a step (mirrors flow_registry.TeachingNotes)."""

    inputs: Tuple[str, ...] = ()
    outputs: Tuple[str, ...] = ()
    emphasizes: Tuple[str, ...] = ()
    constraints: Tuple[str, ...] = ()


@dataclass
class StepRouting:
    """Step routing configuration (mirrors flow_registry.StepRouting)."""

    kind: str = "linear"
    next: Optional[str] = None
    loop_to: Optional[str] = None
    max_iterations: Optional[int] = None
    branch_options: Tuple[str, ...] = ()
    exit_on: Optional[str] = None


@dataclass
class EngineProfile:
    """Engine profile for step execution."""

    engine_id: Optional[str] = None
    mode: Optional[str] = None
    model: Optional[str] = None


@dataclass
class GraphStepDefinition:
    """A step definition derived from a FlowGraph node.

    Compatible with flow_registry.StepDefinition but sourced from JSON.
    """

    id: str
    index: int  # 1-based within flow
    agents: Tuple[str, ...]
    role: str
    objective: str = ""
    inputs: Tuple[str, ...] = ()
    outputs: Tuple[str, ...] = ()
    teaching_notes: Optional[TeachingNotes] = None
    routing: Optional[StepRouting] = None
    engine_profile: Optional[EngineProfile] = None
    teaching_note: Optional[str] = None
    teaching_highlight: bool = False


@dataclass
class GraphFlowDefinition:
    """A flow definition derived from a FlowGraph.

    Compatible with flow_registry.FlowDefinition but sourced from JSON.
    """

    key: str
    index: int
    title: str
    short_title: str
    description: str
    steps: Tuple[GraphStepDefinition, ...] = ()
    cross_cutting: Tuple[str, ...] = ()
    is_sdlc: bool = True
    # Graph-specific fields
    nodes: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    edges: List[Dict[str, Any]] = field(default_factory=list)
    entry_node: Optional[str] = None
    exit_nodes: Tuple[str, ...] = ()


class SpecBridge:
    """Bridge between JSON FlowGraph specs and runtime FlowDefinition.

    This class loads FlowGraph from swarm/specs/flows/*.json and converts
    them to FlowDefinition-compatible objects for the orchestrator.

    Usage:
        bridge = SpecBridge(repo_root=Path("."))
        flow_def = bridge.get_flow("signal")
    """

    def __init__(self, repo_root: Optional[Path] = None):
        """Initialize the spec bridge.

        Args:
            repo_root: Repository root path. Defaults to auto-detection.
        """
        if repo_root is None:
            repo_root = Path(__file__).resolve().parents[3]
        self._repo_root = repo_root
        self._specs_dir = repo_root / "swarm" / "specs" / "flows"
        self._cache: Dict[str, GraphFlowDefinition] = {}

        # Flow key to index mapping (SDLC order)
        self._flow_indices = {
            "signal": 1,
            "plan": 2,
            "build": 3,
            "gate": 4,
            "deploy": 5,
            "wisdom": 6,
        }

    def get_flow(self, flow_key: str, *, use_cache: bool = True) -> Optional[GraphFlowDefinition]:
        """Load a flow definition from JSON specs.

        Args:
            flow_key: Flow key (e.g., "signal", "build").
            use_cache: Whether to use cached result.

        Returns:
            GraphFlowDefinition if found, None otherwise.
        """
        if use_cache and flow_key in self._cache:
            return self._cache[flow_key]

        flow_path = self._specs_dir / f"{flow_key}.json"
        if not flow_path.exists():
            logger.warning("Flow spec not found: %s", flow_path)
            return None

        try:
            import json

            with open(flow_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            flow_def = self._convert_flow_graph(flow_key, data)
            if use_cache:
                self._cache[flow_key] = flow_def
            return flow_def

        except Exception as e:
            logger.error("Failed to load flow spec %s: %s", flow_key, e)
            return None

    def list_flows(self) -> List[str]:
        """List all available flow keys.

        Returns:
            List of flow keys found in specs directory.
        """
        flows = []
        if self._specs_dir.exists():
            for path in self._specs_dir.glob("*.json"):
                # Skip UI overlay files
                if not path.name.endswith(".ui.json"):
                    flows.append(path.stem)
        return sorted(flows, key=lambda k: self._flow_indices.get(k, 99))

    def _convert_flow_graph(self, flow_key: str, data: Dict[str, Any]) -> GraphFlowDefinition:
        """Convert a FlowGraph JSON to GraphFlowDefinition.

        Args:
            flow_key: Flow key (e.g., "signal").
            data: Raw FlowGraph JSON data.

        Returns:
            GraphFlowDefinition with steps in topological order.
        """
        nodes = data.get("nodes", [])
        edges = data.get("edges", [])

        # Build node lookup
        node_map = {n["id"]: n for n in nodes}

        # Topological sort based on edges
        ordered_node_ids = self._topological_sort(nodes, edges)

        # Convert nodes to steps
        steps = []
        for idx, node_id in enumerate(ordered_node_ids, start=1):
            node = node_map.get(node_id)
            if not node:
                continue

            step = self._convert_node_to_step(node, idx, edges)
            steps.append(step)

        # Determine entry/exit nodes
        entry_node = data.get("entry_node") or (ordered_node_ids[0] if ordered_node_ids else None)
        exit_nodes = tuple(data.get("exit_nodes", []))
        if not exit_nodes and ordered_node_ids:
            exit_nodes = (ordered_node_ids[-1],)

        return GraphFlowDefinition(
            key=flow_key,
            index=self._flow_indices.get(flow_key, 0),
            title=data.get("name", flow_key.title()),
            short_title=flow_key.upper()[:3],
            description=data.get("description", ""),
            steps=tuple(steps),
            cross_cutting=tuple(data.get("cross_cutting", [])),
            is_sdlc=flow_key in self._flow_indices,
            nodes=node_map,
            edges=edges,
            entry_node=entry_node,
            exit_nodes=exit_nodes,
        )

    def _convert_node_to_step(
        self, node: Dict[str, Any], index: int, edges: List[Dict[str, Any]]
    ) -> GraphStepDefinition:
        """Convert a FlowGraph node to a step definition.

        Args:
            node: Node data from FlowGraph.
            index: 1-based step index.
            edges: All edges in the flow (for routing).

        Returns:
            GraphStepDefinition.
        """
        node_id = node["id"]

        # Build routing from edges
        routing = self._build_routing_from_edges(node_id, edges)

        # Build teaching notes
        teaching_notes = None
        if any(k in node for k in ["inputs", "outputs", "teaching_note"]):
            teaching_notes = TeachingNotes(
                inputs=tuple(node.get("inputs", [])),
                outputs=tuple(node.get("outputs", [])),
                emphasizes=(),
                constraints=(),
            )

        return GraphStepDefinition(
            id=node_id,
            index=index,
            agents=tuple(node.get("agents", [])),
            role=node.get("role", ""),
            objective=node.get("objective", ""),
            inputs=tuple(node.get("inputs", [])),
            outputs=tuple(node.get("outputs", [])),
            teaching_notes=teaching_notes,
            routing=routing,
            engine_profile=None,
            teaching_note=node.get("teaching_note"),
            teaching_highlight=node.get("teaching_highlight", False),
        )

    def _build_routing_from_edges(
        self, node_id: str, edges: List[Dict[str, Any]]
    ) -> Optional[StepRouting]:
        """Build step routing from outgoing edges.

        Args:
            node_id: Source node ID.
            edges: All edges in the flow.

        Returns:
            StepRouting if edges exist, None otherwise.
        """
        outgoing = [e for e in edges if e.get("from") == node_id]
        if not outgoing:
            return StepRouting(kind="terminal")

        # Check for loop edges
        loop_edges = [e for e in outgoing if e.get("kind") == "loop"]
        next_edges = [e for e in outgoing if e.get("kind") == "next"]
        branch_edges = [e for e in outgoing if e.get("kind") == "branch"]

        if loop_edges:
            loop_edge = loop_edges[0]
            next_edge = next_edges[0] if next_edges else None
            return StepRouting(
                kind="microloop",
                loop_to=loop_edge.get("to"),
                next=next_edge.get("to") if next_edge else None,
                max_iterations=loop_edge.get("max_iterations"),
                exit_on=loop_edge.get("condition"),
            )
        elif branch_edges:
            return StepRouting(
                kind="branch",
                branch_options=tuple(e.get("to") for e in branch_edges),
            )
        elif next_edges:
            return StepRouting(
                kind="linear",
                next=next_edges[0].get("to"),
            )

        return StepRouting(kind="terminal")

    def _topological_sort(
        self, nodes: List[Dict[str, Any]], edges: List[Dict[str, Any]]
    ) -> List[str]:
        """Topologically sort nodes based on edges.

        Uses Kahn's algorithm to produce a stable ordering that respects
        edge dependencies. For nodes with no dependencies, maintains
        original order from the JSON file.

        Args:
            nodes: List of node dicts with "id" field.
            edges: List of edge dicts with "from" and "to" fields.

        Returns:
            List of node IDs in topological order.
        """
        from collections import deque

        if not nodes:
            return []

        # Build adjacency and in-degree
        node_ids = [n["id"] for n in nodes]
        in_degree = {nid: 0 for nid in node_ids}
        adjacency: Dict[str, List[str]] = {nid: [] for nid in node_ids}

        for edge in edges:
            from_node = edge.get("from")
            to_node = edge.get("to")
            # Only count "next" and "branch" edges for ordering, not "loop" edges
            if edge.get("kind") != "loop" and from_node in adjacency and to_node in in_degree:
                adjacency[from_node].append(to_node)
                in_degree[to_node] += 1

        # Find nodes with no incoming edges
        queue = deque([nid for nid in node_ids if in_degree[nid] == 0])
        result = []

        while queue:
            node = queue.popleft()
            result.append(node)

            for neighbor in adjacency[node]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        # If not all nodes were visited, there's a cycle - fall back to original order
        if len(result) != len(node_ids):
            logger.warning("Cycle detected in flow graph, using original order")
            return node_ids

        return result

    def clear_cache(self) -> None:
        """Clear the cached flow definitions."""
        self._cache.clear()


# Singleton instance for convenience
_bridge_instance: Optional[SpecBridge] = None


def get_spec_bridge(repo_root: Optional[Path] = None) -> SpecBridge:
    """Get or create the singleton SpecBridge instance.

    Args:
        repo_root: Repository root path. Only used on first call.

    Returns:
        SpecBridge instance.
    """
    global _bridge_instance
    if _bridge_instance is None:
        _bridge_instance = SpecBridge(repo_root=repo_root)
    return _bridge_instance
