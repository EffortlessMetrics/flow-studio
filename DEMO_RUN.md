# Demo Run

> **Machine-readable manifest:** See [`demo/DEMO_RUN_COMMANDS.jsonl`](./demo/DEMO_RUN_COMMANDS.jsonl)
> for all commands with timings. Use this for automated validation or slide generation.

This is a presenter-friendly demo script for showing the swarm in action.
Each section follows a consistent structure with spoken narrative, commands
to run, and expected output.

---

## 0. Preconditions

Before starting the demo, ensure the environment is ready.

### Step 0.1: Install Dependencies

**You say:** "First, let's make sure all dependencies are installed. This uses uv for fast, reproducible Python environments."

**You run:**
```bash
uv sync --extra dev
```

**You show:**
- `Resolved X packages`
- `Installed X packages` (or `Audited X packages` if already installed)

### Step 0.2: Populate the Demo Run

**You say:** "Now we populate a complete demo run. This copies curated example artifacts from all 7 flows into the runs directory."

**You run:**
```bash
make demo-run
```

**You show:**
- `Copying swarm/examples/health-check/ -> swarm/runs/demo-health-check/`
- `Demo run ready at swarm/runs/demo-health-check/`

### Step 0.3: Verify the Demo Artifacts Exist

**You say:** "Let's confirm the artifacts are in place. Each flow has its own subdirectory with structured outputs."

**You run:**
```bash
ls swarm/runs/demo-health-check/
```

**You show:**
- `build  deploy  gate  plan  signal  wisdom`

---

## 1. Kernel and Selftest

This section demonstrates the layered validation system. The kernel is the
fast, critical path; selftest covers full governance.

### Step 1.1: Run the Full Dev Check

**You say:** "The dev-check target runs all validation in one command. This is what CI runs on every PR."

**You run:**
```bash
make dev-check
```

**You show:**
- `Validation: PASS`
- `Selftest: PASS`
- Exit code 0

### Step 1.2: Run Kernel Smoke Test

**You say:** "For fast feedback, kernel-smoke runs just the critical checks in under a second. This catches fundamental breakage without waiting for full governance."

**You run:**
```bash
make kernel-smoke
```

**You show:**
- `KERNEL: PASS`
- `3 steps completed`
- Timing under 500ms

### Step 1.3: Run Full Selftest

**You say:** "The full selftest runs all 16 steps. This is the complete validation suite with KERNEL, GOVERNANCE, and OPTIONAL tiers."

**You run:**
```bash
make selftest
```

**You show:**
- `KERNEL: PASS (3/3)`
- `GOVERNANCE: PASS (6/6)`
- `OPTIONAL: PASS (1/1)`
- `Overall: PASS`

### If Selftest Fails Unexpectedly

**You say:** "This is exactly what selftest is for — catching drift before it reaches production."

**You run:**
```bash
make selftest-doctor
```

**You show:**
- Diagnostic output showing HARNESS_ISSUE vs SERVICE_ISSUE
- If only GOVERNANCE failing: "We can continue in degraded mode"
- If KERNEL failing: "This blocks everything — let's fix the fundamental issue first"

**Recovery path:**
- KERNEL failure: Fix the lint/compile/core issue before continuing
- GOVERNANCE failure: Run `make selftest-degraded` to continue the demo
- If time is short: "Let's park this and show the flow architecture instead"

### Step 1.4: Check Selftest JSON Output

**You say:** "Selftest produces structured JSON for tooling integration. Let's look at the summary."

**You run:**
```bash
uv run swarm/tools/selftest.py --json-v2 | jq .summary
```

**You show:**
- `"status": "PASS"`
- `"kernel_pass": true`
- `"governance_pass": true`
- Step counts for each tier

---

## 2. Flow Studio

Flow Studio is a local web UI for visualizing the 7 SDLC flows as node
graphs.

### Step 2.1: Start Flow Studio

**You say:** "Flow Studio visualizes the flow architecture using FastAPI. Let's start the server."

**You run:**
```bash
make flow-studio
```

**You show:**
- `Starting Flow Studio (FastAPI)...`
- Server starts at `http://localhost:5000` and remains running
- Uvicorn output: `Application startup complete`

### If Flow Studio Doesn't Start

**You say:** "Port conflict or missing dependency — let's diagnose."

**You run:**
```bash
# Check if port is in use
lsof -i :5000

# Try alternate port (FastAPI backend)
uv run uvicorn swarm.tools.flow_studio_fastapi:app --reload --host 127.0.0.1 --port 5050

# Or verify the FastAPI backend works without the UI
uv run pytest tests/test_flow_studio_fastapi_smoke.py -q
```

**You show:**
- If port conflict: "Another process is using 5000, trying 5050"
- If API smoke passes: "The FastAPI backend works; UI issue is cosmetic for this demo"

