#!/usr/bin/env python3
"""
Generate platform-specific adapter layers from provider-neutral config.

Phase 0.5: Claude-only, frontmatter-only, for a small set of agents.

CLI Usage:
  uv run swarm/tools/gen_adapters.py --platform claude --agent deploy-decider --mode check
  uv run swarm/tools/gen_adapters.py --platform claude --agent deploy-decider --mode generate
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from difflib import unified_diff
from pathlib import Path
from typing import Any, Dict, Optional

# Add swarm package to path for library imports
_SWARM_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_SWARM_ROOT) not in sys.path:
    sys.path.insert(0, str(_SWARM_ROOT))

from control_plane import ControlPlane, validate_model_value  # noqa: E402
from swarm.validator import SimpleYAMLParser  # noqa: E402

__version__ = "0.5.0"


@dataclass
class AgentConfig:
    """Provider-neutral agent configuration."""
    key: str
    short_role: str
    model: str
    color: str
    model_tier: Optional[str] = None
    platforms: Optional[Dict[str, Any]] = None


@dataclass
class PlatformConfig:
    """Platform-specific adapter profile."""
    name: str
    agents_dir: Path
    models: Dict[str, str]
    platform_key: Optional[str] = None


def load_yaml_dict(path: Path, is_frontmatter: bool = False) -> Dict[str, Any]:
    """Load YAML file into a dictionary."""
    content = path.read_text(encoding="utf-8")
    return SimpleYAMLParser.parse(content, path, is_frontmatter=is_frontmatter)


def load_platform_config(root: Path, platform: str) -> PlatformConfig:
    """Load platform configuration."""
    platform_path = root / "swarm" / "platforms" / f"{platform}.yaml"
    if not platform_path.exists():
        raise FileNotFoundError(f"Platform config not found: {platform_path}")

    data = load_yaml_dict(platform_path, is_frontmatter=False)
    agents_dir = root / data.get("agents_dir", ".claude/agents")
    models = data.get("models", {})

    return PlatformConfig(
        name=data.get("name", platform),
        agents_dir=agents_dir,
        models=models,
        platform_key=data.get("platform_key", platform),
    )


def load_agent_config(path: Path) -> AgentConfig:
    """Load a single agent configuration."""
    data = load_yaml_dict(path, is_frontmatter=False)
    key = data.get("key")
    if not key:
        raise ValueError(f"Agent config missing 'key': {path}")

    short_role = data.get("short_role", "").strip()
    model = data.get("model", "inherit")
    color = data.get("color", "blue")
    model_tier = data.get("model_tier")

    # Reconstruct platforms dict from flattened platform_<name>_<field> keys
    # (simple YAML parser doesn't support nested dicts)
    platforms: Dict[str, Any] = {}
    for key_str, value in data.items():
        if key_str.startswith("platform_") and value is not None:
            # platform_openai_model_tier -> platforms.openai.model_tier
            parts = key_str.split("_", 1)  # Split into ["platform", rest]
            if len(parts) == 2:
                rest = parts[1]
                # Find the last underscore to split platform name from field
                last_underscore = rest.rfind("_")
                if last_underscore > 0:
                    platform_name = rest[:last_underscore]
                    field_name = rest[last_underscore + 1 :]
                    if platform_name not in platforms:
                        platforms[platform_name] = {}
                    platforms[platform_name][field_name] = value

    return AgentConfig(
        key=key,
        short_role=short_role,
        model=model,
        color=color,
        model_tier=model_tier,
        platforms=platforms if platforms else None,
    )


def split_frontmatter_and_body(text: str) -> tuple[str, str]:
    """
    Split markdown file into frontmatter and body.

    Returns: (frontmatter_block_including_delimiters, body)
    """
    lines = text.splitlines(keepends=False)
    if not lines or lines[0].strip() != "---":
        return "", text

    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            frontmatter = "\n".join(lines[: i + 1])
            body = "\n".join(lines[i + 1:])
            return frontmatter, body

    return "", text


def get_platform_agent_override(
    agent: AgentConfig,
    platform_name: str,
) -> Dict[str, Any]:
    """
    Return per-platform overrides from the agent config.

    Agents can declare:
      platforms:
        claude:
          model: ...
          model_tier: ...

    Returns: dict (possibly empty)
    """
    if not agent.platforms or not isinstance(agent.platforms, dict):
        return {}

    override = agent.platforms.get(platform_name)
    return override if isinstance(override, dict) else {}




def render_frontmatter(
    agent: AgentConfig,
    platform: PlatformConfig,
    template_text: str,
    platform_name: str,
    control_plane: Optional[ControlPlane] = None,
) -> str:
    """Render canonical frontmatter from config using template.

    Args:
        agent: Agent configuration from config file
        platform: Platform configuration
        template_text: Frontmatter template
        platform_name: Platform name (e.g., "claude")
        control_plane: Optional ControlPlane for audit logging

    Note:
        - `agent.model` is authoritative, even if it's "inherit".
        - `model_tier` is metadata for future use; currently ignored by the generator.
        - Per-platform overrides only matter if they explicitly set `model`.
    """
    # Optional: per-platform override, but only if it explicitly sets `model`
    override = get_platform_agent_override(agent, platform_name)
    override_model = override.get("model") if override else None

    # Use control plane to resolve final model value with validation
    if control_plane:
        model, _decision = control_plane.resolve_model(
            agent.key,
            agent.model if agent.model else None,
            override_model,
        )
    else:
        # Fallback if no control plane (for backwards compatibility)
        if override_model:
            validate_model_value(override_model)
            model = str(override_model)
        else:
            if agent.model:
                validate_model_value(agent.model)
            model = agent.model or "inherit"

    # Simple string formatting with {placeholder} style
    rendered = template_text.format(
        name=agent.key,
        description=agent.short_role,
        model=model,
        color=agent.color,
    )

    # Return without trailing newline; the body provides the necessary newline
    return rendered.rstrip()


def compare_frontmatter(rendered: str, actual: str, agent_path: Path) -> tuple[bool, Optional[str]]:
    """
    Compare rendered vs actual frontmatter.

    Returns: (match: bool, diff_text: Optional[str])
    """
    rendered_lines = rendered.splitlines(keepends=True)
    actual_lines = actual.splitlines(keepends=True)

    if rendered_lines == actual_lines:
        return True, None

    diff_lines = list(unified_diff(
        actual_lines,
        rendered_lines,
        fromfile=str(agent_path),
        tofile=f"{agent_path} (generated)",
        lineterm="",
    ))

    diff_text = "\n".join(diff_lines)
    return False, diff_text


def check_agent(
    root: Path,
    platform_cfg: PlatformConfig,
    agent_cfg: AgentConfig,
    template_text: str,
    platform_name: str,
    control_plane: Optional[ControlPlane] = None,
) -> bool:
    """
    Check if agent file matches canonical config.

    Args:
        control_plane: Optional ControlPlane for audit logging

    Returns: True if match, False otherwise.
    """
    agent_path = platform_cfg.agents_dir / f"{agent_cfg.key}.md"

    if not agent_path.exists():
        print(f"[WARN] {agent_path} does not exist; skipping.")
        return True  # Not a hard error for Phase 0.5

    actual_content = agent_path.read_text(encoding="utf-8")
    actual_frontmatter, _ = split_frontmatter_and_body(actual_content)

    rendered_frontmatter = render_frontmatter(
        agent_cfg, platform_cfg, template_text, platform_name, control_plane
    )

    match, diff = compare_frontmatter(rendered_frontmatter, actual_frontmatter, agent_path)

    if match:
        print(f"[OK] {agent_path}")
        return True
    else:
        print(f"[DIFF] {agent_path}")
        if diff:
            print(diff)
        return False


def generate_agent(
    root: Path,
    platform_cfg: PlatformConfig,
    agent_cfg: AgentConfig,
    template_text: str,
    platform_name: str,
    control_plane: Optional[ControlPlane] = None,
) -> bool:
    """
    Generate and write updated agent file.

    Args:
        control_plane: Optional ControlPlane for audit logging

    Returns: True if successful.
    """
    agent_path = platform_cfg.agents_dir / f"{agent_cfg.key}.md"

    if not agent_path.exists():
        print(f"[WARN] {agent_path} does not exist; skipping.")
        return True

    original = agent_path.read_text(encoding="utf-8")
    _, body = split_frontmatter_and_body(original)

    rendered_fm = render_frontmatter(
        agent_cfg, platform_cfg, template_text, platform_name, control_plane
    )

    # Ensure body has a leading newline if present
    if body and not body.startswith("\n"):
        body = "\n" + body

    updated = rendered_fm + body
    if updated != original:
        print(f"[INFO] Updating frontmatter for {agent_path}")
        agent_path.write_text(updated, encoding="utf-8")
        return True
    else:
        print(f"[OK] {agent_path} already matches generated frontmatter")
        return True


def discover_config_agents(root: Path) -> list[str]:
    """Discover all agent keys from swarm/config/agents/*.yaml files."""
    config_dir = root / "swarm" / "config" / "agents"
    if not config_dir.exists():
        return []

    keys = []
    for yaml_file in sorted(config_dir.glob("*.yaml")):
        keys.append(yaml_file.stem)

    return keys


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate platform-specific adapters from provider-neutral config.",
        epilog="Phase 1: supports both single-agent and batch modes.",
    )
    parser.add_argument(
        "--platform",
        required=True,
        choices=["claude"],
        help="Target platform",
    )
    parser.add_argument(
        "--agent",
        default=None,
        help="Agent key (e.g., deploy-decider). Required for 'check' and 'generate' modes, ignored for 'check-all' and 'generate-all'.",
    )
    parser.add_argument(
        "--mode",
        choices=["check", "generate", "check-all", "generate-all"],
        default="check",
        help="check: single-agent check; generate: single-agent generate; check-all: batch check all configured agents; generate-all: batch generate all configured agents",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"gen_adapters {__version__}",
    )

    args = parser.parse_args()

    root = Path(__file__).resolve().parents[2]

    # Determine which agents to process
    if args.mode in ("check-all", "generate-all"):
        agent_keys = discover_config_agents(root)
        base_mode = "check" if args.mode == "check-all" else "generate"
    else:
        if not args.agent:
            parser.error(f"--agent is required for mode '{args.mode}'")
        agent_keys = [args.agent]
        base_mode = args.mode

    # Load platform config (once, for all agents)
    try:
        platform_cfg = load_platform_config(root, args.platform)
    except Exception as e:
        print(f"[ERROR] Failed to load platform config: {e}", file=sys.stderr)
        sys.exit(2)

    # Load template (once, for all agents)
    template_path = root / "swarm" / "templates" / args.platform / "agent_frontmatter.md.tpl"
    try:
        template_text = template_path.read_text(encoding="utf-8")
    except Exception as e:
        print(f"[ERROR] Failed to load template: {e}", file=sys.stderr)
        sys.exit(2)

    # Initialize control plane for model decision tracking
    control_plane = ControlPlane()

    # Process agents
    any_failure = False

    for agent_key in agent_keys:
        agent_config_path = root / "swarm" / "config" / "agents" / f"{agent_key}.yaml"

        try:
            agent_cfg = load_agent_config(agent_config_path)
        except Exception as e:
            print(f"[ERROR] Failed to load agent config for '{agent_key}': {e}", file=sys.stderr)
            any_failure = True
            continue

        try:
            if base_mode == "check":
                success = check_agent(
                    root, platform_cfg, agent_cfg, template_text, args.platform, control_plane
                )
                if not success:
                    any_failure = True
            else:  # generate
                generate_agent(
                    root, platform_cfg, agent_cfg, template_text, args.platform, control_plane
                )
        except Exception as e:
            print(f"[ERROR] {e}", file=sys.stderr)
            any_failure = True

    # Write control plane audit log
    audit_log_path = root / "swarm" / "runs" / "control_plane_audit.log"
    audit_log_path.parent.mkdir(parents=True, exist_ok=True)
    control_plane.write_audit_log(audit_log_path)
    print(f"\n[INFO] Control plane audit log written to {audit_log_path}")

    # Print summary
    summary = control_plane.summary()
    print(f"\n[SUMMARY] Processed {summary['total_decisions']} decisions:")
    print(f"  By source: {summary['by_source']}")
    print(f"  By model: {summary['by_model']}")
    if summary['changed_count'] > 0:
        changed = control_plane.changed_agents()
        print(f"  Changed agents ({summary['changed_count']}):")
        for agent, (old, new) in sorted(changed.items()):
            print(f"    {agent}: {old} -> {new}")

    # Exit with appropriate code
    # check-all fails if any agent has a diff; generate-all always succeeds unless there's an error
    if base_mode == "check":
        sys.exit(1 if any_failure else 0)
    else:
        sys.exit(1 if any_failure else 0)


if __name__ == "__main__":
    main()
