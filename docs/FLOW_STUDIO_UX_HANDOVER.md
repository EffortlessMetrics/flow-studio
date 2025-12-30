# Flow Studio UX Maintenance Checklist

> **For**: Anyone modifying Flow Studio's user interface.
>
> This document is the operational checklist for UX changes. It covers what to update, what to run, and how to validate your work.

**Related docs**:
- [FLOW_STUDIO.md](./FLOW_STUDIO.md) - Feature reference and SDK contract
- [FLOW_STUDIO_API.md](./FLOW_STUDIO_API.md) - REST API reference
- [FLOW_STUDIO_FIRST_EDIT.md](./FLOW_STUDIO_FIRST_EDIT.md) - First-time contributor guide

---

## Quick Reference

| What you changed | Files to update | Tests to run |
|-----------------|-----------------|--------------|
| Added/moved a UI region | `layout_spec.ts` | `make ts-check && pytest tests/test_flow_studio_ui_ids.py -v` |
| Added a new `data-uiid` | `domain.ts` (type), `layout_spec.ts` (if in a region) | `pytest tests/test_flow_studio_ui_ids.py -v` |
| Changed SDK methods | `domain.ts` | `pytest tests/test_flow_studio_sdk_path.py -v` |
| Modified CSS | `flow-studio.base.css` | Visual inspection + layout review |
| Changed modal/dialog | Run a11y tests | `pytest tests/test_flow_studio_a11y.py -v` |
| Any visual change | Run layout review | `uv run swarm/tools/run_layout_review.py` |

---

## When You Change Flow Studio UX

### Adding or Moving Major UI Regions

If you add a new region (e.g., a new panel, modal, or toolbar):

1. **Update `layout_spec.ts`**:
   ```bash
   $EDITOR swarm/tools/flow_studio_ui/src/layout_spec.ts
   ```

   Add the new screen or region to the `screens` array:
   ```typescript
   {
     id: "flows.new_feature",
     route: "/?feature=new",
     title: "Flows - New Feature",
     description: "Description of what this screen shows",
     regions: [
       {
         id: "modal",  // or header, sidebar, canvas, inspector, sdlc_bar
         purpose: "What this region does",
         uiids: ["flow_studio.modal.new_feature"],
       },
     ],
   }
   ```

2. **Update the `FlowStudioUIID` type in `domain.ts`**:
   ```bash
   $EDITOR swarm/tools/flow_studio_ui/src/domain.ts
   ```

   Add your new UIIDs to the union type:
   ```typescript
   export type FlowStudioUIID =
     // ... existing UIIDs
     | "flow_studio.modal.new_feature"
     | "flow_studio.modal.new_feature.close";
   ```

3. **Add `data-uiid` attributes to HTML**:
   ```html
   <div data-uiid="flow_studio.modal.new_feature" role="dialog" aria-modal="true">
     ...
   </div>
   ```

4. **Run validation**:
   ```bash
   make ts-check
   pytest tests/test_flow_studio_ui_ids.py -v
   ```

### Adding New Governed Surfaces

Governed surfaces are stable APIs that tests and agents depend on. If you add one:

1. **Update `ux_manifest.json`**:
   ```bash
   $EDITOR ux_manifest.json
   ```

   Add references to new specs, tests, or tools:
   ```json
   {
     "specs": {
       "files": [
         "swarm/tools/flow_studio_ui/src/domain.ts",
         "swarm/tools/flow_studio_ui/src/layout_spec.ts",
         "swarm/tools/flow_studio_ui/src/new_feature.ts"
       ]
     }
   }
   ```

2. **Update SDK if adding new methods** (`domain.ts`):
   ```typescript
   export interface FlowStudioSDK {
     // ... existing methods
     newFeatureMethod(): Promise<void>;
   }
   ```

3. **Update tests**:
   - Add test cases to `tests/test_flow_studio_sdk_path.py` for SDK changes
   - Add test cases to `tests/test_flow_studio_ui_ids.py` for UIID changes

### Required Test Commands

After any UX change, run these in order:

```bash
# 1. TypeScript type checking (catches UIID/type mismatches)
make ts-check

# 2. Build TypeScript to JS
make ts-build

# 3. UI ID contract tests
pytest tests/test_flow_studio_ui_ids.py -v

# 4. Accessibility tests (for modal/interactive changes)
pytest tests/test_flow_studio_a11y.py -v

# 5. Full validation
make validate-swarm
```

---

## Key Files to Know About

### Governance Files

| File | Purpose | When to edit |
|------|---------|--------------|
| `ux_manifest.json` | Index of all UX specs, tests, and tools | Adding new governed surface |
| `swarm/tools/flow_studio_ui/src/domain.ts` | TypeScript types, SDK interface, `FlowStudioUIID` union | Adding UIIDs, changing API |
| `swarm/tools/flow_studio_ui/src/layout_spec.ts` | Screen/region registry for layout review | Adding screens or regions |
| `swarm/schemas/ux_critique.schema.json` | Schema for UX review artifacts | Changing review output format |

