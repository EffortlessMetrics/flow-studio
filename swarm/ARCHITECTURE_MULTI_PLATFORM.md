# Multi-Platform Adapter Architecture (RFC)

**Status:** Design proposal (Phase 0: decision, Phases 1–3: future work)
**Date:** 2025-11-28
**Scope:** Extends swarm to support Claude Code, OpenAI Codecs, Gemini, and future platforms.

---

## 1. Problem Statement

Currently, the swarm has:

- **One spec layer** (`swarm/`)—canonical registry of agents, flows, roles, constraints
- **One adapter layer** (`.claude/`)—Claude Code-specific prompts, frontmatter, commands

As soon as you add a second platform (e.g., OpenAI, Gemini), you face:

1. **Duplication** — agent metadata (name, role, flow membership, color, constraints) appears in both `swarm/AGENTS.md` and `.claude/agents/*.md`
2. **No sync guarantee** — when `AGENTS.md` or flow specs change, nothing asserts "regenerate all adapters"
3. **Scaling problem** — 3 platforms × 45 agents = 135 places where drift can happen

**Goal:** Single source of truth (spec) + generated adapters per platform + automated validation.

---

## 2. Three-Phase Roadmap

### Phase 0 – Spec-First (Now: Foundations)

**Status:** In progress (current `swarm-alignment` run).

**Deliverables:**

- ✅ `swarm/AGENTS.md` – canonical agent registry
- ✅ `swarm/flows/flow-*.md` – flow semantics & agent sequences
- ✅ `swarm/runs/<run-id>/` – concrete flow receipts
- ✅ `swarm/tools/validate_swarm.py` – two-layer validator (platform spec + swarm constraints)
- ✅ `.claude/agents/*.md` – hand-authored adapters (for now)
- ✅ `.claude/commands/flow-*.md` – entry points
- ✅ CI + pre-commit + branch rules – automated enforcement (Flow 5 operationalization)

**Key invariant:** "Spec and adapters are hand-synced; validator catches bijection breaks."

**Limitation:** When spec changes, you manually update adapters. No automated propagation.

### Phase 0.5 – Config-Checked Adapters (Now: Minimal vertical slice)

**Status:** Implemented and tested (single command, 2 pilot agents).

**Deliverables:**

- ✅ `swarm/config/agents/{deploy-decider,merge-decider}.yaml` – provider-neutral agent config for 2 pilot agents
- ✅ `swarm/platforms/claude.yaml` – Claude Code adapter profile
- ✅ `swarm/templates/claude/agent_frontmatter.md.tpl` – frontmatter template (simple {placeholder} format)
- ✅ `swarm/tools/gen_adapters.py` – generator CLI (--platform claude --agent <key> --mode check|generate)
- ✅ Verified both pilot agents pass `--mode check`

**What it proves:**

Config can drive adapter files without external dependencies (stdlib YAML parser, no Jinja2). The generator reads provider-neutral YAML, applies platform profile, and renders canonical frontmatter. This is the foundation for Phase 1–3 multi-platform work.

**How to extend:**

1. Add more agents to `swarm/config/agents/*.yaml`
2. Run `uv run swarm/tools/gen_adapters.py --platform claude --agent <key> --mode check` to verify alignment
3. Run with `--mode generate` to regenerate `.claude/agents/<key>.md` frontmatter

**Limitations:**

- Frontmatter only; prompt bodies are hand-maintained
- CLI is single-agent; batch mode deferred to Phase 1
- No CI integration yet; run manually before committing

### Phase 1 – Explicit Config & Validation (Next: Add spec machine-readability)

**Triggers:** After Flow 5 / Flow 6 confirm the teaching story is solid.

**Deliverables:**

- `swarm/config/agents.yaml` – provider-neutral agent metadata (keys, flows, roles, colors, prompt-file refs)
- `swarm/config/flows.yaml` – flow definitions in machine-readable form
- Extended `validate_swarm.py` – checks that `AGENTS.md` and `agents.yaml` agree; validates flow references against config
- `swarm/platforms/claude.yaml` – Claude Code platform profile (model defaults, frontmatter rules, adapter dirs)
- Optional: `swarm/config/requirements.yaml` – encode FR-001..014 and FR-OP-001..005 for validation

