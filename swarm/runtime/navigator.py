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
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


# =============================================================================
# Core Types
# =============================================================================


class RouteIntent(str, Enum):
    """Navigator's routing intent."""

    ADVANCE = "advance"  # Proceed to next node
    LOOP = "loop"  # Continue iteration (microloop)
    DETOUR = "detour"  # Inject sidequest before continuing
    PAUSE = "pause"  # Request human intervention
    TERMINATE = "terminate"  # Flow complete
    EXTEND_GRAPH = "extend_graph"  # Propose edge not in graph (map gap)


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
class ProposedNode:
    """Proposed node for EXTEND_GRAPH intent.

    Specifies WHAT to run when Navigator proposes a map gap.
    Separate from ProposedEdge which specifies HOW to connect it.

    Attributes:
        node_id: Optional explicit node ID (auto-generated if not provided).
        template_id: Station/template to execute (required if station_id not set).
        station_id: Station to execute (required if template_id not set).
        objective: Specific objective for this node execution.
        params: Additional parameters for execution.
    """

    template_id: Optional[str] = None
    station_id: Optional[str] = None
    node_id: Optional[str] = None
    objective: str = ""
    params: Dict[str, Any] = field(default_factory=dict)

    def get_target_id(self) -> Optional[str]:
        """Get the target station/template ID."""
        return self.station_id or self.template_id


