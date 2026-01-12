"""Version consistency tests for selftest-core package.

These tests verify version consistency without importing selftest_core,
making them CI-friendly (no need to install the package first).
"""

import re
from pathlib import Path

import pytest

PACKAGES_ROOT = Path(__file__).resolve().parents[1] / "packages" / "selftest-core"
INIT_FILE = PACKAGES_ROOT / "src" / "selftest_core" / "__init__.py"


def _get_version_from_init() -> str:
    """Extract __version__ from __init__.py without importing."""
    content = INIT_FILE.read_text(encoding="utf-8")
    match = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', content, re.MULTILINE)
    if match is None:
        raise ValueError("Could not find __version__ in __init__.py")
    return match.group(1)


def _get_version_from_pyproject() -> str:
    """Extract version from pyproject.toml."""
    pyproject = PACKAGES_ROOT / "pyproject.toml"
    content = pyproject.read_text(encoding="utf-8")
    match = re.search(r'version\s*=\s*"([^"]+)"', content)
    if match is None:
        raise ValueError("Could not find version in pyproject.toml")
    return match.group(1)


class TestVersionConsistency:
    """Verify version is consistent across package artifacts."""

    def test_version_in_init_matches_pyproject(self):
        """Version in __init__.py matches pyproject.toml."""
        pyproject_version = _get_version_from_pyproject()
        init_version = _get_version_from_init()

        assert init_version == pyproject_version, (
            f"Version mismatch: __init__.py has '{init_version}' "
            f"but pyproject.toml has '{pyproject_version}'"
        )

    def test_version_in_changelog(self):
        """CHANGELOG.md contains current version."""
        changelog = PACKAGES_ROOT / "CHANGELOG.md"
        if not changelog.exists():
            pytest.skip("CHANGELOG.md not yet created")

        content = changelog.read_text(encoding="utf-8")
        version = _get_version_from_init()

        assert version in content, f"Version {version} not found in CHANGELOG.md"

    def test_version_format_semver(self):
        """Version follows semantic versioning."""
        version = _get_version_from_init()

        pattern = r"^\d+\.\d+\.\d+$"
        assert re.match(pattern, version), f"Version '{version}' is not valid semver"
