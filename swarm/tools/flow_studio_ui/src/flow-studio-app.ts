// swarm/tools/flow_studio_ui/src/flow-studio-app.ts
// Bootstrap shell for Flow Studio
//
// This file is the main entry point that:
// - Initializes and configures all modules
// - Handles mode/view toggling
// - Manages URL deep linking
// - Wires up event listeners

// ============================================================================
// Imports
// ============================================================================

// Core state and utilities
import { state } from "./state.js";
import { Api } from "./api.js";
import type {
  FlowKey,
  NodeData,
  FlowDetail,
  FlowGraph,
  UIMode,
  ViewMode,
  FlowStudioSDK,
  ContextBudgetConfig,
  ContextBudgetOverride
} from "./domain.js";
import { qsByUiid, qsAllByUiidPrefix } from "./domain.js";

// Selection management
import {
  configure as configureSelection,
  selectNode,
  selectStep,
  selectAgent,
  clearSelection,
  getSelectionForUrl,
  parseStepParam
} from "./selection.js";

// Details panel
import {
  showStepDetails as showStepDetailsBase,
  showAgentDetails as showAgentDetailsBase,
  showArtifactDetails,
  showEmptyState,
  renderRunTimeline,
  renderFlowTiming
} from "./details.js";

// Graph
import { renderGraphCore } from "./graph.js";

// Runs/flows orchestration
import {
  configure as configureRunsFlows,
  loadRuns,
  loadRunStatus,
  loadFlows,
  setActiveFlow,
  setCompareRun,
  updateCompareSelector,
  refreshCurrentFlow,
  clearWisdomCache
} from "./runs_flows.js";

// Search
import {
  configure as configureSearch,
  initSearchHandlers,
} from "./search.js";

// Keyboard shortcuts
import {
  configure as configureShortcuts,
  initKeyboardShortcuts,
  initShortcutsModal,
  toggleShortcutsModal
} from "./shortcuts.js";

// Governance UI
import {
  loadGovernanceStatus,
  updateFlowListGovernance,
  toggleGovernanceOverlay,
  getNodeGovernanceInfo,
  renderGovernanceSection,
  showGovernanceDetails
} from "./governance_ui.js";

// Tours
import {
  configure as configureTours,
  loadTours,
  initTourHandlers,
  startTour
} from "./tours.js";

// Selftest modal
import {
  initSelftestModal,
  toggleSelftestModal,
  renderSelftestTab
} from "./selftest_ui.js";

// Teaching mode
import {
  initTeachingMode,
  initToggleButtonHandler as initTeachingModeToggle,
  getTeachingMode,
  setTeachingMode
} from "./teaching_mode.js";

// Context budget settings
import {
  initContextBudgetSettings,
  initContextBudgetModalHandlers,
  getContextBudgets,
  setContextBudgets,
  openContextBudgetModal
} from "./context_budget_settings.js";

// Run history panel
import {
  configure as configureRunHistory,
  initRunHistory,
  setSelectedRunId as setRunHistorySelectedRunId
} from "./run_history.js";

// Run detail modal
import {
  configure as configureRunDetailModal,
  showRunDetailModal
} from "./run_detail_modal.js";

// Run control panel
import {
  configure as configureRunControl,
  initRunControl,
  setActiveRun as setRunControlActiveRun,
  clearActiveRun as clearRunControlActiveRun,
  type SSEEvent
} from "./run_control.js";

// Graph semantic companion
import {
  renderFlowOutline,
  getCurrentGraphState
} from "./graph_outline.js";

// Layout spec for SDK
import {
  screens as layoutScreens,
  getScreenById as getLayoutScreenByIdImpl,
  getAllKnownUIIDs as getAllKnownUIIDsImpl
} from "./layout_spec.js";
import type { ScreenId } from "./domain.js";

// Boundary Review - flow completion summaries
import {
  BoundaryReview,
  createBoundaryReview,
  extractBoundaryReviewData,
} from "./components/BoundaryReview.js";
import type {
  BoundaryReviewData,
  BoundaryReviewDecision,
  FlowCompletionStatus,
  RoutingDecision,
} from "./components/BoundaryReview.js";

// Inventory Counts - marker statistics
import { InventoryCounts } from "./components/InventoryCounts.js";

// ============================================================================
// Details Wrappers
// ============================================================================

// Wrapper functions for details module - provide callbacks from this module
async function showStepDetails(data: NodeData): Promise<void> {
  return showStepDetailsBase(data, {
    renderSelftestTab,
    getNodeGovernanceInfo,
    renderGovernanceSection,
    selectAgent
  });
}

async function showAgentDetails(data: NodeData): Promise<void> {
  return showAgentDetailsBase(data, {
    setActiveFlow,
    showStepDetails,
    getNodeGovernanceInfo,
    renderGovernanceSection
  });
}

// ============================================================================
// Profile Status
// ============================================================================

/**
 * Load and display the current profile status.
 */
