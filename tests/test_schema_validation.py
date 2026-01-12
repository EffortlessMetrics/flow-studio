"""Comprehensive schema validation tests for Flow Studio schemas.

Tests for:
1. RoutingSignal schema (routing_signal.schema.json)
2. HandoffEnvelope schema (handoff_envelope.schema.json)
3. FlowGraph schema (flow_graph.schema.json)

Validates the new schema fields including:
- why_now field in RoutingSignal
- skip_justification for skip decisions
- observations and station_opinions in HandoffEnvelope
- charter and suggested_sidequests in FlowGraph
"""

import json
import pytest
from pathlib import Path

try:
    from jsonschema import validate, ValidationError, Draft7Validator
    from referencing import Registry, Resource
    from referencing.jsonschema import DRAFT7
    HAS_JSONSCHEMA = True
except ImportError:
    HAS_JSONSCHEMA = False


SCHEMA_DIR = Path(__file__).parent.parent / "swarm" / "spec" / "schemas"


def load_schema(schema_name: str) -> dict:
    """Load a schema from the schema directory."""
    schema_path = SCHEMA_DIR / schema_name
    return json.loads(schema_path.read_text(encoding="utf-8"))


def load_all_schemas() -> dict:
    """Load all schemas from the schema directory."""
    schemas = {}
    for schema_file in SCHEMA_DIR.glob("*.schema.json"):
        schema = json.loads(schema_file.read_text(encoding="utf-8"))
        schemas[schema_file.name] = schema
    return schemas


def create_registry() -> "Registry":
    """Create a Registry for resolving $ref to local schema files."""
    resources = []
    for schema_file in SCHEMA_DIR.glob("*.schema.json"):
        schema = json.loads(schema_file.read_text(encoding="utf-8"))
        schema_id = schema.get("$id", schema_file.name)
        # Add with full $id URL
        resources.append((schema_id, Resource.from_contents(schema, default_specification=DRAFT7)))
        # Also add with just filename for relative references
        resources.append((schema_file.name, Resource.from_contents(schema, default_specification=DRAFT7)))

    return Registry().with_resources(resources)


def create_validator_with_refs(schema: dict) -> Draft7Validator:
    """Create a validator that can resolve local schema references."""
    registry = create_registry()
    return Draft7Validator(schema, registry=registry)


@pytest.fixture
def routing_signal_schema():
    """Load the routing_signal schema."""
    return load_schema("routing_signal.schema.json")


@pytest.fixture
def handoff_envelope_schema():
    """Load the handoff_envelope schema."""
    return load_schema("handoff_envelope.schema.json")


@pytest.fixture
def handoff_envelope_validator():
    """Create a validator for handoff_envelope with reference resolution."""
    schema = load_schema("handoff_envelope.schema.json")
    return create_validator_with_refs(schema)


@pytest.fixture
def flow_graph_schema():
    """Load the flow_graph schema."""
    return load_schema("flow_graph.schema.json")


# ==============================================================================
# RoutingSignal Schema Tests
# ==============================================================================

