## Machine Summary Block

Every critic and auditor output ends with a structured summary block. This enables orchestrator routing and audit trails.

### Standard Format

```yaml
---
status: VERIFIED | UNVERIFIED | CANNOT_PROCEED
recommended_action: PROCEED | RERUN | BOUNCE | FIX_ENV
route_to: <agent-id> | null
can_further_iteration_help: yes | no
---
```

### Field Definitions

| Field | Values | Purpose |
|-------|--------|---------|
| `status` | VERIFIED, UNVERIFIED, CANNOT_PROCEED | Verdict on work quality |
| `recommended_action` | PROCEED, RERUN, BOUNCE, FIX_ENV | What orchestrator should do |
| `route_to` | agent-id or null | Which agent handles next |
| `can_further_iteration_help` | yes, no | Controls microloop termination |

### Status Values

- **VERIFIED**: Work meets acceptance criteria. No CRITICAL or MAJOR issues.
- **UNVERIFIED**: Work attempted but issues remain. CRITICAL or MAJOR issues exist, or inputs were incomplete.
- **CANNOT_PROCEED**: Mechanical failure prevents work. IO/permissions block reading/writing required paths.

### Recommended Action Values

- **PROCEED**: Advance to next step in flow. Use when VERIFIED, or when UNVERIFIED but issues require human judgment.
- **RERUN**: Loop back to microloop partner. Use when UNVERIFIED and issues are fixable by author/implementer.
- **BOUNCE**: Return to upstream flow. Use when issues require design/spec changes, not implementation fixes.
- **FIX_ENV**: Environment issue blocks progress. Use with CANNOT_PROCEED for IO/tool failures.

### Route-to Values

Specify the agent that should handle the next action:

| Situation | route_to |
|-----------|----------|
| Requirements need fixes | `requirements-author` |
| Tests need fixes | `test-author` |
| Code needs fixes | `code-implementer` |
| Mechanical fixes only | `fixer` |
| Design issue | `design-optioneer` |
| Upstream framing broken | `problem-framer` |
| Needs clarification | `clarifier` |
| Ready for next phase | `null` |

### can_further_iteration_help Logic

This field controls whether the microloop continues:

**Set to `yes` when:**
- Author/implementer can address the issues in another pass
- Specific, actionable fixes exist
- Issues are within scope of the microloop partner

**Set to `no` when:**
- Issues require human judgment or product decisions
- Upstream changes are needed (spec, design, framing)
- No viable fix path exists within current constraints
- Work is already VERIFIED

### Example Blocks

#### Requirements Verified
```yaml
---
status: VERIFIED
recommended_action: PROCEED
route_to: null
can_further_iteration_help: no
---
```

#### Requirements Need Fixes
```yaml
---
status: UNVERIFIED
recommended_action: RERUN
route_to: requirements-author
can_further_iteration_help: yes
---
```

#### Tests Need Code Fix First
```yaml
---
status: UNVERIFIED
recommended_action: RERUN
route_to: code-implementer
can_further_iteration_help: yes
---
```

#### Design Issue Found
```yaml
---
status: UNVERIFIED
recommended_action: BOUNCE
route_to: design-optioneer
can_further_iteration_help: no
---
```

#### Human Decision Needed
```yaml
---
status: UNVERIFIED
recommended_action: PROCEED
route_to: null
can_further_iteration_help: no
---
```

#### Mechanical Failure
```yaml
---
status: CANNOT_PROCEED
recommended_action: FIX_ENV
route_to: null
can_further_iteration_help: no
---
```

### Placement in Output

The machine summary appears at the end of critique/audit files, after human-readable sections:

```markdown
# Test Critique

## Test Runner Summary
...

## Issues
...

## Handoff
...

---
status: UNVERIFIED
recommended_action: RERUN
route_to: test-author
can_further_iteration_help: yes
---
```

### Parsing Guidance

Orchestrator extracts the YAML block using:
1. Find last `---` delimiter pair
2. Parse as YAML
3. Use `status` for flow control
4. Use `recommended_action` + `route_to` for routing
5. Use `can_further_iteration_help` for loop termination

### Consistency Requirements

- `status: VERIFIED` implies `can_further_iteration_help: no`
- `status: CANNOT_PROCEED` implies `recommended_action: FIX_ENV`
- `recommended_action: RERUN` requires `route_to` to be set
- `recommended_action: BOUNCE` requires `route_to` to be set
