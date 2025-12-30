# Demo Run: Operator's Guide

> For: Anyone running the demo for others

This guide helps you run a smooth demo of the swarm. It covers preparation, timing, talking points, and recovery from common issues.

---

## Timeline

### 15 Minutes Before

**Clone and install dependencies:**

```bash
git clone https://github.com/EffortlessMetrics/flow-studio.git
cd flow-studio
uv sync --extra dev
```

**Verify the environment is green:**

```bash
make dev-check
```

Expected output:
- `Validation: PASS`
- `Selftest: PASS`
- Exit code 0

**Populate demo artifacts:**

```bash
make demo-run
```

Expected output:
- `Copying swarm/examples/health-check/ -> swarm/runs/demo-health-check/`
- `Demo run ready at swarm/runs/demo-health-check/`

**Verify artifacts exist:**

```bash
ls swarm/runs/demo-health-check/
```

Expected output: `build  deploy  gate  plan  signal  wisdom`

---

### 5 Minutes Before

**Start Flow Studio:**

```bash
make flow-studio
```

**Open in browser:**

```
http://localhost:5000
```

**Navigate to Signal flow:**

Click "Signal" in the left sidebar to have Flow 1 ready on screen.

**Prepare terminal:**

Have a terminal window ready alongside the browser. Size it so both are visible.

**Verify demo URL works:**

```
http://localhost:5000/?run=demo-health-check&mode=operator
```

You should see the SDLC progress bar across all 7 flows (all green for the demo).

---

## During the Demo

### Section 0: Preconditions (5 min)

**Key talking points:**
- "uv provides fast, reproducible Python environments"
- "demo-run copies curated artifacts so we have real data to explore"
- "Each flow produces structured outputs in its own subdirectory"

**Commands:**
```bash
uv sync --extra dev
make demo-run
ls swarm/runs/demo-health-check/
```

---

### Section 1: Kernel and Selftest (5 min)

**Key talking points:**
- "dev-check is what CI runs on every PR"
- "kernel-smoke is fast feedback (under 500ms)"
- "Selftest has 16 steps in 3 tiers: KERNEL, GOVERNANCE, OPTIONAL"
- "KERNEL must pass; GOVERNANCE should pass; OPTIONAL is informational"

**Commands:**
```bash
make dev-check
make kernel-smoke
make selftest
```

**Common questions:**

Q: "What if selftest fails?"
A: "Run `make selftest-doctor` to diagnose. It separates harness issues from real service failures."

Q: "What's the difference between kernel and governance?"
A: "KERNEL checks fundamentals (Python lint, compile). GOVERNANCE checks swarm alignment (agent bijection, frontmatter, flow references)."

---

### Section 2: Flow Studio (10 min)

**Key talking points:**
- "The graph IS the spec. Each flow has steps, each step has agents."
- "Colors indicate role families: yellow=shaping, purple=spec, green=implementation, red=critic, blue=verification, orange=analytics"
- "Click any node to see details. The UI and the spec tell the same story."
- "Flow Studio runs on a FastAPI backend for fast, responsive visualization."

**Commands:**
```bash
make flow-studio
# Server starts at http://localhost:5000 (FastAPI-powered)
# Open: http://localhost:5000/?flow=build&run=health-check
```

**Walkthrough:**
1. Show the 7 flows in the left sidebar
2. Click Build (Flow 3) - the heaviest flow
3. Click a step node to show agents assigned
4. Click an agent node to show its role and model
5. Switch to the Artifacts tab to show what each flow produced

**Common questions:**

Q: "Can I edit flows here?"
A: "No, Flow Studio is read-only. Edit the YAML configs in `swarm/config/flows/` and run `make gen-flows`."

Q: "Why is Build the largest?"
A: "Build has the most microloops: test-author/critic, code-implementer/critic, mutator/fixer. Each loop iterates until verified."

---

### Section 3: Governance and Degradation (5 min)

**Key talking points:**
- "The validator enforces 5 functional requirements (FR-001 through FR-005)"
- "Degraded mode accepts KERNEL pass with governance warnings"
- "selftest-doctor diagnoses harness vs service issues"

**Commands:**
```bash
make validate-swarm
make selftest-degraded
make selftest-doctor
```

