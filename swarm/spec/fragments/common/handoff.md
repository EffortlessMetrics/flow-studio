## Handoff Protocol

Every step ends with a handoff file that enables:
- Routing decisions (where to go next)
- Context transfer (what the next station needs to know)
- Audit trail (what was done and why)

### Required Handoff Fields

```json
{
  "status": "VERIFIED | UNVERIFIED | PARTIAL | BLOCKED",
  "summary": "1-2 sentence description of what was accomplished",
  "artifacts": ["list", "of", "created", "or", "modified", "files"],
  "proposed_next_step": "station-id or null",
  "confidence": "high | medium | low",
  "can_further_iteration_help": "yes | no"
}
```

### Status Meanings

| Status | Meaning | Next Action |
|--------|---------|-------------|
| **VERIFIED** | Work complete, all requirements met | Advance to next step |
| **UNVERIFIED** | Work attempted but issues remain | Loop if `can_further_iteration_help: yes`, else advance with concerns |
| **PARTIAL** | Some progress, blocked externally | Advance with concerns, document blockers |
| **BLOCKED** | Cannot proceed, missing inputs | Escalate to orchestrator |

### Iteration Control: can_further_iteration_help

This field controls microloop termination:

- **yes**: Another iteration with the same station could fix remaining issues
  - Use when: tests can be fixed, code can be improved, concrete path forward exists
- **no**: Issues require upstream changes or human intervention
  - Use when: missing specs, design flaws, ambiguous requirements, no viable fix path

**Loop Exit Conditions**:
- Exit when `status == VERIFIED`
- Exit when `status == UNVERIFIED` AND `can_further_iteration_help == no`
- Continue when `status == UNVERIFIED` AND `can_further_iteration_help == yes`

Be honest about iteration viability. Don't say "yes" forever.

### Confidence Levels

- **high**: Strong evidence supports the work; claims are well-founded
- **medium**: Work is reasonable but some assumptions were made
- **low**: Significant uncertainty; assumptions documented but unverified

### Context for Next Station

Include in your summary:
1. What was done (concrete actions, not intentions)
2. What's still weak (known issues)
3. What assumptions were made (if any)
4. What the next station should focus on

### Artifact Paths

All paths in `artifacts` array should be:
- Relative to `RUN_BASE` (e.g., `build/impl_changes_summary.md`)
- Files that actually exist after your work
- Accurate (don't list files you didn't create)
