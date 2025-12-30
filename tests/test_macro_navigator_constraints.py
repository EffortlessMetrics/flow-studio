"""
Tests for MacroNavigator constraint enforcement.

Tests cover:
- ConstraintEvaluator parsing of constraint DSL
- Constraint evaluation against run context
- MacroNavigator integration with constraint checking
- Bounce counting and tracking
"""

import pytest

from swarm.runtime.macro_navigator import (
    ConstraintContext,
    ConstraintEvaluator,
    ConstraintType,
    ConstraintViolation,
    MacroNavigator,
    ParsedConstraint,
    extract_flow_result,
)
from swarm.runtime.types import (
    FlowOutcome,
    FlowResult,
    GateVerdict,
    HumanPolicy,
    MacroAction,
    MacroPolicy,
    MacroRoutingRule,
    RunPlanSpec,
    RunState,
    RoutingDecision,
    RoutingSignal,
    HandoffEnvelope,
)


# =============================================================================
# ConstraintEvaluator Parsing Tests
# =============================================================================


class TestConstraintParsing:
    """Test constraint DSL parsing."""

    def test_parse_never_deploy_unless_merge(self):
        """Parse 'never deploy unless gate verdict is MERGE'."""
        evaluator = ConstraintEvaluator()
        constraint = evaluator.parse_constraint(
            "never deploy unless gate verdict is MERGE"
        )

        assert constraint.constraint_type == ConstraintType.NEVER_UNLESS
        assert constraint.action == "deploy"
        assert "gate verdict is MERGE" in constraint.condition
        assert constraint.raw_text == "never deploy unless gate verdict is MERGE"

    def test_parse_never_deploy_with_or_condition(self):
        """Parse constraint with OR condition."""
        evaluator = ConstraintEvaluator()
        constraint = evaluator.parse_constraint(
            "never deploy unless gate verdict is MERGE or MERGE_WITH_CONDITIONS"
        )

        assert constraint.constraint_type == ConstraintType.NEVER_UNLESS
        assert constraint.action == "deploy"
        assert "MERGE_WITH_CONDITIONS" in constraint.condition

    def test_parse_never_skip_gate(self):
        """Parse 'never skip gate flow'."""
        evaluator = ConstraintEvaluator()
        constraint = evaluator.parse_constraint("never skip gate flow")

        assert constraint.constraint_type == ConstraintType.NEVER_UNLESS
        assert constraint.action == "skip gate flow"

    def test_parse_max_bounces_from_to(self):
        """Parse 'max 3 bounces from gate to build'."""
        evaluator = ConstraintEvaluator()
        constraint = evaluator.parse_constraint("max 3 bounces from gate to build")

        assert constraint.constraint_type == ConstraintType.MAX_COUNT
        assert constraint.action == "bounces"
        assert constraint.count == 3
        assert constraint.source_flow == "gate"
        assert constraint.target_flow == "build"

    def test_parse_max_bounces_between(self):
        """Parse 'max 2 bounces between gate and build'."""
        evaluator = ConstraintEvaluator()
        constraint = evaluator.parse_constraint("max 2 bounces between gate and build")

        assert constraint.constraint_type == ConstraintType.MAX_COUNT
        assert constraint.action == "bounces"
        assert constraint.count == 2
        assert constraint.source_flow == "gate"
        assert constraint.target_flow == "build"

    def test_parse_require_human_approval_after_gate(self):
        """Parse 'require human approval after gate'."""
        evaluator = ConstraintEvaluator()
        constraint = evaluator.parse_constraint("require human approval after gate")

        assert constraint.constraint_type == ConstraintType.REQUIRE_AFTER
        assert "human approval" in constraint.action
        assert constraint.trigger_flow == "gate"

    def test_parse_require_after_flow_number(self):
        """Parse 'require human approval after flow 4'."""
        evaluator = ConstraintEvaluator()
        constraint = evaluator.parse_constraint("require human approval after flow 4")

        assert constraint.constraint_type == ConstraintType.REQUIRE_AFTER
        assert constraint.trigger_flow == "gate"  # flow 4 = gate

    def test_parse_invalid_constraint_raises(self):
        """Invalid constraint string raises ValueError."""
        evaluator = ConstraintEvaluator()

        with pytest.raises(ValueError, match="Cannot parse constraint"):
            evaluator.parse_constraint("this is not a valid constraint")

    def test_parse_case_insensitive(self):
        """Parsing is case-insensitive."""
        evaluator = ConstraintEvaluator()

        # All caps
        c1 = evaluator.parse_constraint(
            "NEVER DEPLOY UNLESS GATE VERDICT IS MERGE"
        )
        assert c1.constraint_type == ConstraintType.NEVER_UNLESS

        # Mixed case
        c2 = evaluator.parse_constraint(
            "Max 3 Bounces From Gate To Build"
        )
        assert c2.constraint_type == ConstraintType.MAX_COUNT


