"""Time utilities for the types package.

Provides datetime serialization helpers used by all serdes functions.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional


def _datetime_to_iso(dt: Optional[datetime]) -> Optional[str]:
    """Convert datetime to ISO format string with Z suffix."""
    if dt is None:
        return None
    return dt.isoformat() + "Z" if not dt.isoformat().endswith("Z") else dt.isoformat()


def _iso_to_datetime(iso_str: Optional[str]) -> Optional[datetime]:
    """Parse ISO format string to datetime."""
    if iso_str is None:
        return None
    # Remove Z suffix if present for parsing
    if iso_str.endswith("Z"):
        iso_str = iso_str[:-1]
    return datetime.fromisoformat(iso_str)