async function loadProfileStatus(): Promise<void> {
  const profileText = document.getElementById("profile-text");
  const profileBadge = document.getElementById("profile-badge");

  if (!profileText || !profileBadge) return;

  // Helper to reset modifier classes
  const resetModifiers = () => {
    profileBadge.classList.remove("fs-profile-badge--none", "fs-profile-badge--error");
  };

  try {
    const data = await Api.getCurrentProfile();

    if (data.profile) {
      profileText.textContent = `Profile: ${data.profile.label || data.profile.id}`;
      profileBadge.title = `Profile: ${data.profile.id}\nLoaded: ${data.profile.loaded_at || "unknown"}\nBranch: ${data.profile.source_branch || "unknown"}`;
      resetModifiers(); // Default state (light blue via base class)
    } else {
      profileText.textContent = "Profile: (none)";
      profileBadge.title = data.message || "No profile loaded";
      resetModifiers();
      profileBadge.classList.add("fs-profile-badge--none");
    }
  } catch (err) {
    console.error("Failed to load profile status", err);
    profileText.textContent = "Profile: (unavailable)";
    profileBadge.title = "Profile status unavailable";
    resetModifiers();
    profileBadge.classList.add("fs-profile-badge--error");
  }
}

// ============================================================================
// Backend Loading
// ============================================================================

/** Track the currently selected backend ID */
let selectedBackendId: string = "claude-harness";

/** Global inventory counts component instance */
let inventoryCountsComponent: InventoryCounts | null = null;

/** Debounce timer for inventory counts updates */
let inventoryCountsDebounceTimer: ReturnType<typeof setTimeout> | null = null;

/** Debounce delay for inventory counts updates (ms) */
const INVENTORY_COUNTS_DEBOUNCE_MS = 250;

// ============================================================================
// Inventory Counts
// ============================================================================

/**
 * Initialize and load the inventory counts component.
 */
function initInventoryCounts(): void {
  const container = document.getElementById("inventory-counts-container");
  if (!container) return;

  // Create component instance if not already created
  if (!inventoryCountsComponent) {
    inventoryCountsComponent = new InventoryCounts({
      container,
      onTypeClick: (markerType: string) => {
        // Could navigate to filtered facts view in future
        console.log("Clicked marker type:", markerType);
      },
      onFlowClick: async (flowKey: string) => {
        // Navigate to the flow
        await setActiveFlow(flowKey as FlowKey, true);
      },
      onStepClick: async (flowKey: string, stepId: string) => {
        // Navigate to the step
        await setActiveFlow(flowKey as FlowKey, true);
        setTimeout(() => {
          selectStep(flowKey as FlowKey, stepId, { fitGraph: true });
        }, 300);
      },
    });
  }

  // Load data if we have a run selected
  if (state.currentRunId) {
    inventoryCountsComponent.load(state.currentRunId).catch((err) => {
      console.warn("Failed to load inventory counts:", err);
    });
  } else {
    inventoryCountsComponent.clear();
  }
}

/**
 * Update inventory counts when run changes.
 * Debounced to prevent excessive API calls under bursty SSE events.
 */
function updateInventoryCounts(runId: string | null): void {
  // Cancel any pending debounced update
  if (inventoryCountsDebounceTimer !== null) {
    clearTimeout(inventoryCountsDebounceTimer);
    inventoryCountsDebounceTimer = null;
  }

  inventoryCountsDebounceTimer = setTimeout(() => {
    inventoryCountsDebounceTimer = null;

    if (!inventoryCountsComponent) {
      initInventoryCounts();
    }

    if (runId && inventoryCountsComponent) {
      inventoryCountsComponent.load(runId).catch((err) => {
        console.warn("Failed to load inventory counts:", err);
      });
    } else if (inventoryCountsComponent) {
      inventoryCountsComponent.clear();
    }
  }, INVENTORY_COUNTS_DEBOUNCE_MS);
}

/**
 * Update inventory counts selected step.
 */
function updateInventoryCountsSelectedStep(flowKey: FlowKey | null, stepId: string | null): void {
  if (inventoryCountsComponent) {
    inventoryCountsComponent.setSelectedStep(flowKey, stepId);
  }
}

/**
 * Load and display available backends in the selector.
 */
async function loadBackends(): Promise<void> {
  const selector = document.getElementById("backend-selector") as HTMLSelectElement | null;
  if (!selector) return;

  try {
    const data = await Api.getBackends();
    const backends = data.backends || [];

    selector.innerHTML = "";

    if (!backends.length) {
      selector.innerHTML = '<option value="claude-harness">Claude CLI</option>';
      return;
    }

    for (const backend of backends) {
      const opt = document.createElement("option");
      opt.value = backend.id;
      opt.textContent = backend.label;
      // Add tooltip with capability info
      const caps: string[] = [];
      if (backend.supports_streaming) caps.push("streaming");
      if (backend.supports_events) caps.push("events");
      if (backend.supports_cancel) caps.push("cancel");
      if (backend.supports_replay) caps.push("replay");
      opt.title = `Supports: ${caps.join(", ") || "basic execution"}`;
      selector.appendChild(opt);
    }

    // Restore previous selection if it still exists
    const prevSelected = selector.querySelector(`option[value="${selectedBackendId}"]`);
    if (prevSelected) {
      selector.value = selectedBackendId;
    } else if (backends.length > 0) {
      selectedBackendId = backends[0].id;
    }
  } catch (err) {
    console.error("Failed to load backends", err);
    selector.innerHTML = '<option value="claude-harness">Claude CLI</option>';
  }
}

// ============================================================================
// Mode and View Management
// ============================================================================

/**
 * Set the application mode (author vs operator).
 */
