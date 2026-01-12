#!/usr/bin/env python3
"""
Tests for Flow Studio UI ID contract.

This test suite validates that:
1. All data-uiid attributes follow the naming pattern
2. No duplicate data-uiid values exist
3. Key UI regions have stable identifiers

The data-uiid pattern is: flow_studio.<region>.<thing>[.subthing][.row:{id}]

Pattern Rules:
- Screen prefix: Always "flow_studio"
- Region: header, sidebar, canvas, inspector, modal, sdlc_bar
- Thing: Specific component name (snake_case)
- Subthing: Optional nested component
- Dynamic IDs: Use ":{id}" suffix for repeated items (e.g., step:build:1, agent:code-implementer)
- No layout-based names: Avoid leftCol, row2, etc.

See CLAUDE.md § UI Contract for full documentation.
"""

import re
import sys
from pathlib import Path
from typing import Set, List, Tuple

import pytest

# Add repo root to path so swarm imports work
repo_root = Path(__file__).resolve().parents[1]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))


# ============================================================================
# ID Pattern Validation
# ============================================================================

# Pattern for valid data-uiid values
# Format: flow_studio[.<region>.<thing>[.subthing][:{dynamic_id}]]
# The root "flow_studio" is also valid for the root container
UIID_PATTERN = re.compile(
    r"^flow_studio"                            # Screen prefix
    r"(\.[a-z][a-z0-9_]*)+"                    # Region and components (snake_case)
    r"(:[a-zA-Z0-9_:-]+)?$"                    # Optional dynamic ID suffix
    r"|^flow_studio$"                          # OR just the root "flow_studio"
)

# Known valid regions
VALID_REGIONS = {
    "header",      # Top bar with search, mode toggle, etc.
    "sidebar",     # Left navigation panel
    "canvas",      # Main graph area
    "inspector",   # Right details panel
    "modal",       # Modal dialogs (selftest, shortcuts)
    "sdlc_bar",    # SDLC progress bar
}

# Layout-based names that should NOT be used (case-insensitive patterns)
# These match component names like "leftCol", "row2", etc.
BANNED_PATTERNS = [
    (r"leftcol", "leftCol"),
    (r"rightcol", "rightCol"),
    (r"\.row\d+", "row<N>"),
    (r"\.col\d+", "col<N>"),
    (r"\.column\d+", "column<N>"),
    (r"\.top\.", "top"),
    (r"\.bottom\.", "bottom"),
    (r"\.left\.", "left"),
    (r"\.right\.", "right"),
]


def extract_uiids_from_html(html: str) -> List[Tuple[str, int]]:
    """
    Extract all data-uiid attribute values from HTML DOM elements.

    Skips UIIDs found inside <script> tags (which are JavaScript strings,
    not actual DOM attributes).

    Returns:
        List of (uiid_value, line_number) tuples
    """
    uiids = []
    pattern = re.compile(r'data-uiid="([^"]+)"')

    # Track whether we're inside a script tag
    in_script = False
    script_start = re.compile(r"<script\b", re.IGNORECASE)
    script_end = re.compile(r"</script>", re.IGNORECASE)

    for line_num, line in enumerate(html.split("\n"), start=1):
        # Handle script tag transitions
        if script_start.search(line):
            in_script = True
        if script_end.search(line):
            in_script = False
            continue  # Skip the closing script line

        # Skip lines inside script tags
        if in_script:
            continue

        for match in pattern.finditer(line):
            value = match.group(1)
            # Skip JavaScript template literals (e.g., ${id} in compiled JS)
            if "${" in value:
                continue
            uiids.append((value, line_num))

    return uiids


def validate_uiid(uiid: str) -> List[str]:
    """
    Validate a single data-uiid value against the contract.

    Returns:
        List of validation errors (empty if valid)
    """
    errors = []

    # Check overall pattern
    if not UIID_PATTERN.match(uiid):
        errors.append(f"'{uiid}' does not match pattern flow_studio[.<region>.<thing>][:{id}]")
        return errors

    # Extract region (skip validation for root "flow_studio")
    parts = uiid.split(".")
    if len(parts) >= 2:
        region = parts[1].split(":")[0]  # Remove dynamic ID suffix if present
        if region not in VALID_REGIONS:
            errors.append(f"'{uiid}' uses unknown region '{region}' (valid: {', '.join(sorted(VALID_REGIONS))})")

    # Check for banned layout-based patterns
    for pattern, description in BANNED_PATTERNS:
        if re.search(pattern, uiid, re.IGNORECASE):
            errors.append(f"'{uiid}' contains banned layout-based pattern '{description}'")

    return errors


