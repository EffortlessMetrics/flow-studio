#!/usr/bin/env python3
"""
validate_swarm.py - Enhanced Swarm Alignment Validator

Validates swarm spec/implementation alignment with two layers:

**Layer 1: Claude Code Platform Spec**
- YAML parses correctly
- Fields are of correct types
- Values are sensible (model in [inherit, haiku, sonnet, opus])
- Allows: name, description, model, skills, color

**Layer 2: Flow Studio Design Constraints**
- Required fields: name, description, color, model
- Domain agents must omit 'tools' and 'permissionMode' (prompt-based constraints)
- Agent 'name' must match filename key and AGENTS.md registry
- Agent 'color' must match role_family in AGENTS.md
- Flow specs only reference agents from AGENTS.md or built-ins
- Skills have valid SKILL.md
- Flow specs use RUN_BASE placeholders, not hardcoded paths

## What It Validates

**FR-001: Bijection** — 1:1 mapping between swarm/AGENTS.md entries and .claude/agents/*.md files
  - LEGACY: Skipped if .claude/agents/ directory does not exist (new architecture uses swarm/config/agents/)
  - Every registry entry has a corresponding file (case-sensitive)
  - Every file has a corresponding registry entry
  - Detects missing/extra files

**FR-002: Frontmatter** — YAML frontmatter in agent definitions
  - LEGACY: Skipped if .claude/agents/ directory does not exist (new architecture uses swarm/config/agents/)
  - Required fields: name, description, color, model
  - Name matches filename and registry key
  - Model is valid (inherit, haiku, sonnet, opus)
  - Color is valid and matches role_family
  - Swarm design constraints: no tools/permissionMode (--strict enforces)
  - Skills field is list if present

**FR-003: Flow References** — Agent references in flow specs
  - All agents in swarm/flows/flow-*.md exist in registry or are built-ins
  - Typo detection using Levenshtein distance (edit distance ≤ 2)
  - Suggests up to 3 similar names for unknown references

**FR-004: Skills** — Skill declarations in agent frontmatter
  - Every skill has a .claude/skills/<name>/SKILL.md file
  - Skill frontmatter is valid (name, description)

**FR-005: RUN_BASE Paths** — Artifact path placeholders in flow specs
  - Flow specs use RUN_BASE/<flow>/ placeholders
  - No hardcoded paths like swarm/runs/<run-id>/
  - Detects malformed placeholders ($RUN_BASE, {RUN_BASE})

**FR-006: Agent Prompt Sections** — Required headings in agent prompt body
  - Check for ## Inputs (or ## Input)
  - Check for ## Outputs (or ## Output)
  - Check for ## Behavior
  - Optional, enabled with --check-prompts flag
  - In strict mode: missing sections are errors
  - In default mode: missing sections are warnings

**FR-007: Capability Registry** — Capability claims with evidence
  - specs/capabilities.yaml tracks what the system can do
  - implemented capabilities must have test evidence
  - implemented capabilities must have code evidence
  - @cap:<id> tags in BDD must reference capabilities in registry
  - Prevents "narrative drift" where docs claim unproven capabilities

## CLI Usage

Run full validation:
  uv run swarm/tools/validate_swarm.py

Run with strict mode (enforce swarm design constraints):
  uv run swarm/tools/validate_swarm.py --strict

Run git-aware mode (only check modified files):
  uv run swarm/tools/validate_swarm.py --check-modified

Run with debug output:
  uv run swarm/tools/validate_swarm.py --debug

Show version:
  uv run swarm/tools/validate_swarm.py --version

## CLI Flags

--check-modified    Git-aware incremental mode (only validates modified files)
--check-prompts     Validate agent prompt sections (## Inputs, ## Outputs, ## Behavior)
--strict            Enforce swarm design constraints (tools/permissionMode become errors)
--debug             Show timing and validation steps
--version           Show validator version

## Exit Codes

0   All validation checks passed
1   Validation failed (spec/implementation misalignment detected)
2   Fatal error (missing required files, parse errors)

## Examples

Full validation before commit:
  uv run swarm/tools/validate_swarm.py

Incremental validation (fast, for large repos):
  uv run swarm/tools/validate_swarm.py --check-modified

Strict enforcement of swarm design:
  uv run swarm/tools/validate_swarm.py --strict

Debug mode with timing:
  uv run swarm/tools/validate_swarm.py --debug

## Error Message Format

All errors follow template:
  ✗ TYPE: location problem → Fix: action

Example:
  ✗ BIJECTION: swarm/AGENTS.md:line 42: Agent 'foo-bar' is registered but .claude/agents/foo-bar.md does not exist
    Fix: Create .claude/agents/foo-bar.md with required frontmatter, or remove entry from AGENTS.md

## Performance

- Baseline: < 2 seconds on repos with ~45 agents
- Git-aware mode: >= 50% faster on incremental changes
- Fast-path optimization for common checks (bijection + frontmatter)

## Notes

This validator uses a custom YAML parser (stdlib-only, no external dependencies).
It handles simple frontmatter patterns used in swarm:
  - String values (quoted or unquoted)
  - Lists (inline [...] or multi-line with -)
  - Booleans, nulls, comments

Does NOT handle: YAML anchors, tags, complex nested structures.

For detailed documentation, see:
- /CLAUDE.md — Full reference for CLI usage, error messages, troubleshooting
- docs/VALIDATION_RULES.md — Comprehensive FR-001–FR-005 reference

Functional Requirements: FR-001 through FR-007
Version: 2.1.0
"""

import argparse
import json
import re
import subprocess
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

# Add swarm package to path for library imports
_SWARM_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_SWARM_ROOT) not in sys.path:
    sys.path.insert(0, str(_SWARM_ROOT))

# Lazy import: flow_registry is imported inside functions that need it
# This allows the validator to work in test repos without swarm/config/
from swarm.validator import SimpleYAMLParser, ValidationError, ValidationResult  # noqa: E402

# ============================================================================
# Constants
# ============================================================================

BUILT_IN_AGENTS = ["explore", "plan-subagent", "general-subagent"]
VALID_MODELS = ["inherit", "haiku", "sonnet", "opus"]
VALID_COLORS = ["red", "blue", "green", "yellow", "purple", "orange", "pink", "cyan"]

# Role family → expected color mapping
ROLE_FAMILY_COLOR_MAP = {
    "shaping": "yellow",
    "spec": "purple",
    "design": "purple",
    "implementation": "green",
    "critic": "red",
    "verification": "blue",
    "analytics": "orange",
    "reporter": "pink",
    "infra": "cyan",
}

# Exit codes per contract
EXIT_SUCCESS = 0
EXIT_VALIDATION_FAILED = 1
EXIT_FATAL_ERROR = 2


# ============================================================================
# Utility Functions
# ============================================================================

def safe_get_stripped(value: Any) -> Optional[str]:
    """
    Safely extract and strip a value that might be None.

    Handles YAML null values (including tilde ~) gracefully.

    Args:
        value: Field value (could be None, string, etc.)

    Returns:
        Stripped string if value is a non-empty string, None otherwise
    """
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped if stripped else None


# ============================================================================
# Path Resolution
# ============================================================================

def find_repo_root() -> Path:
    """Find repository root by looking for swarm/AGENTS.md."""
    current = Path.cwd().resolve()

    # Check current directory and parents
    for path in [current] + list(current.parents):
        agents_md = path / "swarm" / "AGENTS.md"
        if agents_md.is_file():
            return path

    # Fallback: assume we're in the repo root
    return current


ROOT = find_repo_root()
AGENTS_MD = ROOT / "swarm" / "AGENTS.md"
FLOW_SPECS_DIR = ROOT / "swarm" / "flows"
FLOWS_CONFIG_DIR = ROOT / "swarm" / "config" / "flows"
AGENTS_DIR = ROOT / ".claude" / "agents"
SKILLS_DIR = ROOT / ".claude" / "skills"


# ============================================================================
# Agent Registry Parsing
# ============================================================================

def parse_agents_registry() -> Dict[str, Dict[str, Any]]:
    """
    Parse swarm/AGENTS.md pipe table and return agent metadata.

    Returns:
        Dict mapping agent key -> metadata dict

    Raises:
        SystemExit: If AGENTS.md not found or unparseable
    """
    if not AGENTS_MD.is_file():
        print(f"ERROR: {AGENTS_MD} not found (required for validation)", file=sys.stderr)
        sys.exit(EXIT_FATAL_ERROR)

    agents: Dict[str, Dict[str, Any]] = {}
    in_table = False
    line_number = 0

    try:
        with AGENTS_MD.open(encoding="utf-8") as f:
            for line_number, line in enumerate(f, start=1):
                line = line.rstrip("\n")

                # Detect table header (new format with role_family and color)
                if line.startswith("| Key") and "Role Family" in line and "Color" in line and "Short Role" in line:
                    in_table = True
                    continue

                # Fallback: old format header (for backward compatibility during migration)
                if line.startswith("| Key") and "Category" in line and "Short Role" in line and "Role Family" not in line:
                    # Old format without color - log warning and continue
                    print(f"WARNING: {AGENTS_MD} uses old format without Role Family/Color columns", file=sys.stderr)
                    in_table = True
                    continue

                # Skip separator row
                if in_table and line.startswith("|---"):
                    continue

                # Parse table row
                if in_table:
                    if not line.strip():
                        continue
                    if not line.startswith("|"):
                        break

                    cols = [c.strip() for c in line.strip("|").split("|")]

                    # New format: Key | Flows | Role Family | Color | Source | Short Role
                    if len(cols) == 6:
                        key, flows, role_family, color, source, role = cols
                        key = key.strip()

                        if not key or key == "Key":
                            continue

                        agents[key] = {
                            "flows": flows.strip(),
                            "role_family": role_family.strip(),
                            "color": color.strip(),
                            "source": source.strip(),
                            "role": role.strip(),
                            "line": line_number
                        }
                    # Old format: Key | Flows | Category | Source | Short Role
                    elif len(cols) == 5:
                        key, flows, category, source, role = cols
                        key = key.strip()

                        if not key or key == "Key":
                            continue

                        agents[key] = {
                            "flows": flows.strip(),
                            "category": category.strip(),
                            "source": source.strip(),
                            "role": role.strip(),
                            "line": line_number
                        }
                    else:
                        continue
    except Exception as e:
        print(f"ERROR: Failed to parse {AGENTS_MD}: {e}", file=sys.stderr)
        sys.exit(EXIT_FATAL_ERROR)

    return agents


# ============================================================================
# Config Coverage Validation (FR-CONF-001)
# ============================================================================

def parse_config_files() -> Dict[str, Dict[str, Any]]:
    """
    Parse all agent config YAML files (raw YAML, no frontmatter).

    Returns:
        Dict mapping agent key → config dict
    """
    config_dir = ROOT / "swarm" / "config" / "agents"
    configs: Dict[str, Dict[str, Any]] = {}

    if not config_dir.is_dir():
        return configs

    for config_file in config_dir.glob("*.yaml"):
        try:
            content = config_file.read_text(encoding="utf-8")
            # Parse raw YAML config (not frontmatter format)
            parsed = _parse_raw_yaml(content)
            key = parsed.get("key", config_file.stem)
            configs[key] = {**parsed, "file_path": str(config_file)}
        except Exception:
            # Skip unparseable configs; they'll be caught elsewhere
            pass

    return configs


def _parse_raw_yaml(content: str) -> Dict[str, Any]:
    """
    Parse raw YAML config file (simple key: value format, no frontmatter).

    Returns:
        Dict of parsed fields
    """
    result: Dict[str, Any] = {}
    for line in content.split("\n"):
        line = line.rstrip()
        if not line or line.startswith("#"):
            continue

        # Match key: value
        if ":" not in line:
            continue

        parts = line.split(":", 1)
        key = parts[0].strip()
        value = parts[1].strip()

        # Remove quotes if present
        if value.startswith('"') and value.endswith('"'):
            value = value[1:-1]
        elif value.startswith("'") and value.endswith("'"):
            value = value[1:-1]

        result[key] = value

    return result


