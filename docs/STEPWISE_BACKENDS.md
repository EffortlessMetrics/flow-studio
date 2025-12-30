# Stepwise Backends

> For: Developers integrating stepwise execution, operators choosing backends.
>
> **Prerequisites:** [FLOW_STUDIO.md](./FLOW_STUDIO.md) | **Related:** CLAUDE.md (Technology Stack section)

---

## Stepwise in 60 Seconds

```bash
# 1. Run a stepwise demo
make demo-run-claude-stepwise

# 2. View it in Flow Studio
make flow-studio
# Open http://localhost:5000/?run=stepwise-claude

# 3. Inspect a transcript
cat swarm/examples/stepwise-claude/signal/llm/normalize-signal-normalizer-claude.jsonl
```

**What happened?** Each flow step executed as a separate LLM call, producing:
- **Transcript**: Conversation log (`llm/*.jsonl`)
- **Receipt**: Execution metadata (`receipts/*.json`)
- **Events**: Timeline in `events.jsonl`

Continue reading for configuration, architecture, and extension details.

---

## What is Stepwise Execution?

In **batch execution** (standard mode), a backend runs an entire flow in one LLM call.
The LLM receives all step instructions upfront and executes them sequentially within
a single session. This is fast but offers limited visibility into step-level behavior.

In **stepwise execution**, the orchestrator:

1. Loads the flow definition from `flow_registry`
2. Iterates through each step in order
3. Makes a **separate LLM call per step**
4. Passes context from previous steps to subsequent steps
5. Persists events and artifacts after each step

This approach trades throughput for observability and control and token efficiency.

### Benefits of Stepwise Execution

| Benefit | Description |
|---------|-------------|
| **Per-step observability** | Each step emits separate `step_start` and `step_end` events |
| **Context handoff** | Previous step outputs are included in subsequent step prompts |
| **Better error isolation** | When a step fails, you know exactly which one and why |
| **Teaching mode** | Supports pausing at step boundaries for demos and debugging |
| **Engine flexibility** | Same orchestrator works with different LLM backends |

---

## Available Stepwise Backends

| Backend ID | Engine | Description |
|------------|--------|-------------|
| `gemini-step-orchestrator` | `GeminiStepEngine` | Stepwise execution via Gemini CLI |
| `claude-step-orchestrator` | `ClaudeStepEngine` | Stepwise execution via Claude Agent SDK |

Both backends use the `GeminiStepOrchestrator` class (despite its name) with
different underlying `StepEngine` implementations. The orchestrator handles
flow traversal while the engine handles LLM communication.

---

## Architecture

### Component Overview

```
Backend (GeminiStepwiseBackend / ClaudeStepwiseBackend)
    |
    v
Orchestrator (GeminiStepOrchestrator)
    |
    +-- flow_registry: Loads flow definitions and steps
    |
    +-- engine: StepEngine implementation
    |       |
    |       v
    |   GeminiStepEngine or ClaudeStepEngine
    |       |
    |       v
    |   LLM (Gemini CLI or Claude Agent SDK)
    |
    +-- storage: Persists events, summaries, transcripts
```

### StepEngine Abstraction

The `StepEngine` interface (`swarm/runtime/engines.py`) defines how individual
steps are executed. All engines implement:

```python
class StepEngine(ABC):
    @property
    @abstractmethod
    def engine_id(self) -> str:
        """Unique identifier (e.g., 'gemini-step', 'claude-step')."""
        ...

    @abstractmethod
    def run_step(self, ctx: StepContext) -> Tuple[StepResult, Iterable[RunEvent]]:
        """Execute a step and return result + events."""
        ...
```

### StepContext Dataclass

Contains all information needed to execute a step:

