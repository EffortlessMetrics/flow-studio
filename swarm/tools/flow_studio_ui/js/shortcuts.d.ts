import type { ShortcutsCallbacks } from "./domain.js";
/**
 * Configure callbacks for the shortcuts module.
 */
export declare function configure(callbacks?: ShortcutsCallbacks): void;
/**
 * Toggle the keyboard shortcuts help modal with focus management.
 */
export declare function toggleShortcutsModal(show: boolean): void;
/**
 * Initialize shortcuts modal close on backdrop click and ESC key.
 */
export declare function initShortcutsModal(): void;
/**
 * Initialize global keyboard shortcuts.
 */
export declare function initKeyboardShortcuts(): void;
