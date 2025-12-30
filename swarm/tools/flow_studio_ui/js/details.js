// swarm/tools/flow_studio_ui/src/details.ts
// Details panel rendering for Flow Studio
//
// This module handles the right-hand details panel, including:
// - Step details (with Node/Run/Selftest tabs)
// - Agent details (with usage information)
// - Artifact details
// - Timeline and timing visualizations
import { state } from "./state.js";
import { Api } from "./api.js";
import { getTeachingMode } from "./teaching_mode.js";
import { formatDuration, formatTime, formatDateTime, createQuickCommands, escapeHtml } from "./utils.js";
import { renderSelectNodeHint, renderAgentUsageItem, renderAgentLocationInfo, renderAgentCategoryHint, renderArtifactProducerHint, renderTabs, } from "./ui_fragments.js";
import { RoutingDecisionCard, ForensicVerdictCard, renderInterruptionStackTab, } from "./components/index.js";
// ============================================================================
// Empty State
// ============================================================================
/**
 * Show the default empty state in the details panel.
 * Called when no node is selected.
 */
export function showEmptyState() {
    const detailsEl = document.getElementById("details");
    if (!detailsEl)
        return;
    detailsEl.innerHTML = renderSelectNodeHint();
}
/**
 * Render run-level timeline in the container
 */
export async function renderRunTimeline(container) {
    if (!state.currentRunId) {
        container.innerHTML = '<div class="muted">Select a run to see timeline</div>';
        return;
    }
    container.innerHTML = '<div class="muted">Loading timeline...</div>';
    try {
        const data = await Api.getRunTimeline(state.currentRunId);
        const events = data.events || [];
        if (events.length === 0) {
            container.innerHTML = '<div class="muted">No timeline data available for this run</div>';
            return;
        }
        let html = '<div class="timeline-container">';
        html += '<div class="timeline-header">Run Timeline</div>';
        events.forEach((event) => {
            const icon = event.status === 'started' ? '\u25CF' :
                event.status === 'completed' ? '\u2713' :
                    event.status === 'failed' ? '\u2717' : '\u2022';
            const time = formatTime(event.timestamp);
            const duration = event.duration_ms ? formatDuration(event.duration_ms / 1000) : '';
            html += `
        <div class="timeline-event ${event.status || ''}">
          <span class="timeline-time">${time}</span>
          <span class="timeline-icon">${icon}</span>
          <span class="timeline-flow">${event.flow}</span>
          <span class="timeline-status">${event.status || ''}</span>
          ${duration ? `<span class="timeline-duration">(${duration})</span>` : ''}
        </div>
      `;
            if (event.note) {
                html += `<div class="timeline-note">\u2514\u2500 ${event.note}</div>`;
            }
        });
        // Add total duration if available
        try {
            const timingData = await Api.getRunTiming(state.currentRunId);
            if (timingData.timing?.total_duration_seconds) {
                html += `<div class="timeline-total">Total: ${formatDuration(timingData.timing.total_duration_seconds)}</div>`;
            }
        }
        catch {
            // Timing data optional
        }
        html += '</div>';
        container.innerHTML = html;
    }
    catch (err) {
        console.error("Failed to load timeline", err);
        container.innerHTML = '<div class="muted">Timeline not available</div>';
    }
}
/**
 * Render flow timing summary in the container
 */
export async function renderFlowTiming(container, flowKey) {
    if (!state.currentRunId || !flowKey) {
        return;
    }
    try {
        const data = await Api.getFlowTiming(state.currentRunId, flowKey);
        const timing = data.timing;
        if (!timing || !timing.duration_seconds) {
            // In operator mode, show a helpful message about missing timing data
            if (state.currentMode === "operator") {
                container.insertAdjacentHTML('beforeend', `
          <div class="timing-empty-state">
            <div class="fs-text-sm fs-text-subtle" style="font-style: italic;">
              No timing data recorded for this flow.
              <br/><span class="fs-text-muted">Timing is captured in <code>flow_history.json</code> during flow execution.</span>
            </div>
          </div>
        `);
            }
            return;
        }
        let html = '<div class="timing-summary">';
        html += '<div class="timing-summary-header">';
        html += `<span class="timing-summary-duration">${formatDuration(timing.duration_seconds)}</span>`;
        if (timing.started_at && timing.ended_at) {
            html += `<span class="timing-summary-range">${formatDateTime(timing.started_at)} \u2192 ${formatDateTime(timing.ended_at)}</span>`;
        }
        html += '</div>';
        // Render step timing bars if we have step data
        const steps = timing.steps || [];
        if (steps.length > 0 && steps.some(s => s.duration_seconds)) {
            // Sort by duration descending, take top 5
            const sortedSteps = steps
                .filter(s => s.duration_seconds)
                .sort((a, b) => (b.duration_seconds || 0) - (a.duration_seconds || 0))
                .slice(0, 5);
            if (sortedSteps.length > 0) {
                const maxDuration = sortedSteps[0].duration_seconds || 1;
                html += '<div class="timing-bar-container">';
                html += '<div class="fs-text-sm fs-text-muted" style="margin-bottom: 6px;">Slowest Steps</div>';
                sortedSteps.forEach(step => {
                    const pct = Math.round(((step.duration_seconds || 0) / maxDuration) * 100);
                    const isSlow = (step.duration_seconds || 0) > timing.duration_seconds * 0.3;
                    html += `
            <div class="timing-bar-label">
              <span>${step.step_id}</span>
              <span>${formatDuration(step.duration_seconds || 0)}</span>
            </div>
            <div class="timing-bar">
              <div class="timing-bar-fill ${isSlow ? 'slow' : ''}" style="width: ${pct}%"></div>
            </div>
          `;
                });
                html += '</div>';
            }
        }
        html += '</div>';
        container.insertAdjacentHTML('beforeend', html);
    }
    catch (err) {
        console.error("Failed to load flow timing", err);
        // Silently fail - timing is optional
    }
}
/**
 * Render step timing inline
 */
