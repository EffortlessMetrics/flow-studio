import type { Template } from "../api/client.js";
import type { FlowKey, FlowGraph, FlowDetail, FlowStep, FlowGraphNode, FlowGraphEdge, ValidationData, FlowValidationResult } from "../domain.js";
/**
 * Validation status for display in the UI
 */
export type ValidationStatus = "valid" | "warning" | "error" | "unknown";
/**
 * Editor state for a flow
 */
interface EditorState {
    flowKey: FlowKey;
    graph: FlowGraph;
    detail: FlowDetail;
    etag: string;
    isDirty: boolean;
    isSaving: boolean;
    isValidating: boolean;
    error: string | null;
    undoStack: FlowGraph[];
    redoStack: FlowGraph[];
    /** Current validation status for UI indicator */
    validationStatus: ValidationStatus;
    /** Last validation result */
    lastValidation: FlowValidationResult | null;
}
/**
 * Conflict resolution options
 */
type ConflictResolution = "overwrite" | "merge" | "discard";
/**
 * Editor options
 */
interface FlowEditorOptions {
    /** Initial flow to load */
    flowKey?: FlowKey;
    /** Callback when flow changes */
    onChange?: (state: EditorState) => void;
    /** Callback when save completes */
    onSave?: (state: EditorState) => void;
    /** Callback when conflict occurs */
    onConflict?: (localState: EditorState, serverData: FlowGraph, serverEtag: string) => Promise<ConflictResolution>;
    /** Auto-save interval in ms (0 to disable) */
    autoSaveInterval?: number;
    /** Skip validation modal and always validate silently (for auto-save) */
    skipValidationModal?: boolean;
    /** Callback when validation completes (for UI updates) */
    onValidation?: (result: FlowValidationResult) => void;
}
/**
 * Flow editor with API integration and optimistic locking.
 *
 * Features:
 * - Fetch flow with ETag tracking
 * - Edit nodes/edges visually
 * - PATCH back with If-Match header
 * - Handle 412 conflicts gracefully
 * - Undo/redo support
 */
export declare class FlowEditor {
    private state;
    private options;
    private autoSaveTimer;
    private maxUndoDepth;
    private validationModal;
    constructor(options?: FlowEditorOptions);
    /**
     * Load a flow for editing
     */
    loadFlow(flowKey: FlowKey): Promise<EditorState>;
    /**
     * Get current editor state
     */
    getState(): EditorState | null;
    /**
     * Check if there are unsaved changes
     */
    isDirty(): boolean;
    /**
     * Add a node to the graph
     */
    addNode(node: FlowGraphNode): void;
    /**
     * Add a node from a template
     */
    addNodeFromTemplate(template: Template, position?: {
        x: number;
        y: number;
    }): FlowGraphNode;
    /**
     * Update a node's data
     */
    updateNode(nodeId: string, updates: Partial<FlowGraphNode["data"]>): void;
    /**
     * Remove a node and its connected edges
     */
    removeNode(nodeId: string): void;
    /**
     * Add an edge to the graph
     */
    addEdge(edge: FlowGraphEdge): void;
    /**
     * Remove an edge
     */
    removeEdge(edgeId: string): void;
    /**
     * Add a step to the flow
     */
    addStep(step: Partial<FlowStep>): Promise<FlowDetail>;
    /**
     * Update a step in the flow
     */
    updateStep(stepId: string, updates: Partial<FlowStep>): Promise<FlowDetail>;
    /**
     * Remove a step from the flow
     */
    removeStep(stepId: string): Promise<FlowDetail>;
    /**
     * Save the current graph state with validation.
     *
     * Validation workflow:
     * 1. Run validation before save
     * 2. If critical errors: block save, show modal, return to editor
     * 3. If warnings: show modal with "Save Anyway" option
     * 4. If no issues or user confirms: proceed with save
     *
     * @param options.skipValidation - Skip validation check (use for forced saves)
     * @param options.silent - Skip validation modal (for auto-save, log issues only)
     */
    save(options?: {
        skipValidation?: boolean;
        silent?: boolean;
    }): Promise<EditorState>;
    /**
     * Show the validation modal and wait for user decision.
     */
    private showValidationModal;
    /**
     * Convert validation result to status indicator value.
     */
    private getValidationStatus;
    /**
     * Handle a 412 conflict error
     */
    private handleConflict;
    /**
     * Attempt to merge local and server graphs
     * Simple strategy: keep local additions, use server for conflicts
     */
    private mergeGraphs;
    /**
     * Push current state to undo stack
     */
    private pushUndo;
    /**
     * Undo the last change
     */
    undo(): boolean;
    /**
     * Redo the last undone change
     */
    redo(): boolean;
    /**
     * Check if undo is available
     */
    canUndo(): boolean;
    /**
     * Check if redo is available
     */
    canRedo(): boolean;
    /**
     * Validate the current flow (returns raw API response)
     */
    validate(): Promise<ValidationData>;
    /**
     * Validate the current flow for save operation.
     * Returns a structured FlowValidationResult with severity categorization.
     */
    validateForSave(): Promise<FlowValidationResult>;
    /**
     * Perform local graph validation for structural issues.
     * These are CRITICAL issues that should block save.
     */
    private validateGraph;
    /**
     * Transform API ValidationData into ValidationIssue array.
     * Maps FR check failures to our severity levels.
     */
    private transformValidationData;
    /**
     * Compile the flow to output formats for a specific step
     *
     * @param stepId - The step ID to compile. Required.
     * @param runId - Optional run ID for context.
     */
    compile(stepId: string, runId?: string): Promise<import("../api/client.js").CompiledFlow>;
    /**
     * Get the current validation status
     */
    getValidationState(): {
        status: ValidationStatus;
        result: FlowValidationResult | null;
    };
    /**
     * Start auto-save timer
     */
    private startAutoSave;
    /**
     * Stop auto-save timer
     */
    stopAutoSave(): void;
    /**
     * Reload graph from server
     */
    private reloadGraph;
    /**
     * Notify change listeners
     */
    private notifyChange;
    /**
     * Destroy the editor and clean up
     */
    destroy(): void;
}
/**
 * Create a new flow editor instance
 */
export declare function createFlowEditor(options?: FlowEditorOptions): FlowEditor;
export {};
