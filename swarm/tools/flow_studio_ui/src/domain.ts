/**
 * Flow Studio Domain Types
 *
 * CANONICAL SOURCE: src/domain.ts
 * The js/domain.d.ts file is GENERATED from this file — do not edit it directly.
 * Run `make ts-build` to regenerate declaration files after editing this source.
 *
 * These types define the core data structures used throughout Flow Studio.
 * They serve as the contract between:
 * - Python backend (FastAPI endpoints)
 * - TypeScript frontend (browser modules)
 * - Tests and tooling
 */

// ============================================================================
// Flow Keys & Constants
// ============================================================================

/** Valid flow keys in the SDLC (core + demo flows) */
export type FlowKey = "signal" | "plan" | "build" | "gate" | "deploy" | "wisdom" | "stepwise-demo";

/** Run types distinguish examples from active work */
export type RunType = "example" | "active";

/** Status values for steps/artifacts */
export type StepStatus = "done" | "in_progress" | "not_started" | "complete" | "partial" | "missing" | "n/a";

/**
 * Flow health status for sidebar display.
 * Provides a simplified, user-friendly status model:
 * - ok: All required checks/artifacts passed
 * - warning: Non-blocking issues or missing optional artifacts
 * - error: Blocking failures or missing required artifacts
 * - unknown: No run data for this flow
 */
export type FlowHealthStatus = "ok" | "warning" | "error" | "unknown";

/** Metadata for flow health status display */
export interface FlowStatusMeta {
  icon: string;
  tooltip: string;
}

/** Artifact presence status */
export type ArtifactStatus = "present" | "missing" | "unknown";

/** UI mode for author vs operator views */
export type UIMode = "author" | "operator";

/** View mode for graph display */
export type ViewMode = "agents" | "artifacts";

// ============================================================================
// Graph Data (Cytoscape)
// ============================================================================

/** Node types in the flow graph */
export type NodeType = "step" | "agent" | "artifact";

/** Edge types connecting nodes */
export type EdgeType = "step-sequence" | "step-agent" | "step-artifact";

/** A node in the flow graph */
export interface FlowGraphNode {
  /** Cytoscape element wrapper */
  data: {
    id: string;
    type: NodeType;
    label: string;
    flow?: FlowKey;
    step_id?: string | null;
    agent_key?: string | null;
    order?: number | null;
    color?: string | null;
    status?: ArtifactStatus | null;
    is_decision?: boolean;
  };
}

/** An edge in the flow graph */
export interface FlowGraphEdge {
  data: {
    id: string;
    type: EdgeType;
    source: string;
    target: string;
  };
}

/** Graph data returned by /api/graph/:flow endpoints */
export interface FlowGraph {
  nodes: FlowGraphNode[];
  edges: FlowGraphEdge[];
  /** Optional UI overlay fields for flow editing */
  palette?: Record<string, unknown>;
  canvas?: Record<string, unknown>;
  groups?: Record<string, unknown>;
  annotations?: Record<string, unknown>;
}

/** Serialized graph state from getCurrentGraphState() */
export interface GraphState {
  version: "flow_graph.v1";
  flow_key: FlowKey | null;
  run_id: string | null;
  view_mode: ViewMode;
  timestamp: string;
  nodes: SerializedNode[];
  edges: SerializedEdge[];
}

/** Flattened node for serialization (no `data` wrapper) */
export interface SerializedNode {
  id: string;
  type: NodeType;
  label: string;
  flow?: FlowKey;
  step_id?: string | null;
  order?: number | null;
  color?: string | null;
  status?: ArtifactStatus | null;
}

/** Flattened edge for serialization */
export interface SerializedEdge {
  id: string;
  type: EdgeType;
  source: string;
  target: string;
}

/** Node data passed to click handlers (flattened from Cytoscape) */
export interface NodeData {
  id: string;
  type: NodeType;
  label: string;
  flow?: FlowKey;
  step_id?: string;
  agent_key?: string;
  order?: number;
  color?: string;
  status?: ArtifactStatus;
  is_decision?: boolean;
}

// ============================================================================
// Context Budget Configuration
// ============================================================================

/**
 * Resolved context budget configuration values.
 * Result of cascade resolution: Step > Flow > Profile > Global defaults
 */
export interface ContextBudgetConfig {
  context_budget_chars: number;
  history_max_recent_chars: number;
  history_max_older_chars: number;
  source: "default" | "profile" | "flow" | "step";
}

/**
 * Optional context budget overrides.
 * Undefined values mean 'inherit from parent level'.
 */
export interface ContextBudgetOverride {
  context_budget_chars?: number;
  history_max_recent_chars?: number;
  history_max_older_chars?: number;
}

/** Preset identifier type */
export type ContextBudgetPresetId = "lean" | "balanced" | "heavy";

/** Preset configuration values */
export interface ContextBudgetPreset {
  id: ContextBudgetPresetId;
  label: string;
  description: string;
  context_budget_chars: number;
  history_max_recent_chars: number;
  history_max_older_chars: number;
}

/** Budget metrics captured during prompt building */
export interface BudgetMetrics {
  prompt_chars_used: number;
  prompt_tokens_estimated: number;
  history_steps_total: number;
  history_steps_included: number;
  truncation_occurred: boolean;
  effective_budgets: {
    context_budget_chars: number;
    history_max_recent_chars: number;
    history_max_older_chars: number;
    source: "default" | "profile" | "flow" | "step";
  };
}

// ============================================================================
// Backends API
// ============================================================================

