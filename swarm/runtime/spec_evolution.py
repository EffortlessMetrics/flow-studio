"""
spec_evolution.py - Graph evolution logic for Flow 7 (Wisdom) spec improvements.

This module analyzes EXTEND_GRAPH routing events from flow execution and generates
JSON Patch proposals for FlowGraph evolution. These proposals appear as "Suggested
Improvements" in the Flow Studio UI, enabling human-reviewed spec evolution.

The evolution loop:
1. Wisdom flow analyzes routing logs for EXTEND_GRAPH events
2. analyze_extend_graph_events() extracts proposals from run state
3. generate_flow_patch() creates RFC 6902 JSON Patch operations
4. save_evolution_proposal() writes proposals to RUN_BASE/wisdom/evolution/

Key principles:
- Proposals are suggestions, never auto-applied
- All proposals require human approval before application
- Proposals are structured for UI display with "Apply" / "Dismiss" actions
- Evolution is incremental and auditable

Usage:
    from swarm.runtime.spec_evolution import (
        GraphEvolutionProposal,
        analyze_extend_graph_events,
        generate_flow_patch,
        save_evolution_proposal,
    )

    # Analyze run state for EXTEND_GRAPH events
    proposals = analyze_extend_graph_events(run_state)

    # Generate JSON patches for each proposal
    for proposal in proposals:
        patch = generate_flow_patch(proposal)
        proposal.json_patch = patch

    # Save proposals to disk for UI display
    save_evolution_proposal(proposals, run_base)
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger(__name__)


# =============================================================================
# Enums
# =============================================================================


class ProposalType(str, Enum):
    """Type of graph evolution proposal."""

    ADD_NODE = "add_node"  # Add a new node to a flow
    ADD_EDGE = "add_edge"  # Add a new edge between nodes
    MODIFY_NODE = "modify_node"  # Modify an existing node's configuration
    MODIFY_POLICY = "modify_policy"  # Modify flow policy (detours, injections)
    ADD_DETOUR = "add_detour"  # Add a suggested detour to policy
    ADD_INJECTION = "add_injection"  # Add a suggested injection to policy


class ProposalStatus(str, Enum):
    """Status of a proposal through its lifecycle."""

    PENDING = "pending"  # Awaiting human review
    APPROVED = "approved"  # Human approved, ready to apply
    APPLIED = "applied"  # Patch has been applied
    DISMISSED = "dismissed"  # Human dismissed, will not apply
    SUPERSEDED = "superseded"  # Replaced by a newer proposal


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class GraphEvolutionProposal:
    """A proposal to evolve a flow graph based on EXTEND_GRAPH routing events.

    Represents a suggested improvement from the Wisdom flow that can be reviewed
    by humans and applied to flow/station specs.

    Attributes:
        id: Unique identifier for this proposal (e.g., "GEP-001").
        source_event: The EXTEND_GRAPH event ID that triggered this proposal.
        target_flow: The flow to modify (e.g., "build", "gate").
        proposal_type: Type of change (add_node, add_edge, modify_policy, etc.).
        description: Human-readable description of the proposed change.
        json_patch: RFC 6902 JSON Patch operations to apply.
        confidence: Confidence score (0.0 to 1.0) based on evidence strength.
        rationale: Detailed explanation of why this change is recommended.
        evidence: List of evidence sources (file paths, run IDs, event IDs).
        source_run_id: The run ID that generated this proposal.
        pattern_count: Number of times this pattern was observed.
        status: Current proposal status (pending, approved, applied, dismissed).
        created_at: ISO 8601 timestamp when proposal was created.
        reviewed_at: ISO 8601 timestamp when proposal was reviewed.
        reviewed_by: Who reviewed the proposal (human or system).
    """

    id: str
    source_event: str
    target_flow: str
    proposal_type: ProposalType
    description: str
    json_patch: List[Dict[str, Any]] = field(default_factory=list)
    confidence: float = 0.5
    rationale: str = ""
    evidence: List[str] = field(default_factory=list)
    source_run_id: Optional[str] = None
    pattern_count: int = 1
    status: ProposalStatus = ProposalStatus.PENDING
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    reviewed_at: Optional[str] = None
    reviewed_by: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "id": self.id,
            "source_event": self.source_event,
            "target_flow": self.target_flow,
            "proposal_type": self.proposal_type.value,
            "description": self.description,
            "json_patch": self.json_patch,
            "confidence": self.confidence,
            "rationale": self.rationale,
            "evidence": self.evidence,
            "source_run_id": self.source_run_id,
            "pattern_count": self.pattern_count,
            "status": self.status.value,
            "created_at": self.created_at,
            "reviewed_at": self.reviewed_at,
            "reviewed_by": self.reviewed_by,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GraphEvolutionProposal":
        """Create from dictionary."""
        return cls(
            id=data["id"],
            source_event=data.get("source_event", ""),
            target_flow=data.get("target_flow", ""),
            proposal_type=ProposalType(data.get("proposal_type", "add_node")),
            description=data.get("description", ""),
            json_patch=data.get("json_patch", []),
            confidence=data.get("confidence", 0.5),
            rationale=data.get("rationale", ""),
            evidence=data.get("evidence", []),
            source_run_id=data.get("source_run_id"),
            pattern_count=data.get("pattern_count", 1),
            status=ProposalStatus(data.get("status", "pending")),
            created_at=data.get(
                "created_at", datetime.now(timezone.utc).isoformat()
            ),
            reviewed_at=data.get("reviewed_at"),
            reviewed_by=data.get("reviewed_by"),
        )


@dataclass
class ExtendGraphEvent:
    """An EXTEND_GRAPH routing event extracted from run state.

    Attributes:
        event_id: Unique identifier for this event.
        flow_key: The flow where this event occurred.
        node_id: The node that triggered this event.
        decision_type: The routing decision type (always EXTEND_GRAPH).
        target: The target for the proposed extension.
        justification: Human-readable justification for the extension.
        why_now: Structured WhyNow justification if available.
        timestamp: When this event occurred.
        observations: Related observations from the station.
    """

    event_id: str
    flow_key: str
    node_id: str
    decision_type: str = "EXTEND_GRAPH"
    target: str = ""
    justification: str = ""
    why_now: Optional[Dict[str, Any]] = None
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    observations: List[Dict[str, Any]] = field(default_factory=list)


# =============================================================================
# Analysis Functions
# =============================================================================


def analyze_extend_graph_events(
    run_state: Any,
    routing_log_path: Optional[Path] = None,
) -> List[GraphEvolutionProposal]:
    """Analyze run state for EXTEND_GRAPH routing events and generate proposals.

    Scans the run state and routing logs for EXTEND_GRAPH events, then generates
    GraphEvolutionProposal objects for each unique pattern detected.

    Args:
        run_state: The RunState object containing execution state.
        routing_log_path: Optional path to routing decisions.jsonl file.

    Returns:
        List of GraphEvolutionProposal objects for detected patterns.
    """
    proposals: List[GraphEvolutionProposal] = []
    extend_graph_events: List[ExtendGraphEvent] = []

    # Extract events from run state handoff envelopes
    if hasattr(run_state, "handoff_envelopes"):
        for step_id, envelope in run_state.handoff_envelopes.items():
            events = _extract_events_from_envelope(
                envelope, run_state.flow_key, step_id, run_state.run_id
            )
            extend_graph_events.extend(events)

    # Extract events from routing log if provided
    if routing_log_path and routing_log_path.exists():
        log_events = _parse_routing_log(routing_log_path, run_state.run_id)
        extend_graph_events.extend(log_events)

    # Group events by pattern and generate proposals
    pattern_groups = _group_events_by_pattern(extend_graph_events)

    for pattern_key, events in pattern_groups.items():
        proposal = _generate_proposal_from_events(
            events, pattern_key, run_state.run_id
        )
        if proposal:
            proposals.append(proposal)

    logger.info(
        "Analyzed %d EXTEND_GRAPH events, generated %d proposals",
        len(extend_graph_events),
        len(proposals),
    )

    return proposals


def _extract_events_from_envelope(
    envelope: Any,
    flow_key: str,
    step_id: str,
    run_id: str,
) -> List[ExtendGraphEvent]:
    """Extract EXTEND_GRAPH events from a handoff envelope.

    Args:
        envelope: The HandoffEnvelope object.
        flow_key: The flow key for context.
        step_id: The step that produced this envelope.
        run_id: The run identifier.

    Returns:
        List of ExtendGraphEvent objects found in the envelope.
    """
    events: List[ExtendGraphEvent] = []

    # Check routing signal in envelope
    routing = None
    if hasattr(envelope, "routing"):
        routing = envelope.routing
    elif isinstance(envelope, dict):
        routing = envelope.get("routing", {})

    if not routing:
        return events

    # Check for EXTEND_GRAPH decision
    decision = None
    if hasattr(routing, "decision"):
        decision = routing.decision
    elif isinstance(routing, dict):
        decision = routing.get("decision")

    if decision and str(decision).upper() in ("EXTEND_GRAPH", "extend_graph"):
        event_id = _generate_event_id(run_id, flow_key, step_id)

        # Extract target
        target = ""
        if hasattr(routing, "target"):
            target = routing.target or ""
        elif isinstance(routing, dict):
            target = routing.get("target", "") or routing.get("next_step", "")

        # Extract justification
        justification = ""
        if hasattr(routing, "reason"):
            justification = routing.reason or ""
        elif isinstance(routing, dict):
            justification = routing.get("reason", "")

        # Extract why_now
        why_now = None
        if hasattr(routing, "why_now"):
            why_now = routing.why_now
        elif isinstance(routing, dict):
            why_now = routing.get("why_now")

        # Extract observations
        observations = []
        if hasattr(envelope, "observations"):
            observations = envelope.observations or []
        elif isinstance(envelope, dict):
            observations = envelope.get("observations", [])

        event = ExtendGraphEvent(
            event_id=event_id,
            flow_key=flow_key,
            node_id=step_id,
            target=target,
            justification=justification,
            why_now=why_now if isinstance(why_now, dict) else None,
            observations=observations if isinstance(observations, list) else [],
        )
        events.append(event)

    return events


def _parse_routing_log(
    log_path: Path,
    run_id: str,
) -> List[ExtendGraphEvent]:
    """Parse routing decisions.jsonl for EXTEND_GRAPH events.

    Args:
        log_path: Path to the decisions.jsonl file.
        run_id: The run identifier for context.

    Returns:
        List of ExtendGraphEvent objects from the log.
    """
    events: List[ExtendGraphEvent] = []

    try:
        with open(log_path, "r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue

                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    logger.warning(
                        "Failed to parse routing log line %d in %s",
                        line_num,
                        log_path,
                    )
                    continue

                decision = entry.get("decision", "")
                if decision.upper() == "EXTEND_GRAPH":
                    event = ExtendGraphEvent(
                        event_id=entry.get("event_id", f"LOG-{line_num:04d}"),
                        flow_key=entry.get("flow_id", entry.get("flow_key", "")),
                        node_id=entry.get("source_node", entry.get("node_id", "")),
                        target=entry.get("target", ""),
                        justification=entry.get("justification", ""),
                        why_now=entry.get("why_now"),
                        timestamp=entry.get("timestamp", ""),
                        observations=entry.get("observations", []),
                    )
                    events.append(event)

    except Exception as e:
        logger.warning("Failed to parse routing log %s: %s", log_path, e)

    return events


def _group_events_by_pattern(
    events: List[ExtendGraphEvent],
) -> Dict[str, List[ExtendGraphEvent]]:
    """Group EXTEND_GRAPH events by their pattern signature.

    Events are grouped by (target_flow, node_id, target) to identify
    recurring patterns that warrant spec evolution.

    Args:
        events: List of ExtendGraphEvent objects.

    Returns:
        Dictionary mapping pattern keys to event lists.
    """
    groups: Dict[str, List[ExtendGraphEvent]] = {}

    for event in events:
        # Create a pattern key from the event's characteristics
        pattern_key = f"{event.flow_key}:{event.node_id}:{event.target}"
        if pattern_key not in groups:
            groups[pattern_key] = []
        groups[pattern_key].append(event)

    return groups


def _generate_proposal_from_events(
    events: List[ExtendGraphEvent],
    pattern_key: str,
    run_id: str,
) -> Optional[GraphEvolutionProposal]:
    """Generate a GraphEvolutionProposal from a group of events.

    Args:
        events: List of related ExtendGraphEvent objects.
        pattern_key: The pattern key for this group.
        run_id: The run identifier.

    Returns:
        GraphEvolutionProposal or None if events are insufficient.
    """
    if not events:
        return None

    # Use the first event as the primary source
    primary_event = events[0]
    pattern_count = len(events)

    # Calculate confidence based on pattern frequency
    # More occurrences = higher confidence (capped at 0.9)
    base_confidence = min(0.3 + (pattern_count * 0.1), 0.9)

    # Adjust confidence based on why_now presence
    if primary_event.why_now:
        base_confidence = min(base_confidence + 0.1, 0.95)

    # Determine proposal type from event characteristics
    proposal_type = _infer_proposal_type(primary_event)

    # Generate a unique proposal ID
    proposal_id = _generate_proposal_id(pattern_key, run_id)

    # Collect evidence from all events
    evidence = []
    for event in events:
        evidence.append(f"event:{event.event_id}")
        if event.why_now:
            if event.why_now.get("trigger"):
                evidence.append(f"trigger:{event.why_now['trigger'][:50]}")

    # Build rationale
    rationale = _build_rationale(events, primary_event)

    proposal = GraphEvolutionProposal(
        id=proposal_id,
        source_event=primary_event.event_id,
        target_flow=primary_event.flow_key,
        proposal_type=proposal_type,
        description=_build_description(primary_event, pattern_count),
        confidence=round(base_confidence, 2),
        rationale=rationale,
        evidence=evidence,
        source_run_id=run_id,
        pattern_count=pattern_count,
    )

    return proposal


def _infer_proposal_type(event: ExtendGraphEvent) -> ProposalType:
    """Infer the proposal type from event characteristics.

    Args:
        event: The ExtendGraphEvent to analyze.

    Returns:
        The inferred ProposalType.
    """
    target_lower = event.target.lower()

    if "detour" in target_lower or "sidequest" in target_lower:
        return ProposalType.ADD_DETOUR
    elif "inject" in target_lower:
        return ProposalType.ADD_INJECTION
    elif "policy" in target_lower:
        return ProposalType.MODIFY_POLICY
    elif "edge" in target_lower or "connection" in target_lower:
        return ProposalType.ADD_EDGE
    else:
        # Default to ADD_NODE for new station/step suggestions
        return ProposalType.ADD_NODE


def _build_description(event: ExtendGraphEvent, pattern_count: int) -> str:
    """Build a human-readable description for the proposal.

    Args:
        event: The primary ExtendGraphEvent.
        pattern_count: Number of times this pattern was observed.

    Returns:
        A description string.
    """
    base_desc = event.justification or f"Extend {event.flow_key} with {event.target}"

    if pattern_count > 1:
        return f"{base_desc} (observed {pattern_count} times)"
    return base_desc


def _build_rationale(
    events: List[ExtendGraphEvent],
    primary_event: ExtendGraphEvent,
) -> str:
    """Build a detailed rationale from events.

    Args:
        events: All related events.
        primary_event: The primary event.

    Returns:
        A rationale string.
    """
    parts = []

    # Add why_now analysis if available
    if primary_event.why_now:
        why_now = primary_event.why_now
        if why_now.get("trigger"):
            parts.append(f"Trigger: {why_now['trigger']}")
        if why_now.get("analysis"):
            parts.append(f"Analysis: {why_now['analysis']}")
        if why_now.get("relevance_to_charter"):
            parts.append(f"Charter relevance: {why_now['relevance_to_charter']}")

    # Add observations summary
    observation_count = sum(len(e.observations) for e in events)
    if observation_count > 0:
        parts.append(f"Based on {observation_count} station observations")

    # Add pattern frequency
    if len(events) > 1:
        parts.append(f"Pattern observed across {len(events)} execution points")

    return ". ".join(parts) if parts else primary_event.justification


def _generate_event_id(run_id: str, flow_key: str, step_id: str) -> str:
    """Generate a unique event ID."""
    content = f"{run_id}:{flow_key}:{step_id}:{datetime.now(timezone.utc).isoformat()}"
    return f"EVT-{hashlib.sha256(content.encode()).hexdigest()[:8].upper()}"


def _generate_proposal_id(pattern_key: str, run_id: str) -> str:
    """Generate a unique proposal ID."""
    content = f"{pattern_key}:{run_id}"
    return f"GEP-{hashlib.sha256(content.encode()).hexdigest()[:6].upper()}"


# =============================================================================
# Patch Generation Functions
# =============================================================================


def generate_flow_patch(
    proposal: GraphEvolutionProposal,
) -> List[Dict[str, Any]]:
    """Generate RFC 6902 JSON Patch operations for a proposal.

    Creates the specific JSON Patch operations needed to apply the proposed
    change to the target flow graph.

    Args:
        proposal: The GraphEvolutionProposal to generate patches for.

    Returns:
        List of RFC 6902 JSON Patch operation dictionaries.
    """
    operations: List[Dict[str, Any]] = []

    if proposal.proposal_type == ProposalType.ADD_NODE:
        operations.extend(_generate_add_node_patch(proposal))
    elif proposal.proposal_type == ProposalType.ADD_EDGE:
        operations.extend(_generate_add_edge_patch(proposal))
    elif proposal.proposal_type == ProposalType.MODIFY_NODE:
        operations.extend(_generate_modify_node_patch(proposal))
    elif proposal.proposal_type == ProposalType.MODIFY_POLICY:
        operations.extend(_generate_modify_policy_patch(proposal))
    elif proposal.proposal_type == ProposalType.ADD_DETOUR:
        operations.extend(_generate_add_detour_patch(proposal))
    elif proposal.proposal_type == ProposalType.ADD_INJECTION:
        operations.extend(_generate_add_injection_patch(proposal))

    return operations


def _generate_add_node_patch(
    proposal: GraphEvolutionProposal,
) -> List[Dict[str, Any]]:
    """Generate patch operations for adding a new node."""
    # Extract node ID from source event or description
    node_id = _extract_node_id_from_proposal(proposal)

    # Create a new node definition
    new_node = {
        "node_id": node_id,
        "template_id": node_id,  # Assumes template matches node ID
        "params": {
            "objective": proposal.description,
        },
        "ui": {
            "type": "step",
            "label": _title_case(node_id),
            "position": {"x": 200, "y": 500},  # Placeholder position
            "color": "#94a3b8",
            "teaching": {
                "highlight": False,
                "note": f"Added via evolution proposal {proposal.id}",
            },
        },
    }

    return [
        {
            "op": "add",
            "path": "/nodes/-",
            "value": new_node,
        }
    ]


def _generate_add_edge_patch(
    proposal: GraphEvolutionProposal,
) -> List[Dict[str, Any]]:
    """Generate patch operations for adding a new edge."""
    # Parse source and target from description or evidence
    source_node = "unknown"
    target_node = _extract_node_id_from_proposal(proposal)

    new_edge = {
        "edge_id": f"e-{source_node}-to-{target_node}",
        "from": source_node,
        "to": target_node,
        "type": "sequence",
    }

    return [
        {
            "op": "add",
            "path": "/edges/-",
            "value": new_edge,
        }
    ]


def _generate_modify_node_patch(
    proposal: GraphEvolutionProposal,
) -> List[Dict[str, Any]]:
    """Generate patch operations for modifying an existing node."""
    # This is more complex - requires knowing the node index
    # For now, return a placeholder operation
    return [
        {
            "op": "replace",
            "path": "/nodes/0/params/objective",
            "value": proposal.description,
        }
    ]


def _generate_modify_policy_patch(
    proposal: GraphEvolutionProposal,
) -> List[Dict[str, Any]]:
    """Generate patch operations for modifying flow policy."""
    return [
        {
            "op": "add",
            "path": "/policy/invariants/-",
            "value": proposal.description,
        }
    ]


def _generate_add_detour_patch(
    proposal: GraphEvolutionProposal,
) -> List[Dict[str, Any]]:
    """Generate patch operations for adding a suggested detour."""
    node_id = _extract_node_id_from_proposal(proposal)

    new_detour = {
        "from_nodes": ["*"],  # Apply to all nodes by default
        "to_station": node_id,
        "condition": {
            "field": "status",
            "operator": "eq",
            "value": "UNVERIFIED",
        },
        "return_to": "next",
        "priority": 50,
    }

    return [
        {
            "op": "add",
            "path": "/policy/suggested_detours/-",
            "value": new_detour,
        }
    ]


def _generate_add_injection_patch(
    proposal: GraphEvolutionProposal,
) -> List[Dict[str, Any]]:
    """Generate patch operations for adding a suggested injection."""
    node_id = _extract_node_id_from_proposal(proposal)

    new_injection = {
        "station_id": node_id,
        "inject_after": ["*"],  # Placeholder - needs context
        "condition": {
            "field": "pattern_count",
            "operator": "gt",
            "value": 0,
        },
        "one_shot": True,
        "priority": 50,
        "injection_type": "INJECT_NODES",
    }

    return [
        {
            "op": "add",
            "path": "/policy/suggested_injections/-",
            "value": new_injection,
        }
    ]


def _extract_node_id_from_proposal(proposal: GraphEvolutionProposal) -> str:
    """Extract a node ID from proposal content."""
    # Try to extract from source_event
    if proposal.source_event:
        parts = proposal.source_event.split(":")
        if len(parts) >= 2:
            return parts[-1].lower().replace(" ", "-")

    # Fall back to description-based extraction
    desc = proposal.description.lower()
    # Remove common prefixes/suffixes
    for prefix in ["add ", "extend ", "inject ", "include "]:
        if desc.startswith(prefix):
            desc = desc[len(prefix):]
            break

    # Take first few words and slugify
    words = desc.split()[:3]
    return "-".join(words).replace("_", "-")


def _title_case(s: str) -> str:
    """Convert kebab-case to Title Case."""
    return " ".join(word.capitalize() for word in s.replace("-", " ").split())


# =============================================================================
# Persistence Functions
# =============================================================================


def save_evolution_proposal(
    proposals: Union[GraphEvolutionProposal, List[GraphEvolutionProposal]],
    run_base: Path,
) -> Path:
    """Save evolution proposals to disk for UI display.

    Writes proposals to RUN_BASE/wisdom/evolution/proposals.json in a format
    suitable for the Flow Studio UI to display as actionable suggestions.

    Args:
        proposals: Single proposal or list of proposals to save.
        run_base: Path to the run base directory (RUN_BASE).

    Returns:
        Path to the written proposals.json file.
    """
    if isinstance(proposals, GraphEvolutionProposal):
        proposals = [proposals]

    # Ensure evolution directory exists
    evolution_dir = run_base / "wisdom" / "evolution"
    evolution_dir.mkdir(parents=True, exist_ok=True)

    proposals_path = evolution_dir / "proposals.json"

    # Load existing proposals if any
    existing_proposals: List[Dict[str, Any]] = []
    if proposals_path.exists():
        try:
            with open(proposals_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                existing_proposals = data.get("proposals", [])
        except (json.JSONDecodeError, KeyError):
            pass

    # Convert new proposals to dicts
    new_proposal_dicts = [p.to_dict() for p in proposals]

    # Merge proposals, avoiding duplicates by ID
    existing_ids = {p["id"] for p in existing_proposals}
    for new_p in new_proposal_dicts:
        if new_p["id"] not in existing_ids:
            existing_proposals.append(new_p)
            existing_ids.add(new_p["id"])

    # Write the combined proposals
    output = {
        "schema_version": "evolution_proposals_v1",
        "run_base": str(run_base),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "proposal_count": len(existing_proposals),
        "proposals": existing_proposals,
    }

    with open(proposals_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    logger.info(
        "Saved %d evolution proposals to %s",
        len(new_proposal_dicts),
        proposals_path,
    )

    # Also write a summary markdown for human review
    _write_proposals_summary(existing_proposals, evolution_dir)

    return proposals_path


def _write_proposals_summary(
    proposals: List[Dict[str, Any]],
    evolution_dir: Path,
) -> None:
    """Write a human-readable summary of proposals."""
    summary_path = evolution_dir / "PROPOSALS_SUMMARY.md"

    lines = [
        "# Evolution Proposals",
        "",
        f"Generated at: {datetime.now(timezone.utc).isoformat()}",
        "",
        f"Total proposals: {len(proposals)}",
        "",
        "---",
        "",
    ]

    for proposal in proposals:
        status_emoji = {
            "pending": "O",
            "approved": "+",
            "applied": "*",
            "dismissed": "X",
            "superseded": "~",
        }.get(proposal.get("status", "pending"), "?")

        lines.extend([
            f"## [{status_emoji}] {proposal['id']}: {proposal['description'][:60]}",
            "",
            f"- **Type:** {proposal.get('proposal_type', 'unknown')}",
            f"- **Target Flow:** {proposal.get('target_flow', 'unknown')}",
            f"- **Confidence:** {proposal.get('confidence', 0):.0%}",
            f"- **Pattern Count:** {proposal.get('pattern_count', 1)}",
            f"- **Status:** {proposal.get('status', 'pending')}",
            "",
            "### Rationale",
            "",
            proposal.get("rationale", "No rationale provided."),
            "",
            "### JSON Patch Preview",
            "",
            "```json",
            json.dumps(proposal.get("json_patch", []), indent=2),
            "```",
            "",
            "---",
            "",
        ])

    with open(summary_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def load_evolution_proposals(run_base: Path) -> List[GraphEvolutionProposal]:
    """Load evolution proposals from disk.

    Args:
        run_base: Path to the run base directory (RUN_BASE).

    Returns:
        List of GraphEvolutionProposal objects.
    """
    proposals_path = run_base / "wisdom" / "evolution" / "proposals.json"

    if not proposals_path.exists():
        return []

    try:
        with open(proposals_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        return [
            GraphEvolutionProposal.from_dict(p) for p in data.get("proposals", [])
        ]
    except (json.JSONDecodeError, KeyError) as e:
        logger.warning("Failed to load evolution proposals: %s", e)
        return []


# =============================================================================
# Routing-Time Proposal Persistence
# =============================================================================


def persist_routing_proposal(
    run_base: Path,
    flow_key: str,
    step_id: str,
    proposed_edge: Any,
    why_now: Optional[Dict[str, Any]] = None,
    routing_reason: str = "",
) -> Path:
    """Persist an EXTEND_GRAPH proposal at routing decision time.

    Unlike save_evolution_proposal (which saves to wisdom/evolution/ post-hoc),
    this function persists proposals immediately when the routing decision
    is made, at: RUN_BASE/<flow>/routing/proposals/<proposal_id>.json

    This ensures EXTEND_GRAPH decisions produce durable artifacts that can be:
    - Referenced in route_decision event payloads
    - Included in envelope routing_signal.proposal_path
    - Analyzed by Wisdom without depending on events.jsonl parsing

    Args:
        run_base: Path to the run base directory (RUN_BASE).
        flow_key: The flow where the decision was made.
        step_id: The step that triggered the decision.
        proposed_edge: The ProposedEdge object from Navigator.
        why_now: Optional WhyNow justification.
        routing_reason: Human-readable reason for the proposal.

    Returns:
        Path to the written proposal file.
    """
    # Ensure routing/proposals directory exists
    proposals_dir = run_base / flow_key / "routing" / "proposals"
    proposals_dir.mkdir(parents=True, exist_ok=True)

    # Generate proposal ID
    timestamp = datetime.now(timezone.utc)
    proposal_id = f"RP-{timestamp.strftime('%Y%m%d-%H%M%S')}-{step_id[:8]}"

    # Extract edge data
    edge_data: Dict[str, Any] = {}
    if proposed_edge is not None:
        if hasattr(proposed_edge, "to_node"):
            edge_data = {
                "from_node": getattr(proposed_edge, "from_node", step_id),
                "to_node": proposed_edge.to_node,
                "edge_type": getattr(proposed_edge, "edge_type", "sequence"),
                "priority": getattr(proposed_edge, "priority", 50),
                "is_return": getattr(proposed_edge, "is_return", False),
                "why": getattr(proposed_edge, "why", routing_reason),
            }
            # Include proposed node if present
            if hasattr(proposed_edge, "proposed_node") and proposed_edge.proposed_node:
                pn = proposed_edge.proposed_node
                edge_data["proposed_node"] = {
                    "node_id": getattr(pn, "node_id", None),
                    "station_id": getattr(pn, "station_id", None),
                    "template_id": getattr(pn, "template_id", None),
                    "objective": getattr(pn, "objective", None),
                }
        elif isinstance(proposed_edge, dict):
            edge_data = proposed_edge

    # Build proposal record
    proposal = {
        "schema_version": "routing_proposal_v1",
        "proposal_id": proposal_id,
        "decision_type": "EXTEND_GRAPH",
        "flow_key": flow_key,
        "step_id": step_id,
        "timestamp": timestamp.isoformat(),
        "proposed_edge": edge_data,
        "why_now": why_now,
        "routing_reason": routing_reason,
        "status": "recorded",
        # JSON Patch suggestion (placeholder for UI)
        "suggested_patch": _generate_extend_graph_patch(edge_data),
    }

    # Write proposal file
    proposal_path = proposals_dir / f"{proposal_id}.json"
    with open(proposal_path, "w", encoding="utf-8") as f:
        json.dump(proposal, f, indent=2, ensure_ascii=False)

    logger.info(
        "Persisted routing proposal %s to %s",
        proposal_id,
        proposal_path,
    )

    # Also append to the decisions ledger
    _append_to_routing_ledger(run_base, flow_key, proposal)

    return proposal_path


def _generate_extend_graph_patch(edge_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Generate JSON Patch operations from edge data.

    Args:
        edge_data: The proposed edge data.

    Returns:
        List of RFC 6902 JSON Patch operations.
    """
    patches: List[Dict[str, Any]] = []

    # Add node if proposed
    if edge_data.get("proposed_node"):
        node = edge_data["proposed_node"]
        patches.append({
            "op": "add",
            "path": "/nodes/-",
            "value": {
                "node_id": node.get("node_id") or f"suggested-{edge_data.get('to_node')}",
                "template_id": node.get("template_id") or edge_data.get("to_node"),
                "station_id": node.get("station_id"),
                "params": {
                    "objective": node.get("objective", ""),
                },
            },
        })

    # Add edge
    patches.append({
        "op": "add",
        "path": "/edges/-",
        "value": {
            "edge_id": f"suggested-{edge_data.get('from_node', 'unknown')}-{edge_data.get('to_node', 'unknown')}",
            "from": edge_data.get("from_node", "unknown"),
            "to": edge_data.get("to_node", "unknown"),
            "type": edge_data.get("edge_type", "sequence"),
            "priority": edge_data.get("priority", 50),
        },
    })

    return patches


