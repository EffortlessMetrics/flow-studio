#!/usr/bin/env python3
"""
Pydantic schema models for Flow Studio API.

This module defines type-safe response models for all FastAPI endpoints.
All models correspond to the data structures returned by FlowStudioCore
and RunInspector.

Usage:
    from swarm.flowstudio.schema import HealthStatus, FlowSummary, GraphPayload

    @app.get("/api/health", response_model=HealthStatus)
    async def api_health():
        return HealthStatus(status="healthy", ...)
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


# =============================================================================
# Health & System Status
# =============================================================================


class SystemStatus(str, Enum):
    """Overall system health status."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


class Capabilities(BaseModel):
    """System capabilities available."""
    runs: bool = Field(description="Run inspector available for artifact tracking")
    timeline: bool = Field(description="Timeline feature available")
    governance: bool = Field(description="Governance status provider available")
    validation: bool = Field(description="Validation data available")


class SelftestSummary(BaseModel):
    """Summary of selftest status."""
    mode: str = Field(description="Selftest mode (strict, degraded, kernel-only)")
    status: str = Field(description="Overall status (GREEN, YELLOW, RED)")
    kernel_ok: bool = Field(description="All kernel checks passed")
    governance_ok: bool = Field(description="All governance checks passed")
    optional_ok: bool = Field(description="All optional checks passed")
    failed_steps: List[str] = Field(default_factory=list, description="List of failed step IDs")


class HealthStatus(BaseModel):
    """Response model for /api/health endpoint."""
    status: str = Field(description="Overall health status (ok, degraded, error)")
    version: str = Field(description="Flow Studio version")
    timestamp: str = Field(description="ISO 8601 timestamp of health check")
    flows: int = Field(description="Number of flows loaded")
    agents: int = Field(description="Number of agents loaded")
    selftest_status: Optional[SelftestSummary] = Field(None, description="Selftest status if available")
    capabilities: Capabilities = Field(description="Available system capabilities")


# =============================================================================
# Flows
# =============================================================================


class FlowSummary(BaseModel):
    """Summary of a single flow for list view."""
    key: str = Field(description="Unique flow identifier (e.g., 'signal', 'build')")
    title: str = Field(description="Human-readable flow title")
    description: str = Field(description="Brief description of flow purpose")
    step_count: int = Field(description="Number of steps in the flow")


class FlowsListResponse(BaseModel):
    """Response model for /api/flows endpoint."""
    flows: List[FlowSummary] = Field(description="List of available flows")


class StepInfo(BaseModel):
    """Information about a single step in a flow."""
    id: str = Field(description="Unique step identifier within flow")
    title: str = Field(description="Human-readable step title")
    role: str = Field(description="Step role or description")
    agents: List[str] = Field(description="List of agent keys assigned to this step")


class AgentInfo(BaseModel):
    """Information about a single agent."""
    key: str = Field(description="Unique agent identifier")
    category: str = Field(description="Agent category (e.g., implementation, critic, verification)")
    color: str = Field(description="Visual color code for agent's role family")
    model: str = Field(description="Model assignment (inherit, haiku, sonnet, opus)")
    short_role: str = Field(description="Brief description of agent's responsibility")


class FlowDetail(BaseModel):
    """Detailed flow information with steps and agents."""
    flow: Dict[str, str] = Field(description="Flow metadata (key, title, description)")
    steps: List[StepInfo] = Field(description="List of steps in execution order")
    agents: Dict[str, AgentInfo] = Field(description="Dictionary of agents used by this flow")


# =============================================================================
# Graph Visualization
# =============================================================================


class GraphNode(BaseModel):
    """Single node in flow graph."""
    data: Dict[str, Any] = Field(description="Node data including id, label, type, and attributes")


class GraphEdge(BaseModel):
    """Single edge in flow graph."""
    data: Dict[str, Any] = Field(description="Edge data including id, source, target, and type")


class GraphPayload(BaseModel):
    """Graph data for visualization (nodes and edges)."""
    nodes: List[GraphNode] = Field(description="List of graph nodes (steps, agents, artifacts)")
    edges: List[GraphEdge] = Field(description="List of graph edges (connections)")


