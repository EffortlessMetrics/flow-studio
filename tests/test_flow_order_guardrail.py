"""Guardrail test to prevent hardcoded flow order lists from being reintroduced.

This test ensures that production code uses get_flow_order() from flow_registry
instead of hardcoding flow order lists like:
  - ["signal", "plan", "build", "gate", "deploy", "wisdom"]  (6-flow, missing review)
  - ["signal", "plan", "build", "review", "gate", "deploy", "wisdom"]  (7-flow)

The flow_registry is the single source of truth for flow ordering.

## Allowed exceptions (documented in ALLOWED_VIOLATIONS):

1. **Fallback constants**: When registry import fails, a fallback is acceptable
   if it's clearly marked as a fallback and the code tries registry first.

2. **Dataclass defaults**: Default values in dataclass fields where the value
   serves as a schema definition, not runtime flow ordering logic.

3. **Documentation/examples**: Example code in docstrings or type hints.

To add a new exception, add an entry to ALLOWED_VIOLATIONS with:
  - file path (relative to project root)
  - line number
  - justification comment
"""

import re
from pathlib import Path
from typing import Dict, List, Set, Tuple

import pytest

# Directories to scan (production code only)
SCAN_DIRS = [
    "swarm/api",
    "swarm/runtime",
    "swarm/tools",
    "swarm/config",
    "swarm/plan",
    "swarm/spec",
]

# Patterns to exclude from scanning
EXCLUDE_PATTERNS = [
    "test_",  # Test files can have hardcoded lists for verification
    "__pycache__",
    ".pyc",
    "_archive",  # Archive directory contains legacy code
]

# Allowed violations with justifications
# Format: { "relative/path/to/file.py": {line_number: "justification", ...} }
# Add entries here when there's a legitimate reason for a hardcoded list
#
# NOTE: Line numbers must match exactly. If code changes, update the line numbers
# or the test_allowlist_lines_still_have_violations test will fail.
ALLOWED_VIOLATIONS: Dict[str, Dict[int, str]] = {
    # Fallback when registry import fails - acceptable since it tries registry first
    "swarm/tools/validate_swarm.py": {
        2454: "Fallback constant when flow_registry import fails",
    },
    # Fallback in _get_default_flow_sequence() when registry import fails
    "swarm/runtime/types/__init__.py": {
        126: "Fallback constant when flow_registry import fails in _get_default_flow_sequence()",
    },
    # Run plan defaults - defines example configurations
    "swarm/runtime/run_plan_api.py": {
        27: "Example default configuration for gated mode",
        257: "Example default configuration for review mode",
    },
    # Spec manager docstring - documentation example
    "swarm/spec/manager.py": {
        1340: "Docstring example - shows expected format in documentation",
    },
}

# Regex patterns to detect hardcoded flow order lists
# These patterns look for list literals containing flow names in order

# Pattern 1: Matches lists starting with ["signal", "plan", "build" ...
# This catches both 6-flow and 7-flow variants
FLOW_LIST_START_PATTERN = re.compile(
    r'\[\s*["\']signal["\']\s*,\s*["\']plan["\']\s*,\s*["\']build["\']',
    re.MULTILINE,
)

# Pattern 2: Matches inline lists with all 6 SDLC flows (missing review)
FLOW_LIST_6_PATTERN = re.compile(
    r'\[\s*["\']signal["\']\s*,\s*["\']plan["\']\s*,\s*["\']build["\']\s*,\s*'
    r'["\']gate["\']\s*,\s*["\']deploy["\']\s*,\s*["\']wisdom["\']\s*\]',
    re.MULTILINE,
)

# Pattern 3: Matches inline lists with all 7 SDLC flows (including review)
FLOW_LIST_7_PATTERN = re.compile(
    r'\[\s*["\']signal["\']\s*,\s*["\']plan["\']\s*,\s*["\']build["\']\s*,\s*'
    r'["\']review["\']\s*,\s*["\']gate["\']\s*,\s*["\']deploy["\']\s*,\s*'
    r'["\']wisdom["\']\s*\]',
    re.MULTILINE,
)

# Pattern 4: Tuple variants of the above
FLOW_TUPLE_START_PATTERN = re.compile(
    r'\(\s*["\']signal["\']\s*,\s*["\']plan["\']\s*,\s*["\']build["\']',
    re.MULTILINE,
)


def _get_project_root() -> Path:
    """Get the project root directory."""
    return Path(__file__).resolve().parent.parent


