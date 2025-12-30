# Flow Studio

> This document describes Flow Studio as implemented in this repo.
> The same contracts apply whether running in staging or production.

> For: Anyone wanting to visualize and explore flows interactively.

> **You are here:** Deep technical reference for maintainers. Coming from:
> [20-Minute Tour ←](./TOUR_20_MIN.md) | Jump to:
> [Adoption TL;DR →](./ADOPTING_SWARM_VALIDATION.md)

**See also:**
- [SELFTEST_SYSTEM.md](./SELFTEST_SYSTEM.md) — How Flow Studio fits into selftest
- [VALIDATION_RULES.md](./VALIDATION_RULES.md) — What the governance gate enforces (FR-001–FR-005)
- [CONTEXT_BUDGETS.md](./CONTEXT_BUDGETS.md) — How input context budgets and priority-aware truncation work
- [LEXICON.md](./LEXICON.md) — Canonical vocabulary (station, step, navigator, worker)

Flow Studio is the visual learning interface for the swarm SDLC. It renders
flows, steps, and stations as an interactive graph, letting you understand how
the swarm works without reading every spec file.

**UX v1.0 Changelog** (December 2025):

- **Onboarding Panel**: New flow/step/agent explainer with "First Edit" CTA for new users
- **Sidebar Flow Status Icons**: Visual status indicators (ok/warning/error/unknown) with tooltips
- **Inspector Text Density**: Reduced visual clutter in the details panel
- **Legend Behavior**: Session-scoped expand/collapse state persists across navigation
- **Documentation**: Added [First Edit Guide](./FLOW_STUDIO_FIRST_EDIT.md) and [Build Your Own Swarm](./FLOW_STUDIO_BUILD_YOUR_OWN.md)
- **UX Harness**: Layout review tool and accessibility (a11y) tests for governed surfaces

**Previous releases**:

- **Selftest Tab**: Click any step's "Selftest" tab to explore governance
  checks, dependencies, and run commands
- **Selftest Modal**: Click "View Selftest Plan" to see all 16 selftest
  steps and understand what each tier validates
- **FastAPI Backend**: Flow Studio now defaults to FastAPI for better
  performance and CORS support
- **Stable API**: Public REST API with documented contracts — integrate
  Flow Studio data into dashboards and tools

See [docs/FLOW_STUDIO_API.md](./FLOW_STUDIO_API.md) for the API reference and integration examples.

> **First time?**
> Start with Lane A of [docs/GETTING_STARTED.md](./GETTING_STARTED.md)
> (10 min):
>
> ```bash
> make demo-flow-studio    # Launches Flow Studio automatically
> # Then open: http://localhost:5000/?run=demo-health-check&mode=operator
> ```
>
> Or use Lane B to explore governance validation in the UI.
>
> **Ready to edit?** Follow [FLOW_STUDIO_FIRST_EDIT.md](./FLOW_STUDIO_FIRST_EDIT.md)
> to make your first agent change and see it reflected in the UI (15 min).

---

## If You're in a Hurry

Three steps to see the swarm in action:

1. **Start Flow Studio**:

   ```bash
   make demo-flow-studio  # or: make flow-studio
   ```

2. **Open the demo run**:

   Open your browser to:

   ```
   http://localhost:5000/?run=demo-health-check&mode=operator
   ```

3. **Explore**:

   - Click flow names in the **left sidebar** to switch flows (Signal → Plan
     → Build → Gate → Deploy → Wisdom)
   - Click **agent nodes** (colored dots) to see their role and model
   - Click the **Artifacts tab** to see what each flow produced
   - Click the **SDLC bar** at the top to see progress across all flows

**After 10 minutes**, you'll understand how flows, steps, and stations relate.
For a guided tour, see below.

---

## How to Run Flow Studio Locally

Three commands to get Flow Studio running with demo data:

```bash
# 1. Create demo data (populates swarm/runs/demo-run/)
make demo-run

# 2. Start Flow Studio server
make flow-studio

# 3. Open in browser with demo run loaded
#    http://localhost:5000/?run=demo-run&flow=build
```

**Explanation:**

- `make demo-run` populates `swarm/runs/demo-run/` with artifacts for all 7 flows
- `make flow-studio` starts the FastAPI server on port 5000
- The URL parameters:
  - `run=demo-run` loads the demo run artifacts
  - `flow=build` navigates directly to Flow 3 (Build)

**Alternative: Quick start without demo data**

```bash
make flow-studio
# then open http://localhost:5000
```

This shows the flow structure without run artifacts.

**Alternative: Use the health-check example**

```bash
make demo-flow-studio
# then open http://localhost:5000/?run=demo-health-check&mode=operator
```

This uses the curated `swarm/examples/health-check/` scenario.

---

## The Selftest Tab: Understanding Governance Checks

Every step node now has a **Selftest** tab that explains what governance checks apply to that step.

### Quick Start: Explore One Step

1. Open Flow Studio: `make flow-studio`
2. Click any **step node** (teal box) in a flow
3. Switch to the **Selftest** tab in the details panel on the right
4. You'll see:
   - **Summary**: How many selftest steps exist (Kernel, Governance, Optional)
   - **View Full Plan**: Opens a modal listing all 16 selftest steps
   - **Quick Commands**: Copy pre-built selftest commands

### Understanding the Plan Modal

Click **"View Full Plan"** to see:

- All selftest steps color-coded by tier:
  - 🔴 **KERNEL** (red): Failures block all merges
  - 🟡 **GOVERNANCE** (yellow): Failures block governance approval
  - 🔵 **OPTIONAL** (blue): Failures are informational
