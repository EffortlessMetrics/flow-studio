// swarm/tools/flow_studio_ui/src/components/InterruptionStackPanel.ts
// Interruption Stack Panel for Flow Studio
//
// Visualizes the flow injection/detour stack during execution.
// Shows operators the current depth and execution path when utility flows
// are injected (detours) and return to their caller.
//
// NO filesystem operations - all data flows through the API.

import type { FlowKey } from "../domain.js";
import { escapeHtml } from "../utils.js";

// ============================================================================
// Types
// ============================================================================

/**
 * Routing decision types from the V3 Routing Protocol
 */
export type RoutingDecisionType =
  | "CONTINUE"
  | "DETOUR"
  | "INJECT_FLOW"
  | "INJECT_NODES"
  | "EXTEND_GRAPH";

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

// ============================================================================
// Styling Constants
// ============================================================================

const INJECTION_TYPE_STYLES: Record<RoutingDecisionType, {
  icon: string;
  color: string;
  bgColor: string;
  label: string;
}> = {
  CONTINUE: {
    icon: "\u27a1\ufe0f",
    color: "#166534",
    bgColor: "#dcfce7",
    label: "Continue"
  },
  DETOUR: {
    icon: "\u21a9\ufe0f",
    color: "#c2410c",
    bgColor: "#ffedd5",
    label: "Detour"
  },
  INJECT_FLOW: {
    icon: "\u2935\ufe0f",
    color: "#7c3aed",
    bgColor: "#ede9fe",
    label: "Flow Injection"
  },
  INJECT_NODES: {
    icon: "\u2795",
    color: "#0369a1",
    bgColor: "#e0f2fe",
    label: "Node Injection"
  },
  EXTEND_GRAPH: {
    icon: "\u2728",
    color: "#b45309",
    bgColor: "#fef3c7",
    label: "Graph Extension"
  }
};

// ============================================================================
// InterruptionStackPanel Component
// ============================================================================

/**
 * Renders an interruption stack visualization.
 * Shows the nested execution context when flows are injected as detours.
 */
export class InterruptionStackPanel {
  private container: HTMLElement;
  private options: InterruptionStackPanelOptions;
  private currentStack: InterruptionStack | null = null;

  constructor(options: InterruptionStackPanelOptions) {
    this.container = options.container;
    this.options = options;
  }

  // ==========================================================================
  // Public Methods
  // ==========================================================================

  /**
   * Render the stack visualization
   */
  render(stack: InterruptionStack): void {
    this.currentStack = stack;
    this.container.innerHTML = "";

    // Add styles if not already present
    this.injectStyles();

    // Create main container
    const panel = document.createElement("div");
    panel.className = "interruption-stack-panel";
    panel.setAttribute("data-uiid", "flow_studio.inspector.interruption_stack");

    // Render header with depth indicator
    panel.appendChild(this.renderHeader(stack));

    // Render breadcrumb trail
    panel.appendChild(this.renderBreadcrumbs(stack));

    // Render stack frames
    if (stack.frames.length > 0) {
      panel.appendChild(this.renderFrames(stack));
    } else {
      panel.appendChild(this.renderEmptyState());
    }

    this.container.appendChild(panel);
  }

  /**
   * Update the stack without full re-render
   */
  update(stack: InterruptionStack): void {
    this.render(stack);
  }

  /**
   * Clear the panel
   */
  clear(): void {
    this.container.innerHTML = "";
    this.currentStack = null;
  }

  /**
   * Get current stack data
   */
  getStack(): InterruptionStack | null {
    return this.currentStack;
  }

  // ==========================================================================
  // Rendering Methods
  // ==========================================================================

  /**
   * Render the header with depth indicator and status
   */
  private renderHeader(stack: InterruptionStack): HTMLElement {
    const header = document.createElement("div");
    header.className = "interruption-stack__header";

    const depthIndicator = this.renderDepthIndicator(stack.depth, stack.maxDepth);
    const statusBadge = this.renderStatusBadge(stack.offroad, stack.depth);

    header.innerHTML = `
      <div class="interruption-stack__header-left">
        <span class="interruption-stack__title">Execution Stack</span>
        ${statusBadge}
      </div>
      <div class="interruption-stack__header-right">
        ${depthIndicator}
      </div>
    `;

    return header;
  }

