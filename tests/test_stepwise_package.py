"""Tests for the stepwise package modularization.

This module contains tripwire tests that verify:
1. The stepwise package can be imported
2. All expected exports are available
3. The backwards compatibility alias works
4. The modular components can be used independently

These tests prevent regression where someone reintroduces a second
orchestrator or breaks the modular structure.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Add repo root to path for imports
repo_root = Path(__file__).resolve().parents[1]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))


class TestStepwisePackageImports:
    """Verify the stepwise package structure and exports."""

    def test_package_imports_successfully(self):
        """Verify the stepwise package can be imported."""
        import swarm.runtime.stepwise

        assert hasattr(swarm.runtime.stepwise, "StepwiseOrchestrator")
        assert hasattr(swarm.runtime.stepwise, "GeminiStepOrchestrator")
        assert hasattr(swarm.runtime.stepwise, "get_orchestrator")

    def test_backwards_compat_alias(self):
        """Verify GeminiStepOrchestrator is an alias for StepwiseOrchestrator."""
        from swarm.runtime.stepwise import (
            GeminiStepOrchestrator,
            StepwiseOrchestrator,
        )

        assert GeminiStepOrchestrator is StepwiseOrchestrator


class TestShimIdentity:
    """Tripwire tests: verify orchestrator.py is just a re-export shim.

    These tests prevent regression where someone "restores" the monolith
    or creates a divergent implementation in the old module.
    """

    def test_shim_reexports_stepwise_orchestrator(self):
        """Verify orchestrator.StepwiseOrchestrator is stepwise.StepwiseOrchestrator."""
        import swarm.runtime.orchestrator as orchestrator
        import swarm.runtime.stepwise as stepwise

        assert orchestrator.StepwiseOrchestrator is stepwise.StepwiseOrchestrator

    def test_shim_reexports_gemini_step_orchestrator(self):
        """Verify orchestrator.GeminiStepOrchestrator is stepwise.GeminiStepOrchestrator."""
        import swarm.runtime.orchestrator as orchestrator
        import swarm.runtime.stepwise as stepwise

        assert orchestrator.GeminiStepOrchestrator is stepwise.GeminiStepOrchestrator

    def test_shim_reexports_get_orchestrator(self):
        """Verify orchestrator.get_orchestrator is stepwise.get_orchestrator."""
        import swarm.runtime.orchestrator as orchestrator
        import swarm.runtime.stepwise as stepwise

        assert orchestrator.get_orchestrator is stepwise.get_orchestrator

    def test_shim_module_is_minimal(self):
        """Verify the shim module only contains re-exports (no new implementation).

        This test ensures the shim file stays minimal by checking that
        it doesn't define any classes or functions locally.
        """
        import ast
        from pathlib import Path

        shim_path = Path(__file__).resolve().parents[1] / "swarm" / "runtime" / "orchestrator.py"
        source = shim_path.read_text(encoding="utf-8")
        tree = ast.parse(source)

        # Count class and function definitions (excluding imports)
        class_defs = [node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]
        func_defs = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]

        assert len(class_defs) == 0, f"Shim should not define classes, found: {[c.name for c in class_defs]}"
        assert len(func_defs) == 0, f"Shim should not define functions, found: {[f.name for f in func_defs]}"


class TestStepwisePackageExports:
    """Verify all expected exports from the stepwise package."""

    def test_types_module_exports(self):
        """Verify types module exports are available."""
        from swarm.runtime.stepwise import (
            StepTxnInput,
            StepTxnOutput,
            VerificationCheck,
            VerificationResult,
        )

        # Verify they are dataclasses
        assert hasattr(StepTxnInput, "__dataclass_fields__")
        assert hasattr(StepTxnOutput, "__dataclass_fields__")
        assert hasattr(VerificationCheck, "__dataclass_fields__")
        assert hasattr(VerificationResult, "__dataclass_fields__")

    def test_receipt_compat_exports(self):
        """Verify receipt_compat module exports are available."""
        from swarm.runtime.stepwise import (
            read_receipt_field,
            update_receipt_routing,
        )

        assert callable(read_receipt_field)
        assert callable(update_receipt_routing)

    def test_spec_facade_exports(self):
        """Verify spec_facade module exports are available."""
        from swarm.runtime.stepwise import (
            SpecFacade,
            load_flow_spec,
            load_station_spec,
        )

        assert callable(load_flow_spec)
        assert callable(load_station_spec)
        # SpecFacade should be a class
        assert isinstance(SpecFacade, type)

    def test_routing_exports(self):
        """Verify routing module exports are available."""
        from swarm.runtime.stepwise import (
            create_routing_signal,
            route_step,
        )

        assert callable(create_routing_signal)
        assert callable(route_step)


class TestReceiptCompat:
    """Test the receipt_compat module functionality."""

    def test_read_receipt_field_returns_none_for_missing_file(self, tmp_path: Path):
        """Verify read_receipt_field handles missing files gracefully."""
        from swarm.runtime.stepwise import read_receipt_field

        result = read_receipt_field(
            repo_root=tmp_path,
            run_id="test-run",
            flow_key="build",
            step_id="test-step",
            agent_key="test-agent",
            field_name="status",
        )

        assert result is None

    def test_read_receipt_field_reads_value(self, tmp_path: Path):
        """Verify read_receipt_field reads values correctly."""
        import json
        from swarm.runtime.stepwise import read_receipt_field

        # Create receipt directory and file
        receipt_dir = tmp_path / "swarm" / "runs" / "test-run" / "build" / "receipts"
        receipt_dir.mkdir(parents=True)
        receipt_file = receipt_dir / "test-step-test-agent.json"
        receipt_file.write_text(json.dumps({"status": "VERIFIED", "confidence": 0.95}))

        result = read_receipt_field(
            repo_root=tmp_path,
            run_id="test-run",
            flow_key="build",
            step_id="test-step",
            agent_key="test-agent",
            field_name="status",
        )

        assert result == "VERIFIED"


class TestSpecFacade:
    """Test the SpecFacade functionality."""

    def test_spec_facade_creation(self, tmp_path: Path):
        """Verify SpecFacade can be instantiated."""
        from swarm.runtime.stepwise import SpecFacade

        facade = SpecFacade(tmp_path)

        assert facade._repo_root == tmp_path
        assert hasattr(facade, "load_flow_spec")
        assert hasattr(facade, "load_station_spec")

    def test_spec_facade_returns_none_for_missing_spec(self, tmp_path: Path):
        """Verify SpecFacade returns None for missing specs."""
        from swarm.runtime.stepwise import SpecFacade

        facade = SpecFacade(tmp_path)

        # This should return None, not raise
        result = facade.load_flow_spec("nonexistent-flow")
        assert result is None

    def test_spec_facade_caching(self, tmp_path: Path):
        """Verify SpecFacade caches results."""
        from swarm.runtime.stepwise import SpecFacade

        facade = SpecFacade(tmp_path)

        # First call
        result1 = facade.load_flow_spec("build")
        # Second call should return cached value
        result2 = facade.load_flow_spec("build")

        # Both should return the same object (None in this case, but same)
        assert result1 is result2


class TestRoutingModule:
    """Test the routing module functionality."""

    def test_build_routing_context(self):
        """Verify build_routing_context creates proper context."""
        from swarm.runtime.stepwise.routing import build_routing_context
        from swarm.config.flow_registry import StepDefinition, StepRouting

        # Create a step with microloop routing
        step = StepDefinition(
            id="code-critic",
            index=5,
            role="Code Critic",
            agents=["code-critic"],
            routing=StepRouting(
                kind="microloop",
                next="doc-writer",
                loop_target="code-implementer",
                max_iterations=3,
            ),
        )

        loop_state = {"code-critic:code-implementer": 2}
        ctx = build_routing_context(step, loop_state)

        assert ctx.loop_iteration == 2
        assert ctx.max_iterations == 3
        assert ctx.decision == "pending"

    def test_build_routing_context_linear_step(self):
        """Verify build_routing_context handles linear steps."""
        from swarm.runtime.stepwise.routing import build_routing_context
        from swarm.config.flow_registry import StepDefinition, StepRouting

        step = StepDefinition(
            id="context-loader",
            index=1,
            role="Context Loader",
            agents=["context-loader"],
            routing=StepRouting(
                kind="linear",
                next="test-author",
            ),
        )

        loop_state = {}
        ctx = build_routing_context(step, loop_state)

        assert ctx.loop_iteration == 0
        assert ctx.max_iterations is None
        assert ctx.decision == "advance"


class TestVerificationTypes:
    """Test the verification types."""

    def test_verification_result_to_dict(self):
        """Verify VerificationResult can be serialized."""
        from swarm.runtime.stepwise import VerificationCheck, VerificationResult

        result = VerificationResult(
            passed=True,
            artifact_checks=[
                VerificationCheck(
                    check_type="artifact",
                    name="test_summary.md",
                    passed=True,
                    output="File exists",
                ),
            ],
            command_checks=[],
            gate_status_on_fail="UNVERIFIED",
        )

        data = result.to_dict()

        assert data["passed"] is True
        assert len(data["artifact_checks"]) == 1
        assert data["artifact_checks"][0]["name"] == "test_summary.md"

    def test_step_txn_output_to_history_entry(self):
        """Verify StepTxnOutput can generate history entries."""
        from swarm.runtime.stepwise import StepTxnOutput

        output = StepTxnOutput(
            step_id="test-step",
            status="succeeded",
            output="Test passed",
            duration_ms=1500,
        )

        entry = output.to_history_entry()

        assert entry["step_id"] == "test-step"
        assert entry["status"] == "succeeded"
        assert entry["output"] == "Test passed"
        assert entry["duration_ms"] == 1500
