"""Tests for Navigator integration features in the stepwise orchestrator.

These tests cover the NavigationOrchestrator's handling of:
1. PAUSE -> DETOUR rewriting (when no_human_mid_flow=True)
2. Multi-step sidequest progression
3. EXTEND_GRAPH injection + graph_patch_suggested event emission
4. Run resume from saved state

The Navigator pattern uses cheap LLM calls to make intelligent routing
decisions, with traditional tooling doing the heavy lifting.
"""

import pytest
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from swarm.runtime.navigator import (
    DetourRequest,
    NavigatorOutput,
    NavigatorSignals,
    NextStepBrief,
    ProposedEdge,
    ProposedNode,
    RouteIntent,
    RouteProposal,
    SignalLevel,
)
from swarm.runtime.navigator_integration import (
    apply_detour_request,
    apply_extend_graph_request,
    check_and_handle_detour_completion,
    emit_graph_patch_suggested_event,
    get_current_detour_depth,
    rewrite_pause_to_detour,
)
from swarm.runtime.stepwise.orchestrator import MAX_DETOUR_DEPTH
from swarm.runtime.sidequest_catalog import (
    ReturnBehavior,
    SidequestCatalog,
    SidequestDefinition,
    SidequestStep,
)
from swarm.runtime.types import (
    RunState,
)


class TestPauseRewriteToDetour:
    """Test PAUSE -> DETOUR rewriting for no_human_mid_flow policy."""

    def test_pause_rewritten_to_detour_when_clarifier_exists(self):
        """When no_human_mid_flow=True, PAUSE intent should become DETOUR targeting clarifier."""
        # Create a NavigatorOutput with PAUSE intent
        nav_output = NavigatorOutput(
            route=RouteProposal(
                intent=RouteIntent.PAUSE,
                target_node=None,
                reasoning="Need clarification on requirements",
                confidence=0.8,
            ),
            next_step_brief=NextStepBrief(
                objective="Wait for human input",
                focus_areas=["requirements"],
            ),
            signals=NavigatorSignals(
                needs_human=True,
                uncertainty=SignalLevel.HIGH,
            ),
        )

        # Create catalog with clarifier sidequest
        clarifier_sidequest = SidequestDefinition(
            sidequest_id="clarifier",
            name="Clarifier",
            description="Resolve ambiguity or missing requirements",
            station_id="clarifier",
            objective_template="Clarify: {{issue}}",
            priority=70,
            cost_hint="low",
        )
        catalog = SidequestCatalog(sidequests=[clarifier_sidequest])

        # Call rewrite_pause_to_detour
        rewritten = rewrite_pause_to_detour(nav_output, catalog)

        # Assert intent changed to DETOUR
        assert rewritten.route.intent == RouteIntent.DETOUR

        # Assert detour_request targets clarifier
        assert rewritten.detour_request is not None
        assert rewritten.detour_request.sidequest_id == "clarifier"
        assert "clarify" in rewritten.detour_request.objective.lower()

        # Assert needs_human is cleared
        assert rewritten.signals.needs_human is False

        # Assert reasoning includes original reason
        assert "Need clarification" in rewritten.route.reasoning or "no_human_mid_flow" in rewritten.route.reasoning

    def test_pause_not_rewritten_when_no_clarifier(self):
        """Without clarifier in catalog, PAUSE should remain unchanged."""
        nav_output = NavigatorOutput(
            route=RouteProposal(
                intent=RouteIntent.PAUSE,
                target_node=None,
                reasoning="Need human input",
            ),
            next_step_brief=NextStepBrief(objective="Wait"),
            signals=NavigatorSignals(needs_human=True),
        )

        # Create catalog with only non-clarifier sidequests
        # (explicitly provide a sidequest to prevent default loading)
        other_sidequest = SidequestDefinition(
            sidequest_id="env-doctor",
            name="Environment Doctor",
            description="Fix environment issues",
            station_id="fixer",
        )
        catalog = SidequestCatalog(sidequests=[other_sidequest])

        # Call rewrite_pause_to_detour
        rewritten = rewrite_pause_to_detour(nav_output, catalog)

        # Assert intent remains PAUSE (no clarifier available)
        assert rewritten.route.intent == RouteIntent.PAUSE
        assert rewritten.detour_request is None

    def test_non_pause_intents_unchanged(self):
        """Non-PAUSE intents should pass through unchanged."""
        for intent in [RouteIntent.ADVANCE, RouteIntent.LOOP, RouteIntent.TERMINATE, RouteIntent.DETOUR]:
            nav_output = NavigatorOutput(
                route=RouteProposal(
                    intent=intent,
                    target_node="next-step",
                    reasoning="Test",
                ),
                next_step_brief=NextStepBrief(objective="Continue"),
            )

            clarifier_sidequest = SidequestDefinition(
                sidequest_id="clarifier",
                name="Clarifier",
                description="Resolve ambiguity",
                station_id="clarifier",
            )
            catalog = SidequestCatalog(sidequests=[clarifier_sidequest])

            rewritten = rewrite_pause_to_detour(nav_output, catalog)

            # Assert intent unchanged
            assert rewritten.route.intent == intent


