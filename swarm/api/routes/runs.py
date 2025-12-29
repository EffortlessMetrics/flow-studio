"""
Run control endpoints for Flow Studio API.

Provides REST endpoints for:
- Starting new runs
- Getting run state
- Pausing/resuming runs
- Injecting nodes into runs
- Interrupting runs with detours
- Canceling runs
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Header, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/runs", tags=["runs"])


# =============================================================================
# Pydantic Models
# =============================================================================


class RunStartRequest(BaseModel):
    """Request to start a new run."""

    flow_id: str = Field(..., description="Flow to execute")
    run_id: Optional[str] = Field(None, description="Custom run ID (generated if not provided)")
    context: Optional[Dict[str, Any]] = Field(None, description="Initial context for the run")
    start_step: Optional[str] = Field(None, description="Step to start from (defaults to first)")
    mode: str = Field("execute", description="Execution mode: execute, preview, validate")


class RunStartResponse(BaseModel):
    """Response when starting a new run."""

    run_id: str
    flow_id: str
    status: str
    created_at: str
    events_url: str


class RunSummary(BaseModel):
    """Run summary for list endpoint."""

    run_id: str
    flow_key: Optional[str] = None
    status: Optional[str] = None
    timestamp: Optional[str] = None


class RunListResponse(BaseModel):
    """Response for list runs endpoint."""

    runs: List[RunSummary]


class RunState(BaseModel):
    """Full run state."""

    run_id: str
    flow_id: str
    status: str
    current_step: Optional[str] = None
    completed_steps: List[str] = Field(default_factory=list)
    pending_steps: List[str] = Field(default_factory=list)
    context: Dict[str, Any] = Field(default_factory=dict)
    created_at: str
    updated_at: str
    paused_at: Optional[str] = None
    completed_at: Optional[str] = None
    error: Optional[str] = None


class RunActionResponse(BaseModel):
    """Generic response for run actions."""

    run_id: str
    status: str
    message: str
    timestamp: str


class InjectRequest(BaseModel):
    """Request to inject a node into a run."""

    step_id: str = Field(..., description="ID for the injected step")
    station_id: str = Field(..., description="Station to use for the step")
    position: str = Field("next", description="Where to inject: next, after:<step_id>, before:<step_id>")
    params: Optional[Dict[str, Any]] = Field(None, description="Parameters for the step")


class InterruptRequest(BaseModel):
    """Request to interrupt a run with a detour."""

    detour_flow: Optional[str] = Field(None, description="Flow to execute as detour")
    detour_steps: Optional[List[str]] = Field(None, description="Specific steps to execute as detour")
    reason: str = Field(..., description="Reason for the interrupt")
    resume_after: bool = Field(True, description="Whether to resume original flow after detour")


# =============================================================================
# Run State Management
# =============================================================================


class RunStateManager:
    """Manages run state in memory and on disk.

    In-memory cache for fast access, with disk persistence for durability.
    """

    def __init__(self, runs_root: Path):
        self.runs_root = runs_root
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._locks: Dict[str, asyncio.Lock] = {}

    def _get_lock(self, run_id: str) -> asyncio.Lock:
        """Get or create a lock for a run."""
        if run_id not in self._locks:
            self._locks[run_id] = asyncio.Lock()
        return self._locks[run_id]

    def _compute_etag(self, state: Dict[str, Any]) -> str:
        """Compute ETag from state."""
        content = json.dumps(state, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    def _state_path(self, run_id: str) -> Path:
        """Get path to run state file."""
        return self.runs_root / run_id / "run_state.json"

    async def create_run(
        self,
        flow_id: str,
        run_id: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        start_step: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a new run."""
        if run_id is None:
            run_id = f"{flow_id}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"

        now = datetime.now(timezone.utc).isoformat()

        state = {
            "run_id": run_id,
            "flow_id": flow_id,
            "status": "pending",
            "current_step": start_step,
            "completed_steps": [],
            "pending_steps": [],
            "context": context or {},
            "created_at": now,
            "updated_at": now,
            "paused_at": None,
            "completed_at": None,
            "error": None,
        }

        # Create run directory
        run_dir = self.runs_root / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        # Save state
        await self._save_state(run_id, state)

        return state

    def _get_run_unlocked(self, run_id: str) -> tuple[Dict[str, Any], str]:
        """Get run state without locking (internal use only)."""
        # Check cache first
        if run_id in self._cache:
            state = self._cache[run_id]
            return state, self._compute_etag(state)

        # Load from disk
        state_path = self._state_path(run_id)
        if not state_path.exists():
            raise FileNotFoundError(f"Run '{run_id}' not found")

        state = json.loads(state_path.read_text(encoding="utf-8"))
        self._cache[run_id] = state
        return state, self._compute_etag(state)

    async def get_run(self, run_id: str) -> tuple[Dict[str, Any], str]:
        """Get run state with ETag."""
        async with self._get_lock(run_id):
            return self._get_run_unlocked(run_id)

    async def update_run(
        self,
        run_id: str,
        updates: Dict[str, Any],
        expected_etag: Optional[str] = None,
    ) -> tuple[Dict[str, Any], str]:
        """Update run state with optional ETag check."""
        async with self._get_lock(run_id):
            state, current_etag = self._get_run_unlocked(run_id)

            if expected_etag and expected_etag != current_etag:
                raise ValueError(f"ETag mismatch: expected {expected_etag}, got {current_etag}")

            # Apply updates
            state.update(updates)
            state["updated_at"] = datetime.now(timezone.utc).isoformat()

            await self._save_state(run_id, state)
            return state, self._compute_etag(state)

    async def _save_state(self, run_id: str, state: Dict[str, Any]) -> None:
        """Save state to disk and cache."""
        state_path = self._state_path(run_id)
        state_path.parent.mkdir(parents=True, exist_ok=True)

        # Write atomically
        tmp_path = state_path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
        os.replace(tmp_path, state_path)

        self._cache[run_id] = state

    def list_runs(self, limit: int = 20) -> List[Dict[str, Any]]:
        """List recent runs."""
        runs = []

        if not self.runs_root.exists():
            return runs

        # Get directories sorted by modification time
        run_dirs = []
        for item in self.runs_root.iterdir():
            if item.is_dir() and (item / "run_state.json").exists():
                run_dirs.append((item.stat().st_mtime, item))

        run_dirs.sort(key=lambda x: x[0], reverse=True)

        for _, run_dir in run_dirs[:limit]:
            state_path = run_dir / "run_state.json"
            try:
                state = json.loads(state_path.read_text(encoding="utf-8"))
                runs.append({
                    "run_id": state.get("run_id", run_dir.name),
                    "flow_key": state.get("flow_id", "").split("-")[-1] if state.get("flow_id") else None,
                    "status": state.get("status"),
                    "timestamp": state.get("created_at"),
                })
            except Exception as e:
                logger.warning("Failed to load run state %s: %s", run_dir, e)

        return runs


