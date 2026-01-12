#!/usr/bin/env python3
"""
Wisdom Summarizer

Reads wisdom artifacts from a run and produces a structured wisdom_summary.json.

This module consolidates Flow 6 (Wisdom) outputs into a machine-readable summary
that can be used for dashboards, trend analysis, and cross-run comparisons.

Usage:
    uv run swarm/tools/wisdom_summarizer.py <run_id>

    # Or from Python:
    from swarm.tools.wisdom_summarizer import WisdomSummarizer
    summarizer = WisdomSummarizer()
    summary = summarizer.generate_summary("health-check-risky-deploy")
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# Add repo root to path for imports
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from swarm.config.flow_registry import get_flow_order


@dataclass
class FlowSummary:
    """Summary of a single flow's execution status."""

    status: str  # succeeded, failed, skipped
    microloops: int = 0
    test_loops: int = 0
    code_loops: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary, excluding zero-valued loop counts."""
        result: dict[str, Any] = {"status": self.status}
        if self.microloops > 0:
            result["microloops"] = self.microloops
        if self.test_loops > 0:
            result["test_loops"] = self.test_loops
        if self.code_loops > 0:
            result["code_loops"] = self.code_loops
        return result


@dataclass
class WisdomSummary:
    """Complete wisdom summary for a run."""

    run_id: str
    created_at: str
    flows: dict[str, FlowSummary]
    summary: dict[str, int]
    labels: list[str]
    key_artifacts: dict[str, str]

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dictionary."""
        return {
            "run_id": self.run_id,
            "created_at": self.created_at,
            "flows": {k: v.to_dict() for k, v in self.flows.items()},
            "summary": self.summary,
            "labels": self.labels,
            "key_artifacts": self.key_artifacts,
        }