class TestMultiStepSidequestProgression:
    """Test multi-step sidequest progression with durable cursor."""

    def test_multi_step_sidequest_advances_cursor(self):
        """Multi-step sidequests should advance step index and return next step's station."""
        # Create a multi-step sidequest definition
        multi_step_sidequest = SidequestDefinition(
            sidequest_id="deep-analysis",
            name="Deep Analysis",
            description="Multi-step analysis flow",
            steps=[
                SidequestStep(template_id="context-loader", step_id="step-1"),
                SidequestStep(template_id="architecture-critic", step_id="step-2"),
                SidequestStep(template_id="plan-writer", step_id="step-3"),
            ],
            priority=60,
        )
        catalog = SidequestCatalog(sidequests=[multi_step_sidequest])

        # Create RunState with interruption frame at step 0 of 3
        run_state = RunState(
            run_id="test-run-001",
            flow_key="build",
            current_step_id="3-implement",
            step_index=3,
        )

        # Push interruption frame for multi-step sidequest at step 0
        run_state.push_interruption(
            reason="Sidequest: Deep Analysis",
            return_node="3-implement",
            context_snapshot={"objective": "Analyze architecture"},
            current_step_index=0,
            total_steps=3,
            sidequest_id="deep-analysis",
        )

        # Push corresponding resume point
        run_state.push_resume("3-implement", {"detour_reason": "Deep analysis needed"})

        # Initial state check
        assert run_state.is_interrupted() is True
        frame = run_state.peek_interruption()
        assert frame is not None
        assert frame.current_step_index == 0
        assert frame.total_steps == 3

        # Call check_and_handle_detour_completion - should advance to step 1
        next_station = check_and_handle_detour_completion(run_state, catalog)

        # Assert it returns the injected node ID for the next step
        assert next_station == "sq-deep-analysis-1"

        # Assert frame's current_step_index was incremented
        updated_frame = run_state.peek_interruption()
        assert updated_frame is not None
        assert updated_frame.current_step_index == 1

        # Stacks should NOT be popped yet (still in sidequest)
        assert run_state.is_interrupted() is True
        assert len(run_state.resume_stack) == 1

    def test_multi_step_sidequest_completes_on_last_step(self):
        """After last step of multi-step sidequest, should pop stacks and resume."""
        multi_step_sidequest = SidequestDefinition(
            sidequest_id="deep-analysis",
            name="Deep Analysis",
            description="Multi-step analysis flow",
            steps=[
                SidequestStep(template_id="context-loader", step_id="step-1"),
                SidequestStep(template_id="plan-writer", step_id="step-2"),
            ],
            priority=60,
        )
        catalog = SidequestCatalog(sidequests=[multi_step_sidequest])

        run_state = RunState(
            run_id="test-run-002",
            flow_key="build",
            current_step_id="sidequest-step",
            step_index=0,
        )

        # Push interruption frame at LAST step (index 1 of 2 steps)
        run_state.push_interruption(
            reason="Sidequest: Deep Analysis",
            return_node="3-implement",
            context_snapshot={},
            current_step_index=1,  # Last step (0-indexed)
            total_steps=2,
            sidequest_id="deep-analysis",
        )
        run_state.push_resume("3-implement", {})

        # Call check_and_handle_detour_completion
        next_station = check_and_handle_detour_completion(run_state, catalog)

        # Should resume to the saved return node
        assert next_station == "3-implement"

        # Stacks should be popped
        assert run_state.is_interrupted() is False
        assert len(run_state.resume_stack) == 0