# =============================================================================
# ConstraintEvaluator Evaluation Tests
# =============================================================================


class TestNeverUnlessEvaluation:
    """Test 'never ... unless ...' constraint evaluation."""

    def test_deploy_blocked_without_merge_verdict(self):
        """Deploy is blocked if gate verdict is not MERGE."""
        evaluator = ConstraintEvaluator()
        constraint = evaluator.parse_constraint(
            "never deploy unless gate verdict is MERGE"
        )

        # Gate verdict is BOUNCE_BUILD
        flow_result = FlowResult(
            flow_key="gate",
            outcome=FlowOutcome.BOUNCED,
            gate_verdict=GateVerdict.BOUNCE_BUILD,
        )

        context = ConstraintContext(
            completed_flow="gate",
            flow_result=flow_result,
            next_flow="deploy",
        )

        is_valid, violation = evaluator.evaluate(constraint, context)

        assert not is_valid
        assert violation is not None
        assert "BOUNCE_BUILD" in violation.message
        assert violation.suggested_action == MacroAction.TERMINATE

    def test_deploy_allowed_with_merge_verdict(self):
        """Deploy is allowed if gate verdict is MERGE."""
        evaluator = ConstraintEvaluator()
        constraint = evaluator.parse_constraint(
            "never deploy unless gate verdict is MERGE"
        )

        flow_result = FlowResult(
            flow_key="gate",
            outcome=FlowOutcome.SUCCEEDED,
            gate_verdict=GateVerdict.MERGE,
        )

        context = ConstraintContext(
            completed_flow="gate",
            flow_result=flow_result,
            next_flow="deploy",
        )

        is_valid, violation = evaluator.evaluate(constraint, context)

        assert is_valid
        assert violation is None

    def test_deploy_allowed_with_merge_with_conditions(self):
        """Deploy is allowed if gate verdict is MERGE_WITH_CONDITIONS."""
        evaluator = ConstraintEvaluator()
        constraint = evaluator.parse_constraint(
            "never deploy unless gate verdict is MERGE or MERGE_WITH_CONDITIONS"
        )

        flow_result = FlowResult(
            flow_key="gate",
            outcome=FlowOutcome.SUCCEEDED,
            gate_verdict=GateVerdict.MERGE_WITH_CONDITIONS,
        )

        context = ConstraintContext(
            completed_flow="gate",
            flow_result=flow_result,
            next_flow="deploy",
        )

        is_valid, violation = evaluator.evaluate(constraint, context)

        assert is_valid
        assert violation is None

    def test_constraint_not_applicable_to_other_flows(self):
        """Deploy constraint doesn't apply to non-deploy transitions."""
        evaluator = ConstraintEvaluator()
        constraint = evaluator.parse_constraint(
            "never deploy unless gate verdict is MERGE"
        )

        flow_result = FlowResult(
            flow_key="build",
            outcome=FlowOutcome.SUCCEEDED,
        )

        context = ConstraintContext(
            completed_flow="build",
            flow_result=flow_result,
            next_flow="gate",  # Not deploy
        )

        is_valid, violation = evaluator.evaluate(constraint, context)

        assert is_valid
        assert violation is None

    def test_deploy_blocked_with_no_verdict(self):
        """Deploy is blocked if no gate verdict is available."""
        evaluator = ConstraintEvaluator()
        constraint = evaluator.parse_constraint(
            "never deploy unless gate verdict is MERGE"
        )

        flow_result = FlowResult(
            flow_key="gate",
            outcome=FlowOutcome.SUCCEEDED,
            gate_verdict=None,  # No verdict
        )

        context = ConstraintContext(
            completed_flow="gate",
            flow_result=flow_result,
            next_flow="deploy",
        )

        is_valid, violation = evaluator.evaluate(constraint, context)

        assert not is_valid
        assert violation is not None
        assert "no gate verdict" in violation.message.lower()


