// swarm/tools/flow_studio_ui/src/components/BoundaryReview.ts
// Boundary Review UI component for flow completion summaries
//
// Shows a summary at the end of each flow for human review:
// - Flow completion status (VERIFIED/UNVERIFIED)
// - Count of assumptions made
// - Count of decisions made
// - Key artifacts produced
// - MacroNavigator routing decision
// - Action buttons for approve/pause
//
// NO filesystem operations - all data flows through the API.
import { escapeHtml, createModalFocusManager } from "../utils.js";
// ============================================================================
// Status Styling
// ============================================================================
const STATUS_STYLES = {
    VERIFIED: {
        icon: "\u2705", // green checkmark
        color: "#166534",
        bgColor: "#dcfce7",
        borderColor: "#22c55e"
    },
    UNVERIFIED: {
        icon: "\u26a0\ufe0f", // warning
        color: "#92400e",
        bgColor: "#fef3c7",
        borderColor: "#f59e0b"
    },
    BLOCKED: {
        icon: "\u274c", // red X
        color: "#991b1b",
        bgColor: "#fee2e2",
        borderColor: "#ef4444"
    },
    UNKNOWN: {
        icon: "\u2753", // question mark
        color: "#6b7280",
        bgColor: "#f3f4f6",
        borderColor: "#9ca3af"
    }
};
// ============================================================================
// BoundaryReview Component
// ============================================================================
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
export class BoundaryReview {
    constructor(options = {}) {
        this.panel = null;
        this.focusManager = null;
        this.resolvePromise = null;
        this.currentData = null;
        this.options = {
            container: document.body,
            ...options
        };
    }
    // ==========================================================================
    // Public Methods
    // ==========================================================================
    /**
     * Show the boundary review panel for a completed flow.
     *
     * @param data - The boundary review data to display
     * @returns Promise resolving to user's decision
     */
    async show(data) {
        // Remove any existing panel
        this.destroy();
        this.currentData = data;
        return new Promise((resolve) => {
            this.resolvePromise = resolve;
            this.render(data);
        });
    }
    /**
     * Close the panel and return a decision
     */
    close(decision = "cancel") {
        if (this.focusManager) {
            this.focusManager.close();
        }
        if (this.panel) {
            // Animate out
            this.panel.classList.add("boundary-review--closing");
            setTimeout(() => {
                if (this.panel) {
                    this.panel.remove();
                    this.panel = null;
                }
            }, 200);
        }
        if (this.resolvePromise) {
            this.resolvePromise(decision);
            this.resolvePromise = null;
        }
        // Trigger callbacks
        if (this.currentData) {
            if (decision === "approve" && this.options.onApprove) {
                this.options.onApprove(this.currentData.flowKey);
            }
            else if (decision === "pause" && this.options.onPause) {
                this.options.onPause(this.currentData.flowKey);
            }
        }
        if (this.options.onClose) {
            this.options.onClose();
        }
        this.currentData = null;
    }
    /**
     * Destroy the panel and clean up
     */
    destroy() {
        if (this.panel) {
            this.panel.remove();
            this.panel = null;
        }
        this.focusManager = null;
        this.resolvePromise = null;
        this.currentData = null;
    }
    /**
     * Check if panel is currently visible
     */
    isVisible() {
        return this.panel !== null;
    }
    /**
     * Get current data
     */
    getData() {
        return this.currentData;
    }
    // ==========================================================================
    // Rendering
    // ==========================================================================
    /**
     * Render the boundary review panel
     */
    render(data) {
        this.panel = document.createElement("div");
        this.panel.className = "boundary-review-overlay";
        this.panel.setAttribute("role", "dialog");
        this.panel.setAttribute("aria-modal", "true");
        this.panel.setAttribute("aria-labelledby", "boundary-review-title");
        this.panel.setAttribute("data-uiid", "flow_studio.boundary_review.panel");
        const statusStyle = STATUS_STYLES[data.status];
        this.panel.innerHTML = `
      <div class="boundary-review-panel" data-uiid="flow_studio.boundary_review.content">
        <div class="boundary-review__header">
          <div class="boundary-review__header-left">
            <span class="boundary-review__status-icon" style="background: ${statusStyle.bgColor}; border-color: ${statusStyle.borderColor};">
              ${statusStyle.icon}
            </span>
            <div class="boundary-review__header-text">
              <h2 id="boundary-review-title" class="boundary-review__title">
                Flow Completed: ${escapeHtml(data.flowTitle)}
              </h2>
              <div class="boundary-review__subtitle" style="color: ${statusStyle.color};">
                Status: ${data.status}
              </div>
            </div>
          </div>
          <button class="boundary-review__close" data-action="close" aria-label="Close">\u00d7</button>
        </div>

        <div class="boundary-review__body">
          ${this.renderSummarySection(data)}
          ${this.renderArtifactsSection(data)}
          ${this.renderRoutingSection(data)}
          ${this.renderIssuesSection(data)}
        </div>

        <div class="boundary-review__footer">
          ${this.renderActions(data)}
        </div>
      </div>
    `;
        // Add styles
        this.injectStyles();
        // Append to container
        const container = this.options.container || document.body;
        container.appendChild(this.panel);
        // Set up focus management
        const content = this.panel.querySelector(".boundary-review-panel");
        if (content) {
            this.focusManager = createModalFocusManager(this.panel, ".boundary-review-panel");
            this.focusManager.open();
        }
        // Set up event listeners
        this.attachEventListeners();
    }
    /**
     * Render summary section with counts
     */
    renderSummarySection(data) {
        const duration = data.durationSeconds
            ? this.formatDuration(data.durationSeconds)
            : "N/A";
        return `
      <div class="boundary-review__section">
        <h3 class="boundary-review__section-title">Summary</h3>
        <div class="boundary-review__metrics">
          <div class="boundary-review__metric">
            <div class="boundary-review__metric-value">${data.assumptionsCount}</div>
            <div class="boundary-review__metric-label">Assumptions Made</div>
          </div>
          <div class="boundary-review__metric">
            <div class="boundary-review__metric-value">${data.decisionsCount}</div>
            <div class="boundary-review__metric-label">Decisions Made</div>
          </div>
          <div class="boundary-review__metric">
            <div class="boundary-review__metric-value">${data.artifacts.length}</div>
            <div class="boundary-review__metric-label">Artifacts Produced</div>
          </div>
          <div class="boundary-review__metric">
            <div class="boundary-review__metric-value">${duration}</div>
            <div class="boundary-review__metric-label">Duration</div>
          </div>
        </div>
      </div>
    `;
    }
    /**
     * Render artifacts section
     */
    renderArtifactsSection(data) {
        if (data.artifacts.length === 0) {
            return "";
        }
        const artifactRows = data.artifacts.slice(0, 8).map(artifact => {
            const statusIcon = artifact.status === "present" ? "\u2705" : "\u274c";
            const statusClass = artifact.status === "present" ? "status-present" : "status-missing";
            const requiredBadge = artifact.required
                ? '<span class="boundary-review__badge boundary-review__badge--required">Required</span>'
                : '<span class="boundary-review__badge">Optional</span>';
            return `
        <tr class="${statusClass}">
          <td class="boundary-review__artifact-status">${statusIcon}</td>
          <td class="boundary-review__artifact-path mono">${escapeHtml(artifact.path)}</td>
          <td>${requiredBadge}</td>
        </tr>
      `;
        }).join("");
        const moreCount = data.artifacts.length > 8 ? `<div class="boundary-review__more">+${data.artifacts.length - 8} more artifacts</div>` : "";
        return `
      <div class="boundary-review__section">
        <h3 class="boundary-review__section-title">Key Artifacts</h3>
        <table class="boundary-review__artifact-table">
          <tbody>
            ${artifactRows}
          </tbody>
        </table>
        ${moreCount}
      </div>
    `;
    }
    /**
     * Render routing decision section
     */
    renderRoutingSection(data) {
        if (!data.routingDecision) {
            return "";
        }
        const rd = data.routingDecision;
        let decisionIcon = "\u27a1\ufe0f"; // arrow
        let decisionColor = "#166534";
        if (rd.isBounce) {
            decisionIcon = "\u21a9\ufe0f"; // curved arrow
            decisionColor = "#dc2626";
        }
        else if (rd.decision === "terminate") {
            decisionIcon = "\u23f9\ufe0f"; // stop
            decisionColor = "#6b7280";
        }
        const targetDisplay = rd.isBounce && rd.bounceTarget
            ? `Bounce back to: ${rd.bounceTarget}`
            : rd.targetFlow
                ? `Next: ${rd.targetFlow}`
                : "End of workflow";
        return `
      <div class="boundary-review__section">
        <h3 class="boundary-review__section-title">Routing Decision</h3>
        <div class="boundary-review__routing" style="border-left-color: ${decisionColor};">
          <div class="boundary-review__routing-header">
            <span class="boundary-review__routing-icon">${decisionIcon}</span>
            <span class="boundary-review__routing-target" style="color: ${decisionColor};">${escapeHtml(targetDisplay)}</span>
          </div>
          <div class="boundary-review__routing-reason">${escapeHtml(rd.reason)}</div>
        </div>
      </div>
    `;
    }
    /**
     * Render issues section (blocking issues and warnings)
     */
    renderIssuesSection(data) {
        const hasBlocking = data.blockingIssues && data.blockingIssues.length > 0;
        const hasWarnings = data.warnings && data.warnings.length > 0;
        if (!hasBlocking && !hasWarnings) {
            return "";
        }
        let content = "";
        if (hasBlocking) {
            const blockingItems = data.blockingIssues.map(issue => `
        <li class="boundary-review__issue boundary-review__issue--blocking">
          <span class="boundary-review__issue-icon">\u274c</span>
          <span>${escapeHtml(issue)}</span>
        </li>
      `).join("");
            content += `
        <div class="boundary-review__issues-group">
          <h4 class="boundary-review__issues-title boundary-review__issues-title--blocking">Blocking Issues</h4>
          <ul class="boundary-review__issues-list">
            ${blockingItems}
          </ul>
        </div>
      `;
        }
        if (hasWarnings) {
            const warningItems = data.warnings.map(warning => `
        <li class="boundary-review__issue boundary-review__issue--warning">
          <span class="boundary-review__issue-icon">\u26a0\ufe0f</span>
          <span>${escapeHtml(warning)}</span>
        </li>
      `).join("");
            content += `
        <div class="boundary-review__issues-group">
          <h4 class="boundary-review__issues-title boundary-review__issues-title--warning">Warnings</h4>
          <ul class="boundary-review__issues-list">
            ${warningItems}
          </ul>
        </div>
      `;
        }
        return `
      <div class="boundary-review__section">
        <h3 class="boundary-review__section-title">Issues</h3>
        ${content}
      </div>
    `;
    }
    /**
     * Render action buttons
     */
    renderActions(data) {
        const hasBlockingIssues = data.blockingIssues && data.blockingIssues.length > 0;
        const isBlocked = data.status === "BLOCKED";
        // If blocked, only show pause button
        if (isBlocked || hasBlockingIssues) {
            return `
        <div class="boundary-review__actions">
          <button class="boundary-review__btn boundary-review__btn--secondary" data-action="cancel">
            Close
          </button>
          <button class="boundary-review__btn boundary-review__btn--warning" data-action="pause" data-uiid="flow_studio.boundary_review.pause">
            Review & Address Issues
          </button>
        </div>
        <div class="boundary-review__action-hint">
          Blocking issues must be resolved before continuing.
        </div>
      `;
        }
        // Normal case: show both approve and pause
        return `
      <div class="boundary-review__actions">
        <button class="boundary-review__btn boundary-review__btn--secondary" data-action="pause" data-uiid="flow_studio.boundary_review.pause">
          Review & Pause
        </button>
        <button class="boundary-review__btn boundary-review__btn--primary" data-action="approve" data-uiid="flow_studio.boundary_review.approve">
          Approve & Continue
        </button>
      </div>
      <div class="boundary-review__action-hint">
        ${data.status === "VERIFIED"
            ? "All checks passed. Safe to continue to next flow."
            : "Some issues noted. Review assumptions before continuing."}
      </div>
    `;
    }
    /**
     * Format duration in human-readable format
     */
    formatDuration(seconds) {
        if (seconds < 60) {
            return `${seconds.toFixed(1)}s`;
        }
        const minutes = Math.floor(seconds / 60);
        const remainingSeconds = seconds % 60;
        if (minutes < 60) {
            return `${minutes}m ${remainingSeconds.toFixed(0)}s`;
        }
        const hours = Math.floor(minutes / 60);
        const remainingMinutes = minutes % 60;
        return `${hours}h ${remainingMinutes}m`;
    }
    /**
     * Inject component styles
     */
    injectStyles() {
        const styleId = "boundary-review-styles";
        if (document.getElementById(styleId)) {
            return;
        }
        const styles = document.createElement("style");
        styles.id = styleId;
        styles.textContent = `
      .boundary-review-overlay {
        position: fixed;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        background: rgba(0, 0, 0, 0.5);
        display: flex;
        align-items: center;
        justify-content: center;
        z-index: var(--fs-z-modal, 2000);
        opacity: 0;
        animation: boundary-review-fade-in 0.2s ease-out forwards;
      }

      .boundary-review-overlay.boundary-review--closing {
        animation: boundary-review-fade-out 0.2s ease-out forwards;
      }

      @keyframes boundary-review-fade-in {
        to { opacity: 1; }
      }

      @keyframes boundary-review-fade-out {
        to { opacity: 0; }
      }

      .boundary-review-panel {
        background: var(--fs-color-bg-base, #ffffff);
        border-radius: var(--fs-radius-xl, 8px);
        box-shadow: var(--fs-shadow-lg, 0 20px 40px rgba(0, 0, 0, 0.2));
        max-width: 600px;
        width: 90%;
        max-height: 80vh;
        overflow: hidden;
        display: flex;
        flex-direction: column;
        animation: boundary-review-slide-up 0.25s ease-out;
      }

      @keyframes boundary-review-slide-up {
        from {
          opacity: 0;
          transform: translateY(20px);
        }
        to {
          opacity: 1;
          transform: translateY(0);
        }
      }

      .boundary-review__header {
        display: flex;
        align-items: flex-start;
        justify-content: space-between;
        padding: var(--fs-spacing-lg, 16px) var(--fs-spacing-xl, 24px);
        border-bottom: 1px solid var(--fs-color-border, #e5e7eb);
        background: var(--fs-color-bg-muted, #f9fafb);
      }

      .boundary-review__header-left {
        display: flex;
        align-items: flex-start;
        gap: var(--fs-spacing-md, 12px);
      }

      .boundary-review__status-icon {
        width: 40px;
        height: 40px;
        border-radius: 50%;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 20px;
        border: 2px solid;
        flex-shrink: 0;
      }

      .boundary-review__header-text {
        display: flex;
        flex-direction: column;
        gap: 4px;
      }

      .boundary-review__title {
        margin: 0;
        font-size: var(--fs-font-size-xl, 16px);
        font-weight: 600;
        color: var(--fs-color-text, #111827);
      }

      .boundary-review__subtitle {
        font-size: var(--fs-font-size-sm, 11px);
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.05em;
      }

      .boundary-review__close {
        background: none;
        border: none;
        font-size: 24px;
        cursor: pointer;
        color: var(--fs-color-text-muted, #6b7280);
        padding: 4px;
        line-height: 1;
      }

      .boundary-review__close:hover {
        color: var(--fs-color-text, #111827);
      }

      .boundary-review__body {
        padding: var(--fs-spacing-lg, 16px) var(--fs-spacing-xl, 24px);
        overflow-y: auto;
        flex: 1;
      }

      .boundary-review__section {
        margin-bottom: var(--fs-spacing-lg, 16px);
      }

      .boundary-review__section:last-child {
        margin-bottom: 0;
      }

      .boundary-review__section-title {
        font-size: var(--fs-font-size-md, 13px);
        font-weight: 600;
        color: var(--fs-color-text, #111827);
        margin: 0 0 var(--fs-spacing-sm, 8px) 0;
      }

      .boundary-review__metrics {
        display: grid;
        grid-template-columns: repeat(4, 1fr);
        gap: var(--fs-spacing-md, 12px);
      }

      .boundary-review__metric {
        text-align: center;
        padding: var(--fs-spacing-sm, 8px);
        background: var(--fs-color-bg-muted, #f9fafb);
        border-radius: var(--fs-radius-md, 4px);
      }

      .boundary-review__metric-value {
        font-size: var(--fs-font-size-xl, 16px);
        font-weight: 700;
        color: var(--fs-color-text, #111827);
      }

      .boundary-review__metric-label {
        font-size: var(--fs-font-size-xs, 10px);
        color: var(--fs-color-text-muted, #6b7280);
        margin-top: 2px;
      }

      .boundary-review__artifact-table {
        width: 100%;
        font-size: var(--fs-font-size-sm, 11px);
        border-collapse: collapse;
      }

      .boundary-review__artifact-table td {
        padding: var(--fs-spacing-xs, 4px) var(--fs-spacing-sm, 8px);
        border-bottom: 1px solid var(--fs-color-border, #e5e7eb);
      }

      .boundary-review__artifact-status {
        width: 24px;
        text-align: center;
      }

      .boundary-review__artifact-path {
        word-break: break-all;
      }

      .boundary-review__badge {
        display: inline-block;
        padding: 2px 6px;
        font-size: 9px;
        border-radius: var(--fs-radius-sm, 3px);
        background: var(--fs-color-bg-subtle, #f3f4f6);
        color: var(--fs-color-text-muted, #6b7280);
      }

      .boundary-review__badge--required {
        background: var(--fs-color-accent-bg, #dbeafe);
        color: var(--fs-color-accent, #3b82f6);
      }

      .boundary-review__more {
        font-size: var(--fs-font-size-xs, 10px);
        color: var(--fs-color-text-muted, #6b7280);
        margin-top: var(--fs-spacing-xs, 4px);
        text-align: right;
      }

      .boundary-review__routing {
        padding: var(--fs-spacing-md, 12px);
        background: var(--fs-color-bg-muted, #f9fafb);
        border-radius: var(--fs-radius-md, 4px);
        border-left: 3px solid;
      }

      .boundary-review__routing-header {
        display: flex;
        align-items: center;
        gap: var(--fs-spacing-sm, 8px);
        margin-bottom: var(--fs-spacing-xs, 4px);
      }

      .boundary-review__routing-icon {
        font-size: 16px;
      }

      .boundary-review__routing-target {
        font-weight: 600;
        font-size: var(--fs-font-size-md, 13px);
      }

      .boundary-review__routing-reason {
        font-size: var(--fs-font-size-sm, 11px);
        color: var(--fs-color-text-muted, #6b7280);
      }

      .boundary-review__issues-group {
        margin-bottom: var(--fs-spacing-md, 12px);
      }

      .boundary-review__issues-group:last-child {
        margin-bottom: 0;
      }

      .boundary-review__issues-title {
        font-size: var(--fs-font-size-sm, 11px);
        font-weight: 600;
        margin: 0 0 var(--fs-spacing-xs, 4px) 0;
      }

      .boundary-review__issues-title--blocking {
        color: var(--fs-color-error, #ef4444);
      }

      .boundary-review__issues-title--warning {
        color: var(--fs-color-warning, #f59e0b);
      }

      .boundary-review__issues-list {
        list-style: none;
        margin: 0;
        padding: 0;
      }

      .boundary-review__issue {
        display: flex;
        align-items: flex-start;
        gap: var(--fs-spacing-sm, 8px);
        padding: var(--fs-spacing-sm, 8px);
        border-radius: var(--fs-radius-md, 4px);
        margin-bottom: var(--fs-spacing-xs, 4px);
        font-size: var(--fs-font-size-sm, 11px);
      }

      .boundary-review__issue--blocking {
        background: var(--fs-color-error-bg, #fee2e2);
        color: #991b1b;
      }

      .boundary-review__issue--warning {
        background: var(--fs-color-warning-bg, #fef3c7);
        color: #92400e;
      }

      .boundary-review__issue-icon {
        flex-shrink: 0;
      }

      .boundary-review__footer {
        padding: var(--fs-spacing-md, 12px) var(--fs-spacing-xl, 24px);
        border-top: 1px solid var(--fs-color-border, #e5e7eb);
        background: var(--fs-color-bg-muted, #f9fafb);
      }

      .boundary-review__actions {
        display: flex;
        justify-content: flex-end;
        gap: var(--fs-spacing-sm, 8px);
      }

      .boundary-review__btn {
        padding: var(--fs-spacing-sm, 8px) var(--fs-spacing-lg, 16px);
        border-radius: var(--fs-radius-md, 4px);
        font-size: var(--fs-font-size-md, 13px);
        font-weight: 500;
        cursor: pointer;
        transition: all var(--fs-transition-fast, 0.15s ease);
        border: none;
      }

      .boundary-review__btn--primary {
        background: var(--fs-color-success, #22c55e);
        color: white;
      }

      .boundary-review__btn--primary:hover {
        background: #16a34a;
      }

      .boundary-review__btn--secondary {
        background: white;
        color: var(--fs-color-text, #111827);
        border: 1px solid var(--fs-color-border-strong, #d1d5db);
      }

      .boundary-review__btn--secondary:hover {
        background: var(--fs-color-bg-muted, #f9fafb);
      }

      .boundary-review__btn--warning {
        background: var(--fs-color-warning, #f59e0b);
        color: white;
      }

      .boundary-review__btn--warning:hover {
        background: #d97706;
      }

      .boundary-review__action-hint {
        font-size: var(--fs-font-size-xs, 10px);
        color: var(--fs-color-text-muted, #6b7280);
        text-align: right;
        margin-top: var(--fs-spacing-sm, 8px);
      }
    `;
        document.head.appendChild(styles);
    }
    /**
     * Attach event listeners
     */
    attachEventListeners() {
        if (!this.panel)
            return;
        // Handle button clicks
        this.panel.addEventListener("click", (e) => {
            const target = e.target;
            const action = target.dataset.action || target.closest("[data-action]")?.getAttribute("data-action");
            if (action === "close" || action === "cancel") {
                this.close("cancel");
            }
            else if (action === "approve") {
                this.close("approve");
            }
            else if (action === "pause") {
                this.close("pause");
            }
            // Close on backdrop click
            if (target.classList.contains("boundary-review-overlay")) {
                this.close("cancel");
            }
        });
        // Handle keyboard
        this.panel.addEventListener("keydown", (e) => {
            if (e.key === "Escape") {
                e.preventDefault();
                this.close("cancel");
            }
        });
    }
}
// ============================================================================
// Factory Function
// ============================================================================
/**
 * Create a new BoundaryReview instance
 */
export function createBoundaryReview(options) {
    return new BoundaryReview(options);
}
// ============================================================================
// Helper to extract review data from run summary
// ============================================================================
/**
 * Extract BoundaryReviewData from a completed flow's data.
 * This is a helper for wiring up the component.
 */
export function extractBoundaryReviewData(flowKey, flowTitle, status, artifacts, options) {
    return {
        flowKey,
        flowTitle,
        status,
        assumptionsCount: options?.assumptionsCount ?? 0,
        decisionsCount: options?.decisionsCount ?? 0,
        artifacts,
        routingDecision: options?.routingDecision,
        completedAt: new Date().toISOString(),
        durationSeconds: options?.durationSeconds,
        blockingIssues: options?.blockingIssues,
        warnings: options?.warnings,
        receipts: options?.receipts,
        confidenceScore: options?.confidenceScore
    };
}
// ============================================================================
// CSS Class Names Reference
// ============================================================================
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
