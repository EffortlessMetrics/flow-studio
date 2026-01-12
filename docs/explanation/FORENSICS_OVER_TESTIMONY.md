# Forensics Over Testimony: The Legal Epistemology

> **Status:** Living document
> **Purpose:** Apply evidence law principles to AI trust

## The Legal Principle

In court, evidence has a hierarchy:
1. **Physical evidence**: DNA, fingerprints, documents
2. **Expert testimony**: Forensic analysis, professional opinion
3. **Witness testimony**: What someone claims they saw
4. **Hearsay**: What someone heard someone else say

Courts trust physical evidence over testimony because:
- Physical evidence doesn't lie
- Witnesses can be mistaken
- Memory is unreliable
- Motivation affects claims

## The AI Application

Apply the same epistemology to AI systems:

| Legal | AgOps | Trust Level |
|-------|-------|-------------|
| Physical evidence | Command output, exit codes | Highest |
| Expert testimony | Forensic scanner analysis | High |
| Witness testimony | Agent claims | Low |
| Hearsay | Agent quoting another agent | Lowest |

## Why Agents are Unreliable Witnesses

### Sycophancy
Agents want to please. They claim success to make you happy.

### Confabulation
Agents fill gaps with plausible-sounding fiction.

### Overconfidence
Agents express certainty without basis.

### Memory Errors
Agents "remember" things that didn't happen in context.

These are not bugs. These are fundamental to how LLMs work.

## The Forensic Approach

Instead of asking agents what happened, **measure what happened**.

### Don't Ask: "Did tests pass?"
Agent might say "yes" regardless.

### Do Measure: `pytest --tb=short 2>&1 | tee test_output.log`
Exit code doesn't lie. Output file proves it.

### Don't Ask: "Is the code secure?"
Agent has no way to know.

### Do Measure: `bandit -r src/ -f json > security_scan.json`
Scanner output is evidence.

## The Sheriff Pattern (Revisited)

The Sheriff doesn't interview witnesses. The Sheriff:
1. Examines the crime scene (diffs, files)
2. Runs forensic tests (scanners, validators)
3. Collects physical evidence (outputs, logs)
4. Makes determinations based on evidence

The Navigator is the Sheriff. It routes based on forensics, not testimony.

## Evidence Hierarchy in Practice

### Tier 1: Physical Evidence (Trust Fully)
- Exit codes from processes
- File existence and content
- Git status and diffs
- Timestamps and hashes

### Tier 2: Forensic Analysis (Trust with Verification)
- Test parser output
- Coverage analyzer results
- Lint scanner findings
- Diff scanner summaries

### Tier 3: Agent Claims (Verify Before Trust)
- "I implemented the feature"
- "Tests should pass"
- "Code follows the spec"
- "Security is handled"

### Tier 4: Unanchored Assertions (Don't Trust)
- "Everything looks good"
- "I'm confident this works"
- "The code is high quality"
- "All requirements are met"

## The Cross-Examination Test

For any agent claim, apply cross-examination:

**Claim**: "Tests pass"
- Q: "What command did you run?"
- Q: "What was the exit code?"
- Q: "Where is the output file?"
- Q: "How many tests ran?"

If the agent can't answer with evidence, the claim is testimony without corroboration.

## Evidence Corroboration

Strong evidence corroborates claims:
```json
{
  "claim": "All tests pass",
  "corroboration": {
    "command": "pytest tests/ -v",
    "exit_code": 0,
    "output_file": "RUN_BASE/build/test_output.log",
    "summary": { "passed": 42, "failed": 0, "skipped": 3 }
  },
  "status": "CORROBORATED"
}
```

Uncorroborated claims:
```json
{
  "claim": "All tests pass",
  "corroboration": null,
  "status": "UNCORROBORATED"
}
```

## The Burden of Proof

In court, prosecutors must prove guilt beyond reasonable doubt.

In AgOps, claims must be proven with evidence:
- Agent makes claim
- Evidence must corroborate
- No evidence = claim rejected

The burden is on the claim, not on verification.

## The Rule

> Physical evidence beats agent testimony. Always.
> Forensic analysis beats agent claims. Always.
> Uncorroborated claims are not evidence.
> The Sheriff measures; the Sheriff doesn't ask.

## Implications

### For Routing
Route based on scanner output, not agent narrative.

### For Review
Check evidence files, not agent explanations.

### For Trust
Trust evidence-backed claims; question naked assertions.

### For Design
Build systems that produce evidence, not just claims.

## The Epistemological Foundation

This isn't cynicism about AI. It's epistemological rigor.

We don't trust human witnesses absolutely either. We corroborate.

AI systems deserve the same rigor:
- Claims need evidence
- Evidence needs verification
- Verification needs independence

This is how truth is established. In court. In science. In AgOps.
