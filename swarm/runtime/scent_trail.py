"""
Scent Trail: Decision Provenance System

The scent trail maintains a compact summary of:
- Key decisions made across flows
- Why they were made
- What alternatives were rejected
- What assumptions are in effect

This prevents re-litigation of settled decisions and provides
context for "how we got here" to downstream steps.

File Placement:
    Scent trails are written to: RUN_BASE/scent_trail.json
    Updated after each step that makes decisions.

The Rule:
    Every step receives and updates the scent trail.
    Prior decisions are respected unless explicitly revisited.
    Conflicts are flagged, not silently overridden.

Economics:
    - Storage: ~1-2KB per run
    - Context: ~500-1000 tokens per step
    - Saves: 5-10x tokens by avoiding re-litigation
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# =============================================================================
# Core Data Classes
# =============================================================================


@dataclass
class DecisionRecord:
    """A single decision recorded in the scent trail.

    Decisions are non-trivial choices that affect flow direction:
    - Architectural decisions
    - Technology choices
    - Approach selection
    - Assumption adoption

    Do NOT record trivial choices like variable naming or formatting.

    Attributes:
        step_id: Step where decision was made (e.g., "signal-step-2").
        flow_key: Flow where decision was made (e.g., "signal", "plan").
        decision: What was decided.
        rationale: Why this decision was made.
        alternatives_rejected: What options were not chosen.
        confidence: Confidence level (HIGH, MEDIUM, LOW).
        timestamp: When decision was recorded (ISO 8601).
    """

    step_id: str
    flow_key: str
    decision: str
    rationale: str
    alternatives_rejected: List[str] = field(default_factory=list)
    confidence: str = "MEDIUM"  # HIGH, MEDIUM, LOW
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat() + "Z")

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "step": self.step_id,
            "flow_key": self.flow_key,
            "decision": self.decision,
            "rationale": self.rationale,
            "alternatives_rejected": list(self.alternatives_rejected),
            "confidence": self.confidence,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DecisionRecord":
        """Deserialize from dictionary."""
        return cls(
            step_id=data.get("step", data.get("step_id", "")),
            flow_key=data.get("flow_key", ""),
            decision=data.get("decision", ""),
            rationale=data.get("rationale", ""),
            alternatives_rejected=list(data.get("alternatives_rejected", [])),
            confidence=data.get("confidence", "MEDIUM"),
            timestamp=data.get("timestamp", datetime.now(timezone.utc).isoformat() + "Z"),
        )


@dataclass
class ActiveAssumption:
    """An assumption currently in effect.

    Assumptions are made when agents face ambiguity and proceed
    with their best interpretation. Tracking them enables:
    - Downstream steps to respect the assumption
    - Validation when more information arrives
    - Clear impact assessment if assumption is wrong

    Attributes:
        assumption: The assumption statement.
        made_at: Step ID where assumption was made.
        impact_if_wrong: What would need to change if wrong.
        status: Current status (ACTIVE, VALIDATED, INVALIDATED).
        invalidation_reason: Why assumption was invalidated (if applicable).
        validated_at: Step where assumption was validated (if applicable).
    """

    assumption: str
    made_at: str  # step_id where assumption was made
    impact_if_wrong: str
    status: str = "ACTIVE"  # ACTIVE, VALIDATED, INVALIDATED
    invalidation_reason: Optional[str] = None
    validated_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        result: Dict[str, Any] = {
            "assumption": self.assumption,
            "made_at": self.made_at,
            "impact_if_wrong": self.impact_if_wrong,
            "status": self.status,
        }
        if self.invalidation_reason:
            result["invalidation_reason"] = self.invalidation_reason
        if self.validated_at:
            result["validated_at"] = self.validated_at
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ActiveAssumption":
        """Deserialize from dictionary."""
        return cls(
            assumption=data.get("assumption", ""),
            made_at=data.get("made_at", ""),
            impact_if_wrong=data.get("impact_if_wrong", ""),
            status=data.get("status", "ACTIVE"),
            invalidation_reason=data.get("invalidation_reason"),
            validated_at=data.get("validated_at"),
        )


@dataclass
class ConflictRecord:
    """A conflict between current analysis and a prior decision.

    When current findings contradict prior decisions, the conflict
    is recorded rather than silently overriding. This enables:
    - Explicit escalation decisions
    - Audit trail of conflicts
    - Clear impact assessment

    Attributes:
        prior_decision: The decision that is in conflict.
        current_finding: What was found that conflicts.
        recommendation: What to do about the conflict.
        impact: Impact of the conflict.
        detected_at: Step where conflict was detected.
        resolved: Whether conflict has been resolved.
        resolution: How conflict was resolved (if applicable).
    """

    prior_decision: str
    current_finding: str
    recommendation: str
    impact: str
    detected_at: str
    resolved: bool = False
    resolution: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        result: Dict[str, Any] = {
            "prior_decision": self.prior_decision,
            "current_finding": self.current_finding,
            "recommendation": self.recommendation,
            "impact": self.impact,
            "detected_at": self.detected_at,
            "resolved": self.resolved,
        }
        if self.resolution:
            result["resolution"] = self.resolution
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ConflictRecord":
        """Deserialize from dictionary."""
        return cls(
            prior_decision=data.get("prior_decision", ""),
            current_finding=data.get("current_finding", ""),
            recommendation=data.get("recommendation", ""),
            impact=data.get("impact", ""),
            detected_at=data.get("detected_at", ""),
            resolved=data.get("resolved", False),
            resolution=data.get("resolution"),
        )


@dataclass
class ScentTrail:
    """Complete scent trail for a run.

    The scent trail is the decision provenance log for an entire run.
    It answers "how did we get here?" for any downstream step.

    Attributes:
        run_id: Unique identifier for the run.
        flow_objective: High-level objective of the current flow/run.
        decisions: List of decisions made across all steps.
        assumptions_in_effect: List of active assumptions.
        open_questions: List of unresolved questions.
        conflicts: List of detected conflicts with prior decisions.
        last_updated: When the trail was last updated.
    """

    run_id: str
    flow_objective: str
    decisions: List[DecisionRecord] = field(default_factory=list)
    assumptions_in_effect: List[ActiveAssumption] = field(default_factory=list)
    open_questions: List[str] = field(default_factory=list)
    conflicts: List[ConflictRecord] = field(default_factory=list)
    last_updated: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat() + "Z")

    def add_decision(
        self,
        step_id: str,
        flow_key: str,
        decision: str,
        rationale: str,
        alternatives: Optional[List[str]] = None,
        confidence: str = "MEDIUM",
    ) -> DecisionRecord:
        """Add a decision to the trail.

        Args:
            step_id: Step where decision was made.
            flow_key: Flow where decision was made.
            decision: What was decided.
            rationale: Why this decision was made.
            alternatives: What options were rejected.
            confidence: Confidence level (HIGH, MEDIUM, LOW).

        Returns:
            The created DecisionRecord.
        """
        record = DecisionRecord(
            step_id=step_id,
            flow_key=flow_key,
            decision=decision,
            rationale=rationale,
            alternatives_rejected=alternatives or [],
            confidence=confidence,
        )
        self.decisions.append(record)
        self._update_timestamp()
        logger.debug("Added decision to scent trail: %s (step=%s)", decision[:50], step_id)
        return record

    def add_assumption(
        self,
        assumption: str,
        made_at: str,
        impact_if_wrong: str,
    ) -> ActiveAssumption:
        """Add an assumption to the trail.

        Args:
            assumption: The assumption statement.
            made_at: Step ID where assumption was made.
            impact_if_wrong: What would change if assumption is incorrect.

        Returns:
            The created ActiveAssumption.
        """
        record = ActiveAssumption(
            assumption=assumption,
            made_at=made_at,
            impact_if_wrong=impact_if_wrong,
        )
        self.assumptions_in_effect.append(record)
        self._update_timestamp()
        logger.debug("Added assumption to scent trail: %s (made_at=%s)", assumption[:50], made_at)
        return record

    def validate_assumption(self, assumption: str, validated_at: str) -> bool:
        """Mark an assumption as validated.

        Args:
            assumption: The assumption text to find.
            validated_at: Step where validation occurred.

        Returns:
            True if assumption was found and updated, False otherwise.
        """
        for record in self.assumptions_in_effect:
            if record.assumption == assumption and record.status == "ACTIVE":
                record.status = "VALIDATED"
                record.validated_at = validated_at
                self._update_timestamp()
                logger.debug("Validated assumption: %s", assumption[:50])
                return True
        logger.warning("Assumption not found for validation: %s", assumption[:50])
        return False

    def invalidate_assumption(self, assumption: str, reason: str) -> bool:
        """Mark an assumption as invalidated.

        Args:
            assumption: The assumption text to find.
            reason: Why the assumption was invalidated.

        Returns:
            True if assumption was found and updated, False otherwise.
        """
        for record in self.assumptions_in_effect:
            if record.assumption == assumption and record.status == "ACTIVE":
                record.status = "INVALIDATED"
                record.invalidation_reason = reason
                self._update_timestamp()
                logger.debug("Invalidated assumption: %s (reason=%s)", assumption[:50], reason[:50])
                return True
        logger.warning("Assumption not found for invalidation: %s", assumption[:50])
        return False

    def add_open_question(self, question: str) -> None:
        """Add an open question.

        Args:
            question: The unresolved question.
        """
        if question not in self.open_questions:
            self.open_questions.append(question)
            self._update_timestamp()
            logger.debug("Added open question: %s", question[:50])

    def resolve_open_question(self, question: str) -> bool:
        """Remove an open question (when resolved).

        Args:
            question: The question to remove.

        Returns:
            True if question was found and removed, False otherwise.
        """
        if question in self.open_questions:
            self.open_questions.remove(question)
            self._update_timestamp()
            logger.debug("Resolved open question: %s", question[:50])
            return True
        return False

    def add_conflict(
        self,
        prior_decision: str,
        current_finding: str,
        recommendation: str,
        impact: str,
        detected_at: str,
    ) -> ConflictRecord:
        """Record a conflict with a prior decision.

        When current analysis conflicts with a prior decision, this
        documents the conflict for escalation rather than silently
        overriding.

        Args:
            prior_decision: The decision that is in conflict.
            current_finding: What was found that conflicts.
            recommendation: What to do about the conflict.
            impact: Impact of the conflict.
            detected_at: Step where conflict was detected.

        Returns:
            The created ConflictRecord.
        """
        record = ConflictRecord(
            prior_decision=prior_decision,
            current_finding=current_finding,
            recommendation=recommendation,
            impact=impact,
            detected_at=detected_at,
        )
        self.conflicts.append(record)
        self._update_timestamp()
        logger.warning(
            "Conflict detected with prior decision: %s vs %s",
            prior_decision[:30],
            current_finding[:30],
        )
        return record

    def resolve_conflict(self, prior_decision: str, resolution: str) -> bool:
        """Mark a conflict as resolved.

        Args:
            prior_decision: The prior decision to find.
            resolution: How the conflict was resolved.

        Returns:
            True if conflict was found and resolved, False otherwise.
        """
        for record in self.conflicts:
            if record.prior_decision == prior_decision and not record.resolved:
                record.resolved = True
                record.resolution = resolution
                self._update_timestamp()
                logger.debug("Resolved conflict: %s", prior_decision[:50])
                return True
        return False

    def check_for_conflicts(self, new_decision: str) -> List[ConflictRecord]:
        """Check if a new decision conflicts with existing decisions.

        This is a simple text-based check. For more sophisticated
        conflict detection, consider using semantic similarity.

        Args:
            new_decision: The decision text to check.

        Returns:
            List of potential conflicts (empty if none found).
        """
        potential_conflicts: List[ConflictRecord] = []

        # Simple keyword-based conflict detection
        new_words = set(new_decision.lower().split())
        negation_words = {"not", "no", "don't", "won't", "instead", "rather", "reject"}

        for existing in self.decisions:
            existing_words = set(existing.decision.lower().split())

            # Check for overlapping topics with negation
            overlap = new_words & existing_words
            if overlap and (new_words & negation_words or existing_words & negation_words):
                # Potential conflict - topics overlap but one has negation
                logger.debug(
                    "Potential conflict detected between '%s' and '%s'",
                    new_decision[:30],
                    existing.decision[:30],
                )
                # Don't create a conflict record yet - caller should review and decide

        return potential_conflicts

    def get_active_assumptions(self) -> List[ActiveAssumption]:
        """Get all assumptions that are currently active.

        Returns:
            List of assumptions with status ACTIVE.
        """
        return [a for a in self.assumptions_in_effect if a.status == "ACTIVE"]

    def get_decisions_by_flow(self, flow_key: str) -> List[DecisionRecord]:
        """Get all decisions made in a specific flow.

        Args:
            flow_key: The flow to filter by.

        Returns:
            List of decisions from that flow.
        """
        return [d for d in self.decisions if d.flow_key == flow_key]

    def get_unresolved_conflicts(self) -> List[ConflictRecord]:
        """Get all conflicts that have not been resolved.

        Returns:
            List of unresolved conflicts.
        """
        return [c for c in self.conflicts if not c.resolved]

    def _update_timestamp(self) -> None:
        """Update the last_updated timestamp."""
        self.last_updated = datetime.now(timezone.utc).isoformat() + "Z"

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary.

        Returns:
            Dictionary representation suitable for JSON serialization.
        """
        return {
            "scent_trail": {
                "run_id": self.run_id,
                "flow_objective": self.flow_objective,
                "decisions": [d.to_dict() for d in self.decisions],
                "assumptions_in_effect": [a.to_dict() for a in self.assumptions_in_effect],
                "open_questions": list(self.open_questions),
                "conflicts": [c.to_dict() for c in self.conflicts],
                "last_updated": self.last_updated,
            }
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ScentTrail":
        """Deserialize from dictionary.

        Args:
            data: Dictionary with scent trail data.
                  Accepts both wrapped ({"scent_trail": {...}}) and unwrapped formats.

        Returns:
            ScentTrail instance.
        """
        # Handle both wrapped and unwrapped formats
        if "scent_trail" in data:
            data = data["scent_trail"]

        return cls(
            run_id=data.get("run_id", ""),
            flow_objective=data.get("flow_objective", ""),
            decisions=[DecisionRecord.from_dict(d) for d in data.get("decisions", [])],
            assumptions_in_effect=[
                ActiveAssumption.from_dict(a) for a in data.get("assumptions_in_effect", [])
            ],
            open_questions=list(data.get("open_questions", [])),
            conflicts=[ConflictRecord.from_dict(c) for c in data.get("conflicts", [])],
            last_updated=data.get("last_updated", datetime.now(timezone.utc).isoformat() + "Z"),
        )

    def to_markdown(self) -> str:
        """Generate a markdown summary for inclusion in context packs.

        Returns:
            Markdown-formatted summary of the scent trail.
        """
        lines = [
            "# Scent Trail: Decision Provenance",
            "",
            f"**Run ID:** {self.run_id}",
            f"**Objective:** {self.flow_objective}",
            f"**Last Updated:** {self.last_updated}",
            "",
        ]

        # Decisions
        if self.decisions:
            lines.append("## Key Decisions")
            lines.append("")
            for i, d in enumerate(self.decisions, 1):
                lines.append(f"### {i}. {d.decision}")
                lines.append(f"- **Step:** {d.step_id} ({d.flow_key})")
                lines.append(f"- **Rationale:** {d.rationale}")
                if d.alternatives_rejected:
                    lines.append(f"- **Rejected:** {', '.join(d.alternatives_rejected)}")
                lines.append(f"- **Confidence:** {d.confidence}")
                lines.append("")

        # Assumptions
        active_assumptions = self.get_active_assumptions()
        if active_assumptions:
            lines.append("## Active Assumptions")
            lines.append("")
            for a in active_assumptions:
                lines.append(f"- **{a.assumption}**")
                lines.append(f"  - Made at: {a.made_at}")
                lines.append(f"  - Impact if wrong: {a.impact_if_wrong}")
                lines.append("")

        # Open Questions
        if self.open_questions:
            lines.append("## Open Questions")
            lines.append("")
            for q in self.open_questions:
                lines.append(f"- {q}")
            lines.append("")

        # Conflicts
        unresolved = self.get_unresolved_conflicts()
        if unresolved:
            lines.append("## Unresolved Conflicts")
            lines.append("")
            for c in unresolved:
                lines.append(f"### {c.prior_decision}")
                lines.append(f"- **Finding:** {c.current_finding}")
                lines.append(f"- **Impact:** {c.impact}")
                lines.append(f"- **Recommendation:** {c.recommendation}")
                lines.append(f"- **Detected at:** {c.detected_at}")
                lines.append("")

        return "\n".join(lines)


# =============================================================================
# Builder Class
# =============================================================================


class ScentTrailBuilder:
    """Builder for constructing and updating scent trails.

    Provides convenience methods for loading, updating, and saving
    scent trails within a run.
    """

    def __init__(self, run_base: Path):
        """Initialize the builder.

        Args:
            run_base: Path to RUN_BASE directory.
        """
        self.run_base = Path(run_base)
        self._trail: Optional[ScentTrail] = None

    @property
    def trail(self) -> Optional[ScentTrail]:
        """Get the current trail (may be None if not loaded)."""
        return self._trail

    def load_or_create(self, run_id: str, flow_objective: str) -> ScentTrail:
        """Load existing trail or create new one.

        Args:
            run_id: Unique identifier for the run.
            flow_objective: High-level objective (used if creating new).

        Returns:
            Loaded or newly created ScentTrail.
        """
        trail = load_scent_trail(self.run_base)
        if trail is not None:
            self._trail = trail
            # Update objective if provided and different
            if flow_objective and trail.flow_objective != flow_objective:
                logger.debug(
                    "Updating flow objective from '%s' to '%s'",
                    trail.flow_objective,
                    flow_objective,
                )
                trail.flow_objective = flow_objective
        else:
            self._trail = ScentTrail(
                run_id=run_id,
                flow_objective=flow_objective,
            )
            logger.debug("Created new scent trail for run %s", run_id)
        return self._trail

    def save(self) -> Path:
        """Save trail to disk.

        Returns:
            Path where trail was saved.

        Raises:
            ValueError: If no trail has been loaded or created.
        """
        if self._trail is None:
            raise ValueError("No trail loaded. Call load_or_create first.")
        return save_scent_trail(self._trail, self.run_base)

    def extract_from_envelope(self, envelope: Dict[str, Any]) -> None:
        """Extract decisions and assumptions from a handoff envelope.

        Parses a handoff envelope and extracts any decisions or assumptions
        recorded in it, adding them to the current scent trail.

        Args:
            envelope: Handoff envelope dictionary.

        Raises:
            ValueError: If no trail has been loaded or created.
        """
        if self._trail is None:
            raise ValueError("No trail loaded. Call load_or_create first.")

        step_id = envelope.get("step_id", envelope.get("meta", {}).get("step_id", "unknown"))
        flow_key = envelope.get("flow_key", envelope.get("meta", {}).get("flow_key", "unknown"))

        # Extract assumptions from envelope
        assumptions = envelope.get("assumptions_made", envelope.get("assumptions", []))
        for assumption_data in assumptions:
            if isinstance(assumption_data, dict):
                # Handle structured assumption format
                statement = assumption_data.get(
                    "statement", assumption_data.get("assumption", "")
                )
                impact = assumption_data.get("impact_if_wrong", "Unknown impact")
                made_at = assumption_data.get("step_introduced", step_id)

                if statement:
                    # Check if assumption already exists
                    existing = [
                        a for a in self._trail.assumptions_in_effect if a.assumption == statement
                    ]
                    if not existing:
                        self._trail.add_assumption(statement, made_at, impact)
            elif isinstance(assumption_data, str):
                # Handle simple string format
                existing = [
                    a
                    for a in self._trail.assumptions_in_effect
                    if a.assumption == assumption_data
                ]
                if not existing:
                    self._trail.add_assumption(
                        assumption_data,
                        step_id,
                        "Impact not specified",
                    )

        # Extract decisions from envelope
        decisions = envelope.get("decisions_made", envelope.get("key_decisions", []))
        for decision_data in decisions:
            if isinstance(decision_data, dict):
                # Handle structured decision format
                decision_text = decision_data.get("decision", "")
                rationale = decision_data.get("rationale", "")
                alternatives = decision_data.get("alternatives_rejected", [])
                confidence = decision_data.get("confidence", "MEDIUM")
                dec_step = decision_data.get("step", step_id)
                dec_flow = decision_data.get("flow", flow_key)

                if decision_text:
                    # Check if decision already exists
                    existing = [d for d in self._trail.decisions if d.decision == decision_text]
                    if not existing:
                        self._trail.add_decision(
                            dec_step,
                            dec_flow,
                            decision_text,
                            rationale,
                            alternatives,
                            confidence,
                        )
            elif isinstance(decision_data, str):
                # Handle simple string format
                existing = [d for d in self._trail.decisions if d.decision == decision_data]
                if not existing:
                    self._trail.add_decision(
                        step_id,
                        flow_key,
                        decision_data,
                        "Rationale not specified",
                    )

        # Extract open questions
        summary = envelope.get("summary", {})
        if isinstance(summary, dict):
            questions = summary.get("open_questions", [])
            for q in questions:
                self._trail.add_open_question(q)

        logger.debug(
            "Extracted from envelope: %d assumptions, %d decisions",
            len(assumptions),
            len(decisions),
        )


# =============================================================================
# File I/O Functions
# =============================================================================


def _get_scent_trail_path(run_base: Path) -> Path:
    """Get the path to the scent trail file.

    Args:
        run_base: Path to RUN_BASE directory.

    Returns:
        Path to scent_trail.json file.
    """
    return Path(run_base) / "scent_trail.json"


def load_scent_trail(run_base: Path) -> Optional[ScentTrail]:
    """Load scent trail from RUN_BASE/scent_trail.json.

    Args:
        run_base: Path to RUN_BASE directory.

    Returns:
        Loaded ScentTrail, or None if file doesn't exist.
    """
    path = _get_scent_trail_path(run_base)
    if not path.exists():
        logger.debug("No scent trail found at %s", path)
        return None

    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        trail = ScentTrail.from_dict(data)
        logger.debug("Loaded scent trail from %s", path)
        return trail
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to load scent trail from %s: %s", path, e)
        return None


def save_scent_trail(trail: ScentTrail, run_base: Path) -> Path:
    """Save scent trail to RUN_BASE/scent_trail.json.

    Args:
        trail: The ScentTrail to save.
        run_base: Path to RUN_BASE directory.

    Returns:
        Path where trail was saved.
    """
    run_base = Path(run_base)
    run_base.mkdir(parents=True, exist_ok=True)

    path = _get_scent_trail_path(run_base)

    # Update timestamp before saving
    trail._update_timestamp()

    with path.open("w", encoding="utf-8") as f:
        json.dump(trail.to_dict(), f, indent=2)

    logger.debug("Saved scent trail to %s", path)
    return path


# =============================================================================
# Convenience Functions
# =============================================================================


def create_scent_trail(run_id: str, flow_objective: str) -> ScentTrail:
    """Create a new scent trail.

    Args:
        run_id: Unique identifier for the run.
        flow_objective: High-level objective of the run.

    Returns:
        New ScentTrail instance.
    """
    return ScentTrail(run_id=run_id, flow_objective=flow_objective)


def update_scent_trail_from_step(
    run_base: Path,
    step_id: str,
    flow_key: str,
    envelope: Optional[Dict[str, Any]] = None,
    decisions: Optional[List[Dict[str, Any]]] = None,
    assumptions: Optional[List[Dict[str, Any]]] = None,
) -> ScentTrail:
    """Update scent trail after a step completes.

    Convenience function that loads the trail, updates it with step
    outputs, and saves it back.

    Args:
        run_base: Path to RUN_BASE directory.
        step_id: ID of the completed step.
        flow_key: Key of the current flow.
        envelope: Optional handoff envelope to extract from.
        decisions: Optional list of decisions to add.
        assumptions: Optional list of assumptions to add.

    Returns:
        Updated ScentTrail.
    """
    builder = ScentTrailBuilder(run_base)

    # Extract run_id from path or generate one
    run_id = run_base.name if run_base.name != "." else f"run-{uuid.uuid4().hex[:8]}"
    flow_objective = f"Flow {flow_key} execution"

    trail = builder.load_or_create(run_id, flow_objective)

    # Extract from envelope if provided
    if envelope:
        builder.extract_from_envelope(envelope)

    # Add explicit decisions
    if decisions:
        for d in decisions:
            trail.add_decision(
                step_id=d.get("step_id", step_id),
                flow_key=d.get("flow_key", flow_key),
                decision=d.get("decision", ""),
                rationale=d.get("rationale", ""),
                alternatives=d.get("alternatives_rejected", []),
                confidence=d.get("confidence", "MEDIUM"),
            )

    # Add explicit assumptions
    if assumptions:
        for a in assumptions:
            trail.add_assumption(
                assumption=a.get("assumption", ""),
                made_at=a.get("made_at", step_id),
                impact_if_wrong=a.get("impact_if_wrong", "Unknown impact"),
            )

    builder.save()
    return trail


def get_scent_trail_summary(run_base: Path, max_decisions: int = 5) -> str:
    """Get a compact summary of the scent trail for context loading.

    Args:
        run_base: Path to RUN_BASE directory.
        max_decisions: Maximum number of recent decisions to include.

    Returns:
        Compact string summary suitable for context injection.
    """
    trail = load_scent_trail(run_base)
    if trail is None:
        return "No prior decisions recorded."

    lines = []

    # Recent decisions
    recent_decisions = trail.decisions[-max_decisions:] if trail.decisions else []
    if recent_decisions:
        lines.append("Prior decisions:")
        for d in recent_decisions:
            lines.append(f"  - {d.decision} (step: {d.step_id}, confidence: {d.confidence})")

    # Active assumptions
    active = trail.get_active_assumptions()
    if active:
        lines.append("Active assumptions:")
        for a in active:
            lines.append(f"  - {a.assumption} (impact if wrong: {a.impact_if_wrong})")

    # Unresolved conflicts
    conflicts = trail.get_unresolved_conflicts()
    if conflicts:
        lines.append("CONFLICTS requiring attention:")
        for c in conflicts:
            lines.append(f"  - {c.prior_decision} vs {c.current_finding}")

    return "\n".join(lines) if lines else "No significant decisions or assumptions recorded."
