# Runbook Standards

**"A runbook someone unfamiliar with the system can execute."**

Runbooks are versioned, executable guides for operational work. They trade planning time for execution clarity.

## The Purpose of Runbooks

Runbooks exist to:
- Enable someone unfamiliar with the system to execute safely
- Provide verifiable success criteria
- Document rollback paths before they're needed
- Capture tribal knowledge in executable form

Runbooks are NOT:
- Flow artifacts (those go to `RUN_BASE/<flow>/`)
- General documentation (those go to `docs/`)
- Agent definitions (those go to `.claude/agents/`)

## Required Structure

Every runbook MUST include these sections:

### 1. Purpose
One sentence: what this runbook accomplishes.

```markdown
## Purpose
Restore a failed stepwise run from its last checkpoint.
```

### 2. Prerequisites
What must be true before starting.

```markdown
## Prerequisites
- Python 3.11+ installed
- `uv` package manager available
- Access to `swarm/runs/<run-id>/` directory
- Previous run exists with at least one completed step
```

### 3. Steps
Numbered steps with exact commands and expected outputs.

```markdown
## Steps

### Step 1: Identify the last checkpoint (1 min)

```bash
ls -la swarm/runs/<run-id>/*/receipts/
```

**Expected output**: List of receipt files, one per completed step.

**Decision point**:
- If receipts exist → proceed to Step 2
- If no receipts → run is unrecoverable, start fresh
```

### 4. Verification
How to confirm the runbook succeeded.

```markdown
## Verification

Run:
```bash
make validate-swarm && echo "SUCCESS"
```

**Pass criteria**:
- Exit code 0
- "SUCCESS" printed
- No warnings in output
```

### 5. Rollback
What to do if it fails.

```markdown
## Rollback

If step 3 fails:
1. Restore the backup: `cp -r backup/ swarm/runs/<run-id>/`
2. Verify backup: `ls swarm/runs/<run-id>/`
3. Start over from Step 1
```

### 6. Troubleshooting
Common issues and fixes.

```markdown
## Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|--------------|-----|
| "Permission denied" | File locked | `chmod +w <file>` or close editor |
| "No such file" | Wrong run ID | `ls swarm/runs/` to find actual ID |
| Timeout | Large run | Add `--timeout 300` flag |
```

## Writing Principles

### Executable by the Unfamiliar

Every step must be understandable by someone who hasn't seen this system before.

**Bad:**
```markdown
Now update the config as usual.
```

**Good:**
```markdown
Edit `swarm/config/flows.yaml` and add:
```yaml
- id: new-step
  agent: my-agent
```
Verify: `grep "new-step" swarm/config/flows.yaml` returns the line.
```

### Every Step Has Expected Output

Never leave the reader wondering if it worked.

**Bad:**
```markdown
Run `make validate-swarm`.
```

**Good:**
```markdown
Run:
```bash
make validate-swarm
```

**Expected output**:
```
Checking agents... OK
Checking flows... OK
All validations passed.
```

**If you see errors**, proceed to Troubleshooting section.
```

### Decision Points Are Explicit

Branch logic is spelled out, not assumed.

**Bad:**
```markdown
Handle any issues that arise.
```

**Good:**
```markdown
**Decision point**:
- If output shows "PASSED" → proceed to Step 3
- If output shows "FAILED with lint errors" → run `make auto-lint`, then repeat Step 2
- If output shows "FAILED with test errors" → proceed to Troubleshooting
```

### Commands Are Copy-Pasteable

No placeholder confusion, no assumed context.

**Bad:**
```markdown
Run the command with appropriate flags.
```

**Good:**
```markdown
```bash
uv run swarm/tools/validate_swarm.py --strict
```
```

### Time Estimates Are Included

Each step includes expected duration.

```markdown
### Step 3: Run full validation (2 min)
```

## What Makes a Good Runbook

| Property | Why It Matters |
|----------|----------------|
| **Idempotent** | Safe to run twice without harm |
| **Atomic steps** | Can stop and resume at any step |
| **Clear success criteria** | Know when you're done |
| **Explicit failure handling** | Know what to do when it breaks |
| **Time-bounded** | Know how long it takes |

## Anti-Patterns

### "Use Your Judgment"

**Problem:** Judgment varies. Results vary.

**Fix:** Be explicit about the decision criteria.

```markdown
# Bad
Use your judgment to decide if the output looks correct.

# Good
**Decision criteria**:
- Exit code is 0: proceed
- Exit code is 1 with "lint" in output: run auto-linter
- Any other failure: stop and escalate
```

### Missing Expected Outputs

**Problem:** Reader doesn't know if it worked.

**Fix:** Show what success looks like.

```markdown
# Bad
Run the tests.

# Good
Run:
```bash
uv run pytest tests/ -v
```

**Expected output** (truncated):
```
tests/test_validate_swarm.py::test_bijection PASSED
tests/test_validate_swarm.py::test_frontmatter PASSED
...
===== 42 passed in 3.21s =====
```
```

### Assumed Context

**Problem:** Works for you, fails for others.

**Fix:** State all prerequisites and working directory.

```markdown
# Bad
Run the validation script.

# Good
From the repository root (`flow-studio-swarm/`):
```bash
uv run swarm/tools/validate_swarm.py
```

Requires: `uv` installed, dependencies synced (`uv sync --frozen`).
```

### No Rollback Plan

**Problem:** When it fails, panic ensues.

**Fix:** Plan the retreat before the advance.

```markdown
# Bad
(Rollback section missing)

# Good
## Rollback

Before Step 3, create a backup:
```bash
cp -r swarm/runs/<run-id> swarm/runs/<run-id>.bak
```

If Step 3 fails:
```bash
rm -rf swarm/runs/<run-id>
mv swarm/runs/<run-id>.bak swarm/runs/<run-id>
```
```

## Naming Convention

Runbook filenames follow: `<action>-<target>[-<context>].md`

| Pattern | Example | Description |
|---------|---------|-------------|
| `deploy-*` | `deploy-flow-studio.md` | Deployment procedures |
| `recover-*` | `recover-failed-run.md` | Recovery procedures |
| `rotate-*` | `rotate-api-keys.md` | Credential rotation |
| `*-health-check` | `10min-health-check.md` | Validation checks |
| `*-fastpath` | `stepwise-fastpath.md` | Quick-start guides |
| `*-retention` | `runs-retention.md` | Lifecycle management |

## Testing Runbooks

Before publishing a runbook:

1. **Execute it yourself** - Run through every step manually
2. **Have someone unfamiliar execute it** - Watch where they get stuck
3. **Update based on friction** - Every question becomes documentation
4. **Verify idempotence** - Run it twice, confirm no harm

## The Rule

> A runbook is only good if someone who's never seen the system can execute it successfully.
> Expected outputs are required. Decision points are explicit. Rollback is planned.

## Current Implementation

See `swarm/runbooks/` for the canonical runbook collection:
- `10min-health-check.md` - Full system validation
- `selftest-flowstudio-fastpath.md` - Flow Studio optimization work
- `stepwise-fastpath.md` - Stepwise execution quick-start
- `runs-retention.md` - Run lifecycle and garbage collection
- `ui-layout-review.md` - UX review process

## See Also

- [swarm/runbooks/README.md](../../../swarm/runbooks/README.md) - Runbook index
- [evidence-discipline.md](./evidence-discipline.md) - Why expected outputs matter
- [pack-check-philosophy.md](./pack-check-philosophy.md) - Competence over compliance
