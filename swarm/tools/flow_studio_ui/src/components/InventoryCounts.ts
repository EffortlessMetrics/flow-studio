// swarm/tools/flow_studio_ui/src/components/InventoryCounts.ts
// Inventory marker counts component for Flow Studio
//
// Displays a horizontal bar showing REQ/SOL/TRC/ASM/DEC counts
// with delta indicators when counts change between steps.
//
// NO filesystem operations - all data flows through API.

import { escapeHtml } from "../utils.js";

// ============================================================================
// Types
// ============================================================================

/**
 * Count for a single marker type
 */
interface MarkerCount {
  marker_type: string;
  label: string;
  count: number;
}

/**
 * Flow marker counts
 */
interface FlowMarkerCounts {
  flow_key: string;
  counts: Record<string, number>;
  total: number;
}

/**
 * Step marker counts
 */
interface StepMarkerCounts {
  flow_key: string;
  step_id: string;
  counts: Record<string, number>;
  total: number;
}

/**
 * Delta between consecutive steps
 */
interface MarkerDelta {
  from_step: string;
  to_step: string;
  deltas: Record<string, number>;
  total_delta: number;
}

/**
 * Facts summary response from API
 */
export interface FactsSummaryResponse {
  run_id: string;
  total_facts: number;
  by_type: MarkerCount[];
  by_flow: FlowMarkerCounts[];
  by_step: StepMarkerCounts[];
  deltas: MarkerDelta[];
  errors: string[];
}

/**
 * Options for creating the inventory counts component
 */
export interface InventoryCountsOptions {
  /** Container element to render into */
  container: HTMLElement;
  /** Callback when a marker type is clicked */
  onTypeClick?: (markerType: string) => void;
  /** Callback when a flow is clicked */
  onFlowClick?: (flowKey: string) => void;
  /** Callback when a step is clicked */
  onStepClick?: (flowKey: string, stepId: string) => void;
}

// ============================================================================
// Constants
// ============================================================================

/** Marker type display configuration */
const MARKER_CONFIG: Record<string, { label: string; color: string; icon: string }> = {
  REQ: { label: "Requirements", color: "#3b82f6", icon: "R" },
  SOL: { label: "Solutions", color: "#10b981", icon: "S" },
  TRC: { label: "Traces", color: "#8b5cf6", icon: "T" },
  ASM: { label: "Assumptions", color: "#f59e0b", icon: "A" },
  DEC: { label: "Decisions", color: "#ef4444", icon: "D" },
};

/** Ordered list of marker types */
const MARKER_ORDER = ["REQ", "SOL", "TRC", "ASM", "DEC"];

// ============================================================================
// InventoryCounts Component
// ============================================================================

/**
 * Inventory counts component for displaying marker statistics.
 *
 * Features:
 * - Horizontal bar showing counts per marker type
 * - Delta indicators (+3, -1) when counts change
 * - Expandable details view
 * - Click handlers for drilling down
 */
export class InventoryCounts {
  private container: HTMLElement;
  private onTypeClick?: (markerType: string) => void;
  private onFlowClick?: (flowKey: string) => void;
  private onStepClick?: (flowKey: string, stepId: string) => void;

  private data: FactsSummaryResponse | null = null;
  private isExpanded = false;
  private isLoading = false;
  private errorMessage: string | null = null;
  private selectedStep: string | null = null;

  // Monotonic sequence counter for request coalescing
  // Prevents out-of-order UI renders under bursty SSE events
  private loadSeq = 0;

  constructor(options: InventoryCountsOptions) {
    this.container = options.container;
    this.onTypeClick = options.onTypeClick;
    this.onFlowClick = options.onFlowClick;
    this.onStepClick = options.onStepClick;
  }

  // ==========================================================================
  // Data Loading
  // ==========================================================================

  /**
   * Load inventory counts for a run.
   * Uses monotonic request ID guard to prevent out-of-order UI renders
   * when multiple requests are in flight (e.g., under bursty SSE).
   */
  async load(runId: string): Promise<void> {
    const seq = ++this.loadSeq;
    this.isLoading = true;
    this.errorMessage = null;
    this.render();

    try {
      const response = await fetch(`/api/runs/${encodeURIComponent(runId)}/facts/summary`);

      // Ignore stale response if a newer request was initiated
      if (seq !== this.loadSeq) {
        return;
      }

      if (!response.ok) {
        if (response.status === 404) {
          // No facts found - show empty state
          this.data = {
            run_id: runId,
            total_facts: 0,
            by_type: MARKER_ORDER.map(t => ({
              marker_type: t,
              label: MARKER_CONFIG[t]?.label || t,
              count: 0,
            })),
            by_flow: [],
            by_step: [],
            deltas: [],
            errors: [],
          };
        } else {
          throw new Error(`Failed to load facts: ${response.statusText}`);
        }
      } else {
        this.data = await response.json() as FactsSummaryResponse;
      }
      this.isLoading = false;
      this.render();
    } catch (err) {
      // Only update state if this is still the latest request
      if (seq !== this.loadSeq) {
        return;
      }
      this.isLoading = false;
      this.errorMessage = err instanceof Error ? err.message : "Failed to load inventory counts";
      this.render();
    }
  }