def validate_config_coverage(registry: Dict[str, Dict[str, Any]]) -> ValidationResult:
    """
    Validate that config files align with AGENTS.md registry.

    Checks:
    - Every domain agent in AGENTS.md has a config YAML
    - Every config YAML corresponds to an agent in AGENTS.md
    - Config fields (category, color, source) match registry

    Note: If swarm/config/agents/ directory doesn't exist, this check is skipped.
    This allows the validator to work on repos that don't use the config system.
    """
    result = ValidationResult()

    # Skip config validation if config directory doesn't exist
    config_dir = ROOT / "swarm" / "config" / "agents"
    if not config_dir.is_dir():
        return result

    configs = parse_config_files()

    # Check registry → config
    for key, meta in registry.items():
        # Skip built-in agents
        if key in BUILT_IN_AGENTS:
            continue

        # Skip non-project agents
        if meta.get("source") != "project/user":
            continue

        if key not in configs:
            location = f"swarm/AGENTS.md:line {meta.get('line', '?')}"
            problem = f"Agent '{key}' is registered but swarm/config/agents/{key}.yaml does not exist"
            fix_action = f"Create swarm/config/agents/{key}.yaml with agent metadata, or remove entry from AGENTS.md"

            result.add_error(
                "CONFIG",
                location,
                problem,
                fix_action,
                line_number=meta.get("line"),
                file_path=str(AGENTS_MD)
            )
            continue

        # Verify config fields match registry
        config = configs[key]
        registry_category = meta.get("role_family")
        config_category = config.get("category")

        if config_category != registry_category:
            location = f"swarm/config/agents/{key}.yaml"
            problem = f"config 'category' is '{config_category}' but AGENTS.md role_family is '{registry_category}'"
            fix_action = "Update 'category' in config to match role_family in AGENTS.md"

            result.add_error(
                "CONFIG",
                location,
                problem,
                fix_action,
                file_path=config.get("file_path")
            )

        registry_color = meta.get("color")
        config_color = config.get("color")

        if config_color != registry_color:
            location = f"swarm/config/agents/{key}.yaml"
            problem = f"config 'color' is '{config_color}' but AGENTS.md color is '{registry_color}'"
            fix_action = "Update 'color' in config to match AGENTS.md"

            result.add_error(
                "CONFIG",
                location,
                problem,
                fix_action,
                file_path=config.get("file_path")
            )

    # Check config → registry
    if config_dir.is_dir():
        for config_file in config_dir.glob("*.yaml"):
            key = config_file.stem
            if key not in registry:
                problem = f"config exists for '{key}' but agent is not in swarm/AGENTS.md"
                fix_action = f"Add entry for '{key}' to AGENTS.md or delete swarm/config/agents/{key}.yaml"

                result.add_error(
                    "CONFIG",
                    f"swarm/config/agents/{key}.yaml",
                    problem,
                    fix_action,
                    file_path=str(config_file)
                )

    return result


# ============================================================================
# FR-001: Bijection Validation
# ============================================================================

def validate_bijection(registry: Dict[str, Dict[str, Any]]) -> ValidationResult:
    """
    Validate correspondence between AGENTS.md and .claude/agents/*.md files.

    LEGACY: This check is skipped if .claude/agents/ directory does not exist.
    The new architecture uses swarm/config/agents/ for agent configuration instead.

    TRANSITION MODE: During the architecture transition from .claude/agents/ to
    swarm/config/agents/, we only enforce:
    - Every file in .claude/agents/ must be registered in AGENTS.md (file → registry)

    We intentionally skip the registry → file check because:
    - Most agents now use swarm/config/agents/ as the source of truth
    - Only agents with custom prompts (like Flow 8 reset agents) need .claude/agents/ files
    - Full bijection will be restored when the migration is complete

    Checks:
    - Every file has a corresponding registry entry (enforced)
    - Names are case-sensitive exact matches
    """
    result = ValidationResult()

    # LEGACY: Skip bijection check if .claude/agents/ doesn't exist
    # The new architecture uses swarm/config/agents/ instead
    if not AGENTS_DIR.is_dir():
        return result

    # Collect agent files
    agent_files: Set[str] = set()
    for path in AGENTS_DIR.glob("*.md"):
        if path.is_symlink():
            # Skip symlinks: they could enable information disclosure or create circular references
            continue
        agent_files.add(path.stem)

    # TRANSITION: Skip registry → file check
    # During migration, we don't require all registered agents to have .claude/agents/ files.
    # Most agents now live in swarm/config/agents/ as the source of truth.

    # Check file → registry
    for filename in agent_files:
        if filename not in registry:
            file_path = AGENTS_DIR / f"{filename}.md"

            # Suggest similar names using Levenshtein distance
            registry_keys = list(registry.keys())
            suggestions = suggest_typos(filename, registry_keys)

            problem = f"file exists but agent key '{filename}' is not in swarm/AGENTS.md"
            if suggestions:
                problem += f"; did you mean: {', '.join(suggestions)}?"

            fix_action = f"Add entry for '{filename}' to swarm/AGENTS.md or delete {file_path.relative_to(ROOT)}"
            if suggestions:
                fix_action = f"Update '{filename}' entry to match one of: {', '.join(suggestions)}, or add new entry to swarm/AGENTS.md, or delete {file_path.relative_to(ROOT)}"

            result.add_error(
                "BIJECTION",
                str(file_path.relative_to(ROOT)),
                problem,
                fix_action,
                file_path=str(file_path)
            )

    return result


# ============================================================================
# FR-002: Frontmatter Validation
# ============================================================================

def validate_frontmatter(_registry: Dict[str, Dict[str, Any]], strict_mode: bool = False) -> ValidationResult:
    """
    Validate YAML frontmatter in all agent files.

    LEGACY: This check is skipped if .claude/agents/ directory does not exist.
    The new architecture uses swarm/config/agents/ for agent configuration instead.

    Checks:
    - YAML parses correctly
    - Required fields present (name, description, model)
    - Name matches filename
    - Model is valid
    - Swarm design constraint fields (tools, permissionMode): WARN in default mode, ERROR in strict mode
    - Skills is a list if present

    Args:
        _registry: Agent registry from AGENTS.md (reserved for future registry-based validation)
        strict_mode: If True, treat swarm design constraint violations as errors
    """
    result = ValidationResult()

    # LEGACY: Skip frontmatter check if .claude/agents/ doesn't exist
    # The new architecture uses swarm/config/agents/ instead
    if not AGENTS_DIR.is_dir():
        return result

    for path in sorted(AGENTS_DIR.glob("*.md")):
        if path.is_symlink():
            # Skip symlinks: validation only applies to real files
            continue

        filename_key = path.stem
        rel_path = path.relative_to(ROOT)

        # Parse frontmatter
        try:
            content = path.read_text(encoding="utf-8")
            fm = SimpleYAMLParser.parse(content, path, strict=strict_mode)
        except ValueError as e:
            result.add_error(
                "FRONTMATTER",
                str(rel_path),
                f"YAML parse error: {e}",
                "Check YAML syntax; ensure frontmatter starts and ends with '---'",
                file_path=str(path)
            )
            continue
        except Exception as e:
            result.add_error(
                "FRONTMATTER",
                str(rel_path),
                f"unexpected error: {e}",
                "Check file encoding and YAML syntax",
                file_path=str(path)
            )
            continue

        # Required fields (with null-safety for YAML tilde values)
        name_value = safe_get_stripped(fm.get("name"))
        if not name_value:
            result.add_error(
                "FRONTMATTER",
                str(rel_path),
                "missing required field 'name'",
                f"Add `name: {filename_key}` to frontmatter",
                file_path=str(path)
            )

        description_value = safe_get_stripped(fm.get("description"))
        if not description_value:
            result.add_error(
                "FRONTMATTER",
                str(rel_path),
                "missing required field 'description'",
                "Add `description: <one-line description>` to frontmatter",
                file_path=str(path)
            )

        model_value = safe_get_stripped(fm.get("model"))
        if not model_value:
            result.add_error(
                "FRONTMATTER",
                str(rel_path),
                "missing required field 'model'",
                "Add `model: inherit` to frontmatter",
                file_path=str(path)
            )

        # Name must match filename
        if name_value and name_value != filename_key:
            result.add_error(
                "FRONTMATTER",
                str(rel_path),
                f"frontmatter 'name' field '{name_value}' does not match filename '{filename_key}'",
                f"Change `name: {name_value}` to `name: {filename_key}`, or rename file to {name_value}.md",
                file_path=str(path)
            )

        # Model must be valid
        if model_value and model_value not in VALID_MODELS:
            result.add_error(
                "FRONTMATTER",
                str(rel_path),
                f"invalid model value '{model_value}' (must be one of {VALID_MODELS})",
                f"Change `model: {model_value}` to one of: {', '.join(VALID_MODELS)}",
                file_path=str(path)
            )

        # Swarm design constraint fields (Layer 2 constraint)
        # Layer 1 (Claude Code platform): supports 'tools' and 'permissionMode'
        # Layer 2 (This swarm design): intentionally omits them, uses prompt-based constraints
        # Default mode: WARN (design guideline, not error)
        # Strict mode: ERROR (enforce swarm design)
        if "tools" in fm:
            if strict_mode:
                result.add_error(
                    "FRONTMATTER",
                    str(rel_path),
                    "field 'tools' violates swarm design constraint (use --strict to enforce)",
                    "Remove 'tools:' field; this swarm uses prompt-based constraints, not tool denial",
                    file_path=str(path)
                )
            else:
                result.add_warning(
                    "FRONTMATTER",
                    str(rel_path),
                    "field 'tools' found (swarm design guideline: omit this field)",
                    "Consider removing 'tools:' field; this swarm uses prompt-based constraints",
                    file_path=str(path)
                )

        if "permissionMode" in fm:
            if strict_mode:
                result.add_error(
                    "FRONTMATTER",
                    str(rel_path),
                    "field 'permissionMode' violates swarm design constraint (use --strict to enforce)",
                    "Remove 'permissionMode:' field; this swarm enforces permissions at repo level",
                    file_path=str(path)
                )
            else:
                result.add_warning(
                    "FRONTMATTER",
                    str(rel_path),
                    "field 'permissionMode' found (swarm design guideline: omit this field)",
                    "Consider removing 'permissionMode:' field; this swarm enforces permissions at repo level",
                    file_path=str(path)
                )

        # Skills must be a list
        if "skills" in fm:
            skills = fm["skills"]
            if not isinstance(skills, list):
                result.add_error(
                    "FRONTMATTER",
                    str(rel_path),
                    f"'skills' must be a list (got {type(skills).__name__})",
                    "Change skills to list format: `skills: [skill1, skill2]` or use multi-line list",
                    file_path=str(path)
                )

    return result


# ============================================================================
# FR-002b: Color Validation
# ============================================================================

