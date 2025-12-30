"""
Compile preview endpoints for Flow Studio API.

Provides REST endpoints for:
- Preview compiled prompts before execution
- Inspect PromptPlan structure for debugging
- Validate station/step combinations

This endpoint bridges StationLibrary and SpecCompiler to produce
UI-inspectable prompt plans without executing anything.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/compile", tags=["compile"])


# =============================================================================
# Pydantic Models
# =============================================================================


class CompilePreviewRequest(BaseModel):
    """Request for compile-preview endpoint."""

    station_id: str = Field(..., description="Station identifier (e.g., 'code-implementer')")
    step_id: str = Field(..., description="Step identifier (e.g., 'implement-feature')")
    objective: str = Field(..., description="Objective for this step")
    flow_key: str = Field(default="build", description="Flow key (e.g., 'build', 'signal')")
    run_base: str = Field(
        default="swarm/runs/preview",
        description="Run base directory for artifact paths",
    )
    context_pack: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional context pack with upstream artifacts and envelopes",
    )


class SdkOptionsResponse(BaseModel):
    """SDK options in the compiled plan."""

    model: str
    permission_mode: str
    allowed_tools: List[str]
    max_turns: int


class TraceabilityResponse(BaseModel):
    """Traceability metadata for audit trail."""

    station_id: str
    station_version: int
    prompt_hash: str


class VerificationResponse(BaseModel):
    """Verification requirements."""

    required_artifacts: List[str]
    verification_commands: List[str]


class HandoffResponse(BaseModel):
    """Handoff contract."""

    path: str
    required_fields: List[str]


class CompilePreviewResponse(BaseModel):
    """Response from compile-preview endpoint."""

    system_prompt: str
    user_prompt: str
    sdk_options: SdkOptionsResponse
    traceability: TraceabilityResponse
    verification: VerificationResponse
    handoff: HandoffResponse


class StationListItem(BaseModel):
    """Summary of a station for listing."""

    station_id: str
    name: str
    description: str
    category: str
    version: int
    tags: List[str] = Field(default_factory=list)


class StationListResponse(BaseModel):
    """Response for listing available stations."""

    stations: List[StationListItem]
    count: int


# =============================================================================
# Helper Functions
# =============================================================================


def _get_repo_root() -> Path:
    """Find repository root by looking for .git directory."""
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / ".git").exists():
            return parent
    raise RuntimeError("Could not find repository root")


def _load_station_library():
    """Load the station library with default and repo packs."""
    from swarm.runtime.station_library import load_station_library

    repo_root = _get_repo_root()
    return load_station_library(repo_root)


def _compile_from_station(
    station_id: str,
    step_id: str,
    objective: str,
    flow_key: str,
    run_base: str,
    context_pack: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Compile a PromptPlan from station spec.

    This is the core compilation logic that:
    1. Loads the station from StationLibrary
    2. Converts to compiler spec format
    3. Builds system and user prompts
    4. Returns the compiled plan as a dictionary

    Args:
        station_id: Station identifier.
        step_id: Step identifier.
        objective: Step objective text.
        flow_key: Flow key for routing.
        run_base: Run base directory path.
        context_pack: Optional context with artifacts/envelopes.

    Returns:
        Compiled plan as dictionary.

    Raises:
        ValueError: If station not found or compilation fails.
    """
    from swarm.runtime.station_library import (
        load_station_library,
        to_compiler_spec,
    )
    from swarm.spec.compiler import (
        build_system_append,
        render_template,
    )

    repo_root = _get_repo_root()

    # Load station library and get station
    library = load_station_library(repo_root)

    if not library.has_station(station_id):
        raise ValueError(f"Station not found: {station_id}")

    station_runtime = library.get_station(station_id)
    if not station_runtime:
        raise ValueError(f"Station not found: {station_id}")

    # Convert to compiler spec format
    station = to_compiler_spec(station_runtime)

    # Build template variables
    run_base_path = Path(run_base)
    variables = {
        "run": {"base": str(run_base_path)},
        "step": {"id": step_id, "objective": objective, "scope": ""},
        "flow": {"key": flow_key, "id": f"preview-{flow_key}", "version": "1"},
        "station": {
            "id": station.id,
            "title": station.title,
            "version": str(station.version),
        },
    }

    # Build system prompt (identity + invariants)
    system_prompt = build_system_append(station, scent_trail=None)

    # Build user prompt (simplified since we don't have full context)
    # For preview, we build a simpler prompt focused on the objective
    user_prompt_parts = []

    # Guidelines from station fragments (if any)
    if station.runtime_prompt.fragments:
        user_prompt_parts.append("## Guidelines\n")
        for frag_path in station.runtime_prompt.fragments:
            user_prompt_parts.append(f"(Fragment: {frag_path})")
        user_prompt_parts.append("")

    # Objective
    user_prompt_parts.append("## Objective\n")
    user_prompt_parts.append(objective)
    user_prompt_parts.append("")

    # Context pointers (from context_pack if provided)
    if context_pack:
        upstream = context_pack.get("upstream_artifacts", {})
        if upstream:
            user_prompt_parts.append("## Available Artifacts\n")
            user_prompt_parts.append("Read these files for context:")
            for name, path in upstream.items():
                user_prompt_parts.append(f"- `{path}` ({name})")
            user_prompt_parts.append("")

        envelopes = context_pack.get("previous_envelopes", [])
        if envelopes:
            user_prompt_parts.append("## Previous Steps\n")
            for env in envelopes[-5:]:
                status = env.get("status", "?").upper()
                summary = env.get("summary", "No summary")[:200]
                env_step_id = env.get("step_id", "unknown")
                user_prompt_parts.append(f"- **{env_step_id}** [{status}]: {summary}")
            user_prompt_parts.append("")

    # IO requirements from station
    if station.io.required_inputs:
        user_prompt_parts.append("## Required Inputs\n")
        user_prompt_parts.append("These artifacts must exist and be read:")
        for inp in station.io.required_inputs:
            resolved = render_template(inp, variables)
            user_prompt_parts.append(f"- `{resolved}`")
        user_prompt_parts.append("")

    if station.io.required_outputs:
        user_prompt_parts.append("## Required Outputs\n")
        user_prompt_parts.append("You MUST produce these artifacts:")
        for out in station.io.required_outputs:
            resolved = render_template(out, variables)
            user_prompt_parts.append(f"- `{resolved}`")
        user_prompt_parts.append("")

    # Handoff instructions
    handoff_path = render_template(station.handoff.path_template, variables)
    user_prompt_parts.append("## Finalization (REQUIRED)\n")
    user_prompt_parts.append(f"When complete, write a handoff file to: `{handoff_path}`")
    user_prompt_parts.append("\nThe file MUST be valid JSON with these fields:")
    user_prompt_parts.append("```json")
    user_prompt_parts.append("{")
    for i, fld in enumerate(station.handoff.required_fields):
        comma = "," if i < len(station.handoff.required_fields) - 1 else ""
        if fld == "status":
            user_prompt_parts.append(
                f'  "status": "VERIFIED | UNVERIFIED | PARTIAL | BLOCKED"{comma}'
            )
        elif fld == "summary":
            user_prompt_parts.append(f'  "summary": "2-paragraph summary of work done"{comma}')
        elif fld == "artifacts":
            user_prompt_parts.append(f'  "artifacts": {{"name": "relative/path"}}{comma}')
        elif fld == "can_further_iteration_help":
            user_prompt_parts.append(f'  "can_further_iteration_help": "yes | no"{comma}')
        else:
            user_prompt_parts.append(f'  "{fld}": "..."{comma}')
    user_prompt_parts.append("}")
    user_prompt_parts.append("```")
    user_prompt_parts.append("\n**DO NOT** finish without writing this file.")

    user_prompt = "\n".join(user_prompt_parts)

    # Compute prompt hash
    prompt_hash = hashlib.sha256((system_prompt + user_prompt).encode("utf-8")).hexdigest()[:16]

    # Build verification requirements
    verification_artifacts = []
    for out in station.io.required_outputs:
        resolved = render_template(out, variables)
        verification_artifacts.append(resolved)

    return {
        "system_prompt": system_prompt,
        "user_prompt": user_prompt,
        "sdk_options": {
            "model": station.sdk.model,
            "permission_mode": station.sdk.permission_mode,
            "allowed_tools": list(station.sdk.allowed_tools),
            "max_turns": station.sdk.max_turns,
        },
        "traceability": {
            "station_id": station.id,
            "station_version": station.version,
            "prompt_hash": prompt_hash,
        },
        "verification": {
            "required_artifacts": verification_artifacts,
            "verification_commands": [],
        },
        "handoff": {
            "path": handoff_path,
            "required_fields": list(station.handoff.required_fields),
        },
    }


