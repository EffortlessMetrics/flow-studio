# Schema Documentation: Flow Studio SpecManager

This document describes the data models, relationships, and operational patterns for the Flow Studio SpecManager API.

---

## Overview

The SpecManager is the backend service that powers the Flow Studio TypeScript frontend. It provides:

1. **Spec Management**: CRUD operations for FlowGraphs and StepTemplates
2. **Validation**: Dry-run validation of spec changes
3. **Compilation**: Preview PromptPlan compilation from specs
4. **Run State**: Execution state management with GPS-style detour routing
5. **Event Streaming**: Server-Sent Events for real-time run updates

---

## Architecture Layers

```
+---------------------------+
|     TypeScript Frontend   |  <-- Flow Studio UI (React Flow)
+---------------------------+
            |
            | REST API + SSE
            v
+---------------------------+
|      SpecManager API      |  <-- This API (api_contracts.yaml)
+---------------------------+
            |
            | Load / Validate / Compile
            v
+---------------------------+
|      Python Kernel        |  <-- swarm/spec/loader.py, compiler.py
+---------------------------+
            |
            | Read / Write
            v
+---------------------------+
|      Spec Files (YAML)    |  <-- swarm/spec/stations/*.yaml, flows/*.yaml
+---------------------------+
            |
            | Validate Against
            v
+---------------------------+
|    JSON Schemas           |  <-- swarm/spec/schemas/*.json
+---------------------------+
```

---

## Core Data Models

### 1. FlowGraph

**Schema**: `flow_graph.schema.json`

A FlowGraph represents an orchestration graph for stepwise flow execution. It maps 1:1 to React Flow's node/edge format.

**Key Properties**:
- `id`: Unique identifier (kebab-case, e.g., `build-flow`)
- `version`: Integer version for change tracking
- `flow_number`: SDLC flow number (1=Signal, 2=Plan, 3=Build, 4=Gate, 5=Deploy, 6=Wisdom)
- `nodes[]`: Graph nodes representing steps
- `edges[]`: Connections between nodes
- `policy`: Execution constraints (max iterations, timeouts, escalation)
- `subflows[]`: Collapsible groupings for microloops

**Relationships**:
```
FlowGraph
    |
    +-- nodes[] --> GraphNode --> StepTemplate (via template_id)
    |                   |
    |                   +-- params (step-specific overrides)
    |                   +-- ui (position, color, teaching notes)
    |
    +-- edges[] --> GraphEdge
    |                   |
    |                   +-- condition (routing logic)
    |                   +-- type (sequence, loop, branch, detour)
    |
    +-- policy --> GraphPolicy
    |                   |
    |                   +-- suggested_detours[] (advisory, not restrictive)
    |                   +-- routing_decisions (CONTINUE, DETOUR, INJECT_FLOW, INJECT_NODES, EXTEND_GRAPH)
    |                   +-- escalation rules
    |
    +-- subflows[] --> Subflow (microloop groupings)
```

---

### 2. StepTemplate

**Schema**: `step_template.schema.json`

A StepTemplate is a reusable blueprint that users drag onto the flow canvas. Templates encapsulate common patterns (critics, implementers, scanners) with parameterized objectives.

**Key Properties**:
- `id`: Unique identifier (kebab-case, e.g., `code-critic-template`)
- `station_id`: Reference to underlying station spec
- `objective`: Parameterized objective with `{{placeholder}}` substitution
- `routing_defaults`: Default behavior (linear, microloop, branch)
- `ui_defaults`: Visual configuration for canvas rendering
- `parameters`: JSON Schema for user-configurable options
- `constraints`: Usage restrictions (allowed flows, predecessors, singleton)

**Objective Substitution**:
```yaml
objective:
  template: "Review {{artifact_type}} for {{quality_criteria}}"
  default_params:
    artifact_type: "code changes"
    quality_criteria: "correctness and maintainability"
```

User provides `artifact_type: "API handlers"` and final objective becomes:
`"Review API handlers for correctness and maintainability"`

---

