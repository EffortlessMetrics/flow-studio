"""
envelope.py - HandoffEnvelope creation and writing for Claude step engine.

Handles:
- Envelope creation from step results
- Envelope writing to disk (delegating to handoff_io)
- Fallback envelope generation

NOTE: Actual file I/O is delegated to swarm.runtime.handoff_io for consistency.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

from swarm.runtime.handoff_io import (
    EnvelopeValidationError,
)
from swarm.runtime.handoff_io import (
    write_handoff_envelope as _write_handoff_envelope_io,
)
from swarm.runtime.types import (
    HandoffEnvelope,
    RoutingCandidate,
    RoutingDecision,
    RoutingSignal,
    handoff_envelope_to_dict,
)

from ..models import StepContext, StepResult

logger = logging.getLogger(__name__)


def create_fallback_envelope(
    ctx: StepContext,
    step_result: StepResult,
    routing_signal: Optional[RoutingSignal],
    work_summary: str,
    file_changes: Optional[Dict[str, Any]] = None,
) -> HandoffEnvelope:
    """Create a fallback HandoffEnvelope without LLM assistance.

    Used when envelope_writer.md template is not available or parsing fails.

    Args:
        ctx: Step execution context.
        step_result: Result from step execution.
        routing_signal: Routing decision from router session (may be None).
        work_summary: Summary text from the step's work session.
        file_changes: Forensic file mutation scan results (optional).

    Returns:
        HandoffEnvelope with basic step information.
    """
    # Create routing signal with proper audit fields for fallback path
    if routing_signal is None:
        fallback_reason = "Fallback envelope: template not found or parsing failed"
        fallback_routing = RoutingSignal(
            decision=RoutingDecision.ADVANCE,
            reason=fallback_reason,
            confidence=0.5,  # Lower confidence for fallback path
            routing_source="fallback_envelope",
            chosen_candidate_id="fallback:advance:auto",
            routing_candidates=[
                RoutingCandidate(
                    candidate_id="fallback:advance:auto",
                    action="advance",
                    target_node=None,
                    reason=fallback_reason,
                    priority=10,
                    source="envelope_fallback",
                    is_default=True,
                )
            ],
        )
    else:
        fallback_routing = routing_signal

    envelope = HandoffEnvelope(
        step_id=ctx.step_id,
        flow_key=ctx.flow_key,
        run_id=ctx.run_id,
        routing_signal=fallback_routing,
        summary=work_summary[:2000]
        if work_summary
        else f"Step {ctx.step_id} completed with status {step_result.status}",
        artifacts=step_result.artifacts or {},
        file_changes=file_changes or {},
        status=step_result.status,
        error=step_result.error,
        duration_ms=step_result.duration_ms,
    )

    # Write envelope to disk
    envelope_path = write_envelope_to_disk(ctx, envelope)
    if envelope_path:
        logger.debug("Wrote fallback handoff envelope to %s", envelope_path)

    return envelope


def write_envelope_to_disk(
    ctx: StepContext,
    envelope: HandoffEnvelope,
) -> Optional[Path]:
    """Write HandoffEnvelope to disk at RUN_BASE/<flow_key>/handoff/<step_id>.json.

    Delegates to swarm.runtime.handoff_io for actual file writing.
    Validates the envelope against the JSON schema before writing.

    Args:
        ctx: Step execution context.
        envelope: The HandoffEnvelope to write.

    Returns:
        Path to the written file, or None if writing failed.

    Raises:
        EnvelopeValidationError: If validation fails and strict mode is enabled.
    """
    try:
        # Convert envelope to dict for JSON serialization
        envelope_dict = handoff_envelope_to_dict(envelope)

        # Delegate to unified handoff_io (handles validation, directory creation, writing)
        _write_handoff_envelope_io(
            run_base=ctx.run_base,
            step_id=ctx.step_id,
            envelope_data=envelope_dict,
            write_draft=False,  # envelope.py only writes committed path
            validate=True,
        )

        # Return the path that was written
        from swarm.runtime.path_helpers import handoff_envelope_path

        return handoff_envelope_path(ctx.run_base, ctx.step_id)

    except EnvelopeValidationError:
        # Re-raise validation errors in strict mode
        raise
    except (OSError, IOError) as e:
        logger.warning("Failed to write handoff envelope for step %s: %s", ctx.step_id, e)
        return None


async def write_handoff_envelope(
    ctx: StepContext,
    step_result: StepResult,
    routing_signal: Optional[RoutingSignal],
    work_summary: str,
    file_changes: Optional[Dict[str, Any]] = None,
) -> Optional[HandoffEnvelope]:
    """Write structured HandoffEnvelope using envelope_writer resolver.

    Called after JIT finalization to create the durable handoff artifact.
    Uses the envelope_writer.md template to generate a structured envelope
    with routing signal, summary, and artifact pointers.

    Args:
        ctx: Step execution context with flow/step metadata.
        step_result: Result from step execution.
        routing_signal: Routing decision from router session (may be None).
        work_summary: Summary text from the step's work session.
        file_changes: Forensic file mutation scan results (optional).

    Returns:
        HandoffEnvelope if successfully created, None otherwise.
    """
    # Load envelope_writer.md template
    template_path = (
        Path(ctx.repo_root) / "swarm" / "prompts" / "resolvers" / "envelope_writer.md"
        if ctx.repo_root
        else Path("swarm/prompts/resolvers/envelope_writer.md")
    )

    if not template_path.exists():
        logger.warning("envelope_writer.md template not found at %s", template_path)
        return create_fallback_envelope(
            ctx, step_result, routing_signal, work_summary, file_changes
        )

    try:
        template_content = template_path.read_text(encoding="utf-8")
    except (OSError, IOError) as e:
        logger.warning("Failed to load envelope_writer.md: %s", e)
        return create_fallback_envelope(
            ctx, step_result, routing_signal, work_summary, file_changes
        )

    # Import SDK here to avoid circular imports
    from swarm.runtime.claude_sdk import create_high_trust_options, get_sdk_module

    sdk = get_sdk_module()
    query = sdk.query

    # Build input data for the envelope writer
    routing_data = {
        "decision": routing_signal.decision.value if routing_signal else "advance",
        "next_step_id": routing_signal.next_step_id if routing_signal else None,
        "route": routing_signal.route if routing_signal else None,
        "reason": routing_signal.reason if routing_signal else "default_advance",
        "confidence": routing_signal.confidence if routing_signal else 0.7,
        "needs_human": routing_signal.needs_human if routing_signal else False,
    }

    # Collect artifact information
    artifacts_created = step_result.artifacts or {}

    # Build the prompt for envelope writer
    envelope_input = f"""
