"""
compiler.py - Compile specs + context into PromptPlan for SDK execution.

The SpecCompiler is the bridge between the spec layer (FlowGraph, StationSpec,
StepTemplate) and the runtime layer (Claude SDK execution). It produces a
fully-resolved PromptPlan with:

- Traceability: station_id, flow_id, step_id, prompt_hash, compiled_at
- SDK Options: model, permission_mode, allowed_tools, max_turns, sandbox
- Prompt Content: system_prompt (preset + append), user_prompt (objective + context)
- Verification: required artifacts, verification commands
- Handoff: resolved path, required fields, output schema

Key concepts:
- StepPlan: Single step compilation result (per PromptPlan schema)
- PromptPlan: Multi-step flow compilation result
- Fragment inclusion: {{fragment:common/status_model}} syntax
- Template resolution: {{param}} substitution with defaults
- Deterministic compilation: same inputs = same prompt_hash
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

from .loader import load_flow, load_fragment, load_fragments, load_station
from .types import (
    FlowSpec,
    FlowStep,
    HandoffContract,
    PromptPlan,
    RoutingKind,
    StationSpec,
    VerificationRequirements,
)

if TYPE_CHECKING:
    from swarm.runtime.context_pack import ContextPack
    from swarm.runtime.engines.models import StepContext

logger = logging.getLogger(__name__)

# Compiler version for traceability
COMPILER_VERSION = "1.0.0"

# Claude preset content (default system prompt base)
CLAUDE_CODE_PRESET = """You are Claude, an AI assistant by Anthropic. You are helpful, harmless, and honest.
You have access to a set of tools to help accomplish tasks. Use them as needed."""

# System prompt presets
SYSTEM_PRESETS: Dict[str, str] = {
    "default": CLAUDE_CODE_PRESET,
    "claude_code": CLAUDE_CODE_PRESET,
    "minimal": "You are a helpful AI assistant.",
    "custom": "",  # Custom presets are loaded from identity.preset_content
}

# Tool profiles for quick configuration
TOOL_PROFILES: Dict[str, Tuple[str, ...]] = {
    "read_only": ("Read", "Grep", "Glob"),
    "read_write": ("Read", "Write", "Edit", "Grep", "Glob"),
    "full_access": ("Read", "Write", "Edit", "Bash", "Grep", "Glob", "Task", "TodoWrite"),
    "critic": ("Read", "Grep", "Glob", "Write"),  # Critics can write critique files
    "reporter": ("Read", "Grep", "Glob", "Write"),  # Reporters write reports
}


# =============================================================================
# StepPlan Dataclass (per prompt_plan.schema.json)
# =============================================================================


@dataclass(frozen=True)
class SystemPromptSpec:
    """Compiled system prompt specification."""
    preset: str  # "default", "claude_code", "minimal", "custom"
    preset_content: str  # Resolved preset content
    append: str  # Station identity + invariants
    combined: str  # Final combined system prompt
    invariants: Tuple[str, ...]  # Explicit invariants
    tone: str  # "neutral", "analytical", "critical", "supportive"
    scent_trail: str  # Wisdom from previous runs


@dataclass(frozen=True)
class UserPromptSpec:
    """Compiled user prompt specification."""
    objective: str  # Primary objective
    scope: str  # Scope constraint
    context_section: str  # Compiled context pointers
    guidelines: str  # Compiled guidelines from fragments
    finalization_instructions: str  # Handoff file instructions
    combined: str  # Final combined user prompt


@dataclass(frozen=True)
class OutputFormatSpec:
    """Output format specification for handoff envelope."""
    handoff_path: str  # Resolved path
    schema_ref: str  # Path to JSON schema
    required_fields: Tuple[str, ...]  # Required envelope fields
    status_values: Tuple[str, ...]  # Valid status values
    example: Dict[str, Any]  # Example envelope


@dataclass(frozen=True)
class SdkOptionsSpec:
    """SDK options for Claude execution."""
    model: str  # Full model ID
    model_tier: str  # Shorthand tier
    permission_mode: str  # "default", "bypassPermissions", "planMode"
    allowed_tools: Tuple[str, ...]  # Explicit tool list
    denied_tools: Tuple[str, ...]  # Denied tools
    tool_profile: str  # Tool profile name
    max_turns: int  # Maximum conversation turns
    sandbox_enabled: bool  # Sandbox mode
    cwd: str  # Working directory


@dataclass(frozen=True)
class TraceabilitySpec:
    """Traceability metadata for audit trail."""
    station_id: str
    station_version: int
    template_id: str  # Optional template reference
    template_version: int
    flow_id: str
    flow_version: int
    flow_key: str
    step_id: str
    prompt_hash: str  # SHA-256 truncated
    compiled_at: str  # ISO timestamp
    compiler_version: str
    run_id: str  # Optional run correlation
    iteration: int  # Microloop iteration


@dataclass(frozen=True)
class FragmentReference:
    """Reference to a loaded fragment for audit."""
    path: str
    hash: str  # Content hash
    version: str  # Optional version


@dataclass(frozen=True)
class VerificationCommand:
    """Command for post-execution verification."""
    command: str
    success_pattern: str
    timeout_seconds: int
    description: str


@dataclass(frozen=True)
class VerificationSpec:
    """Post-execution verification requirements."""
    required_artifacts: Tuple[str, ...]
    verification_commands: Tuple[VerificationCommand, ...]
    gate_status_on_fail: str  # "UNVERIFIED" or "BLOCKED"


@dataclass(frozen=True)
class StepPlan:
    """Compiled plan for a single step, ready for SDK execution.

    This is the per-step output of the SpecCompiler. It contains everything
    needed to execute a single Claude SDK call:

    - Traceability: Links to source specs for audit
    - SDK Options: Model, tools, permissions, sandbox
    - Prompts: System and user prompts fully resolved
    - Output: Expected handoff format and verification

    StepPlan corresponds to the prompt_plan.schema.json structure.
    """
    step_id: str
    station_id: str
    system_prompt: str  # Combined system prompt
    user_prompt: str  # Combined user prompt
    allowed_tools: Tuple[str, ...]
    permission_mode: str
    max_turns: int
    output_schema: Dict[str, Any]  # JSON schema for structured output
    prompt_hash: str  # Deterministic hash for reproducibility

    # Extended fields for full schema compliance
    model: str = "sonnet"
    model_tier: str = "sonnet"
    sandbox_enabled: bool = True
    cwd: str = ""
    station_version: int = 1
    flow_id: str = ""
    flow_version: int = 1
    flow_key: str = ""
    compiled_at: str = ""
    compiler_version: str = COMPILER_VERSION
    handoff_path: str = ""
    required_fields: Tuple[str, ...] = ("status", "summary", "artifacts")
    verification: VerificationRequirements = field(
        default_factory=lambda: VerificationRequirements()
    )
    fragments_used: Tuple[FragmentReference, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary matching prompt_plan.schema.json."""
        return {
            "system_prompt": {
                "preset": "claude_code",
                "append": "",
                "combined": self.system_prompt,
                "invariants": [],
                "tone": "neutral",
            },
            "user_prompt": {
                "objective": "",
                "combined": self.user_prompt,
            },
            "output_format": {
                "handoff_path": self.handoff_path,
                "required_fields": list(self.required_fields),
                "schema_ref": "handoff_envelope.schema.json",
            },
            "sdk_options": {
                "model": self.model,
                "model_tier": self.model_tier,
                "permission_mode": self.permission_mode,
                "tools": {
                    "allowed": list(self.allowed_tools),
                },
                "max_turns": self.max_turns,
                "sandbox": {
                    "enabled": self.sandbox_enabled,
                },
                "cwd": self.cwd,
            },
            "traceability": {
                "station_id": self.station_id,
                "station_version": self.station_version,
                "flow_id": self.flow_id,
                "flow_version": self.flow_version,
                "flow_key": self.flow_key,
                "step_id": self.step_id,
                "prompt_hash": self.prompt_hash,
                "compiled_at": self.compiled_at,
                "compiler_version": self.compiler_version,
            },
            "fragments_used": [
                {"path": f.path, "hash": f.hash, "version": f.version}
                for f in self.fragments_used
            ],
            "verification": {
                "required_artifacts": list(self.verification.required_artifacts),
                "verification_commands": list(self.verification.verification_commands),
            },
        }


