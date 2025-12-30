import type { RunsResponse, RunSummary, RunTimeline, RunEventsResponse, ComparisonData, FlowsResponse, FlowDetail, FlowGraph, FlowKey, SearchResponse, GovernanceStatus, ValidationData, ToursResponse, Tour, SelftestPlan, BackendsResponse, StepTranscriptResponse, StepReceiptResponse, WisdomSummary, BoundaryReviewResponse } from "./domain.js";
/**
 * Fetch JSON with error handling
 */
declare function fetchJSON<T>(url: string, options?: RequestInit): Promise<T>;
/**
 * API client with methods for all Flow Studio endpoints
 */
export declare const Api: {
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
    }): Promise<RunsResponse>;
    /**
     * Get list of exemplar runs (curated examples).
     * These are runs marked as reference implementations.
     */
    listExemplars(): Promise<RunsResponse>;
    /**
     * Get run summary/status
     */
    getRunSummary(runId: string): Promise<RunSummary>;
    /**
     * Get run timeline events
     */
    getRunTimeline(runId: string): Promise<RunTimeline>;
    /**
     * Get all events for a run (from runtime layer).
     * Returns structured events like tool_start, tool_end, flow_start, etc.
     */
    getRunEvents(runId: string): Promise<RunEventsResponse>;
    /**
     * Get run timing data
     */
    getRunTiming(runId: string): Promise<object>;
    /**
     * Get flow-specific timing for a run
     */
    getFlowTiming(runId: string, flowKey: FlowKey): Promise<object>;
    /**
     * Compare two runs
     */
    compareRuns({ runA, runB, flow }: {
        runA: string;
        runB: string;
        flow: FlowKey;
    }): Promise<ComparisonData>;
    /**
     * Get list of available backends and their capabilities.
     * Used to populate the backend selector in the UI.
     */
    getBackends(): Promise<BackendsResponse>;
    /**
     * Get all flows
     */
    getFlows(): Promise<FlowsResponse>;
    /**
     * Get flow details
     */
    getFlowDetail(flowKey: FlowKey): Promise<FlowDetail>;
    /**
     * Get flow graph with agents view
     */
    getFlowGraphAgents(flowKey: FlowKey): Promise<FlowGraph>;
    /**
     * Get flow graph with artifacts view
     */
    getFlowGraphArtifacts(flowKey: FlowKey, runId?: string): Promise<FlowGraph>;
    /**
     * Get agent usage data across flows
     */
    getAgentUsage(agentKey: string): Promise<object>;
    /**
     * Search across flows, steps, agents, artifacts
     */
    search(query: string): Promise<SearchResponse>;
    /**
     * Get governance/platform status
     */
    getGovernanceStatus(): Promise<GovernanceStatus>;
    /**
     * Get validation data for overlays
     */
    getValidationData(): Promise<ValidationData>;
    /**
     * Get available tours
     */
    getTours(): Promise<ToursResponse>;
    /**
     * Get tour by ID
     */
    getTourById(id: string): Promise<Tour>;
    /**
     * Get selftest plan
     */
    getSelftestPlan(): Promise<SelftestPlan>;
    /**
     * Get LLM transcript for a specific step (stepwise runs only)
     */
    getStepTranscript(runId: string, flowKey: FlowKey, stepId: string): Promise<StepTranscriptResponse>;
    /**
     * Get step receipt (execution metadata) for a specific step (stepwise runs only)
     */
    getStepReceipt(runId: string, flowKey: FlowKey, stepId: string): Promise<StepReceiptResponse>;
    /**
     * Get wisdom summary for a run.
     * Returns structured wisdom data including flow statuses, metrics, and labels.
     * Throws 404 error if no wisdom summary exists for this run.
     *
     * @param runId - The run ID to get wisdom summary for
     * @returns WisdomSummary with flow status, metrics, labels, and key artifacts
     */
    getRunWisdom(runId: string): Promise<WisdomSummary>;
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
    }): Promise<BoundaryReviewResponse>;
    /**
     * Reload configuration
     */
    reloadConfig(): Promise<object>;
    /**
     * Get current profile info
     */
    getCurrentProfile(): Promise<{
        profile: ProfileInfo | null;
        message?: string;
    }>;
    /**
     * List all available profiles
     */
    listProfiles(): Promise<{
        profiles: ProfileSummary[];
    }>;
    /**
     * Set or unset a run as an exemplar.
     * Exemplar runs are highlighted as reference implementations.
     *
     * @param runId - The run ID to modify
     * @param isExemplar - Whether to mark as exemplar (true) or unmark (false)
     */
    setRunExemplar(runId: string, isExemplar: boolean): Promise<void>;
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
    startRun(params: {
        flows: string[];
        profile_id?: string;
        backend?: string;
    }): Promise<{
        run_id: string;
    }>;
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
export { fetchJSON };
