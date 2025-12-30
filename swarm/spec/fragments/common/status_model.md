## Status Model

Every station ends with a status that drives routing decisions. Use the correct status for your situation.

### Status Enum

| Status | Meaning | When to Use |
|--------|---------|-------------|
| **VERIFIED** | Work is adequate for its purpose; requirements met | Tests pass, artifacts complete, no blocking issues |
| **UNVERIFIED** | Work attempted but issues remain | Tests fail, incomplete implementation, documented concerns |
| **PARTIAL** | Some progress made but blocked externally | Missing upstream artifacts, waiting on external system |
| **BLOCKED** | Cannot proceed due to missing inputs | Required input files do not exist (exceptional state) |

### Status Semantics

**VERIFIED** means:
- All required outputs exist and are correctly formed
- Tests pass (where applicable)
- Work meets the station's objective
- Assumptions documented but judged reasonable

**UNVERIFIED** means:
- Work was produced but has known issues
- Tests fail or coverage is insufficient
- Critic identified problems that need fixing
- Use with `can_further_iteration_help` to signal loop continuation

**PARTIAL** means:
- Some outputs created, others blocked
- External dependency unavailable
- Upstream station did not complete normally
- Different from UNVERIFIED: PARTIAL implies external cause

**BLOCKED** means:
- Cannot produce meaningful work
- Required input artifacts are missing or corrupted
- This is an **exceptional state** - most stations should not block

### BLOCKED is Exceptional

BLOCKED is reserved for **missing external dependencies**, not for ambiguity:

| Situation | Correct Status |
|-----------|----------------|
| Can read inputs, can form an opinion | VERIFIED or UNVERIFIED |
| Inputs ambiguous but present | UNVERIFIED with documented assumptions |
| Required input file does not exist | BLOCKED |
| Input file exists but corrupted/unparseable | BLOCKED |

**Rule**: If you can read your inputs and produce work, you are VERIFIED or UNVERIFIED, never BLOCKED.

### Iteration Control

When status is UNVERIFIED, the `can_further_iteration_help` field controls microloop behavior:

| Field Value | Meaning | Action |
|-------------|---------|--------|
| **yes** | Another iteration could fix remaining issues | Continue loop with same station |
| **no** | Issues require upstream changes or human intervention | Exit loop, advance with concerns |

**Loop Exit Conditions**:
- Exit when `status == VERIFIED`
- Exit when `status == UNVERIFIED` AND `can_further_iteration_help == no`
- Continue when `status == UNVERIFIED` AND `can_further_iteration_help == yes`

Be honest about iteration viability. Do not say "yes" indefinitely.

### Status in Handoff JSON

```json
{
  "status": "VERIFIED | UNVERIFIED | PARTIAL | BLOCKED",
  "summary": "Brief description of what was done",
  "can_further_iteration_help": "yes | no",
  "concerns": ["list of remaining issues if UNVERIFIED"],
  "assumptions": ["list of assumptions made if any"]
}
```

### No Status Upgrades Without Evidence

Downstream stations **consume** status; they do not upgrade it:

- If upstream says PARTIAL, report PARTIAL
- If critic says UNVERIFIED, do not change to VERIFIED without new evidence
- Reporters and reviewers reflect verdicts; they do not improve them

The only way to upgrade status is to produce new evidence (run tests, fix code, etc.).
