# Adoption Playbook: From Zero to Governed Selftest

> For: Teams adopting the swarm pattern for their own repositories

This playbook guides you through adopting the swarm's governance patterns in your repository. You do not need to adopt the entire 7-flow swarm to get value. Start with selftest and expand as needed.

**Related docs:**
- [ADOPTING_SELFTEST_CORE.md](./ADOPTING_SELFTEST_CORE.md) - Standalone selftest-core package
- [ADOPTING_SWARM_VALIDATION.md](./ADOPTING_SWARM_VALIDATION.md) - Full swarm validation integration
- [SELFTEST_SYSTEM.md](./SELFTEST_SYSTEM.md) - Deep dive on the 10 selftest steps
- [SELFTEST_TEMPLATES.md](./SELFTEST_TEMPLATES.md) - Template comparison and selection guide

---

## Readiness Checklist

You're ready to start if you can say "yes" to all of:

- [ ] We have at least one repo with a passing test suite
- [ ] We can change CI configuration in at least that repo
- [ ] Someone "owns" CI failures (they are not ignored)
- [ ] We can install a Python CLI (uv/pip) in CI
- [ ] We're willing to have KERNEL failures block merges

**Not ready yet?** Start here instead:
1. Pick your most stable repo with existing tests
2. Get CI green on that repo first
3. Come back when you have a baseline to protect

---

## The Operator Mindset

Before adopting, internalize these principles from [AGOPS_MANIFESTO.md](./AGOPS_MANIFESTO.md):

1. **You are the foreman, not the worker** — Define specs, audit outputs, don't pair-program
2. **Trust forensics, not narrative** — If the diff is empty, work didn't happen (the AI lies)
3. **Scoped focus beats long threads** — Each step starts fresh, clearing irrelevant prior context
4. **Compute-attention arbitrage** — Burn compute to save your attention

> **Review the output, not the process.**
> The system does prep work before it reaches you. It will make mistakes. It will also catch mistakes.
> Treat it like a junior's drafts: you care about the final diff, tests, and receipts—not the messy iteration.

**The paradigm shift:**

| Chatbot Habit | Factory Discipline |
|---------------|-------------------|
| Read the chat log | Check the git diff |
| Intervene when stuck | Come back when it's ready |
| Long conversations | Scoped steps |
| Trust the summary | Trust the receipt |

If you find yourself staring at the terminal, you're using it wrong. Launch the run and walk away.

---

## Prerequisites

- Python 3.10+ with uv
- Git repository with CI (GitHub Actions preferred)
- Willingness to add a `selftest` step to your workflow

---

## The 90-Minute Path

### Step 1: Drop in selftest-core template (15 min)

**Option A: Use the bootstrap script (recommended)**

```bash
# Bootstrap a new project with the selftest-minimal template
uv run swarm/tools/bootstrap_selftest_minimal.py /path/to/your-repo

# Or with full setup (git init + install deps)
uv run swarm/tools/bootstrap_selftest_minimal.py /path/to/your-repo --init-git --install-deps
```

**Option B: Manual copy**

```bash
# Copy the template
cp -r templates/selftest-minimal/* your-repo/

# Install dependencies
cd your-repo
uv sync
```

The `templates/selftest-minimal/` template includes:
- `selftest.yaml` - Pre-configured KERNEL/GOVERNANCE/OPTIONAL steps
- `pyproject.toml` with selftest-core dependency
- `.github/workflows/selftest.yml` - Ready-to-use CI workflow
- `README.md` - Template documentation

**Alternative: Visualization-only adoption**

If you only want Flow Studio for understanding flows (no selftest governance):
```bash
cp -r templates/flowstudio-only/* your-repo/
```

This minimal template includes just the visualization components without selftest enforcement.

If no template fits your needs, create a minimal config manually:

```bash
# Create config manually if no template
cat > selftest.yaml << 'EOF'
mode: strict
steps:
  - id: lint
    tier: kernel
    command: ruff check .
    description: Python linting
EOF
```

### Step 2: Define KERNEL for your repo (20 min)

Edit `selftest.yaml` (or `selftest/config.yaml` if using the template):

```yaml
mode: strict

steps:
  # KERNEL tier: Must pass for any merge
  - id: lint
    tier: kernel
    command: ruff check .
    description: Python linting
    severity: critical

  - id: typecheck
    tier: kernel
    command: mypy src/
    description: Type checking
    severity: critical

  - id: compile
    tier: kernel
    command: python -m compileall -q src/
    description: Syntax validation
    severity: critical
```

