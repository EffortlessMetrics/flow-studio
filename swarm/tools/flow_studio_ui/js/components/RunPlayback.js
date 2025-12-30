// swarm/tools/flow_studio_ui/src/components/RunPlayback.ts
// Run playback component with SSE event streaming
//
// Provides real-time visualization of run execution:
// - Subscribe to run events via SSE
// - Animate node state changes
// - Show routing decisions
// - Display step outputs
//
// NO filesystem operations - all data streams through SSE.
import { flowStudioApi } from "../api/client.js";
// ============================================================================
// Animation Styles
// ============================================================================
const ANIMATION_STYLES = {
    idle: {
        "background-color": "#0f766e",
        "border-color": "#134e4a",
        "border-width": "2",
    },
    running: {
        "background-color": "#3b82f6",
        "border-color": "#1d4ed8",
        "border-width": "3",
    },
    success: {
        "background-color": "#22c55e",
        "border-color": "#16a34a",
        "border-width": "2",
    },
    error: {
        "background-color": "#ef4444",
        "border-color": "#dc2626",
        "border-width": "2",
    },
    paused: {
        "background-color": "#f59e0b",
        "border-color": "#d97706",
        "border-width": "3",
    },
};
// ============================================================================
// Run Playback Component
// ============================================================================
/**
 * Run playback component for real-time execution visualization.
 *
 * Features:
 * - SSE subscription for live events
 * - Node animation during execution
 * - Routing decision visualization
 * - Step output display
 * - Pause/resume/stop controls
 */
