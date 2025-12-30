# Output Schema Header

Standard output format for all step receipts. Every step must produce output conforming to this schema.

## Required Fields

### Status Field

```yaml
status: VERIFIED | UNVERIFIED | BLOCKED
```

- **VERIFIED**: Step completed successfully, all assertions passed
- **UNVERIFIED**: Step completed but with concerns or assumptions documented
- **BLOCKED**: Step cannot proceed due to missing inputs (exceptional, see below)

**BLOCKED is exceptional**: Use only when input artifacts don't exist. Ambiguity should result in documented assumptions + UNVERIFIED, not BLOCKED.

### Evidence Structure

```yaml
evidence:
  inputs_consumed:
    - path: "path/to/input"
      hash: "sha256:abc123..."
      summary: "Brief description of what was read"

  operations_performed:
    - operation: "Description of what was done"
      result: "pass | fail | skip"
      details: "Additional context"

  outputs_produced:
    - path: "path/to/output"
      hash: "sha256:def456..."
      summary: "Brief description of what was written"

  assertions:
    - claim: "What was verified"
      evidence: "How it was verified"
      result: "pass | fail"
```

### Routing Signal Format

```yaml
routing_signal:
  decision: CONTINUE | DETOUR | INJECT_FLOW | INJECT_NODES | EXTEND_GRAPH
  confidence: 0.0-1.0

  # For CONTINUE
  next_step: "step-id"

  # For DETOUR
  sidequest:
    type: "sidequest-type"
    reason: "Why detour is needed"
    steps: ["step-1", "step-2"]

  # For INJECT_FLOW
  inject_flow:
    flow_id: "flow-to-inject"
    reason: "Why flow injection is needed"
    resume_at: "step-to-resume-after-injection"

  # For INJECT_NODES
  inject_nodes:
    nodes:
      - id: "custom-node-1"
        type: "node-type"
        config: {}
    reason: "Why custom nodes are needed"

  # For EXTEND_GRAPH
  extend_graph:
    proposal_id: "proposal-uuid"
    summary: "What graph extension is proposed"
```

## Assumptions Documentation

When making assumptions, document explicitly:

```yaml
assumptions:
  - assumption: "What was assumed"
    reason: "Why this assumption was made"
    impact_if_wrong: "What would change if assumption is incorrect"
    confidence: 0.0-1.0
```

## Timestamp and Metadata

```yaml
metadata:
  step_id: "step-identifier"
  flow_id: "flow-identifier"
  run_id: "run-uuid"
  timestamp: "ISO-8601 timestamp"
  duration_ms: 1234
  agent: "agent-name"
  model: "model-identifier"
```
