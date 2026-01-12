# Validation Rules Reference

> For: Platform engineers implementing or debugging swarm validation.

This document provides a comprehensive reference for all validation rules enforced by `validate_swarm.py`. For usage examples and common workflows, see [VALIDATION_WALKTHROUGH.md](./VALIDATION_WALKTHROUGH.md).

---

## Quick Reference Table

| ID | Scope | Short Name | Enforced By | Severity |
|----|-------|------------|-------------|----------|
| FR-001 | Agents | Bijection | `validate_bijection()` | ERROR |
| FR-002 | Agents | Frontmatter | `validate_frontmatter()` | ERROR |
| FR-002b | Agents | Color Validation | `validate_colors()` | ERROR |
| FR-003 | Flows | Flow References | `validate_flow_references()` | ERROR |
| FR-004 | Skills | Skill Files | `validate_skills()` | ERROR |
| FR-005 | Flows | RUN_BASE Paths | `validate_runbase_paths()` | ERROR |
| FR-006 | Agents | Prompt Sections | `validate_prompt_sections()` | WARN (ERROR with --strict) |
| FR-006a | All | Microloop Phrases | `validate_microloop_phrases()` | ERROR |
| FR-007 | Specs | Capability Registry | `validate_capability_registry()` | ERROR |
| FR-CONF | Agents | Config Coverage | `validate_config_coverage()` | ERROR |
| FR-FLOWS | Flows | Flow Invariants | `validate_flow_*()` | ERROR |

---

## Validation Rules Detail

### FR-001: Bijection

**Scope**: Agents

**Description**: Ensures 1:1 mapping between `swarm/AGENTS.md` registry entries and `.claude/agents/*.md` files. Every registry entry must have a corresponding file, and every file must have a registry entry.

**What It Checks**:
- Every agent key in `swarm/AGENTS.md` has a matching `.claude/agents/<key>.md` file
- Every `.claude/agents/*.md` file has a matching entry in `swarm/AGENTS.md`
- Names are case-sensitive exact matches
- Symlinks are skipped (security measure)

**Example FAIL Output**:
```
BIJECTION Errors (1):
======================================================================
x BIJECTION: swarm/AGENTS.md:line 42: Agent 'foo-bar' is registered but .claude/agents/foo-bar.md does not exist
  Fix: Create .claude/agents/foo-bar.md with required frontmatter, or remove entry from AGENTS.md
```

**Example FAIL Output (typo detection)**:
```
x BIJECTION: swarm/AGENTS.md:line 42: Agent 'foo-bar' is registered but .claude/agents/foo-bar.md does not exist; did you mean: foobar, foo_bar?
  Fix: Rename one of: foobar, foo_bar to match 'foo-bar', or create .claude/agents/foo-bar.md with required frontmatter, or remove entry from AGENTS.md
```

**Example FAIL Output (orphan file)**:
```
x BIJECTION: .claude/agents/orphan-agent.md: file exists but agent key 'orphan-agent' is not in swarm/AGENTS.md
  Fix: Add entry for 'orphan-agent' to swarm/AGENTS.md or delete .claude/agents/orphan-agent.md
```

---

### FR-002: Frontmatter

**Scope**: Agents

**Description**: Validates YAML frontmatter in all agent definition files. Ensures required fields are present and values are valid.

**What It Checks**:
- YAML parses correctly (opening and closing `---` delimiters)
- Required fields present: `name`, `description`, `model`, `color`
- `name` matches filename and registry key
- `model` is one of: `inherit`, `haiku`, `sonnet`, `opus`
- `skills` is a list if present
- Design constraints (in strict mode): no `tools` or `permissionMode` fields

**Example FAIL Output (missing field)**:
```
FRONTMATTER Errors (1):
======================================================================
x FRONTMATTER: .claude/agents/test-agent.md: missing required field 'color'
  Fix: Add `color: green` to frontmatter
```

**Example FAIL Output (parse error)**:
```
x FRONTMATTER: .claude/agents/test-agent.md: YAML parse error: frontmatter not terminated with '---'
  Fix: Check YAML syntax; ensure frontmatter starts and ends with '---'
```

**Example FAIL Output (invalid model)**:
```
x FRONTMATTER: .claude/agents/test-agent.md: invalid model value 'claude-3' (must be one of ['inherit', 'haiku', 'sonnet', 'opus'])
  Fix: Change `model: claude-3` to one of: inherit, haiku, sonnet, opus
```

