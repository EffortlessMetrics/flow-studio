// swarm/tools/flow_studio_ui/src/boundary_review.ts
// Boundary review panel for Flow Studio
//
// Displays aggregated run state at flow boundaries:
// - Assumptions (count, high-risk, details)
// - Decisions (count, details)
// - Detours taken
// - Verification results
// - Evolution suggestions (if present)
import { Api } from "./api.js";
// =============================================================================
// State
// =============================================================================
let currentRunId = null;
let currentData = null;
let isExpanded = false;
// Monotonic sequence counter for request coalescing
// Prevents out-of-order UI renders under bursty SSE events
let loadSeq = 0;
// =============================================================================
// Confidence Badge Rendering
// =============================================================================
function getConfidenceBadgeClass(score) {
    if (score >= 0.8)
        return "confidence-high";
    if (score >= 0.5)
        return "confidence-medium";
    return "confidence-low";
}
function getConfidenceLabel(score) {
    if (score >= 0.8)
        return "High";
    if (score >= 0.5)
        return "Medium";
    return "Low";
}
// =============================================================================
// Assumption Rendering
// =============================================================================
function renderAssumptionCard(assumption) {
    const confidenceClass = `assumption-${assumption.confidence}`;
    const statusClass = assumption.status === "active" ? "status-active" : "status-resolved";
    return `
    <div class="boundary-card assumption-card ${confidenceClass}" data-assumption-id="${assumption.assumption_id}">
      <div class="card-header">
        <span class="card-id">${assumption.assumption_id}</span>
        <span class="card-status ${statusClass}">${assumption.status}</span>
        <span class="card-confidence confidence-${assumption.confidence}">${assumption.confidence}</span>
      </div>
      <div class="card-statement">${escapeHtml(assumption.statement)}</div>
      <details class="card-details">
        <summary>Details</summary>
        <div class="card-detail-row">
          <label>Rationale:</label>
          <span>${escapeHtml(assumption.rationale)}</span>
        </div>
        <div class="card-detail-row">
          <label>Impact if wrong:</label>
          <span>${escapeHtml(assumption.impact_if_wrong)}</span>
        </div>
        ${assumption.agent ? `
        <div class="card-detail-row">
          <label>Agent:</label>
          <span class="agent-badge">${escapeHtml(assumption.agent)}</span>
        </div>
        ` : ""}
        ${assumption.tags.length > 0 ? `
        <div class="card-detail-row">
          <label>Tags:</label>
          <span class="tag-list">${assumption.tags.map(t => `<span class="tag">${escapeHtml(t)}</span>`).join("")}</span>
        </div>
        ` : ""}
      </details>
    </div>
  `;
}
// =============================================================================
// Decision Rendering
// =============================================================================
function renderDecisionCard(decision) {
    return `
    <div class="boundary-card decision-card" data-decision-id="${decision.decision_id}">
      <div class="card-header">
        <span class="card-id">${decision.decision_id}</span>
        <span class="card-type">${escapeHtml(decision.decision_type)}</span>
      </div>
      <div class="card-subject">${escapeHtml(decision.subject)}</div>
      <div class="card-decision">${escapeHtml(decision.decision)}</div>
      <details class="card-details">
        <summary>Details</summary>
        <div class="card-detail-row">
          <label>Rationale:</label>
          <span>${escapeHtml(decision.rationale)}</span>
        </div>
        ${decision.supporting_evidence.length > 0 ? `
        <div class="card-detail-row">
          <label>Evidence:</label>
          <span>${decision.supporting_evidence.map(e => escapeHtml(e)).join(", ")}</span>
        </div>
        ` : ""}
        ${decision.assumptions_applied.length > 0 ? `
        <div class="card-detail-row">
          <label>Assumptions:</label>
          <span>${decision.assumptions_applied.map(a => `<span class="assumption-ref">${escapeHtml(a)}</span>`).join(" ")}</span>
        </div>
        ` : ""}
        ${decision.agent ? `
        <div class="card-detail-row">
          <label>Agent:</label>
          <span class="agent-badge">${escapeHtml(decision.agent)}</span>
        </div>
        ` : ""}
      </details>
    </div>
  `;
}
// =============================================================================
// Detour Rendering
// =============================================================================
function renderDetourCard(detour) {
    return `
    <div class="boundary-card detour-card" data-detour-id="${detour.detour_id}">
      <div class="card-header">
        <span class="card-id">${detour.detour_id}</span>
        <span class="card-type">${escapeHtml(detour.detour_type)}</span>
      </div>
      <div class="card-path">
        <span class="from-step">${escapeHtml(detour.from_step)}</span>
        <span class="arrow">→</span>
        <span class="to-step">${escapeHtml(detour.to_step)}</span>
      </div>
      <div class="card-reason">${escapeHtml(detour.reason)}</div>
    </div>
  `;
}
// =============================================================================
// Verification Rendering
// =============================================================================
function renderVerificationCard(verification) {
    const statusClass = verification.verified ? "status-verified" : "status-unverified";
    const icon = verification.verified ? "✓" : "✗";
    return `
    <div class="boundary-card verification-card ${statusClass}" data-step-id="${verification.step_id}">
      <div class="card-header">
        <span class="status-icon">${icon}</span>
        <span class="card-id">${escapeHtml(verification.step_id)}</span>
        <span class="card-status">${escapeHtml(verification.status)}</span>
      </div>
      ${verification.station_id ? `
      <div class="card-station">Station: ${escapeHtml(verification.station_id)}</div>
      ` : ""}
      ${verification.issues.length > 0 ? `
      <div class="card-issues">
        <ul>
          ${verification.issues.map(i => `<li>${escapeHtml(i)}</li>`).join("")}
        </ul>
      </div>
      ` : ""}
    </div>
  `;
}
// =============================================================================
// Main Panel Rendering
// =============================================================================
function renderSummaryBar(data) {
    const confidenceClass = getConfidenceBadgeClass(data.confidence_score);
    const confidenceLabel = getConfidenceLabel(data.confidence_score);
    const confidencePercent = Math.round(data.confidence_score * 100);
    return `
    <div class="boundary-summary-bar">
      <div class="summary-item confidence-summary ${confidenceClass}">
        <span class="summary-label">Confidence</span>
        <span class="summary-value">${confidencePercent}% (${confidenceLabel})</span>
      </div>
      <div class="summary-item">
        <span class="summary-label">Assumptions</span>
        <span class="summary-value">${data.assumptions_count}${data.assumptions_high_risk > 0 ? ` (${data.assumptions_high_risk} high-risk)` : ""}</span>
      </div>
      <div class="summary-item">
        <span class="summary-label">Decisions</span>
        <span class="summary-value">${data.decisions_count}</span>
      </div>
      <div class="summary-item">
        <span class="summary-label">Detours</span>
        <span class="summary-value">${data.detours_count}</span>
      </div>
      <div class="summary-item">
        <span class="summary-label">Verification</span>
        <span class="summary-value verification-summary">
          <span class="passed">${data.verification_passed} ✓</span>
          ${data.verification_failed > 0 ? `<span class="failed">${data.verification_failed} ✗</span>` : ""}
        </span>
      </div>
      ${data.has_evolution_patches ? `
      <div class="summary-item evolution-summary">
        <span class="summary-label">Evolution</span>
        <span class="summary-value">${data.evolution_patch_count} patches pending</span>
      </div>
      ` : ""}
    </div>
  `;
}
function renderUncertaintyNotes(notes) {
    if (notes.length === 0)
        return "";
    return `
    <div class="uncertainty-notes">
      <h4>Uncertainty Notes</h4>
      <ul>
        ${notes.map(n => `<li>${escapeHtml(n)}</li>`).join("")}
      </ul>
    </div>
  `;
}
function renderSection(title, items, collapsed = false) {
    if (items.length === 0)
        return "";
    const openAttr = collapsed ? "" : "open";
    return `
    <details class="boundary-section" ${openAttr}>
      <summary>${title} (${items.length})</summary>
      <div class="section-content">
        ${items.join("")}
      </div>
    </details>
  `;
}
export function renderBoundaryReviewPanel(data) {
    const assumptionCards = data.assumptions.map(renderAssumptionCard);
    const decisionCards = data.decisions.map(renderDecisionCard);
    const detourCards = data.detours.map(renderDetourCard);
    const verificationCards = data.verifications.map(renderVerificationCard);
    return `
    <div class="boundary-review-panel" data-run-id="${data.run_id}" data-scope="${data.scope}">
      <div class="panel-header">
        <h3>Boundary Review</h3>
        ${data.current_flow ? `<span class="current-flow">Flow: ${data.current_flow}</span>` : ""}
        <button class="toggle-expand" title="Toggle expand">
          ${isExpanded ? "▼" : "▶"}
        </button>
      </div>

      ${renderSummaryBar(data)}
      ${renderUncertaintyNotes(data.uncertainty_notes)}

      <div class="boundary-sections ${isExpanded ? "expanded" : "collapsed"}">
        ${renderSection("Assumptions", assumptionCards, assumptionCards.length > 5)}
        ${renderSection("Decisions", decisionCards, decisionCards.length > 5)}
        ${renderSection("Detours", detourCards)}
        ${renderSection("Verification Results", verificationCards, verificationCards.length > 5)}
      </div>
    </div>
  `;
}
// =============================================================================
// Public API
// =============================================================================
/**
 * Load and render boundary review for a run.
 * Uses monotonic request ID guard to prevent out-of-order UI renders
 * when multiple requests are in flight (e.g., under bursty SSE).
 */