## Step Execution Results

Step ID: {ctx.step_id}
Flow key: {ctx.flow_key}
Run ID: {ctx.run_id}
Status: {step_result.status}
Duration: {step_result.duration_ms} ms
Error: {step_result.error or "None"}

## Work Summary
{work_summary[:4000] if work_summary else "No summary available."}

## Artifacts Created/Modified
{json.dumps(artifacts_created, indent=2)}

## Routing Signal
{json.dumps(routing_data, indent=2)}

---
{template_content}
"""

    # Set up working directory
    cwd = str(ctx.repo_root) if ctx.repo_root else str(Path.cwd())

    # Envelope writer uses minimal options
    options = create_high_trust_options(
        cwd=cwd,
        permission_mode="bypassPermissions",
    )

    # Collect envelope writer response
    envelope_response = ""

    try:
        logger.debug("Starting envelope writer session for step %s", ctx.step_id)

        async for event in query(
            prompt=envelope_input,
            options=options,
        ):
            if hasattr(event, "message"):
                message = getattr(event, "message", event)
                content = getattr(message, "content", "")
                if isinstance(content, list):
                    text_parts = [
                        getattr(b, "text", str(getattr(b, "content", ""))) for b in content
                    ]
                    content = "\n".join(text_parts)
                if content:
                    envelope_response += content

        logger.debug("Envelope writer session complete for step %s", ctx.step_id)

        # Parse JSON from response
        json_match = None
        if "```json" in envelope_response:
            start = envelope_response.find("```json") + 7
            end = envelope_response.find("```", start)
            if end > start:
                json_match = envelope_response[start:end].strip()
        elif "```" in envelope_response:
            start = envelope_response.find("```") + 3
            end = envelope_response.find("```", start)
            if end > start:
                json_match = envelope_response[start:end].strip()
        else:
            json_match = envelope_response.strip()

        if not json_match:
            logger.warning("Envelope writer response contained no parseable JSON")
            return create_fallback_envelope(
                ctx, step_result, routing_signal, work_summary, file_changes
            )

        envelope_data = json.loads(json_match)

        # Create routing signal with proper audit fields if not provided
        if routing_signal is None:
            parsed_routing_reason = "Parsed envelope with default advance routing"
            parsed_routing_signal = RoutingSignal(
                decision=RoutingDecision.ADVANCE,
                reason=parsed_routing_reason,
                confidence=0.7,
                routing_source="envelope_writer_parsed",
                chosen_candidate_id="parsed:advance:default",
                routing_candidates=[
                    RoutingCandidate(
                        candidate_id="parsed:advance:default",
                        action="advance",
                        target_node=None,
                        reason=parsed_routing_reason,
                        priority=50,
                        source="envelope_writer",
                        is_default=True,
                    )
                ],
            )
        else:
            parsed_routing_signal = routing_signal

        # Create HandoffEnvelope from parsed data
        envelope = HandoffEnvelope(
            step_id=envelope_data.get("step_id", ctx.step_id),
            flow_key=envelope_data.get("flow_key", ctx.flow_key),
            run_id=envelope_data.get("run_id", ctx.run_id),
            routing_signal=parsed_routing_signal,
            summary=envelope_data.get("summary", work_summary[:2000] if work_summary else ""),
            artifacts=envelope_data.get("artifacts", {}),
            file_changes=file_changes or {},
            status=envelope_data.get("status", step_result.status),
            error=envelope_data.get("error"),
            duration_ms=envelope_data.get("duration_ms", step_result.duration_ms),
        )

        # Write envelope to disk
        envelope_path = write_envelope_to_disk(ctx, envelope)
        if envelope_path:
            logger.debug("Wrote handoff envelope to %s", envelope_path)

        return envelope

    except json.JSONDecodeError as e:
        logger.warning("Failed to parse envelope writer response as JSON: %s", e)
        return create_fallback_envelope(
            ctx, step_result, routing_signal, work_summary, file_changes
        )
    except Exception as e:
        logger.warning("Envelope writer session failed for step %s: %s", ctx.step_id, e)
        return create_fallback_envelope(
            ctx, step_result, routing_signal, work_summary, file_changes
        )