/**
 * Backend capability information returned by /api/backends.
 * Describes what a run execution backend supports.
 */
export interface BackendCapability {
  /** Backend identifier (e.g., "claude-harness", "gemini-cli") */
  id: string;
  /** Human-readable backend name */
  label: string;
  /** Whether the backend can stream events in real-time */
  supports_streaming: boolean;
  /** Whether the backend emits structured events */
  supports_events: boolean;
  /** Whether runs can be canceled mid-execution */
  supports_cancel: boolean;
  /** Whether past runs can be replayed */
  supports_replay: boolean;
}

/** Response from /api/backends */
export interface BackendsResponse {
  backends: BackendCapability[];
}

// ============================================================================
// Runs API
// ============================================================================

/** A run entry from /api/runs */
export interface Run {
  run_id: string;
  run_type: RunType;
  title?: string;
  description?: string;
  created_at?: string;
  /** Whether this run is marked as an exemplar (best-practice example) */
  is_exemplar?: boolean;
  /** Tags for categorizing runs */
  tags?: string[];
  /** Backend used for this run (e.g., "claude-harness", "gemini-cli") */
  backend?: string;
}

/** Response from /api/runs with pagination */
export interface RunsResponse {
  runs: Run[];
  /** Total number of runs available */
  total: number;
  /** Maximum runs returned in this response */
  limit: number;
  /** Number of runs skipped from the beginning */
  offset: number;
  /** Whether more runs are available beyond this page */
  has_more: boolean;
}

/** A single event in a run's execution timeline */
export interface RunEvent {
  run_id: string;
  ts: string;
  kind: string;
  flow_key: string;
  step_id?: string | null;
  agent_key?: string | null;
  payload?: Record<string, unknown>;
}

/** Response from /api/runs/{id}/events */
export interface RunEventsResponse {
  run_id: string;
  events: RunEvent[];
}

/** Timing data for a step */
export interface StepTiming {
  started_at?: string;
  ended_at?: string;
  duration_seconds?: number;
}

/** Artifact status entry */
export interface ArtifactEntry {
  path: string;
  status: ArtifactStatus;
  required: boolean;
}

/** Step status within a flow */
export interface StepStatusData {
  status: StepStatus;
  artifacts?: ArtifactEntry[];
  timing?: StepTiming;
  note?: string;
  required_present?: number;
  required_total?: number;
  optional_present?: number;
  optional_total?: number;
}

/** Flow status within a run */
export interface FlowStatusData {
  status: StepStatus;
  steps: Record<string, StepStatusData>;
}

/** Response from /api/runs/:id/summary */
export interface RunSummary {
  run_id: string;
  title?: string;
  flows: Record<FlowKey, FlowStatusData>;
}

/** Timeline event from /api/runs/:id/timeline */
export interface TimelineEvent {
  timestamp: string;
  flow: FlowKey;
  step_id: string;
  event_type: string;
  message?: string;
  status?: string;
  duration_ms?: number;
  note?: string;
}

/** Agent usage entry */
export interface AgentUsage {
  flow: FlowKey;
  flow_title: string;
  step: string;
  step_title: string;
}

/** Response from /api/agents/:key/usage */
export interface AgentUsageResponse {
  usage: AgentUsage[];
}

/** A single message in an LLM transcript */
export interface TranscriptMessage {
  timestamp?: string;
  role: "system" | "user" | "assistant";
  content: string;
}

/** Response from /api/runs/{run_id}/flows/{flow_key}/steps/{step_id}/transcript */
export interface StepTranscriptResponse {
  run_id: string;
  flow_key: string;
  step_id: string;
  engine: string | null;
  messages: TranscriptMessage[];
  transcript_file: string;
}

/** Receipt data from stepwise execution */
export interface StepReceipt {
  engine: string;
  mode?: string;          // "stub" | "sdk" | "cli"
  provider?: string;      // "anthropic" | "gemini" | "none"
  model?: string;
  step_id: string;
  flow_key: string;
  run_id: string;
  agent_key: string;
  started_at?: string;
  completed_at?: string;
  duration_ms?: number;
  status: string;
  tokens?: {
    prompt: number;
    completion: number;
    total: number;
  };
  transcript_path?: string;
  // Routing decision data (populated by stepwise orchestrator)
  routing?: {
    loop_iteration: number;
    max_iterations: number | null;
    decision: "loop" | "advance" | "terminate";
    reason: string;
  };
  // Context truncation metrics (populated by prompt builder)
  context_truncation?: {
    steps_included: number;
    steps_total: number;
    chars_used: number;
    budget_chars: number;
    truncated: boolean;
    priority_aware?: boolean;
    priority_distribution?: {
      CRITICAL: number;
      HIGH: number;
      MEDIUM: number;
      LOW: number;
    };
  };
  // V3 Routing Protocol: Full routing decision with candidates (optional)
  routing_decision?: {
    chosen_candidate_id: string;
    candidates: Array<{
      candidate_id: string;
      action: string;
      target_node: string | null;
      reason: string;
      priority: number;
      source: string;
      evidence_pointers: string[];
      is_default: boolean;
    }>;
    routing_source: string;
    forensic_verdict?: {
      claim_verified: boolean;
      confidence: number;
      recommendation: "TRUST" | "VERIFY" | "REJECT";
      reward_hacking_flags: string[];
      discrepancy_count?: number;
      critical_issue?: string;
    };
    timestamp?: string;
    iteration?: number;
    flow_key?: string;
    step_id?: string;
  };
  // V3 Forensic Verdict: Standalone forensic verification (optional)
  forensic_verdict?: {
    verdict: "PASS" | "REJECT" | "INCONCLUSIVE";
    discrepancy_count: number;
    critical_issues: string[];
    reward_hacking_flags: string[];
    claim_vs_evidence: Array<{
      claim: string;
      evidence: string;
      match: boolean;
    }>;
  };
}

