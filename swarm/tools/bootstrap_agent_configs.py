#!/usr/bin/env python3
"""Bootstrap YAML configs for all agents from AGENTS.md."""
from pathlib import Path
from typing import Dict, Iterator

ROOT = Path(__file__).resolve().parents[2]
AGENTS_MD = ROOT / "swarm" / "AGENTS.md"
CONFIG_DIR = ROOT / "swarm" / "config" / "agents"


def iter_agent_rows() -> Iterator[Dict[str, str]]:
    """Parse AGENTS.md table and yield agent rows."""
    content = AGENTS_MD.read_text(encoding="utf-8")
    for line in content.splitlines():
        line = line.strip()
        # Skip header/separators
        if "| Key |" in line or "|-" in line:
            continue
        # Parse table rows
        if line.startswith("|") and line.endswith("|"):
            cols = [c.strip() for c in line.split("|")[1:-1]]
            if len(cols) == 6:
                key, flows, role_family, color, source, description = cols
                # Skip empty rows
                if not key or key == "Key":
                    continue
                # Skip built-in agents
                if source == "built-in":
                    continue
                yield {
                    "key": key,
                    "flows": flows,
                    "role_family": role_family,
                    "color": color,
                    "source": source,
                    "description": description,
                }


def write_stub(agent: Dict[str, str]) -> None:
    """Write a config stub for an agent."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    path = CONFIG_DIR / f"{agent['key']}.yaml"
    if path.exists():
        print(f"[SKIP] {path} already exists")
        return

    # Keep short_role conservative; you can refine later
    short_role = agent["description"]
    # Truncate for safety; adjust manually if needed
    if len(short_role) > 120:
        short_role = short_role[:117] + "..."

    text = f"""# Auto-bootstrapped from swarm/AGENTS.md
key: {agent['key']}
flows:
  - {agent['flows']}
category: {agent['role_family']}
color: {agent['color']}
source: {agent['source']}
short_role: "{short_role}"
model: inherit
"""
    path.write_text(text, encoding="utf-8")
    print(f"[BOOTSTRAP] wrote {path}")


def main() -> None:
    """Bootstrap all missing configs."""
    import argparse

    parser = argparse.ArgumentParser(
        prog="bootstrap_agent_configs",
        description=(
            "Bootstrap YAML configs for all agents from AGENTS.md.\n\n"
            "Reads the agent registry at swarm/AGENTS.md and creates stub\n"
            "config files in swarm/config/agents/ for any agents that don't\n"
            "already have config files.\n\n"
            "Existing config files are skipped (not overwritten)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be created without writing files",
    )
    args = parser.parse_args()

    count = 0
    for row in iter_agent_rows():
        if args.dry_run:
            path = CONFIG_DIR / f"{row['key']}.yaml"
            if path.exists():
                print(f"[SKIP] {path} already exists")
            else:
                print(f"[WOULD CREATE] {path}")
        else:
            write_stub(row)
        count += 1
    print(f"\n[OK] Processed {count} agents from AGENTS.md")


if __name__ == "__main__":
    main()
