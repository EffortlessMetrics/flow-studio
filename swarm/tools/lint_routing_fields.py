#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
lint_routing_fields.py - Detect legacy routing patterns and validate V3 routing vocabulary

=== LEGACY PATTERNS (VIOLATIONS) ===
This lint prevents reintroduction of deprecated routing fields:
- route_to_flow: 1|2|3|4|5|6|7|null (enum-based flow routing)
- route_to_agent: <agent-name> (direct agent specification)

=== V3 ROUTING VOCABULARY ===
The V3 architecture uses graph-native routing with the following vocabulary:

ROUTING DECISIONS (used in "decision" or "routing" fields):
- CONTINUE: Proceed on golden path (default; no intervention needed)
- DETOUR: Inject sidequest chain (e.g., lint fix, dep update)
- INJECT_FLOW: Insert entire flow (e.g., Flow 3 calling Flow 8 rebase)
- INJECT_NODES: Insert ad-hoc nodes (novel requirements not covered by flows)
- EXTEND_GRAPH: Propose graph patch (Wisdom suggests SOP evolution)

RECOMMENDED ACTIONS (used in "recommended_action" field):
Action vocabulary:
- PROCEED: Work is complete; continue to next step/flow
- RERUN: Retry current step/flow with same inputs
- BOUNCE: Route to different step/flow for remediation
- FIX_ENV: Environment issue; human intervention needed

Agents can also use routing decisions directly as recommended_action:
- CONTINUE, DETOUR, INJECT_FLOW, INJECT_NODES, EXTEND_GRAPH

ROUTING FIELDS:
- "decision": Routing decision enum (CONTINUE|DETOUR|INJECT_FLOW|INJECT_NODES|EXTEND_GRAPH)
- "routing": Same as decision, used in some contexts
- "target": Target flow/node for non-CONTINUE decisions
- "inject_flow": Target flow name when routing is INJECT_FLOW
- "recommended_action": Agent's recommendation (PROCEED|RERUN|BOUNCE|FIX_ENV)

ARCHITECTURE:
- Navigator selects from SidequestCatalog based on recommended_action + handoff summary
- MacroNavigator handles cross-flow routing via constraint DSL
- Agents describe issues and recommend actions; they don't specify destinations directly

See docs/ROUTING_PROTOCOL.md for the full V3 routing contract.

Usage:
    python swarm/tools/lint_routing_fields.py [--strict] [--check-new]

Exit codes:
    0 - No violations found
    1 - Violations found (or --strict and warnings found)
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from dataclasses import dataclass
from typing import Callable, List, Match, Tuple

# =============================================================================
# LEGACY PATTERNS - These indicate deprecated routing vocabulary (violations)
# =============================================================================
LEGACY_VIOLATION_PATTERNS = [
    # Enum-style route_to_flow with numbers
    (r'route_to_flow:\s*[1-7]', 'route_to_flow with numeric value (use routing: INJECT_FLOW + target instead)'),
    (r'route_to_flow:\s*\d+', 'route_to_flow with numeric value (use routing: INJECT_FLOW + target instead)'),
    # Pattern in schema definitions
    (r'route_to_flow:\s*1\|2\|3\|4\|5\|6\|7', 'route_to_flow enum schema (deprecated; use V3 routing decisions)'),
    # route_to_agent with specific agent name (not null)
    (r'route_to_agent:\s*[a-z]+-[a-z]+', 'route_to_agent with specific agent (use routing: DETOUR + target instead)'),
    # Backtick-quoted versions (in docs)
    (r'`route_to_flow:\s*\d+`', 'route_to_flow example with number (update docs to V3 routing)'),
    (r'`route_to_agent:\s*[a-z]+-', 'route_to_agent example with agent (update docs to V3 routing)'),
]

# Legacy patterns that are warnings (acceptable in transition docs but should be removed)
LEGACY_WARNING_PATTERNS = [
    # Generic mentions that might be documentation of deprecation
    (r'"route_to_flow":\s*null', 'route_to_flow null in JSON (remove field entirely)'),
    (r'"route_to_agent":\s*null', 'route_to_agent null in JSON (remove field entirely)'),
    # Bare mentions of the old field names (might be intentional deprecation docs)
    (r'route_to_flow', 'mention of deprecated route_to_flow (verify this is deprecation documentation)'),
    (r'route_to_agent', 'mention of deprecated route_to_agent (verify this is deprecation documentation)'),
]

# =============================================================================
# V3 ROUTING PATTERNS - Valid vocabulary for graph-native routing
# =============================================================================

