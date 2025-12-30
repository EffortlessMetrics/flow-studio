"""
sidequest_catalog.py - Catalog of available sidequests for intelligent navigation

Sidequests are pre-defined detour patterns that the Navigator can inject
when specific conditions are detected. Each sidequest specifies:
- When to trigger (conditions)
- What to execute (station/template)
- How to resume (return behavior)

The catalog is loaded from YAML/JSON files and provided to the Navigator
as a bounded menu of options.

Usage:
    from swarm.runtime.sidequest_catalog import (
        SidequestCatalog,
        load_default_catalog,
        evaluate_triggers,
    )

    catalog = load_default_catalog()
    applicable = catalog.get_applicable_sidequests(
        verification_passed=False,
        stall_detected=True,
        touched_security_paths=True,
    )
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# =============================================================================
# Sidequest Definition
# =============================================================================


@dataclass
class TriggerCondition:
    """A condition that can trigger a sidequest.

    Conditions are evaluated by traditional tooling (no LLM).
    Supported condition types:
    - field_check: Check a field value (e.g., verification_passed == False)
    - stall: Stall detected by ProgressTracker
    - path_pattern: File paths match a pattern (e.g., "auth/*", "security/*")
    - iteration_count: Microloop iteration threshold
    """

    condition_type: str  # field_check, stall, path_pattern, iteration_count
    field: Optional[str] = None  # For field_check
    operator: str = "equals"  # equals, not_equals, gt, lt, gte, lte, contains
    value: Any = None  # Expected value
    pattern: Optional[str] = None  # For path_pattern


@dataclass
class SidequestStep:
    """A single step in a multi-step sidequest mini-flow.

    Multi-step sidequests allow complex investigations like:
    - context-loader -> architecture-critic -> plan-writer
    - env-doctor -> test-runner -> fixer

    Attributes:
        template_id: Station/template to execute for this step.
        step_id: Unique ID for this step (auto-generated if not provided).
        objective_override: Override station's default objective.
        params: Additional parameters for this step.
        inputs_from: Where to get inputs (["previous", "origin"]).
        outputs_to: Artifact names to produce.
        on_verified: What to do if step is VERIFIED ("next", "skip_to:X", "halt", "resume").
        on_unverified: What to do if step is UNVERIFIED (default: continue).
        on_blocked: What to do if step is BLOCKED (default: halt).
        max_turns: Maximum turns for this step.
        model_tier: Model tier override ("haiku", "sonnet", "opus").
    """

    template_id: str
    step_id: Optional[str] = None
    objective_override: Optional[str] = None
    params: Dict[str, Any] = field(default_factory=dict)
    inputs_from: List[str] = field(default_factory=list)
    outputs_to: List[str] = field(default_factory=list)
    on_verified: str = "next"
    on_unverified: str = "next"
    on_blocked: str = "halt"
    max_turns: Optional[int] = None
    model_tier: Optional[str] = None


@dataclass
class ReturnBehavior:
    """Specifies how to return after sidequest completes.

    Modes:
    - resume: Return to where we were interrupted
    - bounce_to: Go to a specific node
    - advance: Go to next node after original
    - halt: Stop the flow
    - conditional: Evaluate condition to decide

    Attributes:
        mode: Return mode.
        target_node: Target node for bounce_to mode.
        condition: CEL expression for conditional mode.
        on_condition_true: Target if condition is true.
        on_condition_false: Target if condition is false.
        pass_artifacts: Artifacts to forward to resume point.
    """

    mode: str = "resume"
    target_node: Optional[str] = None
    condition: Optional[str] = None
    on_condition_true: Optional[str] = None
    on_condition_false: Optional[str] = None
    pass_artifacts: List[str] = field(default_factory=list)


@dataclass
class SidequestDefinition:
    """Definition of a sidequest in the catalog (v2: multi-step support).

    Sidequests are pre-defined detour patterns. When triggered, they:
    1. Push current state to interruption stack
    2. Execute the sidequest steps (1 or more)
    3. Resume from where we left off

    Multi-step sidequests allow complex investigations like:
    - context-loader -> architecture-critic -> plan-writer
    - env-doctor -> test-runner -> fixer

    For backwards compatibility, single-station sidequests still work.
    """

    sidequest_id: str
    name: str
    description: str

    # Multi-step support (v2)
    steps: List[SidequestStep] = field(default_factory=list)

    # Single-station support (v1, backwards compatible)
    station_id: Optional[str] = None  # Station to execute for this sidequest
    objective_template: Optional[str] = None  # Template with {{placeholders}}

    # Trigger conditions
    triggers: List[TriggerCondition] = field(default_factory=list)
    trigger_mode: str = "any"  # any (OR) or all (AND)

    # Execution policy
    priority: int = 50  # Higher = more likely to be selected
    cost_hint: str = "low"  # low, medium, high (relative LLM cost)
    max_uses_per_run: int = 3  # Prevent infinite sidequest loops

    # Return behavior (enhanced for v2)
    return_behavior: ReturnBehavior = field(default_factory=lambda: ReturnBehavior(mode="resume"))

    # Metadata
    tags: List[str] = field(default_factory=list)

    # Flow-level settings (v2)
    max_duration_seconds: Optional[int] = None
    allow_nested_sidequests: bool = False

    @property
    def is_multi_step(self) -> bool:
        """Check if this is a multi-step sidequest.

        A sidequest is multi-step if:
        - It has multiple steps defined, OR
        - It has steps defined and no legacy station_id
        """
        return len(self.steps) > 1 or (len(self.steps) == 1 and self.station_id is None)

    def to_steps(self) -> List[SidequestStep]:
        """Get steps, converting legacy single-station format if needed.

        For backwards compatibility, if only station_id is set,
        we convert it to a single-step list.

        Returns:
            List of SidequestStep objects.
        """
        if self.steps:
            return self.steps
        elif self.station_id:
            # Backwards compatibility: convert to single-step
            return [
                SidequestStep(
                    template_id=self.station_id,
                    objective_override=self.objective_template,
                )
            ]
        return []

    def get_station_id(self) -> Optional[str]:
        """Get the primary station ID (first step's template_id).

        For single-station sidequests, returns station_id.
        For multi-step, returns first step's template_id.
        """
        if self.station_id:
            return self.station_id
        steps = self.to_steps()
        if steps:
            return steps[0].template_id
        return None


# =============================================================================
# Default Sidequests (Built-in)
# =============================================================================

DEFAULT_SIDEQUESTS: List[Dict[str, Any]] = [
    {
        "sidequest_id": "clarifier",
        "name": "Clarifier",
        "description": "Resolve ambiguity or missing requirements by asking clarifying questions",
        "station_id": "clarifier",
        "objective_template": "Clarify the following ambiguity: {{issue}}. Document assumptions and questions.",
        "triggers": [
            {
                "condition_type": "field_check",
                "field": "has_ambiguity",
                "operator": "equals",
                "value": True,
            },
            {"condition_type": "stall", "field": "stall_count", "operator": "gte", "value": 2},
        ],
        "trigger_mode": "any",
        "priority": 70,
        "cost_hint": "low",
        "tags": ["requirements", "ambiguity"],
    },
    {
        "sidequest_id": "env-doctor",
        "name": "Environment Doctor",
        "description": "Diagnose and fix environment/build issues that are causing test failures",
        "station_id": "fixer",
        "objective_template": "Diagnose environment issue: {{error_signature}}. Check dependencies, configs, and paths.",
        "triggers": [
            {
                "condition_type": "field_check",
                "field": "failure_type",
                "operator": "equals",
                "value": "environment",
            },
            {
                "condition_type": "field_check",
                "field": "error_category",
                "operator": "contains",
                "value": "import",
            },
            {
                "condition_type": "field_check",
                "field": "error_category",
                "operator": "contains",
                "value": "module",
            },
        ],
        "trigger_mode": "any",
        "priority": 80,
        "cost_hint": "medium",
        "tags": ["environment", "build", "dependencies"],
    },
    {
        "sidequest_id": "test-triage",
        "name": "Test Triage",
        "description": "Analyze failing tests to determine root cause and fix strategy",
        "station_id": "test-critic",
        "objective_template": "Triage test failures: {{failure_summary}}. Identify root cause and recommend fixes.",
        "triggers": [
            {
                "condition_type": "field_check",
                "field": "verification_passed",
                "operator": "equals",
                "value": False,
            },
            {
                "condition_type": "stall",
                "field": "same_failure_signature",
                "operator": "equals",
                "value": True,
            },
        ],
        "trigger_mode": "all",
        "priority": 60,
        "cost_hint": "medium",
        "tags": ["testing", "triage"],
    },
    {
        "sidequest_id": "security-audit",
        "name": "Security Audit",
        "description": "Review security implications of changes touching sensitive paths",
        "station_id": "security-scanner",
        "objective_template": "Audit security of changes to: {{sensitive_paths}}. Check for vulnerabilities.",
        "triggers": [
            {"condition_type": "path_pattern", "pattern": "auth/**"},
            {"condition_type": "path_pattern", "pattern": "security/**"},
            {"condition_type": "path_pattern", "pattern": "**/credentials*"},
            {"condition_type": "path_pattern", "pattern": "**/secret*"},
        ],
        "trigger_mode": "any",
        "priority": 90,
        "cost_hint": "high",
        "max_uses_per_run": 1,
        "tags": ["security", "audit"],
    },
    {
        "sidequest_id": "contract-check",
        "name": "Contract Check",
        "description": "Verify API/interface contracts when schema or interface changes detected",
        "station_id": "contract-enforcer",
        "objective_template": "Verify contracts for: {{changed_interfaces}}. Check backwards compatibility.",
        "triggers": [
            {"condition_type": "path_pattern", "pattern": "**/api/**"},
            {"condition_type": "path_pattern", "pattern": "**/schema*"},
            {"condition_type": "path_pattern", "pattern": "**/interface*"},
            {"condition_type": "path_pattern", "pattern": "**/*.proto"},
            {"condition_type": "path_pattern", "pattern": "**/openapi*"},
        ],
        "trigger_mode": "any",
        "priority": 75,
        "cost_hint": "medium",
        "tags": ["contracts", "api", "schema"],
    },
    {
        "sidequest_id": "context-refresh",
        "name": "Context Refresh",
        "description": "Reload context when stalled due to missing information",
        "station_id": "context-loader",
        "objective_template": "Refresh context for: {{current_task}}. Load additional files: {{suggested_paths}}.",
        "triggers": [
            {"condition_type": "stall", "field": "stall_count", "operator": "gte", "value": 3},
            {
                "condition_type": "field_check",
                "field": "context_insufficient",
                "operator": "equals",
                "value": True,
            },
        ],
        "trigger_mode": "any",
        "priority": 55,
        "cost_hint": "low",
        "tags": ["context", "refresh"],
    },
]


# =============================================================================
# Trigger Evaluation (Traditional Tooling)
# =============================================================================


def evaluate_trigger(
    trigger: TriggerCondition,
    context: Dict[str, Any],
) -> bool:
    """Evaluate a single trigger condition against context.

    This is pure traditional tooling - no LLM needed.

    Args:
        trigger: The trigger condition to evaluate.
        context: Context dictionary with field values.

    Returns:
        True if trigger condition is met.
    """
    if trigger.condition_type == "field_check":
        if trigger.field is None:
            return False

        value = context.get(trigger.field)
        expected = trigger.value

        if trigger.operator == "equals":
            return value == expected
        elif trigger.operator == "not_equals":
            return value != expected
        elif trigger.operator == "gt":
            return value is not None and value > expected
        elif trigger.operator == "lt":
            return value is not None and value < expected
        elif trigger.operator == "gte":
            return value is not None and value >= expected
        elif trigger.operator == "lte":
            return value is not None and value <= expected
        elif trigger.operator == "contains":
            return expected in str(value) if value else False
        else:
            return False

    elif trigger.condition_type == "stall":
        stall_signals = context.get("stall_signals", {})
        if trigger.field == "stall_count":
            count = stall_signals.get("stall_count", 0)
            return evaluate_trigger(
                TriggerCondition(
                    condition_type="field_check",
                    field="stall_count",
                    operator=trigger.operator,
                    value=trigger.value,
                ),
                {"stall_count": count},
            )
        elif trigger.field == "same_failure_signature":
            return stall_signals.get("same_failure_signature", False) == trigger.value
        elif trigger.field == "is_stalled":
            return stall_signals.get("is_stalled", False)
        return False

    elif trigger.condition_type == "path_pattern":
        import fnmatch

        changed_paths = context.get("changed_paths", [])
        pattern = trigger.pattern or ""
        for path in changed_paths:
            if fnmatch.fnmatch(path, pattern):
                return True
        return False

    elif trigger.condition_type == "iteration_count":
        iteration = context.get("iteration", 1)
        threshold = trigger.value or 5
        if trigger.operator == "gte":
            return iteration >= threshold
        elif trigger.operator == "gt":
            return iteration > threshold
        return False

    return False


# =============================================================================
# Parsing Helpers
# =============================================================================


def _parse_return_behavior(data: Any) -> ReturnBehavior:
    """Parse return behavior from string or dict.

    Supports both v1 (string) and v2 (dict) formats.
    """
    if isinstance(data, ReturnBehavior):
        return data
    if isinstance(data, str):
        # v1 format: simple string
        return ReturnBehavior(mode=data)
    if isinstance(data, dict):
        # v2 format: full dict
        return ReturnBehavior(
            mode=data.get("mode", "resume"),
            target_node=data.get("target_node"),
            condition=data.get("condition"),
            on_condition_true=data.get("on_condition_true"),
            on_condition_false=data.get("on_condition_false"),
            pass_artifacts=data.get("pass_artifacts", []),
        )
    return ReturnBehavior(mode="resume")


def _parse_sidequest_step(data: Dict[str, Any]) -> SidequestStep:
    """Parse a SidequestStep from dict format."""
    return SidequestStep(
        template_id=data["template_id"],
        step_id=data.get("step_id"),
        objective_override=data.get("objective_override"),
        params=data.get("params", {}),
        inputs_from=data.get("inputs_from", []),
        outputs_to=data.get("outputs_to", []),
        on_verified=data.get("on_verified", "next"),
        on_unverified=data.get("on_unverified", "next"),
        on_blocked=data.get("on_blocked", "halt"),
        max_turns=data.get("max_turns"),
        model_tier=data.get("model_tier"),
    )


def parse_sidequest_definition(sq_data: Dict[str, Any]) -> SidequestDefinition:
    """Parse a SidequestDefinition from dict format.

    Supports both v1 (single station) and v2 (multi-step) formats.
    """
    # Parse triggers
    triggers = [TriggerCondition(**t) for t in sq_data.get("triggers", [])]

    # Parse steps if present (v2 format)
    steps = []
    if "steps" in sq_data:
        steps = [_parse_sidequest_step(s) for s in sq_data["steps"]]

    # Parse return behavior
    return_behavior = _parse_return_behavior(sq_data.get("return_behavior", "resume"))

    return SidequestDefinition(
        sidequest_id=sq_data["sidequest_id"],
        name=sq_data["name"],
        description=sq_data["description"],
        steps=steps,
        station_id=sq_data.get("station_id"),
        objective_template=sq_data.get("objective_template"),
        triggers=triggers,
        trigger_mode=sq_data.get("trigger_mode", "any"),
        priority=sq_data.get("priority", 50),
        cost_hint=sq_data.get("cost_hint", "low"),
        max_uses_per_run=sq_data.get("max_uses_per_run", 3),
        return_behavior=return_behavior,
        tags=sq_data.get("tags", []),
        max_duration_seconds=sq_data.get("max_duration_seconds"),
        allow_nested_sidequests=sq_data.get("allow_nested_sidequests", False),
    )


# =============================================================================
# Sidequest Catalog
# =============================================================================


class SidequestCatalog:
    """Catalog of available sidequests for navigation.

    The catalog provides a bounded menu of sidequest options. The Navigator
    selects from this menu based on context signals.
    """

    def __init__(self, sidequests: Optional[List[SidequestDefinition]] = None):
        """Initialize catalog.

        Args:
            sidequests: List of sidequest definitions. If None, uses defaults.
        """
        self._sidequests: Dict[str, SidequestDefinition] = {}
        self._usage_counts: Dict[str, int] = {}  # Track usage per run

        if sidequests:
            for sq in sidequests:
                self._sidequests[sq.sidequest_id] = sq
        else:
            self._load_defaults()

    def _load_defaults(self) -> None:
        """Load default sidequests."""
        for sq_data in DEFAULT_SIDEQUESTS:
            sq = parse_sidequest_definition(sq_data)
            self._sidequests[sq.sidequest_id] = sq

    def get_all(self) -> List[SidequestDefinition]:
        """Get all sidequests in the catalog."""
        return list(self._sidequests.values())

    def get_by_id(self, sidequest_id: str) -> Optional[SidequestDefinition]:
        """Get sidequest by ID."""
        return self._sidequests.get(sidequest_id)

    def get_by_tags(self, tags: List[str]) -> List[SidequestDefinition]:
        """Get sidequests matching any of the given tags."""
        result = []
        for sq in self._sidequests.values():
            if any(tag in sq.tags for tag in tags):
                result.append(sq)
        return sorted(result, key=lambda s: -s.priority)

    def get_applicable_sidequests(
        self,
        context: Dict[str, Any],
        run_id: Optional[str] = None,
    ) -> List[SidequestDefinition]:
        """Get sidequests whose triggers match the current context.

        This is pure traditional evaluation - no LLM needed.

        Args:
            context: Context dictionary for trigger evaluation.
            run_id: Optional run ID for usage tracking.

        Returns:
            List of applicable sidequests, sorted by priority.
        """
        applicable = []

        for sq in self._sidequests.values():
            # Check usage limit
            usage_key = f"{run_id}:{sq.sidequest_id}" if run_id else sq.sidequest_id
            current_usage = self._usage_counts.get(usage_key, 0)
            if current_usage >= sq.max_uses_per_run:
                continue

            # Evaluate triggers
            if sq.trigger_mode == "all":
                # All triggers must match
                if all(evaluate_trigger(t, context) for t in sq.triggers):
                    applicable.append(sq)
            else:  # "any"
                # Any trigger must match
                if any(evaluate_trigger(t, context) for t in sq.triggers):
                    applicable.append(sq)

        # Sort by priority (higher first)
        return sorted(applicable, key=lambda s: -s.priority)

    def record_usage(self, sidequest_id: str, run_id: Optional[str] = None) -> None:
        """Record usage of a sidequest."""
        usage_key = f"{run_id}:{sidequest_id}" if run_id else sidequest_id
        self._usage_counts[usage_key] = self._usage_counts.get(usage_key, 0) + 1

    def reset_usage(self, run_id: Optional[str] = None) -> None:
        """Reset usage counts for a run."""
        if run_id:
            keys_to_remove = [k for k in self._usage_counts if k.startswith(f"{run_id}:")]
            for key in keys_to_remove:
                del self._usage_counts[key]
        else:
            self._usage_counts.clear()

    def add_sidequest(self, sidequest: SidequestDefinition) -> None:
        """Add a sidequest to the catalog."""
        self._sidequests[sidequest.sidequest_id] = sidequest

    def remove_sidequest(self, sidequest_id: str) -> bool:
        """Remove a sidequest from the catalog."""
        if sidequest_id in self._sidequests:
            del self._sidequests[sidequest_id]
            return True
        return False


# =============================================================================
# Loading
# =============================================================================


def load_default_catalog() -> SidequestCatalog:
    """Load the default sidequest catalog."""
    return SidequestCatalog()


def load_catalog_from_file(path: Path) -> SidequestCatalog:
    """Load sidequest catalog from a JSON/YAML file.

    Args:
        path: Path to the catalog file.

    Returns:
        Loaded SidequestCatalog.
    """
    if not path.exists():
        logger.warning("Sidequest catalog file not found: %s", path)
        return load_default_catalog()

    try:
        with open(path, "r") as f:
            if path.suffix in (".yaml", ".yml"):
                import yaml

                data = yaml.safe_load(f)
            else:
                data = json.load(f)

        sidequests = []
        for sq_data in data.get("sidequests", []):
            sq = parse_sidequest_definition(sq_data)
            sidequests.append(sq)

        return SidequestCatalog(sidequests)

    except Exception as e:
        logger.error("Failed to load sidequest catalog from %s: %s", path, e)
        return load_default_catalog()


# =============================================================================
# Sidequest to Navigator Integration
# =============================================================================


def sidequests_to_navigator_options(
    sidequests: List[SidequestDefinition],
) -> List[Dict[str, Any]]:
    """Convert sidequests to Navigator-compatible options.

    This is used to provide the Navigator with a bounded menu of
    sidequest options. For multi-step sidequests, uses the first step's
    template as the station_template.
    """
    from .navigator import SidequestOption

    options = []
    for sq in sidequests:
        # Get the primary station ID (first step for multi-step)
        station_id = sq.get_station_id()
        # Get objective template from first step if multi-step
        objective = sq.objective_template
        if sq.is_multi_step and sq.steps:
            objective = sq.steps[0].objective_override or objective

        options.append(
            SidequestOption(
                sidequest_id=sq.sidequest_id,
                station_template=station_id,
                trigger_description=sq.description,
                objective_template=objective,
                priority=sq.priority,
                cost_hint=sq.cost_hint,
            )
        )
    return options
