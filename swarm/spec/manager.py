"""
manager.py - Central SpecManager for spec file management.

The SpecManager is the ONLY component authorized to write spec files.
It provides:
- Schema validation via jsonschema
- Atomic writes with backup
- ETag-based concurrency control (using spec_hash from canonical module)
- Git integration (optional commit on save)
- Compile-to-prompt-plan convenience methods
- Shred/merge overlay behavior (flow.json + flow.ui.json)

This module follows ADR-001 (spec-first architecture) and provides the
central authority for all spec file operations.

The spec store lives at swarm/specs/ (JSON-only runtime truth).
Legacy swarm/spec/ (YAML) is supported for migration but deprecated.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import yaml

# Import canonical JSON utilities
try:
    from swarm.runtime.spec_system.canonical import canonical_json, spec_hash
    CANONICAL_AVAILABLE = True
except ImportError:
    CANONICAL_AVAILABLE = False
    # Fallback implementations
    def canonical_json(obj: Any, indent: int | None = None) -> str:
        if indent is not None:
            separators = (",", ": ")
        else:
            separators = (",", ":")
        return json.dumps(obj, sort_keys=True, separators=separators, ensure_ascii=False, indent=indent)

    def spec_hash(obj: Any, length: int = 12) -> str:
        data = canonical_json(obj).encode("utf-8")
        return hashlib.sha256(data).hexdigest()[:length]


logger = logging.getLogger(__name__)

# Default directories relative to repo root
DEFAULT_SPEC_DIR = "swarm/spec"  # Legacy YAML location
DEFAULT_SPECS_DIR = "swarm/specs"  # New JSON location (runtime truth)
DEFAULT_FLOWS_SUBDIR = "flows"
DEFAULT_STATIONS_SUBDIR = "stations"
DEFAULT_TEMPLATES_SUBDIR = "templates"
DEFAULT_SCHEMAS_SUBDIR = "schemas"


# =============================================================================
# Error Types
# =============================================================================


class SpecError(Exception):
    """Base exception for spec-related errors."""

    pass


class SpecNotFoundError(SpecError):
    """Raised when a requested spec file does not exist."""

    def __init__(self, spec_type: str, spec_id: str, path: Optional[Path] = None):
        self.spec_type = spec_type
        self.spec_id = spec_id
        self.path = path
        msg = f"{spec_type} '{spec_id}' not found"
        if path:
            msg += f" at {path}"
        super().__init__(msg)


class SpecValidationError(SpecError):
    """Raised when spec data fails schema validation."""

    def __init__(self, spec_type: str, errors: List["ValidationError"]):
        self.spec_type = spec_type
        self.errors = errors
        error_msgs = "; ".join(str(e) for e in errors)
        super().__init__(f"{spec_type} validation failed: {error_msgs}")


class ConcurrencyError(SpecError):
    """Raised when ETag mismatch indicates concurrent modification."""

    def __init__(self, spec_type: str, spec_id: str, expected_etag: str, actual_etag: str):
        self.spec_type = spec_type
        self.spec_id = spec_id
        self.expected_etag = expected_etag
        self.actual_etag = actual_etag
        super().__init__(
            f"{spec_type} '{spec_id}' was modified by another process. "
            f"Expected ETag: {expected_etag}, Actual: {actual_etag}"
        )


# =============================================================================
# Validation Types
# =============================================================================


@dataclass
class ValidationError:
    """Structured validation error."""

    path: str  # JSON path to the error location
    message: str  # Human-readable error message
    schema_path: Optional[str] = None  # Path in schema where validation failed
    value: Optional[Any] = None  # The invalid value

    def __str__(self) -> str:
        if self.path:
            return f"[{self.path}] {self.message}"
        return self.message


@dataclass
class ValidationResult:
    """Result of spec validation."""

    valid: bool
    errors: List[ValidationError] = field(default_factory=list)
    warnings: List[ValidationError] = field(default_factory=list)

    def __bool__(self) -> bool:
        return self.valid


# =============================================================================
# Data Types for Spec Objects
# =============================================================================


@dataclass
class FlowGraph:
    """Flow graph specification data.

    Corresponds to flow_graph.schema.json.
    """

    id: str
    version: int
    title: str
    flow_number: int
    nodes: List[Dict[str, Any]]
    edges: List[Dict[str, Any]]
    description: str = ""
    policy: Optional[Dict[str, Any]] = None
    subflows: Optional[List[Dict[str, Any]]] = None
    defaults: Optional[Dict[str, Any]] = None
    on_complete: Optional[Dict[str, Any]] = None
    on_failure: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None
    _etag: Optional[str] = None  # Computed ETag for concurrency control

    @classmethod
    def from_dict(cls, data: Dict[str, Any], etag: Optional[str] = None) -> "FlowGraph":
        """Create FlowGraph from dictionary."""
        return cls(
            id=data["id"],
            version=data["version"],
            title=data["title"],
            flow_number=data["flow_number"],
            nodes=data.get("nodes", []),
            edges=data.get("edges", []),
            description=data.get("description", ""),
            policy=data.get("policy"),
            subflows=data.get("subflows"),
            defaults=data.get("defaults"),
            on_complete=data.get("on_complete"),
            on_failure=data.get("on_failure"),
            metadata=data.get("metadata"),
            _etag=etag,
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        result = {
            "id": self.id,
            "version": self.version,
            "title": self.title,
            "flow_number": self.flow_number,
            "nodes": self.nodes,
            "edges": self.edges,
        }
        if self.description:
            result["description"] = self.description
        if self.policy:
            result["policy"] = self.policy
        if self.subflows:
            result["subflows"] = self.subflows
        if self.defaults:
            result["defaults"] = self.defaults
        if self.on_complete:
            result["on_complete"] = self.on_complete
        if self.on_failure:
            result["on_failure"] = self.on_failure
        if self.metadata:
            result["metadata"] = self.metadata
        return result

    @property
    def etag(self) -> Optional[str]:
        """Get the computed ETag."""
        return self._etag


@dataclass
class StepTemplate:
    """Step template specification data.

    Corresponds to step_template.schema.json.
    """

    id: str
    version: int
    title: str
    station_id: str
    objective: Dict[str, Any]
    description: str = ""
    station_version: Optional[int] = None
    io_overrides: Optional[Dict[str, Any]] = None
    routing_defaults: Optional[Dict[str, Any]] = None
    ui_defaults: Optional[Dict[str, Any]] = None
    constraints: Optional[Dict[str, Any]] = None
    parameters: Optional[Dict[str, Any]] = None
    tags: Optional[List[str]] = None
    category: Optional[str] = None
    deprecated: bool = False
    replaced_by: Optional[str] = None
    _etag: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any], etag: Optional[str] = None) -> "StepTemplate":
        """Create StepTemplate from dictionary."""
        return cls(
            id=data["id"],
            version=data["version"],
            title=data["title"],
            station_id=data["station_id"],
            objective=data["objective"],
            description=data.get("description", ""),
            station_version=data.get("station_version"),
            io_overrides=data.get("io_overrides"),
            routing_defaults=data.get("routing_defaults"),
            ui_defaults=data.get("ui_defaults"),
            constraints=data.get("constraints"),
            parameters=data.get("parameters"),
            tags=data.get("tags"),
            category=data.get("category"),
            deprecated=data.get("deprecated", False),
            replaced_by=data.get("replaced_by"),
            _etag=etag,
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        result = {
            "id": self.id,
            "version": self.version,
            "title": self.title,
            "station_id": self.station_id,
            "objective": self.objective,
        }
        if self.description:
            result["description"] = self.description
        if self.station_version:
            result["station_version"] = self.station_version
        if self.io_overrides:
            result["io_overrides"] = self.io_overrides
        if self.routing_defaults:
            result["routing_defaults"] = self.routing_defaults
        if self.ui_defaults:
            result["ui_defaults"] = self.ui_defaults
        if self.constraints:
            result["constraints"] = self.constraints
        if self.parameters:
            result["parameters"] = self.parameters
        if self.tags:
            result["tags"] = self.tags
        if self.category:
            result["category"] = self.category
        if self.deprecated:
            result["deprecated"] = self.deprecated
        if self.replaced_by:
            result["replaced_by"] = self.replaced_by
        return result

    @property
    def etag(self) -> Optional[str]:
        """Get the computed ETag."""
        return self._etag


# =============================================================================
# SpecManager
# =============================================================================


class SpecManager:
    """Central manager for spec file operations.

    The SpecManager is the ONLY authorized writer of spec files.
    All spec modifications should go through this class to ensure:
    - Schema validation
    - Atomic writes with backup
    - ETag-based concurrency control
    - Optional git integration
    - Shred/merge overlay behavior (flow.json + flow.ui.json)

    The spec store lives at swarm/specs/ (JSON-only runtime truth).

    Usage:
        manager = SpecManager(repo_root=Path("/path/to/repo"))

        # Read specs (with overlay merge)
        flow = manager.get_flow_with_ui("3-build")  # Merges flow.json + flow.ui.json

        # Read specs
        graph = manager.get_flow_graph("build-flow")
        template = manager.get_step_template("code-critic-template")

        # Validate
        errors = manager.validate_spec("flow_graph", graph_data)

        # Write with concurrency control
        new_etag = manager.save_flow_graph("build-flow", graph_data, etag=old_etag)

        # Write with shred (splits into flow.json + flow.ui.json)
        manager.save_flow_with_ui("3-build", data, ui_data=ui_overlay)

        # Compile to prompt plan
        plan = manager.compile_to_prompt_plan("3-build")
    """

    def __init__(
        self,
        repo_root: Optional[Path] = None,
        spec_dir: Optional[Path] = None,
        specs_dir: Optional[Path] = None,
        enable_git: bool = False,
        backup_on_write: bool = True,
    ):
        """Initialize the SpecManager.

        Args:
            repo_root: Repository root path. If None, attempts to auto-detect.
            spec_dir: Override for legacy spec directory (YAML). If None, uses repo_root/swarm/spec.
            specs_dir: Override for new specs directory (JSON). If None, uses repo_root/swarm/specs.
            enable_git: If True, commit changes after saving specs.
            backup_on_write: If True, create .bak files before overwriting.
        """
        self._repo_root = self._resolve_repo_root(repo_root)
        self._spec_dir = spec_dir or (self._repo_root / DEFAULT_SPEC_DIR)  # Legacy
        self._specs_dir = specs_dir or (self._repo_root / DEFAULT_SPECS_DIR)  # New JSON store
        self._enable_git = enable_git
        self._backup_on_write = backup_on_write

        # Schema cache
        self._schemas: Dict[str, Dict[str, Any]] = {}

        # Validation availability
        self._jsonschema_available = self._check_jsonschema()

        logger.debug(
            "SpecManager initialized: repo_root=%s, specs_dir=%s, git=%s",
            self._repo_root,
            self._specs_dir,
            self._enable_git,
        )

    def _resolve_repo_root(self, repo_root: Optional[Path]) -> Path:
        """Resolve repository root path."""
        if repo_root:
            return Path(repo_root).resolve()

        # Try to find repo root from current directory
        cwd = Path.cwd()
        for parent in [cwd] + list(cwd.parents):
            if (parent / "swarm" / "spec").exists():
                return parent
            if (parent / ".git").exists():
                return parent

        # Fall back to current directory
        return cwd

    def _check_jsonschema(self) -> bool:
        """Check if jsonschema is available."""
        try:
            import jsonschema  # noqa: F401

            return True
        except ImportError:
            logger.warning(
                "jsonschema not installed - schema validation will be skipped"
            )
            return False

    # =========================================================================
    # Path Resolution
    # =========================================================================

    @property
    def repo_root(self) -> Path:
        """Get repository root path."""
        return self._repo_root

    @property
    def spec_dir(self) -> Path:
        """Get legacy spec directory path (YAML)."""
        return self._spec_dir

    @property
    def specs_dir(self) -> Path:
        """Get new specs directory path (JSON - runtime truth)."""
        return self._specs_dir

    def _flows_dir(self) -> Path:
        """Get flows directory (new JSON store)."""
        return self._specs_dir / DEFAULT_FLOWS_SUBDIR

    def _stations_dir(self) -> Path:
        """Get stations directory (new JSON store)."""
        return self._specs_dir / DEFAULT_STATIONS_SUBDIR

    def _templates_dir(self) -> Path:
        """Get templates directory (new JSON store)."""
        return self._specs_dir / DEFAULT_TEMPLATES_SUBDIR

    def _schemas_dir(self) -> Path:
        """Get schemas directory (new JSON store, fallback to legacy)."""
        new_schemas = self._specs_dir / DEFAULT_SCHEMAS_SUBDIR
        if new_schemas.exists():
            return new_schemas
        return self._spec_dir / DEFAULT_SCHEMAS_SUBDIR

    def _flow_path(self, flow_id: str) -> Path:
        """Get path to flow JSON file."""
        return self._flows_dir() / f"{flow_id}.json"

    def _flow_ui_path(self, flow_id: str) -> Path:
        """Get path to flow UI overlay file."""
        return self._flows_dir() / f"{flow_id}.ui.json"

    def _flow_graph_path(self, flow_id: str) -> Path:
        """Get path to flow graph file (legacy path structure)."""
        # Legacy: swarm/spec/flows/{flow_id}/graph.json
        # Check new location first
        new_path = self._flows_dir() / f"{flow_id}.json"
        if new_path.exists():
            return new_path
        # Fall back to legacy structure
        return self._spec_dir / DEFAULT_FLOWS_SUBDIR / flow_id / "graph.json"

    def _station_path(self, station_id: str) -> Path:
        """Get path to station JSON file."""
        return self._stations_dir() / f"{station_id}.json"

    def _template_path(self, template_id: str) -> Path:
        """Get path to template file."""
        return self._templates_dir() / f"{template_id}.json"

    def _schema_path(self, schema_name: str) -> Path:
        """Get path to schema file."""
        if not schema_name.endswith(".schema.json"):
            schema_name = f"{schema_name}.schema.json"
        return self._schemas_dir() / schema_name

    # =========================================================================
    # ETag Computation
    # =========================================================================

    def _compute_etag(self, content: Union[str, bytes]) -> str:
        """Compute SHA256 ETag from content.

        Uses the canonical spec_hash for deterministic hashing.
        """
        if isinstance(content, str):
            content = content.encode("utf-8")
        return hashlib.sha256(content).hexdigest()

    def _compute_data_etag(self, data: Dict[str, Any]) -> str:
        """Compute ETag from data using canonical JSON serialization.

        This ensures identical logical data produces identical ETags.
        """
        return spec_hash(data, length=64)

    def _compute_file_etag(self, path: Path) -> Optional[str]:
        """Compute ETag from file content."""
        if not path.exists():
            return None
        content = path.read_bytes()
        return self._compute_etag(content)

    # =========================================================================
    # Schema Loading
    # =========================================================================

    def _load_schema(self, schema_name: str) -> Optional[Dict[str, Any]]:
        """Load a JSON schema by name.

        Args:
            schema_name: Schema name (e.g., "flow_graph", "step_template").

        Returns:
            Parsed schema dict, or None if not found.
        """
        if schema_name in self._schemas:
            return self._schemas[schema_name]

        schema_path = self._schema_path(schema_name)
        if not schema_path.exists():
            logger.debug("Schema not found: %s", schema_path)
            return None

        try:
            with open(schema_path, "r", encoding="utf-8") as f:
                schema = json.load(f)
            self._schemas[schema_name] = schema
            return schema
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load schema %s: %s", schema_name, e)
            return None

    # =========================================================================
    # Validation
    # =========================================================================

    def validate_spec(
        self, spec_type: str, data: Dict[str, Any]
    ) -> List[ValidationError]:
        """Validate spec data against its JSON schema.

        Args:
            spec_type: Type of spec ("flow_graph", "step_template", "run_state", etc.).
            data: The spec data to validate.

        Returns:
            List of validation errors. Empty list means valid.
        """
        errors: List[ValidationError] = []

        if not self._jsonschema_available:
            logger.debug("Schema validation skipped (jsonschema not available)")
            return errors

        schema = self._load_schema(spec_type)
        if not schema:
            errors.append(
                ValidationError(
                    path="",
                    message=f"Schema '{spec_type}' not found",
                )
            )
            return errors

        try:
            import jsonschema
            from jsonschema import Draft7Validator

            validator = Draft7Validator(schema)
            for error in validator.iter_errors(data):
                path = ".".join(str(p) for p in error.absolute_path) or "root"
                schema_path = ".".join(str(p) for p in error.schema_path)
                errors.append(
                    ValidationError(
                        path=path,
                        message=error.message,
                        schema_path=schema_path,
                        value=error.instance,
                    )
                )
        except Exception as e:
            errors.append(
                ValidationError(
                    path="",
                    message=f"Validation error: {e}",
                )
            )

        return errors

    def validate_flow_graph(self, data: Dict[str, Any]) -> ValidationResult:
        """Validate flow graph data."""
        errors = self.validate_spec("flow_graph", data)
        return ValidationResult(valid=len(errors) == 0, errors=errors)

    def validate_step_template(self, data: Dict[str, Any]) -> ValidationResult:
        """Validate step template data."""
        errors = self.validate_spec("step_template", data)
        return ValidationResult(valid=len(errors) == 0, errors=errors)

    def validate_run_state(self, data: Dict[str, Any]) -> ValidationResult:
        """Validate run state data."""
        errors = self.validate_spec("run_state", data)
        return ValidationResult(valid=len(errors) == 0, errors=errors)

    def validate_prompt_plan(self, data: Dict[str, Any]) -> ValidationResult:
        """Validate prompt plan data."""
        errors = self.validate_spec("prompt_plan", data)
        return ValidationResult(valid=len(errors) == 0, errors=errors)

    # =========================================================================
    # Reading Specs
    # =========================================================================

    def get_flow_graph(self, flow_id: str) -> FlowGraph:
        """Load a flow graph by ID.

        Args:
            flow_id: The flow graph identifier (e.g., "build-flow").

        Returns:
            Parsed FlowGraph with computed ETag.

        Raises:
            SpecNotFoundError: If the flow graph doesn't exist.
            SpecValidationError: If the data fails schema validation.
        """
        path = self._flow_graph_path(flow_id)
        if not path.exists():
            raise SpecNotFoundError("flow_graph", flow_id, path)

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            raise SpecValidationError(
                "flow_graph",
                [ValidationError(path="", message=f"Invalid JSON: {e}")],
            )

        # Validate
        errors = self.validate_spec("flow_graph", data)
        if errors:
            raise SpecValidationError("flow_graph", errors)

        # Compute ETag
        etag = self._compute_file_etag(path)

        return FlowGraph.from_dict(data, etag=etag)

    def get_step_template(self, template_id: str) -> StepTemplate:
        """Load a step template by ID.

        Args:
            template_id: The template identifier (e.g., "code-critic-template").

        Returns:
            Parsed StepTemplate with computed ETag.

        Raises:
            SpecNotFoundError: If the template doesn't exist.
            SpecValidationError: If the data fails schema validation.
        """
        path = self._template_path(template_id)
        if not path.exists():
            raise SpecNotFoundError("step_template", template_id, path)

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            raise SpecValidationError(
                "step_template",
                [ValidationError(path="", message=f"Invalid JSON: {e}")],
            )

        # Validate
        errors = self.validate_spec("step_template", data)
        if errors:
            raise SpecValidationError("step_template", errors)

        # Compute ETag
        etag = self._compute_file_etag(path)

        return StepTemplate.from_dict(data, etag=etag)

    def get_all_templates(self) -> List[StepTemplate]:
        """Load all step templates.

        Returns:
            List of all valid StepTemplates.
            Invalid templates are logged and skipped.
        """
        templates: List[StepTemplate] = []
        templates_dir = self._templates_dir()

        if not templates_dir.exists():
            logger.debug("Templates directory not found: %s", templates_dir)
            return templates

        for json_file in templates_dir.glob("*.json"):
            template_id = json_file.stem
            try:
                template = self.get_step_template(template_id)
                templates.append(template)
            except (SpecNotFoundError, SpecValidationError) as e:
                logger.warning("Skipping invalid template %s: %s", template_id, e)

        return sorted(templates, key=lambda t: t.id)

    def list_flow_graphs(self) -> List[str]:
        """List all available flow graph IDs."""
        flows_dir = self._flows_dir()
        if not flows_dir.exists():
            return []

        flow_ids = []
        for item in flows_dir.iterdir():
            if item.is_dir() and (item / "graph.json").exists():
                flow_ids.append(item.name)

        return sorted(flow_ids)

    def list_templates(self) -> List[str]:
        """List all available template IDs."""
        templates_dir = self._templates_dir()
        if not templates_dir.exists():
            return []

        return sorted(
            p.stem
            for p in templates_dir.glob("*.json")
            if not p.name.startswith("_")
        )

    def get_template(self, template_id: str) -> Tuple[Dict[str, Any], str]:
        """Get a template as raw dict with ETag.

        This is a convenience method for the API layer that returns the
        template data as a dict (for JSON serialization) along with an ETag
        for HTTP caching.

        Args:
            template_id: The template identifier (e.g., "microloop-writer").

        Returns:
            Tuple of (template_data_dict, etag_string).

        Raises:
            FileNotFoundError: If template not found.
        """
        path = self._template_path(template_id)
        if not path.exists():
            raise FileNotFoundError(f"Template not found: {template_id}")

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        etag = self._compute_file_etag(path)
        return data, etag

    # =========================================================================
    # Writing Specs
    # =========================================================================

    def _atomic_write(
        self,
        path: Path,
        content: str,
        create_backup: bool = True,
    ) -> None:
        """Atomically write content to a file.

        Uses write-to-temp-then-rename pattern for atomicity.

        Args:
            path: Target file path.
            content: Content to write.
            create_backup: If True and file exists, create .bak backup.
        """
        # Ensure parent directory exists
        path.parent.mkdir(parents=True, exist_ok=True)

        # Create backup if requested
        if create_backup and path.exists():
            backup_path = path.with_suffix(path.suffix + ".bak")
            shutil.copy2(path, backup_path)
            logger.debug("Created backup: %s", backup_path)

        # Write to temp file in same directory (for same-filesystem rename)
        fd, tmp_path = tempfile.mkstemp(
            suffix=".tmp",
            prefix=path.stem + "_",
            dir=path.parent,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)

            # Atomic rename
            os.replace(tmp_path, path)
            logger.debug("Atomic write complete: %s", path)

        except Exception:
            # Clean up temp file on failure
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise

    def _git_commit(self, path: Path, message: str) -> bool:
        """Commit a file change to git.

        Args:
            path: Path to the changed file.
            message: Commit message.

        Returns:
            True if commit succeeded, False otherwise.
        """
        if not self._enable_git:
            return False

        try:
            import subprocess

            # Stage the file
            rel_path = path.relative_to(self._repo_root)
            subprocess.run(
                ["git", "add", str(rel_path)],
                cwd=self._repo_root,
                check=True,
                capture_output=True,
            )

            # Commit
            subprocess.run(
                ["git", "commit", "-m", message],
                cwd=self._repo_root,
                check=True,
                capture_output=True,
            )

            logger.info("Git commit: %s", message)
            return True

        except Exception as e:
            logger.warning("Git commit failed: %s", e)
            return False

    def save_flow_graph(
        self,
        flow_id: str,
        data: Dict[str, Any],
        etag: Optional[str] = None,
        commit: bool = False,
        commit_message: Optional[str] = None,
    ) -> str:
        """Save a flow graph spec.

        Args:
            flow_id: The flow graph identifier.
            data: The flow graph data to save.
            etag: If provided, verify this matches current ETag (for concurrency).
            commit: If True, commit the change to git.
            commit_message: Custom commit message.

        Returns:
            New ETag after save.

        Raises:
            SpecValidationError: If data fails schema validation.
            ConcurrencyError: If etag doesn't match current file state.
        """
        # Validate
        errors = self.validate_spec("flow_graph", data)
        if errors:
            raise SpecValidationError("flow_graph", errors)

        path = self._flow_graph_path(flow_id)

        # Check ETag for concurrency control
        if etag is not None:
            current_etag = self._compute_file_etag(path)
            if current_etag is not None and current_etag != etag:
                raise ConcurrencyError("flow_graph", flow_id, etag, current_etag)

        # Serialize
        content = json.dumps(data, indent=2, ensure_ascii=False) + "\n"

        # Atomic write
        self._atomic_write(path, content, create_backup=self._backup_on_write)

        # Compute new ETag
        new_etag = self._compute_etag(content)

        # Git commit if requested
        if commit or (self._enable_git and commit_message):
            msg = commit_message or f"Update flow graph: {flow_id}"
            self._git_commit(path, msg)

        logger.info("Saved flow graph: %s (etag: %s)", flow_id, new_etag[:16])
        return new_etag

    def save_step_template(
        self,
        template_id: str,
        data: Dict[str, Any],
        etag: Optional[str] = None,
        commit: bool = False,
        commit_message: Optional[str] = None,
    ) -> str:
        """Save a step template spec.

        Args:
            template_id: The template identifier.
            data: The template data to save.
            etag: If provided, verify this matches current ETag (for concurrency).
            commit: If True, commit the change to git.
            commit_message: Custom commit message.

        Returns:
            New ETag after save.

        Raises:
            SpecValidationError: If data fails schema validation.
            ConcurrencyError: If etag doesn't match current file state.
        """
        # Validate
        errors = self.validate_spec("step_template", data)
        if errors:
            raise SpecValidationError("step_template", errors)

        path = self._template_path(template_id)

        # Check ETag for concurrency control
        if etag is not None:
            current_etag = self._compute_file_etag(path)
            if current_etag is not None and current_etag != etag:
                raise ConcurrencyError("step_template", template_id, etag, current_etag)

        # Serialize
        content = json.dumps(data, indent=2, ensure_ascii=False) + "\n"

        # Atomic write
        self._atomic_write(path, content, create_backup=self._backup_on_write)

        # Compute new ETag
        new_etag = self._compute_etag(content)

        # Git commit if requested
        if commit or (self._enable_git and commit_message):
            msg = commit_message or f"Update step template: {template_id}"
            self._git_commit(path, msg)

        logger.info("Saved step template: %s (etag: %s)", template_id, new_etag[:16])
        return new_etag

    # =========================================================================
    # Prompt Plan Compilation
    # =========================================================================

    def compile_to_prompt_plan(
        self,
        flow_id: str,
        step_id: Optional[str] = None,
        run_base: Optional[Path] = None,
    ) -> Dict[str, Any]:
        """Compile a flow to a prompt plan.

        This is a convenience method that delegates to the SpecCompiler.
        For advanced compilation options, use the SpecCompiler directly.

        Args:
            flow_id: Flow specification ID (e.g., "3-build").
            step_id: Optional step ID. If None, returns plan for first step.
            run_base: Run base directory for artifact paths.

        Returns:
            Compiled prompt plan as dictionary.

        Raises:
            SpecNotFoundError: If flow or station not found.
            ValueError: If step_id not found in flow.
        """
        from .compiler import SpecCompiler
        from .loader import load_flow

        # Load flow to get step information
        flow = load_flow(flow_id, self._repo_root)

        # Default to first step
        if step_id is None and flow.steps:
            step_id = flow.steps[0].id

        if step_id is None:
            raise ValueError(f"Flow {flow_id} has no steps")

        # Default run base
        if run_base is None:
            run_base = self._repo_root / "swarm" / "runs" / "default"

        # Compile
        compiler = SpecCompiler(self._repo_root)
        plan = compiler.compile(
            flow_id=flow_id,
            step_id=step_id,
            context_pack=None,  # No context pack for basic compilation
            run_base=run_base,
        )

        # Convert dataclass to dict for return
        # PromptPlan is a frozen dataclass, convert manually
        return {
            "station_id": plan.station_id,
            "station_version": plan.station_version,
            "flow_id": plan.flow_id,
            "flow_version": plan.flow_version,
            "step_id": plan.step_id,
            "prompt_hash": plan.prompt_hash,
            "model": plan.model,
            "permission_mode": plan.permission_mode,
            "allowed_tools": list(plan.allowed_tools),
            "max_turns": plan.max_turns,
            "sandbox_enabled": plan.sandbox_enabled,
            "cwd": plan.cwd,
            "system_append": plan.system_append,
            "user_prompt": plan.user_prompt,
            "compiled_at": plan.compiled_at,
            "context_pack_size": plan.context_pack_size,
            "flow_key": plan.flow_key,
            "verification": {
                "required_artifacts": list(plan.verification.required_artifacts),
                "verification_commands": list(plan.verification.verification_commands),
            },
            "handoff": {
                "path": plan.handoff.path,
                "required_fields": list(plan.handoff.required_fields),
            },
        }

    # =========================================================================
    # Shred/Merge Overlay (flow.json + flow.ui.json)
    # =========================================================================

    def _deep_merge(self, base: Dict[str, Any], overlay: Dict[str, Any]) -> Dict[str, Any]:
        """Deep merge overlay into base.

        Arrays are replaced, not merged. Nested dicts are recursively merged.
        """
        result = base.copy()
        for key, value in overlay.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._deep_merge(result[key], value)
            else:
                result[key] = value
        return result

    def get_flow_with_ui(self, flow_id: str) -> Tuple[Dict[str, Any], Optional[str]]:
        """Load a flow spec with UI overlay merged.

        Reads flow.json and flow.ui.json, deep merges them.
        Returns merged data and combined ETag.

        Args:
            flow_id: The flow identifier (e.g., "3-build").

        Returns:
            Tuple of (merged_data, combined_etag).

        Raises:
            SpecNotFoundError: If flow.json doesn't exist.
        """
        flow_path = self._flow_path(flow_id)
        ui_path = self._flow_ui_path(flow_id)

        if not flow_path.exists():
            raise SpecNotFoundError("flow", flow_id, flow_path)

        try:
            with open(flow_path, "r", encoding="utf-8") as f:
                flow_data = json.load(f)
        except json.JSONDecodeError as e:
            raise SpecValidationError(
                "flow",
                [ValidationError(path="", message=f"Invalid JSON: {e}")],
            )

        # Load UI overlay if it exists
        ui_data = {}
        if ui_path.exists():
            try:
                with open(ui_path, "r", encoding="utf-8") as f:
                    ui_data = json.load(f)
            except json.JSONDecodeError as e:
                logger.warning("Invalid UI overlay JSON for %s: %s", flow_id, e)

        # Merge
        merged = self._deep_merge(flow_data, ui_data)

        # Combined ETag from both files
        flow_etag = self._compute_file_etag(flow_path) or ""
        ui_etag = self._compute_file_etag(ui_path) or ""
        combined_etag = self._compute_etag(f"{flow_etag}:{ui_etag}")

        return merged, combined_etag

    def save_flow_with_ui(
        self,
        flow_id: str,
        data: Dict[str, Any],
        ui_keys: Optional[List[str]] = None,
        etag: Optional[str] = None,
    ) -> Tuple[str, str]:
        """Save a flow spec, shredding UI-only fields into flow.ui.json.

        This supports the shred/merge pattern where:
        - flow.json contains runtime-relevant data
        - flow.ui.json contains UI-only overlays (positions, colors, etc.)

        Args:
            flow_id: The flow identifier.
            data: The full flow data (will be split).
            ui_keys: Keys to extract to UI overlay. Defaults to ["ui", "positions", "layout"].
            etag: If provided, verify combined ETag matches.

        Returns:
            Tuple of (flow_etag, ui_etag).
        """
        if ui_keys is None:
            ui_keys = ["ui", "positions", "layout", "style", "viewport"]

        flow_path = self._flow_path(flow_id)
        ui_path = self._flow_ui_path(flow_id)

        # Check ETag for concurrency
        if etag is not None:
            _, current_etag = self.get_flow_with_ui(flow_id)
            if current_etag and current_etag != etag:
                raise ConcurrencyError("flow", flow_id, etag, current_etag)

        # Split data
        flow_data = {}
        ui_data = {}

        for key, value in data.items():
            if key in ui_keys:
                ui_data[key] = value
            else:
                flow_data[key] = value

        # Ensure directories exist
        flow_path.parent.mkdir(parents=True, exist_ok=True)

        # Save flow.json using canonical JSON
        flow_content = canonical_json(flow_data, indent=2) + "\n"
        self._atomic_write(flow_path, flow_content, create_backup=self._backup_on_write)
        flow_etag = self._compute_etag(flow_content)

        # Save flow.ui.json only if there's UI data
        ui_etag = ""
        if ui_data:
            ui_content = canonical_json(ui_data, indent=2) + "\n"
            self._atomic_write(ui_path, ui_content, create_backup=self._backup_on_write)
            ui_etag = self._compute_etag(ui_content)

        logger.info(
            "Saved flow with UI: %s (flow_etag: %s, ui_etag: %s)",
            flow_id, flow_etag[:12], ui_etag[:12] if ui_etag else "none"
        )

        return flow_etag, ui_etag

    def save_station(
        self,
        station_id: str,
        data: Dict[str, Any],
        etag: Optional[str] = None,
    ) -> str:
        """Save a station spec to the JSON store.

        Args:
            station_id: The station identifier.
            data: The station data to save.
            etag: If provided, verify this matches current ETag.

        Returns:
            New ETag after save.
        """
        # Validate
        errors = self.validate_spec("station", data)
        if errors:
            raise SpecValidationError("station", errors)

        path = self._station_path(station_id)

        # Check ETag for concurrency control
        if etag is not None:
            current_etag = self._compute_file_etag(path)
            if current_etag is not None and current_etag != etag:
                raise ConcurrencyError("station", station_id, etag, current_etag)

        # Ensure directory exists
        path.parent.mkdir(parents=True, exist_ok=True)

        # Serialize using canonical JSON
        content = canonical_json(data, indent=2) + "\n"

        # Atomic write
        self._atomic_write(path, content, create_backup=self._backup_on_write)

        # Compute new ETag
        new_etag = self._compute_etag(content)

        logger.info("Saved station: %s (etag: %s)", station_id, new_etag[:16])
        return new_etag

    # =========================================================================
    # Utility Methods
    # =========================================================================

    def check_spec_exists(self, spec_type: str, spec_id: str) -> bool:
        """Check if a spec file exists.

        Args:
            spec_type: Type of spec ("flow_graph", "step_template").
            spec_id: The spec identifier.

        Returns:
            True if the spec file exists.
        """
        if spec_type == "flow_graph":
            return self._flow_graph_path(spec_id).exists()
        elif spec_type == "step_template":
            return self._template_path(spec_id).exists()
        else:
            logger.warning("Unknown spec type: %s", spec_type)
            return False

    def get_spec_etag(self, spec_type: str, spec_id: str) -> Optional[str]:
        """Get ETag for a spec file without loading it.

        Args:
            spec_type: Type of spec ("flow_graph", "step_template").
            spec_id: The spec identifier.

        Returns:
            ETag string, or None if file doesn't exist.
        """
        if spec_type == "flow_graph":
            path = self._flow_graph_path(spec_id)
        elif spec_type == "step_template":
            path = self._template_path(spec_id)
        else:
            return None

        return self._compute_file_etag(path)

    def clear_schema_cache(self) -> None:
        """Clear the schema cache."""
        self._schemas.clear()
        logger.debug("Schema cache cleared")


# =============================================================================
# Module-Level Convenience Functions
# =============================================================================


_default_manager: Optional[SpecManager] = None


def get_manager(repo_root: Optional[Path] = None) -> SpecManager:
    """Get or create the default SpecManager.

    Args:
        repo_root: Optional repository root. If None, uses auto-detection.

    Returns:
        The SpecManager instance.
    """
    global _default_manager
    if _default_manager is None:
        _default_manager = SpecManager(repo_root=repo_root)
    return _default_manager


def reset_manager() -> None:
    """Reset the default SpecManager (useful for testing)."""
    global _default_manager
    _default_manager = None


# =============================================================================
# FlowGraph Merge/Shred Functions (WP3)
# =============================================================================


class FlowSpecManager:
    """Manager for FlowGraph logic and UI overlay files.

    This class provides the merge/shred pattern for flow specs:
    - merge_flow_with_overlay(): Combines logic graph + UI overlay for API response
    - shred_flow_update(): Splits merged data back into separate files on save

    API returns merged view to UI; on save, server shreds back to separate files.

    The flow specs live at swarm/specs/flows/:
    - {flow_id}.json - Logic graph (nodes, edges, metadata)
    - {flow_id}.ui.json - UI overlay (positions, colors, canvas state)
    """

    def __init__(self, repo_root: Optional[Path] = None):
        """Initialize the FlowSpecManager.

        Args:
            repo_root: Repository root path. If None, attempts to auto-detect.
        """
        self._manager = SpecManager(repo_root=repo_root)
        self._flows_dir = self._manager.specs_dir / "flows"

    @property
    def flows_dir(self) -> Path:
        """Get the flows directory path."""
        return self._flows_dir

    def list_flows(self) -> List[str]:
        """List all available flow IDs.

        Returns:
            List of flow IDs (e.g., ["signal", "plan", "build", "gate", "deploy", "wisdom"]).
        """
        if not self._flows_dir.exists():
            return []

        flow_ids = set()
        for json_file in self._flows_dir.glob("*.json"):
            # Skip UI overlay files
            if not json_file.name.endswith(".ui.json"):
                flow_ids.add(json_file.stem)

        return sorted(flow_ids)

    def load_flow_graph(self, flow_id: str) -> Dict[str, Any]:
        """Load just the logic graph (no UI overlay).

        Args:
            flow_id: The flow identifier (e.g., "signal").

        Returns:
            Flow graph data as dictionary.

        Raises:
            SpecNotFoundError: If flow graph doesn't exist.
        """
        path = self._flows_dir / f"{flow_id}.json"
        if not path.exists():
            raise SpecNotFoundError("flow_graph", flow_id, path)

        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            raise SpecValidationError(
                "flow_graph",
                [ValidationError(path="", message=f"Invalid JSON: {e}")],
            )

    def load_ui_overlay(self, flow_id: str) -> Optional[Dict[str, Any]]:
        """Load just the UI overlay.

        Args:
            flow_id: The flow identifier (e.g., "signal").

        Returns:
            UI overlay data as dictionary, or None if no overlay exists.
        """
        path = self._flows_dir / f"{flow_id}.ui.json"
        if not path.exists():
            return None

        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            logger.warning("Invalid UI overlay JSON for %s: %s", flow_id, e)
            return None

    def merge_flow_with_overlay(self, flow_id: str) -> Tuple[Dict[str, Any], str]:
        """Merge flow graph with UI overlay for API response.

        This is the primary read operation for the UI. It combines:
        - {flow_id}.json (logic graph: nodes, edges, routing)
        - {flow_id}.ui.json (UI overlay: positions, colors, canvas state)

        The merged result includes:
        - All logic graph fields at top level
        - UI overlay merged in (nodes get position/color from overlay)
        - Combined ETag for concurrency control

        Args:
            flow_id: The flow identifier (e.g., "signal").

        Returns:
            Tuple of (merged_data, combined_etag).

        Raises:
            SpecNotFoundError: If flow graph doesn't exist.
        """
        flow_data = self.load_flow_graph(flow_id)
        ui_data = self.load_ui_overlay(flow_id) or {}

        # Deep merge UI overlay into flow data
        merged = self._deep_merge_with_nodes(flow_data, ui_data)

        # Compute combined ETag
        flow_path = self._flows_dir / f"{flow_id}.json"
        ui_path = self._flows_dir / f"{flow_id}.ui.json"

        flow_etag = self._manager._compute_file_etag(flow_path) or ""
        ui_etag = self._manager._compute_file_etag(ui_path) or ""
        combined_etag = self._manager._compute_etag(f"{flow_etag}:{ui_etag}")

        return merged, combined_etag

    def _deep_merge_with_nodes(
        self, flow_data: Dict[str, Any], ui_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Deep merge UI overlay into flow data, with special node handling.

        For nodes array, we merge UI data by node ID to add positions/colors.
        """
        merged = flow_data.copy()

        # Merge top-level UI-only keys
        for key in ["palette", "canvas", "groups", "annotations"]:
            if key in ui_data:
                merged[key] = ui_data[key]

        # Merge node-level UI data (positions, colors, etc.)
        if "nodes" in ui_data and "nodes" in merged:
            ui_nodes = ui_data["nodes"]
            if isinstance(ui_nodes, dict):
                # UI overlay uses {node_id: {position, color, ...}} format
                for i, node in enumerate(merged["nodes"]):
                    node_id = node.get("id")
                    if node_id and node_id in ui_nodes:
                        # Merge UI properties into node
                        merged["nodes"][i] = {**node, **ui_nodes[node_id]}

        # Merge edge-level UI data
        if "edges" in ui_data and "edges" in merged:
            ui_edges = ui_data["edges"]
            if isinstance(ui_edges, dict):
                # UI overlay uses {from:to: {color, waypoints, ...}} format
                for i, edge in enumerate(merged["edges"]):
                    edge_key = f"{edge.get('from')}:{edge.get('to')}"
                    if edge_key in ui_edges:
                        merged["edges"][i] = {**edge, **ui_edges[edge_key]}

        return merged

    def shred_flow_update(
        self,
        flow_id: str,
        merged_data: Dict[str, Any],
        etag: Optional[str] = None,
    ) -> Tuple[str, str]:
        """Split merged data back into logic graph and UI overlay files.

        This is the primary write operation from the UI. It takes merged data
        and shreds it into:
        - {flow_id}.json (logic graph: nodes, edges, routing)
        - {flow_id}.ui.json (UI overlay: positions, colors, canvas state)

        Args:
            flow_id: The flow identifier (e.g., "signal").
            merged_data: The merged flow data from UI.
            etag: Optional combined ETag for concurrency control.

        Returns:
            Tuple of (flow_etag, ui_etag).

        Raises:
            ConcurrencyError: If etag doesn't match current state.
        """
        # Check ETag for concurrency
        if etag is not None:
            _, current_etag = self.merge_flow_with_overlay(flow_id)
            if current_etag != etag:
                raise ConcurrencyError("flow", flow_id, etag, current_etag)

        # Keys that belong in UI overlay
        ui_top_level_keys = {"palette", "canvas", "groups", "annotations", "version"}
        ui_node_keys = {"position", "size", "color", "icon", "collapsed", "pinned",
                        "label_position", "custom_class"}
        ui_edge_keys = {"color", "stroke_width", "stroke_style", "label_visible",
                        "waypoints"}

        # Split the data
        flow_data: Dict[str, Any] = {}
        ui_data: Dict[str, Any] = {"flow_id": flow_id}

        for key, value in merged_data.items():
            if key in ui_top_level_keys:
                ui_data[key] = value
            elif key == "nodes":
                # Split node data
                flow_nodes = []
                ui_nodes = {}
                for node in value:
                    node_id = node.get("id")
                    flow_node = {}
                    ui_node = {}
                    for nk, nv in node.items():
                        if nk in ui_node_keys:
                            ui_node[nk] = nv
                        else:
                            flow_node[nk] = nv
                    flow_nodes.append(flow_node)
                    if ui_node:
                        ui_nodes[node_id] = ui_node
                flow_data["nodes"] = flow_nodes
                if ui_nodes:
                    ui_data["nodes"] = ui_nodes
            elif key == "edges":
                # Split edge data
                flow_edges = []
                ui_edges = {}
                for edge in value:
                    edge_key = f"{edge.get('from')}:{edge.get('to')}"
                    flow_edge = {}
                    ui_edge = {}
                    for ek, ev in edge.items():
                        if ek in ui_edge_keys:
                            ui_edge[ek] = ev
                        else:
                            flow_edge[ek] = ev
                    flow_edges.append(flow_edge)
                    if ui_edge:
                        ui_edges[edge_key] = ui_edge
                flow_data["edges"] = flow_edges
                if ui_edges:
                    ui_data["edges"] = ui_edges
            else:
                flow_data[key] = value

        # Ensure directory exists
        self._flows_dir.mkdir(parents=True, exist_ok=True)

        # Write flow graph
        flow_path = self._flows_dir / f"{flow_id}.json"
        flow_content = json.dumps(flow_data, indent=2, ensure_ascii=False) + "\n"
        self._manager._atomic_write(flow_path, flow_content)
        flow_etag = self._manager._compute_etag(flow_content)

        # Write UI overlay (only if there's UI data beyond flow_id)
        ui_etag = ""
        ui_path = self._flows_dir / f"{flow_id}.ui.json"
        if len(ui_data) > 1:  # More than just flow_id
            ui_content = json.dumps(ui_data, indent=2, ensure_ascii=False) + "\n"
            self._manager._atomic_write(ui_path, ui_content)
            ui_etag = self._manager._compute_etag(ui_content)

        logger.info(
            "Shredded flow update: %s (flow_etag: %s, ui_etag: %s)",
            flow_id, flow_etag[:12], ui_etag[:12] if ui_etag else "none"
        )

        return flow_etag, ui_etag