### 3. PromptPlan

**Schema**: `prompt_plan.schema.json`

A PromptPlan is the compiled output ready for Claude SDK execution. It contains fully resolved prompts and SDK options with complete traceability.

**Key Properties**:
- `system_prompt`: Preset + station-specific append
- `user_prompt`: Objective + context + output requirements
- `output_format`: Handoff contract (path, required fields)
- `sdk_options`: Model, tools, permissions, sandbox config
- `traceability`: Station version, flow version, prompt hash

**Compilation Process**:
```
FlowSpec + StepSpec + StationSpec
            |
            v
      [SpecCompiler]
            |
            +-- Resolve station reference
            +-- Merge step overrides
            +-- Render {{templates}}
            +-- Resolve fragment paths
            +-- Compute prompt hash
            |
            v
      PromptPlan (ready for SDK)
```

---

### 4. RunState

**Schema**: `run_state.schema.json`

RunState is the durable program counter for stepwise flow execution. It enables resumption, GPS-style detour routing, and version consistency validation.

**Key Properties**:
- `run_id`: Unique identifier (format: `run-YYYYMMDD-HHMMSS-random`)
- `flow_key`: Current flow being executed
- `current_step_id`: Step currently executing
- `status`: Execution status (pending, running, succeeded, failed, etc.)
- `interruption_stack[]`: Active detours (GPS rerouting)
- `resume_stack[]`: Saved positions for resumption
- `spec_versions`: Captured hashes for drift detection
- `injected_nodes[]`: Dynamic nodes added during execution

---

## Relationship Between Specs and Runtime

### Design Time vs Runtime

| Aspect | Design Time | Runtime |
|--------|-------------|---------|
| Data | FlowGraph, StepTemplate | RunState, HandoffEnvelope |
| Storage | YAML files in `swarm/spec/` | JSON files in `swarm/runs/{run_id}/` |
| Mutability | Versioned, human-editable | Append-only, machine-managed |
| Validation | JSON Schema + reference checks | Handoff contract validation |

### Spec-to-Runtime Flow

```
1. User designs flow in UI
   |
   v
2. FlowGraph saved to swarm/spec/flows/{flow_id}.yaml
   |
   v
3. Run created: POST /runs
   |
   v
4. SpecCompiler loads FlowGraph + Templates
   |
   v
5. For each step:
   a. Compile PromptPlan
   b. Execute via Claude SDK
   c. Receive HandoffEnvelope
   d. Update RunState
   e. Evaluate routing (next step, loop, branch, terminate)
   |
   v
6. Run completes: status = succeeded/failed
```

---

## Optimistic Concurrency with ETags

### Overview

All mutable resources use **optimistic concurrency control** via HTTP ETags. This prevents lost updates when multiple clients edit the same resource.

### How It Works

```
Client A                    Server                      Client B
   |                          |                            |
   |--- GET /flows/build ---->|                            |
   |<-- 200 + ETag: "abc" ----|                            |
   |                          |                            |
   |                          |<-- GET /flows/build -------|
   |                          |--- 200 + ETag: "abc" ----->|
   |                          |                            |
   |--- PATCH (If-Match: "abc") -->|                       |
   |<-- 200 + ETag: "def" ----|                            |
   |                          |                            |
   |                          |<-- PATCH (If-Match: "abc") |
   |                          |--- 409 Conflict ---------->|
   |                          |                            |
```

### ETag Generation

ETags are computed as SHA-256 hashes of the canonical JSON representation:

```python
import hashlib
import json

def compute_etag(resource: dict) -> str:
    canonical = json.dumps(resource, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]
```

### API Usage

**Reading a Resource**:
```http
GET /api/spec/flows/build-flow HTTP/1.1
Host: localhost:5000
```

```http
HTTP/1.1 200 OK
ETag: "abc123def456"
Content-Type: application/json

{
  "id": "build-flow",
  "version": 1,
  ...
}
```

