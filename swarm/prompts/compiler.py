"""
compiler.py - Compile step prompts by injecting fragments.

This module provides prompt compilation functionality that:
- Loads prompt templates from swarm/prompts/agentic_steps/
- Finds and replaces {{fragment_name}} markers with fragment content
- Handles nested fragments (fragments can reference other fragments)
- Caches compiled prompts for performance
- Validates prompts for missing fragments

Fragment resolution order:
1. swarm/prompts/fragments/  (step prompts fragments - primary)
2. swarm/spec/fragments/     (spec fragments - fallback)
3. swarm/specs/fragments/    (JSON spec fragments - fallback)

Usage:
    from swarm.prompts.compiler import compile_prompt, validate_prompt

    # Compile a prompt with fragment injection
    compiled = compile_prompt("swarm/prompts/agentic_steps/code-implementer.md")

    # Validate a prompt for missing fragments
    missing = validate_prompt("swarm/prompts/agentic_steps/code-implementer.md")
"""

from __future__ import annotations

import hashlib
import logging
import re
import time
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# Maximum recursion depth for nested fragments
MAX_FRAGMENT_DEPTH = 10

# Fragment marker patterns:
# - Simple: {{fragment_name}} or {{path/to/fragment}}
# - Explicit: {{fragment:path/to/fragment}} (compatible with spec compiler)
FRAGMENT_PATTERN = re.compile(r"\{\{([a-zA-Z0-9_/\-]+)\}\}")
FRAGMENT_EXPLICIT_PATTERN = re.compile(r"\{\{fragment:([a-zA-Z0-9_/\-\.]+)\}\}")


@dataclass
class CompiledPrompt:
    """Result of prompt compilation with metadata."""

    content: str  # The compiled prompt content
    source_path: str  # Original prompt path
    fragments_used: Tuple[str, ...]  # Fragment names that were injected
    content_hash: str  # Hash of compiled content for cache validation
    compiled_at: float  # Unix timestamp


@dataclass
class FragmentCache:
    """Cache for loaded fragments with TTL."""

    _cache: Dict[str, Tuple[str, float]] = field(default_factory=dict)
    _ttl_seconds: float = 300.0  # 5 minutes default TTL

    def get(self, key: str) -> Optional[str]:
        """Get cached fragment content if not expired."""
        if key in self._cache:
            content, cached_at = self._cache[key]
            if time.time() - cached_at < self._ttl_seconds:
                return content
            # Expired - remove from cache
            del self._cache[key]
        return None

    def set(self, key: str, content: str) -> None:
        """Cache fragment content with current timestamp."""
        self._cache[key] = (content, time.time())

    def clear(self) -> None:
        """Clear all cached fragments."""
        self._cache.clear()


# Global fragment cache instance
_fragment_cache = FragmentCache()

# Global compiled prompt cache
_compiled_cache: Dict[str, CompiledPrompt] = {}


def get_repo_root() -> Path:
    """Get repository root path by searching for swarm/ directory."""
    cwd = Path.cwd()
    for parent in [cwd] + list(cwd.parents):
        if (parent / "swarm").exists():
            return parent
    return cwd


def get_fragment_dirs(repo_root: Optional[Path] = None) -> List[Path]:
    """Get directories to search for fragments, in priority order.

    Args:
        repo_root: Repository root path. If None, detected automatically.

    Returns:
        List of existing fragment directories in priority order.
    """
    if repo_root is None:
        repo_root = get_repo_root()

    dirs = [
        repo_root / "swarm" / "prompts" / "fragments",  # Primary: prompt fragments
        repo_root / "swarm" / "spec" / "fragments",  # Legacy: spec fragments
        repo_root / "swarm" / "specs" / "fragments",  # New: JSON spec fragments
    ]

    return [d for d in dirs if d.exists()]


def load_fragment(
    fragment_name: str,
    repo_root: Optional[Path] = None,
    use_cache: bool = True,
) -> str:
    """Load a fragment by name from the fragment directories.

    Fragment names can be:
    - Simple names: "git_safety_rules" -> looks for git_safety_rules.md
    - Paths: "common/invariants" -> looks for common/invariants.md
    - Names with extension: "status_model.md" -> looks for status_model.md

    Args:
        fragment_name: Fragment identifier (name or relative path).
        repo_root: Repository root path.
        use_cache: Whether to use fragment cache.

    Returns:
        Fragment content as string.

    Raises:
        FileNotFoundError: If fragment not found in any search directory.
    """
    # Check cache first
    cache_key = f"{repo_root or 'default'}:{fragment_name}"
    if use_cache:
        cached = _fragment_cache.get(cache_key)
        if cached is not None:
            return cached

    if repo_root is None:
        repo_root = get_repo_root()

    # Normalize fragment name
    # Add .md extension if not present
    if not fragment_name.endswith(".md"):
        fragment_path = f"{fragment_name}.md"
    else:
        fragment_path = fragment_name

    # Search in fragment directories
    searched_paths: List[Path] = []
    for frag_dir in get_fragment_dirs(repo_root):
        full_path = frag_dir / fragment_path
        searched_paths.append(full_path)

        if full_path.exists():
            content = full_path.read_text(encoding="utf-8")
            if use_cache:
                _fragment_cache.set(cache_key, content)
            logger.debug("Loaded fragment %s from %s", fragment_name, full_path)
            return content

    raise FileNotFoundError(
        f"Fragment not found: {fragment_name}\n"
        f"Searched in: {[str(p) for p in searched_paths]}"
    )