**Example FAIL Output (name mismatch)**:
```
x FRONTMATTER: .claude/agents/my-agent.md: frontmatter 'name' field 'my_agent' does not match filename 'my-agent'
  Fix: Change `name: my_agent` to `name: my-agent`, or rename file to my_agent.md
```

**Example WARN Output (design constraint)**:
```
! FRONTMATTER: .claude/agents/test-agent.md: field 'tools' found (swarm design guideline: omit this field)
  Fix: Consider removing 'tools:' field; this swarm uses prompt-based constraints
```

---

### FR-002b: Color Validation

**Scope**: Agents

**Description**: Validates that agent colors match expected colors for their role_family. Colors are semantic, not aesthetic.

**What It Checks**:
- Agent frontmatter has `color` field
- Color is valid (one of: `red`, `blue`, `green`, `yellow`, `purple`, `orange`, `pink`, `cyan`)
- Color matches expected color for the agent's role_family in `AGENTS.md`

**Role Family to Color Mapping**:

| Role Family | Expected Color | Agent Examples |
|-------------|----------------|----------------|
| shaping | yellow | signal-normalizer, problem-framer, clarifier, scope-assessor |
| spec | purple | requirements-author, bdd-author |
| design | purple | adr-author, interface-designer, test-strategist, work-planner |
| implementation | green | context-loader, test-author, code-implementer, fixer, doc-writer |
| critic | red | requirements-critic, test-critic, code-critic, design-critic |
| verification | blue | receipt-checker, contract-enforcer, security-scanner, merge-decider |
| analytics | orange | risk-analyst, policy-analyst, regression-analyst, learning-synthesizer |
| reporter | pink | gh-reporter (exactly one per swarm) |
| infra | cyan | explore, plan-subagent, general-subagent (built-in only) |

**Example FAIL Output (color mismatch)**:
```
COLOR Errors (1):
======================================================================
x COLOR: .claude/agents/test-critic.md: color 'blue' does not match expected color 'red' for role family 'critic'
  Fix: Change `color: blue` to `color: red` to match role family in AGENTS.md
```

**Example FAIL Output (missing color)**:
```
x COLOR: .claude/agents/my-agent.md: missing required field 'color' (expected 'green' for role family 'implementation')
  Fix: Add `color: green` to frontmatter
```

**Example FAIL Output (invalid color)**:
```
x COLOR: .claude/agents/my-agent.md: invalid color value 'grey' (expected one of: red, blue, green, yellow, purple, orange, pink, cyan)
  Fix: Change `color: grey` to a valid color
```

---

### FR-003: Flow References

**Scope**: Flows

**Description**: Validates that all agent references in flow specs are valid. Uses Levenshtein distance for typo detection.

**What It Checks**:
- All agents referenced in `swarm/flows/flow-*.md` exist in registry or are built-ins
- Detects typos using edit distance (suggests corrections for distance <= 2)
- Built-in agents (`explore`, `plan-subagent`, `general-subagent`) are always valid

**Example FAIL Output**:
```
REFERENCE Errors (1):
======================================================================
x REFERENCE: swarm/flows/flow-build.md:line 42: references unknown agent 'code-implmenter'; did you mean: code-implementer?
  Fix: Update reference to one of: code-implementer, or add 'code-implmenter' to swarm/AGENTS.md
```

**Example FAIL Output (no suggestions)**:
```
x REFERENCE: swarm/flows/flow-signal.md:line 15: references unknown agent 'my-custom-agent'
  Fix: Add 'my-custom-agent' to swarm/AGENTS.md, or fix the agent name
```

---

### FR-004: Skills

**Scope**: Skills

**Description**: Validates that skills declared in agent frontmatter have valid SKILL.md files.

**What It Checks**:
- Every skill in agent `skills:` frontmatter has a `.claude/skills/<name>/SKILL.md` file
- Skill frontmatter is valid (has `name` and `description` fields)

**Example FAIL Output (missing file)**:
```
SKILL Errors (1):
======================================================================
x SKILL: skill 'my-skill': declared by agents but .claude/skills/my-skill/SKILL.md does not exist
  Fix: Create .claude/skills/my-skill/SKILL.md with valid frontmatter (name, description)
```

**Example FAIL Output (missing field)**:
```
x SKILL: .claude/skills/test-runner/SKILL.md: missing required field 'description'
  Fix: Add `description: <skill description>` to frontmatter
```

---

### FR-005: RUN_BASE Paths

**Scope**: Flows

**Description**: Validates that flow specs use `RUN_BASE` placeholder, not hardcoded paths.

