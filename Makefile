.PHONY: list
list:
	@echo "Available make targets:"
	@grep -E '^[a-zA-Z0-9_-]+:' Makefile | grep -v '^\.PHONY' | cut -d: -f1 | sort | sed 's/^/  - /'

.PHONY: help
help:
	@echo "Flow Studio demo harness — Essential Commands"
	@echo ""
	@echo "Getting started:"
	@echo "  make demo-swarm          # One-command demo: validate, stepwise run, Flow Studio"
	@echo "  make demo-flow-studio    # Quick demo: sync, populate, launch Flow Studio"
	@echo "  make demo-selftest       # Governance introspection demo (selftest + Flow Studio)"
	@echo "  make dev-check           # Full validation (adapters, flows, selftest)"
	@echo "  make demo-run            # Populate example run at swarm/runs/demo-health-check/"
	@echo "  make flow-studio         # Flow visualization at http://localhost:5000"
	@echo ""
	@echo "Validation & testing:"
	@echo "  make test                # Alias for selftest (full swarm selftest)"
	@echo "  make selftest-fast       # Fast KERNEL-only check (~400ms)"
	@echo "  make selftest            # Full swarm selftest (16 steps)"
	@echo ""
	@echo "Pytest test taxonomy (by marks):"
	@echo "  make test-unit           # Unit tests (isolated logic, no I/O)"
	@echo "  make test-integration    # Integration tests (CLI, file I/O)"
	@echo "  make test-slow           # Slow tests (>1s, full subprocess)"
	@echo "  make test-quick          # Quick tests (<100ms, unit + mocks)"
	@echo "  make test-all            # All pytest tests"
	@echo "  make selftest-distributed  # Parallel selftest with wave-based execution"
	@echo "  make selftest-govern     # Governance checks only (no code tests)"
	@echo "  make selftest-doctor     # Diagnose selftest failures"
	@echo "  make selftest-suggest-remediation  # Suggest fixes for degradations"
	@echo "  make selftest-remediate            # Execute remediations with approval"
	@echo "  make selftest-incident-pack        # Generate diagnostic tarball for incidents"
	@echo "  make check-ac-freshness  # Validate AC matrix consistency"
	@echo "  make quick-check         # Validator only (no selftest)"
	@echo "  make ci-validate         # CI gate: fail on validation errors"
	@echo "  make ci-validate-strict  # CI gate: fail on warnings too"
	@echo ""
	@echo "Exit codes: 0 = OK, 1 = validation failed, 2 = fatal error"
	@echo ""
	@echo "Documentation:"
	@echo "  DEMO_RUN.md              # See it work (2 min walkthrough)"
	@echo "  docs/WHY_DEMO_SWARM.md   # Understand the three core ideas"
	@echo "  CLAUDE.md                # Full reference for Claude Code usage"
	@echo "  docs/SELFTEST_SYSTEM.md  # Selftest design & troubleshooting"
	@echo ""
	@echo "Agent & flow ops:"
	@echo "  make agents-help         # Agent configuration workflow"
	@echo "  make flows-help          # Flow commands"
	@echo "  make agents-models       # Show model distribution"
	@echo ""
	@echo "Stepwise backends:"
	@echo "  make demo-run-stepwise   # Demo both stepwise backends"
	@echo "  make stepwise-help       # Stepwise backend help"
	@echo ""
	@echo "Agent SDK:"
	@echo "  make agent-sdk-ts-demo   # Run TypeScript Agent SDK example"
	@echo "  make agent-sdk-py-demo   # Run Python Agent SDK example"
	@echo "  make agent-sdk-help      # Agent SDK documentation"
	@echo ""
	@echo "Maintenance:"
	@echo "  make runs-clean          # Clean stale runs from swarm/runs/"
	@echo "  make wisdom-cycle        # Aggregate wisdom, preview cleanup"
	@echo ""

.PHONY: validate-swarm
validate-swarm:
	uv run swarm/tools/validate_swarm.py

.PHONY: ci-validate
ci-validate:
	./swarm/tools/ci_validate_swarm.sh --fail-on-fail --list-issues

.PHONY: ci-validate-strict
ci-validate-strict:
	./swarm/tools/ci_validate_swarm.sh --fail-on-warn --list-issues

.PHONY: quick-check
quick-check:
	uv run swarm/tools/validate_swarm.py

.PHONY: lint-routing
lint-routing:
	@echo "Checking for deprecated routing field patterns..."
	uv run python swarm/tools/lint_routing_fields.py

.PHONY: lint-routing-strict
lint-routing-strict:
	@echo "Checking for deprecated routing field patterns (strict mode)..."
	uv run python swarm/tools/lint_routing_fields.py --strict

# Operator Spine: the 8 docs every operator should read
SPINE_DOCS = README.md docs/GETTING_STARTED.md CHEATSHEET.md GLOSSARY.md \
             docs/SELFTEST_SYSTEM.md docs/FLOW_STUDIO.md REPO_MAP.md docs/VALIDATION_RULES.md

.PHONY: docs-check
docs-check:
	@echo "Validating documentation structure..."
	@echo "  Checking operator spine (8 key docs)..."
	@for f in $(SPINE_DOCS); do \
		test -f "$$f" || { echo "ERROR: Operator spine doc $$f missing"; exit 1; }; \
	done
	@echo "  ✓ All spine docs exist"
	@echo "  Running structure tests..."
	@uv run pytest tests/test_docs_structure.py -v --tb=short
	@echo "  Checking doc invariants (count references)..."
	@uv run python swarm/tools/doc_invariants_check.py
	@echo "Documentation structure valid"

# Meta documentation generator - updates docs with computed counts
.PHONY: gen-doc-meta
gen-doc-meta:
	@echo "Generating documentation from computed metadata..."
	uv run python swarm/tools/generate_meta_docs.py

.PHONY: gen-doc-meta-check
gen-doc-meta-check:
	@echo "Checking if docs have up-to-date metadata..."
	uv run python swarm/tools/generate_meta_docs.py --check

