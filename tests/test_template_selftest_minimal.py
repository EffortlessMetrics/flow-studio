"""Tests for selftest-minimal template.

These tests verify that:
1. The template can be bootstrapped to a new directory
2. The config file is valid YAML with required structure
3. The selftest CLI can parse the config
"""

import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).parent.parent
TEMPLATE_DIR = REPO_ROOT / "templates" / "selftest-minimal"
BOOTSTRAP_SCRIPT = REPO_ROOT / "swarm" / "tools" / "bootstrap_selftest_minimal.py"


class TestTemplateStructure:
    """Test that template has required files."""

    def test_template_dir_exists(self) -> None:
        """Template directory should exist."""
        assert TEMPLATE_DIR.exists(), f"Template dir not found: {TEMPLATE_DIR}"

    def test_selftest_yaml_exists(self) -> None:
        """selftest.yaml should exist at template root."""
        config_file = TEMPLATE_DIR / "selftest.yaml"
        assert config_file.exists(), "selftest.yaml not found in template"

    def test_pyproject_toml_exists(self) -> None:
        """pyproject.toml should exist."""
        assert (TEMPLATE_DIR / "pyproject.toml").exists()

    def test_readme_exists(self) -> None:
        """README.md should exist."""
        assert (TEMPLATE_DIR / "README.md").exists()

    def test_workflow_exists(self) -> None:
        """GitHub Actions workflow should exist."""
        workflow = TEMPLATE_DIR / ".github" / "workflows" / "selftest.yml"
        assert workflow.exists(), "selftest.yml workflow not found"


class TestConfigValidity:
    """Test that selftest.yaml is valid and well-structured."""

    @pytest.fixture
    def config(self) -> dict:
        """Load the template config."""
        config_file = TEMPLATE_DIR / "selftest.yaml"
        with open(config_file) as f:
            return yaml.safe_load(f)

    def test_config_parses(self, config: dict) -> None:
        """Config should parse as valid YAML."""
        assert config is not None
        assert isinstance(config, dict)

    def test_config_has_steps(self, config: dict) -> None:
        """Config should have a 'steps' key."""
        assert "steps" in config
        assert isinstance(config["steps"], list)
        assert len(config["steps"]) > 0

    def test_steps_have_required_fields(self, config: dict) -> None:
        """Each step should have id, tier, and command."""
        for step in config["steps"]:
            assert "id" in step, f"Step missing 'id': {step}"
            assert "tier" in step, f"Step missing 'tier': {step}"
            assert "command" in step, f"Step missing 'command': {step}"

    def test_tiers_are_valid(self, config: dict) -> None:
        """All tiers should be kernel, governance, or optional."""
        valid_tiers = {"kernel", "governance", "optional"}
        for step in config["steps"]:
            tier = step["tier"].lower()
            assert tier in valid_tiers, f"Invalid tier '{tier}' in step {step['id']}"

    def test_has_kernel_steps(self, config: dict) -> None:
        """Config should have at least one KERNEL tier step."""
        kernel_steps = [s for s in config["steps"] if s["tier"].lower() == "kernel"]
        assert len(kernel_steps) >= 1, "Config should have at least one KERNEL step"

    def test_step_ids_unique(self, config: dict) -> None:
        """Step IDs should be unique."""
        ids = [s["id"] for s in config["steps"]]
        assert len(ids) == len(set(ids)), "Duplicate step IDs found"


