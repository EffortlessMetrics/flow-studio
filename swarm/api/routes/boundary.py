"""
Boundary review endpoints for Flow Studio API.

Provides REST endpoints for:
- Getting boundary review summary for a run
  (aggregates assumptions, decisions, detours, verification)
- Used by operators to review run state at flow boundaries
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from swarm.config.flow_registry import get_flow_order
from swarm.runtime.storage import find_run_path

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/runs", tags=["boundary"])


# =============================================================================
# Pydantic Models
# =============================================================================


class AssumptionSummary(BaseModel):
    """Summary of an assumption."""

    assumption_id: str
    statement: str
    rationale: str
    impact_if_wrong: str
    confidence: str = "medium"
    status: str = "active"
    tags: List[str] = Field(default_factory=list)
    flow_introduced: Optional[str] = None
    step_introduced: Optional[str] = None
    agent: Optional[str] = None
    timestamp: Optional[str] = None


class DecisionSummary(BaseModel):
    """Summary of a decision."""

    decision_id: str
    decision_type: str
    subject: str
    decision: str
    rationale: str
    supporting_evidence: List[str] = Field(default_factory=list)
    conditions: List[str] = Field(default_factory=list)
    assumptions_applied: List[str] = Field(default_factory=list)
    flow: Optional[str] = None
    step: Optional[str] = None
    agent: Optional[str] = None
    timestamp: Optional[str] = None


class DetourSummary(BaseModel):
    """Summary of a detour taken during execution."""

    detour_id: str
    from_step: str
    to_step: str
    reason: str
    detour_type: str = "sidequest"
    evidence_path: Optional[str] = None
    timestamp: Optional[str] = None


class VerificationSummary(BaseModel):
    """Verification result for a step."""

    step_id: str
    station_id: Optional[str] = None
    status: str
    verified: bool = False
    can_further_iteration_help: Optional[bool] = None
    issues: List[str] = Field(default_factory=list)
    timestamp: Optional[str] = None


class InventoryDelta(BaseModel):
    """Inventory marker delta between steps."""

    marker_type: str
    label: str
    count: int
    delta: int = 0


class BoundaryReviewResponse(BaseModel):
    """Response for boundary review endpoint."""

    run_id: str
    scope: str = "flow"  # "flow" or "run"
    current_flow: Optional[str] = None

    # Assumptions
    assumptions_count: int = 0
    assumptions_high_risk: int = 0
    assumptions: List[AssumptionSummary] = Field(default_factory=list)

    # Decisions
    decisions_count: int = 0
    decisions: List[DecisionSummary] = Field(default_factory=list)

    # Detours taken
    detours_count: int = 0
    detours: List[DetourSummary] = Field(default_factory=list)

    # Verification results
    verification_passed: int = 0
    verification_failed: int = 0
    verifications: List[VerificationSummary] = Field(default_factory=list)

    # Inventory deltas
    inventory_deltas: List[InventoryDelta] = Field(default_factory=list)

    # Evolution suggestions (from wisdom)
    has_evolution_patches: bool = False
    evolution_patch_count: int = 0

    # Summary metrics
    confidence_score: float = 1.0  # 0.0 to 1.0 based on assumption risk
    uncertainty_notes: List[str] = Field(default_factory=list)

    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# =============================================================================
# Helper Functions
# =============================================================================


def _get_runs_root() -> Path:
    """Get the runs root directory."""
    from ..server import get_spec_manager

    manager = get_spec_manager()
    return manager.runs_root


def _aggregate_assumptions(envelopes: List[Dict[str, Any]]) -> List[AssumptionSummary]:
    """Aggregate assumptions from all envelopes."""
    assumptions = []
    seen_ids = set()

    for envelope in envelopes:
        for asm in envelope.get("assumptions_made", []):
            asm_id = asm.get("assumption_id", "")
            if asm_id and asm_id not in seen_ids:
                seen_ids.add(asm_id)
                assumptions.append(
                    AssumptionSummary(
                        assumption_id=asm_id,
                        statement=asm.get("statement", ""),
                        rationale=asm.get("rationale", ""),
                        impact_if_wrong=asm.get("impact_if_wrong", ""),
                        confidence=asm.get("confidence", "medium"),
                        status=asm.get("status", "active"),
                        tags=asm.get("tags", []),
                        flow_introduced=asm.get("flow_introduced"),
                        step_introduced=asm.get("step_introduced"),
                        agent=asm.get("agent"),
                        timestamp=asm.get("timestamp"),
                    )
                )

    return assumptions


def _aggregate_decisions(envelopes: List[Dict[str, Any]]) -> List[DecisionSummary]:
    """Aggregate decisions from all envelopes."""
    decisions = []
    seen_ids = set()

    for envelope in envelopes:
        for dec in envelope.get("decisions_made", []):
            dec_id = dec.get("decision_id", "")
            if dec_id and dec_id not in seen_ids:
                seen_ids.add(dec_id)
                decisions.append(
                    DecisionSummary(
                        decision_id=dec_id,
                        decision_type=dec.get("decision_type", ""),
                        subject=dec.get("subject", ""),
                        decision=dec.get("decision", ""),
                        rationale=dec.get("rationale", ""),
                        supporting_evidence=dec.get("supporting_evidence", []),
                        conditions=dec.get("conditions", []),
                        assumptions_applied=dec.get("assumptions_applied", []),
                        flow=dec.get("flow"),
                        step=dec.get("step"),
                        agent=dec.get("agent"),
                        timestamp=dec.get("timestamp"),
                    )
                )

    return decisions


def _extract_detours(envelopes: List[Dict[str, Any]]) -> List[DetourSummary]:
    """Extract detour information from envelopes' routing signals."""
    detours = []
    detour_idx = 0

    for envelope in envelopes:
        routing = envelope.get("routing_signal", {})
        decision = routing.get("decision", "")

        if decision in ("EXTEND_GRAPH", "DETOUR"):
            detour_idx += 1
            detours.append(
                DetourSummary(
                    detour_id=f"DETOUR-{detour_idx:03d}",
                    from_step=envelope.get("step_id", ""),
                    to_step=routing.get("next_step", routing.get("target", "")),
                    reason=routing.get("reason", routing.get("rationale", "")),
                    detour_type=routing.get("detour_type", "sidequest"),
                    evidence_path=routing.get("evidence_path"),
                    timestamp=envelope.get("timestamp"),
                )
            )

    return detours