export function renderStepTiming(timing) {
    if (!timing || (!timing.started_at && !timing.duration_seconds)) {
        return '';
    }
    let html = '<div class="step-timing">';
    if (timing.started_at) {
        html += `
      <div class="step-timing-row">
        <span class="step-timing-label">Started</span>
        <span class="step-timing-value">${formatTime(timing.started_at)}</span>
      </div>
    `;
    }
    if (timing.ended_at) {
        html += `
      <div class="step-timing-row">
        <span class="step-timing-label">Ended</span>
        <span class="step-timing-value">${formatTime(timing.ended_at)}</span>
      </div>
    `;
    }
    if (timing.duration_seconds) {
        html += `
      <div class="step-timing-row">
        <span class="step-timing-label">Duration</span>
        <span class="step-timing-value">${formatDuration(timing.duration_seconds)}</span>
      </div>
    `;
    }
    html += '</div>';
    return html;
}
// ============================================================================
// Agent Usage Rendering
// ============================================================================
/**
 * Render agent usage as clickable links
 */
export function renderAgentUsage(container, usage, callbacks = {}) {
    const { setActiveFlow, showStepDetails } = callbacks;
    container.innerHTML = '<div class="kv-label">Used in</div>';
    if (!usage.length) {
        const empty = document.createElement("div");
        empty.className = "muted";
        empty.textContent = "Not used in any flows";
        container.appendChild(empty);
        return;
    }
    const list = document.createElement("div");
    list.className = "fs-text-body";
    list.style.lineHeight = "1.8";
    usage.forEach(u => {
        const item = document.createElement("div");
        item.style.cursor = "pointer";
        item.style.padding = "2px 0";
        item.innerHTML = renderAgentUsageItem(u.flow_title, u.step_title);
        item.title = `Click to navigate to ${u.flow}:${u.step}`;
        item.addEventListener("click", async () => {
            if (setActiveFlow) {
                await setActiveFlow(u.flow, true);
                // After graph loads, select the step node
                setTimeout(() => {
                    if (state.cy) {
                        const nodeId = `step:${u.flow}:${u.step}`;
                        const node = state.cy.getElementById(nodeId);
                        if (node) {
                            state.cy.fit(50);
                            node.select();
                            if (showStepDetails) {
                                showStepDetails(node.data());
                            }
                        }
                    }
                }, 300);
            }
        });
        item.addEventListener("mouseenter", () => { item.style.background = "#f3f4f6"; });
        item.addEventListener("mouseleave", () => { item.style.background = "transparent"; });
        list.appendChild(item);
    });
    container.appendChild(list);
}
// ============================================================================
// Teaching Callout
// ============================================================================
/**
 * Render a teaching note callout for a step.
 * Only visible when Teaching Mode is enabled.
 *
 * @param teachingNote - The teaching note text to display
 * @returns HTML string for the teaching callout
 */
function renderTeachingCallout(teachingNote) {
    if (!teachingNote)
        return "";
    return `
    <div class="teaching-callout" data-uiid="flow_studio.inspector.teaching_note">
      <span class="teaching-callout-icon">&#x1F4A1;</span>
      <div class="teaching-callout-content">
        <div class="teaching-callout-label">Teaching Note</div>
        <div class="teaching-callout-text">${teachingNote}</div>
      </div>
    </div>
  `;
}
/**
 * Render structured teaching notes for a step.
 * Shows inputs, outputs, emphasizes, and constraints in a formatted display.
 * Only visible when Teaching Mode is enabled.
 */
