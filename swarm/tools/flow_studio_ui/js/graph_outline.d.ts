import type { GraphState } from "./domain.js";
/**
 * Get the current graph state as a JSON-serializable object.
 * Useful for snapshots, tests, and LLM agent context.
 */
export declare function getCurrentGraphState(): GraphState | null;
/**
 * Render a semantic DOM tree mirroring the graph structure.
 * This provides:
 * - ARIA tree semantics for screen readers
 * - Text representation for LLM agents
 * - Stable selectors for testing (data-uiid)
 *
 * The outline is rendered into #flow-outline (visually hidden but accessible).
 */
export declare function renderFlowOutline(): void;
