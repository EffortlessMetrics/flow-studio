# Agent Operations Guide

> For: Anyone managing agents in the swarm.
>
> **Terminology note:** This guide covers `.claude/agents/` subagent definitions—helpers invoked via the Task tool inside steps. For the canonical vocabulary distinguishing agents from stations, steps, and navigators, see [LEXICON.md](./LEXICON.md).

This guide covers the day-to-day operations of managing agents: adding, modifying, and inspecting them.

---

## Mental Model

- **Where to edit:** `swarm/config/agents/<key>.yaml` (the source of truth)
- **What gets generated:** `.claude/agents/<key>.md` frontmatter (read-only, auto-generated)
- **What you run:** Three Make targets that regenerate and validate

---

## Quick Reference

```bash
# Regenerate and verify (always run all three)
make gen-adapters
make check-adapters
make validate-swarm

# Quick overview: model distribution
make agents-models

# See flows <-> agents mapping
uv run swarm/tools/flow_graph.py --format table

# Remind yourself of the workflow
make agents-help
```

---

## Common Operations

### Change an Agent's Model

The `model` field controls which Claude model an agent uses. Valid values: `inherit` (default), `haiku`, `sonnet`, `opus`.

```bash
# 1. Edit the config file
$EDITOR swarm/config/agents/<key>.yaml

# 2. Change this single field:
#    model: inherit | haiku | sonnet | opus

# 3. Regenerate and verify
make gen-adapters
make check-adapters
make validate-swarm
```

### Add a New Agent

1. **Register in `swarm/AGENTS.md`** with:
   - `key` (kebab-case, must match filename and config key)
   - `flows` (comma-separated, e.g., `build` or `1, 3, 6`)
   - `role_family` (from: shaping, spec, design, implementation, critic, verification, analytics, reporter, infra)
   - `color` (determined by role_family; see Color Scheme below)
   - `source` (usually `project/user`)
   - `description` (one-line)

2. **Create the config file:** `swarm/config/agents/<key>.yaml`
   ```yaml
   key: <key>
   flows:
     - <flow-id>
   category: <role-family>
   color: <color>
   source: project/user
   short_role: "One-line description"
   model: inherit
   ```

3. **Regenerate and validate:**
   ```bash
   make gen-adapters
   make check-adapters
   make validate-swarm
   ```

### Modify an Agent's Prompt

Agent prompts live in `.claude/agents/<key>.md` after the frontmatter. Edit the markdown content (not the YAML frontmatter) directly, then validate:

```bash
make validate-swarm
```

---

## Agent Definition Format

All agents in `.claude/agents/*.md`:

```yaml
---
name: agent-key-name
description: One-line responsibility
color: purple  # Required: yellow, purple, green, red, blue, orange, pink, cyan
model: inherit  # or sonnet, haiku
skills: []      # Optional: [test-runner, auto-linter]
---

You are the **Agent Name**.

## Inputs

- `RUN_BASE/<flow>/file1.md`

## Outputs

- `RUN_BASE/<flow>/artifact.md` describing...

## Behavior

1. Step one
2. Step two
```

### Frontmatter Schema

**Required fields**:

- `name` (string): Agent identifier (must match filename)
- `description` (string): One-line role description
- `color` (string): Visual color code for role family
- `model` (string): Model selector (`inherit`, `haiku`, `sonnet`, `opus`)

**Optional fields**:

- `skills` (list): Restrict agent to specific Skills (e.g., `[test-runner, auto-linter]`). Omit to inherit all Skills.

**Intentionally omitted**:

- `tools` — This swarm uses prompt-based constraints, not tool denial. All agents inherit full tooling.
- `permissionMode` — Permissions enforced at repo level, not agent level.

---

## Color Scheme and Role Families

Colors map to **semantic role families**—not aesthetic choice, part of the specification. Enforced by `validate_swarm.py`:

| Color | Role Family | Agents | Semantic Meaning |
|-------|-------------|--------|------------------|
| **yellow** | shaping | signal-normalizer, problem-framer, clarifier, scope-assessor | Front-of-funnel: parsing raw signal, early clarity |
| **purple** | spec, design | requirements-author, bdd-author, impact-analyzer, design-optioneer, adr-author, interface-designer, observability-designer, test-strategist, work-planner | Specification & architecture contracts |
| **green** | implementation | context-loader, test-author, code-implementer, fixer, doc-writer, gate-fixer, repo-operator | Direct repo changes: code, tests, docs, git ops |
| **red** | critic | requirements-critic, design-critic, test-critic, code-critic | Adversarial reviewers (never fix, only critique) |
| **blue** | verification | receipt-checker, contract-enforcer, security-scanner, coverage-enforcer, mutator, self-reviewer, deploy-monitor, smoke-verifier, deploy-decider, artifact-auditor, merge-decider | Checks, gates, verification, audit, decisions |
| **orange** | analytics | risk-analyst, policy-analyst, regression-analyst, flow-historian, learning-synthesizer, feedback-applier | Cross-flow analysis, risk, learnings, feedback |
| **pink** | reporter | gh-reporter | Human-facing GitHub reporting (exactly one) |
| **cyan** | infra | explore, plan-subagent, general-subagent | Built-in orchestration infrastructure |

### Color Invariants

