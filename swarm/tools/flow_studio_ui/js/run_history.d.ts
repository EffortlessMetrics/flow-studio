import type { Run } from "./domain.js";
/**
 * Callbacks for run history interactions.
 */
export interface RunHistoryCallbacks {
    /** Called when a run is selected from history */
    onRunSelect?: (runId: string) => Promise<void>;
    /** Called when run detail is opened */
    onRunDetailOpen?: (runId: string) => Promise<void>;
}
/**
 * Configure callbacks for the run history module.
 * Call this before using other functions to wire up UI interactions.
 */
export declare function configure(callbacks?: RunHistoryCallbacks): void;
type RunFilterType = "all" | "example" | "active";
/**
 * Load run history from API and update internal state.
 * Fetches runs from the API and populates the run history panel.
 */
export declare function loadRunHistory(): Promise<void>;
/**
 * Filter the displayed runs by type.
 *
 * @param type - Filter type: "all", "example", or "active"
 */
export declare function filterRuns(type: RunFilterType): void;
/**
 * Handle run selection from history.
 * Updates internal state and calls the onRunSelect callback.
 *
 * @param runId - The ID of the run to select
 */
export declare function selectHistoryRun(runId: string): Promise<void>;
/**
 * Open the run detail modal/panel for a specific run.
 *
 * @param runId - The ID of the run to show details for
 */
export declare function openRunDetail(runId: string): Promise<void>;
/**
 * Render the run history panel into a container element.
 *
 * @param container - The HTML element to render into
 */
export declare function renderRunHistoryPanel(container: HTMLElement): void;
/**
 * Get the currently selected run ID.
 */
export declare function getSelectedRunId(): string | null;
/**
 * Get the current filter type.
 */
export declare function getCurrentFilter(): RunFilterType;
/**
 * Get the current runs (filtered).
 */
export declare function getFilteredRuns(): Run[];
/**
 * Get all loaded runs.
 */
export declare function getAllRuns(): Run[];
/**
 * Set the selected run ID without triggering callback.
 * Useful for syncing with external state changes.
 */
export declare function setSelectedRunId(runId: string | null): void;
/**
 * Initialize the run history panel.
 * Loads runs from the API and populates the existing HTML structure.
 *
 * Call this once during app initialization to:
 * - Load initial run data
 * - Wire up filter buttons
 * - Wire up collapse toggle
 * - Render the run list
 *
 * When Teaching Mode is enabled, defaults to "example" filter.
 */
export declare function initRunHistory(): Promise<void>;
export {};
