"""
Routing Audit Trail: Off-Road Decision Logging

When flows deviate from the golden path, every decision is logged.
This creates an append-only audit trail for V3 routing.

Artifacts:
- RUN_BASE/<flow>/routing/decisions.jsonl - Append-only decision log
- RUN_BASE/<flow>/routing/injections/ - Flow/node injection records
- RUN_BASE/<flow>/routing/proposals/ - Graph extension proposals

The golden path (CONTINUE at every step) needs no special logging.
But when routing goes "off-road" (LOOP, DETOUR, INJECT_FLOW, INJECT_NODES,
ESCALATE), every decision must be traceable.

Logging Rules:
- Always log: All non-CONTINUE decisions, all injections, all escalations
- Never log: CONTINUE decisions on golden path (implicit)
- Format: JSONL for decisions (append-only), JSON for injection/proposal records

See .claude/rules/artifacts/off-road-logging.md for the full specification.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Directory names
ROUTING_DIR = "routing"
INJECTIONS_DIR = "injections"
PROPOSALS_DIR = "proposals"

# File names
DECISIONS_FILE = "decisions.jsonl"

# Valid decision types
VALID_DECISIONS = frozenset({
    "CONTINUE",
    "LOOP",
    "DETOUR",
    "INJECT_FLOW",
    "INJECT_NODES",
    "ESCALATE",
    "TERMINATE",
    "EXTEND_GRAPH",
})

# Valid confidence levels
VALID_CONFIDENCE = frozenset({"HIGH", "MEDIUM", "LOW"})

# Valid injection statuses
VALID_INJECTION_STATUS = frozenset({
    "pending",
    "in_progress",
    "completed",
    "failed",
})

# Valid proposal statuses
VALID_PROPOSAL_STATUS = frozenset({
    "pending_review",
    "approved",
    "rejected",
    "implemented",
})


def _format_iso(dt: datetime) -> str:
    """Format datetime as ISO string with Z suffix."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")


def _now_iso() -> str:
    """Get current UTC time as ISO string."""
    return _format_iso(datetime.now(timezone.utc))


def _generate_id(prefix: str) -> str:
    """Generate a unique ID with prefix."""
    short_uuid = uuid.uuid4().hex[:8]
    return f"{prefix}-{short_uuid}"


