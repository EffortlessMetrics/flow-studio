"""
resolvers.py - Resolver functions for JIT finalization and routing.

This module provides functions for:
1. Loading and caching prompt templates (routing_signal.md, envelope_writer.md)
2. Building finalization prompts for envelope writing
3. Parsing envelope responses into HandoffEnvelope dataclasses
4. Building routing prompts from handoff envelopes
5. Parsing routing responses into RoutingSignal objects

The resolvers use templates from swarm/prompts/resolvers/ when available,
with fallback logic for missing templates.

Design Philosophy:
    - Router is a SEPARATE short-lived LLM call (not part of worker session)
    - Router validates that proposed next steps exist in the flow
    - Includes confidence scoring and reasoning
    - Supports needs_human flag for escalation
    - Envelope writer creates durable handoff artifacts

Usage:
    from swarm.runtime.resolvers import (
        # Envelope writer functions
        load_envelope_writer_prompt,
        build_finalization_prompt,
        parse_envelope_response,
        EnvelopeWriterResolver,
        # Routing functions
        load_routing_signal_prompt,
        build_routing_prompt,
        parse_routing_response,
        read_receipt_field,
    )
"""

from __future__ import annotations

import functools
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from swarm.config.flow_registry import (
    FlowDefinition,
    StepDefinition,
    StepRouting,
)
from swarm.runtime.types import (
    HandoffEnvelope,
    RoutingCandidate,
    RoutingDecision,
    RoutingSignal,
    routing_signal_from_dict,
)

# Module logger
logger = logging.getLogger(__name__)

# Default resolver template paths
_ROUTING_SIGNAL_TEMPLATE = (
    Path(__file__).parent.parent / "prompts" / "resolvers" / "routing_signal.md"
)
_ENVELOPE_WRITER_TEMPLATE = (
    Path(__file__).parent.parent / "prompts" / "resolvers" / "envelope_writer.md"
)


# =============================================================================
# Envelope Writer Resolver Functions
# =============================================================================


@functools.lru_cache(maxsize=8)
def load_envelope_writer_prompt(repo_root: Path) -> Optional[str]:
    """Load the envelope_writer.md template from disk.

    Loads the template from swarm/prompts/resolvers/envelope_writer.md and
    strips any YAML frontmatter. Results are cached for performance.

    Args:
        repo_root: Repository root path.

    Returns:
        Template content (without frontmatter) or None if not found.

    Example:
        >>> template = load_envelope_writer_prompt(Path("/repo"))
        >>> print(template[:50])
        'You are an envelope writer...'
    """
    template_path = repo_root / "swarm" / "prompts" / "resolvers" / "envelope_writer.md"

    if not template_path.exists():
        logger.debug("envelope_writer.md template not found at %s", template_path)
        return None

    try:
        content = template_path.read_text(encoding="utf-8")

        # Strip YAML frontmatter (between --- markers) if present
        if content.startswith("---"):
            end_marker = content.find("---", 3)
            if end_marker != -1:
                body_start = end_marker + 3
                if body_start < len(content) and content[body_start] == "\n":
                    body_start += 1
                content = content[body_start:]

        logger.debug("Loaded envelope_writer.md template from %s", template_path)
        return content.strip()

    except (OSError, IOError) as e:
        logger.warning("Failed to load envelope_writer.md: %s", e)
        return None


def clear_template_cache() -> None:
    """Clear the template cache.

    Useful for testing or when templates are modified during runtime.
    """
    load_envelope_writer_prompt.cache_clear()


