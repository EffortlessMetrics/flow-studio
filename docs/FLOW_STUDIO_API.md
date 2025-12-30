# Flow Studio API Reference

> **OpenAPI baseline**: `docs/flowstudio-openapi.json`
> **Live docs** (when Flow Studio is running):
> - Swagger UI: `http://localhost:5000/docs`
> - ReDoc: `http://localhost:5000/redoc`
> - Raw schema: `http://localhost:5000/openapi.json`

This document specifies the stable API contract for Flow Studio, supporting both external integrations and internal Flow Studio UI consumption. The JSON schema in `docs/flowstudio-openapi.json` is the source of truth for contracts and tooling.

**Status**: Stable (v2.0) — FastAPI backend only.

> **Note**: As of v2.2, Flow Studio uses FastAPI exclusively. The legacy Flask backend has been archived.

---

## Overview

Flow Studio provides a RESTful API for visualization and inspection of agentic SDLC flows, agents, artifacts, and selftest governance.

### Base URL

```
http://localhost:5000
```

### Response Format

All responses are JSON unless otherwise noted. Successful responses use HTTP 200; errors use appropriate 4xx/5xx codes with JSON error details.

---

## Key Endpoints

| Endpoint                    | Method | Purpose                                   |
|----------------------------|--------|-------------------------------------------|
| `/api/health`              | GET    | Basic health, flow/agent counts           |
| `/api/flows`               | GET    | List available flows                      |
| `/api/flows/{flow_key}`    | GET    | Flow detail (steps, agents, metadata)     |
| `/api/graph/{flow_key}`    | GET    | Graph nodes/edges for a flow              |
| `/api/runs`                | GET    | List known runs                           |
| `/api/runs/{run_id}/summary` | GET  | Run summary with artifacts                |
| `/api/runs/{run_id}/routing` | GET  | All routing decisions (including off-road)|
| `/api/runs/{run_id}/stack` | GET    | Flow execution stack state                |
| `/api/runs/{run_id}/boundary-review` | GET | Aggregated assumptions/decisions/detours |
| `/api/runs/{run_id}/wisdom/summary` | GET | Wisdom summary (Flow 6 analysis)    |
| `/api/selftest/plan`       | GET    | Selftest plan summary                     |
| `/platform/status`         | GET    | Governance status                         |
| `/api/profile`             | GET    | Current swarm profile                     |
| `/api/profiles`            | GET    | List available profiles                   |
| `/api/backends`            | GET    | List run backends and capabilities        |
| `/api/run`                 | POST   | Execute a stepwise run (UI-internal)      |
| `/api/runs/{run_id}/events`| GET    | SSE events stream for run (UI-internal)   |
| `/api/agents`              | GET    | List all agents                           |
| `/api/validation`          | GET    | Validation results                        |
| `/api/search`              | GET    | Search flows/agents/artifacts             |

> **Note**: Endpoints marked "(UI-internal)" are primarily consumed by the Flow Studio UI. They are stable but subject to more frequent iteration than public endpoints.

---

## Public Endpoints (Stable)

### Health & Capability Check

#### `GET /api/health`

Returns health status and server capabilities.

**Response (200)**:
```json
{
  "status": "ok",
  "flows": 7,
  "agents": 42,
  "capabilities": {
    "runs": true,
    "timeline": true,
    "governance": true,
    "validation": false
  }
}
```

**Stability**: Stable. Fields may be added; existing fields retain semantics.

---

### Flows & Graph Data

#### `GET /api/flows`

List all defined flows.

**Response (200)**:
```json
{
  "flows": [
    {
      "key": "signal",
      "title": "Signal → Specs",
      "description": "Shape the problem, identify stakeholders...",
      "step_count": 6
    },
    ...
  ]
}
```

#### `GET /api/graph/{flow_key}`

Get the flow graph (nodes and edges) for visualization.

**Parameters**:
- `flow_key`: Flow identifier (e.g., `signal`, `plan`, `build`, `review`, `gate`, `deploy`, `wisdom`)

**Response (200)**:
```json
{
  "nodes": [
    {
      "id": "step-id",
      "type": "step",
      "label": "Step label",
      "flow": "signal",
      "step_id": "step-id",
      "role": "Role description"
    },
    {
      "id": "agent-key",
      "type": "agent",
      "agent_key": "agent-key",
      "label": "Agent Name",
      "category": "shaping|spec|implementation|...",
      "model": "inherit|haiku|sonnet|opus",
      "short_role": "One-line role"
    },
    ...
  ],
  "edges": [
    {
      "id": "edge-id",
      "source": "node-id",
      "target": "node-id",
      "type": "step-sequence|step-agent|..."
    },
    ...
  ]
}
```

