# Commit and PR Standards

Commits are audit artifacts. They must be atomic, traceable, and bisectable.

## Commit Message Format

### Subject Line

```
<type>: <description>
```

- **50 character limit** for subject line
- **Lowercase** after the colon
- **No period** at the end
- **Imperative mood**: "add feature" not "added feature"

### Types

| Type | Purpose | Example |
|------|---------|---------|
| `feat` | New feature or capability | `feat: add OAuth2 login flow` |
| `fix` | Bug fix | `fix: prevent null pointer in auth check` |
| `refactor` | Code change that neither fixes nor adds | `refactor: extract validation logic` |
| `docs` | Documentation only | `docs: update API reference` |
| `test` | Adding or fixing tests | `test: add edge cases for token refresh` |
| `chore` | Maintenance, deps, tooling | `chore: upgrade pytest to 8.0` |

### Body

The body explains **what** and **why**, not **how**.

```
feat: add rate limiting to API endpoints

Rate limiting prevents abuse and ensures fair resource allocation.
Current implementation uses token bucket algorithm with 100 req/min
per authenticated user.

Fixes #234
```

**Good body content:**
- Why this change is necessary
- What problem it solves
- What alternative approaches were considered
- Any non-obvious implications

**Bad body content:**
- Line-by-line code explanation
- Implementation details visible in diff
- "Updated file X" (obvious from diff)

### Issue References

| Syntax | Meaning | When to Use |
|--------|---------|-------------|
| `Fixes #123` | Closes issue on merge | Bug fixes, feature completion |
| `Closes #123` | Closes issue on merge | Same as Fixes |
| `Relates to #456` | Links without closing | Partial work, related context |
| `Part of #789` | Work toward larger issue | Incremental progress |

## PR Description Format

### Required Sections

```markdown
## Summary
- What this PR accomplishes (1-3 bullets)
- Key changes at a glance

## Test Plan
- How to verify this works
- Commands to run
- Expected outcomes

## Evidence
- Receipt paths: `RUN_BASE/build/receipts/...`
- Test output: `RUN_BASE/build/test_output.log`
- Coverage: X% (link to report)

## Risks/Concerns (if any)
- Known limitations
- Areas needing extra review
- Assumptions made
```

### Example PR Description

```markdown
## Summary
- Add token refresh mechanism for OAuth2 flow
- Handle refresh token expiration gracefully
- Add retry logic for transient failures

## Test Plan
1. Run `pytest tests/test_auth.py -v`
2. Verify all 12 new tests pass
3. Manual test: login, wait 5 min, verify auto-refresh

## Evidence
- Test receipt: `swarm/runs/abc123/build/receipts/step-5-test-author.json`
- Test output: 47 passed, 0 failed (see attached log)
- Coverage: 94% on auth module

## Risks/Concerns
- Refresh token storage assumes secure cookie context
- Rate limiting not yet implemented for refresh endpoint
```

## What Commits Must NOT Contain

### Multiple Unrelated Changes

```bash
# BAD: Kitchen sink commit
git commit -m "fix: auth bug, add logging, update deps, refactor utils"

# GOOD: Separate commits
git commit -m "fix: prevent null pointer in auth check"
git commit -m "feat: add structured logging to auth module"
git commit -m "chore: update cryptography to 42.0"
git commit -m "refactor: extract validation to separate module"
```

### Generated Files Without Source Changes

```bash
# BAD: Commit only the generated output
git add dist/bundle.js
git commit -m "chore: update bundle"

# GOOD: Commit source with generated files
git add src/app.ts dist/bundle.js
git commit -m "feat: add dashboard component"
```

### Secrets, Credentials, API Keys

```bash
# NEVER commit these:
API_KEY=sk-1234567890abcdef...
password: "hunter2"
aws_secret_access_key: AKIA...

# If committed accidentally:
# 1. Rotate the credential immediately
# 2. Use git filter-branch or BFG to remove from history
# 3. Force push (with approval at publish boundary)
```

### Large Binary Files