@pytest.mark.skipif(not HAS_JSONSCHEMA, reason="jsonschema not installed")
class TestRoutingSignalSchema:
    """Tests for routing_signal.schema.json validation."""

    def test_valid_advance_signal(self, routing_signal_schema):
        """Test valid advance decision with next_step."""
        signal = {
            "decision": "advance",
            "confidence": "high",
            "reason": "All tests passed, proceeding to next step",
            "next_step": "code-implement"
        }
        validate(signal, routing_signal_schema)

    def test_valid_advance_with_next_flow(self, routing_signal_schema):
        """Test valid advance decision with next_flow."""
        signal = {
            "decision": "advance",
            "confidence": "high",
            "reason": "Flow complete, transitioning to next flow",
            "next_flow": "4-review"
        }
        validate(signal, routing_signal_schema)

    def test_advance_requires_next_step_or_flow(self, routing_signal_schema):
        """Test that advance decision requires next_step or next_flow."""
        signal = {
            "decision": "advance",
            "confidence": "high",
            "reason": "Missing next_step or next_flow"
        }
        with pytest.raises(ValidationError):
            validate(signal, routing_signal_schema)

    def test_valid_loop_signal(self, routing_signal_schema):
        """Test valid loop decision with required fields."""
        signal = {
            "decision": "loop",
            "confidence": "medium",
            "reason": "Tests failing, need another iteration",
            "can_further_iteration_help": True,
            "loop_count": 2
        }
        validate(signal, routing_signal_schema)

    def test_loop_requires_can_further_iteration_help(self, routing_signal_schema):
        """Test that loop decision requires can_further_iteration_help."""
        signal = {
            "decision": "loop",
            "confidence": "medium",
            "reason": "Tests failing"
        }
        with pytest.raises(ValidationError):
            validate(signal, routing_signal_schema)

    def test_valid_terminate_signal(self, routing_signal_schema):
        """Test valid terminate decision."""
        signal = {
            "decision": "terminate",
            "confidence": "high",
            "reason": "Critical error, cannot continue"
        }
        validate(signal, routing_signal_schema)

    def test_valid_branch_signal(self, routing_signal_schema):
        """Test valid branch decision with branch_target."""
        signal = {
            "decision": "branch",
            "confidence": "high",
            "reason": "Condition met for alternative path",
            "branch_target": "error-handler"
        }
        validate(signal, routing_signal_schema)

    def test_branch_requires_branch_target(self, routing_signal_schema):
        """Test that branch decision requires branch_target."""
        signal = {
            "decision": "branch",
            "confidence": "high",
            "reason": "Missing branch_target"
        }
        with pytest.raises(ValidationError):
            validate(signal, routing_signal_schema)

    def test_valid_skip_with_justification(self, routing_signal_schema):
        """Test valid skip decision with full skip_justification."""
        signal = {
            "decision": "skip",
            "confidence": "high",
            "reason": "Node not needed for this flow execution",
            "skip_justification": {
                "skip_reason": "Tests already passing from previous iteration",
                "why_not_needed_for_exit": "Exit criteria AC-001 already satisfied by upstream step",
                "replacement_assurance": "Coverage verified by test-critic in step 3"
            }
        }
        validate(signal, routing_signal_schema)

    def test_skip_requires_justification(self, routing_signal_schema):
        """Test that skip decision requires skip_justification."""
        signal = {
            "decision": "skip",
            "confidence": "high",
            "reason": "Want to skip but no justification"
        }
        with pytest.raises(ValidationError):
            validate(signal, routing_signal_schema)

    def test_skip_justification_requires_all_fields(self, routing_signal_schema):
        """Test that skip_justification requires all three fields."""
        signal = {
            "decision": "skip",
            "confidence": "high",
            "reason": "Skipping",
            "skip_justification": {
                "skip_reason": "Tests already passing"
                # Missing: why_not_needed_for_exit, replacement_assurance
            }
        }
        with pytest.raises(ValidationError):
            validate(signal, routing_signal_schema)

    def test_skip_justification_partial_fields(self, routing_signal_schema):
        """Test that skip_justification with only two fields fails."""
        signal = {
            "decision": "skip",
            "confidence": "high",
            "reason": "Skipping",
            "skip_justification": {
                "skip_reason": "Tests already passing",
                "why_not_needed_for_exit": "Already covered"
                # Missing: replacement_assurance
            }
        }
        with pytest.raises(ValidationError):
            validate(signal, routing_signal_schema)

    def test_valid_why_now_field(self, routing_signal_schema):
        """Test valid why_now object with required fields."""
        signal = {
            "decision": "advance",
            "confidence": "high",
            "reason": "Deviation required",
            "next_step": "clarifier",
            "why_now": {
                "trigger": "Tests failed with Method Not Found error",
                "relevance_to_charter": "Cannot satisfy AC-002 without upstream fix"
            }
        }
        validate(signal, routing_signal_schema)

    def test_why_now_with_all_optional_fields(self, routing_signal_schema):
        """Test why_now with all optional fields."""
        signal = {
            "decision": "advance",
            "confidence": "high",
            "reason": "Deviation with full justification",
            "next_step": "risk-analyst",
            "why_now": {
                "trigger": "Upstream API changed signature",
                "analysis": "Root cause is breaking change in Auth interface v2.3",
                "relevance_to_charter": "Cannot implement Feature X without compatible Auth",
                "alternatives_considered": [
                    "Use deprecated v2.2 API",
                    "Implement auth wrapper",
                    "Defer feature to next sprint"
                ],
                "expected_outcome": "Risk assessment will inform go/no-go decision"
            }
        }
        validate(signal, routing_signal_schema)

    def test_why_now_requires_trigger(self, routing_signal_schema):
        """Test that why_now requires trigger field."""
        signal = {
            "decision": "advance",
            "confidence": "high",
            "reason": "Missing trigger",
            "next_step": "test",
            "why_now": {
                "relevance_to_charter": "Important but missing trigger"
            }
        }
        with pytest.raises(ValidationError):
            validate(signal, routing_signal_schema)

    def test_why_now_requires_relevance_to_charter(self, routing_signal_schema):
        """Test that why_now requires relevance_to_charter field."""
        signal = {
            "decision": "advance",
            "confidence": "high",
            "reason": "Missing relevance",
            "next_step": "test",
            "why_now": {
                "trigger": "Something happened"
            }
        }
        with pytest.raises(ValidationError):
            validate(signal, routing_signal_schema)

    def test_invalid_decision_value(self, routing_signal_schema):
        """Test invalid decision enum value."""
        signal = {
            "decision": "invalid_decision",
            "confidence": "high",
            "reason": "Invalid decision type"
        }
        with pytest.raises(ValidationError):
            validate(signal, routing_signal_schema)

    def test_valid_decision_enum_values(self, routing_signal_schema):
        """Test all valid decision enum values."""
        valid_decisions = ["advance", "loop", "terminate", "branch", "skip"]
        for decision in valid_decisions:
            signal = {
                "decision": decision,
                "confidence": "high",
                "reason": f"Testing {decision} decision"
            }
            # Add required fields based on decision type
            if decision == "advance":
                signal["next_step"] = "test-step"
            elif decision == "loop":
                signal["can_further_iteration_help"] = True
            elif decision == "branch":
                signal["branch_target"] = "target"
            elif decision == "skip":
                signal["skip_justification"] = {
                    "skip_reason": "reason",
                    "why_not_needed_for_exit": "explanation",
                    "replacement_assurance": "assurance"
                }
            validate(signal, routing_signal_schema)

    def test_invalid_confidence_value(self, routing_signal_schema):
        """Test invalid confidence enum value."""
        signal = {
            "decision": "terminate",
            "confidence": "very_high",
            "reason": "Invalid confidence"
        }
        with pytest.raises(ValidationError):
            validate(signal, routing_signal_schema)

    def test_valid_confidence_enum_values(self, routing_signal_schema):
        """Test all valid confidence enum values."""
        for confidence in ["high", "medium", "low"]:
            signal = {
                "decision": "terminate",
                "confidence": confidence,
                "reason": f"Testing {confidence} confidence"
            }
            validate(signal, routing_signal_schema)

    def test_confidence_score_range(self, routing_signal_schema):
        """Test numeric confidence_score range validation."""
        # Valid range
        for score in [0, 0.5, 1]:
            signal = {
                "decision": "terminate",
                "confidence": "high",
                "reason": "Testing confidence_score",
                "confidence_score": score
            }
            validate(signal, routing_signal_schema)

        # Invalid: above 1
        signal = {
            "decision": "terminate",
            "confidence": "high",
            "reason": "Invalid score",
            "confidence_score": 1.5
        }
        with pytest.raises(ValidationError):
            validate(signal, routing_signal_schema)

        # Invalid: below 0
        signal["confidence_score"] = -0.1
        with pytest.raises(ValidationError):
            validate(signal, routing_signal_schema)

    def test_blocker_structure(self, routing_signal_schema):
        """Test blocker array structure validation."""
        signal = {
            "decision": "terminate",
            "confidence": "high",
            "reason": "Blocked by missing dependency",
            "blockers": [
                {
                    "type": "missing_input",
                    "description": "plan/adr.md not found",
                    "artifact": "plan/adr.md",
                    "recoverable": True
                },
                {
                    "type": "validation_failure",
                    "description": "Schema validation failed"
                }
            ]
        }
        validate(signal, routing_signal_schema)

    def test_invalid_blocker_type(self, routing_signal_schema):
        """Test invalid blocker type enum value."""
        signal = {
            "decision": "terminate",
            "confidence": "high",
            "reason": "Invalid blocker type",
            "blockers": [
                {
                    "type": "invalid_type",
                    "description": "Invalid blocker"
                }
            ]
        }
        with pytest.raises(ValidationError):
            validate(signal, routing_signal_schema)

    def test_required_fields_missing(self, routing_signal_schema):
        """Test that required fields are enforced."""
        # Missing decision
        with pytest.raises(ValidationError):
            validate({"confidence": "high", "reason": "test"}, routing_signal_schema)

        # Missing confidence
        with pytest.raises(ValidationError):
            validate({"decision": "terminate", "reason": "test"}, routing_signal_schema)

        # Missing reason
        with pytest.raises(ValidationError):
            validate({"decision": "terminate", "confidence": "high"}, routing_signal_schema)

    def test_additional_properties_rejected(self, routing_signal_schema):
        """Test that additional properties are rejected."""
        signal = {
            "decision": "terminate",
            "confidence": "high",
            "reason": "test",
            "unknown_field": "should be rejected"
        }
        with pytest.raises(ValidationError):
            validate(signal, routing_signal_schema)


