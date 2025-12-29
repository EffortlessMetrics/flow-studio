# Implementation Changes Summary

## Task: Real Claude Agent SDK Integration for ClaudeStepEngine

**Date**: 2025-12-09
**Status**: VERIFIED

---

## Files Changed

### Primary Implementation

**`/home/steven/code/Swarm/demo-swarm-dev/swarm/runtime/engines.py`** (ClaudeStepEngine class)

The `ClaudeStepEngine` class was significantly enhanced to support real Claude Agent SDK execution alongside the existing stub mode.

---

## Changes Made

### 1. Mode Switch Implementation

Added dual-mode support controlled by:
- `SWARM_CLAUDE_STEP_ENGINE_MODE` environment variable (values: `stub`, `sdk`)
- Config file `swarm/config/runtime.yaml` settings
- Default: `stub` mode (for CI/testing safety)

The engine checks `is_stub_mode("claude")` from `runtime_config.py` and also verifies SDK availability before attempting real execution.

### 2. SDK Availability Check

Added `_check_sdk_available()` method that:
- Attempts to import `claude_code_sdk`
- Caches the result to avoid repeated import attempts
- Falls back to stub mode gracefully if SDK is not installed

### 3. Tool Mapping for Step Types

Implemented intelligent tool selection based on step characteristics:

| Step Type | Tools Allowed |
|-----------|---------------|
| **Analysis** (context, analyze, assess, review, audit, check) | Read, Grep, Glob |
| **Build** (implement, author, write, fix, create, mutate) | Read, Write, Edit, Bash, Grep, Glob |
| **Default** | Read, Write, Edit, Bash, Grep, Glob |

The `_get_tools_for_step(ctx)` method inspects `step_id` and `step_role` to determine the appropriate tool set.

### 4. Prompt Building

Added `_build_prompt(ctx)` method that mirrors `GeminiStepEngine._build_prompt()` for consistency:
- Includes flow title, step info, run ID
- Agent assignments
- RUN_BASE output location instructions
- Previous step context with budget management (8000 chars total budget)
- Step execution instructions

### 5. Real SDK Execution

Added `_run_step_sdk()` and `_run_step_sdk_async()` methods:

```python
async def _run_step_sdk_async(self, ctx: StepContext):
    from claude_code_sdk import ClaudeCodeOptions, query

    # Build prompt, set up options with allowed_tools
    async for event in query(prompt=prompt, cwd=cwd, options=options):
        # Process events: messages, tool_use, tool_result, result
        # Map to RunEvents for observability
        # Collect transcript entries
```

Key features:
- Async streaming execution with `query()`
- Event mapping from SDK events to `RunEvent` types
- Token usage extraction when available
- Model name extraction from results
- Error handling with failed status on exceptions

### 6. Transcript and Receipt Writing

Both stub and SDK modes write:
- **Transcripts**: JSONL at `RUN_BASE/llm/<step_id>-<agent>-claude.jsonl`
- **Receipts**: JSON at `RUN_BASE/receipts/<step_id>-<agent>.json`

SDK mode receipts include additional fields:
- `tools_allowed`: List of tools that were permitted for this step
- Real token counts when available from SDK response
- Actual model name used

---

## Tests Addressed

All existing tests continue to pass:

### Step Engine Contract Tests (30 tests)
- Duration/status/output invariants
- Transcript JSONL validity
- Receipt JSON schema compliance
- Engine ID uniqueness

### Claude Stepwise Backend Tests (14 tests)
- Backend registration
- Capability reporting
- Run creation
- Transcript/receipt file generation
- Edge cases (nonexistent runs)

### Gemini Stepwise Backend Tests (16 tests)
- Full run lifecycle
- Step event emission
- Backend registry integration

**Total: 60 stepwise-related tests passing**

---

## Trade-offs and Decisions

### 1. Sync Wrapper for Async SDK

The `run_step()` method is synchronous (per the `StepEngine` interface), but the Claude SDK uses async. Used `asyncio.get_event_loop().run_until_complete()` as a sync wrapper. This may need refinement if the orchestrator becomes async-native.

### 2. Event Type Detection

SDK events are detected by checking both `event.type` attribute and `hasattr()` fallbacks for flexibility across SDK versions. This is defensive but may need updates as the SDK stabilizes.

### 3. Tool Selection Heuristics

Tool selection uses simple string pattern matching on step_id and step_role. This is a reasonable first pass but could be enhanced with:
- Agent-specific tool configurations
- Flow-specific tool policies
- Explicit tool declarations in step definitions

### 4. Graceful Fallback

If SDK execution fails, the engine returns a failed `StepResult` rather than falling back to stub mode. This ensures failures are visible rather than silently degraded.

---

## Usage

### Enable Real SDK Mode

```bash
# Via environment variable
export SWARM_CLAUDE_STEP_ENGINE_MODE=sdk

# Or in runtime.yaml
engines:
  claude:
    mode: sdk
```

### Prerequisites

```bash
# Install Claude Agent SDK (not yet in pyproject.toml)
pip install claude-code-sdk
```

### Run a stepwise demo

```bash
make demo-run-claude-stepwise
```

---

## Outstanding Items

1. **SDK Dependency**: `claude-code-sdk` is not yet in `pyproject.toml`. Add when ready for production use.

2. **Event Type Refinement**: The SDK event type handling is defensive; may need updates as SDK API stabilizes.

3. **Async Orchestrator**: Consider making the orchestrator async-native to avoid sync wrappers.

---

## Verification

```bash
# Run all stepwise tests
uv run pytest tests/ -k "stepwise or step_engine" -v

# Expected: 60 passed
```
