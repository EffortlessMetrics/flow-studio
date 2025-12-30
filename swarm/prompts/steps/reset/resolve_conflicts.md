# resolve_conflicts (Flow 8 - Reset)

You are executing the **resolve_conflicts** step in Flow 8 (Reset).

## Objective

Safely resolve merge or rebase conflicts that arose from the `sync_upstream` step. Your goal is to restore the repository to a clean, mergeable state while preserving the intent of both upstream and local changes.

**Prime Directive**: Never lose work. Never auto-resolve if uncertain. Pause for human when semantic judgment is required.

---

## Inputs

From `sync_upstream` step (via handoff envelope or context):

| Input | Source | Required |
|-------|--------|----------|
| `has_conflicts` | sync_upstream result | Yes |
| `conflict_files` | sync_upstream result | Yes |
| `sync_method` | "rebase" or "merge" | Yes |
| `upstream_ref` | SHA of upstream commit | Yes |

From run artifacts:

- `.runs/<run-id>/reset/sync_report.md` - Details of sync attempt
- `.runs/<run-id>/reset/diagnose_report.md` - Initial state diagnosis

---

## Outputs

### Primary Output

- `.runs/<run-id>/reset/conflict_resolution_report.md`

### Output Schema

```yaml
# resolve_conflicts Output Schema
status: VERIFIED | UNVERIFIED | PAUSED
conflict_complexity: low | medium | high

resolution_summary:
  total_conflicts: <count>
  resolved_at_level_1: <count>  # Mechanical
  resolved_at_level_2: <count>  # Semantic
  escalated_to_level_3: <count> # Human

files_resolved:
  - file: "path/to/file"
    level: 1 | 2
    strategy: "ours | theirs | manual_merge"
    rationale: "Why this resolution was chosen"
    confidence: 0.0-1.0

files_unresolved:
  - file: "path/to/file"
    reason: "Why resolution could not be automated"
    both_sides_summary:
      ours: "Summary of our changes"
      theirs: "Summary of their changes"
    recommendation: "Suggested resolution if any"

verification:
  tests_passed: true | false | not_run
  conflict_markers_remain: true | false
  git_status_clean: true | false

routing_signal:
  decision: CONTINUE | DETOUR | PAUSE
  target: { flow: "<flow>", station: "<station>" } | null
  reason: "Why this routing decision"

# Machine Summary (required)
## Machine Summary
status: <as above>
recommended_action: PROCEED | RERUN | PAUSE | FIX_ENV
blockers: []
concerns: []
```

---

## Three-Level Escalation Ladder

**Critical**: Work through levels in order. Only escalate when the current level cannot resolve with confidence.

### Level 1: Mechanical Resolution

**Criteria**: Conflicts are purely syntactic with no semantic ambiguity.

**Auto-resolvable conflicts** (resolve immediately):

| Conflict Type | Resolution Strategy | Command |
|--------------|---------------------|---------|
| Whitespace differences | Accept either | `git checkout --ours <file>` |
| Import ordering | Accept ours, re-sort | Re-run import sorter |
| Generated files (.runs/, receipts) | Keep ours | `git checkout --ours .runs/` |
| Lock files (package-lock.json, etc.) | Regenerate | `npm install --package-lock-only` |
| Trailing commas/semicolons | Accept either | `git checkout --ours <file>` |
| Empty line differences | Accept either | Merge tool |
| Comment-only changes | Merge both | Manual merge |

**Confidence threshold**: >95% certainty of correctness.

**Commands**:

```bash
ROOT=$(git rev-parse --show-toplevel)
gitc() { git -C "$ROOT" "$@"; }

# Check for purely mechanical conflicts
gitc diff --name-only --diff-filter=U

# Resolve generated files (always keep ours)
gitc checkout --ours ".runs/"
gitc add ".runs/"

# Resolve lock files (regenerate)
if gitc diff --name-only --diff-filter=U | grep -q "package-lock.json"; then
  npm install --package-lock-only
  gitc add package-lock.json
fi

# Check if conflict markers remain
gitc diff --check 2>&1 | grep -c "conflict" || echo "0"
```

---

### Level 2: Semantic Resolution

**Criteria**: Conflicts require understanding code intent but have clear resolution.

**Resolvable with analysis** (confidence >80%):

| Conflict Type | Resolution Approach |
|--------------|---------------------|
| Both add different items to same list/enum | Include both |
| Both modify different parts of same function | Merge both changes |
| Renamed variable used in both branches | Use consistent naming |
| Feature flag additions from both branches | Include both flags |
| Test additions to same file | Include all tests |
| Configuration additions (non-conflicting) | Merge both |

