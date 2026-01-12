"""
Tests for runbook automation (P4.4).

Tests cover:
- Configuration loading and validation
- GitHub Actions workflow YAML validity
- Artifact path specifications
"""

import sys
from pathlib import Path

# Add repo root to path so swarm imports work
repo_root = Path(__file__).resolve().parents[1]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

import pytest
import yaml


# ============================================================================
# Configuration Tests
# ============================================================================


class TestRunbookConfig:
    """Tests for runbook_config.py module."""

    def test_config_file_exists(self):
        """Config file should exist at expected location."""
        config_path = Path("swarm/config/runbook_automation.yaml")
        assert config_path.exists(), f"Config file not found: {config_path}"

    def test_config_is_valid_yaml(self):
        """Config file should be valid YAML."""
        config_path = Path("swarm/config/runbook_automation.yaml")
        with open(config_path, encoding="utf-8") as f:
            config = yaml.safe_load(f)
        assert config is not None, "Config file is empty"
        assert isinstance(config, dict), "Config should be a dictionary"

    def test_config_has_required_sections(self):
        """Config should have all required top-level sections."""
        config_path = Path("swarm/config/runbook_automation.yaml")
        with open(config_path, encoding="utf-8") as f:
            config = yaml.safe_load(f)

        required_sections = ["version", "enabled", "triggers", "actions", "notifications"]
        for section in required_sections:
            assert section in config, f"Missing required section: {section}"

    def test_config_version_is_supported(self):
        """Config version should be supported."""
        config_path = Path("swarm/config/runbook_automation.yaml")
        with open(config_path, encoding="utf-8") as f:
            config = yaml.safe_load(f)

        assert config.get("version") == "1.0", "Only version 1.0 is supported"

    def test_triggers_section_structure(self):
        """Triggers section should have expected keys."""
        config_path = Path("swarm/config/runbook_automation.yaml")
        with open(config_path, encoding="utf-8") as f:
            config = yaml.safe_load(f)

        triggers = config.get("triggers", {})
        expected_keys = ["on_selftest_failure", "manual_dispatch"]
        for key in expected_keys:
            assert key in triggers, f"Missing trigger key: {key}"

    def test_actions_section_structure(self):
        """Actions section should have expected keys."""
        config_path = Path("swarm/config/runbook_automation.yaml")
        with open(config_path, encoding="utf-8") as f:
            config = yaml.safe_load(f)

        actions = config.get("actions", {})
        expected_actions = ["incident_pack", "suggest_remediation"]
        for action in expected_actions:
            assert action in actions, f"Missing action: {action}"

    def test_notifications_section_structure(self):
        """Notifications section should have expected keys."""
        config_path = Path("swarm/config/runbook_automation.yaml")
        with open(config_path, encoding="utf-8") as f:
            config = yaml.safe_load(f)

        notifications = config.get("notifications", {})
        expected_keys = ["upload_artifacts", "post_pr_comment"]
        for key in expected_keys:
            assert key in notifications, f"Missing notification key: {key}"


class TestRunbookConfigLoader:
    """Tests for the config loader module."""

    def test_load_config_returns_dict(self):
        """load_config should return a dictionary."""
        from swarm.tools.runbook_config import load_config

        config = load_config()
        assert isinstance(config, dict)

    def test_load_config_has_defaults(self):
        """load_config should include default values."""
        from swarm.tools.runbook_config import load_config

        config = load_config()
        assert "version" in config
        assert "enabled" in config
        assert "triggers" in config

    def test_is_enabled_master_switch(self):
        """is_enabled should respect master enabled flag."""
        from swarm.tools.runbook_config import is_enabled

        # Enabled config
        config_enabled = {"enabled": True, "actions": {"incident_pack": {"enabled": True}}}
        assert is_enabled(config_enabled, "actions.incident_pack") is True

        # Disabled config
        config_disabled = {"enabled": False, "actions": {"incident_pack": {"enabled": True}}}
        assert is_enabled(config_disabled, "actions.incident_pack") is False

    def test_is_enabled_nested_path(self):
        """is_enabled should navigate nested paths."""
        from swarm.tools.runbook_config import is_enabled

        config = {
            "enabled": True,
            "notifications": {
                "upload_artifacts": {"enabled": True},
                "slack_notify": {"enabled": False},
            },
        }

        assert is_enabled(config, "notifications.upload_artifacts") is True
        assert is_enabled(config, "notifications.slack_notify") is False

    def test_is_enabled_missing_path(self):
        """is_enabled should return False for missing paths."""
        from swarm.tools.runbook_config import is_enabled

        config = {"enabled": True}
        assert is_enabled(config, "nonexistent.path") is False

    def test_get_setting_returns_value(self):
        """get_setting should return the correct value."""
        from swarm.tools.runbook_config import get_setting

        config = {
            "limits": {
                "workflow_timeout_minutes": 15,
                "max_concurrent": 1,
            }
        }

        assert get_setting(config, "limits.workflow_timeout_minutes") == 15
        assert get_setting(config, "limits.max_concurrent") == 1

    def test_get_setting_returns_default(self):
        """get_setting should return default for missing paths."""
        from swarm.tools.runbook_config import get_setting

        config = {}
        assert get_setting(config, "nonexistent.path", "default") == "default"

    def test_validate_config_valid(self):
        """validate_config should return empty list for valid config."""
        from swarm.tools.runbook_config import validate_config

        config = {
            "version": "1.0",
            "enabled": True,
            "triggers": {},
            "actions": {
                "incident_pack": {"timeout_seconds": 300},
                "suggest_remediation": {"timeout_seconds": 60},
            },
            "notifications": {
                "upload_artifacts": {"retention_days": 30},
            },
            "limits": {
                "workflow_timeout_minutes": 15,
            },
        }

        errors = validate_config(config)
        assert errors == []

    def test_validate_config_invalid_version(self):
        """validate_config should detect invalid version."""
        from swarm.tools.runbook_config import validate_config

        config = {"version": "2.0", "triggers": {}, "actions": {}, "notifications": {}, "limits": {}}
        errors = validate_config(config)
        assert any("version" in e.lower() for e in errors)

    def test_validate_config_missing_section(self):
        """validate_config should detect missing sections."""
        from swarm.tools.runbook_config import validate_config

        config = {"version": "1.0"}
        errors = validate_config(config)
        assert any("triggers" in e.lower() for e in errors)