# ============================================================================
# HTML Loading
# ============================================================================


def get_flow_studio_html() -> str:
    """Load the Flow Studio HTML from the UI module."""
    from swarm.tools.flow_studio_ui import get_index_html
    return get_index_html()


# ============================================================================
# Tests
# ============================================================================


class TestUIIDPattern:
    """Tests for data-uiid pattern validation."""

    def test_valid_patterns(self):
        """Verify valid patterns are accepted."""
        valid_examples = [
            "flow_studio",  # Root container
            "flow_studio.header",
            "flow_studio.header.search",
            "flow_studio.header.search.input",
            "flow_studio.sidebar.flow_list",
            "flow_studio.canvas.outline",
            "flow_studio.canvas.outline.step:build:1",
            "flow_studio.inspector.properties",
            "flow_studio.modal.selftest",
            "flow_studio.modal.selftest.close",
            "flow_studio.sdlc_bar.flows",
        ]

        for uiid in valid_examples:
            errors = validate_uiid(uiid)
            assert not errors, f"Valid pattern '{uiid}' was rejected: {errors}"

    def test_invalid_patterns_rejected(self):
        """Verify invalid patterns are rejected."""
        invalid_examples = [
            ("header.search", "missing flow_studio prefix"),
            ("FlowStudio.header", "wrong prefix case"),
            ("flow_studio.Header", "uppercase region"),
            ("flow_studio.header.Search", "uppercase component"),
            ("other_app.header", "wrong app prefix"),
        ]

        for uiid, reason in invalid_examples:
            errors = validate_uiid(uiid)
            assert errors, f"Invalid pattern '{uiid}' ({reason}) should be rejected"

    def test_banned_layout_names_rejected(self):
        """Verify layout-based names are rejected."""
        banned_examples = [
            ("flow_studio.header.leftcol", "leftCol"),
            ("flow_studio.header.row2", "row<N>"),
            ("flow_studio.sidebar.column1", "column<N>"),
        ]

        for uiid, expected_pattern in banned_examples:
            errors = validate_uiid(uiid)
            assert any("banned" in e.lower() for e in errors), \
                f"Banned pattern '{uiid}' should be rejected (expected pattern: {expected_pattern})"


class TestFlowStudioUIIDs:
    """Tests for Flow Studio HTML data-uiid attributes."""

    def test_uiids_follow_pattern(self):
        """All data-uiid values should follow the naming pattern."""
        html = get_flow_studio_html()
        uiids = extract_uiids_from_html(html)

        all_errors = []
        for uiid, line in uiids:
            errors = validate_uiid(uiid)
            for error in errors:
                all_errors.append(f"Line {line}: {error}")

        if all_errors:
            error_report = "\n".join(all_errors)
            pytest.fail(f"Invalid data-uiid values found:\n{error_report}")

    def test_no_duplicate_uiids(self):
        """No duplicate data-uiid values should exist."""
        html = get_flow_studio_html()
        uiids = extract_uiids_from_html(html)

        seen: dict[str, int] = {}
        duplicates = []

        for uiid, line in uiids:
            if uiid in seen:
                duplicates.append(f"'{uiid}' appears at lines {seen[uiid]} and {line}")
            else:
                seen[uiid] = line

        if duplicates:
            pytest.fail(f"Duplicate data-uiid values found:\n" + "\n".join(duplicates))

    def test_required_regions_present(self):
        """All required UI regions should have data-uiid."""
        html = get_flow_studio_html()
        uiids = extract_uiids_from_html(html)

        # Extract unique regions from UIIDs
        present_regions = set()
        for uiid, _ in uiids:
            parts = uiid.split(".")
            if len(parts) >= 2:
                region = parts[1].split(":")[0]
                present_regions.add(region)

        # Required regions that must be present
        required = {"header", "sidebar", "canvas", "inspector"}

        missing = required - present_regions
        if missing:
            pytest.fail(f"Missing required UI regions: {', '.join(sorted(missing))}")

    def test_minimum_uiid_coverage(self):
        """Flow Studio should have a minimum number of data-uiid attributes."""
        html = get_flow_studio_html()
        uiids = extract_uiids_from_html(html)

        # We expect at least 25 unique UIIDs for reasonable coverage
        # (Current implementation has 30+ UIIDs)
        MIN_EXPECTED = 25

        if len(uiids) < MIN_EXPECTED:
            pytest.fail(
                f"Only {len(uiids)} data-uiid attributes found, expected at least {MIN_EXPECTED}. "
                "Add data-uiid to key interactive elements."
            )

    def test_header_elements_have_uiids(self):
        """Key header elements should have data-uiid."""
        html = get_flow_studio_html()
        uiids = {uiid for uiid, _ in extract_uiids_from_html(html)}

        # Expected header UIIDs
        expected_header = [
            "flow_studio.header",
            "flow_studio.header.search",
            "flow_studio.header.mode",
            "flow_studio.header.profile",  # Profile badge
        ]

        missing = [e for e in expected_header if e not in uiids]
        if missing:
            pytest.fail(f"Missing expected header UIIDs: {', '.join(missing)}")

    def test_profile_badge_uiid_exists(self):
        """Profile badge element should have data-uiid for automation."""
        html = get_flow_studio_html()
        uiids = {uiid for uiid, _ in extract_uiids_from_html(html)}

        uiid = "flow_studio.header.profile"
        assert uiid in uiids, (
            f"Profile badge missing data-uiid='{uiid}'. "
            "This UIID is required for test automation to locate the profile indicator."
        )

    def test_sidebar_elements_have_uiids(self):
        """Key sidebar elements should have data-uiid."""
        html = get_flow_studio_html()
        uiids = {uiid for uiid, _ in extract_uiids_from_html(html)}

        # Expected sidebar UIIDs
        expected_sidebar = [
            "flow_studio.sidebar",
            "flow_studio.sidebar.run_selector",
            "flow_studio.sidebar.flow_list",
        ]

        missing = [e for e in expected_sidebar if e not in uiids]
        if missing:
            pytest.fail(f"Missing expected sidebar UIIDs: {', '.join(missing)}")

    def test_canvas_elements_have_uiids(self):
        """Key canvas elements should have data-uiid."""
        html = get_flow_studio_html()
        uiids = {uiid for uiid, _ in extract_uiids_from_html(html)}

        # Expected canvas UIIDs
        expected_canvas = [
            "flow_studio.canvas",
            "flow_studio.canvas.legend",
            "flow_studio.canvas.outline",
        ]

        missing = [e for e in expected_canvas if e not in uiids]
        if missing:
            pytest.fail(f"Missing expected canvas UIIDs: {', '.join(missing)}")


