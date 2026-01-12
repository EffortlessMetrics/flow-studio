# Handoff Protocol

Handoffs transfer state between steps. They are the routing surface.

## Handoff Envelope Structure

Every step produces a handoff envelope:

```json
{
  "meta": {
    "step_id": "string",
    "flow_key": "string",
    "agent_key": "string",
    "timestamp": "ISO8601"
  },
  "status": "VERIFIED | UNVERIFIED | BLOCKED",
  "summary": {
    "what_i_did": "string",
    "what_i_found": "string",
    "key_decisions": ["string"],
    "evidence": {
      "artifacts_produced": ["path"],
      "commands_run": ["command"],
      "measurements": {}
    }
  },
  "concerns": [
    {
      "severity": "HIGH | MEDIUM | LOW",
      "description": "string",
      "location": "file:line (optional)",
      "recommendation": "string"
    }
  ],
  "assumptions": [
    {
      "assumption": "string",
      "why": "string",
      "impact_if_wrong": "string"
    }
  ],
  "routing": {
    "recommendation": "CONTINUE | LOOP | DETOUR | ESCALATE",
    "next_step_suggestion": "string (optional)",
    "can_further_iteration_help": "boolean (for critics)",
    "reason": "string"
  }
}
```

## Status Meanings

| Status | Meaning | Routing Implication |
|--------|---------|---------------------|
| **VERIFIED** | Work complete, requirements met | Advance to next step |
| **UNVERIFIED** | Work complete, concerns documented | Critic decides if loop helps |
| **BLOCKED** | Cannot proceed | Human intervention needed |

## Handoff Content by Role

### Implementer → Critic
```json
{
  "summary": {
    "what_i_did": "Implemented REQ-001 through REQ-005",
    "evidence": {
      "artifacts_produced": ["src/auth.py", "tests/test_auth.py"],
      "commands_run": ["pytest tests/test_auth.py -v"]
    }
  },
  "status": "UNVERIFIED",
  "routing": {
    "recommendation": "CONTINUE",
    "reason": "Ready for review"
  }
}
```

### Critic → Implementer (Loop)
```json
{
  "summary": {
    "what_i_found": "3 issues found"
  },
  "concerns": [
    {
      "severity": "HIGH",
      "description": "Missing input validation",
      "location": "src/auth.py:42",
      "recommendation": "Add validation before database query"
    }
  ],
  "status": "UNVERIFIED",
  "routing": {
    "recommendation": "LOOP",
    "can_further_iteration_help": true,
    "reason": "Issues are fixable, iteration will help"
  }
}
```

### Critic → Next Step (Exit Loop)
```json
{
  "summary": {
    "what_i_found": "Implementation meets requirements"
  },
  "concerns": [],
  "status": "VERIFIED",
  "routing": {
    "recommendation": "CONTINUE",
    "can_further_iteration_help": false,
    "reason": "No issues found"
  }
}
```

## File Placement

Handoff envelopes are written to:
```
RUN_BASE/<flow>/handoffs/<step_id>-<agent_key>.json
```

Draft versions (during work):
```
RUN_BASE/<flow>/handoffs/<step_id>-<agent_key>.draft.json
```

## JIT Finalization

Workers are bad at paperwork. Handoff envelopes are extracted via
Just-In-Time Finalization:

1. Work phase completes
2. Kernel injects finalization prompt into same session
3. Hot context enables accurate extraction
4. Structured output schema enforces format

## The Rule

> Handoffs are the routing surface. They tell the next step what happened
> and recommend what should happen next. Evidence pointers are required.