- Step descriptions: What each check validates
- Dependencies: Which steps must run first

### Learn What Each Step Does

Click any step in the plan to open its explanation modal:

- **Tier & Severity**: Why this step matters
- **Category**: What it validates (linting, governance, etc.)
- **Dependencies**: Steps that must pass first
- **Run This Step**: Copy commands to run it locally
- **Learn More**: Link to `docs/SELFTEST_SYSTEM.md`

### Example: Why "core-checks" Matters

```text
Step: core-checks
Tier: KERNEL (failures block all merges)
Category: linting
Description: Python lint (ruff) + compile check
Depends on: (nothing)

Run this step:
  uv run swarm/tools/selftest.py --step core-checks
```

This is the foundational check. If linting fails, governance can't even
begin.

---

## One Hour with Flow Studio

A step-by-step script to understand the swarm through the UI.

### 0–5 min: Setup

```bash
# Clone and install (skip if already done)
uv sync --extra dev

# Verify the swarm is healthy
make dev-check

# Populate demo artifacts
make demo-run

# Start Flow Studio
make flow-studio
```

Open `http://localhost:5000/?run=demo-health-check&mode=operator` in your
browser.

### 5–15 min: Explore the SDLC Bar

1. Look at the **SDLC bar** at the top — 7 boxes for 7 flows
2. All should be green (DONE) for the health-check run
3. Click each flow in the bar to switch views
4. Notice how Build (Flow 3) is the heaviest — most steps and stations

### 15–30 min: Walk the Build Flow

1. Click **Build** in the SDLC bar (or press `3`)
2. Switch to **Artifacts** view (toggle in the details panel)
3. See the artifacts this flow produced: `test_summary.md`, `build_receipt.json`
4. Switch back to **Steps/Agents** view
5. Click step nodes (teal) to see their role and stations
6. Click agent nodes (colored) to see their category and model

### 30–45 min: Try a Failure Scenario

1. Use the **Run selector** dropdown in the top-left
2. Select `health-check-risky-deploy`
3. Notice the SDLC bar changes — Gate (Flow 4) shows issues
4. Click Gate to see what failed
5. Open the **Run** tab to see the timeline overlay

### 45–60 min: Compare Runs

1. Open this URL to compare two runs:
   `http://localhost:5000/?run=demo-health-check&compare=health-check-risky-deploy`
2. See side-by-side flow status
3. Identify which flows differ and why

**After one hour**, you understand:

- How flows, steps, and stations relate
- How to read artifact status
- How to diagnose failures via the UI
- How to compare runs

---

## Backends & Events Timeline

Flow Studio can run flows using different execution backends. This lets you
exercise the same specs with Claude (Make harness), Gemini CLI, or the
stepwise orchestrator, while keeping all runs in a single ledger.

### Choosing a Backend

In the left sidebar, above the flow list, there is a **Backend** selector.

Common options are:

- **Claude (claude-harness)**
  Uses `claude-harness` to call the existing `make demo-*` targets. This is
  the same code path as the original demo flows.

- **Gemini (gemini-cli)**
  Uses the `gemini` CLI with `--output-format stream-json` to run each flow
  in a single call. In stub mode (default for CI / dev) it simulates events
  without requiring the CLI to be installed.

- **Gemini Stepwise (gemini-step-orchestrator)**
  Uses the step orchestrator backend to call Gemini once per step, with
  explicit context handoff between steps. This is useful for teaching and
  debugging, and is marked experimental while the APIs settle.

The selected backend is used whenever you start a run from Flow Studio.
Existing runs retain their original backend.

### Backend Badges in Run History

The **Run History** panel shows a badge for each run indicating its backend:

- `Claude` — `claude-harness`
- `Gemini` — `gemini-cli`
- `Gemini Stepwise` — `gemini-step-orchestrator`

Clicking a run opens the **Run Detail** modal, which also shows the backend
in the metadata section.

### Events Timeline

The Run Detail modal includes an **Events Timeline** section. Click
**"Load Events"** to fetch the runtime events for that run.

You'll see:

- **Timestamp** — When the event occurred
- **Event kind** — `run_created`, `flow_start`, `tool_start`, `step_complete`, etc.
- **Flow key** — Which flow the event belongs to (when available)
- **Payload snippet** — A short JSON snippet from the event payload

This is especially useful for Gemini backends, where the CLI streams
structured events. Use the timeline to debug why a run failed, or to see
how a stepwise run progressed through its steps.

### UIID Selectors for Automation

For test automation, use these `data-uiid` selectors:

| Selector | Purpose |
|----------|---------|
| `[data-uiid="flow_studio.sidebar.backend_selector.select"]` | Backend dropdown |
| `[data-uiid^="flow_studio.sidebar.run_history.item.badge.backend:"]` | All backend badges |
| `[data-uiid="flow_studio.modal.run_detail.events.toggle"]` | "Load Events" button |
| `[data-uiid="flow_studio.modal.run_detail.events.container"]` | Events list container |

---

## Viewing Wisdom

The Run Detail modal includes a **Wisdom** section for runs that have completed Flow 6 (Prod -> Wisdom). This surfaces the analysis and learnings extracted from the run.

### Loading Wisdom Data

1. Open the **Run Detail** modal by clicking a run in the Run History panel
2. Click **"Load Wisdom"** to fetch the wisdom summary for that run
3. If Flow 6 has not run or no `wisdom_summary.json` exists, the button will show an error

### Understanding Wisdom Metrics

The wisdom summary displays key metrics from Flow 6 analysis:

| Metric | Meaning |
|--------|---------|
| **Artifacts Present** | Total artifacts found across all flows |
| **Regressions Found** | Number of regressions detected vs previous runs |
| **Learnings Count** | Extractable learnings identified for future runs |
| **Feedback Actions** | Suggested improvements or pattern updates |
| **Issues Created** | GitHub issues opened by wisdom stations |

### Flow Status Summary

The wisdom view shows per-flow status and loop counts:

- **status**: `succeeded`, `failed`, or `skipped`
- **loop_counts**: For flows with microloops (Build), shows iteration counts (e.g., `{"test": 2, "code": 3}`)

### Labels and Key Artifacts

- **Labels**: Classification tags applied by wisdom stations (e.g., `clean-run`, `no-regressions`, `needs-review`)
- **Key Artifacts**: Links to the most important wisdom outputs:
  - `wisdom/artifact_audit.md` — Artifact presence and completeness audit
  - `wisdom/regressions.md` — Regression analysis
  - `wisdom/learnings.md` — Extractable patterns and improvements

### API Access

Wisdom data is also available via the REST API:

```bash
curl http://localhost:5000/api/runs/health-check/wisdom/summary | jq .
```

See [FLOW_STUDIO_API.md](./FLOW_STUDIO_API.md) for the full response schema.

---

## Demo Links

Canonical URLs for slides, talks, and documentation:

| Scenario | URL |
|----------|-----|
| Baseline (operator mode) | `/?run=demo-health-check&mode=operator` |
| Build microloops (author mode) | `/?run=demo-health-check&flow=build&view=agents&mode=author` |
| Missing tests scenario | `/?run=health-check-missing-tests&mode=operator&flow=build&tab=run` |
| Risky deploy scenario | `/?run=health-check-risky-deploy&mode=operator&flow=gate&tab=run` |
| Run comparison | `/?run=demo-health-check&compare=health-check-risky-deploy` |

All URLs assume `http://localhost:5000` as the base.

---

## For Operators: Reading the UI

This section maps Flow Studio UI elements to decisions. Use this when reviewing runs or preparing for audits.

### SDLC Bar States

The SDLC bar at the top shows progress across all 7 flows. Each flow box can be:

| State | Visual | Meaning | Action |
|-------|--------|---------|--------|
| **DONE** | Green | Flow completed successfully | None required |
| **ACTIVE** | Blue pulse | Flow currently running | Wait for completion |
| **BLOCKED** | Yellow | Waiting on predecessor | Check previous flow |
| **FAILED** | Red | Flow failed or bounced | Click to see details |
| **NOT_STARTED** | Gray | Flow not yet begun | Expected if earlier flows incomplete |

**Decision flow:**

1. If Gate (Flow 4) is **yellow** → open Gate flow, check `merge_recommendation.md`
2. If Gate is **red** → work bounced; check if bounce target is Build or Plan
3. If Deploy (Flow 5) is **yellow** → Gate decision was BOUNCE or ESCALATE; don't deploy
4. If all green → run is healthy, ready for human review

### Governance Badge

The governance badge (top-right area) summarizes validation status:

| Badge | Meaning | Action |
|-------|---------|--------|
| **All Clear** | FR-001–FR-005 pass | Swarm is healthy |
| **Issues (N)** | N validation failures | Click badge → Validation tab |
| **Unknown** | Validation not run | Run `make dev-check` |

**Common issue patterns:**

- **FR-001 failure**: Agent ↔ registry mismatch → run `make check-adapters`
- **FR-002 failure**: Frontmatter issue → check agent YAML
- **FR-003 failure**: Flow references invalid agent → check flow spec
- **FR-005 failure**: Hardcoded path in flow spec → use `RUN_BASE/` placeholder

### FR Badges (Validation Tab)

Each FR (Functional Requirement) has its own badge:

| FR | What it validates | If failing |
|----|-------------------|------------|
| FR-001 | Agent registry bijection | Agent added/removed without registry update |
| FR-002 | Agent frontmatter | Missing required fields, wrong color |
| FR-003 | Flow references | Flow mentions non-existent agent |
| FR-004 | Skills | Skill referenced but SKILL.md missing |
| FR-005 | RUN_BASE | Hardcoded paths in flow specs |

### Agent Node Colors

Agent nodes in the graph are colored by role family:

| Color | Family | Example stations |
|-------|--------|----------------|
| **Green** | Implementation | code-implementer, test-author |
| **Red** | Critic/Review | code-critic, test-critic |
| **Blue** | Verification | coverage-enforcer, contract-enforcer |
| **Orange** | Planning | design-optioneer, work-planner |
| **Purple** | Analysis | impact-analyzer, risk-analyst |
| **Teal** | Cross-cutting | repo-operator, gh-reporter |

### What Flow Studio Does NOT Answer

Flow Studio is for **structure and status**, not:

- **Log analysis**: Use CI logs or `swarm/runs/<run-id>/` artifacts directly
- **Diff review**: Use git diff or PR interface
- **Performance metrics**: Use observability tooling (see `swarm/infrastructure/`)
- **Real-time execution**: Flow Studio shows snapshots, not live updates

For these, see the relevant artifacts in `RUN_BASE/` or external tooling.

---

## Flow Key Reference

Flow Studio uses flow keys to identify flows. This table maps keys to human names:

| Flow key | Human name | Number |
|----------|------------|--------|
| signal | Signal -> Spec | Flow 1 |
| plan | Specs -> Plan | Flow 2 |
| build | Plan -> Draft | Flow 3 |
| gate | Draft -> Verify | Flow 4 |
| deploy | Artifact -> Prod | Flow 5 |
| wisdom | Prod -> Wisdom | Flow 6 |

