#!/usr/bin/env python3
"""
Run Inspector - Utility for checking artifact status in swarm runs.

This module provides Flow Studio with the ability to:
1. Discover available runs (active + examples)
2. Check artifact status for a specific (run_id, flow, step)
3. Compute flow-level and run-level summaries

Usage:
    from swarm.tools.run_inspector import RunInspector

    inspector = RunInspector()
    runs = inspector.list_runs()
    status = inspector.get_step_status("demo-health-check", "build", "self_review")
    summary = inspector.get_run_summary("demo-health-check")
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Optional

# Add repo root to path for imports
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from swarm.config.flow_registry import get_sdlc_flow_keys  # noqa: E402
from swarm.flowstudio.schema import StepStatusEnum  # noqa: E402

# Canonical step artifact status - imported from flowstudio.schema
# Aliased as StepStatus for backward compatibility within this module
StepStatus = StepStatusEnum


class ArtifactStatus(str, Enum):
    """Status of a single artifact."""
    PRESENT = "present"
    MISSING = "missing"


class FlowStatus(str, Enum):
    """Aggregate status of a flow based on decision artifact."""
    NOT_STARTED = "not_started"    # No flow directory
    IN_PROGRESS = "in_progress"    # Directory exists, no decision artifact
    DONE = "done"                  # Decision artifact exists


@dataclass
class ArtifactResult:
    """Status of a single artifact check."""
    path: str
    status: ArtifactStatus
    required: bool


@dataclass
class StepResult:
    """Aggregate result for a step's artifacts."""
    step_id: str
    status: StepStatus
    required_present: int
    required_total: int
    optional_present: int
    optional_total: int
    artifacts: list[ArtifactResult] = field(default_factory=list)
    note: Optional[str] = None


@dataclass
class FlowResult:
    """Aggregate result for a flow."""
    flow_key: str
    status: FlowStatus
    title: str
    decision_artifact: Optional[str]
    decision_present: bool
    steps: dict[str, StepResult] = field(default_factory=dict)


@dataclass
class RunResult:
    """Aggregate result for an entire run."""
    run_id: str
    run_type: str  # "active" | "example"
    path: str
    flows: dict[str, FlowResult] = field(default_factory=dict)


@dataclass
class FlowEvent:
    """Single event in flow history."""
    timestamp: str  # ISO 8601
    flow: str
    step: Optional[str]
    status: str  # started, completed, failed
    duration_ms: Optional[int]
    note: Optional[str]


@dataclass
class StepTiming:
    """Timing for a single step."""
    step_id: str
    started_at: Optional[str]
    ended_at: Optional[str]
    duration_seconds: Optional[float]


@dataclass
class FlowTiming:
    """Timing for a flow."""
    flow_key: str
    started_at: Optional[str]
    ended_at: Optional[str]
    duration_seconds: Optional[float]
    steps: list[StepTiming] = field(default_factory=list)


@dataclass
class RunTiming:
    """Complete timing for a run."""
    run_id: str
    started_at: Optional[str]
    ended_at: Optional[str]
    total_duration_seconds: Optional[float]
    flows: dict[str, FlowTiming] = field(default_factory=dict)


