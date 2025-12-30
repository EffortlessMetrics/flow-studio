"""
flow_registry.py - Load canonical flow ordering from flows.yaml

This module provides the single source of truth for flow ordering
and metadata across all Python tools.

Usage:
    from swarm.config.flow_registry import get_flow_keys, get_flow_index, get_flow_order
    from swarm.config.flow_registry import get_flow_steps, get_step_index, get_agent_position
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml

_CONFIG_FILE = Path(__file__).parent / "flows.yaml"
_FLOWS_DIR = Path(__file__).parent / "flows"


@dataclass
class TeachingNotes:
    """Teaching metadata for a step, enabling scoped context for stepwise execution.

    Attributes:
        inputs: Paths to files/artifacts this step should read
        outputs: Paths to files/artifacts this step should produce
        emphasizes: Key behaviors or patterns to focus on
        constraints: Limitations or prohibitions for this step
    """
    inputs: Tuple[str, ...] = ()
    outputs: Tuple[str, ...] = ()
    emphasizes: Tuple[str, ...] = ()
    constraints: Tuple[str, ...] = ()


@dataclass
class StepRouting:
    """Routing configuration for a step.

    Controls how the orchestrator decides which step to execute next after
    this step completes. Supports three routing patterns:

    - linear: Simple sequential execution, next step is predetermined
    - microloop: Loops back to a target step until a condition is met
    - branch: Chooses next step based on result values

    Attributes:
        kind: Routing pattern - "linear" | "microloop" | "branch"
        next: Next step ID for linear routing (after loop exits for microloop)
        loop_target: Step ID to loop back to for microloop routing
        loop_condition_field: Field in receipt to check for loop exit
        loop_success_values: Values that mean "loop is complete, exit"
        max_iterations: Safety limit on loop iterations (default 5)
        branches: For branch routing, maps condition values to step IDs
    """
    kind: str  # "linear" | "microloop" | "branch"
    next: Optional[str] = None  # next step ID for linear, or after loop exits
    loop_target: Optional[str] = None  # step to loop back to
    loop_condition_field: Optional[str] = None  # field in receipt to check
    loop_success_values: Tuple[str, ...] = ()  # values that mean "done"
    max_iterations: int = 5  # safety limit
    branches: Dict[str, str] = field(default_factory=dict)  # condition -> step_id


@dataclass
class ContextBudgetOverride:
    """Optional context budget overrides for a step, flow, or profile.

    None values mean 'inherit from parent level' in the resolution cascade:
    Step override > Flow override > Profile override > Global defaults
    """
    context_budget_chars: Optional[int] = None
    history_max_recent_chars: Optional[int] = None
    history_max_older_chars: Optional[int] = None

    def merge_with(self, parent: "ContextBudgetOverride") -> "ContextBudgetOverride":
        """Merge with parent, preferring non-None values from self."""
        return ContextBudgetOverride(
            context_budget_chars=self.context_budget_chars if self.context_budget_chars is not None else parent.context_budget_chars,
            history_max_recent_chars=self.history_max_recent_chars if self.history_max_recent_chars is not None else parent.history_max_recent_chars,
            history_max_older_chars=self.history_max_older_chars if self.history_max_older_chars is not None else parent.history_max_older_chars,
        )


@dataclass
class EngineProfile:
    """Engine configuration for stepwise execution (v2.4.0).

    Allows per-step customization of the LLM engine used during
    stepwise execution. If not specified, the orchestrator uses
    its default engine configuration.

    Attributes:
        engine: Engine identifier ("claude-step", "gemini-step", "stub")
        mode: Execution mode ("stub", "sdk", "cli")
        model: Optional model override (e.g., "claude-opus-4-5-20251101")
        timeout_ms: Step timeout in milliseconds (default 300000 = 5 min)
        context_budgets: Optional context budget overrides for this step (v2.4.0)
    """
    engine: str = "claude-step"
    mode: str = "stub"
    model: Optional[str] = None
    timeout_ms: int = 300000
    context_budgets: Optional[ContextBudgetOverride] = None  # NEW in v2.4.0


@dataclass
class StepDefinition:
    """A single step within a flow.

    Attributes:
        id: Unique identifier for this step within the flow
        index: 1-based position in the flow
        agents: Tuple of agent keys assigned to execute this step
        role: Description of what this step accomplishes
        teaching_notes: Optional teaching metadata for stepwise execution
        routing: Optional routing configuration for non-linear flow execution
        engine_profile: Optional engine configuration for this step (v2.4.0)
    """
    id: str
    index: int  # 1-based within flow
    agents: Tuple[str, ...]
    role: str
    teaching_notes: Optional[TeachingNotes] = None
    routing: Optional[StepRouting] = None
    engine_profile: Optional[EngineProfile] = None


@dataclass
class FlowDefinition:
    """A single flow definition from the registry."""
    key: str
    index: int
    title: str
    short_title: str
    description: str
    steps: Tuple[StepDefinition, ...] = ()
    cross_cutting: Tuple[str, ...] = ()
    is_sdlc: bool = True  # True for core SDLC flows, False for demo/test flows


class FlowRegistry:
    """Registry of all flows in SDLC order."""

    _instance: Optional["FlowRegistry"] = None

    def __init__(self, config_path: Path = _CONFIG_FILE, flows_dir: Path = _FLOWS_DIR):
        with open(config_path) as f:
            data = yaml.safe_load(f)

        self._flows: List[FlowDefinition] = []
        self._by_key: Dict[str, FlowDefinition] = {}
        # Tuple: (flow_key, step_id, flow_idx, step_idx)
        # For cross-cutting agents: step_id is None and step_idx is 0
        self._agent_index: Dict[str, List[Tuple[str, Optional[str], int, int]]] = {}

        for flow_data in data.get("flows", []):
            flow_key = flow_data["key"]
            flow_index = flow_data["index"]

            # Load steps from per-flow YAML file
            steps, cross_cutting = self._load_flow_steps(flows_dir, flow_key)

            flow = FlowDefinition(
                key=flow_key,
                index=flow_index,
                title=flow_data["title"],
                short_title=flow_data["short_title"],
                description=flow_data["description"],
                steps=steps,
                cross_cutting=cross_cutting,
                is_sdlc=flow_data.get("is_sdlc", True),  # Default to True for SDLC flows
            )
            self._flows.append(flow)
            self._by_key[flow.key] = flow

            # Build agent reverse index for step-attached agents
            for step in steps:
                for agent in step.agents:
                    if agent not in self._agent_index:
                        self._agent_index[agent] = []
                    self._agent_index[agent].append(
                        (flow_key, step.id, flow_index, step.index)
                    )

            # Index cross-cutting agents (not tied to specific steps)
            for agent in cross_cutting:
                if agent not in self._agent_index:
                    self._agent_index[agent] = []
                # Use None for step_id and 0 for step_idx to indicate cross-cutting
                self._agent_index[agent].append((flow_key, None, flow_index, 0))

    def _load_flow_steps(
        self, flows_dir: Path, flow_key: str
    ) -> Tuple[Tuple[StepDefinition, ...], Tuple[str, ...]]:
        """Load steps from a per-flow YAML file."""
        flow_file = flows_dir / f"{flow_key}.yaml"

        if not flow_file.exists():
            return (), ()

        with open(flow_file) as f:
            flow_data = yaml.safe_load(f)

        steps: List[StepDefinition] = []
        for idx, step_data in enumerate(flow_data.get("steps", []), start=1):
            # Parse teaching_notes if present
            teaching_notes = None
            if "teaching_notes" in step_data:
                tn_data = step_data["teaching_notes"]
                teaching_notes = TeachingNotes(
                    inputs=tuple(tn_data.get("inputs", [])),
                    outputs=tuple(tn_data.get("outputs", [])),
                    emphasizes=tuple(tn_data.get("emphasizes", [])),
                    constraints=tuple(tn_data.get("constraints", [])),
                )

            # Parse routing if present
            routing = None
            if "routing" in step_data:
                r_data = step_data["routing"]
                routing = StepRouting(
                    kind=r_data.get("kind", "linear"),
                    next=r_data.get("next"),
                    loop_target=r_data.get("loop_target"),
                    loop_condition_field=r_data.get("loop_condition_field"),
                    loop_success_values=tuple(r_data.get("loop_success_values", [])),
                    max_iterations=r_data.get("max_iterations", 5),
                    branches=r_data.get("branches", {}),
                )

            step = StepDefinition(
                id=step_data["id"],
                index=idx,
                agents=tuple(step_data.get("agents", [])),
                role=step_data.get("role", ""),
                teaching_notes=teaching_notes,
                routing=routing,
            )
            steps.append(step)

        cross_cutting = tuple(flow_data.get("cross_cutting", []))

        return tuple(steps), cross_cutting

    @classmethod
    def get_instance(cls, config_path: Path = _CONFIG_FILE) -> "FlowRegistry":
        if cls._instance is None:
            cls._instance = cls(config_path)
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Reset singleton for testing."""
        cls._instance = None

    @property
    def flow_order(self) -> List[str]:
        """Return list of flow keys in SDLC order."""
        return [f.key for f in self._flows]

    @property
    def flows(self) -> List[FlowDefinition]:
        """Return all flow definitions in order."""
        return list(self._flows)

    def get_flow(self, key: str) -> Optional[FlowDefinition]:
        """Get flow by key."""
        return self._by_key.get(key)

    def get_index(self, key: str) -> int:
        """Get numeric index for flow key (1-6)."""
        flow = self._by_key.get(key)
        return flow.index if flow else 99

    def get_steps(self, flow_key: str) -> List[StepDefinition]:
        """Get steps for a flow."""
        flow = self._by_key.get(flow_key)
        return list(flow.steps) if flow else []

    def get_step_index(self, flow_key: str, step_id: str) -> int:
        """Get 1-based step index within a flow."""
        flow = self._by_key.get(flow_key)
        if not flow:
            return 0
        for step in flow.steps:
            if step.id == step_id:
                return step.index
        return 0

    def get_agent_positions(
        self, agent_key: str
    ) -> List[Tuple[str, Optional[str], int, int]]:
        """Get all positions for an agent.

        Returns list of (flow_key, step_id, flow_idx, step_idx) tuples.
        For cross-cutting agents, step_id is None and step_idx is 0.
        """
        return self._agent_index.get(agent_key, [])

    def get_total_flows(self) -> int:
        """Get total number of flows."""
        return len(self._flows)

    def get_total_steps(self, flow_key: str) -> int:
        """Get total steps in a flow."""
        flow = self._by_key.get(flow_key)
        return len(flow.steps) if flow else 0

    @property
    def sdlc_flows(self) -> List[FlowDefinition]:
        """Return only SDLC flows (excluding demo/test flows)."""
        return [f for f in self._flows if f.is_sdlc]

    @property
    def sdlc_flow_keys(self) -> List[str]:
        """Return keys of SDLC flows only."""
        return [f.key for f in self._flows if f.is_sdlc]

    def get_total_sdlc_flows(self) -> int:
        """Get total number of SDLC flows (excluding demo/test flows)."""
        return len(self.sdlc_flows)


