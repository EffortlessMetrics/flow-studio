---
description: Interactively customize DemoSwarm for your stack
---

# Customize DemoSwarm Pack

You are guiding the user through customizing the DemoSwarm pack for their specific repository and stack.

## Purpose

This command helps newcomers adapt the pack to their codebase by:
1. Detecting existing patterns in the repository
2. Asking targeted questions about stack and preferences
3. Updating skill files and agent prompts accordingly
4. Writing a receipt documenting all changes

## Customization Workflow

### Step 1: Detect Current Environment

Before asking questions, use explore agents to scan the repository to infer:

```bash
# Detect language/runtime (use test -f for reliability)
test -f package.json && echo "Node.js detected"
test -f Cargo.toml && echo "Rust detected"
test -f pyproject.toml && echo "Python (pyproject) detected"
test -f setup.py && echo "Python (setup.py) detected"
test -f requirements.txt && echo "Python (requirements) detected"
test -f go.mod && echo "Go detected"

# Detect test framework
test -f package.json && grep -q '"jest"\|"vitest"\|"mocha"' package.json && echo "JS test framework detected"
test -f pyproject.toml && grep -q 'pytest' pyproject.toml && echo "pytest detected"
test -f Cargo.toml && echo "Rust tests (cargo test) detected"

# Detect lint tools
test -f .eslintrc.js -o -f .eslintrc.json -o -f .eslintrc.yml && echo "ESLint detected"
test -f .prettierrc -o -f .prettierrc.json -o -f .prettierrc.js && echo "Prettier detected"
test -f ruff.toml && echo "Ruff detected"
test -f pyproject.toml && grep -Fq '[tool.ruff]' pyproject.toml && echo "Ruff (in pyproject) detected"
test -f rustfmt.toml && echo "rustfmt detected"

# Detect source layout (use test -d for directories)
test -d src && echo "src/ found"
test -d lib && echo "lib/ found"
test -d app && echo "app/ found"
test -d tests && echo "tests/ found"
test -d test && echo "test/ found"
test -d __tests__ && echo "__tests__/ found"
test -d spec && echo "spec/ found"
```

### Step 2: Ask Targeted Questions

Based on detection, ask for confirmation or clarification:

**Questions to ask (adapt based on detection):**

1. **Language/Runtime**: "I detected [X]. Is this the primary language for this project?"
2. **Test Command**: "What command runs your tests?" (suggest based on detection)
3. **Lint/Format Command**: "What commands format and lint your code?"
4. **Source Layout**: "I see your source code is in [X] and tests in [Y]. Is this correct?"
5. **Git Provider**: "Are you using GitHub, GitLab, Bitbucket, or another provider?"
6. **Windows Environment**: "Are you using WSL2, Git Bash, or native PowerShell?"
7. **Mutation Harness (optional)**: "Do you have mutation testing configured? If so, what command should we run?"
8. **Fuzz Harness (optional)**: "Do you have fuzzing configured? If so, what command should we run?"

Use the AskUserQuestion tool to gather this information.

### Step 3: Update Skills

Based on answers, update the following files:

**`.claude/skills/test-runner/SKILL.md`**:
- Replace the test command with the user's command
- Update any language-specific patterns

**`.claude/skills/auto-linter/SKILL.md`**:
- Replace format and lint commands
- Update file patterns if needed

**`.claude/skills/policy-runner/SKILL.md`**:
- Update policy check commands if the user has them

### Step 4: Update Agent Prompts (If Needed)

If source layout differs from default (`src/`, `tests/`, `features/`), update:
- `code-implementer.md` - Where to write code
- `test-author.md` - Where to write tests
- `bdd-author.md` - Where to write features

If Git provider is not GitHub, update:
- `gh-issue-manager.md`
- `gh-reporter.md`
- `gh-researcher.md`
- `repo-operator.md`
- `deploy-monitor.md`

### Step 5: Write Configuration Receipt

Create `demo-swarm.config.json` in repo root:

```json
{
  "version": 1,
  "customized_at": "<ISO8601>",
  "stack": {
    "language": "rust | node | python | go | other",
    "runtime": "<specific runtime if relevant>",
    "package_manager": "cargo | npm | pnpm | yarn | pip | poetry | go"
  },
  "commands": {
    "test": "<test command>",
    "lint": "<lint command>",
    "format": "<format command>"
  },
  "mutation": {
    "command": "<mutation command or null>",
    "budget_seconds": 300,
    "survivor_threshold": 0
  },
  "fuzz": {
    "command": "<fuzz command or null>",
    "budget_seconds": 300
  },
  "flakiness": {
    "command": "<flakiness rerun command or null>",
    "rerun_count": 3,
    "budget_seconds": 180
  },
  "layout": {
    "source": "src/",
    "tests": "tests/",
    "features": "features/",
    "docs": "docs/"
  },
  "environment": {
    "platform": "linux | macos | windows-wsl2 | windows-gitbash",
    "git_provider": "github | gitlab | bitbucket | azure-devops"
  },
  "files_modified": [
    ".claude/skills/test-runner/SKILL.md",
    ".claude/skills/auto-linter/SKILL.md"
  ]
}
```

### Step 6: Write Customization Receipt

Create `docs/CUSTOMIZATION_RECEIPT.md`:

```markdown
# DemoSwarm Customization Receipt

## Customized: <ISO8601 timestamp>

## Detected Stack

- **Language**: <detected>
- **Test Framework**: <detected>
- **Lint Tools**: <detected>

## User Choices

- **Test Command**: `<command>`
- **Lint Command**: `<command>`
- **Source Layout**: <layout>
- **Platform**: <platform>

## Files Modified

| File | Change |
|------|--------|
| `.claude/skills/test-runner/SKILL.md` | Updated test command to `<cmd>` |
| `.claude/skills/auto-linter/SKILL.md` | Updated lint commands |

## Next Steps

1. Review the changes in the modified files
2. Run `/flow-1-signal "test feature"` to validate the setup
3. If issues arise, manually adjust skill files per `docs/CUSTOMIZATION.md`
```

## Completion

Report to the user:
1. Summary of changes made
2. List of modified files
3. Suggested next step: run a test flow

## Important Notes

- Always preserve existing file structure when editing
- Make minimal changes—only what's needed for the stack
- Document every change in the receipt
- If unsure about a setting, ask rather than guess
- Default to GitHub if git provider is unclear