**What It Checks**:
- No hardcoded `swarm/runs/<run-id>/` paths in flow specs
- `RUN_BASE` placeholder is correctly formatted
- Detects malformed placeholders: `$RUN_BASE`, `{RUN_BASE}`, `RUN_BASEsignal` (no slash)

**Valid Formats**:
- `RUN_BASE/signal/`
- `RUN_BASE/plan/`
- `RUN_BASE/build/`
- `RUN_BASE/gate/`
- `RUN_BASE/deploy/`
- `RUN_BASE/wisdom/`

**Example FAIL Output (hardcoded path)**:
```
RUNBASE Errors (1):
======================================================================
x RUNBASE: swarm/flows/flow-build.md:line 45: contains hardcoded path 'swarm/runs/<run-id>/'; should use RUN_BASE placeholder
  Fix: Replace hardcoded path with 'RUN_BASE/<flow>/' in artifact instructions
```

**Example FAIL Output (malformed placeholder)**:
```
x RUNBASE: swarm/flows/flow-signal.md:line 22: malformed RUN_BASE placeholder (should be 'RUN_BASE/<flow>/', not '$RUN_BASE', '{RUN_BASE}', or 'RUN_BASEsignal')
  Fix: Use 'RUN_BASE/<flow>/' with forward slash; valid examples: RUN_BASE/signal/, RUN_BASE/plan/, RUN_BASE/build/
```

---

### FR-006: Prompt Sections

**Scope**: Agents

**Description**: Validates that agent prompt bodies include required sections. Optional check, enabled with `--check-prompts` flag.

**What It Checks**:
- `## Inputs` (or `## Input`) section present
- `## Outputs` (or `## Output`) section present
- `## Behavior` section present

**Severity**:
- Default mode: WARN (warnings only)
- Strict mode (`--strict`): ERROR (fails validation)

**Example WARN Output**:
```
! PROMPT: .claude/agents/my-agent.md: missing required prompt sections: ## Inputs, ## Behavior
  Fix: Add the following sections to agent prompt: ## Inputs, ## Behavior
```

**Example FAIL Output (strict mode)**:
```
x PROMPT: .claude/agents/my-agent.md: missing required prompt sections: ## Inputs, ## Behavior
  Fix: Add the following sections to agent prompt: ## Inputs, ## Behavior
```

---

### FR-006a: Microloop Phrases

**Scope**: All (commands, flows, agents, CLAUDE.md)

**Description**: Validates that deprecated microloop phrases are not used. Enforces new iteration logic based on explicit `Status` and `can_further_iteration_help` signals.

**What It Checks**:
- Bans old iteration logic phrases:
  - `restat` (catches "restate", "restating", etc.)
  - `until the reviewer is satisfied or can only restate concerns`
  - `can only restate concerns`
  - `restating same concerns`

**Files Checked**:
- `.claude/commands/*.md`
- `swarm/flows/*.md`
- `.claude/agents/*.md`
- `CLAUDE.md`

**Example FAIL Output**:
```
MICROLOOP Errors (1):
======================================================================
x MICROLOOP: swarm/flows/flow-signal.md:line 55: uses banned microloop phrase 'restat' (old iteration logic)
  Fix: Replace with explicit 'can_further_iteration_help: yes/no' or Status-based exit logic
```

---

### FR-007: Capability Registry

**Scope**: Specs (`specs/capabilities.yaml`, `features/*.feature`)

**Description**: Validates the capability registry for evidence discipline. Ensures capability claims have code and test evidence, and that BDD `@cap:<id>` tags reference valid capabilities.

**What It Checks**:
- `specs/capabilities.yaml` parses correctly
- `implemented` capabilities have ≥1 test evidence pointer
- `implemented` capabilities have ≥1 code evidence pointer
- `@cap:<id>` tags in BDD scenarios reference capabilities that exist in registry
- `supported` capabilities have code evidence (tests optional)
- `aspirational` capabilities don't require evidence

**Status Meanings**:

| Status | Meaning | Evidence Required |
|--------|---------|-------------------|
| `implemented` | Has code + test evidence; safe to claim | code + tests |
| `supported` | Has code but incomplete tests | code only |
| `aspirational` | Design only; NOT shipped | none (design docs optional) |

**Example FAIL Output (missing test evidence)**:
```
CAPABILITY Errors (1):
======================================================================
x CAPABILITY: specs/capabilities.yaml:receipts.required_fields: capability 'receipts.required_fields' is 'implemented' but has no test evidence
  Fix: Add 'tests' evidence pointers or change status to 'supported'
```