**Guidelines for KERNEL checks:**
- Add 3-5 checks maximum
- Must complete in < 30 seconds total
- These are your "circuit breakers" - if broken, nothing else matters
- Examples: lint, typecheck, compile, core unit tests

### Step 3: Add one GOVERNANCE check (15 min)

GOVERNANCE checks are important but can be worked around with `--degraded` mode:

```yaml
steps:
  # ... KERNEL steps above ...

  # GOVERNANCE tier: Should pass, but can be deferred
  - id: api-compat
    tier: governance
    command: ./scripts/check-api-compat.sh
    description: API backward compatibility check
    severity: warning

  - id: migrations
    tier: governance
    command: python manage.py migrate --check
    description: Verify no pending migrations
    severity: warning
```

**Good GOVERNANCE checks:**
- API compatibility validation
- Migration verification
- Documentation freshness
- Security dependency scanning

### Step 4: Wire to CI (20 min)

Create `.github/workflows/selftest.yml`:

```yaml
name: Selftest

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  kernel-smoke:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v2
      - name: Install dependencies
        run: uv sync
      - name: Kernel smoke check
        run: uv run selftest run --kernel-only

  full-selftest:
    runs-on: ubuntu-latest
    needs: kernel-smoke
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v2
      - name: Install dependencies
        run: uv sync
      - name: Full selftest
        run: uv run selftest run --report selftest_report.json
      - name: Upload report
        uses: actions/upload-artifact@v4
        if: always()
        with:
          name: selftest-report
          path: selftest_report.json
```

**Key patterns:**
- Run `--kernel-only` first (fast, blocks everything else)
- Full selftest runs only if kernel passes
- Always upload the report artifact for debugging

### Step 5: Write acceptance tests (20 min)

Create `tests/test_selftest_ac.py`:

```python
"""Acceptance tests for selftest integration.

These tests verify that selftest is correctly configured and
that failure modes work as expected.
"""
import subprocess
import sys


def test_kernel_failures_return_exit_code_1():
    """KERNEL failures must block with exit code 1."""
    # This test assumes you have a way to trigger a KERNEL failure
    # In practice, you'd mock or have a test-specific config
    result = subprocess.run(
        [sys.executable, "-m", "selftest", "run", "--kernel-only"],
        capture_output=True,
        text=True,
    )
    # Exit code should be 0 (pass) or 1 (fail), never 2 (config error)
    assert result.returncode in (0, 1), f"Unexpected exit code: {result.returncode}"


def test_governance_failures_logged_in_degraded_mode():
    """GOVERNANCE failures should be logged but not block in degraded mode."""
    result = subprocess.run(
        [sys.executable, "-m", "selftest", "run", "--degraded"],
        capture_output=True,
        text=True,
    )
    # In degraded mode, only KERNEL failures cause exit code 1
    # GOVERNANCE failures are logged but don't block
    assert result.returncode in (0, 1)


def test_selftest_plan_is_introspectable():
    """Selftest plan should be visible without running anything."""
    result = subprocess.run(
        [sys.executable, "-m", "selftest", "plan", "--json"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "steps" in result.stdout
```

Run the tests:

```bash
uv run pytest tests/test_selftest_ac.py -v
```

---

## Success Criteria

After 90 minutes, you should have:

- [ ] `selftest run` executes without error
- [ ] KERNEL failures return exit code 1
- [ ] GOVERNANCE failures are logged (visible in `--degraded` mode output)
- [ ] CI workflow runs on PR
- [ ] Acceptance tests pass

**Verification commands:**

```bash
# Verify selftest runs
uv run selftest run

# Verify plan is visible
uv run selftest plan

# Verify CI config is valid
act -n  # (if you have 'act' installed for local GitHub Actions testing)

# Verify tests pass
uv run pytest tests/test_selftest_ac.py -v
```

---

## Adoption Archetypes

Different org shapes need different adoption paths. Find your archetype and follow its timeline.

### Archetype 1: Single Product, Single Repo

**Who you are:** One main application, one team, one CI pipeline. You own the whole stack.

**Starting point:**
- One repo with pytest/cargo test and real CI
- At least a smoke test suite that runs on PR
- Team has authority to change CI configuration

**First targets:**
- Land selftest-minimal in this repo
- Make KERNEL blocking in CI
- Add one GOVERNANCE check that matters to you