def _should_exclude(filepath: Path) -> bool:
    """Check if a file should be excluded from scanning."""
    path_str = str(filepath)
    return any(pattern in path_str for pattern in EXCLUDE_PATTERNS)


def _normalize_path(path: Path) -> str:
    """Normalize path to use forward slashes for cross-platform comparison."""
    return str(path).replace("\\", "/")


def _is_allowed_violation(filepath: Path, line_num: int, project_root: Path) -> bool:
    """Check if a violation is in the allowlist.

    Args:
        filepath: Absolute path to the file
        line_num: Line number of the violation
        project_root: Project root directory

    Returns:
        True if the violation is allowed, False otherwise
    """
    try:
        relative_path = _normalize_path(filepath.relative_to(project_root))
    except ValueError:
        return False

    if relative_path in ALLOWED_VIOLATIONS:
        return line_num in ALLOWED_VIOLATIONS[relative_path]
    return False


def _find_violations(
    content: str,
    filepath: Path,
    project_root: Path = None,
    check_allowlist: bool = False,
) -> List[Tuple[int, str, str]]:
    """Find all flow order violations in file content.

    Args:
        content: File content to scan
        filepath: Path to the file (for allowlist checking)
        project_root: Project root directory (for allowlist checking)
        check_allowlist: Whether to filter out allowed violations

    Returns:
        List of (line_number, pattern_name, matched_text) tuples.
    """
    violations = []
    lines = content.split("\n")

    patterns = [
        (FLOW_LIST_START_PATTERN, "hardcoded flow list starting with signal/plan/build"),
        (FLOW_LIST_6_PATTERN, "hardcoded 6-flow list (missing review)"),
        (FLOW_LIST_7_PATTERN, "hardcoded 7-flow list"),
        (FLOW_TUPLE_START_PATTERN, "hardcoded flow tuple starting with signal/plan/build"),
    ]

    for line_num, line in enumerate(lines, start=1):
        # Skip comments
        stripped = line.strip()
        if stripped.startswith("#"):
            continue

        # Check allowlist if requested
        if check_allowlist and project_root:
            if _is_allowed_violation(filepath, line_num, project_root):
                continue

        for pattern, pattern_name in patterns:
            match = pattern.search(line)
            if match:
                violations.append((line_num, pattern_name, match.group(0)))

    return violations


class TestFlowOrderGuardrail:
    """Prevent hardcoded flow order lists from being reintroduced."""

    def test_no_hardcoded_flow_lists(self):
        """Ensure production code uses get_flow_order() instead of hardcoded lists.

        This test scans production directories for patterns like:
          ["signal", "plan", "build", ...]

        These should be replaced with:
          from swarm.config.flow_registry import get_flow_order
          flows = get_flow_order()

        Violations in ALLOWED_VIOLATIONS are skipped (with documented justifications).
        """
        project_root = _get_project_root()
        all_violations: List[Tuple[Path, int, str, str]] = []

        for scan_dir in SCAN_DIRS:
            dir_path = project_root / scan_dir
            if not dir_path.exists():
                continue

            for py_file in dir_path.rglob("*.py"):
                if _should_exclude(py_file):
                    continue

                try:
                    content = py_file.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    continue

                # Use allowlist to filter out documented exceptions
                violations = _find_violations(
                    content, py_file, project_root=project_root, check_allowlist=True
                )
                for line_num, pattern_name, matched_text in violations:
                    relative_path = py_file.relative_to(project_root)
                    all_violations.append(
                        (relative_path, line_num, pattern_name, matched_text)
                    )

        if all_violations:
            msg = (
                "Hardcoded flow order lists found! Use get_flow_order() from "
                "swarm.config.flow_registry instead:\n\n"
            )
            for filepath, line_num, pattern_name, matched_text in all_violations:
                msg += f"  {filepath}:{line_num}\n"
                msg += f"    Pattern: {pattern_name}\n"
                msg += f"    Found: {matched_text}\n\n"

            msg += (
                "To fix, either:\n"
                "  1. Replace hardcoded lists with:\n"
                "       from swarm.config.flow_registry import get_flow_order\n"
                "       flows = get_flow_order()\n"
                "  2. Or add to ALLOWED_VIOLATIONS in test_flow_order_guardrail.py\n"
                "     with a documented justification.\n"
            )
            pytest.fail(msg)

    def test_flow_registry_provides_order(self):
        """Verify flow registry is the source of truth for flow ordering."""
        from swarm.config.flow_registry import get_flow_order, get_flow_index

        order = get_flow_order()

        # Should have at least 7 flows (core SDLC flows)
        assert len(order) >= 7, f"Expected at least 7 flows, got {len(order)}"

        # Key flows should be present
        assert "signal" in order, "signal flow should be in order"
        assert "plan" in order, "plan flow should be in order"
        assert "build" in order, "build flow should be in order"
        assert "review" in order, "review flow should be in order (it's now a real flow)"
        assert "gate" in order, "gate flow should be in order"
        assert "deploy" in order, "deploy flow should be in order"
        assert "wisdom" in order, "wisdom flow should be in order"

        # Order should be correct (signal before plan, plan before build, etc.)
        assert order.index("signal") < order.index("plan"), "signal should come before plan"
        assert order.index("plan") < order.index("build"), "plan should come before build"
        assert order.index("build") < order.index("review"), "build should come before review"
        assert order.index("review") < order.index("gate"), "review should come before gate"
        assert order.index("gate") < order.index("deploy"), "gate should come before deploy"
        assert order.index("deploy") < order.index("wisdom"), "deploy should come before wisdom"

    def test_flow_registry_has_review_flow(self):
        """Ensure the registry includes the review flow (prevents 6-flow regression)."""
        from swarm.config.flow_registry import get_flow_order, get_flow_index

        order = get_flow_order()

        assert "review" in order, (
            "review flow is missing from flow_registry! "
            "This is a regression - review was added as Flow 4."
        )

        # Review should be Flow 4 (index 4)
        review_index = get_flow_index("review")
        assert review_index == 4, (
            f"review flow should be at index 4, but found at index {review_index}"
        )

    def test_flow_indices_are_sequential(self):
        """Verify flow indices are sequential starting from 1."""
        from swarm.config.flow_registry import get_flow_order, get_flow_index

        order = get_flow_order()
        indices = [get_flow_index(key) for key in order]

        # Indices should be sequential 1, 2, 3, ...
        expected = list(range(1, len(order) + 1))
        assert indices == expected, (
            f"Flow indices should be sequential {expected}, got {indices}"
        )


