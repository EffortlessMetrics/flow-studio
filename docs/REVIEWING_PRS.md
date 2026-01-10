# Reviewing PRs from Flow Studio

> **Purpose:** Operator guide for reviewing PRs produced by Flow Studio.
> Use this to review efficiently without reading every line.

---

## The 5-Question Reviewer Contract

A Flow Studio PR should be reviewable in 5-10 minutes by answering these questions:

| # | Question | Where to Look |
|---|----------|---------------|
| 1 | **Did tests pass?** | Evidence section (test receipts, CI status) |
| 2 | **Are boundaries respected?** | Quality Events (interface locks, layering checks) |
| 3 | **What's the risk assessment?** | Summary or Concerns section |
| 4 | **What wasn't measured?** | Not Measured section (explicit gaps) |
| 5 | **Do I trust the evidence?** | Spot-check hotspots against receipts |

If any question is unanswerable from the PR body, the PR cockpit is incomplete. Request it be regenerated.

---

## The PR Cockpit Template

Flow Studio PRs use a standard body format:

```markdown
## Summary

[1-3 sentences: what changed and why]

## Hotspots

Files or areas requiring focused review:
- `src/auth/session.ts` — New session validation logic
- `tests/auth/` — Coverage for edge cases
- `migrations/003_add_token_table.sql` — Schema change

## Quality Events

| Event | Type | Evidence |
|-------|------|----------|
| Interface lock respected | Observed | No changes to `api_contracts.yaml` |
| Tests pass | Observed | `test_summary.md`: 47 passed, 0 failed |
| Lint clean | Observed | `auto-linter` exit 0 |
| Security scan | Observed | `security_scan.md`: 0 HIGH, 0 CRITICAL |

## Evidence

- Build receipt: `RUN_BASE/build/build_receipt.json`
- Test summary: `RUN_BASE/build/test_summary.md`
- Gate audit: `RUN_BASE/gate/merge_decision.md`

## Not Measured

- Performance impact (no load tests in this flow)
- Cross-browser compatibility (manual QA recommended)
- Observability coverage (metrics not yet instrumented)
```

### Section Breakdown

| Section | Purpose | Reviewer Action |
|---------|---------|-----------------|
| **Summary** | Quick orientation | Understand scope in 10 seconds |
| **Hotspots** | Focus review attention | Read these 3-8 files; skip the rest |
| **Quality Events** | What quality was verified | Check "Type" column for Observed vs Prevented |
| **Evidence** | Links to receipts | Spot-check 1-2 receipts for consistency |
| **Not Measured** | Explicit gaps | Decide if gaps are acceptable for this change |

---

## Observed vs Prevented

**The rule: Never claim "prevented" without before/after evidence.**

| Type | Meaning | Evidence Required |
|------|---------|-------------------|
| **Observed** | We saw this happen | Log, receipt, or exit code showing the event |
| **Prevented** | We have evidence drift was stopped | Before/after comparison OR explicit blocking check |

### Examples

**Observed (valid claims):**
- "Tests pass" — `test_summary.md` shows 47 passed, 0 failed
- "Lint clean" — `auto-linter` exited with code 0
- "Security scan clean" — `security_scan.md` shows 0 HIGH findings
- "Interface stable" — No files in `contracts/` were modified

**Prevented (requires before/after):**
- "Dependency drift prevented" — Before: `package-lock.json` hash X. After: same hash.
- "Breaking change prevented" — Contract diff shows API was unchanged despite implementation changes
- "Test regression prevented" — Mutation testing caught a gap and we added the missing test

**Invalid claims (don't use):**
- "Prevented bugs" — Not measurable without a counterfactual
- "Improved security" — Claim must be specific and observable
- "Quality improved" — Too vague; break down into observable events

### Why This Matters

Reviewers trust observed facts, not aspirational claims. If you claim "prevented," show the check that would have caught the drift and prove it ran.

---

## Review Workflow

Quick checklist for reviewing a PR cockpit:

### 1. Read the Summary (30 seconds)
- [ ] Do I understand what changed?
- [ ] Is the scope appropriate for one PR?

### 2. Scan Quality Events (1 minute)
- [ ] Are all events marked "Observed" (not aspirational)?
- [ ] Do the events cover the expected checks (tests, lint, security)?
- [ ] Any "Prevented" claims with proper before/after evidence?

### 3. Check Not Measured (30 seconds)
- [ ] Are the gaps acceptable for this change?
- [ ] Any gaps that should block merge?

### 4. Spot-Check Hotspots (3-5 minutes)
- [ ] Open 2-3 hotspot files
- [ ] Do the changes match what Summary claims?
- [ ] Any obvious issues not caught by automation?

### 5. Verify Evidence (1 minute)
- [ ] Open 1 receipt (e.g., `build_receipt.json`)
- [ ] Does it match the Quality Events claimed?
- [ ] Is the receipt recent (check timestamps)?

### Decision

| Outcome | When |
|---------|------|
| **Approve** | All 5 questions answered, spot-checks pass |
| **Request Changes** | Gaps in Not Measured are unacceptable, or evidence doesn't match claims |
| **Request Regeneration** | PR cockpit is incomplete or missing sections |

---

## Red Flags

Watch for these signals that warrant deeper review:

| Flag | What it means |
|------|---------------|
| Empty "Not Measured" | Either nothing was omitted (suspicious) or section wasn't filled |
| "Prevented" without evidence | Aspirational claim, not forensic fact |
| Hotspots missing | Reviewer doesn't know where to look |
| Test count decreased | Possible test deletion to make CI pass |
| Receipt timestamps old | Evidence may not reflect current code |
| No security scan | Should be present for any code-touching PR |

---

## See Also

- [MERGE_CHECKLIST.md](./MERGE_CHECKLIST.md) — Pre-merge checklist for authors
- [DEFINITION_OF_DONE.md](./DEFINITION_OF_DONE.md) — What "done" means
- [AGOPS_MANIFESTO.md](./AGOPS_MANIFESTO.md) — Section 11 covers the review contract
- [LEXICON.md](./LEXICON.md) — Canonical vocabulary
