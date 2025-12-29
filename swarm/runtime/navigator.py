"""
navigator.py - Intelligence-Driven Navigation for Stepwise Execution

This module implements the Navigator pattern: a cheap LLM call that runs after
each step to decide routing and generate instructions for the next station.

Design Philosophy:
    - Traditional tooling does the heavy lifting (graph checks, verification,
      diff scanning, stall detection)
    - Navigator LLM receives a compact, pre-digested packet
    - Navigator makes the smart call quickly (Haiku-class, seconds, pennies)
    - Kernel enforces the decision (graph constraints, detour validation)

The Navigator is NOT a replacement for the router - it augments it:
    - Router: deterministic-first, graph-constrained edge selection
    - Navigator: intelligent brief generation + sidequest triggering + stall diagnosis

Usage:
    from swarm.runtime.navigator import (
        Navigator,
        NavigatorInput,
        NavigatorOutput,
        build_navigator_input,
    )

    # Build input from traditional tooling outputs
    nav_input = build_navigator_input(
        current_node=current_step.id,
        flow_graph=flow_graph,
        verification_result=verification_result,
        file_changes=file_changes_summary,
        context_digest=context_pack.summary,
        sidequest_catalog=sidequest_catalog,
    )

    # Run navigator (cheap LLM call)
    nav_output = await navigator.navigate(nav_input)

    # Use output for routing and next step
    next_step_brief = nav_output.next_step_brief
    if nav_output.detour_request:
        run_state.push_interruption(...)
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# =============================================================================
# Core Types
# =============================================================================


class RouteIntent(str, Enum):
    """Navigator's routing intent."""
    ADVANCE = "advance"      # Proceed to next node
    LOOP = "loop"            # Continue iteration (microloop)
    DETOUR = "detour"        # Inject sidequest before continuing
    PAUSE = "pause"          # Request human intervention
    TERMINATE = "terminate"  # Flow complete


class SignalLevel(str, Enum):
    """Signal severity levels."""
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass
class EdgeCandidate:
    """A candidate edge for navigation (pre-filtered by graph)."""
    edge_id: str
    target_node: str
    edge_type: str = "sequence"  # sequence, loop, branch, detour
    priority: int = 50
    condition_summary: str = ""  # Human-readable condition (e.g., "status == VERIFIED")


@dataclass
class SidequestOption:
    """A sidequest option from the catalog."""
    sidequest_id: str
    station_template: str  # Station/template to execute
    trigger_description: str  # When to use this sidequest
    objective_template: str  # Template for objective (can use {{placeholders}})
    priority: int = 50
    cost_hint: str = "low"  # low, medium, high (relative LLM cost)


@dataclass
class VerificationSummary:
    """Summary of verification results from traditional tooling."""
    passed: bool
    checks_run: int = 0
    checks_passed: int = 0
    checks_failed: int = 0
    failure_summary: str = ""  # Compact description of failures
    artifacts_verified: List[str] = field(default_factory=list)
    commands_run: List[str] = field(default_factory=list)


@dataclass
class FileChangesSummary:
    """Summary of file changes from diff scanner."""
    files_modified: int = 0
    files_added: int = 0
    files_deleted: int = 0
    lines_added: int = 0
    lines_removed: int = 0
    sensitive_paths_touched: List[str] = field(default_factory=list)
    change_signature: str = ""  # Hash for stall detection


@dataclass
class StallSignals:
    """Signals for stall detection from ProgressTracker."""
    is_stalled: bool = False
    stall_count: int = 0  # Consecutive iterations with no progress
    last_change_signature: str = ""
    same_failure_signature: bool = False  # Same test failure repeated
    no_file_changes: bool = False