.PHONY: show-meta
show-meta:
	@echo "Computed swarm metadata:"
	uv run python swarm/meta.py

.PHONY: check-adapters
check-adapters:
	uv run swarm/tools/gen_adapters.py --platform claude --mode check-all

.PHONY: gen-adapters
gen-adapters:
	uv run swarm/tools/gen_adapters.py --platform claude --mode generate-all

.PHONY: test-control-plane
test-control-plane:
	uv run swarm/tools/test_control_plane.py

.PHONY: agents-models
agents-models:
	uv run swarm/tools/list_agent_models.py

.PHONY: agents-help
agents-help:
	@echo "Agent Ops — Quick Reference"
	@echo ""
	@echo "File you edit:"
	@echo "  swarm/config/agents/<key>.yaml    # Source of truth for agent config"
	@echo ""
	@echo "Typical workflow:"
	@echo ""
	@echo "  1. Edit config (model, flows, etc):"
	@echo "     \$$EDITOR swarm/config/agents/<key>.yaml"
	@echo ""
	@echo "  2. Regenerate + verify:"
	@echo "     make gen-adapters"
	@echo "     make check-adapters"
	@echo "     make validate-swarm"
	@echo ""
	@echo "Commands to inspect:"
	@echo ""
	@echo "  make agents-models               # See model distribution (inherit vs pinned)"
	@echo "  uv run swarm/tools/flow_graph.py --format table  # See flows ↔ agents"
	@echo ""
	@echo "Read CLAUDE.md § Agent Ops for more detail."

.PHONY: gen-flows
gen-flows:
	uv run swarm/tools/gen_flows.py

.PHONY: check-flows
check-flows: gen-flows
	@echo "Validating flow definitions and invariants..."
	@uv run swarm/tools/validate_swarm.py --flows-only

# Flow constants generation (TypeScript constants from flow YAML)
# Generates swarm/tools/flow_studio_ui/ts/generated/flowConstants.ts
.PHONY: gen-flow-constants
gen-flow-constants:
	uv run swarm/tools/gen_flow_constants.py

.PHONY: check-flow-constants
check-flow-constants:
	uv run swarm/tools/gen_flow_constants.py --check

# Index HTML generation (assembles index.html from fragments + CSS + JS)
# Fragments are in swarm/tools/flow_studio_ui/fragments/
.PHONY: gen-index-html
gen-index-html:
	@uv run swarm/tools/gen_index_html.py

.PHONY: check-index-html
check-index-html:
	@uv run swarm/tools/gen_index_html.py --check

.PHONY: flow-studio
flow-studio:
	@$(MAKE) gen-index-html
	@$(MAKE) ts-build
	@echo "Starting Flow Studio..."
	@uv run uvicorn swarm.tools.flow_studio_fastapi:app --reload --host 127.0.0.1 --port 5000

# Spec API server - REST API for SpecManager functionality (TypeScript frontend integration)
# Runs on port 5001 by default to avoid conflicting with Flow Studio (port 5000)
.PHONY: spec-api
spec-api:
	@echo "Starting Spec API server on http://127.0.0.1:5001..."
	@uv run uvicorn swarm.api.server:app --host 127.0.0.1 --port 5001

.PHONY: spec-api-reload
spec-api-reload:
	@echo "Starting Spec API server with auto-reload..."
	@uv run uvicorn swarm.api.server:app --reload --host 127.0.0.1 --port 5001

# Combined: Flow Studio UI + Spec API (runs both servers)
# Flow Studio on :5000, Spec API on :5001
.PHONY: flow-studio-full
flow-studio-full:
	@$(MAKE) gen-index-html
	@$(MAKE) ts-build
	@echo "Starting Flow Studio (port 5000) and Spec API (port 5001)..."
	@echo ""
	@echo "  Flow Studio UI:  http://127.0.0.1:5000"
	@echo "  Spec API:        http://127.0.0.1:5001"
	@echo "  API Health:      http://127.0.0.1:5001/api/health"
	@echo "  API Docs:        http://127.0.0.1:5001/docs"
	@echo ""
	@(uv run uvicorn swarm.api.server:app --host 127.0.0.1 --port 5001 &) && \
		uv run uvicorn swarm.tools.flow_studio_fastapi:app --reload --host 127.0.0.1 --port 5000

# Flow Studio smoke test: receipt-backed verification
# Produces artifacts in artifacts/flowstudio_smoke/<timestamp>/
# Port configurable via FLOWSTUDIO_PORT (default: 5000)
.PHONY: flowstudio-smoke
flowstudio-smoke:
	@echo "Running Flow Studio smoke test..."
	@VIRTUAL_ENV= uv run swarm/tools/flowstudio_smoke.py

# Smoke test against existing server (doesn't start/stop server)
.PHONY: flowstudio-smoke-external
flowstudio-smoke-external:
	@echo "Running Flow Studio smoke test against existing server..."
	@VIRTUAL_ENV= FLOWSTUDIO_SKIP_SERVER=1 uv run swarm/tools/flowstudio_smoke.py

# Strict UI assets smoke (POSITIVE): verify server starts with strict preflight enabled
# This catches misconfigurations where STRICT mode is set but the server is broken.
# Does NOT verify that missing files cause failure - use strict-negative for that.
.PHONY: flowstudio-smoke-strict
flowstudio-smoke-strict:
	@echo "Running Flow Studio smoke test with strict UI asset checking (positive)..."
	@VIRTUAL_ENV= FLOW_STUDIO_STRICT_UI_ASSETS=1 uv run swarm/tools/flowstudio_smoke.py