**Recovery path:**
- Use port 5050: Update browser URL to http://localhost:5050
- Skip UI: Show flow specs directly with `cat swarm/flows/flow-build.md`

### Step 2.2: Open the Build Flow

**You say:** "Open the browser and navigate to the Build flow. You'll see the step sequence with agent assignments."

**You run:**
```
Open: http://localhost:5000/?flow=build&run=demo-health-check
```

**You show:**
- Left sidebar: 7 flows (Signal, Plan, Build, Review, Gate, Deploy, Wisdom)
- Center: Node graph showing steps (teal) connected to agents (colored by role)
- Right panel: Details on selected node

### Step 2.3: Explore a Step Node

**You say:** "Click on a step node to see its role and which agents handle it. The graph and the spec tell the same story."

**You run:**
```
Click the 'implement' step node in the center graph
```

**You show:**
- Step ID: `implement`
- Role: Implementation of code changes
- Agents: `code-implementer`, `code-critic`

### Step 2.4: View Artifacts Tab

**You say:** "Switch to the Run tab to see which artifacts each step produces. This bridges the spec to actual outputs."

**You run:**
```
Open: http://localhost:5000/?flow=build&run=demo-health-check&tab=run
```

**You show:**
- Artifact status indicators (present/missing)
- Links to actual files in `swarm/runs/demo-health-check/build/`

### Step 2.5: Navigate Across Flows

**You say:** "Use the left sidebar or keyboard shortcuts to navigate between flows. Each flow shows its own step sequence and agents."

**You run:**
```
Press '4' or click 'Gate' in the sidebar
```

**You show:**
- Gate flow graph with audit, verify, and decide steps
- Different agent colors (blue for verification, orange for analytics)

---

## 3. Governance and Degradation

This section shows how the swarm handles partial failures gracefully.

### Step 3.1: Validate the Swarm

**You say:** "The validator checks all agent definitions, flow references, and frontmatter. This enforces structural integrity."

**You run:**
```bash
make validate-swarm
```

**You show:**
- `FR-001: PASS` (bijection)
- `FR-002: PASS` (frontmatter)
- `FR-003: PASS` (flow references)
- `Validation: PASS`

### Step 3.2: Run Degraded Mode

**You say:** "Degraded mode accepts KERNEL pass with governance warnings. This is useful when some checks are known-failing during development."

**You run:**
```bash
make selftest-degraded
```

**You show:**
- `KERNEL: PASS`
- `GOVERNANCE: OK (degraded mode)`
- Overall status indicates degraded acceptance

### Step 3.3: Run Selftest Doctor

**You say:** "When selftest fails, the doctor diagnoses whether it's a harness issue or a real service failure. This separates infrastructure problems from code problems."

**You run:**
```bash
make selftest-doctor
```

**You show:**
- Diagnostic output separating HARNESS_ISSUE from SERVICE_ISSUE
- Recommendations for fixing each type of failure

### Step 3.4: View JSON Validation Output

**You say:** "The validator also produces JSON for dashboard integration. Let's check the summary."

**You run:**
```bash
uv run swarm/tools/validate_swarm.py --json | jq '.summary'
```

**You show:**
- `"status": "PASS"`
- `"total_checks": N`
- `"passed": N`
- `"failed": 0`

---

## 4. Templates (selftest-minimal, flowstudio-only)

Templates provide quick-start configurations for different use cases.

### Step 4.1: List Available Templates

**You say:** "Templates are pre-configured setups for common scenarios. Let's see what's available."

**You run:**
```bash
ls templates/
```

**You show:**
- `selftest-minimal/`
- `flowstudio-only/`
- Template README files

### Step 4.2: Explore selftest-minimal

**You say:** "The selftest-minimal template provides just the kernel checks with no external dependencies. Good for CI bootstrapping."

**You run:**
```bash
cat templates/selftest-minimal/README.md
```

**You show:**
- Template description
- Included components (kernel checks only)
- Usage instructions

### If Template Bootstrap Fails

**You say:** "The template system is how you package this for your own repos."

**You run:**
```bash
# Check if templates directory exists
ls -la templates/

# Manual verification that template contents are valid
cat templates/selftest-minimal/README.md
```

**You show:**
- Template structure exists
- Config file is valid and readable

**Recovery path:**
- If templates missing: "We can still show the pattern in the demo repo itself"
- Show the source: `cat swarm/tools/bootstrap_selftest_minimal.py`

### Step 4.3: Explore flowstudio-only

**You say:** "The flowstudio-only template includes just the visualization layer. Useful for exploring flow architecture without running validation."

**You run:**
```bash
cat templates/flowstudio-only/README.md
```

**You show:**
- Template description
- Included components (Flow Studio + config)
- Usage instructions

---

## 5. Q&A / Extensions

This section provides hands-on exercises and extension points.

