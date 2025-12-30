import { type RunState, type SSEEvent } from "./api/client.js";
/**
 * Run control state
 */
interface RunControlState {
    /** Current run ID being controlled */
    activeRunId: string | null;
    /** Current run state */
    runState: RunState;
    /** Current step being executed */
    currentStep: string | null;
    /** Current flow being executed (for autopilot) */
    currentFlow: string | null;
    /** Progress percentage (0-100) */
    progress: number;
    /** Error message if any */
    error: string | null;
    /** Whether an action is in progress */
    isLoading: boolean;
    /** Unsubscribe function for SSE */
    unsubscribe: (() => void) | null;
    /** ETag for optimistic locking */
    etag: string | null;
    /** Whether this is an autopilot run (multiple flows or plan_id) */
    isAutopilot: boolean;
    /** Flow keys for autopilot runs */
    flowKeys: string[];
    /** Plan ID for autopilot runs (if from a plan) */
    planId: string | null;
    /** Completed flows in this run (for autopilot tracking) */
    completedFlows: string[];
}
/**
 * Callbacks for run control events
 */
export interface RunControlCallbacks {
    /** Called when a run starts */
    onRunStart?: (runId: string) => void;
    /** Called when a run state changes */
    onStateChange?: (state: RunState, runId: string) => void;
    /** Called when a run completes */
    onRunComplete?: (runId: string, isAutopilot: boolean) => void;
    /** Called when a run fails (error condition) */
    onRunFailed?: (runId: string, error: string) => void;
    /** Called when a run is stopped by user (clean stop, distinct from failure) */
    onRunStopped?: (runId: string) => void;
    /** Called when run needs to be selected in the UI */
    onSelectRun?: (runId: string) => Promise<void>;
    /** Called for every SSE event received during a run */
    onRunEvent?: (event: SSEEvent, runId: string | null) => void;
    /** Called when an individual flow completes (during autopilot) */
    onFlowCompleted?: (runId: string, flowKey: string) => void;
    /** Called when the entire plan completes (during autopilot) */
    onPlanCompleted?: (runId: string, planId: string) => void;
}
/**
 * Configure callbacks for run control events.
 */
export declare function configure(callbacks?: RunControlCallbacks): void;
/**
 * Get the current run control state.
 */
export declare function getRunControlState(): Readonly<RunControlState>;
/**
 * Check if there's an active run.
 */
export declare function hasActiveRun(): boolean;
/**
 * Check if the current run is an autopilot run.
 */
export declare function isAutopilotRun(): boolean;
/**
 * Get the list of completed flows in the current autopilot run.
 */
export declare function getCompletedFlows(): readonly string[];
/**
 * Get the current flow being executed (for autopilot runs).
 */
export declare function getCurrentFlow(): string | null;
/**
 * Start a new run.
 *
 * @param flowId - Flow ID to run (defaults to current flow)
 * @param options - Optional run configuration
 */
export declare function startRun(flowId?: string, options?: {
    runId?: string;
    context?: Record<string, unknown>;
    startStep?: string;
    mode?: "execute" | "preview" | "validate";
    /** Flow keys for autopilot runs (multiple flows) */
    flowKeys?: string[];
    /** Plan ID for autopilot runs derived from a plan */
    planId?: string;
}): Promise<void>;
/**
 * Pause the current run.
 */
export declare function pauseRun(): Promise<void>;
/**
 * Resume the current paused run.
 */
export declare function resumeRun(): Promise<void>;
/**
 * Stop the current run.
 *
 * Stopped is a clean user-initiated termination, distinct from a failure.
 * Stopped runs remain selectable and reviewable (no auto-reset).
 */
export declare function stopRun(): Promise<void>;
/**
 * Cancel the current run.
 * @deprecated Use stopRun() instead. This alias is kept for backwards compatibility.
 */
export declare function cancelRun(): Promise<void>;
/**
 * Set the active run to monitor (for existing runs).
 */
export declare function setActiveRun(runId: string): Promise<void>;
/**
 * Clear the active run (e.g., when selecting a different run in the UI).
 */
export declare function clearActiveRun(): void;
/**
 * Initialize the run control panel.
 * Call this during app initialization to wire up event handlers.
 */
export declare function initRunControl(): void;
export { startRun as start, pauseRun as pause, resumeRun as resume, stopRun as stop, cancelRun as cancel, };
export type { SSEEvent } from "./api/client.js";