class WisdomSummarizer:
    """
    Summarizer for Flow 6 (Wisdom) artifacts.

    Reads wisdom artifacts from a run and produces a structured summary
    in JSON format that captures key metrics and metadata.
    """

    # Standard flow keys in execution order (from registry, includes review)
    FLOW_KEYS = get_flow_order()

    # Wisdom artifacts to look for
    WISDOM_ARTIFACTS = [
        "artifact_audit.md",
        "regression_report.md",
        "flow_history.json",
        "learnings.md",
        "feedback_actions.md",
    ]

    def __init__(self, repo_root: Optional[Path] = None):
        """
        Initialize the summarizer.

        Args:
            repo_root: Repository root path. Auto-detected if not provided.
        """
        if repo_root is None:
            repo_root = Path(__file__).parent.parent.parent
        self.repo_root = Path(repo_root)
        self.runs_dir = self.repo_root / "swarm" / "runs"
        self.examples_dir = self.repo_root / "swarm" / "examples"

    def get_run_path(self, run_id: str) -> Optional[Path]:
        """
        Get the filesystem path for a run.

        Args:
            run_id: Run identifier

        Returns:
            Path to the run directory, or None if not found.
        """
        # Check examples first
        example_path = self.examples_dir / run_id
        if example_path.exists():
            return example_path

        # Then active runs
        active_path = self.runs_dir / run_id
        if active_path.exists():
            return active_path

        return None

    def _read_file(self, path: Path) -> Optional[str]:
        """Read a file, returning None if it doesn't exist or can't be read."""
        if not path.exists():
            return None
        try:
            return path.read_text(encoding="utf-8")
        except (IOError, UnicodeDecodeError):
            return None

    def _read_json(self, path: Path) -> Optional[dict]:
        """Read a JSON file, returning None if it doesn't exist or is invalid."""
        content = self._read_file(path)
        if content is None:
            return None
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return None

    def _parse_flow_history(self, flow_history: dict) -> dict[str, FlowSummary]:
        """
        Parse flow_history.json to extract flow statuses and loop counts.

        Args:
            flow_history: Parsed flow_history.json data

        Returns:
            Dictionary mapping flow keys to FlowSummary objects.
        """
        flows: dict[str, FlowSummary] = {}

        # Initialize all flows as skipped
        for flow_key in self.FLOW_KEYS:
            flows[flow_key] = FlowSummary(status="skipped")

        # Parse execution timeline
        execution_timeline = flow_history.get("execution_timeline", [])
        for entry in execution_timeline:
            flow_key = entry.get("flow", "")
            if flow_key not in self.FLOW_KEYS:
                continue

            # Determine status from decision
            decision = entry.get("decision", "")
            if decision in ("BOUNCE", "BLOCKED", "FAILED"):
                status = "failed"
            elif decision in ("SKIP", "SKIPPED"):
                status = "skipped"
            else:
                status = "succeeded"

            # Extract microloop iterations
            microloop_data = entry.get("microloop_iterations", {})
            test_loops = microloop_data.get("test_loop", 0)
            code_loops = microloop_data.get("code_loop", 0)

            # For signal flow, check for requirements loop
            req_loops = microloop_data.get("requirements_loop", 0)
            microloops = req_loops if flow_key == "signal" else 0

            flows[flow_key] = FlowSummary(
                status=status,
                microloops=microloops,
                test_loops=test_loops,
                code_loops=code_loops,
            )

        return flows

    def _infer_flow_status_from_artifacts(
        self, run_path: Path
    ) -> dict[str, FlowSummary]:
        """
        Infer flow statuses from presence of decision artifacts.

        Fallback when flow_history.json is not available.

        Args:
            run_path: Path to the run directory

        Returns:
            Dictionary mapping flow keys to FlowSummary objects.
        """
        flows: dict[str, FlowSummary] = {}

        # Decision artifacts for each flow (primary and alternatives)
        # Uses list of possible filenames since naming varies across runs
        decision_artifacts = {
            "signal": ["problem_statement.md"],
            "plan": ["adr.md", "adr_current.md"],
            "build": ["build_receipt.json", "impl_changes_summary.md"],
            "gate": ["merge_recommendation.md", "merge_decision.md"],
            "deploy": ["deployment_decision.md", "deployment_log.md"],
            "wisdom": ["learnings.md", "wisdom_summary.json"],
        }

        for flow_key in self.FLOW_KEYS:
            flow_dir = run_path / flow_key
            if not flow_dir.exists():
                flows[flow_key] = FlowSummary(status="skipped")
                continue

            decision_files = decision_artifacts.get(flow_key, [])
            has_decision = any(
                (flow_dir / df).exists() for df in decision_files
            )
            if has_decision:
                flows[flow_key] = FlowSummary(status="succeeded")
            else:
                # Directory exists but no decision artifact - assume in progress or failed
                # Check if any files exist
                files = list(flow_dir.glob("*"))
                if files:
                    flows[flow_key] = FlowSummary(status="failed")
                else:
                    flows[flow_key] = FlowSummary(status="skipped")

        return flows

    def _count_headings(self, content: str) -> int:
        """
        Count markdown headings to estimate learnings count.

        Counts ## and ### level headings, excluding the document title.

        Args:
            content: Markdown file content

        Returns:
            Count of section headings.
        """
        # Match ## or ### at start of line (not #)
        pattern = r"^#{2,3}\s+\S"
        matches = re.findall(pattern, content, re.MULTILINE)
        return len(matches)

    def _count_action_items(self, content: str) -> int:
        """
        Count action items (checkboxes) in feedback_actions.md.

        Looks for patterns like:
        - [ ] Action item
        - [x] Completed item

        Args:
            content: Markdown file content

        Returns:
            Count of action items (both checked and unchecked).
        """
        pattern = r"^-\s+\[[ xX]\]"
        matches = re.findall(pattern, content, re.MULTILINE)
        return len(matches)

    def _count_regressions(self, content: str) -> int:
        """
        Count regressions found in regression_report.md.

        Looks for patterns indicating regressions or returns 0 if none found.

        Args:
            content: Markdown file content

        Returns:
            Count of regressions detected.
        """
        # Check for "NO REGRESSIONS" pattern
        if re.search(r"NO\s+REGRESSIONS?\s+(DETECTED|FOUND)", content, re.IGNORECASE):
            return 0

        # Count lines that look like regression entries
        # Patterns: "- REGRESSION:", "**Regression**:", numbered regression items
        regression_patterns = [
            r"^-\s+REGRESSION:",
            r"^\*\*Regression\*\*:",
            r"^##.*[Rr]egression\s*#?\d+",
            r"^\d+\.\s+\*\*Regression\*\*",
        ]

        total = 0
        for pattern in regression_patterns:
            matches = re.findall(pattern, content, re.MULTILINE)
            total += len(matches)

        return total

    def _count_issues_created(self, content: str) -> int:
        """
        Count issues to be created from feedback_actions.md.

        Looks for "Issue to Create" sections.

        Args:
            content: Markdown file content

        Returns:
            Count of issues to create.
        """
        pattern = r"###\s+Issue to Create"
        matches = re.findall(pattern, content, re.IGNORECASE)
        return len(matches)

    def _extract_labels(
        self,
        flow_history: Optional[dict],
        artifact_audit: Optional[str],
        learnings: Optional[str],
    ) -> list[str]:
        """
        Extract labels/tags for the run.

        Args:
            flow_history: Parsed flow_history.json data
            artifact_audit: Content of artifact_audit.md
            learnings: Content of learnings.md

        Returns:
            List of relevant labels.
        """
        labels: list[str] = []

        # Extract from flow_history outcome
        if flow_history:
            outcome = flow_history.get("outcome", "")
            if outcome:
                labels.append(outcome.lower().replace("_", "-"))

        # Check for risk management
        if learnings and re.search(r"risk", learnings, re.IGNORECASE):
            labels.append("risk-managed")

        # Check for conditional approval
        if learnings and re.search(
            r"conditional\s+approv", learnings, re.IGNORECASE
        ):
            labels.append("conditional-approval")

        # Check artifact completeness
        if artifact_audit:
            if re.search(r"COMPLETE", artifact_audit):
                labels.append("complete-artifacts")
            if re.search(r"Gaps?\s+Identified.*None", artifact_audit, re.IGNORECASE):
                labels.append("no-gaps")

        return sorted(set(labels))

    def generate_summary(self, run_id: str) -> Optional[WisdomSummary]:
        """
        Generate a wisdom summary for a run.

        Args:
            run_id: Run identifier

        Returns:
            WisdomSummary object, or None if run not found.
        """
        run_path = self.get_run_path(run_id)
        if run_path is None:
            return None

        wisdom_dir = run_path / "wisdom"

        # Read all wisdom artifacts
        artifact_audit = self._read_file(wisdom_dir / "artifact_audit.md")
        regression_report = self._read_file(wisdom_dir / "regression_report.md")
        flow_history = self._read_json(wisdom_dir / "flow_history.json")
        learnings = self._read_file(wisdom_dir / "learnings.md")
        feedback_actions = self._read_file(wisdom_dir / "feedback_actions.md")

        # Parse flow statuses
        if flow_history:
            flows = self._parse_flow_history(flow_history)
        else:
            flows = self._infer_flow_status_from_artifacts(run_path)

        # Count artifacts present
        artifacts_present = sum(
            1
            for artifact in self.WISDOM_ARTIFACTS
            if (wisdom_dir / artifact).exists()
        )

        # Count regressions
        regressions_found = 0
        if regression_report:
            regressions_found = self._count_regressions(regression_report)

        # Count learnings (sections in learnings.md)
        learnings_count = 0
        if learnings:
            learnings_count = self._count_headings(learnings)

        # Count feedback actions
        feedback_actions_count = 0
        issues_created = 0
        if feedback_actions:
            feedback_actions_count = self._count_action_items(feedback_actions)
            issues_created = self._count_issues_created(feedback_actions)

        # Extract labels
        labels = self._extract_labels(flow_history, artifact_audit, learnings)

        # Build key artifacts map
        key_artifacts: dict[str, str] = {}
        if artifact_audit:
            key_artifacts["artifact_audit"] = "wisdom/artifact_audit.md"
        if regression_report:
            key_artifacts["regression_report"] = "wisdom/regression_report.md"
        if learnings:
            key_artifacts["learnings"] = "wisdom/learnings.md"
        if flow_history:
            key_artifacts["flow_history"] = "wisdom/flow_history.json"
        if feedback_actions:
            key_artifacts["feedback_actions"] = "wisdom/feedback_actions.md"

        # Build summary
        summary = {
            "artifacts_present": artifacts_present,
            "regressions_found": regressions_found,
            "learnings_count": learnings_count,
            "feedback_actions_count": feedback_actions_count,
            "issues_created": issues_created,
        }

        return WisdomSummary(
            run_id=run_id,
            created_at=datetime.now(timezone.utc).isoformat(),
            flows=flows,
            summary=summary,
            labels=labels,
            key_artifacts=key_artifacts,
        )

    def write_summary(self, run_id: str) -> Optional[Path]:
        """
        Generate and write wisdom summary to disk.

        Args:
            run_id: Run identifier

        Returns:
            Path to the written file, or None if run not found.
        """
        summary = self.generate_summary(run_id)
        if summary is None:
            return None

        run_path = self.get_run_path(run_id)
        if run_path is None:
            return None

        wisdom_dir = run_path / "wisdom"
        wisdom_dir.mkdir(parents=True, exist_ok=True)

        output_path = wisdom_dir / "wisdom_summary.json"
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(summary.to_dict(), f, indent=2)

        return output_path


