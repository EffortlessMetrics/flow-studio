"""
Spec endpoints for Flow Studio API.

Provides REST endpoints for:
- Template management (list, get)
- Flow graph management (list, get, update)
- Validation and compilation
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Header, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/specs", tags=["specs"])


# =============================================================================
# Pydantic Models
# =============================================================================


class TemplateSummary(BaseModel):
    """Template summary for list endpoint."""

    id: str
    title: str
    station_id: Optional[str] = None
    category: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    description: str = ""


class TemplateListResponse(BaseModel):
    """Response for list templates endpoint."""

    templates: List[TemplateSummary]


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

    step_id: str
    run_id: Optional[str] = None


class CompileResponse(BaseModel):
    """Response for compile endpoint."""

    prompt_plan: Dict[str, Any]


class PatchOperation(BaseModel):
    """JSON Patch operation."""

    op: str = Field(..., description="Operation type: replace, add, remove")
    path: str = Field(..., description="JSON Pointer path")
    value: Optional[Any] = Field(None, description="Value for replace/add")


# =============================================================================
# Spec Manager Access
# =============================================================================


def _get_spec_manager():
    """Get the global SpecManager instance."""
    # Import here to avoid circular imports
    from ..server import get_spec_manager

    return get_spec_manager()


# =============================================================================
# Template Endpoints
# =============================================================================


@router.get("/templates", response_model=TemplateListResponse)
async def list_templates():
    """List all available step templates (for palette).

    Returns:
        List of template summaries with id, title, category, tags.
    """
    manager = _get_spec_manager()
    templates = manager.list_templates()
    return TemplateListResponse(templates=[TemplateSummary(**t) for t in templates])


@router.get("/templates/{template_id}")
async def get_template(
    template_id: str,
    if_none_match: Optional[str] = Header(None, alias="If-None-Match"),
):
    """Get a single template by ID.

    Args:
        template_id: Template identifier.
        if_none_match: Optional ETag for caching.

    Returns:
        Template data with ETag header.

    Raises:
        404: Template not found.
        304: Not modified (if ETag matches).
    """
    manager = _get_spec_manager()

    try:
        template_data, etag = manager.get_template(template_id)

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
                "details": {"template_id": template_id},
            },
        )


# =============================================================================
# Flow Endpoints
# =============================================================================


@router.get("/flows", response_model=FlowListResponse)
async def list_flows():
    """List all available flow graphs.

    Returns:
        List of flow summaries with id, title, flow_number, version.
    """
    manager = _get_spec_manager()
    flows = manager.list_flows()
    return FlowListResponse(flows=[FlowSummary(**f) for f in flows])


@router.get("/flows/{flow_id}")
async def get_flow(
    flow_id: str,
    if_none_match: Optional[str] = Header(None, alias="If-None-Match"),
):
    """Get a merged flow graph (logic + UI overlay) by ID.

    Args:
        flow_id: Flow identifier.
        if_none_match: Optional ETag for caching.

    Returns:
        Merged flow data with ETag header.

    Raises:
        404: Flow not found.
        304: Not modified (if ETag matches).
    """
    manager = _get_spec_manager()

    try:
        flow_data, etag = manager.get_flow(flow_id)

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
                "error": "flow_not_found",
                "message": f"Flow graph '{flow_id}' not found",
                "details": {"flow_id": flow_id},
            },
        )


@router.patch("/flows/{flow_id}")
async def update_flow(
    flow_id: str,
    patch_ops: List[PatchOperation],
    if_match: str = Header(..., alias="If-Match", description="ETag for optimistic concurrency"),
):
    """Update a flow graph with JSON Patch operations.

    Requires If-Match header for optimistic concurrency control.

    Args:
        flow_id: Flow identifier.
        patch_ops: List of JSON Patch operations.
        if_match: Required ETag for concurrency control.

    Returns:
        Updated flow data with new ETag header.

    Raises:
        404: Flow not found.
        412: ETag mismatch (Precondition Failed).
        400: Validation error.
    """
    manager = _get_spec_manager()

    # Strip quotes from ETag if present
    expected_etag = if_match.strip('"')

    try:
        # Convert Pydantic models to dicts
        ops = [op.model_dump(exclude_none=True) for op in patch_ops]

        updated_data, new_etag = manager.update_flow(
            flow_id, ops, expected_etag
        )

        return JSONResponse(
            content=updated_data,
            headers={"ETag": f'"{new_etag}"'},
        )

    except FileNotFoundError:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "flow_not_found",
                "message": f"Flow graph '{flow_id}' not found",
                "details": {"flow_id": flow_id},
            },
        )
    except ValueError as e:
        if "ETag mismatch" in str(e):
            raise HTTPException(
                status_code=412,
                detail={
                    "error": "etag_mismatch",
                    "message": "Resource was modified by another request. Refresh and try again.",
                    "details": {"expected_etag": expected_etag},
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


# =============================================================================
# Validation Endpoint
# =============================================================================


@router.post("/flows/{flow_id}/validate", response_model=ValidationResponse)
async def validate_flow(flow_id: str, request: Optional[ValidationRequest] = None):
    """Validate a flow spec.

    Can validate either:
    - The existing flow (if no body provided)
    - A proposed flow update (if body provided)

    Args:
        flow_id: Flow identifier.
        request: Optional validation request with proposed changes.

    Returns:
        Validation result with valid flag and error list.
    """
    manager = _get_spec_manager()

    try:
        if request:
            # Validate the provided data
            data = request.model_dump(exclude_none=True)
            data["id"] = flow_id  # Ensure ID matches
        else:
            # Validate existing flow
            flow_data, _ = manager.get_flow(flow_id)
            data = flow_data

        errors = manager.validate_flow(data)
        return ValidationResponse(valid=len(errors) == 0, errors=errors)

    except FileNotFoundError:
        return ValidationResponse(
            valid=False,
            errors=[f"Flow '{flow_id}' not found"],
        )


# =============================================================================
# Compilation Endpoint
# =============================================================================


@router.post("/flows/{flow_id}/compile", response_model=CompileResponse)
async def compile_flow(flow_id: str, request: CompileRequest):
    """Compile a flow (expand templates) into a PromptPlan.

    This is a preview endpoint - it shows what the PromptPlan would look like
    for a given flow/step combination without executing anything.

    Args:
        flow_id: Flow identifier.
        request: Compile request with step_id and optional run_id.

    Returns:
        Compiled PromptPlan dictionary.

    Raises:
        400: Compilation error.
    """
    manager = _get_spec_manager()

    try:
        prompt_plan = manager.compile_prompt_plan(
            flow_id=flow_id,
            step_id=request.step_id,
            run_id=request.run_id,
        )
        return CompileResponse(prompt_plan=prompt_plan)

    except FileNotFoundError as e:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "not_found",
                "message": str(e),
                "details": {"flow_id": flow_id, "step_id": request.step_id},
            },
        )
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "compilation_error",
                "message": str(e),
                "details": {"flow_id": flow_id, "step_id": request.step_id},
            },
        )
    except Exception as e:
        logger.error("Compilation failed: %s", e)
        raise HTTPException(
            status_code=500,
            detail={
                "error": "internal_error",
                "message": "Compilation failed",
                "details": {"error": str(e)},
            },
        )
