"""
router.py - Routing logic for Claude step engine.

Handles:
- Microloop termination detection
- Router session execution
- Routing signal generation
- Spec-based deterministic routing
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

from swarm.runtime.routing_utils import parse_routing_decision
from swarm.runtime.types import (
    DecisionMetrics,
    DecisionType,
    EdgeOption,
    Elimination,
    LLMReasoning,
    MicroloopContext,
    RoutingCandidate,
    RoutingDecision,
    RoutingExplanation,
    RoutingFactor,
    RoutingSignal,
)
from swarm.spec.types import RoutingConfig, RoutingKind

from ..models import RoutingContext, StepContext

logger = logging.getLogger(__name__)


def _create_deterministic_routing_signal(
    decision: RoutingDecision,
    next_step_id: Optional[str],
    reason: str,
    source: str = "deterministic",
    confidence: float = 1.0,
    needs_human: bool = False,
    loop_count: int = 0,
    exit_condition_met: bool = False,
    route: Optional[str] = None,
    explanation: Optional[RoutingExplanation] = None,
) -> RoutingSignal:
    """Create a RoutingSignal for deterministic routing with complete audit trail.

    This helper ensures all deterministic/fast-path routing decisions populate
    chosen_candidate_id and routing_candidates for consistent audit coverage.
    No routing decision should be a "dark spot" in the audit trail.

    Args:
        decision: The routing decision (advance, loop, terminate, branch).
        next_step_id: Target step ID.
        reason: Human-readable explanation.
        source: Routing source identifier (e.g., "deterministic", "fast_path", "spec_linear").
        confidence: Confidence score (0.0-1.0).
        needs_human: Whether human intervention is required.
        loop_count: Current iteration for microloop tracking.
        exit_condition_met: Whether exit condition was met.
        route: Named route for branch routing.
        explanation: Optional structured explanation.

    Returns:
        RoutingSignal with populated chosen_candidate_id and routing_candidates.
    """
    # Generate deterministic candidate_id based on decision and target
    if decision == RoutingDecision.LOOP:
        candidate_id = f"loop:{next_step_id}:iter_{loop_count}"
    elif decision == RoutingDecision.ADVANCE and next_step_id:
        candidate_id = f"advance:{next_step_id}"
    elif decision == RoutingDecision.TERMINATE:
        candidate_id = "terminate"
    elif decision == RoutingDecision.BRANCH and next_step_id:
        candidate_id = f"branch:{route or next_step_id}"
    else:
        candidate_id = f"{decision.value}:{next_step_id or 'none'}"

    # Create the routing candidate that was implicitly chosen
    chosen_candidate = RoutingCandidate(
        candidate_id=candidate_id,
        action=decision.value,
        target_node=next_step_id,
        reason=reason,
        priority=100,  # Deterministic decisions are highest priority
        source=source,
        is_default=True,
    )

    return RoutingSignal(
        decision=decision,
        next_step_id=next_step_id,
        route=route,
        reason=reason,
        confidence=confidence,
        needs_human=needs_human,
        loop_count=loop_count,
        exit_condition_met=exit_condition_met,
        chosen_candidate_id=candidate_id,
        routing_candidates=[chosen_candidate],
        routing_source=source,
        explanation=explanation,
    )


# Router prompt template for agentic routing decisions with structured JSON output
ROUTER_PROMPT_TEMPLATE = """
You are a routing resolver. Your job is to analyze handoff data and routing configuration to produce a structured routing decision with full reasoning.

## Handoff from Previous Step

```json
{handoff_json}
```

## Step Routing Configuration

```yaml
step_id: {step_id}
flow_key: {flow_key}
routing:
  kind: {routing_kind}
  next: {routing_next}
  loop_target: {loop_target}
  loop_condition_field: {loop_condition_field}
  loop_success_values: {loop_success_values}
  max_iterations: {max_iterations}
  can_further_iteration_help: {can_further_iteration_help}
current_iteration: {current_iteration}
```

## Available Edges
{available_edges_json}

## Decision Logic

### Linear Flow
- If `loop_target` is reached and `success_values` contains the target value -> **"advance"**
- If `loop_target` is not reached but `max_iterations` is exhausted -> **"loop"**
- If `loop_target` is not reached and `can_further_iteration_help` is false -> **"terminate"**

### Microloop Flow
- If `success_values` contains the current status value -> **"advance"** (exit loop)
- If `max_iterations` is exhausted -> **"advance"** (exit with documented concerns)
- If `can_further_iteration_help` is false -> **"advance"** (exit loop, no viable fix path)
- Otherwise if UNVERIFIED and iterations < max -> **"loop"** back to loop_target

### Branching Flow
- If explicit user routing hint exists in handoff text -> **"branch"** with the specified step_id

### Default
- If no conditions met -> **"advance"** with `next_step_id: null`

## Output Format

Output ONLY a valid JSON object with this structure (no markdown, no explanation):