# Valid routing decision values
VALID_ROUTING_DECISIONS = {'CONTINUE', 'DETOUR', 'INJECT_FLOW', 'INJECT_NODES', 'EXTEND_GRAPH'}

# Valid recommended_action values
# NOTE: recommended_action can use either:
#   - Action vocabulary: PROCEED, RERUN, BOUNCE, FIX_ENV
#   - Routing vocabulary: CONTINUE, DETOUR, INJECT_FLOW, INJECT_NODES, EXTEND_GRAPH
# This flexibility allows agents to recommend routing decisions directly
VALID_RECOMMENDED_ACTIONS = {
    # Action vocabulary
    'PROCEED', 'RERUN', 'BOUNCE', 'FIX_ENV',
    # Routing vocabulary (agents can recommend routing decisions)
    'CONTINUE', 'DETOUR', 'INJECT_FLOW', 'INJECT_NODES', 'EXTEND_GRAPH',
}

# Patterns to validate new routing vocabulary is well-formed
# These patterns are intentionally specific to avoid false positives
NEW_ROUTING_VALIDATION_PATTERNS = [
    # decision field with invalid value (JSON format, typically in routing decision logs)
    # Only matches when decision appears to be a routing decision (has routing-like context)
    (
        r'"decision":\s*"([^"]+)"(?=.*"(target|justification|offroad|source_node)")',
        'decision_field',
        lambda m: m.group(1) not in VALID_ROUTING_DECISIONS,
        'invalid decision value (must be CONTINUE|DETOUR|INJECT_FLOW|INJECT_NODES|EXTEND_GRAPH)'
    ),
    # routing field with explicit routing decision value (YAML style in prompts/specs)
    # Must be followed by a recognized routing decision value, not just any word
    # Pattern: `routing: VALUE` where VALUE is ALL_CAPS
    (
        r'^\s*[-*]?\s*routing:\s*([A-Z][A-Z_]+)\s*(?:,|$|\()',
        'routing_field_yaml',
        lambda m: m.group(1) not in VALID_ROUTING_DECISIONS and m.group(1) not in {'MERGE', 'SKIP', 'NULL'},
        'invalid routing value (must be CONTINUE|DETOUR|INJECT_FLOW|INJECT_NODES|EXTEND_GRAPH)'
    ),
    # routing field in JSON format
    (
        r'"routing":\s*"([A-Z][A-Z_]+)"',
        'routing_field_json',
        lambda m: m.group(1) not in VALID_ROUTING_DECISIONS,
        'invalid routing value (must be CONTINUE|DETOUR|INJECT_FLOW|INJECT_NODES|EXTEND_GRAPH)'
    ),
    # recommended_action with invalid value (both YAML and JSON contexts)
    (
        r'recommended_action:\s*(PROCEED|RERUN|BOUNCE|FIX_ENV|[A-Z][A-Z_]+)',
        'recommended_action_field',
        lambda m: m.group(1) not in VALID_RECOMMENDED_ACTIONS,
        'invalid recommended_action value (must be PROCEED|RERUN|BOUNCE|FIX_ENV)'
    ),
    # recommended_action in JSON format
    (
        r'"recommended_action":\s*"([A-Z][A-Z_]+)"',
        'recommended_action_json',
        lambda m: m.group(1) not in VALID_RECOMMENDED_ACTIONS,
        'invalid recommended_action value (must be PROCEED|RERUN|BOUNCE|FIX_ENV)'
    ),
]

# Patterns that indicate correct NEW routing usage (for info/stats)
NEW_ROUTING_VALID_PATTERNS = [
    (r'"decision":\s*"(CONTINUE|DETOUR|INJECT_FLOW|INJECT_NODES|EXTEND_GRAPH)"', 'valid decision field'),
    (r'routing:\s*(CONTINUE|DETOUR|INJECT_FLOW|INJECT_NODES|EXTEND_GRAPH)\b', 'valid routing field'),
    (r'recommended_action:\s*(PROCEED|RERUN|BOUNCE|FIX_ENV)\b', 'valid recommended_action field'),
    (r'"target":\s*"[a-z]+-?[a-z]*"', 'target field for routing'),
    (r'inject_flow:\s*[a-z]+', 'inject_flow target'),
]

# Combine legacy patterns for backward compatibility with existing code
VIOLATION_PATTERNS = LEGACY_VIOLATION_PATTERNS
WARNING_PATTERNS = LEGACY_WARNING_PATTERNS

# Files/directories to skip
SKIP_PATTERNS = [
    '**/node_modules/**',
    '**/.git/**',
    '**/dist/**',
    '**/__pycache__/**',
    '**/lint_routing_fields.py',  # Don't lint ourselves
    '**/swarm/runs/**',  # Run artifacts use different state machine vocabulary
    '**/run_state.json',  # Stepwise state machine uses advance/terminate/error/loop
]