### CSS Design System

The design system lives in a single file:

```
swarm/tools/flow_studio_ui/css/flow-studio.base.css
```

**Design tokens** (CSS custom properties) are defined at the top:

```css
:root {
  /* Colors - Base */
  --fs-color-bg-base: #ffffff;
  --fs-color-bg-muted: #f9fafb;
  --fs-color-text: #111827;
  --fs-color-text-muted: #6b7280;

  /* Colors - Semantic */
  --fs-color-accent: #3b82f6;
  --fs-color-success: #22c55e;
  --fs-color-warning: #f59e0b;
  --fs-color-error: #ef4444;

  /* Agent role colors */
  --fs-color-step: #0f766e;
  --fs-color-implementation: #22c55e;
  --fs-color-critic: #ef4444;
  --fs-color-verification: #3b82f6;

  /* Spacing, radius, typography, shadows, z-index */
  --fs-spacing-md: 12px;
  --fs-radius-md: 4px;
  --fs-font-size-body: 12px;
}
```

**Utility classes** available:
- Typography: `.fs-text-xs`, `.fs-text-sm`, `.fs-text-body`, `.fs-text-lg`
- Monospace: `.fs-mono`, `.fs-mono-sm`, `.fs-mono-xs`
- Colors: `.fs-text-muted`, `.fs-text-subtle`
- Buttons: `.fs-button-small`, `.fs-button-primary`
- Labels: `.fs-label`

**State components** for consistent empty/loading/error states:
- `.fs-empty` - No data available
- `.fs-loading` - Data is loading
- `.fs-error` - Something went wrong
- `.fs-skeleton` - Placeholder shimmer effect
- `.fs-status-badge` - Status indicators (`.success`, `.warning`, `.error`, `.info`)

### UI Fragments and Components

TypeScript UI components live in:

```
swarm/tools/flow_studio_ui/src/
```

Key modules:

| Module | Purpose |
|--------|---------|
| `ui_fragments.ts` | Reusable HTML fragment functions (empty states, hints, KV displays) |
| `details.ts` | Step/agent/artifact detail panel rendering |
| `graph.ts` | Cytoscape graph rendering and styling |
| `graph_outline.ts` | Text-based outline view of graph |
| `search.ts` | Search box and result dropdown |
| `shortcuts.ts` | Keyboard shortcuts handling |
| `selftest_ui.ts` | Selftest modal and step explanations |
| `governance_ui.ts` | Governance badge and overlay |
| `tours.ts` | Guided tour system |

**Fragment functions** (in `ui_fragments.ts`) provide consistent UI patterns:

```typescript
// Empty states
renderNoRuns(): string
renderNoFlows(): string
renderSelectNodeHint(): string

// Error states
renderRunsLoadError(): string
renderErrorState(title, message, actionLabel?, actionOnClick?): string

// Key-value displays
renderKV(label, value, mono?): string
renderKVHtml(label, valueHtml): string

// Mode-specific hints
renderGettingStartedHint(flowKey): string
renderOperatorFlowHint(): string
```

---

## Layout Review Ritual

The layout review harness captures DOM, SDK state, and screenshots for each screen. Use it to verify visual changes and create review artifacts.

### Step-by-Step

```bash
# 1. Ensure Flow Studio is running
make flow-studio

# 2. Run the layout review
uv run swarm/tools/run_layout_review.py

# 3. Check the output
ls swarm/runs/ui-review/$(date +%Y%m%d-*)
```

### Artifacts Produced

The review creates a timestamped directory:

```
swarm/runs/ui-review/<YYYYMMDD-HHMMSS>/
  flows.default/
    dom.html          # Full HTML snapshot
    state.json        # SDK state (getState + getGraphState)
    screenshot.png    # Visual capture (requires Playwright)
    screen_spec.json  # Screen metadata from layout_spec.ts
  flows.selftest/
    ...
  flows.shortcuts/
    ...
  flows.validation/
    ...
  flows.tour/
    ...
  summary.json        # Run summary with success/error counts
```

### Command Options

```bash
# Use manifest fallback (when API unavailable)
uv run swarm/tools/run_layout_review.py --use-manifest

# Skip Playwright (HTTP-only capture, no screenshots)
uv run swarm/tools/run_layout_review.py --no-playwright

# Custom base URL
FLOW_STUDIO_BASE_URL=http://localhost:8000 uv run swarm/tools/run_layout_review.py
```

### When to Run Layout Review

Run layout review:
- **Before releases**: Capture baseline screenshots for release notes
- **After big UX changes**: Verify all screens render correctly
- **When adding screens**: Confirm new screens appear in the registry
- **For debugging**: Compare DOM/state between working and broken states

### Installing Playwright (Optional but Recommended)

For full screenshot and SDK state capture:

```bash
uv add playwright
playwright install chromium
```

Without Playwright, the tool falls back to HTTP-based capture (no screenshots, limited state).

---

## Test Coverage

### UI ID Tests (`tests/test_flow_studio_ui_ids.py`)

These tests validate the `data-uiid` contract:

| Test | What it checks |
|------|----------------|
| `test_valid_patterns` | UIIDs match `flow_studio[.<region>.<thing>][:{id}]` pattern |
| `test_invalid_patterns_rejected` | Bad patterns are caught (wrong prefix, uppercase) |
| `test_banned_layout_names_rejected` | Layout-based names like `leftCol`, `row2` are rejected |
| `test_uiids_follow_pattern` | All UIIDs in HTML follow the naming pattern |
| `test_no_duplicate_uiids` | No duplicate `data-uiid` values exist |
| `test_required_regions_present` | Required regions (header, sidebar, canvas, inspector) exist |
| `test_minimum_uiid_coverage` | At least 25 UIIDs are defined |
| `test_header_elements_have_uiids` | Key header elements have UIIDs |
| `test_sidebar_elements_have_uiids` | Key sidebar elements have UIIDs |
| `test_canvas_elements_have_uiids` | Key canvas elements have UIIDs |
| `test_ui_ready_states_documented_in_js` | JS defines loading/ready/error states |

Run with:
```bash
pytest tests/test_flow_studio_ui_ids.py -v
```

### Accessibility Tests (`tests/test_flow_studio_a11y.py`)

These tests catch common a11y regressions:

| Test Class | What it checks |
|------------|----------------|
| `TestLandmarks` | Page has banner, main, navigation, complementary landmarks |
| `TestARIAReferences` | `aria-labelledby`, `aria-controls`, `aria-describedby` reference valid IDs |
| `TestModalAccessibility` | Modals have `aria-modal`, `aria-labelledby`, focus trap utilities |
| `TestInteractiveElements` | Buttons have accessible names, selects have labels |
| `TestKeyboardNavigation` | Shortcuts module exists, common keys are handled |
| `TestLiveRegions` | Status regions exist for announcements |
| `TestColorAccessibility` | CSS uses design tokens, status not color-only |
| `TestUIReadyHandshake` | `data-ui-ready` attribute exists with three states |

Run with:
```bash
pytest tests/test_flow_studio_a11y.py -v
```

### Full UX Test Suite

Run all UX-related tests:

```bash
uv run pytest tests/test_flow_studio_ui_ids.py \
              tests/test_flow_studio_sdk_path.py \
              tests/test_flow_studio_a11y.py \
              tests/test_flow_studio_scenarios.py -v
```

---

## UIID Pattern Reference

### Pattern Format

```
flow_studio[.<region>.<thing>[.subthing][:{dynamic_id}]]
```

- **Screen prefix**: Always `flow_studio`
- **Region**: `header`, `sidebar`, `canvas`, `inspector`, `modal`, `sdlc_bar`
- **Thing**: Component name in `snake_case`
- **Subthing**: Optional nested component
- **Dynamic ID**: Use `:{id}` suffix for repeated items

### Valid Examples

```
flow_studio                              # Root container
flow_studio.header                       # Header region
flow_studio.header.search.input          # Search input in header
flow_studio.sidebar.flow_list            # Flow list in sidebar
flow_studio.canvas.outline.step:build:1  # Step node with dynamic ID
flow_studio.modal.selftest               # Selftest modal
```

### Invalid Examples (Avoid These)

```
header.search              # Missing flow_studio prefix
FlowStudio.header          # Wrong case
flow_studio.header.leftCol # Layout-based name (banned)
flow_studio.header.row2    # Layout-based name (banned)
flow_studio.Header.search  # Uppercase region
```

### Regions by Purpose

| Region | Purpose | Examples |
|--------|---------|----------|
| `header` | Top bar navigation, search, controls | search, mode toggle, governance badge |
| `sidebar` | Left panel navigation | run selector, flow list, view toggle |
| `canvas` | Main graph visualization | graph, legend, outline |
| `inspector` | Right details panel | step/agent/artifact details |
| `modal` | Modal dialogs | selftest, shortcuts |
| `sdlc_bar` | SDLC progress bar | flow status indicators |

---

## Checklists for Common Tasks

### Adding a New Modal

- [ ] Create modal HTML with `role="dialog"` and `aria-modal="true"`
- [ ] Add `aria-labelledby` pointing to modal title ID
- [ ] Add `data-uiid="flow_studio.modal.<name>"`
- [ ] Update `FlowStudioUIID` type in `domain.ts`
- [ ] Add screen entry to `layout_spec.ts`
- [ ] Implement focus trap (see `createFocusTrap` in `utils.ts`)
- [ ] Run `pytest tests/test_flow_studio_a11y.py -v`

### Adding a New Sidebar Section