**Error (404)**:
```json
{
  "error": "Flow 'unknown' not found"
}
```

---

### Runs & Artifacts

#### `GET /api/runs`

List all available runs (active + examples).

**Response (200)**:
```json
{
  "runs": [
    {
      "id": "health-check",
      "type": "example",
      "timestamp": "2025-12-01T04:20:00+00:00",
      "status": "complete",
      "flow_status": {
        "signal": "complete",
        "plan": "complete",
        "build": "complete",
        "gate": "complete",
        "deploy": "complete",
        "wisdom": "complete"
      }
    },
    ...
  ]
}
```

#### `GET /api/runs/{run_id}/summary`

Get detailed run summary with artifact status.

**Parameters**:
- `run_id`: Run identifier (e.g., `health-check`, `ticket-123`)

**Response (200)**:
```json
{
  "id": "health-check",
  "type": "example",
  "timestamp": "2025-12-01T04:20:00+00:00",
  "flows": {
    "signal": {
      "status": "complete",
      "steps": {
        "signal-normalize": {
          "status": "complete",
          "artifacts": [
            {
              "path": "swarm/runs/health-check/signal/problem_statement.md",
              "status": "present",
              "required": true
            },
            ...
          ]
        },
        ...
      }
    },
    ...
  }
}
```

**Error (500)**:
```json
{
  "error": "Failed to load run summary"
}
```

#### `GET /api/runs/{run_id}/routing`

Returns all routing decisions made during a run, including off-road decisions.

**Parameters**:
- `run_id`: Run identifier

**Response (200)**:
```json
{
  "run_id": "ticket-123",
  "decisions": [
    {
      "step_id": "S4",
      "flow_key": "build",
      "timestamp": "2025-12-15T10:00:05Z",
      "route_type": "ADVANCE",
      "golden_path_step": "code-critic",
      "actual_step": "code-critic",
      "is_offroad": false,
      "confidence": 1.0,
      "reason": "Step completed successfully"
    },
    {
      "step_id": "S5",
      "flow_key": "build",
      "timestamp": "2025-12-15T10:05:10Z",
      "route_type": "DETOUR",
      "golden_path_step": "self-reviewer",
      "actual_step": "security-scanner",
      "is_offroad": true,
      "confidence": 0.85,
      "reason": "Detected potential SQL injection pattern",
      "return_address": "self-reviewer",
      "evaluated_conditions": ["has_db_queries == true"]
    }
  ],
  "summary": {
    "total_decisions": 12,
    "offroad_count": 2,
    "detour_count": 1,
    "inject_flow_count": 0,
    "inject_node_count": 1
  }
}
```

#### `GET /api/runs/{run_id}/stack`

Returns the current flow execution stack state for a run.

**Parameters**:
- `run_id`: Run identifier

**Response (200)**:
```json
{
  "run_id": "ticket-123",
  "current_depth": 2,
  "max_depth_reached": 2,
  "stack": [
    {
      "flow_key": "rebase",
      "state": "active",
      "started_at": "2025-12-15T10:10:00Z",
      "current_step": "conflict-resolver"
    },
    {
      "flow_key": "build",
      "state": "paused",
      "paused_at": "2025-12-15T10:09:55Z",
      "paused_step": "code-implementer",
      "resume_condition": "flow_completed",
      "injected_by": "stack_push at S6"
    }
  ],
  "events": [
    {
      "kind": "stack_push",
      "timestamp": "2025-12-15T10:09:55Z",
      "paused_flow": "build",
      "injected_flow": "rebase"
    }
  ]
}
```

**Response (200) - No stack (normal execution)**:
```json
{
  "run_id": "ticket-456",
  "current_depth": 1,
  "max_depth_reached": 1,
  "stack": [
    {
      "flow_key": "build",
      "state": "active",
      "started_at": "2025-12-15T09:00:00Z",
      "current_step": "code-critic"
    }
  ],
  "events": []
}
```

#### `GET /api/runs/{run_id}/boundary-review`

Returns aggregated boundary review data including assumptions, decisions, and detours.

**Parameters**:
- `run_id`: Run identifier
- `scope` (optional): `run` (default) or `flow`
- `flow_key` (optional): Required if `scope=flow`