/** Response from /api/runs/{run_id}/flows/{flow_key}/steps/{step_id}/receipt */
export interface StepReceiptResponse {
  run_id: string;
  flow_key: string;
  step_id: string;
  receipt: StepReceipt;
  receipt_file: string;
}

/** Response from /api/runs/:id/timeline */
export interface RunTimeline {
  events: TimelineEvent[];
}

// ============================================================================
// Wisdom API (v2.4.0)
// ============================================================================

/** Flow status within a wisdom summary */
export interface FlowWisdomStatus {
  status: "succeeded" | "failed" | "skipped";
  microloops?: number;
  test_loops?: number;
  code_loops?: number;
}

/** Wisdom metrics summary */
export interface WisdomMetrics {
  artifacts_present: number;
  regressions_found: number;
  learnings_count: number;
  feedback_actions_count: number;
  issues_created: number;
}

/** Response from /api/runs/{id}/wisdom/summary */
export interface WisdomSummary {
  run_id: string;
  created_at: string;
  flows: Record<FlowKey, FlowWisdomStatus>;
  summary: WisdomMetrics;
  labels: string[];
  key_artifacts: Record<string, string>;
}

/** Run health assessment */
export interface RunHealth {
  run_id: string;
  health: "healthy" | "degraded" | "unhealthy" | "unknown";
  score: number;  // 0-100
  breakdown: {
    artifacts_completeness: number;
    test_coverage: number;
    gate_verdict: string;
    regression_count: number;
  };
}

// ============================================================================
// Flows API
// ============================================================================

/** A flow entry from /api/flows */
export interface Flow {
  key: FlowKey;
  title: string;
  description?: string;
  step_count: number;
}

/** Response from /api/flows */
export interface FlowsResponse {
  flows: Flow[];
}

/** Teaching metadata for a flow */
export interface FlowTeaching {
  /** Human-readable title for teaching mode */
  title: string;
  /** 1-2 sentence explanation of what this flow does */
  summary: string;
}

/** Step definition within a flow */
export interface FlowStep {
  id: string;
  order: number;
  role: string;
  agents: string[];
  artifacts?: string[];
  human_only?: boolean;
  /** Teaching note explaining why this step matters and what to look for */
  teaching_note?: string;
  /** Mark important steps for visual emphasis in teaching mode */
  teaching_highlight?: boolean;
  // Structured teaching notes
  teaching_notes?: {
    inputs: string[];
    outputs: string[];
    emphasizes: string[];
    constraints: string[];
  };
}

/** Response from /api/flows/:key */
export interface FlowDetail {
  key: FlowKey;
  title: string;
  description?: string;
  steps: FlowStep[];
  agents: string[];
  /** Teaching metadata for the flow */
  teaching?: FlowTeaching;
}

// ============================================================================
// Comparison API
// ============================================================================

/** Step comparison data */
export interface StepComparison {
  step_id: string;
  run_a: { status: StepStatus };
  run_b: { status: StepStatus };
  change: "improved" | "regressed" | "unchanged";
}

/** Response from /api/runs/compare */
export interface ComparisonData {
  run_a: string;
  run_b: string;
  flow: FlowKey;
  summary: {
    improved: number;
    regressed: number;
    unchanged: number;
  };
  steps: StepComparison[];
}

// ============================================================================
// Search API
// ============================================================================

/** Search result types */
export type SearchResultType = "flow" | "step" | "agent" | "artifact";

/** A single search result */
export interface SearchResult {
  type: SearchResultType;
  id: string;
  label: string;
  flow?: FlowKey;
  step_id?: string;
  agent_key?: string;
  score?: number;
  /** For agent results: the agent key */
  key?: string;
  /** For agent results: list of flows this agent belongs to */
  flows?: FlowKey[];
  /** For artifact results: the file path */
  file?: string;
}

/** Response from /api/search */
export interface SearchResponse {
  query: string;
  results: SearchResult[];
}

// ============================================================================
// Governance & Validation
// ============================================================================

/**
 * Validation error severity levels.
 * - CRITICAL: Blocking issues that prevent save (missing required fields, invalid IDs, broken edges)
 * - WARNING: Non-blocking issues that should be reviewed (missing teaching notes, potential issues)
 * - INFO: Suggestions for improvement (optional enhancements)
 */
export type ValidationSeverity = "CRITICAL" | "WARNING" | "INFO";

/**
 * A single validation issue with severity and actionable information.
 */
export interface ValidationIssue {
  /** Unique identifier for this issue type */
  code: string;
  /** Severity level determining how the issue is handled */
  severity: ValidationSeverity;
  /** Human-readable description of the issue */
  message: string;
  /** Path to the problematic element (e.g., "nodes[0].data.id") */
  path?: string;
  /** Suggested fix action */
  fix?: string;
  /** Related node or edge ID */
  elementId?: string;
}

/**
 * Result of flow validation for save operations.
 * Categorizes issues by severity for decision-making.
 */
export interface FlowValidationResult {
  /** Whether the flow is valid for saving (no critical errors) */
  valid: boolean;
  /** All validation issues found */
  issues: ValidationIssue[];
  /** Count by severity for quick checks */
  summary: {
    critical: number;
    warning: number;
    info: number;
  };
}

