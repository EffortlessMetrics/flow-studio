// swarm/tools/flow_studio_ui/src/components/index.ts
// Component exports for Flow Studio UI
//
// All components are pure client-side with NO filesystem operations.
// Data flows through the API client to the backend server.

// Template Palette - drag-and-drop template selection
export {
  TemplatePalette,
  createTemplatePalette,
} from "./TemplatePalette.js";

// Flow Editor - visual flow editing with ETag-based conflict handling
export {
  FlowEditor,
  createFlowEditor,
} from "./FlowEditor.js";
export type { ValidationStatus } from "./FlowEditor.js";

// Validation Modal - displays validation results with severity-based actions
export {
  ValidationModal,
  createValidationModal,
} from "./ValidationModal.js";

// Run Playback - SSE-based run visualization
export {
  RunPlayback,
  createRunPlayback,
} from "./RunPlayback.js";

// Node Inspector - step property editing form
export {
  NodeInspector,
  createNodeInspector,
} from "./NodeInspector.js";

// Inventory Counts - marker count display with deltas
export {
  InventoryCounts,
  createInventoryCounts,
} from "./InventoryCounts.js";
export type { FactsSummaryResponse } from "./InventoryCounts.js";

// Boundary Review - flow completion summary for human review
export {
  BoundaryReview,
  createBoundaryReview,
  extractBoundaryReviewData,
} from "./BoundaryReview.js";
export type {
  BoundaryReviewData,
  BoundaryReviewDecision,
  BoundaryReviewOptions,
  FlowCompletionStatus,
  RoutingDecision,
} from "./BoundaryReview.js";

// Forensic Verdict Card - displays forensic analysis results
export {
  ForensicVerdictCard,
  createForensicVerdictCard,
} from "./ForensicVerdictCard.js";
export type {
  ForensicVerdict,
  ForensicVerdictType,
  ClaimEvidenceComparison,
  ForensicVerdictCardOptions,
} from "./ForensicVerdictCard.js";

// Routing Decision Card - routing choice visualization
export {
  RoutingDecisionCard,
  createRoutingDecisionCard,
} from "./RoutingDecisionCard.js";
export type {
  RoutingCandidate,
  RoutingDecisionData,
  RoutingDecisionCardOptions,
  RoutingAction,
  RoutingSource,
  ForensicVerdictFlags,
} from "./RoutingDecisionCard.js";

// Interruption Stack Panel - flow injection/detour stack visualization
export {
  InterruptionStackPanel,
  createInterruptionStackPanel,
  createEmptyStack,
  parseStackFromApiResponse,
  renderInterruptionStackTab,
} from "./InterruptionStackPanel.js";
export type {
  InterruptionStack,
  StackFrame,
  InterruptionStackPanelOptions,
  RoutingDecisionType,
} from "./InterruptionStackPanel.js";
