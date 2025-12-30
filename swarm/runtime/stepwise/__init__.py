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
    RoutingOutcome,
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

# Legacy routing re-exports - prefer importing from swarm.runtime.stepwise.routing
from .routing import (
    # Core routing
    create_routing_signal,
    route_step,
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