function renderStructuredTeachingNotes(notes) {
    if (!notes)
        return "";
    const hasContent = (notes.inputs?.length ?? 0) > 0 ||
        (notes.outputs?.length ?? 0) > 0 ||
        (notes.emphasizes?.length ?? 0) > 0 ||
        (notes.constraints?.length ?? 0) > 0;
    if (!hasContent)
        return "";
    let html = `<div class="teaching-notes-structured" data-uiid="flow_studio.inspector.teaching_notes_structured">
    <div class="teaching-notes-header">
      <span class="teaching-notes-icon">&#x1F4D6;</span>
      <span class="teaching-notes-title">Step Context</span>
    </div>`;
    if (notes.inputs?.length) {
        html += `<div class="teaching-notes-section">
      <div class="teaching-notes-label">&#x1F4E5; Inputs</div>
      <ul class="teaching-notes-list inputs">
        ${notes.inputs.map(p => `<li class="mono">${p}</li>`).join('')}
      </ul>
    </div>`;
    }
    if (notes.outputs?.length) {
        html += `<div class="teaching-notes-section">
      <div class="teaching-notes-label">&#x1F4E4; Outputs</div>
      <ul class="teaching-notes-list outputs">
        ${notes.outputs.map(p => `<li class="mono">${p}</li>`).join('')}
      </ul>
    </div>`;
    }
    if (notes.emphasizes?.length) {
        html += `<div class="teaching-notes-section">
      <div class="teaching-notes-label">&#x2728; Emphasizes</div>
      <ul class="teaching-notes-list emphasizes">
        ${notes.emphasizes.map(e => `<li>${e}</li>`).join('')}
      </ul>
    </div>`;
    }
    if (notes.constraints?.length) {
        html += `<div class="teaching-notes-section">
      <div class="teaching-notes-label">&#x26D4; Constraints</div>
      <ul class="teaching-notes-list constraints">
        ${notes.constraints.map(c => `<li>${c}</li>`).join('')}
      </ul>
    </div>`;
    }
    html += '</div>';
    return html;
}
// ============================================================================
// Transcript Helpers
// ============================================================================
/**
 * Load and render transcript for a step
 */
async function loadTranscript(container, runId, flowKey, stepId) {
    container.innerHTML = '<div class="muted">Loading transcript...</div>';
    try {
        const resp = await Api.getStepTranscript(runId, flowKey, stepId);
        container.innerHTML = renderTranscript(resp);
    }
    catch {
        container.innerHTML = '<div class="muted">No transcript available for this step</div>';
    }
}
/**
 * Render transcript response to HTML
 */
function renderTranscript(resp) {
    if (!resp.messages || resp.messages.length === 0) {
        return '<div class="muted">No messages in transcript</div>';
    }
    let html = '<div class="transcript-container">';
    if (resp.engine) {
        html += `<div class="transcript-engine">Engine: <span class="mono">${escapeHtml(resp.engine)}</span></div>`;
    }
    resp.messages.forEach(msg => {
        const roleClass = `transcript-role-${msg.role}`;
        const contentPreview = msg.content.length > 500 ? msg.content.substring(0, 500) + '...' : msg.content;
        html += `
      <div class="transcript-message ${roleClass}">
        <div class="transcript-header">
          <span class="transcript-role">${escapeHtml(msg.role)}</span>
        </div>
        <div class="transcript-content">${escapeHtml(contentPreview)}</div>
      </div>
    `;
    });
    html += '</div>';
    return html;
}
// ============================================================================
// Receipt Badges Rendering
// ============================================================================
/**
 * Load and render engine/mode/provider badges for a step
 */
async function loadReceiptBadges(container, runId, flowKey, stepId) {
    container.innerHTML = '<span class="loading">Loading execution info...</span>';
    try {
        const resp = await Api.getStepReceipt(runId, flowKey, stepId);
        container.innerHTML = renderReceiptBadges(resp);
    }
    catch {
        // No receipt available - this is fine for non-stepwise runs
        container.innerHTML = '<span class="muted fs-text-sm">No execution metadata available</span>';
    }
}
/**
 * Render receipt badges HTML
 */
function renderReceiptBadges(resp) {
    const receipt = resp.receipt;
    if (!receipt) {
        return '<span class="muted fs-text-sm">No execution metadata</span>';
    }
    const badges = [];
    // Engine badge
    if (receipt.engine) {
        const engineClass = receipt.engine.replace(/\s+/g, '-').toLowerCase();
        badges.push(`<span class="run-badge engine ${engineClass}" title="Execution engine">${escapeHtml(receipt.engine)}</span>`);
    }
    // Mode badge
    if (receipt.mode) {
        const modeClass = receipt.mode.toLowerCase();
        badges.push(`<span class="run-badge mode ${modeClass}" title="Execution mode">${escapeHtml(receipt.mode)}</span>`);
    }
    // Provider badge
    if (receipt.provider) {
        const providerClass = receipt.provider.toLowerCase();
        badges.push(`<span class="run-badge provider ${providerClass}" title="LLM provider">${escapeHtml(receipt.provider)}</span>`);
    }
    if (badges.length === 0) {
        return '<span class="muted fs-text-sm">No execution metadata</span>';
    }
    // Add truncation info section if available
    const truncationHtml = renderContextTruncation(receipt.context_truncation);
    return badges.join('') + truncationHtml;
}
/**
 * Render context truncation metrics as a detailed section.
 * Shows history steps included/total, character budget usage, and priority distribution.
 */