def _extract_verifications(envelopes: List[Dict[str, Any]]) -> List[VerificationSummary]:
    """Extract verification results from envelopes."""
    verifications = []

    for envelope in envelopes:
        step_id = envelope.get("step_id", "")
        status = envelope.get("status", "")
        verification = envelope.get("verification", {})

        if step_id:
            # Determine verified status
            verified = status == "VERIFIED" or verification.get("verified", False)

            # Extract issues
            issues = []
            if not verified:
                critique = envelope.get("critique", {})
                if isinstance(critique, dict):
                    issues = critique.get("issues", [])
                elif isinstance(critique, str) and critique:
                    issues = [critique]

            verifications.append(
                VerificationSummary(
                    step_id=step_id,
                    station_id=envelope.get("station_id"),
                    status=status,
                    verified=verified,
                    can_further_iteration_help=verification.get("can_further_iteration_help"),
                    issues=issues[:5],  # Limit to top 5 issues
                    timestamp=envelope.get("timestamp"),
                )
            )

    return verifications


def _compute_confidence_score(assumptions: List[AssumptionSummary]) -> float:
    """Compute overall confidence score based on assumptions."""
    if not assumptions:
        return 1.0

    # Weight by confidence level
    weights = {"high": 1.0, "medium": 0.7, "low": 0.4}
    active_assumptions = [a for a in assumptions if a.status == "active"]

    if not active_assumptions:
        return 1.0

    total_weight = sum(weights.get(a.confidence, 0.7) for a in active_assumptions)
    avg_weight = total_weight / len(active_assumptions)

    # Penalize for number of assumptions
    penalty = min(len(active_assumptions) * 0.05, 0.3)

    return max(0.0, min(1.0, avg_weight - penalty))


def _count_high_risk_assumptions(assumptions: List[AssumptionSummary]) -> int:
    """Count assumptions that are high risk (low confidence or high impact)."""
    return sum(1 for a in assumptions if a.status == "active" and a.confidence == "low")


def _get_uncertainty_notes(
    assumptions: List[AssumptionSummary],
    detours: List[DetourSummary],
    verifications: List[VerificationSummary],
) -> List[str]:
    """Generate uncertainty notes for the boundary review."""
    notes = []

    # Low confidence assumptions
    low_conf = [a for a in assumptions if a.confidence == "low" and a.status == "active"]
    if low_conf:
        notes.append(f"{len(low_conf)} low-confidence assumption(s) remain active")

    # Multiple detours
    if len(detours) > 2:
        notes.append(f"Flow took {len(detours)} detours, suggesting complexity or ambiguity")

    # Failed verifications
    failed = [v for v in verifications if not v.verified]
    if failed:
        notes.append(f"{len(failed)} step(s) have unresolved verification issues")

    return notes


