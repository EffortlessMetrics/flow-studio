#!/usr/bin/env python3
"""
gen_index_html.py - Generate Flow Studio index.html from fragments and assets.

Assembles Flow Studio HTML from:
- HTML fragments (swarm/tools/flow_studio_ui/fragments/*.html)
- Inline CSS (swarm/tools/flow_studio_ui/css/flow-studio.base.css)
- Inline JS bundle (swarm/tools/flow_studio_ui/js/*.js concatenated)

Usage:
    uv run swarm/tools/gen_index_html.py           # Generate
    uv run swarm/tools/gen_index_html.py --check   # Check if up-to-date

Exit codes:
    0 - Success (generated or check passed)
    1 - Failure (check failed, file out of date)
    2 - Error (missing source files)
"""

import argparse
import sys
from pathlib import Path
from typing import List

# Project root (two levels up from this script)
PROJECT_ROOT = Path(__file__).parent.parent.parent
UI_DIR = PROJECT_ROOT / "swarm" / "tools" / "flow_studio_ui"
FRAGMENTS_DIR = UI_DIR / "fragments"
CSS_FILE = UI_DIR / "css" / "flow-studio.base.css"
JS_DIR = UI_DIR / "js"
OUTPUT_HTML = UI_DIR / "index.html"

# Fragment assembly order (files in fragments/ directory)
FRAGMENT_ORDER = [
    "00-head.html",      # DOCTYPE, head, body start, app div start
    "10-header.html",    # Header region
    "20-sdlc-bar.html",  # SDLC progress bar
    "30-sidebar.html",   # Sidebar with flow list, run history
    "40-canvas.html",    # Main graph canvas
    "50-inspector.html", # Details/inspector panel
]

# Modal/overlay fragments to include after main content
MODAL_FRAGMENTS = [
    "60-modals.html",
    "65-context-budget-modal.html",
    "67-boundary-review.html",
]
FOOTER_FRAGMENT = "90-footer.html"

# JS files to bundle (in dependency order)
# This matches the order in the existing inline bundle
JS_BUNDLE_ORDER = [
    "api.js",
    "details.js",
    "domain.js",
    "flow-studio-app.js",
    "governance_ui.js",
    "graph.js",
    "graph_outline.js",
    "main.js",
    "runs_flows.js",
    "search.js",
    "selection.js",
    "selftest_ui.js",
    "shortcuts.js",
    "state.js",
    "tours.js",
    "ui_fragments.js",
    "utils.js",
    "flow_constants.js",
    "teaching_mode.js",
    "layout_spec.js",
    "run_history.js",
    "run_detail_modal.js",
]


def load_fragment(name: str) -> str:
    """Load a single HTML fragment."""
    path = FRAGMENTS_DIR / name
    if not path.exists():
        print(f"Error: Fragment not found: {path}")
        sys.exit(2)
    return path.read_text(encoding="utf-8")


def load_all_fragments() -> dict[str, str]:
    """Load all HTML fragments."""
    fragments = {}
    for f in FRAGMENTS_DIR.glob("*.html"):
        fragments[f.name] = f.read_text(encoding="utf-8")
    return fragments


def load_css() -> str:
    """Load CSS file content."""
    if not CSS_FILE.exists():
        print(f"Error: CSS file not found: {CSS_FILE}")
        sys.exit(2)
    return CSS_FILE.read_text(encoding="utf-8")


def bundle_js() -> str:
    """Bundle JS files into a single string with file comments."""
    if not JS_DIR.exists():
        print(f"Error: JS directory not found: {JS_DIR}")
        sys.exit(2)

    parts: List[str] = []

    # First, add files in the specified order
    added_files = set()
    for js_name in JS_BUNDLE_ORDER:
        js_path = JS_DIR / js_name
        if js_path.exists():
            content = js_path.read_text(encoding="utf-8").rstrip()
            parts.append(f"// {js_name}")
            parts.append(content)
            added_files.add(js_name)

    # Then add any remaining JS files not in the explicit order
    for js_path in sorted(JS_DIR.glob("*.js")):
        if js_path.name not in added_files:
            content = js_path.read_text(encoding="utf-8").rstrip()
            parts.append(f"// {js_path.name}")
            parts.append(content)

    return "\n".join(parts)


