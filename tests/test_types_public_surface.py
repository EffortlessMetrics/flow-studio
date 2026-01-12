"""Public surface and serialization roundtrip tests for swarm.runtime.types.

These tests serve as guardrails during the modularization of types.py into
a package. They ensure:
1. All public symbols remain importable from swarm.runtime.types
2. Serialization roundtrips preserve data integrity
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest


class TestPublicSurfaceImports:
    """Verify all public symbols are importable from swarm.runtime.types."""

    def test_type_aliases(self) -> None:
        """Test type aliases are importable."""
        from swarm.runtime.types import BackendId, RunId

        # These are type aliases, just verify they exist
        assert RunId is not None
        assert BackendId is not None

    def test_enums(self) -> None:
        """Test all enums are importable."""
        from swarm.runtime.types import (
            AssumptionStatus,
            ConfidenceLevel,
            DecisionType,
            FlowOutcome,
            GateVerdict,
            MacroAction,
            ObservationPriority,
            ObservationType,
            RoutingDecision,
            RoutingMode,
            RunStatus,
            SDLCStatus,
        )

        # Verify enum values exist
        assert RunStatus.PENDING.value == "pending"
        assert SDLCStatus.OK.value == "ok"
        assert RoutingDecision.ADVANCE.value == "advance"
        assert DecisionType.EXPLICIT.value == "explicit"
        assert RoutingMode.ASSIST.value == "assist"
        assert ConfidenceLevel.HIGH.value == "high"
        assert AssumptionStatus.ACTIVE.value == "active"
        assert ObservationType.ACTION_TAKEN.value == "action_taken"
        assert ObservationPriority.LOW.value == "low"
        assert MacroAction.ADVANCE.value == "advance"
        assert GateVerdict.MERGE.value == "MERGE"
        assert FlowOutcome.SUCCEEDED.value == "succeeded"

    def test_typed_dicts(self) -> None:
        """Test TypedDicts are importable."""
        from swarm.runtime.types import SkipJustification, StationOpinion

        # Verify they're usable as types
        assert StationOpinion is not None
        assert SkipJustification is not None

    def test_dataclasses(self) -> None:
        """Test all dataclasses are importable."""
        from swarm.runtime.types import (
            AssumptionEntry,
            BackendCapabilities,
            CELEvaluation,
            DecisionLogEntry,
            DecisionMetrics,
            EdgeOption,
            Elimination,
            FlowResult,
            HandoffEnvelope,
            HumanPolicy,
            InjectedNode,
            InjectedNodeSpec,
            InterruptionFrame,
            LLMReasoning,
            MacroPolicy,
            MacroRoutingDecision,
            MacroRoutingRule,
            MicroloopContext,
            ObservationEntry,
            ResumePoint,
            RoutingCandidate,
            RoutingDecision,
            RoutingExplanation,
            RoutingFactor,
            RoutingSignal,
            RunEvent,
            RunPlanSpec,
            RunSpec,
            RunState,
            RunSummary,
            WhyNowJustification,
            WP4EliminationEntry,
            WP4RoutingExplanation,
            WP4RoutingMetrics,
        )

        # Spot-check instantiation
        assert RunSpec(flow_keys=["signal"]).flow_keys == ["signal"]
        assert RoutingSignal(decision=RoutingDecision.ADVANCE).decision == RoutingDecision.ADVANCE

    def test_functions(self) -> None:
        """Test all public functions are importable."""
        from swarm.runtime.types import (
            assumption_entry_from_dict,
            assumption_entry_to_dict,
            decision_log_entry_from_dict,
            decision_log_entry_to_dict,
            flow_result_from_dict,
            flow_result_to_dict,
            generate_run_id,
            handoff_envelope_from_dict,
            handoff_envelope_to_dict,
            human_policy_from_dict,
            human_policy_to_dict,
            injected_node_from_dict,
            injected_node_spec_from_dict,
            injected_node_spec_to_dict,
            injected_node_to_dict,
            interruption_frame_from_dict,
            interruption_frame_to_dict,
            macro_policy_from_dict,
            macro_policy_to_dict,
            macro_routing_decision_from_dict,
            macro_routing_decision_to_dict,
            macro_routing_rule_from_dict,
            macro_routing_rule_to_dict,
            resume_point_from_dict,
            resume_point_to_dict,
            routing_candidate_from_dict,
            routing_candidate_to_dict,
            routing_explanation_from_dict,
            routing_explanation_to_dict,
            routing_signal_from_dict,
            routing_signal_to_dict,
            run_event_from_dict,
            run_event_to_dict,
            run_plan_spec_from_dict,
            run_plan_spec_to_dict,
            run_spec_from_dict,
            run_spec_to_dict,
            run_state_from_dict,
            run_state_to_dict,
            run_summary_from_dict,
            run_summary_to_dict,
            wp4_routing_explanation_from_dict,
            wp4_routing_explanation_to_dict,
        )

        # Verify generate_run_id works
        run_id = generate_run_id()
        assert run_id.startswith("run-")


class TestSerdesRoundtrip:
    """Verify serialization roundtrips preserve data."""

    def test_run_spec_roundtrip(self) -> None:
        """Test RunSpec serialization roundtrip."""
        from swarm.runtime.types import (
            RunSpec,
            run_spec_from_dict,
            run_spec_to_dict,
        )

        original = RunSpec(
            flow_keys=["signal", "plan", "build"],
            profile_id="test-profile",
            backend="claude-harness",
            initiator="cli",
            params={"debug": True},
            no_human_mid_flow=True,
        )
        roundtrip = run_spec_from_dict(run_spec_to_dict(original))

        assert roundtrip.flow_keys == original.flow_keys
        assert roundtrip.profile_id == original.profile_id
        assert roundtrip.backend == original.backend
        assert roundtrip.initiator == original.initiator
        assert roundtrip.params == original.params
        assert roundtrip.no_human_mid_flow == original.no_human_mid_flow

    def test_run_event_roundtrip(self) -> None:
        """Test RunEvent serialization roundtrip with backwards compat."""
        from swarm.runtime.types import (
            RunEvent,
            run_event_from_dict,
            run_event_to_dict,
        )

        now = datetime.now(timezone.utc)
        original = RunEvent(
            run_id="run-test-123",
            ts=now,
            kind="step_start",
            flow_key="build",
            event_id="evt-123",
            seq=5,
            step_id="step-1",
            agent_key="code-implementer",
            payload={"message": "Starting step"},
        )
        serialized = run_event_to_dict(original)
        roundtrip = run_event_from_dict(serialized)

        assert roundtrip.run_id == original.run_id
        assert roundtrip.kind == original.kind
        assert roundtrip.flow_key == original.flow_key
        assert roundtrip.event_id == original.event_id
        assert roundtrip.seq == original.seq
        assert roundtrip.step_id == original.step_id
        assert roundtrip.agent_key == original.agent_key
        assert roundtrip.payload == original.payload

    def test_run_event_backwards_compat(self) -> None:
        """Test RunEvent handles missing event_id/seq fields."""
        from swarm.runtime.types import run_event_from_dict

        # Old-style event without event_id or seq
        old_data = {
            "run_id": "run-old",
            "ts": "2025-01-01T00:00:00Z",
            "kind": "log",
            "flow_key": "signal",
        }
        event = run_event_from_dict(old_data)
        assert event.event_id  # Should have generated one
        assert event.seq == 0  # Default

    def test_routing_signal_roundtrip(self) -> None:
        """Test RoutingSignal with explanation roundtrip."""
        from swarm.runtime.types import (
            DecisionType,
            RoutingDecision,
            RoutingExplanation,
            RoutingSignal,
            routing_signal_from_dict,
            routing_signal_to_dict,
        )

        explanation = RoutingExplanation(
            decision_type=DecisionType.DETERMINISTIC,
            selected_target="step-2",
            confidence=0.95,
            reasoning_summary="Single outgoing edge",
        )
        original = RoutingSignal(
            decision=RoutingDecision.ADVANCE,
            next_step_id="step-2",
            reason="Proceeding to next step",
            confidence=0.95,
            loop_count=1,
            exit_condition_met=False,
            explanation=explanation,
        )
        roundtrip = routing_signal_from_dict(routing_signal_to_dict(original))

        assert roundtrip.decision == original.decision
        assert roundtrip.next_step_id == original.next_step_id
        assert roundtrip.reason == original.reason
        assert roundtrip.confidence == original.confidence
        assert roundtrip.loop_count == original.loop_count
        assert roundtrip.exit_condition_met == original.exit_condition_met
        assert roundtrip.explanation is not None
        assert roundtrip.explanation.decision_type == explanation.decision_type

    def test_routing_signal_with_skip_justification(self) -> None:
        """Test RoutingSignal with skip_justification roundtrip."""
        from swarm.runtime.types import (
            RoutingDecision,
            RoutingSignal,
            SkipJustification,
            routing_signal_from_dict,
            routing_signal_to_dict,
        )

        skip_just: SkipJustification = {
            "skip_reason": "Already verified externally",
            "why_not_needed_for_exit": "External CI passed",
            "replacement_assurance": "CI pipeline provides verification",
        }
        original = RoutingSignal(
            decision=RoutingDecision.SKIP,
            reason="Skipping due to external verification",
            skip_justification=skip_just,
        )
        roundtrip = routing_signal_from_dict(routing_signal_to_dict(original))

        assert roundtrip.decision == RoutingDecision.SKIP
        assert roundtrip.skip_justification is not None
        assert roundtrip.skip_justification["skip_reason"] == skip_just["skip_reason"]

    def test_handoff_envelope_roundtrip(self) -> None:
        """Test HandoffEnvelope with assumptions/decisions roundtrip."""
        from swarm.runtime.types import (
            AssumptionEntry,
            ConfidenceLevel,
            DecisionLogEntry,
            HandoffEnvelope,
            RoutingDecision,
            RoutingSignal,
            StationOpinion,
            handoff_envelope_from_dict,
            handoff_envelope_to_dict,
        )

        now = datetime.now(timezone.utc)
        assumption = AssumptionEntry(
            assumption_id="asm-1",
            flow_introduced="build",
            step_introduced="step-1",
            agent="code-implementer",
            statement="Assuming API uses REST",
            rationale="No gRPC dependencies found",
            impact_if_wrong="Would need to refactor client code",
            confidence=ConfidenceLevel.MEDIUM,
            timestamp=now,
        )
        decision = DecisionLogEntry(
            decision_id="dec-1",
            flow="build",
            step="step-1",
            agent="code-implementer",
            decision_type="implementation",
            subject="API client",
            decision="Use httpx for HTTP requests",
            rationale="Already in dependencies",
            timestamp=now,
        )
        opinion: StationOpinion = {
            "kind": "suggest_detour",
            "suggested_action": "Run additional tests",
            "reason": "Complexity detected",
        }
        original = HandoffEnvelope(
            step_id="step-1",
            flow_key="build",
            run_id="run-test",
            routing_signal=RoutingSignal(decision=RoutingDecision.ADVANCE),
            summary="Step completed successfully",
            artifacts={"code": "src/api.py"},
            status="succeeded",
            duration_ms=1500,
            timestamp=now,
            assumptions_made=[assumption],
            decisions_made=[decision],
            station_opinions=[opinion],
        )
        roundtrip = handoff_envelope_from_dict(handoff_envelope_to_dict(original))

        assert roundtrip.step_id == original.step_id
        assert roundtrip.flow_key == original.flow_key
        assert roundtrip.summary == original.summary
        assert len(roundtrip.assumptions_made) == 1
        assert roundtrip.assumptions_made[0].assumption_id == "asm-1"
        assert len(roundtrip.decisions_made) == 1
        assert roundtrip.decisions_made[0].decision_id == "dec-1"
        assert len(roundtrip.station_opinions) == 1
        assert roundtrip.station_opinions[0]["kind"] == "suggest_detour"

    def test_run_state_roundtrip(self) -> None:
        """Test RunState with interruption stack roundtrip."""
        from swarm.runtime.types import (
            HandoffEnvelope,
            InjectedNodeSpec,
            InterruptionFrame,
            ResumePoint,
            RoutingDecision,
            RoutingSignal,
            RunState,
            run_state_from_dict,
            run_state_to_dict,
        )

        now = datetime.now(timezone.utc)
        envelope = HandoffEnvelope(
            step_id="step-1",
            flow_key="build",
            run_id="run-test",
            routing_signal=RoutingSignal(decision=RoutingDecision.ADVANCE),
            summary="Completed",
            timestamp=now,
        )
        injected_spec = InjectedNodeSpec(
            node_id="sq-clarifier-0",
            station_id="clarifier",
            agent_key="clarifier",
            role="Clarify requirements",
            sidequest_origin="clarify",
            sequence_index=0,
            total_in_sequence=2,
        )
        original = RunState(
            run_id="run-test",
            flow_key="build",
            current_step_id="step-2",
            step_index=1,
            loop_state={"microloop-1": 2},
            handoff_envelopes={"step-1": envelope},
            status="running",
            timestamp=now,
            current_flow_index=3,
            interruption_stack=[
                InterruptionFrame(
                    reason="Detour for clarification",
                    interrupted_at=now,
                    return_node="step-2",
                    current_step_index=0,
                    total_steps=2,
                    sidequest_id="clarify",
                )
            ],
            resume_stack=[ResumePoint(node_id="step-2", saved_context={"key": "value"})],
            injected_nodes=["sq-clarifier-0"],
            injected_node_specs={"sq-clarifier-0": injected_spec},
            completed_nodes=["step-1"],
        )
        roundtrip = run_state_from_dict(run_state_to_dict(original))

        assert roundtrip.run_id == original.run_id
        assert roundtrip.flow_key == original.flow_key
        assert roundtrip.current_step_id == original.current_step_id
        assert roundtrip.loop_state == original.loop_state
        assert len(roundtrip.handoff_envelopes) == 1
        assert roundtrip.status == original.status
        assert len(roundtrip.interruption_stack) == 1
        assert roundtrip.interruption_stack[0].sidequest_id == "clarify"
        assert len(roundtrip.resume_stack) == 1
        assert len(roundtrip.injected_node_specs) == 1
        assert roundtrip.injected_node_specs["sq-clarifier-0"].station_id == "clarifier"

    def test_wp4_routing_explanation_roundtrip(self) -> None:
        """Test WP4RoutingExplanation roundtrip."""
        from swarm.runtime.types import (
            WP4EliminationEntry,
            WP4RoutingExplanation,
            WP4RoutingMetrics,
            wp4_routing_explanation_from_dict,
            wp4_routing_explanation_to_dict,
        )

        original = WP4RoutingExplanation(
            decision="Advance to step-2",
            method="deterministic",
            selected_edge="edge-1",
            candidates_evaluated=3,
            elimination_log=[
                WP4EliminationEntry(
                    edge_id="edge-2",
                    reason="Condition false",
                    stage="condition",
                )
            ],
            llm_reasoning=None,
            metrics=WP4RoutingMetrics(
                edges_considered=3,
                time_ms=15.5,
                llm_tokens_used=0,
            ),
        )
        roundtrip = wp4_routing_explanation_from_dict(
            wp4_routing_explanation_to_dict(original)
        )

        assert roundtrip.decision == original.decision
        assert roundtrip.method == original.method
        assert roundtrip.selected_edge == original.selected_edge
        assert roundtrip.candidates_evaluated == original.candidates_evaluated
        assert len(roundtrip.elimination_log) == 1
        assert roundtrip.elimination_log[0].edge_id == "edge-2"
        assert roundtrip.metrics is not None
        assert roundtrip.metrics.edges_considered == 3

    def test_macro_routing_decision_roundtrip(self) -> None:
        """Test MacroRoutingDecision roundtrip."""
        from swarm.runtime.types import (
            MacroAction,
            MacroRoutingDecision,
            macro_routing_decision_from_dict,
            macro_routing_decision_to_dict,
        )

        original = MacroRoutingDecision(
            action=MacroAction.GOTO,
            next_flow="build",
            reason="Gate bounced to build",
            rule_applied="gate-bounce-build",
            confidence=0.9,
            constraints_checked=["max_bounces"],
            warnings=["Approaching bounce limit"],
        )
        roundtrip = macro_routing_decision_from_dict(
            macro_routing_decision_to_dict(original)
        )

        assert roundtrip.action == MacroAction.GOTO
        assert roundtrip.next_flow == "build"
        assert roundtrip.rule_applied == "gate-bounce-build"
        assert roundtrip.warnings == ["Approaching bounce limit"]


class TestPrivateHelperAccess:
    """Test that commonly-used private helpers remain accessible."""

    def test_datetime_helpers(self) -> None:
        """Test datetime helpers are accessible (for compatibility)."""
        # These are private but may be used externally
        from swarm.runtime.types import _datetime_to_iso, _iso_to_datetime

        now = datetime.now(timezone.utc)
        iso_str = _datetime_to_iso(now)
        assert iso_str is not None
        assert iso_str.endswith("Z")

        parsed = _iso_to_datetime(iso_str)
        assert parsed is not None

    def test_generate_event_id(self) -> None:
        """Test _generate_event_id is accessible."""
        from swarm.runtime.types import _generate_event_id

        event_id = _generate_event_id()
        assert event_id is not None
        assert len(event_id) > 0