export class RunPlayback {
    constructor(options = {}) {
        this.runId = null;
        this.flowKey = null;
        this.unsubscribe = null;
        this.playbackState = "stopped";
        this.events = [];
        this.routingDecisions = [];
        this.stepOutputs = [];
        this.currentStepId = null;
        this.options = {
            animationDuration: 300,
            ...options,
        };
    }
    // ==========================================================================
    // Playback Control
    // ==========================================================================
    /**
     * Start playback for a run
     */
    async start(runId, flowKey) {
        // Clean up any existing subscription
        this.stop();
        this.runId = runId;
        this.flowKey = flowKey || null;
        this.playbackState = "playing";
        this.events = [];
        this.routingDecisions = [];
        this.stepOutputs = [];
        this.currentStepId = null;
        // Reset all nodes to idle state
        this.resetNodeStates();
        // Subscribe to SSE events
        this.unsubscribe = flowStudioApi.subscribeToRun(runId, (event) => {
            this.handleEvent(event);
        });
    }
    /**
     * Pause playback (stop processing events but keep subscription)
     */
    pause() {
        if (this.playbackState === "playing") {
            this.playbackState = "paused";
            // Mark current step as paused
            if (this.currentStepId) {
                this.animateNode(this.currentStepId, "paused");
            }
        }
    }
    /**
     * Resume paused playback
     */
    resume() {
        if (this.playbackState === "paused") {
            this.playbackState = "playing";
            // Resume animation for current step
            if (this.currentStepId) {
                this.animateNode(this.currentStepId, "running");
            }
        }
    }
    /**
     * Stop playback and clean up
     */
    stop() {
        if (this.unsubscribe) {
            this.unsubscribe();
            this.unsubscribe = null;
        }
        this.playbackState = "stopped";
        this.runId = null;
        this.currentStepId = null;
        // Reset all nodes
        this.resetNodeStates();
    }
    /**
     * Get current playback state
     */
    getState() {
        return this.playbackState;
    }
    /**
     * Get all received events
     */
    getEvents() {
        return [...this.events];
    }
    /**
     * Get routing decisions
     */
    getRoutingDecisions() {
        return [...this.routingDecisions];
    }
    /**
     * Get step outputs
     */
    getStepOutputs() {
        return [...this.stepOutputs];
    }
    // ==========================================================================
    // Event Handling
    // ==========================================================================
    /**
     * Handle an incoming SSE event
     */
    handleEvent(event) {
        // Store event
        this.events.push(event);
        // Skip processing if paused (but still store events)
        if (this.playbackState === "paused") {
            return;
        }
        switch (event.type) {
            case "step_start":
                this.handleStepStart(event);
                break;
            case "step_end":
                this.handleStepEnd(event);
                break;
            case "routing_decision":
                this.handleRoutingDecision(event);
                break;
            case "artifact_created":
                this.handleArtifactCreated(event);
                break;
            case "complete":
                this.handleComplete(event);
                break;
            case "error":
                this.handleError(event);
                break;
        }
    }
    /**
     * Handle step_start event
     */
    handleStepStart(event) {
        const stepId = event.stepId;
        if (!stepId)
            return;
        // Mark previous step as success (if there was one)
        if (this.currentStepId && this.currentStepId !== stepId) {
            this.animateNode(this.currentStepId, "success");
        }
        this.currentStepId = stepId;
        this.animateNode(stepId, "running");
        // Focus on the node
        this.focusNode(stepId);
        if (this.options.onStepStart) {
            this.options.onStepStart(event);
        }
    }
    /**
     * Handle step_end event
     */
    handleStepEnd(event) {
        const stepId = event.stepId;
        if (!stepId)
            return;
        const status = event.payload?.status;
        const animationState = status === "error" || status === "failed" ? "error" : "success";
        this.animateNode(stepId, animationState);
        // Record step output
        const output = {
            timestamp: event.timestamp,
            stepId,
            agentKey: event.agentKey || undefined,
            status: animationState === "error" ? "error" : "success",
            duration: event.payload?.duration_ms,
            artifacts: event.payload?.artifacts,
        };
        this.stepOutputs.push(output);
        this.renderStepOutput(output);
        if (this.options.onStepEnd) {
            this.options.onStepEnd(event);
        }
    }
    /**
     * Handle routing_decision event
     */
    handleRoutingDecision(event) {
        const payload = event.payload || {};
        const decision = {
            timestamp: event.timestamp,
            fromStep: payload.from_step || "",
            toStep: payload.to_step || "",
            reason: payload.reason || "",
            loopIteration: payload.loop_iteration,
            decisionType: (payload.decision_type || payload.decision || "advance"),
        };
        this.routingDecisions.push(decision);
        this.renderRoutingDecision(decision);
        // Animate edge if we have graph
        this.animateEdge(decision.fromStep, decision.toStep);
        if (this.options.onRoutingDecision) {
            this.options.onRoutingDecision(decision);
        }
    }
    /**
     * Handle artifact_created event
     */
    handleArtifactCreated(event) {
        // Could add artifact visualization here
        // For now, just log
        console.log("Artifact created:", event.payload?.path);
    }
    /**
     * Handle complete event
     */
    handleComplete(_event) {
        this.playbackState = "stopped";
        // Mark last step as success
        if (this.currentStepId) {
            this.animateNode(this.currentStepId, "success");
            this.currentStepId = null;
        }
        if (this.options.onComplete) {
            this.options.onComplete();
        }
    }
    /**
     * Handle error event
     */
    handleError(event) {
        // Mark current step as error
        if (this.currentStepId) {
            this.animateNode(this.currentStepId, "error");
        }
        const errorMessage = event.payload?.error || "Unknown error";
        if (this.options.onError) {
            this.options.onError(errorMessage);
        }
    }
    // ==========================================================================
    // Graph Animation
    // ==========================================================================
    /**
     * Animate a node to a new state
     */
    animateNode(stepId, state) {
        const cy = this.options.cy;
        if (!cy)
            return;
        // Find the node
        const nodeId = this.flowKey ? `step:${this.flowKey}:${stepId}` : stepId;
        const node = cy.getElementById(nodeId);
        if (!node)
            return;
        const styles = ANIMATION_STYLES[state];
        const duration = this.options.animationDuration || 300;
        // Animate using Cytoscape's animation
        node.animate({
            style: styles,
            duration,
            easing: "ease-in-out",
        });
        // Add pulsing effect for running state
        if (state === "running") {
            node.addClass("node-running");
        }
        else {
            node.removeClass("node-running");
        }
    }
    /**
     * Animate an edge (highlight the path)
     */
    animateEdge(fromStep, toStep) {
        const cy = this.options.cy;
        if (!cy)
            return;
        // Find edge between steps
        const edges = cy.edges().filter((edge) => {
            const source = edge.data("source");
            const target = edge.data("target");
            return ((source.includes(fromStep) && target.includes(toStep)) ||
                (source === fromStep && target === toStep));
        });
        if (edges.length === 0)
            return;
        const duration = this.options.animationDuration || 300;
        // Highlight edge
        edges.forEach((edge) => {
            edge.animate({
                style: {
                    "line-color": "#3b82f6",
                    width: 4,
                },
                duration,
                easing: "ease-in-out",
            }).play();
            // Reset after animation
            setTimeout(() => {
                edge.animate({
                    style: {
                        "line-color": "#818cf8",
                        width: 2,
                    },
                    duration,
                    easing: "ease-in-out",
                }).play();
            }, duration * 2);
        });
    }
    /**
     * Focus the view on a node
     */
    focusNode(stepId) {
        const cy = this.options.cy;
        if (!cy)
            return;
        const nodeId = this.flowKey ? `step:${this.flowKey}:${stepId}` : stepId;
        const node = cy.getElementById(nodeId);
        if (!node)
            return;
        // Smooth pan to center the node
        cy.animate({
            center: { eles: node },
            duration: this.options.animationDuration || 300,
            easing: "ease-in-out",
        });
    }
    /**
     * Reset all nodes to idle state
     */
    resetNodeStates() {
        const cy = this.options.cy;
        if (!cy)
            return;
        cy.nodes('[type = "step"]').forEach((node) => {
            const styles = ANIMATION_STYLES.idle;
            Object.entries(styles).forEach(([key, value]) => {
                node.style(key, value);
            });
            node.removeClass("node-running");
        });
    }
    // ==========================================================================
    // UI Rendering
    // ==========================================================================
    /**
     * Render a step output to the output container
     */
    renderStepOutput(output) {
        const container = this.options.outputContainer;
        if (!container)
            return;
        const statusIcon = output.status === "success" ? "\u2705" : "\u274c";
        const durationText = output.duration
            ? `(${(output.duration / 1000).toFixed(2)}s)`
            : "";
        const item = document.createElement("div");
        item.className = `playback-output playback-output--${output.status}`;
        item.innerHTML = `
      <span class="playback-output__icon">${statusIcon}</span>
      <span class="playback-output__step">${output.stepId}</span>
      ${output.agentKey ? `<span class="playback-output__agent">${output.agentKey}</span>` : ""}
      <span class="playback-output__duration">${durationText}</span>
    `;
        container.appendChild(item);
        // Auto-scroll to bottom
        container.scrollTop = container.scrollHeight;
    }
    /**
     * Get icon for routing decision type
     */
    getDecisionTypeIcon(decisionType) {
        switch (decisionType) {
            case "advance":
                return "\u27A1\uFE0F"; // Right arrow emoji
            case "loop":
                return "\uD83D\uDD04"; // Counterclockwise arrows emoji
            case "terminate":
                return "\u23F9\uFE0F"; // Stop button emoji
            case "branch":
                return "\uD83D\uDD00"; // Shuffle tracks emoji (fork/branch)
            case "bounce":
                return "\u21A9\uFE0F"; // Left hook arrow emoji
            case "skip":
                return "\u23ED\uFE0F"; // Next track emoji
            default:
                return "\u27A1\uFE0F"; // Default to right arrow
        }
    }
    /**
     * Get CSS class modifier for routing decision type
     */
    getDecisionTypeClass(decisionType) {
        return decisionType ? `playback-routing--${decisionType}` : "";
    }
    /**
     * Format timestamp for display
     */
    formatTimestamp(timestamp) {
        try {
            const date = new Date(timestamp);
            return date.toLocaleTimeString(undefined, {
                hour: "2-digit",
                minute: "2-digit",
                second: "2-digit",
            });
        }
        catch {
            return timestamp;
        }
    }
    /**
     * Truncate text with ellipsis
     */
    truncateText(text, maxLength) {
        if (text.length <= maxLength) {
            return { truncated: text, isTruncated: false };
        }
        return { truncated: text.substring(0, maxLength) + "...", isTruncated: true };
    }
    /**
     * Escape HTML to prevent XSS
     */
    escapeHtml(text) {
        const div = document.createElement("div");
        div.textContent = text;
        return div.innerHTML;
    }
    /**
     * Render a routing decision to the routing container
     */
    renderRoutingDecision(decision) {
        const container = this.options.routingContainer;
        if (!container)
            return;
        const item = document.createElement("div");
        const decisionTypeClass = this.getDecisionTypeClass(decision.decisionType);
        item.className = `playback-routing ${decisionTypeClass}`;
        // Get decision type icon and label
        const icon = this.getDecisionTypeIcon(decision.decisionType);
        const typeLabel = decision.decisionType || "advance";
        // Format timestamp
        const timeDisplay = this.formatTimestamp(decision.timestamp);
        // Build iteration text
        let iterationText = "";
        if (decision.loopIteration !== undefined) {
            iterationText = `<span class="playback-routing__iteration">Loop #${decision.loopIteration}</span>`;
        }
        // Truncate reason text (max 100 chars for display)
        const { truncated: truncatedReason, isTruncated } = this.truncateText(decision.reason, 100);
        const escapedTruncatedReason = this.escapeHtml(truncatedReason);
        const escapedFullReason = this.escapeHtml(decision.reason);
        // Build reason element with expand capability
        const reasonClass = isTruncated ? "playback-routing__reason playback-routing__reason--truncated" : "playback-routing__reason";
        item.innerHTML = `
      <div class="playback-routing__header">
        <span class="playback-routing__icon" title="${typeLabel}">${icon}</span>
        <span class="playback-routing__type">${typeLabel}</span>
        <span class="playback-routing__timestamp">${timeDisplay}</span>
      </div>
      <div class="playback-routing__path">
        <span class="playback-routing__from">${this.escapeHtml(decision.fromStep)}</span>
        <span class="playback-routing__arrow">\u2192</span>
        <span class="playback-routing__to">${this.escapeHtml(decision.toStep || "(end)")}</span>
        ${iterationText}
      </div>
      <div class="${reasonClass}" data-full-reason="${escapedFullReason}" data-truncated-reason="${escapedTruncatedReason}">
        ${escapedTruncatedReason}
      </div>
    `;
        // Add click handler to expand/collapse truncated reason
        if (isTruncated) {
            const reasonElement = item.querySelector(".playback-routing__reason");
            if (reasonElement) {
                reasonElement.addEventListener("click", () => {
                    const isExpanded = reasonElement.classList.contains("playback-routing__reason--expanded");
                    if (isExpanded) {
                        reasonElement.textContent = reasonElement.getAttribute("data-truncated-reason") || "";
                        reasonElement.classList.remove("playback-routing__reason--expanded");
                        reasonElement.classList.add("playback-routing__reason--truncated");
                    }
                    else {
                        reasonElement.textContent = reasonElement.getAttribute("data-full-reason") || "";
                        reasonElement.classList.add("playback-routing__reason--expanded");
                        reasonElement.classList.remove("playback-routing__reason--truncated");
                    }
                });
            }
        }
        container.appendChild(item);
        // Auto-scroll to bottom
        container.scrollTop = container.scrollHeight;
    }
    /**
     * Render all routing decisions as a timeline
     */
    renderRoutingHistory() {
        const container = this.options.routingContainer;
        if (!container)
            return;
        // Clear existing content
        container.innerHTML = "";
        // Add timeline wrapper
        const timeline = document.createElement("div");
        timeline.className = "playback-routing-timeline";
        if (this.routingDecisions.length === 0) {
            const emptyMessage = document.createElement("div");
            emptyMessage.className = "playback-routing-timeline__empty";
            emptyMessage.textContent = "No routing decisions recorded";
            timeline.appendChild(emptyMessage);
        }
        else {
            // Render each decision
            for (const decision of this.routingDecisions) {
                const entry = this.createRoutingTimelineEntry(decision);
                timeline.appendChild(entry);
            }
        }
        container.appendChild(timeline);
    }
    /**
     * Create a timeline entry element for a routing decision
     */
    createRoutingTimelineEntry(decision) {
        const entry = document.createElement("div");
        const decisionTypeClass = this.getDecisionTypeClass(decision.decisionType);
        entry.className = `playback-routing-timeline__entry ${decisionTypeClass}`;
        const icon = this.getDecisionTypeIcon(decision.decisionType);
        const typeLabel = decision.decisionType || "advance";
        const timeDisplay = this.formatTimestamp(decision.timestamp);
        const { truncated: truncatedReason, isTruncated } = this.truncateText(decision.reason, 80);
        // Build iteration badge
        let iterationBadge = "";
        if (decision.loopIteration !== undefined) {
            iterationBadge = `<span class="playback-routing-timeline__iteration">#${decision.loopIteration}</span>`;
        }
        entry.innerHTML = `
      <div class="playback-routing-timeline__marker">
        <span class="playback-routing-timeline__icon">${icon}</span>
        <span class="playback-routing-timeline__line"></span>
      </div>
      <div class="playback-routing-timeline__content">
        <div class="playback-routing-timeline__header">
          <span class="playback-routing-timeline__type">${typeLabel}</span>
          ${iterationBadge}
          <span class="playback-routing-timeline__time">${timeDisplay}</span>
        </div>
        <div class="playback-routing-timeline__path">
          ${this.escapeHtml(decision.fromStep)} \u2192 ${this.escapeHtml(decision.toStep || "(end)")}
        </div>
        <div class="playback-routing-timeline__reason ${isTruncated ? "playback-routing-timeline__reason--truncated" : ""}"
             data-full="${this.escapeHtml(decision.reason)}"
             data-truncated="${this.escapeHtml(truncatedReason)}">
          ${this.escapeHtml(truncatedReason)}
        </div>
      </div>
    `;
        // Add click handler for truncated reason
        if (isTruncated) {
            const reasonElement = entry.querySelector(".playback-routing-timeline__reason");
            if (reasonElement) {
                reasonElement.addEventListener("click", () => {
                    const isExpanded = reasonElement.classList.contains("playback-routing-timeline__reason--expanded");
                    if (isExpanded) {
                        reasonElement.textContent = reasonElement.getAttribute("data-truncated") || "";
                        reasonElement.classList.remove("playback-routing-timeline__reason--expanded");
                        reasonElement.classList.add("playback-routing-timeline__reason--truncated");
                    }
                    else {
                        reasonElement.textContent = reasonElement.getAttribute("data-full") || "";
                        reasonElement.classList.add("playback-routing-timeline__reason--expanded");
                        reasonElement.classList.remove("playback-routing-timeline__reason--truncated");
                    }
                });
            }
        }
        return entry;
    }
    /**
     * Clear all output displays
     */
    clearOutputs() {
        if (this.options.outputContainer) {
            this.options.outputContainer.innerHTML = "";
        }
        if (this.options.routingContainer) {
            this.options.routingContainer.innerHTML = "";
        }
    }
    // ==========================================================================
    // Cleanup
    // ==========================================================================
    /**
     * Destroy the playback component
     */
    destroy() {
        this.stop();
        this.clearOutputs();
    }
}
// ============================================================================
// Factory Function
// ============================================================================
/**
 * Create a new run playback instance
 */
