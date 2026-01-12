# Routing Decisions

The V3 routing model uses graph-native routing with goal-aligned decisions.

## Decision Vocabulary (Closed Set)

| Decision | Description | When to Use |
|----------|-------------|-------------|
| **CONTINUE** | Proceed on golden path | Normal flow progression |
| **LOOP** | Repeat current step | Microloop iteration (author ⇄ critic) |
| **DETOUR** | Inject sidequest chain | Known failure patterns (lint fix, dep update) |
| **INJECT_FLOW** | Insert entire flow | Flow 3 calling Flow 8 rebase when upstream diverges |
| **INJECT_NODES** | Ad-hoc nodes | Novel requirements not covered by existing flows |
| **EXTEND_GRAPH** | Propose patch | Wisdom learns new pattern; suggests SOP evolution |
| **TERMINATE** | End flow | Terminal step reached or explicit termination |
| **ESCALATE** | Request human | Cannot proceed without human decision |

## Routing Priority

The kernel resolves routing in this order:

### 1. Fast-Path (Deterministic, No LLM)
- Terminal step → TERMINATE
- Explicit `next_step_id` in envelope → ADVANCE
- Microloop exit condition met → ADVANCE
- VERIFIED status → ADVANCE

### 2. Deterministic Checks
- Microloop iteration count exceeded → ADVANCE with warning
- Repeated failure signature → DETOUR to known fix
- Graph constraint violation → reject decision

### 3. Navigator (LLM, when needed)
- Build compact forensic input
- Call Navigator (cheap Haiku call)
- Parse routing decision
- Kernel validates against graph constraints

### 4. Envelope Fallback (Legacy)
- Read RoutingSignal from handoff envelope
- Apply envelope-based routing

### 5. Escalate (Failure Case)
- Log error
- Return ESCALATE with reason

## Microloop Termination

Microloops (author ⇄ critic) exit when:

1. **Status == VERIFIED** - Critic finds no issues
2. **Status == UNVERIFIED AND can_further_iteration_help == false** - Critic says "no viable fix path"
3. **Iteration limit reached** - Configurable per flow (default: 3)
4. **Repeated failure signature** - Same error twice in a row

## Off-Road Capability

When the golden path is insufficient, flows can go "off-road":

- **Novel situations expected** - Not every scenario fits pre-defined flows
- **Always spec'd and logged** - Every routing decision produces artifacts
- **Deviations tracked** - `routing_offroad` events log all non-CONTINUE decisions

Artifacts for off-road decisions:
- `RUN_BASE/<flow>/routing/decisions.jsonl` - Append-only log
- `RUN_BASE/<flow>/routing/injections/` - Flow/node injection records
- `RUN_BASE/<flow>/routing/proposals/` - Graph extension proposals

## Goal-Aligned Test

Every routing decision passes this test:

> "Does this help achieve the flow's objective?"

If yes → proceed
If no → reject or escalate

Flow charters define the objective. Routing that drifts from charter is rejected.
