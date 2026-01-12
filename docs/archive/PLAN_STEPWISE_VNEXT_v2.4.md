# Stepwise vNext: Executable Graph IR Plan

> **Archived:** This v2.4 planning document is superseded by [ARCHITECTURE.md](../ARCHITECTURE.md) and [ROUTING_PROTOCOL.md](./ROUTING_PROTOCOL.md). Kept for historical reference.

> For: Core team driving spec system → production execution
>
> **Status:** Planning | **Owner:** TBD | **Target:** v2.4.0
>
> **Related:** [STEPWISE_BACKENDS.md](../STEPWISE_BACKENDS.md) | [RUNTIME_ENGINE_PLAN.md](../RUNTIME_ENGINE_PLAN.md)

---

## Executive Summary

The 7-flow spec library exists. The smart routing logic exists. The gap is making the **spec the single executable graph IR** that the orchestrator and UI both treat as the authoritative map—with detours, policy, and auditability built in.

**Core trade:** Spend compute to save senior engineer attention. Optimize for receipts and auditability, not speed.

---

## Priority Levels

| Priority | Theme | Risk Mitigation |
|----------|-------|-----------------|
| **P0** | Merge hygiene + correctness | Safe to iterate |
| **P1** | Canonical spec IR | UI edits what orchestrator runs |
| **P2** | Smart routing | Bounded, auditable, cheap |
| **P3** | SDK alignment | Fewer sessions, cleaner control |
| **P4** | UI: graph editor + run control | Thin client, Python kernel |

---

## P0 — Merge Hygiene + Correctness

**Goal:** PRs reviewable, builds repeatable, no hidden landmines.

### P0.1 Split the Mega-PR

- [ ] Separate "spec system" from "engine refactor" from "telemetry"
- [ ] Each PR ≤ 50 files (review tools skip at 150+)
- [ ] If one branch, merge in slices with clear commit boundaries

**Files to audit:**
```bash
git diff --stat main | head -20  # Check file counts
```

### P0.2 Remove Local Artifacts + Lock Down `.gitignore`

- [ ] Delete any `impl_changes_summary.md`, `test_output.log`, Windows path-named files
- [ ] Update `.gitignore` with patterns:

```gitignore
# P0.2: Local artifacts
*_summary.md
*.log
test_output*
*.pyc
__pycache__/
.pytest_cache/
```

**Grep-able check:**
```bash
git ls-files | grep -E "(summary\.md|\.log|test_output)"
# Should return empty
```

### P0.3 Kill Circular Imports

- [ ] Fix `context_pack.py` importing `StepContext` from package root
- [ ] Import from direct type source: `swarm/runtime/engines/models.py`
- [ ] Add `TYPE_CHECKING` gates where needed

**Files to fix:**
```
swarm/runtime/context_pack.py
swarm/runtime/engines/__init__.py
swarm/runtime/types.py
```

**Grep-able invariant:**
```bash
grep -r "from swarm.runtime import StepContext" swarm/
# Should return empty (import from engines/models.py instead)
```

### P0.4 Centralize Flow ID Mapping

- [ ] Create single function: `get_flow_spec_id(flow_key: str) -> str`
- [ ] Location: `swarm/config/flow_registry.py`
- [ ] Replace all inline maps in orchestrator, spec_adapter, loader

**Grep for duplicates:**
```bash
grep -rn "signal.*spec-signal\|plan.*spec-plan" swarm/
# All matches should delegate to flow_registry
```

**Target API:**
```python
# swarm/config/flow_registry.py
def get_flow_spec_id(flow_key: str) -> str:
    """Map flow key to spec ID. Single source of truth."""
    FLOW_TO_SPEC = {
        "signal": "spec-signal",
        "plan": "spec-plan",
        "build": "spec-build",
        "gate": "spec-gate",
        "deploy": "spec-deploy",
        "wisdom": "spec-wisdom",
    }
    return FLOW_TO_SPEC[flow_key]
```

### P0.5 Template Extraction

- [ ] Move router prompt template to `swarm/prompts/router.md`
- [ ] Move finalization template to `swarm/prompts/finalize.md`
- [ ] Load templates at runtime, not string literals in code

**Files to create:**
```
swarm/prompts/
├── router.md
├── finalize.md
└── README.md
```