```python
@dataclass
class StepContext:
    repo_root: Path          # Repository root path
    run_id: str              # Run identifier
    flow_key: str            # Flow being executed (signal, plan, build, etc.)
    step_id: str             # Step identifier within the flow
    step_index: int          # 1-based step index
    total_steps: int         # Total steps in the flow
    spec: RunSpec            # Run specification
    flow_title: str          # Human-readable flow title
    step_role: str           # Description of what this step does
    step_agents: Tuple[str]  # Agent keys assigned to this step
    history: List[Dict]      # Previous step results for context
    extra: Dict[str, Any]    # Additional context-specific data

    @property
    def run_base(self) -> Path:
        """Get RUN_BASE path for this step's artifacts."""
        return repo_root / "swarm" / "runs" / run_id / flow_key
```

### StepResult Dataclass

Returned by engines after step execution:

```python
@dataclass
class StepResult:
    step_id: str                      # Step identifier
    status: str                       # "succeeded" | "failed" | "skipped"
    output: str                       # Summary text describing what happened
    error: Optional[str] = None       # Error message if failed
    duration_ms: int = 0              # Execution duration in milliseconds
    artifacts: Optional[Dict] = None  # Artifact paths/metadata produced
```

### Orchestrator

The `GeminiStepOrchestrator` (`swarm/runtime/orchestrator.py`) coordinates
stepwise execution:

1. **Run creation**: Generates run ID, creates directories, writes initial metadata
2. **Flow loading**: Gets flow definition from `flow_registry`
3. **Step iteration**: Loops through steps, building context for each
4. **Engine invocation**: Calls `engine.run_step(ctx)` for each step
5. **Event persistence**: Writes engine events to `events.jsonl`
6. **Status updates**: Updates run summary as execution progresses

Key method:

```python
def run_stepwise_flow(
    self,
    flow_key: str,
    spec: RunSpec,
    start_step: Optional[str] = None,
    end_step: Optional[str] = None,
) -> RunId:
    """Execute a flow step-by-step, one LLM call per step."""
```

---

## Transcript and Receipt Format

### Transcripts

Stepwise backends write detailed transcripts of LLM interactions.

**Location**: `RUN_BASE/<flow>/llm/<step_id>-<agent>-<engine>.jsonl`

**Example path**: `swarm/runs/run-20251209-143022-abc123/signal/llm/S1-context-loader-claude.jsonl`

**Format**: JSONL (one JSON object per line)

```jsonl
{"timestamp": "2025-01-15T10:00:00Z", "role": "system", "content": "Executing step S1 with agent context-loader"}
{"timestamp": "2025-01-15T10:00:01Z", "role": "user", "content": "Step role: Load relevant context from the codebase"}
{"timestamp": "2025-01-15T10:00:05Z", "role": "assistant", "content": "I have loaded the following files..."}
```

### Receipts

Step receipts capture execution metadata for auditing and debugging.

**Location**: `RUN_BASE/<flow>/receipts/<step_id>-<agent>.json`

**Example path**: `swarm/runs/run-20251209-143022-abc123/signal/receipts/S1-context-loader.json`

**Format**: JSON with execution metadata:

```json
{
  "engine": "claude-step",
  "mode": "sdk",
  "provider": "anthropic",
  "model": "claude-sonnet-4-20250514",
  "step_id": "S1",
  "flow_key": "signal",
  "run_id": "run-20251209-143022-abc123",
  "agent_key": "context-loader",
  "started_at": "2025-01-15T10:00:00Z",
  "completed_at": "2025-01-15T10:00:05Z",
  "duration_ms": 5000,
  "status": "succeeded",
  "tokens": {"prompt": 1200, "completion": 800, "total": 2000},
  "transcript_path": "llm/S1-context-loader-claude.jsonl"
}
```

The `mode` and `provider` fields indicate how the step was executed:
- `mode`: Engine mode used (`stub`, `sdk`, or `real`)
- `provider`: Provider profile (`anthropic`, `anthropic_compat`)

---

## Engines & Providers

The stepwise system supports multiple LLM providers behind a unified interface.

### Provider Profiles

