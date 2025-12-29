"""
handoff_io.py - Unified handoff envelope persistence.

This module provides a single IO function for all handoff envelope writes,
ensuring consistent behavior across:
- WP6 session finalize
- Legacy lifecycle finalize
- Stub mode finalize

All handoff persistence goes through write_handoff_envelope() to ensure:
- Consistent path handling (draft + committed)
- Optional schema validation
- Atomic writes (future)
- Single point of change for schema bumps, extra fields, etc.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from swarm.runtime.path_helpers import (
    ensure_handoff_dir,
    handoff_envelope_path as make_handoff_envelope_path,
)

logger = logging.getLogger(__name__)

# Cached schema to avoid repeated file reads
_HANDOFF_SCHEMA: Optional[Dict[str, Any]] = None
_ROUTING_SIGNAL_SCHEMA: Optional[Dict[str, Any]] = None

# Try to import jsonschema, graceful fallback if not available
try:
    import jsonschema

    JSONSCHEMA_AVAILABLE = True
except ImportError:
    JSONSCHEMA_AVAILABLE = False
    jsonschema = None  # type: ignore[assignment]


def _load_handoff_schema() -> Optional[Dict[str, Any]]:
    """Load handoff envelope schema, caching result."""
    global _HANDOFF_SCHEMA
    if _HANDOFF_SCHEMA is not None:
        return _HANDOFF_SCHEMA

    schema_paths = [
        Path(__file__).parent.parent / "schemas" / "handoff_envelope.schema.json",
        Path("swarm/schemas/handoff_envelope.schema.json"),
    ]

    for path in schema_paths:
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    _HANDOFF_SCHEMA = json.load(f)
                return _HANDOFF_SCHEMA
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("Failed to load handoff schema from %s: %s", path, e)
                continue

    return None


def _load_routing_signal_schema() -> Optional[Dict[str, Any]]:
    """Load routing signal schema, caching result."""
    global _ROUTING_SIGNAL_SCHEMA
    if _ROUTING_SIGNAL_SCHEMA is not None:
        return _ROUTING_SIGNAL_SCHEMA

    schema_paths = [
        Path(__file__).parent.parent / "schemas" / "routing_signal.schema.json",
        Path("swarm/schemas/routing_signal.schema.json"),
    ]

    for path in schema_paths:
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    _ROUTING_SIGNAL_SCHEMA = json.load(f)
                return _ROUTING_SIGNAL_SCHEMA
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("Failed to load routing signal schema from %s: %s", path, e)
                continue

    return None


def _create_schema_resolver() -> Optional[Any]:
    """Create a JSON schema resolver that handles $ref to routing_signal.schema.json."""
    if not JSONSCHEMA_AVAILABLE:
        return None

    handoff_schema = _load_handoff_schema()
    routing_schema = _load_routing_signal_schema()

    if handoff_schema is None:
        return None

    store: Dict[str, Any] = {}
    if routing_schema is not None:
        store["https://swarm.dev/schemas/routing_signal.schema.json"] = routing_schema

    resolver = jsonschema.RefResolver.from_schema(handoff_schema, store=store)
    return resolver


def validate_envelope(envelope_dict: Dict[str, Any]) -> List[str]:
    """Validate envelope dict against JSON schema.

    Args:
        envelope_dict: The envelope dictionary to validate.

    Returns:
        List of validation error messages (empty if valid or
        validation could not be performed).
    """
    if not JSONSCHEMA_AVAILABLE:
        logger.debug("jsonschema not available, skipping envelope validation")
        return []

    schema = _load_handoff_schema()
    if schema is None:
        logger.debug("Handoff envelope schema not found, skipping validation")
        return []

    errors: List[str] = []
    try:
        resolver = _create_schema_resolver()
        if resolver is not None:
            jsonschema.validate(envelope_dict, schema, resolver=resolver)
        else:
            jsonschema.validate(envelope_dict, schema)
    except jsonschema.ValidationError as e:
        json_path = e.json_path if hasattr(e, "json_path") else str(list(e.absolute_path))
        errors.append(f"Validation error at {json_path}: {e.message}")
    except jsonschema.SchemaError as e:
        errors.append(f"Schema error: {e.message}")
    except Exception as e:
        errors.append(f"Unexpected validation error: {str(e)}")

    return errors


def is_strict_validation_enabled() -> bool:
    """Check if strict envelope validation mode is enabled.

    Returns:
        True if SWARM_STRICT_ENVELOPE_VALIDATION is set to a truthy value.
    """
    strict_env = os.environ.get("SWARM_STRICT_ENVELOPE_VALIDATION", "").lower()
    return strict_env in ("1", "true", "yes", "on")


class EnvelopeValidationError(Exception):
    """Raised when envelope validation fails in strict mode."""

    def __init__(self, errors: List[str]) -> None:
        self.errors = errors
        super().__init__(f"Envelope validation failed: {'; '.join(errors)}")


def write_handoff_envelope(
    run_base: Path,
    step_id: str,
    envelope_data: Dict[str, Any],
    *,
    write_draft: bool = True,
    validate: bool = True,
) -> Dict[str, Any]:
    """Persist a handoff envelope to disk.

    This is THE canonical function for all handoff envelope writes.
    All code paths that persist envelopes should call this function.

    Args:
        run_base: The RUN_BASE path (e.g., swarm/runs/<run-id>/<flow-key>)
        step_id: Step identifier within the flow
        envelope_data: The envelope dictionary to write
        write_draft: If True, also write <step_id>.draft.json (default True)
        validate: If True, validate against schema before writing (default True)

    Returns:
        The envelope_data dict (with timestamp added if not present)

    Raises:
        EnvelopeValidationError: If validation fails and strict mode is enabled.
        OSError: If file write fails.
    """
    # Ensure handoff directory exists
    ensure_handoff_dir(run_base)

    # Add timestamp if not present
    if "timestamp" not in envelope_data:
        envelope_data["timestamp"] = datetime.now(timezone.utc).isoformat() + "Z"

    # Validate if requested
    if validate:
        validation_errors = validate_envelope(envelope_data)
        if validation_errors:
            if is_strict_validation_enabled():
                logger.error(
                    "Envelope validation failed for step %s: %s",
                    step_id,
                    validation_errors,
                )
                raise EnvelopeValidationError(validation_errors)
            else:
                logger.warning(
                    "Envelope validation warnings for step %s: %s",
                    step_id,
                    validation_errors,
                )

    # Write draft file for debugging (optional)
    if write_draft:
        draft_path = run_base / "handoff" / f"{step_id}.draft.json"
        with draft_path.open("w", encoding="utf-8") as f:
            json.dump(envelope_data, f, indent=2)
        logger.debug("Wrote draft envelope to %s", draft_path)

    # Write committed envelope at canonical path
    committed_path = make_handoff_envelope_path(run_base, step_id)
    with committed_path.open("w", encoding="utf-8") as f:
        json.dump(envelope_data, f, indent=2)
    logger.debug("Wrote committed envelope to %s", committed_path)

    return envelope_data


def update_envelope_routing(
    run_base: Path,
    step_id: str,
    routing_signal: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Update an existing envelope's routing_signal field.

    Used to patch routing signal into an envelope after the route phase
    completes (when envelope was already written during finalize phase).

    Args:
        run_base: The RUN_BASE path
        step_id: Step identifier
        routing_signal: Routing signal dict to add/update

    Returns:
        Updated envelope dict, or None if envelope doesn't exist.
    """
    committed_path = make_handoff_envelope_path(run_base, step_id)

    if not committed_path.exists():
        logger.warning("Cannot update routing: envelope not found at %s", committed_path)
        return None

    try:
        with committed_path.open("r", encoding="utf-8") as f:
            envelope_data = json.load(f)

        envelope_data["routing_signal"] = routing_signal

        with committed_path.open("w", encoding="utf-8") as f:
            json.dump(envelope_data, f, indent=2)

        logger.debug("Updated envelope routing_signal for step %s", step_id)
        return envelope_data

    except (json.JSONDecodeError, OSError) as e:
        logger.warning(
            "Failed to update envelope routing for step %s: %s",
            step_id,
            e,
        )
        return None


def read_handoff_envelope(
    run_base: Path,
    step_id: str,
    prefer_draft: bool = False,
) -> Optional[Dict[str, Any]]:
    """Read a handoff envelope from disk.

    Args:
        run_base: The RUN_BASE path
        step_id: Step identifier
        prefer_draft: If True, read draft file if it exists (default False)

    Returns:
        Parsed envelope dict, or None if not found.
    """
    if prefer_draft:
        draft_path = run_base / "handoff" / f"{step_id}.draft.json"
        if draft_path.exists():
            try:
                with draft_path.open("r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("Failed to read draft envelope %s: %s", draft_path, e)

    committed_path = make_handoff_envelope_path(run_base, step_id)
    if committed_path.exists():
        try:
            with committed_path.open("r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to read committed envelope %s: %s", committed_path, e)

    return None