**Response (200)**:
```json
{
  "run_id": "ticket-123",
  "scope": "run",
  "aggregated_at": "2025-12-15T10:30:00Z",
  "assumptions": [
    {
      "step_id": "S2",
      "flow_key": "signal",
      "assumption": "User wants React-based implementation",
      "basis": "Framework hints in issue description",
      "impact_if_wrong": "Would need to reimplement in different framework"
    }
  ],
  "decisions": [
    {
      "step_id": "S4",
      "flow_key": "build",
      "decision": "Used hook-based state management",
      "rationale": "Aligns with existing codebase patterns",
      "alternatives_considered": ["Redux", "Zustand"]
    }
  ],
  "detours": [
    {
      "step_id": "S5",
      "flow_key": "build",
      "route_type": "DETOUR",
      "from_step": "code-critic",
      "to_step": "security-scanner",
      "rationale": "Security concern detected",
      "returned": true,
      "return_step": "code-critic"
    }
  ],
  "summary": {
    "assumptions_count": 3,
    "decisions_count": 7,
    "detours_count": 1,
    "offroad_count": 1
  }
}
```

#### `GET /api/runs/{run_id}/wisdom/summary`

Returns the wisdom summary for a completed run. This endpoint surfaces Flow 6 (Prod -> Wisdom) analysis results.

**Parameters**:
- `run_id`: Run identifier (e.g., `health-check`, `ticket-123`)

**Response (200)**:
```json
{
  "run_id": "health-check",
  "flows": {
    "signal": {"status": "succeeded", "loop_counts": {}},
    "plan": {"status": "succeeded", "loop_counts": {}},
    "build": {"status": "succeeded", "loop_counts": {"test": 2, "code": 3}},
    "gate": {"status": "succeeded", "loop_counts": {}},
    "deploy": {"status": "succeeded", "loop_counts": {}},
    "wisdom": {"status": "succeeded", "loop_counts": {}}
  },
  "metrics": {
    "artifacts_present": 24,
    "regressions_found": 0,
    "learnings_count": 3,
    "feedback_actions_count": 2,
    "issues_created": 1
  },
  "labels": ["clean-run", "no-regressions"],
  "key_artifacts": [
    "wisdom/artifact_audit.md",
    "wisdom/regressions.md",
    "wisdom/learnings.md"
  ]
}
```

**Response (404)**:
```json
{
  "error": "Run 'unknown-run' not found or no wisdom_summary.json exists"
}
```

---

### Governance & Status

#### `GET /platform/status`

Current governance status across all flows and selftest.

**Response (200)**:
```json
{
  "timestamp": "2025-12-01T04:20:00+00:00",
  "service": "demo-swarm",
  "status": "healthy",
  "governance": {
    "kernel": {
      "status": "HEALTHY",
      "passed": 3,
      "failed": 0
    },
    "selftest": {
      "mode": "strict",
      "status": "GREEN",
      "kernel_ok": true,
      "governance_ok": true,
      "optional_ok": true,
      "failed_steps": []
    },
    "flows": {
      "healthy": 7,
      "degraded": 0,
      "broken": 0,
      "invalid_flows": []
    },
    "agents": {
      "total": 42,
      "healthy": 42,
      "misconfigured": 0,
      "unknown": 0
    }
  }
}
```

---

### Selftest Plan

#### `GET /api/selftest/plan`

Get the selftest execution plan with all steps, tiers, and dependencies.

**Response (200)**:
```json
{
  "version": "1.0",
  "steps": [
    {
      "id": "core-checks",
      "tier": "KERNEL",
      "severity": "CRITICAL",
      "category": "linting",
      "description": "Python lint (ruff) + compile check",
      "depends_on": []
    },
    {
      "id": "skills-governance",
      "tier": "GOVERNANCE",
      "severity": "WARNING",
      "category": "governance",
      "description": "Skills YAML validation",
      "depends_on": ["core-checks"]
    },
    ...
  ],
  "summary": {
    "total": 10,
    "by_tier": {
      "kernel": 3,
      "governance": 5,
      "optional": 2
    }
  }
}
```

**Stability**: Stable. Step count and content may evolve; use `id` field for stable reference.

**Error (503)**:
```json
{
  "error": "Selftest module not available"
}
```

---

### Agents

#### `GET /api/agents/{agent_key}/usage`

Get flow usage for a specific agent.

**Parameters**:
- `agent_key`: Agent identifier (e.g., `signal-normalizer`, `test-author`)

**Response (200)**:
```json
{
  "usage": [
    {
      "flow": "signal",
      "step": "normalize-input",
      "role": "Front-of-funnel parsing"
    },
    ...
  ]
}
```

