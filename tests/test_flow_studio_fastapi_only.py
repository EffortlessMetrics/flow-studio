#!/usr/bin/env python3
"""
FastAPI-only Flow Studio tests.

Verifies that Flask backend is fully removed from production paths
and that the system operates exclusively on FastAPI.

Test Categories:
- Flask removal verification (no Flask in dependencies, code archived)
- Makefile verification (flow-studio target uses FastAPI)
- Import verification (no accidental Flask imports)
"""

import subprocess
import sys
from pathlib import Path

import pytest

# Add repo root to path for imports
repo_root = Path(__file__).resolve().parents[1]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))


# ============================================================================
# Flask Removal Tests
# ============================================================================


def test_flask_not_in_production_dependencies():
    """Verify Flask is not in production dependencies."""
    # Check pyproject.toml dependencies
    pyproject = repo_root / "pyproject.toml"
    assert pyproject.exists(), "pyproject.toml should exist"

    content = pyproject.read_text(encoding="utf-8")

    # Flask should not be in dependencies (might be in optional-dependencies for legacy support)
    # But should not be in main dependencies
    lines = content.split("\n")
    in_dependencies = False
    for line in lines:
        if line.strip() == "[project.dependencies]":
            in_dependencies = True
        elif line.strip().startswith("[") and in_dependencies:
            # Entered a different section
            in_dependencies = False
        elif in_dependencies and "flask" in line.lower():
            pytest.fail(f"Flask found in [project.dependencies]: {line}")


def test_flow_studio_py_archived():
    """Verify old Flask flow_studio.py is gone and legacy is under _archive/."""
    active_path = repo_root / "swarm" / "tools" / "flow_studio.py"
    archived_path = (
        repo_root / "swarm" / "tools" / "_archive" / "flow_studio_flask_legacy.py"
    )

    assert not active_path.exists(), (
        "flow_studio.py should not exist in active tools any more "
        "(FastAPI is the only backend)."
    )
    assert archived_path.exists(), (
        "Legacy Flask backend should be archived at "
        "swarm/tools/_archive/flow_studio_flask_legacy.py for reference."
    )


def test_makefile_flow_studio_uses_fastapi():
    """Verify Makefile flow-studio target uses FastAPI."""
    makefile = repo_root / "Makefile"
    assert makefile.exists(), "Makefile should exist"

    content = makefile.read_text(encoding="utf-8")

    # Find flow-studio target
    assert "flow-studio:" in content, "Makefile should have flow-studio target"

    # Extract target section (simple heuristic: lines after "flow-studio:" until next target)
    lines = content.split("\n")
    target_lines = []
    in_target = False
    for line in lines:
        if line.startswith("flow-studio:"):
            in_target = True
            continue
        elif in_target:
            if line and not line.startswith("\t") and not line.startswith(" "):
                # Next target or section
                break
            target_lines.append(line)

    target_text = "\n".join(target_lines)

    # Assertions
    assert "uvicorn swarm.tools.flow_studio_fastapi:app" in target_text, (
        "flow-studio should use FastAPI backend via uvicorn"
    )
    assert "flask" not in target_text.lower(), (
        "flow-studio should not reference Flask"
    )


def test_no_flask_imports_in_fastapi_module():
    """Verify FastAPI module doesn't import Flask."""
    fastapi_module = repo_root / "swarm" / "tools" / "flow_studio_fastapi.py"
    assert fastapi_module.exists(), "FastAPI module should exist"

    content = fastapi_module.read_text(encoding="utf-8")

    # Should not import Flask
    assert "import flask" not in content.lower(), (
        "FastAPI module should not import Flask"
    )
    assert "from flask" not in content.lower(), (
        "FastAPI module should not import from Flask"
    )


def test_no_flask_in_active_test_imports():
    """Verify active tests don't import Flask (except skipped tests)."""
    test_files = [
        "test_flow_studio_fastapi_smoke.py",
        "test_flow_studio_governance.py",
        "test_flow_studio_fastapi_endpoint.py",
    ]

    for test_file in test_files:
        test_path = repo_root / "tests" / test_file
        if not test_path.exists():
            continue

        content = test_path.read_text(encoding="utf-8")

        # Check for Flask imports in non-skipped tests
        lines = content.split("\n")
        in_skipped_test = False
        for i, line in enumerate(lines):
            # Detect skipped test
            if "@pytest.mark.skip" in line:
                in_skipped_test = True
            # Detect function definition
            elif line.strip().startswith("def test_"):
                in_skipped_test = False

            # If not in skipped test and found Flask import
            if not in_skipped_test and "from swarm.tools.flow_studio import" in line:
                pytest.fail(
                    f"{test_file}:{i+1}: Active test imports Flask: {line.strip()}"
                )


# ============================================================================
# FastAPI Verification Tests
# ============================================================================


