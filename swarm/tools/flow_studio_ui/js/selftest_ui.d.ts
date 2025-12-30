import type { SelftestPlan, SelftestStep } from "./domain.js";
/**
 * Fetch and cache selftest plan.
 */
export declare function getSelftestPlan(): Promise<SelftestPlan | null>;
/**
 * Toggle selftest modal visibility with focus management.
 */
export declare function toggleSelftestModal(show: boolean): void;
/**
 * Initialize selftest modal close on backdrop click and keyboard handling.
 */
export declare function initSelftestModal(): void;
/**
 * Show copy success feedback with toast.
 */
export declare function showCopyFeedback(message: string): void;
/**
 * Show copy fallback box (for clipboard API unavailable).
 */
export declare function showCopyFallback(text: string, message: string): void;
/**
 * Copy command and show instructions.
 */
export declare function copyAndRun(cmd: string): void;
/**
 * Show selftest step details in modal.
 */
export declare function showSelftestStepModal(stepId: string): Promise<void>;
/**
 * Render error state in selftest modal.
 */
export declare function renderSelftestPlanError(title: string, message: string): void;
/**
 * Render the selftest step explanation modal.
 */
export declare function renderSelftestStepModal(step: SelftestStep): void;
/**
 * Render selftest plan in a tab container.
 */
export declare function renderSelftestTab(container: HTMLElement): Promise<void>;
/**
 * Show full selftest plan in modal.
 */
export declare function showSelftestPlanModal(): Promise<void>;