### Hands-On Task: Change an Agent's Model

**You say:** "Let's see how config-driven agents work. We'll change an agent's model and verify the change propagates correctly."

**You run:**
```bash
# See current model distribution
make agents-models

# Edit an agent's config
$EDITOR swarm/config/agents/test-author.yaml
# Change: model: inherit -> model: haiku

# Regenerate and verify
make gen-adapters && make check-adapters && make validate-swarm

# Confirm the change
make agents-models
```

**You show:**
- Model distribution before and after
- Successful regeneration
- Validation pass

### Hands-On Task: Break the Validator (Then Fix It)

**You say:** "Let's intentionally break validation to see how it catches misalignment."

**You run:**
```bash
# Introduce a color mismatch
$EDITOR .claude/agents/code-critic.md
# Change frontmatter: color: red -> color: blue

# Watch validation fail
make validate-swarm
# You'll see: "color 'blue' does not match expected color 'red' for role family 'critic'"

# Fix it
$EDITOR .claude/agents/code-critic.md
# Change back: color: blue -> color: red

# Confirm it passes
make validate-swarm
```

**You show:**
- Validation failure with specific error message
- Successful validation after fix

### Hands-On Task: Follow One Requirement Through All Flows

**You say:** "Let's trace the health check requirement from Signal through Wisdom to see the full SDLC chain."

**You run:**
```bash
# Signal: Problem and requirements
cat swarm/runs/demo-health-check/signal/problem_statement.md
cat swarm/runs/demo-health-check/signal/requirements.md

# Plan: Design and contracts
cat swarm/runs/demo-health-check/plan/adr_current.md

# Build: Implementation receipts
cat swarm/runs/demo-health-check/build/build_receipt.json | jq '.requirements'

# Gate: Merge decision
cat swarm/runs/demo-health-check/gate/merge_decision.md

# Deploy: Deployment verdict
cat swarm/runs/demo-health-check/deploy/deployment_decision.md

# Wisdom: Learnings
cat swarm/runs/demo-health-check/wisdom/learnings.md
```

**You show:**
- REQ-/AC- IDs threading through each flow
- Consistent traceability from signal to wisdom

### Explore Failure Scenarios

**You say:** "The examples directory contains curated failure scenarios. Let's explore one."

**You run:**
```bash
# List available scenarios
ls swarm/examples/

# Open missing tests scenario in Flow Studio
# http://localhost:5000/?run=health-check-missing-tests&mode=operator&flow=build&tab=run

# Read the bounce decision
cat swarm/examples/health-check-missing-tests/gate/merge_decision.md
```

**You show:**
- Available scenarios: `health-check`, `health-check-risky-deploy`, `health-check-missing-tests`
- Bounce-back decision explaining why the merge was rejected

### Running Your Own Flows

**You say:** "To run flows manually from Claude Code, use the flow commands."

**You run:**
```bash
/flow-1-signal "Your feature description here"
/flow-2-plan
/flow-3-build
/flow-4-gate
/flow-5-deploy
/flow-6-wisdom
```

**You show:**
- Each command creates a new `run-id` under `swarm/runs/<run-id>/`
- Artifacts appear in the corresponding flow subdirectory

---

## Troubleshooting

**Issue**: `make demo-run` fails or artifacts are missing

**Fix**: Check that `swarm/examples/health-check/` exists and contains
subdirectories for each flow

**Issue**: Flow Studio won't start

**Fix**: Run `make flow-studio` again; check that port 5000 is available

**Issue**: Validation fails unexpectedly

**Fix**: Run `make selftest-doctor` to diagnose harness vs service issues

**Issue**: Want to see a real Flow run?

**Fix**: Run `/flow-1-signal "your description"` in Claude Code; inspect
`swarm/runs/<new-run-id>/signal/` after it completes

---

## Key Files and Tools

| Resource | Purpose |
|----------|---------|
| `make flow-studio` | Start visual flow explorer |
| `make dev-check` | Run all validation (CI entrypoint) |
| `make selftest` | Full 10-step governance check |
| `make kernel-smoke` | Fast 3-step kernel check |
| `swarm/runs/demo-health-check/` | Demo artifacts from all 7 flows |
| `swarm/examples/` | Curated scenarios including failure cases |
| `swarm/flows/flow-*.md` | Flow specifications |
| `swarm/AGENTS.md` | Agent registry |
| `.claude/agents/` | Agent definitions |

---

## Next Steps

- **Deeper dive**: Read [CLAUDE.md](./CLAUDE.md) for complete orchestration reference
- **Philosophy**: See [swarm/positioning.md](./swarm/positioning.md)
- **Full structure**: Check [REPO_MAP.md](./REPO_MAP.md)
- **Why this approach**: Read [docs/WHY_DEMO_SWARM.md](./docs/WHY_DEMO_SWARM.md)
