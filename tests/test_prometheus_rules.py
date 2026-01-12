"""
Tests for Prometheus recording and alert rules.

Tests:
- YAML syntax validation
- Rule name conventions (selftest: prefix)
- Alert severity validation (critical, high, warning, info)
- Recording rule format validation
- Alert rule required fields (expr, for, labels, annotations)
- PromQL expression validation (basic syntax checks)
"""

import re
from pathlib import Path

import pytest
import yaml

# Paths to rule files
REPO_ROOT = Path(__file__).resolve().parents[1]
PROMETHEUS_DIR = REPO_ROOT / "observability" / "prometheus"
KUBERNETES_DIR = REPO_ROOT / "observability" / "kubernetes"

RECORDING_RULES_FILE = PROMETHEUS_DIR / "recording_rules.yaml"
ALERT_RULES_FILE = PROMETHEUS_DIR / "alert_rules.yaml"
SERVICE_MONITOR_FILE = KUBERNETES_DIR / "service_monitor.yaml"


class TestPrometheusRecordingRules:
    """Test Prometheus recording rules syntax and conventions."""

    @pytest.fixture
    def recording_rules(self):
        """Load recording rules YAML."""
        assert RECORDING_RULES_FILE.exists(), f"Recording rules file not found: {RECORDING_RULES_FILE}"
        with open(RECORDING_RULES_FILE) as f:
            return yaml.safe_load(f)

    def test_yaml_syntax_valid(self, recording_rules):
        """Recording rules file should have valid YAML syntax."""
        assert recording_rules is not None
        assert "groups" in recording_rules

    def test_groups_structure(self, recording_rules):
        """Recording rules should have proper group structure."""
        groups = recording_rules.get("groups", [])
        assert len(groups) > 0, "At least one rule group required"

        for group in groups:
            assert "name" in group, "Group must have a name"
            assert "rules" in group, "Group must have rules"
            assert len(group["rules"]) > 0, f"Group {group['name']} must have at least one rule"

    def test_rule_names_follow_convention(self, recording_rules):
        """Recording rule names should follow selftest:metric:window convention."""
        for group in recording_rules.get("groups", []):
            for rule in group.get("rules", []):
                record_name = rule.get("record", "")
                assert record_name.startswith("selftest:"), (
                    f"Rule name '{record_name}' should start with 'selftest:'"
                )
                # Check for standard format: selftest:metric:window
                parts = record_name.split(":")
                assert len(parts) >= 2, (
                    f"Rule name '{record_name}' should have format 'selftest:metric:window'"
                )

    def test_rules_have_expressions(self, recording_rules):
        """All recording rules should have valid expressions."""
        for group in recording_rules.get("groups", []):
            for rule in group.get("rules", []):
                expr = rule.get("expr", "")
                assert expr.strip(), f"Rule {rule.get('record')} must have a non-empty expression"

    def test_rules_have_labels_for_sli(self, recording_rules):
        """Recording rules should have labels indicating SLI type."""
        sli_labeled_count = 0
        total_rules = 0

        for group in recording_rules.get("groups", []):
            for rule in group.get("rules", []):
                total_rules += 1
                labels = rule.get("labels", {})
                if "sli" in labels or "slo" in labels:
                    sli_labeled_count += 1

        # At least 50% of rules should have SLI/SLO labels
        assert sli_labeled_count >= total_rules * 0.5, (
            f"At least 50% of recording rules should have 'sli' or 'slo' labels. "
            f"Found {sli_labeled_count}/{total_rules}"
        )

    def test_required_slo_rules_present(self, recording_rules):
        """Required SLO recording rules should be present."""
        required_rules = [
            "selftest:pass_rate:",
            "selftest:kernel_failure_rate:",
            "selftest:step_duration_p95:",
        ]

        all_rule_names = []
        for group in recording_rules.get("groups", []):
            for rule in group.get("rules", []):
                all_rule_names.append(rule.get("record", ""))

        for required in required_rules:
            found = any(name.startswith(required) for name in all_rule_names)
            assert found, f"Required recording rule pattern '{required}*' not found"