```json
{{
  "decision": "advance" | "loop" | "terminate" | "branch",
  "next_step_id": "<step_id or null>",
  "route": null,
  "reason": "<one-sentence explanation for this routing decision>",
  "confidence": <0.0 to 1.0>,
  "needs_human": <true | false>,
  "reasoning": {{
    "factors_considered": [
      {{
        "name": "<factor name, max 50 chars>",
        "impact": "strongly_favors" | "favors" | "neutral" | "against" | "strongly_against",
        "evidence": "<pointer to supporting data, max 100 chars>",
        "weight": <0.0 to 1.0>
      }}
    ],
    "option_scores": {{
      "<edge_id>": <0.0 to 1.0 score>
    }},
    "primary_justification": "<main reason for selected option, max 300 chars>",
    "risks_identified": [
      {{
        "risk": "<risk description, max 100 chars>",
        "severity": "low" | "medium" | "high",
        "mitigation": "<how to mitigate, max 100 chars>"
      }}
    ],
    "assumptions_made": ["<assumption 1>", "<assumption 2>"]
  }}
}}
```

Analyze the handoff and emit your routing decision with full reasoning now.
"""


# Simple router prompt for backward compatibility
ROUTER_PROMPT_SIMPLE = """
You are a routing resolver. Analyze the handoff and routing config below to decide the next step.

## Handoff
```json
{handoff_json}
```

## Routing Config
- kind: {routing_kind}
- next: {routing_next}
- loop_target: {loop_target}
- success_values: {loop_success_values}
- max_iterations: {max_iterations}
- current_iteration: {current_iteration}

