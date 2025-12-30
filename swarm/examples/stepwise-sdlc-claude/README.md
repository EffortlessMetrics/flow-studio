# Stepwise Full SDLC Example (Claude)

Golden example of complete stepwise SDLC execution through all 7 flows.

## Flows Included

- **Signal** (Flow 1): Requirements microloop
- **Plan** (Flow 2): Architecture design
- **Build** (Flow 3): Implementation with test/code microloops
- **Review** (Flow 4): Draft PR and feedback harvesting
- **Gate** (Flow 5): Pre-merge verification
- **Deploy** (Flow 6): Artifact deployment and verification
- **Wisdom** (Flow 7): Learning synthesis and feedback loop

## Backend Configuration

- **Backend**: `claude-step-orchestrator`
- **Engine**: `ClaudeStepEngine`
- **Mode**: `stub` (no API calls)
- **Provider**: `anthropic`

## Directory Structure

```
stepwise-sdlc-claude/
├── spec.json           # RunSpec with all 7 flow_keys
├── meta.json           # RunSummary with final status
├── events.jsonl        # Complete event stream (~350 events)
├── signal/             # Flow 1 artifacts
├── plan/               # Flow 2 artifacts
├── build/              # Flow 3 artifacts
├── gate/               # Flow 4 artifacts
├── deploy/             # Flow 5 artifacts
└── wisdom/             # Flow 6 artifacts
    ├── llm/            # 6 transcripts (audit, regression, history, learnings, feedback, wisdom_report)
    └── receipts/       # 6 receipts with execution metadata
```

## Key Observations

1. **Complete SDLC**: All 7 flows executed in sequence
2. **Wisdom Flow**: Closes the feedback loop by analyzing all previous flow artifacts
3. **Teaching Notes**: All steps in Deploy and Wisdom now have structured teaching_notes
4. **Linear Routing**: Deploy and Wisdom use linear routing (no microloops)

## Total Step Count

| Flow    | Steps | Notes |
|---------|-------|-------|
| Signal  | 6     | Includes requirements microloop |
| Plan    | 9     | Linear design steps |
| Build   | 12    | Includes test/code microloops |
| Gate    | 6     | Linear verification |
| Deploy  | 5     | Linear deployment |
| Wisdom  | 6     | Linear analysis |
| **Total** | **44** | Full SDLC |

## How to Regenerate

```bash
SWARM_CLAUDE_STEP_ENGINE_MODE=stub uv run swarm/tools/demo_stepwise_run.py \
  --backend claude-step-orchestrator \
  --mode stub \
  --flows signal,plan,build,gate,deploy,wisdom
```

## Related Examples

- `stepwise-deploy-claude/`: SDLC through Deploy (without Wisdom)
- `stepwise-gate-claude/`: SDLC through Gate only
- `stepwise-build-claude/`: SDLC through Build only