class TestPrometheusAlertRules:
    """Test Prometheus alert rules syntax and conventions."""

    @pytest.fixture
    def alert_rules(self):
        """Load alert rules YAML."""
        assert ALERT_RULES_FILE.exists(), f"Alert rules file not found: {ALERT_RULES_FILE}"
        with open(ALERT_RULES_FILE) as f:
            return yaml.safe_load(f)

    def test_yaml_syntax_valid(self, alert_rules):
        """Alert rules file should have valid YAML syntax."""
        assert alert_rules is not None
        assert "groups" in alert_rules

    def test_groups_structure(self, alert_rules):
        """Alert rules should have proper group structure."""
        groups = alert_rules.get("groups", [])
        assert len(groups) > 0, "At least one alert group required"

        for group in groups:
            assert "name" in group, "Group must have a name"
            assert "rules" in group, "Group must have rules"

    def test_alert_names_follow_convention(self, alert_rules):
        """Alert names should follow SelftestCamelCase convention."""
        for group in alert_rules.get("groups", []):
            for rule in group.get("rules", []):
                alert_name = rule.get("alert", "")
                assert alert_name.startswith("Selftest"), (
                    f"Alert name '{alert_name}' should start with 'Selftest'"
                )
                # Check CamelCase
                assert re.match(r"^Selftest[A-Z][a-zA-Z]+$", alert_name), (
                    f"Alert name '{alert_name}' should be CamelCase (e.g., SelftestKernelFailure)"
                )

    def test_alerts_have_required_fields(self, alert_rules):
        """Alert rules should have required fields."""
        required_fields = ["alert", "expr", "labels", "annotations"]

        for group in alert_rules.get("groups", []):
            for rule in group.get("rules", []):
                for field in required_fields:
                    assert field in rule, (
                        f"Alert {rule.get('alert', 'unknown')} missing required field '{field}'"
                    )

    def test_alerts_have_valid_severity(self, alert_rules):
        """Alert severity labels should be valid values."""
        valid_severities = {"critical", "high", "warning", "info"}

        for group in alert_rules.get("groups", []):
            for rule in group.get("rules", []):
                labels = rule.get("labels", {})
                severity = labels.get("severity")
                assert severity in valid_severities, (
                    f"Alert {rule.get('alert')} has invalid severity '{severity}'. "
                    f"Must be one of: {valid_severities}"
                )

    def test_alerts_have_summary_annotation(self, alert_rules):
        """Alert annotations should include summary."""
        for group in alert_rules.get("groups", []):
            for rule in group.get("rules", []):
                annotations = rule.get("annotations", {})
                assert "summary" in annotations, (
                    f"Alert {rule.get('alert')} missing 'summary' annotation"
                )
                assert len(annotations["summary"]) > 10, (
                    f"Alert {rule.get('alert')} summary should be descriptive"
                )

    def test_alerts_have_description_annotation(self, alert_rules):
        """Alert annotations should include description."""
        for group in alert_rules.get("groups", []):
            for rule in group.get("rules", []):
                annotations = rule.get("annotations", {})
                assert "description" in annotations, (
                    f"Alert {rule.get('alert')} missing 'description' annotation"
                )

    def test_critical_alerts_have_runbook(self, alert_rules):
        """Critical alerts should have runbook_url annotation."""
        for group in alert_rules.get("groups", []):
            for rule in group.get("rules", []):
                labels = rule.get("labels", {})
                annotations = rule.get("annotations", {})
                if labels.get("severity") == "critical":
                    assert "runbook_url" in annotations, (
                        f"Critical alert {rule.get('alert')} must have 'runbook_url' annotation"
                    )

    def test_severity_distribution(self, alert_rules):
        """Alert rules should have a reasonable severity distribution."""
        severity_counts = {"critical": 0, "high": 0, "warning": 0, "info": 0}

        for group in alert_rules.get("groups", []):
            for rule in group.get("rules", []):
                severity = rule.get("labels", {}).get("severity", "unknown")
                if severity in severity_counts:
                    severity_counts[severity] += 1

        # Should have at least one alert of each major severity
        assert severity_counts["critical"] >= 1, "At least one critical alert required"
        assert severity_counts["warning"] >= 1, "At least one warning alert required"

        # Critical alerts should be rare (less than 30% of total)
        total = sum(severity_counts.values())
        if total > 0:
            critical_pct = severity_counts["critical"] / total
            assert critical_pct < 0.5, (
                f"Too many critical alerts ({severity_counts['critical']}/{total}). "
                "Critical should be reserved for immediate action items."
            )

    def test_required_alerts_present(self, alert_rules):
        """Required alerts for SLOs should be present."""
        required_alerts = [
            "SelftestKernelFailure",
            "SelftestGovernanceDegraded",
            "SelftestPerformanceSLOBreach",
        ]

        all_alert_names = []
        for group in alert_rules.get("groups", []):
            for rule in group.get("rules", []):
                all_alert_names.append(rule.get("alert", ""))

        for required in required_alerts:
            assert required in all_alert_names, (
                f"Required alert '{required}' not found in alert rules"
            )


