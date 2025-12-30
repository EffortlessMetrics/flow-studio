"""Path helpers for transcript and receipt file naming.

Provides unified, engine-agnostic path construction for LLM execution
artifacts to ensure consistency across all stepwise engines.

Standard conventions:
- Transcripts: RUN_BASE/llm/<step_id>-<agent_key>-<engine>.jsonl
- Receipts: RUN_BASE/receipts/<step_id>-<agent_key>.json

Usage:
    from swarm.runtime.path_helpers import (
        transcript_path,
        receipt_path,
        ensure_llm_dir,
        ensure_receipts_dir,
        parse_transcript_filename,
        parse_receipt_filename,
        list_transcripts,
        list_receipts,
    )
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional, Tuple

# Directory names
LLM_DIR = "llm"
RECEIPTS_DIR = "receipts"
HANDOFF_DIR = "handoff"
FORENSICS_DIR = "forensics"

# File extensions
TRANSCRIPT_EXT = ".jsonl"
RECEIPT_EXT = ".json"

# Pattern for parsing transcript filenames: <step_id>-<agent_key>-<engine>.jsonl
# step_id uses underscores (no hyphens), agent_key uses hyphens, engine has no hyphens
# This allows unambiguous parsing: step_id ends at first hyphen, engine is last segment
TRANSCRIPT_PATTERN = re.compile(r"^([a-zA-Z0-9_]+)-(.+)-([a-zA-Z0-9]+)\.jsonl$")

# Pattern for parsing receipt filenames: <step_id>-<agent_key>.json
# step_id uses underscores (no hyphens), agent_key is everything after first hyphen
RECEIPT_PATTERN = re.compile(r"^([a-zA-Z0-9_]+)-(.+)\.json$")


def transcript_path(
    run_base: Path,
    step_id: str,
    agent_key: str,
    engine: str,
) -> Path:
    """Generate transcript file path.

    Args:
        run_base: The RUN_BASE path (e.g., swarm/runs/<run-id>/<flow-key>)
        step_id: Step identifier within the flow
        agent_key: Agent key assigned to the step
        engine: Engine identifier (claude, gemini)

    Returns:
        Path to the transcript file: RUN_BASE/llm/<step_id>-<agent_key>-<engine>.jsonl

    Example:
        >>> transcript_path(Path("/runs/abc/build"), "1", "code-implementer", "claude")
        PosixPath('/runs/abc/build/llm/1-code-implementer-claude.jsonl')
    """
    filename = f"{step_id}-{agent_key}-{engine}{TRANSCRIPT_EXT}"
    return run_base / LLM_DIR / filename


def receipt_path(
    run_base: Path,
    step_id: str,
    agent_key: str,
) -> Path:
    """Generate receipt file path.

    Args:
        run_base: The RUN_BASE path
        step_id: Step identifier
        agent_key: Agent key

    Returns:
        Path to the receipt file: RUN_BASE/receipts/<step_id>-<agent_key>.json

    Example:
        >>> receipt_path(Path("/runs/abc/build"), "1", "code-implementer")
        PosixPath('/runs/abc/build/receipts/1-code-implementer.json')
    """
    filename = f"{step_id}-{agent_key}{RECEIPT_EXT}"
    return run_base / RECEIPTS_DIR / filename


def ensure_llm_dir(run_base: Path) -> Path:
    """Ensure llm/ directory exists and return its path.

    Creates the directory and any parent directories if they don't exist.

    Args:
        run_base: The RUN_BASE path

    Returns:
        Path to the llm/ directory

    Example:
        >>> llm_dir = ensure_llm_dir(Path("/runs/abc/build"))
        >>> llm_dir.exists()
        True
    """
    llm_path = run_base / LLM_DIR
    llm_path.mkdir(parents=True, exist_ok=True)
    return llm_path


def ensure_receipts_dir(run_base: Path) -> Path:
    """Ensure receipts/ directory exists and return its path.

    Creates the directory and any parent directories if they don't exist.

    Args:
        run_base: The RUN_BASE path

    Returns:
        Path to the receipts/ directory

    Example:
        >>> receipts_dir = ensure_receipts_dir(Path("/runs/abc/build"))
        >>> receipts_dir.exists()
        True
    """
    receipts_path = run_base / RECEIPTS_DIR
    receipts_path.mkdir(parents=True, exist_ok=True)
    return receipts_path


def ensure_handoff_dir(run_base: Path) -> Path:
    """Ensure handoff/ directory exists and return its path.

    Creates the directory and any parent directories if they don't exist.
    Handoff files contain structured HandoffEnvelope JSON artifacts
    for cross-step communication.

    Args:
        run_base: The RUN_BASE path

    Returns:
        Path to the handoff/ directory

    Example:
        >>> handoff_dir = ensure_handoff_dir(Path("/runs/abc/build"))
        >>> handoff_dir.exists()
        True
    """
    handoff_path = run_base / HANDOFF_DIR
    handoff_path.mkdir(parents=True, exist_ok=True)
    return handoff_path


def handoff_envelope_path(run_base: Path, step_id: str) -> Path:
    """Generate handoff envelope file path.

    Args:
        run_base: The RUN_BASE path (e.g., swarm/runs/<run-id>/<flow-key>)
        step_id: Step identifier within the flow

    Returns:
        Path to the handoff envelope file: RUN_BASE/handoff/<step_id>.json

    Example:
        >>> handoff_envelope_path(Path("/runs/abc/build"), "1")
        PosixPath('/runs/abc/build/handoff/1.json')
    """
    filename = f"{step_id}.json"
    return run_base / HANDOFF_DIR / filename


def ensure_forensics_dir(run_base: Path) -> Path:
    """Ensure forensics/ directory exists and return its path.

    Creates the directory and any parent directories if they don't exist.
    Forensics files contain out-of-line data extracted from handoff envelopes
    to reduce ledger bloat (e.g., file_changes, large artifacts).

    Args:
        run_base: The RUN_BASE path

    Returns:
        Path to the forensics/ directory

    Example:
        >>> forensics_dir = ensure_forensics_dir(Path("/runs/abc/build"))
        >>> forensics_dir.exists()
        True
    """
    forensics_path = run_base / FORENSICS_DIR
    forensics_path.mkdir(parents=True, exist_ok=True)
    return forensics_path


def file_changes_path(run_base: Path, step_id: str) -> Path:
    """Generate file_changes artifact path for out-of-line storage.

    When file_changes data exceeds a size threshold, it is extracted
    from the handoff envelope and stored separately in the forensics
    directory to reduce ledger bloat.

    Args:
        run_base: The RUN_BASE path (e.g., swarm/runs/<run-id>/<flow-key>)
        step_id: Step identifier within the flow

    Returns:
        Path to the file_changes artifact: RUN_BASE/forensics/file_changes_<step_id>.json

    Example:
        >>> file_changes_path(Path("/runs/abc/build"), "1")
        PosixPath('/runs/abc/build/forensics/file_changes_1.json')
    """
    filename = f"file_changes_{step_id}.json"
    return run_base / FORENSICS_DIR / filename


def parse_transcript_filename(filename: str) -> Optional[Tuple[str, str, str]]:
    """Parse <step_id>-<agent_key>-<engine>.jsonl into (step_id, agent_key, engine).

    Step IDs use underscores (no hyphens), while agent keys typically have hyphens.
    This allows unambiguous parsing.

    Args:
        filename: The transcript filename (e.g., "implement-code-implementer-claude.jsonl")

    Returns:
        Tuple of (step_id, agent_key, engine) if valid, None otherwise.

    Examples:
        >>> parse_transcript_filename("implement-code-implementer-claude.jsonl")
        ('implement', 'code-implementer', 'claude')
        >>> parse_transcript_filename("author_tests-test-author-gemini.jsonl")
        ('author_tests', 'test-author', 'gemini')
        >>> parse_transcript_filename("invalid.txt")
        None
    """
    match = TRANSCRIPT_PATTERN.match(filename)
    if match is None:
        return None

    step_id = match.group(1)
    agent_key = match.group(2)
    engine = match.group(3)

    # Validate non-empty parts
    if not step_id or not agent_key or not engine:
        return None

    return (step_id, agent_key, engine)


def parse_receipt_filename(filename: str) -> Optional[Tuple[str, str]]:
    """Parse <step_id>-<agent_key>.json into (step_id, agent_key).

    Step IDs use underscores (no hyphens), while agent keys typically have hyphens.
    This allows unambiguous parsing.

    Args:
        filename: The receipt filename (e.g., "implement-code-implementer.json")

    Returns:
        Tuple of (step_id, agent_key) if valid, None otherwise.

    Examples:
        >>> parse_receipt_filename("implement-code-implementer.json")
        ('implement', 'code-implementer')
        >>> parse_receipt_filename("author_tests-test-author.json")
        ('author_tests', 'test-author')
        >>> parse_receipt_filename("invalid.txt")
        None
    """
    match = RECEIPT_PATTERN.match(filename)
    if match is None:
        return None

    step_id = match.group(1)
    agent_key = match.group(2)

    # Validate non-empty parts
    if not step_id or not agent_key:
        return None

    return (step_id, agent_key)


def list_transcripts(run_base: Path, engine: Optional[str] = None) -> List[Path]:
    """List all transcript files, optionally filtered by engine.

    Args:
        run_base: The RUN_BASE path
        engine: Optional engine to filter by (e.g., "claude", "gemini")

    Returns:
        List of transcript file paths, sorted by name.
        Returns empty list if directory doesn't exist.

    Example:
        >>> transcripts = list_transcripts(Path("/runs/abc/build"))
        >>> transcripts = list_transcripts(Path("/runs/abc/build"), engine="claude")
    """
    llm_dir = run_base / LLM_DIR

    if not llm_dir.exists():
        return []

    transcripts: List[Path] = []
    for entry in llm_dir.iterdir():
        if not entry.is_file():
            continue
        if not entry.name.endswith(TRANSCRIPT_EXT):
            continue

        # Optionally filter by engine
        if engine is not None:
            parsed = parse_transcript_filename(entry.name)
            if parsed is None or parsed[2] != engine:
                continue

        transcripts.append(entry)

    return sorted(transcripts, key=lambda p: p.name)


def list_receipts(run_base: Path) -> List[Path]:
    """List all receipt files.

    Args:
        run_base: The RUN_BASE path

    Returns:
        List of receipt file paths, sorted by name.
        Returns empty list if directory doesn't exist.

    Example:
        >>> receipts = list_receipts(Path("/runs/abc/build"))
    """
    receipts_dir = run_base / RECEIPTS_DIR

    if not receipts_dir.exists():
        return []

    receipts: List[Path] = []
    for entry in receipts_dir.iterdir():
        if not entry.is_file():
            continue
        if not entry.name.endswith(RECEIPT_EXT):
            continue

        receipts.append(entry)

    return sorted(receipts, key=lambda p: p.name)
