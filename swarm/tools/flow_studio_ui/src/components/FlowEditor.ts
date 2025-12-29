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

import {
  flowStudioApi,
  ConflictError,
} from "../api/client.js";
import type {
  Template,
  ETagResponse,
} from "../api/client.js";
import type {
  FlowKey,
  FlowGraph,
  FlowDetail,
  FlowStep,
  FlowGraphNode,
  FlowGraphEdge,
} from "../domain.js";

// ============================================================================
// Types
// ============================================================================

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
  error: string | null;
  undoStack: FlowGraph[];
  redoStack: FlowGraph[];
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
  onConflict?: (
    localState: EditorState,
    serverData: FlowGraph,
    serverEtag: string
  ) => Promise<ConflictResolution>;
  /** Auto-save interval in ms (0 to disable) */
  autoSaveInterval?: number;
}

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
  private state: EditorState | null = null;
  private options: FlowEditorOptions;
  private autoSaveTimer: ReturnType<typeof setInterval> | null = null;
  private maxUndoDepth = 50;

  constructor(options: FlowEditorOptions = {}) {
    this.options = {
      autoSaveInterval: 0,
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
  async loadFlow(flowKey: FlowKey): Promise<EditorState> {
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
      error: null,
      undoStack: [],
      redoStack: [],
    };

    this.notifyChange();
    return this.state;
  }

  /**
   * Get current editor state
   */
  getState(): EditorState | null {
    return this.state;
  }

  /**
   * Check if there are unsaved changes
   */
  isDirty(): boolean {
    return this.state?.isDirty ?? false;
  }

  // ==========================================================================
  // Graph Editing
  // ==========================================================================

  /**
   * Add a node to the graph
   */
  addNode(node: FlowGraphNode): void {
    if (!this.state) return;

    this.pushUndo();
    this.state.graph.nodes.push(node);
    this.state.isDirty = true;
    this.notifyChange();
  }

  /**
   * Add a node from a template
   */
  addNodeFromTemplate(
    template: Template,
    position?: { x: number; y: number }
  ): FlowGraphNode {
    if (!this.state) {
      throw new Error("No flow loaded");
    }

    // Generate unique ID
    const nodeId = `${template.node.type}:${this.state.flowKey}:${Date.now()}`;

    const node: FlowGraphNode = {
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
        const edge: FlowGraphEdge = {
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
  updateNode(nodeId: string, updates: Partial<FlowGraphNode["data"]>): void {
    if (!this.state) return;

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
  removeNode(nodeId: string): void {
    if (!this.state) return;

    this.pushUndo();

    // Remove node
    this.state.graph.nodes = this.state.graph.nodes.filter(
      (n) => n.data.id !== nodeId
    );

    // Remove connected edges
    this.state.graph.edges = this.state.graph.edges.filter(
      (e) => e.data.source !== nodeId && e.data.target !== nodeId
    );

    this.state.isDirty = true;
    this.notifyChange();
  }

  /**
   * Add an edge to the graph
   */
  addEdge(edge: FlowGraphEdge): void {
    if (!this.state) return;

    this.pushUndo();
    this.state.graph.edges.push(edge);
    this.state.isDirty = true;
    this.notifyChange();
  }

  /**
   * Remove an edge
   */
  removeEdge(edgeId: string): void {
    if (!this.state) return;

    this.pushUndo();
    this.state.graph.edges = this.state.graph.edges.filter(
      (e) => e.data.id !== edgeId
    );
    this.state.isDirty = true;
    this.notifyChange();
  }

  // ==========================================================================
  // Step Editing (High-level)
  // ==========================================================================

  /**
   * Add a step to the flow
   */
  async addStep(step: Partial<FlowStep>): Promise<FlowDetail> {
    if (!this.state) {
      throw new Error("No flow loaded");
    }

    try {
      const response = await flowStudioApi.addStep(
        this.state.flowKey,
        step,
        this.state.etag
      );

      this.state.detail = response.data;
      this.state.etag = response.etag;

      // Reload graph to get updated structure
      await this.reloadGraph();

      this.notifyChange();
      return response.data;
    } catch (err) {
      if (err instanceof ConflictError) {
        await this.handleConflict(err);
      }
      throw err;
    }
  }

  /**
   * Update a step in the flow
   */
  async updateStep(stepId: string, updates: Partial<FlowStep>): Promise<FlowDetail> {
    if (!this.state) {
      throw new Error("No flow loaded");
    }

    try {
      const response = await flowStudioApi.updateStep(
        this.state.flowKey,
        stepId,
        updates,
        this.state.etag
      );

      this.state.detail = response.data;
      this.state.etag = response.etag;

      await this.reloadGraph();
      this.notifyChange();

      return response.data;
    } catch (err) {
      if (err instanceof ConflictError) {
        await this.handleConflict(err);
      }
      throw err;
    }
  }

  /**
   * Remove a step from the flow
   */
  async removeStep(stepId: string): Promise<FlowDetail> {
    if (!this.state) {
      throw new Error("No flow loaded");
    }

    try {
      const response = await flowStudioApi.removeStep(
        this.state.flowKey,
        stepId,
        this.state.etag
      );

      this.state.detail = response.data;
      this.state.etag = response.etag;

      await this.reloadGraph();
      this.notifyChange();

      return response.data;
    } catch (err) {
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
   * Save the current graph state
   */
  async save(): Promise<EditorState> {
    if (!this.state) {
      throw new Error("No flow loaded");
    }

    if (!this.state.isDirty) {
      return this.state;
    }

    this.state.isSaving = true;
    this.state.error = null;
    this.notifyChange();

    try {
      // Create patch operations for the full graph update
      // Using replace operations for nodes and edges
      const patchOps: import("../api/client").PatchOperation[] = [
        { op: "replace", path: "/nodes", value: this.state.graph.nodes },
        { op: "replace", path: "/edges", value: this.state.graph.edges },
      ];

      // Include UI-related fields if present (these come from merged overlay)
      const graphWithUi = this.state.graph as FlowGraph & {
        palette?: unknown;
        canvas?: unknown;
        groups?: unknown;
        annotations?: unknown;
      };
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

      const response = await flowStudioApi.updateFlow(
        this.state.flowKey,
        patchOps,
        this.state.etag
      );

      this.state.graph = response.data;
      this.state.etag = response.etag;
      this.state.isDirty = false;
      this.state.isSaving = false;

      // Clear undo/redo after successful save
      this.state.undoStack = [];
      this.state.redoStack = [];

      if (this.options.onSave) {
        this.options.onSave(this.state);
      }

      this.notifyChange();
      return this.state;
    } catch (err) {
      this.state.isSaving = false;

      if (err instanceof ConflictError) {
        await this.handleConflict(err);
      } else {
        this.state.error = err instanceof Error ? err.message : "Save failed";
        this.notifyChange();
      }

      throw err;
    }
  }

  // ==========================================================================
  // Conflict Handling
  // ==========================================================================

  /**
   * Handle a 412 conflict error
   */
  private async handleConflict(err: ConflictError): Promise<void> {
    if (!this.state) return;

    const serverData = err.serverData as FlowGraph;
    const serverEtag = err.serverEtag;

    // If we have a conflict handler, use it
    if (this.options.onConflict) {
      const resolution = await this.options.onConflict(
        this.state,
        serverData,
        serverEtag
      );

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
    } else {
      // Default: set error state and let user decide
      this.state.error = "Conflict: Flow was modified by another user";
      this.notifyChange();
    }
  }

  /**
   * Attempt to merge local and server graphs
   * Simple strategy: keep local additions, use server for conflicts
   */
  private mergeGraphs(local: FlowGraph, server: FlowGraph): FlowGraph {
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
  private pushUndo(): void {
    if (!this.state) return;

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
  undo(): boolean {
    if (!this.state || this.state.undoStack.length === 0) {
      return false;
    }

    // Save current state to redo stack
    const current = JSON.parse(JSON.stringify(this.state.graph));
    this.state.redoStack.push(current);

    // Restore previous state
    this.state.graph = this.state.undoStack.pop()!;
    this.state.isDirty = true;
    this.notifyChange();

    return true;
  }

  /**
   * Redo the last undone change
   */
  redo(): boolean {
    if (!this.state || this.state.redoStack.length === 0) {
      return false;
    }

    // Save current state to undo stack
    const current = JSON.parse(JSON.stringify(this.state.graph));
    this.state.undoStack.push(current);

    // Restore redo state
    this.state.graph = this.state.redoStack.pop()!;
    this.state.isDirty = true;
    this.notifyChange();

    return true;
  }

  /**
   * Check if undo is available
   */
  canUndo(): boolean {
    return (this.state?.undoStack.length ?? 0) > 0;
  }

  /**
   * Check if redo is available
   */
  canRedo(): boolean {
    return (this.state?.redoStack.length ?? 0) > 0;
  }

  // ==========================================================================
  // Validation
  // ==========================================================================

  /**
   * Validate the current flow
   */
  async validate(): Promise<import("../domain.js").ValidationData> {
    if (!this.state) {
      throw new Error("No flow loaded");
    }

    return flowStudioApi.validateFlow(this.state.flowKey);
  }

  /**
   * Compile the flow to output formats for a specific step
   *
   * @param stepId - The step ID to compile. Required.
   * @param runId - Optional run ID for context.
   */
  async compile(stepId: string, runId?: string): Promise<import("../api/client.js").CompiledFlow> {
    if (!this.state) {
      throw new Error("No flow loaded");
    }

    return flowStudioApi.compileFlow(this.state.flowKey, stepId, runId);
  }

  // ==========================================================================
  // Auto-save
  // ==========================================================================

  /**
   * Start auto-save timer
   */
  private startAutoSave(): void {
    if (this.autoSaveTimer) {
      clearInterval(this.autoSaveTimer);
    }

    this.autoSaveTimer = setInterval(async () => {
      if (this.state?.isDirty && !this.state.isSaving) {
        try {
          await this.save();
        } catch (err) {
          console.error("Auto-save failed", err);
        }
      }
    }, this.options.autoSaveInterval);
  }

  /**
   * Stop auto-save timer
   */
  stopAutoSave(): void {
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
  private async reloadGraph(): Promise<void> {
    if (!this.state) return;

    const response = await flowStudioApi.getFlow(this.state.flowKey);
    this.state.graph = response.data;
    this.state.etag = response.etag;
  }

  /**
   * Notify change listeners
   */
  private notifyChange(): void {
    if (this.state && this.options.onChange) {
      this.options.onChange(this.state);
    }
  }

  /**
   * Destroy the editor and clean up
   */
  destroy(): void {
    this.stopAutoSave();
    this.state = null;
  }
}

// ============================================================================
// Factory Function
// ============================================================================

/**
 * Create a new flow editor instance
 */
export function createFlowEditor(options?: FlowEditorOptions): FlowEditor {
  return new FlowEditor(options);
}
