// swarm/tools/flow_studio_ui/src/run_detail_modal.ts
// Run Detail Modal for Flow Studio
//
// This module handles:
// - Displaying detailed information about a selected run
// - Run metadata (ID, backend, profile, timestamps)
// - Flow progress and status
// - Re-run and close actions
import { Api } from "./api.js";
import { escapeHtml, formatDateTime, createModalFocusManager } from "./utils.js";
import { updateCompactInventory, injectInventoryCSS } from "./inventory_counts.js";
import { updateBoundaryReviewPanel, injectBoundaryReviewCSS } from "./boundary_review.js";
// ============================================================================
// Module State
// ============================================================================
let _callbacks = {};
let _focusManager = null;
let _currentRunId = null;
// ============================================================================
// Configuration
// ============================================================================
/**
 * Configure the run detail modal with callbacks.
 */
export function configure(callbacks = {}) {
    _callbacks = callbacks;
}
// ============================================================================
// Modal Visibility
// ============================================================================
/**
 * Get or create the modal element.
 */
function getOrCreateModal() {
    let modal = document.getElementById("run-detail-modal");
    if (modal)
        return modal;
    // Create modal structure
    modal = document.createElement("div");
    modal.id = "run-detail-modal";
    modal.className = "selftest-modal"; // Reuse selftest modal styling
    modal.setAttribute("data-uiid", "flow_studio.modal.run_detail");
    modal.setAttribute("role", "dialog");
    modal.setAttribute("aria-modal", "true");
    modal.setAttribute("aria-labelledby", "run-detail-modal-title");
    modal.innerHTML = `
    <div class="selftest-step-content" data-uiid="flow_studio.modal.run_detail.body">
      <button class="selftest-modal-close" data-uiid="flow_studio.modal.run_detail.close" aria-label="Close modal">&times;</button>
      <div id="run-detail-modal-content">
        <div class="muted">Loading...</div>
      </div>
    </div>
  `;
    document.body.appendChild(modal);
    // Initialize close handlers
    initModalCloseHandlers(modal);
    return modal;
}
/**
 * Initialize modal close handlers.
 */
function initModalCloseHandlers(modal) {
    // Close on backdrop click
    modal.addEventListener("click", (e) => {
        if (e.target === modal) {
            closeRunDetailModal();
        }
    });
    // Close on Escape key
    modal.addEventListener("keydown", (e) => {
        if (e.key === "Escape") {
            e.preventDefault();
            closeRunDetailModal();
        }
    });
    // Close button click
    const closeBtn = modal.querySelector('[data-uiid="flow_studio.modal.run_detail.close"]');
    if (closeBtn) {
        closeBtn.addEventListener("click", () => closeRunDetailModal());
    }
}
/**
 * Toggle modal visibility with focus management.
 */
function toggleModal(show) {
    const modal = getOrCreateModal();
    // Lazy-init focus manager
    if (!_focusManager) {
        _focusManager = createModalFocusManager(modal, ".selftest-step-content");
    }
    if (show) {
        modal.classList.add("open");
        _focusManager.open(document.activeElement);
    }
    else {
        modal.classList.remove("open");
        _focusManager.close();
    }
}
// ============================================================================
// Public API
// ============================================================================
/**
 * Show the run detail modal for a specific run.
 */
export async function showRunDetailModal(runId) {
    _currentRunId = runId;
    const modal = getOrCreateModal();
    const contentEl = modal.querySelector("#run-detail-modal-content");
    if (contentEl) {
        contentEl.innerHTML = '<div class="muted">Loading run details...</div>';
    }
    toggleModal(true);
    try {
        const summary = await Api.getRunSummary(runId);
        if (contentEl) {
            contentEl.innerHTML = renderRunDetailContent(runId, summary);
            attachActionHandlers(modal, runId, summary);
        }
    }
    catch (err) {
        console.error("Failed to load run details", err);
        if (contentEl) {
            contentEl.innerHTML = renderRunDetailError(runId, err);
        }
    }
}
/**
 * Close the run detail modal.
 */