# Global state manager (initialized on first use)
_state_manager: Optional[RunStateManager] = None


def _get_state_manager() -> RunStateManager:
    """Get or create the global state manager."""
    global _state_manager
    if _state_manager is None:
        from ..server import get_spec_manager

        manager = get_spec_manager()
        _state_manager = RunStateManager(manager.runs_root)
    return _state_manager


# =============================================================================
# Run Endpoints
# =============================================================================


@router.post("", response_model=RunStartResponse, status_code=201)
async def start_run(request: RunStartRequest):
    """Start a new run.

    Creates a new run directory and initializes run state.
    Returns the run ID and SSE events URL.

    Args:
        request: Run start request with flow_id and optional parameters.

    Returns:
        RunStartResponse with run_id and events_url.
    """
    state_manager = _get_state_manager()

    try:
        state = await state_manager.create_run(
            flow_id=request.flow_id,
            run_id=request.run_id,
            context=request.context,
            start_step=request.start_step,
        )

        return RunStartResponse(
            run_id=state["run_id"],
            flow_id=state["flow_id"],
            status=state["status"],
            created_at=state["created_at"],
            events_url=f"/api/runs/{state['run_id']}/events",
        )

    except Exception as e:
        logger.error("Failed to start run: %s", e)
        raise HTTPException(
            status_code=500,
            detail={
                "error": "run_start_failed",
                "message": str(e),
                "details": {},
            },
        )


@router.get("", response_model=RunListResponse)
async def list_runs(limit: int = 20):
    """List recent runs.

    Args:
        limit: Maximum number of runs to return.

    Returns:
        List of run summaries.
    """
    state_manager = _get_state_manager()
    runs = state_manager.list_runs(limit=limit)
    return RunListResponse(runs=[RunSummary(**r) for r in runs])


@router.get("/{run_id}")
async def get_run(
    run_id: str,
    if_none_match: Optional[str] = Header(None, alias="If-None-Match"),
):
    """Get run state.

    Args:
        run_id: Run identifier.
        if_none_match: Optional ETag for caching.

    Returns:
        Run state with ETag header.

    Raises:
        404: Run not found.
        304: Not modified (if ETag matches).
    """
    state_manager = _get_state_manager()

    try:
        state, etag = await state_manager.get_run(run_id)

        # Check If-None-Match for caching
        if if_none_match and if_none_match.strip('"') == etag:
            return Response(status_code=304)

        return JSONResponse(
            content=state,
            headers={"ETag": f'"{etag}"'},
        )

    except FileNotFoundError:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "run_not_found",
                "message": f"Run '{run_id}' not found",
                "details": {"run_id": run_id},
            },
        )