# =============================================================================
# FlowGraph Node Types (per flow_graph.schema.json)
# =============================================================================


@dataclass
class FlowNode:
    """A node in the FlowGraph (from flow_graph.schema.json)."""
    node_id: str
    template_id: str
    params: Dict[str, Any] = field(default_factory=dict)
    overrides: Dict[str, Any] = field(default_factory=dict)
    ui: Dict[str, Any] = field(default_factory=dict)


@dataclass
class StepTemplate:
    """A step template (from step_template.schema.json)."""
    id: str
    version: int
    title: str
    station_id: str
    objective: Dict[str, Any]  # ParameterizedObjective
    io_overrides: Dict[str, Any] = field(default_factory=dict)
    routing_defaults: Dict[str, Any] = field(default_factory=dict)
    ui_defaults: Dict[str, Any] = field(default_factory=dict)
    constraints: Dict[str, Any] = field(default_factory=dict)
    parameters: Dict[str, Any] = field(default_factory=dict)
    tags: List[str] = field(default_factory=list)
    category: str = "implementation"
    deprecated: bool = False


@dataclass
class CompileContext:
    """Context for compilation including run information."""
    run_id: str = ""
    run_base: Path = field(default_factory=lambda: Path("swarm/runs/default"))
    repo_root: Optional[Path] = None
    iteration: int = 1
    context_pack: Optional[Any] = None
    scent_trail: str = ""


# =============================================================================
# Flow Key Extraction
# =============================================================================


def extract_flow_key(flow_id: str) -> str:
    """Extract the flow key from a flow ID.

    Flow IDs are typically formatted as "<number>-<key>" (e.g., "3-build").
    This function extracts the key portion for routing purposes.

    Args:
        flow_id: The full flow identifier (e.g., "3-build").

    Returns:
        The flow key (e.g., "build").

    Examples:
        >>> extract_flow_key("3-build")
        'build'
        >>> extract_flow_key("1-signal")
        'signal'
        >>> extract_flow_key("build")  # Already just the key
        'build'
    """
    if "-" in flow_id:
        # Split on first hyphen and take everything after
        parts = flow_id.split("-", 1)
        if len(parts) == 2 and parts[0].isdigit():
            return parts[1]
    return flow_id


# =============================================================================
# Template Rendering
# =============================================================================


def render_template(template: str, variables: Dict[str, Any]) -> str:
    """Render a Mustache-style template with {{variable}} substitution.

    Supports nested access like {{step.objective}} and {{run.base}}.

    Args:
        template: Template string with {{variable}} placeholders.
        variables: Dictionary of variable values (can be nested).

    Returns:
        Rendered string with substitutions applied.
    """
    def get_nested(obj: Any, path: str) -> str:
        """Get a nested value from a dict using dot notation."""
        parts = path.split(".")
        current = obj
        for part in parts:
            if isinstance(current, dict):
                current = current.get(part, "")
            elif hasattr(current, part):
                current = getattr(current, part)
            else:
                return ""
        return str(current) if current else ""

    def replace_match(match: re.Match) -> str:
        var_path = match.group(1).strip()
        return get_nested(variables, var_path)

    return re.sub(r"\{\{([^}]+)\}\}", replace_match, template)


# =============================================================================
# Prompt Building
# =============================================================================


def build_system_append(
    station: StationSpec,
    scent_trail: Optional[str] = None,
) -> str:
    """Build the system prompt append from station identity.

    Combines:
    - Station identity (system_append)
    - Station invariants
    - Scent trail (wisdom from previous runs)

    Args:
        station: The station specification.
        scent_trail: Optional cross-run wisdom content.

    Returns:
        Combined system prompt append text.
    """
    parts: List[str] = []

    # Station identity
    if station.identity.system_append:
        parts.append(station.identity.system_append.strip())

    # Invariants as hard rules
    if station.invariants:
        parts.append("\n## Invariants (Non-Negotiable)")
        for inv in station.invariants:
            parts.append(f"- {inv}")

    # Scent trail (truncated to avoid bloat)
    if scent_trail:
        trail = scent_trail[:1500]  # Cap at 1500 chars
        if len(scent_trail) > 1500:
            trail += "\n... (truncated)"
        parts.append("\n## Lessons from Previous Runs")
        parts.append(trail)

    return "\n".join(parts)


def build_system_append_v2(
    station: StationSpec,
    scent_trail: Optional[str] = None,
    repo_root: Optional[Path] = None,
    policy_invariants_ref: Optional[List[str]] = None,
) -> str:
    """Build the v2 system prompt append with policy fragment loading.

    V2 enhancements over build_system_append:
    - Loads policy invariants from referenced fragment files
    - Includes station-specific invariants after global ones
    - Better structured output with clear sections

    Args:
        station: The station specification.
        scent_trail: Optional cross-run wisdom content.
        repo_root: Repository root for fragment loading.
        policy_invariants_ref: List of fragment paths for policy invariants.

    Returns:
        Combined system prompt append text.
    """
    parts: List[str] = []

    # 1. Station identity (who you are)
    if station.identity.system_append:
        parts.append(station.identity.system_append.strip())

    # 2. Load policy invariants from referenced fragments
    if policy_invariants_ref:
        fragment_content = load_fragments(
            policy_invariants_ref,
            repo_root,
            separator="\n\n",
        )
        if fragment_content:
            parts.append("\n## Policy Invariants (From Fragments)")
            parts.append(fragment_content)

    # 3. Station-specific invariants (always apply)
    if station.invariants:
        parts.append("\n## Station Invariants (Non-Negotiable)")
        for inv in station.invariants:
            parts.append(f"- {inv}")

    # 4. Scent trail (wisdom from previous runs, truncated)
    if scent_trail:
        trail = scent_trail[:1500]
        if len(scent_trail) > 1500:
            trail += "\n... (truncated)"
        parts.append("\n## Lessons from Previous Runs")
        parts.append(trail)

    return "\n".join(parts)