---

### Tours (Optional)

#### `GET /api/tours`

List available interactive tours.

**Response (200)**:
```json
{
  "tours": [
    {
      "id": "quickstart",
      "title": "20-Minute Quickstart",
      "description": "Navigate all 7 flows in 20 minutes",
      "steps": 12
    },
    ...
  ]
}
```

#### `GET /api/tours/{tour_id}`

Get tour steps.

**Response (200)**:
```json
{
  "id": "quickstart",
  "title": "20-Minute Quickstart",
  "steps": [
    {
      "id": "tour-step-1",
      "title": "Welcome",
      "text": "This is Flow Studio...",
      "target": "#sidebar",
      "action": "highlight"
    },
    ...
  ]
}
```

---

## Design Patterns & Contracts

### Error Handling

All endpoints follow this error contract:

```json
{
  "error": "Human-readable error message"
}
```

HTTP status codes:
- **200**: Success
- **400**: Bad request (invalid parameter)
- **404**: Not found (resource doesn't exist)
- **500**: Server error (unexpected failure)
- **503**: Service unavailable (dependency missing)

### Field Stability

Documented endpoints follow this stability guarantee:

- **Stable fields**: Will not change semantics; may be removed only in major version
- **New fields**: May be added without warning; ignore unknown fields
- **Deprecated fields**: Marked in documentation with removal timeline

### Response Headers

All responses include:
- `Content-Type: application/json`
- `Access-Control-Allow-Origin: *` (CORS enabled)

---

## Integration Examples

### JavaScript / TypeScript

```typescript
// Fetch flow data
const flows = await fetch('/api/flows').then(r => r.json());

// Get selftest plan and render
const plan = await fetch('/api/selftest/plan').then(r => r.json());
plan.steps.forEach(step => {
  console.log(`${step.id} (${step.tier}): ${step.description}`);
});

// Monitor governance status
setInterval(async () => {
  const status = await fetch('/platform/status').then(r => r.json());
  console.log(`Governance: ${status.governance.selftest.status}`);
}, 5000);
```

### Python / Requests

```python
import requests

# Check health
health = requests.get('http://localhost:5000/api/health').json()
print(f"Agents: {health['agents']}")

# List runs
runs = requests.get('http://localhost:5000/api/runs').json()
for run in runs['runs']:
    print(f"{run['id']}: {run['status']}")

# Get governance status
status = requests.get('http://localhost:5000/platform/status').json()
print(f"Kernel: {status['governance']['kernel']['status']}")
```

### cURL

```bash
# Health check
curl http://localhost:5000/api/health | jq .

# List flows
curl http://localhost:5000/api/flows | jq '.flows[] | {key, title}'

# Get selftest plan
curl http://localhost:5000/api/selftest/plan | jq '.steps[] | {id, tier, description}'

# Monitor governance
watch -n 2 'curl -s http://localhost:5000/platform/status | jq .governance.selftest.status'
```

---

## Deployment & SLA

### Performance (Baseline)

- **Health check**: < 100ms
- **Flow listing**: < 200ms
- **Graph retrieval**: < 500ms (scales with flow size)
- **Selftest plan**: < 300ms (cached)
- **Governance status**: < 1s (validation-intensive)

### Availability

Flow Studio uses in-process state; no external services required.

- Single-process design (suitable for development, demos)
- For production: Deploy behind a load balancer, use read-only mounts for artifact inspection
- See `swarm/infrastructure/` for scaling patterns

---

## Changelog

### v2.0 (Current)

- FastAPI backend (default)
- Selftest plan endpoint (`GET /api/selftest/plan`)
- Stable API contract with documented error codes
- CORS support for external dashboards

### v1.0 (Archived)

- Flask backend (archived as of v2.2; see git history if needed)
- Basic flow visualization
- Run inspector

---

## See Also

- **[FLOW_STUDIO.md](../swarm/FLOW_STUDIO.md)** — UI and operator UX
- **[VALIDATION_RULES.md](./VALIDATION_RULES.md)** — Color / governance rules
- **[SELFTEST_SYSTEM.md](./SELFTEST_SYSTEM.md)** — How Flow Studio and selftest interact

---

## Support & Feedback

- **Issues**: Report at https://github.com/anthropics/claude-code/issues
- **Documentation**: See `docs/FLOW_STUDIO.md` for UI guide
- **Selftest System**: See `docs/SELFTEST_SYSTEM.md` for governance details