  /**
   * Set data directly (for testing or pre-loaded data)
   */
  setData(data: FactsSummaryResponse): void {
    this.data = data;
    this.isLoading = false;
    this.errorMessage = null;
    this.render();
  }

  /**
   * Get the deltas for a specific step
   */
  getDeltasForStep(flowKey: string, stepId: string): Record<string, number> | null {
    if (!this.data) return null;

    const stepKey = `${flowKey}:${stepId}`;
    const delta = this.data.deltas.find(d => d.to_step === stepKey);
    return delta ? delta.deltas : null;
  }

  // ==========================================================================
  // Rendering
  // ==========================================================================

  /**
   * Render the component
   */
  render(): void {
    this.container.innerHTML = "";
    this.container.className = "inventory-counts";
    this.container.setAttribute("data-uiid", "flow_studio.inventory.counts");

    if (this.isLoading) {
      this.container.appendChild(this.createLoadingState());
      return;
    }

    if (this.errorMessage) {
      this.container.appendChild(this.createErrorState());
      return;
    }

    if (!this.data || this.data.total_facts === 0) {
      this.container.appendChild(this.createEmptyState());
      return;
    }

    // Main content
    this.container.appendChild(this.createHeader());
    this.container.appendChild(this.createMarkerBar());

    if (this.isExpanded) {
      this.container.appendChild(this.createExpandedDetails());
    }
  }

  /**
   * Create loading state
   */
  private createLoadingState(): HTMLElement {
    const div = document.createElement("div");
    div.className = "inventory-counts__loading";
    div.innerHTML = `
      <div class="inventory-counts__spinner"></div>
      <span>Loading inventory...</span>
    `;
    return div;
  }

  /**
   * Create error state
   */
  private createErrorState(): HTMLElement {
    const div = document.createElement("div");
    div.className = "inventory-counts__error";
    div.innerHTML = `
      <span class="inventory-counts__error-icon">\u26A0</span>
      <span>${escapeHtml(this.errorMessage || "Unknown error")}</span>
    `;
    return div;
  }

  /**
   * Create empty state
   */
  private createEmptyState(): HTMLElement {
    const div = document.createElement("div");
    div.className = "inventory-counts__empty";
    div.innerHTML = `
      <span class="inventory-counts__empty-text">No inventory markers found</span>
    `;
    return div;
  }

  /**
   * Create header with total and expand button
   */
  private createHeader(): HTMLElement {
    const header = document.createElement("div");
    header.className = "inventory-counts__header";

    const title = document.createElement("span");
    title.className = "inventory-counts__title";
    title.textContent = "Inventory";

    const total = document.createElement("span");
    total.className = "inventory-counts__total";
    total.textContent = `${this.data?.total_facts || 0} markers`;

    const expandBtn = document.createElement("button");
    expandBtn.className = "inventory-counts__expand-btn";
    expandBtn.setAttribute("aria-expanded", String(this.isExpanded));
    expandBtn.innerHTML = this.isExpanded ? "\u25B2" : "\u25BC";
    expandBtn.title = this.isExpanded ? "Collapse details" : "Expand details";
    expandBtn.addEventListener("click", () => {
      this.isExpanded = !this.isExpanded;
      this.render();
    });

    header.appendChild(title);
    header.appendChild(total);
    header.appendChild(expandBtn);

    return header;
  }