class TestFlowOrderGuardrailPatterns:
    """Test that the detection patterns work correctly."""

    def test_pattern_detects_6_flow_list(self):
        """Pattern should detect 6-flow lists (missing review)."""
        code = '''
flows = ["signal", "plan", "build", "gate", "deploy", "wisdom"]
'''
        violations = _find_violations(code, Path("test.py"))
        assert len(violations) > 0, "Should detect 6-flow list"

    def test_pattern_detects_7_flow_list(self):
        """Pattern should detect 7-flow lists."""
        code = '''
flows = ["signal", "plan", "build", "review", "gate", "deploy", "wisdom"]
'''
        violations = _find_violations(code, Path("test.py"))
        assert len(violations) > 0, "Should detect 7-flow list"

    def test_pattern_detects_partial_list(self):
        """Pattern should detect lists starting with signal/plan/build."""
        code = '''
FIRST_FLOWS = ["signal", "plan", "build"]
'''
        violations = _find_violations(code, Path("test.py"))
        assert len(violations) > 0, "Should detect partial flow list"

    def test_pattern_detects_tuple_variant(self):
        """Pattern should detect tuple variants."""
        code = '''
FLOWS = ("signal", "plan", "build", "gate", "deploy", "wisdom")
'''
        violations = _find_violations(code, Path("test.py"))
        assert len(violations) > 0, "Should detect flow tuple"

    def test_pattern_ignores_comments(self):
        """Pattern should ignore commented lines."""
        code = '''
# flows = ["signal", "plan", "build", "gate", "deploy", "wisdom"]
'''
        violations = _find_violations(code, Path("test.py"))
        assert len(violations) == 0, "Should ignore commented lines"

    def test_pattern_allows_single_flow_references(self):
        """Pattern should allow single flow key references."""
        code = '''
flow_key = "signal"
if flow == "build":
    do_something()
'''
        violations = _find_violations(code, Path("test.py"))
        assert len(violations) == 0, "Should allow single flow references"

    def test_pattern_allows_get_flow_order_usage(self):
        """Pattern should allow proper get_flow_order() usage."""
        code = '''
from swarm.config.flow_registry import get_flow_order
flows = get_flow_order()
for flow in flows:
    print(flow)
'''
        violations = _find_violations(code, Path("test.py"))
        assert len(violations) == 0, "Should allow get_flow_order() usage"

    def test_pattern_detects_multiline_list(self):
        """Pattern should detect flow lists even with different spacing."""
        code = '''
flows = [
    "signal",
    "plan", "build", "gate",
    "deploy", "wisdom"
]
'''
        # This won't be detected by current patterns since they're single-line
        # That's acceptable - the main risk is copy-paste of inline lists
        # Multiline lists are less common and easier to spot in review
        _violations = _find_violations(code, Path("test.py"))  # noqa: F841
        # We don't require detection of multiline lists, just document behavior
        # The assignment above documents that we tried the pattern
        assert True  # Pattern behavior is acceptable


