#!/usr/bin/env python3
"""
gen_capabilities_doc.py - Generate CAPABILITIES.md from specs/capabilities.yaml

This script generates a human-readable Markdown document from the capability
registry. The generated doc is for reading only - all edits should be made
to specs/capabilities.yaml.

Usage:
    uv run swarm/tools/gen_capabilities_doc.py           # Generate doc
    uv run swarm/tools/gen_capabilities_doc.py --check   # Check if up-to-date

Exit codes:
    0 - Success (or doc is up-to-date in --check mode)
    1 - Doc is out of date (--check mode only)
    2 - Error (file not found, parse error, etc.)
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

# Find repo root
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent

# Paths
REGISTRY_PATH = REPO_ROOT / "specs" / "capabilities.yaml"
OUTPUT_PATH = REPO_ROOT / "docs" / "reference" / "CAPABILITIES.md"

# Header for generated doc
HEADER = """# Capability Registry

> **GENERATED FILE - DO NOT EDIT**
>
> Source: `specs/capabilities.yaml`
> Regenerate: `make gen-capabilities-doc`

This document lists what Flow Studio can do, with evidence pointers.

## Status Legend

| Status | Meaning |
|--------|---------|
| **implemented** | Has code + test evidence; safe to claim publicly |
| **supported** | Has code but incomplete/no formal tests; use with caveats |
| **aspirational** | Design only; NOT shipped; do NOT claim as available |

---

