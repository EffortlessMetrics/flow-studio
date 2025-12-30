# swarm/validator/errors.py
"""Validation error collection and formatting."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

# Error message template: [FAIL] TYPE: location problem -> Fix: action
ERROR_TEMPLATE = "[FAIL] {error_type}: {location} {problem}\n  Fix: {fix_action}"


class ValidationError:
    """Structured validation error."""

    def __init__(
        self,
        error_type: str,
        location: str,
        problem: str,
        fix_action: str,
        line_number: Optional[int] = None,
        file_path: Optional[str] = None,
    ):
        self.error_type = error_type
        self.location = location
        self.problem = problem
        self.fix_action = fix_action
        self.line_number = line_number
        self.file_path = file_path or location.split(":")[0]

    def format(self) -> str:
        """Format error message."""
        return ERROR_TEMPLATE.format(
            error_type=self.error_type,
            location=self.location,
            problem=self.problem,
            fix_action=self.fix_action,
        )

    def sort_key(self) -> Tuple[str, int]:
        """Sort key for deterministic ordering."""
        return (self.file_path, self.line_number or 0)

    def to_dict(self) -> Dict[str, Any]:
        """Convert error to dictionary for JSON serialization."""
        return {
            "type": self.error_type,
            "location": self.location,
            "problem": self.problem,
            "fix_action": self.fix_action,
            "line_number": self.line_number,
            "file_path": self.file_path,
        }


class ValidationResult:
    """Collects validation errors and warnings."""

    def __init__(self):
        self.errors: List[ValidationError] = []
        self.warnings: List[ValidationError] = []

    def add_error(
        self,
        error_type: str,
        location: str,
        problem: str,
        fix_action: str,
        line_number: Optional[int] = None,
        file_path: Optional[str] = None,
    ):
        """Add a validation error."""
        self.errors.append(
            ValidationError(
                error_type, location, problem, fix_action, line_number, file_path
            )
        )

    def add_warning(
        self,
        error_type: str,
        location: str,
        problem: str,
        fix_action: str,
        line_number: Optional[int] = None,
        file_path: Optional[str] = None,
    ):
        """Add a validation warning (design guideline violation, not an error)."""
        self.warnings.append(
            ValidationError(
                error_type, location, problem, fix_action, line_number, file_path
            )
        )

    def extend(self, other: "ValidationResult"):
        """Extend with errors and warnings from another result."""
        self.errors.extend(other.errors)
        self.warnings.extend(other.warnings)

    def has_errors(self) -> bool:
        """Check if any errors were collected."""
        return len(self.errors) > 0

    def has_warnings(self) -> bool:
        """Check if any warnings were collected."""
        return len(self.warnings) > 0

    def sorted_errors(self) -> List[ValidationError]:
        """Get errors in deterministic order."""
        return sorted(self.errors, key=lambda e: e.sort_key())

    def sorted_warnings(self) -> List[ValidationError]:
        """Get warnings in deterministic order."""
        return sorted(self.warnings, key=lambda e: e.sort_key())

    def to_dict(self) -> Dict[str, Any]:
        """Convert result to dictionary for JSON serialization."""
        return {
            "errors": [e.to_dict() for e in self.sorted_errors()],
            "warnings": [w.to_dict() for w in self.sorted_warnings()],
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "status": "FAIL" if self.has_errors() else "PASS",
        }