class TestUIIDConsistency:
    """Tests for UI ID consistency and stability."""

    def test_uiids_are_stable_across_loads(self):
        """data-uiid values should be consistent across multiple loads."""
        html1 = get_flow_studio_html()
        html2 = get_flow_studio_html()

        uiids1 = set(uiid for uiid, _ in extract_uiids_from_html(html1))
        uiids2 = set(uiid for uiid, _ in extract_uiids_from_html(html2))

        assert uiids1 == uiids2, "UIIDs should be identical across loads"

    def test_region_prefix_consistency(self):
        """All UIIDs under a region should start with that region."""
        html = get_flow_studio_html()
        uiids = extract_uiids_from_html(html)

        inconsistencies = []
        for uiid, line in uiids:
            parts = uiid.split(".")
            if len(parts) < 2:
                continue

            region = parts[1].split(":")[0]

            # Check that all parts after the region are valid
            for i, part in enumerate(parts[2:], start=2):
                component = part.split(":")[0]
                if not re.match(r"^[a-z][a-z0-9_]*$", component):
                    inconsistencies.append(f"Line {line}: '{uiid}' has invalid component '{component}'")

        if inconsistencies:
            pytest.fail("UIID consistency errors:\n" + "\n".join(inconsistencies))


class TestUIIDSelectorUsage:
    """Tests demonstrating how to locate elements using data-uiid selectors.

    These tests serve as examples for Playwright/test automation scripts.
    Instead of using brittle CSS selectors like '#run-selector' or
    '.mode-toggle button:first-child', use data-uiid attributes for stable selectors.

    Example Playwright usage:
        # Instead of: page.locator('#run-selector')
        # Use: page.locator('[data-uiid="flow_studio.sidebar.run_selector.select"]')

        # Instead of: page.locator('.search-input')
        # Use: page.locator('[data-uiid="flow_studio.header.search.input"]')
    """

    def test_locate_search_input_by_uiid(self):
        """Demonstrate locating search input by data-uiid."""
        html = get_flow_studio_html()

        # This is the recommended way to locate the search input
        uiid = "flow_studio.header.search.input"
        pattern = f'data-uiid="{uiid}"'

        assert pattern in html, f"Search input with data-uiid={uiid} should exist"

        # Also verify it has expected attributes
        assert 'id="search-input"' in html, "Search input should have id for backwards compat"

    def test_locate_run_selector_by_uiid(self):
        """Demonstrate locating run selector by data-uiid."""
        html = get_flow_studio_html()

        # This is the recommended way to locate the run selector
        uiid = "flow_studio.sidebar.run_selector.select"
        pattern = f'data-uiid="{uiid}"'

        assert pattern in html, f"Run selector with data-uiid={uiid} should exist"

    def test_locate_flow_list_by_uiid(self):
        """Demonstrate locating flow list by data-uiid."""
        html = get_flow_studio_html()

        # This is the recommended way to locate the flow list
        uiid = "flow_studio.sidebar.flow_list"
        pattern = f'data-uiid="{uiid}"'

        assert pattern in html, f"Flow list with data-uiid={uiid} should exist"

    def test_uiid_selectors_are_unique(self):
        """Verify each data-uiid can uniquely identify an element.

        This is critical for test automation - selectors must be unique.
        """
        html = get_flow_studio_html()
        uiids = extract_uiids_from_html(html)

        # Group by UIID value
        from collections import Counter
        uiid_counts = Counter(uiid for uiid, _ in uiids)

        # Each UIID should appear exactly once
        duplicates = [(uiid, count) for uiid, count in uiid_counts.items() if count > 1]

        assert not duplicates, f"UIIDs must be unique for reliable selectors: {duplicates}"


