// swarm/tools/flow_studio_ui/src/inventory_counts.ts
// Inventory counts component for Flow Studio
//
// Displays deterministic marker statistics:
// - Counts per marker type (REQ, SOL, TRC, ASM, DEC)
// - Counts per flow
// - Deltas between steps (what changed)
import { Api, fetchJSON } from "./api.js";
// =============================================================================
// State
// =============================================================================
let currentRunId = null;
let currentData = null;
// Monotonic sequence counter for request coalescing
// Prevents out-of-order UI renders under bursty SSE events
let loadSeq = 0;
// =============================================================================
// API
// =============================================================================
async function getFactsSummary(runId) {
    return fetchJSON(`/api/runs/${encodeURIComponent(runId)}/facts/summary`);
}
// =============================================================================
// Rendering Helpers
// =============================================================================
const MARKER_COLORS = {
    REQ: "#3b82f6", // blue
    SOL: "#22c55e", // green
    TRC: "#a855f7", // purple
    ASM: "#f59e0b", // amber
    DEC: "#06b6d4", // cyan
    TRC_MISSING: "#ef4444", // red
};
function getMarkerColor(markerType) {
    return MARKER_COLORS[markerType] || "#6b7280";
}
function formatDelta(delta) {
    if (delta > 0)
        return `+${delta}`;
    if (delta < 0)
        return `${delta}`;
    return "0";
}
function getDeltaClass(delta) {
    if (delta > 0)
        return "delta-positive";
    if (delta < 0)
        return "delta-negative";
    return "delta-neutral";
}
// =============================================================================
// Scoreboard Rendering
// =============================================================================
function renderScoreboard(data) {
    const items = data.by_type.map((mc) => {
        const color = getMarkerColor(mc.marker_type);
        return `
      <div class="scoreboard-item" data-marker-type="${mc.marker_type}" style="--marker-color: ${color}">
        <span class="marker-type">${escapeHtml(mc.marker_type)}</span>
        <span class="marker-count">${mc.count}</span>
        <span class="marker-label">${escapeHtml(mc.label)}</span>
      </div>
    `;
    }).join("");
    return `
    <div class="inventory-scoreboard">
      <div class="scoreboard-header">
        <h4>Inventory</h4>
        <span class="total-count">${data.total_facts} facts</span>
      </div>
      <div class="scoreboard-items">
        ${items}
      </div>
    </div>
  `;
}
// =============================================================================
// Flow Breakdown Rendering
// =============================================================================
function renderFlowBreakdown(data) {
    if (data.by_flow.length === 0) {
        return "";
    }
    const flowItems = data.by_flow.map((fc) => {
        // Build mini bar chart
        const markerTypes = Object.keys(fc.counts).sort();
        const bars = markerTypes.map((mt) => {
            const count = fc.counts[mt];
            const color = getMarkerColor(mt);
            const width = fc.total > 0 ? (count / fc.total) * 100 : 0;
            return `<div class="bar-segment" style="width: ${width}%; background: ${color}" title="${mt}: ${count}"></div>`;
        }).join("");
        return `
      <div class="flow-item" data-flow="${fc.flow_key}">
        <span class="flow-key">${escapeHtml(fc.flow_key)}</span>
        <div class="flow-bar">${bars}</div>
        <span class="flow-total">${fc.total}</span>
      </div>
    `;
    }).join("");
    return `
    <div class="inventory-flows">
      <h5>By Flow</h5>
      <div class="flow-breakdown">
        ${flowItems}
      </div>
    </div>
  `;
}
// =============================================================================
// Delta View Rendering
// =============================================================================
function renderDeltaView(data) {
    if (data.deltas.length === 0) {
        return "";
    }
    // Show only the most recent deltas (last 5)
    const recentDeltas = data.deltas.slice(-5);
    const deltaItems = recentDeltas.map((d) => {
        const deltaChips = Object.entries(d.deltas).map(([mt, delta]) => {
            const color = getMarkerColor(mt);
            const deltaClass = getDeltaClass(delta);
            return `<span class="delta-chip ${deltaClass}" style="--marker-color: ${color}">${mt} ${formatDelta(delta)}</span>`;
        }).join(" ");
        return `
      <div class="delta-item">
        <span class="delta-path">${escapeHtml(d.to_step)}</span>
        <div class="delta-chips">${deltaChips || "no change"}</div>
      </div>
    `;
    }).join("");
    return `
    <details class="inventory-deltas">
      <summary>Recent Changes (${data.deltas.length})</summary>
      <div class="delta-list">
        ${deltaItems}
      </div>
    </details>
  `;
}
// =============================================================================
// Compact View (for header bar)
// =============================================================================
export function renderCompactInventory(data) {
    const items = data.by_type.map((mc) => {
        if (mc.count === 0)
            return "";
        const color = getMarkerColor(mc.marker_type);
        return `<span class="compact-marker" style="color: ${color}">${mc.marker_type}:${mc.count}</span>`;
    }).filter(Boolean).join(" ");
    return `
    <div class="inventory-compact">
      ${items || "No facts"}
    </div>
  `;
}
// =============================================================================
// Full Panel Rendering
// =============================================================================
export function renderInventoryPanel(data) {
    return `
    <div class="inventory-panel" data-run-id="${data.run_id}">
      ${renderScoreboard(data)}
      ${renderFlowBreakdown(data)}
      ${renderDeltaView(data)}
      ${data.errors.length > 0 ? `
        <div class="inventory-errors">
          <details>
            <summary>${data.errors.length} extraction error(s)</summary>
            <ul>
              ${data.errors.map((e) => `<li>${escapeHtml(e)}</li>`).join("")}
            </ul>
          </details>
        </div>
      ` : ""}
    </div>
  `;
}
// =============================================================================
// Public API
// =============================================================================
/**
 * Load and cache facts summary for a run.
 * Uses monotonic request ID guard to prevent out-of-order UI renders
 * when multiple requests are in flight (e.g., under bursty SSE).
 */
