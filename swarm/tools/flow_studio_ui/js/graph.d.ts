import type { FlowGraph, NodeData, CytoscapeInstance, CytoscapeNodeCollection, RenderGraphOptions, FocusNodeOptions } from "./domain.js";
/**
 * Initialize the Cytoscape graph instance.
 * Safe to call multiple times - returns existing instance if already initialized.
 */
export declare function initGraph(options?: RenderGraphOptions): CytoscapeInstance;
/**
 * Render a graph with the given nodes and edges.
 * Initializes Cytoscape if not already done.
 */
export declare function renderGraphCore(graph: FlowGraph, options?: RenderGraphOptions): CytoscapeInstance;
/**
 * Get the current Cytoscape instance.
 */
export declare function getCy(): CytoscapeInstance | null;
/**
 * Update the node click handler.
 * Useful when you need to change behavior after initialization.
 */
export declare function setNodeClickHandler(handler: (nodeData: NodeData) => void): void;
/**
 * Fit the graph view to a specific node with animation.
 */
export declare function focusNode(nodeId: string, options?: FocusNodeOptions): void;
/**
 * Get step nodes sorted by their order.
 */
export declare function getStepNodesSorted(): CytoscapeNodeCollection | [];