class TestMaxCountEvaluation:
    """Test 'max N ...' constraint evaluation."""

    def test_bounce_limit_not_exceeded(self):
        """Under the bounce limit passes constraint."""
        evaluator = ConstraintEvaluator()
        constraint = evaluator.parse_constraint("max 3 bounces from gate to build")

        flow_result = FlowResult(
            flow_key="gate",
            outcome=FlowOutcome.BOUNCED,
            gate_verdict=GateVerdict.BOUNCE_BUILD,
        )

        context = ConstraintContext(
            completed_flow="gate",
            flow_result=flow_result,
            next_flow="build",
            bounce_counts={"gate->build": 2},  # Under limit
        )

        is_valid, violation = evaluator.evaluate(constraint, context)

        assert is_valid
        assert violation is None

    def test_bounce_limit_exceeded(self):
        """At or over the bounce limit fails constraint."""
        evaluator = ConstraintEvaluator()
        constraint = evaluator.parse_constraint("max 3 bounces from gate to build")

        flow_result = FlowResult(
            flow_key="gate",
            outcome=FlowOutcome.BOUNCED,
            gate_verdict=GateVerdict.BOUNCE_BUILD,
        )

        context = ConstraintContext(
            completed_flow="gate",
            flow_result=flow_result,
            next_flow="build",
            bounce_counts={"gate->build": 3},  # At limit
        )

        is_valid, violation = evaluator.evaluate(constraint, context)

        assert not is_valid
        assert violation is not None
        assert "maximum bounces" in violation.message.lower()
        assert violation.suggested_action == MacroAction.TERMINATE

    def test_bounce_counts_both_directions(self):
        """Bounce counts include both directions for 'between' constraints."""
        evaluator = ConstraintEvaluator()
        constraint = evaluator.parse_constraint("max 3 bounces between gate and build")

        flow_result = FlowResult(
            flow_key="gate",
            outcome=FlowOutcome.BOUNCED,
        )

        # 2 bounces gate->build + 2 bounces build->gate = 4 total
        context = ConstraintContext(
            completed_flow="gate",
            flow_result=flow_result,
            next_flow="build",
            bounce_counts={
                "gate->build": 2,
                "build->gate": 2,
            },
        )

        is_valid, violation = evaluator.evaluate(constraint, context)

        assert not is_valid
        assert violation is not None


class TestRequireAfterEvaluation:
    """Test 'require ... after ...' constraint evaluation."""

    def test_human_approval_required_after_gate(self):
        """Human approval is required after gate flow."""
        evaluator = ConstraintEvaluator()
        constraint = evaluator.parse_constraint("require human approval after gate")

        flow_result = FlowResult(
            flow_key="gate",
            outcome=FlowOutcome.SUCCEEDED,
            gate_verdict=GateVerdict.MERGE,
        )

        context = ConstraintContext(
            completed_flow="gate",
            flow_result=flow_result,
            next_flow="deploy",
        )

        is_valid, violation = evaluator.evaluate(constraint, context)

        assert not is_valid
        assert violation is not None
        assert "human approval" in violation.message.lower()
        assert violation.suggested_action == MacroAction.PAUSE

    def test_require_after_not_applicable_to_other_flows(self):
        """Require after constraint only applies to trigger flow."""
        evaluator = ConstraintEvaluator()
        constraint = evaluator.parse_constraint("require human approval after gate")

        flow_result = FlowResult(
            flow_key="build",
            outcome=FlowOutcome.SUCCEEDED,
        )

        context = ConstraintContext(
            completed_flow="build",  # Not gate
            flow_result=flow_result,
            next_flow="gate",
        )

        is_valid, violation = evaluator.evaluate(constraint, context)

        assert is_valid
        assert violation is None


# =============================================================================
# ConstraintEvaluator Violation Message Tests
# =============================================================================


