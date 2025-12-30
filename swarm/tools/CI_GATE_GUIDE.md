# CI Gate Validation Guide

The `ci_validate_swarm.sh` script provides a production-ready CI gate for enforcing swarm configuration integrity through the validator's JSON output contract.

## Overview

This script:
- Runs `validate_swarm.py --json` to get structured validation output
- Parses the JSON using `jq` to enforce specific Functional Requirements (FRs)
- Provides flexible enforcement modes: all checks, specific FRs, or fail-on-warn
- Outputs human-readable summaries with color coding
- Returns proper exit codes for CI/CD pipeline integration

## Features

- **Flexible enforcement**: Check all FRs or only specific ones
- **Strict mode**: `--fail-on-warn` to treat warnings as failures
- **Detailed reporting**: `--list-issues` to see all agent/flow problems
- **Quiet mode**: `--summary` for GitHub Actions logs
- **No external dependencies**: Uses only `bash`, `jq`, and `uv`

## Quick Start

Basic usage (fail if any check fails):
```bash
./swarm/tools/ci_validate_swarm.sh --fail-on-fail
```

Strict mode (fail on warnings too):
```bash
./swarm/tools/ci_validate_swarm.sh --fail-on-warn
```

Debug mode with full details:
```bash
./swarm/tools/ci_validate_swarm.sh --list-issues --fail-on-fail
```

Conservative gate (only FR-001 and FR-002):
```bash
./swarm/tools/ci_validate_swarm.sh --enforce-fr FR-001,FR-002 --fail-on-fail
```

## Functional Requirements (FRs)

The validator checks these FRs:

| FR | Description | Enforces |
|----|-------------|----------|
| **FR-001** | Bijection | 1:1 mapping between `swarm/AGENTS.md` and `.claude/agents/*.md` files |
| **FR-002** | Frontmatter | Valid YAML with required fields (`name`, `description`, `color`, `model`) |
| **FR-002b** | Color matching | Agent color matches role family in AGENTS.md |
| **FR-003** | Flow references | All agents in flow specs exist in registry or are built-ins |
| **FR-004** | Skills | All skill declarations have matching SKILL.md files |
| **FR-005** | RUN_BASE paths | Flow specs use `RUN_BASE/` placeholders, not hardcoded paths |
| **FR-CONF** | Config alignment | Config YAML matches generated frontmatter |

## Usage Examples

### Example 1: Basic CI Gate

Fail the build if any validation check fails:

```bash
./swarm/tools/ci_validate_swarm.sh --fail-on-fail
echo "Validation passed"
```

Exit code: 0 if all checks pass, 1 if any fail, 2 if fatal error

### Example 2: Strict Enforcement

Fail on warnings (useful for early PRs or production):

```bash
./swarm/tools/ci_validate_swarm.sh --fail-on-warn --list-issues
```

### Example 3: Conservative Gate

Only enforce critical FRs (bijection, frontmatter):

```bash
./swarm/tools/ci_validate_swarm.sh \
  --enforce-fr FR-001,FR-002,FR-002b \
  --fail-on-fail
```

### Example 4: Debug / Local Development

Full details for troubleshooting:

```bash
./swarm/tools/ci_validate_swarm.sh --list-issues --fail-on-fail
```

Output shows:
- Validation summary (passed, failed, warnings)
- List of agents with issues
- List of flows with issues
- Per-FR status for each

### Example 5: Quiet Mode (Logs)

Minimal output for GitHub Actions logs:

```bash
./swarm/tools/ci_validate_swarm.sh --summary --fail-on-fail
```

Output: `Validation: PASS (P: 42, F: 0, W: 0)`

## GitHub Actions Integration

Add to `.github/workflows/swarm-validate.yml`:

```yaml
name: Swarm Validation

on:
  push:
    branches: [main, develop]
    paths:
      - '.claude/**'
      - 'swarm/**'
  pull_request:
    paths:
      - '.claude/**'
      - 'swarm/**'

jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'

      - name: Install uv
        run: curl -LsSf https://astral.sh/uv/install.sh | sh

      - name: Install jq
        run: sudo apt-get install -y jq

      - name: Run swarm validation gate
        run: |
          ./swarm/tools/ci_validate_swarm.sh --fail-on-fail --list-issues
```

## Make Integration

Add to `Makefile`:

```makefile
.PHONY: ci-validate
ci-validate:
	./swarm/tools/ci_validate_swarm.sh --fail-on-fail --list-issues

.PHONY: ci-validate-strict
ci-validate-strict:
	./swarm/tools/ci_validate_swarm.sh --fail-on-warn --list-issues
```

Then in CI:
```bash
make ci-validate
```

## Exit Codes

