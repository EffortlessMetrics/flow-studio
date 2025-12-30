// swarm/tools/flow_studio_ui/src/run_control.ts
// Run Control panel module for Flow Studio
//
// This module handles:
// - Starting, pausing, resuming, and stopping runs
// - Run state management and UI updates
// - Integration with the API client
import { flowStudioApi } from "./api/client.js";
import { state } from "./state.js";
// ============================================================================
// Module State
// ============================================================================
const _state = {
    activeRunId: null,
    runState: "pending",
    currentStep: null,
    currentFlow: null,
    progress: 0,
    error: null,
    isLoading: false,
    unsubscribe: null,
    etag: null,
    isAutopilot: false,
    flowKeys: [],
    planId: null,
    completedFlows: [],
};
let _callbacks = {};
// ============================================================================
// Configuration
// ============================================================================
/**
 * Configure callbacks for run control events.
 */
export function configure(callbacks = {}) {
    _callbacks = { ..._callbacks, ...callbacks };
}
// ============================================================================
// State Accessors
// ============================================================================
/**
 * Get the current run control state.
 */
export function getRunControlState() {
    return { ..._state };
}
/**
 * Check if there's an active run.
 */
export function hasActiveRun() {
    return _state.activeRunId !== null &&
        (_state.runState === "running" || _state.runState === "paused");
}
/**
 * Check if the current run is an autopilot run.
 */
export function isAutopilotRun() {
    return _state.isAutopilot;
}
/**
 * Get the list of completed flows in the current autopilot run.
 */
export function getCompletedFlows() {
    return [..._state.completedFlows];
}
/**
 * Get the current flow being executed (for autopilot runs).
 */
export function getCurrentFlow() {
    return _state.currentFlow;
}
// ============================================================================
// Run Control Actions
// ============================================================================
/**
 * Start a new run.
 *
 * @param flowId - Flow ID to run (defaults to current flow)
 * @param options - Optional run configuration
 */
export async function startRun(flowId, options) {
    if (_state.isLoading)
        return;
    const targetFlowId = flowId || state.currentFlowKey || "signal";
    _state.isLoading = true;
    _state.error = null;
    updateUI();
    try {
        const runInfo = await flowStudioApi.startRun(targetFlowId, options);
        _state.activeRunId = runInfo.run_id;
        _state.runState = runInfo.state || "running";
        _state.currentStep = runInfo.currentStep || null;
        _state.currentFlow = targetFlowId;
        _state.progress = runInfo.progress || 0;
        _state.isLoading = false;
        // Detect autopilot mode: multiple flows or plan ID
        const flowKeys = options?.flowKeys || [];
        const planId = options?.planId || null;
        _state.isAutopilot = flowKeys.length > 1 || planId !== null;
        _state.flowKeys = flowKeys.length > 0 ? flowKeys : [targetFlowId];
        _state.planId = planId;
        _state.completedFlows = [];
        // Subscribe to run events
        subscribeToRunEvents(runInfo.run_id);
        if (_callbacks.onRunStart) {
            _callbacks.onRunStart(runInfo.run_id);
        }
        if (_callbacks.onSelectRun) {
            await _callbacks.onSelectRun(runInfo.run_id);
        }
        updateUI();
    }
    catch (err) {
        _state.isLoading = false;
        _state.error = err.message || "Failed to start run";
        console.error("Failed to start run", err);
        updateUI();
    }
}
/**
 * Pause the current run.
 */
export async function pauseRun() {
    if (!_state.activeRunId || _state.isLoading || _state.runState !== "running") {
        return;
    }
    _state.isLoading = true;
    updateUI();
    try {
        await flowStudioApi.pauseRun(_state.activeRunId, _state.etag || undefined);
        _state.runState = "paused";
        _state.isLoading = false;
        if (_callbacks.onStateChange) {
            _callbacks.onStateChange("paused", _state.activeRunId);
        }
        updateUI();
    }
    catch (err) {
        _state.isLoading = false;
        _state.error = err.message || "Failed to pause run";
        console.error("Failed to pause run", err);
        updateUI();
    }
}
/**
 * Resume the current paused run.
 */
