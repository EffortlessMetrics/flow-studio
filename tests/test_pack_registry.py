"""Tests for pack registry and configuration resolution."""

import json
import os
import pytest
from pathlib import Path
from unittest.mock import patch

from swarm.config.pack_registry import (
    Pack,
    PackLock,
    EngineConfig,
    FeaturesConfig,
    RuntimeConfig,
    PackResolver,
    load_pack_from_file,
    load_baseline_pack,
    get_baseline_pack_path,
    get_pack_lock_path,
    resolve_pack_config,
    compute_pack_hash,
    generate_pack_lock,
    read_pack_lock,
    write_pack_lock,
    lock_current_pack,
    verify_pack_lock,
)


class TestPackLoading:
    """Tests for pack file loading."""

    def test_load_baseline_pack_exists(self):
        """Baseline pack should exist and load successfully."""
        pack = load_baseline_pack()
        assert pack is not None
        assert pack.id == "baseline"
        assert pack.version == "1.0"

    def test_baseline_pack_has_engines(self):
        """Baseline pack should have engine configuration."""
        pack = load_baseline_pack()
        assert "claude" in pack.engines
        assert pack.engines["claude"].mode == "stub"
        assert pack.engines["claude"].execution == "legacy"

    def test_baseline_pack_has_features(self):
        """Baseline pack should have feature flags."""
        pack = load_baseline_pack()
        assert pack.features.stepwise_execution is True
        assert pack.features.write_receipts is True

    def test_baseline_pack_has_runtime(self):
        """Baseline pack should have runtime settings."""
        pack = load_baseline_pack()
        assert pack.runtime.context_budget_chars == 200000
        assert pack.runtime.timeout_seconds == 30

    def test_load_nonexistent_file_returns_none(self, tmp_path):
        """Loading a nonexistent file should return None."""
        result = load_pack_from_file(tmp_path / "nonexistent.yaml")
        assert result is None

    def test_load_empty_pack_returns_defaults(self, tmp_path):
        """Empty pack file should return Pack with defaults."""
        pack_file = tmp_path / "pack.yaml"
        pack_file.write_text("")
        pack = load_pack_from_file(pack_file)
        assert pack is not None
        assert pack.version == "1.0"
        assert pack.engines == {}

    def test_load_pack_with_engine_override(self, tmp_path):
        """Pack with engine override should load correctly."""
        pack_file = tmp_path / "pack.yaml"
        pack_file.write_text("""
version: "1.0"
engines:
  claude:
    mode: sdk
    execution: session
""")
        pack = load_pack_from_file(pack_file)
        assert pack is not None
        assert "claude" in pack.engines
        assert pack.engines["claude"].mode == "sdk"
        assert pack.engines["claude"].execution == "session"


class TestPackResolution:
    """Tests for pack resolution with provenance."""

    def test_baseline_provides_defaults(self):
        """Resolver should use baseline when no overrides present."""
        resolver = PackResolver(repo_root=None)
        result = resolver.resolve()

        assert result.config.get("engines.claude.mode") == "stub"
        assert result.provenance["engines.claude.mode"].source == "baseline"

    def test_env_overrides_baseline(self):
        """Environment variables should override baseline."""
        with patch.dict(os.environ, {"SWARM_CLAUDE_MODE": "sdk"}):
            resolver = PackResolver(repo_root=None)
            result = resolver.resolve()

            assert result.config.get("engines.claude.mode") == "sdk"
            assert result.provenance["engines.claude.mode"].source == "env"
            assert result.provenance["engines.claude.mode"].path == "SWARM_CLAUDE_MODE"

    def test_cli_overrides_env(self):
        """CLI overrides should take highest priority."""
        with patch.dict(os.environ, {"SWARM_CLAUDE_MODE": "sdk"}):
            resolver = PackResolver(
                repo_root=None,
                cli_overrides={"engines.claude.mode": "cli"}
            )
            result = resolver.resolve()

            assert result.config.get("engines.claude.mode") == "cli"
            assert result.provenance["engines.claude.mode"].source == "cli"

    def test_repo_pack_overrides_baseline(self, tmp_path):
        """Repo pack should override baseline but not env."""
        # Create repo pack
        swarm_dir = tmp_path / ".swarm"
        swarm_dir.mkdir()
        pack_file = swarm_dir / "pack.yaml"
        pack_file.write_text("""
version: "1.0"
engines:
  claude:
    mode: sdk
    execution: session
""")

        resolver = PackResolver(repo_root=tmp_path)
        result = resolver.resolve()

        assert result.config.get("engines.claude.mode") == "sdk"
        assert result.config.get("engines.claude.execution") == "session"
        assert result.provenance["engines.claude.mode"].source == "repo"

    def test_env_boolean_parsing(self):
        """Environment booleans should be parsed correctly."""
        with patch.dict(os.environ, {"SWARM_FEATURE_STEPWISE_EXECUTION": "false"}):
            resolver = PackResolver(repo_root=None)
            result = resolver.resolve()

            assert result.config.get("features.stepwise_execution") is False

    def test_env_integer_parsing(self):
        """Environment integers should be parsed correctly."""
        with patch.dict(os.environ, {"SWARM_CONTEXT_BUDGET_CHARS": "500000"}):
            resolver = PackResolver(repo_root=None)
            result = resolver.resolve()

            assert result.config.get("runtime.context_budget_chars") == 500000


