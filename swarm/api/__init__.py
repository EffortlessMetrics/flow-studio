"""
Flow Studio API - FastAPI REST API for SpecManager functionality.

This module exposes the spec system (flows, templates, validation, compilation)
to the TypeScript frontend via a FastAPI REST API.

Note: Although the original design mentioned Flask, the codebase standardizes
on FastAPI. This implementation follows FastAPI patterns for consistency.

New API (v2.0) - Modular Routes:
    Spec Endpoints (from routes/specs.py):
        GET    /api/specs/templates          - List templates (for palette)
        GET    /api/specs/templates/{id}     - Get template
        GET    /api/specs/flows              - List flows
        GET    /api/specs/flows/{id}         - Get merged flow
        PATCH  /api/specs/flows/{id}         - Update flow (requires If-Match)
        POST   /api/specs/flows/{id}/validate - Validate flow spec
        POST   /api/specs/flows/{id}/compile  - Compile flow

    Run Control Endpoints (from routes/runs.py):
        POST   /api/runs                     - Start new run
        GET    /api/runs                     - List runs
        GET    /api/runs/{id}                - Get run state
        POST   /api/runs/{id}/pause          - Pause run
        POST   /api/runs/{id}/resume         - Resume run
        POST   /api/runs/{id}/inject         - Inject node into run
        POST   /api/runs/{id}/interrupt      - Interrupt with detour
        DELETE /api/runs/{id}                - Cancel run

    SSE Event Streaming (from routes/events.py):
        GET    /api/runs/{id}/events         - Stream run events

    Health:
        GET    /api/health                   - Health check

Legacy API (v1.0) - Backward Compatible:
    GET  /api/spec/flows              - List all flows
    GET  /api/spec/flows/<flow_id>    - Get flow graph (with ETag)
    PATCH /api/spec/flows/<flow_id>   - Update flow (JSON Patch, If-Match)
    GET  /api/spec/templates          - List all templates
    GET  /api/spec/templates/<id>     - Get template details
    POST /api/spec/validate           - Dry-run validation
    POST /api/spec/compile            - Preview PromptPlan
    GET  /api/runs                    - List runs
    GET  /api/runs/<run_id>/state     - Get run state
    GET  /api/runs/<run_id>/events    - SSE event stream
"""

from .server import SpecManager, app, create_app, get_spec_manager

# Also expose routers for custom integration
try:
    from .routes import events_router, runs_router, specs_router

    __all__ = [
        "create_app",
        "SpecManager",
        "app",
        "get_spec_manager",
        "specs_router",
        "runs_router",
        "events_router",
    ]
except ImportError:
    __all__ = ["create_app", "SpecManager", "app", "get_spec_manager"]