# ==============================================================================
# HandoffEnvelope Schema Tests
# ==============================================================================

@pytest.mark.skipif(not HAS_JSONSCHEMA, reason="jsonschema not installed")
class TestHandoffEnvelopeSchema:
    """Tests for handoff_envelope.schema.json validation."""

    def _minimal_routing_signal(self) -> dict:
        """Create a minimal valid routing signal."""
        return {
            "decision": "terminate",
            "confidence": "high",
            "reason": "test"
        }

    def test_valid_minimal_envelope(self, handoff_envelope_validator):
        """Test minimal valid envelope with required fields only."""
        envelope = {
            "status": "VERIFIED",
            "summary": "Step completed successfully",
            "routing_signal": self._minimal_routing_signal()
        }
        errors = list(handoff_envelope_validator.iter_errors(envelope))
        assert len(errors) == 0, f"Unexpected errors: {errors}"

    def test_valid_status_enum_values(self, handoff_envelope_validator):
        """Test all valid status enum values."""
        for status in ["VERIFIED", "UNVERIFIED", "BLOCKED", "PARTIAL"]:
            envelope = {
                "status": status,
                "summary": f"Testing {status} status",
                "routing_signal": self._minimal_routing_signal()
            }
            errors = list(handoff_envelope_validator.iter_errors(envelope))
            assert len(errors) == 0, f"Status {status} failed: {errors}"

    def test_invalid_status_value(self, handoff_envelope_validator):
        """Test invalid status enum value."""
        envelope = {
            "status": "INVALID_STATUS",
            "summary": "Invalid status",
            "routing_signal": self._minimal_routing_signal()
        }
        errors = list(handoff_envelope_validator.iter_errors(envelope))
        assert len(errors) > 0, "Expected validation error for invalid status"

    def test_valid_observations_array(self, handoff_envelope_validator):
        """Test valid observations array structure."""
        envelope = {
            "status": "VERIFIED",
            "summary": "Step with observations",
            "routing_signal": self._minimal_routing_signal(),
            "observations": [
                {
                    "type": "action_taken",
                    "observation": "Refactored helper function for clarity",
                    "reason": "Part of test implementation",
                    "priority": "low"
                },
                {
                    "type": "action_deferred",
                    "observation": "README.md is outdated",
                    "reason": "I am in Flow 3 (Build), so I ignored the outdated README",
                    "suggested_action": "Add to Flow 7 backlog",
                    "target_flow": "7-wisdom",
                    "priority": "medium"
                },
                {
                    "type": "optimization_opportunity",
                    "observation": "Duplicate code pattern detected in auth module"
                },
                {
                    "type": "pattern_detected",
                    "observation": "Recurring error handling approach"
                }
            ]
        }
        errors = list(handoff_envelope_validator.iter_errors(envelope))
        assert len(errors) == 0, f"Observation validation failed: {errors}"

    def test_observation_type_enum_values(self, handoff_envelope_validator):
        """Test all valid observation type enum values."""
        valid_types = ["action_taken", "action_deferred", "optimization_opportunity", "pattern_detected"]
        for obs_type in valid_types:
            envelope = {
                "status": "VERIFIED",
                "summary": "test",
                "routing_signal": self._minimal_routing_signal(),
                "observations": [
                    {
                        "type": obs_type,
                        "observation": f"Testing {obs_type}"
                    }
                ]
            }
            errors = list(handoff_envelope_validator.iter_errors(envelope))
            assert len(errors) == 0, f"Observation type {obs_type} failed: {errors}"

    def test_invalid_observation_type(self, handoff_envelope_validator):
        """Test invalid observation type enum value."""
        envelope = {
            "status": "VERIFIED",
            "summary": "test",
            "routing_signal": self._minimal_routing_signal(),
            "observations": [
                {
                    "type": "invalid_type",
                    "observation": "Should fail"
                }
            ]
        }
        errors = list(handoff_envelope_validator.iter_errors(envelope))
        assert len(errors) > 0, "Expected validation error for invalid observation type"

    def test_observation_requires_type_and_observation(self, handoff_envelope_validator):
        """Test that observation requires type and observation fields."""
        envelope = {
            "status": "VERIFIED",
            "summary": "test",
            "routing_signal": self._minimal_routing_signal(),
            "observations": [
                {
                    "type": "action_taken"
                    # Missing: observation
                }
            ]
        }
        errors = list(handoff_envelope_validator.iter_errors(envelope))
        assert len(errors) > 0, "Expected validation error for missing observation field"

    def test_valid_station_opinions_array(self, handoff_envelope_validator):
        """Test valid station_opinions array structure."""
        envelope = {
            "status": "UNVERIFIED",
            "summary": "Step with opinions",
            "routing_signal": self._minimal_routing_signal(),
            "station_opinions": [
                {
                    "kind": "suggest_detour",
                    "suggested_action": "Run clarifier to resolve ambiguous requirements",
                    "reason": "AC-003 has multiple interpretations",
                    "evidence_paths": ["plan/requirements.md", "signal/bdd.feature"],
                    "confidence": 0.85
                },
                {
                    "kind": "suggest_repeat",
                    "suggested_action": "Re-run test-author with updated context",
                    "reason": "New edge case discovered"
                },
                {
                    "kind": "suggest_subflow_injection",
                    "suggested_action": "Inject security-scanner subflow",
                    "reason": "Authentication code modified",
                    "confidence": 0.9
                },
                {
                    "kind": "suggest_defer_to_wisdom",
                    "suggested_action": "Analyze recurring test flakiness pattern",
                    "reason": "Third flaky test this sprint"
                },
                {
                    "kind": "flag_concern",
                    "suggested_action": "Review hardcoded timeout values",
                    "reason": "May cause issues in CI environment"
                }
            ]
        }
        errors = list(handoff_envelope_validator.iter_errors(envelope))
        assert len(errors) == 0, f"Station opinions validation failed: {errors}"

    def test_station_opinion_kind_enum_values(self, handoff_envelope_validator):
        """Test all valid station_opinion kind enum values."""
        valid_kinds = [
            "suggest_detour",
            "suggest_repeat",
            "suggest_subflow_injection",
            "suggest_defer_to_wisdom",
            "flag_concern"
        ]
        for kind in valid_kinds:
            envelope = {
                "status": "VERIFIED",
                "summary": "test",
                "routing_signal": self._minimal_routing_signal(),
                "station_opinions": [
                    {
                        "kind": kind,
                        "suggested_action": f"Testing {kind}",
                        "reason": "Test reason"
                    }
                ]
            }
            errors = list(handoff_envelope_validator.iter_errors(envelope))
            assert len(errors) == 0, f"Opinion kind {kind} failed: {errors}"

    def test_invalid_station_opinion_kind(self, handoff_envelope_validator):
        """Test invalid station_opinion kind enum value."""
        envelope = {
            "status": "VERIFIED",
            "summary": "test",
            "routing_signal": self._minimal_routing_signal(),
            "station_opinions": [
                {
                    "kind": "invalid_kind",
                    "suggested_action": "Should fail",
                    "reason": "Invalid kind"
                }
            ]
        }
        errors = list(handoff_envelope_validator.iter_errors(envelope))
        assert len(errors) > 0, "Expected validation error for invalid station opinion kind"

    def test_station_opinion_confidence_range(self, handoff_envelope_validator):
        """Test station_opinion confidence range (0-1)."""
        # Valid range
        for confidence in [0, 0.5, 1]:
            envelope = {
                "status": "VERIFIED",
                "summary": "test",
                "routing_signal": self._minimal_routing_signal(),
                "station_opinions": [
                    {
                        "kind": "suggest_detour",
                        "suggested_action": "test",
                        "reason": "test",
                        "confidence": confidence
                    }
                ]
            }
            errors = list(handoff_envelope_validator.iter_errors(envelope))
            assert len(errors) == 0, f"Confidence {confidence} failed: {errors}"

        # Invalid: above 1
        envelope = {
            "status": "VERIFIED",
            "summary": "test",
            "routing_signal": self._minimal_routing_signal(),
            "station_opinions": [
                {
                    "kind": "suggest_detour",
                    "suggested_action": "test",
                    "reason": "test",
                    "confidence": 1.5
                }
            ]
        }
        errors = list(handoff_envelope_validator.iter_errors(envelope))
        assert len(errors) > 0, "Expected validation error for confidence > 1"

    def test_station_opinion_requires_kind_action_reason(self, handoff_envelope_validator):
        """Test that station_opinion requires kind, suggested_action, and reason."""
        # Missing kind
        envelope = {
            "status": "VERIFIED",
            "summary": "test",
            "routing_signal": self._minimal_routing_signal(),
            "station_opinions": [
                {
                    "suggested_action": "test",
                    "reason": "test"
                }
            ]
        }
        errors = list(handoff_envelope_validator.iter_errors(envelope))
        assert len(errors) > 0, "Expected validation error for missing kind"

        # Missing suggested_action
        envelope["station_opinions"] = [{"kind": "suggest_detour", "reason": "test"}]
        errors = list(handoff_envelope_validator.iter_errors(envelope))
        assert len(errors) > 0, "Expected validation error for missing suggested_action"

        # Missing reason
        envelope["station_opinions"] = [{"kind": "suggest_detour", "suggested_action": "test"}]
        errors = list(handoff_envelope_validator.iter_errors(envelope))
        assert len(errors) > 0, "Expected validation error for missing reason"

    def test_valid_artifact_reference(self, handoff_envelope_validator):
        """Test valid artifact reference structure."""
        envelope = {
            "status": "VERIFIED",
            "summary": "test",
            "routing_signal": self._minimal_routing_signal(),
            "artifacts": [
                {
                    "path": "build/test_summary.md",
                    "action": "created",
                    "description": "Test execution summary",
                    "hash": "abc123",
                    "size_bytes": 1024
                },
                {
                    "path": "build/receipt.json",
                    "action": "modified"
                }
            ]
        }
        errors = list(handoff_envelope_validator.iter_errors(envelope))
        assert len(errors) == 0, f"Artifact validation failed: {errors}"

    def test_artifact_action_enum_values(self, handoff_envelope_validator):
        """Test all valid artifact action enum values."""
        for action in ["created", "modified", "read", "deleted"]:
            envelope = {
                "status": "VERIFIED",
                "summary": "test",
                "routing_signal": self._minimal_routing_signal(),
                "artifacts": [
                    {"path": "test/file.md", "action": action}
                ]
            }
            errors = list(handoff_envelope_validator.iter_errors(envelope))
            assert len(errors) == 0, f"Action {action} failed: {errors}"

    def test_valid_file_change(self, handoff_envelope_validator):
        """Test valid file_changes structure."""
        envelope = {
            "status": "VERIFIED",
            "summary": "test",
            "routing_signal": self._minimal_routing_signal(),
            "file_changes": [
                {
                    "path": "src/auth.py",
                    "change_type": "modified",
                    "lines_added": 15,
                    "lines_removed": 3,
                    "summary": "Added password validation"
                },
                {
                    "path": "src/utils.py",
                    "change_type": "renamed",
                    "old_path": "src/helpers.py"
                }
            ]
        }
        errors = list(handoff_envelope_validator.iter_errors(envelope))
        assert len(errors) == 0, f"File change validation failed: {errors}"

    def test_file_change_type_enum_values(self, handoff_envelope_validator):
        """Test all valid file change_type enum values."""
        for change_type in ["added", "modified", "deleted", "renamed"]:
            envelope = {
                "status": "VERIFIED",
                "summary": "test",
                "routing_signal": self._minimal_routing_signal(),
                "file_changes": [
                    {"path": "test.py", "change_type": change_type}
                ]
            }
            errors = list(handoff_envelope_validator.iter_errors(envelope))
            assert len(errors) == 0, f"Change type {change_type} failed: {errors}"

    def test_valid_concerns_array(self, handoff_envelope_validator):
        """Test valid concerns array structure."""
        envelope = {
            "status": "UNVERIFIED",
            "summary": "test",
            "routing_signal": self._minimal_routing_signal(),
            "concerns": [
                {
                    "concern": "Test coverage below 80%",
                    "severity": "high",
                    "recommendation": "Add unit tests for edge cases"
                },
                {
                    "concern": "Minor code style inconsistency",
                    "severity": "low"
                }
            ]
        }
        errors = list(handoff_envelope_validator.iter_errors(envelope))
        assert len(errors) == 0, f"Concerns validation failed: {errors}"

    def test_concern_severity_enum_values(self, handoff_envelope_validator):
        """Test all valid concern severity enum values."""
        for severity in ["low", "medium", "high"]:
            envelope = {
                "status": "VERIFIED",
                "summary": "test",
                "routing_signal": self._minimal_routing_signal(),
                "concerns": [
                    {"concern": "test concern", "severity": severity}
                ]
            }
            errors = list(handoff_envelope_validator.iter_errors(envelope))
            assert len(errors) == 0, f"Severity {severity} failed: {errors}"


