import type { FlowKey } from "../domain.js";
/**
 * Routing decision types from the V3 Routing Protocol
 */
export type RoutingDecisionType = "CONTINUE" | "DETOUR" | "INJECT_FLOW" | "INJECT_NODES" | "EXTEND_GRAPH";
/**
 * A single frame in the interruption stack.
 * Represents a paused execution context waiting to resume.
 */
export interface StackFrame {
    /** Unique identifier for this frame */
    frameId: string;
    /** The flow that was interrupted */
    flowKey: FlowKey;
    /** The step where interruption occurred */
    stepId: string;
    /** Human-readable step name */
    stepLabel?: string;
    /** Reason for the interruption */
    reason: string;
    /** The utility flow or nodes that were injected */
    injectedTarget: string;
    /** Type of injection */
    injectionType: RoutingDecisionType;
    /** Timestamp when interrupted */
    interruptedAt: string;
    /** Goal inherited from parent (for context) */
    inheritedGoal?: string;
    /** Return point description */
    returnPoint: string;
    /** Evidence supporting the injection decision */
    evidence?: string[];
    /** Additional why-now context */
    whyNow?: {
        trigger: string;
        relevanceToCharter?: string;
        expectedOutcome?: string;
    };
}
/**
 * Complete interruption stack state
 */
export interface InterruptionStack {
    /** Current stack depth (0 = root flow, no interruptions) */
    depth: number;
    /** Maximum allowed depth */
    maxDepth: number;
    /** Stack frames from bottom (oldest) to top (current) */
    frames: StackFrame[];
    /** The currently executing flow */
    currentFlow: FlowKey;
    /** The currently executing step */
    currentStep: string;
    /** Root goal context */
    rootGoal?: string;
    /** Whether currently in an off-road state */
    offroad: boolean;
}
/**
 * Options for the InterruptionStackPanel
 */
export interface InterruptionStackPanelOptions {
    /** Container element to render into */
    container: HTMLElement;
    /** Callback when a frame is clicked */
    onFrameClick?: (frame: StackFrame) => void;
    /** Whether to show in compact mode */
    compact?: boolean;
}
/**
 * Renders an interruption stack visualization.
 * Shows the nested execution context when flows are injected as detours.
 */
export declare class InterruptionStackPanel {
    private container;
    private options;
    private currentStack;
    constructor(options: InterruptionStackPanelOptions);
    /**
     * Render the stack visualization
     */
    render(stack: InterruptionStack): void;
    /**
     * Update the stack without full re-render
     */
    update(stack: InterruptionStack): void;
    /**
     * Clear the panel
     */
    clear(): void;
    /**
     * Get current stack data
     */
    getStack(): InterruptionStack | null;
    /**
     * Render the header with depth indicator and status
     */
    private renderHeader;
    /**
     * Render depth indicator pills
     */
    private renderDepthIndicator;
    /**
     * Render status badge
     */
    private renderStatusBadge;
    /**
     * Render visual breadcrumb trail
     */
    private renderBreadcrumbs;
    /**
     * Render stack frames list
     */
    private renderFrames;
    /**
     * Render a single stack frame
     */
    private renderFrame;
    /**
     * Render why-now context block
     */
    private renderWhyNow;
    /**
     * Render evidence links
     */
    private renderEvidence;
    /**
     * Render empty state when no interruptions
     */
    private renderEmptyState;
    /**
     * Inject component styles
     */
    private injectStyles;
}
/**
 * Create a new InterruptionStackPanel instance
 */
export declare function createInterruptionStackPanel(options: InterruptionStackPanelOptions): InterruptionStackPanel;
/**
 * Create an empty/default interruption stack
 */
export declare function createEmptyStack(currentFlow: FlowKey, currentStep: string): InterruptionStack;
/**
 * Parse stack data from API response.
 * Converts raw routing decisions and detours into a structured stack.
 */
export declare function parseStackFromApiResponse(runData: {
    detours?: Array<{
        detour_id: string;
        from_step: string;
        to_step: string;
        reason: string;
        detour_type: string;
        evidence_path?: string;
        timestamp?: string;
    }>;
    routing_decisions?: Array<{
        decision: string;
        target: string;
        justification: string;
        evidence: string[];
        offroad: boolean;
        source_node: string;
        stack_depth: number;
        timestamp: string;
        why_now?: {
            trigger: string;
            relevance_to_charter?: string;
            expected_outcome?: string;
        };
    }>;
}, currentFlow: FlowKey, currentStep: string): InterruptionStack;
/**
 * Render the interruption stack as tab content in the Step Details panel.
 * This is the entry point for integrating with the details.ts module.
 */
export declare function renderInterruptionStackTab(container: HTMLElement, runId: string | null, flowKey: FlowKey | null, stepId: string | null, fetchBoundaryReview: (runId: string) => Promise<{
    detours?: Array<{
        detour_id: string;
        from_step: string;
        to_step: string;
        reason: string;
        detour_type: string;
        evidence_path?: string;
        timestamp?: string;
    }>;
}>): Promise<void>;
/**
 * CSS class names used by this component:
 *
 * .interruption-stack-panel - Main container
 * .interruption-stack-panel--compact - Compact mode variant
 *
 * Header:
 * .interruption-stack__header - Header container
 * .interruption-stack__header-left - Left side with title and status
 * .interruption-stack__header-right - Right side with depth indicator
 * .interruption-stack__title - Panel title text
 * .interruption-stack__status - Status badge
 * .interruption-stack__status--normal - Normal/golden path status
 * .interruption-stack__status--offroad - Off-road status
 * .interruption-stack__status--nested - Nested execution status
 *
 * Depth Indicator:
 * .interruption-stack__depth-indicator - Depth pill container
 * .interruption-stack__depth-pill - Individual depth pill
 * .interruption-stack__depth-pill--current - Current depth pill
 * .interruption-stack__depth-pill--active - Active (traversed) depth pill
 * .interruption-stack__depth-pill--inactive - Inactive depth pill
 * .interruption-stack__depth-label - Depth text label (e.g., "2/3")
 *
 * Breadcrumbs:
 * .interruption-stack__breadcrumbs - Breadcrumb trail container
 * .interruption-stack__crumb - Individual breadcrumb
 * .interruption-stack__crumb--root - Root crumb (home icon)
 * .interruption-stack__crumb--current - Current position crumb
 * .interruption-stack__crumb-arrow - Arrow between crumbs
 *
 * Frames:
 * .interruption-stack__frames - Frames list container
 * .interruption-stack__section-title - Section title (e.g., "Paused Contexts")
 * .interruption-stack__frame - Single frame card
 * .interruption-stack__frame-header - Frame header with type badge
 * .interruption-stack__frame-badge - Injection type badge
 * .interruption-stack__frame-top-badge - "TOP" indicator for topmost frame
 * .interruption-stack__frame-body - Frame content body
 * .interruption-stack__frame-row - Key-value row in frame
 * .interruption-stack__frame-label - Row label
 * .interruption-stack__frame-value - Row value
 *
 * Why-Now Block:
 * .interruption-stack__why-now - Why-now context block
 * .interruption-stack__why-now-title - Why-now title
 * .interruption-stack__why-now-content - Why-now content
 *
 * Evidence:
 * .interruption-stack__evidence-row - Evidence row
 * .interruption-stack__evidence-list - Evidence items container
 * .interruption-stack__evidence-item - Single evidence item
 *
 * Empty State:
 * .interruption-stack__empty - Empty state container
 * .interruption-stack__empty-icon - Empty state icon
 * .interruption-stack__empty-title - Empty state title
 * .interruption-stack__empty-desc - Empty state description
 */