function renderContextTruncation(truncation) {
    if (!truncation)
        return "";
    const { steps_included, steps_total, chars_used, budget_chars, truncated, priority_distribution } = truncation;
    const utilization = budget_chars > 0 ? Math.round((chars_used / budget_chars) * 100) : 0;
    // Color coding based on truncation status
    const bgColor = truncated ? "#fef2f2" : "#f0fdf4";
    const borderColor = truncated ? "#fecaca" : "#dcfce7";
    const statusColor = truncated ? "#dc2626" : "#059669";
    const statusText = truncated ? "TRUNCATED" : "Complete";
    // Priority distribution display
    let priorityHtml = "";
    if (priority_distribution) {
        const { CRITICAL, HIGH, MEDIUM, LOW } = priority_distribution;
        priorityHtml = `
      <div style="margin-top: 6px; font-size: 10px; color: #6b7280;">
        <span title="Critical priority items">C:${CRITICAL}</span>
        <span style="margin-left: 6px;" title="High priority items">H:${HIGH}</span>
        <span style="margin-left: 6px;" title="Medium priority items">M:${MEDIUM}</span>
        <span style="margin-left: 6px;" title="Low priority items">L:${LOW}</span>
      </div>
    `;
    }
    return `
    <div class="context-truncation-section" style="background: ${bgColor}; border-left: 3px solid ${borderColor}; padding: 8px; margin-top: 8px; border-radius: 4px;">
      <div style="font-weight: 500; margin-bottom: 4px; font-size: 11px; color: #374151;">Context Budget</div>
      <div style="font-size: 11px; line-height: 1.5;">
        <div><span style="color: #6b7280;">History:</span> ${steps_included}/${steps_total} steps</div>
        <div><span style="color: #6b7280;">Budget:</span> ${(chars_used / 1000).toFixed(0)}k/${(budget_chars / 1000).toFixed(0)}k chars (${utilization}%)</div>
        <div><span style="color: ${statusColor}; font-weight: 500;">${statusText}</span></div>
      </div>
      ${priorityHtml}
    </div>
  `;
}
/**
 * Render routing decision information from a step receipt.
 * Shows loop iteration, max iterations, decision type, and reason.
 */
function renderRoutingDecision(routing) {
    if (!routing)
        return "";
    let html = '<div class="routing-decision">';
    html += '<div class="routing-decision-header">Routing Decision</div>';
    const kindClass = routing.decision === 'loop' ? 'microloop' : 'linear';
    html += `<div class="routing-kind-badge ${kindClass}">${routing.decision.toUpperCase()}</div>`;
    if (routing.loop_iteration > 0 || routing.max_iterations) {
        html += `<div class="routing-detail">
      <span class="routing-label">Iteration</span>
      <span class="routing-value">${routing.loop_iteration} / ${routing.max_iterations ?? '\u221E'}</span>
    </div>`;
    }
    if (routing.reason) {
        const exitClass = routing.reason.toLowerCase().includes('verified') ? 'success' : 'warning';
        html += `<div class="routing-detail">
      <span class="routing-label">Reason</span>
      <span class="routing-value exit-reason ${exitClass}">${routing.reason}</span>
    </div>`;
    }
    html += '</div>';
    return html;
}
// ============================================================================
// Routing Tab Rendering
// ============================================================================
/**
 * Load and render routing information for a step.
 * Uses the RoutingDecisionCard and ForensicVerdictCard components
 * when full routing data is available, falls back to simple display otherwise.
 */