**Updating a Resource**:
```http
PATCH /api/spec/flows/build-flow HTTP/1.1
Host: localhost:5000
If-Match: "abc123def456"
Content-Type: application/json-patch+json

[{"op": "replace", "path": "/nodes/0/ui/position", "value": {"x": 100, "y": 200}}]
```

**Success**:
```http
HTTP/1.1 200 OK
ETag: "def456ghi789"
Content-Type: application/json

{...updated resource...}
```

**Conflict**:
```http
HTTP/1.1 409 Conflict
Content-Type: application/json

{
  "error": "ETAG_MISMATCH",
  "message": "Flow has been modified since your last read",
  "details": {
    "expected_etag": "abc123def456",
    "current_etag": "xyz789abc123"
  }
}
```

### TypeScript Client Pattern

```typescript
async function updateFlow(flowId: string, patch: JsonPatch[]): Promise<FlowGraph> {
  // 1. Fetch current state with ETag
  const response = await fetch(`/api/spec/flows/${flowId}`);
  const etag = response.headers.get('ETag');
  const flow = await response.json();

  // 2. Apply patch with If-Match
  const updateResponse = await fetch(`/api/spec/flows/${flowId}`, {
    method: 'PATCH',
    headers: {
      'Content-Type': 'application/json-patch+json',
      'If-Match': etag!,
    },
    body: JSON.stringify(patch),
  });

  // 3. Handle conflict
  if (updateResponse.status === 409) {
    const conflict = await updateResponse.json();
    throw new ETagConflictError(conflict);
  }

  return updateResponse.json();
}
```

---

## Validation Pipeline

### Validation Levels

The API supports four validation levels, each building on the previous:

| Level | Checks | Use Case |
|-------|--------|----------|
| `schema` | JSON Schema validation | Syntax correctness |
| `references` | + Station exists, fragment paths valid | Basic integrity |
| `routing` | + Next steps exist, loop targets valid | Flow consistency |
| `full` | + Cross-flow dependencies, constraint checking | Production readiness |

### Validation Request

```json
{
  "spec_type": "flow",
  "spec": {
    "id": "custom-flow",
    "version": 1,
    "title": "Custom Flow",
    "flow_number": 3,
    "nodes": [...],
    "edges": [...]
  },
  "level": "full",
  "context": {
    "existing_templates": ["code-critic", "test-author"]
  }
}
```

### Validation Response

```json
{
  "valid": false,
  "errors": [
    {
      "code": "VAL-020",
      "message": "Station 'nonexistent-station' not found",
      "path": "/nodes/0/template_id",
      "severity": "error",
      "suggestion": "Did you mean 'code-critic'?"
    }
  ],
  "warnings": [
    {
      "code": "VAL-101",
      "message": "Flow has no terminal node",
      "path": "/nodes",
      "severity": "warning",
      "suggestion": "Add a node with routing_defaults.kind='terminal'"
    }
  ],
  "checked_at": "2025-12-28T10:00:00Z"
}
```

### Validation Codes

| Code | Severity | Description |
|------|----------|-------------|
| VAL-001 | error | Required field missing |
| VAL-002 | error | Invalid field type |
| VAL-003 | error | Value outside allowed range |
| VAL-010 | error | Invalid identifier format |
| VAL-020 | error | Referenced station not found |
| VAL-021 | error | Referenced template not found |
| VAL-022 | error | Referenced fragment not found |
| VAL-030 | error | Invalid routing target |
| VAL-031 | error | Loop target not reachable |
| VAL-040 | error | Constraint violation (singleton, max instances) |
| VAL-100 | warning | Deprecated template used |
| VAL-101 | warning | No terminal node defined |
| VAL-102 | warning | Unreachable node detected |

---

## Compilation Process

### Overview

Compilation transforms a FlowStep (design-time) into a PromptPlan (runtime-ready). The process is deterministic and produces a prompt hash for reproducibility.

### Compilation Request

```json
{
  "flow_id": "build-flow",
  "step_id": "author_tests",
  "run_context": {
    "run_id": "run-20251228-100000-abc123",
    "run_base": "swarm/runs/preview-run",
    "iteration": 2
  },
  "include_context_pack": true,
  "template_overrides": {
    "quality_criteria": "security vulnerabilities"
  }
}
```

