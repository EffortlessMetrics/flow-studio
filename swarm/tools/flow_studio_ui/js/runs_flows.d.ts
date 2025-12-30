import type { FlowKey, FlowDetail, Run, Flow, RunsFlowsCallbacks, FlowHealthStatus, FlowStatusData } from "./domain.js";
/**
 * Wisdom status for SDLC bar indicator.
 * - ok: wisdom exists, no regressions
 * - warning: wisdom exists, has warnings or non-blocking issues
 * - error: wisdom exists, has regressions
 * - unknown: no wisdom data available
 */
export type WisdomIndicatorStatus = "ok" | "warning" | "error" | "unknown";
/**
 * Show or hide the canvas empty state based on whether we have data.
 * Called when runs/flows are loaded or cleared.
 */
export declare function updateCanvasEmptyState(hasRuns: boolean): void;
/**
 * Configure callbacks for the runs/flows module.
 * Call this before using other functions to wire up UI interactions.
 */
export declare function configure(callbacks?: RunsFlowsCallbacks): void;
/**
 * Map flow status data to a simplified health status for sidebar display.
 * This provides a consistent mental model: ok, warning, error, unknown.
 *
 * @param flowData - The flow status data from the run summary, or undefined if no data
 * @returns FlowHealthStatus - The simplified health status
 */
export declare function getFlowHealthStatus(flowData: FlowStatusData | undefined): FlowHealthStatus;
/**
 * Load runs into the run selector and initialize state.currentRunId.
 * Also caches runs for compare selector and loads initial run status.
 */
export declare function loadRuns(): Promise<Run[]>;
/**
 * Load summary for current run and update SDLC + flow list + graph status.
 */
export declare function loadRunStatus(): Promise<void>;
/**
 * Update the compare run selector dropdown.
 */
export declare function updateCompareSelector(): void;
/**
 * Load comparison data between current and compare runs.
 */
export declare function loadComparison(): Promise<void>;
/**
 * Set comparison run and load comparison data.
 */
export declare function setCompareRun(runId: string | null): Promise<void>;
/**
 * Render comparison table HTML from state.comparisonData.
 */
export declare function renderComparisonTable(): string;
/**
 * Clear cached wisdom data (called when run changes).
 */
export declare function clearWisdomCache(): void;
/**
 * Update SDLC bar with run + comparison status.
 */
export declare function updateSDLCBar(): void;
/**
 * Update list items in the sidebar with status icons and tooltips.
 * Uses FlowHealthStatus for a consistent user-facing status model.
 */
export declare function updateFlowListStatus(): void;
/**
 * Load flows and populate the flow list sidebar.
 */
export declare function loadFlows(): Promise<Flow[]>;
/**
 * Mark active flow in sidebar and SDLC bar.
 */
export declare function markActiveFlow(flowKey: FlowKey): void;
/**
 * Update Cytoscape nodes with run status (step badges).
 */
export declare function updateGraphStatus(): void;
/**
 * Update Cytoscape nodes with teaching highlights.
 * When Teaching Mode is enabled, steps with teaching_highlight: true get
 * a visual emphasis (border color/style).
 *
 * @param detail - The flow detail containing step info with teaching_highlight
 */
export declare function updateGraphTeachingHighlights(detail: FlowDetail): void;
/**
 * Clear all teaching highlights from the graph.
 * Called when teaching mode is disabled.
 */
export declare function clearGraphTeachingHighlights(): void;
/**
 * Set the active flow, load its graph + detail, and refresh status overlays.
 */
export declare function setActiveFlow(flowKey: FlowKey, force?: boolean): Promise<void>;
/**
 * Refresh the current flow's graph (e.g., after view mode change).
 */
export declare function refreshCurrentFlow(): Promise<void>;
/**
 * Refresh all run-related state (run status, SDLC bar, flow list, graph).
 */
export declare function refreshRunState(): Promise<void>;