# Strict UI assets smoke (NEGATIVE): verify server FAILS startup when JS is missing
# This is the real guard: proves that strict mode actually protects against silent 404s.
# Temporarily hides main.js and expects startup to fail with a specific error message.
# Uses port 5001 to avoid collisions with running Flow Studio instances.
.PHONY: flowstudio-smoke-strict-negative
flowstudio-smoke-strict-negative:
	@echo "Running Flow Studio strict assets negative test (expect startup failure)..."
	@VIRTUAL_ENV= FLOWSTUDIO_PORT=5001 \
		FLOW_STUDIO_STRICT_UI_ASSETS=1 \
		FLOWSTUDIO_EXPECT_STARTUP_FAIL=1 \
		FLOWSTUDIO_HIDE_UI_ENTRYPOINT=main.js \
		uv run swarm/tools/flowstudio_smoke.py

# Flow Studio TypeScript targets
# Contract A: Compiled JS is committed for "clone → run" reliability.
# TypeScript sources in src/, compiled JS in js/ - checked for drift in CI.
.PHONY: ts-check
ts-check:
	@echo "Type-checking Flow Studio TypeScript..."
	@cd swarm/tools/flow_studio_ui && npm run ts-check --silent

.PHONY: ts-build
ts-build:
	@echo "Building Flow Studio TypeScript..."
	@cd swarm/tools/flow_studio_ui && npm run ts-build --silent
	@echo "✓ TypeScript compiled to js/"

.PHONY: ts-watch
ts-watch:
	@echo "Watching Flow Studio TypeScript for changes..."
	@cd swarm/tools/flow_studio_ui && npx tsc --watch

# UI drift check: ensures compiled JS matches TypeScript source
# Used by CI to enforce that ts-build was run before commit
.PHONY: check-ui-drift
check-ui-drift: ts-build
	@echo "Checking Flow Studio UI drift..."
	@git diff --exit-code -- swarm/tools/flow_studio_ui/js/ || \
		(echo "ERROR: Compiled JS differs from repo. Run 'make ts-build' and commit."; exit 1)
	@if [ -n "$$(git ls-files --others --exclude-standard swarm/tools/flow_studio_ui/js/)" ]; then \
		echo "ERROR: Untracked generated JS detected in swarm/tools/flow_studio_ui/js/"; \
		git ls-files --others --exclude-standard swarm/tools/flow_studio_ui/js/; \
		exit 1; \
	fi
	@echo "✓ Compiled JS matches repo (no drift, no untracked files)"

.PHONY: dump-openapi-schema
dump-openapi-schema:
	@echo "Dumping OpenAPI schema from FastAPI app..."
	@uv run python -c "from swarm.tools.flow_studio_fastapi import app; import json; from pathlib import Path; schema = app.openapi(); out = Path('docs/flowstudio-openapi.json'); out.write_text(json.dumps(schema, indent=2)); print(f'✓ Schema dumped to {out}')"

.PHONY: validate-openapi-schema
validate-openapi-schema:
	@echo "Validating OpenAPI schema against baseline..."
	@uv run pytest tests/test_flow_studio_schema_stability.py -v --tb=short

.PHONY: check-openapi-breaking-changes
check-openapi-breaking-changes:
	@echo "Checking for breaking changes to API contract..."
	@uv run pytest tests/test_flow_studio_schema_stability.py::TestOpenAPISchemaStability::test_required_endpoints_still_documented -v
	@uv run pytest tests/test_flow_studio_schema_stability.py::TestOpenAPISchemaStability::test_endpoint_methods_not_removed -v

.PHONY: diff-openapi-schema
diff-openapi-schema: dump-openapi-schema
	@echo "Comparing current schema against git baseline..."
	@git diff --color-words docs/flowstudio-openapi.json || echo "✓ No changes detected"

.PHONY: flow-studio-docs
flow-studio-docs:
	@echo "Flow Studio OpenAPI documentation:"
	@echo "  Baseline: docs/flowstudio-openapi.json"
	@echo "  Live: http://localhost:5000/docs (Swagger UI)"
	@echo "  Live: http://localhost:5000/redoc (ReDoc)"
	@echo "  Live: http://localhost:5000/openapi.json (raw schema)"
	@echo ""
	@echo "Commands:"
	@echo "  make dump-openapi-schema           # Export current schema"
	@echo "  make validate-openapi-schema       # Test stability"
	@echo "  make check-openapi-breaking-changes # Detect removals"
	@echo "  make diff-openapi-schema           # Show git diff"

.PHONY: flows-help
flows-help:
	uv run swarm/tools/flows_help.py

.PHONY: selftest
selftest:
	@echo "Running full selftest suite (all 16 steps)..."
	uv run swarm/tools/selftest.py

.PHONY: selftest-distributed
selftest-distributed:
	@echo "Running distributed selftest (wave-based parallel execution)..."
	uv run swarm/tools/selftest.py --distributed --workers $(or $(WORKERS),4)

.PHONY: test
test: selftest
	@echo "Note: \`make test\` is an alias for \`make selftest\` in this repo."

# Test taxonomy targets (pytest marks)
.PHONY: test-unit
test-unit:
	@echo "Running unit tests (isolated logic tests, no I/O)..."
	uv run pytest tests/ -m "unit" -v --tb=short

.PHONY: test-integration
test-integration:
	@echo "Running integration tests (CLI, file I/O, subprocess)..."
	uv run pytest tests/ -m "integration" -v --tb=short

.PHONY: test-slow
test-slow:
	@echo "Running slow tests (>1s, full subprocess, extensive I/O)..."
	uv run pytest tests/ -m "slow" -v --tb=short

.PHONY: test-quick
test-quick:
	@echo "Running quick tests (<100ms, unit + mocks only)..."
	uv run pytest tests/ -m "quick or unit" -v --tb=short

.PHONY: test-all
test-all:
	@echo "Running all pytest tests..."
	uv run pytest tests/ -v --tb=short

.PHONY: test-performance
test-performance:
	@echo "Running performance benchmark tests (non-gating)..."
	uv run pytest tests/ -m "performance" -v --tb=short --benchmark-enable

.PHONY: test-gating
test-gating:
	@echo "Running gating tests (excludes performance)..."
	uv run pytest tests/ -m "not performance" -v --tb=short

