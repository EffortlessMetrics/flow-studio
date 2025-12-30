"""Backwards compatibility shim - moved to swarm.runtime.stepwise.

This module re-exports from the modular stepwise package for backwards
compatibility. All new code should import directly from:

    from swarm.runtime.stepwise import (
        StepwiseOrchestrator,
        GeminiStepOrchestrator,
        get_orchestrator,
    )

The stepwise package provides a modularized implementation with:
- types.py: StepTxnInput/Output, VerificationResult
- receipt_compat.py: Legacy receipt read/update
- spec_facade.py: FlowSpec/StationSpec caching
- routing.py: Fallback routing logic
- orchestrator.py: Thin coordinator
"""

from swarm.runtime.stepwise import (
    GeminiStepOrchestrator,
    StepwiseOrchestrator,
    get_orchestrator,
)

__all__ = [
    "StepwiseOrchestrator",
    "GeminiStepOrchestrator",
    "get_orchestrator",
]