# =============================================================================
# Runs & Artifacts
# =============================================================================


class RunInfo(BaseModel):
    """Summary information about a run."""
    run_id: str = Field(description="Unique run identifier")
    run_type: str = Field(description="Type of run (active or example)")
    path: str = Field(description="File system path to run directory")
    title: Optional[str] = Field(None, description="Run title from metadata if available")
    description: Optional[str] = Field(None, description="Run description from metadata")
    tags: List[str] = Field(default_factory=list, description="Tags from metadata")


class RunsListResponse(BaseModel):
    """Response model for /api/runs endpoint."""
    runs: List[RunInfo] = Field(description="List of available runs")
    total: int = Field(description="Total number of runs available")
    limit: int = Field(description="Maximum runs returned in this response")
    offset: int = Field(description="Number of runs skipped from the beginning")
    has_more: bool = Field(description="Whether more runs are available beyond this page")


class ArtifactStatus(str, Enum):
    """Status of a single artifact."""
    PRESENT = "present"
    MISSING = "missing"
    UNKNOWN = "unknown"


class ArtifactInfo(BaseModel):
    """Information about a single artifact."""
    path: str = Field(description="Artifact file path relative to step directory")
    status: str = Field(description="Artifact status (present, missing, unknown)")
    required: bool = Field(description="Whether artifact is required or optional")


class StepStatusEnum(str, Enum):
    """Aggregate status of a step based on its artifacts."""
    COMPLETE = "complete"
    PARTIAL = "partial"
    MISSING = "missing"
    NOT_APPLICABLE = "n/a"


class StepStatusInfo(BaseModel):
    """Status information for a single step in a run."""
    status: str = Field(description="Step status (complete, partial, missing, n/a)")
    required_present: int = Field(description="Number of required artifacts present")
    required_total: int = Field(description="Total number of required artifacts")
    optional_present: int = Field(description="Number of optional artifacts present")
    optional_total: int = Field(description="Total number of optional artifacts")
    artifacts: List[ArtifactInfo] = Field(description="List of artifact statuses")
    note: Optional[str] = Field(None, description="Optional note about step status")


class FlowStatusEnum(str, Enum):
    """Aggregate status of a flow based on decision artifact."""
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    DONE = "done"


class FlowStatusInfo(BaseModel):
    """Status information for a single flow in a run."""
    flow_key: str = Field(description="Flow identifier")
    status: str = Field(description="Flow status (not_started, in_progress, done)")
    title: str = Field(description="Flow title")
    decision_artifact: Optional[str] = Field(None, description="Decision artifact filename if defined")
    decision_present: bool = Field(description="Whether decision artifact is present")
    steps: Dict[str, StepStatusInfo] = Field(description="Status for each step in flow")


class RunSummary(BaseModel):
    """Complete summary of a run with all flow and step statuses."""
    run_id: str = Field(description="Unique run identifier")
    run_type: str = Field(description="Type of run (active or example)")
    path: str = Field(description="File system path to run directory")
    flows: Dict[str, FlowStatusInfo] = Field(description="Status for each flow in run")


class SDLCBarSegment(BaseModel):
    """Single segment in SDLC progress bar."""
    flow: str = Field(description="Flow key")
    status: str = Field(description="Flow status (not_started, in_progress, done)")
    title: str = Field(description="Flow title for display")


class SDLCBarResponse(BaseModel):
    """Response model for /api/runs/{run_id}/sdlc endpoint."""
    run_id: str = Field(description="Run identifier")
    sdlc: List[SDLCBarSegment] = Field(description="SDLC progress bar segments")


# =============================================================================
# Timeline & Timing
# =============================================================================


class TimelineEvent(BaseModel):
    """Single event in run timeline."""
    timestamp: str = Field(description="ISO 8601 timestamp of event")
    flow: str = Field(description="Flow key")
    step: Optional[str] = Field(None, description="Step ID if applicable")
    status: str = Field(description="Event status (started, completed, failed)")
    duration_ms: Optional[int] = Field(None, description="Duration in milliseconds if completed")
    note: Optional[str] = Field(None, description="Additional event notes")