.PHONY: test-ci-smoke
test-ci-smoke:
	@echo "Running CI smoke tests (fast validation + core FastAPI tests)..."
	uv run pytest -v --tb=short --color=yes \
		tests/test_flow_studio_fastapi_smoke.py \
		tests/test_flow_studio_governance.py \
		tests/test_flow_studio_fastapi_only.py \
		tests/test_validate_swarm_json.py \
		tests/test_bijection.py \
		tests/test_frontmatter.py

.PHONY: selftest-fast
selftest-fast:
	@echo "Running fast kernel-only check (~400ms)..."
	uv run swarm/tools/kernel_smoke.py

.PHONY: selftest-govern
selftest-govern:
	@echo "Running governance checks (AC matrix, config, no code tests)..."
	@uv run swarm/tools/selftest.py --until graph-invariants

.PHONY: selftest-plan
selftest-plan:
	uv run swarm/tools/selftest.py --plan

.PHONY: selftest-degraded
selftest-degraded:
	uv run swarm/tools/selftest.py --degraded

.PHONY: selftest-step
selftest-step:
	@if [ -z "$(STEP)" ]; then \
		echo "Usage: make selftest-step STEP=<step-id>"; \
		echo "Available steps:"; \
		uv run swarm/tools/selftest.py --list; \
		exit 1; \
	fi
	uv run swarm/tools/selftest.py --step $(STEP)

.PHONY: kernel-smoke
kernel-smoke:
	@echo "Running kernel smoke check (KERNEL tier only)..."
	uv run swarm/tools/kernel_smoke.py

.PHONY: selftest-bdd
selftest-bdd:
	@echo "Running executable BDD scenarios (selftest golden paths)…"
	uv run pytest tests/test_selftest_bdd.py -m executable -v

.PHONY: selftest-degradations
selftest-degradations:
	@echo "Showing selftest degradation log (failures in degraded mode)…"
	@uv run swarm/tools/show_selftest_degradations.py

.PHONY: check-platform-status
check-platform-status:
	@curl -s http://localhost:5000/platform/status | jq .

.PHONY: gen-flows-index
gen-flows-index:
	uv run swarm/tools/gen_flows_index.py

.PHONY: check-flows-index
check-flows-index:
	@echo "Checking if FLOWS_INDEX.md is up-to-date..."
	uv run swarm/tools/gen_flows_index.py --check

.PHONY: selftest-doctor
selftest-doctor:
	uv run swarm/tools/selftest_doctor.py

.PHONY: check-ac-freshness
check-ac-freshness:
	uv run swarm/tools/check_selftest_ac_freshness.py

.PHONY: check-ac-freshness-verbose
check-ac-freshness-verbose:
	uv run swarm/tools/check_selftest_ac_freshness.py --verbose

.PHONY: selftest-suggest-remediation
selftest-suggest-remediation:
	uv run swarm/tools/selftest_suggest_remediation.py

.PHONY: selftest-suggest-remediation-json
selftest-suggest-remediation-json:
	uv run swarm/tools/selftest_suggest_remediation.py --json

.PHONY: selftest-remediate
selftest-remediate:
	uv run swarm/tools/selftest_remediate_execute.py

.PHONY: selftest-remediate-dry-run
selftest-remediate-dry-run:
	uv run swarm/tools/selftest_remediate_execute.py --dry-run

.PHONY: selftest-incident-pack
selftest-incident-pack:
	uv run swarm/tools/selftest_incident_pack.py

# Runbook automation targets (P4.4)
.PHONY: selftest-diagnose-remote
selftest-diagnose-remote:
	@echo "Triggering remote diagnostics workflow via GitHub Actions..."
	gh workflow run selftest-auto-diagnostics.yml
	@echo ""
	@echo "Workflow triggered. View status at:"
	@echo "  https://github.com/$$(gh repo view --json nameWithOwner -q .nameWithOwner)/actions/workflows/selftest-auto-diagnostics.yml"

.PHONY: selftest-diagnose-remote-wait
selftest-diagnose-remote-wait:
	@echo "Triggering remote diagnostics workflow and waiting for completion..."
	gh workflow run selftest-auto-diagnostics.yml
	@sleep 5
	@RUN_ID=$$(gh run list --workflow=selftest-auto-diagnostics.yml --limit=1 --json databaseId -q '.[0].databaseId'); \
	echo "Waiting for run $$RUN_ID..."; \
	gh run watch $$RUN_ID

.PHONY: runbook-config-check
runbook-config-check:
	@echo "Checking runbook automation configuration..."
	uv run swarm/tools/runbook_config.py

.PHONY: override-create
override-create:
	@if [ -z "$(STEP)" ] || [ -z "$(REASON)" ] || [ -z "$(APPROVER)" ]; then \
		echo "Usage: make override-create STEP=<step_id> REASON='<reason>' APPROVER=<name>"; \
		exit 1; \
	fi
	uv run swarm/tools/override_manager.py create "$(STEP)" "$(REASON)" "$(APPROVER)"

.PHONY: override-revoke
override-revoke:
	@if [ -z "$(STEP)" ]; then \
		echo "Usage: make override-revoke STEP=<step_id>"; \
		exit 1; \
	fi
	uv run swarm/tools/override_manager.py revoke "$(STEP)"

.PHONY: override-list
override-list:
	uv run swarm/tools/override_manager.py list

# ============================================================================
# Runs cleanup
# ============================================================================

.PHONY: runs-clean
runs-clean:
	@echo "Cleaning ephemeral runs under swarm/runs/..."
	@rm -rf swarm/runs/run-*
	@echo "✓ Cleaned run-* directories."
	@echo ""
	@echo "Note: Golden examples (demo-health-check, stepwise-stub) are preserved."
	@echo "      To regenerate: make demo-run or make stepwise-sdlc-stub"

.PHONY: runs-list
runs-list:
	@uv run swarm/tools/runs_gc.py list

.PHONY: runs-list-v
runs-list-v:
	@uv run swarm/tools/runs_gc.py list -v

