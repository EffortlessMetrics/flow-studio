# ADR-001: Spec-First Architecture

**Status:** Accepted
**Date:** 2025-12-28
**Deciders:** Flow Studio Team

## Context

Flow Studio manages 53+ agents across 7 flows (6 SDLC flows + teaching/demo). The original implementation used markdown prompts with YAML frontmatter as the source of truth for agent configuration. This approach had several limitations:

### Problems with Markdown-First Approach

1. **No compile-time validation**: Typos in agent references, invalid field values, and schema violations only surfaced at runtime.

2. **Prompt sprawl**: Each agent's markdown file embedded identity, SDK config, I/O contracts, and handoff rules in prose. Changes required careful reading of narrative text.

3. **No graph representation**: Flows were described in mermaid diagrams, but the actual step-to-step routing and microloop logic lived in orchestrator prompts. The UI had to re-parse markdown to render the flow graph.

4. **Reproducibility gaps**: SDK options (model, tools, permissions) were scattered across agent files, `.claude/settings.json`, and orchestrator logic. Reproducing a run required reconstructing all these pieces.

5. **Teaching mode blocked**: We wanted to highlight specific steps with notes and explanations, but markdown offered no structured way to attach teaching metadata.

6. **No versioning**: When station behavior changed, there was no version bump to track. Debugging required git archaeology.

### Scale of the Problem

- 53+ agents with identity + SDK config + I/O contracts
- 7 flows with step sequences and routing logic
- Microloops (adversarial iteration) requiring explicit exit conditions
- Cross-flow artifact dependencies
- Teaching mode for demos and onboarding

## Decision

We adopt a **spec-first architecture** with three layers:

### 1. JSON as Canonical Format (via Python Dataclasses)

Structured specifications replace prose. Two primary spec types:

**StationSpec** (`swarm/spec/types.py:StationSpec`):
```python
@dataclass(frozen=True)
class StationSpec:
    id: str                          # Unique identifier (kebab-case)
    version: int                     # Version for traceability
    title: str                       # Human-readable name
    category: StationCategory        # Role family (shaping, critic, etc.)
    sdk: StationSDK                  # Model, tools, permissions, sandbox
    identity: StationIdentity        # System prompt append (<2000 chars)
    io: StationIO                    # Required/optional inputs and outputs
    handoff: StationHandoff          # Handoff path template and required fields
    runtime_prompt: StationRuntimePrompt  # Fragment references and template
    invariants: Tuple[str, ...]      # Hard rules (non-negotiable)
    routing_hints: StationRoutingHints    # Default routing behavior
```

**FlowSpec** (`swarm/spec/types.py:FlowSpec`):
```python
@dataclass(frozen=True)
class FlowSpec:
    id: str                          # e.g., "3-build"
    version: int                     # Flow spec version
    title: str                       # Human-readable name
    description: str                 # Purpose and scope
    defaults: FlowDefaults           # Context pack config, SDK overrides
    steps: Tuple[FlowStep, ...]      # Ordered step sequence
    cross_cutting_stations: Tuple[str, ...]  # Available to all steps
```

Each `FlowStep` references a station and provides step-specific overrides:
- Objective and scope
- Additional inputs/outputs
- Routing configuration (linear, microloop, branch, terminal)
- SDK overrides
- Teaching metadata (highlight, note)

### 2. Python Kernel for Spec Management

The Python layer handles loading, validation, and compilation:

**Loader** (`swarm/spec/loader.py`):
- Loads StationSpecs and FlowSpecs from YAML files
- Validates against JSON schemas (`swarm/spec/schemas/*.json`)
- Checks station references, fragment paths, routing consistency
- Provides cached access for repeated lookups

**Compiler** (`swarm/spec/compiler.py`):
- Produces a `PromptPlan` ready for SDK execution
- Merges station defaults with step overrides
- Renders templates with {{variable}} substitution
- Computes prompt hash for traceability
- Resolves handoff contracts and verification requirements

**PromptPlan** output includes:
```python
@dataclass(frozen=True)
class PromptPlan:
    # Traceability
    station_id: str
    station_version: int
    flow_id: str
    flow_version: int
    step_id: str
    prompt_hash: str

    # SDK Options (programmatic, not filesystem)
    model: str
    permission_mode: str
    allowed_tools: Tuple[str, ...]
    max_turns: int
    sandbox_enabled: bool
    cwd: str

    # Prompt Content
    system_append: str
    user_prompt: str

    # Verification and Handoff
    verification: VerificationRequirements
    handoff: HandoffContract
    flow_key: str
```

### 3. JSON Schemas for Validation

Eight schemas in `swarm/spec/schemas/`:
- `station.schema.json` - StationSpec validation
- `flow.schema.json` - FlowSpec validation
- `prompt_plan.schema.json` - Compiled output validation
- `handoff_envelope.schema.json` - Step handoff format
- `routing_signal.schema.json` - Routing decisions
- `flow_graph.schema.json` - Graph representation for UI
- `run_state.schema.json` - Run execution state
- `template.schema.json` - Template rendering rules

Validation runs at:
- Load time (schema validation)
- Compile time (reference resolution)
- Runtime (handoff validation)

### 4. TypeScript Client for UI

Flow Studio UI consumes specs via:
- `window.__flowStudio.getFlowGraph()` - Graph data from specs
- Step highlighting based on `teaching.highlight`
- Teaching notes from `teaching.note`
- Station categories for color coding