def test_fastapi_module_exists():
    """Verify FastAPI module exists and is importable."""
    try:
        from swarm.tools.flow_studio_fastapi import app
        assert app is not None, "FastAPI app should be defined"
    except ImportError as e:
        pytest.fail(f"Failed to import FastAPI module: {e}")


def test_fastapi_serves_core_endpoints():
    """Verify FastAPI serves all core endpoints."""
    from fastapi.testclient import TestClient
    from swarm.tools.flow_studio_fastapi import app

    client = TestClient(app)

    # Core endpoints that must work
    endpoints = [
        "/api/health",
        "/api/flows",
        "/",
    ]

    for endpoint in endpoints:
        response = client.get(endpoint)
        assert response.status_code in (200, 503), (
            f"Endpoint {endpoint} returned unexpected status {response.status_code}"
        )


# ============================================================================
# Migration Completeness Tests
# ============================================================================


def test_ui_module_extracted():
    """Verify HTML UI is extracted to shared module."""
    ui_module = repo_root / "swarm" / "tools" / "flow_studio_ui"
    assert ui_module.exists(), "UI module should exist"
    assert ui_module.is_dir(), "UI module should be a directory"

    # Should have __init__.py
    init_file = ui_module / "__init__.py"
    assert init_file.exists(), "UI module should have __init__.py"

    # Should have index.html
    html_file = ui_module / "index.html"
    assert html_file.exists(), "UI module should have index.html"


def test_fastapi_uses_extracted_ui():
    """Verify FastAPI imports HTML from shared UI module."""
    fastapi_module = repo_root / "swarm" / "tools" / "flow_studio_fastapi.py"
    content = fastapi_module.read_text(encoding="utf-8")

    assert "from swarm.tools.flow_studio_ui import get_index_html" in content, (
        "FastAPI should import get_index_html from shared UI module"
    )


def test_no_backend_toggle_in_makefile():
    """Verify FLOWSTUDIO_BACKEND toggle is removed from Makefile."""
    makefile = repo_root / "Makefile"
    content = makefile.read_text(encoding="utf-8")

    # Find flow-studio target
    lines = content.split("\n")
    target_lines = []
    in_target = False
    for line in lines:
        if line.startswith("flow-studio:"):
            in_target = True
            continue
        elif in_target:
            if line and not line.startswith("\t") and not line.startswith(" "):
                break
            target_lines.append(line)

    target_text = "\n".join(target_lines)

    # Should not have backend toggle
    assert "FLOWSTUDIO_BACKEND" not in target_text, (
        "flow-studio should not have FLOWSTUDIO_BACKEND toggle (FastAPI only)"
    )


# ============================================================================
# Documentation Tests
# ============================================================================


def test_flow_studio_docs_reference_fastapi():
    """Verify Flow Studio documentation references FastAPI, not Flask."""
    # Only check FLOW_STUDIO.md (specific documentation)
    # CLAUDE.md is a general guide and doesn't need to mention implementation details
    doc_path = repo_root / "docs" / "FLOW_STUDIO.md"

    if not doc_path.exists():
        pytest.skip("FLOW_STUDIO.md not found")

    content = doc_path.read_text(encoding="utf-8")

    # Should mention FastAPI or uvicorn (implementation details)
    # (Might mention Flask in migration notes, so we don't enforce strict exclusion)
    if "flow-studio" in content.lower() or "flow studio" in content.lower():
        # If document discusses Flow Studio, it should mention FastAPI
        assert "fastapi" in content.lower() or "uvicorn" in content.lower(), (
            f"{doc_path.name} should reference FastAPI for Flow Studio"
        )


# ============================================================================
# Regression Prevention Tests
# ============================================================================


def test_no_flask_test_client_in_conftest():
    """Verify conftest.py doesn't create Flask test clients."""
    conftest = repo_root / "tests" / "conftest.py"
    if not conftest.exists():
        pytest.skip("conftest.py not found")

    content = conftest.read_text(encoding="utf-8")

    # Should not import Flask for test fixtures
    assert "from flask import" not in content, (
        "conftest.py should not import Flask"
    )
    assert "import flask" not in content, (
        "conftest.py should not import Flask"
    )


def test_demo_commands_reference_fastapi():
    """Verify demo commands reference FastAPI backend."""
    demo_commands = repo_root / "demo" / "DEMO_RUN_COMMANDS.jsonl"
    if not demo_commands.exists():
        pytest.skip("DEMO_RUN_COMMANDS.jsonl not found")

    content = demo_commands.read_text(encoding="utf-8")

    # If it mentions flow-studio, should not mention Flask
    if "flow-studio" in content:
        lines = content.split("\n")
        for i, line in enumerate(lines):
            if "flow-studio" in line and "flask" in line.lower():
                pytest.fail(
                    f"DEMO_RUN_COMMANDS.jsonl:{i+1} references Flask with flow-studio"
                )