export async function resumeRun() {
    if (!_state.activeRunId || _state.isLoading || _state.runState !== "paused") {
        return;
    }
    _state.isLoading = true;
    updateUI();
    try {
        await flowStudioApi.resumeRun(_state.activeRunId, _state.etag || undefined);
        _state.runState = "running";
        _state.isLoading = false;
        if (_callbacks.onStateChange) {
            _callbacks.onStateChange("running", _state.activeRunId);
        }
        updateUI();
    }
    catch (err) {
        _state.isLoading = false;
        _state.error = err.message || "Failed to resume run";
        console.error("Failed to resume run", err);
        updateUI();
    }
}
/**
 * Stop the current run.
 *
 * Stopped is a clean user-initiated termination, distinct from a failure.
 * Stopped runs remain selectable and reviewable (no auto-reset).
 */
export async function stopRun() {
    if (!_state.activeRunId || _state.isLoading) {
        return;
    }
    // Only allow stop if running or paused
    if (_state.runState !== "running" && _state.runState !== "paused") {
        return;
    }
    _state.isLoading = true;
    updateUI();
    try {
        // Use the existing cancelRun API endpoint (backend still calls it cancel)
        await flowStudioApi.cancelRun(_state.activeRunId, _state.etag || undefined);
        const runId = _state.activeRunId;
        // Unsubscribe from events
        if (_state.unsubscribe) {
            _state.unsubscribe();
            _state.unsubscribe = null;
        }
        // Set state to "stopped" - distinct from "failed"
        _state.runState = "stopped";
        _state.isLoading = false;
        // No error message - stopped is a clean state, not an error
        _state.error = null;
        // Fire the stopped callback (not failed)
        if (_callbacks.onRunStopped) {
            _callbacks.onRunStopped(runId);
        }
        // Also fire state change for general listeners
        if (_callbacks.onStateChange) {
            _callbacks.onStateChange("stopped", runId);
        }
        // No auto-reset: stopped runs remain selectable and reviewable
        updateUI();
    }
    catch (err) {
        _state.isLoading = false;
        _state.error = err.message || "Failed to stop run";
        console.error("Failed to stop run", err);
        updateUI();
    }
}
/**
 * Cancel the current run.
 * @deprecated Use stopRun() instead. This alias is kept for backwards compatibility.
 */
export async function cancelRun() {
    return stopRun();
}
// ============================================================================
// SSE Subscription
// ============================================================================
/**
 * Subscribe to run events via SSE.
 */
function subscribeToRunEvents(runId) {
    // Clean up existing subscription
    if (_state.unsubscribe) {
        _state.unsubscribe();
    }
    _state.unsubscribe = flowStudioApi.subscribeToRun(runId, handleSSEEvent);
}
/**
 * Handle incoming SSE events.
 */
function handleSSEEvent(event) {
    switch (event.type) {
        case "step_start":
            _state.currentStep = event.stepId || null;
            // Update current flow if provided
            if (event.flowKey) {
                _state.currentFlow = event.flowKey;
            }
            break;
        case "step_end":
            // Calculate progress based on completed steps
            if (event.payload?.progress !== undefined) {
                _state.progress = event.payload.progress;
            }
            break;
        case "flow_completed":
            // Individual flow completed (relevant for autopilot runs)
            if (event.flowKey && !_state.completedFlows.includes(event.flowKey)) {
                _state.completedFlows.push(event.flowKey);
            }
            // Notify listeners of flow completion
            if (_callbacks.onFlowCompleted && _state.activeRunId && event.flowKey) {
                _callbacks.onFlowCompleted(_state.activeRunId, event.flowKey);
            }
            break;
        case "plan_completed":
            // Entire plan completed (autopilot run finished)
            if (_callbacks.onPlanCompleted && _state.activeRunId && _state.planId) {
                _callbacks.onPlanCompleted(_state.activeRunId, _state.planId);
            }
            // Fall through to complete handling
            _state.runState = "completed";
            _state.progress = 100;
            if (_state.unsubscribe) {
                _state.unsubscribe();
                _state.unsubscribe = null;
            }
            if (_callbacks.onRunComplete && _state.activeRunId) {
                _callbacks.onRunComplete(_state.activeRunId, _state.isAutopilot);
            }
            break;
        case "complete":
            _state.runState = "completed";
            _state.progress = 100;
            if (_state.unsubscribe) {
                _state.unsubscribe();
                _state.unsubscribe = null;
            }
            if (_callbacks.onRunComplete && _state.activeRunId) {
                _callbacks.onRunComplete(_state.activeRunId, _state.isAutopilot);
            }
            break;
        case "error":
            _state.runState = "failed";
            _state.error = event.payload?.error || "Run failed";
            if (_state.unsubscribe) {
                _state.unsubscribe();
                _state.unsubscribe = null;
            }
            if (_callbacks.onRunFailed && _state.activeRunId) {
                _callbacks.onRunFailed(_state.activeRunId, _state.error);
            }
            break;
    }
    // Notify listeners of every SSE event for UI propagation
    _callbacks.onRunEvent?.(event, _state.activeRunId);
    updateUI();
}
// ============================================================================
// State Management
// ============================================================================
/**
 * Reset the run control state.
 */
