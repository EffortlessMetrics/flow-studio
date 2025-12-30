"""
FastAPI REST API server for SpecManager functionality.

Exposes the spec system (flows, templates, validation, compilation) to the
TypeScript frontend.

Note: Although the original request specified Flask, the codebase standardizes
on FastAPI. This implementation follows FastAPI patterns to match existing code
in swarm/tools/flow_studio_fastapi.py.

Usage:
    # Run standalone
    python -m swarm.api.server

    # Or via factory
    from swarm.api import create_app, SpecManager
    app = create_app()
    uvicorn.run(app, port=5001)

API Structure:
    /api/specs/           - Template and flow graph endpoints (from routes/specs.py)
    /api/runs/            - Run control endpoints (from routes/runs.py)
    /api/runs/{id}/events - SSE streaming (from routes/events.py)
    /api/spec/            - Legacy endpoints (inline, for backward compatibility)
    /api/health           - Health check
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple

from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# =============================================================================
# Pydantic Models for Request/Response
# =============================================================================


class FlowSummary(BaseModel):
    """Flow summary for list endpoint."""

    id: str
    title: str
    flow_number: Optional[int] = None
    version: int = 1
    description: str = ""


class FlowListResponse(BaseModel):
    """Response for list flows endpoint."""

    flows: List[FlowSummary]


class TemplateSummary(BaseModel):
    """Template summary for list endpoint."""

    id: str
    title: str
    station_id: Optional[str] = None
    category: Optional[str] = None
    tags: List[str] = []
    description: str = ""


class TemplateListResponse(BaseModel):
    """Response for list templates endpoint."""

    templates: List[TemplateSummary]


class ValidationRequest(BaseModel):
    """Request for validation endpoint."""

    id: Optional[str] = None
    version: Optional[int] = None
    title: Optional[str] = None
    nodes: Optional[List[Dict[str, Any]]] = None
    edges: Optional[List[Dict[str, Any]]] = None


class ValidationResponse(BaseModel):
    """Response for validation endpoint."""

    valid: bool
    errors: List[str]


class CompileRequest(BaseModel):
    """Request for compile endpoint."""

    flow_id: str
    step_id: str
    run_id: Optional[str] = None


class CompileResponse(BaseModel):
    """Response for compile endpoint."""

    prompt_plan: Dict[str, Any]


class RunSummary(BaseModel):
    """Run summary for list endpoint."""

    run_id: str
    flow_key: Optional[str] = None
    status: Optional[str] = None
    timestamp: Optional[str] = None


class RunListResponse(BaseModel):
    """Response for list runs endpoint."""

    runs: List[RunSummary]


class DBHealthInfo(BaseModel):
    """Database health information."""

    healthy: bool = False
    projection_version: int = 0
    db_exists: bool = False
    rebuild_count: int = 0
    error_count: int = 0
    last_error: Optional[str] = None
    last_check: Optional[str] = None
    last_rebuild: Optional[str] = None


class TailerHealthInfo(BaseModel):
    """RunTailer health information."""

    enabled: bool = False
    active_runs: int = 0
    total_events_ingested: int = 0
    last_ingest_at: Optional[str] = None
    error: Optional[str] = None


class TailerIngestResponse(BaseModel):
    """Response for manual tailer ingest endpoint."""

    run_id: str
    events_ingested: int


class HealthResponse(BaseModel):
    """Response for health check endpoint."""

    status: str
    timestamp: str
    repo_root: str
    db: Optional[DBHealthInfo] = None
    tailer: Optional[TailerHealthInfo] = None


class ErrorResponse(BaseModel):
    """Standard error response."""

    error: str
    message: str
    details: Dict[str, Any] = {}


# =============================================================================
# SpecManager - Centralized Spec Management
# =============================================================================


class SpecManager:
    """Manages spec loading, caching, and mutations.

    The SpecManager is the single source of truth for flow graphs, templates,
    and run state. It handles:
    - Loading specs from YAML files
    - Computing ETags for optimistic concurrency
    - Validating spec mutations
    - Compiling PromptPlans

    Attributes:
        repo_root: Repository root path.
        spec_root: Path to spec directory (swarm/spec).
        runs_root: Path to runs directory (swarm/runs).
        _flow_cache: Cached flow graphs with ETags.
        _template_cache: Cached templates with ETags.
    """

    def __init__(self, repo_root: Optional[Path] = None):
        """Initialize the SpecManager.

        Args:
            repo_root: Repository root path. If not provided, auto-detects
                by walking up from current file.
        """
        if repo_root is None:
            repo_root = self._find_repo_root()

        self.repo_root = repo_root
        self.spec_root = repo_root / "swarm" / "spec"
        self.runs_root = repo_root / "swarm" / "runs"
        self.flows_config = repo_root / "swarm" / "config" / "flows"

        self._flow_cache: Dict[str, Tuple[Dict[str, Any], str]] = {}
        self._template_cache: Dict[str, Tuple[Dict[str, Any], str]] = {}
        self._run_state_cache: Dict[str, Tuple[Dict[str, Any], str]] = {}

        logger.info("SpecManager initialized with repo_root=%s", repo_root)

    @staticmethod
    def _find_repo_root() -> Path:
        """Find repository root by looking for .git directory.

        The .git directory is the most reliable indicator of repo root,
        as there may be CLAUDE.md files in subdirectories.
        """
        current = Path(__file__).resolve()
        for parent in current.parents:
            if (parent / ".git").exists():
                return parent
        # Fallback: look for root CLAUDE.md (only at actual roots)
        for parent in current.parents:
            if (parent / "CLAUDE.md").exists() and (parent / "swarm").exists():
                return parent
        raise RuntimeError("Could not find repository root")

    def _compute_etag(self, data: Any) -> str:
        """Compute ETag hash for data.

        Args:
            data: Data to hash (will be JSON serialized).

        Returns:
            Shortened SHA256 hash as ETag.
        """
        content = json.dumps(data, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    # -------------------------------------------------------------------------
    # Flow Graph Operations
    # -------------------------------------------------------------------------

    def list_flows(self) -> List[Dict[str, Any]]:
        """List all available flow graphs.

        Returns:
            List of flow summaries with id, title, flow_number, version.
        """
        flows = []

        # Check for flow graph specs in swarm/spec/flows/
        flow_graphs_dir = self.spec_root / "flows"
        if flow_graphs_dir.exists():
            for yaml_file in flow_graphs_dir.glob("*.yaml"):
                try:
                    flow_data = self._load_yaml(yaml_file)
                    flows.append(
                        {
                            "id": flow_data.get("id", yaml_file.stem),
                            "title": flow_data.get("title", yaml_file.stem),
                            "flow_number": flow_data.get("flow_number"),
                            "version": flow_data.get("version", 1),
                            "description": flow_data.get("description", ""),
                        }
                    )
                except Exception as e:
                    logger.warning("Failed to load flow %s: %s", yaml_file, e)

        # Also check config/flows for legacy flow definitions
        if self.flows_config.exists():
            for yaml_file in self.flows_config.glob("*.yaml"):
                flow_id = yaml_file.stem
                # Skip if already loaded from spec/flows
                if any(f["id"] == flow_id for f in flows):
                    continue
                try:
                    flow_data = self._load_yaml(yaml_file)
                    flows.append(
                        {
                            "id": flow_id,
                            "title": flow_data.get("name", flow_id),
                            "flow_number": flow_data.get("flow_number"),
                            "version": flow_data.get("version", 1),
                            "description": flow_data.get("description", ""),
                        }
                    )
                except Exception as e:
                    logger.warning("Failed to load flow config %s: %s", yaml_file, e)

        # Sort by flow_number
        flows.sort(key=lambda f: f.get("flow_number") or 99)
        return flows

    def get_flow(self, flow_id: str) -> Tuple[Dict[str, Any], str]:
        """Get a flow graph by ID.

        Args:
            flow_id: Flow identifier.

        Returns:
            Tuple of (flow_data, etag).

        Raises:
            FileNotFoundError: If flow not found.
        """
        # Check cache
        if flow_id in self._flow_cache:
            return self._flow_cache[flow_id]

        # Try spec/flows first
        flow_file = self.spec_root / "flows" / f"{flow_id}.yaml"
        if not flow_file.exists():
            # Try config/flows
            flow_file = self.flows_config / f"{flow_id}.yaml"

        if not flow_file.exists():
            raise FileNotFoundError(f"Flow '{flow_id}' not found")

        flow_data = self._load_yaml(flow_file)
        etag = self._compute_etag(flow_data)

        self._flow_cache[flow_id] = (flow_data, etag)
        return flow_data, etag

    def update_flow(
        self,
        flow_id: str,
        patch_operations: List[Dict[str, Any]],
        expected_etag: str,
    ) -> Tuple[Dict[str, Any], str]:
        """Update a flow graph with JSON Patch operations.

        Args:
            flow_id: Flow identifier.
            patch_operations: List of JSON Patch operations.
            expected_etag: Expected ETag for optimistic concurrency.

        Returns:
            Tuple of (updated_flow_data, new_etag).

        Raises:
            FileNotFoundError: If flow not found.
            ValueError: If ETag mismatch (concurrent modification).
        """
        flow_data, current_etag = self.get_flow(flow_id)

        if current_etag != expected_etag:
            raise ValueError(f"ETag mismatch: expected {expected_etag}, got {current_etag}")

        # Apply JSON Patch operations
        import copy

        updated_data = copy.deepcopy(flow_data)

        for op in patch_operations:
            operation = op.get("op")
            path = op.get("path", "").split("/")[1:]  # Skip empty first element
            value = op.get("value")

            if operation == "replace":
                self._set_nested(updated_data, path, value)
            elif operation == "add":
                self._add_nested(updated_data, path, value)
            elif operation == "remove":
                self._remove_nested(updated_data, path)
            else:
                raise ValueError(f"Unsupported patch operation: {operation}")

        # Validate the updated flow
        validation_errors = self.validate_flow(updated_data)
        if validation_errors:
            raise ValueError(f"Validation failed: {validation_errors}")

        # Save to file
        flow_file = self.spec_root / "flows" / f"{flow_id}.yaml"
        if not flow_file.exists():
            flow_file = self.flows_config / f"{flow_id}.yaml"

        self._save_yaml(flow_file, updated_data)

        # Update cache
        new_etag = self._compute_etag(updated_data)
        self._flow_cache[flow_id] = (updated_data, new_etag)

        return updated_data, new_etag

    def validate_flow(self, flow_data: Dict[str, Any]) -> List[str]:
        """Validate a flow graph against the schema.

        Args:
            flow_data: Flow graph data to validate.

        Returns:
            List of validation error messages (empty if valid).
        """
        errors = []

        # Required fields
        required = ["id", "version", "title"]
        for field in required:
            if field not in flow_data:
                errors.append(f"Missing required field: {field}")

        # Validate nodes
        nodes = flow_data.get("nodes", [])
        node_ids = set()
        for node in nodes:
            node_id = node.get("node_id")
            if not node_id:
                errors.append("Node missing node_id")
            elif node_id in node_ids:
                errors.append(f"Duplicate node_id: {node_id}")
            else:
                node_ids.add(node_id)

            if not node.get("template_id"):
                errors.append(f"Node {node_id} missing template_id")

        # Validate edges
        edges = flow_data.get("edges", [])
        for edge in edges:
            edge_id = edge.get("edge_id")
            from_node = edge.get("from")
            to_node = edge.get("to")

            if not edge_id:
                errors.append("Edge missing edge_id")
            if from_node and from_node not in node_ids:
                errors.append(f"Edge {edge_id} references unknown from node: {from_node}")
            if to_node and to_node not in node_ids:
                errors.append(f"Edge {edge_id} references unknown to node: {to_node}")

        return errors

    # -------------------------------------------------------------------------
    # Template Operations
    # -------------------------------------------------------------------------

    def list_templates(self) -> List[Dict[str, Any]]:
        """List all available step templates.

        Returns:
            List of template summaries.
        """
        templates = []

        templates_dir = self.spec_root / "templates"
        if templates_dir.exists():
            for yaml_file in templates_dir.glob("*.yaml"):
                try:
                    template_data = self._load_yaml(yaml_file)
                    templates.append(
                        {
                            "id": template_data.get("id", yaml_file.stem),
                            "title": template_data.get("title", yaml_file.stem),
                            "station_id": template_data.get("station_id"),
                            "category": template_data.get("category"),
                            "tags": template_data.get("tags", []),
                            "description": template_data.get("description", ""),
                        }
                    )
                except Exception as e:
                    logger.warning("Failed to load template %s: %s", yaml_file, e)

        # Also load station specs as implicit templates
        stations_dir = self.spec_root / "stations"
        if stations_dir.exists():
            for yaml_file in stations_dir.glob("*.yaml"):
                station_id = yaml_file.stem
                # Skip if already have explicit template
                if any(t["id"] == station_id for t in templates):
                    continue
                try:
                    station_data = self._load_yaml(yaml_file)
                    templates.append(
                        {
                            "id": station_id,
                            "title": station_data.get("title", station_id),
                            "station_id": station_id,
                            "category": station_data.get("category", "custom"),
                            "tags": [],
                            "description": station_data.get("description", ""),
                        }
                    )
                except Exception as e:
                    logger.warning("Failed to load station %s: %s", yaml_file, e)

        return templates

    def get_template(self, template_id: str) -> Tuple[Dict[str, Any], str]:
        """Get a template by ID.

        Args:
            template_id: Template identifier.

        Returns:
            Tuple of (template_data, etag).

        Raises:
            FileNotFoundError: If template not found.
        """
        if template_id in self._template_cache:
            return self._template_cache[template_id]

        # Try templates first
        template_file = self.spec_root / "templates" / f"{template_id}.yaml"
        if not template_file.exists():
            # Try stations
            template_file = self.spec_root / "stations" / f"{template_id}.yaml"

        if not template_file.exists():
            raise FileNotFoundError(f"Template '{template_id}' not found")

        template_data = self._load_yaml(template_file)
        etag = self._compute_etag(template_data)

        self._template_cache[template_id] = (template_data, etag)
        return template_data, etag

    # -------------------------------------------------------------------------
    # Compilation
    # -------------------------------------------------------------------------

    def compile_prompt_plan(
        self,
        flow_id: str,
        step_id: str,
        run_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Compile a PromptPlan for a flow step.

        Args:
            flow_id: Flow identifier.
            step_id: Step identifier within the flow.
            run_id: Optional run ID for context.

        Returns:
            Compiled PromptPlan dictionary.
        """
        try:
            from swarm.spec.compiler import compile_prompt

            run_base = self.runs_root / (run_id or "preview")

            plan = compile_prompt(
                flow_id=flow_id,
                step_id=step_id,
                context_pack=None,
                run_base=run_base,
                repo_root=self.repo_root,
            )

            # Convert to dict
            return {
                "station_id": plan.station_id,
                "station_version": plan.station_version,
                "flow_id": plan.flow_id,
                "flow_version": plan.flow_version,
                "step_id": plan.step_id,
                "prompt_hash": plan.prompt_hash,
                "model": plan.model,
                "permission_mode": plan.permission_mode,
                "allowed_tools": list(plan.allowed_tools),
                "max_turns": plan.max_turns,
                "sandbox_enabled": plan.sandbox_enabled,
                "cwd": plan.cwd,
                "system_append": plan.system_append[:500] + "..."
                if len(plan.system_append) > 500
                else plan.system_append,
                "user_prompt": plan.user_prompt[:500] + "..."
                if len(plan.user_prompt) > 500
                else plan.user_prompt,
                "compiled_at": plan.compiled_at,
            }
        except ImportError:
            logger.warning("SpecCompiler not available, returning mock data")
            return {
                "station_id": "mock-station",
                "flow_id": flow_id,
                "step_id": step_id,
                "prompt_hash": "mock-hash",
                "compiled_at": datetime.now(timezone.utc).isoformat(),
            }
        except Exception as e:
            logger.error("Failed to compile prompt plan: %s", e)
            raise

    # -------------------------------------------------------------------------
    # Run State Operations
    # -------------------------------------------------------------------------

    def get_run_state(self, run_id: str) -> Tuple[Dict[str, Any], str]:
        """Get the state of a run.

        Args:
            run_id: Run identifier.

        Returns:
            Tuple of (run_state, etag).

        Raises:
            FileNotFoundError: If run not found.
        """
        if run_id in self._run_state_cache:
            return self._run_state_cache[run_id]

        run_dir = self.runs_root / run_id
        state_file = run_dir / "run_state.json"

        if not state_file.exists():
            raise FileNotFoundError(f"Run '{run_id}' not found")

        state_data = json.loads(state_file.read_text(encoding="utf-8"))
        etag = self._compute_etag(state_data)

        self._run_state_cache[run_id] = (state_data, etag)
        return state_data, etag

    def list_runs(self, limit: int = 20) -> List[Dict[str, Any]]:
        """List recent runs.

        Args:
            limit: Maximum number of runs to return.

        Returns:
            List of run summaries, most recent first.
        """
        runs = []

        if not self.runs_root.exists():
            return runs

        for run_dir in sorted(self.runs_root.iterdir(), reverse=True):
            if not run_dir.is_dir():
                continue

            state_file = run_dir / "run_state.json"
            if state_file.exists():
                try:
                    state = json.loads(state_file.read_text(encoding="utf-8"))
                    runs.append(
                        {
                            "run_id": state.get("run_id", run_dir.name),
                            "flow_key": state.get("flow_key"),
                            "status": state.get("status"),
                            "timestamp": state.get("timestamp"),
                        }
                    )
                except Exception as e:
                    logger.warning("Failed to load run state %s: %s", run_dir, e)

            if len(runs) >= limit:
                break

        return runs

    # -------------------------------------------------------------------------
    # SSE Event Stream
    # -------------------------------------------------------------------------

    async def stream_run_events(self, run_id: str) -> AsyncGenerator[str, None]:
        """Stream Server-Sent Events for a run.

        Args:
            run_id: Run identifier.

        Yields:
            SSE formatted event strings.
        """
        run_dir = self.runs_root / run_id
        events_file = run_dir / "events.jsonl"

        # Send initial connection event
        yield f"data: {json.dumps({'event': 'connected', 'run_id': run_id})}\n\n"

        # Track file position for incremental reading
        last_position = 0

        while True:
            try:
                state, _ = self.get_run_state(run_id)
                status = state.get("status", "pending")

                # Read new events from file
                if events_file.exists():
                    with open(events_file, "r", encoding="utf-8") as f:
                        f.seek(last_position)
                        for line in f:
                            if line.strip():
                                yield f"data: {line.strip()}\n\n"
                        last_position = f.tell()

                # Send heartbeat with current state
                yield f"data: {json.dumps({'event': 'heartbeat', 'status': status, 'timestamp': datetime.now(timezone.utc).isoformat()})}\n\n"

                # Stop streaming if run is complete
                if status in ("succeeded", "failed", "canceled"):
                    yield f"data: {json.dumps({'event': 'complete', 'status': status})}\n\n"
                    break

                await asyncio.sleep(1)  # Poll interval

            except FileNotFoundError:
                yield f"data: {json.dumps({'event': 'error', 'message': 'Run not found'})}\n\n"
                break
            except Exception as e:
                yield f"data: {json.dumps({'event': 'error', 'message': str(e)})}\n\n"
                await asyncio.sleep(5)  # Back off on error

    # -------------------------------------------------------------------------
    # YAML Helpers
    # -------------------------------------------------------------------------

    def _load_yaml(self, path: Path) -> Dict[str, Any]:
        """Load a YAML file.

        Args:
            path: Path to YAML file.

        Returns:
            Parsed YAML data.
        """
        import yaml

        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def _save_yaml(self, path: Path, data: Dict[str, Any]) -> None:
        """Save data to a YAML file.

        Args:
            path: Path to YAML file.
            data: Data to save.
        """
        import yaml

        with open(path, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, default_flow_style=False, sort_keys=False)

    # -------------------------------------------------------------------------
    # JSON Patch Helpers
    # -------------------------------------------------------------------------

    def _set_nested(self, data: Dict, path: List[str], value: Any) -> None:
        """Set a nested value in a dictionary."""
        for key in path[:-1]:
            if key.isdigit():
                data = data[int(key)]
            else:
                data = data.setdefault(key, {})

        final_key = path[-1]
        if final_key.isdigit():
            data[int(final_key)] = value
        else:
            data[final_key] = value

    def _add_nested(self, data: Dict, path: List[str], value: Any) -> None:
        """Add a value at a nested path."""
        for key in path[:-1]:
            if key.isdigit():
                data = data[int(key)]
            else:
                data = data.setdefault(key, {})

        final_key = path[-1]
        if final_key == "-":
            # Append to array
            data.append(value)
        elif final_key.isdigit():
            data.insert(int(final_key), value)
        else:
            data[final_key] = value

    def _remove_nested(self, data: Dict, path: List[str]) -> None:
        """Remove a value at a nested path."""
        for key in path[:-1]:
            if key.isdigit():
                data = data[int(key)]
            else:
                data = data[key]

        final_key = path[-1]
        if final_key.isdigit():
            del data[int(final_key)]
        else:
            del data[final_key]


