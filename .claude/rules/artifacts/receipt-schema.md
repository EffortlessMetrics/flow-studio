# Receipt Schema

Receipts are the proof that work happened. They are the audit trail.

## Required Fields

Every step receipt MUST include:

```json
{
  "engine": "claude-step | gemini-step",
  "mode": "stub | sdk | cli",
  "provider": "anthropic | gemini",
  "step_id": "string",
  "flow_key": "signal | plan | build | review | gate | deploy | wisdom",
  "run_id": "string",
  "agent_key": "string",
  "started_at": "ISO8601 timestamp",
  "completed_at": "ISO8601 timestamp",
  "duration_ms": "number",
  "status": "succeeded | failed",
  "tokens": {
    "prompt": "number",
    "completion": "number",
    "total": "number"
  }
}
```

## Optional Fields

```json
{
  "error": "string (if status == failed)",
  "transcript_path": "relative/path/to/llm/file.jsonl",
  "handoff_envelope_path": "relative/path/to/envelope.json",
  "routing_signal": {
    "decision": "CONTINUE | LOOP | DETOUR | ...",
    "next_step_id": "string",
    "reason": "string"
  },
  "git_sha": "string (commit at step start)",
  "git_branch": "string",
  "workspace_root": "string"
}
```

## Evidence Binding

Receipts that claim results MUST include evidence:

### Test Results
```json
{
  "tests": {
    "measured": true,
    "passed": 42,
    "failed": 0,
    "skipped": 3,
    "evidence_path": "RUN_BASE/build/test_output.log"
  }
}
```

### Code Changes
```json
{
  "changes": {
    "files_modified": 5,
    "lines_added": 120,
    "lines_removed": 45,
    "evidence_path": "RUN_BASE/build/diff_summary.md"
  }
}
```

### Security Scans
```json
{
  "security": {
    "measured": true,
    "vulnerabilities": 0,
    "evidence_path": "RUN_BASE/gate/security_scan.log"
  }
}
```

### Not Measured
```json
{
  "mutation_testing": {
    "measured": false,
    "reason": "Mutation testing not configured for this project"
  }
}
```

## File Placement

Receipts are written to:
```
RUN_BASE/<flow>/receipts/<step_id>-<agent_key>.json
```

Example:
```
swarm/runs/abc123/build/receipts/step-3-code-implementer.json
```

## Validation

`receipt_io.py` validates:
1. All required fields present
2. Status is valid enum
3. Timestamps are valid ISO8601
4. Token counts are non-negative
5. Evidence paths exist (when claimed)

## The Rule

> Receipts are the audit trail. They prove what happened.
> Claims without evidence are flagged. "Not measured" is valid.
