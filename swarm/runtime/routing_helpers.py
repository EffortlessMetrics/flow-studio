"""
routing_helpers.py - Shared microloop exit logic.

This module provides the SINGLE source of truth for microloop termination decisions.
All routing-related code should import from here instead of maintaining separate
exit condition checks.

Microloop Exit Contract (from CLAUDE.md):
-----------------------------------------
**Continue looping while:**
- status == UNVERIFIED **and**
- can_further_iteration_help == yes (in critic's Iteration Guidance)

**Exit loop when:**
- status == VERIFIED, **or**
- status == UNVERIFIED **and** can_further_iteration_help == no
  (critic explicitly judges there is no viable fix path within current scope/constraints)

Critics **never fix**; they write harsh critiques with clear status and explicit
iteration guidance. Implementers may be called multiple times while
can_further_iteration_help == yes.

Note: max_iterations is a safety fuse, not a steering mechanism. Actual loop exit
should be driven by:
1. VERIFIED status from critic
2. can_further_iteration_help == False from critic
3. Safety fuse: max_iterations reached (fallback)

Exit Reason Codes:
- "status_verified": status == VERIFIED
- "max_iterations_reached": current_iteration >= max_iterations
- "no_further_help": can_further_iteration_help == "no" or False

Usage:
    >>> from swarm.runtime.routing_helpers import should_exit_microloop, MicroloopState
    >>> state = MicroloopState(current_iteration=2, max_iterations=5, status="VERIFIED")
    >>> should_exit, reason = should_exit_microloop(state)
    >>> should_exit
    True
    >>> reason
    'status_verified'
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Union

# =============================================================================
# MICROLOOP STATE DATACLASS
# =============================================================================


@dataclass
class MicroloopState:
    """State for microloop exit decision.

    Captures all signals needed to determine whether a microloop should exit.

    Attributes:
        current_iteration: Current iteration count (0-indexed).
        max_iterations: Maximum allowed iterations (safety fuse).
        status: Step status (VERIFIED, UNVERIFIED, PARTIAL, BLOCKED).
        can_further_iteration_help: Whether further iteration can improve outcome.
            Can be "yes"/"no" string or True/False boolean.
        success_values: List of status values that trigger exit (default ["VERIFIED"]).

    Examples:
        >>> state = MicroloopState(
        ...     current_iteration=1,
        ...     max_iterations=5,
        ...     status="VERIFIED",
        ...     can_further_iteration_help="yes"
        ... )
        >>> state.current_iteration
        1
        >>> state.status
        'VERIFIED'

        >>> state2 = MicroloopState(
        ...     current_iteration=3,
        ...     max_iterations=3,
        ...     status="UNVERIFIED",
        ...     can_further_iteration_help="no"
        ... )
        >>> state2.is_at_max_iterations()
        True
    """

    current_iteration: int
    max_iterations: int
    status: str  # VERIFIED, UNVERIFIED, PARTIAL, BLOCKED
    can_further_iteration_help: Union[str, bool] = "yes"  # "yes"/"no" or True/False
    success_values: List[str] = field(default_factory=lambda: ["VERIFIED"])

    def is_status_success(self) -> bool:
        """Check if status matches success values.

        Returns:
            True if status is in success_values (case-insensitive).

        Examples:
            >>> MicroloopState(0, 5, "VERIFIED").is_status_success()
            True
            >>> MicroloopState(0, 5, "verified").is_status_success()
            True
            >>> MicroloopState(0, 5, "UNVERIFIED").is_status_success()
            False
        """
        status_upper = self.status.upper() if self.status else ""
        return status_upper in [s.upper() for s in self.success_values]

    def is_at_max_iterations(self) -> bool:
        """Check if current iteration meets or exceeds max_iterations.

        Returns:
            True if at or beyond max iterations.

        Examples:
            >>> MicroloopState(5, 5, "UNVERIFIED").is_at_max_iterations()
            True
            >>> MicroloopState(4, 5, "UNVERIFIED").is_at_max_iterations()
            False
        """
        return self.current_iteration >= self.max_iterations

    def can_help(self) -> bool:
        """Check if further iteration can help.

        Normalizes string values "yes"/"no"/"true"/"false" and boolean values.

        Returns:
            True if iteration can help, False otherwise.

        Examples:
            >>> MicroloopState(0, 5, "UNVERIFIED", "yes").can_help()
            True
            >>> MicroloopState(0, 5, "UNVERIFIED", "no").can_help()
            False
            >>> MicroloopState(0, 5, "UNVERIFIED", True).can_help()
            True
            >>> MicroloopState(0, 5, "UNVERIFIED", False).can_help()
            False
            >>> MicroloopState(0, 5, "UNVERIFIED", "TRUE").can_help()
            True
        """
        return _normalize_can_help(self.can_further_iteration_help)


# =============================================================================
# CORE EXIT LOGIC
# =============================================================================


def _normalize_can_help(value: Union[str, bool, None]) -> bool:
    """Normalize can_further_iteration_help to boolean.

    Args:
        value: String ("yes"/"no"/"true"/"false") or boolean.

    Returns:
        True if help is possible, False otherwise.

    Examples:
        >>> _normalize_can_help("yes")
        True
        >>> _normalize_can_help("no")
        False
        >>> _normalize_can_help("true")
        True
        >>> _normalize_can_help("false")
        False
        >>> _normalize_can_help(True)
        True
        >>> _normalize_can_help(False)
        False
        >>> _normalize_can_help(None)
        True
        >>> _normalize_can_help("YES")
        True
        >>> _normalize_can_help("1")
        True
        >>> _normalize_can_help("0")
        False
    """
    if value is None:
        return True  # Default: assume help is possible
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ("yes", "true", "1")
    return True  # Fallback: assume help is possible


def should_exit_microloop(state: MicroloopState) -> Tuple[bool, str]:
    """Determine if microloop should exit based on state.

    This is the SINGLE source of truth for microloop termination decisions.
    All routing code should use this function instead of duplicating logic.

    Priority order:
    1. status == VERIFIED (or in success_values) -> exit with "status_verified"
    2. current_iteration >= max_iterations -> exit with "max_iterations_reached"
    3. can_further_iteration_help == "no" -> exit with "no_further_help"
    4. Otherwise -> continue looping (False, "")

    Args:
        state: MicroloopState containing all decision inputs.

    Returns:
        Tuple of (should_exit: bool, reason: str).
        If should_exit is True, reason contains exit reason code.
        If should_exit is False, reason is empty string.

    Examples:
        >>> # Exit: VERIFIED status
        >>> should_exit_microloop(MicroloopState(1, 5, "VERIFIED"))
        (True, 'status_verified')

        >>> # Exit: max iterations reached
        >>> should_exit_microloop(MicroloopState(5, 5, "UNVERIFIED"))
        (True, 'max_iterations_reached')

        >>> # Exit: no further help possible
        >>> should_exit_microloop(MicroloopState(2, 5, "UNVERIFIED", "no"))
        (True, 'no_further_help')

        >>> # Continue: UNVERIFIED but help is possible
        >>> should_exit_microloop(MicroloopState(2, 5, "UNVERIFIED", "yes"))
        (False, '')

        >>> # Continue: still under max iterations
        >>> should_exit_microloop(MicroloopState(1, 5, "PARTIAL", True))
        (False, '')

        >>> # Custom success values
        >>> state = MicroloopState(1, 5, "COMPLETE", success_values=["COMPLETE", "DONE"])
        >>> should_exit_microloop(state)
        (True, 'status_verified')
    """
    # Priority 1: Check success status
    if state.is_status_success():
        return (True, "status_verified")

    # Priority 2: Check iteration limit (safety fuse)
    if state.is_at_max_iterations():
        return (True, "max_iterations_reached")

    # Priority 3: Check can_further_iteration_help
    if not state.can_help():
        return (True, "no_further_help")

    # Continue looping
    return (False, "")


# =============================================================================
# CONVENIENCE WRAPPER FOR EXISTING CODE
# =============================================================================


def check_microloop_termination(
    handoff: Dict[str, Any],
    routing_config: Dict[str, Any],
    iteration: int,
) -> Optional[str]:
    """Check if microloop should terminate based on handoff and routing config.

    This is a convenience wrapper that extracts state from handoff and routing_config
    dictionaries and delegates to should_exit_microloop(). Existing code can call
    this function directly instead of manually constructing MicroloopState.

    Args:
        handoff: The handoff JSON from step finalization. Expected keys:
            - "status": Step status (VERIFIED, UNVERIFIED, etc.)
            - "can_further_iteration_help": Optional, "yes"/"no" or True/False
        routing_config: The step's routing configuration. Expected keys:
            - "max_iterations": Maximum iterations (default 3)
            - "loop_success_values": Status values that trigger exit (default ["VERIFIED"])
            - "loop_condition_field": Field to check for status (default "status")
        iteration: Current loop iteration count (0-indexed).

    Returns:
        Exit reason string if loop should exit, None if loop should continue.
        Reason codes: "status_verified", "max_iterations_reached", "no_further_help"

    Examples:
        >>> # Exit: VERIFIED status
        >>> handoff = {"status": "VERIFIED"}
        >>> config = {"max_iterations": 5}
        >>> check_microloop_termination(handoff, config, 1)
        'status_verified'

        >>> # Exit: max iterations
        >>> handoff = {"status": "UNVERIFIED"}
        >>> config = {"max_iterations": 3}
        >>> check_microloop_termination(handoff, config, 3)
        'max_iterations_reached'

        >>> # Exit: no further help
        >>> handoff = {"status": "UNVERIFIED", "can_further_iteration_help": "no"}
        >>> config = {"max_iterations": 5}
        >>> check_microloop_termination(handoff, config, 1)
        'no_further_help'

        >>> # Continue: under limit and help possible
        >>> handoff = {"status": "UNVERIFIED", "can_further_iteration_help": "yes"}
        >>> config = {"max_iterations": 5}
        >>> check_microloop_termination(handoff, config, 2) is None
        True

        >>> # Custom success values
        >>> handoff = {"status": "PASSED"}
        >>> config = {"max_iterations": 5, "loop_success_values": ["PASSED", "VERIFIED"]}
        >>> check_microloop_termination(handoff, config, 1)
        'status_verified'

        >>> # Custom status field
        >>> handoff = {"result": "VERIFIED"}
        >>> config = {"max_iterations": 5, "loop_condition_field": "result"}
        >>> check_microloop_termination(handoff, config, 1)
        'status_verified'
    """
    # Extract configuration with defaults
    max_iterations = routing_config.get("max_iterations", 3)
    success_values = routing_config.get("loop_success_values", ["VERIFIED"])
    status_field = routing_config.get("loop_condition_field", "status")

    # Extract status from handoff using configured field
    status = handoff.get(status_field, "")
    if isinstance(status, str):
        status = status.upper()

    # Extract can_further_iteration_help
    can_help = handoff.get("can_further_iteration_help", True)

    # Build state and delegate to core function
    state = MicroloopState(
        current_iteration=iteration,
        max_iterations=max_iterations,
        status=status,
        can_further_iteration_help=can_help,
        success_values=success_values,
    )

    should_exit, reason = should_exit_microloop(state)
    return reason if should_exit else None


# =============================================================================
# UTILITIES FOR MIGRATION
# =============================================================================


def exit_reason_to_human_readable(reason: str) -> str:
    """Convert exit reason code to human-readable string.

    Args:
        reason: Exit reason code from should_exit_microloop().

    Returns:
        Human-readable description of the exit reason.

    Examples:
        >>> exit_reason_to_human_readable("status_verified")
        'Status is VERIFIED'
        >>> exit_reason_to_human_readable("max_iterations_reached")
        'Maximum iterations reached'
        >>> exit_reason_to_human_readable("no_further_help")
        'Critic indicated no further iteration can help'
        >>> exit_reason_to_human_readable("")
        ''
        >>> exit_reason_to_human_readable("unknown")
        'Unknown exit reason: unknown'
    """
    mapping = {
        "status_verified": "Status is VERIFIED",
        "max_iterations_reached": "Maximum iterations reached",
        "no_further_help": "Critic indicated no further iteration can help",
        "": "",
    }
    return mapping.get(reason, f"Unknown exit reason: {reason}")


def exit_reason_needs_human_review(reason: str) -> bool:
    """Check if exit reason indicates human review is needed.

    VERIFIED exits are clean; other exits may need human review.

    Args:
        reason: Exit reason code from should_exit_microloop().

    Returns:
        True if human should review, False otherwise.

    Examples:
        >>> exit_reason_needs_human_review("status_verified")
        False
        >>> exit_reason_needs_human_review("max_iterations_reached")
        True
        >>> exit_reason_needs_human_review("no_further_help")
        True
        >>> exit_reason_needs_human_review("")
        False
    """
    return reason in ("max_iterations_reached", "no_further_help")


def exit_reason_to_confidence(reason: str) -> float:
    """Map exit reason to confidence score.

    Clean exits have high confidence; forced exits have lower confidence.

    Args:
        reason: Exit reason code from should_exit_microloop().

    Returns:
        Confidence score between 0.0 and 1.0.

    Examples:
        >>> exit_reason_to_confidence("status_verified")
        1.0
        >>> exit_reason_to_confidence("no_further_help")
        0.8
        >>> exit_reason_to_confidence("max_iterations_reached")
        0.7
        >>> exit_reason_to_confidence("")
        1.0
    """
    mapping = {
        "status_verified": 1.0,
        "no_further_help": 0.8,
        "max_iterations_reached": 0.7,
        "": 1.0,  # Continue has full confidence
    }
    return mapping.get(reason, 0.5)


# =============================================================================
# MODULE DOCTEST
# =============================================================================

if __name__ == "__main__":
    import doctest

    results = doctest.testmod(verbose=True)
    print(f"\nPassed: {results.attempted - results.failed}/{results.attempted}")