  /**
   * Render depth indicator pills
   */
  private renderDepthIndicator(depth: number, maxDepth: number): string {
    const pills: string[] = [];
    for (let i = 0; i <= maxDepth; i++) {
      const isActive = i <= depth;
      const isCurrent = i === depth;
      const pillClass = isActive
        ? isCurrent
          ? "interruption-stack__depth-pill--current"
          : "interruption-stack__depth-pill--active"
        : "interruption-stack__depth-pill--inactive";
      pills.push(`<span class="interruption-stack__depth-pill ${pillClass}" title="Depth ${i}"></span>`);
    }
    return `
      <div class="interruption-stack__depth-indicator" title="Stack depth: ${depth}/${maxDepth}">
        ${pills.join("")}
        <span class="interruption-stack__depth-label">${depth}/${maxDepth}</span>
      </div>
    `;
  }

  /**
   * Render status badge
   */
  private renderStatusBadge(offroad: boolean, depth: number): string {
    if (depth === 0 && !offroad) {
      return `<span class="interruption-stack__status interruption-stack__status--normal">On Golden Path</span>`;
    }
    if (offroad) {
      return `<span class="interruption-stack__status interruption-stack__status--offroad">Off-Road</span>`;
    }
    return `<span class="interruption-stack__status interruption-stack__status--nested">Nested Execution</span>`;
  }

  /**
   * Render visual breadcrumb trail
   */
  private renderBreadcrumbs(stack: InterruptionStack): HTMLElement {
    const breadcrumbs = document.createElement("div");
    breadcrumbs.className = "interruption-stack__breadcrumbs";

    // Start with root
    let html = `<span class="interruption-stack__crumb interruption-stack__crumb--root" title="Root execution">\u{1F3E0}</span>`;

    // Add each frame as a crumb
    stack.frames.forEach((frame, index) => {
      const style = INJECTION_TYPE_STYLES[frame.injectionType];
      html += `
        <span class="interruption-stack__crumb-arrow">\u2192</span>
        <span class="interruption-stack__crumb"
              style="background: ${style.bgColor}; color: ${style.color};"
              title="${escapeHtml(frame.reason)}"
              data-frame-index="${index}">
          ${style.icon} ${escapeHtml(frame.injectedTarget)}
        </span>
      `;
    });

    // Add current position
    html += `
      <span class="interruption-stack__crumb-arrow">\u2192</span>
      <span class="interruption-stack__crumb interruption-stack__crumb--current" title="Current position">
        \u{1F4CD} ${escapeHtml(stack.currentFlow)}:${escapeHtml(stack.currentStep)}
      </span>
    `;

    breadcrumbs.innerHTML = html;

    // Add click handlers for crumbs
    breadcrumbs.querySelectorAll("[data-frame-index]").forEach((el) => {
      el.addEventListener("click", () => {
        const index = parseInt((el as HTMLElement).dataset.frameIndex || "0", 10);
        if (this.options.onFrameClick && stack.frames[index]) {
          this.options.onFrameClick(stack.frames[index]);
        }
      });
    });

    return breadcrumbs;
  }

  /**
   * Render stack frames list
   */
  private renderFrames(stack: InterruptionStack): HTMLElement {
    const framesContainer = document.createElement("div");
    framesContainer.className = "interruption-stack__frames";

    const sectionTitle = document.createElement("div");
    sectionTitle.className = "interruption-stack__section-title";
    sectionTitle.textContent = `Paused Contexts (${stack.frames.length})`;
    framesContainer.appendChild(sectionTitle);

    // Render frames in reverse order (top of stack first)
    const reversedFrames = [...stack.frames].reverse();
    reversedFrames.forEach((frame, visualIndex) => {
      const actualIndex = stack.frames.length - 1 - visualIndex;
      const frameEl = this.renderFrame(frame, actualIndex, stack.depth);
      framesContainer.appendChild(frameEl);
    });

    return framesContainer;
  }