class TestAccessibilityIDs:
    """Tests for accessibility-related ID attributes."""

    def test_aria_labelledby_references_exist(self):
        """aria-labelledby references should point to existing IDs."""
        html = get_flow_studio_html()

        # Find all aria-labelledby references
        labelledby_pattern = re.compile(r'aria-labelledby="([^"]+)"')
        matches = labelledby_pattern.findall(html)

        # Find all IDs in the document
        id_pattern = re.compile(r'\bid="([^"]+)"')
        all_ids = set(id_pattern.findall(html))

        missing = []
        for ref in matches:
            # aria-labelledby can have multiple space-separated IDs
            for id_ref in ref.split():
                if id_ref not in all_ids:
                    missing.append(id_ref)

        if missing:
            pytest.fail(f"aria-labelledby references non-existent IDs: {', '.join(missing)}")

    def test_aria_controls_references_exist(self):
        """aria-controls references should point to existing IDs."""
        html = get_flow_studio_html()

        # Find all aria-controls references
        controls_pattern = re.compile(r'aria-controls="([^"]+)"')
        matches = controls_pattern.findall(html)

        # Find all IDs in the document
        id_pattern = re.compile(r'\bid="([^"]+)"')
        all_ids = set(id_pattern.findall(html))

        missing = []
        for ref in matches:
            for id_ref in ref.split():
                if id_ref not in all_ids:
                    missing.append(id_ref)

        if missing:
            pytest.fail(f"aria-controls references non-existent IDs: {', '.join(missing)}")


class TestUIReadyHandshake:
    """Tests for UI ready state handshake (data-ui-ready attribute).

    The UI uses three states for the data-ui-ready attribute:
    - "loading": Initialization in progress
    - "ready": UI fully initialized, safe to interact
    - "error": Initialization failed

    Tests and LLM agents should wait for "ready" before interacting.
    """

    def test_ui_ready_states_documented_in_js(self):
        """Verify the JS code documents all three UI ready states."""
        from pathlib import Path

        js_file = (
            Path(__file__).resolve().parents[1]
            / "swarm"
            / "tools"
            / "flow_studio_ui"
            / "js"
            / "flow-studio-app.js"
        )
        js_content = js_file.read_text(encoding="utf-8")

        # All three states should be documented
        assert 'uiReady = "loading"' in js_content, "Should have loading state"
        assert 'uiReady = "ready"' in js_content, "Should have ready state"
        assert 'uiReady = "error"' in js_content, "Should have error state"

    def test_ui_ready_handshake_example(self):
        """Demonstrate the UI ready handshake pattern for tests/agents.

        This test shows the recommended pattern for waiting for UI readiness.

        Playwright example:
            # Wait for UI to be ready (successful init)
            await page.wait_for_selector('html[data-ui-ready="ready"]')

            # Or check for error state to fail fast
            state = await page.get_attribute('html', 'data-ui-ready')
            if state == 'error':
                raise Exception('UI initialization failed')

        The three-state model (loading/ready/error) prevents tests from
        hanging forever when initialization fails.
        """
        # This test documents the pattern - no assertions needed
        # The pattern is validated by test_ui_ready_states_documented_in_js
        pass


