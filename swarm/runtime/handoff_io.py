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
from typing import Any, Dict, List, Optional

from swarm.runtime.path_helpers import (
    ensure_forensics_dir,
    ensure_handoff_dir,
    file_changes_path as make_file_changes_path,
    handoff_envelope_path as make_handoff_envelope_path,
)

logger = logging.getLogger(__name__)

# Threshold for extracting file_changes to out-of-line storage (in bytes)
# If serialized file_changes exceeds this size, it's moved to forensics directory
FILE_CHANGES_EXTRACTION_THRESHOLD = 1000

# Cached schemas to avoid repeated file reads
_HANDOFF_SCHEMA: Optional[Dict[str, Any]] = None
_ROUTING_SIGNAL_SCHEMA: Optional[Dict[str, Any]] = None
_ASSUMPTION_RECORD_SCHEMA: Optional[Dict[str, Any]] = None
_DECISION_RECORD_SCHEMA: Optional[Dict[str, Any]] = None

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


def _load_assumption_record_schema() -> Optional[Dict[str, Any]]:
    """Load assumption record schema, caching result."""
    global _ASSUMPTION_RECORD_SCHEMA
    if _ASSUMPTION_RECORD_SCHEMA is not None:
        return _ASSUMPTION_RECORD_SCHEMA

    schema_paths = [
        Path(__file__).parent.parent / "schemas" / "assumption_record.schema.json",
        Path("swarm/schemas/assumption_record.schema.json"),
    ]

    for path in schema_paths:
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    _ASSUMPTION_RECORD_SCHEMA = json.load(f)
                return _ASSUMPTION_RECORD_SCHEMA
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("Failed to load assumption record schema from %s: %s", path, e)
                continue

    return None


def _load_decision_record_schema() -> Optional[Dict[str, Any]]:
    """Load decision record schema, caching result."""
    global _DECISION_RECORD_SCHEMA
    if _DECISION_RECORD_SCHEMA is not None:
        return _DECISION_RECORD_SCHEMA

    schema_paths = [
        Path(__file__).parent.parent / "schemas" / "decision_record.schema.json",
        Path("swarm/schemas/decision_record.schema.json"),
    ]

    for path in schema_paths:
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    _DECISION_RECORD_SCHEMA = json.load(f)
                return _DECISION_RECORD_SCHEMA
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("Failed to load decision record schema from %s: %s", path, e)
                continue

    return None


def _create_schema_resolver() -> Optional[Any]:
    """Create a JSON schema resolver that handles $ref to all related schemas."""
    if not JSONSCHEMA_AVAILABLE:
        return None

    handoff_schema = _load_handoff_schema()
    routing_schema = _load_routing_signal_schema()
    assumption_schema = _load_assumption_record_schema()
    decision_schema = _load_decision_record_schema()

    if handoff_schema is None:
        return None

    store: Dict[str, Any] = {}
    if routing_schema is not None:
        store["https://swarm.dev/schemas/routing_signal.schema.json"] = routing_schema
    if assumption_schema is not None:
        store["https://swarm.dev/schemas/assumption_record.schema.json"] = assumption_schema
    if decision_schema is not None:
        store["https://swarm.dev/schemas/decision_record.schema.json"] = decision_schema

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

    When file_changes data exceeds FILE_CHANGES_EXTRACTION_THRESHOLD bytes,
    it is extracted to a separate file in the forensics directory to reduce
    ledger bloat. The envelope then contains a file_changes_path reference
    instead of the inline data.

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

    # Validate if requested (before extraction, so we validate the full envelope)
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

    # Extract file_changes to out-of-line storage if it exceeds threshold
    file_changes = envelope_data.get("file_changes")
    extracted_file_changes_path: Optional[Path] = None

    if file_changes:
        file_changes_json = json.dumps(file_changes)
        if len(file_changes_json) > FILE_CHANGES_EXTRACTION_THRESHOLD:
            # Write file_changes to forensics directory
            ensure_forensics_dir(run_base)
            extracted_file_changes_path = make_file_changes_path(run_base, step_id)

            with extracted_file_changes_path.open("w", encoding="utf-8") as f:
                json.dump(file_changes, f, indent=2)

            logger.debug(
                "Extracted file_changes (%d bytes) to %s",
                len(file_changes_json),
                extracted_file_changes_path,
            )

            # Replace inline data with path reference in the envelope
            # Store relative path with forward slashes for cross-platform portability
            relative_path = extracted_file_changes_path.relative_to(run_base)
            envelope_data["file_changes"] = None
            # Use as_posix() to ensure forward slashes on all platforms
            envelope_data["file_changes_path"] = relative_path.as_posix()

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


