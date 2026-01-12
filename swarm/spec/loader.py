"""
loader.py - Load and validate specs from JSON files (JSON-only runtime truth).

The loader reads StationSpecs, FlowSpecs, and Fragments from the spec store.

Primary spec store: swarm/specs/ (JSON files - runtime truth)
Legacy spec store: swarm/spec/ (YAML files - will be deprecated)

The loader prioritizes JSON files from swarm/specs/:
1. Check swarm/specs/stations/<id>.json first
2. Fall back to swarm/spec/stations/<id>.yaml for migration period

For one-time migration from YAML to JSON, use:
    from swarm.spec.loader import migrate_yaml_to_json
    migrate_yaml_to_json()
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from .types import (
    FlowSpec,
    StationSpec,
    flow_spec_from_dict,
    station_spec_from_dict,
)

logger = logging.getLogger(__name__)

# Spec directories relative to repo root
DEFAULT_SPEC_DIR = "swarm/spec"  # Legacy YAML location
DEFAULT_SPECS_DIR = "swarm/specs"  # New JSON location (runtime truth)


def get_repo_root() -> Path:
    """Get repository root path."""
    cwd = Path.cwd()
    for parent in [cwd] + list(cwd.parents):
        if (parent / "swarm").exists():
            return parent
    return cwd


def get_spec_root(repo_root: Optional[Path] = None) -> Path:
    """Get the legacy spec directory root (YAML)."""
    if repo_root:
        return repo_root / DEFAULT_SPEC_DIR
    # Try to find repo root
    cwd = Path.cwd()
    for parent in [cwd] + list(cwd.parents):
        if (parent / "swarm" / "spec").exists():
            return parent / "swarm" / "spec"
    return cwd / DEFAULT_SPEC_DIR


def get_specs_root(repo_root: Optional[Path] = None) -> Path:
    """Get the new specs directory root (JSON - runtime truth)."""
    if repo_root:
        return repo_root / DEFAULT_SPECS_DIR
    root = get_repo_root()
    return root / DEFAULT_SPECS_DIR


# =============================================================================
# Internal Helpers
# =============================================================================


def _load_json_file(path: Path) -> Dict[str, Any]:
    """Load and parse a JSON file."""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not data:
        raise ValueError(f"Empty JSON file: {path}")
    return data


def _load_yaml_file(path: Path) -> Dict[str, Any]:
    """Load and parse a YAML file."""
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not data:
        raise ValueError(f"Empty YAML file: {path}")
    return data


# =============================================================================
# Station Loading
# =============================================================================


def load_station(station_id: str, repo_root: Optional[Path] = None) -> StationSpec:
    """Load a station spec by ID.

    Prioritizes JSON files from swarm/specs/stations/ (runtime truth),
    falls back to YAML from swarm/spec/stations/ for migration period.

    Args:
        station_id: The station identifier (e.g., "code-implementer").
        repo_root: Optional repository root path.

    Returns:
        Parsed StationSpec.

    Raises:
        FileNotFoundError: If station spec file not found.
        ValueError: If spec is invalid.
    """
    # Try JSON first (new spec store - runtime truth)
    specs_root = get_specs_root(repo_root)
    json_path = specs_root / "stations" / f"{station_id}.json"

    if json_path.exists():
        try:
            data = _load_json_file(json_path)
            return station_spec_from_dict(data)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in station spec {json_path}: {e}")

    # Fall back to YAML (legacy spec store)
    spec_root = get_spec_root(repo_root)
    yaml_path = spec_root / "stations" / f"{station_id}.yaml"

    if yaml_path.exists():
        try:
            data = _load_yaml_file(yaml_path)
            logger.debug(
                "Loaded station %s from YAML (migrate to JSON with migrate_yaml_to_json())",
                station_id
            )
            return station_spec_from_dict(data)
        except yaml.YAMLError as e:
            raise ValueError(f"Invalid YAML in station spec {yaml_path}: {e}")

    raise FileNotFoundError(
        f"Station spec not found: {station_id} "
        f"(checked {json_path} and {yaml_path})"
    )


@lru_cache(maxsize=64)
def load_station_cached(station_id: str, repo_root_str: str) -> StationSpec:
    """Cached version of load_station for repeated access."""
    return load_station(station_id, Path(repo_root_str) if repo_root_str else None)


def list_stations(repo_root: Optional[Path] = None) -> List[str]:
    """List all available station IDs.

    Combines stations from both JSON (swarm/specs/) and YAML (swarm/spec/) stores.
    JSON files take precedence if both exist.

    Args:
        repo_root: Optional repository root path.

    Returns:
        List of station IDs (without extension).
    """
    station_ids = set()

    # Check JSON store first (runtime truth)
    specs_root = get_specs_root(repo_root)
    json_stations_dir = specs_root / "stations"
    if json_stations_dir.exists():
        for p in json_stations_dir.glob("*.json"):
            if not p.name.startswith("_"):
                station_ids.add(p.stem)

    # Also check YAML store (legacy)
    spec_root = get_spec_root(repo_root)
    yaml_stations_dir = spec_root / "stations"
    if yaml_stations_dir.exists():
        for p in yaml_stations_dir.glob("*.yaml"):
            if not p.name.startswith("_"):
                station_ids.add(p.stem)

    return sorted(station_ids)


# =============================================================================
# Flow Loading
# =============================================================================


def load_flow(flow_id: str, repo_root: Optional[Path] = None) -> FlowSpec:
    """Load a flow spec by ID.

    Prioritizes JSON files from swarm/specs/flows/ (runtime truth),
    falls back to YAML from swarm/spec/flows/ for migration period.

    Args:
        flow_id: The flow identifier (e.g., "3-build").
        repo_root: Optional repository root path.

    Returns:
        Parsed FlowSpec.

    Raises:
        FileNotFoundError: If flow spec file not found.
        ValueError: If spec is invalid.
    """
    # Try JSON first (new spec store - runtime truth)
    specs_root = get_specs_root(repo_root)
    json_path = specs_root / "flows" / f"{flow_id}.json"

    if json_path.exists():
        try:
            data = _load_json_file(json_path)
            return flow_spec_from_dict(data)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in flow spec {json_path}: {e}")

    # Fall back to YAML (legacy spec store)
    spec_root = get_spec_root(repo_root)
    yaml_path = spec_root / "flows" / f"{flow_id}.yaml"

    if yaml_path.exists():
        try:
            data = _load_yaml_file(yaml_path)
            logger.debug(
                "Loaded flow %s from YAML (migrate to JSON with migrate_yaml_to_json())",
                flow_id
            )
            return flow_spec_from_dict(data)
        except yaml.YAMLError as e:
            raise ValueError(f"Invalid YAML in flow spec {yaml_path}: {e}")

    raise FileNotFoundError(
        f"Flow spec not found: {flow_id} "
        f"(checked {json_path} and {yaml_path})"
    )


@lru_cache(maxsize=16)
def load_flow_cached(flow_id: str, repo_root_str: str) -> FlowSpec:
    """Cached version of load_flow for repeated access."""
    return load_flow(flow_id, Path(repo_root_str) if repo_root_str else None)


def list_flows(repo_root: Optional[Path] = None, include_graph_format: bool = False) -> List[str]:
    """List all available flow IDs.

    Combines flows from both JSON (swarm/specs/) and YAML (swarm/spec/) stores.

    By default, only returns flows in the step-based format (with 'steps' key).
    Graph-format flows (with 'nodes'/'edges' keys) are skipped unless
    include_graph_format=True.

    Args:
        repo_root: Optional repository root path.
        include_graph_format: If True, include graph-format flows from swarm/specs/.

    Returns:
        List of flow IDs (without extension).
    """
    flow_ids = set()

    # Check JSON store (runtime truth)
    specs_root = get_specs_root(repo_root)
    json_flows_dir = specs_root / "flows"
    if json_flows_dir.exists():
        for p in json_flows_dir.glob("*.json"):
            # Skip UI files (flow.ui.json) and hidden files
            if p.name.startswith("_") or p.name.endswith(".ui.json"):
                continue

            if include_graph_format:
                flow_ids.add(p.stem)
            else:
                # Check if this is a step-based flow or graph-based flow
                try:
                    data = _load_json_file(p)
                    # Graph-format flows have 'nodes' key, step-format have 'steps'
                    if "steps" in data and "nodes" not in data:
                        flow_ids.add(p.stem)
                except (json.JSONDecodeError, ValueError):
                    # Skip invalid files
                    pass

    # Also check YAML store (legacy) - always step-based format
    spec_root = get_spec_root(repo_root)
    yaml_flows_dir = spec_root / "flows"
    if yaml_flows_dir.exists():
        for p in yaml_flows_dir.glob("*.yaml"):
            if not p.name.startswith("_"):
                flow_ids.add(p.stem)

    return sorted(flow_ids)


# =============================================================================
# Fragment Loading
# =============================================================================


def load_fragment(fragment_path: str, repo_root: Optional[Path] = None) -> str:
    """Load a prompt fragment by path.

    Checks swarm/specs/fragments/ first (runtime truth),
    falls back to swarm/spec/fragments/ (legacy).

    Args:
        fragment_path: Relative path within fragments/ (e.g., "common/invariants.md").
        repo_root: Optional repository root path.

    Returns:
        Fragment content as string.

    Raises:
        FileNotFoundError: If fragment file not found.
    """
    # Try new specs store first
    specs_root = get_specs_root(repo_root)
    new_path = specs_root / "fragments" / fragment_path
    if new_path.exists():
        return new_path.read_text(encoding="utf-8")

    # Fall back to legacy spec store
    spec_root = get_spec_root(repo_root)
    legacy_path = spec_root / "fragments" / fragment_path
    if legacy_path.exists():
        return legacy_path.read_text(encoding="utf-8")

    raise FileNotFoundError(
        f"Fragment not found: {fragment_path} "
        f"(checked {new_path} and {legacy_path})"
    )


def load_fragments(
    fragment_paths: List[str],
    repo_root: Optional[Path] = None,
    separator: str = "\n\n---\n\n",
) -> str:
    """Load and concatenate multiple fragments.

    Args:
        fragment_paths: List of relative paths within fragments/.
        repo_root: Optional repository root path.
        separator: String to insert between fragments.

    Returns:
        Concatenated content of all fragments.

    Note:
        Missing fragments are logged as warnings but do not raise errors.
        This allows graceful degradation when optional fragments are absent.
    """
    contents: List[str] = []

    for frag_path in fragment_paths:
        try:
            content = load_fragment(frag_path, repo_root)
            if content.strip():
                contents.append(content.strip())
        except FileNotFoundError:
            logger.warning("Fragment not found (skipping): %s", frag_path)

    return separator.join(contents)


@lru_cache(maxsize=64)
def load_fragment_cached(fragment_path: str, repo_root_str: str) -> str:
    """Cached version of load_fragment for repeated access."""
    return load_fragment(fragment_path, Path(repo_root_str) if repo_root_str else None)


def list_fragments(repo_root: Optional[Path] = None) -> List[str]:
    """List all available fragment paths.

    Combines fragments from both JSON (swarm/specs/) and YAML (swarm/spec/) stores.

    Args:
        repo_root: Optional repository root path.

    Returns:
        List of relative fragment paths.
    """
    fragments = set()

    # Check new specs store
    specs_root = get_specs_root(repo_root)
    new_fragments_dir = specs_root / "fragments"
    if new_fragments_dir.exists():
        for md_file in new_fragments_dir.rglob("*.md"):
            rel_path = md_file.relative_to(new_fragments_dir)
            fragments.add(str(rel_path).replace("\\", "/"))

    # Check legacy spec store
    spec_root = get_spec_root(repo_root)
    legacy_fragments_dir = spec_root / "fragments"
    if legacy_fragments_dir.exists():
        for md_file in legacy_fragments_dir.rglob("*.md"):
            rel_path = md_file.relative_to(legacy_fragments_dir)
            fragments.add(str(rel_path).replace("\\", "/"))

    return sorted(fragments)


# =============================================================================
# YAML to JSON Migration
# =============================================================================


def migrate_yaml_to_json(
    repo_root: Optional[Path] = None,
    dry_run: bool = False,
) -> Dict[str, List[str]]:
    """Migrate specs from YAML (swarm/spec/) to JSON (swarm/specs/).

    This is a one-time migration tool. After migration, the loader
    will read from the JSON files.

    Args:
        repo_root: Optional repository root path.
        dry_run: If True, only report what would be migrated.

    Returns:
        Dict with "migrated", "skipped", and "errors" lists.
    """
    try:
        from swarm.runtime.spec_system.canonical import canonical_json
    except ImportError:
        # Fall back to simple JSON serialization if canonical not available
        def canonical_json(obj: Any, indent: int = 2) -> str:
            return json.dumps(obj, indent=indent, sort_keys=True, ensure_ascii=False)

    results: Dict[str, List[str]] = {
        "migrated": [],
        "skipped": [],
        "errors": [],
    }

    spec_root = get_spec_root(repo_root)
    specs_root = get_specs_root(repo_root)

    # Migrate stations
    yaml_stations_dir = spec_root / "stations"
    json_stations_dir = specs_root / "stations"

    if yaml_stations_dir.exists():
        if not dry_run:
            json_stations_dir.mkdir(parents=True, exist_ok=True)

        for yaml_file in yaml_stations_dir.glob("*.yaml"):
            if yaml_file.name.startswith("_"):
                continue

            station_id = yaml_file.stem
            json_file = json_stations_dir / f"{station_id}.json"

            if json_file.exists():
                results["skipped"].append(f"stations/{station_id} (JSON exists)")
                continue

            try:
                data = _load_yaml_file(yaml_file)
                if not dry_run:
                    content = canonical_json(data, indent=2) + "\n"
                    json_file.write_text(content, encoding="utf-8")
                results["migrated"].append(f"stations/{station_id}")
            except Exception as e:
                results["errors"].append(f"stations/{station_id}: {e}")

    # Migrate flows
    yaml_flows_dir = spec_root / "flows"
    json_flows_dir = specs_root / "flows"

    if yaml_flows_dir.exists():
        if not dry_run:
            json_flows_dir.mkdir(parents=True, exist_ok=True)

        for yaml_file in yaml_flows_dir.glob("*.yaml"):
            if yaml_file.name.startswith("_"):
                continue

            flow_id = yaml_file.stem
            json_file = json_flows_dir / f"{flow_id}.json"

            if json_file.exists():
                results["skipped"].append(f"flows/{flow_id} (JSON exists)")
                continue

            try:
                data = _load_yaml_file(yaml_file)
                if not dry_run:
                    content = canonical_json(data, indent=2) + "\n"
                    json_file.write_text(content, encoding="utf-8")
                results["migrated"].append(f"flows/{flow_id}")
            except Exception as e:
                results["errors"].append(f"flows/{flow_id}: {e}")

    return results


# =============================================================================
# Validation
# =============================================================================


def validate_specs(repo_root: Optional[Path] = None) -> Dict[str, List[str]]:
    """Validate all specs in the repository.

    Checks:
    - All spec files (JSON and YAML) parse correctly
    - Required fields are present
    - Station references in flows exist
    - Fragment references exist

    Args:
        repo_root: Optional repository root path.

    Returns:
        Dict with "errors" and "warnings" lists.
    """
    errors: List[str] = []
    warnings: List[str] = []

    specs_root = get_specs_root(repo_root)
    spec_root = get_spec_root(repo_root)

    # Load schema for validation if jsonschema is available
    try:
        import jsonschema
        schema_available = True

        # Try new specs location first, then legacy
        station_schema_path = specs_root / "schemas" / "station.schema.json"
        if not station_schema_path.exists():
            station_schema_path = spec_root / "schemas" / "station.schema.json"

        flow_schema_path = specs_root / "schemas" / "flow.schema.json"
        if not flow_schema_path.exists():
            flow_schema_path = spec_root / "schemas" / "flow.schema.json"

        station_schema = None
        flow_schema = None

        if station_schema_path.exists():
            with open(station_schema_path, "r", encoding="utf-8") as f:
                station_schema = json.load(f)

        if flow_schema_path.exists():
            with open(flow_schema_path, "r", encoding="utf-8") as f:
                flow_schema = json.load(f)

    except ImportError:
        schema_available = False
        station_schema = None
        flow_schema = None
        warnings.append("jsonschema not installed - skipping JSON Schema validation")

    # Validate stations
    station_ids = set()
    for station_id in list_stations(repo_root):
        try:
            station = load_station(station_id, repo_root)
            station_ids.add(station_id)

            # JSON Schema validation - load raw data for validation
            if schema_available and station_schema:
                # Try to load raw data for schema validation
                json_path = specs_root / "stations" / f"{station_id}.json"
                yaml_path = spec_root / "stations" / f"{station_id}.yaml"

                if json_path.exists():
                    raw_data = _load_json_file(json_path)
                elif yaml_path.exists():
                    raw_data = _load_yaml_file(yaml_path)
                else:
                    continue

                try:
                    jsonschema.validate(raw_data, station_schema)
                except jsonschema.ValidationError as ve:
                    errors.append(f"Station {station_id}: Schema validation failed - {ve.message}")

            # Check fragment references
            for frag in station.runtime_prompt.fragments:
                try:
                    load_fragment(frag, repo_root)
                except FileNotFoundError:
                    errors.append(f"Station {station_id}: Fragment not found - {frag}")

        except FileNotFoundError as e:
            errors.append(f"Station {station_id}: {e}")
        except ValueError as e:
            errors.append(f"Station {station_id}: {e}")

    # Validate flows
    for flow_id in list_flows(repo_root):
        try:
            flow = load_flow(flow_id, repo_root)

            # JSON Schema validation - load raw data for validation
            if schema_available and flow_schema:
                json_path = specs_root / "flows" / f"{flow_id}.json"
                yaml_path = spec_root / "flows" / f"{flow_id}.yaml"

                if json_path.exists():
                    raw_data = _load_json_file(json_path)
                elif yaml_path.exists():
                    raw_data = _load_yaml_file(yaml_path)
                else:
                    continue

                try:
                    jsonschema.validate(raw_data, flow_schema)
                except jsonschema.ValidationError as ve:
                    errors.append(f"Flow {flow_id}: Schema validation failed - {ve.message}")

            # Check station references
            for step in flow.steps:
                if step.station not in station_ids:
                    errors.append(f"Flow {flow_id}, step {step.id}: Unknown station - {step.station}")

            # Check routing consistency
            step_ids = {s.id for s in flow.steps}
            for step in flow.steps:
                if step.routing.next and step.routing.next not in step_ids:
                    errors.append(f"Flow {flow_id}, step {step.id}: Unknown next step - {step.routing.next}")
                if step.routing.loop_target and step.routing.loop_target not in step_ids:
                    errors.append(f"Flow {flow_id}, step {step.id}: Unknown loop_target - {step.routing.loop_target}")

        except FileNotFoundError as e:
            errors.append(f"Flow {flow_id}: {e}")
        except ValueError as e:
            errors.append(f"Flow {flow_id}: {e}")

    return {"errors": errors, "warnings": warnings}


# =============================================================================
# CLI Entry Point
# =============================================================================


def main():
    """CLI entry point for spec validation and listing."""
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Spec loader CLI")
    parser.add_argument("command", choices=["lint", "list", "render", "migrate"],
                        help="Command to run")
    parser.add_argument("--type", choices=["stations", "flows", "fragments"],
                        help="Type to list")
    parser.add_argument("--station", help="Station ID for render")
    parser.add_argument("--flow", help="Flow ID for render")
    parser.add_argument("--step", help="Step ID for render")
    parser.add_argument("--dry-run", action="store_true",
                        help="For migrate: show what would be migrated")

    args = parser.parse_args()

    if args.command == "lint":
        results = validate_specs()
        for warning in results["warnings"]:
            print(f"WARNING: {warning}")
        for error in results["errors"]:
            print(f"ERROR: {error}")

        if results["errors"]:
            print(f"\n{len(results['errors'])} error(s) found")
            sys.exit(1)
        else:
            print("All specs valid")
            sys.exit(0)

    elif args.command == "list":
        if args.type == "stations":
            for s in list_stations():
                print(s)
        elif args.type == "flows":
            for f in list_flows():
                print(f)
        elif args.type == "fragments":
            for f in list_fragments():
                print(f)
        else:
            print("Stations:")
            for s in list_stations():
                print(f"  {s}")
            print("\nFlows:")
            for f in list_flows():
                print(f"  {f}")
            print("\nFragments:")
            for f in list_fragments():
                print(f"  {f}")

    elif args.command == "migrate":
        results = migrate_yaml_to_json(dry_run=args.dry_run)
        prefix = "[DRY RUN] " if args.dry_run else ""

        if results["migrated"]:
            print(f"{prefix}Migrated:")
            for item in results["migrated"]:
                print(f"  {item}")

        if results["skipped"]:
            print(f"\n{prefix}Skipped:")
            for item in results["skipped"]:
                print(f"  {item}")

        if results["errors"]:
            print(f"\n{prefix}Errors:")
            for item in results["errors"]:
                print(f"  {item}")
            sys.exit(1)

        print(f"\n{prefix}Migration complete: {len(results['migrated'])} files")

    elif args.command == "render":
        if not args.station:
            print("--station required for render")
            sys.exit(1)
        # Render will be implemented in compiler
        print("Render not yet implemented - use spec_compiler")


if __name__ == "__main__":
    main()