function setMode(mode: UIMode): void {
  state.currentMode = mode;
  document.body.classList.remove("mode-author", "mode-operator");
  document.body.classList.add("mode-" + mode);

  // Update toggle buttons
  const authorBtn = document.getElementById("mode-author");
  const operatorBtn = document.getElementById("mode-operator");
  if (authorBtn) authorBtn.classList.toggle("active", mode === "author");
  if (operatorBtn) operatorBtn.classList.toggle("active", mode === "operator");

  // Update URL
  updateURL();

  // Refresh timeline display when switching to operator mode
  if (mode === "operator" && state.currentRunId && state.currentFlowKey) {
    const timelineContainer = document.getElementById("flow-overview-timeline");
    if (timelineContainer) {
      renderRunTimeline(timelineContainer);
      renderFlowTiming(timelineContainer, state.currentFlowKey);
    }
  }
}

/**
 * Set the view mode (agents vs artifacts).
 */
async function setViewMode(viewMode: ViewMode): Promise<void> {
  state.currentViewMode = viewMode;

  // Update toggle buttons
  const agentsBtn = document.getElementById("view-agents");
  const artifactsBtn = document.getElementById("view-artifacts");
  if (agentsBtn) agentsBtn.classList.toggle("active", viewMode === "agents");
  if (artifactsBtn) artifactsBtn.classList.toggle("active", viewMode === "artifacts");

  // Update URL
  updateURL();

  // Reload graph with new view mode if we have a flow selected
  if (state.currentFlowKey) {
    await refreshCurrentFlow();
  }
}

// ============================================================================
// URL Management (Deep Linking)
// ============================================================================

interface URLParams {
  mode: string | null;
  run: string | null;
  flow: string | null;
  step: string | null;
  agent: string | null;
  view: string | null;
  tour: string | null;
  tab: string | null;
}

/**
 * Update URL to reflect current state (for shareable deep links).
 */
function updateURL(): void {
  const url = new URL(window.location.href);

  // Set mode
  if (state.currentMode && state.currentMode !== "author") {
    url.searchParams.set("mode", state.currentMode);
  } else {
    url.searchParams.delete("mode");
  }

  // Set run
  if (state.currentRunId) {
    url.searchParams.set("run", state.currentRunId);
  } else {
    url.searchParams.delete("run");
  }

  // Set flow
  if (state.currentFlowKey) {
    url.searchParams.set("flow", state.currentFlowKey);
  } else {
    url.searchParams.delete("flow");
  }

  // Set view mode (only if not default)
  if (state.currentViewMode && state.currentViewMode !== "agents") {
    url.searchParams.set("view", state.currentViewMode);
  } else {
    url.searchParams.delete("view");
  }

  // Set selection (step or agent)
  const selection = getSelectionForUrl();
  if (selection.step) {
    url.searchParams.set("step", selection.step);
    url.searchParams.delete("agent");
  } else if (selection.agent) {
    url.searchParams.set("agent", selection.agent);
    url.searchParams.delete("step");
  } else {
    url.searchParams.delete("step");
    url.searchParams.delete("agent");
  }

  window.history.pushState({ flowStudio: true }, "", url.toString());
}

/**
 * Get URL params for deep linking.
 */
function getURLParams(): URLParams {
  const url = new URL(window.location.href);
  return {
    mode: url.searchParams.get("mode"),
    run: url.searchParams.get("run"),
    flow: url.searchParams.get("flow"),
    step: url.searchParams.get("step"),
    agent: url.searchParams.get("agent"),
    view: url.searchParams.get("view"),
    tour: url.searchParams.get("tour"),
    tab: url.searchParams.get("tab")
  };
}

// Cached URL params from initial load
let initialURLParams: URLParams | null = null;

/**
 * Initialize mode from URL or default.
 */
function initMode(): void {
  initialURLParams = getURLParams();
  const mode = initialURLParams.mode;
  if (mode === "operator") {
    setMode("operator");
  } else {
    setMode("author");
  }

  // Initialize view mode from URL
  const view = initialURLParams.view;
  if (view === "artifacts") {
    state.currentViewMode = "artifacts";
    const agentsBtn = document.getElementById("view-agents");
    const artifactsBtn = document.getElementById("view-artifacts");
    if (agentsBtn) agentsBtn.classList.remove("active");
    if (artifactsBtn) artifactsBtn.classList.add("active");
  }
}

/**
 * Apply deep link params after data is loaded.
 */
async function applyDeepLinkParams(): Promise<void> {
  if (!initialURLParams) return;

  const { run, flow, step, agent, tour, tab } = initialURLParams;

  // Apply run selection if specified
  if (run) {
    const runSelector = document.getElementById("run-selector") as HTMLSelectElement | null;
    if (runSelector) {
      const optionExists = Array.from(runSelector.options).some(opt => opt.value === run);
      if (optionExists) {
        state.currentRunId = run;
        runSelector.value = run;
        updateCompareSelector();
        await loadRunStatus();
        // Sync run history selection (handles race where initRunHistory finishes after deep link)
        setRunHistorySelectedRunId(run);
      }
    }
  }

  // Apply flow selection if specified
  if (flow) {
    const flowExists = document.querySelector(`.flow-item[data-key="${flow}"]`);
    if (flowExists) {
      await setActiveFlow(flow as FlowKey, true);
    }
  }

  // Apply step selection if specified (uses unified selection)
  if (step && flow) {
    setTimeout(async () => {
      await selectStep(flow as FlowKey, step, { skipUrlUpdate: true, fitGraph: true });
    }, 300);
  }
  // Apply agent selection if specified (uses unified selection)
  else if (agent && flow) {
    setTimeout(async () => {
      await selectAgent(agent, flow as FlowKey, { skipUrlUpdate: true, fitGraph: true });
    }, 300);
  }

  // Apply tab selection if specified
  if (tab) {
    setTimeout(() => {
      const tabEl = document.querySelector(`.tab[data-tab="${tab}"]`) as HTMLElement | null;
      if (tabEl) {
        tabEl.click();
      }
    }, 400);
  }

  // Start tour if specified
  if (tour) {
    setTimeout(() => {
      startTour(tour);
    }, 500);
  }
}