class TestExtendGraphInjection:
    """Test EXTEND_GRAPH node injection and event emission."""

    def test_extend_graph_injects_node_and_tracks_in_state(self):
        """EXTEND_GRAPH should inject run-local node into RunState."""
        # Create NavigatorOutput with proposed_edge
        nav_output = NavigatorOutput(
            route=RouteProposal(
                intent=RouteIntent.EXTEND_GRAPH,
                target_node=None,
                reasoning="Need architecture review before continuing",
            ),
            next_step_brief=NextStepBrief(objective="Review architecture"),
            proposed_edge=ProposedEdge(
                from_node="3-implement",
                to_node="architecture-critic",
                why="Implementation touches core architecture",
                edge_type="injection",
                priority=80,
                is_return=True,
                proposed_node=ProposedNode(
                    template_id="architecture-critic",
                    objective="Review architecture changes",
                ),
            ),
        )

        run_state = RunState(
            run_id="test-run-003",
            flow_key="build",
            current_step_id="3-implement",
            step_index=3,
        )

        current_node = "3-implement"

        # Call apply_extend_graph_request
        target = apply_extend_graph_request(
            nav_output=nav_output,
            run_state=run_state,
            current_node=current_node,
            station_library=["architecture-critic", "context-loader", "fixer"],  # Valid stations
        )

        # Assert target is the proposed station
        assert target == "architecture-critic"

        # Assert injected node was added to run_state
        assert len(run_state.injected_nodes) == 1
        assert "architecture-critic" in run_state.injected_nodes[0]

        # Assert resume point was pushed (since is_return=True)
        assert len(run_state.resume_stack) == 1
        assert run_state.peek_resume().node_id == current_node

        # Assert interruption frame was pushed
        assert run_state.is_interrupted() is True

    def test_extend_graph_rejects_invalid_target(self):
        """EXTEND_GRAPH should reject targets not in station library."""
        nav_output = NavigatorOutput(
            route=RouteProposal(
                intent=RouteIntent.EXTEND_GRAPH,
                reasoning="Need security audit",
            ),
            next_step_brief=NextStepBrief(objective="Security review"),
            proposed_edge=ProposedEdge(
                from_node="3-implement",
                to_node="nonexistent-station",  # Not in library
                why="Security concern detected",
            ),
        )

        run_state = RunState(
            run_id="test-run-004",
            flow_key="build",
            current_step_id="3-implement",
            step_index=3,
        )

        # Call with a station library that doesn't include the target
        target = apply_extend_graph_request(
            nav_output=nav_output,
            run_state=run_state,
            current_node="3-implement",
            station_library=["architecture-critic", "context-loader"],  # Does not include nonexistent-station
        )

        # Assert target is None (rejected)
        assert target is None

        # Assert no nodes were injected
        assert len(run_state.injected_nodes) == 0

    def test_emit_graph_patch_suggested_event(self):
        """emit_graph_patch_suggested_event should emit event with correct payload."""
        proposed_edge = ProposedEdge(
            from_node="3-implement",
            to_node="security-scanner",
            why="Security paths touched",
            edge_type="injection",
            priority=90,
            is_return=True,
            proposed_node=ProposedNode(
                template_id="security-scanner",
                station_id="security-scanner",
                objective="Scan for vulnerabilities",
            ),
        )

        # Capture emitted events
        emitted_events: List[Any] = []

        def mock_append_event(run_id: str, event: Any) -> None:
            emitted_events.append(event)

        # Call emit_graph_patch_suggested_event
        emit_graph_patch_suggested_event(
            run_id="test-run-005",
            flow_key="build",
            step_id="3-implement",
            proposed_edge=proposed_edge,
            append_event_fn=mock_append_event,
        )

        # Assert event was emitted
        assert len(emitted_events) == 1
        event = emitted_events[0]

        # Check event kind
        assert event.kind == "graph_patch_suggested"
        assert event.run_id == "test-run-005"
        assert event.flow_key == "build"
        assert event.step_id == "3-implement"

        # Check payload
        payload = event.payload
        assert payload["reason"] == "Security paths touched"
        assert payload["is_return"] is True
        assert payload["injected_for_run"] is True

        # Check patch contains both node and edge patches (since proposed_node is set)
        patch = payload["patch"]
        assert isinstance(patch, list)
        assert len(patch) == 2  # Node patch + edge patch


