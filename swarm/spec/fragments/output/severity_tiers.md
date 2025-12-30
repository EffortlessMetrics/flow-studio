## Severity Tiers

Issue severity determines routing priority and loop exit conditions. Use consistent severity across all critics and auditors.

### Tier Definitions

| Tier | Meaning | Loop Impact |
|------|---------|-------------|
| **CRITICAL** | Blocks correctness, security, or contract compliance | Must fix before VERIFIED |
| **MAJOR** | Affects quality, completeness, or spec alignment | Should fix; may proceed with documented concerns |
| **MINOR** | Style, polish, or non-blocking improvements | Informational; does not affect status |

### CRITICAL (Must Fix)

Issues that prevent the work from being considered complete or correct.

**Requirements Critic:**
- Untestable requirement (no observable outcome)
- Contradictory requirements (same condition produces different outcomes)
- Duplicate IDs (REQ-### or NFR-* collision)
- Secret material present in requirements

**Test Critic:**
- Core REQ has no tests at all
- Tests fail for core functionality (not edge cases)
- Test runner cannot execute (environment broken)

**Code Critic:**
- Security vulnerability (auth bypass, injection, secret leak)
- Missing implementation for core REQ
- Contract violation (wrong status codes, missing required fields)
- ADR constraint violated (architecture rule broken)

**Gate/Audit:**
- Required receipt missing or invalid
- Policy violation (compliance, security scan failure)
- Unsigned or unattributed changes

### MAJOR (Should Fix)

Issues that affect quality or completeness but allow the work to function.

**Requirements Critic:**
- Vague criteria ("secure", "scalable", "appropriate" without bounds)
- Missing AC markers for testability
- Missing MET markers for NFR verification
- Untyped NFR ID (NFR-### instead of NFR-DOMAIN-###)
- Ambiguous language that changes behavior interpretation
- Missing error/edge handling for obvious cases

**Test Critic:**
- Weak assertions (status code only, no body validation)
- Missing edge case coverage
- xfailed tests that are not deferred/documented
- BDD scenario without corresponding test

**Code Critic:**
- ADR drift (implementation diverges from architecture decision)
- Missing edge case handling (boundaries, negative paths)
- Observability gaps (no metrics/logs where spec requires them)
- Error handling incomplete

**Gate/Audit:**
- Coverage threshold not met
- Test summary mismatch with claimed results
- Incomplete artifact chain

### MINOR (Informational)

Issues that are cosmetic or low priority. Do not affect status.

**Requirements Critic:**
- Non-sequential IDs (REQ-001, REQ-003, REQ-007)
- Naming inconsistencies
- Missing "Impact if wrong" on assumptions
- Format issues in questions

**Test Critic:**
- Test naming conventions
- Minor assertion improvements
- Code organization

**Code Critic:**
- Style issues (formatting, naming)
- Documentation gaps (not blocking functionality)
- Minor observability improvements

**Gate/Audit:**
- Artifact organization suggestions
- Process improvement notes

### Severity Assignment Rules

1. **Derive from impact**: Ask "What breaks if this is wrong?"
2. **Security is always CRITICAL**: No exceptions for auth/secrets issues
3. **Missing core work is CRITICAL**: If a REQ has no implementation or tests, CRITICAL
4. **Missing edge work is MAJOR**: If boundaries/errors are unhandled, MAJOR
5. **Style is always MINOR**: Never block on formatting or naming

### Severity and Status Relationship

| Severity Counts | Resulting Status |
|-----------------|------------------|
| Critical > 0 | UNVERIFIED (must fix) |
| Critical = 0, Major > 0 | UNVERIFIED (should fix) |
| Critical = 0, Major = 0 | VERIFIED (proceed) |

Minor issues are documented but do not affect status.

### Example Issue Format

```markdown
## Issues

### Testability
- [CRITICAL] REQ-001: No observable outcome - "system shall be secure" is not testable
- [MAJOR] REQ-003: Missing AC markers - acceptance criteria in paragraph form, not atomized

### Security
- [CRITICAL] src/auth.ts:45: Hardcoded API key in source code

### Coverage
- [MAJOR] REQ-005: No tests found for error handling path
- [MINOR] test_login: Consider adding assertion for token format
```
