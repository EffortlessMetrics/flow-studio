"""
Routes package for Flow Studio API.

This package contains the FastAPI routers for:
- specs: Template and flow graph endpoints
- runs: Run control endpoints (start, pause, resume, inject, interrupt, cancel)
- events: SSE event streaming for runs
"""

from .specs import router as specs_router
from .runs import router as runs_router
from .events import router as events_router

__all__ = ["specs_router", "runs_router", "events_router"]