def build_user_prompt(
    station: StationSpec,
    step: FlowStep,
    context_pack: Optional["ContextPack"],
    run_base: Path,
    repo_root: Optional[Path] = None,
) -> str:
    """Build the user prompt from station template + context.

    Constructs a focused, bounded prompt:
    1. Fragments (shared rules, loaded and concatenated)
    2. Objective (from flow step)
    3. Context pointers (from ContextPack)
    4. Input/Output requirements
    5. Handoff instructions

    Args:
        station: The station specification.
        step: The flow step being executed.
        context_pack: Hydrated context with artifacts and envelopes.
        run_base: Run base directory.
        repo_root: Repository root for fragment loading.

    Returns:
        Complete user prompt text.
    """
    parts: List[str] = []

    # 1. Load and concatenate fragments
    if station.runtime_prompt.fragments:
        parts.append("## Guidelines\n")
        for frag_path in station.runtime_prompt.fragments:
            try:
                frag_content = load_fragment(frag_path, repo_root)
                parts.append(frag_content.strip())
                parts.append("")
            except FileNotFoundError:
                logger.warning("Fragment not found: %s", frag_path)

    # 2. Objective (from step)
    parts.append("## Objective\n")
    parts.append(step.objective)
    if step.scope:
        parts.append(f"\n**Scope:** {step.scope}")
    parts.append("")

    # 3. Context pointers (from ContextPack)
    if context_pack:
        if context_pack.upstream_artifacts:
            parts.append("## Available Artifacts\n")
            parts.append("Read these files for context:")
            for name, path in context_pack.upstream_artifacts.items():
                parts.append(f"- `{path}` ({name})")
            parts.append("")

        if context_pack.previous_envelopes:
            parts.append("## Previous Steps\n")
            for env in context_pack.previous_envelopes[-5:]:  # Last 5 envelopes
                status = env.status.upper() if env.status else "?"
                parts.append(f"- **{env.step_id}** [{status}]: {env.summary[:200] if env.summary else 'No summary'}")
            parts.append("")

    # 4. Input/Output requirements
    # Merge station IO with step-specific overrides
    required_inputs = list(station.io.required_inputs) + list(step.inputs)
    required_outputs = list(station.io.required_outputs) + list(step.outputs)

    if required_inputs:
        parts.append("## Required Inputs\n")
        parts.append("These artifacts must exist and be read:")
        for inp in required_inputs:
            parts.append(f"- `{inp}`")
        parts.append("")

    if required_outputs:
        parts.append("## Required Outputs\n")
        parts.append("You MUST produce these artifacts:")
        for out in required_outputs:
            parts.append(f"- `{out}`")
        parts.append("")

    # 5. Template rendering (if station has a template)
    if station.runtime_prompt.template:
        variables = {
            "step": {
                "id": step.id,
                "objective": step.objective,
                "scope": step.scope or "",
            },
            "station": {
                "id": station.id,
                "title": station.title,
            },
            "run": {
                "base": str(run_base),
            },
            "context": {
                "pointers": ", ".join(context_pack.upstream_artifacts.keys()) if context_pack else "",
            },
        }
        rendered = render_template(station.runtime_prompt.template, variables)
        parts.append(rendered)
        parts.append("")

    # 6. Handoff instructions (always appended)
    handoff_path = render_template(
        station.handoff.path_template,
        {"run": {"base": str(run_base)}, "step": {"id": step.id}},
    )
    parts.append("## Finalization (REQUIRED)\n")
    parts.append(f"When complete, write a handoff file to: `{handoff_path}`")
    parts.append("\nThe file MUST be valid JSON with these fields:")
    parts.append("```json")
    parts.append("{")
    for i, field in enumerate(station.handoff.required_fields):
        comma = "," if i < len(station.handoff.required_fields) - 1 else ""
        if field == "status":
            parts.append(f'  "status": "VERIFIED | UNVERIFIED | PARTIAL | BLOCKED"{comma}')
        elif field == "summary":
            parts.append(f'  "summary": "2-paragraph summary of work done"{comma}')
        elif field == "artifacts":
            parts.append(f'  "artifacts": {{"name": "relative/path"}}{comma}')
        elif field == "can_further_iteration_help":
            parts.append(f'  "can_further_iteration_help": "yes | no"{comma}')
        elif field == "proposed_next_step":
            parts.append(f'  "proposed_next_step": "step_id or null"{comma}')
        elif field == "confidence":
            parts.append(f'  "confidence": 0.0 to 1.0{comma}')
        elif field == "blockers":
            parts.append(f'  "blockers": ["blocker1", "blocker2"]{comma}')
    parts.append("}")
    parts.append("```")
    parts.append("\n**DO NOT** finish without writing this file.")

    return "\n".join(parts)


# =============================================================================
# SpecCompiler
# =============================================================================


def merge_verification_requirements(
    station: StationSpec,
    step: FlowStep,
    run_base: Path,
    variables: Dict[str, Any],
) -> VerificationRequirements:
    """Merge station and step verification requirements.

    Station provides defaults; step can override or extend.

    Args:
        station: Station specification with default verification.
        step: Step specification with potential overrides.
        run_base: Run base path for template resolution.
        variables: Template variables for path resolution.

    Returns:
        Merged VerificationRequirements with resolved paths.
    """
    # Collect required artifacts from station IO and step outputs
    artifacts: List[str] = []

    # Station required outputs become verification requirements
    for output_path in station.io.required_outputs:
        resolved = render_template(output_path, variables)
        artifacts.append(resolved)

    # Step outputs also become verification requirements
    for output_path in step.outputs:
        resolved = render_template(output_path, variables)
        if resolved not in artifacts:
            artifacts.append(resolved)

    # Verification commands from step sdk_overrides (if specified)
    commands: List[str] = []
    if step.sdk_overrides.get("verification_commands"):
        for cmd in step.sdk_overrides["verification_commands"]:
            commands.append(render_template(cmd, variables))

    return VerificationRequirements(
        required_artifacts=tuple(artifacts),
        verification_commands=tuple(commands),
    )


def resolve_handoff_contract(
    station: StationSpec,
    variables: Dict[str, Any],
) -> HandoffContract:
    """Resolve the handoff contract with template substitution.

    Args:
        station: Station specification with handoff template.
        variables: Template variables for path resolution.

    Returns:
        HandoffContract with resolved path.
    """
    resolved_path = render_template(station.handoff.path_template, variables)

    return HandoffContract(
        path=resolved_path,
        required_fields=station.handoff.required_fields,
    )