# ==============================================================================
# FlowGraph Schema Tests
# ==============================================================================

@pytest.mark.skipif(not HAS_JSONSCHEMA, reason="jsonschema not installed")
class TestFlowGraphSchema:
    """Tests for flow_graph.schema.json validation."""

    def _minimal_node(self, node_id: str = "test-node") -> dict:
        """Create a minimal valid node."""
        return {
            "node_id": node_id,
            "template_id": "test-template"
        }

    def _minimal_edge(self, edge_id: str, from_node: str, to_node: str) -> dict:
        """Create a minimal valid edge."""
        return {
            "edge_id": edge_id,
            "from": from_node,
            "to": to_node
        }

    def test_valid_minimal_flow_graph(self, flow_graph_schema):
        """Test minimal valid flow graph with required fields."""
        graph = {
            "id": "test-flow",
            "version": 1,
            "title": "Test Flow",
            "flow_number": 3,
            "nodes": [self._minimal_node()],
            "edges": []
        }
        validate(graph, flow_graph_schema)

    def test_valid_flow_number_range(self, flow_graph_schema):
        """Test valid flow_number range (1-7)."""
        for flow_num in range(1, 8):
            graph = {
                "id": "test-flow",
                "version": 1,
                "title": f"Flow {flow_num}",
                "flow_number": flow_num,
                "nodes": [self._minimal_node()],
                "edges": []
            }
            validate(graph, flow_graph_schema)

    def test_invalid_flow_number_range(self, flow_graph_schema):
        """Test invalid flow_number values."""
        # Below minimum (0 is invalid)
        graph = {
            "id": "test-flow",
            "version": 1,
            "title": "Invalid Flow",
            "flow_number": 0,
            "nodes": [self._minimal_node()],
            "edges": []
        }
        with pytest.raises(ValidationError):
            validate(graph, flow_graph_schema)

        # Above maximum (100 is invalid, schema allows 1-99)
        # Note: Schema allows 1-99 to support utility flows (8+)
        graph["flow_number"] = 100
        with pytest.raises(ValidationError):
            validate(graph, flow_graph_schema)

    def test_valid_charter_object(self, flow_graph_schema):
        """Test valid charter object with required and optional fields."""
        graph = {
            "id": "build-flow",
            "version": 1,
            "title": "Build Flow",
            "flow_number": 3,
            "nodes": [self._minimal_node()],
            "edges": [],
            "charter": {
                "goal": "Produces verified code that satisfies the AC Matrix",
                "question": "Does implementation match design?",
                "exit_criteria": [
                    "All tests pass",
                    "Coverage >= 80%",
                    "No lint errors"
                ],
                "non_goals": [
                    "Updating documentation",
                    "Refactoring unrelated code",
                    "Performance optimization"
                ],
                "prime_directive": "Maximize passing tests. Minimize changes. Only detach from Golden Path if build is blocked."
            }
        }
        validate(graph, flow_graph_schema)

    def test_charter_requires_goal_and_exit_criteria(self, flow_graph_schema):
        """Test that charter requires goal and exit_criteria."""
        # Missing goal
        graph = {
            "id": "test-flow",
            "version": 1,
            "title": "Test Flow",
            "flow_number": 3,
            "nodes": [self._minimal_node()],
            "edges": [],
            "charter": {
                "exit_criteria": ["All tests pass"]
            }
        }
        with pytest.raises(ValidationError):
            validate(graph, flow_graph_schema)

        # Missing exit_criteria
        graph["charter"] = {"goal": "Test goal"}
        with pytest.raises(ValidationError):
            validate(graph, flow_graph_schema)

    def test_charter_exit_criteria_non_empty(self, flow_graph_schema):
        """Test that exit_criteria must have at least one item."""
        graph = {
            "id": "test-flow",
            "version": 1,
            "title": "Test Flow",
            "flow_number": 3,
            "nodes": [self._minimal_node()],
            "edges": [],
            "charter": {
                "goal": "Test goal",
                "exit_criteria": []  # Empty array
            }
        }
        with pytest.raises(ValidationError):
            validate(graph, flow_graph_schema)

    def test_valid_suggested_sidequests_on_node(self, flow_graph_schema):
        """Test valid suggested_sidequests array on a node."""
        graph = {
            "id": "build-flow",
            "version": 1,
            "title": "Build Flow",
            "flow_number": 3,
            "nodes": [
                {
                    "node_id": "test-author",
                    "template_id": "test-author",
                    "suggested_sidequests": [
                        {
                            "station_id": "clarifier",
                            "typical_trigger": "When requirements have ambiguous scope",
                            "routing_type": "DETOUR",
                            "priority": 75
                        },
                        {
                            "station_id": "risk-analyst",
                            "typical_trigger": "When security-sensitive code detected"
                        },
                        {
                            "station_id": "test-microloop",
                            "typical_trigger": "When complex feature needs iterative testing",
                            "routing_type": "INJECT_FLOW",
                            "priority": 60
                        }
                    ]
                }
            ],
            "edges": []
        }
        validate(graph, flow_graph_schema)

    def test_suggested_sidequest_requires_station_id_and_trigger(self, flow_graph_schema):
        """Test that suggested_sidequest requires station_id and typical_trigger."""
        # Missing station_id
        graph = {
            "id": "test-flow",
            "version": 1,
            "title": "Test Flow",
            "flow_number": 3,
            "nodes": [
                {
                    "node_id": "test",
                    "template_id": "test",
                    "suggested_sidequests": [
                        {"typical_trigger": "When something happens"}
                    ]
                }
            ],
            "edges": []
        }
        with pytest.raises(ValidationError):
            validate(graph, flow_graph_schema)

        # Missing typical_trigger
        graph["nodes"][0]["suggested_sidequests"] = [{"station_id": "clarifier"}]
        with pytest.raises(ValidationError):
            validate(graph, flow_graph_schema)

    def test_suggested_sidequest_routing_type_enum(self, flow_graph_schema):
        """Test suggested_sidequest routing_type enum values."""
        valid_types = ["DETOUR", "INJECT_NODES", "INJECT_FLOW"]
        for routing_type in valid_types:
            graph = {
                "id": "test-flow",
                "version": 1,
                "title": "Test Flow",
                "flow_number": 3,
                "nodes": [
                    {
                        "node_id": "test",
                        "template_id": "test",
                        "suggested_sidequests": [
                            {
                                "station_id": "clarifier",
                                "typical_trigger": "test",
                                "routing_type": routing_type
                            }
                        ]
                    }
                ],
                "edges": []
            }
            validate(graph, flow_graph_schema)

        # Invalid routing_type
        graph["nodes"][0]["suggested_sidequests"][0]["routing_type"] = "INVALID"
        with pytest.raises(ValidationError):
            validate(graph, flow_graph_schema)

    def test_suggested_sidequest_priority_range(self, flow_graph_schema):
        """Test suggested_sidequest priority range (0-100)."""
        # Valid range
        for priority in [0, 50, 100]:
            graph = {
                "id": "test-flow",
                "version": 1,
                "title": "Test Flow",
                "flow_number": 3,
                "nodes": [
                    {
                        "node_id": "test",
                        "template_id": "test",
                        "suggested_sidequests": [
                            {
                                "station_id": "clarifier",
                                "typical_trigger": "test",
                                "priority": priority
                            }
                        ]
                    }
                ],
                "edges": []
            }
            validate(graph, flow_graph_schema)

        # Invalid: above 100
        graph["nodes"][0]["suggested_sidequests"][0]["priority"] = 101
        with pytest.raises(ValidationError):
            validate(graph, flow_graph_schema)

        # Invalid: below 0
        graph["nodes"][0]["suggested_sidequests"][0]["priority"] = -1
        with pytest.raises(ValidationError):
            validate(graph, flow_graph_schema)

    def test_valid_node_ui_configuration(self, flow_graph_schema):
        """Test valid node UI configuration."""
        graph = {
            "id": "test-flow",
            "version": 1,
            "title": "Test Flow",
            "flow_number": 3,
            "nodes": [
                {
                    "node_id": "load-context",
                    "template_id": "context-loader",
                    "ui": {
                        "position": {"x": 100, "y": 200},
                        "type": "step",
                        "label": "Load Context",
                        "color": "#4f46e5",
                        "icon": "folder",
                        "width": 180,
                        "height": 60,
                        "collapsed": False,
                        "hidden": False,
                        "teaching": {
                            "highlight": True,
                            "note": "Heavy context loading step"
                        }
                    }
                }
            ],
            "edges": []
        }
        validate(graph, flow_graph_schema)

    def test_node_ui_type_enum_values(self, flow_graph_schema):
        """Test all valid node UI type enum values."""
        valid_types = ["step", "agent", "artifact", "subflow", "decision", "join"]
        for ui_type in valid_types:
            graph = {
                "id": "test-flow",
                "version": 1,
                "title": "Test Flow",
                "flow_number": 3,
                "nodes": [
                    {
                        "node_id": "test",
                        "template_id": "test",
                        "ui": {"type": ui_type}
                    }
                ],
                "edges": []
            }
            validate(graph, flow_graph_schema)

    def test_valid_edge_configuration(self, flow_graph_schema):
        """Test valid edge configuration."""
        graph = {
            "id": "test-flow",
            "version": 1,
            "title": "Test Flow",
            "flow_number": 3,
            "nodes": [
                self._minimal_node("node-a"),
                self._minimal_node("node-b")
            ],
            "edges": [
                {
                    "edge_id": "e1-a-to-b",
                    "from": "node-a",
                    "to": "node-b",
                    "type": "sequence",
                    "priority": 50,
                    "condition": {
                        "field": "status",
                        "operator": "equals",
                        "value": "VERIFIED"
                    },
                    "ui": {
                        "label": "Success",
                        "style": "solid",
                        "animated": False,
                        "color": "#22c55e",
                        "width": 2,
                        "marker_end": "arrowclosed",
                        "curve_type": "bezier"
                    }
                }
            ]
        }
        validate(graph, flow_graph_schema)

    def test_edge_type_enum_values(self, flow_graph_schema):
        """Test all valid edge type enum values."""
        valid_types = ["sequence", "loop", "branch", "detour", "injection", "subflow"]
        for edge_type in valid_types:
            graph = {
                "id": "test-flow",
                "version": 1,
                "title": "Test Flow",
                "flow_number": 3,
                "nodes": [
                    self._minimal_node("node-a"),
                    self._minimal_node("node-b")
                ],
                "edges": [
                    {
                        "edge_id": "e1",
                        "from": "node-a",
                        "to": "node-b",
                        "type": edge_type
                    }
                ]
            }
            validate(graph, flow_graph_schema)

    def test_edge_condition_operators(self, flow_graph_schema):
        """Test all valid edge condition operators."""
        operators = ["equals", "not_equals", "in", "not_in", "contains", "gt", "lt", "gte", "lte", "matches"]
        for operator in operators:
            graph = {
                "id": "test-flow",
                "version": 1,
                "title": "Test Flow",
                "flow_number": 3,
                "nodes": [
                    self._minimal_node("node-a"),
                    self._minimal_node("node-b")
                ],
                "edges": [
                    {
                        "edge_id": "e1",
                        "from": "node-a",
                        "to": "node-b",
                        "condition": {
                            "field": "test_field",
                            "operator": operator,
                            "value": "test"
                        }
                    }
                ]
            }
            validate(graph, flow_graph_schema)

    def test_valid_graph_policy(self, flow_graph_schema):
        """Test valid graph policy configuration."""
        graph = {
            "id": "build-flow",
            "version": 1,
            "title": "Build Flow",
            "flow_number": 3,
            "nodes": [self._minimal_node()],
            "edges": [],
            "policy": {
                "max_depth": 5,
                "max_loop_iterations": 3,
                "suggested_detours": [
                    {
                        "from_nodes": ["test-author", "code-implement"],
                        "to_station": "clarifier",
                        "return_to": "next",
                        "max_uses": 2,
                        "priority": 70
                    }
                ],
                "suggested_injections": [
                    {
                        "station_id": "risk-analyst",
                        "inject_after": ["code-implement"],
                        "injection_type": "INJECT_NODES",
                        "one_shot": True,
                        "priority": 60
                    }
                ],
                "routing_decisions": {
                    "default_decision": "CONTINUE",
                    "decision_precedence": ["CONTINUE", "DETOUR", "INJECT_NODES"],
                    "signal_interpretation": {
                        "on_verified": "CONTINUE",
                        "on_unverified_can_iterate": "CONTINUE",
                        "on_blocked": "DETOUR"
                    }
                },
                "escalation": {
                    "on_blocked": "continue_with_concerns",
                    "max_unverified_streak": 3
                },
                "timeout": {
                    "node_timeout_seconds": 600,
                    "flow_timeout_seconds": 3600,
                    "on_timeout": "fail"
                },
                "retry": {
                    "enabled": True,
                    "max_attempts": 2,
                    "backoff_seconds": 30
                }
            }
        }
        validate(graph, flow_graph_schema)

    def test_routing_decision_enum_values(self, flow_graph_schema):
        """Test routing decision enum values in policy."""
        decisions = ["CONTINUE", "DETOUR", "INJECT_FLOW", "INJECT_NODES", "EXTEND_GRAPH"]
        for decision in decisions:
            graph = {
                "id": "test-flow",
                "version": 1,
                "title": "Test Flow",
                "flow_number": 3,
                "nodes": [self._minimal_node()],
                "edges": [],
                "policy": {
                    "routing_decisions": {
                        "default_decision": decision
                    }
                }
            }
            validate(graph, flow_graph_schema)

    def test_valid_subflow_configuration(self, flow_graph_schema):
        """Test valid subflow configuration."""
        graph = {
            "id": "build-flow",
            "version": 1,
            "title": "Build Flow",
            "flow_number": 3,
            "nodes": [
                self._minimal_node("test-author"),
                self._minimal_node("test-critic")
            ],
            "edges": [
                self._minimal_edge("e1", "test-author", "test-critic")
            ],
            "subflows": [
                {
                    "subflow_id": "test-microloop",
                    "title": "Test Microloop",
                    "description": "Author/critic loop for test quality",
                    "entry_node": "test-author",
                    "exit_nodes": ["test-critic"],
                    "contained_nodes": ["test-author", "test-critic"],
                    "ui": {
                        "color": "#fef3c7",
                        "collapsed_by_default": False,
                        "position": {"x": 100, "y": 100}
                    },
                    "policy": {
                        "allow_external_entry": False,
                        "allow_external_exit": False
                    }
                }
            ]
        }
        validate(graph, flow_graph_schema)

    def test_subflow_requires_exit_nodes(self, flow_graph_schema):
        """Test that subflow requires at least one exit_node."""
        graph = {
            "id": "test-flow",
            "version": 1,
            "title": "Test Flow",
            "flow_number": 3,
            "nodes": [self._minimal_node()],
            "edges": [],
            "subflows": [
                {
                    "subflow_id": "test-subflow",
                    "title": "Test Subflow",
                    "entry_node": "test-node",
                    "exit_nodes": []  # Empty
                }
            ]
        }
        with pytest.raises(ValidationError):
            validate(graph, flow_graph_schema)

    def test_valid_flow_transition(self, flow_graph_schema):
        """Test valid on_complete and on_failure transitions."""
        graph = {
            "id": "build-flow",
            "version": 1,
            "title": "Build Flow",
            "flow_number": 3,
            "nodes": [self._minimal_node()],
            "edges": [],
            "on_complete": {
                "next_flow": "4-review",
                "reason": "Build complete; proceed to PR review",
                "pass_artifacts": ["build/receipt.json", "build/test_summary.md"]
            },
            "on_failure": {
                "next_flow": "2-plan",
                "reason": "Implementation issues may require design changes"
            }
        }
        validate(graph, flow_graph_schema)

    def test_flow_transition_next_flow_pattern(self, flow_graph_schema):
        """Test next_flow accepts various valid formats.

        The FlowTransition schema allows any string for next_flow to support:
        - Main SDLC flows: "1-signal", "2-plan", etc.
        - Utility flow special values: "return", "pause"
        - Custom flow identifiers

        No pattern validation is enforced at the schema level.
        """
        # Valid patterns - main SDLC flows
        valid_flows = ["1-signal", "2-plan", "3-build", "4-review", "5-gate", "6-deploy", "7-wisdom"]
        for next_flow in valid_flows:
            graph = {
                "id": "test-flow",
                "version": 1,
                "title": "Test Flow",
                "flow_number": 3,
                "nodes": [self._minimal_node()],
                "edges": [],
                "on_complete": {"next_flow": next_flow}
            }
            validate(graph, flow_graph_schema)

        # Valid patterns - utility flow special values
        for special_value in ["return", "pause"]:
            graph = {
                "id": "test-flow",
                "version": 1,
                "title": "Test Flow",
                "flow_number": 8,  # Utility flow
                "nodes": [self._minimal_node()],
                "edges": [],
                "on_complete": {"next_flow": special_value}
            }
            validate(graph, flow_graph_schema)

    def test_id_pattern_validation(self, flow_graph_schema):
        """Test graph ID pattern validation."""
        # Valid IDs
        valid_ids = ["build-flow", "test", "my-flow-123"]
        for graph_id in valid_ids:
            graph = {
                "id": graph_id,
                "version": 1,
                "title": "Test Flow",
                "flow_number": 3,
                "nodes": [self._minimal_node()],
                "edges": []
            }
            validate(graph, flow_graph_schema)

        # Invalid IDs (must start with lowercase letter)
        invalid_ids = ["123-flow", "Build-Flow", "_flow", "-flow"]
        for graph_id in invalid_ids:
            graph["id"] = graph_id
            with pytest.raises(ValidationError):
                validate(graph, flow_graph_schema)

    def test_node_id_pattern_validation(self, flow_graph_schema):
        """Test node_id pattern validation."""
        # Valid node IDs
        valid_node_ids = ["test-node", "test_node", "test123", "a"]
        for node_id in valid_node_ids:
            graph = {
                "id": "test-flow",
                "version": 1,
                "title": "Test Flow",
                "flow_number": 3,
                "nodes": [{"node_id": node_id, "template_id": "test"}],
                "edges": []
            }
            validate(graph, flow_graph_schema)

        # Invalid node IDs
        invalid_node_ids = ["123node", "Test-Node", "_node", "-node"]
        for node_id in invalid_node_ids:
            graph["nodes"] = [{"node_id": node_id, "template_id": "test"}]
            with pytest.raises(ValidationError):
                validate(graph, flow_graph_schema)

    def test_required_fields_missing(self, flow_graph_schema):
        """Test that required fields are enforced."""
        base = {
            "version": 1,
            "title": "Test",
            "flow_number": 3,
            "nodes": [self._minimal_node()],
            "edges": []
        }

        # Missing id
        with pytest.raises(ValidationError):
            validate(base, flow_graph_schema)

        # Missing version
        base["id"] = "test"
        del base["version"]
        with pytest.raises(ValidationError):
            validate(base, flow_graph_schema)

        # Missing title
        base["version"] = 1
        del base["title"]
        with pytest.raises(ValidationError):
            validate(base, flow_graph_schema)

        # Missing flow_number
        base["title"] = "Test"
        del base["flow_number"]
        with pytest.raises(ValidationError):
            validate(base, flow_graph_schema)

        # Missing nodes
        base["flow_number"] = 3
        del base["nodes"]
        with pytest.raises(ValidationError):
            validate(base, flow_graph_schema)

    def test_nodes_requires_at_least_one(self, flow_graph_schema):
        """Test that nodes array requires at least one item."""
        graph = {
            "id": "test-flow",
            "version": 1,
            "title": "Test Flow",
            "flow_number": 3,
            "nodes": [],  # Empty
            "edges": []
        }
        with pytest.raises(ValidationError):
            validate(graph, flow_graph_schema)


