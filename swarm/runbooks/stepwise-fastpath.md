# Runbook: Stepwise Execution Quick-Start Fastpath

**Branch**: N/A (validation runbook, no implementation)

## TL;DR (30 seconds)

```bash
make stepwise-sdlc-stub                    # Zero-cost demo run
make flow-studio                           # Start visualization
# Open: http://localhost:5000/?run=stepwise-stub&mode=operator
```

---

## Goal

Enable developers to run their first stepwise demo in under 5 minutes, understand which mode to use, and know where to find detailed docs.

## Prerequisites

- Python 3.11+
- `uv` package manager installed
- Port 5000 available (for Flow Studio)
- **No API keys required** for stub mode

## Constraints

- Focuses on stub mode (zero cost, fastest)
- No API keys required for the fastpath
- Happy path only—troubleshooting covered elsewhere

## Invariants (Don't Break These)

- Stub mode must produce valid transcripts and receipts
- Events timeline must be populated
- Flow Studio must load the run without errors

---

## Technical Steps

### Step 1: Verify prerequisites (30 sec)

```bash
uv sync --frozen
make kernel-smoke  # Quick health check
```

**Verify**: Both commands succeed.

### Step 2: Run stepwise demo (30 sec)

```bash
make stepwise-sdlc-stub
```

This runs a full 7-flow SDLC in stub mode (no LLM calls, instant completion).

**Verify**: Output shows run creation and flow completion messages.

### Step 3: Start Flow Studio (30 sec)

```bash
make flow-studio
```

**Verify**: Server starts at `http://127.0.0.1:5000`

### Step 4: Explore the stepwise run (3 min)

Open your browser to:

```
http://localhost:5000/?run=stepwise-stub&mode=operator
```

**Checklist**:

- [ ] SDLC bar shows all 7 flows completed
- [ ] Click "Build" → see step nodes in the graph
- [ ] Click a step node → inspector shows teaching notes (inputs, outputs, emphasizes, constraints)
- [ ] Click "Run Detail" → see events timeline with step boundaries
- [ ] Explore `signal/` → `plan/` → `build/` flows to see the progression

### Step 5: Inspect artifacts (1 min)

```bash
# View a transcript (LLM conversation log)
cat swarm/runs/stepwise-stub/signal/llm/normalize-signal-normalizer-claude.jsonl

# View a receipt (execution metadata)
cat swarm/runs/stepwise-stub/signal/receipts/normalize-signal-normalizer.json | jq .
```

**Key receipt fields**:
- `engine`: Which engine executed (gemini-step, claude-step)
- `mode`: stub, sdk, or cli
- `duration_ms`: Execution time
- `status`: succeeded, failed, skipped

---

## Decision Tree: Which Mode Should I Use?

| Your Situation | Recommended Surface | Notes |
|----------------|---------------------|-------|
| Testing flows, no LLM calls | **stub** mode | `make stepwise-sdlc-stub` |
| Building agents locally (Claude Max/Team) | **Agent SDK** (TS/Python) | No API key needed—uses Claude login |
| Shell debugging / non-Claude providers | **CLI** mode | `make stepwise-sdlc-claude-cli` |
| Server-side / CI / multi-tenant | **HTTP API** | `ANTHROPIC_API_KEY` required |

> **Key insight**: The Agent SDK is the primary programmable surface for Claude users.
> CLI mode is for debugging and bridging to other providers (Gemini CLI, etc.).

---

## Three Personas

### Persona 1: CI / Demo (Zero cost)

- Uses stub mode
- No API calls, instant execution
- Perfect for testing, CI, and demos

```bash
make stepwise-sdlc-stub
```

### Persona 2: Agent SDK (Primary for local dev)

> **The Agent SDK is "headless Claude Code"**—if Claude Code works on your machine,
> the Agent SDK works too. No separate API billing account required.

- Uses TypeScript or Python Agent SDK
- Reuses your Claude subscription (Max/Team/Enterprise)
- Ideal for building agents and extending this harness

```bash
# TypeScript: npm install @anthropic-ai/claude-agent-sdk
# Python: pip install claude-code-sdk
# Then use the SDK in your own project to call stepwise flows
```

**CLI fallback:** If you prefer shell integration or debugging, use CLI mode:
```bash
make stepwise-sdlc-claude-cli   # Uses claude --output-format stream-json
```

### Persona 3: API User (Server-side / Multi-tenant)

- Uses HTTP SDK mode
- Requires `ANTHROPIC_API_KEY` environment variable
- For CI, batch runs, and production deployments

```bash
export ANTHROPIC_API_KEY=sk-ant-...
make stepwise-sdlc-claude-sdk
```

---

## Success Criteria

All of these must be true:

1. `make stepwise-sdlc-stub` completes without errors
2. `swarm/runs/stepwise-stub/` contains artifacts for all 7 flows
3. Flow Studio loads the run at `/?run=stepwise-stub&mode=operator`
4. Events timeline shows 50+ events with step boundaries
5. Step details panel shows teaching notes (inputs/outputs/emphasizes/constraints)

If all pass: **Stepwise execution is working.**

---

## Troubleshooting Quick Reference

| Symptom | Likely Cause | Fix |
|---------|--------------|-----|
| No run directory created | Run didn't execute | Check command output for errors |
| Transcripts empty | Using stub mode | Expected for stub—switch to cli/sdk for real output |
| Flow Studio shows "No runs" | Wrong run ID | Check `ls swarm/runs/` for actual run name |
| Step shows "skipped" | Missing previous step outputs | Run full SDLC, not single flow |
| API key error | SDK mode without key | Use cli mode or set `ANTHROPIC_API_KEY` |
| Flow Studio logs "Failed to parse summary" | Corrupt runs in `swarm/runs/` | Run `make runs-quarantine` ([see runbook](./runs-retention.md)) |
| Flow Studio slow to load | Too many runs accumulated | Run `make runs-prune` ([see runbook](./runs-retention.md)) |

---

## Next Steps

- **For detailed backend reference** → [STEPWISE_BACKENDS.md](../../docs/STEPWISE_BACKENDS.md)
- **For Anthropic patterns** → [LONG_RUNNING_HARNESSES.md](../../docs/LONG_RUNNING_HARNESSES.md)
- **For troubleshooting** → [CI_TROUBLESHOOTING.md](../../docs/CI_TROUBLESHOOTING.md)
- **For full validation** → [10min-health-check.md](./10min-health-check.md)

---

## Related Resources

- [STEPWISE_BACKENDS.md](../../docs/STEPWISE_BACKENDS.md) — Complete stepwise reference
- [STEPWISE_BACKENDS.md#contracts](../../docs/STEPWISE_BACKENDS.md#contracts-proof-not-promise) — Contract verification proof
- [LONG_RUNNING_HARNESSES.md](../../docs/LONG_RUNNING_HARNESSES.md) — Anthropic pattern mapping
- [FLOW_STUDIO.md](../../docs/FLOW_STUDIO.md) — Flow Studio UI reference
- [runs-retention.md](./runs-retention.md) — Runs lifecycle, GC, and retention policy
- [stepwise-sdlc-claude/](../examples/stepwise-sdlc-claude/) — Complete 7-flow golden example
