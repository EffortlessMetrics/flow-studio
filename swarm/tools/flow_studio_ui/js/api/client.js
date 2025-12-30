// swarm/tools/flow_studio_ui/src/api/client.ts
// Flow Studio API Client with ETag support and SSE subscriptions
//
// This module provides a pure client-side API layer. NO filesystem operations.
// All data flows through HTTP/SSE to the backend server.
/**
 * HTTP conflict error (412)
 */
export class ConflictError extends Error {
    constructor(message, serverEtag, serverData) {
        super(message);
        this.serverEtag = serverEtag;
        this.serverData = serverData;
        this.name = "ConflictError";
    }
}
// ============================================================================
// Core HTTP Helpers
// ============================================================================
/**
 * Fetch JSON with ETag support
 */
async function fetchWithEtag(url, options) {
    const resp = await fetch(url, options);
    if (!resp.ok) {
        if (resp.status === 412) {
            // Conflict - extract server state
            const serverData = await resp.json();
            const serverEtag = resp.headers.get("ETag") || "";
            throw new ConflictError("Resource was modified by another client", serverEtag, serverData);
        }
        throw new Error(`HTTP ${resp.status} for ${url}`);
    }
    const data = await resp.json();
    const etag = resp.headers.get("ETag") || "";
    return { data, etag };
}
/**
 * Simple fetch JSON without ETag tracking
 */
async function fetchJSON(url, options) {
    const resp = await fetch(url, options);
    if (!resp.ok) {
        throw new Error(`HTTP ${resp.status} for ${url}`);
    }
    return resp.json();
}
// ============================================================================
// Flow Studio API Client
// ============================================================================
/**
 * Flow Studio API Client
 *
 * Provides all data operations for the Flow Studio UI.
 * NO filesystem operations - all data flows through HTTP.
 */
