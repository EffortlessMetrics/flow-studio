# Lexicon

> Canonical vocabulary for Flow Studio. Use these terms consistently to prevent noun-overload.

---

## Reserved Term: Agent

**Reserve "agent" for `.claude/agents/` definitions only.** These are subagents invoked via the Task tool inside a step. Everywhere else, use the precise term from the table below.

---

## Core Vocabulary

| Term | Definition | Example |
|------|------------|---------|
| **Flow** | Orchestration phase (1 of 7) with a charter, exit criteria, and non-goals. Transforms a question into artifacts. | Signal, Plan, Build, Review, Gate, Deploy, Wisdom |
| **Station** | Reusable execution unit with explicit contracts: inputs, outputs, invariants, SDK access. A step executes a station. | `code-critic`, `test-author`, `context-loader` |
| **Step** | A single stepwise Claude Code call. One objective, one context pack, produces receipts. Position in a flow that executes a station. | "Build step 3" executes the `code-implementer` station |
| **Subagent** | Helper invoked *inside* a step via the Task tool. Full Claude Code orchestrator, but scoped to a specific mechanical operation. | `explore`, `plan-subagent`, domain agents |
| **Navigator** | The routing decision-maker. Analyzes forensics and decides: CONTINUE, DETOUR, INJECT_FLOW, INJECT_NODES, or EXTEND_GRAPH. | MacroNavigator (between flows), Navigator (within flow) |
| **Worker** | The station executing its objective. Full autonomy within station constraints. | `code-implementer` implementing features |
| **Charter** | Flow-level constitution: goal, exit criteria, non-goals, prime directive. Injected into Navigator prompts to enforce scope. | Build charter: "Maximize passing tests. Minimize changes." |
| **Golden Path** | The default route through the flow graph. What happens when everything works. | Signal -> Plan -> Build -> Review -> Gate -> Deploy -> Wisdom |
| **Detour** | Extra stations inserted around the golden path to handle known failure patterns. Returns to golden path after completion. | Lint-fix sidequest, env-doctor |
| **Sidequest** | Synonym for detour. A pre-catalogued remediation pattern from the SidequestCatalog. | `clarifier`, `test-triage`, `security-audit` |
| **Subflow Injection** | Pushing a flow-shaped bundle onto the execution stack to unblock the current charter, then returning. The injected flow inherits the parent's goal context. | Build injects Flow 8 (Rebase) when upstream diverges |
| **Context Pack** | Curated context prepared for a station. Selected by the Curator, consumed by the Worker. Respects context budgets. | Handoff from previous step + relevant artifacts |
| **Forensics** | Semantic interpretation of diffs, logs, and test results. Physical evidence the Navigator uses for routing decisions (not just counters). | DiffScanner output, TestParser results, git status |
| **Curator** | Cheap model that preps context for an expensive model. Selects what goes into the Context Pack. | Selects 20K tokens from 200K available |
| **Handoff** | Structured artifact written by a step's Finalizer. Contains: summary, artifacts, concerns, next_step_hint. Crosses the amnesia boundary. | `handoff.json` written at step completion |
| **Receipt** | Audit artifact documenting what an agent did, decisions made, and outcomes. Enables traceability. | `build_receipt.json`, `gate_receipt.json` |

---

## Execution Hierarchy

```
Python Kernel (Director)
    Manages: Time, Disk, Budget, Graph topology
    Never LLM; spawns Steps
        |
        v
Step (Manager)
    Executes: Single station objective
    Power: Full orchestrator, delegates to Subagents
        |
        v
Subagent (Specialist)
    Executes: Specific mechanical operation
    Power: Full orchestrator, returns distilled results
```

---

## Routing Vocabulary

| Term | Definition |
|------|------------|
| **CONTINUE** | Proceed on golden path. Default decision. |
| **DETOUR** | Inject sidequest chain, then return to golden path. |
| **INJECT_FLOW** | Insert entire flow onto the stack. Used for complete flow capabilities. |
| **INJECT_NODES** | Create ad-hoc spec-backed nodes. Used when no existing flow matches. |
| **EXTEND_GRAPH** | Propose graph patch for future runs. Wisdom learns new pattern. |
| **Graph Stack** | Nested execution model. Injected flows create new stack frames. Max depth: 3. |

---

## Anti-Patterns

| Wrong | Right | Why |
|-------|-------|-----|
| "The agent runs the flow" | "The step executes the station" | Agent is reserved for `.claude/agents/` |
| "Agent decided to DETOUR" | "Navigator decided to DETOUR" | Navigator makes routing decisions |
| "The agent's context" | "The step's context pack" | Precision about what context is prepared |
| "Flow 3 agents" | "Build stations" or "Build subagents" | Distinguish between station specs and callable agents |

---

## Quick Reference: What to Call Things

| You're talking about... | Call it... |
|------------------------|------------|
| Signal, Plan, Build, Review, Gate, Deploy, Wisdom | **Flow** |
| A position in a flow that does work | **Step** |
| The reusable capability definition | **Station** |
| Something called via Task tool inside a step | **Subagent** (or just "agent" since it's in `.claude/agents/`) |
| Who picks the next step | **Navigator** |
| Who does the work | **Worker** |
| What the flow is trying to achieve | **Charter** |
| The default route | **Golden Path** |
| Extra work to handle failures | **Detour** or **Sidequest** |
| A whole flow pushed onto the stack | **Subflow Injection** |
| What context a step gets | **Context Pack** |
| Evidence for routing | **Forensics** |
| Who preps context cheaply | **Curator** |
