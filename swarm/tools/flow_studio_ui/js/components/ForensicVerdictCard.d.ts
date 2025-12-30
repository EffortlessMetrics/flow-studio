/**
 * Verdict type for forensic verification
 */
export type ForensicVerdictType = "PASS" | "REJECT" | "INCONCLUSIVE";
/**
 * Claim vs evidence comparison entry
 */
export interface ClaimEvidenceComparison {
    /** What the agent claimed to do */
    claim: string;
    /** What forensics actually found */
    evidence: string;
    /** Whether claim matches evidence */
    match: boolean;
}
/**
 * Forensic verdict data structure
 */
export interface ForensicVerdict {
    /** Overall verdict: PASS, REJECT, or INCONCLUSIVE */
    verdict: ForensicVerdictType;
    /** Number of discrepancies found between claims and reality */
    discrepancy_count: number;
    /** List of critical issues that must be addressed */
    critical_issues: string[];
    /** Reward hacking flags - patterns indicating gaming of metrics */
    reward_hacking_flags: string[];
    /** Detailed claim vs evidence comparisons */
    claim_vs_evidence: ClaimEvidenceComparison[];
}
/**
 * Options for creating the forensic verdict card
 */
export interface ForensicVerdictCardOptions {
    /** Container element to render into */
    container: HTMLElement;
    /** Optional callback when a comparison item is clicked */
    onComparisonClick?: (comparison: ClaimEvidenceComparison, index: number) => void;
    /** Optional callback when verdict badge is clicked */
    onVerdictClick?: (verdict: ForensicVerdictType) => void;
    /** Whether to start expanded (default: false) */
    startExpanded?: boolean;
}
/**
 * Forensic Verdict Card component for displaying forensic analysis results.
 *
 * Features:
 * - Verdict badge with color coding (green/red/yellow)
 * - Discrepancy count display
 * - Critical issues list with warning icons
 * - Reward hacking flags (prominently displayed if any)
 * - Expandable claim vs evidence comparisons
 * - Visual indicators for mismatches
 */
export declare class ForensicVerdictCard {
    private container;
    private onComparisonClick?;
    private onVerdictClick?;
    private data;
    private isExpanded;
    private isLoading;
    private errorMessage;
    constructor(options: ForensicVerdictCardOptions);
    /**
     * Set forensic verdict data and render
     */
    setData(data: ForensicVerdict): void;
    /**
     * Set loading state
     */
    setLoading(loading: boolean): void;
    /**
     * Set error message
     */
    setError(message: string): void;
    /**
     * Get current data
     */
    getData(): ForensicVerdict | null;
    /**
     * Check if component has data
     */
    hasData(): boolean;
    /**
     * Clear data and reset state
     */
    clear(): void;
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
     * Create header with verdict badge
     */
    private createHeader;
    /**
     * Create verdict badge with appropriate styling
     */
    private createVerdictBadge;
    /**
     * Create summary section with discrepancy count
     */
    private createSummarySection;
    /**
     * Create reward hacking flags section (prominently displayed)
     */
    private createRewardHackingSection;
    /**
     * Create critical issues section
     */
    private createCriticalIssuesSection;
    /**
     * Create expandable claim vs evidence section
     */
    private createClaimEvidenceSection;
    /**
     * Create a single claim vs evidence comparison item
     */
    private createComparisonItem;
    /**
     * Inject component styles
     */
    private injectStyles;
    /**
     * Toggle expanded state
     */
    toggleExpanded(): void;
    /**
     * Set expanded state
     */
    setExpanded(expanded: boolean): void;
    /**
     * Check if expanded
     */
    isExpandedState(): boolean;
    /**
     * Destroy the component
     */
    destroy(): void;
}
/**
 * Create a forensic verdict card with initial data
 */
export declare function createForensicVerdictCard(container: HTMLElement, data?: ForensicVerdict, options?: Omit<ForensicVerdictCardOptions, "container">): ForensicVerdictCard;
/**
 * CSS class names used by this component:
 *
 * .forensic-verdict-card - Main container
 * .forensic-verdict-card__loading - Loading state container
 * .forensic-verdict-card__spinner - Loading spinner
 * .forensic-verdict-card__error - Error state container
 * .forensic-verdict-card__error-icon - Error icon
 * .forensic-verdict-card__empty - Empty state container
 * .forensic-verdict-card__empty-text - Empty state text
 * .forensic-verdict-card__header - Header section
 * .forensic-verdict-card__title - Title text
 * .forensic-verdict-card__verdict-badge - Verdict badge button
 * .forensic-verdict-card__verdict-icon - Icon in verdict badge
 * .forensic-verdict-card__verdict-text - Text in verdict badge
 * .forensic-verdict-card__summary - Summary metrics grid
 * .forensic-verdict-card__metric - Individual metric box
 * .forensic-verdict-card__metric-value - Metric number
 * .forensic-verdict-card__metric-value--success - Green metric
 * .forensic-verdict-card__metric-value--warning - Yellow metric
 * .forensic-verdict-card__metric-value--error - Red metric
 * .forensic-verdict-card__metric-value--severe - Dark red metric
 * .forensic-verdict-card__metric-label - Metric description
 * .forensic-verdict-card__section - Section container
 * .forensic-verdict-card__section--severe - Severe (reward hacking) section
 * .forensic-verdict-card__section--critical - Critical issues section
 * .forensic-verdict-card__section-header - Section header
 * .forensic-verdict-card__section-header--severe - Severe header
 * .forensic-verdict-card__section-header--critical - Critical header
 * .forensic-verdict-card__section-header--expandable - Expandable header
 * .forensic-verdict-card__section-header-left - Left side of header
 * .forensic-verdict-card__section-icon - Section icon
 * .forensic-verdict-card__section-title - Section title
 * .forensic-verdict-card__section-description - Section description text
 * .forensic-verdict-card__flag-list - Reward hacking flags list
 * .forensic-verdict-card__flag-item - Individual flag item
 * .forensic-verdict-card__flag-icon - Flag warning icon
 * .forensic-verdict-card__flag-text - Flag text
 * .forensic-verdict-card__issue-list - Critical issues list
 * .forensic-verdict-card__issue-item - Individual issue item
 * .forensic-verdict-card__issue-icon - Issue warning icon
 * .forensic-verdict-card__issue-text - Issue text
 * .forensic-verdict-card__claims-summary - Claims match/mismatch summary
 * .forensic-verdict-card__claims-match - Match count (green)
 * .forensic-verdict-card__claims-mismatch - Mismatch count (red)
 * .forensic-verdict-card__expand-btn - Expand/collapse button
 * .forensic-verdict-card__claims-content - Expandable claims container
 * .forensic-verdict-card__comparison - Comparison item container
 * .forensic-verdict-card__comparison--match - Matching comparison (green)
 * .forensic-verdict-card__comparison--mismatch - Mismatching comparison (red)
 * .forensic-verdict-card__comparison-indicator - Match/mismatch indicator
 * .forensic-verdict-card__match-icon - Checkmark icon
 * .forensic-verdict-card__mismatch-icon - X icon
 * .forensic-verdict-card__comparison-content - Comparison text content
 * .forensic-verdict-card__comparison-row - Claim or evidence row
 * .forensic-verdict-card__comparison-label - "Claim:" or "Evidence:" label
 * .forensic-verdict-card__comparison-text - Claim or evidence text
 */