  /**
   * Create the horizontal marker bar
   */
  private createMarkerBar(): HTMLElement {
    const bar = document.createElement("div");
    bar.className = "inventory-counts__bar";

    for (const markerType of MARKER_ORDER) {
      const config = MARKER_CONFIG[markerType];
      const typeData = this.data?.by_type.find(t => t.marker_type === markerType);
      const count = typeData?.count || 0;

      // Get delta for selected step
      let delta = 0;
      if (this.selectedStep && this.data) {
        const [flowKey, stepId] = this.selectedStep.split(":");
        const deltas = this.getDeltasForStep(flowKey, stepId);
        if (deltas) {
          delta = deltas[markerType] || 0;
        }
      }

      const item = document.createElement("div");
      item.className = "inventory-counts__item";
      item.setAttribute("data-uiid", `flow_studio.inventory.type.${markerType.toLowerCase()}`);
      item.setAttribute("data-marker-type", markerType);
      item.style.setProperty("--marker-color", config.color);

      // Icon
      const icon = document.createElement("span");
      icon.className = "inventory-counts__icon";
      icon.textContent = config.icon;
      icon.style.backgroundColor = config.color;

      // Count
      const countSpan = document.createElement("span");
      countSpan.className = "inventory-counts__count";
      countSpan.textContent = String(count);

      // Delta indicator
      if (delta !== 0) {
        const deltaSpan = document.createElement("span");
        deltaSpan.className = `inventory-counts__delta inventory-counts__delta--${delta > 0 ? "positive" : "negative"}`;
        deltaSpan.textContent = delta > 0 ? `+${delta}` : String(delta);
        item.appendChild(deltaSpan);
      }

      // Tooltip
      item.title = `${config.label}: ${count}`;

      // Click handler
      if (this.onTypeClick) {
        item.style.cursor = "pointer";
        item.addEventListener("click", () => {
          this.onTypeClick?.(markerType);
        });
      }

      item.appendChild(icon);
      item.appendChild(countSpan);
      bar.appendChild(item);
    }

    return bar;
  }

  /**
   * Create expanded details view
   */
  private createExpandedDetails(): HTMLElement {
    const details = document.createElement("div");
    details.className = "inventory-counts__details";

    // By flow section
    if (this.data && this.data.by_flow.length > 0) {
      const flowSection = document.createElement("div");
      flowSection.className = "inventory-counts__section";

      const flowHeader = document.createElement("div");
      flowHeader.className = "inventory-counts__section-header";
      flowHeader.textContent = "By Flow";
      flowSection.appendChild(flowHeader);

      const flowList = document.createElement("div");
      flowList.className = "inventory-counts__flow-list";

      for (const flow of this.data.by_flow) {
        const flowItem = document.createElement("div");
        flowItem.className = "inventory-counts__flow-item";
        flowItem.setAttribute("data-uiid", `flow_studio.inventory.flow.${flow.flow_key}`);

        const flowName = document.createElement("span");
        flowName.className = "inventory-counts__flow-name";
        flowName.textContent = flow.flow_key;

        const flowCounts = document.createElement("span");
        flowCounts.className = "inventory-counts__flow-counts";

        // Show mini bar for each flow
        for (const markerType of MARKER_ORDER) {
          const count = flow.counts[markerType] || 0;
          if (count > 0) {
            const miniItem = document.createElement("span");
            miniItem.className = "inventory-counts__mini-count";
            miniItem.style.color = MARKER_CONFIG[markerType].color;
            miniItem.textContent = `${MARKER_CONFIG[markerType].icon}${count}`;
            flowCounts.appendChild(miniItem);
          }
        }

        const flowTotal = document.createElement("span");
        flowTotal.className = "inventory-counts__flow-total";
        flowTotal.textContent = `(${flow.total})`;

        // Click handler
        if (this.onFlowClick) {
          flowItem.style.cursor = "pointer";
          flowItem.addEventListener("click", () => {
            this.onFlowClick?.(flow.flow_key);
          });
        }

        flowItem.appendChild(flowName);
        flowItem.appendChild(flowCounts);
        flowItem.appendChild(flowTotal);
        flowList.appendChild(flowItem);
      }

      flowSection.appendChild(flowList);
      details.appendChild(flowSection);
    }

    // Deltas section
    if (this.data && this.data.deltas.length > 0) {
      const deltaSection = document.createElement("div");
      deltaSection.className = "inventory-counts__section";

      const deltaHeader = document.createElement("div");
      deltaHeader.className = "inventory-counts__section-header";
      deltaHeader.textContent = "Changes Between Steps";
      deltaSection.appendChild(deltaHeader);

      const deltaList = document.createElement("div");
      deltaList.className = "inventory-counts__delta-list";

      for (const delta of this.data.deltas) {
        const deltaItem = document.createElement("div");
        deltaItem.className = "inventory-counts__delta-item";

        const steps = document.createElement("span");
        steps.className = "inventory-counts__delta-steps";
        steps.textContent = `${delta.from_step} \u2192 ${delta.to_step}`;

        const changes = document.createElement("span");
        changes.className = "inventory-counts__delta-changes";

        for (const [markerType, change] of Object.entries(delta.deltas)) {
          if (change !== 0) {
            const changeSpan = document.createElement("span");
            changeSpan.className = `inventory-counts__delta-change inventory-counts__delta-change--${change > 0 ? "positive" : "negative"}`;
            changeSpan.style.color = MARKER_CONFIG[markerType]?.color || "#666";
            changeSpan.textContent = `${MARKER_CONFIG[markerType]?.icon || markerType}${change > 0 ? "+" : ""}${change}`;
            changes.appendChild(changeSpan);
          }
        }

        // Click handler
        if (this.onStepClick) {
          deltaItem.style.cursor = "pointer";
          deltaItem.addEventListener("click", () => {
            const [flowKey, stepId] = delta.to_step.split(":");
            this.onStepClick?.(flowKey, stepId);
          });
        }

        deltaItem.appendChild(steps);
        deltaItem.appendChild(changes);
        deltaList.appendChild(deltaItem);
      }

      deltaSection.appendChild(deltaList);
      details.appendChild(deltaSection);
    }

    return details;
  }

