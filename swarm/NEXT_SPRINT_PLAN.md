# Next Sprint Plan: Spec-Runtime Convergence

> **For:** Next thread agents (explore → plan → implement)
> **Prerequisite:** Convergence gate is GREEN (validated 2024-12-30)

---

## Executive Summary

Four phases remain to close the "Industrial Logic Factory":

| Phase | Goal | Files to Touch | Risk |
|-------|------|----------------|------|
| **3** | SpecCompiler becomes runtime source | `swarm/runtime/`, `swarm/spec/` | HIGH |
| **4** | Utility flow injection with call/return | `swarm/runtime/`, interruption stack | HIGH |
| **5** | Routing audit trail thin + correct | `swarm/runtime/engines/claude/` | MEDIUM |
| **6** | Golden path + chaos run verification | Tests + manual runs | MEDIUM |

**The Core Problem:** Specs exist but runtime bypasses them. The SpecCompiler can produce PromptPlans, but the actual execution path (`run_stepwise.py`, Claude engine) doesn't consume them consistently.

---

## Phase 3: Make SpecCompiler the Runtime Source

### Current State

```
swarm/spec/compiler.py        - SpecCompiler exists, produces PromptPlan
swarm/runtime/engines/claude/ - Has its own prompt_builder.py that bypasses specs
swarm/runtime/stepwise/       - Orchestrator calls engine directly
```

The `/api/station/compile-preview` endpoint proves SpecCompiler works. But production execution doesn't use it.

### Target State

```
ContextPack + FlowPosition + StationRole + RepoContext
                    ↓
              SpecCompiler
                    ↓
               PromptPlan
                    ↓
         SDK Runner (Claude/Gemini)
                    ↓
            PromptReceipt (artifact)
```

### Exploration Tasks

1. **Trace the execution path:**
   - `swarm/runtime/stepwise/orchestrator.py` - How does it call engines?
   - `swarm/runtime/engines/claude/router.py` - What builds the prompt?
   - `swarm/runtime/engines/claude/prompt_builder.py` - Is this the bypass?

2. **Understand SpecCompiler output:**
   - `swarm/spec/compiler.py` - What does `PromptPlan` contain?
   - `swarm/spec/models.py` - Data structures for specs
   - Compare PromptPlan fields to what prompt_builder produces

3. **Find the integration point:**
   - Where should SpecCompiler.compile() be called?
   - What context does it need that's available at runtime?

### Implementation Plan

1. **Create a PromptReceipt model** (`swarm/spec/models.py`):
   ```python
   @dataclass
   class PromptReceipt:
       prompt_hash: str           # SHA256 of work+finalize prompts
       fragment_manifest: List[str]  # Which fragments were injected
       context_pack_hash: str     # Hash of input context
       model_tier: str            # haiku/sonnet/opus
       tool_profile: List[str]    # Allowed tools
       compiled_at: str           # ISO timestamp
       compiler_version: str
   ```

2. **Modify orchestrator to use SpecCompiler:**
   - In `run_step()`, call `SpecCompiler.compile()` before engine execution
   - Pass the PromptPlan to the engine instead of raw parameters
   - Write PromptReceipt to `RUN_BASE/<flow>/receipts/`

3. **Modify Claude engine to consume PromptPlan:**
   - `prompt_builder.py` should read from PromptPlan, not rebuild from scratch
   - Or: Replace prompt_builder with PromptPlan passthrough

4. **Verify with existing preview endpoint:**
   - `/api/station/compile-preview` should produce identical output to runtime

### Success Criteria

- [ ] Every step execution goes through SpecCompiler
- [ ] PromptReceipt written for every step
- [ ] `prompt_builder.py` is no longer called directly in production paths
- [ ] Compilation is deterministic (same inputs → same prompt hash)

---

## Phase 4: Utility Flow Injection with Call/Return

### Current State

```
swarm/config/flows.yaml       - "reset" marked as utility flow (is_utility: true)
swarm/runtime/navigator_integration.py - Can detect routing decisions
InterruptionStackPanel        - UI component exists but no runtime backing
```

The UI can display stack frames, but there's no runtime that pushes/pops them.

### Target State

```
Flow 3 (Build) executing step 3.5
           ↓
Navigator detects: upstream diverged
           ↓
Routing decision: INJECT_FLOW(reset)
           ↓
Push stack frame: {interrupted_at: "3.5", return_point: "3.5", injected: "reset"}
           ↓
Execute Flow 8 (Reset) steps
           ↓
Reset completes with on_complete: return
           ↓
Pop stack frame
           ↓
Resume Flow 3 at step 3.5
```