export function closeRunDetailModal() {
    toggleModal(false);
    _currentRunId = null;
    if (_callbacks.onClose) {
        _callbacks.onClose();
    }
}
// ============================================================================
// Rendering
// ============================================================================
/**
 * Render the run detail modal content.
 */
export function renderRunDetailContent(runId, summary) {
    const statusClass = getStatusClass(summary.status);
    const statusLabel = getStatusLabel(summary.status);
    const flowProgress = renderFlowProgress(summary.flows);
    const tagsHtml = renderTags(summary.tags, summary.is_exemplar, runId);
    return `
    <h3 id="run-detail-modal-title" class="selftest-step-title">Run Details</h3>

    <div class="selftest-step-header" style="flex-wrap: wrap; gap: 8px;">
      <div class="selftest-step-id">${escapeHtml(runId)}</div>
      <div class="${statusClass}" style="padding: 3px 8px; border-radius: 3px; font-size: 10px; font-weight: 600;">
        ${statusLabel}
      </div>
    </div>

    ${summary.title ? `<div class="fs-text-body" style="margin-bottom: 12px; color: #374151;">${escapeHtml(summary.title)}</div>` : ""}

    <div class="selftest-step-metadata" style="grid-template-columns: 1fr 1fr 1fr;">
      <div class="selftest-metadata-row">
        <div class="selftest-metadata-label">Run ID</div>
        <div class="selftest-metadata-value mono" style="font-size: 11px; word-break: break-all;">${escapeHtml(runId)}</div>
      </div>
      <div class="selftest-metadata-row">
        <div class="selftest-metadata-label">Backend</div>
        <div class="selftest-metadata-value">${escapeHtml(summary.backend || "unknown")}</div>
      </div>
      <div class="selftest-metadata-row">
        <div class="selftest-metadata-label">Profile</div>
        <div class="selftest-metadata-value">${escapeHtml(summary.profile_id || "(none)")}</div>
      </div>
    </div>

    <div class="selftest-step-metadata" style="grid-template-columns: 1fr 1fr 1fr;">
      <div class="selftest-metadata-row">
        <div class="selftest-metadata-label">Created</div>
        <div class="selftest-metadata-value">${formatDateTime(summary.created_at || null)}</div>
      </div>
      <div class="selftest-metadata-row">
        <div class="selftest-metadata-label">Started</div>
        <div class="selftest-metadata-value">${formatDateTime(summary.started_at || null)}</div>
      </div>
      <div class="selftest-metadata-row">
        <div class="selftest-metadata-label">Completed</div>
        <div class="selftest-metadata-value">${formatDateTime(summary.completed_at || null)}</div>
      </div>
    </div>

    <div class="kv-section" style="margin-top: 16px;">
      <div class="kv-label">Flow Progress</div>
      ${flowProgress}
    </div>

    <div class="kv-section" style="margin-top: 16px;" data-uiid="flow_studio.modal.run_detail.inventory">
      <div class="kv-label">Inventory Markers</div>
      <div id="run-detail-inventory-container" data-uiid="flow_studio.modal.run_detail.inventory.container" style="margin-top: 8px;">
        <div class="muted fs-text-xs">Loading inventory...</div>
      </div>
    </div>

    <div class="kv-section" style="margin-top: 16px;" data-uiid="flow_studio.modal.run_detail.boundary">
      <div class="kv-label" style="display: flex; align-items: center; gap: 8px;">
        <span>Boundary Summary</span>
        <button id="run-detail-boundary-toggle" class="fs-button-small" data-uiid="flow_studio.modal.run_detail.boundary.toggle" style="padding: 2px 8px; font-size: 10px;">Load Review</button>
      </div>
      <div id="run-detail-boundary-container" data-uiid="flow_studio.modal.run_detail.boundary.container" style="display: none; margin-top: 8px;">
        <div class="muted fs-text-xs">Click "Load Review" to view boundary data...</div>
      </div>
    </div>

    <div class="kv-section" style="margin-top: 16px;">
      <div class="kv-label" style="display: flex; align-items: center; gap: 8px;">
        <span>Events Timeline</span>
        <button id="run-detail-events-toggle" class="fs-button-small" data-uiid="flow_studio.modal.run_detail.events.toggle" style="padding: 2px 8px; font-size: 10px;">Load Events</button>
      </div>
      <div id="run-detail-events-container" data-uiid="flow_studio.modal.run_detail.events.container" style="display: none; margin-top: 8px; max-height: 200px; overflow-y: auto; background: #f9fafb; border-radius: 4px; padding: 8px;">
        <div class="muted fs-text-xs">Click "Load Events" to view execution events...</div>
      </div>
    </div>

    <div class="kv-section" style="margin-top: 16px;" data-uiid="flow_studio.modal.run_detail.wisdom">
      <div class="kv-label" style="display: flex; align-items: center; gap: 8px;">
        <span>Wisdom Summary</span>
        <button id="run-detail-wisdom-toggle" class="fs-button-small" data-uiid="flow_studio.modal.run_detail.wisdom.toggle" style="padding: 2px 8px; font-size: 10px;">Load Wisdom</button>
      </div>
      <div id="run-detail-wisdom-container" data-uiid="flow_studio.modal.run_detail.wisdom.container" style="display: none; margin-top: 8px; background: #f0fdf4; border-radius: 4px; padding: 12px;">
        <div class="muted fs-text-xs">Click "Load Wisdom" to view wisdom metrics...</div>
      </div>
    </div>

    ${summary.error_message ? `
      <div class="selftest-dependencies" style="background: #fee2e2; border-left-color: #ef4444; margin-top: 16px;">
        <div class="selftest-dependencies-title" style="color: #991b1b;">Error</div>
        <div class="fs-text-sm" style="color: #7f1d1d; word-break: break-word;">${escapeHtml(summary.error_message)}</div>
      </div>
    ` : ""}

    ${tagsHtml}

    <div style="display: flex; flex-direction: column; gap: 8px; margin-top: 20px; padding-top: 16px; border-top: 1px solid #e5e7eb;">
      <div id="run-detail-rerun-error" class="fs-text-sm" style="color: #dc2626; min-height: 0;"></div>
      <div style="display: flex; gap: 12px;">
        <button id="run-detail-rerun-btn" data-uiid="flow_studio.modal.run_detail.rerun" class="fs-button-primary" style="flex: 1;">
          Re-run
        </button>
        <button id="run-detail-close-btn" class="fs-button-small" style="flex: 1;">
          Close
        </button>
      </div>
    </div>
  `;
}
/**
 * Render error state for run detail modal.
 */
