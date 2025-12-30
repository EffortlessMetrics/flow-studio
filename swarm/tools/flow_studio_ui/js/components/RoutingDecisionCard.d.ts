/**
 * Routing action types from the V3 routing model.
 */
export type RoutingAction = "advance" | "loop" | "detour" | "escalate" | "repeat" | "terminate";
/**
 * Routing candidate source types.
 */
export type RoutingSource = "graph_edge" | "fast_path" | "detour_catalog" | "extend_graph" | "navigator" | "deterministic_fallback";
/**
 * A candidate routing decision matching the Python dataclass.
 *
 * The candidate-set pattern: Python generates candidates from the graph,
 * Navigator intelligently chooses among them, Python validates and executes.
 */
export interface RoutingCandidate {
    /** Unique identifier for this candidate */
    candidate_id: string;
    /** The routing action (advance, loop, detour, escalate, repeat, terminate) */
    action: RoutingAction;
    /** Target node ID for advance/loop/detour */
    target_node: string | null;
    /** Human-readable explanation of why this is a candidate */
    reason: string;
    /** Priority score (0-100, higher = more likely default) */
    priority: number;
    /** Where this candidate came from */
    source: RoutingSource;
    /** References to evidence supporting this candidate */
    evidence_pointers: string[];
    /** Whether this is the default/suggested choice */
    is_default: boolean;
}
/**
 * Forensic verdict flags for detecting reward hacking.
 */
export interface ForensicVerdictFlags {
    /** Whether claims matched evidence */
    claim_verified: boolean;
    /** Confidence in the verdict (0.0-1.0) */
    confidence: number;
    /** Recommendation: TRUST, VERIFY, or REJECT */
    recommendation: "TRUST" | "VERIFY" | "REJECT";
    /** Specific patterns detected */
    reward_hacking_flags: string[];
    /** Count of discrepancies found */
    discrepancy_count?: number;
    /** Description of critical issue if present */
    critical_issue?: string;
}
/**
 * Full routing decision data for visualization.
 */
export interface RoutingDecisionData {
    /** ID of the chosen candidate */
    chosen_candidate_id: string;
    /** All candidates that were considered */
    candidates: RoutingCandidate[];
    /** Source that made the routing decision */
    routing_source: RoutingSource;
    /** Forensic verdict if present (Semantic Handoff Injection) */
    forensic_verdict?: ForensicVerdictFlags;
    /** Timestamp of the decision */
    timestamp?: string;
    /** Current iteration number */
    iteration?: number;
    /** Current flow key */
    flow_key?: string;
    /** Current step ID */
    step_id?: string;
}
/**
 * Options for RoutingDecisionCard component.
 */
export interface RoutingDecisionCardOptions {
    /** Container element to render into */
    container?: HTMLElement;
    /** Whether to start with rejected candidates expanded */
    expandedByDefault?: boolean;
    /** Callback when a candidate is clicked */
    onCandidateClick?: (candidate: RoutingCandidate) => void;
}
/**
 * Routing Decision Card for visualizing Navigator routing choices.
 *
 * Features:
 * - Routing source badge (navigator/fast_path/deterministic_fallback)
 * - Chosen candidate highlighted with green border
 * - Rejected candidates in collapsed section
 * - Default marker on the default candidate
 * - Forensic verdict warning flags if present
 * - Priority scores displayed
 */
export declare class RoutingDecisionCard {
    private container;
    private card;
    private options;
    private data;
    private isExpanded;
    constructor(options?: RoutingDecisionCardOptions);
    /**
     * Render the routing decision card with the given data.
     */
    render(data: RoutingDecisionData, container?: HTMLElement): HTMLElement;
    /**
     * Update the card with new data.
     */
    update(data: RoutingDecisionData): void;
    /**
     * Get the current data.
     */
    getData(): RoutingDecisionData | null;
    /**
     * Get the card element.
     */
    getElement(): HTMLElement | null;
    /**
     * Destroy the card and clean up.
     */
    destroy(): void;
    /**
     * Build the complete card HTML.
     */
    private buildCardHTML;
    /**
     * Build the routing source badge.
     */
    private buildSourceBadge;
    /**
     * Build meta information (iteration, flow, step).
     */
    private buildMetaInfo;
    /**
     * Build forensic verdict section if present.
     */
    private buildForensicVerdict;
    /**
     * Build the chosen candidate section.
     */
    private buildChosenCandidate;
    /**
     * Build the rejected candidates section (collapsible).
     */
    private buildRejectedCandidates;
    /**
     * Build a single candidate card.
     */
    private buildCandidateCard;
    /**
     * Inject component styles.
     */
    private injectStyles;
    /**
     * Attach event listeners.
     */
    private attachEventListeners;
    /**
     * Toggle the rejected candidates section.
     */
    private toggleRejectedSection;
}
/**
 * Create a new RoutingDecisionCard instance.
 */
export declare function createRoutingDecisionCard(options?: RoutingDecisionCardOptions): RoutingDecisionCard;
/**
 * CSS class names used by this component:
 *
 * .routing-decision-card - Main container
 * .routing-card__header - Header with source badge and meta
 * .routing-card__source-badge - Routing source badge
 * .routing-card__meta - Meta info container
 * .routing-card__meta-item - Individual meta item
 * .routing-card__section - Section container
 * .routing-card__section-title - Section title
 * .routing-card__empty - Empty state text
 * .routing-card__forensic - Forensic verdict container
 * .routing-card__forensic--warning - Warning state
 * .routing-card__forensic--error - Error state
 * .routing-card__forensic-header - Forensic header
 * .routing-card__forensic-icon - Forensic status icon
 * .routing-card__forensic-title - Forensic title text
 * .routing-card__forensic-confidence - Confidence percentage
 * .routing-card__forensic-flags - Flags list
 * .routing-card__forensic-flag - Individual flag item
 * .routing-card__forensic-flag-icon - Flag icon
 * .routing-card__forensic-critical - Critical issue text
 * .routing-card__candidate - Candidate card
 * .routing-card__candidate--chosen - Chosen candidate (green border)
 * .routing-card__candidate--default - Default candidate
 * .routing-card__candidate-header - Candidate header row
 * .routing-card__action-badge - Action type badge
 * .routing-card__target - Target node text
 * .routing-card__priority - Priority score badge
 * .routing-card__default-badge - Default marker badge
 * .routing-card__candidate-reason - Reason text
 * .routing-card__candidate-meta - Candidate meta info
 * .routing-card__candidate-source - Source text
 * .routing-card__evidence - Evidence pointers container
 * .routing-card__evidence-label - Evidence label
 * .routing-card__evidence-item - Evidence pointer item
 * .routing-card__evidence-more - More evidence text
 * .routing-card__rejected - Rejected candidates section
 * .routing-card__rejected--expanded - Expanded state
 * .routing-card__rejected-toggle - Toggle button
 * .routing-card__rejected-arrow - Expand/collapse arrow
 * .routing-card__rejected-content - Collapsed content
 */
