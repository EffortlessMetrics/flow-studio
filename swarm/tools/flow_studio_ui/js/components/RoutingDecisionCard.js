// swarm/tools/flow_studio_ui/src/components/RoutingDecisionCard.ts
// Routing Decision Card component for visualizing Navigator routing choices
//
// Displays routing decisions from the stepwise orchestrator:
// - Routing source badge (navigator/fast_path/deterministic_fallback)
// - Chosen candidate highlighted with green border
// - Rejected candidates in collapsed section
// - Default marker on the default candidate
// - Forensic verdict warning flags if present
// - Priority scores displayed
//
// NO filesystem operations - all data flows through props.
import { escapeHtml } from "../utils.js";
// ============================================================================
// Source Badge Styling
// ============================================================================
const SOURCE_STYLES = {
    navigator: {
        label: "Navigator",
        color: "#1d4ed8",
        bgColor: "#dbeafe",
    },
    fast_path: {
        label: "Fast Path",
        color: "#047857",
        bgColor: "#d1fae5",
    },
    deterministic_fallback: {
        label: "Deterministic",
        color: "#6b7280",
        bgColor: "#f3f4f6",
    },
    graph_edge: {
        label: "Graph Edge",
        color: "#7c3aed",
        bgColor: "#ede9fe",
    },
    detour_catalog: {
        label: "Detour",
        color: "#ea580c",
        bgColor: "#ffedd5",
    },
    extend_graph: {
        label: "Extension",
        color: "#0891b2",
        bgColor: "#cffafe",
    },
};
// ============================================================================
// Action Badge Styling
// ============================================================================
const ACTION_STYLES = {
    advance: {
        icon: "\u27a1\ufe0f",
        color: "#166534",
        bgColor: "#dcfce7",
    },
    loop: {
        icon: "\ud83d\udd04",
        color: "#1d4ed8",
        bgColor: "#dbeafe",
    },
    detour: {
        icon: "\u2197\ufe0f",
        color: "#ea580c",
        bgColor: "#ffedd5",
    },
    escalate: {
        icon: "\u26a0\ufe0f",
        color: "#dc2626",
        bgColor: "#fee2e2",
    },
    repeat: {
        icon: "\ud83d\udd01",
        color: "#7c3aed",
        bgColor: "#ede9fe",
    },
    terminate: {
        icon: "\u23f9\ufe0f",
        color: "#6b7280",
        bgColor: "#f3f4f6",
    },
};
// ============================================================================
// RoutingDecisionCard Component
// ============================================================================
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
export class RoutingDecisionCard {
    constructor(options = {}) {
        this.container = null;
        this.card = null;
        this.data = null;
        this.isExpanded = false;
        this.options = {
            expandedByDefault: false,
            ...options,
        };
        this.isExpanded = this.options.expandedByDefault || false;
    }
    // ==========================================================================
    // Public Methods
    // ==========================================================================
    /**
     * Render the routing decision card with the given data.
     */
    render(data, container) {
        this.data = data;
        this.container = container || this.options.container || null;
        // Create the card element
        this.card = document.createElement("div");
        this.card.className = "routing-decision-card";
        this.card.setAttribute("data-uiid", "flow_studio.routing_decision.card");
        this.card.innerHTML = this.buildCardHTML(data);
        // Inject styles
        this.injectStyles();
        // Attach event listeners
        this.attachEventListeners();
        // Append to container if provided
        if (this.container) {
            this.container.appendChild(this.card);
        }
        return this.card;
    }
    /**
     * Update the card with new data.
     */
    update(data) {
        if (!this.card)
            return;
        this.data = data;
        this.card.innerHTML = this.buildCardHTML(data);
        this.attachEventListeners();
    }
    /**
     * Get the current data.
     */
    getData() {
        return this.data;
    }
    /**
     * Get the card element.
     */
    getElement() {
        return this.card;
    }
    /**
     * Destroy the card and clean up.
     */
    destroy() {
        if (this.card) {
            this.card.remove();
            this.card = null;
        }
        this.data = null;
        this.container = null;
    }
    // ==========================================================================
    // HTML Building
    // ==========================================================================
    /**
     * Build the complete card HTML.
     */
    buildCardHTML(data) {
        const chosenCandidate = data.candidates.find((c) => c.candidate_id === data.chosen_candidate_id);
        const rejectedCandidates = data.candidates.filter((c) => c.candidate_id !== data.chosen_candidate_id);
        return `
      <div class="routing-card__header">
        ${this.buildSourceBadge(data.routing_source)}
        ${this.buildMetaInfo(data)}
      </div>
      ${this.buildForensicVerdict(data.forensic_verdict)}
      ${this.buildChosenCandidate(chosenCandidate)}
      ${this.buildRejectedCandidates(rejectedCandidates)}
    `;
    }
    /**
     * Build the routing source badge.
     */
    buildSourceBadge(source) {
        const style = SOURCE_STYLES[source] || SOURCE_STYLES.deterministic_fallback;
        return `
      <span class="routing-card__source-badge" style="color: ${style.color}; background: ${style.bgColor};">
        ${escapeHtml(style.label)}
      </span>
    `;
    }
    /**
     * Build meta information (iteration, flow, step).
     */
    buildMetaInfo(data) {
        const parts = [];
        if (data.flow_key) {
            parts.push(`<span class="routing-card__meta-item">Flow: ${escapeHtml(data.flow_key)}</span>`);
        }
        if (data.step_id) {
            parts.push(`<span class="routing-card__meta-item">Step: ${escapeHtml(data.step_id)}</span>`);
        }
        if (data.iteration !== undefined) {
            parts.push(`<span class="routing-card__meta-item">Iteration: ${data.iteration}</span>`);
        }
        if (parts.length === 0)
            return "";
        return `<div class="routing-card__meta">${parts.join("")}</div>`;
    }
    /**
     * Build forensic verdict section if present.
     */
    buildForensicVerdict(verdict) {
        if (!verdict)
            return "";
        const hasWarnings = verdict.recommendation !== "TRUST" ||
            verdict.reward_hacking_flags.length > 0;
        if (!hasWarnings)
            return "";
        let statusClass = "routing-card__forensic--warning";
        let statusIcon = "\u26a0\ufe0f";
        if (verdict.recommendation === "REJECT") {
            statusClass = "routing-card__forensic--error";
            statusIcon = "\u274c";
        }
        const flagItems = verdict.reward_hacking_flags
            .map((flag) => `
        <li class="routing-card__forensic-flag">
          <span class="routing-card__forensic-flag-icon">\u26a0\ufe0f</span>
          <span>${escapeHtml(flag.replace(/_/g, " "))}</span>
        </li>
      `)
            .join("");
        return `
      <div class="routing-card__forensic ${statusClass}">
        <div class="routing-card__forensic-header">
          <span class="routing-card__forensic-icon">${statusIcon}</span>
          <span class="routing-card__forensic-title">Forensic Verdict: ${escapeHtml(verdict.recommendation)}</span>
          <span class="routing-card__forensic-confidence">(${Math.round(verdict.confidence * 100)}% confidence)</span>
        </div>
        ${verdict.reward_hacking_flags.length > 0 ? `
          <ul class="routing-card__forensic-flags">
            ${flagItems}
          </ul>
        ` : ""}
        ${verdict.critical_issue ? `
          <div class="routing-card__forensic-critical">
            <strong>Critical Issue:</strong> ${escapeHtml(verdict.critical_issue)}
          </div>
        ` : ""}
      </div>
    `;
    }
    /**
     * Build the chosen candidate section.
     */
    buildChosenCandidate(candidate) {
        if (!candidate) {
            return `
        <div class="routing-card__section">
          <h4 class="routing-card__section-title">Chosen Route</h4>
          <div class="routing-card__empty">No candidate selected</div>
        </div>
      `;
        }
        return `
      <div class="routing-card__section">
        <h4 class="routing-card__section-title">Chosen Route</h4>
        ${this.buildCandidateCard(candidate, true)}
      </div>
    `;
    }
    /**
     * Build the rejected candidates section (collapsible).
     */
    buildRejectedCandidates(candidates) {
        if (candidates.length === 0)
            return "";
        const expandedClass = this.isExpanded ? "routing-card__rejected--expanded" : "";
        const arrowIcon = this.isExpanded ? "\u25bc" : "\u25b6";
        const candidateCards = candidates
            .map((c) => this.buildCandidateCard(c, false))
            .join("");
        return `
      <div class="routing-card__section routing-card__rejected ${expandedClass}">
        <button class="routing-card__rejected-toggle" data-action="toggle-rejected">
          <span class="routing-card__rejected-arrow">${arrowIcon}</span>
          <span>Other Candidates (${candidates.length})</span>
        </button>
        <div class="routing-card__rejected-content">
          ${candidateCards}
        </div>
      </div>
    `;
    }
    /**
     * Build a single candidate card.
     */
    buildCandidateCard(candidate, isChosen) {
        const chosenClass = isChosen ? "routing-card__candidate--chosen" : "";
        const defaultClass = candidate.is_default
            ? "routing-card__candidate--default"
            : "";
        const actionStyle = ACTION_STYLES[candidate.action] || ACTION_STYLES.advance;
        const evidenceItems = candidate.evidence_pointers.length > 0
            ? `
          <div class="routing-card__evidence">
            <span class="routing-card__evidence-label">Evidence:</span>
            ${candidate.evidence_pointers
                .slice(0, 3)
                .map((e) => `<code class="routing-card__evidence-item">${escapeHtml(e)}</code>`)
                .join("")}
            ${candidate.evidence_pointers.length > 3 ? `<span class="routing-card__evidence-more">+${candidate.evidence_pointers.length - 3} more</span>` : ""}
          </div>
        `
            : "";
        return `
      <div class="routing-card__candidate ${chosenClass} ${defaultClass}"
           data-candidate-id="${escapeHtml(candidate.candidate_id)}"
           data-action="select-candidate">
        <div class="routing-card__candidate-header">
          <span class="routing-card__action-badge" style="color: ${actionStyle.color}; background: ${actionStyle.bgColor};">
            ${actionStyle.icon} ${escapeHtml(candidate.action)}
          </span>
          ${candidate.target_node ? `
            <span class="routing-card__target">
              \u2192 ${escapeHtml(candidate.target_node)}
            </span>
          ` : ""}
          <span class="routing-card__priority" title="Priority score">
            P${candidate.priority}
          </span>
          ${candidate.is_default ? `
            <span class="routing-card__default-badge" title="Suggested default choice">
              Default
            </span>
          ` : ""}
        </div>
        <div class="routing-card__candidate-reason">
          ${escapeHtml(candidate.reason)}
        </div>
        <div class="routing-card__candidate-meta">
          <span class="routing-card__candidate-source">
            Source: ${escapeHtml(candidate.source.replace(/_/g, " "))}
          </span>
        </div>
        ${evidenceItems}
      </div>
    `;
    }
    // ==========================================================================
    // Styles
    // ==========================================================================
    /**
     * Inject component styles.
     */
    injectStyles() {
        const styleId = "routing-decision-card-styles";
        if (document.getElementById(styleId)) {
            return;
        }
        const styles = document.createElement("style");
        styles.id = styleId;
        styles.textContent = `
      .routing-decision-card {
        background: var(--fs-color-bg-base, #ffffff);
        border: 1px solid var(--fs-color-border, #e5e7eb);
        border-radius: var(--fs-radius-lg, 6px);
        overflow: hidden;
        font-size: var(--fs-font-size-sm, 11px);
      }

      .routing-card__header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: var(--fs-spacing-sm, 8px) var(--fs-spacing-md, 12px);
        background: var(--fs-color-bg-muted, #f9fafb);
        border-bottom: 1px solid var(--fs-color-border, #e5e7eb);
      }

      .routing-card__source-badge {
        display: inline-flex;
        align-items: center;
        padding: 2px 8px;
        border-radius: var(--fs-radius-full, 9999px);
        font-size: var(--fs-font-size-xs, 10px);
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.05em;
      }

      .routing-card__meta {
        display: flex;
        gap: var(--fs-spacing-sm, 8px);
      }

      .routing-card__meta-item {
        color: var(--fs-color-text-muted, #6b7280);
        font-size: var(--fs-font-size-xs, 10px);
      }

      .routing-card__section {
        padding: var(--fs-spacing-sm, 8px) var(--fs-spacing-md, 12px);
      }

      .routing-card__section:not(:last-child) {
        border-bottom: 1px solid var(--fs-color-border-light, #f3f4f6);
      }

      .routing-card__section-title {
        margin: 0 0 var(--fs-spacing-xs, 4px) 0;
        font-size: var(--fs-font-size-xs, 10px);
        font-weight: 600;
        color: var(--fs-color-text-muted, #6b7280);
        text-transform: uppercase;
        letter-spacing: 0.05em;
      }

      .routing-card__empty {
        color: var(--fs-color-text-muted, #6b7280);
        font-style: italic;
      }

      /* Forensic Verdict */
      .routing-card__forensic {
        padding: var(--fs-spacing-sm, 8px) var(--fs-spacing-md, 12px);
        border-bottom: 1px solid var(--fs-color-border, #e5e7eb);
      }

      .routing-card__forensic--warning {
        background: var(--fs-color-warning-bg, #fef3c7);
        border-left: 3px solid var(--fs-color-warning, #f59e0b);
      }

      .routing-card__forensic--error {
        background: var(--fs-color-error-bg, #fee2e2);
        border-left: 3px solid var(--fs-color-error, #ef4444);
      }

      .routing-card__forensic-header {
        display: flex;
        align-items: center;
        gap: var(--fs-spacing-xs, 4px);
        margin-bottom: var(--fs-spacing-xs, 4px);
      }

      .routing-card__forensic-icon {
        font-size: 14px;
      }

      .routing-card__forensic-title {
        font-weight: 600;
        color: var(--fs-color-text, #111827);
      }

      .routing-card__forensic-confidence {
        color: var(--fs-color-text-muted, #6b7280);
        font-size: var(--fs-font-size-xs, 10px);
      }

      .routing-card__forensic-flags {
        list-style: none;
        margin: var(--fs-spacing-xs, 4px) 0 0 0;
        padding: 0;
      }

      .routing-card__forensic-flag {
        display: flex;
        align-items: center;
        gap: var(--fs-spacing-xs, 4px);
        padding: 2px 0;
        font-size: var(--fs-font-size-xs, 10px);
      }

      .routing-card__forensic-flag-icon {
        font-size: 12px;
      }

      .routing-card__forensic-critical {
        margin-top: var(--fs-spacing-xs, 4px);
        padding: var(--fs-spacing-xs, 4px);
        background: rgba(0, 0, 0, 0.05);
        border-radius: var(--fs-radius-sm, 3px);
        font-size: var(--fs-font-size-xs, 10px);
      }

      /* Candidate Cards */
      .routing-card__candidate {
        padding: var(--fs-spacing-sm, 8px);
        background: var(--fs-color-bg-subtle, #f9fafb);
        border: 1px solid var(--fs-color-border-light, #e5e7eb);
        border-radius: var(--fs-radius-md, 4px);
        margin-bottom: var(--fs-spacing-xs, 4px);
        cursor: pointer;
        transition: all var(--fs-transition-fast, 0.15s ease);
      }

      .routing-card__candidate:hover {
        border-color: var(--fs-color-accent, #3b82f6);
      }

      .routing-card__candidate--chosen {
        background: var(--fs-color-success-bg, #dcfce7);
        border-color: var(--fs-color-success, #22c55e);
        border-width: 2px;
      }

      .routing-card__candidate--default {
        position: relative;
      }

      .routing-card__candidate-header {
        display: flex;
        align-items: center;
        flex-wrap: wrap;
        gap: var(--fs-spacing-xs, 4px);
        margin-bottom: var(--fs-spacing-xs, 4px);
      }

      .routing-card__action-badge {
        display: inline-flex;
        align-items: center;
        gap: 2px;
        padding: 2px 6px;
        border-radius: var(--fs-radius-sm, 3px);
        font-size: var(--fs-font-size-xs, 10px);
        font-weight: 500;
      }

      .routing-card__target {
        color: var(--fs-color-text, #111827);
        font-weight: 500;
      }

      .routing-card__priority {
        margin-left: auto;
        padding: 1px 4px;
        background: var(--fs-color-bg-muted, #f3f4f6);
        border-radius: var(--fs-radius-sm, 3px);
        font-size: var(--fs-font-size-xs, 10px);
        font-weight: 600;
        color: var(--fs-color-text-muted, #6b7280);
      }

      .routing-card__default-badge {
        padding: 1px 4px;
        background: var(--fs-color-accent-bg, #dbeafe);
        color: var(--fs-color-accent, #3b82f6);
        border-radius: var(--fs-radius-sm, 3px);
        font-size: 9px;
        font-weight: 600;
        text-transform: uppercase;
      }

      .routing-card__candidate-reason {
        color: var(--fs-color-text, #111827);
        line-height: 1.4;
        margin-bottom: var(--fs-spacing-xs, 4px);
      }

      .routing-card__candidate-meta {
        font-size: var(--fs-font-size-xs, 10px);
        color: var(--fs-color-text-muted, #6b7280);
      }

      .routing-card__candidate-source {
        text-transform: capitalize;
      }

      .routing-card__evidence {
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        gap: 4px;
        margin-top: var(--fs-spacing-xs, 4px);
        font-size: var(--fs-font-size-xs, 10px);
      }

      .routing-card__evidence-label {
        color: var(--fs-color-text-muted, #6b7280);
      }

      .routing-card__evidence-item {
        padding: 1px 4px;
        background: var(--fs-color-bg-muted, #f3f4f6);
        border-radius: var(--fs-radius-sm, 3px);
        font-family: var(--fs-font-mono, monospace);
        font-size: 9px;
      }

      .routing-card__evidence-more {
        color: var(--fs-color-text-muted, #6b7280);
      }

      /* Rejected Candidates (Collapsible) */
      .routing-card__rejected {
        padding: 0;
      }

      .routing-card__rejected-toggle {
        display: flex;
        align-items: center;
        gap: var(--fs-spacing-xs, 4px);
        width: 100%;
        padding: var(--fs-spacing-sm, 8px) var(--fs-spacing-md, 12px);
        background: none;
        border: none;
        cursor: pointer;
        font-size: var(--fs-font-size-sm, 11px);
        color: var(--fs-color-text-muted, #6b7280);
        text-align: left;
      }

      .routing-card__rejected-toggle:hover {
        background: var(--fs-color-bg-muted, #f9fafb);
      }

      .routing-card__rejected-arrow {
        font-size: 10px;
        transition: transform var(--fs-transition-fast, 0.15s ease);
      }

      .routing-card__rejected-content {
        display: none;
        padding: 0 var(--fs-spacing-md, 12px) var(--fs-spacing-sm, 8px);
      }

      .routing-card__rejected--expanded .routing-card__rejected-content {
        display: block;
      }

      .routing-card__rejected--expanded .routing-card__rejected-arrow {
        transform: rotate(0deg);
      }
    `;
        document.head.appendChild(styles);
    }
    // ==========================================================================
    // Event Handling
    // ==========================================================================
    /**
     * Attach event listeners.
     */
    attachEventListeners() {
        if (!this.card)
            return;
        // Toggle rejected candidates
        const toggleBtn = this.card.querySelector('[data-action="toggle-rejected"]');
        if (toggleBtn) {
            toggleBtn.addEventListener("click", () => {
                this.toggleRejectedSection();
            });
        }
        // Candidate clicks
        const candidates = this.card.querySelectorAll('[data-action="select-candidate"]');
        candidates.forEach((el) => {
            el.addEventListener("click", () => {
                const candidateId = el.dataset.candidateId;
                if (candidateId && this.data && this.options.onCandidateClick) {
                    const candidate = this.data.candidates.find((c) => c.candidate_id === candidateId);
                    if (candidate) {
                        this.options.onCandidateClick(candidate);
                    }
                }
            });
        });
    }
    /**
     * Toggle the rejected candidates section.
     */
    toggleRejectedSection() {
        if (!this.card)
            return;
        const section = this.card.querySelector(".routing-card__rejected");
        if (!section)
            return;
        this.isExpanded = !this.isExpanded;
        section.classList.toggle("routing-card__rejected--expanded", this.isExpanded);
        // Update arrow
        const arrow = section.querySelector(".routing-card__rejected-arrow");
        if (arrow) {
            arrow.textContent = this.isExpanded ? "\u25bc" : "\u25b6";
        }
    }
}
// ============================================================================
// Factory Function
// ============================================================================
/**
 * Create a new RoutingDecisionCard instance.
 */
export function createRoutingDecisionCard(options) {
    return new RoutingDecisionCard(options);
}
// ============================================================================
// CSS Class Names Reference
// ============================================================================
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
