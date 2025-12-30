// swarm/tools/flow_studio_ui/src/components/FlowEditor.ts
// Flow editor component with API integration and optimistic locking
//
// Provides visual editing of flow graphs with:
// - ETag-based conflict detection
// - Graceful 412 conflict handling
// - Drag-and-drop from template palette
// - Undo/redo support
//
// NO filesystem operations - all data flows through API.
import { flowStudioApi, ConflictError, } from "../api/client.js";
import { ValidationModal } from "./ValidationModal.js";
// ============================================================================
// Flow Editor Component
// ============================================================================
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
export class FlowEditor {
    constructor(options = {}) {
        this.state = null;
        this.autoSaveTimer = null;
        this.maxUndoDepth = 50;
        this.validationModal = null;
        this.options = {
            autoSaveInterval: 0,
            skipValidationModal: false,
            ...options,
        };
        if (this.options.autoSaveInterval && this.options.autoSaveInterval > 0) {
            this.startAutoSave();
        }
    }
    // ==========================================================================
    // Flow Loading
    // ==========================================================================
    /**
     * Load a flow for editing
     */
    async loadFlow(flowKey) {
        // Fetch graph and detail in parallel
        const [graphResponse, detailResponse] = await Promise.all([
            flowStudioApi.getFlow(flowKey),
            flowStudioApi.getFlowDetail(flowKey),
        ]);
        this.state = {
            flowKey,
            graph: graphResponse.data,
            detail: detailResponse.data,
            etag: graphResponse.etag,
            isDirty: false,
            isSaving: false,
            isValidating: false,
            error: null,
            undoStack: [],
            redoStack: [],
            validationStatus: "unknown",
            lastValidation: null,
        };
        this.notifyChange();
        return this.state;
    }
    /**
     * Get current editor state
     */
    getState() {
        return this.state;
    }
    /**
     * Check if there are unsaved changes
     */
    isDirty() {
        return this.state?.isDirty ?? false;
    }
    // ==========================================================================
    // Graph Editing
    // ==========================================================================
    /**
     * Add a node to the graph
     */
    addNode(node) {
        if (!this.state)
            return;
        this.pushUndo();
        this.state.graph.nodes.push(node);
        this.state.isDirty = true;
        this.notifyChange();
    }
    /**
     * Add a node from a template
     */
    addNodeFromTemplate(template, position) {
        if (!this.state) {
            throw new Error("No flow loaded");
        }
        // Generate unique ID
        const nodeId = `${template.node.type}:${this.state.flowKey}:${Date.now()}`;
        const node = {
            data: {
                id: nodeId,
                type: template.node.type === "decision" ? "step" : template.node.type,
                label: template.node.label,
                flow: this.state.flowKey,
                is_decision: template.node.isDecision,
            },
        };
        this.addNode(node);
        // Add default edges if specified
        if (template.defaultEdges) {
            for (const edgeDef of template.defaultEdges) {
                // Resolve relative references
                const edge = {
                    data: {
                        id: `edge:${nodeId}:${Date.now()}`,
                        type: edgeDef.type,
                        source: edgeDef.fromRelative === "self" ? nodeId : "",
                        target: edgeDef.toRelative === "self" ? nodeId : "",
                    },
                };
                if (edge.data.source && edge.data.target) {
                    this.addEdge(edge);
                }
            }
        }
        return node;
    }
    /**
     * Update a node's data
     */
    updateNode(nodeId, updates) {
        if (!this.state)
            return;
        this.pushUndo();
        const node = this.state.graph.nodes.find((n) => n.data.id === nodeId);
        if (node) {
            node.data = { ...node.data, ...updates };
            this.state.isDirty = true;
            this.notifyChange();
        }
    }
    /**
     * Remove a node and its connected edges
     */
    removeNode(nodeId) {
        if (!this.state)
            return;
        this.pushUndo();
        // Remove node
        this.state.graph.nodes = this.state.graph.nodes.filter((n) => n.data.id !== nodeId);
        // Remove connected edges
        this.state.graph.edges = this.state.graph.edges.filter((e) => e.data.source !== nodeId && e.data.target !== nodeId);
        this.state.isDirty = true;
        this.notifyChange();
    }
    /**
     * Add an edge to the graph
     */
    addEdge(edge) {
        if (!this.state)
            return;
        this.pushUndo();
        this.state.graph.edges.push(edge);
        this.state.isDirty = true;
        this.notifyChange();
    }
    /**
     * Remove an edge
     */
    removeEdge(edgeId) {
        if (!this.state)
            return;
        this.pushUndo();
        this.state.graph.edges = this.state.graph.edges.filter((e) => e.data.id !== edgeId);
        this.state.isDirty = true;
        this.notifyChange();
    }
    // ==========================================================================
    // Step Editing (High-level)
    // ==========================================================================
    /**
     * Add a step to the flow
     */
    async addStep(step) {
        if (!this.state) {
            throw new Error("No flow loaded");
        }
        try {
            const response = await flowStudioApi.addStep(this.state.flowKey, step, this.state.etag);
            this.state.detail = response.data;
            this.state.etag = response.etag;
            // Reload graph to get updated structure
            await this.reloadGraph();
            this.notifyChange();
            return response.data;
        }
        catch (err) {
            if (err instanceof ConflictError) {
                await this.handleConflict(err);
            }
            throw err;
        }
    }
    /**
     * Update a step in the flow
     */
    async updateStep(stepId, updates) {
        if (!this.state) {
            throw new Error("No flow loaded");
        }
        try {
            const response = await flowStudioApi.updateStep(this.state.flowKey, stepId, updates, this.state.etag);
            this.state.detail = response.data;
            this.state.etag = response.etag;
            await this.reloadGraph();
            this.notifyChange();
            return response.data;
        }
        catch (err) {
            if (err instanceof ConflictError) {
                await this.handleConflict(err);
            }
            throw err;
        }
    }
    /**
     * Remove a step from the flow
     */
    async removeStep(stepId) {
        if (!this.state) {
            throw new Error("No flow loaded");
        }
        try {
            const response = await flowStudioApi.removeStep(this.state.flowKey, stepId, this.state.etag);
            this.state.detail = response.data;
            this.state.etag = response.etag;
            await this.reloadGraph();
            this.notifyChange();
            return response.data;
        }
        catch (err) {
            if (err instanceof ConflictError) {
                await this.handleConflict(err);
            }
            throw err;
        }
    }
    // ==========================================================================
    // Saving
    // ==========================================================================
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
    async save(options) {
        if (!this.state) {
            throw new Error("No flow loaded");
        }
        if (!this.state.isDirty) {
            return this.state;
        }
        const skipValidation = options?.skipValidation ?? false;
        const silent = options?.silent ?? this.options.skipValidationModal ?? false;
        // Run validation unless skipped
        if (!skipValidation) {
            const validationResult = await this.validateForSave();
            // Update state with validation result
            this.state.lastValidation = validationResult;
            this.state.validationStatus = this.getValidationStatus(validationResult);
            // Notify validation callback
            if (this.options.onValidation) {
                this.options.onValidation(validationResult);
            }
            // Check for issues
            const hasCritical = validationResult.summary.critical > 0;
            const hasWarnings = validationResult.summary.warning > 0;
            if (hasCritical || hasWarnings) {
                if (silent) {
                    // Silent mode (auto-save): log issues, block on critical
                    if (hasCritical) {
                        console.warn(`[FlowEditor] Save blocked: ${validationResult.summary.critical} critical error(s)`, validationResult.issues.filter((i) => i.severity === "CRITICAL"));
                        this.state.error = `Cannot save: ${validationResult.summary.critical} critical error(s)`;
                        this.notifyChange();
                        throw new Error(this.state.error);
                    }
                    // Warnings only in silent mode: proceed with save
                    console.warn(`[FlowEditor] Saving with ${validationResult.summary.warning} warning(s)`, validationResult.issues.filter((i) => i.severity === "WARNING"));
                }
                else {
                    // Interactive mode: show validation modal
                    const decision = await this.showValidationModal(validationResult);
                    if (decision === "fix" || decision === "cancel") {
                        // User chose to fix issues or cancel
                        this.notifyChange();
                        throw new Error("Save cancelled: User chose to fix validation issues");
                    }
                    // decision === "save": user confirmed save anyway (warnings only)
                    if (hasCritical) {
                        // This shouldn't happen since modal blocks on critical, but be safe
                        throw new Error("Cannot save: Critical errors must be fixed first");
                    }
                }
            }
        }
        // Proceed with actual save
        this.state.isSaving = true;
        this.state.error = null;
        this.notifyChange();
        try {
            // Create patch operations for the full graph update
            // Using replace operations for nodes and edges
            const patchOps = [
                { op: "replace", path: "/nodes", value: this.state.graph.nodes },
                { op: "replace", path: "/edges", value: this.state.graph.edges },
            ];
            // Include UI-related fields if present (these come from merged overlay)
            const graphWithUi = this.state.graph;
            if (graphWithUi.palette) {
                patchOps.push({ op: "replace", path: "/palette", value: graphWithUi.palette });
            }
            if (graphWithUi.canvas) {
                patchOps.push({ op: "replace", path: "/canvas", value: graphWithUi.canvas });
            }
            if (graphWithUi.groups) {
                patchOps.push({ op: "replace", path: "/groups", value: graphWithUi.groups });
            }
            if (graphWithUi.annotations) {
                patchOps.push({ op: "replace", path: "/annotations", value: graphWithUi.annotations });
            }
            const response = await flowStudioApi.updateFlow(this.state.flowKey, patchOps, this.state.etag);
            this.state.graph = response.data;
            this.state.etag = response.etag;
            this.state.isDirty = false;
            this.state.isSaving = false;
            // Clear undo/redo after successful save
            this.state.undoStack = [];
            this.state.redoStack = [];
            // Update validation status to valid after successful save
            this.state.validationStatus = "valid";
            if (this.options.onSave) {
                this.options.onSave(this.state);
            }
            this.notifyChange();
            return this.state;
        }
        catch (err) {
            this.state.isSaving = false;
            if (err instanceof ConflictError) {
                await this.handleConflict(err);
            }
            else {
                this.state.error = err instanceof Error ? err.message : "Save failed";
                this.notifyChange();
            }
            throw err;
        }
    }
    /**
     * Show the validation modal and wait for user decision.
     */
    async showValidationModal(result) {
        if (!this.validationModal) {
            this.validationModal = new ValidationModal();
        }
        return this.validationModal.show(result);
    }
    /**
     * Convert validation result to status indicator value.
     */
    getValidationStatus(result) {
        if (result.summary.critical > 0) {
            return "error";
        }
        if (result.summary.warning > 0) {
            return "warning";
        }
        return "valid";
    }
    // ==========================================================================
    // Conflict Handling
    // ==========================================================================
    /**
     * Handle a 412 conflict error
     */
    async handleConflict(err) {
        if (!this.state)
            return;
        const serverData = err.serverData;
        const serverEtag = err.serverEtag;
        // If we have a conflict handler, use it
        if (this.options.onConflict) {
            const resolution = await this.options.onConflict(this.state, serverData, serverEtag);
            switch (resolution) {
                case "overwrite":
                    // Force save with new ETag
                    this.state.etag = serverEtag;
                    await this.save();
                    break;
                case "merge":
                    // Attempt to merge changes
                    this.state.graph = this.mergeGraphs(this.state.graph, serverData);
                    this.state.etag = serverEtag;
                    this.state.isDirty = true;
                    this.notifyChange();
                    break;
                case "discard":
                    // Discard local changes, use server version
                    this.state.graph = serverData;
                    this.state.etag = serverEtag;
                    this.state.isDirty = false;
                    this.state.undoStack = [];
                    this.state.redoStack = [];
                    this.notifyChange();
                    break;
            }
        }
        else {
            // Default: set error state and let user decide
            this.state.error = "Conflict: Flow was modified by another user";
            this.notifyChange();
        }
    }
    /**
     * Attempt to merge local and server graphs
     * Simple strategy: keep local additions, use server for conflicts
     */
    mergeGraphs(local, server) {
        const serverNodeIds = new Set(server.nodes.map((n) => n.data.id));
        const serverEdgeIds = new Set(server.edges.map((e) => e.data.id));
        // Keep local additions (nodes/edges not on server)
        const localOnlyNodes = local.nodes.filter((n) => !serverNodeIds.has(n.data.id));
        const localOnlyEdges = local.edges.filter((e) => !serverEdgeIds.has(e.data.id));
        return {
            nodes: [...server.nodes, ...localOnlyNodes],
            edges: [...server.edges, ...localOnlyEdges],
        };
    }
    // ==========================================================================
    // Undo/Redo
    // ==========================================================================
    /**
     * Push current state to undo stack
     */
    pushUndo() {
        if (!this.state)
            return;
        // Deep clone current graph
        const snapshot = JSON.parse(JSON.stringify(this.state.graph));
        this.state.undoStack.push(snapshot);
        // Limit stack depth
        if (this.state.undoStack.length > this.maxUndoDepth) {
            this.state.undoStack.shift();
        }
        // Clear redo stack on new action
        this.state.redoStack = [];
    }
    /**
     * Undo the last change
     */
    undo() {
        if (!this.state || this.state.undoStack.length === 0) {
            return false;
        }
        // Save current state to redo stack
        const current = JSON.parse(JSON.stringify(this.state.graph));
        this.state.redoStack.push(current);
        // Restore previous state
        this.state.graph = this.state.undoStack.pop();
        this.state.isDirty = true;
        this.notifyChange();
        return true;
    }
    /**
     * Redo the last undone change
     */
    redo() {
        if (!this.state || this.state.redoStack.length === 0) {
            return false;
        }
        // Save current state to undo stack
        const current = JSON.parse(JSON.stringify(this.state.graph));
        this.state.undoStack.push(current);
        // Restore redo state
        this.state.graph = this.state.redoStack.pop();
        this.state.isDirty = true;
        this.notifyChange();
        return true;
    }
    /**
     * Check if undo is available
     */
    canUndo() {
        return (this.state?.undoStack.length ?? 0) > 0;
    }
    /**
     * Check if redo is available
     */
    canRedo() {
        return (this.state?.redoStack.length ?? 0) > 0;
    }
    // ==========================================================================
    // Validation
    // ==========================================================================
    /**
     * Validate the current flow (returns raw API response)
     */
    async validate() {
        if (!this.state) {
            throw new Error("No flow loaded");
        }
        return flowStudioApi.validateFlow(this.state.flowKey);
    }
    /**
     * Validate the current flow for save operation.
     * Returns a structured FlowValidationResult with severity categorization.
     */
    async validateForSave() {
        if (!this.state) {
            throw new Error("No flow loaded");
        }
        this.state.isValidating = true;
        this.notifyChange();
        try {
            // Get raw validation from API
            const rawValidation = await this.validate();
            // Also perform local graph validation
            const localIssues = this.validateGraph();
            // Transform API validation to our format
            const apiIssues = this.transformValidationData(rawValidation);
            // Combine all issues
            const allIssues = [...localIssues, ...apiIssues];
            // Calculate summary
            const summary = {
                critical: allIssues.filter((i) => i.severity === "CRITICAL").length,
                warning: allIssues.filter((i) => i.severity === "WARNING").length,
                info: allIssues.filter((i) => i.severity === "INFO").length,
            };
            const result = {
                valid: summary.critical === 0,
                issues: allIssues,
                summary,
            };
            this.state.isValidating = false;
            this.notifyChange();
            return result;
        }
        catch (err) {
            this.state.isValidating = false;
            this.notifyChange();
            throw err;
        }
    }
    /**
     * Perform local graph validation for structural issues.
     * These are CRITICAL issues that should block save.
     */
    validateGraph() {
        if (!this.state)
            return [];
        const issues = [];
        const { nodes, edges } = this.state.graph;
        const nodeIds = new Set(nodes.map((n) => n.data.id));
        // Check for nodes with missing required fields
        for (let i = 0; i < nodes.length; i++) {
            const node = nodes[i];
            const path = `nodes[${i}]`;
            // Check for missing ID
            if (!node.data.id || node.data.id.trim() === "") {
                issues.push({
                    code: "MISSING_NODE_ID",
                    severity: "CRITICAL",
                    message: "Node is missing a required ID",
                    path: `${path}.data.id`,
                    fix: "Provide a unique ID for this node",
                });
            }
            // Check for missing label
            if (!node.data.label || node.data.label.trim() === "") {
                issues.push({
                    code: "MISSING_NODE_LABEL",
                    severity: "CRITICAL",
                    message: `Node "${node.data.id || "(unnamed)"}" is missing a required label`,
                    path: `${path}.data.label`,
                    elementId: node.data.id,
                    fix: "Provide a label for this node",
                });
            }
            // Check for missing type
            if (!node.data.type) {
                issues.push({
                    code: "MISSING_NODE_TYPE",
                    severity: "CRITICAL",
                    message: `Node "${node.data.id || "(unnamed)"}" is missing a required type`,
                    path: `${path}.data.type`,
                    elementId: node.data.id,
                    fix: "Specify the node type (step, agent, or artifact)",
                });
            }
        }
        // Check for edges with broken references
        for (let i = 0; i < edges.length; i++) {
            const edge = edges[i];
            const path = `edges[${i}]`;
            // Check for missing source
            if (!edge.data.source) {
                issues.push({
                    code: "MISSING_EDGE_SOURCE",
                    severity: "CRITICAL",
                    message: `Edge "${edge.data.id}" is missing a source node`,
                    path: `${path}.data.source`,
                    elementId: edge.data.id,
                    fix: "Specify the source node for this edge",
                });
            }
            else if (!nodeIds.has(edge.data.source)) {
                issues.push({
                    code: "BROKEN_EDGE_SOURCE",
                    severity: "CRITICAL",
                    message: `Edge "${edge.data.id}" references non-existent source node "${edge.data.source}"`,
                    path: `${path}.data.source`,
                    elementId: edge.data.id,
                    fix: "Connect the edge to an existing node or remove it",
                });
            }
            // Check for missing target
            if (!edge.data.target) {
                issues.push({
                    code: "MISSING_EDGE_TARGET",
                    severity: "CRITICAL",
                    message: `Edge "${edge.data.id}" is missing a target node`,
                    path: `${path}.data.target`,
                    elementId: edge.data.id,
                    fix: "Specify the target node for this edge",
                });
            }
            else if (!nodeIds.has(edge.data.target)) {
                issues.push({
                    code: "BROKEN_EDGE_TARGET",
                    severity: "CRITICAL",
                    message: `Edge "${edge.data.id}" references non-existent target node "${edge.data.target}"`,
                    path: `${path}.data.target`,
                    elementId: edge.data.id,
                    fix: "Connect the edge to an existing node or remove it",
                });
            }
        }
        // Check for duplicate node IDs
        const seenIds = new Set();
        for (const node of nodes) {
            if (node.data.id) {
                if (seenIds.has(node.data.id)) {
                    issues.push({
                        code: "DUPLICATE_NODE_ID",
                        severity: "CRITICAL",
                        message: `Duplicate node ID: "${node.data.id}"`,
                        elementId: node.data.id,
                        fix: "Ensure all nodes have unique IDs",
                    });
                }
                seenIds.add(node.data.id);
            }
        }
        return issues;
    }
    /**
     * Transform API ValidationData into ValidationIssue array.
     * Maps FR check failures to our severity levels.
     */
    transformValidationData(data) {
        const issues = [];
        // Map check status to severity
        const statusToSeverity = (status) => {
            switch (status) {
                case "fail":
                    return "CRITICAL";
                case "warn":
                    return "WARNING";
                default:
                    return null;
            }
        };
        // Process flow validation for current flow
        if (this.state) {
            const flowValidation = data.flows[this.state.flowKey];
            if (flowValidation) {
                // Process FR checks
                for (const [checkId, check] of Object.entries(flowValidation.checks)) {
                    const severity = statusToSeverity(check.status);
                    if (severity) {
                        issues.push({
                            code: checkId,
                            severity,
                            message: check.message || `Check ${checkId} ${check.status}`,
                            fix: check.fix,
                        });
                    }
                }
                // Process detailed issues
                if (flowValidation.issues) {
                    for (const issue of flowValidation.issues) {
                        issues.push({
                            code: issue.error_type,
                            severity: "CRITICAL",
                            message: issue.problem,
                            fix: issue.fix_action,
                        });
                    }
                }
            }
        }
        // Check for missing teaching notes (WARNING level)
        if (this.state?.detail?.steps) {
            for (const step of this.state.detail.steps) {
                if (!step.teaching_note && !step.teaching_notes) {
                    issues.push({
                        code: "MISSING_TEACHING_NOTE",
                        severity: "WARNING",
                        message: `Step "${step.id}" is missing teaching notes`,
                        elementId: step.id,
                        fix: "Add teaching notes to help users understand this step",
                    });
                }
            }
        }
        return issues;
    }
    /**
     * Compile the flow to output formats for a specific step
     *
     * @param stepId - The step ID to compile. Required.
     * @param runId - Optional run ID for context.
     */
    async compile(stepId, runId) {
        if (!this.state) {
            throw new Error("No flow loaded");
        }
        return flowStudioApi.compileFlow(this.state.flowKey, stepId, runId);
    }
    /**
     * Get the current validation status
     */
    getValidationState() {
        return {
            status: this.state?.validationStatus ?? "unknown",
            result: this.state?.lastValidation ?? null,
        };
    }
    // ==========================================================================
    // Auto-save
    // ==========================================================================
    /**
     * Start auto-save timer
     */
    startAutoSave() {
        if (this.autoSaveTimer) {
            clearInterval(this.autoSaveTimer);
        }
        this.autoSaveTimer = setInterval(async () => {
            if (this.state?.isDirty && !this.state.isSaving && !this.state.isValidating) {
                try {
                    // Auto-save uses silent mode to avoid modal interruptions
                    await this.save({ silent: true });
                }
                catch (err) {
                    console.error("Auto-save failed", err);
                }
            }
        }, this.options.autoSaveInterval);
    }
    /**
     * Stop auto-save timer
     */
    stopAutoSave() {
        if (this.autoSaveTimer) {
            clearInterval(this.autoSaveTimer);
            this.autoSaveTimer = null;
        }
    }
    // ==========================================================================
    // Helpers
    // ==========================================================================
    /**
     * Reload graph from server
     */
    async reloadGraph() {
        if (!this.state)
            return;
        const response = await flowStudioApi.getFlow(this.state.flowKey);
        this.state.graph = response.data;
        this.state.etag = response.etag;
    }
    /**
     * Notify change listeners
     */
    notifyChange() {
        if (this.state && this.options.onChange) {
            this.options.onChange(this.state);
        }
    }
    /**
     * Destroy the editor and clean up
     */
    destroy() {
        this.stopAutoSave();
        if (this.validationModal) {
            this.validationModal.destroy();
            this.validationModal = null;
        }
        this.state = null;
    }
}
// ============================================================================
// Factory Function
// ============================================================================
/**
 * Create a new flow editor instance
 */
export function createFlowEditor(options) {
    return new FlowEditor(options);
}
