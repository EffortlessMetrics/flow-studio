# Packaging Notes: Future Extraction Strategy

This document outlines the strategy for extracting Flow Studio and core tooling into a published package in the future. **No extraction is happening now** — this is planning documentation to prevent coupling pain later.

---

## Boundary Definition

When published, the swarm toolkit would naturally split into:

### Published Boundary: `swarm-flowstudio` Package

Code and modules suitable for public release, reusable across repos:

#### 1. **Core Business Logic** (`swarm.flowstudio.core`)
- Flow graph data structures (Step, Agent, Flow, Edge)
- Graph traversal and validation (topological sort, cycle detection, contract enforcement)
- Acceptance criteria tracking (AC parsing, status transitions)
- Selftest plan generation (tier classification, step sequencing)
- Model-agnostic step/agent definitions (no CLI or UI logic)

**Location in repo**: `swarm/flowstudio/core.py`, `swarm/flowstudio/models.py`, `swarm/flowstudio/validator.py`

#### 2. **FastAPI Adapter** (`swarm.tools.flow_studio_fastapi`)
- REST API server (`/platform/status`, `/flows/<id>`, `/graph`, etc.)
- OpenAPI schema generation
- JSON serialization for core models
- CORS and caching policies
- Graceful degradation (works without optional extensions)

**Location in repo**: `swarm/tools/flow_studio_fastapi.py`, `swarm/tools/flow_studio_routes.py`

#### 3. **Validation Tooling** (`swarm.tools.validate_swarm`, `swarm.tools.selftest`)
- Validator (agent bijection, color scheme, frontmatter, RUN_BASE paths)
- Selftest plan runner (16-step governance, tier classification)
- JSON report generation
- Exit code contracts (0 = pass, 1 = fail, 2 = fatal)

**Location in repo**: `swarm/tools/validate_swarm.py`, `swarm/tools/selftest.py`

---

## Repository-Specific: What Stays Local

Code tightly coupled to this demo repo and not suitable for publishing:

- **Flow definitions** (`swarm/flows/flow-*.md`) — demo-specific scenarios
- **Agent roster** (`swarm/AGENTS.md`, `.claude/agents/`) — demo-specific agents
- **Examples** (`swarm/examples/health-check/`) — demo run artifacts
- **Flow Studio UI** (`swarm/tools/flow_studio_ui/` frontend code) — can be extracted later, but currently tightly tied to FastAPI backend
- **Flask backend** (`swarm/tools/flow_studio_flask.py`) — legacy, not extracted

**Examples of demo-specific coupling**:
- Agent definitions reference `RUN_BASE/signal/`, `RUN_BASE/build/` paths specific to 7-flow demo
- Flows hard-code step sequences (e.g., "signal → plan → build → gate → deploy → wisdom")
- Examples show demo agents (context-loader, code-implementer, etc.)

---

## Coupling Risk Analysis: What to Avoid

To prevent extraction pain, the code currently observes these boundaries:

### ✅ Good Patterns (Already Following)
1. **Core uses no repo context**: `models.py` and `core.py` never reference absolute repo paths
2. **API is flow-agnostic**: `/platform/status` returns JSON with no CLI-isms; paths use `run_id` parameter, not hardcoded branches
3. **Validation is generic**: Validator enforces 5 FRs (bijection, frontmatter, references, skills, RUN_BASE) independent of repo structure
4. **Selftest tiers are portable**: KERNEL/GOVERNANCE/OPTIONAL are core concepts, not demo-specific

### ⚠️ Coupling Risks to Watch

1. **Don't leak Flask/repo concepts into `core.py`**:
   - ✅ Good: `core.py` takes `flow_config_path: str` as parameter
   - ❌ Bad: `core.py` calls `os.path.join(REPO_ROOT, "swarm/flows/flow-*.md")`

2. **Don't hardcode paths**:
   - ✅ Good: `selftest.py` reads `swarm/config/` from `--config-path` CLI arg
   - ❌ Bad: `selftest.py` imports `from demo_swarm_dev.config import STEPS`

3. **Don't mix UI and API**:
   - ✅ Good: FastAPI routes return JSON; UI is separate frontend
   - ❌ Bad: `/flows/<id>` endpoint returns HTML; API couples to UI framework

4. **Keep validators report-agnostic**:
   - ✅ Good: `validate_swarm.py --json` outputs stable schema (version,
     timestamp, checks, agents, flows)
   - ❌ Bad: Validator writes HTML reports with hardcoded styles

5. **Don't assume agent model names**:
   - ✅ Good: Agent frontmatter has `model: inherit` or `model: sonnet`
     (portable)
   - ❌ Bad: Hardcoding `model_name = "claude-sonnet-4-5"` in validation
     logic

---

## Extraction Timeline & Next Steps

### Phase Now: Planning
- ✅ Define boundary (this document)
- ✅ Identify repo-specific code (flows, examples, agents)
- ✅ Document portable modules (core, validator, selftest, FastAPI)
- ✅ Establish CI to ensure no coupling creep

### Phase 1 (If Prioritized): Minimal Publishing
- Extract `swarm.flowstudio.core` and `swarm.tools.validate_swarm` as read-only packages
- No FastAPI yet (too much repo coupling, UI not ready)
- Publish to internal registry (e.g., Artifactory) for other teams to use

### Phase 2 (Future): Full Product
- Extract FastAPI adapter and REST API
- Generalize Flow Studio UI (separate frontend, configurable backend)
- Publish to public PyPI with examples
- Establish versioning and SLA contracts

### Phase 3 (Future): Multi-Platform Support
- Generalize to other orchestrators (GitLab, Bitbucket, GitHub Actions)
- Decouple from Claude Code specifics

---

## Dependencies to Watch

Core dependencies that should remain stable:

1. **Python stdlib only** for `core.py` and `models.py` (no external deps)
2. **PyYAML** for config parsing (stable, widely-used)
3. **FastAPI/Starlette** for API (optional; can be swapped for Flask/Django)
4. **Pydantic** for validation (optional; can be omitted for core)

Do NOT add heavy dependencies to core logic (e.g., no numpy, pandas, TensorFlow in `core.py`).

---

## Questions for Future Maintainers

When considering extraction, ask:

1. **Is this portable?** Does it depend on demo-swarm paths, 7-flow structure, or Claude Code concepts?
2. **Is the API stable?** Does changing this module break many consumers?
3. **Is the contract clear?** Can users understand what input/output is expected without reading implementation?
4. **Is it tested?** Are there unit tests independent of repo structure?
5. **Is it documented?** Do API docs explain design choices and constraints?

If the answer to any is "no," it's not ready to extract.

---

## References

- **Core modules**: `swarm/flowstudio/`, `swarm/tools/validate_swarm.py`, `swarm/tools/selftest.py`
- **Repo-specific**: `swarm/flows/`, `swarm/AGENTS.md`, `.claude/agents/`, `swarm/examples/`
- **API contracts**: `docs/FLOW_STUDIO_API.md`
- **Demo examples**: `swarm/examples/health-check/`
