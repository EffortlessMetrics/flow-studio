# Quality Events Specification

> For: PR cockpit authors, gate agents, and receipt auditors.

This document specifies the quality event types used in Flow Studio PR cockpits. Quality events are claims about code quality backed by receipts.

---

## 1. Quality Event Types

Quality events represent verifiable claims about code quality. Each event type has a defined scope, measurement method, and receipt backing.

### Event Categories

| Event Type | Scope | Description |
|------------|-------|-------------|
| **Interface Lock** | Contract/API boundaries | Public interfaces, exported types, and API signatures remain stable or change intentionally |
| **Complexity Cap** | Function/module metrics | Cyclomatic and cognitive complexity stay within defined thresholds |
| **Test Depth** | Coverage and edge cases | Test coverage meets thresholds; critical paths and edge cases are exercised |
| **Security Airbag** | Vulnerability scanning | No new vulnerabilities introduced; existing issues not worsened |
| **Lint Clean** | Style and format | All linter and formatter rules pass |
| **Doc Sync** | Documentation accuracy | Code changes have corresponding documentation updates |

### Event Type Definitions

#### Interface Lock

**What it measures:** Stability of public API contracts.

**Thresholds:**
- Zero breaking changes to exported types/functions without explicit `@breaking` annotation
- Semantic versioning compliance (breaking = major bump)
- Contract files unchanged or updated with changelog

**Backing agents:** `interface-designer` (Flow 2), `contract-enforcer` (Flow 5)

---

#### Complexity Cap

**What it measures:** Code maintainability via complexity metrics.

**Thresholds:**
- Cyclomatic complexity per function: <= 10 (warning at 8)
- Cognitive complexity per function: <= 15 (warning at 12)
- File-level complexity: <= 200 (sum of function complexities)

**Backing agents:** `code-critic` (Flow 3), `gate-fixer` (Flow 5)

---

#### Test Depth

**What it measures:** Confidence in test coverage and edge case handling.

**Thresholds:**
- Line coverage: >= 80% (warning at 70%)
- Branch coverage: >= 70% (warning at 60%)
- Critical path coverage: 100% (paths marked `@critical` must have tests)
- Mutation score: >= 60% (when mutation testing enabled)

**Backing agents:** `test-author` (Flow 3), `test-critic` (Flow 3), `coverage-enforcer` (Flow 5)

---

#### Security Airbag

**What it measures:** Security posture before and after change.

**Thresholds:**
- New HIGH/CRITICAL vulnerabilities: 0
- New MEDIUM vulnerabilities: <= 2 (warning at 1)
- Secrets detection: 0 new secrets in diff
- Dependency audit: no new vulnerable dependencies

**Backing agents:** `risk-analyst` (Flow 1), `security-scanner` (Flow 5)

---

#### Lint Clean

**What it measures:** Adherence to style and format rules.

**Thresholds:**
- Linter errors: 0
- Formatter drift: 0 files (all files match formatted output)
- Type errors: 0 (when type checking enabled)

**Backing agents:** `auto-linter` skill, `gate-fixer` (Flow 5)

---

#### Doc Sync

**What it measures:** Documentation freshness relative to code changes.

**Thresholds:**
- Public API changes: corresponding doc updates required
- README accuracy: no stale installation/usage instructions
- Changelog updated for user-facing changes

**Backing agents:** `doc-writer` (Flow 3), `artifact-auditor` (Flow 7)

---

## 2. Observed vs Prevented

Each quality event can be in one of two states: **Observed** (positive evidence it was maintained) or **Prevented** (evidence that drift was stopped before merge).

### State Definitions

| State | Definition | Signal |
|-------|------------|--------|
| **Observed** | Quality was present and measured | Receipt shows passing check |
| **Prevented** | Quality drift was detected and fixed | Receipt shows failure then fix |
| **Not Measured** | Check was not run or not applicable | No receipt present |

### Per-Event Examples

#### Interface Lock

