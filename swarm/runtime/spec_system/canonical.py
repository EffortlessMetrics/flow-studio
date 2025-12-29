"""
canonical.py - Canonical JSON utilities for deterministic spec serialization.

This module provides the foundation for JSON-only runtime truth:
- Deterministic serialization (sorted keys, tight separators)
- Content-addressed hashing for ETags and deduplication
- No external dependencies beyond stdlib

The canonical format ensures:
1. Same logical data always produces identical bytes
2. Hashes are stable across Python versions and platforms
3. Diffs are meaningful (sorted keys make changes easy to spot)

Usage:
    from swarm.runtime.spec_system.canonical import canonical_json, spec_hash

    data = {"z": 1, "a": 2, "nested": {"b": 3, "a": 4}}
    json_str = canonical_json(data)
    # '{"a":2,"nested":{"a":4,"b":3},"z":1}'

    hash_id = spec_hash(data)
    # First 12 chars of SHA256: e.g., "a1b2c3d4e5f6"
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Union


def canonical_json(obj: Any, *, indent: int | None = None) -> str:
    """Serialize object to canonical JSON.

    Produces deterministic JSON output:
    - Keys sorted alphabetically (recursive)
    - Tight separators (no extra whitespace) when indent=None
    - UTF-8 characters preserved (ensure_ascii=False)
    - No trailing whitespace

    Args:
        obj: Any JSON-serializable Python object.
        indent: Optional indentation level. None for compact output.
                Use 2 for human-readable output.

    Returns:
        Canonical JSON string.

    Raises:
        TypeError: If obj contains non-serializable values.

    Examples:
        >>> canonical_json({"b": 1, "a": 2})
        '{"a":2,"b":1}'

        >>> canonical_json({"name": "test", "items": [3, 1, 2]})
        '{"items":[3,1,2],"name":"test"}'

        >>> canonical_json({"a": 1}, indent=2)
        '{\\n  "a": 1\\n}'
    """
    if indent is not None:
        separators = (",", ": ")
    else:
        separators = (",", ":")

    return json.dumps(
        obj,
        sort_keys=True,
        separators=separators,
        ensure_ascii=False,
        indent=indent,
        allow_nan=False,  # Strict JSON: no NaN/Infinity
    )


def spec_hash(obj: Any, *, length: int = 12) -> str:
    """Compute short SHA256 hash of spec data.

    The hash is computed from the canonical JSON representation,
    ensuring identical logical data produces identical hashes.

    Args:
        obj: Any JSON-serializable Python object.
        length: Number of hex characters to return (default 12).
                Use 64 for full SHA256 hash.

    Returns:
        Hex string of first `length` characters of SHA256 hash.

    Raises:
        TypeError: If obj contains non-serializable values.
        ValueError: If length < 1 or length > 64.

    Examples:
        >>> spec_hash({"a": 1})
        'b39916b17fd8'  # First 12 chars of SHA256

        >>> spec_hash({"a": 1}, length=8)
        'b39916b1'

        >>> spec_hash({"a": 1, "b": 2}) == spec_hash({"b": 2, "a": 1})
        True  # Order doesn't matter - canonical form is sorted
    """
    if length < 1 or length > 64:
        raise ValueError(f"length must be between 1 and 64, got {length}")

    # Get canonical JSON bytes
    canonical = canonical_json(obj)
    data = canonical.encode("utf-8")

    # Compute SHA256
    hash_bytes = hashlib.sha256(data).hexdigest()

    return hash_bytes[:length]


def canonical_json_bytes(obj: Any) -> bytes:
    """Serialize object to canonical JSON bytes.

    Convenience function for when bytes are needed directly
    (e.g., for hashing, network transmission).

    Args:
        obj: Any JSON-serializable Python object.

    Returns:
        UTF-8 encoded canonical JSON bytes.
    """
    return canonical_json(obj).encode("utf-8")


def normalize_for_hash(obj: Any) -> Any:
    """Normalize object for consistent hashing.

    Handles edge cases that could cause hash instability:
    - Converts sets to sorted lists
    - Rounds floats to avoid precision issues
    - Strips None values from dicts (optional fields)

    Note: This is a deep copy operation.

    Args:
        obj: Object to normalize.

    Returns:
        Normalized copy of the object.
    """
    if isinstance(obj, dict):
        return {
            k: normalize_for_hash(v)
            for k, v in sorted(obj.items())
            if v is not None
        }
    elif isinstance(obj, (list, tuple)):
        return [normalize_for_hash(item) for item in obj]
    elif isinstance(obj, set):
        return sorted(normalize_for_hash(item) for item in obj)
    elif isinstance(obj, float):
        # Round to 10 decimal places to avoid precision issues
        return round(obj, 10)
    else:
        return obj


def verify_canonical(json_str: str) -> bool:
    """Verify that a JSON string is in canonical form.

    Parses the JSON and re-serializes canonically to check
    if the output matches the input.

    Args:
        json_str: JSON string to verify.

    Returns:
        True if the string is already canonical, False otherwise.

    Examples:
        >>> verify_canonical('{"a":1,"b":2}')
        True

        >>> verify_canonical('{ "b": 2, "a": 1 }')
        False
    """
    try:
        obj = json.loads(json_str)
        return canonical_json(obj) == json_str
    except json.JSONDecodeError:
        return False


def canonicalize_file(input_path: str, output_path: str | None = None) -> str:
    """Read a JSON file and write it back in canonical form.

    Useful for normalizing existing JSON files.

    Args:
        input_path: Path to input JSON file.
        output_path: Path to output file. If None, overwrites input.

    Returns:
        The canonical JSON string that was written.

    Raises:
        FileNotFoundError: If input file doesn't exist.
        json.JSONDecodeError: If input is not valid JSON.
    """
    import os

    with open(input_path, "r", encoding="utf-8") as f:
        obj = json.load(f)

    canonical = canonical_json(obj, indent=2) + "\n"

    target = output_path or input_path
    with open(target, "w", encoding="utf-8") as f:
        f.write(canonical)

    return canonical