async function loadRoutingData(container, runId, flowKey, stepId) {
    container.innerHTML = '<div class="muted">Loading routing data...</div>';
    try {
        const resp = await Api.getStepReceipt(runId, flowKey, stepId);
        const receipt = resp.receipt;
        if (!receipt) {
            container.innerHTML = '<div class="muted">No routing data available for this step</div>';
            return;
        }
        // Clear container for rendering
        container.innerHTML = '';
        // Check if we have full routing decision data (V3 routing model)
        // The receipt may include a routing_decision field with candidates
        const receiptAny = receipt;
        const routingDecision = receiptAny.routing_decision;
        const forensicVerdict = receiptAny.forensic_verdict;
        // Section: Forensic Verdict (if present)
        if (forensicVerdict) {
            const forensicSection = document.createElement("div");
            forensicSection.className = "routing-tab-section";
            forensicSection.innerHTML = '<div class="kv-label" style="margin-bottom: 8px;">Forensic Verification</div>';
            const forensicContainer = document.createElement("div");
            forensicSection.appendChild(forensicContainer);
            const forensicCard = new ForensicVerdictCard({
                container: forensicContainer,
                startExpanded: false,
            });
            forensicCard.setData(forensicVerdict);
            container.appendChild(forensicSection);
        }
        // Section: Full Routing Decision Card (if present)
        if (routingDecision && routingDecision.candidates && routingDecision.candidates.length > 0) {
            const routingSection = document.createElement("div");
            routingSection.className = "routing-tab-section";
            routingSection.innerHTML = '<div class="kv-label" style="margin-bottom: 8px;">Routing Decision</div>';
            const routingCardContainer = document.createElement("div");
            routingSection.appendChild(routingCardContainer);
            const routingCard = new RoutingDecisionCard({
                expandedByDefault: false,
                onCandidateClick: (candidate) => {
                    console.log('Routing candidate clicked:', candidate);
                },
            });
            routingCard.render(routingDecision, routingCardContainer);
            container.appendChild(routingSection);
        }
        // Section: Simple routing info from receipt (fallback for non-V3 routing)
        if (receipt.routing) {
            const simpleRoutingSection = document.createElement("div");
            simpleRoutingSection.className = "routing-tab-section";
            simpleRoutingSection.innerHTML = renderRoutingDecision(receipt.routing);
            container.appendChild(simpleRoutingSection);
        }
        // If no routing data at all, show empty state
        if (!forensicVerdict && !routingDecision && !receipt.routing) {
            container.innerHTML = '<div class="muted">No routing data recorded for this step</div>';
        }
    }
    catch (err) {
        console.error("Failed to load routing data", err);
        container.innerHTML = '<div class="muted">Routing data not available</div>';
    }
}
/**
 * Show step details in the details panel
 */