These keys are used in:
- URL parameters: `?flow=build`
- SDK methods: `setActiveFlow("build")`
- API endpoints: `/api/flows/build`
- Config files: `swarm/config/flows/build.yaml`

---

## 1. Conceptual Map

Flow Studio reads from YAML configs and renders them as an interactive graph:

```text
spec (swarm/flows/*.md)
        │
        ▼
config (swarm/config/flows/*.yaml, swarm/config/agents/*.yaml)
        │
        ▼
adapters (.claude/agents/*.md)
        │
        ▼
runs (swarm/runs/<run-id>/)
```

### UI Surfaces

| Surface | Purpose |
|---------|---------|
| **Sidebar flows** | List of all 7 flows; click to load |
| **Graph** | Cytoscape visualization showing steps → agents |
| **Details panel** | Info for selected step or agent |
| **SDLC bar** | Run progress across all 7 flows |
| **Run selector** | Switch between active runs and examples |

### Node Types in the Graph

- **Step nodes** (teal boxes): Flow execution order; numbered S1, S2, etc.
- **Agent nodes** (colored by role): Implementation agents
- **Solid edges**: Step sequence (S1 → S2 → S3)
- **Dotted edges**: Step → Agent assignment

---

## 2. Guided Views

These deep links show specific aspects of the swarm. Click one after starting
Flow Studio.

### View 1: A Complete Run

See a happy-path run with all 7 flows completed:

```text
http://localhost:5000/?run=demo-health-check&tab=run
```

This shows:

- SDLC bar with all flows green (DONE)
- Run summary with artifact counts
- Flow timeline showing execution order

### View 2: Build Flow Microloops

See how Build (Flow 3) uses adversarial microloops:

```text
http://localhost:5000/?flow=build&tab=graph
```

This shows:

- 9 steps: repo setup → context → tests → code → hardening → commit
- Author/critic pairs: test-author ⇄ test-critic, code-implementer ⇄ code-critic
- Mutator → fixer hardening loop
- Green (implementation), red (critic), blue (verification) color coding

### View 3: Comparing Runs

Compare artifact status across two runs:

```text
http://localhost:5000/?run=health-check&compare=demo-run&flow=build
```

This shows:

- Side-by-side flow status
- Which artifacts differ
- Useful for debugging why one run passed and another failed

---

## 3. CLI Connection

Flow Studio is a UI over the same config files the CLI uses:

### Same Source of Truth

| CLI command | What it uses | Flow Studio equivalent |
|-------------|--------------|----------------------|
| `make validate-swarm` | `swarm/config/agents/*.yaml` | Agent list, colors |
| `make gen-flows` | `swarm/config/flows/*.yaml` | Graph structure |
| `make demo-run` | Creates `swarm/runs/demo-health-check/` | Run selector, SDLC bar |

### Common Workflow

```bash
# 1. Validate the swarm is healthy
make dev-check

# 2. Populate an example run
make demo-run

# 3. Visualize in Flow Studio
make flow-studio
```

Then open `http://localhost:5000` to see the run.

### Editing Flows

1. Edit the YAML: `$EDITOR swarm/config/flows/build.yaml`
2. Regenerate: `make gen-flows`
3. Click "Reload" in Flow Studio (top right)
4. Verify: `make validate-swarm`

Everything you see in Flow Studio is just a visualization of the YAML
configs. The CLI commands (`make gen-*`, `make validate-*`) are the
authoritative tools; Flow Studio helps you understand their output.

---

## API Endpoints

Flow Studio exposes a REST API for programmatic access:

| Endpoint | Returns |
|----------|---------|
| `GET /api/health` | `{"status": "ok"}` |
| `GET /api/flows` | List of all flows with step counts |
| `GET /api/flows/<key>` | Single flow with full step details |
| `GET /api/agents` | List of all agents |
| `GET /api/graph/<flow>` | Cytoscape-format nodes and edges |
| `GET /api/runs` | Available runs (active + examples) |
| `GET /api/runs/<id>/summary` | Run summary with flow status |
| `GET /api/runs/<id>/sdlc` | SDLC bar data |

---

## Troubleshooting

### "No runs found"

Run `make demo-run` to populate the example run.

### Graph is empty

Check that `swarm/config/flows/*.yaml` exists. Run `make gen-flows` to
regenerate from specs.

### Agent colors wrong

Colors come from `swarm/config/agents/*.yaml`. Run `make check-adapters`
to verify config ↔ adapter alignment.

### Changes not showing

Click "Reload" in the top-right corner, or restart the server.

### Slow runs list / too many runs

Too many runs can slow down Flow Studio. Clean up with:

```bash
make runs-list        # Check run count
make runs-prune-dry   # Preview cleanup
make runs-prune       # Apply retention policy
```

See [runs-retention.md](../swarm/runbooks/runs-retention.md) for full GC documentation.

### "Failed to parse summary" in logs

Corrupt run metadata is causing parse errors:

```bash
make runs-quarantine-dry   # Identify corrupt runs
make runs-quarantine       # Move to swarm/runs/_corrupt/
```

---

## Architecture Note

Flow Studio reads YAML configs directly. It does **not** parse the Markdown
specs in `swarm/flows/*.md`. The configs are generated from those specs via
`make gen-flows`, so the workflow is:

```text
swarm/flows/*.md  →  make gen-flows  →  swarm/config/flows/*.yaml  →  Flow Studio
```

This keeps a single source of truth (the Markdown specs) while allowing
fast, schema-validated UI rendering from YAML.

---

## Source Layout (Modular HTML)