# ============================================================================
# Workflow YAML Tests
# ============================================================================


def _get_workflow_triggers(workflow: dict) -> dict:
    """Get workflow triggers, handling YAML 1.1 'on' -> True quirk.

    YAML 1.1 parses 'on:' as boolean True, not string 'on'.
    This helper function handles both cases.
    """
    # Try string key first (YAML 1.2 behavior)
    if "on" in workflow:
        return workflow["on"]
    # Fall back to boolean key (YAML 1.1 behavior)
    if True in workflow:
        return workflow[True]
    return {}


class TestWorkflowYaml:
    """Tests for the GitHub Actions workflow YAML."""

    @pytest.fixture
    def workflow_path(self):
        """Path to the workflow file."""
        return Path(".github/workflows/selftest-auto-diagnostics.yml")

    def test_workflow_file_exists(self, workflow_path):
        """Workflow file should exist."""
        assert workflow_path.exists(), f"Workflow file not found: {workflow_path}"

    def test_workflow_is_valid_yaml(self, workflow_path):
        """Workflow file should be valid YAML."""
        with open(workflow_path, encoding="utf-8") as f:
            workflow = yaml.safe_load(f)
        assert workflow is not None, "Workflow file is empty"
        assert isinstance(workflow, dict), "Workflow should be a dictionary"

    def test_workflow_has_name(self, workflow_path):
        """Workflow should have a name."""
        with open(workflow_path, encoding="utf-8") as f:
            workflow = yaml.safe_load(f)
        assert "name" in workflow, "Workflow must have a name"
        assert workflow["name"] == "Selftest Auto-Diagnostics"

    def test_workflow_has_triggers(self, workflow_path):
        """Workflow should have trigger configuration."""
        with open(workflow_path, encoding="utf-8") as f:
            workflow = yaml.safe_load(f)

        triggers = _get_workflow_triggers(workflow)
        assert triggers, "Workflow must have 'on' triggers"

        # Should have workflow_run trigger
        assert "workflow_run" in triggers, "Should trigger on workflow_run"

        # Should have repository_dispatch trigger
        assert "repository_dispatch" in triggers, "Should trigger on repository_dispatch"

        # Should have workflow_dispatch trigger
        assert "workflow_dispatch" in triggers, "Should allow manual dispatch"

    def test_workflow_run_trigger_config(self, workflow_path):
        """workflow_run trigger should be configured correctly."""
        with open(workflow_path, encoding="utf-8") as f:
            workflow = yaml.safe_load(f)

        triggers = _get_workflow_triggers(workflow)
        workflow_run = triggers.get("workflow_run", {})

        # Should listen for completed workflows
        assert "types" in workflow_run
        assert "completed" in workflow_run["types"]

        # Should reference selftest governance gate
        assert "workflows" in workflow_run
        assert "Selftest Governance Gate" in workflow_run["workflows"]

    def test_workflow_has_jobs(self, workflow_path):
        """Workflow should have jobs defined."""
        with open(workflow_path, encoding="utf-8") as f:
            workflow = yaml.safe_load(f)

        assert "jobs" in workflow, "Workflow must have jobs"
        assert "auto-diagnose" in workflow["jobs"], "Should have auto-diagnose job"

    def test_job_has_condition(self, workflow_path):
        """Job should only run on failure or manual trigger."""
        with open(workflow_path, encoding="utf-8") as f:
            workflow = yaml.safe_load(f)

        job = workflow["jobs"]["auto-diagnose"]
        assert "if" in job, "Job should have conditional execution"

        # Condition should check for failure or manual dispatch
        condition = job["if"]
        assert "workflow_dispatch" in condition or "failure" in condition

    def test_job_has_timeout(self, workflow_path):
        """Job should have a timeout."""
        with open(workflow_path, encoding="utf-8") as f:
            workflow = yaml.safe_load(f)

        job = workflow["jobs"]["auto-diagnose"]
        assert "timeout-minutes" in job, "Job should have timeout"
        assert job["timeout-minutes"] <= 30, "Timeout should be reasonable"

    def test_job_runs_incident_pack(self, workflow_path):
        """Job should run selftest-incident-pack."""
        with open(workflow_path, encoding="utf-8") as f:
            content = f.read()

        assert "selftest-incident-pack" in content, "Should run incident pack"

    def test_job_runs_remediation(self, workflow_path):
        """Job should run suggest-remediation."""
        with open(workflow_path, encoding="utf-8") as f:
            content = f.read()

        assert "selftest_suggest_remediation" in content, "Should run remediation suggestions"

    def test_job_uploads_artifacts(self, workflow_path):
        """Job should upload diagnostic artifacts."""
        with open(workflow_path, encoding="utf-8") as f:
            workflow = yaml.safe_load(f)

        job = workflow["jobs"]["auto-diagnose"]
        steps = job.get("steps", [])

        # Find upload artifact step
        upload_steps = [s for s in steps if "upload-artifact" in str(s.get("uses", ""))]
        assert len(upload_steps) > 0, "Should have artifact upload step"

    def test_workflow_has_permissions(self, workflow_path):
        """Workflow should declare required permissions."""
        with open(workflow_path, encoding="utf-8") as f:
            workflow = yaml.safe_load(f)

        assert "permissions" in workflow, "Workflow should declare permissions"
        perms = workflow["permissions"]

        # Should have content read
        assert "contents" in perms
        assert perms["contents"] == "read"

        # Should have PR write for comments
        assert "pull-requests" in perms


