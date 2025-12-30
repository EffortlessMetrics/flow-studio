# Changelog

All notable changes to the Flow Studio project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

---

## [2.3.0] - 2025-12-09

### Added

#### Stepwise Execution Engine
- **Two Backend Engines**: `gemini-step-orchestrator` and `claude-step-orchestrator` for per-step LLM execution
- **Three Execution Modes**: `stub` (zero-cost CI/demos), `cli` (Claude Code/GLM Coding Plan/Gemini CLI), `sdk` (Anthropic Agent API)
- **Step-Level Observability**: Per-step transcripts (`llm/*.jsonl`) and receipts (`receipts/*.json`)
- **Context Handoff Architecture**: Previous step outputs included in subsequent step prompts
- **Teaching Notes Integration**: Flow YAML `teaching_notes` appear in step prompts (inputs/outputs/emphasizes/constraints)
- **Microloop Routing**: Build flow test/code loops with VERIFIED/UNVERIFIED status-based routing
- **Comprehensive Documentation**: `docs/STEPWISE_BACKENDS.md` with architecture, contracts, and troubleshooting

#### Golden Examples (7 total)
- `stepwise-gemini/` — Signal + Plan flows (events-only model)
- `stepwise-claude/` — Signal + Plan flows (rich transcripts + receipts)
- `stepwise-build-gemini/` — Signal + Plan + Build flows
- `stepwise-build-claude/` — Signal + Plan + Build flows
- `stepwise-gate-claude/` — Through Gate flow (4 flows)
- `stepwise-deploy-claude/` — Through Deploy flow (5 flows)
- `stepwise-sdlc-claude/` — Complete 7-flow SDLC with all transcripts and receipts

#### Testing & Contracts
- Contract tests: `test_step_prompt_teaching_notes.py`, `test_build_stepwise_routing.py`, `test_step_engine_contract.py`
- Backend tests: `test_gemini_stepwise_backend.py`, `test_claude_stepwise_backend.py`
- Example validation: `test_stepwise_build_examples.py`, `test_stepwise_deploy_wisdom_examples.py`

### Changed
- README.md now includes "Stepwise SDLC Quick Reference" with three personas
- Flow Studio displays stepwise runs with per-step event boundaries
- `make stepwise-help` shows all stepwise-related targets

### Documentation
- **Governed Surfaces documentation**: Flow Studio SDK contract and UIID selectors now documented
- **Operator Pack section**: INDEX.md now has quick reference for runbooks, Flow Studio, and validation
- **Sanity Check section**: README.md now has 10-minute health check entry point

---

## Flow Studio Milestones

These tags track Flow Studio-specific releases on a separate versioning track:

### v0.5.0-flowstudio — 2025-12-07
- **Layout Spec**: `layout_spec.ts` defines all screens, regions, and UIIDs as code
- **SDK Layout Methods**: `getLayoutScreens()`, `getLayoutScreenById()`, `getAllKnownUIIDs()`
- **FastAPI Layout Endpoint**: `/api/layout_screens` exposes screen definitions
- **UX Manifest**: `ux_manifest.json` binds layout spec, docs, and tests together
- **UX MCP Servers**: `ux_spec`, `ux_review`, `ux_repo` for agent-driven UX review
- **UX Agents**: `ux-critic` and `ux-implementer` agents for structured UX feedback loops
- **UX Orchestrator**: `ux_orchestrator.py` generates review prompts per screen
- **Layout Review Runner**: `run_layout_review.py` captures DOM/state snapshots per screen
- **UI Layout Review Runbook**: `swarm/runbooks/ui-layout-review.md` documents the workflow

### v0.4.1-flowstudio — 2025-12-06
- **Accessibility (a11y)**: Full keyboard navigation, ARIA landmarks, skip links
- **SDK Contract Tests**: `test_flow_studio_sdk_path.py` validates `window.__flowStudio` shape
- **CLAUDE Router**: CLAUDE.md now directs humans and agents to correct entry points
- **Governed Surfaces**: Documented SDK, UIIDs, and `data-ui-ready` states

### v0.4.0-flowstudio — 2025-12-05
- **TypeScript Migration**: Flow Studio UI fully typed (`domain.ts`, `*.ts` modules)
- **Runbooks**: `10min-health-check.md`, `selftest-flowstudio-fastpath.md`
- **Validation UX**: Flow Studio shows FR badge status, governance overlay
- **UIID System**: `data-uiid` selectors for stable test automation

