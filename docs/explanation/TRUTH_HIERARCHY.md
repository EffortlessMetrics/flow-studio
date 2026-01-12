# Truth Hierarchy: What Counts as Evidence

> **Status:** Living document
> **Purpose:** Teaching doc for the evidence hierarchy

## The Problem

LLMs are **convincing narrators**. They don't produce gibberish—they produce
*plausible-sounding claims that may be wrong*. The failure mode is not noise;
it's **confident errors**.

Traditional approaches try to solve this with:
- Better prompting (still narrative-based)
- Chain of thought (still narrative-based)
- Multi-agent debate (narrative + narrative = more narrative)

None of these produce **ground truth**. They produce more elaborate stories.

## The Solution: Truth Hierarchy

Flow Studio uses an explicit hierarchy of truth. When sources conflict,
higher levels override lower levels.

### Level 1: Physics (Highest Trust)

**What it is:** Observable state from the operating system, runtime, or tooling.

**Examples:**
- Exit codes (pytest returned 0 or 1)
- File existence and hashes
- Git status and commit SHA
- Process output

**Why it's trusted:** Physics can't be hallucinated. Either the file exists or it doesn't.
Either the test passed or it didn't.

**Override:** Nothing. Physics is ground truth.

### Level 2: Receipts

**What it is:** Captured outputs of physics, stored as artifacts.

**Examples:**
- Test output logs
- Coverage reports
- Lint scan results
- Diff summaries

**Why it's trusted:** Receipts are recorded physics. They're reproducible.
Run the command again and you get the same result.

**Override:** Only by re-running the command.

### Level 3: Intent

**What it is:** Human-authored specifications of what should happen.

**Examples:**
- BDD scenarios
- ADRs (Architecture Decision Records)
- Contract interfaces
- Teaching notes

**Why it's trusted:** Humans authored these with deliberate intent.
They're the "spec" that work is measured against.

**Override:** Physics/receipts showing the spec doesn't match reality.

### Level 4: Generated Artifacts

**What it is:** Code, tests, and documentation produced by agents.

**Examples:**
- Source code files
- Test files
- Documentation
- Configuration

**Why it's trusted:** These are concrete deliverables that can be verified.
They exist on disk and can be tested.

**Override:** Anything above. Specs define what artifacts should do.
Physics/receipts prove what they actually do.

### Level 5: Narrative (Lowest Trust)

**What it is:** Agent explanations, chat output, reasoning traces.

**Examples:**
- "Tests passed successfully"
- "I implemented all requirements"
- "The code is secure"
- "Everything looks good"

**Why it's NOT trusted:** These are claims without evidence.
The agent might be right. It might be hallucinating.

**Override:** Everything. Narrative is advisory, not authoritative.

## The Epistemology

The hierarchy encodes a simple epistemology:

> **Observable state > Recorded state > Intended state > Produced state > Claimed state**

Or more simply:

> **What happened > What we recorded > What we wanted > What we built > What we said**

## Practical Implications

### Routing Decisions

The Navigator (router) makes decisions based on **levels 1-3**.
It NEVER relies on level 5 (narrative) for routing.

Bad: "The agent said tests passed, so advance."
Good: "pytest returned exit code 0 with 42 tests, so advance."

### Critic Behavior

Critics compare **levels 3 and 4** (intent vs artifacts) using **level 1-2**
evidence (physics/receipts).

Bad: "The code looks like it implements the spec."
Good: "Function `validate_token` at `src/auth.py:42` is missing the error
handling required by ADR-001 section 3.2."

### Receipt Content

Receipts include evidence pointers so claims can be verified:

```json
{
  "tests": {
    "claim": "All tests passed",
    "evidence": {
      "command": "pytest tests/ -v",
      "exit_code": 0,
      "output_path": "RUN_BASE/build/test_output.log"
    }
  }
}
```

### "Not Measured" is Valid

When something isn't measured, say so explicitly:

```json
{
  "security_scan": {
    "measured": false,
    "reason": "No SAST tool configured for this project"
  }
}
```

This is honest. False certainty is not.

## The Sheriff Pattern

Flow Studio implements the "Sheriff" pattern:

1. **Workers** do work and produce narrative
2. **Sheriff** (kernel) runs forensic tools (DiffScanner, TestParser)
3. **Navigator** makes decisions based on forensic evidence
4. Narrative is ignored for routing decisions

The Sheriff doesn't trust workers. The Sheriff measures the output.

> **"Don't listen to the worker; measure the bolt."**

## Contradiction Resolution

When levels conflict, higher levels win:

| Conflict | Resolution |
|----------|------------|
| Narrative says "tests pass" but pytest fails | Trust pytest (physics) |
| Receipt says 0 errors but lint tool finds 5 | Re-run lint, trust fresh physics |
| Spec says X but code does Y | Code is wrong, not spec (unless spec is outdated) |
| Code says it does X but tests show Y | Trust tests (physics over artifact) |

## Why This Matters

This hierarchy is what makes autonomous operation **trustworthy**.

Without it, you have:
- Black box systems that claim success
- No way to verify claims
- Review requires reading everything

With it, you have:
- Transparent evidence trails
- Verifiable claims
- Review focuses on hotspots flagged by evidence

The hierarchy is the **physics** that makes the factory safe.
