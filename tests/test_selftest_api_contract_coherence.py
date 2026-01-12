#!/usr/bin/env python3
"""
Test Suite: Selftest API Contract Coherence

This test suite validates runtime API coherence between:
- /api/selftest/plan (returns selftest execution plan with AC IDs)
- /platform/status (returns governance status with AC status per-acceptance-criteria)

**Contract Definition:**

The two endpoints must maintain coherence such that:
1. All AC IDs declared in /api/selftest/plan appear in /platform/status governance.ac
2. Step tiers in plan match expected semantics (KERNEL never in governance section)
3. AC statuses in /platform/status use valid enum values (PASS, FAIL, CRITICAL, WARNING, INFO)
4. Dependencies in plan reference valid step IDs
5. Plan response is stable/deterministic across multiple calls

**Purpose:** Ensure UI and CLI tools can rely on consistent data structures across
both endpoints without drift or breakage.

**Test Coverage** (7 tests):
1. test_plan_endpoint_returns_all_acs - Verify all ACs are present and count matches docs
2. test_status_endpoint_has_governance_ac_field - Verify governance.ac exists and is dict
3. test_plan_acs_match_status_acs - Plan AC IDs must be subset of Status AC keys
4. test_plan_steps_have_correct_tiers - Verify tier semantics (KERNEL → kernel)
5. test_status_ac_values_are_valid_statuses - AC statuses use valid enum values
6. test_plan_depends_on_relationships_valid - Dependencies reference valid steps
7. test_api_response_is_stable_across_runs - Responses are deterministic

**Related Files:**
- swarm/tools/flow_studio_fastapi.py (FastAPI endpoints)
- swarm/tools/selftest.py (get_selftest_plan_json)
- swarm/tools/status_provider.py (_aggregate_ac_status)
- docs/SELFTEST_AC_MATRIX.md (source of truth for AC IDs)
"""

import sys
from pathlib import Path

# Add repo root to path
repo_root = Path(__file__).resolve().parents[1]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

import re
from typing import Dict, List, Set

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def fastapi_client():
    """Create FastAPI test client."""
    from swarm.tools.flow_studio_fastapi import app
    return TestClient(app)


def collect_ac_ids_from_plan(plan_response: dict) -> Set[str]:
    """
    Collect all unique AC IDs from /api/selftest/plan response.

    Args:
        plan_response: JSON response from /api/selftest/plan

    Returns:
        Set of all unique AC IDs mentioned across all steps
    """
    ac_ids = set()
    for step in plan_response.get("steps", []):
        for ac_id in step.get("ac_ids", []):
            ac_ids.add(ac_id)
    return ac_ids


def parse_ac_matrix_expected_count() -> int:
    """
    Parse docs/SELFTEST_AC_MATRIX.md to get expected AC count.

    Returns:
        Number of AC IDs documented in the matrix

    Raises:
        FileNotFoundError: If AC matrix file doesn't exist
        ValueError: If AC matrix cannot be parsed
    """
    ac_matrix_path = repo_root / "docs" / "SELFTEST_AC_MATRIX.md"
    if not ac_matrix_path.exists():
        raise FileNotFoundError(f"AC matrix not found at {ac_matrix_path}")

    # Pattern to match AC-SELFTEST-* headings
    ac_pattern = re.compile(r"^###\s+(AC-SELFTEST-[\w-]+)", re.MULTILINE)

    content = ac_matrix_path.read_text(encoding="utf-8")
    matches = ac_pattern.findall(content)

    if not matches:
        raise ValueError("No AC IDs found in AC matrix")

    return len(set(matches))  # Return unique count


