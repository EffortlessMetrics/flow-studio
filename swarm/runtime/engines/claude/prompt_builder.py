"""
prompt_builder.py - Prompt construction for Claude step engine.

Handles:
- SpecCompiler-first prompt assembly (default, USE_SPEC_COMPILER=true)
- Agentic step prompt loading (fallback from swarm/prompts/agentic_steps/)
- Agent persona loading (fallback from .claude/agents/)
- ContextPack-first context injection
- History priority-aware budgeting
- Inline finalization prompt injection
- Scent Trail injection (wisdom from previous runs)

The SpecCompiler integration (default enabled) provides:
- Station-based identity and invariants
- Fragment-resolved guidelines
- Template-driven prompt composition
- Better traceability via prompt_hash

Set SWARM_USE_SPEC_COMPILER=false to disable and use legacy file-based loading.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from swarm.config.runtime_config import get_resolved_context_budgets
from swarm.runtime.flow_loader import load_agent_step_prompt
from swarm.runtime.history_priority import (
    HistoryPriority,
    get_priority_label,
    prioritize_history,
)

from ..models import HistoryTruncationInfo, StepContext

if TYPE_CHECKING:
    from swarm.runtime.context_pack import ContextPack
    from swarm.spec.types import PromptPlan

logger = logging.getLogger(__name__)

# =============================================================================
# ContextPack-Only Mode
# =============================================================================
# When enabled, raw history fallback is disabled. The orchestrator MUST provide
# a ContextPack with previous_envelopes for all steps after the first.
# This ensures consistent context handoff via structured envelopes.

_CONTEXTPACK_ONLY = os.environ.get("SWARM_CONTEXTPACK_ONLY", "false").lower() == "true"

# Scent Trail: Cross-run wisdom from previous runs
WISDOM_LATEST_PATH = ".runs/_wisdom/latest.md"

# =============================================================================
# SpecCompiler Integration (Default Enabled)
# =============================================================================
# Prompts are now assembled using the spec system (SpecCompiler) by default.
# This provides:
# - Station-based identity with invariants
# - Fragment-resolved guidelines
# - Template-driven prompt composition
# - Better traceability via prompt_hash
#
# Set SWARM_USE_SPEC_COMPILER=false to disable and use legacy file loading.

USE_SPEC_COMPILER = os.environ.get("SWARM_USE_SPEC_COMPILER", "true").lower() == "true"


# Inline finalization prompt (appended to work prompt for single-call pattern)
# This preserves "hot context" by having the agent finalize in the same session
INLINE_FINALIZATION_PROMPT = """
---
## Finalization (REQUIRED)

When you have completed all work above, you MUST create a handoff file.

Use the `Write` tool to create: {handoff_path}

The file MUST be valid JSON:
```json
{{
  "step_id": "{step_id}",
  "flow_key": "{flow_key}",
  "run_id": "{run_id}",
  "status": "VERIFIED | UNVERIFIED | PARTIAL | BLOCKED",
  "summary": "2-paragraph summary: what you accomplished, any issues encountered",
  "artifacts": {{"artifact_name": "relative/path/from/run_base"}},
  "proposed_next_step": "next_step_id or null",
  "notes_for_next_step": "What the next agent should know",
  "confidence": 0.0 to 1.0
}}
```

Status meanings:
- VERIFIED: Task completed successfully
- UNVERIFIED: Tests fail or work incomplete
- PARTIAL: Some work done but blocked on something
- BLOCKED: Cannot proceed (missing inputs, invalid state)