# Default template when envelope_writer.md is not available
DEFAULT_ENVELOPE_TEMPLATE = """
You are an envelope writer. Your job is to convert step execution results into a structured HandoffEnvelope JSON for durable handoff between steps.

Output ONLY a valid HandoffEnvelope JSON. No markdown, no explanation, no additional text.

### Required Fields

- `step_id`: The step ID that produced this envelope
- `flow_key`: The flow key this step belongs to
- `run_id`: The run ID
- `routing_signal`: The routing decision signal object
- `summary`: Compressed summary of step output (max 2000 characters)

### Optional Fields

- `artifacts`: Map of artifact names to their file paths (relative to RUN_BASE)
- `status`: Execution status ("succeeded", "failed", or "skipped")
- `error`: Error message if the step failed
- `duration_ms`: Execution duration in milliseconds
- `timestamp`: ISO 8601 timestamp when this envelope was created

### Summary Guidelines

The `summary` field should be a concise (1-2k chars max) summary of:
- What the step accomplished
- Key decisions made
- Important outputs or changes
- Any issues or warnings

Focus on information relevant to the next step. Avoid verbose details.

Output the JSON now.
"""


def build_finalization_prompt(
    step_id: str,
    step_output: str,
    artifacts_changed: List[str],
    routing_config: Optional[StepRouting] = None,
    flow_key: str = "",
    run_id: str = "",
    status: str = "succeeded",
    error: Optional[str] = None,
    duration_ms: int = 0,
    routing_signal: Optional[RoutingSignal] = None,
    template: Optional[str] = None,
) -> str:
    """Build the JIT finalization prompt for envelope writing.

    Creates a structured prompt that includes:
    - Step execution context (ID, flow, run)
    - Summary of step output (truncated to avoid bloat)
    - List of artifacts created/modified
    - Routing configuration and signal
    - Template instructions for envelope format

    The prompt does NOT include the raw transcript, only a summary.

    Args:
        step_id: The step identifier.
        step_output: Summary or output text from step execution.
        artifacts_changed: List of artifact paths created/modified.
        routing_config: Optional routing configuration for this step.
        flow_key: The flow key (e.g., "build", "plan").
        run_id: The run identifier.
        status: Execution status.
        error: Error message if failed.
        duration_ms: Execution duration in milliseconds.
        routing_signal: Optional pre-computed routing signal.
        template: Optional pre-loaded template content.

    Returns:
        Formatted prompt string for envelope writing.

    Example:
        >>> prompt = build_finalization_prompt(
        ...     step_id="implement",
        ...     step_output="Implemented the health-check endpoint...",
        ...     artifacts_changed=["src/health.py", "tests/test_health.py"],
        ... )
        >>> "Step ID: implement" in prompt
        True
    """
    # Build routing signal data for prompt
    routing_data: Dict[str, Any] = {}
    if routing_signal:
        routing_data = {
            "decision": routing_signal.decision.value
            if isinstance(routing_signal.decision, RoutingDecision)
            else routing_signal.decision,
            "next_step_id": routing_signal.next_step_id,
            "route": routing_signal.route,
            "reason": routing_signal.reason,
            "confidence": routing_signal.confidence,
            "needs_human": routing_signal.needs_human,
        }
    else:
        routing_data = {
            "decision": "advance",
            "next_step_id": None,
            "route": None,
            "reason": "default_advance",
            "confidence": 0.7,
            "needs_human": False,
        }

    # Build routing config info if available
    routing_config_info = ""
    if routing_config:
        routing_config_info = f"""
## Step Routing Configuration

- Kind: {routing_config.kind}
- Next step: {routing_config.next or "None (flow end)"}
- Loop target: {getattr(routing_config, "loop_target", None) or "N/A"}
- Max iterations: {getattr(routing_config, "max_iterations", 5)}
"""

    # Truncate step output to avoid prompt bloat (max 4000 chars for summary)
    truncated_output = step_output[:4000] if step_output else "No output available."
    if len(step_output) > 4000:
        truncated_output += "\n... (output truncated)"

    # Format artifacts list
    artifacts_formatted = (
        "\n".join(f"- {path}" for path in artifacts_changed)
        if artifacts_changed
        else "No artifacts recorded."
    )

    # Build the prompt
    prompt = f"""## Step Execution Results

Step ID: {step_id}
Flow key: {flow_key}
Run ID: {run_id}
Status: {status}
Duration: {duration_ms} ms
Error: {error or "None"}

## Work Summary

{truncated_output}

## Artifacts Created/Modified

{artifacts_formatted}

## Routing Signal

```json
{json.dumps(routing_data, indent=2)}
```
{routing_config_info}
---

{template or DEFAULT_ENVELOPE_TEMPLATE}
"""

    return prompt


