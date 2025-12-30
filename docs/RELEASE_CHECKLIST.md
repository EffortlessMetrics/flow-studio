# Public Release Readiness Checklist

> **Purpose:** Run this checklist before tagging a public release.
> **Audience:** Maintainers preparing for a release.
> **Time:** ~30 minutes for a full pass.

---

## Pre-Release Validation

### 1. Install & Run (Fresh Clone)

A new user should be able to clone and run immediately.

```bash
# In a fresh directory
git clone <repo-url> flow-studio-test
cd flow-studio-test

# Smoke test: does the tooling work?
make dev-check        # Should pass all validation

# Demo run: does a complete flow work?
make demo-run         # Should populate swarm/runs/demo/

# Flow Studio: does the UI start?
make flow-studio      # Should serve at http://localhost:5000
```

**Checklist:**
- [ ] `make dev-check` passes without errors
- [ ] `make demo-run` produces artifacts in `swarm/runs/demo/`
- [ ] `make flow-studio` serves the UI
- [ ] UI loads without console errors
- [ ] At least one flow can be visualized

### 2. Hello World Path

There should be a path that works **without GitHub access**:

- [ ] `make stepwise-sdlc-stub` runs successfully (zero-cost demo)
- [ ] Stub run produces transcripts in `RUN_BASE/`
- [ ] No authentication errors or missing credentials

---

## Documentation Accuracy

### 3. Start Here Document

The main entry point should match reality.

- [ ] `docs/GETTING_STARTED.md` steps work as written
- [ ] Commands referenced in docs exist and work
- [ ] No references to deprecated features
- [ ] Flow descriptions match current implementation

### 4. Diagram Accuracy

Diagrams should use correct nouns.

- [ ] "Flow" means the 7 SDLC flows (Signal, Plan, Build, Review, Gate, Deploy, Wisdom)
- [ ] "Step/Station" means execution units within flows (not "agents")
- [ ] "Subagent" means Claude Code subagents (explore, plan-subagent, etc.)
- [ ] No diagram uses "agent" for what should be "step"

### 5. Architecture Documentation

Key architecture docs should be current.

- [ ] `ARCHITECTURE.md` reflects V3 routing model
- [ ] `docs/ROUTING_PROTOCOL.md` exists and is complete
- [ ] Flow charters (goal/exit_criteria/non_goals) are documented

---

## Contract Stability

### 6. Schema Validation

All schemas should be valid JSON Schema.

```bash
# Validate schemas parse correctly
uv run python -c "import json; [json.load(open(f)) for f in glob.glob('swarm/spec/schemas/*.json')]"
```

- [ ] All schema files are valid JSON
- [ ] `routing_signal.schema.json` includes `why_now` field
- [ ] `flow_graph.schema.json` includes `charter` and `suggested_sidequests`
- [ ] `handoff_envelope.schema.json` includes `observations`

### 7. Legacy Pattern Exclusion

Legacy patterns should be rejected.

```bash
# This should find only the linter tool and educational references
grep -r "route_to_flow\|route_to_agent" swarm/
```

- [ ] No active uses of `route_to_flow` or `route_to_agent`
- [ ] Linter rule exists to prevent reintroduction
- [ ] V3 routing vocabulary is used everywhere (CONTINUE, DETOUR, INJECT_FLOW, INJECT_NODES, EXTEND_GRAPH)

### 8. Handoff Contracts

Flow handoff contracts should be explicit.

- [ ] `swarm/spec/contracts/build_review_handoff.md` exists
- [ ] `build_receipt.json` schema is documented
- [ ] Draft→Ready transition criteria are explicit
- [ ] "Review complete" definition is documented

---

## Security & Trust

### 9. Secret Hygiene

No secrets should be committed.

```bash
# Check for common secret patterns
grep -rn "ANTHROPIC_API_KEY\|sk-ant-\|ghp_\|gho_" . --include="*.md" --include="*.yaml" --include="*.json"
```

- [ ] No API keys in committed files
- [ ] No GitHub tokens in examples
- [ ] `.gitignore` excludes `.env`, credentials files
- [ ] Secrets sanitizer story is documented (if applicable)

### 10. Scope Statement

Clear boundaries on what the system does.

- [ ] README states what flows exist
- [ ] README states what external services are used (GitHub)
- [ ] README states what is NOT automated (e.g., "Flow 8 rebase is injected only when blocking")
- [ ] No false claims about capabilities

---

## Quality Gates

### 11. CI Passes

All automated checks should pass.

```bash
make selftest        # Full selftest suite
make validate-swarm  # Swarm validation
uv run pytest tests/ # Unit tests
```

- [ ] `make selftest` passes (all 16 steps)
- [ ] `make validate-swarm` passes (FR-001 through FR-005)
- [ ] Unit tests pass
- [ ] No flaky tests

### 12. Golden Runs

Example runs should match documentation.

- [ ] `swarm/examples/health-check/` is up-to-date
- [ ] Example artifacts match current flow outputs
- [ ] README in examples describes what they demonstrate

---

## Project Hygiene

### 13. Standard Files

Open source hygiene files should exist.

- [ ] `LICENSE` exists and is appropriate
- [ ] `CONTRIBUTING.md` exists with contribution guidelines
- [ ] `CODE_OF_CONDUCT.md` exists (or link to org-level)
- [ ] `SECURITY.md` exists with vulnerability reporting instructions

### 14. Issue Templates

GitHub issue templates should exist.

- [ ] Bug report template
- [ ] Documentation drift template (for docs that don't match reality)
- [ ] Spec drift template (for specs that don't match implementation)

### 15. Version Tagging

Release should be properly tagged.

- [ ] Version number follows semver
- [ ] CHANGELOG is updated with release notes
- [ ] Tag message describes key changes
- [ ] Release notes link to relevant documentation

---

## Final Verification

### 16. End-to-End Smoke Test

Run a minimal end-to-end test.

```bash
# Create a fresh run
export RUN_ID="release-test-$(date +%s)"
make stepwise-sdlc-claude-cli RUN_ID=$RUN_ID

# Verify artifacts
ls swarm/runs/$RUN_ID/
```

- [ ] All 7 flows can execute (or gracefully skip)
- [ ] Artifacts are written to correct locations
- [ ] No orphaned temporary files
- [ ] Run can be cleaned up without issues

### 17. Rollback Test

Verify the previous release still works.

```bash
# Check out previous tag
git checkout v<previous>
make dev-check
```

- [ ] Previous release validation passes
- [ ] No breaking changes to core contracts (or documented migration path)

---

## Release Signoff

| Area | Owner | Status |
|------|-------|--------|
| Install & Run | | [ ] Pass |
| Documentation | | [ ] Pass |
| Contracts | | [ ] Pass |
| Security | | [ ] Pass |
| Quality | | [ ] Pass |
| Hygiene | | [ ] Pass |
| E2E Smoke | | [ ] Pass |

**Release Approved By:** _______________
**Date:** _______________
**Version:** _______________

---

## Post-Release

- [ ] Announcement posted (if applicable)
- [ ] Documentation site updated (if applicable)
- [ ] Known issues documented
- [ ] Next milestone planned