| Provider | Base URL | Description |
|----------|----------|-------------|
| `anthropic` | api.anthropic.com | Direct Anthropic Claude API |
| `anthropic_compat` | Configurable | Anthropic-compatible APIs (GLM, etc.) |

### Engine Modes

Each engine can run in different modes:

| Engine | Mode | Description |
|--------|------|-------------|
| `claude-step` | `stub` | Synthetic responses for testing (default) |
| `claude-step` | `sdk` | Real Claude Agent SDK execution |
| `claude-step` | `cli` | Real Claude CLI execution (`claude --output-format stream-json`) |
| `gemini-step` | `stub` | Synthetic responses for testing |
| `gemini-step` | `cli` | Real Gemini CLI execution |

### Which Backend Should I Use?

**If you have a Claude Code seat (no API key):**
- Use `claude-step-orchestrator` with `mode: cli` (NEW!)
- Your Claude Code CLI handles authentication automatically
- Full stepwise execution with per-step transcripts
- Works with Claude Code or GLM Coding Plan via your CLI settings

**If you have an Anthropic API key:**
- Use `claude-step-orchestrator` with `mode: sdk`
- Set `ANTHROPIC_API_KEY` environment variable
- Full stepwise execution with per-step transcripts

**If you have a GLM Coding Plan (Z.AI):**
- **Option 1 (CLI):** Use `claude-step-orchestrator` with `mode: cli`
  - Your Claude Code CLI should already be configured for GLM
  - No environment variables needed in the swarm
- **Option 2 (SDK):** Use `claude-step-orchestrator` with `mode: sdk`
  - Set `ANTHROPIC_BASE_URL=https://api.z.ai/api/anthropic`
  - Set `ANTHROPIC_API_KEY` to your GLM key

**If you want cheap testing:**
- Use `gemini-step-orchestrator` with Gemini CLI
- Good for iteration before using Claude

**If you just want to explore the harness:**
- Leave everything at defaults (`mode: stub`)
- Run `make demo-run-stepwise` to see synthetic runs

### Quick Reference: Three Personas

| Persona | Description | Command | API Key Required? |
|---------|-------------|---------|-------------------|
| **CI / Demo** | Testing flows, exploring harness | `make stepwise-sdlc-stub` | No |
| **Agent SDK** | Local dev with Claude subscription (Max/Team/Enterprise) | TypeScript/Python Agent SDK | No (uses Claude login) |
| **API User** | Server-side / multi-user integration | `make stepwise-sdlc-claude-sdk` | Yes (`ANTHROPIC_API_KEY`) |

> **Understanding Claude Surfaces**
>
> The **Agent SDK** (TypeScript/Python) is "headless Claude Code"—it reuses your Claude subscription
> when you're logged into Claude Code on your machine. No separate API account needed for local dev.
> Use the **HTTP API** (`ANTHROPIC_API_KEY`) for server-side, CI, or multi-tenant deployments.
>
> The **CLI mode** (`make stepwise-sdlc-claude-cli`) is a lower-level surface that bridges
> to Claude Code CLI. It's useful for debugging and for providers without an Agent SDK (Gemini CLI, etc.).
>
> **Try it now**: `make agent-sdk-ts-demo` or `make agent-sdk-py-demo`
> See `examples/agent-sdk-ts/` and `examples/agent-sdk-py/` for working examples.

For a step-by-step walkthrough, see [swarm/runbooks/stepwise-fastpath.md](../swarm/runbooks/stepwise-fastpath.md).

---

## Configuration

### Mode Switches

Both stepwise engines support **stub mode** for development and CI testing.
In stub mode, engines return synthetic responses without calling real LLMs.

| Variable | Values | Description |
|----------|--------|-------------|
| `SWARM_GEMINI_STUB` | `0`, `1` | Force Gemini stub mode (default: `1`) |
| `SWARM_GEMINI_CLI` | path | Override Gemini CLI executable path |
| `SWARM_CLAUDE_STEP_ENGINE_MODE` | `stub`, `sdk`, `cli` | Claude engine mode |
| `SWARM_CLAUDE_CLI` | path | Override Claude CLI executable path |