def parse_envelope_response(
    response: str,
    step_id: str,
    flow_key: str,
    run_id: str,
    fallback_routing_signal: Optional[RoutingSignal] = None,
    fallback_summary: str = "",
    fallback_status: str = "succeeded",
) -> HandoffEnvelope:
    """Parse the JSON response into a HandoffEnvelope.

    Attempts to extract and parse JSON from the response, with fallback
    handling for malformed responses.

    Args:
        response: Raw response text from the envelope writer.
        step_id: The step identifier (for fallback).
        flow_key: The flow key (for fallback).
        run_id: The run identifier (for fallback).
        fallback_routing_signal: Routing signal to use if not in response.
        fallback_summary: Summary to use if not in response.
        fallback_status: Status to use if not in response.

    Returns:
        Parsed HandoffEnvelope.

    Raises:
        ValueError: If response cannot be parsed and no valid fallback.

    Example:
        >>> response = '{"step_id": "test", "summary": "Done"}'
        >>> envelope = parse_envelope_response(response, "test", "build", "run-1")
        >>> envelope.step_id
        'test'
    """
    # Try to extract JSON from response
    json_content = _extract_envelope_json(response)

    if json_content is None:
        logger.warning("No parseable JSON found in envelope response, using fallback")
        return _create_fallback_envelope(
            step_id=step_id,
            flow_key=flow_key,
            run_id=run_id,
            routing_signal=fallback_routing_signal,
            summary=fallback_summary,
            status=fallback_status,
        )

    try:
        envelope_data = json.loads(json_content)
    except json.JSONDecodeError as e:
        logger.warning("Failed to parse envelope JSON: %s", e)
        return _create_fallback_envelope(
            step_id=step_id,
            flow_key=flow_key,
            run_id=run_id,
            routing_signal=fallback_routing_signal,
            summary=fallback_summary,
            status=fallback_status,
        )

    # Parse routing signal from response or use fallback
    routing_signal = fallback_routing_signal
    if "routing_signal" in envelope_data:
        try:
            routing_signal = routing_signal_from_dict(envelope_data["routing_signal"])
        except (KeyError, ValueError) as e:
            logger.debug("Failed to parse routing_signal from response: %s", e)

    if routing_signal is None:
        default_reason = "Default advance routing (no routing_signal in response)"
        routing_signal = RoutingSignal(
            decision=RoutingDecision.ADVANCE,
            reason=default_reason,
            confidence=0.7,
            routing_source="resolver_default",
            chosen_candidate_id="resolver:advance:default",
            routing_candidates=[
                RoutingCandidate(
                    candidate_id="resolver:advance:default",
                    action="advance",
                    target_node=None,
                    reason=default_reason,
                    priority=50,
                    source="resolver_fallback",
                    is_default=True,
                )
            ],
        )

    # Parse timestamp
    timestamp = datetime.now(timezone.utc)
    if "timestamp" in envelope_data:
        try:
            ts_str = envelope_data["timestamp"]
            if ts_str.endswith("Z"):
                ts_str = ts_str[:-1]
            timestamp = datetime.fromisoformat(ts_str)
        except (ValueError, TypeError):
            pass

    # Build envelope from parsed data with fallbacks
    return HandoffEnvelope(
        step_id=envelope_data.get("step_id", step_id),
        flow_key=envelope_data.get("flow_key", flow_key),
        run_id=envelope_data.get("run_id", run_id),
        routing_signal=routing_signal,
        summary=envelope_data.get("summary", fallback_summary)[:2000],
        artifacts=envelope_data.get("artifacts", {}),
        status=envelope_data.get("status", fallback_status),
        error=envelope_data.get("error"),
        duration_ms=envelope_data.get("duration_ms", 0),
        timestamp=timestamp,
    )


