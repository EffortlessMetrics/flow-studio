# Subsumption Principle

When a backend lacks a capability, the kernel subsumes it. This is how the abstraction works.

## The Problem

Different backends have different capabilities:
- Claude SDK: hooks, interrupts, output_format, hot context
- Claude CLI: stateless, no hooks, markdown parsing
- Gemini CLI: large context, no hooks, JSONL events
- Stubs: simulate anything

Without subsumption, orchestration code would be littered with `if backend == X` checks.

## The Solution: Kernel Subsumption

The kernel provides a uniform interface by compensating for missing capabilities.

## Subsumption Table

| Missing Capability | Kernel Subsumption |
|--------------------|-------------------|
| `output_format` | Parse markdown, extract JSON from fences, validate against schema |
| `hooks` | Wrap execution with logging, capture tool calls from transcript |
| `interrupts` | Graceful timeout, periodic health check, clean shutdown |
| `hot_context` | Inject work summary into finalize prompt, inject finalize into route prompt |
| `streaming` | Buffer complete response, emit as single event |
| `tool_observation` | Parse transcript for tool usage patterns |
| `native_tools` | Prompt-based tool invocation with output capture |

## How It Works

### Example: output_format Subsumption

**With Claude SDK (has output_format):**
```python
result = await session.finalize(schema=envelope_schema)
envelope = result.structured_output  # Native JSON
```

**With Claude CLI (lacks output_format):**
```python
result = await session.finalize(prompt="Output JSON in ```json fences")
text = result.output
envelope = extract_json_from_markdown(text)  # Kernel parses
validate_against_schema(envelope, envelope_schema)  # Kernel validates
```

The orchestrator sees the same interface. The kernel does the work.

### Example: hot_context Subsumption

**With Claude SDK (has hot_context):**
```python
# All three phases share conversation
work_result = await session.work(prompt)
finalize_result = await session.finalize(schema)  # Remembers work
route_result = await session.route(schema)  # Remembers finalize
```

**With Claude CLI (lacks hot_context):**
```python
# Kernel injects summaries
work_result = await run_cli(work_prompt)
finalize_result = await run_cli(
    f"Previous work summary:\n{work_result.summary}\n\nNow finalize..."
)
route_result = await run_cli(
    f"Finalization:\n{finalize_result.summary}\n\nNow route..."
)
```

## Fallback Strategies

Different capabilities have different fallback strategies:

| Capability | Fallback Strategy |
|------------|-------------------|
| output_format | `best-effort` (parse markdown) or `microloop` (iterate until valid) |
| hooks | `logging` (record but don't intercept) |
| interrupts | `timeout` (hard cutoff after duration) |
| hot_context | `injection` (prepend summaries) |
| streaming | `buffer` (collect then emit) |

## Capability Declaration

Transports declare what they support:
```python
CLAUDE_CLI_CAPABILITIES = TransportCapabilities(
    supports_output_format=False,
    structured_output_fallback="best-effort",  # How kernel compensates
    ...
)
```

The `structured_output_fallback` field tells the kernel which strategy to use.

## Current Capability Matrix

From `swarm/runtime/transports/port.py`:

| Transport | output_format | hooks | interrupts | hot_context | streaming | native_tools | tool_observation |
|-----------|---------------|-------|------------|-------------|-----------|--------------|------------------|
| Claude SDK | Yes | Yes | Yes | Yes | Yes | Yes | Yes |
| Claude CLI | No | No | No | No | Yes | No | No |
| Gemini CLI | No | No | No | No | Yes | No | Yes |
| Stub | Yes | Yes | Yes | Yes | Yes | Yes | Yes |

**Fallback strategies:**
- Claude SDK: `none` (native support)
- Claude CLI: `best-effort` (parse markdown fences)
- Gemini CLI: `microloop` (iterate until valid JSON)
- Stub: `none` (simulates native support)

## The Rule

> The orchestrator sees a uniform interface.
> The kernel compensates for backend differences.
> Capability gaps are bridged, not exposed.

## Why This Matters

Without subsumption:
- Backend-specific code spreads everywhere
- Adding new backends requires touching all orchestration
- Testing requires real backends

With subsumption:
- Clean abstraction at transport layer
- New backends implement interface, kernel handles gaps
- Stubs can simulate any backend

## Current Implementation

See `swarm/runtime/transports/port.py` for capability declarations.
See engine-specific code for subsumption implementations.