def list_fragments(repo_root: Optional[Path] = None) -> List[str]:
    """List all available fragment names.

    Args:
        repo_root: Repository root path.

    Returns:
        Sorted list of fragment names (relative paths without .md extension).
    """
    if repo_root is None:
        repo_root = get_repo_root()

    fragments: Set[str] = set()

    for frag_dir in get_fragment_dirs(repo_root):
        for md_file in frag_dir.rglob("*.md"):
            rel_path = md_file.relative_to(frag_dir)
            # Convert to fragment name (remove .md, use forward slashes)
            fragment_name = str(rel_path.with_suffix("")).replace("\\", "/")
            fragments.add(fragment_name)

    return sorted(fragments)


def find_fragment_markers(content: str) -> List[str]:
    """Find all fragment markers in content.

    Supports two marker formats:
    - Simple: {{fragment_name}} or {{path/to/fragment}}
    - Explicit: {{fragment:path/to/fragment}} (spec compiler compatible)

    Args:
        content: Text to search for markers.

    Returns:
        List of fragment names found in markers.
    """
    # Find simple markers: {{name}}
    simple_matches = FRAGMENT_PATTERN.findall(content)

    # Find explicit markers: {{fragment:name}}
    explicit_matches = FRAGMENT_EXPLICIT_PATTERN.findall(content)

    # Combine and deduplicate
    all_matches = simple_matches + explicit_matches
    return list(dict.fromkeys(all_matches))  # Preserve order, remove duplicates


def compile_prompt(
    prompt_path: str,
    repo_root: Optional[Path] = None,
    use_cache: bool = True,
) -> str:
    """Load a prompt and inject all fragments.

    This is the main entry point for prompt compilation. It:
    1. Loads the prompt template from the given path
    2. Finds all {{fragment_name}} markers
    3. Recursively loads and injects fragment content
    4. Returns the fully compiled prompt

    Args:
        prompt_path: Path to the prompt file (absolute or relative to repo root).
        repo_root: Repository root path.
        use_cache: Whether to use caching for compiled prompts.

    Returns:
        Compiled prompt content with all fragments injected.

    Raises:
        FileNotFoundError: If prompt or required fragment not found.
        RecursionError: If fragment nesting exceeds MAX_FRAGMENT_DEPTH.
    """
    result = compile_prompt_with_metadata(prompt_path, repo_root, use_cache)
    return result.content


def compile_prompt_with_metadata(
    prompt_path: str,
    repo_root: Optional[Path] = None,
    use_cache: bool = True,
) -> CompiledPrompt:
    """Load a prompt and inject all fragments, returning metadata.

    Like compile_prompt but returns a CompiledPrompt with metadata about
    which fragments were used, content hash, etc.

    Args:
        prompt_path: Path to the prompt file.
        repo_root: Repository root path.
        use_cache: Whether to use caching.

    Returns:
        CompiledPrompt with content and metadata.
    """
    if repo_root is None:
        repo_root = get_repo_root()

    # Resolve prompt path
    prompt_file = Path(prompt_path)
    if not prompt_file.is_absolute():
        prompt_file = repo_root / prompt_path

    if not prompt_file.exists():
        raise FileNotFoundError(f"Prompt file not found: {prompt_file}")

    # Check cache
    cache_key = str(prompt_file)
    if use_cache and cache_key in _compiled_cache:
        cached = _compiled_cache[cache_key]
        # Validate cache - check if source file changed
        current_mtime = prompt_file.stat().st_mtime
        if current_mtime <= cached.compiled_at:
            return cached

    # Load prompt content
    content = prompt_file.read_text(encoding="utf-8")

    # Compile by injecting fragments
    compiled_content, fragments_used = _inject_fragments(content, repo_root, depth=0)

    # Compute content hash
    content_hash = hashlib.sha256(compiled_content.encode("utf-8")).hexdigest()[:16]

    result = CompiledPrompt(
        content=compiled_content,
        source_path=str(prompt_file),
        fragments_used=tuple(sorted(set(fragments_used))),
        content_hash=content_hash,
        compiled_at=time.time(),
    )

    # Cache result
    if use_cache:
        _compiled_cache[cache_key] = result

    return result