@dataclass
class RoutingDecisionRecord:
    """A single routing decision for the audit trail.

    Required fields:
    - timestamp: When decision was made (ISO8601)
    - run_id: Run identifier
    - flow_key: Current flow
    - step_id: Current step
    - decision: CONTINUE, LOOP, DETOUR, INJECT_FLOW, INJECT_NODES, ESCALATE, TERMINATE
    - reason: Human-readable justification

    Optional fields for specific decision types.
    """

    timestamp: str
    run_id: str
    flow_key: str
    step_id: str
    decision: str  # CONTINUE, LOOP, DETOUR, INJECT_FLOW, INJECT_NODES, ESCALATE, TERMINATE
    reason: str
    agent_key: Optional[str] = None
    detour_target: Optional[str] = None
    injected_flow: Optional[str] = None
    injected_nodes: Optional[List[Dict[str, Any]]] = None
    forensic_summary: Optional[Dict[str, Any]] = None
    iteration: Optional[Dict[str, int]] = None
    signature_matched: Optional[str] = None
    confidence: str = "HIGH"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dict, omitting None values."""
        result: Dict[str, Any] = {
            "timestamp": self.timestamp,
            "run_id": self.run_id,
            "flow_key": self.flow_key,
            "step_id": self.step_id,
            "decision": self.decision,
            "reason": self.reason,
        }

        # Add optional fields if present
        if self.agent_key is not None:
            result["agent_key"] = self.agent_key
        if self.detour_target is not None:
            result["detour_target"] = self.detour_target
        if self.injected_flow is not None:
            result["injected_flow"] = self.injected_flow
        if self.injected_nodes is not None:
            result["injected_nodes"] = self.injected_nodes
        if self.forensic_summary is not None:
            result["forensic_summary"] = self.forensic_summary
        if self.iteration is not None:
            result["iteration"] = self.iteration
        if self.signature_matched is not None:
            result["signature_matched"] = self.signature_matched
        if self.confidence != "HIGH":  # Only include if not default
            result["confidence"] = self.confidence

        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RoutingDecisionRecord":
        """Create from dict (e.g., from JSONL line)."""
        return cls(
            timestamp=data["timestamp"],
            run_id=data["run_id"],
            flow_key=data["flow_key"],
            step_id=data["step_id"],
            decision=data["decision"],
            reason=data["reason"],
            agent_key=data.get("agent_key"),
            detour_target=data.get("detour_target"),
            injected_flow=data.get("injected_flow"),
            injected_nodes=data.get("injected_nodes"),
            forensic_summary=data.get("forensic_summary"),
            iteration=data.get("iteration"),
            signature_matched=data.get("signature_matched"),
            confidence=data.get("confidence", "HIGH"),
        )


@dataclass
class FlowInjectionRecord:
    """Record of a flow injection (e.g., Flow 8 rebase).

    When a flow injects another flow mid-execution, this record captures:
    - Where it was injected
    - What flow was injected
    - Why it was injected
    - Where to return after completion
    """

    injection_id: str
    timestamp: str
    injected_at: Dict[str, Any]  # flow_key, step_id, after_iteration
    injected_flow: str
    reason: str
    trigger: Dict[str, Any]
    return_to: Dict[str, Any]
    status: str = "in_progress"  # pending, in_progress, completed, failed
    completed_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dict."""
        result = {
            "injection_id": self.injection_id,
            "timestamp": self.timestamp,
            "injected_at": self.injected_at,
            "injected_flow": self.injected_flow,
            "reason": self.reason,
            "trigger": self.trigger,
            "return_to": self.return_to,
            "status": self.status,
        }
        if self.completed_at is not None:
            result["completed_at"] = self.completed_at
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FlowInjectionRecord":
        """Create from dict."""
        return cls(
            injection_id=data["injection_id"],
            timestamp=data["timestamp"],
            injected_at=data["injected_at"],
            injected_flow=data["injected_flow"],
            reason=data["reason"],
            trigger=data["trigger"],
            return_to=data["return_to"],
            status=data.get("status", "in_progress"),
            completed_at=data.get("completed_at"),
        )


@dataclass
class NodeInjectionRecord:
    """Record of ad-hoc node injection.

    When novel requirements require injecting steps not in the flow graph,
    this record captures what nodes were added and why.
    """

    injection_id: str
    timestamp: str
    injected_at: Dict[str, Any]  # flow_key, step_id
    nodes: List[Dict[str, Any]]  # List of node specs
    reason: str
    goal_alignment: str  # How this helps achieve the flow's objective
    status: str = "pending"  # pending, in_progress, completed, failed

    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "injection_id": self.injection_id,
            "timestamp": self.timestamp,
            "injected_at": self.injected_at,
            "nodes": self.nodes,
            "reason": self.reason,
            "goal_alignment": self.goal_alignment,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "NodeInjectionRecord":
        """Create from dict."""
        return cls(
            injection_id=data["injection_id"],
            timestamp=data["timestamp"],
            injected_at=data["injected_at"],
            nodes=data["nodes"],
            reason=data["reason"],
            goal_alignment=data["goal_alignment"],
            status=data.get("status", "pending"),
        )