class SpecCompiler:
    """Compiler that produces PromptPlans from specs.

    Usage:
        compiler = SpecCompiler(repo_root)
        plan = compiler.compile(flow_id, step_id, context_pack, run_base)
    """

    def __init__(self, repo_root: Optional[Path] = None):
        """Initialize the spec compiler.

        Args:
            repo_root: Repository root path for loading specs.
        """
        self.repo_root = repo_root
        self._scent_trail: Optional[str] = None
        self._scent_trail_loaded = False

    def _load_scent_trail(self) -> Optional[str]:
        """Load the scent trail (wisdom from previous runs)."""
        if self._scent_trail_loaded:
            return self._scent_trail

        self._scent_trail_loaded = True

        if not self.repo_root:
            return None

        # Try multiple locations
        paths = [
            self.repo_root / ".runs" / "_wisdom" / "latest.md",
            self.repo_root / "swarm" / "runs" / "_wisdom" / "latest.md",
        ]

        for path in paths:
            if path.exists():
                try:
                    content = path.read_text(encoding="utf-8").strip()
                    if content:
                        self._scent_trail = content
                        logger.debug("Loaded scent trail from %s", path)
                        return content
                except (OSError, IOError) as e:
                    logger.debug("Failed to read scent trail: %s", e)

        return None

    def compile(
        self,
        flow_id: str,
        step_id: str,
        context_pack: Optional["ContextPack"],
        run_base: Path,
        cwd: Optional[str] = None,
        policy_invariants_ref: Optional[List[str]] = None,
        use_v2: bool = True,
    ) -> PromptPlan:
        """Compile a PromptPlan for a flow step.

        V2 enhancements:
        - Includes verification requirements (merged from station + step)
        - Includes resolved handoff contract
        - Includes flow_key for routing
        - Supports policy invariants from fragment references
        - Full template resolution for paths

        Args:
            flow_id: Flow specification ID (e.g., "3-build").
            step_id: Step ID within the flow.
            context_pack: Hydrated context with artifacts and envelopes.
            run_base: Run base directory for outputs.
            cwd: Working directory for SDK. Defaults to repo_root.
            policy_invariants_ref: Fragment paths for policy invariants.
            use_v2: Use v2 system_append with policy loading (default True).

        Returns:
            Compiled PromptPlan ready for SDK execution.

        Raises:
            FileNotFoundError: If flow or station spec not found.
            ValueError: If step not found in flow.
        """
        # Load flow spec
        flow = load_flow(flow_id, self.repo_root)

        # Extract flow key for routing
        flow_key = extract_flow_key(flow_id)

        # Find step in flow
        step = None
        for s in flow.steps:
            if s.id == step_id:
                step = s
                break

        if not step:
            raise ValueError(f"Step {step_id} not found in flow {flow_id}")

        # Load station spec
        station = load_station(step.station, self.repo_root)

        # Load scent trail
        scent_trail = self._load_scent_trail()

        # Build template variables for path resolution
        variables = {
            "run": {
                "base": str(run_base),
            },
            "step": {
                "id": step.id,
                "objective": step.objective,
                "scope": step.scope or "",
            },
            "flow": {
                "id": flow.id,
                "key": flow_key,
                "version": str(flow.version),
            },
            "station": {
                "id": station.id,
                "title": station.title,
                "version": str(station.version),
            },
        }

        # Build system append (v1 or v2)
        if use_v2:
            # Default policy invariants if not specified
            if policy_invariants_ref is None:
                policy_invariants_ref = list(station.runtime_prompt.fragments)

            system_append = build_system_append_v2(
                station=station,
                scent_trail=scent_trail,
                repo_root=self.repo_root,
                policy_invariants_ref=policy_invariants_ref,
            )
        else:
            system_append = build_system_append(station, scent_trail)

        # Build user prompt
        user_prompt = build_user_prompt(
            station=station,
            step=step,
            context_pack=context_pack,
            run_base=run_base,
            repo_root=self.repo_root,
        )

        # Compute prompt hash for traceability (SHA256 of combined prompts)
        prompt_hash = hashlib.sha256(
            (system_append + user_prompt).encode("utf-8")
        ).hexdigest()[:16]

        # Merge SDK settings (station + step overrides)
        model = step.sdk_overrides.get("model", station.sdk.model)
        permission_mode = step.sdk_overrides.get("permission_mode", station.sdk.permission_mode)
        allowed_tools = tuple(step.sdk_overrides.get("allowed_tools", station.sdk.allowed_tools))
        max_turns = step.sdk_overrides.get("max_turns", station.sdk.max_turns)
        sandbox_enabled = step.sdk_overrides.get("sandbox_enabled", station.sdk.sandbox.enabled)

        # Determine cwd
        effective_cwd = cwd or (str(self.repo_root) if self.repo_root else str(Path.cwd()))

        # V2: Merge verification requirements from station and step
        verification = merge_verification_requirements(
            station=station,
            step=step,
            run_base=run_base,
            variables=variables,
        )

        # V2: Resolve handoff contract with template substitution
        handoff = resolve_handoff_contract(
            station=station,
            variables=variables,
        )

        return PromptPlan(
            # Traceability
            station_id=station.id,
            station_version=station.version,
            flow_id=flow.id,
            flow_version=flow.version,
            step_id=step.id,
            prompt_hash=prompt_hash,
            # SDK Options
            model=model,
            permission_mode=permission_mode,
            allowed_tools=allowed_tools,
            max_turns=max_turns,
            sandbox_enabled=sandbox_enabled,
            cwd=effective_cwd,
            # Prompt Content
            system_append=system_append,
            user_prompt=user_prompt,
            # Metadata
            compiled_at=datetime.now(timezone.utc).isoformat(),
            context_pack_size=len(context_pack.previous_envelopes) if context_pack else 0,
            # V2 additions
            verification=verification,
            handoff=handoff,
            flow_key=flow_key,
        )

    def compile_from_context(
        self,
        ctx: "StepContext",
        flow_id: str,
    ) -> PromptPlan:
        """Compile a PromptPlan from a StepContext.

        Convenience method for engine integration.

        Args:
            ctx: Step execution context.
            flow_id: Flow specification ID.

        Returns:
            Compiled PromptPlan.
        """
        context_pack = ctx.extra.get("context_pack") if ctx.extra else None
        return self.compile(
            flow_id=flow_id,
            step_id=ctx.step_id,
            context_pack=context_pack,
            run_base=ctx.run_base,
            cwd=str(ctx.repo_root) if ctx.repo_root else None,
        )

    # =========================================================================
    # FlowGraph Compilation Methods
    # =========================================================================

    def compile_step(
        self,
        node: FlowNode,
        template: Optional[StepTemplate],
        context: CompileContext,
    ) -> StepPlan:
        """Compile a single FlowNode into a StepPlan.

        This is the core method for FlowGraph-based compilation. It takes a
        node from the FlowGraph, resolves its template (if any), and produces
        a StepPlan ready for SDK execution.

        Args:
            node: The FlowNode from the FlowGraph.
            template: Optional StepTemplate referenced by the node.
            context: Compilation context with run information.

        Returns:
            StepPlan ready for SDK execution.

        Raises:
            FileNotFoundError: If station spec not found.
            ValueError: If required parameters are missing.
        """
        # Determine station ID from template or node overrides
        station_id = self._resolve_station_id(node, template)

        # Load station spec
        station = load_station(station_id, context.repo_root)

        # Build objective from template + node params
        objective = self._resolve_objective(node, template)

        # Build template variables
        variables = self._build_variables(
            node=node,
            template=template,
            station=station,
            context=context,
        )

        # Build system prompt
        system_prompt = self.build_system_prompt(station, context.scent_trail)

        # Build user prompt
        user_prompt = self.build_user_prompt(
            objective=objective,
            context_pack=context.context_pack,
            io_contract=self._build_io_contract(node, template, station),
            variables=variables,
        )

        # Process fragment includes in both prompts
        system_prompt = self._process_fragment_includes(system_prompt, context.repo_root)
        user_prompt = self._process_fragment_includes(user_prompt, context.repo_root)

        # Collect fragment references for audit trail
        fragments_used = self._collect_fragment_references(
            station.runtime_prompt.fragments,
            context.repo_root,
        )

        # Compute prompt hash
        prompt_hash = self.compute_prompt_hash(system_prompt, user_prompt)

        # Build output schema
        output_schema = self._build_output_schema(station)

        # Resolve handoff path
        handoff_path = render_template(
            station.handoff.path_template,
            variables,
        )

        # Merge verification requirements
        verification = self._build_verification_from_node(
            node, template, station, variables
        )

        # Build SDK options from station with node overrides
        sdk_options = self._merge_sdk_options(station, node)

        return StepPlan(
            step_id=node.node_id,
            station_id=station.id,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            allowed_tools=sdk_options["allowed_tools"],
            permission_mode=sdk_options["permission_mode"],
            max_turns=sdk_options["max_turns"],
            output_schema=output_schema,
            prompt_hash=prompt_hash,
            model=sdk_options["model"],
            model_tier=sdk_options["model"],
            sandbox_enabled=sdk_options["sandbox_enabled"],
            cwd=str(context.repo_root) if context.repo_root else "",
            station_version=station.version,
            flow_id=context.run_id,
            flow_version=1,
            flow_key=context.run_id.split("-")[0] if context.run_id else "",
            compiled_at=datetime.now(timezone.utc).isoformat(),
            compiler_version=COMPILER_VERSION,
            handoff_path=handoff_path,
            required_fields=station.handoff.required_fields,
            verification=verification,
            fragments_used=tuple(fragments_used),
        )

    def resolve_template(
        self,
        node: FlowNode,
        template_registry: Optional[Dict[str, StepTemplate]] = None,
    ) -> Optional[StepTemplate]:
        """Resolve the StepTemplate for a FlowNode.

        Looks up the template by ID from the registry or loads it from disk.
        Returns None if the node has no template_id.

        Args:
            node: The FlowNode to resolve template for.
            template_registry: Optional pre-loaded template registry.

        Returns:
            Resolved StepTemplate or None if no template referenced.
        """
        if not node.template_id:
            return None

        # Check registry first
        if template_registry and node.template_id in template_registry:
            return template_registry[node.template_id]

        # Try to load from disk
        return self._load_template(node.template_id)

    def build_system_prompt(
        self,
        station: StationSpec,
        scent_trail: Optional[str] = None,
    ) -> str:
        """Build the complete system prompt from station spec.

        The system prompt follows this structure:
        1. Claude preset (default or custom)
        2. Station identity (who you are)
        3. Station invariants (non-negotiable rules)
        4. Scent trail (wisdom from previous runs)

        Args:
            station: The station specification.
            scent_trail: Optional cross-run wisdom.

        Returns:
            Complete system prompt string.
        """
        parts: List[str] = []

        # 1. Claude preset (if custom)
        preset = getattr(station.identity, 'preset', 'default')
        if preset == "custom":
            preset_content = getattr(station.identity, 'preset_content', '')
            if preset_content:
                parts.append(preset_content)
        elif preset in SYSTEM_PRESETS:
            parts.append(SYSTEM_PRESETS[preset])

        # 2. Station identity append
        if station.identity.system_append:
            parts.append("\n## Your Role\n")
            parts.append(station.identity.system_append.strip())

        # 3. Invariants
        if station.invariants:
            parts.append("\n## Invariants (Non-Negotiable)\n")
            for inv in station.invariants:
                parts.append(f"- {inv}")

        # 4. Scent trail
        if scent_trail:
            trail = scent_trail[:1500]
            if len(scent_trail) > 1500:
                trail += "\n... (truncated)"
            parts.append("\n## Lessons from Previous Runs\n")
            parts.append(trail)

        return "\n".join(parts)

    def build_user_prompt(
        self,
        objective: str,
        context_pack: Optional[Dict[str, Any]],
        io_contract: Dict[str, Any],
        variables: Dict[str, Any],
    ) -> str:
        """Build the user prompt from objective and context.

        The user prompt follows this structure:
        1. Guidelines (from fragments)
        2. Objective (what to do)
        3. Context pointers (what to read)
        4. IO contract (what to write where)
        5. Finalization instructions (handoff file)

        Args:
            objective: The step objective.
            context_pack: Hydrated context with artifacts.
            io_contract: Input/output requirements.
            variables: Template variables for substitution.

        Returns:
            Complete user prompt string.
        """
        parts: List[str] = []

        # 1. Objective
        parts.append("## Objective\n")
        rendered_objective = render_template(objective, variables)
        parts.append(rendered_objective)
        parts.append("")

        # 2. Context pointers
        if context_pack:
            upstream = context_pack.get("upstream_artifacts", {})
            if upstream:
                parts.append("## Available Artifacts\n")
                parts.append("Read these files for context:")
                for name, path in upstream.items():
                    parts.append(f"- `{path}` ({name})")
                parts.append("")

            envelopes = context_pack.get("previous_envelopes", [])
            if envelopes:
                parts.append("## Previous Steps\n")
                for env in envelopes[-5:]:
                    status = env.get("status", "?").upper()
                    summary = env.get("summary", "No summary")[:200]
                    step_id = env.get("step_id", "unknown")
                    parts.append(f"- **{step_id}** [{status}]: {summary}")
                parts.append("")

        # 3. IO contract
        required_inputs = io_contract.get("required_inputs", [])
        required_outputs = io_contract.get("required_outputs", [])

        if required_inputs:
            parts.append("## Required Inputs\n")
            parts.append("These artifacts must exist and be read:")
            for inp in required_inputs:
                resolved = render_template(inp, variables)
                parts.append(f"- `{resolved}`")
            parts.append("")

        if required_outputs:
            parts.append("## Required Outputs\n")
            parts.append("You MUST produce these artifacts:")
            for out in required_outputs:
                resolved = render_template(out, variables)
                parts.append(f"- `{resolved}`")
            parts.append("")

        # 4. Finalization instructions
        handoff_template = io_contract.get("handoff_template", "")
        required_fields = io_contract.get("required_fields", ["status", "summary", "artifacts"])

        if handoff_template:
            handoff_path = render_template(handoff_template, variables)
            parts.append("## Finalization (REQUIRED)\n")
            parts.append(f"When complete, write a handoff file to: `{handoff_path}`")
            parts.append("\nThe file MUST be valid JSON with these fields:")
            parts.append("```json")
            parts.append("{")
            for i, fld in enumerate(required_fields):
                comma = "," if i < len(required_fields) - 1 else ""
                if fld == "status":
                    parts.append(f'  "status": "VERIFIED | UNVERIFIED | PARTIAL | BLOCKED"{comma}')
                elif fld == "summary":
                    parts.append(f'  "summary": "2-paragraph summary of work done"{comma}')
                elif fld == "artifacts":
                    parts.append(f'  "artifacts": {{"name": "relative/path"}}{comma}')
                elif fld == "can_further_iteration_help":
                    parts.append(f'  "can_further_iteration_help": "yes | no"{comma}')
                else:
                    parts.append(f'  "{fld}": "..."{comma}')
            parts.append("}")
            parts.append("```")
            parts.append("\n**DO NOT** finish without writing this file.")

        return "\n".join(parts)

    def compute_prompt_hash(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> str:
        """Compute a deterministic hash for the prompt pair.

        The hash is used for:
        - Reproducibility: same inputs = same hash
        - Traceability: link execution to exact prompts
        - Caching: avoid recompilation if hash matches

        Args:
            system_prompt: The system prompt content.
            user_prompt: The user prompt content.

        Returns:
            16-character truncated SHA-256 hash.
        """
        combined = system_prompt + "\n---\n" + user_prompt
        full_hash = hashlib.sha256(combined.encode("utf-8")).hexdigest()
        return full_hash[:16]

    # =========================================================================
    # Private Helper Methods
    # =========================================================================

    def _resolve_station_id(
        self,
        node: FlowNode,
        template: Optional[StepTemplate],
    ) -> str:
        """Resolve the station ID from node or template."""
        # Node overrides take precedence
        if "station_id" in node.overrides:
            return node.overrides["station_id"]

        # Template provides default
        if template:
            return template.station_id

        # Fallback: derive from node_id
        return node.node_id

    def _resolve_objective(
        self,
        node: FlowNode,
        template: Optional[StepTemplate],
    ) -> str:
        """Resolve the objective from template and node params."""
        if not template:
            return node.params.get("objective", f"Execute step {node.node_id}")

        # Get base objective from template
        obj_spec = template.objective
        base_template = obj_spec.get("template", "")

        # Apply node params to template
        merged_params = {**template.parameters, **node.params}
        return render_template(base_template, merged_params)

    def _build_variables(
        self,
        node: FlowNode,
        template: Optional[StepTemplate],
        station: StationSpec,
        context: CompileContext,
    ) -> Dict[str, Any]:
        """Build template variables for substitution."""
        return {
            "run": {
                "base": str(context.run_base),
                "id": context.run_id,
            },
            "step": {
                "id": node.node_id,
            },
            "station": {
                "id": station.id,
                "title": station.title,
                "version": str(station.version),
            },
            "params": node.params,
            "flow": {
                "key": context.run_id.split("-")[0] if context.run_id else "",
            },
        }

    def _build_io_contract(
        self,
        node: FlowNode,
        template: Optional[StepTemplate],
        station: StationSpec,
    ) -> Dict[str, Any]:
        """Build the IO contract from node, template, and station."""
        required_inputs = list(station.io.required_inputs)
        required_outputs = list(station.io.required_outputs)

        # Template IO overrides
        if template and template.io_overrides:
            io = template.io_overrides
            required_inputs.extend(io.get("required_inputs", []))
            required_outputs.extend(io.get("required_outputs", []))

        # Node overrides
        if "inputs" in node.overrides:
            required_inputs.extend(node.overrides["inputs"])
        if "outputs" in node.overrides:
            required_outputs.extend(node.overrides["outputs"])

        return {
            "required_inputs": list(set(required_inputs)),  # Dedupe
            "required_outputs": list(set(required_outputs)),
            "handoff_template": station.handoff.path_template,
            "required_fields": list(station.handoff.required_fields),
        }

    def _build_output_schema(self, station: StationSpec) -> Dict[str, Any]:
        """Build JSON schema for structured output."""
        return {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "required": list(station.handoff.required_fields),
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["VERIFIED", "UNVERIFIED", "PARTIAL", "BLOCKED"],
                },
                "summary": {"type": "string"},
                "artifacts": {
                    "type": "object",
                    "additionalProperties": {"type": "string"},
                },
                "can_further_iteration_help": {
                    "type": "string",
                    "enum": ["yes", "no"],
                },
                "proposed_next_step": {"type": ["string", "null"]},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "blockers": {"type": "array", "items": {"type": "string"}},
            },
        }

    def _build_verification_from_node(
        self,
        node: FlowNode,
        template: Optional[StepTemplate],
        station: StationSpec,
        variables: Dict[str, Any],
    ) -> VerificationRequirements:
        """Build verification requirements from node context."""
        artifacts: List[str] = []
        commands: List[str] = []

        # From station
        for out in station.io.required_outputs:
            artifacts.append(render_template(out, variables))

        # From template constraints
        if template and template.constraints:
            for artifact in template.constraints.get("required_artifacts", []):
                resolved = render_template(artifact, variables)
                if resolved not in artifacts:
                    artifacts.append(resolved)
            commands.extend(template.constraints.get("verification_commands", []))

        # From node overrides
        if "verification" in node.overrides:
            v = node.overrides["verification"]
            artifacts.extend(v.get("required_artifacts", []))
            commands.extend(v.get("verification_commands", []))

        return VerificationRequirements(
            required_artifacts=tuple(artifacts),
            verification_commands=tuple(commands),
        )

    def _merge_sdk_options(
        self,
        station: StationSpec,
        node: FlowNode,
    ) -> Dict[str, Any]:
        """Merge SDK options from station with node overrides."""
        sdk = station.sdk

        return {
            "model": node.overrides.get("model", sdk.model),
            "permission_mode": node.overrides.get("permission_mode", sdk.permission_mode),
            "allowed_tools": tuple(node.overrides.get("allowed_tools", sdk.allowed_tools)),
            "max_turns": node.overrides.get("max_turns", sdk.max_turns),
            "sandbox_enabled": node.overrides.get("sandbox_enabled", sdk.sandbox.enabled),
        }

    def _process_fragment_includes(
        self,
        content: str,
        repo_root: Optional[Path],
    ) -> str:
        """Process {{fragment:path}} includes in content.

        Supports syntax like:
        - {{fragment:common/status_model}}
        - {{fragment:microloop/critic_never_fixes.md}}

        Args:
            content: Text with potential fragment includes.
            repo_root: Repository root for fragment loading.

        Returns:
            Content with fragment includes resolved.
        """
        pattern = r"\{\{fragment:([^}]+)\}\}"

        def replace_fragment(match: re.Match) -> str:
            frag_path = match.group(1).strip()
            # Add .md extension if missing
            if not frag_path.endswith(".md"):
                frag_path = f"{frag_path}.md"
            try:
                return load_fragment(frag_path, repo_root)
            except FileNotFoundError:
                logger.warning("Fragment include not found: %s", frag_path)
                return f"[Fragment not found: {frag_path}]"

        return re.sub(pattern, replace_fragment, content)

    def _collect_fragment_references(
        self,
        fragment_paths: Tuple[str, ...],
        repo_root: Optional[Path],
    ) -> List[FragmentReference]:
        """Collect fragment references for audit trail."""
        refs: List[FragmentReference] = []

        for frag_path in fragment_paths:
            try:
                content = load_fragment(frag_path, repo_root)
                content_hash = hashlib.sha256(content.encode()).hexdigest()[:12]
                refs.append(FragmentReference(
                    path=frag_path,
                    hash=content_hash,
                    version="",
                ))
            except FileNotFoundError:
                logger.warning("Fragment not found for audit: %s", frag_path)

        return refs

    @lru_cache(maxsize=32)
    def _load_template(self, template_id: str) -> Optional[StepTemplate]:
        """Load a StepTemplate from disk.

        Templates are stored in swarm/spec/templates/{template_id}.yaml

        Args:
            template_id: The template identifier.

        Returns:
            Loaded StepTemplate or None if not found.
        """
        if not self.repo_root:
            return None

        template_path = self.repo_root / "swarm" / "spec" / "templates" / f"{template_id}.yaml"

        if not template_path.exists():
            logger.debug("Template not found: %s", template_path)
            return None

        try:
            import yaml
            with open(template_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)

            return StepTemplate(
                id=data.get("id", template_id),
                version=data.get("version", 1),
                title=data.get("title", template_id),
                station_id=data.get("station_id", ""),
                objective=data.get("objective", {}),
                io_overrides=data.get("io_overrides", {}),
                routing_defaults=data.get("routing_defaults", {}),
                ui_defaults=data.get("ui_defaults", {}),
                constraints=data.get("constraints", {}),
                parameters=data.get("parameters", {}),
                tags=data.get("tags", []),
                category=data.get("category", "implementation"),
                deprecated=data.get("deprecated", False),
            )
        except Exception as e:
            logger.warning("Failed to load template %s: %s", template_id, e)
            return None

    # =========================================================================
    # Multi-Step Compilation
    # =========================================================================

    def compile_flow(
        self,
        flow_id: str,
        context: CompileContext,
    ) -> "MultiStepPromptPlan":
        """Compile a complete flow into a MultiStepPromptPlan.

        This compiles all steps in a flow, producing a plan that can be
        executed sequentially with context handoff between steps.

        Args:
            flow_id: Flow specification ID (e.g., "3-build").
            context: Compilation context with run information.

        Returns:
            MultiStepPromptPlan containing all step plans.
        """
        flow = load_flow(flow_id, context.repo_root)
        flow_key = extract_flow_key(flow_id)

        step_plans: List[StepPlan] = []
        spec_hashes: List[str] = []

        for step in flow.steps:
            # Create a FlowNode from the FlowStep
            node = FlowNode(
                node_id=step.id,
                template_id="",  # No template for direct FlowStep
                params={
                    "objective": step.objective,
                    "scope": step.scope or "",
                },
                overrides=step.sdk_overrides,
            )

            # Load station for this step
            station = load_station(step.station, context.repo_root)

            # Build plan using compile_step infrastructure
            step_plan = self._compile_flow_step(
                flow=flow,
                step=step,
                station=station,
                context=context,
                flow_key=flow_key,
            )

            step_plans.append(step_plan)
            spec_hashes.append(step_plan.prompt_hash)

        # Compute overall spec hash
        spec_hash = hashlib.sha256(
            "".join(spec_hashes).encode()
        ).hexdigest()[:16]

        return MultiStepPromptPlan(
            flow_id=flow_id,
            steps=step_plans,
            spec_hash=spec_hash,
            compiled_at=datetime.now(timezone.utc).isoformat(),
        )

    def _compile_flow_step(
        self,
        flow: FlowSpec,
        step: FlowStep,
        station: StationSpec,
        context: CompileContext,
        flow_key: str,
    ) -> StepPlan:
        """Compile a single FlowStep into a StepPlan."""
        # Build variables
        variables = {
            "run": {"base": str(context.run_base)},
            "step": {"id": step.id, "objective": step.objective, "scope": step.scope or ""},
            "flow": {"id": flow.id, "key": flow_key, "version": str(flow.version)},
            "station": {"id": station.id, "title": station.title, "version": str(station.version)},
        }

        # Build system prompt
        system_prompt = self.build_system_prompt(station, context.scent_trail)

        # Build IO contract
        io_contract = {
            "required_inputs": list(station.io.required_inputs) + list(step.inputs),
            "required_outputs": list(station.io.required_outputs) + list(step.outputs),
            "handoff_template": station.handoff.path_template,
            "required_fields": list(station.handoff.required_fields),
        }

        # Build user prompt
        user_prompt = self.build_user_prompt(
            objective=step.objective,
            context_pack=None,  # Will be populated at runtime
            io_contract=io_contract,
            variables=variables,
        )

        # Process fragment includes
        system_prompt = self._process_fragment_includes(system_prompt, context.repo_root)
        user_prompt = self._process_fragment_includes(user_prompt, context.repo_root)

        # Collect fragments
        fragments_used = self._collect_fragment_references(
            station.runtime_prompt.fragments, context.repo_root
        )

        # Compute hash
        prompt_hash = self.compute_prompt_hash(system_prompt, user_prompt)

        # Build output schema
        output_schema = self._build_output_schema(station)

        # Resolve handoff path
        handoff_path = render_template(station.handoff.path_template, variables)

        # Build verification
        verification = merge_verification_requirements(
            station, step, context.run_base, variables
        )

        # SDK options
        model = step.sdk_overrides.get("model", station.sdk.model)
        permission_mode = step.sdk_overrides.get("permission_mode", station.sdk.permission_mode)
        allowed_tools = tuple(step.sdk_overrides.get("allowed_tools", station.sdk.allowed_tools))
        max_turns = step.sdk_overrides.get("max_turns", station.sdk.max_turns)
        sandbox_enabled = step.sdk_overrides.get("sandbox_enabled", station.sdk.sandbox.enabled)

        return StepPlan(
            step_id=step.id,
            station_id=station.id,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            allowed_tools=allowed_tools,
            permission_mode=permission_mode,
            max_turns=max_turns,
            output_schema=output_schema,
            prompt_hash=prompt_hash,
            model=model,
            model_tier=model,
            sandbox_enabled=sandbox_enabled,
            cwd=str(context.repo_root) if context.repo_root else "",
            station_version=station.version,
            flow_id=flow.id,
            flow_version=flow.version,
            flow_key=flow_key,
            compiled_at=datetime.now(timezone.utc).isoformat(),
            compiler_version=COMPILER_VERSION,
            handoff_path=handoff_path,
            required_fields=station.handoff.required_fields,
            verification=verification,
            fragments_used=tuple(fragments_used),
        )