# File extensions to check
CHECK_EXTENSIONS = {'.md', '.yaml', '.yml', '.json', '.py', '.ts', '.tsx'}


@dataclass
class Violation:
    file: Path
    line_num: int
    line: str
    pattern_desc: str
    is_warning: bool = False
    is_new_pattern_issue: bool = False  # True if this is a malformed V3 pattern

    def safe_line(self) -> str:
        """Return line with non-ASCII chars replaced for console output."""
        return self.line.encode('ascii', 'replace').decode('ascii')


@dataclass
class RoutingUsage:
    """Track usage of new routing patterns for statistics."""
    file: Path
    line_num: int
    pattern_type: str
    value: str


def should_skip_file(file_path: Path) -> bool:
    """Check if file should be skipped based on skip patterns."""
    path_str = str(file_path)
    for pattern in SKIP_PATTERNS:
        if pattern.replace('**/', '').replace('/**', '') in path_str:
            return True
    return False


def check_file(file_path: Path, check_new: bool = False) -> Tuple[List[Violation], List[RoutingUsage]]:
    """Check a single file for routing field violations and new pattern usage.

    Args:
        file_path: Path to the file to check
        check_new: If True, also validate V3 routing patterns are well-formed

    Returns:
        Tuple of (violations, routing_usages)
    """
    if file_path.suffix not in CHECK_EXTENSIONS:
        return [], []

    if should_skip_file(file_path):
        return [], []

    violations = []
    usages = []

    try:
        content = file_path.read_text(encoding='utf-8')
    except (UnicodeDecodeError, PermissionError):
        return [], []

    lines = content.split('\n')

    for line_num, line in enumerate(lines, start=1):
        # Check legacy violation patterns
        for pattern, desc in LEGACY_VIOLATION_PATTERNS:
            if re.search(pattern, line, re.IGNORECASE):
                violations.append(Violation(
                    file=file_path,
                    line_num=line_num,
                    line=line.strip()[:100],  # Truncate long lines
                    pattern_desc=desc,
                    is_warning=False,
                    is_new_pattern_issue=False,
                ))

        # Check legacy warning patterns (only if not already matched as violation)
        # Skip warnings if the line already has a violation to avoid duplicates
        line_has_violation = any(v.line_num == line_num for v in violations)
        if not line_has_violation:
            for pattern, desc in LEGACY_WARNING_PATTERNS:
                if re.search(pattern, line, re.IGNORECASE):
                    violations.append(Violation(
                        file=file_path,
                        line_num=line_num,
                        line=line.strip()[:100],
                        pattern_desc=desc,
                        is_warning=True,
                        is_new_pattern_issue=False,
                    ))

        # Check new routing patterns for validity (if enabled)
        if check_new:
            for pattern, name, is_invalid, desc in NEW_ROUTING_VALIDATION_PATTERNS:
                match = re.search(pattern, line)
                if match and is_invalid(match):
                    violations.append(Violation(
                        file=file_path,
                        line_num=line_num,
                        line=line.strip()[:100],
                        pattern_desc=desc,
                        is_warning=False,
                        is_new_pattern_issue=True,
                    ))

        # Track valid new routing pattern usage (for stats)
        for pattern, pattern_type in NEW_ROUTING_VALID_PATTERNS:
            match = re.search(pattern, line)
            if match:
                usages.append(RoutingUsage(
                    file=file_path,
                    line_num=line_num,
                    pattern_type=pattern_type,
                    value=match.group(1) if match.lastindex else match.group(0),
                ))

    return violations, usages


def find_files(root: Path) -> List[Path]:
    """Find all files to check."""
    files = []
    for ext in CHECK_EXTENSIONS:
        files.extend(root.rglob(f'*{ext}'))
    return files