- [ ] Add HTML with `data-uiid="flow_studio.sidebar.<name>"`
- [ ] Update `FlowStudioUIID` type in `domain.ts`
- [ ] Update sidebar region in `layout_spec.ts`
- [ ] Ensure proper heading hierarchy for a11y
- [ ] Run `pytest tests/test_flow_studio_ui_ids.py -v`

### Changing the SDK API

- [ ] Update `FlowStudioSDK` interface in `domain.ts`
- [ ] Implement method in `flow-studio-app.ts`
- [ ] Update `window.__flowStudio` assignment
- [ ] Add tests to `test_flow_studio_sdk_path.py`
- [ ] Update SDK documentation in `FLOW_STUDIO.md`
- [ ] Consider version bump for breaking changes

### Before Any Release

- [ ] Run `make ts-check`
- [ ] Run full test suite: `uv run pytest tests/test_flow_studio_*.py -v`
- [ ] Run layout review: `uv run swarm/tools/run_layout_review.py`
- [ ] Review screenshots in `swarm/runs/ui-review/*/`
- [ ] Update `ux_manifest.json` version if needed

---

## Off-Road Visualization Components

Flow Studio visualizes off-road navigation (detours, flow injection, graph extensions). This section documents the UI components for off-road features.

### Run Timeline Off-Road Badges

The Run History panel shows badges for runs with off-road routing:

| Badge | CSS Class | Meaning |
|-------|-----------|---------|
| "Off-road" | `.fs-badge.offroad` | Run included routing deviations |
| "Injected Flow" | `.fs-badge.injected` | Run included a dynamically injected flow |
| "Detour" | `.fs-badge.detour` | Run included detour routing |

### Event Types to Display

The Events Timeline should surface these off-road event types:

| Event Kind | Display | Color |
|------------|---------|-------|
| `routing_offroad` | Orange marker | `--fs-color-warning` |
| `flow_injected` | Purple marker | `var(--fs-color-offroad-inject)` |
| `node_injected` | Blue marker | `var(--fs-color-offroad-node)` |
| `graph_extended` | Gray marker | `--fs-color-text-muted` |
| `stack_push` | Purple push icon | `var(--fs-color-offroad-inject)` |
| `stack_pop` | Purple pop icon | `var(--fs-color-offroad-inject)` |

### Step Node Visual Treatments

Off-road steps receive distinct visual treatment:

```css
/* Normal step */
.fs-step-node { border: 2px solid var(--fs-color-step); }

/* Detour step */
.fs-step-node.detour {
  border: 2px dashed var(--fs-color-warning);
  background: var(--fs-color-warning-bg);
}

/* Injected node */
.fs-step-node.injected {
  border: 2px dotted var(--fs-color-accent);
  background: var(--fs-color-accent-bg);
}

/* Injected flow step */
.fs-step-node.inject-flow {
  border: 4px double var(--fs-color-offroad-inject);
  background: var(--fs-color-offroad-inject-bg);
}
```

### Flow Stack Visualization

When flows are stacked (nested execution), the UI shows:

**SDLC Bar**:
- Active flow: Blue pulsing border
- Paused flows: Gray background with stacked icon
- Stack depth badge: `+N` indicator

**Sidebar**:
- Flow items show state suffix: "(running)", "(paused)", "(completed)"
- Paused flows are dimmed but clickable

**Inspector**:
- Routing tab shows stack state
- "Paused at step X" indicator
- "Will resume when Y" condition

### Adding Off-Road UIIDs

If implementing off-road visualization, add these UIIDs to `domain.ts`:

```typescript
// Off-road visualization
| "flow_studio.sidebar.run_history.item.badge.offroad"
| "flow_studio.modal.run_detail.events.filter.routing"
| "flow_studio.modal.run_detail.events.item.offroad"
| "flow_studio.modal.run_detail.stack"
| "flow_studio.modal.run_detail.stack.depth"
| "flow_studio.sdlc_bar.flow.stacked"
| "flow_studio.sdlc_bar.stack_depth"
| "flow_studio.sidebar.flow_list.item.paused"
| "flow_studio.canvas.outline.step.routing_marker"
| "flow_studio.inspector.routing"
| "flow_studio.inspector.routing.suggestions"
| "flow_studio.inspector.routing.taken"
```

### API Endpoints for Off-Road Data

The following API endpoints support off-road visualization:

| Endpoint | Returns |
|----------|---------|
| `GET /api/runs/{id}/routing` | All routing decisions for a run |
| `GET /api/runs/{id}/events?kind=routing_offroad` | Filtered off-road events |
| `GET /api/runs/{id}/stack` | Current flow stack state |
| `GET /api/runs/{id}/boundary-review` | Aggregated assumptions/decisions/detours |

---

# Flow Studio & Swarm UX Handover (Reference)

The sections below provide deeper context for new owners of Flow Studio.

---

## 1. System context: where Flow Studio fits

At a high level, this repo implements a **governed, agentic SDLC**:

