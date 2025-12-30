# Contributing to Flow Studio

Thanks for contributing to Flow Studio. This project uses an agentic SDLC with strict governance gates.

> **Quick Links:**
> - [Definition of Done](docs/DEFINITION_OF_DONE.md) — What "done" means for merging
> - [Merge Checklist](docs/MERGE_CHECKLIST.md) — Pre-merge verification checklist
> - [CI Troubleshooting](docs/CI_TROUBLESHOOTING.md) — Fixing CI failures

All contributions go through seven flows:

1. **Signal → Specs** — Problem statement, requirements, BDD
2. **Specs → Plan** — Design, contracts, observability, test plans
3. **Plan → Build** — Implementation with adversarial microloops
4. **Build → Review** — Code review and feedback
5. **Review → Gate** — Pre-merge verification (receipts, contracts, security)
6. **Gate → Deploy** — Merge and deployment
7. **Deploy → Wisdom** — Regression analysis and learning loops

Before editing docs, README, or agent prompts: Write like a senior engineer explaining what works, not a product launch or transformation pitch. Be direct, technical, and honest about trade-offs.

## Local Development Setup

### 1. Clone and Install

```bash
git clone <repo>
cd flow-studio
uv sync --frozen  # Install dependencies (Python 3.13+)
```

### 2. Pre-commit Hooks (Optional but Recommended)

Pre-commit hooks validate your changes before committing, catching issues early:

```bash
pip install pre-commit
pre-commit install
```

This runs:
- Swarm validation (agent/flow config alignment)
- AC matrix freshness (acceptance criteria consistency)
- AC test suite (bijection, API contracts)
- Degradation tests (selftest integrity)

**Why optional?** Governance is enforced by CI/CD gates. Local pre-commit is a convenience for faster feedback.

### 3. Verify Everything Works

```bash
make dev-check                # Validate + run kernel selftest (fast)
make selftest                 # Full selftest (slow, comprehensive)
uv run pytest                 # All unit/integration tests
```

## Working on Flow Studio (Governed UI)

Flow Studio (`swarm/tools/flow_studio_ui/…`) is a **governed surface**. It is the
typed UI/SDK that operators, tests, and LLM-based tools rely on.

If your change touches Flow Studio, follow these rules:

### 1. Edit TypeScript, not compiled JS

- Source lives in `swarm/tools/flow_studio_ui/src/*.ts`
- Build output lives in `swarm/tools/flow_studio_ui/js/` and is **gitignored**
- Do not edit anything under `js/` by hand

Build / check:

```bash
cd swarm/tools/flow_studio_ui
npm install          # first time
npm run ts-check     # or: make ts-check
npm run ts-build     # or: make ts-build
```

### 2. Governed surfaces = breaking changes

The following are treated as public API:

* `window.__flowStudio` shape (`FlowStudioSDK` in `domain.ts`)
* `data-uiid="flow_studio.…"` selectors (`FlowStudioUIID` in `domain.ts`)
* `data-ui-ready="loading|ready|error"` on `<html>`

If you change any of these:

1. Update `swarm/tools/flow_studio_ui/src/domain.ts`
2. Update tests:
   * `tests/test_flow_studio_ui_ids.py`
   * `tests/test_flow_studio_scenarios.py`
   * `tests/test_flow_studio_sdk_path.py`
3. Update docs:
   * `docs/FLOW_STUDIO.md` ("Governed Surfaces" section)
   * `CLAUDE.md` (short note under Flow Studio)
4. Re-run and fix:
   * `make dev-check`
   * `make ts-build`
5. If behavior changed for operators, update:
   * `swarm/runbooks/10min-health-check.md`
   * `swarm/runbooks/selftest-flowstudio-fastpath.md`

See **[MAINTAINING_FLOW_STUDIO.md](./docs/MAINTAINING_FLOW_STUDIO.md)** for full details.

### 3. Always use the runbooks to validate UX

**Before merging any Flow Studio PR**, run these two runbooks:

- `swarm/runbooks/10min-health-check.md`
- `swarm/runbooks/selftest-flowstudio-fastpath.md`

```bash
# Quick reference: commands from those runbooks
make dev-check              # Automated checks
make demo-run               # Populate demo artifacts
make flow-studio            # Start UI, then walk through manually
```

Those runbooks are part of the contract. If they no longer describe reality,
update them in the same PR.

### 4. Prefer SDK + UIIDs in tests and tools

If you are writing tests or automation that interacts with Flow Studio:

* Use `window.__flowStudio` instead of ad-hoc `page.click` chains
* Use `[data-uiid="flow_studio.…"]` selectors instead of brittle CSS like
  `.run-selector` or `#run-selector`
* Wait for readiness with `html[data-ui-ready="ready"]` (or `waitForUIReady()`)