export async function loadFactsSummary(runId) {
    const seq = ++loadSeq;
    try {
        currentRunId = runId;
        const data = await getFactsSummary(runId);
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
            console.error("Failed to load facts summary:", err);
            currentData = null;
        }
        return null;
    }
}
/**
 * Get the current cached facts data.
 */
export function getCurrentFactsData() {
    return currentData;
}
/**
 * Update the inventory panel in a container.
 */
export async function updateInventoryPanel(container, runId) {
    const data = await loadFactsSummary(runId);
    if (data) {
        container.innerHTML = renderInventoryPanel(data);
    }
    else {
        container.innerHTML = `
      <div class="inventory-panel empty">
        <div class="empty-message">No inventory data available.</div>
      </div>
    `;
    }
}
/**
 * Update the compact inventory display in a container.
 */
export async function updateCompactInventory(container, runId) {
    const data = await loadFactsSummary(runId);
    if (data) {
        container.innerHTML = renderCompactInventory(data);
    }
    else {
        container.innerHTML = `<span class="inventory-compact">--</span>`;
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
export function injectInventoryCSS() {
    if (cssInjected)
        return;
    cssInjected = true;
    const style = document.createElement("style");
    style.textContent = `
    .inventory-panel {
      background: var(--bg-secondary, #f5f5f5);
      border-radius: 8px;
      padding: 12px;
      margin: 8px 0;
    }

    .inventory-scoreboard {
      margin-bottom: 12px;
    }

    .scoreboard-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin-bottom: 8px;
    }

    .scoreboard-header h4 {
      margin: 0;
      font-size: 14px;
      font-weight: 600;
    }

    .total-count {
      font-size: 12px;
      color: var(--text-secondary, #666);
    }

    .scoreboard-items {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }

    .scoreboard-item {
      display: flex;
      flex-direction: column;
      align-items: center;
      padding: 8px 12px;
      background: white;
      border-radius: 6px;
      border-left: 3px solid var(--marker-color);
      min-width: 60px;
    }

    .marker-type {
      font-size: 10px;
      font-weight: 600;
      color: var(--marker-color);
      text-transform: uppercase;
    }

    .marker-count {
      font-size: 20px;
      font-weight: 700;
      color: var(--text-primary, #111);
    }

    .marker-label {
      font-size: 9px;
      color: var(--text-tertiary, #888);
      text-align: center;
      max-width: 80px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .inventory-flows h5 {
      margin: 0 0 8px 0;
      font-size: 12px;
      font-weight: 500;
      color: var(--text-secondary, #666);
    }

    .flow-breakdown {
      display: flex;
      flex-direction: column;
      gap: 4px;
    }

    .flow-item {
      display: flex;
      align-items: center;
      gap: 8px;
    }

    .flow-key {
      font-size: 11px;
      font-weight: 500;
      width: 60px;
      text-transform: capitalize;
    }

    .flow-bar {
      flex: 1;
      height: 12px;
      background: var(--bg-tertiary, #e8e8e8);
      border-radius: 2px;
      display: flex;
      overflow: hidden;
    }

    .bar-segment {
      height: 100%;
      transition: width 0.3s ease;
    }

    .flow-total {
      font-size: 11px;
      font-weight: 600;
      width: 30px;
      text-align: right;
    }

    .inventory-deltas {
      margin-top: 12px;
      font-size: 12px;
    }

    .inventory-deltas summary {
      cursor: pointer;
      color: var(--text-secondary, #666);
      font-weight: 500;
    }

    .delta-list {
      margin-top: 8px;
      display: flex;
      flex-direction: column;
      gap: 4px;
    }

    .delta-item {
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 4px 0;
      border-bottom: 1px solid var(--border-color, #eee);
    }

    .delta-item:last-child {
      border-bottom: none;
    }

    .delta-path {
      font-family: monospace;
      font-size: 10px;
      color: var(--text-tertiary, #888);
      min-width: 100px;
    }

    .delta-chips {
      display: flex;
      flex-wrap: wrap;
      gap: 4px;
    }

    .delta-chip {
      font-size: 10px;
      padding: 2px 6px;
      border-radius: 3px;
      font-family: monospace;
    }

    .delta-positive {
      background: #dcfce7;
      color: #166534;
    }

    .delta-negative {
      background: #fee2e2;
      color: #991b1b;
    }

    .delta-neutral {
      background: var(--bg-tertiary, #e8e8e8);
      color: var(--text-tertiary, #888);
    }

    .inventory-errors {
      margin-top: 12px;
      font-size: 11px;
      color: var(--text-secondary, #666);
    }

    .inventory-errors summary {
      cursor: pointer;
      color: #f59e0b;
    }

    .inventory-errors ul {
      margin: 4px 0 0 0;
      padding-left: 16px;
      color: #92400e;
    }

    .inventory-compact {
      display: flex;
      gap: 8px;
      font-size: 11px;
      font-family: monospace;
    }

    .compact-marker {
      font-weight: 500;
    }

    .inventory-panel.empty {
      text-align: center;
      color: var(--text-secondary, #666);
    }

    .empty-message {
      padding: 16px;
      font-style: italic;
    }
  `;
    document.head.appendChild(style);
}