| State | Evidence |
|-------|----------|
| **Observed** | `contract_check.json` shows `status: passed`, no breaking changes detected |
| **Prevented** | `contract_check.json` shows `status: failed` with breaking change, `gate_fix_receipt.json` shows rollback or annotation added |

---

#### Complexity Cap

| State | Evidence |
|-------|----------|
| **Observed** | `complexity_report.json` shows all functions below threshold |
| **Prevented** | `code_critique.md` flagged complexity, `code_implementer` refactored, final `complexity_report.json` passes |

---

#### Test Depth

| State | Evidence |
|-------|----------|
| **Observed** | `test_summary.json` shows coverage >= thresholds, `coverage_report.json` confirms |
| **Prevented** | `test_critique.md` flagged missing tests, `test_author` added tests, final coverage passes |

---

#### Security Airbag

| State | Evidence |
|-------|----------|
| **Observed** | `security_scan.json` shows 0 new vulnerabilities |
| **Prevented** | `security_scan.json` initial shows vulnerability, `gate_fixer` or `code_implementer` fixed, rescan passes |

---

#### Lint Clean

| State | Evidence |
|-------|----------|
| **Observed** | `lint_report.json` shows 0 errors, 0 formatter drift |
| **Prevented** | `auto-linter` skill fixed issues, final `lint_report.json` passes |

---

#### Doc Sync

| State | Evidence |
|-------|----------|
| **Observed** | `doc_audit.json` shows all public API changes have doc updates |
| **Prevented** | `artifact_audit.md` flagged stale docs, `doc-writer` updated, final audit passes |

---

## 3. Receipt Mapping

Quality events are claims; receipts are evidence. Every event must map to a receipt file.

### Receipt Locations

All receipts follow the `RUN_BASE` structure:

```
RUN_BASE/<flow>/receipts/<step_id>-<agent_key>.json
RUN_BASE/<flow>/artifacts/<artifact_name>.<ext>
```

Where `RUN_BASE = swarm/runs/<run-id>/`.

### Event-to-Receipt Mapping

| Event Type | Primary Receipt | Secondary Receipts |
|------------|-----------------|-------------------|
| **Interface Lock** | `gate/receipts/contract-contract-enforcer.json` | `plan/artifacts/interface_contracts.md` |
| **Complexity Cap** | `build/artifacts/complexity_report.json` | `build/receipts/critique_code-code-critic.json` |
| **Test Depth** | `gate/receipts/coverage-coverage-enforcer.json` | `build/artifacts/test_summary.json`, `build/receipts/critique_tests-test-critic.json` |
| **Security Airbag** | `gate/receipts/security-security-scanner.json` | `signal/artifacts/risk_assessment.md` |
| **Lint Clean** | `gate/receipts/gate_fix-gate-fixer.json` | `build/artifacts/lint_report.json` |
| **Doc Sync** | `wisdom/artifacts/artifact_audit.md` | `build/receipts/docs-doc-writer.json` |

### Receipt Format

Receipts use the standard step receipt schema:

```json
{
  "engine": "claude-step",
  "mode": "production",
  "provider": "anthropic",
  "model": "claude-sonnet-4-20250514",
  "step_id": "security",
  "flow_key": "gate",
  "run_id": "run-20251209-102036-zjl1mf",
  "agent_key": "security-scanner",
  "started_at": "2025-12-09T10:20:36.152293+00:00Z",
  "completed_at": "2025-12-09T10:20:41.893421+00:00Z",
  "duration_ms": 5741,
  "status": "succeeded",
  "tokens": {
    "prompt": 8420,
    "completion": 1205,
    "total": 9625
  },
  "transcript_path": "llm/security-security-scanner-claude.jsonl",
  "quality_events": [
    {
      "type": "security_airbag",
      "state": "observed",
      "details": {
        "new_vulnerabilities": 0,
        "scanned_files": 42
      }
    }
  ]
}
```

### Verification Contract

To verify a quality event claim:

1. **Locate receipt:** Use event-to-receipt mapping table
2. **Check status:** Receipt `status` must be `succeeded`
3. **Read quality_events array:** Find event with matching `type`
4. **Verify state:** `observed` or `prevented` with supporting `details`

If no receipt exists or `quality_events` is empty, the event is **Not Measured**.

---

## 4. Reporting in PR Cockpit

Quality events are surfaced in the PR body via the `gh-reporter` agent.

### PR Body Format

Quality events appear in a dedicated section:

```markdown
## Quality Events

| Event | State | Evidence |
|-------|-------|----------|
| Interface Lock | Observed | [contract-enforcer receipt](./gate/receipts/contract-contract-enforcer.json) |
| Complexity Cap | Observed | [complexity report](./build/artifacts/complexity_report.json) |
| Test Depth | Prevented | [coverage-enforcer receipt](./gate/receipts/coverage-coverage-enforcer.json) (fixed from 68% to 82%) |
| Security Airbag | Observed | [security-scanner receipt](./gate/receipts/security-security-scanner.json) |
| Lint Clean | Prevented | [gate-fixer receipt](./gate/receipts/gate_fix-gate-fixer.json) |
| Doc Sync | Not Measured | No doc-writer receipt found |
```

### State Indicators

| State | Display | Meaning |
|-------|---------|---------|
| **Observed** | `Observed` | Check ran and passed |
| **Prevented** | `Prevented` | Issue found and fixed before merge |
| **Not Measured** | `Not Measured` | Check did not run or receipt missing |

### Marking Not Measured Explicitly

When a check is not applicable or not run, mark it explicitly:

```markdown
| Doc Sync | Not Measured | No public API changes in this PR |
```

Do not omit rows. All six event types must appear in the table.

### Evidence Links

Evidence links are relative paths from `RUN_BASE`:

- Receipt files: `./gate/receipts/<receipt>.json`
- Artifact files: `./build/artifacts/<artifact>.json`

For runs visible in Flow Studio, these link to the artifact viewer.

### Aggregated Summary

When multiple PRs or runs are aggregated (e.g., release notes), use counts:

```markdown
## Quality Summary (5 runs)

| Event | Observed | Prevented | Not Measured |
|-------|----------|-----------|--------------|
| Interface Lock | 5 | 0 | 0 |
| Complexity Cap | 4 | 1 | 0 |
| Test Depth | 3 | 2 | 0 |
| Security Airbag | 5 | 0 | 0 |
| Lint Clean | 2 | 3 | 0 |
| Doc Sync | 4 | 0 | 1 |
```

---

## 5. Extension Points

### Adding New Event Types

To add a new quality event type:

1. Define the event in this document (scope, thresholds, backing agents)
2. Update the agent that produces the receipt to emit `quality_events`
3. Add the event-to-receipt mapping
4. Update `gh-reporter` to include the new event in PR body

### Custom Thresholds

Thresholds can be customized per-repository via `swarm/config/quality_thresholds.yaml`:

```yaml
complexity_cap:
  cyclomatic_max: 12
  cognitive_max: 18

test_depth:
  line_coverage_min: 75
  branch_coverage_min: 65
```

### Integration with Wisdom

Flow 7 (Wisdom) aggregates quality events across runs to detect trends:

- Rising complexity over time
- Coverage decay
- Recurring lint fixes (suggests missing pre-commit hook)

See `wisdom/artifacts/quality_trends.json` for aggregated metrics.

---

## Related Documentation

- [VALIDATION_RULES.md](./VALIDATION_RULES.md) - FR-001 through FR-005 validation
- [FLOW_STUDIO.md](./FLOW_STUDIO.md) - PR cockpit visualization
- [STEPWISE_BACKENDS.md](./STEPWISE_BACKENDS.md) - Receipt file format
- [ROUTING_PROTOCOL.md](./ROUTING_PROTOCOL.md) - Observation and evidence schemas