# ============================================================================
# Artifact Path Tests
# ============================================================================


class TestArtifactPaths:
    """Tests for artifact path specifications."""

    def test_config_artifacts_list(self):
        """Config should specify artifact files to include."""
        config_path = Path("swarm/config/runbook_automation.yaml")
        with open(config_path, encoding="utf-8") as f:
            config = yaml.safe_load(f)

        artifacts = config.get("artifacts", {})
        include = artifacts.get("include", [])

        assert len(include) > 0, "Should have artifact includes"

        # Should include incident pack tarball
        assert any("selftest_incident" in f for f in include)

        # Should include remediation suggestions
        assert any("remediation_suggestions" in f for f in include)

    def test_workflow_artifact_paths_match_config(self):
        """Workflow artifact paths should match config specification."""
        # Load config
        config_path = Path("swarm/config/runbook_automation.yaml")
        with open(config_path, encoding="utf-8") as f:
            config = yaml.safe_load(f)

        config_artifacts = set(config.get("artifacts", {}).get("include", []))

        # Load workflow
        workflow_path = Path(".github/workflows/selftest-auto-diagnostics.yml")
        with open(workflow_path, encoding="utf-8") as f:
            content = f.read()

        # Check that key artifacts are mentioned in workflow
        key_artifacts = [
            "selftest_incident_",
            "remediation_suggestions",
            "git_recent_commits",
            "environment_info",
        ]

        for artifact in key_artifacts:
            assert artifact in content, f"Workflow should reference {artifact}"


# ============================================================================
# Integration Tests
# ============================================================================


class TestRunbookIntegration:
    """Integration tests for runbook automation components."""

    def test_incident_pack_script_exists(self):
        """selftest_incident_pack.py should exist."""
        path = Path("swarm/tools/selftest_incident_pack.py")
        assert path.exists(), f"Script not found: {path}"

    def test_remediation_script_exists(self):
        """selftest_suggest_remediation.py should exist."""
        path = Path("swarm/tools/selftest_suggest_remediation.py")
        assert path.exists(), f"Script not found: {path}"

    def test_config_loader_script_exists(self):
        """runbook_config.py should exist."""
        path = Path("swarm/tools/runbook_config.py")
        assert path.exists(), f"Script not found: {path}"

    def test_remediation_map_exists(self):
        """selftest_remediation_map.yaml should exist."""
        path = Path("swarm/config/selftest_remediation_map.yaml")
        assert path.exists(), f"Remediation map not found: {path}"

    def test_makefile_has_remote_diagnose_target(self):
        """Makefile should have selftest-diagnose-remote target."""
        makefile_path = Path("Makefile")
        with open(makefile_path, encoding="utf-8") as f:
            content = f.read()

        assert "selftest-diagnose-remote:" in content, "Missing selftest-diagnose-remote target"

    def test_makefile_has_config_check_target(self):
        """Makefile should have runbook-config-check target."""
        makefile_path = Path("Makefile")
        with open(makefile_path, encoding="utf-8") as f:
            content = f.read()

        assert "runbook-config-check:" in content, "Missing runbook-config-check target"