def generate_html() -> str:
    """Assemble full HTML from fragments and assets."""
    fragments = load_all_fragments()

    # Verify all required fragments exist
    required = FRAGMENT_ORDER + MODAL_FRAGMENTS + [FOOTER_FRAGMENT]
    for name in required:
        if name not in fragments:
            print(f"Error: Required fragment missing: {name}")
            sys.exit(2)

    parts: List[str] = []

    # 1. Opening fragments (head through inspector)
    for name in FRAGMENT_ORDER:
        parts.append(fragments[name].rstrip())

    # 2. Close app div and add module script
    parts.append("</div>")
    parts.append("")
    parts.append('<script type="module" src="js/main.js"></script>')
    parts.append("")

    # 3. Modals and overlays
    for modal_name in MODAL_FRAGMENTS:
        parts.append(fragments[modal_name].rstrip())
        parts.append("")

    # 4. Embedded assets comment and inline CSS
    css_content = load_css()
    parts.append("  <!-- Embedded Flow Studio assets for offline parity and test fixtures -->")
    parts.append('  <style data-inline-source="flowstudio-base-css">')
    parts.append(css_content.rstrip())
    parts.append("  </style>")

    # 5. Inline JS bundle
    js_bundle = bundle_js()
    parts.append('  <script type="application/json" data-inline-source="flowstudio-js-bundle">')
    parts.append(js_bundle)
    parts.append("  </script>")
    parts.append("")

    # 6. Footer (closing body/html)
    parts.append(fragments[FOOTER_FRAGMENT].strip())
    parts.append("")  # Final newline

    return "\n".join(parts)


def write_output(content: str) -> bool:
    """Write the generated HTML to the output file."""
    OUTPUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_HTML.write_text(content, encoding="utf-8")
    return True


def check_output(content: str) -> bool:
    """Check if generated content matches existing file."""
    if not OUTPUT_HTML.exists():
        print(f"ERROR: {OUTPUT_HTML} does not exist")
        return False

    existing = OUTPUT_HTML.read_text(encoding="utf-8")

    if content == existing:
        print(f"OK: {OUTPUT_HTML} is up to date")
        return True
    else:
        # Show some diff context for debugging
        content_lines = content.split("\n")
        existing_lines = existing.split("\n")

        print(f"ERROR: {OUTPUT_HTML} is out of date. Run: make gen-index-html")
        print(f"  Generated lines: {len(content_lines)}")
        print(f"  Existing lines: {len(existing_lines)}")

        # Find first differing line
        for i, (gen, exist) in enumerate(zip(content_lines, existing_lines)):
            if gen != exist:
                print(f"  First difference at line {i + 1}:")
                print(f"    Generated: {repr(gen[:100])}")
                print(f"    Existing:  {repr(exist[:100])}")
                break

        return False


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Generate Flow Studio index.html from fragments and assets"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check if generated file is up-to-date (don't regenerate)"
    )
    args = parser.parse_args()

    # Generate HTML content
    generated = generate_html()

    if args.check:
        # Check mode
        success = check_output(generated)
        sys.exit(0 if success else 1)
    else:
        # Generate mode
        write_output(generated)
        print(f"Generated {OUTPUT_HTML}")
        print(f"  Fragments: {len(list(FRAGMENTS_DIR.glob('*.html')))}")
        print(f"  CSS: {CSS_FILE.name}")
        print(f"  JS modules: {len(list(JS_DIR.glob('*.js')))}")
        sys.exit(0)


if __name__ == "__main__":
    main()