export class FlowStudioAPI {
    constructor(baseUrl = "") {
        this.activeSubscriptions = new Map();
        this.baseUrl = baseUrl;
    }
    // ==========================================================================
    // Templates
    // ==========================================================================
    /**
     * Get all available templates for the palette.
     * Backend: GET /api/specs/templates
     */
    async getTemplates() {
        const response = await fetchJSON(`${this.baseUrl}/api/specs/templates`);
        return response.templates;
    }
    /**
     * Get templates filtered by category
     */
    async getTemplatesByCategory(category) {
        const templates = await this.getTemplates();
        return templates.filter((t) => t.category === category);
    }
    /**
     * Get a single template by ID with ETag caching.
     * Backend: GET /api/specs/templates/{template_id}
     */
    async getTemplate(templateId) {
        return fetchWithEtag(`${this.baseUrl}/api/specs/templates/${encodeURIComponent(templateId)}`);
    }
    // ==========================================================================
    // Flows
    // ==========================================================================
    /**
     * List all available flows.
     * Backend: GET /api/specs/flows
     */
    async listFlows() {
        const response = await fetchJSON(`${this.baseUrl}/api/specs/flows`);
        return response.flows;
    }
    /**
     * Get merged flow graph (logic + UI overlay) with ETag for editing.
     * Backend: GET /api/specs/flows/{flow_id}
     */
    async getFlow(id) {
        return fetchWithEtag(`${this.baseUrl}/api/specs/flows/${encodeURIComponent(id)}`);
    }
    /**
     * Get flow detail with ETag.
     * Alias for getFlow - both return merged flow data.
     * Backend: GET /api/specs/flows/{flow_id}
     */
    async getFlowDetail(id) {
        return fetchWithEtag(`${this.baseUrl}/api/specs/flows/${encodeURIComponent(id)}`);
    }
    /**
     * Update flow with optimistic locking (If-Match header).
     * Backend: PATCH /api/specs/flows/{flow_id}
     *
     * @param id - Flow key
     * @param patchOps - JSON Patch operations
     * @param etag - ETag from previous GET
     * @returns Updated flow and new ETag
     * @throws ConflictError if another client modified the flow (412)
     */
    async updateFlow(id, patchOps, etag) {
        return fetchWithEtag(`${this.baseUrl}/api/specs/flows/${encodeURIComponent(id)}`, {
            method: "PATCH",
            headers: {
                "Content-Type": "application/json",
                "If-Match": `"${etag}"`,
            },
            body: JSON.stringify(patchOps),
        });
    }
    /**
     * Update flow by replacing the entire graph (convenience method).
     * Converts full replacement to JSON Patch operations.
     */
    async replaceFlow(id, flow, etag) {
        // Convert to JSON Patch replace operation
        const patchOps = [
            { op: "replace", path: "/nodes", value: flow.nodes },
            { op: "replace", path: "/edges", value: flow.edges },
        ];
        return this.updateFlow(id, patchOps, etag);
    }
    /**
     * Add a step to a flow
     */
    async addStep(flowId, step, etag) {
        return fetchWithEtag(`${this.baseUrl}/api/flows/${encodeURIComponent(flowId)}/steps`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "If-Match": etag,
            },
            body: JSON.stringify(step),
        });
    }
    /**
     * Update a step in a flow
     */
    async updateStep(flowId, stepId, step, etag) {
        return fetchWithEtag(`${this.baseUrl}/api/flows/${encodeURIComponent(flowId)}/steps/${encodeURIComponent(stepId)}`, {
            method: "PATCH",
            headers: {
                "Content-Type": "application/json",
                "If-Match": etag,
            },
            body: JSON.stringify(step),
        });
    }
    /**
     * Remove a step from a flow
     */
    async removeStep(flowId, stepId, etag) {
        return fetchWithEtag(`${this.baseUrl}/api/flows/${encodeURIComponent(flowId)}/steps/${encodeURIComponent(stepId)}`, {
            method: "DELETE",
            headers: {
                "If-Match": etag,
            },
        });
    }
    // ==========================================================================
    // Validation & Compilation
    // ==========================================================================
    /**
     * Validate a flow without saving.
     * Backend: POST /api/specs/flows/{flow_id}/validate
     */
    async validateFlow(id, data) {
        return fetchJSON(`${this.baseUrl}/api/specs/flows/${encodeURIComponent(id)}/validate`, data ? {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(data),
        } : { method: "POST" });
    }
    /**
     * Compile a flow step to a PromptPlan.
     * Backend: POST /api/specs/flows/{flow_id}/compile
     */
    async compileFlow(id, stepId, runId) {
        return fetchJSON(`${this.baseUrl}/api/specs/flows/${encodeURIComponent(id)}/compile`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ step_id: stepId, run_id: runId }),
        });
    }
    // ==========================================================================
    // Run Control
    // ==========================================================================
    /**
     * List all runs.
     * Backend: GET /api/runs
     */
    async listRuns(limit = 20) {
        const response = await fetchJSON(`${this.baseUrl}/api/runs?limit=${limit}`);
        return response.runs;
    }
    /**
     * Start a new run.
     * Backend: POST /api/runs
     */
    async startRun(flowId, options) {
        const response = await fetchJSON(`${this.baseUrl}/api/runs`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                flow_id: flowId,
                run_id: options?.runId,
                context: options?.context,
                start_step: options?.startStep,
                mode: options?.mode ?? "execute",
            }),
        });
        return {
            run_id: response.run_id,
            run_type: "active",
            state: response.status,
        };
    }
    /**
     * Get run state with ETag.
     * Backend: GET /api/runs/{run_id}
     */
    async getRunState(runId) {
        return fetchWithEtag(`${this.baseUrl}/api/runs/${encodeURIComponent(runId)}`);
    }
    /**
     * Pause a running run.
     * Backend: POST /api/runs/{run_id}/pause
     */
    async pauseRun(runId, etag) {
        const headers = {};
        if (etag)
            headers["If-Match"] = `"${etag}"`;
        return fetchJSON(`${this.baseUrl}/api/runs/${encodeURIComponent(runId)}/pause`, { method: "POST", headers });
    }
    /**
     * Resume a paused run.
     * Backend: POST /api/runs/{run_id}/resume
     */
    async resumeRun(runId, etag) {
        const headers = {};
        if (etag)
            headers["If-Match"] = `"${etag}"`;
        return fetchJSON(`${this.baseUrl}/api/runs/${encodeURIComponent(runId)}/resume`, { method: "POST", headers });
    }
    /**
     * Cancel a running run.
     * Backend: DELETE /api/runs/{run_id}
     */
    async cancelRun(runId, etag) {
        const headers = {};
        if (etag)
            headers["If-Match"] = `"${etag}"`;
        return fetchJSON(`${this.baseUrl}/api/runs/${encodeURIComponent(runId)}`, { method: "DELETE", headers });
    }
    /**
     * Inject a node into a run.
     * Backend: POST /api/runs/{run_id}/inject
     */
    async injectNode(runId, injection, etag) {
        const headers = { "Content-Type": "application/json" };
        if (etag)
            headers["If-Match"] = `"${etag}"`;
        return fetchJSON(`${this.baseUrl}/api/runs/${encodeURIComponent(runId)}/inject`, {
            method: "POST",
            headers,
            body: JSON.stringify(injection),
        });
    }
    /**
     * Interrupt a run with a detour.
     * Backend: POST /api/runs/{run_id}/interrupt
     */
    async interruptRun(runId, interrupt, etag) {
        const headers = { "Content-Type": "application/json" };
        if (etag)
            headers["If-Match"] = `"${etag}"`;
        return fetchJSON(`${this.baseUrl}/api/runs/${encodeURIComponent(runId)}/interrupt`, {
            method: "POST",
            headers,
            body: JSON.stringify(interrupt),
        });
    }
    /**
     * Get run info (backwards compatible wrapper)
     */
    async getRunInfo(runId) {
        const { data: state } = await this.getRunState(runId);
        return {
            run_id: state.run_id,
            run_type: "active",
            state: state.status,
            currentStep: state.current_step ?? undefined,
        };
    }
    // ==========================================================================
    // SSE Subscriptions
    // ==========================================================================
    /**
     * Subscribe to run events via Server-Sent Events.
     * Backend: GET /api/runs/{run_id}/events
     *
     * @param runId - Run to subscribe to
     * @param callback - Called for each event
     * @returns Unsubscribe function
     */
    subscribeToRun(runId, callback) {
        // Clean up any existing subscription for this run
        const existing = this.activeSubscriptions.get(runId);
        if (existing) {
            existing();
        }
        const eventSource = new EventSource(`${this.baseUrl}/api/runs/${encodeURIComponent(runId)}/events`);
        const handleMessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                callback(data);
            }
            catch (err) {
                console.error("Failed to parse SSE event", err);
            }
        };
        const handleError = (event) => {
            console.error("SSE connection error", event);
            callback({
                type: "error",
                timestamp: new Date().toISOString(),
                runId,
                payload: { error: "Connection lost" },
            });
        };
        eventSource.onmessage = handleMessage;
        eventSource.onerror = handleError;
        // Handle specific event types from the backend
        const eventTypes = [
            "connected", "heartbeat",
            "run:started", "run:paused", "run:resumed", "run:completed",
            "run:failed", "run:canceled", "run:interrupted",
            "step:started", "step:progress", "step:completed", "step:failed", "step:skipped",
            "artifact:created", "artifact:updated",
            "flow:completed", "plan:completed",
            "llm:started", "llm:token", "llm:completed",
            "error",
        ];
        for (const eventType of eventTypes) {
            eventSource.addEventListener(eventType, handleMessage);
        }
        const unsubscribe = () => {
            eventSource.close();
            this.activeSubscriptions.delete(runId);
        };
        this.activeSubscriptions.set(runId, unsubscribe);
        return unsubscribe;
    }
    /**
     * Close all active SSE subscriptions
     */
    closeAllSubscriptions() {
        for (const unsubscribe of this.activeSubscriptions.values()) {
            unsubscribe();
        }
        this.activeSubscriptions.clear();
    }
}
// ============================================================================
// Default Instance
// ============================================================================
/**
 * Default API client instance
 */
export const flowStudioApi = new FlowStudioAPI();