def _extract_envelope_json(response: str) -> Optional[str]:
    """Extract JSON content from a response that may contain markdown.

    Handles responses that wrap JSON in markdown code blocks.

    Args:
        response: Raw response text.

    Returns:
        Extracted JSON string or None if not found.
    """
    response = response.strip()

    # Try to find JSON in ```json ... ``` block
    if "```json" in response:
        start = response.find("```json") + 7
        end = response.find("```", start)
        if end > start:
            return response[start:end].strip()

    # Try to find JSON in ``` ... ``` block
    if "```" in response:
        start = response.find("```") + 3
        end = response.find("```", start)
        if end > start:
            content = response[start:end].strip()
            # Verify it looks like JSON
            if content.startswith("{") or content.startswith("["):
                return content

    # Try to find raw JSON object
    match = re.search(
        r'\{[^{}]*("step_id"|"summary"|"routing_signal")[^{}]*\}', response, re.DOTALL
    )
    if match:
        # Try to extract the full JSON object
        start = response.find("{")
        if start >= 0:
            # Find matching closing brace
            depth = 0
            for i, c in enumerate(response[start:], start):
                if c == "{":
                    depth += 1
                elif c == "}":
                    depth -= 1
                    if depth == 0:
                        return response[start : i + 1]

    # Last resort: try entire response as JSON
    if response.startswith("{"):
        return response

    return None


def _create_fallback_envelope(
    step_id: str,
    flow_key: str,
    run_id: str,
    routing_signal: Optional[RoutingSignal] = None,
    summary: str = "",
    status: str = "succeeded",
    error: Optional[str] = None,
    duration_ms: int = 0,
) -> HandoffEnvelope:
    """Create a fallback HandoffEnvelope when parsing fails.

    Args:
        step_id: The step identifier.
        flow_key: The flow key.
        run_id: The run identifier.
        routing_signal: Optional routing signal.
        summary: Summary text.
        status: Execution status.
        error: Error message if failed.
        duration_ms: Execution duration.

    Returns:
        HandoffEnvelope with provided or default values.
    """
    # Create routing signal with proper audit fields for fallback path
    if routing_signal is None:
        fallback_reason = "Fallback envelope: parsing failed or no response"
        fallback_routing = RoutingSignal(
            decision=RoutingDecision.ADVANCE,
            reason=fallback_reason,
            confidence=0.5,
            routing_source="resolver_fallback",
            chosen_candidate_id="resolver:advance:fallback",
            routing_candidates=[
                RoutingCandidate(
                    candidate_id="resolver:advance:fallback",
                    action="advance",
                    target_node=None,
                    reason=fallback_reason,
                    priority=10,
                    source="resolver_fallback",
                    is_default=True,
                )
            ],
        )
    else:
        fallback_routing = routing_signal

    return HandoffEnvelope(
        step_id=step_id,
        flow_key=flow_key,
        run_id=run_id,
        routing_signal=fallback_routing,
        summary=summary[:2000] if summary else f"Step {step_id} completed with status {status}",
        artifacts={},
        status=status,
        error=error,
        duration_ms=duration_ms,
        timestamp=datetime.now(timezone.utc),
    )


@dataclass
class FinalizationContext:
    """Context for building a finalization prompt.

    Encapsulates all the information needed to generate a JIT finalization
    prompt for envelope writing.

    Attributes:
        step_id: The step identifier that produced this output.
        flow_key: The flow key this step belongs to.
        run_id: The run identifier.
        step_output: Summary or output text from the step execution.
        artifacts_changed: List of artifact paths that were created/modified.
        status: Execution status ("succeeded", "failed", "skipped").
        error: Error message if the step failed.
        duration_ms: Execution duration in milliseconds.
        routing_config: Optional routing configuration for this step.
        routing_signal: Optional pre-computed routing signal.
    """

    step_id: str
    flow_key: str
    run_id: str
    step_output: str
    artifacts_changed: List[str]
    status: str = "succeeded"
    error: Optional[str] = None
    duration_ms: int = 0
    routing_config: Optional[StepRouting] = None
    routing_signal: Optional[RoutingSignal] = None