# Module-level convenience functions
def _get_registry() -> FlowRegistry:
    return FlowRegistry.get_instance()


def get_flow_keys() -> List[str]:
    """Get list of flow keys in SDLC order."""
    return _get_registry().flow_order


def get_flow_index(key: str) -> int:
    """Get numeric index for a flow key."""
    return _get_registry().get_index(key)


def get_flow_titles() -> Dict[str, str]:
    """Get mapping of flow key to short title."""
    return {f.key: f.short_title for f in _get_registry().flows}


def get_flow_descriptions() -> Dict[str, str]:
    """Get mapping of flow key to description."""
    return {f.key: f.description for f in _get_registry().flows}


def get_flow_steps(flow_key: str) -> List[StepDefinition]:
    """Get steps for a flow."""
    return _get_registry().get_steps(flow_key)


def get_step_index(flow_key: str, step_id: str) -> int:
    """Get 1-based step index within a flow."""
    return _get_registry().get_step_index(flow_key, step_id)


def get_agent_position(agent_key: str) -> List[Tuple[str, Optional[str], int, int]]:
    """Get all positions for an agent.

    Returns list of (flow_key, step_id, flow_idx, step_idx) tuples.
    For cross-cutting agents, step_id is None and step_idx is 0.
    """
    return _get_registry().get_agent_positions(agent_key)