**Grep-able check:**
```bash
grep -rn "ROUTER_PROMPT_TEMPLATE\|FINALIZE_TEMPLATE" swarm/runtime/
# Should show only loading code, not inline definitions
```

### P0 Acceptance Criteria

```bash
# All must pass
git status                          # Clean working tree
uv run pytest tests/ -x             # Tests pass without special env
python -c "from swarm.runtime import *"  # No import cycles
grep -r "flow.*=.*{" swarm/runtime/ | wc -l  # ≤ 1 (centralized mapping)
```

---

## P1 — Canonical Spec IR: JSON + Fragments + Overlays

**Goal:** UI edits what the orchestrator runs, with strict validation and stable hashing.

### P1.1 Make JSON Canonical

- [ ] Store Stations/Templates/FlowGraph as JSON (not YAML at runtime)
- [ ] YAML only as import format (optional), never runtime truth
- [ ] Canonicalize JSON (sorted keys) before hashing

**File structure:**
```
swarm/specs/
├── stations/
│   ├── station-signal-normalizer.json
│   ├── station-problem-framer.json
│   └── ...
├── templates/
│   ├── template-writer-reviewer-loop.json
│   └── ...
├── flows/
│   ├── spec-signal.json
│   ├── spec-plan.json
│   └── ...
└── schemas/
    ├── station.schema.json
    ├── template.schema.json
    └── flow_graph.schema.json
```

**Canonicalization function:**
```python
# swarm/runtime/spec_system/canonical.py
import json
import hashlib

def canonical_json(obj: dict) -> str:
    """Return deterministic JSON string."""
    return json.dumps(obj, sort_keys=True, separators=(',', ':'))

def spec_hash(obj: dict) -> str:
    """Return stable hash of spec object."""
    return hashlib.sha256(canonical_json(obj).encode()).hexdigest()[:12]
```

### P1.2 Keep Prose in Markdown Fragments

- [ ] StationSpec/TemplateSpec reference fragment IDs/paths
- [ ] Compiler resolves fragments → PromptPlan

**Fragment structure:**
```
swarm/specs/fragments/
├── signal/
│   ├── normalize-context.md
│   ├── normalize-task.md
│   └── normalize-output-format.md
├── plan/
│   └── ...
└── shared/
    ├── evidence-requirements.md
    └── handoff-format.md
```

**Spec reference:**
```json
{
  "station_id": "station-signal-normalizer",
  "prompt_fragments": {
    "context": "fragments/signal/normalize-context.md",
    "task": "fragments/signal/normalize-task.md",
    "output": "fragments/signal/normalize-output-format.md"
  }
}
```

### P1.3 Separate Logic Graph from UI Overlay

- [ ] `flow_graph.json` = nodes/edges + routing policy
- [ ] `flow_graph.ui.json` = positions, colors, icons, palette metadata
- [ ] Python merges for UI, shreds on save

**Graph structure:**
```json
// spec-signal.json (logic)
{
  "spec_id": "spec-signal",
  "nodes": [...],
  "edges": [...],
  "routing_policy": {...}
}

// spec-signal.ui.json (overlay)
{
  "spec_id": "spec-signal",
  "node_positions": {
    "normalize": {"x": 100, "y": 50},
    "frame": {"x": 300, "y": 50}
  },
  "theme": "default"
}
```

### P1.4 ETag + Patch Semantics

- [ ] Server returns ETag header with spec responses
- [ ] UI sends `If-Match` header with updates
- [ ] Support JSON Patch (`application/json-patch+json`) and Merge Patch
- [ ] Server validates schema + invariants before write

**API endpoints:**
```
GET  /api/specs/{spec_id}              → 200 + ETag
PUT  /api/specs/{spec_id}              → 200 (full replace) + If-Match required
PATCH /api/specs/{spec_id}             → 200 (JSON Patch) + If-Match required
GET  /api/specs/{spec_id}/validate     → 200/400 (dry-run validation)
```

**Invariant checks on save:**
```python
def validate_flow_graph(graph: dict) -> list[str]:
    """Return list of validation errors (empty = valid)."""
    errors = []

    # All edges reference valid nodes
    node_ids = {n["id"] for n in graph["nodes"]}
    for edge in graph["edges"]:
        if edge["from"] not in node_ids:
            errors.append(f"Edge references unknown source: {edge['from']}")
        if edge["to"] not in node_ids:
            errors.append(f"Edge references unknown target: {edge['to']}")

    # Exactly one START node
    starts = [n for n in graph["nodes"] if n.get("type") == "START"]
    if len(starts) != 1:
        errors.append(f"Expected 1 START node, found {len(starts)}")

    # At least one END node
    ends = [n for n in graph["nodes"] if n.get("type") == "END"]
    if len(ends) < 1:
        errors.append("No END node found")

    return errors
```