class RunInspector:
    """
    Inspector for checking artifact status in swarm runs.

    Loads the artifact catalog from swarm/meta/artifact_catalog.json
    and provides methods to check artifact presence for runs.
    """

    def __init__(self, repo_root: Optional[Path] = None):
        """
        Initialize the inspector.

        Args:
            repo_root: Repository root path. Auto-detected if not provided.
        """
        if repo_root is None:
            # Auto-detect from this file's location
            repo_root = Path(__file__).parent.parent.parent
        self.repo_root = Path(repo_root)
        self.runs_dir = self.repo_root / "swarm" / "runs"
        self.examples_dir = self.repo_root / "swarm" / "examples"
        self.catalog = self._load_catalog()

    def _load_catalog(self) -> dict:
        """Load the artifact catalog from swarm/meta/artifact_catalog.json."""
        catalog_path = self.repo_root / "swarm" / "meta" / "artifact_catalog.json"
        if not catalog_path.exists():
            return {"flows": {}}
        with open(catalog_path) as f:
            return json.load(f)

    def _load_run_metadata(self, run_path: Path) -> dict:
        """
        Load run metadata from run.json if present.

        Args:
            run_path: Path to the run directory

        Returns:
            Dict with title, description, tags, or empty dict if no metadata.
        """
        metadata_path = run_path / "run.json"
        if not metadata_path.exists():
            return {}
        try:
            with open(metadata_path) as f:
                data = json.load(f)
            return {
                "title": data.get("title", ""),
                "description": data.get("description", ""),
                "tags": data.get("tags", []),
            }
        except (json.JSONDecodeError, IOError):
            return {}

    def list_runs(self) -> list[dict]:
        """
        List all available runs (active + examples).

        Delegates to RunService for consistent run discovery and metadata.
        Falls back to legacy implementation if RunService is unavailable.

        Returns:
            List of dicts with run_id, run_type, path, and optional metadata
            (title, description, tags from run.json if present).
        """
        # Try to delegate to RunService for unified run listing
        try:
            from swarm.runtime.service import RunService
            service = RunService.get_instance(self.repo_root)
            summaries = service.list_runs(
                include_legacy=True,
                include_examples=True,
            )

            # Convert RunSummary objects to backward-compatible dict format
            runs = []
            for summary in summaries:
                # Determine run_type from tags
                if "example" in summary.tags:
                    run_type = "example"
                else:
                    run_type = "active"

                run_data = {
                    "run_id": summary.id,
                    "run_type": run_type,
                    "path": summary.path or "",
                }

                # Add optional metadata
                if summary.title:
                    run_data["title"] = summary.title
                if summary.description:
                    run_data["description"] = summary.description
                # Extract tags (excluding type markers)
                filtered_tags = [t for t in summary.tags if t not in ("example", "legacy")]
                if filtered_tags:
                    run_data["tags"] = filtered_tags

                runs.append(run_data)

            return runs
        except ImportError:
            # Fall back to legacy implementation
            return self._list_runs_legacy()

    def _list_runs_legacy(self) -> list[dict]:
        """
        Legacy implementation of list_runs (fallback).

        Returns:
            List of dicts with run_id, run_type, path, and optional metadata.
        """
        runs = []

        # Active runs (gitignored)
        if self.runs_dir.exists():
            for entry in self.runs_dir.iterdir():
                if entry.is_dir() and not entry.name.startswith("."):
                    run_data = {
                        "run_id": entry.name,
                        "run_type": "active",
                        "path": str(entry),
                    }
                    # Load optional metadata
                    metadata = self._load_run_metadata(entry)
                    run_data.update(metadata)
                    runs.append(run_data)

        # Example runs (committed)
        if self.examples_dir.exists():
            for entry in self.examples_dir.iterdir():
                if entry.is_dir() and not entry.name.startswith("."):
                    run_data = {
                        "run_id": entry.name,
                        "run_type": "example",
                        "path": str(entry),
                    }
                    # Load optional metadata
                    metadata = self._load_run_metadata(entry)
                    run_data.update(metadata)
                    runs.append(run_data)

        # Sort: examples first, then active by name
        runs.sort(key=lambda r: (0 if r["run_type"] == "example" else 1, r["run_id"]))
        return runs

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

    def get_step_status(
        self,
        run_id: str,
        flow_key: str,
        step_id: str,
    ) -> StepResult:
        """
        Get artifact status for a specific step.

        Args:
            run_id: Run identifier
            flow_key: Flow key (e.g., "build")
            step_id: Step identifier (e.g., "self_review")

        Returns:
            StepResult with artifact statuses.
        """
        run_path = self.get_run_path(run_id)
        flow_dir = run_path / flow_key if run_path else None

        # Get step config from catalog
        flow_config = self.catalog.get("flows", {}).get(flow_key, {})
        step_config = flow_config.get("steps", {}).get(step_id, {})

        required = step_config.get("required", [])
        optional = step_config.get("optional", [])
        note = step_config.get("note")

        artifacts = []
        required_present = 0
        optional_present = 0

        # Check required artifacts
        for artifact in required:
            path = flow_dir / artifact if flow_dir else None
            present = path.exists() if path else False
            if present:
                required_present += 1
            artifacts.append(ArtifactResult(
                path=artifact,
                status=ArtifactStatus.PRESENT if present else ArtifactStatus.MISSING,
                required=True,
            ))

        # Check optional artifacts
        for artifact in optional:
            path = flow_dir / artifact if flow_dir else None
            present = path.exists() if path else False
            if present:
                optional_present += 1
            artifacts.append(ArtifactResult(
                path=artifact,
                status=ArtifactStatus.PRESENT if present else ArtifactStatus.MISSING,
                required=False,
            ))

        # Compute aggregate status
        if len(required) == 0:
            status = StepStatus.NOT_APPLICABLE
        elif required_present == len(required):
            status = StepStatus.COMPLETE
        elif required_present > 0:
            status = StepStatus.PARTIAL
        else:
            status = StepStatus.MISSING

        return StepResult(
            step_id=step_id,
            status=status,
            required_present=required_present,
            required_total=len(required),
            optional_present=optional_present,
            optional_total=len(optional),
            artifacts=artifacts,
            note=note,
        )

    def get_flow_status(self, run_id: str, flow_key: str) -> FlowResult:
        """
        Get aggregate status for a flow.

        Args:
            run_id: Run identifier
            flow_key: Flow key

        Returns:
            FlowResult with flow and step statuses.
        """
        run_path = self.get_run_path(run_id)
        flow_dir = run_path / flow_key if run_path else None

        flow_config = self.catalog.get("flows", {}).get(flow_key, {})
        title = flow_config.get("title", flow_key.title())
        decision_artifact = flow_config.get("decision_artifact")

        # Check flow directory and decision artifact
        if flow_dir is None or not flow_dir.exists():
            flow_status = FlowStatus.NOT_STARTED
            decision_present = False
        elif decision_artifact and (flow_dir / decision_artifact).exists():
            flow_status = FlowStatus.DONE
            decision_present = True
        else:
            flow_status = FlowStatus.IN_PROGRESS
            decision_present = False

        # Get step statuses
        steps = {}
        for step_id in flow_config.get("steps", {}).keys():
            steps[step_id] = self.get_step_status(run_id, flow_key, step_id)

        return FlowResult(
            flow_key=flow_key,
            status=flow_status,
            title=title,
            decision_artifact=decision_artifact,
            decision_present=decision_present,
            steps=steps,
        )

    def get_run_summary(self, run_id: str) -> RunResult:
        """
        Get complete status summary for a run.

        Args:
            run_id: Run identifier

        Returns:
            RunResult with all flow and step statuses.
        """
        run_path = self.get_run_path(run_id)

        if run_path is None:
            run_type = "unknown"
            path = ""
        elif "examples" in str(run_path):
            run_type = "example"
            path = str(run_path)
        else:
            run_type = "active"
            path = str(run_path)

        flows = {}
        # Use SDLC flows only (excludes demo/test flows like stepwise-demo)
        for flow_key in get_sdlc_flow_keys():
            flows[flow_key] = self.get_flow_status(run_id, flow_key)

        return RunResult(
            run_id=run_id,
            run_type=run_type,
            path=path,
            flows=flows,
        )

    def get_sdlc_bar(self, run_id: str) -> list[dict]:
        """
        Get SDLC bar data for UI display.

        Returns a list of flow summaries in SDLC order, suitable for
        rendering the horizontal flow selector with status indicators.

        Args:
            run_id: Run identifier

        Returns:
            List of dicts with flow_key, title, status, decision_status.
        """
        result = []
        # Use SDLC flows only (excludes demo/test flows like stepwise-demo)
        for flow_key in get_sdlc_flow_keys():
            flow_result = self.get_flow_status(run_id, flow_key)
            result.append({
                "flow_key": flow_key,
                "title": flow_result.title,
                "status": flow_result.status.value,
                "decision_artifact": flow_result.decision_artifact,
                "decision_present": flow_result.decision_present,
            })
        return result

    # Status ordering for comparison: higher is better
    _STATUS_ORDER = {
        StepStatus.COMPLETE: 4,
        StepStatus.PARTIAL: 3,
        StepStatus.MISSING: 2,
        StepStatus.NOT_APPLICABLE: 1,
    }

    _FLOW_STATUS_ORDER = {
        FlowStatus.DONE: 3,
        FlowStatus.IN_PROGRESS: 2,
        FlowStatus.NOT_STARTED: 1,
    }

    def compare_flows(self, run_a: str, run_b: str, flow_key: str) -> dict:
        """
        Compare two runs for a specific flow, returning per-step differences.

        Args:
            run_a: First run identifier (baseline)
            run_b: Second run identifier (comparison target)
            flow_key: Flow key to compare

        Returns:
            Dictionary with comparison data including:
            - run_a, run_b: Run identifiers
            - flow: Flow key
            - flow_status: Status of each run for this flow
            - steps: List of step comparisons with status and change direction
            - summary: Counts of improved, regressed, unchanged steps
        """
        flow_a = self.get_flow_status(run_a, flow_key)
        flow_b = self.get_flow_status(run_b, flow_key)

        flow_config = self.catalog.get("flows", {}).get(flow_key, {})
        step_ids = list(flow_config.get("steps", {}).keys())

        steps = []
        improved = 0
        regressed = 0
        unchanged = 0

        for step_id in step_ids:
            step_a = self.get_step_status(run_a, flow_key, step_id)
            step_b = self.get_step_status(run_b, flow_key, step_id)

            # Determine change direction
            order_a = self._STATUS_ORDER.get(step_a.status, 0)
            order_b = self._STATUS_ORDER.get(step_b.status, 0)

            if order_b > order_a:
                change = "improved"
                improved += 1
            elif order_b < order_a:
                change = "regressed"
                regressed += 1
            else:
                change = "unchanged"
                unchanged += 1

            steps.append({
                "step_id": step_id,
                "run_a": {
                    "status": step_a.status.value,
                    "required_present": step_a.required_present,
                    "required_total": step_a.required_total,
                },
                "run_b": {
                    "status": step_b.status.value,
                    "required_present": step_b.required_present,
                    "required_total": step_b.required_total,
                },
                "change": change,
            })

        return {
            "run_a": run_a,
            "run_b": run_b,
            "flow": flow_key,
            "flow_status": {
                "run_a": flow_a.status.value,
                "run_b": flow_b.status.value,
            },
            "steps": steps,
            "summary": {
                "improved": improved,
                "regressed": regressed,
                "unchanged": unchanged,
            },
        }

    def get_run_timeline(self, run_id: str) -> list[FlowEvent]:
        """
        Get chronologically sorted timeline of flow events.

        Args:
            run_id: Run identifier

        Returns:
            List of FlowEvent objects sorted by timestamp, or empty list if no history.
        """
        run_path = self.get_run_path(run_id)
        if run_path is None:
            return []

        # Try wisdom/flow_history.json
        history_path = run_path / "wisdom" / "flow_history.json"
        if not history_path.exists():
            return []

        try:
            with open(history_path) as f:
                data = json.load(f)

            events = []

            # Format 1: New format with "events" array
            if "events" in data:
                for event_data in data.get("events", []):
                    events.append(FlowEvent(
                        timestamp=event_data.get("ts", ""),
                        flow=event_data.get("flow", ""),
                        step=event_data.get("step"),
                        status=event_data.get("status", ""),
                        duration_ms=event_data.get("duration_ms"),
                        note=event_data.get("note"),
                    ))

            # Format 2: Legacy format with "execution_timeline" array
            elif "execution_timeline" in data:
                for flow_data in data.get("execution_timeline", []):
                    flow_key = flow_data.get("flow", "")
                    start_time = flow_data.get("start_time", "")
                    end_time = flow_data.get("end_time", "")
                    duration_min = flow_data.get("duration_minutes")

                    # Create started event
                    if start_time:
                        events.append(FlowEvent(
                            timestamp=start_time,
                            flow=flow_key,
                            step=None,
                            status="started",
                            duration_ms=None,
                            note=flow_data.get("decision"),
                        ))

                    # Create completed event
                    if end_time:
                        events.append(FlowEvent(
                            timestamp=end_time,
                            flow=flow_key,
                            step=None,
                            status="completed",
                            duration_ms=int(duration_min * 60 * 1000)
                            if duration_min
                            else None,
                            note=flow_data.get("decision_artifact"),
                        ))

            # Sort by timestamp
            events.sort(key=lambda e: e.timestamp)
            return events
        except (json.JSONDecodeError, IOError, KeyError):
            return []

    def compute_timing_from_history(self, events: list[FlowEvent]) -> Optional[RunTiming]:
        """
        Compute timing data from event list.

        Args:
            events: List of FlowEvent objects

        Returns:
            RunTiming object or None if no events.
        """
        if not events:
            return None

        # Group events by flow and step
        flow_events: dict[str, list[FlowEvent]] = {}
        step_events: dict[tuple[str, str], list[FlowEvent]] = {}

        for event in events:
            # Track flow-level events
            if event.flow not in flow_events:
                flow_events[event.flow] = []
            flow_events[event.flow].append(event)

            # Track step-level events
            if event.step:
                key = (event.flow, event.step)
                if key not in step_events:
                    step_events[key] = []
                step_events[key].append(event)

        # Compute flow timings
        flows: dict[str, FlowTiming] = {}
        for flow_key, flow_evts in flow_events.items():
            started_events = [e for e in flow_evts if e.status == "started"]
            completed_events = [e for e in flow_evts if e.status == "completed"]

            started_at = min((e.timestamp for e in started_events), default=None)
            ended_at = max((e.timestamp for e in completed_events), default=None)

            # Compute duration
            duration_seconds = None
            if started_at and ended_at:
                try:
                    start_dt = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
                    end_dt = datetime.fromisoformat(ended_at.replace("Z", "+00:00"))
                    duration_seconds = (end_dt - start_dt).total_seconds()
                except (ValueError, AttributeError):
                    pass

            # Compute step timings for this flow
            steps: list[StepTiming] = []
            for (f_key, s_key), step_evts in step_events.items():
                if f_key != flow_key:
                    continue

                step_started = [e for e in step_evts if e.status == "started"]
                step_completed = [e for e in step_evts if e.status == "completed"]

                step_start = min((e.timestamp for e in step_started), default=None)
                step_end = max((e.timestamp for e in step_completed), default=None)

                step_duration = None
                if step_start and step_end:
                    try:
                        s_dt = datetime.fromisoformat(step_start.replace("Z", "+00:00"))
                        e_dt = datetime.fromisoformat(step_end.replace("Z", "+00:00"))
                        step_duration = (e_dt - s_dt).total_seconds()
                    except (ValueError, AttributeError):
                        pass

                steps.append(StepTiming(
                    step_id=s_key,
                    started_at=step_start,
                    ended_at=step_end,
                    duration_seconds=step_duration,
                ))

            flows[flow_key] = FlowTiming(
                flow_key=flow_key,
                started_at=started_at,
                ended_at=ended_at,
                duration_seconds=duration_seconds,
                steps=steps,
            )

        # Compute run-level timing
        all_starts = [f.started_at for f in flows.values() if f.started_at]
        all_ends = [f.ended_at for f in flows.values() if f.ended_at]

        run_started = min(all_starts) if all_starts else None
        run_ended = max(all_ends) if all_ends else None

        run_duration = None
        if run_started and run_ended:
            try:
                start_dt = datetime.fromisoformat(run_started.replace("Z", "+00:00"))
                end_dt = datetime.fromisoformat(run_ended.replace("Z", "+00:00"))
                run_duration = (end_dt - start_dt).total_seconds()
            except (ValueError, AttributeError):
                pass

        # Extract run_id from first event (or use "unknown")
        run_id = events[0].flow if events else "unknown"

        return RunTiming(
            run_id=run_id,
            started_at=run_started,
            ended_at=run_ended,
            total_duration_seconds=run_duration,
            flows=flows,
        )

    def get_run_timing(self, run_id: str) -> Optional[RunTiming]:
        """
        Get timing data for a run.

        Tries to load pre-computed run_timing.json first, falls back to
        computing from flow_history.json.

        Args:
            run_id: Run identifier

        Returns:
            RunTiming object or None if no timing data available.
        """
        run_path = self.get_run_path(run_id)
        if run_path is None:
            return None

        # Try pre-computed timing file first
        timing_path = run_path / "wisdom" / "run_timing.json"
        if timing_path.exists():
            try:
                with open(timing_path) as f:
                    data = json.load(f)

                # Reconstruct RunTiming from JSON
                flows = {}
                for flow_key, flow_data in data.get("flows", {}).items():
                    steps = [
                        StepTiming(**step_data)
                        for step_data in flow_data.get("steps", [])
                    ]
                    flows[flow_key] = FlowTiming(
                        flow_key=flow_data.get("flow_key", flow_key),
                        started_at=flow_data.get("started_at"),
                        ended_at=flow_data.get("ended_at"),
                        duration_seconds=flow_data.get("duration_seconds"),
                        steps=steps,
                    )

                return RunTiming(
                    run_id=data.get("run_id", run_id),
                    started_at=data.get("started_at"),
                    ended_at=data.get("ended_at"),
                    total_duration_seconds=data.get("total_duration_seconds"),
                    flows=flows,
                )
            except (json.JSONDecodeError, IOError, KeyError, TypeError):
                pass  # Fall through to compute from history

        # Fall back to computing from flow_history.json
        events = self.get_run_timeline(run_id)
        if not events:
            return None

        timing = self.compute_timing_from_history(events)
        if timing:
            # Update run_id to match the actual run
            timing.run_id = run_id
        return timing

    def get_flow_timing(self, run_id: str, flow_key: str) -> Optional[FlowTiming]:
        """
        Get timing for a specific flow.

        Args:
            run_id: Run identifier
            flow_key: Flow key (e.g., "build")

        Returns:
            FlowTiming object or None if not available.
        """
        run_timing = self.get_run_timing(run_id)
        if run_timing is None:
            return None
        return run_timing.flows.get(flow_key)

    def to_dict(self, obj: Any) -> Any:
        """
        Convert a dataclass result to a JSON-serializable dict.

        Handles nested dataclasses and Enums.
        """
        # Handle new timing dataclasses
        if isinstance(obj, (FlowEvent, StepTiming, FlowTiming, RunTiming)):
            return asdict(obj)
        elif hasattr(obj, "__dataclass_fields__"):
            return {
                k: self.to_dict(v) for k, v in obj.__dict__.items()
            }
        elif isinstance(obj, Enum):
            return obj.value
        elif isinstance(obj, dict):
            return {k: self.to_dict(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self.to_dict(v) for v in obj]
        else:
            return obj


def main():
    """CLI for testing run inspector."""
    import argparse

    parser = argparse.ArgumentParser(description="Inspect swarm run artifacts")
    parser.add_argument("--run", "-r", default="health-check",
                       help="Run ID to inspect (default: health-check)")
    parser.add_argument("--flow", "-f", help="Specific flow to inspect")
    parser.add_argument("--step", "-s", help="Specific step to inspect (requires --flow)")
    parser.add_argument("--list", "-l", action="store_true",
                       help="List available runs")
    parser.add_argument("--sdlc-bar", action="store_true",
                       help="Show SDLC bar data")
    parser.add_argument("--json", action="store_true",
                       help="Output as JSON")

    args = parser.parse_args()
    inspector = RunInspector()

    if args.list:
        runs = inspector.list_runs()
        if args.json:
            print(json.dumps(runs, indent=2))
        else:
            print("Available runs:")
            for run in runs:
                print(f"  [{run['run_type']}] {run['run_id']}")
        return

    if args.sdlc_bar:
        bar = inspector.get_sdlc_bar(args.run)
        if args.json:
            print(json.dumps(bar, indent=2))
        else:
            for flow in bar:
                status_icon = {
                    "done": "\u2705",
                    "in_progress": "\u23f3",
                    "not_started": "\u2014",
                }.get(flow["status"], "?")
                print(f"{status_icon} {flow['title']}")
        return

    if args.step:
        if not args.flow:
            print("Error: --step requires --flow")
            return
        result = inspector.get_step_status(args.run, args.flow, args.step)
    elif args.flow:
        result = inspector.get_flow_status(args.run, args.flow)
    else:
        result = inspector.get_run_summary(args.run)

    if args.json:
        print(json.dumps(inspector.to_dict(result), indent=2))
    else:
        # Human-readable output
        if isinstance(result, StepResult):
            print(f"Step: {result.step_id}")
            print(f"Status: {result.status.value}")
            print(f"Required: {result.required_present}/{result.required_total}")
            print(f"Optional: {result.optional_present}/{result.optional_total}")
            if result.note:
                print(f"Note: {result.note}")
            print("Artifacts:")
            for a in result.artifacts:
                icon = "\u2705" if a.status == ArtifactStatus.PRESENT else "\u274c"
                req = "[REQ]" if a.required else "[OPT]"
                print(f"  {icon} {req} {a.path}")
        elif isinstance(result, FlowResult):
            print(f"Flow: {result.title}")
            print(f"Status: {result.status.value}")
            if result.decision_artifact:
                icon = "\u2705" if result.decision_present else "\u274c"
                print(f"Decision: {icon} {result.decision_artifact}")
            print("Steps:")
            for step_id, step in result.steps.items():
                icon = {
                    StepStatus.COMPLETE: "\u2705",
                    StepStatus.PARTIAL: "\u26a0\ufe0f",
                    StepStatus.MISSING: "\u274c",
                    StepStatus.NOT_APPLICABLE: "\u2014",
                }.get(step.status, "?")
                print(f"  {icon} {step_id}: {step.required_present}/{step.required_total}")
        elif isinstance(result, RunResult):
            print(f"Run: {result.run_id} ({result.run_type})")
            print(f"Path: {result.path}")
            print("Flows:")
            for flow_key, flow in result.flows.items():
                icon = {
                    FlowStatus.DONE: "\u2705",
                    FlowStatus.IN_PROGRESS: "\u23f3",
                    FlowStatus.NOT_STARTED: "\u2014",
                }.get(flow.status, "?")
                print(f"  {icon} {flow.title}")


if __name__ == "__main__":
    main()