**Default behavior**:
- `SWARM_GEMINI_STUB=1`: Stub mode is enabled by default
- Set `SWARM_GEMINI_STUB=0` to use real Gemini CLI (requires CLI installed)
- Set `SWARM_CLAUDE_STEP_ENGINE_MODE=sdk` to use real Claude Agent SDK
- Set `SWARM_CLAUDE_STEP_ENGINE_MODE=cli` to use Claude CLI (NEW!)

**Mode selection order for Claude:**
1. Environment variable: `SWARM_CLAUDE_STEP_ENGINE_MODE`
2. Config file: `swarm/config/runtime.yaml`
3. Default: `stub`

### Configuration Examples

#### Using Anthropic API

```yaml
# swarm/config/runtime.yaml
engines:
  claude:
    mode: "sdk"
    provider: "anthropic"
```

```bash
export ANTHROPIC_API_KEY=sk-ant-...
make demo-run-claude-stepwise
```

#### Using GLM via Z.AI (SDK)

```yaml
# swarm/config/runtime.yaml
engines:
  claude:
    mode: "sdk"
    provider: "anthropic_compat"
    env:
      ANTHROPIC_BASE_URL: "https://api.z.ai/api/anthropic"
```

```bash
export ANTHROPIC_BASE_URL=https://api.z.ai/api/anthropic
export ANTHROPIC_API_KEY=<your-glm-key>
make demo-run-claude-stepwise
```

#### Using Claude CLI (Claude Code / GLM Coding Plan)

For users with Claude Code or GLM Coding Plan configured in their CLI:

```yaml
# swarm/config/runtime.yaml
engines:
  claude:
    mode: "cli"
    provider: "anthropic"  # or "anthropic_compat" for GLM
```

```bash
# No environment variables needed - uses your CLI config!
make demo-run-claude-stepwise

# Or via the CLI tool with mode flag:
uv run swarm/tools/demo_stepwise_run.py \
  --backend claude-step-orchestrator \
  --mode cli \
  --flows build
```

This mode uses `claude --output-format stream-json` to execute steps,
leveraging your existing Claude Code CLI authentication.

#### Using Gemini CLI

```yaml
# swarm/config/runtime.yaml
engines:
  gemini:
    mode: "real"
```

```bash
export SWARM_GEMINI_STUB=0
make demo-run-gemini-stepwise
```

### Stub Mode Rationale

Stub mode is the default because:

1. **CI/CD safety**: Tests run without LLM credentials or API calls
2. **Fast iteration**: Developers can test orchestration logic without LLM latency
3. **Cost control**: No LLM costs during development or testing
4. **Deterministic testing**: Stub responses are predictable

The stub mode still writes transcript and receipt files with placeholder content,
allowing end-to-end testing of the orchestrator, storage, and Flow Studio UI.

---

## Using Stepwise Backends

### In Flow Studio

1. Open Flow Studio: `make flow-studio`
2. In the left sidebar, locate the **Backend** dropdown (above the flow list)
3. Select `Gemini CLI (stepwise)` or `Claude Agent SDK (stepwise)`
4. Start a run using the selected backend
5. View step-by-step progress in the Events Timeline

The Run Detail modal shows:
- `step_start` events when each step begins
- `step_end` or `step_error` events when steps complete
- Engine-specific events from the LLM (tool_start, tool_end, etc.)

### Via Python API

```python
from swarm.runtime.backends import get_backend
from swarm.runtime.types import RunSpec

# Get a stepwise backend
backend = get_backend("gemini-step-orchestrator")
# or
backend = get_backend("claude-step-orchestrator")

# Create a run specification
spec = RunSpec(
    flow_keys=["signal", "plan"],
    backend="gemini-step-orchestrator",
    initiator="api",
    params={"title": "My Stepwise Run"},
)

# Start the run (returns immediately, runs in background)
run_id = backend.start(spec)

# Check status
summary = backend.get_summary(run_id)
print(f"Status: {summary.status}")

# Get events
events = backend.get_events(run_id)
for event in events:
    print(f"{event.kind}: {event.step_id or 'run-level'}")
```