class EnvelopeWriterResolver:
    """Resolver for creating HandoffEnvelopes with template caching.

    Provides a class-based interface for envelope creation that caches
    the template and provides convenience methods for the full workflow.

    Attributes:
        repo_root: Repository root path.
        template: Cached template content (loaded on first use).

    Example:
        >>> resolver = EnvelopeWriterResolver(Path("/repo"))
        >>> prompt = resolver.build_prompt(
        ...     step_id="implement",
        ...     step_output="Completed implementation...",
        ...     artifacts_changed=["src/feature.py"],
        ... )
        >>> envelope = resolver.parse_response(response, "implement", "build", "run-1")
    """

    def __init__(self, repo_root: Path):
        """Initialize the resolver.

        Args:
            repo_root: Repository root path.
        """
        self.repo_root = repo_root
        self._template: Optional[str] = None

    @property
    def template(self) -> Optional[str]:
        """Get the cached template, loading if necessary."""
        if self._template is None:
            self._template = load_envelope_writer_prompt(self.repo_root)
        return self._template

    def build_prompt(
        self,
        step_id: str,
        step_output: str,
        artifacts_changed: List[str],
        routing_config: Optional[StepRouting] = None,
        flow_key: str = "",
        run_id: str = "",
        status: str = "succeeded",
        error: Optional[str] = None,
        duration_ms: int = 0,
        routing_signal: Optional[RoutingSignal] = None,
    ) -> str:
        """Build a finalization prompt using the cached template.

        Args:
            step_id: The step identifier.
            step_output: Summary or output text from step execution.
            artifacts_changed: List of artifact paths created/modified.
            routing_config: Optional routing configuration.
            flow_key: The flow key.
            run_id: The run identifier.
            status: Execution status.
            error: Error message if failed.
            duration_ms: Execution duration.
            routing_signal: Optional pre-computed routing signal.

        Returns:
            Formatted prompt string.
        """
        return build_finalization_prompt(
            step_id=step_id,
            step_output=step_output,
            artifacts_changed=artifacts_changed,
            routing_config=routing_config,
            flow_key=flow_key,
            run_id=run_id,
            status=status,
            error=error,
            duration_ms=duration_ms,
            routing_signal=routing_signal,
            template=self.template,
        )

    def parse_response(
        self,
        response: str,
        step_id: str,
        flow_key: str,
        run_id: str,
        fallback_routing_signal: Optional[RoutingSignal] = None,
        fallback_summary: str = "",
        fallback_status: str = "succeeded",
    ) -> HandoffEnvelope:
        """Parse an envelope writer response.

        Args:
            response: Raw response text.
            step_id: The step identifier.
            flow_key: The flow key.
            run_id: The run identifier.
            fallback_routing_signal: Routing signal for fallback.
            fallback_summary: Summary for fallback.
            fallback_status: Status for fallback.

        Returns:
            Parsed HandoffEnvelope.
        """
        return parse_envelope_response(
            response=response,
            step_id=step_id,
            flow_key=flow_key,
            run_id=run_id,
            fallback_routing_signal=fallback_routing_signal,
            fallback_summary=fallback_summary,
            fallback_status=fallback_status,
        )

    def create_fallback_envelope(
        self,
        step_id: str,
        flow_key: str,
        run_id: str,
        routing_signal: Optional[RoutingSignal] = None,
        summary: str = "",
        status: str = "succeeded",
        error: Optional[str] = None,
        duration_ms: int = 0,
    ) -> HandoffEnvelope:
        """Create a fallback envelope without LLM assistance.

        Args:
            step_id: The step identifier.
            flow_key: The flow key.
            run_id: The run identifier.
            routing_signal: Optional routing signal.
            summary: Summary text.
            status: Execution status.
            error: Error message if failed.
            duration_ms: Execution duration.

        Returns:
            HandoffEnvelope with provided values.
        """
        return _create_fallback_envelope(
            step_id=step_id,
            flow_key=flow_key,
            run_id=run_id,
            routing_signal=routing_signal,
            summary=summary,
            status=status,
            error=error,
            duration_ms=duration_ms,
        )


