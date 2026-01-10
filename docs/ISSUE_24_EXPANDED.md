# V3.1 Industrial Logic Factory - Master Implementation Plan

**Issue #24 - Expanded Documentation**
**Version:** 3.1.1
**Last Updated:** 2025-12-31
**Status:** Architecture Locked, Implementation In-Progress

---

## Executive Summary

Flow Studio Swarm is an **Industrial Logic Factory** - a stepwise orchestration engine that treats the Claude Agent SDK as a compute primitive. This document provides a comprehensive implementation roadmap from current state to production-ready system.

**The Economic Thesis (The Zimmerman Inversion):**
> We intentionally "waste" compute resources—running adversarial loops, redundant verification steps, and dedicated architectural routing sessions—to minimize **Developer Lead Time (DevLT)**. We burn pennies on tokens to save hours of senior engineer attention.

---

## Table of Contents

1. [Current State Assessment](#current-state-assessment)
2. [Component Deep Dives](#component-deep-dives)
3. [Implementation Phases](#implementation-phases)
4. [Acceptance Criteria](#acceptance-criteria)
5. [Architecture Diagrams](#architecture-diagrams)
6. [Code Examples](#code-examples)
7. [Risk Analysis](#risk-analysis)

---

## Current State Assessment

### Validated Component Status

| Component | Implementation | Active Use | Gap Analysis |
|-----------|---------------|------------|--------------|
| **Execution Engine** | 80% | 80% | Shadow Fork missing, JIT Finalization incomplete |
| **Navigation/Routing** | 95% | 90% | Sidequest catalog populated but not wired |
| **Data Plane** | 85% | 85% | RunState not rebuildable from events |
| **Spec System** | 70% | 20% | Feature-flagged OFF (`use_pack_specs=false`) |
| **UI (Flow Studio)** | 90% | 90% | Cost ticker missing, forensic dashboard partial |
| **Flows 1-7** | 95% | 95% | AC Matrix generation gap in Flow 2 |
| **Flow 8 (Reset)** | 100% spec | 0% | No agent implementations |

### Key Files Analyzed

```
swarm/runtime/
├── stepwise/
│   ├── orchestrator.py      # Navigator-mandatory stepwise orchestrator (1439 lines)
│   ├── routing/
│   │   └── driver.py        # Unified routing driver
│   └── envelope.py          # Envelope invariant enforcement
├── types/
│   ├── routing.py           # RoutingSignal, RoutingCandidate (725 lines)
│   ├── runs.py              # RunState, RunEvent, RunSpec (335 lines)
│   └── handoff.py           # HandoffEnvelope schema
├── storage.py               # Atomic disk I/O with temp+rename (1270 lines)
├── sidequest_catalog.py     # 6 default sidequests (715 lines)
├── navigator.py             # LLM-based navigation
└── macro_navigator.py       # Between-flow routing

swarm/spec/
├── compiler.py              # SpecCompiler with fragment loading (2191 lines)
├── types.py                 # StationSpec, FlowSpec, PromptPlan
└── loader.py                # Spec file loading

swarm/config/
├── flows.yaml               # Flow ordering
├── flows/*.yaml             # Per-flow step definitions
├── model_policy.json        # Model tier configuration
└── pack_registry.py         # Pack-based spec loading
```

---

## Component Deep Dives

### 1. Execution Engine

**Location:** `swarm/runtime/stepwise/orchestrator.py`

#### What's Built ✅
- **StepwiseOrchestrator** class with Navigator-mandatory routing
- Three routing modes: `DETERMINISTIC_ONLY`, `ASSIST`, `AUTHORITATIVE`
- Preflight checks with env-doctor sidequest injection
- Utility flow injection via `InjectionTriggerDetector`
- Graceful stop via `request_stop()` and `_is_stop_requested()`
- `run_autopilot()` for multi-flow execution with MacroNavigator

```python
# Current orchestrator initialization (orchestrator.py:125-198)
def __init__(
    self,
    engine: StepEngine,
    routing_mode: RoutingMode = RoutingMode.ASSIST,
    navigation_orchestrator: Optional["NavigationOrchestrator"] = None,
    skip_preflight: bool = False,
):
    # Navigator-Mandatory Design:
    # The Navigator is the ONLY source of truth for routing decisions.
    # Python kernel is a "dumb executor" that interprets Navigator signals.
```

#### What's Missing ❌
1. **Shadow Fork Isolation**
   - No git branch isolation for speculative execution
   - Agents currently run in the main working tree
   - Risk: Changes leak to production before Flow 6

2. **JIT Finalization (Clerk Pattern)**
   - Envelope writing exists (`ensure_step_envelope()`)
   - Missing: Two-turn pattern (Work → Finalize injection)
   - Missing: Force handoff_draft.json before session exit

3. **Context Hydration (Amnesia Protocol)**
   - `ContextPack` exists but not fully enforced
   - Chat history may leak into agent sessions
   - Missing: Strict session isolation per step

#### Implementation Priority: **CRITICAL**

---

### 2. Navigation/Routing System

**Location:** `swarm/runtime/types/routing.py`, `swarm/runtime/navigator.py`

#### What's Built ✅
- **Comprehensive Type System:**
  - `RoutingDecision`: ADVANCE, LOOP, TERMINATE, BRANCH, SKIP
  - `RoutingCandidate`: Candidate-set pattern for bounded routing
  - `RoutingSignal`: Normalized routing decision signal
  - `RoutingExplanation`: Full audit trail for decisions
  - `WhyNowJustification`: Required for DETOUR/INJECT_*
  - `SkipJustification`: High-friction justification for SKIP

```python
# Candidate-set pattern (routing.py:281-308)
@dataclass
class RoutingCandidate:
    """A candidate routing decision for the Navigator to choose from.

    The candidate-set pattern: Python generates candidates from the graph,
    Navigator intelligently chooses among them, Python validates and executes.
    """
    candidate_id: str
    action: str  # "advance" | "loop" | "detour" | "escalate" | "repeat" | "terminate"
    target_node: Optional[str] = None
    reason: str = ""
    priority: int = 50
    source: str = "graph_edge"  # "graph_edge" | "fast_path" | "detour_catalog"
    evidence_pointers: List[str] = field(default_factory=list)
    is_default: bool = False
```

- **Microloop Context:**
  - `max_iterations=50` as safety fuse (not steering mechanism)
  - `status_history` for stall detection
  - `can_further_iteration_help` flag

- **SidequestCatalog with 6 Default Sidequests:**
  - `clarifier` - Resolve ambiguity
  - `env-doctor` - Diagnose environment issues
  - `test-triage` - Analyze failing tests
  - `security-audit` - Security review for sensitive paths
  - `contract-check` - API/interface contract verification
  - `context-refresh` - Reload context when stalled

#### What's Missing ❌
1. **EXTEND_GRAPH Proposal Persistence**
   - Navigator can propose graph extensions
   - Proposals not persisted for Wisdom analysis
   - Missing: `RUN_BASE/<flow>/routing/proposals/`

2. **Stall Detection Wiring**
   - `ProgressTracker` concept referenced but not implemented
   - Missing: Error signature comparison between iterations
   - Missing: "Elephant Protocol" velocity measurement

3. **MacroFlow Graph Validation**
   - Inter-flow routing exists but not validated against macro graph
   - Missing: Flow sequence constraint enforcement

#### Implementation Priority: **HIGH**

---

### 3. Data Plane

**Location:** `swarm/runtime/storage.py`, `swarm/runtime/types/runs.py`

#### What's Built ✅
- **Atomic Persistence:**
  - `_atomic_write_json()` using temp file + `os.replace()`
  - `os.fsync()` for durability guarantee
  - Per-run locking via `_get_run_lock()`

```python
# Atomic write pattern (storage.py:176-210)
def _atomic_write_json(path: Path, data: Any, indent: int = 2) -> None:
    """Write JSON data to a file atomically.
    Uses a temporary file + os.replace pattern to ensure atomicity.
    """
    fd, tmp_path = tempfile.mkstemp(suffix=".tmp", prefix=path.name + ".", dir=parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=indent, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())  # Ensure data is on disk
        os.replace(tmp_path, path)  # Atomic rename
    except Exception:
        os.unlink(tmp_path)
        raise
```

- **Event-Sourced Storage:**
  - `events.jsonl` with monotonic sequence numbers
  - `_next_seq()` for reliable ordering
  - `_init_seq_from_disk()` for crash recovery

- **HandoffEnvelope Persistence:**
  - `write_envelope()` / `read_envelope()` / `list_envelopes()`
  - `commit_step_completion()` for atomic envelope + state update

- **Navigator Event Queries:**
  - `query_navigator_events()` for Wisdom analysis
  - `summarize_navigator_events()` for tier classification

#### What's Missing ❌
1. **RunState Rebuildability**
   - State written to `run_state.json`
   - Cannot be rebuilt solely from `events.jsonl`
   - Missing: Event replay to reconstruct state

2. **Explicit Resume/Checkpoint API**
   - `read_run_state()` has crash recovery for envelopes
   - Missing: Explicit checkpoint markers
   - Missing: `--resume <run_id>` CLI integration

3. **DuckDB Projection**
   - `run_tailer.py` exists but usage unclear
   - Missing: Real-time projection from events.jsonl
   - Missing: `rebuild-db` command

#### Implementation Priority: **CRITICAL**

---

### 4. Spec System

**Location:** `swarm/spec/compiler.py`, `swarm/spec/types.py`

#### What's Built ✅
- **SpecCompiler Class:**
  - Compiles FlowSpec + StationSpec → PromptPlan
  - Fragment loading with `{{fragment:path}}` syntax
  - Template rendering with `{{variable}}` substitution
  - Deterministic `prompt_hash` for reproducibility

```python
# SpecCompiler core flow (compiler.py:741-912)
def compile(
    self,
    flow_id: str,
    step_id: str,
    context_pack: Optional["ContextPack"],
    run_base: Path,
    use_v2: bool = True,
) -> PromptPlan:
    """Compile a PromptPlan for a flow step.

    V2 enhancements:
    - Includes verification requirements (merged from station + step)
    - Includes resolved handoff contract
    - Includes flow_key for routing
    - Supports policy invariants from fragment references
    """
```

- **StepPlan Dataclass:**
  - Full SDK options: model, tools, permissions, sandbox
  - Traceability: station_id, flow_id, step_id, prompt_hash
  - Verification requirements

- **Template Library (WP2):**
  - `list_templates()` for palette display
  - `expand_template()` for parameter resolution
  - `expand_flow_graph()` for bulk expansion

- **Model Policy:**
  - `model_policy.json` for tier configuration
  - `resolve_station_model()` for tier → full ID resolution

#### What's Missing ❌
1. **Spec-First Loading Default**
   - Currently behind `use_pack_specs=false` flag
   - Legacy Markdown prompts still primary path
   - Missing: Migration of 50+ station specs

2. **Economy Mode Toggle**
   - Model policy exists but no runtime toggle
   - Missing: UI switch for Haiku/Flash mode
   - Missing: Per-station model override

3. **Spec Compilation Validation in CI**
   - No CI check for spec compilation
   - Missing: `make validate-specs` target

#### Implementation Priority: **HIGH**

---

### 5. User Interface (Flow Studio)

**Location:** `swarm/tools/flow_studio_ui/`

#### What's Built ✅
- **Graph Visualization:**
  - `graph.ts` / `graph.js` for node/edge rendering
  - `flow-studio-app.ts` for main application
  - `api.ts` for backend communication

- **SDK Interface:**
  - `window.__flowStudio.getState()`
  - `window.__flowStudio.setActiveFlow()`
  - `window.__flowStudio.selectStep()`

- **Run Control:**
  - `run_control.ts` for execution control
  - SSE for live updates

- **UIID Selectors:**
  - `[data-uiid="flow_studio.header.search.input"]`
  - `[data-uiid="flow_studio.sidebar.flow_list"]`
  - `[data-uiid^="flow_studio.canvas.outline.step:"]`

#### What's Missing ❌
1. **Cost Ticker**
   - No real-time token cost display
   - Missing: Per-step cost accumulation
   - Missing: Run total cost projection

2. **Forensic Dashboard (Sheriff's View)**
   - Partial implementation
   - Missing: Side-by-side Narrative vs Git Diff
   - Missing: Evidence bundle display

3. **Detour Visualization**
   - Injected nodes not visually distinct
   - Missing: Dashed nodes for sidequests
   - Missing: Stack visualization for interruptions

#### Implementation Priority: **MEDIUM**

---

### 6. Flow Implementations

**Location:** `swarm/flows/`, `swarm/config/flows/`

#### Flows 1-7 Status ✅

| Flow | Steps | Agents | Status |
|------|-------|--------|--------|
| **Signal (1)** | 6 | 6 | Complete |
| **Plan (2)** | 8 | 8 | AC Matrix gap |
| **Build (3)** | 9 | 9 | Complete |
| **Review (4)** | 6 | 6 | Complete |
| **Gate (5)** | 6 | 6 | Complete |
| **Deploy (6)** | 4 | 4 | Complete |
| **Wisdom (7)** | 5 | 5 | Complete |

#### Flow 8 (Reset) Status ❌

**Spec exists but no implementation:**
- Purpose: Rebase shadow fork against upstream
- Trigger: Upstream divergence detected in Flow 3
- Agents needed: 8 (to be created)

```yaml
# Flow 8 agent requirements (not yet implemented)
agents:
  - upstream-fetcher      # Fetch upstream changes
  - divergence-analyzer   # Analyze merge conflicts
  - rebase-strategist     # Plan rebase approach
  - conflict-resolver     # Resolve conflicts
  - rebase-executor       # Execute rebase
  - verification-runner   # Run tests post-rebase
  - state-reconciler      # Update run state
  - reporter              # Report rebase outcome
```

#### Implementation Priority: **HIGH**

---

## Implementation Phases

### Phase 1: Foundation Hardening (Critical Path)

**Goal:** Make the system crash-safe and resumable

**Duration:** Sprint 1

#### Tasks

1. **[Data] Make RunState Rebuildable from Events** (#9)
   ```python
   # Proposed: swarm/runtime/state_rebuilder.py
   def rebuild_run_state(run_id: RunId) -> RunState:
       """Rebuild RunState by replaying events.jsonl"""
       events = read_events(run_id)
       state = RunState(run_id=run_id, flow_key="", status="pending")
       for event in events:
           state = apply_event(state, event)
       return state
   ```

2. **[Data] Implement Explicit Resume/Checkpoint API** (#10)
   ```python
   # Proposed: Add to storage.py
   def create_checkpoint(run_id: RunId, label: str) -> str:
       """Create named checkpoint for resumption."""
       checkpoint_id = f"cp-{label}-{_generate_event_id()}"
       append_event(run_id, RunEvent(
           kind="checkpoint",
           payload={"checkpoint_id": checkpoint_id, "label": label}
       ))
       return checkpoint_id

   def resume_from_checkpoint(run_id: RunId, checkpoint_id: str) -> RunState:
       """Resume run from specific checkpoint."""
       ...
   ```

3. **[Data] Add Event Schema Validation** (#18)
   ```python
   # Proposed: swarm/runtime/event_validator.py
   def validate_event(event: RunEvent) -> ValidationResult:
       """Validate event against V1 contract."""
       ...
   ```

#### Exit Criteria
- [ ] Can kill process mid-run and resume cleanly
- [ ] All state reconstructable from events.jsonl alone
- [ ] `make test-crash-recovery` passes

---

### Phase 2: Spec-First Transition

**Goal:** Move from Markdown prompts to compiled JSON specs

**Duration:** Sprint 2

#### Tasks

1. **[Spec] Enable SpecCompiler Default** (#8)
   - Change `use_pack_specs` default to `true`
   - Migrate legacy `build_prompt()` calls
   - Update all backends to use compiled specs

2. **[Spec] Create JSON Station Specs** (50+ files)
   ```json
   // Example: swarm/specs/stations/code-implementer.json
   {
     "id": "code-implementer",
     "version": 1,
     "title": "Code Implementer",
     "category": "implementation",
     "identity": {
       "system_append": "You are the Code Implementer...",
       "tone": "analytical"
     },
     "invariants": [
       "Write code, never prose about code",
       "Run tests after every change"
     ],
     "io": {
       "required_inputs": ["{{run.base}}/plan/work_plan.md"],
       "required_outputs": ["{{run.base}}/build/code_changes.md"]
     },
     "sdk": {
       "model": "sonnet",
       "allowed_tools": ["Read", "Write", "Edit", "Bash", "Grep", "Glob"],
       "max_turns": 50
     }
   }
   ```

3. **[Spec] Add Spec Compilation to CI** (#17)
   ```yaml
   # .github/workflows/validate.yml addition
   - name: Validate Spec Compilation
     run: |
       uv run python -c "
         from swarm.spec.compiler import SpecCompiler
         compiler = SpecCompiler(Path('.'))
         for flow_id in ['signal', 'plan', 'build', 'review', 'gate', 'deploy', 'wisdom']:
           plan = compiler.compile_flow(flow_id)
           assert len(plan.steps) > 0
       "
   ```

#### Exit Criteria
- [ ] `SWARM_USE_SPEC_COMPILER=true` is default
- [ ] All stations have JSON specs in `swarm/specs/stations/`
- [ ] CI validates spec compilation

---

### Phase 3: Routing Completeness

**Goal:** Full candidate-set routing with learning

**Duration:** Sprint 3

#### Tasks

1. **[Routing] Implement EXTEND_GRAPH Persistence** (#11)
   ```python
   # Proposed: Add to storage.py
   def persist_graph_proposal(
       run_id: RunId,
       flow_key: str,
       proposal: GraphExtensionProposal,
   ) -> Path:
       """Persist EXTEND_GRAPH proposal for Wisdom analysis."""
       proposals_dir = get_run_path(run_id) / flow_key / "routing" / "proposals"
       proposals_dir.mkdir(parents=True, exist_ok=True)
       proposal_path = proposals_dir / f"{proposal.proposal_id}.json"
       _atomic_write_json(proposal_path, proposal.to_dict())
       return proposal_path
   ```

2. **[Routing] Wire SidequestCatalog to Navigator** (#12)
   - Connect `get_applicable_sidequests()` to routing driver
   - Add sidequest injection to candidate set
   - Track sidequest usage for max_uses_per_run

3. **[Routing] Implement Stall Detection** (#22)
   ```python
   # Proposed: swarm/runtime/progress_tracker.py
   @dataclass
   class ProgressTracker:
       """Track progress velocity for stall detection."""
       error_signatures: List[str] = field(default_factory=list)

       def record_iteration(self, error_signature: str) -> None:
           self.error_signatures.append(error_signature)

       def is_stalled(self, window: int = 3) -> bool:
           """Check if last N iterations have same error signature."""
           if len(self.error_signatures) < window:
               return False
           recent = self.error_signatures[-window:]
           return len(set(recent)) == 1
   ```

#### Exit Criteria
- [ ] Navigator can inject 5+ default sidequests
- [ ] EXTEND_GRAPH proposals logged in `RUN_BASE/<flow>/routing/proposals/`
- [ ] Stall detection triggers after 3 identical error signatures

---

### Phase 4: Flow Completeness

**Goal:** All 8 flows fully operational

**Duration:** Sprint 4

#### Tasks

1. **[Flows] Implement Flow 8 Reset/Rebase Agents** (#13)
   - Create 8 agent definitions in `.claude/agents/`
   - Add flow spec in `swarm/flows/flow-reset.md`
   - Add flow config in `swarm/config/flows/reset.yaml`

2. **[Flows] Generate AC Matrix in Flow 2** (#14)
   ```python
   # Proposed output: RUN_BASE/plan/ac_matrix.json
   {
     "requirements": [
       {
         "id": "REQ-001",
         "description": "User can log in with email/password",
         "acceptance_criteria": [
           {"id": "AC-001-1", "criterion": "Valid credentials → success"},
           {"id": "AC-001-2", "criterion": "Invalid credentials → error"}
         ],
         "test_cases": ["test_login_success", "test_login_invalid"]
       }
     ]
   }
   ```

3. **[Spec] Automate Wisdom Extraction** (#15)
   ```python
   # Proposed: Write to _wisdom/latest.md after Flow 7
   def write_scent_trail(run_id: RunId, learnings: List[Learning]) -> Path:
       """Write wisdom for next run's context."""
       wisdom_dir = RUNS_DIR / "_wisdom"
       wisdom_dir.mkdir(exist_ok=True)
       content = format_scent_trail(learnings)
       path = wisdom_dir / "latest.md"
       path.write_text(content)
       return path
   ```

#### Exit Criteria
- [ ] Flow 8 can be injected via INJECT_FLOW
- [ ] AC Matrix traces requirements → tests
- [ ] Wisdom automatically feeds next run

---

### Phase 5: Safety & Isolation

**Goal:** Speculative execution without risk

**Duration:** Sprint 5

#### Tasks

1. **[Engine] Implement Shadow Fork Isolation** (#7)
   ```python
   # Proposed: swarm/runtime/shadow_fork.py
   class ShadowFork:
       """Isolated git branch for speculative execution."""

       def __init__(self, repo_root: Path, upstream_remote: str = "origin"):
           self.repo_root = repo_root
           self.upstream_remote = upstream_remote
           self.shadow_branch: Optional[str] = None

       def create(self, base_branch: str = "main") -> str:
           """Create shadow branch for isolation."""
           shadow_name = f"shadow/{datetime.now().strftime('%Y%m%d-%H%M%S')}"
           subprocess.run(["git", "checkout", "-b", shadow_name, base_branch])
           self.shadow_branch = shadow_name
           return shadow_name

       def block_upstream_push(self) -> None:
           """Block pushes to upstream until Flow 6."""
           # Set up pre-push hook to reject non-Flow-6 pushes
           ...
   ```

2. **Add Rollback Semantics**
   ```python
   # Proposed: Add to orchestrator.py
   def rollback_step(self, run_id: RunId, step_id: str) -> bool:
       """Rollback failed step changes."""
       # Use git stash or git checkout to revert
       ...
   ```

3. **Implement Capability-Based Tool Policy**
   ```python
   # Proposed: swarm/runtime/tool_policy.py
   @dataclass
   class ToolPolicy:
       """Capability-based tool access control."""
       allowed_tools: Set[str]
       denied_patterns: List[str]  # e.g., ["rm -rf", "git push --force"]

       def can_execute(self, command: str) -> bool:
           for pattern in self.denied_patterns:
               if pattern in command:
                   return False
           return True
   ```

#### Exit Criteria
- [ ] Agents execute in isolated git branch
- [ ] Failed steps can be rolled back
- [ ] Dangerous commands blocked until Flow 6

---

### Phase 6: Polish & Documentation

**Goal:** Production-ready with full docs

**Duration:** Sprint 6

#### Tasks

1. **[Engine] Document Amnesia Protocol** (#21)
   - Write `docs/AMNESIA_PROTOCOL.md`
   - Document ContextPack structure
   - Document session isolation requirements

2. **[UI] Add Token Cost Ticker** (#23)
   ```typescript
   // Proposed: flow_studio_ui/src/cost_ticker.ts
   interface CostTicker {
     totalTokens: number;
     totalCostUsd: number;
     perStepCosts: Map<string, StepCost>;

     updateFromEvent(event: RunEvent): void;
     formatDisplay(): string;
   }
   ```

3. **Create Operator Runbook**
   - `docs/OPERATOR_RUNBOOK.md`
   - Debugging failed runs
   - Resuming interrupted runs
   - Analyzing routing decisions

#### Exit Criteria
- [ ] All architectural concepts documented
- [ ] Operator can debug runs from UI alone
- [ ] Cost tracking visible in real-time

---

## Acceptance Criteria

### System Acceptance Checklist

#### 1. Execution Engine (The Factory Floor)
- [ ] **Atomic Step Execution:** Spin up fresh session, execute, shut down cleanly
- [ ] **Context Hydration:** ContextPack contains summaries + file pointers, no chat history
- [ ] **JIT Finalization:** Agent forced to write handoff_draft.json before exit
- [ ] **Shadow Fork Isolation:** All ops in shadow branch, blocked from upstream
- [ ] **Permission Bypass:** Agents execute without human confirmation

#### 2. Navigation System (The GPS)
- [ ] **Forensic Verification:** DiffScanner + TestParser run between Worker and Navigator
- [ ] **Agentic Routing:** Navigator produces valid RoutingSignal from candidates
- [ ] **Dynamic Detours:** InterruptionStack correctly pushes/pops sidequests
- [ ] **Stall Detection:** Elephant Protocol triggers on repeated error signatures

#### 3. Data Plane (The Ledger)
- [ ] **Atomic Persistence:** RunState survives SIGKILL mid-write
- [ ] **Resumability:** `--resume <run_id>` picks up at last checkpoint
- [ ] **DuckDB Projection:** Tailer populates tables in real-time
- [ ] **Rebuildability:** `rebuild-db` reconstructs state from events.jsonl

#### 4. Management Plane (Specs & Config)
- [ ] **Spec-First Loading:** System runs from JSON specs, not Markdown
- [ ] **Model Policy Enforcement:** Economy Mode switches to Haiku/Flash
- [ ] **Wisdom Injection:** Flow 7 writes, Flow 1 reads scent trail

#### 5. User Interface (Mission Control)
- [ ] **Graph Visualization:** Nodes and edges render, active nodes pulse
- [ ] **Forensic Dashboard:** Sheriff's View shows Narrative vs Diff
- [ ] **Live Telemetry:** Cost ticker and file tree update via SSE
- [ ] **Control Actions:** Stop triggers orderly shutdown, not hard kill

#### 6. Flow Lifecycle (The Pipeline)
- [ ] **Flows 1-2:** Produce valid ac_matrix.json and adr.md
- [ ] **Flow 3:** Iterates through AC Matrix autonomously
- [ ] **Flow 4:** Harvests PR feedback and clusters it
- [ ] **Flow 5:** Rejects code if Forensics fail
- [ ] **Flow 6:** Merges to main after gate approval
- [ ] **Flow 7:** Generates spec patches
- [ ] **Flow 8:** Rebases shadow fork against upstream

---

## Architecture Diagrams

### Control Flow

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           PYTHON KERNEL                                  │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │                    StepwiseOrchestrator                           │  │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐               │  │
│  │  │  Preflight  │→ │  StepLoop   │→ │  MacroNav   │               │  │
│  │  │   Checks    │  │   Driver    │  │   Router    │               │  │
│  │  └─────────────┘  └──────┬──────┘  └─────────────┘               │  │
│  │                          │                                        │  │
│  │                          ▼                                        │  │
│  │  ┌─────────────────────────────────────────────────────────────┐ │  │
│  │  │                   Routing Driver                             │ │  │
│  │  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐    │ │  │
│  │  │  │ FastPath │→ │ Navigator│→ │ Envelope │→ │ Escalate │    │ │  │
│  │  │  │ (cheap)  │  │ (LLM)    │  │ (legacy) │  │ (halt)   │    │ │  │
│  │  │  └──────────┘  └──────────┘  └──────────┘  └──────────┘    │ │  │
│  │  └─────────────────────────────────────────────────────────────┘ │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                                                          │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │                       Storage Layer                               │  │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐         │  │
│  │  │ RunState │  │ Events   │  │ Envelopes│  │ DuckDB   │         │  │
│  │  │  .json   │  │ .jsonl   │  │  /handoff│  │ Projection│         │  │
│  │  └──────────┘  └──────────┘  └──────────┘  └──────────┘         │  │
│  └───────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                           CLAUDE SDK                                     │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │                     StepEngine                                    │  │
│  │  ┌──────────────────────────────────────────────────────────────┐│  │
│  │  │  Session 1: Worker (Sonnet)                                  ││  │
│  │  │  - ContextPack injected                                      ││  │
│  │  │  - bypassPermissions enabled                                 ││  │
│  │  │  - Full tool access                                          ││  │
│  │  └──────────────────────────────────────────────────────────────┘│  │
│  │                              │                                    │  │
│  │                              ▼                                    │  │
│  │  ┌──────────────────────────────────────────────────────────────┐│  │
│  │  │  Session 2: Clerk (same context, finalization prompt)        ││  │
│  │  │  - Force handoff_draft.json write                            ││  │
│  │  └──────────────────────────────────────────────────────────────┘│  │
│  └───────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
```

### Routing Decision Flow

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        ROUTING DECISION                                  │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  1. Python Generates Candidate Set                                       │
│     ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────────┐    │
│     │   ADVANCE   │ │    LOOP     │ │   DETOUR    │ │  TERMINATE  │    │
│     │  to step-4  │ │  to step-3  │ │ env-doctor  │ │   (halt)    │    │
│     │ priority:80 │ │ priority:60 │ │ priority:70 │ │ priority:10 │    │
│     └─────────────┘ └─────────────┘ └─────────────┘ └─────────────┘    │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  2. Navigator Selects from Candidates                                    │
│     - Reads: FlowGraph, Handoff, EvidenceBundle                         │
│     - Considers: Forensics > Narrative                                  │
│     - Output: chosen_candidate_id + reasoning                           │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  3. Python Validates and Executes                                        │
│     - Verifies candidate is in original set                             │
│     - Applies graph constraints                                         │
│     - Logs RoutingExplanation for audit                                 │
│     - Commits to RunState                                               │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Code Examples

### Example: Crash-Safe Event Replay

```python
# swarm/runtime/state_rebuilder.py

from typing import Dict, Any
from swarm.runtime.storage import read_events, RUNS_DIR
from swarm.runtime.types import RunEvent, RunState, run_state_from_dict

def rebuild_run_state(run_id: str) -> RunState:
    """Rebuild RunState by replaying events.jsonl.

    This is the foundation of crash recovery - given only the append-only
    event log, we can reconstruct the exact program counter state.

    Event types that modify state:
    - run_started: Initialize new state
    - step_completed: Advance step_index, update handoff_envelopes
    - route_decision: Update current_step_id
    - checkpoint: Mark resumption point
    - flow_paused/run_stopped: Update status
    """
    events = read_events(run_id)

    if not events:
        raise ValueError(f"No events found for run {run_id}")

    # Find run_started event for initial state
    start_event = next((e for e in events if e.kind == "run_started"), None)
    if not start_event:
        raise ValueError(f"No run_started event for run {run_id}")

    # Initialize state
    state = RunState(
        run_id=run_id,
        flow_key=start_event.flow_key,
        status="running",
        step_index=0,
    )

    # Replay events in order
    for event in events:
        state = _apply_event(state, event)

    return state


def _apply_event(state: RunState, event: RunEvent) -> RunState:
    """Apply a single event to state."""
    if event.kind == "step_completed":
        state.step_index = event.payload.get("step_index", state.step_index) + 1
        step_id = event.step_id
        if step_id:
            state.mark_node_completed(step_id)

    elif event.kind == "route_decision":
        state.current_step_id = event.payload.get("next_step_id")

    elif event.kind in ("run_stopped", "flow_paused"):
        state.status = "paused"

    elif event.kind == "run_completed":
        state.status = "completed"

    elif event.kind == "run_failed":
        state.status = "failed"

    return state
```

### Example: Shadow Fork Implementation

```python
# swarm/runtime/shadow_fork.py

import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

@dataclass
class ShadowFork:
    """Isolated git branch for speculative execution.

    Key invariants:
    1. All work happens on shadow branch, never main
    2. Pushes to upstream blocked until Flow 6
    3. Failed runs can be discarded without cleanup
    4. Successful runs merge cleanly in Flow 6
    """

    repo_root: Path
    shadow_branch: Optional[str] = None
    original_branch: Optional[str] = None

    def create(self, base_branch: str = "main") -> str:
        """Create shadow branch for isolated execution."""
        # Save original branch
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=self.repo_root,
            capture_output=True,
            text=True,
        )
        self.original_branch = result.stdout.strip()

        # Create timestamped shadow branch
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.shadow_branch = f"shadow/{timestamp}"

        subprocess.run(
            ["git", "checkout", "-b", self.shadow_branch, base_branch],
            cwd=self.repo_root,
            check=True,
        )

        # Install pre-push hook to block upstream pushes
        self._install_push_guard()

        return self.shadow_branch

    def _install_push_guard(self) -> None:
        """Block pushes to upstream until Flow 6."""
        hook_path = self.repo_root / ".git" / "hooks" / "pre-push"
        hook_content = '''#!/bin/bash
# Shadow Fork Push Guard - blocks pushes until Flow 6
if [ -f ".shadow_fork_active" ]; then
    echo "ERROR: Cannot push from shadow fork outside Flow 6"
    echo "Use 'swarm deploy' to merge approved changes"
    exit 1
fi
'''
        hook_path.write_text(hook_content)
        hook_path.chmod(0o755)

        # Create marker file
        (self.repo_root / ".shadow_fork_active").touch()

    def allow_push(self) -> None:
        """Allow push (called by Flow 6 after gate approval)."""
        marker = self.repo_root / ".shadow_fork_active"
        if marker.exists():
            marker.unlink()

    def cleanup(self, success: bool) -> None:
        """Clean up shadow branch after run."""
        if not success:
            # Discard failed shadow branch
            subprocess.run(
                ["git", "checkout", self.original_branch or "main"],
                cwd=self.repo_root,
            )
            subprocess.run(
                ["git", "branch", "-D", self.shadow_branch],
                cwd=self.repo_root,
            )

        # Remove marker
        marker = self.repo_root / ".shadow_fork_active"
        if marker.exists():
            marker.unlink()
```

### Example: Sidequest Injection

```python
# Integration with routing driver

from swarm.runtime.sidequest_catalog import (
    SidequestCatalog,
    load_default_catalog,
)
from swarm.runtime.types.routing import RoutingCandidate

def build_candidate_set(
    step_result: StepResult,
    run_state: RunState,
    catalog: SidequestCatalog,
) -> List[RoutingCandidate]:
    """Build routing candidates including applicable sidequests."""
    candidates = []

    # 1. Standard graph-based candidates
    candidates.extend(_get_graph_candidates(step_result, run_state))

    # 2. Applicable sidequests from catalog
    context = {
        "verification_passed": step_result.status == "VERIFIED",
        "failure_type": step_result.failure_type,
        "changed_paths": step_result.changed_files,
        "stall_signals": {
            "stall_count": run_state.get_stall_count(),
            "same_failure_signature": run_state.has_same_error_signature(),
        },
    }

    applicable = catalog.get_applicable_sidequests(context, run_id=run_state.run_id)

    for sq in applicable:
        candidates.append(RoutingCandidate(
            candidate_id=f"detour:{sq.sidequest_id}",
            action="detour",
            target_node=sq.get_station_id(),
            reason=sq.description,
            priority=sq.priority,
            source="detour_catalog",
            evidence_pointers=[f"trigger:{sq.sidequest_id}"],
        ))

    return sorted(candidates, key=lambda c: -c.priority)
```

---

## Risk Analysis

### High-Risk Items

| Risk | Impact | Mitigation |
|------|--------|------------|
| **No Shadow Fork** | Changes leak to production | Phase 5 priority |
| **State not rebuildable** | Lost work on crash | Phase 1 priority |
| **Spec migration** | Breaking changes | Feature flag, gradual rollout |
| **Flow 8 missing** | Cannot sync with upstream | Phase 4 priority |

### Dependencies

```
Phase 1 (Data Plane)
    │
    ├──► Phase 2 (Spec System) ──► Phase 3 (Routing)
    │                                    │
    │                                    └──► Phase 4 (Flows)
    │
    └──► Phase 5 (Safety) ──► Phase 6 (Polish)
```

### Success Metrics

1. **Reliability:** 99% of runs complete without manual intervention
2. **Resumability:** 100% of interrupted runs resume correctly
3. **Crash Safety:** Zero data loss on process crash
4. **Auditability:** Every routing decision traceable to evidence
5. **Cost Visibility:** Token spend visible per-step in UI

---

## Related Issues

- **Critical:** #7 (Shadow Fork), #8 (SpecCompiler)
- **High:** #9 (RunState Rebuild), #10 (Resume API), #11 (EXTEND_GRAPH), #12 (Sidequests), #13 (Flow 8), #14 (AC Matrix)
- **Medium:** #15 (Wisdom), #16 (MacroFlow), #17 (Spec CI), #18 (Event Schema), #19 (Forensic Score), #20 (Examples)
- **Low:** #21 (Amnesia Docs), #22 (Stall Config), #23 (Cost Ticker)

---

**Document Owner:** @EffortlessSteven
**Last Review:** 2025-12-31
**Next Review:** After Phase 1 completion