### P1 Acceptance Criteria

```bash
# Round-trip test
python -c "
from swarm.runtime.spec_system import load_spec, save_spec, spec_hash
original = load_spec('spec-signal')
save_spec(original)
reloaded = load_spec('spec-signal')
assert spec_hash(original) == spec_hash(reloaded), 'Hash mismatch after round-trip'
print('P1: Round-trip OK')
"

# UI never reads files directly
grep -r "open.*\.json\|read.*\.json" swarm/tools/flow_studio_ui/
# Should return empty (UI uses API only)
```

---

## P2 — Smart Routing: Bounded, Auditable, Cheap

**Goal:** "GPS routing" without turning the router into an unbounded storyteller.

### P2.1 Routing Explanations: Small + Typed JSON

- [ ] Keep explanations to structured fields, not verbose prose
- [ ] Max lengths enforced in schema

**Schema:**
```json
{
  "decision_type": "deterministic|exit_condition|cel|llm_tiebreaker",
  "reason_code": "LOOP_EXIT_VERIFIED|EDGE_CONDITION_TRUE|LLM_CHOICE",
  "reason_text": "string (max 100 chars)",
  "evidence_pointers": ["receipts/step-1.json:verified"],
  "alternatives_considered": [
    {"edge_id": "e2", "eliminated_reason": "condition false"}
  ],
  "decision_metrics": {
    "candidates_count": 3,
    "decision_time_ms": 45
  }
}
```

### P2.2 Deterministic First, LLM Last

- [ ] Implement routing priority chain:
  1. Hard constraints (schema violations, missing inputs)
  2. Exit conditions (microloop termination)
  3. Edge conditions (CEL expressions)
  4. LLM tie-breaker (only if >1 candidate)

**Router implementation:**
```python
# swarm/runtime/engines/claude/router.py
def smart_route(context: RouterContext, edges: list[Edge]) -> RoutingSignal:
    """Priority-based routing. LLM only as last resort."""

    # 1. Check hard constraints
    blocked_edges = [e for e in edges if not e.constraints_satisfied(context)]
    candidates = [e for e in edges if e not in blocked_edges]

    if len(candidates) == 0:
        return RoutingSignal(decision_type="blocked", ...)

    # 2. Check exit conditions (microloop)
    for edge in candidates:
        if edge.is_exit_edge and context.exit_condition_met():
            return RoutingSignal(decision_type="exit_condition", edge=edge, ...)

    # 3. Check edge conditions (CEL)
    for edge in candidates:
        if edge.condition and eval_cel(edge.condition, context):
            return RoutingSignal(decision_type="cel", edge=edge, ...)

    # 4. If single candidate, take it
    if len(candidates) == 1:
        return RoutingSignal(decision_type="deterministic", edge=candidates[0], ...)

    # 5. LLM tie-breaker (>1 candidate, no conditions matched)
    return llm_tiebreak(context, candidates)
```

### P2.3 Real Condition DSL (CEL Subset)

- [ ] Implement CEL evaluator for edge conditions
- [ ] Constrained subset: comparisons, logical ops, field access
- [ ] Evaluate over compact `RouterContext`

**Supported CEL expressions:**
```cel
# Simple comparisons
verification_status == "VERIFIED"
loop_count >= 3
confidence_score > 0.8

# Logical operators
verification_status == "VERIFIED" || loop_count >= 3
has_errors == false && confidence_score > 0.7

# Field access
receipt.status == "VERIFIED"
handoff.metrics.token_count < 10000
```

**RouterContext schema:**
```python
@dataclass
class RouterContext:
    """Compact context for routing decisions."""
    verification_status: str  # VERIFIED | UNVERIFIED | BLOCKED
    loop_count: int
    max_iterations: int
    confidence_score: float
    has_errors: bool
    receipt: dict  # Last step receipt
    handoff: dict  # Handoff envelope summary
    candidate_edges: list[str]  # Edge IDs still valid
```

### P2.4 Detours as First-Class

