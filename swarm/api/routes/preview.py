"""
Preview endpoints for Flow Studio API.

Provides REST endpoints to safely preview configuration changes before applying:
- Model policy preview: See effective models and resolution chains
- Station preview: See resolved model, tools, compiled prompt
- Flow validation: Validate flow graph schema and referential integrity

These are read-only preview endpoints that compute what would happen
without actually modifying any state.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/preview", tags=["preview"])


# =============================================================================
# Pydantic Models
# =============================================================================


class ModelPolicyPreviewRequest(BaseModel):
    """Request for model policy preview endpoint."""

    user_preferences: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Proposed user preferences (primary_model, etc.)",
    )
    tiers: Optional[Dict[str, str]] = Field(
        default=None,
        description="Proposed tier definitions (primary, economy, standard, elite, edge)",
    )
    group_assignments: Optional[Dict[str, str]] = Field(
        default=None,
        description="Proposed category to tier assignments",
    )


class ModelPolicyPreviewResponse(BaseModel):
    """Response for model policy preview endpoint."""

    effective_models: Dict[str, str] = Field(
        description="Mapping of station_id to resolved tier alias"
    )
    resolution_chain: Dict[str, List[str]] = Field(
        description="Mapping of station_id to resolution chain showing how model was resolved"
    )
    affected_stations_count: int = Field(
        description="Number of stations affected by the proposed changes"
    )
    diff_summary: str = Field(
        description="Human-readable summary of changes"
    )


class StationPreviewResponse(BaseModel):
    """Response for station preview endpoint."""

    resolved_model: str = Field(
        description="Resolved model tier alias (haiku, sonnet, opus)"
    )
    resolved_tools: List[str] = Field(
        description="List of allowed tools for this station"
    )
    compiled_system_prompt: str = Field(
        description="First 500 characters of compiled system prompt"
    )
    injected_fragments: List[str] = Field(
        description="List of fragment paths injected into the prompt"
    )
    output_contracts: List[str] = Field(
        description="Required output artifacts for this station"
    )


class ReferentialIntegrity(BaseModel):
    """Referential integrity check results."""

    missing_stations: List[str] = Field(
        default_factory=list,
        description="Station template_ids referenced but not found"
    )
    missing_nodes: List[str] = Field(
        default_factory=list,
        description="Node IDs referenced in edges but not defined"
    )
    orphan_edges: List[str] = Field(
        default_factory=list,
        description="Edge IDs that reference non-existent nodes"
    )


class FlowValidationResponse(BaseModel):
    """Response for flow validation endpoint."""

    schema_valid: bool = Field(
        description="Whether the flow passes JSON schema validation"
    )
    schema_errors: List[str] = Field(
        default_factory=list,
        description="List of schema validation errors"
    )
    referential_integrity: ReferentialIntegrity = Field(
        description="Referential integrity check results"
    )
    warnings: List[str] = Field(
        default_factory=list,
        description="Non-fatal warnings about the flow configuration"
    )


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
    try:
        from swarm.runtime.station_library import load_station_library

        repo_root = _get_repo_root()
        return load_station_library(repo_root)
    except ImportError:
        return None


def _get_all_station_ids() -> List[str]:
    """Get all station IDs from the spec/stations directory."""
    repo_root = _get_repo_root()
    stations_dir = repo_root / "swarm" / "spec" / "stations"
    station_ids = []

    if stations_dir.exists():
        # Look for both .yaml and .json station files
        for yaml_file in stations_dir.glob("*.yaml"):
            station_ids.append(yaml_file.stem)
        for json_file in stations_dir.glob("*.station.json"):
            # Remove .station.json suffix
            station_id = json_file.stem
            if station_id.endswith(".station"):
                station_id = station_id[:-8]
            if station_id not in station_ids:
                station_ids.append(station_id)

    return sorted(station_ids)


def _load_station_spec(station_id: str) -> Optional[Dict[str, Any]]:
    """Load a station spec by ID."""
    import yaml

    repo_root = _get_repo_root()
    stations_dir = repo_root / "swarm" / "spec" / "stations"

    # Try YAML first
    yaml_path = stations_dir / f"{station_id}.yaml"
    if yaml_path.exists():
        with open(yaml_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    # Try JSON station file
    json_path = stations_dir / f"{station_id}.station.json"
    if json_path.exists():
        with open(json_path, "r", encoding="utf-8") as f:
            return json.load(f)

    return None


def _load_flow_graph(flow_id: str) -> Optional[Dict[str, Any]]:
    """Load a flow graph by ID."""
    repo_root = _get_repo_root()

    # Try spec/flows first (JSON graphs)
    flows_dir = repo_root / "swarm" / "spec" / "flows"
    json_path = flows_dir / f"{flow_id}.graph.json"
    if json_path.exists():
        with open(json_path, "r", encoding="utf-8") as f:
            return json.load(f)

    # Try without .graph suffix
    json_path = flows_dir / f"{flow_id}.json"
    if json_path.exists():
        with open(json_path, "r", encoding="utf-8") as f:
            return json.load(f)

    return None


def _load_model_policy() -> Dict[str, Any]:
    """Load the current model policy from disk."""
    repo_root = _get_repo_root()
    policy_path = repo_root / "swarm" / "config" / "model_policy.json"

    if policy_path.exists():
        with open(policy_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _resolve_tier_to_alias(tier_name: str, policy: Dict[str, Any]) -> str:
    """Resolve a tier name to a canonical SDK alias."""
    tiers = policy.get("tiers", {})
    user_prefs = policy.get("user_preferences", {})
    user_primary = user_prefs.get("primary_model", "sonnet")

    tier_def = tiers.get(tier_name, tier_name)

    # Handle user primary resolution
    if tier_def == "inherit_user_primary":
        return user_primary

    # If it's already a valid tier alias
    if tier_def in ("haiku", "sonnet", "opus"):
        return tier_def

    # Fallback
    return "sonnet"


def _resolve_station_model(
    station_spec: Dict[str, Any],
    policy: Dict[str, Any],
) -> tuple[str, List[str]]:
    """Resolve a station's model to a tier alias and return resolution chain.

    Returns:
        Tuple of (resolved_alias, resolution_chain)
    """
    chain = []

    # Get model from station spec
    sdk = station_spec.get("sdk", {})
    model_value = sdk.get("model", "inherit")
    category = station_spec.get("category", "")

    chain.append(f"station.sdk.model = {model_value}")

    # If already a valid tier, return it
    if model_value in ("haiku", "sonnet", "opus"):
        chain.append(f"direct tier -> {model_value}")
        return model_value, chain

    # Handle "inherit" by looking up category via policy
    if model_value.lower() == "inherit":
        group_assignments = policy.get("group_assignments", {})
        tier_name = group_assignments.get(category.lower(), "standard")
        chain.append(f"category={category} -> group_assignments[{category}] = {tier_name}")

        resolved = _resolve_tier_to_alias(tier_name, policy)
        chain.append(f"tier {tier_name} -> {resolved}")
        return resolved, chain

    # Pass through unknown values
    chain.append(f"unknown model value, pass through -> {model_value}")
    return model_value, chain


# =============================================================================
# Endpoints
# =============================================================================


@router.post("/settings/model-policy", response_model=ModelPolicyPreviewResponse)
async def preview_model_policy(request: ModelPolicyPreviewRequest):
    """Preview the effect of proposed model policy changes.

    This endpoint computes what models would be assigned to each station
    if the proposed policy changes were applied. It does NOT modify any state.

    The response includes:
    - effective_models: The resolved model tier for each station
    - resolution_chain: How each station's model was resolved (for debugging)
    - affected_stations_count: How many stations would be affected
    - diff_summary: Human-readable summary of changes

    Args:
        request: Proposed model policy changes.

    Returns:
        ModelPolicyPreviewResponse with preview of effective changes.

    Raises:
        500: If preview computation fails.
    """
    try:
        # Load current policy
        current_policy = _load_model_policy()

        # Build proposed policy by merging changes
        proposed_policy = {
            "user_preferences": current_policy.get("user_preferences", {"primary_model": "sonnet"}),
            "tiers": current_policy.get("tiers", {
                "primary": "inherit_user_primary",
                "economy": "haiku",
                "standard": "sonnet",
                "elite": "opus",
                "edge": "sonnet",
            }),
            "group_assignments": current_policy.get("group_assignments", {}),
        }

        # Apply proposed changes
        if request.user_preferences:
            proposed_policy["user_preferences"] = {
                **proposed_policy["user_preferences"],
                **request.user_preferences,
            }
        if request.tiers:
            proposed_policy["tiers"] = {
                **proposed_policy["tiers"],
                **request.tiers,
            }
        if request.group_assignments:
            proposed_policy["group_assignments"] = {
                **proposed_policy["group_assignments"],
                **request.group_assignments,
            }

        # Get all station IDs
        station_ids = _get_all_station_ids()

        # Compute effective models for each station
        effective_models: Dict[str, str] = {}
        resolution_chains: Dict[str, List[str]] = {}
        current_models: Dict[str, str] = {}

        for station_id in station_ids:
            station_spec = _load_station_spec(station_id)
            if station_spec:
                # Compute with proposed policy
                resolved, chain = _resolve_station_model(station_spec, proposed_policy)
                effective_models[station_id] = resolved
                resolution_chains[station_id] = chain

                # Compute with current policy for diff
                current_resolved, _ = _resolve_station_model(station_spec, current_policy)
                current_models[station_id] = current_resolved

        # Count affected stations (those that would change)
        affected_count = sum(
            1 for sid in effective_models
            if effective_models[sid] != current_models.get(sid, "")
        )

        # Build diff summary
        diff_lines = []
        for station_id in sorted(effective_models.keys()):
            current = current_models.get(station_id, "unknown")
            proposed = effective_models[station_id]
            if current != proposed:
                diff_lines.append(f"  {station_id}: {current} -> {proposed}")

        if diff_lines:
            diff_summary = f"Changes ({affected_count} stations):\n" + "\n".join(diff_lines)
        else:
            diff_summary = "No changes - proposed policy matches current configuration"

        return ModelPolicyPreviewResponse(
            effective_models=effective_models,
            resolution_chain=resolution_chains,
            affected_stations_count=affected_count,
            diff_summary=diff_summary,
        )

    except Exception as e:
        logger.error("Model policy preview failed: %s", e, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "error": "preview_error",
                "message": f"Failed to compute model policy preview: {str(e)}",
                "details": {},
            },
        )


@router.post("/spec/stations/{station_id}", response_model=StationPreviewResponse)
async def preview_station(station_id: str):
    """Preview a station's resolved configuration.

    This endpoint shows what a station would look like when compiled:
    - The resolved model tier (after policy resolution)
    - The allowed tools
    - The compiled system prompt (first 500 chars)
    - Injected prompt fragments
    - Required output artifacts (output contracts)

    Args:
        station_id: Station identifier (e.g., 'code-implementer').

    Returns:
        StationPreviewResponse with resolved station configuration.

    Raises:
        404: If station not found.
        500: If preview computation fails.
    """
    try:
        station_spec = _load_station_spec(station_id)

        if not station_spec:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "station_not_found",
                    "message": f"Station '{station_id}' not found",
                    "details": {"station_id": station_id},
                },
            )

        # Load current policy for model resolution
        policy = _load_model_policy()

        # Resolve model
        resolved_model, _ = _resolve_station_model(station_spec, policy)

        # Get allowed tools
        sdk = station_spec.get("sdk", {})
        allowed_tools = sdk.get("allowed_tools", [])
        if isinstance(allowed_tools, list):
            resolved_tools = [str(t) for t in allowed_tools]
        else:
            resolved_tools = []

        # Get system prompt (first 500 chars)
        identity = station_spec.get("identity", {})
        system_append = identity.get("system_append", "")
        if isinstance(system_append, str):
            compiled_system_prompt = system_append[:500]
            if len(system_append) > 500:
                compiled_system_prompt += "..."
        else:
            compiled_system_prompt = ""

        # Get injected fragments
        runtime_prompt = station_spec.get("runtime_prompt", {})
        fragments = runtime_prompt.get("fragments", [])
        if isinstance(fragments, list):
            injected_fragments = [str(f) for f in fragments]
        else:
            injected_fragments = []

        # Also include policy refs as fragments
        policy_config = station_spec.get("policy", {})
        invariants_ref = policy_config.get("invariants_ref", [])
        handoff_ref = policy_config.get("handoff_ref", [])

        if isinstance(invariants_ref, list):
            injected_fragments.extend([str(f) for f in invariants_ref])
        if isinstance(handoff_ref, list):
            injected_fragments.extend([str(f) for f in handoff_ref])

        # Get output contracts (required outputs)
        io = station_spec.get("io", {})
        required_outputs = io.get("required_outputs", [])
        if isinstance(required_outputs, list):
            output_contracts = [str(o) for o in required_outputs]
        else:
            output_contracts = []

        return StationPreviewResponse(
            resolved_model=resolved_model,
            resolved_tools=resolved_tools,
            compiled_system_prompt=compiled_system_prompt,
            injected_fragments=injected_fragments,
            output_contracts=output_contracts,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Station preview failed for %s: %s", station_id, e, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "error": "preview_error",
                "message": f"Failed to preview station: {str(e)}",
                "details": {"station_id": station_id},
            },
        )


@router.post("/spec/flows/{flow_id}/validate", response_model=FlowValidationResponse)
async def validate_flow(flow_id: str):
    """Validate a flow graph's schema and referential integrity.

    This endpoint checks:
    1. JSON Schema validation against flow_graph.schema.json
    2. Referential integrity:
       - All template_ids reference existing stations
       - All edge from/to reference existing nodes
       - No orphan edges
    3. Warnings for potential issues (non-fatal)

    Args:
        flow_id: Flow identifier (e.g., 'build-flow').

    Returns:
        FlowValidationResponse with validation results.

    Raises:
        404: If flow not found.
        500: If validation fails.
    """
    try:
        flow_graph = _load_flow_graph(flow_id)

        if not flow_graph:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "flow_not_found",
                    "message": f"Flow '{flow_id}' not found",
                    "details": {"flow_id": flow_id},
                },
            )

        schema_errors: List[str] = []
        warnings: List[str] = []
        missing_stations: List[str] = []
        missing_nodes: List[str] = []
        orphan_edges: List[str] = []

        # Schema validation
        schema_valid = True
        try:
            import jsonschema

            repo_root = _get_repo_root()
            schema_path = repo_root / "swarm" / "spec" / "schemas" / "flow_graph.schema.json"

            if schema_path.exists():
                with open(schema_path, "r", encoding="utf-8") as f:
                    schema = json.load(f)

                validator = jsonschema.Draft7Validator(schema)
                for error in validator.iter_errors(flow_graph):
                    schema_valid = False
                    # Format error path
                    path = ".".join(str(p) for p in error.absolute_path)
                    if path:
                        schema_errors.append(f"{path}: {error.message}")
                    else:
                        schema_errors.append(error.message)
            else:
                warnings.append("Schema file not found - skipping schema validation")

        except ImportError:
            warnings.append("jsonschema not installed - skipping schema validation")
        except Exception as e:
            schema_valid = False
            schema_errors.append(f"Schema validation error: {str(e)}")

        # Build set of node IDs
        nodes = flow_graph.get("nodes", [])
        node_ids = set()
        for node in nodes:
            node_id = node.get("node_id")
            if node_id:
                node_ids.add(node_id)

        # Check referential integrity - template_ids
        existing_station_ids = set(_get_all_station_ids())

        for node in nodes:
            template_id = node.get("template_id", "")
            node_id = node.get("node_id", "unknown")

            # Check if template exists (station or built-in)
            # Allow built-in templates like "run-prep"
            if template_id and template_id not in existing_station_ids:
                # Check if it might be a built-in or special template
                builtin_templates = {"run-prep", "flow-start", "flow-end"}
                if template_id not in builtin_templates:
                    missing_stations.append(f"{template_id} (referenced by node '{node_id}')")

        # Check referential integrity - edges
        edges = flow_graph.get("edges", [])
        for edge in edges:
            edge_id = edge.get("edge_id", "unknown")
            from_node = edge.get("from", "")
            to_node = edge.get("to", "")

            if from_node and from_node not in node_ids:
                missing_nodes.append(f"'{from_node}' (referenced by edge '{edge_id}')")
                orphan_edges.append(edge_id)

            if to_node and to_node not in node_ids:
                missing_nodes.append(f"'{to_node}' (referenced by edge '{edge_id}')")
                if edge_id not in orphan_edges:
                    orphan_edges.append(edge_id)

        # Check subflows referential integrity
        subflows = flow_graph.get("subflows", [])
        for subflow in subflows:
            subflow_id = subflow.get("subflow_id", "unknown")

            entry_node = subflow.get("entry_node", "")
            if entry_node and entry_node not in node_ids:
                missing_nodes.append(f"'{entry_node}' (entry node for subflow '{subflow_id}')")

            exit_nodes = subflow.get("exit_nodes", [])
            for exit_node in exit_nodes:
                if exit_node and exit_node not in node_ids:
                    missing_nodes.append(f"'{exit_node}' (exit node for subflow '{subflow_id}')")

            contained_nodes = subflow.get("contained_nodes", [])
            for contained in contained_nodes:
                if contained and contained not in node_ids:
                    missing_nodes.append(f"'{contained}' (contained in subflow '{subflow_id}')")

        # Add warnings for potential issues
        if not nodes:
            warnings.append("Flow has no nodes defined")

        if not edges and len(nodes) > 1:
            warnings.append("Flow has multiple nodes but no edges connecting them")

        # Check for unreachable nodes (no incoming edges except entry)
        if edges and nodes:
            target_nodes = set(edge.get("to") for edge in edges if edge.get("to"))
            source_nodes = set(edge.get("from") for edge in edges if edge.get("from"))

            # First node is typically entry, doesn't need incoming
            entry_candidates = node_ids - target_nodes
            if len(entry_candidates) > 1:
                warnings.append(
                    f"Multiple potential entry nodes (no incoming edges): {sorted(entry_candidates)}"
                )

            # Nodes with no outgoing edges (should be exit nodes or OK)
            exit_candidates = node_ids - source_nodes
            # This is often fine, just informational

        # Deduplicate missing items
        missing_stations = list(set(missing_stations))
        missing_nodes = list(set(missing_nodes))
        orphan_edges = list(set(orphan_edges))

        return FlowValidationResponse(
            schema_valid=schema_valid,
            schema_errors=schema_errors,
            referential_integrity=ReferentialIntegrity(
                missing_stations=missing_stations,
                missing_nodes=missing_nodes,
                orphan_edges=orphan_edges,
            ),
            warnings=warnings,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Flow validation failed for %s: %s", flow_id, e, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "error": "validation_error",
                "message": f"Failed to validate flow: {str(e)}",
                "details": {"flow_id": flow_id},
            },
        )
