// swarm/tools/flow_studio_ui/src/selection.ts
// Unified selection management for Flow Studio
//
// This module provides a single entry point for all selection operations:
// - Graph node clicks
// - Search result selection
// - Keyboard navigation
// - Tour step navigation
// - URL deep links
//
// All paths go through selectNode() to ensure consistent behavior.

import { state, setSelectedNode, clearSelectedNode } from "./state.js";
import type { FlowKey, NodeData, NodeType } from "./domain.js";

// ============================================================================
// Module configuration - callbacks set by consumer
// ============================================================================

interface SelectionCallbacks {
  setActiveFlow?: (flowKey: FlowKey, force?: boolean) => Promise<void>;
  showStepDetails?: (data: NodeData) => void;
  showAgentDetails?: (data: NodeData) => void;
  showArtifactDetails?: (data: NodeData) => void;
  showEmptyState?: () => void;
  updateURL?: () => void;
  updateOutlineSelection?: (nodeId: string | null) => void;
  /** Called when a step is selected - for updating inventory counts delta display */
  onStepSelected?: (flowKey: FlowKey | null, stepId: string | null) => void;
}

let _callbacks: SelectionCallbacks = {};

/**
 * Configure callbacks for the selection module.
 */
export function configure(callbacks: SelectionCallbacks): void {
  _callbacks = { ..._callbacks, ...callbacks };
}

// ============================================================================
// Unified Selection
// ============================================================================

/**
 * Select a node by ID. This is the single entry point for all selection.
 *
 * Handles:
 * - Updating state.selectedNodeId
 * - Selecting the Cytoscape node (if graph is ready)
 * - Showing the appropriate details panel
 * - Updating the URL for deep linking
 * - Updating the outline tree selection
 *
 * @param nodeId - Full node ID (e.g., "step:build:1", "agent:code-implementer")
 * @param options - Configuration for selection behavior
 */
export async function selectNode(
  nodeId: string | null,
  options: {
    /** Flow to switch to before selecting (if different from current) */
    flowKey?: FlowKey;
    /** Force flow switch even if already on that flow */
    forceFlowSwitch?: boolean;
    /** Skip URL update (for URL-initiated selections to avoid loops) */
    skipUrlUpdate?: boolean;
    /** Fit the graph to show the selected node */
    fitGraph?: boolean;
    /** Node data if already known (avoids re-fetching from Cytoscape) */
    nodeData?: NodeData;
  } = {}
): Promise<void> {
  const {
    flowKey,
    forceFlowSwitch = false,
    skipUrlUpdate = false,
    fitGraph = true,
    nodeData
  } = options;

  // Handle null selection (clear)
  if (!nodeId) {
    clearSelectedNode();
    if (_callbacks.showEmptyState) {
      _callbacks.showEmptyState();
    }
    if (_callbacks.updateURL && !skipUrlUpdate) {
      _callbacks.updateURL();
    }
    return;
  }

  // Switch flow if needed
  if (flowKey && _callbacks.setActiveFlow) {
    if (flowKey !== state.currentFlowKey || forceFlowSwitch) {
      await _callbacks.setActiveFlow(flowKey, forceFlowSwitch);
      // Wait for graph to render
      await waitForGraph(300);
    }
  }

  // Get node data
  let data = nodeData;
  if (!data && state.cy) {
    const node = state.cy.getElementById(nodeId);
    if (node && typeof node.data === "function") {
      data = node.data() as NodeData;
    }
  }

  if (!data) {
    console.warn(`selectNode: Could not find node data for ${nodeId}`);
    return;
  }

  // Update state
  setSelectedNode(nodeId, data.type as NodeType);

  // Select in Cytoscape graph
  if (state.cy) {
    const node = state.cy.getElementById(nodeId);
    if (node) {
      if (fitGraph) {
        state.cy.fit(50);
      }
      node.select();
    }
  }

  // Show details panel
  showNodeDetails(data);

  // Update URL
  if (_callbacks.updateURL && !skipUrlUpdate) {
    _callbacks.updateURL();
  }

  // Update outline selection
  if (_callbacks.updateOutlineSelection) {
    _callbacks.updateOutlineSelection(nodeId);
  }
}

