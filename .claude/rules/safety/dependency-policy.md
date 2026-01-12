# Dependency Policy

**Every dependency is a liability. Justify its existence.**

Dependencies are not free. Each one adds maintenance burden, security surface, and coupling to external maintainers. This policy defines when and how to add them.

## Before Adding a Dependency

Ask these five questions in order. If any answer is "no" or "unknown," stop and reconsider.

### 1. Is this solving a problem we actually have?

Not a problem we might have. Not a problem that sounds interesting. A problem we have **right now** that is blocking work.

**Red flags:**
- "We might need this later"
- "It's best practice"
- "Everyone uses it"

**Green flags:**
- "We tried without it and hit [specific blocker]"
- "The alternative is 200+ lines of error-prone code"

### 2. Can we solve it with existing deps or stdlib?

Check in this order:
1. **Standard library** - Python stdlib, Node built-ins, Go stdlib
2. **Existing dependencies** - Something already in the tree
3. **Copy-paste** - Small, stable code that won't change

Only after exhausting these: consider a new dependency.

### 3. Is the dependency maintained?

| Signal | Healthy | Concerning | Abandon |
|--------|---------|------------|---------|
| Last commit | < 6 months | 6-18 months | > 2 years |
| Open issues | Triaged, responded | Backlog growing | Ignored |
| Bus factor | 3+ maintainers | 1-2 maintainers | Solo + inactive |
| Release cadence | Regular | Sporadic | Stalled |

**Check:**
- GitHub/GitLab activity
- npm/PyPI download trends
- Issue response time

### 4. What's the security posture?

| Check | How | Acceptable |
|-------|-----|------------|
| Known vulns | `npm audit`, `pip-audit`, Snyk, Dependabot | Zero HIGH/CRITICAL unpatched |
| Audit history | Security advisories, CVE history | Responsive to past issues |
| Permissions | What does it access? | Minimal scope |
| Supply chain | Who owns it? Org vs individual? | Verifiable ownership |

**Blockers:**
- Known unpatched vulnerabilities (HIGH or CRITICAL)
- History of slow security response
- Unclear ownership or transfer history

### 5. What's the size impact?

| Metric | Check | Threshold |
|--------|-------|-----------|
| Direct size | Package size | Proportional to value |
| Transitive deps | `npm ls`, `pipdeptree` | < 10 new transitive deps |
| Bundle impact | Build before/after | < 5% increase for non-core |

**Red flags:**
- 50+ transitive dependencies for a utility function
- Pulls in framework-scale deps for small features
- Bundles native binaries unnecessarily

## Approval Requirements

### New Runtime Dependency

**Bar: HIGH** - These ship to production.

Required in PR:
- [ ] Answers to all five questions above
- [ ] Alternative approaches considered
- [ ] Size/security audit results
- [ ] Explicit reviewer approval

### New Dev Dependency

**Bar: MEDIUM** - These affect the build, not production.

Required in PR:
- [ ] Problem statement
- [ ] Why existing tools don't suffice
- [ ] Brief maintenance check

### Version Bumps

**Bar: VARIABLE** - Depends on change scope.

| Bump Type | Requirement |
|-----------|-------------|
| Patch (x.x.PATCH) | Changelog glance, CI green |
| Minor (x.MINOR.x) | Changelog review, test coverage |
| Major (MAJOR.x.x) | Breaking changes documented, migration tested |

## Banned Patterns

### Deps for Trivial Functions

**The left-pad rule:** If you can write it in < 20 lines and it won't change, don't import it.

```javascript
// BAD: Adding a dep for this
import leftPad from 'left-pad';

// GOOD: Just write it
const leftPad = (str, len, ch = ' ') =>
  str.padStart(len, ch);
```

### Unmaintained Dependencies

No commits in 2+ years = abandoned. Exceptions require:
- Explicit acknowledgment of risk
- Plan for maintenance if upstream dies
- Fork readiness

### Known Unpatched Vulnerabilities

Zero tolerance for HIGH/CRITICAL unpatched CVEs in runtime deps.

Dev deps: case-by-case, but document the risk.

### Massive Transitive Trees

If a utility pulls 100+ transitive deps, the cost exceeds the benefit. Find an alternative or write it yourself.

## Preferred Patterns

### Stdlib Over External

```python
# PREFERRED: stdlib
import json
from pathlib import Path
from dataclasses import dataclass

# AVOID: external for stdlib-equivalent
import simplejson  # json works fine
import pathlib2    # use stdlib pathlib
import attrs       # dataclasses exist
```

### Focused Deps Over Frameworks

```javascript
// PREFERRED: focused utility
import slugify from 'slugify';  // Does one thing

// AVOID: kitchen sink
import lodash from 'lodash';    // 99% unused
```

If you need 2-3 lodash functions, import them individually or copy them.

### Pinned Versions Over Ranges

```json
// PREFERRED: exact versions
"dependencies": {
  "express": "4.18.2"
}

// RISKY: ranges
"dependencies": {
  "express": "^4.18.2"
}
```

Ranges invite surprise breakage. Pin versions, update deliberately.

### Lock Files Committed

Always commit:
- `package-lock.json` (npm)
- `uv.lock` / `poetry.lock` (Python)
- `go.sum` (Go)

Lock files ensure reproducible builds. Never gitignore them.

## When to Remove Dependencies

### No Longer Used

Dead code detection should include dead deps. If nothing imports it, remove it.

```bash
# Check for unused deps
npx depcheck
pip-extra-reqs .
```

### Better Alternative Exists

When stdlib catches up or a better-maintained option emerges, migrate.

Example: `moment.js` → `date-fns` or native `Intl`

### Security Concerns

Unpatched vulnerabilities with no fix timeline = remove or fork.

### Maintenance Abandoned

Upstream stopped responding to issues/PRs = assess risk, plan exit.

## The Economics

| Cost | Description |
|------|-------------|
| **Install time** | Every CI run, every dev setup |
| **Update burden** | Security patches, breaking changes |
| **Debug surface** | More code = more places bugs hide |
| **Supply chain risk** | Compromised upstream = compromised you |
| **Cognitive load** | Another API to learn, another changelog to read |

Benefits must exceed these costs. For trivial utilities, they rarely do.

## The Rule

> Every dependency is a liability. Justify its existence.
> Prefer stdlib. Prefer existing deps. Prefer copy-paste.
> When you must add one: maintain it like your own code.

## Enforcement

Dependency changes are reviewed for:
- Justification present in PR
- Five questions answered
- No banned patterns
- Lock file updated

Automated checks:
- `npm audit` / `pip-audit` in CI
- Dependabot / Renovate for updates
- Bundle size tracking (if applicable)

---

## See Also
- [git-safety.md](./git-safety.md) - Safe operations for dependency updates
- [boundary-automation.md](./boundary-automation.md) - Supply chain at publish boundary