.PHONY: runs-prune
runs-prune:
	@uv run swarm/tools/runs_gc.py prune

.PHONY: runs-prune-dry
runs-prune-dry:
	@uv run swarm/tools/runs_gc.py prune --dry-run

.PHONY: runs-quarantine
runs-quarantine:
	@uv run swarm/tools/runs_gc.py quarantine

.PHONY: runs-quarantine-dry
runs-quarantine-dry:
	@uv run swarm/tools/runs_gc.py quarantine --dry-run

.PHONY: runs-gc-help
runs-gc-help:
	@echo "Runs Garbage Collection Commands"
	@echo "================================="
	@echo ""
	@echo "  make runs-list          Show run statistics and retention eligibility"
	@echo "  make runs-list-v        Verbose: show individual runs with age/size"
	@echo "  make runs-prune-dry     Preview what would be deleted (dry run)"
	@echo "  make runs-prune         Apply retention policy and delete old runs"
	@echo "  make runs-quarantine-dry Preview corrupt runs to quarantine"
	@echo "  make runs-quarantine    Move corrupt runs to swarm/runs/_corrupt/"
	@echo "  make runs-clean         Nuclear option: rm -rf run-* (preserves examples)"
	@echo ""
	@echo "Configuration: swarm/config/runs_retention.yaml"
	@echo "  - retention_days: 30 (default)"
	@echo "  - max_count: 300"
	@echo "  - preserved prefixes: demo-, stepwise-, golden-"
	@echo ""
	@echo "Environment overrides:"
	@echo "  SWARM_RUNS_RETENTION_DAYS=N  Override retention days"
	@echo "  SWARM_RUNS_MAX_COUNT=N       Override max run count"
	@echo "  SWARM_RUNS_DRY_RUN=1         Force dry-run mode"

# ============================================================================
# Wisdom Tools
# ============================================================================

.PHONY: wisdom-summary
wisdom-summary:
	@if [ -z "$(RUN_ID)" ]; then \
		echo "Usage: make wisdom-summary RUN_ID=<run-id>"; \
		echo ""; \
		echo "Creates wisdom_summary.json for a specific run."; \
		exit 1; \
	fi
	@uv run swarm/tools/wisdom_summarizer.py "$(RUN_ID)"

.PHONY: wisdom-aggregate
wisdom-aggregate:
	@uv run swarm/tools/wisdom_aggregate_runs.py

.PHONY: wisdom-report
wisdom-report:
	@uv run swarm/tools/wisdom_aggregate_runs.py --markdown

.PHONY: wisdom-cycle
wisdom-cycle:
	@echo "Running wisdom lifecycle cycle..."
	@echo ""
	@if [ -z "$(RUN_ID)" ]; then \
		echo "Step 1: Aggregating wisdom from all existing runs..."; \
		uv run swarm/tools/wisdom_aggregate_runs.py --markdown > wisdom_report.md; \
		echo "✓ Generated wisdom_report.md"; \
	else \
		echo "Step 1: Generating wisdom summary for run $(RUN_ID)..."; \
		uv run swarm/tools/wisdom_summarizer.py "$(RUN_ID)"; \
		echo "✓ Generated wisdom_summary.json for $(RUN_ID)"; \
		echo ""; \
		echo "Step 2: Aggregating across all runs..."; \
		uv run swarm/tools/wisdom_aggregate_runs.py --markdown > wisdom_report.md; \
		echo "✓ Generated wisdom_report.md"; \
	fi
	@echo ""
	@echo "Step 3: Preview runs eligible for cleanup..."
	@uv run swarm/tools/runs_gc.py prune --dry-run 2>/dev/null || echo "(no runs to prune)"
	@echo ""
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo "  WISDOM CYCLE COMPLETE"
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo ""
	@echo "  Review: wisdom_report.md"
	@echo "  Cleanup: make runs-prune (if dry-run looks safe)"
	@echo ""