Output ONLY a JSON object:
```json
{{
  "decision": "advance" | "loop" | "terminate" | "branch",
  "next_step_id": "<step_id or null>",
  "reason": "<why>",
  "confidence": <0.0 to 1.0>,
  "needs_human": <true | false>
}}
```
"""


def load_resolver_template(repo_root: Optional[Path], resolver_name: str) -> Optional[str]:
    """Load resolver template from swarm/prompts/resolvers/*.md.

    Resolver templates provide customizable prompts for specific routing/decision
    tasks. If a template exists, it is used instead of the hardcoded prompt.

    Args:
        repo_root: Repository root path.
        resolver_name: The resolver name (e.g., "routing_signal").

    Returns:
        The resolver template content, or None if not found.
    """
    if not repo_root:
        return None

    resolver_path = Path(repo_root) / "swarm" / "prompts" / "resolvers" / f"{resolver_name}.md"
    if not resolver_path.exists():
        logger.debug("Resolver template not found: %s", resolver_path)
        return None

    try:
        content = resolver_path.read_text(encoding="utf-8")

        # Strip YAML frontmatter (between --- markers) if present
        if content.startswith("---"):
            end_marker = content.find("---", 3)
            if end_marker != -1:
                body_start = end_marker + 3
                if body_start < len(content) and content[body_start] == "\n":
                    body_start += 1
                content = content[body_start:]

        logger.debug("Loaded resolver template: %s", resolver_path)
        return content.strip()

    except (OSError, IOError) as e:
        logger.warning("Failed to load resolver template %s: %s", resolver_name, e)
        return None


def check_microloop_termination(
    handoff_data: Dict[str, Any],
    routing_config: Dict[str, Any],
    current_iteration: int,
) -> Optional[RoutingSignal]:
    """Check if microloop should terminate based on resolver spec logic.

    This implements the microloop termination logic from routing_signal.md:
    1. Check if loop_target reached with success_values
    2. Check if max_iterations exhausted
    3. Check if can_further_iteration_help is false in handoff

    Args:
        handoff_data: The handoff JSON from JIT finalization.
        routing_config: The step's routing configuration from extra.routing.
        current_iteration: Current loop iteration count.

    Returns:
        RoutingSignal if termination condition met, None to continue looping.
    """
    # Extract routing configuration
    # Note: loop_target is defined in routing config but routing uses success_values + max_iterations
    success_values = routing_config.get("loop_success_values", ["VERIFIED"])
    max_iterations = routing_config.get("max_iterations", 3)
    loop_condition_field = routing_config.get("loop_condition_field", "status")

    # Get the current status from handoff
    current_status = handoff_data.get(loop_condition_field, "").upper()

    # Check can_further_iteration_help from handoff (explicit signal from critic)
    can_further_help = handoff_data.get("can_further_iteration_help", True)
    if isinstance(can_further_help, str):
        can_further_help = can_further_help.lower() in ("yes", "true", "1")

    # Condition 1: Success status reached - exit loop with ADVANCE
    if current_status in [s.upper() for s in success_values]:
        return _create_deterministic_routing_signal(
            decision=RoutingDecision.ADVANCE,
            next_step_id=None,  # Orchestrator determines next step
            reason=f"Loop target reached: {loop_condition_field}={current_status}",
            source="microloop_termination",
            exit_condition_met=True,
            loop_count=current_iteration,
        )

    # Condition 2: Max iterations exhausted - exit loop with ADVANCE
    if current_iteration >= max_iterations:
        return _create_deterministic_routing_signal(
            decision=RoutingDecision.ADVANCE,
            next_step_id=None,
            reason=f"Max iterations reached ({current_iteration}/{max_iterations}), exiting with documented concerns",
            source="microloop_termination",
            confidence=0.7,
            needs_human=True,  # Human should review incomplete work
            loop_count=current_iteration,
            exit_condition_met=True,
        )

    # Condition 3: can_further_iteration_help is false - exit loop
    if not can_further_help:
        return _create_deterministic_routing_signal(
            decision=RoutingDecision.ADVANCE,
            next_step_id=None,
            reason="Critic indicated no further iteration can help, exiting loop",
            source="microloop_termination",
            confidence=0.8,
            needs_human=True,  # Human should review why iteration was not helpful
            loop_count=current_iteration,
            exit_condition_met=True,
        )

    # No termination condition met - return None to continue looping
    return None


async def run_router_session(
    handoff_data: Dict[str, Any],
    ctx: StepContext,
    cwd: str,
    model: Optional[str] = None,
) -> Optional[RoutingSignal]:
    """Run a lightweight router session to decide the next step.

    This is a fresh, short-lived session that analyzes the handoff
    and produces a routing decision. Uses resolver template if available,
    otherwise falls back to ROUTER_PROMPT_TEMPLATE.

    Uses the unified claude_sdk adapter for SDK access.

    Args:
        handoff_data: The handoff JSON from JIT finalization.
        ctx: Step execution context with routing configuration.
        cwd: Working directory for the session.
        model: Model to use for routing session (from spec).

    Returns:
        RoutingSignal if routing was determined, None if routing failed.
    """
    from swarm.runtime.claude_sdk import create_high_trust_options, get_sdk_module

    sdk = get_sdk_module()
    query = sdk.query

    # Extract routing config from context
    routing = ctx.routing or RoutingContext()
    routing_config = ctx.extra.get("routing", {})
    current_iteration = routing.loop_iteration
    routing_kind = routing_config.get("kind", "linear")

    # For microloops, check termination conditions before LLM call
    if routing_kind == "microloop":
        termination_signal = check_microloop_termination(
            handoff_data=handoff_data,
            routing_config=routing_config,
            current_iteration=current_iteration,
        )
        if termination_signal:
            logger.debug(
                "Microloop termination detected for step %s: %s",
                ctx.step_id,
                termination_signal.reason,
            )
            return termination_signal

    # Try to load resolver template, fall back to hardcoded template
    resolver_template = load_resolver_template(ctx.repo_root, "routing_signal")

    # Prepare template variables
    template_vars = {
        "handoff_json": json.dumps(handoff_data, indent=2),
        "step_id": ctx.step_id,
        "flow_key": ctx.flow_key,
        "routing_kind": routing_kind,
        "routing_next": routing_config.get("next", "null"),
        "loop_target": routing_config.get("loop_target", "null"),
        "loop_condition_field": routing_config.get("loop_condition_field", "status"),
        "loop_success_values": routing_config.get("loop_success_values", ["VERIFIED"]),
        "max_iterations": routing_config.get("max_iterations", 3),
        "can_further_iteration_help": handoff_data.get("can_further_iteration_help", True),
        "current_iteration": current_iteration,
    }

    # Build router prompt from resolver template or fallback
    if resolver_template:
        router_prompt = f"""
## Handoff from Previous Step

```json
{template_vars["handoff_json"]}
```

## Step Routing Configuration

```yaml
step_id: {template_vars["step_id"]}
flow_key: {template_vars["flow_key"]}
routing:
  kind: {template_vars["routing_kind"]}
  next: {template_vars["routing_next"]}
  loop_target: {template_vars["loop_target"]}
  loop_condition_field: {template_vars["loop_condition_field"]}
  loop_success_values: {template_vars["loop_success_values"]}
  max_iterations: {template_vars["max_iterations"]}
  can_further_iteration_help: {template_vars["can_further_iteration_help"]}
current_iteration: {template_vars["current_iteration"]}
```

{resolver_template}
"""
        logger.debug("Using resolver template for routing")
    else:
        router_prompt = ROUTER_PROMPT_TEMPLATE.format(**template_vars)
        logger.debug("Using fallback ROUTER_PROMPT_TEMPLATE for routing")

    # Router uses minimal options via adapter, with spec model for consistency
    options = create_high_trust_options(
        cwd=cwd,
        permission_mode="bypassPermissions",
        model=model,  # Use spec model if available, otherwise SDK default
    )

    # Collect router response
    router_response = ""

    try:
        logger.debug("Starting router session for step %s", ctx.step_id)

        async for event in query(
            prompt=router_prompt,
            options=options,
        ):
            # Extract text content from messages
            if hasattr(event, "message"):
                message = getattr(event, "message", event)
                content = getattr(message, "content", "")
                if isinstance(content, list):
                    text_parts = [
                        getattr(b, "text", str(getattr(b, "content", ""))) for b in content
                    ]
                    content = "\n".join(text_parts)
                if content:
                    router_response += content

        logger.debug("Router session complete, parsing response")

        # Parse JSON from response (may be wrapped in markdown)
        json_match = None
        if "```json" in router_response:
            start = router_response.find("```json") + 7
            end = router_response.find("```", start)
            if end > start:
                json_match = router_response[start:end].strip()
        elif "```" in router_response:
            start = router_response.find("```") + 3
            end = router_response.find("```", start)
            if end > start:
                json_match = router_response[start:end].strip()
        else:
            json_match = router_response.strip()

        if not json_match:
            logger.warning("Router response contained no parseable JSON")
            return None

        routing_data = json.loads(json_match)

        # Map decision string to enum using centralized parsing
        decision_str = routing_data.get("decision", "advance")
        decision = parse_routing_decision(decision_str)

        # Build LLMReasoning from structured response if present
        llm_reasoning = None
        reasoning_data = routing_data.get("reasoning", {})
        if reasoning_data:
            factors = [
                RoutingFactor(
                    name=f.get("name", ""),
                    impact=f.get("impact", "neutral"),
                    evidence=f.get("evidence"),
                    weight=float(f.get("weight", 0.5)),
                )
                for f in reasoning_data.get("factors_considered", [])
            ]
            llm_reasoning = LLMReasoning(
                model_used="claude",  # SDK doesn't expose model easily
                prompt_hash=routing_data.get("prompt_hash", ""),
                response_time_ms=0,  # Would need timing wrapper
                factors_considered=factors,
                option_scores=reasoning_data.get("option_scores", {}),
                primary_justification=reasoning_data.get("primary_justification", ""),
                risks_identified=reasoning_data.get("risks_identified", []),
                assumptions_made=reasoning_data.get("assumptions_made", []),
            )

        # Build explanation
        from datetime import datetime, timezone

        next_step_id = routing_data.get("next_step_id")
        route = routing_data.get("route")
        reason = routing_data.get("reason", "")
        confidence = float(routing_data.get("confidence", 0.7))
        needs_human = bool(routing_data.get("needs_human", False))

        explanation = RoutingExplanation(
            decision_type=DecisionType.LLM_TIEBREAKER,
            selected_target=next_step_id or "",
            timestamp=datetime.now(timezone.utc),
            confidence=confidence,
            reasoning_summary=reason[:200],
            llm_reasoning=llm_reasoning,
            metrics=DecisionMetrics(llm_calls=1),
        )

        # Generate candidate_id for LLM-based routing (consistent audit trail)
        if decision == RoutingDecision.LOOP:
            candidate_id = f"loop:{next_step_id}"
        elif decision == RoutingDecision.ADVANCE and next_step_id:
            candidate_id = f"advance:{next_step_id}"
        elif decision == RoutingDecision.TERMINATE:
            candidate_id = "terminate"
        elif decision == RoutingDecision.BRANCH and next_step_id:
            candidate_id = f"branch:{route or next_step_id}"
        else:
            candidate_id = f"{decision.value}:{next_step_id or 'none'}"

        # Create routing candidate for audit trail
        chosen_candidate = RoutingCandidate(
            candidate_id=candidate_id,
            action=decision.value,
            target_node=next_step_id,
            reason=reason,
            priority=80,  # LLM decisions have lower priority than deterministic
            source="llm_router_session",
            is_default=False,
        )

        return RoutingSignal(
            decision=decision,
            next_step_id=next_step_id,
            route=route,
            reason=reason,
            confidence=confidence,
            needs_human=needs_human,
            explanation=explanation,
            chosen_candidate_id=candidate_id,
            routing_candidates=[chosen_candidate],
            routing_source="llm_router_session",
        )

    except json.JSONDecodeError as e:
        logger.warning("Failed to parse router response as JSON: %s", e)
        logger.debug("Router response was: %s", router_response[:500])
        return None
    except Exception as e:
        logger.warning("Router session failed: %s", e)
        return None


def route_step_stub(
    ctx: StepContext,
    handoff_data: Dict[str, Any],
) -> Optional[RoutingSignal]:
    """Stub implementation of route_step for testing.

    Uses deterministic routing based on routing config from ctx.extra.
    This allows testing of the orchestrator's routing logic without LLM calls.

    Args:
        ctx: Step execution context.
        handoff_data: Parsed handoff data.

    Returns:
        RoutingSignal with deterministic routing decision.
    """
    routing_config = ctx.extra.get("routing", {})

    # Check for microloop termination
    if routing_config.get("kind") == "microloop":
        status = handoff_data.get("status", "").upper()
        success_values = routing_config.get("loop_success_values", ["VERIFIED"])

        if status in [v.upper() for v in success_values]:
            next_step = routing_config.get("next")
            return _create_deterministic_routing_signal(
                decision=RoutingDecision.ADVANCE,
                next_step_id=next_step,
                reason=f"stub_microloop_exit:{status}",
                source="stub",
                exit_condition_met=True,
            )

        # Check can_further_iteration_help
        can_help = handoff_data.get("can_further_iteration_help", "no")
        if isinstance(can_help, str) and can_help.lower() == "no":
            next_step = routing_config.get("next")
            return _create_deterministic_routing_signal(
                decision=RoutingDecision.ADVANCE,
                next_step_id=next_step,
                reason="stub_microloop_no_further_help",
                source="stub",
                exit_condition_met=True,
            )

    # Default: advance to next step
    next_step = routing_config.get("next")
    if next_step:
        return _create_deterministic_routing_signal(
            decision=RoutingDecision.ADVANCE,
            next_step_id=next_step,
            reason="stub_linear_advance",
            source="stub",
        )

    # No next step - terminate flow
    return _create_deterministic_routing_signal(
        decision=RoutingDecision.TERMINATE,
        reason="stub_flow_complete",
        confidence=1.0,
        needs_human=False,
    )


def route_from_routing_config(
    routing_config: RoutingConfig,
    handoff_status: str,
    iteration_count: int = 0,
) -> Optional[RoutingSignal]:
    """Interpret RoutingConfig from specs to produce RoutingSignal.

    This function provides deterministic routing based on the spec-first
    architecture. It enables routing decisions without requiring an LLM call
    for cases where the routing logic is fully specified in the flow spec.

    Args:
        routing_config: The RoutingConfig from the step's FlowStep.routing.
        handoff_status: The status value from the handoff (e.g., "VERIFIED", "UNVERIFIED").
        iteration_count: Current iteration count for microloop tracking (0-based).

    Returns:
        RoutingSignal if routing can be determined deterministically,
        None if routing requires LLM decision (e.g., ambiguous branch conditions).

    Examples:
        >>> config = RoutingConfig(kind=RoutingKind.TERMINAL)
        >>> signal = route_from_routing_config(config, "VERIFIED")
        >>> signal.decision
        <RoutingDecision.TERMINATE: 'terminate'>

        >>> config = RoutingConfig(kind=RoutingKind.LINEAR, next="step_2")
        >>> signal = route_from_routing_config(config, "succeeded")
        >>> signal.next_step_id
        'step_2'
    """
    # Normalize handoff status for comparison (handle case variations)
    normalized_status = handoff_status.upper() if handoff_status else ""

    # Handle terminal routing - always terminates
    if routing_config.kind == RoutingKind.TERMINAL:
        return _create_deterministic_routing_signal(
            decision=RoutingDecision.TERMINATE,
            next_step_id=None,
            reason="spec_terminal",
            source="spec_routing",
        )

    # Handle linear routing - advances to next step or terminates
    if routing_config.kind == RoutingKind.LINEAR:
        if routing_config.next:
            return _create_deterministic_routing_signal(
                decision=RoutingDecision.ADVANCE,
                next_step_id=routing_config.next,
                reason="spec_linear",
                source="spec_routing",
            )
        # Linear with no next step means flow complete
        return _create_deterministic_routing_signal(
            decision=RoutingDecision.TERMINATE,
            next_step_id=None,
            reason="spec_linear_no_next",
            source="spec_routing",
        )

    # Handle microloop routing - checks success, max iterations, or loops back
    if routing_config.kind == RoutingKind.MICROLOOP:
        # Normalize success values for comparison
        success_values_upper = tuple(v.upper() for v in routing_config.loop_success_values)

        # Check if success condition met
        if normalized_status in success_values_upper:
            return _create_deterministic_routing_signal(
                decision=RoutingDecision.ADVANCE,
                next_step_id=routing_config.next,
                reason="spec_microloop_verified",
                source="spec_routing",
                exit_condition_met=True,
                loop_count=iteration_count,
            )

        # Check if max iterations reached
        if iteration_count >= routing_config.max_iterations:
            return _create_deterministic_routing_signal(
                decision=RoutingDecision.ADVANCE,
                next_step_id=routing_config.next,
                reason="spec_microloop_max_iterations",
                source="spec_routing",
                confidence=0.7,
                needs_human=True,  # Human should review incomplete work
                exit_condition_met=True,
                loop_count=iteration_count,
            )

        # Loop back to target
        return _create_deterministic_routing_signal(
            decision=RoutingDecision.LOOP,
            next_step_id=routing_config.loop_target,
            reason="spec_microloop_continue",
            source="spec_routing",
            loop_count=iteration_count + 1,
        )

    # Handle branch routing - routes based on status matching branches
    if routing_config.kind == RoutingKind.BRANCH:
        # Check if status matches any branch
        if routing_config.branches:
            # Try exact match first
            if handoff_status in routing_config.branches:
                return _create_deterministic_routing_signal(
                    decision=RoutingDecision.BRANCH,
                    next_step_id=routing_config.branches[handoff_status],
                    reason="spec_branch",
                    source="spec_routing",
                    route=handoff_status,
                )
            # Try case-insensitive match
            for branch_key, branch_target in routing_config.branches.items():
                if branch_key.upper() == normalized_status:
                    return _create_deterministic_routing_signal(
                        decision=RoutingDecision.BRANCH,
                        next_step_id=branch_target,
                        reason="spec_branch",
                        source="spec_routing",
                        route=branch_key,
                    )

        # Fallback to next if no matching branch
        if routing_config.next:
            return _create_deterministic_routing_signal(
                decision=RoutingDecision.ADVANCE,
                next_step_id=routing_config.next,
                reason="spec_branch_default",
                source="spec_routing",
                confidence=0.8,
            )

    # Routing cannot be determined deterministically - requires LLM decision
    return None


def smart_route(
    routing_config: RoutingConfig,
    handoff_data: Dict[str, Any],
    iteration_count: int = 0,
    available_edges: Optional[list] = None,
) -> RoutingSignal:
    """Smart routing with structured JSON explanation.

    Implements priority-based routing with full audit trail:
    1. Exit conditions (VERIFIED status, max iterations)
    2. Deterministic spec routing
    3. Branch matching
    4. LLM tie-breaker (if multiple valid options)

    Args:
        routing_config: The RoutingConfig from the step's FlowStep.routing.
        handoff_data: The handoff data including status and other fields.
        iteration_count: Current iteration count for microloop tracking.
        available_edges: Optional list of available edges for audit trail.

    Returns:
        RoutingSignal with populated explanation field.
    """
    import time
    from datetime import datetime, timezone

    start_time = time.time()
    handoff_status = handoff_data.get("status", "")
    normalized_status = handoff_status.upper() if handoff_status else ""
    elimination_log = []
    edges_considered = []

    # Build edge options from routing config
    if available_edges:
        edges_considered = [
            EdgeOption(
                edge_id=e.get("edge_id", f"edge_{i}"),
                target_node=e.get("to", ""),
                edge_type=e.get("type", "sequence"),
                priority=e.get("priority", 50),
            )
            for i, e in enumerate(available_edges)
        ]
    elif routing_config.next:
        edges_considered = [
            EdgeOption(
                edge_id="primary",
                target_node=routing_config.next,
                edge_type="sequence",
                priority=0,
            )
        ]
        if routing_config.loop_target:
            edges_considered.append(
                EdgeOption(
                    edge_id="loop",
                    target_node=routing_config.loop_target,
                    edge_type="loop",
                    priority=10,
                )
            )

    # Build microloop context if applicable
    microloop_ctx = None
    if routing_config.kind == RoutingKind.MICROLOOP:
        microloop_ctx = MicroloopContext(
            iteration=iteration_count + 1,
            max_iterations=routing_config.max_iterations,
            loop_target=routing_config.loop_target or "",
            exit_status=normalized_status,
            can_further_iteration_help=handoff_data.get("can_further_iteration_help", True),
        )

    # Priority 1: Check for exit conditions (deterministic)
    if routing_config.kind == RoutingKind.TERMINAL:
        elapsed_ms = int((time.time() - start_time) * 1000)
        return _create_deterministic_routing_signal(
            decision=RoutingDecision.TERMINATE,
            next_step_id=None,
            reason="spec_terminal",
            source="smart_route",
            explanation=RoutingExplanation(
                decision_type=DecisionType.EXIT_CONDITION,
                selected_target="",
                timestamp=datetime.now(timezone.utc),
                confidence=1.0,
                reasoning_summary="Terminal step, flow complete",
                available_edges=edges_considered,
                elimination_log=elimination_log,
                microloop_context=microloop_ctx,
                metrics=DecisionMetrics(
                    total_time_ms=elapsed_ms,
                    edges_total=len(edges_considered),
                    edges_eliminated=len(elimination_log),
                ),
            ),
        )

    # Priority 2: Check microloop success condition
    if routing_config.kind == RoutingKind.MICROLOOP:
        success_values_upper = tuple(v.upper() for v in routing_config.loop_success_values)

        if normalized_status in success_values_upper:
            elapsed_ms = int((time.time() - start_time) * 1000)
            # Mark loop edge as eliminated
            for e in edges_considered:
                if e.edge_type == "loop":
                    elimination_log.append(
                        Elimination(
                            edge_id=e.edge_id,
                            reason_code="exit_condition_met",
                            detail=f"Status {normalized_status} matches success values",
                        )
                    )
                else:
                    e.evaluated_result = True
                    e.score = 1.0

            return _create_deterministic_routing_signal(
                decision=RoutingDecision.ADVANCE,
                next_step_id=routing_config.next,
                reason="spec_microloop_verified",
                source="smart_route",
                exit_condition_met=True,
                loop_count=iteration_count,
                explanation=RoutingExplanation(
                    decision_type=DecisionType.EXIT_CONDITION,
                    selected_target=routing_config.next or "",
                    timestamp=datetime.now(timezone.utc),
                    confidence=1.0,
                    reasoning_summary=f"Microloop exit: status {normalized_status} matches success condition",
                    available_edges=edges_considered,
                    elimination_log=elimination_log,
                    microloop_context=microloop_ctx,
                    metrics=DecisionMetrics(
                        total_time_ms=elapsed_ms,
                        edges_total=len(edges_considered),
                        edges_eliminated=len(elimination_log),
                    ),
                ),
            )

        # Check max iterations
        if iteration_count >= routing_config.max_iterations:
            elapsed_ms = int((time.time() - start_time) * 1000)
            for e in edges_considered:
                if e.edge_type == "loop":
                    elimination_log.append(
                        Elimination(
                            edge_id=e.edge_id,
                            reason_code="max_iterations",
                            detail=f"Iteration {iteration_count + 1} >= max {routing_config.max_iterations}",
                        )
                    )

            return _create_deterministic_routing_signal(
                decision=RoutingDecision.ADVANCE,
                next_step_id=routing_config.next,
                reason="spec_microloop_max_iterations",
                source="smart_route",
                confidence=0.7,
                needs_human=True,
                exit_condition_met=True,
                loop_count=iteration_count,
                explanation=RoutingExplanation(
                    decision_type=DecisionType.EXIT_CONDITION,
                    selected_target=routing_config.next or "",
                    timestamp=datetime.now(timezone.utc),
                    confidence=0.7,
                    reasoning_summary=f"Max iterations reached ({iteration_count + 1}/{routing_config.max_iterations})",
                    available_edges=edges_considered,
                    elimination_log=elimination_log,
                    microloop_context=microloop_ctx,
                    metrics=DecisionMetrics(
                        total_time_ms=elapsed_ms,
                        edges_total=len(edges_considered),
                        edges_eliminated=len(elimination_log),
                    ),
                ),
            )

        # Check can_further_iteration_help
        can_help = handoff_data.get("can_further_iteration_help", True)
        if isinstance(can_help, str):
            can_help = can_help.lower() in ("yes", "true", "1")
        if not can_help:
            elapsed_ms = int((time.time() - start_time) * 1000)
            for e in edges_considered:
                if e.edge_type == "loop":
                    elimination_log.append(
                        Elimination(
                            edge_id=e.edge_id,
                            reason_code="status_mismatch",
                            detail="Critic indicated no further iteration can help",
                        )
                    )

            return _create_deterministic_routing_signal(
                decision=RoutingDecision.ADVANCE,
                next_step_id=routing_config.next,
                reason="spec_microloop_no_further_help",
                source="smart_route",
                confidence=0.8,
                needs_human=True,
                exit_condition_met=True,
                loop_count=iteration_count,
                explanation=RoutingExplanation(
                    decision_type=DecisionType.EXIT_CONDITION,
                    selected_target=routing_config.next or "",
                    timestamp=datetime.now(timezone.utc),
                    confidence=0.8,
                    reasoning_summary="Critic judged no further iteration can help",
                    available_edges=edges_considered,
                    elimination_log=elimination_log,
                    microloop_context=microloop_ctx,
                    metrics=DecisionMetrics(
                        total_time_ms=elapsed_ms,
                        edges_total=len(edges_considered),
                        edges_eliminated=len(elimination_log),
                    ),
                ),
            )

        # Continue looping
        elapsed_ms = int((time.time() - start_time) * 1000)
        for e in edges_considered:
            if e.edge_type != "loop":
                elimination_log.append(
                    Elimination(
                        edge_id=e.edge_id,
                        reason_code="condition_false",
                        detail=f"Status {normalized_status} not in success values, loop continues",
                    )
                )

        return _create_deterministic_routing_signal(
            decision=RoutingDecision.LOOP,
            next_step_id=routing_config.loop_target,
            reason="spec_microloop_continue",
            source="smart_route",
            loop_count=iteration_count + 1,
            explanation=RoutingExplanation(
                decision_type=DecisionType.DETERMINISTIC,
                selected_target=routing_config.loop_target or "",
                timestamp=datetime.now(timezone.utc),
                confidence=1.0,
                reasoning_summary=f"Continuing microloop: iteration {iteration_count + 1}, status {normalized_status}",
                available_edges=edges_considered,
                elimination_log=elimination_log,
                microloop_context=microloop_ctx,
                metrics=DecisionMetrics(
                    total_time_ms=elapsed_ms,
                    edges_total=len(edges_considered),
                    edges_eliminated=len(elimination_log),
                ),
            ),
        )

    # Priority 3: Linear routing
    if routing_config.kind == RoutingKind.LINEAR:
        elapsed_ms = int((time.time() - start_time) * 1000)
        if routing_config.next:
            return _create_deterministic_routing_signal(
                decision=RoutingDecision.ADVANCE,
                next_step_id=routing_config.next,
                reason="spec_linear",
                source="smart_route",
                explanation=RoutingExplanation(
                    decision_type=DecisionType.DETERMINISTIC,
                    selected_target=routing_config.next,
                    timestamp=datetime.now(timezone.utc),
                    confidence=1.0,
                    reasoning_summary="Linear flow: advancing to next step",
                    available_edges=edges_considered,
                    elimination_log=elimination_log,
                    metrics=DecisionMetrics(
                        total_time_ms=elapsed_ms,
                        edges_total=len(edges_considered),
                        edges_eliminated=len(elimination_log),
                    ),
                ),
            )
        return _create_deterministic_routing_signal(
            decision=RoutingDecision.TERMINATE,
            next_step_id=None,
            reason="spec_linear_no_next",
            source="smart_route",
            explanation=RoutingExplanation(
                decision_type=DecisionType.DETERMINISTIC,
                selected_target="",
                timestamp=datetime.now(timezone.utc),
                confidence=1.0,
                reasoning_summary="Linear flow complete: no next step defined",
                available_edges=edges_considered,
                elimination_log=elimination_log,
                metrics=DecisionMetrics(
                    total_time_ms=elapsed_ms,
                    edges_total=len(edges_considered),
                    edges_eliminated=len(elimination_log),
                ),
            ),
        )

    # Priority 4: Branch routing
    if routing_config.kind == RoutingKind.BRANCH and routing_config.branches:
        elapsed_ms = int((time.time() - start_time) * 1000)

        # Try exact match first, then case-insensitive
        matched_target = None
        matched_key = None
        for branch_key, branch_target in routing_config.branches.items():
            if branch_key == handoff_status or branch_key.upper() == normalized_status:
                matched_target = branch_target
                matched_key = branch_key
                break
            else:
                elimination_log.append(
                    Elimination(
                        edge_id=f"branch_{branch_key}",
                        reason_code="condition_false",
                        detail=f"Status '{handoff_status}' != branch key '{branch_key}'",
                    )
                )

        if matched_target:
            return _create_deterministic_routing_signal(
                decision=RoutingDecision.BRANCH,
                next_step_id=matched_target,
                reason="spec_branch",
                source="smart_route",
                route=matched_key,
                explanation=RoutingExplanation(
                    decision_type=DecisionType.DETERMINISTIC,
                    selected_target=matched_target,
                    timestamp=datetime.now(timezone.utc),
                    confidence=1.0,
                    reasoning_summary=f"Branch matched: status '{handoff_status}' -> '{matched_target}'",
                    available_edges=edges_considered,
                    elimination_log=elimination_log,
                    metrics=DecisionMetrics(
                        total_time_ms=elapsed_ms,
                        edges_total=len(edges_considered),
                        edges_eliminated=len(elimination_log),
                    ),
                ),
            )

        # Fallback to next
        if routing_config.next:
            return _create_deterministic_routing_signal(
                decision=RoutingDecision.ADVANCE,
                next_step_id=routing_config.next,
                reason="spec_branch_default",
                source="smart_route",
                confidence=0.8,
                explanation=RoutingExplanation(
                    decision_type=DecisionType.DETERMINISTIC,
                    selected_target=routing_config.next,
                    timestamp=datetime.now(timezone.utc),
                    confidence=0.8,
                    reasoning_summary=f"No branch matched status '{handoff_status}', using default",
                    available_edges=edges_considered,
                    elimination_log=elimination_log,
                    metrics=DecisionMetrics(
                        total_time_ms=elapsed_ms,
                        edges_total=len(edges_considered),
                        edges_eliminated=len(elimination_log),
                    ),
                ),
            )

    # Fallback: routing could not be determined
    elapsed_ms = int((time.time() - start_time) * 1000)
    return _create_deterministic_routing_signal(
        decision=RoutingDecision.TERMINATE,
        next_step_id=None,
        reason="routing_undetermined",
        source="smart_route_fallback",
        confidence=0.5,
        needs_human=True,
        explanation=RoutingExplanation(
            decision_type=DecisionType.ERROR,
            selected_target="",
            timestamp=datetime.now(timezone.utc),
            confidence=0.5,
            reasoning_summary="Could not determine routing from spec",
            available_edges=edges_considered,
            elimination_log=elimination_log,
            microloop_context=microloop_ctx,
            metrics=DecisionMetrics(
                total_time_ms=elapsed_ms,
                edges_total=len(edges_considered),
                edges_eliminated=len(elimination_log),
            ),
        ),
    )