### Via Orchestrator Directly

For finer control, use the orchestrator directly:

```python
from pathlib import Path
from swarm.runtime.orchestrator import get_orchestrator
from swarm.runtime.engines import ClaudeStepEngine
from swarm.runtime.types import RunSpec

# Create orchestrator with specific engine
repo_root = Path("/path/to/repo")
engine = ClaudeStepEngine(repo_root)
orchestrator = get_orchestrator(engine=engine, repo_root=repo_root)

# Run a single flow stepwise
spec = RunSpec(flow_keys=["build"], backend="claude-step-orchestrator")
run_id = orchestrator.run_stepwise_flow("build", spec)

# Optional: Run partial flow (steps 2-5 only)
run_id = orchestrator.run_stepwise_flow(
    "build",
    spec,
    start_step="S2",
    end_step="S5",
)
```

---

## Development

### Running Tests

```bash
# Run Gemini stepwise backend tests
uv run pytest tests/test_gemini_stepwise_backend.py -v

# Run Claude stepwise backend tests
uv run pytest tests/test_claude_stepwise_backend.py -v

# Run routing microloop tests
uv run pytest tests/test_build_stepwise_routing.py -v

# Run all stepwise-related tests
uv run pytest tests/ -k "stepwise" -v
```

### Running Demos

**Basic demos (signal + plan flows):**

```bash
make demo-run-gemini-stepwise  # Gemini stepwise backend (stub mode)
make demo-run-claude-stepwise  # Claude stepwise backend (stub mode)
make demo-run-stepwise         # Run both
```

**Full SDLC demos (signal + plan + build flows):**

```bash
make stepwise-sdlc-gemini      # Gemini stepwise (stub mode)
make stepwise-sdlc-claude-cli  # Claude CLI stepwise
make stepwise-sdlc-claude-sdk  # Claude Agent SDK stepwise (requires API key)
make stepwise-sdlc-stub        # Both backends in stub mode
```

**View help:**

```bash
make stepwise-help
```

### Golden Examples

Pre-generated stepwise runs are available in `swarm/examples/`:

| Example | Backend | Flows | Description |
|---------|---------|-------|-------------|
| `stepwise-gemini/` | Gemini | signal, plan | Lightweight mode (events only) |
| `stepwise-claude/` | Claude | signal, plan | Rich mode (transcripts + receipts) |
| `stepwise-build-gemini/` | Gemini | signal, plan, build | Build flow (lightweight) |
| `stepwise-build-claude/` | Claude | signal, plan, build | Build flow (rich mode) |
| `stepwise-gate-claude/` | Claude | signal, plan, build, gate | Through Gate verification |
| `stepwise-deploy-claude/` | Claude | signal, plan, build, gate, deploy | Through Deploy |
| `stepwise-sdlc-claude/` | Claude | all 7 flows | **Complete SDLC** (44 steps, recommended) |

Each example includes:
- `spec.json` - Run specification
- `meta.json` - Run metadata
- `events.jsonl` - Event log
- `README.md` - Documentation

Claude examples also include:
- `<flow>/llm/*.jsonl` - Per-step transcripts
- `<flow>/receipts/*.json` - Per-step execution receipts

### Testing in Stub Mode

Tests use `isolated_runs_env` fixture which:
1. Creates temporary `swarm/runs/` and `swarm/examples/` directories
2. Monkeypatches storage module to use temporary paths
3. Resets RunService singleton before/after each test

Example test fixture:

```python
@pytest.fixture
def isolated_runs_env(tmp_path, monkeypatch):
    runs_dir = tmp_path / "swarm" / "runs"
    examples_dir = tmp_path / "swarm" / "examples"
    runs_dir.mkdir(parents=True)
    examples_dir.mkdir(parents=True)

    monkeypatch.setattr(storage, "RUNS_DIR", runs_dir)
    monkeypatch.setattr(storage, "EXAMPLES_DIR", examples_dir)

    RunService.reset()
    yield {"runs_dir": runs_dir, "examples_dir": examples_dir}
    RunService.reset()
```

### Adding a New StepEngine

To add a new LLM backend (e.g., for OpenAI):

1. **Create engine class** in `swarm/runtime/engines.py`:

```python
class OpenAIStepEngine(StepEngine):
    @property
    def engine_id(self) -> str:
        return "openai-step"

    def run_step(self, ctx: StepContext) -> Tuple[StepResult, Iterable[RunEvent]]:
        # Build prompt from ctx
        # Call OpenAI API
        # Write transcript and receipt
        # Return StepResult and events
        ...
```

2. **Create backend class** in `swarm/runtime/backends.py`:

```python
class OpenAIStepwiseBackend(RunBackend):
    def _get_orchestrator(self) -> GeminiStepOrchestrator:
        from .engines import OpenAIStepEngine
        from .orchestrator import get_orchestrator
        return get_orchestrator(
            engine=OpenAIStepEngine(self._repo_root),
            repo_root=self._repo_root,
        )
    # ... implement required methods
```

3. **Register in backend registry**:

```python
_BACKEND_REGISTRY: dict[BackendId, type[RunBackend]] = {
    # ... existing backends
    "openai-step-orchestrator": OpenAIStepwiseBackend,
}
```

4. **Add BackendId type**:

```python
# In swarm/runtime/types.py
BackendId = Literal[
    # ... existing backends
    "openai-step-orchestrator",
]
```

5. **Write tests** following patterns in `tests/test_gemini_stepwise_backend.py`

---

## Troubleshooting

### Common Issues

| Issue | Cause | Solution |
|-------|-------|----------|
| No transcript files | Engine did not write them | Check engine logs, verify `run_base` path exists |
| Stub mode active unexpectedly | Env var override or CLI not found | Check `SWARM_GEMINI_STUB`, verify CLI in PATH |
| Step timeout | Long-running step | Check step complexity, increase timeout if needed |
| "Unknown flow" error | Flow not in registry | Verify `swarm/config/flows/<flow>.yaml` exists |
| "Flow has no steps" | Empty steps list | Check flow YAML has steps defined |
| Events missing | Storage write failed | Check disk space, verify write permissions |

### Debugging Steps

1. **Check stub mode status**:
   ```python
   from swarm.runtime.backends import GeminiStepwiseBackend
   backend = GeminiStepwiseBackend()
   orch = backend._get_orchestrator()
   print(f"Stub mode: {orch._engine.stub_mode}")
   ```

2. **Inspect events**:
   ```python
   events = backend.get_events(run_id)
   for e in events:
       print(f"{e.ts} {e.kind} {e.step_id}: {e.payload}")
   ```

3. **Check transcript content**:
   ```bash
   cat swarm/runs/<run_id>/<flow>/llm/*.jsonl
   ```

4. **Check receipt metadata**:
   ```bash
   cat swarm/runs/<run_id>/<flow>/receipts/*.json | jq .
   ```

---

## Events Reference

Stepwise runs emit these event kinds:

### Core Execution Events

| Event | Level | Description |
|-------|-------|-------------|
| `run_created` | Run | Initial run creation (has `stepwise: true`) |
| `run_started` | Run | Execution began |
| `step_start` | Step | Step execution began |
| `tool_start` | Tool | Tool invocation started (engine-specific) |
| `tool_end` | Tool | Tool invocation completed |
| `step_end` | Step | Step completed successfully |
| `step_error` | Step | Step failed with error |
| `run_completed` | Run | All steps finished |
| `run_stopping` | Run | Orderly shutdown initiated |
| `run_stopped` | Run | Run stopped before completion |
| `run_pausing` | Run | Pause requested |
| `run_paused` | Run | Run paused at step boundary |
| `run_resumed` | Run | Execution resumed |

