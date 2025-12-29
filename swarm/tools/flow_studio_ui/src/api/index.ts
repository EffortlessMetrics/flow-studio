// swarm/tools/flow_studio_ui/src/api/index.ts
// API exports for Flow Studio UI
//
// Pure HTTP/SSE client layer. NO filesystem operations.

export {
  // Main client class
  FlowStudioAPI,
  flowStudioApi,

  // Error types
  ConflictError,

  // Types
  type Template,
  type TemplateCategory,
  type TemplateNode,
  type TemplateEdge,
  type CompiledFlow,
  type RunState,
  type RunInfo,
  type NodeSpec,
  type ETagResponse,
  type SSEEventType,
  type SSEEvent,

  // New types for spec system
  type PatchOperation,
  type RunStateData,
  type RunActionResponse,
  type InjectNodeRequest,
  type InterruptRequest,
} from "./client.js";
