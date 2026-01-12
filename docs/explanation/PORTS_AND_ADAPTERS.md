# Ports and Adapters: Engine-Agnostic Architecture

> **Status:** Living document
> **Purpose:** Teaching doc for the transport abstraction

## The Problem

Flow Studio needs to work with multiple LLM backends:
- Claude Agent SDK (primary)
- Claude CLI
- Gemini CLI
- Stubs (testing)

Without abstraction, you get:
- Backend-specific code everywhere
- Impossible to swap backends
- Testing requires real API calls
- Capability differences break logic

## The Solution: Hexagonal Architecture

Flow Studio implements **Ports and Adapters** (hexagonal architecture):

```
┌─────────────────────────────────────────┐
│              Orchestrator               │
│  (Uses abstract interfaces only)        │
└────────────────┬────────────────────────┘
                 │
         ┌───────▼────────┐
         │   Port (API)   │
         │  StepEngine    │
         │  Transport     │
         └───────┬────────┘
                 │
    ┌────────────┼────────────┬────────────┐
    │            │            │            │
    ▼            ▼            ▼            ▼
 Claude      Claude      Gemini        Stub
 SDK         CLI         CLI          Adapter
 Adapter     Adapter     Adapter
```

## The Ports

### StepEngine Port

The abstract contract for step execution:

```python
class StepEngine(ABC):
    @property
    def engine_id(self) -> str:
        """e.g., 'claude-step', 'gemini-step'"""

    def run_step(self, ctx: StepContext) -> Tuple[StepResult, Iterable[RunEvent]]:
        """Execute a step and return result + events."""
```

### Transport Port

The abstract contract for LLM sessions:

```python
class TransportProtocol:
    @property
    def capabilities(self) -> TransportCapabilities:
        """What this transport supports."""

    def open_session(self, step_id, flow_key, run_id, **options):
        """Create a step session."""
```

### StepSession Port

The three-phase lifecycle:

```python
class StepSessionProtocol:
    async def work(self, prompt: str) -> WorkResult:
        """Execute main task with tools enabled."""

    async def finalize(self, schema: dict) -> FinalizeResult:
        """Extract structured handoff envelope."""

    async def route(self, schema: dict) -> RouteResult:
        """Determine next step."""
```

## The Adapters

### Claude SDK Adapter
- Full-featured: hooks, interrupts, streaming, output_format
- Hot context across phases
- Native tool integration
- Primary production backend

### Claude CLI Adapter
- Subprocess execution
- Stateless per call
- Markdown parsing for structured output
- Bridge for CLI workflows

### Gemini CLI Adapter
- JSONL event stream
- Large context window (1M tokens)
- Microloop for structured output
- Alternative backend

### Stub Adapter
- Synthetic responses
- Fast (no API calls)
- Deterministic for testing
- Capability simulation

## Capability Declaration

Transports declare what they support:

```python
CLAUDE_SDK_CAPABILITIES = TransportCapabilities(
    supports_output_format=True,   # Native JSON schemas
    supports_interrupts=True,      # Can stop mid-execution
    supports_hooks=True,           # Pre/post tool hooks
    supports_hot_context=True,     # Context preserved across phases
    max_context_tokens=200000,
    structured_output_fallback="none",
)

CLAUDE_CLI_CAPABILITIES = TransportCapabilities(
    supports_output_format=False,  # Must parse markdown
    supports_interrupts=False,
    supports_hooks=False,
    supports_hot_context=False,    # Stateless
    structured_output_fallback="best-effort",
)
```

The orchestrator adapts behavior based on capabilities.

## The Three-Phase Lifecycle

Every step follows Work → Finalize → Route:

### Phase 1: Work
- Agent executes main task
- Tools enabled
- Streaming available
- Produces output + artifacts

### Phase 2: Finalize
- Extract structured handoff envelope
- Tools disabled
- Structured output (where supported)
- Captures state while context is hot

### Phase 3: Route
- Determine next step
- Tools disabled
- Returns routing decision
- Kernel validates against graph

## Hot Context

Where supported (Claude SDK), phases share context:

```
Work: "I implemented the auth module..."
         ↓ (context preserved)
Finalize: "Based on my work, the handoff is..."
         ↓ (context preserved)
Route: "Given the results, I recommend..."
```

Where not supported (CLI), context is rebuilt:

```
Work: → subprocess → output
         ↓ (context lost)
Finalize: [inject work summary] → subprocess → output
         ↓ (context lost)
Route: [inject finalize summary] → subprocess → output
```

## Adding a New Backend

To add a new LLM backend:

1. **Implement TransportProtocol**
   ```python
   class NewBackendTransport(TransportProtocol):
       @property
       def capabilities(self):
           return TransportCapabilities(...)

       def open_session(self, ...):
           return NewBackendSession(...)
   ```

2. **Implement StepSessionProtocol**
   ```python
   class NewBackendSession(StepSessionProtocol):
       async def work(self, prompt):
           # Call your backend

       async def finalize(self, schema):
           # Extract structured output

       async def route(self, schema):
           # Get routing decision
   ```

3. **Declare Capabilities**
   - What does your backend support?
   - What fallbacks are needed?

4. **Register in Factory**
   - Add to engine factory resolution
   - Configure in `runtime.yaml`

## Why This Matters

### Testability
- Stub adapter for fast tests
- No API calls in CI
- Deterministic behavior

### Flexibility
- Swap backends without code changes
- A/B test different providers
- Graceful degradation

### Maintenance
- Backend changes isolated to adapter
- Core logic backend-agnostic
- Capability matrix documents differences

## The Subsumption Principle

When a backend lacks a capability, the kernel subsumes it:

| Missing Capability | Kernel Subsumption |
|--------------------|-------------------|
| output_format | Markdown parsing + validation |
| hooks | Logging wrapper |
| interrupts | Graceful timeout |
| hot_context | Context injection prompts |

The orchestrator sees a uniform interface regardless of backend.
