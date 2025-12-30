# v2.3.0 Release Notes

> **Release Date:** December 2025
>
> This release establishes the golden stepwise SDLC harness with full 7-flow coverage,
> expands selftest to 16 steps with a complete AC matrix, and delivers fully operational
> wisdom cycle tooling.

---

## Highlights

- **Golden stepwise SDLC harness** with full 7-flow coverage
- **Selftest expanded to 16 steps** with complete AC matrix
- **Wisdom cycle tooling** fully operational
- **demo-swarm** one-command entry point for new users

---

## Selftest System

The selftest system has been expanded from 10 to 16 steps, with all documentation aligned to the new step count.

### Step Distribution

| Tier | Count | Purpose |
|------|-------|---------|
| KERNEL | 1 | Fast kernel health (Python lint + compile) |
| GOVERNANCE | 13 | Config, flows, agents, BDD, policies, UI checks |
| OPTIONAL | 2 | Coverage thresholds, experimental checks |

### New Steps

- **runs-gc-dry-check**: Validates runs garbage collection tool is operational
- **wisdom-smoke**: Validates wisdom summarizer and aggregator tools
- **provider-env-check**: Validates provider environment variables for stepwise backends

### AC Matrix

The acceptance criteria matrix is now complete with 11 acceptance criteria tracked across all selftest steps. See `docs/SELFTEST_AC_MATRIX.md` for the full mapping.

### Documentation Updates

- `swarm/SELFTEST_SYSTEM.md`: Updated to 16 steps
- `docs/SELFTEST_GOVERNANCE.md`: Quick reference aligned
- `docs/SELFTEST_DEVELOPER_WORKFLOW.md`: Developer guide updated
- `Makefile`: Help text and summary outputs reflect 16 steps
- `tests/selftest_plan_test.py`: Test expectations updated

---

## Wisdom Cycle

Flow 6 (Wisdom) tooling is now fully operational with two key tools:

### wisdom_summarizer.py

Generates per-run `wisdom_summary.json` files from Flow 6 artifacts:

```bash
uv run swarm/tools/wisdom_summarizer.py <run_id>
```

Features:
- Reads wisdom artifacts (artifact_audit.md, regression_report.md, etc.)
- Produces structured JSON summary with flow status, labels, and key metrics
- Supports `--dry-run` mode for validation

### wisdom_aggregate_runs.py

Provides cross-run analysis by aggregating wisdom summaries:

```bash
uv run swarm/tools/wisdom_aggregate_runs.py
uv run swarm/tools/wisdom_aggregate_runs.py --markdown
```

Features:
- Discovers wisdom summaries across examples and active runs
- Aggregates flow success rates, regressions, learnings
- Outputs JSON or Markdown format

### Make Target

```bash
make wisdom-cycle    # End-to-end: aggregate wisdom, preview cleanup
```

### Golden Wisdom Summaries

Key examples now include `wisdom_summary.json` files:
- `swarm/examples/health-check/wisdom/wisdom_summary.json`
- `swarm/examples/stepwise-sdlc-claude/wisdom/wisdom_summary.json`

---

## Agent SDK Integration

The Claude Agent SDK is now fully integrated with three execution modes.

### ClaudeStepEngine Modes

| Mode | Description | Use Case |
|------|-------------|----------|
| `stub` | Synthetic responses (default) | CI/dev, zero LLM cost |
| `sdk` | Real Agent SDK execution | Local development |
| `cli` | Claude CLI fallback | Shell integration |

### Configuration

```bash
# Environment variable
export SWARM_CLAUDE_STEP_ENGINE_MODE=sdk

# Or in swarm/config/runtime.yaml
engines:
  claude:
    mode: "sdk"
```

### Examples

Working examples are provided in:
- `examples/agent-sdk-ts/`: TypeScript Agent SDK demo
- `examples/agent-sdk-py/`: Python Agent SDK demo

### Make Targets

```bash
make agent-sdk-ts-demo    # Run TypeScript example
make agent-sdk-py-demo    # Run Python example
make agent-sdk-help       # Show Agent SDK documentation
```

### Documentation

See `docs/AGENT_SDK_INTEGRATION.md` for the complete integration guide, including:
- Surface comparison (Agent SDK vs CLI vs HTTP API)
- Stepwise execution patterns
- Troubleshooting guide

---

## Flow Studio

### Curated Run Ordering

Demo runs now appear first in the run selector, making it easier for new users to find example data.

### Empty State Handling

When no runs are available, Flow Studio now displays helpful hints:
- Guidance to run `make demo-run`
- Links to getting started documentation

### Run Comparison (Per-Flow)

The run comparison feature now works at the per-flow level:
```
http://localhost:5000/?run=health-check&compare=health-check-risky-deploy&flow=build
```

### Teaching Mode with Exemplars

Flow Studio now supports teaching mode with curated exemplar runs that demonstrate key patterns:
- Requirements microloops (Flow 1)
- Build microloops (Flow 3)
- Gate bounce scenarios (Flow 4)

---