| Code | Meaning | CI Action |
|------|---------|-----------|
| 0 | Validation passed | Continue |
| 1 | Validation failed | Fail build/PR |
| 2 | Fatal error | Fail build (missing tools, JSON parse error) |

## JSON Output Contract

The script parses this JSON structure from `validate_swarm.py --json`:

```json
{
  "summary": {
    "status": "PASS" | "FAIL",
    "passed": <int>,
    "failed": <int>,
    "warnings": <int>,
    "agents_with_issues": ["key1", "key2"],
    "flows_with_issues": ["flow-id1"]
  },
  "agents": {
    "<key>": {
      "file": "<path>",
      "checks": {
        "FR-001": { "status": "pass" | "fail" | "warn" },
        "FR-002": { ... },
        ...
      },
      "has_issues": <bool>,
      "issues": [ ... ]
    }
  },
  "flows": {
    "<flow-id>": {
      "file": "<path>",
      "checks": { ... },
      "has_issues": <bool>,
      "issues": [ ... ]
    }
  }
}
```

## JQ Filters Reference

Common filters used by the script (and for custom analysis):

```bash
# Overall status
jq '.summary.status' validate_output.json

# Quick stats
jq '.summary | {passed, failed, warnings}' validate_output.json

# Agents with issues
jq '.summary.agents_with_issues[]' validate_output.json

# All failed checks
jq '.agents[].checks | to_entries[] | select(.value.status == "fail")' validate_output.json

# Count agents with issues
jq '.agents | map(select(.has_issues)) | length' validate_output.json

# Get specific agent's status
jq '.agents["adr-author"]' validate_output.json

# List all failures across agents and flows
jq '.agents | to_entries[] | select(.value.has_issues) | {key: .key, issues: .value.issues}' validate_output.json
```

## Troubleshooting

### "jq is required but not found"

Install jq:
```bash
# Ubuntu/Debian
sudo apt-get install jq

# macOS
brew install jq

# Alpine
apk add jq
```

### "uv is required but not found"

Install uv:
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### "Validator produced invalid JSON"

The validator crashed or returned malformed output. Check:
```bash
# Run validator directly to see error
uv run swarm/tools/validate_swarm.py --json
```

### Script returns exit code 2

Fatal error: check dependencies first:
```bash
which jq   # Should exist
which uv   # Should exist
```

### Want to check specific FRs in isolation

```bash
# Only check bijection and color matching
./swarm/tools/ci_validate_swarm.sh --enforce-fr FR-001,FR-002b
```

## Advanced Patterns

### Pattern 1: Strict for main, lenient for branches

```yaml
jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: sudo apt-get install -y jq
      - run: curl -LsSf https://astral.sh/uv/install.sh | sh

      - name: Validate swarm
        run: |
          if [ "${{ github.ref }}" == "refs/heads/main" ]; then
            ./swarm/tools/ci_validate_swarm.sh --fail-on-warn --list-issues
          else
            ./swarm/tools/ci_validate_swarm.sh --fail-on-fail
          fi
```

### Pattern 2: Report validation results as GitHub check

```bash
# Parse validation results and create a check annotation
RESULT=$(./swarm/tools/ci_validate_swarm.sh --summary 2>&1)
if [ $? -eq 0 ]; then
  echo "::notice title=Swarm Validation::$RESULT"
else
  echo "::error title=Swarm Validation::$RESULT"
  exit 1
fi
```

### Pattern 3: Progressive validation enforcement

Start loose, tighten over time:

```bash
# PR: only enforce core FRs
./swarm/tools/ci_validate_swarm.sh --enforce-fr FR-001,FR-002,FR-002b

# Merge to develop: stricter
./swarm/tools/ci_validate_swarm.sh --fail-on-fail

# Merge to main: strictest
./swarm/tools/ci_validate_swarm.sh --fail-on-warn
```

## Performance

The script is fast:
- Validator runtime: ~1-2 seconds
- JSON parsing: <100ms
- Total gate latency: ~1-2 seconds on typical repos (48 agents, 7 flows)

For very large swarms (100+ agents), use `validate_swarm.py --check-modified` to validate only changed files.

## Design Philosophy

- **Fail fast**: Exit code signals pipeline decision immediately
- **Human-readable**: Color-coded output, clear issue listing
- **Composable**: Use with `&&` or `||` for chaining
- **CI/CD native**: Works in GitHub Actions, GitLab CI, Jenkins, etc.
- **No magic**: Simple bash, just calls validator and parses JSON

## See Also

- `swarm/tools/validate_swarm.py` - Core validation logic
- `CLAUDE.md` - Full swarm documentation
- `swarm/AGENTS.md` - Agent registry
- `.github/workflows/` - Example GitHub Actions workflows