function renderRunDetailError(runId, error) {
    return `
    <h3 id="run-detail-modal-title" class="selftest-step-title">Run Details</h3>

    <div class="fs-error" style="margin: 16px 0;">
      <div class="fs-error-icon">\u26A0\uFE0F</div>
      <p class="fs-error-title">Failed to load run</p>
      <p class="fs-error-description">${escapeHtml(error.message || "Unknown error")}</p>
    </div>

    <div class="selftest-step-header">
      <div class="selftest-step-id">${escapeHtml(runId)}</div>
    </div>

    <div style="display: flex; gap: 12px; margin-top: 20px; padding-top: 16px; border-top: 1px solid #e5e7eb;">
      <button id="run-detail-close-btn" class="fs-button-small" style="flex: 1;">
        Close
      </button>
    </div>
  `;
}
/**
 * Render flow progress section.
 */
function renderFlowProgress(flows) {
    if (!flows) {
        return '<div class="muted fs-text-sm">No flow data available</div>';
    }
    const flowOrder = ["signal", "plan", "build", "gate", "deploy", "wisdom", "stepwise-demo"];
    const flowLabels = {
        signal: "Signal",
        plan: "Plan",
        build: "Build",
        gate: "Gate",
        deploy: "Deploy",
        wisdom: "Wisdom",
        "stepwise-demo": "Stepwise"
    };
    const flowItems = flowOrder.map(key => {
        const flowData = flows[key];
        const status = flowData?.status || "not_started";
        const icon = getFlowStatusIcon(status);
        const statusClass = getFlowStatusClass(status);
        const label = flowLabels[key] || key;
        return `
      <div class="flow-progress-item" style="display: flex; align-items: center; gap: 8px; padding: 6px 0; border-bottom: 1px solid #f3f4f6;">
        <span class="flow-progress-icon" style="font-size: 14px;">${icon}</span>
        <span class="flow-progress-label fs-text-sm" style="flex: 1;">${escapeHtml(label)}</span>
        <span class="flow-progress-status ${statusClass}" style="font-size: 11px; font-weight: 500;">${escapeHtml(status.toUpperCase())}</span>
      </div>
    `;
    });
    return `<div class="flow-progress-list">${flowItems.join("")}</div>`;
}
/**
 * Render tags and exemplar checkbox.
 */
