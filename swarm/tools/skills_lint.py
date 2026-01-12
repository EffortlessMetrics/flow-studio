"""
Skills Linting Validator

Validates all .claude/skills/*/SKILL.md files for correct structure and metadata.
"""

import sys
from pathlib import Path
from typing import List, Tuple

import yaml


class SkillsValidator:
    def __init__(self, repo_root: Path):
        self.repo_root = repo_root
        self.errors: List[str] = []

    def validate(self) -> Tuple[bool, List[str]]:
        """
        Validate all skills.

        Returns:
            (is_valid, error_messages)
        """
        errors = []
        skills_dir = self.repo_root / ".claude" / "skills"

        if not skills_dir.exists():
            return True, []  # No skills, OK

        # Find all SKILL.md files
        for skill_file in skills_dir.glob("*/SKILL.md"):
            skill_name = skill_file.parent.name

            # Parse YAML frontmatter
            try:
                with open(skill_file) as f:
                    content = f.read()

                    # Extract frontmatter between --- markers
                    if not content.startswith("---"):
                        errors.append(f"{skill_name}: Missing YAML frontmatter (must start with ---)")
                        continue

                    end_marker = content.find("---", 3)
                    if end_marker == -1:
                        errors.append(f"{skill_name}: Unterminated YAML frontmatter (missing closing ---)")
                        continue

                    frontmatter_str = content[3:end_marker]
                    frontmatter = yaml.safe_load(frontmatter_str)

                    if frontmatter is None:
                        errors.append(f"{skill_name}: Empty YAML frontmatter")
                        continue

                    # Validate required fields
                    if not frontmatter.get("name"):
                        errors.append(f"{skill_name}: Missing required field 'name'")

                    if not frontmatter.get("description"):
                        errors.append(f"{skill_name}: Missing required field 'description'")

            except yaml.YAMLError as e:
                errors.append(f"{skill_name}: YAML parse error: {e}")
            except Exception as e:
                errors.append(f"{skill_name}: {e}")

        return len(errors) == 0, errors


def main():
    import argparse

    parser = argparse.ArgumentParser(
        prog="skills_lint",
        description=(
            "Skills Linting Validator\n\n"
            "Validates all .claude/skills/*/SKILL.md files for correct structure\n"
            "and required metadata (name, description fields in YAML frontmatter)."
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
    validator = SkillsValidator(repo_root)
    is_valid, errors = validator.validate()

    if not is_valid:
        for error in errors:
            print(f"[FAIL] {error}", file=sys.stderr)
        sys.exit(1)

    print("[OK] Skills validation passed", file=sys.stdout)
    sys.exit(0)


if __name__ == "__main__":
    main()