/**
 * User's decision when validation issues are found.
 */
export type ValidationDecision = "save" | "fix" | "cancel";

/** FR check result */
export interface FRCheck {
  status: "pass" | "fail" | "warn";
  message?: string;
  fix?: string;
}

/** Agent validation data */
export interface AgentValidation {
  file: string;
  checks: Record<string, FRCheck>;
  has_issues: boolean;
  has_warnings: boolean;
  issues?: Array<{
    error_type: string;
    problem: string;
    fix_action: string;
  }>;
}

/** Flow validation data */
export interface FlowValidation {
  file: string;
  checks: Record<string, FRCheck>;
  has_issues: boolean;
  has_warnings: boolean;
  issues?: Array<{
    error_type: string;
    problem: string;
    fix_action: string;
  }>;
}

/** Step extraction data from validation */
export interface StepValidation {
  id: string;
  agents: string[];
  role: string;
  human_only: boolean;
  line: number;
}

/** Skill validation data */
export interface SkillValidation {
  file: string;
  valid: boolean;
  issues?: Array<{
    error_type: string;
    problem: string;
    fix_action: string;
  }>;
}

/** Response from /api/validation */
export interface ValidationData {
  version: string;
  timestamp: string;
  summary: {
    status: "PASS" | "FAIL";
    total_checks: number;
    passed: number;
    failed: number;
    warnings: number;
    agents_with_issues: string[];
    flows_with_issues: string[];
    steps_with_issues: string[];
  };
  agents: Record<string, AgentValidation>;
  flows: Record<string, FlowValidation>;
  steps: Record<string, StepValidation[]>;
  skills: Record<string, SkillValidation>;
}

/** Kernel status in governance */
export interface KernelStatus {
  status: "HEALTHY" | "BROKEN" | "unknown";
  error?: string;
}

/**
 * Normalized selftest status using the 4-state model.
 * The API may return legacy values (GREEN/YELLOW/RED/UNKNOWN) which should be
 * normalized to this model in the UI layer.
 */
export type NormalizedSelftestStatus = "ok" | "warning" | "error" | "unknown";

/**
 * Legacy selftest status values from the API.
 * These are converted to NormalizedSelftestStatus in the UI layer.
 */
export type LegacySelftestStatus = "GREEN" | "YELLOW" | "RED" | "UNKNOWN";

/** Selftest results in governance */
export interface SelftestStatus {
  status: LegacySelftestStatus | NormalizedSelftestStatus;
  mode: "strict" | "degraded" | "kernel-only" | "unknown";
  kernel_ok: boolean;
  governance_ok: boolean;
  optional_ok: boolean;
  failed_steps: string[];
  degraded_steps: string[];
  degradations?: Array<{
    step_id: string;
    severity: "CRITICAL" | "WARNING" | "INFO";
    timestamp: string;
    message: string;
    remediation?: string;
  }>;
  critical_passed?: number;
  critical_failed?: number;
  warning_passed?: number;
  warning_failed?: number;
  info_passed?: number;
  info_failed?: number;
}

/** Agent stats in governance */
export interface AgentStats {
  total: number;
  by_status: {
    healthy: number;
    invalid?: number;
  };
  invalid_agents?: string[];
}

/** Flow stats in governance */
export interface FlowStats {
  total: number;
  healthy: number;
  invalid_flows?: string[];
}

/** Response from /platform/status */
export interface GovernanceStatus {
  timestamp: string;
  governance: {
    kernel: KernelStatus;
    selftest: SelftestStatus;
  };
  agents: AgentStats;
  flows: FlowStats;
  hints?: {
    summary?: string;
    detailed?: string;
  };
}

// ============================================================================
// Selftest API
// ============================================================================

/** Selftest tier levels */
export type SelftestTier = "kernel" | "governance" | "optional";

/** A step in the selftest plan */
export interface SelftestStep {
  id: string;
  tier: SelftestTier;
  severity: "critical" | "warning" | "info";
  category: string;
  description?: string;
  depends_on: string[];
  ac_ids?: string[];
}

/** Response from /api/selftest/plan */
export interface SelftestPlan {
  steps: SelftestStep[];
  summary: {
    total: number;
    by_tier: {
      kernel: number;
      governance: number;
      optional: number;
    };
  };
}

// ============================================================================
// Tours API
// ============================================================================

/** Target for a tour step */
export interface TourTarget {
  type: "flow" | "step";
  flow: FlowKey;
  step?: string;
}

/** A tour step */
export interface TourStep {
  target: TourTarget;
  title: string;
  /** Text content for the tour card */
  text: string;
  position?: "top" | "bottom" | "left" | "right";
}

/** A tour definition */
export interface Tour {
  id: string;
  title: string;
  description?: string;
  steps: TourStep[];
}

/** Response from /api/tours */
export interface ToursResponse {
  tours: Tour[];
}

// ============================================================================
// UI State
// ============================================================================

/** The global UI state object shape */
export interface UIState {
  // Cytoscape instance (typed as `any` since Cytoscape has its own types)
  cy: CytoscapeInstance | null;

  // Current selection
  currentFlowKey: FlowKey | null;
  currentRunId: string | null;
  compareRunId: string | null;

  // Node selection (unified selection model)
  selectedNodeId: string | null;
  selectedNodeType: NodeType | null;