DO NOT finish without writing this handoff file.
---
"""


def load_scent_trail(repo_root: Optional[Path]) -> Optional[str]:
    """Load the Scent Trail from previous runs' wisdom.

    The Scent Trail is cross-run institutional memory that informs the current
    run about lessons learned from previous runs. This enables the swarm to
    learn from its mistakes across runs without a complex database.

    Location: .runs/_wisdom/latest.md (or swarm/runs/_wisdom/latest.md)

    Args:
        repo_root: Repository root path.

    Returns:
        The scent trail content, or None if not found.
    """
    if not repo_root:
        return None

    # Try both locations (new path and legacy path)
    scent_paths = [
        Path(repo_root) / WISDOM_LATEST_PATH,
        Path(repo_root) / "swarm" / "runs" / "_wisdom" / "latest.md",
    ]

    for scent_path in scent_paths:
        if scent_path.exists():
            try:
                content = scent_path.read_text(encoding="utf-8")
                if content.strip():
                    logger.debug("Loaded scent trail from %s", scent_path)
                    return content.strip()
            except (OSError, IOError) as e:
                logger.debug("Failed to read scent trail from %s: %s", scent_path, e)

    return None


def load_agent_persona(repo_root: Optional[Path], agent_key: str) -> Optional[str]:
    """Load agent persona/prompt for a step.

    Priority order:
    1. swarm/prompts/agentic_steps/{agent_key}.md (detailed step prompts)
    2. .claude/agents/{agent_key}.md (basic persona fallback)

    The agentic_steps prompts are comprehensive industrialized prompts with
    detailed behavioral specifications, while .claude/agents provides basic
    persona definitions for backwards compatibility.

    Args:
        repo_root: Repository root path.
        agent_key: The agent identifier (e.g., "code-implementer").

    Returns:
        The agent's prompt/persona markdown (without frontmatter), or None if not found.
    """
    if not repo_root:
        return None

    # Use flow_loader which implements the priority order
    prompt = load_agent_step_prompt(agent_key, Path(repo_root))
    if prompt:
        logger.debug("Loaded agentic step prompt for %s", agent_key)
        return prompt

    # Fallback: try legacy .claude/agents location directly (in case flow_loader fails)
    agent_path = Path(repo_root) / ".claude" / "agents" / f"{agent_key}.md"
    if not agent_path.exists():
        logger.debug("Agent persona not found: %s", agent_path)
        return None

    try:
        content = agent_path.read_text(encoding="utf-8")

        # Strip YAML frontmatter (between --- markers)
        if content.startswith("---"):
            # Find the closing ---
            end_marker = content.find("---", 3)
            if end_marker != -1:
                # Skip past the closing --- and any immediate newline
                body_start = end_marker + 3
                if body_start < len(content) and content[body_start] == "\n":
                    body_start += 1
                content = content[body_start:]

        return content.strip()

    except (OSError, IOError) as e:
        logger.warning("Failed to load agent persona %s: %s", agent_key, e)
        return None


def build_context_from_pack(
    context_pack: "ContextPack",
    max_summary_chars: int = 2000,
) -> Tuple[List[str], int]:
    """Build context lines from a ContextPack's previous envelopes.

    This method extracts structured context from HandoffEnvelopes,
    providing higher-fidelity context than raw history dicts.

    The ContextPack approach:
    - Uses HandoffEnvelope.summary (compressed, high-signal)
    - Includes routing decisions and status
    - Provides artifact pointers (not full content)
    - Preserves file_changes forensics

    Args:
        context_pack: The ContextPack with previous_envelopes.
        max_summary_chars: Max chars per envelope summary.

    Returns:
        Tuple of (context_lines, total_chars_used).
    """
    lines: List[str] = []
    chars_used = 0

    if not context_pack.previous_envelopes:
        return lines, chars_used

    lines.append("## Previous Steps (from ContextPack)")
    lines.append("")

    for envelope in context_pack.previous_envelopes:
        # Status indicator
        status_emoji = {
            "verified": "[OK]",
            "unverified": "[?]",
            "partial": "[~]",
            "blocked": "[X]",
        }.get(envelope.status.lower(), "[?]")

        lines.append(f"### Step: {envelope.step_id} {status_emoji}")

        # Summary (the key context - compressed by the previous agent)
        if envelope.summary:
            summary = envelope.summary
            if len(summary) > max_summary_chars:
                summary = summary[:max_summary_chars] + "... (truncated)"
            lines.append(f"**Summary:** {summary}")

        # Routing decision (what did the previous step decide?)
        if envelope.routing_signal:
            rs = envelope.routing_signal
            lines.append(f"**Routing:** {rs.decision.value} -> {rs.reason}")

        # File changes (what was mutated?)
        if envelope.file_changes and envelope.file_changes.get("summary"):
            lines.append(f"**Changes:** {envelope.file_changes['summary']}")

        # Artifacts (file pointers, not content)
        if envelope.artifacts:
            artifact_list = ", ".join(envelope.artifacts.keys())
            lines.append(f"**Artifacts:** {artifact_list}")

        lines.append("")

    # Calculate total chars
    context_text = "\n".join(lines)
    chars_used = len(context_text)

    return lines, chars_used


def build_artifact_pointers(context_pack: "ContextPack") -> List[str]:
    """Build artifact pointer lines from upstream artifacts.

    Lists file paths that the agent should read for context.

    Args:
        context_pack: The ContextPack with upstream_artifacts.

    Returns:
        List of formatted lines describing available artifacts.
    """
    lines: List[str] = []

    if not context_pack.upstream_artifacts:
        return lines

    lines.append("## Available Upstream Artifacts")
    lines.append("The following artifacts from previous flows are available:")
    lines.append("")

    for name, path in context_pack.upstream_artifacts.items():
        lines.append(f"- **{name}**: `{path}`")

    lines.append("")
    lines.append("Use the `Read` tool to load relevant artifacts before starting work.")
    lines.append("")

    return lines


# =============================================================================
# SpecCompiler-Based Prompt Building
# =============================================================================


def _get_flow_id_from_context(ctx: StepContext) -> str:
    """Derive the flow_id for SpecCompiler from StepContext.

    The SpecCompiler expects flow_id in format like "3-build".
    We map flow_key to a numeric prefix based on standard flow ordering.

    Args:
        ctx: Step execution context.

    Returns:
        Flow ID string (e.g., "3-build").
    """
    # Standard flow key to index mapping
    flow_indices = {
        "signal": 1,
        "plan": 2,
        "build": 3,
        "review": 4,
        "gate": 5,
        "deploy": 6,
        "wisdom": 7,
    }
    idx = flow_indices.get(ctx.flow_key, 0)
    return f"{idx}-{ctx.flow_key}"


def build_prompt_from_spec(
    ctx: StepContext,
    repo_root: Optional[Path],
    profile_id: Optional[str] = None,
) -> Tuple[str, Optional[HistoryTruncationInfo], Optional[str], Optional["PromptPlan"]]:
    """Build a prompt using the SpecCompiler for spec-driven assembly.

    This function uses the spec system (SpecCompiler) to compile prompts from
    station specs, fragments, and templates. It provides:
    - Station-based identity with invariants (system_append)
    - Fragment-resolved guidelines
    - Template-driven prompt composition
    - Better traceability via prompt_hash

    Args:
        ctx: Step execution context.
        repo_root: Repository root for loading specs.
        profile_id: Optional profile ID (unused but kept for API compatibility).

    Returns:
        Tuple of:
        - user_prompt: The compiled user prompt (main work instructions)
        - truncation_info: Always None (SpecCompiler handles its own budgeting)
        - system_append: Station identity + invariants for system prompt
        - prompt_plan: The full PromptPlan for traceability (or None on failure)

    Raises:
        FileNotFoundError: If flow or station spec not found.
        ValueError: If step not found in flow spec.
    """
    # Import here to avoid circular dependencies
    from swarm.spec.compiler import SpecCompiler

    if not repo_root:
        raise ValueError("repo_root is required for SpecCompiler")

    # Get context_pack from extra if available
    context_pack = ctx.extra.get("context_pack") if ctx.extra else None

    # Derive flow_id from context
    flow_id = _get_flow_id_from_context(ctx)

    # Initialize compiler
    compiler = SpecCompiler(repo_root)

    # Compile the prompt plan
    try:
        prompt_plan = compiler.compile(
            flow_id=flow_id,
            step_id=ctx.step_id,
            context_pack=context_pack,
            run_base=ctx.run_base,
            cwd=str(repo_root),
            policy_invariants_ref=None,  # Use station defaults
            use_v2=True,  # Use v2 with policy loading
        )

        logger.info(
            "Compiled prompt via SpecCompiler: flow=%s, step=%s, hash=%s",
            flow_id,
            ctx.step_id,
            prompt_plan.prompt_hash,
        )

        # The user_prompt from SpecCompiler is the complete work prompt
        # The system_append contains station identity + invariants
        return (
            prompt_plan.user_prompt,
            None,  # No truncation info (SpecCompiler handles budgeting)
            prompt_plan.system_append,
            prompt_plan,
        )

    except FileNotFoundError as e:
        logger.warning(
            "SpecCompiler failed (spec not found): %s. Falling back to legacy builder.",
            e,
        )
        raise
    except ValueError as e:
        logger.warning(
            "SpecCompiler failed (invalid step): %s. Falling back to legacy builder.",
            e,
        )
        raise


def build_prompt_auto(
    ctx: StepContext,
    repo_root: Optional[Path],
    profile_id: Optional[str] = None,
    use_spec_compiler: Optional[bool] = None,
) -> Tuple[str, Optional[HistoryTruncationInfo], Optional[str], Optional["PromptPlan"]]:
    """Build a prompt with automatic selection between legacy and spec-based builders.

    This function automatically chooses between:
    1. SpecCompiler-based building (if USE_SPEC_COMPILER=true or use_spec_compiler=True)
    2. Legacy file-based building (default)

    When SpecCompiler fails (missing specs), it falls back to legacy building.

    Args:
        ctx: Step execution context.
        repo_root: Repository root for loading specs/personas.
        profile_id: Optional profile ID for budget resolution.
        use_spec_compiler: Override for USE_SPEC_COMPILER flag. If None, uses env var.

    Returns:
        Tuple of:
        - prompt: The compiled user/work prompt
        - truncation_info: History truncation info (legacy) or None (spec)
        - system_append_or_persona: System append (spec) or agent persona (legacy)
        - prompt_plan: PromptPlan if spec-based, None otherwise
    """
    # Determine whether to use SpecCompiler
    should_use_spec = use_spec_compiler if use_spec_compiler is not None else USE_SPEC_COMPILER

    if should_use_spec:
        try:
            return build_prompt_from_spec(ctx, repo_root, profile_id)
        except (FileNotFoundError, ValueError) as e:
            logger.info(
                "SpecCompiler unavailable for step %s, falling back to legacy: %s",
                ctx.step_id,
                e,
            )
            # Fall through to legacy

    # Legacy path: use file-based prompt building
    prompt, truncation_info, persona = build_prompt(ctx, repo_root, profile_id)
    return prompt, truncation_info, persona, None


def build_prompt(
    ctx: StepContext,
    repo_root: Optional[Path],
    profile_id: Optional[str] = None,
) -> Tuple[str, Optional[HistoryTruncationInfo], Optional[str]]:
    """Build a context-aware prompt for a Claude step.

    Composes the prompt with agent persona (if available) and step context.
    Returns the persona separately for system_prompt composition.

    Args:
        ctx: Step execution context.
        repo_root: Repository root for loading personas.
        profile_id: Optional profile ID for budget resolution.

    Returns:
        Tuple of (formatted prompt string, truncation info or None, agent persona or None).
    """
    lines = []

    # Load agent persona for the primary agent
    agent_persona = None
    if ctx.step_agents:
        agent_persona = load_agent_persona(repo_root, ctx.step_agents[0])
        if agent_persona:
            lines.append("# Your Identity")
            lines.append("")
            lines.append(agent_persona)
            lines.append("")
            lines.append("---")
            lines.append("")

    # Scent Trail: Cross-run wisdom from previous runs
    # This injects institutional memory at the start of the prompt
    scent_trail = load_scent_trail(repo_root)
    if scent_trail:
        lines.append("# Wisdom from Previous Runs (Scent Trail)")
        lines.append("")
        lines.append("The following lessons were extracted from previous runs in this repository:")
        lines.append("")
        # Limit scent trail to ~2000 chars to avoid bloating the prompt
        if len(scent_trail) > 2000:
            scent_trail = scent_trail[:2000] + "\n\n... (truncated)"
        lines.append(scent_trail)
        lines.append("")
        lines.append("Consider these lessons when making decisions in this step.")
        lines.append("")
        lines.append("---")
        lines.append("")
        logger.debug("Injected scent trail (%d chars) into prompt", len(scent_trail))

    # Flow and step context
    lines.extend(
        [
            f"# Flow: {ctx.flow_title}",
            f"# Step: {ctx.step_id} (Step {ctx.step_index} of {ctx.total_steps})",
            f"# Run ID: {ctx.run_id}",
            "",
            "## Step Role",
            ctx.step_role,
            "",
        ]
    )

    # Agent assignments
    if ctx.step_agents:
        lines.append("## Assigned Agents")
        for agent in ctx.step_agents:
            lines.append(f"- {agent}")
        lines.append("")

    # Teaching notes (scoped context for this step)
    if ctx.teaching_notes:
        tn = ctx.teaching_notes

        if tn.inputs:
            lines.append("## Expected Inputs")
            lines.append("Read the following files/artifacts for this step:")
            for input_path in tn.inputs:
                lines.append(f"- {input_path}")
            lines.append("")

        if tn.outputs:
            lines.append("## Expected Outputs")
            lines.append("Produce the following files/artifacts:")
            for output_path in tn.outputs:
                lines.append(f"- {output_path}")
            lines.append("")

        if tn.emphasizes:
            lines.append("## Key Behaviors")
            lines.append("Focus on these patterns and behaviors:")
            for emphasis in tn.emphasizes:
                lines.append(f"- {emphasis}")
            lines.append("")

        if tn.constraints:
            lines.append("## Constraints")
            lines.append("Observe these limitations:")
            for constraint in tn.constraints:
                lines.append(f"- {constraint}")
            lines.append("")

    # RUN_BASE instructions
    lines.extend(
        [
            "## Output Location",
            f"Write outputs to: {ctx.run_base}/",
            "Follow RUN_BASE conventions for all artifacts.",
            "",
        ]
    )

    # Context Injection: ContextPack-First Strategy
    truncation_info: Optional[HistoryTruncationInfo] = None
    context_pack: Optional["ContextPack"] = ctx.extra.get("context_pack")

    if context_pack and context_pack.previous_envelopes:
        # ContextPack-first: use structured envelopes
        logger.debug(
            "Using ContextPack for step %s (envelopes: %d, artifacts: %d)",
            ctx.step_id,
            len(context_pack.previous_envelopes),
            len(context_pack.upstream_artifacts),
        )

        # Add artifact pointers first (tells agent what to read)
        artifact_lines = build_artifact_pointers(context_pack)
        lines.extend(artifact_lines)

        # Add previous step context from envelopes
        context_lines, chars_used = build_context_from_pack(context_pack)
        lines.extend(context_lines)

        # Create truncation info for observability (no truncation with ContextPack)
        truncation_info = HistoryTruncationInfo(
            steps_included=len(context_pack.previous_envelopes),
            steps_total=len(context_pack.previous_envelopes),
            chars_used=chars_used,
            budget_chars=chars_used,  # No budget exceeded
            truncated=False,
            priority_aware=False,  # ContextPack doesn't use priority
        )

    elif ctx.history:
        # Check ContextPack-only mode before falling back to raw history
        if _CONTEXTPACK_ONLY:
            raise ValueError(
                f"ContextPack-only mode active but no ContextPack available for step {ctx.step_id}. "
                f"Orchestrator must build ContextPack for all steps after the first. "
                "Set SWARM_CONTEXTPACK_ONLY=false to allow raw history fallback."
            )

        # Fallback: use raw history dicts with priority-aware budget management
        logger.debug(
            "Using raw history for step %s (no ContextPack available)",
            ctx.step_id,
        )
        lines.append("## Previous Steps Context")
        lines.append("The following steps have already been completed:")
        lines.append("")

        # Get resolved budgets for this step's context
        budgets = get_resolved_context_budgets(
            flow_key=ctx.flow_key,
            step_id=ctx.step_id,
            profile_id=profile_id,
        )
        history_budget = budgets.context_budget_chars
        recent_max = budgets.history_max_recent_chars
        older_max = budgets.history_max_older_chars

        # Sort history by priority (CRITICAL first, then HIGH, MEDIUM, LOW)
        prioritized = prioritize_history(ctx.history)
        total_steps = len(ctx.history)

        # Track which items we include and their priorities
        included_items: List[Tuple[int, Dict[str, Any], List[str]]] = []
        priority_counts: Dict[str, int] = {
            "CRITICAL": 0,
            "HIGH": 0,
            "MEDIUM": 0,
            "LOW": 0,
        }
        chars_used = 0

        # Most recent step index for determining output limits
        most_recent_idx = total_steps - 1 if total_steps > 0 else -1

        # Process by priority order, including highest-value items first
        for priority, orig_idx, prev in prioritized:
            is_most_recent = orig_idx == most_recent_idx
            step_lines: List[str] = []

            status_emoji = "[OK]" if prev.get("status") == "succeeded" else "[FAIL]"
            priority_label = get_priority_label(priority)
            step_lines.append(f"### Step: {prev.get('step_id')} {status_emoji}")

            if prev.get("output"):
                output = str(prev.get("output"))
                # CRITICAL items get full recent budget, others based on recency
                if priority >= HistoryPriority.CRITICAL:
                    max_chars = recent_max
                elif is_most_recent:
                    max_chars = recent_max
                else:
                    max_chars = older_max
                if len(output) > max_chars:
                    output = output[:max_chars] + "... (truncated)"
                step_lines.append(f"Output: {output}")

            if prev.get("error"):
                error = str(prev.get("error"))
                max_error = 200
                if len(error) > max_error:
                    error = error[:max_error] + "... (truncated)"
                step_lines.append(f"Error: {error}")

            step_lines.append("")

            # Calculate chars for this step
            step_text = "\n".join(step_lines)
            step_chars = len(step_text)

            # Check if adding this step would exceed budget
            if chars_used + step_chars > history_budget:
                continue

            # Include this item
            included_items.append((orig_idx, prev, step_lines))
            priority_counts[priority_label] += 1
            chars_used += step_chars

        # Sort included items back to chronological order for output
        included_items.sort(key=lambda x: x[0])

        # Build history lines in chronological order
        history_lines: List[str] = []
        for _, _, step_lines in included_items:
            history_lines.extend(step_lines)

        steps_included = len(included_items)

        # Track truncation metadata with priority information
        truncated = steps_included < total_steps
        truncation_info = HistoryTruncationInfo(
            steps_included=steps_included,
            steps_total=total_steps,
            chars_used=chars_used,
            budget_chars=history_budget,
            truncated=truncated,
            priority_aware=True,
            priority_distribution=priority_counts,
        )

        # Add machine-readable truncation warning if we didn't include all steps
        if truncated:
            truncation_warning = truncation_info.truncation_note
            history_lines.insert(0, truncation_warning + "\n")

            logger.debug(
                "History truncation: %s (flow=%s, step=%s)",
                truncation_warning,
                ctx.flow_key,
                ctx.step_id,
            )

        lines.extend(history_lines)

    # Work Phase Instructions
    lines.extend(
        [
            "## Work Phase Instructions",
            "",
            "Execute your assigned role following these steps:",
            "",
            "1. **Read inputs**: Load any required artifacts from previous steps or RUN_BASE",
            "2. **Execute work**: Perform the step role as described above",
            "3. **Write outputs**: Save all artifacts to the correct RUN_BASE location",
            "4. **Create handoff**: Write the handoff file as specified below (REQUIRED)",
            "",
        ]
    )

    # Finalization Phase (MANDATORY - within same session)
    handoff_dir = ctx.run_base / "handoff"
    handoff_path = handoff_dir / f"{ctx.step_id}.draft.json"
    inline_finalization = INLINE_FINALIZATION_PROMPT.format(
        handoff_path=str(handoff_path),
        step_id=ctx.step_id,
        flow_key=ctx.flow_key,
        run_id=ctx.run_id,
    )
    lines.append(inline_finalization)

    return "\n".join(lines), truncation_info, agent_persona
