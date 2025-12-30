## Critics Never Fix

This is a core microloop invariant: **critics critique; they never fix**.

### The Separation

In a microloop, two roles alternate:
- **Writer**: Creates or improves artifacts (requirements-author, test-author, code-implementer, bdd-author)
- **Critic**: Reviews artifacts and produces harsh critiques (requirements-critic, test-critic, code-critic, bdd-critic)

The critic's job is to **find the flaw**. The writer's job is to **fix it**.

### Why Critics Don't Fix

1. **Auditability**: When changes happen, you know which agent made them. If critics could fix, you couldn't trace whether a change came from implementation or review.

2. **Separation of concerns**: The critic's judgment about what's wrong is distinct from the skill of fixing it. A critic might correctly identify a security issue but propose a flawed fix.

3. **No reward hacking**: If critics could fix, they might be tempted to "fix" issues by weakening tests, deleting coverage, or adjusting requirements to match implementation. Critics that only critique cannot cheat.

4. **Clean handoffs**: The writer receives a critique and knows exactly what to address. The writer doesn't have to untangle "what did the critic change vs. what did I write?"

5. **Predictability**: The orchestrator knows what each station will and won't do. Critics produce reports. Writers produce artifacts.

### What Critics DO

Critics write harsh, specific reports:
- Identify issues with severity (CRITICAL, MAJOR, MINOR)
- Point to specific evidence (file, line, section, symbol)
- Explain what's wrong and why it matters
- Suggest what "good" looks like (without implementing it)
- Set status and iteration guidance
- Route to the appropriate agent for fixes

### What Critics DO NOT

Critics never:
- Modify the artifact they're reviewing
- Write code, tests, or requirements themselves
- "Fix" issues by editing files
- Delete or weaken tests to make them pass
- Upgrade status to make progress look better
- Apply mechanical fixes (even "obvious" ones)

### The Critique Output

A critic produces exactly one artifact: their critique file.

```
requirements-critic  -> requirements_critique.md
test-critic          -> test_critique.md
code-critic          -> code_critique.md
bdd-critic           -> bdd_critique.md
design-critic        -> design_validation.md
```

The critique contains:
- Issue inventory with severity levels
- Evidence pointers (where the issue is)
- Guidance (what the fix should accomplish)
- Routing (who should fix it)
- Iteration control (can the writer fix it, or is it upstream?)

### Providing Guidance Without Fixing

Critics should explain what the fix should accomplish without writing the fix:

**Good critique (explains what to fix):**
```markdown
- [MAJOR] tests/auth.test.ts::test_login - only checks status code 200, not response body.
  Can't verify REQ-001 claim that JWT is returned.
  Fix: add assertion for `response.body.token` existence and format.
```

**Bad critique (too vague):**
```markdown
- [MAJOR] tests/auth.test.ts::test_login - weak assertions
```

**Also bad (actually fixes):**
```markdown
- [MAJOR] tests/auth.test.ts::test_login - weak assertions.
  I've added the assertion `expect(response.body.token).toMatch(/^eyJ/)` at line 47.
```

### Routing for Fixes

When issues need fixing, the critic routes to the appropriate agent:

| Issue Type | Route To |
|------------|----------|
| Implementation gaps | code-implementer |
| Test coverage gaps | test-author |
| Requirements ambiguity | requirements-author |
| BDD scenario issues | bdd-author |
| Design flaws | design-optioneer, interface-designer |
| ADR clarity | adr-author |
| Mechanical fixes (lint, format) | fixer, gate-fixer |

### Philosophy

The critic's harshness protects the codebase. If a test is weak, say "this test is weak." If a requirement has no implementation, say "REQ-042 has no implementation." If the ADR says "use JWT" and the code uses sessions, say "ADR violation: using sessions instead of JWT."

Cite specific locations. Explain why it matters. The writer can take it.

The critic who never fixes is the critic who never lies. Their reports are pure signal about the state of the artifacts. When they say VERIFIED, you can trust it - they didn't massage the code to make it pass.

### Enforcement

This separation is enforced by:
1. **Lane discipline**: Critics are in the "Critic" category, which can "Review and critique, set status" but cannot "Fix code, modify tests, apply changes"
2. **Output contracts**: Critics produce exactly one file (their critique), not modified source files
3. **Tool constraints**: Critics don't need Write/Edit tools on source directories
4. **Orchestrator routing**: The orchestrator calls the writer after the critic, never expects the critic to have made changes

If you're a critic and you find yourself wanting to "just fix this one thing" - stop. Write it in your critique and route to the writer. That's the system working as designed.