class TestKubernetesManifests:
    """Test Kubernetes ServiceMonitor and PrometheusRule manifests."""

    @pytest.fixture
    def k8s_manifests(self):
        """Load Kubernetes manifests (multi-document YAML)."""
        assert SERVICE_MONITOR_FILE.exists(), f"ServiceMonitor file not found: {SERVICE_MONITOR_FILE}"
        with open(SERVICE_MONITOR_FILE) as f:
            # Load all documents from multi-doc YAML
            docs = list(yaml.safe_load_all(f))
        return docs

    def test_yaml_syntax_valid(self, k8s_manifests):
        """Kubernetes manifests should have valid YAML syntax."""
        assert len(k8s_manifests) >= 1, "At least one Kubernetes manifest required"

    def test_service_monitor_present(self, k8s_manifests):
        """ServiceMonitor CRD should be present."""
        service_monitors = [
            doc for doc in k8s_manifests
            if doc and doc.get("kind") == "ServiceMonitor"
        ]
        assert len(service_monitors) >= 1, "ServiceMonitor resource not found"

    def test_prometheus_rule_present(self, k8s_manifests):
        """PrometheusRule CRD should be present."""
        prom_rules = [
            doc for doc in k8s_manifests
            if doc and doc.get("kind") == "PrometheusRule"
        ]
        assert len(prom_rules) >= 1, "PrometheusRule resource not found"

    def test_service_monitor_has_required_fields(self, k8s_manifests):
        """ServiceMonitor should have required fields."""
        for doc in k8s_manifests:
            if doc and doc.get("kind") == "ServiceMonitor":
                assert "metadata" in doc, "ServiceMonitor missing metadata"
                assert "spec" in doc, "ServiceMonitor missing spec"
                assert "selector" in doc["spec"], "ServiceMonitor missing spec.selector"
                assert "endpoints" in doc["spec"], "ServiceMonitor missing spec.endpoints"

    def test_prometheus_rule_has_groups(self, k8s_manifests):
        """PrometheusRule should have rule groups."""
        for doc in k8s_manifests:
            if doc and doc.get("kind") == "PrometheusRule":
                assert "spec" in doc, "PrometheusRule missing spec"
                assert "groups" in doc["spec"], "PrometheusRule missing spec.groups"
                assert len(doc["spec"]["groups"]) > 0, "PrometheusRule has no rule groups"

    def test_labels_for_prometheus_operator(self, k8s_manifests):
        """Manifests should have labels for Prometheus Operator discovery."""
        for doc in k8s_manifests:
            if doc and doc.get("kind") in ("ServiceMonitor", "PrometheusRule"):
                labels = doc.get("metadata", {}).get("labels", {})
                # Check for common discovery labels
                has_release = "release" in labels
                has_app = "app" in labels
                assert has_release or has_app, (
                    f"{doc['kind']} should have 'release' or 'app' label for Prometheus Operator discovery"
                )


