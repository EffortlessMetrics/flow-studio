# Artifact Naming Conventions

Predictable naming enables automation. Given flow, step, and agent, you should know the path without looking it up.

## The Rule

> Names should be predictable. Given flow, step, and agent, you should know the path without looking it up.

## File Naming

### General Conventions

- Lowercase with hyphens: `work-plan.md`, not `WorkPlan.md`
- Include step ID where relevant: `step-3-code-implementer.json`
- Include agent key for agent outputs: `<step>-<agent>.<ext>`

### Examples

| Good | Bad | Why |
|------|-----|-----|
| `work-plan.md` | `WorkPlan.md` | Lowercase with hyphens |
| `step-3-code-implementer.json` | `Step3CodeImplementer.json` | Consistent separator |
| `adr-001.md` | `ADR_001.md` | Lowercase, hyphens |
| `test-output.log` | `test output.log` | No spaces |

## Directory Structure

Every run follows this canonical structure:

```
RUN_BASE/<flow>/
├── receipts/<step>-<agent>.json       # Step completion proofs
├── handoffs/<step>-<agent>.json       # State transfer envelopes
├── logs/<step>.jsonl                  # Execution logs
├── llm/<step>-<agent>-<engine>.jsonl  # LLM transcripts
├── routing/                           # Routing decisions
│   ├── decisions.jsonl                # Append-only decision log
│   └── injections/                    # Flow/node injection records
└── artifacts/                         # Flow-specific outputs
    └── <artifact-name>.<ext>
```

## Naming Patterns

### Receipts
```
<step_id>-<agent_key>.json
```
Examples:
- `step-1-requirements-author.json`
- `step-3-code-implementer.json`
- `step-5-code-critic.json`

### Handoffs
```
<step_id>-<agent_key>.json
```
Examples:
- `step-2-impact-analyzer.json`
- `step-4-test-author.json`

Draft handoffs (during work):
```
<step_id>-<agent_key>.draft.json
```

### Transcripts
```
<step_id>-<agent_key>-<engine>.jsonl
```
Examples:
- `step-3-code-implementer-claude-sdk.jsonl`
- `step-5-code-critic-gemini-cli.jsonl`

### Logs
```
<step_id>.jsonl
```
Examples:
- `step-1.jsonl`
- `step-3.jsonl`

### Routing Decisions
```
routing/decisions.jsonl                    # Append-only log
routing/injections/flow-<id>.json          # Flow injection records
routing/injections/nodes-<id>.json         # Node injection records
```

## What NOT to Include in Names

### Timestamps
```
# BAD
step-3-code-implementer-2024-01-15T10-30-00.json

# GOOD
step-3-code-implementer.json
# (timestamp is in file metadata or content)
```

### Random IDs
```
# BAD
step-3-code-implementer-a1b2c3d4.json

# GOOD
step-3-code-implementer.json
# (deterministic from flow, step, agent)
```

### Spaces or Special Characters
```
# BAD
step 3 - code implementer.json
step-3_code@implementer.json

# GOOD
step-3-code-implementer.json
```

### Version Numbers
```
# BAD
work-plan-v2.md
adr-001-final-v3.md

# GOOD
work-plan.md
adr-001.md
# (git handles versions)
```

## Artifact References

### Always Use Relative Paths from RUN_BASE
```json
{
  "evidence_path": "build/receipts/step-3-code-implementer.json"
}
```

Not:
```json
{
  "evidence_path": "C:\\Code\\swarm\\runs\\abc123\\build\\receipts\\step-3-code-implementer.json"
}
```

### Use Forward Slashes (Even on Windows)
```json
{
  "transcript_path": "build/llm/step-3-code-implementer-claude-sdk.jsonl"
}
```

Not:
```json
{
  "transcript_path": "build\\llm\\step-3-code-implementer-claude-sdk.jsonl"
}
```

### No Trailing Slashes on Directories
```json
{
  "artifacts_dir": "build/artifacts"
}
```

Not:
```json
{
  "artifacts_dir": "build/artifacts/"
}
```

## Path Resolution

Given:
- `run_id = "abc123"`
- `flow_key = "build"`
- `step_id = "step-3"`
- `agent_key = "code-implementer"`
- `engine = "claude-sdk"`

You can derive:
```
RUN_BASE = swarm/runs/abc123/
Receipt  = swarm/runs/abc123/build/receipts/step-3-code-implementer.json
Handoff  = swarm/runs/abc123/build/handoffs/step-3-code-implementer.json
Transcript = swarm/runs/abc123/build/llm/step-3-code-implementer-claude-sdk.jsonl
```

No lookup required. The path is deterministic.

## Enforcement

Naming conventions are validated by:
- `validate_swarm.py` FR-005 (RUN_BASE path hygiene)
- `receipt_io.py` (receipt path validation)
- Runtime kernel (artifact placement)

## The Economics

Predictable naming enables:
- Automated tooling without path discovery
- Glob patterns that work: `*/receipts/*.json`
- Debugging without searching: "I know where it is"
- Resume logic without indexes: "Last receipt for step-3 is..."

Random or timestamped names require indexes, discovery, and search.
Deterministic names are self-describing.
