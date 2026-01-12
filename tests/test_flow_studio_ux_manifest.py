"""
Test UX Manifest Validity

Ensures ux_manifest.json exists, is valid JSON, and all referenced
paths exist in the repository.

Issue: #22
"""
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
MANIFEST_PATH = REPO_ROOT / "ux_manifest.json"


def test_ux_manifest_exists():
    """ux_manifest.json must exist at repo root."""
    assert MANIFEST_PATH.exists(), f"ux_manifest.json not found at {MANIFEST_PATH}"


def test_ux_manifest_valid_json():
    """ux_manifest.json must be valid JSON."""
    text = MANIFEST_PATH.read_text(encoding="utf-8")
    manifest = json.loads(text)
    assert isinstance(manifest, dict), "Manifest must be a JSON object"


def test_ux_manifest_required_keys():
    """ux_manifest.json must have required top-level keys."""
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    required_keys = ["name", "version", "specs", "docs", "tests", "tools"]
    for key in required_keys:
        assert key in manifest, f"Required key '{key}' missing from ux_manifest.json"


def test_ux_manifest_specs_exist():
    """All files in specs.files must exist."""
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    specs = manifest.get("specs", {})
    files = specs.get("files", [])

    for filepath in files:
        full_path = REPO_ROOT / filepath
        assert full_path.exists(), f"Spec file does not exist: {filepath}"


def test_ux_manifest_docs_exist():
    """All files in docs.files must exist."""
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    docs = manifest.get("docs", {})
    files = docs.get("files", [])

    for filepath in files:
        full_path = REPO_ROOT / filepath
        assert full_path.exists(), f"Doc file does not exist: {filepath}"


def test_ux_manifest_tests_exist():
    """All files in tests.files must exist."""
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    tests = manifest.get("tests", {})
    files = tests.get("files", [])

    for filepath in files:
        full_path = REPO_ROOT / filepath
        assert full_path.exists(), f"Test file does not exist: {filepath}"


def test_ux_manifest_tools_exist():
    """All files in tools.files must exist."""
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    tools = manifest.get("tools", {})
    files = tools.get("files", [])

    for filepath in files:
        full_path = REPO_ROOT / filepath
        assert full_path.exists(), f"Tool file does not exist: {filepath}"


def test_ux_manifest_version_format():
    """Version must follow semver-like format."""
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    version = manifest.get("version", "")

    # Should have at least major.minor.patch
    parts = version.split("-")[0].split(".")
    assert len(parts) >= 3, f"Version '{version}' should have major.minor.patch format"

    # First three parts should be numeric
    for i, part in enumerate(parts[:3]):
        assert part.isdigit(), f"Version part {i} '{part}' should be numeric"


def test_ux_manifest_sdk_methods():
    """SDK methods must include core required methods."""
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    sdk = manifest.get("sdk", {})
    methods = sdk.get("methods", [])

    method_names = {m["name"] for m in methods}

    required_methods = [
        "getState",
        "getGraphState",
        "setActiveFlow",
        "selectStep",
        "selectAgent",
        "clearSelection",
        "qsByUiid",
        "qsAllByUiidPrefix",
        # v0.5.0-flowstudio additions
        "getLayoutScreens",
        "getLayoutScreenById",
        "getAllKnownUIIDs",
    ]

    for method in required_methods:
        assert method in method_names, f"Required SDK method '{method}' not in manifest"


def test_ux_manifest_api_endpoints():
    """API endpoints must include layout_screens."""
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    api = manifest.get("api", {})
    endpoints = api.get("endpoints", [])

    paths = {e["path"] for e in endpoints}

    assert "/api/layout_screens" in paths, "API must include /api/layout_screens endpoint"
    assert "/api/health" in paths, "API must include /api/health endpoint"


