import type { FlowKey, NodeData } from "./domain.js";
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
/**
 * Configure callbacks for the selection module.
 */
export declare function configure(callbacks: SelectionCallbacks): void;
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
export declare function selectNode(nodeId: string | null, options?: {
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
}): Promise<void>;
/**
 * Select a step by flow key and step ID.
 * Convenience method for common use case.
 */
export declare function selectStep(flowKey: FlowKey, stepId: string, options?: {
    skipUrlUpdate?: boolean;
    fitGraph?: boolean;
}): Promise<void>;
/**
 * Select an agent by key.
 * Optionally specify a flow to show the agent in.
 */
export declare function selectAgent(agentKey: string, flowKey?: FlowKey, options?: {
    skipUrlUpdate?: boolean;
    fitGraph?: boolean;
}): Promise<void>;
/**
 * Clear the current selection.
 */
export declare function clearSelection(): void;
/**
 * Parse a step query param into flow key and step ID.
 * Format: "flow:stepId" or just "stepId" (uses current flow)
 */
export declare function parseStepParam(stepParam: string): {
    flowKey?: FlowKey;
    stepId: string;
};
/**
 * Get the current selection info for URL serialization.
 */
export declare function getSelectionForUrl(): {
    step?: string;
    agent?: string;
};
export {};