Flow Studio's `index.html` is **generated** from smaller, maintainable fragments.
This makes it easier for humans and agents to edit individual UI regions without
dealing with a 6000+ line monolithic file.

### Source Files

| Type | Location | Purpose |
|------|----------|---------|
| **HTML Fragments** | `swarm/tools/flow_studio_ui/fragments/*.html` | UI regions (header, sidebar, canvas, etc.) |
| **TypeScript** | `swarm/tools/flow_studio_ui/src/*.ts` | Behavior modules |
| **CSS** | `swarm/tools/flow_studio_ui/css/flow-studio.base.css` | Styles and design tokens |
| **Generator** | `swarm/tools/gen_index_html.py` | Assembles index.html |

### Fragment Files

```text
fragments/
├── 00-head.html       # DOCTYPE, head, body start, app container
├── 10-header.html     # Header region (search, mode toggle, etc.)
├── 20-sdlc-bar.html   # SDLC progress bar
├── 30-sidebar.html    # Sidebar (run selector, flow list, run history)
├── 40-canvas.html     # Main canvas (legend, graph area, outline)
├── 50-inspector.html  # Inspector/details panel
├── 60-modals.html     # All modals (selftest, shortcuts, run-detail)
└── 90-footer.html     # Closing body/html
```

### Generated Output

The generator assembles `index.html` from:
1. HTML fragments (in order by filename)
2. Inline CSS from `css/flow-studio.base.css`
3. Inline JS bundle from compiled `js/*.js` modules

### Commands

```bash
make gen-index-html    # Generate index.html from fragments
make check-index-html  # Verify index.html matches fragments (for CI)
make flow-studio       # Includes gen-index-html automatically
```

### Editing Flow Studio UI

To modify the UI structure:

1. **Edit the appropriate fragment** in `swarm/tools/flow_studio_ui/fragments/`
2. **Regenerate** with `make gen-index-html`
3. **Test** with `uv run pytest tests/test_flow_studio_ui_ids.py -v`

Do **not** edit `index.html` directly—your changes will be overwritten.

### Build Contract: Compiled JS in Repo

Flow Studio uses **Contract A**: compiled JS is committed to the repo for "clone → run" reliability.

**Why?** Flow Studio is a demo harness. Users should be able to run it immediately after cloning without setting up a Node.js toolchain. Silent failures from missing JS assets (the bug this contract prevents) are worse than the minor overhead of committing compiled output.

**For contributors editing TypeScript:**

1. **Edit** TypeScript in `swarm/tools/flow_studio_ui/src/*.ts`
2. **Build** with `make ts-build`
3. **Commit** both the TS source changes and the compiled JS output

**CI enforces drift**: The `check-ui-drift` job rebuilds TypeScript and fails if the compiled output doesn't match what's in the repo. If CI fails with "Flow Studio JS drift detected", run `make ts-build` and commit the output.

**Line ending stability**: `.gitattributes` enforces LF line endings for JS files to ensure deterministic builds across platforms.

---

## Governed Surfaces (Do Not Break Lightly)

Flow Studio exposes a public contract for tests and agents. Changes to these surfaces require updating tests and documentation.

> **Stability window (0.4.x)**
> For the 0.4.x line, the Flow Studio SDK shape, `data-uiid` contract, and
> `data-ui-ready` semantics are treated as **frozen API**. Changes to these
> should be treated as breaking: update types, tests, runbooks, and the
> Flow Studio release notes, and bump the minor version (e.g. 0.5.0).

### SDK Contract (`window.__flowStudio`)

The SDK is available when `data-ui-ready="ready"` on `<html>`. Types are defined in `swarm/tools/flow_studio_ui/src/domain.ts`.

| Method | Returns | Purpose |
|--------|---------|---------|
| `getState()` | `{ currentFlowKey, currentRunId, currentMode, currentViewMode, selectedNodeId, selectedNodeType }` | Read current UI state |
| `getGraphState()` | `GraphState \| null` | Serialized graph for snapshots |
| `setActiveFlow(flowKey)` | `Promise<void>` | Navigate to a flow |
| `selectStep(flowKey, stepId)` | `Promise<void>` | Select a step node |
| `selectAgent(agentKey, flowKey?)` | `Promise<void>` | Select an agent node |
| `clearSelection()` | `void` | Deselect current node |
| `qsByUiid(id)` | `Element \| null` | Query by typed UIID |
| `qsAllByUiidPrefix(prefix)` | `NodeList` | Query by UIID prefix |
| `getLayoutScreens()` | `LayoutScreen[]` | Get all screen definitions from layout spec |
| `getLayoutScreenById(id)` | `LayoutScreen \| undefined` | Get a specific screen by ID |
| `getAllKnownUIIDs()` | `string[]` | Get all UIIDs defined in layout spec |

### Layout Spec (v0.5.0+)

The layout spec (`swarm/tools/flow_studio_ui/src/layout_spec.ts`) defines all screens programmatically:

```ts
interface LayoutScreen {
  id: ScreenId;           // e.g., "flows.default", "validation.overview"
  route: string;          // URL route pattern
  regions: LayoutRegion[];
  purpose: string;
}

interface LayoutRegion {
  id: string;             // e.g., "header", "sidebar", "canvas"
  purpose: string;
  uiids: string[];        // UIIDs in this region
}
```

The layout spec is also exposed via REST API:
- `GET /api/layout_screens` — All screens with regions and UIIDs
- `GET /api/layout_screens/<id>` — Single screen by ID

### UIID Selectors (`data-uiid`)

Tests and agents should use `[data-uiid="..."]` selectors, not arbitrary CSS. Key UIIDs:

- `flow_studio.header.search.input` — Search input field
- `flow_studio.sidebar.flow_list` — Flow navigation list
- `flow_studio.sidebar.run_selector.select` — Run dropdown
- `flow_studio.canvas.graph` — Cytoscape graph container
- `flow_studio.canvas.outline.step:{id}` — Step node in outline
- `flow_studio.inspector.details` — Details panel

Full type: `FlowStudioUIID` in `domain.ts`.

### UI Ready States (`data-ui-ready`)

The `<html>` element signals initialization state:

| State | Meaning | SDK Available? |
|-------|---------|----------------|
| `"loading"` | Initialization in progress | No |
| `"ready"` | UI fully initialized | Yes |
| `"error"` | Initialization failed | No |

### When Changing Governed Surfaces

1. Update types in `swarm/tools/flow_studio_ui/src/domain.ts`
2. Update tests:
   - `tests/test_flow_studio_ui_ids.py` — UIID coverage
   - `tests/test_flow_studio_scenarios.py` — E2E scenarios
   - `tests/test_flow_studio_sdk_path.py` — SDK contract
3. Update this section if the API shape changes
4. Consider bumping the `v0.4.x-flowstudio` tag series

---

## Stepwise Backends

Stepwise backends execute flows one step at a time, making a separate LLM call
for each step rather than running the entire flow in a single invocation. This
provides finer-grained observability and better error isolation.

### What is Stepwise Execution?

In standard execution, a backend runs an entire flow in one CLI/API call. The
LLM receives all step instructions upfront and executes them sequentially
within a single session.

In **stepwise execution**, the orchestrator:

1. Loads the flow definition from `flow_registry`
2. Iterates through each step in order
3. Makes a separate LLM call per step
4. Passes context from previous steps to subsequent steps
5. Persists events and artifacts after each step

This approach trades throughput for observability and control.

### Available Stepwise Backends

| Backend ID | Engine | Description |
|------------|--------|-------------|
| `gemini-step-orchestrator` | `GeminiStepEngine` | Gemini CLI stepwise execution |
| `claude-step-orchestrator` | `ClaudeStepEngine` | Claude Agent SDK stepwise execution |

Both stepwise backends use the `GeminiStepOrchestrator` class from
`swarm/runtime/orchestrator.py` with different underlying engines from
`swarm/runtime/engines.py`.

### Benefits of Stepwise Execution

1. **Per-step observability**: Each step emits separate `step_start` and
   `step_end` events, making it easy to identify which step failed or took
   longer than expected.

2. **Context handoff**: Previous step outputs are included in subsequent step
   prompts, enabling explicit reasoning chains across steps.

3. **Better error isolation**: When a step fails, the orchestrator stops
   immediately. You can inspect the exact step that failed without parsing
   a long transcript.

4. **Teaching mode**: Stepwise execution supports pausing at step boundaries,
   making it useful for demonstrations and debugging.

5. **Engine flexibility**: The same orchestrator works with different LLM
   backends (Gemini, Claude) by swapping the `StepEngine` implementation.

### How to Select a Stepwise Backend

In Flow Studio, use the **Backend** dropdown in the left sidebar (above the
flow list) to select a stepwise backend before starting a run.

Alternatively, when using the API:

```bash
# Start a stepwise run via the REST API
curl -X POST http://localhost:5000/api/run \
  -H "Content-Type: application/json" \
  -d '{
    "flow_key": "build",
    "backend": "gemini-step-orchestrator",
    "params": {}
  }'
```

### Transcript and Receipt Locations

Stepwise backends write detailed transcripts and receipts for each step:

```text
RUN_BASE/<flow>/
  llm/
    <step_id>-<agent>-gemini.jsonl   # Gemini CLI transcript
    <step_id>-<agent>-claude.jsonl   # Claude Agent SDK transcript
  receipts/
    <step_id>-<agent>.json           # Step receipt with timing/tokens
```

**Transcript format**: JSONL with one message per line. Each line includes
`timestamp`, `role`, and `content` fields.

**Receipt format**: JSON with execution metadata:

```json
{
  "engine": "claude-step",
  "model": "claude-sonnet-4-20250514",
  "step_id": "S1",
  "flow_key": "build",
  "run_id": "run-abc123",
  "agent_key": "context-loader",
  "started_at": "2025-01-15T10:00:00Z",
  "completed_at": "2025-01-15T10:00:05Z",
  "duration_ms": 5000,
  "status": "succeeded",
  "tokens": {"prompt": 1200, "completion": 800, "total": 2000},
  "transcript_path": "llm/S1-context-loader-claude.jsonl"
}
```

### Events Timeline for Stepwise Runs

The Run Detail modal in Flow Studio shows an **Events Timeline** for stepwise
runs with events like:

- `run_created` — Run initialized with stepwise mode
- `step_start` — Step execution began (includes agent, role, engine)
- `tool_start` / `tool_end` — Tool invocations within the step
- `step_end` / `step_error` — Step completed or failed
- `run_completed` — All steps finished

Use the timeline to trace execution flow and debug step-level issues.

### Stub Mode for Development

Both stepwise engines support stub mode for development and CI:

- `SWARM_GEMINI_STUB=1`: Use synthetic responses instead of real Gemini CLI
- The Claude engine currently runs in stub mode by default

Stub mode writes transcript and receipt files with placeholder content,
allowing end-to-end testing of the orchestrator without LLM costs.

---

## Off-Road Visualization

Flow Studio visualizes runs where the navigator has gone "off-road"—deviating from the pre-defined flow graph to handle edge cases, inject sidequests, or adapt to runtime conditions.

### Understanding Off-Road Navigation

