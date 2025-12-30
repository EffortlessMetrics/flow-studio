## RUN_BASE Conventions

RUN_BASE is the root directory for all artifacts produced during a flow run. Understanding the pathing conventions ensures artifacts are placed correctly and can be found by downstream stations.

### RUN_BASE Definition

```
RUN_BASE = swarm/runs/<run-id>/
```

Where `<run-id>` is a unique identifier for the run (ticket ID, branch name, timestamp, etc.).

### Directory Structure

Each flow writes artifacts under `RUN_BASE/<flow>/`:

```
swarm/runs/<run-id>/
  signal/          # Flow 1 artifacts
  plan/            # Flow 2 artifacts
  build/           # Flow 3 artifacts
  gate/            # Flow 4 artifacts
  deploy/          # Flow 5 artifacts
  wisdom/          # Flow 6 artifacts
```

### Flow Directory Contents

| Flow | Directory | Typical Contents |
|------|-----------|------------------|
| Signal | `signal/` | problem_statement.md, requirements.md, bdd.feature, risk_assessment.md |
| Plan | `plan/` | adr.md, api_contracts.yaml, observability_spec.md, test_plan.md, work_plan.md |
| Build | `build/` | test_summary.md, impl_changes_summary.md, build_receipt.json, handoff/*.json |
| Gate | `gate/` | receipt_audit.md, security_scan.md, merge_decision.md |
| Deploy | `deploy/` | deployment_log.md, verification_report.md, deployment_decision.md |
| Wisdom | `wisdom/` | artifact_audit.md, regression_report.md, learnings.md, feedback_actions.md |

### Handoff Subdirectory

Each flow may include a `handoff/` subdirectory for station-to-station JSON:

```
RUN_BASE/build/handoff/
  implement.draft.json
  test.draft.json
  code.verified.json
```

### Path Conventions

**In spec files**: Use `RUN_BASE/<flow>/` placeholder:
```
## Outputs
- `RUN_BASE/build/impl_changes_summary.md`
- `RUN_BASE/build/handoff/code.verified.json`
```

**In station prompts**: Use template variable `{{run.base}}`:
```
Read the test plan from {{run.base}}/plan/test_plan.md
Write your output to {{run.base}}/build/test_summary.md
```

**Never use**:
- Absolute system paths (`C:\Code\...`, `/home/user/...`)
- Hardcoded run IDs (`swarm/runs/ticket-123/...`)

### What Lives Outside RUN_BASE

Production code and tests are **not** in RUN_BASE:

| Content | Location | Notes |
|---------|----------|-------|
| Source code | `src/` | Authoritative implementation |
| Tests | `tests/` | Authoritative test suite |
| BDD features | `features/` | Gherkin scenarios |
| Migrations | `migrations/` | Database migrations |
| Fuzz harnesses | `fuzz/` | Fuzzing targets |

Flow artifacts describe and audit code; they do not contain the code itself.

### Run Lifecycle

1. **Creation**: Orchestrator creates `RUN_BASE` at flow start
2. **Population**: Stations write artifacts to their flow directory
3. **Handoff**: Each station's handoff JSON enables next station
4. **Archival**: Completed runs may be archived or cleaned up
5. **Gitignore**: `swarm/runs/` is gitignored (active runs are ephemeral)

### Curated Examples

For committed example artifacts, use `swarm/examples/<scenario>/`:

```
swarm/examples/health-check/
  signal/
  plan/
  build/
  gate/
  deploy/
  wisdom/
  code-snapshot/    # Read-only copies for teaching
  README.md
```

Examples are committed to git; active runs are not.

### Validation

The swarm validator (FR-005) checks:
- Flow specs use `RUN_BASE/` placeholder, not hardcoded paths
- No absolute system paths in artifact references
- Station outputs reference valid flow directories