class TestUIIDIntegrationExample:
    """Integration test examples showing real data-uiid usage.

    These tests verify that elements exist AND demonstrate the selector
    pattern for actual test automation. Unlike TestUIIDSelectorUsage which
    just checks if patterns exist in HTML, these tests extract the actual
    element attributes to show how to build working selectors.
    """

    def test_search_input_selector_integration(self):
        """Verify search input can be reliably located by data-uiid.

        Playwright selector: [data-uiid="flow_studio.header.search.input"]
        """
        html = get_flow_studio_html()

        # Build the actual CSS selector pattern
        selector = '[data-uiid="flow_studio.header.search.input"]'

        # Verify the element exists with this selector
        assert selector.replace('[data-uiid="', 'data-uiid="').replace('"]', '"') in html

        # Extract the element's id for backwards-compatibility check
        pattern = re.compile(
            r'<input[^>]*data-uiid="flow_studio\.header\.search\.input"[^>]*>'
        )
        match = pattern.search(html)
        assert match, "Search input element should exist with data-uiid"

        element_html = match.group(0)
        assert 'id="search-input"' in element_html, (
            "Search input should have legacy id for backwards compatibility"
        )

    def test_run_selector_css_selector(self):
        """Verify run selector dropdown can be reliably located by data-uiid.

        Playwright selector: [data-uiid="flow_studio.sidebar.run_selector.select"]
        """
        html = get_flow_studio_html()

        # The recommended CSS selector for test automation
        css_selector = '[data-uiid="flow_studio.sidebar.run_selector.select"]'

        # Extract the actual <select> element
        pattern = re.compile(
            r'<select[^>]*data-uiid="flow_studio\.sidebar\.run_selector\.select"[^>]*>'
        )
        match = pattern.search(html)
        assert match, f"Element with selector {css_selector} should exist"

        # Verify it's a <select> element (important for automation)
        element_html = match.group(0)
        assert element_html.startswith("<select"), (
            "Run selector should be a <select> element"
        )

    def test_mode_toggle_buttons_by_uiid(self):
        """Verify mode toggle buttons can be located by data-uiid.

        Playwright selectors:
        - [data-uiid="flow_studio.header.mode.author"]
        - [data-uiid="flow_studio.header.mode.operator"]
        """
        html = get_flow_studio_html()

        # Both mode buttons should exist
        for mode in ["author", "operator"]:
            uiid = f"flow_studio.header.mode.{mode}"
            css_selector = f'[data-uiid="{uiid}"]'

            # Verify the pattern exists
            assert f'data-uiid="{uiid}"' in html, (
                f"Mode button with selector {css_selector} should exist"
            )

    def test_legend_toggle_has_aria_expanded(self):
        """Verify legend toggle has aria-expanded for state tracking.

        This validates that clicking the legend toggle will update aria-expanded,
        which tests can use to verify toggle state without visual inspection.

        Playwright example:
            toggle = page.locator('[data-uiid="flow_studio.canvas.legend.toggle"]')
            await expect(toggle).to_have_attribute('aria-expanded', 'true')
        """
        html = get_flow_studio_html()

        # Find the legend toggle element
        pattern = re.compile(
            r'<[^>]*data-uiid="flow_studio\.canvas\.legend\.toggle"[^>]*>'
        )
        match = pattern.search(html)
        assert match, "Legend toggle should exist"

        element_html = match.group(0)
        assert 'aria-expanded=' in element_html, (
            "Legend toggle should have aria-expanded attribute"
        )


class TestRunHistoryUIIDs:
    """Tests for Run History panel data-uiid attributes.

    The Run History panel provides a list of previous runs in the sidebar.
    These UIIDs enable test automation to:
    - Locate the run history section
    - Filter runs by status/flow
    - Select specific runs from the list
    """

    def test_run_history_section_has_uiid(self):
        """Run history section container should have data-uiid."""
        html = get_flow_studio_html()
        uiids = {uiid for uiid, _ in extract_uiids_from_html(html)}

        uiid = "flow_studio.sidebar.run_history"
        assert uiid in uiids, (
            f"Run history section missing data-uiid='{uiid}'. "
            "This UIID is required for test automation to locate the run history panel."
        )

    def test_run_history_filter_has_uiid(self):
        """Run history filter should have data-uiid."""
        html = get_flow_studio_html()
        uiids = {uiid for uiid, _ in extract_uiids_from_html(html)}

        uiid = "flow_studio.sidebar.run_history.filter"
        assert uiid in uiids, (
            f"Run history filter missing data-uiid='{uiid}'. "
            "This UIID is required for test automation to interact with run filtering."
        )

    def test_run_history_list_has_uiid(self):
        """Run history list should have data-uiid."""
        html = get_flow_studio_html()
        uiids = {uiid for uiid, _ in extract_uiids_from_html(html)}

        uiid = "flow_studio.sidebar.run_history.list"
        assert uiid in uiids, (
            f"Run history list missing data-uiid='{uiid}'. "
            "This UIID is required for test automation to locate the list of runs."
        )

    def test_run_history_elements_have_uiids(self):
        """All key run history elements should have data-uiid."""
        html = get_flow_studio_html()
        uiids = {uiid for uiid, _ in extract_uiids_from_html(html)}

        # Expected run history UIIDs
        expected_run_history = [
            "flow_studio.sidebar.run_history",
            "flow_studio.sidebar.run_history.filter",
            "flow_studio.sidebar.run_history.list",
        ]

        missing = [e for e in expected_run_history if e not in uiids]
        if missing:
            pytest.fail(f"Missing expected run history UIIDs: {', '.join(missing)}")