# =============================================================================
# Module-Level FlowGraph Functions (WP3)
# =============================================================================


_default_flow_manager: Optional[FlowSpecManager] = None


def get_flow_manager(repo_root: Optional[Path] = None) -> FlowSpecManager:
    """Get or create the default FlowSpecManager.

    Args:
        repo_root: Optional repository root. If None, uses auto-detection.

    Returns:
        The FlowSpecManager instance.
    """
    global _default_flow_manager
    if _default_flow_manager is None:
        _default_flow_manager = FlowSpecManager(repo_root=repo_root)
    return _default_flow_manager


def merge_flow_with_overlay(flow_id: str) -> Tuple[Dict[str, Any], str]:
    """Merge flow graph with UI overlay for API response.

    Convenience function that uses the default FlowSpecManager.

    Args:
        flow_id: The flow identifier (e.g., "signal").

    Returns:
        Tuple of (merged_data, combined_etag).
    """
    return get_flow_manager().merge_flow_with_overlay(flow_id)


def shred_flow_update(
    flow_id: str,
    merged_data: Dict[str, Any],
    etag: Optional[str] = None,
) -> Tuple[str, str]:
    """Split merged data back into logic graph and UI overlay files.

    Convenience function that uses the default FlowSpecManager.

    Args:
        flow_id: The flow identifier (e.g., "signal").
        merged_data: The merged flow data from UI.
        etag: Optional combined ETag for concurrency control.

    Returns:
        Tuple of (flow_etag, ui_etag).
    """
    return get_flow_manager().shred_flow_update(flow_id, merged_data, etag)


def load_flow_graph(flow_id: str) -> Dict[str, Any]:
    """Load just the flow logic graph (no UI overlay).

    Convenience function that uses the default FlowSpecManager.

    Args:
        flow_id: The flow identifier (e.g., "signal").

    Returns:
        Flow graph data as dictionary.
    """
    return get_flow_manager().load_flow_graph(flow_id)


def load_ui_overlay(flow_id: str) -> Optional[Dict[str, Any]]:
    """Load just the UI overlay for a flow.

    Convenience function that uses the default FlowSpecManager.

    Args:
        flow_id: The flow identifier (e.g., "signal").

    Returns:
        UI overlay data as dictionary, or None if no overlay exists.
    """
    return get_flow_manager().load_ui_overlay(flow_id)


def list_flows() -> List[str]:
    """List all available flow IDs.

    Convenience function that uses the default FlowSpecManager.

    Returns:
        List of flow IDs.
    """
    return get_flow_manager().list_flows()