@dataclass
class GraphExtensionProposal:
    """Proposal to extend the flow graph (from Wisdom).

    When Wisdom analyzes patterns across runs and identifies improvements,
    it proposes graph extensions rather than implementing them directly.
    Human review is required before proposals become permanent changes.
    """

    proposal_id: str
    timestamp: str
    proposed_by: str
    pattern_observed: Dict[str, Any]
    proposed_change: Dict[str, Any]
    rationale: str
    status: str = "pending_review"  # pending_review, approved, rejected, implemented
    reviewed_by: Optional[str] = None
    decision: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dict."""
        result = {
            "proposal_id": self.proposal_id,
            "timestamp": self.timestamp,
            "proposed_by": self.proposed_by,
            "pattern_observed": self.pattern_observed,
            "proposed_change": self.proposed_change,
            "rationale": self.rationale,
            "status": self.status,
        }
        if self.reviewed_by is not None:
            result["reviewed_by"] = self.reviewed_by
        if self.decision is not None:
            result["decision"] = self.decision
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GraphExtensionProposal":
        """Create from dict."""
        return cls(
            proposal_id=data["proposal_id"],
            timestamp=data["timestamp"],
            proposed_by=data["proposed_by"],
            pattern_observed=data["pattern_observed"],
            proposed_change=data["proposed_change"],
            rationale=data["rationale"],
            status=data.get("status", "pending_review"),
            reviewed_by=data.get("reviewed_by"),
            decision=data.get("decision"),
        )


class RoutingAuditTrail:
    """Manager for routing audit trail artifacts.

    Handles:
    - Append-only decision log (JSONL)
    - Flow injection records (JSON)
    - Node injection records (JSON)
    - Graph extension proposals (JSON)

    Usage:
        trail = RoutingAuditTrail(run_base, "build")
        trail.log_decision(decision_record)
        trail.log_flow_injection(injection_record)

        # Query
        decisions = trail.get_decisions()
        off_road_count = trail.get_off_road_count()
    """

    def __init__(self, run_base: Path, flow_key: str):
        """Initialize the audit trail manager.

        Args:
            run_base: The run base directory (e.g., swarm/runs/<run_id>)
            flow_key: The flow key (e.g., "build", "signal")
        """
        self.run_base = Path(run_base)
        self.flow_key = flow_key
        self.routing_dir = self.run_base / flow_key / ROUTING_DIR
        self.injections_dir = self.routing_dir / INJECTIONS_DIR
        self.proposals_dir = self.routing_dir / PROPOSALS_DIR
        self.decisions_file = self.routing_dir / DECISIONS_FILE

    def _ensure_routing_dir(self) -> Path:
        """Ensure routing/ directory exists."""
        self.routing_dir.mkdir(parents=True, exist_ok=True)
        return self.routing_dir

    def _ensure_injections_dir(self) -> Path:
        """Ensure routing/injections/ directory exists."""
        self._ensure_routing_dir()
        self.injections_dir.mkdir(parents=True, exist_ok=True)
        return self.injections_dir

    def _ensure_proposals_dir(self) -> Path:
        """Ensure routing/proposals/ directory exists."""
        self._ensure_routing_dir()
        self.proposals_dir.mkdir(parents=True, exist_ok=True)
        return self.proposals_dir

    def log_decision(self, record: RoutingDecisionRecord) -> None:
        """Append a routing decision to decisions.jsonl.

        Following the logging rules:
        - CONTINUE decisions are typically not logged (golden path is implicit)
        - All other decisions are logged for audit

        Args:
            record: The routing decision to log
        """
        self._ensure_routing_dir()

        record_dict = record.to_dict()
        line = json.dumps(record_dict, separators=(",", ":"))

        with self.decisions_file.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

        logger.debug(
            "Logged routing decision: %s for %s/%s",
            record.decision,
            record.flow_key,
            record.step_id,
        )

    def log_flow_injection(self, record: FlowInjectionRecord) -> Path:
        """Write a flow injection record.

        Args:
            record: The flow injection to log

        Returns:
            Path to the written injection file
        """
        self._ensure_injections_dir()

        filename = f"flow-{record.injection_id}.json"
        filepath = self.injections_dir / filename

        with filepath.open("w", encoding="utf-8") as f:
            json.dump(record.to_dict(), f, indent=2)

        logger.debug(
            "Logged flow injection: %s -> %s",
            record.injection_id,
            record.injected_flow,
        )

        return filepath

    def log_node_injection(self, record: NodeInjectionRecord) -> Path:
        """Write a node injection record.

        Args:
            record: The node injection to log

        Returns:
            Path to the written injection file
        """
        self._ensure_injections_dir()

        filename = f"nodes-{record.injection_id}.json"
        filepath = self.injections_dir / filename

        with filepath.open("w", encoding="utf-8") as f:
            json.dump(record.to_dict(), f, indent=2)

        logger.debug(
            "Logged node injection: %s with %d nodes",
            record.injection_id,
            len(record.nodes),
        )

        return filepath

    def log_proposal(self, proposal: GraphExtensionProposal) -> Path:
        """Write a graph extension proposal.

        Args:
            proposal: The proposal to log

        Returns:
            Path to the written proposal file
        """
        self._ensure_proposals_dir()

        filename = f"extend-{proposal.proposal_id}.json"
        filepath = self.proposals_dir / filename

        with filepath.open("w", encoding="utf-8") as f:
            json.dump(proposal.to_dict(), f, indent=2)

        logger.debug(
            "Logged graph extension proposal: %s by %s",
            proposal.proposal_id,
            proposal.proposed_by,
        )

        return filepath

    def get_decisions(self) -> List[RoutingDecisionRecord]:
        """Read all decisions from JSONL.

        Returns:
            List of RoutingDecisionRecord objects, in order logged.
            Returns empty list if no decisions file exists.
        """
        if not self.decisions_file.exists():
            return []

        decisions: List[RoutingDecisionRecord] = []

        with self.decisions_file.open("r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    decisions.append(RoutingDecisionRecord.from_dict(data))
                except json.JSONDecodeError as e:
                    logger.warning(
                        "Invalid JSON at line %d in %s: %s",
                        line_num,
                        self.decisions_file,
                        e,
                    )

        return decisions

    def get_off_road_count(self) -> int:
        """Count non-CONTINUE decisions.

        Returns:
            Number of off-road (non-CONTINUE) decisions logged.
        """
        decisions = self.get_decisions()
        return sum(1 for d in decisions if d.decision != "CONTINUE")

    def get_decisions_by_type(self, decision_type: str) -> List[RoutingDecisionRecord]:
        """Get all decisions of a specific type.

        Args:
            decision_type: The decision type to filter by (e.g., "DETOUR", "LOOP")

        Returns:
            List of matching decisions.
        """
        decisions = self.get_decisions()
        return [d for d in decisions if d.decision == decision_type]

    def get_flow_injections(self) -> List[FlowInjectionRecord]:
        """Get all flow injection records.

        Returns:
            List of FlowInjectionRecord objects.
        """
        if not self.injections_dir.exists():
            return []

        injections: List[FlowInjectionRecord] = []

        for filepath in sorted(self.injections_dir.glob("flow-*.json")):
            try:
                with filepath.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                injections.append(FlowInjectionRecord.from_dict(data))
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("Could not read injection file %s: %s", filepath, e)

        return injections

    def get_node_injections(self) -> List[NodeInjectionRecord]:
        """Get all node injection records.

        Returns:
            List of NodeInjectionRecord objects.
        """
        if not self.injections_dir.exists():
            return []

        injections: List[NodeInjectionRecord] = []

        for filepath in sorted(self.injections_dir.glob("nodes-*.json")):
            try:
                with filepath.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                injections.append(NodeInjectionRecord.from_dict(data))
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("Could not read injection file %s: %s", filepath, e)

        return injections

    def get_proposals(self) -> List[GraphExtensionProposal]:
        """Get all graph extension proposals.

        Returns:
            List of GraphExtensionProposal objects.
        """
        if not self.proposals_dir.exists():
            return []

        proposals: List[GraphExtensionProposal] = []

        for filepath in sorted(self.proposals_dir.glob("extend-*.json")):
            try:
                with filepath.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                proposals.append(GraphExtensionProposal.from_dict(data))
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("Could not read proposal file %s: %s", filepath, e)

        return proposals

    def update_flow_injection_status(
        self,
        injection_id: str,
        status: str,
        completed_at: Optional[str] = None,
    ) -> bool:
        """Update the status of a flow injection.

        Args:
            injection_id: The injection ID to update
            status: New status (pending, in_progress, completed, failed)
            completed_at: Completion timestamp (set automatically if status is completed)

        Returns:
            True if update succeeded, False if injection not found.
        """
        filepath = self.injections_dir / f"flow-{injection_id}.json"
        if not filepath.exists():
            logger.warning("Flow injection not found: %s", injection_id)
            return False

        try:
            with filepath.open("r", encoding="utf-8") as f:
                data = json.load(f)

            data["status"] = status
            if status == "completed" and completed_at is None:
                data["completed_at"] = _now_iso()
            elif completed_at is not None:
                data["completed_at"] = completed_at

            with filepath.open("w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)

            return True

        except (json.JSONDecodeError, OSError) as e:
            logger.error("Could not update injection %s: %s", injection_id, e)
            return False

    def update_proposal_status(
        self,
        proposal_id: str,
        status: str,
        reviewed_by: Optional[str] = None,
        decision: Optional[str] = None,
    ) -> bool:
        """Update the status of a graph extension proposal.

        Args:
            proposal_id: The proposal ID to update
            status: New status (pending_review, approved, rejected, implemented)
            reviewed_by: Who reviewed the proposal
            decision: Decision rationale

        Returns:
            True if update succeeded, False if proposal not found.
        """
        filepath = self.proposals_dir / f"extend-{proposal_id}.json"
        if not filepath.exists():
            logger.warning("Proposal not found: %s", proposal_id)
            return False

        try:
            with filepath.open("r", encoding="utf-8") as f:
                data = json.load(f)

            data["status"] = status
            if reviewed_by is not None:
                data["reviewed_by"] = reviewed_by
            if decision is not None:
                data["decision"] = decision

            with filepath.open("w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)

            return True

        except (json.JSONDecodeError, OSError) as e:
            logger.error("Could not update proposal %s: %s", proposal_id, e)
            return False


# Factory functions for creating records


def create_routing_decision(
    run_id: str,
    flow_key: str,
    step_id: str,
    decision: str,
    reason: str,
    *,
    agent_key: Optional[str] = None,
    detour_target: Optional[str] = None,
    injected_flow: Optional[str] = None,
    injected_nodes: Optional[List[Dict[str, Any]]] = None,
    forensic_summary: Optional[Dict[str, Any]] = None,
    iteration: Optional[Dict[str, int]] = None,
    signature_matched: Optional[str] = None,
    confidence: str = "HIGH",
    timestamp: Optional[str] = None,
) -> RoutingDecisionRecord:
    """Factory function for creating routing decision records.

    Args:
        run_id: Run identifier
        flow_key: Current flow key
        step_id: Current step ID
        decision: Routing decision (CONTINUE, LOOP, DETOUR, etc.)
        reason: Human-readable justification
        agent_key: Agent that completed the step (optional)
        detour_target: Target for DETOUR decisions (optional)
        injected_flow: Flow key for INJECT_FLOW decisions (optional)
        injected_nodes: Node specs for INJECT_NODES decisions (optional)
        forensic_summary: Compact forensics that informed decision (optional)
        iteration: Microloop state (optional)
        signature_matched: Known failure signature if matched (optional)
        confidence: Confidence level (HIGH, MEDIUM, LOW)
        timestamp: ISO timestamp (defaults to now)

    Returns:
        RoutingDecisionRecord ready to be logged.

    Raises:
        ValueError: If decision or confidence is invalid.
    """
    if decision not in VALID_DECISIONS:
        raise ValueError(
            f"Invalid decision '{decision}'. "
            f"Valid values: {sorted(VALID_DECISIONS)}"
        )
    if confidence not in VALID_CONFIDENCE:
        raise ValueError(
            f"Invalid confidence '{confidence}'. "
            f"Valid values: {sorted(VALID_CONFIDENCE)}"
        )

    return RoutingDecisionRecord(
        timestamp=timestamp or _now_iso(),
        run_id=run_id,
        flow_key=flow_key,
        step_id=step_id,
        decision=decision,
        reason=reason,
        agent_key=agent_key,
        detour_target=detour_target,
        injected_flow=injected_flow,
        injected_nodes=injected_nodes,
        forensic_summary=forensic_summary,
        iteration=iteration,
        signature_matched=signature_matched,
        confidence=confidence,
    )


def create_flow_injection(
    injected_flow: str,
    reason: str,
    trigger: Dict[str, Any],
    injected_at_flow: str,
    injected_at_step: str,
    return_to_flow: str,
    return_to_step: str,
    *,
    after_iteration: Optional[int] = None,
    injection_id: Optional[str] = None,
    timestamp: Optional[str] = None,
) -> FlowInjectionRecord:
    """Factory function for creating flow injection records.

    Args:
        injected_flow: The flow being injected (e.g., "reset")
        reason: Why the flow is being injected
        trigger: What triggered the injection (type, details)
        injected_at_flow: Flow where injection occurred
        injected_at_step: Step where injection occurred
        return_to_flow: Flow to return to after injection
        return_to_step: Step to return to after injection
        after_iteration: Iteration count when injected (optional)
        injection_id: Custom ID (auto-generated if not provided)
        timestamp: ISO timestamp (defaults to now)

    Returns:
        FlowInjectionRecord ready to be logged.
    """
    injected_at: Dict[str, Any] = {
        "flow_key": injected_at_flow,
        "step_id": injected_at_step,
    }
    if after_iteration is not None:
        injected_at["after_iteration"] = after_iteration

    return FlowInjectionRecord(
        injection_id=injection_id or _generate_id("inject"),
        timestamp=timestamp or _now_iso(),
        injected_at=injected_at,
        injected_flow=injected_flow,
        reason=reason,
        trigger=trigger,
        return_to={
            "flow_key": return_to_flow,
            "step_id": return_to_step,
        },
        status="in_progress",
    )


def create_node_injection(
    nodes: List[Dict[str, Any]],
    reason: str,
    goal_alignment: str,
    injected_at_flow: str,
    injected_at_step: str,
    *,
    injection_id: Optional[str] = None,
    timestamp: Optional[str] = None,
) -> NodeInjectionRecord:
    """Factory function for creating node injection records.

    Args:
        nodes: List of node specs (id, agent, purpose, inputs, outputs)
        reason: Why the nodes are being injected
        goal_alignment: How this helps achieve the flow's objective
        injected_at_flow: Flow where injection occurred
        injected_at_step: Step where injection occurred
        injection_id: Custom ID (auto-generated if not provided)
        timestamp: ISO timestamp (defaults to now)

    Returns:
        NodeInjectionRecord ready to be logged.
    """
    return NodeInjectionRecord(
        injection_id=injection_id or _generate_id("nodes"),
        timestamp=timestamp or _now_iso(),
        injected_at={
            "flow_key": injected_at_flow,
            "step_id": injected_at_step,
        },
        nodes=nodes,
        reason=reason,
        goal_alignment=goal_alignment,
        status="pending",
    )


def create_graph_extension_proposal(
    proposed_by: str,
    pattern_observed: Dict[str, Any],
    proposed_change: Dict[str, Any],
    rationale: str,
    *,
    proposal_id: Optional[str] = None,
    timestamp: Optional[str] = None,
) -> GraphExtensionProposal:
    """Factory function for creating graph extension proposals.

    Args:
        proposed_by: Agent that proposed the change
        pattern_observed: Pattern that led to proposal (description, frequency, evidence)
        proposed_change: What change is proposed (type, flow, new_step, etc.)
        rationale: Why this change would help
        proposal_id: Custom ID (auto-generated if not provided)
        timestamp: ISO timestamp (defaults to now)

    Returns:
        GraphExtensionProposal ready to be logged.
    """
    return GraphExtensionProposal(
        proposal_id=proposal_id or _generate_id("extend"),
        timestamp=timestamp or _now_iso(),
        proposed_by=proposed_by,
        pattern_observed=pattern_observed,
        proposed_change=proposed_change,
        rationale=rationale,
        status="pending_review",
    )


# Convenience functions


def log_off_road_decision(
    run_base: Path,
    flow_key: str,
    run_id: str,
    step_id: str,
    decision: str,
    reason: str,
    **kwargs: Any,
) -> None:
    """Convenience function to log an off-road decision.

    This is the most common entry point for logging routing decisions.
    Skips CONTINUE decisions (golden path is implicit).

    Args:
        run_base: The run base directory
        flow_key: Current flow key
        run_id: Run identifier
        step_id: Current step ID
        decision: Routing decision
        reason: Human-readable justification
        **kwargs: Additional fields for RoutingDecisionRecord
    """
    if decision == "CONTINUE":
        logger.debug("Skipping CONTINUE decision (golden path)")
        return

    trail = RoutingAuditTrail(run_base, flow_key)
    record = create_routing_decision(
        run_id=run_id,
        flow_key=flow_key,
        step_id=step_id,
        decision=decision,
        reason=reason,
        **kwargs,
    )
    trail.log_decision(record)


__all__ = [
    # Data classes
    "RoutingDecisionRecord",
    "FlowInjectionRecord",
    "NodeInjectionRecord",
    "GraphExtensionProposal",
    # Main class
    "RoutingAuditTrail",
    # Factory functions
    "create_routing_decision",
    "create_flow_injection",
    "create_node_injection",
    "create_graph_extension_proposal",
    # Convenience functions
    "log_off_road_decision",
    # Constants
    "VALID_DECISIONS",
    "VALID_CONFIDENCE",
]