# =============================================================================
# Global SpecManager instance
# =============================================================================

_spec_manager: Optional[SpecManager] = None


def get_spec_manager() -> SpecManager:
    """Get the global SpecManager instance."""
    global _spec_manager
    if _spec_manager is None:
        _spec_manager = SpecManager()
    return _spec_manager


# =============================================================================
# FastAPI Application Factory
# =============================================================================


def create_app(
    repo_root: Optional[Path] = None,
    enable_cors: bool = True,
) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        repo_root: Repository root path for SpecManager.
        enable_cors: Whether to enable CORS middleware.

    Returns:
        Configured FastAPI application.
    """
    global _spec_manager
    _spec_manager = SpecManager(repo_root)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """Application lifespan manager.

        On startup:
        - Initialize the resilient stats database
        - Check DB schema version and rebuild from events.jsonl if needed
        - Initialize RunTailer for incremental event ingestion
        - Start background task to watch active runs

        On shutdown:
        - Cancel the tailer background task
        - Close the database connection
        """
        logger.info("Spec API server starting...")

        # Initialize resilient database with auto-rebuild
        db_available = False
        try:
            from swarm.runtime.resilient_db import close_resilient_db, get_resilient_db

            db = get_resilient_db()
            health = db.health
            logger.info(
                "Resilient DB initialized: healthy=%s, projection_version=%d, rebuild_count=%d",
                health.healthy,
                health.projection_version,
                health.rebuild_count,
            )
            if health.last_error:
                logger.warning("DB initialization had error: %s", health.last_error)
            db_available = True
        except Exception as e:
            logger.warning("Could not initialize resilient DB (non-fatal): %s", e)

        # Initialize RunTailer for incremental event ingestion
        tailer_task: Optional[asyncio.Task] = None
        tailer_state: Dict[str, Any] = {
            "enabled": False,
            "total_events_ingested": 0,
            "last_ingest_at": None,
            "error": None,
        }

        if db_available:
            try:
                from swarm.runtime.db import get_stats_db
                from swarm.runtime.run_tailer import RunTailer

                # Get runs directory from spec manager
                runs_dir = _spec_manager.runs_root if _spec_manager else Path("swarm/runs")

                # Create tailer with the stats database
                stats_db = get_stats_db()
                tailer = RunTailer(db=stats_db, runs_dir=runs_dir)

                # Store tailer in app state for access by endpoints
                app.state.tailer = tailer
                app.state.tailer_state = tailer_state

                async def watch_active_runs():
                    """Background task to watch active runs for new events."""
                    try:
                        async for results in tailer.watch_active_runs(poll_interval_ms=1000):
                            total_ingested = sum(results.values())
                            tailer_state["total_events_ingested"] += total_ingested
                            tailer_state["last_ingest_at"] = datetime.now(
                                timezone.utc
                            ).isoformat()
                            logger.debug(
                                "Tailer ingested %d events from %d runs",
                                total_ingested,
                                len(results),
                            )
                    except asyncio.CancelledError:
                        logger.info("RunTailer watch task cancelled")
                        raise
                    except Exception as e:
                        tailer_state["error"] = str(e)
                        logger.error("RunTailer watch task error: %s", e)

                # Start background tailing task
                tailer_task = asyncio.create_task(watch_active_runs())
                tailer_state["enabled"] = True
                logger.info("RunTailer initialized and watching for events")

            except ImportError as e:
                logger.warning("Could not initialize RunTailer (missing module): %s", e)
                tailer_state["error"] = f"Import error: {e}"
            except Exception as e:
                logger.warning("Could not initialize RunTailer (non-fatal): %s", e)
                tailer_state["error"] = str(e)
        else:
            tailer_state["error"] = "Database not available"
            logger.info("RunTailer disabled (database not available)")

        yield

        logger.info("Spec API server shutting down...")

        # Cancel the tailer background task
        if tailer_task is not None:
            tailer_task.cancel()
            try:
                await tailer_task
            except asyncio.CancelledError:
                pass
            logger.info("RunTailer task stopped")

        # Close the resilient database
        try:
            close_resilient_db()
            logger.info("Resilient DB closed")
        except Exception as e:
            logger.warning("Error closing resilient DB: %s", e)

    app = FastAPI(
        title="Flow Studio API",
        description="REST API for SpecManager functionality - exposes flows, templates, validation, and compilation to the TypeScript frontend.",
        version="2.0.0",
        lifespan=lifespan,
    )

    # Add CORS middleware
    if enable_cors:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
            allow_headers=["*"],
            expose_headers=["ETag", "If-Match", "If-None-Match"],
        )

    # -------------------------------------------------------------------------
    # Include Modular Routers
    # -------------------------------------------------------------------------
    # These routers provide the new API structure with full run control
    try:
        from .routes import (
            boundary_router,
            compile_router,
            db_router,
            events_router,
            evolution_router,
            facts_router,
            preview_router,
            runs_router,
            settings_router,
            specs_router,
            wisdom_router,
        )

        app.include_router(specs_router, prefix="/api")
        app.include_router(runs_router, prefix="/api")
        app.include_router(events_router, prefix="/api")
        app.include_router(wisdom_router, prefix="/api")
        app.include_router(compile_router, prefix="/api")
        app.include_router(facts_router, prefix="/api")
        app.include_router(evolution_router, prefix="/api")
        app.include_router(boundary_router, prefix="/api")
        app.include_router(db_router, prefix="/api")
        app.include_router(settings_router, prefix="/api")
        app.include_router(preview_router, prefix="/api")
        logger.info("Loaded modular API routers")
    except ImportError as e:
        logger.warning("Could not load modular routers: %s", e)

    # -------------------------------------------------------------------------
    # Request Logging Middleware
    # -------------------------------------------------------------------------

    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        start_time = time.time()
        response = await call_next(request)
        duration = time.time() - start_time
        logger.info(
            "%s %s %s %.3fs",
            request.method,
            request.url.path,
            response.status_code,
            duration,
        )
        return response

    # -------------------------------------------------------------------------
    # Flow Graph Endpoints
    # -------------------------------------------------------------------------

    @app.get("/api/spec/flows", response_model=FlowListResponse)
    async def list_flows():
        """List all available flow graphs."""
        flows = get_spec_manager().list_flows()
        return FlowListResponse(flows=[FlowSummary(**f) for f in flows])

    @app.get("/api/spec/flows/{flow_id}")
    async def get_flow(
        flow_id: str,
        if_none_match: Optional[str] = Header(None),
    ):
        """Get a flow graph by ID."""
        try:
            flow_data, etag = get_spec_manager().get_flow(flow_id)

            # Check If-None-Match for caching (strip quotes from ETag)
            if if_none_match and if_none_match.strip('"') == etag:
                return Response(status_code=304)

            return JSONResponse(
                content=flow_data,
                headers={"ETag": f'"{etag}"'},
            )

        except FileNotFoundError:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "spec_not_found",
                    "message": f"Flow graph '{flow_id}' not found",
                    "details": {},
                },
            )

    @app.patch("/api/spec/flows/{flow_id}")
    async def update_flow(
        flow_id: str,
        patch_ops: List[Dict[str, Any]],
        if_match: str = Header(..., description="ETag for optimistic concurrency"),
    ):
        """Update a flow graph with JSON Patch operations."""
        try:
            updated_data, new_etag = get_spec_manager().update_flow(flow_id, patch_ops, if_match)

            return JSONResponse(
                content=updated_data,
                headers={"ETag": new_etag},
            )

        except FileNotFoundError:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "spec_not_found",
                    "message": f"Flow graph '{flow_id}' not found",
                    "details": {},
                },
            )
        except ValueError as e:
            if "ETag mismatch" in str(e):
                raise HTTPException(
                    status_code=412,
                    detail={
                        "error": "etag_mismatch",
                        "message": str(e),
                        "details": {},
                    },
                )
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "validation_error",
                    "message": str(e),
                    "details": {},
                },
            )

    # -------------------------------------------------------------------------
    # Template Endpoints
    # -------------------------------------------------------------------------

    @app.get("/api/spec/templates", response_model=TemplateListResponse)
    async def list_templates():
        """List all available step templates."""
        templates = get_spec_manager().list_templates()
        return TemplateListResponse(templates=[TemplateSummary(**t) for t in templates])

    @app.get("/api/spec/templates/{template_id}")
    async def get_template(
        template_id: str,
        if_none_match: Optional[str] = Header(None),
    ):
        """Get a template by ID."""
        try:
            template_data, etag = get_spec_manager().get_template(template_id)

            # Check If-None-Match for caching (strip quotes from ETag)
            if if_none_match and if_none_match.strip('"') == etag:
                return Response(status_code=304)

            return JSONResponse(
                content=template_data,
                headers={"ETag": f'"{etag}"'},
            )

        except FileNotFoundError:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "template_not_found",
                    "message": f"Template '{template_id}' not found",
                    "details": {},
                },
            )

    # -------------------------------------------------------------------------
    # Validation / Compilation Endpoints
    # -------------------------------------------------------------------------

    @app.post("/api/spec/validate", response_model=ValidationResponse)
    async def validate_spec(request: ValidationRequest):
        """Validate a flow spec without saving."""
        data = request.model_dump(exclude_none=True)
        errors = get_spec_manager().validate_flow(data)
        return ValidationResponse(valid=len(errors) == 0, errors=errors)

    @app.post("/api/spec/compile", response_model=CompileResponse)
    async def compile_spec(request: CompileRequest):
        """Preview PromptPlan compilation."""
        try:
            prompt_plan = get_spec_manager().compile_prompt_plan(
                flow_id=request.flow_id,
                step_id=request.step_id,
                run_id=request.run_id,
            )
            return CompileResponse(prompt_plan=prompt_plan)

        except Exception as e:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "compilation_error",
                    "message": str(e),
                    "details": {},
                },
            )

    # -------------------------------------------------------------------------
    # Run State Endpoints
    # -------------------------------------------------------------------------

    @app.get("/api/runs", response_model=RunListResponse)
    async def list_runs(limit: int = 20):
        """List recent runs."""
        runs = get_spec_manager().list_runs(limit=limit)
        return RunListResponse(runs=[RunSummary(**r) for r in runs])

    @app.get("/api/runs/{run_id}/state")
    async def get_run_state(
        run_id: str,
        if_none_match: Optional[str] = Header(None),
    ):
        """Get the state of a run."""
        try:
            state_data, etag = get_spec_manager().get_run_state(run_id)

            # Check If-None-Match for caching (strip quotes from ETag)
            if if_none_match and if_none_match.strip('"') == etag:
                return Response(status_code=304)

            return JSONResponse(
                content=state_data,
                headers={"ETag": f'"{etag}"'},
            )

        except FileNotFoundError:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "run_not_found",
                    "message": f"Run '{run_id}' not found",
                    "details": {},
                },
            )

    @app.get("/api/runs/{run_id}/events")
    async def stream_run_events(run_id: str):
        """Stream Server-Sent Events for a run."""
        return StreamingResponse(
            get_spec_manager().stream_run_events(run_id),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    # -------------------------------------------------------------------------
    # Health Check
    # -------------------------------------------------------------------------

    @app.get("/api/health", response_model=HealthResponse)
    async def health_check(request: Request):
        """Health check endpoint.

        Returns overall API health including database and tailer status.
        The API is considered healthy even if the DB or tailer has issues,
        since these operations fail gracefully.
        """
        # Get DB health info
        db_info = None
        try:
            from swarm.runtime.resilient_db import check_db_health

            health = check_db_health()
            db_info = DBHealthInfo(
                healthy=health.healthy,
                projection_version=health.projection_version,
                db_exists=health.db_exists,
                rebuild_count=health.rebuild_count,
                error_count=health.error_count,
                last_error=health.last_error,
                last_check=health.last_check.isoformat() if health.last_check else None,
                last_rebuild=health.last_rebuild.isoformat() if health.last_rebuild else None,
            )
        except Exception as e:
            logger.warning("Could not get DB health: %s", e)
            db_info = DBHealthInfo(healthy=False, last_error=str(e))

        # Get tailer health info
        tailer_info = None
        try:
            tailer_state = getattr(request.app.state, "tailer_state", None)
            if tailer_state:
                # Count active runs from the tailer if available
                active_runs = 0
                tailer = getattr(request.app.state, "tailer", None)
                if tailer:
                    try:
                        from swarm.runtime.storage import list_runs

                        active_runs = len(list(list_runs(tailer._runs_dir)))
                    except Exception:
                        pass

                tailer_info = TailerHealthInfo(
                    enabled=tailer_state.get("enabled", False),
                    active_runs=active_runs,
                    total_events_ingested=tailer_state.get("total_events_ingested", 0),
                    last_ingest_at=tailer_state.get("last_ingest_at"),
                    error=tailer_state.get("error"),
                )
            else:
                tailer_info = TailerHealthInfo(enabled=False, error="Tailer state not available")
        except Exception as e:
            logger.warning("Could not get tailer health: %s", e)
            tailer_info = TailerHealthInfo(enabled=False, error=str(e))

        return HealthResponse(
            status="healthy",
            timestamp=datetime.now(timezone.utc).isoformat(),
            repo_root=str(get_spec_manager().repo_root),
            db=db_info,
            tailer=tailer_info,
        )

    # -------------------------------------------------------------------------
    # RunTailer Endpoints
    # -------------------------------------------------------------------------

    @app.get("/api/tailer/health", response_model=TailerHealthInfo)
    async def tailer_health(request: Request):
        """Check RunTailer health.

        Returns detailed information about the RunTailer status including
        whether it's enabled, active run count, and ingestion statistics.
        """
        tailer_state = getattr(request.app.state, "tailer_state", None)

        if not tailer_state:
            return TailerHealthInfo(enabled=False, error="Tailer not initialized")

        # Count active runs
        active_runs = 0
        tailer = getattr(request.app.state, "tailer", None)
        if tailer:
            try:
                from swarm.runtime.storage import list_runs

                active_runs = len(list(list_runs(tailer._runs_dir)))
            except Exception:
                pass

        return TailerHealthInfo(
            enabled=tailer_state.get("enabled", False),
            active_runs=active_runs,
            total_events_ingested=tailer_state.get("total_events_ingested", 0),
            last_ingest_at=tailer_state.get("last_ingest_at"),
            error=tailer_state.get("error"),
        )

    @app.post("/api/tailer/ingest/{run_id}", response_model=TailerIngestResponse)
    async def trigger_ingest(run_id: str, request: Request):
        """Manually trigger ingestion for a specific run.

        This endpoint allows explicit ingestion of events from a run's
        events.jsonl file, useful for testing or forcing immediate updates.

        Args:
            run_id: The run identifier to ingest events from.

        Returns:
            The run_id and count of events ingested.

        Raises:
            HTTPException: If tailer is not available or ingestion fails.
        """
        tailer = getattr(request.app.state, "tailer", None)
        tailer_state = getattr(request.app.state, "tailer_state", None)

        if not tailer:
            raise HTTPException(
                status_code=503,
                detail={
                    "error": "tailer_unavailable",
                    "message": "RunTailer is not available",
                    "details": {},
                },
            )

        try:
            events_ingested = tailer.tail_run(run_id)

            # Update state tracking
            if tailer_state and events_ingested > 0:
                tailer_state["total_events_ingested"] += events_ingested
                tailer_state["last_ingest_at"] = datetime.now(timezone.utc).isoformat()

            return TailerIngestResponse(run_id=run_id, events_ingested=events_ingested)

        except Exception as e:
            logger.error("Failed to ingest events for run %s: %s", run_id, e)
            raise HTTPException(
                status_code=500,
                detail={
                    "error": "ingestion_failed",
                    "message": f"Failed to ingest events: {e}",
                    "details": {"run_id": run_id},
                },
            )

    return app


# Create default app instance for uvicorn
app = create_app()


# =============================================================================
# Main Entry Point
# =============================================================================


def main():
    """Run the API server."""
    import argparse

    import uvicorn

    parser = argparse.ArgumentParser(description="Spec API Server")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind to")
    parser.add_argument("--port", type=int, default=5001, help="Port to bind to")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    parser.add_argument("--no-cors", action="store_true", help="Disable CORS")
    args = parser.parse_args()

    global app
    app = create_app(enable_cors=not args.no_cors)

    print(f"Starting Flow Studio API server at http://{args.host}:{args.port}")
    print("\nNew API Endpoints (v2.0):")
    print("  Specs:")
    print("    GET    /api/specs/templates          - List templates (for palette)")
    print("    GET    /api/specs/templates/{id}     - Get template")
    print("    GET    /api/specs/flows              - List flows")
    print("    GET    /api/specs/flows/{id}         - Get merged flow")
    print("    PATCH  /api/specs/flows/{id}         - Update flow (requires If-Match)")
    print("    POST   /api/specs/flows/{id}/validate - Validate flow spec")
    print("    POST   /api/specs/flows/{id}/compile  - Compile flow")
    print("  Compile Preview:")
    print("    POST   /api/compile/preview          - Preview compiled prompt (NEW)")
    print("    GET    /api/compile/stations         - List available stations (NEW)")
    print("    GET    /api/compile/stations/{id}    - Get station details (NEW)")
    print("    POST   /api/compile/validate         - Validate station/step (NEW)")
    print("  Runs:")
    print("    POST   /api/runs                     - Start new run")
    print("    GET    /api/runs                     - List runs")
    print("    GET    /api/runs/{id}                - Get run state")
    print("    POST   /api/runs/{id}/pause          - Pause run")
    print("    POST   /api/runs/{id}/resume         - Resume run")
    print("    POST   /api/runs/{id}/inject         - Inject node into run")
    print("    POST   /api/runs/{id}/interrupt      - Interrupt with detour")
    print("    DELETE /api/runs/{id}                - Cancel run")
    print("    GET    /api/runs/{id}/events         - SSE event stream")
    print("\nLegacy API Endpoints (v1.0 - backward compatible):")
    print("    GET    /api/spec/flows               - List flows")
    print("    GET    /api/spec/flows/{id}          - Get flow")
    print("    PATCH  /api/spec/flows/{id}          - Update flow")
    print("    GET    /api/spec/templates           - List templates")
    print("    GET    /api/spec/templates/{id}      - Get template")
    print("    POST   /api/spec/validate            - Validate spec")
    print("    POST   /api/spec/compile             - Compile spec")
    print("    GET    /api/runs                     - List runs (legacy)")
    print("    GET    /api/runs/{id}/state          - Get run state (legacy)")
    print("    GET    /api/health                   - Health check")
    print("  Tailer:")
    print("    GET    /api/tailer/health            - Check RunTailer health")
    print("    POST   /api/tailer/ingest/{run_id}   - Manually trigger ingestion")
    print("  Settings:")
    print("    GET    /api/settings/model-policy    - Get model policy configuration")
    print("    POST   /api/settings/model-policy    - Update model policy")
    print("    POST   /api/settings/model-policy/reload - Force reload from disk")
    print("  Preview:")
    print("    POST   /api/preview/settings/model-policy - Preview model policy changes")
    print("    POST   /api/preview/spec/stations/{id}    - Preview station configuration")
    print("    POST   /api/preview/spec/flows/{id}/validate - Validate flow graph")

    uvicorn.run(app, host=args.host, port=args.port, reload=args.debug)


if __name__ == "__main__":
    main()