```bash
# BAD: Large binaries in repo
git add model.pkl  # 500MB
git add dataset.zip  # 2GB

# GOOD: Use Git LFS or external storage
git lfs track "*.pkl"
git add .gitattributes
```

## Atomic Commits

### One Logical Change Per Commit

| Commit | Content | Atomic? |
|--------|---------|---------|
| `feat: add user model` | Model + migration + tests | Yes (one feature) |
| `fix: auth + logging` | Two unrelated fixes | No (split them) |
| `refactor: extract utils` | Only the extraction | Yes (one refactor) |
| `chore: deps + config` | Dependencies + unrelated config | No (split them) |

### Tests Must Pass at Each Commit

```bash
# Bisectable history means:
git checkout HEAD~5  # Tests should pass
git checkout HEAD~3  # Tests should pass
git checkout HEAD~1  # Tests should pass
git checkout HEAD    # Tests should pass

# BAD pattern:
# commit 1: "feat: add feature (broken)"
# commit 2: "fix: make tests pass"

# GOOD pattern:
# commit 1: "feat: add feature" (tests pass)
```

### Why Bisectable History Matters

When debugging regressions:
```bash
git bisect start
git bisect bad HEAD
git bisect good v1.2.0
# Git binary searches to find the breaking commit
# Only works if each commit is valid
```

## Agent-Generated Commits

### Receipt References Required

Agent commits MUST include evidence pointers:

```
feat: implement OAuth2 callback handler

Implements the callback handler for OAuth2 authorization flow
as specified in ADR-005.

Receipt: swarm/runs/abc123/build/receipts/step-3-code-implementer.json
Tests: 12 passed, 0 failed
Coverage: 89% on new code

Fixes #234
```

### Pre-Commit Hooks Must Pass

Agents MUST NOT bypass hooks:

```bash
# NEVER use:
git commit --no-verify  # Skips hooks
git commit -n           # Same thing

# ALWAYS let hooks run:
git commit -m "feat: add feature"  # Hooks validate
```

### Subject Line Conventions

Agent commits use standard types, NOT automation markers:

```bash
# GOOD: Standard commit type
git commit -m "feat: add rate limiting to API"
git commit -m "fix: handle edge case in parser"

# BAD: Automation markers in subject
git commit -m "[AUTO] feat: add rate limiting"
git commit -m "AI: add rate limiting to API"
git commit -m "Generated: add rate limiting"
```

Automation is evident from the receipt reference in the body, not the subject.

## The Rule

> Commits are audit artifacts. Atomic, traceable, bisectable.
> PRs include evidence. Summary, test plan, receipts.
> Agent commits reference receipts. No hook bypasses.

## Examples: Good vs Bad

### Commit Messages

```bash
# BAD: Vague
git commit -m "fix stuff"

# BAD: Too long subject
git commit -m "fix: this commit fixes the bug where users couldn't log in when their session expired"

# BAD: Past tense
git commit -m "fix: fixed the login bug"

# BAD: No type
git commit -m "add rate limiting"

# GOOD: Clear, typed, imperative
git commit -m "fix: prevent session timeout during active use"
```

### PR Descriptions

```markdown
# BAD: No structure, no evidence
This PR adds some auth stuff. Please review.

# BAD: Implementation details, no test plan
This PR changes line 45 of auth.py to use a different hash.
Also updated line 102 to handle the new format.

# GOOD: Structured with evidence
## Summary
- Add bcrypt password hashing (replaces MD5)
- Migrate existing users on next login

## Test Plan
- Run `pytest tests/test_auth.py -v`
- Verify password upgrade on login

## Evidence
- Receipt: swarm/runs/xyz/build/receipts/step-3.json
- Tests: 23 passed

## Risks
- Migration is lazy (on login), not bulk
```

---

## See Also
- [git-safety.md](./git-safety.md) - Git operations by zone
- [boundary-automation.md](./boundary-automation.md) - Publish gate checks
- [receipt-schema.md](../artifacts/receipt-schema.md) - Receipt requirements
