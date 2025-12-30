# ADR-002: Graph-Native Flow Representation

**Status:** Proposed
**Date:** 2025-12-28
**Deciders:** Flow Studio Team

## Context

Flow Studio requires explicit graph representation for orchestration flows to support:

1. **React Flow Visualization**: The UI uses React Flow (via Cytoscape.js currently) to render flows as interactive node graphs. Linear step lists in YAML require transformation logic to derive implicit edges.

2. **Bounded Routing**: Stepwise orchestrators need explicit edge conditions (microloops, branches, detours) to make routing decisions. Currently, routing is embedded in step definitions with `routing.kind`, `routing.loop_target`, etc., which conflates topology with step metadata.

3. **Visual Editing**: Future authoring workflows need a canonical graph format that round-trips between visual editors and YAML definitions without lossy transformations.

4. **Policy Enforcement**: Detours, injections, and escalation rules need explicit graph topology to validate that edges are legal and bounded.

### Current State

**YAML Flow Definitions** (`swarm/config/flows/*.yaml`):
```yaml
steps:
  - id: author_tests
    agents: [test-author]
    routing:
      kind: linear
      next: critique_tests
  - id: critique_tests
    agents: [test-critic]
    routing:
      kind: microloop
      loop_target: author_tests
      next: implement
```

- Edges are implicit (derived from `routing.next` and `routing.loop_target`)
- Topology is scattered across step definitions
- No explicit node positions for layout
- No edge metadata (conditions, UI styling)

**TypeScript Domain Types** (`swarm/tools/flow_studio_ui/src/domain.ts`):
```typescript
interface FlowGraphNode {
  data: { id: string; type: NodeType; label: string; ... }
}
interface FlowGraphEdge {
  data: { id: string; type: EdgeType; source: string; target: string; }
}
```

- Already graph-shaped for Cytoscape consumption
- Transformation happens at runtime in Python backend

**JSON Schema** (`swarm/spec/schemas/flow_graph.schema.json`):
- Comprehensive GraphIR specification already exists
- Defines `nodes[]`, `edges[]`, `policy{}`, `subflows[]`
- Maps directly to React Flow concepts
- Includes edge conditions, UI styling, policy constraints

## Decision

We adopt **Graph-Native Flow Representation** using the canonical GraphIR format defined in `swarm/spec/schemas/flow_graph.schema.json` as the authoritative representation for flow topology.

### Core GraphIR Structure

```json
{
  "id": "build-flow",
  "version": 1,
  "title": "Flow 3 - Build",
  "flow_number": 3,
  "nodes": [
    {
      "node_id": "author_tests",
      "template_id": "test-author",
      "params": { "objective": "Write tests based on BDD scenarios" },
      "ui": { "type": "step", "position": { "x": 100, "y": 200 } }
    }
  ],
  "edges": [
    {
      "edge_id": "e-tests-to-critique",
      "from": "author_tests",
      "to": "critique_tests",
      "type": "sequence"
    },
    {
      "edge_id": "e-loop-back",
      "from": "critique_tests",
      "to": "author_tests",
      "type": "loop",
      "condition": { "field": "status", "operator": "equals", "value": "UNVERIFIED" }
    }
  ],
  "policy": {
    "max_loop_iterations": 3,
    "allowed_injections": [{ "station_id": "clarifier", "inject_after": ["*"] }]
  }
}
```

### Key Design Principles

1. **Explicit Edges**: All transitions are first-class edge objects with `from`, `to`, optional `condition`, and `type` (sequence, loop, branch, detour).

2. **Nodes Reference Templates**: `template_id` points to agent/station definitions; `params` customize the instance. This separates topology from agent behavior.

3. **Policy is Declarative**: `policy{}` defines what routing is legal (max iterations, allowed detours, escalation rules). Orchestrators enforce; the schema validates.

4. **1:1 React Flow Mapping**: GraphIR maps directly to React Flow's `Node[]` and `Edge[]` arrays. No transformation logic needed in the UI layer.

5. **UI Metadata is Optional**: `ui{}` blocks contain positions, colors, labels, teaching notes. Absent UI blocks use auto-layout and defaults.

### Migration Path