The swarm follows a "High Trust" model where the flow graph defines **suggestions**, not **constraints**. When the navigator encounters a situation not handled by the golden path, it can:

- **Inject a detour**: Route to a sidequest station and return to the main path
- **Inject a new node**: Add a station not in the original flow spec
- **Inject an entire flow**: Pause the current flow, run a different flow, then resume
- **Skip a step**: Bypass a step when preconditions aren't met

All off-road decisions are logged with rationale for human review.

### Off-Road Badge

When a run includes off-road routing decisions, Flow Studio shows an **"Off-road"** badge in several locations:

| Location | Badge Appearance | Meaning |
|----------|------------------|---------|
| **Run History** | Red "Off-road" badge | This run deviated from the golden path |
| **SDLC Bar** | Yellow highlight on flow | This flow included routing deviations |
| **Step Node** | Dashed border + icon | This step was injected or is a detour |
| **Timeline** | Orange event marker | Off-road routing decision occurred here |

### Quick Links to Off-Road Artifacts

When viewing an off-road run, the Run Detail modal provides quick links to:

- **Injected Spec Artifacts**: The spec files that were dynamically generated or selected
- **Routing Rationale**: The navigator's explanation for why it went off-road
- **Return Points**: Where the execution returned to the main flow

### Visual Distinction by Routing Type

Different off-road patterns have distinct visual treatments:

| Pattern | Border Style | Icon | Color |
|---------|--------------|------|-------|
| **Normal Step** | Solid | None | Teal |
| **DETOUR** | Dashed | `↩️` (return arrow) | Orange |
| **INJECT_FLOW** | Double | `📦` (package) | Purple |
| **INJECT_NODE** | Dotted | `➕` (plus) | Blue |

---

## Routing Events

Flow Studio displays routing-related events in the Events Timeline. These events provide visibility into the navigator's decision-making process.

### Core Routing Events

| Event Kind | When Emitted | Payload |
|------------|--------------|---------|
| `routing_decision` | After each step completes | `{next_step_id, route_type, confidence, reason}` |
| `routing_offroad` | When navigator deviates from golden path | `{golden_path_step, actual_step, rationale, return_address}` |
| `flow_injected` | When a new flow is started mid-run | `{parent_flow, injected_flow, trigger_step, resume_point}` |
| `node_injected` | When a new node is added to current flow | `{flow_key, node_spec, position, rationale}` |
| `graph_extended` | When navigator proposes spec changes | `{proposals: [{patch_type, target, diff}]}` |

### Event Timeline Filtering

In the Run Detail modal, use the **Event Filter** dropdown to focus on routing events:

- **All Events**: Show everything
- **Routing Only**: Show only `routing_*` events
- **Off-road Only**: Show only deviations from golden path
- **Flow Transitions**: Show `flow_start`, `flow_completed`, `flow_injected`

### Reading Routing Event Payloads

The `routing_offroad` event payload contains critical diagnostic information:

```json
{
  "ts": "2025-12-15T10:00:05Z",
  "kind": "routing_offroad",
  "flow_key": "build",
  "step_id": "S4",
  "payload": {
    "golden_path_step": "code-critic",
    "actual_step": "security-scanner",
    "route_type": "DETOUR",
    "rationale": "Detected potential SQL injection pattern; routing to security scan before critic review",
    "return_address": "code-critic",
    "confidence": 0.85,
    "evaluated_conditions": [
      "has_db_queries == true",
      "security_scan_recent == false"
    ],
    "tie_breaker_used": false
  }
}
```

### UIID Selectors for Routing Events

| Selector | Purpose |
|----------|---------|
| `[data-uiid="flow_studio.modal.run_detail.events.filter.routing"]` | Routing filter option |
| `[data-uiid="flow_studio.modal.run_detail.events.item.offroad"]` | Off-road event row |
| `[data-uiid="flow_studio.sidebar.run_history.item.badge.offroad"]` | Off-road badge in run list |

---

## Flow Stack Visualization

When the navigator injects a flow mid-execution (e.g., Flow 3 injects Flow 8 for rebasing), Flow Studio visualizes the **flow execution stack**.

### What is the Flow Stack?

The flow stack tracks nested flow execution:

```
Stack when Flow 3 injects Flow 8:
┌─────────────────────────────┐
│ Flow 8 (Rebase)  [ACTIVE]   │ <- Currently executing
├─────────────────────────────┤
│ Flow 3 (Build)   [PAUSED]   │ <- Waiting for Flow 8 to complete
│   at step: code-implementer │
│   return_on: flow_completed │
└─────────────────────────────┘
```

When Flow 8 completes, the orchestrator pops the stack and resumes Flow 3 at the return point.

### Stack Visualization in the UI

**SDLC Bar**:
- Active flow: Blue pulsing highlight
- Paused flows: Gray with "stacked" icon (`📚`)
- Stack depth indicator: Shows `+N` badge when flows are stacked

**Flow Sidebar**:
- Paused flows show "(paused)" suffix
- Active flow shows "(running)" suffix
- Click a paused flow to view its state at pause time

**Inspector Panel**:
- When viewing a paused flow, shows "Paused at step {step_id}"
- Shows "Will resume when {condition}"
- Links to the flow that caused the pause

### Stack State in Run Detail Modal

The Run Detail modal includes a **Stack** tab showing:

| Field | Description |
|-------|-------------|
| **Current Depth** | Number of flows on the stack (1 = normal, 2+ = nested) |
| **Active Flow** | The flow currently executing |
| **Paused Flows** | List of paused flows with their pause points |
| **Max Depth Reached** | Historical maximum stack depth during this run |

