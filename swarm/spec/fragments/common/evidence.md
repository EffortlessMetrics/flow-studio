## Evidence Standards

Your work must leave verifiable traces. The system verifies claims forensically.

### Verifiable Traces

- **File Changes**: Use Write/Edit tools. Changes must be visible in git diff.
- **Test Results**: Run tests and capture output. Don't claim results without logs.
- **Receipts**: The handoff JSON is your proof of work. Be accurate and complete.
- **Artifacts**: Every required output must exist at the specified path.

### Status Model (VERIFIED / UNVERIFIED / CANNOT_PROCEED)

Every step ends with one of these statuses:

| Status | Meaning | When to Use |
|--------|---------|-------------|
| **VERIFIED** | Work is adequate for its purpose; requirements met | Tests pass, artifacts complete, no blocking issues |
| **UNVERIFIED** | Work attempted but issues remain | Tests fail, incomplete implementation, documented concerns |
| **PARTIAL** | Some progress made but blocked externally | Missing upstream artifacts, waiting on external system |
| **BLOCKED** | Cannot proceed due to missing inputs | Required input files do not exist (exceptional state) |

**Key Rule**: If you can read your inputs and form an opinion, you are VERIFIED or UNVERIFIED, never BLOCKED. Ambiguity uses documented assumptions, not BLOCKED status.

### Evidence Binding Rules

1. **Numeric metrics must come from canonical sources**:
   - Test counts from pytest summary output
   - Coverage percentages from coverage tool
   - Mutation scores from mutation testing tool
   - Never recalculate or infer these values

2. **Metric consistency check**:
   - If prose says "196 tests" but pytest shows "191 passed + 4 xfailed + 1 xpassed = 196 total", document the exact breakdown
   - If inconsistency found, set status UNVERIFIED with "metrics mismatch"

3. **No status upgrades without evidence**:
   - If test-critic says "REQ-004 is MVP_VERIFIED", downstream stations report that
   - If code-critic says "REQ-007 PARTIAL", reflect that without upgrade
   - Reporters and reviewers consume verdicts; they do not change them

### Receipt Structure

All receipts must include:

```json
{
  "status": "VERIFIED | UNVERIFIED | PARTIAL | BLOCKED",
  "summary": "Brief description of what was done",
  "artifacts": ["list", "of", "created", "files"],
  "can_further_iteration_help": "yes | no",
  "concerns": ["list of remaining issues if UNVERIFIED"],
  "assumptions": ["list of assumptions made if any"]
}
```

### Discrepancy Handling

Discrepancies between claims and evidence trigger review:
- Claimed "tests pass" but no test log exists
- Claimed "VERIFIED" but required outputs missing
- Metric claims that don't match tool output
- Status upgrades without supporting evidence
