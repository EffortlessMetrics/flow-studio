"""
context_pack.py - ContextPack builder for step hydration.

This module provides the ContextPack dataclass and builder functions for
the "Hydrate" phase of stepwise execution. A ContextPack contains all the
structured context needed to execute a step, including upstream artifacts,
previous envelopes, teaching notes, and flow spec information.

Usage:
    from swarm.runtime.context_pack import (
        ContextPack,
        build_context_pack,
        resolve_upstream_artifacts,
        load_previous_envelopes,
    )

    # Build a complete context pack for a step
    ctx_pack = build_context_pack(step_ctx, run_state, repo_root)

    # Or use individual functions for specific needs
    artifacts = resolve_upstream_artifacts(run_base, flow_key, step_id)
    envelopes = load_previous_envelopes(run_base, flow_key)
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from swarm.config.flow_registry import TeachingNotes, get_flow_steps
from swarm.runtime.types import HandoffEnvelope, RunState, handoff_envelope_from_dict

if TYPE_CHECKING:
    from swarm.runtime.engines import StepContext

# Module logger
logger = logging.getLogger(__name__)

# Directory name for handoff envelopes
HANDOFF_DIR = "handoff"


@dataclass
class ContextPack:
    """Structured context for step execution (the 'Hydrate' phase).

    A ContextPack consolidates all contextual information needed to execute
    a step. It provides a clean interface between the orchestrator's routing
    logic and the engine's execution logic.

    Attributes:
        run_id: The run identifier.
        flow_key: The flow being executed (signal, plan, build, etc.).
        step_id: The step identifier within the flow.
        upstream_artifacts: Map of artifact names to their file paths.
            Resolved from teaching_notes.inputs when available.
        previous_envelopes: List of HandoffEnvelopes from prior steps
            in this flow, ordered chronologically.
        teaching_notes: Optional teaching metadata for scoped context.
        flow_spec_prompt: Optional flow specification prompt text.
        agent_persona: Optional agent persona/role description.
    """

    run_id: str
    flow_key: str
    step_id: str
    upstream_artifacts: Dict[str, Path] = field(default_factory=dict)
    previous_envelopes: List[HandoffEnvelope] = field(default_factory=list)
    teaching_notes: Optional[TeachingNotes] = None
    flow_spec_prompt: Optional[str] = None
    agent_persona: Optional[str] = None

    def has_artifacts(self) -> bool:
        """Check if any upstream artifacts are available.

        Returns:
            True if at least one upstream artifact path exists.
        """
        return len(self.upstream_artifacts) > 0

    def get_artifact_path(self, name: str) -> Optional[Path]:
        """Get the path for a specific artifact by name.

        Args:
            name: The artifact name (e.g., "requirements.md", "adr.md").

        Returns:
            Path to the artifact if found, None otherwise.
        """
        return self.upstream_artifacts.get(name)

    def get_latest_envelope(self) -> Optional[HandoffEnvelope]:
        """Get the most recent previous envelope.

        Returns:
            The last HandoffEnvelope in previous_envelopes, or None if empty.
        """
        return self.previous_envelopes[-1] if self.previous_envelopes else None

    def get_envelope_for_step(self, step_id: str) -> Optional[HandoffEnvelope]:
        """Get the envelope for a specific prior step.

        Args:
            step_id: The step ID to look up.

        Returns:
            The HandoffEnvelope for that step, or None if not found.
        """
        for envelope in self.previous_envelopes:
            if envelope.step_id == step_id:
                return envelope
        return None


def build_context_pack(
    ctx: "StepContext",
    run_state: Optional[RunState] = None,
    repo_root: Optional[Path] = None,
) -> ContextPack:
    """Build a complete ContextPack for step execution.

    Assembles all context needed for the "Hydrate" phase by:
    1. Resolving upstream artifacts based on teaching_notes.inputs
    2. Loading previous handoff envelopes from disk or run_state
    3. Extracting teaching notes from the step context

    Args:
        ctx: The StepContext containing step execution metadata.
        run_state: Optional RunState with in-memory handoff envelopes.
            If provided, envelopes are read from run_state.handoff_envelopes
            instead of disk.
        repo_root: Optional repository root path override. Defaults to
            ctx.repo_root if not provided.

    Returns:
        A populated ContextPack ready for step hydration.

    Example:
        >>> ctx = StepContext(...)
        >>> pack = build_context_pack(ctx)
        >>> if pack.has_artifacts():
        ...     adr_path = pack.get_artifact_path("adr.md")
    """
    effective_repo_root = repo_root or ctx.repo_root
    run_base = ctx.run_base

    logger.debug(
        "Building context pack for step %s in flow %s (run_id=%s)",
        ctx.step_id,
        ctx.flow_key,
        ctx.run_id,
    )

    # Resolve upstream artifacts
    upstream_artifacts = resolve_upstream_artifacts(
        run_base=run_base,
        flow_key=ctx.flow_key,
        step_id=ctx.step_id,
        teaching_notes=ctx.teaching_notes,
        repo_root=effective_repo_root,
    )

    # Load previous envelopes
    if run_state is not None and run_state.handoff_envelopes:
        # Use in-memory envelopes from run state
        previous_envelopes = _extract_previous_envelopes(
            run_state.handoff_envelopes,
            ctx.step_id,
        )
        logger.debug(
            "Loaded %d envelopes from run_state for step %s",
            len(previous_envelopes),
            ctx.step_id,
        )
    else:
        # Load from disk
        previous_envelopes = load_previous_envelopes(run_base, ctx.flow_key)
        logger.debug(
            "Loaded %d envelopes from disk for step %s",
            len(previous_envelopes),
            ctx.step_id,
        )

    return ContextPack(
        run_id=ctx.run_id,
        flow_key=ctx.flow_key,
        step_id=ctx.step_id,
        upstream_artifacts=upstream_artifacts,
        previous_envelopes=previous_envelopes,
        teaching_notes=ctx.teaching_notes,
        flow_spec_prompt=None,  # Reserved for future flow spec loading
        agent_persona=None,  # Reserved for future agent persona loading
    )


def resolve_upstream_artifacts(
    run_base: Path,
    flow_key: str,
    step_id: str,
    teaching_notes: Optional[TeachingNotes] = None,
    repo_root: Optional[Path] = None,
) -> Dict[str, Path]:
    """Resolve upstream artifact paths for a step.

    Looks for artifacts based on teaching_notes.inputs if available,
    or scans the run_base directory for common artifact types.

    Artifact path resolution:
    - Paths starting with "RUN_BASE/" are resolved relative to run_base
    - Paths starting with "/" are treated as absolute
    - Other paths are resolved relative to repo_root or run_base

    Args:
        run_base: The RUN_BASE path for the current flow
            (e.g., swarm/runs/<run-id>/<flow-key>).
        flow_key: The flow key (signal, plan, build, etc.).
        step_id: The step ID within the flow.
        teaching_notes: Optional teaching notes with input specifications.
        repo_root: Optional repository root for resolving relative paths.

    Returns:
        Dict mapping artifact names to their resolved file paths.
        Only includes paths that actually exist on disk.

    Example:
        >>> artifacts = resolve_upstream_artifacts(
        ...     run_base=Path("swarm/runs/abc/build"),
        ...     flow_key="build",
        ...     step_id="implement",
        ...     teaching_notes=TeachingNotes(inputs=("RUN_BASE/plan/adr.md",)),
        ... )
        >>> artifacts.get("adr.md")
        PosixPath('swarm/runs/abc/plan/adr.md')
    """
    artifacts: Dict[str, Path] = {}

    # Determine the runs directory for cross-flow artifact resolution
    # run_base is typically: swarm/runs/<run-id>/<flow-key>
    run_dir = run_base.parent  # swarm/runs/<run-id>/

    if teaching_notes and teaching_notes.inputs:
        # Resolve explicitly specified inputs
        for input_spec in teaching_notes.inputs:
            resolved_path = _resolve_artifact_path(
                input_spec,
                run_base=run_base,
                run_dir=run_dir,
                repo_root=repo_root,
            )
            if resolved_path and resolved_path.exists():
                artifact_name = resolved_path.name
                artifacts[artifact_name] = resolved_path
                logger.debug(
                    "Resolved artifact %s -> %s",
                    input_spec,
                    resolved_path,
                )
            else:
                logger.debug(
                    "Artifact not found: %s (resolved to %s)",
                    input_spec,
                    resolved_path,
                )
    else:
        # Fallback: scan for common artifacts in run_base and parent flows
        artifacts = _scan_common_artifacts(run_base, run_dir)

    return artifacts


def _resolve_artifact_path(
    input_spec: str,
    run_base: Path,
    run_dir: Path,
    repo_root: Optional[Path] = None,
) -> Optional[Path]:
    """Resolve a single artifact path specification.

    Handles various path formats:
    - "RUN_BASE/<flow>/<artifact>" -> resolved to run_dir/<flow>/<artifact>
    - "RUN_BASE/<artifact>" -> resolved to run_base/<artifact>
    - Absolute paths -> used as-is
    - Relative paths -> resolved relative to repo_root or run_base

    Args:
        input_spec: The input path specification.
        run_base: Current flow's RUN_BASE path.
        run_dir: Parent run directory (contains all flows).
        repo_root: Optional repository root.

    Returns:
        Resolved Path, or None if resolution failed.
    """
    if input_spec.startswith("RUN_BASE/"):
        # Remove RUN_BASE/ prefix and resolve relative to run_dir
        relative_part = input_spec[len("RUN_BASE/") :]

        # Check if it specifies a different flow (e.g., "plan/adr.md")
        if "/" in relative_part:
            return run_dir / relative_part
        else:
            # No flow specified, use current run_base
            return run_base / relative_part

    elif input_spec.startswith("/"):
        # Absolute path
        return Path(input_spec)

    else:
        # Relative path
        if repo_root:
            return repo_root / input_spec
        else:
            return run_base / input_spec


def _scan_common_artifacts(run_base: Path, run_dir: Path) -> Dict[str, Path]:
    """Scan for common artifacts when no teaching_notes are available.

    Looks for standard SDLC artifacts in the current flow and upstream flows.

    Args:
        run_base: Current flow's RUN_BASE path.
        run_dir: Parent run directory.

    Returns:
        Dict of found artifact names to paths.
    """
    artifacts: Dict[str, Path] = {}

    # Common artifact names by flow
    common_artifacts = {
        "signal": [
            "problem_statement.md",
            "requirements.md",
            "bdd_scenarios.md",
            "risk_assessment.md",
        ],
        "plan": [
            "adr.md",
            "api_contracts.yaml",
            "interface_spec.md",
            "observability_spec.md",
            "test_plan.md",
            "work_plan.md",
        ],
        "build": [
            "impl_changes_summary.md",
            "test_summary.md",
            "code_critique.md",
            "build_receipt.json",
        ],
        "gate": [
            "merge_decision.md",
            "audit_report.md",
            "policy_verdict.md",
        ],
    }

    # Scan run_dir for all flow directories
    if run_dir.exists():
        for flow_dir in run_dir.iterdir():
            if not flow_dir.is_dir():
                continue

            flow_key = flow_dir.name
            expected_artifacts = common_artifacts.get(flow_key, [])

            for artifact_name in expected_artifacts:
                artifact_path = flow_dir / artifact_name
                if artifact_path.exists():
                    # Use qualified name to avoid collisions
                    qualified_name = f"{flow_key}/{artifact_name}"
                    artifacts[qualified_name] = artifact_path

    return artifacts


def load_previous_envelopes(run_base: Path, flow_key: str) -> List[HandoffEnvelope]:
    """Load previous handoff envelopes from disk.

    Reads all envelope JSON files from the handoff/ directory and parses
    them into HandoffEnvelope objects. Returns envelopes in chronological
    order based on their step IDs.

    Args:
        run_base: The RUN_BASE path for the flow
            (e.g., swarm/runs/<run-id>/<flow-key>).
        flow_key: The flow key for context.

    Returns:
        List of HandoffEnvelope objects, ordered by step index.
        Returns empty list if handoff directory doesn't exist.

    Example:
        >>> envelopes = load_previous_envelopes(
        ...     run_base=Path("swarm/runs/abc/build"),
        ...     flow_key="build",
        ... )
        >>> for env in envelopes:
        ...     print(f"Step {env.step_id}: {env.status}")
    """
    handoff_dir = run_base / HANDOFF_DIR

    if not handoff_dir.exists():
        logger.debug("Handoff directory does not exist: %s", handoff_dir)
        return []

    envelopes: List[HandoffEnvelope] = []
    step_order = _get_step_order(flow_key)

    for entry in handoff_dir.iterdir():
        if not entry.is_file():
            continue
        if not entry.name.endswith(".json"):
            continue

        try:
            with open(entry, "r", encoding="utf-8") as f:
                data = json.load(f)

            envelope = handoff_envelope_from_dict(data)
            envelopes.append(envelope)
            logger.debug(
                "Loaded envelope for step %s from %s",
                envelope.step_id,
                entry.name,
            )

        except json.JSONDecodeError as e:
            logger.warning(
                "Failed to parse envelope JSON in %s: %s",
                entry,
                e,
            )
        except Exception as e:
            logger.warning(
                "Failed to load envelope from %s: %s",
                entry,
                e,
            )

    # Sort by step order within the flow
    envelopes.sort(key=lambda env: step_order.get(env.step_id, 999))

    return envelopes


def _get_step_order(flow_key: str) -> Dict[str, int]:
    """Get step ordering for a flow.

    Args:
        flow_key: The flow key.

    Returns:
        Dict mapping step_id to 0-based order index.
    """
    try:
        steps = get_flow_steps(flow_key)
        return {step.id: idx for idx, step in enumerate(steps)}
    except Exception as e:
        logger.debug("Could not get step order for flow %s: %s", flow_key, e)
        return {}


def _extract_previous_envelopes(
    handoff_envelopes: Dict[str, HandoffEnvelope],
    current_step_id: str,
) -> List[HandoffEnvelope]:
    """Extract envelopes for steps prior to the current step.

    Filters and orders envelopes from the run state to only include
    those from steps that have already completed.

    Args:
        handoff_envelopes: Dict of step_id -> HandoffEnvelope from RunState.
        current_step_id: The current step being executed.

    Returns:
        List of prior envelopes in chronological order.
    """
    # Filter out current step and sort by step_id
    # This is a simplified ordering; for proper ordering we'd need
    # access to the flow registry
    prior_envelopes = [
        env
        for step_id, env in handoff_envelopes.items()
        if step_id != current_step_id
    ]

    # Sort by timestamp as a proxy for chronological order
    prior_envelopes.sort(key=lambda env: env.timestamp)

    return prior_envelopes


def ensure_handoff_dir(run_base: Path) -> Path:
    """Ensure handoff/ directory exists and return its path.

    Creates the directory and any parent directories if they don't exist.

    Args:
        run_base: The RUN_BASE path.

    Returns:
        Path to the handoff/ directory.

    Example:
        >>> handoff_dir = ensure_handoff_dir(Path("swarm/runs/abc/build"))
        >>> handoff_dir.exists()
        True
    """
    handoff_path = run_base / HANDOFF_DIR
    handoff_path.mkdir(parents=True, exist_ok=True)
    return handoff_path


def save_envelope(envelope: HandoffEnvelope, run_base: Path) -> Path:
    """Save a handoff envelope to disk.

    Writes the envelope to the handoff/ directory with a filename
    based on the step_id.

    Args:
        envelope: The HandoffEnvelope to save.
        run_base: The RUN_BASE path.

    Returns:
        Path where the envelope was saved.

    Example:
        >>> envelope = HandoffEnvelope(step_id="implement", ...)
        >>> path = save_envelope(envelope, Path("swarm/runs/abc/build"))
        >>> path
        PosixPath('swarm/runs/abc/build/handoff/implement.json')
    """
    from swarm.runtime.types import handoff_envelope_to_dict

    handoff_dir = ensure_handoff_dir(run_base)
    envelope_path = handoff_dir / f"{envelope.step_id}.json"

    with open(envelope_path, "w", encoding="utf-8") as f:
        json.dump(handoff_envelope_to_dict(envelope), f, indent=2, default=str)

    logger.debug("Saved envelope for step %s to %s", envelope.step_id, envelope_path)

    return envelope_path