### Compilation Steps

1. **Load Specs**: FlowSpec, StepSpec, StationSpec
2. **Resolve Template**: Apply step overrides to template defaults
3. **Render Objective**: Substitute `{{placeholders}}` with values
4. **Load Fragments**: Concatenate prompt fragments
5. **Build System Prompt**: Preset + station identity + invariants
6. **Build User Prompt**: Objective + context + output requirements
7. **Resolve SDK Options**: Model, tools, permissions
8. **Compute Prompt Hash**: SHA-256 of combined prompts
9. **Build Traceability**: Station version, flow version, step ID

### Compilation Output

```json
{
  "system_prompt": {
    "preset": "claude_code",
    "append": "You are the **Test Author**...",
    "combined": "...",
    "invariants": ["Never skip tests", "Cover edge cases"],
    "tone": "analytical"
  },
  "user_prompt": {
    "objective": "Write tests for the authentication module",
    "scope": "AC-001..AC-003",
    "context_section": "## Upstream Artifacts\n...",
    "combined": "..."
  },
  "output_format": {
    "handoff_path": "swarm/runs/preview-run/build/test_author_handoff.json",
    "required_fields": ["status", "summary", "artifacts"],
    "status_values": ["VERIFIED", "UNVERIFIED", "BLOCKED"]
  },
  "sdk_options": {
    "model": "claude-sonnet-4-20250514",
    "model_tier": "sonnet",
    "permission_mode": "bypassPermissions",
    "tools": {
      "allowed": ["Read", "Write", "Bash", "Grep", "Glob"]
    },
    "max_turns": 12
  },
  "traceability": {
    "station_id": "test-author",
    "station_version": 1,
    "template_id": "test-author-template",
    "flow_id": "3-build",
    "flow_version": 1,
    "step_id": "author_tests",
    "prompt_hash": "a7b3c9d2e4f5...",
    "compiled_at": "2025-12-28T10:00:00Z",
    "run_id": "run-20251228-100000-abc123",
    "iteration": 2
  }
}
```

---

## Event Streaming (SSE)

### Overview

The `/runs/{run_id}/events` endpoint provides real-time updates via Server-Sent Events. This enables the UI to display live execution progress.

### Event Types

| Event | Description | Payload |
|-------|-------------|---------|
| `state_change` | Run status or step changed | `{run_id, status, current_step_id}` |
| `step_started` | Step execution began | `{step_id, station_id, timestamp}` |
| `step_completed` | Step execution finished | `{step_id, status, duration_ms, artifacts}` |
| `handoff_received` | Handoff envelope received | `{step_id, status, summary}` |
| `routing_decision` | Routing decision made | `{from_step, to_step, decision, reason}` |
| `detour_started` | Detour sequence began | `{interruption_id, detour_steps}` |
| `detour_completed` | Detour sequence finished | `{interruption_id, resume_step}` |
| `error` | Error occurred | `{step_id, error, message}` |
| `metrics_update` | Metrics updated | `{steps_completed, duration_ms, tokens}` |

### SSE Message Format

```
event: step_completed
id: evt-002
data: {"step_id":"author_tests","status":"VERIFIED","duration_ms":45000}

event: routing_decision
id: evt-003
data: {"from_step":"author_tests","to_step":"critique_tests","decision":"advance","reason":"linear_routing"}

```

### TypeScript Client

```typescript
const eventSource = new EventSource(`/api/runs/${runId}/events`);

eventSource.addEventListener('step_completed', (event) => {
  const data = JSON.parse(event.data);
  console.log(`Step ${data.step_id} completed: ${data.status}`);
});

eventSource.addEventListener('routing_decision', (event) => {
  const data = JSON.parse(event.data);
  highlightEdge(data.from_step, data.to_step);
});

eventSource.onerror = () => {
  console.error('SSE connection lost, reconnecting...');
};
```