**Example FAIL Output (missing code evidence)**:
```
x CAPABILITY: specs/capabilities.yaml:routing.microloop_exit: capability 'routing.microloop_exit' is 'implemented' but has no code evidence
  Fix: Add 'code' evidence pointers with path and symbol
```

**Example FAIL Output (invalid BDD tag)**:
```
x CAPABILITY: selftest.feature:line 26: @cap:selftest.nonexistent references capability not in registry
  Fix: Add 'selftest.nonexistent' to specs/capabilities.yaml or fix tag
```

**Example WARN Output (registry not found)**:
```
! CAPABILITY: specs/capabilities.yaml: capability registry not found (optional file)
  Fix: Create specs/capabilities.yaml to track capability claims with evidence
```

**Related Commands**:
```bash
# Regenerate CAPABILITIES.md from registry
make gen-capabilities-doc

# Check if doc is up-to-date
make check-capabilities-doc
```

---

### FR-CONF: Config Coverage

**Scope**: Agents

**Description**: Validates that config YAML files align with AGENTS.md registry. Only runs if `swarm/config/agents/` directory exists.

**What It Checks**:
- Every domain agent in AGENTS.md has a `swarm/config/agents/<key>.yaml` file
- Every config file corresponds to an agent in AGENTS.md
- Config fields (`category`, `color`) match registry values

**Example FAIL Output (missing config)**:
```
CONFIG Errors (1):
======================================================================
x CONFIG: swarm/AGENTS.md:line 42: Agent 'my-agent' is registered but swarm/config/agents/my-agent.yaml does not exist
  Fix: Create swarm/config/agents/my-agent.yaml with agent metadata, or remove entry from AGENTS.md
```

**Example FAIL Output (field mismatch)**:
```
x CONFIG: swarm/config/agents/my-agent.yaml: config 'category' is 'implementation' but AGENTS.md role_family is 'critic'
  Fix: Update 'category' in config to match role_family in AGENTS.md
```

**Example FAIL Output (orphan config)**:
```
x CONFIG: swarm/config/agents/orphan.yaml: config exists for 'orphan' but agent is not in swarm/AGENTS.md
  Fix: Add entry for 'orphan' to AGENTS.md or delete swarm/config/agents/orphan.yaml
```

---

### FR-FLOWS: Flow Invariants

**Scope**: Flows

**Description**: Validates structural invariants for flow definitions in `swarm/config/flows/*.yaml`.

**What It Checks**:

1. **No empty flows**: Each flow has at least one step
2. **No agentless steps**: Each step has agents or is marked `kind: human_only`
3. **Agent validity**: All agent references in steps exist in registry
4. **Documentation completeness**: Each flow config has corresponding `swarm/flows/flow-<id>.md` with autogen markers

**Example FAIL Output (empty flow)**:
```
FLOW Errors (1):
======================================================================
x FLOW: swarm/config/flows/custom.yaml: Flow 'custom' has no steps
  Fix: Add at least one step to swarm/config/flows/custom.yaml, or remove the flow definition
```

**Example FAIL Output (agentless step)**:
```
x FLOW: swarm/config/flows/build.yaml: Step 'build/my-step' has no agents and is not marked 'kind: human_only'
  Fix: Either add agents to the step or mark it with 'kind: human_only'
```

**Example FAIL Output (invalid agent)**:
```
x FLOW: swarm/config/flows/signal.yaml: Flow 'signal' step 'normalize' references unknown agent 'signal-normaliser'; did you mean: signal-normalizer?
  Fix: Update agent reference to one of: signal-normalizer, or add 'signal-normaliser' to swarm/AGENTS.md
```

**Example FAIL Output (missing documentation)**:
```
x FLOW: swarm/config/flows/wisdom.yaml: Flow 'wisdom' config exists but documentation file is missing
  Fix: Create swarm/flows/flow-wisdom.md with flow specification
```

**Example FAIL Output (missing autogen markers)**:
```
x FLOW: swarm/flows/flow-build.md: Flow documentation missing autogen markers
  Fix: Add '<!-- FLOW AUTOGEN START -->' and '<!-- FLOW AUTOGEN END -->' markers to swarm/flows/flow-build.md
```

---

## Validation Modes

### Default Mode

```bash
uv run swarm/tools/validate_swarm.py
```

- Runs all checks
- Design constraint violations (tools, permissionMode) are WARNINGs
- Prompt section checks are skipped
- Validates all files