def _inject_fragments(
    content: str,
    repo_root: Path,
    depth: int,
    seen_fragments: Optional[Set[str]] = None,
) -> Tuple[str, List[str]]:
    """Recursively inject fragments into content.

    Args:
        content: Text with potential {{fragment}} markers.
        repo_root: Repository root path.
        depth: Current recursion depth.
        seen_fragments: Set of already-injected fragments (for cycle detection).

    Returns:
        Tuple of (compiled content, list of fragment names used).

    Raises:
        RecursionError: If depth exceeds MAX_FRAGMENT_DEPTH.
    """
    if depth > MAX_FRAGMENT_DEPTH:
        raise RecursionError(
            f"Fragment recursion depth exceeded {MAX_FRAGMENT_DEPTH}. "
            "Check for circular fragment references."
        )

    if seen_fragments is None:
        seen_fragments = set()

    fragments_used: List[str] = []

    def replace_fragment(match: re.Match) -> str:
        fragment_name = match.group(1).strip()
        fragments_used.append(fragment_name)

        # Check for circular reference
        if fragment_name in seen_fragments:
            logger.warning(
                "Circular fragment reference detected: %s (skipping)", fragment_name
            )
            return f"[CIRCULAR REFERENCE: {fragment_name}]"

        try:
            fragment_content = load_fragment(fragment_name, repo_root)

            # Recursively process nested fragments
            new_seen = seen_fragments | {fragment_name}
            nested_content, nested_fragments = _inject_fragments(
                fragment_content, repo_root, depth + 1, new_seen
            )
            fragments_used.extend(nested_fragments)

            return nested_content.strip()

        except FileNotFoundError:
            logger.error("Fragment not found: %s", fragment_name)
            return f"[FRAGMENT NOT FOUND: {fragment_name}]"

    # Replace simple markers: {{name}}
    compiled = FRAGMENT_PATTERN.sub(replace_fragment, content)

    # Replace explicit markers: {{fragment:name}}
    compiled = FRAGMENT_EXPLICIT_PATTERN.sub(replace_fragment, compiled)

    return compiled, fragments_used


def validate_prompt(
    prompt_path: str,
    repo_root: Optional[Path] = None,
) -> List[str]:
    """Validate a prompt for missing fragments.

    Args:
        prompt_path: Path to the prompt file.
        repo_root: Repository root path.

    Returns:
        List of missing fragment names. Empty list if all fragments found.
    """
    if repo_root is None:
        repo_root = get_repo_root()

    # Resolve prompt path
    prompt_file = Path(prompt_path)
    if not prompt_file.is_absolute():
        prompt_file = repo_root / prompt_path

    if not prompt_file.exists():
        return [f"PROMPT_NOT_FOUND:{prompt_path}"]

    content = prompt_file.read_text(encoding="utf-8")

    return _validate_fragments(content, repo_root, depth=0)


def _validate_fragments(
    content: str,
    repo_root: Path,
    depth: int,
    seen: Optional[Set[str]] = None,
) -> List[str]:
    """Recursively validate fragments in content.

    Args:
        content: Text to validate.
        repo_root: Repository root path.
        depth: Current recursion depth.
        seen: Already-validated fragments.

    Returns:
        List of missing fragment names.
    """
    if depth > MAX_FRAGMENT_DEPTH:
        return ["RECURSION_DEPTH_EXCEEDED"]

    if seen is None:
        seen = set()

    missing: List[str] = []
    fragment_names = find_fragment_markers(content)

    for fragment_name in fragment_names:
        if fragment_name in seen:
            continue
        seen.add(fragment_name)

        try:
            fragment_content = load_fragment(fragment_name, repo_root, use_cache=False)
            # Recursively validate nested fragments
            nested_missing = _validate_fragments(
                fragment_content, repo_root, depth + 1, seen
            )
            missing.extend(nested_missing)
        except FileNotFoundError:
            missing.append(fragment_name)

    return missing


def validate_all_prompts(
    prompt_dir: Optional[str] = None,
    repo_root: Optional[Path] = None,
) -> Dict[str, List[str]]:
    """Validate all prompts in a directory for missing fragments.

    Args:
        prompt_dir: Directory containing prompt files. Defaults to agentic_steps.
        repo_root: Repository root path.

    Returns:
        Dict mapping prompt paths to their missing fragments.
        Only includes prompts with missing fragments.
    """
    if repo_root is None:
        repo_root = get_repo_root()

    if prompt_dir is None:
        prompt_dir = "swarm/prompts/agentic_steps"

    dir_path = Path(prompt_dir)
    if not dir_path.is_absolute():
        dir_path = repo_root / prompt_dir

    if not dir_path.exists():
        return {"ERROR": [f"Directory not found: {prompt_dir}"]}

    results: Dict[str, List[str]] = {}

    for prompt_file in dir_path.glob("*.md"):
        missing = validate_prompt(str(prompt_file), repo_root)
        if missing:
            results[str(prompt_file.relative_to(repo_root))] = missing

    return results