- [ ] Implement `interruption_stack` in orchestrator state
- [ ] Implement `resume_stack` for return points
- [ ] Add operator injection endpoints

**Orchestrator state:**
```python
@dataclass
class OrchestratorState:
    current_node: str
    interruption_stack: list[InterruptionFrame]  # LIFO
    resume_stack: list[ResumePoint]  # Where to return after detour

@dataclass
class InterruptionFrame:
    injected_node: str
    injected_by: str  # "operator" | "policy" | "error_handler"
    original_edge: str  # What we were about to take
    timestamp: datetime

@dataclass
class ResumePoint:
    node_id: str
    edge_id: str
    context_snapshot: dict
```

**API endpoints:**
```
POST /api/runs/{run_id}/inject    → Inject a detour node
POST /api/runs/{run_id}/interrupt → Pause at current step
POST /api/runs/{run_id}/resume    → Resume from interruption
GET  /api/runs/{run_id}/stack     → View interruption/resume stacks
```

### P2 Acceptance Criteria

```bash
# Routing decisions are replayable
python -c "
from swarm.runtime.engines.claude.router import smart_route, RouterContext
ctx = RouterContext(verification_status='VERIFIED', loop_count=2, ...)
signal = smart_route(ctx, edges)
assert signal.decision_type in ('deterministic', 'exit_condition', 'cel', 'llm_tiebreaker')
assert len(signal.explanation.reason_text) <= 100
print('P2: Routing OK')
"

# LLM tie-break outputs are schema-valid
uv run pytest tests/test_spec_system.py -k "routing" -v
```

---

## P3 — SDK Alignment: Use Features That Matter

**Goal:** Stop fighting the SDK's model; use it to keep "hot context" and increase control.

### P3.1 Prefer ClaudeSDKClient for Multi-Turn Steps

- [ ] One session per step (not per turn)
- [ ] Session structure: Work turn(s) → Finalize turn → Optional route turn
- [ ] Preserve hot context within step

**Session pattern:**
```python
async def run_step_with_sdk(step: StepSpec, context: StepContext) -> StepResult:
    """Run step with multi-turn session."""
    async with ClaudeSDKClient() as client:
        session = await client.create_session(
            system_prompt=step.system_prompt,
            tools=step.allowed_tools,
        )

        # Work turn(s) - may iterate
        work_result = await session.send(step.work_prompt)
        while not work_result.is_complete:
            work_result = await session.send("Continue...")

        # Finalize turn - structured output
        handoff = await session.send(
            step.finalize_prompt,
            output_format=HandoffSchema,
        )

        return StepResult(work=work_result, handoff=handoff)
```

### P3.2 Use `output_format` for High Leverage

- [ ] Router output: enforce JSON schema validation
- [ ] Handoff output: schema-validated response → Python writes file
- [ ] Agent still uses tools for work; finalization is structured

**Where to use `output_format`:**
```python
# Router output (no tools needed)
routing_response = await session.send(
    "Choose next edge from candidates...",
    output_format=RoutingDecisionSchema,
)

# Handoff finalization
handoff_response = await session.send(
    "Summarize your work for the next agent...",
    output_format=HandoffEnvelopeSchema,
)
```

### P3.3 Hooks and `can_use_tool` as High-Trust Guardrails

- [ ] Don't use restrictive allowlists (too fragile)
- [ ] Implement "block obviously destructive" + "force evidence"
- [ ] PreToolUse: block dangerous commands
- [ ] PostToolUse: append tool events / evidence pointers

**Hook implementations:**
```python
# swarm/runtime/hooks/safety.py
BLOCKED_PATTERNS = [
    r"rm\s+-rf\s+/",
    r"git\s+push\s+--force",
    r"DROP\s+TABLE",
    r"password|secret|api.?key",  # In file writes
]

def pre_tool_use(tool_name: str, args: dict) -> HookResult:
    """Block obviously destructive operations."""
    if tool_name == "bash":
        for pattern in BLOCKED_PATTERNS:
            if re.search(pattern, args.get("command", ""), re.IGNORECASE):
                return HookResult.BLOCK(f"Blocked: matches {pattern}")

    if tool_name == "write":
        path = args.get("path", "")
        if not path.startswith(ALLOWED_WRITE_ROOTS):
            return HookResult.BLOCK(f"Write outside allowed roots: {path}")

    return HookResult.ALLOW()

def post_tool_use(tool_name: str, args: dict, result: dict) -> None:
    """Record tool usage as evidence."""
    emit_event("tool_use", {
        "tool": tool_name,
        "args_hash": hash_args(args),
        "result_summary": summarize(result),
        "timestamp": now(),
    })
```