# ==============================================================================
# Cross-Schema Integration Tests
# ==============================================================================

@pytest.mark.skipif(not HAS_JSONSCHEMA, reason="jsonschema not installed")
class TestCrossSchemaIntegration:
    """Tests for cross-schema validation and integration."""

    def test_routing_signal_embedded_in_envelope(self, handoff_envelope_validator):
        """Test that a complete routing signal can be embedded in envelope."""
        envelope = {
            "status": "VERIFIED",
            "summary": "Test step completed",
            "routing_signal": {
                "decision": "advance",
                "confidence": "high",
                "reason": "All tests passed",
                "next_step": "code-critic",
                "why_now": {
                    "trigger": "Test coverage improved to 95%",
                    "relevance_to_charter": "Meets AC-002 coverage requirement"
                },
                "confidence_score": 0.95,
                "metadata": {
                    "station_id": "test-author",
                    "flow_id": "3-build"
                }
            },
            "observations": [
                {
                    "type": "optimization_opportunity",
                    "observation": "Could parallelize test execution"
                }
            ],
            "station_opinions": [
                {
                    "kind": "suggest_defer_to_wisdom",
                    "suggested_action": "Analyze test execution time trends",
                    "reason": "Tests taking longer each sprint",
                    "confidence": 0.7
                }
            ]
        }
        errors = list(handoff_envelope_validator.iter_errors(envelope))
        assert len(errors) == 0, f"Integration validation failed: {errors}"

    def test_flow_graph_with_all_new_fields(self, flow_graph_schema):
        """Test flow graph with all new V3 fields populated."""
        graph = {
            "id": "build-flow",
            "version": 1,
            "title": "Flow 3 - Build",
            "flow_number": 3,
            "description": "Transform design artifacts into working code",
            "charter": {
                "goal": "Produces verified code that satisfies the AC Matrix",
                "question": "Does implementation match design?",
                "exit_criteria": [
                    "All tests pass",
                    "Coverage >= 80%",
                    "No critical lint errors"
                ],
                "non_goals": [
                    "Updating documentation",
                    "Refactoring unrelated code"
                ],
                "prime_directive": "Maximize passing tests. Minimize changes."
            },
            "nodes": [
                {
                    "node_id": "test-author",
                    "template_id": "test-author",
                    "suggested_sidequests": [
                        {
                            "station_id": "clarifier",
                            "typical_trigger": "When test scenarios have ambiguous scope",
                            "routing_type": "DETOUR",
                            "priority": 70
                        }
                    ],
                    "ui": {
                        "position": {"x": 100, "y": 200},
                        "type": "step",
                        "teaching": {
                            "highlight": True,
                            "note": "Author tests based on BDD scenarios"
                        }
                    }
                },
                {
                    "node_id": "test-critic",
                    "template_id": "test-critic",
                    "suggested_sidequests": [
                        {
                            "station_id": "risk-analyst",
                            "typical_trigger": "When security test coverage is low",
                            "routing_type": "INJECT_NODES"
                        }
                    ]
                }
            ],
            "edges": [
                {
                    "edge_id": "e1-author-to-critic",
                    "from": "test-author",
                    "to": "test-critic",
                    "type": "sequence"
                },
                {
                    "edge_id": "e2-loop-back",
                    "from": "test-critic",
                    "to": "test-author",
                    "type": "loop",
                    "condition": {
                        "field": "status",
                        "operator": "equals",
                        "value": "UNVERIFIED"
                    }
                }
            ],
            "policy": {
                "max_loop_iterations": 3,
                "routing_decisions": {
                    "default_decision": "CONTINUE",
                    "signal_interpretation": {
                        "on_verified": "CONTINUE",
                        "on_blocked": "DETOUR"
                    }
                }
            },
            "on_complete": {
                "next_flow": "4-review",
                "reason": "Build complete; proceed to PR review"
            }
        }
        validate(graph, flow_graph_schema)