@router.post("/{run_id}/pause", response_model=RunActionResponse)
async def pause_run(
    run_id: str,
    if_match: Optional[str] = Header(None, alias="If-Match"),
):
    """Pause a running run.

    Pauses execution at the current step. The run can be resumed later.

    Args:
        run_id: Run identifier.
        if_match: Optional ETag for concurrency control.

    Returns:
        Action response with new status.

    Raises:
        404: Run not found.
        409: Run is not in a pausable state.
        412: ETag mismatch.
    """
    state_manager = _get_state_manager()
    expected_etag = if_match.strip('"') if if_match else None

    try:
        state, _ = await state_manager.get_run(run_id)

        if state["status"] not in ("running", "pending"):
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "invalid_state",
                    "message": f"Cannot pause run with status '{state['status']}'",
                    "details": {"current_status": state["status"]},
                },
            )

        now = datetime.now(timezone.utc).isoformat()
        await state_manager.update_run(
            run_id,
            {"status": "paused", "paused_at": now},
            expected_etag=expected_etag,
        )

        return RunActionResponse(
            run_id=run_id,
            status="paused",
            message="Run paused successfully",
            timestamp=now,
        )

    except FileNotFoundError:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "run_not_found",
                "message": f"Run '{run_id}' not found",
                "details": {"run_id": run_id},
            },
        )
    except ValueError as e:
        if "ETag mismatch" in str(e):
            raise HTTPException(
                status_code=412,
                detail={
                    "error": "etag_mismatch",
                    "message": "Run was modified by another request",
                    "details": {},
                },
            )
        raise


@router.post("/{run_id}/resume", response_model=RunActionResponse)
async def resume_run(
    run_id: str,
    if_match: Optional[str] = Header(None, alias="If-Match"),
):
    """Resume a paused run.

    Continues execution from where it was paused.

    Args:
        run_id: Run identifier.
        if_match: Optional ETag for concurrency control.

    Returns:
        Action response with new status.

    Raises:
        404: Run not found.
        409: Run is not paused.
        412: ETag mismatch.
    """
    state_manager = _get_state_manager()
    expected_etag = if_match.strip('"') if if_match else None

    try:
        state, _ = await state_manager.get_run(run_id)

        if state["status"] != "paused":
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "invalid_state",
                    "message": f"Cannot resume run with status '{state['status']}'",
                    "details": {"current_status": state["status"]},
                },
            )

        now = datetime.now(timezone.utc).isoformat()
        await state_manager.update_run(
            run_id,
            {"status": "running", "paused_at": None},
            expected_etag=expected_etag,
        )

        return RunActionResponse(
            run_id=run_id,
            status="running",
            message="Run resumed successfully",
            timestamp=now,
        )

    except FileNotFoundError:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "run_not_found",
                "message": f"Run '{run_id}' not found",
                "details": {"run_id": run_id},
            },
        )
    except ValueError as e:
        if "ETag mismatch" in str(e):
            raise HTTPException(
                status_code=412,
                detail={
                    "error": "etag_mismatch",
                    "message": "Run was modified by another request",
                    "details": {},
                },
            )
        raise


@router.post("/{run_id}/inject", response_model=RunActionResponse)
async def inject_node(
    run_id: str,
    request: InjectRequest,
    if_match: Optional[str] = Header(None, alias="If-Match"),
):
    """Inject a node into a run.

    Inserts a new step into the run's execution plan. The step will be
    executed at the specified position.

    Args:
        run_id: Run identifier.
        request: Inject request with step details.
        if_match: Optional ETag for concurrency control.

    Returns:
        Action response confirming injection.

    Raises:
        404: Run not found.
        409: Run is not in an injectable state.
        412: ETag mismatch.
    """
    state_manager = _get_state_manager()
    expected_etag = if_match.strip('"') if if_match else None

    try:
        state, _ = await state_manager.get_run(run_id)

        if state["status"] not in ("pending", "running", "paused"):
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "invalid_state",
                    "message": f"Cannot inject into run with status '{state['status']}'",
                    "details": {"current_status": state["status"]},
                },
            )

        # Add injected step to pending steps
        pending = state.get("pending_steps", [])

        if request.position == "next":
            # Insert at beginning of pending
            pending.insert(0, request.step_id)
        elif request.position.startswith("after:"):
            target = request.position[6:]
            try:
                idx = pending.index(target) + 1
                pending.insert(idx, request.step_id)
            except ValueError:
                # Target not in pending, insert at end
                pending.append(request.step_id)
        elif request.position.startswith("before:"):
            target = request.position[7:]
            try:
                idx = pending.index(target)
                pending.insert(idx, request.step_id)
            except ValueError:
                # Target not in pending, insert at beginning
                pending.insert(0, request.step_id)
        else:
            pending.append(request.step_id)

        # Store injection metadata
        injections = state.get("context", {}).get("injections", [])
        injections.append({
            "step_id": request.step_id,
            "station_id": request.station_id,
            "position": request.position,
            "params": request.params,
            "injected_at": datetime.now(timezone.utc).isoformat(),
        })

        now = datetime.now(timezone.utc).isoformat()
        context = state.get("context", {})
        context["injections"] = injections

        await state_manager.update_run(
            run_id,
            {"pending_steps": pending, "context": context},
            expected_etag=expected_etag,
        )

        return RunActionResponse(
            run_id=run_id,
            status=state["status"],
            message=f"Step '{request.step_id}' injected at position '{request.position}'",
            timestamp=now,
        )

    except FileNotFoundError:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "run_not_found",
                "message": f"Run '{run_id}' not found",
                "details": {"run_id": run_id},
            },
        )
    except ValueError as e:
        if "ETag mismatch" in str(e):
            raise HTTPException(
                status_code=412,
                detail={
                    "error": "etag_mismatch",
                    "message": "Run was modified by another request",
                    "details": {},
                },
            )
        raise


