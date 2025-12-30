import type { BoundaryReviewResponse, FlowKey } from "./domain.js";
export declare function renderBoundaryReviewPanel(data: BoundaryReviewResponse): string;
/**
 * Load and render boundary review for a run.
 * Uses monotonic request ID guard to prevent out-of-order UI renders
 * when multiple requests are in flight (e.g., under bursty SSE).
 */
export declare function loadBoundaryReview(runId: string, options?: {
    scope?: "flow" | "run";
    flowKey?: FlowKey;
}): Promise<BoundaryReviewResponse | null>;
/**
 * Get the current boundary review data.
 */
export declare function getCurrentBoundaryData(): BoundaryReviewResponse | null;
/**
 * Toggle the expanded state of the panel.
 */
export declare function toggleExpanded(): void;
/**
 * Set up event handlers for the boundary review panel.
 */
export declare function setupBoundaryReviewHandlers(container: HTMLElement): void;
/**
 * Update the boundary review panel in a container.
 */
export declare function updateBoundaryReviewPanel(container: HTMLElement, runId: string, options?: {
    scope?: "flow" | "run";
    flowKey?: FlowKey;
}): Promise<void>;
export declare function injectBoundaryReviewCSS(): void;