  // ==========================================================================
  // Public API
  // ==========================================================================

  /**
   * Set the selected step for delta highlighting
   */
  setSelectedStep(flowKey: string | null, stepId: string | null): void {
    this.selectedStep = flowKey && stepId ? `${flowKey}:${stepId}` : null;
    this.render();
  }

  /**
   * Toggle expanded state
   */
  toggleExpanded(): void {
    this.isExpanded = !this.isExpanded;
    this.render();
  }

  /**
   * Get current data
   */
  getData(): FactsSummaryResponse | null {
    return this.data;
  }

  /**
   * Check if component has data
   */
  hasData(): boolean {
    return this.data !== null && this.data.total_facts > 0;
  }

  /**
   * Clear data and reset state
   */
  clear(): void {
    this.data = null;
    this.isExpanded = false;
    this.selectedStep = null;
    this.errorMessage = null;
    this.render();
  }

  /**
   * Destroy the component
   */
  destroy(): void {
    this.container.innerHTML = "";
    this.data = null;
  }
}

// ============================================================================
// Factory Function
// ============================================================================

/**
 * Create and initialize an inventory counts component
 */
export async function createInventoryCounts(
  container: HTMLElement,
  runId: string,
  options?: Omit<InventoryCountsOptions, "container">
): Promise<InventoryCounts> {
  const component = new InventoryCounts({
    container,
    ...options,
  });
  await component.load(runId);
  return component;
}

// ============================================================================
// CSS Class Names Reference
// ============================================================================

/**
 * CSS class names used by this component:
 *
 * .inventory-counts - Main container
 * .inventory-counts__loading - Loading state container
 * .inventory-counts__spinner - Loading spinner
 * .inventory-counts__error - Error state container
 * .inventory-counts__error-icon - Error icon
 * .inventory-counts__empty - Empty state container
 * .inventory-counts__empty-text - Empty state text
 * .inventory-counts__header - Header section
 * .inventory-counts__title - Title text
 * .inventory-counts__total - Total count badge
 * .inventory-counts__expand-btn - Expand/collapse button
 * .inventory-counts__bar - Horizontal marker bar
 * .inventory-counts__item - Individual marker type item
 * .inventory-counts__icon - Marker type icon
 * .inventory-counts__count - Marker count number
 * .inventory-counts__delta - Delta indicator
 * .inventory-counts__delta--positive - Positive delta (+)
 * .inventory-counts__delta--negative - Negative delta (-)
 * .inventory-counts__details - Expanded details container
 * .inventory-counts__section - Details section
 * .inventory-counts__section-header - Section header
 * .inventory-counts__flow-list - Flow list container
 * .inventory-counts__flow-item - Individual flow item
 * .inventory-counts__flow-name - Flow name
 * .inventory-counts__flow-counts - Mini counts bar
 * .inventory-counts__flow-total - Flow total
 * .inventory-counts__mini-count - Mini count item
 * .inventory-counts__delta-list - Delta list container
 * .inventory-counts__delta-item - Individual delta item
 * .inventory-counts__delta-steps - Step transition text
 * .inventory-counts__delta-changes - Delta changes container
 * .inventory-counts__delta-change - Individual delta change
 * .inventory-counts__delta-change--positive - Positive change
 * .inventory-counts__delta-change--negative - Negative change
 */
