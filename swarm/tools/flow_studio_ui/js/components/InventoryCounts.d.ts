/**
 * Count for a single marker type
 */
interface MarkerCount {
    marker_type: string;
    label: string;
    count: number;
}
/**
 * Flow marker counts
 */
interface FlowMarkerCounts {
    flow_key: string;
    counts: Record<string, number>;
    total: number;
}
/**
 * Step marker counts
 */
interface StepMarkerCounts {
    flow_key: string;
    step_id: string;
    counts: Record<string, number>;
    total: number;
}
/**
 * Delta between consecutive steps
 */
interface MarkerDelta {
    from_step: string;
    to_step: string;
    deltas: Record<string, number>;
    total_delta: number;
}
/**
 * Facts summary response from API
 */
export interface FactsSummaryResponse {
    run_id: string;
    total_facts: number;
    by_type: MarkerCount[];
    by_flow: FlowMarkerCounts[];
    by_step: StepMarkerCounts[];
    deltas: MarkerDelta[];
    errors: string[];
}
/**
 * Options for creating the inventory counts component
 */
export interface InventoryCountsOptions {
    /** Container element to render into */
    container: HTMLElement;
    /** Callback when a marker type is clicked */
    onTypeClick?: (markerType: string) => void;
    /** Callback when a flow is clicked */
    onFlowClick?: (flowKey: string) => void;
    /** Callback when a step is clicked */
    onStepClick?: (flowKey: string, stepId: string) => void;
}
/**
 * Inventory counts component for displaying marker statistics.
 *
 * Features:
 * - Horizontal bar showing counts per marker type
 * - Delta indicators (+3, -1) when counts change
 * - Expandable details view
 * - Click handlers for drilling down
 */
export declare class InventoryCounts {
    private container;
    private onTypeClick?;
    private onFlowClick?;
    private onStepClick?;
    private data;
    private isExpanded;
    private isLoading;
    private errorMessage;
    private selectedStep;
    private loadSeq;
    constructor(options: InventoryCountsOptions);
    /**
     * Load inventory counts for a run.
     * Uses monotonic request ID guard to prevent out-of-order UI renders
     * when multiple requests are in flight (e.g., under bursty SSE).
     */
    load(runId: string): Promise<void>;
    /**
     * Set data directly (for testing or pre-loaded data)
     */
    setData(data: FactsSummaryResponse): void;
    /**
     * Get the deltas for a specific step
     */
    getDeltasForStep(flowKey: string, stepId: string): Record<string, number> | null;
    /**
     * Render the component
     */
    render(): void;
    /**
     * Create loading state
     */
    private createLoadingState;
    /**
     * Create error state
     */
    private createErrorState;
    /**
     * Create empty state
     */
    private createEmptyState;
    /**
     * Create header with total and expand button
     */
    private createHeader;
    /**
     * Create the horizontal marker bar
     */
    private createMarkerBar;
    /**
     * Create expanded details view
     */
    private createExpandedDetails;
    /**
     * Set the selected step for delta highlighting
     */
    setSelectedStep(flowKey: string | null, stepId: string | null): void;
    /**
     * Toggle expanded state
     */
    toggleExpanded(): void;
    /**
     * Get current data
     */
    getData(): FactsSummaryResponse | null;
    /**
     * Check if component has data
     */
    hasData(): boolean;
    /**
     * Clear data and reset state
     */
    clear(): void;
    /**
     * Destroy the component
     */
    destroy(): void;
}
/**
 * Create and initialize an inventory counts component
 */
export declare function createInventoryCounts(container: HTMLElement, runId: string, options?: Omit<InventoryCountsOptions, "container">): Promise<InventoryCounts>;
export {};
/**
 * CSS class names used by this component:
 *
 * .inventory-counts - Main container
 * .inventory-counts__loading - Loading state container
 * .inventory-counts__spinner - Loading spinner
 * .inventory-counts__error - Error state container
 * .inventory-counts__error-icon - Error icon
 * .inventory-counts__empty - Empty state container
 * .inventory-counts__empty-text - Empty state text
 * .inventory-counts__header - Header section
 * .inventory-counts__title - Title text
 * .inventory-counts__total - Total count badge
 * .inventory-counts__expand-btn - Expand/collapse button
 * .inventory-counts__bar - Horizontal marker bar
 * .inventory-counts__item - Individual marker type item
 * .inventory-counts__icon - Marker type icon
 * .inventory-counts__count - Marker count number
 * .inventory-counts__delta - Delta indicator
 * .inventory-counts__delta--positive - Positive delta (+)
 * .inventory-counts__delta--negative - Negative delta (-)
 * .inventory-counts__details - Expanded details container
 * .inventory-counts__section - Details section
 * .inventory-counts__section-header - Section header
 * .inventory-counts__flow-list - Flow list container
 * .inventory-counts__flow-item - Individual flow item
 * .inventory-counts__flow-name - Flow name
 * .inventory-counts__flow-counts - Mini counts bar
 * .inventory-counts__flow-total - Flow total
 * .inventory-counts__mini-count - Mini count item
 * .inventory-counts__delta-list - Delta list container
 * .inventory-counts__delta-item - Individual delta item
 * .inventory-counts__delta-steps - Step transition text
 * .inventory-counts__delta-changes - Delta changes container
 * .inventory-counts__delta-change - Individual delta change
 * .inventory-counts__delta-change--positive - Positive change
 * .inventory-counts__delta-change--negative - Negative change
 */