**Key step:** Make the spec machine-readable without changing how it's maintained.

**No generation yet** – just adding a "config layer" so future generation has a clear input.

**Validation benefit:** Can now assert "if an agent is in `agents.yaml`, it must have both an `AGENTS.md` entry AND a `.claude/agents` file" (true bijection, not just name matching).

### Phase 2 – Single-Platform Generation (Later: Prove codegen works)

**Triggers:** Once Phase 1 config is stable and you want to automate Claude adapter updates.

**Deliverables:**

- `swarm/prompts/agents/*.md` – isolated prompt bodies (extracted from `.claude/agents/*.md`)
- `swarm/templates/claude/agent.md.j2` – Jinja2 template for Claude agent files
- `swarm/templates/claude/command.md.j2` – template for slash commands
- `swarm/tools/gen_adapters.py` – generator tool
- Updated `.pre-commit-config.yaml` – new hook `swarm-codegen --check` (fails if adapters are stale)
- Updated `validate_swarm.py` – detects `GENERATED` header; flags hand-edits or stale artifacts

**Workflow:**

```bash
# Edit spec or prompt
vim swarm/config/agents.yaml
vim swarm/prompts/agents/requirements-author.md

# Regenerate adapters
uv run swarm/tools/gen_adapters.py --platform claude

# Validator ensures they're in sync
uv run swarm/tools/validate_swarm.py
```

**Key invariant:** `.claude/agents/*.md` are build artifacts, not source.

### Phase 3 – Multi-Platform (Future: Scale to N platforms)

**Triggers:** When a second platform (Gemini, OpenAI, etc.) is ready.

**Deliverables:**

- `swarm/platforms/openai.yaml`, `swarm/platforms/gemini.yaml`, etc.
- `swarm/templates/openai/agent.md.j2`
- `swarm/templates/gemini/agent.md.j2`
- Enhanced `gen_adapters.py` supporting `--platform claude openai gemini`
- Pre-commit hook and CI jobs for all platforms

**Scaling benefit:** Adding a new platform is now:

1. Write platform profile YAML (toolset mapping, model aliases, syntax rules)
2. Write templates (prompt structure, frontmatter)
3. Run generator
4. Done – all 45 agents + 7 flows wired for the new platform

No hand-editing of 45+ agent files per platform.

---

## 3. Phase 0 → Phase 1 Transition: Minimal Scaffolding

To ease the Phase 0 → Phase 1 move, we can add a **config skeleton** now without committing to generation.

### 3.1 Add minimal config files

Create (empty or reference):

```
swarm/
  config/
    agents.yaml           # Will be populated in Phase 1
    flows.yaml            # Will be populated in Phase 1
  platforms/
    claude.yaml           # Platform profile (can start minimal)
  prompts/                # Will be populated in Phase 2
    agents/
      .gitkeep
  templates/              # Will be populated in Phase 2
    claude/
      .gitkeep
    openai/
      .gitkeep
  tools/
    gen_adapters.py       # Placeholder stub (Phase 2)
```

### 3.2 Minimal Phase 1 config example

**`swarm/config/agents.yaml`** (example for 3 agents):

```yaml
# Provider-neutral agent registry
# Source of truth for all platforms

agents:
  - key: requirements-author
    flows: [signal, plan]
    category: analysis
    role_family: spec
    color: purple
    description: "Write functional + non-functional requirements."
    persona_tags: [author, requirements, writer]
    constraints:
      - "never invent unstated acceptance criteria"
      - "always state assumptions"
    capabilities:
      - "read-context"
      - "write-structured-docs"
      - "refine-from-critique"

  - key: requirements-critic
    flows: [signal, plan]
    category: verification
    role_family: critic
    color: red
    description: "Verify requirements are testable, consistent."
    persona_tags: [critic, requirements, verifier]
    constraints:
      - "never fix; only critique"
      - "always provide status (VERIFIED/UNVERIFIED/BLOCKED)"
    capabilities:
      - "read-context"
      - "write-critiques"

  - key: deploy-decider
    flows: [deploy]
    category: verification
    role_family: verification
    color: blue
    description: "Verify operationalization FRs (FR-OP-001..005)."
    persona_tags: [deploy, decider, governance]
    constraints:
      - "UNKNOWN is not pass by omission; it is NOT_DEPLOYED"
      - "always provide FR status"
    capabilities:
      - "read-config"
      - "verify-ci"
      - "verify-branch-rules"
      - "write-deployment-decision"
```

