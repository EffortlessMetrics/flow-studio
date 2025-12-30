# Operator Flows Guide

> For: Developers and operators running the swarm day-to-day.
>
> **Prerequisites:** [GETTING_STARTED.md](./GETTING_STARTED.md) | **Related:** [FLOW_STUDIO.md](./FLOW_STUDIO.md)

This guide consolidates the three main workflows operators use: Demo (onboarding), Development (daily work), and Wisdom (cross-run analysis).

---

## Quick Reference

| Workflow | Command | Time | Purpose |
|----------|---------|------|---------|
| **Demo** | `make demo-swarm` | ~2min | Full demo with stepwise run + Flow Studio |
| **Fast Check** | `make kernel-smoke` | ~300ms | KERNEL tier only |
| **Full Check** | `make dev-check` | ~2min | All validation + selftest |
| **Wisdom** | `make wisdom-cycle RUN_ID=<id>` | ~30s | Aggregate learnings |

---

## Demo Workflow (New Users)

For new users exploring the swarm or giving demonstrations.

### One-Command Entry

```bash
make demo-swarm
```

This single command:

1. Runs validation (`make dev-check`)
2. Previews run cleanup (`make runs-prune-dry`)
3. Creates a stepwise SDLC stub demo
4. Starts Flow Studio at `http://localhost:5000`

**What you get:**
- Stepwise demo run with all 7 flows (stub mode, no LLM costs)
- Flow Studio visualization
- Demo links printed to console

### Step-by-Step Alternative

If you prefer more control:

```bash
# Step 1: Install dependencies
uv sync --extra dev

# Step 2: Verify swarm is healthy
make dev-check

# Step 3: Populate example run
make demo-run

# Step 4: Start Flow Studio
make flow-studio
```

Then open `http://localhost:5000/?run=demo-health-check&mode=operator`

### What You Get

| Artifact | Location | Description |
|----------|----------|-------------|
| Demo run | `swarm/runs/demo-health-check/` | Pre-populated artifacts for all 7 flows |
| Flow visualization | `http://localhost:5000` | Interactive graph of flows, steps, agents |
| Example scenarios | `swarm/examples/` | Golden examples for comparison |

### Demo Links

These URLs are useful during presentations:

```
# Baseline (operator mode)
http://localhost:5000/?run=demo-health-check&mode=operator

# Governance status
http://localhost:5000/?tab=validation&mode=governance

# Build microloops
http://localhost:5000/?run=demo-health-check&flow=build&view=agents
```

---

## Development Workflow (Daily Use)

For developers contributing to the swarm. Two loops: inner (fast iteration) and outer (before commit/push).

### Inner Loop (Fast Iteration)

When actively coding, use fast checks for tight feedback:

```bash
# KERNEL tier only (~300ms)
make kernel-smoke

# Full kernel check (~400ms)
make selftest-fast
```

**What these check:**
- Python syntax errors (compileall)
- Linting (ruff)
- No governance or integration tests

**When to use:** During active development, before every commit.

### Outer Loop (Before Commit)

Before pushing to GitHub, run full validation:

```bash
# Full validation + selftest (all 16 steps)
make dev-check
```

**What `dev-check` does:**

```bash
make gen-adapters       # Regenerate adapters from config
make gen-flows          # Regenerate flows from config
make gen-flow-constants # Generate TypeScript constants
make gen-index-html     # Regenerate Flow Studio UI
make check-adapters     # Verify adapters match config
make check-flows        # Verify flows match config
make validate-swarm     # Run FR-001 through FR-005 checks
make ts-check           # TypeScript type-checking
make docs-check         # Validate documentation structure
make selftest           # Run all 16 selftest steps
```

**Exit codes:**
- **0**: All passed, safe to push
- **1**: KERNEL or GOVERNANCE failed, fix before pushing
- **2**: Config error (selftest harness broken), escalate

### Pytest Test Taxonomy

For more targeted testing, use pytest marks:

```bash
# Isolated logic tests (no I/O, <100ms)
make test-unit

# CLI, file I/O, subprocess tests
make test-integration

# Tests that take >1 second
make test-slow

# Fast tests only (<100ms)
make test-quick

# All pytest tests
make test-all
```

### Stepwise Execution

