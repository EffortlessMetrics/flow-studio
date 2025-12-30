#!/usr/bin/env python3
"""
Validate AC matrix consistency across Gherkin, docs, and config.

Checks that:
1. All @AC-* tags in features/selftest.feature are in docs/SELFTEST_AC_MATRIX.md
2. All ACs in matrix are in swarm/tools/selftest_config.py
3. No orphaned ACs in config

Exit code:
  0 = all checks pass
  1 = any check fails
"""

import json
import re
import sys
from pathlib import Path
from typing import Dict, Set

# File paths
GHERKIN_FILE = Path("features/selftest.feature")
MATRIX_FILE = Path("docs/SELFTEST_AC_MATRIX.md")
CONFIG_FILE = Path("swarm/tools/selftest_config.py")


def parse_gherkin_acs() -> Set[str]:
    """
    Extract AC tags from Gherkin feature file.

    Looks for @AC-SELFTEST-* tags in scenario tags.
    Example: @AC-SELFTEST-KERNEL-FAST

    Returns:
        Set of AC identifiers found in Gherkin file.
    """
    if GHERKIN_FILE.is_symlink():
        return set()

    if not GHERKIN_FILE.exists():
        print(f"⚠ Warning: Gherkin file not found: {GHERKIN_FILE}", file=sys.stderr)
        return set()

    content = GHERKIN_FILE.read_text(encoding="utf-8")

    # Match @AC-SELFTEST-* tags
    pattern = r"@(AC-SELFTEST-[A-Z-]+)"
    matches = re.findall(pattern, content)

    return set(matches)


def parse_matrix_acs() -> Set[str]:
    """
    Extract AC identifiers from SELFTEST_AC_MATRIX.md.

    Looks for ### AC-SELFTEST-* markdown headers.
    Example: ### AC-SELFTEST-KERNEL-FAST

    Returns:
        Set of AC identifiers found in Matrix documentation.
    """
    if MATRIX_FILE.is_symlink():
        return set()

    if not MATRIX_FILE.exists():
        print(f"⚠ Warning: Matrix file not found: {MATRIX_FILE}", file=sys.stderr)
        return set()

    content = MATRIX_FILE.read_text(encoding="utf-8")

    # Match ### AC-SELFTEST-* headers
    pattern = r"###\s+(AC-SELFTEST-[A-Z-]+)"
    matches = re.findall(pattern, content)

    return set(matches)


def parse_config_acs() -> Set[str]:
    """
    Extract AC identifiers from selftest_config.py.

    Looks for ac_ids lists in SELFTEST_STEPS.
    Example: ac_ids=["AC-SELFTEST-KERNEL-FAST"]

    Returns:
        Set of AC identifiers found in config file.
    """
    if CONFIG_FILE.is_symlink():
        return set()

    if not CONFIG_FILE.exists():
        print(f"⚠ Warning: Config file not found: {CONFIG_FILE}", file=sys.stderr)
        return set()

    content = CONFIG_FILE.read_text(encoding="utf-8")

    # Match AC-SELFTEST-* identifiers in ac_ids lists
    # Handles both single-line and multi-line list formats
    pattern = r'"(AC-SELFTEST-[A-Z-]+)"'
    matches = re.findall(pattern, content)

    return set(matches)