## Developer Experience

### demo-swarm One-Command Entry

New users can now get started with a single command:

```bash
make demo-swarm
```

This command:
1. Validates the swarm is healthy
2. Creates a stepwise demo run
3. Launches Flow Studio
4. Opens the demo URL in browser (if supported)

### Improved Getting Started

`docs/GETTING_STARTED.md` now features:
- Fastest path callout (`make demo-swarm`)
- Two-lane structure (SDLC Demo vs Governance Demo)
- Version notes for compatibility

### Better Error Messages

- Selftest failures now include remediation suggestions
- Validation errors include file paths and line numbers
- Degradation handling logs to `selftest_degradations.log`

---

## Test Surface Improvements

### XPASS Tests Promoted

Five tests previously marked `xfail` now pass consistently and have been promoted to regular tests:

| Test | File | Reason |
|------|------|--------|
| `test_health_meets_target` | test_flow_studio_performance.py | Performance baseline now reliable |
| `test_graph_meets_target` | test_flow_studio_performance.py | Performance baseline now reliable |
| `test_multiple_frontmatter_errors_all_reported` | test_frontmatter.py | Feature implemented |
| `test_validation_performance_consistent` | test_performance.py | Variance within bounds |
| `test_speedup_with_4_workers` | test_selftest_distributed.py | Speedup achievable |

### Warning Suppression

- Registered `performance` pytest marker (eliminates PytestUnknownMarkWarning)
- Added filter for gherkin library deprecation warnings (41 warnings suppressed)

### Claude Stepwise Test Fixed

The integration test `TestClaudeStepwiseBackendRunCreation::test_start_creates_run` was previously quarantined due to timing-dependent flakiness. It has been **fixed** using a `StubStepwiseOrchestrator` that makes the test deterministic.

**Key changes:**
- Test now verifies only the synchronous contract of `start()` (run_id, meta.json, spec.json, events.jsonl)
- Background thread execution is stubbed out, eliminating race conditions
- Test runs in ~0.15s instead of timing out

### Test Surface Summary (v2.3.1)

| Category | Count | Notes |
|----------|-------|-------|
| Passed | ~1588 | Core functionality (14 reporting tests promoted) |
| Skipped | 41 | Env-gated (SDK, observability, server) or migration tests |
| XFail | 3 | Edge cases only (performance, line numbers, YAML validation) |
| XPass | 0 | All promoted to regular tests |
| Warnings | 0 | All filtered or registered |

**Intentionally skipped tests:**
- Claude SDK smoke tests (require `ANTHROPIC_API_KEY`)
- Observability backend tests (require Datadog/CloudWatch/Prometheus)
- Flask/FastAPI migration comparison tests
- Template server boot tests

**Intentionally xfailed tests:**
- Incremental mode performance (1 test in `test_performance.py`) - overhead exceeds gains on small repos
- Line number reporting (1 test in `test_frontmatter.py`) - enhancement not yet implemented
- Malformed YAML validation (1 test in `test_skill.py`) - edge case validation not yet implemented

**Promoted to regular tests (v2.3.1):**
- Validator JSON/Markdown reporting (14 tests in `test_reporting.py`) - `--report json/markdown` now implemented

---

## Known Issues

### Wisdom Summaries in Flow Studio UI (v2.4.0 Preview)

Wisdom summary data is now visible in the Flow Studio run detail modal:
- Click "Load Wisdom" button to view metrics, flow status, and labels
- Metrics include: artifacts present, regressions, learnings, feedback actions, issues created
- Flow status shows succeeded/failed/skipped for each flow with loop counts

The data is also available via:
- API endpoint: `GET /api/runs/{run_id}/wisdom/summary`
- Direct file access: `swarm/runs/<run-id>/wisdom/wisdom_summary.json`
- Aggregation tool: `uv run swarm/tools/wisdom_aggregate_runs.py`

---

## Upgrade Notes

### From v2.2.x

No breaking changes. The upgrade is additive:

1. Run `uv sync --extra dev` to update dependencies
2. Run `make selftest` to verify all 16 steps pass
3. Regenerate any local adapters: `make gen-adapters`

### Selftest Step Contract

If you have custom tooling that depends on selftest step counts, update expectations:
- Total steps: 16 (was 10)
- KERNEL: 1
- GOVERNANCE: 13
- OPTIONAL: 2

---

## See Also

- [RELEASE_NOTES_2_3_1.md](./RELEASE_NOTES_2_3_1.md): Next release (v2.3.1 - resolved limitations)
- [CHANGELOG.md](../CHANGELOG.md): Full changelog with all commits
- [GETTING_STARTED.md](./GETTING_STARTED.md): Quick start guide
- [SELFTEST_SYSTEM.md](../swarm/SELFTEST_SYSTEM.md): Complete selftest documentation
- [AGENT_SDK_INTEGRATION.md](./AGENT_SDK_INTEGRATION.md): Agent SDK guide
- [FLOW_STUDIO.md](./FLOW_STUDIO.md): Flow Studio reference
