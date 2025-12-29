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
import type { SSEEvent, SSEEventType, RunInfo } from "../api/client.js";
import type { FlowKey, CytoscapeInstance } from "../domain.js";

// ============================================================================
// Types
// ============================================================================

/**
 * Node animation state
 */
type NodeAnimationState = "idle" | "running" | "success" | "error" | "paused";

/**
 * Playback state
 */
type PlaybackState = "stopped" | "playing" | "paused";

/**
 * Routing decision for display
 */
interface RoutingDecision {
  timestamp: string;
  fromStep: string;
  toStep: string;
  reason: string;
  loopIteration?: number;
}

/**
 * Step output for display
 */
interface StepOutput {
  timestamp: string;
  stepId: string;
  agentKey?: string;
  status: "success" | "error";
  duration?: number;
  artifacts?: string[];
}

/**
 * Playback options
 */
interface RunPlaybackOptions {
  /** Cytoscape instance to animate */
  cy?: CytoscapeInstance;
  /** Container for output display */
  outputContainer?: HTMLElement;
  /** Container for routing decisions */
  routingContainer?: HTMLElement;
  /** Callback when step starts */
  onStepStart?: (event: SSEEvent) => void;
  /** Callback when step ends */
  onStepEnd?: (event: SSEEvent) => void;
  /** Callback when routing decision is made */
  onRoutingDecision?: (decision: RoutingDecision) => void;
  /** Callback when playback completes */
  onComplete?: () => void;
  /** Callback on error */
  onError?: (error: string) => void;
  /** Animation duration in ms */
  animationDuration?: number;
}

// ============================================================================
// Animation Styles
// ============================================================================