export async function showStepDetails(data, callbacks = {}) {
    const { renderSelftestTab, getNodeGovernanceInfo, renderGovernanceSection, selectAgent } = callbacks;
    const detailsEl = document.getElementById("details");
    if (!detailsEl)
        return;
    detailsEl.innerHTML = "";
    const h2 = document.createElement("h2");
    h2.textContent = `Step: ${data.label.replace(/^[\u2705\u26a0\ufe0f\u274c\u2014] /, "")}`;
    // Tabs - default based on mode (Node for author, Run for operator)
    const defaultTab = state.currentMode === "operator" ? "run" : "node";
    const tabs = document.createElement("div");
    tabs.className = "tabs";
    tabs.innerHTML = renderTabs([
        { id: "node", label: "Node", active: defaultTab === "node" },
        { id: "run", label: "Run", active: defaultTab === "run" },
        { id: "routing", label: "Routing" },
        { id: "stack", label: "Stack" },
        { id: "transcript", label: "Transcript" },
        { id: "selftest", label: "Selftest" }
    ]);
    // Fetch flow detail to get step agents and teaching notes
    let stepAgents = [];
    let stepDescription = "";
    let stepTeachingNote = "";
    if (data.flow) {
        try {
            const flowDetail = await Api.getFlowDetail(data.flow);
            const stepInfo = flowDetail.steps?.find((s) => s.id === data.step_id);
            if (stepInfo) {
                stepAgents = stepInfo.agents || [];
                // Use role as description if available
                stepDescription = stepInfo.role || data.role || "";
                // Get teaching note for teaching mode
                stepTeachingNote = stepInfo.teaching_note || "";
            }
        }
        catch (err) {
            console.error("Failed to fetch flow detail for step agents", err);
        }
    }
    // Create teaching note callout (shown when Teaching Mode is enabled)
    const teachingCallout = document.createElement("div");
    if (stepTeachingNote && getTeachingMode()) {
        teachingCallout.innerHTML = renderTeachingCallout(stepTeachingNote);
    }
    // Node tab content
    const nodeTab = document.createElement("div");
    nodeTab.className = `tab-content ${defaultTab === "node" ? "active" : ""}`;
    nodeTab.dataset.tab = "node";
    // Build the node tab HTML
    let nodeTabHtml = `
    <div class="author-only">
      <div class="kv-label">Step id</div>
      <div class="mono">${data.step_id || ""}</div>
      <div class="kv-label">Flow</div>
      <div class="mono">${data.flow || ""}</div>
    </div>
  `;
    // What this step does section
    nodeTabHtml += `
    <div class="kv-section">
      <div class="kv-label">What this step does</div>
      <div class="fs-text-body" style="line-height: 1.4;">${stepDescription || data.role || "\u2014"}</div>
    </div>
  `;
    // Agents section (placeholder - will add interactive links below)
    nodeTabHtml += `
    <div class="kv-section">
      <div class="kv-label">Agents</div>
      <div id="step-agents-list" class="fs-text-body" style="line-height: 1.8;"></div>
    </div>
  `;
    // Author-only sections: Spec, Edit step, Artifacts template
    nodeTabHtml += `
    <div class="author-only">
      <div class="kv-section">
        <div class="kv-label">Spec</div>
        <div class="fs-text-sm">
          <span class="mono">swarm/flows/flow-${data.flow}.md</span>
        </div>
      </div>
      <div class="kv-section">
        <div class="fs-text-sm fs-text-muted" style="margin-bottom: 4px;">Edit step:</div>
        <pre class="mono fs-text-xs" style="margin: 0;">$EDITOR swarm/config/flows/${data.flow}.yaml</pre>
      </div>
      <div class="kv-section">
        <div class="kv-label">Artifacts</div>
        <div class="mono fs-text-sm">swarm/runs/&lt;run&gt;/${data.flow}/${data.step_id || ""}/</div>
      </div>
    </div>
    <div class="operator-only">
      <div class="muted fs-text-sm" style="margin-top: 8px;">
        See <strong>Run</strong> tab for artifact status.
      </div>
    </div>
  `;
    nodeTab.innerHTML = nodeTabHtml;
    // Now add clickable agent links
    const agentsListEl = nodeTab.querySelector("#step-agents-list");
    if (agentsListEl) {
        if (stepAgents.length === 0) {
            agentsListEl.innerHTML = '<span class="muted">No agents assigned</span>';
        }
        else {
            stepAgents.forEach(agentKey => {
                const agentLink = document.createElement("div");
                agentLink.style.cursor = "pointer";
                agentLink.style.padding = "2px 0";
                agentLink.style.color = "#3b82f6";
                agentLink.innerHTML = `<span class="mono">${agentKey}</span>`;
                agentLink.title = `Click to view agent: ${agentKey}`;
                agentLink.addEventListener("click", async () => {
                    if (selectAgent) {
                        await selectAgent(agentKey, data.flow);
                    }
                });
                agentLink.addEventListener("mouseenter", () => {
                    agentLink.style.background = "#f3f4f6";
                    agentLink.style.textDecoration = "underline";
                });
                agentLink.addEventListener("mouseleave", () => {
                    agentLink.style.background = "transparent";
                    agentLink.style.textDecoration = "none";
                });
                agentsListEl.appendChild(agentLink);
            });
        }
    }
    // Run tab content
    const runTab = document.createElement("div");
    runTab.className = `tab-content ${defaultTab === "run" ? "active" : ""}`;
    runTab.dataset.tab = "run";
    // Get step status from cached run data
    const flowData = state.runStatus.flows?.[data.flow];
    const stepData = flowData?.steps?.[data.step_id || ""];
    const stepStatus = stepData?.status || "n/a";
    const artifacts = stepData?.artifacts || [];
    const statusClassMap = {
        complete: "status-complete",
        partial: "status-partial",
        missing: "status-missing",
        "n/a": "status-na"
    };
    const statusClass = statusClassMap[stepStatus] || "status-na";
    let artifactRows = "";
    if (artifacts.length === 0) {
        artifactRows = '<tr><td colspan="3" class="muted">No artifacts defined for this step</td></tr>';
    }
    else {
        artifacts.forEach(a => {
            const icon = a.status === "present" ? "\u2705" : "\u274c";
            const req = a.required ? "Required" : "Optional";
            artifactRows += `<tr>
        <td>${icon}</td>
        <td class="mono">${a.path}</td>
        <td class="muted">${req}</td>
      </tr>`;
        });
    }
    // Get step timing if available
    const stepTimingHtml = stepData?.timing ? renderStepTiming(stepData.timing) : '';
    runTab.innerHTML = `
    <div class="kv-label">Run</div>
    <div class="mono">${state.currentRunId || "None selected"}</div>
    <div class="kv-label">Step Status</div>
    <div class="${statusClass}" style="font-weight: 600;">${stepStatus.toUpperCase()}</div>
    <div class="fs-text-sm fs-text-muted" style="margin-top: 2px;">
      ${stepData?.required_present || 0}/${stepData?.required_total || 0} required,
      ${stepData?.optional_present || 0}/${stepData?.optional_total || 0} optional
    </div>
    ${stepData?.note ? `<div class="muted" style="margin-top: 4px; font-style: italic;">${stepData.note}</div>` : ""}
    <div class="kv-label" style="margin-top: 8px;">Execution</div>
    <div class="run-detail-badges" id="step-receipt-badges"></div>
    ${stepTimingHtml}
    <div class="kv-label">Artifacts</div>
    <table class="artifact-table">
      <thead>
        <tr><th></th><th>Path</th><th>Type</th></tr>
      </thead>
      <tbody>${artifactRows}</tbody>
    </table>
    <div class="kv-label" style="margin-top: 12px;">Artifact Directory</div>
    <div class="mono fs-text-sm">swarm/runs/${state.currentRunId || "<run>"}/${data.flow}/</div>
  `;
    // Load receipt badges asynchronously if we have run context
    if (state.currentRunId && data.flow && data.step_id) {
        const badgesContainer = runTab.querySelector("#step-receipt-badges");
        if (badgesContainer) {
            loadReceiptBadges(badgesContainer, state.currentRunId, data.flow, data.step_id);
        }
    }
    // Selftest tab content (never active by default)
    const selftestTab = document.createElement("div");
    selftestTab.className = "tab-content";
    selftestTab.dataset.tab = "selftest";
    if (renderSelftestTab) {
        await renderSelftestTab(selftestTab);
    }
    else {
        selftestTab.innerHTML = '<div class="muted">Selftest info not available</div>';
    }
    // Transcript tab content (lazy-loaded)
    const transcriptTab = document.createElement("div");
    transcriptTab.className = "tab-content";
    transcriptTab.dataset.tab = "transcript";
    transcriptTab.innerHTML = '<div class="muted">Select a step to view transcript</div>';
    // Routing tab content (lazy-loaded)
    const routingTab = document.createElement("div");
    routingTab.className = "tab-content";
    routingTab.dataset.tab = "routing";
    routingTab.innerHTML = '<div class="muted">Click to view routing decisions</div>';
    // Stack tab content (lazy-loaded) - shows interruption/detour stack
    const stackTab = document.createElement("div");
    stackTab.className = "tab-content";
    stackTab.dataset.tab = "stack";
    stackTab.innerHTML = '<div class="muted">Click to view execution stack</div>';
    detailsEl.appendChild(h2);
    // Add teaching callout if available and teaching mode is on
    if (teachingCallout.innerHTML) {
        detailsEl.appendChild(teachingCallout);
    }
    detailsEl.appendChild(tabs);
    detailsEl.appendChild(nodeTab);
    detailsEl.appendChild(runTab);
    detailsEl.appendChild(routingTab);
    detailsEl.appendChild(stackTab);
    detailsEl.appendChild(transcriptTab);
    detailsEl.appendChild(selftestTab);
    // Add quick commands section
    const quickCmds = createQuickCommands([
        "ls swarm/runs/" + (state.currentRunId || "<run>") + "/" + data.flow + "/",
        "cat swarm/flows/flow-" + data.flow + ".md",
        "code swarm/config/flows/" + data.flow + ".yaml"
    ]);
    quickCmds.classList.add("author-only");
    nodeTab.appendChild(quickCmds);
    // Tab switching
    tabs.querySelectorAll(".tab").forEach(tab => {
        tab.addEventListener("click", () => {
            tabs.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
            detailsEl.querySelectorAll(".tab-content").forEach(c => c.classList.remove("active"));
            tab.classList.add("active");
            const tabName = tab.dataset.tab;
            const content = detailsEl.querySelector(`.tab-content[data-tab="${tabName}"]`);
            if (content)
                content.classList.add("active");
            // Lazy load transcript when tab is clicked
            if (tabName === "transcript" && state.currentRunId && data.flow && data.step_id) {
                loadTranscript(transcriptTab, state.currentRunId, data.flow, data.step_id);
            }
            // Lazy load routing data when tab is clicked
            if (tabName === "routing" && state.currentRunId && data.flow && data.step_id) {
                loadRoutingData(routingTab, state.currentRunId, data.flow, data.step_id);
            }
            // Lazy load stack data when tab is clicked
            if (tabName === "stack") {
                renderInterruptionStackTab(stackTab, state.currentRunId, data.flow || null, data.step_id || null, (runId) => Api.getBoundaryReview(runId));
            }
        });
    });
    // Add governance section if there are issues
    if (getNodeGovernanceInfo && renderGovernanceSection) {
        const govInfo = getNodeGovernanceInfo(data);
        if (govInfo) {
            renderGovernanceSection(detailsEl, govInfo);
        }
    }
}
/**
 * Show agent details in the details panel
 */