Stepwise backends execute flows one step at a time, enabling per-step observability:

```bash
# Zero-cost demo (stub mode, no LLM calls)
make stepwise-sdlc-stub

# Real Claude via CLI (uses Claude Code login)
make stepwise-sdlc-claude-cli

# Real Claude via SDK (requires ANTHROPIC_API_KEY)
make stepwise-sdlc-claude-sdk

# Gemini stepwise (stub mode)
make stepwise-sdlc-gemini

# Show all stepwise commands
make stepwise-help
```

**Stepwise artifacts:**
- Transcripts: `RUN_BASE/<flow>/llm/<step>-<agent>-<engine>.jsonl`
- Receipts: `RUN_BASE/<flow>/receipts/<step>-<agent>.json`
- Events: `RUN_BASE/events.jsonl`

See [STEPWISE_BACKENDS.md](./STEPWISE_BACKENDS.md) for full documentation.

---

## Wisdom Workflow (Cross-Run Analysis)

For extracting learnings and patterns from completed runs.

### Single Run Summary

Generate a wisdom summary for a specific run:

```bash
make wisdom-summary RUN_ID=<run-id>
```

**Output:** `swarm/runs/<run-id>/wisdom/wisdom_summary.json`

Contains:
- Flow execution metrics
- Agent performance statistics
- Error patterns
- Artifact inventory

### Cross-Run Aggregation

Aggregate wisdom across all runs:

```bash
# JSON output
make wisdom-aggregate

# Markdown report
make wisdom-report
```

**Output:** `wisdom_report.md` in repo root with:
- Run statistics (total, success rate, avg duration)
- Common failure patterns
- Agent performance trends
- Recommendations

### Full Wisdom Cycle

Combine summary generation, aggregation, and cleanup preview:

```bash
# For a specific run
make wisdom-cycle RUN_ID=<run-id>

# For all runs (no specific run)
make wisdom-cycle
```

**This command:**

1. Generates wisdom summary for specified run (if `RUN_ID` provided)
2. Aggregates wisdom across all runs
3. Generates `wisdom_report.md`
4. Previews runs eligible for cleanup

---

## Troubleshooting

### Flow Studio Won't Start

**Symptoms:** Port 5000 in use, TypeScript errors, or Flask startup failure.

**Solution:**

```bash
# Step 1: Diagnose selftest issues
make selftest-doctor

# Step 2: Rebuild TypeScript
make ts-build

# Step 3: Check port availability
lsof -i :5000

# Step 4: Use alternative port if needed
uv run uvicorn swarm.tools.flow_studio_fastapi:app --reload --host 127.0.0.1 --port 5001
```

### Stale Runs

**Symptoms:** Too many runs in `swarm/runs/`, Flow Studio is slow.

**Solution:**

```bash
# List runs and statistics
make runs-list

# Verbose: show individual runs with age/size
make runs-list-v

# Preview what would be deleted (dry run)
make runs-prune-dry

# Apply retention policy
make runs-prune
```

**Retention policy defaults:**
- Keep runs for 30 days
- Maximum 300 runs
- Preserve: `demo-*`, `stepwise-*`, `baseline-*`, pinned/golden tags

### Corrupt Runs

**Symptoms:** "Failed to parse summary" errors, runs showing as corrupt in Flow Studio.

**Solution:**

```bash
# Preview corrupt runs to quarantine
make runs-quarantine-dry

# Move corrupt runs to swarm/runs/_corrupt/
make runs-quarantine

# Examine manually if needed
ls swarm/runs/_corrupt/
cat swarm/runs/_corrupt/<run-id>/meta.json
```

### Selftest Failures

**Symptoms:** CI red, `make selftest` failing.

**Solution:**

```bash
# Step 1: Run the doctor
make selftest-doctor

# Step 2: Run failing step in verbose mode
uv run swarm/tools/selftest.py --step <step-id> --verbose

# Step 3: Get AI-suggested fixes
make selftest-suggest-remediation

# Step 4: Generate incident pack for escalation
make selftest-incident-pack
```

### Validation Errors

**Symptoms:** FR-001 through FR-005 failures.

**Solution:**