function renderTags(tags, isExemplar, runId) {
    const tagBadges = [];
    if (tags && tags.length > 0) {
        tags.forEach(tag => {
            tagBadges.push(`<span class="selftest-ac-badge">${escapeHtml(tag)}</span>`);
        });
    }
    const exemplarChecked = isExemplar ? "checked" : "";
    return `
    <div class="kv-section" style="margin-top: 16px;">
      <div class="kv-label">Run Settings</div>
      <div style="margin-top: 8px;">
        <label style="display: flex; align-items: center; gap: 8px; cursor: pointer; font-size: 13px;">
          <input
            type="checkbox"
            id="run-detail-exemplar-checkbox"
            data-uiid="flow_studio.modal.run_detail.exemplar"
            ${exemplarChecked}
            style="width: 16px; height: 16px; cursor: pointer;"
          />
          <span>Mark as Exemplar</span>
          <span class="muted fs-text-xs" style="margin-left: 4px;">(Reference implementation)</span>
        </label>
        <div id="run-detail-exemplar-status" class="fs-text-xs muted" style="margin-left: 24px; margin-top: 4px; min-height: 16px;"></div>
      </div>
      ${tagBadges.length > 0 ? `
        <div style="margin-top: 12px;">
          <div class="kv-label">Tags</div>
          <div class="selftest-ac-badges" style="margin-top: 6px;">
            ${tagBadges.join("")}
          </div>
        </div>
      ` : ""}
    </div>
  `;
}
// ============================================================================
// Status Helpers
// ============================================================================
/**
 * Get CSS class for run status.
 */
function getStatusClass(status) {
    switch (status) {
        case "completed":
            return "fs-status-badge success";
        case "running":
            return "fs-status-badge info";
        case "failed":
            return "fs-status-badge error";
        case "canceled":
            return "fs-status-badge warning";
        case "pending":
        default:
            return "fs-status-badge";
    }
}
/**
 * Get label for run status.
 */
function getStatusLabel(status) {
    switch (status) {
        case "completed":
            return "\u2713 COMPLETED";
        case "running":
            return "\u25CF RUNNING";
        case "failed":
            return "\u2717 FAILED";
        case "canceled":
            return "\u2014 CANCELED";
        case "pending":
            return "\u2026 PENDING";
        default:
            return "\u2014 UNKNOWN";
    }
}
/**
 * Get icon for flow status.
 */