def main():
    parser = argparse.ArgumentParser(
        description='Lint for deprecated routing patterns and validate V3 routing vocabulary',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
V3 Routing Vocabulary:

  ROUTING DECISIONS (decision/routing fields):
    CONTINUE, DETOUR, INJECT_FLOW, INJECT_NODES, EXTEND_GRAPH

  RECOMMENDED ACTIONS (recommended_action field):
    Action vocabulary: PROCEED, RERUN, BOUNCE, FIX_ENV
    Routing vocabulary: CONTINUE, DETOUR, INJECT_FLOW, INJECT_NODES, EXTEND_GRAPH

See docs/ROUTING_PROTOCOL.md for the full routing contract.
        """
    )
    parser.add_argument(
        '--strict',
        action='store_true',
        help='Treat warnings as errors',
    )
    parser.add_argument(
        '--check-new',
        action='store_true',
        help='Also validate that V3 routing patterns are well-formed',
    )
    parser.add_argument(
        '--show-usage',
        action='store_true',
        help='Show statistics about V3 routing pattern usage',
    )
    parser.add_argument(
        '--root',
        type=Path,
        default=Path.cwd(),
        help='Root directory to scan',
    )
    args = parser.parse_args()

    # Find repo root (look for CLAUDE.md or .git)
    root = args.root
    if not (root / 'CLAUDE.md').exists() and not (root / '.git').exists():
        print(f"Warning: {root} doesn't look like repo root", file=sys.stderr)

    # Scan specific directories
    scan_dirs = ['swarm', 'docs', '.claude']
    all_violations = []
    all_usages = []

    for scan_dir in scan_dirs:
        dir_path = root / scan_dir
        if dir_path.exists():
            files = find_files(dir_path)
            for file in files:
                violations, usages = check_file(file, check_new=args.check_new)
                all_violations.extend(violations)
                all_usages.extend(usages)

    # Categorize violations
    legacy_errors = [v for v in all_violations if not v.is_warning and not v.is_new_pattern_issue]
    new_pattern_errors = [v for v in all_violations if v.is_new_pattern_issue]
    warnings = [v for v in all_violations if v.is_warning]

    # Print legacy errors
    if legacy_errors:
        print(f"\n{'='*60}")
        print("ERRORS: Legacy routing field patterns found")
        print("These deprecated patterns must be removed before merge.")
        print("Use V3 routing vocabulary instead (see --help for reference).")
        print(f"{'='*60}\n")

        for v in legacy_errors:
            rel_path = v.file.relative_to(root)
            print(f"  {rel_path}:{v.line_num}")
            print(f"    Pattern: {v.pattern_desc}")
            print(f"    Line: {v.safe_line()}")
            print()

    # Print new pattern errors (malformed V3 patterns)
    if new_pattern_errors:
        print(f"\n{'='*60}")
        print("ERRORS: Malformed V3 routing patterns found")
        print("These patterns use V3 vocabulary but with invalid values.")
        print(f"{'='*60}\n")

        for v in new_pattern_errors:
            rel_path = v.file.relative_to(root)
            print(f"  {rel_path}:{v.line_num}")
            print(f"    Issue: {v.pattern_desc}")
            print(f"    Line: {v.safe_line()}")
            print()

    # Print warnings
    if warnings:
        print(f"\n{'-'*60}")
        print("WARNINGS: Transitional/legacy patterns found")
        print("Consider removing these fields entirely.")
        print(f"{'-'*60}\n")

        for v in warnings:
            rel_path = v.file.relative_to(root)
            print(f"  {rel_path}:{v.line_num}")
            print(f"    Pattern: {v.pattern_desc}")
            print()

    # Print usage statistics if requested
    if args.show_usage and all_usages:
        print(f"\n{'='*60}")
        print("V3 ROUTING PATTERN USAGE")
        print(f"{'='*60}\n")

        # Group by pattern type
        usage_by_type: dict = {}
        for usage in all_usages:
            if usage.pattern_type not in usage_by_type:
                usage_by_type[usage.pattern_type] = []
            usage_by_type[usage.pattern_type].append(usage)

        for pattern_type, usages in sorted(usage_by_type.items()):
            print(f"  {pattern_type}: {len(usages)} occurrences")
            # Count values
            value_counts: dict = {}
            for u in usages:
                value_counts[u.value] = value_counts.get(u.value, 0) + 1
            for value, count in sorted(value_counts.items(), key=lambda x: -x[1]):
                print(f"    - {value}: {count}")
        print()

    # Summary
    total_errors = len(legacy_errors) + len(new_pattern_errors)
    print(f"\nSummary: {len(legacy_errors)} legacy errors, {len(new_pattern_errors)} malformed V3 errors, {len(warnings)} warnings")

    if all_usages:
        print(f"V3 routing patterns found: {len(all_usages)} valid usages")

    # Exit code
    if total_errors > 0:
        if legacy_errors and new_pattern_errors:
            print("\nFAILED: Remove legacy patterns and fix malformed V3 patterns")
        elif legacy_errors:
            print("\nFAILED: Remove legacy routing patterns")
        else:
            print("\nFAILED: Fix malformed V3 routing patterns")
        return 1
    elif args.strict and warnings:
        print("\nFAILED (strict mode): Remove transitional patterns")
        return 1
    else:
        print("\nPASSED")
        return 0


if __name__ == '__main__':
    sys.exit(main())