class TestConvenienceFunction:
    """Tests for the resolve_pack_config convenience function."""

    def test_resolve_pack_config_returns_result(self):
        """resolve_pack_config should return ResolvedConfig."""
        result = resolve_pack_config()
        assert result is not None
        assert isinstance(result.config, dict)
        assert isinstance(result.provenance, dict)

    def test_resolve_pack_config_with_cli_overrides(self):
        """resolve_pack_config should accept CLI overrides."""
        result = resolve_pack_config(
            cli_overrides={"engines.claude.mode": "test"}
        )
        assert result.config.get("engines.claude.mode") == "test"


class TestPackHashing:
    """Tests for pack content hashing."""

    def test_compute_pack_hash_deterministic(self):
        """Same pack should produce same hash."""
        pack = Pack(
            version="1.0",
            id="test",
            engines={"claude": EngineConfig(mode="sdk")},
        )
        hash1 = compute_pack_hash(pack)
        hash2 = compute_pack_hash(pack)
        assert hash1 == hash2

    def test_compute_pack_hash_different_packs(self):
        """Different packs should produce different hashes."""
        pack1 = Pack(
            version="1.0",
            id="test1",
            engines={"claude": EngineConfig(mode="sdk")},
        )
        pack2 = Pack(
            version="1.0",
            id="test2",
            engines={"claude": EngineConfig(mode="cli")},
        )
        hash1 = compute_pack_hash(pack1)
        hash2 = compute_pack_hash(pack2)
        assert hash1 != hash2

    def test_compute_pack_hash_length(self):
        """Hash should be 64 characters (SHA256 hex)."""
        pack = Pack(version="1.0", id="test")
        pack_hash = compute_pack_hash(pack)
        assert len(pack_hash) == 64
        assert all(c in "0123456789abcdef" for c in pack_hash)

    def test_compute_pack_hash_baseline(self):
        """Baseline pack should have a valid hash."""
        pack = load_baseline_pack()
        pack_hash = compute_pack_hash(pack)
        assert len(pack_hash) == 64


class TestPackLockGeneration:
    """Tests for lock file generation."""

    def test_generate_pack_lock_structure(self):
        """Generated lock should have required fields."""
        pack = Pack(version="1.0", id="test")
        lock_data = generate_pack_lock(pack)

        assert "version" in lock_data
        assert "pack_hash" in lock_data
        assert "timestamp" in lock_data
        assert "pack_id" in lock_data
        assert "pack_version" in lock_data
        assert "resolved_config" in lock_data

    def test_generate_pack_lock_hash_matches(self):
        """Lock hash should match computed hash."""
        pack = Pack(version="1.0", id="test")
        lock_data = generate_pack_lock(pack)
        expected_hash = compute_pack_hash(pack)
        assert lock_data["pack_hash"] == expected_hash

    def test_generate_pack_lock_timestamp_format(self):
        """Timestamp should be ISO 8601 format."""
        pack = Pack(version="1.0", id="test")
        lock_data = generate_pack_lock(pack)
        # Should contain T separator and Z or +offset
        assert "T" in lock_data["timestamp"]

    def test_generate_pack_lock_with_custom_config(self):
        """Lock should accept custom resolved_config."""
        pack = Pack(version="1.0", id="test")
        custom_config = {"custom": "value"}
        lock_data = generate_pack_lock(pack, resolved_config=custom_config)
        assert lock_data["resolved_config"] == custom_config