def main() -> int:
    """CLI entrypoint for wisdom summarizer."""
    parser = argparse.ArgumentParser(
        description="Generate wisdom summary from run artifacts"
    )
    parser.add_argument(
        "run_id",
        help="Run identifier (e.g., health-check-risky-deploy)",
    )
    parser.add_argument(
        "--output",
        "-o",
        choices=["json", "path", "quiet"],
        default="json",
        help="Output format: json (print summary), path (print output path), quiet (no output)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Generate summary but don't write to disk",
    )

    args = parser.parse_args()

    summarizer = WisdomSummarizer()

    if args.dry_run:
        summary = summarizer.generate_summary(args.run_id)
        if summary is None:
            print(f"Error: Run '{args.run_id}' not found", file=sys.stderr)
            return 1
        if args.output == "json":
            print(json.dumps(summary.to_dict(), indent=2))
        return 0

    output_path = summarizer.write_summary(args.run_id)
    if output_path is None:
        print(f"Error: Run '{args.run_id}' not found", file=sys.stderr)
        return 1

    if args.output == "json":
        summary = summarizer.generate_summary(args.run_id)
        if summary:
            print(json.dumps(summary.to_dict(), indent=2))
    elif args.output == "path":
        print(output_path)

    return 0


if __name__ == "__main__":
    sys.exit(main())