def clear_cache() -> None:
    """Clear all caches (fragments and compiled prompts)."""
    _fragment_cache.clear()
    _compiled_cache.clear()


# =============================================================================
# Convenience functions for common use cases
# =============================================================================


def compile_step_prompt(step_name: str, repo_root: Optional[Path] = None) -> str:
    """Compile a step prompt by name.

    Convenience function that looks up step prompts in the standard location.

    Args:
        step_name: Step name (e.g., "code-implementer", "test-author").
        repo_root: Repository root path.

    Returns:
        Compiled prompt content.

    Example:
        >>> prompt = compile_step_prompt("code-implementer")
    """
    prompt_path = f"swarm/prompts/agentic_steps/{step_name}.md"
    return compile_prompt(prompt_path, repo_root)


def get_fragment_usage(repo_root: Optional[Path] = None) -> Dict[str, List[str]]:
    """Get a report of which prompts use which fragments.

    Args:
        repo_root: Repository root path.

    Returns:
        Dict mapping fragment names to list of prompts that use them.
    """
    if repo_root is None:
        repo_root = get_repo_root()

    usage: Dict[str, List[str]] = {}
    prompt_dir = repo_root / "swarm" / "prompts" / "agentic_steps"

    if not prompt_dir.exists():
        return usage

    for prompt_file in prompt_dir.glob("*.md"):
        content = prompt_file.read_text(encoding="utf-8")
        fragments = find_fragment_markers(content)

        for fragment in fragments:
            if fragment not in usage:
                usage[fragment] = []
            usage[fragment].append(prompt_file.name)

    return usage


# =============================================================================
# CLI entry point
# =============================================================================


def main() -> None:
    """CLI entry point for prompt compilation."""
    import argparse
    import sys

    # Force UTF-8 output on Windows
    if sys.stdout.encoding != "utf-8":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except (AttributeError, OSError):
            pass

    parser = argparse.ArgumentParser(description="Prompt compiler with fragment injection")
    parser.add_argument(
        "command",
        choices=["compile", "validate", "list-fragments", "usage"],
        help="Command to run",
    )
    parser.add_argument(
        "--prompt",
        help="Prompt path for compile/validate commands",
    )
    parser.add_argument(
        "--dir",
        help="Directory for validate-all command",
    )
    parser.add_argument(
        "--output",
        help="Output file for compiled prompt",
    )

    args = parser.parse_args()

    if args.command == "compile":
        if not args.prompt:
            print("ERROR: --prompt required for compile command")
            sys.exit(1)

        try:
            result = compile_prompt_with_metadata(args.prompt)
            print(f"# Compiled from: {result.source_path}")
            print(f"# Fragments used: {', '.join(result.fragments_used) or 'none'}")
            print(f"# Content hash: {result.content_hash}")
            print()
            print(result.content)

            if args.output:
                Path(args.output).write_text(result.content, encoding="utf-8")
                print(f"\nWritten to: {args.output}")

        except FileNotFoundError as e:
            print(f"ERROR: {e}")
            sys.exit(1)

    elif args.command == "validate":
        if args.prompt:
            missing = validate_prompt(args.prompt)
            if missing:
                print(f"Missing fragments in {args.prompt}:")
                for m in missing:
                    print(f"  - {m}")
                sys.exit(1)
            else:
                print(f"OK: {args.prompt} - all fragments found")
        else:
            results = validate_all_prompts(args.dir)
            if results:
                print("Prompts with missing fragments:")
                for prompt, missing in results.items():
                    print(f"\n  {prompt}:")
                    for m in missing:
                        print(f"    - {m}")
                sys.exit(1)
            else:
                print("OK: All prompts have valid fragment references")

    elif args.command == "list-fragments":
        fragments = list_fragments()
        print(f"Available fragments ({len(fragments)}):")
        for f in fragments:
            print(f"  {f}")

    elif args.command == "usage":
        usage = get_fragment_usage()
        if usage:
            print("Fragment usage:")
            for fragment, prompts in sorted(usage.items()):
                print(f"\n  {fragment}:")
                for p in prompts:
                    print(f"    - {p}")
        else:
            print("No fragment usage found")


if __name__ == "__main__":
    main()
