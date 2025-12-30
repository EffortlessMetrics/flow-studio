// swarm/tools/flow_studio_ui/src/components/ValidationModal.ts
// Validation modal for FlowEditor save operations
//
// Displays validation results with severity-based categorization:
// - CRITICAL: Block save entirely, must fix first
// - WARNING: Allow "Save Anyway" with confirmation
// - INFO: Informational only, always allow save
//
// NO filesystem operations - all data flows through the component.
import { escapeHtml, createModalFocusManager, } from "../utils.js";
/**
 * Icons for each severity level
 */
const SEVERITY_ICONS = {
    CRITICAL: "\u274c", // Red X
    WARNING: "\u26a0\ufe0f", // Warning
    INFO: "\u2139\ufe0f", // Info
};
/**
 * Colors for each severity level
 */
const SEVERITY_COLORS = {
    CRITICAL: { bg: "#fee2e2", text: "#991b1b", border: "#dc2626" },
    WARNING: { bg: "#fef3c7", text: "#92400e", border: "#f59e0b" },
    INFO: { bg: "#dbeafe", text: "#1e40af", border: "#3b82f6" },
};
/**
 * Labels for each severity level
 */
const SEVERITY_LABELS = {
    CRITICAL: "Critical Error",
    WARNING: "Warning",
    INFO: "Suggestion",
};
// ============================================================================
// ValidationModal Component
// ============================================================================
/**
 * Modal component for displaying validation results.
 *
 * Features:
 * - Groups issues by severity
 * - Shows actionable fix suggestions
 * - Blocks save on critical errors
 * - Allows "Save Anyway" for warnings
 * - Returns user decision via Promise
 */