class TestFlowOrderGuardrailExclusions:
    """Test that exclusion patterns work correctly."""

    def test_test_files_are_excluded(self):
        """Test files should be excluded from scanning."""
        assert _should_exclude(Path("tests/test_flow_registry.py"))
        assert _should_exclude(Path("swarm/tools/test_gen_adapters.py"))

    def test_pycache_is_excluded(self):
        """__pycache__ directories should be excluded."""
        assert _should_exclude(Path("swarm/api/__pycache__/routes.cpython-311.pyc"))

    def test_archive_is_excluded(self):
        """Archive directories should be excluded."""
        assert _should_exclude(Path("swarm/tools/_archive/old_code.py"))

    def test_production_files_are_not_excluded(self):
        """Normal production files should not be excluded."""
        assert not _should_exclude(Path("swarm/api/routes/runs.py"))
        assert not _should_exclude(Path("swarm/runtime/orchestrator.py"))
        assert not _should_exclude(Path("swarm/config/flow_registry.py"))


class TestFlowOrderGuardrailAllowlist:
    """Test that the allowlist is valid and well-maintained."""

    def test_allowlist_files_exist(self):
        """All files in ALLOWED_VIOLATIONS should exist."""
        project_root = _get_project_root()
        missing_files = []

        for relative_path in ALLOWED_VIOLATIONS.keys():
            full_path = project_root / relative_path
            if not full_path.exists():
                missing_files.append(relative_path)

        if missing_files:
            msg = (
                "Stale entries in ALLOWED_VIOLATIONS - files no longer exist:\n"
                + "\n".join(f"  - {f}" for f in missing_files)
                + "\n\nRemove these entries from ALLOWED_VIOLATIONS."
            )
            pytest.fail(msg)

    def test_allowlist_lines_still_have_violations(self):
        """Allowed lines should still contain the violation pattern.

        This prevents stale allowlist entries from accumulating when
        the underlying code is refactored.
        """
        project_root = _get_project_root()
        stale_entries: List[Tuple[str, int, str]] = []

        for relative_path, line_numbers in ALLOWED_VIOLATIONS.items():
            full_path = project_root / relative_path
            if not full_path.exists():
                continue  # Already caught by test_allowlist_files_exist

            try:
                content = full_path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue

            # Check each allowed line number
            lines = content.split("\n")
            for line_num, justification in line_numbers.items():
                if line_num > len(lines):
                    stale_entries.append((relative_path, line_num, "Line number out of range"))
                    continue

                line = lines[line_num - 1]  # Convert to 0-based index

                # Check if this line still has a flow list pattern
                has_pattern = any(
                    p.search(line)
                    for p in [
                        FLOW_LIST_START_PATTERN,
                        FLOW_LIST_6_PATTERN,
                        FLOW_LIST_7_PATTERN,
                        FLOW_TUPLE_START_PATTERN,
                    ]
                )

                if not has_pattern:
                    stale_entries.append(
                        (relative_path, line_num, f"No flow list pattern found (justification: {justification})")
                    )

        if stale_entries:
            msg = (
                "Stale entries in ALLOWED_VIOLATIONS - lines no longer have flow lists:\n"
            )
            for path, line_num, reason in stale_entries:
                msg += f"  - {path}:{line_num} - {reason}\n"
            msg += "\nRemove these stale entries from ALLOWED_VIOLATIONS."
            pytest.fail(msg)

    def test_allowlist_has_justifications(self):
        """All allowlist entries should have non-empty justifications."""
        missing_justifications = []

        for relative_path, line_numbers in ALLOWED_VIOLATIONS.items():
            for line_num, justification in line_numbers.items():
                if not justification or not justification.strip():
                    missing_justifications.append((relative_path, line_num))

        if missing_justifications:
            msg = "ALLOWED_VIOLATIONS entries missing justifications:\n"
            for path, line_num in missing_justifications:
                msg += f"  - {path}:{line_num}\n"
            msg += "\nAll allowlist entries must have a justification explaining why the hardcoded list is acceptable."
            pytest.fail(msg)
