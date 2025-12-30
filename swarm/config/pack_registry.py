"""Pack registry for configuration resolution.

Packs are versioned bundles of swarm configuration that can be:
- Embedded in the runtime (baseline)
- Defined in the repo (.swarm/pack.yaml)
- Overridden via CLI or environment

The registry implements layered resolution with provenance tracking,
so the UI can show where each setting came from.

Resolution order (highest to lowest priority):
1. CLI flags (e.g., --mode=sdk)
2. Environment variables (e.g., SWARM_CLAUDE_EXECUTION=session)
3. Repo pack (.swarm/pack.yaml)
4. Pinned pack (.swarm/pack.lock.json)
5. Baseline pack (swarm/packs/baseline/)

Pack Contents:
- Station definitions (swarm/packs/stations/*.yaml)
- Flow specifications (swarm/packs/flows/*.json)
- Templates and configurations

Usage:
    from swarm.config.pack_registry import (
        PackRegistry,
        load_pack_registry,
    )

    registry = load_pack_registry(repo_root)

    # Get all stations
    stations = registry.get_all_stations()

    # Get a specific flow
    flow = registry.get_flow("build")

    # Get station library for runtime
    library = registry.get_station_library()
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    from swarm.runtime.station_library import StationLibrary

logger = logging.getLogger(__name__)


# =============================================================================
# Pack Schema Types
# =============================================================================

@dataclass
class EngineConfig:
    """Engine configuration from pack."""
    mode: Optional[str] = None
    execution: Optional[str] = None
    provider: Optional[str] = None


@dataclass
class FeaturesConfig:
    """Feature flags from pack."""
    stepwise_execution: Optional[bool] = None
    context_handoff: Optional[bool] = None
    write_transcripts: Optional[bool] = None
    write_receipts: Optional[bool] = None


@dataclass
class RuntimeConfig:
    """Runtime settings from pack."""
    context_budget_chars: Optional[int] = None
    history_max_recent_chars: Optional[int] = None
    history_max_older_chars: Optional[int] = None
    timeout_seconds: Optional[int] = None


@dataclass
class FlowConfig:
    """Per-flow configuration from pack."""
    enabled: bool = True
    context_budgets: Optional[Dict[str, int]] = None


@dataclass
class Pack:
    """A complete pack definition."""
    version: str = "1.0"
    id: Optional[str] = None
    description: Optional[str] = None
    extends: Optional[str] = None
    engines: Dict[str, EngineConfig] = field(default_factory=dict)
    features: FeaturesConfig = field(default_factory=FeaturesConfig)
    runtime: RuntimeConfig = field(default_factory=RuntimeConfig)
    flows: Dict[str, FlowConfig] = field(default_factory=dict)


@dataclass
class Provenance:
    """Tracks where a configuration value came from."""
    value: Any
    source: str  # "cli" | "env" | "repo" | "pin" | "baseline"
    path: Optional[str] = None  # e.g., ".swarm/pack.yaml" or "SWARM_CLAUDE_MODE"


@dataclass
class ResolvedConfig:
    """Fully resolved configuration with provenance."""
    config: Dict[str, Any]
    provenance: Dict[str, Provenance]


# =============================================================================
# Pack Loading
# =============================================================================

def _parse_engine_config(data: Dict[str, Any]) -> EngineConfig:
    """Parse engine config from YAML data."""
    return EngineConfig(
        mode=data.get("mode"),
        execution=data.get("execution"),
        provider=data.get("provider"),
    )


def _parse_features_config(data: Dict[str, Any]) -> FeaturesConfig:
    """Parse features config from YAML data."""
    return FeaturesConfig(
        stepwise_execution=data.get("stepwise_execution"),
        context_handoff=data.get("context_handoff"),
        write_transcripts=data.get("write_transcripts"),
        write_receipts=data.get("write_receipts"),
    )


def _parse_runtime_config(data: Dict[str, Any]) -> RuntimeConfig:
    """Parse runtime config from YAML data."""
    return RuntimeConfig(
        context_budget_chars=data.get("context_budget_chars"),
        history_max_recent_chars=data.get("history_max_recent_chars"),
        history_max_older_chars=data.get("history_max_older_chars"),
        timeout_seconds=data.get("timeout_seconds"),
    )


def _parse_flow_config(data: Dict[str, Any]) -> FlowConfig:
    """Parse flow config from YAML data."""
    return FlowConfig(
        enabled=data.get("enabled", True),
        context_budgets=data.get("context_budgets"),
    )


def load_pack_from_file(path: Path) -> Optional[Pack]:
    """Load a pack from a YAML file.

    Args:
        path: Path to pack.yaml file.

    Returns:
        Parsed Pack, or None if file doesn't exist or is invalid.
    """
    if not path.exists():
        return None

    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)

        if not data:
            # Empty pack is valid - uses defaults
            return Pack()

        engines = {}
        for engine_id, engine_data in data.get("engines", {}).items():
            if isinstance(engine_data, dict):
                engines[engine_id] = _parse_engine_config(engine_data)

        flows = {}
        for flow_id, flow_data in data.get("flows", {}).items():
            if isinstance(flow_data, dict):
                flows[flow_id] = _parse_flow_config(flow_data)

        return Pack(
            version=data.get("version", "1.0"),
            id=data.get("id"),
            description=data.get("description"),
            extends=data.get("extends"),
            engines=engines,
            features=_parse_features_config(data.get("features", {})),
            runtime=_parse_runtime_config(data.get("runtime", {})),
            flows=flows,
        )

    except (yaml.YAMLError, OSError) as e:
        logger.warning("Failed to load pack from %s: %s", path, e)
        return None


def get_baseline_pack_path() -> Path:
    """Get path to the baseline pack bundled with the runtime."""
    return Path(__file__).parent.parent / "packs" / "baseline" / "pack.yaml"


def load_baseline_pack() -> Pack:
    """Load the baseline pack that ships with the runtime.

    Returns:
        The baseline Pack. Returns empty Pack if baseline file is missing.
    """
    path = get_baseline_pack_path()
    pack = load_pack_from_file(path)
    if pack is None:
        logger.warning("Baseline pack not found at %s, using empty defaults", path)
        return Pack(id="baseline")
    return pack


def get_repo_pack_path(repo_root: Path) -> Path:
    """Get path to the repo pack."""
    return repo_root / ".swarm" / "pack.yaml"


def load_repo_pack(repo_root: Path) -> Optional[Pack]:
    """Load the repo pack from .swarm/pack.yaml.

    Args:
        repo_root: Repository root path.

    Returns:
        The repo Pack, or None if not present.
    """
    return load_pack_from_file(get_repo_pack_path(repo_root))


# =============================================================================
# Pack Pinning (Lock File Support)
# =============================================================================

@dataclass
class PackLock:
    """Lock file content for pinning pack configuration.

    The lock file captures a point-in-time snapshot of resolved pack
    configuration, enabling reproducible builds and drift detection.

    Attributes:
        version: Lock file schema version.
        pack_hash: SHA256 hash of pack content for integrity verification.
        timestamp: ISO 8601 timestamp when lock was generated.
        pack_id: ID of the pack that was locked.
        pack_version: Version of the pack that was locked.
        resolved_config: The fully resolved configuration values.
    """
    version: str = "1.0"
    pack_hash: str = ""
    timestamp: str = ""
    pack_id: Optional[str] = None
    pack_version: str = "1.0"
    resolved_config: Dict[str, Any] = field(default_factory=dict)


def get_pack_lock_path(repo_root: Path) -> Path:
    """Get path to the pack lock file.

    Args:
        repo_root: Repository root path.

    Returns:
        Path to .swarm/pack.lock.json
    """
    return repo_root / ".swarm" / "pack.lock.json"


def _pack_to_hashable_dict(pack: Pack) -> Dict[str, Any]:
    """Convert a Pack to a dictionary suitable for hashing.

    This creates a deterministic representation of the pack content
    that can be used for hash computation.

    Args:
        pack: The Pack to convert.

    Returns:
        Dictionary with sorted keys for deterministic serialization.
    """
    def engine_to_dict(ec: EngineConfig) -> Dict[str, Any]:
        return {
            "mode": ec.mode,
            "execution": ec.execution,
            "provider": ec.provider,
        }

    def features_to_dict(fc: FeaturesConfig) -> Dict[str, Any]:
        return {
            "stepwise_execution": fc.stepwise_execution,
            "context_handoff": fc.context_handoff,
            "write_transcripts": fc.write_transcripts,
            "write_receipts": fc.write_receipts,
        }

    def runtime_to_dict(rc: RuntimeConfig) -> Dict[str, Any]:
        return {
            "context_budget_chars": rc.context_budget_chars,
            "history_max_recent_chars": rc.history_max_recent_chars,
            "history_max_older_chars": rc.history_max_older_chars,
            "timeout_seconds": rc.timeout_seconds,
        }

    def flow_to_dict(fc: FlowConfig) -> Dict[str, Any]:
        return {
            "enabled": fc.enabled,
            "context_budgets": fc.context_budgets,
        }

    return {
        "version": pack.version,
        "id": pack.id,
        "description": pack.description,
        "extends": pack.extends,
        "engines": {k: engine_to_dict(v) for k, v in sorted(pack.engines.items())},
        "features": features_to_dict(pack.features),
        "runtime": runtime_to_dict(pack.runtime),
        "flows": {k: flow_to_dict(v) for k, v in sorted(pack.flows.items())},
    }


def compute_pack_hash(pack: Pack) -> str:
    """Compute SHA256 hash of pack content for integrity verification.

    This creates a deterministic hash of the pack's configuration values.
    The hash can be used to detect configuration drift between the lock
    file and current state.

    Args:
        pack: The Pack to hash.

    Returns:
        SHA256 hash as hex string (64 characters).
    """
    hashable = _pack_to_hashable_dict(pack)
    # Use sort_keys for deterministic JSON serialization
    content = json.dumps(hashable, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def generate_pack_lock(pack: Pack, resolved_config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Generate lock file content from a pack.

    Creates a complete lock file structure including hash, timestamp,
    and resolved configuration snapshot.

    Args:
        pack: The Pack to lock.
        resolved_config: Optional pre-resolved config dict. If not provided,
            only pack-level values are included.

    Returns:
        Dictionary suitable for writing to pack.lock.json.
    """
    pack_hash = compute_pack_hash(pack)
    timestamp = datetime.now(timezone.utc).isoformat()

    lock_data = {
        "version": "1.0",
        "pack_hash": pack_hash,
        "timestamp": timestamp,
        "pack_id": pack.id,
        "pack_version": pack.version,
        "resolved_config": resolved_config or _pack_to_hashable_dict(pack),
    }

    return lock_data


