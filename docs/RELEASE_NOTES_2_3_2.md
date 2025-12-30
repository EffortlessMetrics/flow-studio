# v2.3.2 Release Notes

> **Release Date:** December 2025
>
> This release improves Flow Studio responsiveness, fixes documentation inconsistencies,
> and adds context budget cross-references throughout the documentation.

---

## v2.3.2: The Governed Baseline

**v2.3.2 is the stable governed baseline** for teams evaluating or adopting Flow Studio.

If you're landing here for the first time, this is the version to pin to:

- **16-step selftest** covering KERNEL → GOVERNANCE → OPTIONAL tiers
- **Context budgets** with priority-aware history truncation
- **Flow Studio v1** with async loading and operator/observer modes
- **Wisdom scaffolding** for cross-run learning extraction

This version represents a complete, tested implementation of the 7-flow SDLC pattern.
Treat `main` and `v2.3.2` as immutable except for critical bugfixes, doc errata, or security issues.

### Announcement (Copy-Paste Ready)

> **Flow Studio v2.3.2** is now available — a governed SDLC harness for teams wondering
> what AI-assisted development with audit trails actually looks like.
>
> In under an hour you can: run selftest (16 steps), open Flow Studio, and see receipts
> for every agent decision. It's a reference implementation, not a product — fork and copy patterns.
>
> Start here: [EVALUATION_CHECKLIST.md](EVALUATION_CHECKLIST.md) (1-hour guided path)
> or [TOUR_20_MIN.md](TOUR_20_MIN.md) (quick visual overview).

---

## Stability Matrix

What's stable vs experimental in v2.3.2:

| Surface | Status | Notes |
|---------|--------|-------|
| **Receipt format** | ✅ Stable | Event kinds, JSON schema locked |
| **Stepwise contract** | ✅ Stable | Transcript format, behavioral invariants |
| **Validation rules** (FR-001–FR-005) | ✅ Stable | Breaking changes require ADR |
| **Selftest AC/schema** | ✅ Stable | 16-step breakdown, tier assignments |
| **Flow Studio SDK** (`window.__flowStudio`) | ✅ Stable | `getState`, `setActiveFlow`, `selectStep` |
| **UIID selectors** (`data-uiid`) | ✅ Stable | Test and automation targets |
| **Context budget config** | ✅ Stable | `context_budgets.yaml` schema |
| Wisdom UIs | ⚠️ Experimental | Shape may change in v2.4 |
| Model registry defaults | ⚠️ Experimental | May tune based on feedback |
| New visualizations | ⚠️ Experimental | Flow Studio v2 features |

**Stable** means: no breaking changes without migration path and ADR.
**Experimental** means: expect iteration; pin to specific behavior if needed.

### Status

v2.3.2 is an early re-implementation of a swarm pattern that has worked before, exercised on the included examples and a handful of demos; expect gaps in other scenarios and file issues when you find them.

---

## Highlights

- **Flow Studio: Non-blocking initialization** – Run history now loads in background, preventing UI hang on slow runs APIs
- **Documentation consistency** – Test counts, selftest step references, and context budget links updated
- **Engine mode clarity** – Runtime config docstrings now accurately reflect available modes per engine

---

## Changes

### Flow Studio Improvements

**Non-blocking run history loading:**
- Run history panel now loads asynchronously after core UI is ready
- This prevents the "Loading..." hang when the runs API is slow or run discovery is expensive
- The main UI (flows, profiles, governance badge) becomes interactive immediately

### Documentation Updates

**Test baseline updates:**
- Updated test counts from 1609 → ~1750 across all baseline documentation
- Updated in: `DEFINITION_OF_DONE.md`, `HANDOVER_TEST_HARNESS_V2_3_1.md`, `RELEASE_NOTES_2_3_1.md`

**Selftest step count fixes:**
- Updated references from "10-step" to "16-step" where referring to actual step count
- Note: ADR references to "10-step selftest pattern" are design pattern names and remain unchanged
- Updated in: `GETTING_STARTED.md`, `SELFTEST_DEVELOPER_WORKFLOW.md`, `PACKAGING_NOTES.md`

**Context budgets cross-linking:**
- Added `CONTEXT_BUDGETS.md` link to README.md "Release Notes & Contracts" section
- Added `CONTEXT_BUDGETS.md` link to STEPWISE_BACKENDS.md "See Also" section

### Runtime Configuration Fixes

**Engine mode docstring accuracy:**
- `get_engine_mode()` docstring now correctly documents:
  - gemini: "stub" or "cli"
  - claude: "stub", "sdk", or "cli"
- Module docstring example updated to use "cli" instead of "real"
- `runtime.yaml` comment for Gemini corrected: "Options: stub, cli"

---

## Technical Details

### Flow Studio Init Change

**Before:**
```typescript
// Blocking - UI waits for run history
await initRunHistory();
```

**After:**
```typescript
// Non-blocking - UI ready immediately, history loads in background
initRunHistory()
  .then(() => { /* sync selection */ })
  .catch((err) => { console.error(err); });
```

This change addresses the issue where Flow Studio would show "Loading..." indefinitely if the `/api/runs` endpoint was slow due to large numbers of runs or slow filesystem discovery.

---

## Upgrade Notes

### From v2.3.1

This is a non-breaking point release:

1. Run `uv sync --extra dev` to update dependencies
2. Run `make ts-build` to rebuild TypeScript (optional, compiled JS included)
3. Flow Studio will now load faster on repositories with many runs

### No API Changes

- No changes to receipt format or event kinds
- No changes to stepwise contract
- No changes to validation rules

---

## See Also

- [RELEASE_NOTES_2_3_1.md](./RELEASE_NOTES_2_3_1.md): Previous release
- [CONTEXT_BUDGETS.md](./CONTEXT_BUDGETS.md): Token discipline and history truncation
- [FLOW_STUDIO.md](./FLOW_STUDIO.md): Flow Studio documentation
- [STEPWISE_BACKENDS.md](./STEPWISE_BACKENDS.md): Stepwise execution guide