/**
 * Handle browser back/forward navigation.
 */
function handlePopState(event: PopStateEvent): void {
  // Only handle our own history entries
  if (!event.state?.flowStudio) {
    return;
  }

  const params = getURLParams();

  // Apply mode
  if (params.mode === "operator") {
    setMode("operator");
  } else {
    setMode("author");
  }

  // Apply view mode
  if (params.view === "artifacts") {
    setViewMode("artifacts");
  } else if (state.currentViewMode !== "agents") {
    setViewMode("agents");
  }

  // Apply flow and selection
  if (params.flow) {
    setActiveFlow(params.flow as FlowKey, true).then(() => {
      if (params.step) {
        selectStep(params.flow as FlowKey, params.step, { skipUrlUpdate: true, fitGraph: true });
      } else if (params.agent) {
        selectAgent(params.agent, params.flow as FlowKey, { skipUrlUpdate: true, fitGraph: true });
      }
    });
  }
}

// ============================================================================
// Graph and Details Rendering
// ============================================================================

/**
 * Handle node click from graph.
 * Uses the unified selection module for consistent behavior.
 */
function handleNodeClick(data: NodeData): void {
  // Build node ID from data
  let nodeId: string;
  if (data.type === "step") {
    nodeId = data.id || `step:${data.flow}:${data.step_id}`;
  } else if (data.type === "agent") {
    nodeId = data.id || `agent:${data.agent_key}`;
  } else if (data.type === "artifact") {
    nodeId = data.id || `artifact:${data.flow}:${data.label}`;
  } else {
    return;
  }

  // Use unified selection - graph click doesn't need flow switch or fit
  selectNode(nodeId, {
    nodeData: data,
    fitGraph: false,
    skipUrlUpdate: false
  });
}

/** Flow detail with optional flow property */
interface FlowDetailExtended {
  flow?: {
    key?: string;
    title?: string;
    description?: string;
  };
  steps?: unknown[];
}

/**
 * Show flow details in the details panel.
 */
function showFlowDetails(detail: FlowDetail | FlowDetailExtended): void {
  const flow = (detail as FlowDetailExtended).flow || { key: (detail as FlowDetail).key, title: (detail as FlowDetail).title, description: (detail as FlowDetail).description };
  const steps = (detail as FlowDetail).steps || (detail as FlowDetailExtended).steps || [];

  const detailsEl = document.getElementById("details");
  if (!detailsEl) return;

  detailsEl.innerHTML = "";

  const h2 = document.createElement("h2");
  h2.textContent = flow.title || flow.key || "Flow";

  const desc = document.createElement("div");
  desc.className = "muted";
  desc.textContent = flow.description || "";

  const meta = document.createElement("div");
  meta.innerHTML = `
    <div class="kv-label">Flow key</div>
    <div class="mono">${flow.key || ""}</div>
    <div class="kv-label">Steps</div>
    <div>${steps.length} step(s)</div>
  `;

  const hint = document.createElement("div");
  hint.className = "welcome-panel author-only";
  hint.innerHTML = `
    <div class="welcome-section" style="margin-bottom: 12px;">
      <div style="font-size: 11px; color: #6b7280; margin-bottom: 8px;">
        Click a node for details. Press <kbd class="shortcut-key">?</kbd> for shortcuts.
      </div>
      <div style="font-size: 11px; color: #9ca3af;">
        Artifacts: <code class="mono" style="font-size: 10px;">swarm/runs/&lt;run&gt;/${flow.key || "&lt;flow&gt;"}/</code>
      </div>
    </div>
    <div class="welcome-section">
      <div style="font-size: 11px; color: #6b7280; margin-bottom: 4px;">Edit flow:</div>
      <pre class="mono" style="font-size: 10px; margin: 0;">$EDITOR swarm/config/flows/${flow.key || "&lt;key&gt;"}.yaml</pre>
    </div>
  `;

  const operatorHint = document.createElement("div");
  operatorHint.className = "operator-only";
  operatorHint.id = "flow-overview-timeline";

  if (state.currentMode === "operator" && state.currentRunId) {
    operatorHint.innerHTML = '<div class="muted">Loading timeline...</div>';
  } else {
    operatorHint.innerHTML = `
      <div class="muted" style="margin-top: 8px; font-size: 11px;">
        Select a step for status and artifacts.
      </div>
    `;
  }

  detailsEl.appendChild(h2);
  detailsEl.appendChild(desc);
  detailsEl.appendChild(meta);
  detailsEl.appendChild(hint);
  detailsEl.appendChild(operatorHint);

  // Load timeline in operator mode after DOM is ready
  if (state.currentMode === "operator" && state.currentRunId && flow.key) {
    renderRunTimeline(operatorHint);
    renderFlowTiming(operatorHint, flow.key as FlowKey);
  }
}