### Routing Events

| Event | Level | Description |
|-------|-------|-------------|
| `routing_decision` | Step | Navigator made a routing decision |
| `routing_offroad` | Step | Navigator deviated from golden path |
| `flow_injected` | Flow | A new flow was injected mid-run |
| `node_injected` | Step | A new node was added to current flow |
| `graph_extended` | Run | Navigator proposed spec changes |

### Stack Events

| Event | Level | Description |
|-------|-------|-------------|
| `stack_push` | Flow | A flow was paused and new flow injected |
| `stack_pop` | Flow | An injected flow completed, resuming parent |
| `stack_overflow_prevented` | Flow | Max stack depth would be exceeded |

### Fact Extraction Events

| Event | Level | Description |
|-------|-------|-------------|
| `facts_updated` | Step | Fact markers extracted from handoff |
| `assumption_recorded` | Step | An assumption was documented |
| `decision_recorded` | Step | A significant decision was documented |

Event payload examples:

```json
// step_start
{
  "role": "Load context from codebase",
  "agents": ["context-loader"],
  "step_index": 1,
  "engine": "claude-step"
}

// step_end
{
  "status": "succeeded",
  "duration_ms": 5000,
  "engine": "claude-step"
}

// routing_offroad
{
  "golden_path_step": "code-critic",
  "actual_step": "security-scanner",
  "route_type": "DETOUR",
  "rationale": "Detected potential SQL injection pattern",
  "return_address": "code-critic",
  "confidence": 0.85,
  "evaluated_conditions": ["has_db_queries == true"],
  "tie_breaker_used": false
}

// stack_push
{
  "paused_flow": "build",
  "paused_step": "code-implementer",
  "injected_flow": "rebase",
  "current_depth": 2
}
```

---

## Contracts: Proof, Not Promise

The stepwise harness is backed by test-enforced contracts. Here's where each contract is proven:

| Contract | Where it's enforced | What it proves |
|----------|---------------------|----------------|
| Teaching notes appear in prompts | `tests/test_step_prompt_teaching_notes.py` | Inputs/outputs/emphasizes/constraints from flow YAML appear in LLM prompts |
| Routing decisions follow receipts | `tests/test_build_stepwise_routing.py` | Orchestrator routes based on `status` field in receipts; microloops exit on VERIFIED |
| Receipts have required fields | `tests/test_step_engine_contract.py` | Every receipt includes engine, mode, provider, step_id, flow_key, run_id, status, duration_ms |
| Transcripts have valid format | `tests/test_step_engine_contract.py` | JSONL format with role, content, timestamp per message |
| Examples reflect real flows | `swarm/examples/stepwise-build-claude/` | Golden receipts/transcripts from actual stepwise runs |

### Key Contract Dataclasses

**Teaching Notes** (`swarm/config/flow_registry.py`):
```python
@dataclass
class TeachingNotes:
    inputs: Tuple[str, ...]      # What the step reads
    outputs: Tuple[str, ...]     # What the step writes
    emphasizes: Tuple[str, ...]  # Key focus areas
    constraints: Tuple[str, ...] # What the step cannot do
```

**Step Routing** (`swarm/config/flow_registry.py`):
```python
@dataclass
class StepRouting:
    kind: str              # "linear" | "microloop" | "branch"
    loop_target: str       # Step to loop back to
    loop_condition_field: str  # Receipt field to check
    loop_success_values: Tuple[str, ...]  # Values that exit the loop
```

**Step Result** (`swarm/runtime/engines.py`):
```python
@dataclass
class StepResult:
    step_id: str
    status: str  # "succeeded" | "failed" | "skipped"
    output: str
    duration_ms: int
```

### Verifying Contracts Locally