.PHONY: wisdom-examples
wisdom-examples:
	@echo "Generating wisdom summaries for all examples..."
	@count=0; \
	for example in swarm/examples/*/; do \
		example_id=$$(basename "$$example"); \
		if [ -d "$$example" ]; then \
			echo "  Processing: $$example_id"; \
			uv run swarm/tools/wisdom_summarizer.py "$$example_id" --output quiet 2>/dev/null && count=$$((count + 1)) || true; \
		fi; \
	done; \
	echo ""; \
	echo "✓ Wisdom summaries updated"; \
	echo ""; \
	echo "Summary:"; \
	find swarm/examples -name "wisdom_summary.json" 2>/dev/null | wc -l | xargs printf "  %s examples have wisdom_summary.json\n"

.PHONY: demo-run
demo-run:
	@echo "Populating demo run from health-check example…"
	@rm -rf swarm/runs/demo-health-check
	@mkdir -p swarm/runs
	@cp -r swarm/examples/health-check swarm/runs/demo-health-check
	@echo ""
	@echo "✓ Demo run created at swarm/runs/demo-health-check/"
	@echo ""
	@echo "Next steps:"
	@echo "  - Explore artifacts: ls -R swarm/runs/demo-health-check/"
	@echo "  - View in Flow Studio: make flow-studio → http://localhost:5000"
	@echo "  - Read the guide: DEMO_RUN.md"

.PHONY: demo-flow-studio
demo-flow-studio:
	@echo "Setting up demo swarm with Flow Studio…"
	@echo ""
	@echo "Step 1: Syncing dependencies…"
	@uv sync --extra dev > /dev/null 2>&1
	@echo "✓ Dependencies synced"
	@echo ""
	@echo "Step 2: Populating demo run from health-check example…"
	@$(MAKE) demo-run > /dev/null 2>&1
	@echo "✓ Demo run populated"
	@echo ""
	@echo "Step 3: Starting Flow Studio…"
	@echo ""
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo "  DEMO LINKS (use during presentation):"
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo ""
	@echo "  📊 Baseline flow:"
	@echo "     http://localhost:5000/?run=demo-health-check&mode=operator&tab=artifacts"
	@echo ""
	@echo "  ⚙️  Governance status:"
	@echo "     http://localhost:5000/?run=demo-health-check&tab=validation"
	@echo ""
	@echo "  🔄 Complete walkthrough:"
	@echo "     http://localhost:5000/?mode=operator"
	@echo ""
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo ""
	@$(MAKE) flow-studio

# demo-swarm: Single-command full demo with validation and stepwise execution
# For new developers: "just run this" gives them the right run, URL, and mental model
.PHONY: demo-swarm
demo-swarm:
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo "  DEMO SWARM — Full Orchestrated Demo"
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo ""
	@echo "Step 1: Running validation (dev-check)…"
	@$(MAKE) dev-check 2>&1 | tail -10
	@echo "✓ Validation passed"
	@echo ""
	@echo "Step 2: Previewing run cleanup…"
	@$(MAKE) runs-prune-dry 2>&1 | tail -5 || echo "  (no stale runs)"
	@echo ""
	@echo "Step 3: Running stepwise SDLC stub demo…"
	@$(MAKE) stepwise-sdlc-stub 2>&1 | tail -10
	@echo "✓ Stepwise demo run created"
	@echo ""
	@echo "Step 4: Starting Flow Studio…"
	@echo ""
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo "  DEMO READY — Open in browser:"
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo ""
	@echo "  http://localhost:5000/?run=stepwise-stub&mode=operator"
	@echo ""
	@echo "  Other views:"
	@echo "    • Stepwise events:  http://localhost:5000/?run=stepwise-stub&tab=events"
	@echo "    • Governance:       http://localhost:5000/?tab=validation"
	@echo "    • All examples:     http://localhost:5000/?mode=operator"
	@echo ""
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo ""
	@$(MAKE) flow-studio

.PHONY: demo-selftest
demo-selftest:
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo "  SELFTEST INTROSPECTION DEMO"
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo ""
	@echo "Step 1: Showing selftest plan (introspectable):"
	@echo ""
	@uv run swarm/tools/selftest.py --plan | head -30
	@echo ""
	@echo "┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈"
	@echo ""
	@echo "Step 2: Running full selftest with verbose output…"
	@echo ""
	@uv run swarm/tools/selftest.py --verbose 2>&1 | tail -30
	@echo ""
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo "  SELFTEST DEMO LINKS (use during presentation):"
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo ""
	@echo "  🔍 Detailed step breakdown:"
	@echo "     http://localhost:5000/?tab=validation&mode=governance"
	@echo ""
	@echo "  📋 Selftest plan (static view):"
	@echo "     uv run swarm/tools/selftest.py --plan"
	@echo ""
	@echo "  🚀 Individual step debugging:"
	@echo "     uv run swarm/tools/selftest.py --step core-checks"
	@echo ""
	@echo "  📊 Full Flow Studio:"
	@echo "     http://localhost:5000/?mode=operator"
	@echo ""
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo ""
	@echo "Starting Flow Studio…"
	@echo ""
	@$(MAKE) flow-studio

# ============================================================================
# Stepwise Demo Targets
# ============================================================================

.PHONY: demo-run-gemini-stepwise
demo-run-gemini-stepwise:
	@echo "Running stepwise demo with Gemini backend (stub mode)..."
	@SWARM_GEMINI_STUB=1 uv run swarm/tools/demo_stepwise_run.py \
		--backend gemini-step-orchestrator \
		--flows signal,plan

.PHONY: demo-run-claude-stepwise
demo-run-claude-stepwise:
	@echo "Running stepwise demo with Claude backend (stub mode)..."
	@uv run swarm/tools/demo_stepwise_run.py \
		--backend claude-step-orchestrator \
		--flows signal,plan

.PHONY: demo-run-stepwise
demo-run-stepwise: demo-run-gemini-stepwise demo-run-claude-stepwise
	@echo ""
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo "  STEPWISE DEMOS COMPLETE"
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo ""
	@echo "  View runs in Flow Studio:"
	@echo "    make flow-studio -> http://localhost:5000"
	@echo ""

.PHONY: stepwise-help
stepwise-help:
	@echo "Stepwise Backend Targets"
	@echo "========================"
	@echo ""
	@echo "Basic demos (signal + plan flows):"
	@echo "  make demo-run-gemini-stepwise  Run demo with Gemini stepwise backend"
	@echo "  make demo-run-claude-stepwise  Run demo with Claude stepwise backend"
	@echo "  make demo-run-stepwise         Run both stepwise demos"
	@echo ""
	@echo "Full SDLC demos (signal + plan + build flows):"
	@echo "  make stepwise-sdlc-gemini      Gemini stepwise (stub mode)"
	@echo "  make stepwise-sdlc-claude-cli  Claude CLI stepwise"
	@echo "  make stepwise-sdlc-claude-sdk  Claude Agent SDK stepwise"
	@echo ""
	@echo "Documentation:"
	@echo "  docs/STEPWISE_BACKENDS.md"
	@echo ""

# ============================================================================
# Stepwise SDLC Targets (Signal + Plan + Build)
# ============================================================================

.PHONY: stepwise-sdlc-gemini
stepwise-sdlc-gemini:
	@echo "Running full SDLC stepwise with Gemini backend (stub mode)..."
	@echo "Flows: signal -> plan -> build"
	@echo ""
	@SWARM_GEMINI_STUB=1 uv run swarm/tools/demo_stepwise_run.py \
		--backend gemini-step-orchestrator \
		--flows signal,plan,build
	@echo ""
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo "  STEPWISE SDLC COMPLETE (Gemini)"
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo "  View in Flow Studio: make flow-studio"
	@echo ""

.PHONY: stepwise-sdlc-claude-cli
stepwise-sdlc-claude-cli:
	@echo "Running full SDLC stepwise with Claude CLI backend..."
	@echo "Flows: signal -> plan -> build"
	@echo ""
	@SWARM_CLAUDE_STEP_ENGINE_MODE=cli uv run swarm/tools/demo_stepwise_run.py \
		--backend claude-step-orchestrator \
		--mode cli \
		--flows signal,plan,build
	@echo ""
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo "  STEPWISE SDLC COMPLETE (Claude CLI)"
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo "  View in Flow Studio: make flow-studio"
	@echo ""

.PHONY: stepwise-sdlc-claude-sdk
stepwise-sdlc-claude-sdk:
	@echo "Running full SDLC stepwise with Claude Agent SDK..."
	@echo "Flows: signal -> plan -> build"
	@echo "Note: Uses Claude Code login (Max/Team/Enterprise). No API key needed."
	@echo ""
	@SWARM_CLAUDE_STEP_ENGINE_MODE=sdk uv run swarm/tools/demo_stepwise_run.py \
		--backend claude-step-orchestrator \
		--mode sdk \
		--flows signal,plan,build
	@echo ""
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo "  STEPWISE SDLC COMPLETE (Claude SDK)"
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo "  View in Flow Studio: make flow-studio"
	@echo ""

.PHONY: stepwise-sdlc-stub
stepwise-sdlc-stub:
	@echo "Running full SDLC stepwise in stub mode (both backends)..."
	@echo "Flows: signal -> plan -> build"
	@echo ""
	@$(MAKE) stepwise-sdlc-gemini
	@echo ""
	@SWARM_CLAUDE_STEP_ENGINE_MODE=stub uv run swarm/tools/demo_stepwise_run.py \
		--backend claude-step-orchestrator \
		--mode stub \
		--flows signal,plan,build
	@echo ""
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo "  STEPWISE SDLC STUB DEMOS COMPLETE"
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo "  View in Flow Studio: make flow-studio"
	@echo ""

# ============================================================================
# Agent SDK Examples
# ============================================================================

.PHONY: agent-sdk-ts-demo
agent-sdk-ts-demo:
	@echo "Running TypeScript Agent SDK example..."
	@echo "Note: Requires Claude Code installed and logged in (Max/Team/Enterprise)"
	@echo ""
	@cd examples/agent-sdk-ts && npm install --silent && npm run demo

.PHONY: agent-sdk-py-demo
agent-sdk-py-demo:
	@echo "Running Python Agent SDK example..."
	@echo "Note: Requires Claude Code installed and logged in (Max/Team/Enterprise)"
	@echo ""
	@cd examples/agent-sdk-py && uv run python agent_sdk_demo.py

.PHONY: agent-sdk-help
agent-sdk-help:
	@echo "Agent SDK Examples"
	@echo "=================="
	@echo ""
	@echo "These examples demonstrate the Claude Agent SDK - 'headless Claude Code'"
	@echo "that reuses your Claude login. No separate API key needed for local dev."
	@echo ""
	@echo "  make agent-sdk-ts-demo    Run TypeScript example (examples/agent-sdk-ts/)"
	@echo "  make agent-sdk-py-demo    Run Python example (examples/agent-sdk-py/)"
	@echo ""
	@echo "Prerequisites:"
	@echo "  - Claude Code installed: npm install -g @anthropic-ai/claude-code"
	@echo "  - Logged in: claude auth login"
	@echo ""
	@echo "Documentation:"
	@echo "  docs/AGENT_SDK_INTEGRATION.md"
	@echo ""

# Shared pre-check target for dev-check and dev-check-fast
# Runs all validation before selftest (DRY: single place to maintain)
.PHONY: dev-precheck
dev-precheck:
	@$(MAKE) gen-adapters
	@$(MAKE) gen-flows
	@$(MAKE) gen-flow-constants
	@$(MAKE) gen-index-html
	@$(MAKE) check-adapters
	@$(MAKE) check-flows
	@$(MAKE) check-flow-constants
	@$(MAKE) check-index-html
	@$(MAKE) validate-swarm
	@$(MAKE) ts-check
	@$(MAKE) docs-check
	@echo ""
	@echo "Running acceptance tests..."
	@uv run pytest tests/test_selftest_acceptance.py -q
	@echo ""

.PHONY: dev-check
dev-check:
	@echo "Running full swarm dev check..."
	@$(MAKE) dev-precheck
	@$(MAKE) selftest
	@echo ""
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo "  SWARM CHECKS SUMMARY"
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo ""
	@echo "  ✓ Adapters generated (FR-002, FR-OP-001)"
	@echo "  ✓ Flows generated (FR-003, FR-005)"
	@echo "  ✓ Flow constants generated (TypeScript)"
	@echo "  ✓ Index HTML generated (from fragments)"
	@echo "  ✓ Validator (FR-001..005) PASS"
	@echo "  ✓ TypeScript (Flow Studio UI) PASS"
	@echo "  ✓ Selftest (16 steps: KERNEL + GOVERNANCE + OPTIONAL) PASS"
	@echo "  ✓ Acceptance tests PASS"
	@echo ""
	@echo "  Golden state: ready to develop or merge."
	@echo ""
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo ""
	@echo "Next steps:"
	@echo "  make demo-run         # Populate example artifacts"
	@echo "  make demo-flow-studio # Launch Flow Studio at http://localhost:5000"
	@echo "  docs/GETTING_STARTED.md # Start here (10 min, two lanes)"
	@echo ""

# Fast variant of dev-check that skips flowstudio-smoke for quick iteration
# Use this for inner-loop development; use full dev-check before merge
.PHONY: dev-check-fast
dev-check-fast:
	@echo "Running fast swarm dev check (skipping flowstudio-smoke)..."
	@$(MAKE) dev-precheck
	@SELFTEST_SKIP_STEPS=flowstudio-smoke $(MAKE) selftest
	@echo ""
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo "  SWARM CHECKS SUMMARY (fast mode)"
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo ""
	@echo "  ✓ Adapters generated (FR-002, FR-OP-001)"
	@echo "  ✓ Flows generated (FR-003, FR-005)"
	@echo "  ✓ Flow constants generated (TypeScript)"
	@echo "  ✓ Index HTML generated (from fragments)"
	@echo "  ✓ Validator (FR-001..005) PASS"
	@echo "  ✓ TypeScript (Flow Studio UI) PASS"
	@echo "  ✓ Selftest (flowstudio-smoke skipped for speed) PASS"
	@echo "  ✓ Acceptance tests PASS"
	@echo ""
	@echo "  Note: Run 'make dev-check' for full verification before merge."
	@echo ""
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo ""

.PHONY: release-verify
release-verify:
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo "  RELEASE VERIFICATION (v2.2.0+)"
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo ""
	@echo "Running full swarm dev check..."
	@$(MAKE) dev-check
	@echo ""
	@echo "Validating OpenAPI schema stability..."
	@$(MAKE) validate-openapi-schema
	@echo ""
	@echo "Running Flask quarantine tests..."
	@uv run pytest tests/test_no_flask_in_runtime.py -q
	@echo ""
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo "  RELEASE GATE: PASSED"
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo ""
	@echo "  ✓ FastAPI-only backend: verified"
	@echo "  ✓ OpenAPI baseline: stable"
	@echo "  ✓ Flask quarantine: enforced"
	@echo "  ✓ All gates passed: safe to tag release"
	@echo ""

.PHONY: selftest-core-build
selftest-core-build:
	@echo "Building selftest-core package..."
	cd packages/selftest-core && uv build

.PHONY: whitepaper
whitepaper:
	@echo "Exporting whitepaper..."
	uv run swarm/tools/export_whitepaper.py

# Profile management targets
.PHONY: profile-save
profile-save:
	@if [ -z "$(PROFILE_ID)" ]; then \
		echo "Usage: make profile-save PROFILE_ID=<id> [LABEL='Human Label'] [DESCRIPTION='...']"; \
		echo ""; \
		echo "Saves current swarm configuration as a portable profile."; \
		exit 1; \
	fi
	uv run swarm/tools/profile_save.py "$(PROFILE_ID)" \
		$(if $(LABEL),--label "$(LABEL)",) \
		$(if $(DESCRIPTION),--description "$(DESCRIPTION)",)

.PHONY: profile-load
profile-load:
	@if [ -z "$(PROFILE_ID)" ]; then \
		echo "Usage: make profile-load PROFILE_ID=<id> [DRY_RUN=1] [FORCE=1]"; \
		echo ""; \
		echo "Applies a profile to the current repository."; \
		echo ""; \
		echo "By default, runs with --apply --backup (safe live apply)."; \
		echo "Use DRY_RUN=1 to preview changes without applying."; \
		echo "Use FORCE=1 to skip backup requirement (dangerous)."; \
		echo ""; \
		echo "Available profiles:"; \
		ls -1 swarm/profiles/*.swarm_profile.yaml 2>/dev/null | xargs -I{} basename {} .swarm_profile.yaml | sed 's/^/  - /' || echo "  (none)"; \
		exit 1; \
	fi
	@if [ "$(DRY_RUN)" = "1" ]; then \
		uv run swarm/tools/profile_load.py "$(PROFILE_ID)"; \
	elif [ "$(FORCE)" = "1" ]; then \
		uv run swarm/tools/profile_load.py "$(PROFILE_ID)" --apply --force; \
	else \
		uv run swarm/tools/profile_load.py "$(PROFILE_ID)" --apply --backup; \
	fi

.PHONY: profile-diff
profile-diff:
	@if [ -z "$(PROFILE_A)" ]; then \
		echo "Usage:"; \
		echo "  make profile-diff PROFILE_A=<id> PROFILE_B=<id>   # Compare two profiles"; \
		echo "  make profile-diff PROFILE_A=<id> CURRENT=1        # Compare profile to current state"; \
		exit 1; \
	fi
	uv run swarm/tools/profile_diff.py "$(PROFILE_A)" \
		$(if $(PROFILE_B),"$(PROFILE_B)",) \
		$(if $(filter 1,$(CURRENT)),--current,)

.PHONY: profile-list
profile-list:
	@echo "Available swarm profiles:"
	@ls -1 swarm/profiles/*.swarm_profile.yaml 2>/dev/null | while read f; do \
		id=$$(basename "$$f" .swarm_profile.yaml); \
		label=$$(grep -A1 "^meta:" "$$f" 2>/dev/null | grep "label:" | sed 's/.*label: *"\?\([^"]*\)"\?/\1/' || echo ""); \
		printf "  %-20s %s\n" "$$id" "$$label"; \
	done || echo "  (no profiles found)"
	@echo ""
	@echo "Commands:"
	@echo "  make profile-save PROFILE_ID=<id>     # Save current config as profile"
	@echo "  make profile-load PROFILE_ID=<id>     # Apply a profile"
	@echo "  make profile-diff PROFILE_A=<a> ...   # Compare profiles"

.PHONY: profiles-help
profiles-help:
	@echo "Profile Management — Quick Reference"
	@echo ""
	@echo "A profile is a portable snapshot of your swarm configuration"
	@echo "(flows, agents) that you can save, share, compare, and apply."
	@echo ""
	@echo "Commands:"
	@echo "  make profile-list                          # List available profiles"
	@echo "  make profile-save PROFILE_ID=my-swarm      # Save current config"
	@echo "  make profile-load PROFILE_ID=baseline      # Apply a profile"
	@echo "  make profile-diff PROFILE_A=a PROFILE_B=b  # Compare two profiles"
	@echo "  make profile-diff PROFILE_A=a CURRENT=1    # Compare to current state"
	@echo ""
	@echo "Profile files:"
	@echo "  swarm/profiles/<id>.swarm_profile.yaml"
	@echo ""
	@echo "After loading a profile, regenerate adapters:"
	@echo "  make gen-flow-constants && make gen-adapters && make ts-build"
	@echo ""
	@echo "See docs/FLOW_PROFILES.md for full documentation."
