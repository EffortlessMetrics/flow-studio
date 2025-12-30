import type { FlowStudioUIID } from "./domain.js";
/**
 * Layout regions are semantic, not positional.
 * They describe the purpose of a UI area, not its CSS position.
 */
export type LayoutRegionId = "header" | "sidebar" | "canvas" | "inspector" | "modal" | "sdlc_bar";
/**
 * Screen identifiers for Flow Studio.
 * Format: <context>.<variant>
 */
export type ScreenId = "flows.default" | "flows.validation" | "flows.selftest" | "flows.tour" | "flows.shortcuts";
/**
 * A layout region within a screen.
 */
export interface LayoutRegion {
    /** Region identifier */
    id: LayoutRegionId;
    /** Human-readable purpose for docs/agents */
    purpose: string;
    /** CSS selectors or data-uiid values that define this region */
    uiids: FlowStudioUIID[];
}
/**
 * A screen specification in the layout registry.
 */
export interface ScreenSpec {
    /** Unique screen identifier */
    id: ScreenId;
    /** Route fragment or query shape (e.g., "/flow-studio?view=flows") */
    route: string;
    /** Human-readable screen title */
    title: string;
    /** Description of the screen's purpose */
    description: string;
    /** Regions present on this screen */
    regions: LayoutRegion[];
}
/**
 * Authoritative registry of screens.
 * This is what MCP + layout-review will enumerate.
 */
export declare const screens: ScreenSpec[];
/**
 * Index of screens by ID for quick lookup.
 */
export declare const screenById: Record<ScreenId, ScreenSpec>;
/**
 * Get all known screen IDs.
 */
export declare function getScreenIds(): ScreenId[];
/**
 * Get a screen spec by ID, or null if not found.
 */
export declare function getScreenById(id: ScreenId): ScreenSpec | null;
/**
 * Get all UIIDs across all screens and regions.
 * Useful for coverage checks.
 */
export declare function getAllKnownUIIDs(): FlowStudioUIID[];
/**
 * Validate that all UIIDs in the layout spec are actually defined
 * in the FlowStudioUIID type. Returns UIIDs that are in spec but
 * not in the type (should be empty if spec is in sync).
 */
export declare function validateLayoutUIIDs(): {
    valid: boolean;
    issues: string[];
};
/**
 * Export the layout spec as a JSON-serializable object.
 * Used by /api/layout_screens endpoint.
 */
export declare function toJSON(): {
    version: string;
    screens: ScreenSpec[];
};