```bash
# Verify teaching notes appear in prompts
uv run pytest tests/test_step_prompt_teaching_notes.py -v

# Verify routing decisions
uv run pytest tests/test_build_stepwise_routing.py -v

# Verify receipt/transcript contracts
uv run pytest tests/test_step_engine_contract.py -v
```

---

## Known Limitations

This section documents deliberate scope boundaries for the stepwise harness implementation.

### Current Scope

| Feature | Status | Notes |
|---------|--------|-------|
| **Flows 1-4** (Signal → Gate) | ✅ Complete | Fully stepwise with teaching_notes, microloops, golden examples |
| **Flows 5-6** (Deploy → Wisdom) | ✅ Complete | Linear routing, teaching_notes, golden examples |
| **Stub mode** | ✅ Complete | Zero-cost testing for CI and demos |
| **CLI mode** | ✅ Complete | Claude Code or GLM Coding Plan |
| **SDK mode** | ✅ Complete | Real Anthropic API calls |

### Intentional Limitations

1. **No multi-engine per step**: Engine selection is at the flow level, not step level.
   You cannot run step 1 with Claude and step 2 with Gemini in the same flow.
   *Workaround*: Run different flows with different engines.

2. **No automatic resumption**: If a run fails mid-flow, you must restart from the
   beginning. There's no checkpoint/resume mechanism yet.
   *Workaround*: Use stub mode to test flow structure, then run real mode when ready.

3. **SDK tests are minimal**: Most test coverage uses stub mode. The SDK smoke test
   (`test_step_engine_sdk_smoke.py`) only runs when `ANTHROPIC_API_KEY` is set.
   *Workaround*: Run `uv run pytest tests/test_step_engine_sdk_smoke.py -v` manually to verify SDK integration.

4. **Microloops only in Build**: Routing with microloops (loop-back on UNVERIFIED) is
   only tested for Build flow (test/code loops). Deploy and Wisdom use linear routing.
   *Workaround*: Extend `_route()` in `orchestrator.py` if you need microloops elsewhere.

5. **No streaming to UI**: Transcripts are written after step completion, not streamed
   during execution. Flow Studio shows completed steps, not in-progress output.

### Extension Points

To extend beyond these limitations:

- **Per-step engine**: Add `engine_strategy` config to `runtime.yaml` and implement
  `get_engine_for_step(flow_key, step_id)` in `engines.py`

- **Resumption**: Add checkpoint serialization in `storage.py` and resume logic in
  `orchestrator._execute_stepwise()`

- **Streaming**: Use `streaming_callback` in engine methods to emit events during execution

---

## Future Work

The following enhancements are **not implemented** and out-of-scope for v2.3.0. They are documented here for future reference.

| Feature | Description | Entry Point |
|---------|-------------|-------------|
| **Per-step engine strategy** | Mix Gemini + Claude in one flow (e.g., step 1 with Claude, step 2 with Gemini) | Add `engine_strategy` to `swarm/config/runtime.yaml`, implement `get_engine_for_step(flow_key, step_id)` in `swarm/runtime/engines.py` |
| **Run resumption / checkpoints** | Persist orchestrator step index + routing state for mid-flow recovery | Add checkpoint serialization to `swarm/runtime/storage.py`, add `start_from_step` / `resume_run` entry points in orchestrator |
| **Streaming into Flow Studio** | Real-time updates during step execution instead of post-completion | Expose streaming event channel from engines, extend Flow Studio to subscribe and render in-progress steps |

---

## See Also

- [FLOW_STUDIO.md](./FLOW_STUDIO.md) -- Flow Studio UI guide, including stepwise section
- [CONTEXT_BUDGETS.md](./CONTEXT_BUDGETS.md) -- Token discipline, priority-aware history selection
- [GLOSSARY.md](../GLOSSARY.md) -- Terminology definitions
- [CLAUDE.md](../CLAUDE.md) -- Technology stack and runtime backends overview
- [LONG_RUNNING_HARNESSES.md](./LONG_RUNNING_HARNESSES.md) -- How stepwise maps to Anthropic's long-running agent patterns
