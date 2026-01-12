# Build Your Own Swarm

> For: Developers who want to customize and extend this swarm framework.

This guide covers adding flows, agents, and customizing artifacts. For the basic edit loop, see [FLOW_STUDIO_FIRST_EDIT.md](./FLOW_STUDIO_FIRST_EDIT.md).

**Getting started:** See [How to Run Flow Studio Locally](./FLOW_STUDIO.md#how-to-run-flow-studio-locally) to set up your development environment.

---

## Overview

The demo swarm is a template. Edit configs, regenerate, validate, test.

---

## Adding a New Flow

### 1. Create Flow Config

Create `swarm/config/flows/<name>.yaml`:

```yaml
key: review
title: "Custom Flow: Code Review (Example)"
description: "Automated code review with multiple perspectives."

steps:
  - id: load_context
    agents: [context-loader]
    role: "Load PR diff and related files."
  - id: security_review
    agents: [security-scanner]
    role: "Check for security issues."
  - id: summarize
    agents: [review-summarizer]
    role: "Synthesize findings into review_summary.md."

cross_cutting:
  - gh-reporter
```

### 2. Create Flow Spec

Create `swarm/flows/flow-<name>.md` with mermaid diagram, step table, and RUN_BASE pathing. See `swarm/flows/flow-build.md` for format.

### 3. Create Slash Command

Create `.claude/commands/flow-<n>-<name>.md`:

```yaml
---
description: Run Custom Flow (Code Review): automated multi-perspective review.
---

# Custom Flow: Code Review (Example)
...
```

### 4. Regenerate and Validate

```bash
make gen-adapters && make validate-swarm
```

---

## Adding a New Agent

### 1. Register in AGENTS.md

Add to `swarm/AGENTS.md`:

```markdown
| style-checker | review | verification | blue | project/user | Enforce style guidelines. |
```

### 2. Create Config File

Create `swarm/config/agents/<key>.yaml`:

```yaml
key: style-checker
flows: [review]
category: verification
color: blue
source: project/user
short_role: "Enforce style guidelines."
model: inherit
```

### 3. Create Agent Definition

Create `.claude/agents/<key>.md`:

```yaml
---
name: style-checker
description: Enforce style guidelines.
color: blue
model: inherit
---

You are the **Style Checker**.

## Inputs
- `RUN_BASE/review/pr_diff.md`

## Outputs
- `RUN_BASE/review/style_findings.md`

## Behavior
1. Read the PR diff.
2. Check against style guidelines.
3. Set Status: VERIFIED or UNVERIFIED.
```

### 4. Reference in Flow Config

Add to `swarm/config/flows/<flow>.yaml`:

```yaml
steps:
  - id: style_review
    agents: [style-checker]
    role: "Enforce style guidelines."
```

### 5. Regenerate and Validate

```bash
make gen-adapters && make check-adapters && make validate-swarm
```

---

## Customizing Step Artifacts

### Conventions

- Use `RUN_BASE` placeholder, never hardcoded paths
- Artifacts are markdown or JSON
- Code changes go in `src/`, `tests/`, not RUN_BASE

### In Agent Prompts

```markdown
## Outputs
- `RUN_BASE/review/style_findings.md`: Summary of violations with line numbers
```

---

## The Edit Loop

```
Edit Config --> gen-adapters --> validate-swarm --> Test
```

1. **Edit**: `swarm/config/agents/<key>.yaml` or `swarm/config/flows/<name>.yaml`
2. **Regenerate**: `make gen-adapters`
3. **Validate**: `make validate-swarm`
4. **Test**: `make flow-studio` and verify in browser

See [FLOW_STUDIO_FIRST_EDIT.md](./FLOW_STUDIO_FIRST_EDIT.md) for walkthrough.

---

## Validation

```bash
make validate-swarm    # Quick check
make selftest          # Full suite
```

### What It Checks

| Rule | Description |
|------|-------------|
| FR-001 | Bijection: AGENTS.md <-> `.claude/agents/*.md` |
| FR-002 | Frontmatter: required fields, valid values |
| FR-003 | Flow references: agents in flows exist |
| FR-005 | RUN_BASE: no hardcoded paths |
| FR-FLOWS | Flow invariants: no empty flows, no agentless steps |

See [VALIDATION_RULES.md](./VALIDATION_RULES.md) for details.

---

## Quick Recipes

### Change Agent Model

```yaml
# swarm/config/agents/<key>.yaml
model: sonnet  # or haiku, opus, inherit
```

### Create a Microloop

In your flow command, pair writer with critic:

```markdown
4. **Tighten code**: Loop `code-implementer` <-> `code-critic`:
   - If VERIFIED, proceed
   - If UNVERIFIED + `can_further_iteration_help: yes`, loop back
   - If UNVERIFIED + `can_further_iteration_help: no`, proceed
```

### Add Cross-Cutting Agent

Register in AGENTS.md with multiple flows, add to `cross_cutting:` in each flow config.

---

## File Reference

| Path | Purpose | Edit? |
|------|---------|-------|
| `swarm/config/agents/*.yaml` | Agent configs | Yes |
| `swarm/config/flows/*.yaml` | Flow configs | Yes |
| `.claude/agents/*.md` | Agent definitions | Body only |
| `.claude/commands/*.md` | Slash commands | Yes |
| `swarm/AGENTS.md` | Agent registry | Yes |

---

## Next Steps

- [FLOW_STUDIO_FIRST_EDIT.md](./FLOW_STUDIO_FIRST_EDIT.md) - Hands-on edit walkthrough
- [AGENT_OPS.md](./AGENT_OPS.md) - Agent management details
- [VALIDATION_RULES.md](./VALIDATION_RULES.md) - Validation rule reference
- `swarm/examples/health-check/` - Complete artifact examples