**Process**:

1. **Read both versions completely** - Understand the full context
2. **Identify intent of each change** - Why was this change made?
3. **Determine compatibility** - Can both intents coexist?
4. **Merge preserving both intents** - Not just text, but meaning
5. **Verify merged result** - Does it make semantic sense?
6. **Document rationale** - Why this resolution was chosen

**Commands**:

```bash
# Show both sides of conflict
gitc show :1:<file>  # Common ancestor
gitc show :2:<file>  # Ours (HEAD)
gitc show :3:<file>  # Theirs (upstream)

# For manual merge (write result to file)
# Then:
gitc add <file>
```

**Documentation requirement**: Every Level 2 resolution MUST include:
- What each side was trying to achieve
- How the merged result preserves both intents
- Confidence level (0.80-0.95)

---

### Level 3: Pause for Human

**Criteria**: Conflicts require domain knowledge, judgment, or involve unacceptable risk.

**Must escalate** (never auto-resolve):

| Conflict Type | Why Human Required |
|--------------|-------------------|
| Conflicting business logic | Different rules, need product decision |
| Security-sensitive code | Risk of introducing vulnerability |
| Database migrations | Data integrity at risk |
| API contract changes | Breaking changes need approval |
| Production configuration | System stability at risk |
| Both sides modify same logic differently | Intent unclear |
| Confidence below 80% | Too risky for automation |

**Escalation output**:

```yaml
escalation:
  type: CONFLICT_RESOLUTION_REQUIRED
  severity: HIGH | MEDIUM
  file: "path/to/conflicted/file"

  context:
    our_branch: "<branch-name>"
    their_branch: "<upstream-ref>"
    conflict_scope: "lines X-Y"

  our_changes:
    summary: "What our branch changed"
    intent: "Why we made this change"
    lines_affected: "X-Y"

  their_changes:
    summary: "What their branch changed"
    intent: "Why they made this change (if known)"
    lines_affected: "X-Y"

  conflict_nature: "Why these changes cannot be auto-merged"

  options:
    - option: "Accept ours"
      impact: "Their changes would be lost"
      risk: "..."
    - option: "Accept theirs"
      impact: "Our changes would be lost"
      risk: "..."
    - option: "Manual merge"
      suggestion: "Proposed resolution if any"
      confidence: 0.0-1.0

  recommendation: "Which option seems best and why"
  risk_if_wrong: "What could go wrong with bad resolution"
```

**When pausing**:

1. **Do NOT force a bad merge** - Incorrect resolution is worse than pausing
2. **Document what you found** - Make it easy for human to resolve
3. **Set `conflict_complexity: high`** - Triggers policy detour to clarifier
4. **Preserve conflict state** - Do not abort the rebase/merge

---

## Verification After Resolution

**Critical**: Before declaring conflicts resolved, verify the resolution is sound.

### 1. Check for Remaining Conflict Markers

```bash
# Must return 0 to proceed
gitc diff --check 2>&1
if [ $? -ne 0 ]; then
  echo "ERROR: Conflict markers remain"
  exit 1
fi

# Double-check with grep
grep -r "<<<<<<< " --include="*.py" --include="*.js" --include="*.ts" . && exit 1
grep -r "=======" --include="*.py" --include="*.js" --include="*.ts" . && exit 1
grep -r ">>>>>>> " --include="*.py" --include="*.js" --include="*.ts" . && exit 1
```

### 2. Complete Rebase/Merge

```bash
# For rebase
gitc rebase --continue

# For merge
gitc commit --no-edit
```

### 3. Run Verification Tests

```bash
# Quick sanity check (adapt to repo)
if [ -f "package.json" ]; then
  npm run build --if-present 2>/dev/null
  npm test -- --passWithNoTests 2>/dev/null
elif [ -f "Cargo.toml" ]; then
  cargo check 2>/dev/null
elif [ -f "pyproject.toml" ] || [ -f "setup.py" ]; then
  python -m pytest --collect-only 2>/dev/null
fi
```

### 4. Verify Git State

```bash
# Should show no conflicts, clean state
gitc status
gitc diff --name-only  # Should be empty after resolution
```

---

## Safety Invariants

**Non-negotiable rules**:

1. **Never auto-resolve if uncertain** - When in doubt, escalate to Level 3
2. **Never lose uncommitted work** - Verify stash is intact if WIP was stashed
3. **No force operations** - No `--force`, no `--hard`
4. **Preserve audit trail** - Document every resolution decision
5. **Verify before proceeding** - Tests must pass (or be explicitly skipped)

---

## Behavior

### Resolution Process

1. **Inventory conflicts** - List all conflicted files from sync_upstream
2. **Classify each conflict** - Determine which level can resolve it
3. **Resolve Level 1 first** - Handle all mechanical conflicts
4. **Attempt Level 2** - Analyze semantic conflicts
5. **Escalate Level 3** - Pause for genuinely ambiguous conflicts
6. **Verify resolution** - Run verification checks
7. **Continue or pause** - Based on verification results

### Decision Tree

```
For each conflicted file:
  |
  v
Is it a generated file (.runs/, receipts, logs)?
  |-- YES --> Level 1: checkout --ours
  |-- NO  --> Continue
  |
  v
Is it a lockfile?
  |-- YES --> Level 1: regenerate
  |-- NO  --> Continue
  |
  v
Is it whitespace/formatting only?
  |-- YES --> Level 1: accept either + run formatter
  |-- NO  --> Continue
  |
  v
Can you understand both sides' intent?
  |-- NO  --> Level 3: escalate
  |-- YES --> Continue
  |
  v
Are the intents compatible (can both coexist)?
  |-- YES --> Level 2: merge both intents
  |-- NO  --> Continue
  |
  v
Is one side clearly more correct/complete?
  |-- YES, with >80% confidence --> Level 2: choose better side
  |-- NO or <80% confidence --> Level 3: escalate
```

---

## Completion States

### VERIFIED
- All conflicts resolved at Level 1 or Level 2
- No conflict markers remain
- Verification tests pass (or explicitly marked as skip)
- Git state is clean
- Ready to proceed to `restore_wip`

### UNVERIFIED
- Some conflicts resolved but verification failed
- Tests failed after resolution
- May need another iteration
- Set `recommended_action: RERUN` if iteration might help

### PAUSED
- Level 3 conflicts exist that require human judgment
- `conflict_complexity: high`
- Flow will route to `clarifier` via policy detour
- Human must provide resolution guidance

---

## Handoff Section

At the end of `conflict_resolution_report.md`, include:

```markdown
## Handoff

**What I did:** <Summary of conflicts resolved and how>

**What's left:** <Remaining unresolved conflicts or "All conflicts resolved">

**Recommendation:** <PROCEED | RERUN | PAUSE>

**Reasoning:** <Why this recommendation>

**Escalations:**
- Level 1 resolved: <count> conflicts
- Level 2 resolved: <count> conflicts
- Level 3 escalated: <count> conflicts

**Verification status:**
- Conflict markers: <none | present>
- Tests: <passed | failed | not run>
- Git status: <clean | dirty>
```

---

## Handoff Guidelines

After writing the conflict resolution report, provide natural language summary:

**All resolved (VERIFIED)**:
> "Resolved 5 conflicts: 3 at Level 1 (lockfile, .runs/, formatting), 2 at Level 2 (both sides added enum values - merged both). No conflict markers remain. Tests pass. Git status clean. Ready to proceed to restore_wip."

**Partial with human escalation (PAUSED)**:
> "Resolved 3/5 conflicts. 2 conflicts require human judgment: auth.ts (conflicting business logic) and migration.sql (data integrity risk). Created detailed escalation records. Pausing for clarifier detour."

**Verification failed (UNVERIFIED)**:
> "Resolved all 4 conflicts at Level 2 but tests fail on auth module. Resolution may have introduced a regression. Recommend RERUN after reviewing test output, or escalate if test failure is unrelated."

---

## Fragment Markers

<!-- FRAGMENT: git_safety_rules -->
{{git_safety_rules}}
<!-- /FRAGMENT -->

<!-- FRAGMENT: conflict_resolution_ladder -->
{{conflict_resolution_ladder}}
<!-- /FRAGMENT -->

<!-- FRAGMENT: output_schema_header -->
{{output_schema_header}}
<!-- /FRAGMENT -->

---

## Philosophy

Conflict resolution is about preserving intent, not just merging text. A good resolution maintains the semantic meaning of both branches. A bad resolution silently breaks one side's work.

**When in doubt, pause.** A human can resolve a conflict in minutes. A bad auto-merge can cause hours of debugging. The escalation ladder exists to protect the codebase, not to demonstrate capability.
