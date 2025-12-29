// swarm/tools/flow_studio_ui/src/api/client.ts
// Flow Studio API Client with ETag support and SSE subscriptions
//
// This module provides a pure client-side API layer. NO filesystem operations.
// All data flows through HTTP/SSE to the backend server.

import type {
  FlowKey,
  FlowGraph,
  FlowDetail,
  FlowStep,
  RunsResponse,
  Run,
  RunSummary,
  RunEvent,
  ValidationData,
} from "../domain.js";

// ============================================================================
// Types
// ============================================================================

/**
 * Template category for organizing the palette
 */
export type TemplateCategory =
  | "flow-control"
  | "agent"
  | "decision"
  | "artifact"
  | "gate"
  | "custom";

/**
 * Template definition for drag-and-drop palette
 */
export interface Template {
  id: string;
  name: string;
  description: string;
  category: TemplateCategory;
  icon?: string;
  /** Template node structure */
  node: TemplateNode;
  /** Default connections when dropped */
  defaultEdges?: TemplateEdge[];
}

/**
 * Template node structure
 */
export interface TemplateNode {
  type: "step" | "agent" | "artifact" | "decision";
  label: string;
  role?: string;
  agents?: string[];
  artifacts?: string[];
  /** Whether this is a decision point */
  isDecision?: boolean;
  /** Teaching note for the template */
  teachingNote?: string;
}

/**
 * Template edge definition
 */
export interface TemplateEdge {
  type: "step-sequence" | "step-agent" | "step-artifact";
  /** Relative to template node: "self", "previous", "next" */
  fromRelative: string;
  toRelative: string;
}

/**
 * Compiled flow result
 */
export interface CompiledFlow {
  flowKey: FlowKey;
  yaml: string;
  markdown: string;
  validation: ValidationData;
  warnings?: string[];
}

/**
 * Run control state
 */
export type RunState = "pending" | "running" | "paused" | "completed" | "failed";

/**
 * Run information
 */
export interface RunInfo extends Run {
  state: RunState;
  currentStep?: string;
  progress?: number;
}

/**
 * Node specification for run injection
 */
export interface NodeSpec {
  id: string;
  type: "step" | "agent" | "artifact";
  label: string;
  position?: { x: number; y: number };
  data?: Record<string, unknown>;
}

/**
 * API response with ETag for optimistic locking
 */
export interface ETagResponse<T> {
  data: T;
  etag: string;
}

/**
 * HTTP conflict error (412)
 */
export class ConflictError extends Error {
  constructor(
    message: string,
    public readonly serverEtag: string,
    public readonly serverData: unknown
  ) {
    super(message);
    this.name = "ConflictError";
  }
}

/**
 * JSON Patch operation for flow updates
 */
export interface PatchOperation {
  op: "replace" | "add" | "remove";
  path: string;
  value?: unknown;
}

/**
 * Full run state from backend
 */
export interface RunStateData {
  run_id: string;
  flow_id: string;
  status: string;
  current_step: string | null;
  completed_steps: string[];
  pending_steps: string[];
  context: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  paused_at: string | null;
  completed_at: string | null;
  error: string | null;
}

/**
 * Response from run action endpoints
 */
export interface RunActionResponse {
  run_id: string;
  status: string;
  message: string;
  timestamp: string;
}

/**
 * Request to inject a node into a run
 */
export interface InjectNodeRequest {
  step_id: string;
  station_id: string;
  position?: string;  // "next", "after:<step_id>", "before:<step_id>"
  params?: Record<string, unknown>;
}

/**
 * Request to interrupt a run with a detour
 */
export interface InterruptRequest {
  reason: string;
  detour_flow?: string;
  detour_steps?: string[];
  resume_after?: boolean;
}

/**
 * SSE event types for run playback
 */
export type SSEEventType =
  | "step_start"
  | "step_end"
  | "routing_decision"
  | "artifact_created"
  | "error"
  | "complete";

/**
 * SSE event payload
 */
