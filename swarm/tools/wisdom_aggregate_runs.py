#!/usr/bin/env python3
"""Wisdom aggregate runs tool.

Aggregates wisdom_summary.json files across multiple runs to produce
cross-run analysis and trend reports.

Usage:
    uv run swarm/tools/wisdom_aggregate_runs.py
    uv run swarm/tools/wisdom_aggregate_runs.py --markdown
    uv run swarm/tools/wisdom_aggregate_runs.py --output path/to/output.json
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from swarm.config.flow_registry import get_flow_order
from swarm.runtime.storage import EXAMPLES_DIR, RUNS_DIR

logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
)
logger = logging.getLogger(__name__)


def discover_wisdom_summaries() -> List[Dict[str, Any]]:
    """Find all wisdom_summary.json files across runs and examples."""
    summaries: List[Dict[str, Any]] = []

    # Check examples
    if EXAMPLES_DIR.exists():
        for run_dir in EXAMPLES_DIR.iterdir():
            if run_dir.is_dir() and not run_dir.name.startswith("."):
                summary_path = run_dir / "wisdom" / "wisdom_summary.json"
                if summary_path.exists():
                    try:
                        with open(summary_path, "r", encoding="utf-8") as f:
                            data = json.load(f)
                            data["_source"] = "example"
                            data["_path"] = str(summary_path)
                            summaries.append(data)
                    except (json.JSONDecodeError, OSError) as e:
                        logger.warning(f"Failed to read {summary_path}: {e}")

    # Check active runs
    if RUNS_DIR.exists():
        for run_dir in RUNS_DIR.iterdir():
            if run_dir.is_dir() and not run_dir.name.startswith("."):
                summary_path = run_dir / "wisdom" / "wisdom_summary.json"
                if summary_path.exists():
                    try:
                        with open(summary_path, "r", encoding="utf-8") as f:
                            data = json.load(f)
                            data["_source"] = "active"
                            data["_path"] = str(summary_path)
                            summaries.append(data)
                    except (json.JSONDecodeError, OSError) as e:
                        logger.warning(f"Failed to read {summary_path}: {e}")

    return summaries


def aggregate_summaries(summaries: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Aggregate multiple wisdom summaries into a cross-run report."""
    if not summaries:
        return {
            "aggregated_at": datetime.now(timezone.utc).isoformat(),
            "runs_analyzed": 0,
            "message": "No wisdom summaries found",
        }

    # Initialize aggregation (from registry, includes review)
    flow_success_counts: Dict[str, Dict[str, int]] = {
        flow: {"succeeded": 0, "failed": 0, "skipped": 0}
        for flow in get_flow_order()
    }

    total_regressions = 0
    total_learnings = 0
    total_feedback_actions = 0
    total_issues = 0
    total_artifacts = 0

    label_counts: Dict[str, int] = {}
    run_ids: List[str] = []

    for summary in summaries:
        run_id = summary.get("run_id", "unknown")
        run_ids.append(run_id)

        # Aggregate flow statuses
        flows = summary.get("flows", {})
        for flow_key, flow_data in flows.items():
            if flow_key in flow_success_counts:
                status = flow_data.get("status", "skipped")
                if status in flow_success_counts[flow_key]:
                    flow_success_counts[flow_key][status] += 1

        # Aggregate summary counts
        summ = summary.get("summary", {})
        total_regressions += summ.get("regressions_found", 0)
        total_learnings += summ.get("learnings_count", 0)
        total_feedback_actions += summ.get("feedback_actions_count", 0)
        total_issues += summ.get("issues_created", 0)
        total_artifacts += summ.get("artifacts_present", 0)

        # Aggregate labels
        labels = summary.get("labels", [])
        for label in labels:
            label_counts[label] = label_counts.get(label, 0) + 1

    # Sort labels by frequency
    top_labels = sorted(label_counts.items(), key=lambda x: x[1], reverse=True)[:10]

    # Calculate success rates
    flow_success_rates: Dict[str, float] = {}
    for flow_key, counts in flow_success_counts.items():
        total = counts["succeeded"] + counts["failed"]
        if total > 0:
            flow_success_rates[flow_key] = counts["succeeded"] / total
        else:
            flow_success_rates[flow_key] = 0.0

    return {
        "aggregated_at": datetime.now(timezone.utc).isoformat(),
        "runs_analyzed": len(summaries),
        "run_ids": run_ids,
        "flow_success_rates": {
            flow: f"{rate:.1%}" for flow, rate in flow_success_rates.items()
        },
        "flow_counts": flow_success_counts,
        "totals": {
            "regressions_found": total_regressions,
            "learnings_extracted": total_learnings,
            "feedback_actions": total_feedback_actions,
            "issues_created": total_issues,
            "artifacts_produced": total_artifacts,
        },
        "averages": {
            "regressions_per_run": total_regressions / len(summaries),
            "learnings_per_run": total_learnings / len(summaries),
            "artifacts_per_run": total_artifacts / len(summaries),
        },
        "top_labels": [{"label": label, "count": count} for label, count in top_labels],
    }


def format_markdown(aggregate: Dict[str, Any]) -> str:
    """Format aggregation as markdown report."""
    lines = [
        "# Wisdom Aggregation Report",
        "",
        f"**Generated:** {aggregate.get('aggregated_at', 'unknown')}",
        f"**Runs Analyzed:** {aggregate.get('runs_analyzed', 0)}",
        "",
        "## Flow Success Rates",
        "",
        "| Flow | Success Rate |",
        "|------|-------------|",
    ]

    for flow, rate in aggregate.get("flow_success_rates", {}).items():
        lines.append(f"| {flow} | {rate} |")

    lines.extend([
        "",
        "## Aggregate Totals",
        "",
    ])

    totals = aggregate.get("totals", {})
    for key, value in totals.items():
        lines.append(f"- **{key.replace('_', ' ').title()}:** {value}")

    lines.extend([
        "",
        "## Averages Per Run",
        "",
    ])

    averages = aggregate.get("averages", {})
    for key, value in averages.items():
        lines.append(f"- **{key.replace('_', ' ').title()}:** {value:.2f}")

    lines.extend([
        "",
        "## Top Labels",
        "",
    ])

    for item in aggregate.get("top_labels", []):
        lines.append(f"- {item['label']}: {item['count']} runs")

    lines.extend([
        "",
        "---",
        "",
        "*Generated by wisdom_aggregate_runs.py*",
    ])

    return "\n".join(lines)


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Aggregate wisdom summaries across runs",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--markdown", "-m",
        action="store_true",
        help="Output as markdown instead of JSON",
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        help="Write output to file instead of stdout",
    )

    args = parser.parse_args()

    # Discover and aggregate
    summaries = discover_wisdom_summaries()
    aggregate = aggregate_summaries(summaries)

    # Format output
    if args.markdown:
        output = format_markdown(aggregate)
    else:
        output = json.dumps(aggregate, indent=2, ensure_ascii=False)

    # Write output
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output, encoding="utf-8")
        logger.info(f"Report written to {args.output}")
    else:
        print(output)

    return 0


if __name__ == "__main__":
    sys.exit(main())
