# Truth Hierarchy

The system distinguishes between LLM claims and ground truth using an explicit hierarchy.
When sources conflict, higher levels override lower levels.

## The Stack (Highest to Lowest)

### Level 1: Physics
- Exit codes, file hashes, git status, pytest output
- **Source**: OS, runtime, tooling
- **Override**: Nothing overrides physics

### Level 2: Receipts
- Captured outputs of physics (logs, counts, diffs, scan results)
- **Source**: `receipt_io.py`, forensic scanners
- **Override**: Only contradicted by re-running the command

### Level 3: Intent
- BDD scenarios, ADRs, contracts, teaching notes
- **Source**: Human-authored specifications
- **Override**: Physics and receipts showing spec doesn't match reality

### Level 4: Generated Artifacts
- Source code, test files, documentation
- **Source**: Agent work output
- **Override**: Anything above

### Level 5: Narrative
- Chat explanations, agent claims, prose descriptions
- **Source**: LLM output during work phase
- **Override**: Everything above

## Enforcement

**Routing decisions consult levels 1-3. They MUST NOT depend on level 5.**

Example violations:
- "Tests passed" claim without pytest output → invalid
- "Security scan clean" without scan log → invalid
- "All requirements met" without evidence pointers → invalid

## The Rule

> If an agent claims something, it must cite evidence from levels 1-2.
> "Not measured" is valid. False certainty is not.

## Evidence Binding Pattern

Every claim in a receipt or handoff envelope should include:
- **What was measured**: The specific command or check
- **Result**: The output (or path to output file)
- **Status**: PASS, FAIL, or NOT_MEASURED

```json
{
  "tests": {
    "measured": true,
    "command": "pytest tests/ -v",
    "passed": 42,
    "failed": 0,
    "evidence": "RUN_BASE/build/test_output.log"
  },
  "security_scan": {
    "measured": false,
    "reason": "No security scanner configured"
  }
}
```