const ANIMATION_STYLES: Record<NodeAnimationState, Record<string, string>> = {
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
  private runId: string | null = null;
  private flowKey: FlowKey | null = null;
  private options: RunPlaybackOptions;
  private unsubscribe: (() => void) | null = null;
  private playbackState: PlaybackState = "stopped";
  private events: SSEEvent[] = [];
  private routingDecisions: RoutingDecision[] = [];
  private stepOutputs: StepOutput[] = [];
  private currentStepId: string | null = null;

  constructor(options: RunPlaybackOptions = {}) {
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
  async start(runId: string, flowKey?: FlowKey): Promise<void> {
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
  pause(): void {
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
  resume(): void {
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
  stop(): void {
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
  getState(): PlaybackState {
    return this.playbackState;
  }

  /**
   * Get all received events
   */
  getEvents(): SSEEvent[] {
    return [...this.events];
  }

  /**
   * Get routing decisions
   */
  getRoutingDecisions(): RoutingDecision[] {
    return [...this.routingDecisions];
  }

  /**
   * Get step outputs
   */
  getStepOutputs(): StepOutput[] {
    return [...this.stepOutputs];
  }

  // ==========================================================================
  // Event Handling
  // ==========================================================================

  /**
   * Handle an incoming SSE event
   */
  private handleEvent(event: SSEEvent): void {
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
  private handleStepStart(event: SSEEvent): void {
    const stepId = event.stepId;
    if (!stepId) return;

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
  private handleStepEnd(event: SSEEvent): void {
    const stepId = event.stepId;
    if (!stepId) return;

    const status = event.payload?.status as string;
    const animationState: NodeAnimationState =
      status === "error" || status === "failed" ? "error" : "success";

    this.animateNode(stepId, animationState);

    // Record step output
    const output: StepOutput = {
      timestamp: event.timestamp,
      stepId,
      agentKey: event.agentKey || undefined,
      status: animationState === "error" ? "error" : "success",
      duration: event.payload?.duration_ms as number | undefined,
      artifacts: event.payload?.artifacts as string[] | undefined,
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
  private handleRoutingDecision(event: SSEEvent): void {
    const payload = event.payload || {};
    const decision: RoutingDecision = {
      timestamp: event.timestamp,
      fromStep: payload.from_step as string || "",
      toStep: payload.to_step as string || "",
      reason: payload.reason as string || "",
      loopIteration: payload.loop_iteration as number | undefined,
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
  private handleArtifactCreated(event: SSEEvent): void {
    // Could add artifact visualization here
    // For now, just log
    console.log("Artifact created:", event.payload?.path);
  }

  /**
   * Handle complete event
   */
  private handleComplete(_event: SSEEvent): void {
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
  private handleError(event: SSEEvent): void {
    // Mark current step as error
    if (this.currentStepId) {
      this.animateNode(this.currentStepId, "error");
    }

    const errorMessage = event.payload?.error as string || "Unknown error";

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
  private animateNode(stepId: string, state: NodeAnimationState): void {
    const cy = this.options.cy;
    if (!cy) return;

    // Find the node
    const nodeId = this.flowKey ? `step:${this.flowKey}:${stepId}` : stepId;
    const node = cy.getElementById(nodeId);
    if (!node) return;

    const styles = ANIMATION_STYLES[state];
    const duration = this.options.animationDuration || 300;

    // Animate using Cytoscape's animation
    (node as unknown as {
      animate: (opts: {
        style: Record<string, string>;
        duration: number;
        easing: string;
      }) => void;
    }).animate({
      style: styles,
      duration,
      easing: "ease-in-out",
    });

    // Add pulsing effect for running state
    if (state === "running") {
      (node as unknown as { addClass: (cls: string) => void }).addClass("node-running");
    } else {
      (node as unknown as { removeClass: (cls: string) => void }).removeClass("node-running");
    }
  }

  /**
   * Animate an edge (highlight the path)
   */
  private animateEdge(fromStep: string, toStep: string): void {
    const cy = this.options.cy;
    if (!cy) return;

    // Find edge between steps
    const edges = cy.edges().filter((edge) => {
      const source = edge.data("source") as string;
      const target = edge.data("target") as string;
      return (
        (source.includes(fromStep) && target.includes(toStep)) ||
        (source === fromStep && target === toStep)
      );
    });

    if (edges.length === 0) return;

    const duration = this.options.animationDuration || 300;

    // Highlight edge
    edges.forEach((edge) => {
      (edge as unknown as {
        animate: (opts: {
          style: Record<string, string | number>;
          duration: number;
          easing: string;
        }) => { play: () => void };
      }).animate({
        style: {
          "line-color": "#3b82f6",
          width: 4,
        },
        duration,
        easing: "ease-in-out",
      }).play();

      // Reset after animation
      setTimeout(() => {
        (edge as unknown as {
          animate: (opts: {
            style: Record<string, string | number>;
            duration: number;
            easing: string;
          }) => { play: () => void };
        }).animate({
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
  private focusNode(stepId: string): void {
    const cy = this.options.cy;
    if (!cy) return;

    const nodeId = this.flowKey ? `step:${this.flowKey}:${stepId}` : stepId;
    const node = cy.getElementById(nodeId);
    if (!node) return;

    // Smooth pan to center the node
    (cy as unknown as {
      animate: (opts: {
        center: { eles: unknown };
        duration: number;
        easing: string;
      }) => void;
    }).animate({
      center: { eles: node },
      duration: this.options.animationDuration || 300,
      easing: "ease-in-out",
    });
  }

  /**
   * Reset all nodes to idle state
   */
  private resetNodeStates(): void {
    const cy = this.options.cy;
    if (!cy) return;

    cy.nodes('[type = "step"]').forEach((node) => {
      const styles = ANIMATION_STYLES.idle;
      Object.entries(styles).forEach(([key, value]) => {
        (node as unknown as { style: (key: string, value: string) => void }).style(key, value);
      });
      (node as unknown as { removeClass: (cls: string) => void }).removeClass("node-running");
    });
  }

  // ==========================================================================
  // UI Rendering
  // ==========================================================================

  /**
   * Render a step output to the output container
   */
  private renderStepOutput(output: StepOutput): void {
    const container = this.options.outputContainer;
    if (!container) return;

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
  private renderRoutingDecision(decision: RoutingDecision): void {
    const container = this.options.routingContainer;
    if (!container) return;

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
  clearOutputs(): void {
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
  destroy(): void {
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
export function createRunPlayback(options?: RunPlaybackOptions): RunPlayback {
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
