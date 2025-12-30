import type { FlowKey, StepReceipt, ArtifactEntry } from "../domain.js";
/**
 * Flow completion status
 */
export type FlowCompletionStatus = "VERIFIED" | "UNVERIFIED" | "BLOCKED" | "UNKNOWN";
/**
 * MacroNavigator routing decision
 */
export interface RoutingDecision {
    /** Target flow key */
    targetFlow: FlowKey | null;
    /** Decision type */
    decision: "advance" | "bounce" | "terminate";
    /** Human-readable reason */
    reason: string;
    /** Whether this is a bounce-back */
    isBounce: boolean;
    /** Bounce target flow if bouncing */
    bounceTarget?: FlowKey;
}
/**
 * Boundary review data for a completed flow
 */
export interface BoundaryReviewData {
    /** Flow that just completed */
    flowKey: FlowKey;
    /** Flow title for display */
    flowTitle: string;
    /** Overall flow completion status */
    status: FlowCompletionStatus;
    /** Number of assumptions made during this flow */
    assumptionsCount: number;
    /** Number of decisions made during this flow */
    decisionsCount: number;
    /** Key artifacts produced */
    artifacts: ArtifactEntry[];
    /** MacroNavigator routing decision (if any) */
    routingDecision?: RoutingDecision;
    /** Completion timestamp */
    completedAt: string;
    /** Total duration in seconds */
    durationSeconds?: number;
    /** Step receipts for detailed info */
    receipts?: StepReceipt[];
    /** Any blocking issues */
    blockingIssues?: string[];
    /** Any warnings */
    warnings?: string[];
    /** Confidence score from boundary review API (0-100) */
    confidenceScore?: number;
}
/**
 * User decision from boundary review
 */
export type BoundaryReviewDecision = "approve" | "pause" | "cancel";
/**
 * Options for BoundaryReview component
 */
export interface BoundaryReviewOptions {
    /** Container element to append panel to (defaults to document.body) */
    container?: HTMLElement;
    /** Callback when panel is closed */
    onClose?: () => void;
    /** Callback when user approves and continues */
    onApprove?: (flowKey: FlowKey) => void;
    /** Callback when user pauses for review */
    onPause?: (flowKey: FlowKey) => void;
}
/**
 * Boundary Review panel for flow completion summaries.
 *
 * This is the "human review at flow boundary" feature. Shows:
 * - Flow completion status
 * - Counts of assumptions and decisions
 * - Key artifacts produced
 * - Routing decision
 * - Action buttons
 */
export declare class BoundaryReview {
    private panel;
    private focusManager;
    private options;
    private resolvePromise;
    private currentData;
    constructor(options?: BoundaryReviewOptions);
    /**
     * Show the boundary review panel for a completed flow.
     *
     * @param data - The boundary review data to display
     * @returns Promise resolving to user's decision
     */
    show(data: BoundaryReviewData): Promise<BoundaryReviewDecision>;
    /**
     * Close the panel and return a decision
     */
    close(decision?: BoundaryReviewDecision): void;
    /**
     * Destroy the panel and clean up
     */
    destroy(): void;
    /**
     * Check if panel is currently visible
     */
    isVisible(): boolean;
    /**
     * Get current data
     */
    getData(): BoundaryReviewData | null;
    /**
     * Render the boundary review panel
     */
    private render;
    /**
     * Render summary section with counts
     */
    private renderSummarySection;
    /**
     * Render artifacts section
     */
    private renderArtifactsSection;
    /**
     * Render routing decision section
     */
    private renderRoutingSection;
    /**
     * Render issues section (blocking issues and warnings)
     */
    private renderIssuesSection;
    /**
     * Render action buttons
     */
    private renderActions;
    /**
     * Format duration in human-readable format
     */
    private formatDuration;
    /**
     * Inject component styles
     */
    private injectStyles;
    /**
     * Attach event listeners
     */
    private attachEventListeners;
}
/**
 * Create a new BoundaryReview instance
 */
export declare function createBoundaryReview(options?: BoundaryReviewOptions): BoundaryReview;
/**
 * Extract BoundaryReviewData from a completed flow's data.
 * This is a helper for wiring up the component.
 */
export declare function extractBoundaryReviewData(flowKey: FlowKey, flowTitle: string, status: FlowCompletionStatus, artifacts: ArtifactEntry[], options?: {
    assumptionsCount?: number;
    decisionsCount?: number;
    routingDecision?: RoutingDecision;
    durationSeconds?: number;
    blockingIssues?: string[];
    warnings?: string[];
    receipts?: StepReceipt[];
    confidenceScore?: number;
}): BoundaryReviewData;
/**
 * CSS class names used by this component:
 *
 * .boundary-review-overlay - Main overlay container
 * .boundary-review-overlay.boundary-review--closing - Closing animation
 * .boundary-review-panel - Panel content container
 * .boundary-review__header - Header with status and title
 * .boundary-review__header-left - Left side of header
 * .boundary-review__status-icon - Status icon circle
 * .boundary-review__header-text - Title and subtitle container
 * .boundary-review__title - Main title
 * .boundary-review__subtitle - Status text
 * .boundary-review__close - Close button
 * .boundary-review__body - Scrollable body content
 * .boundary-review__section - Section container
 * .boundary-review__section-title - Section header
 * .boundary-review__metrics - Metrics grid
 * .boundary-review__metric - Individual metric box
 * .boundary-review__metric-value - Metric number
 * .boundary-review__metric-label - Metric description
 * .boundary-review__artifact-table - Artifacts table
 * .boundary-review__artifact-status - Status column
 * .boundary-review__artifact-path - Path column
 * .boundary-review__badge - Badge pill
 * .boundary-review__badge--required - Required badge variant
 * .boundary-review__more - "More items" text
 * .boundary-review__routing - Routing decision box
 * .boundary-review__routing-header - Routing header with icon
 * .boundary-review__routing-icon - Direction icon
 * .boundary-review__routing-target - Target flow text
 * .boundary-review__routing-reason - Reason text
 * .boundary-review__issues-group - Issues group container
 * .boundary-review__issues-title - Issues section title
 * .boundary-review__issues-title--blocking - Blocking issues variant
 * .boundary-review__issues-title--warning - Warning variant
 * .boundary-review__issues-list - Issues list
 * .boundary-review__issue - Individual issue item
 * .boundary-review__issue--blocking - Blocking issue variant
 * .boundary-review__issue--warning - Warning variant
 * .boundary-review__issue-icon - Issue icon
 * .boundary-review__footer - Footer with actions
 * .boundary-review__actions - Action buttons container
 * .boundary-review__btn - Button base class
 * .boundary-review__btn--primary - Primary (approve) button
 * .boundary-review__btn--secondary - Secondary (pause) button
 * .boundary-review__btn--warning - Warning button
 * .boundary-review__action-hint - Hint text below buttons
 */