  /**
   * Render a single stack frame
   */
  private renderFrame(frame: StackFrame, index: number, totalDepth: number): HTMLElement {
    const frameEl = document.createElement("div");
    frameEl.className = "interruption-stack__frame";
    frameEl.dataset.frameId = frame.frameId;

    const style = INJECTION_TYPE_STYLES[frame.injectionType];
    const isTopOfStack = index === totalDepth - 1;

    frameEl.innerHTML = `
      <div class="interruption-stack__frame-header" style="border-left-color: ${style.color};">
        <div class="interruption-stack__frame-badge" style="background: ${style.bgColor}; color: ${style.color};">
          ${style.icon} ${escapeHtml(style.label)}
        </div>
        ${isTopOfStack ? '<span class="interruption-stack__frame-top-badge">TOP</span>' : ''}
      </div>

      <div class="interruption-stack__frame-body">
        <div class="interruption-stack__frame-row">
          <span class="interruption-stack__frame-label">Interrupted At</span>
          <span class="interruption-stack__frame-value mono">
            ${escapeHtml(frame.flowKey)}:${escapeHtml(frame.stepId)}
            ${frame.stepLabel ? `<span class="muted">(${escapeHtml(frame.stepLabel)})</span>` : ""}
          </span>
        </div>

        <div class="interruption-stack__frame-row">
          <span class="interruption-stack__frame-label">Injected</span>
          <span class="interruption-stack__frame-value mono">${escapeHtml(frame.injectedTarget)}</span>
        </div>

        <div class="interruption-stack__frame-row">
          <span class="interruption-stack__frame-label">Reason</span>
          <span class="interruption-stack__frame-value">${escapeHtml(frame.reason)}</span>
        </div>

        <div class="interruption-stack__frame-row">
          <span class="interruption-stack__frame-label">Return To</span>
          <span class="interruption-stack__frame-value mono">${escapeHtml(frame.returnPoint)}</span>
        </div>

        ${frame.whyNow ? this.renderWhyNow(frame.whyNow) : ""}
        ${frame.evidence && frame.evidence.length > 0 ? this.renderEvidence(frame.evidence) : ""}
      </div>
    `;

    // Add click handler
    frameEl.addEventListener("click", () => {
      if (this.options.onFrameClick) {
        this.options.onFrameClick(frame);
      }
    });

    return frameEl;
  }

  /**
   * Render why-now context block
   */
  private renderWhyNow(whyNow: StackFrame["whyNow"]): string {
    if (!whyNow) return "";

    return `
      <div class="interruption-stack__why-now">
        <div class="interruption-stack__why-now-title">Why Now?</div>
        <div class="interruption-stack__why-now-content">
          <div><strong>Trigger:</strong> ${escapeHtml(whyNow.trigger)}</div>
          ${whyNow.relevanceToCharter ? `<div><strong>Charter Relevance:</strong> ${escapeHtml(whyNow.relevanceToCharter)}</div>` : ""}
          ${whyNow.expectedOutcome ? `<div><strong>Expected Outcome:</strong> ${escapeHtml(whyNow.expectedOutcome)}</div>` : ""}
        </div>
      </div>
    `;
  }

  /**
   * Render evidence links
   */
  private renderEvidence(evidence: string[]): string {
    const items = evidence.map(e => `<span class="interruption-stack__evidence-item mono">${escapeHtml(e)}</span>`).join("");
    return `
      <div class="interruption-stack__frame-row interruption-stack__evidence-row">
        <span class="interruption-stack__frame-label">Evidence</span>
        <div class="interruption-stack__evidence-list">${items}</div>
      </div>
    `;
  }

  /**
   * Render empty state when no interruptions
   */
  private renderEmptyState(): HTMLElement {
    const empty = document.createElement("div");
    empty.className = "interruption-stack__empty";
    empty.innerHTML = `
      <div class="interruption-stack__empty-icon">\u2705</div>
      <div class="interruption-stack__empty-title">No Interruptions</div>
      <div class="interruption-stack__empty-desc">
        Execution is proceeding on the golden path with no injected flows or detours.
      </div>
    `;
    return empty;
  }