@dataclass(frozen=True)
class MultiStepPromptPlan:
    """Compiled plan for a complete flow with multiple steps.

    This represents the output of compile_flow() and contains all the
    StepPlans needed to execute a flow sequentially.
    """
    flow_id: str
    steps: List[StepPlan]
    spec_hash: str  # Hash of all source specs
    compiled_at: str  # ISO timestamp

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "flow_id": self.flow_id,
            "steps": [s.to_dict() for s in self.steps],
            "spec_hash": self.spec_hash,
            "compiled_at": self.compiled_at,
        }


# =============================================================================
# Convenience Function
# =============================================================================


def compile_prompt(
    flow_id: str,
    step_id: str,
    context_pack: Optional["ContextPack"],
    run_base: Path,
    repo_root: Optional[Path] = None,
    cwd: Optional[str] = None,
    policy_invariants_ref: Optional[List[str]] = None,
    use_v2: bool = True,
) -> PromptPlan:
    """Compile a PromptPlan for a flow step (convenience function).

    V2 enhancements:
    - Includes verification requirements (merged from station + step)
    - Includes resolved handoff contract
    - Includes flow_key for routing
    - Supports policy invariants from fragment references

    Args:
        flow_id: Flow specification ID (e.g., "3-build").
        step_id: Step ID within the flow.
        context_pack: Hydrated context with artifacts and envelopes.
        run_base: Run base directory for outputs.
        repo_root: Repository root for loading specs.
        cwd: Working directory for SDK.
        policy_invariants_ref: Fragment paths for policy invariants.
        use_v2: Use v2 system_append with policy loading (default True).

    Returns:
        Compiled PromptPlan ready for SDK execution.
    """
    compiler = SpecCompiler(repo_root)
    return compiler.compile(
        flow_id=flow_id,
        step_id=step_id,
        context_pack=context_pack,
        run_base=run_base,
        cwd=cwd,
        policy_invariants_ref=policy_invariants_ref,
        use_v2=use_v2,
    )