Examples live in:

* `tests/test_flow_studio_scenarios.py`
* `tests/test_flow_studio_sdk_path.py`

For more, see [MAINTAINING_FLOW_STUDIO.md](./docs/MAINTAINING_FLOW_STUDIO.md) and [FLOW_STUDIO.md](./docs/FLOW_STUDIO.md).

---

## Making Changes

### 1. Create a Feature Branch

```bash
git checkout -b feat/your-feature-name
```

### 2. Make Your Changes

Follow the agentic SDLC:
- **Code changes:** Edit files in `src/`, `tests/`, `features/`
- **Agent changes:** Edit `swarm/config/agents/<key>.yaml`, then `make gen-adapters`
- **Flow changes:** Edit `swarm/config/flows/<key>.yaml`, then `make gen-flows`
- **Configuration:** Edit config files, regenerate adapters, validate

### 3. Validate Locally

```bash
# Quick check (validation only)
make quick-check

# Full check (validation + selftest)
make dev-check

# If you modified selftest infrastructure
make selftest  # Full selftest with all 16 steps
```

### 4. Commit Your Changes

```bash
git add .
git commit -m "feat: your descriptive commit message"
```

Pre-commit hooks will run if installed. Fix any errors and try again.

### 5. Push and Open a Pull Request

```bash
git push origin feat/your-feature-name
```

## Validation Workflow

Before committing changes to `swarm/` or `.claude/`:

### 1. Run Validator

```bash
# Full validation
uv run swarm/tools/validate_swarm.py

# Or use make shorthand
make validate-swarm
```

The validator enforces:
- **FR-001: Bijection** — 1:1 mapping between `swarm/AGENTS.md` and `.claude/agents/*.md` files
- **FR-002: Frontmatter** — Required YAML fields, color matching role family, no `tools:` or `permissionMode:` fields
- **FR-003: Flow References** — All agent references in flows exist and are spelled correctly
- **FR-004: Skills** — All declared skills have valid SKILL.md files
- **FR-005: RUN_BASE Paths** — All artifact paths use `RUN_BASE/<flow>/` placeholders, not hardcoded paths

Exit codes:
- `0` — Validation passed
- `1` — Validation failed (fix issues before committing)
- `2` — Fatal error (missing AGENTS.md or parse error; contact maintainer)

### 2. Run Tests

```bash
# Full test suite
uv run pytest

# Incremental (fast) validation
uv run swarm/tools/validate_swarm.py --check-modified
```

## Troubleshooting

### Color Mismatch Error

```
✗ COLOR: .claude/agents/test-critic.md: color 'blue' does not match expected color 'red' for role family 'critic'
```

**Fix**: Update the agent's `color:` frontmatter to match its role family in `swarm/AGENTS.md`.

Color ↔ role family mapping:
- `yellow` → shaping
- `purple` → spec/design
- `green` → implementation
- `red` → critic
- `blue` → verification
- `orange` → analytics
- `pink` → reporter (exactly one)
- `cyan` → infra

### Missing Agent File

```
✗ BIJECTION: swarm/AGENTS.md:line 42: Agent 'foo-bar' is registered but .claude/agents/foo-bar.md does not exist
```

**Fix**: Either create `.claude/agents/foo-bar.md` with required frontmatter or remove the entry from `swarm/AGENTS.md`.

### RUN_BASE Path Error

```
✗ RUNBASE: swarm/flows/flow-3.md:line 45: contains hardcoded path 'swarm/runs/<run-id>/'; should use RUN_BASE placeholder
```

**Fix**: Replace hardcoded paths with `RUN_BASE/<flow>/` placeholder. Example: use `RUN_BASE/build/artifact.md` instead of `swarm/runs/ticket-123/build/artifact.md`.

### Unknown Agent Reference

```
✗ REFERENCE: swarm/flows/flow-3.md:line 12: references unknown agent 'code-implemen'; did you mean 'code-implementer'?
```

**Fix**: Correct the typo in the flow spec, or add the agent to `swarm/AGENTS.md` and create its file if the agent is new.

### AC Matrix Freshness Failed

The AC (Acceptance Criteria) matrix must be aligned across:
1. **Gherkin features** (`features/selftest.feature`) — The executable spec
2. **Documentation** (`docs/SELFTEST_AC_MATRIX.md`) — The spec registry
3. **Config** (`swarm/tools/selftest_config.py`) — The implementation

If one AC is in features but not in the docs:

```bash
make check-ac-freshness --verbose
```

Then add the AC to `docs/SELFTEST_AC_MATRIX.md` and link it to the appropriate selftest step.

### Degradation Tests Failed