**Common questions:**

Q: "When would I use degraded mode?"
A: "During development when you're iterating on governance but need to keep building."

---

### Section 4: Templates (5 min)

**Key talking points:**
- "selftest-minimal gives you CI validation without the full swarm"
- "flowstudio-only gives you visualization without validation"
- "Templates are the path to adopting pieces incrementally"

**Commands:**
```bash
ls swarm/templates/
cat swarm/templates/selftest-minimal/README.md
```

---

### Section 5: Q&A / Extensions (10 min)

**Hands-on exercises to offer:**

1. **Change an agent's model:**
   ```bash
   make agents-models
   $EDITOR swarm/config/agents/test-author.yaml
   # Change model: inherit -> model: haiku
   make gen-adapters && make check-adapters && make validate-swarm
   ```

2. **Break and fix validation:**
   ```bash
   $EDITOR .claude/agents/code-critic.md
   # Change color: red -> color: blue
   make validate-swarm  # See it fail
   # Fix it back
   make validate-swarm  # See it pass
   ```

3. **Trace a requirement through all flows:**
   ```bash
   cat swarm/runs/demo-health-check/signal/requirements.md
   cat swarm/runs/demo-health-check/plan/adr_current.md
   cat swarm/runs/demo-health-check/build/build_receipt.json | jq '.requirements'
   cat swarm/runs/demo-health-check/gate/merge_decision.md
   ```

---

## If Something Goes Wrong

### Flow Studio Won't Start

```bash
# Check if port is in use
lsof -i :5000

# Try alternate port (FastAPI backend)
uv run uvicorn swarm.tools.flow_studio_fastapi:app --reload --host 127.0.0.1 --port 5050

# Fallback: show flow specs directly
cat swarm/flows/flow-build.md
```

### Selftest Fails Unexpectedly

```bash
# Diagnose
make selftest-doctor

# If KERNEL fails: fix the fundamental issue first
# If only GOVERNANCE fails: continue with degraded mode
make selftest-degraded
```

### demo-run Fails

```bash
# Verify examples exist
ls swarm/examples/health-check/

# Manual copy if needed
cp -r swarm/examples/health-check swarm/runs/demo-health-check
```

### Validation Fails

```bash
# Get JSON output for specific errors
uv run swarm/tools/validate_swarm.py --json | jq '.summary'

# See which agents have issues
uv run swarm/tools/validate_swarm.py --json | jq '.summary.agents_with_issues'
```

### Time Is Short

If you need to cut the demo short:
- Skip Section 4 (Templates)
- Shorten Section 5 (pick one hands-on task, not three)
- Focus on Flow Studio (Section 2) as the visual centerpiece

---

## Key Files Reference

| File | Purpose |
|------|---------|
| `DEMO_RUN.md` | Full narrative walkthrough (what to say, what to run, what to show) |
| `demo/DEMO_RUN_COMMANDS.jsonl` | Machine-readable command manifest (for automation or slides) |
| `docs/GETTING_STARTED.md` | Attendee handout (10-minute self-guided tour) |
| `docs/FLOW_STUDIO.md` | Flow Studio UI reference |
| `docs/SELFTEST_SYSTEM.md` | Selftest design and troubleshooting |

---

## Machine-Readable Command Manifest

All demo commands are captured in `demo/DEMO_RUN_COMMANDS.jsonl`. Each line is a JSON object with:

```json
{"section": "0.1", "command": "uv sync --extra dev", "expected": "Resolved X packages", "timing": "30s"}
```

Use this for:
- Automated validation that commands still work
- Generating slides from the command list
- Pre-caching command outputs for offline demos

---

## After the Demo

**Clean up demo artifacts:**

```bash
rm -rf swarm/runs/demo-health-check
```

**Stop Flow Studio:**

Press Ctrl+C in the terminal running `make flow-studio`.

**Point attendees to next steps:**

- `docs/GETTING_STARTED.md` - Self-guided tour
- `DEMO_RUN.md` - Full walkthrough they can follow
- `docs/WHY_DEMO_SWARM.md` - Philosophy and core ideas
- `CLAUDE.md` - Complete reference for Claude Code users
