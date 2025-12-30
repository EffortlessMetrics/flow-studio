# Flow Studio Architecture

**Status:** Phase 3 (Self-Healing Specs, Intelligent Routing)
**Last Updated:** 2025-12-29

Flow Studio is a Python orchestrator that drives stepwise LLM execution through a 7-flow SDLC pipeline. It manages state, calls Claude Code SDK for each step, and uses LLM intelligence for routing decisions.

For the operational philosophy, see [docs/AGOPS_MANIFESTO.md](./docs/AGOPS_MANIFESTO.md).
For canonical vocabulary (station, step, navigator, worker), see [docs/LEXICON.md](./docs/LEXICON.md).

---

## High-Level Design

The swarm is organized into **five layers**:

### 1. Spec Layer (`swarm/`)

**Source of truth** for the SDLC harness.

- **`AGENTS.md`** – canonical agent registry (name, role, flows, color, description)
- **`flows/flow-*.md`** – flow specifications (question, outputs, agents, orchestration)
- **`packs/`** – portable flow + station bundles (JSON specs)
- **`config/`** – registries (flow, pack, agent, runtime)
- **`tools/validate_swarm.py`** – validator enforcing spec + platform constraints
- **`runs/<run-id>/`** – concrete receipts from actual flow executions

### 2. Adapter Layer (`.claude/`)

**Platform-specific** implementation of the spec.

- `.claude/agents/*.md` – Claude Code agent definitions (YAML frontmatter + prompts)
- `.claude/commands/flow-*.md` – slash command entrypoints
- `.claude/skills/*/SKILL.md` – reusable capabilities

Generated from `swarm/config/` + templates via `make gen-adapters`.

### 3. Runtime Layer (`swarm/runtime/`)

**Execution engine** for stepwise orchestration.

- **`stepwise/`** – Step transaction types, orchestrator, routing
- **`macro_navigator.py`** – Between-flow routing with constraint DSL
- **`navigator.py`** – Within-flow routing (microloops, sidequests)
- **`station_library.py`** – Station templates with tunable parameters
- **`evolution.py`** – Policy-gated spec patches from Wisdom
- **`fact_extraction.py`** – Structured fact markers from handoffs
- **`resilient_db.py`** – Journal-first DuckDB with auto-rebuild

### 4. API Layer (`swarm/api/`)

**REST + SSE interface** for Flow Studio UI.

- **`routes/runs.py`** – Run management, start/stop/resume
- **`routes/events.py`** – SSE streaming of run events
- **`routes/boundary.py`** – Boundary review aggregation
- **`routes/facts.py`** – Fact marker queries
- **`routes/evolution.py`** – Spec evolution proposals
- **`routes/db.py`** – DuckDB health and rebuild

### 5. UI Layer (`swarm/tools/flow_studio_ui/`)

**Flow Studio** visualization and control.

- **`src/run_control.ts`** – SSE-driven state management
- **`src/components/InventoryCounts.ts`** – Real-time fact dashboard
- **`src/components/BoundaryReview.ts`** – Assumption/decision review
- **`src/components/FlowEditor.ts`** – Visual flow editing
- **`src/domain.ts`** – Canonical TypeScript types

---

## Terminology: The Execution Hierarchy

Understanding these terms prevents confusion between orchestration units and tool libraries.

### Core Concepts

| Term | Definition | Example |
|------|------------|---------|
| **Flow** | SDLC phase (1 of 7) | Signal, Plan, Build, Review, Gate, Deploy, Wisdom |
| **Step** | Position in a flow that executes a Station | "critique_tests" in Build flow |
| **Station** | Reusable execution capability with explicit contracts | `code-critic` station with I/O, SDK, invariants |
| **Subagent** | Helper callable *inside* a step via `Task` tool | `explore`, `plan-subagent`, or domain agents |

### The Hierarchy of Intelligence

Both **Steps** and **Subagents** are smart—they're full Claude Code orchestrators. The hierarchy separates concerns by scope and responsibility.

