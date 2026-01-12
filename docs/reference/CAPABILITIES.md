# Capability Registry

> **GENERATED FILE - DO NOT EDIT**
>
> Source: `specs/capabilities.yaml`
> Regenerate: `make gen-capabilities-doc`

This document lists what Flow Studio can do, with evidence pointers.

## Status Legend

| Status | Meaning |
|--------|---------|
| **implemented** | Has code + test evidence; safe to claim publicly |
| **supported** | Has code but incomplete/no formal tests; use with caveats |
| **aspirational** | Design only; NOT shipped; do NOT claim as available |

---


## Table of Contents

- [Receipts](#receipts)
- [Routing](#routing)
- [Validation](#validation)
- [Transport](#transport)
- [Selftest](#selftest)
- [Flow_Studio](#flow_studio)
- [Quality](#quality)
- [Spec_Ledger](#spec_ledger)

---

## Receipts

*Step execution audit trail and evidence binding*

| Capability | Status | Summary |
|------------|--------|---------|
| `receipts.required_fields` | implemented | Receipts include engine, mode, step_id, flow_key, run_id,... |
| `receipts.write_api` | implemented | Unified write_step_receipt() API for all execution paths |
| `receipts.git_capture` | implemented | Receipts capture git SHA and branch at execution time |
| `receipts.tool_calls` | implemented | Receipts capture normalized tool call data |
| `receipts.routing_signal` | implemented | Receipts include routing decision for audit trail |

### `receipts.required_fields`

**Status:** **implemented**

Receipts include engine, mode, step_id, flow_key, run_id, timestamps, status, tokens

**Evidence:**
  - **Code:**
    - `swarm/runtime/receipt_io.py` → `StepReceiptData`
  - **Tests:**
    - [unit] `tests/test_receipt_io.py`

### `receipts.write_api`

**Status:** **implemented**

Unified write_step_receipt() API for all execution paths

**Evidence:**
  - **Code:**
    - `swarm/runtime/receipt_io.py` → `write_step_receipt`
  - **Tests:**
    - [unit] `tests/test_receipt_io.py`

### `receipts.git_capture`

**Status:** **implemented**

Receipts capture git SHA and branch at execution time

**Evidence:**
  - **Code:**
    - `swarm/runtime/receipt_io.py` → `capture_git_info`
  - **Tests:**
    - [unit] `tests/test_receipt_io.py`

### `receipts.tool_calls`

**Status:** **implemented**

Receipts capture normalized tool call data

**Evidence:**
  - **Code:**
    - `swarm/runtime/receipt_io.py` → `StepReceiptData.tool_calls`
  - **Tests:**
    - [unit] `tests/test_receipt_io.py`

### `receipts.routing_signal`

**Status:** **implemented**

Receipts include routing decision for audit trail

**Evidence:**
  - **Code:**
    - `swarm/runtime/receipt_io.py` → `StepReceiptData.routing_signal`
  - **Tests:**
    - [unit] `tests/test_receipt_io.py`

---

## Routing

*Flow graph navigation and step transitions*

| Capability | Status | Summary |
|------------|--------|---------|
| `routing.decision_vocabulary` | implemented | Closed vocabulary: ADVANCE, LOOP, TERMINATE, BRANCH, SKIP |
| `routing.decision_types` | implemented | Decision provenance: EXPLICIT, EXIT_CONDITION, DETERMINIS... |
| `routing.modes` | implemented | Routing modes: DETERMINISTIC_ONLY, ASSIST, AUTHORITATIVE |
| `routing.microloop_context` | implemented | Microloop iteration tracking with stall detection |
| `routing.stall_detection` | implemented | Elephant Protocol: velocity-based stall detection for rep... |
| `routing.candidate_pattern` | implemented | Python generates candidates, Navigator chooses, Python va... |
| `routing.skip_justification` | implemented | High-friction justification required for SKIP decisions |
| `routing.why_now` | implemented | WhyNow justification for DETOUR/INJECT routing |
| `routing.wp4_explanation` | implemented | WP4-compliant routing explanation for audit trails |

### `routing.decision_vocabulary`

**Status:** **implemented**

Closed vocabulary: ADVANCE, LOOP, TERMINATE, BRANCH, SKIP

**Evidence:**
  - **Code:**
    - `swarm/runtime/types/routing.py` → `RoutingDecision`
  - **Tests:**
    - [unit] `tests/test_route_step_navigator.py`

### `routing.decision_types`

**Status:** **implemented**

Decision provenance: EXPLICIT, EXIT_CONDITION, DETERMINISTIC, CEL, LLM_*

**Evidence:**
  - **Code:**
    - `swarm/runtime/types/routing.py` → `DecisionType`
  - **Tests:**
    - [unit] `tests/test_route_step_navigator.py`

### `routing.modes`

**Status:** **implemented**

Routing modes: DETERMINISTIC_ONLY, ASSIST, AUTHORITATIVE

**Evidence:**
  - **Code:**
    - `swarm/runtime/types/routing.py` → `RoutingMode`
  - **Tests:**
    - [unit] `tests/test_routing_driver_fixes.py`

### `routing.microloop_context`

**Status:** **implemented**

Microloop iteration tracking with stall detection

**Evidence:**
  - **Code:**
    - `swarm/runtime/types/routing.py` → `MicroloopContext`
  - **Tests:**
    - [unit] `tests/test_progress_tracker.py`

### `routing.stall_detection`

**Status:** **implemented**

Elephant Protocol: velocity-based stall detection for repeated failures

**Evidence:**
  - **Code:**
    - `swarm/runtime/types/routing.py` → `StallContext`
  - **Tests:**
    - [unit] `tests/test_progress_tracker.py`

### `routing.candidate_pattern`

**Status:** **implemented**

Python generates candidates, Navigator chooses, Python validates

**Evidence:**
  - **Code:**
    - `swarm/runtime/types/routing.py` → `RoutingCandidate`
  - **Tests:**
    - [unit] `tests/test_route_step_navigator.py`

### `routing.skip_justification`

**Status:** **implemented**

High-friction justification required for SKIP decisions

**Evidence:**
  - **Code:**
    - `swarm/runtime/types/routing.py` → `SkipJustification`
  - **Tests:**
    - [unit] `tests/test_route_step_navigator.py`

### `routing.why_now`

**Status:** **implemented**

WhyNow justification for DETOUR/INJECT routing

**Evidence:**
  - **Code:**
    - `swarm/runtime/types/routing.py` → `WhyNowJustification`
  - **Tests:**
    - [unit] `tests/test_route_step_navigator.py`

### `routing.wp4_explanation`

**Status:** **implemented**

WP4-compliant routing explanation for audit trails

**Evidence:**
  - **Code:**
    - `swarm/runtime/types/routing.py` → `WP4RoutingExplanation`
  - **Tests:**
    - [unit] `tests/test_route_step_navigator.py`

---

## Validation

*Swarm specification validation (pack-check philosophy)*

| Capability | Status | Summary |
|------------|--------|---------|
| `validation.fr001_bijection` | implemented | 1:1 mapping between AGENTS.md registry and .claude/agents/ |
| `validation.fr002_frontmatter` | implemented | Agent frontmatter validation (name, description, color, m... |
| `validation.fr003_flow_refs` | implemented | Flow specs only reference valid agents (with typo detection) |
| `validation.fr004_skills` | implemented | Skills have valid SKILL.md files |
| `validation.fr005_runbase` | implemented | Flow specs use RUN_BASE placeholders, not hardcoded paths |
| `validation.fr006_prompt_sections` | implemented | Agent prompts have required sections (Inputs, Outputs, Be... |
| `validation.incremental_mode` | implemented | Git-aware incremental validation (--check-modified) |

### `validation.fr001_bijection`

**Status:** **implemented**

1:1 mapping between AGENTS.md registry and .claude/agents/

**Evidence:**
  - **Code:**
    - `swarm/tools/validate_swarm.py` → `validate_bijection`
  - **Tests:**
    - [unit] `tests/test_bijection.py`

### `validation.fr002_frontmatter`

**Status:** **implemented**

Agent frontmatter validation (name, description, color, model)

**Evidence:**
  - **Code:**
    - `swarm/tools/validate_swarm.py` → `validate_frontmatter`
  - **Tests:**
    - [unit] `tests/test_frontmatter.py`

### `validation.fr003_flow_refs`

**Status:** **implemented**

Flow specs only reference valid agents (with typo detection)

**Evidence:**
  - **Code:**
    - `swarm/tools/validate_swarm.py` → `validate_flow_references`
  - **Tests:**
    - [unit] `tests/test_validate_swarm_json.py`

### `validation.fr004_skills`

**Status:** **implemented**

Skills have valid SKILL.md files

**Evidence:**
  - **Code:**
    - `swarm/tools/validate_swarm.py` → `validate_skills`
  - **Tests:**
    - [unit] `tests/test_skills_lint.py`

### `validation.fr005_runbase`

**Status:** **implemented**

Flow specs use RUN_BASE placeholders, not hardcoded paths

**Evidence:**
  - **Code:**
    - `swarm/tools/validate_swarm.py` → `validate_runbase_paths`
  - **Tests:**
    - [unit] `tests/test_runbase.py`

### `validation.fr006_prompt_sections`

**Status:** **implemented**

Agent prompts have required sections (Inputs, Outputs, Behavior)

**Evidence:**
  - **Code:**
    - `swarm/tools/validate_swarm.py` → `validate_prompt_sections`
  - **Tests:**
    - [unit] `tests/test_prompt_sections.py`

### `validation.incremental_mode`

**Status:** **implemented**

Git-aware incremental validation (--check-modified)

**Evidence:**
  - **Code:**
    - `swarm/tools/validate_swarm.py`
  - **Tests:**
    - [unit] `tests/test_incremental_mode.py`

---

## Transport

*LLM backend abstraction and capability declaration*

| Capability | Status | Summary |
|------------|--------|---------|
| `transport.capability_declaration` | implemented | Transports declare capabilities via TransportCapabilities... |
| `transport.session_protocol` | implemented | StepSessionProtocol: work() -> finalize() -> route() phases |
| `transport.claude_sdk` | implemented | Claude Agent SDK transport with full capabilities |
| `transport.claude_cli` | implemented | Claude CLI transport (stateless, best-effort structured o... |
| `transport.gemini_cli` | implemented | Gemini CLI transport (large context, microloop fallback) |
| `transport.stub` | implemented | Stub transport for testing and CI (simulates all capabili... |
| `transport.subsumption` | supported | Kernel compensates for missing backend capabilities |

### `transport.capability_declaration`

**Status:** **implemented**

Transports declare capabilities via TransportCapabilities dataclass

**Evidence:**
  - **Code:**
    - `swarm/runtime/transports/port.py` → `TransportCapabilities`
  - **Tests:**
    - [unit] `tests/test_step_engine_contract.py`

### `transport.session_protocol`

**Status:** **implemented**

StepSessionProtocol: work() -> finalize() -> route() phases

**Evidence:**
  - **Code:**
    - `swarm/runtime/transports/port.py` → `StepSessionProtocol`
  - **Tests:**
    - [unit] `tests/test_step_engine_contract.py`

### `transport.claude_sdk`

**Status:** **implemented**

Claude Agent SDK transport with full capabilities

**Evidence:**
  - **Code:**
    - `swarm/runtime/transports/port.py` → `CLAUDE_SDK_CAPABILITIES`
    - `swarm/runtime/transports/claude_sdk_transport.py`
  - **Tests:**
    - [unit] `tests/test_step_engine_sdk_smoke.py`

### `transport.claude_cli`

**Status:** **implemented**

Claude CLI transport (stateless, best-effort structured output)

**Evidence:**
  - **Code:**
    - `swarm/runtime/transports/port.py` → `CLAUDE_CLI_CAPABILITIES`
  - **Tests:**
    - [unit] `tests/test_claude_stepwise_backend.py`

### `transport.gemini_cli`

**Status:** **implemented**

Gemini CLI transport (large context, microloop fallback)

**Evidence:**
  - **Code:**
    - `swarm/runtime/transports/port.py` → `GEMINI_CLI_CAPABILITIES`
  - **Tests:**
    - [unit] `tests/test_gemini_stepwise_backend.py`

### `transport.stub`

**Status:** **implemented**

Stub transport for testing and CI (simulates all capabilities)

**Evidence:**
  - **Code:**
    - `swarm/runtime/transports/port.py` → `STUB_CAPABILITIES`
  - **Tests:**
    - [unit] `tests/test_step_engine_contract.py`

### `transport.subsumption`

**Status:** *supported*

Kernel compensates for missing backend capabilities

> Pattern defined; implementation varies by capability

**Evidence:**
  - **Code:**
    - `swarm/runtime/transports/port.py` → `structured_output_fallback`
  - **Design:**
    - `.claude/rules/execution/subsumption-principle.md`

---

## Selftest

*Platform selftest and governance tiers*

| Capability | Status | Summary |
|------------|--------|---------|
| `selftest.kernel_smoke` | implemented | Fast kernel health check (<0.5s) |
| `selftest.introspectable_plan` | implemented | Selftest --plan shows all steps with tiers |
| `selftest.individual_steps` | implemented | Run individual selftest steps with --step flag |
| `selftest.degraded_mode` | implemented | Degraded mode treats OPTIONAL failures as warnings |
| `selftest.governance_tiers` | implemented | KERNEL, GOVERNANCE, OPTIONAL tiers with different blockin... |

### `selftest.kernel_smoke`

**Status:** **implemented**

Fast kernel health check (<0.5s)

**Evidence:**
  - **Code:**
    - `swarm/tools/kernel_smoke.py`
  - **Tests:**
    - [bdd] `@AC-SELFTEST-KERNEL-FAST`

### `selftest.introspectable_plan`

**Status:** **implemented**

Selftest --plan shows all steps with tiers

**Evidence:**
  - **Code:**
    - `swarm/tools/selftest.py`
  - **Tests:**
    - [bdd] `@AC-SELFTEST-INTROSPECTABLE`

### `selftest.individual_steps`

**Status:** **implemented**

Run individual selftest steps with --step flag

**Evidence:**
  - **Code:**
    - `swarm/tools/selftest.py`
  - **Tests:**
    - [bdd] `@AC-SELFTEST-INDIVIDUAL-STEPS`

### `selftest.degraded_mode`

**Status:** **implemented**

Degraded mode treats OPTIONAL failures as warnings

**Evidence:**
  - **Code:**
    - `swarm/tools/selftest.py`
  - **Tests:**
    - [bdd] `@AC-SELFTEST-DEGRADED`

### `selftest.governance_tiers`

**Status:** **implemented**

KERNEL, GOVERNANCE, OPTIONAL tiers with different blocking behavior

**Evidence:**
  - **Code:**
    - `swarm/tools/selftest.py`
  - **Tests:**
    - [unit] `tests/test_selftest_core_cli.py`

---

## Flow_Studio

*Flow visualization and developer experience*

| Capability | Status | Summary |
|------------|--------|---------|
| `flow_studio.sdk_api` | implemented | window.__flowStudio SDK for programmatic control |
| `flow_studio.uiid_selectors` | implemented | data-uiid selectors for stable test automation |
| `flow_studio.profile_management` | implemented | Save, load, diff flow profiles |
| `flow_studio.fastapi_backend` | implemented | FastAPI backend for run management and status |

### `flow_studio.sdk_api`

**Status:** **implemented**

window.__flowStudio SDK for programmatic control

**Evidence:**
  - **Code:**
    - `swarm/tools/flow_studio_ui/flow_studio_sdk.ts`
  - **Tests:**
    - [unit] `tests/test_flow_studio_sdk_path.py`

### `flow_studio.uiid_selectors`

**Status:** **implemented**

data-uiid selectors for stable test automation

**Evidence:**
  - **Code:**
    - `swarm/tools/flow_studio_ui/index.html`
  - **Tests:**
    - [unit] `tests/test_flow_studio_governance.py`

### `flow_studio.profile_management`

**Status:** **implemented**

Save, load, diff flow profiles

**Evidence:**
  - **Code:**
    - `swarm/config/profile_registry.py`
  - **Tests:**
    - [unit] `tests/test_flow_profiles.py`

### `flow_studio.fastapi_backend`

**Status:** **implemented**

FastAPI backend for run management and status

**Evidence:**
  - **Code:**
    - `swarm/tools/flow_studio_api.py`
  - **Tests:**
    - [unit] `tests/test_flow_studio_fastapi_smoke.py`

---

## Quality

*Quality event detection and forensic analysis*

| Capability | Status | Summary |
|------------|--------|---------|
| `quality.diff_scanner` | implemented | Analyze git diffs for change metrics |
| `quality.test_parsing` | supported | Parse pytest output for pass/fail counts |
| `quality.panel_evaluation` | aspirational | Multi-metric panel evaluation (anti-Goodhart) |

### `quality.diff_scanner`

**Status:** **implemented**

Analyze git diffs for change metrics

**Evidence:**
  - **Code:**
    - `swarm/runtime/diff_scanner.py`
  - **Tests:**
    - [unit] `tests/test_diff_scanner.py`

### `quality.test_parsing`

**Status:** *supported*

Parse pytest output for pass/fail counts

> pytest parser implemented; jest parser is stub

**Evidence:**
  - **Code:**
    - `swarm/runtime/forensics/test_parser.py`

### `quality.panel_evaluation`

**Status:** ~aspirational~

Multi-metric panel evaluation (anti-Goodhart)

**Evidence:**
  - **Design:**
    - `.claude/rules/governance/panel-thinking.md`

---

## Spec_Ledger

*Story and acceptance criteria governance*

| Capability | Status | Summary |
|------------|--------|---------|
| `spec_ledger.yaml_format` | implemented | Stories and ACs tracked in specs/spec_ledger.yaml |
| `spec_ledger.bdd_cross_refs` | implemented | BDD scenarios tagged with AC IDs (@AC-*) |

### `spec_ledger.yaml_format`

**Status:** **implemented**

Stories and ACs tracked in specs/spec_ledger.yaml

**Evidence:**
  - **Code:**
    - `specs/spec_ledger.yaml`
  - **Tests:**
    - [bdd] `@AC-SPEC-LEDGER-EXISTS`

### `spec_ledger.bdd_cross_refs`

**Status:** **implemented**

BDD scenarios tagged with AC IDs (@AC-*)

**Evidence:**
  - **Code:**
    - `features/selftest.feature`
  - **Tests:**
    - [unit] `tests/test_selftest_ac_bijection.py`

---

## Statistics

- **Total capabilities:** 42
- **Implemented:** 39
- **Supported:** 2
- **Aspirational:** 1

---

*Generated: 2026-01-11T15:03:46.697245+00:00*