function resetState() {
    if (_state.unsubscribe) {
        _state.unsubscribe();
    }
    _state.activeRunId = null;
    _state.runState = "pending";
    _state.currentStep = null;
    _state.currentFlow = null;
    _state.progress = 0;
    _state.error = null;
    _state.isLoading = false;
    _state.unsubscribe = null;
    _state.etag = null;
    _state.isAutopilot = false;
    _state.flowKeys = [];
    _state.planId = null;
    _state.completedFlows = [];
}
/**
 * Set the active run to monitor (for existing runs).
 */
export async function setActiveRun(runId) {
    if (_state.activeRunId === runId)
        return;
    // Clean up existing subscription
    if (_state.unsubscribe) {
        _state.unsubscribe();
        _state.unsubscribe = null;
    }
    try {
        const { data, etag } = await flowStudioApi.getRunState(runId);
        _state.activeRunId = runId;
        _state.runState = data.status;
        _state.currentStep = data.current_step;
        _state.etag = etag;
        _state.error = data.error;
        // Subscribe to events if run is active
        if (_state.runState === "running" || _state.runState === "paused") {
            subscribeToRunEvents(runId);
        }
        updateUI();
    }
    catch (err) {
        console.error("Failed to get run state", err);
        // Run might not exist in backend - just show idle state
        resetState();
        updateUI();
    }
}
/**
 * Clear the active run (e.g., when selecting a different run in the UI).
 */
export function clearActiveRun() {
    resetState();
    updateUI();
}
// ============================================================================
// UI Updates
// ============================================================================
/**
 * Update the run control UI based on current state.
 */