### P3.4 Sandbox as Defense-in-Depth

- [ ] Use SDK sandbox settings for command containment
- [ ] Treat permission rules + hooks as primary control
- [ ] Sandbox is backup, not only wall

**Sandbox configuration:**
```python
session_config = SessionConfig(
    sandbox=SandboxConfig(
        enabled=True,
        allowed_paths=[
            "/workspace/**",
            RUN_BASE + "/**",
        ],
        blocked_commands=["curl", "wget", "ssh"],
    ),
    hooks=HookConfig(
        pre_tool_use=pre_tool_use,
        post_tool_use=post_tool_use,
    ),
)
```

### P3 Acceptance Criteria

```bash
# Session count per step
python -c "
from swarm.runtime.engines.claude import ClaudeStepEngine
# Each step should create exactly 1 session
# Verify in logs/metrics
"

# Hooks are registered
grep -r "pre_tool_use\|post_tool_use" swarm/runtime/
# Should show hook registration in engine setup
```

---

## P4 — UI: Graph Editor + Run Control Room

**Goal:** TS is pure frontend; Python is the kernel.

### P4.1 Palette from StepTemplateSpec

- [ ] `GET /api/templates` → grouped palette data
- [ ] Drag/drop creates nodes with defaults + parameter forms
- [ ] Templates define parameter schemas for forms

**API response:**
```json
{
  "groups": [
    {
      "id": "microloops",
      "label": "Microloops",
      "templates": [
        {
          "template_id": "template-writer-reviewer-loop",
          "label": "Writer-Reviewer Loop",
          "icon": "loop",
          "parameters": {
            "max_iterations": {"type": "integer", "default": 3},
            "exit_on_verified": {"type": "boolean", "default": true}
          }
        }
      ]
    }
  ]
}
```

### P4.2 Flow Validation is Server-Side

- [ ] On every save: server validates schema + invariants
- [ ] UI shows validation errors but doesn't compute them
- [ ] `POST /api/specs/{id}/validate` for dry-run

**Validation response:**
```json
{
  "valid": false,
  "errors": [
    {"path": "edges[2].to", "message": "References unknown node: xyz"},
    {"path": "nodes", "message": "Missing required START node"}
  ],
  "warnings": [
    {"path": "nodes[5]", "message": "Node has no outgoing edges (dead end)"}
  ]
}
```

### P4.3 Run View is Projection-Driven

- [ ] SSE streaming from DuckDB projection
- [ ] Node "pulse" = `route_decision` events + step status
- [ ] Click node → narrative summary, evidence, routing audit, tool stats

**SSE event stream:**
```
event: step_start
data: {"step_id": "normalize", "timestamp": "...", "agent": "signal-normalizer"}

event: tool_use
data: {"step_id": "normalize", "tool": "read", "path": "input.md"}

event: route_decision
data: {"from": "normalize", "to": "frame", "decision_type": "deterministic"}

event: step_end
data: {"step_id": "normalize", "status": "VERIFIED", "duration_ms": 4500}
```

**Node detail panel:**
```typescript
interface NodeDetail {
  step_id: string;
  status: "pending" | "running" | "verified" | "unverified" | "blocked";
  narrative_summary: string;  // From handoff
  evidence_pointers: string[];
  routing_audit: RoutingExplanation;
  tool_stats: {
    read_count: number;
    write_count: number;
    bash_count: number;
    total_duration_ms: number;
  };
}
```

### P4.4 Live Detours

- [ ] Injected nodes appear dashed in UI
- [ ] Resume points visible with indicator
- [ ] UI can trigger interrupt/inject/resume

**UI state for detours:**
```typescript
interface RunState {
  current_node: string;
  interruption_stack: Array<{
    injected_node: string;
    original_edge: string;
    injected_by: "operator" | "policy";
  }>;
  resume_points: Array<{
    node_id: string;
    edge_id: string;
  }>;
}

// Node styling
function getNodeStyle(node: Node, runState: RunState): NodeStyle {
  if (runState.interruption_stack.some(f => f.injected_node === node.id)) {
    return { border: "dashed", opacity: 0.8, badge: "INJECTED" };
  }
  if (runState.resume_points.some(p => p.node_id === node.id)) {
    return { badge: "RESUME" };
  }
  return { border: "solid" };
}
```