* 7 flows: **Signal -> Plan -> Build -> Review -> Gate -> Deploy -> Wisdom**
* ~45 agents, wired via:

  * Specs: `swarm/flows/`
  * Config: `swarm/config/`
  * Adapters: `.claude/agents/`, `.claude/commands/`
* Governance:

  * `swarm/tools/validate_swarm.py` (FR-001..FR-005)
  * Selftest system: `swarm/SELFTEST_SYSTEM.md`

**Flow Studio** is the **visual control surface** for all of that:

* Backend: `swarm/tools/flow_studio_fastapi.py` (FastAPI)
* Frontend: `swarm/tools/flow_studio_ui/` (TypeScript + CSS)
* Purpose:

  * Operators: see flow status, governance health, artifacts
  * LLMs/automation: have a structured UI+SDK they can drive safely

The repo also now has a **runbooks layer**:

* `swarm/runbooks/` — durable, versioned "how to actually do X" docs
* Flow Studio and selftest each have runbooks with explicit success criteria

---

## 2. Flow Studio: what's shipped

### 2.1 Code layout

**Backend**

* `swarm/tools/flow_studio_fastapi.py`

  * Serves:

    * `index.html`
    * Static assets under `/css` and `/js`
    * JSON APIs:

      * `/api/flows`, `/api/graph/*`, `/api/runs`, `/api/runs/*/summary`
      * `/api/validation`, `/platform/status`
      * `/api/tours`, `/api/selftest/plan`
      * health endpoints

**Frontend (ESM + TypeScript)**

Source (truth):

* `swarm/tools/flow_studio_ui/src/`

  * `domain.ts` — **all the types**: SDK, UIIDs, graph state, API responses
  * `global.d.ts` — window globals (SDK, debug objects, Cytoscape)
  * `state.ts` — `UIState` + helpers (`setMode`, `setCurrentRun`, etc.)
  * `api.ts` — typed API client for all `/api/*` endpoints
  * `graph.ts` — Cytoscape setup, layout, node interactions
  * `graph_outline.ts` — semantic graph companion + JSON export
  * `runs_flows.ts` — run + flow loading, SDLC bar, flow list, comparisons
  * `details.ts` — right-hand details panel (step/agent/artifact, timeline, timing)
  * `governance_ui.ts` — governance badge + overlays + FR badges
  * `search.ts` — header search with dropdown, keyboard nav
  * `shortcuts.ts` — keyboard shortcuts + help modal (with focus trap)
  * `tours.ts` — guided tours system
  * `selftest_ui.ts` — selftest modal + plan view + copy helpers
  * `selection.ts` — **unified selection model** (step/agent/artifact, URL, SDK)
  * `ui_fragments.ts` — HTML snippet helpers (empty/error states, hints, tabs)
  * `utils.ts` — formatting, clipboard, focus trap, modal helper
  * `flow-studio-app.ts` — **bootstrap shell**, wires everything + history
  * `main.ts` — entry point, imports `flow-studio-app.ts`

Build output (ignored):

* `swarm/tools/flow_studio_ui/js/` — compiled ES modules (gitignored)
* `swarm/tools/flow_studio_ui/css/flow-studio.base.css` — tokenized stylesheet
* `swarm/tools/flow_studio_ui/index.html` — shell HTML page

Node/TS config:

* `swarm/tools/flow_studio_ui/package.json` — `ts-build`, `ts-check`
* `swarm/tools/flow_studio_ui/tsconfig.json` — strict TS, `src -> js` ESM

### 2.2 UX contract: SDK, UIIDs, ready state

**SDK** (`window.__flowStudio`, typed as `FlowStudioSDK` in `domain.ts`)

Key methods:

* `getState()` -> snapshot:

  ```ts
  {
    currentFlowKey: FlowKey | null;
    currentRunId: string | null;
    currentMode: "author" | "operator";
    currentViewMode: "agents" | "artifacts";
    selectedNodeId: string | null;
    selectedNodeType: "step" | "agent" | "artifact" | null;
  }
  ```

* `getGraphState()` -> `GraphState | null` (deterministic nodes/edges for snapshots)

* `setActiveFlow(flowKey: FlowKey)` -> `Promise<void>`

* `selectStep(flowKey: FlowKey, stepId: string)` -> `Promise<void>`

* `selectAgent(agentKey: string, flowKey?: FlowKey)` -> `Promise<void>`

* `clearSelection()` -> `void`

* `qsByUiid(id: FlowStudioUIID)` -> `HTMLElement | null`

* `qsAllByUiidPrefix(prefix: string)` -> `NodeListOf<HTMLElement>`

**UIIDs** (`data-uiid="flow_studio...."`; type `FlowStudioUIID` in `domain.ts`)

Examples:

* Root: `flow_studio`
* Header:

  * `flow_studio.header`
  * `flow_studio.header.search.input`
  * `flow_studio.header.mode.author` / `.operator`
  * `flow_studio.header.governance`