export class ValidationModal {
    constructor(options = {}) {
        this.modal = null;
        this.focusManager = null;
        this.resolvePromise = null;
        this.options = {
            container: document.body,
            ...options,
        };
    }
    // ==========================================================================
    // Public Methods
    // ==========================================================================
    /**
     * Show the validation modal and wait for user decision.
     *
     * @param result - The validation result to display
     * @returns Promise resolving to user's decision
     */
    async show(result) {
        // Remove any existing modal
        this.destroy();
        return new Promise((resolve) => {
            this.resolvePromise = resolve;
            this.render(result);
        });
    }
    /**
     * Close the modal and clean up
     */
    close(decision = "cancel") {
        if (this.focusManager) {
            this.focusManager.close();
        }
        if (this.modal) {
            this.modal.remove();
            this.modal = null;
        }
        if (this.resolvePromise) {
            this.resolvePromise(decision);
            this.resolvePromise = null;
        }
        if (this.options.onClose) {
            this.options.onClose();
        }
    }
    /**
     * Destroy the modal instance
     */
    destroy() {
        if (this.modal) {
            this.modal.remove();
            this.modal = null;
        }
        this.focusManager = null;
        this.resolvePromise = null;
    }
    // ==========================================================================
    // Rendering
    // ==========================================================================
    /**
     * Render the modal with validation results
     */
    render(result) {
        this.modal = document.createElement("div");
        this.modal.className = "validation-modal-overlay";
        this.modal.setAttribute("role", "dialog");
        this.modal.setAttribute("aria-modal", "true");
        this.modal.setAttribute("aria-labelledby", "validation-modal-title");
        this.modal.setAttribute("data-uiid", "flow_studio.modal.validation");
        const hasCritical = result.summary.critical > 0;
        const hasWarnings = result.summary.warning > 0;
        this.modal.innerHTML = `
      <style>
        .validation-modal-overlay {
          position: fixed;
          top: 0;
          left: 0;
          right: 0;
          bottom: 0;
          background: rgba(0, 0, 0, 0.5);
          display: flex;
          align-items: center;
          justify-content: center;
          z-index: 2000;
          opacity: 0;
          animation: fadeIn 0.15s ease-out forwards;
        }

        @keyframes fadeIn {
          to { opacity: 1; }
        }

        .validation-modal-content {
          background: white;
          border-radius: 8px;
          box-shadow: 0 20px 40px rgba(0, 0, 0, 0.2);
          max-width: 560px;
          width: 90%;
          max-height: 80vh;
          overflow: hidden;
          display: flex;
          flex-direction: column;
          animation: slideUp 0.2s ease-out;
        }

        @keyframes slideUp {
          from {
            opacity: 0;
            transform: translateY(10px);
          }
          to {
            opacity: 1;
            transform: translateY(0);
          }
        }

        .validation-modal-header {
          padding: 16px 20px;
          border-bottom: 1px solid #e5e7eb;
          display: flex;
          align-items: center;
          gap: 12px;
        }

        .validation-modal-icon {
          font-size: 24px;
        }

        .validation-modal-title {
          margin: 0;
          font-size: 18px;
          font-weight: 600;
          color: #111827;
          flex: 1;
        }

        .validation-modal-close {
          background: none;
          border: none;
          font-size: 20px;
          cursor: pointer;
          padding: 4px;
          color: #6b7280;
        }

        .validation-modal-close:hover {
          color: #111827;
        }

        .validation-modal-body {
          padding: 16px 20px;
          overflow-y: auto;
          flex: 1;
        }

        .validation-summary {
          display: flex;
          gap: 16px;
          margin-bottom: 16px;
          padding: 12px;
          background: #f9fafb;
          border-radius: 6px;
        }

        .validation-summary-item {
          display: flex;
          align-items: center;
          gap: 6px;
          font-size: 14px;
        }

        .validation-summary-count {
          font-weight: 600;
          min-width: 20px;
        }

        .validation-section {
          margin-bottom: 16px;
        }

        .validation-section-title {
          font-size: 13px;
          font-weight: 600;
          margin-bottom: 8px;
          color: #374151;
          display: flex;
          align-items: center;
          gap: 6px;
        }

        .validation-issue {
          padding: 10px 12px;
          border-radius: 6px;
          margin-bottom: 8px;
          border-left: 3px solid;
        }

        .validation-issue-header {
          display: flex;
          align-items: flex-start;
          gap: 8px;
        }

        .validation-issue-icon {
          font-size: 14px;
          flex-shrink: 0;
          margin-top: 2px;
        }

        .validation-issue-content {
          flex: 1;
        }

        .validation-issue-message {
          font-size: 14px;
          color: #111827;
          margin-bottom: 4px;
        }

        .validation-issue-code {
          font-size: 11px;
          font-family: monospace;
          color: #6b7280;
          background: rgba(0, 0, 0, 0.05);
          padding: 2px 6px;
          border-radius: 3px;
          display: inline-block;
          margin-bottom: 4px;
        }

        .validation-issue-path {
          font-size: 12px;
          font-family: monospace;
          color: #6b7280;
        }

        .validation-issue-fix {
          font-size: 12px;
          color: #059669;
          margin-top: 6px;
          padding: 6px 8px;
          background: #ecfdf5;
          border-radius: 4px;
        }

        .validation-modal-footer {
          padding: 12px 20px;
          border-top: 1px solid #e5e7eb;
          display: flex;
          justify-content: flex-end;
          gap: 8px;
        }

        .validation-btn {
          padding: 8px 16px;
          border-radius: 6px;
          font-size: 14px;
          font-weight: 500;
          cursor: pointer;
          transition: all 0.15s ease;
        }

        .validation-btn-primary {
          background: #3b82f6;
          color: white;
          border: none;
        }

        .validation-btn-primary:hover {
          background: #2563eb;
        }

        .validation-btn-secondary {
          background: white;
          color: #374151;
          border: 1px solid #d1d5db;
        }

        .validation-btn-secondary:hover {
          background: #f9fafb;
        }

        .validation-btn-warning {
          background: #f59e0b;
          color: white;
          border: none;
        }

        .validation-btn-warning:hover {
          background: #d97706;
        }

        .validation-btn:disabled {
          opacity: 0.5;
          cursor: not-allowed;
        }

        .validation-blocking-notice {
          padding: 12px;
          background: #fee2e2;
          border: 1px solid #dc2626;
          border-radius: 6px;
          color: #991b1b;
          font-size: 13px;
          margin-bottom: 16px;
        }
      </style>

      <div class="validation-modal-content" data-uiid="flow_studio.modal.validation.content">
        <div class="validation-modal-header">
          <span class="validation-modal-icon">${hasCritical ? SEVERITY_ICONS.CRITICAL : SEVERITY_ICONS.WARNING}</span>
          <h2 class="validation-modal-title" id="validation-modal-title">
            ${hasCritical ? "Cannot Save - Critical Errors" : "Validation Warnings"}
          </h2>
          <button class="validation-modal-close" data-action="close" aria-label="Close">\u00d7</button>
        </div>

        <div class="validation-modal-body">
          ${this.renderSummary(result)}
          ${hasCritical ? this.renderBlockingNotice() : ""}
          ${this.renderIssuesBySection(result.issues)}
        </div>

        <div class="validation-modal-footer">
          ${this.renderActions(hasCritical, hasWarnings)}
        </div>
      </div>
    `;
        // Append to container
        const container = this.options.container || document.body;
        container.appendChild(this.modal);
        // Set up focus management
        const content = this.modal.querySelector(".validation-modal-content");
        if (content) {
            this.focusManager = createModalFocusManager(this.modal, ".validation-modal-content");
            this.focusManager.open();
        }
        // Set up event listeners
        this.attachEventListeners();
    }
    /**
     * Render the summary counts
     */
    renderSummary(result) {
        const { summary } = result;
        return `
      <div class="validation-summary">
        ${summary.critical > 0 ? `
          <div class="validation-summary-item">
            <span>${SEVERITY_ICONS.CRITICAL}</span>
            <span class="validation-summary-count" style="color: ${SEVERITY_COLORS.CRITICAL.text}">${summary.critical}</span>
            <span>Critical</span>
          </div>
        ` : ""}
        ${summary.warning > 0 ? `
          <div class="validation-summary-item">
            <span>${SEVERITY_ICONS.WARNING}</span>
            <span class="validation-summary-count" style="color: ${SEVERITY_COLORS.WARNING.text}">${summary.warning}</span>
            <span>Warnings</span>
          </div>
        ` : ""}
        ${summary.info > 0 ? `
          <div class="validation-summary-item">
            <span>${SEVERITY_ICONS.INFO}</span>
            <span class="validation-summary-count" style="color: ${SEVERITY_COLORS.INFO.text}">${summary.info}</span>
            <span>Suggestions</span>
          </div>
        ` : ""}
      </div>
    `;
    }
    /**
     * Render blocking notice for critical errors
     */
    renderBlockingNotice() {
        return `
      <div class="validation-blocking-notice">
        <strong>Save blocked:</strong> Critical errors must be fixed before saving.
        Review the issues below and use "Fix Issues" to return to the editor.
      </div>
    `;
    }
    /**
     * Render issues grouped by severity
     */
    renderIssuesBySection(issues) {
        const grouped = {
            CRITICAL: [],
            WARNING: [],
            INFO: [],
        };
        for (const issue of issues) {
            grouped[issue.severity].push(issue);
        }
        const sections = [];
        for (const severity of ["CRITICAL", "WARNING", "INFO"]) {
            const sectionIssues = grouped[severity];
            if (sectionIssues.length === 0)
                continue;
            sections.push(`
        <div class="validation-section">
          <div class="validation-section-title">
            ${SEVERITY_ICONS[severity]} ${SEVERITY_LABELS[severity]}s (${sectionIssues.length})
          </div>
          ${sectionIssues.map((issue) => this.renderIssue(issue)).join("")}
        </div>
      `);
        }
        return sections.join("");
    }
    /**
     * Render a single issue
     */
    renderIssue(issue) {
        const colors = SEVERITY_COLORS[issue.severity];
        return `
      <div class="validation-issue" style="background: ${colors.bg}; border-left-color: ${colors.border};">
        <div class="validation-issue-header">
          <span class="validation-issue-icon">${SEVERITY_ICONS[issue.severity]}</span>
          <div class="validation-issue-content">
            <div class="validation-issue-code">${escapeHtml(issue.code)}</div>
            <div class="validation-issue-message">${escapeHtml(issue.message)}</div>
            ${issue.path ? `<div class="validation-issue-path">${escapeHtml(issue.path)}</div>` : ""}
            ${issue.fix ? `<div class="validation-issue-fix">\u2192 ${escapeHtml(issue.fix)}</div>` : ""}
          </div>
        </div>
      </div>
    `;
    }
    /**
     * Render action buttons based on error severity
     */
    renderActions(hasCritical, hasWarnings) {
        if (hasCritical) {
            // Critical errors: only "Fix Issues" button
            return `
        <button class="validation-btn validation-btn-primary" data-action="fix" data-uiid="flow_studio.modal.validation.fix">
          Fix Issues
        </button>
      `;
        }
        if (hasWarnings) {
            // Warnings only: "Fix Issues" and "Save Anyway" buttons
            return `
        <button class="validation-btn validation-btn-secondary" data-action="fix" data-uiid="flow_studio.modal.validation.fix">
          Fix Issues
        </button>
        <button class="validation-btn validation-btn-warning" data-action="save" data-uiid="flow_studio.modal.validation.save_anyway">
          Save Anyway
        </button>
      `;
        }
        // Info only: "Close" and "Save" buttons
        return `
      <button class="validation-btn validation-btn-secondary" data-action="close" data-uiid="flow_studio.modal.validation.close">
        Close
      </button>
      <button class="validation-btn validation-btn-primary" data-action="save" data-uiid="flow_studio.modal.validation.save">
        Save
      </button>
    `;
    }
    /**
     * Attach event listeners
     */
    attachEventListeners() {
        if (!this.modal)
            return;
        // Handle button clicks
        this.modal.addEventListener("click", (e) => {
            const target = e.target;
            const action = target.dataset.action || target.closest("[data-action]")?.getAttribute("data-action");
            if (action === "close" || action === "cancel") {
                this.close("cancel");
            }
            else if (action === "fix") {
                this.close("fix");
            }
            else if (action === "save") {
                this.close("save");
            }
            // Close on backdrop click
            if (target.classList.contains("validation-modal-overlay")) {
                this.close("cancel");
            }
        });
        // Handle keyboard
        this.modal.addEventListener("keydown", (e) => {
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
 * Create a new validation modal instance
 */
export function createValidationModal(options) {
    return new ValidationModal(options);
}
