"""
Test suite for capability registry validation (FR-007).

Tests the validator's ability to ensure capability claims have evidence
and that BDD @cap: tags reference valid capabilities.

BDD Scenarios covered:
- Scenario 1: Valid capability registry with all evidence (happy path)
- Scenario 2: Missing capability registry returns warning (optional file)
- Scenario 3: Implemented capability without test evidence fails
- Scenario 4: Implemented capability without code evidence fails
- Scenario 5: BDD @cap: tag references non-existent capability fails
- Scenario 6: Aspirational capability without evidence passes
- Scenario 7: Supported capability without tests passes (only code required)
"""

import pytest
from pathlib import Path


# ============================================================================
# Helper Functions
# ============================================================================


def create_capability_registry(repo_path: Path, content: str) -> Path:
    """Create specs/capabilities.yaml with given content."""
    specs_dir = repo_path / "specs"
    specs_dir.mkdir(parents=True, exist_ok=True)
    registry_path = specs_dir / "capabilities.yaml"
    registry_path.write_text(content, encoding="utf-8")
    return registry_path


def create_feature_file(repo_path: Path, name: str, content: str) -> Path:
    """Create a feature file in features/ directory."""
    features_dir = repo_path / "features"
    features_dir.mkdir(parents=True, exist_ok=True)
    feature_path = features_dir / f"{name}.feature"
    feature_path.write_text(content, encoding="utf-8")
    return feature_path


# ============================================================================
# Happy Path Tests
# ============================================================================


def test_valid_capability_registry(temp_repo, run_validator):
    """
    Scenario 1: Valid capability registry with all evidence.

    Given: A capability registry with implemented capabilities
    And: Each implemented capability has code and test evidence
    When: I run the validator
    Then: Validator passes with no capability errors
    """
    create_capability_registry(temp_repo, """
version: 1
surfaces:
  receipts:
    description: "Test surface"
    capabilities:
      - id: receipts.required_fields
        status: implemented
        summary: "Test capability"
        evidence:
          code:
            - path: swarm/runtime/receipt_io.py
              symbol: StepReceiptData
          tests:
            - kind: unit
              ref: tests/test_receipt_io.py
""")

    result = run_validator(temp_repo)
    # Should pass (no CAPABILITY errors)
    assert "CAPABILITY Errors" not in result.stderr


def test_missing_capability_registry_is_warning(temp_repo, run_validator):
    """
    Scenario 2: Missing capability registry returns warning.

    Given: No specs/capabilities.yaml file
    When: I run the validator
    Then: Validator passes (optional file)
    And: A warning is emitted about missing registry
    """
    # Don't create any capability registry
    result = run_validator(temp_repo)
    # Should pass - registry is optional
    assert result.returncode == 0


# ============================================================================
# Validation Error Tests
# ============================================================================


def test_implemented_without_test_evidence_fails(temp_repo, run_validator):
    """
    Scenario 3: Implemented capability without test evidence fails.

    Given: A capability with status 'implemented'
    And: No test evidence in the evidence section
    When: I run the validator
    Then: Validator fails with CAPABILITY error
    And: Error mentions missing test evidence
    """
    create_capability_registry(temp_repo, """
version: 1
surfaces:
  test:
    description: "Test surface"
    capabilities:
      - id: test.no_tests
        status: implemented
        summary: "Missing test evidence"
        evidence:
          code:
            - path: src/test.py
""")

    result = run_validator(temp_repo)
    assert "CAPABILITY" in result.stderr
    assert "no test evidence" in result.stderr


def test_implemented_without_code_evidence_fails(temp_repo, run_validator):
    """
    Scenario 4: Implemented capability without code evidence fails.

    Given: A capability with status 'implemented'
    And: No code evidence in the evidence section
    When: I run the validator
    Then: Validator fails with CAPABILITY error
    And: Error mentions missing code evidence
    """
    create_capability_registry(temp_repo, """
version: 1
surfaces:
  test:
    description: "Test surface"
    capabilities:
      - id: test.no_code
        status: implemented
        summary: "Missing code evidence"
        evidence:
          tests:
            - kind: unit
              ref: tests/test_something.py
""")

    result = run_validator(temp_repo)
    assert "CAPABILITY" in result.stderr
    assert "no code evidence" in result.stderr