* Sidebar:

  * `flow_studio.sidebar`
  * `flow_studio.sidebar.run_selector.select`
  * `flow_studio.sidebar.flow_list`
  * `flow_studio.sidebar.view_toggle.agents` / `.artifacts`
* Canvas:

  * `flow_studio.canvas`
  * `flow_studio.canvas.legend.toggle`
  * `flow_studio.canvas.outline` (ARIA tree; outline of graph)
* Inspector:

  * `flow_studio.inspector`
  * `flow_studio.inspector.details`
* Modals:

  * `flow_studio.modal.shortcuts`
  * `flow_studio.modal.selftest`

Plus patterns like:

* `flow_studio.canvas.outline.step:<flow>:<step>` for semantic outline nodes

**Ready state** (`data-ui-ready` on `<html>`)

* `"loading"` — init in progress
* `"ready"` — UI fully initialized, SDK available
* `"error"` — init failed

Helpers in `domain.ts`:

* `isUIReady()`
* `isUIError()`
* `getUIReadyState()`
* `waitForUIReady(timeoutMs)` -> resolves with `FlowStudioSDK`
* `getSDKIfReady()` -> `FlowStudioSDK | null`

Fastest test/agent pattern:

```js
await page.waitForSelector('html[data-ui-ready="ready"]');
const sdk = await page.evaluate(() => window.__flowStudio);
```

---

## 3. Governance: tests, runbooks, releases

### 3.1 Tests that protect the UX contract

**Structural & contract tests**

* `tests/test_flow_studio_ui_ids.py`

  * Validates:

    * `data-uiid` naming pattern (`flow_studio.[region].[thing]`)
    * Required UIIDs exist
    * No layout-based names ("leftCol", "row2", etc.)
    * Example selectors for tests (search, run selector, flow list)
* `tests/test_flow_studio_sdk_path.py`

  * Validates:

    * SDK export exists
    * `getState()` includes run + selection info
    * UIIDs exist in HTML
    * `waitForUIReady` semantics
    * Example Playwright usage patterns

**Scenario / behavior tests**

* `tests/test_flow_studio_scenarios.py`

  * Exercises:

    * Baseline load
    * Search and navigation
    * Deep links (`?run=...&flow=...&step=...`)
    * Selection syncing between graph/outline/details
    * Tours
    * Selftest integration

**Accessibility tests**

* `tests/test_flow_studio_a11y.py`

  * Validates:

    * Landmarks (banner, main, navigation, complementary)
    * ARIA references (label/controls/labelledby)
    * Buttons & selects have names
    * Focus traps on modals
    * Ready state semantics

### 3.2 Runbooks

**Operational runbooks**

* `swarm/runbooks/10min-health-check.md`

  * "Prove the system works in 10 minutes"
  * Steps:

    * `uv sync --extra dev`
    * `make dev-check`
    * `make demo-run`
    * `make flow-studio`
    * Keyboard walkthrough

* `swarm/runbooks/selftest-flowstudio-fastpath.md`

  * Fast path to check Flow Studio against selftest system

**Contributor guardrails**

* `CONTRIBUTING.md` -> "Working on Flow Studio (Governed UI)"

  * Always edit `src/*.ts`, never `js/`
  * Governed surfaces:

    * SDK shape
    * UIIDs
    * ready state
  * Must run:

    * `make dev-check`
    * Both runbooks above **before merging a Flow Studio PR**

**Maintenance reference**

* [`MAINTAINING_FLOW_STUDIO.md`](./MAINTAINING_FLOW_STUDIO.md)

  * Governing principles
  * 0.4.x release discipline (frozen SDK & UIIDs)
  * Checklist for governed surface changes

### 3.3 Releases & tags

* Mainline: `v2.2.0` (app-level)
* Flow Studio milestones:

  * `v0.4.0-flowstudio`

    * TS migration, Flow Studio UI, basic governance UX
    * Runbooks introduced
  * `v0.4.1-flowstudio`

    * a11y tests
    * SDK contract tests
    * CLAUDE router + governed surfaces documentation

`CHANGELOG.md` has a "Flow Studio Milestones" section that describes these.

---

## 4. What's *done* vs what's *missing*

**Done**

* Flow Studio UI itself:

  * TypeScript, ESM, tokens, ARIA, focus traps
* SDK contract:

  * `window.__flowStudio` typed, documented, tested
* Data contract:

  * `FlowStudioUIID` and `FlowStudioSDK` types are authoritative
* Governance:

  * Tests for UIIDs, SDK shape, a11y, scenarios
  * Runbooks for validation & Flow Studio
  * Maintenance docs + contributor guidance
* Releases:

  * 0.4.0 & 0.4.1 flowstudio tags
  * GitHub releases created

**UX Self-Test Layer Status (v0.5.0-flowstudio)**

The following items are now implemented:

1. **Layout spec as code** ✅

   * `swarm/tools/flow_studio_ui/src/layout_spec.ts` defines:
     * Each screen (id, route)
     * Regions (header, sidebar, canvas, inspector, modals)
     * Purpose per region
     * Which UIIDs live where
   * Exported via SDK (`getLayoutScreens()`, `getLayoutScreenById()`, `getAllKnownUIIDs()`)
   * Exposed via `/api/layout_screens` REST endpoint

2. **UI review runner** ✅

   * `swarm/tools/run_layout_review.py`:
     * Starts Flow Studio (or assumes it's running)
     * Enumerates screens (from layout spec)
     * Visits each URL
     * Waits for `data-ui-ready="ready"`
     * Dumps DOM, state into `swarm/runs/ui-review/<timestamp>/...`

3. **UX manifest** ✅

   * `ux_manifest.json` at repo root binds:
     * Layout spec (`domain.ts`, `layout_spec.ts`)
     * Docs (`FLOW_STUDIO.md`, `FLOW_STUDIO_UX_HANDOVER.md`, `MAINTAINING_FLOW_STUDIO.md`)
     * Tests (`test_flow_studio_ui_ids.py`, `test_flow_studio_sdk_path.py`, etc.)
     * Tools (`run_layout_review.py`, `flow_studio_fastapi.py`)
     * MCP servers (`mcp_ux_spec.py`, `mcp_ux_review.py`, `mcp_ux_repo.py`)
     * SDK methods and API endpoints
   * Used by LLM agents as the single source of "what matters about the UX"
   * Schema: `name`, `version`, `specs`, `docs`, `tests`, `tools`, `mcp_servers`, `api`, `sdk`, `workflows`

4. **Runbook for UI layout review** ✅

   * `swarm/runbooks/ui-layout-review.md`:
     * How to run the review script
     * Where the artifacts end up
     * How to drive MCP/Playwright/Vision over them

5. **MCP Servers for UX Review** ✅ (NEW)

   * `swarm/tools/mcp_ux_spec.py` — UX spec access (manifest, layout screens, UIIDs, critique schema)
   * `swarm/tools/mcp_ux_review.py` — Run layout reviews and load screen snapshots
   * `swarm/tools/mcp_ux_repo.py` — Governed file access for UX changes

6. **UX Agents** ✅ (NEW)

   * `.claude/agents/ux-critic.md` — Produces structured JSON critiques
   * `.claude/agents/ux-implementer.md` — Applies fixes from critiques
   * Configs in `swarm/config/agents/ux-*.yaml`

7. **UX Orchestrator** ✅ (NEW)

   * `swarm/tools/ux_orchestrator.py` — CLI to generate review prompts per screen
   * Usage: `uv run python -m swarm.tools.ux_orchestrator --screen flows.default`

All of these **layer on top** of the existing contract. They make MCP-driven reviews and UX iteration tractable without breaking the 0.4.x SDK contract.

### First UX Loop (Proof of Life)

The full UX loop has been run successfully on `flows.default`:

1. **Captured UI artifacts** via `run_layout_review.py`:
   - DOM snapshots, SDK state, layout JSON, screenshots
   - Output: `swarm/runs/ui-review/<timestamp>/flows.default/`

2. **Produced structured critique** via UX Critic agent:
   - Analyzed against layout spec, color semantics, a11y rules
   - Output: `swarm/runs/ux-critique/<timestamp>/flows.default.json`
   - Issues found: `canvas-graph-visibility` (high), `inspector-text-density` (medium), `decorative-icons-a11y` (low), `legend-default-expanded` (low)

3. **Applied a governed fix**:
   - Fix: Added `aria-hidden="true"` to decorative icons in `index.html`
   - Validated: `make dev-check` green
   - Shipped: PR #24 (`ux/flows-default-a11y-icons`)

This proves the loop works end-to-end. Remaining issues are tracked for follow-up iterations.

---

## 5. How to safely change Flow Studio

If you're the new owner and want to change anything, follow this order:

### 5.1 When you change code

1. Work in `swarm/tools/flow_studio_ui/src/`.

2. Run:

   ```bash
   make ts-check
   make ts-build
   make dev-check
   ```

3. If you touched:

   * `FlowStudioSDK` in `domain.ts`
   * `FlowStudioUIID` in `domain.ts`
   * ready state logic in `flow-studio-app.ts`

   then also:

   * Update `docs/FLOW_STUDIO.md` Governed Surfaces section
   * Update `FLOW_STUDIO_MAINTENANCE.md`
   * Update tests:

     * `test_flow_studio_ui_ids.py`
     * `test_flow_studio_sdk_path.py`
     * `test_flow_studio_scenarios.py`

4. Run:

   ```bash
   uv run pytest tests/test_flow_studio_*.py
   ```

### 5.2 Before merging

Run both runbooks end-to-end:

* `swarm/runbooks/10min-health-check.md`
* `swarm/runbooks/selftest-flowstudio-fastpath.md`

If **anything** in those runbooks feels wrong or out of date:

* Fix the system **or** fix the runbook in the same PR.

### 5.3 Typography and styling conventions

When adding or modifying UI text:

* **Prefer CSS classes over inline styles** — Use `.fs-meta-text`, `.muted`, `.mono` rather than `style="font-size: 11px"`.
* **Use design tokens** — Typography tokens exist in `flow-studio.base.css`:
  ```css
  --fs-font-size-xs: 10px;
  --fs-font-size-sm: 11px;
  --fs-font-size-body: 12px;
  --fs-font-size-md: 13px;
  --fs-font-size-lg: 14px;
  --fs-font-size-xl: 16px;
  ```
* **Future migration** — These tokens use `px` for now. A future PR may convert to `rem` for accessibility. When that happens, update the token values once; all usages will scale.
* **Avoid text bloat** — Keep microcopy concise. Prefer "See Run tab" over "Select the Run tab to see artifact status."

### 5.4 When you're ready to evolve the contract (post-0.4.x)

If you need to make a breaking change (e.g., new SDK method, UIID rename):

1. Treat it as a **minor bump** in the flowstudio line (e.g., `v0.5.0-flowstudio`).
2. Update:

   * `domain.ts` (types)
   * all related tests
   * the Governed Surfaces section
   * `CHANGELOG.md` Flow Studio milestones
3. Tag & release:

   * `git tag -a v0.5.0-flowstudio -m "..."`
   * `git push origin v0.5.0-flowstudio`
   * GitHub release with a short note

---

## 6. If you want to push this further (the "over the line" ideas)

This is optional, but aligns with the direction already set:

1. **Implement `layout_spec.ts`**

   * Define `ScreenSpec` and `LayoutRegion`.
   * Map each screen (home, flows, validation, modals, etc.).
   * Export via SDK and `/api/layout_screens`.

2. **Add `run_layout_review.py`**

   * Visit all screens with a default run (`demo-health-check`).
   * Dump DOM, state, layout JSON, screenshot.
   * Use these artifacts in MCP/vision critique passes.

3. **`ux_manifest.json`** (already implemented)

   * Located at repo root, binds:

     * `domain.ts`, `layout_spec.ts`
     * `FLOW_STUDIO.md`, maintenance doc
     * core tests
   * Enforced by `tests/test_flow_studio_ux_manifest.py`.

4. **Integrate with a Browser MCP**

   * Out-of-repo (or in a separate folder), build an agent that:

     * Reads `ux_manifest`
     * Reads `layout_spec`
     * Walks `ui-review` outputs
     * Produces a structured UX critique (per screen)

This would give you:

* Spec-as-code for layout
* Deterministic, enumerable UX surfaces
* Automated page-by-page review with vision models
* A clear story for "we test the UX, not just code"

---

## 7. How to read this repo as "the new owner"

If you're just starting:

1. **High-level orientation**

   * [`GETTING_STARTED.md`](./GETTING_STARTED.md)
   * [`INDEX.md`](./INDEX.md) → Operator Pack
   * [`CLAUDE.md`](../CLAUDE.md) – top "router" section for humans vs agents

2. **Flow Studio specific**

   * [`FLOW_STUDIO.md`](./FLOW_STUDIO.md) – conceptual + Governed Surfaces
   * [`MAINTAINING_FLOW_STUDIO.md`](./MAINTAINING_FLOW_STUDIO.md) – deeper maintenance rules
   * [`MAINTAINING_FLOW_STUDIO.md`](./MAINTAINING_FLOW_STUDIO.md) – architecture & schema guide
   * [`CONTRIBUTING.md`](../CONTRIBUTING.md) – Flow Studio section

3. **Runbooks**

   * [`10min-health-check.md`](../swarm/runbooks/10min-health-check.md)
   * [`selftest-flowstudio-fastpath.md`](../swarm/runbooks/selftest-flowstudio-fastpath.md)
   * [`ui-layout-review.md`](../swarm/runbooks/ui-layout-review.md)

4. **Tests**

   * `tests/test_flow_studio_a11y.py`
   * `tests/test_flow_studio_sdk_path.py`
   * `tests/test_flow_studio_scenarios.py`
   * (and later whatever we add for layout spec)

5. **Code**

   * `swarm/tools/flow_studio_ui/src/domain.ts`
   * `swarm/tools/flow_studio_ui/src/flow-studio-app.ts`
   * `swarm/tools/flow_studio_fastapi.py`

Once you're comfortable with those, the rest is "just" normal TS/HTML/CSS and Python.

---

If you hand this document plus the repo to a competent engineer, they should be able to:

* Understand what's already guaranteed (and by which tests)
* Know exactly where the API edges are
* Safely extend Flow Studio and its tests
* Finish the "UX self-test" layer without breaking what's here.