**`swarm/config/flows.yaml`**:

```yaml
flows:
  - id: 1
    key: signal
    name: "Signal → Spec"
    command: "/flow-1-signal"
    question: "What problem, for whom, under which constraints?"
    agents:
      - key: signal-normalizer
      - key: problem-framer
      - key: clarifier
      - key: requirements-author
      - key: requirements-critic
      - key: bdd-author
      - key: scope-assessor
      - key: risk-analyst
      - key: gh-reporter

  - id: 5
    key: deploy
    name: "Artifact → Prod (Deploy)"
    command: "/flow-5-deploy"
    question: "Is the governance layer actually enforced?"
    agents:
      - key: deploy-monitor
      - key: smoke-verifier
      - key: deploy-decider
      - key: gh-reporter
```

**`swarm/platforms/claude.yaml`**:

```yaml
id: claude
description: "Claude Code adapter layer"
agents_dir: ".claude/agents"
commands_dir: ".claude/commands"

model_defaults:
  shaping: haiku
  analysis: haiku
  spec: sonnet
  design: sonnet
  implementation: sonnet
  critic: sonnet
  verification: haiku

frontmatter:
  required: [name, description, model, color]
  optional: [skills]
  forbidden_in_domain_agents:
    - tools
    - permissionMode

cli:
  slash_command_prefix: "/"
```

### 3.3 Validator updates (Phase 1 check)

Extend `validate_swarm.py` to:

1. **Load `agents.yaml`** – parse as config
2. **Cross-check with `AGENTS.md`**:
   - Same keys present? ✓
   - Same flows listed? ✓
   - Same colors? ✓
3. **Cross-check with `.claude/agents/`**:
   - Every agent in config has a file? ✓
4. **New error level:** "Spec drift detected"

Example output:

```
✓ agents.yaml parses correctly (45 agents)
✓ agents.yaml ↔ AGENTS.md bijection: PASS
✓ agents.yaml ↔ .claude/agents/: PASS
```

or

```
✗ Spec Drift: requirements-author in agents.yaml lists flows [signal, plan]
  but AGENTS.md lists [signal]. Update one or both.
```

---

## 4. Phase 2 Scaffold: Generator Stub

Once Phase 1 config is stable, the generator would be small:

**`swarm/tools/gen_adapters.py` outline:**

```python
#!/usr/bin/env python3
"""
Generate platform-specific adapter layers from provider-neutral spec.

Usage:
  uv run swarm/tools/gen_adapters.py --platform claude [--check]
  uv run swarm/tools/gen_adapters.py --platform openai --check
"""

import yaml
import sys
from pathlib import Path
from jinja2 import Environment, FileSystemLoader

def load_spec():
    with open("swarm/config/agents.yaml") as f:
        agents = yaml.safe_load(f)
    with open("swarm/config/flows.yaml") as f:
        flows = yaml.safe_load(f)
    return agents, flows

def load_platform(platform_name):
    with open(f"swarm/platforms/{platform_name}.yaml") as f:
        profile = yaml.safe_load(f)
    return profile

def generate(platform_name, check_only=False):
    agents, flows = load_spec()
    profile = load_platform(platform_name)

    # Load templates
    env = Environment(loader=FileSystemLoader(f"swarm/templates/{platform_name}"))
    agent_template = env.get_template("agent.md.j2")

    # Generate per agent
    for agent in agents:
        output_path = Path(profile["agents_dir"]) / f"{agent['key']}.md"
        content = agent_template.render(
            agent=agent,
            platform=profile,
            timestamp=datetime.now().isoformat()
        )

        if check_only:
            # Compare with existing; flag if stale
            if output_path.exists():
                existing = output_path.read_text()
                if existing != content:
                    print(f"✗ {output_path} is stale (would be regenerated)")
                    return False
            else:
                print(f"✗ {output_path} is missing (would be generated)")
                return False
        else:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(content)
            print(f"✓ Generated {output_path}")

    return True

if __name__ == "__main__":
    platform = "claude"  # default
    check = False

    if "--platform" in sys.argv:
        platform = sys.argv[sys.argv.index("--platform") + 1]
    if "--check" in sys.argv:
        check = True

    success = generate(platform, check)
    sys.exit(0 if success else 1)
```