class TestViolationMessages:
    """Test violation message formatting."""

    def test_violation_message_includes_details(self):
        """Violation message includes all relevant details."""
        evaluator = ConstraintEvaluator()

        constraint = ParsedConstraint(
            constraint_type=ConstraintType.NEVER_UNLESS,
            raw_text="never deploy unless gate verdict is MERGE",
            action="deploy",
            condition="gate verdict is MERGE",
        )

        violation = ConstraintViolation(
            constraint=constraint,
            message="Cannot deploy: gate verdict is BOUNCE_BUILD",
            context={
                "gate_verdict": "BOUNCE_BUILD",
                "allowed_verdicts": ["MERGE"],
            },
            suggested_action=MacroAction.TERMINATE,
        )

        message = evaluator.get_violation_message(violation)

        assert "Cannot deploy" in message
        assert "BOUNCE_BUILD" in message
        assert "never deploy unless gate verdict is MERGE" in message
        assert "terminate" in message.lower()


# =============================================================================
# MacroNavigator Integration Tests
# =============================================================================


class TestMacroNavigatorConstraintIntegration:
    """Test MacroNavigator with constraint enforcement."""

    def _create_run_state(self, flow_key: str = "gate") -> RunState:
        """Create a minimal RunState for testing."""
        return RunState(
            run_id="test-run-001",
            flow_key=flow_key,
            status="running",
        )

    def test_navigator_parses_constraints_on_init(self):
        """MacroNavigator parses constraints during initialization."""
        run_plan = RunPlanSpec(
            flow_sequence=["signal", "plan", "build", "gate", "deploy", "wisdom"],
            constraints=[
                "never deploy unless gate verdict is MERGE",
                "max 3 bounces from gate to build",
            ],
        )

        navigator = MacroNavigator(run_plan)

        assert len(navigator.parsed_constraints) == 2
        assert navigator.parsed_constraints[0].constraint_type == ConstraintType.NEVER_UNLESS
        assert navigator.parsed_constraints[1].constraint_type == ConstraintType.MAX_COUNT

    def test_navigator_skips_unparseable_constraints(self):
        """MacroNavigator logs warning for unparseable constraints."""
        run_plan = RunPlanSpec(
            flow_sequence=["signal", "plan", "build", "gate", "deploy", "wisdom"],
            constraints=[
                "never deploy unless gate verdict is MERGE",
                "this is invalid and will be skipped",
            ],
        )

        navigator = MacroNavigator(run_plan)

        # Only one constraint should be parsed
        assert len(navigator.parsed_constraints) == 1

    def test_navigator_blocks_deploy_without_merge(self):
        """Navigator blocks deploy if gate verdict is not MERGE."""
        run_plan = RunPlanSpec(
            flow_sequence=["signal", "plan", "build", "gate", "deploy", "wisdom"],
            macro_policy=MacroPolicy(
                routing_rules=[],  # No routing rules
                default_action=MacroAction.ADVANCE,
            ),
            constraints=[
                "never deploy unless gate verdict is MERGE",
            ],
        )

        navigator = MacroNavigator(run_plan)

        flow_result = FlowResult(
            flow_key="gate",
            outcome=FlowOutcome.SUCCEEDED,
            gate_verdict=GateVerdict.ESCALATE,  # Not MERGE
        )

        run_state = self._create_run_state("gate")

        decision = navigator.route_after_flow("gate", flow_result, run_state)

        assert decision.action == MacroAction.TERMINATE
        assert "Constraint violation" in decision.reason
        assert len(decision.warnings) > 0

    def test_navigator_allows_deploy_with_merge(self):
        """Navigator allows deploy if gate verdict is MERGE."""
        run_plan = RunPlanSpec(
            flow_sequence=["signal", "plan", "build", "gate", "deploy", "wisdom"],
            macro_policy=MacroPolicy(
                routing_rules=[],
                default_action=MacroAction.ADVANCE,
            ),
            constraints=[
                "never deploy unless gate verdict is MERGE",
            ],
        )

        navigator = MacroNavigator(run_plan)

        flow_result = FlowResult(
            flow_key="gate",
            outcome=FlowOutcome.SUCCEEDED,
            gate_verdict=GateVerdict.MERGE,
        )

        run_state = self._create_run_state("gate")

        decision = navigator.route_after_flow("gate", flow_result, run_state)

        assert decision.action == MacroAction.ADVANCE
        assert decision.next_flow == "deploy"

    def test_navigator_tracks_bounces(self):
        """Navigator tracks bounce counts between flows."""
        run_plan = RunPlanSpec(
            flow_sequence=["signal", "plan", "build", "gate", "deploy", "wisdom"],
            macro_policy=MacroPolicy(
                routing_rules=[
                    MacroRoutingRule(
                        rule_id="gate-bounce-build",
                        condition="gate.verdict == 'BOUNCE_BUILD'",
                        action=MacroAction.GOTO,
                        target_flow="build",
                        max_uses=10,
                    ),
                ],
            ),
            constraints=[],
        )

        navigator = MacroNavigator(run_plan)

        flow_result = FlowResult(
            flow_key="gate",
            outcome=FlowOutcome.BOUNCED,
            gate_verdict=GateVerdict.BOUNCE_BUILD,
        )

        run_state = self._create_run_state("gate")

        # First bounce
        navigator.route_after_flow("gate", flow_result, run_state)
        assert navigator.bounce_counts.get("gate->build", 0) == 1

        # Second bounce
        navigator.route_after_flow("gate", flow_result, run_state)
        assert navigator.bounce_counts.get("gate->build", 0) == 2

    def test_navigator_enforces_max_bounces(self):
        """Navigator enforces max bounce limit."""
        run_plan = RunPlanSpec(
            flow_sequence=["signal", "plan", "build", "gate", "deploy", "wisdom"],
            macro_policy=MacroPolicy(
                routing_rules=[
                    MacroRoutingRule(
                        rule_id="gate-bounce-build",
                        condition="gate.verdict == 'BOUNCE_BUILD'",
                        action=MacroAction.GOTO,
                        target_flow="build",
                        max_uses=10,
                    ),
                ],
            ),
            constraints=[
                "max 2 bounces from gate to build",
            ],
        )

        # Start with 2 bounces already
        navigator = MacroNavigator(
            run_plan,
            bounce_counts={"gate->build": 2},
        )

        flow_result = FlowResult(
            flow_key="gate",
            outcome=FlowOutcome.BOUNCED,
            gate_verdict=GateVerdict.BOUNCE_BUILD,
        )

        run_state = self._create_run_state("gate")

        decision = navigator.route_after_flow("gate", flow_result, run_state)

        assert decision.action == MacroAction.TERMINATE
        assert "Constraint violation" in decision.reason
        assert "bounces" in decision.reason.lower()

    def test_navigator_serialization_includes_bounce_counts(self):
        """Navigator serialization includes bounce counts."""
        run_plan = RunPlanSpec.default()
        navigator = MacroNavigator(
            run_plan,
            flow_execution_counts={"gate": 3},
            bounce_counts={"gate->build": 2},
        )

        data = navigator.to_dict()

        assert "bounce_counts" in data
        assert data["bounce_counts"] == {"gate->build": 2}

    def test_navigator_deserialization_restores_bounce_counts(self):
        """Navigator deserialization restores bounce counts."""
        run_plan = RunPlanSpec.default()

        data = {
            "flow_execution_counts": {"gate": 3},
            "total_flow_executions": 3,
            "routing_history": [],
            "bounce_counts": {"gate->build": 2, "gate->plan": 1},
        }

        navigator = MacroNavigator.from_dict(data, run_plan)

        assert navigator.bounce_counts == {"gate->build": 2, "gate->plan": 1}


class TestMultipleConstraints:
    """Test evaluation of multiple constraints."""

    def test_most_severe_violation_wins(self):
        """When multiple constraints violated, most severe action is used."""
        run_plan = RunPlanSpec(
            flow_sequence=["signal", "plan", "build", "gate", "deploy", "wisdom"],
            macro_policy=MacroPolicy(routing_rules=[]),
            constraints=[
                "never deploy unless gate verdict is MERGE",  # TERMINATE
                "require human approval after gate",  # PAUSE
            ],
        )

        navigator = MacroNavigator(run_plan)

        flow_result = FlowResult(
            flow_key="gate",
            outcome=FlowOutcome.SUCCEEDED,
            gate_verdict=GateVerdict.ESCALATE,  # Violates first constraint
        )

        run_state = RunState(
            run_id="test-run-001",
            flow_key="gate",
            status="running",
        )

        decision = navigator.route_after_flow("gate", flow_result, run_state)

        # TERMINATE is more severe than PAUSE
        assert decision.action == MacroAction.TERMINATE
        # Both violations should be in warnings
        assert len(decision.warnings) == 2
