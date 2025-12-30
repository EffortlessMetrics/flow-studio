#!/usr/bin/env python3
"""
Flow Studio - FastAPI Implementation

This module provides a FastAPI web server for Flow Studio that mirrors
the Flask implementation. It uses the same FlowStudioCore backend for
consistency.

Usage (from repo root):

    uv run uvicorn swarm.tools.flow_studio_fastapi:app --reload --port 5000

Then open:

    http://localhost:5000/

Dependencies:
  - fastapi
  - uvicorn
  - PyYAML

Install via:

    uv add fastapi uvicorn pyyaml
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

try:
    from swarm.flowstudio.core import FlowStudioCore
except ImportError:
    FlowStudioCore = None  # Fallback

try:
    from swarm.config.profile_registry import (
        CurrentProfileInfo,
        get_current_profile,
        list_profiles,
    )
except ImportError:
    get_current_profile = None
    list_profiles = None
    CurrentProfileInfo = None

try:
    from swarm.flowstudio import schema
except ImportError:
    schema = None  # Fallback

from swarm.tools.flow_studio_ui import get_index_html

try:
    from swarm.tools.run_inspector import RunInspector
except ImportError:
    RunInspector = None  # Fallback

try:
    from swarm.tools.flow_studio_validation import get_validation_data
except ImportError:
    get_validation_data = None  # Fallback

try:
    from swarm.runtime.service import RunService, get_run_service
    from swarm.runtime.types import RunSpec, RunStatus, SDLCStatus
except ImportError:
    RunService = None
    get_run_service = None
    RunSpec = None
    RunStatus = None
    SDLCStatus = None

# Module logger - defined after all imports to avoid E402
logger = logging.getLogger(__name__)

# Strict UI asset checking: set to "1" for CI or when you want hard failures
# on missing compiled JS. In dev mode (default), missing files log warnings.
STRICT_UI_ASSETS = os.getenv("FLOW_STUDIO_STRICT_UI_ASSETS", "0") == "1"


def _check_ui_assets(ui_dir: Path) -> None:
    """
    Check for required compiled JS files at startup.

    This check is drift-proof: instead of a hardcoded list of all modules,
    we require only entrypoints (main.js, flow-studio-app.js) and walk the
    full import graph (BFS) to detect missing dependencies automatically.

    Supported import patterns:
      - Static: import ... from "./x.js" or "../x.js"
      - Side-effect: import "./x.js" or "../x.js"
      - Dynamic: import("./x.js") or import("../x.js")

    The graph walk catches transitive dependencies, e.g.:
      - flow-studio-app.js imports ./runs_flows.js (exists)
      - runs_flows.js imports ../utils/foo.js (missing)
      - This check will catch utils/foo.js as missing

    Path traversal protection: imports that escape the js/ directory are
    flagged as errors (e.g., importing "../../secrets.js").

    Args:
        ui_dir: Path to the flow_studio_ui directory

    Raises:
        RuntimeError: If FLOW_STUDIO_STRICT_UI_ASSETS=1 and files are missing

    Note:
        STRICT_UI_ASSETS is evaluated at module import time, not at call time.
        Changing the env var after import won't affect behavior without reload.
    """
    js_dir = ui_dir / "js"

    if not js_dir.exists():
        msg = f"Flow Studio JS directory not found: {js_dir}. Run `make ts-build`."
        if STRICT_UI_ASSETS:
            logger.error(msg)
            raise RuntimeError(msg)
        logger.warning(msg)
        return

    # Only require entrypoints - everything else is derived from imports
    entrypoints = ["main.js", "flow-studio-app.js"]
    missing_entrypoints = [f for f in entrypoints if not (js_dir / f).exists()]

    if missing_entrypoints:
        msg = f"Missing Flow Studio entrypoints: {', '.join(missing_entrypoints)}. Run `make ts-build`."
        if STRICT_UI_ASSETS:
            logger.error(msg)
            raise RuntimeError(msg)
        logger.warning(msg)
        return

    # Parse ESM imports to walk the full module graph
    # This catches transitive dependencies, not just first-hop imports
    import re
    from collections import deque

    # Match relative imports: ./x.js or ../x.js
    # Anchored to start-of-line (with optional whitespace) to avoid matching inside comments
    # Covers both import and export ... from "..." patterns
    import_export_from_re = re.compile(
        r'^\s*(?:import|export)\b.*?\bfrom\s*["\'](\.\.?/[^"\']+)["\']',
        re.MULTILINE,
    )
    side_effect_re = re.compile(r'^\s*import\s*["\'](\.\.?/[^"\']+)["\']', re.MULTILINE)
    # Dynamic imports can appear anywhere (not anchored)
    dynamic_re = re.compile(r'\bimport\(\s*["\'](\.\.?/[^"\']+)["\']\s*\)')

    def parse_imports(text: str) -> set[str]:
        return (
            set(import_export_from_re.findall(text))
            | set(side_effect_re.findall(text))
            | set(dynamic_re.findall(text))
        )

    # Walk the import graph (BFS via deque)
    js_root = js_dir.resolve()
    queue: deque[Path] = deque(Path(ep) for ep in entrypoints)
    seen: set[str] = {ep for ep in entrypoints}
    missing: list[str] = []

    while queue:
        rel = queue.popleft()
        path = js_dir / rel
        if not path.exists():
            missing.append(rel.as_posix())
            continue

        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            logger.warning("Failed to read %s: %s", rel, e)
            continue

        for spec in parse_imports(text):
            # Resolve relative to the importing file's directory.
            # strict=False lets us detect missing files without raising,
            # and still detect path traversal (imports escaping js/) on nonexistent targets.
            dep_abs = (path.parent / spec).resolve(strict=False)

            # Reject imports that escape js_dir (path traversal protection)
            try:
                dep_rel = dep_abs.relative_to(js_root).as_posix()
            except ValueError:
                # Import escapes js_dir - record as missing with context
                missing.append(f"{rel} -> {spec} (escapes js/)")
                continue

            if dep_rel not in seen:
                seen.add(dep_rel)
                queue.append(Path(dep_rel))

    if missing:
        msg = (
            "Missing compiled Flow Studio module dependencies: "
            + ", ".join(sorted(set(missing)))
            + ". Run `make ts-build`."
        )
        if STRICT_UI_ASSETS:
            logger.error(msg)
            raise RuntimeError(msg)
        logger.warning(msg)


def create_fastapi_app() -> FastAPI:
    """Create and configure the FastAPI application."""

    app = FastAPI(
        title="Flow Studio API",
        description="Interactive visualization of swarm flows, steps, agents, and artifacts",
        version="2.0.0",
    )

    # Add CORS middleware to allow all origins (adjust as needed for production)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Repository root for path resolution
    REPO_ROOT = Path(__file__).resolve().parents[2]

    # Initialize core
    try:
        _core = FlowStudioCore()
        _core.reload()
    except Exception:
        _core = None

    # Initialize run inspector
    _run_inspector: Optional[Any] = None
    if RunInspector is not None:
        try:
            _run_inspector = RunInspector(repo_root=REPO_ROOT)
        except Exception:
            _run_inspector = None

    # Initialize validation data
    _validation_data: Optional[Dict[str, Any]] = None
    if get_validation_data is not None:
        try:
            _validation_data = get_validation_data()
        except Exception:
            _validation_data = None

    # Initialize RunService
    _run_service: Optional[Any] = None
    if RunService is not None:
        try:
            _run_service = RunService.get_instance(REPO_ROOT)
        except Exception:
            _run_service = None

    # Local caches for flows, agents, and tours (similar to Flask globals)
    _flows_cache: Dict[str, Any] = {}
    _agents_cache: Dict[str, Any] = {}
    _tours_cache: Dict[str, Any] = {}

    def _load_tours() -> Dict[str, Any]:
        """Load tours from swarm/config/tours/*.yaml"""
        import yaml

        tours: Dict[str, Any] = {}
        tours_dir = REPO_ROOT / "swarm" / "config" / "tours"

        if not tours_dir.exists():
            return tours

        for cfg_path in sorted(tours_dir.glob("*.yaml")):
            try:
                text = cfg_path.read_text(encoding="utf-8")
                data = yaml.safe_load(text)
                if data is None or not isinstance(data, dict):
                    continue
                tour_id = data.get("id")
                if not tour_id:
                    continue

                tour_steps = []
                for raw_step in data.get("steps") or []:
                    if not isinstance(raw_step, dict):
                        continue
                    target = raw_step.get("target") or {}
                    tour_steps.append({
                        "target_type": target.get("type", "flow"),
                        "target_flow": target.get("flow", ""),
                        "target_step": target.get("step", ""),
                        "title": raw_step.get("title", ""),
                        "text": raw_step.get("text", ""),
                        "action": raw_step.get("action", "select_flow"),
                    })

                tours[tour_id] = {
                    "id": tour_id,
                    "title": data.get("title", tour_id),
                    "description": (data.get("description") or "").strip(),
                    "steps": tour_steps,
                }
            except Exception:
                continue

        return tours

    def _reload_from_disk() -> tuple:
        """Reload all data from disk."""
        nonlocal _flows_cache, _agents_cache, _tours_cache

        if _core:
            _agents_cache, _flows_cache = _core.reload()
        _tours_cache = _load_tours()
        return _agents_cache, _flows_cache

    # Initial load
    _reload_from_disk()

    # =========================================================================
    # Public Routes
    # =========================================================================

    @app.get("/", response_class=HTMLResponse)
    async def index():
        """Serve the Flow Studio HTML interface."""
        return get_index_html()

    @app.get("/api/health", response_model=schema.HealthStatus if schema else None)
    async def api_health():
        """Health check endpoint."""
        import datetime

        if _core:
            flows = _core.list_flows()
            agents_count = len(_core._agents_cache) if _core._agents_cache else 0
        else:
            flows = []
            agents_count = 0

        # Get selftest status if available
        selftest_status = None
        try:
            if _core:
                status = _core.get_validation_snapshot()
                if hasattr(status, "selftest_summary"):
                    selftest_status = status.selftest_summary
        except Exception:
            pass  # Graceful degradation

        return {
            "status": "ok",
            "version": "2.0.0",
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "flows": len(flows),
            "agents": agents_count,
            "selftest_status": selftest_status,
            "capabilities": {
                "runs": _run_inspector is not None,
                "timeline": _run_inspector is not None,
                "governance": _core is not None,
                "validation": _validation_data is not None,
            }
        }

    # =========================================================================
    # Profile Endpoint
    # =========================================================================

    @app.get("/api/profile")
    async def api_current_profile():
        """Get the currently loaded swarm profile."""
        if get_current_profile is None:
            return JSONResponse(
                {"error": "Profile registry not available", "profile": None},
                status_code=503
            )

        try:
            current = get_current_profile()
            if current is None:
                return {
                    "profile": None,
                    "message": "No profile currently loaded. Use 'make profile-load' to apply a profile."
                }

            return {
                "profile": {
                    "id": current.id,
                    "label": current.label,
                    "loaded_at": current.loaded_at,
                    "source_branch": current.source_branch,
                }
            }
        except Exception as e:
            return JSONResponse(
                {"error": f"Failed to get current profile: {str(e)}", "profile": None},
                status_code=500
            )

    @app.get("/api/profiles")
    async def api_list_profiles():
        """List all available swarm profiles."""
        if list_profiles is None:
            return JSONResponse(
                {"error": "Profile registry not available", "profiles": []},
                status_code=503
            )

        try:
            profiles = list_profiles()
            return {
                "profiles": [
                    {
                        "id": p.id,
                        "label": p.label,
                        "description": p.description,
                    }
                    for p in profiles
                ]
            }
        except Exception as e:
            return JSONResponse(
                {"error": f"Failed to list profiles: {str(e)}", "profiles": []},
                status_code=500
            )

    # =========================================================================
    # Model Policy Endpoints
    # =========================================================================

    @app.get("/api/model-policy/preview", response_model=schema.ModelPolicyPreviewResponse if schema else None)
    async def api_model_policy_preview(
        category: str = Query(..., description="Station category (e.g., implementation, critic, shaping)"),
        model: str = Query("inherit", description="Model value to resolve (inherit, haiku, sonnet, opus)")
    ):
        """Preview model resolution for a given category and model value.

        Shows the effective model that would be used for a station with the given
        category and model specification, along with the resolution chain explaining
        how the final model was determined.

        Resolution chain steps:
        - "inherit -> category": Model was 'inherit', looked up category default
        - "category -> group": Category mapped to tier group via policy
        - "group -> tier": Tier group resolved to final tier alias
        - "primary -> user": Primary tier resolved to user's configured model
        """
        try:
            from swarm.config.model_registry import (
                load_model_policy,
                resolve_station_model,
                resolve_model_tier,
                VALID_TIERS,
            )

            policy = load_model_policy()
            resolution_chain: list[str] = []
            model_lower = model.lower()

            # Track resolution steps
            if model_lower == "inherit":
                resolution_chain.append(f"inherit -> category '{category}'")
                # Look up the category's tier assignment
                tier_name = policy.group_assignments.get(category.lower())
                if tier_name:
                    resolution_chain.append(f"category -> tier group '{tier_name}'")
                    # Resolve tier name to alias
                    tier_def = policy.tiers.get(tier_name, tier_name)
                    if tier_def == "inherit_user_primary":
                        resolution_chain.append(f"group '{tier_name}' -> user primary '{policy.user_primary}'")
                    elif tier_def in VALID_TIERS:
                        resolution_chain.append(f"group '{tier_name}' -> tier '{tier_def}'")
                    else:
                        resolution_chain.append(f"group '{tier_name}' -> fallback 'sonnet'")
                else:
                    resolution_chain.append(f"category '{category}' -> fallback 'sonnet'")
            elif model_lower in VALID_TIERS:
                resolution_chain.append(f"explicit tier '{model_lower}'")
            else:
                resolution_chain.append(f"explicit model ID '{model}'")

            # Get the actual resolved values
            effective_tier = resolve_station_model(model, category, return_tier_alias=True)
            effective_model_id = resolve_model_tier(effective_tier)

            return {
                "requested": {
                    "category": category,
                    "model": model,
                },
                "effective": {
                    "tier": effective_tier,
                    "model_id": effective_model_id,
                },
                "resolution_chain": resolution_chain,
            }

        except ValueError as e:
            return JSONResponse(
                {"error": str(e)},
                status_code=400
            )
        except ImportError:
            return JSONResponse(
                {"error": "Model registry not available"},
                status_code=503
            )
        except Exception as e:
            return JSONResponse(
                {"error": f"Failed to preview model policy: {str(e)}"},
                status_code=500
            )

    @app.get("/api/model-policy/matrix", response_model=schema.ModelPolicyMatrixResponse if schema else None)
    async def api_model_policy_matrix():
        """Get the complete model policy matrix showing effective models per station category.

        Returns the user's primary model preference, tier definitions, and the
        resolved model assignments for all station categories. This provides
        a complete view of how models are allocated across the swarm.
        """
        try:
            from swarm.config.model_registry import (
                load_model_policy,
                resolve_tier_alias,
                resolve_model_tier,
            )

            policy = load_model_policy()

            # Build resolved tier definitions
            resolved_tiers: dict[str, str] = {}
            for tier_name, tier_def in policy.tiers.items():
                if tier_def == "inherit_user_primary":
                    resolved_tiers[tier_name] = policy.user_primary
                else:
                    resolved_tiers[tier_name] = tier_def

            # Build category assignments
            assignments: dict[str, dict[str, str]] = {}
            for category, tier_name in policy.group_assignments.items():
                tier_alias = resolve_tier_alias(tier_name, policy)
                model_id = resolve_model_tier(tier_alias)
                assignments[category] = {
                    "tier_name": tier_name,
                    "tier_alias": tier_alias,
                    "model_id": model_id,
                }

            return {
                "user_primary": policy.user_primary,
                "tiers": resolved_tiers,
                "assignments": assignments,
            }

        except ImportError:
            return JSONResponse(
                {"error": "Model registry not available"},
                status_code=503
            )
        except Exception as e:
            return JSONResponse(
                {"error": f"Failed to get model policy matrix: {str(e)}"},
                status_code=500
            )

    @app.get("/api/flows", response_model=schema.FlowsListResponse if schema else None)
    async def api_flows():
        """List all flows."""
        if not _core:
            return {"flows": []}

        flows = _core.list_flows()
        return {
            "flows": [
                {
                    "key": f.key,
                    "title": f.title,
                    "description": f.description,
                    "step_count": f.step_count,
                }
                for f in flows
            ]
        }

    @app.get("/api/graph/{flow_key}", response_model=schema.GraphPayload if schema else None)
    async def api_graph(flow_key: str):
        """Get the graph (nodes and edges) for a flow."""
        if not _core:
            return JSONResponse(
                {"error": "Flow Studio core not available"},
                status_code=503
            )

        try:
            graph = _core.get_flow_graph(flow_key)
            return graph.to_dict()
        except KeyError:
            available = sorted([f.key for f in _core.list_flows()]) if _core else []
            return JSONResponse(
                {
                    "error": f"Flow '{flow_key}' not found",
                    "available_flows": available,
                    "hint": f"Available flows: {', '.join(available)}" if available else "No flows loaded"
                },
                status_code=404
            )

    @app.get("/api/runs", response_model=schema.RunsListResponse if schema else None)
    async def api_runs(
        limit: int = 100,
        offset: int = 0,
    ):
        """List available runs with pagination (active + examples).

        Args:
            limit: Maximum number of runs to return (default 100, max 500).
            offset: Number of runs to skip from the beginning (default 0).

        Delegates to RunService for unified run discovery and metadata.
        Falls back to FlowStudioCore if RunService is unavailable.

        Note: Uses run_in_threadpool because list_runs() does filesystem
        work (directory scanning, stat calls) that can be slow on WSL/Windows.
        """
        # Clamp pagination parameters
        limit = max(1, min(limit, 500))  # 1-500 range
        offset = max(0, offset)

        def _fetch_runs():
            """Blocking function to fetch runs - runs in threadpool."""
            all_runs_inner = []

            # Try RunService first for unified run listing
            if _run_service is not None:
                try:
                    summaries = _run_service.list_runs(
                        include_legacy=True,
                        include_examples=True,
                    )

                    # Convert RunSummary objects to backward-compatible dict format
                    for summary in summaries:
                        # Determine run_type from tags
                        if "example" in summary.tags:
                            run_type = "example"
                        else:
                            run_type = "active"

                        run_data = {
                            "run_id": summary.id,
                            "run_type": run_type,
                            "path": summary.path or "",
                        }

                        # Add optional metadata
                        if summary.title:
                            run_data["title"] = summary.title
                        if summary.description:
                            run_data["description"] = summary.description
                        # Add backend from spec
                        if summary.spec and summary.spec.backend:
                            run_data["backend"] = summary.spec.backend
                        # Add exemplar flag
                        if summary.is_exemplar:
                            run_data["is_exemplar"] = True
                        # Extract tags (excluding type markers)
                        filtered_tags = [t for t in summary.tags if t not in ("example", "legacy")]
                        if filtered_tags:
                            run_data["tags"] = filtered_tags

                        all_runs_inner.append(run_data)

                except Exception as e:
                    logger.warning(
                        "RunService.list_runs failed, falling back to legacy inspector: %s",
                        e,
                        exc_info=True,
                    )
                    all_runs_inner = []  # Reset for fallback

            # Fall back to FlowStudioCore if no runs from RunService
            if not all_runs_inner and _core:
                all_runs_inner = _core.list_runs()

            return all_runs_inner

        try:
            # Offload filesystem work to threadpool to avoid blocking event loop
            all_runs = await run_in_threadpool(_fetch_runs)
        except Exception:
            return JSONResponse(
                {
                    "error": "Run inspector not available",
                    "runs": [],
                    "total": 0,
                    "limit": limit,
                    "offset": offset,
                    "has_more": False,
                },
                status_code=503
            )

        # Apply pagination
        total = len(all_runs)
        paginated_runs = all_runs[offset:offset + limit]
        has_more = (offset + limit) < total

        return {
            "runs": paginated_runs,
            "total": total,
            "limit": limit,
            "offset": offset,
            "has_more": has_more,
        }

    @app.get("/api/runs/{run_id}/summary", response_model=schema.RunSummary if schema else None)
    async def api_run_summary(run_id: str):
        """Get full run summary."""
        if not _core:
            return JSONResponse(
                {"error": "Run inspector not available"},
                status_code=503
            )

        try:
            summary = _core.get_run_summary(run_id)
            return summary.to_dict()
        except Exception as e:
            return JSONResponse(
                {"error": str(e)},
                status_code=500
            )

    # =========================================================================
    # RunService Endpoints (new runtime layer)
    # =========================================================================

    @app.get("/api/backends", response_model=schema.BackendsListResponse if schema else None)
    async def api_backends():
        """List available run backends and their capabilities."""
        if _run_service is None:
            return JSONResponse(
                {"error": "RunService not available", "backends": []},
                status_code=503
            )

        try:
            backends = _run_service.list_backends()
            return {
                "backends": [
                    {
                        "id": b.id,
                        "label": b.label,
                        "supports_streaming": b.supports_streaming,
                        "supports_events": b.supports_events,
                        "supports_cancel": b.supports_cancel,
                        "supports_replay": b.supports_replay,
                    }
                    for b in backends
                ]
            }
        except Exception as e:
            return JSONResponse(
                {"error": str(e), "backends": []},
                status_code=500
            )

    @app.post("/api/run", response_model=schema.StartRunResponse if schema else None)
    async def api_start_run(request: schema.StartRunRequest if schema else None):
        """Start a new run.

        This endpoint triggers execution of the specified flows using the
        RunService. The run executes asynchronously - use the run_id to
        poll for status.

        Request body:
            flows: List of flow keys to execute (required)
            profile_id: Profile ID to use (optional)
            backend: Backend to use (default: "claude-harness")
        """
        if _run_service is None:
            return JSONResponse(
                {"error": "RunService not available"},
                status_code=503
            )

        # Handle the request body
        if request is None:
            return JSONResponse(
                {"error": "Request body required", "run_id": None, "status": "error"},
                status_code=400
            )

        try:
            spec = RunSpec(
                flow_keys=request.flows,
                profile_id=request.profile_id,
                backend=request.backend,
                initiator="flow-studio",
            )
            run_id = _run_service.start_run(spec)
            logger.info("Started run %s with flows: %s", run_id, request.flows)
            return {
                "run_id": run_id,
                "status": "started",
                "message": f"Run {run_id} started with flows: {', '.join(request.flows)}",
            }
        except ValueError as e:
            logger.warning("Invalid run request: %s", e)
            return JSONResponse(
                {"error": str(e), "run_id": None, "status": "error"},
                status_code=400
            )
        except Exception as e:
            logger.exception("Failed to start run")
            return JSONResponse(
                {"error": str(e), "run_id": None, "status": "error"},
                status_code=500
            )

    @app.get("/api/runs/{run_id}/events", response_model=schema.RunEventsResponse if schema else None)
    async def api_run_events(run_id: str):
        """Get all events for a run."""
        if _run_service is None:
            return JSONResponse(
                {"error": "RunService not available"},
                status_code=503
            )

        try:
            events = _run_service.get_events(run_id)
            return {
                "run_id": run_id,
                "events": [
                    {
                        "run_id": e.run_id,
                        "ts": e.ts.isoformat() if e.ts else None,
                        "kind": e.kind,
                        "flow_key": e.flow_key,
                        "step_id": e.step_id,
                        "agent_key": e.agent_key,
                        "payload": e.payload,
                    }
                    for e in events
                ],
            }
        except Exception as e:
            return JSONResponse(
                {"error": str(e)},
                status_code=500
            )

    @app.get("/api/runs/{run_id}/flows/{flow_key}/steps/{step_id}/transcript")
    async def api_step_transcript(run_id: str, flow_key: str, step_id: str):
        """Get LLM transcript for a specific step.

        Returns the conversation transcript (system/user/assistant messages)
        from Claude or Gemini execution of a specific step.

        Transcripts are stored at:
            RUN_BASE/<flow_key>/llm/<step_id>-*.jsonl

        Response:
            {
                "run_id": "...",
                "flow_key": "...",
                "step_id": "...",
                "engine": "claude" | "gemini" | null,
                "messages": [
                    {"ts": "...", "type": "system", "content": "..."},
                    {"ts": "...", "type": "user", "content": "..."},
                    {"ts": "...", "type": "assistant", "content": "...", "tool_calls": [...]}
                ]
            }
        """
        import json as json_module

        # Find run path
        run_path = None
        if _run_inspector is not None:
            run_path = _run_inspector.get_run_path(run_id)

        if run_path is None:
            # Try direct lookup
            from swarm.runtime import storage as runtime_storage
            run_path = runtime_storage.find_run_path(run_id)

        if run_path is None:
            return JSONResponse(
                {"error": f"Run '{run_id}' not found"},
                status_code=404
            )

        # Look for transcript files in llm/ subdirectory
        llm_dir = Path(run_path) / flow_key / "llm"
        if not llm_dir.exists():
            return JSONResponse(
                {
                    "error": "No transcripts available for this step",
                    "hint": "Transcripts are written by Claude flows using record_event.py"
                },
                status_code=404
            )

        # Find matching transcript file (pattern: <step_id>-<agent>-<engine>.jsonl)
        transcripts = list(llm_dir.glob(f"{step_id}-*.jsonl"))
        if not transcripts:
            return JSONResponse(
                {
                    "error": f"No transcript found for step '{step_id}'",
                    "available_files": [f.name for f in llm_dir.glob("*.jsonl")]
                },
                status_code=404
            )

        # Parse the transcript file
        transcript_file = transcripts[0]
        messages = []
        engine = None

        try:
            with transcript_file.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        msg = json_module.loads(line)
                        messages.append(msg)
                    except json_module.JSONDecodeError:
                        continue  # Skip malformed lines

            # Try to infer engine from filename (e.g., "3.4-code-implementer-claude.jsonl")
            parts = transcript_file.stem.split("-")
            if len(parts) >= 3:
                engine = parts[-1]  # Last part is engine

        except Exception as e:
            return JSONResponse(
                {"error": f"Failed to read transcript: {str(e)}"},
                status_code=500
            )

        return {
            "run_id": run_id,
            "flow_key": flow_key,
            "step_id": step_id,
            "engine": engine,
            "messages": messages,
            "transcript_file": transcript_file.name,
        }

    @app.get("/api/runs/{run_id}/flows/{flow_key}/steps/{step_id}/receipt")
    async def api_step_receipt(run_id: str, flow_key: str, step_id: str):
        """Get step receipt (summary) for a specific step.

        Receipts are structured summaries of step execution stored at:
            RUN_BASE/<flow_key>/receipts/<step_id>-<agent>.json

        Response:
            {
                "run_id": "...",
                "flow_key": "...",
                "step_id": "...",
                "receipt": {
                    "engine": "claude",
                    "agent_key": "code-implementer",
                    "status": "VERIFIED",
                    "summary": "...",
                    "concerns": [...],
                    "next_actions": [...]
                }
            }
        """
        import json as json_module

        # Find run path
        run_path = None
        if _run_inspector is not None:
            run_path = _run_inspector.get_run_path(run_id)

        if run_path is None:
            from swarm.runtime import storage as runtime_storage
            run_path = runtime_storage.find_run_path(run_id)

        if run_path is None:
            return JSONResponse(
                {"error": f"Run '{run_id}' not found"},
                status_code=404
            )

        # Look for receipt files
        receipts_dir = Path(run_path) / flow_key / "receipts"
        if not receipts_dir.exists():
            return JSONResponse(
                {"error": "No receipts available for this step"},
                status_code=404
            )

        # Find matching receipt file (pattern: <step_id>-<agent>.json)
        receipts = list(receipts_dir.glob(f"{step_id}-*.json"))
        if not receipts:
            return JSONResponse(
                {
                    "error": f"No receipt found for step '{step_id}'",
                    "available_files": [f.name for f in receipts_dir.glob("*.json")]
                },
                status_code=404
            )

        receipt_file = receipts[0]

        try:
            with receipt_file.open("r", encoding="utf-8") as f:
                receipt = json_module.load(f)
        except Exception as e:
            return JSONResponse(
                {"error": f"Failed to read receipt: {str(e)}"},
                status_code=500
            )

        return {
            "run_id": run_id,
            "flow_key": flow_key,
            "step_id": step_id,
            "receipt": receipt,
            "receipt_file": receipt_file.name,
        }

    @app.post("/api/runs/{run_id}/cancel")
    async def api_cancel_run(run_id: str):
        """Cancel a running run."""
        if _run_service is None:
            return JSONResponse(
                {"error": "RunService not available"},
                status_code=503
            )

        try:
            cancelled = _run_service.cancel_run(run_id)
            if cancelled:
                return {"status": "cancelled", "run_id": run_id}
            else:
                return JSONResponse(
                    {"error": "Run not found or already completed", "run_id": run_id},
                    status_code=404
                )
        except Exception as e:
            return JSONResponse(
                {"error": str(e)},
                status_code=500
            )

    @app.post("/api/runs/{run_id}/exemplar")
    async def api_set_exemplar(run_id: str, is_exemplar: bool = Query(True)):
        """Mark or unmark a run as an exemplar (for teaching mode)."""
        if _run_service is None:
            return JSONResponse(
                {"error": "RunService not available"},
                status_code=503
            )

        try:
            success = _run_service.mark_exemplar(run_id, is_exemplar)
            if success:
                return {
                    "status": "updated",
                    "run_id": run_id,
                    "is_exemplar": is_exemplar,
                }
            else:
                return JSONResponse(
                    {"error": "Run not found", "run_id": run_id},
                    status_code=404
                )
        except Exception as e:
            return JSONResponse(
                {"error": str(e)},
                status_code=500
            )

    @app.get("/api/runs/exemplars")
    async def api_list_exemplars():
        """List all exemplar runs (for teaching mode)."""
        if _run_service is None:
            return JSONResponse(
                {"error": "RunService not available", "runs": []},
                status_code=503
            )

        try:
            from swarm.runtime.types import run_summary_to_dict
            exemplars = _run_service.list_exemplars()
            return {
                "runs": [run_summary_to_dict(s) for s in exemplars],
            }
        except Exception as e:
            return JSONResponse(
                {"error": str(e), "runs": []},
                status_code=500
            )

    @app.get("/api/runs/{run_id}/wisdom/summary")
    async def api_run_wisdom_summary(run_id: str):
        """Get wisdom summary for a run.

        Returns the structured wisdom_summary.json content if present,
        or 404 if no wisdom summary exists for this run.

        Part of v2.4.0 Flow Studio Wisdom UI integration.
        """
        import json as json_module

        # Find run path
        run_path = None
        if _run_inspector is not None:
            run_path = _run_inspector.get_run_path(run_id)

        if run_path is None:
            from swarm.runtime import storage as runtime_storage
            run_path = runtime_storage.find_run_path(run_id)

        if run_path is None:
            return JSONResponse(
                {"error": f"Run '{run_id}' not found"},
                status_code=404
            )

        # Look for wisdom_summary.json
        wisdom_summary_path = Path(run_path) / "wisdom" / "wisdom_summary.json"
        if not wisdom_summary_path.exists():
            return JSONResponse(
                {
                    "error": "No wisdom summary available for this run",
                    "hint": f"Generate with: uv run swarm/tools/wisdom_summarizer.py {run_id}"
                },
                status_code=404
            )

        try:
            with wisdom_summary_path.open("r", encoding="utf-8") as f:
                summary = json_module.load(f)
            return summary
        except Exception as e:
            return JSONResponse(
                {"error": f"Failed to read wisdom summary: {str(e)}"},
                status_code=500
            )

    @app.get("/platform/status", response_model=schema.ValidationSnapshot if schema else None)
    async def platform_status():
        """Get current governance status.

        IMPORTANT: This endpoint runs blocking subprocess calls (kernel_smoke,
        selftest, validate_swarm) so we offload to a threadpool to avoid
        blocking the async event loop and causing head-of-line blocking for
        other API requests.
        """
        if not _core:
            return JSONResponse(
                {
                    "error": "Status provider not available",
                    "timestamp": None,
                    "service": "flow-studio",
                },
                status_code=503
            )

        try:
            # Offload to threadpool - this prevents blocking the event loop
            # while subprocess calls run (kernel_smoke, selftest, validate)
            status = await run_in_threadpool(_core.get_validation_snapshot)
            return status.to_dict()
        except Exception as e:
            return JSONResponse(
                {
                    "error": f"Failed to compute status: {str(e)}",
                    "service": "flow-studio",
                },
                status_code=500
            )

    @app.get("/api/selftest/plan", response_model=schema.SelftestPlanResponse if schema else None)
    async def api_selftest_plan():
        """Get selftest plan with all steps, tiers, and dependencies."""
        try:
            # Import locally to avoid module-level sys.exit() issues
            import os
            import sys
            # Add swarm/tools to path so selftest_config can be imported
            tools_path = os.path.join(os.path.dirname(__file__))
            if tools_path not in sys.path:
                sys.path.insert(0, tools_path)

            from swarm.tools.selftest import get_selftest_plan_json
            plan = get_selftest_plan_json()
            return plan
        except (ImportError, SystemExit):
            return JSONResponse(
                {"error": "Selftest module not available"},
                status_code=503
            )
        except Exception as e:
            return JSONResponse(
                {"error": f"Failed to get selftest plan: {str(e)}"},
                status_code=500
            )

    # =========================================================================
    # Validation Endpoint
    # =========================================================================

    @app.get("/api/validation", response_model=schema.ValidationData if schema else None)
    async def api_validation():
        """Return cached validation data (FR status badges and governance info)."""
        if _validation_data is not None:
            return {"data": _validation_data}
        return JSONResponse(
            {"data": None, "error": "validation data not available"},
            status_code=503
        )

    # =========================================================================
    # Flow Detail Endpoint
    # =========================================================================

    @app.get("/api/flows/{flow_key}", response_model=schema.FlowDetail if schema else None)
    async def api_flow_detail(flow_key: str):
        """Get detailed flow information with steps and agents."""
        if flow_key not in _flows_cache:
            available = sorted(_flows_cache.keys())
            return JSONResponse(
                {
                    "error": f"Flow '{flow_key}' not found",
                    "available_flows": available,
                    "hint": f"Available flows: {', '.join(available)}" if available else "No flows loaded"
                },
                status_code=404
            )

        flow = _flows_cache[flow_key]
        steps = []
        used_agents: Dict[str, bool] = {}

        for s in flow.get("steps", []):
            steps.append({
                "id": s["id"],
                "title": s["title"],
                "role": s["role"],
                "agents": s["agents"],
            })
            for ak in s.get("agents", []):
                used_agents[ak] = True

        agents: Dict[str, Any] = {}
        for ak in sorted(used_agents.keys()):
            a = _agents_cache.get(ak)
            if a:
                agents[ak] = a
            else:
                agents[ak] = {
                    "key": ak,
                    "category": "unknown",
                    "color": "#9ca3af",
                    "model": "inherit",
                    "short_role": "",
                }

        return {
            "flow": {
                "key": flow["key"],
                "title": flow["title"],
                "description": flow["description"],
            },
            "steps": steps,
            "agents": agents,
        }

    # =========================================================================
    # Agents Endpoints
    # =========================================================================

    @app.get("/api/agents", response_model=schema.AgentsListResponse if schema else None)
    async def api_agents():
        """Get full list of agents."""
        return {"agents": list(_agents_cache.values())}

    @app.get("/api/agents/{agent_key}/usage", response_model=schema.AgentUsageResponse if schema else None)
    async def api_agent_usage(agent_key: str):
        """Get usage information for an agent: which flows and steps it appears in."""
        usage: List[Dict[str, Any]] = []

        for flow_key, flow in _flows_cache.items():
            for step in flow.get("steps", []):
                if agent_key in step.get("agents", []):
                    usage.append({
                        "flow": flow_key,
                        "flow_title": flow["title"],
                        "step": step["id"],
                        "step_title": step["title"],
                    })

        return {
            "agent": agent_key,
            "usage": usage,
        }

    # =========================================================================
    # Reload Endpoint
    # =========================================================================

    @app.post("/api/reload", response_model=schema.ReloadResponse if schema else None)
    async def api_reload():
        """Force reload all data from disk."""
        agents, flows = _reload_from_disk()
        return {
            "status": "ok",
            "flows": len(flows),
            "agents": len(agents),
        }

    # =========================================================================
    # Platform Status Refresh Endpoint
    # =========================================================================

    @app.post("/platform/status/refresh", response_model=schema.ValidationSnapshot if schema else None)
    async def platform_status_refresh():
        """Force refresh of governance status (bypasses cache).

        IMPORTANT: This endpoint runs blocking subprocess calls (kernel_smoke,
        selftest, validate_swarm) so we offload to a threadpool to avoid
        blocking the async event loop.
        """
        if not _core:
            return JSONResponse(
                {
                    "error": "Status provider not available",
                    "timestamp": None,
                    "service": "flow-studio",
                },
                status_code=503
            )

        def _do_refresh():
            """Blocking refresh operation to run in threadpool."""
            if hasattr(_core, '_status_provider') and _core._status_provider:
                status = _core._status_provider.get_status(force_refresh=True)
                from swarm.flowstudio.core import ValidationSnapshot
                return ValidationSnapshot(
                    timestamp=status.timestamp,
                    service=status.service,
                    governance=status.governance,
                    flows=status.flows if hasattr(status, 'flows') else {},
                    agents=status.agents if hasattr(status, 'agents') else {},
                    hints=status.hints if hasattr(status, 'hints') else {},
                ).to_dict()
            else:
                status = _core.get_validation_snapshot()
                return status.to_dict()

        try:
            # Offload to threadpool - this prevents blocking the event loop
            result = await run_in_threadpool(_do_refresh)
            return result
        except Exception as e:
            return JSONResponse(
                {
                    "error": f"Failed to compute status: {str(e)}",
                    "service": "flow-studio",
                },
                status_code=500
            )

    # =========================================================================
    # Run Inspector API Endpoints
    # =========================================================================

    @app.get("/api/runs/{run_id}/sdlc", response_model=schema.SDLCBarResponse if schema else None)
    async def api_run_sdlc(run_id: str):
        """Get SDLC bar data for a run."""
        if _run_inspector is None:
            return JSONResponse(
                {"error": "Run inspector not available"},
                status_code=503
            )
        bar = _run_inspector.get_sdlc_bar(run_id)
        return {"run_id": run_id, "sdlc": bar}

    @app.get("/api/runs/{run_id}/flows/{flow_key}", response_model=schema.FlowStatusInfo if schema else None)
    async def api_run_flow(run_id: str, flow_key: str):
        """Get flow status for a run."""
        if _run_inspector is None:
            return JSONResponse(
                {"error": "Run inspector not available"},
                status_code=503
            )
        result = _run_inspector.get_flow_status(run_id, flow_key)
        return _run_inspector.to_dict(result)

    @app.get("/api/runs/{run_id}/flows/{flow_key}/steps/{step_id}", response_model=schema.StepStatusInfo if schema else None)
    async def api_run_step(run_id: str, flow_key: str, step_id: str):
        """Get step status for a run."""
        if _run_inspector is None:
            return JSONResponse(
                {"error": "Run inspector not available"},
                status_code=503
            )
        result = _run_inspector.get_step_status(run_id, flow_key, step_id)

        # Add timing if available
        step_timing = None
        flow_timing = _run_inspector.get_flow_timing(run_id, flow_key)
        if flow_timing:
            for st in flow_timing.steps:
                if st.step_id == step_id:
                    step_timing = _run_inspector.to_dict(st)
                    break

        step_dict = _run_inspector.to_dict(result)
        step_dict["timing"] = step_timing
        return step_dict

    @app.get("/api/runs/{run_id}/timeline", response_model=schema.TimelineResponse if schema else None)
    async def api_run_timeline(run_id: str):
        """Get chronological event timeline for a run."""
        if _run_inspector is None:
            return JSONResponse(
                {"error": "RunInspector not available"},
                status_code=503
            )

        timeline = _run_inspector.get_run_timeline(run_id)
        return {
            "run_id": run_id,
            "events": [_run_inspector.to_dict(e) for e in timeline]
        }

    @app.get("/api/runs/{run_id}/timing", response_model=schema.RunTimingResponse if schema else None)
    async def api_run_timing(run_id: str):
        """Get timing summary for a run."""
        if _run_inspector is None:
            return JSONResponse(
                {"error": "RunInspector not available"},
                status_code=503
            )

        timing = _run_inspector.get_run_timing(run_id)
        if timing is None:
            return {"run_id": run_id, "timing": None, "message": "No timing data available"}

        return {
            "run_id": run_id,
            "timing": _run_inspector.to_dict(timing)
        }

    @app.get("/api/runs/{run_id}/flows/{flow_key}/timing", response_model=schema.FlowTimingResponse if schema else None)
    async def api_flow_timing(run_id: str, flow_key: str):
        """Get timing for a specific flow in a run."""
        if _run_inspector is None:
            return JSONResponse(
                {"error": "RunInspector not available"},
                status_code=503
            )

        timing = _run_inspector.get_flow_timing(run_id, flow_key)
        if timing is None:
            return {
                "run_id": run_id,
                "flow_key": flow_key,
                "timing": None,
                "message": "No timing data available"
            }

        return {
            "run_id": run_id,
            "flow_key": flow_key,
            "timing": _run_inspector.to_dict(timing)
        }

    @app.get("/api/runs/compare", response_class=JSONResponse)
    async def api_runs_compare(
        run_a: str = Query(None, description="First run identifier (baseline)"),
        run_b: str = Query(None, description="Second run identifier (comparison target)"),
        flow: str = Query(None, description="Flow key to compare")
    ):
        """Compare two runs for a specific flow."""
        if _run_inspector is None:
            return JSONResponse(
                {"error": "Run inspector not available"},
                status_code=503
            )

        if not run_a or not run_b or not flow:
            return JSONResponse(
                {"error": "Missing required parameters: run_a, run_b, flow"},
                status_code=400
            )

        if _run_inspector.get_run_path(run_a) is None:
            return JSONResponse(
                {"error": f"Run '{run_a}' not found"},
                status_code=404
            )

        if _run_inspector.get_run_path(run_b) is None:
            return JSONResponse(
                {"error": f"Run '{run_b}' not found"},
                status_code=404
            )

        if flow not in _run_inspector.catalog.get("flows", {}):
            return JSONResponse(
                {"error": f"Flow '{flow}' not found in catalog"},
                status_code=404
            )

        result = _run_inspector.compare_flows(run_a, run_b, flow)
        return result

    # =========================================================================
    # Artifact Graph Endpoint
    # =========================================================================

    def _load_artifact_catalog() -> Dict[str, Any]:
        """Load the artifact catalog from swarm/meta/artifact_catalog.json."""
        import json
        catalog_path = REPO_ROOT / "swarm" / "meta" / "artifact_catalog.json"
        if not catalog_path.exists():
            return {"flows": {}}
        with open(catalog_path) as f:
            return json.load(f)

    @app.get("/api/graph/{flow_key}/artifacts", response_model=schema.GraphPayload if schema else None)
    async def api_graph_artifacts(
        flow_key: str,
        run_id: str = Query(None, description="Optional run ID to overlay artifact status")
    ):
        """Get artifact-centric graph for a flow."""
        if flow_key not in _flows_cache:
            available = sorted(_flows_cache.keys())
            return JSONResponse(
                {
                    "error": f"Flow '{flow_key}' not found",
                    "available_flows": available,
                    "hint": f"Available flows: {', '.join(available)}" if available else "No flows loaded"
                },
                status_code=404
            )

        flow = _flows_cache[flow_key]
        artifact_catalog = _load_artifact_catalog()
        flow_catalog = artifact_catalog.get("flows", {}).get(flow_key, {})
        decision_artifact = flow_catalog.get("decision_artifact")
        step_catalog = flow_catalog.get("steps", {})

        # Get artifact status from run inspector if run_id provided
        artifact_status: Dict[str, str] = {}  # filename -> "present" | "missing"
        if run_id and _run_inspector is not None:
            try:
                flow_result = _run_inspector.get_flow_status(run_id, flow_key)
                for step_id, step_result in flow_result.steps.items():
                    for artifact in step_result.artifacts:
                        artifact_status[f"{step_id}:{artifact.path}"] = artifact.status.value
            except Exception:
                pass  # Graceful degradation if run inspector fails

        nodes: List[Dict[str, Any]] = []
        edges: List[Dict[str, Any]] = []

        # Step nodes
        for idx, step in enumerate(flow.get("steps", [])):
            nid = f"step:{flow_key}:{step['id']}"
            nodes.append({
                "data": {
                    "id": nid,
                    "label": step["title"],
                    "type": "step",
                    "flow": flow_key,
                    "step_id": step["id"],
                    "order": idx,
                    "role": step.get("role", ""),
                }
            })

        # Step ordering edges
        steps = flow.get("steps", [])
        for i in range(len(steps) - 1):
            a = steps[i]
            b = steps[i + 1]
            edges.append({
                "data": {
                    "id": f"edge:step:{a['id']}->{b['id']}",
                    "source": f"step:{flow_key}:{a['id']}",
                    "target": f"step:{flow_key}:{b['id']}",
                    "type": "step-sequence",
                }
            })

        # Artifact nodes + step->artifact edges
        for step in steps:
            step_node_id = f"step:{flow_key}:{step['id']}"
            step_artifacts = step_catalog.get(step["id"], {})
            required_artifacts = step_artifacts.get("required", [])
            optional_artifacts = step_artifacts.get("optional", [])
            note = step_artifacts.get("note")

            for artifact in required_artifacts:
                artifact_id = f"artifact:{flow_key}:{step['id']}:{artifact}"
                status_key = f"{step['id']}:{artifact}"
                status = artifact_status.get(status_key, "unknown")
                is_decision = (artifact == decision_artifact)

                nodes.append({
                    "data": {
                        "id": artifact_id,
                        "label": artifact,
                        "type": "artifact",
                        "flow": flow_key,
                        "step_id": step["id"],
                        "filename": artifact,
                        "required": True,
                        "status": status,
                        "is_decision": is_decision,
                        "note": note,
                    }
                })

                edges.append({
                    "data": {
                        "id": f"edge:step:{step['id']}->artifact:{artifact}",
                        "source": step_node_id,
                        "target": artifact_id,
                        "type": "step-artifact",
                    }
                })

            for artifact in optional_artifacts:
                artifact_id = f"artifact:{flow_key}:{step['id']}:{artifact}"
                status_key = f"{step['id']}:{artifact}"
                status = artifact_status.get(status_key, "unknown")

                nodes.append({
                    "data": {
                        "id": artifact_id,
                        "label": artifact,
                        "type": "artifact",
                        "flow": flow_key,
                        "step_id": step["id"],
                        "filename": artifact,
                        "required": False,
                        "status": status,
                        "is_decision": False,
                        "note": note,
                    }
                })

                edges.append({
                    "data": {
                        "id": f"edge:step:{step['id']}->artifact:{artifact}",
                        "source": step_node_id,
                        "target": artifact_id,
                        "type": "step-artifact",
                    }
                })

        return {"nodes": nodes, "edges": edges}

    # =========================================================================
    # Search Endpoint
    # =========================================================================

    @app.get("/api/search", response_model=schema.SearchResponse if schema else None)
    async def api_search(q: str = Query("", description="Search query")):
        """Search across flows, steps, agents, and artifacts."""
        query = q.lower().strip()
        if not query:
            return {"results": [], "query": ""}

        results: List[Dict[str, Any]] = []
        max_results = 8

        # Search flows
        for flow_key, flow in _flows_cache.items():
            if len(results) >= max_results:
                break
            if query in flow_key.lower() or query in flow["title"].lower():
                results.append({
                    "type": "flow",
                    "id": flow_key,
                    "label": flow["title"],
                    "match": query
                })

        # Search steps
        for flow_key, flow in _flows_cache.items():
            if len(results) >= max_results:
                break
            for step in flow.get("steps", []):
                if len(results) >= max_results:
                    break
                if query in step["id"].lower() or query in step["title"].lower():
                    results.append({
                        "type": "step",
                        "flow": flow_key,
                        "id": step["id"],
                        "label": step["title"],
                        "match": query
                    })

        # Search agents
        for agent_key, agent in _agents_cache.items():
            if len(results) >= max_results:
                break
            short_role = agent.get("short_role", "")
            if query in agent_key.lower() or query in short_role.lower():
                # Find which flows this agent belongs to
                agent_flows = []
                for flow_key, flow in _flows_cache.items():
                    for step in flow.get("steps", []):
                        if agent_key in step.get("agents", []):
                            agent_flows.append(flow_key)
                            break
                results.append({
                    "type": "agent",
                    "key": agent_key,
                    "label": agent_key,
                    "flows": agent_flows,
                    "match": query
                })

        # Search artifacts (common artifact filenames)
        common_artifacts = [
            ("signal", "normalize_input", "problem_statement.md"),
            ("signal", "author_requirements", "requirements.md"),
            ("signal", "author_bdd", "bdd_scenarios.feature"),
            ("signal", "assess_risk", "risk_assessment.md"),
            ("plan", "author_adr", "adr.md"),
            ("plan", "design_interfaces", "api_contracts.yaml"),
            ("plan", "design_observability", "observability_spec.md"),
            ("plan", "author_test_strategy", "test_plan.md"),
            ("plan", "author_work_plan", "work_plan.md"),
            ("build", "author_tests", "test_summary.md"),
            ("build", "implement_code", "impl_changes_summary.md"),
            ("build", "self_review", "build_receipt.json"),
            ("gate", "check_receipts", "receipt_audit.md"),
            ("gate", "decide_merge", "merge_decision.md"),
            ("deploy", "verify_deployment", "verification_report.md"),
            ("wisdom", "audit_artifacts", "artifact_audit.md"),
            ("wisdom", "synthesize_learnings", "learnings.md"),
        ]
        for flow, step, filename in common_artifacts:
            if len(results) >= max_results:
                break
            if query in filename.lower():
                results.append({
                    "type": "artifact",
                    "flow": flow,
                    "step": step,
                    "file": filename,
                    "match": query
                })

        return {"results": results, "query": query}

    # =========================================================================
    # Layout Screens Endpoint (UX Review)
    # =========================================================================

    # Layout spec - mirrored from TypeScript layout_spec.ts
    # This is the Python-side mirror of the layout registry for MCP/tools
    LAYOUT_SCREENS: List[Dict[str, Any]] = [
        {
            "id": "flows.default",
            "route": "/",
            "title": "Flows - Default",
            "description": "Main Flow Studio screen with run selector, flow list, graph canvas, and inspector.",
            "regions": [
                {
                    "id": "header",
                    "purpose": "Global navigation, search, governance indicators, mode toggle.",
                    "uiids": [
                        "flow_studio.header",
                        "flow_studio.header.search",
                        "flow_studio.header.search.input",
                        "flow_studio.header.search.results",
                        "flow_studio.header.controls",
                        "flow_studio.header.tour",
                        "flow_studio.header.governance",
                        "flow_studio.header.reload",
                        "flow_studio.header.help",
                    ],
                },
                {
                    "id": "sdlc_bar",
                    "purpose": "SDLC progress bar showing flow completion status.",
                    "uiids": ["flow_studio.sdlc_bar"],
                },
                {
                    "id": "sidebar",
                    "purpose": "Run selector, flow list, and view toggles.",
                    "uiids": [
                        "flow_studio.sidebar",
                        "flow_studio.sidebar.run_selector",
                        "flow_studio.sidebar.flow_list",
                        "flow_studio.sidebar.view_toggle",
                    ],
                },
                {
                    "id": "canvas",
                    "purpose": "Graph visualization of the current flow and SDLC legend.",
                    "uiids": [
                        "flow_studio.canvas",
                        "flow_studio.canvas.graph",
                        "flow_studio.canvas.legend",
                        "flow_studio.canvas.outline",
                    ],
                },
                {
                    "id": "inspector",
                    "purpose": "Details panel for selected step/agent/artifact.",
                    "uiids": [
                        "flow_studio.inspector",
                        "flow_studio.inspector.details",
                    ],
                },
            ],
        },
        {
            "id": "flows.selftest",
            "route": "/?modal=selftest",
            "title": "Flows - Selftest Modal",
            "description": "Selftest plan / results modal and controls.",
            "regions": [
                {
                    "id": "modal",
                    "purpose": "Selftest plan, run controls, copy helpers.",
                    "uiids": ["flow_studio.modal.selftest"],
                },
            ],
        },
        {
            "id": "flows.shortcuts",
            "route": "/?modal=shortcuts",
            "title": "Flows - Shortcuts Modal",
            "description": "Keyboard shortcuts reference modal.",
            "regions": [
                {
                    "id": "modal",
                    "purpose": "Keyboard shortcuts grid.",
                    "uiids": ["flow_studio.modal.shortcuts"],
                },
            ],
        },
        {
            "id": "flows.validation",
            "route": "/?tab=validation",
            "title": "Flows - Validation View",
            "description": "Governance validation results and FR status badges.",
            "regions": [
                {
                    "id": "header",
                    "purpose": "Governance badge and overlay toggle.",
                    "uiids": [
                        "flow_studio.header.governance",
                    ],
                },
                {
                    "id": "inspector",
                    "purpose": "Validation details for selected agent or flow.",
                    "uiids": [
                        "flow_studio.inspector",
                        "flow_studio.inspector.details",
                    ],
                },
            ],
        },
        {
            "id": "flows.tour",
            "route": "/?tour=<tour_id>",
            "title": "Flows - Tour Mode",
            "description": "Guided tour overlay with step-by-step navigation.",
            "regions": [
                {
                    "id": "header",
                    "purpose": "Tour menu and controls.",
                    "uiids": [
                        "flow_studio.header.tour",
                    ],
                },
                {
                    "id": "canvas",
                    "purpose": "Tour card overlay on graph nodes.",
                    "uiids": [
                        "flow_studio.canvas",
                        "flow_studio.canvas.graph",
                    ],
                },
            ],
        },
    ]

    @app.get("/api/layout_screens")
    async def api_layout_screens():
        """
        Get layout screen specifications for UX review tooling.

        Returns the authoritative registry of screens, regions, and UIIDs
        that MCP tools and run_layout_review.py can use to enumerate and
        capture Flow Studio UI state.

        This mirrors the TypeScript layout_spec.ts for Python consumers.
        """
        return {
            "version": "0.5.0-flowstudio",
            "screens": LAYOUT_SCREENS,
        }

    # =========================================================================
    # Tours Endpoints
    # =========================================================================

    @app.get("/api/tours", response_model=schema.ToursListResponse if schema else None)
    async def api_tours():
        """List all available guided tours."""
        tours = []
        for tour in _tours_cache.values():
            tours.append({
                "id": tour["id"],
                "title": tour["title"],
                "description": tour["description"],
                "step_count": len(tour["steps"]),
            })
        return {"tours": tours}

    @app.get("/api/tours/{tour_id}", response_model=schema.TourDetail if schema else None)
    async def api_tour_detail(tour_id: str):
        """Get full tour definition with all steps."""
        tour = _tours_cache.get(tour_id)
        if not tour:
            available = sorted(_tours_cache.keys())
            return JSONResponse(
                {
                    "error": f"Tour '{tour_id}' not found",
                    "available_tours": available,
                    "hint": f"Available tours: {', '.join(available)}" if available else "No tours loaded"
                },
                status_code=404
            )

        steps = []
        for step in tour["steps"]:
            steps.append({
                "target": {
                    "type": step["target_type"],
                    "flow": step["target_flow"],
                    "step": step["target_step"],
                },
                "title": step["title"],
                "text": step["text"],
                "action": step["action"],
            })

        return {
            "id": tour["id"],
            "title": tour["title"],
            "description": tour["description"],
            "steps": steps,
        }

    # =========================================================================
    # Station Spec Compilation Preview
    # =========================================================================

    @app.post(
        "/api/station/compile-preview",
        response_model=schema.CompilePreviewResponse if schema else None,
    )
    async def api_station_compile_preview(
        request: schema.CompilePreviewRequest if schema else None,
    ):
        """Preview the compiled station spec before execution.

        This endpoint compiles a station spec for a given flow/step combination
        and returns the fully resolved prompt plan without executing it.

        This is useful for:
        - Debugging prompt construction
        - Previewing what the LLM will see
        - Validating spec changes before execution
        - Understanding the compilation pipeline

        Request body:
            flow_id: Flow identifier (e.g., "3-build")
            step_id: Step identifier within the flow (e.g., "3.3")
            station_id: Station identifier (e.g., "code-implementer")
            run_id: Optional run ID for context resolution

        Returns:
            Compiled prompt plan with system prompt, user prompt, SDK options,
            verification requirements, and traceability metadata.
        """
        if request is None:
            return JSONResponse(
                {"error": "Request body required"},
                status_code=400
            )

        # Import the SpecCompiler
        try:
            from swarm.spec.compiler import SpecCompiler, COMPILER_VERSION
        except ImportError:
            return JSONResponse(
                {"error": "SpecCompiler not available"},
                status_code=503
            )

        # Determine run base path
        run_base = REPO_ROOT / "swarm" / "runs" / (request.run_id or "default")

        try:
            # Create compiler and compile the step
            compiler = SpecCompiler(repo_root=REPO_ROOT)
            plan = compiler.compile(
                flow_id=request.flow_id,
                step_id=request.step_id,
                context_pack=None,  # No runtime context for preview
                run_base=run_base,
                cwd=str(REPO_ROOT),
            )

            # Build response
            return {
                "flow_id": plan.flow_id,
                "step_id": plan.step_id,
                "station_id": plan.station_id,
                "system_prompt": plan.system_append,
                "user_prompt": plan.user_prompt,
                "sdk_options": {
                    "model": plan.model,
                    "tools": list(plan.allowed_tools),
                    "permission_mode": plan.permission_mode,
                    "max_turns": plan.max_turns,
                    "sandbox_enabled": plan.sandbox_enabled,
                    "cwd": plan.cwd,
                },
                "verification": {
                    "required_artifacts": list(plan.verification.required_artifacts),
                    "verification_commands": list(plan.verification.verification_commands),
                },
                "traceability": {
                    "prompt_hash": plan.prompt_hash,
                    "compiled_at": plan.compiled_at,
                    "compiler_version": COMPILER_VERSION,
                    "station_version": plan.station_version,
                    "flow_version": plan.flow_version,
                },
            }

        except FileNotFoundError as e:
            # Flow or station spec not found
            return JSONResponse(
                {
                    "error": f"Spec not found: {str(e)}",
                    "hint": "Check that flow_id and step_id reference valid specs in swarm/specs/",
                },
                status_code=404
            )
        except ValueError as e:
            # Step not found in flow
            return JSONResponse(
                {
                    "error": f"Invalid step: {str(e)}",
                    "hint": "Verify step_id matches a step in the specified flow",
                },
                status_code=400
            )
        except Exception as e:
            logger.exception("Failed to compile station spec preview")
            return JSONResponse(
                {"error": f"Compilation failed: {str(e)}"},
                status_code=500
            )

    # Mount static files (CSS, JS, static assets) from the flow_studio_ui directory
    ui_dir = Path(__file__).parent / "flow_studio_ui"

    # Startup sanity check: warn if required compiled JS files are missing
    # These files are compiled from TypeScript via `make ts-build`
    # If missing, the UI will load but fail silently with 404s
    #
    # This check is drift-proof: instead of maintaining a hardcoded list of all
    # modules, we only require entrypoints and parse their imports dynamically.
    # This stays in sync with reality as modules are added/renamed.
    _check_ui_assets(ui_dir)

    if (ui_dir / "css").exists():
        app.mount("/css", StaticFiles(directory=str(ui_dir / "css")), name="css")
    if (ui_dir / "js").exists():
        app.mount("/js", StaticFiles(directory=str(ui_dir / "js")), name="js")
    if (ui_dir / "static").exists():
        app.mount("/static", StaticFiles(directory=str(ui_dir / "static")), name="static")

    return app


# Create the app instance
app = create_fastapi_app()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=5000)
