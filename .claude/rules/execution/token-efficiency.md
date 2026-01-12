# Token Efficiency

Tokens are cheap but not free. Waste indicates design problems.

## The Principle

Every token should earn its place. Efficient token usage isn't about cost savings—it's about focus. Bloated context causes:
- Model drift from instructions
- Reduced reasoning quality
- Slower execution
- Budget overruns on long runs

## Input Efficiency

### Load Only What's Needed

The context discipline hierarchy:
1. **Critical** (always load): Teaching notes, step spec
2. **High** (load if budget): Previous step output
3. **Medium** (on-demand): Referenced artifacts
4. **Low** (if space remains): History summary

```python
# Good: Load specific artifact
load_artifact("RUN_BASE/plan/adr.md")

# Bad: Load everything "just in case"
load_directory("RUN_BASE/plan/")
```

### Summarize Before Loading

Large artifacts should be compressed before loading:

| Artifact Size | Action |
|---------------|--------|
| < 2k tokens | Load directly |
| 2k-10k tokens | Consider summary |
| > 10k tokens | Always summarize first |

Heavy context loaders exist for this reason:
- `context-loader`: 20-50k input → 2-5k structured output
- `impact-analyzer`: Full codebase scan → impact summary

### Use Paths, Not Contents

When referencing exists elsewhere:

```markdown
# Good: Path reference
See implementation in `src/auth.py:42-85`

# Bad: Inline content
Here's the implementation:
```python
def authenticate(user, password):
    # ... 50 lines of code ...
```
```

### Priority Loading Order

When budget is constrained:

```
1. Teaching notes (NEVER drop)
2. Step-specific spec (NEVER drop)
3. Previous step output (truncate if needed)
4. Referenced artifacts (load on-demand)
5. History/scent trail (drop first)
```

## Output Efficiency

### Structured Over Prose

```json
// Good: Structured output
{
  "status": "UNVERIFIED",
  "concerns": [
    { "severity": "HIGH", "file": "src/auth.py", "line": 42 }
  ]
}

// Bad: Prose output
"I found an issue in the authentication module. Specifically,
on line 42 of the src/auth.py file, there's a high severity
concern that needs to be addressed..."
```

### Evidence Pointers Over Inline Evidence

```markdown
# Good: Pointer
Test results: `RUN_BASE/build/test_output.log` (47 passed, 0 failed)

# Bad: Inline
Test results:
```
============================= test session starts ==============================
platform linux -- Python 3.11.0, pytest-7.4.0
collected 47 items

tests/test_auth.py::test_login PASSED
tests/test_auth.py::test_logout PASSED
... [45 more lines of output]
=============================== 47 passed in 2.31s =============================
```
```

### Diff Over Full File

When showing changes:

```diff
# Good: Diff
@@ -42,3 +42,5 @@
 def authenticate(user, password):
+    if not user or not password:
+        raise ValueError("Credentials required")
     return check_credentials(user, password)

# Bad: Full file with changes noted
"Here's the updated auth.py file: [entire 200-line file]"
```

### Receipts Are Compact By Design

Receipts capture:
- What happened (status, duration)
- Evidence pointers (paths to logs)
- Key metrics (counts, not raw output)

```json
{
  "tests": { "passed": 47, "failed": 0, "evidence": "test_output.log" },
  "lint": { "errors": 0, "evidence": "lint_output.log" }
}
```

NOT the full test output or lint report.

## Compression Patterns

### Heavy Loaders Compress for Downstream

The economics:
- One agent reads 50k tokens, produces 2k summary
- Ten downstream agents each receive 2k instead of 50k
- Math: 50k + (10 × 2k) = 70k vs. 10 × 50k = 500k

Heavy loading is a multiplier, not waste.

### Scent Trail Carries Decisions

What's in the scent trail:
- Key decisions made
- Why they were made
- What alternatives were rejected

What's NOT in the scent trail:
- Full reasoning chains
- Exploration of alternatives
- Abandoned approaches

```json
{
  "decisions": [
    {
      "step": "plan-step-3",
      "decision": "Use OAuth over API keys",
      "rationale": "User requested 'standard login'",
      "confidence": "HIGH"
    }
  ]
}
```

