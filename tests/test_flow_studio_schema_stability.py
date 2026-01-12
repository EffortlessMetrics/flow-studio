#!/usr/bin/env python3
"""
OpenAPI Schema Stability Tests for Flow Studio FastAPI backend.

These tests detect breaking changes to the API contract by comparing the live
schema against a committed baseline (`docs/flowstudio-openapi.json`).

## Purpose

- Prevent accidental removal of endpoints or HTTP methods
- Detect changes to OpenAPI version or API version
- Track schema evolution over time
- Enable safe API refactoring with confidence

## Usage

Run these tests during development to detect schema changes:

```bash
make validate-openapi-schema
```

Or run specific stability checks:

```bash
pytest tests/test_flow_studio_schema_stability.py -v
```

## Baseline Management

To update the baseline schema after intentional API changes:

```bash
make dump-openapi-schema
git add docs/flowstudio-openapi.json
git commit -m "Update OpenAPI schema baseline"
```

## Test Philosophy

- **Endpoints can be added** (additive changes are safe)
- **Endpoints should not be removed** (breaking change)
- **HTTP methods should not be removed from endpoints** (breaking change)
- **API version should only increase** (semver progression)
- **OpenAPI spec version should remain stable** (3.x family)

These tests implement "ratchet semantics": the schema can only grow or evolve
forward, never regress.
"""

import json
import sys
from pathlib import Path

import pytest

# Add repo root to path for imports
repo_root = Path(__file__).resolve().parents[1]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))


@pytest.fixture
def baseline_schema():
    """Load the committed baseline schema from docs/flowstudio-openapi.json.

    If the baseline doesn't exist, skip tests that require it. This allows
    tests to pass in environments where the baseline hasn't been generated yet.
    """
    baseline_path = repo_root / "docs" / "flowstudio-openapi.json"
    if not baseline_path.exists():
        pytest.skip(
            "Baseline schema not found; run 'make dump-openapi-schema' first"
        )
    return json.loads(baseline_path.read_text(encoding="utf-8"))


@pytest.fixture
def client():
    """Create a FastAPI test client for Flow Studio."""
    from fastapi.testclient import TestClient
    from swarm.tools.flow_studio_fastapi import app

    return TestClient(app)