---

## 5. Implementation Roadmap

### Current (Phase 0)

- ✅ Spec, adapters, validator, CI enforcement in place
- ✅ `swarm-alignment` run validates the story end-to-end

### After Flow 6 (Phase 1: optional, prep work)

- [ ] Create `swarm/config/` skeleton
- [ ] Write `agents.yaml` for all 45 agents (copy metadata from `AGENTS.md`)
- [ ] Write `flows.yaml` for all 7 flows
- [ ] Extend `validate_swarm.py` to cross-check config ↔ registry ↔ files
- [ ] Create `swarm/platforms/claude.yaml` profile
- [ ] Update this RFC with Phase 1 completion

### Later (Phase 2: when Claude adapters are stable)

- [ ] Extract prompt bodies to `swarm/prompts/agents/`
- [ ] Write Jinja2 templates for `.claude/agents/` and `.claude/commands/`
- [ ] Implement `gen_adapters.py --platform claude`
- [ ] Update validator to enforce `GENERATED` headers
- [ ] Add pre-commit hook for `--check`

### Future (Phase 3: when multi-platform is needed)

- [ ] Add `swarm/platforms/{openai,gemini}.yaml` profiles
- [ ] Write platform-specific templates
- [ ] Extend `gen_adapters.py` for multi-platform
- [ ] Test generation for each platform

---

## 6. Benefits of This Approach

| Aspect | Phase 0 | Phase 1 | Phase 2 | Phase 3 |
|--------|---------|---------|---------|---------|
| **Source of truth** | AGENTS.md + flow specs | Config YAML | Config YAML | Config YAML |
| **Adapter sync** | Hand-maintained | Validated bijection | Auto-generated | Auto-generated (N platforms) |
| **Validation** | Basic (bijection) | Extended (config ↔ files) | Generation check | All platforms verified |
| **Cost to add agent** | Update 2 files manually | Update YAML, regenerate | Update YAML, regenerate | Update YAML, regenerate (auto for all platforms) |
| **Cost to add platform** | Not supported | Not supported | Manual (new templates) | Minimal (YAML profile + templates) |

---

## 7. Design Principles

1. **Spec is source of truth** – everything else is derived or validated
2. **Explicit is better than implicit** – config files are readable and editable
3. **Generation is opt-in per platform** – Phase 0/1 work without it
4. **Validation is continuous** – validator catches drift automatically
5. **Transition is gradual** – you can stay in Phase 0 indefinitely if you prefer hand-maintenance
6. **Teaching repo remains teaching-focused** – generation is "future work," not core story

---

## 8. Out-of-Scope (for now)

- Automatic migration of existing `.claude` files to generated form (Phase 2 effort)
- Orchestrator integration (separate concern; kept in its own repo/package)
- Runtime agent selection / fallback (platform portability is template/config work, not runtime)

---

## References

- `swarm/AGENTS.md` – current agent registry
- `swarm/flows/flow-*.md` – current flow specs
- `swarm/tools/validate_swarm.py` – validator (will be extended in Phase 1)
- `swarm/CLAUDE.md` – main swarm documentation
- `swarm/positioning.md` – design philosophy

---

**Next step:** After `swarm-alignment` Flow 6 (Wisdom) completes, review this RFC and decide: does Phase 1 make sense for your use case? If yes, create a ticket/milestone for config extraction.