class TestDetourCompletionResume:
    """Test run resume from saved state after detour completion."""

    def test_detour_completion_resumes_to_saved_node(self):
        """After sidequest completes, should resume to the saved return node."""
        # Create a simple sidequest
        sidequest = SidequestDefinition(
            sidequest_id="clarifier",
            name="Clarifier",
            description="Resolve ambiguity",
            station_id="clarifier",
            return_behavior=ReturnBehavior(mode="resume"),
        )
        catalog = SidequestCatalog(sidequests=[sidequest])

        run_state = RunState(
            run_id="test-run-006",
            flow_key="signal",
            current_step_id="clarifier-node",
            step_index=2,
        )

        # Simulate completing a sidequest by having frame with completed step
        # For single-step sidequest, current_step_index=0 and total_steps=1 means complete
        run_state.push_interruption(
            reason="Sidequest: Clarifier",
            return_node="2-requirements",
            context_snapshot={"question": "What is the scope?"},
            current_step_index=0,
            total_steps=1,  # Single step sidequest
            sidequest_id="clarifier",
        )

        # Push resume point
        run_state.push_resume("2-requirements", {"detour_reason": "Clarification needed"})

        # Verify initial state
        assert run_state.is_interrupted() is True
        assert len(run_state.resume_stack) == 1

        # Call check_and_handle_detour_completion
        resume_node = check_and_handle_detour_completion(run_state, catalog)

        # Assert it returns the resume node
        assert resume_node == "2-requirements"

        # Assert stacks were popped
        assert run_state.is_interrupted() is False
        assert len(run_state.resume_stack) == 0

    def test_detour_with_bounce_to_behavior(self):
        """Sidequest with bounce_to return behavior should redirect to target node."""
        sidequest = SidequestDefinition(
            sidequest_id="fixer",
            name="Fixer",
            description="Fix environment issues",
            station_id="fixer",
            return_behavior=ReturnBehavior(
                mode="bounce_to",
                target_node="1-start",  # Bounce back to start
            ),
        )
        catalog = SidequestCatalog(sidequests=[sidequest])

        run_state = RunState(
            run_id="test-run-007",
            flow_key="build",
            current_step_id="fixer-node",
        )

        # Push interruption and resume for completed sidequest
        run_state.push_interruption(
            reason="Sidequest: Fixer",
            return_node="3-implement",  # Original return node
            current_step_index=0,
            total_steps=1,
            sidequest_id="fixer",
        )
        run_state.push_resume("3-implement", {})

        # Call check_and_handle_detour_completion
        resume_node = check_and_handle_detour_completion(run_state, catalog)

        # Assert it returns the bounce_to target, not the resume point
        assert resume_node == "1-start"

    def test_detour_with_halt_behavior(self):
        """Sidequest with halt return behavior should return None (stop flow)."""
        sidequest = SidequestDefinition(
            sidequest_id="blocker",
            name="Blocker",
            description="Block on critical issue",
            station_id="blocker",
            return_behavior=ReturnBehavior(mode="halt"),
        )
        catalog = SidequestCatalog(sidequests=[sidequest])

        run_state = RunState(
            run_id="test-run-008",
            flow_key="build",
            current_step_id="blocker-node",
        )

        run_state.push_interruption(
            reason="Sidequest: Blocker",
            return_node="3-implement",
            current_step_index=0,
            total_steps=1,
            sidequest_id="blocker",
        )
        run_state.push_resume("3-implement", {})

        # Call check_and_handle_detour_completion
        resume_node = check_and_handle_detour_completion(run_state, catalog)

        # Assert it returns None (halt)
        assert resume_node is None

    def test_no_resume_when_not_interrupted(self):
        """When not interrupted, check_and_handle_detour_completion should return None."""
        catalog = SidequestCatalog(sidequests=[])

        run_state = RunState(
            run_id="test-run-009",
            flow_key="build",
            current_step_id="3-implement",
        )

        # No interruption pushed
        assert run_state.is_interrupted() is False

        # Call check_and_handle_detour_completion
        resume_node = check_and_handle_detour_completion(run_state, catalog)

        # Assert it returns None
        assert resume_node is None