---

## [2.2.0] - 2025-12-02

### Added
- **FastAPI Backend**: Flow Studio now runs exclusively on FastAPI for improved performance and async support
- **Flask Quarantine Tests**: 12 comprehensive tests prevent Flask re-introduction (`tests/test_no_flask_in_runtime.py`)
- **OpenAPI Schema Validation**: 14 tests validate API contract stability and structure
- **Prometheus Metrics**: Ephemeral port support to prevent address-in-use conflicts

### Changed
- **Flow Studio backend unification**: Deprecated Flask backend in favor of FastAPI
- **Makefile**: Single `make flow-studio` target now invokes FastAPI backend; added OpenAPI schema management targets
- **Selftest**: Updated to validate FastAPI-only configuration; flowstudio-smoke now uses configurable ports
- **Backwards compatibility**: API surface unchanged; existing integrations continue to work
- **Documentation**: Enhanced API contract documentation with OpenAPI schema baseline

### Deprecated
- **Flask backend**: Legacy Flask implementation archived under `swarm/tools/_archive/flow_studio_flask_legacy.py`

### Fixed
- **Port conflicts**: Prometheus metrics server now supports ephemeral ports via environment variables
- **Test guards**: Flask guard test now detects `Flask(__name__)`, `@app.route`, and `Blueprint` patterns comprehensively

---

## [2.1.1] - 2025-12-01

### Added
- **Golden Runs documentation**: `docs/GOLDEN_RUNS.md` with curated example runs for teaching and validation
- **Validation tests**: BDD tests for governance failure logging and degradation tracking
- **Flow Studio keyboard shortcuts**: Press `?` in Flow Studio to see available navigation shortcuts
- **selftest-core adoption guide**: Step-by-step guide for integrating the reusable selftest package

### Fixed
- **Centralized selftest_degradations.log path**: All degradation logging now writes to a consistent location
- **BDD test for governance failures**: Ensures degradation events are properly captured and logged

### Changed
- **README designates repo as "canonical governed specimen"**: Clarifies the purpose and stability guarantee of this repo
- **Status banner added to README**: Quick visibility into release status

## [2.1.0] - 2025-12-01

### Added

#### Auto-Remediation & Safety (P4.1)
- **Auto-Remediation Executor**: Allowlist/blocklist safety controls, dry-run preview, CLI approval workflow
- **Audit Logging**: Full traceability for all remediation actions
- **35 Safety Tests**: Comprehensive coverage of safety boundaries and edge cases

#### Testing & Quality (P4.2, P4.3, P4.7)
- **BDD Datatable Fixtures**: 3 previously-skipped tests now pass with proper fixture support
- **Observability Backend Strict Mode**: RuntimeError raised when strict_mode=True and backend unavailable
- **API Performance Benchmarks**: 8 benchmark tests via pytest-benchmark for regression detection

#### Runbook Automation (P4.4)
- **GitHub Actions Workflow**: Auto-diagnostics triggered on gate failure
- **Incident Pack Generation**: Automated diagnostic bundle creation on CI failure
- **Remediation Suggestions**: AI-assisted fix hints integrated into workflow
- **Artifact Upload**: Diagnostic packs uploaded as workflow artifacts
- **37 Integration Tests**: Full coverage of runbook automation scenarios

#### Native Observability Plugins (P4.6)
- **Prometheus Recording Rules**: `recording_rules.yaml` with 14 pre-aggregated metrics
- **Prometheus Alert Rules**: `alert_rules.yaml` with 12 production-ready alerts
- **Kubernetes ServiceMonitor**: `service_monitor.yaml` for k8s-native scraping
- **Install Automation**: Script for deploying observability plugins to clusters
- **33+ Tests**: Coverage for rule syntax, alert thresholds, and k8s manifests

#### Flow Studio UX Polish (P4.5)
- **Enhanced /api/health**: Returns version, timestamp, selftest_status in response
- **Improved 404 Responses**: Includes available_flows hints for better developer UX
- **Backend Parity**: Flask and FastAPI backends now return identical response structures

#### Distributed Execution (P5.1)
- **Distributed Selftest Execution**: ProcessPoolExecutor-based parallel step execution
- **EXECUTION_WAVES Config**: Define parallelizable step groups in configuration
- **CLI Flags**: `--distributed` and `--workers` flags for runtime control
- **Make Target**: `make selftest-distributed` for easy parallel runs
- **1.3x Speedup**: Observed performance improvement on multi-core systems
- **14 Tests**: Coverage for distribution logic, wave ordering, and worker management

