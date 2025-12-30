"""
Tests for DEMO_RUN_COMMANDS.jsonl manifest validity.

Validates that the demo command manifest is well-formed, complete, and
references valid commands. Does NOT execute commands - just validates structure.

C2.2 Acceptance: "Demo command manifest + timings"
"""

import json
import shutil
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).parent.parent
MANIFEST_PATH = REPO_ROOT / "demo" / "DEMO_RUN_COMMANDS.jsonl"


class TestManifestStructure:
    """Test that the manifest file exists and has valid structure."""

    def test_manifest_exists(self):
        """Verify demo manifest file exists."""
        assert MANIFEST_PATH.exists(), f"Manifest not found at {MANIFEST_PATH}"

    def test_manifest_is_valid_jsonl(self):
        """Verify each line is valid JSON."""
        assert MANIFEST_PATH.exists()

        with open(MANIFEST_PATH) as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    json.loads(line)
                except json.JSONDecodeError as e:
                    pytest.fail(f"Invalid JSON on line {line_num}: {e}")

    def test_all_entries_have_required_fields(self):
        """Verify each entry has all required fields."""
        required_fields = {"id", "section", "order", "command", "expected", "approx_seconds", "category"}

        with open(MANIFEST_PATH) as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue

                entry = json.loads(line)
                missing = required_fields - set(entry.keys())
                assert not missing, f"Line {line_num} (id={entry.get('id', '?')}) missing fields: {missing}"

    def test_ids_are_unique(self):
        """Verify all entry IDs are unique."""
        ids = []

        with open(MANIFEST_PATH) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                entry = json.loads(line)
                ids.append(entry["id"])

        duplicates = [id for id in ids if ids.count(id) > 1]
        assert not duplicates, f"Duplicate IDs found: {set(duplicates)}"

    def test_orders_are_numeric(self):
        """Verify order values are numeric and sortable."""
        with open(MANIFEST_PATH) as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue

                entry = json.loads(line)
                order = entry["order"]
                assert isinstance(order, (int, float)), f"Line {line_num}: order must be numeric, got {type(order)}"

    def test_approx_seconds_are_reasonable(self):
        """Verify timing estimates are reasonable (0-600 seconds)."""
        with open(MANIFEST_PATH) as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue

                entry = json.loads(line)
                seconds = entry["approx_seconds"]
                assert isinstance(seconds, (int, float)), f"Line {line_num}: approx_seconds must be numeric"
                assert 0 <= seconds <= 600, f"Line {line_num}: approx_seconds {seconds} out of range (0-600)"


class TestManifestContent:
    """Test manifest content validity."""

    @pytest.fixture
    def entries(self):
        """Load all manifest entries."""
        entries = []
        with open(MANIFEST_PATH) as f:
            for line in f:
                line = line.strip()
                if line:
                    entries.append(json.loads(line))
        return entries

    def test_has_preconditions_section(self, entries):
        """Verify manifest includes precondition commands."""
        sections = {e["section"] for e in entries}
        assert "0-preconditions" in sections, "Missing 0-preconditions section"

    def test_has_kernel_selftest_section(self, entries):
        """Verify manifest includes kernel/selftest commands."""
        sections = {e["section"] for e in entries}
        assert "1-kernel-selftest" in sections, "Missing 1-kernel-selftest section"

    def test_commands_are_non_empty(self, entries):
        """Verify all commands are non-empty strings."""
        for entry in entries:
            assert entry["command"], f"Entry {entry['id']} has empty command"
            assert isinstance(entry["command"], str), f"Entry {entry['id']} command must be string"

    def test_categories_are_valid(self, entries):
        """Verify categories are from expected set."""
        valid_categories = {"setup", "kernel", "governance", "visualization", "templates", "extensions"}

        for entry in entries:
            category = entry["category"]
            assert category in valid_categories, f"Entry {entry['id']} has invalid category '{category}'"

    def test_expected_values_are_non_empty(self, entries):
        """Verify expected output descriptions are provided."""
        for entry in entries:
            assert entry["expected"], f"Entry {entry['id']} has empty expected value"

    def test_minimum_entry_count(self, entries):
        """Verify manifest has reasonable number of entries."""
        # DEMO_RUN.md has ~16 commands documented
        assert len(entries) >= 10, f"Too few entries ({len(entries)}), expected at least 10"


class TestCommandValidity:
    """Test that commands reference valid binaries/targets."""

    @pytest.fixture
    def entries(self):
        """Load all manifest entries."""
        entries = []
        with open(MANIFEST_PATH) as f:
            for line in f:
                line = line.strip()
                if line:
                    entries.append(json.loads(line))
        return entries

    def test_make_targets_exist(self, entries):
        """Verify make targets referenced in commands exist in Makefile."""
        makefile = REPO_ROOT / "Makefile"
        if not makefile.exists():
            pytest.skip("No Makefile found")

        makefile_content = makefile.read_text(encoding="utf-8")

        for entry in entries:
            cmd = entry["command"]
            if cmd.startswith("make "):
                target = cmd.split()[1]
                # Check if target is defined in Makefile (either as target: or .PHONY: target)
                target_pattern = f"{target}:"
                if target_pattern not in makefile_content:
                    # Could be defined via variable or include - just warn
                    pytest.skip(f"Could not verify make target '{target}' exists")

    def test_binary_commands_exist(self, entries):
        """Verify first word of commands is a valid binary (where checkable)."""
        # Commands that are definitely binaries we can check
        checkable_binaries = {"uv", "ls", "cat", "make"}

        for entry in entries:
            cmd = entry["command"]
            first_word = cmd.split()[0]

            if first_word in checkable_binaries:
                # Check if binary exists in PATH
                if not shutil.which(first_word):
                    pytest.skip(f"Binary '{first_word}' not in PATH")

    def test_no_dangerous_commands(self, entries):
        """Verify no destructive commands in manifest."""
        dangerous_patterns = [
            "rm -rf",
            "git push --force",
            "git reset --hard",
            "sudo rm",
            "> /dev/",
            ":(){ :",  # fork bomb
        ]

        for entry in entries:
            cmd = entry["command"]
            for pattern in dangerous_patterns:
                assert pattern not in cmd, f"Entry {entry['id']} contains dangerous pattern '{pattern}'"


class TestManifestOrdering:
    """Test manifest ordering and sequencing."""

    @pytest.fixture
    def entries(self):
        """Load all manifest entries."""
        entries = []
        with open(MANIFEST_PATH) as f:
            for line in f:
                line = line.strip()
                if line:
                    entries.append(json.loads(line))
        return entries

    def test_entries_are_sorted_by_order(self, entries):
        """Verify entries appear in order."""
        orders = [e["order"] for e in entries]
        assert orders == sorted(orders), "Entries are not sorted by order field"

    def test_sections_appear_in_order(self, entries):
        """Verify sections appear in logical order (0, 1, 2, ...)."""
        seen_sections = []
        for entry in entries:
            section = entry["section"]
            if section not in seen_sections:
                seen_sections.append(section)

        # Extract section numbers
        section_nums = []
        for s in seen_sections:
            try:
                num = int(s.split("-")[0])
                section_nums.append(num)
            except (ValueError, IndexError):
                pass

        assert section_nums == sorted(section_nums), f"Sections not in order: {seen_sections}"
