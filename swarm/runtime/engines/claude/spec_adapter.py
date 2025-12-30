"""
spec_adapter.py - Adapter to use StationSpecs with ClaudeStepEngine.

This module provides the bridge between the spec-first architecture
and the existing engine infrastructure. It compiles StationSpecs and
FlowSpecs into the format expected by the engine.

Usage:
    from swarm.runtime.engines.claude.spec_adapter import SpecAdapter

    adapter = SpecAdapter(repo_root)
    plan = adapter.compile_step(ctx, flow_id)

    # Use plan.system_append and plan.user_prompt with the engine
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Optional, Tuple

from swarm.config.flow_registry import get_flow_spec_id
from swarm.spec.compiler import SpecCompiler
from swarm.spec.loader import list_flows, list_stations
from swarm.spec.types import PromptPlan

if TYPE_CHECKING:
    from swarm.runtime.engines.models import StepContext

logger = logging.getLogger(__name__)


class SpecAdapter:
    """Adapter that compiles specs for engine consumption.

    This adapter:
    1. Maps flow_key (e.g., "build") to flow_id (e.g., "3-build") using
       the canonical get_flow_spec_id() from flow_registry
    2. Compiles PromptPlan from specs
    3. Provides SDK options for engine configuration
    4. Falls back to legacy prompt_builder if spec not found

    Usage:
        adapter = SpecAdapter(repo_root)

        # Check if spec-based execution is available
        if adapter.has_spec(flow_key, step_id):
            plan = adapter.compile_step(ctx, flow_id)
            # Use plan for execution
        else:
            # Fall back to legacy
    """

    def __init__(self, repo_root: Optional[Path] = None):
        """Initialize the spec adapter.

        Args:
            repo_root: Repository root path.
        """
        self.repo_root = repo_root
        self._compiler = SpecCompiler(repo_root)
        self._available_flows: Optional[set] = None
        self._available_stations: Optional[set] = None

    def _load_available(self) -> None:
        """Load available flows and stations."""
        if self._available_flows is None:
            self._available_flows = set(list_flows(self.repo_root))
        if self._available_stations is None:
            self._available_stations = set(list_stations(self.repo_root))

    def has_flow_spec(self, flow_key: str) -> bool:
        """Check if a flow spec exists.

        Args:
            flow_key: Flow key (e.g., "build").

        Returns:
            True if flow spec exists.
        """
        self._load_available()
        flow_id = get_flow_spec_id(flow_key)
        # get_flow_spec_id returns the key unchanged if not found
        if flow_id == flow_key:
            return False
        return flow_id in self._available_flows

    def has_station_spec(self, station_id: str) -> bool:
        """Check if a station spec exists.

        Args:
            station_id: Station identifier.

        Returns:
            True if station spec exists.
        """
        self._load_available()
        return station_id in self._available_stations

    def get_flow_id(self, flow_key: str) -> Optional[str]:
        """Map flow_key to flow_id.

        Uses the canonical get_flow_spec_id() from flow_registry.

        Args:
            flow_key: Flow key (e.g., "build").

        Returns:
            Flow ID (e.g., "3-build") or None if not found.
        """
        flow_id = get_flow_spec_id(flow_key)
        # get_flow_spec_id returns the key unchanged if not found
        if flow_id == flow_key:
            return None
        return flow_id

    def compile_step(
        self,
        ctx: "StepContext",
        flow_key: Optional[str] = None,
    ) -> Optional[PromptPlan]:
        """Compile a PromptPlan for a step.

        Args:
            ctx: Step execution context.
            flow_key: Flow key. If None, uses ctx.flow_key.

        Returns:
            Compiled PromptPlan, or None if spec not found.
        """
        effective_flow_key = flow_key or ctx.flow_key
        flow_id = self.get_flow_id(effective_flow_key)

        if not flow_id:
            logger.debug("No flow_id mapping for flow_key: %s", effective_flow_key)
            return None

        if not self.has_flow_spec(effective_flow_key):
            logger.debug("Flow spec not found: %s", flow_id)
            return None

        # Get context pack from ctx.extra
        context_pack = ctx.extra.get("context_pack") if ctx.extra else None

        try:
            plan = self._compiler.compile(
                flow_id=flow_id,
                step_id=ctx.step_id,
                context_pack=context_pack,
                run_base=ctx.run_base,
                cwd=str(ctx.repo_root) if ctx.repo_root else None,
            )
            logger.debug(
                "Compiled PromptPlan for %s/%s (hash=%s, station=%s v%d)",
                flow_id,
                ctx.step_id,
                plan.prompt_hash,
                plan.station_id,
                plan.station_version,
            )
            return plan

        except FileNotFoundError as e:
            logger.warning("Spec not found for %s/%s: %s", flow_id, ctx.step_id, e)
            return None
        except ValueError as e:
            logger.warning("Invalid spec for %s/%s: %s", flow_id, ctx.step_id, e)
            return None

    def get_sdk_options_from_plan(self, plan: PromptPlan) -> Dict[str, Any]:
        """Extract SDK options from a PromptPlan.

        Returns a dict suitable for creating ClaudeAgentOptions.

        Args:
            plan: Compiled PromptPlan.

        Returns:
            Dict with SDK option fields.
        """
        return {
            "cwd": plan.cwd,
            "permission_mode": plan.permission_mode,
            "allowed_tools": list(plan.allowed_tools),
            "max_turns": plan.max_turns,
            "sandbox_enabled": plan.sandbox_enabled,
            "model": plan.model,
        }

    def build_prompt_from_plan(self, plan: PromptPlan) -> Tuple[str, Optional[str]]:
        """Build prompt tuple from PromptPlan.

        Returns (user_prompt, system_append) suitable for engine use.

        Args:
            plan: Compiled PromptPlan.

        Returns:
            Tuple of (user_prompt, system_append).
        """
        return plan.user_prompt, plan.system_append


# =============================================================================
# Integration with Engine
# =============================================================================


def try_compile_from_spec(
    ctx: "StepContext",
    repo_root: Optional[Path] = None,
) -> Optional[Tuple[str, Optional[str], PromptPlan]]:
    """Try to compile prompt from spec, return None if not available.

    This is the main integration point for the engine. It attempts
    spec-based prompt compilation and returns None if specs are not
    available for this flow/step.

    Args:
        ctx: Step execution context.
        repo_root: Repository root.

    Returns:
        Tuple of (user_prompt, system_append, PromptPlan) or None.
    """
    adapter = SpecAdapter(repo_root)
    plan = adapter.compile_step(ctx)

    if plan:
        return plan.user_prompt, plan.system_append, plan

    return None