def _hydrate_file_changes(
    envelope_data: Dict[str, Any],
    run_base: Path,
) -> Dict[str, Any]:
    """Hydrate file_changes from external file if referenced by path.

    If the envelope contains file_changes_path but no file_changes data,
    this function loads the file_changes from the referenced path and
    populates the file_changes field.

    Args:
        envelope_data: The envelope dictionary to hydrate.
        run_base: The RUN_BASE path for resolving relative paths.

    Returns:
        The envelope_data dict with file_changes hydrated (if applicable).
    """
    file_changes_path_str = envelope_data.get("file_changes_path")
    file_changes = envelope_data.get("file_changes")

    # Only hydrate if we have a path reference but no inline data
    if file_changes_path_str and not file_changes:
        fc_path = run_base / file_changes_path_str
        if fc_path.exists():
            try:
                with fc_path.open("r", encoding="utf-8") as f:
                    envelope_data["file_changes"] = json.load(f)
                logger.debug("Hydrated file_changes from %s", fc_path)
            except (json.JSONDecodeError, OSError) as e:
                logger.warning(
                    "Failed to hydrate file_changes from %s: %s",
                    fc_path,
                    e,
                )
        else:
            logger.warning(
                "file_changes_path %s does not exist, cannot hydrate",
                fc_path,
            )

    return envelope_data


def read_handoff_envelope(
    run_base: Path,
    step_id: str,
    prefer_draft: bool = False,
    hydrate_file_changes: bool = True,
) -> Optional[Dict[str, Any]]:
    """Read a handoff envelope from disk.

    When file_changes was extracted to an out-of-line file during write,
    this function automatically hydrates it back into the envelope (unless
    hydrate_file_changes=False).

    Args:
        run_base: The RUN_BASE path
        step_id: Step identifier
        prefer_draft: If True, read draft file if it exists (default False)
        hydrate_file_changes: If True, load file_changes from external file
            if referenced by file_changes_path (default True)

    Returns:
        Parsed envelope dict (with file_changes hydrated), or None if not found.
    """
    envelope_data: Optional[Dict[str, Any]] = None

    if prefer_draft:
        draft_path = run_base / "handoff" / f"{step_id}.draft.json"
        if draft_path.exists():
            try:
                with draft_path.open("r", encoding="utf-8") as f:
                    envelope_data = json.load(f)
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("Failed to read draft envelope %s: %s", draft_path, e)

    if envelope_data is None:
        committed_path = make_handoff_envelope_path(run_base, step_id)
        if committed_path.exists():
            try:
                with committed_path.open("r", encoding="utf-8") as f:
                    envelope_data = json.load(f)
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("Failed to read committed envelope %s: %s", committed_path, e)

    if envelope_data is None:
        return None

    # Hydrate file_changes from external file if needed
    if hydrate_file_changes:
        envelope_data = _hydrate_file_changes(envelope_data, run_base)

    return envelope_data


