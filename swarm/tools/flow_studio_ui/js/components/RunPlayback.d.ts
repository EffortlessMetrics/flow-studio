import type { SSEEvent } from "../api/client.js";
import type { FlowKey, CytoscapeInstance } from "../domain.js";
/**
 * Playback state
 */
type PlaybackState = "stopped" | "playing" | "paused";
/**
 * Routing decision type
 */
type RoutingDecisionType = "advance" | "loop" | "terminate" | "branch" | "skip" | "bounce";
/**
 * Routing decision for display
 */
interface RoutingDecision {
    timestamp: string;
    fromStep: string;
    toStep: string;
    reason: string;
    loopIteration?: number;
    decisionType?: RoutingDecisionType;
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
export declare class RunPlayback {
    private runId;
    private flowKey;
    private options;
    private unsubscribe;
    private playbackState;
    private events;
    private routingDecisions;
    private stepOutputs;
    private currentStepId;
    constructor(options?: RunPlaybackOptions);
    /**
     * Start playback for a run
     */
    start(runId: string, flowKey?: FlowKey): Promise<void>;
    /**
     * Pause playback (stop processing events but keep subscription)
     */
    pause(): void;
    /**
     * Resume paused playback
     */
    resume(): void;
    /**
     * Stop playback and clean up
     */
    stop(): void;
    /**
     * Get current playback state
     */
    getState(): PlaybackState;
    /**
     * Get all received events
     */
    getEvents(): SSEEvent[];
    /**
     * Get routing decisions
     */
    getRoutingDecisions(): RoutingDecision[];
    /**
     * Get step outputs
     */
    getStepOutputs(): StepOutput[];
    /**
     * Handle an incoming SSE event
     */
    private handleEvent;
    /**
     * Handle step_start event
     */
    private handleStepStart;
    /**
     * Handle step_end event
     */
    private handleStepEnd;
    /**
     * Handle routing_decision event
     */
    private handleRoutingDecision;
    /**
     * Handle artifact_created event
     */
    private handleArtifactCreated;
    /**
     * Handle complete event
     */
    private handleComplete;
    /**
     * Handle error event
     */
    private handleError;
    /**
     * Animate a node to a new state
     */
    private animateNode;
    /**
     * Animate an edge (highlight the path)
     */
    private animateEdge;
    /**
     * Focus the view on a node
     */
    private focusNode;
    /**
     * Reset all nodes to idle state
     */
    private resetNodeStates;
    /**
     * Render a step output to the output container
     */
    private renderStepOutput;
    /**
     * Get icon for routing decision type
     */
    private getDecisionTypeIcon;
    /**
     * Get CSS class modifier for routing decision type
     */
    private getDecisionTypeClass;
    /**
     * Format timestamp for display
     */
    private formatTimestamp;
    /**
     * Truncate text with ellipsis
     */
    private truncateText;
    /**
     * Escape HTML to prevent XSS
     */
    private escapeHtml;
    /**
     * Render a routing decision to the routing container
     */
    private renderRoutingDecision;
    /**
     * Render all routing decisions as a timeline
     */
    renderRoutingHistory(): void;
    /**
     * Create a timeline entry element for a routing decision
     */
    private createRoutingTimelineEntry;
    /**
     * Clear all output displays
     */
    clearOutputs(): void;
    /**
     * Destroy the playback component
     */
    destroy(): void;
}
/**
 * Create a new run playback instance
 */
export declare function createRunPlayback(options?: RunPlaybackOptions): RunPlayback;
export {};
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