# =============================================================================
# Endpoints
# =============================================================================


@router.post("/preview", response_model=CompilePreviewResponse)
async def compile_preview(request: CompilePreviewRequest):
    """Preview a compiled prompt plan without executing.

    This endpoint allows the UI to inspect what a prompt would look like
    before actually executing it. It's useful for:
    - Debugging prompt construction
    - Verifying station configuration
    - Understanding what context will be included
    - Validating objective/scope combinations

    The compiled plan includes:
    - system_prompt: Identity + invariants from station spec
    - user_prompt: Objective + context + IO contract + handoff instructions
    - sdk_options: Model, tools, permissions for SDK execution
    - traceability: Station ID, version, prompt hash for audit
    - verification: Required artifacts and verification commands
    - handoff: Path and required fields for handoff envelope

    Args:
        request: CompilePreviewRequest with station_id, step_id, objective, etc.

    Returns:
        CompilePreviewResponse with the compiled plan.

    Raises:
        404: Station not found.
        400: Compilation failed.
    """
    try:
        compiled = _compile_from_station(
            station_id=request.station_id,
            step_id=request.step_id,
            objective=request.objective,
            flow_key=request.flow_key,
            run_base=request.run_base,
            context_pack=request.context_pack,
        )

        return CompilePreviewResponse(
            system_prompt=compiled["system_prompt"],
            user_prompt=compiled["user_prompt"],
            sdk_options=SdkOptionsResponse(**compiled["sdk_options"]),
            traceability=TraceabilityResponse(**compiled["traceability"]),
            verification=VerificationResponse(**compiled["verification"]),
            handoff=HandoffResponse(**compiled["handoff"]),
        )

    except ValueError as e:
        if "not found" in str(e).lower():
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "station_not_found",
                    "message": str(e),
                    "details": {"station_id": request.station_id},
                },
            )
        raise HTTPException(
            status_code=400,
            detail={
                "error": "compilation_error",
                "message": str(e),
                "details": {"station_id": request.station_id, "step_id": request.step_id},
            },
        )
    except Exception as e:
        logger.error("Compilation failed: %s", e, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "error": "internal_error",
                "message": f"Compilation failed: {str(e)}",
                "details": {},
            },
        )


