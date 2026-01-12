# SDK-Native Stepwise Implementation Plan

> Target state: Each step is a Claude Code SDK call with context pack + custom prompt + default system prompt.

This document outlines the concrete investigation tasks and implementation PRs to achieve SDK-native stepwise orchestration.

---

## Current State (After PR1-PR3)

### Completed

1. **PR1: Naming Cleanup** - `ClaudeSDKClient` renamed to `StepSessionClient` to avoid collision with upstream `claude_code_sdk.ClaudeSDKClient`
2. **PR2: Transport Port Interface** - Created `swarm/runtime/transports/` with:
   - `port.py` - Defines `TransportProtocol`, `StepSessionProtocol`, `TransportCapabilities`
   - `claude_sdk_transport.py` - Claude SDK adapter implementing the protocol
   - Capability presets: `CLAUDE_SDK_CAPABILITIES`, `CLAUDE_CLI_CAPABILITIES`, `GEMINI_CLI_CAPABILITIES`, `STUB_CAPABILITIES`
3. **PR3: output_format Verification** - Confirmed WP6 session path uses `output_format` for finalize/route

### Current Transport Capabilities

| Transport | output_format | interrupts | hooks | hot_context | streaming |
|-----------|---------------|------------|-------|-------------|-----------|
| Claude SDK | ✅ | ✅ | ✅ | ✅ | ✅ |
| Claude CLI | ❌ | ❌ | ❌ | ❌ | ✅ |
| Gemini CLI | ❌ | ❌ | ❌ | ❌ | ✅ |
| Stub | ✅ | ✅ | ✅ | ✅ | ✅ |

---

## Investigation Tasks

### Investigation 1: Claude SDK Settings Loading + System Prompt Composition

**Questions to Answer:**
1. When do we use `setting_sources=["project"]` vs other configurations?
2. How is system prompt composed (preset + append pattern)?
3. What belongs in `CLAUDE.md` vs passed programmatically?

**Current Implementation:**
- `swarm/runtime/claude_sdk.py:480-485` - Always uses `preset=claude_code` with optional append
- `swarm/runtime/claude_sdk.py:487-496` - `setting_sources=["project"]` loads `.claude/settings.json` and `CLAUDE.md`
- Agent persona loaded from `.claude/agents/<key>.md` as system prompt append

**Decision to Make:**
- Confirm we want `preset=claude_code` for all steps (gives Claude Code tooling)
- Decide when to skip settings loading (e.g., deterministic CI runs)

**Acceptance Criteria:**
- Document the exact composition: `preset(claude_code) + agent_persona + step_discipline_append`

---

### Investigation 2: Work Phase Streaming Model + Events → Receipts Mapping

**Questions to Answer:**
1. Which SDK event stream API should we use: `receive_response()` vs `receive_messages()`?
2. How do SDK events map to `events.jsonl` and receipts?
3. What telemetry data should be preserved?

**Current Implementation:**
- `swarm/runtime/claude_sdk.py:1451-1569` - Uses `async for event in sdk.query()`
- Event types: `AssistantMessageEvent`, `ToolUseEvent`, `ToolResultEvent`, `ResultEvent`
- Token counts extracted from `ResultEvent.token_usage`

**Decision to Make:**
- Whether to enrich events with SDK-specific metadata
- Normalization contract for cross-transport receipts

**Acceptance Criteria:**
- One `ToolRun` / `ToolOutput` representation used in receipts across all transports

---

### Investigation 3: Hooks as Enforcement Surface

**Questions to Answer:**
1. What dangerous patterns are currently blocked?
2. What file boundaries need enforcement?
3. What telemetry is collected?

**Current Implementation:**
- `swarm/runtime/claude_sdk.py:2015-2064` - `create_dangerous_command_hook()` blocks:
  - `rm -rf /`, `git push --force`, `git reset --hard`, `chmod -R 777`, fork bombs
- `swarm/runtime/claude_sdk.py:2067-2106` - `create_telemetry_hook()` collects timings
- `swarm/runtime/claude_sdk.py:2109-2161` - `create_file_access_audit_hook()` audits Read/Write/Edit

**Decision to Make:**
- Move workspace boundary enforcement into hooks (currently kernel-level)
- Define what remains kernel-level (stage → sanitize → persist)

**Acceptance Criteria:**
- All foot-gun blocking in hooks
- All telemetry collection in hooks
- Kernel handles only stage/sanitize/persist

---

### Investigation 4: Interrupt + Stop Semantics for Partial Handoff

**Questions to Answer:**
1. How does SDK-level cancellation work?
2. What state needs persisting on interrupt?
3. How does resumption work?

**Current Implementation:**
- `swarm/runtime/transports/claude_sdk_transport.py:144-151` - `interrupt()` is a no-op TODO
- SDK supports `asyncio.CancelledError` handling
- Partial handoff not currently implemented