### Exploration Tasks

1. **Understand current routing:**
   - `swarm/runtime/navigator_integration.py` - How are routing decisions made?
   - `swarm/runtime/stepwise/orchestrator.py` - How does it handle routing signals?
   - `docs/ROUTING_PROTOCOL.md` - What's the contract?

2. **Find injection triggers:**
   - What conditions trigger INJECT_FLOW vs DETOUR?
   - Where is the sidequest catalog? (`swarm/SIDEQUESTS.md`?)
   - How does Reset flow know when to activate?

3. **Understand run_state.json:**
   - What's the current schema?
   - Where would interruption_stack live?
   - How is flow position tracked?

### Implementation Plan

1. **Extend run_state.json schema:**
   ```python
   # In swarm/runtime/state.py or similar
   @dataclass
   class StackFrame:
       frame_id: str
       interrupted_flow: str
       interrupted_step: str
       injected_flow: str
       reason: str
       return_point: str
       inherited_goal: Optional[str]

   @dataclass
   class RunState:
       current_flow: str
       current_step: str
       interruption_stack: List[StackFrame]  # NEW
       # ... existing fields
   ```

2. **Add injection detection to Navigator:**
   - When routing decision is INJECT_FLOW:
     - Push current position to stack
     - Update current_flow/step to injected flow's entry point
   - When routing decision includes `on_complete: return`:
     - Pop stack frame
     - Restore previous position

3. **Modify orchestrator loop:**
   ```python
   while not complete:
       step = get_current_step(run_state)
       result = execute_step(step)
       routing = get_routing_decision(result)

       if routing.action == "INJECT_FLOW":
           push_stack_frame(run_state, routing)
           run_state.current_flow = routing.target_flow
           run_state.current_step = get_entry_step(routing.target_flow)
       elif routing.action == "RETURN":
           frame = pop_stack_frame(run_state)
           run_state.current_flow = frame.interrupted_flow
           run_state.current_step = frame.return_point
       else:
           run_state.current_step = routing.next_step
   ```

4. **Wire to InterruptionStackPanel:**
   - API endpoint to expose `run_state.interruption_stack`
   - UI already has `parseStackFromApiResponse()` helper

### Success Criteria

- [ ] run_state.json includes `interruption_stack` field
- [ ] INJECT_FLOW routing decision pushes a frame
- [ ] Utility flow completion pops the frame and resumes
- [ ] InterruptionStackPanel displays real stack data
- [ ] Reset flow can be injected and return cleanly

---

## Phase 5: Routing Audit Trail Thin + Correct

### Current State

```
Routing decisions are logged, but:
- chosen_candidate_id sometimes inferred, not persisted
- Full candidate sets bloat the journal
- Deterministic/fast-path routes may skip fields
```

### Target State

Every routing event has:
```json
{
  "chosen_candidate_id": "candidate-uuid",
  "candidate_count": 3,
  "candidate_set_path": "RUN_BASE/flow/routing/candidates-step-3.json",
  "routing_source": "navigator|fast_path|deterministic_fallback|config_default"
}
```

Full candidates stored out-of-line, only pointers in journal.

### Exploration Tasks

1. **Find all routing emission points:**
   - `swarm/runtime/engines/claude/router.py`
   - `swarm/runtime/navigator_integration.py`
   - Search for `routing_decision`, `chosen_candidate`

2. **Check current envelope schema:**
   - `swarm/runtime/handoff_io.py`
   - What routing fields exist today?

3. **Identify missing cases:**
   - Deterministic routing (graph edge)
   - Fast-path routing (no Navigator call)
   - Config fallback routing

### Implementation Plan

1. **Normalize RoutingSignal emission:**
   - Every routing path must emit:
     - `chosen_candidate_id` (never inferred)
     - `routing_source` (always set)
     - `candidate_set_path` (if candidates > 1)

2. **Store candidates out-of-line:**
   ```python
   if len(candidates) > 1:
       path = write_candidates_artifact(run_base, flow, step, candidates)
       signal.candidate_set_path = path
   signal.candidate_count = len(candidates)
   ```

3. **Update envelope writer:**
   - Ensure routing fields are copied verbatim from RoutingSignal
   - No re-derivation of chosen_candidate_id

