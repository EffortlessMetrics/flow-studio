/**
 * Format duration in seconds to human-readable form
 */
export declare function formatDuration(seconds: number | null): string;
/**
 * Format ISO timestamp to time only (HH:MM)
 */
export declare function formatTime(isoString: string | null): string;
/**
 * Format ISO timestamp to date + time
 */
export declare function formatDateTime(isoString: string | null): string;
/**
 * Escape HTML special characters to prevent XSS
 */
export declare function escapeHtml(text: string | null): string;
/**
 * Copy text to clipboard
 */
export declare function copyToClipboard(text: string): Promise<void>;
/**
 * Create a copy button element
 */
export declare function createCopyButton(text: string, label?: string): HTMLButtonElement;
/**
 * Create a path display with copy button
 */
export declare function createPathWithCopy(path: string): HTMLDivElement;
/**
 * Create quick commands section with copy buttons
 */
export declare function createQuickCommands(commands: string[]): HTMLDivElement;
/**
 * Get all focusable elements within a container
 */
export declare function getFocusableElements(container: HTMLElement): HTMLElement[];
/**
 * Focus trap state for cleanup
 */
export interface FocusTrapState {
    cleanup: () => void;
}
/**
 * Create a focus trap within a container.
 *
 * - Traps Tab/Shift+Tab to cycle within the container
 * - Moves focus into the container on creation
 * - Returns cleanup function to remove the trap
 *
 * @param container - The element to trap focus within
 * @param initialFocusEl - Element to focus initially (defaults to first focusable)
 */
export declare function createFocusTrap(container: HTMLElement, initialFocusEl?: HTMLElement | null): FocusTrapState;
/**
 * Modal focus management helper.
 *
 * Handles:
 * - Storing the invoker element
 * - Creating a focus trap when opened
 * - Restoring focus when closed
 *
 * @param modal - The modal element
 * @param contentSelector - Selector for the modal content (for focus trap)
 */
export interface ModalFocusManager {
    open(invoker?: Element | null): void;
    close(): void;
    isOpen(): boolean;
}
export declare function createModalFocusManager(modal: HTMLElement, contentSelector: string): ModalFocusManager;