class TestLayoutSpecConsistency:
    """Tests that ensure TypeScript and Python layout specs stay in sync."""

    def test_layout_spec_ts_exists(self):
        """layout_spec.ts must exist."""
        ts_path = REPO_ROOT / "swarm/tools/flow_studio_ui/src/layout_spec.ts"
        assert ts_path.exists(), f"layout_spec.ts not found at {ts_path}"

    def test_layout_screens_endpoint_exists_in_fastapi(self):
        """FastAPI must have layout_screens endpoint defined."""
        fastapi_path = REPO_ROOT / "swarm/tools/flow_studio_fastapi.py"
        content = fastapi_path.read_text(encoding="utf-8")

        assert "/api/layout_screens" in content, "FastAPI missing /api/layout_screens route"
        assert "LAYOUT_SCREENS" in content, "FastAPI missing LAYOUT_SCREENS definition"


class TestLayoutScreensAPIConsistency:
    """Tests that verify API layout_screens matches TypeScript source."""

    def test_api_screens_have_required_fields(self):
        """Each screen from API must have id, route, regions, description."""
        from swarm.tools.flow_studio_fastapi import app
        from fastapi.testclient import TestClient

        client = TestClient(app)
        resp = client.get("/api/layout_screens")
        assert resp.status_code == 200

        data = resp.json()
        for screen in data["screens"]:
            assert "id" in screen, "Screen missing 'id'"
            assert "route" in screen, "Screen missing 'route'"
            assert "regions" in screen, "Screen missing 'regions'"
            # description is the screen-level purpose field
            assert "description" in screen or "title" in screen, (
                f"Screen {screen.get('id')} missing 'description' or 'title'"
            )

    def test_api_screens_routes_are_valid(self):
        """All screen routes should be valid URL patterns."""
        from swarm.tools.flow_studio_fastapi import app
        from fastapi.testclient import TestClient

        client = TestClient(app)
        resp = client.get("/api/layout_screens")
        assert resp.status_code == 200

        data = resp.json()
        for screen in data["screens"]:
            route = screen["route"]
            # Routes should start with / or be empty for root
            assert route == "" or route.startswith("/") or route.startswith("?"), (
                f"Invalid route for screen {screen['id']}: {route}"
            )

    def test_api_screens_uiids_match_convention(self):
        """All UIIDs in screens should follow flow_studio.* convention."""
        from swarm.tools.flow_studio_fastapi import app
        from fastapi.testclient import TestClient

        client = TestClient(app)
        resp = client.get("/api/layout_screens")
        assert resp.status_code == 200

        data = resp.json()
        for screen in data["screens"]:
            for region in screen.get("regions", []):
                for uiid in region.get("uiids", []):
                    assert uiid.startswith("flow_studio."), (
                        f"UIID {uiid} in screen {screen['id']} doesn't follow convention"
                    )

    def test_api_screens_count_matches_expectation(self):
        """Layout screens should have a reasonable count (1-20 for v0.5.0)."""
        from swarm.tools.flow_studio_fastapi import app
        from fastapi.testclient import TestClient

        client = TestClient(app)
        resp = client.get("/api/layout_screens")
        assert resp.status_code == 200

        data = resp.json()
        screen_count = len(data["screens"])

        # Sanity check: should have at least 1 screen, at most 20
        assert 1 <= screen_count <= 20, (
            f"Unexpected screen count: {screen_count}. Expected 1-20 for v0.5.0"
        )


class TestRunLayoutReview:
    """Tests for the run_layout_review.py tool."""

    def test_run_layout_review_exists(self):
        """run_layout_review.py must exist."""
        tool_path = REPO_ROOT / "swarm/tools/run_layout_review.py"
        assert tool_path.exists(), f"run_layout_review.py not found at {tool_path}"

    def test_run_layout_review_is_executable(self):
        """run_layout_review.py must have main() function."""
        tool_path = REPO_ROOT / "swarm/tools/run_layout_review.py"
        content = tool_path.read_text(encoding="utf-8")

        assert "def main()" in content, "run_layout_review.py must have main() function"
        assert 'if __name__ == "__main__"' in content, "run_layout_review.py must be executable"

    def test_run_layout_review_uses_layout_screens_api(self):
        """run_layout_review.py must use /api/layout_screens."""
        tool_path = REPO_ROOT / "swarm/tools/run_layout_review.py"
        content = tool_path.read_text(encoding="utf-8")

        assert "/api/layout_screens" in content, "run_layout_review.py must fetch from /api/layout_screens"