### Reconnection

Include `Last-Event-ID` header to resume from a specific event:

```typescript
const eventSource = new EventSource(`/api/runs/${runId}/events`, {
  headers: {
    'Last-Event-ID': 'evt-042'
  }
});
```

---

## GPS-Style Detour Routing

### Overview

Runs can be interrupted and detoured, similar to GPS navigation rerouting around obstacles. The `interruption_stack` and `resume_stack` enable nested detours with proper resumption.

### Detour Sequence

```
Normal Route:        A -> B -> C -> D -> E
                          |
Detour Triggered:         +----> X -> Y -> Z
                                          |
Resume:                   B <-------------+
                          |
Continue:                 +-> C -> D -> E
```

### API Flow

1. **Trigger Interruption**: `POST /runs/{run_id}/interrupt`
   - Saves current position to `resume_stack`
   - Pushes interruption to `interruption_stack`
   - Status changes to `interrupted`

2. **Execute Detour**: Normal step execution through detour steps

3. **Resume**: `POST /runs/{run_id}/resume`
   - Pops from `interruption_stack`
   - Pops from `resume_stack`
   - Continues from saved position

### Nested Detours

Multiple detours can nest. The stacks handle arbitrary depth:

```yaml
interruption_stack:
  - id: "int-1"  # First detour
    detour_steps: ["X", "Y"]
  - id: "int-2"  # Nested detour (triggered during Y)
    detour_steps: ["P", "Q"]

resume_stack:
  - interruption_id: "int-1"  # Resume after int-1
    step_id: "B"
  - interruption_id: "int-2"  # Resume after int-2
    step_id: "Y"
```

---

## Schema File Locations

| Schema | Path | Purpose |
|--------|------|---------|
| FlowGraph | `swarm/spec/schemas/flow_graph.schema.json` | Flow orchestration graph |
| StepTemplate | `swarm/spec/schemas/step_template.schema.json` | Reusable step blueprints |
| PromptPlan | `swarm/spec/schemas/prompt_plan.schema.json` | Compiled SDK-ready prompts |
| RunState | `swarm/spec/schemas/run_state.schema.json` | Execution state |
| HandoffEnvelope | `swarm/spec/schemas/handoff_envelope.schema.json` | Step output contract |
| RoutingSignal | `swarm/spec/schemas/routing_signal.schema.json` | Routing decisions |

---

## API Contract Location

**File**: `swarm/plan/api_contracts.yaml`

**OpenAPI Version**: 3.0.3

**Namespace**: Flow Studio SpecManager API v2.0.0

---

## Migration Notes

### Backward Compatibility

New fields in schemas have sensible defaults:

| Schema | New Fields | Defaults |
|--------|------------|----------|
| RunState | `interruption_stack` | `[]` |
| RunState | `resume_stack` | `[]` |
| RunState | `spec_versions` | `null` |
| RunState | `injected_nodes` | `[]` |
| RunState | `routing_cursor` | `null` |
| RunState | `metrics` | `null` |
| FlowGraph | `policy.suggested_detours` | `[]` |
| FlowGraph | `policy.routing_decisions` | `["CONTINUE"]` |
| FlowGraph | `subflows` | `[]` |

Existing JSON files load without error. The Python loader and TypeScript client check for field presence before using them.

### Version Bumps

When making breaking changes:
1. Bump schema version in `$id` field
2. Update `version` field in affected specs
3. Update API version in `api_contracts.yaml`
4. Document migration path in this file

---

## References

- ADR-001: Spec-First Architecture (`docs/adr/ADR-001-spec-first-architecture.md`)
- Flow Graph Schema (`swarm/spec/schemas/flow_graph.schema.json`)
- Step Template Schema (`swarm/spec/schemas/step_template.schema.json`)
- Prompt Plan Schema (`swarm/spec/schemas/prompt_plan.schema.json`)
- Run State Schema (`swarm/spec/schemas/run_state.schema.json`)
- API Contracts (`swarm/plan/api_contracts.yaml`)