@router.post("/{run_id}/interrupt", response_model=RunActionResponse)
async def interrupt_run(
    run_id: str,
    request: InterruptRequest,
    if_match: Optional[str] = Header(None, alias="If-Match"),
):
    """Interrupt a run with a detour.

    Pauses the current run and optionally executes a detour flow/steps
    before resuming.

    Args:
        run_id: Run identifier.
        request: Interrupt request with detour details.
        if_match: Optional ETag for concurrency control.

    Returns:
        Action response with interrupt details.

    Raises:
        404: Run not found.
        409: Run is not in an interruptible state.
        412: ETag mismatch.
    """
    state_manager = _get_state_manager()
    expected_etag = if_match.strip('"') if if_match else None

    try:
        state, _ = await state_manager.get_run(run_id)

        if state["status"] not in ("pending", "running"):
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "invalid_state",
                    "message": f"Cannot interrupt run with status '{state['status']}'",
                    "details": {"current_status": state["status"]},
                },
            )

        now = datetime.now(timezone.utc).isoformat()

        # Store interrupt details in context
        context = state.get("context", {})
        context["interrupt"] = {
            "reason": request.reason,
            "detour_flow": request.detour_flow,
            "detour_steps": request.detour_steps,
            "resume_after": request.resume_after,
            "interrupted_at": now,
            "interrupted_step": state.get("current_step"),
        }

        await state_manager.update_run(
            run_id,
            {
                "status": "interrupted",
                "paused_at": now,
                "context": context,
            },
            expected_etag=expected_etag,
        )

        return RunActionResponse(
            run_id=run_id,
            status="interrupted",
            message=f"Run interrupted: {request.reason}",
            timestamp=now,
        )

    except FileNotFoundError:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "run_not_found",
                "message": f"Run '{run_id}' not found",
                "details": {"run_id": run_id},
            },
        )
    except ValueError as e:
        if "ETag mismatch" in str(e):
            raise HTTPException(
                status_code=412,
                detail={
                    "error": "etag_mismatch",
                    "message": "Run was modified by another request",
                    "details": {},
                },
            )
        raise


@router.delete("/{run_id}", response_model=RunActionResponse)
async def cancel_run(
    run_id: str,
    if_match: Optional[str] = Header(None, alias="If-Match"),
):
    """Cancel a run.

    Terminates the run and marks it as canceled. This is irreversible.

    Args:
        run_id: Run identifier.
        if_match: Optional ETag for concurrency control.

    Returns:
        Action response confirming cancellation.

    Raises:
        404: Run not found.
        409: Run is already completed.
        412: ETag mismatch.
    """
    state_manager = _get_state_manager()
    expected_etag = if_match.strip('"') if if_match else None

    try:
        state, _ = await state_manager.get_run(run_id)

        if state["status"] in ("succeeded", "failed", "canceled"):
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "invalid_state",
                    "message": f"Cannot cancel run with status '{state['status']}'",
                    "details": {"current_status": state["status"]},
                },
            )

        now = datetime.now(timezone.utc).isoformat()
        await state_manager.update_run(
            run_id,
            {"status": "canceled", "completed_at": now},
            expected_etag=expected_etag,
        )

        return RunActionResponse(
            run_id=run_id,
            status="canceled",
            message="Run canceled successfully",
            timestamp=now,
        )

    except FileNotFoundError:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "run_not_found",
                "message": f"Run '{run_id}' not found",
                "details": {"run_id": run_id},
            },
        )
    except ValueError as e:
        if "ETag mismatch" in str(e):
            raise HTTPException(
                status_code=412,
                detail={
                    "error": "etag_mismatch",
                    "message": "Run was modified by another request",
                    "details": {},
                },
            )
        raise