@dataclass
class NavigatorInput:
    """Compact input packet for Navigator LLM.

    All fields are pre-computed by traditional tooling. The Navigator
    receives a digested view, not raw data.
    """
    # Identity
    run_id: str
    flow_key: str
    current_node: str
    iteration: int = 1

    # Graph context (from FlowGraph)
    candidate_edges: List[EdgeCandidate] = field(default_factory=list)
    sidequest_options: List[SidequestOption] = field(default_factory=list)

    # Verification results (from station spec checks)
    verification: Optional[VerificationSummary] = None

    # File changes (from diff scanner)
    file_changes: Optional[FileChangesSummary] = None

    # Stall signals (from ProgressTracker)
    stall_signals: Optional[StallSignals] = None

    # Context digest (from ContextPack - compressed summary)
    context_digest: str = ""

    # Previous step summary (from last HandoffEnvelope)
    previous_step_summary: str = ""
    previous_step_status: str = ""  # VERIFIED, UNVERIFIED, BLOCKED

    # Optional: worker's suggested route (if available)
    worker_suggested_route: Optional[str] = None


@dataclass
class RouteProposal:
    """Navigator's proposed route."""
    intent: RouteIntent
    target_node: Optional[str] = None  # Required for advance/loop
    reasoning: str = ""  # Why this route (stored in audit, not sent to worker)
    confidence: float = 1.0


@dataclass
class DetourRequest:
    """Request to inject a sidequest."""
    sidequest_id: str
    objective: str  # Specific objective for this detour
    priority: int = 50
    resume_at: Optional[str] = None  # Node to resume at after detour


@dataclass
class NavigatorSignals:
    """Signals emitted by Navigator for observability."""
    stall: SignalLevel = SignalLevel.NONE
    risk: SignalLevel = SignalLevel.NONE
    uncertainty: SignalLevel = SignalLevel.NONE
    needs_human: bool = False


@dataclass
class NextStepBrief:
    """Instructions for the next station.

    This is the key output - tells the next worker what to focus on
    given what just happened.
    """
    objective: str  # What the next station should accomplish
    focus_areas: List[str] = field(default_factory=list)  # Specific things to check
    context_pointers: List[str] = field(default_factory=list)  # File paths to read
    warnings: List[str] = field(default_factory=list)  # Things to watch out for
    constraints: List[str] = field(default_factory=list)  # Boundaries to respect


@dataclass
class NavigatorOutput:
    """Complete output from Navigator."""
    route: RouteProposal
    next_step_brief: NextStepBrief
    signals: NavigatorSignals = field(default_factory=NavigatorSignals)
    detour_request: Optional[DetourRequest] = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # Audit trail (not sent to next worker)
    elimination_log: List[Dict[str, str]] = field(default_factory=list)
    factors_considered: List[Dict[str, Any]] = field(default_factory=list)


# =============================================================================
# Progress Tracker (Traditional Tooling)
# =============================================================================


