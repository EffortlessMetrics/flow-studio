import type { FlowValidationResult, ValidationDecision } from "../domain.js";
/**
 * Modal options for customization
 */
export interface ValidationModalOptions {
    /** Container element to append modal to (defaults to document.body) */
    container?: HTMLElement;
    /** Callback when modal is closed */
    onClose?: () => void;
}
/**
 * Modal component for displaying validation results.
 *
 * Features:
 * - Groups issues by severity
 * - Shows actionable fix suggestions
 * - Blocks save on critical errors
 * - Allows "Save Anyway" for warnings
 * - Returns user decision via Promise
 */
export declare class ValidationModal {
    private modal;
    private focusManager;
    private options;
    private resolvePromise;
    constructor(options?: ValidationModalOptions);
    /**
     * Show the validation modal and wait for user decision.
     *
     * @param result - The validation result to display
     * @returns Promise resolving to user's decision
     */
    show(result: FlowValidationResult): Promise<ValidationDecision>;
    /**
     * Close the modal and clean up
     */
    close(decision?: ValidationDecision): void;
    /**
     * Destroy the modal instance
     */
    destroy(): void;
    /**
     * Render the modal with validation results
     */
    private render;
    /**
     * Render the summary counts
     */
    private renderSummary;
    /**
     * Render blocking notice for critical errors
     */
    private renderBlockingNotice;
    /**
     * Render issues grouped by severity
     */
    private renderIssuesBySection;
    /**
     * Render a single issue
     */
    private renderIssue;
    /**
     * Render action buttons based on error severity
     */
    private renderActions;
    /**
     * Attach event listeners
     */
    private attachEventListeners;
}
/**
 * Create a new validation modal instance
 */
export declare function createValidationModal(options?: ValidationModalOptions): ValidationModal;
