import type { UIState, UIMode, ViewMode, FlowKey, StatusIcons, NodeType, FlowHealthStatus, FlowStatusMeta } from "./domain.js";
/**
 * Application state object. All mutable state lives here.
 */
export declare const state: UIState;
/**
 * Status icons used throughout the app
 */
export declare const STATUS_ICONS: StatusIcons;
/**
 * Flow health status metadata for sidebar display.
 * Maps FlowHealthStatus to icon and tooltip text.
 */
export declare const FLOW_STATUS_META: Record<FlowHealthStatus, FlowStatusMeta>;
/**
 * Flow key order - re-exported from generated constants
 */
export { FLOW_KEYS } from "./flow_constants.js";
/**
 * Set the current UI mode
 */
export declare function setMode(mode: UIMode): void;
/**
 * Set the current view mode
 */
export declare function setViewMode(view: ViewMode): void;
/**
 * Set the current run ID
 */
export declare function setCurrentRun(runId: string | null): void;
/**
 * Set the current flow key
 */
export declare function setCurrentFlow(flowKey: FlowKey | null): void;
/**
 * Set the comparison run ID
 */
export declare function setCompareRun(runId: string | null): void;
/**
 * Toggle the governance overlay
 */
export declare function setGovernanceOverlay(enabled: boolean): void;
/**
 * Set the selected node
 */
export declare function setSelectedNode(nodeId: string | null, nodeType: NodeType | null): void;
/**
 * Clear the selected node
 */
export declare function clearSelectedNode(): void;