  // Cached API data
  runStatus: Partial<RunSummary>;
  comparisonData: ComparisonData | null;
  availableRuns: Run[];

  // Governance state
  governanceStatus: GovernanceStatus | null;
  validationData: ValidationData | null;
  governanceOverlayEnabled: boolean;

  // UI mode
  currentMode: UIMode;
  currentViewMode: ViewMode;

  // Search state
  searchDebounceTimer: ReturnType<typeof setTimeout> | null;
  searchSelectedIndex: number;
  searchResults: SearchResult[];

  // Navigation
  currentStepIndex: number;

  // Selftest state
  selftestPlan: SelftestPlan | null;
  selftestPlanCache: SelftestPlan | null;
}

/** Status icons mapping */
export interface StatusIcons {
  done: string;
  in_progress: string;
  not_started: string;
  complete: string;
  partial: string;
  missing: string;
  "n/a": string;
}

// ============================================================================
// Module Callback Types
// ============================================================================

/** Callbacks for runs_flows module configuration */
export interface RunsFlowsCallbacks {
  onFlowDetails?: (detail: FlowDetail) => void;
  onNodeClick?: (nodeData: NodeData) => void;
  onURLUpdate?: () => void;
  updateFlowListGovernance?: () => void;
}

/** Callbacks for search module configuration */
export interface SearchCallbacks {
  setActiveFlow?: (flowKey: FlowKey) => Promise<void>;
  getCy?: () => CytoscapeInstance | null;
}

/** Callbacks for shortcuts module configuration */
export interface ShortcutsCallbacks {
  setActiveFlow?: (flowKey: FlowKey) => Promise<void>;
  showStepDetails?: (nodeData: NodeData) => void;
  toggleSelftestModal?: (show: boolean) => void;
}

/** Callbacks for tours module configuration */
export interface ToursCallbacks {
  setActiveFlow?: (flowKey: FlowKey) => Promise<void>;
}

/** Governance info for a node */
export interface NodeGovernanceInfo {
  has_issues: boolean;
  checks?: Record<string, FRCheck>;
  issues?: Array<{
    error_type: string;
    problem: string;
    fix_action: string;
  }>;
}

/** Callbacks for step details rendering */
export interface StepDetailsCallbacks {
  renderSelftestTab?: (container: HTMLElement) => Promise<void>;
  getNodeGovernanceInfo?: (data: NodeData) => NodeGovernanceInfo | null;
  renderGovernanceSection?: (container: HTMLElement, info: NodeGovernanceInfo) => void;
  selectAgent?: (agentKey: string, flowKey?: FlowKey) => Promise<void>;
}

/** Callbacks for agent details rendering */
export interface AgentDetailsCallbacks {
  setActiveFlow?: (flowKey: FlowKey, force?: boolean) => Promise<void>;
  showStepDetails?: (nodeData: NodeData) => void;
  getNodeGovernanceInfo?: (data: NodeData) => NodeGovernanceInfo | null;
  renderGovernanceSection?: (container: HTMLElement, info: NodeGovernanceInfo) => void;
}

/** Callbacks for agent usage rendering */
export interface AgentUsageCallbacks {
  setActiveFlow?: (flowKey: FlowKey, force?: boolean) => Promise<void>;
  showStepDetails?: (nodeData: NodeData) => void;
}

/** Options for graph rendering */
export interface RenderGraphOptions {
  onNodeClick?: (nodeData: NodeData) => void;
}

/** Options for focus node animation */
export interface FocusNodeOptions {
  padding?: number;
}

// ============================================================================
// Resolution Hints
// ============================================================================

/** A resolution hint for governance issues */
export interface ResolutionHint {
  type: "failure" | "advisory" | "workaround";
  step?: string;
  root_cause: string;
  command: string;
  docs: string;
}

// ============================================================================
// Boundary Review API
// ============================================================================

/** Summary of an assumption made during execution */
export interface AssumptionSummary {
  assumption_id: string;
  statement: string;
  rationale: string;
  impact_if_wrong: string;
  confidence: "high" | "medium" | "low";
  status: "active" | "resolved" | "invalidated";
  tags: string[];
  flow_introduced?: string;
  step_introduced?: string;
  agent?: string;
  timestamp?: string;
}

/** Summary of a decision made during execution */
export interface DecisionSummary {
  decision_id: string;
  decision_type: string;
  subject: string;
  decision: string;
  rationale: string;
  supporting_evidence: string[];
  conditions: string[];
  assumptions_applied: string[];
  flow?: string;
  step?: string;
  agent?: string;
  timestamp?: string;
}

/** Summary of a detour taken during execution */
export interface DetourSummary {
  detour_id: string;
  from_step: string;
  to_step: string;
  reason: string;
  detour_type: string;
  evidence_path?: string;
  timestamp?: string;
}

/** Routing decision from V3 routing protocol */
export interface RoutingDecisionRecord {
  /** One of: CONTINUE, DETOUR, INJECT_FLOW, INJECT_NODES, EXTEND_GRAPH */
  decision: string;
  /** Target flow/node(s) for non-CONTINUE decisions */
  target: string;
  /** Human-readable explanation */
  justification: string;
  /** Links to artifacts supporting the decision */
  evidence: string[];
  /** Whether this deviates from the golden path */
  offroad: boolean;
  /** Alternative routes that were evaluated */
  suggestions_considered?: string[];
  /** When the decision was made */
  timestamp: string;
  /** Node where decision was made (e.g., "build.step-3") */
  source_node: string;
  /** Current depth in graph stack (0 = root flow) */
  stack_depth: number;
  /** Structured justification for off-road decisions */
  why_now?: {
    trigger: string;
    analysis?: string;
    relevance_to_charter?: string;
    alternatives_considered?: string[];
    expected_outcome?: string;
  };
}

