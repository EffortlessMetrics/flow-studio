// swarm/tools/flow_studio_ui/src/components/ForensicVerdictCard.ts
// Forensic Verdict Card component for Flow Studio
//
// Displays forensic analysis results from the Forensics Over Narrative system.
// Shows verdict, discrepancy counts, critical issues, reward hacking flags,
// and claim vs evidence comparisons.
//
// NO filesystem operations - all data flows through the API.
import { escapeHtml } from "../utils.js";
// ============================================================================
// Constants
// ============================================================================
/** Verdict styling configuration */
const VERDICT_STYLES = {
    PASS: {
        color: "#166534",
        bgColor: "#dcfce7",
        borderColor: "#22c55e",
        icon: "\u2705" // green checkmark
    },
    REJECT: {
        color: "#991b1b",
        bgColor: "#fee2e2",
        borderColor: "#ef4444",
        icon: "\u274c" // red X
    },
    INCONCLUSIVE: {
        color: "#92400e",
        bgColor: "#fef3c7",
        borderColor: "#f59e0b",
        icon: "\u2753" // question mark
    }
};
// ============================================================================
// ForensicVerdictCard Component
// ============================================================================
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
export class ForensicVerdictCard {
    constructor(options) {
        this.data = null;
        this.isLoading = false;
        this.errorMessage = null;
        this.container = options.container;
        this.onComparisonClick = options.onComparisonClick;
        this.onVerdictClick = options.onVerdictClick;
        this.isExpanded = options.startExpanded ?? false;
    }
    // ==========================================================================
    // Data Management
    // ==========================================================================
    /**
     * Set forensic verdict data and render
     */
    setData(data) {
        this.data = data;
        this.isLoading = false;
        this.errorMessage = null;
        this.render();
    }
    /**
     * Set loading state
     */
    setLoading(loading) {
        this.isLoading = loading;
        this.render();
    }
    /**
     * Set error message
     */
    setError(message) {
        this.errorMessage = message;
        this.isLoading = false;
        this.render();
    }
    /**
     * Get current data
     */
    getData() {
        return this.data;
    }
    /**
     * Check if component has data
     */
    hasData() {
        return this.data !== null;
    }
    /**
     * Clear data and reset state
     */
    clear() {
        this.data = null;
        this.isExpanded = false;
        this.errorMessage = null;
        this.render();
    }
    // ==========================================================================
    // Rendering
    // ==========================================================================
    /**
     * Render the component
     */
    render() {
        this.container.innerHTML = "";
        this.container.className = "forensic-verdict-card";
        this.container.setAttribute("data-uiid", "flow_studio.forensic_verdict.card");
        // Inject styles if not already present
        this.injectStyles();
        if (this.isLoading) {
            this.container.appendChild(this.createLoadingState());
            return;
        }
        if (this.errorMessage) {
            this.container.appendChild(this.createErrorState());
            return;
        }
        if (!this.data) {
            this.container.appendChild(this.createEmptyState());
            return;
        }
        // Main content
        this.container.appendChild(this.createHeader());
        this.container.appendChild(this.createSummarySection());
        // Reward hacking flags (prominently displayed if any)
        if (this.data.reward_hacking_flags.length > 0) {
            this.container.appendChild(this.createRewardHackingSection());
        }
        // Critical issues
        if (this.data.critical_issues.length > 0) {
            this.container.appendChild(this.createCriticalIssuesSection());
        }
        // Expandable claim vs evidence section
        if (this.data.claim_vs_evidence.length > 0) {
            this.container.appendChild(this.createClaimEvidenceSection());
        }
    }
    /**
     * Create loading state
     */
    createLoadingState() {
        const div = document.createElement("div");
        div.className = "forensic-verdict-card__loading";
        div.innerHTML = `
      <div class="forensic-verdict-card__spinner"></div>
      <span>Analyzing forensic evidence...</span>
    `;
        return div;
    }
    /**
     * Create error state
     */
    createErrorState() {
        const div = document.createElement("div");
        div.className = "forensic-verdict-card__error";
        div.innerHTML = `
      <span class="forensic-verdict-card__error-icon">\u26A0</span>
      <span>${escapeHtml(this.errorMessage || "Unknown error")}</span>
    `;
        return div;
    }
    /**
     * Create empty state
     */
    createEmptyState() {
        const div = document.createElement("div");
        div.className = "forensic-verdict-card__empty";
        div.innerHTML = `
      <span class="forensic-verdict-card__empty-text">No forensic verification data available</span>
    `;
        return div;
    }
    /**
     * Create header with verdict badge
     */
    createHeader() {
        const header = document.createElement("div");
        header.className = "forensic-verdict-card__header";
        const title = document.createElement("span");
        title.className = "forensic-verdict-card__title";
        title.textContent = "Forensic Verification";
        const verdictBadge = this.createVerdictBadge();
        header.appendChild(title);
        header.appendChild(verdictBadge);
        return header;
    }
    /**
     * Create verdict badge with appropriate styling
     */
    createVerdictBadge() {
        const verdict = this.data.verdict;
        const style = VERDICT_STYLES[verdict];
        const badge = document.createElement("button");
        badge.className = "forensic-verdict-card__verdict-badge";
        badge.setAttribute("data-uiid", "flow_studio.forensic_verdict.badge");
        badge.setAttribute("data-verdict", verdict);
        badge.style.backgroundColor = style.bgColor;
        badge.style.borderColor = style.borderColor;
        badge.style.color = style.color;
        badge.innerHTML = `
      <span class="forensic-verdict-card__verdict-icon">${style.icon}</span>
      <span class="forensic-verdict-card__verdict-text">${verdict}</span>
    `;
        if (this.onVerdictClick) {
            badge.style.cursor = "pointer";
            badge.addEventListener("click", () => {
                this.onVerdictClick?.(verdict);
            });
        }
        return badge;
    }
    /**
     * Create summary section with discrepancy count
     */
    createSummarySection() {
        const section = document.createElement("div");
        section.className = "forensic-verdict-card__summary";
        const discrepancyCount = this.data.discrepancy_count;
        const hasDiscrepancies = discrepancyCount > 0;
        section.innerHTML = `
      <div class="forensic-verdict-card__metric">
        <span class="forensic-verdict-card__metric-value ${hasDiscrepancies ? "forensic-verdict-card__metric-value--warning" : "forensic-verdict-card__metric-value--success"}">
          ${discrepancyCount}
        </span>
        <span class="forensic-verdict-card__metric-label">
          ${discrepancyCount === 1 ? "Discrepancy" : "Discrepancies"}
        </span>
      </div>
      <div class="forensic-verdict-card__metric">
        <span class="forensic-verdict-card__metric-value ${this.data.critical_issues.length > 0 ? "forensic-verdict-card__metric-value--error" : "forensic-verdict-card__metric-value--success"}">
          ${this.data.critical_issues.length}
        </span>
        <span class="forensic-verdict-card__metric-label">
          Critical ${this.data.critical_issues.length === 1 ? "Issue" : "Issues"}
        </span>
      </div>
      <div class="forensic-verdict-card__metric">
        <span class="forensic-verdict-card__metric-value ${this.data.reward_hacking_flags.length > 0 ? "forensic-verdict-card__metric-value--severe" : "forensic-verdict-card__metric-value--success"}">
          ${this.data.reward_hacking_flags.length}
        </span>
        <span class="forensic-verdict-card__metric-label">
          ${this.data.reward_hacking_flags.length === 1 ? "Hack Flag" : "Hack Flags"}
        </span>
      </div>
      <div class="forensic-verdict-card__metric">
        <span class="forensic-verdict-card__metric-value">
          ${this.data.claim_vs_evidence.length}
        </span>
        <span class="forensic-verdict-card__metric-label">
          ${this.data.claim_vs_evidence.length === 1 ? "Claim" : "Claims"} Verified
        </span>
      </div>
    `;
        return section;
    }
    /**
     * Create reward hacking flags section (prominently displayed)
     */
    createRewardHackingSection() {
        const section = document.createElement("div");
        section.className = "forensic-verdict-card__section forensic-verdict-card__section--severe";
        section.setAttribute("data-uiid", "flow_studio.forensic_verdict.reward_hacking");
        const header = document.createElement("div");
        header.className = "forensic-verdict-card__section-header forensic-verdict-card__section-header--severe";
        header.innerHTML = `
      <span class="forensic-verdict-card__section-icon">\u26D4</span>
      <span class="forensic-verdict-card__section-title">Reward Hacking Detected</span>
    `;
        const description = document.createElement("div");
        description.className = "forensic-verdict-card__section-description";
        description.textContent = "These patterns indicate potential gaming of metrics or misleading claims:";
        const list = document.createElement("ul");
        list.className = "forensic-verdict-card__flag-list";
        for (const flag of this.data.reward_hacking_flags) {
            const item = document.createElement("li");
            item.className = "forensic-verdict-card__flag-item";
            item.innerHTML = `
        <span class="forensic-verdict-card__flag-icon">\u26A0</span>
        <span class="forensic-verdict-card__flag-text">${escapeHtml(flag)}</span>
      `;
            list.appendChild(item);
        }
        section.appendChild(header);
        section.appendChild(description);
        section.appendChild(list);
        return section;
    }
    /**
     * Create critical issues section
     */
    createCriticalIssuesSection() {
        const section = document.createElement("div");
        section.className = "forensic-verdict-card__section forensic-verdict-card__section--critical";
        section.setAttribute("data-uiid", "flow_studio.forensic_verdict.critical_issues");
        const header = document.createElement("div");
        header.className = "forensic-verdict-card__section-header forensic-verdict-card__section-header--critical";
        header.innerHTML = `
      <span class="forensic-verdict-card__section-icon">\u274c</span>
      <span class="forensic-verdict-card__section-title">Critical Issues</span>
    `;
        const list = document.createElement("ul");
        list.className = "forensic-verdict-card__issue-list";
        for (const issue of this.data.critical_issues) {
            const item = document.createElement("li");
            item.className = "forensic-verdict-card__issue-item";
            item.innerHTML = `
        <span class="forensic-verdict-card__issue-icon">\u26A0</span>
        <span class="forensic-verdict-card__issue-text">${escapeHtml(issue)}</span>
      `;
            list.appendChild(item);
        }
        section.appendChild(header);
        section.appendChild(list);
        return section;
    }
    /**
     * Create expandable claim vs evidence section
     */
    createClaimEvidenceSection() {
        const section = document.createElement("div");
        section.className = "forensic-verdict-card__section";
        section.setAttribute("data-uiid", "flow_studio.forensic_verdict.claims");
        // Header with expand/collapse button
        const header = document.createElement("div");
        header.className = "forensic-verdict-card__section-header forensic-verdict-card__section-header--expandable";
        const headerLeft = document.createElement("div");
        headerLeft.className = "forensic-verdict-card__section-header-left";
        headerLeft.innerHTML = `
      <span class="forensic-verdict-card__section-icon">\u{1F50D}</span>
      <span class="forensic-verdict-card__section-title">Claim vs Evidence</span>
    `;
        const expandBtn = document.createElement("button");
        expandBtn.className = "forensic-verdict-card__expand-btn";
        expandBtn.setAttribute("aria-expanded", String(this.isExpanded));
        expandBtn.innerHTML = this.isExpanded ? "\u25B2" : "\u25BC";
        expandBtn.title = this.isExpanded ? "Collapse" : "Expand";
        expandBtn.addEventListener("click", () => {
            this.isExpanded = !this.isExpanded;
            this.render();
        });
        // Count summary
        const matchCount = this.data.claim_vs_evidence.filter(c => c.match).length;
        const mismatchCount = this.data.claim_vs_evidence.length - matchCount;
        const summary = document.createElement("span");
        summary.className = "forensic-verdict-card__claims-summary";
        summary.innerHTML = `
      <span class="forensic-verdict-card__claims-match">\u2713 ${matchCount}</span>
      <span class="forensic-verdict-card__claims-mismatch">\u2717 ${mismatchCount}</span>
    `;
        header.appendChild(headerLeft);
        header.appendChild(summary);
        header.appendChild(expandBtn);
        section.appendChild(header);
        // Expandable content
        if (this.isExpanded) {
            const content = document.createElement("div");
            content.className = "forensic-verdict-card__claims-content";
            for (let i = 0; i < this.data.claim_vs_evidence.length; i++) {
                const comparison = this.data.claim_vs_evidence[i];
                const item = this.createComparisonItem(comparison, i);
                content.appendChild(item);
            }
            section.appendChild(content);
        }
        return section;
    }
    /**
     * Create a single claim vs evidence comparison item
     */
    createComparisonItem(comparison, index) {
        const item = document.createElement("div");
        item.className = `forensic-verdict-card__comparison ${comparison.match ? "forensic-verdict-card__comparison--match" : "forensic-verdict-card__comparison--mismatch"}`;
        item.setAttribute("data-uiid", `flow_studio.forensic_verdict.comparison.${index}`);
        const indicator = document.createElement("div");
        indicator.className = "forensic-verdict-card__comparison-indicator";
        indicator.innerHTML = comparison.match
            ? '<span class="forensic-verdict-card__match-icon">\u2713</span>'
            : '<span class="forensic-verdict-card__mismatch-icon">\u2717</span>';
        const content = document.createElement("div");
        content.className = "forensic-verdict-card__comparison-content";
        const claimRow = document.createElement("div");
        claimRow.className = "forensic-verdict-card__comparison-row";
        claimRow.innerHTML = `
      <span class="forensic-verdict-card__comparison-label">Claim:</span>
      <span class="forensic-verdict-card__comparison-text">${escapeHtml(comparison.claim)}</span>
    `;
        const evidenceRow = document.createElement("div");
        evidenceRow.className = "forensic-verdict-card__comparison-row";
        evidenceRow.innerHTML = `
      <span class="forensic-verdict-card__comparison-label">Evidence:</span>
      <span class="forensic-verdict-card__comparison-text">${escapeHtml(comparison.evidence)}</span>
    `;
        content.appendChild(claimRow);
        content.appendChild(evidenceRow);
        item.appendChild(indicator);
        item.appendChild(content);
        // Click handler
        if (this.onComparisonClick) {
            item.style.cursor = "pointer";
            item.addEventListener("click", () => {
                this.onComparisonClick?.(comparison, index);
            });
        }
        return item;
    }
    // ==========================================================================
    // Styles
    // ==========================================================================
    /**
     * Inject component styles
     */
    injectStyles() {
        const styleId = "forensic-verdict-card-styles";
        if (document.getElementById(styleId)) {
            return;
        }
        const styles = document.createElement("style");
        styles.id = styleId;
        styles.textContent = `
      .forensic-verdict-card {
        background: var(--fs-color-bg-base, #ffffff);
        border: 1px solid var(--fs-color-border, #e5e7eb);
        border-radius: var(--fs-radius-lg, 6px);
        overflow: hidden;
      }

      .forensic-verdict-card__loading,
      .forensic-verdict-card__error,
      .forensic-verdict-card__empty {
        padding: var(--fs-spacing-lg, 16px);
        display: flex;
        align-items: center;
        justify-content: center;
        gap: var(--fs-spacing-sm, 8px);
        color: var(--fs-color-text-muted, #6b7280);
        font-size: var(--fs-font-size-sm, 11px);
      }

      .forensic-verdict-card__spinner {
        width: 16px;
        height: 16px;
        border: 2px solid var(--fs-color-border, #e5e7eb);
        border-top-color: var(--fs-color-accent, #3b82f6);
        border-radius: 50%;
        animation: forensic-spin 0.8s linear infinite;
      }

      @keyframes forensic-spin {
        to { transform: rotate(360deg); }
      }

      .forensic-verdict-card__error {
        color: var(--fs-color-error, #ef4444);
      }

      .forensic-verdict-card__error-icon {
        font-size: 16px;
      }

      .forensic-verdict-card__header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: var(--fs-spacing-md, 12px) var(--fs-spacing-lg, 16px);
        background: var(--fs-color-bg-muted, #f9fafb);
        border-bottom: 1px solid var(--fs-color-border, #e5e7eb);
      }

      .forensic-verdict-card__title {
        font-size: var(--fs-font-size-md, 13px);
        font-weight: 600;
        color: var(--fs-color-text, #111827);
      }

      .forensic-verdict-card__verdict-badge {
        display: inline-flex;
        align-items: center;
        gap: var(--fs-spacing-xs, 4px);
        padding: var(--fs-spacing-xs, 4px) var(--fs-spacing-sm, 8px);
        border-radius: var(--fs-radius-md, 4px);
        border: 2px solid;
        font-size: var(--fs-font-size-sm, 11px);
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        background: none;
      }

      .forensic-verdict-card__verdict-badge:hover {
        opacity: 0.9;
      }

      .forensic-verdict-card__verdict-icon {
        font-size: 12px;
      }

      .forensic-verdict-card__summary {
        display: grid;
        grid-template-columns: repeat(4, 1fr);
        gap: var(--fs-spacing-xs, 4px);
        padding: var(--fs-spacing-md, 12px);
        border-bottom: 1px solid var(--fs-color-border, #e5e7eb);
      }

      .forensic-verdict-card__metric {
        text-align: center;
        padding: var(--fs-spacing-xs, 4px);
      }

      .forensic-verdict-card__metric-value {
        font-size: var(--fs-font-size-lg, 14px);
        font-weight: 700;
        color: var(--fs-color-text, #111827);
      }

      .forensic-verdict-card__metric-value--success {
        color: var(--fs-color-success, #22c55e);
      }

      .forensic-verdict-card__metric-value--warning {
        color: var(--fs-color-warning, #f59e0b);
      }

      .forensic-verdict-card__metric-value--error {
        color: var(--fs-color-error, #ef4444);
      }

      .forensic-verdict-card__metric-value--severe {
        color: #7c2d12;
      }

      .forensic-verdict-card__metric-label {
        font-size: var(--fs-font-size-xs, 10px);
        color: var(--fs-color-text-muted, #6b7280);
      }

      .forensic-verdict-card__section {
        border-bottom: 1px solid var(--fs-color-border, #e5e7eb);
      }

      .forensic-verdict-card__section:last-child {
        border-bottom: none;
      }

      .forensic-verdict-card__section--severe {
        background: linear-gradient(135deg, #fef2f2, #fff7ed);
      }

      .forensic-verdict-card__section--critical {
        background: var(--fs-color-error-bg, #fee2e2);
      }

      .forensic-verdict-card__section-header {
        display: flex;
        align-items: center;
        gap: var(--fs-spacing-sm, 8px);
        padding: var(--fs-spacing-sm, 8px) var(--fs-spacing-lg, 16px);
      }

      .forensic-verdict-card__section-header--severe {
        color: #7c2d12;
        font-weight: 600;
      }

      .forensic-verdict-card__section-header--critical {
        color: var(--fs-color-error, #ef4444);
      }

      .forensic-verdict-card__section-header--expandable {
        justify-content: space-between;
        cursor: pointer;
      }

      .forensic-verdict-card__section-header--expandable:hover {
        background: var(--fs-color-bg-hover, #f3f4f6);
      }

      .forensic-verdict-card__section-header-left {
        display: flex;
        align-items: center;
        gap: var(--fs-spacing-sm, 8px);
      }

      .forensic-verdict-card__section-icon {
        font-size: 14px;
      }

      .forensic-verdict-card__section-title {
        font-size: var(--fs-font-size-sm, 11px);
        font-weight: 600;
      }

      .forensic-verdict-card__section-description {
        padding: 0 var(--fs-spacing-lg, 16px) var(--fs-spacing-sm, 8px);
        font-size: var(--fs-font-size-xs, 10px);
        color: #78350f;
      }

      .forensic-verdict-card__flag-list,
      .forensic-verdict-card__issue-list {
        list-style: none;
        margin: 0;
        padding: 0 var(--fs-spacing-lg, 16px) var(--fs-spacing-md, 12px);
      }

      .forensic-verdict-card__flag-item,
      .forensic-verdict-card__issue-item {
        display: flex;
        align-items: flex-start;
        gap: var(--fs-spacing-sm, 8px);
        padding: var(--fs-spacing-xs, 4px) var(--fs-spacing-sm, 8px);
        margin-bottom: var(--fs-spacing-xs, 4px);
        background: rgba(255, 255, 255, 0.7);
        border-radius: var(--fs-radius-sm, 3px);
        font-size: var(--fs-font-size-sm, 11px);
      }

      .forensic-verdict-card__flag-item {
        border-left: 3px solid #c2410c;
        color: #7c2d12;
      }

      .forensic-verdict-card__issue-item {
        border-left: 3px solid var(--fs-color-error, #ef4444);
        color: #991b1b;
      }

      .forensic-verdict-card__flag-icon,
      .forensic-verdict-card__issue-icon {
        flex-shrink: 0;
        font-size: 12px;
      }

      .forensic-verdict-card__claims-summary {
        display: flex;
        gap: var(--fs-spacing-md, 12px);
        font-size: var(--fs-font-size-xs, 10px);
        font-weight: 600;
      }

      .forensic-verdict-card__claims-match {
        color: var(--fs-color-success, #22c55e);
      }

      .forensic-verdict-card__claims-mismatch {
        color: var(--fs-color-error, #ef4444);
      }

      .forensic-verdict-card__expand-btn {
        background: none;
        border: none;
        padding: var(--fs-spacing-xs, 4px);
        cursor: pointer;
        color: var(--fs-color-text-muted, #6b7280);
        font-size: 10px;
      }

      .forensic-verdict-card__expand-btn:hover {
        color: var(--fs-color-text, #111827);
      }

      .forensic-verdict-card__claims-content {
        padding: 0 var(--fs-spacing-lg, 16px) var(--fs-spacing-md, 12px);
      }

      .forensic-verdict-card__comparison {
        display: flex;
        gap: var(--fs-spacing-sm, 8px);
        padding: var(--fs-spacing-sm, 8px);
        margin-bottom: var(--fs-spacing-sm, 8px);
        border-radius: var(--fs-radius-md, 4px);
        border-left: 3px solid;
      }

      .forensic-verdict-card__comparison:last-child {
        margin-bottom: 0;
      }

      .forensic-verdict-card__comparison--match {
        background: var(--fs-color-success-bg, #dcfce7);
        border-left-color: var(--fs-color-success, #22c55e);
      }

      .forensic-verdict-card__comparison--mismatch {
        background: var(--fs-color-error-bg, #fee2e2);
        border-left-color: var(--fs-color-error, #ef4444);
      }

      .forensic-verdict-card__comparison-indicator {
        flex-shrink: 0;
        width: 20px;
        height: 20px;
        display: flex;
        align-items: center;
        justify-content: center;
        border-radius: 50%;
      }

      .forensic-verdict-card__match-icon {
        color: var(--fs-color-success, #22c55e);
        font-weight: bold;
      }

      .forensic-verdict-card__mismatch-icon {
        color: var(--fs-color-error, #ef4444);
        font-weight: bold;
      }

      .forensic-verdict-card__comparison-content {
        flex: 1;
        min-width: 0;
      }

      .forensic-verdict-card__comparison-row {
        display: flex;
        gap: var(--fs-spacing-sm, 8px);
        font-size: var(--fs-font-size-xs, 10px);
        margin-bottom: var(--fs-spacing-xs, 4px);
      }

      .forensic-verdict-card__comparison-row:last-child {
        margin-bottom: 0;
      }

      .forensic-verdict-card__comparison-label {
        flex-shrink: 0;
        font-weight: 600;
        color: var(--fs-color-text-muted, #6b7280);
        width: 55px;
      }

      .forensic-verdict-card__comparison-text {
        color: var(--fs-color-text, #111827);
        word-break: break-word;
      }
    `;
        document.head.appendChild(styles);
    }
    // ==========================================================================
    // Public API
    // ==========================================================================
    /**
     * Toggle expanded state
     */
    toggleExpanded() {
        this.isExpanded = !this.isExpanded;
        this.render();
    }
    /**
     * Set expanded state
     */
    setExpanded(expanded) {
        this.isExpanded = expanded;
        this.render();
    }
    /**
     * Check if expanded
     */
    isExpandedState() {
        return this.isExpanded;
    }
    /**
     * Destroy the component
     */
    destroy() {
        this.container.innerHTML = "";
        this.data = null;
    }
}
// ============================================================================
// Factory Function
// ============================================================================
/**
 * Create a forensic verdict card with initial data
 */
export function createForensicVerdictCard(container, data, options) {
    const component = new ForensicVerdictCard({
        container,
        ...options,
    });
    if (data) {
        component.setData(data);
    }
    else {
        component.render();
    }
    return component;
}
// ============================================================================
// CSS Class Names Reference
// ============================================================================
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
