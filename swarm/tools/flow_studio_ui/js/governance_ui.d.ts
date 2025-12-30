import type { NodeData, FRCheck, GovernanceStatus, NodeGovernanceInfo, ResolutionHint } from "./domain.js";
/**
 * Load governance status from API and update UI elements.
 */
export declare function loadGovernanceStatus(): Promise<void>;
/**
 * Update the issues count badge in the header.
 */
export declare function updateValidationIssuesCount(): void;
/**
 * Update flow list items with governance warning badges.
 */
export declare function updateFlowListGovernance(): void;
/**
 * Toggle governance overlay on graph nodes.
 */
export declare function toggleGovernanceOverlay(enabled: boolean): void;
/**
 * Update graph nodes with governance issue highlighting.
 */
export declare function updateGraphGovernanceOverlay(): void;
/**
 * Apply FR status classes to graph nodes for visual feedback.
 */
export declare function applyFRStatusToNodes(): void;
/**
 * Get governance info for a specific node.
 */
export declare function getNodeGovernanceInfo(nodeData: NodeData): NodeGovernanceInfo | null;
/**
 * Get FR status badges HTML for a node.
 */
export declare function getNodeFRBadges(nodeData: NodeData): string | null;
/**
 * Format FR checks as HTML badges.
 */
export declare function formatFRBadges(checks: Record<string, FRCheck>): string;
/**
 * Render governance section in details panel.
 */
export declare function renderGovernanceSection(container: HTMLElement, govInfo: NodeGovernanceInfo): void;
/**
 * Generate resolution hints based on governance status.
 */
export declare function generateResolutionHints(governanceStatus: GovernanceStatus): ResolutionHint[];
/**
 * Render resolution hints in the details panel.
 */
export declare function renderResolutionHints(container: HTMLElement, governanceStatus: GovernanceStatus): void;
/**
 * Render selftest plan table HTML.
 */
export declare function renderSelftestPlan(): Promise<string>;
/**
 * Show full governance details in the details panel.
 */
export declare function showGovernanceDetails(): void;
