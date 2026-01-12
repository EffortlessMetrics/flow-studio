#!/usr/bin/env python3
"""
Doc Invariants Checker - Catch outdated count references before they hit main.

This script scans key documentation files for obviously wrong patterns
like "10-step selftest" or "42 agents" that indicate doc drift.

Usage:
    python swarm/tools/doc_invariants_check.py          # Human-readable
    python swarm/tools/doc_invariants_check.py --json   # JSON output
    python swarm/tools/doc_invariants_check.py --fix    # Show suggested fixes

Exit codes:
    0 = All checks passed
    1 = Found outdated references
"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

# Import from meta.py - the single source of truth
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from meta import compute_meta

# Compute authoritative counts from actual configuration
_META = compute_meta()
SELFTEST_STEPS = _META["selftest"]["total"]
DOMAIN_AGENTS = _META["agents"]["domain"]
TOTAL_AGENTS = _META["agents"]["total"]
SKILLS_COUNT = _META["skills"]["count"]

# Files to scan (relative to repo root)
SCAN_FILES = [
    "README.md",
    "CLAUDE.md",
    "ARCHITECTURE.md",
    "REPO_MAP.md",
    "RUNBOOK.md",
    "DEMO_RUN.md",
    "CONTRIBUTING.md",
    "swarm/AGENTS.md",
    "swarm/SELFTEST_SYSTEM.md",
    "docs/WHITEPAPER.md",
    "docs/AGENT_OPS.md",
    "docs/FLOW_STUDIO.md",
    "docs/GETTING_STARTED.md",
    "docs/TOUR_20_MIN.md",
    "docs/GOLDEN_RUNS.md",
    "docs/CHANGELOG.md",
    "docs/RELEASE_NOTES_2_3_0.md",
    "specs/spec_ledger.yaml",
    "FLOW_STUDIO_GOVERNANCE_README.md",
    "FLOW_STUDIO_GOVERNANCE_INDEX.md",
]

# Patterns that indicate outdated documentation
# Format: (pattern, description, suggestion)
OUTDATED_PATTERNS: List[Tuple[re.Pattern, str, str]] = [
    # Selftest step counts (excluding Flow 7 which is intentionally 10 steps)
    (
        re.compile(r'\b10[-\s]?step\s+selftest\b', re.IGNORECASE),
        "Outdated selftest step count (10 instead of 16)",
        "Replace with '16-step selftest'"
    ),
    (
        re.compile(r'\ball\s+10\s+steps?\b(?!.*(?:flow\s*7|stepwise[-\s]?demo))', re.IGNORECASE),
        "Outdated 'all 10 steps' reference",
        "Replace with 'all 16 steps'"
    ),
    (
        re.compile(r'\b10\s+selftest\s+steps?\b', re.IGNORECASE),
        "Outdated '10 selftest steps' reference",
        "Replace with '16 selftest steps'"
    ),
    # Agent counts
    (
        re.compile(r'\b42\s+(?:domain\s+)?agents?\b', re.IGNORECASE),
        "Outdated agent count (42 instead of 45 domain)",
        "Replace with '45 domain agents' or '48 total agents'"
    ),
    (
        re.compile(r'\b44\s+agents?\b', re.IGNORECASE),
        "Outdated agent count (44 instead of 48 total)",
        "Replace with '48 agents'"
    ),
    (
        re.compile(r'\b45\s*\(\s*3\s+built-in\s*\+\s*42\s+domain\s*\)', re.IGNORECASE),
        "Outdated total calculation (3+42=45 instead of 3+45=48)",
        "Replace with '48 (3 built-in + 45 domain)'"
    ),
]

# Patterns that are OK (false positive exclusions)
FALSE_POSITIVE_PATTERNS = [
    re.compile(r'flow\s*7.*10[-\s]?step', re.IGNORECASE),  # Flow 7 is intentionally 10 steps
    re.compile(r'stepwise[-\s]?demo.*10', re.IGNORECASE),  # stepwise-demo flow
    re.compile(r'line\s+\d+', re.IGNORECASE),  # Line number references
]


def get_repo_root() -> Path:
    """Find repository root by looking for .git directory or pyproject.toml."""
    current = Path(__file__).resolve().parent
    while current != current.parent:
        # Look for .git or pyproject.toml as definitive repo root markers
        if (current / ".git").exists() or (current / "pyproject.toml").exists():
            return current
        current = current.parent
    # Fallback to current working directory
    return Path.cwd()


def is_false_positive(line: str) -> bool:
    """Check if a line contains known false positive patterns."""
    return any(p.search(line) for p in FALSE_POSITIVE_PATTERNS)


def scan_file(file_path: Path) -> List[Dict[str, Any]]:
    """Scan a file for outdated patterns."""
    issues = []

    if not file_path.exists():
        return issues

    try:
        content = file_path.read_text(encoding='utf-8')
        lines = content.splitlines()
    except Exception as e:
        return [{"error": str(e), "file": str(file_path)}]

    for line_num, line in enumerate(lines, start=1):
        # Skip false positives
        if is_false_positive(line):
            continue

        for pattern, description, suggestion in OUTDATED_PATTERNS:
            match = pattern.search(line)
            if match:
                issues.append({
                    "file": str(file_path),
                    "line": line_num,
                    "column": match.start() + 1,
                    "match": match.group(),
                    "context": line.strip()[:100],
                    "description": description,
                    "suggestion": suggestion,
                })

    return issues


def scan_all_files(repo_root: Path) -> List[Dict[str, Any]]:
    """Scan all configured files for issues."""
    all_issues = []

    for rel_path in SCAN_FILES:
        file_path = repo_root / rel_path
        issues = scan_file(file_path)
        all_issues.extend(issues)

    return all_issues


def print_human_readable(issues: List[Dict[str, Any]], repo_root: Path) -> None:
    """Print issues in human-readable format."""
    if not issues:
        print("[OK] Doc Invariants Check")
        print(f"  Scanned {len(SCAN_FILES)} files, no outdated references found")
        print()
        print("  Authoritative counts (computed from config):")
        print(f"    - Selftest: {SELFTEST_STEPS} steps")
        print(f"    - Agents: {TOTAL_AGENTS} total ({DOMAIN_AGENTS} domain + {_META['agents']['built_in']} built-in)")
        print(f"    - Skills: {SKILLS_COUNT}")
        return

    print("[FAIL] Doc Invariants Check - FAILED")
    print(f"  Found {len(issues)} outdated reference(s)")
    print()

    # Group by file
    by_file: Dict[str, List[Dict[str, Any]]] = {}
    for issue in issues:
        f = issue.get("file", "unknown")
        if f not in by_file:
            by_file[f] = []
        by_file[f].append(issue)

    for file_path, file_issues in by_file.items():
        # Make path relative for readability
        try:
            rel_path = Path(file_path).relative_to(repo_root)
        except ValueError:
            rel_path = file_path

        print(f"  {rel_path}:")
        for issue in file_issues:
            line = issue.get("line", "?")
            desc = issue.get("description", "Unknown issue")
            match = issue.get("match", "")
            suggestion = issue.get("suggestion", "")
            print(f"    Line {line}: {desc}")
            print(f"      Found: '{match}'")
            print(f"      Fix: {suggestion}")
        print()


def print_json(issues: List[Dict[str, Any]]) -> None:
    """Print issues in JSON format."""
    result = {
        "status": "pass" if not issues else "fail",
        "issues_count": len(issues),
        "authoritative_counts": {
            "selftest_steps": SELFTEST_STEPS,
            "domain_agents": DOMAIN_AGENTS,
            "total_agents": TOTAL_AGENTS,
            "skills": SKILLS_COUNT,
        },
        "scanned_files": len(SCAN_FILES),
        "issues": issues,
    }
    print(json.dumps(result, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check documentation for outdated count references"
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results in JSON format"
    )
    parser.add_argument(
        "--fix",
        action="store_true",
        help="Show detailed fix suggestions"
    )
    args = parser.parse_args()

    repo_root = get_repo_root()
    issues = scan_all_files(repo_root)

    if args.json:
        print_json(issues)
    else:
        print_human_readable(issues, repo_root)

    return 1 if issues else 0


if __name__ == "__main__":
    sys.exit(main())
