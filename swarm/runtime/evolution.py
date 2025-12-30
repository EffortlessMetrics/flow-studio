"""
evolution.py - Evolution loop for applying Wisdom flow patches to improve flow/station specs.

This module provides the evolution loop where Wisdom flow generates patches
that can be applied to improve flow and station specs. It bridges the feedback
from wisdom outputs to spec file mutations.

The evolution loop:
1. feedback-applier agent generates structured evolution suggestions
2. generate_evolution_patch() parses Wisdom artifacts for improvement suggestions
3. apply_evolution_patch() applies patches to spec files (with dry_run support)

Usage:
    from swarm.runtime.evolution import (
        EvolutionPatch,
        generate_evolution_patch,
        apply_evolution_patch,
    )

    # Parse wisdom outputs for evolution patches
    patches = generate_evolution_patch(wisdom_dir)

    # Validate patches (dry run)
    for patch in patches:
        result = apply_evolution_patch(patch, dry_run=True)
        if result.valid:
            # Apply for real
            apply_evolution_patch(patch, dry_run=False)
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# =============================================================================
# Enums and Types
# =============================================================================


class PatchType(str, Enum):
    """Type of evolution patch."""

    FLOW_SPEC = "flow_spec"  # Patch to a flow spec (e.g., add step, modify edge)
    STATION_SPEC = "station_spec"  # Patch to a station spec (tuning)
    AGENT_PROMPT = "agent_prompt"  # Patch to an agent prompt file
    TEMPLATE = "template"  # Patch to a step template
    CONFIG = "config"  # Patch to config files


class ConfidenceLevel(str, Enum):
    """Confidence level for an evolution patch."""

    LOW = "low"  # Speculative, may need human review
    MEDIUM = "medium"  # Reasonable confidence based on evidence
    HIGH = "high"  # Strong evidence from multiple runs


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class EvolutionPatch:
    """A single evolution patch to apply to a spec file.

    Represents a suggested improvement from the Wisdom flow that can be
    validated and applied to flow/station specs.

    Attributes:
        id: Unique identifier for this patch (e.g., "FLOW-PATCH-001")
        target_file: Relative path to the file to patch (from repo root)
        patch_type: Type of patch (flow_spec, station_spec, agent_prompt, etc.)
        content: The patch content (diff, JSON patch ops, or replacement text)
        confidence: Confidence level based on evidence
        reasoning: Explanation of why this patch is suggested
        evidence: List of evidence sources (file paths, run IDs, etc.)
        source_run_id: The run ID that generated this patch suggestion
        operations: For JSON patches, the list of operations to apply
        risk: Risk assessment (low, medium, high)
        human_review_required: Whether human review is required before applying
        created_at: Timestamp when the patch was created
    """

    id: str
    target_file: str
    patch_type: PatchType
    content: str
    confidence: ConfidenceLevel
    reasoning: str
    evidence: List[str] = field(default_factory=list)
    source_run_id: Optional[str] = None
    operations: List[Dict[str, Any]] = field(default_factory=list)
    risk: str = "low"
    human_review_required: bool = True
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "target_file": self.target_file,
            "patch_type": self.patch_type.value,
            "content": self.content,
            "confidence": self.confidence.value,
            "reasoning": self.reasoning,
            "evidence": self.evidence,
            "source_run_id": self.source_run_id,
            "operations": self.operations,
            "risk": self.risk,
            "human_review_required": self.human_review_required,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EvolutionPatch":
        """Create from dictionary."""
        return cls(
            id=data["id"],
            target_file=data["target_file"],
            patch_type=PatchType(data["patch_type"]),
            content=data["content"],
            confidence=ConfidenceLevel(data.get("confidence", "medium")),
            reasoning=data["reasoning"],
            evidence=data.get("evidence", []),
            source_run_id=data.get("source_run_id"),
            operations=data.get("operations", []),
            risk=data.get("risk", "low"),
            human_review_required=data.get("human_review_required", True),
            created_at=data.get("created_at", datetime.now(timezone.utc).isoformat()),
        )


@dataclass
class PatchValidationResult:
    """Result of validating an evolution patch.

    Attributes:
        valid: Whether the patch is valid and can be applied
        errors: List of validation errors
        warnings: List of validation warnings
        preview: Preview of changes that would be made
        target_exists: Whether the target file exists
        target_etag: ETag of the target file (for concurrency control)
    """

    valid: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    preview: List[Dict[str, Any]] = field(default_factory=list)
    target_exists: bool = False
    target_etag: Optional[str] = None


@dataclass
class PatchApplicationResult:
    """Result of applying an evolution patch.

    Attributes:
        success: Whether the patch was successfully applied
        dry_run: Whether this was a dry run
        errors: List of errors if application failed
        changes_made: List of changes that were made
        backup_path: Path to backup file if created
        new_etag: New ETag of the target file after patching
    """

    success: bool
    dry_run: bool
    errors: List[str] = field(default_factory=list)
    changes_made: List[str] = field(default_factory=list)
    backup_path: Optional[str] = None
    new_etag: Optional[str] = None


# =============================================================================
# Patch Generation
# =============================================================================


def generate_evolution_patch(
    wisdom_output: Path,
    run_id: Optional[str] = None,
) -> List[EvolutionPatch]:
    """Parse Wisdom artifacts for improvement suggestions.

    Scans the wisdom output directory for:
    - flow_evolution.patch (Tier 2 - flow topology patches)
    - station_tuning.md (Tier 3 - station config updates)
    - pack_improvements.md (ready-to-apply diffs for agent prompts)
    - feedback_actions.md (issue drafts with evolution suggestions)

    Args:
        wisdom_output: Path to wisdom output directory (e.g., RUN_BASE/wisdom/)
        run_id: Optional run ID to associate with patches

    Returns:
        List of EvolutionPatch objects parsed from wisdom artifacts.
    """
    patches: List[EvolutionPatch] = []

    if not wisdom_output.exists():
        logger.warning("Wisdom output directory not found: %s", wisdom_output)
        return patches

    # Extract run_id from path if not provided
    if run_id is None:
        # Try to extract from path like swarm/runs/<run-id>/wisdom
        parts = wisdom_output.parts
        if len(parts) >= 2 and parts[-1] == "wisdom":
            run_id = parts[-2]

    # Parse flow_evolution.patch (JSON format)
    flow_evolution_path = wisdom_output / "flow_evolution.patch"
    if flow_evolution_path.exists():
        patches.extend(_parse_flow_evolution_patch(flow_evolution_path, run_id))

    # Parse station_tuning.md (Markdown with diff blocks)
    station_tuning_path = wisdom_output / "station_tuning.md"
    if station_tuning_path.exists():
        patches.extend(_parse_station_tuning(station_tuning_path, run_id))

    # Parse pack_improvements.md (Markdown with diff blocks)
    pack_improvements_path = wisdom_output / "pack_improvements.md"
    if pack_improvements_path.exists():
        patches.extend(_parse_pack_improvements(pack_improvements_path, run_id))

    # Parse feedback_actions.md for Evolution Suggestions section
    feedback_actions_path = wisdom_output / "feedback_actions.md"
    if feedback_actions_path.exists():
        patches.extend(_parse_feedback_actions(feedback_actions_path, run_id))

    logger.info(
        "Generated %d evolution patches from %s",
        len(patches),
        wisdom_output,
    )

    return patches


def _parse_flow_evolution_patch(
    path: Path,
    run_id: Optional[str],
) -> List[EvolutionPatch]:
    """Parse flow_evolution.patch JSON file.

    Expected format (from feedback-applier prompt):
    {
        "schema_version": "flow_evolution_v1",
        "run_id": "<run-id>",
        "patches": [
            {
                "id": "FLOW-PATCH-001",
                "target_flow": "swarm/spec/flows/3-build.yaml",
                "reason": "Navigator injected SecurityScanner after Implement 3+ times",
                "evidence": [...],
                "operations": [{...}],
                "risk": "low",
                "human_review_required": true
            }
        ]
    }
    """
    patches: List[EvolutionPatch] = []

    try:
        content = path.read_text(encoding="utf-8")
        data = json.loads(content)

        for patch_data in data.get("patches", []):
            patch = EvolutionPatch(
                id=patch_data.get("id", f"FLOW-PATCH-{len(patches) + 1:03d}"),
                target_file=patch_data.get("target_flow", ""),
                patch_type=PatchType.FLOW_SPEC,
                content=json.dumps(patch_data.get("operations", []), indent=2),
                confidence=_parse_confidence(patch_data.get("risk", "medium")),
                reasoning=patch_data.get("reason", ""),
                evidence=patch_data.get("evidence", []),
                source_run_id=run_id or data.get("run_id"),
                operations=patch_data.get("operations", []),
                risk=patch_data.get("risk", "low"),
                human_review_required=patch_data.get("human_review_required", True),
            )
            patches.append(patch)

    except json.JSONDecodeError as e:
        logger.warning("Failed to parse flow_evolution.patch: %s", e)
    except Exception as e:
        logger.warning("Error reading flow_evolution.patch: %s", e)

    return patches


def _parse_station_tuning(
    path: Path,
    run_id: Optional[str],
) -> List[EvolutionPatch]:
    """Parse station_tuning.md for station config patches.

    Looks for patterns like:
    ## Station: code-implementer
    **Pattern observed:** ...
    **Evidence:** ...
    **Proposed tuning:**
    File: `swarm/spec/stations/code-implementer.yaml`
    ```diff
    ...
    ```
    """
    patches: List[EvolutionPatch] = []

    try:
        content = path.read_text(encoding="utf-8")

        # Split by station sections
        station_sections = re.split(r"^## Station:\s*(.+)$", content, flags=re.MULTILINE)

        # Process each station section (skip first split part which is header)
        for i in range(1, len(station_sections), 2):
            if i + 1 >= len(station_sections):
                break

            station_name = station_sections[i].strip()
            section_content = station_sections[i + 1]

            # Check if this station has tuning needed
            if "(none detected)" in section_content.lower():
                continue

            # Extract pattern observed
            pattern_match = re.search(
                r"\*\*Pattern observed:\*\*\s*(.+?)(?=\n\*\*|$)",
                section_content,
                re.DOTALL,
            )
            pattern = pattern_match.group(1).strip() if pattern_match else ""

            # Extract evidence
            evidence_match = re.search(
                r"\*\*Evidence:\*\*\s*(.+?)(?=\n\*\*|$)",
                section_content,
                re.DOTALL,
            )
            evidence_text = evidence_match.group(1).strip() if evidence_match else ""
            evidence = [
                line.strip("- ").strip() for line in evidence_text.split("\n") if line.strip()
            ]

            # Extract target file
            file_match = re.search(
                r"File:\s*`([^`]+)`",
                section_content,
            )
            target_file = (
                file_match.group(1) if file_match else f"swarm/spec/stations/{station_name}.yaml"
            )

            # Extract diff content
            diff_match = re.search(
                r"```diff\s*\n(.+?)```",
                section_content,
                re.DOTALL,
            )
            diff_content = diff_match.group(1).strip() if diff_match else ""

            # Extract risk
            risk_match = re.search(
                r"\*\*Risk:\*\*\s*(\w+)",
                section_content,
            )
            risk = risk_match.group(1).lower() if risk_match else "low"

            if diff_content:
                patch = EvolutionPatch(
                    id=f"STATION-TUNE-{len(patches) + 1:03d}",
                    target_file=target_file,
                    patch_type=PatchType.STATION_SPEC,
                    content=diff_content,
                    confidence=_parse_confidence(risk),
                    reasoning=pattern,
                    evidence=evidence,
                    source_run_id=run_id,
                    risk=risk,
                    human_review_required=True,
                )
                patches.append(patch)

    except Exception as e:
        logger.warning("Error parsing station_tuning.md: %s", e)

    return patches


def _parse_pack_improvements(
    path: Path,
    run_id: Optional[str],
) -> List[EvolutionPatch]:
    """Parse pack_improvements.md for agent prompt patches.

    Looks for patterns like:
    ### PACK-001: <short title>
    **Pattern observed:** ...
    **Evidence:** ...
    **Risk:** Low | Medium | High
    **Rationale:** ...
    **File:** `.claude/agents/<agent>.md`
    ```diff
    ...
    ```
    """
    patches: List[EvolutionPatch] = []

    try:
        content = path.read_text(encoding="utf-8")

        # Split by PACK- sections
        pack_sections = re.split(r"^### (PACK-\d+):\s*(.+)$", content, flags=re.MULTILINE)

        # Process each pack section
        for i in range(1, len(pack_sections), 3):
            if i + 2 >= len(pack_sections):
                break

            pack_id = pack_sections[i].strip()
            pack_title = pack_sections[i + 1].strip()
            section_content = pack_sections[i + 2]

            # Extract pattern observed
            pattern_match = re.search(
                r"\*\*Pattern observed:\*\*\s*(.+?)(?=\n\*\*|$)",
                section_content,
                re.DOTALL,
            )
            pattern = pattern_match.group(1).strip() if pattern_match else pack_title

            # Extract evidence
            evidence_match = re.search(
                r"\*\*Evidence:\*\*\s*(.+?)(?=\n\*\*|$)",
                section_content,
                re.DOTALL,
            )
            evidence_text = evidence_match.group(1).strip() if evidence_match else ""
            evidence = [
                line.strip("- ").strip() for line in evidence_text.split("\n") if line.strip()
            ]

            # Extract target file
            file_match = re.search(
                r"\*\*File:\*\*\s*`([^`]+)`",
                section_content,
            )
            target_file = file_match.group(1) if file_match else ""

            # Extract diff content
            diff_match = re.search(
                r"```diff\s*\n(.+?)```",
                section_content,
                re.DOTALL,
            )
            diff_content = diff_match.group(1).strip() if diff_match else ""

            # Extract risk
            risk_match = re.search(
                r"\*\*Risk:\*\*\s*(\w+)",
                section_content,
            )
            risk = risk_match.group(1).lower() if risk_match else "low"

            # Extract rationale
            rationale_match = re.search(
                r"\*\*Rationale:\*\*\s*(.+?)(?=\n\*\*|$)",
                section_content,
                re.DOTALL,
            )
            rationale = rationale_match.group(1).strip() if rationale_match else pattern

            if diff_content and target_file:
                patch = EvolutionPatch(
                    id=pack_id,
                    target_file=target_file,
                    patch_type=PatchType.AGENT_PROMPT,
                    content=diff_content,
                    confidence=_parse_confidence(risk),
                    reasoning=rationale,
                    evidence=evidence,
                    source_run_id=run_id,
                    risk=risk,
                    human_review_required=True,
                )
                patches.append(patch)

    except Exception as e:
        logger.warning("Error parsing pack_improvements.md: %s", e)

    return patches


def _parse_feedback_actions(
    path: Path,
    run_id: Optional[str],
) -> List[EvolutionPatch]:
    """Parse feedback_actions.md for Evolution Suggestions section.

    Looks for the structured format:
    ## Evolution Suggestions
    ### Station: clarifier
    - Issue: Low clarification acceptance rate
    - Suggestion: Add fallback research step
    - Confidence: medium
    """
    patches: List[EvolutionPatch] = []

    try:
        content = path.read_text(encoding="utf-8")

        # Find Evolution Suggestions section
        evolution_match = re.search(
            r"## Evolution Suggestions\s*\n(.+?)(?=\n## |$)",
            content,
            re.DOTALL,
        )

        if not evolution_match:
            return patches

        evolution_content = evolution_match.group(1)

        # Split by station sections
        station_sections = re.split(r"^### Station:\s*(.+)$", evolution_content, flags=re.MULTILINE)

        for i in range(1, len(station_sections), 2):
            if i + 1 >= len(station_sections):
                break

            station_name = station_sections[i].strip()
            section_content = station_sections[i + 1]

            # Parse list items
            issue_match = re.search(r"-\s*Issue:\s*(.+)", section_content)
            suggestion_match = re.search(r"-\s*Suggestion:\s*(.+)", section_content)
            confidence_match = re.search(r"-\s*Confidence:\s*(\w+)", section_content)

            issue = issue_match.group(1).strip() if issue_match else ""
            suggestion = suggestion_match.group(1).strip() if suggestion_match else ""
            confidence = confidence_match.group(1).lower() if confidence_match else "medium"

            if issue and suggestion:
                patch = EvolutionPatch(
                    id=f"EVOLUTION-{len(patches) + 1:03d}",
                    target_file=f"swarm/spec/stations/{station_name}.yaml",
                    patch_type=PatchType.STATION_SPEC,
                    content=f"# Suggested improvement for {station_name}\n# Issue: {issue}\n# Suggestion: {suggestion}",
                    confidence=_parse_confidence(confidence),
                    reasoning=f"Issue: {issue}. Suggestion: {suggestion}",
                    evidence=[str(path)],
                    source_run_id=run_id,
                    risk="low" if confidence == "high" else "medium",
                    human_review_required=True,
                )
                patches.append(patch)

    except Exception as e:
        logger.warning("Error parsing feedback_actions.md: %s", e)

    return patches


def _parse_confidence(risk_or_confidence: str) -> ConfidenceLevel:
    """Convert risk/confidence string to ConfidenceLevel."""
    value = risk_or_confidence.lower()
    if value in ("high", "low"):  # low risk = high confidence
        if value == "low":
            return ConfidenceLevel.HIGH
        return ConfidenceLevel.LOW
    elif value == "medium":
        return ConfidenceLevel.MEDIUM
    return ConfidenceLevel.MEDIUM


# =============================================================================
# Patch Application
# =============================================================================


def apply_evolution_patch(
    patch: EvolutionPatch,
    dry_run: bool = True,
    repo_root: Optional[Path] = None,
    create_backup: bool = True,
) -> PatchApplicationResult:
    """Apply an evolution patch to a spec file.

    Args:
        patch: The evolution patch to apply
        dry_run: If True, validate only without applying changes
        repo_root: Repository root path (auto-detected if not provided)
        create_backup: If True, create a backup of the target file before patching

    Returns:
        PatchApplicationResult with validation/application results
    """
    # Resolve repo root
    if repo_root is None:
        repo_root = _find_repo_root()

    if repo_root is None:
        return PatchApplicationResult(
            success=False,
            dry_run=dry_run,
            errors=["Could not determine repository root"],
        )

    # Resolve target file path
    target_path = repo_root / patch.target_file

    # Validate the patch
    validation = validate_evolution_patch(patch, repo_root)

    if not validation.valid:
        return PatchApplicationResult(
            success=False,
            dry_run=dry_run,
            errors=validation.errors,
        )

    # If dry run, return validation success
    if dry_run:
        return PatchApplicationResult(
            success=True,
            dry_run=True,
            changes_made=[f"Would apply {patch.patch_type.value} patch to {patch.target_file}"],
            new_etag=validation.target_etag,
        )

    # Apply the patch
    try:
        backup_path = None

        # Create backup if requested
        if create_backup and target_path.exists():
            backup_path = target_path.with_suffix(target_path.suffix + ".bak")
            import shutil

            shutil.copy2(target_path, backup_path)

        # Apply based on patch type
        if patch.patch_type == PatchType.FLOW_SPEC and patch.operations:
            _apply_json_patch(target_path, patch.operations)
            changes = [f"Applied {len(patch.operations)} JSON patch operations"]
        elif patch.content.startswith("-") or patch.content.startswith("+"):
            _apply_diff_patch(target_path, patch.content)
            changes = ["Applied diff patch"]
        else:
            # Fall back to appending content (for suggestions)
            _append_content(target_path, patch.content)
            changes = ["Appended content"]

        # Compute new ETag
        new_content = target_path.read_text(encoding="utf-8")
        new_etag = hashlib.sha256(new_content.encode()).hexdigest()[:16]

        logger.info(
            "Applied evolution patch %s to %s",
            patch.id,
            patch.target_file,
        )

        return PatchApplicationResult(
            success=True,
            dry_run=False,
            changes_made=changes,
            backup_path=str(backup_path) if backup_path else None,
            new_etag=new_etag,
        )

    except Exception as e:
        logger.error("Failed to apply patch %s: %s", patch.id, e)
        return PatchApplicationResult(
            success=False,
            dry_run=False,
            errors=[f"Failed to apply patch: {e}"],
        )


def validate_evolution_patch(
    patch: EvolutionPatch,
    repo_root: Optional[Path] = None,
) -> PatchValidationResult:
    """Validate an evolution patch without applying it.

    Args:
        patch: The evolution patch to validate
        repo_root: Repository root path (auto-detected if not provided)

    Returns:
        PatchValidationResult with validation results
    """
    errors: List[str] = []
    warnings: List[str] = []
    preview: List[Dict[str, Any]] = []

    # Resolve repo root
    if repo_root is None:
        repo_root = _find_repo_root()

    if repo_root is None:
        return PatchValidationResult(
            valid=False,
            errors=["Could not determine repository root"],
        )

    # Check target file exists
    target_path = repo_root / patch.target_file
    target_exists = target_path.exists()

    if not target_exists and patch.patch_type != PatchType.CONFIG:
        # Allow creating new config files, but not other types
        errors.append(f"Target file does not exist: {patch.target_file}")

    # Compute ETag if file exists
    target_etag = None
    if target_exists:
        try:
            content = target_path.read_text(encoding="utf-8")
            target_etag = hashlib.sha256(content.encode()).hexdigest()[:16]
        except Exception as e:
            errors.append(f"Failed to read target file: {e}")

    # Validate patch content
    if not patch.content and not patch.operations:
        errors.append("Patch has no content or operations")

    # Validate JSON patch operations if present
    if patch.operations:
        for i, op in enumerate(patch.operations):
            if "op" not in op:
                errors.append(f"Operation {i} missing 'op' field")
            elif op["op"] not in ("add", "remove", "replace", "move", "copy", "test"):
                errors.append(f"Operation {i} has invalid op: {op['op']}")
            if "path" not in op:
                errors.append(f"Operation {i} missing 'path' field")

            preview.append(
                {
                    "operation": op.get("op", "unknown"),
                    "path": op.get("path", ""),
                    "value_preview": str(op.get("value", ""))[:100] if "value" in op else None,
                }
            )

    # Validate diff content if present
    if patch.content and (patch.content.startswith("-") or patch.content.startswith("+")):
        lines = patch.content.split("\n")
        for line in lines:
            if line.startswith("-"):
                preview.append({"operation": "remove", "line": line[1:][:80]})
            elif line.startswith("+"):
                preview.append({"operation": "add", "line": line[1:][:80]})

    # Add warnings based on risk and confidence
    if patch.risk == "high":
        warnings.append("High-risk patch - careful review recommended")
    if patch.confidence == ConfidenceLevel.LOW:
        warnings.append("Low-confidence patch - evidence may be insufficient")
    if patch.human_review_required:
        warnings.append("Human review required before applying")

    return PatchValidationResult(
        valid=len(errors) == 0,
        errors=errors,
        warnings=warnings,
        preview=preview,
        target_exists=target_exists,
        target_etag=target_etag,
    )


def _apply_json_patch(target_path: Path, operations: List[Dict[str, Any]]) -> None:
    """Apply JSON patch operations to a file (YAML or JSON)."""
    import yaml

    # Read current content
    content = target_path.read_text(encoding="utf-8")

    # Parse as YAML (works for JSON too)
    data = yaml.safe_load(content) or {}

    # Apply operations
    for op in operations:
        operation = op.get("op")
        path = op.get("path", "").split("/")[1:]  # Skip empty first element
        value = op.get("value")

        if operation == "add":
            _set_nested(data, path, value)
        elif operation == "replace":
            _set_nested(data, path, value)
        elif operation == "remove":
            _remove_nested(data, path)

    # Write back
    if target_path.suffix == ".json":
        target_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    else:
        target_path.write_text(
            yaml.safe_dump(data, default_flow_style=False, sort_keys=False),
            encoding="utf-8",
        )


def _apply_diff_patch(target_path: Path, diff_content: str) -> None:
    """Apply a unified diff to a file."""
    if not target_path.exists():
        raise FileNotFoundError(f"Target file not found: {target_path}")

    content = target_path.read_text(encoding="utf-8")
    lines = content.split("\n")

    # Simple diff application - find and apply changes
    diff_lines = diff_content.split("\n")
    output_lines = []
    i = 0

    for diff_line in diff_lines:
        if diff_line.startswith("-"):
            # Skip this line in the original (removal)
            target_text = diff_line[1:].strip()
            while i < len(lines) and lines[i].strip() != target_text:
                output_lines.append(lines[i])
                i += 1
            if i < len(lines):
                i += 1  # Skip the removed line
        elif diff_line.startswith("+"):
            # Add this line
            output_lines.append(diff_line[1:])
        elif diff_line.startswith(" "):
            # Context line - keep original
            if i < len(lines):
                output_lines.append(lines[i])
                i += 1

    # Add remaining lines
    while i < len(lines):
        output_lines.append(lines[i])
        i += 1

    target_path.write_text("\n".join(output_lines), encoding="utf-8")


def _append_content(target_path: Path, content: str) -> None:
    """Append content to a file."""
    if target_path.exists():
        existing = target_path.read_text(encoding="utf-8")
        target_path.write_text(
            existing + "\n\n" + content + "\n",
            encoding="utf-8",
        )
    else:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(content + "\n", encoding="utf-8")


def _set_nested(data: Dict, path: List[str], value: Any) -> None:
    """Set a nested value in a dictionary."""
    for key in path[:-1]:
        if key.isdigit():
            data = data[int(key)]
        elif key == "-":
            # Append to array
            data.append({})
            data = data[-1]
        else:
            data = data.setdefault(key, {})

    if path:
        final_key = path[-1]
        if final_key.isdigit():
            data[int(final_key)] = value
        elif final_key == "-":
            data.append(value)
        else:
            data[final_key] = value


def _remove_nested(data: Dict, path: List[str]) -> None:
    """Remove a nested value from a dictionary."""
    for key in path[:-1]:
        if key.isdigit():
            data = data[int(key)]
        else:
            data = data[key]

    if path:
        final_key = path[-1]
        if final_key.isdigit():
            del data[int(final_key)]
        else:
            del data[final_key]


def _find_repo_root() -> Optional[Path]:
    """Find repository root by looking for .git directory."""
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / ".git").exists():
            return parent
        if (parent / "CLAUDE.md").exists() and (parent / "swarm").exists():
            return parent
    return None


# =============================================================================
# Convenience Functions
# =============================================================================


def list_pending_patches(
    runs_root: Path,
    limit: int = 50,
) -> List[Tuple[str, List[EvolutionPatch]]]:
    """List pending evolution patches across all runs.

    Args:
        runs_root: Path to runs directory (e.g., swarm/runs/)
        limit: Maximum number of runs to scan

    Returns:
        List of (run_id, patches) tuples for runs with pending patches
    """
    results: List[Tuple[str, List[EvolutionPatch]]] = []

    if not runs_root.exists():
        return results

    run_dirs = sorted(runs_root.iterdir(), reverse=True)[:limit]

    for run_dir in run_dirs:
        if not run_dir.is_dir():
            continue

        wisdom_dir = run_dir / "wisdom"
        if not wisdom_dir.exists():
            continue

        # Check if patches have been applied
        applied_markers = list(wisdom_dir.glob(".applied_*"))
        rejected_markers = list(wisdom_dir.glob(".rejected_*"))

        patches = generate_evolution_patch(wisdom_dir, run_id=run_dir.name)

        # Filter out applied/rejected patches
        pending_patches = [
            p
            for p in patches
            if not any(m.name.endswith(p.id) for m in applied_markers)
            and not any(m.name.endswith(p.id) for m in rejected_markers)
        ]

        if pending_patches:
            results.append((run_dir.name, pending_patches))

    return results