class TimelineResponse(BaseModel):
    """Response model for /api/runs/{run_id}/timeline endpoint."""
    run_id: str = Field(description="Run identifier")
    events: List[TimelineEvent] = Field(description="Chronological list of events")


class StepTiming(BaseModel):
    """Timing information for a single step."""
    step_id: str = Field(description="Step identifier")
    started_at: Optional[str] = Field(None, description="ISO 8601 timestamp when step started")
    ended_at: Optional[str] = Field(None, description="ISO 8601 timestamp when step ended")
    duration_seconds: Optional[float] = Field(None, description="Step duration in seconds")


class FlowTiming(BaseModel):
    """Timing information for a flow."""
    flow_key: str = Field(description="Flow identifier")
    started_at: Optional[str] = Field(None, description="ISO 8601 timestamp when flow started")
    ended_at: Optional[str] = Field(None, description="ISO 8601 timestamp when flow ended")
    duration_seconds: Optional[float] = Field(None, description="Flow duration in seconds")
    steps: List[StepTiming] = Field(default_factory=list, description="Timing for each step")


class RunTiming(BaseModel):
    """Complete timing information for a run."""
    run_id: str = Field(description="Run identifier")
    started_at: Optional[str] = Field(None, description="ISO 8601 timestamp when run started")
    ended_at: Optional[str] = Field(None, description="ISO 8601 timestamp when run ended")
    total_duration_seconds: Optional[float] = Field(None, description="Total run duration in seconds")
    flows: Dict[str, FlowTiming] = Field(default_factory=dict, description="Timing for each flow")


class RunTimingResponse(BaseModel):
    """Response model for /api/runs/{run_id}/timing endpoint."""
    run_id: str = Field(description="Run identifier")
    timing: Optional[RunTiming] = Field(None, description="Timing data if available")
    message: Optional[str] = Field(None, description="Message if timing not available")


class FlowTimingResponse(BaseModel):
    """Response model for /api/runs/{run_id}/flows/{flow_key}/timing endpoint."""
    run_id: str = Field(description="Run identifier")
    flow_key: str = Field(description="Flow identifier")
    timing: Optional[FlowTiming] = Field(None, description="Flow timing data if available")
    message: Optional[str] = Field(None, description="Message if timing not available")


# =============================================================================
# Tours
# =============================================================================


class TourSummary(BaseModel):
    """Summary of a guided tour for list view."""
    id: str = Field(description="Unique tour identifier")
    title: str = Field(description="Tour title")
    description: str = Field(description="Tour description")
    step_count: int = Field(description="Number of steps in tour")


class ToursListResponse(BaseModel):
    """Response model for /api/tours endpoint."""
    tours: List[TourSummary] = Field(description="List of available tours")


class TourTarget(BaseModel):
    """Target specification for a tour step."""
    type: str = Field(description="Target type (flow, step, agent)")
    flow: str = Field(description="Flow key if applicable")
    step: str = Field(description="Step ID if applicable")


class TourStep(BaseModel):
    """Single step in a guided tour."""
    target: TourTarget = Field(description="What to highlight in UI")
    title: str = Field(description="Step title")
    text: str = Field(description="Step explanation text")
    action: str = Field(description="Action to perform (select_flow, highlight_step, etc.)")


class TourDetail(BaseModel):
    """Complete tour definition with all steps."""
    id: str = Field(description="Unique tour identifier")
    title: str = Field(description="Tour title")
    description: str = Field(description="Tour description")
    steps: List[TourStep] = Field(description="Tour steps in order")


# =============================================================================
# Validation & Governance
# =============================================================================


class ValidationData(BaseModel):
    """Validation data for governance overlays."""
    data: Optional[Dict[str, Any]] = Field(None, description="Validation data if available")
    error: Optional[str] = Field(None, description="Error message if validation unavailable")