# =============================================================================
# Routing Signal Resolver Functions
# =============================================================================


def load_routing_signal_prompt(repo_root: Optional[Path] = None) -> str:
    """Load the routing_signal.md template from disk.

    Args:
        repo_root: Optional repository root path. Defaults to auto-detection.

    Returns:
        The contents of the routing_signal.md template file.

    Raises:
        FileNotFoundError: If the template file does not exist.
    """
    if repo_root is None:
        template_path = _ROUTING_SIGNAL_TEMPLATE
    else:
        template_path = repo_root / "swarm" / "prompts" / "resolvers" / "routing_signal.md"

    if not template_path.exists():
        raise FileNotFoundError(f"Routing signal template not found at: {template_path}")

    return template_path.read_text(encoding="utf-8")


def build_routing_prompt(
    handoff_envelope: HandoffEnvelope,
    current_step: StepDefinition,
    flow_spec: FlowDefinition,
    loop_state: Dict[str, int],
    repo_root: Optional[Path] = None,
) -> str:
    """Build the routing decision prompt.

    Constructs a prompt that includes:
    - The base routing_signal.md template
    - The HandoffEnvelope from finalization
    - Current step's routing configuration
    - Current loop state (iteration counts)
    - Available next steps from flow spec

    Args:
        handoff_envelope: The handoff envelope from step finalization.
        current_step: The step that just completed.
        flow_spec: The flow definition containing all steps.
        loop_state: Dictionary tracking iteration counts per loop.
        repo_root: Optional repository root path for template loading.

    Returns:
        A formatted prompt string ready for the routing resolver.
    """
    # Load the base template
    base_template = load_routing_signal_prompt(repo_root)

    # Build routing configuration section
    routing_config = _build_routing_config_section(current_step, loop_state)

    # Build available steps section
    available_steps = _build_available_steps_section(flow_spec, current_step)

    # Build handoff summary section
    handoff_section = _build_handoff_section(handoff_envelope)

    # Compose the full prompt
    prompt_parts = [
        base_template,
        "",
        "---",
        "",
        "# Current Routing Context",
        "",
        handoff_section,
        "",
        routing_config,
        "",
        available_steps,
        "",
        "---",
        "",
        "Based on the above context, output a valid RoutingSignal JSON.",
    ]

    return "\n".join(prompt_parts)


def _build_handoff_section(envelope: HandoffEnvelope) -> str:
    """Build the handoff text section for the routing prompt.

    Args:
        envelope: The handoff envelope from step completion.

    Returns:
        Formatted handoff section string.
    """
    lines = [
        "## Handoff from Previous Step",
        "",
        f"**Step ID**: {envelope.step_id}",
        f"**Flow**: {envelope.flow_key}",
        f"**Status**: {envelope.status}",
        f"**Duration**: {envelope.duration_ms}ms",
        "",
        "### Summary",
        envelope.summary[:2000] if envelope.summary else "(no summary)",
    ]

    if envelope.error:
        lines.extend(
            [
                "",
                "### Error",
                envelope.error,
            ]
        )

    if envelope.artifacts:
        lines.extend(
            [
                "",
                "### Artifacts",
            ]
        )
        for name, path in envelope.artifacts.items():
            lines.append(f"- {name}: {path}")

    return "\n".join(lines)