## Alternatives Considered

### A. Database-First (Rejected)

Store specs in SQLite or PostgreSQL with an ORM layer.

**Pros:**
- Query capabilities (find all critics, list steps by station)
- Transaction support for multi-spec updates
- Built-in versioning via migration tools

**Cons:**
- Heavy dependency for a demo harness
- Breaks "works on clone" promise (needs DB setup)
- Harder to review in PRs (no diff-friendly format)
- Overkill for 53 agents and 7 flows

**Rejected because:** The added complexity isn't justified. YAML files in git provide sufficient query capability via Glob/Grep, natural versioning via git history, and easy PR review.

### B. YAML-Only (Rejected)

Use YAML for everything: specs, fragments, templates.

**Pros:**
- Simple toolchain (just PyYAML)
- Human-readable and git-friendly
- No schema compilation step

**Cons:**
- No compile-time type safety
- Easy to introduce typos in field names
- No programmatic access patterns (dataclasses)
- Validation is runtime-only

**Rejected because:** YAML is great for storage but terrible for type safety. Python dataclasses give us IDE autocomplete, type checking, and structured access. We use YAML for serialization but dataclasses for the domain model.

### C. Keep Markdown (Rejected)

Continue with markdown prompts and YAML frontmatter.

**Pros:**
- Already working
- Familiar to contributors
- Prose is flexible

**Cons:**
- No validation until runtime
- Prompt content mixed with config
- No graph representation
- No teaching metadata
- Reproducibility requires reading prose

**Rejected because:** The scale of the system (53+ agents, 7 flows, microloops, cross-flow dependencies) demands structured specs. Markdown is great for documentation but wrong for machine-readable contracts.

## Consequences

### Positive

1. **Graph-native UI**: The UI reads `FlowSpec.steps` and `FlowStep.routing` directly. No more parsing mermaid diagrams. Microloops render as cycles; branches render as forks.

2. **Reproducible runs**: A `PromptPlan` captures everything needed to replay a step: station version, flow version, prompt hash, SDK options. Debugging agentic flows becomes tractable.

3. **Versioned specs**: Bumping `station.version` or `flow.version` creates a clear trail. When behavior changes, the version changes.

4. **Teaching mode**: `FlowStep.teaching.highlight` and `FlowStep.teaching.note` enable step-by-step walkthroughs without polluting agent logic.

5. **Compile-time validation**: JSON schemas catch typos, invalid enums, and missing required fields before runtime.

6. **Separation of concerns**:
   - StationSpec = "who am I and what can I do"
   - FlowSpec = "when do I run and what's my objective"
   - PromptPlan = "exactly what to send to the SDK"

7. **Testability**: Dataclasses are easy to construct in tests. Mock a `StationSpec`, compile it, verify the `PromptPlan`.

### Negative

1. **Learning curve**: Contributors must understand the spec hierarchy (Station, Flow, Step, PromptPlan) before modifying agents.

2. **Two representations**: YAML files on disk, dataclasses in memory. Changes must be reflected in both.

3. **Schema maintenance**: As specs evolve, schemas must be updated. Breaking changes require migration.

4. **Indirection**: Finding what an agent actually says requires tracing: FlowStep -> StationSpec -> fragments -> rendered prompt.

### Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| Specs diverge from reality | Validation in CI (`make validate-swarm`), selftest checks spec consistency |
| Schema evolution breaks runs | Version fields enable graceful degradation; compiler checks versions |
| Contributors bypass specs | Pre-commit hooks, PR review checklist, clear documentation |
| Over-engineering for demo | Keep it minimal: only add schema fields when needed for real use cases |

## Implementation Notes

### File Locations

- **Python types**: `swarm/spec/types.py`
- **Loader**: `swarm/spec/loader.py`
- **Compiler**: `swarm/spec/compiler.py`
- **JSON schemas**: `swarm/spec/schemas/*.json`
- **Station specs**: `swarm/spec/stations/*.yaml`
- **Flow specs**: `swarm/spec/flows/*.yaml`
- **Prompt fragments**: `swarm/spec/fragments/**/*.md`

### Key Patterns

**Immutability**: All dataclasses are `frozen=True`. Specs are values, not mutable objects.

**Template rendering**: `{{variable}}` syntax with nested access (`{{run.base}}`, `{{step.id}}`).

**Fragment composition**: Stations reference fragments by path; compiler loads and concatenates.

**Cached loading**: `@lru_cache` on loaders for repeated access during a run.

### Validation Layers

1. **YAML parse**: Syntax errors caught immediately
2. **JSON schema**: Structure and enum validation
3. **Reference resolution**: Station exists, fragment exists, step exists
4. **Routing consistency**: `next` and `loop_target` point to valid steps

## References

- `swarm/spec/types.py` - Python dataclasses (source of truth for types)
- `swarm/spec/loader.py` - Loading and validation logic
- `swarm/spec/compiler.py` - Prompt compilation
- `swarm/spec/schemas/station.schema.json` - Station validation schema
- `swarm/spec/schemas/flow.schema.json` - Flow validation schema
- `docs/STEPWISE_BACKENDS.md` - How compiled specs drive execution
- `swarm/SELFTEST_SYSTEM.md` - Validation in CI