```
┌─────────────────────────────────────────────────────────────┐
│  Layer 1: ORCHESTRATOR (Python Kernel)                      │
│  Role: The Director                                         │
│  Scope: Entire Run                                          │
│  Manages: Time, Disk, Budget, Graph topology                │
│  Power: Spawns Steps, owns the event journal, never LLM     │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  Layer 2: STEP (Claude SDK Session)                         │
│  Role: The Manager                                          │
│  Scope: Single Station objective                            │
│  Manages: Logic, delegation, handoff synthesis              │
│  Power: Full orchestrator, delegates to Subagents           │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  Layer 3: SUBAGENT (Task Tool)                              │
│  Role: The Specialist                                       │
│  Scope: Specific mechanical operation                       │
│  Manages: Token-heavy mechanics (file reads, searches)      │
│  Power: Full orchestrator, returns distilled results        │
└─────────────────────────────────────────────────────────────┘
```

**Context Sharding: The Key Insight**

The hierarchy implements **context sharding**—distributing token load across isolated sessions:

| Layer | Holds | Delegates |
|-------|-------|-----------|
| Orchestrator | Run topology, budget | Step execution |
| Step | Logic, decisions, handoff | Mechanics to Subagents |
| Subagent | Focused task | Nothing (leaf node) |

**Why this matters:**
- **Steps maintain logic** while Subagents burn tokens on mechanics (reading files, running commands)
- **Steps don't get "drunk"** on grep output—the Subagent abstracts it away and returns distilled results
- **Parallel Subagent calls** let a Step fan out work without context explosion
- **Clean handoffs** preserve reasoning across the amnesia boundary

### Routing Philosophy: Suggested Detours, Not Allowlists

The V3 routing model treats routes as **hints, not constraints**. The Navigator has full off-road capability when the objective demands it.

| Principle | Implementation |
|-----------|----------------|
| **Suggested detours** | SidequestCatalog offers pre-planned routes, but doesn't constrain |
| **Off-road capable** | Can inject ad-hoc flows, create new steps when blocking |
| **Always spec'd** | Even improvised moves produce artifacts and receipts |
| **Goal-aligned** | Only deviate when standard path blocks the objective |

**The Navigator's Decision Space:**

```
┌─────────────────────────────────────────────────────────────┐
│                    Navigator Inputs                          │
├─────────────────────────────────────────────────────────────┤
│  1. Golden Path — standard outgoing edges (Build → Review)   │
│  2. Sidequest Catalog — pre-planned detours for this node    │
│  3. Forensics — evidence (git diff, test results, errors)    │
│  4. Objective — what the run is trying to achieve            │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                   Routing Decisions                          │
├─────────────────────────────────────────────────────────────┤
│  CONTINUE      — Proceed on golden path                      │
│  DETOUR        — Inject sidequest chain, return to path      │
│  INJECT_FLOW   — Inject a named pack flow (e.g., Flow 8)     │
│  INJECT_NODES  — Create ad-hoc spec-backed nodes             │
│  EXTEND_GRAPH  — Propose graph patch for future runs         │
└─────────────────────────────────────────────────────────────┘
```

**Sidequest Catalog** (`swarm/runtime/sidequest_catalog.py`):
- `clarifier` — resolve ambiguity
- `env-doctor` — diagnose environment issues
- `test-triage` — analyze failing tests
- `security-audit` — review sensitive paths
- `contract-check` — verify API contracts
- `context-refresh` — reload missing information

**Example Decision:**
- *Scenario:* Tests failed with `ModuleNotFound`
- *Forensics:* Stack trace shows missing dependency
- *Catalog offers:* `env-doctor`
- *Decision:* `DETOUR` to `env-doctor`, then return to golden path

### GitHub Lifecycle (V3 vs V4)

**V3 (Current): Synchronous Integration**
- Flows 1-2: `gh-researcher` pulls issues/comments *during* the step
- Flow 3: `repo-operator` pushes Draft PR *during* the step
- Flow 4: `feedback-harvester` pulls PR comments *during* the step
- The Orchestrator drives timing

**V4 (Future Vision): Asynchronous Integration**
- Webhooks push context to a living session as events arrive
- Flows react to external events, not poll for them
- Documented but not implemented in V3

### Graph-Native Mutation: Nested Flow Injection

The flow graph isn't static—it supports runtime mutation through a **Nested Graph Stack** model.