def _build_routing_config_section(
    step: StepDefinition,
    loop_state: Dict[str, int],
) -> str:
    """Build the routing configuration section for the prompt.

    Args:
        step: The current step definition with routing config.
        loop_state: Dictionary tracking iteration counts.

    Returns:
        Formatted routing configuration string.
    """
    lines = [
        "## Step Routing Configuration",
        "",
        f"**Step ID**: {step.id}",
        f"**Step Index**: {step.index}",
        f"**Role**: {step.role}",
    ]

    routing = step.routing
    if routing is None:
        lines.extend(
            [
                "",
                "**Routing Kind**: linear (default)",
                "**Next Step**: (determined by index)",
            ]
        )
    else:
        lines.extend(
            [
                "",
                f"**Routing Kind**: {routing.kind}",
            ]
        )

        if routing.next:
            lines.append(f"**Next Step**: {routing.next}")

        if routing.kind == "microloop":
            loop_key = f"{step.id}:{routing.loop_target}" if routing.loop_target else step.id
            current_iter = loop_state.get(loop_key, 0)

            lines.extend(
                [
                    "",
                    "### Microloop Configuration",
                    f"**Loop Target**: {routing.loop_target or '(none)'}",
                    f"**Condition Field**: {routing.loop_condition_field or '(none)'}",
                    f"**Success Values**: {', '.join(routing.loop_success_values) if routing.loop_success_values else '(none)'}",
                    f"**Max Iterations**: {routing.max_iterations}",
                    f"**Current Iteration**: {current_iter}",
                ]
            )

        if routing.kind == "branch" and routing.branches:
            lines.extend(
                [
                    "",
                    "### Branch Configuration",
                ]
            )
            for condition, target in routing.branches.items():
                lines.append(f"- If `{condition}` -> `{target}`")

    return "\n".join(lines)


def _build_available_steps_section(
    flow: FlowDefinition,
    current_step: StepDefinition,
) -> str:
    """Build the available steps section for validation.

    Args:
        flow: The flow definition with all steps.
        current_step: The current step for context.

    Returns:
        Formatted available steps string.
    """
    lines = [
        "## Available Steps in Flow",
        "",
        f"**Flow**: {flow.title} ({flow.key})",
        f"**Current Step**: {current_step.id} (index {current_step.index})",
        "",
        "### All Steps",
    ]

    for step in flow.steps:
        marker = " <- (current)" if step.id == current_step.id else ""
        lines.append(f"{step.index}. `{step.id}`: {step.role}{marker}")

    return "\n".join(lines)


def parse_routing_response(response: str) -> RoutingSignal:
    """Parse the JSON response into a RoutingSignal.

    Handles various response formats:
    - Pure JSON object
    - JSON wrapped in markdown code blocks
    - JSON with surrounding text

    Args:
        response: The raw response string from the routing resolver.

    Returns:
        A RoutingSignal instance with the parsed decision.

    Raises:
        ValueError: If the response cannot be parsed as valid JSON.
    """
    # Try to extract JSON from the response
    json_str = _extract_json(response)

    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        raise ValueError(f"Failed to parse routing response as JSON: {e}") from e

    return _routing_signal_from_response(data)


def _extract_json(text: str) -> str:
    """Extract JSON from potentially wrapped text.

    Args:
        text: Raw text that may contain JSON.

    Returns:
        The extracted JSON string.
    """
    text = text.strip()

    # Try to find JSON in markdown code blocks
    code_block_patterns = [
        r"```json\s*([\s\S]*?)\s*```",
        r"```\s*([\s\S]*?)\s*```",
    ]

    for pattern in code_block_patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1).strip()

    # Try to find a JSON object directly
    # Look for { ... } pattern
    brace_match = re.search(r"\{[\s\S]*\}", text)
    if brace_match:
        return brace_match.group(0)

    # Return as-is and let JSON parsing handle errors
    return text