### Strict Mode

```bash
uv run swarm/tools/validate_swarm.py --strict
```

- Elevates design guideline warnings to errors
- `tools:` and `permissionMode:` fields become failures
- Missing prompt sections become errors (if `--check-prompts` also used)

### Git-Aware Mode

```bash
uv run swarm/tools/validate_swarm.py --check-modified
```

- Only validates files modified vs main branch
- Includes uncommitted changes (staged and unstaged)
- Faster for incremental development (typically 50%+ speedup)
- Falls back to full validation if git unavailable

### Flows-Only Mode

```bash
uv run swarm/tools/validate_swarm.py --flows-only
```

- Only runs flow validation checks (FR-FLOWS)
- Skips agent/adapter validation (FR-001, FR-002, FR-002b)
- Useful for flow config development

### Prompt Validation Mode

```bash
uv run swarm/tools/validate_swarm.py --check-prompts
```

- Enables FR-006 prompt section validation
- Checks for `## Inputs`, `## Outputs`, `## Behavior` in agent prompts
- Missing sections are warnings (or errors with `--strict`)

### JSON Output Mode

```bash
uv run swarm/tools/validate_swarm.py --json
```

- Outputs machine-readable JSON to stdout
- Includes per-agent, per-flow, per-step breakdown
- Useful for CI integration and dashboards

### Debug Mode

```bash
uv run swarm/tools/validate_swarm.py --debug
```

- Shows timing and validation steps
- Prints debug information to stderr
- Useful for troubleshooting performance issues

---

## Exit Code Reference

| Exit Code | Meaning | When Used |
|-----------|---------|-----------|
| **0** | All checks passed | Validation successful, merge is safe |
| **1** | Validation failed | Spec/implementation misalignment detected |
| **2** | Fatal error | Missing required files, parse errors, config issues |

---

## CLI Flags Summary

| Flag | Description |
|------|-------------|
| `--check-modified` | Git-aware incremental mode (only validates modified files) |
| `--check-prompts` | Validate agent prompt sections (## Inputs, ## Outputs, ## Behavior) |
| `--strict` | Enforce swarm design constraints as errors (not warnings) |
| `--flows-only` | Only run flow validation checks |
| `--json` | Output machine-readable JSON |
| `--debug` | Show timing and validation steps |
| `--version` | Show validator version |

---

## JSON Output Schema

When using `--json`, the output follows this schema:

```json
{
  "version": "1.0.0",
  "timestamp": "2025-12-01T04:53:37+00:00",
  "summary": {
    "status": "PASS | FAIL",
    "total_checks": 42,
    "passed": 42,
    "failed": 0,
    "warnings": 2,
    "agents_with_issues": [],
    "flows_with_issues": [],
    "steps_with_issues": []
  },
  "agents": {
    "<agent-key>": {
      "file": ".claude/agents/<key>.md",
      "checks": {
        "FR-001": { "status": "pass | fail | warn", "message": "...", "fix": "..." },
        "FR-002": { "status": "...", "message": "...", "fix": "..." },
        "FR-002b": { "status": "...", "message": "...", "fix": "..." },
        "FR-CONF": { "status": "...", "message": "...", "fix": "..." }
      },
      "has_issues": false,
      "has_warnings": false,
      "issues": []
    }
  },
  "flows": {
    "<flow-id>": {
      "file": "swarm/flows/flow-<id>.md",
      "checks": {
        "FR-003": { "status": "...", "message": "...", "fix": "..." },
        "FR-005": { "status": "...", "message": "...", "fix": "..." },
        "FR-FLOW": { "status": "...", "message": "...", "fix": "..." }
      },
      "has_issues": false,
      "issues": []
    }
  },
  "steps": {},
  "skills": {},
  "errors": [],
  "warnings": []
}
```

---

## Related Documentation

- [CLAUDE.md](/CLAUDE.md) - Main project documentation with validation section
- [VALIDATION_WALKTHROUGH.md](./VALIDATION_WALKTHROUGH.md) - Step-by-step usage examples
- [CI_TROUBLESHOOTING.md](./CI_TROUBLESHOOTING.md) - CI failure diagnosis
- [swarm/tools/validate_swarm.py](/swarm/tools/validate_swarm.py) - Source code

---

## Version History

| Version | Changes |
|---------|---------|
| 2.1.0 | Added FR-FLOWS flow invariant checks, --flows-only mode |
| 2.0.0-mvp | Initial MVP with FR-001 through FR-006 |