```bash
# Run validator with verbose output
uv run swarm/tools/validate_swarm.py --strict

# Common fixes by FR:
# FR-001 (agent registry): make check-adapters && make gen-adapters
# FR-002 (frontmatter):    edit swarm/config/agents/<key>.yaml
# FR-003 (flow refs):      check swarm/config/flows/<flow>.yaml
# FR-005 (hardcoded paths): use RUN_BASE/ placeholder
```

### Validation Reporting

Generate validation reports for documentation or CI integration:

```bash
# Human-readable markdown report
uv run swarm/tools/validate_swarm.py --report markdown > validation_report.md

# Machine-readable JSON report
uv run swarm/tools/validate_swarm.py --report json > validation_report.json

# Detailed per-agent breakdown
uv run swarm/tools/validate_swarm.py --json | jq .summary
```

The `--report` flag produces standalone reports suitable for archiving or CI artifacts, while `--json` provides structured output for programmatic processing.

---

## Command Quick Reference

### Demo Commands

| Command | Description |
|---------|-------------|
| `make demo-swarm` | One-command full demo (validate + stepwise + Flow Studio) |
| `make demo-flow-studio` | Quick demo (sync, populate, launch Flow Studio) |
| `make demo-selftest` | Governance introspection demo |
| `make demo-run` | Populate example run at `swarm/runs/demo-health-check/` |

### Development Commands

| Command | Time | Description |
|---------|------|-------------|
| `make kernel-smoke` | ~300ms | KERNEL tier only |
| `make selftest-fast` | ~400ms | Fast kernel check |
| `make selftest` | ~2min | Full 16-step selftest |
| `make dev-check` | ~2min | Full validation + selftest |
| `make dev-check-fast` | ~1min | Fast variant (skips flowstudio-smoke) |

### Test Commands

| Command | Description |
|---------|-------------|
| `make test-unit` | Isolated logic tests (no I/O) |
| `make test-integration` | CLI, file I/O, subprocess tests |
| `make test-slow` | Tests >1 second |
| `make test-quick` | Fast tests only (<100ms) |
| `make test-all` | All pytest tests |

### Stepwise Commands

| Command | Description |
|---------|-------------|
| `make stepwise-sdlc-stub` | Zero-cost demo (both backends, stub mode) |
| `make stepwise-sdlc-claude-cli` | Real Claude via CLI |
| `make stepwise-sdlc-claude-sdk` | Real Claude via SDK |
| `make stepwise-sdlc-gemini` | Gemini stepwise (stub mode) |
| `make stepwise-help` | Show all stepwise commands |

### Wisdom Commands

| Command | Description |
|---------|-------------|
| `make wisdom-summary RUN_ID=<id>` | Generate summary for one run |
| `make wisdom-aggregate` | Aggregate all runs (JSON) |
| `make wisdom-report` | Aggregate all runs (Markdown) |
| `make wisdom-cycle RUN_ID=<id>` | Full cycle: summarize + aggregate + preview cleanup |

### Cleanup Commands

| Command | Description |
|---------|-------------|
| `make runs-list` | Show run statistics |
| `make runs-list-v` | Verbose: individual runs with age/size |
| `make runs-prune-dry` | Preview cleanup (dry run) |
| `make runs-prune` | Apply retention policy |
| `make runs-quarantine-dry` | Preview corrupt runs |
| `make runs-quarantine` | Move corrupt runs to `_corrupt/` |
| `make runs-clean` | Nuclear: rm -rf run-* (preserves examples) |
| `make runs-gc-help` | Full garbage collection help |

---

## See Also

- [STEPWISE_BACKENDS.md](./STEPWISE_BACKENDS.md) - Stepwise execution architecture and configuration
- [RUN_LIFECYCLE.md](./RUN_LIFECYCLE.md) - How runs are created, executed, and cleaned up
- [SELFTEST_DEVELOPER_WORKFLOW.md](./SELFTEST_DEVELOPER_WORKFLOW.md) - Detailed selftest debugging guide
- [FLOW_STUDIO.md](./FLOW_STUDIO.md) - Flow Studio UI reference
- [GETTING_STARTED.md](./GETTING_STARTED.md) - First-time setup guide
- [CI_TROUBLESHOOTING.md](./CI_TROUBLESHOOTING.md) - CI-specific troubleshooting
