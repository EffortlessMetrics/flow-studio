"""
agent_logging.py - High-level utilities for agent assumption and decision logging.

This module provides convenient functions for agents to log structured assumptions
and decisions during step execution. It wraps the lower-level add_assumption() and
add_decision() functions from handoff_io.py with:
- Auto-generated sequential IDs (ASM-001, DEC-001 format)
- Auto-filled context from envelope (flow, step, agent)
- Simplified API for common use cases

Usage in agent code (conceptually - agents use prompts, not Python):

    from swarm.runtime.agent_logging import log_assumption, log_decision

    # Log an assumption made due to ambiguity
    log_assumption(
        envelope,
        statement="User wants REST API, not GraphQL",
        rationale="No explicit API style mentioned; REST is conventional",
        impact_if_wrong="Would need to redesign API layer for GraphQL",
        confidence="medium",
    )

    # Log a design decision
    log_decision(
        envelope,
        decision_type="architecture",
        subject="Database selection",
        decision="Use PostgreSQL for primary data store",
        rationale="Team expertise + ACID requirements + JSON support",
    )

The generated IDs use the pattern:
- Assumptions: ASM-001, ASM-002, etc. (per envelope)
- Decisions: DEC-001, DEC-002, etc. (per envelope)

These utilities are designed for use by:
1. Orchestrator code calling agents
2. Stepwise backends that need to track agent reasoning
3. Testing and validation of agent behavior
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from swarm.runtime.handoff_io import add_assumption, add_decision

logger = logging.getLogger(__name__)

# Type alias for confidence levels
ConfidenceLevelStr = Literal["high", "medium", "low"]


def _count_assumptions(envelope_data: Dict[str, Any]) -> int:
    """Count existing assumptions in the envelope."""
    assumptions = envelope_data.get("assumptions_made", [])
    return len(assumptions)


def _count_decisions(envelope_data: Dict[str, Any]) -> int:
    """Count existing decisions in the envelope."""
    decisions = envelope_data.get("decisions_made", [])
    return len(decisions)


def _generate_assumption_id(envelope_data: Dict[str, Any]) -> str:
    """Generate the next sequential assumption ID.

    Returns IDs in the format ASM-001, ASM-002, etc.
    The sequence is based on the count of existing assumptions in the envelope.
    """
    count = _count_assumptions(envelope_data)
    next_num = count + 1
    return f"ASM-{next_num:03d}"


def _generate_decision_id(envelope_data: Dict[str, Any]) -> str:
    """Generate the next sequential decision ID.

    Returns IDs in the format DEC-001, DEC-002, etc.
    The sequence is based on the count of existing decisions in the envelope.
    """
    count = _count_decisions(envelope_data)
    next_num = count + 1
    return f"DEC-{next_num:03d}"


def _extract_context(envelope_data: Dict[str, Any]) -> Dict[str, str]:
    """Extract flow, step, and agent context from envelope.

    Returns a dict with:
    - flow_key: The flow key from the envelope
    - step_id: The step ID from the envelope
    - agent: The agent key (extracted from station_id or empty)
    """
    return {
        "flow_key": envelope_data.get("flow_key", ""),
        "step_id": envelope_data.get("step_id", ""),
        "agent": envelope_data.get("station_id", "") or envelope_data.get("agent", ""),
    }


def log_assumption(
    envelope_data: Dict[str, Any],
    statement: str,
    rationale: str,
    impact_if_wrong: str,
    confidence: ConfidenceLevelStr = "medium",
    tags: Optional[List[str]] = None,
) -> str:
    """Log a structured assumption to the envelope.

    This is the high-level API for agents to log assumptions. It:
    - Auto-generates a sequential ID (ASM-001 format)
    - Auto-fills flow/step/agent from envelope context
    - Adds timestamp automatically
    - Returns the generated assumption ID

    Args:
        envelope_data: The envelope dictionary to modify.
        statement: The assumption itself (what is being assumed).
        rationale: Why this assumption was made (evidence, context).
        impact_if_wrong: What would need to change if assumption is incorrect.
        confidence: Confidence level - "high", "medium", or "low".
            Default is "medium".
        tags: Optional list of categorization tags (e.g., ["architecture", "api"]).

    Returns:
        The generated assumption ID (e.g., "ASM-001").

    Example:
        >>> envelope = {"step_id": "1", "flow_key": "signal", "station_id": "requirements-author"}
        >>> asm_id = log_assumption(
        ...     envelope,
        ...     statement="User wants REST API, not GraphQL",
        ...     rationale="No explicit API style mentioned; REST is conventional",
        ...     impact_if_wrong="Would need to redesign API layer for GraphQL",
        ...     confidence="medium",
        ...     tags=["architecture", "api"],
        ... )
        >>> asm_id
        'ASM-001'
    """
    # Generate sequential ID
    assumption_id = _generate_assumption_id(envelope_data)

    # Extract context from envelope
    ctx = _extract_context(envelope_data)

    # Build assumption entry
    assumption_entry: Dict[str, Any] = {
        "assumption_id": assumption_id,
        "flow_introduced": ctx["flow_key"],
        "step_introduced": ctx["step_id"],
        "agent": ctx["agent"],
        "statement": statement,
        "rationale": rationale,
        "impact_if_wrong": impact_if_wrong,
        "confidence": confidence,
        "status": "active",
        "tags": tags or [],
        "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
    }

    # Add to envelope using the underlying function
    add_assumption(envelope_data, assumption_entry)

    logger.info(
        "Logged assumption %s: %s (flow=%s, step=%s, agent=%s)",
        assumption_id,
        statement[:50] + "..." if len(statement) > 50 else statement,
        ctx["flow_key"],
        ctx["step_id"],
        ctx["agent"],
    )

    return assumption_id


def log_decision(
    envelope_data: Dict[str, Any],
    decision_type: str,
    subject: str,
    decision: str,
    rationale: str,
    supporting_evidence: Optional[List[str]] = None,
    conditions: Optional[List[str]] = None,
    assumptions_applied: Optional[List[str]] = None,
) -> str:
    """Log a structured decision to the envelope.

    This is the high-level API for agents to log decisions. It:
    - Auto-generates a sequential ID (DEC-001 format)
    - Auto-fills flow/step/agent from envelope context
    - Adds timestamp automatically
    - Returns the generated decision ID

    Args:
        envelope_data: The envelope dictionary to modify.
        decision_type: Category of decision (e.g., "architecture", "implementation",
            "routing", "design", "testing", "integration").
        subject: What the decision is about (e.g., "Database selection",
            "API design", "Test strategy").
        decision: The actual decision made.
        rationale: Why this decision was made.
        supporting_evidence: Optional list of evidence paths/references that
            support this decision (e.g., ["requirements.md:L45", "team_skills.md"]).
        conditions: Optional list of conditions under which this decision applies.
        assumptions_applied: Optional list of assumption IDs (e.g., ["ASM-001"])
            that influenced this decision.

    Returns:
        The generated decision ID (e.g., "DEC-001").

    Example:
        >>> envelope = {"step_id": "3", "flow_key": "plan", "station_id": "design-optioneer"}
        >>> dec_id = log_decision(
        ...     envelope,
        ...     decision_type="architecture",
        ...     subject="Database selection",
        ...     decision="Use PostgreSQL for primary data store",
        ...     rationale="Team expertise + ACID requirements + JSON support",
        ...     supporting_evidence=["requirements.md:L45", "team_skills.md"],
        ...     assumptions_applied=["ASM-001"],
        ... )
        >>> dec_id
        'DEC-001'
    """
    # Generate sequential ID
    decision_id = _generate_decision_id(envelope_data)

    # Extract context from envelope
    ctx = _extract_context(envelope_data)

    # Build decision entry
    decision_entry: Dict[str, Any] = {
        "decision_id": decision_id,
        "flow": ctx["flow_key"],
        "step": ctx["step_id"],
        "agent": ctx["agent"],
        "decision_type": decision_type,
        "subject": subject,
        "decision": decision,
        "rationale": rationale,
        "supporting_evidence": supporting_evidence or [],
        "conditions": conditions or [],
        "assumptions_applied": assumptions_applied or [],
        "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
    }

    # Add to envelope using the underlying function
    add_decision(envelope_data, decision_entry)

    logger.info(
        "Logged decision %s: %s -> %s (flow=%s, step=%s, agent=%s)",
        decision_id,
        subject,
        decision[:50] + "..." if len(decision) > 50 else decision,
        ctx["flow_key"],
        ctx["step_id"],
        ctx["agent"],
    )

    return decision_id


def get_assumption_by_id(
    envelope_data: Dict[str, Any],
    assumption_id: str,
) -> Optional[Dict[str, Any]]:
    """Retrieve an assumption by its ID.

    Args:
        envelope_data: The envelope dictionary to query.
        assumption_id: The assumption ID to look up (e.g., "ASM-001").

    Returns:
        The assumption entry dict if found, None otherwise.
    """
    assumptions = envelope_data.get("assumptions_made", [])
    for assumption in assumptions:
        if assumption.get("assumption_id") == assumption_id:
            return assumption
    return None


def get_decision_by_id(
    envelope_data: Dict[str, Any],
    decision_id: str,
) -> Optional[Dict[str, Any]]:
    """Retrieve a decision by its ID.

    Args:
        envelope_data: The envelope dictionary to query.
        decision_id: The decision ID to look up (e.g., "DEC-001").

    Returns:
        The decision entry dict if found, None otherwise.
    """
    decisions = envelope_data.get("decisions_made", [])
    for decision in decisions:
        if decision.get("decision_id") == decision_id:
            return decision
    return None


def list_assumptions(
    envelope_data: Dict[str, Any],
    status: Optional[str] = None,
    confidence: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """List assumptions with optional filtering.

    Args:
        envelope_data: The envelope dictionary to query.
        status: Optional filter by status ("active", "resolved", "invalidated").
        confidence: Optional filter by confidence ("high", "medium", "low").

    Returns:
        List of matching assumption entries.
    """
    assumptions = envelope_data.get("assumptions_made", [])
    result = []
    for assumption in assumptions:
        if status is not None and assumption.get("status") != status:
            continue
        if confidence is not None and assumption.get("confidence") != confidence:
            continue
        result.append(assumption)
    return result


def list_decisions(
    envelope_data: Dict[str, Any],
    decision_type: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """List decisions with optional filtering.

    Args:
        envelope_data: The envelope dictionary to query.
        decision_type: Optional filter by decision type.

    Returns:
        List of matching decision entries.
    """
    decisions = envelope_data.get("decisions_made", [])
    if decision_type is None:
        return list(decisions)
    return [d for d in decisions if d.get("decision_type") == decision_type]


def get_assumptions_for_decision(
    envelope_data: Dict[str, Any],
    decision_id: str,
) -> List[Dict[str, Any]]:
    """Get all assumptions that were applied to a specific decision.

    Args:
        envelope_data: The envelope dictionary to query.
        decision_id: The decision ID to find assumptions for.

    Returns:
        List of assumption entries that were applied to this decision.
    """
    decision = get_decision_by_id(envelope_data, decision_id)
    if decision is None:
        return []

    assumption_ids = decision.get("assumptions_applied", [])
    result = []
    for asm_id in assumption_ids:
        assumption = get_assumption_by_id(envelope_data, asm_id)
        if assumption is not None:
            result.append(assumption)
    return result


def format_assumption_for_prompt(assumption: Dict[str, Any]) -> str:
    """Format an assumption entry as a markdown block for use in prompts.

    Args:
        assumption: The assumption entry dict.

    Returns:
        Formatted markdown string.
    """
    lines = [
        f"- **{assumption.get('assumption_id', 'Unknown')}**: {assumption.get('statement', '')}",
        f"  - Rationale: {assumption.get('rationale', '')}",
        f"  - Impact if wrong: {assumption.get('impact_if_wrong', '')}",
        f"  - Confidence: {assumption.get('confidence', 'medium')}",
    ]
    tags = assumption.get("tags", [])
    if tags:
        lines.append(f"  - Tags: {', '.join(tags)}")
    return "\n".join(lines)


def format_decision_for_prompt(decision: Dict[str, Any]) -> str:
    """Format a decision entry as a markdown block for use in prompts.

    Args:
        decision: The decision entry dict.

    Returns:
        Formatted markdown string.
    """
    lines = [
        f"- **{decision.get('decision_id', 'Unknown')}** [{decision.get('decision_type', '')}]: {decision.get('subject', '')}",
        f"  - Decision: {decision.get('decision', '')}",
        f"  - Rationale: {decision.get('rationale', '')}",
    ]
    evidence = decision.get("supporting_evidence", [])
    if evidence:
        lines.append(f"  - Evidence: {', '.join(evidence)}")
    assumptions = decision.get("assumptions_applied", [])
    if assumptions:
        lines.append(f"  - Based on assumptions: {', '.join(assumptions)}")
    return "\n".join(lines)
