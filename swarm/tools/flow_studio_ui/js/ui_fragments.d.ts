/**
 * Render an empty state for "no runs" in the sidebar.
 */
export declare function renderNoRuns(): string;
/**
 * Render an empty state for "no flows configured" in the sidebar.
 */
export declare function renderNoFlows(): string;
/**
 * Render the "select a node" empty state for the details panel.
 * Includes onboarding content explaining flows, steps, and agents.
 */
export declare function renderSelectNodeHint(): string;
/**
 * Render an error state for failed run loading.
 */
export declare function renderRunsLoadError(): string;
/**
 * Render a generic error state with custom title and message.
 */
export declare function renderErrorState(title: string, message: string, actionLabel?: string, actionOnClick?: string): string;
/**
 * Render a single key-value pair.
 */
export declare function renderKV(label: string, value: string, mono?: boolean): string;
/**
 * Render a key-value pair with raw HTML value (use with caution).
 */
export declare function renderKVHtml(label: string, valueHtml: string): string;
/**
 * Render the getting started hint for flow details (author mode).
 */
export declare function renderGettingStartedHint(flowKey: string): string;
/**
 * Render the operator mode hint when no timeline is available.
 */
export declare function renderOperatorFlowHint(): string;
/**
 * Render a loading placeholder.
 */
export declare function renderLoading(message?: string): string;
/**
 * Render the "no tour" menu item.
 */
export declare function renderNoTourMenuItem(): string;
/**
 * Render a tour menu item.
 */
export declare function renderTourMenuItem(tourId: string, title: string, description: string): string;
/**
 * Render an agent usage link item.
 */
export declare function renderAgentUsageItem(flowTitle: string, stepTitle: string): string;
/**
 * Render the step location info (author mode).
 */
export declare function renderStepLocationInfo(flowKey: string): string;
/**
 * Render the agent location info (author mode).
 */
export declare function renderAgentLocationInfo(agentKey: string): string;
/**
 * Render agent category hint (operator mode).
 */
export declare function renderAgentCategoryHint(category: string, model: string): string;
/**
 * Render artifact producer hint (operator mode).
 */
export declare function renderArtifactProducerHint(stepId: string, flowKey: string): string;
/**
 * Render tab navigation.
 */
export declare function renderTabs(tabs: Array<{
    id: string;
    label: string;
    active?: boolean;
}>): string;