class TestPackLockReadWrite:
    """Tests for lock file I/O operations."""

    def test_write_and_read_lock(self, tmp_path):
        """Written lock should be readable."""
        lock_path = tmp_path / ".swarm" / "pack.lock.json"
        pack = Pack(version="1.0", id="test")
        lock_data = generate_pack_lock(pack)

        success = write_pack_lock(lock_path, lock_data)
        assert success
        assert lock_path.exists()

        read_lock = read_pack_lock(lock_path)
        assert read_lock is not None
        assert read_lock.version == "1.0"
        assert read_lock.pack_id == "test"
        assert read_lock.pack_hash == lock_data["pack_hash"]

    def test_read_nonexistent_lock_returns_none(self, tmp_path):
        """Reading nonexistent lock should return None."""
        lock_path = tmp_path / "nonexistent.lock.json"
        result = read_pack_lock(lock_path)
        assert result is None

    def test_read_invalid_json_returns_none(self, tmp_path):
        """Reading invalid JSON should return None."""
        lock_path = tmp_path / "invalid.lock.json"
        lock_path.write_text("not valid json {{{")
        result = read_pack_lock(lock_path)
        assert result is None

    def test_write_creates_parent_directory(self, tmp_path):
        """Write should create parent directory if missing."""
        lock_path = tmp_path / "new" / "dir" / "pack.lock.json"
        lock_data = {"version": "1.0", "pack_hash": "abc"}
        success = write_pack_lock(lock_path, lock_data)
        assert success
        assert lock_path.exists()

    def test_write_overwrites_existing(self, tmp_path):
        """Write should overwrite existing lock file."""
        lock_path = tmp_path / "pack.lock.json"
        lock_path.write_text('{"version": "old"}')

        lock_data = {"version": "1.0", "pack_hash": "new"}
        success = write_pack_lock(lock_path, lock_data)
        assert success

        read_lock = read_pack_lock(lock_path)
        assert read_lock is not None
        assert read_lock.pack_hash == "new"


class TestPackLockVerification:
    """Tests for lock file verification."""

    def test_verify_matching_hash(self):
        """Verification should pass for matching hash."""
        pack = Pack(version="1.0", id="test")
        lock = PackLock(
            version="1.0",
            pack_hash=compute_pack_hash(pack),
            pack_id="test",
        )
        is_valid, error = verify_pack_lock(lock, pack)
        assert is_valid
        assert error is None

    def test_verify_mismatched_hash(self):
        """Verification should fail for mismatched hash."""
        pack = Pack(version="1.0", id="test")
        lock = PackLock(
            version="1.0",
            pack_hash="incorrect_hash_value",
            pack_id="test",
        )
        is_valid, error = verify_pack_lock(lock, pack)
        assert not is_valid
        assert "mismatch" in error.lower()

    def test_verify_empty_hash(self):
        """Verification should fail for empty hash."""
        pack = Pack(version="1.0", id="test")
        lock = PackLock(version="1.0", pack_hash="")
        is_valid, error = verify_pack_lock(lock, pack)
        assert not is_valid
        assert "no pack_hash" in error.lower()


class TestLockCurrentPack:
    """Tests for the lock_current_pack CLI function."""

    def test_lock_current_pack_creates_file(self, tmp_path):
        """lock_current_pack should create lock file."""
        # Create minimal .swarm directory
        swarm_dir = tmp_path / ".swarm"
        swarm_dir.mkdir()

        success, message = lock_current_pack(tmp_path)
        assert success
        assert "Locked" in message

        lock_path = get_pack_lock_path(tmp_path)
        assert lock_path.exists()

    def test_lock_current_pack_with_repo_pack(self, tmp_path):
        """lock_current_pack should use repo pack if available."""
        swarm_dir = tmp_path / ".swarm"
        swarm_dir.mkdir()
        pack_file = swarm_dir / "pack.yaml"
        pack_file.write_text("""
version: "1.0"
id: my-repo-pack
engines:
  claude:
    mode: sdk
""")

        success, message = lock_current_pack(tmp_path)
        assert success

        lock = read_pack_lock(get_pack_lock_path(tmp_path))
        assert lock is not None
        assert lock.pack_id == "my-repo-pack"