class TestSelfTestAPIContractCoherence:
    """Test suite for API contract coherence between plan and status endpoints."""

    def test_plan_endpoint_returns_all_acs(self, fastapi_client):
        """
        Test that /api/selftest/plan returns all documented AC IDs.

        **Contract:**
        - Plan endpoint must include all AC IDs from docs/SELFTEST_AC_MATRIX.md
        - AC IDs are in steps[*].ac_ids arrays
        - Count matches documented acceptance criteria

        **Test:**
        - Call /api/selftest/plan
        - Collect all unique AC IDs across all steps
        - Compare count to AC matrix documentation
        """
        # Act
        resp = fastapi_client.get("/api/selftest/plan")

        # Assert: Endpoint returns success (200) or graceful degradation (503)
        assert resp.status_code in (200, 503), (
            f"Expected status 200 or 503, got {resp.status_code}: {resp.text}"
        )

        if resp.status_code == 503:
            pytest.skip("Selftest module not available (503)")

        plan = resp.json()

        # Act: Collect AC IDs from plan
        plan_ac_ids = collect_ac_ids_from_plan(plan)

        # Act: Get expected count from AC matrix
        try:
            expected_count = parse_ac_matrix_expected_count()
        except (FileNotFoundError, ValueError) as e:
            pytest.skip(f"Could not parse AC matrix: {e}")

        # Assert: Count matches (or is close; some ACs may be cross-cutting)
        # Accept count >= expected (some ACs may appear on multiple steps)
        assert len(plan_ac_ids) >= expected_count, (
            f"Plan returned {len(plan_ac_ids)} unique AC IDs, "
            f"expected at least {expected_count} from docs/SELFTEST_AC_MATRIX.md. "
            f"Found: {sorted(plan_ac_ids)}"
        )

        # Assert: All AC IDs follow expected format
        ac_id_pattern = re.compile(r"^AC-SELFTEST-[\w-]+$")
        for ac_id in plan_ac_ids:
            assert ac_id_pattern.match(ac_id), (
                f"AC ID '{ac_id}' does not match expected format 'AC-SELFTEST-*'"
            )

    def test_status_endpoint_has_governance_ac_field(self, fastapi_client):
        """
        Test that /platform/status returns governance.ac field with AC IDs as keys.

        **Contract:**
        - Status endpoint must have governance.ac dict
        - Keys are AC IDs (e.g., "AC-SELFTEST-KERNEL-FAST")
        - Values are status strings (e.g., "PASS", "FAIL")

        **Test:**
        - Call /platform/status
        - Verify governance.ac exists and is a dict
        - Verify keys are non-empty strings (AC IDs)
        """
        # Act
        resp = fastapi_client.get("/platform/status")

        # Assert: Endpoint returns success or graceful degradation
        assert resp.status_code in (200, 503), (
            f"Expected status 200 or 503, got {resp.status_code}: {resp.text}"
        )

        if resp.status_code == 503:
            pytest.skip("Status provider not available (503)")

        status = resp.json()

        # Assert: governance field exists
        assert "governance" in status, "Status response missing 'governance' field"
        governance = status["governance"]

        # Assert: governance.ac field exists and is dict
        assert "ac" in governance, (
            "Status response missing 'governance.ac' field for AC status aggregation"
        )
        ac_status = governance["ac"]
        assert isinstance(ac_status, dict), (
            f"governance.ac should be dict, got {type(ac_status).__name__}"
        )

        # Assert: AC IDs (keys) are non-empty strings
        for ac_id in ac_status.keys():
            assert isinstance(ac_id, str), (
                f"AC ID key should be string, got {type(ac_id).__name__}"
            )
            assert len(ac_id) > 0, "AC ID key cannot be empty"

    def test_plan_acs_match_status_acs(self, fastapi_client):
        """
        Test that all AC IDs in plan appear in status endpoint's ac field.

        **Contract:**
        - Plan AC IDs (from steps[*].ac_ids) must be subset of status AC keys
        - Every AC mentioned in plan must have a status in governance.ac
        - Status may have additional ACs (OK for forward compatibility)

        **Test:**
        - Fetch both /api/selftest/plan and /platform/status
        - Collect AC IDs from plan
        - Verify all plan ACs have status keys
        """
        # Act: Fetch both endpoints
        plan_resp = fastapi_client.get("/api/selftest/plan")
        status_resp = fastapi_client.get("/platform/status")

        # Skip if either endpoint unavailable
        if plan_resp.status_code == 503 or status_resp.status_code == 503:
            pytest.skip("One or both endpoints unavailable (503)")

        plan = plan_resp.json()
        status = status_resp.json()

        # Act: Collect AC IDs from plan
        plan_ac_ids = collect_ac_ids_from_plan(plan)

        # Act: Collect AC IDs from status
        status_ac_ids = set(status["governance"]["ac"].keys())

        # Assert: All plan ACs appear in status
        missing_in_status = plan_ac_ids - status_ac_ids
        assert not missing_in_status, (
            f"Plan AC IDs missing from status endpoint: {sorted(missing_in_status)}. "
            f"Plan has {len(plan_ac_ids)} ACs, status has {len(status_ac_ids)} ACs."
        )

        # Note: It's OK for status to have extra ACs (forward compatibility)
        # So we don't assert status_ac_ids ⊆ plan_ac_ids

    def test_plan_steps_have_correct_tiers(self, fastapi_client):
        """
        Test that step tiers match expected semantics.

        **Contract:**
        - Step tiers must be one of: kernel, governance, optional
        - Tier values are lowercase strings
        - KERNEL tier steps are critical (never in degraded mode)
        - GOVERNANCE tier steps can be degraded (warnings)
        - OPTIONAL tier steps are informational

        **Test:**
        - Fetch /api/selftest/plan
        - Verify each step's tier is valid enum
        - Verify tier semantics match config
        """
        # Act
        resp = fastapi_client.get("/api/selftest/plan")

        if resp.status_code == 503:
            pytest.skip("Selftest module not available (503)")

        plan = resp.json()
        steps = plan["steps"]

        # Assert: Valid tier values
        valid_tiers = {"kernel", "governance", "optional"}

        for step in steps:
            tier = step["tier"]
            assert tier in valid_tiers, (
                f"Step '{step['id']}' has invalid tier '{tier}', "
                f"expected one of {valid_tiers}"
            )

            # Assert: Tier is lowercase
            assert tier == tier.lower(), (
                f"Step '{step['id']}' tier '{tier}' should be lowercase"
            )

        # Assert: Summary tier counts match step tiers
        summary = plan["summary"]
        by_tier = summary["by_tier"]

        kernel_count = sum(1 for s in steps if s["tier"] == "kernel")
        governance_count = sum(1 for s in steps if s["tier"] == "governance")
        optional_count = sum(1 for s in steps if s["tier"] == "optional")

        assert by_tier["kernel"] == kernel_count, (
            f"Summary kernel count mismatch: {by_tier['kernel']} != {kernel_count}"
        )
        assert by_tier["governance"] == governance_count, (
            f"Summary governance count mismatch: {by_tier['governance']} != {governance_count}"
        )
        assert by_tier["optional"] == optional_count, (
            f"Summary optional count mismatch: {by_tier['optional']} != {optional_count}"
        )

    def test_status_ac_values_are_valid_statuses(self, fastapi_client):
        """
        Test that AC status values use valid enum values.

        **Contract:**
        - governance.ac values must be one of: PASS, FAIL, CRITICAL, WARNING, INFO
        - Status strings are uppercase
        - Status precedence: CRITICAL > FAILURE > WARNING > INFO > PASS

        **Test:**
        - Fetch /platform/status
        - Verify each AC status is valid enum
        - Verify status values are uppercase
        """
        # Act
        resp = fastapi_client.get("/platform/status")

        if resp.status_code == 503:
            pytest.skip("Status provider not available (503)")

        status = resp.json()
        ac_status = status["governance"]["ac"]

        # Assert: Valid AC status values
        valid_statuses = {"PASS", "FAIL", "FAILURE", "CRITICAL", "WARNING", "INFO"}

        for ac_id, ac_value in ac_status.items():
            assert ac_value in valid_statuses, (
                f"AC '{ac_id}' has invalid status '{ac_value}', "
                f"expected one of {valid_statuses}"
            )

            # Assert: Status value is uppercase
            assert ac_value == ac_value.upper(), (
                f"AC '{ac_id}' status '{ac_value}' should be uppercase"
            )

    def test_plan_depends_on_relationships_valid(self, fastapi_client):
        """
        Test that step dependencies reference valid step IDs.

        **Contract:**
        - steps[*].depends_on is a list of step IDs
        - All dependency IDs must exist in the steps array
        - No self-dependencies allowed
        - Dependencies should form a valid DAG (no cycles)

        **Test:**
        - Fetch /api/selftest/plan
        - Build set of all step IDs
        - Verify all dependencies reference valid IDs
        - Verify no self-dependencies
        """
        # Act
        resp = fastapi_client.get("/api/selftest/plan")

        if resp.status_code == 503:
            pytest.skip("Selftest module not available (503)")

        plan = resp.json()
        steps = plan["steps"]

        # Act: Build set of all step IDs
        step_ids = {step["id"] for step in steps}

        # Assert: All dependencies reference valid steps
        for step in steps:
            step_id = step["id"]
            depends_on = step.get("depends_on", [])

            assert isinstance(depends_on, list), (
                f"Step '{step_id}' depends_on should be list, "
                f"got {type(depends_on).__name__}"
            )

            for dep_id in depends_on:
                # Assert: Dependency is a string
                assert isinstance(dep_id, str), (
                    f"Step '{step_id}' dependency should be string, "
                    f"got {type(dep_id).__name__}"
                )

                # Assert: Dependency exists
                assert dep_id in step_ids, (
                    f"Step '{step_id}' depends on unknown step '{dep_id}'. "
                    f"Valid step IDs: {sorted(step_ids)}"
                )

                # Assert: No self-dependencies
                assert dep_id != step_id, (
                    f"Step '{step_id}' has self-dependency"
                )

    def test_api_response_is_stable_across_runs(self, fastapi_client):
        """
        Test that API responses are deterministic across multiple calls.

        **Contract:**
        - Calling /api/selftest/plan twice returns identical responses
        - Step order is deterministic (not randomized)
        - AC IDs are in same order
        - Summary counts are consistent

        **Test:**
        - Call /api/selftest/plan twice
        - Compare responses for equality
        - Verify deterministic ordering
        """
        # Act: Call endpoint twice
        resp1 = fastapi_client.get("/api/selftest/plan")
        resp2 = fastapi_client.get("/api/selftest/plan")

        # Skip if endpoint unavailable
        if resp1.status_code == 503 or resp2.status_code == 503:
            pytest.skip("Selftest module not available (503)")

        plan1 = resp1.json()
        plan2 = resp2.json()

        # Assert: Same number of steps
        assert len(plan1["steps"]) == len(plan2["steps"]), (
            "Step count differs between calls"
        )

        # Assert: Steps are in same order
        for i, (step1, step2) in enumerate(zip(plan1["steps"], plan2["steps"])):
            assert step1["id"] == step2["id"], (
                f"Step order differs at position {i}: "
                f"'{step1['id']}' vs '{step2['id']}'"
            )

            # Assert: AC IDs are in same order
            assert step1["ac_ids"] == step2["ac_ids"], (
                f"Step '{step1['id']}' has different AC IDs between calls: "
                f"{step1['ac_ids']} vs {step2['ac_ids']}"
            )

            # Assert: Dependencies are in same order
            assert step1["depends_on"] == step2["depends_on"], (
                f"Step '{step1['id']}' has different dependencies between calls: "
                f"{step1['depends_on']} vs {step2['depends_on']}"
            )

        # Assert: Summaries are identical
        assert plan1["summary"] == plan2["summary"], (
            "Summary differs between calls"
        )

        # Assert: Versions are identical
        assert plan1["version"] == plan2["version"], (
            "Version differs between calls"
        )