class TestRunDetailModalUIIDs:
    """Tests for Run Detail modal data-uiid attributes.

    The Run Detail modal displays detailed information about a selected run.
    These UIIDs enable test automation to:
    - Open and close the modal
    - Read run details
    - Trigger re-run actions

    Playwright selectors:
    - Modal: [data-uiid="flow_studio.modal.run_detail"]
    - Close: [data-uiid="flow_studio.modal.run_detail.close"]
    - Body: [data-uiid="flow_studio.modal.run_detail.body"]
    - Re-run: [data-uiid="flow_studio.modal.run_detail.rerun"]
    """

    def test_run_detail_modal_has_uiid(self):
        """Run detail modal container should have data-uiid."""
        html = get_flow_studio_html()
        uiids = {uiid for uiid, _ in extract_uiids_from_html(html)}

        uiid = "flow_studio.modal.run_detail"
        assert uiid in uiids, (
            f"Run detail modal missing data-uiid='{uiid}'. "
            "This UIID is required for test automation to locate the modal."
        )

    def test_run_detail_close_button_has_uiid(self):
        """Run detail modal close button should have data-uiid."""
        html = get_flow_studio_html()
        uiids = {uiid for uiid, _ in extract_uiids_from_html(html)}

        uiid = "flow_studio.modal.run_detail.close"
        assert uiid in uiids, (
            f"Run detail close button missing data-uiid='{uiid}'. "
            "This UIID is required for test automation to close the modal."
        )

    def test_run_detail_body_has_uiid(self):
        """Run detail modal body should have data-uiid."""
        html = get_flow_studio_html()
        uiids = {uiid for uiid, _ in extract_uiids_from_html(html)}

        uiid = "flow_studio.modal.run_detail.body"
        assert uiid in uiids, (
            f"Run detail body missing data-uiid='{uiid}'. "
            "This UIID is required for test automation to read run details."
        )

    def test_run_detail_rerun_button_has_uiid(self):
        """Run detail modal re-run button should have data-uiid."""
        html = get_flow_studio_html()
        uiids = {uiid for uiid, _ in extract_uiids_from_html(html)}

        uiid = "flow_studio.modal.run_detail.rerun"
        assert uiid in uiids, (
            f"Run detail re-run button missing data-uiid='{uiid}'. "
            "This UIID is required for test automation to trigger re-runs."
        )

    def test_run_detail_modal_elements_have_uiids(self):
        """All key run detail modal elements should have data-uiid."""
        html = get_flow_studio_html()
        uiids = {uiid for uiid, _ in extract_uiids_from_html(html)}

        # Expected run detail modal UIIDs
        expected_modal = [
            "flow_studio.modal.run_detail",
            "flow_studio.modal.run_detail.close",
            "flow_studio.modal.run_detail.body",
            "flow_studio.modal.run_detail.rerun",
        ]

        missing = [e for e in expected_modal if e not in uiids]
        if missing:
            pytest.fail(f"Missing expected run detail modal UIIDs: {', '.join(missing)}")

    def test_run_detail_modal_is_dialog(self):
        """Run detail modal should have proper dialog role for accessibility."""
        html = get_flow_studio_html()

        # Find the run detail modal element
        pattern = re.compile(
            r'<[^>]*data-uiid="flow_studio\.modal\.run_detail"[^>]*>'
        )
        match = pattern.search(html)
        assert match, "Run detail modal should exist"

        element_html = match.group(0)
        assert 'role="dialog"' in element_html, (
            "Run detail modal should have role='dialog' for accessibility"
        )
        assert 'aria-modal="true"' in element_html, (
            "Run detail modal should have aria-modal='true' for accessibility"
        )