function updateUI() {
    const playBtn = document.getElementById("run-control-play");
    const pauseBtn = document.getElementById("run-control-pause");
    const resumeBtn = document.getElementById("run-control-resume");
    const cancelBtn = document.getElementById("run-control-cancel");
    const statusText = document.getElementById("run-control-status-text");
    const statusContainer = document.getElementById("run-control-status");
    if (!playBtn || !pauseBtn || !resumeBtn || !cancelBtn || !statusText || !statusContainer) {
        return;
    }
    // Remove all state classes
    statusContainer.classList.remove("run-control-status--pending", "run-control-status--running", "run-control-status--paused", "run-control-status--completed", "run-control-status--failed", "run-control-status--stopped");
    // Handle loading state
    if (_state.isLoading) {
        playBtn.disabled = true;
        pauseBtn.disabled = true;
        resumeBtn.disabled = true;
        cancelBtn.disabled = true;
        statusText.textContent = "Processing...";
        statusText.className = "run-control-status-text run-control-status-text--loading";
        return;
    }
    // Update based on run state
    switch (_state.runState) {
        case "pending":
            // No active run - can start
            playBtn.disabled = false;
            playBtn.style.display = "";
            pauseBtn.disabled = true;
            pauseBtn.style.display = "";
            resumeBtn.style.display = "none";
            cancelBtn.disabled = true;
            statusText.textContent = "No active run";
            statusText.className = "muted";
            statusContainer.classList.add("run-control-status--pending");
            break;
        case "running":
            // Run in progress - can pause or stop
            playBtn.disabled = true;
            playBtn.style.display = "";
            pauseBtn.disabled = false;
            pauseBtn.style.display = "";
            resumeBtn.style.display = "none";
            cancelBtn.disabled = false;
            statusText.textContent = _state.currentStep
                ? `Running: ${_state.currentStep}`
                : "Running...";
            statusText.className = "run-control-status-text run-control-status-text--running";
            statusContainer.classList.add("run-control-status--running");
            break;
        case "paused":
            // Run paused - can resume or stop
            playBtn.style.display = "none";
            pauseBtn.style.display = "none";
            resumeBtn.disabled = false;
            resumeBtn.style.display = "";
            cancelBtn.disabled = false;
            statusText.textContent = _state.currentStep
                ? `Paused at: ${_state.currentStep}`
                : "Paused";
            statusText.className = "run-control-status-text run-control-status-text--paused";
            statusContainer.classList.add("run-control-status--paused");
            break;
        case "completed":
            // Run completed - can start new
            playBtn.disabled = false;
            playBtn.style.display = "";
            pauseBtn.disabled = true;
            pauseBtn.style.display = "";
            resumeBtn.style.display = "none";
            cancelBtn.disabled = true;
            statusText.textContent = "Completed";
            statusText.className = "run-control-status-text run-control-status-text--completed";
            statusContainer.classList.add("run-control-status--completed");
            break;
        case "failed":
            // Run failed - can start new
            playBtn.disabled = false;
            playBtn.style.display = "";
            pauseBtn.disabled = true;
            pauseBtn.style.display = "";
            resumeBtn.style.display = "none";
            cancelBtn.disabled = true;
            statusText.textContent = _state.error || "Failed";
            statusText.className = "run-control-status-text run-control-status-text--failed";
            statusContainer.classList.add("run-control-status--failed");
            break;
        case "stopped":
            // Run stopped by user - can start new, remains selectable for review
            playBtn.disabled = false;
            playBtn.style.display = "";
            pauseBtn.disabled = true;
            pauseBtn.style.display = "";
            resumeBtn.style.display = "none";
            cancelBtn.disabled = true;
            statusText.textContent = _state.currentStep
                ? `Stopped at: ${_state.currentStep}`
                : "Stopped";
            statusText.className = "run-control-status-text run-control-status-text--stopped";
            statusContainer.classList.add("run-control-status--stopped");
            break;
    }
    // Add progress indicator if running
    if (_state.runState === "running" && _state.progress > 0) {
        const progressBar = statusContainer.querySelector(".run-control-progress");
        if (progressBar) {
            progressBar.style.width = `${_state.progress}%`;
        }
    }
}
// ============================================================================
// Initialization
// ============================================================================
/**
 * Initialize the run control panel.
 * Call this during app initialization to wire up event handlers.
 */
export function initRunControl() {
    const playBtn = document.getElementById("run-control-play");
    const pauseBtn = document.getElementById("run-control-pause");
    const resumeBtn = document.getElementById("run-control-resume");
    const cancelBtn = document.getElementById("run-control-cancel");
    if (playBtn) {
        playBtn.addEventListener("click", () => {
            void startRun();
        });
    }
    if (pauseBtn) {
        pauseBtn.addEventListener("click", () => {
            void pauseRun();
        });
    }
    if (resumeBtn) {
        resumeBtn.addEventListener("click", () => {
            void resumeRun();
        });
    }
    if (cancelBtn) {
        cancelBtn.addEventListener("click", () => {
            void stopRun();
        });
    }
    // Initial UI update
    updateUI();
}
// ============================================================================
// Exports for SDK
// ============================================================================
export { startRun as start, pauseRun as pause, resumeRun as resume, stopRun as stop, cancelRun as cancel, // deprecated alias for stopRun
 };
