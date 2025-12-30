"""
station_library.py - Registry of available stations and templates.

This module provides a StationLibrary that aggregates stations from:
1. Default pack (built-in stations shipped with the system)
2. Repo pack (custom stations defined in the repository)
3. Installed packs (optional external packs)

The library is used by:
- EXTEND_GRAPH validation: ensure proposed targets exist
- Node resolution: get execution specs for stations
- UI: display available stations for flow editing

Usage:
    from swarm.runtime.station_library import StationLibrary, load_station_library

    # Load library from repo
    library = load_station_library(repo_root)

    # Validate a station exists
    if library.has_station("clarifier"):
        spec = library.get_station("clarifier")

    # Get all stations for a category
    sidequests = library.get_stations_by_category("sidequest")
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set, Tuple

import yaml

if TYPE_CHECKING:
    from swarm.spec import types as compiler_types

logger = logging.getLogger(__name__)


@dataclass
class StationSpec:
    """Specification for a station/template.

    Attributes:
        station_id: Unique identifier for this station.
        name: Human-readable name.
        description: What this station does.
        category: Category (sidequest, worker, critic, etc.).
        version: Spec version number.

        # Execution config (enriched schema)
        sdk: SDK configuration (model, tools, permissions, etc.).
        identity: Identity configuration (system_append, tone).
        io: Input/output contract (required/optional inputs/outputs).
        handoff: Handoff contract (path_template, required_fields).
        runtime_prompt: Runtime prompt configuration (fragments, template).
        invariants: List of invariant strings.
        routing_hints: Default routing behavior (on_verified, on_unverified, etc.).

        # Existing fields
        agent_key: Default agent to execute.
        template_id: Template identifier if different from station_id.
        params_schema: JSON Schema for parameters (optional).
        default_params: Default parameter values.
        tags: Tags for filtering/search.
        pack_origin: Which pack this station came from.
    """

    station_id: str
    name: str
    description: str = ""
    category: str = "general"
    version: int = 1

    # Execution config (enriched schema)
    sdk: Dict[str, Any] = field(default_factory=dict)
    identity: Dict[str, Any] = field(default_factory=dict)
    io: Dict[str, Any] = field(default_factory=dict)
    handoff: Dict[str, Any] = field(default_factory=dict)
    runtime_prompt: Dict[str, Any] = field(default_factory=dict)
    invariants: List[str] = field(default_factory=list)
    routing_hints: Dict[str, Any] = field(default_factory=dict)

    # Existing fields
    agent_key: Optional[str] = None
    template_id: Optional[str] = None
    params_schema: Dict[str, Any] = field(default_factory=dict)
    default_params: Dict[str, Any] = field(default_factory=dict)
    tags: List[str] = field(default_factory=list)
    pack_origin: str = "default"

    # Source tracking for write operations
    source_file: Optional[str] = None  # Absolute path to source file
    source_index: int = -1  # Index in file if file contains a list, -1 for single


def station_spec_to_dict(spec: StationSpec, include_metadata: bool = False) -> Dict[str, Any]:
    """Convert StationSpec to dictionary.

    Args:
        spec: The StationSpec to convert.
        include_metadata: If True, include source_file and source_index for write operations.

    Returns:
        Dictionary representation of the spec.
    """
    result = {
        "station_id": spec.station_id,
        "name": spec.name,
        "description": spec.description,
        "category": spec.category,
        "version": spec.version,
        # Enriched schema fields
        "sdk": dict(spec.sdk) if spec.sdk else {},
        "identity": dict(spec.identity) if spec.identity else {},
        "io": dict(spec.io) if spec.io else {},
        "handoff": dict(spec.handoff) if spec.handoff else {},
        "runtime_prompt": dict(spec.runtime_prompt) if spec.runtime_prompt else {},
        "invariants": list(spec.invariants) if spec.invariants else [],
        "routing_hints": dict(spec.routing_hints) if spec.routing_hints else {},
        # Existing fields
        "agent_key": spec.agent_key,
        "template_id": spec.template_id,
        "params_schema": spec.params_schema,
        "default_params": spec.default_params,
        "tags": list(spec.tags),
        "pack_origin": spec.pack_origin,
    }
    if include_metadata:
        result["source_file"] = spec.source_file
        result["source_index"] = spec.source_index
    return result


def station_spec_from_dict(
    data: Dict[str, Any],
    source_file: Optional[str] = None,
    source_index: int = -1,
) -> StationSpec:
    """Parse StationSpec from dictionary.

    Backward compatible: if new fields are missing, uses sensible defaults.

    Args:
        data: Dictionary containing station spec data.
        source_file: Optional path to the source file.
        source_index: Index in file if file contains a list, -1 for single.

    Returns:
        StationSpec instance.
    """
    return StationSpec(
        station_id=data.get("station_id", data.get("id", "")),
        name=data.get("name", data.get("title", data.get("station_id", data.get("id", "")))),
        description=data.get("description", ""),
        category=data.get("category", "general"),
        version=data.get("version", 1),
        # Enriched schema fields (defaults to empty if not present)
        sdk=dict(data.get("sdk", {})),
        identity=dict(data.get("identity", {})),
        io=dict(data.get("io", {})),
        handoff=dict(data.get("handoff", {})),
        runtime_prompt=dict(data.get("runtime_prompt", {})),
        invariants=list(data.get("invariants", [])),
        routing_hints=dict(data.get("routing_hints", {})),
        # Existing fields
        agent_key=data.get("agent_key"),
        template_id=data.get("template_id"),
        params_schema=data.get("params_schema", {}),
        default_params=data.get("default_params", {}),
        tags=list(data.get("tags", [])),
        pack_origin=data.get("pack_origin", "default"),
        # Source tracking
        source_file=source_file,
        source_index=source_index,
    )


def to_compiler_spec(spec: StationSpec) -> "compiler_types.StationSpec":
    """Convert a StationLibrary StationSpec to the compiler's StationSpec.

    This bridges the runtime's StationSpec (used for library management)
    to the compiler's StationSpec (used for prompt compilation and execution).

    Args:
        spec: StationLibrary StationSpec instance.

    Returns:
        Compiler StationSpec instance suitable for prompt compilation.
    """
    from swarm.spec.types import station_spec_from_dict as compiler_from_dict

    return compiler_from_dict(
        {
            "id": spec.station_id,
            "version": spec.version,
            "title": spec.name,
            "category": spec.category,
            "sdk": spec.sdk,
            "identity": spec.identity,
            "io": spec.io,
            "handoff": spec.handoff,
            "runtime_prompt": spec.runtime_prompt,
            "invariants": spec.invariants,
            "routing_hints": spec.routing_hints,
        }
    )


# =============================================================================
# Default Pack Stations
# =============================================================================

# These are the built-in stations that ship with the system.
# They provide core sidequest and utility functionality.

# Default SDK configuration for sidequest stations
_DEFAULT_SDK_SIDEQUEST = {
    "model": "sonnet",
    "permission_mode": "bypassPermissions",
    "allowed_tools": ["Read", "Write", "Edit", "Bash", "Grep", "Glob"],
    "denied_tools": [],
    "max_turns": 8,
    "sandbox": {"enabled": True, "auto_allow_bash": True},
    "context_budget": {"total_chars": 150000, "recent_chars": 50000, "older_chars": 10000},
}

# Default SDK configuration for worker stations
_DEFAULT_SDK_WORKER = {
    "model": "sonnet",
    "permission_mode": "bypassPermissions",
    "allowed_tools": ["Read", "Write", "Edit", "Bash", "Grep", "Glob"],
    "denied_tools": [],
    "max_turns": 12,
    "sandbox": {"enabled": True, "auto_allow_bash": True},
    "context_budget": {"total_chars": 200000, "recent_chars": 60000, "older_chars": 10000},
}

# Default SDK configuration for critic stations
_DEFAULT_SDK_CRITIC = {
    "model": "sonnet",
    "permission_mode": "bypassPermissions",
    "allowed_tools": ["Read", "Grep", "Glob"],
    "denied_tools": ["Write", "Edit", "Bash"],
    "max_turns": 6,
    "sandbox": {"enabled": True, "auto_allow_bash": False},
    "context_budget": {"total_chars": 150000, "recent_chars": 50000, "older_chars": 10000},
}

# Default routing hints
_DEFAULT_ROUTING_HINTS = {
    "on_verified": "advance",
    "on_unverified": "loop",
    "on_partial": "advance_with_concerns",
    "on_blocked": "escalate",
}

# Default handoff configuration
_DEFAULT_HANDOFF = {
    "path_template": "{{run.base}}/handoff/{{step.id}}.draft.json",
    "required_fields": ["status", "summary", "artifacts", "can_further_iteration_help"],
}

DEFAULT_STATIONS: List[Dict[str, Any]] = [
    {
        "station_id": "clarifier",
        "name": "Clarifier",
        "description": "Resolve ambiguity by researching context and documenting assumptions",
        "category": "sidequest",
        "version": 1,
        "agent_key": "clarifier",
        "tags": ["sidequest", "research", "assumptions"],
        "sdk": _DEFAULT_SDK_SIDEQUEST,
        "identity": {
            "system_append": "You are the Clarifier. Your job is to resolve ambiguity by researching the codebase and documenting clear assumptions.",
            "tone": "analytical",
        },
        "io": {
            "required_inputs": [],
            "optional_inputs": ["{{run.base}}/signal/problem_statement.md"],
            "required_outputs": ["{{run.base}}/sidequest/clarifications.md"],
            "optional_outputs": [],
        },
        "handoff": _DEFAULT_HANDOFF,
        "runtime_prompt": {"fragments": [], "template": ""},
        "invariants": ["Document all assumptions explicitly", "Never block on ambiguity"],
        "routing_hints": _DEFAULT_ROUTING_HINTS,
    },
    {
        "station_id": "research",
        "name": "Research",
        "description": "Deep dive into codebase or documentation to gather context",
        "category": "sidequest",
        "version": 1,
        "agent_key": "context-loader",
        "tags": ["sidequest", "research", "context"],
        "sdk": _DEFAULT_SDK_SIDEQUEST,
        "identity": {
            "system_append": "You are the Research station. Your job is to deeply explore the codebase and gather comprehensive context.",
            "tone": "analytical",
        },
        "io": {
            "required_inputs": [],
            "optional_inputs": [],
            "required_outputs": ["{{run.base}}/sidequest/research_findings.md"],
            "optional_outputs": [],
        },
        "handoff": _DEFAULT_HANDOFF,
        "runtime_prompt": {"fragments": [], "template": ""},
        "invariants": ["Load 20-50k tokens of relevant context", "Document sources explicitly"],
        "routing_hints": _DEFAULT_ROUTING_HINTS,
    },
    {
        "station_id": "risk-assessment",
        "name": "Risk Assessment",
        "description": "Evaluate risks in current approach and document mitigations",
        "category": "sidequest",
        "version": 1,
        "agent_key": "risk-analyst",
        "tags": ["sidequest", "risk", "analysis"],
        "sdk": _DEFAULT_SDK_SIDEQUEST,
        "identity": {
            "system_append": "You are the Risk Analyst. Your job is to identify and evaluate risks in the current approach.",
            "tone": "analytical",
        },
        "io": {
            "required_inputs": [],
            "optional_inputs": ["{{run.base}}/plan/adr.md"],
            "required_outputs": ["{{run.base}}/sidequest/risk_assessment.md"],
            "optional_outputs": [],
        },
        "handoff": _DEFAULT_HANDOFF,
        "runtime_prompt": {"fragments": [], "template": ""},
        "invariants": ["Assess security, compliance, data, and performance risks"],
        "routing_hints": _DEFAULT_ROUTING_HINTS,
    },
    {
        "station_id": "policy-check",
        "name": "Policy Check",
        "description": "Verify current work against organizational policies",
        "category": "sidequest",
        "version": 1,
        "agent_key": "policy-analyst",
        "tags": ["sidequest", "policy", "compliance"],
        "sdk": _DEFAULT_SDK_SIDEQUEST,
        "identity": {
            "system_append": "You are the Policy Analyst. Your job is to verify work against organizational policies.",
            "tone": "analytical",
        },
        "io": {
            "required_inputs": [],
            "optional_inputs": ["POLICIES.md"],
            "required_outputs": ["{{run.base}}/sidequest/policy_check.md"],
            "optional_outputs": [],
        },
        "handoff": _DEFAULT_HANDOFF,
        "runtime_prompt": {"fragments": [], "template": ""},
        "invariants": ["Check all applicable policies", "Document any violations"],
        "routing_hints": _DEFAULT_ROUTING_HINTS,
    },
    {
        "station_id": "security-review",
        "name": "Security Review",
        "description": "Quick security assessment of changes",
        "category": "sidequest",
        "version": 1,
        "agent_key": "security-scanner",
        "tags": ["sidequest", "security", "review"],
        "sdk": _DEFAULT_SDK_SIDEQUEST,
        "identity": {
            "system_append": "You are the Security Scanner. Your job is to identify security vulnerabilities in changes.",
            "tone": "critical",
        },
        "io": {
            "required_inputs": [],
            "optional_inputs": [],
            "required_outputs": ["{{run.base}}/sidequest/security_review.md"],
            "optional_outputs": [],
        },
        "handoff": _DEFAULT_HANDOFF,
        "runtime_prompt": {"fragments": [], "template": ""},
        "invariants": [
            "Check for common vulnerability patterns",
            "Flag any secrets or credentials",
        ],
        "routing_hints": _DEFAULT_ROUTING_HINTS,
    },
    # Core worker stations (for EXTEND_GRAPH targets)
    {
        "station_id": "code-implementer",
        "name": "Code Implementer",
        "description": "Implement code changes based on specifications",
        "category": "worker",
        "version": 1,
        "agent_key": "code-implementer",
        "tags": ["worker", "implementation", "code"],
        "sdk": _DEFAULT_SDK_WORKER,
        "identity": {
            "system_append": "You are the Code Implementer. Your job is to write production-quality code based on specifications.",
            "tone": "neutral",
        },
        "io": {
            "required_inputs": ["{{run.base}}/plan/work_plan.md"],
            "optional_inputs": ["{{run.base}}/build/test_summary.md"],
            "required_outputs": [],
            "optional_outputs": ["{{run.base}}/build/implementation_notes.md"],
        },
        "handoff": _DEFAULT_HANDOFF,
        "runtime_prompt": {"fragments": [], "template": ""},
        "invariants": ["Follow the work plan", "Write tests alongside code when applicable"],
        "routing_hints": _DEFAULT_ROUTING_HINTS,
    },
    {
        "station_id": "test-author",
        "name": "Test Author",
        "description": "Write tests based on specifications",
        "category": "worker",
        "version": 1,
        "agent_key": "test-author",
        "tags": ["worker", "testing", "code"],
        "sdk": _DEFAULT_SDK_WORKER,
        "identity": {
            "system_append": "You are the Test Author. Your job is to write comprehensive tests based on specifications.",
            "tone": "neutral",
        },
        "io": {
            "required_inputs": ["{{run.base}}/plan/test_plan.md"],
            "optional_inputs": ["{{run.base}}/signal/bdd_scenarios.md"],
            "required_outputs": ["{{run.base}}/build/test_summary.md"],
            "optional_outputs": [],
        },
        "handoff": _DEFAULT_HANDOFF,
        "runtime_prompt": {"fragments": [], "template": ""},
        "invariants": ["Cover all BDD scenarios", "Include edge cases"],
        "routing_hints": _DEFAULT_ROUTING_HINTS,
    },
    {
        "station_id": "code-critic",
        "name": "Code Critic",
        "description": "Review code implementation for issues",
        "category": "critic",
        "version": 1,
        "agent_key": "code-critic",
        "tags": ["critic", "review", "code"],
        "sdk": _DEFAULT_SDK_CRITIC,
        "identity": {
            "system_append": "You are the Code Critic. Your job is to provide harsh, thorough critique of code implementations.",
            "tone": "critical",
        },
        "io": {
            "required_inputs": [],
            "optional_inputs": ["{{run.base}}/plan/adr.md"],
            "required_outputs": ["{{run.base}}/build/code_critique.md"],
            "optional_outputs": [],
        },
        "handoff": _DEFAULT_HANDOFF,
        "runtime_prompt": {"fragments": [], "template": ""},
        "invariants": ["Never fix code yourself", "Provide actionable critique"],
        "routing_hints": {
            "on_verified": "advance",
            "on_unverified": "loop",
            "on_partial": "loop",
            "on_blocked": "escalate",
        },
    },
    {
        "station_id": "test-critic",
        "name": "Test Critic",
        "description": "Review test implementation for coverage and quality",
        "category": "critic",
        "version": 1,
        "agent_key": "test-critic",
        "tags": ["critic", "review", "testing"],
        "sdk": _DEFAULT_SDK_CRITIC,
        "identity": {
            "system_append": "You are the Test Critic. Your job is to critique test coverage and quality.",
            "tone": "critical",
        },
        "io": {
            "required_inputs": ["{{run.base}}/build/test_summary.md"],
            "optional_inputs": ["{{run.base}}/signal/bdd_scenarios.md"],
            "required_outputs": ["{{run.base}}/build/test_critique.md"],
            "optional_outputs": [],
        },
        "handoff": _DEFAULT_HANDOFF,
        "runtime_prompt": {"fragments": [], "template": ""},
        "invariants": ["Never write tests yourself", "Check BDD coverage"],
        "routing_hints": {
            "on_verified": "advance",
            "on_unverified": "loop",
            "on_partial": "loop",
            "on_blocked": "escalate",
        },
    },
]


class StationLibrary:
    """Registry of available stations and templates.

    The library aggregates stations from multiple sources:
    1. Default pack (built-in)
    2. Repo pack (swarm/packs/ or swarm/specs/stations/)
    3. Installed packs (optional)

    Usage:
        library = StationLibrary()
        library.load_default_pack()
        library.load_repo_pack(repo_root)

        if library.has_station("clarifier"):
            spec = library.get_station("clarifier")
    """

    def __init__(self):
        """Initialize an empty station library."""
        self._stations: Dict[str, StationSpec] = {}
        self._by_category: Dict[str, List[str]] = {}
        self._by_tag: Dict[str, Set[str]] = {}
        self._repo_root: Optional[Path] = None

    def load_default_pack(self) -> int:
        """Load built-in default stations.

        Returns:
            Number of stations loaded.
        """
        count = 0
        for station_data in DEFAULT_STATIONS:
            spec = station_spec_from_dict(station_data)
            spec.pack_origin = "default"
            self._register_station(spec)
            count += 1

        logger.info("Loaded %d default stations", count)
        return count

    def load_repo_pack(self, repo_root: Path) -> int:
        """Load stations from repository pack.

        Looks for stations in:
        - swarm/packs/stations/*.yaml
        - swarm/packs/stations/*.json
        - swarm/specs/stations/*.yaml (legacy)

        Args:
            repo_root: Repository root path.

        Returns:
            Number of stations loaded.
        """
        count = 0
        self._repo_root = repo_root

        # Try multiple locations
        pack_dirs = [
            repo_root / "swarm" / "packs" / "stations",
            repo_root / "swarm" / "specs" / "stations",
        ]

        for pack_dir in pack_dirs:
            if not pack_dir.exists():
                continue

            # Load YAML files
            for yaml_file in pack_dir.glob("*.yaml"):
                try:
                    with open(yaml_file, "r") as f:
                        data = yaml.safe_load(f)

                    file_path = str(yaml_file.resolve())
                    if isinstance(data, list):
                        for idx, item in enumerate(data):
                            spec = station_spec_from_dict(
                                item,
                                source_file=file_path,
                                source_index=idx,
                            )
                            spec.pack_origin = f"repo:{pack_dir.name}"
                            self._register_station(spec)
                            count += 1
                    elif isinstance(data, dict):
                        spec = station_spec_from_dict(
                            data,
                            source_file=file_path,
                            source_index=-1,
                        )
                        spec.pack_origin = f"repo:{pack_dir.name}"
                        self._register_station(spec)
                        count += 1
                except Exception as e:
                    logger.warning("Failed to load station from %s: %s", yaml_file, e)

            # Load JSON files
            for json_file in pack_dir.glob("*.json"):
                try:
                    with open(json_file, "r") as f:
                        data = json.load(f)

                    file_path = str(json_file.resolve())
                    if isinstance(data, list):
                        for idx, item in enumerate(data):
                            spec = station_spec_from_dict(
                                item,
                                source_file=file_path,
                                source_index=idx,
                            )
                            spec.pack_origin = f"repo:{pack_dir.name}"
                            self._register_station(spec)
                            count += 1
                    elif isinstance(data, dict):
                        spec = station_spec_from_dict(
                            data,
                            source_file=file_path,
                            source_index=-1,
                        )
                        spec.pack_origin = f"repo:{pack_dir.name}"
                        self._register_station(spec)
                        count += 1
                except Exception as e:
                    logger.warning("Failed to load station from %s: %s", json_file, e)

        if count > 0:
            logger.info("Loaded %d repo stations", count)

        return count

    def _register_station(self, spec: StationSpec) -> None:
        """Register a station in the library.

        Args:
            spec: Station specification to register.
        """
        self._stations[spec.station_id] = spec

        # Index by category
        if spec.category not in self._by_category:
            self._by_category[spec.category] = []
        if spec.station_id not in self._by_category[spec.category]:
            self._by_category[spec.category].append(spec.station_id)

        # Index by tags
        for tag in spec.tags:
            if tag not in self._by_tag:
                self._by_tag[tag] = set()
            self._by_tag[tag].add(spec.station_id)

    def has_station(self, station_id: str) -> bool:
        """Check if a station exists in the library.

        Args:
            station_id: Station ID to check.

        Returns:
            True if station exists.
        """
        return station_id in self._stations

    def get_station(self, station_id: str) -> Optional[StationSpec]:
        """Get a station specification.

        Args:
            station_id: Station ID to retrieve.

        Returns:
            StationSpec if found, None otherwise.
        """
        return self._stations.get(station_id)

    def get_compiler_spec(self, station_id: str) -> "compiler_types.StationSpec":
        """Get a station spec in compiler format.

        This converts the runtime StationSpec to the compiler's StationSpec
        type, suitable for prompt compilation and SDK execution.

        Args:
            station_id: Station ID to retrieve.

        Returns:
            Compiler StationSpec instance.

        Raises:
            ValueError: If station not found.
        """
        spec = self.get_station(station_id)
        if not spec:
            raise ValueError(f"Station not found: {station_id}")
        return to_compiler_spec(spec)

    def get_stations_by_category(self, category: str) -> List[StationSpec]:
        """Get all stations in a category.

        Args:
            category: Category to filter by.

        Returns:
            List of station specs in that category.
        """
        station_ids = self._by_category.get(category, [])
        return [self._stations[sid] for sid in station_ids if sid in self._stations]

    def get_stations_by_tag(self, tag: str) -> List[StationSpec]:
        """Get all stations with a tag.

        Args:
            tag: Tag to filter by.

        Returns:
            List of station specs with that tag.
        """
        station_ids = self._by_tag.get(tag, set())
        return [self._stations[sid] for sid in station_ids if sid in self._stations]

    def list_all_stations(self) -> List[StationSpec]:
        """Get all stations in the library.

        Returns:
            List of all station specs.
        """
        return list(self._stations.values())

    def list_station_ids(self) -> List[str]:
        """Get all station IDs.

        Returns:
            List of station IDs.
        """
        return list(self._stations.keys())

    def validate_target(self, target_id: str) -> bool:
        """Validate that a target exists for EXTEND_GRAPH.

        This is the primary validation method used by Navigator
        when evaluating EXTEND_GRAPH proposals.

        Args:
            target_id: The proposed target station/template ID.

        Returns:
            True if the target is valid and can be executed.
        """
        return self.has_station(target_id)

    # =========================================================================
    # Write Operations
    # =========================================================================

    def compute_etag(self, station_id: str) -> str:
        """Compute ETag for a station.

        The ETag is a hash of the station's serialized form, used for
        optimistic concurrency control.

        Args:
            station_id: Station ID to compute ETag for.

        Returns:
            ETag string (first 16 chars of SHA256 hash).

        Raises:
            ValueError: If station not found.
        """
        spec = self.get_station(station_id)
        if not spec:
            raise ValueError(f"Station not found: {station_id}")

        # Serialize to JSON for consistent hashing
        data = station_spec_to_dict(spec)
        content = json.dumps(data, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]

    def get_station_with_etag(self, station_id: str) -> Tuple[Optional[StationSpec], str]:
        """Get a station with its ETag.

        Args:
            station_id: Station ID to retrieve.

        Returns:
            Tuple of (StationSpec, etag) or (None, "") if not found.
        """
        spec = self.get_station(station_id)
        if not spec:
            return None, ""
        return spec, self.compute_etag(station_id)

    def validate_station_data(self, data: Dict[str, Any]) -> List[str]:
        """Validate station data before saving.

        Args:
            data: Station data dictionary.

        Returns:
            List of validation error messages. Empty if valid.
        """
        errors = []

        # Required fields
        if not data.get("station_id") and not data.get("id"):
            errors.append("station_id is required")

        if not data.get("name") and not data.get("title"):
            errors.append("name is required")

        # station_id format (alphanumeric, hyphens, underscores)
        station_id = data.get("station_id") or data.get("id", "")
        if station_id:
            import re

            if not re.match(r"^[a-zA-Z][a-zA-Z0-9_-]*$", station_id):
                errors.append(
                    "station_id must start with a letter and contain only "
                    "alphanumeric characters, hyphens, and underscores"
                )

        # Version must be positive integer
        version = data.get("version", 1)
        if not isinstance(version, int) or version < 1:
            errors.append("version must be a positive integer")

        # Category validation
        valid_categories = {
            "sidequest",
            "worker",
            "critic",
            "general",
            "spec",
            "design",
            "implementation",
        }
        category = data.get("category", "general")
        if category not in valid_categories:
            errors.append(f"category must be one of: {', '.join(sorted(valid_categories))}")

        # SDK validation (if provided)
        sdk = data.get("sdk", {})
        if sdk:
            valid_models = {"inherit", "haiku", "sonnet", "opus"}
            model = sdk.get("model", "sonnet")
            if model not in valid_models:
                errors.append(f"sdk.model must be one of: {', '.join(sorted(valid_models))}")

            max_turns = sdk.get("max_turns")
            if max_turns is not None:
                if not isinstance(max_turns, int) or max_turns < 1:
                    errors.append("sdk.max_turns must be a positive integer")

        return errors

    def create_station(
        self,
        data: Dict[str, Any],
        target_file: Optional[str] = None,
    ) -> Tuple[StationSpec, str]:
        """Create a new station.

        Args:
            data: Station data dictionary.
            target_file: Optional target file path. If not provided,
                creates a new file in swarm/packs/stations/.

        Returns:
            Tuple of (created StationSpec, etag).

        Raises:
            ValueError: If station_id already exists or validation fails.
        """
        # Validate data
        errors = self.validate_station_data(data)
        if errors:
            raise ValueError(f"Validation failed: {'; '.join(errors)}")

        station_id = data.get("station_id") or data.get("id")

        # Check for duplicate
        if self.has_station(station_id):
            raise ValueError(f"Station already exists: {station_id}")

        # Determine target file
        if not target_file:
            if not hasattr(self, "_repo_root") or not self._repo_root:
                raise ValueError("Cannot create station: repo_root not set")

            # Create new file for this station
            pack_dir = self._repo_root / "swarm" / "packs" / "stations"
            pack_dir.mkdir(parents=True, exist_ok=True)
            target_file = str(pack_dir / f"{station_id}.yaml")

        # Create spec from data
        spec = station_spec_from_dict(data, source_file=target_file, source_index=-1)
        spec.pack_origin = "repo:stations"

        # Write to file
        self._write_station_to_file(spec, target_file)

        # Register in library
        self._register_station(spec)

        return spec, self.compute_etag(station_id)

    def update_station(
        self,
        station_id: str,
        data: Dict[str, Any],
        expected_etag: str,
    ) -> Tuple[StationSpec, str]:
        """Replace a station (PUT semantics).

        Args:
            station_id: Station ID to update.
            data: Complete station data.
            expected_etag: Expected ETag for concurrency control.

        Returns:
            Tuple of (updated StationSpec, new etag).

        Raises:
            ValueError: If station not found, ETag mismatch, or validation fails.
        """
        existing = self.get_station(station_id)
        if not existing:
            raise ValueError(f"Station not found: {station_id}")

        # Check ETag
        current_etag = self.compute_etag(station_id)
        if current_etag != expected_etag:
            raise ValueError(f"ETag mismatch: expected {expected_etag}, got {current_etag}")

        # Cannot update default pack stations
        if existing.pack_origin == "default":
            raise ValueError("Cannot update default pack stations")

        # Validate data
        errors = self.validate_station_data(data)
        if errors:
            raise ValueError(f"Validation failed: {'; '.join(errors)}")

        # Ensure station_id in data matches
        data["station_id"] = station_id

        # Create updated spec preserving source info
        spec = station_spec_from_dict(
            data,
            source_file=existing.source_file,
            source_index=existing.source_index,
        )
        spec.pack_origin = existing.pack_origin

        # Write to file
        if spec.source_file:
            self._write_station_to_file(spec, spec.source_file)

        # Re-register (will update indexes)
        self._unregister_station(station_id)
        self._register_station(spec)

        return spec, self.compute_etag(station_id)

    def patch_station(
        self,
        station_id: str,
        patch_data: Dict[str, Any],
        expected_etag: str,
    ) -> Tuple[StationSpec, str]:
        """Partially update a station (PATCH semantics).

        Args:
            station_id: Station ID to update.
            patch_data: Partial station data to merge.
            expected_etag: Expected ETag for concurrency control.

        Returns:
            Tuple of (updated StationSpec, new etag).

        Raises:
            ValueError: If station not found, ETag mismatch, or validation fails.
        """
        existing = self.get_station(station_id)
        if not existing:
            raise ValueError(f"Station not found: {station_id}")

        # Check ETag
        current_etag = self.compute_etag(station_id)
        if current_etag != expected_etag:
            raise ValueError(f"ETag mismatch: expected {expected_etag}, got {current_etag}")

        # Cannot update default pack stations
        if existing.pack_origin == "default":
            raise ValueError("Cannot update default pack stations")

        # Merge existing data with patch
        existing_data = station_spec_to_dict(existing)
        merged_data = self._deep_merge(existing_data, patch_data)

        # Prevent changing station_id
        merged_data["station_id"] = station_id

        # Validate merged data
        errors = self.validate_station_data(merged_data)
        if errors:
            raise ValueError(f"Validation failed: {'; '.join(errors)}")

        # Create updated spec
        spec = station_spec_from_dict(
            merged_data,
            source_file=existing.source_file,
            source_index=existing.source_index,
        )
        spec.pack_origin = existing.pack_origin

        # Write to file
        if spec.source_file:
            self._write_station_to_file(spec, spec.source_file)

        # Re-register
        self._unregister_station(station_id)
        self._register_station(spec)

        return spec, self.compute_etag(station_id)

    def delete_station(
        self,
        station_id: str,
        expected_etag: Optional[str] = None,
    ) -> None:
        """Delete a station.

        Args:
            station_id: Station ID to delete.
            expected_etag: Optional expected ETag for concurrency control.

        Raises:
            ValueError: If station not found, is a default station, or ETag mismatch.
        """
        existing = self.get_station(station_id)
        if not existing:
            raise ValueError(f"Station not found: {station_id}")

        # Check ETag if provided
        if expected_etag:
            current_etag = self.compute_etag(station_id)
            if current_etag != expected_etag:
                raise ValueError(f"ETag mismatch: expected {expected_etag}, got {current_etag}")

        # Cannot delete default pack stations
        if existing.pack_origin == "default":
            raise ValueError("Cannot delete default pack stations")

        # Remove from file
        if existing.source_file:
            self._remove_station_from_file(existing)

        # Unregister from library
        self._unregister_station(station_id)

    def _unregister_station(self, station_id: str) -> None:
        """Remove a station from all indexes.

        Args:
            station_id: Station ID to unregister.
        """
        spec = self._stations.get(station_id)
        if not spec:
            return

        # Remove from main dict
        del self._stations[station_id]

        # Remove from category index
        if spec.category in self._by_category:
            try:
                self._by_category[spec.category].remove(station_id)
            except ValueError:
                pass

        # Remove from tag indexes
        for tag in spec.tags:
            if tag in self._by_tag:
                self._by_tag[tag].discard(station_id)

    def _deep_merge(self, base: Dict[str, Any], patch: Dict[str, Any]) -> Dict[str, Any]:
        """Deep merge two dictionaries.

        Args:
            base: Base dictionary.
            patch: Patch dictionary to merge into base.

        Returns:
            Merged dictionary.
        """
        result = dict(base)
        for key, value in patch.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._deep_merge(result[key], value)
            else:
                result[key] = value
        return result

    def _write_station_to_file(self, spec: StationSpec, file_path: str) -> None:
        """Write a station spec to a file.

        Handles both single-station files and list files.

        Args:
            spec: Station spec to write.
            file_path: Target file path.
        """
        path = Path(file_path)

        # Convert spec to dict (without metadata)
        spec_dict = station_spec_to_dict(spec, include_metadata=False)

        if spec.source_index >= 0:
            # This is a list file - need to read/update/write
            if path.exists():
                with open(path, "r") as f:
                    if path.suffix in (".yaml", ".yml"):
                        data = yaml.safe_load(f) or []
                    else:
                        data = json.load(f)

                if not isinstance(data, list):
                    data = [data]

                # Update or append
                if spec.source_index < len(data):
                    data[spec.source_index] = spec_dict
                else:
                    data.append(spec_dict)
                    # Update the source_index
                    spec.source_index = len(data) - 1
            else:
                data = [spec_dict]
                spec.source_index = 0
        else:
            # Single station file
            data = spec_dict

        # Write to file
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            if path.suffix in (".yaml", ".yml"):
                yaml.dump(
                    data,
                    f,
                    default_flow_style=False,
                    allow_unicode=True,
                    sort_keys=False,
                )
            else:
                json.dump(data, f, indent=2, ensure_ascii=False)

    def _remove_station_from_file(self, spec: StationSpec) -> None:
        """Remove a station from its source file.

        Args:
            spec: Station spec to remove.
        """
        if not spec.source_file:
            return

        path = Path(spec.source_file)
        if not path.exists():
            return

        if spec.source_index >= 0:
            # List file - remove from list
            with open(path, "r") as f:
                if path.suffix in (".yaml", ".yml"):
                    data = yaml.safe_load(f) or []
                else:
                    data = json.load(f)

            if isinstance(data, list) and spec.source_index < len(data):
                data.pop(spec.source_index)

                # Update source_index for all stations that came after this one
                for sid, station in self._stations.items():
                    if (
                        station.source_file == spec.source_file
                        and station.source_index > spec.source_index
                    ):
                        station.source_index -= 1

                if data:
                    # Write remaining data
                    with open(path, "w") as f:
                        if path.suffix in (".yaml", ".yml"):
                            yaml.dump(
                                data,
                                f,
                                default_flow_style=False,
                                allow_unicode=True,
                                sort_keys=False,
                            )
                        else:
                            json.dump(data, f, indent=2, ensure_ascii=False)
                else:
                    # No stations left, remove file
                    path.unlink()
        else:
            # Single station file - just delete it
            path.unlink()

    def to_dict(self) -> Dict[str, Any]:
        """Serialize library state.

        Returns:
            Dictionary representation of the library.
        """
        return {
            "stations": {sid: station_spec_to_dict(spec) for sid, spec in self._stations.items()},
            "categories": dict(self._by_category),
            "tags": {tag: list(ids) for tag, ids in self._by_tag.items()},
        }


def load_station_library(repo_root: Optional[Path] = None) -> StationLibrary:
    """Load a station library with default and repo packs.

    This is the standard way to create a StationLibrary for use
    in the runtime.

    Args:
        repo_root: Optional repository root. If None, only loads defaults.

    Returns:
        Configured StationLibrary instance.
    """
    library = StationLibrary()
    library.load_default_pack()

    if repo_root:
        library.load_repo_pack(repo_root)

    return library


__all__ = [
    "StationSpec",
    "StationLibrary",
    "load_station_library",
    "station_spec_to_dict",
    "station_spec_from_dict",
    "to_compiler_spec",
]
