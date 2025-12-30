"""
types.py - Dataclasses for the spec-first architecture.

These types represent the machine-readable contracts that drive stepwise execution.
They are the source of truth - prompts and SDK options are compiled from these specs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from enum import Enum


class RoutingKind(Enum):
    """Routing strategy for flow steps."""
    LINEAR = "linear"
    MICROLOOP = "microloop"
    BRANCH = "branch"
    TERMINAL = "terminal"


class StationCategory(Enum):
    """Role family for station classification."""
    SHAPING = "shaping"
    SPEC = "spec"
    DESIGN = "design"
    IMPLEMENTATION = "implementation"
    CRITIC = "critic"
    VERIFICATION = "verification"
    ANALYTICS = "analytics"
    REPORTER = "reporter"
    INFRA = "infra"
    ROUTER = "router"


# =============================================================================
# StationSpec Components
# =============================================================================


@dataclass(frozen=True)
class StationSandbox:
    """Sandbox configuration for a station."""
    enabled: bool = True
    auto_allow_bash: bool = True
    excluded_commands: Tuple[str, ...] = ()


@dataclass(frozen=True)
class StationContextBudget:
    """Context budget limits for a station."""
    total_chars: int = 200000
    recent_chars: int = 60000
    older_chars: int = 10000


@dataclass(frozen=True)
class StationSDK:
    """SDK configuration for a station.

    This defines the Claude SDK options programmatically,
    removing dependence on .claude filesystem settings.
    """
    model: str = "sonnet"
    permission_mode: str = "bypassPermissions"
    allowed_tools: Tuple[str, ...] = (
        "Read", "Write", "Edit", "Bash", "Grep", "Glob"
    )
    denied_tools: Tuple[str, ...] = ()
    sandbox: StationSandbox = field(default_factory=StationSandbox)
    max_turns: int = 12
    context_budget: StationContextBudget = field(default_factory=StationContextBudget)


@dataclass(frozen=True)
class StationIdentity:
    """Station identity for system prompt.

    This is the ONLY prose that goes into the system prompt.
    Keep it short (<2000 chars) and focused on identity + invariants.
    """
    system_append: str
    tone: str = "neutral"  # neutral, analytical, critical, supportive


@dataclass(frozen=True)
class StationIO:
    """Input/Output contract for a station.

    Paths are relative to run_base (e.g., "plan/adr.md").
    """
    required_inputs: Tuple[str, ...] = ()
    optional_inputs: Tuple[str, ...] = ()
    required_outputs: Tuple[str, ...] = ()
    optional_outputs: Tuple[str, ...] = ()


@dataclass(frozen=True)
class StationHandoff:
    """Handoff contract for a station."""
    path_template: str = "{{run.base}}/handoff/{{step.id}}.draft.json"
    required_fields: Tuple[str, ...] = (
        "status", "summary", "artifacts", "can_further_iteration_help"
    )


@dataclass(frozen=True)
class StationRuntimePrompt:
    """Runtime prompt template configuration.

    Fragments are loaded and concatenated.
    Template uses {{variable}} syntax for substitution.
    """
    fragments: Tuple[str, ...] = ()
    template: str = ""


@dataclass(frozen=True)
class StationRoutingHints:
    """Default routing behavior for this station."""
    on_verified: str = "advance"
    on_unverified: str = "loop"
    on_partial: str = "advance_with_concerns"
    on_blocked: str = "escalate"


@dataclass(frozen=True)
class StationSpec:
    """Complete station specification.

    A station is a reusable execution role with:
    - Identity (who am I)
    - SDK config (what tools/model)
    - IO contract (what I read/write)
    - Handoff contract (how I signal completion)
    - Runtime prompt template (what instructions I receive)
    """
    id: str
    version: int
    title: str
    category: StationCategory = StationCategory.IMPLEMENTATION
    sdk: StationSDK = field(default_factory=StationSDK)
    identity: StationIdentity = field(default_factory=lambda: StationIdentity(""))
    io: StationIO = field(default_factory=StationIO)
    handoff: StationHandoff = field(default_factory=StationHandoff)
    runtime_prompt: StationRuntimePrompt = field(default_factory=StationRuntimePrompt)
    invariants: Tuple[str, ...] = ()
    routing_hints: StationRoutingHints = field(default_factory=StationRoutingHints)


# =============================================================================
# FlowSpec Components
# =============================================================================


@dataclass(frozen=True)
class ContextPackConfig:
    """Context pack configuration for a flow."""
    include_upstream_artifacts: bool = True
    include_previous_envelopes: bool = True
    max_envelopes: int = 12
    include_scent_trail: bool = True


@dataclass(frozen=True)
class FlowDefaults:
    """Default settings for all steps in a flow."""
    context_pack: ContextPackConfig = field(default_factory=ContextPackConfig)
    sdk_overrides: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RoutingConfig:
    """Routing configuration for a flow step."""
    kind: RoutingKind = RoutingKind.LINEAR
    next: Optional[str] = None
    loop_target: Optional[str] = None
    loop_condition_field: str = "status"
    loop_success_values: Tuple[str, ...] = ("VERIFIED", "verified")
    max_iterations: int = 3
    branches: Dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class StepTeaching:
    """Teaching metadata for a flow step."""
    highlight: bool = False
    note: str = ""


@dataclass(frozen=True)
class FlowStep:
    """A step in a flow specification.

    References a station and provides step-specific overrides.
    """
    id: str
    station: str  # Station ID reference
    objective: str
    scope: Optional[str] = None
    inputs: Tuple[str, ...] = ()
    outputs: Tuple[str, ...] = ()
    routing: RoutingConfig = field(default_factory=RoutingConfig)
    sdk_overrides: Dict[str, Any] = field(default_factory=dict)
    teaching: StepTeaching = field(default_factory=StepTeaching)


@dataclass(frozen=True)
class FlowSpec:
    """Complete flow specification.

    The orchestrator spine: defines step sequence and routing.
    """
    id: str
    version: int
    title: str
    description: str = ""
    defaults: FlowDefaults = field(default_factory=FlowDefaults)
    steps: Tuple[FlowStep, ...] = ()
    cross_cutting_stations: Tuple[str, ...] = ()


# =============================================================================
# Compiler Output
# =============================================================================


@dataclass(frozen=True)
class VerificationRequirements:
    """Verification requirements for a step.

    Defines what artifacts must exist and what commands must pass
    for the step to be considered verified.
    """
    required_artifacts: Tuple[str, ...] = ()
    verification_commands: Tuple[str, ...] = ()


@dataclass(frozen=True)
class HandoffContract:
    """Handoff contract for a step.

    Defines where the handoff file goes and what fields it must contain.
    """
    path: str  # Resolved path (no templates)
    required_fields: Tuple[str, ...] = (
        "status", "summary", "artifacts", "can_further_iteration_help"
    )


@dataclass(frozen=True)
class PromptPlan:
    """Compiled prompt plan ready for SDK execution.

    This is the output of the spec compiler - everything needed
    to make a Claude SDK call without any additional computation.

    V2 additions:
    - verification: Required artifacts and verification commands
    - handoff: Resolved handoff path and required fields
    - flow_key: Separate from flow_id for routing
    """
    # Traceability
    station_id: str
    station_version: int
    flow_id: str
    flow_version: int
    step_id: str
    prompt_hash: str

    # SDK Options (programmatic, not filesystem)
    model: str
    permission_mode: str
    allowed_tools: Tuple[str, ...]
    max_turns: int
    sandbox_enabled: bool
    cwd: str

    # Prompt Content
    system_append: str
    user_prompt: str

    # Metadata for events
    compiled_at: str  # ISO timestamp
    context_pack_size: int  # Number of envelopes included

    # V2: Verification requirements (merged from station + step)
    verification: VerificationRequirements = field(
        default_factory=lambda: VerificationRequirements()
    )

    # V2: Handoff contract (resolved path, required fields)
    handoff: HandoffContract = field(
        default_factory=lambda: HandoffContract(path="")
    )

    # V2: Flow key for routing (e.g., "build" from "3-build")
    flow_key: str = ""


@dataclass(frozen=True)
class PromptReceipt:
    """Receipt tracking compilation for audit trail."""
    prompt_hash: str           # SHA256 of combined prompts (from PromptPlan)
    fragment_manifest: Tuple[str, ...] = ()  # Fragment paths used
    context_pack_hash: str = ""     # Hash of input context
    model_tier: str = ""            # haiku/sonnet/opus
    tool_profile: Tuple[str, ...] = ()  # Allowed tools
    compiled_at: str = ""           # ISO timestamp
    compiler_version: str = "1.0.0"
    station_id: str = ""
    flow_id: str = ""
    step_id: str = ""


# =============================================================================
# Helpers
# =============================================================================


def create_prompt_receipt(plan: PromptPlan, context_pack_hash: str = "") -> PromptReceipt:
    """Create a PromptReceipt from a compiled PromptPlan."""
    return PromptReceipt(
        prompt_hash=plan.prompt_hash,
        fragment_manifest=(),  # TODO: Track fragments in compiler
        context_pack_hash=context_pack_hash,
        model_tier=plan.model.split("-")[1] if "-" in plan.model else plan.model,
        tool_profile=plan.allowed_tools,
        compiled_at=plan.compiled_at,
        compiler_version="1.0.0",
        station_id=plan.station_id,
        flow_id=plan.flow_id,
        step_id=plan.step_id,
    )


def station_spec_from_dict(data: Dict[str, Any]) -> StationSpec:
    """Parse a StationSpec from a dictionary (e.g., YAML load)."""
    # Parse nested objects
    sdk_data = data.get("sdk", {})
    sandbox_data = sdk_data.get("sandbox", {})
    budget_data = sdk_data.get("context_budget", {})

    sandbox = StationSandbox(
        enabled=sandbox_data.get("enabled", True),
        auto_allow_bash=sandbox_data.get("auto_allow_bash", True),
        excluded_commands=tuple(sandbox_data.get("excluded_commands", [])),
    )

    budget = StationContextBudget(
        total_chars=budget_data.get("total_chars", 200000),
        recent_chars=budget_data.get("recent_chars", 60000),
        older_chars=budget_data.get("older_chars", 10000),
    )

    sdk = StationSDK(
        model=sdk_data.get("model", "sonnet"),
        permission_mode=sdk_data.get("permission_mode", "bypassPermissions"),
        allowed_tools=tuple(sdk_data.get("allowed_tools", ["Read", "Write", "Edit", "Bash", "Grep", "Glob"])),
        denied_tools=tuple(sdk_data.get("denied_tools", [])),
        sandbox=sandbox,
        max_turns=sdk_data.get("max_turns", 12),
        context_budget=budget,
    )

    identity_data = data.get("identity", {})
    identity = StationIdentity(
        system_append=identity_data.get("system_append", ""),
        tone=identity_data.get("tone", "neutral"),
    )

    io_data = data.get("io", {})
    io = StationIO(
        required_inputs=tuple(io_data.get("required_inputs", [])),
        optional_inputs=tuple(io_data.get("optional_inputs", [])),
        required_outputs=tuple(io_data.get("required_outputs", [])),
        optional_outputs=tuple(io_data.get("optional_outputs", [])),
    )

    handoff_data = data.get("handoff", {})
    handoff = StationHandoff(
        path_template=handoff_data.get("path_template", "{{run.base}}/handoff/{{step.id}}.draft.json"),
        required_fields=tuple(handoff_data.get("required_fields", ["status", "summary", "artifacts", "can_further_iteration_help"])),
    )

    prompt_data = data.get("runtime_prompt", {})
    runtime_prompt = StationRuntimePrompt(
        fragments=tuple(prompt_data.get("fragments", [])),
        template=prompt_data.get("template", ""),
    )

    hints_data = data.get("routing_hints", {})
    routing_hints = StationRoutingHints(
        on_verified=hints_data.get("on_verified", "advance"),
        on_unverified=hints_data.get("on_unverified", "loop"),
        on_partial=hints_data.get("on_partial", "advance_with_concerns"),
        on_blocked=hints_data.get("on_blocked", "escalate"),
    )

    category_str = data.get("category", "implementation")
    try:
        category = StationCategory(category_str)
    except ValueError:
        category = StationCategory.IMPLEMENTATION

    return StationSpec(
        id=data["id"],
        version=data.get("version", 1),
        title=data.get("title", data["id"]),
        category=category,
        sdk=sdk,
        identity=identity,
        io=io,
        handoff=handoff,
        runtime_prompt=runtime_prompt,
        invariants=tuple(data.get("invariants", [])),
        routing_hints=routing_hints,
    )


def flow_spec_from_dict(data: Dict[str, Any]) -> FlowSpec:
    """Parse a FlowSpec from a dictionary (e.g., YAML load)."""
    # Parse defaults
    defaults_data = data.get("defaults", {})
    cp_data = defaults_data.get("context_pack", {})

    context_pack = ContextPackConfig(
        include_upstream_artifacts=cp_data.get("include_upstream_artifacts", True),
        include_previous_envelopes=cp_data.get("include_previous_envelopes", True),
        max_envelopes=cp_data.get("max_envelopes", 12),
        include_scent_trail=cp_data.get("include_scent_trail", True),
    )

    defaults = FlowDefaults(
        context_pack=context_pack,
        sdk_overrides=defaults_data.get("sdk_overrides", {}),
    )

    # Parse steps
    steps = []
    for step_data in data.get("steps", []):
        routing_data = step_data.get("routing", {})

        kind_str = routing_data.get("kind", "linear")
        try:
            kind = RoutingKind(kind_str)
        except ValueError:
            kind = RoutingKind.LINEAR

        routing = RoutingConfig(
            kind=kind,
            next=routing_data.get("next"),
            loop_target=routing_data.get("loop_target"),
            loop_condition_field=routing_data.get("loop_condition_field", "status"),
            loop_success_values=tuple(routing_data.get("loop_success_values", ["VERIFIED", "verified"])),
            max_iterations=routing_data.get("max_iterations", 3),
            branches=routing_data.get("branches", {}),
        )

        teaching_data = step_data.get("teaching", {})
        teaching = StepTeaching(
            highlight=teaching_data.get("highlight", False),
            note=teaching_data.get("note", ""),
        )

        step = FlowStep(
            id=step_data["id"],
            station=step_data["station"],
            objective=step_data.get("objective", ""),
            scope=step_data.get("scope"),
            inputs=tuple(step_data.get("inputs", [])),
            outputs=tuple(step_data.get("outputs", [])),
            routing=routing,
            sdk_overrides=step_data.get("sdk_overrides", {}),
            teaching=teaching,
        )
        steps.append(step)

    return FlowSpec(
        id=data["id"],
        version=data.get("version", 1),
        title=data.get("title", data["id"]),
        description=data.get("description", ""),
        defaults=defaults,
        steps=tuple(steps),
        cross_cutting_stations=tuple(data.get("cross_cutting_stations", [])),
    )
