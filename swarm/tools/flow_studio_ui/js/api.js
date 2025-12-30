// swarm/tools/flow_studio_ui/src/api.ts
// Centralized API client for Flow Studio
/**
 * Fetch JSON with error handling
 */
async function fetchJSON(url, options) {
    const resp = await fetch(url, options);
    if (!resp.ok) {
        throw new Error(`HTTP ${resp.status} for ${url}`);
    }
    return resp.json();
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
    getRuns(options) {
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
        return fetchJSON(`/api/runs${queryString ? `?${queryString}` : ""}`);
    },
    /**
     * Get list of exemplar runs (curated examples).
     * These are runs marked as reference implementations.
     */
    listExemplars() {
        return fetchJSON("/api/runs/exemplars");
    },
    /**
     * Get run summary/status
     */
    getRunSummary(runId) {
        return fetchJSON(`/api/runs/${encodeURIComponent(runId)}/summary`);
    },
    /**
     * Get run timeline events
     */
    getRunTimeline(runId) {
        return fetchJSON(`/api/runs/${encodeURIComponent(runId)}/timeline`);
    },
    /**
     * Get all events for a run (from runtime layer).
     * Returns structured events like tool_start, tool_end, flow_start, etc.
     */
    getRunEvents(runId) {
        return fetchJSON(`/api/runs/${encodeURIComponent(runId)}/events`);
    },
    /**
     * Get run timing data
     */
    getRunTiming(runId) {
        return fetchJSON(`/api/runs/${encodeURIComponent(runId)}/timing`);
    },
    /**
     * Get flow-specific timing for a run
     */
    getFlowTiming(runId, flowKey) {
        return fetchJSON(`/api/runs/${encodeURIComponent(runId)}/flows/${encodeURIComponent(flowKey)}/timing`);
    },
    /**
     * Compare two runs
     */
    compareRuns({ runA, runB, flow }) {
        return fetchJSON(`/api/runs/compare?run_a=${encodeURIComponent(runA)}&run_b=${encodeURIComponent(runB)}&flow=${encodeURIComponent(flow)}`);
    },
    // ============================================================================
    // Backends
    // ============================================================================
    /**
     * Get list of available backends and their capabilities.
     * Used to populate the backend selector in the UI.
     */
    getBackends() {
        return fetchJSON("/api/backends");
    },
    // ============================================================================
    // Flows & Graph
    // ============================================================================
    /**
     * Get all flows
     */
    getFlows() {
        return fetchJSON("/api/flows");
    },
    /**
     * Get flow details
     */
    getFlowDetail(flowKey) {
        return fetchJSON(`/api/flows/${encodeURIComponent(flowKey)}`);
    },
    /**
     * Get flow graph with agents view
     */
    getFlowGraphAgents(flowKey) {
        return fetchJSON(`/api/graph/${encodeURIComponent(flowKey)}`);
    },
    /**
     * Get flow graph with artifacts view
     */
    getFlowGraphArtifacts(flowKey, runId) {
        const runParam = runId ? `?run_id=${encodeURIComponent(runId)}` : "";
        return fetchJSON(`/api/graph/${encodeURIComponent(flowKey)}/artifacts${runParam}`);
    },
    // ============================================================================
    // Agents
    // ============================================================================
    /**
     * Get agent usage data across flows
     */
    getAgentUsage(agentKey) {
        return fetchJSON(`/api/agents/${encodeURIComponent(agentKey)}/usage`);
    },
    // ============================================================================
    // Search
    // ============================================================================
    /**
     * Search across flows, steps, agents, artifacts
     */
    search(query) {
        return fetchJSON(`/api/search?q=${encodeURIComponent(query)}`);
    },
    // ============================================================================
    // Governance & Validation
    // ============================================================================
    /**
     * Get governance/platform status
     */
    getGovernanceStatus() {
        return fetchJSON("/platform/status");
    },
    /**
     * Get validation data for overlays
     */
    getValidationData() {
        return fetchJSON("/api/validation");
    },
    // ============================================================================
    // Tours
    // ============================================================================
    /**
     * Get available tours
     */
    getTours() {
        return fetchJSON("/api/tours");
    },
    /**
     * Get tour by ID
     */
    getTourById(id) {
        return fetchJSON(`/api/tours/${encodeURIComponent(id)}`);
    },
    // ============================================================================
    // Selftest
    // ============================================================================
    /**
     * Get selftest plan
     */
    getSelftestPlan() {
        return fetchJSON("/api/selftest/plan");
    },
    // ============================================================================
    // Transcripts
    // ============================================================================
    /**
     * Get LLM transcript for a specific step (stepwise runs only)
     */
    getStepTranscript(runId, flowKey, stepId) {
        return fetchJSON(`/api/runs/${encodeURIComponent(runId)}/flows/${encodeURIComponent(flowKey)}/steps/${encodeURIComponent(stepId)}/transcript`);
    },
    /**
     * Get step receipt (execution metadata) for a specific step (stepwise runs only)
     */
    getStepReceipt(runId, flowKey, stepId) {
        return fetchJSON(`/api/runs/${encodeURIComponent(runId)}/flows/${encodeURIComponent(flowKey)}/steps/${encodeURIComponent(stepId)}/receipt`);
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
    getRunWisdom(runId) {
        return fetchJSON(`/api/runs/${encodeURIComponent(runId)}/wisdom/summary`);
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
    getBoundaryReview(runId, options) {
        const params = new URLSearchParams();
        if (options?.scope) {
            params.set("scope", options.scope);
        }
        if (options?.flowKey) {
            params.set("flow_key", options.flowKey);
        }
        const queryString = params.toString();
        return fetchJSON(`/api/runs/${encodeURIComponent(runId)}/boundary-review${queryString ? `?${queryString}` : ""}`);
    },
    // ============================================================================
    // Config
    // ============================================================================
    /**
     * Reload configuration
     */
    reloadConfig() {
        return fetchJSON("/api/reload", { method: "POST" });
    },
    // ============================================================================
    // Profiles
    // ============================================================================
    /**
     * Get current profile info
     */
    getCurrentProfile() {
        return fetchJSON("/api/profile");
    },
    /**
     * List all available profiles
     */
    listProfiles() {
        return fetchJSON("/api/profiles");
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
    setRunExemplar(runId, isExemplar) {
        return fetchJSON(`/api/runs/${encodeURIComponent(runId)}/exemplar`, {
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
    startRun(params) {
        return fetchJSON("/api/run", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(params),
        });
    }
};
// For backwards compatibility, also export fetchJSON
export { fetchJSON };