### Handoffs Carry What's Needed

Handoff envelopes include:
- What was done (summary)
- What was found (structured)
- Evidence pointers (paths)
- Routing recommendation

Handoffs exclude:
- Full reasoning
- Abandoned approaches
- Verbose explanations
- Repeated context

## Waste Patterns

### Loading Conversation History

**Wrong:** Rely on chat history for context
**Right:** Rehydrate from artifacts on disk

Session amnesia is a feature. Each step starts fresh and loads from artifacts.

### Repeating Instructions

**Wrong:** Include teaching notes in every message
**Right:** Teaching notes loaded once at step start

The kernel handles instruction loading. Agents don't re-inject.

### Verbose Explanations

**Wrong:**
```
"I have carefully analyzed the requirements and determined that
the best approach would be to implement authentication using
OAuth 2.0 because..."
```

**Right:**
```json
{ "decision": "OAuth 2.0", "rationale": "Matches 'standard login' requirement" }
```

Structured output is self-documenting.

### Full File Reads When Grep Would Do

**Wrong:** Read entire file to find one function
**Right:** Grep for function, read only relevant section

```bash
# Good: Targeted search
grep -n "def authenticate" src/auth.py

# Bad: Full file read
cat src/auth.py  # Then search in prompt
```

## Budget Allocation

### The 80/20 Split

| Category | Budget Share | Purpose |
|----------|--------------|---------|
| Work | 80% | Actual task execution |
| Coordination | 20% | Handoffs, routing, receipts |

If coordination exceeds 20%, the flow design is bloated.

### Context by Role

| Role | Context Budget | Rationale |
|------|----------------|-----------|
| Implementer | Higher | Needs codebase context |
| Critic | Lower | Focused on specific output |
| Navigator | Minimal | Compact forensics only |
| Reporter | Low | Summarization from artifacts |

Critics don't need the full implementation context—they review specific output.
Navigators don't need history—they route based on forensic metrics.

### Budget Pressure Points

| Flow Phase | Token Pressure | Mitigation |
|------------|----------------|------------|
| Signal | Low | Small inputs |
| Plan | Medium | Summarize research |
| Build | High | Use subagents for exploration |
| Gate | Medium | Compact forensics |
| Wisdom | High | Batch and summarize |

## Monitoring

### Track Tokens Per Step

Every receipt includes token counts:
```json
{
  "tokens": {
    "prompt": 12500,
    "completion": 3200,
    "total": 15700
  }
}
```

### Alert on Outliers

| Condition | Alert Level | Action |
|-----------|-------------|--------|
| Step > 2× flow average | Warning | Investigate bloat |
| Step > 3× flow average | Error | Redesign step |
| Coordination > 30% | Warning | Simplify handoffs |

### Identify Bloated Prompts

Common bloat sources:
- Full file contents instead of paths
- Repeated instructions across messages
- Verbose system prompts
- Unused context "just in case"

## The Rule

> Tokens are cheap but not free. Waste indicates design problems.

When you see:
- Steps consistently over budget → step scope too broad
- High coordination overhead → flow has too many steps
- Repeated content → context discipline failing
- Verbose outputs → structured schemas missing

These are design signals, not just cost issues.

## Anti-Patterns

### The Kitchen Sink
```
# Bad: Load everything
context = load_all_artifacts() + load_history() + load_related_files()
```

### The Narrator
```
# Bad: Verbose explanation
"Let me explain in detail what I'm about to do and why..."
```

### The Repeater
```
# Bad: Re-stating instructions
"As you asked me to do, I will now implement..."
```

### The Copy-Paster
```
# Bad: Full output inline
"Here are the complete test results: [500 lines of output]"
```

---

## See Also
- [context-discipline.md](./context-discipline.md) - Session amnesia rules
- [scent-trail.md](../artifacts/scent-trail.md) - Decision provenance
- [handoff-protocol.md](../artifacts/handoff-protocol.md) - Envelope structure
- [scarcity-enforcement.md](../governance/scarcity-enforcement.md) - Budgets as design