def _routing_signal_from_response(data: Dict[str, Any]) -> RoutingSignal:
    """Convert parsed JSON data to a RoutingSignal.

    Args:
        data: Parsed JSON dictionary.

    Returns:
        A RoutingSignal instance.
    """
    # Parse decision
    decision_str = data.get("decision", "advance")
    try:
        decision = RoutingDecision(decision_str)
    except ValueError:
        # Map alternative decision names
        decision_map = {
            "proceed": RoutingDecision.ADVANCE,
            "continue": RoutingDecision.ADVANCE,
            "next": RoutingDecision.ADVANCE,
            "rerun": RoutingDecision.LOOP,
            "retry": RoutingDecision.LOOP,
            "iterate": RoutingDecision.LOOP,
            "stop": RoutingDecision.TERMINATE,
            "end": RoutingDecision.TERMINATE,
            "complete": RoutingDecision.TERMINATE,
            "blocked": RoutingDecision.TERMINATE,
            "route": RoutingDecision.BRANCH,
            "switch": RoutingDecision.BRANCH,
        }
        decision = decision_map.get(decision_str.lower(), RoutingDecision.ADVANCE)

    # Parse next_step_id
    next_step_id = data.get("next_step_id")
    if next_step_id is None:
        # Check alternative field names
        next_step_id = data.get("next") or data.get("target") or data.get("step_id")

    # Parse route (for branch routing)
    route = data.get("route")
    if isinstance(route, dict):
        # Handle nested route object
        route = route.get("step_id") or route.get("step")

    # Parse reason
    reason = data.get("reason", "")

    # Parse confidence (0.0 to 1.0)
    confidence = data.get("confidence", 1.0)
    if isinstance(confidence, str):
        try:
            confidence = float(confidence)
        except ValueError:
            confidence = 0.7  # Default for unparseable
    confidence = max(0.0, min(1.0, confidence))

    # Parse needs_human flag
    needs_human = data.get("needs_human", False)
    if isinstance(needs_human, str):
        needs_human = needs_human.lower() in ("true", "yes", "1")

    return RoutingSignal(
        decision=decision,
        next_step_id=next_step_id,
        route=route,
        reason=reason,
        confidence=confidence,
        needs_human=needs_human,
    )


def read_receipt_field(
    repo_root: Path,
    run_id: str,
    flow_key: str,
    step_id: str,
    agent_key: str,
    field_name: str,
) -> Optional[str]:
    """Read a specific field from a receipt file.

    This is the function that the orchestrator's _route method needs to
    extract receipt fields for routing decisions.

    Args:
        repo_root: Repository root path.
        run_id: The run identifier.
        flow_key: The flow key (e.g., "build").
        step_id: The step identifier.
        agent_key: The agent key.
        field_name: The field to extract from the receipt.

    Returns:
        The field value as a string if found, None otherwise.
    """
    run_base = repo_root / "swarm" / "runs" / run_id / flow_key
    receipt_path = run_base / "receipts" / f"{step_id}-{agent_key}.json"

    if not receipt_path.exists():
        logger.debug("Receipt not found: %s", receipt_path)
        return None

    try:
        with receipt_path.open("r", encoding="utf-8") as f:
            receipt = json.load(f)

        value = receipt.get(field_name)
        if value is None:
            return None

        # Convert to string for consistent handling
        return str(value)

    except (json.JSONDecodeError, IOError) as e:
        logger.warning("Failed to read receipt %s: %s", receipt_path, e)
        return None


def validate_next_step(
    next_step_id: Optional[str],
    flow_spec: FlowDefinition,
) -> bool:
    """Validate that the proposed next step exists in the flow.

    Args:
        next_step_id: The proposed next step ID.
        flow_spec: The flow definition to validate against.

    Returns:
        True if the step exists or next_step_id is None, False otherwise.
    """
    if next_step_id is None:
        return True

    for step in flow_spec.steps:
        if step.id == next_step_id:
            return True

    return False


def get_available_next_steps(
    current_step: StepDefinition,
    flow_spec: FlowDefinition,
) -> List[str]:
    """Get list of valid next step IDs from current position.

    Args:
        current_step: The current step.
        flow_spec: The flow definition.

    Returns:
        List of valid step IDs that can be routed to.
    """
    available = []

    # Add routing.next if defined
    if current_step.routing and current_step.routing.next:
        available.append(current_step.routing.next)

    # Add loop_target if microloop
    if current_step.routing and current_step.routing.loop_target:
        available.append(current_step.routing.loop_target)

    # Add branch targets if branch routing
    if current_step.routing and current_step.routing.branches:
        available.extend(current_step.routing.branches.values())

    # Add next step by index as fallback
    next_by_index = None
    for step in flow_spec.steps:
        if step.index == current_step.index + 1:
            next_by_index = step.id
            break

    if next_by_index and next_by_index not in available:
        available.append(next_by_index)

    return available
