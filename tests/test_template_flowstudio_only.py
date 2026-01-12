"""Tests for flowstudio-only template.

These tests verify that:
1. The template has required files
2. The server module can be imported
3. The Flask app starts and serves endpoints
4. The Dockerfile is valid
"""

import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).parent.parent
TEMPLATE_DIR = REPO_ROOT / "templates" / "flowstudio-only"


class TestTemplateStructure:
    """Test that template has required files."""

    def test_template_dir_exists(self) -> None:
        """Template directory should exist."""
        assert TEMPLATE_DIR.exists(), f"Template dir not found: {TEMPLATE_DIR}"

    def test_pyproject_toml_exists(self) -> None:
        """pyproject.toml should exist."""
        assert (TEMPLATE_DIR / "pyproject.toml").exists()

    def test_readme_exists(self) -> None:
        """README.md should exist."""
        assert (TEMPLATE_DIR / "README.md").exists()

    def test_dockerfile_exists(self) -> None:
        """Dockerfile should exist."""
        assert (TEMPLATE_DIR / "Dockerfile").exists()

    def test_server_module_exists(self) -> None:
        """flowstudio/server.py should exist."""
        assert (TEMPLATE_DIR / "flowstudio" / "server.py").exists()

    def test_config_module_exists(self) -> None:
        """flowstudio/config.py should exist."""
        assert (TEMPLATE_DIR / "flowstudio" / "config.py").exists()

    def test_example_flow_exists(self) -> None:
        """config/flows/ should have at least one example."""
        flows_dir = TEMPLATE_DIR / "config" / "flows"
        assert flows_dir.exists()
        yaml_files = list(flows_dir.glob("*.yaml"))
        assert len(yaml_files) >= 1, "No example flows found"

    def test_example_agents_exist(self) -> None:
        """config/agents/ should have example agents."""
        agents_dir = TEMPLATE_DIR / "config" / "agents"
        assert agents_dir.exists()
        yaml_files = list(agents_dir.glob("*.yaml"))
        assert len(yaml_files) >= 1, "No example agents found"


class TestPyprojectToml:
    """Test pyproject.toml configuration."""

    @pytest.fixture
    def pyproject(self) -> dict:
        """Load pyproject.toml as dict (TOML parsing)."""
        import tomllib

        with open(TEMPLATE_DIR / "pyproject.toml", "rb") as f:
            return tomllib.load(f)

    def test_has_project_name(self, pyproject: dict) -> None:
        """Should have project name."""
        assert "project" in pyproject
        assert "name" in pyproject["project"]
        assert pyproject["project"]["name"] == "flowstudio"

    def test_has_flask_dependency(self, pyproject: dict) -> None:
        """Should depend on Flask."""
        deps = pyproject["project"].get("dependencies", [])
        assert any("flask" in d.lower() for d in deps)

    def test_has_cli_entry_point(self, pyproject: dict) -> None:
        """Should have CLI entry point."""
        scripts = pyproject["project"].get("scripts", {})
        assert "flowstudio" in scripts


class TestReadmeContent:
    """Test README content."""

    @pytest.fixture
    def readme(self) -> str:
        """Load README content."""
        return (TEMPLATE_DIR / "README.md").read_text(encoding="utf-8")

    def test_has_audience_header(self, readme: str) -> None:
        """README should have audience header."""
        head = "\n".join(readme.splitlines()[:10])
        assert "For:" in head, "README should have audience header"

    def test_has_quick_start(self, readme: str) -> None:
        """README should have Quick Start section."""
        assert "Quick Start" in readme

    def test_has_api_documentation(self, readme: str) -> None:
        """README should document API endpoints."""
        assert "/api/flows" in readme
        assert "/api/graph" in readme

    def test_has_docker_instructions(self, readme: str) -> None:
        """README should have Docker instructions."""
        assert "docker" in readme.lower()


