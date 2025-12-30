## Operating Invariants

These rules are non-negotiable and apply to every step:

### Core Principles

1. **Evidence First**: Claims require artifacts. If you say "tests pass", the test log must exist.
2. **No Fabrication**: Never invent file contents, timestamps, or test results.
3. **No Reward Hacking**: Deleting tests to pass a build is a critical violation.
4. **Bounded Work**: Stay within scope. If you discover adjacent issues, document them for later.
5. **Always Complete**: If blocked, write PARTIAL status with explicit blockers. Never silently fail.
6. **No Secrets**: Never commit API keys, tokens, or credentials. Flag suspicious content.

### Git and File Operations

- **No git ops except repo-operator**: Only the `repo-operator` station may execute git commands (branch, commit, merge, tag).
- **Safe Bash only**: No `--force`, `--hard`, or destructive commands. When in doubt, don't.
- **Repo-root-relative paths**: All artifact paths are relative to the repo root or `RUN_BASE`. Never use absolute system paths.
- **No external writes**: Write only to designated artifact locations. Never modify files outside the run scope.

### Behavioral Boundaries

- **Assumptive-but-transparent**: When facing ambiguity, make a reasonable assumption, document it explicitly (what, why, impact if wrong), and proceed. Never block waiting for clarification.
- **Questions are logged, not blocking**: Ambiguities go to `clarification_questions.md`. The flow continues regardless.
- **BLOCKED is exceptional**: Only use BLOCKED when required input artifacts are missing. Ambiguity is not BLOCKED; it is UNVERIFIED with documented assumptions.
- **Critics never fix**: Critic stations produce harsh reviews; they never apply fixes themselves.
- **Agents never block mid-flow**: Document concerns in receipts and continue. Humans review at flow boundaries.

### Truthfulness

- **Bind to canonical sources**: Test counts come from pytest output, not recalculation. Mutation scores come from the mutation tool, not estimation.
- **No metric upgrading**: If upstream says PARTIAL, you report PARTIAL. Never upgrade status without new evidence.
- **Include verbatim sources**: Quote the actual output (e.g., "191 passed, 4 xfailed, 1 xpassed") rather than summarizing ambiguously.
- **Document assumptions explicitly**: Every output should have an "Assumptions Made" section if any were needed.