/**
 * Render graph and show flow details.
 */
function renderGraph(graph: FlowGraph, detail: FlowDetail): void {
  renderGraphCore(graph, { onNodeClick: handleNodeClick });
  showFlowDetails(detail);

  // Update semantic outline after graph render
  renderFlowOutline();
}

// ============================================================================
// Config Reload
// ============================================================================

/**
 * Reload configuration from server.
 */
async function reloadConfig(): Promise<void> {
  const btn = document.getElementById("reload-btn") as HTMLButtonElement | null;
  if (!btn) return;

  btn.disabled = true;
  btn.textContent = "Reloading\u2026";

  try {
    await Api.reloadConfig();
    await loadFlows();
    btn.textContent = "Reload";
  } catch (err) {
    console.error("Failed to reload config", err);
    const listEl = document.getElementById("flow-list");
    if (listEl) listEl.textContent = "Reload failed: " + (err as Error).message;
    btn.textContent = "Reload";
  } finally {
    btn.disabled = false;
  }
}

// ============================================================================
// UI Ready Handshake
// ============================================================================

/**
 * Mark the UI as ready for interaction.
 */
function markUiReady(): void {
  document.documentElement.dataset.uiReady = "ready";
}

/**
 * Mark the UI as loading (initialization in progress).
 */
function markUiLoading(): void {
  document.documentElement.dataset.uiReady = "loading";
}

/**
 * Mark the UI as failed (initialization error).
 */
function markUiError(): void {
  document.documentElement.dataset.uiReady = "error";
}

// ============================================================================
// Initialization
// ============================================================================