export interface SSEEvent {
  type: SSEEventType;
  timestamp: string;
  runId: string;
  flowKey?: FlowKey;
  stepId?: string;
  agentKey?: string;
  payload?: Record<string, unknown>;
}

// ============================================================================
// Core HTTP Helpers
// ============================================================================

/**
 * Fetch JSON with ETag support
 */
async function fetchWithEtag<T>(
  url: string,
  options?: RequestInit
): Promise<ETagResponse<T>> {
  const resp = await fetch(url, options);

  if (!resp.ok) {
    if (resp.status === 412) {
      // Conflict - extract server state
      const serverData = await resp.json();
      const serverEtag = resp.headers.get("ETag") || "";
      throw new ConflictError(
        "Resource was modified by another client",
        serverEtag,
        serverData
      );
    }
    throw new Error(`HTTP ${resp.status} for ${url}`);
  }

  const data = await resp.json() as T;
  const etag = resp.headers.get("ETag") || "";

  return { data, etag };
}

/**
 * Simple fetch JSON without ETag tracking
 */
async function fetchJSON<T>(url: string, options?: RequestInit): Promise<T> {
  const resp = await fetch(url, options);
  if (!resp.ok) {
    throw new Error(`HTTP ${resp.status} for ${url}`);
  }
  return resp.json() as Promise<T>;
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
  private baseUrl: string;
  private activeSubscriptions: Map<string, () => void> = new Map();

  constructor(baseUrl = "") {
    this.baseUrl = baseUrl;
  }

  // ==========================================================================
  // Templates
  // ==========================================================================

  /**
   * Get all available templates for the palette.
   * Backend: GET /api/specs/templates
   */
  async getTemplates(): Promise<Template[]> {
    const response = await fetchJSON<{ templates: Template[] }>(
      `${this.baseUrl}/api/specs/templates`
    );
    return response.templates;
  }

  /**
   * Get templates filtered by category
   */
  async getTemplatesByCategory(category: TemplateCategory): Promise<Template[]> {
    const templates = await this.getTemplates();
    return templates.filter((t) => t.category === category);
  }

  /**
   * Get a single template by ID with ETag caching.
   * Backend: GET /api/specs/templates/{template_id}
   */
  async getTemplate(templateId: string): Promise<ETagResponse<Template>> {
    return fetchWithEtag<Template>(
      `${this.baseUrl}/api/specs/templates/${encodeURIComponent(templateId)}`
    );
  }

  // ==========================================================================
  // Flows
  // ==========================================================================

  /**
   * List all available flows.
   * Backend: GET /api/specs/flows
   */
  async listFlows(): Promise<FlowDetail[]> {
    const response = await fetchJSON<{ flows: FlowDetail[] }>(
      `${this.baseUrl}/api/specs/flows`
    );
    return response.flows;
  }

  /**
   * Get merged flow graph (logic + UI overlay) with ETag for editing.
   * Backend: GET /api/specs/flows/{flow_id}
   */
  async getFlow(id: string): Promise<ETagResponse<FlowGraph>> {
    return fetchWithEtag<FlowGraph>(
      `${this.baseUrl}/api/specs/flows/${encodeURIComponent(id)}`
    );
  }

  /**
   * Get flow detail with ETag.
   * Alias for getFlow - both return merged flow data.
   * Backend: GET /api/specs/flows/{flow_id}
   */
  async getFlowDetail(id: string): Promise<ETagResponse<FlowDetail>> {
    return fetchWithEtag<FlowDetail>(
      `${this.baseUrl}/api/specs/flows/${encodeURIComponent(id)}`
    );
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
  async updateFlow(
    id: string,
    patchOps: PatchOperation[],
    etag: string
  ): Promise<ETagResponse<FlowGraph>> {
    return fetchWithEtag<FlowGraph>(
      `${this.baseUrl}/api/specs/flows/${encodeURIComponent(id)}`,
      {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
          "If-Match": `"${etag}"`,
        },
        body: JSON.stringify(patchOps),
      }
    );
  }

  /**
   * Update flow by replacing the entire graph (convenience method).
   * Converts full replacement to JSON Patch operations.
   */
  async replaceFlow(
    id: string,
    flow: FlowGraph,
    etag: string
  ): Promise<ETagResponse<FlowGraph>> {
    // Convert to JSON Patch replace operation
    const patchOps: PatchOperation[] = [
      { op: "replace", path: "/nodes", value: flow.nodes },
      { op: "replace", path: "/edges", value: flow.edges },
    ];
    return this.updateFlow(id, patchOps, etag);
  }

  /**
   * Add a step to a flow
   */
  async addStep(
    flowId: string,
    step: Partial<FlowStep>,
    etag: string
  ): Promise<ETagResponse<FlowDetail>> {
    return fetchWithEtag<FlowDetail>(
      `${this.baseUrl}/api/flows/${encodeURIComponent(flowId)}/steps`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "If-Match": etag,
        },
        body: JSON.stringify(step),
      }
    );
  }

  /**
   * Update a step in a flow
   */
  async updateStep(
    flowId: string,
    stepId: string,
    step: Partial<FlowStep>,
    etag: string
  ): Promise<ETagResponse<FlowDetail>> {
    return fetchWithEtag<FlowDetail>(
      `${this.baseUrl}/api/flows/${encodeURIComponent(flowId)}/steps/${encodeURIComponent(stepId)}`,
      {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
          "If-Match": etag,
        },
        body: JSON.stringify(step),
      }
    );
  }

  /**
   * Remove a step from a flow
   */
  async removeStep(
    flowId: string,
    stepId: string,
    etag: string
  ): Promise<ETagResponse<FlowDetail>> {
    return fetchWithEtag<FlowDetail>(
      `${this.baseUrl}/api/flows/${encodeURIComponent(flowId)}/steps/${encodeURIComponent(stepId)}`,
      {
        method: "DELETE",
        headers: {
          "If-Match": etag,
        },
      }
    );
  }

  // ==========================================================================
  // Validation & Compilation
  // ==========================================================================

  /**
   * Validate a flow without saving.
   * Backend: POST /api/specs/flows/{flow_id}/validate
   */
  async validateFlow(id: string, data?: Record<string, unknown>): Promise<ValidationData> {
    return fetchJSON<ValidationData>(
      `${this.baseUrl}/api/specs/flows/${encodeURIComponent(id)}/validate`,
      data ? {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      } : { method: "POST" }
    );
  }

  /**
   * Compile a flow step to a PromptPlan.
   * Backend: POST /api/specs/flows/{flow_id}/compile
   */
  async compileFlow(
    id: string,
    stepId: string,
    runId?: string
  ): Promise<CompiledFlow> {
    return fetchJSON<CompiledFlow>(
      `${this.baseUrl}/api/specs/flows/${encodeURIComponent(id)}/compile`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ step_id: stepId, run_id: runId }),
      }
    );
  }

  // ==========================================================================
  // Run Control
  // ==========================================================================

  /**
   * List all runs.
   * Backend: GET /api/runs
   */
  async listRuns(limit = 20): Promise<Run[]> {
    const response = await fetchJSON<{ runs: Run[] }>(
      `${this.baseUrl}/api/runs?limit=${limit}`
    );
    return response.runs;
  }

  /**
   * Start a new run.
   * Backend: POST /api/runs
   */
  async startRun(flowId: string, options?: {
    runId?: string;
    context?: Record<string, unknown>;
    startStep?: string;
    mode?: "execute" | "preview" | "validate";
  }): Promise<RunInfo> {
    const response = await fetchJSON<{
      run_id: string;
      flow_id: string;
      status: string;
      created_at: string;
      events_url: string;
    }>(
      `${this.baseUrl}/api/runs`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          flow_id: flowId,
          run_id: options?.runId,
          context: options?.context,
          start_step: options?.startStep,
          mode: options?.mode ?? "execute",
        }),
      }
    );

    return {
      run_id: response.run_id,
      run_type: "active",
      state: response.status as RunState,
    };
  }

  /**
   * Get run state with ETag.
   * Backend: GET /api/runs/{run_id}
   */
  async getRunState(runId: string): Promise<ETagResponse<RunStateData>> {
    return fetchWithEtag<RunStateData>(
      `${this.baseUrl}/api/runs/${encodeURIComponent(runId)}`
    );
  }

  /**
   * Pause a running run.
   * Backend: POST /api/runs/{run_id}/pause
   */
  async pauseRun(runId: string, etag?: string): Promise<RunActionResponse> {
    const headers: Record<string, string> = {};
    if (etag) headers["If-Match"] = `"${etag}"`;

    return fetchJSON<RunActionResponse>(
      `${this.baseUrl}/api/runs/${encodeURIComponent(runId)}/pause`,
      { method: "POST", headers }
    );
  }

  /**
   * Resume a paused run.
   * Backend: POST /api/runs/{run_id}/resume
   */
  async resumeRun(runId: string, etag?: string): Promise<RunActionResponse> {
    const headers: Record<string, string> = {};
    if (etag) headers["If-Match"] = `"${etag}"`;

    return fetchJSON<RunActionResponse>(
      `${this.baseUrl}/api/runs/${encodeURIComponent(runId)}/resume`,
      { method: "POST", headers }
    );
  }

  /**
   * Cancel a running run.
   * Backend: DELETE /api/runs/{run_id}
   */
  async cancelRun(runId: string, etag?: string): Promise<RunActionResponse> {
    const headers: Record<string, string> = {};
    if (etag) headers["If-Match"] = `"${etag}"`;

    return fetchJSON<RunActionResponse>(
      `${this.baseUrl}/api/runs/${encodeURIComponent(runId)}`,
      { method: "DELETE", headers }
    );
  }

  /**
   * Inject a node into a run.
   * Backend: POST /api/runs/{run_id}/inject
   */
  async injectNode(runId: string, injection: InjectNodeRequest, etag?: string): Promise<RunActionResponse> {
    const headers: Record<string, string> = { "Content-Type": "application/json" };
    if (etag) headers["If-Match"] = `"${etag}"`;

    return fetchJSON<RunActionResponse>(
      `${this.baseUrl}/api/runs/${encodeURIComponent(runId)}/inject`,
      {
        method: "POST",
        headers,
        body: JSON.stringify(injection),
      }
    );
  }

  /**
   * Interrupt a run with a detour.
   * Backend: POST /api/runs/{run_id}/interrupt
   */
  async interruptRun(runId: string, interrupt: InterruptRequest, etag?: string): Promise<RunActionResponse> {
    const headers: Record<string, string> = { "Content-Type": "application/json" };
    if (etag) headers["If-Match"] = `"${etag}"`;

    return fetchJSON<RunActionResponse>(
      `${this.baseUrl}/api/runs/${encodeURIComponent(runId)}/interrupt`,
      {
        method: "POST",
        headers,
        body: JSON.stringify(interrupt),
      }
    );
  }

  /**
   * Get run info (backwards compatible wrapper)
   */
  async getRunInfo(runId: string): Promise<RunInfo> {
    const { data: state } = await this.getRunState(runId);
    return {
      run_id: state.run_id,
      run_type: "active",
      state: state.status as RunState,
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
  subscribeToRun(
    runId: string,
    callback: (event: SSEEvent) => void
  ): () => void {
    // Clean up any existing subscription for this run
    const existing = this.activeSubscriptions.get(runId);
    if (existing) {
      existing();
    }

    const eventSource = new EventSource(
      `${this.baseUrl}/api/runs/${encodeURIComponent(runId)}/events`
    );

    const handleMessage = (event: MessageEvent) => {
      try {
        const data = JSON.parse(event.data) as SSEEvent;
        callback(data);
      } catch (err) {
        console.error("Failed to parse SSE event", err);
      }
    };

    const handleError = (event: Event) => {
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
  closeAllSubscriptions(): void {
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

// ============================================================================
// Re-exports for convenience
// ============================================================================

export type { FlowKey, FlowGraph, FlowDetail, FlowStep, RunEvent };