  /**
   * Inject component styles
   */
  private injectStyles(): void {
    const styleId = "interruption-stack-styles";
    if (document.getElementById(styleId)) {
      return;
    }

    const styles = document.createElement("style");
    styles.id = styleId;
    styles.textContent = `
      .interruption-stack-panel {
        font-size: var(--fs-font-size-sm, 11px);
      }

      .interruption-stack__header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: var(--fs-spacing-sm, 8px) 0;
        border-bottom: 1px solid var(--fs-color-border, #e5e7eb);
        margin-bottom: var(--fs-spacing-sm, 8px);
      }

      .interruption-stack__header-left {
        display: flex;
        align-items: center;
        gap: var(--fs-spacing-sm, 8px);
      }

      .interruption-stack__title {
        font-weight: 600;
        font-size: var(--fs-font-size-md, 13px);
        color: var(--fs-color-text, #111827);
      }

      .interruption-stack__status {
        display: inline-block;
        padding: 2px 8px;
        border-radius: var(--fs-radius-full, 9999px);
        font-size: var(--fs-font-size-xs, 10px);
        font-weight: 500;
      }

      .interruption-stack__status--normal {
        background: #dcfce7;
        color: #166534;
      }

      .interruption-stack__status--offroad {
        background: #fee2e2;
        color: #991b1b;
      }

      .interruption-stack__status--nested {
        background: #ede9fe;
        color: #7c3aed;
      }

      .interruption-stack__depth-indicator {
        display: flex;
        align-items: center;
        gap: 4px;
      }

      .interruption-stack__depth-pill {
        width: 8px;
        height: 8px;
        border-radius: 50%;
        transition: all var(--fs-transition-fast, 0.15s ease);
      }

      .interruption-stack__depth-pill--current {
        background: #3b82f6;
        box-shadow: 0 0 4px rgba(59, 130, 246, 0.5);
      }

      .interruption-stack__depth-pill--active {
        background: #93c5fd;
      }

      .interruption-stack__depth-pill--inactive {
        background: #e5e7eb;
      }

      .interruption-stack__depth-label {
        font-size: var(--fs-font-size-xs, 10px);
        color: var(--fs-color-text-muted, #6b7280);
        margin-left: 4px;
      }

      .interruption-stack__breadcrumbs {
        display: flex;
        align-items: center;
        flex-wrap: wrap;
        gap: 4px;
        padding: var(--fs-spacing-sm, 8px);
        background: var(--fs-color-bg-muted, #f9fafb);
        border-radius: var(--fs-radius-md, 4px);
        margin-bottom: var(--fs-spacing-md, 12px);
      }

      .interruption-stack__crumb {
        display: inline-flex;
        align-items: center;
        gap: 4px;
        padding: 3px 8px;
        border-radius: var(--fs-radius-sm, 3px);
        font-size: var(--fs-font-size-xs, 10px);
        cursor: pointer;
        transition: all var(--fs-transition-fast, 0.15s ease);
      }

      .interruption-stack__crumb:hover {
        opacity: 0.8;
        transform: translateY(-1px);
      }

      .interruption-stack__crumb--root {
        background: var(--fs-color-bg-subtle, #f3f4f6);
        color: var(--fs-color-text-muted, #6b7280);
      }

      .interruption-stack__crumb--current {
        background: #dbeafe;
        color: #1e40af;
        font-weight: 500;
      }

      .interruption-stack__crumb-arrow {
        color: var(--fs-color-text-muted, #6b7280);
        font-size: 10px;
      }

      .interruption-stack__section-title {
        font-size: var(--fs-font-size-xs, 10px);
        font-weight: 600;
        color: var(--fs-color-text-muted, #6b7280);
        text-transform: uppercase;
        letter-spacing: 0.05em;
        margin-bottom: var(--fs-spacing-sm, 8px);
      }

      .interruption-stack__frames {
        display: flex;
        flex-direction: column;
        gap: var(--fs-spacing-sm, 8px);
      }

      .interruption-stack__frame {
        background: var(--fs-color-bg-base, #ffffff);
        border: 1px solid var(--fs-color-border, #e5e7eb);
        border-radius: var(--fs-radius-md, 4px);
        overflow: hidden;
        cursor: pointer;
        transition: all var(--fs-transition-fast, 0.15s ease);
      }

      .interruption-stack__frame:hover {
        border-color: var(--fs-color-border-strong, #d1d5db);
        box-shadow: var(--fs-shadow-sm, 0 1px 2px rgba(0, 0, 0, 0.05));
      }

      .interruption-stack__frame-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: var(--fs-spacing-xs, 4px) var(--fs-spacing-sm, 8px);
        background: var(--fs-color-bg-muted, #f9fafb);
        border-left: 3px solid;
      }

      .interruption-stack__frame-badge {
        display: inline-flex;
        align-items: center;
        gap: 4px;
        padding: 2px 6px;
        border-radius: var(--fs-radius-sm, 3px);
        font-size: var(--fs-font-size-xs, 10px);
        font-weight: 500;
      }

      .interruption-stack__frame-top-badge {
        display: inline-block;
        padding: 1px 4px;
        background: #3b82f6;
        color: white;
        border-radius: var(--fs-radius-sm, 3px);
        font-size: 8px;
        font-weight: 700;
        letter-spacing: 0.05em;
      }

      .interruption-stack__frame-body {
        padding: var(--fs-spacing-sm, 8px);
      }

      .interruption-stack__frame-row {
        display: flex;
        align-items: flex-start;
        gap: var(--fs-spacing-sm, 8px);
        margin-bottom: var(--fs-spacing-xs, 4px);
      }

      .interruption-stack__frame-row:last-child {
        margin-bottom: 0;
      }

      .interruption-stack__frame-label {
        flex-shrink: 0;
        width: 80px;
        font-size: var(--fs-font-size-xs, 10px);
        color: var(--fs-color-text-muted, #6b7280);
        font-weight: 500;
      }

      .interruption-stack__frame-value {
        flex: 1;
        color: var(--fs-color-text, #111827);
        word-break: break-word;
      }

      .interruption-stack__why-now {
        margin-top: var(--fs-spacing-sm, 8px);
        padding: var(--fs-spacing-sm, 8px);
        background: #fefce8;
        border-radius: var(--fs-radius-sm, 3px);
        border-left: 2px solid #facc15;
      }

      .interruption-stack__why-now-title {
        font-size: var(--fs-font-size-xs, 10px);
        font-weight: 600;
        color: #854d0e;
        margin-bottom: var(--fs-spacing-xs, 4px);
      }

      .interruption-stack__why-now-content {
        font-size: var(--fs-font-size-xs, 10px);
        color: #713f12;
        line-height: 1.5;
      }

      .interruption-stack__why-now-content div {
        margin-bottom: 2px;
      }

      .interruption-stack__evidence-row {
        margin-top: var(--fs-spacing-xs, 4px);
      }

      .interruption-stack__evidence-list {
        display: flex;
        flex-wrap: wrap;
        gap: 4px;
      }

      .interruption-stack__evidence-item {
        display: inline-block;
        padding: 2px 6px;
        background: var(--fs-color-bg-subtle, #f3f4f6);
        border-radius: var(--fs-radius-sm, 3px);
        font-size: 9px;
        color: var(--fs-color-text-muted, #6b7280);
      }

      .interruption-stack__empty {
        text-align: center;
        padding: var(--fs-spacing-xl, 24px) var(--fs-spacing-lg, 16px);
      }

      .interruption-stack__empty-icon {
        font-size: 32px;
        margin-bottom: var(--fs-spacing-sm, 8px);
      }

      .interruption-stack__empty-title {
        font-weight: 600;
        color: var(--fs-color-text, #111827);
        margin-bottom: var(--fs-spacing-xs, 4px);
      }

      .interruption-stack__empty-desc {
        color: var(--fs-color-text-muted, #6b7280);
        font-size: var(--fs-font-size-xs, 10px);
        line-height: 1.5;
      }

      /* Compact mode */
      .interruption-stack-panel.interruption-stack-panel--compact .interruption-stack__frame-body {
        padding: var(--fs-spacing-xs, 4px) var(--fs-spacing-sm, 8px);
      }

      .interruption-stack-panel.interruption-stack-panel--compact .interruption-stack__why-now,
      .interruption-stack-panel.interruption-stack-panel--compact .interruption-stack__evidence-row {
        display: none;
      }
    `;
    document.head.appendChild(styles);
  }
}