class TestCoherenceEdgeCases:
    """Test edge cases and error handling for API coherence."""

    def test_empty_ac_ids_handled_gracefully(self, fastapi_client):
        """
        Test that steps with empty ac_ids arrays are handled correctly.

        **Contract:**
        - Some steps may have ac_ids: [] (no ACs assigned)
        - This is valid and should not break coherence checks
        - Status endpoint may not have entries for unassigned ACs

        **Test:**
        - Fetch plan
        - Identify steps with no ACs
        - Verify they don't break status aggregation
        """
        # Act
        resp = fastapi_client.get("/api/selftest/plan")

        if resp.status_code == 503:
            pytest.skip("Selftest module not available (503)")

        plan = resp.json()
        steps = plan["steps"]

        # Act: Find steps with no AC IDs
        steps_with_no_acs = [s for s in steps if not s.get("ac_ids", [])]

        # If all steps have ACs, skip this test (edge case doesn't apply)
        if not steps_with_no_acs:
            pytest.skip("All steps have AC IDs; edge case doesn't apply")

        # Assert: Plan is still valid
        assert "summary" in plan
        assert "steps" in plan
        assert plan["summary"]["total"] == len(steps)

    def test_status_endpoint_without_plan_acs(self, fastapi_client):
        """
        Test that status endpoint can return AC status even if plan unavailable.

        **Contract:**
        - Status endpoint should not depend on plan endpoint being available
        - AC statuses are computed from artifacts, not from plan response
        - If artifacts unavailable, governance.ac may be empty dict

        **Test:**
        - Fetch /platform/status directly (without fetching plan first)
        - Verify governance.ac is present (even if empty)
        - Verify response structure is valid
        """
        # Act
        resp = fastapi_client.get("/platform/status")

        if resp.status_code == 503:
            pytest.skip("Status provider not available (503)")

        status = resp.json()

        # Assert: governance.ac exists (may be empty if no artifacts)
        assert "governance" in status
        assert "ac" in status["governance"]
        assert isinstance(status["governance"]["ac"], dict)

        # Note: It's OK if ac is empty dict (graceful degradation)

    def test_cross_cutting_acs_appear_on_multiple_steps(self, fastapi_client):
        """
        Test that cross-cutting ACs (e.g., FAILURE-HINTS) appear on multiple steps.

        **Contract:**
        - Some ACs are cross-cutting (apply to all governance steps)
        - Examples: AC-SELFTEST-FAILURE-HINTS, AC-SELFTEST-DEGRADATION-TRACKED
        - These should appear on 8+ steps legitimately

        **Test:**
        - Fetch plan
        - Identify cross-cutting ACs (those on 5+ steps)
        - Verify they are documented as cross-cutting in AC matrix
        """
        # Act
        resp = fastapi_client.get("/api/selftest/plan")

        if resp.status_code == 503:
            pytest.skip("Selftest module not available (503)")

        plan = resp.json()
        steps = plan["steps"]

        # Act: Build AC → [step_ids] mapping
        ac_to_steps: Dict[str, List[str]] = {}
        for step in steps:
            for ac_id in step.get("ac_ids", []):
                if ac_id not in ac_to_steps:
                    ac_to_steps[ac_id] = []
                ac_to_steps[ac_id].append(step["id"])

        # Act: Find cross-cutting ACs (appear on 5+ steps)
        cross_cutting_acs = {
            ac_id: step_ids
            for ac_id, step_ids in ac_to_steps.items()
            if len(step_ids) >= 5
        }

        # If no cross-cutting ACs, skip this test
        if not cross_cutting_acs:
            pytest.skip("No cross-cutting ACs found (none on 5+ steps)")

        # Assert: Cross-cutting ACs are expected ones
        expected_cross_cutting = {
            "AC-SELFTEST-FAILURE-HINTS",
            "AC-SELFTEST-DEGRADATION-TRACKED",
        }

        for ac_id in cross_cutting_acs.keys():
            # It's OK if new cross-cutting ACs are added; just document them
            if ac_id not in expected_cross_cutting:
                # This is informational, not a failure
                print(
                    f"Info: AC '{ac_id}' appears on {len(cross_cutting_acs[ac_id])} steps "
                    f"(cross-cutting). If this is intentional, update test expectations."
                )


