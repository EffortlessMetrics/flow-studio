"""
flow_loader.py - Load enriched step definitions from prompt-based flow specs.

This module provides utilities to load orchestrator and agent prompts from
the `swarm/prompts/` directory hierarchy and enrich StepDefinition objects
with this contextual information.

Directory Layout:
    swarm/prompts/
        orchestrator_flows/     # Flow-level orchestrator prompts
            flow-1-signal.md
            flow-2-plan.md
            ...
        agentic_steps/          # Per-agent step prompts
            code-implementer.md
            test-author.md
            ...

Usage:
    from swarm.runtime.flow_loader import enrich_step_definition, EnrichedStepDefinition
    from swarm.config.flow_registry import get_flow_steps

    steps = get_flow_steps("build")
    enriched = [enrich_step_definition(s, repo_root) for s in steps]
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from swarm.config.flow_registry import StepDefinition, get_flow_index, get_flow_steps

# Module logger
logger = logging.getLogger(__name__)


@dataclass
class EnrichedStepDefinition:
    """Step definition enriched with prompt-based context.

    Combines the base step definition from flow_registry with loaded prompts
    from the swarm/prompts directory hierarchy.

    Attributes:
        base: The underlying StepDefinition from flow_registry.
        orchestrator_prompt: The full orchestrator flow prompt (if found).
        agent_prompts: Mapping of agent_key to agent prompt body (frontmatter stripped).
    """

    base: StepDefinition
    orchestrator_prompt: Optional[str] = None
    agent_prompts: Dict[str, str] = field(default_factory=dict)


def _strip_yaml_frontmatter(content: str) -> str:
    """Strip YAML frontmatter from markdown content.

    Removes the frontmatter block delimited by --- markers at the start of
    the file. Returns the content after the closing --- marker.

    Args:
        content: The markdown file content.

    Returns:
        Content with frontmatter stripped, or original content if no frontmatter.
    """
    # Match frontmatter: starts with ---, ends with ---, at beginning of file
    pattern = r"^---\s*\n.*?\n---\s*\n"
    match = re.match(pattern, content, re.DOTALL)
    if match:
        return content[match.end() :].lstrip()
    return content


def load_orchestrator_flow_prompt(flow_key: str, repo_root: Path) -> Optional[str]:
    """Load the orchestrator flow prompt for a given flow.

    Loads from `swarm/prompts/orchestrator_flows/flow-{N}-{flow_key}.md`.

    Args:
        flow_key: The flow key (signal, plan, build, review, gate, deploy, wisdom).
        repo_root: Repository root path.

    Returns:
        The prompt file content (with frontmatter stripped), or None if not found.
    """
    flow_number = get_flow_index(flow_key)
    if flow_number == 99:  # Unknown flow key (get_flow_index returns 99 for unknown keys)
        logger.warning("Unknown flow key '%s' - cannot map to flow number", flow_key)
        return None

    prompt_path = (
        repo_root / "swarm" / "prompts" / "orchestrator_flows" / f"flow-{flow_number}-{flow_key}.md"
    )

    if not prompt_path.exists():
        logger.debug(
            "Orchestrator flow prompt not found for '%s' at %s",
            flow_key,
            prompt_path,
        )
        return None

    try:
        content = prompt_path.read_text(encoding="utf-8")
        return _strip_yaml_frontmatter(content)
    except OSError as e:
        logger.warning("Failed to read orchestrator prompt for '%s': %s", flow_key, e)
        return None


def load_agent_step_prompt(agent_key: str, repo_root: Path) -> Optional[str]:
    """Load the step prompt for an agent.

    First tries `swarm/prompts/agentic_steps/{agent_key}.md`. If not found,
    falls back to `.claude/agents/{agent_key}.md`. Frontmatter is stripped
    from either location.

    Args:
        agent_key: The agent key (e.g., "code-implementer", "test-author").
        repo_root: Repository root path.

    Returns:
        The prompt body (frontmatter stripped), or None if not found in either location.
    """
    # Primary location: swarm/prompts/agentic_steps/
    primary_path = repo_root / "swarm" / "prompts" / "agentic_steps" / f"{agent_key}.md"

    if primary_path.exists():
        try:
            content = primary_path.read_text(encoding="utf-8")
            return _strip_yaml_frontmatter(content)
        except OSError as e:
            logger.warning(
                "Failed to read agent prompt for '%s' from primary path: %s", agent_key, e
            )
            # Fall through to try fallback

    # Fallback location: .claude/agents/
    fallback_path = repo_root / ".claude" / "agents" / f"{agent_key}.md"

    if fallback_path.exists():
        try:
            content = fallback_path.read_text(encoding="utf-8")
            logger.debug(
                "Using fallback agent prompt for '%s' from .claude/agents/",
                agent_key,
            )
            return _strip_yaml_frontmatter(content)
        except OSError as e:
            logger.warning(
                "Failed to read agent prompt for '%s' from fallback path: %s",
                agent_key,
                e,
            )
            return None

    logger.debug(
        "Agent prompt not found for '%s' (checked %s and %s)",
        agent_key,
        primary_path,
        fallback_path,
    )
    return None


def enrich_step_definition(step: StepDefinition, repo_root: Path) -> EnrichedStepDefinition:
    """Enrich a StepDefinition with loaded prompts.

    Takes a StepDefinition from flow_registry and augments it with:
    - The orchestrator prompt for the step's flow
    - Agent prompts for all agents assigned to the step

    The orchestrator prompt is loaded once per flow and cached internally by
    the caller if needed. This function does not cache; it loads fresh each call.

    Args:
        step: The base StepDefinition from flow_registry.
        repo_root: Repository root path.

    Returns:
        An EnrichedStepDefinition with all available prompts loaded.
    """
    # Note: We need to get the flow_key from the step context.
    # StepDefinition doesn't directly contain flow_key, so we need to
    # accept it via the step's parent context or derive it.
    # For now, we'll load agent prompts but leave orchestrator_prompt
    # to be loaded by the caller who knows the flow_key.
    #
    # If needed, the caller can call load_orchestrator_flow_prompt separately.

    agent_prompts: Dict[str, str] = {}
    for agent_key in step.agents:
        prompt = load_agent_step_prompt(agent_key, repo_root)
        if prompt is not None:
            agent_prompts[agent_key] = prompt

    return EnrichedStepDefinition(
        base=step,
        orchestrator_prompt=None,  # Caller sets this via load_orchestrator_flow_prompt
        agent_prompts=agent_prompts,
    )


def enrich_step_definition_with_flow(
    step: StepDefinition, flow_key: str, repo_root: Path
) -> EnrichedStepDefinition:
    """Enrich a StepDefinition with loaded prompts, including orchestrator prompt.

    Like enrich_step_definition, but also loads the orchestrator prompt for
    the specified flow.

    Args:
        step: The base StepDefinition from flow_registry.
        flow_key: The flow key this step belongs to.
        repo_root: Repository root path.

    Returns:
        An EnrichedStepDefinition with all available prompts loaded.
    """
    enriched = enrich_step_definition(step, repo_root)

    orchestrator_prompt = load_orchestrator_flow_prompt(flow_key, repo_root)
    # Since EnrichedStepDefinition is a dataclass, we can create a new instance
    # with the orchestrator_prompt set
    return EnrichedStepDefinition(
        base=enriched.base,
        orchestrator_prompt=orchestrator_prompt,
        agent_prompts=enriched.agent_prompts,
    )


def enrich_flow_steps(flow_key: str, repo_root: Path) -> List[EnrichedStepDefinition]:
    """Load and enrich all steps for a flow.

    Convenience function that loads all step definitions for a flow
    and enriches them with prompts.

    Args:
        flow_key: The flow key (signal, plan, build, etc.).
        repo_root: Repository root path.

    Returns:
        List of EnrichedStepDefinitions for all steps in the flow.
    """
    steps = get_flow_steps(flow_key)

    # Load orchestrator prompt once for the flow
    orchestrator_prompt = load_orchestrator_flow_prompt(flow_key, repo_root)

    enriched_steps: List[EnrichedStepDefinition] = []
    for step in steps:
        # Load agent prompts for each step
        agent_prompts: Dict[str, str] = {}
        for agent_key in step.agents:
            prompt = load_agent_step_prompt(agent_key, repo_root)
            if prompt is not None:
                agent_prompts[agent_key] = prompt

        enriched_steps.append(
            EnrichedStepDefinition(
                base=step,
                orchestrator_prompt=orchestrator_prompt,
                agent_prompts=agent_prompts,
            )
        )

    return enriched_steps