// ============================================================================
// Factory Functions
// ============================================================================

/**
 * Create a new InterruptionStackPanel instance
 */
export function createInterruptionStackPanel(
  options: InterruptionStackPanelOptions
): InterruptionStackPanel {
  return new InterruptionStackPanel(options);
}

/**
 * Create an empty/default interruption stack
 */
export function createEmptyStack(currentFlow: FlowKey, currentStep: string): InterruptionStack {
  return {
    depth: 0,
    maxDepth: 3,
    frames: [],
    currentFlow,
    currentStep,
    offroad: false
  };
}

/**
 * Parse stack data from API response.
 * Converts raw routing decisions and detours into a structured stack.
 */
export function parseStackFromApiResponse(
  runData: {
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
  },
  currentFlow: FlowKey,
  currentStep: string
): InterruptionStack {
  const frames: StackFrame[] = [];
  let maxDepth = 0;

  // Convert routing decisions to stack frames
  if (runData.routing_decisions) {
    runData.routing_decisions.forEach((decision, index) => {
      if (decision.decision !== "CONTINUE" && decision.stack_depth > 0) {
        const [flowKey, stepId] = decision.source_node.split(".");
        frames.push({
          frameId: `frame-${index}`,
          flowKey: flowKey as FlowKey,
          stepId: stepId || "unknown",
          reason: decision.justification,
          injectedTarget: decision.target,
          injectionType: decision.decision as RoutingDecisionType,
          interruptedAt: decision.timestamp,
          returnPoint: decision.source_node,
          evidence: decision.evidence,
          whyNow: decision.why_now ? {
            trigger: decision.why_now.trigger,
            relevanceToCharter: decision.why_now.relevance_to_charter,
            expectedOutcome: decision.why_now.expected_outcome
          } : undefined
        });
        maxDepth = Math.max(maxDepth, decision.stack_depth);
      }
    });
  }

  // Fallback to detours if no routing decisions
  if (frames.length === 0 && runData.detours) {
    runData.detours.forEach((detour, index) => {
      const [flowKey, stepId] = detour.from_step.split(":");
      frames.push({
        frameId: detour.detour_id || `detour-${index}`,
        flowKey: (flowKey || "unknown") as FlowKey,
        stepId: stepId || detour.from_step,
        reason: detour.reason,
        injectedTarget: detour.to_step,
        injectionType: detour.detour_type === "INJECT_FLOW" ? "INJECT_FLOW" : "DETOUR",
        interruptedAt: detour.timestamp || new Date().toISOString(),
        returnPoint: detour.from_step
      });
    });
  }

  const depth = frames.length;
  const hasOffroad = runData.routing_decisions?.some(d => d.offroad) ?? false;

  return {
    depth,
    maxDepth: Math.max(3, maxDepth),
    frames,
    currentFlow,
    currentStep,
    offroad: hasOffroad
  };
}