class TestApplyDetourRequest:
    """Test detour request application to RunState."""

    def test_apply_detour_request_pushes_stacks(self):
        """apply_detour_request should push resume and interruption stacks."""
        sidequest = SidequestDefinition(
            sidequest_id="test-triage",
            name="Test Triage",
            description="Analyze failing tests",
            station_id="test-critic",
            objective_template="Triage: {{issue}}",
            steps=[
                SidequestStep(template_id="test-critic", step_id="step-1"),
                SidequestStep(template_id="fixer", step_id="step-2"),
            ],
        )
        catalog = SidequestCatalog(sidequests=[sidequest])

        nav_output = NavigatorOutput(
            route=RouteProposal(
                intent=RouteIntent.DETOUR,
                reasoning="Tests failing repeatedly",
            ),
            next_step_brief=NextStepBrief(objective="Investigate test failures"),
            detour_request=DetourRequest(
                sidequest_id="test-triage",
                objective="Triage failing tests",
                priority=60,
            ),
        )

        run_state = RunState(
            run_id="test-run-010",
            flow_key="build",
            current_step_id="3-implement",
            step_index=3,
        )

        current_node = "3-implement"

        # Call apply_detour_request
        station = apply_detour_request(nav_output, run_state, catalog, current_node)

        # Assert returns the first step's injected node ID
        assert station == "sq-test-triage-0"

        # Assert resume stack was pushed
        assert len(run_state.resume_stack) == 1
        resume_point = run_state.peek_resume()
        assert resume_point.node_id == current_node
        assert "test-triage" in resume_point.saved_context.get("sidequest_id", "")

        # Assert interruption frame was pushed with multi-step tracking
        assert run_state.is_interrupted() is True
        frame = run_state.peek_interruption()
        assert frame.sidequest_id == "test-triage"
        assert frame.current_step_index == 0
        assert frame.total_steps == 2  # Multi-step sidequest has 2 steps

        # Assert injected nodes were added for ALL steps
        assert len(run_state.injected_nodes) == 2  # One for each step
        assert "sq-test-triage-0" in run_state.injected_nodes
        assert "sq-test-triage-1" in run_state.injected_nodes

        # Assert injected node specs were registered
        spec_0 = run_state.get_injected_node_spec("sq-test-triage-0")
        assert spec_0 is not None
        assert spec_0.station_id == "test-critic"
        assert spec_0.sequence_index == 0
        assert spec_0.total_in_sequence == 2

        spec_1 = run_state.get_injected_node_spec("sq-test-triage-1")
        assert spec_1 is not None
        assert spec_1.station_id == "fixer"
        assert spec_1.sequence_index == 1
        assert spec_1.total_in_sequence == 2

    def test_apply_detour_request_returns_none_for_unknown_sidequest(self):
        """apply_detour_request should return None for unknown sidequest."""
        catalog = SidequestCatalog(sidequests=[])  # Empty catalog

        nav_output = NavigatorOutput(
            route=RouteProposal(intent=RouteIntent.DETOUR),
            next_step_brief=NextStepBrief(objective="Unknown"),
            detour_request=DetourRequest(
                sidequest_id="nonexistent",
                objective="Test",
            ),
        )

        run_state = RunState(
            run_id="test-run-011",
            flow_key="build",
            current_step_id="3-implement",
        )

        station = apply_detour_request(nav_output, run_state, catalog, "3-implement")

        # Assert returns None
        assert station is None

        # Assert stacks were not modified
        assert run_state.is_interrupted() is False
        assert len(run_state.resume_stack) == 0