class TestPackResolverPinning:
    """Tests for pack resolution with lock file (pin layer)."""

    def test_pin_layer_between_repo_and_baseline(self, tmp_path):
        """Pin layer should be between repo and baseline in resolution."""
        swarm_dir = tmp_path / ".swarm"
        swarm_dir.mkdir()

        # Create a lock file with pinned config
        lock_data = {
            "version": "1.0",
            "pack_hash": "test_hash",
            "timestamp": "2025-01-01T00:00:00Z",
            "pack_id": "pinned",
            "pack_version": "1.0",
            "resolved_config": {
                "version": "1.0",
                "id": "pinned",
                "engines": {
                    "claude": {
                        "mode": "pinned-mode",
                        "execution": None,
                        "provider": None,
                    }
                },
                "features": {},
                "runtime": {},
                "flows": {},
            },
        }
        lock_path = swarm_dir / "pack.lock.json"
        lock_path.write_text(json.dumps(lock_data))

        # No repo pack, so pin should be used
        resolver = PackResolver(repo_root=tmp_path)
        result = resolver.resolve()

        assert result.config.get("engines.claude.mode") == "pinned-mode"
        assert result.provenance["engines.claude.mode"].source == "pin"

    def test_repo_overrides_pin(self, tmp_path):
        """Repo pack should override pinned pack."""
        swarm_dir = tmp_path / ".swarm"
        swarm_dir.mkdir()

        # Create repo pack
        pack_file = swarm_dir / "pack.yaml"
        pack_file.write_text("""
version: "1.0"
engines:
  claude:
    mode: repo-mode
""")

        # Create lock file with different mode
        lock_data = {
            "version": "1.0",
            "pack_hash": "test_hash",
            "timestamp": "2025-01-01T00:00:00Z",
            "pack_id": "pinned",
            "pack_version": "1.0",
            "resolved_config": {
                "version": "1.0",
                "id": "pinned",
                "engines": {
                    "claude": {
                        "mode": "pinned-mode",
                        "execution": None,
                        "provider": None,
                    }
                },
                "features": {},
                "runtime": {},
                "flows": {},
            },
        }
        lock_path = swarm_dir / "pack.lock.json"
        lock_path.write_text(json.dumps(lock_data))

        resolver = PackResolver(repo_root=tmp_path)
        result = resolver.resolve()

        # Repo should win over pin
        assert result.config.get("engines.claude.mode") == "repo-mode"
        assert result.provenance["engines.claude.mode"].source == "repo"

    def test_hash_mismatch_warning(self, tmp_path):
        """Resolver should warn when lock hash doesn't match repo pack."""
        swarm_dir = tmp_path / ".swarm"
        swarm_dir.mkdir()

        # Create repo pack
        pack_file = swarm_dir / "pack.yaml"
        pack_file.write_text("""
version: "1.0"
id: current
engines:
  claude:
    mode: current-mode
""")

        # Create lock file with different hash (from different pack config)
        lock_data = {
            "version": "1.0",
            "pack_hash": "outdated_hash_that_wont_match",
            "timestamp": "2025-01-01T00:00:00Z",
            "pack_id": "old",
            "pack_version": "1.0",
            "resolved_config": {},
        }
        lock_path = swarm_dir / "pack.lock.json"
        lock_path.write_text(json.dumps(lock_data))

        resolver = PackResolver(repo_root=tmp_path)

        # Should have warning about hash mismatch
        assert not resolver.pin_hash_valid
        assert resolver.pin_hash_warning is not None
        assert "mismatch" in resolver.pin_hash_warning.lower()

    def test_ignore_lock_parameter(self, tmp_path):
        """ignore_lock=True should skip loading lock file."""
        swarm_dir = tmp_path / ".swarm"
        swarm_dir.mkdir()

        # Create lock file
        lock_data = {
            "version": "1.0",
            "pack_hash": "test",
            "timestamp": "2025-01-01T00:00:00Z",
            "resolved_config": {
                "engines": {
                    "claude": {"mode": "pinned-mode", "execution": None, "provider": None}
                },
                "features": {},
                "runtime": {},
                "flows": {},
            },
        }
        lock_path = swarm_dir / "pack.lock.json"
        lock_path.write_text(json.dumps(lock_data))

        resolver = PackResolver(repo_root=tmp_path, ignore_lock=True)
        result = resolver.resolve()

        # Should use baseline, not pin
        assert result.config.get("engines.claude.mode") == "stub"
        assert result.provenance["engines.claude.mode"].source == "baseline"

    def test_no_lock_file_uses_baseline(self, tmp_path):
        """Without lock file, should fall back to baseline."""
        swarm_dir = tmp_path / ".swarm"
        swarm_dir.mkdir()

        resolver = PackResolver(repo_root=tmp_path)
        result = resolver.resolve()

        # Should use baseline
        assert result.config.get("engines.claude.mode") == "stub"
        assert result.provenance["engines.claude.mode"].source == "baseline"