#### Cross-Repo Reusability (P5.2)
- **selftest-core Package**: `packages/selftest-core/` with reusable components
- **SelfTestRunner**: Core execution engine extracted for reuse
- **Config Module**: YAML-based step configuration for customization
- **Doctor Module**: Diagnostic tooling for troubleshooting
- **Reporter Module**: Pluggable output formatting
- **CLI Tool**: Standalone `selftest-core` with run/doctor/version commands
- **60 Tests**: Comprehensive coverage of the reusable package

### Changed
- Selftest now includes safety automation and distributed execution capabilities
- Observability backends support strict mode for production environments
- Flow Studio API includes version and health metadata in responses
- Test suite expanded from 155+ to 240+ tests

### Fixed
- Flow Studio 404 responses now provide actionable guidance
- Observability backend fallback behavior in strict mode

## [2.0.0] - 2025-12-01

### Added

#### Metrics & Observability
- **Metrics Emission**: Full Prometheus/Datadog/CloudWatch integration via `selftest_metrics.py`
- **Multi-backend Support**: Configuration-driven backends in `observability_backends.yaml`
- **10-panel Grafana Dashboard**: Success rate, failure distribution, duration, degradations, heatmaps
- **3 SLOs with Error Budgets**: Availability (99%), Performance (P95 ≤ 120s), Degradation limits

#### Alerts & Incident Response
- **8 Alert Policies**: 3 page-severity, 4 ticket-severity, 1 info-severity with multi-channel routing
- **Incident Pack Tool**: `make selftest-incident-pack` generates diagnostic bundles for escalation
- **Remediation Suggestions**: `make selftest-suggest-remediation` provides AI-assisted fix hints

#### Developer Experience
- **5 New Make Targets**:
  - `make selftest-fast` (~400ms) - KERNEL only, inner-loop iteration
  - `make selftest-govern` (~30s) - GOVERNANCE only, config/docs changes
  - `make selftest` (~120s) - Full 10 steps, before push
  - `make selftest-incident-pack` (~5s) - Gather diagnostics
  - `make selftest-suggest-remediation` (~2s) - Get fix suggestions
- **PR Template**: Selftest impact checklist for routine/config/test changes
- **Developer Workflow Doc**: Step-by-step guide at `docs/SELFTEST_DEVELOPER_WORKFLOW.md`

#### Org Governance
- **Branch Protection Guide**: `docs/BRANCH_PROTECTION_SETUP.md` for GitHub admins
- **Ownership Documentation**: Escalation procedures and decision log
- **Remediation Map**: 8 safe, low-ambiguity fix patterns

#### Testing
- **155+ tests passing**: 19 metrics, 18 remediation, 18 backend tests + existing suite
- **Test Coverage**: 96% pass rate (97/108 executable tests)

### Changed
- Selftest system upgraded from working implementation to fully operationalized platform
- Metrics emitted at all execution points (run start/end, step completion/failure)
- Documentation expanded by 50+ KB covering workflows, setup, troubleshooting

### Fixed
- BDD step definition discovery (14 tests fixed, 78% improvement)
- Degradation log parsing in test fixtures
- JSON output handling in acceptance tests

## [1.5.0] - 2025-11-30

### Added
- Initial selftest implementation with 10-step governance validation
- KERNEL/GOVERNANCE/OPTIONAL tier system
- AC matrix tracking and freshness checks
- Basic degradation logging

### Changed
- Validator upgraded to enforce FR-001 through FR-005

---

[Unreleased]: https://github.com/EffortlessMetrics/flow-studio/compare/v2.3.0...HEAD
[2.3.0]: https://github.com/EffortlessMetrics/flow-studio/compare/v2.2.0...v2.3.0
[2.2.0]: https://github.com/EffortlessMetrics/flow-studio/compare/v2.1.1...v2.2.0
[2.1.1]: https://github.com/EffortlessMetrics/flow-studio/compare/v2.1.0...v2.1.1
[2.1.0]: https://github.com/EffortlessMetrics/flow-studio/compare/v2.0.0...v2.1.0
[2.0.0]: https://github.com/EffortlessMetrics/flow-studio/compare/v1.5.0...v2.0.0
[1.5.0]: https://github.com/EffortlessMetrics/flow-studio/releases/tag/v1.5.0