class TestDockerfile:
    """Test Dockerfile validity."""

    @pytest.fixture
    def dockerfile(self) -> str:
        """Load Dockerfile content."""
        return (TEMPLATE_DIR / "Dockerfile").read_text(encoding="utf-8")

    def test_dockerfile_has_from(self, dockerfile: str) -> None:
        """Dockerfile should have FROM instruction."""
        assert "FROM" in dockerfile

    def test_dockerfile_exposes_port(self, dockerfile: str) -> None:
        """Dockerfile should expose a port."""
        assert "EXPOSE" in dockerfile

    def test_dockerfile_has_healthcheck(self, dockerfile: str) -> None:
        """Dockerfile should have health check."""
        assert "HEALTHCHECK" in dockerfile

    def test_dockerfile_has_cmd(self, dockerfile: str) -> None:
        """Dockerfile should have CMD."""
        assert "CMD" in dockerfile


class TestExampleFlows:
    """Test example flow/agent YAML files."""

    def test_example_flow_valid_yaml(self) -> None:
        """Example flows should be valid YAML."""
        flows_dir = TEMPLATE_DIR / "config" / "flows"
        for yaml_file in flows_dir.glob("*.yaml"):
            with open(yaml_file) as f:
                data = yaml.safe_load(f)
            assert data is not None
            assert "key" in data, f"Flow {yaml_file.name} missing 'key'"
            assert "steps" in data, f"Flow {yaml_file.name} missing 'steps'"

    def test_example_agents_valid_yaml(self) -> None:
        """Example agents should be valid YAML."""
        agents_dir = TEMPLATE_DIR / "config" / "agents"
        for yaml_file in agents_dir.glob("*.yaml"):
            with open(yaml_file) as f:
                data = yaml.safe_load(f)
            assert data is not None
            assert "key" in data, f"Agent {yaml_file.name} missing 'key'"


class TestServerModule:
    """Test that the server module can be imported and used."""

    @pytest.mark.slow
    def test_server_module_imports(self) -> None:
        """Server module should import successfully."""
        # Skip if flask not available
        try:
            import flask  # noqa: F401
        except ImportError:
            pytest.skip("Flask not installed")

        # Copy template to temp dir and test import
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "flowstudio-test"
            shutil.copytree(TEMPLATE_DIR, target)

            # Add to path and try import
            result = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    "import sys; sys.path.insert(0, '.'); from flowstudio.server import create_app; print('OK')",
                ],
                cwd=target,
                capture_output=True,
                text=True,
            )

            assert result.returncode == 0, f"Import failed: {result.stderr}"
            assert "OK" in result.stdout

    @pytest.mark.slow
    def test_server_starts_and_serves_health(self) -> None:
        """Server should start and serve /health endpoint."""
        # Skip if flask not available
        try:
            import flask  # noqa: F401
        except ImportError:
            pytest.skip("Flask not installed")

        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "flowstudio-test"
            shutil.copytree(TEMPLATE_DIR, target)

            # Start server in background
            proc = subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    """
import sys
sys.path.insert(0, '.')
from flowstudio.server import create_app
app = create_app()
app.run(host='127.0.0.1', port=15555, debug=False, use_reloader=False)
""",
                ],
                cwd=target,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            try:
                # Wait for server to start
                time.sleep(2)

                # Test health endpoint
                import urllib.request

                try:
                    resp = urllib.request.urlopen("http://127.0.0.1:15555/health", timeout=5)
                    assert resp.status == 200
                    data = resp.read().decode()
                    assert "ok" in data.lower()
                except Exception as e:
                    pytest.fail(f"Health check failed: {e}")

            finally:
                proc.terminate()
                proc.wait(timeout=5)

    @pytest.mark.slow
    def test_server_serves_api_flows(self) -> None:
        """Server should serve /api/flows endpoint."""
        # Skip if flask not available
        try:
            import flask  # noqa: F401
        except ImportError:
            pytest.skip("Flask not installed")

        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "flowstudio-test"
            shutil.copytree(TEMPLATE_DIR, target)

            # Start server in background
            proc = subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    """
import sys
sys.path.insert(0, '.')
from flowstudio.server import create_app
app = create_app()
app.run(host='127.0.0.1', port=15556, debug=False, use_reloader=False)
""",
                ],
                cwd=target,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            try:
                time.sleep(2)

                import urllib.request

                try:
                    resp = urllib.request.urlopen("http://127.0.0.1:15556/api/flows", timeout=5)
                    assert resp.status == 200
                    data = resp.read().decode()
                    # Should return a JSON array
                    assert data.startswith("[")
                except Exception as e:
                    pytest.fail(f"API flows failed: {e}")

            finally:
                proc.terminate()
                proc.wait(timeout=5)