def validate_colors(registry: Dict[str, Dict[str, Any]]) -> ValidationResult:
    """
    Validate that agent colors match expected colors for their role_family.

    LEGACY: This check is skipped if .claude/agents/ directory does not exist.
    The new architecture uses swarm/config/agents/ for agent configuration instead.

    Checks:
    - Agent frontmatter has 'color' field
    - Color is valid (in VALID_COLORS)
    - Color matches expected color for the agent's role_family in AGENTS.md
    """
    result = ValidationResult()

    # LEGACY: Skip color check if .claude/agents/ doesn't exist
    # The new architecture uses swarm/config/agents/ instead
    if not AGENTS_DIR.is_dir():
        return result

    # Check each agent file
    for path in sorted(AGENTS_DIR.glob("*.md")):
        if path.is_symlink():
            # Skip symlinks: validation only applies to real files
            continue

        filename_key = path.stem
        rel_path = path.relative_to(ROOT)

        # Get expected color from registry
        if filename_key not in registry:
            continue

        agent_meta = registry[filename_key]
        if "role_family" not in agent_meta:
            # Registry hasn't been updated with role_family yet; skip color check
            continue

        role_family = agent_meta.get("role_family", "").strip().lower()
        expected_color = ROLE_FAMILY_COLOR_MAP.get(role_family)

        if not expected_color:
            # Unknown role family
            result.add_warning(
                "COLOR",
                str(rel_path),
                f"unknown role_family '{role_family}' in AGENTS.md (cannot validate color)",
                "Ensure role_family is one of: " + ", ".join(ROLE_FAMILY_COLOR_MAP.keys()),
                file_path=str(path)
            )
            continue

        # Parse frontmatter
        try:
            content = path.read_text(encoding="utf-8")
            fm = SimpleYAMLParser.parse(content, path)
        except Exception:
            # Skip color check if frontmatter parsing failed (already reported)
            continue

        # Check for color field
        if "color" not in fm:
            result.add_error(
                "COLOR",
                str(rel_path),
                f"missing required field 'color' (expected '{expected_color}' for role family '{role_family}')",
                f"Add `color: {expected_color}` to frontmatter",
                file_path=str(path)
            )
            continue

        color_value = safe_get_stripped(fm.get("color"))
        color = color_value.lower() if color_value else ""

        # Validate color value
        if color and color not in VALID_COLORS:
            result.add_error(
                "COLOR",
                str(rel_path),
                f"invalid color value '{color}' (expected one of: {', '.join(VALID_COLORS)})",
                f"Change `color: {color}` to a valid color",
                file_path=str(path)
            )
            continue

        # Check color matches expected color for role family
        if color != expected_color:
            result.add_error(
                "COLOR",
                str(rel_path),
                f"color '{color}' does not match expected color '{expected_color}' for role family '{role_family}'",
                f"Change `color: {color}` to `color: {expected_color}` to match role family in AGENTS.md",
                file_path=str(path)
            )

    return result


# ============================================================================
# FR-003: Flow Spec Reference Validation (with Levenshtein)
# ============================================================================

def levenshtein_distance(s1: str, s2: str) -> int:
    """
    Calculate Levenshtein edit distance between two strings.

    Used for typo detection in agent references.
    """
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)

    if len(s2) == 0:
        return len(s1)

    previous_row: list[int] = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        current_row: list[int] = [i + 1]
        for j, c2 in enumerate(s2):
            # Cost of insertions, deletions, or substitutions
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row

    return previous_row[-1]


def suggest_typos(name: str, candidates: List[str], max_dist: int = 2) -> List[str]:
    """
    Suggest similar agent names using Levenshtein distance.

    Returns up to 3 suggestions with distance <= max_dist, sorted by distance.
    """
    suggestions: List[Tuple[int, str]] = []
    for candidate in candidates:
        dist = levenshtein_distance(name.lower(), candidate.lower())
        if dist <= max_dist:
            suggestions.append((dist, candidate))

    # Sort by distance, then alphabetically
    suggestions.sort(key=lambda x: (x[0], x[1]))

    # Return up to 3 suggestions
    return [s[1] for s in suggestions[:3]]


def parse_flow_spec_agents(flow_path: Path) -> List[Tuple[int, str]]:
    """
    Parse agent references from flow spec.

    Looks for patterns like:
    - Agent: `agent-name`
    - Step tables with agent columns
    - Inline references to agents

    Returns list of (step_number, agent_name) tuples.
    """
    agents: List[Tuple[int, str]] = []
    content = flow_path.read_text(encoding="utf-8")
    lines = content.splitlines()

    # Pattern 1: Agent: `agent-name`
    agent_ref_pattern = re.compile(r"Agent:\s*`([a-zA-Z0-9_\-]+)`")

    # Pattern 2: Look in step tables
    in_table = False

    for i, line in enumerate(lines, start=1):
        # Check for agent references
        match = agent_ref_pattern.search(line)
        if match:
            agent_name = match.group(1)
            agents.append((i, agent_name))

        # Check step tables (| Step | Node | Type |)
        if "| Step" in line and "Node" in line and "Type" in line:
            in_table = True
            continue

        if in_table:
            if line.startswith("|---"):
                continue
            if not line.startswith("|"):
                in_table = False
                continue

            cols = [c.strip() for c in line.strip("|").split("|")]
            if len(cols) >= 3:
                try:
                    step = int(cols[0])
                    node = cols[1].strip()
                    node_type = cols[2].strip()

                    # Extract agent name from backticks
                    if node.startswith("`") and node.endswith("`"):
                        node = node[1:-1]

                    # Only track 'agent' type nodes
                    if node_type == "agent":
                        agents.append((step, node))
                except (ValueError, IndexError):
                    pass

    return agents


def validate_flow_references(registry: Dict[str, Dict[str, Any]]) -> ValidationResult:
    """
    Validate that all agent references in flow specs are valid.

    Checks:
    - Agent exists in registry or is a built-in
    - Suggests typos using Levenshtein distance
    """
    result = ValidationResult()

    if not FLOW_SPECS_DIR.is_dir():
        return result

    # Build list of valid agent names
    valid_agents = set(registry.keys()) | set(BUILT_IN_AGENTS)
    candidate_list = list(valid_agents)

    for flow_path in sorted(FLOW_SPECS_DIR.glob("flow-*.md")):
        if flow_path.is_symlink():
            # Skip symlinks: validation only applies to real files
            continue

        rel_path = flow_path.relative_to(ROOT)
        agent_refs = parse_flow_spec_agents(flow_path)

        for line_num, agent_name in agent_refs:
            if agent_name not in valid_agents:
                # Find similar names
                suggestions = suggest_typos(agent_name, candidate_list)

                location = f"{rel_path}:line {line_num}"

                if suggestions:
                    problem = f"references unknown agent '{agent_name}'; did you mean: {', '.join(suggestions)}?"
                    fix_action = f"Update reference to one of: {', '.join(suggestions)}, or add '{agent_name}' to swarm/AGENTS.md"
                else:
                    problem = f"references unknown agent '{agent_name}'"
                    fix_action = f"Add '{agent_name}' to swarm/AGENTS.md, or fix the agent name"

                result.add_error(
                    "REFERENCE",
                    location,
                    problem,
                    fix_action,
                    line_number=line_num,
                    file_path=str(flow_path)
                )

    return result


# ============================================================================
# FR-004: Skill File Validation
# ============================================================================

def validate_skills() -> ValidationResult:
    """
    Validate that skills declared in agent frontmatter have valid SKILL.md files.

    Checks:
    - Skill file exists
    - Skill frontmatter is valid (name, description)
    """
    result = ValidationResult()

    if not SKILLS_DIR.is_dir():
        return result

    # Collect all declared skills from agents
    declared_skills: Set[str] = set()
    if AGENTS_DIR.is_dir():
        for agent_path in AGENTS_DIR.glob("*.md"):
            if agent_path.is_symlink():
                # Skip symlinks: validation only applies to real files
                continue
            try:
                content = agent_path.read_text(encoding="utf-8")
                fm = SimpleYAMLParser.parse(content)
                if "skills" in fm and isinstance(fm["skills"], list):
                    # Type ignore: fm from YAML parser returns Any; we know skills are strings
                    skills_list: list[str] = [str(s) for s in fm["skills"]]  # type: ignore[misc]
                    declared_skills.update(skills_list)
            except Exception:
                pass

    # Check each declared skill has a valid file
    for skill_name in declared_skills:
        skill_file = SKILLS_DIR / skill_name / "SKILL.md"

        if not skill_file.is_file():
            result.add_error(
                "SKILL",
                f"skill '{skill_name}'",
                f"declared by agents but {skill_file.relative_to(ROOT)} does not exist",
                f"Create {skill_file.relative_to(ROOT)} with valid frontmatter (name, description)",
                file_path=str(skill_file)
            )
            continue

        # Validate skill frontmatter
        try:
            content = skill_file.read_text(encoding="utf-8")
            fm = SimpleYAMLParser.parse(content)

            if "name" not in fm or not fm.get("name", "").strip():
                result.add_error(
                    "SKILL",
                    str(skill_file.relative_to(ROOT)),
                    "missing required field 'name'",
                    f"Add `name: {skill_name}` to frontmatter",
                    file_path=str(skill_file)
                )

            if "description" not in fm or not fm.get("description", "").strip():
                result.add_error(
                    "SKILL",
                    str(skill_file.relative_to(ROOT)),
                    "missing required field 'description'",
                    "Add `description: <skill description>` to frontmatter",
                    file_path=str(skill_file)
                )
        except ValueError as e:
            result.add_error(
                "SKILL",
                str(skill_file.relative_to(ROOT)),
                f"malformed YAML in skill frontmatter: {e}",
                "Check YAML syntax in skill frontmatter",
                file_path=str(skill_file)
            )

    return result


# ============================================================================
# FR-005: RUN_BASE Path Validation
# ============================================================================

def validate_runbase_paths() -> ValidationResult:
    """
    Validate that flow specs use RUN_BASE placeholder, not hardcoded paths.

    Checks:
    - No hardcoded swarm/runs/<run-id>/ paths
    - RUN_BASE placeholder is correctly formatted (no $, {}, etc.)
    """
    result = ValidationResult()

    if not FLOW_SPECS_DIR.is_dir():
        return result

    # Patterns to detect
    # Match swarm/runs/SOMETHING/ where SOMETHING is alphanumeric, hyphens, underscores, or angle/curly brackets
    # Handles: swarm/runs/run-123/, swarm/runs/<run-id>/, swarm/runs/{run-id}/
    hardcoded_pattern = re.compile(r"swarm/runs/[a-zA-Z0-9_\-<>{}]+/")

    # Malformed RUN_BASE patterns:
    # - $RUN_BASE (shell variable syntax)
    # - {RUN_BASE} (template variable syntax without slash)
    # - RUN_BASE without trailing slash (e.g., RUN_BASEsignal)
    # - run_base or run-base (lowercase or hyphenated, case-sensitive check)
    malformed_runbase = re.compile(r"(\$RUN_BASE|RUN_BASE\}|RUN_BASE[a-zA-Z_]|\{RUN_BASE[^/]|run_base/)")

    for flow_path in sorted(FLOW_SPECS_DIR.glob("*.md")):
        if flow_path.is_symlink():
            # Skip symlinks: validation only applies to real files
            continue

        rel_path = flow_path.relative_to(ROOT)
        content = flow_path.read_text(encoding="utf-8")
        lines = content.splitlines()

        in_code_block = False

        for i, line in enumerate(lines, start=1):
            stripped_line = line.strip()
            # Track code blocks
            if stripped_line.startswith("```"):
                in_code_block = not in_code_block
                continue

            if in_code_block:
                continue

            # Skip comments (both Markdown and HTML)
            if stripped_line.startswith("#") or stripped_line.startswith("<!--"):
                continue

            # Check for hardcoded paths
            if hardcoded_pattern.search(line):
                result.add_error(
                    "RUNBASE",
                    f"{rel_path}:line {i}",
                    "contains hardcoded path 'swarm/runs/<run-id>/'; should use RUN_BASE placeholder",
                    "Replace hardcoded path with 'RUN_BASE/<flow>/' in artifact instructions",
                    line_number=i,
                    file_path=str(flow_path)
                )

            # Check for malformed RUN_BASE - iterate over all matches to include actual text
            for match in malformed_runbase.finditer(line):
                bad_text = match.group(0)
                result.add_error(
                    "RUNBASE",
                    f"{rel_path}:line {i}",
                    f"malformed RUN_BASE placeholder '{bad_text}' (should be 'RUN_BASE/<flow>/', not '$RUN_BASE', '{{RUN_BASE}}', or 'RUN_BASEsignal')",
                    "Use 'RUN_BASE/<flow>/' with forward slash; valid examples: RUN_BASE/signal/, RUN_BASE/plan/, RUN_BASE/build/",
                    line_number=i,
                    file_path=str(flow_path)
                )

    return result


# ============================================================================
# FR-006: Agent Prompt Section Validation
# ============================================================================


