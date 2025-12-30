"""
receipt_compat.py - Legacy receipt read/update functions.

This module consolidates receipt file handling that was duplicated across
the orchestrator. It provides the single source of truth for:
- Reading fields from receipt JSON files
- Updating receipts with routing decisions

Note: This is "compat" because the long-term direction is HandoffEnvelope
based routing, not receipt-field extraction. But config-based routing
still needs this for the microloop condition_field pattern.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Optional

if TYPE_CHECKING:
    from swarm.runtime.engines.models import RoutingContext

logger = logging.getLogger(__name__)


def read_receipt_field(
    repo_root: Path,
    run_id: str,
    flow_key: str,
    step_id: str,
    agent_key: str,
    field_name: str,
) -> Optional[str]:
    """Read a specific field from a receipt file.

    This is the canonical implementation for reading receipt fields.
    The orchestrator's _read_receipt_field methods should delegate here.

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


def update_receipt_routing(
    repo_root: Path,
    run_id: str,
    flow_key: str,
    step_id: str,
    agent_key: str,
    routing_ctx: "RoutingContext",
) -> bool:
    """Update receipt with final routing decision.

    Adds a "routing" block to the receipt JSON containing:
    - loop_iteration: Current iteration count
    - max_iterations: Max allowed iterations
    - decision: The routing decision made (loop, advance, terminate)
    - reason: Human-readable reason

    Args:
        repo_root: Repository root path.
        run_id: The run identifier.
        flow_key: The flow key.
        step_id: The step identifier.
        agent_key: The agent key.
        routing_ctx: The routing context with decision info.

    Returns:
        True if update succeeded, False otherwise.
    """
    run_base = repo_root / "swarm" / "runs" / run_id / flow_key
    receipt_path = run_base / "receipts" / f"{step_id}-{agent_key}.json"

    if not receipt_path.exists():
        logger.debug("Receipt not found for routing update: %s", receipt_path)
        return False

    try:
        with receipt_path.open("r", encoding="utf-8") as f:
            receipt = json.load(f)

        receipt["routing"] = {
            "loop_iteration": routing_ctx.loop_iteration,
            "max_iterations": routing_ctx.max_iterations,
            "decision": routing_ctx.decision,
            "reason": routing_ctx.reason,
        }

        with receipt_path.open("w", encoding="utf-8") as f:
            json.dump(receipt, f, indent=2)

        return True

    except (json.JSONDecodeError, IOError) as e:
        logger.warning("Failed to update receipt routing: %s", e)
        return False


def read_receipt(
    repo_root: Path,
    run_id: str,
    flow_key: str,
    step_id: str,
    agent_key: str,
) -> Optional[Dict[str, Any]]:
    """Read entire receipt as a dict.

    Args:
        repo_root: Repository root path.
        run_id: The run identifier.
        flow_key: The flow key.
        step_id: The step identifier.
        agent_key: The agent key.

    Returns:
        Receipt dict if found and valid, None otherwise.
    """
    run_base = repo_root / "swarm" / "runs" / run_id / flow_key
    receipt_path = run_base / "receipts" / f"{step_id}-{agent_key}.json"

    if not receipt_path.exists():
        return None

    try:
        with receipt_path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        logger.warning("Failed to read receipt %s: %s", receipt_path, e)
        return None


__all__ = [
    "read_receipt_field",
    "update_receipt_routing",
    "read_receipt",
]
