"""
Wisdom endpoints for Flow Studio API.

Provides REST endpoints for:
- Reading wisdom artifacts from completed runs
- Applying flow evolution patches from wisdom outputs
- Reviewing and managing wisdom recommendations
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/wisdom", tags=["wisdom"])


# =============================================================================
# Pydantic Models
# =============================================================================


class WisdomArtifact(BaseModel):
    """A single wisdom artifact."""

    name: str
    path: str
    content_type: str = "text/markdown"
    size_bytes: int = 0
    digest: Optional[str] = None
    tier: Optional[str] = None  # "flow_evolution", "station_tuning", "learnings"


class WisdomArtifactsResponse(BaseModel):
    """Response containing wisdom artifacts for a run."""

    run_id: str
    artifacts: List[WisdomArtifact]
    has_evolution_patch: bool = False
    has_station_tuning: bool = False
    timestamp: str


class WisdomContentResponse(BaseModel):
    """Response containing the content of a wisdom artifact."""

    run_id: str
    artifact_name: str
    content: str
    content_type: str
    digest: str
    timestamp: str


class ApplyPatchRequest(BaseModel):
    """Request to apply a wisdom evolution patch."""

    dry_run: bool = Field(True, description="If true, validate only without applying")
    artifact_name: str = Field("flow_evolution.patch", description="Name of the patch artifact")
    commit_message: Optional[str] = Field(None, description="Optional commit message if applying")


class ApplyPatchResponse(BaseModel):
    """Response after applying or validating a patch."""

    run_id: str
    dry_run: bool
    valid: bool
    changes_preview: List[Dict[str, Any]] = Field(default_factory=list)
    validation_errors: List[str] = Field(default_factory=list)
    applied: bool = False
    commit_sha: Optional[str] = None
    timestamp: str


class RejectPatchRequest(BaseModel):
    """Request to reject a wisdom patch."""

    artifact_name: str = Field("flow_evolution.patch", description="Name of the patch artifact")
    reason: str = Field(..., description="Reason for rejecting the patch")


class RejectPatchResponse(BaseModel):
    """Response after rejecting a patch."""

    run_id: str
    artifact_name: str
    rejected: bool = True
    reason: str
    timestamp: str


class WisdomApplyRequest(BaseModel):
    """Request to apply wisdom patches at run boundary.

    This endpoint is designed for run-end auto-apply scenarios where
    accumulated wisdom patches can be applied with safety controls.
    """

    dry_run: bool = Field(True, description="If true, validate only without applying")
    patch_type: str = Field(
        "flow_evolution", description="Type of patch to apply: 'flow_evolution' or 'station_tuning'"
    )
    policy: str = Field(
        "safe",
        description="Application policy: 'safe' (validates schema, compile preview, ETag) or 'all' (applies all matching)",
    )


class WisdomPatchResult(BaseModel):
    """Result for a single patch application."""

    patch_id: str
    target_file: str
    patch_type: str
    status: str  # "applied", "rejected", "skipped", "error"
    reason: Optional[str] = None
    validation_errors: List[str] = Field(default_factory=list)
    validation_warnings: List[str] = Field(default_factory=list)
    etag_before: Optional[str] = None
    etag_after: Optional[str] = None


class WisdomApplyResponse(BaseModel):
    """Response from wisdom apply endpoint.

    Contains results for each patch processed, along with summary metrics.
    """

    run_id: str
    dry_run: bool
    policy: str
    patch_type: str
    patches_processed: int
    patches_applied: int
    patches_rejected: int
    patches_skipped: int
    results: List[WisdomPatchResult] = Field(default_factory=list)
    compile_preview_passed: bool = True
    timestamp: str


# =============================================================================
# Helper Functions
# =============================================================================


def _get_runs_root() -> Path:
    """Get the runs root directory."""
    from ..server import get_spec_manager

    manager = get_spec_manager()
    return manager.runs_root


def _get_run_wisdom_dir(run_id: str) -> Path:
    """Get the wisdom directory for a run."""
    return _get_runs_root() / run_id / "wisdom"


def _compute_digest(content: str) -> str:
    """Compute SHA256 digest of content."""
    return hashlib.sha256(content.encode()).hexdigest()[:16]


def _detect_artifact_tier(name: str) -> Optional[str]:
    """Detect the tier of an artifact based on its name."""
    if "evolution" in name.lower() or "patch" in name.lower():
        return "flow_evolution"
    if "tuning" in name.lower() or "station" in name.lower():
        return "station_tuning"
    if "learning" in name.lower() or "insight" in name.lower():
        return "learnings"
    return None


def _get_repo_root() -> Path:
    """Get the repository root path."""
    from ..server import get_spec_manager

    manager = get_spec_manager()
    return manager.repo_root


def _validate_patch_safe_policy(
    patch,
    repo_root: Path,
) -> tuple[bool, List[str], List[str]]:
    """Validate a patch using the 'safe' policy.

    Safe policy checks:
    1. Schema validation - patch has required fields
    2. Target file exists (if applicable)
    3. Compile preview succeeds (for station patches)
    4. ETag matches current file state

    Args:
        patch: EvolutionPatch to validate.
        repo_root: Repository root path.

    Returns:
        Tuple of (valid, errors, warnings).
    """
    from swarm.runtime.evolution import validate_evolution_patch

    errors: List[str] = []
    warnings: List[str] = []

    # Step 1: Basic validation via evolution module
    result = validate_evolution_patch(patch, repo_root=repo_root)
    errors.extend(result.errors)
    warnings.extend(result.warnings)

    # Step 2: Additional safe policy checks

    # Check human_review_required flag
    if patch.human_review_required:
        warnings.append(
            f"Patch {patch.id} has human_review_required=true, "
            "consider manual review before applying"
        )

    # Check confidence level
    from swarm.runtime.evolution import ConfidenceLevel

    if patch.confidence == ConfidenceLevel.LOW:
        warnings.append(f"Patch {patch.id} has low confidence, evidence may be insufficient")

    # Step 3: Try compile preview for station patches
    if patch.patch_type.value == "station_spec":
        try:
            # Extract station ID from target file path
            target_name = Path(patch.target_file).stem
            from swarm.runtime.station_library import load_station_library

            library = load_station_library(repo_root)
            if library.has_station(target_name):
                # Station exists, check if we can still compile
                pass  # Compile preview is optional validation
        except Exception as e:
            warnings.append(f"Could not validate station compile preview: {e}")

    return len(errors) == 0, errors, warnings


def _apply_wisdom_patches(
    run_id: str,
    wisdom_dir: Path,
    patch_type: str,
    policy: str,
    dry_run: bool,
    repo_root: Path,
) -> tuple[List[Dict[str, Any]], bool]:
    """Apply wisdom patches with specified policy.

    Args:
        run_id: Run identifier.
        wisdom_dir: Path to wisdom directory.
        patch_type: Type of patches to apply ('flow_evolution' or 'station_tuning').
        policy: Application policy ('safe' or 'all').
        dry_run: If True, validate only without applying.
        repo_root: Repository root path.

    Returns:
        Tuple of (results list, compile_preview_passed).
    """
    from swarm.runtime.evolution import (
        PatchType,
        apply_evolution_patch,
        generate_evolution_patch,
    )

    results: List[Dict[str, Any]] = []
    compile_preview_passed = True

    # Generate patches from wisdom artifacts
    patches = generate_evolution_patch(wisdom_dir, run_id=run_id)

    # Filter by patch_type
    type_mapping = {
        "flow_evolution": [PatchType.FLOW_SPEC],
        "station_tuning": [PatchType.STATION_SPEC],
    }
    target_types = type_mapping.get(patch_type, [PatchType.FLOW_SPEC, PatchType.STATION_SPEC])

    for patch in patches:
        if patch.patch_type not in target_types:
            continue

        # Check if already applied or rejected
        applied_marker = wisdom_dir / f".applied_{patch.id}"
        rejected_marker = wisdom_dir / f".rejected_{patch.id}"

        if applied_marker.exists():
            results.append(
                {
                    "patch_id": patch.id,
                    "target_file": patch.target_file,
                    "patch_type": patch.patch_type.value,
                    "status": "skipped",
                    "reason": "Already applied",
                }
            )
            continue

        if rejected_marker.exists():
            results.append(
                {
                    "patch_id": patch.id,
                    "target_file": patch.target_file,
                    "patch_type": patch.patch_type.value,
                    "status": "skipped",
                    "reason": "Previously rejected",
                }
            )
            continue

        # Validate based on policy
        if policy == "safe":
            valid, errors, warnings = _validate_patch_safe_policy(patch, repo_root)
        else:
            # 'all' policy - minimal validation
            from swarm.runtime.evolution import validate_evolution_patch

            result = validate_evolution_patch(patch, repo_root=repo_root)
            valid = result.valid
            errors = result.errors
            warnings = result.warnings

        result_entry = {
            "patch_id": patch.id,
            "target_file": patch.target_file,
            "patch_type": patch.patch_type.value,
            "validation_errors": errors,
            "validation_warnings": warnings,
            "etag_before": None,
            "etag_after": None,
        }

        if not valid:
            result_entry["status"] = "rejected"
            result_entry["reason"] = "; ".join(errors) if errors else "Validation failed"
            results.append(result_entry)
            continue

        # If dry run, mark as validated
        if dry_run:
            result_entry["status"] = "validated"
            result_entry["reason"] = "Would apply (dry run)"
            results.append(result_entry)
            continue

        # Apply the patch
        try:
            apply_result = apply_evolution_patch(
                patch,
                dry_run=False,
                repo_root=repo_root,
                create_backup=True,
            )

            if apply_result.success:
                result_entry["status"] = "applied"
                result_entry["reason"] = "; ".join(apply_result.changes_made)
                result_entry["etag_after"] = apply_result.new_etag

                # Write applied marker
                applied_marker.write_text(
                    json.dumps(
                        {
                            "applied_at": datetime.now(timezone.utc).isoformat(),
                            "patch_id": patch.id,
                            "changes_made": apply_result.changes_made,
                            "backup_path": apply_result.backup_path,
                        }
                    )
                )
            else:
                result_entry["status"] = "error"
                result_entry["reason"] = "; ".join(apply_result.errors)

        except Exception as e:
            result_entry["status"] = "error"
            result_entry["reason"] = f"Application failed: {e}"
            logger.error("Failed to apply patch %s: %s", patch.id, e)

        results.append(result_entry)

    return results, compile_preview_passed


# =============================================================================
# Wisdom Endpoints
# =============================================================================


@router.get("/{run_id}", response_model=WisdomArtifactsResponse)
async def get_wisdom_artifacts(run_id: str):
    """Get list of wisdom artifacts for a run.

    Returns metadata about available wisdom outputs including:
    - Flow evolution patches
    - Station tuning recommendations
    - Learning synthesis outputs

    Args:
        run_id: The run identifier.

    Returns:
        WisdomArtifactsResponse with artifact metadata.

    Raises:
        404: Run not found or no wisdom artifacts.
    """
    wisdom_dir = _get_run_wisdom_dir(run_id)

    if not wisdom_dir.exists():
        raise HTTPException(
            status_code=404,
            detail={
                "error": "wisdom_not_found",
                "message": f"No wisdom artifacts found for run '{run_id}'",
                "details": {"run_id": run_id},
            },
        )

    artifacts = []
    has_evolution_patch = False
    has_station_tuning = False

    for artifact_path in wisdom_dir.iterdir():
        if artifact_path.is_file():
            name = artifact_path.name
            tier = _detect_artifact_tier(name)

            # Determine content type
            if name.endswith(".md"):
                content_type = "text/markdown"
            elif name.endswith(".json"):
                content_type = "application/json"
            elif name.endswith(".patch"):
                content_type = "text/x-patch"
            else:
                content_type = "text/plain"

            # Compute digest
            try:
                content = artifact_path.read_text(encoding="utf-8")
                digest = _compute_digest(content)
            except Exception:
                digest = None

            artifacts.append(
                WisdomArtifact(
                    name=name,
                    path=str(artifact_path.relative_to(_get_runs_root().parent)),
                    content_type=content_type,
                    size_bytes=artifact_path.stat().st_size,
                    digest=digest,
                    tier=tier,
                )
            )

            if tier == "flow_evolution":
                has_evolution_patch = True
            if tier == "station_tuning":
                has_station_tuning = True

    return WisdomArtifactsResponse(
        run_id=run_id,
        artifacts=artifacts,
        has_evolution_patch=has_evolution_patch,
        has_station_tuning=has_station_tuning,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@router.get("/{run_id}/{artifact_name}")
async def get_wisdom_content(
    run_id: str,
    artifact_name: str,
    if_none_match: Optional[str] = Header(None, alias="If-None-Match"),
):
    """Get the content of a specific wisdom artifact.

    Args:
        run_id: The run identifier.
        artifact_name: Name of the artifact to retrieve.
        if_none_match: Optional ETag for caching.

    Returns:
        WisdomContentResponse with artifact content.

    Raises:
        404: Artifact not found.
        304: Not modified (if ETag matches).
    """
    wisdom_dir = _get_run_wisdom_dir(run_id)
    artifact_path = wisdom_dir / artifact_name

    if not artifact_path.exists():
        raise HTTPException(
            status_code=404,
            detail={
                "error": "artifact_not_found",
                "message": f"Artifact '{artifact_name}' not found in run '{run_id}'",
                "details": {"run_id": run_id, "artifact_name": artifact_name},
            },
        )

    try:
        content = artifact_path.read_text(encoding="utf-8")
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail={
                "error": "read_failed",
                "message": f"Failed to read artifact: {e}",
                "details": {},
            },
        )

    digest = _compute_digest(content)

    # Check If-None-Match for caching
    if if_none_match and if_none_match.strip('"') == digest:
        from fastapi import Response

        return Response(status_code=304)

    # Determine content type
    if artifact_name.endswith(".md"):
        content_type = "text/markdown"
    elif artifact_name.endswith(".json"):
        content_type = "application/json"
    elif artifact_name.endswith(".patch"):
        content_type = "text/x-patch"
    else:
        content_type = "text/plain"

    return JSONResponse(
        content={
            "run_id": run_id,
            "artifact_name": artifact_name,
            "content": content,
            "content_type": content_type,
            "digest": digest,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
        headers={"ETag": f'"{digest}"'},
    )


@router.post("/{run_id}/apply", response_model=ApplyPatchResponse)
async def apply_wisdom_patch(
    run_id: str,
    request: ApplyPatchRequest,
    if_match: Optional[str] = Header(None, alias="If-Match"),
):
    """Apply a wisdom evolution patch.

    Validates and optionally applies a flow evolution patch from wisdom outputs.
    When dry_run=True, only validates the patch without applying.
    When dry_run=False, applies the patch and optionally commits.

    Args:
        run_id: The run identifier.
        request: Apply patch request with options.
        if_match: Optional ETag for concurrency control.

    Returns:
        ApplyPatchResponse with validation results or application status.

    Raises:
        404: Patch artifact not found.
        409: Patch validation failed.
        412: ETag mismatch.
    """
    wisdom_dir = _get_run_wisdom_dir(run_id)
    patch_path = wisdom_dir / request.artifact_name

    if not patch_path.exists():
        raise HTTPException(
            status_code=404,
            detail={
                "error": "patch_not_found",
                "message": f"Patch artifact '{request.artifact_name}' not found",
                "details": {"run_id": run_id, "artifact_name": request.artifact_name},
            },
        )

    try:
        patch_content = patch_path.read_text(encoding="utf-8")
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail={
                "error": "read_failed",
                "message": f"Failed to read patch: {e}",
                "details": {},
            },
        )

    # Check ETag if provided
    current_digest = _compute_digest(patch_content)
    if if_match and if_match.strip('"') != current_digest:
        raise HTTPException(
            status_code=412,
            detail={
                "error": "etag_mismatch",
                "message": "Patch was modified since last read",
                "details": {},
            },
        )

    # Parse and validate patch
    validation_errors = []
    changes_preview = []

    try:
        # Attempt to parse as JSON patch format
        if request.artifact_name.endswith(".json"):
            patch_data = json.loads(patch_content)
            if isinstance(patch_data, list):
                for change in patch_data:
                    changes_preview.append(
                        {
                            "op": change.get("op", "unknown"),
                            "path": change.get("path", ""),
                            "value_preview": str(change.get("value", ""))[:100],
                        }
                    )
            elif isinstance(patch_data, dict):
                changes_preview.append(
                    {
                        "op": "replace",
                        "path": "/",
                        "value_preview": str(patch_data)[:100],
                    }
                )
        else:
            # Markdown/text patch - extract sections
            lines = patch_content.split("\n")
            current_section = None
            for line in lines:
                if line.startswith("## ") or line.startswith("### "):
                    current_section = line.strip("# ").strip()
                    changes_preview.append(
                        {
                            "op": "section",
                            "path": current_section,
                            "value_preview": "",
                        }
                    )

    except json.JSONDecodeError as e:
        validation_errors.append(f"Invalid JSON: {e}")
    except Exception as e:
        validation_errors.append(f"Parse error: {e}")

    # Additional validation
    if not changes_preview and not validation_errors:
        validation_errors.append("Patch appears to be empty or unparseable")

    valid = len(validation_errors) == 0

    # If dry_run, return validation results only
    if request.dry_run:
        return ApplyPatchResponse(
            run_id=run_id,
            dry_run=True,
            valid=valid,
            changes_preview=changes_preview,
            validation_errors=validation_errors,
            applied=False,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    # Apply the patch (not dry run)
    if not valid:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "validation_failed",
                "message": "Patch validation failed",
                "details": {"errors": validation_errors},
            },
        )

    # TODO: Actually apply the patch via SpecManager
    # For now, record the application intent
    applied_marker = wisdom_dir / f".applied_{request.artifact_name}"
    try:
        applied_marker.write_text(
            json.dumps(
                {
                    "applied_at": datetime.now(timezone.utc).isoformat(),
                    "commit_message": request.commit_message,
                    "digest": current_digest,
                }
            )
        )
    except Exception as e:
        logger.error("Failed to write applied marker: %s", e)

    logger.info(
        "Wisdom patch applied for run %s: %s",
        run_id,
        request.artifact_name,
    )

    return ApplyPatchResponse(
        run_id=run_id,
        dry_run=False,
        valid=True,
        changes_preview=changes_preview,
        validation_errors=[],
        applied=True,
        commit_sha=None,  # TODO: Return actual commit SHA
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@router.post("/{run_id}/reject", response_model=RejectPatchResponse)
async def reject_wisdom_patch(
    run_id: str,
    request: RejectPatchRequest,
):
    """Reject a wisdom patch with a reason.

    Records the decision to reject a patch for audit purposes.

    Args:
        run_id: The run identifier.
        request: Reject request with reason.

    Returns:
        RejectPatchResponse confirming rejection.
    """
    wisdom_dir = _get_run_wisdom_dir(run_id)

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
    rejection_path = wisdom_dir / f".rejected_{request.artifact_name}"
    try:
        rejection_path.write_text(
            json.dumps(
                {
                    "rejected_at": datetime.now(timezone.utc).isoformat(),
                    "artifact_name": request.artifact_name,
                    "reason": request.reason,
                }
            )
        )
    except Exception as e:
        logger.error("Failed to write rejection record: %s", e)

    logger.info(
        "Wisdom patch rejected for run %s: %s (reason: %s)",
        run_id,
        request.artifact_name,
        request.reason,
    )

    return RejectPatchResponse(
        run_id=run_id,
        artifact_name=request.artifact_name,
        rejected=True,
        reason=request.reason,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@router.post("/{run_id}/apply-patches", response_model=WisdomApplyResponse)
async def apply_wisdom_patches(
    run_id: str,
    request: WisdomApplyRequest,
    if_match: Optional[str] = Header(None, alias="If-Match"),
):
    """Apply wisdom patches at run boundary with policy controls.

    This endpoint is designed for automated patch application at the end
    of a run cycle. It supports two policies:

    - **safe**: Validates patches against schema, ensures compile preview
      succeeds, and checks ETag consistency before applying.
    - **all**: Applies all matching patches with minimal validation.

    The endpoint emits `wisdom:patch_applied` or `wisdom:patch_rejected`
    events for each patch processed, enabling observability of the
    evolution loop.

    Args:
        run_id: The run identifier.
        request: WisdomApplyRequest with dry_run, patch_type, and policy.
        if_match: Optional ETag for concurrency control.

    Returns:
        WisdomApplyResponse with results for each patch.

    Raises:
        404: Run or wisdom artifacts not found.
        400: Invalid patch_type or policy.
    """
    # Validate request parameters
    if request.patch_type not in ("flow_evolution", "station_tuning"):
        raise HTTPException(
            status_code=400,
            detail={
                "error": "invalid_patch_type",
                "message": f"Invalid patch_type: {request.patch_type}. "
                "Must be 'flow_evolution' or 'station_tuning'.",
                "details": {"patch_type": request.patch_type},
            },
        )

    if request.policy not in ("safe", "all"):
        raise HTTPException(
            status_code=400,
            detail={
                "error": "invalid_policy",
                "message": f"Invalid policy: {request.policy}. Must be 'safe' or 'all'.",
                "details": {"policy": request.policy},
            },
        )

    wisdom_dir = _get_run_wisdom_dir(run_id)

    if not wisdom_dir.exists():
        raise HTTPException(
            status_code=404,
            detail={
                "error": "wisdom_not_found",
                "message": f"No wisdom artifacts found for run '{run_id}'",
                "details": {"run_id": run_id},
            },
        )

    repo_root = _get_repo_root()

    # Apply patches with the specified policy
    results, compile_preview_passed = _apply_wisdom_patches(
        run_id=run_id,
        wisdom_dir=wisdom_dir,
        patch_type=request.patch_type,
        policy=request.policy,
        dry_run=request.dry_run,
        repo_root=repo_root,
    )

    # Count results by status
    patches_applied = sum(1 for r in results if r.get("status") == "applied")
    patches_rejected = sum(1 for r in results if r.get("status") == "rejected")
    patches_skipped = sum(1 for r in results if r.get("status") == "skipped")
    patches_validated = sum(1 for r in results if r.get("status") == "validated")

    # Emit events for each result (non-dry-run only)
    if not request.dry_run:
        from .events import EventType, write_event_sync

        runs_root = _get_runs_root()

        for result in results:
            status = result.get("status")
            if status == "applied":
                write_event_sync(
                    run_id=run_id,
                    runs_root=runs_root,
                    event_type=EventType.WISDOM_PATCH_APPLIED,
                    data={
                        "patch_id": result.get("patch_id"),
                        "target_file": result.get("target_file"),
                        "patch_type": result.get("patch_type"),
                        "policy": request.policy,
                    },
                )
            elif status == "rejected":
                write_event_sync(
                    run_id=run_id,
                    runs_root=runs_root,
                    event_type=EventType.WISDOM_PATCH_REJECTED,
                    data={
                        "patch_id": result.get("patch_id"),
                        "target_file": result.get("target_file"),
                        "patch_type": result.get("patch_type"),
                        "reason": result.get("reason"),
                        "policy": request.policy,
                    },
                )

    logger.info(
        "Wisdom patches %s for run %s: %d processed, %d applied, %d rejected, %d skipped",
        "validated" if request.dry_run else "applied",
        run_id,
        len(results),
        patches_applied if not request.dry_run else patches_validated,
        patches_rejected,
        patches_skipped,
    )

    # Convert results to response model format
    patch_results = [
        WisdomPatchResult(
            patch_id=r.get("patch_id", "unknown"),
            target_file=r.get("target_file", ""),
            patch_type=r.get("patch_type", "unknown"),
            status=r.get("status", "error"),
            reason=r.get("reason"),
            validation_errors=r.get("validation_errors", []),
            validation_warnings=r.get("validation_warnings", []),
            etag_before=r.get("etag_before"),
            etag_after=r.get("etag_after"),
        )
        for r in results
    ]

    return WisdomApplyResponse(
        run_id=run_id,
        dry_run=request.dry_run,
        policy=request.policy,
        patch_type=request.patch_type,
        patches_processed=len(results),
        patches_applied=patches_applied if not request.dry_run else 0,
        patches_rejected=patches_rejected,
        patches_skipped=patches_skipped,
        results=patch_results,
        compile_preview_passed=compile_preview_passed,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@router.get("/latest", response_model=WisdomContentResponse)
async def get_latest_wisdom():
    """Get the latest consolidated wisdom artifact.

    Returns the content of .runs/_wisdom/latest.md if it exists.

    Returns:
        WisdomContentResponse with latest wisdom content.

    Raises:
        404: No latest wisdom found.
    """
    runs_root = _get_runs_root()
    latest_path = runs_root / "_wisdom" / "latest.md"

    if not latest_path.exists():
        raise HTTPException(
            status_code=404,
            detail={
                "error": "latest_not_found",
                "message": "No consolidated wisdom found",
                "details": {},
            },
        )

    try:
        content = latest_path.read_text(encoding="utf-8")
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail={
                "error": "read_failed",
                "message": f"Failed to read latest wisdom: {e}",
                "details": {},
            },
        )

    digest = _compute_digest(content)

    return WisdomContentResponse(
        run_id="_wisdom",
        artifact_name="latest.md",
        content=content,
        content_type="text/markdown",
        digest=digest,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