def validate_prompt_sections(registry: Dict[str, Dict[str, Any]], strict_mode: bool = False) -> ValidationResult:
    """
    Validate that agent prompt bodies include required sections.

    LEGACY: This check is skipped if .claude/agents/ directory does not exist.
    The new architecture uses swarm/config/agents/ for agent configuration instead.

    FR-006: Agent Prompt Sections
    Checks for presence of these required headings after frontmatter:
    - ## Inputs (or ## Input)
    - ## Outputs (or ## Output)
    - ## Behavior

    Args:
        registry: Agent registry from AGENTS.md
        strict_mode: If True, missing sections are errors; if False, warnings

    Returns:
        ValidationResult with errors or warnings for missing sections
    """
    result = ValidationResult()

    # LEGACY: Skip prompt sections check if .claude/agents/ doesn't exist
    # The new architecture uses swarm/config/agents/ instead
    if not AGENTS_DIR.is_dir():
        return result

    # Patterns to match required sections (case-insensitive)
    input_pattern = re.compile(r"^##\s+Inputs?\s*$", re.IGNORECASE | re.MULTILINE)
    output_pattern = re.compile(r"^##\s+Outputs?\s*$", re.IGNORECASE | re.MULTILINE)
    behavior_pattern = re.compile(r"^##\s+Behavior\s*$", re.IGNORECASE | re.MULTILINE)

    for path in sorted(AGENTS_DIR.glob("*.md")):
        if path.is_symlink():
            # Skip symlinks: validation only applies to real files
            continue

        filename_key = path.stem
        rel_path = path.relative_to(ROOT)

        # Skip built-in agents
        if filename_key in BUILT_IN_AGENTS:
            continue

        # Only validate project/user agents in registry
        if filename_key not in registry:
            continue

        agent_meta = registry[filename_key]
        if agent_meta.get("source") != "project/user":
            continue

        try:
            content = path.read_text(encoding="utf-8")
        except Exception:
            # Skip files that can't be read (already reported elsewhere)
            continue

        # Extract the body after frontmatter
        # Frontmatter is between first --- and second ---
        if content.startswith("---"):
            # Find the closing ---
            end_idx = content.find("---", 3)
            if end_idx != -1:
                body = content[end_idx + 3:].strip()
            else:
                body = ""
        else:
            body = content

        missing_sections: List[str] = []

        if not input_pattern.search(body):
            missing_sections.append("## Inputs")

        if not output_pattern.search(body):
            missing_sections.append("## Outputs")

        if not behavior_pattern.search(body):
            missing_sections.append("## Behavior")

        if missing_sections:
            location = str(rel_path)
            problem = f"missing required prompt sections: {', '.join(missing_sections)}"
            fix_action = f"Add the following sections to agent prompt: {', '.join(missing_sections)}"

            if strict_mode:
                result.add_error(
                    "PROMPT",
                    location,
                    problem,
                    fix_action,
                    file_path=str(path)
                )
            else:
                result.add_warning(
                    "PROMPT",
                    location,
                    problem,
                    fix_action,
                    file_path=str(path)
                )

    return result


# ============================================================================
# FR-FLOWS: Flow Invariants Validation
# ============================================================================
# Validates structural invariants for flow definitions (both YAML config and markdown docs)

def parse_flow_config(flow_path: Path) -> Dict[str, Any]:
    """
    Parse a flow config YAML file (robust YAML parsing without external deps).

    Handles both indentation styles:
    - signal.yaml: steps at indent 0, fields at indent 2
    - build.yaml: steps at indent 2, fields at indent 4

    Returns:
        Dict with keys: id, title, description, steps, cross_cutting, errors
    """
    result: Dict[str, Any] = {
        "id": flow_path.stem,
        "title": "",
        "description": "",
        "steps": [],
        "cross_cutting": [],
        "errors": []
    }

    try:
        content = flow_path.read_text(encoding="utf-8")
        lines = content.split("\n")

        current_list: Optional[str] = None
        in_step = False
        in_agents_list = False  # Track when we're inside an agents list

        for i, line in enumerate(lines, start=1):
            line_stripped = line.strip()

            # Skip empty lines and comments
            if not line_stripped or line_stripped.startswith("#"):
                in_agents_list = False  # Reset agents flag on empty line
                continue

            # Get indentation level
            indent = len(line) - len(line.lstrip())

            # Top-level key: value (no leading spaces) - but not list items (- ...)
            if indent == 0 and ":" in line_stripped and not line_stripped.startswith("- "):
                key, value = line_stripped.split(":", 1)
                key = key.strip()
                value = value.strip()

                if key == "key":
                    result["id"] = value.strip("'\"")
                elif key == "title":
                    result["title"] = value.strip("'\"")
                elif key == "description":
                    result["description"] = value.strip("'\"")
                elif key == "steps":
                    current_list = "steps"
                    in_step = False
                    in_agents_list = False
                elif key == "cross_cutting":
                    current_list = "cross_cutting"
                    in_step = False
                    in_agents_list = False
                else:
                    current_list = None
                    in_step = False
                    in_agents_list = False

            # Top-level list items (indent 0): step or cross_cutting item
            elif indent == 0 and line_stripped.startswith("- "):
                item = line_stripped[2:].strip()
                in_agents_list = False

                if current_list == "steps":
                    # Check if this line has 'id:' directly (step start)
                    if ":" in item:
                        key, value = item.split(":", 1)
                        if key.strip() == "id":
                            step_id = value.strip().strip("'\"")
                            result["steps"].append({  # type: ignore[union-attr]
                                "id": step_id,
                                "agents": [],
                                "role": "",
                                "human_only": False,
                                "line": i
                            })
                            in_step = True
                elif current_list == "cross_cutting":
                    # cross_cutting items are just agent names
                    result["cross_cutting"].append(item.strip("'\""))  # type: ignore[union-attr]
                    in_step = False

            # List item at indent level 2: could be a step or agent
            elif indent == 2 and line_stripped.startswith("- "):
                item = line_stripped[2:].strip()

                if current_list == "steps":
                    if in_agents_list:
                        # This is an agent under agents:
                        if result["steps"]:
                            result["steps"][-1]["agents"].append(item.strip("'\""))  # type: ignore[union-attr,index]
                    elif ":" in item:
                        # Check if this is a step start (has 'id:')
                        key, value = item.split(":", 1)
                        if key.strip() == "id":
                            step_id = value.strip().strip("'\"")
                            result["steps"].append({  # type: ignore[union-attr]
                                "id": step_id,
                                "agents": [],
                                "role": "",
                                "human_only": False,
                                "line": i
                            })
                            in_step = True
                            in_agents_list = False
                        else:
                            # Some other field at indent 2, mark as in_step
                            in_step = True
                    else:
                        in_step = True
                        in_agents_list = False
                elif current_list == "cross_cutting" and not in_agents_list:
                    result["cross_cutting"].append(item.strip("'\""))  # type: ignore[union-attr]

            # Nested fields within a step (agents:, role:, id:, etc.)
            elif current_list == "steps" and in_step and ":" in line_stripped:
                key, value = line_stripped.split(":", 1)
                key = key.strip()
                value = value.strip()

                if key == "agents":
                    in_agents_list = True
                elif in_agents_list:
                    # We were in agents list but hit another key, so exit agents list
                    in_agents_list = False
                    if key == "role" and result["steps"]:
                        result["steps"][-1]["role"] = value.strip("'\"")  # type: ignore[union-attr,index]

                if key == "id" and result["steps"]:
                    result["steps"][-1]["id"] = value.strip("'\"")  # type: ignore[union-attr,index]
                elif key == "role" and result["steps"]:
                    result["steps"][-1]["role"] = value.strip("'\"")  # type: ignore[union-attr,index]
                elif key == "kind":
                    if value.strip("'\"") == "human_only" and result["steps"]:
                        result["steps"][-1]["human_only"] = True  # type: ignore[union-attr,index]

            # Agent list items within a step (indent 6 for build.yaml style, indent 2 for signal.yaml)
            elif line_stripped.startswith("- ") and current_list == "steps" and in_agents_list:
                if result["steps"]:
                    agent_name = line_stripped[2:].strip().strip("'\"")
                    result["steps"][-1]["agents"].append(agent_name)  # type: ignore[union-attr,index]

    except Exception as e:
        result["errors"].append(f"Parse error: {e}")  # type: ignore[union-attr]

    return result


def validate_no_empty_flows(flow_configs: Dict[str, Dict[str, Any]]) -> ValidationResult:
    """
    Validate that each flow has at least one step.

    Invariant 1: No empty flows
    """
    result = ValidationResult()

    for flow_id, config in flow_configs.items():
        if not config.get("steps"):
            flow_file = FLOWS_CONFIG_DIR / f"{flow_id}.yaml"
            location = f"swarm/config/flows/{flow_id}.yaml"

            result.add_error(
                "FLOW",
                location,
                f"Flow '{flow_id}' has no steps",
                f"Add at least one step to {location}, or remove the flow definition",
                file_path=str(flow_file)
            )

    return result


def validate_no_agentless_steps(flow_configs: Dict[str, Dict[str, Any]]) -> ValidationResult:
    """
    Validate that each step has agents or is marked human_only.

    Invariant 2: No agentless steps (unless explicitly marked as human_only)
    """
    result = ValidationResult()

    for flow_id, config in flow_configs.items():
        for step in config.get("steps", []):
            if not step.get("agents") and not step.get("human_only"):
                flow_file = FLOWS_CONFIG_DIR / f"{flow_id}.yaml"
                location = f"swarm/config/flows/{flow_id}.yaml"

                result.add_error(
                    "FLOW",
                    location,
                    f"Step '{flow_id}/{step['id']}' has no agents and is not marked 'kind: human_only'",
                    "Either add agents to the step or mark it with 'kind: human_only'",
                    file_path=str(flow_file),
                    line_number=step.get("line")
                )

    return result


def validate_flow_agent_validity(flow_configs: Dict[str, Dict[str, Any]], registry: Dict[str, Dict[str, Any]]) -> ValidationResult:
    """
    Validate that all agent references in flows are valid.

    Invariant 3: Agent validity - agents exist in registry
    """
    result = ValidationResult()

    # Build list of valid agents
    valid_agents = set(registry.keys()) | set(BUILT_IN_AGENTS)
    candidate_list = list(valid_agents)

    for flow_id, config in flow_configs.items():
        for step in config.get("steps", []):
            for agent in step.get("agents", []):
                if agent not in valid_agents:
                    flow_file = FLOWS_CONFIG_DIR / f"{flow_id}.yaml"
                    location = f"swarm/config/flows/{flow_id}.yaml"

                    # Find similar names
                    suggestions = suggest_typos(agent, candidate_list)

                    if suggestions:
                        problem = f"Flow '{flow_id}' step '{step['id']}' references unknown agent '{agent}'; did you mean: {', '.join(suggestions)}?"
                        fix_action = f"Update agent reference to one of: {', '.join(suggestions)}, or add '{agent}' to swarm/AGENTS.md"
                    else:
                        problem = f"Flow '{flow_id}' step '{step['id']}' references unknown agent '{agent}'"
                        fix_action = f"Add '{agent}' to swarm/AGENTS.md, or fix the agent name"

                    result.add_error(
                        "FLOW",
                        location,
                        problem,
                        fix_action,
                        file_path=str(flow_file),
                        line_number=step.get("line")
                    )

    return result


def validate_flow_documentation_completeness() -> ValidationResult:
    """
    Validate that each flow config has corresponding markdown documentation.

    Invariant 4: Documentation completeness - each flow has a markdown file with autogen markers
    """
    result = ValidationResult()

    FLOWS_CONFIG_DIR = ROOT / "swarm" / "config" / "flows"
    FLOWS_DOC_DIR = ROOT / "swarm" / "flows"

    if not FLOWS_CONFIG_DIR.is_dir():
        return result

    for config_file in sorted(FLOWS_CONFIG_DIR.glob("*.yaml")):
        flow_id = config_file.stem

        # Check for corresponding markdown file
        doc_file = FLOWS_DOC_DIR / f"flow-{flow_id}.md"

        if not doc_file.is_file():
            location = f"swarm/config/flows/{flow_id}.yaml"

            result.add_error(
                "FLOW",
                location,
                f"Flow '{flow_id}' config exists but documentation file is missing",
                f"Create {doc_file.relative_to(ROOT)} with flow specification",
                file_path=str(config_file)
            )
            continue

        # Check for autogen markers in markdown
        try:
            content = doc_file.read_text(encoding="utf-8")
            has_start = "FLOW AUTOGEN START" in content or "<!-- FLOW AUTOGEN START" in content
            has_end = "FLOW AUTOGEN END" in content or "FLOW AUTOGEN END -->" in content

            if not (has_start and has_end):
                location = f"{doc_file.relative_to(ROOT)}"

                result.add_error(
                    "FLOW",
                    location,
                    "Flow documentation missing autogen markers",
                    f"Add '<!-- FLOW AUTOGEN START -->' and '<!-- FLOW AUTOGEN END -->' markers to {location}",
                    file_path=str(doc_file)
                )
        except Exception as e:
            result.add_error(
                "FLOW",
                str(doc_file.relative_to(ROOT)),
                f"Failed to read flow documentation: {e}",
                "Check file permissions and encoding",
                file_path=str(doc_file)
            )

    return result