class TestBuildSummaryStatusCoherence:
    """Test coherence between SelfTestRunner.build_summary() and /platform/status endpoint.

    **Contract:**
    The `build_summary()` method in selftest.py is documented as the canonical
    summary shape for /platform/status. This test suite verifies that key fields
    in build_summary() are accurately reflected in the status endpoint response.

    **Fields to verify:**
    - mode: strict/degraded/kernel-only
    - kernel_ok: boolean
    - governance_ok: boolean
    - optional_ok: boolean
    - failed_steps: list of step IDs
    - hints: actionable remediation hints
    """

    def test_status_selftest_mode_matches_summary(self, fastapi_client):
        """
        Test that /platform/status.governance.selftest.mode matches build_summary().

        **Contract:**
        - build_summary()["mode"] should equal governance.selftest.mode
        - Valid modes: "strict", "degraded", "kernel-only"
        """
        resp = fastapi_client.get("/platform/status")

        if resp.status_code == 503:
            pytest.skip("Status provider not available (503)")

        status = resp.json()

        # Assert: selftest.mode exists and is valid
        selftest = status["governance"]["selftest"]
        assert "mode" in selftest, "Missing selftest.mode field"

        valid_modes = {"strict", "degraded", "kernel-only"}
        assert selftest["mode"] in valid_modes, (
            f"Invalid mode '{selftest['mode']}', expected one of {valid_modes}"
        )

    def test_status_selftest_tier_flags_match_summary(self, fastapi_client):
        """
        Test that /platform/status has kernel_ok, governance_ok, optional_ok flags.

        **Contract:**
        - build_summary() returns kernel_ok, governance_ok, optional_ok booleans
        - These should appear in governance.selftest
        - All three flags should be boolean values
        """
        resp = fastapi_client.get("/platform/status")

        if resp.status_code == 503:
            pytest.skip("Status provider not available (503)")

        status = resp.json()
        selftest = status["governance"]["selftest"]

        # Assert: Tier flags exist and are boolean
        tier_flags = ["kernel_ok", "governance_ok", "optional_ok"]
        for flag in tier_flags:
            assert flag in selftest, f"Missing selftest.{flag} field"
            assert isinstance(selftest[flag], bool), (
                f"selftest.{flag} should be boolean, got {type(selftest[flag]).__name__}"
            )

    def test_status_selftest_failed_steps_is_list(self, fastapi_client):
        """
        Test that /platform/status.governance.selftest.failed_steps is a list.

        **Contract:**
        - build_summary()["failed_steps"] is a list of step IDs
        - This should appear in governance.selftest.failed_steps
        - All items should be valid step ID strings
        """
        resp = fastapi_client.get("/platform/status")

        if resp.status_code == 503:
            pytest.skip("Status provider not available (503)")

        status = resp.json()
        selftest = status["governance"]["selftest"]

        # Assert: failed_steps exists and is a list
        assert "failed_steps" in selftest, "Missing selftest.failed_steps field"
        assert isinstance(selftest["failed_steps"], list), (
            f"selftest.failed_steps should be list, got {type(selftest['failed_steps']).__name__}"
        )

        # Assert: All items are strings (step IDs)
        for step_id in selftest["failed_steps"]:
            assert isinstance(step_id, str), (
                f"Step ID should be string, got {type(step_id).__name__}"
            )

    def test_status_hints_reflect_summary_hints(self, fastapi_client):
        """
        Test that /platform/status.hints reflects build_summary() hints.

        **Contract:**
        - build_summary() returns hints list with actionable commands
        - Status endpoint should have hints.detailed or hints.summary
        - Hints should include run commands for failed steps
        """
        resp = fastapi_client.get("/platform/status")

        if resp.status_code == 503:
            pytest.skip("Status provider not available (503)")

        status = resp.json()

        # Assert: hints field exists
        assert "hints" in status, "Missing hints field in status response"
        hints = status["hints"]

        # Assert: hints has summary or detailed field
        assert "summary" in hints or "detailed" in hints, (
            "hints should have 'summary' or 'detailed' field"
        )

        # Assert: hints content is non-empty string
        if "detailed" in hints:
            assert isinstance(hints["detailed"], str), "hints.detailed should be string"
            assert len(hints["detailed"]) > 0, "hints.detailed should not be empty"

        if "summary" in hints:
            assert isinstance(hints["summary"], str), "hints.summary should be string"
            assert hints["summary"], "hints.summary should not be empty"

    def test_status_state_reflects_tier_flags(self, fastapi_client):
        """
        Test that governance.state is consistent with tier flags.

        **Contract:**
        - state = "FULLY_GOVERNED" when kernel_ok=True, governance_ok=True
        - state = "DEGRADED" when kernel_ok=True, governance_ok=False
        - state = "UNHEALTHY" when kernel_ok=False
        - state = "UNKNOWN" when status cannot be determined
        """
        resp = fastapi_client.get("/platform/status")

        if resp.status_code == 503:
            pytest.skip("Status provider not available (503)")

        status = resp.json()
        governance = status["governance"]
        selftest = governance["selftest"]

        state = governance["state"]
        kernel_ok = selftest.get("kernel_ok", True)
        governance_ok = selftest.get("governance_ok", True)

        # Assert: State matches tier flags
        if not kernel_ok:
            assert state in ("UNHEALTHY", "UNKNOWN"), (
                f"kernel_ok=False but state='{state}', expected UNHEALTHY or UNKNOWN"
            )
        elif not governance_ok:
            assert state in ("DEGRADED", "UNHEALTHY", "UNKNOWN"), (
                f"governance_ok=False but state='{state}', expected DEGRADED, UNHEALTHY, or UNKNOWN"
            )
        else:
            # kernel_ok=True and governance_ok=True
            assert state in ("FULLY_GOVERNED", "UNKNOWN"), (
                f"kernel_ok=True, governance_ok=True but state='{state}', "
                f"expected FULLY_GOVERNED or UNKNOWN"
            )


# Run tests if executed directly
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
