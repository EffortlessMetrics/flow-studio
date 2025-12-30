"""
Spec endpoints for Flow Studio API.

Provides REST endpoints for:
- Template management (list, get)
- Flow graph management (list, get, update)
- Station management (list, get, create, update, patch, delete)
- Validation and compilation
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException, Response
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
# Station Pydantic Models
# =============================================================================


class StationSummary(BaseModel):
    """Station summary for list endpoint."""

    station_id: str
    name: str
    description: str = ""
    category: str = "general"
    version: int = 1
    tags: List[str] = Field(default_factory=list)


class StationListResponse(BaseModel):
    """Response for list stations endpoint."""

    stations: List[StationSummary]
    count: int


class StationCreateRequest(BaseModel):
    """Request for creating a new station."""

    station_id: str = Field(..., description="Unique station identifier")
    name: str = Field(..., description="Human-readable name")
    description: str = Field(default="", description="Station description")
    category: str = Field(default="general", description="Station category")
    version: int = Field(default=1, description="Station version")
    sdk: Dict[str, Any] = Field(default_factory=dict, description="SDK configuration")
    identity: Dict[str, Any] = Field(default_factory=dict, description="Identity config")
    io: Dict[str, Any] = Field(default_factory=dict, description="IO contract")
    handoff: Dict[str, Any] = Field(default_factory=dict, description="Handoff config")
    runtime_prompt: Dict[str, Any] = Field(
        default_factory=dict, description="Runtime prompt config"
    )
    invariants: List[str] = Field(default_factory=list, description="Invariants")
    routing_hints: Dict[str, Any] = Field(default_factory=dict, description="Routing hints")
    agent_key: Optional[str] = Field(None, description="Default agent key")
    tags: List[str] = Field(default_factory=list, description="Tags")
    default_params: Dict[str, Any] = Field(default_factory=dict, description="Default parameters")


class StationUpdateRequest(BaseModel):
    """Request for updating a station (PUT semantics)."""

    name: str = Field(..., description="Human-readable name")
    description: str = Field(default="", description="Station description")
    category: str = Field(default="general", description="Station category")
    version: int = Field(default=1, description="Station version")
    sdk: Dict[str, Any] = Field(default_factory=dict, description="SDK configuration")
    identity: Dict[str, Any] = Field(default_factory=dict, description="Identity config")
    io: Dict[str, Any] = Field(default_factory=dict, description="IO contract")
    handoff: Dict[str, Any] = Field(default_factory=dict, description="Handoff config")
    runtime_prompt: Dict[str, Any] = Field(
        default_factory=dict, description="Runtime prompt config"
    )
    invariants: List[str] = Field(default_factory=list, description="Invariants")
    routing_hints: Dict[str, Any] = Field(default_factory=dict, description="Routing hints")
    agent_key: Optional[str] = Field(None, description="Default agent key")
    tags: List[str] = Field(default_factory=list, description="Tags")
    default_params: Dict[str, Any] = Field(default_factory=dict, description="Default parameters")


class StationPatchRequest(BaseModel):
    """Request for partially updating a station (PATCH semantics)."""

    name: Optional[str] = Field(None, description="Human-readable name")
    description: Optional[str] = Field(None, description="Station description")
    category: Optional[str] = Field(None, description="Station category")
    version: Optional[int] = Field(None, description="Station version")
    sdk: Optional[Dict[str, Any]] = Field(None, description="SDK configuration")
    identity: Optional[Dict[str, Any]] = Field(None, description="Identity config")
    io: Optional[Dict[str, Any]] = Field(None, description="IO contract")
    handoff: Optional[Dict[str, Any]] = Field(None, description="Handoff config")
    runtime_prompt: Optional[Dict[str, Any]] = Field(None, description="Runtime prompt config")
    invariants: Optional[List[str]] = Field(None, description="Invariants")
    routing_hints: Optional[Dict[str, Any]] = Field(None, description="Routing hints")
    agent_key: Optional[str] = Field(None, description="Default agent key")
    tags: Optional[List[str]] = Field(None, description="Tags")
    default_params: Optional[Dict[str, Any]] = Field(None, description="Default parameters")


# =============================================================================
# Spec Manager Access
# =============================================================================


def _get_spec_manager():
    """Get the global SpecManager instance."""
    # Import here to avoid circular imports
    from ..server import get_spec_manager

    return get_spec_manager()


def _get_repo_root() -> Path:
    """Find repository root by looking for .git directory."""
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / ".git").exists():
            return parent
    raise RuntimeError("Could not find repository root")


def _get_station_library():
    """Get a loaded StationLibrary instance."""
    from swarm.runtime.station_library import load_station_library

    repo_root = _get_repo_root()
    return load_station_library(repo_root)


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

        updated_data, new_etag = manager.update_flow(flow_id, ops, expected_etag)

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


# =============================================================================
# Station CRUD Endpoints
# =============================================================================


@router.get("/stations", response_model=StationListResponse)
async def list_stations(
    category: Optional[str] = None,
    tag: Optional[str] = None,
):
    """List all available stations.

    Args:
        category: Optional filter by category (e.g., 'worker', 'critic', 'sidequest').
        tag: Optional filter by tag.

    Returns:
        List of station summaries.
    """
    try:
        library = _get_station_library()

        if category:
            stations = library.get_stations_by_category(category)
        elif tag:
            stations = library.get_stations_by_tag(tag)
        else:
            stations = library.list_all_stations()

        items = [
            StationSummary(
                station_id=s.station_id,
                name=s.name,
                description=s.description,
                category=s.category,
                version=s.version,
                tags=list(s.tags),
            )
            for s in stations
        ]

        return StationListResponse(stations=items, count=len(items))

    except Exception as e:
        logger.error("Failed to list stations: %s", e, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "error": "internal_error",
                "message": f"Failed to list stations: {str(e)}",
                "details": {},
            },
        )


@router.get("/stations/{station_id}")
async def get_station(
    station_id: str,
    if_none_match: Optional[str] = Header(None, alias="If-None-Match"),
):
    """Get a station by ID with ETag support.

    Args:
        station_id: Station identifier.
        if_none_match: Optional ETag for caching.

    Returns:
        Station data with ETag header.

    Raises:
        404: Station not found.
        304: Not modified (if ETag matches).
    """
    try:
        library = _get_station_library()
        from swarm.runtime.station_library import station_spec_to_dict

        spec, etag = library.get_station_with_etag(station_id)

        if spec is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "station_not_found",
                    "message": f"Station '{station_id}' not found",
                    "details": {"station_id": station_id},
                },
            )

        # Check If-None-Match for caching (strip quotes from ETag)
        if if_none_match and if_none_match.strip('"') == etag:
            return Response(status_code=304)

        return JSONResponse(
            content=station_spec_to_dict(spec),
            headers={"ETag": f'"{etag}"'},
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get station %s: %s", station_id, e, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "error": "internal_error",
                "message": f"Failed to get station: {str(e)}",
                "details": {"station_id": station_id},
            },
        )


@router.post("/stations", status_code=201)
async def create_station(request: StationCreateRequest):
    """Create a new station.

    Args:
        request: Station creation request.

    Returns:
        Created station data with Location and ETag headers.

    Raises:
        400: Validation error.
        409: Station already exists.
    """
    try:
        library = _get_station_library()
        from swarm.runtime.station_library import station_spec_to_dict

        data = request.model_dump(exclude_none=True)
        spec, etag = library.create_station(data)

        return JSONResponse(
            status_code=201,
            content=station_spec_to_dict(spec),
            headers={
                "ETag": f'"{etag}"',
                "Location": f"/api/specs/stations/{spec.station_id}",
            },
        )

    except ValueError as e:
        error_msg = str(e)
        if "already exists" in error_msg:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "station_exists",
                    "message": error_msg,
                    "details": {"station_id": request.station_id},
                },
            )
        raise HTTPException(
            status_code=400,
            detail={
                "error": "validation_error",
                "message": error_msg,
                "details": {},
            },
        )
    except Exception as e:
        logger.error("Failed to create station: %s", e, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "error": "internal_error",
                "message": f"Failed to create station: {str(e)}",
                "details": {},
            },
        )


@router.put("/stations/{station_id}")
async def update_station(
    station_id: str,
    request: StationUpdateRequest,
    if_match: str = Header(..., alias="If-Match", description="ETag for optimistic concurrency"),
):
    """Replace a station (PUT semantics).

    Requires If-Match header for optimistic concurrency control.

    Args:
        station_id: Station identifier.
        request: Complete station data.
        if_match: Required ETag for concurrency control.

    Returns:
        Updated station data with new ETag header.

    Raises:
        404: Station not found.
        412: ETag mismatch (Precondition Failed).
        400: Validation error.
        403: Cannot modify default pack stations.
    """
    try:
        library = _get_station_library()
        from swarm.runtime.station_library import station_spec_to_dict

        # Strip quotes from ETag if present
        expected_etag = if_match.strip('"')

        data = request.model_dump(exclude_none=True)
        spec, new_etag = library.update_station(station_id, data, expected_etag)

        return JSONResponse(
            content=station_spec_to_dict(spec),
            headers={"ETag": f'"{new_etag}"'},
        )

    except ValueError as e:
        error_msg = str(e)
        if "not found" in error_msg.lower():
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "station_not_found",
                    "message": error_msg,
                    "details": {"station_id": station_id},
                },
            )
        if "ETag mismatch" in error_msg:
            raise HTTPException(
                status_code=412,
                detail={
                    "error": "etag_mismatch",
                    "message": "Resource was modified by another request. Refresh and try again.",
                    "details": {"expected_etag": if_match.strip('"')},
                },
            )
        if "default pack" in error_msg.lower():
            raise HTTPException(
                status_code=403,
                detail={
                    "error": "forbidden",
                    "message": error_msg,
                    "details": {"station_id": station_id},
                },
            )
        raise HTTPException(
            status_code=400,
            detail={
                "error": "validation_error",
                "message": error_msg,
                "details": {},
            },
        )
    except Exception as e:
        logger.error("Failed to update station %s: %s", station_id, e, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "error": "internal_error",
                "message": f"Failed to update station: {str(e)}",
                "details": {"station_id": station_id},
            },
        )


@router.patch("/stations/{station_id}")
async def patch_station(
    station_id: str,
    request: StationPatchRequest,
    if_match: str = Header(..., alias="If-Match", description="ETag for optimistic concurrency"),
):
    """Partially update a station (PATCH semantics).

    Requires If-Match header for optimistic concurrency control.

    Args:
        station_id: Station identifier.
        request: Partial station data to merge.
        if_match: Required ETag for concurrency control.

    Returns:
        Updated station data with new ETag header.

    Raises:
        404: Station not found.
        412: ETag mismatch (Precondition Failed).
        400: Validation error.
        403: Cannot modify default pack stations.
    """
    try:
        library = _get_station_library()
        from swarm.runtime.station_library import station_spec_to_dict

        # Strip quotes from ETag if present
        expected_etag = if_match.strip('"')

        # Only include non-None values in patch
        patch_data = request.model_dump(exclude_none=True)
        spec, new_etag = library.patch_station(station_id, patch_data, expected_etag)

        return JSONResponse(
            content=station_spec_to_dict(spec),
            headers={"ETag": f'"{new_etag}"'},
        )

    except ValueError as e:
        error_msg = str(e)
        if "not found" in error_msg.lower():
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "station_not_found",
                    "message": error_msg,
                    "details": {"station_id": station_id},
                },
            )
        if "ETag mismatch" in error_msg:
            raise HTTPException(
                status_code=412,
                detail={
                    "error": "etag_mismatch",
                    "message": "Resource was modified by another request. Refresh and try again.",
                    "details": {"expected_etag": if_match.strip('"')},
                },
            )
        if "default pack" in error_msg.lower():
            raise HTTPException(
                status_code=403,
                detail={
                    "error": "forbidden",
                    "message": error_msg,
                    "details": {"station_id": station_id},
                },
            )
        raise HTTPException(
            status_code=400,
            detail={
                "error": "validation_error",
                "message": error_msg,
                "details": {},
            },
        )
    except Exception as e:
        logger.error("Failed to patch station %s: %s", station_id, e, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "error": "internal_error",
                "message": f"Failed to patch station: {str(e)}",
                "details": {"station_id": station_id},
            },
        )


@router.delete("/stations/{station_id}", status_code=204)
async def delete_station(
    station_id: str,
    if_match: Optional[str] = Header(
        None, alias="If-Match", description="Optional ETag for concurrency"
    ),
):
    """Delete a station.

    Args:
        station_id: Station identifier.
        if_match: Optional ETag for concurrency control.

    Returns:
        204 No Content on success.

    Raises:
        404: Station not found.
        412: ETag mismatch (Precondition Failed).
        403: Cannot delete default pack stations.
    """
    try:
        library = _get_station_library()

        # Strip quotes from ETag if present
        expected_etag = if_match.strip('"') if if_match else None

        library.delete_station(station_id, expected_etag)

        return Response(status_code=204)

    except ValueError as e:
        error_msg = str(e)
        if "not found" in error_msg.lower():
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "station_not_found",
                    "message": error_msg,
                    "details": {"station_id": station_id},
                },
            )
        if "ETag mismatch" in error_msg:
            raise HTTPException(
                status_code=412,
                detail={
                    "error": "etag_mismatch",
                    "message": "Resource was modified by another request. Refresh and try again.",
                    "details": {"expected_etag": if_match.strip('"') if if_match else None},
                },
            )
        if "default pack" in error_msg.lower():
            raise HTTPException(
                status_code=403,
                detail={
                    "error": "forbidden",
                    "message": error_msg,
                    "details": {"station_id": station_id},
                },
            )
        raise HTTPException(
            status_code=400,
            detail={
                "error": "validation_error",
                "message": error_msg,
                "details": {},
            },
        )
    except Exception as e:
        logger.error("Failed to delete station %s: %s", station_id, e, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "error": "internal_error",
                "message": f"Failed to delete station: {str(e)}",
                "details": {"station_id": station_id},
            },
        )


@router.post("/stations/{station_id}/validate")
async def validate_station(
    station_id: str,
    request: Optional[StationPatchRequest] = None,
):
    """Validate a station spec.

    Can validate either:
    - The existing station (if no body provided)
    - A proposed station update (if body provided)

    Args:
        station_id: Station identifier.
        request: Optional partial station data to validate.

    Returns:
        Validation result with valid flag and error list.
    """
    try:
        library = _get_station_library()
        from swarm.runtime.station_library import station_spec_to_dict

        if request:
            # Get existing station and merge with proposed changes
            existing = library.get_station(station_id)
            if existing:
                existing_data = station_spec_to_dict(existing)
                patch_data = request.model_dump(exclude_none=True)
                # Simple merge for validation
                data = {**existing_data, **patch_data}
            else:
                # Validate just the patch data
                data = request.model_dump(exclude_none=True)
                data["station_id"] = station_id
        else:
            # Validate existing station
            existing = library.get_station(station_id)
            if not existing:
                return JSONResponse(
                    content={
                        "valid": False,
                        "errors": [f"Station '{station_id}' not found"],
                    }
                )
            data = station_spec_to_dict(existing)

        errors = library.validate_station_data(data)
        return JSONResponse(
            content={
                "valid": len(errors) == 0,
                "errors": errors,
            }
        )

    except Exception as e:
        logger.error("Failed to validate station %s: %s", station_id, e, exc_info=True)
        return JSONResponse(
            content={
                "valid": False,
                "errors": [f"Validation error: {str(e)}"],
            }
        )