### Stack Events

| Event Kind | When Emitted | Payload |
|------------|--------------|---------|
| `stack_push` | When a flow is paused and new flow injected | `{paused_flow, paused_step, injected_flow}` |
| `stack_pop` | When an injected flow completes | `{completed_flow, resumed_flow, resumed_step}` |
| `stack_overflow_prevented` | When max depth (3) would be exceeded | `{attempted_flow, current_depth, action_taken}` |

### Safety: Stack Depth Limits

The orchestrator enforces a maximum stack depth of 3 to prevent unbounded recursion:

1. **Depth 1**: Normal flow execution
2. **Depth 2**: One injected flow (e.g., Build → Rebase)
3. **Depth 3**: Emergency recovery only (e.g., Rebase → HotfixPrep)

If injection would exceed depth 3, the orchestrator:
- Emits `stack_overflow_prevented` event
- Continues on current path with `needs_human: true`
- Logs warning for human review

### UIID Selectors for Stack Visualization

| Selector | Purpose |
|----------|---------|
| `[data-uiid="flow_studio.sdlc_bar.flow.stacked"]` | Flow with stacked indicator |
| `[data-uiid="flow_studio.sdlc_bar.stack_depth"]` | Stack depth badge |
| `[data-uiid="flow_studio.sidebar.flow_list.item.paused"]` | Paused flow in sidebar |
| `[data-uiid="flow_studio.modal.run_detail.stack"]` | Stack tab in run detail |
| `[data-uiid="flow_studio.modal.run_detail.stack.depth"]` | Stack depth display |

---

## Suggested vs Taken Detours

Flow Studio distinguishes between what the navigator **suggested** at each decision point and what path was **actually taken**.

### The Suggestion Model

At each routing decision point, the navigator may evaluate multiple possible paths:

1. **Golden Path**: The next step defined in the flow spec
2. **Suggested Detours**: Alternative paths based on runtime conditions
3. **Taken Path**: The path actually chosen

The navigator records all evaluated options, not just the winner.

### Visualization in Flow Studio

**Step Node Tooltip**:
When hovering over a step node, the tooltip shows:

```
Step: code-critic (S4)
━━━━━━━━━━━━━━━━━━━━━━━
Routing at this step:
  • Suggested: code-implementer (loop back, 75%)
  • Suggested: self-reviewer (advance, 20%)
  • Suggested: security-scanner (detour, 5%)
  ────────────────────
  ✓ Taken: code-implementer
    Reason: "UNVERIFIED status, iteration 2 of 5"
```

**Decision Point Markers**:
- **Green checkmark**: Followed the golden path
- **Orange arrow**: Went off-road (took a non-primary suggestion)
- **Red exclamation**: Went completely off-road (path not in suggestions)

### Detour Suggestions in Inspector

When selecting a step that had routing suggestions, the Inspector's **Routing** tab shows:

| Column | Description |
|--------|-------------|
| **Option** | The suggested next step |
| **Score** | Confidence score (0-1) |
| **Conditions** | CEL expressions that matched |
| **Taken** | Whether this option was chosen |

### Highlighting Off-Road Decisions

When the navigator went off-road (chose something not in the primary suggestions):

- The step node gets an **orange border**
- The edge to the next step is **dashed orange**
- The Events Timeline shows a `routing_offroad` event
- The Run Summary includes "Off-road decisions: N"

### Comparing Suggested vs Taken Across Runs

In Run Comparison mode (`?run=A&compare=B`), Flow Studio highlights:

- Steps where Run A followed suggestions but Run B went off-road
- Steps where both runs went off-road but chose differently
- Aggregate off-road decision count per run

This helps identify patterns: "Why does this run always detour at step 4?"

### UIID Selectors for Suggestions

| Selector | Purpose |
|----------|---------|
| `[data-uiid="flow_studio.canvas.outline.step.routing_marker"]` | Decision point marker |
| `[data-uiid="flow_studio.inspector.routing"]` | Routing tab in inspector |
| `[data-uiid="flow_studio.inspector.routing.suggestions"]` | Suggestions list |
| `[data-uiid="flow_studio.inspector.routing.taken"]` | Taken path highlight |
| `[data-uiid^="flow_studio.canvas.edge.offroad:"]` | Off-road edges |

---

## See Also

- **[FLOW_STUDIO_FIRST_EDIT.md](./FLOW_STUDIO_FIRST_EDIT.md)**: Make your first agent edit (15 min walkthrough)
- **[SELFTEST_SYSTEM.md](./SELFTEST_SYSTEM.md)**: The 16 selftest steps that Flow Studio visualizes
- **[VALIDATION_RULES.md](./VALIDATION_RULES.md)**: FR-001–FR-005 rules behind agent/flow colors
- **[FLOW_STUDIO_API.md](./FLOW_STUDIO_API.md)**: REST API reference for programmatic access
- **[CONTEXT_BUDGETS.md](./CONTEXT_BUDGETS.md)**: Token discipline and priority-aware history truncation
- **[LONG_RUNNING_HARNESSES.md](./LONG_RUNNING_HARNESSES.md)**: Anthropic patterns for state persistence and observability
- **[GETTING_STARTED.md](./GETTING_STARTED.md)**: Quick start guide with Flow Studio lane
- **[AGOPS_MANIFESTO.md](./AGOPS_MANIFESTO.md)**: High Trust model and detour philosophy
- **[ADR-004](./adr/ADR-004-bounded-smart-routing.md)**: Bounded smart routing architecture
- **[ROADMAP_3_0.md](./ROADMAP_3_0.md)**: v3.0 features including MacroNavigator and stack handling