window.addEventListener("load", async () => {
  // Mark UI as loading during initialization
  markUiLoading();

  // Performance measurement (opt-in via ?debugPerf=1)
  const debugPerf = new URL(window.location.href).searchParams.has("debugPerf");
  const t0 = debugPerf ? performance.now() : 0;

  try {
    // Initialize mode from URL
    initMode();

    // Configure runs/flows module with callbacks
    configureRunsFlows({
      onFlowDetails: showFlowDetails,
      onNodeClick: handleNodeClick,
      onURLUpdate: updateURL,
      updateFlowListGovernance: updateFlowListGovernance
    });

    // Configure search module
    configureSearch({
      setActiveFlow: setActiveFlow
    });

    // Configure shortcuts module
    configureShortcuts({
      setActiveFlow: setActiveFlow,
      showStepDetails: showStepDetails,
      toggleSelftestModal: toggleSelftestModal
    });

    // Configure tours module
    configureTours({
      setActiveFlow: setActiveFlow
    });

    // Configure selection module (unified selection for all surfaces)
    configureSelection({
      setActiveFlow: setActiveFlow,
      showStepDetails: showStepDetails,
      showAgentDetails: showAgentDetails,
      showArtifactDetails: showArtifactDetails,
      showEmptyState: showEmptyState,
      updateURL: updateURL,
      onStepSelected: updateInventoryCountsSelectedStep
    });

    // Initialize search handlers
    initSearchHandlers();

    // Handle browser back/forward navigation
    window.addEventListener("popstate", handlePopState);

    // Initialize keyboard shortcuts
    initKeyboardShortcuts();
    initShortcutsModal();
    initSelftestModal();

    // Initialize teaching mode
    initTeachingMode();
    initTeachingModeToggle();

    // Initialize context budget settings
    initContextBudgetSettings();
    initContextBudgetModalHandlers();

    // Mode toggle handlers
    const authorBtn = document.getElementById("mode-author");
    const operatorBtn = document.getElementById("mode-operator");
    if (authorBtn) authorBtn.addEventListener("click", () => setMode("author"));
    if (operatorBtn) operatorBtn.addEventListener("click", () => setMode("operator"));

    // View toggle handlers
    const viewAgentsBtn = document.getElementById("view-agents");
    const viewArtifactsBtn = document.getElementById("view-artifacts");
    if (viewAgentsBtn) viewAgentsBtn.addEventListener("click", () => setViewMode("agents"));
    if (viewArtifactsBtn) viewArtifactsBtn.addEventListener("click", () => setViewMode("artifacts"));

    // Reload button handler
    const btn = document.getElementById("reload-btn");
    if (btn) {
      btn.addEventListener("click", reloadConfig);
    }

    // Help button handler
    const helpBtn = document.getElementById("help-btn");
    if (helpBtn) {
      helpBtn.addEventListener("click", () => toggleShortcutsModal(true));
    }

    // Governance badge click handler
    const govBadge = document.getElementById("governance-badge");
    if (govBadge) {
      govBadge.addEventListener("click", showGovernanceDetails);
    }

    // Governance overlay toggle handler
    const govOverlayCheckbox = document.getElementById("governance-overlay-checkbox") as HTMLInputElement | null;
    if (govOverlayCheckbox) {
      govOverlayCheckbox.addEventListener("change", (e: Event) => {
        toggleGovernanceOverlay((e.target as HTMLInputElement).checked);
      });
    }

    // Run selector change handler
    const runSelector = document.getElementById("run-selector") as HTMLSelectElement | null;
    if (runSelector) {
      runSelector.addEventListener("change", async (e: Event) => {
        const runId = (e.target as HTMLSelectElement).value;
        state.currentRunId = runId;
        clearWisdomCache(); // Clear wisdom cache when run changes
        updateCompareSelector();
        await loadRunStatus();
        // Update inventory counts for new run
        updateInventoryCounts(runId || null);
        // Sync run history selection
        setRunHistorySelectedRunId(runId);
        // Sync run control panel to monitor this run
        if (runId) {
          void setRunControlActiveRun(runId);
        } else {
          clearRunControlActiveRun();
        }
        // Refresh artifact view if in artifact mode
        if (state.currentViewMode === "artifacts" && state.currentFlowKey) {
          setActiveFlow(state.currentFlowKey, true);
        }
      });
    }

    // Compare selector change handler (operator mode)
    const compareSelector = document.getElementById("compare-selector") as HTMLSelectElement | null;
    if (compareSelector) {
      compareSelector.addEventListener("change", async (e: Event) => {
        await setCompareRun((e.target as HTMLSelectElement).value);
      });
    }

    // Backend selector change handler
    const backendSelector = document.getElementById("backend-selector") as HTMLSelectElement | null;
    if (backendSelector) {
      backendSelector.addEventListener("change", (e: Event) => {
        selectedBackendId = (e.target as HTMLSelectElement).value;
      });
    }

    // ========================================================================
    // CRITICAL PATH: Only await what's needed for initial render
    // Non-critical loads run in background to reduce time-to-interactive
    // ========================================================================

    // Phase 1: Start background loads for non-critical UI elements
    // These populate header badges and selectors but don't block core UI
    // Error handling is centralized in the .then() below
    const backgroundLoadNames = ["profile status", "backends", "governance status", "tours"] as const;
    const backgroundLoads = Promise.allSettled([
      loadProfileStatus(),
      loadBackends(),
      loadGovernanceStatus(),
      loadTours()
    ]);

    // Phase 2: Critical path - runs and flows are needed for main UI
    // Load runs first (populates run selector), then flows (renders graph)
    try {
      await loadRuns();
    } catch (err) {
      console.error("Failed to load runs", err);
    }

    try {
      await loadFlows();
    } catch (err) {
      const listEl = document.getElementById("flow-list");
      if (listEl) listEl.textContent = "Failed to load flows: " + (err as Error).message;
    }

    // Initialize tour system (sync handlers only)
    initTourHandlers();

    // Log any background load failures (non-blocking)
    backgroundLoads.then(results => {
      // Guard against ordering drift if loads/names get out of sync
      if (results.length !== backgroundLoadNames.length) {
        console.warn("Background load names list out of sync with loads", {
          results: results.length,
          names: backgroundLoadNames.length
        });
      }
      results.forEach((result, idx) => {
        if (result.status === "rejected") {
          console.error(`Failed to load ${backgroundLoadNames[idx]}:`, result.reason);
        }
      });
    });

    // Configure and initialize run history panel
    configureRunHistory({
      onRunSelect: async (runId: string) => {
        // Update the main run selector to match
        const runSelector = document.getElementById("run-selector") as HTMLSelectElement | null;
        if (runSelector) {
          runSelector.value = runId;
        }
        state.currentRunId = runId;
        updateCompareSelector();
        await loadRunStatus();
        // Refresh artifact view if in artifact mode
        if (state.currentViewMode === "artifacts" && state.currentFlowKey) {
          await setActiveFlow(state.currentFlowKey, true);
        }
      },
      onRunDetailOpen: async (runId: string) => {
        await showRunDetailModal(runId);
      }
    });

    // Configure run detail modal
    configureRunDetailModal({
      onClose: () => {
        // Optional: any cleanup after modal closes
      },
      onRerun: async (_runId: string) => {
        // Re-run functionality - for now just log
        // Future: call Api.startRun() with appropriate params
      }
    });

    // Initialize boundary review component for flow completion summaries
    const boundaryReview = createBoundaryReview({
      onApprove: (flowKey) => {
        console.log(`[BoundaryReview] Approved flow: ${flowKey}`);
        // Continue to next flow automatically if applicable
      },
      onPause: (flowKey) => {
        console.log(`[BoundaryReview] Paused for review: ${flowKey}`);
        // User wants to pause and review - no automatic continuation
      },
      onClose: () => {
        // Refresh status after review
        void loadRunStatus();
      }
    });

    /**
     * Show a non-blocking toast notification when a flow completes during autopilot.
     */
    function showFlowCompletedToast(flowKey: string, runId: string): void {
      // Create toast container if it doesn't exist
      let toastContainer = document.getElementById("toast-container");
      if (!toastContainer) {
        toastContainer = document.createElement("div");
        toastContainer.id = "toast-container";
        toastContainer.className = "toast-container";
        document.body.appendChild(toastContainer);
      }

      // Create toast element
      const toast = document.createElement("div");
      toast.className = "toast toast--info";
      toast.innerHTML = `
        <div class="toast__content">
          <span class="toast__icon">&#10003;</span>
          <span class="toast__message">Flow <strong>${flowKey}</strong> completed - review available</span>
          <button class="toast__action" data-flow="${flowKey}" data-run="${runId}">Review</button>
        </div>
        <button class="toast__close" aria-label="Dismiss">&times;</button>
      `;

      // Add event listeners
      const actionBtn = toast.querySelector(".toast__action") as HTMLButtonElement | null;
      if (actionBtn) {
        actionBtn.addEventListener("click", () => {
          // Navigate to the completed flow for review
          void setActiveFlow(flowKey as FlowKey, true);
          toast.remove();
        });
      }

      const closeBtn = toast.querySelector(".toast__close") as HTMLButtonElement | null;
      if (closeBtn) {
        closeBtn.addEventListener("click", () => {
          toast.remove();
        });
      }

      // Auto-dismiss after 8 seconds
      setTimeout(() => {
        toast.classList.add("toast--fade-out");
        setTimeout(() => toast.remove(), 300);
      }, 8000);

      toastContainer.appendChild(toast);
    }

    // Helper to show boundary review for a completed flow or run
    async function showBoundaryReviewPanel(
      flowKey: FlowKey,
      runId: string,
      scope: "flow" | "run" = "flow"
    ): Promise<BoundaryReviewDecision> {
      try {
        // Fetch boundary review data from the dedicated API endpoint
        const boundary = await Api.getBoundaryReview(runId, { scope, flowKey: scope === "flow" ? flowKey : undefined });

        // Derive status from verification results
        let status: FlowCompletionStatus = "UNKNOWN";
        if (boundary.verification_failed > 0) {
          status = "UNVERIFIED";
        } else if (boundary.verification_passed > 0) {
          status = "VERIFIED";
        } else if (boundary.assumptions_count === 0 && boundary.decisions_count === 0) {
          // No data available - check if there's anything at all
          status = "BLOCKED";
        }

        // Get artifacts from RunSummary for display (boundary API doesn't include them)
        const artifacts: import("./domain.js").ArtifactEntry[] = [];
        try {
          const summary = await Api.getRunSummary(runId);
          const flowStatus = summary?.flows?.[flowKey];
          if (flowStatus?.steps) {
            for (const step of Object.values(flowStatus.steps)) {
              if (step.artifacts) {
                artifacts.push(...step.artifacts);
              }
            }
          }
        } catch {
          // Artifacts are optional for display, continue without them
          console.warn("[BoundaryReview] Could not load artifacts from run summary");
        }

        // Get flow title from flows list
        const flowsResponse = await Api.getFlows();
        const flowInfo = flowsResponse.flows.find(f => f.key === flowKey);
        const flowTitle = flowInfo?.title || flowKey;

        // Extract blocking issues and warnings from verifications
        const blockingIssues: string[] = [];
        const warnings: string[] = [];
        for (const v of boundary.verifications) {
          if (!v.verified && v.issues.length > 0) {
            blockingIssues.push(...v.issues);
          }
        }
        // Add uncertainty notes as warnings
        if (boundary.uncertainty_notes && boundary.uncertainty_notes.length > 0) {
          warnings.push(...boundary.uncertainty_notes);
        }

        // Create review data using endpoint response fields
        const reviewData = extractBoundaryReviewData(
          flowKey,
          flowTitle,
          status,
          artifacts,
          {
            assumptionsCount: boundary.assumptions_count,
            decisionsCount: boundary.decisions_count,
            confidenceScore: boundary.confidence_score,
            blockingIssues: blockingIssues.length > 0 ? blockingIssues : undefined,
            warnings: warnings.length > 0 ? warnings : undefined
          }
        );

        // Show the boundary review panel
        return await boundaryReview.show(reviewData);
      } catch (err) {
        console.error("[BoundaryReview] Error loading review data:", err);
        return "cancel";
      }
    }

    // Configure and initialize run control panel
    configureRunControl({
      onRunStart: (runId: string) => {
        // Update run selector when a new run starts
        const runSelector = document.getElementById("run-selector") as HTMLSelectElement | null;
        if (runSelector) {
          // Add new run option if not present
          const existingOption = runSelector.querySelector(`option[value="${runId}"]`);
          if (!existingOption) {
            const newOption = document.createElement("option");
            newOption.value = runId;
            newOption.textContent = runId;
            runSelector.insertBefore(newOption, runSelector.firstChild);
          }
          runSelector.value = runId;
        }
        state.currentRunId = runId;
      },
      onStateChange: (_runState, _runId) => {
        // Refresh status when run state changes
        void loadRunStatus();
      },
      onRunComplete: (runId, isAutopilot) => {
        // Reload run history to show completed run
        void initRunHistory().then(() => {
          setRunHistorySelectedRunId(runId);
        });

        // Different behavior for autopilot vs single-flow runs
        if (isAutopilot) {
          // Autopilot run: show run-level boundary review (scope="run")
          void showBoundaryReviewPanel(state.currentFlowKey || "signal" as FlowKey, runId, "run");
        } else {
          // Single-flow run: show flow-level boundary review (existing behavior)
          if (state.currentFlowKey) {
            void showBoundaryReviewPanel(state.currentFlowKey, runId, "flow");
          }
        }
      },
      onRunFailed: (_runId, _error) => {
        // Refresh status to show failure
        void loadRunStatus();
      },
      onRunStopped: (runId) => {
        // Refresh status to show stopped state
        // Stopped runs remain selectable for review (no reset)
        void loadRunStatus();
        // Update run history to reflect stopped state
        void initRunHistory().then(() => {
          setRunHistorySelectedRunId(runId);
        });
      },
      onSelectRun: async (runId: string) => {
        // Update the main run selector to match
        const runSelector = document.getElementById("run-selector") as HTMLSelectElement | null;
        if (runSelector) {
          runSelector.value = runId;
        }
        state.currentRunId = runId;
        updateCompareSelector();
        await loadRunStatus();
        setRunHistorySelectedRunId(runId);
      },
      onFlowCompleted: (runId: string, flowKey: string) => {
        // Individual flow completed during autopilot run
        // Show a non-blocking toast notification
        showFlowCompletedToast(flowKey, runId);
      },
      onPlanCompleted: (runId: string, _planId: string) => {
        // Entire plan completed - the run-level review will be shown via onRunComplete
        console.log(`[AutoPilot] Plan completed for run: ${runId}`);
      },
      onRunEvent: (event: SSEEvent, runId: string | null) => {
        // Only process events for the currently viewed run
        if (runId !== state.currentRunId) return;

        switch (event.type) {
          case "step_start":
            // Update selected step highlight when a new step starts
            if (event.flowKey && event.stepId && state.currentFlowKey === event.flowKey) {
              selectStep(event.flowKey, event.stepId, { fitGraph: false, skipUrlUpdate: true });
            }
            break;

          case "step_end":
          case "facts_updated":
            // Refresh InventoryCounts when step completes or facts are updated
            if (runId) {
              updateInventoryCounts(runId);
            }
            break;
        }
      }
    });
    initRunControl();

    // Initialize run history in background (non-blocking)
    // This prevents run history loading from blocking the main UI ready state
    initRunHistory()
      .then(() => {
        // Sync run history selection with current run
        if (state.currentRunId) {
          setRunHistorySelectedRunId(state.currentRunId);
        }
      })
      .catch((err) => {
        console.error("Failed to initialize run history", err);
      });

    // Initialize legend toggle with sessionStorage persistence
    // Legend defaults to COLLAPSED on first load for cleaner first impression.
    // User preference persists within session via sessionStorage.
    const LEGEND_STORAGE_KEY = "flowstudio.legend.collapsed";

    function getLegendCollapsed(): boolean {
      if (typeof window === "undefined") return true;
      try {
        const raw = window.sessionStorage.getItem(LEGEND_STORAGE_KEY);
        // If key is missing (null), default to collapsed for cleaner first impression
        if (raw === null) return true;
        return raw === "true";
      } catch {
        // sessionStorage blocked or unavailable - default to collapsed
        return true;
      }
    }

    function setLegendCollapsed(collapsed: boolean): void {
      if (typeof window === "undefined") return;
      try {
        window.sessionStorage.setItem(LEGEND_STORAGE_KEY, collapsed ? "true" : "false");
      } catch {
        // Ignore - UX still works, just loses persistence
      }
    }

    const legendToggle = document.getElementById("legend-toggle");
    const legend = document.getElementById("legend");
    if (legendToggle && legend) {
      // Restore collapsed state from sessionStorage
      const isCollapsed = getLegendCollapsed();
      if (isCollapsed) {
        legend.classList.add("collapsed");
        legendToggle.setAttribute("aria-expanded", "false");
      } else {
        legend.classList.remove("collapsed");
        legendToggle.setAttribute("aria-expanded", "true");
      }

      legendToggle.addEventListener("click", () => {
        legend.classList.toggle("collapsed");
        const nowCollapsed = legend.classList.contains("collapsed");
        setLegendCollapsed(nowCollapsed);
        // Keep aria-expanded in sync with legend state
        legendToggle.setAttribute("aria-expanded", nowCollapsed ? "false" : "true");
      });
    }

    // Apply deep link params after all data is loaded
    try {
      await applyDeepLinkParams();
    } catch (err) {
      console.error("Failed to apply deep link params", err);
    }

    // Initialize inventory counts component (operator mode feature)
    initInventoryCounts();

    // Signal that UI is fully initialized and ready for interaction
    if (debugPerf) {
      // Performance timing logged in development mode
    }
    markUiReady();

    // Export SDK for agents and automation
    window.__flowStudio = {
      getState: () => ({
        currentFlowKey: state.currentFlowKey,
        currentRunId: state.currentRunId,
        currentMode: state.currentMode,
        currentViewMode: state.currentViewMode,
        selectedNodeId: state.selectedNodeId,
        selectedNodeType: state.selectedNodeType
      }),
      getGraphState: getCurrentGraphState,
      setActiveFlow: (flowKey: FlowKey) => setActiveFlow(flowKey, true),
      selectStep: (flowKey: FlowKey, stepId: string) => selectStep(flowKey, stepId),
      selectAgent: (agentKey: string, flowKey?: FlowKey) => selectAgent(agentKey, flowKey),
      clearSelection: clearSelection,
      qsByUiid,
      qsAllByUiidPrefix,
      // Layout spec methods (v0.5.0-flowstudio)
      getLayoutScreens: () => layoutScreens,
      getLayoutScreenById: (id: ScreenId) => getLayoutScreenByIdImpl(id),
      getAllKnownUIIDs: () => getAllKnownUIIDsImpl(),
      // Teaching mode (v0.6.0-flowstudio)
      getTeachingMode,
      setTeachingMode,
      // Context budget settings (v0.7.0-flowstudio)
      getContextBudgets,
      setContextBudgets,
      openContextBudgetModal
    } satisfies FlowStudioSDK;

  } catch (err) {
    // Fatal initialization error - mark UI as failed
    console.error("Flow Studio initialization failed", err);
    markUiError();
  }
});