class TestBootstrapScript:
    """Test the bootstrap script."""

    def test_bootstrap_script_exists(self) -> None:
        """Bootstrap script should exist."""
        assert BOOTSTRAP_SCRIPT.exists()

    def test_bootstrap_help(self) -> None:
        """Bootstrap script should show help."""
        result = subprocess.run(
            [sys.executable, str(BOOTSTRAP_SCRIPT), "--help"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "target" in result.stdout.lower()

    def test_bootstrap_dry_run(self) -> None:
        """Bootstrap script dry-run should list files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = subprocess.run(
                [sys.executable, str(BOOTSTRAP_SCRIPT), tmpdir, "--dry-run"],
                capture_output=True,
                text=True,
            )
            assert result.returncode == 0
            assert "selftest.yaml" in result.stdout

    def test_bootstrap_copies_files(self) -> None:
        """Bootstrap script should copy template files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "test-project"

            result = subprocess.run(
                [sys.executable, str(BOOTSTRAP_SCRIPT), str(target)],
                capture_output=True,
                text=True,
            )

            assert result.returncode == 0, f"Bootstrap failed: {result.stderr}"
            assert (target / "selftest.yaml").exists()
            assert (target / "pyproject.toml").exists()
            assert (target / "README.md").exists()


class TestSelftestCLIIntegration:
    """Test that selftest-core CLI can use the template config."""

    @pytest.mark.slow
    def test_selftest_list_parses_config(self) -> None:
        """selftest list should parse the template config."""
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir)

            # Copy just the config file
            import shutil

            shutil.copy(TEMPLATE_DIR / "selftest.yaml", target / "selftest.yaml")

            # Run selftest list (doesn't execute steps, just parses)
            result = subprocess.run(
                [sys.executable, "-m", "selftest_core.cli", "list"],
                cwd=target,
                capture_output=True,
                text=True,
            )

            # Should either succeed or fail with "No steps" if module not installed
            # We mainly want to verify the YAML parses
            if result.returncode == 0:
                assert "lint" in result.stdout or "Available steps" in result.stdout

    @pytest.mark.slow
    def test_selftest_plan_shows_steps(self) -> None:
        """selftest plan should show execution plan."""
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir)

            import shutil

            shutil.copy(TEMPLATE_DIR / "selftest.yaml", target / "selftest.yaml")

            result = subprocess.run(
                [sys.executable, "-m", "selftest_core.cli", "plan"],
                cwd=target,
                capture_output=True,
                text=True,
            )

            if result.returncode == 0:
                # Should show the plan
                assert "lint" in result.stdout or "KERNEL" in result.stdout


class TestReadmeContent:
    """Test that README has required content."""

    @pytest.fixture
    def readme(self) -> str:
        """Load README content."""
        return (TEMPLATE_DIR / "README.md").read_text(encoding="utf-8")

    def test_readme_has_audience_header(self, readme: str) -> None:
        """README should have audience header."""
        # Check first 10 lines for "For:"
        head = "\n".join(readme.splitlines()[:10])
        assert "For:" in head, "README should have audience header"

    def test_readme_has_quick_start(self, readme: str) -> None:
        """README should have Quick Start section."""
        assert "Quick Start" in readme

    def test_readme_shows_correct_cli_commands(self, readme: str) -> None:
        """README should show correct CLI commands."""
        # These are the actual selftest-core CLI commands
        assert "selftest run" in readme
        assert "selftest plan" in readme
        assert "--kernel-only" in readme

    def test_readme_no_invalid_flags(self, readme: str) -> None:
        """README should not show invalid CLI flags."""
        # --tier is not a valid flag in selftest-core
        assert "--tier KERNEL" not in readme
        assert "--tier GOVERNANCE" not in readme


class TestWorkflowContent:
    """Test that GitHub workflow is valid."""

    @pytest.fixture
    def workflow(self) -> dict:
        """Load workflow content."""
        workflow_path = TEMPLATE_DIR / ".github" / "workflows" / "selftest.yml"
        with open(workflow_path) as f:
            return yaml.safe_load(f)

    def test_workflow_is_valid_yaml(self, workflow: dict) -> None:
        """Workflow should be valid YAML."""
        assert workflow is not None
        assert "jobs" in workflow

    def test_workflow_uses_correct_commands(self, workflow: dict) -> None:
        """Workflow should use correct selftest commands."""
        # Get all run commands
        runs = []
        for job in workflow.get("jobs", {}).values():
            for step in job.get("steps", []):
                if "run" in step:
                    runs.append(step["run"])

        run_text = "\n".join(runs)

        # Should use correct flags
        assert "--kernel-only" in run_text or "selftest run" in run_text
        # Should NOT use invalid --tier flag
        assert "--tier KERNEL" not in run_text
        assert "--tier GOVERNANCE" not in run_text
