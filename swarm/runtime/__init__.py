# swarm/runtime package
# Provides runtime abstraction for executing and tracking runs across multiple backends.
#
# Core components:
#   - types: Core dataclasses (RunSpec, RunSummary, RunEvent, BackendCapabilities)
#   - storage: Disk I/O for run metadata and events
#   - backends: Abstract RunBackend + concrete implementations
#   - service: RunService singleton for orchestration
#   - state_builder: RunState rebuilder from events.jsonl (crash recovery)
#
# Usage:
#     from swarm.runtime import RunService
#     service = RunService.get_instance()
#     run_id = service.start_run(spec)
#     summary = service.get_run(run_id)
#
# State recovery:
#     from swarm.runtime import rebuild_run_state, recover_run_state
#     state = recover_run_state(run_id)  # Uses stored state if available
#     state = rebuild_run_state(run_id)  # Always rebuilds from events

from typing import TYPE_CHECKING

from .state_builder import (
    rebuild_run_state,
    recover_run_state,
    verify_run_state,
)
from .storage import (
    RUNS_DIR,
    get_run_path,
    list_runs,
    run_exists,
)
from .types import (
    BackendCapabilities,
    BackendId,
    RunEvent,
    RunId,
    RunSpec,
    RunStatus,
    RunSummary,
    SDLCStatus,
    generate_run_id,
)

# TYPE_CHECKING stubs for static type checkers
# These allow `from swarm.runtime import RunService` to type-check correctly
# while still using lazy imports at runtime to avoid circular dependencies
if TYPE_CHECKING:
    from .service import RunService as RunService
    from .service import get_run_service as get_run_service

__all__ = [
    # Types
    "RunId",
    "BackendId",
    "RunStatus",
    "SDLCStatus",
    "RunSpec",
    "RunSummary",
    "RunEvent",
    "BackendCapabilities",
    "generate_run_id",
    # Storage
    "RUNS_DIR",
    "get_run_path",
    "run_exists",
    "list_runs",
    # State Builder (crash recovery)
    "rebuild_run_state",
    "recover_run_state",
    "verify_run_state",
    # Service (imported lazily at runtime, statically available for type checking)
    "RunService",
    "get_run_service",
]


def __getattr__(name: str):
    """Lazy import for service to avoid circular dependencies."""
    if name == "RunService":
        from .service import RunService

        return RunService
    if name == "get_run_service":
        from .service import get_run_service

        return get_run_service
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