function getFlowStatusIcon(status) {
    switch (status) {
        case "done":
        case "complete":
            return "\u2705";
        case "in_progress":
            return "\u23F3";
        case "partial":
            return "\u26A0\uFE0F";
        case "missing":
        case "not_started":
        default:
            return "\u2B1C";
    }
}
/**
 * Get CSS class for flow status.
 */
function getFlowStatusClass(status) {
    switch (status) {
        case "done":
        case "complete":
            return "status-complete";
        case "in_progress":
            return "status-partial";
        case "partial":
            return "status-partial";
        case "missing":
            return "status-missing";
        case "not_started":
        default:
            return "status-na";
    }
}
// ============================================================================
// Action Handlers
// ============================================================================
/**
 * Attach action handlers to modal buttons.
 */
function attachActionHandlers(modal, runId, summary) {
    // Inject CSS for inventory and boundary components
    injectInventoryCSS();
    injectBoundaryReviewCSS();
    // Load inventory counts immediately (compact view)
    const inventoryContainer = modal.querySelector("#run-detail-inventory-container");
    if (inventoryContainer) {
        updateCompactInventory(inventoryContainer, runId).catch((err) => {
            console.error("Failed to load inventory counts", err);
            inventoryContainer.innerHTML = '<span class="muted fs-text-xs">Failed to load inventory data.</span>';
        });
    }
    // Boundary review toggle button (lazy-load on click)
    const boundaryToggle = modal.querySelector("#run-detail-boundary-toggle");
    const boundaryContainer = modal.querySelector("#run-detail-boundary-container");
    if (boundaryToggle && boundaryContainer) {
        boundaryToggle.addEventListener("click", async () => {
            const btn = boundaryToggle;
            const container = boundaryContainer;
            // Toggle visibility
            if (container.style.display === "none") {
                container.style.display = "block";
                btn.textContent = "Loading...";
                btn.disabled = true;
                try {
                    await updateBoundaryReviewPanel(container, runId, { scope: "run" });
                    btn.textContent = "Hide Review";
                }
                catch (err) {
                    console.error("Failed to load boundary review", err);
                    container.innerHTML = `<div class="fs-text-xs" style="color: #dc2626;">Failed to load boundary review: ${escapeHtml(err.message || "Unknown error")}</div>`;
                    btn.textContent = "Retry";
                }
                finally {
                    btn.disabled = false;
                }
            }
            else {
                container.style.display = "none";
                btn.textContent = "Load Review";
            }
        });
    }
    // Exemplar checkbox
    const exemplarCheckbox = modal.querySelector("#run-detail-exemplar-checkbox");
    const exemplarStatus = modal.querySelector("#run-detail-exemplar-status");
    if (exemplarCheckbox) {
        exemplarCheckbox.addEventListener("change", async () => {
            const isExemplar = exemplarCheckbox.checked;
            exemplarCheckbox.disabled = true;
            if (exemplarStatus) {
                exemplarStatus.textContent = isExemplar ? "Marking as exemplar..." : "Removing exemplar status...";
                exemplarStatus.className = "fs-text-xs muted";
            }
            try {
                await Api.setRunExemplar(runId, isExemplar);
                if (exemplarStatus) {
                    exemplarStatus.textContent = isExemplar ? "Marked as exemplar" : "Exemplar status removed";
                    exemplarStatus.className = "fs-text-xs";
                    exemplarStatus.style.color = "#059669"; // Green for success
                    // Clear success message after 2 seconds
                    setTimeout(() => {
                        if (exemplarStatus) {
                            exemplarStatus.textContent = "";
                        }
                    }, 2000);
                }
            }
            catch (err) {
                console.error("Failed to update exemplar status", err);
                // Revert checkbox state on error
                exemplarCheckbox.checked = !isExemplar;
                if (exemplarStatus) {
                    exemplarStatus.textContent = `Error: ${err.message || "Failed to update"}`;
                    exemplarStatus.className = "fs-text-xs";
                    exemplarStatus.style.color = "#dc2626"; // Red for error
                }
            }
            finally {
                exemplarCheckbox.disabled = false;
            }
        });
    }
    // Re-run button
    const rerunBtn = modal.querySelector("#run-detail-rerun-btn");
    if (rerunBtn) {
        rerunBtn.addEventListener("click", async () => {
            const btn = rerunBtn;
            btn.disabled = true;
            btn.textContent = "Starting...";
            try {
                // Determine flows to run based on the original run's flows
                const flowsToRun = summary?.flows
                    ? Object.keys(summary.flows).filter(key => {
                        const flowData = summary.flows[key];
                        return flowData && flowData.status !== "not_started";
                    })
                    : ["signal", "plan", "build", "gate", "deploy", "wisdom"]; // Default: all flows
                // Start the new run via API
                const result = await Api.startRun({
                    flows: flowsToRun,
                    profile_id: summary?.profile_id,
                    backend: summary?.backend,
                });
                // Started new run: result.run_id
                // Call the callback if provided (for additional UI updates)
                if (_callbacks.onRerun) {
                    await _callbacks.onRerun(runId);
                }
                closeRunDetailModal();
            }
            catch (err) {
                console.error("Failed to re-run", err);
                btn.textContent = "Re-run";
                btn.disabled = false;
                // Show error in a status area if available
                const errorArea = modal.querySelector("#run-detail-rerun-error");
                if (errorArea) {
                    errorArea.textContent = `Error: ${err.message || "Failed to start run"}`;
                }
            }
        });
    }
    // Close button
    const closeBtn = modal.querySelector("#run-detail-close-btn");
    if (closeBtn) {
        closeBtn.addEventListener("click", () => closeRunDetailModal());
    }
    // Events toggle button
    const eventsToggle = modal.querySelector("#run-detail-events-toggle");
    const eventsContainer = modal.querySelector("#run-detail-events-container");
    if (eventsToggle && eventsContainer) {
        eventsToggle.addEventListener("click", async () => {
            const btn = eventsToggle;
            const container = eventsContainer;
            // Toggle visibility
            if (container.style.display === "none") {
                container.style.display = "block";
                btn.textContent = "Loading...";
                btn.disabled = true;
                try {
                    const response = await Api.getRunEvents(runId);
                    container.innerHTML = renderEventsTimeline(response.events);
                    btn.textContent = "Hide Events";
                }
                catch (err) {
                    console.error("Failed to load events", err);
                    container.innerHTML = `<div class="fs-text-xs" style="color: #dc2626;">Failed to load events: ${escapeHtml(err.message || "Unknown error")}</div>`;
                    btn.textContent = "Retry";
                }
                finally {
                    btn.disabled = false;
                }
            }
            else {
                container.style.display = "none";
                btn.textContent = "Load Events";
            }
        });
    }
    // Wisdom toggle button
    const wisdomToggle = modal.querySelector("#run-detail-wisdom-toggle");
    const wisdomContainer = modal.querySelector("#run-detail-wisdom-container");
    if (wisdomToggle && wisdomContainer) {
        wisdomToggle.addEventListener("click", async () => {
            const btn = wisdomToggle;
            const container = wisdomContainer;
            // Toggle visibility
            if (container.style.display === "none") {
                container.style.display = "block";
                btn.textContent = "Loading...";
                btn.disabled = true;
                try {
                    const wisdom = await Api.getRunWisdom(runId);
                    container.innerHTML = renderWisdomSummary(wisdom);
                    btn.textContent = "Hide Wisdom";
                }
                catch (err) {
                    console.error("Failed to load wisdom", err);
                    // 404 means no wisdom available - show helpful message
                    const errorMsg = err.message || "Unknown error";
                    if (errorMsg.includes("404")) {
                        container.innerHTML = renderWisdomEmpty(runId);
                    }
                    else {
                        container.innerHTML = `<div class="fs-text-xs" style="color: #dc2626;">Failed to load wisdom: ${escapeHtml(errorMsg)}</div>`;
                    }
                    btn.textContent = "Retry";
                }
                finally {
                    btn.disabled = false;
                }
            }
            else {
                container.style.display = "none";
                btn.textContent = "Load Wisdom";
            }
        });
    }
}
/**
 * Render events timeline.
 */