def check_freshness(verbose: bool = False) -> Dict[str, any]:
    """
    Perform AC matrix freshness check.

    Args:
        verbose: If True, include per-AC status details

    Returns:
        Dict with check results, status, and optional verbose details
    """
    gherkin_acs = parse_gherkin_acs()
    matrix_acs = parse_matrix_acs()
    config_acs = parse_config_acs()

    # Check 1: All Gherkin tags exist in Matrix
    missing_in_matrix = gherkin_acs - matrix_acs

    # Check 2: All Matrix ACs exist in Config
    missing_in_config = matrix_acs - config_acs

    # Check 3: All Config ACs exist in Matrix (no orphans)
    orphaned_in_config = config_acs - matrix_acs

    # Determine overall status
    all_pass = not missing_in_matrix and not missing_in_config and not orphaned_in_config

    result = {
        "status": "PASS" if all_pass else "FAIL",
        "total_acs": len(matrix_acs),
        "checks": {
            "gherkin_to_matrix": {
                "pass": len(missing_in_matrix) == 0,
                "missing": sorted(missing_in_matrix),
            },
            "matrix_to_config": {
                "pass": len(missing_in_config) == 0,
                "missing": sorted(missing_in_config),
            },
            "config_to_matrix": {
                "pass": len(orphaned_in_config) == 0,
                "orphaned": sorted(orphaned_in_config),
            },
        },
        "counts": {
            "gherkin": len(gherkin_acs),
            "matrix": len(matrix_acs),
            "config": len(config_acs),
        },
    }

    if verbose:
        # Add per-AC status details
        all_acs = sorted(matrix_acs | gherkin_acs | config_acs)
        ac_details = []
        for ac in all_acs:
            status_parts = []
            if ac in gherkin_acs:
                status_parts.append("GHERKIN")
            if ac in matrix_acs:
                status_parts.append("MATRIX")
            if ac in config_acs:
                status_parts.append("CONFIG")

            # Determine overall status for this AC
            if ac in matrix_acs and ac in config_acs:
                if ac in gherkin_acs:
                    status = "OK"
                else:
                    status = "OK_NO_GHERKIN"  # Documented but not in feature file (may be intentional)
            elif ac in gherkin_acs and ac not in matrix_acs:
                status = "MISSING_IN_MATRIX"
            elif ac in matrix_acs and ac not in config_acs:
                status = "MISSING_IN_CONFIG"
            elif ac in config_acs and ac not in matrix_acs:
                status = "ORPHANED_IN_CONFIG"
            else:
                status = "UNKNOWN"

            ac_details.append({
                "id": ac,
                "status": status,
                "sources": status_parts,
            })

        result["acs"] = ac_details

    return result


def print_plain_text_summary(result: Dict[str, any], verbose: bool = False):
    """Print human-readable summary."""
    if result["status"] == "PASS":
        print("[PASS] AC Matrix Freshness Check")
        print(f"  {result['total_acs']} ACs OK (all layers aligned)")
        print(f"  Gherkin: {result['counts']['gherkin']}, Matrix: {result['counts']['matrix']}, Config: {result['counts']['config']}")
    else:
        print("[FAIL] AC Matrix Freshness Check FAILED")
        print()

        # Report Gherkin -> Matrix issues
        gherkin_check = result["checks"]["gherkin_to_matrix"]
        if not gherkin_check["pass"]:
            print(f"  [FAIL] Gherkin -> Matrix: {len(gherkin_check['missing'])} missing")
            for ac in gherkin_check["missing"]:
                print(f"    - {ac}")
            print(f"  Fix: Add these ACs as '### <AC-ID>' headers in {MATRIX_FILE}")
            print()

        # Report Matrix -> Config issues
        matrix_check = result["checks"]["matrix_to_config"]
        if not matrix_check["pass"]:
            print(f"  [FAIL] Matrix -> Config: {len(matrix_check['missing'])} missing")
            for ac in matrix_check["missing"]:
                print(f"    - {ac}")
            print(f"  Fix: Add these ACs to appropriate step 'ac_ids' lists in {CONFIG_FILE}")
            print()

        # Report Config -> Matrix issues (orphans)
        config_check = result["checks"]["config_to_matrix"]
        if not config_check["pass"]:
            print(f"  [FAIL] Config -> Matrix: {len(config_check['orphaned'])} orphaned")
            for ac in config_check["orphaned"]:
                print(f"    - {ac}")
            print(f"  Fix: Add documentation for these ACs in {MATRIX_FILE} or remove from {CONFIG_FILE}")
            print()

    if verbose and "acs" in result:
        print()
        print("Detailed AC Status:")
        print()
        for ac_info in result["acs"]:
            status_symbol = "[PASS]" if ac_info["status"] in ["OK", "OK_NO_GHERKIN"] else "[FAIL]"
            sources = ", ".join(ac_info["sources"])
            print(f"  {status_symbol} {ac_info['id']:<30} [{ac_info['status']:<20}] ({sources})")


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Validate AC matrix consistency across Gherkin, docs, and config"
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON (for machine parsing)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Include per-AC status details",
    )

    args = parser.parse_args()

    # Perform the check
    result = check_freshness(verbose=args.verbose)

    # Output results
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print_plain_text_summary(result, verbose=args.verbose)

    # Exit with appropriate code
    sys.exit(0 if result["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