def get_total_flows() -> int:
    """Get total number of flows."""
    return _get_registry().get_total_flows()


def get_total_steps(flow_key: str) -> int:
    """Get total steps in a flow."""
    return _get_registry().get_total_steps(flow_key)


def get_flow_order() -> List[str]:
    """Convenience alias for get_flow_keys()."""
    return get_flow_keys()


def get_flow_spec_id(flow_key: str) -> str:
    """Get the spec ID for a flow key (e.g., "build" -> "3-build").

    This is the canonical function for mapping flow keys to spec IDs.
    Use this instead of inline dictionaries.

    Args:
        flow_key: The flow key (signal, plan, build, review, gate, deploy, wisdom).

    Returns:
        The spec ID in the format "{index}-{key}" (e.g., "3-build").
        If the flow key is not found, returns the flow_key unchanged.
    """
    flow_index = get_flow_index(flow_key)
    if flow_index == 99:  # Unknown flow key
        return flow_key
    return f"{flow_index}-{flow_key}"


def get_sdlc_flow_keys() -> List[str]:
    """Get list of SDLC flow keys only (excluding demo/test flows)."""
    return _get_registry().sdlc_flow_keys


def get_total_sdlc_flows() -> int:
    """Get total number of SDLC flows (excluding demo/test flows)."""
    return _get_registry().get_total_sdlc_flows()