# =============================================================================
# Template Library Functions (WP2: Palette-Ready Templates)
# =============================================================================


@dataclass
class TemplateMetadata:
    """Metadata for a step template, suitable for palette display.

    This is a lightweight structure returned by list_templates() for
    UI rendering without loading the full template specification.
    """
    id: str
    name: str
    description: str
    category: str
    station_id: str
    tags: List[str]
    version: int
    ui: Dict[str, Any]


@dataclass
class ExpandedTemplate:
    """Result of expand_template() - a plain node configuration.

    After template expansion, the orchestrator sees plain nodes with:
    - station_id: Which station to use
    - objective: Resolved objective string (parameters substituted)
    - routing: Routing configuration
    - io: Input/output configuration

    Templates are UI ergonomics, not runtime magic.
    """
    station_id: str
    objective: str
    routing: Dict[str, Any]
    io: Dict[str, Any]
    parameters: Dict[str, Any]  # Resolved parameter values


def _get_template_dirs(repo_root: Optional[Path] = None) -> List[Path]:
    """Get directories to search for templates.

    Searches in order:
    1. swarm/specs/templates/ (new location, JSON files)
    2. swarm/spec/templates/ (legacy location, YAML files)

    Args:
        repo_root: Repository root path. If None, uses current directory.

    Returns:
        List of template directories that exist.
    """
    if repo_root is None:
        repo_root = Path.cwd()

    dirs = [
        repo_root / "swarm" / "specs" / "templates",  # Primary: JSON templates
        repo_root / "swarm" / "spec" / "templates",   # Legacy: YAML templates
    ]

    return [d for d in dirs if d.exists()]