class TestMaxDetourDepthEnforcement:
    """Test MAX_DETOUR_DEPTH enforcement to prevent runaway nested sidequests."""

    def test_get_current_detour_depth_returns_zero_when_no_interruptions(self):
        """get_current_detour_depth should return 0 when interruption stack is empty."""
        run_state = RunState(
            run_id="test-depth-001",
            flow_key="build",
            current_step_id="3-implement",
        )

        assert get_current_detour_depth(run_state) == 0
        assert run_state.is_interrupted() is False

    def test_get_current_detour_depth_counts_interruption_frames(self):
        """get_current_detour_depth should return the count of interruption frames."""
        run_state = RunState(
            run_id="test-depth-002",
            flow_key="build",
            current_step_id="3-implement",
        )

        # Push 3 interruption frames
        for i in range(3):
            run_state.push_interruption(
                reason=f"Detour {i+1}",
                return_node=f"node-{i}",
                sidequest_id=f"sidequest-{i+1}",
            )

        assert get_current_detour_depth(run_state) == 3

    def test_detour_rejected_when_at_max_depth(self):
        """apply_detour_request should reject detour when already at MAX_DETOUR_DEPTH."""
        # Create a sidequest that could be applied
        sidequest = SidequestDefinition(
            sidequest_id="clarifier",
            name="Clarifier",
            description="Resolve ambiguity",
            station_id="clarifier",
        )
        catalog = SidequestCatalog(sidequests=[sidequest])

        run_state = RunState(
            run_id="test-depth-003",
            flow_key="build",
            current_step_id="deep-step",
        )

        # Push MAX_DETOUR_DEPTH interruption frames to simulate being at the limit
        for i in range(MAX_DETOUR_DEPTH):
            run_state.push_interruption(
                reason=f"Nested detour {i+1}",
                return_node=f"node-{i}",
                sidequest_id=f"sidequest-{i+1}",
            )

        # Verify we are at the limit
        assert get_current_detour_depth(run_state) == MAX_DETOUR_DEPTH

        # Attempt to apply another detour
        nav_output = NavigatorOutput(
            route=RouteProposal(
                intent=RouteIntent.DETOUR,
                reasoning="Need to clarify something",
            ),
            next_step_brief=NextStepBrief(objective="Clarify"),
            detour_request=DetourRequest(
                sidequest_id="clarifier",
                objective="Clarify requirement",
                priority=70,
            ),
        )

        # Apply detour request - should be rejected
        station = apply_detour_request(nav_output, run_state, catalog, "deep-step")

        # Assert detour was rejected (returns None)
        assert station is None

        # Assert no additional interruption was pushed
        assert get_current_detour_depth(run_state) == MAX_DETOUR_DEPTH

    def test_detour_allowed_when_below_max_depth(self):
        """apply_detour_request should allow detour when below MAX_DETOUR_DEPTH."""
        sidequest = SidequestDefinition(
            sidequest_id="clarifier",
            name="Clarifier",
            description="Resolve ambiguity",
            station_id="clarifier",
        )
        catalog = SidequestCatalog(sidequests=[sidequest])

        run_state = RunState(
            run_id="test-depth-004",
            flow_key="build",
            current_step_id="some-step",
        )

        # Push (MAX_DETOUR_DEPTH - 1) interruption frames to be just below the limit
        for i in range(MAX_DETOUR_DEPTH - 1):
            run_state.push_interruption(
                reason=f"Nested detour {i+1}",
                return_node=f"node-{i}",
                sidequest_id=f"sidequest-{i+1}",
            )
            run_state.push_resume(f"node-{i}", {})

        # Verify we are one below the limit
        initial_depth = get_current_detour_depth(run_state)
        assert initial_depth == MAX_DETOUR_DEPTH - 1

        # Attempt to apply another detour
        nav_output = NavigatorOutput(
            route=RouteProposal(
                intent=RouteIntent.DETOUR,
                reasoning="Need to clarify",
            ),
            next_step_brief=NextStepBrief(objective="Clarify"),
            detour_request=DetourRequest(
                sidequest_id="clarifier",
                objective="Clarify requirement",
                priority=70,
            ),
        )

        # Apply detour request - should succeed
        station = apply_detour_request(nav_output, run_state, catalog, "some-step")

        # Assert detour was applied (returns station ID)
        assert station == "sq-clarifier-0"

        # Assert interruption was pushed
        assert get_current_detour_depth(run_state) == MAX_DETOUR_DEPTH

    def test_max_detour_depth_is_ten(self):
        """Verify MAX_DETOUR_DEPTH is set to 10 as specified."""
        assert MAX_DETOUR_DEPTH == 10

    def test_depth_decreases_after_detour_completion(self):
        """Depth should decrease when detour completes and interruption is popped."""
        sidequest = SidequestDefinition(
            sidequest_id="test-sq",
            name="Test Sidequest",
            description="For testing",
            station_id="test-station",
        )
        catalog = SidequestCatalog(sidequests=[sidequest])

        run_state = RunState(
            run_id="test-depth-005",
            flow_key="build",
            current_step_id="test-step",
        )

        # Push an interruption frame (simulating an active detour)
        run_state.push_interruption(
            reason="Test detour",
            return_node="original-node",
            current_step_index=0,
            total_steps=1,
            sidequest_id="test-sq",
        )
        run_state.push_resume("original-node", {})

        assert get_current_detour_depth(run_state) == 1

        # Complete the detour
        resume_node = check_and_handle_detour_completion(run_state, catalog)

        # Verify depth returned to 0
        assert get_current_detour_depth(run_state) == 0
        assert resume_node == "original-node"
