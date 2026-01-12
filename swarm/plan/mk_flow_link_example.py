#!/usr/bin/env python3
"""
mk_flow_link.py - Flow Studio Deep Link Generator

Generate shareable URLs for Flow Studio UI to link directly to runs, flows, or steps.

Example implementation (not final code):
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode

# Add repo root to path for imports
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from swarm.config.flow_registry import get_flow_order


# Mock for example - would use real YAML loader in implementation
def _load_flow_config(flow_key: str) -> dict:
    """Load flow config from swarm/config/flows/{flow_key}.yaml"""
    # In real implementation, would load and parse YAML
    # For now, return mock data
    MOCK_FLOWS = {
        "signal": {"steps": ["normalize_input", "frame_problem", "author_requirements", "critique_requirements", "bdd_scenarios", "scope_risk"]},
        "plan": {"steps": ["impact_analysis", "design_options", "adr_draft", "interface_design", "observability_spec", "test_strategy", "work_plan", "design_critique"]},
        "build": {"steps": ["context_load", "test_microloop", "code_microloop", "mutation_hardening", "doc_update", "self_review"]},
        "gate": {"steps": ["receipt_audit", "contract_check", "security_scan", "coverage_check", "gate_fixes", "merge_decision"]},
        "deploy": {"steps": ["deploy_trigger", "health_check", "deploy_decision"]},
        "wisdom": {"steps": ["artifact_audit", "regression_analysis", "flow_history", "learning_synthesis", "feedback_application", "wisdom_summary"]},
    }
    return MOCK_FLOWS.get(flow_key, {"steps": []})


class FlowStudioLinkGenerator:
    """
    Generate Flow Studio deep links.

    URL format:
        http://localhost:5000/?mode=operator&run=pr-123&flow=build&step=self_review&view=artifacts&tab=run

    Supported parameters:
        - mode: "author" | "operator" (default: author)
        - run: run ID (e.g., "health-check", "pr-123-abc123")
        - flow: flow key (e.g., "signal", "build", "gate")
        - step: step ID within flow (requires flow)
        - view: "agents" | "artifacts" (default: agents)
        - tab: tab in step details (e.g., "spec", "run", "artifacts") (requires step)
    """

    VALID_FLOWS = get_flow_order()
    VALID_MODES = ["author", "operator"]
    VALID_VIEWS = ["agents", "artifacts"]

    def __init__(self, base_url: str = "http://localhost:5000", repo_root: Optional[Path] = None):
        """
        Initialize link generator.

        Args:
            base_url: Base URL for Flow Studio (default: localhost:5000)
            repo_root: Repository root path (auto-detected if not provided)
        """
        self.base_url = base_url.rstrip("/")
        if repo_root is None:
            # Auto-detect from this file's location
            repo_root = Path(__file__).parent.parent.parent
        self.repo_root = Path(repo_root)

    def link(
        self,
        run: str,
        flow: Optional[str] = None,
        step: Optional[str] = None,
        mode: Optional[str] = None,
        view: Optional[str] = None,
        tab: Optional[str] = None,
    ) -> str:
        """
        Generate a Flow Studio deep link.

        Args:
            run: Run ID (required)
            flow: Flow key (optional)
            step: Step ID (optional, requires flow)
            mode: Mode (optional, "author" or "operator")
            view: View mode (optional, "agents" or "artifacts")
            tab: Tab name (optional, requires step)

        Returns:
            Full URL with query parameters

        Raises:
            ValueError: If parameters are invalid or incompatible
        """
        # Validate required
        if not run:
            raise ValueError("run parameter is required")

        # Validate step requires flow
        if step and not flow:
            raise ValueError("step parameter requires flow to be specified")

        # Validate tab requires step
        if tab and not step:
            raise ValueError("tab parameter requires step to be specified")

        # Validate flow is valid
        if flow and flow not in self.VALID_FLOWS:
            raise ValueError(f"Invalid flow '{flow}'. Must be one of: {', '.join(self.VALID_FLOWS)}")

        # Validate mode is valid
        if mode and mode not in self.VALID_MODES:
            raise ValueError(f"Invalid mode '{mode}'. Must be one of: {', '.join(self.VALID_MODES)}")

        # Validate view is valid
        if view and view not in self.VALID_VIEWS:
            raise ValueError(f"Invalid view '{view}'. Must be one of: {', '.join(self.VALID_VIEWS)}")

        # Validate step exists in flow (if both specified)
        if flow and step:
            flow_config = _load_flow_config(flow)
            valid_steps = flow_config.get("steps", [])
            if step not in valid_steps:
                raise ValueError(
                    f"Invalid step '{step}' for flow '{flow}'. "
                    f"Valid steps: {', '.join(valid_steps)}"
                )

        # Build query parameters
        params = {}

        # Always include run
        params["run"] = run

        # Add mode if specified and not default
        if mode and mode != "author":
            params["mode"] = mode

        # Add flow if specified
        if flow:
            params["flow"] = flow

        # Add step if specified
        if step:
            params["step"] = step

        # Add view if specified and not default
        if view and view != "agents":
            params["view"] = view

        # Add tab if specified
        if tab:
            params["tab"] = tab

        # Construct URL
        if params:
            query_string = urlencode(params)
            return f"{self.base_url}/?{query_string}"
        else:
            return self.base_url

    def get_available_flows(self) -> list[str]:
        """Get list of valid flow keys."""
        return self.VALID_FLOWS.copy()

    def get_flow_steps(self, flow_key: str) -> list[str]:
        """
        Get list of valid step IDs for a flow.

        Args:
            flow_key: Flow key

        Returns:
            List of step IDs

        Raises:
            ValueError: If flow is invalid
        """
        if flow_key not in self.VALID_FLOWS:
            raise ValueError(f"Invalid flow '{flow_key}'")

        flow_config = _load_flow_config(flow_key)
        return flow_config.get("steps", [])


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Generate Flow Studio deep links for runs, flows, and steps",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Link to a run
  %(prog)s --run health-check

  # Link to a flow in operator mode
  %(prog)s --run pr-123 --flow build --mode operator

  # Link to a step with artifacts view
  %(prog)s --run pr-123 --flow gate --step merge_decision --view artifacts

  # Link to specific tab in step details
  %(prog)s --run pr-123 --flow gate --step merge_decision --tab run

  # JSON output
  %(prog)s --run pr-123 --flow build --json

  # Custom base URL
  %(prog)s --run pr-123 --base-url https://flow-studio.example.com

Valid flows: signal, plan, build, gate, deploy, wisdom
Valid modes: author, operator
Valid views: agents, artifacts
        """
    )

    parser.add_argument(
        "--run", "-r",
        required=True,
        help="Run ID (e.g., health-check, pr-123-abc123)"
    )

    parser.add_argument(
        "--flow", "-f",
        choices=FlowStudioLinkGenerator.VALID_FLOWS,
        help="Flow key"
    )

    parser.add_argument(
        "--step", "-s",
        help="Step ID within flow (requires --flow)"
    )

    parser.add_argument(
        "--mode", "-m",
        choices=FlowStudioLinkGenerator.VALID_MODES,
        help="Mode (author or operator)"
    )

    parser.add_argument(
        "--view", "-v",
        choices=FlowStudioLinkGenerator.VALID_VIEWS,
        help="View mode (agents or artifacts)"
    )

    parser.add_argument(
        "--tab", "-t",
        help="Tab in step details (requires --step)"
    )

    parser.add_argument(
        "--base-url", "-b",
        default="http://localhost:5000",
        help="Base URL for Flow Studio (default: http://localhost:5000)"
    )

    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON instead of plain URL"
    )

    parser.add_argument(
        "--list-flows",
        action="store_true",
        help="List available flows and exit"
    )

    parser.add_argument(
        "--list-steps",
        metavar="FLOW",
        help="List steps for a flow and exit"
    )

    args = parser.parse_args()

    # Initialize generator
    gen = FlowStudioLinkGenerator(base_url=args.base_url)

    # Handle list commands
    if args.list_flows:
        flows = gen.get_available_flows()
        if args.json:
            print(json.dumps({"flows": flows}, indent=2))
        else:
            print("Available flows:")
            for flow in flows:
                print(f"  - {flow}")
        return

    if args.list_steps:
        try:
            steps = gen.get_flow_steps(args.list_steps)
            if args.json:
                print(json.dumps({"flow": args.list_steps, "steps": steps}, indent=2))
            else:
                print(f"Steps in flow '{args.list_steps}':")
                for step in steps:
                    print(f"  - {step}")
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
        return

    # Generate link
    try:
        url = gen.link(
            run=args.run,
            flow=args.flow,
            step=args.step,
            mode=args.mode,
            view=args.view,
            tab=args.tab,
        )

        if args.json:
            output = {
                "url": url,
                "params": {
                    "run": args.run,
                }
            }
            if args.flow:
                output["params"]["flow"] = args.flow
            if args.step:
                output["params"]["step"] = args.step
            if args.mode:
                output["params"]["mode"] = args.mode
            if args.view:
                output["params"]["view"] = args.view
            if args.tab:
                output["params"]["tab"] = args.tab

            print(json.dumps(output, indent=2))
        else:
            print(url)

    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()


# Example usage as a library:

if __name__ == "__main__":
    # Example: Generate links programmatically
    gen = FlowStudioLinkGenerator()

    # Basic run link
    url1 = gen.link(run="health-check")
    print(f"Run link: {url1}")

    # Flow link in operator mode
    url2 = gen.link(run="pr-123", flow="build", mode="operator")
    print(f"Flow link: {url2}")

    # Step link with artifacts view
    url3 = gen.link(run="pr-123", flow="gate", step="merge_decision", view="artifacts")
    print(f"Step link: {url3}")

    # Full link with all parameters
    url4 = gen.link(
        run="pr-123",
        flow="gate",
        step="merge_decision",
        mode="operator",
        view="artifacts",
        tab="run"
    )
    print(f"Full link: {url4}")