### P4 Acceptance Criteria

```bash
# UI never reads files directly
grep -r "fs\.\|readFile\|writeFile" swarm/tools/flow_studio_ui/src/
# Should return empty (use API only)

# Run playback is instant
# Measure: Load run with 100 events < 200ms from DuckDB projection
```

---

## Strategic Lock-In: 3-Layer Model

Keep optional at runtime for flexibility:

```
┌─────────────────────────────────────────────────────────────────┐
│                     StepTemplateSpec                            │
│  (UI/palette blueprint + parameter schema + grouping)           │
│  - Helps humans design flows                                    │
│  - Optional at runtime                                          │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                       StationSpec                               │
│  (Runtime profile + invariants + verification expectations)     │
│  - Required for execution                                       │
│  - Defines agent behavior constraints                           │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                        FlowGraph                                │
│  (Executable map: nodes + edges + routing policy)               │
│  - The actual runtime artifact                                  │
│  - Nodes reference station_id OR template_id                    │
└─────────────────────────────────────────────────────────────────┘
```

**Key insight:** A node can reference `template_id` (expands to full config) or `station_id` directly (raw execution). This keeps the orchestrator simple while giving the UI a real library system.

---

## PR Sequence

| PR | Scope | Depends On | Files |
|----|-------|------------|-------|
| PR-1 | P0.1-P0.3: Hygiene | None | `.gitignore`, imports |
| PR-2 | P0.4-P0.5: Centralize | PR-1 | `flow_registry.py`, `swarm/prompts/` |
| PR-3 | P1.1-P1.2: JSON canonical | PR-2 | `swarm/specs/`, schemas |
| PR-4 | P1.3-P1.4: Overlays + ETag | PR-3 | API endpoints, UI updates |
| PR-5 | P2.1-P2.2: Smart routing | PR-3 | `router.py`, schemas |
| PR-6 | P2.3-P2.4: CEL + detours | PR-5 | `cel.py`, orchestrator |
| PR-7 | P3.1-P3.4: SDK alignment | PR-5 | `ClaudeStepEngine`, hooks |
| PR-8 | P4.1-P4.4: UI features | PR-4, PR-6 | Flow Studio TS |

---

## Test Matrix

| Feature | Unit Test | Integration Test | E2E Test |
|---------|-----------|------------------|----------|
| Flow ID mapping | `test_flow_registry.py` | — | — |
| JSON canonicalization | `test_canonical.py` | — | — |
| Spec round-trip | `test_spec_system.py` | — | — |
| CEL evaluation | `test_cel.py` | — | — |
| Smart routing | `test_router.py` | `test_routing_integration.py` | — |
| Detour injection | `test_detours.py` | `test_detour_integration.py` | `e2e/detours.spec.ts` |
| ETag semantics | — | `test_api_etag.py` | — |
| SSE streaming | — | `test_sse.py` | `e2e/run_streaming.spec.ts` |

---

## Appendix: Grep-able Invariants

Quick checks to verify implementation:

```bash
# P0: No duplicate flow mappings
grep -rn "signal.*spec-signal" swarm/ | wc -l  # Should be 1

# P0: No inline prompt templates
grep -rn "PROMPT_TEMPLATE\s*=" swarm/runtime/ | wc -l  # Should be 0

# P1: All specs are JSON
find swarm/specs -name "*.yaml" | wc -l  # Should be 0

# P1: All specs have hashes
grep -L "spec_hash" swarm/specs/**/*.json | wc -l  # Should be 0

# P2: Router uses priority chain
grep -A20 "def smart_route" swarm/runtime/engines/claude/router.py | grep -c "# 1\|# 2\|# 3\|# 4"  # Should be 4

# P3: Hooks are registered
grep -r "pre_tool_use" swarm/runtime/engines/ | wc -l  # Should be ≥ 1

# P4: UI uses API only
grep -r "readFileSync\|writeFileSync" swarm/tools/flow_studio_ui/ | wc -l  # Should be 0
```

---

## Revision History

| Date | Version | Changes |
|------|---------|---------|
| 2025-12-28 | 0.1 | Initial plan from architecture review |
