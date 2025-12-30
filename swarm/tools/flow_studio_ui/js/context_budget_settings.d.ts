/**
 * Context Budget Settings Module
 *
 * Provides state management and UI for context budget configuration.
 * Follows the same pattern as teaching_mode.ts.
 */
import type { ContextBudgetConfig, ContextBudgetOverride, ContextBudgetPresetId, ContextBudgetPreset } from "./domain";
/** Preset configurations for common context budget scenarios */
export declare const PRESETS: Record<ContextBudgetPresetId, ContextBudgetPreset>;
/** Callback type for context budget changes */
export type ContextBudgetCallback = (budgets: ContextBudgetConfig) => void;
/**
 * Detect which preset (if any) matches the current effective budgets.
 * Returns null if no preset matches exactly.
 */
export declare function detectCurrentPreset(): ContextBudgetPresetId | null;
/**
 * Apply a preset's values to the current context budgets.
 * @param presetId - The preset to apply ("lean", "balanced", or "heavy")
 */
export declare function applyPreset(presetId: ContextBudgetPresetId): Promise<void>;
/**
 * Initialize the context budget settings module.
 * Should be called once during app startup.
 */
export declare function initContextBudgetSettings(): void;
/**
 * Get the current effective context budgets.
 */
export declare function getContextBudgets(): ContextBudgetConfig;
/**
 * Get the current profile override (may be null if using defaults).
 */
export declare function getProfileOverride(): ContextBudgetOverride | null;
/**
 * Update profile-level context budget overrides.
 * Pass null to reset to defaults.
 */
export declare function setContextBudgets(budgets: Partial<ContextBudgetOverride> | null): Promise<void>;
/**
 * Reset to default budgets (clear all overrides).
 */
export declare function resetToDefaults(): Promise<void>;
/**
 * Register a callback to be notified when budgets change.
 * Returns an unsubscribe function.
 */
export declare function onContextBudgetChange(callback: ContextBudgetCallback): () => void;
/**
 * Open the context budget settings modal.
 * This should be wired to a button in the header.
 */
export declare function openContextBudgetModal(): void;
/**
 * Close the context budget settings modal.
 */
export declare function closeContextBudgetModal(): void;
/**
 * Update the active state of preset buttons based on current settings.
 * Toggles the `.active` class on preset buttons based on whether the current
 * budget settings match that preset.
 */
export declare function updatePresetButtonStates(): void;
/**
 * Initialize modal event handlers.
 * Should be called after DOM is ready.
 */
export declare function initContextBudgetModalHandlers(): void;