class TestOpenAPISchemaStability:
    """Tests to detect schema regressions against committed baseline."""

    def test_openapi_version_unchanged(self, client, baseline_schema):
        """Test OpenAPI spec version hasn't changed unexpectedly.

        We stay on OpenAPI 3.x for stability. Changes to 4.x would be major
        and should be intentional.
        """
        current_schema = client.get("/openapi.json").json()
        assert current_schema["openapi"] == baseline_schema["openapi"], (
            f"OpenAPI version changed: {baseline_schema['openapi']} → "
            f"{current_schema['openapi']}"
        )

    def test_info_version_unchanged_or_increased(self, client, baseline_schema):
        """Test API version (info.version) hasn't regressed.

        Version should only increase (semver progression), not decrease or change
        arbitrarily.
        """
        current_schema = client.get("/openapi.json").json()
        current_info = current_schema["info"]
        baseline_info = baseline_schema["info"]

        # Parse major.minor version numbers for comparison
        current_ver_str = current_info["version"]
        baseline_ver_str = baseline_info["version"]

        # Simple string comparison for exact match
        if current_ver_str != baseline_ver_str:
            # Allow version increases but warn about changes
            pytest.fail(
                f"API version changed: {baseline_ver_str} → {current_ver_str}\n"
                f"If this is intentional, update the baseline with "
                f"'make dump-openapi-schema'"
            )

    def test_required_endpoints_still_documented(self, client, baseline_schema):
        """Test that all previously documented endpoints still exist.

        Removing endpoints is a breaking change. New endpoints can be added
        (additive change), but existing endpoints should remain.
        """
        current_schema = client.get("/openapi.json").json()
        current_paths = set(current_schema["paths"].keys())
        baseline_paths = set(baseline_schema["paths"].keys())

        removed = baseline_paths - current_paths
        assert not removed, (
            f"Endpoints removed from API contract: {sorted(removed)}\n"
            f"This is a breaking change. If intentional, update baseline with "
            f"'make dump-openapi-schema'"
        )

    def test_endpoint_methods_not_removed(self, client, baseline_schema):
        """Test that HTTP methods on endpoints weren't removed.

        Removing a GET, POST, etc. from an endpoint is a breaking change.
        New methods can be added, but existing methods should remain.
        """
        current_schema = client.get("/openapi.json").json()
        baseline_paths = baseline_schema["paths"]
        current_paths = current_schema["paths"]

        method_removals = []

        for path, baseline_methods in baseline_paths.items():
            if path not in current_paths:
                continue  # Already caught by test_required_endpoints_still_documented

            current_methods = current_paths.get(path, {})

            # Extract HTTP methods (get, post, put, delete, patch)
            http_methods = {"get", "post", "put", "delete", "patch", "options", "head"}
            baseline_http_methods = {
                k for k in baseline_methods.keys() if k.lower() in http_methods
            }
            current_http_methods = {
                k for k in current_methods.keys() if k.lower() in http_methods
            }

            removed_methods = baseline_http_methods - current_http_methods
            if removed_methods:
                method_removals.append((path, removed_methods))

        assert not method_removals, (
            f"HTTP methods removed from endpoints:\n" +
            "\n".join(
                f"  {path}: {sorted(methods)}"
                for path, methods in method_removals
            ) +
            f"\nThis is a breaking change. If intentional, update baseline with "
            f"'make dump-openapi-schema'"
        )

    def test_response_definitions_present(self, client, baseline_schema):
        """Test that documented endpoints have response definitions.

        This is a quality check: endpoints should document their responses
        for proper OpenAPI tooling support.
        """
        current_schema = client.get("/openapi.json").json()

        # Spot check: /api/health should have responses
        health_path = current_schema["paths"].get("/api/health", {})
        if "get" in health_path:
            assert "responses" in health_path["get"], (
                "/api/health GET missing 'responses' definition"
            )

        # Spot check: /api/flows should have responses
        flows_path = current_schema["paths"].get("/api/flows", {})
        if "get" in flows_path:
            assert "responses" in flows_path["get"], (
                "/api/flows GET missing 'responses' definition"
            )

    def test_schema_additions_logged(self, client, baseline_schema):
        """Log schema additions for review (non-failing test).

        New endpoints and methods are additive changes (safe), but we log them
        for visibility during code review.
        """
        current_schema = client.get("/openapi.json").json()

        baseline_paths = set(baseline_schema["paths"].keys())
        current_paths = set(current_schema["paths"].keys())

        added_endpoints = current_paths - baseline_paths

        if added_endpoints:
            print(
                f"\n[INFO] Schema additions detected (additive, non-breaking):\n"
                f"  New endpoints: {sorted(added_endpoints)}"
            )

    def test_baseline_schema_is_valid_json(self, baseline_schema):
        """Sanity check: ensure baseline schema is valid JSON.

        This test verifies the baseline file can be loaded and parsed.
        """
        assert isinstance(baseline_schema, dict), (
            "Baseline schema should be a JSON object"
        )
        assert "openapi" in baseline_schema, (
            "Baseline schema should have 'openapi' version field"
        )
        assert "info" in baseline_schema, (
            "Baseline schema should have 'info' metadata"
        )
        assert "paths" in baseline_schema, (
            "Baseline schema should have 'paths' definitions"
        )

    def test_baseline_matches_current_structure(self, client, baseline_schema):
        """Test that baseline and current schemas have compatible structure.

        Both should have the same top-level keys (openapi, info, paths, etc.).
        """
        current_schema = client.get("/openapi.json").json()

        baseline_keys = set(baseline_schema.keys())
        current_keys = set(current_schema.keys())

        # Allow current schema to have additional keys (additive)
        missing_keys = baseline_keys - current_keys

        assert not missing_keys, (
            f"Current schema missing keys present in baseline: {sorted(missing_keys)}"
        )


class TestOpenAPISchemaIntegration:
    """Integration tests for OpenAPI schema generation and serving."""

    def test_dump_openapi_schema_command_works(self):
        """Test that the make dump-openapi-schema command can be executed.

        This verifies the schema can be extracted programmatically.
        """
        from swarm.tools.flow_studio_fastapi import app

        # This is what 'make dump-openapi-schema' does
        schema = app.openapi()

        assert isinstance(schema, dict), "Schema should be a dictionary"
        assert "openapi" in schema, "Schema should have OpenAPI version"
        assert "paths" in schema, "Schema should document paths"

    def test_live_openapi_endpoint_matches_baseline_structure(self, client, baseline_schema):
        """Test that /openapi.json returns structurally compatible schema.

        Live endpoint should have same top-level structure as baseline.
        """
        response = client.get("/openapi.json")
        assert response.status_code == 200, "OpenAPI endpoint should return 200"

        current_schema = response.json()

        # Structural checks
        assert "openapi" in current_schema
        assert "info" in current_schema
        assert "paths" in current_schema

        # Ensure paths is not empty
        assert len(current_schema["paths"]) > 0, (
            "Schema should document at least one endpoint"
        )
