# Pre-Demo Checklist

> For: Anyone preparing to demonstrate the demo swarm or present Flow Studio.

Quick checklist to ensure the swarm is ready for demonstration.

---

## 5-Minute Quick Check

**Fastest path:** `make demo-swarm` does all of this in one command.

```bash
# Or step by step:

# 1. Clean up stale runs (if any)
make runs-prune-dry          # Preview - check for surprises
make runs-prune              # Apply cleanup

# 2. Ensure golden example exists
make stepwise-sdlc-stub      # Create/refresh golden SDLC run

# 3. Start Flow Studio
make flow-studio             # http://localhost:5000

# 4. Verify health
make kernel-smoke            # Fast sanity check (~400ms)
```

---

## Full Pre-Demo Preparation (10 min)

### Step 1: Environment Check

```bash
uv sync --extra dev          # Ensure dependencies
make dev-check               # Full validation
```

Expected: All checks pass.

### Step 2: Clean Up Runs

```bash
make runs-list               # Check run count and age
make runs-prune-dry          # Preview what would be deleted
make runs-prune              # Apply retention policy
```

**Why**: Too many runs slow Flow Studio. Keep under 300 runs.

### Step 3: Ensure Golden Runs Exist

```bash
# Stub mode (no LLM calls, fast)
make stepwise-sdlc-stub

# Or with real execution (requires credentials)
# SWARM_CLAUDE_STEP_ENGINE_MODE=sdk make stepwise-sdlc-claude-sdk
```

### Step 4: Start Flow Studio

```bash
make flow-studio
```

Open: http://localhost:5000/?run=stepwise-sdlc-claude&mode=operator

### Step 5: Verify Key Views

| URL | What to Check |
|-----|---------------|
| `/?run=demo-health-check&mode=operator` | SDLC bar shows all flows green |
| `/?flow=build&view=agents` | Build flow graph renders correctly |
| `/?tab=validation` | Governance badge shows "All Clear" |

### Step 6: (Optional) Generate Wisdom Report

```bash
make wisdom-report           # Cross-run analytics
```

---

## Troubleshooting During Demo

| Symptom | Quick Fix |
|---------|-----------|
| Flow Studio slow | `make runs-prune && make flow-studio` |
| No runs visible | `make stepwise-sdlc-stub` |
| Graph empty | `make gen-flows && make flow-studio` |
| Validation errors | `make validate-swarm` to see details |

---

## Demo URLs for Slides

Bookmark these for quick navigation:

```
# Baseline view
http://localhost:5000/?run=demo-health-check&mode=operator

# Build flow deep dive
http://localhost:5000/?run=demo-health-check&flow=build&view=agents

# Run comparison
http://localhost:5000/?run=demo-health-check&compare=health-check-risky-deploy

# Governance view
http://localhost:5000/?tab=validation
```

---

## What to Highlight in Demo

1. **SDLC Bar**: 7 flows from Signal to Wisdom
2. **Agent Colors**: Green=implementation, Red=critic, Blue=verification
3. **Microloops**: Author ⇄ Critic pairs in Build flow
4. **Receipts**: Click any step to see execution metadata
5. **Governance**: Selftest validates everything before merge

---

## See Also

- [FLOW_STUDIO.md](./FLOW_STUDIO.md) — Full Flow Studio documentation
- [GETTING_STARTED.md](./GETTING_STARTED.md) — Quick start guide
- [DEMO_RUN.md](../DEMO_RUN.md) — Narrative walkthrough
- [runs-retention.md](../swarm/runbooks/runs-retention.md) — Run cleanup reference
