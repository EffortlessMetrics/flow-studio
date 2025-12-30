"""Tests for the agent_logging utility module.

This module tests the high-level functions for logging assumptions and decisions
during agent execution. These utilities wrap the lower-level handoff_io functions
with convenience features like auto-generated IDs and context extraction.
"""

import pytest
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

# Ensure swarm modules are importable
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from swarm.runtime.agent_logging import (
    log_assumption,
    log_decision,
    get_assumption_by_id,
    get_decision_by_id,
    list_assumptions,
    list_decisions,
    get_assumptions_for_decision,
    format_assumption_for_prompt,
    format_decision_for_prompt,
    _generate_assumption_id,
    _generate_decision_id,
    _extract_context,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def empty_envelope() -> Dict[str, Any]:
    """An empty envelope with basic context fields."""
    return {
        "step_id": "1",
        "flow_key": "signal",
        "run_id": "run-20251229-120000-abc123",
        "station_id": "requirements-author",
    }


@pytest.fixture
def envelope_with_assumptions() -> Dict[str, Any]:
    """An envelope with pre-existing assumptions."""
    return {
        "step_id": "2",
        "flow_key": "plan",
        "run_id": "run-20251229-120000-abc123",
        "station_id": "design-optioneer",
        "assumptions_made": [
            {
                "assumption_id": "ASM-001",
                "flow_introduced": "plan",
                "step_introduced": "2",
                "agent": "design-optioneer",
                "statement": "API will use REST, not GraphQL",
                "rationale": "No GraphQL mentioned in requirements",
                "impact_if_wrong": "Need to redesign API layer",
                "confidence": "medium",
                "status": "active",
                "tags": ["architecture", "api"],
                "timestamp": "2025-12-29T12:00:00Z",
            }
        ],
        "decisions_made": [],
    }


@pytest.fixture
def envelope_with_decisions() -> Dict[str, Any]:
    """An envelope with pre-existing decisions."""
    return {
        "step_id": "3",
        "flow_key": "plan",
        "run_id": "run-20251229-120000-abc123",
        "station_id": "adr-author",
        "assumptions_made": [],
        "decisions_made": [
            {
                "decision_id": "DEC-001",
                "flow": "plan",
                "step": "3",
                "agent": "adr-author",
                "decision_type": "architecture",
                "subject": "Database selection",
                "decision": "Use PostgreSQL",
                "rationale": "ACID compliance needed",
                "supporting_evidence": ["requirements.md:L45"],
                "conditions": [],
                "assumptions_applied": [],
                "timestamp": "2025-12-29T12:00:00Z",
            }
        ],
    }


# =============================================================================
# ID Generation Tests
# =============================================================================


class TestIdGeneration:
    """Tests for automatic ID generation."""

    def test_generate_assumption_id_first(self, empty_envelope):
        """First assumption gets ASM-001."""
        assert _generate_assumption_id(empty_envelope) == "ASM-001"

    def test_generate_assumption_id_sequential(self, envelope_with_assumptions):
        """Subsequent assumptions get incremented IDs."""
        assert _generate_assumption_id(envelope_with_assumptions) == "ASM-002"

    def test_generate_decision_id_first(self, empty_envelope):
        """First decision gets DEC-001."""
        assert _generate_decision_id(empty_envelope) == "DEC-001"

    def test_generate_decision_id_sequential(self, envelope_with_decisions):
        """Subsequent decisions get incremented IDs."""
        assert _generate_decision_id(envelope_with_decisions) == "DEC-002"

    def test_assumption_and_decision_ids_independent(self):
        """Assumption and decision counters are independent."""
        envelope = {
            "step_id": "1",
            "flow_key": "signal",
            "assumptions_made": [
                {"assumption_id": "ASM-001"},
                {"assumption_id": "ASM-002"},
            ],
            "decisions_made": [
                {"decision_id": "DEC-001"},
            ],
        }
        assert _generate_assumption_id(envelope) == "ASM-003"
        assert _generate_decision_id(envelope) == "DEC-002"


# =============================================================================
# Context Extraction Tests
# =============================================================================


class TestContextExtraction:
    """Tests for context extraction from envelopes."""

    def test_extract_context_with_station_id(self, empty_envelope):
        """Extracts context including agent from station_id."""
        ctx = _extract_context(empty_envelope)
        assert ctx["flow_key"] == "signal"
        assert ctx["step_id"] == "1"
        assert ctx["agent"] == "requirements-author"

    def test_extract_context_with_agent_field(self):
        """Falls back to agent field if station_id not present."""
        envelope = {
            "step_id": "2",
            "flow_key": "plan",
            "agent": "design-optioneer",
        }
        ctx = _extract_context(envelope)
        assert ctx["agent"] == "design-optioneer"

    def test_extract_context_missing_fields(self):
        """Handles missing fields gracefully."""
        envelope = {}
        ctx = _extract_context(envelope)
        assert ctx["flow_key"] == ""
        assert ctx["step_id"] == ""
        assert ctx["agent"] == ""


# =============================================================================
# log_assumption Tests
# =============================================================================


class TestLogAssumption:
    """Tests for the log_assumption function."""

    def test_log_assumption_basic(self, empty_envelope):
        """Logs a basic assumption with auto-generated ID."""
        asm_id = log_assumption(
            empty_envelope,
            statement="User wants REST API",
            rationale="No GraphQL mentioned in requirements",
            impact_if_wrong="Would need to redesign API layer",
        )

        assert asm_id == "ASM-001"
        assert "assumptions_made" in empty_envelope
        assert len(empty_envelope["assumptions_made"]) == 1

        asm = empty_envelope["assumptions_made"][0]
        assert asm["assumption_id"] == "ASM-001"
        assert asm["statement"] == "User wants REST API"
        assert asm["rationale"] == "No GraphQL mentioned in requirements"
        assert asm["impact_if_wrong"] == "Would need to redesign API layer"
        assert asm["confidence"] == "medium"  # default
        assert asm["status"] == "active"
        assert asm["flow_introduced"] == "signal"
        assert asm["step_introduced"] == "1"
        assert asm["agent"] == "requirements-author"

    def test_log_assumption_with_confidence(self, empty_envelope):
        """Logs assumption with custom confidence level."""
        asm_id = log_assumption(
            empty_envelope,
            statement="System handles 1000 concurrent users",
            rationale="Based on similar systems",
            impact_if_wrong="Need performance testing",
            confidence="low",
        )

        asm = empty_envelope["assumptions_made"][0]
        assert asm["confidence"] == "low"

    def test_log_assumption_with_tags(self, empty_envelope):
        """Logs assumption with categorization tags."""
        asm_id = log_assumption(
            empty_envelope,
            statement="Authentication uses OAuth2",
            rationale="Industry standard for web apps",
            impact_if_wrong="Security review needed",
            tags=["security", "authentication"],
        )

        asm = empty_envelope["assumptions_made"][0]
        assert asm["tags"] == ["security", "authentication"]

    def test_log_multiple_assumptions(self, empty_envelope):
        """Multiple assumptions get sequential IDs."""
        asm1 = log_assumption(
            empty_envelope,
            statement="First assumption",
            rationale="Reason 1",
            impact_if_wrong="Impact 1",
        )
        asm2 = log_assumption(
            empty_envelope,
            statement="Second assumption",
            rationale="Reason 2",
            impact_if_wrong="Impact 2",
        )
        asm3 = log_assumption(
            empty_envelope,
            statement="Third assumption",
            rationale="Reason 3",
            impact_if_wrong="Impact 3",
        )

        assert asm1 == "ASM-001"
        assert asm2 == "ASM-002"
        assert asm3 == "ASM-003"
        assert len(empty_envelope["assumptions_made"]) == 3

    def test_log_assumption_has_timestamp(self, empty_envelope):
        """Logged assumption has a timestamp."""
        log_assumption(
            empty_envelope,
            statement="Test",
            rationale="Test",
            impact_if_wrong="Test",
        )

        asm = empty_envelope["assumptions_made"][0]
        assert "timestamp" in asm
        assert asm["timestamp"].endswith("Z")


# =============================================================================
# log_decision Tests
# =============================================================================


class TestLogDecision:
    """Tests for the log_decision function."""

    def test_log_decision_basic(self, empty_envelope):
        """Logs a basic decision with auto-generated ID."""
        dec_id = log_decision(
            empty_envelope,
            decision_type="architecture",
            subject="Database selection",
            decision="Use PostgreSQL",
            rationale="ACID compliance and team expertise",
        )

        assert dec_id == "DEC-001"
        assert "decisions_made" in empty_envelope
        assert len(empty_envelope["decisions_made"]) == 1

        dec = empty_envelope["decisions_made"][0]
        assert dec["decision_id"] == "DEC-001"
        assert dec["decision_type"] == "architecture"
        assert dec["subject"] == "Database selection"
        assert dec["decision"] == "Use PostgreSQL"
        assert dec["rationale"] == "ACID compliance and team expertise"
        assert dec["flow"] == "signal"
        assert dec["step"] == "1"
        assert dec["agent"] == "requirements-author"

    def test_log_decision_with_evidence(self, empty_envelope):
        """Logs decision with supporting evidence."""
        dec_id = log_decision(
            empty_envelope,
            decision_type="implementation",
            subject="API framework",
            decision="Use FastAPI",
            rationale="Async support and OpenAPI generation",
            supporting_evidence=["requirements.md:L23", "adr/001-api-design.md"],
        )

        dec = empty_envelope["decisions_made"][0]
        assert dec["supporting_evidence"] == ["requirements.md:L23", "adr/001-api-design.md"]

    def test_log_decision_with_conditions(self, empty_envelope):
        """Logs decision with conditions."""
        dec_id = log_decision(
            empty_envelope,
            decision_type="design",
            subject="Caching strategy",
            decision="Use Redis for session caching",
            rationale="Performance requirements",
            conditions=["Traffic exceeds 100 req/s", "Session data < 1MB"],
        )

        dec = empty_envelope["decisions_made"][0]
        assert dec["conditions"] == ["Traffic exceeds 100 req/s", "Session data < 1MB"]

    def test_log_decision_with_assumptions(self, envelope_with_assumptions):
        """Logs decision that applies assumptions."""
        dec_id = log_decision(
            envelope_with_assumptions,
            decision_type="integration",
            subject="API endpoint design",
            decision="Use REST endpoints with JSON",
            rationale="Based on REST assumption",
            assumptions_applied=["ASM-001"],
        )

        dec = envelope_with_assumptions["decisions_made"][0]
        assert dec["assumptions_applied"] == ["ASM-001"]

    def test_log_multiple_decisions(self, empty_envelope):
        """Multiple decisions get sequential IDs."""
        dec1 = log_decision(
            empty_envelope,
            decision_type="architecture",
            subject="Subject 1",
            decision="Decision 1",
            rationale="Reason 1",
        )
        dec2 = log_decision(
            empty_envelope,
            decision_type="design",
            subject="Subject 2",
            decision="Decision 2",
            rationale="Reason 2",
        )

        assert dec1 == "DEC-001"
        assert dec2 == "DEC-002"
        assert len(empty_envelope["decisions_made"]) == 2


# =============================================================================
# Retrieval Tests
# =============================================================================


class TestRetrieval:
    """Tests for retrieval functions."""

    def test_get_assumption_by_id(self, envelope_with_assumptions):
        """Retrieves assumption by ID."""
        asm = get_assumption_by_id(envelope_with_assumptions, "ASM-001")
        assert asm is not None
        assert asm["statement"] == "API will use REST, not GraphQL"

    def test_get_assumption_by_id_not_found(self, envelope_with_assumptions):
        """Returns None when assumption not found."""
        asm = get_assumption_by_id(envelope_with_assumptions, "ASM-999")
        assert asm is None

    def test_get_decision_by_id(self, envelope_with_decisions):
        """Retrieves decision by ID."""
        dec = get_decision_by_id(envelope_with_decisions, "DEC-001")
        assert dec is not None
        assert dec["subject"] == "Database selection"

    def test_get_decision_by_id_not_found(self, envelope_with_decisions):
        """Returns None when decision not found."""
        dec = get_decision_by_id(envelope_with_decisions, "DEC-999")
        assert dec is None


# =============================================================================
# Listing Tests
# =============================================================================


class TestListing:
    """Tests for listing functions."""

    def test_list_assumptions_all(self, envelope_with_assumptions):
        """Lists all assumptions without filter."""
        assumptions = list_assumptions(envelope_with_assumptions)
        assert len(assumptions) == 1

    def test_list_assumptions_by_status(self):
        """Filters assumptions by status."""
        envelope = {
            "assumptions_made": [
                {"assumption_id": "ASM-001", "status": "active"},
                {"assumption_id": "ASM-002", "status": "resolved"},
                {"assumption_id": "ASM-003", "status": "active"},
            ]
        }
        active = list_assumptions(envelope, status="active")
        assert len(active) == 2
        resolved = list_assumptions(envelope, status="resolved")
        assert len(resolved) == 1

    def test_list_assumptions_by_confidence(self):
        """Filters assumptions by confidence."""
        envelope = {
            "assumptions_made": [
                {"assumption_id": "ASM-001", "confidence": "high"},
                {"assumption_id": "ASM-002", "confidence": "medium"},
                {"assumption_id": "ASM-003", "confidence": "low"},
            ]
        }
        high = list_assumptions(envelope, confidence="high")
        assert len(high) == 1
        assert high[0]["assumption_id"] == "ASM-001"

    def test_list_decisions_all(self, envelope_with_decisions):
        """Lists all decisions without filter."""
        decisions = list_decisions(envelope_with_decisions)
        assert len(decisions) == 1

    def test_list_decisions_by_type(self):
        """Filters decisions by type."""
        envelope = {
            "decisions_made": [
                {"decision_id": "DEC-001", "decision_type": "architecture"},
                {"decision_id": "DEC-002", "decision_type": "implementation"},
                {"decision_id": "DEC-003", "decision_type": "architecture"},
            ]
        }
        arch = list_decisions(envelope, decision_type="architecture")
        assert len(arch) == 2
        impl = list_decisions(envelope, decision_type="implementation")
        assert len(impl) == 1


# =============================================================================
# Relationship Tests
# =============================================================================


class TestRelationships:
    """Tests for relationship tracking between assumptions and decisions."""

    def test_get_assumptions_for_decision(self):
        """Gets assumptions applied to a decision."""
        envelope = {
            "assumptions_made": [
                {"assumption_id": "ASM-001", "statement": "First assumption"},
                {"assumption_id": "ASM-002", "statement": "Second assumption"},
                {"assumption_id": "ASM-003", "statement": "Third assumption"},
            ],
            "decisions_made": [
                {
                    "decision_id": "DEC-001",
                    "assumptions_applied": ["ASM-001", "ASM-003"],
                },
            ],
        }
        assumptions = get_assumptions_for_decision(envelope, "DEC-001")
        assert len(assumptions) == 2
        statements = [a["statement"] for a in assumptions]
        assert "First assumption" in statements
        assert "Third assumption" in statements
        assert "Second assumption" not in statements

    def test_get_assumptions_for_decision_not_found(self, empty_envelope):
        """Returns empty list when decision not found."""
        assumptions = get_assumptions_for_decision(empty_envelope, "DEC-999")
        assert assumptions == []


# =============================================================================
# Formatting Tests
# =============================================================================


class TestFormatting:
    """Tests for prompt formatting functions."""

    def test_format_assumption_for_prompt(self):
        """Formats assumption as markdown."""
        assumption = {
            "assumption_id": "ASM-001",
            "statement": "API uses REST",
            "rationale": "Industry standard",
            "impact_if_wrong": "Need to redesign",
            "confidence": "high",
            "tags": ["api", "architecture"],
        }
        formatted = format_assumption_for_prompt(assumption)
        assert "ASM-001" in formatted
        assert "API uses REST" in formatted
        assert "Industry standard" in formatted
        assert "Need to redesign" in formatted
        assert "high" in formatted
        assert "api, architecture" in formatted

    def test_format_assumption_without_tags(self):
        """Formats assumption without tags."""
        assumption = {
            "assumption_id": "ASM-001",
            "statement": "Test",
            "rationale": "Test",
            "impact_if_wrong": "Test",
            "confidence": "medium",
            "tags": [],
        }
        formatted = format_assumption_for_prompt(assumption)
        assert "Tags:" not in formatted

    def test_format_decision_for_prompt(self):
        """Formats decision as markdown."""
        decision = {
            "decision_id": "DEC-001",
            "decision_type": "architecture",
            "subject": "Database",
            "decision": "Use PostgreSQL",
            "rationale": "ACID compliance",
            "supporting_evidence": ["req.md:L45"],
            "assumptions_applied": ["ASM-001"],
        }
        formatted = format_decision_for_prompt(decision)
        assert "DEC-001" in formatted
        assert "architecture" in formatted
        assert "Database" in formatted
        assert "Use PostgreSQL" in formatted
        assert "ACID compliance" in formatted
        assert "req.md:L45" in formatted
        assert "ASM-001" in formatted

    def test_format_decision_minimal(self):
        """Formats decision with minimal fields."""
        decision = {
            "decision_id": "DEC-001",
            "decision_type": "design",
            "subject": "Subject",
            "decision": "Decision",
            "rationale": "Rationale",
            "supporting_evidence": [],
            "assumptions_applied": [],
        }
        formatted = format_decision_for_prompt(decision)
        assert "DEC-001" in formatted
        assert "Evidence:" not in formatted
        assert "Based on assumptions:" not in formatted


# =============================================================================
# Integration Tests
# =============================================================================


class TestIntegration:
    """Integration tests for the full workflow."""

    def test_full_workflow(self, empty_envelope):
        """Tests a full workflow of logging assumptions and decisions."""
        # Log some assumptions
        asm1_id = log_assumption(
            empty_envelope,
            statement="API will use REST",
            rationale="Industry standard for web APIs",
            impact_if_wrong="Would need GraphQL setup",
            confidence="high",
            tags=["api"],
        )

        asm2_id = log_assumption(
            empty_envelope,
            statement="Max 1000 concurrent users",
            rationale="Based on similar systems",
            impact_if_wrong="Need horizontal scaling",
            confidence="medium",
            tags=["performance"],
        )

        # Log a decision that uses the assumptions
        dec_id = log_decision(
            empty_envelope,
            decision_type="architecture",
            subject="API framework selection",
            decision="Use FastAPI with async endpoints",
            rationale="REST support, async for concurrent users",
            supporting_evidence=["requirements.md:L10-20"],
            assumptions_applied=[asm1_id, asm2_id],
        )

        # Verify the structure
        assert len(empty_envelope["assumptions_made"]) == 2
        assert len(empty_envelope["decisions_made"]) == 1

        # Retrieve and verify relationships
        decision = get_decision_by_id(empty_envelope, dec_id)
        assert decision is not None
        assert len(decision["assumptions_applied"]) == 2

        related_assumptions = get_assumptions_for_decision(empty_envelope, dec_id)
        assert len(related_assumptions) == 2

        # Verify IDs are sequential
        assert asm1_id == "ASM-001"
        assert asm2_id == "ASM-002"
        assert dec_id == "DEC-001"