**Day 1 / Week 1 / Month 1:**

| Timeframe | Actions | Success Criteria |
|-----------|---------|------------------|
| **Day 1** | Run `make dev-check` on flow-studio; read CLAUDE.md | Understand the three tiers |
| **Week 1** | Fork `templates/selftest-minimal/` and run `bootstrap_selftest_minimal.py` | `selftest run --kernel-only` passes in CI |
| **Month 1** | Add 2-3 GOVERNANCE checks; switch from degraded to strict | PR blocked on KERNEL; GOVERNANCE failures logged |

**Quick start:**
```bash
# Copy template to your repo
cp -r templates/selftest-minimal/* your-repo/
cd your-repo && uv sync
uv run selftest run --kernel-only
```

---

### Archetype 2: Platform Team with N Services

**Who you are:** Central platform team supporting 10-50 services owned by product teams. You provide golden paths.

**Starting point:**
- Multiple repos with varying test maturity
- Shared CI templates or reusable workflows
- Authority to mandate baseline checks

**First targets:**
- Pick 2-3 "lighthouse" repos with good test coverage
- Roll out selftest-core as shared dependency
- Create org-specific KERNEL definition

**Day 1 / Week 1 / Month 1:**

| Timeframe | Actions | Success Criteria |
|-----------|---------|------------------|
| **Day 1** | Fork flow-studio; run dev-check; identify lighthouse repos | 2-3 candidate repos identified |
| **Week 1** | Create internal boilerplate from `templates/selftest-minimal/` and `templates/flowstudio-only/` | Lighthouse repos have passing KERNEL |
| **Month 1** | Create shared workflow; enable for 5+ repos | Selftest in 5+ repos; KERNEL blocking on all |

**Quick start:**
```bash
# Create org template from selftest-minimal
cp -r templates/selftest-minimal/ org-selftest-template/
# Customize for your org's KERNEL definition
$EDITOR org-selftest-template/selftest.yaml
```

---

### Archetype 3: Skeptical Audit/Security Function

**Who you are:** Compliance, audit, or security team. You need evidence without owning the code.

**Starting point:**
- Product teams ship code; you verify compliance
- Need audit trails and decision rationale
- May not control CI directly

**First targets:**
- Use Flow Studio to visualize existing flows
- Review receipts and merge decisions
- Identify gaps between stated process and actual practice

**Day 1 / Week 1 / Month 1:**

| Timeframe | Actions | Success Criteria |
|-----------|---------|------------------|
| **Day 1** | Run `make flow-studio`; explore the 7 flows | Understand Signal to Wisdom pipeline |
| **Week 1** | Review demo artifacts in `swarm/examples/`; map to your compliance requirements | Gap analysis document |
| **Month 1** | Propose GOVERNANCE checks that feed your audit needs | At least one repo producing receipts you consume |

---

## Scaling Up

### Week 2: Add Flow Studio (Optional)

If you want visual understanding of your flows:

```bash
# Copy Flow Studio (if not using full swarm)
cp -r flow-studio/swarm/tools/flow_studio.py ./swarm/tools/
cp -r flow-studio/swarm/flowstudio ./swarm/

# Define your flows
mkdir -p swarm/config/flows
cat > swarm/config/flows/ci.yaml << 'EOF'
key: ci
title: "CI Pipeline"
description: "Continuous integration checks"
steps:
  - id: lint
    role: "Code quality"
    agents: []
  - id: test
    role: "Verification"
    agents: []
EOF

# Start Flow Studio
uv run python swarm/tools/flow_studio.py
# Open http://localhost:5000
```

### Week 3-4: Full Swarm Integration

If you want the full 7-flow SDLC:

1. **Read the philosophy**: Start with `docs/WHY_DEMO_SWARM.md`
2. **Copy the structure**: Fork `flow-studio` or copy `swarm/` directory
3. **Customize agents**: Edit `swarm/config/agents/*.yaml` for your domain
4. **Define flows**: Edit `swarm/config/flows/*.yaml` for your process
5. **Wire CI gates**: Add Flow 4 (Gate) to your merge protection

See [ADOPTING_SWARM_VALIDATION.md](./ADOPTING_SWARM_VALIDATION.md) for the full adoption path.

---

## Anti-Patterns to Avoid

### 1. Don't start with all 7 flows

**Bad**: "Let's implement Signal, Plan, Build, Review, Gate, Deploy, and Wisdom all at once!"