/** Verification result for a step */
export interface VerificationSummary {
  step_id: string;
  station_id?: string;
  status: string;
  verified: boolean;
  can_further_iteration_help?: boolean;
  issues: string[];
  timestamp?: string;
}

/** Inventory marker delta */
export interface InventoryDelta {
  marker_type: string;
  label: string;
  count: number;
  delta: number;
}

/** Response from /api/runs/:id/boundary-review */
export interface BoundaryReviewResponse {
  run_id: string;
  scope: "flow" | "run";
  current_flow?: FlowKey;

  assumptions_count: number;
  assumptions_high_risk: number;
  assumptions: AssumptionSummary[];

  decisions_count: number;
  decisions: DecisionSummary[];

  detours_count: number;
  detours: DetourSummary[];

  /** V3 routing decisions from the routing protocol */
  routing_decisions?: RoutingDecisionRecord[];
  /** Current stack depth during execution */
  stack_depth?: number;
  /** Maximum stack depth reached */
  max_stack_depth?: number;

  verification_passed: number;
  verification_failed: number;
  verifications: VerificationSummary[];

  inventory_deltas: InventoryDelta[];

  has_evolution_patches: boolean;
  evolution_patch_count: number;

  confidence_score: number;
  uncertainty_notes: string[];

  timestamp: string;
}

// ============================================================================
// Cytoscape Types (minimal interface for our usage)
// ============================================================================

/** Minimal Cytoscape node interface */
export interface CytoscapeNode {
  id(): string;
  data(key?: string): unknown;
  select(): void;
}

/** Minimal Cytoscape edge interface */
export interface CytoscapeEdge {
  id(): string;
  data(key?: string): unknown;
}

/** Minimal Cytoscape instance interface */
export interface CytoscapeInstance {
  nodes(selector?: string): CytoscapeNodeCollection;
  edges(selector?: string): CytoscapeEdgeCollection;
  fit(padding?: number): void;
  center(): void;
  zoom(level?: number): number;
  on(event: string, handler: (evt: CytoscapeEvent) => void): void;
  getElementById(id: string): CytoscapeNode;
  layout(options: object): { run(): void };
  add(elements: object | object[]): void;
  remove(elements: object): void;
  elements(): CytoscapeCollection;
  destroy(): void;
}

/** Cytoscape collection interface */
export interface CytoscapeCollection {
  forEach(callback: (ele: CytoscapeNode | CytoscapeEdge) => void): void;
  map<T>(callback: (ele: CytoscapeNode | CytoscapeEdge) => T): T[];
  filter(callback: (ele: CytoscapeNode | CytoscapeEdge) => boolean): CytoscapeCollection;
  length: number;
}

/** Cytoscape node collection */
export interface CytoscapeNodeCollection extends CytoscapeCollection {
  [index: number]: CytoscapeNode;
  forEach(callback: (ele: CytoscapeNode) => void): void;
  map<T>(callback: (ele: CytoscapeNode) => T): T[];
  filter(callback: (ele: CytoscapeNode) => boolean): CytoscapeNodeCollection;
  sort(compareFn: (a: CytoscapeNode, b: CytoscapeNode) => number): CytoscapeNodeCollection;
}

/** Cytoscape edge collection */
export interface CytoscapeEdgeCollection extends CytoscapeCollection {
  forEach(callback: (ele: CytoscapeEdge) => void): void;
  map<T>(callback: (ele: CytoscapeEdge) => T): T[];
  filter(callback: (ele: CytoscapeEdge) => boolean): CytoscapeEdgeCollection;
}

/** Cytoscape event */
export interface CytoscapeEvent {
  target: CytoscapeNode | CytoscapeEdge;
}

// ============================================================================
// UI Contract: Typed UIID Selectors
// ============================================================================

/**
 * Known UI element IDs for stable selectors.
 * These follow the pattern: flow_studio[.<region>.<thing>[.subthing][:{dynamic_id}]]
 *
 * Regions are semantic (not layout-based):
 * - header: Top bar with search, mode toggle, governance badge
 * - sidebar: Left panel with run selector, flow list, view toggle
 * - canvas: Main graph visualization area and legend
 * - inspector: Right details panel (steps/agents/artifacts)
 * - modal: Modal dialogs (selftest, shortcuts)
 * - sdlc_bar: SDLC progress bar between header and content
 */
