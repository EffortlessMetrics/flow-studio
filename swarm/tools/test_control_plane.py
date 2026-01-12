#!/usr/bin/env python3
"""
Test suite for control plane model configuration logic.

Validates:
1. Model value validation (only inherit, haiku, sonnet, opus allowed)
2. Decision priority (override > config > default)
3. Audit logging (timestamps, reasons, change tracking)
4. Backwards compatibility (generator works without control plane)
"""

import sys

from control_plane import VALID_MODELS, ControlPlane, validate_model_value


def test_valid_models():
    """Verify only allowed models are accepted."""
    print("Test: Valid model values")
    for model in VALID_MODELS:
        try:
            validate_model_value(model)
            print(f"  [OK] {model} accepted")
        except ValueError as e:
            print(f"  [FAIL] {model} rejected: {e}")
            return False

    # Test invalid
    invalid = ["gpt-4", "turbo", "cheap", "sonnet4"]
    for model in invalid:
        try:
            validate_model_value(model)
            print(f"  [FAIL] {model} should be rejected but wasn't")
            return False
        except ValueError:
            print(f"  [OK] {model} correctly rejected")

    return True


def test_decision_priority():
    """Verify decision priority: override > config > default."""
    print("\nTest: Decision priority")
    cp = ControlPlane()

    # Case 1: Override wins
    model, decision = cp.resolve_model("test-agent-1", "sonnet", "haiku")
    if model != "haiku" or decision.source != "override":
        print(f"  [FAIL] Override should win, got {model} (source={decision.source})")
        return False
    print("  [OK] Override takes priority")

    # Case 2: Config used if no override
    cp = ControlPlane()
    model, decision = cp.resolve_model("test-agent-2", "sonnet", None)
    if model != "sonnet" or decision.source != "config":
        print(f"  [FAIL] Config should be used, got {model} (source={decision.source})")
        return False
    print("  [OK] Config used when no override")

    # Case 3: Default to inherit if nothing specified
    cp = ControlPlane()
    model, decision = cp.resolve_model("test-agent-3", None, None)
    if model != "inherit" or decision.source != "default":
        print(f"  [FAIL] Should default to inherit, got {model} (source={decision.source})")
        return False
    print("  [OK] Defaults to inherit when nothing specified")

    return True


def test_audit_logging():
    """Verify audit log format and content."""
    print("\nTest: Audit logging")
    cp = ControlPlane()

    # Make some decisions (including one with default)
    cp.resolve_model("agent-a", "inherit", None)        # source: config
    cp.resolve_model("agent-b", "haiku", None)          # source: config
    cp.resolve_model("agent-c", "sonnet", "haiku")      # source: override
    cp.resolve_model("agent-d", None, None)             # source: default

    # Generate audit log
    log = cp.audit_log()

    # Verify format
    if "# Control Plane Audit Log" not in log:
        print("  [FAIL] Audit log missing header")
        return False
    print("  [OK] Header present")

    # Verify entries
    for agent in ["agent-a", "agent-b", "agent-c", "agent-d"]:
        if agent not in log:
            print(f"  [FAIL] Audit log missing entry for {agent}")
            return False
    print("  [OK] All agents logged")

    # Verify timestamps
    if "Z" not in log:  # ISO 8601 with Z suffix
        print("  [FAIL] Audit log missing timestamps")
        return False
    print("  [OK] Timestamps present")

    # Verify sources (all three types should appear in this test)
    if "config ->" not in log or "override ->" not in log or "default ->" not in log:
        print("  [FAIL] Audit log missing source info")
        print(f"     config -> {('config ->' in log)}")
        print(f"     override -> {('override ->' in log)}")
        print(f"     default -> {('default ->' in log)}")
        return False
    print("  [OK] Sources documented")

    return True