| Phase | State | Format |
|-------|-------|--------|
| Current | YAML flows with implicit edges | `swarm/config/flows/*.yaml` |
| Intermediate | YAML + generated GraphIR | Both formats, GraphIR derived at build time |
| Target | GraphIR as source of truth | `swarm/spec/flows/*.flow.json` |

- **Phase 1**: Build tooling to generate GraphIR from existing YAML
- **Phase 2**: Flow Studio reads GraphIR directly; YAML becomes legacy
- **Phase 3**: Visual editor writes GraphIR; YAML generated for backward compatibility

## Alternatives Considered

### Option A: Linear Step Lists (Status Quo)

Keep the current YAML format where steps are an ordered list and edges are derived from `routing.*` properties.

**Rejected because:**
- Implicit graph requires transformation logic
- Loop targets and branch conditions are scattered across steps
- No explicit edge representation for complex routing
- Difficult to validate topology invariants
- Visual editor round-trip would be lossy

### Option B: Database Workflow Engines

Use a workflow engine (Temporal, Airflow, n8n) that stores flows in a database with native graph support.

**Rejected because:**
- Over-engineering for the demo harness scope
- Adds external service dependencies (violates "works on clone")
- Workflow engines optimize for execution, not visualization
- Would require mapping their graph model to React Flow anyway
- Loses the "files-as-source-of-truth" philosophy

### Option C: Hybrid Dual Source of Truth

Maintain both YAML steps and a separate `topology.yaml` file defining edges.

**Rejected because:**
- Two sources of truth for the same concept
- Synchronization burden on every edit
- Validation must span multiple files
- Authoring experience is fragmented
- GraphIR already solves this with a single canonical format

## Consequences

### Positive

1. **Direct Visualization**: GraphIR feeds directly to React Flow without transformation. The Python backend serves `nodes[]` and `edges[]` as-is.

2. **Visual Editing**: A future graph editor can read and write GraphIR. Round-trip fidelity is guaranteed because the format matches the visual model.

3. **Explicit Topology**: Loops, branches, detours are visible as edges with conditions. Reviewing a flow's routing is reading edges, not tracing `routing.*` fields.

4. **Bounded Routing Enforcement**: Policy constraints (max iterations, allowed detours) are declarative. Orchestrators query policy before taking edges. Invalid routes fail schema validation.

5. **Subflow Composition**: The `subflows[]` array enables collapsible groups (e.g., "Test Microloop" containing author and critic). Visual hierarchy matches logical grouping.

### Negative

1. **Migration Effort**: Existing YAML flows must be converted. Tool to generate GraphIR from YAML is required.

2. **Larger Files**: GraphIR is more verbose than compact YAML. A 12-step flow's GraphIR may be 3-5x larger in bytes.

3. **JSON vs YAML Authoring**: JSON is less human-friendly for hand-editing. Mitigated by:
   - Visual editor for most edits
   - YAML->JSON tooling for migration
   - JSON with comments (JSON5) if needed

4. **Schema Versioning**: GraphIR `version` field must be managed. Breaking changes require migration tooling.

### Risks

| Risk | Mitigation |
|------|------------|
| GraphIR schema evolves incompatibly | Version field + migration scripts in `swarm/tools/` |
| Visual editor introduces invalid graphs | JSON Schema validation on save; CI validates all `*.flow.json` |
| Performance with large graphs | Lazy loading by flow; pagination of runs |
| Backward compatibility with YAML consumers | Generate YAML from GraphIR during transition; deprecate YAML after stabilization |

## References

- **GraphIR Schema**: `swarm/spec/schemas/flow_graph.schema.json` (canonical specification)
- **TypeScript Types**: `swarm/tools/flow_studio_ui/src/domain.ts` (UI contract)
- **Current YAML Flows**: `swarm/config/flows/*.yaml` (to be migrated)
- **React Flow**: https://reactflow.dev/ (target visualization library)
- **ADR-001**: Swarm Selftest scope (established ADR pattern for this repo)

## Related Work

- Flow 2 (Plan) produces design artifacts; GraphIR could represent dependency graphs in ADRs
- Flow 6 (Wisdom) analyzes flow execution; GraphIR enables topology-aware regression detection
- Stepwise orchestrators already use routing signals; GraphIR formalizes edge conditions