def validate_flow_studio_sync() -> ValidationResult:
    """
    Optional: Try to connect to Flow Studio API to verify flow sync.

    Invariant 5 (optional): Flow Studio sanity check
    Returns warning only (not error) if server unavailable.
    """
    result = ValidationResult()

    # Try to connect to Flow Studio API
    try:
        import json
        import urllib.error
        import urllib.request

        url = "http://localhost:5000/api/flows"
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                data = json.loads(response.read().decode("utf-8"))

                # Verify response structure
                if isinstance(data, dict) and "flows" in data:
                    return result  # Success

                result.add_warning(
                    "FLOW",
                    "http://localhost:5000/api/flows",
                    "Flow Studio API response format unexpected",
                    "Verify Flow Studio is running and serving correct data"
                )
        except (urllib.error.URLError, urllib.error.HTTPError):
            # Server not available, don't warn (optional check)
            pass
        except json.JSONDecodeError:
            result.add_warning(
                "FLOW",
                "http://localhost:5000/api/flows",
                "Flow Studio API returned invalid JSON",
                "Verify Flow Studio is running correctly"
            )
    except (ImportError, Exception):
        # If we can't import urllib or connect, just skip the check
        pass

    return result


# ============================================================================
# FR-UTILITY: Utility Flow Validation
# ============================================================================

def validate_utility_flow_graphs() -> ValidationResult:
    """
    Validate utility flow graph specifications.

    FR-UTILITY: Utility Flow Consistency
    Checks:
    - If is_utility_flow is true, injection_trigger should be defined
    - If is_utility_flow is true, on_complete.next_flow should be "return" or "pause"
    - If is_utility_flow is true, flow_number should be >= 8
    - Utility flows should not have next_flow pointing to a flow spec ID
    - Main SDLC flows (1-7) should not have is_utility_flow=true
    """
    result = ValidationResult()

    flow_graphs_dir = ROOT / "swarm" / "spec" / "flows"

    if not flow_graphs_dir.is_dir():
        return result

    # Valid utility flow next_flow values
    valid_utility_next_flows = {"return", "pause"}

    for graph_file in sorted(flow_graphs_dir.glob("*.graph.json")):
        if graph_file.is_symlink():
            continue

        rel_path = graph_file.relative_to(ROOT)

        try:
            content = graph_file.read_text(encoding="utf-8")
            graph_data = json.loads(content)
        except json.JSONDecodeError as e:
            result.add_error(
                "UTILITY",
                str(rel_path),
                f"Invalid JSON in flow graph: {e}",
                "Fix JSON syntax errors in the flow graph file",
                file_path=str(graph_file)
            )
            continue
        except Exception as e:
            result.add_error(
                "UTILITY",
                str(rel_path),
                f"Failed to read flow graph: {e}",
                "Check file permissions and encoding",
                file_path=str(graph_file)
            )
            continue

        # Extract relevant fields
        flow_number = graph_data.get("flow_number", 0)
        metadata = graph_data.get("metadata", {})
        is_utility_flow = metadata.get("is_utility_flow", False)
        injection_trigger = metadata.get("injection_trigger")
        on_complete = graph_data.get("on_complete", {})
        next_flow = on_complete.get("next_flow", "")
        flow_id = graph_data.get("id", graph_file.stem)

        # Validation Rule 1: Utility flows need injection_trigger
        if is_utility_flow and not injection_trigger:
            result.add_error(
                "UTILITY",
                str(rel_path),
                f"Utility flow '{flow_id}' is missing injection_trigger in metadata",
                "Add 'injection_trigger' to metadata section (e.g., 'upstream_diverged', 'lint_failure')",
                file_path=str(graph_file)
            )

        # Validation Rule 2: Utility flows should use 'return' or 'pause' for next_flow
        if is_utility_flow:
            if next_flow and next_flow not in valid_utility_next_flows:
                # Check if it looks like a flow spec ID (e.g., "4-gate")
                if re.match(r"^\d+-[a-z]+$", next_flow):
                    result.add_error(
                        "UTILITY",
                        str(rel_path),
                        f"Utility flow '{flow_id}' has on_complete.next_flow='{next_flow}' which is a flow spec ID; utility flows should use 'return' or 'pause'",
                        "Change on_complete.next_flow to 'return' (to resume interrupted flow) or 'pause' (for human intervention)",
                        file_path=str(graph_file)
                    )
                else:
                    # Warn about unknown next_flow value
                    result.add_warning(
                        "UTILITY",
                        str(rel_path),
                        f"Utility flow '{flow_id}' has unusual on_complete.next_flow='{next_flow}'; expected 'return' or 'pause'",
                        "Consider using 'return' or 'pause' for utility flows",
                        file_path=str(graph_file)
                    )

        # Validation Rule 3: Utility flows should have flow_number >= 8
        if is_utility_flow and flow_number < 8:
            result.add_error(
                "UTILITY",
                str(rel_path),
                f"Utility flow '{flow_id}' has flow_number={flow_number}; utility flows should use 8+ (main SDLC flows use 1-7)",
                "Change flow_number to 8 or higher to indicate this is a utility flow",
                file_path=str(graph_file)
            )

        # Validation Rule 4: Main SDLC flows (1-7) should not have is_utility_flow=true
        if flow_number >= 1 and flow_number <= 7 and is_utility_flow:
            result.add_error(
                "UTILITY",
                str(rel_path),
                f"Flow '{flow_id}' (flow_number={flow_number}) is marked as utility flow but uses SDLC flow number (1-7)",
                "Either remove is_utility_flow from metadata, or change flow_number to 8+",
                file_path=str(graph_file)
            )

        # Validation Rule 5: If injection_trigger is defined but is_utility_flow is not true, warn
        if injection_trigger and not is_utility_flow:
            result.add_warning(
                "UTILITY",
                str(rel_path),
                f"Flow '{flow_id}' has injection_trigger='{injection_trigger}' but is_utility_flow is not true",
                "Add 'is_utility_flow: true' to metadata if this is a utility flow",
                file_path=str(graph_file)
            )

    return result


# ============================================================================
# FR-006: Banned Microloop Phrases (Design Constraint Enforcement)
# ============================================================================

def validate_microloop_phrases() -> ValidationResult:
    """
    Validate that deprecated microloop phrases are not used.

    Banned phrases (old iteration logic):
    - "restat"
    - "until the reviewer is satisfied or can only restate concerns"
    - "can only restate concerns"
    - "restating same concerns"

    Allowed alternatives:
    - "can_further_iteration_help: yes"
    - "can_further_iteration_help: no"
    - Status-based logic (VERIFIED/UNVERIFIED + iteration guidance)

    Checks:
    - Flow specs (.claude/commands/*.md, swarm/flows/*.md)
    - Main documentation (CLAUDE.md)
    - Agent definitions (.claude/agents/*.md)
    """
    result = ValidationResult()

    # Banned phrases list
    banned_phrases = [
        r"restat",  # Catches "restate", "restating", etc.
        r"until the reviewer is satisfied or can only restate concerns",
        r"can only restate concerns",
        r"restating same concerns",
        r"until the reviewer is satisfied\s+or",  # Partial old pattern
    ]

    # Directories to check
    check_dirs = [
        (ROOT / ".claude" / "commands", "Commands"),
        (ROOT / "swarm" / "flows", "Flow Specs"),
        (ROOT / ".claude" / "agents", "Agent Definitions"),
    ]

    # Check root-level CLAUDE.md
    check_files = [
        (ROOT / "CLAUDE.md", "CLAUDE.md"),
    ]

    # Helper: check file for banned phrases
    def check_file_for_banned_phrases(file_path: Path, _display_name: str) -> None:
        try:
            content = file_path.read_text(encoding="utf-8")
            lines = content.splitlines()

            for i, line in enumerate(lines, start=1):
                # Skip comments and code blocks that might be examples
                if line.strip().startswith("#"):
                    continue

                for banned_phrase in banned_phrases:
                    if re.search(banned_phrase, line, re.IGNORECASE):
                        rel_path = file_path.relative_to(ROOT)
                        result.add_error(
                            "MICROLOOP",
                            f"{rel_path}:line {i}",
                            f"uses banned microloop phrase '{banned_phrase}' (old iteration logic)",
                            "Replace with explicit 'can_further_iteration_help: yes/no' or Status-based exit logic",
                            line_number=i,
                            file_path=str(file_path)
                        )
        except (OSError, UnicodeDecodeError):
            pass  # Skip files that can't be read

    # Check specified files
    for file_path, display_name in check_files:
        if file_path.is_file():
            check_file_for_banned_phrases(file_path, display_name)

    # Check directories
    for dir_path, display_name in check_dirs:
        if dir_path.is_dir():
            for file_path in dir_path.rglob("*.md"):
                check_file_for_banned_phrases(file_path, display_name)

    return result


# ============================================================================
# FR-007: Capability Registry Validation
# ============================================================================

def validate_capability_registry() -> ValidationResult:
    """
    Validate the capability registry for evidence discipline.

    FR-007: Capability Registry
    Checks:
    - implemented capabilities have >=1 test pointer
    - implemented capabilities have >=1 code pointer
    - @cap:<id> tags in BDD reference capabilities that exist in registry
    - aspirational capabilities are not claimed as implemented

    This validation ensures that capability claims have evidence,
    preventing "narrative drift" where docs claim capabilities
    that aren't backed by code or tests.
    """
    result = ValidationResult()

    # Check if capability registry exists
    registry_path = ROOT / "specs" / "capabilities.yaml"
    if not registry_path.exists():
        result.add_warning(
            "CAPABILITY",
            "specs/capabilities.yaml",
            "capability registry not found (optional file)",
            "Create specs/capabilities.yaml to track capability claims with evidence",
            file_path=str(registry_path)
        )
        return result

    # Parse capability registry (uses PyYAML, not SimpleYAMLParser which is for frontmatter)
    try:
        import yaml
        content = registry_path.read_text(encoding="utf-8")
        registry = yaml.safe_load(content)
    except ImportError:
        result.add_warning(
            "CAPABILITY",
            "specs/capabilities.yaml",
            "PyYAML not installed; skipping capability registry validation",
            "Install PyYAML: pip install pyyaml",
            file_path=str(registry_path)
        )
        return result
    except Exception as e:
        result.add_error(
            "CAPABILITY",
            "specs/capabilities.yaml",
            f"failed to parse capability registry: {e}",
            "Fix YAML syntax in specs/capabilities.yaml",
            file_path=str(registry_path)
        )
        return result

    # Collect all capability IDs
    cap_ids: Set[str] = set()
    aspirational_ids: Set[str] = set()

    surfaces = registry.get("surfaces", {})
    if not isinstance(surfaces, dict):
        result.add_error(
            "CAPABILITY",
            "specs/capabilities.yaml",
            "'surfaces' must be a dict",
            "Fix structure: surfaces should map surface names to capability lists",
            file_path=str(registry_path)
        )
        return result

    for surface_key, surface_data in surfaces.items():
        if not isinstance(surface_data, dict):
            continue

        capabilities = surface_data.get("capabilities", [])
        if not isinstance(capabilities, list):
            continue

        for cap in capabilities:
            if not isinstance(cap, dict):
                continue

            cap_id = cap.get("id", "")
            status = cap.get("status", "")
            evidence = cap.get("evidence", {})

            if not cap_id:
                result.add_warning(
                    "CAPABILITY",
                    f"specs/capabilities.yaml:{surface_key}",
                    "capability missing 'id' field",
                    "Add 'id' field to capability entry",
                    file_path=str(registry_path)
                )
                continue

            cap_ids.add(cap_id)

            if status == "aspirational":
                aspirational_ids.add(cap_id)
                # Aspirational caps don't need code/test evidence
                continue

            if status == "implemented":
                # Must have test evidence
                tests = evidence.get("tests", [])
                if not tests:
                    result.add_error(
                        "CAPABILITY",
                        f"specs/capabilities.yaml:{cap_id}",
                        f"capability '{cap_id}' is 'implemented' but has no test evidence",
                        "Add 'tests' evidence pointers or change status to 'supported'",
                        file_path=str(registry_path)
                    )

                # Must have code evidence
                code = evidence.get("code", [])
                if not code:
                    result.add_error(
                        "CAPABILITY",
                        f"specs/capabilities.yaml:{cap_id}",
                        f"capability '{cap_id}' is 'implemented' but has no code evidence",
                        "Add 'code' evidence pointers with path and symbol",
                        file_path=str(registry_path)
                    )

    # Check BDD @cap: tags reference capabilities that exist
    features_dir = ROOT / "features"
    if features_dir.is_dir():
        for feature_file in features_dir.glob("*.feature"):
            try:
                feature_content = feature_file.read_text(encoding="utf-8")
                # Find all @cap:<id> tags
                cap_tag_pattern = re.compile(r"@cap:([a-z0-9_.]+)")
                for match in cap_tag_pattern.finditer(feature_content):
                    tag_id = match.group(1)
                    if tag_id not in cap_ids:
                        # Find line number
                        line_num = feature_content[:match.start()].count('\n') + 1
                        result.add_error(
                            "CAPABILITY",
                            f"{feature_file.name}:line {line_num}",
                            f"@cap:{tag_id} references capability not in registry",
                            f"Add '{tag_id}' to specs/capabilities.yaml or fix tag",
                            line_number=line_num,
                            file_path=str(feature_file)
                        )
            except (OSError, UnicodeDecodeError):
                pass  # Skip files that can't be read

    return result