@dataclass
class ProposedEdge:
    """Proposed edge for EXTEND_GRAPH intent.

    When Navigator encounters a map gap (needs a transition not in the graph),
    it proposes an edge via this structure. The Kernel validates the target
    and injects the edge into the run's graph view.

    This is different from DETOUR:
    - DETOUR: Target is a known sidequest from the catalog
    - EXTEND_GRAPH: Target is any valid station/template not in current edges

    Attributes:
        from_node: Source node (current position).
        to_node: Target station/template ID (must be validated).
        why: Reasoning for why this edge should exist.
        edge_type: Type of edge (default: "injection").
        priority: Priority for the injected edge.
        is_return: Whether execution should return after this node.
        proposed_node: Optional ProposedNode with execution details.
    """

    from_node: str
    to_node: str
    why: str
    edge_type: str = "injection"
    priority: int = 70
    is_return: bool = True  # Default: return after executing
    proposed_node: Optional[ProposedNode] = None


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

    # Forensic verdict: comparison of handoff claims vs actual evidence
    # This is the key input for Semantic Handoff Injection - Navigator uses
    # this to detect "reward hacking" (claimed progress without evidence).
    # See forensic_comparator.py for ForensicVerdict structure.
    forensic_verdict: Optional[Dict[str, Any]] = None

    # Candidate-set pattern: pre-computed routing candidates from the kernel.
    # Navigator MUST choose from these candidates via chosen_candidate_id.
    # Each candidate has: candidate_id, action, target_node, reason, priority, source.
    # See types.py RoutingCandidate for full structure.
    routing_candidates: List[Dict[str, Any]] = field(default_factory=list)


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
    proposed_edge: Optional[ProposedEdge] = None  # For EXTEND_GRAPH intent
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # Candidate-set pattern: Navigator must choose from provided candidates
    chosen_candidate_id: Optional[str] = None  # ID of selected candidate

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
            file_changes.files_modified == 0
            and file_changes.files_added == 0
            and file_changes.files_deleted == 0
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
    forensic_verdict: Optional[Dict[str, Any]] = None,
    routing_candidates: Optional[List[Dict[str, Any]]] = None,
) -> NavigatorInput:
    """Build NavigatorInput from traditional tooling outputs.

    This function collects outputs from various traditional tools
    (graph traversal, verification, diff scanner, progress tracker,
    forensic comparator) and packages them into a compact input for
    the Navigator LLM.

    Args:
        run_id: The run identifier.
        flow_key: The flow key.
        current_node: Current node/step being navigated from.
        iteration: Current iteration number (for microloops).
        candidate_edges: Available edges from current node.
        sidequest_options: Available sidequests to inject.
        verification: Verification results from spec checks.
        file_changes: File changes from diff scanner.
        stall_signals: Stall detection signals.
        context_digest: Compressed context summary.
        previous_step_summary: Summary from last step's handoff.
        previous_step_status: Status from last step (VERIFIED, etc.).
        worker_suggested_route: Route suggested by the worker.
        forensic_verdict: ForensicVerdict comparing claims vs evidence
            (Semantic Handoff Injection). See forensic_comparator.py.
        routing_candidates: Pre-computed routing candidates from the kernel.
            Navigator MUST choose from these via chosen_candidate_id.

    Returns:
        NavigatorInput ready for Navigator.navigate().
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
        forensic_verdict=forensic_verdict,
        routing_candidates=routing_candidates or [],
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
                condition_summary = (
                    f"{edge.condition.field} {edge.condition.operator} {edge.condition.value}"
                )

        candidates.append(
            EdgeCandidate(
                edge_id=edge.edge_id,
                target_node=edge.to_node,
                edge_type=edge.edge_type,
                priority=edge.priority,
                condition_summary=condition_summary,
            )
        )

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

## The Candidate-Set Pattern (CRITICAL)

You receive a set of **Valid Moves** (routing candidates) generated by the kernel.
Your job is to SELECT the best move from this set, not invent new routes.

Each candidate has:
- `candidate_id`: Unique identifier (MUST be returned in your response)
- `action`: What the move does (advance, loop, detour, escalate, repeat, terminate)
- `target_node`: Where it goes (if applicable)
- `reason`: Why this is a valid option
- `priority`: Default ranking (higher = more likely correct)
- `is_default`: Whether this is the suggested choice

**RULE**: You MUST return a `chosen_candidate_id` that matches one of the provided candidates.
The only exception is EXTEND_GRAPH, when you need a transition not in the candidate set.

## Your Responsibilities

1. **Choose** the best route from valid candidates (return `chosen_candidate_id`)
2. **Write** a brief for the next station (what to focus on)
3. **Detect** when sidequests are needed (e.g., clarifier, env-doctor)
4. **Signal** stalls, risks, or uncertainty
5. **Verify** worker claims against forensic evidence

## Forensic Verification (IMPORTANT)

The forensic_verdict field compares worker claims against actual evidence:
- claim_verified: Did claims match evidence?
- confidence: How trustworthy is this verdict (0.0-1.0)?
- recommendation: TRUST (proceed), VERIFY (double-check), REJECT (flag issue)
- reward_hacking_flags: Specific patterns like "test_count_decreased", "claimed_pass_but_failed"

**If recommendation is REJECT or multiple reward_hacking_flags are present**:
- Set signals.risk to "high"
- Add warnings to next_step_brief about the discrepancies
- Choose RETRY or ESCALATE candidate, NOT the ADVANCE candidate
- Consider PAUSE intent if multiple critical flags

Common reward hacking patterns:
- "test_count_decreased": Tests may have been deleted to hide failures
- "claimed_pass_but_failed": Worker claims tests pass but evidence shows failures
- "claimed_progress_no_diff": Worker claims progress but no file changes detected
- "coverage_dropped": Code coverage decreased (possible test deletion)

## Response Schema

Respond with JSON matching this schema:
{
    "chosen_candidate_id": "REQUIRED: ID from candidates list (or 'extend_graph' for EXTEND_GRAPH)",
    "route": {
        "intent": "advance|loop|detour|pause|terminate|extend_graph",
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

        # Add routing candidates (candidate-set pattern - primary routing input)
        if nav_input.routing_candidates:
            data["routing_candidates"] = [
                {
                    "candidate_id": c.get("candidate_id", ""),
                    "action": c.get("action", ""),
                    "target_node": c.get("target_node"),
                    "reason": c.get("reason", ""),
                    "priority": c.get("priority", 50),
                    "is_default": c.get("is_default", False),
                }
                for c in nav_input.routing_candidates
            ]

        # Add candidate edges (legacy format, for backwards compatibility)
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

        # Add forensic verdict (Semantic Handoff Injection)
        if nav_input.forensic_verdict:
            fv = nav_input.forensic_verdict
            data["forensic_verdict"] = {
                "claim_verified": fv.get("claim_verified", True),
                "confidence": fv.get("confidence", 1.0),
                "recommendation": fv.get("recommendation", "TRUST"),
                "reward_hacking_flags": fv.get("reward_hacking_flags", []),
            }
            # Add summary of discrepancies if present
            discrepancies = fv.get("discrepancies", [])
            if discrepancies:
                data["forensic_verdict"]["discrepancy_count"] = len(discrepancies)
                # Include first critical discrepancy as example
                critical = [d for d in discrepancies if d.get("severity") == "critical"]
                if critical:
                    data["forensic_verdict"]["critical_issue"] = critical[0].get("details", "")

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

            # Extract and validate chosen_candidate_id (candidate-set pattern)
            chosen_candidate_id = data.get("chosen_candidate_id")
            valid_candidate_ids = {
                c.get("candidate_id") for c in nav_input.routing_candidates
            }

            # Validate chosen_candidate_id if routing_candidates were provided
            if nav_input.routing_candidates and chosen_candidate_id:
                if chosen_candidate_id not in valid_candidate_ids:
                    # Special case: extend_graph doesn't need to match
                    if chosen_candidate_id != "extend_graph":
                        logger.warning(
                            "Navigator chose invalid candidate_id: %s (valid: %s)",
                            chosen_candidate_id,
                            valid_candidate_ids,
                        )
                        # Fall back to default candidate
                        default_candidates = [
                            c for c in nav_input.routing_candidates
                            if c.get("is_default")
                        ]
                        if default_candidates:
                            chosen_candidate_id = default_candidates[0].get("candidate_id")
                        elif nav_input.routing_candidates:
                            chosen_candidate_id = nav_input.routing_candidates[0].get("candidate_id")

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
                chosen_candidate_id=chosen_candidate_id,
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

        # Incorporate forensic verdict into signals and warnings (Semantic Handoff Injection)
        if nav_input.forensic_verdict:
            fv = nav_input.forensic_verdict
            recommendation = fv.get("recommendation", "TRUST")
            reward_flags = fv.get("reward_hacking_flags", [])

            if recommendation == "REJECT" or len(reward_flags) >= 2:
                signals.risk = SignalLevel.HIGH
                signals.uncertainty = SignalLevel.HIGH
                brief.warnings.append(
                    f"Forensic verdict: {recommendation} - claims do not match evidence"
                )
                # Add specific flag warnings
                for flag in reward_flags[:2]:  # Limit to first 2
                    brief.warnings.append(f"Reward hacking detected: {flag}")
                # Consider PAUSE if too many flags
                if len(reward_flags) >= 2 and route.intent != RouteIntent.TERMINATE:
                    route = RouteProposal(
                        intent=RouteIntent.PAUSE,
                        reasoning="Forensic verdict REJECT with multiple reward hacking flags (deterministic)",
                    )
            elif recommendation == "VERIFY" or len(reward_flags) == 1:
                signals.risk = SignalLevel.MEDIUM
                brief.warnings.append(
                    f"Forensic verdict: {recommendation} - verify claims before proceeding"
                )
                if reward_flags:
                    brief.warnings.append(f"Potential issue: {reward_flags[0]}")

        # Determine chosen_candidate_id from routing_candidates if available
        chosen_candidate_id = None
        if nav_input.routing_candidates:
            # Find candidate matching the route
            for candidate in nav_input.routing_candidates:
                if (candidate.get("action") == route.intent.value and
                    candidate.get("target_node") == route.target_node):
                    chosen_candidate_id = candidate.get("candidate_id")
                    break
            # Fall back to default if no match
            if not chosen_candidate_id:
                default_candidates = [
                    c for c in nav_input.routing_candidates if c.get("is_default")
                ]
                if default_candidates:
                    chosen_candidate_id = default_candidates[0].get("candidate_id")

        return NavigatorOutput(
            route=route,
            next_step_brief=brief,
            signals=signals,
            chosen_candidate_id=chosen_candidate_id,
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
        "chosen_candidate_id": output.chosen_candidate_id,
    }

    if output.detour_request:
        result["detour_request"] = {
            "sidequest_id": output.detour_request.sidequest_id,
            "objective": output.detour_request.objective,
            "priority": output.detour_request.priority,
            "resume_at": output.detour_request.resume_at,
        }

    if output.proposed_edge:
        pe_dict = {
            "from_node": output.proposed_edge.from_node,
            "to_node": output.proposed_edge.to_node,
            "why": output.proposed_edge.why,
            "edge_type": output.proposed_edge.edge_type,
            "priority": output.proposed_edge.priority,
            "is_return": output.proposed_edge.is_return,
        }
        if output.proposed_edge.proposed_node:
            pe_dict["proposed_node"] = {
                "template_id": output.proposed_edge.proposed_node.template_id,
                "station_id": output.proposed_edge.proposed_node.station_id,
                "node_id": output.proposed_edge.proposed_node.node_id,
                "objective": output.proposed_edge.proposed_node.objective,
                "params": output.proposed_edge.proposed_node.params,
            }
        result["proposed_edge"] = pe_dict

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

    proposed_edge = None
    if "proposed_edge" in data and data["proposed_edge"]:
        pe = data["proposed_edge"]
        proposed_node = None
        if "proposed_node" in pe and pe["proposed_node"]:
            pn = pe["proposed_node"]
            proposed_node = ProposedNode(
                template_id=pn.get("template_id"),
                station_id=pn.get("station_id"),
                node_id=pn.get("node_id"),
                objective=pn.get("objective", ""),
                params=pn.get("params", {}),
            )
        proposed_edge = ProposedEdge(
            from_node=pe.get("from_node", ""),
            to_node=pe.get("to_node", ""),
            why=pe.get("why", ""),
            edge_type=pe.get("edge_type", "injection"),
            priority=pe.get("priority", 70),
            is_return=pe.get("is_return", True),
            proposed_node=proposed_node,
        )

    return NavigatorOutput(
        route=route,
        next_step_brief=brief,
        signals=signals,
        detour_request=detour_request,
        proposed_edge=proposed_edge,
        chosen_candidate_id=data.get("chosen_candidate_id"),
        elimination_log=data.get("elimination_log", []),
        factors_considered=data.get("factors_considered", []),
    )
