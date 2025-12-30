"""
Routing subsystem for stepwise orchestration.

This package provides the unified routing logic for stepwise flow execution.
It implements the priority-based routing strategy defined in the routing
protocol:

1. Fast-path: Obvious deterministic cases (single edge, VERIFIED, terminal)
2. Deterministic: CEL/condition evaluation (if DETERMINISTIC_ONLY mode)
3. Navigator: Intelligent routing via Navigator agent (ASSIST/AUTHORITATIVE modes)
4. Envelope fallback: Legacy RoutingSignal from step finalization
5. Escalate: Human intervention required (no valid candidates)

The routing subsystem is designed to be:

- **Bounded**: Only considers edges defined in the flow graph
- **Auditable**: Produces structured explanation for every decision
- **Cheap**: Uses LLM (Navigator) only when truly needed
- **Mode-aware**: Respects RoutingMode (DETERMINISTIC_ONLY, ASSIST, AUTHORITATIVE)

Components:
    driver.py - Main route_step_unified() function that orchestrates routing strategies
    _routing_legacy.py - Legacy routing functions (re-exported for compatibility)

Usage (new unified routing):
    from swarm.runtime.stepwise.routing import route_step_unified, RoutingOutcome

    outcome = route_step_unified(
        step=current_step,
        step_result=result,
        run_state=state,
        loop_state=loops,
        iteration=iter_count,
        routing_mode=RoutingMode.ASSIST,
    )

Usage (legacy - maintained for backwards compatibility):
    from swarm.runtime.stepwise.routing import (
        create_routing_signal,
        generate_routing_candidates,
        build_routing_context,
    )

See Also:
    - swarm/runtime/router.py: Core FlowGraph and edge routing logic
    - swarm/runtime/types.py: RoutingSignal, RoutingMode, and related types
    - docs/ROUTING_PROTOCOL.md: Full routing protocol documentation
"""

from __future__ import annotations

# Re-export everything from legacy routing module for backwards compatibility
# This ensures existing imports like:
#   from .routing import create_routing_signal, build_routing_context
# continue to work unchanged.
from swarm.runtime.stepwise._routing_legacy import (
    # Routing signal creation
    create_routing_signal,
    route_step,  # Legacy route_step function
    build_routing_context,
    ReceiptReader,
    # Elephant Protocol: Stall detection types
    ProgressDelta,
    ProgressEvidence,
    StallAnalysis,
    # Elephant Protocol: Stall detection functions
    detect_stall,
    record_progress_evidence,
    create_stall_routing_signal,
    compute_error_signature,
    # Candidate-set pattern
    generate_routing_candidates,
)

# Re-export from new driver module
# Using route_step_unified to avoid collision with legacy route_step
from swarm.runtime.stepwise.routing.driver import (
    RoutingOutcome,
    route_step as route_step_unified,
)

# Convenience re-exports for RoutingOutcome construction
# These allow: from swarm.runtime.stepwise.routing import RoutingOutcome
# Then: outcome = RoutingOutcome.from_signal(signal, "source")

__all__ = [
    # ==========================================================================
    # Legacy exports (backwards compatibility with existing code)
    # ==========================================================================
    # Routing signal creation
    "create_routing_signal",
    "route_step",  # Legacy function
    "build_routing_context",
    "ReceiptReader",
    # Elephant Protocol: Stall detection types
    "ProgressDelta",
    "ProgressEvidence",
    "StallAnalysis",
    # Elephant Protocol: Stall detection functions
    "detect_stall",
    "record_progress_evidence",
    "create_stall_routing_signal",
    "compute_error_signature",
    # Candidate-set pattern
    "generate_routing_candidates",
    # ==========================================================================
    # New unified routing (driver.py)
    # ==========================================================================
    "RoutingOutcome",
    "route_step_unified",
]
