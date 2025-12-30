interface MarkerCount {
    marker_type: string;
    label: string;
    count: number;
}
interface FlowMarkerCounts {
    flow_key: string;
    counts: Record<string, number>;
    total: number;
}
interface StepMarkerCounts {
    flow_key: string;
    step_id: string;
    counts: Record<string, number>;
    total: number;
}
interface MarkerDelta {
    from_step: string;
    to_step: string;
    deltas: Record<string, number>;
    total_delta: number;
}
interface FactsSummaryResponse {
    run_id: string;
    total_facts: number;
    by_type: MarkerCount[];
    by_flow: FlowMarkerCounts[];
    by_step: StepMarkerCounts[];
    deltas: MarkerDelta[];
    errors: string[];
}
export declare function renderCompactInventory(data: FactsSummaryResponse): string;
export declare function renderInventoryPanel(data: FactsSummaryResponse): string;
/**
 * Load and cache facts summary for a run.
 * Uses monotonic request ID guard to prevent out-of-order UI renders
 * when multiple requests are in flight (e.g., under bursty SSE).
 */
export declare function loadFactsSummary(runId: string): Promise<FactsSummaryResponse | null>;
/**
 * Get the current cached facts data.
 */
export declare function getCurrentFactsData(): FactsSummaryResponse | null;
/**
 * Update the inventory panel in a container.
 */
export declare function updateInventoryPanel(container: HTMLElement, runId: string): Promise<void>;
/**
 * Update the compact inventory display in a container.
 */
export declare function updateCompactInventory(container: HTMLElement, runId: string): Promise<void>;
export declare function injectInventoryCSS(): void;
export {};
