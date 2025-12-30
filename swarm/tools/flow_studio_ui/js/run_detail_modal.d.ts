import type { RunSummary } from "./domain.js";
/**
 * Callbacks for run detail modal actions.
 */
export interface RunDetailCallbacks {
    onClose?: () => void;
    onRerun?: (runId: string) => Promise<void>;
}
/**
 * Extended run summary with additional metadata fields.
 * The API may return these additional fields beyond the base RunSummary.
 */
interface ExtendedRunSummary extends RunSummary {
    backend?: string;
    profile_id?: string;
    created_at?: string;
    started_at?: string;
    completed_at?: string;
    status?: "pending" | "running" | "completed" | "failed" | "canceled";
    error_message?: string;
    tags?: string[];
    is_exemplar?: boolean;
}
/**
 * Configure the run detail modal with callbacks.
 */
export declare function configure(callbacks?: RunDetailCallbacks): void;
/**
 * Show the run detail modal for a specific run.
 */
export declare function showRunDetailModal(runId: string): Promise<void>;
/**
 * Close the run detail modal.
 */
export declare function closeRunDetailModal(): void;
/**
 * Render the run detail modal content.
 */
export declare function renderRunDetailContent(runId: string, summary: ExtendedRunSummary): string;
declare global {
    interface Window {
        showRunDetailModal?: typeof showRunDetailModal;
        closeRunDetailModal?: typeof closeRunDetailModal;
    }
}
export {};