**Decision to Make:**
- Define `handoff_partial.json` schema
- Define which phases can be interrupted (work yes, finalize/route probably no)

**Acceptance Criteria:**
- Interrupt during work → persist `handoff_partial.json`
- Route to PAUSE / NEEDS_HUMAN cleanly
- Resume continues from disk artifacts

---

### Investigation 5: Gemini CLI Tool Visibility vs Kernel-Runs-Tools Decision

**Questions to Answer:**
1. Can we observe Gemini tool calls (names, inputs, outputs)?
2. Can we intercept/block tool calls?
3. Should we delegate tools to Gemini or run them ourselves?

**Current Implementation:**
- `swarm/runtime/engines/gemini.py:616-685` - `_map_gemini_event()` observes:
  - `tool_use` events with tool name and input
  - `tool_result` events with success and output
- Gemini CLI is fully autonomous - Python observes but doesn't control

**Key Finding:**
> Gemini CLI runs tools internally. Python kernel **observes** via JSONL events but **cannot intercept**.

**Decision to Make:**
1. **Option A: Gemini runs tools (current)** - Trust Gemini's sandbox, observe via events
2. **Option B: Kernel runs tools** - Have Gemini emit tool plans, kernel executes

**Recommendation:** Option A for now. Gemini's sandbox is trusted. Option B would require significant protocol changes.

**Acceptance Criteria:**
- Document decision
- If Option B: Define tool plan schema and execution protocol

---

### Investigation 6: Cross-Transport ToolRun/ToolOutput Normalization

**Questions to Answer:**
1. What's the normalized representation of a tool call?
2. How do we handle transports with different tool visibility?
3. How does this affect PR cockpit generation?

**Current State:**
- Claude SDK: Full tool call visibility via `ToolUseEvent`/`ToolResultEvent`
- Gemini CLI: Tool visibility via JSONL events
- Claude CLI: Subprocess output, no structured tool events

**Proposed Normalization:**

```python
@dataclass
class NormalizedToolCall:
    tool_name: str
    input: Dict[str, Any]
    output: Optional[str]
    success: bool
    duration_ms: int
    blocked: bool = False
    blocked_reason: Optional[str] = None
    source: str = "unknown"  # "sdk", "cli-observed", "kernel-executed"
```

**Acceptance Criteria:**
- One `NormalizedToolCall` format in all receipts
- PR cockpit generator consumes only normalized format

---

## Implementation PRs

### PR4: Consolidate Routing (HIGH PRIORITY)

**Problem:** 6 routing implementations with duplicated microloop exit logic:

| Location | Function | Duplication |
|----------|----------|-------------|
| `router.py:767-836` | `SmartRouter._check_exit_conditions()` | status==VERIFIED, max_iterations, can_further_iteration_help |
| `router.py:1232-1300` | `StepRouter.filter_exit_conditions()` | Same logic, different structure |
| `engines/claude/router.py:271-343` | `check_microloop_termination()` | Same checks |
| `engines/claude/router.py:714-749` | `route_from_routing_config()` | Same checks for MICROLOOP |
| `engines/claude/router.py:887-1010` | `smart_route()` | Same checks with audit trail |

**Additionally:** `engines/claude/router.py:476-489` parses JSON from markdown fences instead of using `output_format`.

**Deliverables:**
1. Make `swarm/runtime/stepwise/routing/driver.py` the only authoritative router
2. Create shared `_check_microloop_exit()` helper
3. Delete or delegate all duplicate logic
4. Remove markdown fence JSON parsing (use `output_format` or fail gracefully)

**Files to Modify:**
- `swarm/runtime/stepwise/routing/driver.py` - Becomes canonical
- `swarm/runtime/router.py` - Delegate to driver or delete
- `swarm/runtime/engines/claude/router.py` - Remove duplicates, add deprecation warnings

**Acceptance Criteria:**
- One place to understand routing decisions
- All microloop exit logic in one helper
- No markdown fence JSON parsing in production paths

---

### PR5: Real Claude Agent SDK Transport Using Upstream SDK

**Problem:** Current transport wraps our `StepSessionClient` which wraps upstream SDK. Should be thinner.

**Deliverables:**
1. Create `ClaudeAgentSdkTransport` that uses upstream `claude_code_sdk.ClaudeSDKClient` directly
2. Work phase: `client.query()` with streaming
3. Finalize/route: One-shot `query()` with `output_format` schemas
4. Hooks: Wire to SDK hook infrastructure

**Key Implementation:**
```python
class ClaudeAgentSdkTransport:
    async def open_session(self, ...):
        # Use upstream SDK directly
        from claude_code_sdk import ClaudeSDKClient, ClaudeCodeOptions

        client = ClaudeSDKClient()
        options = ClaudeCodeOptions(
            permission_mode="bypassPermissions",
            system_prompt={"type": "preset", "preset": "claude_code", "append": persona},
            setting_sources=["project"],
            output_format=schema if phase in ["finalize", "route"] else None,
        )
        async for event in client.query(prompt=prompt, options=options):
            yield event
```