4. **Add projection table:**
   - DuckDB table for routing decisions
   - Columns: run_id, flow, step, routing_source, chosen_id, candidate_count, path

### Success Criteria

- [ ] Every step has `routing_source` in envelope
- [ ] `chosen_candidate_id` is always explicit, never inferred
- [ ] Candidate sets stored in artifacts, not journal
- [ ] DuckDB can query routing decisions efficiently

---

## Phase 6: Golden Path + Chaos Run Verification

### Golden Run Test

Execute Flows 1-7 with at least:
- One DETOUR (sidequest)
- One routing decision visible in UI
- All receipts produced

**Commands:**
```bash
make stepwise-sdlc-stub          # Zero-cost demo run
# OR
make stepwise-sdlc-claude-sdk    # Full Claude execution
```

**Verification:**
1. Open Flow Studio: `http://localhost:5000/?run=<run-id>&mode=operator`
2. Navigate to a step with routing decision
3. Click "Routing" tab → verify RoutingDecisionCard renders
4. Click "Stack" tab → verify InterruptionStackPanel renders (even if empty)
5. Check `RUN_BASE/<flow>/receipts/` for PromptReceipts

### Chaos Run Test

Test resilience:

1. **Stop mid-step:**
   ```bash
   # Start a run
   make stepwise-sdlc-claude-sdk &
   # Kill after ~30 seconds
   kill %1
   ```

2. **Resume:**
   ```bash
   # Resume the same run
   python -m swarm.runtime.run_stepwise --resume --run-id <run-id>
   ```

3. **Verify:**
   - Run continues from last completed step
   - No duplicate receipts
   - UI shows consistent state
   - Routing history intact

4. **Projection rebuild:**
   ```bash
   # Delete DuckDB and rebuild
   rm swarm/runs/<run-id>/projection.duckdb
   make rebuild-projection RUN_ID=<run-id>
   ```
   - UI should show identical data after rebuild

### Success Criteria

- [ ] Golden run completes all 7 flows
- [ ] At least one routing decision visible in UI
- [ ] Chaos run resumes correctly
- [ ] Projection rebuild produces identical queries

---

## File Reference

### Primary Files to Modify

| File | Phase | Purpose |
|------|-------|---------|
| `swarm/spec/compiler.py` | 3 | SpecCompiler entry point |
| `swarm/spec/models.py` | 3 | Add PromptReceipt |
| `swarm/runtime/stepwise/orchestrator.py` | 3, 4 | Use SpecCompiler, handle injection |
| `swarm/runtime/engines/claude/router.py` | 3, 5 | Consume PromptPlan, emit routing |
| `swarm/runtime/engines/claude/prompt_builder.py` | 3 | Deprecate or wrap |
| `swarm/runtime/navigator_integration.py` | 4, 5 | Injection detection, routing source |
| `swarm/runtime/state.py` | 4 | Add interruption_stack to RunState |
| `swarm/runtime/handoff_io.py` | 5 | Routing fields in envelope |

### Key Documentation

| Doc | Purpose |
|-----|---------|
| `docs/ROUTING_PROTOCOL.md` | V3 routing contract |
| `docs/STEPWISE_BACKENDS.md` | Execution model |
| `docs/STEPWISE_CONTRACT.md` | Step lifecycle |
| `swarm/SELFTEST_SYSTEM.md` | Testing approach |

### Test Files

| Test | Coverage |
|------|----------|
| `tests/test_claude_stepwise_backend.py` | Claude engine |
| `tests/test_build_stepwise_routing.py` | Routing logic |
| `tests/test_flow_registry.py` | Flow structure |

---

## Recommended Execution Order

1. **Phase 3 first** - SpecCompiler is foundational; other phases depend on clean compilation
2. **Phase 5 second** - Routing audit trail is simpler and unblocks debugging
3. **Phase 4 third** - Utility injection builds on routing infrastructure
4. **Phase 6 last** - Verification after all changes

**Estimated scope:** ~500-800 lines of code changes across 8-10 files.

---

## Questions to Resolve During Exploration

1. Does SpecCompiler handle all station types or just some?
2. Is there a ContextPack builder we can reuse?
3. What's the exact trigger condition for Reset injection?
4. Should routing candidates be JSON or JSONL?
5. Is there an existing "resume" mechanism we're not aware of?

---

*Generated: 2024-12-30*
*Convergence gate: GREEN*
*Ready for next thread.*
