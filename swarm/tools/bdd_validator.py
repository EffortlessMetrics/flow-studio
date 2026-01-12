#!/usr/bin/env python3
"""
BDD Feature File Validator

Validates Gherkin .feature files for correct structure.
"""

import sys
from pathlib import Path
from typing import List, Tuple


class BDDValidator:
    def __init__(self, repo_root: Path):
        self.repo_root = repo_root

    def validate(self) -> Tuple[bool, List[str]]:
        """
        Validate BDD feature files.

        Returns:
            (is_valid, error_messages)
        """
        errors = []
        features_dir = self.repo_root / "features"

        if not features_dir.exists():
            return True, []  # No features, OK

        feature_files = list(features_dir.glob("**/*.feature"))
        if not feature_files:
            return True, []  # No feature files, OK

        for feature_file in feature_files:
            try:
                with open(feature_file) as f:
                    lines = f.readlines()

                    # Basic syntax checks
                    if not any("Feature:" in line for line in lines):
                        errors.append(f"{feature_file.name}: No 'Feature:' found")
                        continue

                    # Count scenarios
                    scenario_count = sum(1 for line in lines if "Scenario:" in line)
                    if scenario_count == 0:
                        errors.append(f"{feature_file.name}: No 'Scenario:' found")
                        continue

                    # Check each scenario has steps
                    in_scenario = False
                    scenario_name = None
                    scenario_steps = 0

                    for line in lines:
                        if "Scenario:" in line:
                            if in_scenario and scenario_steps == 0:
                                errors.append(
                                    f"{feature_file.name}: Scenario '{scenario_name}' has no steps"
                                )
                            in_scenario = True
                            scenario_name = line.split(":", 1)[1].strip()
                            scenario_steps = 0
                        elif in_scenario and any(
                            kw in line
                            for kw in ["Given ", "When ", "Then ", "And ", "But "]
                        ):
                            scenario_steps += 1

                    # Check the last scenario
                    if in_scenario and scenario_steps == 0:
                        errors.append(
                            f"{feature_file.name}: Scenario '{scenario_name}' has no steps"
                        )

            except Exception as e:
                errors.append(f"{feature_file.name}: {e}")

        return len(errors) == 0, errors


def main():
    import argparse

    parser = argparse.ArgumentParser(
        prog="bdd_validator",
        description=(
            "BDD Feature File Validator\n\n"
            "Validates Gherkin .feature files in features/ directory for:\n"
            "  - Correct Feature: declaration\n"
            "  - At least one Scenario:\n"
            "  - Scenarios have steps (Given/When/Then/And/But)"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--path",
        type=str,
        default=None,
        help="Path to repo root (default: current directory)",
    )
    args = parser.parse_args()

    repo_root = Path(args.path) if args.path else Path.cwd()
    validator = BDDValidator(repo_root)
    is_valid, errors = validator.validate()

    if not is_valid:
        for error in errors:
            print(f"[FAIL] {error}", file=sys.stderr)
        sys.exit(1)

    print("[OK] BDD validation passed", file=sys.stdout)
    sys.exit(0)


if __name__ == "__main__":
    main()