/**
 * Select a step by flow key and step ID.
 * Convenience method for common use case.
 */
export async function selectStep(
  flowKey: FlowKey,
  stepId: string,
  options: { skipUrlUpdate?: boolean; fitGraph?: boolean } = {}
): Promise<void> {
  const nodeId = `step:${flowKey}:${stepId}`;
  await selectNode(nodeId, {
    flowKey,
    ...options
  });
}

/**
 * Select an agent by key.
 * Optionally specify a flow to show the agent in.
 */
export async function selectAgent(
  agentKey: string,
  flowKey?: FlowKey,
  options: { skipUrlUpdate?: boolean; fitGraph?: boolean } = {}
): Promise<void> {
  const nodeId = `agent:${agentKey}`;
  await selectNode(nodeId, {
    flowKey,
    ...options
  });
}

/**
 * Clear the current selection.
 */
export function clearSelection(): void {
  clearSelectedNode();
  if (state.cy) {
    state.cy.elements().forEach(ele => {
      if (typeof (ele as unknown as { unselect: () => void }).unselect === "function") {
        (ele as unknown as { unselect: () => void }).unselect();
      }
    });
  }
  if (_callbacks.showEmptyState) {
    _callbacks.showEmptyState();
  }
  if (_callbacks.updateURL) {
    _callbacks.updateURL();
  }
}

// ============================================================================
// Helpers
// ============================================================================

/**
 * Show the appropriate details panel for a node.
 */
function showNodeDetails(data: NodeData): void {
  if (data.type === "step" && _callbacks.showStepDetails) {
    _callbacks.showStepDetails(data);
    // Notify about step selection for inventory counts delta display
    if (_callbacks.onStepSelected && data.flow && data.step_id) {
      _callbacks.onStepSelected(data.flow, data.step_id);
    }
  } else if (data.type === "agent" && _callbacks.showAgentDetails) {
    _callbacks.showAgentDetails(data);
    // Clear step selection when switching to agent
    if (_callbacks.onStepSelected) {
      _callbacks.onStepSelected(null, null);
    }
  } else if (data.type === "artifact" && _callbacks.showArtifactDetails) {
    _callbacks.showArtifactDetails(data);
    // Clear step selection when switching to artifact
    if (_callbacks.onStepSelected) {
      _callbacks.onStepSelected(null, null);
    }
  }
}

/**
 * Wait for the graph to be ready after a flow switch.
 */
function waitForGraph(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms));
}

/**
 * Parse a step query param into flow key and step ID.
 * Format: "flow:stepId" or just "stepId" (uses current flow)
 */
export function parseStepParam(stepParam: string): { flowKey?: FlowKey; stepId: string } {
  if (stepParam.includes(":")) {
    const [flowKey, stepId] = stepParam.split(":", 2);
    return { flowKey: flowKey as FlowKey, stepId };
  }
  return { stepId: stepParam };
}

/**
 * Get the current selection info for URL serialization.
 */
export function getSelectionForUrl(): { step?: string; agent?: string } {
  if (!state.selectedNodeId || !state.selectedNodeType) {
    return {};
  }

  if (state.selectedNodeType === "step") {
    // Extract step ID from "step:flow:stepId"
    const parts = state.selectedNodeId.split(":");
    if (parts.length >= 3) {
      return { step: parts.slice(2).join(":") };
    }
  } else if (state.selectedNodeType === "agent") {
    // Extract agent key from "agent:key"
    const parts = state.selectedNodeId.split(":");
    if (parts.length >= 2) {
      return { agent: parts.slice(1).join(":") };
    }
  }

  return {};
}
