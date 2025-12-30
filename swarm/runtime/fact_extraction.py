"""
fact_extraction.py - Fact extraction pipeline for inventory markers.

This module provides a pipeline to parse inventory markers from step outputs
and artifacts. Markers follow the pattern PREFIX_NNN where PREFIX indicates
the fact type and NNN is a 3-digit numeric identifier.

Supported marker types:
- REQ_NNN: Requirements (functional/non-functional)
- SOL_NNN: Solutions (implementation decisions)
- TRC_NNN: Trace/lineage markers
- ASM_NNN: Assumptions made during processing
- DEC_NNN: Decisions (architectural, design)

Usage:
    from swarm.runtime.fact_extraction import (
        ExtractedFact,
        extract_facts_from_text,
        extract_facts_from_file,
        extract_facts_from_step,
        ingest_facts_to_db,
    )

    # Extract from text
    facts = extract_facts_from_text("REQ_001: User can login\nSOL_001: Use OAuth2")

    # Extract from a file
    facts = extract_facts_from_file(Path("/runs/abc/signal/requirements.md"))

    # Extract from a step's artifacts
    facts = extract_facts_from_step(run_base, "signal", "1")

    # Ingest into DuckDB
    ingest_facts_to_db(facts, run_id, db)
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Pattern

logger = logging.getLogger(__name__)


# =============================================================================
# Marker Patterns
# =============================================================================

# Maps marker type prefixes to their description
MARKER_TYPES: Dict[str, str] = {
    "REQ": "Requirement",
    "SOL": "Solution",
    "TRC": "Trace",
    "ASM": "Assumption",
    "DEC": "Decision",
}

# Core pattern for marker detection: PREFIX_NNN followed by content
# Captures: (1) prefix, (2) numeric ID, (3) content after colon/whitespace
MARKER_PATTERNS: Dict[str, Pattern[str]] = {
    # REQ_001: Content or REQ_001 - Content
    "REQ": re.compile(
        r"\bREQ_(\d{3})(?:\s*[:.-]\s*|\s+)(.+?)(?=\n|\bREQ_|\bSOL_|\bTRC_|\bASM_|\bDEC_|$)",
        re.IGNORECASE,
    ),
    # SOL_001: Content
    "SOL": re.compile(
        r"\bSOL_(\d{3})(?:\s*[:.-]\s*|\s+)(.+?)(?=\n|\bREQ_|\bSOL_|\bTRC_|\bASM_|\bDEC_|$)",
        re.IGNORECASE,
    ),
    # TRC_001: Content
    "TRC": re.compile(
        r"\bTRC_(\d{3})(?:\s*[:.-]\s*|\s+)(.+?)(?=\n|\bREQ_|\bSOL_|\bTRC_|\bASM_|\bDEC_|$)",
        re.IGNORECASE,
    ),
    # ASM_001: Content
    "ASM": re.compile(
        r"\bASM_(\d{3})(?:\s*[:.-]\s*|\s+)(.+?)(?=\n|\bREQ_|\bSOL_|\bTRC_|\bASM_|\bDEC_|$)",
        re.IGNORECASE,
    ),
    # DEC_001: Content
    "DEC": re.compile(
        r"\bDEC_(\d{3})(?:\s*[:.-]\s*|\s+)(.+?)(?=\n|\bREQ_|\bSOL_|\bTRC_|\bASM_|\bDEC_|$)",
        re.IGNORECASE,
    ),
}

# Simple pattern to find any marker (for line number detection)
ANY_MARKER_PATTERN = re.compile(r"\b(REQ|SOL|TRC|ASM|DEC)_(\d{3})\b", re.IGNORECASE)

# Context window: number of characters before/after marker to capture
CONTEXT_WINDOW = 100


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class ExtractedFact:
    """A single fact extracted from an artifact.

    Attributes:
        marker_type: The marker type prefix (REQ, SOL, TRC, ASM, DEC).
        marker_id: The full marker identifier (e.g., "REQ_001").
        content: The fact text/description.
        source_file: Path to the source file (relative or absolute).
        source_line: Line number where the marker appears (1-indexed).
        context: Surrounding text for disambiguation.
        step_id: Optional step identifier.
        flow_key: Optional flow key (signal, plan, build, etc.).
        run_id: Optional run identifier.
        agent_key: Optional agent that produced this fact.
        extracted_at: ISO timestamp when fact was extracted.
    """

    marker_type: str
    marker_id: str
    content: str
    source_file: str
    source_line: int
    context: str = ""
    step_id: Optional[str] = None
    flow_key: Optional[str] = None
    run_id: Optional[str] = None
    agent_key: Optional[str] = None
    extracted_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dictionary."""
        return {
            "marker_type": self.marker_type,
            "marker_id": self.marker_id,
            "content": self.content,
            "source_file": self.source_file,
            "source_line": self.source_line,
            "context": self.context,
            "step_id": self.step_id,
            "flow_key": self.flow_key,
            "run_id": self.run_id,
            "agent_key": self.agent_key,
            "extracted_at": self.extracted_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExtractedFact":
        """Create ExtractedFact from dictionary."""
        return cls(
            marker_type=data.get("marker_type", ""),
            marker_id=data.get("marker_id", ""),
            content=data.get("content", ""),
            source_file=data.get("source_file", ""),
            source_line=data.get("source_line", 0),
            context=data.get("context", ""),
            step_id=data.get("step_id"),
            flow_key=data.get("flow_key"),
            run_id=data.get("run_id"),
            agent_key=data.get("agent_key"),
            extracted_at=data.get("extracted_at"),
        )


@dataclass
class ExtractionResult:
    """Result of a fact extraction operation.

    Attributes:
        facts: List of extracted facts.
        source_files: List of files that were scanned.
        errors: Any errors encountered during extraction.
    """

    facts: List[ExtractedFact] = field(default_factory=list)
    source_files: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dictionary."""
        return {
            "facts": [f.to_dict() for f in self.facts],
            "source_files": self.source_files,
            "errors": self.errors,
            "fact_count": len(self.facts),
        }


# =============================================================================
# Extraction Functions
# =============================================================================


def _get_line_number(text: str, position: int) -> int:
    """Get 1-indexed line number for a character position in text."""
    return text[:position].count("\n") + 1


def _get_context(text: str, start: int, end: int, window: int = CONTEXT_WINDOW) -> str:
    """Get surrounding context for a match.

    Args:
        text: Full text.
        start: Start position of match.
        end: End position of match.
        window: Number of characters to include before/after.

    Returns:
        Context string with ellipsis if truncated.
    """
    context_start = max(0, start - window)
    context_end = min(len(text), end + window)

    context = text[context_start:context_end]

    # Clean up whitespace
    context = " ".join(context.split())

    # Add ellipsis if truncated
    prefix = "..." if context_start > 0 else ""
    suffix = "..." if context_end < len(text) else ""

    return f"{prefix}{context}{suffix}"


def extract_facts_from_text(
    text: str,
    source_file: str = "<text>",
    step_id: Optional[str] = None,
    flow_key: Optional[str] = None,
    run_id: Optional[str] = None,
    agent_key: Optional[str] = None,
) -> List[ExtractedFact]:
    """Extract all inventory markers from text.

    Args:
        text: The text to scan for markers.
        source_file: Source file path for attribution.
        step_id: Optional step identifier.
        flow_key: Optional flow key.
        run_id: Optional run identifier.
        agent_key: Optional agent key.

    Returns:
        List of ExtractedFact objects found in the text.

    Example:
        >>> text = "REQ_001: User must be able to login\\nSOL_001: Use OAuth2"
        >>> facts = extract_facts_from_text(text)
        >>> len(facts)
        2
        >>> facts[0].marker_id
        'REQ_001'
    """
    facts: List[ExtractedFact] = []
    seen_markers: set = set()  # Deduplicate markers

    from datetime import datetime, timezone

    extracted_at = datetime.now(timezone.utc).isoformat() + "Z"

    for marker_type, pattern in MARKER_PATTERNS.items():
        for match in pattern.finditer(text):
            numeric_id = match.group(1)
            content = match.group(2).strip()
            marker_id = f"{marker_type}_{numeric_id}"

            # Skip duplicates
            if marker_id in seen_markers:
                continue
            seen_markers.add(marker_id)

            # Get line number and context
            line_number = _get_line_number(text, match.start())
            context = _get_context(text, match.start(), match.end())

            fact = ExtractedFact(
                marker_type=marker_type,
                marker_id=marker_id,
                content=content,
                source_file=source_file,
                source_line=line_number,
                context=context,
                step_id=step_id,
                flow_key=flow_key,
                run_id=run_id,
                agent_key=agent_key,
                extracted_at=extracted_at,
            )
            facts.append(fact)

    # Sort by marker type, then by numeric ID
    facts.sort(key=lambda f: (f.marker_type, f.marker_id))
    return facts


def extract_facts_from_file(
    path: Path,
    step_id: Optional[str] = None,
    flow_key: Optional[str] = None,
    run_id: Optional[str] = None,
    agent_key: Optional[str] = None,
) -> List[ExtractedFact]:
    """Extract all inventory markers from a file.

    Args:
        path: Path to the file to scan.
        step_id: Optional step identifier.
        flow_key: Optional flow key.
        run_id: Optional run identifier.
        agent_key: Optional agent key.

    Returns:
        List of ExtractedFact objects found in the file.
        Returns empty list if file doesn't exist or can't be read.

    Example:
        >>> facts = extract_facts_from_file(Path("requirements.md"))
    """
    if not path.exists():
        logger.debug("File not found for fact extraction: %s", path)
        return []

    if not path.is_file():
        logger.debug("Path is not a file: %s", path)
        return []

    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        logger.warning("Failed to read file for fact extraction: %s - %s", path, e)
        return []

    return extract_facts_from_text(
        text=text,
        source_file=str(path),
        step_id=step_id,
        flow_key=flow_key,
        run_id=run_id,
        agent_key=agent_key,
    )


def extract_facts_from_step(
    run_base: Path,
    flow_key: str,
    step_id: str,
    run_id: Optional[str] = None,
) -> ExtractionResult:
    """Extract facts from all artifacts of a step.

    Scans all .md and .json files in the flow directory for the given step,
    extracting any inventory markers found.

    Args:
        run_base: The run base directory (e.g., swarm/runs/<run_id>).
        flow_key: The flow key (signal, plan, build, etc.).
        step_id: The step identifier.
        run_id: Optional run identifier.

    Returns:
        ExtractionResult containing all facts and metadata.

    Example:
        >>> result = extract_facts_from_step(
        ...     Path("swarm/runs/abc"),
        ...     "signal",
        ...     "1",
        ... )
        >>> len(result.facts)
        5
    """
    result = ExtractionResult()
    flow_path = run_base / flow_key

    if not flow_path.exists():
        result.errors.append(f"Flow directory not found: {flow_path}")
        return result

    # Agent key extraction from receipts
    agent_key = None
    receipts_dir = flow_path / "receipts"
    if receipts_dir.exists():
        for receipt_file in receipts_dir.glob(f"{step_id}-*.json"):
            try:
                receipt_data = json.loads(receipt_file.read_text(encoding="utf-8"))
                agent_key = receipt_data.get("agent_key")
                break
            except (OSError, json.JSONDecodeError):
                pass

    # Scan .md files in flow directory
    for md_file in flow_path.glob("*.md"):
        try:
            facts = extract_facts_from_file(
                path=md_file,
                step_id=step_id,
                flow_key=flow_key,
                run_id=run_id,
                agent_key=agent_key,
            )
            result.facts.extend(facts)
            result.source_files.append(str(md_file))
        except Exception as e:
            result.errors.append(f"Error scanning {md_file}: {e}")

    # Scan handoff envelopes
    handoff_dir = flow_path / "handoff"
    if handoff_dir.exists():
        envelope_file = handoff_dir / f"{step_id}.json"
        if envelope_file.exists():
            try:
                envelope_data = json.loads(envelope_file.read_text(encoding="utf-8"))
                summary = envelope_data.get("summary", "")
                if summary:
                    facts = extract_facts_from_text(
                        text=summary,
                        source_file=str(envelope_file) + "#summary",
                        step_id=step_id,
                        flow_key=flow_key,
                        run_id=run_id,
                        agent_key=agent_key,
                    )
                    result.facts.extend(facts)
                    result.source_files.append(str(envelope_file))
            except (OSError, json.JSONDecodeError) as e:
                result.errors.append(f"Error reading envelope {envelope_file}: {e}")

    # Deduplicate facts (same marker_id from multiple sources)
    seen: Dict[str, ExtractedFact] = {}
    for fact in result.facts:
        if fact.marker_id not in seen:
            seen[fact.marker_id] = fact

    result.facts = sorted(seen.values(), key=lambda f: (f.marker_type, f.marker_id))

    return result


def extract_facts_from_run(
    run_base: Path,
    run_id: Optional[str] = None,
) -> ExtractionResult:
    """Extract facts from all flows in a run.

    Args:
        run_base: The run base directory.
        run_id: Optional run identifier.

    Returns:
        ExtractionResult containing all facts from all flows.
    """
    result = ExtractionResult()

    if not run_base.exists():
        result.errors.append(f"Run directory not found: {run_base}")
        return result

    # Known flow keys
    flow_keys = ["signal", "plan", "build", "gate", "deploy", "wisdom"]

    for flow_key in flow_keys:
        flow_path = run_base / flow_key
        if not flow_path.exists():
            continue

        # Find all step IDs from handoff or receipts
        step_ids: set = set()

        # From handoff directory
        handoff_dir = flow_path / "handoff"
        if handoff_dir.exists():
            for f in handoff_dir.glob("*.json"):
                step_ids.add(f.stem)

        # From receipts directory
        receipts_dir = flow_path / "receipts"
        if receipts_dir.exists():
            for f in receipts_dir.glob("*.json"):
                # Receipt filenames are step_id-agent_key.json
                name = f.stem
                if "-" in name:
                    step_ids.add(name.split("-")[0])

        # If no step IDs found, scan all .md files without step attribution
        if not step_ids:
            for md_file in flow_path.glob("*.md"):
                try:
                    facts = extract_facts_from_file(
                        path=md_file,
                        flow_key=flow_key,
                        run_id=run_id,
                    )
                    result.facts.extend(facts)
                    result.source_files.append(str(md_file))
                except Exception as e:
                    result.errors.append(f"Error scanning {md_file}: {e}")
        else:
            # Extract per step
            for step_id in sorted(step_ids):
                step_result = extract_facts_from_step(
                    run_base=run_base,
                    flow_key=flow_key,
                    step_id=step_id,
                    run_id=run_id,
                )
                result.facts.extend(step_result.facts)
                result.source_files.extend(step_result.source_files)
                result.errors.extend(step_result.errors)

    # Deduplicate facts
    seen: Dict[str, ExtractedFact] = {}
    for fact in result.facts:
        key = f"{fact.marker_id}:{fact.source_file}"
        if key not in seen:
            seen[key] = fact

    result.facts = sorted(
        seen.values(), key=lambda f: (f.flow_key or "", f.marker_type, f.marker_id)
    )
    result.source_files = sorted(set(result.source_files))

    return result


# =============================================================================
# DuckDB Integration
# =============================================================================
#
# The facts table is defined in db.py as part of the StatsDB schema.
# This module provides extraction functions that can ingest facts using
# the existing StatsDB.ingest_fact() method, which handles the facts table
# creation and schema.
#
# The StatsDB facts schema includes:
# - fact_id, run_id, step_id, flow_key, agent_key
# - marker_type (REQ, SOL, TRC, ASM, DEC)
# - marker_id (e.g., REQ_001)
# - fact_type (human-readable type)
# - content, priority, status, evidence, created_at, extracted_at, metadata


# Type alias for forward reference
try:
    from .db import StatsDB
except ImportError:
    StatsDB = None  # type: ignore


def ingest_facts_to_db(
    facts: List[ExtractedFact],
    run_id: str,
    db: "StatsDB",
) -> int:
    """Ingest extracted facts into DuckDB using StatsDB.ingest_fact().

    This function adapts ExtractedFact objects to the StatsDB facts table
    schema, storing source_file/source_line/context in the metadata field.

    Args:
        facts: List of ExtractedFact objects to ingest.
        run_id: The run identifier.
        db: The StatsDB instance.

    Returns:
        Number of facts successfully ingested.
    """
    if db is None or db.connection is None:
        return 0

    ingested = 0
    for fact in facts:
        # Map marker type to human-readable fact_type
        fact_type_map = {
            "REQ": "requirement",
            "SOL": "solution",
            "TRC": "trace",
            "ASM": "assumption",
            "DEC": "decision",
        }
        fact_type = fact_type_map.get(fact.marker_type, fact.marker_type.lower())

        # Store source location info in metadata
        metadata = {
            "source_file": fact.source_file,
            "source_line": fact.source_line,
            "context": fact.context,
        }

        # Use StatsDB's ingest_fact method
        result = db.ingest_fact(
            run_id=run_id,
            step_id=fact.step_id or "",
            flow_key=fact.flow_key or "",
            marker_type=fact.marker_type,
            marker_id=fact.marker_id,
            fact_type=fact_type,
            content=fact.content,
            agent_key=fact.agent_key,
            priority=None,  # Could be extracted from content in future
            status="verified",
            evidence=None,
            created_at=None,
            metadata=metadata,
        )

        if result:
            ingested += 1

    return ingested


def query_facts(
    db: "StatsDB",
    run_id: Optional[str] = None,
    marker_type: Optional[str] = None,
    flow_key: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Query facts from DuckDB.

    This function uses the StatsDB facts table schema and returns
    results in a format compatible with ExtractedFact.

    Args:
        db: The StatsDB instance.
        run_id: Optional run ID filter.
        marker_type: Optional marker type filter (REQ, SOL, etc.).
        flow_key: Optional flow key filter.

    Returns:
        List of fact dictionaries.
    """
    if db is None or db.connection is None:
        return []

    # Use StatsDB's query methods if available
    if hasattr(db, "get_facts_for_run") and run_id:
        try:
            if marker_type:
                facts = db.get_facts_by_marker_type(run_id, marker_type)
            else:
                facts = db.get_facts_for_run(run_id)

            # Filter by flow_key if specified
            if flow_key:
                facts = [f for f in facts if f.flow_key == flow_key]

            # Convert Fact dataclass objects to dicts
            results = []
            for fact in facts:
                # Extract source location from metadata
                metadata = fact.metadata or {}
                results.append(
                    {
                        "run_id": fact.run_id,
                        "flow_key": fact.flow_key,
                        "step_id": fact.step_id,
                        "agent_key": fact.agent_key,
                        "marker_type": fact.marker_type,
                        "marker_id": fact.marker_id,
                        "content": fact.content,
                        "source_file": metadata.get("source_file", ""),
                        "source_line": metadata.get("source_line", 0),
                        "context": metadata.get("context", ""),
                        "extracted_at": (
                            fact.extracted_at.isoformat() if fact.extracted_at else None
                        ),
                    }
                )
            return results
        except Exception as e:
            logger.warning("Failed to query facts via StatsDB methods: %s", e)

    # Fallback to direct query
    conditions = []
    params = []

    if run_id:
        conditions.append("run_id = ?")
        params.append(run_id)
    if marker_type:
        conditions.append("marker_type = ?")
        params.append(marker_type.upper())
    if flow_key:
        conditions.append("flow_key = ?")
        params.append(flow_key)

    where_clause = " AND ".join(conditions) if conditions else "1=1"
    query = f"""
        SELECT run_id, flow_key, step_id, agent_key,
               marker_type, marker_id, content, metadata, extracted_at
        FROM facts
        WHERE {where_clause}
        ORDER BY marker_type, marker_id
    """

    try:
        results = db.connection.execute(query, params).fetchall()
        parsed_results = []
        for r in results:
            # Parse metadata JSON for source location
            import json as json_mod

            try:
                metadata = json_mod.loads(r[7]) if r[7] else {}
            except (json_mod.JSONDecodeError, TypeError):
                metadata = {}

            parsed_results.append(
                {
                    "run_id": r[0],
                    "flow_key": r[1],
                    "step_id": r[2],
                    "agent_key": r[3],
                    "marker_type": r[4],
                    "marker_id": r[5],
                    "content": r[6],
                    "source_file": metadata.get("source_file", ""),
                    "source_line": metadata.get("source_line", 0),
                    "context": metadata.get("context", ""),
                    "extracted_at": r[8].isoformat() if r[8] else None,
                }
            )
        return parsed_results
    except Exception as e:
        logger.warning("Failed to query facts: %s", e)
        return []


# =============================================================================
# Post-Step Hook
# =============================================================================


def extract_and_ingest_step_facts(
    run_base: Path,
    flow_key: str,
    step_id: str,
    run_id: str,
    db: Optional["StatsDB"] = None,
) -> ExtractionResult:
    """Post-step hook to extract and optionally ingest facts.

    This function should be called after each step completes to extract
    any inventory markers from the step's outputs and optionally ingest
    them into DuckDB.

    Args:
        run_base: The run base directory.
        flow_key: The flow key.
        step_id: The step identifier.
        run_id: The run identifier.
        db: Optional StatsDB instance for ingestion.

    Returns:
        ExtractionResult with extracted facts.
    """
    result = extract_facts_from_step(
        run_base=run_base,
        flow_key=flow_key,
        step_id=step_id,
        run_id=run_id,
    )

    if db is not None and result.facts:
        ingested = ingest_facts_to_db(result.facts, run_id, db)
        logger.info(
            "Extracted %d facts from step %s/%s, ingested %d to DB",
            len(result.facts),
            flow_key,
            step_id,
            ingested,
        )
    else:
        logger.debug(
            "Extracted %d facts from step %s/%s (no DB)",
            len(result.facts),
            flow_key,
            step_id,
        )

    return result


# =============================================================================
# CLI Entry Point
# =============================================================================


def main():
    """CLI entry point for fact extraction.

    Usage:
        python -m swarm.runtime.fact_extraction <run_id>
        python -m swarm.runtime.fact_extraction <run_id> --flow signal
        python -m swarm.runtime.fact_extraction <run_id> --ingest
        python -m swarm.runtime.fact_extraction <run_id> --json
    """
    import argparse
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="Extract inventory markers from run artifacts",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "run_id",
        help="Run ID to extract facts from",
    )
    parser.add_argument(
        "--flow",
        "-f",
        help="Filter to specific flow (signal, plan, build, gate, deploy, wisdom)",
    )
    parser.add_argument(
        "--step",
        "-s",
        help="Filter to specific step ID",
    )
    parser.add_argument(
        "--type",
        "-t",
        dest="marker_type",
        choices=list(MARKER_TYPES.keys()),
        help="Filter to specific marker type",
    )
    parser.add_argument(
        "--ingest",
        "-i",
        action="store_true",
        help="Ingest extracted facts into DuckDB",
    )
    parser.add_argument(
        "--json",
        "-j",
        action="store_true",
        help="Output as JSON",
    )
    parser.add_argument(
        "--runs-dir",
        type=Path,
        default=None,
        help="Path to runs directory (default: swarm/runs/)",
    )

    args = parser.parse_args()

    # Determine runs directory
    from .storage import find_run_path

    if args.runs_dir:
        run_base = args.runs_dir / args.run_id
    else:
        # Try to find run in runs/ or examples/
        run_base = find_run_path(args.run_id)
        if run_base is None:
            print(f"Run not found: {args.run_id}")
            sys.exit(1)

    # Extract facts
    if args.flow and args.step:
        result = extract_facts_from_step(
            run_base=run_base,
            flow_key=args.flow,
            step_id=args.step,
            run_id=args.run_id,
        )
    elif args.flow:
        # Extract from entire flow
        result = ExtractionResult()
        flow_path = run_base / args.flow
        if flow_path.exists():
            for md_file in flow_path.glob("*.md"):
                facts = extract_facts_from_file(
                    path=md_file,
                    flow_key=args.flow,
                    run_id=args.run_id,
                )
                result.facts.extend(facts)
                result.source_files.append(str(md_file))
    else:
        result = extract_facts_from_run(
            run_base=run_base,
            run_id=args.run_id,
        )

    # Filter by marker type if specified
    if args.marker_type:
        result.facts = [f for f in result.facts if f.marker_type == args.marker_type.upper()]

    # Ingest if requested
    if args.ingest:
        from .db import get_stats_db

        db = get_stats_db()
        ingested = ingest_facts_to_db(result.facts, args.run_id, db)
        print(f"Ingested {ingested} facts into DuckDB")

    # Output
    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        print(f"Extracted {len(result.facts)} facts from {len(result.source_files)} files")
        print()

        if result.errors:
            print("Errors:")
            for err in result.errors:
                print(f"  - {err}")
            print()

        # Group by marker type
        by_type: Dict[str, List[ExtractedFact]] = {}
        for fact in result.facts:
            if fact.marker_type not in by_type:
                by_type[fact.marker_type] = []
            by_type[fact.marker_type].append(fact)

        for marker_type in sorted(by_type.keys()):
            type_desc = MARKER_TYPES.get(marker_type, marker_type)
            facts = by_type[marker_type]
            print(f"{type_desc}s ({len(facts)}):")
            for fact in facts:
                source = Path(fact.source_file).name
                print(
                    f"  {fact.marker_id}: {fact.content[:60]}{'...' if len(fact.content) > 60 else ''}"
                )
                print(f"    Source: {source}:{fact.source_line}")
            print()

    sys.exit(0)


if __name__ == "__main__":
    main()