export type FlowStudioUIID =
  // Root
  | "flow_studio"
  // Header
  | "flow_studio.header"
  | "flow_studio.header.search"
  | "flow_studio.header.search.input"
  | "flow_studio.header.search.results"
  | "flow_studio.header.controls"
  | "flow_studio.header.tour"
  | "flow_studio.header.tour.trigger"
  | "flow_studio.header.tour.menu"
  | "flow_studio.header.mode"
  | "flow_studio.header.mode.author"
  | "flow_studio.header.mode.operator"
  | "flow_studio.header.governance"
  | "flow_studio.header.governance.overlay"
  | "flow_studio.header.teaching_mode"
  | "flow_studio.header.teaching_mode.toggle"
  | "flow_studio.header.reload"
  | "flow_studio.header.reload.btn"
  | "flow_studio.header.help"
  | "flow_studio.header.profile"
  // SDLC Bar
  | "flow_studio.sdlc_bar"
  | "flow_studio.sdlc_bar.wisdom_indicator"
  // Sidebar
  | "flow_studio.sidebar"
  | "flow_studio.sidebar.run_selector"
  | "flow_studio.sidebar.run_selector.select"
  | "flow_studio.sidebar.compare_selector"
  | "flow_studio.sidebar.flow_list"
  | "flow_studio.sidebar.view_toggle"
  | "flow_studio.sidebar.view_toggle.agents"
  | "flow_studio.sidebar.view_toggle.artifacts"
  | "flow_studio.sidebar.backend_selector"
  | "flow_studio.sidebar.backend_selector.select"
  // Sidebar: Inventory Counts
  | "flow_studio.sidebar.inventory_counts"
  | "flow_studio.sidebar.run_control"
  | "flow_studio.sidebar.run_control.buttons"
  | "flow_studio.sidebar.run_control.play"
  | "flow_studio.sidebar.run_control.pause"
  | "flow_studio.sidebar.run_control.resume"
  | "flow_studio.sidebar.run_control.cancel"
  | "flow_studio.sidebar.run_control.status"
  // Sidebar: Run History
  | "flow_studio.sidebar.run_history"
  | "flow_studio.sidebar.run_history.filter"
  | "flow_studio.sidebar.run_history.list"
  // Inventory Component
  | "flow_studio.inventory.counts"
  // Canvas
  | "flow_studio.canvas"
  | "flow_studio.canvas.graph"
  | "flow_studio.canvas.legend"
  | "flow_studio.canvas.legend.toggle"
  | "flow_studio.canvas.outline"
  // Inspector
  | "flow_studio.inspector"
  | "flow_studio.inspector.details"
  | "flow_studio.inspector.teaching_note"
  | "flow_studio.inspector.interruption_stack"
  // Modals
  | "flow_studio.modal.shortcuts"
  | "flow_studio.modal.selftest"
  // Run Detail Modal
  | "flow_studio.modal.run_detail"
  | "flow_studio.modal.run_detail.close"
  | "flow_studio.modal.run_detail.body"
  | "flow_studio.modal.run_detail.rerun"
  | "flow_studio.modal.run_detail.exemplar"
  | "flow_studio.modal.run_detail.events.toggle"
  | "flow_studio.modal.run_detail.events.container"
  // Wisdom UI in Run Detail Modal
  | "flow_studio.modal.run_detail.wisdom"
  | "flow_studio.modal.run_detail.wisdom.toggle"
  | "flow_studio.modal.run_detail.wisdom.container"
  | "flow_studio.modal.run_detail.wisdom.summary"
  | "flow_studio.modal.run_detail.wisdom.empty"
  // Context Budget Modal
  | "flow_studio.modal.context_budget"
  | "flow_studio.modal.context_budget.close"
  | "flow_studio.modal.context_budget.effective"
  | "flow_studio.modal.context_budget.profile_form"
  | "flow_studio.modal.context_budget.reset"
  | "flow_studio.modal.context_budget.save"
  // Context Budget Header Control
  | "flow_studio.header.context_budget"
  | "flow_studio.header.context_budget.trigger"
  // Boundary Review
  | "flow_studio.boundary_review.panel"
  | "flow_studio.boundary_review.content"
  | "flow_studio.boundary_review.container"
  | "flow_studio.boundary_review.approve"
  | "flow_studio.boundary_review.pause";

/**
 * Query an element by its data-uiid attribute with type safety.
 * Returns null if not found.
 *
 * @example
 * const searchInput = qsByUiid("flow_studio.header.search.input");
 * if (searchInput) searchInput.focus();
 */
export function qsByUiid<T extends HTMLElement = HTMLElement>(
  id: FlowStudioUIID
    | `flow_studio.canvas.outline.${"flow" | "step" | "agent" | "artifact"}:${string}`
    | `flow_studio.inventory.type.${string}`
    | `flow_studio.inventory.flow.${string}`
): T | null {
  return document.querySelector<T>(`[data-uiid="${id}"]`);
}

/**
 * Query all elements matching a data-uiid prefix.
 * Useful for dynamic IDs like "flow_studio.canvas.outline.step:*".
 *
 * @example
 * const steps = qsAllByUiidPrefix("flow_studio.canvas.outline.step:");
 */
export function qsAllByUiidPrefix<T extends HTMLElement = HTMLElement>(
  prefix: string
): NodeListOf<T> {
  return document.querySelectorAll<T>(`[data-uiid^="${prefix}"]`);
}

// ============================================================================
// Flow Studio SDK (Agent-Facing API)
// ============================================================================

/**
 * UI readiness states signaled via data-ui-ready attribute on <html>.
 *
 * - "loading": Initialization in progress
 * - "ready": UI fully initialized, SDK available
 * - "error": Initialization failed
 */
export type UIReadyState = "loading" | "ready" | "error";

/**
 * Check if the Flow Studio UI is ready for interaction.
 * @returns true if data-ui-ready="ready" on <html>
 */
export function isUIReady(): boolean {
  return document.documentElement.dataset.uiReady === "ready";
}

/**
 * Check if the Flow Studio UI failed to initialize.
 * @returns true if data-ui-ready="error" on <html>
 */
export function isUIError(): boolean {
  return document.documentElement.dataset.uiReady === "error";
}

/**
 * Get the current UI readiness state.
 * @returns "loading" | "ready" | "error"
 */
export function getUIReadyState(): UIReadyState {
  return (document.documentElement.dataset.uiReady as UIReadyState) || "loading";
}