The degradation system tests ensure:
- Selftest can emit degradation logs in the correct schema
- CLI outputs match documented formats
- `/api/selftest/status` endpoint coherence with degradation logs

Run diagnostics:

```bash
make selftest-doctor
uv run pytest tests/test_selftest_degradation_*.py -v
```

### "My code works locally but fails in CI"

Check these environmental differences:
- Python version: `python --version` (CI uses 3.13)
- Dependencies: `uv sync --frozen` (use uv, not pip)
- Git history: Some checks need full history (`git fetch --unshallow`)

See [docs/CI_TROUBLESHOOTING.md](docs/CI_TROUBLESHOOTING.md) for detailed troubleshooting.

## CI/CD Gates

Your PR will be checked by three gates:

### Gate 1: validate-swarm (Swarm Spec Alignment)

- Agent ↔ file bijection (FR-001)
- Frontmatter validation (FR-002)
- Flow references exist (FR-003)
- Skills declarations valid (FR-004)
- RUN_BASE paths correct (FR-005)

**If it fails:** Run `make validate-swarm` locally to reproduce, then fix misalignment.

### Gate 2: test-swarm (Unit/Integration Tests)

- All pytest tests pass
- No flaky tests (retry logic if needed)
- Coverage thresholds met

**If it fails:** Run `uv run pytest -v` locally to see details. All tests must pass.

### Gate 3: selftest-governance-gate (Governance Enforcement)

- AC matrix freshness (ACs aligned across Gherkin, docs, code)
- AC test suite (bijection, API contracts, traceability)
- Degradation tests (selftest system integrity)

**If it fails:** Run `make selftest-doctor` to diagnose. Fix AC matrix or degradation schema issues locally.

## Code Style

### Python (tools, validators, tests)

```bash
# Format
black swarm/tests/

# Lint
ruff check swarm/tools/
ruff check --fix swarm/tools/
```

### YAML (workflows, configs)
- Use 2-space indentation
- Use literal `|` for multiline strings
- Use `|>` for folded strings

### Markdown (docs, guides)
- Use 1-space code fence indentation
- Use GitHub-flavored markdown
- Spell check: `codespell` (if available)

## Merging Your PR

Once all gates pass:
1. Get one approval from a maintainer
2. Merge via GitHub (squash or regular merge, your choice)
3. The merged code is immediately deployed (Flow 5) and analyzed (Flow 6)

## Adding a New Agent

Follow this checklist:

1. **Register the agent** in `swarm/AGENTS.md`:
   ```markdown
   | foo-bar | spec | purple | Designs foo subsystem |
   ```

2. **Create agent file** at `.claude/agents/foo-bar.md`:
   ```yaml
   ---
   name: foo-bar
   description: Designs foo subsystem
   color: purple
   model: inherit
   ---

   You are the **Foo Designer**.

   ## Inputs
   - `RUN_BASE/plan/requirements.md`

   ## Outputs
   - `RUN_BASE/plan/foo_design.md`

   ## Behavior
   1. Read requirements
   2. Design subsystem
   3. Write design document
   ```

   **Important**:
   - `name:` must match filename (case-sensitive)
   - `color:` must match role family (derived from `AGENTS.md` row)
   - `model:` use `inherit` for most agents (inherits Claude Code's default)
   - Omit `tools:` and `permissionMode:` fields (use prompt-based constraints)

3. **Update flow specs** if agent is used:
   - Edit `swarm/flows/flow-*.md` Step tables to include agent name in appropriate step

4. **Run validation**:
   ```bash
   make validate-swarm
   ```

5. **Commit**:
   ```bash
   git add swarm/AGENTS.md .claude/agents/foo-bar.md swarm/flows/...
   git commit -m "feat: Add foo-bar agent"
   ```

## Running Strict Validation

To enforce additional design constraints:

```bash
uv run swarm/tools/validate_swarm.py --strict
```

Strict mode treats design guideline warnings as errors (e.g., `tools:` or `permissionMode:` fields). Default mode warns but allows these for compatibility; use `--strict` in CI for enforcement.

## For Maintainers

If you need to update the validator itself (`swarm/tools/validate_swarm.py`):

1. Update the validation logic
2. Add/update tests in `tests/` directory
3. Run full test suite: `uv run pytest`
4. Update this file and `CLAUDE.md` to document new requirements
5. Increment version in validator docstring if FR requirements change

## Questions?

- **Design questions:** See `swarm/positioning.md` (philosophy) and `ARCHITECTURE.md` (structure)
- **Agent/flow questions:** Read `CLAUDE.md` § Agent Ops
- **Selftest questions:** See `docs/SELFTEST_SYSTEM.md`
- **CI/CD issues:** See `docs/CI_TROUBLESHOOTING.md`
- **Voice and style:** See `VOICE.md` for documentation guidelines