@router.get("/stations", response_model=StationListResponse)
async def list_stations(
    category: Optional[str] = None,
    tag: Optional[str] = None,
):
    """List all available stations from the StationLibrary.

    This endpoint provides station discovery for the UI palette.
    It loads stations from:
    - Default pack (built-in stations)
    - Repo pack (custom stations in swarm/packs/)

    Args:
        category: Optional filter by category (e.g., 'worker', 'critic', 'sidequest').
        tag: Optional filter by tag.

    Returns:
        List of station summaries with id, name, description, category.
    """
    try:
        library = _load_station_library()

        if category:
            stations = library.get_stations_by_category(category)
        elif tag:
            stations = library.get_stations_by_tag(tag)
        else:
            stations = library.list_all_stations()

        items = [
            StationListItem(
                station_id=s.station_id,
                name=s.name,
                description=s.description,
                category=s.category,
                version=s.version,
                tags=list(s.tags),
            )
            for s in stations
        ]

        return StationListResponse(
            stations=items,
            count=len(items),
        )

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
async def get_station(station_id: str):
    """Get detailed information about a specific station.

    Returns the full station specification including SDK config,
    IO contract, handoff settings, and routing hints.

    Args:
        station_id: Station identifier.

    Returns:
        Full station specification as JSON.

    Raises:
        404: Station not found.
    """
    try:
        library = _load_station_library()

        if not library.has_station(station_id):
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "station_not_found",
                    "message": f"Station '{station_id}' not found",
                    "details": {"station_id": station_id},
                },
            )

        station = library.get_station(station_id)
        if not station:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "station_not_found",
                    "message": f"Station '{station_id}' not found",
                    "details": {"station_id": station_id},
                },
            )

        # Convert to dict for JSON response
        from swarm.runtime.station_library import station_spec_to_dict

        return station_spec_to_dict(station)

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


@router.post("/validate")
async def validate_station_step(
    station_id: str,
    step_id: str,
):
    """Validate that a station exists and can be used for a step.

    This is a lightweight validation endpoint that checks:
    - Station exists in the library
    - Station has required configuration for execution

    Args:
        station_id: Station identifier.
        step_id: Step identifier.

    Returns:
        Validation result with valid flag and any warnings.
    """
    try:
        library = _load_station_library()

        valid = library.has_station(station_id)
        warnings = []

        if valid:
            station = library.get_station(station_id)
            if station:
                # Check for potential issues
                # Note: station.identity and station.io are dicts in StationSpec
                identity = station.identity
                io = station.io
                if isinstance(identity, dict):
                    if not identity.get("system_append"):
                        warnings.append("Station has no system_append identity")
                else:
                    if not getattr(identity, "system_append", None):
                        warnings.append("Station has no system_append identity")

                if isinstance(io, dict):
                    if not io.get("required_outputs"):
                        warnings.append("Station has no required_outputs defined")
                else:
                    if not getattr(io, "required_outputs", None):
                        warnings.append("Station has no required_outputs defined")

        return {
            "valid": valid,
            "station_id": station_id,
            "step_id": step_id,
            "warnings": warnings,
            "message": "Station found" if valid else f"Station '{station_id}' not found",
        }

    except Exception as e:
        logger.error("Validation failed: %s", e, exc_info=True)
        return {
            "valid": False,
            "station_id": station_id,
            "step_id": step_id,
            "warnings": [],
            "message": f"Validation error: {str(e)}",
        }