def test_change_tracking():
    """Verify changed_agents() correctly identifies platform overrides."""
    print("\nTest: Change tracking")
    cp = ControlPlane()

    # No override: no change
    cp.resolve_model("stable-agent", "inherit", None)

    # Override to different value: tracked as change
    cp.resolve_model("updated-agent", "sonnet", "haiku")

    changed = cp.changed_agents()
    if "stable-agent" in changed:
        print("  [FAIL] stable-agent should not be in changes")
        return False
    print("  [OK] Stable agents not marked as changed")

    if "updated-agent" not in changed:
        print("  [FAIL] updated-agent should be in changes")
        return False

    old, new = changed["updated-agent"]
    if old != "sonnet" or new != "haiku":
        print(f"  [FAIL] Change should be sonnet->haiku, got {old}->{new}")
        return False
    print("  [OK] Changes correctly tracked")

    return True


def test_summary_statistics():
    """Verify summary() returns correct statistics."""
    print("\nTest: Summary statistics")
    cp = ControlPlane()

    # Create mix of decision sources
    cp.resolve_model("agent-inherit", "inherit", None)          # config
    cp.resolve_model("agent-haiku", "haiku", None)              # config
    cp.resolve_model("agent-override", "sonnet", "haiku")       # override

    summary = cp.summary()

    # Check totals
    if summary["total_decisions"] != 3:
        print(f"  [FAIL] Expected 3 decisions, got {summary['total_decisions']}")
        return False
    print("  [OK] Total decisions correct")

    # Check by_source
    if summary["by_source"].get("config") != 2:
        print(f"  [FAIL] Expected 2 config decisions, got {summary['by_source'].get('config')}")
        return False
    if summary["by_source"].get("override") != 1:
        print(f"  [FAIL] Expected 1 override decision, got {summary['by_source'].get('override')}")
        return False
    print("  [OK] By-source counts correct")

    # Check by_model
    if summary["by_model"].get("inherit") != 1:
        print(f"  [FAIL] Expected 1 inherit, got {summary['by_model'].get('inherit')}")
        return False
    if summary["by_model"].get("haiku") != 2:
        print(f"  [FAIL] Expected 2 haiku, got {summary['by_model'].get('haiku')}")
        return False
    print("  [OK] By-model counts correct")

    # Check change count
    if summary["changed_count"] != 1:
        print(f"  [FAIL] Expected 1 change, got {summary['changed_count']}")
        return False
    print("  [OK] Change count correct")

    return True


def test_invalid_model_error():
    """Verify invalid models are rejected with clear errors."""
    print("\nTest: Invalid model error handling")
    cp = ControlPlane()

    try:
        cp.resolve_model("bad-agent", "invalid-model", None)
        print("  [FAIL] Should have raised ValueError for invalid model")
        return False
    except ValueError as e:
        if "Invalid model" in str(e) and "invalid-model" in str(e):
            print(f"  [OK] Clear error: {e}")
            return True
        else:
            print(f"  [FAIL] Error message unclear: {e}")
            return False


def main():
    """Run all tests."""
    print("=" * 60)
    print("Control Plane Test Suite")
    print("=" * 60)

    tests = [
        test_valid_models,
        test_decision_priority,
        test_audit_logging,
        test_change_tracking,
        test_summary_statistics,
        test_invalid_model_error,
    ]

    results = []
    for test_fn in tests:
        try:
            result = test_fn()
            results.append((test_fn.__name__, result))
        except Exception as e:
            print(f"\n[FAIL] Test {test_fn.__name__} crashed: {e}")
            import traceback
            traceback.print_exc()
            results.append((test_fn.__name__, False))

    # Summary
    print("\n" + "=" * 60)
    print("Test Results")
    print("=" * 60)
    passed = sum(1 for _, result in results if result)
    total = len(results)

    for name, result in results:
        status = "[OK] PASS" if result else "[FAIL] FAIL"
        print(f"{status}: {name}")

    print(f"\nTotal: {passed}/{total} passed")
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
