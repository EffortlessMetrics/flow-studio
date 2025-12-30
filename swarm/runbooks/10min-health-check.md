# Runbook: 10-Minute Health Check

**Branch**: N/A (validation runbook, no implementation)

## Goal

Verify the swarm is healthy and Flow Studio works correctly in under 10 minutes. This is the canonical "prove it works" checklist for new environments, post-clone validation, and demo preparation.

## Prerequisites

- Python 3.11+
- Node.js 18+ (for TypeScript compilation)
- `uv` package manager installed
- Port 5000 available (or specify alternate)

## Constraints

- No code changes
- Read-only validation
- All steps must pass for a healthy swarm

## Invariants (Don't Break These)

This runbook does not modify the repo. If any step fails, the swarm has a pre-existing issue.

---

## Technical Steps

### Step 1: Install dependencies (1 min)

```bash
uv sync --frozen
```

**Verify**: Command exits with code 0, no errors.

### Step 2: Run full validation (2 min)

```bash
make dev-check
```

**Verify**: All checks pass. Look for:

- `✓ Selftest passed (16/16 steps)`
- `✓ Adapters match config`
- `✓ TypeScript compiles`

If this fails, run `make selftest-doctor` for diagnosis.

### Step 3: Populate demo run (30 sec)

```bash
make demo-run
```

**Verify**: Output shows:

```
✓ Demo run created at swarm/runs/demo-health-check/
```

### Step 4: Start Flow Studio (1 min)

```bash
make flow-studio
```

**Verify**: Server starts with message:

```
Running on http://127.0.0.1:5000
```

Leave this terminal running.

### Step 5: Verify Flow Studio loads (2 min)

Open in browser:

```
http://localhost:5000/?run=demo-health-check&mode=operator
```

**Verify checklist**:

- [ ] Left sidebar shows 7 flows (Signal, Plan, Build, Review, Gate, Deploy, Wisdom)
- [ ] SDLC bar at top shows all flows with status
- [ ] Clicking "Build" in sidebar loads the flow graph
- [ ] Clicking an agent node opens the details panel

### Step 6: Verify governance view (2 min)

Open in browser:

```
http://localhost:5000/?run=demo-health-check&tab=validation
```

**Verify checklist**:

- [ ] Validation tab loads without errors
- [ ] FR badges (FR-001 through FR-005) are visible
- [ ] No critical issues flagged

### Step 7: Verify API endpoint (1 min)

```bash
curl -s http://localhost:5000/api/health | jq .
```

**Verify**: Response is `{"status": "ok"}` or similar healthy status.

### Step 8 (Optional): Verify stepwise execution (2 min)

If you want to validate stepwise execution specifically:

```bash
make stepwise-sdlc-stub
```

**Verify**: Output shows run creation and 7 flows complete.

Then open Flow Studio with the stepwise run:

```
http://localhost:5000/?run=stepwise-stub&mode=operator
```

**Checklist**:

- [ ] Events timeline shows step-level boundaries
- [ ] Clicking a step shows teaching notes in inspector
- [ ] Receipts exist in `swarm/runs/stepwise-stub/<flow>/receipts/`

For a full stepwise walkthrough, see [swarm/runbooks/stepwise-fastpath.md](./stepwise-fastpath.md).

---

## Success Criteria

All of these must be true:

1. `make dev-check` passes (all 16 selftest steps green)
2. `make demo-run` creates `swarm/runs/demo-health-check/`
3. Flow Studio starts on port 5000
4. Browser can load `/?run=demo-health-check&mode=operator`
5. SDLC bar shows 7 flows
6. Validation tab loads without errors
7. `/api/health` returns healthy status

If all pass: **Swarm is healthy.**

---

## Troubleshooting Quick Reference

| Symptom | Likely Cause | Fix |
|---------|--------------|-----|
| `uv sync` fails | Missing uv | `pip install uv` |
| `dev-check` fails | Swarm validation issue | `make selftest-doctor` |
| Port 5000 in use | Another process | `lsof -i :5000` then kill or use `--port 5001` |
| Flow Studio blank | No runs populated | `make demo-run` |
| Graph not rendering | Missing flow config | `make gen-flows` |
| TypeScript errors | Build needed | `make ts-build` |

For detailed troubleshooting, see [docs/CI_TROUBLESHOOTING.md](../../docs/CI_TROUBLESHOOTING.md).

---

## Dependencies

- None (standalone validation runbook)

## Files to Modify

- None (read-only runbook)

## Files to Create

- None

---

## Related Resources

- [docs/GETTING_STARTED.md](../../docs/GETTING_STARTED.md) — Educational walkthrough (explains concepts)
- [docs/FLOW_STUDIO.md](../../docs/FLOW_STUDIO.md) — Flow Studio reference
- [swarm/SELFTEST_SYSTEM.md](../SELFTEST_SYSTEM.md) — Selftest architecture
