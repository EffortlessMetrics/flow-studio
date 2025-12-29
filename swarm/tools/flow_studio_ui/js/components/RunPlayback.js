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
     * Render a routing decision to the routing container
     */
    renderRoutingDecision(decision) {
        const container = this.options.routingContainer;
        if (!container)
            return;
        const item = document.createElement("div");
        item.className = "playback-routing";
        let iterationText = "";
        if (decision.loopIteration !== undefined) {
            iterationText = `<span class="playback-routing__iteration">Loop #${decision.loopIteration}</span>`;
        }
        item.innerHTML = `
      <div class="playback-routing__header">
        <span class="playback-routing__from">${decision.fromStep}</span>
        <span class="playback-routing__arrow">\u2192</span>
        <span class="playback-routing__to">${decision.toStep}</span>
        ${iterationText}
      </div>
      <div class="playback-routing__reason">${decision.reason}</div>
    `;
        container.appendChild(item);
        // Auto-scroll to bottom
        container.scrollTop = container.scrollHeight;
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
 * Routing display:
 * - .playback-routing - Routing item container
 * - .playback-routing__header - Header with from/to/arrow
 * - .playback-routing__from - Source step
 * - .playback-routing__arrow - Arrow indicator
 * - .playback-routing__to - Target step
 * - .playback-routing__iteration - Loop iteration badge
 * - .playback-routing__reason - Decision reason
 */