export function createRunPlayback(options) {
    return new RunPlayback(options);
}
// ============================================================================
// CSS Classes Documentation
// ============================================================================
/**
 * CSS class names used by this component:
 *
 * Node animation:
 * - .node-running - Pulsing animation for running nodes
 *
 * Output display:
 * - .playback-output - Output item container
 * - .playback-output--success - Success state
 * - .playback-output--error - Error state
 * - .playback-output__icon - Status icon
 * - .playback-output__step - Step ID
 * - .playback-output__agent - Agent key
 * - .playback-output__duration - Duration text
 *
 * Routing display (single decision):
 * - .playback-routing - Routing item container
 * - .playback-routing--advance - Advance decision type modifier
 * - .playback-routing--loop - Loop decision type modifier
 * - .playback-routing--terminate - Terminate decision type modifier
 * - .playback-routing--branch - Branch decision type modifier
 * - .playback-routing--bounce - Bounce decision type modifier
 * - .playback-routing--skip - Skip decision type modifier
 * - .playback-routing__header - Header with icon, type, timestamp
 * - .playback-routing__icon - Decision type icon
 * - .playback-routing__type - Decision type label
 * - .playback-routing__timestamp - Timestamp display
 * - .playback-routing__path - Path with from/to/arrow
 * - .playback-routing__from - Source step
 * - .playback-routing__arrow - Arrow indicator
 * - .playback-routing__to - Target step
 * - .playback-routing__iteration - Loop iteration badge
 * - .playback-routing__reason - Decision reason text
 * - .playback-routing__reason--truncated - Truncated reason (clickable to expand)
 * - .playback-routing__reason--expanded - Expanded reason
 *
 * Routing timeline (history view):
 * - .playback-routing-timeline - Timeline container
 * - .playback-routing-timeline__empty - Empty state message
 * - .playback-routing-timeline__entry - Single timeline entry
 * - .playback-routing-timeline__marker - Visual marker (icon + line)
 * - .playback-routing-timeline__icon - Entry icon
 * - .playback-routing-timeline__line - Vertical connector line
 * - .playback-routing-timeline__content - Entry content wrapper
 * - .playback-routing-timeline__header - Entry header
 * - .playback-routing-timeline__type - Decision type label
 * - .playback-routing-timeline__iteration - Iteration badge (#N)
 * - .playback-routing-timeline__time - Timestamp
 * - .playback-routing-timeline__path - From -> To path text
 * - .playback-routing-timeline__reason - Reason text
 * - .playback-routing-timeline__reason--truncated - Truncated reason (clickable)
 * - .playback-routing-timeline__reason--expanded - Expanded reason
 *
 * Recommended CSS for routing components:
 *
 * .playback-routing {
 *   padding: 8px 12px;
 *   margin-bottom: 8px;
 *   border-radius: 6px;
 *   background: var(--bg-secondary, #1e293b);
 *   border-left: 3px solid var(--border-color, #475569);
 * }
 *
 * .playback-routing--advance { border-left-color: #22c55e; }
 * .playback-routing--loop { border-left-color: #3b82f6; }
 * .playback-routing--terminate { border-left-color: #ef4444; }
 * .playback-routing--branch { border-left-color: #f59e0b; }
 * .playback-routing--bounce { border-left-color: #8b5cf6; }
 * .playback-routing--skip { border-left-color: #6b7280; }
 *
 * .playback-routing__header {
 *   display: flex;
 *   align-items: center;
 *   gap: 8px;
 *   margin-bottom: 4px;
 * }
 *
 * .playback-routing__icon { font-size: 1.1em; }
 * .playback-routing__type { font-weight: 600; text-transform: capitalize; }
 * .playback-routing__timestamp { color: var(--text-muted, #94a3b8); font-size: 0.85em; margin-left: auto; }
 *
 * .playback-routing__path {
 *   display: flex;
 *   align-items: center;
 *   gap: 6px;
 *   font-family: monospace;
 *   font-size: 0.9em;
 *   margin-bottom: 4px;
 * }
 *
 * .playback-routing__iteration {
 *   background: var(--badge-bg, #334155);
 *   padding: 2px 6px;
 *   border-radius: 4px;
 *   font-size: 0.8em;
 * }
 *
 * .playback-routing__reason {
 *   color: var(--text-secondary, #cbd5e1);
 *   font-size: 0.9em;
 *   line-height: 1.4;
 * }
 *
 * .playback-routing__reason--truncated {
 *   cursor: pointer;
 * }
 *
 * .playback-routing__reason--truncated:hover {
 *   text-decoration: underline;
 *   text-decoration-style: dotted;
 * }
 *
 * .playback-routing-timeline {
 *   display: flex;
 *   flex-direction: column;
 *   gap: 0;
 * }
 *
 * .playback-routing-timeline__entry {
 *   display: flex;
 *   gap: 12px;
 * }
 *
 * .playback-routing-timeline__marker {
 *   display: flex;
 *   flex-direction: column;
 *   align-items: center;
 *   width: 24px;
 * }
 *
 * .playback-routing-timeline__line {
 *   flex: 1;
 *   width: 2px;
 *   background: var(--border-color, #475569);
 *   margin-top: 4px;
 * }
 *
 * .playback-routing-timeline__content {
 *   flex: 1;
 *   padding-bottom: 16px;
 * }
 */