class GovernanceStatus(BaseModel):
    """Governance status information."""
    kernel: Dict[str, Any] = Field(description="Kernel health status")
    selftest: Dict[str, Any] = Field(description="Selftest status")
    validation: Dict[str, Any] = Field(description="Validation results")
    state: str = Field(description="Overall state (HEALTHY, DEGRADED, BROKEN)")
    degradations: List[Dict[str, Any]] = Field(default_factory=list, description="Recent degradation entries")
    ac: Dict[str, str] = Field(default_factory=dict, description="AC (Acceptance Criteria) status aggregation")


class ValidationSnapshot(BaseModel):
    """Snapshot of validation/governance status."""
    timestamp: str = Field(description="ISO 8601 timestamp of snapshot")
    service: str = Field(description="Service name (flow-studio)")
    governance: GovernanceStatus = Field(description="Governance status details")
    flows: Dict[str, Any] = Field(description="Flow-level validation details")
    agents: Dict[str, Any] = Field(description="Agent-level validation details")
    hints: Dict[str, str] = Field(description="Remediation hints")


# =============================================================================
# Search
# =============================================================================


class SearchResultType(str, Enum):
    """Type of search result."""
    FLOW = "flow"
    STEP = "step"
    AGENT = "agent"
    ARTIFACT = "artifact"


class SearchResult(BaseModel):
    """Single search result."""
    type: str = Field(description="Result type (flow, step, agent, artifact)")
    id: Optional[str] = Field(None, description="Identifier for flow/step")
    key: Optional[str] = Field(None, description="Agent key if agent result")
    flow: Optional[str] = Field(None, description="Flow key if step/artifact result")
    step: Optional[str] = Field(None, description="Step ID if artifact result")
    file: Optional[str] = Field(None, description="Filename if artifact result")
    label: str = Field(description="Display label for result")
    flows: List[str] = Field(default_factory=list, description="Associated flows if agent result")
    match: str = Field(description="Matching query string")


class SearchResponse(BaseModel):
    """Response model for /api/search endpoint."""
    results: List[SearchResult] = Field(description="List of search results (max 8)")
    query: str = Field(description="Original query string")


# =============================================================================
# Agents
# =============================================================================


class AgentUsageInfo(BaseModel):
    """Usage information for an agent in a specific flow/step."""
    flow: str = Field(description="Flow key")
    flow_title: str = Field(description="Flow title")
    step: str = Field(description="Step ID")
    step_title: str = Field(description="Step title")


class AgentUsageResponse(BaseModel):
    """Response model for /api/agents/{agent_key}/usage endpoint."""
    agent: str = Field(description="Agent key")
    usage: List[AgentUsageInfo] = Field(description="List of flows/steps where agent is used")


class AgentsListResponse(BaseModel):
    """Response model for /api/agents endpoint."""
    agents: List[AgentInfo] = Field(description="List of all agents")


# =============================================================================
# Reload & Control
# =============================================================================


class ReloadResponse(BaseModel):
    """Response model for /api/reload endpoint."""
    status: str = Field(description="Reload status (ok or error)")
    flows: int = Field(description="Number of flows loaded")
    agents: int = Field(description="Number of agents loaded")


# =============================================================================
# Selftest
# =============================================================================


class SelftestStepInfo(BaseModel):
    """Information about a selftest step."""
    id: str = Field(description="Step identifier (e.g., 'core-checks')")
    tier: str = Field(description="Tier: kernel, governance, optional")
    severity: str = Field(description="Severity: critical, warning, info")
    category: str = Field(description="Category: correctness, governance")
    description: str = Field(description="Human-readable description")
    ac_ids: List[str] = Field(default_factory=list, description="Related acceptance criteria IDs")
    depends_on: List[str] = Field(default_factory=list, description="Dependencies (step IDs)")


class SelftestPlanResponse(BaseModel):
    """Response model for /api/selftest/plan endpoint."""
    version: str = Field(description="Selftest schema version")
    steps: List[SelftestStepInfo] = Field(description="All selftest steps")
    summary: Dict[str, Any] = Field(description="Summary with total and by_tier counts")


# =============================================================================
# Error Responses
# =============================================================================