**Good**: Start with selftest only. Add flows incrementally when you understand why you need them.

### 2. Don't make GOVERNANCE blocking initially

**Bad**: Strict mode from day one with 10 GOVERNANCE checks that fail.

**Good**: Start with `--degraded` mode. Log governance failures. Fix them incrementally. Switch to strict when stable.

```bash
# Week 1-2: Degraded mode (collect data)
uv run selftest run --degraded

# Week 3+: Strict mode (enforce)
uv run selftest run
```

### 3. Don't skip the acceptance tests

**Bad**: "We'll add tests later."

**Good**: Write 3 acceptance tests before deploying to CI. They prove the system works and prevent regressions.

### 4. Don't customize before validating

**Bad**: Immediately modify the selftest framework for your "special needs."

**Good**: Get vanilla working first. Understand why it works. Then customize incrementally.

### 5. Don't ignore the exit codes

**Bad**: CI step that runs selftest but ignores the exit code.

**Good**: CI step fails the build when selftest returns exit code 1.

```yaml
# Bad
- run: selftest run || true

# Good
- run: selftest run
```

---

## Troubleshooting

### "selftest: command not found"

Install selftest-core:

```bash
uv add selftest-core
# or
pip install selftest-core
```

### "No configuration file found"

Create `selftest.yaml` in your project root:

```bash
cat > selftest.yaml << 'EOF'
steps:
  - id: smoke
    tier: kernel
    command: echo "Hello, selftest"
    description: Smoke test
EOF
```

### "KERNEL failure in CI but passes locally"

Common causes:
1. **Missing dependencies**: CI doesn't have the same packages installed
2. **Path differences**: Hardcoded paths that work locally but not in CI
3. **Environment variables**: Missing env vars in CI

Debug with:

```bash
# Run doctor diagnostics
uv run selftest doctor

# Run with verbose output
uv run selftest run --verbose
```

### "GOVERNANCE failures blocking merge"

If you're not ready to fix all GOVERNANCE issues:

```bash
# Run in degraded mode (GOVERNANCE becomes warnings)
uv run selftest run --degraded
```

Or temporarily demote the check to OPTIONAL tier:

```yaml
steps:
  - id: problematic-check
    tier: optional  # Was: governance
    command: ./check.sh
    description: Temporarily optional
```

---

## Support

- **Issues**: https://github.com/EffortlessMetrics/flow-studio/issues
- **Docs**:
  - `CLAUDE.md` - Full reference
  - `docs/SELFTEST_SYSTEM.md` - Selftest deep dive
  - `docs/ADOPTING_SELFTEST_CORE.md` - Standalone package guide

---

## Quick Reference

### Exit Codes

| Code | Meaning | Action |
|------|---------|--------|
| 0 | All checks passed | Merge is safe |
| 1 | Check failed | Fix and re-run |
| 2 | Configuration error | Fix config |

### Tier Semantics

| Tier | Blocking? | Degradable? | Use For |
|------|-----------|-------------|---------|
| KERNEL | Always | Never | Fundamentals (lint, compile, core tests) |
| GOVERNANCE | Yes (unless --degraded) | Yes | Contracts (API compat, migrations, docs) |
| OPTIONAL | Never | Always | Nice-to-have (coverage thresholds, extras) |

### Key Commands

```bash
# See the plan without running
uv run selftest plan

# Run all checks (strict mode)
uv run selftest run

# Run only KERNEL (fast)
uv run selftest run --kernel-only

# Run with GOVERNANCE as warnings
uv run selftest run --degraded

# Run a single step
uv run selftest run --step lint

# Get JSON output
uv run selftest run --json

# Diagnose environment issues
uv run selftest doctor
```

---

## See Also

- **[SELFTEST_TEMPLATES.md](./SELFTEST_TEMPLATES.md)** - Compare templates and choose the right starting point
- **[ADOPTING_SELFTEST_CORE.md](./ADOPTING_SELFTEST_CORE.md)** - Deep dive on selftest-core configuration and Python API
- **[SELFTEST_SYSTEM.md](./SELFTEST_SYSTEM.md)** - Full reference for the 10 selftest steps and tier semantics
- **Templates:**
  - `templates/selftest-minimal/` - Full selftest with KERNEL/GOVERNANCE/OPTIONAL tiers
  - `templates/flowstudio-only/` - Visualization-only, no governance enforcement
- **Bootstrap script:** `swarm/tools/bootstrap_selftest_minimal.py` - Automated project setup