"""


def parse_yaml_simple(content: str) -> Dict[str, Any]:
    """Parse YAML using PyYAML (standard library not sufficient for complex YAML)."""
    try:
        import yaml
        return yaml.safe_load(content)
    except ImportError:
        # Fallback to a basic parser if yaml not available
        # This won't handle complex YAML but works for simple cases
        raise ImportError("PyYAML required: pip install pyyaml")


def status_badge(status: str) -> str:
    """Return a badge for the status."""
    if status == "implemented":
        return "**implemented**"
    elif status == "supported":
        return "*supported*"
    elif status == "aspirational":
        return "~aspirational~"
    return status


def render_evidence(evidence: Dict[str, Any]) -> List[str]:
    """Render evidence section as markdown lines."""
    lines = []

    # Code evidence
    code = evidence.get("code", [])
    if code:
        lines.append("  - **Code:**")
        for c in code:
            path = c.get("path", "")
            symbol = c.get("symbol", "")
            if symbol:
                lines.append(f"    - `{path}` → `{symbol}`")
            else:
                lines.append(f"    - `{path}`")

    # Test evidence
    tests = evidence.get("tests", [])
    if tests:
        lines.append("  - **Tests:**")
        for t in tests:
            kind = t.get("kind", "")
            ref = t.get("ref", "")
            lines.append(f"    - [{kind}] `{ref}`")

    # Design evidence (for aspirational)
    design = evidence.get("design", [])
    if design:
        lines.append("  - **Design:**")
        for d in design:
            path = d.get("path", "")
            lines.append(f"    - `{path}`")

    return lines


def render_capability(cap: Dict[str, Any]) -> List[str]:
    """Render a single capability as markdown lines."""
    lines = []

    cap_id = cap.get("id", "unknown")
    status = cap.get("status", "unknown")
    summary = cap.get("summary", "")
    notes = cap.get("notes", "")
    evidence = cap.get("evidence", {})

    lines.append(f"### `{cap_id}`")
    lines.append("")
    lines.append(f"**Status:** {status_badge(status)}")
    lines.append("")
    if summary:
        lines.append(summary)
        lines.append("")
    if notes:
        lines.append(f"> {notes}")
        lines.append("")

    # Evidence
    if evidence:
        lines.append("**Evidence:**")
        lines.extend(render_evidence(evidence))
        lines.append("")

    return lines


def render_surface(surface_key: str, surface_data: Dict[str, Any]) -> List[str]:
    """Render a surface section as markdown lines."""
    lines = []

    description = surface_data.get("description", "")
    capabilities = surface_data.get("capabilities", [])

    # Surface header
    lines.append(f"## {surface_key.title()}")
    lines.append("")
    if description:
        lines.append(f"*{description}*")
        lines.append("")

    # Summary table
    if capabilities:
        lines.append("| Capability | Status | Summary |")
        lines.append("|------------|--------|---------|")
        for cap in capabilities:
            cap_id = cap.get("id", "")
            status = cap.get("status", "")
            summary = cap.get("summary", "")
            # Truncate summary for table
            if len(summary) > 60:
                summary = summary[:57] + "..."
            lines.append(f"| `{cap_id}` | {status} | {summary} |")
        lines.append("")

    # Detailed sections
    for cap in capabilities:
        lines.extend(render_capability(cap))

    lines.append("---")
    lines.append("")

    return lines


def generate_doc(registry: Dict[str, Any]) -> str:
    """Generate the full markdown document."""
    lines = [HEADER]

    # Table of contents
    surfaces = registry.get("surfaces", {})
    lines.append("## Table of Contents")
    lines.append("")
    for surface_key in surfaces:
        lines.append(f"- [{surface_key.title()}](#{surface_key})")
    lines.append("")
    lines.append("---")
    lines.append("")

    # Surfaces
    for surface_key, surface_data in surfaces.items():
        lines.extend(render_surface(surface_key, surface_data))

    # Footer with stats
    total_caps = 0
    by_status = {"implemented": 0, "supported": 0, "aspirational": 0}
    for surface_data in surfaces.values():
        for cap in surface_data.get("capabilities", []):
            total_caps += 1
            status = cap.get("status", "")
            if status in by_status:
                by_status[status] += 1

    lines.append("## Statistics")
    lines.append("")
    lines.append(f"- **Total capabilities:** {total_caps}")
    lines.append(f"- **Implemented:** {by_status['implemented']}")
    lines.append(f"- **Supported:** {by_status['supported']}")
    lines.append(f"- **Aspirational:** {by_status['aspirational']}")
    lines.append("")

    # Generation timestamp
    now = datetime.now(timezone.utc).isoformat()
    lines.append("---")
    lines.append("")
    lines.append(f"*Generated: {now}*")
    lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Generate CAPABILITIES.md from specs/capabilities.yaml"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check if doc is up-to-date (exit 1 if not)"
    )
    args = parser.parse_args()

    # Check registry exists
    if not REGISTRY_PATH.exists():
        print(f"ERROR: Registry not found: {REGISTRY_PATH}", file=sys.stderr)
        sys.exit(2)

    # Parse registry
    try:
        content = REGISTRY_PATH.read_text(encoding="utf-8")
        registry = parse_yaml_simple(content)
    except Exception as e:
        print(f"ERROR: Failed to parse registry: {e}", file=sys.stderr)
        sys.exit(2)

    # Generate doc
    doc_content = generate_doc(registry)

    if args.check:
        # Check mode: compare with existing
        if not OUTPUT_PATH.exists():
            print(f"FAIL: Generated doc does not exist: {OUTPUT_PATH}", file=sys.stderr)
            print("Run: make gen-capabilities-doc", file=sys.stderr)
            sys.exit(1)

        existing = OUTPUT_PATH.read_text(encoding="utf-8")

        # Strip timestamps for comparison (last line varies)
        def strip_timestamp(s: str) -> str:
            lines = s.strip().split("\n")
            # Remove last line if it's the timestamp
            if lines and lines[-1].startswith("*Generated:"):
                lines = lines[:-1]
            return "\n".join(lines)

        if strip_timestamp(existing) != strip_timestamp(doc_content):
            print(f"FAIL: Generated doc is out of date: {OUTPUT_PATH}", file=sys.stderr)
            print("Run: make gen-capabilities-doc", file=sys.stderr)
            sys.exit(1)

        print(f"OK: {OUTPUT_PATH} is up to date")
        sys.exit(0)

    # Write mode
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(doc_content, encoding="utf-8")
    print(f"Generated: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
