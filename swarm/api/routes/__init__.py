"""
Routes package for Flow Studio API.

This package contains the FastAPI routers for:
- specs: Template and flow graph endpoints
- runs: Run control endpoints (start, pause, resume, inject, interrupt, cancel)
- events: SSE event streaming for runs
- wisdom: Wisdom artifact reading and patch application
- compile: Compile preview endpoints for prompt inspection
- facts: Inventory marker extraction and summary endpoints
- evolution: Evolution patch parsing and application endpoints
- boundary: Boundary review aggregation endpoints
- db: Database health, rebuild, and statistics endpoints
- settings: Model policy and user preferences endpoints
- preview: Preview endpoints for configuration changes
"""

from .boundary import router as boundary_router
from .compile import router as compile_router
from .db import router as db_router
from .events import router as events_router
from .evolution import router as evolution_router
from .facts import router as facts_router
from .preview import router as preview_router
from .runs import router as runs_router
from .settings import router as settings_router
from .specs import router as specs_router
from .wisdom import router as wisdom_router

__all__ = [
    "specs_router",
    "runs_router",
    "events_router",
    "wisdom_router",
    "compile_router",
    "facts_router",
    "evolution_router",
    "boundary_router",
    "db_router",
    "settings_router",
    "preview_router",
]