```
┌─────────────────────────────────────────────────────────────┐
│                   Graph Stack (Runtime)                      │
├─────────────────────────────────────────────────────────────┤
│  Level 0: Main SDLC Graph                                    │
│           [Signal] → [Plan] → [Build] → [Review] → ...       │
│                                  │                           │
│                                  │ INJECT_FLOW (Flow 8)      │
│                                  ▼                           │
│  Level 1: Injected Flow 8 (Security Audit)                   │
│           [scan] → [triage] → [remediate]                    │
│                       │                                      │
│                       │ INJECT_NODES (ad-hoc)                │
│                       ▼                                      │
│  Level 2: Ad-hoc Sidequest                                   │
│           [fetch-cve-details] → [assess-impact]              │
└─────────────────────────────────────────────────────────────┘
```

**Stack Operations:**

| Operation | Effect | Return Behavior |
|-----------|--------|-----------------|
| `PUSH` | Enter injected flow/nodes | Suspends parent graph position |
| `POP` | Complete injected work | Resumes parent at injection point |
| `INHERIT` | Child inherits parent's goal | Ensures alignment through nesting |

**Recursive Goal Inheritance:**

When Flow 3 (Build) injects Flow 8 (Security Audit):
1. Flow 8 inherits Flow 3's objective context
2. Flow 8's steps can access Flow 3's artifacts
3. Flow 8's outputs feed back into Flow 3's decision space
4. On completion, control returns to Flow 3's next step

**Why This Matters:**
- **Dynamic composition** — runs adapt to discovered requirements
- **Artifact continuity** — injected flows contribute to the same receipt chain
- **Bounded complexity** — stack depth limits prevent runaway injection

### Parallelism Principle: Fan Out for Independence

When operations are independent, **fan out to subagents in parallel**. This applies at both the Orchestrator and Step levels.

```
┌─────────────────────────────────────────────────────────────┐
│                 Step: Code Review                            │
├─────────────────────────────────────────────────────────────┤
│  Files to review: [auth.py, api.py, models.py, utils.py]     │
│                                                              │
│  Sequential (slow):                                          │
│    review(auth) → review(api) → review(models) → review(utils)│
│    Total time: 4 × T                                         │
│                                                              │
│  Parallel (fast):                                            │
│    ┌─ review(auth) ──┐                                       │
│    ├─ review(api) ───┤  All run simultaneously               │
│    ├─ review(models) ┤                                       │
│    └─ review(utils) ─┘                                       │
│    Total time: ~T                                            │
└─────────────────────────────────────────────────────────────┘
```

**When to Parallelize:**

| Parallel | Sequential |
|----------|------------|
| File reviews (independent) | Steps with dependencies |
| Test runs (isolated) | Git operations (serial) |
| Search queries (read-only) | Write operations (conflicts) |
| Lint checks (per-file) | Build then test (ordered) |

**Implementation:**
- Subagents are ideal parallelism units (isolated context)
- Use `Task` tool with multiple concurrent calls
- Aggregate results in the parent Step
- Handle partial failures gracefully

---

## v3.0 Architecture: The Cognitive Hierarchy

The system separates concerns across distinct cognitive roles:

```
┌─────────────────────────────────────────────────────────────┐
│                      Python Kernel                          │
│  (Factory Foreman - manages Time, Disk, Budget)             │
└─────────────────────────────────────────────────────────────┘
                              │
          ┌───────────────────┼───────────────────┐
          ▼                   ▼                   ▼
┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
│    Navigator    │ │     Worker      │ │    Curator      │
│ (Decide Path)   │ │   (Do Work)     │ │ (Pack Context)  │
└─────────────────┘ └─────────────────┘ └─────────────────┘
          │                   │                   │
          └───────────────────┼───────────────────┘
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                       The Disk                              │
│  (Ledger - events.jsonl, handoffs, artifacts)               │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                        DuckDB                               │
│  (Visibility Layer - projection of journal)                 │
└─────────────────────────────────────────────────────────────┘
```

### Role Definitions

| Role | Responsibility | Optimization |
|------|---------------|--------------|
| **Worker** | Implement code, write tests, fix lint | Full autonomy, broad tools |
| **Finalizer** | Summarize work, write handoff | Same-session (hot context) |
| **Navigator** | Analyze state, choose next step | Fresh session, minimal context |
| **Curator** | Select context for next station | Dedicated scoping logic |
| **Auditor** | Scan evidence, reconcile claims | Python-driven (deterministic) |