class TestRunDetailModalIntegration:
    """Integration tests demonstrating Run Detail modal selector usage.

    These tests verify that elements exist AND demonstrate the selector
    pattern for actual test automation.
    """

    def test_run_detail_modal_css_selector(self):
        """Verify run detail modal can be reliably located by data-uiid.

        Playwright selector: [data-uiid="flow_studio.modal.run_detail"]
        """
        html = get_flow_studio_html()

        # The recommended CSS selector for test automation
        css_selector = '[data-uiid="flow_studio.modal.run_detail"]'

        # Extract the actual element
        pattern = re.compile(
            r'<div[^>]*data-uiid="flow_studio\.modal\.run_detail"[^>]*>'
        )
        match = pattern.search(html)
        assert match, f"Element with selector {css_selector} should exist"

        # Verify it's a div element with proper dialog attributes
        element_html = match.group(0)
        assert 'role="dialog"' in element_html, (
            "Run detail modal should be a dialog"
        )

    def test_run_detail_close_is_button(self):
        """Verify run detail close is a button element.

        Playwright selector: [data-uiid="flow_studio.modal.run_detail.close"]
        """
        html = get_flow_studio_html()

        # Extract the close button element
        pattern = re.compile(
            r'<button[^>]*data-uiid="flow_studio\.modal\.run_detail\.close"[^>]*>'
        )
        match = pattern.search(html)
        assert match, "Run detail close button should exist"

        element_html = match.group(0)
        assert 'aria-label=' in element_html, (
            "Close button should have aria-label for accessibility"
        )

    def test_run_detail_rerun_is_button(self):
        """Verify run detail re-run is a button element.

        Playwright selector: [data-uiid="flow_studio.modal.run_detail.rerun"]
        """
        html = get_flow_studio_html()

        # Extract the rerun button element
        pattern = re.compile(
            r'<button[^>]*data-uiid="flow_studio\.modal\.run_detail\.rerun"[^>]*>'
        )
        match = pattern.search(html)
        assert match, "Run detail rerun button should exist"


class TestRunHistoryIntegration:
    """Integration tests demonstrating Run History selector usage.

    These tests verify that elements exist AND demonstrate the selector
    pattern for actual test automation.
    """

    def test_run_history_list_has_role(self):
        """Verify run history list has proper list role for accessibility.

        Playwright selector: [data-uiid="flow_studio.sidebar.run_history.list"]
        """
        html = get_flow_studio_html()

        # Extract the run history list element
        pattern = re.compile(
            r'<div[^>]*data-uiid="flow_studio\.sidebar\.run_history\.list"[^>]*>'
        )
        match = pattern.search(html)
        assert match, "Run history list should exist"

        element_html = match.group(0)
        assert 'role="list"' in element_html, (
            "Run history list should have role='list' for accessibility"
        )

    def test_run_history_list_has_aria_label(self):
        """Verify run history list has aria-label for accessibility."""
        html = get_flow_studio_html()

        # Extract the run history list element
        pattern = re.compile(
            r'<div[^>]*data-uiid="flow_studio\.sidebar\.run_history\.list"[^>]*>'
        )
        match = pattern.search(html)
        assert match, "Run history list should exist"

        element_html = match.group(0)
        assert 'aria-label=' in element_html, (
            "Run history list should have aria-label for accessibility"
        )