function renderEventsTimeline(events) {
    if (!events || events.length === 0) {
        return '<div class="muted fs-text-xs">No events recorded for this run.</div>';
    }
    const eventItems = events.map(event => {
        const time = event.ts ? new Date(event.ts).toLocaleTimeString() : "";
        const kindClass = getEventKindClass(event.kind);
        const payload = event.payload ? JSON.stringify(event.payload).slice(0, 100) : "";
        return `
      <div class="run-event-item" style="display: flex; gap: 8px; padding: 4px 0; border-bottom: 1px solid #e5e7eb; font-size: 11px;">
        <span class="mono" style="color: #6b7280; flex-shrink: 0; width: 70px;">${escapeHtml(time)}</span>
        <span class="${kindClass}" style="flex-shrink: 0; width: 100px; font-weight: 500;">${escapeHtml(event.kind)}</span>
        <span style="color: #9ca3af; flex-shrink: 0; width: 60px;">${escapeHtml(event.flow_key)}</span>
        ${event.step_id ? `<span style="color: #6b7280;">${escapeHtml(event.step_id)}</span>` : ""}
        ${payload ? `<span class="mono" style="color: #9ca3af; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${escapeHtml(payload)}</span>` : ""}
      </div>
    `;
    }).join("");
    return `<div class="run-events-list">${eventItems}</div>`;
}
/**
 * Get CSS class for event kind.
 */
function getEventKindClass(kind) {
    if (kind.includes("error") || kind.includes("fail"))
        return "fs-text-error";
    if (kind.includes("start") || kind.includes("created"))
        return "fs-text-info";
    if (kind.includes("end") || kind.includes("complete"))
        return "fs-text-success";
    return "";
}
/**
 * Render wisdom summary content.
 */
function renderWisdomSummary(wisdom) {
    const { summary, flows, labels, created_at } = wisdom;
    // Flow status rows
    const flowOrder = ["signal", "plan", "build", "gate", "deploy", "wisdom"];
    const flowRows = flowOrder.map(key => {
        const flowData = flows[key];
        const status = flowData?.status || "unknown";
        const dot = getWisdomStatusDot(status);
        const loopInfo = getLoopInfo(flowData);
        return `
      <div style="display: flex; align-items: center; gap: 8px; padding: 4px 0; border-bottom: 1px solid #d1fae5;">
        <span>${dot}</span>
        <span style="width: 60px; font-weight: 500; text-transform: capitalize;">${escapeHtml(key)}</span>
        <span style="color: #059669; font-size: 12px;">${escapeHtml(status)}</span>
        ${loopInfo ? `<span style="color: #6b7280; font-size: 11px; margin-left: auto;">${escapeHtml(loopInfo)}</span>` : ""}
      </div>
    `;
    }).join("");
    // Labels badges
    const labelBadges = labels.length > 0
        ? labels.map(l => `<span class="selftest-ac-badge" style="background: #dcfce7; color: #166534;">${escapeHtml(l)}</span>`).join(" ")
        : '<span class="muted fs-text-xs">No labels</span>';
    return `
    <div data-uiid="flow_studio.modal.run_detail.wisdom.summary">
      <div style="font-size: 11px; color: #6b7280; margin-bottom: 12px;">
        Generated: ${created_at ? formatDateTime(created_at) : "Unknown"}
      </div>

      <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-bottom: 16px;">
        <div style="background: #f0fdf4; padding: 8px; border-radius: 4px; text-align: center;">
          <div style="font-size: 20px; font-weight: 600; color: #166534;">${summary.artifacts_present}</div>
          <div style="font-size: 10px; color: #6b7280;">Artifacts</div>
        </div>
        <div style="background: ${summary.regressions_found > 0 ? "#fef2f2" : "#f0fdf4"}; padding: 8px; border-radius: 4px; text-align: center;">
          <div style="font-size: 20px; font-weight: 600; color: ${summary.regressions_found > 0 ? "#dc2626" : "#166534"};">${summary.regressions_found}</div>
          <div style="font-size: 10px; color: #6b7280;">Regressions</div>
        </div>
        <div style="background: #f0fdf4; padding: 8px; border-radius: 4px; text-align: center;">
          <div style="font-size: 20px; font-weight: 600; color: #166534;">${summary.learnings_count}</div>
          <div style="font-size: 10px; color: #6b7280;">Learnings</div>
        </div>
      </div>

      <div style="display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; margin-bottom: 16px;">
        <div style="background: #eff6ff; padding: 8px; border-radius: 4px; text-align: center;">
          <div style="font-size: 16px; font-weight: 600; color: #1d4ed8;">${summary.feedback_actions_count}</div>
          <div style="font-size: 10px; color: #6b7280;">Feedback Actions</div>
        </div>
        <div style="background: #fefce8; padding: 8px; border-radius: 4px; text-align: center;">
          <div style="font-size: 16px; font-weight: 600; color: #a16207;">${summary.issues_created}</div>
          <div style="font-size: 10px; color: #6b7280;">Issues Created</div>
        </div>
      </div>

      <div style="margin-bottom: 12px;">
        <div style="font-weight: 500; margin-bottom: 6px; font-size: 12px;">Flow Status</div>
        ${flowRows}
      </div>

      <div>
        <div style="font-weight: 500; margin-bottom: 6px; font-size: 12px;">Labels</div>
        <div style="display: flex; flex-wrap: wrap; gap: 4px;">
          ${labelBadges}
        </div>
      </div>
    </div>
  `;
}
/**
 * Get status dot for wisdom flow status.
 */
function getWisdomStatusDot(status) {
    const colors = {
        succeeded: "#22c55e",
        failed: "#ef4444",
        skipped: "#9ca3af",
        partial: "#eab308",
    };
    const color = colors[status] || "#9ca3af";
    return `<span style="display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: ${color};"></span>`;
}
/**
 * Get loop info string for flow data.
 */
function getLoopInfo(flowData) {
    if (!flowData)
        return "";
    const parts = [];
    if (flowData.microloops)
        parts.push(`μ:${flowData.microloops}`);
    if (flowData.test_loops)
        parts.push(`T:${flowData.test_loops}`);
    if (flowData.code_loops)
        parts.push(`C:${flowData.code_loops}`);
    return parts.join(" ");
}
/**
 * Render empty wisdom state.
 */
function renderWisdomEmpty(runId) {
    return `
    <div data-uiid="flow_studio.modal.run_detail.wisdom.empty" style="text-align: center; padding: 16px;">
      <div style="font-size: 24px; margin-bottom: 8px;">📊</div>
      <div style="font-weight: 500; color: #374151; margin-bottom: 4px;">No Wisdom Data</div>
      <div class="muted fs-text-xs" style="margin-bottom: 12px;">
        Wisdom summary not yet generated for this run.
      </div>
      <div style="background: #f9fafb; border-radius: 4px; padding: 8px; font-family: monospace; font-size: 11px; color: #6b7280;">
        uv run swarm/tools/wisdom_summarizer.py ${escapeHtml(runId)}
      </div>
    </div>
  `;
}
// ============================================================================
// Window Exports (for onclick handlers in HTML)
// ============================================================================
if (typeof window !== "undefined") {
    window.showRunDetailModal = showRunDetailModal;
    window.closeRunDetailModal = closeRunDetailModal;
}
