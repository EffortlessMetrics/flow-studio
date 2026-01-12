"""ID types and generators for the types package.

Provides run and event ID generation, plus type aliases.
"""

from __future__ import annotations

import secrets
import string
from datetime import datetime, timezone
from typing import Literal

# Type aliases
RunId = str
BackendId = Literal[
    "claude-harness",
    "claude-agent-sdk",
    "claude-step-orchestrator",
    "gemini-cli",
    "gemini-step-orchestrator",
    "custom-cli",
]


# Event ID generation: prefer ulid for time-ordered IDs, fall back to uuid4
try:
    import ulid

    def _generate_event_id() -> str:
        """Generate a globally unique event ID using ULID."""
        return str(ulid.new())
except ImportError:
    import uuid

    def _generate_event_id() -> str:
        """Generate a globally unique event ID using UUID4."""
        return str(uuid.uuid4())


def generate_run_id() -> RunId:
    """Generate a unique run ID.

    Creates IDs in the format: run-YYYYMMDD-HHMMSS-xxxxxx
    where xxxxxx is a random 6-character alphanumeric suffix.

    Returns:
        A unique run identifier string.

    Example:
        >>> run_id = generate_run_id()
        >>> run_id  # e.g., "run-20251208-143022-abc123"
    """
    now = datetime.now(timezone.utc)
    timestamp = now.strftime("%Y%m%d-%H%M%S")
    suffix = "".join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(6))
    return f"run-{timestamp}-{suffix}"