---

## Component Deep Dive

### Stepwise Orchestrator (`swarm/runtime/stepwise/`)

The step transaction abstraction that encapsulates all inputs and outputs:

```python
@dataclass
class StepTxnInput:
    repo_root: Path
    run_id: str
    flow_key: str
    step: StepDefinition
    spec: RunSpec
    history: List[Dict[str, Any]]
    run_state: Optional[RunState]
    routing_ctx: Optional[RoutingContext]

@dataclass
class StepTxnOutput:
    step_id: str
    status: str  # "succeeded" | "failed" | "skipped"
    envelope: Optional[HandoffEnvelope]
    routing_signal: Optional[RoutingSignal]
    verification: Optional[VerificationResult]
    events: List[RunEvent]
```

### MacroNavigator (`swarm/runtime/macro_navigator.py`)

Between-flow routing with constraint DSL:

```python
# Constraint patterns
"never deploy unless gate verdict is MERGE"
"max 3 bounces from gate to build"
"require human approval after flow 4"

# Actions
MacroAction.ADVANCE   # Go to next flow
MacroAction.GOTO      # Non-sequential jump
MacroAction.REPEAT    # Re-run same flow
MacroAction.PAUSE     # Wait for human
MacroAction.TERMINATE # End the run
```

### Resilient DB (`swarm/runtime/resilient_db.py`)

Journal-first design with auto-rebuild:

```python
# The events.jsonl is the append-only journal (authoritative)
# The DuckDB is a projection/cache that can be deleted and rebuilt

db = get_resilient_db()
stats = db.get_run_stats_safe(run_id)  # Never raises, returns None on error

# Health check and rebuild
health = db.get_health()
if health.needs_rebuild:
    db.rebuild()
```

### Evolution Engine (`swarm/runtime/evolution.py`)

Policy-gated spec patches from Wisdom:

```python
@dataclass
class EvolutionPatch:
    id: str                    # "FLOW-PATCH-001"
    target_file: str           # Relative path from repo root
    patch_type: PatchType      # flow_spec, station_spec, agent_prompt
    content: str               # Diff or JSON patch
    confidence: ConfidenceLevel
    reasoning: str
    evidence: List[str]
    human_review_required: bool
```

---

## Storage Architecture

### Journal-First Design

```
swarm/runs/<run-id>/
├── events.jsonl          # Append-only event journal (authoritative)
├── run_state.json        # Current run state snapshot
├── <flow>/
│   ├── receipts/         # Step receipts
│   ├── artifacts/        # Flow artifacts
│   ├── llm/              # LLM transcripts
│   └── handoffs/         # Step handoff envelopes
└── db.duckdb             # Projection (can be deleted and rebuilt)
```

### Event Types

```python
# Step events
"step_start"    # {flow_key, step_id, station_id}
"step_end"      # {flow_key, step_id, status, verified, progress}

# Flow events
"flow_completed"  # {flow_key, status}

# Run events
"run_completed"   # {status}
"run_stopping"    # {}
"run_stopped"     # {reason}
"run_paused"      # {}
"run_resumed"     # {}

# Fact events
"facts_updated"   # {flow_key, step_id, markers}
```

---

## Pack System

Packs are portable bundles of flows + stations:

```
swarm/packs/
├── baseline/
│   └── pack.yaml           # Pack manifest
├── flows/
│   ├── signal.json         # Flow 1 spec
│   ├── plan.json           # Flow 2 spec
│   ├── build.json          # Flow 3 spec
│   ├── review.json         # Flow 4 spec
│   ├── gate.json           # Flow 5 spec
│   ├── deploy.json         # Flow 6 spec
│   └── wisdom.json         # Flow 7 spec
└── stations/
    ├── workers.yaml        # Worker station templates
    ├── critics.yaml        # Critic station templates
    └── sidequests.yaml     # Sidequest station templates
```

### Station Templates

```yaml
# swarm/packs/stations/workers.yaml
code-implementer:
  model: sonnet
  context_budget: 80000
  tools: [Read, Write, Bash, Glob, Grep]
  verification:
    artifacts: [implementation.md, build_log.txt]
    commands: ["npm run build"]
  tunable:
    max_iterations: 5
    style_guide_path: null
```

---

## Phase Evolution

