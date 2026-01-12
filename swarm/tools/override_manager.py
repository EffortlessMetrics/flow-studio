#!/usr/bin/env python3
"""
Override Manager

Manages temporary overrides for selftest step failures.
Allows humans to approve skips with audit trail.
"""

import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional


@dataclass
class Override:
    """Represents a single override approval."""
    step_id: str
    reason: str
    approver: str
    created_at: str  # ISO format
    expires_at: str  # ISO format
    status: str  # APPROVED | PENDING | REVOKED


class OverrideManager:
    """Manages selftest step overrides."""

    def __init__(self, config_file: Optional[Path] = None):
        self.config_file = config_file or Path(".claude/config/overrides.json")
        self.config_file.parent.mkdir(parents=True, exist_ok=True)

    def load_overrides(self) -> List[Override]:
        """Load overrides from file."""
        if not self.config_file.exists():
            return []

        try:
            with open(self.config_file) as f:
                data = json.load(f)
                return [Override(**o) for o in data.get("overrides", [])]
        except Exception:
            return []

    def is_override_active(self, step_id: str) -> bool:
        """Check if override is active for step."""
        now = datetime.now(timezone.utc)

        for override in self.load_overrides():
            if override.step_id == step_id and override.status == "APPROVED":
                try:
                    expires = datetime.fromisoformat(override.expires_at)
                    if now < expires:
                        return True
                except ValueError:
                    pass

        return False

    def create_override(
        self,
        step_id: str,
        reason: str,
        approver: str,
        hours: int = 24,
    ) -> Override:
        """Create new override."""
        now = datetime.now(timezone.utc)
        expires = now + timedelta(hours=hours)

        override = Override(
            step_id=step_id,
            reason=reason,
            approver=approver,
            created_at=now.isoformat(),
            expires_at=expires.isoformat(),
            status="APPROVED",
        )

        overrides = self.load_overrides()
        # Check for existing active override
        for existing in overrides:
            if existing.step_id == step_id and existing.status == "APPROVED":
                existing.status = "REVOKED"

        overrides.append(override)

        with open(self.config_file, "w") as f:
            json.dump(
                {"overrides": [asdict(o) for o in overrides]},
                f,
                indent=2,
            )

        return override

    def revoke_override(self, step_id: str) -> bool:
        """Revoke an override."""
        overrides = self.load_overrides()
        found = False

        for override in overrides:
            if override.step_id == step_id and override.status == "APPROVED":
                override.status = "REVOKED"
                found = True

        if found:
            with open(self.config_file, "w") as f:
                json.dump(
                    {"overrides": [asdict(o) for o in overrides]},
                    f,
                    indent=2,
                )

        return found

    def list_overrides(self) -> List[Override]:
        """List all active overrides."""
        now = datetime.now(timezone.utc)
        active = []

        for override in self.load_overrides():
            if override.status == "APPROVED":
                try:
                    expires = datetime.fromisoformat(override.expires_at)
                    if now < expires:
                        active.append(override)
                except ValueError:
                    pass

        return active


def main():
    """CLI for override manager."""
    if len(sys.argv) < 2:
        print("Usage: override_manager.py <create|revoke|list> [args...]")
        sys.exit(1)

    command = sys.argv[1]
    manager = OverrideManager()

    if command == "create":
        if len(sys.argv) < 5:
            print("Usage: override_manager.py create <step_id> <reason> <approver> [hours]")
            sys.exit(1)

        step_id = sys.argv[2]
        reason = sys.argv[3]
        approver = sys.argv[4]
        hours = int(sys.argv[5]) if len(sys.argv) > 5 else 24

        override = manager.create_override(step_id, reason, approver, hours)
        print(f"[OK] Override created for {step_id}")
        print(f"  Reason: {reason}")
        print(f"  Approver: {approver}")
        print(f"  Expires: {override.expires_at}")

    elif command == "revoke":
        if len(sys.argv) < 3:
            print("Usage: override_manager.py revoke <step_id>")
            sys.exit(1)

        step_id = sys.argv[2]
        if manager.revoke_override(step_id):
            print(f"[OK] Override revoked for {step_id}")
        else:
            print(f"[FAIL] No active override found for {step_id}")
            sys.exit(1)

    elif command == "list":
        overrides = manager.list_overrides()
        if not overrides:
            print("[OK] No active overrides")
        else:
            print(f"Active Overrides ({len(overrides)}):")
            for override in overrides:
                print(f"  • {override.step_id}")
                print(f"    Reason: {override.reason}")
                print(f"    Approver: {override.approver}")
                print(f"    Expires: {override.expires_at}")

    else:
        print(f"Unknown command: {command}")
        sys.exit(1)


if __name__ == "__main__":
    main()