def _read_all_envelopes(run_base: Path, flow_key: Optional[str] = None) -> List[Dict[str, Any]]:
    """Read all handoff envelopes for a run, optionally filtered by flow."""
    envelopes = []

    # Flow order for iteration (from registry, includes review)
    flow_order = get_flow_order()

    if flow_key:
        flows_to_check = [flow_key]
    else:
        flows_to_check = flow_order

    for flow in flows_to_check:
        flow_path = run_base / flow / "handoff"
        if flow_path.exists():
            for envelope_file in sorted(flow_path.glob("*.json")):
                if envelope_file.name.endswith(".draft.json"):
                    continue
                try:
                    envelope = json.loads(envelope_file.read_text(encoding="utf-8"))
                    envelope["_flow_key"] = flow  # Add flow context
                    envelopes.append(envelope)
                except (json.JSONDecodeError, OSError) as e:
                    logger.warning("Failed to read envelope %s: %s", envelope_file, e)

    return envelopes


def _check_evolution_patches(run_base: Path) -> tuple[bool, int]:
    """Check for evolution patches in wisdom outputs."""
    wisdom_dir = run_base / "wisdom"
    if not wisdom_dir.exists():
        return False, 0

    # Check for patch files
    patch_files = list(wisdom_dir.glob("*.patch")) + list(wisdom_dir.glob("flow_evolution*"))

    # Also check for pending patches (not applied/rejected)
    applied = set(p.name.replace(".applied_", "") for p in wisdom_dir.glob(".applied_*"))
    rejected = set(p.name.replace(".rejected_", "") for p in wisdom_dir.glob(".rejected_*"))

    pending_count = len(
        [p for p in patch_files if p.name not in applied and p.name not in rejected]
    )

    return pending_count > 0, pending_count


# =============================================================================
# Endpoints
# =============================================================================


@router.get("/{run_id}/boundary-review", response_model=BoundaryReviewResponse)
async def get_boundary_review(
    run_id: str,
    scope: str = "flow",
    flow_key: Optional[str] = None,
):
    """Get boundary review summary for a run.

    Aggregates assumptions, decisions, detours, and verification results
    for operator review at flow boundaries.

    Args:
        run_id: Run identifier (can be in runs/ or examples/).
        scope: "flow" for current flow only, "run" for entire run.
        flow_key: Optional flow key to filter (when scope="flow").

    Returns:
        BoundaryReviewResponse with comprehensive boundary review data.

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

    # Read all envelopes
    flow_filter = flow_key if scope == "flow" else None
    envelopes = _read_all_envelopes(run_base, flow_filter)

    if not envelopes:
        return BoundaryReviewResponse(
            run_id=run_id,
            scope=scope,
            current_flow=flow_key,
        )

    # Aggregate data
    assumptions = _aggregate_assumptions(envelopes)
    decisions = _aggregate_decisions(envelopes)
    detours = _extract_detours(envelopes)
    verifications = _extract_verifications(envelopes)

    # Compute metrics
    confidence_score = _compute_confidence_score(assumptions)
    high_risk_count = _count_high_risk_assumptions(assumptions)
    uncertainty_notes = _get_uncertainty_notes(assumptions, detours, verifications)

    # Count verifications
    verified_count = sum(1 for v in verifications if v.verified)
    failed_count = sum(1 for v in verifications if not v.verified)

    # Check for evolution patches
    has_patches, patch_count = _check_evolution_patches(run_base)

    # Determine current flow from latest envelope
    current_flow = flow_key or (envelopes[-1].get("_flow_key") if envelopes else None)

    return BoundaryReviewResponse(
        run_id=run_id,
        scope=scope,
        current_flow=current_flow,
        assumptions_count=len(assumptions),
        assumptions_high_risk=high_risk_count,
        assumptions=assumptions,
        decisions_count=len(decisions),
        decisions=decisions,
        detours_count=len(detours),
        detours=detours,
        verification_passed=verified_count,
        verification_failed=failed_count,
        verifications=verifications,
        has_evolution_patches=has_patches,
        evolution_patch_count=patch_count,
        confidence_score=confidence_score,
        uncertainty_notes=uncertainty_notes,
    )