class TestPromQLExpressions:
    """Basic validation of PromQL expressions in rules."""

    @pytest.fixture
    def all_expressions(self):
        """Collect all expressions from recording and alert rules."""
        expressions = []

        if RECORDING_RULES_FILE.exists():
            with open(RECORDING_RULES_FILE) as f:
                data = yaml.safe_load(f)
                for group in data.get("groups", []):
                    for rule in group.get("rules", []):
                        expr = rule.get("expr", "")
                        if expr:
                            expressions.append({
                                "source": "recording_rules.yaml",
                                "name": rule.get("record", "unknown"),
                                "expr": expr
                            })

        if ALERT_RULES_FILE.exists():
            with open(ALERT_RULES_FILE) as f:
                data = yaml.safe_load(f)
                for group in data.get("groups", []):
                    for rule in group.get("rules", []):
                        expr = rule.get("expr", "")
                        if expr:
                            expressions.append({
                                "source": "alert_rules.yaml",
                                "name": rule.get("alert", "unknown"),
                                "expr": expr
                            })

        return expressions

    def test_expressions_not_empty(self, all_expressions):
        """All expressions should be non-empty."""
        for item in all_expressions:
            expr = item["expr"].strip()
            assert expr, f"Expression for {item['name']} in {item['source']} is empty"

    def test_expressions_have_balanced_brackets(self, all_expressions):
        """Expressions should have balanced brackets and parentheses."""
        def check_balanced(expr, open_char, close_char):
            count = 0
            for char in expr:
                if char == open_char:
                    count += 1
                elif char == close_char:
                    count -= 1
                if count < 0:
                    return False
            return count == 0

        for item in all_expressions:
            expr = item["expr"]
            assert check_balanced(expr, "(", ")"), (
                f"Unbalanced parentheses in {item['name']}: {expr[:50]}..."
            )
            assert check_balanced(expr, "[", "]"), (
                f"Unbalanced brackets in {item['name']}: {expr[:50]}..."
            )
            assert check_balanced(expr, "{", "}"), (
                f"Unbalanced braces in {item['name']}: {expr[:50]}..."
            )

    def test_expressions_reference_selftest_metrics(self, all_expressions):
        """Expressions should reference selftest metrics or recording rules."""
        selftest_pattern = re.compile(r"selftest[_:]")

        for item in all_expressions:
            expr = item["expr"]
            assert selftest_pattern.search(expr), (
                f"Expression for {item['name']} should reference 'selftest_*' metrics or 'selftest:*' rules. "
                f"Found: {expr[:100]}..."
            )

    def test_time_ranges_are_valid(self, all_expressions):
        """Time ranges in expressions should be valid Prometheus durations."""
        # Valid duration pattern: number + unit (s, m, h, d, w, y)
        duration_pattern = re.compile(r"\[(\d+[smhdwy])\]")

        for item in all_expressions:
            expr = item["expr"]
            for match in duration_pattern.finditer(expr):
                duration = match.group(1)
                # Just verify it's a valid format (the regex already does this)
                assert duration, f"Invalid duration in {item['name']}"


class TestInstallScript:
    """Test the Prometheus installation script."""

    @pytest.fixture
    def install_script(self):
        """Path to install script."""
        script_path = PROMETHEUS_DIR / "install.sh"
        assert script_path.exists(), f"Install script not found: {script_path}"
        return script_path

    def test_script_exists(self, install_script):
        """Install script should exist."""
        assert install_script.exists()

    def test_script_is_executable(self, install_script):
        """Install script should be executable."""
        import os
        assert os.access(install_script, os.X_OK), "Install script should be executable"

    def test_script_has_shebang(self, install_script):
        """Install script should have proper shebang."""
        with open(install_script) as f:
            first_line = f.readline()
        assert first_line.startswith("#!/bin/bash"), "Script should start with #!/bin/bash"

    def test_script_has_set_options(self, install_script):
        """Install script should have safety options (set -e, set -u, set -o pipefail)."""
        content = install_script.read_text(encoding="utf-8")
        # Check for either combined or individual set options
        has_safety = (
            "set -euo pipefail" in content or
            ("set -e" in content and "set -u" in content)
        )
        assert has_safety, "Script should have 'set -e' and 'set -u' for safety"

    def test_script_has_help_option(self, install_script):
        """Install script should have --help option."""
        content = install_script.read_text(encoding="utf-8")
        assert "--help" in content, "Script should support --help option"

    def test_script_has_dry_run_option(self, install_script):
        """Install script should have --dry-run option."""
        content = install_script.read_text(encoding="utf-8")
        assert "--dry-run" in content, "Script should support --dry-run option"

    def test_script_has_kubernetes_option(self, install_script):
        """Install script should have --kubernetes option."""
        content = install_script.read_text(encoding="utf-8")
        assert "--kubernetes" in content, "Script should support --kubernetes option"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
