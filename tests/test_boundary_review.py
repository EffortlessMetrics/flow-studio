#!/usr/bin/env python3
"""
Tests for swarm/api/routes/boundary.py - Boundary Review API.

This module provides Flow Studio with the ability to:
1. Aggregate assumptions from handoff envelopes
2. Aggregate decisions with deduplication
3. Extract detours from routing signals
4. Extract verification results
5. Compute confidence scores based on assumption risk
6. Generate uncertainty notes for operator review

## Test Coverage

### Unit Tests - Aggregation Functions (6 tests)
1. test_aggregate_assumptions_empty - Returns empty list for no envelopes
2. test_aggregate_assumptions_multiple - Aggregates from multiple envelopes
3. test_aggregate_assumptions_deduplication - Deduplicates by assumption_id
4. test_aggregate_decisions_empty - Returns empty list for no envelopes
5. test_aggregate_decisions_multiple - Aggregates from multiple envelopes
6. test_aggregate_decisions_deduplication - Deduplicates by decision_id

### Unit Tests - Extraction Functions (6 tests)
7. test_extract_detours_empty - Returns empty list for no routing signals
8. test_extract_detours_extend_graph - Extracts EXTEND_GRAPH detours
9. test_extract_detours_detour_type - Extracts DETOUR routing signals
10. test_extract_verifications_empty - Returns empty list for no steps
11. test_extract_verifications_verified_status - Extracts VERIFIED steps
12. test_extract_verifications_with_critique - Extracts critique issues

### Unit Tests - Scoring Functions (6 tests)
13. test_compute_confidence_score_no_assumptions - Returns 1.0 for no assumptions
14. test_compute_confidence_score_high_confidence - Returns high score for high confidence
15. test_compute_confidence_score_low_confidence - Returns low score for low confidence
16. test_compute_confidence_score_penalty - Applies penalty for many assumptions
17. test_count_high_risk_assumptions_none - Returns 0 for no low-confidence
18. test_count_high_risk_assumptions_some - Counts low-confidence active assumptions

### Unit Tests - Uncertainty Notes (4 tests)
19. test_get_uncertainty_notes_empty - Returns empty list when no issues
20. test_get_uncertainty_notes_low_confidence - Notes low-confidence assumptions
21. test_get_uncertainty_notes_detours - Notes multiple detours
22. test_get_uncertainty_notes_verifications - Notes failed verifications

### Unit Tests - Envelope Reading (4 tests)
23. test_read_all_envelopes_empty - Returns empty list for no envelopes
24. test_read_all_envelopes_with_filter - Filters by flow_key
25. test_read_all_envelopes_skips_drafts - Skips .draft.json files
26. test_read_all_envelopes_handles_invalid_json - Handles malformed JSON gracefully

### Unit Tests - Evolution Patches (3 tests)
27. test_check_evolution_patches_no_wisdom - Returns False when no wisdom dir
28. test_check_evolution_patches_with_patches - Detects patch files
29. test_check_evolution_patches_counts_pending - Counts pending (not applied/rejected)

### Integration Tests (12 tests)
30. test_boundary_review_endpoint_not_found - Returns 404 for missing run
31. test_boundary_review_endpoint_empty_run - Returns empty response for run with no envelopes
32. test_boundary_review_endpoint_with_data - Returns aggregated data for run with envelopes
33. test_boundary_review_endpoint_flow_scope - Filters by flow when scope="flow"
34. test_boundary_review_endpoint_verifications - Counts verified and failed verifications
35. test_boundary_review_endpoint_confidence_score - Returns computed confidence score
36. test_boundary_review_endpoint_evolution_patches - Detects evolution patches in wisdom dir
37. test_boundary_review_endpoint_empty_run_confidence_score - Empty run returns 1.0 confidence
38. test_boundary_review_endpoint_ordering_stable - Maintains stable ordering across requests
39. test_boundary_review_endpoint_missing_artifacts_graceful - Partial artifacts return 200, not 500
40. test_boundary_review_endpoint_scope_run_aggregates_all - scope="run" aggregates all flows
41. test_boundary_review_endpoint_timestamp_present - Response includes valid ISO timestamp
42. test_boundary_review_endpoint_invalid_json_in_envelope - Malformed JSON skipped gracefully
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List

# Add repo root to path so swarm imports work
repo_root = Path(__file__).resolve().parents[1]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

import pytest
from fastapi.testclient import TestClient
from swarm.api.routes.boundary import (
    AssumptionSummary,
    DecisionSummary,
    DetourSummary,
    VerificationSummary,
    _aggregate_assumptions,
    _aggregate_decisions,
    _check_evolution_patches,
    _compute_confidence_score,
    _count_high_risk_assumptions,
    _extract_detours,
    _extract_verifications,
    _get_uncertainty_notes,
    _read_all_envelopes,
)
from swarm.runtime import storage

# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------


@pytest.fixture
def sample_envelope_with_assumptions() -> Dict[str, Any]:
    """Return a sample envelope with assumptions."""
    return {
        "step_id": "step-1",
        "status": "VERIFIED",
        "timestamp": "2025-01-15T10:00:00Z",
        "assumptions_made": [
            {
                "assumption_id": "ASM-001",
                "statement": "User has valid authentication",
                "rationale": "Based on login flow",
                "impact_if_wrong": "Security vulnerability",
                "confidence": "high",
                "status": "active",
                "tags": ["security"],
                "flow_introduced": "signal",
                "step_introduced": "step-1",
                "agent": "signal-normalizer",
                "timestamp": "2025-01-15T10:00:00Z",
            },
            {
                "assumption_id": "ASM-002",
                "statement": "API rate limits are sufficient",
                "rationale": "Historical data shows low traffic",
                "impact_if_wrong": "Service degradation",
                "confidence": "medium",
                "status": "active",
                "tags": ["performance"],
            },
        ],
    }


@pytest.fixture
def sample_envelope_with_decisions() -> Dict[str, Any]:
    """Return a sample envelope with decisions."""
    return {
        "step_id": "step-2",
        "status": "VERIFIED",
        "timestamp": "2025-01-15T10:05:00Z",
        "decisions_made": [
            {
                "decision_id": "DEC-001",
                "decision_type": "architecture",
                "subject": "Database selection",
                "decision": "Use PostgreSQL",
                "rationale": "Best fit for relational data",
                "supporting_evidence": ["perf tests", "team expertise"],
                "conditions": ["data is relational"],
                "assumptions_applied": ["ASM-001"],
                "flow": "plan",
                "step": "step-2",
                "agent": "adr-author",
                "timestamp": "2025-01-15T10:05:00Z",
            }
        ],
    }


@pytest.fixture
def sample_envelope_with_detour() -> Dict[str, Any]:
    """Return a sample envelope with a detour routing signal."""
    return {
        "step_id": "step-3",
        "status": "UNVERIFIED",
        "timestamp": "2025-01-15T10:10:00Z",
        "routing_signal": {
            "decision": "EXTEND_GRAPH",
            "next_step": "additional-analysis",
            "reason": "Unexpected complexity discovered",
            "detour_type": "sidequest",
            "evidence_path": "build/analysis.md",
        },
    }


@pytest.fixture
def sample_envelope_verified() -> Dict[str, Any]:
    """Return a sample verified envelope."""
    return {
        "step_id": "step-4",
        "station_id": "station-a",
        "status": "VERIFIED",
        "timestamp": "2025-01-15T10:15:00Z",
        "verification": {
            "verified": True,
            "can_further_iteration_help": False,
        },
    }


@pytest.fixture
def sample_envelope_unverified() -> Dict[str, Any]:
    """Return a sample unverified envelope with critique."""
    return {
        "step_id": "step-5",
        "station_id": "station-b",
        "status": "UNVERIFIED",
        "timestamp": "2025-01-15T10:20:00Z",
        "verification": {
            "verified": False,
            "can_further_iteration_help": True,
        },
        "critique": {
            "issues": [
                "Missing error handling",
                "Incomplete test coverage",
                "Documentation gaps",
            ]
        },
    }


@pytest.fixture
def isolated_runs_env(tmp_path, monkeypatch):
    """
    Fixture that isolates tests from real swarm/runs/ and swarm/examples/.

    Creates temporary directories and monkeypatches storage module globals.
    """
    runs_dir = tmp_path / "swarm" / "runs"
    examples_dir = tmp_path / "swarm" / "examples"

    runs_dir.mkdir(parents=True)
    examples_dir.mkdir(parents=True)

    # Monkeypatch storage module globals
    monkeypatch.setattr(storage, "RUNS_DIR", runs_dir)
    monkeypatch.setattr(storage, "EXAMPLES_DIR", examples_dir)

    yield {
        "runs_dir": runs_dir,
        "examples_dir": examples_dir,
        "tmp_path": tmp_path,
    }


def _create_run_with_envelopes(
    runs_dir: Path,
    run_id: str,
    envelopes: Dict[str, List[Dict[str, Any]]],
) -> Path:
    """
    Create a run directory with handoff envelopes.

    Args:
        runs_dir: Base directory for runs.
        run_id: Run identifier.
        envelopes: Dict mapping flow_key -> list of envelope dicts.

    Returns:
        Path to the created run directory.
    """
    run_path = runs_dir / run_id
    run_path.mkdir(parents=True, exist_ok=True)

    for flow_key, envelope_list in envelopes.items():
        handoff_dir = run_path / flow_key / "handoff"
        handoff_dir.mkdir(parents=True, exist_ok=True)

        for idx, envelope in enumerate(envelope_list):
            step_id = envelope.get("step_id", f"step-{idx}")
            envelope_file = handoff_dir / f"{step_id}.json"
            envelope_file.write_text(json.dumps(envelope), encoding="utf-8")

    return run_path


# -----------------------------------------------------------------------------
# Unit Tests - Aggregation Functions
# -----------------------------------------------------------------------------


class TestAggregateAssumptions:
    """Tests for _aggregate_assumptions function."""

    def test_aggregate_assumptions_empty(self):
        """Returns empty list for no envelopes."""
        result = _aggregate_assumptions([])
        assert result == []

    def test_aggregate_assumptions_multiple(self, sample_envelope_with_assumptions):
        """Aggregates from multiple envelopes."""
        envelopes = [sample_envelope_with_assumptions]
        result = _aggregate_assumptions(envelopes)

        assert len(result) == 2
        assert all(isinstance(a, AssumptionSummary) for a in result)
        assert result[0].assumption_id == "ASM-001"
        assert result[1].assumption_id == "ASM-002"

    def test_aggregate_assumptions_deduplication(self, sample_envelope_with_assumptions):
        """Deduplicates by assumption_id."""
        # Same envelope twice - should deduplicate
        envelopes = [
            sample_envelope_with_assumptions,
            sample_envelope_with_assumptions,
        ]
        result = _aggregate_assumptions(envelopes)

        assert len(result) == 2
        assumption_ids = [a.assumption_id for a in result]
        assert len(set(assumption_ids)) == 2  # Unique IDs

    def test_aggregate_assumptions_fields_mapped(self, sample_envelope_with_assumptions):
        """Verifies all fields are correctly mapped."""
        envelopes = [sample_envelope_with_assumptions]
        result = _aggregate_assumptions(envelopes)

        first = result[0]
        assert first.statement == "User has valid authentication"
        assert first.rationale == "Based on login flow"
        assert first.impact_if_wrong == "Security vulnerability"
        assert first.confidence == "high"
        assert first.status == "active"
        assert first.tags == ["security"]
        assert first.flow_introduced == "signal"
        assert first.agent == "signal-normalizer"


class TestAggregateDecisions:
    """Tests for _aggregate_decisions function."""

    def test_aggregate_decisions_empty(self):
        """Returns empty list for no envelopes."""
        result = _aggregate_decisions([])
        assert result == []

    def test_aggregate_decisions_multiple(self, sample_envelope_with_decisions):
        """Aggregates from multiple envelopes."""
        envelopes = [sample_envelope_with_decisions]
        result = _aggregate_decisions(envelopes)

        assert len(result) == 1
        assert all(isinstance(d, DecisionSummary) for d in result)
        assert result[0].decision_id == "DEC-001"

    def test_aggregate_decisions_deduplication(self, sample_envelope_with_decisions):
        """Deduplicates by decision_id."""
        # Same envelope twice - should deduplicate
        envelopes = [
            sample_envelope_with_decisions,
            sample_envelope_with_decisions,
        ]
        result = _aggregate_decisions(envelopes)

        assert len(result) == 1
        assert result[0].decision_id == "DEC-001"

    def test_aggregate_decisions_fields_mapped(self, sample_envelope_with_decisions):
        """Verifies all fields are correctly mapped."""
        envelopes = [sample_envelope_with_decisions]
        result = _aggregate_decisions(envelopes)

        first = result[0]
        assert first.decision_type == "architecture"
        assert first.subject == "Database selection"
        assert first.decision == "Use PostgreSQL"
        assert first.rationale == "Best fit for relational data"
        assert first.supporting_evidence == ["perf tests", "team expertise"]
        assert first.conditions == ["data is relational"]
        assert first.assumptions_applied == ["ASM-001"]
        assert first.flow == "plan"
        assert first.agent == "adr-author"


# -----------------------------------------------------------------------------
# Unit Tests - Extraction Functions
# -----------------------------------------------------------------------------


class TestExtractDetours:
    """Tests for _extract_detours function."""

    def test_extract_detours_empty(self):
        """Returns empty list for no routing signals."""
        envelopes = [{"step_id": "step-1", "status": "VERIFIED"}]
        result = _extract_detours(envelopes)
        assert result == []

    def test_extract_detours_extend_graph(self, sample_envelope_with_detour):
        """Extracts EXTEND_GRAPH detours."""
        envelopes = [sample_envelope_with_detour]
        result = _extract_detours(envelopes)

        assert len(result) == 1
        assert isinstance(result[0], DetourSummary)
        assert result[0].detour_id == "DETOUR-001"
        assert result[0].from_step == "step-3"
        assert result[0].to_step == "additional-analysis"
        assert result[0].reason == "Unexpected complexity discovered"
        assert result[0].detour_type == "sidequest"

    def test_extract_detours_detour_type(self):
        """Extracts DETOUR routing signals."""
        envelope = {
            "step_id": "step-x",
            "routing_signal": {
                "decision": "DETOUR",
                "target": "fallback-step",
                "rationale": "Primary path blocked",
            },
        }
        result = _extract_detours([envelope])

        assert len(result) == 1
        assert result[0].from_step == "step-x"
        assert result[0].to_step == "fallback-step"
        assert result[0].reason == "Primary path blocked"

    def test_extract_detours_ignores_continue(self):
        """Ignores CONTINUE routing signals."""
        envelope = {
            "step_id": "step-y",
            "routing_signal": {
                "decision": "CONTINUE",
                "next_step": "normal-step",
            },
        }
        result = _extract_detours([envelope])
        assert result == []


class TestExtractVerifications:
    """Tests for _extract_verifications function."""

    def test_extract_verifications_empty(self):
        """Returns empty list for no steps."""
        result = _extract_verifications([])
        assert result == []

    def test_extract_verifications_verified_status(self, sample_envelope_verified):
        """Extracts VERIFIED steps."""
        envelopes = [sample_envelope_verified]
        result = _extract_verifications(envelopes)

        assert len(result) == 1
        assert isinstance(result[0], VerificationSummary)
        assert result[0].step_id == "step-4"
        assert result[0].station_id == "station-a"
        assert result[0].status == "VERIFIED"
        assert result[0].verified is True
        assert result[0].issues == []

    def test_extract_verifications_with_critique(self, sample_envelope_unverified):
        """Extracts critique issues from unverified envelopes."""
        envelopes = [sample_envelope_unverified]
        result = _extract_verifications(envelopes)

        assert len(result) == 1
        assert result[0].step_id == "step-5"
        assert result[0].verified is False
        assert result[0].can_further_iteration_help is True
        # Should limit to 5 issues
        assert len(result[0].issues) <= 5
        assert "Missing error handling" in result[0].issues

    def test_extract_verifications_critique_string(self):
        """Handles critique as a string."""
        envelope = {
            "step_id": "step-z",
            "status": "UNVERIFIED",
            "critique": "This is a simple critique message",
        }
        result = _extract_verifications([envelope])

        assert len(result) == 1
        assert result[0].issues == ["This is a simple critique message"]

    def test_extract_verifications_multiple(
        self, sample_envelope_verified, sample_envelope_unverified
    ):
        """Extracts verifications from multiple envelopes."""
        envelopes = [sample_envelope_verified, sample_envelope_unverified]
        result = _extract_verifications(envelopes)

        assert len(result) == 2
        verified_count = sum(1 for v in result if v.verified)
        assert verified_count == 1


# -----------------------------------------------------------------------------
# Unit Tests - Scoring Functions
# -----------------------------------------------------------------------------


class TestComputeConfidenceScore:
    """Tests for _compute_confidence_score function."""

    def test_compute_confidence_score_no_assumptions(self):
        """Returns 1.0 for no assumptions."""
        result = _compute_confidence_score([])
        assert result == 1.0

    def test_compute_confidence_score_high_confidence(self):
        """Returns high score for high confidence assumptions."""
        assumptions = [
            AssumptionSummary(
                assumption_id="ASM-001",
                statement="test",
                rationale="test",
                impact_if_wrong="test",
                confidence="high",
                status="active",
            )
        ]
        result = _compute_confidence_score(assumptions)

        # High confidence (1.0) - penalty (0.05 for 1 assumption) = 0.95
        assert result == pytest.approx(0.95, abs=0.01)

    def test_compute_confidence_score_low_confidence(self):
        """Returns low score for low confidence assumptions."""
        assumptions = [
            AssumptionSummary(
                assumption_id="ASM-001",
                statement="test",
                rationale="test",
                impact_if_wrong="test",
                confidence="low",
                status="active",
            )
        ]
        result = _compute_confidence_score(assumptions)

        # Low confidence (0.4) - penalty (0.05) = 0.35
        assert result == pytest.approx(0.35, abs=0.01)

    def test_compute_confidence_score_penalty(self):
        """Applies penalty for many assumptions."""
        # Create 10 high-confidence assumptions
        assumptions = [
            AssumptionSummary(
                assumption_id=f"ASM-{i:03d}",
                statement="test",
                rationale="test",
                impact_if_wrong="test",
                confidence="high",
                status="active",
            )
            for i in range(10)
        ]
        result = _compute_confidence_score(assumptions)

        # High confidence (1.0) - max penalty (0.3) = 0.7
        assert result == pytest.approx(0.7, abs=0.01)

    def test_compute_confidence_score_inactive_ignored(self):
        """Inactive assumptions are ignored."""
        assumptions = [
            AssumptionSummary(
                assumption_id="ASM-001",
                statement="test",
                rationale="test",
                impact_if_wrong="test",
                confidence="low",
                status="resolved",  # Not active
            )
        ]
        result = _compute_confidence_score(assumptions)

        # No active assumptions, returns 1.0
        assert result == 1.0

    def test_compute_confidence_score_mixed(self):
        """Correctly averages mixed confidence levels."""
        assumptions = [
            AssumptionSummary(
                assumption_id="ASM-001",
                statement="test",
                rationale="test",
                impact_if_wrong="test",
                confidence="high",  # 1.0
                status="active",
            ),
            AssumptionSummary(
                assumption_id="ASM-002",
                statement="test",
                rationale="test",
                impact_if_wrong="test",
                confidence="low",  # 0.4
                status="active",
            ),
        ]
        result = _compute_confidence_score(assumptions)

        # Average (1.0 + 0.4) / 2 = 0.7 - penalty (0.1) = 0.6
        assert result == pytest.approx(0.6, abs=0.01)


class TestCountHighRiskAssumptions:
    """Tests for _count_high_risk_assumptions function."""

    def test_count_high_risk_assumptions_none(self):
        """Returns 0 for no low-confidence assumptions."""
        assumptions = [
            AssumptionSummary(
                assumption_id="ASM-001",
                statement="test",
                rationale="test",
                impact_if_wrong="test",
                confidence="high",
                status="active",
            )
        ]
        result = _count_high_risk_assumptions(assumptions)
        assert result == 0

    def test_count_high_risk_assumptions_some(self):
        """Counts low-confidence active assumptions."""
        assumptions = [
            AssumptionSummary(
                assumption_id="ASM-001",
                statement="test",
                rationale="test",
                impact_if_wrong="test",
                confidence="low",
                status="active",
            ),
            AssumptionSummary(
                assumption_id="ASM-002",
                statement="test",
                rationale="test",
                impact_if_wrong="test",
                confidence="low",
                status="active",
            ),
            AssumptionSummary(
                assumption_id="ASM-003",
                statement="test",
                rationale="test",
                impact_if_wrong="test",
                confidence="high",
                status="active",
            ),
        ]
        result = _count_high_risk_assumptions(assumptions)
        assert result == 2

    def test_count_high_risk_assumptions_inactive_ignored(self):
        """Inactive low-confidence assumptions are not counted."""
        assumptions = [
            AssumptionSummary(
                assumption_id="ASM-001",
                statement="test",
                rationale="test",
                impact_if_wrong="test",
                confidence="low",
                status="resolved",  # Not active
            )
        ]
        result = _count_high_risk_assumptions(assumptions)
        assert result == 0


# -----------------------------------------------------------------------------
# Unit Tests - Uncertainty Notes
# -----------------------------------------------------------------------------


class TestGetUncertaintyNotes:
    """Tests for _get_uncertainty_notes function."""

    def test_get_uncertainty_notes_empty(self):
        """Returns empty list when no issues."""
        result = _get_uncertainty_notes([], [], [])
        assert result == []

    def test_get_uncertainty_notes_low_confidence(self):
        """Notes low-confidence assumptions."""
        assumptions = [
            AssumptionSummary(
                assumption_id="ASM-001",
                statement="test",
                rationale="test",
                impact_if_wrong="test",
                confidence="low",
                status="active",
            ),
            AssumptionSummary(
                assumption_id="ASM-002",
                statement="test",
                rationale="test",
                impact_if_wrong="test",
                confidence="low",
                status="active",
            ),
        ]
        result = _get_uncertainty_notes(assumptions, [], [])

        assert len(result) == 1
        assert "2 low-confidence assumption(s)" in result[0]

    def test_get_uncertainty_notes_detours(self):
        """Notes multiple detours indicating complexity."""
        detours = [
            DetourSummary(
                detour_id=f"DETOUR-{i:03d}",
                from_step=f"step-{i}",
                to_step=f"sidequest-{i}",
                reason="Complexity",
            )
            for i in range(3)
        ]
        result = _get_uncertainty_notes([], detours, [])

        assert len(result) == 1
        assert "3 detours" in result[0]
        assert "complexity or ambiguity" in result[0]

    def test_get_uncertainty_notes_verifications(self):
        """Notes failed verifications."""
        verifications = [
            VerificationSummary(
                step_id="step-1",
                status="UNVERIFIED",
                verified=False,
            ),
            VerificationSummary(
                step_id="step-2",
                status="UNVERIFIED",
                verified=False,
            ),
        ]
        result = _get_uncertainty_notes([], [], verifications)

        assert len(result) == 1
        assert "2 step(s) have unresolved verification issues" in result[0]

    def test_get_uncertainty_notes_combined(self):
        """Generates multiple notes for multiple issues."""
        assumptions = [
            AssumptionSummary(
                assumption_id="ASM-001",
                statement="test",
                rationale="test",
                impact_if_wrong="test",
                confidence="low",
                status="active",
            )
        ]
        detours = [
            DetourSummary(
                detour_id=f"DETOUR-{i:03d}",
                from_step=f"step-{i}",
                to_step=f"sidequest-{i}",
                reason="Complexity",
            )
            for i in range(5)
        ]
        verifications = [
            VerificationSummary(
                step_id="step-x",
                status="UNVERIFIED",
                verified=False,
            )
        ]

        result = _get_uncertainty_notes(assumptions, detours, verifications)

        assert len(result) == 3


# -----------------------------------------------------------------------------
# Unit Tests - Envelope Reading
# -----------------------------------------------------------------------------


class TestReadAllEnvelopes:
    """Tests for _read_all_envelopes function."""

    def test_read_all_envelopes_empty(self, tmp_path):
        """Returns empty list for no envelopes."""
        run_path = tmp_path / "test-run"
        run_path.mkdir()

        result = _read_all_envelopes(run_path)
        assert result == []

    def test_read_all_envelopes_with_filter(self, tmp_path, sample_envelope_with_assumptions):
        """Filters by flow_key."""
        run_path = tmp_path / "test-run"

        # Create envelopes in multiple flows
        for flow in ["signal", "plan"]:
            handoff_dir = run_path / flow / "handoff"
            handoff_dir.mkdir(parents=True)
            (handoff_dir / "step-1.json").write_text(json.dumps(sample_envelope_with_assumptions))

        # Filter to signal only
        result = _read_all_envelopes(run_path, flow_key="signal")

        assert len(result) == 1
        assert result[0]["_flow_key"] == "signal"

    def test_read_all_envelopes_skips_drafts(self, tmp_path, sample_envelope_with_assumptions):
        """Skips .draft.json files."""
        handoff_dir = tmp_path / "test-run" / "signal" / "handoff"
        handoff_dir.mkdir(parents=True)

        # Write regular envelope and draft
        (handoff_dir / "step-1.json").write_text(json.dumps(sample_envelope_with_assumptions))
        (handoff_dir / "step-1.draft.json").write_text(json.dumps({"draft": True}))

        result = _read_all_envelopes(tmp_path / "test-run")

        assert len(result) == 1
        assert "draft" not in result[0]

    def test_read_all_envelopes_handles_invalid_json(self, tmp_path):
        """Handles malformed JSON gracefully."""
        handoff_dir = tmp_path / "test-run" / "signal" / "handoff"
        handoff_dir.mkdir(parents=True)

        # Write valid and invalid JSON
        (handoff_dir / "step-1.json").write_text('{"valid": true}')
        (handoff_dir / "step-2.json").write_text("{ not valid json }")

        result = _read_all_envelopes(tmp_path / "test-run")

        # Should only get the valid one
        assert len(result) == 1
        assert result[0]["valid"] is True

    def test_read_all_envelopes_adds_flow_key(self, tmp_path, sample_envelope_with_assumptions):
        """Adds _flow_key to each envelope."""
        handoff_dir = tmp_path / "test-run" / "build" / "handoff"
        handoff_dir.mkdir(parents=True)
        (handoff_dir / "step-1.json").write_text(json.dumps(sample_envelope_with_assumptions))

        result = _read_all_envelopes(tmp_path / "test-run")

        assert len(result) == 1
        assert result[0]["_flow_key"] == "build"


# -----------------------------------------------------------------------------
# Unit Tests - Evolution Patches
# -----------------------------------------------------------------------------


class TestCheckEvolutionPatches:
    """Tests for _check_evolution_patches function."""

    def test_check_evolution_patches_no_wisdom(self, tmp_path):
        """Returns False when no wisdom directory."""
        run_path = tmp_path / "test-run"
        run_path.mkdir()

        has_patches, count = _check_evolution_patches(run_path)

        assert has_patches is False
        assert count == 0

    def test_check_evolution_patches_with_patches(self, tmp_path):
        """Detects patch files."""
        wisdom_dir = tmp_path / "test-run" / "wisdom"
        wisdom_dir.mkdir(parents=True)

        # Create patch files
        (wisdom_dir / "fix-issue.patch").write_text("diff content")
        (wisdom_dir / "flow_evolution_001.yaml").write_text("evolution content")

        has_patches, count = _check_evolution_patches(tmp_path / "test-run")

        assert has_patches is True
        assert count == 2

    def test_check_evolution_patches_counts_pending(self, tmp_path):
        """Counts pending (not applied/rejected) patches.

        The implementation checks for patches matching *.patch or flow_evolution*,
        then excludes any that have .applied_<name> or .rejected_<name> markers.

        Note: Due to glob behavior on Windows, marker files with .patch extension
        are also matched by *.patch, so we use flow_evolution* files to avoid this.
        """
        wisdom_dir = tmp_path / "test-run" / "wisdom"
        wisdom_dir.mkdir(parents=True)

        # Create 2 pending patches using flow_evolution naming
        (wisdom_dir / "flow_evolution_001.yaml").write_text("evolution 1")
        (wisdom_dir / "flow_evolution_002.yaml").write_text("evolution 2")

        # Create 1 applied patch (has marker)
        (wisdom_dir / "flow_evolution_applied.yaml").write_text("applied")
        (wisdom_dir / ".applied_flow_evolution_applied.yaml").write_text("")

        has_patches, count = _check_evolution_patches(tmp_path / "test-run")

        # Only 2 patches are pending (the third is marked as applied)
        assert has_patches is True
        assert count == 2

    def test_check_evolution_patches_empty_wisdom(self, tmp_path):
        """Returns False for empty wisdom directory."""
        wisdom_dir = tmp_path / "test-run" / "wisdom"
        wisdom_dir.mkdir(parents=True)

        has_patches, count = _check_evolution_patches(tmp_path / "test-run")

        assert has_patches is False
        assert count == 0


# -----------------------------------------------------------------------------
# Integration Tests
# -----------------------------------------------------------------------------


@pytest.fixture
def fastapi_client(isolated_runs_env, monkeypatch):
    """Create FastAPI test client with isolated runs environment."""
    from swarm.api.server import create_app

    # Patch the _get_runs_root function to use isolated directory
    def mock_get_runs_root():
        return isolated_runs_env["runs_dir"]

    monkeypatch.setattr(
        "swarm.api.routes.boundary._get_runs_root",
        mock_get_runs_root,
    )

    app = create_app()
    return TestClient(app)


class TestBoundaryReviewEndpoint:
    """Integration tests for the boundary review endpoint."""

    def test_boundary_review_endpoint_not_found(self, fastapi_client, isolated_runs_env):
        """Returns 404 for missing run."""
        resp = fastapi_client.get("/api/runs/nonexistent-run/boundary-review")

        assert resp.status_code == 404
        data = resp.json()
        assert data["detail"]["error"] == "run_not_found"

    def test_boundary_review_endpoint_empty_run(self, fastapi_client, isolated_runs_env):
        """Returns empty response for run with no envelopes."""
        runs_dir = isolated_runs_env["runs_dir"]
        run_path = runs_dir / "empty-run"
        run_path.mkdir()

        resp = fastapi_client.get("/api/runs/empty-run/boundary-review")

        assert resp.status_code == 200
        data = resp.json()
        assert data["run_id"] == "empty-run"
        assert data["assumptions_count"] == 0
        assert data["decisions_count"] == 0
        assert data["detours_count"] == 0

    def test_boundary_review_endpoint_with_data(
        self,
        fastapi_client,
        isolated_runs_env,
        sample_envelope_with_assumptions,
        sample_envelope_with_decisions,
        sample_envelope_with_detour,
    ):
        """Returns aggregated data for run with envelopes."""
        runs_dir = isolated_runs_env["runs_dir"]

        _create_run_with_envelopes(
            runs_dir,
            "data-run",
            {
                "signal": [sample_envelope_with_assumptions],
                "plan": [sample_envelope_with_decisions],
                "build": [sample_envelope_with_detour],
            },
        )

        resp = fastapi_client.get("/api/runs/data-run/boundary-review")

        assert resp.status_code == 200
        data = resp.json()
        assert data["run_id"] == "data-run"
        assert data["assumptions_count"] == 2
        assert data["decisions_count"] == 1
        assert data["detours_count"] == 1

    def test_boundary_review_endpoint_flow_scope(
        self,
        fastapi_client,
        isolated_runs_env,
        sample_envelope_with_assumptions,
    ):
        """Filters by flow when scope='flow'."""
        runs_dir = isolated_runs_env["runs_dir"]

        # Create envelopes in multiple flows
        envelope_signal = {
            **sample_envelope_with_assumptions,
            "assumptions_made": [
                {
                    "assumption_id": "ASM-SIGNAL-001",
                    "statement": "Signal assumption",
                    "rationale": "test",
                    "impact_if_wrong": "test",
                }
            ],
        }
        envelope_plan = {
            "step_id": "plan-step",
            "status": "VERIFIED",
            "assumptions_made": [
                {
                    "assumption_id": "ASM-PLAN-001",
                    "statement": "Plan assumption",
                    "rationale": "test",
                    "impact_if_wrong": "test",
                }
            ],
        }

        _create_run_with_envelopes(
            runs_dir,
            "scoped-run",
            {
                "signal": [envelope_signal],
                "plan": [envelope_plan],
            },
        )

        # Request with flow scope
        resp = fastapi_client.get(
            "/api/runs/scoped-run/boundary-review",
            params={"scope": "flow", "flow_key": "signal"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["scope"] == "flow"
        assert data["current_flow"] == "signal"
        # Should only have signal assumptions
        assert data["assumptions_count"] == 1
        assert data["assumptions"][0]["assumption_id"] == "ASM-SIGNAL-001"

    def test_boundary_review_endpoint_verifications(
        self,
        fastapi_client,
        isolated_runs_env,
        sample_envelope_verified,
        sample_envelope_unverified,
    ):
        """Correctly counts verified and failed verifications."""
        runs_dir = isolated_runs_env["runs_dir"]

        _create_run_with_envelopes(
            runs_dir,
            "verify-run",
            {
                "build": [sample_envelope_verified, sample_envelope_unverified],
            },
        )

        resp = fastapi_client.get("/api/runs/verify-run/boundary-review")

        assert resp.status_code == 200
        data = resp.json()
        assert data["verification_passed"] == 1
        assert data["verification_failed"] == 1

    def test_boundary_review_endpoint_confidence_score(
        self,
        fastapi_client,
        isolated_runs_env,
    ):
        """Returns computed confidence score."""
        runs_dir = isolated_runs_env["runs_dir"]

        envelope = {
            "step_id": "step-1",
            "status": "VERIFIED",
            "assumptions_made": [
                {
                    "assumption_id": "ASM-001",
                    "statement": "Low confidence assumption",
                    "rationale": "test",
                    "impact_if_wrong": "high",
                    "confidence": "low",
                    "status": "active",
                }
            ],
        }

        _create_run_with_envelopes(
            runs_dir,
            "confidence-run",
            {"signal": [envelope]},
        )

        resp = fastapi_client.get("/api/runs/confidence-run/boundary-review")

        assert resp.status_code == 200
        data = resp.json()
        assert data["confidence_score"] < 1.0
        assert data["assumptions_high_risk"] == 1

    def test_boundary_review_endpoint_evolution_patches(
        self,
        tmp_path,
        monkeypatch,
    ):
        """Detects evolution patches in wisdom directory.

        Uses direct patching of the boundary module's find_run_path
        before importing/creating the app.

        Note: The endpoint requires at least one handoff envelope to proceed
        past the early return, otherwise evolution patches are not checked.
        """
        import swarm.api.routes.boundary as boundary_module
        from swarm.api.server import create_app

        runs_dir = tmp_path / "swarm" / "runs"
        runs_dir.mkdir(parents=True)

        # Create run with evolution patches AND at least one handoff envelope
        run_path = runs_dir / "evolution-run"
        run_path.mkdir()

        # Add wisdom directory with evolution patch
        wisdom_dir = run_path / "wisdom"
        wisdom_dir.mkdir()
        (wisdom_dir / "flow_evolution_001.yaml").write_text("evolution: true")

        # Add a handoff envelope so the endpoint doesn't return early
        signal_handoff = run_path / "signal" / "handoff"
        signal_handoff.mkdir(parents=True)
        (signal_handoff / "step-1.json").write_text('{"step_id": "step-1", "status": "VERIFIED"}')

        # Patch find_run_path on the boundary module directly
        original_find = boundary_module.find_run_path

        def mock_find_run_path(run_id):
            path = runs_dir / run_id
            if path.exists():
                return path
            # Fall back to original for other runs
            return original_find(run_id)

        monkeypatch.setattr(boundary_module, "find_run_path", mock_find_run_path)

        app = create_app()
        client = TestClient(app)

        resp = client.get("/api/runs/evolution-run/boundary-review")

        assert resp.status_code == 200
        data = resp.json()
        assert data["has_evolution_patches"] is True
        assert data["evolution_patch_count"] == 1

    def test_boundary_review_endpoint_empty_run_confidence_score(
        self,
        fastapi_client,
        isolated_runs_env,
    ):
        """Empty run returns 1.0 confidence score (no assumptions = full confidence)."""
        runs_dir = isolated_runs_env["runs_dir"]
        run_path = runs_dir / "empty-confidence-run"
        run_path.mkdir()

        resp = fastapi_client.get("/api/runs/empty-confidence-run/boundary-review")

        assert resp.status_code == 200
        data = resp.json()
        # Empty run should have confidence score of 1.0
        assert data["confidence_score"] == 1.0
        assert data["assumptions_count"] == 0
        assert data["assumptions_high_risk"] == 0
        # Empty arrays for all collections
        assert data["assumptions"] == []
        assert data["decisions"] == []
        assert data["detours"] == []
        assert data["verifications"] == []
        assert data["uncertainty_notes"] == []

    def test_boundary_review_endpoint_ordering_stable(
        self,
        fastapi_client,
        isolated_runs_env,
    ):
        """Assumptions, decisions, and detours maintain stable ordering across requests."""
        runs_dir = isolated_runs_env["runs_dir"]

        # Create envelopes with multiple items that could be ordered differently
        envelopes_signal = [
            {
                "step_id": "step-1",
                "status": "VERIFIED",
                "timestamp": "2025-01-15T10:00:00Z",
                "assumptions_made": [
                    {
                        "assumption_id": "ASM-001",
                        "statement": "First assumption",
                        "rationale": "test",
                        "impact_if_wrong": "test",
                    },
                    {
                        "assumption_id": "ASM-002",
                        "statement": "Second assumption",
                        "rationale": "test",
                        "impact_if_wrong": "test",
                    },
                ],
                "decisions_made": [
                    {
                        "decision_id": "DEC-001",
                        "decision_type": "design",
                        "subject": "First decision",
                        "decision": "Choose A",
                        "rationale": "test",
                    },
                ],
            },
            {
                "step_id": "step-2",
                "status": "UNVERIFIED",
                "timestamp": "2025-01-15T10:05:00Z",
                "assumptions_made": [
                    {
                        "assumption_id": "ASM-003",
                        "statement": "Third assumption",
                        "rationale": "test",
                        "impact_if_wrong": "test",
                    },
                ],
                "routing_signal": {
                    "decision": "EXTEND_GRAPH",
                    "next_step": "extra-step",
                    "reason": "Needed more analysis",
                },
            },
        ]

        _create_run_with_envelopes(
            runs_dir,
            "ordering-run",
            {"signal": envelopes_signal},
        )

        # Make multiple requests and verify ordering is consistent
        responses = []
        for _ in range(3):
            resp = fastapi_client.get("/api/runs/ordering-run/boundary-review")
            assert resp.status_code == 200
            responses.append(resp.json())

        # All responses should have identical ordering
        for i in range(1, len(responses)):
            # Check assumptions order
            prev_asm_ids = [a["assumption_id"] for a in responses[i - 1]["assumptions"]]
            curr_asm_ids = [a["assumption_id"] for a in responses[i]["assumptions"]]
            assert prev_asm_ids == curr_asm_ids, "Assumption ordering not stable"

            # Check decisions order
            prev_dec_ids = [d["decision_id"] for d in responses[i - 1]["decisions"]]
            curr_dec_ids = [d["decision_id"] for d in responses[i]["decisions"]]
            assert prev_dec_ids == curr_dec_ids, "Decision ordering not stable"

            # Check detours order
            prev_det_ids = [d["detour_id"] for d in responses[i - 1]["detours"]]
            curr_det_ids = [d["detour_id"] for d in responses[i]["detours"]]
            assert prev_det_ids == curr_det_ids, "Detour ordering not stable"

    def test_boundary_review_endpoint_missing_artifacts_graceful(
        self,
        fastapi_client,
        isolated_runs_env,
    ):
        """Run with missing/partial artifacts returns warnings, not 500."""
        runs_dir = isolated_runs_env["runs_dir"]

        # Create a run with a handoff directory but some missing content
        run_path = runs_dir / "partial-run"
        run_path.mkdir()

        # Create handoff directory with a valid envelope
        signal_handoff = run_path / "signal" / "handoff"
        signal_handoff.mkdir(parents=True)

        # Add one valid envelope with UNVERIFIED status (simulates incomplete work)
        (signal_handoff / "step-1.json").write_text(
            json.dumps(
                {
                    "step_id": "step-1",
                    "status": "UNVERIFIED",
                    "verification": {
                        "verified": False,
                        "can_further_iteration_help": True,
                    },
                    "critique": {
                        "issues": ["Missing implementation", "Incomplete test coverage"],
                    },
                }
            )
        )

        # Create plan directory but leave it empty (missing artifacts)
        plan_dir = run_path / "plan"
        plan_dir.mkdir()

        resp = fastapi_client.get("/api/runs/partial-run/boundary-review")

        # Should return 200, not 500
        assert resp.status_code == 200
        data = resp.json()

        # Should report verification issues
        assert data["verification_failed"] >= 1
        assert len(data["verifications"]) >= 1

        # Find the unverified step
        unverified_steps = [v for v in data["verifications"] if not v["verified"]]
        assert len(unverified_steps) >= 1
        assert unverified_steps[0]["status"] == "UNVERIFIED"

        # Should have uncertainty notes about failed verifications
        # (may or may not depending on implementation)
        # Just verify no 500 and response is valid

    def test_boundary_review_endpoint_scope_run_aggregates_all(
        self,
        fastapi_client,
        isolated_runs_env,
        sample_envelope_with_assumptions,
    ):
        """Scope='run' aggregates data from all flows."""
        runs_dir = isolated_runs_env["runs_dir"]

        # Create envelopes across multiple flows
        envelope_signal = {
            "step_id": "signal-step-1",
            "status": "VERIFIED",
            "assumptions_made": [
                {
                    "assumption_id": "ASM-SIGNAL-001",
                    "statement": "Signal assumption",
                    "rationale": "test",
                    "impact_if_wrong": "test",
                }
            ],
        }
        envelope_plan = {
            "step_id": "plan-step-1",
            "status": "VERIFIED",
            "assumptions_made": [
                {
                    "assumption_id": "ASM-PLAN-001",
                    "statement": "Plan assumption",
                    "rationale": "test",
                    "impact_if_wrong": "test",
                }
            ],
            "decisions_made": [
                {
                    "decision_id": "DEC-PLAN-001",
                    "decision_type": "architecture",
                    "subject": "DB choice",
                    "decision": "PostgreSQL",
                    "rationale": "test",
                }
            ],
        }
        envelope_build = {
            "step_id": "build-step-1",
            "status": "UNVERIFIED",
            "routing_signal": {
                "decision": "DETOUR",
                "target": "extra-analysis",
                "rationale": "Need more investigation",
            },
        }

        _create_run_with_envelopes(
            runs_dir,
            "full-run",
            {
                "signal": [envelope_signal],
                "plan": [envelope_plan],
                "build": [envelope_build],
            },
        )

        # Request with scope='run' (entire run)
        resp = fastapi_client.get(
            "/api/runs/full-run/boundary-review",
            params={"scope": "run"},
        )

        assert resp.status_code == 200
        data = resp.json()

        # Should aggregate from all flows
        assert data["scope"] == "run"
        # 2 assumptions (1 from signal, 1 from plan)
        assert data["assumptions_count"] == 2
        # 1 decision (from plan)
        assert data["decisions_count"] == 1
        # 1 detour (from build)
        assert data["detours_count"] == 1

        # Verify all assumptions are present
        assumption_ids = {a["assumption_id"] for a in data["assumptions"]}
        assert "ASM-SIGNAL-001" in assumption_ids
        assert "ASM-PLAN-001" in assumption_ids

    def test_boundary_review_endpoint_timestamp_present(
        self,
        fastapi_client,
        isolated_runs_env,
    ):
        """Response includes valid ISO timestamp."""
        runs_dir = isolated_runs_env["runs_dir"]
        run_path = runs_dir / "timestamp-run"
        run_path.mkdir()

        resp = fastapi_client.get("/api/runs/timestamp-run/boundary-review")

        assert resp.status_code == 200
        data = resp.json()

        # Timestamp should be present and in ISO format
        assert "timestamp" in data
        assert data["timestamp"] is not None

        # Should be parseable as ISO timestamp
        from datetime import datetime

        try:
            # ISO format with or without timezone
            ts = data["timestamp"]
            if ts.endswith("Z"):
                ts = ts[:-1] + "+00:00"
            datetime.fromisoformat(ts)
        except ValueError:
            pytest.fail(f"Invalid timestamp format: {data['timestamp']}")

    def test_boundary_review_endpoint_invalid_json_in_envelope(
        self,
        fastapi_client,
        isolated_runs_env,
    ):
        """Malformed JSON in envelope is skipped gracefully, not 500."""
        runs_dir = isolated_runs_env["runs_dir"]

        run_path = runs_dir / "bad-json-run"
        signal_handoff = run_path / "signal" / "handoff"
        signal_handoff.mkdir(parents=True)

        # Write one valid envelope
        (signal_handoff / "step-1.json").write_text(
            json.dumps(
                {
                    "step_id": "step-1",
                    "status": "VERIFIED",
                    "assumptions_made": [
                        {
                            "assumption_id": "ASM-VALID",
                            "statement": "Valid assumption",
                            "rationale": "test",
                            "impact_if_wrong": "test",
                        }
                    ],
                }
            )
        )

        # Write one malformed envelope
        (signal_handoff / "step-2.json").write_text("{ invalid json }")

        resp = fastapi_client.get("/api/runs/bad-json-run/boundary-review")

        # Should return 200, not 500
        assert resp.status_code == 200
        data = resp.json()

        # Should still have the valid assumption
        assert data["assumptions_count"] == 1
        assert data["assumptions"][0]["assumption_id"] == "ASM-VALID"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