class ErrorResponse(BaseModel):
    """Standard error response."""
    error: str = Field(description="Error message")
    available_flows: Optional[List[str]] = Field(None, description="Available flows if flow not found")
    available_tours: Optional[List[str]] = Field(None, description="Available tours if tour not found")
    hint: Optional[str] = Field(None, description="Hint for resolving error")


# =============================================================================
# RunService Types
# =============================================================================


class RunSpecModel(BaseModel):
    """API model for run specification."""
    flow_keys: List[str] = Field(description="List of flow keys to execute")
    profile_id: Optional[str] = Field(None, description="Profile ID to use for the run")
    backend: Literal["claude-harness", "claude-agent-sdk", "gemini-cli", "custom-cli"] = Field(
        default="claude-harness", description="Backend to use for execution"
    )
    initiator: str = Field(default="flow-studio", description="Who initiated the run")
    params: Dict[str, Any] = Field(default_factory=dict, description="Additional parameters for the run")


class RunStatusEnum(str, Enum):
    """Status of a run."""
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"


class SDLCStatusEnum(str, Enum):
    """SDLC health status for a run."""
    OK = "ok"
    WARNING = "warning"
    ERROR = "error"
    UNKNOWN = "unknown"


class RunSummaryModel(BaseModel):
    """API model for run summary."""
    id: str = Field(description="Unique run identifier")
    spec: RunSpecModel = Field(description="Run specification")
    status: RunStatusEnum = Field(description="Current run status")
    sdlc_status: SDLCStatusEnum = Field(description="SDLC health status")
    created_at: str = Field(description="ISO 8601 timestamp when run was created")
    updated_at: str = Field(description="ISO 8601 timestamp when run was last updated")
    started_at: Optional[str] = Field(None, description="ISO 8601 timestamp when run started")
    completed_at: Optional[str] = Field(None, description="ISO 8601 timestamp when run completed")
    error: Optional[str] = Field(None, description="Error message if run failed")
    artifacts: Dict[str, Any] = Field(default_factory=dict, description="Artifacts produced by the run")
    is_exemplar: bool = Field(default=False, description="Whether this is an exemplar run")
    tags: List[str] = Field(default_factory=list, description="Tags for the run")


class RunEventModel(BaseModel):
    """API model for run event."""
    run_id: str = Field(description="Run identifier this event belongs to")
    ts: str = Field(description="ISO 8601 timestamp of the event")
    kind: str = Field(description="Event kind (e.g., 'step_started', 'step_completed')")
    flow_key: str = Field(description="Flow key this event relates to")
    step_id: Optional[str] = Field(None, description="Step ID if applicable")
    agent_key: Optional[str] = Field(None, description="Agent key if applicable")
    payload: Dict[str, Any] = Field(default_factory=dict, description="Event-specific payload data")


class BackendCapabilitiesModel(BaseModel):
    """API model for backend capabilities."""
    id: str = Field(description="Backend identifier")
    label: str = Field(description="Human-readable backend label")
    supports_streaming: bool = Field(default=False, description="Whether backend supports streaming output")
    supports_events: bool = Field(default=True, description="Whether backend emits events")
    supports_cancel: bool = Field(default=False, description="Whether backend supports run cancellation")
    supports_replay: bool = Field(default=False, description="Whether backend supports replay")


class BackendsListResponse(BaseModel):
    """Response for GET /api/backends."""
    backends: List[BackendCapabilitiesModel] = Field(description="List of available backends")


class StartRunRequest(BaseModel):
    """Request body for POST /api/run."""
    flows: List[str] = Field(description="List of flow keys to execute")
    profile_id: Optional[str] = Field(None, description="Profile ID to use")
    backend: str = Field(default="claude-harness", description="Backend to use for execution")


class StartRunResponse(BaseModel):
    """Response for POST /api/run."""
    run_id: str = Field(description="Unique identifier for the started run")
    status: str = Field(description="Initial run status")
    message: str = Field(description="Human-readable status message")