export async function showAgentDetails(data, callbacks = {}) {
    const { setActiveFlow, showStepDetails: showStepDetailsFn, getNodeGovernanceInfo, renderGovernanceSection } = callbacks;
    const agentKey = data.agent_key || data.label;
    const detailsEl = document.getElementById("details");
    if (!detailsEl)
        return;
    detailsEl.innerHTML = "";
    const h2 = document.createElement("h2");
    h2.textContent = `Agent: ${agentKey}`;
    // What this agent does - use description if available, fall back to short_role
    const agentDescription = data.description || data.short_role || "";
    const descSection = document.createElement("div");
    descSection.className = "kv-section";
    descSection.innerHTML = `
    <div class="kv-label">What this agent does</div>
    <div class="fs-text-body" style="line-height: 1.4;">${agentDescription || "\u2014"}</div>
  `;
    const meta = document.createElement("div");
    meta.innerHTML = `
    <div class="author-only">
      <div class="kv-label">Agent key</div>
      <div class="mono">${agentKey}</div>
    </div>
    <div class="kv-label">Category</div>
    <div>${data.category || "unknown"}</div>
    <div class="kv-label">Model</div>
    <div class="mono">${data.model || "inherit"}</div>
  `;
    // Fetch agent usage
    const usageSection = document.createElement("div");
    usageSection.innerHTML = '<div class="kv-label">Used in</div><div class="muted">Loading...</div>';
    const authorOnly = document.createElement("div");
    authorOnly.className = "author-only";
    authorOnly.innerHTML = renderAgentLocationInfo(agentKey);
    const operatorOnly = document.createElement("div");
    operatorOnly.className = "operator-only";
    operatorOnly.innerHTML = renderAgentCategoryHint(data.category || "", data.model || "");
    detailsEl.appendChild(h2);
    detailsEl.appendChild(descSection);
    detailsEl.appendChild(meta);
    detailsEl.appendChild(usageSection);
    detailsEl.appendChild(authorOnly);
    detailsEl.appendChild(operatorOnly);
    // Add quick commands for agent
    const agentCmds = createQuickCommands([
        "cat swarm/config/agents/" + agentKey + ".yaml",
        "cat .claude/agents/" + agentKey + ".md",
        "code swarm/config/agents/" + agentKey + ".yaml"
    ]);
    agentCmds.classList.add("author-only");
    authorOnly.appendChild(agentCmds);
    // Add governance section if there are issues
    if (getNodeGovernanceInfo && renderGovernanceSection) {
        const govInfo = getNodeGovernanceInfo(data);
        if (govInfo) {
            renderGovernanceSection(detailsEl, govInfo);
        }
    }
    // Load and render agent usage asynchronously
    try {
        const usageData = await Api.getAgentUsage(agentKey);
        renderAgentUsage(usageSection, usageData.usage || [], {
            setActiveFlow,
            showStepDetails: showStepDetailsFn
        });
    }
    catch (err) {
        console.error("Failed to load agent usage", err);
        usageSection.innerHTML = '<div class="kv-label">Used in</div><div class="muted">Failed to load usage</div>';
    }
}
/**
 * Show artifact details in the details panel
 */
