# Claims Register: What's Proof vs Promise

> **Purpose**: Honest inventory of system capabilities
> **Principle**: Apply evidence discipline to ourselves

## Why This Matters

We teach that claims need evidence. This document applies that standard to Flow Studio itself.

- **Implemented**: Code enforces it; tests prove it
- **Supported**: Pattern exists; opt-in to use
- **Aspirational**: Designed in docs; not yet wired

## The Register

### Receipts & Evidence

| Capability | Status | Evidence |
|------------|--------|----------|
| Receipt schema (required fields) | Implemented | `swarm/runtime/receipt_io.py` validates StepReceiptData |
| Receipt status enum | Implemented | Code enforces `succeeded` / `failed` |
| Token counting | Implemented | All engines report `tokens: {prompt, completion, total}` |
| Transcript capture | Implemented | JSONL files written to `RUN_BASE/<flow>/llm/` |
| Git SHA in receipts | Implemented | `capture_git_info()` records HEAD at step execution |
| Tool calls in receipts | Implemented | Wave 4 `tool_calls` field in StepReceiptData |
| Evidence binding (paths in receipts) | Supported | Schema allows `transcript_path`; not required in all paths |
| Quality events in receipts | Aspirational | QUALITY_EVENTS.md designed; not in receipt schema |

### Routing

| Capability | Status | Evidence |
|------------|--------|----------|
| RoutingOutcome structure | Implemented | `swarm/runtime/stepwise/routing/driver.py` enforces dataclass |
| Routing source audit trail | Implemented | 7 sources tracked: fast_path, deterministic, navigator, envelope_fallback, escalate, signal, detour_catalog |
| Fast-path heuristics | Implemented | `_try_fast_path()` checks terminal, explicit next, single edge |
| Deterministic fallback | Implemented | `_try_deterministic()` via CEL/condition evaluation |
| Navigator LLM routing | Implemented | `_try_navigator()` with Haiku call for decisions |
| Sidequest candidates | Implemented | `_get_sidequest_candidates()` builds candidate list from catalog |
| Utility flow injection | Implemented | `_get_utility_flow_candidates()` for INJECT_FLOW pattern |
| Why-now structured blocks | Aspirational | ROUTING_PROTOCOL.md section 3; not in code schema |
| Graph stack depth limits | Aspirational | ROUTING_PROTOCOL.md section 5; not enforced at runtime |
| Off-road logging to artifacts | Aspirational | ROUTING_PROTOCOL.md section 7; no `routing/decisions.jsonl` |
| Observations (Wisdom stream) | Aspirational | ROUTING_PROTOCOL.md section 8; no receiver implemented |

### Validation

| Capability | Status | Evidence |
|------------|--------|----------|
| FR-001: Agent bijection | Implemented | `validate_swarm.py` enforces 1:1 agent mapping |
| FR-002: Frontmatter validation | Implemented | YAML checks for required fields + design constraints |
| FR-003: Flow references | Implemented | Typo detection with Levenshtein distance |
| FR-004: Skills validation | Implemented | Checks `SKILL.md` file existence |
| FR-005: RUN_BASE paths | Implemented | Placeholder detection, rejects hardcoded paths |
| FR-006: Prompt sections | Supported | Optional with `--check-prompts` flag |

### Execution

| Capability | Status | Evidence |
|------------|--------|----------|
| Stepwise execution | Implemented | One LLM call per step via orchestrator |
| Three-phase lifecycle | Implemented | Work -> Finalize -> Route in `session_runner.py` |
| Hot context (Claude SDK) | Implemented | `execute_step_session()` preserves session between phases |
| Microloop iteration | Implemented | Author <-> Critic loops with loop_state tracking |
| Iteration limits | Implemented | Configurable via routing config per step |
| Loop state tracking | Implemented | `_update_loop_state_if_looping()` increments counters |
| Dangerous command blocking | Implemented | `create_dangerous_command_hook()` in pre-hooks |
| Telemetry hooks | Implemented | Pre/post hooks for tool call tracking |
| Interrupt/resume | Supported | SDK supports; not fully surfaced in UI |
| Shadow fork isolation | Aspirational | Described in BOUNDARY_PHYSICS.md; not enforced |

### Selftest & Governance

| Capability | Status | Evidence |
|------------|--------|----------|
| Selftest 16-step contract | Implemented | `selftest_config.py` defines all 16 steps |
| Three tiers (KERNEL/GOVERNANCE/OPTIONAL) | Implemented | `SelfTestTier` enum in config |
| Degradation logging | Implemented | V1.1 schema with severity, category |
| AC traceability | Implemented | `ac_ids` field links steps to acceptance criteria |
| Override expiration | Supported | 24-hour default; not enforced in all paths |
| Wisdom -> Rules pipeline | Aspirational | No implementation connecting learnings to rules |

### Quality Events

| Capability | Status | Evidence |
|------------|--------|----------|
| Interface Lock checks | Aspirational | QUALITY_EVENTS.md designed; agent prompts only |
| Complexity Cap enforcement | Aspirational | Thresholds in docs; no automatic measurement |
| Test Depth tracking | Aspirational | Coverage thresholds in docs; not wired to receipts |
| Security Airbag scans | Aspirational | Agent prompts reference; no SAST integration |
| Lint Clean verification | Supported | auto-linter skill exists; not in quality event schema |
| Doc Sync validation | Aspirational | Described; no automation |

### Transport & Engines

| Capability | Status | Evidence |
|------------|--------|----------|
| Claude SDK engine | Implemented | `swarm/runtime/engines/claude/` full implementation |
| Gemini CLI engine | Implemented | `swarm/runtime/engines/gemini/` |
| Stub engine (zero-cost demo) | Implemented | All engines support stub mode |
| Engine-agnostic receipt format | Implemented | `receipt_io.py` shared across engines |
| Engine fallback with reason tracking | Implemented | `fallback_reason` field in receipts |
| OpenAI engine | Aspirational | PORTS_AND_ADAPTERS.md mentions; not implemented |

## How to Read This

**Implemented** = Safe to depend on; used in production paths
**Supported** = Available but verify configuration; opt-in
**Aspirational** = Don't claim in production; roadmap item

## Evidence Pointers

For any claim above, here's where to look:

| Category | Primary Evidence |
|----------|------------------|
| Receipts | `swarm/runtime/receipt_io.py` |
| Routing | `swarm/runtime/stepwise/routing/driver.py` |
| Validation | `swarm/tools/validate_swarm.py` |
| Execution | `swarm/runtime/engines/claude/session_runner.py` |
| Selftest | `swarm/tools/selftest_config.py` |
| Quality Events | `docs/QUALITY_EVENTS.md` (spec only) |

## Updating This Register

When moving capability from Aspirational -> Implemented:
1. Write the code
2. Add tests
3. Update this register with evidence pointer

When adding new capability:
1. Start as Aspirational with design doc reference
2. Graduate to Supported when pattern exists
3. Graduate to Implemented when tests prove it

This is the discipline: claims require evidence, including our own.

---

## Version History

| Date | Change |
|------|--------|
| 2025-01-11 | Initial register created |