def _load_template_file(template_path: Path) -> Optional[Dict[str, Any]]:
    """Load a template file (JSON or YAML).

    Args:
        template_path: Path to template file.

    Returns:
        Parsed template data or None if loading fails.
    """
    try:
        if template_path.suffix == ".json":
            with open(template_path, "r", encoding="utf-8") as f:
                return json.load(f)
        elif template_path.suffix in (".yaml", ".yml"):
            import yaml
            with open(template_path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f)
        else:
            logger.warning("Unknown template format: %s", template_path)
            return None
    except Exception as e:
        logger.warning("Failed to load template %s: %s", template_path, e)
        return None


def load_template(
    template_id: str,
    repo_root: Optional[Path] = None,
) -> Optional[Dict[str, Any]]:
    """Load a template by ID from the template library.

    Searches both JSON (swarm/specs/templates/) and YAML (swarm/spec/templates/)
    locations. JSON takes precedence if both exist.

    Args:
        template_id: Template identifier (kebab-case).
        repo_root: Repository root path.

    Returns:
        Template data dictionary or None if not found.
    """
    for template_dir in _get_template_dirs(repo_root):
        # Try JSON first (primary format)
        json_path = template_dir / f"{template_id}.json"
        if json_path.exists():
            return _load_template_file(json_path)

        # Fall back to YAML (legacy format)
        yaml_path = template_dir / f"{template_id}.yaml"
        if yaml_path.exists():
            return _load_template_file(yaml_path)

        yml_path = template_dir / f"{template_id}.yml"
        if yml_path.exists():
            return _load_template_file(yml_path)

    logger.debug("Template not found: %s", template_id)
    return None