class ProgressTracker:
    """Track progress for stall detection using hashing.

    This is pure traditional tooling - no LLM calls. It computes
    signatures from file changes and test results to detect when
    the system is stuck in a loop making no progress.
    """

    def __init__(self, stall_threshold: int = 3):
        """Initialize tracker.

        Args:
            stall_threshold: Number of iterations with same signature
                           before declaring stall.
        """
        self._stall_threshold = stall_threshold
        self._history: Dict[str, List[str]] = {}  # node_id -> list of signatures

    def compute_signature(
        self,
        file_changes: Optional[FileChangesSummary],
        verification: Optional[VerificationSummary],
        step_output: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Compute a signature from current state.

        The signature captures:
        - File change summary (what changed)
        - Verification failure pattern (what's still wrong)
        - Step output hash (what was produced)

        If consecutive iterations have the same signature, we're stalled.
        """
        parts = []

        if file_changes:
            parts.append(f"fc:{file_changes.change_signature}")

        if verification and not verification.passed:
            parts.append(f"vf:{verification.failure_summary[:100]}")

        if step_output:
            # Hash key fields that indicate progress
            status = step_output.get("status", "")
            artifacts = sorted(step_output.get("artifacts", {}).keys())
            parts.append(f"s:{status}")
            parts.append(f"a:{','.join(artifacts)}")

        combined = "|".join(parts)
        return hashlib.sha256(combined.encode()).hexdigest()[:16]

    def record_iteration(
        self,
        node_id: str,
        file_changes: Optional[FileChangesSummary],
        verification: Optional[VerificationSummary],
        step_output: Optional[Dict[str, Any]] = None,
    ) -> StallSignals:
        """Record an iteration and check for stall.

        Args:
            node_id: The node being tracked.
            file_changes: File changes from this iteration.
            verification: Verification results from this iteration.
            step_output: Step output from this iteration.

        Returns:
            StallSignals indicating whether we're stalled.
        """
        signature = self.compute_signature(file_changes, verification, step_output)

        if node_id not in self._history:
            self._history[node_id] = []

        history = self._history[node_id]
        history.append(signature)

        # Check for repeated signature
        stall_count = 0
        if len(history) >= 2:
            for i in range(len(history) - 1, -1, -1):
                if history[i] == signature:
                    stall_count += 1
                else:
                    break

        is_stalled = stall_count >= self._stall_threshold

        # Check specific patterns
        same_failure = False
        if verification and not verification.passed and len(history) >= 2:
            # Compare failure summaries
            same_failure = history[-1] == history[-2] if len(history) >= 2 else False

        no_file_changes = file_changes is None or (
            file_changes.files_modified == 0 and
            file_changes.files_added == 0 and
            file_changes.files_deleted == 0
        )

        return StallSignals(
            is_stalled=is_stalled,
            stall_count=stall_count,
            last_change_signature=signature,
            same_failure_signature=same_failure,
            no_file_changes=no_file_changes,
        )

    def reset(self, node_id: str) -> None:
        """Reset history for a node (e.g., after successful verification)."""
        if node_id in self._history:
            del self._history[node_id]

    def clear_all(self) -> None:
        """Clear all history."""
        self._history.clear()


# =============================================================================
# Navigator Input Builder (Traditional Tooling Integration)
# =============================================================================


def build_navigator_input(
    run_id: str,
    flow_key: str,
    current_node: str,
    iteration: int,
    candidate_edges: List[EdgeCandidate],
    sidequest_options: Optional[List[SidequestOption]] = None,
    verification: Optional[VerificationSummary] = None,
    file_changes: Optional[FileChangesSummary] = None,
    stall_signals: Optional[StallSignals] = None,
    context_digest: str = "",
    previous_step_summary: str = "",
    previous_step_status: str = "",
    worker_suggested_route: Optional[str] = None,
) -> NavigatorInput:
    """Build NavigatorInput from traditional tooling outputs.

    This function collects outputs from various traditional tools
    (graph traversal, verification, diff scanner, progress tracker)
    and packages them into a compact input for the Navigator LLM.
    """
    return NavigatorInput(
        run_id=run_id,
        flow_key=flow_key,
        current_node=current_node,
        iteration=iteration,
        candidate_edges=candidate_edges,
        sidequest_options=sidequest_options or [],
        verification=verification,
        file_changes=file_changes,
        stall_signals=stall_signals,
        context_digest=context_digest,
        previous_step_summary=previous_step_summary,
        previous_step_status=previous_step_status,
        worker_suggested_route=worker_suggested_route,
    )


def extract_candidate_edges_from_graph(
    flow_graph: Any,  # FlowGraph from router.py
    current_node: str,
) -> List[EdgeCandidate]:
    """Extract candidate edges from FlowGraph.

    This is a pure graph traversal - no LLM needed.
    """
    candidates = []

    for edge in flow_graph.get_outgoing_edges(current_node):
        condition_summary = ""
        if edge.condition:
            if edge.condition.expression:
                condition_summary = edge.condition.expression
            elif edge.condition.field:
                condition_summary = f"{edge.condition.field} {edge.condition.operator} {edge.condition.value}"

        candidates.append(EdgeCandidate(
            edge_id=edge.edge_id,
            target_node=edge.to_node,
            edge_type=edge.edge_type,
            priority=edge.priority,
            condition_summary=condition_summary,
        ))

    # Sort by priority (higher first)
    candidates.sort(key=lambda e: -e.priority)
    return candidates


# =============================================================================
# Navigator (LLM Intelligence)
# =============================================================================


class Navigator:
    """Navigator for intelligent routing decisions.

    The Navigator makes cheap LLM calls to:
    1. Decide the best route among valid candidates
    2. Generate instructions for the next station (NextStepBrief)
    3. Detect when sidequests are needed
    4. Diagnose stalls and suggest interventions

    Traditional tooling provides the inputs; Navigator provides intelligence.
    """

    def __init__(
        self,
        llm_call: Optional[Callable[[str, str], str]] = None,
        model: str = "haiku",  # Default to cheap/fast model
    ):
        """Initialize Navigator.

        Args:
            llm_call: Callable that takes (system_prompt, user_prompt) and
                     returns LLM response. If None, uses deterministic fallback.
            model: Model to use for navigation (default: haiku for speed/cost).
        """
        self._llm_call = llm_call
        self._model = model

    def navigate(self, nav_input: NavigatorInput) -> NavigatorOutput:
        """Make navigation decision.

        Args:
            nav_input: Compact input from traditional tooling.

        Returns:
            NavigatorOutput with route, brief, signals, and optional detour.
        """
        # If no LLM available, use deterministic fallback
        if self._llm_call is None:
            return self._deterministic_navigate(nav_input)

        # Build prompts
        system_prompt = self._build_system_prompt()
        user_prompt = self._build_user_prompt(nav_input)

        try:
            # Make LLM call
            response = self._llm_call(system_prompt, user_prompt)

            # Parse response
            return self._parse_response(response, nav_input)

        except Exception as e:
            logger.warning("Navigator LLM call failed: %s, using fallback", e)
            return self._deterministic_navigate(nav_input)

    async def navigate_async(self, nav_input: NavigatorInput) -> NavigatorOutput:
        """Async version of navigate."""
        # For now, just wrap sync version
        # TODO: Add async LLM call support
        return self.navigate(nav_input)

    def _build_system_prompt(self) -> str:
        """Build system prompt for Navigator."""
        return """You are a Navigator for a stepwise execution system.

Your job is to:
1. Decide the best route among valid candidates
2. Write a brief for the next station (what to focus on)
3. Detect when sidequests are needed (e.g., clarifier, env-doctor)
4. Signal stalls, risks, or uncertainty

You receive a compact packet with:
- Current node and candidate edges
- Verification results (what passed/failed)
- File changes summary
- Stall signals (are we making progress?)
- Context digest

Respond with JSON matching this schema:
{
    "route": {
        "intent": "advance|loop|detour|pause|terminate",
        "target_node": "node-id or null",
        "reasoning": "why this route (brief)"
    },
    "next_step_brief": {
        "objective": "what the next station should accomplish",
        "focus_areas": ["specific things to check"],
        "warnings": ["things to watch out for"]
    },
    "signals": {
        "stall": "none|low|medium|high",
        "risk": "none|low|medium|high",
        "uncertainty": "none|low|medium|high"
    },
    "detour_request": null or {
        "sidequest_id": "id",
        "objective": "specific objective for this detour"
    }
}

Be concise. The next worker needs actionable instructions, not essays."""

    def _build_user_prompt(self, nav_input: NavigatorInput) -> str:
        """Build user prompt from NavigatorInput."""
        # Convert to compact JSON representation
        data = {
            "current_node": nav_input.current_node,
            "iteration": nav_input.iteration,
            "previous_status": nav_input.previous_step_status,
        }

        # Add candidate edges
        if nav_input.candidate_edges:
            data["candidate_edges"] = [
                {
                    "edge_id": e.edge_id,
                    "target": e.target_node,
                    "type": e.edge_type,
                    "condition": e.condition_summary or "(none)",
                }
                for e in nav_input.candidate_edges
            ]

        # Add verification summary
        if nav_input.verification:
            v = nav_input.verification
            data["verification"] = {
                "passed": v.passed,
                "failures": v.failure_summary if not v.passed else "",
            }

        # Add stall signals
        if nav_input.stall_signals and nav_input.stall_signals.is_stalled:
            data["stall"] = {
                "is_stalled": True,
                "stall_count": nav_input.stall_signals.stall_count,
                "same_failure": nav_input.stall_signals.same_failure_signature,
            }

        # Add sidequest options (if any)
        if nav_input.sidequest_options:
            data["sidequests_available"] = [
                {"id": s.sidequest_id, "when": s.trigger_description}
                for s in nav_input.sidequest_options
            ]

        # Add context digest
        if nav_input.context_digest:
            data["context"] = nav_input.context_digest[:500]  # Limit length

        return json.dumps(data, indent=2)

    def _parse_response(
        self,
        response: str,
        nav_input: NavigatorInput,
    ) -> NavigatorOutput:
        """Parse LLM response into NavigatorOutput."""
        try:
            # Try to extract JSON from response
            # Handle responses that may have text before/after JSON
            json_match = response
            if "```json" in response:
                start = response.find("```json") + 7
                end = response.find("```", start)
                json_match = response[start:end].strip()
            elif "{" in response:
                start = response.find("{")
                end = response.rfind("}") + 1
                json_match = response[start:end]

            data = json.loads(json_match)

            # Parse route
            route_data = data.get("route", {})
            route = RouteProposal(
                intent=RouteIntent(route_data.get("intent", "advance")),
                target_node=route_data.get("target_node"),
                reasoning=route_data.get("reasoning", ""),
            )

            # Validate target_node against candidates
            if route.intent in (RouteIntent.ADVANCE, RouteIntent.LOOP):
                valid_targets = {e.target_node for e in nav_input.candidate_edges}
                if route.target_node not in valid_targets:
                    # Fall back to first candidate
                    if nav_input.candidate_edges:
                        route.target_node = nav_input.candidate_edges[0].target_node
                        route.reasoning += " (target validated by kernel)"

            # Parse brief
            brief_data = data.get("next_step_brief", {})
            brief = NextStepBrief(
                objective=brief_data.get("objective", "Continue with next step"),
                focus_areas=brief_data.get("focus_areas", []),
                warnings=brief_data.get("warnings", []),
            )

            # Parse signals
            signals_data = data.get("signals", {})
            signals = NavigatorSignals(
                stall=SignalLevel(signals_data.get("stall", "none")),
                risk=SignalLevel(signals_data.get("risk", "none")),
                uncertainty=SignalLevel(signals_data.get("uncertainty", "none")),
            )

            # Parse detour request
            detour_request = None
            detour_data = data.get("detour_request")
            if detour_data:
                detour_request = DetourRequest(
                    sidequest_id=detour_data.get("sidequest_id", ""),
                    objective=detour_data.get("objective", ""),
                )

            return NavigatorOutput(
                route=route,
                next_step_brief=brief,
                signals=signals,
                detour_request=detour_request,
            )

        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.warning("Failed to parse Navigator response: %s", e)
            return self._deterministic_navigate(nav_input)

    def _deterministic_navigate(
        self,
        nav_input: NavigatorInput,
    ) -> NavigatorOutput:
        """Deterministic fallback when LLM is unavailable.

        Uses traditional logic to pick route and generate basic brief.
        """
        # Default route: first candidate edge
        route = RouteProposal(intent=RouteIntent.TERMINATE)

        if nav_input.candidate_edges:
            first_edge = nav_input.candidate_edges[0]

            # Check if verification passed
            if nav_input.verification and nav_input.verification.passed:
                # Look for non-loop exit edge
                for edge in nav_input.candidate_edges:
                    if edge.edge_type != "loop":
                        route = RouteProposal(
                            intent=RouteIntent.ADVANCE,
                            target_node=edge.target_node,
                            reasoning="Verification passed, advancing (deterministic)",
                        )
                        break
            elif nav_input.previous_step_status == "VERIFIED":
                route = RouteProposal(
                    intent=RouteIntent.ADVANCE,
                    target_node=first_edge.target_node,
                    reasoning="Status VERIFIED, advancing (deterministic)",
                )
            else:
                # Check for stall
                if nav_input.stall_signals and nav_input.stall_signals.is_stalled:
                    # If stalled and sidequests available, suggest detour
                    if nav_input.sidequest_options:
                        route = RouteProposal(
                            intent=RouteIntent.DETOUR,
                            reasoning="Stall detected, suggesting sidequest (deterministic)",
                        )
                    else:
                        route = RouteProposal(
                            intent=RouteIntent.PAUSE,
                            reasoning="Stall detected, no sidequests available (deterministic)",
                        )
                else:
                    # Default: advance to first candidate
                    route = RouteProposal(
                        intent=RouteIntent.ADVANCE,
                        target_node=first_edge.target_node,
                        reasoning="Default progression (deterministic)",
                    )

        # Generate basic brief
        brief = NextStepBrief(
            objective=f"Continue from {nav_input.current_node}",
            focus_areas=[],
            warnings=[],
        )

        # Set signals based on stall
        signals = NavigatorSignals()
        if nav_input.stall_signals and nav_input.stall_signals.is_stalled:
            signals.stall = SignalLevel.HIGH

        return NavigatorOutput(
            route=route,
            next_step_brief=brief,
            signals=signals,
        )


# =============================================================================
# Serialization
# =============================================================================


def navigator_output_to_dict(output: NavigatorOutput) -> Dict[str, Any]:
    """Convert NavigatorOutput to dictionary for storage."""
    result = {
        "route": {
            "intent": output.route.intent.value,
            "target_node": output.route.target_node,
            "reasoning": output.route.reasoning,
            "confidence": output.route.confidence,
        },
        "next_step_brief": {
            "objective": output.next_step_brief.objective,
            "focus_areas": output.next_step_brief.focus_areas,
            "context_pointers": output.next_step_brief.context_pointers,
            "warnings": output.next_step_brief.warnings,
            "constraints": output.next_step_brief.constraints,
        },
        "signals": {
            "stall": output.signals.stall.value,
            "risk": output.signals.risk.value,
            "uncertainty": output.signals.uncertainty.value,
            "needs_human": output.signals.needs_human,
        },
        "timestamp": output.timestamp.isoformat(),
    }

    if output.detour_request:
        result["detour_request"] = {
            "sidequest_id": output.detour_request.sidequest_id,
            "objective": output.detour_request.objective,
            "priority": output.detour_request.priority,
            "resume_at": output.detour_request.resume_at,
        }

    if output.elimination_log:
        result["elimination_log"] = output.elimination_log

    if output.factors_considered:
        result["factors_considered"] = output.factors_considered

    return result


def navigator_output_from_dict(data: Dict[str, Any]) -> NavigatorOutput:
    """Parse NavigatorOutput from dictionary."""
    route_data = data.get("route", {})
    route = RouteProposal(
        intent=RouteIntent(route_data.get("intent", "advance")),
        target_node=route_data.get("target_node"),
        reasoning=route_data.get("reasoning", ""),
        confidence=route_data.get("confidence", 1.0),
    )

    brief_data = data.get("next_step_brief", {})
    brief = NextStepBrief(
        objective=brief_data.get("objective", ""),
        focus_areas=brief_data.get("focus_areas", []),
        context_pointers=brief_data.get("context_pointers", []),
        warnings=brief_data.get("warnings", []),
        constraints=brief_data.get("constraints", []),
    )

    signals_data = data.get("signals", {})
    signals = NavigatorSignals(
        stall=SignalLevel(signals_data.get("stall", "none")),
        risk=SignalLevel(signals_data.get("risk", "none")),
        uncertainty=SignalLevel(signals_data.get("uncertainty", "none")),
        needs_human=signals_data.get("needs_human", False),
    )

    detour_request = None
    if "detour_request" in data and data["detour_request"]:
        dr = data["detour_request"]
        detour_request = DetourRequest(
            sidequest_id=dr.get("sidequest_id", ""),
            objective=dr.get("objective", ""),
            priority=dr.get("priority", 50),
            resume_at=dr.get("resume_at"),
        )

    return NavigatorOutput(
        route=route,
        next_step_brief=brief,
        signals=signals,
        detour_request=detour_request,
        elimination_log=data.get("elimination_log", []),
        factors_considered=data.get("factors_considered", []),
    )
