## Iteration Control

Microloops exit based on explicit signals in the critic's handoff. This section defines the `can_further_iteration_help` semantics and loop exit conditions.

### The Core Question

When you finish your critique, answer honestly: **Can another iteration with the writer actually fix the remaining issues?**

This controls whether the orchestrator loops back to the writer or advances the flow.

### Field Semantics

```yaml
can_further_iteration_help: yes | no
```

**yes** - The remaining issues are within the writer's power to fix:
- Missing acceptance criteria markers (writer can add them)
- Vague language that needs concrete values (writer can specify)
- Missing test coverage for in-scope requirements (writer can add tests)
- Implementation gaps for defined requirements (writer can implement)
- Format violations that the prompt already defines (writer knows the fix)

**no** - The remaining issues require something outside the writer's control:
- Requirements are ambiguous or contradictory (needs upstream clarification)
- Design decisions not made in ADR (needs design-optioneer or human)
- Missing upstream artifacts (needs prior flow to run)
- Human judgment or business decisions needed
- Issues are purely informational (MINOR polish, no action needed)
- Writer has already addressed these points but you still disagree on judgment calls

### Loop Exit Conditions (Canonical)

The orchestrator uses these rules:

| Status | can_further_iteration_help | Action |
|--------|---------------------------|--------|
| VERIFIED | (ignored) | Exit loop, advance to next step |
| UNVERIFIED | yes | Loop: call writer again with your critique |
| UNVERIFIED | no | Exit loop, advance with concerns documented |
| BLOCKED | (ignored) | Exit loop, escalate to orchestrator |

**Key insight**: `can_further_iteration_help: no` is not failure. It means the loop has done what it can; remaining issues need different intervention.

### When to Say Yes

Say `yes` when:
- You found concrete, actionable issues the writer can fix
- The fix is within the writer's documented scope and capabilities
- Rerunning the writer with your critique as context will likely help
- You are seeing the same issue pattern for the first time (give the writer a chance)

Example scenarios:
- "REQ-003 has no implementation found" - writer can implement it
- "Missing AC markers for REQ-005" - writer can add them
- "Test only checks status code, not response body" - writer can strengthen assertion
- "Interface-coupled step without justification comment" - writer can add comment or rewrite step

### When to Say No

Say `no` when:
- Issues require upstream changes (requirements, ADR, contracts)
- Issues require human judgment or product decisions
- The writer has already attempted to fix this and you still disagree
- Remaining issues are MINOR polish that don't block progress
- You're blocked waiting for artifacts that don't exist
- The issue is a design flaw, not an implementation gap

Example scenarios:
- "REQ-008 is vague about error handling - says 'appropriate error'" - needs requirements-author
- "NFR-PERF-001 cannot be verified without load testing infrastructure" - needs human decision
- "ADR doesn't specify which option was chosen" - needs adr-author
- "Contract endpoint doesn't match requirement intent" - needs interface-designer
- "Only minor naming suggestions remain" - no further iteration needed

### Avoiding Infinite Loops

Be honest about iteration viability:
- Don't say `yes` forever hoping the writer will eventually get it right
- If you've seen the same issue twice, the writer may not understand the fix
- If your critique is unclear, the issue may be your guidance, not the writer's work
- If the issue requires judgment calls, that's `no` - humans decide at flow boundaries

### Example Handoff Patterns

**Iteration should continue (yes):**
```markdown
## Handoff

**What I found:** 3 critical issues - REQ-003 missing implementation, REQ-005 has weak assertions (status code only), REQ-007 missing error path test.

**What's left:** All issues are implementable by the writer.

**Can further iteration help:** Yes - these are concrete gaps the writer can address.

**Recommendation:** Run code-implementer to add REQ-003 implementation and error handling, then run test-author to strengthen assertions for REQ-005 and add REQ-007 error path test.
```

**Iteration should stop (no - upstream issue):**
```markdown
## Handoff

**What I found:** REQ-004 specifies "appropriate timeout" but doesn't define what timeout value is appropriate. Cannot write a concrete assertion.

**What's left:** Requirements ambiguity blocks testable scenarios.

**Can further iteration help:** No - the issue is in requirements.md, not the writer's work.

**Recommendation:** Route to requirements-author to clarify timeout value, then rerun this microloop.
```

**Iteration should stop (no - only minor issues):**
```markdown
## Handoff

**What I found:** All critical requirements have coverage. Only minor issues: test naming conventions, some redundant comments.

**What's left:** Polish only; nothing blocks implementation.

**Can further iteration help:** No - remaining issues are minor and don't require iteration.

**Recommendation:** Proceed to next step. Minor issues can be addressed opportunistically.
```

### Integration with Status

The `can_further_iteration_help` field works with `status`:

- **VERIFIED + (any)**: Work is complete. Exit loop.
- **UNVERIFIED + yes**: Work has issues the writer can fix. Loop.
- **UNVERIFIED + no**: Work has issues outside the writer's control. Exit loop, document concerns.
- **BLOCKED + (any)**: Cannot proceed due to missing inputs. Exit loop, escalate.

Never set `BLOCKED` just because iteration cannot help. `BLOCKED` is for IO/permissions failures or missing required input files, not for upstream ambiguity or judgment calls.