def list_templates(
    repo_root: Optional[Path] = None,
    category: Optional[str] = None,
    tags: Optional[List[str]] = None,
) -> List[TemplateMetadata]:
    """List all available templates with metadata for palette display.

    This is the primary function for populating the Flow Studio template palette.
    Returns lightweight metadata suitable for UI rendering.

    Args:
        repo_root: Repository root path.
        category: Optional filter by category.
        tags: Optional filter by tags (matches if any tag present).

    Returns:
        List of TemplateMetadata sorted by category and palette_order.
    """
    templates: List[TemplateMetadata] = []
    seen_ids: set = set()

    for template_dir in _get_template_dirs(repo_root):
        # Scan for JSON and YAML files
        for pattern in ("*.json", "*.yaml", "*.yml"):
            for template_path in template_dir.glob(pattern):
                data = _load_template_file(template_path)
                if not data:
                    continue

                template_id = data.get("id", template_path.stem)

                # Skip duplicates (JSON takes precedence)
                if template_id in seen_ids:
                    continue
                seen_ids.add(template_id)

                # Skip deprecated templates
                if data.get("deprecated", False):
                    continue

                # Apply category filter
                template_category = data.get("category", "custom")
                if category and template_category != category:
                    continue

                # Apply tags filter
                template_tags = data.get("tags", [])
                if tags and not any(t in template_tags for t in tags):
                    continue

                # Extract UI defaults
                ui = data.get("ui", data.get("ui_defaults", {}))

                templates.append(TemplateMetadata(
                    id=template_id,
                    name=data.get("name", data.get("title", template_id)),
                    description=data.get("description", ""),
                    category=template_category,
                    station_id=data.get("station_id", ""),
                    tags=template_tags,
                    version=data.get("version", 1),
                    ui=ui,
                ))

    # Sort by category, then palette_order, then name
    def sort_key(t: TemplateMetadata) -> tuple:
        order = t.ui.get("palette_order", 999)
        return (t.category, order, t.name)

    return sorted(templates, key=sort_key)


def expand_template(
    template_id: str,
    params: Optional[Dict[str, Any]] = None,
    repo_root: Optional[Path] = None,
) -> Optional[ExpandedTemplate]:
    """Expand a template with parameters into a plain node configuration.

    This is the core template compilation function. It takes a template_id
    and user-provided parameters, and returns a fully resolved configuration
    that the orchestrator can use directly.

    Key principle: Templates are UI ergonomics, not runtime magic. After
    expansion, the orchestrator sees plain nodes.

    Args:
        template_id: Template identifier.
        params: User-provided parameter values (merged with defaults).
        repo_root: Repository root path.

    Returns:
        ExpandedTemplate with resolved station_id, objective, routing, and IO.
        Returns None if template not found.

    Example:
        >>> result = expand_template("microloop-writer", {"artifact_type": "test plan"})
        >>> print(result.station_id)
        'requirements-author'
        >>> print(result.objective)
        'Write test plan based on upstream context...'
    """
    template_data = load_template(template_id, repo_root)
    if not template_data:
        return None

    # Merge parameters: user params override template defaults
    param_defs = template_data.get("parameters", [])
    resolved_params: Dict[str, Any] = {}

    # Start with defaults from parameter definitions
    for param_def in param_defs:
        if isinstance(param_def, dict):
            param_name = param_def.get("name", "")
            if param_name and "default" in param_def:
                resolved_params[param_name] = param_def["default"]

    # Override with user-provided params
    if params:
        resolved_params.update(params)

    # Resolve objective template with parameters
    default_objective = template_data.get("default_objective", "")
    objective = render_template(default_objective, resolved_params)

    # Get routing defaults
    routing = template_data.get("routing_defaults", {
        "kind": "linear",
        "on_verified": "advance",
        "on_unverified": "advance_with_concerns",
    })

    # Get IO schema
    io_schema = template_data.get("io_schema", {})
    io = {
        "additional_inputs": io_schema.get("additional_inputs", []),
        "additional_outputs": io_schema.get("additional_outputs", []),
    }

    # Resolve any template variables in IO paths
    io["additional_inputs"] = [
        render_template(path, {"params": resolved_params})
        for path in io["additional_inputs"]
    ]
    io["additional_outputs"] = [
        render_template(path, {"params": resolved_params})
        for path in io["additional_outputs"]
    ]

    return ExpandedTemplate(
        station_id=template_data.get("station_id", ""),
        objective=objective,
        routing=routing,
        io=io,
        parameters=resolved_params,
    )


def expand_flow_graph(
    flow_data: Dict[str, Any],
    repo_root: Optional[Path] = None,
) -> Dict[str, Any]:
    """Expand all template references in a FlowGraph.

    This function takes a FlowGraph with nodes that may reference templates
    (via template_id field) and expands them into concrete node configurations.

    Key principle: Templates are design-time only. After expansion, the
    orchestrator sees plain nodes with all values inline.

    Args:
        flow_data: FlowGraph data dict (from JSON).
        repo_root: Repository root path.

    Returns:
        New FlowGraph dict with all template references expanded.
        Nodes with template_id will have their properties merged with
        the expanded template values.

    Example:
        >>> flow = {"nodes": [{"id": "step1", "template_id": "microloop-writer"}]}
        >>> expanded = expand_flow_graph(flow)
        >>> print(expanded["nodes"][0]["station_id"])
        'requirements-author'
    """
    import copy

    # Deep copy to avoid mutating input
    result = copy.deepcopy(flow_data)

    expanded_nodes = []
    for node in result.get("nodes", []):
        template_id = node.get("template_id")

        if template_id:
            # Expand template
            params = node.get("params", {})
            expanded = expand_template(template_id, params, repo_root)

            if expanded:
                # Merge expanded template into node
                # Node values override template defaults
                expanded_node = {
                    "id": node["id"],
                    "station_id": node.get("station_id") or expanded.station_id,
                    "objective": node.get("objective") or expanded.objective,
                    "agents": node.get("agents", [expanded.station_id] if expanded.station_id else []),
                    "role": node.get("role", expanded.objective),
                    "inputs": node.get("inputs", expanded.io.get("additional_inputs", [])),
                    "outputs": node.get("outputs", expanded.io.get("additional_outputs", [])),
                }

                # Copy routing from template if not overridden
                if "routing" not in node and expanded.routing:
                    expanded_node["routing"] = expanded.routing

                # Preserve other node fields
                for key in ["teaching_note", "teaching_highlight", "ui"]:
                    if key in node:
                        expanded_node[key] = node[key]

                # Mark as expanded for debugging
                expanded_node["_expanded_from_template"] = template_id
                expanded_node["_expansion_params"] = params

                expanded_nodes.append(expanded_node)
            else:
                # Template not found - keep node as-is with warning
                logger.warning(
                    "Template %s not found for node %s, keeping as-is",
                    template_id,
                    node.get("id"),
                )
                expanded_nodes.append(node)
        else:
            # No template reference - keep node as-is
            expanded_nodes.append(node)

    result["nodes"] = expanded_nodes
    return result


def get_template_categories(
    repo_root: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    """Get all template categories with counts for palette grouping.

    Args:
        repo_root: Repository root path.

    Returns:
        List of category info dicts with id, name, count, and order.
    """
    templates = list_templates(repo_root)

    # Count templates per category
    category_counts: Dict[str, int] = {}
    for t in templates:
        category_counts[t.category] = category_counts.get(t.category, 0) + 1

    # Define category display order and names
    category_info = {
        "microloop": {"name": "Microloop", "order": 1},
        "context": {"name": "Context Loading", "order": 2},
        "implementation": {"name": "Implementation", "order": 3},
        "critic": {"name": "Critics", "order": 4},
        "verification": {"name": "Verification", "order": 5},
        "gate": {"name": "Gates", "order": 6},
        "artifact": {"name": "Artifacts", "order": 7},
        "reporter": {"name": "Reporters", "order": 8},
        "custom": {"name": "Custom", "order": 99},
    }

    result = []
    for cat_id, count in sorted(category_counts.items()):
        info = category_info.get(cat_id, {"name": cat_id.title(), "order": 50})
        result.append({
            "id": cat_id,
            "name": info["name"],
            "count": count,
            "order": info["order"],
        })

    return sorted(result, key=lambda x: x["order"])