1. **Name patterns -> color**: Agent names should match semantic color (e.g., `*-critic` -> red, `*-analyzer` -> orange)
2. **Exactly one pink agent**: `gh-reporter` is the sole reporter
3. **No double-duty**: Agent's `role_family` in `AGENTS.md` determines canonical color; frontmatter must match
4. **Every agent has a color**: Missing color field is an error

---

## Agent Taxonomy

**Built-in Infra Agents (3)** — native to Claude Code, no `.claude/agents/` files:

- `explore` — Fast Haiku read-only search (Glob/Grep/Read/Bash)
- `plan-subagent` — High-level repo analyzer for complex architecture
- `general-subagent` — Generic Task worker (implicit)

**Cross-cutting Agents (5)** — used across multiple flows:

- `clarifier` — Detect ambiguities, draft clarification questions
- `risk-analyst` — Identify risk patterns (security, compliance, data, performance)
- `policy-analyst` — Interpret policy docs vs change
- `repo-operator` — Git workflows: branch, commit, merge, tag (safe Bash only)
- `gh-reporter` — Post summaries to GitHub issues/PRs

**Utility Agents (3)** — used for operations and tooling:

- `swarm-ops` — Guide for agent operations: model changes, adding agents, inspecting flows
- `ux-critic` — Inspect Flow Studio screens and produce structured JSON critiques
- `ux-implementer` — Apply UX critique fixes to Flow Studio code and run tests

**Flow-specific Agents (37)**:

- **Flow 1 - Signal** (6): signal-normalizer, problem-framer, requirements-author, requirements-critic, bdd-author, scope-assessor
- **Flow 2 - Plan** (8): impact-analyzer, design-optioneer, adr-author, interface-designer, observability-designer, test-strategist, work-planner, design-critic
- **Flow 3 - Build** (9): context-loader, test-author, test-critic, code-implementer, code-critic, mutator, fixer, doc-writer, self-reviewer
- **Flow 4 - Gate** (6): receipt-checker, contract-enforcer, security-scanner, coverage-enforcer, gate-fixer, merge-decider
- **Flow 5 - Deploy** (3): deploy-monitor, smoke-verifier, deploy-decider
- **Flow 6 - Wisdom** (5): artifact-auditor, regression-analyst, flow-historian, learning-synthesizer, feedback-applier

**Total: 56 agents** (3 built-in + 53 domain)

---

## Config-Driven Agents

**All 53 domain agents are config-backed:**

- Signal (Flow 1): 6 agents
- Plan (Flow 2): 8 agents
- Build (Flow 3): 9 agents
- Gate (Flow 4): 6 agents
- Deploy (Flow 5): 3 agents
- Wisdom (Flow 6): 5 agents
- Cross-cutting: 5 agents
- Utility: 3 agents

**Important:** Do not manually edit `.claude/agents/*.md` frontmatter. Frontmatter is a generated artifact; changes will be overwritten. Edit config YAML instead.

### CI Enforcement

Every PR runs `make check-adapters` and `make validate-swarm`, which verify:

- All config-backed adapters' frontmatter matches config files
- AGENTS.md <-> config YAML bijection
- Semantic consistency (role_family <-> category, color)

Misalignment fails the build.

---

## Skills vs. Agents

**Skills** (`.claude/skills/*/SKILL.md`): Global, model-invoked capabilities available to all agents:

- `test-runner` — Execute test suites, write `test_output.log` and `test_summary.md`
- `auto-linter` — Mechanical lint/format fixes
- `policy-runner` — Policy-as-code validation
- `heal_selftest` — Diagnose and repair selftest failures

**Skill inheritance**:

- **By default** (no `skills:` in frontmatter): agents inherit **all available Skills**
- **When `skills: [skill1, skill2]` is specified**: agents can use **only** those Skills (restriction)

Use `skills:` frontmatter only when you want to restrict a specific agent to a subset. Skills are **tools**, not agents—they cannot call other agents.

---

## Key Invariants

1. **Do not edit `.claude/agents/*.md` frontmatter by hand.** It's generated from config and changes will be overwritten.

2. **Always run the three Make commands after editing config.**
   ```bash
   make gen-adapters && make check-adapters && make validate-swarm
   ```

3. **Agent identifiers are case-sensitive and kebab-case.** The key must match:
   - The filename (`.claude/agents/<key>.md`)
   - The registry entry in `swarm/AGENTS.md`
   - Exactly.

4. **Color is derived, not chosen.** Your `role_family` determines the canonical color.

---

## Troubleshooting Frontmatter Errors

When validation reports frontmatter errors, the message includes file and line number:

```
FRONTMATTER: .claude/agents/my-agent.md:3 Invalid YAML: unclosed quote
Fix: Check line 3 for missing closing quote in YAML value
```

Common frontmatter mistakes:

- **Unclosed quotes:** `description: "This quote is not closed`
- **Bad indentation:** Extra spaces before keys
- **Missing colons:** `name value` instead of `name: value`
- **Missing closing `---` delimiter**

### Skill YAML Errors

Skill validation also reports line numbers and helpful context:

```
SKILL_FRONTMATTER: .claude/skills/test-runner/SKILL.md:5 Invalid YAML
Fix: Check line 5 for YAML syntax errors
```

### Debugging Steps

1. Open the file at the reported line number
2. Check for the specific error type mentioned
3. Ensure YAML frontmatter is properly delimited with `---` on both ends
4. Validate quotes are matched (both single `'` and double `"`)
5. Run `make validate-swarm` to confirm the fix