# ============================================================================
# Git-Aware Incremental Mode (FR-011)
# ============================================================================

def get_modified_files() -> Optional[Set[str]]:
    """
    Get list of modified files from git, including uncommitted changes.

    Resolves default branch dynamically (origin/HEAD or fallback to main).
    Includes both committed and uncommitted changes relative to base branch.

    Returns set of file paths relative to repo root, or None if git unavailable.
    Returns an empty set when the repo is clean.
    """
    try:
        def _ref_exists(ref: str) -> bool:
            """Check if a git ref exists (local or remote)."""
            result = subprocess.run(
                ["git", "show-ref", "--verify", "--quiet", ref],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=5,
            )
            return result.returncode == 0

        # Resolve default branch dynamically
        base_branch: Optional[str] = None
        try:
            # Try to get the default branch from origin/HEAD
            result = subprocess.run(
                ["git", "symbolic-ref", "refs/remotes/origin/HEAD"],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                # Result is like "refs/remotes/origin/main"
                ref = result.stdout.strip().split("/")[-1]
                if ref:
                    base_branch = ref
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass  # Use fallback

        # Fall back to common default branches if origin/HEAD is unavailable
        if base_branch is None:
            for ref in (
                "refs/remotes/origin/main",
                "refs/remotes/origin/master",
                "refs/heads/main",
                "refs/heads/master",
            ):
                if _ref_exists(ref):
                    # Keep remote prefix (origin/main) when present
                    base_branch = ref.replace("refs/remotes/", "").replace("refs/heads/", "")
                    break

        if base_branch is None:
            base_branch = "main"

        # Get modified files including uncommitted changes
        # git diff <base> (without HEAD) shows both staged and unstaged changes
        diff_output: Optional[str] = None
        for target in [base_branch, "HEAD"] if base_branch != "HEAD" else [base_branch]:
            result = subprocess.run(
                ["git", "diff", "--name-only", target],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                diff_output = result.stdout
                break

        if diff_output is None:
            return None

        # Parse diff output (includes uncommitted changes)
        files = set(diff_output.strip().splitlines())

        # Also include staged changes (already in git diff, but be explicit)
        # and any modified files from git status
        result_status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=5
        )

        if result_status.returncode == 0:
            # Parse status output (modified/staged/untracked)
            for line in result_status.stdout.splitlines():
                if len(line) > 3:
                    # Status format: "XY filename"
                    # Include any modified (M), added (A), deleted (D), renamed (R), etc.
                    status = line[:2].strip()
                    if status:  # Non-empty status means file was changed
                        files.add(line[3:].split(" -> ")[-1])  # handle renames

        return files
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None


def should_check_file(file_path: Path, modified_files: Optional[Set[str]]) -> bool:
    """
    Determine if file should be checked based on --check-modified flag.

    Args:
        file_path: Absolute path to file
        modified_files: Set of modified files (None = check all)

    Returns:
        True if file should be checked
    """
    if modified_files is None:
        return True

    try:
        rel_path = str(file_path.relative_to(ROOT))
        return rel_path in modified_files
    except ValueError:
        return True


# ============================================================================
# ValidatorRunner Class - Orchestrates Validation Checks
# ============================================================================


class ValidatorRunner:
    """
    Orchestrates validation checks for the swarm.

    Encapsulates the logic for running different categories of validation
    (agents, flows, skills) with support for incremental mode and debug output.

    Attributes:
        registry: Agent registry from AGENTS.md
        modified_files: Set of modified files (None = check all)
        debug: If True, print debug information
        strict: If True, enforce swarm design constraints as errors
        flows_only: If True, only run flow validation checks
        check_prompts: If True, validate agent prompt sections
    """

    def __init__(
        self,
        registry: Dict[str, Dict[str, Any]],
        modified_files: Optional[Set[str]] = None,
        debug: bool = False,
        strict: bool = False,
        flows_only: bool = False,
        check_prompts: bool = False,
    ):
        """
        Initialize the validator runner.

        Args:
            registry: Agent registry from AGENTS.md
            modified_files: Set of modified files for incremental mode (None = check all)
            debug: If True, print debug information to stderr
            strict: If True, enforce swarm design constraints as errors
            flows_only: If True, only run flow validation checks
            check_prompts: If True, validate agent prompt sections
        """
        self.registry = registry
        self.modified_files = modified_files
        self.debug = debug
        self.strict = strict
        self.flows_only = flows_only
        self.check_prompts = check_prompts

    def _should_check(self, *path_prefixes: str) -> bool:
        """
        Check if any file matching the given prefixes should be validated.

        Args:
            path_prefixes: Path prefixes to check (e.g., "swarm/AGENTS.md", ".claude/agents/")

        Returns:
            True if validation should run for these paths
        """
        if self.modified_files is None:
            return True
        return any(
            any(f.startswith(prefix) for prefix in path_prefixes)
            for f in self.modified_files
        )

    def _debug_print(self, message: str) -> None:
        """Print debug message to stderr if debug mode is enabled."""
        if self.debug:
            print(f"Debug: {message}", file=sys.stderr)

    def run_all(self) -> ValidationResult:
        """
        Run all validation checks.

        Returns:
            ValidationResult with all errors and warnings
        """
        start_time = time.time()
        result = ValidationResult()

        self._debug_print(f"Parsed {len(self.registry)} agents from registry")

        if self.flows_only:
            self._debug_print("Running flows-only validation")
            result.extend(self.run_flows())
        else:
            # Full validation: run all checks in order
            result.extend(self.run_agents())
            result.extend(self.run_flows())
            result.extend(self.run_skills())
            result.extend(self._run_microloop_validation())
            result.extend(self._run_prompt_validation())
            result.extend(self._run_capability_validation())

        elapsed = time.time() - start_time
        mode = "Flows-only" if self.flows_only else "Full"
        self._debug_print(f"{mode} validation completed in {elapsed:.3f}s")

        return result

    def run_agents(self) -> ValidationResult:
        """
        Run agent-related validation checks.

        Includes:
        - FR-CONF-001: Config coverage validation (new architecture)
        - FR-001: Bijection validation (LEGACY: skipped if .claude/agents/ doesn't exist)
        - FR-002: Frontmatter validation (LEGACY: skipped if .claude/agents/ doesn't exist)
        - FR-002b: Color validation (LEGACY: skipped if .claude/agents/ doesn't exist)

        Returns:
            ValidationResult with agent-related errors and warnings
        """
        result = ValidationResult()

        # FR-CONF-001: Config coverage validation
        if self._should_check("swarm/AGENTS.md", "swarm/config/agents/"):
            config_result = validate_config_coverage(self.registry)
            result.extend(config_result)
            self._debug_print(f"Config coverage check: {len(config_result.errors)} errors")

        # FR-001: Bijection validation
        if self._should_check("swarm/AGENTS.md", ".claude/agents/"):
            bijection_result = validate_bijection(self.registry)
            result.extend(bijection_result)
            self._debug_print(f"Bijection check: {len(bijection_result.errors)} errors")

        # FR-002: Frontmatter validation
        if self._should_check(".claude/agents/"):
            frontmatter_result = validate_frontmatter(self.registry, strict_mode=self.strict)
            result.extend(frontmatter_result)
            self._debug_print(
                f"Frontmatter check: {len(frontmatter_result.errors)} errors, "
                f"{len(frontmatter_result.warnings)} warnings"
            )

        # FR-002b: Color validation
        if self._should_check(".claude/agents/", "swarm/AGENTS.md"):
            color_result = validate_colors(self.registry)
            result.extend(color_result)
            self._debug_print(f"Color check: {len(color_result.errors)} errors")

        return result

    def run_flows(self) -> ValidationResult:
        """
        Run flow-related validation checks.

        Includes:
        - FR-003: Flow reference validation
        - FR-005: RUN_BASE validation
        - FR-FLOWS: Flow invariant checks (no empty flows, no agentless steps, etc.)

        Returns:
            ValidationResult with flow-related errors and warnings
        """
        result = ValidationResult()

        # FR-003: Flow reference validation (only in full mode, not flows_only)
        if not self.flows_only and self._should_check("swarm/flows/", "swarm/AGENTS.md"):
            reference_result = validate_flow_references(self.registry)
            result.extend(reference_result)
            self._debug_print(f"Reference check: {len(reference_result.errors)} errors")

        # FR-005: RUN_BASE validation (only in full mode, not flows_only)
        if not self.flows_only and self._should_check("swarm/flows/"):
            runbase_result = validate_runbase_paths()
            result.extend(runbase_result)
            self._debug_print(f"RUN_BASE check: {len(runbase_result.errors)} errors")

        # FR-FLOWS: Flow invariant checks
        if self.flows_only or self._should_check("swarm/config/flows/", "swarm/flows/"):
            result.extend(self._run_flow_invariant_checks())

        return result

    def _run_flow_invariant_checks(self) -> ValidationResult:
        """
        Run flow invariant validation checks.

        Parses flow configs and validates:
        - No empty flows
        - No agentless steps
        - Agent validity
        - Documentation completeness
        - Flow Studio sync (optional)
        - Utility flow consistency (FR-UTILITY)

        Returns:
            ValidationResult with flow invariant errors and warnings
        """
        result = ValidationResult()

        # Parse all flow configs
        flow_configs: Dict[str, Dict[str, Any]] = {}
        if FLOWS_CONFIG_DIR.is_dir():
            for flow_file in sorted(FLOWS_CONFIG_DIR.glob("*.yaml")):
                flow_id = flow_file.stem
                flow_configs[flow_id] = parse_flow_config(flow_file)
            self._debug_print(f"Parsed {len(flow_configs)} flow configs")

        # Invariant 1: No empty flows
        no_empty_result = validate_no_empty_flows(flow_configs)
        result.extend(no_empty_result)
        self._debug_print(f"No-empty-flows check: {len(no_empty_result.errors)} errors")

        # Invariant 2: No agentless steps
        no_agentless_result = validate_no_agentless_steps(flow_configs)
        result.extend(no_agentless_result)
        self._debug_print(f"No-agentless-steps check: {len(no_agentless_result.errors)} errors")

        # Invariant 3: Agent validity
        agent_validity_result = validate_flow_agent_validity(flow_configs, self.registry)
        result.extend(agent_validity_result)
        self._debug_print(f"Agent-validity check: {len(agent_validity_result.errors)} errors")

        # Invariant 4: Documentation completeness
        doc_completeness_result = validate_flow_documentation_completeness()
        result.extend(doc_completeness_result)
        self._debug_print(f"Doc-completeness check: {len(doc_completeness_result.errors)} errors")

        # Invariant 5: Flow Studio sync (optional)
        flow_studio_result = validate_flow_studio_sync()
        result.extend(flow_studio_result)
        self._debug_print(f"Flow-studio-sync check: {len(flow_studio_result.warnings)} warnings")

        # Invariant 6: Utility flow validation (flow graph JSON files)
        utility_flow_result = validate_utility_flow_graphs()
        result.extend(utility_flow_result)
        self._debug_print(f"Utility-flow check: {len(utility_flow_result.errors)} errors, {len(utility_flow_result.warnings)} warnings")

        return result

    def run_skills(self) -> ValidationResult:
        """
        Run skill-related validation checks.

        Includes:
        - FR-004: Skill validation

        Returns:
            ValidationResult with skill-related errors and warnings
        """
        result = ValidationResult()

        # FR-004: Skill validation
        if self._should_check(".claude/skills/", ".claude/agents/"):
            skill_result = validate_skills()
            result.extend(skill_result)
            self._debug_print(f"Skill check: {len(skill_result.errors)} errors")

        return result

    def _run_microloop_validation(self) -> ValidationResult:
        """
        Run microloop phrase validation.

        Includes:
        - FR-006a: Microloop phrase validation (ban old "restates concerns" patterns)

        Returns:
            ValidationResult with microloop-related errors
        """
        result = ValidationResult()

        # FR-006a: Microloop phrase validation
        if self._should_check(
            ".claude/commands/",
            "swarm/flows/",
            ".claude/agents/",
            "CLAUDE.md"
        ):
            microloop_result = validate_microloop_phrases()
            result.extend(microloop_result)
            self._debug_print(f"Microloop phrase check: {len(microloop_result.errors)} errors")

        return result

    def _run_prompt_validation(self) -> ValidationResult:
        """
        Run prompt section validation (optional).

        Includes:
        - FR-006b: Agent prompt section validation

        Returns:
            ValidationResult with prompt-related errors or warnings
        """
        result = ValidationResult()

        # FR-006b: Agent prompt section validation (optional, enabled with check_prompts)
        if self.check_prompts:
            if self._should_check(".claude/agents/"):
                prompt_result = validate_prompt_sections(self.registry, strict_mode=self.strict)
                result.extend(prompt_result)
                self._debug_print(
                    f"Prompt sections check: {len(prompt_result.errors)} errors, "
                    f"{len(prompt_result.warnings)} warnings"
                )

        return result

    def _run_capability_validation(self) -> ValidationResult:
        """
        Run capability registry validation.

        Includes:
        - FR-007: Capability registry validation

        Returns:
            ValidationResult with capability-related errors or warnings
        """
        result = ValidationResult()

        # FR-007: Capability registry validation
        if self._should_check("specs/capabilities.yaml", "features/"):
            capability_result = validate_capability_registry()
            result.extend(capability_result)
            self._debug_print(
                f"Capability registry check: {len(capability_result.errors)} errors, "
                f"{len(capability_result.warnings)} warnings"
            )

        return result


# ============================================================================
# Main Validation Orchestrator (Thin Wrapper)
# ============================================================================


def run_validation(
    check_modified: bool = False,
    debug: bool = False,
    strict_mode: bool = False,
    flows_only: bool = False,
    check_prompts: bool = False
) -> ValidationResult:
    """
    Run all validation checks.

    This is a thin wrapper around ValidatorRunner for backward compatibility.

    Args:
        check_modified: If True, only check modified files (git-aware mode)
        debug: If True, print debug information
        strict_mode: If True, enforce swarm design constraints as errors (not warnings)
        flows_only: If True, only run flow validation checks
        check_prompts: If True, validate agent prompt sections (## Inputs, ## Outputs, ## Behavior)

    Returns:
        ValidationResult with all errors and warnings
    """
    # Get modified files if incremental mode
    modified_files = None
    if check_modified:
        if debug:
            print("Debug: Git-aware mode enabled", file=sys.stderr)
        modified_files = get_modified_files()
        if modified_files is None:
            if debug:
                print("Debug: Git unavailable, falling back to full validation", file=sys.stderr)
        elif debug:
            print(f"Debug: Modified files: {len(modified_files)}", file=sys.stderr)

    # Parse registry (always needed, even for flow-only checks)
    try:
        registry = parse_agents_registry()
    except SystemExit:
        raise
    except Exception as e:
        print(f"ERROR: Failed to parse agent registry: {e}", file=sys.stderr)
        sys.exit(EXIT_FATAL_ERROR)

    # Create runner and execute validation
    runner = ValidatorRunner(
        registry=registry,
        modified_files=modified_files,
        debug=debug,
        strict=strict_mode,
        flows_only=flows_only,
        check_prompts=check_prompts,
    )

    return runner.run_all()


# ============================================================================
# JSON Output for Machine-Readable Results
# ============================================================================

def build_detailed_json_output(
    result: ValidationResult,
    registry: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Build detailed JSON output with per-agent/flow/step breakdown.

    The output format provides machine-readable validation results
    that can be consumed by Flow Studio for governance overlays.
    """
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")

    # Build agents section with per-agent check status
    agents_data: Dict[str, Any] = {}
    for agent_key in sorted(registry.keys()):
        if agent_key in BUILT_IN_AGENTS:
            continue

        meta = registry[agent_key]
        if meta.get("source") != "project/user":
            continue

        agent_file = AGENTS_DIR / f"{agent_key}.md"
        rel_path = str(agent_file.relative_to(ROOT)) if agent_file.exists() else f".claude/agents/{agent_key}.md"

        # Collect all errors/warnings for this agent
        agent_errors = [e for e in result.errors if agent_key in e.location or (e.file_path and agent_key in e.file_path)]
        agent_warnings = [w for w in result.warnings if agent_key in w.location or (w.file_path and agent_key in w.file_path)]

        checks: Dict[str, Any] = {}

        # FR-001: Bijection check
        bijection_errors = [e for e in agent_errors if e.error_type == "BIJECTION"]
        if bijection_errors:
            checks["FR-001"] = {
                "status": "fail",
                "message": bijection_errors[0].problem,
                "fix": bijection_errors[0].fix_action,
            }
        else:
            checks["FR-001"] = {"status": "pass", "message": "Registered in AGENTS.md"}

        # FR-002: Frontmatter check
        frontmatter_errors = [e for e in agent_errors if e.error_type == "FRONTMATTER"]
        frontmatter_warnings = [w for w in agent_warnings if w.error_type == "FRONTMATTER"]
        if frontmatter_errors:
            checks["FR-002"] = {
                "status": "fail",
                "message": frontmatter_errors[0].problem,
                "fix": frontmatter_errors[0].fix_action,
            }
        elif frontmatter_warnings:
            checks["FR-002"] = {
                "status": "warn",
                "message": frontmatter_warnings[0].problem,
                "fix": frontmatter_warnings[0].fix_action,
            }
        else:
            checks["FR-002"] = {"status": "pass", "message": "Frontmatter valid"}

        # Color check (part of FR-002b)
        color_errors = [e for e in agent_errors if e.error_type == "COLOR"]
        if color_errors:
            checks["FR-002b"] = {
                "status": "fail",
                "message": color_errors[0].problem,
                "fix": color_errors[0].fix_action,
            }
        else:
            checks["FR-002b"] = {"status": "pass", "message": "Color matches role family"}

        # Config check
        config_errors = [e for e in agent_errors if e.error_type == "CONFIG"]
        if config_errors:
            checks["FR-CONF"] = {
                "status": "fail",
                "message": config_errors[0].problem,
                "fix": config_errors[0].fix_action,
            }
        else:
            checks["FR-CONF"] = {"status": "pass", "message": "Config aligned"}

        # Determine overall status for this agent
        has_issues = any(c.get("status") == "fail" for c in checks.values())
        has_warnings = any(c.get("status") == "warn" for c in checks.values())

        agents_data[agent_key] = {
            "file": rel_path,
            "checks": checks,
            "has_issues": has_issues,
            "has_warnings": has_warnings,
            "issues": [e.to_dict() for e in agent_errors],
        }

    # Build flows section with per-flow check status
    flows_data: Dict[str, Any] = {}

    # Lazy import to support running validator in test repos without swarm/config/
    try:
        from swarm.config.flow_registry import get_flow_keys
        flow_keys = get_flow_keys()
    except ImportError:
        # Fallback: use canonical 7-flow keys if registry not available
        flow_keys = ["signal", "plan", "build", "review", "gate", "deploy", "wisdom"]

    for flow_id in flow_keys:
        flow_file = FLOW_SPECS_DIR / f"flow-{flow_id}.md"
        rel_path = str(flow_file.relative_to(ROOT)) if flow_file.exists() else f"swarm/flows/flow-{flow_id}.md"

        # Collect all errors for this flow
        flow_errors = [e for e in result.errors if flow_id in e.location or (e.file_path and flow_id in e.file_path)]

        checks: Dict[str, Any] = {}  # type: ignore[no-redef]

        # FR-003: Flow references check
        reference_errors = [e for e in flow_errors if e.error_type == "REFERENCE"]
        if reference_errors:
            checks["FR-003"] = {
                "status": "fail",
                "message": reference_errors[0].problem,
                "fix": reference_errors[0].fix_action,
            }
        else:
            checks["FR-003"] = {"status": "pass", "message": "All agent references valid"}

        # FR-005: RUN_BASE paths check
        runbase_errors = [e for e in flow_errors if e.error_type == "RUNBASE"]
        if runbase_errors:
            checks["FR-005"] = {
                "status": "fail",
                "message": runbase_errors[0].problem,
                "fix": runbase_errors[0].fix_action,
            }
        else:
            checks["FR-005"] = {"status": "pass", "message": "RUN_BASE paths correct"}

        # Flow-specific checks
        flow_check_errors = [e for e in flow_errors if e.error_type == "FLOW"]
        if flow_check_errors:
            checks["FR-FLOW"] = {
                "status": "fail",
                "message": flow_check_errors[0].problem,
                "fix": flow_check_errors[0].fix_action,
            }
        else:
            checks["FR-FLOW"] = {"status": "pass", "message": "Flow structure valid"}

        has_issues = any(c.get("status") == "fail" for c in checks.values())

        flows_data[flow_id] = {
            "file": rel_path,
            "checks": checks,
            "has_issues": has_issues,
            "issues": [e.to_dict() for e in flow_errors],
        }

    # Build steps section (for detailed step-level governance issues)
    steps_data: Dict[str, Any] = {}
    # Steps can be identified from flow config files
    if FLOWS_CONFIG_DIR.is_dir():
        for flow_file in sorted(FLOWS_CONFIG_DIR.glob("*.yaml")):
            flow_id = flow_file.stem
            flow_config = parse_flow_config(flow_file)
            for step in flow_config.get("steps", []):
                step_id = step.get("id", "")
                full_step_id = f"{flow_id}:{step_id}"

                # Check for step-specific issues (agentless steps, invalid agent refs)
                step_errors = [e for e in result.errors
                               if (e.error_type == "FLOW" and step_id in e.problem)]

                if step_errors:
                    steps_data[full_step_id] = {
                        "checks": {
                            "FR-FLOW": {
                                "status": "fail",
                                "message": step_errors[0].problem,
                                "fix": step_errors[0].fix_action,
                            }
                        },
                        "has_issues": True,
                        "issues": [e.to_dict() for e in step_errors],
                    }

    # Build skills section
    skills_data: Dict[str, Any] = {}
    skill_errors = [e for e in result.errors if e.error_type == "SKILL"]
    for err in skill_errors:
        # Extract skill name from error location or problem
        if "skill '" in err.problem:
            skill_name = err.problem.split("skill '")[1].split("'")[0]
        else:
            skill_name = err.location.replace("skill ", "").replace("'", "")

        skills_data[skill_name] = {
            "checks": {
                "FR-004": {
                    "status": "fail",
                    "message": err.problem,
                    "fix": err.fix_action,
                }
            },
            "has_issues": True,
        }

    # Calculate summary
    total_checks = len(result.errors) + len(result.warnings)
    agents_with_issues = [k for k, v in agents_data.items() if v.get("has_issues")]
    flows_with_issues = [k for k, v in flows_data.items() if v.get("has_issues")]
    steps_with_issues = [k for k, v in steps_data.items() if v.get("has_issues")]

    return {
        "version": "1.0.0",
        "timestamp": timestamp,
        "summary": {
            "total_checks": total_checks,
            "passed": total_checks - len(result.errors),
            "failed": len(result.errors),
            "warnings": len(result.warnings),
            "status": "PASS" if not result.has_errors() else "FAIL",
            "agents_with_issues": agents_with_issues,
            "flows_with_issues": flows_with_issues,
            "steps_with_issues": steps_with_issues,
        },
        "agents": agents_data,
        "flows": flows_data,
        "steps": steps_data,
        "skills": skills_data,
        "errors": [e.to_dict() for e in result.sorted_errors()],
        "warnings": [w.to_dict() for w in result.sorted_warnings()],
    }


def build_report_json(result: ValidationResult) -> Dict[str, Any]:
    """Build simplified FR-012 report JSON.

    This format is designed for machine consumption with a simpler schema
    than the detailed --json output.
    """
    checks = [
        "agent_bijection",
        "frontmatter",
        "flow_references",
        "skills",
        "runbase_paths",
    ]

    errors_list: list[dict[str, Any]] = []
    for error in result.sorted_errors():
        errors_list.append({
            "type": error.error_type,
            "file": error.file_path or error.location,
            "location": error.location,
            "line": error.line_number,
            "message": error.problem,
            "suggestions": [error.fix_action] if error.fix_action else [],
        })

    warnings_list: list[dict[str, Any]] = []
    for warning in result.sorted_warnings():
        warnings_list.append({
            "type": warning.error_type,
            "file": warning.file_path or warning.location,
            "location": warning.location,
            "line": warning.line_number,
            "message": warning.problem,
            "suggestions": [warning.fix_action] if warning.fix_action else [],
        })

    total_checks = len(result.errors) + len(result.warnings)
    passed = len(result.warnings)  # Warnings don't fail
    failed = len(result.errors)

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "status": "PASSED" if not result.has_errors() else "FAILED",
        "checks": checks,
        "total_checks": total_checks if total_checks > 0 else len(checks),
        "passed": passed,
        "failed": failed,
        "errors": errors_list,
        "warnings": warnings_list,
    }


def build_report_markdown(result: ValidationResult) -> str:
    """Build markdown validation report.

    Generates a human-readable markdown report with title, status,
    checks performed, and any errors/warnings.
    """
    lines: list[str] = []

    # Title and summary
    lines.append("# Swarm Validation Report")
    lines.append("")
    lines.append(f"**Timestamp**: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    lines.append(f"**Status**: {'PASSED' if not result.has_errors() else 'FAILED'}")
    lines.append("")

    # Checks performed
    checks = [
        ("Agent Registry Bijection", "BIJECTION"),
        ("Frontmatter Validation", "FRONTMATTER"),
        ("Flow References", "REFERENCE"),
        ("Skills Validation", "SKILL"),
        ("RUN_BASE Paths", "RUNBASE"),
    ]

    lines.append("## Checks Performed")
    lines.append("")
    for name, error_type in checks:
        has_error = any(e.error_type == error_type for e in result.errors)
        marker = "[ ]" if has_error else "[x]"
        lines.append(f"- {marker} {name}")
    lines.append("")

    # Errors section
    error_count = len(result.errors)
    lines.append(f"## Errors ({error_count})")
    lines.append("")

    if error_count == 0:
        lines.append("_No errors found._")
    else:
        for error in result.sorted_errors():
            lines.append(f"### {error.error_type}")
            lines.append(f"**Location**: {error.location}")
            lines.append(f"**Error**: {error.problem}")
            if error.fix_action:
                lines.append(f"**Fix**: {error.fix_action}")
            lines.append("")

    lines.append("")

    # Warnings section
    warning_count = len(result.warnings)
    lines.append(f"## Warnings ({warning_count})")
    lines.append("")

    if warning_count == 0:
        lines.append("_No warnings._")
    else:
        for warning in result.sorted_warnings():
            lines.append(f"### {warning.error_type}")
            lines.append(f"**Location**: {warning.location}")
            lines.append(f"**Warning**: {warning.problem}")
            if warning.fix_action:
                lines.append(f"**Fix**: {warning.fix_action}")
            lines.append("")

    return "\n".join(lines)


def print_json_output(result: ValidationResult, registry: Dict[str, Dict[str, Any]]) -> None:
    """Print JSON output to stdout."""
    output = build_detailed_json_output(result, registry)
    print(json.dumps(output, indent=2))


# ============================================================================
# CLI and Main
# ============================================================================

def print_success(result: ValidationResult) -> None:
    """Print success message to stdout, including warnings if any."""
    print("Swarm validation PASSED.")
    print("  [PASS] All agents conform to Claude Code platform spec")
    print("  [PASS] All agents follow swarm design constraints")
    print("  [PASS] Flow specs reference valid agents")

    # Print warnings if any (they don't fail validation)
    if result.has_warnings():
        warnings_by_type: Dict[str, List[ValidationError]] = defaultdict(list)
        for warning in result.sorted_warnings():
            warnings_by_type[warning.error_type].append(warning)

        print("\n", file=sys.stderr)
        print("=" * 70, file=sys.stderr)
        print("WARNINGS (design guidelines, not errors):", file=sys.stderr)
        print("=" * 70, file=sys.stderr)

        for warn_type in sorted(warnings_by_type.keys()):
            warnings = warnings_by_type[warn_type]
            print(f"\n{warn_type} Warnings ({len(warnings)}):", file=sys.stderr)
            for warning in warnings:
                print(warning.format().replace("[FAIL]", "[WARN]"), file=sys.stderr)

        print("\nNote: Warnings indicate swarm design guideline violations.", file=sys.stderr)
        print("      Use --strict flag to treat warnings as errors.", file=sys.stderr)


def print_errors(result: ValidationResult) -> None:
    """Print errors and warnings to stderr in deterministic order."""
    # Group errors by type
    by_type: Dict[str, List[ValidationError]] = defaultdict(list)
    for error in result.sorted_errors():
        by_type[error.error_type].append(error)

    # Print errors grouped by type
    for error_type in sorted(by_type.keys()):
        errors = by_type[error_type]
        print(f"\n{error_type} Errors ({len(errors)}):", file=sys.stderr)
        print("=" * 70, file=sys.stderr)
        for error in errors:
            print(error.format(), file=sys.stderr)

    # Print warnings if any
    if result.has_warnings():
        warnings_by_type: Dict[str, List[ValidationError]] = defaultdict(list)
        for warning in result.sorted_warnings():
            warnings_by_type[warning.error_type].append(warning)

        print("\n", file=sys.stderr)
        print("=" * 70, file=sys.stderr)
        print("WARNINGS (design guidelines, not errors):", file=sys.stderr)
        print("=" * 70, file=sys.stderr)

        for warn_type in sorted(warnings_by_type.keys()):
            warnings = warnings_by_type[warn_type]
            print(f"\n{warn_type} Warnings ({len(warnings)}):", file=sys.stderr)
            for warning in warnings:
                print(warning.format().replace("[FAIL]", "[WARN]"), file=sys.stderr)

        print("\nNote: Warnings indicate swarm design guideline violations.", file=sys.stderr)
        print("      Use --strict flag to treat warnings as errors.", file=sys.stderr)

    print(f"\nSwarm validation FAILED ({len(result.errors)} errors).", file=sys.stderr)


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Swarm alignment validator - validate spec/implementation alignment",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exit Codes:
  0 - All validation checks passed
  1 - Validation failed (spec/implementation misalignment)
  2 - Fatal error (missing required files, parse errors)

Examples:
  uv run swarm/tools/validate_swarm.py
  uv run swarm/tools/validate_swarm.py --check-modified
  uv run swarm/tools/validate_swarm.py --flows-only
  uv run swarm/tools/validate_swarm.py --debug
        """
    )

    parser.add_argument(
        "--check-modified",
        action="store_true",
        help="Only check files modified vs main branch (git-aware mode)"
    )

    parser.add_argument(
        "--flows-only",
        action="store_true",
        help="Only run flow validation checks (skip agent/adapter validation)"
    )

    parser.add_argument(
        "--check-prompts",
        action="store_true",
        help="Validate agent prompt sections (## Inputs, ## Outputs, ## Behavior)"
    )

    parser.add_argument(
        "--strict",
        action="store_true",
        help="Enforce swarm design constraints (tools/permissionMode become errors, not warnings)"
    )

    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug output with timing and validation steps"
    )

    parser.add_argument(
        "--json",
        action="store_true",
        help="Output machine-readable JSON with detailed per-agent/flow/step results"
    )

    parser.add_argument(
        "--report",
        choices=["json", "markdown"],
        help="Output format for validation report (json or markdown)"
    )

    parser.add_argument(
        "--version",
        action="version",
        version="validate_swarm.py 2.1.0"
    )

    args = parser.parse_args()

    # Parse registry first (needed for both validation and JSON output)
    try:
        registry = parse_agents_registry()
    except SystemExit:
        if args.json:
            error_output: Dict[str, Any] = {
                "version": "1.0.0",
                "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "summary": {"status": "ERROR", "message": "Failed to parse agent registry"},
                "agents": {},
                "flows": {},
                "steps": {},
                "errors": [],
                "warnings": [],
            }
            print(json.dumps(error_output, indent=2))
        raise

    # Run validation
    try:
        result = run_validation(
            check_modified=args.check_modified,
            debug=args.debug,
            strict_mode=args.strict,
            flows_only=args.flows_only,
            check_prompts=args.check_prompts
        )
    except SystemExit:
        raise
    except Exception as e:
        if args.json:
            error_output: Dict[str, Any] = {
                "version": "1.0.0",
                "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "summary": {"status": "ERROR", "message": f"Unexpected error: {e}"},
                "agents": {},
                "flows": {},
                "steps": {},
                "errors": [],
                "warnings": [],
            }
            print(json.dumps(error_output, indent=2))
            sys.exit(EXIT_FATAL_ERROR)
        print(f"ERROR: Unexpected error during validation: {e}", file=sys.stderr)
        if args.debug:
            import traceback
            traceback.print_exc(file=sys.stderr)
        sys.exit(EXIT_FATAL_ERROR)

    # Report results
    if args.report == "json":
        # Simplified FR-012 JSON report format
        report = build_report_json(result)
        print(json.dumps(report, indent=2))
        sys.exit(EXIT_SUCCESS if not result.has_errors() else EXIT_VALIDATION_FAILED)
    elif args.report == "markdown":
        # Markdown report format
        report = build_report_markdown(result)
        print(report)
        sys.exit(EXIT_SUCCESS if not result.has_errors() else EXIT_VALIDATION_FAILED)
    elif args.json:
        # Detailed JSON output mode - print structured JSON to stdout
        print_json_output(result, registry)
        sys.exit(EXIT_SUCCESS if not result.has_errors() else EXIT_VALIDATION_FAILED)
    elif result.has_errors():
        print_errors(result)
        sys.exit(EXIT_VALIDATION_FAILED)
    else:
        print_success(result)
        sys.exit(EXIT_SUCCESS)


if __name__ == "__main__":
    main()