**Acceptance Criteria:**
- Transport uses upstream SDK, not internal wrapper
- Work/finalize/route phases work correctly
- Hooks wired for foot-gun blocking

---

### PR6: Gemini CLI Thick Adapter with Clear Boundaries

**Problem:** Gemini CLI has different capabilities; adapter must subsume missing features.

**Decision from Investigation 5:** Gemini runs tools (Option A).

**Deliverables:**
1. Document explicitly: "Gemini CLI is autonomous; kernel observes via JSONL"
2. Implement structured output microloop for finalize/route:
   ```python
   async def _finalize_with_microloop(self, response: str, schema: dict) -> dict:
       # Parse JSON from response
       # Validate against schema
       # If invalid: reprompt with validation errors (max 3 retries)
   ```
3. Normalize tool events to `NormalizedToolCall`

**Acceptance Criteria:**
- Gemini finalize/route produce valid JSON via microloop
- Tool events normalized for receipts
- Clear documentation of capability differences

---

### PR7: Unified Receipts with Normalized Tool Outputs

**Deliverables:**
1. Define `NormalizedToolCall` dataclass
2. Update receipt writers to use normalized format
3. Update PR cockpit generator to consume normalized receipts

**Receipt Format:**
```json
{
  "step_id": "1",
  "flow_key": "build",
  "run_id": "run-2026-01-10",
  "transport": "claude-sdk",
  "duration_ms": 15234,
  "tool_calls": [
    {
      "tool_name": "Write",
      "input": {"path": "src/main.py", "content": "..."},
      "output": "File written",
      "success": true,
      "duration_ms": 45,
      "blocked": false,
      "source": "sdk"
    }
  ],
  "token_counts": {"prompt": 5000, "completion": 2000}
}
```

**Acceptance Criteria:**
- All transports produce same receipt format
- PR cockpit works regardless of which transport executed

---

## Proposed PR Sequence

```
PR4: Routing Consolidation (HIGH PRIORITY)
 ↓
PR5: Real Claude Agent SDK Transport
 ↓
PR6: Gemini CLI Thick Adapter
 ↓
PR7: Unified Receipts
```

**Rationale:**
1. PR4 unblocks clean routing for all transports
2. PR5 makes Claude SDK "genuinely SDK-native"
3. PR6 handles Gemini as the "thick adapter" case
4. PR7 normalizes across all transports

---

## Capability Matrix Extension

Current `TransportCapabilities` should add:

```python
@dataclass
class TransportCapabilities:
    # Existing
    supports_output_format: bool = False
    supports_interrupts: bool = False
    supports_hooks: bool = False
    supports_hot_context: bool = True
    supports_streaming: bool = True
    supports_rewind: bool = False
    max_context_tokens: int = 0
    provider_name: str = "unknown"

    # NEW: Tooling model
    supports_native_tools: bool = False  # Claude-style tool calls
    supports_tool_observation: bool = False  # Can observe tool calls
    supports_tool_interception: bool = False  # Can block tool calls

    # NEW: Settings integration
    supports_project_context: bool = False  # CLAUDE.md / settings.json loading
```

**Updated Matrix:**

| Transport | native_tools | tool_observation | tool_interception | project_context |
|-----------|--------------|------------------|-------------------|-----------------|
| Claude SDK | ✅ | ✅ | ✅ (via hooks) | ✅ |
| Claude CLI | ❌ | ❌ | ❌ | ✅ (reads files) |
| Gemini CLI | ❌ | ✅ | ❌ | ❌ |
| Stub | ✅ | ✅ | ✅ | ✅ |

---

## Implementation Timeline

**Phase 1 (Immediate):** PR4 - Routing Consolidation
- Unblocks all other work
- Eliminates 5 redundant microloop exit implementations
- Removes markdown fence JSON parsing

**Phase 2 (Next):** PR5 + PR6 - Transport Implementations
- Can be done in parallel
- PR5: Claude SDK becomes thin wrapper over upstream
- PR6: Gemini CLI becomes explicit "thick adapter"

**Phase 3 (Final):** PR7 - Unified Receipts
- Depends on PR5/PR6 for tool normalization
- Enables transport-agnostic PR cockpit

---

## Open Questions for User Decision

1. **Gemini tool execution model:** Confirm Option A (Gemini autonomous) vs Option B (kernel executes)?

2. **Interrupt granularity:** Interrupt only work phase, or allow interrupt during finalize/route?

3. **Capability extensions:** Should we add the new capability fields now, or defer?

4. **Legacy router deprecation:** Hard delete or deprecation warnings first?
