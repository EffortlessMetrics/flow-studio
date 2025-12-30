import type { FlowKey, ToursCallbacks } from "./domain.js";
/**
 * Configure callbacks for the tours module.
 */
export declare function configure(callbacks?: ToursCallbacks): void;
/**
 * Load available tours from API.
 */
export declare function loadTours(): Promise<void>;
/**
 * Render the tour dropdown menu.
 */
export declare function renderTourMenu(): void;
/**
 * Start a tour by ID.
 */
export declare function startTour(tourId: string): Promise<void>;
/**
 * Exit the current tour.
 */
export declare function exitTour(): void;
/**
 * Show the current tour step.
 */
export declare function showTourStep(): void;
/**
 * Go to next tour step.
 */
export declare function nextTourStep(): void;
/**
 * Go to previous tour step.
 */
export declare function prevTourStep(): void;
/**
 * Highlight a flow in the sidebar and SDLC bar.
 */
export declare function highlightFlow(flowKey: FlowKey): void;
/**
 * Highlight a step in the graph.
 */
export declare function highlightStep(flowKey: FlowKey, stepId: string): void;
/**
 * Clear all tour highlights.
 */
export declare function clearTourHighlight(): void;
/**
 * Hide the tour card.
 */
export declare function hideTourCard(): void;
/**
 * Update tour button appearance.
 */
export declare function updateTourButton(active: boolean): void;
/**
 * Toggle tour dropdown menu visibility.
 */
export declare function toggleTourMenu(): void;
/**
 * Close tour dropdown menu.
 */
export declare function closeMenu(): void;
/**
 * Initialize tour event handlers.
 */
export declare function initTourHandlers(): void;
/**
 * Get the current tour ID if one is active.
 */
export declare function getCurrentTourId(): string | null;