export function showArtifactDetails(data) {
    const detailsEl = document.getElementById("details");
    if (!detailsEl)
        return;
    detailsEl.innerHTML = "";
    const h2 = document.createElement("h2");
    h2.textContent = `Artifact: ${data.filename || data.label}`;
    const statusIconMap = {
        present: "\u2705",
        missing: "\u274c",
        unknown: "\u2014"
    };
    const statusIcon = statusIconMap[data.status || "unknown"] || "\u2014";
    const statusClassMap = {
        present: "status-complete",
        missing: "status-missing",
        unknown: "status-na"
    };
    const statusClass = statusClassMap[data.status || "unknown"] || "status-na";
    const meta = document.createElement("div");
    meta.innerHTML = `
    <div class="kv-label">Filename</div>
    <div class="mono">${data.filename || data.label}</div>
    <div class="kv-label">Type</div>
    <div>${data.required ? "Required" : "Optional"}</div>
    <div class="kv-label">Status</div>
    <div class="${statusClass}" style="font-weight: 600;">${statusIcon} ${(data.status || "unknown").toUpperCase()}</div>
    ${data.is_decision ? '<div class="kv-label">Decision Artifact</div><div style="color: #3b82f6; font-weight: 600;">Yes - This is the flow\'s decision artifact</div>' : ''}
    <div class="kv-label">Produced by Step</div>
    <div class="mono">${data.step_id || ""}</div>
    ${data.note ? '<div class="kv-label">Note</div><div class="muted" style="font-style: italic;">' + data.note + '</div>' : ''}
  `;
    const pathSection = document.createElement("div");
    pathSection.className = "author-only";
    const runPath = state.currentRunId ?
        (state.currentRunId.includes('health-check') || state.currentRunId.includes('example') ?
            `swarm/examples/${state.currentRunId}/${data.flow}/${data.filename || ""}` :
            `swarm/runs/${state.currentRunId}/${data.flow}/${data.filename || ""}`) :
        `swarm/runs/<run-id>/${data.flow}/${data.filename || ""}`;
    pathSection.innerHTML = `
    <div class="kv-label">Path</div>
    <div class="mono fs-text-sm">${runPath}</div>
    <div class="kv-label" style="margin-top: 12px;">Copy Command</div>
    <pre class="mono">cat ${runPath}</pre>
  `;
    const operatorOnly = document.createElement("div");
    operatorOnly.className = "operator-only";
    operatorOnly.innerHTML = renderArtifactProducerHint(data.step_id || "", data.flow || "");
    detailsEl.appendChild(h2);
    detailsEl.appendChild(meta);
    detailsEl.appendChild(pathSection);
    detailsEl.appendChild(operatorOnly);
}