def _append_to_routing_ledger(
    run_base: Path,
    flow_key: str,
    proposal: Dict[str, Any],
) -> None:
    """Append a routing proposal to the decisions ledger.

    The ledger is an append-only JSONL file at:
    RUN_BASE/<flow>/routing/decisions.jsonl

    Args:
        run_base: Path to the run base directory.
        flow_key: The flow key.
        proposal: The proposal record to append.
    """
    routing_dir = run_base / flow_key / "routing"
    routing_dir.mkdir(parents=True, exist_ok=True)

    ledger_path = routing_dir / "decisions.jsonl"

    ledger_entry = {
        "event_type": "extend_graph_proposal",
        "proposal_id": proposal["proposal_id"],
        "step_id": proposal["step_id"],
        "timestamp": proposal["timestamp"],
        "decision": "EXTEND_GRAPH",
        "target": proposal.get("proposed_edge", {}).get("to_node"),
        "proposal_path": str(run_base / flow_key / "routing" / "proposals" / f"{proposal['proposal_id']}.json"),
    }

    with open(ledger_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(ledger_entry, ensure_ascii=False) + "\n")


def load_routing_proposals(
    run_base: Path,
    flow_key: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Load routing proposals from disk.

    Args:
        run_base: Path to the run base directory.
        flow_key: Optional flow key to filter by. If None, loads from all flows.

    Returns:
        List of proposal dictionaries.
    """
    proposals: List[Dict[str, Any]] = []

    if flow_key:
        flow_dirs = [run_base / flow_key]
    else:
        # Scan all flow directories
        flow_dirs = [d for d in run_base.iterdir() if d.is_dir() and (d / "routing" / "proposals").exists()]

    for flow_dir in flow_dirs:
        proposals_dir = flow_dir / "routing" / "proposals"
        if not proposals_dir.exists():
            continue

        for proposal_file in proposals_dir.glob("*.json"):
            try:
                with open(proposal_file, "r", encoding="utf-8") as f:
                    proposal = json.load(f)
                    proposal["_file_path"] = str(proposal_file)
                    proposals.append(proposal)
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("Failed to load proposal %s: %s", proposal_file, e)

    return proposals


def update_proposal_status(
    run_base: Path,
    proposal_id: str,
    new_status: ProposalStatus,
    reviewed_by: str = "human",
) -> bool:
    """Update the status of a proposal.

    Args:
        run_base: Path to the run base directory.
        proposal_id: The ID of the proposal to update.
        new_status: The new status to set.
        reviewed_by: Who reviewed/updated the proposal.

    Returns:
        True if the proposal was found and updated, False otherwise.
    """
    proposals_path = run_base / "wisdom" / "evolution" / "proposals.json"

    if not proposals_path.exists():
        return False

    try:
        with open(proposals_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        proposals = data.get("proposals", [])
        updated = False

        for proposal in proposals:
            if proposal.get("id") == proposal_id:
                proposal["status"] = new_status.value
                proposal["reviewed_at"] = datetime.now(timezone.utc).isoformat()
                proposal["reviewed_by"] = reviewed_by
                updated = True
                break

        if updated:
            with open(proposals_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            # Update the summary
            _write_proposals_summary(proposals, proposals_path.parent)

        return updated

    except (json.JSONDecodeError, KeyError) as e:
        logger.warning("Failed to update proposal status: %s", e)
        return False
