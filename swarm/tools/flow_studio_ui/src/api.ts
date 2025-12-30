// swarm/tools/flow_studio_ui/src/api.ts
// Centralized API client for Flow Studio

import type {
  RunsResponse,
  RunSummary,
  RunTimeline,
  RunEventsResponse,
  ComparisonData,
  FlowsResponse,
  FlowDetail,
  FlowGraph,
  FlowKey,
  SearchResponse,
  GovernanceStatus,
  ValidationData,
  ToursResponse,
  Tour,
  SelftestPlan,
  BackendsResponse,
  StepTranscriptResponse,
  StepReceiptResponse,
  WisdomSummary,
  BoundaryReviewResponse,
} from "./domain.js";

/**
 * Fetch JSON with error handling
 */
async function fetchJSON<T>(url: string, options?: RequestInit): Promise<T> {
  const resp = await fetch(url, options);
  if (!resp.ok) {
    throw new Error(`HTTP ${resp.status} for ${url}`);
  }
  return resp.json() as Promise<T>;
}

/**
 * API client with methods for all Flow Studio endpoints
 */
export const Api = {
  // ============================================================================
  // Runs
  // ============================================================================

  /**
   * Get list of available runs with pagination.
   * Optionally filter by flow key.
   *
   * @param options - Optional parameters for pagination and filtering
   * @param options.flowKey - Optional flow key to filter runs
   * @param options.limit - Maximum number of runs to return (default 100, max 500)
   * @param options.offset - Number of runs to skip from the beginning (default 0)
   */
  getRuns(options?: {
    flowKey?: string;
    limit?: number;
    offset?: number;
  }): Promise<RunsResponse> {
    const params = new URLSearchParams();
    if (options?.flowKey) {
      params.set("flow", options.flowKey);
    }
    if (options?.limit !== undefined) {
      params.set("limit", String(options.limit));
    }
    if (options?.offset !== undefined) {
      params.set("offset", String(options.offset));
    }
    const queryString = params.toString();
    return fetchJSON<RunsResponse>(`/api/runs${queryString ? `?${queryString}` : ""}`);
  },

  /**
   * Get list of exemplar runs (curated examples).
   * These are runs marked as reference implementations.
   */
  listExemplars(): Promise<RunsResponse> {
    return fetchJSON<RunsResponse>("/api/runs/exemplars");
  },

  /**
   * Get run summary/status
   */
  getRunSummary(runId: string): Promise<RunSummary> {
    return fetchJSON<RunSummary>(`/api/runs/${encodeURIComponent(runId)}/summary`);
  },

  /**
   * Get run timeline events
   */
  getRunTimeline(runId: string): Promise<RunTimeline> {
    return fetchJSON<RunTimeline>(`/api/runs/${encodeURIComponent(runId)}/timeline`);
  },

  /**
   * Get all events for a run (from runtime layer).
   * Returns structured events like tool_start, tool_end, flow_start, etc.
   */
  getRunEvents(runId: string): Promise<RunEventsResponse> {
    return fetchJSON<RunEventsResponse>(`/api/runs/${encodeURIComponent(runId)}/events`);
  },

  /**
   * Get run timing data
   */
  getRunTiming(runId: string): Promise<object> {
    return fetchJSON<object>(`/api/runs/${encodeURIComponent(runId)}/timing`);
  },

  /**
   * Get flow-specific timing for a run
   */
  getFlowTiming(runId: string, flowKey: FlowKey): Promise<object> {
    return fetchJSON<object>(`/api/runs/${encodeURIComponent(runId)}/flows/${encodeURIComponent(flowKey)}/timing`);
  },

  /**
   * Compare two runs
   */
  compareRuns({ runA, runB, flow }: { runA: string; runB: string; flow: FlowKey }): Promise<ComparisonData> {
    return fetchJSON<ComparisonData>(
      `/api/runs/compare?run_a=${encodeURIComponent(runA)}&run_b=${encodeURIComponent(runB)}&flow=${encodeURIComponent(flow)}`
    );
  },

  // ============================================================================
  // Backends
  // ============================================================================

  /**
   * Get list of available backends and their capabilities.
   * Used to populate the backend selector in the UI.
   */
  getBackends(): Promise<BackendsResponse> {
    return fetchJSON<BackendsResponse>("/api/backends");
  },

  // ============================================================================
  // Flows & Graph
  // ============================================================================

  /**
   * Get all flows
   */
  getFlows(): Promise<FlowsResponse> {
    return fetchJSON<FlowsResponse>("/api/flows");
  },

  /**
   * Get flow details
   */
  getFlowDetail(flowKey: FlowKey): Promise<FlowDetail> {
    return fetchJSON<FlowDetail>(`/api/flows/${encodeURIComponent(flowKey)}`);
  },

  /**
   * Get flow graph with agents view
   */
  getFlowGraphAgents(flowKey: FlowKey): Promise<FlowGraph> {
    return fetchJSON<FlowGraph>(`/api/graph/${encodeURIComponent(flowKey)}`);
  },

  /**
   * Get flow graph with artifacts view
   */
  getFlowGraphArtifacts(flowKey: FlowKey, runId?: string): Promise<FlowGraph> {
    const runParam = runId ? `?run_id=${encodeURIComponent(runId)}` : "";
    return fetchJSON<FlowGraph>(`/api/graph/${encodeURIComponent(flowKey)}/artifacts${runParam}`);
  },

  // ============================================================================
  // Agents
  // ============================================================================

  /**
   * Get agent usage data across flows
   */
  getAgentUsage(agentKey: string): Promise<object> {
    return fetchJSON<object>(`/api/agents/${encodeURIComponent(agentKey)}/usage`);
  },

  // ============================================================================
  // Search
  // ============================================================================

  /**
   * Search across flows, steps, agents, artifacts
   */
  search(query: string): Promise<SearchResponse> {
    return fetchJSON<SearchResponse>(`/api/search?q=${encodeURIComponent(query)}`);
  },

  // ============================================================================
  // Governance & Validation
  // ============================================================================

  /**
   * Get governance/platform status
   */
  getGovernanceStatus(): Promise<GovernanceStatus> {
    return fetchJSON<GovernanceStatus>("/platform/status");
  },

  /**
   * Get validation data for overlays
   */
  getValidationData(): Promise<ValidationData> {
    return fetchJSON<ValidationData>("/api/validation");
  },

  // ============================================================================
  // Tours
  // ============================================================================

  /**
   * Get available tours
   */
  getTours(): Promise<ToursResponse> {
    return fetchJSON<ToursResponse>("/api/tours");
  },

  /**
   * Get tour by ID
   */
  getTourById(id: string): Promise<Tour> {
    return fetchJSON<Tour>(`/api/tours/${encodeURIComponent(id)}`);
  },

  // ============================================================================
  // Selftest
  // ============================================================================

  /**
   * Get selftest plan
   */
  getSelftestPlan(): Promise<SelftestPlan> {
    return fetchJSON<SelftestPlan>("/api/selftest/plan");
  },

  // ============================================================================
  // Transcripts
  // ============================================================================

  /**
   * Get LLM transcript for a specific step (stepwise runs only)
   */
  getStepTranscript(runId: string, flowKey: FlowKey, stepId: string): Promise<StepTranscriptResponse> {
    return fetchJSON<StepTranscriptResponse>(
      `/api/runs/${encodeURIComponent(runId)}/flows/${encodeURIComponent(flowKey)}/steps/${encodeURIComponent(stepId)}/transcript`
    );
  },

  /**
   * Get step receipt (execution metadata) for a specific step (stepwise runs only)
   */
  getStepReceipt(runId: string, flowKey: FlowKey, stepId: string): Promise<StepReceiptResponse> {
    return fetchJSON<StepReceiptResponse>(
      `/api/runs/${encodeURIComponent(runId)}/flows/${encodeURIComponent(flowKey)}/steps/${encodeURIComponent(stepId)}/receipt`
    );
  },

  // ============================================================================
  // Wisdom
  // ============================================================================

  /**
   * Get wisdom summary for a run.
   * Returns structured wisdom data including flow statuses, metrics, and labels.
   * Throws 404 error if no wisdom summary exists for this run.
   *
   * @param runId - The run ID to get wisdom summary for
   * @returns WisdomSummary with flow status, metrics, labels, and key artifacts
   */
  getRunWisdom(runId: string): Promise<WisdomSummary> {
    return fetchJSON<WisdomSummary>(
      `/api/runs/${encodeURIComponent(runId)}/wisdom/summary`
    );
  },

  // ============================================================================
  // Boundary Review
  // ============================================================================

  /**
   * Get boundary review summary for a run.
   * Aggregates assumptions, decisions, detours, and verification results
   * for operator review at flow boundaries.
   *
   * @param runId - The run ID to get boundary review for
   * @param options - Optional parameters
   * @param options.scope - "flow" for current flow only, "run" for entire run (default "flow")
   * @param options.flowKey - Optional flow key to filter (when scope="flow")
   * @returns BoundaryReviewResponse with comprehensive boundary review data
   */
  getBoundaryReview(runId: string, options?: {
    scope?: "flow" | "run";
    flowKey?: FlowKey;
  }): Promise<BoundaryReviewResponse> {
    const params = new URLSearchParams();
    if (options?.scope) {
      params.set("scope", options.scope);
    }
    if (options?.flowKey) {
      params.set("flow_key", options.flowKey);
    }
    const queryString = params.toString();
    return fetchJSON<BoundaryReviewResponse>(
      `/api/runs/${encodeURIComponent(runId)}/boundary-review${queryString ? `?${queryString}` : ""}`
    );
  },

  // ============================================================================
  // Config
  // ============================================================================

  /**
   * Reload configuration
   */
  reloadConfig(): Promise<object> {
    return fetchJSON<object>("/api/reload", { method: "POST" });
  },

  // ============================================================================
  // Profiles
  // ============================================================================

  /**
   * Get current profile info
   */
  getCurrentProfile(): Promise<{ profile: ProfileInfo | null; message?: string }> {
    return fetchJSON<{ profile: ProfileInfo | null; message?: string }>("/api/profile");
  },

  /**
   * List all available profiles
   */
  listProfiles(): Promise<{ profiles: ProfileSummary[] }> {
    return fetchJSON<{ profiles: ProfileSummary[] }>("/api/profiles");
  },

  // ============================================================================
  // Run Actions
  // ============================================================================

  /**
   * Set or unset a run as an exemplar.
   * Exemplar runs are highlighted as reference implementations.
   *
   * @param runId - The run ID to modify
   * @param isExemplar - Whether to mark as exemplar (true) or unmark (false)
   */
  setRunExemplar(runId: string, isExemplar: boolean): Promise<void> {
    return fetchJSON<void>(`/api/runs/${encodeURIComponent(runId)}/exemplar`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ is_exemplar: isExemplar }),
    });
  },

  /**
   * Start a new run with the specified configuration.
   * Can be used to re-run an existing run's configuration or start fresh.
   *
   * @param params - Run configuration
   * @param params.flows - Array of flow keys to run (e.g., ["signal", "plan", "build"])
   * @param params.profile_id - Optional profile ID to use
   * @param params.backend - Optional backend identifier (e.g., "local", "github")
   * @returns Object containing the new run_id
   */
  startRun(params: { flows: string[]; profile_id?: string; backend?: string }): Promise<{ run_id: string }> {
    return fetchJSON<{ run_id: string }>("/api/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(params),
    });
  }
};

/** Profile information for currently loaded profile */
export interface ProfileInfo {
  id: string;
  label: string;
  loaded_at: string;
  source_branch: string | null;
}

/** Profile summary for listing */
export interface ProfileSummary {
  id: string;
  label: string;
  description: string;
}

// For backwards compatibility, also export fetchJSON
export { fetchJSON };
