"""
Evolution endpoints for Flow Studio API.

Provides REST endpoints for:
- Listing pending evolution patches from Wisdom outputs
- Validating evolution patches before application
- Applying evolution patches to spec files
- Rejecting patches with documented reasons
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/evolution", tags=["evolution"])


# =============================================================================
# Pydantic Models
# =============================================================================


class EvolutionPatchSummary(BaseModel):
    """Summary of an evolution patch."""

    id: str
    target_file: str
    patch_type: str
    confidence: str
    risk: str
    reasoning: str
    source_run_id: Optional[str] = None
    human_review_required: bool = True
    created_at: str


class PendingPatchesResponse(BaseModel):
    """Response containing pending evolution patches."""

    run_id: str
    patches: List[EvolutionPatchSummary]
    total_patches: int
    timestamp: str


class AllPendingPatchesResponse(BaseModel):
    """Response containing all pending patches across runs."""

    runs: List[PendingPatchesResponse]
    total_runs: int
    total_patches: int
    timestamp: str


class ApplyEvolutionRequest(BaseModel):
    """Request to apply an evolution patch."""

    patch_id: str = Field(..., description="ID of the patch to apply")
    dry_run: bool = Field(True, description="If true, validate only without applying")
    create_backup: bool = Field(True, description="Create backup of target file before patching")


class ApplyEvolutionResponse(BaseModel):
    """Response after applying or validating an evolution patch."""

    patch_id: str
    dry_run: bool
    success: bool
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    changes_made: List[str] = Field(default_factory=list)
    changes_preview: List[Dict[str, Any]] = Field(default_factory=list)
    backup_path: Optional[str] = None
    new_etag: Optional[str] = None
    timestamp: str


class RejectEvolutionRequest(BaseModel):
    """Request to reject an evolution patch."""

    patch_id: str = Field(..., description="ID of the patch to reject")
    reason: str = Field(..., description="Reason for rejecting the patch")


class RejectEvolutionResponse(BaseModel):
    """Response after rejecting a patch."""

    patch_id: str
    rejected: bool = True
    reason: str
    timestamp: str


class PatchValidationResponse(BaseModel):
    """Response from patch validation."""

    patch_id: str
    valid: bool
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    preview: List[Dict[str, Any]] = Field(default_factory=list)
    target_exists: bool = False
    target_etag: Optional[str] = None
    timestamp: str


# =============================================================================
# Helper Functions
# =============================================================================


def _get_repo_root() -> Path:
    """Get the repository root path."""
    from ..server import get_spec_manager

    manager = get_spec_manager()
    return manager.repo_root


def _get_runs_root() -> Path:
    """Get the runs root directory."""
    from ..server import get_spec_manager

    manager = get_spec_manager()
    return manager.runs_root


def _get_evolution_module():
    """Import evolution module (lazy to avoid circular imports)."""
    from swarm.runtime.evolution import (
        EvolutionPatch,
        apply_evolution_patch,
        generate_evolution_patch,
        list_pending_patches,
        validate_evolution_patch,
    )

    return {
        "EvolutionPatch": EvolutionPatch,
        "generate_evolution_patch": generate_evolution_patch,
        "apply_evolution_patch": apply_evolution_patch,
        "validate_evolution_patch": validate_evolution_patch,
        "list_pending_patches": list_pending_patches,
    }


def _patch_to_summary(patch) -> EvolutionPatchSummary:
    """Convert EvolutionPatch to summary model."""
    return EvolutionPatchSummary(
        id=patch.id,
        target_file=patch.target_file,
        patch_type=patch.patch_type.value,
        confidence=patch.confidence.value,
        risk=patch.risk,
        reasoning=patch.reasoning,
        source_run_id=patch.source_run_id,
        human_review_required=patch.human_review_required,
        created_at=patch.created_at,
    )


# =============================================================================
# Evolution Endpoints
# =============================================================================


@router.get("/pending", response_model=AllPendingPatchesResponse)
async def list_all_pending_patches(limit: int = 50):
    """List all pending evolution patches across runs.

    Scans recent Wisdom outputs for evolution patches that have not been
    applied or rejected.

    Args:
        limit: Maximum number of runs to scan.

    Returns:
        AllPendingPatchesResponse with patches organized by run.
    """
    evolution = _get_evolution_module()
    runs_root = _get_runs_root()

    pending = evolution["list_pending_patches"](runs_root, limit=limit)

    runs = []
    total_patches = 0

    for run_id, patches in pending:
        run_response = PendingPatchesResponse(
            run_id=run_id,
            patches=[_patch_to_summary(p) for p in patches],
            total_patches=len(patches),
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        runs.append(run_response)
        total_patches += len(patches)

    return AllPendingPatchesResponse(
        runs=runs,
        total_runs=len(runs),
        total_patches=total_patches,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@router.get("/{run_id}", response_model=PendingPatchesResponse)
async def get_run_evolution_patches(run_id: str):
    """Get evolution patches for a specific run.

    Args:
        run_id: The run identifier.

    Returns:
        PendingPatchesResponse with patches for this run.

    Raises:
        404: Run not found or no wisdom outputs.
    """
    evolution = _get_evolution_module()
    runs_root = _get_runs_root()

    wisdom_dir = runs_root / run_id / "wisdom"

    if not wisdom_dir.exists():
        raise HTTPException(
            status_code=404,
            detail={
                "error": "wisdom_not_found",
                "message": f"No wisdom artifacts found for run '{run_id}'",
                "details": {"run_id": run_id},
            },
        )

    patches = evolution["generate_evolution_patch"](wisdom_dir, run_id=run_id)

    return PendingPatchesResponse(
        run_id=run_id,
        patches=[_patch_to_summary(p) for p in patches],
        total_patches=len(patches),
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@router.get("/{run_id}/{patch_id}")
async def get_evolution_patch_details(
    run_id: str,
    patch_id: str,
    if_none_match: Optional[str] = Header(None, alias="If-None-Match"),
):
    """Get detailed information about a specific evolution patch.

    Args:
        run_id: The run identifier.
        patch_id: The patch identifier.
        if_none_match: Optional ETag for caching.

    Returns:
        Full patch details including content and operations.

    Raises:
        404: Patch not found.
    """
    evolution = _get_evolution_module()
    runs_root = _get_runs_root()

    wisdom_dir = runs_root / run_id / "wisdom"

    if not wisdom_dir.exists():
        raise HTTPException(
            status_code=404,
            detail={
                "error": "wisdom_not_found",
                "message": f"No wisdom artifacts found for run '{run_id}'",
                "details": {"run_id": run_id},
            },
        )

    patches = evolution["generate_evolution_patch"](wisdom_dir, run_id=run_id)

    # Find the specific patch
    patch = next((p for p in patches if p.id == patch_id), None)

    if not patch:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "patch_not_found",
                "message": f"Patch '{patch_id}' not found in run '{run_id}'",
                "details": {"run_id": run_id, "patch_id": patch_id},
            },
        )

    patch_dict = patch.to_dict()

    # Compute ETag
    import hashlib
    import json

    etag = hashlib.sha256(json.dumps(patch_dict, sort_keys=True).encode()).hexdigest()[:16]

    # Check If-None-Match for caching
    if if_none_match and if_none_match.strip('"') == etag:
        from fastapi import Response

        return Response(status_code=304)

    return JSONResponse(
        content=patch_dict,
        headers={"ETag": f'"{etag}"'},
    )


@router.post("/{run_id}/validate/{patch_id}", response_model=PatchValidationResponse)
async def validate_evolution_patch_endpoint(run_id: str, patch_id: str):
    """Validate an evolution patch without applying it.

    Args:
        run_id: The run identifier.
        patch_id: The patch identifier.

    Returns:
        PatchValidationResponse with validation results.

    Raises:
        404: Patch not found.
    """
    evolution = _get_evolution_module()
    runs_root = _get_runs_root()
    repo_root = _get_repo_root()

    wisdom_dir = runs_root / run_id / "wisdom"

    if not wisdom_dir.exists():
        raise HTTPException(
            status_code=404,
            detail={
                "error": "wisdom_not_found",
                "message": f"No wisdom artifacts found for run '{run_id}'",
                "details": {"run_id": run_id},
            },
        )

    patches = evolution["generate_evolution_patch"](wisdom_dir, run_id=run_id)
    patch = next((p for p in patches if p.id == patch_id), None)

    if not patch:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "patch_not_found",
                "message": f"Patch '{patch_id}' not found in run '{run_id}'",
                "details": {"run_id": run_id, "patch_id": patch_id},
            },
        )

    # Validate the patch
    result = evolution["validate_evolution_patch"](patch, repo_root=repo_root)

    return PatchValidationResponse(
        patch_id=patch_id,
        valid=result.valid,
        errors=result.errors,
        warnings=result.warnings,
        preview=result.preview,
        target_exists=result.target_exists,
        target_etag=result.target_etag,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@router.post("/apply", response_model=ApplyEvolutionResponse)
async def apply_evolution_patch_endpoint(
    request: ApplyEvolutionRequest,
    if_match: Optional[str] = Header(None, alias="If-Match"),
):
    """Apply an evolution patch.

    Validates and optionally applies an evolution patch from wisdom outputs.
    When dry_run=True, only validates the patch without applying.
    When dry_run=False, applies the patch to the target spec file.

    The patch_id should be in the format "run_id:patch_id" (e.g., "my-run:FLOW-PATCH-001")
    or just "patch_id" if the run_id is included in the patch data.

    Args:
        request: Apply evolution request with patch_id and options.
        if_match: Optional ETag for concurrency control.

    Returns:
        ApplyEvolutionResponse with validation results or application status.

    Raises:
        404: Patch not found.
        409: Validation failed.
        412: ETag mismatch.
    """
    evolution = _get_evolution_module()
    runs_root = _get_runs_root()
    repo_root = _get_repo_root()

    # Parse patch_id (may be "run_id:patch_id" or just "patch_id")
    if ":" in request.patch_id:
        run_id, patch_id = request.patch_id.split(":", 1)
    else:
        # Search all recent runs for this patch_id
        patch_id = request.patch_id
        run_id = None
        pending = evolution["list_pending_patches"](runs_root, limit=50)
        for rid, patches in pending:
            if any(p.id == patch_id for p in patches):
                run_id = rid
                break

        if run_id is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "patch_not_found",
                    "message": f"Patch '{patch_id}' not found in any recent run",
                    "details": {"patch_id": patch_id},
                },
            )

    wisdom_dir = runs_root / run_id / "wisdom"

    if not wisdom_dir.exists():
        raise HTTPException(
            status_code=404,
            detail={
                "error": "wisdom_not_found",
                "message": f"No wisdom artifacts found for run '{run_id}'",
                "details": {"run_id": run_id},
            },
        )

    patches = evolution["generate_evolution_patch"](wisdom_dir, run_id=run_id)
    patch = next((p for p in patches if p.id == patch_id), None)

    if not patch:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "patch_not_found",
                "message": f"Patch '{patch_id}' not found in run '{run_id}'",
                "details": {"run_id": run_id, "patch_id": patch_id},
            },
        )

    # Validate first
    validation = evolution["validate_evolution_patch"](patch, repo_root=repo_root)

    # Check ETag if provided
    if if_match and validation.target_etag:
        if if_match.strip('"') != validation.target_etag:
            raise HTTPException(
                status_code=412,
                detail={
                    "error": "etag_mismatch",
                    "message": "Target file was modified since last read",
                    "details": {},
                },
            )

    if not validation.valid:
        if request.dry_run:
            return ApplyEvolutionResponse(
                patch_id=patch_id,
                dry_run=True,
                success=False,
                errors=validation.errors,
                warnings=validation.warnings,
                changes_preview=validation.preview,
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
        else:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "validation_failed",
                    "message": "Patch validation failed",
                    "details": {"errors": validation.errors},
                },
            )

    # Apply the patch
    result = evolution["apply_evolution_patch"](
        patch,
        dry_run=request.dry_run,
        repo_root=repo_root,
        create_backup=request.create_backup,
    )

    if not result.success and not request.dry_run:
        raise HTTPException(
            status_code=500,
            detail={
                "error": "apply_failed",
                "message": "Failed to apply patch",
                "details": {"errors": result.errors},
            },
        )

    logger.info(
        "Evolution patch %s %s for run %s",
        patch_id,
        "validated" if request.dry_run else "applied",
        run_id,
    )

    return ApplyEvolutionResponse(
        patch_id=patch_id,
        dry_run=request.dry_run,
        success=result.success,
        errors=result.errors,
        warnings=validation.warnings,
        changes_made=result.changes_made,
        changes_preview=validation.preview,
        backup_path=result.backup_path,
        new_etag=result.new_etag,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@router.post("/{run_id}/reject/{patch_id}", response_model=RejectEvolutionResponse)
async def reject_evolution_patch_endpoint(
    run_id: str,
    patch_id: str,
    request: RejectEvolutionRequest,
):
    """Reject an evolution patch with a documented reason.

    Records the decision to reject a patch for audit purposes.
    The rejection is stored alongside the wisdom artifacts.

    Args:
        run_id: The run identifier.
        patch_id: The patch identifier.
        request: Reject request with reason.

    Returns:
        RejectEvolutionResponse confirming rejection.

    Raises:
        404: Patch not found.
    """
    import json

    runs_root = _get_runs_root()
    wisdom_dir = runs_root / run_id / "wisdom"

    if not wisdom_dir.exists():
        raise HTTPException(
            status_code=404,
            detail={
                "error": "wisdom_not_found",
                "message": f"No wisdom artifacts found for run '{run_id}'",
                "details": {"run_id": run_id},
            },
        )

    # Record rejection
    rejection_path = wisdom_dir / f".rejected_{patch_id}"
    try:
        rejection_path.write_text(
            json.dumps(
                {
                    "rejected_at": datetime.now(timezone.utc).isoformat(),
                    "patch_id": patch_id,
                    "reason": request.reason,
                }
            )
        )
    except Exception as e:
        logger.error("Failed to write rejection record: %s", e)
        raise HTTPException(
            status_code=500,
            detail={
                "error": "write_failed",
                "message": f"Failed to record rejection: {e}",
                "details": {},
            },
        )

    logger.info(
        "Evolution patch %s rejected for run %s: %s",
        patch_id,
        run_id,
        request.reason,
    )

    return RejectEvolutionResponse(
        patch_id=patch_id,
        rejected=True,
        reason=request.reason,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
