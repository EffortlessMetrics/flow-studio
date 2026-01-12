"""
swarm.runtime.stepwise - Modular stepwise orchestration package.

This package provides a modularized implementation of stepwise flow execution.
The package is organized into focused modules:

Package Structure:
    orchestrator.py  - StepwiseOrchestrator coordinator
    models.py        - FlowStepwiseSummary, FlowExecutionResult, ResolvedNode
    types.py         - StepTxnInput/Output, VerificationResult
    routing/         - Routing subsystem (unified driver + legacy support)
    graph_bridge.py  - FlowDefinition -> FlowGraph conversion
    node_resolver.py - Node resolution (regular + injected nodes)
    envelope.py      - Envelope invariant enforcement
    receipt_compat.py - Receipt read/update helpers
    spec_facade.py   - FlowSpec/StationSpec caching
    parallel.py      - Fork/join parallel execution

Usage:
    from swarm.runtime.stepwise import StepwiseOrchestrator, get_orchestrator
    from swarm.runtime.backends import GeminiCliBackend

    backend = GeminiCliBackend()
    engine = GeminiStepEngine(backend)
    orchestrator = StepwiseOrchestrator(engine)
    run_id = orchestrator.run_stepwise_flow("build", spec)

Backwards Compatibility:
    GeminiStepOrchestrator is an alias for StepwiseOrchestrator.
"""

# =============================================================================
# Public API: Orchestrator
# =============================================================================
from .orchestrator import StepwiseOrchestrator, get_orchestrator

# Backwards compatibility alias
GeminiStepOrchestrator = StepwiseOrchestrator

# =============================================================================
# Public API: Types and Models
# =============================================================================
from .types import (
    StepTxnInput,
    StepTxnOutput,
    VerificationCheck,
    VerificationResult,
)
from .models import (
    FlowExecutionResult,
    FlowStepwiseSummary,
    ResolvedNode,
    # Note: RoutingOutcome is now imported from .routing (driver.py version)
)

# =============================================================================
# Public API: Spec Loading
# =============================================================================
from .spec_facade import SpecFacade, load_flow_spec, load_station_spec

# =============================================================================
# Internal helpers (re-exported for backwards compatibility)
# Keep imports minimal - most code should use routing/ subpackage directly
# =============================================================================
from .envelope import ensure_step_envelope
from .graph_bridge import build_flow_graph_from_definition
from .node_resolver import find_step_index, get_next_node_id, resolve_node
from .receipt_compat import read_receipt_field, update_receipt_routing

# Routing re-exports
# Note: There are TWO route_step functions with different signatures:
# 1. route_step_legacy (from _routing_legacy.py) - Legacy signature for receipt-based routing
#    Signature: (flow_def, current_step, result, loop_state, run_id, flow_key, ...) -> (next_step_id, reason)
# 2. route_step (from routing/driver.py) - New unified driver signature
#    Signature: (*, step, step_result, run_state, loop_state, iteration, routing_mode, ...) -> RoutingOutcome
#
# For backwards compatibility, this package exports route_step_legacy as route_step.
# New code should import from swarm.runtime.stepwise.routing for the driver version.
from .routing import (
    # Re-export legacy route_step for backwards compatibility
    route_step_legacy as route_step,  # Legacy signature - for existing code
    # Driver's RoutingOutcome type
    RoutingOutcome,  # From driver.py - use with driver's route_step
    # Legacy routing signal creation
    create_routing_signal,
    # Elephant Protocol
    ProgressDelta,
    ProgressEvidence,
    StallAnalysis,
    detect_stall,
    record_progress_evidence,
    create_stall_routing_signal,
    compute_error_signature,
    # Candidate-set pattern
    generate_routing_candidates,
)

__all__ = [
    # === Orchestrator (primary API) ===
    "StepwiseOrchestrator",
    "GeminiStepOrchestrator",
    "get_orchestrator",
    # === Types and Models ===
    "StepTxnInput",
    "StepTxnOutput",
    "VerificationResult",
    "VerificationCheck",
    "FlowExecutionResult",
    "FlowStepwiseSummary",
    "ResolvedNode",
    "RoutingOutcome",
    # === Spec Loading ===
    "SpecFacade",
    "load_flow_spec",
    "load_station_spec",
    # === Internal Helpers (backwards compat) ===
    "ensure_step_envelope",
    "build_flow_graph_from_definition",
    "find_step_index",
    "get_next_node_id",
    "resolve_node",
    "read_receipt_field",
    "update_receipt_routing",
    # === Routing (prefer swarm.runtime.stepwise.routing) ===
    "create_routing_signal",
    "route_step",
    "ProgressDelta",
    "ProgressEvidence",
    "StallAnalysis",
    "detect_stall",
    "record_progress_evidence",
    "create_stall_routing_signal",
    "compute_error_signature",
    "generate_routing_candidates",
]