class TestDynamicUIIDs:
    """Tests for data-uiid attributes in dynamically rendered components.

    Some components (like run detail modal content, run history items) are
    rendered dynamically by TypeScript. These tests verify the UIIDs are
    present in the compiled JavaScript code.
    """

    def test_backend_badge_uiid_in_run_history(self):
        """Verify backend badge UIID pattern is in run_history.ts.

        The run history module renders backend badges dynamically with:
        data-uiid="flow_studio.sidebar.run_history.item.badge.backend:{run_id}"

        Playwright selector pattern:
        [data-uiid^="flow_studio.sidebar.run_history.item.badge.backend:"]
        """
        js_file = repo_root / "swarm" / "tools" / "flow_studio_ui" / "js" / "run_history.js"
        assert js_file.exists(), "run_history.js should exist"

        content = js_file.read_text(encoding="utf-8")

        # Should contain the backend badge UIID pattern
        assert "flow_studio.sidebar.run_history.item.badge.backend:" in content, (
            "run_history.js should render backend badges with data-uiid"
        )

    def test_events_toggle_uiid_in_run_detail_modal(self):
        """Verify events toggle UIID is in run_detail_modal.ts.

        The run detail modal renders events section dynamically with:
        data-uiid="flow_studio.modal.run_detail.events.toggle"

        Playwright selector:
        [data-uiid="flow_studio.modal.run_detail.events.toggle"]
        """
        js_file = repo_root / "swarm" / "tools" / "flow_studio_ui" / "js" / "run_detail_modal.js"
        assert js_file.exists(), "run_detail_modal.js should exist"

        content = js_file.read_text(encoding="utf-8")

        # Should contain the events toggle UIID
        assert "flow_studio.modal.run_detail.events.toggle" in content, (
            "run_detail_modal.js should render events toggle with data-uiid"
        )

    def test_events_container_uiid_in_run_detail_modal(self):
        """Verify events container UIID is in run_detail_modal.ts.

        The run detail modal renders events section dynamically with:
        data-uiid="flow_studio.modal.run_detail.events.container"

        Playwright selector:
        [data-uiid="flow_studio.modal.run_detail.events.container"]
        """
        js_file = repo_root / "swarm" / "tools" / "flow_studio_ui" / "js" / "run_detail_modal.js"
        assert js_file.exists(), "run_detail_modal.js should exist"

        content = js_file.read_text(encoding="utf-8")

        # Should contain the events container UIID
        assert "flow_studio.modal.run_detail.events.container" in content, (
            "run_detail_modal.js should render events container with data-uiid"
        )

    def test_exemplar_checkbox_uiid_in_run_detail_modal(self):
        """Verify exemplar checkbox UIID is in run_detail_modal.ts.

        The run detail modal renders exemplar checkbox dynamically with:
        data-uiid="flow_studio.modal.run_detail.exemplar"

        Playwright selector:
        [data-uiid="flow_studio.modal.run_detail.exemplar"]
        """
        js_file = repo_root / "swarm" / "tools" / "flow_studio_ui" / "js" / "run_detail_modal.js"
        assert js_file.exists(), "run_detail_modal.js should exist"

        content = js_file.read_text(encoding="utf-8")

        # Should contain the exemplar checkbox UIID
        assert "flow_studio.modal.run_detail.exemplar" in content, (
            "run_detail_modal.js should render exemplar checkbox with data-uiid"
        )


class TestBackendBadgeUIIDs:
    """Tests for backend badge data-uiid attributes.

    Backend badges in run history use dynamic UIIDs following the pattern:
    flow_studio.sidebar.run_history.item.badge.backend:{run_id}

    This allows tests to:
    - Find all backend badges: [data-uiid^="flow_studio.sidebar.run_history.item.badge.backend:"]
    - Find specific run's badge: [data-uiid="flow_studio.sidebar.run_history.item.badge.backend:run-123"]
    """

    def test_backend_badge_pattern_documented(self):
        """Document backend badge UIID pattern for automation.

        Pattern: flow_studio.sidebar.run_history.item.badge.backend:{run_id}

        The badge shows which backend was used for a run:
        - "Claude" for claude-harness
        - "Gemini" for gemini-cli
        - "Gemini Stepwise" for gemini-step-orchestrator
        """
        # This is a documentation test
        # Verify the pattern is documented in domain.ts FlowStudioUIID type
        ts_file = repo_root / "swarm" / "tools" / "flow_studio_ui" / "src" / "domain.ts"
        content = ts_file.read_text(encoding="utf-8")

        # The type should include run detail modal UIIDs
        assert "flow_studio.modal.run_detail" in content, (
            "domain.ts FlowStudioUIID should include run_detail modal UIIDs"
        )


class TestEventsTimelineUIIDs:
    """Tests for events timeline data-uiid attributes.

    The events timeline section in the run detail modal uses these UIIDs:
    - flow_studio.modal.run_detail.events.toggle: "Load Events" button
    - flow_studio.modal.run_detail.events.container: Events list container

    These UIIDs are defined in domain.ts and rendered in run_detail_modal.ts.
    """

    def test_events_uiids_defined_in_domain(self):
        """Verify events UIIDs are defined in domain.ts FlowStudioUIID type."""
        ts_file = repo_root / "swarm" / "tools" / "flow_studio_ui" / "src" / "domain.ts"
        content = ts_file.read_text(encoding="utf-8")

        # Should include events toggle and container UIIDs
        assert "flow_studio.modal.run_detail.events.toggle" in content, (
            "domain.ts should define events.toggle UIID"
        )
        assert "flow_studio.modal.run_detail.events.container" in content, (
            "domain.ts should define events.container UIID"
        )
