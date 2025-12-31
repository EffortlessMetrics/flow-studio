"""
Facts endpoints for Flow Studio API.

Provides REST endpoints for:
- Getting facts summary for a run (marker counts, per-flow counts, deltas)
- Querying facts by marker type
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from swarm.config.flow_registry import get_flow_order
from swarm.runtime.fact_extraction import (
    MARKER_TYPES,
    extract_facts_from_run,
)
from swarm.runtime.storage import find_run_path

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/runs", tags=["facts"])


# =============================================================================
# Pydantic Models
# =============================================================================


class MarkerCount(BaseModel):
    """Count for a single marker type."""

    marker_type: str = Field(..., description="Marker type prefix (REQ, SOL, etc.)")
    label: str = Field(..., description="Human-readable label")
    count: int = Field(..., description="Number of markers of this type")


class FlowMarkerCounts(BaseModel):
    """Marker counts for a single flow."""

    flow_key: str = Field(..., description="Flow key (signal, plan, etc.)")
    counts: Dict[str, int] = Field(default_factory=dict, description="Counts by marker type")
    total: int = Field(0, description="Total markers in this flow")


class StepMarkerCounts(BaseModel):
    """Marker counts for a single step within a flow."""

    flow_key: str = Field(..., description="Flow key")
    step_id: str = Field(..., description="Step identifier")
    counts: Dict[str, int] = Field(default_factory=dict, description="Counts by marker type")
    total: int = Field(0, description="Total markers in this step")


class MarkerDelta(BaseModel):
    """Delta in marker counts between consecutive steps."""

    from_step: str = Field(..., description="Previous step (flow:step_id)")
    to_step: str = Field(..., description="Current step (flow:step_id)")
    deltas: Dict[str, int] = Field(
        default_factory=dict,
        description="Change in count by marker type (+/- values)",
    )
    total_delta: int = Field(0, description="Net change in total markers")


class FactsSummaryResponse(BaseModel):
    """Response for facts summary endpoint."""

    run_id: str = Field(..., description="Run identifier")
    total_facts: int = Field(0, description="Total facts extracted")
    by_type: List[MarkerCount] = Field(default_factory=list, description="Counts per marker type")
    by_flow: List[FlowMarkerCounts] = Field(default_factory=list, description="Counts per flow")
    by_step: List[StepMarkerCounts] = Field(default_factory=list, description="Counts per step")
    deltas: List[MarkerDelta] = Field(
        default_factory=list, description="Deltas between consecutive steps"
    )
    errors: List[str] = Field(default_factory=list, description="Errors during extraction")


class FactDetail(BaseModel):
    """A single fact detail."""

    marker_id: str = Field(..., description="Marker ID (e.g., REQ_001)")
    marker_type: str = Field(..., description="Marker type prefix")
    content: str = Field(..., description="Fact content/description")
    flow_key: Optional[str] = Field(None, description="Flow where fact was found")
    step_id: Optional[str] = Field(None, description="Step where fact was found")
    source_file: Optional[str] = Field(None, description="Source file path")
    source_line: Optional[int] = Field(None, description="Source line number")


class FactsListResponse(BaseModel):
    """Response for listing facts."""

    run_id: str = Field(..., description="Run identifier")
    facts: List[FactDetail] = Field(default_factory=list, description="List of facts")
    total: int = Field(0, description="Total facts returned")


# =============================================================================
# Endpoints
# =============================================================================


@router.get("/{run_id}/facts/summary", response_model=FactsSummaryResponse)
async def get_facts_summary(run_id: str):
    """Get summary of inventory markers for a run.

    Returns counts per marker type (REQ, SOL, TRC, ASM, DEC),
    counts per flow, counts per step, and deltas between consecutive steps.

    Args:
        run_id: Run identifier (can be in runs/ or examples/).

    Returns:
        FactsSummaryResponse with comprehensive marker statistics.

    Raises:
        404: Run not found.
    """
    # Find run path (checks both runs/ and examples/)
    run_base = find_run_path(run_id)
    if run_base is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "run_not_found",
                "message": f"Run '{run_id}' not found",
                "details": {"run_id": run_id},
            },
        )

    # Extract all facts from the run
    result = extract_facts_from_run(run_base, run_id=run_id)

    # Initialize counters
    by_type: Dict[str, int] = defaultdict(int)
    by_flow: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    by_step: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))

    # Count facts
    for fact in result.facts:
        by_type[fact.marker_type] += 1
        if fact.flow_key:
            by_flow[fact.flow_key][fact.marker_type] += 1
            if fact.step_id:
                step_key = f"{fact.flow_key}:{fact.step_id}"
                by_step[step_key][fact.marker_type] += 1

    # Build by_type response
    type_counts = []
    for marker_type in MARKER_TYPES:
        if marker_type in by_type or True:  # Always include all types
            type_counts.append(
                MarkerCount(
                    marker_type=marker_type,
                    label=MARKER_TYPES.get(marker_type, marker_type),
                    count=by_type.get(marker_type, 0),
                )
            )

    # Build by_flow response (from registry, includes review)
    flow_order = get_flow_order()
    flow_counts = []
    for flow_key in flow_order:
        if flow_key in by_flow:
            counts = dict(by_flow[flow_key])
            flow_counts.append(
                FlowMarkerCounts(
                    flow_key=flow_key,
                    counts=counts,
                    total=sum(counts.values()),
                )
            )

    # Build by_step response (sorted by flow order, then step_id)
    step_counts = []
    sorted_steps = sorted(
        by_step.keys(),
        key=lambda k: (
            flow_order.index(k.split(":")[0]) if k.split(":")[0] in flow_order else 99,
            k.split(":")[1] if ":" in k else "",
        ),
    )

    for step_key in sorted_steps:
        flow_key, step_id = step_key.split(":", 1)
        counts = dict(by_step[step_key])
        step_counts.append(
            StepMarkerCounts(
                flow_key=flow_key,
                step_id=step_id,
                counts=counts,
                total=sum(counts.values()),
            )
        )

    # Calculate deltas between consecutive steps
    deltas = []
    for i in range(1, len(step_counts)):
        prev_step = step_counts[i - 1]
        curr_step = step_counts[i]

        delta_counts: Dict[str, int] = {}
        for marker_type in MARKER_TYPES:
            prev_count = prev_step.counts.get(marker_type, 0)
            curr_count = curr_step.counts.get(marker_type, 0)
            diff = curr_count - prev_count
            if diff != 0:
                delta_counts[marker_type] = diff

        total_delta = curr_step.total - prev_step.total

        if delta_counts or total_delta != 0:
            deltas.append(
                MarkerDelta(
                    from_step=f"{prev_step.flow_key}:{prev_step.step_id}",
                    to_step=f"{curr_step.flow_key}:{curr_step.step_id}",
                    deltas=delta_counts,
                    total_delta=total_delta,
                )
            )

    return FactsSummaryResponse(
        run_id=run_id,
        total_facts=len(result.facts),
        by_type=type_counts,
        by_flow=flow_counts,
        by_step=step_counts,
        deltas=deltas,
        errors=result.errors,
    )


@router.get("/{run_id}/facts", response_model=FactsListResponse)
async def list_facts(
    run_id: str,
    marker_type: Optional[str] = None,
    flow_key: Optional[str] = None,
):
    """List all facts for a run.

    Args:
        run_id: Run identifier.
        marker_type: Optional filter by marker type (REQ, SOL, etc.).
        flow_key: Optional filter by flow key.

    Returns:
        FactsListResponse with list of facts.

    Raises:
        404: Run not found.
    """
    # Find run path
    run_base = find_run_path(run_id)
    if run_base is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "run_not_found",
                "message": f"Run '{run_id}' not found",
                "details": {"run_id": run_id},
            },
        )

    # Extract facts
    result = extract_facts_from_run(run_base, run_id=run_id)

    # Filter facts
    facts = result.facts
    if marker_type:
        facts = [f for f in facts if f.marker_type == marker_type.upper()]
    if flow_key:
        facts = [f for f in facts if f.flow_key == flow_key]

    # Build response
    fact_details = [
        FactDetail(
            marker_id=f.marker_id,
            marker_type=f.marker_type,
            content=f.content,
            flow_key=f.flow_key,
            step_id=f.step_id,
            source_file=f.source_file,
            source_line=f.source_line,
        )
        for f in facts
    ]

    return FactsListResponse(
        run_id=run_id,
        facts=fact_details,
        total=len(fact_details),
    )
