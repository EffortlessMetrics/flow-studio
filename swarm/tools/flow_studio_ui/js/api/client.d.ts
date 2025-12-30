import type { FlowKey, FlowGraph, FlowDetail, FlowStep, Run, RunEvent, ValidationData } from "../domain.js";
/**
 * Template category for organizing the palette
 */
export type TemplateCategory = "flow-control" | "agent" | "decision" | "artifact" | "gate" | "custom";
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
export type RunState = "pending" | "running" | "paused" | "completed" | "failed" | "stopped";
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
    position?: {
        x: number;
        y: number;
    };
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
export declare class ConflictError extends Error {
    readonly serverEtag: string;
    readonly serverData: unknown;
    constructor(message: string, serverEtag: string, serverData: unknown);
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
    position?: string;
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
export type SSEEventType = "step_start" | "step_end" | "routing_decision" | "artifact_created" | "facts_updated" | "flow_completed" | "plan_completed" | "error" | "complete";
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
/**
 * Flow Studio API Client
 *
 * Provides all data operations for the Flow Studio UI.
 * NO filesystem operations - all data flows through HTTP.
 */
export declare class FlowStudioAPI {
    private baseUrl;
    private activeSubscriptions;
    constructor(baseUrl?: string);
    /**
     * Get all available templates for the palette.
     * Backend: GET /api/specs/templates
     */
    getTemplates(): Promise<Template[]>;
    /**
     * Get templates filtered by category
     */
    getTemplatesByCategory(category: TemplateCategory): Promise<Template[]>;
    /**
     * Get a single template by ID with ETag caching.
     * Backend: GET /api/specs/templates/{template_id}
     */
    getTemplate(templateId: string): Promise<ETagResponse<Template>>;
    /**
     * List all available flows.
     * Backend: GET /api/specs/flows
     */
    listFlows(): Promise<FlowDetail[]>;
    /**
     * Get merged flow graph (logic + UI overlay) with ETag for editing.
     * Backend: GET /api/specs/flows/{flow_id}
     */
    getFlow(id: string): Promise<ETagResponse<FlowGraph>>;
    /**
     * Get flow detail with ETag.
     * Alias for getFlow - both return merged flow data.
     * Backend: GET /api/specs/flows/{flow_id}
     */
    getFlowDetail(id: string): Promise<ETagResponse<FlowDetail>>;
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
    updateFlow(id: string, patchOps: PatchOperation[], etag: string): Promise<ETagResponse<FlowGraph>>;
    /**
     * Update flow by replacing the entire graph (convenience method).
     * Converts full replacement to JSON Patch operations.
     */
    replaceFlow(id: string, flow: FlowGraph, etag: string): Promise<ETagResponse<FlowGraph>>;
    /**
     * Add a step to a flow
     */
    addStep(flowId: string, step: Partial<FlowStep>, etag: string): Promise<ETagResponse<FlowDetail>>;
    /**
     * Update a step in a flow
     */
    updateStep(flowId: string, stepId: string, step: Partial<FlowStep>, etag: string): Promise<ETagResponse<FlowDetail>>;
    /**
     * Remove a step from a flow
     */
    removeStep(flowId: string, stepId: string, etag: string): Promise<ETagResponse<FlowDetail>>;
    /**
     * Validate a flow without saving.
     * Backend: POST /api/specs/flows/{flow_id}/validate
     */
    validateFlow(id: string, data?: Record<string, unknown>): Promise<ValidationData>;
    /**
     * Compile a flow step to a PromptPlan.
     * Backend: POST /api/specs/flows/{flow_id}/compile
     */
    compileFlow(id: string, stepId: string, runId?: string): Promise<CompiledFlow>;
    /**
     * List all runs.
     * Backend: GET /api/runs
     */
    listRuns(limit?: number): Promise<Run[]>;
    /**
     * Start a new run.
     * Backend: POST /api/runs
     */
    startRun(flowId: string, options?: {
        runId?: string;
        context?: Record<string, unknown>;
        startStep?: string;
        mode?: "execute" | "preview" | "validate";
    }): Promise<RunInfo>;
    /**
     * Get run state with ETag.
     * Backend: GET /api/runs/{run_id}
     */
    getRunState(runId: string): Promise<ETagResponse<RunStateData>>;
    /**
     * Pause a running run.
     * Backend: POST /api/runs/{run_id}/pause
     */
    pauseRun(runId: string, etag?: string): Promise<RunActionResponse>;
    /**
     * Resume a paused run.
     * Backend: POST /api/runs/{run_id}/resume
     */
    resumeRun(runId: string, etag?: string): Promise<RunActionResponse>;
    /**
     * Cancel a running run.
     * Backend: DELETE /api/runs/{run_id}
     */
    cancelRun(runId: string, etag?: string): Promise<RunActionResponse>;
    /**
     * Inject a node into a run.
     * Backend: POST /api/runs/{run_id}/inject
     */
    injectNode(runId: string, injection: InjectNodeRequest, etag?: string): Promise<RunActionResponse>;
    /**
     * Interrupt a run with a detour.
     * Backend: POST /api/runs/{run_id}/interrupt
     */
    interruptRun(runId: string, interrupt: InterruptRequest, etag?: string): Promise<RunActionResponse>;
    /**
     * Get run info (backwards compatible wrapper)
     */
    getRunInfo(runId: string): Promise<RunInfo>;
    /**
     * Subscribe to run events via Server-Sent Events.
     * Backend: GET /api/runs/{run_id}/events
     *
     * @param runId - Run to subscribe to
     * @param callback - Called for each event
     * @returns Unsubscribe function
     */
    subscribeToRun(runId: string, callback: (event: SSEEvent) => void): () => void;
    /**
     * Close all active SSE subscriptions
     */
    closeAllSubscriptions(): void;
}
/**
 * Default API client instance
 */
export declare const flowStudioApi: FlowStudioAPI;
export type { FlowKey, FlowGraph, FlowDetail, FlowStep, RunEvent };