def read_routing_from_envelope(
    run_base: Path,
    step_id: str,
) -> Optional[Dict[str, Any]]:
    """Read routing_signal from a committed envelope.

    This is the A3 envelope-first routing helper. It reads the committed
    envelope and returns the routing_signal if present.

    Used by the orchestrator to implement envelope-first routing:
    1. Read committed envelope
    2. If routing_signal exists, use it for routing
    3. If missing, fallback to engine.route_step() and persist result

    Args:
        run_base: The RUN_BASE path
        step_id: Step identifier

    Returns:
        routing_signal dict if present, None otherwise.
    """
    envelope = read_handoff_envelope(run_base, step_id, prefer_draft=False)
    if envelope is None:
        logger.debug("No committed envelope found for step %s", step_id)
        return None

    routing_signal = envelope.get("routing_signal")
    if routing_signal is None:
        logger.debug("Envelope for step %s has no routing_signal", step_id)
        return None

    logger.debug(
        "Read routing_signal from envelope for step %s: decision=%s",
        step_id,
        routing_signal.get("decision", "unknown"),
    )
    return routing_signal


# -----------------------------------------------------------------------------
# Assumption and Decision Logging Helpers
# -----------------------------------------------------------------------------


def add_assumption(
    envelope_data: Dict[str, Any],
    assumption_entry: Dict[str, Any],
) -> Dict[str, Any]:
    """Add an assumption entry to an envelope's assumptions_made list.

    This helper enables structured assumption logging during step execution.
    Assumptions are recorded when agents face ambiguity and proceed with
    their best interpretation.

    Args:
        envelope_data: The envelope dictionary to modify.
        assumption_entry: The assumption entry to add. Should contain:
            - assumption_id: Unique identifier (auto-generated if not provided)
            - flow_introduced: Flow key where assumption was made
            - step_introduced: Step ID where assumption was made
            - agent: Agent key that made the assumption
            - statement: The assumption itself
            - rationale: Why this assumption was made
            - impact_if_wrong: What changes if assumption is incorrect
            - confidence: "high", "medium", or "low" (default: "medium")
            - status: "active", "resolved", or "invalidated" (default: "active")
            - tags: List of categorization tags (optional)
            - timestamp: ISO 8601 timestamp (auto-added if not present)

    Returns:
        The modified envelope_data with the assumption added.

    Example:
        >>> envelope = {"step_id": "1", "flow_key": "signal", ...}
        >>> add_assumption(envelope, {
        ...     "assumption_id": "asm-001",
        ...     "flow_introduced": "signal",
        ...     "step_introduced": "1",
        ...     "agent": "requirements-author",
        ...     "statement": "User wants REST API, not GraphQL",
        ...     "rationale": "No explicit API style mentioned; REST is conventional",
        ...     "impact_if_wrong": "Would need to redesign API layer for GraphQL",
        ...     "confidence": "medium",
        ...     "tags": ["architecture", "api"]
        ... })
    """
    if "assumptions_made" not in envelope_data:
        envelope_data["assumptions_made"] = []

    # Auto-generate ID if not provided
    if "assumption_id" not in assumption_entry:
        import uuid

        assumption_entry["assumption_id"] = f"asm-{uuid.uuid4().hex[:8]}"

    # Add timestamp if not present
    if "timestamp" not in assumption_entry:
        assumption_entry["timestamp"] = datetime.now(timezone.utc).isoformat() + "Z"

    # Set defaults
    if "confidence" not in assumption_entry:
        assumption_entry["confidence"] = "medium"
    if "status" not in assumption_entry:
        assumption_entry["status"] = "active"
    if "tags" not in assumption_entry:
        assumption_entry["tags"] = []

    envelope_data["assumptions_made"].append(assumption_entry)
    logger.debug(
        "Added assumption %s to envelope for step %s",
        assumption_entry.get("assumption_id"),
        envelope_data.get("step_id"),
    )
    return envelope_data


