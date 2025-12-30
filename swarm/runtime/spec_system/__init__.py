"""
swarm/runtime/spec_system - Canonical JSON spec system for runtime truth.

This module provides:
- canonical_json(): Deterministic JSON serialization (sorted keys, tight separators)
- spec_hash(): SHA256 hash of spec data for ETags and content addressing
- SpecBridge: Bridge between JSON FlowGraph specs and runtime FlowDefinition

Usage:
    from swarm.runtime.spec_system.canonical import canonical_json, spec_hash
    from swarm.runtime.spec_system.bridge import SpecBridge, get_spec_bridge

    # Serialize deterministically
    json_str = canonical_json({"b": 1, "a": 2})  # '{"a":2,"b":1}'

    # Get content hash (first 12 chars of SHA256)
    hash_id = spec_hash(data)  # e.g., "a1b2c3d4e5f6"

    # Load flow from JSON specs
    bridge = get_spec_bridge()
    flow_def = bridge.get_flow("signal")
"""

from .bridge import SpecBridge, get_spec_bridge
from .canonical import canonical_json, spec_hash

__all__ = ["canonical_json", "spec_hash", "SpecBridge", "get_spec_bridge"]