class RunEventsResponse(BaseModel):
    """Response for GET /api/runs/{run_id}/events."""
    run_id: str = Field(description="Run identifier")
    events: List[RunEventModel] = Field(description="List of events for the run")


# =============================================================================
# Model Policy
# =============================================================================


class ModelPolicyRequest(BaseModel):
    """Request parameters for model policy preview."""
    category: str = Field(description="Station category (e.g., implementation, critic, shaping)")
    model: str = Field(description="Model value to resolve (e.g., inherit, haiku, sonnet, opus)")


class EffectiveModel(BaseModel):
    """Resolved effective model information."""
    tier: str = Field(description="Resolved tier alias (haiku, sonnet, opus)")
    model_id: str = Field(description="Full model ID for context budget computation")


class ModelPolicyPreviewResponse(BaseModel):
    """Response for GET /api/model-policy/preview endpoint."""
    requested: ModelPolicyRequest = Field(description="The original request parameters")
    effective: EffectiveModel = Field(description="The resolved effective model")
    resolution_chain: List[str] = Field(
        description="Chain of resolution steps (e.g., ['inherit -> category', 'category -> group', 'group -> tier'])"
    )


class CategoryAssignment(BaseModel):
    """Model assignment for a station category."""
    tier_name: str = Field(description="Tier name from policy (economy, standard, primary, elite, edge)")
    tier_alias: str = Field(description="Resolved tier alias (haiku, sonnet, opus)")
    model_id: str = Field(description="Full model ID for context budget computation")


class ModelPolicyMatrixResponse(BaseModel):
    """Response for GET /api/model-policy/matrix endpoint."""
    user_primary: str = Field(description="User's configured primary model (sonnet or opus)")
    tiers: Dict[str, str] = Field(
        description="Tier definitions mapping tier names to aliases (e.g., {'economy': 'haiku'})"
    )
    assignments: Dict[str, CategoryAssignment] = Field(
        description="Model assignments per station category"
    )


# =============================================================================
# Station Spec Compilation Preview
# =============================================================================


class CompilePreviewRequest(BaseModel):
    """Request body for POST /api/station/compile-preview."""
    flow_id: str = Field(description="Flow identifier (e.g., '3-build')")
    step_id: str = Field(description="Step identifier within the flow (e.g., '3.3')")
    station_id: str = Field(description="Station identifier (e.g., 'code-implementer')")
    run_id: Optional[str] = Field(None, description="Optional run ID for context resolution")


class SdkOptionsModel(BaseModel):
    """SDK options for Claude execution."""
    model: str = Field(description="Full model ID")
    tools: List[str] = Field(description="Allowed tools list")
    permission_mode: str = Field(description="Permission mode (default, bypassPermissions, planMode)")
    max_turns: int = Field(description="Maximum conversation turns")
    sandbox_enabled: bool = Field(description="Whether sandbox mode is enabled")
    cwd: str = Field(description="Working directory")


class VerificationModel(BaseModel):
    """Verification requirements for a step."""
    required_artifacts: List[str] = Field(default_factory=list, description="Required artifact paths")
    verification_commands: List[str] = Field(default_factory=list, description="Verification commands to run")


class TraceabilityModel(BaseModel):
    """Traceability metadata for audit trail."""
    prompt_hash: str = Field(description="SHA-256 truncated hash of prompts")
    compiled_at: str = Field(description="ISO timestamp of compilation")
    compiler_version: str = Field(description="Compiler version")
    station_version: int = Field(description="Station spec version")
    flow_version: int = Field(description="Flow spec version")


class CompilePreviewResponse(BaseModel):
    """Response for POST /api/station/compile-preview."""
    flow_id: str = Field(description="Flow identifier")
    step_id: str = Field(description="Step identifier")
    station_id: str = Field(description="Station identifier")
    system_prompt: str = Field(description="Full compiled system prompt")
    user_prompt: str = Field(description="Full compiled user prompt")
    sdk_options: SdkOptionsModel = Field(description="SDK execution options")
    verification: VerificationModel = Field(description="Verification requirements")
    traceability: TraceabilityModel = Field(description="Traceability metadata")