def add_decision(
    envelope_data: Dict[str, Any],
    decision_entry: Dict[str, Any],
) -> Dict[str, Any]:
    """Add a decision entry to an envelope's decisions_made list.

    This helper enables structured decision logging during step execution.
    Decisions are significant choices made by agents that affect the
    direction of work.

    Args:
        envelope_data: The envelope dictionary to modify.
        decision_entry: The decision entry to add. Should contain:
            - decision_id: Unique identifier (auto-generated if not provided)
            - flow: Flow key where decision was made
            - step: Step ID where decision was made
            - agent: Agent key that made the decision
            - decision_type: Category (e.g., "design", "implementation", "routing")
            - subject: What the decision is about
            - decision: The actual decision made
            - rationale: Why this decision was made
            - supporting_evidence: List of evidence (optional)
            - conditions: Conditions when this applies (optional)
            - assumptions_applied: IDs of related assumptions (optional)
            - timestamp: ISO 8601 timestamp (auto-added if not present)

    Returns:
        The modified envelope_data with the decision added.

    Example:
        >>> envelope = {"step_id": "3", "flow_key": "plan", ...}
        >>> add_decision(envelope, {
        ...     "decision_id": "dec-001",
        ...     "flow": "plan",
        ...     "step": "3",
        ...     "agent": "design-optioneer",
        ...     "decision_type": "architecture",
        ...     "subject": "Database selection",
        ...     "decision": "Use PostgreSQL for primary data store",
        ...     "rationale": "Team expertise + ACID requirements + JSON support",
        ...     "supporting_evidence": ["requirements.md:L45", "team_skills.md"],
        ...     "assumptions_applied": ["asm-001"]
        ... })
    """
    if "decisions_made" not in envelope_data:
        envelope_data["decisions_made"] = []

    # Auto-generate ID if not provided
    if "decision_id" not in decision_entry:
        import uuid

        decision_entry["decision_id"] = f"dec-{uuid.uuid4().hex[:8]}"

    # Add timestamp if not present
    if "timestamp" not in decision_entry:
        decision_entry["timestamp"] = datetime.now(timezone.utc).isoformat() + "Z"

    # Set defaults for optional list fields
    if "supporting_evidence" not in decision_entry:
        decision_entry["supporting_evidence"] = []
    if "conditions" not in decision_entry:
        decision_entry["conditions"] = []
    if "assumptions_applied" not in decision_entry:
        decision_entry["assumptions_applied"] = []

    envelope_data["decisions_made"].append(decision_entry)
    logger.debug(
        "Added decision %s to envelope for step %s",
        decision_entry.get("decision_id"),
        envelope_data.get("step_id"),
    )
    return envelope_data


def update_assumption_status(
    envelope_data: Dict[str, Any],
    assumption_id: str,
    new_status: str,
    resolution_note: Optional[str] = None,
) -> bool:
    """Update the status of an assumption in the envelope.

    Args:
        envelope_data: The envelope dictionary to modify.
        assumption_id: The ID of the assumption to update.
        new_status: New status ("active", "resolved", or "invalidated").
        resolution_note: Optional explanation for the status change.

    Returns:
        True if the assumption was found and updated, False otherwise.
    """
    assumptions = envelope_data.get("assumptions_made", [])
    for assumption in assumptions:
        if assumption.get("assumption_id") == assumption_id:
            assumption["status"] = new_status
            if resolution_note:
                assumption["resolution_note"] = resolution_note
            logger.debug(
                "Updated assumption %s status to %s",
                assumption_id,
                new_status,
            )
            return True

    logger.warning("Assumption %s not found in envelope", assumption_id)
    return False


def get_active_assumptions(envelope_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Get all active assumptions from an envelope.

    Args:
        envelope_data: The envelope dictionary to query.

    Returns:
        List of assumption entries with status "active".
    """
    assumptions = envelope_data.get("assumptions_made", [])
    return [a for a in assumptions if a.get("status") == "active"]


def get_decisions_by_type(
    envelope_data: Dict[str, Any],
    decision_type: str,
) -> List[Dict[str, Any]]:
    """Get all decisions of a specific type from an envelope.

    Args:
        envelope_data: The envelope dictionary to query.
        decision_type: The type of decisions to retrieve.

    Returns:
        List of decision entries matching the type.
    """
    decisions = envelope_data.get("decisions_made", [])
    return [d for d in decisions if d.get("decision_type") == decision_type]