### Phase 0 (Complete) – Teaching Repo

- Single platform (Claude Code)
- Hand-maintained adapters
- Manual validation

### Phase 1 (Complete) – Explicit Configuration

- Machine-readable config (`swarm/config/`)
- Flow and agent registries
- Bijection validation

### Phase 2 (Complete) – Single-Platform Generation

- `gen_adapters.py` generates `.claude/agents/*.md`
- Prompts in `swarm/prompts/agents/`
- Templates in `swarm/templates/claude/`

### Phase 3 (Current) – Self-Healing Specs

- Pack system for portable flows
- MacroNavigator for intelligent routing
- Evolution engine for spec patches
- Resilient DB for journal-first storage
- Fact extraction for marker system

---

## Key Patterns

### The Amnesia Protocol

Every step starts fresh. No chat history accumulation.

```
Step N completes → Finalizer writes handoff.json
                 → Curator selects context for Step N+1
                 → Step N+1 starts with curated ContextPack
```

### Forensics Over Narrative

The Sheriff (DiffScanner, TestParser) verifies claims:

```python
# Don't trust: "Tests passed!"
# Verify: git diff --numstat, test_summary.json

forensics = DiffScanner.scan(repo_root)
# Navigator routes based on forensics, not worker claims
```

### Dynamic Navigation

The FlowGraph is the map; the Navigator traverses it with full routing authority:

```python
# Navigator sees:
# - FlowGraph (available paths + injected nodes)
# - Forensics (physical state: git diff, test results)
# - History (what's been tried, detour count)
# - Objective (run goal for alignment check)

decision = navigator.route(
    current_state=forensics,
    graph_stack=active_graphs,
    history=routing_history,
    objective=run_objective,
)
# Returns: RoutingDecision with action and target

class RoutingDecision:
    action: Literal["CONTINUE", "DETOUR", "INJECT_FLOW", "INJECT_NODES", "EXTEND_GRAPH"]
    target: Optional[str]        # Flow key, sidequest ID, or node spec
    reason: str                  # Why this route
    artifacts: List[str]         # What this route will produce
```

**Routing Decision Types:**

| Decision | When Used | Example |
|----------|-----------|---------|
| `CONTINUE` | Golden path is clear | Build step 3 → Build step 4 |
| `DETOUR` | Catalog sidequest fits | Test failure → `test-triage` |
| `INJECT_FLOW` | Need full flow capabilities | Security concern → Flow 8 |
| `INJECT_NODES` | Ad-hoc work needed | Missing CVE data → fetch nodes |
| `EXTEND_GRAPH` | Pattern should be permanent | Propose new sidequest type |

### The Shadow Fork

High trust requires isolation:

```
upstream/main ──┐
                │
                ▼ (fork at T-0)
           origin/feature-branch
                │
                ▼ (swarm works here)
           Shadow Fork (isolated)
                │
                ▼ (Flow 8: Rebase)
           upstream/main
```

---

## File Structure

```
.claude/
  agents/              # 53 domain agent definitions (generated)
  commands/flows/      # 7 slash commands
  skills/              # 4 global skills
  settings.json

swarm/
  api/                 # FastAPI routes
  config/              # Registries (flow, pack, agent, runtime)
  flows/               # Flow specs (markdown)
  packs/               # Portable flow + station bundles
  prompts/             # Agent prompt templates
  runtime/             # Execution engine
    stepwise/          # Step transaction types
    engines/           # LLM backends (Claude SDK, CLI, Gemini)
  tools/               # Validation, generation, UI
    flow_studio_ui/    # TypeScript UI
  runs/                # Run artifacts (gitignored)
  examples/            # Curated demo snapshots

tests/                 # Python tests
docs/                  # Documentation
```

---

## References

- [docs/AGOPS_MANIFESTO.md](./docs/AGOPS_MANIFESTO.md) – Operational philosophy
- [docs/ROADMAP_3_0.md](./docs/ROADMAP_3_0.md) – v3.0 roadmap and next steps
- [docs/STEPWISE_BACKENDS.md](./docs/STEPWISE_BACKENDS.md) – Engine configuration
- [docs/FLOW_STUDIO.md](./docs/FLOW_STUDIO.md) – UI documentation
- [CLAUDE.md](./CLAUDE.md) – Project instructions