export async function loadBoundaryReview(runId, options) {
    const seq = ++loadSeq;
    try {
        currentRunId = runId;
        const data = await Api.getBoundaryReview(runId, options);
        // Ignore stale response if a newer request was initiated
        if (seq !== loadSeq) {
            return currentData;
        }
        currentData = data;
        return currentData;
    }
    catch (err) {
        // Only update state if this is still the latest request
        if (seq === loadSeq) {
            console.error("Failed to load boundary review:", err);
            currentData = null;
        }
        return null;
    }
}
/**
 * Get the current boundary review data.
 */
export function getCurrentBoundaryData() {
    return currentData;
}
/**
 * Toggle the expanded state of the panel.
 */
export function toggleExpanded() {
    isExpanded = !isExpanded;
}
/**
 * Set up event handlers for the boundary review panel.
 */
export function setupBoundaryReviewHandlers(container) {
    // Toggle expand button
    container.addEventListener("click", (e) => {
        const target = e.target;
        if (target.classList.contains("toggle-expand")) {
            toggleExpanded();
            const sections = container.querySelector(".boundary-sections");
            if (sections) {
                sections.classList.toggle("expanded", isExpanded);
                sections.classList.toggle("collapsed", !isExpanded);
            }
            target.textContent = isExpanded ? "▼" : "▶";
        }
    });
}
/**
 * Update the boundary review panel in a container.
 */