def test_bdd_cap_tag_references_nonexistent_capability(temp_repo, run_validator):
    """
    Scenario 5: BDD @cap: tag references non-existent capability fails.

    Given: A BDD feature file with @cap:nonexistent tag
    And: No capability with id 'nonexistent' in registry
    When: I run the validator
    Then: Validator fails with CAPABILITY error
    And: Error mentions the invalid tag
    """
    # Create registry without the referenced capability
    create_capability_registry(temp_repo, """
version: 1
surfaces:
  test:
    description: "Test surface"
    capabilities:
      - id: test.exists
        status: implemented
        summary: "Existing capability"
        evidence:
          code:
            - path: src/test.py
          tests:
            - kind: unit
              ref: tests/test.py
""")

    # Create feature file with invalid @cap: tag
    create_feature_file(temp_repo, "test", """
Feature: Test feature

  @cap:test.nonexistent
  Scenario: Test scenario
    Given something
    Then something else
""")

    result = run_validator(temp_repo)
    assert "CAPABILITY" in result.stderr
    assert "test.nonexistent" in result.stderr
    assert "not in registry" in result.stderr


# ============================================================================
# Status-Based Tests
# ============================================================================


def test_aspirational_without_evidence_passes(temp_repo, run_validator):
    """
    Scenario 6: Aspirational capability without evidence passes.

    Given: A capability with status 'aspirational'
    And: No code or test evidence
    When: I run the validator
    Then: Validator passes (aspirational doesn't need evidence)
    """
    create_capability_registry(temp_repo, """
version: 1
surfaces:
  test:
    description: "Test surface"
    capabilities:
      - id: test.future
        status: aspirational
        summary: "Future capability"
        evidence:
          design:
            - path: docs/DESIGN.md
""")

    result = run_validator(temp_repo)
    # Should pass - aspirational doesn't need code/test evidence
    assert "CAPABILITY Errors" not in result.stderr


def test_supported_without_tests_passes(temp_repo, run_validator):
    """
    Scenario 7: Supported capability without tests passes.

    Given: A capability with status 'supported'
    And: Code evidence but no test evidence
    When: I run the validator
    Then: Validator passes (supported only requires code)
    """
    create_capability_registry(temp_repo, """
version: 1
surfaces:
  test:
    description: "Test surface"
    capabilities:
      - id: test.partial
        status: supported
        summary: "Partially tested capability"
        notes: "Tests incomplete"
        evidence:
          code:
            - path: src/test.py
""")

    result = run_validator(temp_repo)
    # Should pass - supported only requires code evidence
    assert "CAPABILITY Errors" not in result.stderr


# ============================================================================
# Edge Cases
# ============================================================================


def test_valid_cap_tag_passes(temp_repo, run_validator):
    """Valid @cap: tag that references existing capability passes."""
    create_capability_registry(temp_repo, """
version: 1
surfaces:
  test:
    description: "Test surface"
    capabilities:
      - id: test.feature
        status: implemented
        summary: "Test capability"
        evidence:
          code:
            - path: src/test.py
          tests:
            - kind: bdd
              ref: "@cap:test.feature"
""")

    create_feature_file(temp_repo, "test", """
Feature: Test feature

  @cap:test.feature
  Scenario: Test scenario
    Given something
    Then something else
""")

    result = run_validator(temp_repo)
    # Should pass - tag references valid capability
    assert "CAPABILITY Errors" not in result.stderr


def test_multiple_surfaces_validated(temp_repo, run_validator):
    """All surfaces in registry are validated."""
    create_capability_registry(temp_repo, """
version: 1
surfaces:
  surface1:
    description: "First surface"
    capabilities:
      - id: surface1.cap1
        status: implemented
        summary: "First capability"
        evidence:
          code:
            - path: src/s1.py
          tests:
            - kind: unit
              ref: tests/test_s1.py
  surface2:
    description: "Second surface"
    capabilities:
      - id: surface2.cap1
        status: implemented
        summary: "Second capability"
        evidence:
          code:
            - path: src/s2.py
          # Missing tests - should fail
""")

    result = run_validator(temp_repo)
    assert "CAPABILITY" in result.stderr
    assert "surface2.cap1" in result.stderr
