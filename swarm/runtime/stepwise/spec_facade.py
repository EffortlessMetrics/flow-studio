"""
spec_facade.py - Cached access to FlowSpec and StationSpec.

This module provides a facade for loading and caching spec-first types:
- FlowSpec: Flow definition from swarm/spec/flows/
- StationSpec: Station definition from swarm/spec/stations/

The facade abstracts away the file I/O and caching, making specs available
to routing, verification, and orchestration without repeated loading.

Supports two loading modes:
1. Legacy YAML mode: Loads from swarm/spec/flows/*.yaml (original)
2. Pack JSON mode: Loads from swarm/packs/flows/*.json (new graph-based)

Use `use_pack_specs=True` to enable pack-based loading for gradual migration.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from swarm.config.flow_registry import FlowDefinition, get_flow_spec_id
from swarm.config.pack_registry import PackRegistry
from swarm.runtime.router import Edge, EdgeCondition, FlowGraph, NodeConfig

# Pack-based loading support
from swarm.runtime.spec_bridge import (
    PackFlowRegistry,
    load_flow_from_pack,
)

# Conditional imports for spec module (may not be available in all environments)
try:
    from swarm.spec.loader import load_flow, load_station
    from swarm.spec.types import FlowSpec, RoutingKind, StationSpec

    SPEC_AVAILABLE = True
except ImportError:
    SPEC_AVAILABLE = False
    FlowSpec = None  # type: ignore
    RoutingKind = None  # type: ignore
    StationSpec = None  # type: ignore

    def load_flow(flow_id: str, repo_root: Path) -> Any:
        raise ImportError("swarm.spec module not available")

    def load_station(station_id: str, repo_root: Path) -> Any:
        raise ImportError("swarm.spec module not available")


logger = logging.getLogger(__name__)


class SpecFacade:
    """Facade for loading and caching FlowSpec and StationSpec.

    Provides thread-safe caching of specs to avoid repeated file I/O.
    Returns None for missing specs rather than raising exceptions.

    Supports two modes:
    - use_pack_specs=False (default): Load from legacy YAML specs
    - use_pack_specs=True: Load from new JSON pack specs

    Attributes:
        repo_root: Repository root path.
        use_pack_specs: Whether to use pack-based JSON loading.
    """

    def __init__(self, repo_root: Path, use_pack_specs: bool = False):
        """Initialize the facade.

        Args:
            repo_root: Repository root path.
            use_pack_specs: If True, load flows from pack JSON specs
                instead of legacy YAML specs.
        """
        self._repo_root = repo_root
        self._use_pack_specs = use_pack_specs
        self._flow_cache: Dict[str, Any] = {}
        self._station_cache: Dict[str, Any] = {}
        self._flow_graph_cache: Dict[str, Optional[FlowGraph]] = {}
        self._flow_def_cache: Dict[str, Optional[FlowDefinition]] = {}

        # Pack registry for pack-based loading
        self._pack_registry: Optional[PackRegistry] = None
        self._pack_flow_registry: Optional[PackFlowRegistry] = None

    @property
    def spec_available(self) -> bool:
        """Check if the spec module is available."""
        return SPEC_AVAILABLE

    def load_flow_spec(self, flow_key: str) -> Optional[Any]:
        """Load FlowSpec from swarm/spec/flows/{flow_id}.yaml.

        Uses caching to avoid repeated file I/O.

        Args:
            flow_key: The flow key (e.g., "build", "plan").

        Returns:
            Loaded FlowSpec or None if not available.
        """
        if not SPEC_AVAILABLE:
            logger.debug("Spec module not available, skipping FlowSpec load")
            return None

        if flow_key in self._flow_cache:
            return self._flow_cache[flow_key]

        # Map flow_key to spec flow_id (e.g., "build" -> "3-build")
        flow_id = get_flow_spec_id(flow_key)

        try:
            flow_spec = load_flow(flow_id, self._repo_root)
            self._flow_cache[flow_key] = flow_spec
            logger.debug("Loaded FlowSpec for %s (id=%s)", flow_key, flow_id)
            return flow_spec
        except FileNotFoundError:
            logger.debug("FlowSpec not found for %s", flow_key)
            self._flow_cache[flow_key] = None
            return None
        except Exception as e:
            logger.warning("Failed to load FlowSpec for %s: %s", flow_key, e)
            self._flow_cache[flow_key] = None
            return None

    def load_station_spec(self, station_id: str) -> Optional[Any]:
        """Load StationSpec from swarm/spec/stations/{station_id}.yaml.

        Uses caching to avoid repeated file I/O.

        Args:
            station_id: The station identifier (e.g., "code-implementer").

        Returns:
            Loaded StationSpec or None if not available.
        """
        if not SPEC_AVAILABLE:
            return None

        if station_id in self._station_cache:
            return self._station_cache[station_id]

        try:
            station_spec = load_station(station_id, self._repo_root)
            self._station_cache[station_id] = station_spec
            logger.debug("Loaded StationSpec for %s", station_id)
            return station_spec
        except FileNotFoundError:
            logger.debug("StationSpec not found for %s", station_id)
            self._station_cache[station_id] = None
            return None
        except Exception as e:
            logger.warning("Failed to load StationSpec for %s: %s", station_id, e)
            self._station_cache[station_id] = None
            return None

    def build_flow_graph(self, flow_key: str) -> Optional[FlowGraph]:
        """Build a FlowGraph from FlowSpec for Navigator context.

        The Navigator needs a FlowGraph to extract candidate edges and
        make routing decisions. This method converts FlowSpec step routing
        into graph edges.

        Args:
            flow_key: The flow key to build graph for.

        Returns:
            FlowGraph if spec is available, None otherwise.
        """
        if flow_key in self._flow_graph_cache:
            return self._flow_graph_cache[flow_key]

        flow_spec = self.load_flow_spec(flow_key)
        if flow_spec is None:
            self._flow_graph_cache[flow_key] = None
            return None

        try:
            nodes: Dict[str, NodeConfig] = {}
            edges: List[Edge] = []

            for step in flow_spec.steps:
                # Create node
                nodes[step.id] = NodeConfig(
                    node_id=step.id,
                    template_id=step.station or step.id,
                    max_iterations=getattr(step.routing, "max_iterations", None),
                    exit_on=(
                        {"status": list(step.routing.loop_success_values)}
                        if step.routing.loop_success_values
                        else None
                    ),
                )

                # Create edges from routing
                routing = step.routing
                # routing_kind available via routing.kind but not needed for edge creation

                # Next edge (linear/terminal/branch default)
                if routing.next:
                    edges.append(
                        Edge(
                            edge_id=f"{step.id}->next",
                            from_node=step.id,
                            to_node=routing.next,
                            edge_type="sequence",
                            priority=50,
                        )
                    )

                # Loop edge (for microloops)
                if routing.loop_target:
                    # Loop edge with exit condition
                    exit_condition = None
                    if routing.loop_success_values:
                        exit_condition = EdgeCondition(
                            field="status",
                            operator="not_in",
                            value=list(routing.loop_success_values),
                        )
                    edges.append(
                        Edge(
                            edge_id=f"{step.id}->loop",
                            from_node=step.id,
                            to_node=routing.loop_target,
                            edge_type="loop",
                            priority=40,  # Lower priority than advance
                            condition=exit_condition,
                        )
                    )

            graph = FlowGraph(
                graph_id=flow_key,
                nodes=nodes,
                edges=edges,
                policy={
                    "max_loop_iterations": 10,  # Default fuse
                },
            )
            self._flow_graph_cache[flow_key] = graph
            return graph

        except Exception as e:
            logger.debug("Failed to build FlowGraph for %s: %s", flow_key, e)
            self._flow_graph_cache[flow_key] = None
            return None

    def clear_cache(self) -> None:
        """Clear all cached specs.

        Useful for testing or when spec files are modified during runtime.
        """
        self._flow_cache.clear()
        self._station_cache.clear()
        self._flow_graph_cache.clear()
        self._flow_def_cache.clear()
        self._pack_registry = None
        self._pack_flow_registry = None

    # -------------------------------------------------------------------------
    # Pack-Based Loading (New JSON Format)
    # -------------------------------------------------------------------------

    def _ensure_pack_registry(self) -> PackRegistry:
        """Lazily initialize pack registry."""
        if self._pack_registry is None:
            self._pack_registry = PackRegistry(self._repo_root)
            self._pack_registry.load()
        return self._pack_registry

    def _ensure_pack_flow_registry(self) -> PackFlowRegistry:
        """Lazily initialize pack flow registry."""
        if self._pack_flow_registry is None:
            self._pack_flow_registry = PackFlowRegistry(self._repo_root)
        return self._pack_flow_registry

    def load_flow_definition(self, flow_key: str) -> Optional[FlowDefinition]:
        """Load FlowDefinition from pack or legacy source.

        If use_pack_specs is True, loads from pack JSON specs.
        Otherwise, returns None (caller should use flow_registry).

        Args:
            flow_key: The flow key (e.g., "build", "plan").

        Returns:
            FlowDefinition or None if not available.
        """
        if flow_key in self._flow_def_cache:
            return self._flow_def_cache[flow_key]

        if not self._use_pack_specs:
            # Pack specs disabled, return None for legacy path
            return None

        try:
            flow_def = load_flow_from_pack(flow_key, self._repo_root)
            self._flow_def_cache[flow_key] = flow_def
            logger.debug("Loaded FlowDefinition from pack for %s", flow_key)
            return flow_def
        except Exception as e:
            logger.warning("Failed to load FlowDefinition from pack for %s: %s", flow_key, e)
            self._flow_def_cache[flow_key] = None
            return None

    def get_pack_flow_registry(self) -> PackFlowRegistry:
        """Get the PackFlowRegistry for pack-based loading.

        Returns:
            PackFlowRegistry instance.

        Raises:
            RuntimeError: If use_pack_specs is False.
        """
        if not self._use_pack_specs:
            raise RuntimeError(
                "Pack specs not enabled. Initialize SpecFacade with use_pack_specs=True"
            )
        return self._ensure_pack_flow_registry()

    def build_flow_graph_from_pack(self, flow_key: str) -> Optional[FlowGraph]:
        """Build FlowGraph from pack JSON spec.

        Alternative to build_flow_graph() that uses the new pack format.

        Args:
            flow_key: The flow key to build graph for.

        Returns:
            FlowGraph if available, None otherwise.
        """
        cache_key = f"pack:{flow_key}"
        if cache_key in self._flow_graph_cache:
            return self._flow_graph_cache[cache_key]

        try:
            pack_registry = self._ensure_pack_registry()
            flow_spec = pack_registry.get_flow(flow_key)

            if flow_spec is None:
                self._flow_graph_cache[cache_key] = None
                return None

            # Convert pack nodes/edges to FlowGraph
            nodes: Dict[str, NodeConfig] = {}
            edges: List[Edge] = []

            for node in flow_spec.nodes:
                exit_on = None
                if node.overrides and "exit_on" in node.overrides:
                    exit_on = node.overrides["exit_on"]

                nodes[node.node_id] = NodeConfig(
                    node_id=node.node_id,
                    template_id=node.template_id or node.node_id,
                    max_iterations=node.params.get("max_iterations") if node.params else None,
                    exit_on=exit_on,
                )

            for edge in flow_spec.edges:
                condition = None
                if edge.condition:
                    # Convert condition dict to EdgeCondition if needed
                    if isinstance(edge.condition, dict):
                        condition = EdgeCondition(
                            field=edge.condition.get("field", "status"),
                            operator=edge.condition.get("operator", "=="),
                            value=edge.condition.get("value", ""),
                            expression=edge.condition.get("expression"),
                        )

                edges.append(
                    Edge(
                        edge_id=edge.edge_id,
                        from_node=edge.from_node,
                        to_node=edge.to_node,
                        edge_type=edge.edge_type,
                        priority=edge.priority,
                        condition=condition,
                    )
                )

            policy = {}
            if flow_spec.policy:
                if isinstance(flow_spec.policy, dict):
                    policy = flow_spec.policy
                elif hasattr(flow_spec.policy, "max_loop_iterations"):
                    policy = {
                        "max_loop_iterations": flow_spec.policy.max_loop_iterations,
                        "suggested_sidequests": getattr(
                            flow_spec.policy, "suggested_sidequests", []
                        ),
                    }

            graph = FlowGraph(
                graph_id=flow_key,
                nodes=nodes,
                edges=edges,
                policy=policy,
            )

            self._flow_graph_cache[cache_key] = graph
            return graph

        except Exception as e:
            logger.warning("Failed to build FlowGraph from pack for %s: %s", flow_key, e)
            self._flow_graph_cache[cache_key] = None
            return None

    @property
    def use_pack_specs(self) -> bool:
        """Whether pack-based loading is enabled."""
        return self._use_pack_specs

    @use_pack_specs.setter
    def use_pack_specs(self, value: bool) -> None:
        """Enable or disable pack-based loading.

        Clears caches when mode changes.
        """
        if value != self._use_pack_specs:
            self._use_pack_specs = value
            self.clear_cache()


# Module-level convenience functions for simple use cases
_default_facade: Optional[SpecFacade] = None


def get_facade(
    repo_root: Optional[Path] = None,
    use_pack_specs: bool = False,
) -> SpecFacade:
    """Get or create a module-level SpecFacade.

    Args:
        repo_root: Repository root path. Uses auto-detection if not provided.
        use_pack_specs: If True, enable pack-based loading.

    Returns:
        SpecFacade instance.
    """
    global _default_facade
    if _default_facade is None or (repo_root and _default_facade._repo_root != repo_root):
        if repo_root is None:
            repo_root = Path(__file__).resolve().parents[3]
        _default_facade = SpecFacade(repo_root, use_pack_specs=use_pack_specs)
    elif _default_facade._use_pack_specs != use_pack_specs:
        _default_facade.use_pack_specs = use_pack_specs
    return _default_facade


def load_flow_spec(flow_key: str, repo_root: Optional[Path] = None) -> Optional[Any]:
    """Convenience function to load a FlowSpec."""
    return get_facade(repo_root).load_flow_spec(flow_key)


def load_station_spec(station_id: str, repo_root: Optional[Path] = None) -> Optional[Any]:
    """Convenience function to load a StationSpec."""
    return get_facade(repo_root).load_station_spec(station_id)


__all__ = [
    "SpecFacade",
    "get_facade",
    "load_flow_spec",
    "load_station_spec",
    "SPEC_AVAILABLE",
    # Pack-based loading re-exports
    "PackFlowRegistry",
    "load_flow_from_pack",
]