export async function updateBoundaryReviewPanel(container, runId, options) {
    const data = await loadBoundaryReview(runId, options);
    if (data) {
        container.innerHTML = renderBoundaryReviewPanel(data);
        setupBoundaryReviewHandlers(container);
    }
    else {
        container.innerHTML = `
      <div class="boundary-review-panel empty">
        <div class="panel-header">
          <h3>Boundary Review</h3>
        </div>
        <div class="empty-message">No boundary data available for this run.</div>
      </div>
    `;
    }
}
// =============================================================================
// Utility
// =============================================================================
function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
}
// =============================================================================
// CSS (injected on first use)
// =============================================================================
let cssInjected = false;
export function injectBoundaryReviewCSS() {
    if (cssInjected)
        return;
    cssInjected = true;
    const style = document.createElement("style");
    style.textContent = `
    .boundary-review-panel {
      background: var(--bg-secondary, #f5f5f5);
      border-radius: 8px;
      padding: 16px;
      margin: 8px 0;
    }

    .boundary-review-panel .panel-header {
      display: flex;
      align-items: center;
      gap: 12px;
      margin-bottom: 12px;
    }

    .boundary-review-panel .panel-header h3 {
      margin: 0;
      font-size: 16px;
      font-weight: 600;
    }

    .boundary-review-panel .current-flow {
      color: var(--text-secondary, #666);
      font-size: 12px;
    }

    .boundary-review-panel .toggle-expand {
      margin-left: auto;
      background: none;
      border: none;
      cursor: pointer;
      font-size: 12px;
      padding: 4px 8px;
    }

    .boundary-summary-bar {
      display: flex;
      flex-wrap: wrap;
      gap: 16px;
      margin-bottom: 12px;
      padding: 8px;
      background: var(--bg-tertiary, #e8e8e8);
      border-radius: 4px;
    }

    .summary-item {
      display: flex;
      flex-direction: column;
      gap: 2px;
    }

    .summary-label {
      font-size: 10px;
      text-transform: uppercase;
      color: var(--text-tertiary, #888);
    }

    .summary-value {
      font-size: 14px;
      font-weight: 500;
    }

    .confidence-summary.confidence-high { color: #22c55e; }
    .confidence-summary.confidence-medium { color: #f59e0b; }
    .confidence-summary.confidence-low { color: #ef4444; }

    .verification-summary .passed { color: #22c55e; }
    .verification-summary .failed { color: #ef4444; margin-left: 8px; }

    .evolution-summary .summary-value { color: #8b5cf6; }

    .uncertainty-notes {
      background: #fef3c7;
      border: 1px solid #fbbf24;
      border-radius: 4px;
      padding: 8px 12px;
      margin-bottom: 12px;
    }

    .uncertainty-notes h4 {
      margin: 0 0 4px 0;
      font-size: 12px;
      color: #92400e;
    }

    .uncertainty-notes ul {
      margin: 0;
      padding-left: 16px;
      font-size: 12px;
      color: #78350f;
    }

    .boundary-sections.collapsed .boundary-section:not([open]) .section-content {
      display: none;
    }

    .boundary-section {
      margin-bottom: 8px;
      border: 1px solid var(--border-color, #ddd);
      border-radius: 4px;
      overflow: hidden;
    }

    .boundary-section summary {
      padding: 8px 12px;
      background: var(--bg-tertiary, #e8e8e8);
      cursor: pointer;
      font-weight: 500;
    }

    .section-content {
      padding: 8px;
      display: grid;
      gap: 8px;
    }

    .boundary-card {
      background: white;
      border: 1px solid var(--border-color, #ddd);
      border-radius: 4px;
      padding: 8px 12px;
    }

    .card-header {
      display: flex;
      align-items: center;
      gap: 8px;
      margin-bottom: 4px;
    }

    .card-id {
      font-family: monospace;
      font-size: 11px;
      color: var(--text-tertiary, #888);
    }

    .card-status {
      font-size: 11px;
      padding: 2px 6px;
      border-radius: 4px;
    }

    .status-active { background: #dbeafe; color: #1d4ed8; }
    .status-resolved { background: #dcfce7; color: #166534; }

    .card-confidence {
      font-size: 10px;
      padding: 2px 6px;
      border-radius: 4px;
      margin-left: auto;
    }

    .confidence-high { background: #dcfce7; color: #166534; }
    .confidence-medium { background: #fef3c7; color: #92400e; }
    .confidence-low { background: #fee2e2; color: #991b1b; }

    .assumption-card.assumption-low {
      border-left: 3px solid #ef4444;
    }

    .card-statement, .card-subject, .card-decision, .card-reason {
      font-size: 13px;
      margin-bottom: 4px;
    }

    .card-details {
      margin-top: 8px;
      font-size: 12px;
    }

    .card-details summary {
      cursor: pointer;
      color: var(--text-secondary, #666);
    }

    .card-detail-row {
      display: flex;
      gap: 8px;
      margin-top: 4px;
    }

    .card-detail-row label {
      color: var(--text-tertiary, #888);
      min-width: 100px;
    }

    .agent-badge, .tag {
      display: inline-block;
      padding: 1px 6px;
      background: var(--bg-tertiary, #e8e8e8);
      border-radius: 3px;
      font-size: 11px;
    }

    .tag-list {
      display: flex;
      gap: 4px;
      flex-wrap: wrap;
    }

    .assumption-ref {
      font-family: monospace;
      font-size: 10px;
      padding: 1px 4px;
      background: #dbeafe;
      border-radius: 2px;
    }

    .card-type {
      font-size: 10px;
      text-transform: uppercase;
      color: var(--text-tertiary, #888);
    }

    .card-path {
      display: flex;
      align-items: center;
      gap: 8px;
      font-family: monospace;
      font-size: 12px;
    }

    .card-path .arrow {
      color: var(--text-tertiary, #888);
    }

    .verification-card.status-verified {
      border-left: 3px solid #22c55e;
    }

    .verification-card.status-unverified {
      border-left: 3px solid #ef4444;
    }

    .status-icon {
      font-weight: bold;
    }

    .status-verified .status-icon { color: #22c55e; }
    .status-unverified .status-icon { color: #ef4444; }

    .card-station {
      font-size: 11px;
      color: var(--text-tertiary, #888);
    }

    .card-issues ul {
      margin: 4px 0 0 0;
      padding-left: 16px;
      font-size: 12px;
      color: #991b1b;
    }

    .boundary-review-panel.empty {
      text-align: center;
      color: var(--text-secondary, #666);
    }

    .empty-message {
      padding: 24px;
      font-style: italic;
    }
  `;
    document.head.appendChild(style);
}
