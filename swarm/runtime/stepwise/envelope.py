"""
envelope.py - Envelope Invariant Enforcement for Stepwise Execution.

This module provides functions to enforce the "envelope invariant": the guarantee
that a handoff envelope exists for every completed step, regardless of which
engine executed the step.

The Envelope Invariant
----------------------
The orchestrator ensures an envelope exists for every completed step because:

1. Non-lifecycle engines (GeminiStepEngine) don't call finalize_step(), so they
   may not create envelopes during execution.

2. Routing code (Navigator, deterministic routing) expects envelopes to exist
   at canonical paths after step completion.

3. The envelope is the canonical ledger entry for the step - without it, the
   step's outcome is invisible to downstream components.

If the engine didn't create an envelope (common in stub/non-lifecycle engines),
the orchestrator creates a minimal one with essential fields as a "last resort"
fallback. These fallback envelopes are marked with `_envelope_source: orchestrator_fallback`
for debugging purposes.

Usage:
    from swarm.runtime.stepwise.envelope import ensure_step_envelope

    # After step execution completes:
    created = ensure_step_envelope(
        run_base=run_base,
        step_id=step.id,
        step_result=step_result,
        flow_key=flow_key,
        run_id=run_id,
    )
    if created:
        logger.debug("Fallback envelope created for step %s", step.id)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from swarm.runtime.handoff_io import write_handoff_envelope
from swarm.runtime.path_helpers import handoff_envelope_path

logger = logging.getLogger(__name__)

__all__ = [
    "ensure_step_envelope",
    "write_minimal_envelope",
]


def ensure_step_envelope(
    run_base: Path,
    step_id: str,
    step_result: Any,
    flow_key: str,
    run_id: str,
    *,
    source: str = "orchestrator_fallback",
) -> bool:
    """Ensure a handoff envelope exists for the completed step.

    This function enforces the envelope invariant: every completed step must
    have a handoff envelope at the canonical path. If the engine that executed
    the step did not create an envelope, this function creates a minimal one.

    The minimal envelope contains essential fields required by downstream
    components (routing, observability, auditing) but may lack detailed
    artifacts that a full lifecycle engine would produce.

    Args:
        run_base: The RUN_BASE path (e.g., swarm/runs/<run-id>/<flow-key>)
        step_id: Step identifier within the flow
        step_result: The StepResult object from step execution, expected to have:
            - status: str ("succeeded", "failed", etc.)
            - output: Optional[str] - step output text
            - duration_ms: int - execution duration in milliseconds
        flow_key: The flow key (e.g., "build", "signal")
        run_id: The run identifier
        source: Marker for debugging envelope provenance (default: "orchestrator_fallback")

    Returns:
        True if a fallback envelope was created, False if envelope already existed.

    Raises:
        No exceptions are raised. Errors are logged as warnings and the function
        returns False to indicate the envelope could not be guaranteed.

    Example:
        >>> from swarm.runtime.stepwise.envelope import ensure_step_envelope
        >>> created = ensure_step_envelope(
        ...     run_base=Path("swarm/runs/abc123/build"),
        ...     step_id="1",
        ...     step_result=step_result,
        ...     flow_key="build",
        ...     run_id="abc123",
        ... )
        >>> if created:
        ...     print("Created fallback envelope")
    """
    envelope_path = handoff_envelope_path(run_base, step_id)

    if envelope_path.exists():
        # Envelope already exists - invariant is satisfied
        return False

    # Build minimal envelope with essential fields
    # Extract output safely with fallback
    output = ""
    if hasattr(step_result, "output") and step_result.output:
        output = step_result.output[:500]  # Truncate for summary
    summary = output if output else f"Step {step_id} completed"

    # Map step result status to envelope status
    status = "VERIFIED" if getattr(step_result, "status", "") == "succeeded" else "UNVERIFIED"

    # Extract duration safely
    duration_ms = getattr(step_result, "duration_ms", 0)

    minimal_envelope: Dict[str, Any] = {
        "step_id": step_id,
        "flow_key": flow_key,
        "run_id": run_id,
        "status": status,
        "summary": summary,
        "duration_ms": duration_ms,
        "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
        "artifacts": [],
        # Mark envelope source for debugging provenance
        "_envelope_source": source,
    }

    try:
        write_handoff_envelope(
            run_base=run_base,
            step_id=step_id,
            envelope_data=minimal_envelope,
            write_draft=True,
            validate=False,  # Skip validation for minimal envelopes
        )
        logger.debug(
            "Created fallback envelope for step %s (engine didn't create one)",
            step_id,
        )
        return True

    except Exception as err:
        logger.warning(
            "Failed to create fallback envelope for step %s: %s",
            step_id,
            err,
        )
        return False


def write_minimal_envelope(
    run_base: Path,
    step_id: str,
    envelope_data: Dict[str, Any],
    *,
    validate: bool = False,
) -> None:
    """Write a minimal handoff envelope with source marker.

    This is a convenience wrapper around write_handoff_envelope for writing
    minimal envelopes. It automatically sets the `_envelope_source` marker
    if not already present in the envelope data.

    Minimal envelopes are typically created as fallbacks when the primary
    envelope creation path (lifecycle engine finalize) did not execute.

    Args:
        run_base: The RUN_BASE path (e.g., swarm/runs/<run-id>/<flow-key>)
        step_id: Step identifier within the flow
        envelope_data: The envelope dictionary to write. Should contain at minimum:
            - step_id: str
            - flow_key: str
            - status: str ("VERIFIED", "UNVERIFIED", etc.)
        validate: If True, validate against schema before writing (default False
            for minimal envelopes since they may lack optional fields)

    Raises:
        OSError: If file write fails.
        EnvelopeValidationError: If validation is enabled and fails in strict mode.

    Example:
        >>> write_minimal_envelope(
        ...     run_base=Path("swarm/runs/abc123/build"),
        ...     step_id="1",
        ...     envelope_data={
        ...         "step_id": "1",
        ...         "flow_key": "build",
        ...         "run_id": "abc123",
        ...         "status": "VERIFIED",
        ...         "summary": "Step completed successfully",
        ...     },
        ... )
    """
    # Set default envelope source marker if not present
    if "_envelope_source" not in envelope_data:
        envelope_data["_envelope_source"] = "minimal_envelope"

    write_handoff_envelope(
        run_base=run_base,
        step_id=step_id,
        envelope_data=envelope_data,
        write_draft=True,
        validate=validate,
    )