def read_pack_lock(path: Path) -> Optional[PackLock]:
    """Read an existing pack lock file.

    Args:
        path: Path to the lock file.

    Returns:
        PackLock if file exists and is valid, None otherwise.
    """
    if not path.exists():
        return None

    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)

        return PackLock(
            version=data.get("version", "1.0"),
            pack_hash=data.get("pack_hash", ""),
            timestamp=data.get("timestamp", ""),
            pack_id=data.get("pack_id"),
            pack_version=data.get("pack_version", "1.0"),
            resolved_config=data.get("resolved_config", {}),
        )

    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to read pack lock from %s: %s", path, e)
        return None


def write_pack_lock(path: Path, lock_data: Dict[str, Any]) -> bool:
    """Write lock file atomically.

    Uses atomic write (write to temp file, then rename) to prevent
    corrupted lock files from partial writes.

    Args:
        path: Path to write the lock file.
        lock_data: Lock file content dictionary.

    Returns:
        True if write succeeded, False otherwise.
    """
    # Ensure parent directory exists
    path.parent.mkdir(parents=True, exist_ok=True)

    try:
        # Write to temp file first for atomic operation
        fd, tmp_path = tempfile.mkstemp(
            suffix=".json",
            prefix="pack.lock.",
            dir=path.parent,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(lock_data, f, indent=2, sort_keys=True)
                f.write("\n")  # Trailing newline

            # Atomic rename (on POSIX; on Windows this may fail if target exists)
            tmp_path_obj = Path(tmp_path)
            if path.exists():
                path.unlink()
            tmp_path_obj.rename(path)

            logger.info("Wrote pack lock to %s", path)
            return True

        except Exception:
            # Clean up temp file on error
            try:
                Path(tmp_path).unlink()
            except OSError:
                pass
            raise

    except (OSError, IOError) as e:
        logger.error("Failed to write pack lock to %s: %s", path, e)
        return False


def _pack_from_lock_config(lock: PackLock) -> Pack:
    """Reconstruct a Pack from lock file resolved_config.

    Args:
        lock: The PackLock containing resolved_config.

    Returns:
        Pack instance with values from the lock file.
    """
    config = lock.resolved_config

    # Parse engines
    engines = {}
    for engine_id, engine_data in config.get("engines", {}).items():
        if isinstance(engine_data, dict):
            engines[engine_id] = EngineConfig(
                mode=engine_data.get("mode"),
                execution=engine_data.get("execution"),
                provider=engine_data.get("provider"),
            )

    # Parse features
    features_data = config.get("features", {})
    features = FeaturesConfig(
        stepwise_execution=features_data.get("stepwise_execution"),
        context_handoff=features_data.get("context_handoff"),
        write_transcripts=features_data.get("write_transcripts"),
        write_receipts=features_data.get("write_receipts"),
    )

    # Parse runtime
    runtime_data = config.get("runtime", {})
    runtime = RuntimeConfig(
        context_budget_chars=runtime_data.get("context_budget_chars"),
        history_max_recent_chars=runtime_data.get("history_max_recent_chars"),
        history_max_older_chars=runtime_data.get("history_max_older_chars"),
        timeout_seconds=runtime_data.get("timeout_seconds"),
    )

    # Parse flows
    flows = {}
    for flow_id, flow_data in config.get("flows", {}).items():
        if isinstance(flow_data, dict):
            flows[flow_id] = FlowConfig(
                enabled=flow_data.get("enabled", True),
                context_budgets=flow_data.get("context_budgets"),
            )

    return Pack(
        version=config.get("version", lock.pack_version),
        id=config.get("id", lock.pack_id),
        description=config.get("description"),
        extends=config.get("extends"),
        engines=engines,
        features=features,
        runtime=runtime,
        flows=flows,
    )


def verify_pack_lock(lock: PackLock, current_pack: Pack) -> Tuple[bool, Optional[str]]:
    """Verify that a lock file matches the current pack state.

    Compares the hash in the lock file against the current pack's
    computed hash to detect configuration drift.

    Args:
        lock: The PackLock to verify.
        current_pack: The current Pack to compare against.

    Returns:
        Tuple of (is_valid, error_message). If is_valid is True,
        error_message is None. If False, error_message explains the mismatch.
    """
    if not lock.pack_hash:
        return False, "Lock file has no pack_hash"

    current_hash = compute_pack_hash(current_pack)
    if lock.pack_hash != current_hash:
        return False, (
            f"Pack hash mismatch: lock has {lock.pack_hash[:12]}..., "
            f"current is {current_hash[:12]}..."
        )

    return True, None


def lock_current_pack(
    repo_root: Path,
    cli_overrides: Optional[Dict[str, Any]] = None,
) -> Tuple[bool, str]:
    """Lock the current resolved pack configuration.

    Creates or updates .swarm/pack.lock.json with the current resolved
    configuration. This is the CLI/API entry point for "lock current pack".

    Args:
        repo_root: Repository root path.
        cli_overrides: Optional CLI overrides to include in resolution.

    Returns:
        Tuple of (success, message).
    """
    # Import here to avoid circular dependency at module load
    # We'll use the resolver after defining it, so defer the actual call
    try:
        # Load current packs
        baseline = load_baseline_pack()
        repo_pack = load_repo_pack(repo_root)

        # Use repo pack if available, otherwise baseline
        pack_to_lock = repo_pack if repo_pack else baseline

        # Build resolved config for storage
        # We'll use a simplified approach here - store the merged pack values
        resolved = _pack_to_hashable_dict(pack_to_lock)

        # Generate lock data
        lock_data = generate_pack_lock(pack_to_lock, resolved_config=resolved)

        # Write lock file
        lock_path = get_pack_lock_path(repo_root)
        success = write_pack_lock(lock_path, lock_data)

        if success:
            return True, f"Locked pack configuration to {lock_path}"
        else:
            return False, f"Failed to write lock file to {lock_path}"

    except Exception as e:
        return False, f"Failed to lock pack: {e}"


# =============================================================================
# Pack Resolution with Provenance
# =============================================================================

class PackResolver:
    """Resolves configuration through the pack layer hierarchy.

    Resolution order (highest to lowest priority):
    1. CLI flags
    2. Environment variables
    3. Repo pack (.swarm/pack.yaml)
    4. Pinned pack (.swarm/pack.lock.json)
    5. Baseline pack

    Each resolved value includes provenance showing which layer it came from.
    """

    def __init__(
        self,
        repo_root: Optional[Path] = None,
        cli_overrides: Optional[Dict[str, Any]] = None,
        ignore_lock: bool = False,
    ):
        """Initialize the resolver.

        Args:
            repo_root: Repository root for loading repo pack.
            cli_overrides: CLI flag overrides (e.g., {"engines.claude.mode": "sdk"}).
            ignore_lock: If True, skip loading the lock file (useful for lock generation).
        """
        self._repo_root = repo_root
        self._cli_overrides = cli_overrides or {}

        # Load packs
        self._baseline = load_baseline_pack()
        self._repo_pack = load_repo_pack(repo_root) if repo_root else None

        # Load pinned pack from lock file
        self._pinned_pack: Optional[Pack] = None
        self._pin_path: Optional[str] = None
        self._pin_hash_valid: bool = True
        self._pin_hash_warning: Optional[str] = None

        if repo_root and not ignore_lock:
            self._load_pinned_pack(repo_root)

    def _load_pinned_pack(self, repo_root: Path) -> None:
        """Load pinned pack from lock file if it exists.

        Args:
            repo_root: Repository root path.
        """
        lock_path = get_pack_lock_path(repo_root)
        lock = read_pack_lock(lock_path)

        if lock is None:
            return

        # Reconstruct Pack from lock file
        self._pinned_pack = _pack_from_lock_config(lock)
        self._pin_path = str(lock_path)

        # Verify hash if we have a repo pack to compare against
        if self._repo_pack and lock.pack_hash:
            current_hash = compute_pack_hash(self._repo_pack)
            if lock.pack_hash != current_hash:
                self._pin_hash_valid = False
                self._pin_hash_warning = (
                    f"Pack hash mismatch: lock file was generated from a different "
                    f"pack configuration. Lock hash: {lock.pack_hash[:12]}..., "
                    f"current: {current_hash[:12]}... "
                    f"Consider regenerating the lock file with 'lock_current_pack()'."
                )
                logger.warning(self._pin_hash_warning)

    @property
    def pin_hash_valid(self) -> bool:
        """Check if the pinned pack hash matches current pack.

        Returns:
            True if no lock file exists, or if hash matches.
            False if hash mismatch was detected.
        """
        return self._pin_hash_valid

    @property
    def pin_hash_warning(self) -> Optional[str]:
        """Get the hash mismatch warning message if any.

        Returns:
            Warning message if hash mismatch, None otherwise.
        """
        return self._pin_hash_warning

    def resolve(self) -> ResolvedConfig:
        """Resolve all configuration with provenance.

        Returns:
            ResolvedConfig with final values and provenance map.
        """
        config: Dict[str, Any] = {}
        provenance: Dict[str, Provenance] = {}

        # Resolve engine config
        for engine_id in ["claude", "gemini"]:
            engine_config, engine_prov = self._resolve_engine(engine_id)
            for key, value in engine_config.items():
                full_key = f"engines.{engine_id}.{key}"
                config[full_key] = value
                provenance[full_key] = engine_prov[key]

        # Resolve features
        feature_config, feature_prov = self._resolve_features()
        for key, value in feature_config.items():
            full_key = f"features.{key}"
            config[full_key] = value
            provenance[full_key] = feature_prov[key]

        # Resolve runtime
        runtime_config, runtime_prov = self._resolve_runtime()
        for key, value in runtime_config.items():
            full_key = f"runtime.{key}"
            config[full_key] = value
            provenance[full_key] = runtime_prov[key]

        return ResolvedConfig(config=config, provenance=provenance)

    def _resolve_engine(
        self, engine_id: str
    ) -> Tuple[Dict[str, Any], Dict[str, Provenance]]:
        """Resolve engine configuration."""
        result: Dict[str, Any] = {}
        prov: Dict[str, Provenance] = {}

        for field in ["mode", "execution", "provider"]:
            value, source, path = self._resolve_value(
                cli_key=f"engines.{engine_id}.{field}",
                env_key=f"SWARM_{engine_id.upper()}_{field.upper()}",
                repo_getter=lambda p, f=field, e=engine_id: (
                    getattr(p.engines.get(e, EngineConfig()), f, None)
                    if p else None
                ),
                baseline_getter=lambda p, f=field, e=engine_id: (
                    getattr(p.engines.get(e, EngineConfig()), f, None)
                    if p else None
                ),
            )
            if value is not None:
                result[field] = value
                prov[field] = Provenance(value=value, source=source, path=path)

        return result, prov

    def _resolve_features(self) -> Tuple[Dict[str, Any], Dict[str, Provenance]]:
        """Resolve feature flags."""
        result: Dict[str, Any] = {}
        prov: Dict[str, Provenance] = {}

        for field in [
            "stepwise_execution",
            "context_handoff",
            "write_transcripts",
            "write_receipts",
        ]:
            value, source, path = self._resolve_value(
                cli_key=f"features.{field}",
                env_key=f"SWARM_FEATURE_{field.upper()}",
                repo_getter=lambda p, f=field: (
                    getattr(p.features, f, None) if p else None
                ),
                baseline_getter=lambda p, f=field: (
                    getattr(p.features, f, None) if p else None
                ),
            )
            if value is not None:
                result[field] = value
                prov[field] = Provenance(value=value, source=source, path=path)

        return result, prov

    def _resolve_runtime(self) -> Tuple[Dict[str, Any], Dict[str, Provenance]]:
        """Resolve runtime settings."""
        result: Dict[str, Any] = {}
        prov: Dict[str, Provenance] = {}

        for field in [
            "context_budget_chars",
            "history_max_recent_chars",
            "history_max_older_chars",
            "timeout_seconds",
        ]:
            value, source, path = self._resolve_value(
                cli_key=f"runtime.{field}",
                env_key=f"SWARM_{field.upper()}",
                repo_getter=lambda p, f=field: (
                    getattr(p.runtime, f, None) if p else None
                ),
                baseline_getter=lambda p, f=field: (
                    getattr(p.runtime, f, None) if p else None
                ),
            )
            if value is not None:
                result[field] = value
                prov[field] = Provenance(value=value, source=source, path=path)

        return result, prov

    def _resolve_value(
        self,
        cli_key: str,
        env_key: str,
        repo_getter,
        baseline_getter,
        pin_getter=None,
    ) -> Tuple[Optional[Any], str, Optional[str]]:
        """Resolve a single value through the layer hierarchy.

        Args:
            cli_key: Key for CLI override lookup.
            env_key: Environment variable name.
            repo_getter: Function to extract value from repo pack.
            baseline_getter: Function to extract value from baseline pack.
            pin_getter: Optional function to extract value from pinned pack.
                If None, uses baseline_getter for the pinned pack.

        Returns:
            Tuple of (value, source, path).
        """
        # Use baseline_getter for pin if not specified
        if pin_getter is None:
            pin_getter = baseline_getter

        # 1. CLI override
        if cli_key in self._cli_overrides:
            return (self._cli_overrides[cli_key], "cli", f"--{cli_key}")

        # 2. Environment variable
        env_value = os.environ.get(env_key)
        if env_value is not None:
            # Parse booleans and integers
            if env_value.lower() in ("true", "1", "yes"):
                return (True, "env", env_key)
            if env_value.lower() in ("false", "0", "no"):
                return (False, "env", env_key)
            try:
                return (int(env_value), "env", env_key)
            except ValueError:
                return (env_value, "env", env_key)

        # 3. Repo pack
        if self._repo_pack:
            repo_value = repo_getter(self._repo_pack)
            if repo_value is not None:
                path = ".swarm/pack.yaml"
                if self._repo_root:
                    path = str(get_repo_pack_path(self._repo_root))
                return (repo_value, "repo", path)

        # 4. Pinned pack (from lock file)
        if self._pinned_pack:
            pin_value = pin_getter(self._pinned_pack)
            if pin_value is not None:
                return (pin_value, "pin", self._pin_path)

        # 5. Baseline pack
        baseline_value = baseline_getter(self._baseline)
        if baseline_value is not None:
            return (baseline_value, "baseline", str(get_baseline_pack_path()))

        return (None, "default", None)


def resolve_pack_config(
    repo_root: Optional[Path] = None,
    cli_overrides: Optional[Dict[str, Any]] = None,
) -> ResolvedConfig:
    """Convenience function to resolve pack configuration.

    Args:
        repo_root: Repository root for loading repo pack.
        cli_overrides: CLI flag overrides.

    Returns:
        ResolvedConfig with final values and provenance map.
    """
    resolver = PackResolver(repo_root=repo_root, cli_overrides=cli_overrides)
    return resolver.resolve()


# =============================================================================
# Bridge: Resolved Runtime Adapter
# =============================================================================
#
# This adapter bridges pack_registry (new) with runtime_config (legacy).
# It provides a single entry point that:
# 1. Resolves pack config (baseline + repo + env + cli)
# 2. Returns values compatible with get_engine_mode() etc.
# 3. Includes provenance for UI display
#


@dataclass
class EngineSettings:
    """Resolved engine settings with provenance."""
    mode: str
    execution: str
    provider: str
    mode_source: str  # "cli" | "env" | "repo" | "baseline" | "default"
    execution_source: str
    provider_source: str


@dataclass
class ResolvedRuntimeConfig:
    """Complete resolved runtime configuration with provenance.

    This is the output of resolve_runtime() and provides all settings
    needed for engine initialization plus provenance for debugging/UI.
    """
    engines: Dict[str, EngineSettings]
    features: Dict[str, Tuple[Any, str]]  # (value, source)
    runtime: Dict[str, Tuple[Any, str]]   # (value, source)


def resolve_runtime(
    repo_root: Optional[Path] = None,
    cli_overrides: Optional[Dict[str, Any]] = None,
) -> ResolvedRuntimeConfig:
    """Resolve runtime configuration through pack hierarchy.

    This is the primary entry point for callers who need engine settings.
    It returns resolved values with provenance, suitable for:
    - Engine factory initialization
    - UI display of "where did this setting come from"
    - Debugging configuration issues

    Resolution order (highest to lowest priority):
    1. CLI flags (cli_overrides)
    2. Environment variables
    3. Repo pack (.swarm/pack.yaml)
    4. Baseline pack (swarm/packs/baseline/)
    5. Hardcoded defaults

    Args:
        repo_root: Repository root for loading repo pack.
        cli_overrides: CLI flag overrides.

    Returns:
        ResolvedRuntimeConfig with engine settings and provenance.
    """
    # Resolve pack config
    resolved = resolve_pack_config(repo_root=repo_root, cli_overrides=cli_overrides)

    # Build engine settings with provenance
    engines: Dict[str, EngineSettings] = {}

    for engine_id in ["claude", "gemini"]:
        mode_key = f"engines.{engine_id}.mode"
        exec_key = f"engines.{engine_id}.execution"
        prov_key = f"engines.{engine_id}.provider"

        mode_prov = resolved.provenance.get(mode_key)
        exec_prov = resolved.provenance.get(exec_key)
        provider_prov = resolved.provenance.get(prov_key)

        engines[engine_id] = EngineSettings(
            mode=resolved.config.get(mode_key, "stub"),
            execution=resolved.config.get(exec_key, "legacy"),
            provider=resolved.config.get(prov_key, ""),
            mode_source=mode_prov.source if mode_prov else "default",
            execution_source=exec_prov.source if exec_prov else "default",
            provider_source=provider_prov.source if provider_prov else "default",
        )

    # Build feature settings with provenance
    features: Dict[str, Tuple[Any, str]] = {}
    for key in ["stepwise_execution", "context_handoff", "write_transcripts", "write_receipts"]:
        full_key = f"features.{key}"
        value = resolved.config.get(full_key)
        prov = resolved.provenance.get(full_key)
        if value is not None:
            features[key] = (value, prov.source if prov else "default")

    # Build runtime settings with provenance
    runtime: Dict[str, Tuple[Any, str]] = {}
    for key in ["context_budget_chars", "history_max_recent_chars", "history_max_older_chars", "timeout_seconds"]:
        full_key = f"runtime.{key}"
        value = resolved.config.get(full_key)
        prov = resolved.provenance.get(full_key)
        if value is not None:
            runtime[key] = (value, prov.source if prov else "default")

    return ResolvedRuntimeConfig(
        engines=engines,
        features=features,
        runtime=runtime,
    )


def get_engine_mode_from_pack(
    engine_id: str,
    repo_root: Optional[Path] = None,
) -> Tuple[str, str]:
    """Get engine mode using pack resolution.

    This is the pack-aware replacement for runtime_config.get_engine_mode().

    Args:
        engine_id: Engine identifier ("claude" or "gemini").
        repo_root: Repository root for loading repo pack.

    Returns:
        Tuple of (mode, source) where source is "cli"|"env"|"repo"|"baseline"|"default".
    """
    resolved = resolve_runtime(repo_root=repo_root)
    settings = resolved.engines.get(engine_id)
    if settings:
        return settings.mode, settings.mode_source
    return "stub", "default"


def get_engine_execution_from_pack(
    engine_id: str,
    repo_root: Optional[Path] = None,
) -> Tuple[str, str]:
    """Get engine execution pattern using pack resolution.

    This is the pack-aware replacement for runtime_config.get_engine_execution().

    Args:
        engine_id: Engine identifier ("claude" or "gemini").
        repo_root: Repository root for loading repo pack.

    Returns:
        Tuple of (execution, source) where execution is "legacy"|"session".
    """
    resolved = resolve_runtime(repo_root=repo_root)
    settings = resolved.engines.get(engine_id)
    if settings:
        return settings.execution, settings.execution_source
    return "legacy", "default"


# =============================================================================
# Station Spec Types (for pack loading)
# =============================================================================

@dataclass
class StationSpec:
    """Specification for a station/template.

    Attributes:
        station_id: Unique identifier for this station.
        name: Human-readable name.
        description: What this station does.
        category: Category (sidequest, worker, critic, etc.).
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
    agent_key: Optional[str] = None
    template_id: Optional[str] = None
    params_schema: Dict[str, Any] = field(default_factory=dict)
    default_params: Dict[str, Any] = field(default_factory=dict)
    tags: List[str] = field(default_factory=list)
    pack_origin: str = "default"


def station_spec_to_dict(spec: StationSpec) -> Dict[str, Any]:
    """Convert StationSpec to dictionary."""
    return {
        "station_id": spec.station_id,
        "name": spec.name,
        "description": spec.description,
        "category": spec.category,
        "agent_key": spec.agent_key,
        "template_id": spec.template_id,
        "params_schema": spec.params_schema,
        "default_params": spec.default_params,
        "tags": list(spec.tags),
        "pack_origin": spec.pack_origin,
    }


def station_spec_from_dict(data: Dict[str, Any]) -> StationSpec:
    """Parse StationSpec from dictionary."""
    return StationSpec(
        station_id=data.get("station_id", ""),
        name=data.get("name", data.get("station_id", "")),
        description=data.get("description", ""),
        category=data.get("category", "general"),
        agent_key=data.get("agent_key"),
        template_id=data.get("template_id"),
        params_schema=data.get("params_schema", {}),
        default_params=data.get("default_params", {}),
        tags=list(data.get("tags", [])),
        pack_origin=data.get("pack_origin", "default"),
    )


# =============================================================================
# Flow Spec Types (for pack loading)
# =============================================================================

@dataclass
class FlowNode:
    """A node in a flow specification."""
    node_id: str
    template_id: str
    params: Dict[str, Any] = field(default_factory=dict)
    overrides: Dict[str, Any] = field(default_factory=dict)


@dataclass
class FlowEdge:
    """An edge in a flow specification."""
    edge_id: str
    from_node: str
    to_node: str
    edge_type: str = "sequence"
    priority: int = 50
    condition: Optional[Dict[str, Any]] = None


@dataclass
class FlowPolicy:
    """Policy configuration for a flow."""
    max_loop_iterations: int = 50
    suggested_sidequests: List[str] = field(default_factory=list)


@dataclass
class FlowSpecData:
    """Complete flow specification from pack.

    This represents flows as defined in swarm/packs/flows/*.json.
    """
    id: str
    name: str
    description: str = ""
    version: int = 1
    nodes: List[FlowNode] = field(default_factory=list)
    edges: List[FlowEdge] = field(default_factory=list)
    policy: FlowPolicy = field(default_factory=FlowPolicy)
    pack_origin: str = "default"


def flow_node_from_dict(data: Dict[str, Any]) -> FlowNode:
    """Parse FlowNode from dictionary."""
    return FlowNode(
        node_id=data.get("node_id", ""),
        template_id=data.get("template_id", ""),
        params=data.get("params", {}),
        overrides=data.get("overrides", {}),
    )


def flow_edge_from_dict(data: Dict[str, Any]) -> FlowEdge:
    """Parse FlowEdge from dictionary."""
    return FlowEdge(
        edge_id=data.get("edge_id", ""),
        from_node=data.get("from", ""),
        to_node=data.get("to", ""),
        edge_type=data.get("type", "sequence"),
        priority=data.get("priority", 50),
        condition=data.get("condition"),
    )


def flow_spec_from_dict(data: Dict[str, Any], pack_origin: str = "default") -> FlowSpecData:
    """Parse FlowSpecData from dictionary."""
    nodes = [flow_node_from_dict(n) for n in data.get("nodes", [])]
    edges = [flow_edge_from_dict(e) for e in data.get("edges", [])]

    policy_data = data.get("policy", {})
    policy = FlowPolicy(
        max_loop_iterations=policy_data.get("max_loop_iterations", 50),
        suggested_sidequests=policy_data.get("suggested_sidequests", []),
    )

    return FlowSpecData(
        id=data.get("id", ""),
        name=data.get("name", data.get("id", "")),
        description=data.get("description", ""),
        version=data.get("version", 1),
        nodes=nodes,
        edges=edges,
        policy=policy,
        pack_origin=pack_origin,
    )


def flow_spec_to_dict(spec: FlowSpecData) -> Dict[str, Any]:
    """Convert FlowSpecData to dictionary."""
    return {
        "id": spec.id,
        "name": spec.name,
        "description": spec.description,
        "version": spec.version,
        "nodes": [
            {
                "node_id": n.node_id,
                "template_id": n.template_id,
                "params": n.params,
                "overrides": n.overrides,
            }
            for n in spec.nodes
        ],
        "edges": [
            {
                "edge_id": e.edge_id,
                "from": e.from_node,
                "to": e.to_node,
                "type": e.edge_type,
                "priority": e.priority,
                "condition": e.condition,
            }
            for e in spec.edges
        ],
        "policy": {
            "max_loop_iterations": spec.policy.max_loop_iterations,
            "suggested_sidequests": spec.policy.suggested_sidequests,
        },
        "pack_origin": spec.pack_origin,
    }


# =============================================================================
# Pack Registry - Unified interface for pack contents
# =============================================================================

class PackRegistry:
    """Registry for loading and managing packs.

    Packs contain:
    - Station definitions (swarm/packs/stations/*.yaml)
    - Flow specifications (swarm/packs/flows/*.json)
    - Templates and configurations

    This registry provides a unified interface for accessing pack contents
    and integrates with the StationLibrary for runtime use.

    Usage:
        registry = PackRegistry(repo_root)
        registry.load()

        # Get all stations
        stations = registry.get_all_stations()

        # Get a specific flow
        flow = registry.get_flow("build")

        # Get station library for runtime
        library = registry.get_station_library()
    """

    def __init__(self, repo_root: Optional[Path] = None):
        """Initialize the pack registry.

        Args:
            repo_root: Repository root path. If None, uses default pack location.
        """
        self._repo_root = repo_root
        self._stations: Dict[str, StationSpec] = {}
        self._flows: Dict[str, FlowSpecData] = {}
        self._by_category: Dict[str, List[str]] = {}
        self._by_tag: Dict[str, Set[str]] = {}
        self._loaded = False
        self._station_library: Optional["StationLibrary"] = None

    def load(self) -> None:
        """Load all pack contents.

        Loads stations and flows from:
        1. Default pack location (swarm/packs/)
        2. Repo pack location if different
        """
        if self._loaded:
            return

        self._load_stations()
        self._load_flows()
        self._loaded = True

    def _get_packs_dir(self) -> Path:
        """Get the packs directory path."""
        if self._repo_root:
            return self._repo_root / "swarm" / "packs"
        # Fall back to module-relative path
        return Path(__file__).parent.parent / "packs"

    def _load_stations(self) -> int:
        """Load station specs from pack directories.

        Returns:
            Number of stations loaded.
        """
        count = 0
        packs_dir = self._get_packs_dir()
        stations_dir = packs_dir / "stations"

        if not stations_dir.exists():
            logger.debug("Stations directory not found: %s", stations_dir)
            return count

        # Load YAML files
        for yaml_file in stations_dir.glob("*.yaml"):
            try:
                with open(yaml_file, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)

                if isinstance(data, list):
                    for item in data:
                        spec = station_spec_from_dict(item)
                        spec.pack_origin = f"pack:{yaml_file.stem}"
                        self._register_station(spec)
                        count += 1
                elif isinstance(data, dict):
                    spec = station_spec_from_dict(data)
                    spec.pack_origin = f"pack:{yaml_file.stem}"
                    self._register_station(spec)
                    count += 1
            except Exception as e:
                logger.warning("Failed to load station from %s: %s", yaml_file, e)

        # Load JSON files
        for json_file in stations_dir.glob("*.json"):
            try:
                with open(json_file, "r", encoding="utf-8") as f:
                    data = json.load(f)

                if isinstance(data, list):
                    for item in data:
                        spec = station_spec_from_dict(item)
                        spec.pack_origin = f"pack:{json_file.stem}"
                        self._register_station(spec)
                        count += 1
                elif isinstance(data, dict):
                    spec = station_spec_from_dict(data)
                    spec.pack_origin = f"pack:{json_file.stem}"
                    self._register_station(spec)
                    count += 1
            except Exception as e:
                logger.warning("Failed to load station from %s: %s", json_file, e)

        if count > 0:
            logger.info("Loaded %d stations from pack", count)

        return count

    def _load_flows(self) -> int:
        """Load flow specs from pack directories.

        Returns:
            Number of flows loaded.
        """
        count = 0
        packs_dir = self._get_packs_dir()
        flows_dir = packs_dir / "flows"

        if not flows_dir.exists():
            logger.debug("Flows directory not found: %s", flows_dir)
            return count

        # Load JSON files (primary format for flows)
        for json_file in flows_dir.glob("*.json"):
            try:
                with open(json_file, "r", encoding="utf-8") as f:
                    data = json.load(f)

                spec = flow_spec_from_dict(data, pack_origin=f"pack:{json_file.stem}")
                self._flows[spec.id] = spec
                count += 1
            except Exception as e:
                logger.warning("Failed to load flow from %s: %s", json_file, e)

        # Also support YAML flows
        for yaml_file in flows_dir.glob("*.yaml"):
            try:
                with open(yaml_file, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)

                if data:
                    spec = flow_spec_from_dict(data, pack_origin=f"pack:{yaml_file.stem}")
                    self._flows[spec.id] = spec
                    count += 1
            except Exception as e:
                logger.warning("Failed to load flow from %s: %s", yaml_file, e)

        if count > 0:
            logger.info("Loaded %d flows from pack", count)

        return count

    def _register_station(self, spec: StationSpec) -> None:
        """Register a station in the registry.

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

    # =========================================================================
    # Station Access Methods
    # =========================================================================

    def has_station(self, station_id: str) -> bool:
        """Check if a station exists in the registry.

        Args:
            station_id: Station ID to check.

        Returns:
            True if station exists.
        """
        self.load()
        return station_id in self._stations

    def get_station(self, station_id: str) -> Optional[StationSpec]:
        """Get a station specification.

        Args:
            station_id: Station ID to retrieve.

        Returns:
            StationSpec if found, None otherwise.
        """
        self.load()
        return self._stations.get(station_id)

    def get_stations_by_category(self, category: str) -> List[StationSpec]:
        """Get all stations in a category.

        Args:
            category: Category to filter by (e.g., "sidequest", "worker", "critic").

        Returns:
            List of station specs in that category.
        """
        self.load()
        station_ids = self._by_category.get(category, [])
        return [self._stations[sid] for sid in station_ids if sid in self._stations]

    def get_stations_by_tag(self, tag: str) -> List[StationSpec]:
        """Get all stations with a tag.

        Args:
            tag: Tag to filter by.

        Returns:
            List of station specs with that tag.
        """
        self.load()
        station_ids = self._by_tag.get(tag, set())
        return [self._stations[sid] for sid in station_ids if sid in self._stations]

    def get_all_stations(self) -> List[StationSpec]:
        """Get all stations in the registry.

        Returns:
            List of all station specs.
        """
        self.load()
        return list(self._stations.values())

    def list_station_ids(self) -> List[str]:
        """Get all station IDs.

        Returns:
            List of station IDs.
        """
        self.load()
        return list(self._stations.keys())

    def list_categories(self) -> List[str]:
        """Get all station categories.

        Returns:
            List of category names.
        """
        self.load()
        return list(self._by_category.keys())

    def list_tags(self) -> List[str]:
        """Get all station tags.

        Returns:
            List of tag names.
        """
        self.load()
        return list(self._by_tag.keys())

    # =========================================================================
    # Flow Access Methods
    # =========================================================================

    def has_flow(self, flow_id: str) -> bool:
        """Check if a flow exists in the registry.

        Args:
            flow_id: Flow ID to check.

        Returns:
            True if flow exists.
        """
        self.load()
        return flow_id in self._flows

    def get_flow(self, flow_id: str) -> Optional[FlowSpecData]:
        """Get a flow specification.

        Args:
            flow_id: Flow ID to retrieve.

        Returns:
            FlowSpecData if found, None otherwise.
        """
        self.load()
        return self._flows.get(flow_id)

    def get_all_flows(self) -> List[FlowSpecData]:
        """Get all flows in the registry.

        Returns:
            List of all flow specs.
        """
        self.load()
        return list(self._flows.values())

    def list_flow_ids(self) -> List[str]:
        """Get all flow IDs.

        Returns:
            List of flow IDs.
        """
        self.load()
        return list(self._flows.keys())

    # =========================================================================
    # StationLibrary Integration
    # =========================================================================

    def get_station_library(self) -> "StationLibrary":
        """Get a StationLibrary instance populated from this registry.

        The StationLibrary is lazily created and cached.

        Returns:
            StationLibrary instance with all stations from this registry.
        """
        if self._station_library is not None:
            return self._station_library

        # Import here to avoid circular dependency
        from swarm.runtime.station_library import (
            StationLibrary,
            StationSpec as LibraryStationSpec,
        )

        self.load()

        library = StationLibrary()

        # Convert and register each station
        for spec in self._stations.values():
            lib_spec = LibraryStationSpec(
                station_id=spec.station_id,
                name=spec.name,
                description=spec.description,
                category=spec.category,
                agent_key=spec.agent_key,
                template_id=spec.template_id,
                params_schema=spec.params_schema,
                default_params=spec.default_params,
                tags=list(spec.tags),
                pack_origin=spec.pack_origin,
            )
            library._register_station(lib_spec)

        self._station_library = library
        return library

    # =========================================================================
    # Serialization
    # =========================================================================

    def to_dict(self) -> Dict[str, Any]:
        """Serialize registry state.

        Returns:
            Dictionary representation of the registry.
        """
        self.load()
        return {
            "stations": {
                sid: station_spec_to_dict(spec)
                for sid, spec in self._stations.items()
            },
            "flows": {
                fid: flow_spec_to_dict(spec)
                for fid, spec in self._flows.items()
            },
            "categories": dict(self._by_category),
            "tags": {tag: list(ids) for tag, ids in self._by_tag.items()},
        }


def load_pack_registry(repo_root: Optional[Path] = None) -> PackRegistry:
    """Load a pack registry with all pack contents.

    This is the standard way to create a PackRegistry for use
    in the runtime.

    Args:
        repo_root: Optional repository root. If None, uses default pack location.

    Returns:
        Configured PackRegistry instance.
    """
    registry = PackRegistry(repo_root=repo_root)
    registry.load()
    return registry
