import type { FlowKey, NodeData, AgentUsage, StepTiming, StepDetailsCallbacks, AgentDetailsCallbacks, AgentUsageCallbacks } from "./domain.js";
/**
 * Show the default empty state in the details panel.
 * Called when no node is selected.
 */
export declare function showEmptyState(): void;
/**
 * Render run-level timeline in the container
 */
export declare function renderRunTimeline(container: HTMLElement): Promise<void>;
/**
 * Render flow timing summary in the container
 */
export declare function renderFlowTiming(container: HTMLElement, flowKey: FlowKey): Promise<void>;
/**
 * Render step timing inline
 */
export declare function renderStepTiming(timing: StepTiming): string;
/**
 * Render agent usage as clickable links
 */
export declare function renderAgentUsage(container: HTMLElement, usage: AgentUsage[], callbacks?: AgentUsageCallbacks): void;
/** Extended node data for steps */
interface StepNodeData extends NodeData {
    step_id?: string;
    role?: string;
}
/**
 * Show step details in the details panel
 */
export declare function showStepDetails(data: StepNodeData, callbacks?: StepDetailsCallbacks): Promise<void>;
/** Extended node data for agents */
interface AgentNodeData extends NodeData {
    agent_key?: string;
    category?: string;
    model?: string;
    short_role?: string;
    description?: string;
}
/**
 * Show agent details in the details panel
 */
export declare function showAgentDetails(data: AgentNodeData, callbacks?: AgentDetailsCallbacks): Promise<void>;
/** Extended node data for artifacts */
interface ArtifactNodeData extends NodeData {
    filename?: string;
    required?: boolean;
    is_decision?: boolean;
    note?: string;
}
/**
 * Show artifact details in the details panel
 */
export declare function showArtifactDetails(data: ArtifactNodeData): void;
export {};