// ============================================================================
// Tab Content Renderer
// ============================================================================

/**
 * Render the interruption stack as tab content in the Step Details panel.
 * This is the entry point for integrating with the details.ts module.
 */
export async function renderInterruptionStackTab(
  container: HTMLElement,
  runId: string | null,
  flowKey: FlowKey | null,
  stepId: string | null,
  fetchBoundaryReview: (runId: string) => Promise<{
    detours?: Array<{
      detour_id: string;
      from_step: string;
      to_step: string;
      reason: string;
      detour_type: string;
      evidence_path?: string;
      timestamp?: string;
    }>;
  }>
): Promise<void> {
  // Check if we have run context
  if (!runId || !flowKey || !stepId) {
    container.innerHTML = `
      <div class="muted" style="padding: 16px; text-align: center;">
        <div style="font-size: 24px; margin-bottom: 8px;">\u{1F4CB}</div>
        <div>Select a run to view the execution stack.</div>
      </div>
    `;
    return;
  }

  // Show loading state
  container.innerHTML = `
    <div class="muted" style="padding: 16px; text-align: center;">
      Loading execution stack...
    </div>
  `;

  try {
    // Fetch boundary review data which includes detours
    const reviewData = await fetchBoundaryReview(runId);

    // Parse into stack structure
    const stack = parseStackFromApiResponse(
      reviewData,
      flowKey,
      stepId
    );

    // Clear and render
    container.innerHTML = "";
    const panel = new InterruptionStackPanel({
      container,
      onFrameClick: (frame) => {
        console.log("Frame clicked:", frame);
        // Could navigate to the interrupted step here
      }
    });
    panel.render(stack);
  } catch (error) {
    console.error("Failed to load interruption stack:", error);
    container.innerHTML = `
      <div class="muted" style="padding: 16px; text-align: center;">
        <div style="font-size: 24px; margin-bottom: 8px;">\u26a0\ufe0f</div>
        <div>Could not load execution stack data.</div>
        <div style="font-size: 10px; margin-top: 4px; color: #9ca3af;">
          Stack data is available during stepwise execution.
        </div>
      </div>
    `;
  }
}

// ============================================================================
// CSS Class Names Reference
// ============================================================================

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