# ==============================================================================
# Schema File Existence Tests
# ==============================================================================

class TestSchemaFileExistence:
    """Tests for schema file existence and basic structure."""

    def test_routing_signal_schema_exists(self):
        """Test that routing_signal.schema.json exists."""
        schema_path = SCHEMA_DIR / "routing_signal.schema.json"
        assert schema_path.exists(), f"Schema file not found: {schema_path}"

    def test_handoff_envelope_schema_exists(self):
        """Test that handoff_envelope.schema.json exists."""
        schema_path = SCHEMA_DIR / "handoff_envelope.schema.json"
        assert schema_path.exists(), f"Schema file not found: {schema_path}"

    def test_flow_graph_schema_exists(self):
        """Test that flow_graph.schema.json exists."""
        schema_path = SCHEMA_DIR / "flow_graph.schema.json"
        assert schema_path.exists(), f"Schema file not found: {schema_path}"

    def test_schemas_are_valid_json(self):
        """Test that all schemas are valid JSON."""
        for schema_file in SCHEMA_DIR.glob("*.schema.json"):
            try:
                json.loads(schema_file.read_text(encoding="utf-8"))
            except json.JSONDecodeError as e:
                pytest.fail(f"Invalid JSON in {schema_file.name}: {e}")

    def test_schemas_have_required_metadata(self):
        """Test that schemas have $schema and $id fields."""
        required_schemas = [
            "routing_signal.schema.json",
            "handoff_envelope.schema.json",
            "flow_graph.schema.json"
        ]

        for schema_name in required_schemas:
            schema_path = SCHEMA_DIR / schema_name
            schema = json.loads(schema_path.read_text(encoding="utf-8"))

            assert "$schema" in schema, f"{schema_name} missing $schema"
            assert "$id" in schema, f"{schema_name} missing $id"
            assert "title" in schema, f"{schema_name} missing title"
            assert "description" in schema, f"{schema_name} missing description"
            assert "type" in schema, f"{schema_name} missing type"