/**
 * Wait for the Flow Studio UI to be ready.
 * Resolves when data-ui-ready="ready", rejects if "error" or timeout.
 *
 * @param timeoutMs - Maximum time to wait (default: 10000ms)
 * @returns Promise that resolves with the SDK when ready
 * @throws Error if UI fails to initialize or times out
 *
 * @example
 * // In test or automation code:
 * try {
 *   const sdk = await waitForUIReady();
 *   await sdk.setActiveFlow("build");
 * } catch (err) {
 *   console.error("Flow Studio failed to initialize", err);
 * }
 */
export async function waitForUIReady(timeoutMs = 10000): Promise<FlowStudioSDK> {
  const startTime = Date.now();

  return new Promise((resolve, reject) => {
    // Check immediately
    const state = getUIReadyState();
    if (state === "ready" && window.__flowStudio) {
      return resolve(window.__flowStudio);
    }
    if (state === "error") {
      return reject(new Error("Flow Studio initialization failed"));
    }

    // Set up polling
    const checkInterval = 100;
    const check = (): void => {
      const elapsed = Date.now() - startTime;
      const currentState = getUIReadyState();

      if (currentState === "ready" && window.__flowStudio) {
        resolve(window.__flowStudio);
        return;
      }
      if (currentState === "error") {
        reject(new Error("Flow Studio initialization failed"));
        return;
      }
      if (elapsed >= timeoutMs) {
        reject(new Error(`Flow Studio initialization timed out after ${timeoutMs}ms (state: ${currentState})`));
        return;
      }

      setTimeout(check, checkInterval);
    };

    setTimeout(check, checkInterval);
  });
}

/**
 * Safely get the Flow Studio SDK, returning null if not ready.
 * Use this for code that should gracefully handle the SDK being unavailable.
 *
 * @returns The SDK if ready, null otherwise
 *
 * @example
 * const sdk = getSDKIfReady();
 * if (sdk) {
 *   // Use SDK
 * } else {
 *   // Graceful fallback
 * }
 */
export function getSDKIfReady(): FlowStudioSDK | null {
  return isUIReady() ? window.__flowStudio || null : null;
}

// ============================================================================
// Layout Spec Types (for SDK extension)
// ============================================================================

/**
 * Layout region identifiers.
 */
export type LayoutRegionId =
  | "header"
  | "sidebar"
  | "canvas"
  | "inspector"
  | "modal"
  | "sdlc_bar";

/**
 * Screen identifiers for Flow Studio.
 */
export type ScreenId =
  | "flows.default"
  | "flows.validation"
  | "flows.selftest"
  | "flows.tour"
  | "flows.shortcuts";

/**
 * A layout region within a screen.
 */
export interface LayoutRegion {
  id: LayoutRegionId;
  purpose: string;
  uiids: FlowStudioUIID[];
}

/**
 * A screen specification in the layout registry.
 */
export interface ScreenSpec {
  id: ScreenId;
  route: string;
  title: string;
  description: string;
  regions: LayoutRegion[];
}

/**
 * Public SDK interface for agents and automation.
 * Exposed on window.__flowStudio for programmatic access.
 *
 * This is the stable, typed surface that agents can rely on.
 *
 * VERSION: 0.5.0-flowstudio (adds layout spec methods)
 */
export interface FlowStudioSDK {
  /** Current UI state (read-only snapshot) */
  getState(): {
    currentFlowKey: FlowKey | null;
    currentRunId: string | null;
    currentMode: UIMode;
    currentViewMode: ViewMode;
    selectedNodeId: string | null;
    selectedNodeType: NodeType | null;
  };

  /** Get serialized graph state (for snapshots) */
  getGraphState(): GraphState | null;

  /** Navigate to a specific flow */
  setActiveFlow(flowKey: FlowKey): Promise<void>;

  /** Select a step by flow key and step ID */
  selectStep(flowKey: FlowKey, stepId: string): Promise<void>;

  /** Select an agent by key, optionally in a specific flow */
  selectAgent(agentKey: string, flowKey?: FlowKey): Promise<void>;

  /** Clear the current selection */
  clearSelection(): void;

  /** Query element by typed UIID */
  qsByUiid: typeof qsByUiid;

  /** Query elements by UIID prefix */
  qsAllByUiidPrefix: typeof qsAllByUiidPrefix;

  // =========================================================================
  // Layout Spec (v0.5.0-flowstudio)
  // =========================================================================

  /** Get all registered screens */
  getLayoutScreens(): ScreenSpec[];

  /** Get a specific screen by ID */
  getLayoutScreenById(id: ScreenId): ScreenSpec | null;

  /** Get all known UIIDs across all screens */
  getAllKnownUIIDs(): FlowStudioUIID[];

  // =========================================================================
  // Teaching Mode (v0.6.0-flowstudio)
  // =========================================================================

  /** Get the current Teaching Mode state */
  getTeachingMode(): boolean;

  /** Set the Teaching Mode state */
  setTeachingMode(enabled: boolean): void;

  // =========================================================================
  // Context Budget Settings (v0.7.0-flowstudio)
  // =========================================================================

  /** Get current effective context budgets (resolved through cascade) */
  getContextBudgets(): ContextBudgetConfig;

  /** Update profile-level context budgets */
  setContextBudgets(budgets: Partial<ContextBudgetOverride>): Promise<void>;

  /** Open the context budget settings modal */
  openContextBudgetModal(): void;
}
