/**
 * Initialize teaching mode from localStorage.
 * Call this once during app startup.
 */
export declare function initTeachingMode(): void;
/**
 * Get the current teaching mode state.
 * @returns true if Teaching Mode is enabled
 */
export declare function getTeachingMode(): boolean;
/**
 * Set the teaching mode state.
 * Persists to localStorage and updates the DOM.
 * Notifies all registered callbacks of the change.
 *
 * @param enabled - Whether Teaching Mode should be enabled
 */
export declare function setTeachingMode(enabled: boolean): void;
/**
 * Toggle the teaching mode state.
 * Convenience method that inverts the current state.
 *
 * @returns The new state after toggling
 */
export declare function toggleTeachingMode(): boolean;
/** Callback type for teaching mode changes */
export type TeachingModeCallback = (enabled: boolean) => void;
/**
 * Register a callback to be notified when Teaching Mode changes.
 * Useful for components that need to update when teaching mode is toggled.
 *
 * @param callback - Function called with the new state when teaching mode changes
 */
export declare function onTeachingModeChange(callback: TeachingModeCallback): void;
/**
 * Get the default Run History filter based on Teaching Mode.
 * When Teaching Mode is enabled, defaults to "example" filter.
 *
 * @returns "example" if Teaching Mode is on, "all" otherwise
 */
export declare function getDefaultRunHistoryFilter(): "all" | "example";
/**
 * Initialize the toggle button event handler.
 * Call this after the DOM is ready.
 */
export declare function initToggleButtonHandler(): void;
