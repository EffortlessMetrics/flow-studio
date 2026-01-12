# Operating Model: The PM/IC Organization

> **Status:** Living document
> **Purpose:** Teaching doc for the orchestration hierarchy

## The Mental Model

Don't think "AI assistant" or "co-pilot."

Think: **Factory Floor**.

| Component | Role | Behavior |
|-----------|------|----------|
| **Python Kernel** | Factory Foreman | Deterministic, strict. Never guesses. |
| **Navigator** | Shift Supervisor | Intelligent routing. Reads evidence, decides next step. |
| **Agents** | Specialists | One job each. Execute and report. |
| **Disk** | Ledger | Truth of record. If not written, didn't happen. |

## The Hierarchy

```
┌─────────────────────────────────────────┐
│              Python Kernel              │
│  (Director / Foreman)                   │
│                                         │
│  • Manages Time, Disk, Budget           │
│  • Enforces graph constraints           │
│  • Never guesses; always measures       │
│  • Deterministic operations             │
└────────────────┬────────────────────────┘
                 │
┌────────────────▼────────────────────────┐
│              Navigator                  │
│  (Shift Supervisor)                     │
│                                         │
│  • Reads forensic evidence              │
│  • Selects from candidate routes        │
│  • Makes intelligent decisions          │
│  • Cheap LLM call (Haiku-class)         │
└────────────────┬────────────────────────┘
                 │
┌────────────────▼────────────────────────┐
│           Step / Station                │
│  (Manager)                              │
│                                         │
│  • Executes single objective            │
│  • Full Claude orchestrator             │
│  • Delegates to subagents               │
│  • Produces handoff envelope            │
└────────────────┬────────────────────────┘
                 │
┌────────────────▼────────────────────────┐
│             Subagent                    │
│  (Specialist)                           │
│                                         │
│  • Executes specific operation          │
│  • Narrower scope than Step             │
│  • Returns distilled results            │
│  • One tool call or focused task        │
└─────────────────────────────────────────┘
```

## Why This Hierarchy

### Kernel: Determinism
The kernel handles what must be predictable:
- File I/O
- Process execution
- Budget enforcement
- Graph traversal

If the kernel did LLM reasoning, you'd have non-deterministic infrastructure.

### Navigator: Intelligence
The Navigator handles what requires judgment:
- Interpreting forensic evidence
- Choosing between valid routes
- Detecting stuck conditions
- Deciding when to detour

Cheap model (Haiku) makes fast decisions. Seconds, not minutes.

### Step: Execution
Steps do the actual work:
- Writing code
- Running tests
- Analyzing requirements
- Producing artifacts

Full Claude orchestrator capability within a bounded scope.

### Subagent: Focus
Subagents prevent context pollution:
- Step maintains logic
- Subagent burns tokens on mechanics
- Step doesn't get "drunk" on grep output
- Subagent abstracts mechanical work

## PM/IC Dynamics

### Orchestrator = PM

The orchestrator's job:
- Keep intent coherent across steps
- Decide what "enough evidence" means
- Route based on handoffs (not parsing)
- Stop only for true boundaries

**PMs read handoffs. They don't parse JSON schemas.**

### Agents = ICs

Each agent:
- Has one scoped job
- Reports with evidence
- Recommends next step
- Doesn't decide routing (suggests only)

**ICs don't call ICs.** Only the orchestrator coordinates.

## Separation of Concerns

| Layer | Responsibility | NOT Responsible For |
|-------|---------------|---------------------|
| Kernel | Resource management, physics | Judgment, reasoning |
| Navigator | Routing decisions | Work execution |
| Step | Work execution | Routing decisions |
| Subagent | Focused operations | Broad reasoning |

Violations of this separation cause:
- Non-deterministic infrastructure (kernel doing LLM)
- Context pollution (step doing subagent work)
- Routing drift (step deciding its own next step)

## Fix-Forward Vocabulary

The system uses explicit vocabulary to prevent bureaucracy:

### Valid Outcomes

| Outcome | Meaning | Next Action |
|---------|---------|-------------|
| **Needs fixes** | Issues found, iteration needed | Route to fixer |
| **Cannot proceed (mechanical)** | Environment issue | Fix environment |
| **Needs human decision** | Non-derivable choice | Ask crisp question |
| **Not safe to publish yet** | Boundary issue | Remediate first |

### Invalid Patterns

❌ "Blocked because ambiguous" → Make documented assumption
❌ "Cannot proceed because uncertain" → State uncertainty, proceed
❌ "Need approval to continue" → Complete work, gate at boundary

**"Blocked" is rare and literal.** Missing inputs, not ambiguity.

## Evidence-Based Routing

The Navigator receives **forensic evidence**, not narrative:

```json
{
  "step_result": {
    "status": "succeeded",
    "duration_ms": 4500
  },
  "forensics": {
    "tests": { "passed": 42, "failed": 0 },
    "lint": { "errors": 0, "warnings": 3 },
    "coverage": { "line_pct": 78.5 }
  },
  "handoff": {
    "status": "UNVERIFIED",
    "concerns": [
      { "severity": "MEDIUM", "description": "..." }
    ]
  }
}
```

The Navigator sees **numbers and structured data**, not prose claims.

## The Rule

> **Kernel enforces physics. Navigator applies intelligence. Agents execute work.**
> **Each layer constrains the next. Evidence flows up. Decisions flow down.**
