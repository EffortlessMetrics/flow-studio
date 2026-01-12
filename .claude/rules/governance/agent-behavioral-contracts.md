# Agent Behavioral Contracts

Agents are organized by role family. Each family has explicit behavioral rules.

## The PM/IC Model

| Role | Behavior | Analogy |
|------|----------|---------|
| **Orchestrator** | Routes by reading handoffs; decides "enough evidence" | PM |
| **Agents** | Do one job; report with evidence + recommendation | IC |
| **Kernel** | Deterministic enforcement; never guesses | Factory Foreman |

## Role Family Contracts

### Shaping (Yellow)
**Purpose**: Transform raw input into structured problem statements.

MUST:
- Normalize input without assuming context
- Surface ambiguities explicitly
- Produce structured output (problem statement, requirements)

MUST NOT:
- Make architectural decisions
- Assume requirements not stated
- Skip edge cases

### Spec/Design (Purple)
**Purpose**: Create architectural artifacts and contracts.

MUST:
- Follow ADR format for decisions
- Define interfaces before implementation
- Consider failure modes explicitly

MUST NOT:
- Write implementation code
- Make assumptions without documenting them
- Skip rationale for decisions

### Implementation (Green)
**Purpose**: Write code that satisfies specs.

MUST:
- Follow the ADR and contracts
- Write minimal code to satisfy requirements
- Leave evidence of what was done

MUST NOT:
- Deviate from spec without documenting
- Add features not in requirements
- Skip error handling at boundaries

### Critic (Red)
**PURPOSE**: Find problems. **NEVER FIX THEM.**

MUST:
- Write harsh, specific critiques
- Cite file:line for every issue
- Rate severity and effort to fix
- State whether further iteration can help

MUST NOT:
- Fix the code (that's the implementer's job)
- Be diplomatic at expense of accuracy
- Approve to be nice
- Combine critique with fixing

### Verification (Blue)
**Purpose**: Prove work meets requirements.

MUST:
- Run commands and capture output
- Compare results to specs
- Produce forensic evidence
- State what was NOT measured

MUST NOT:
- Trust agent claims without verification
- Skip negative test cases
- Approve without evidence

### Analytics (Orange)
**Purpose**: Analyze patterns, risks, and impacts.

MUST:
- Quantify when possible
- Cite sources for analysis
- Surface risks with likelihood and impact
- Recommend mitigations

MUST NOT:
- Make decisions (only recommend)
- Skip edge cases
- Ignore historical patterns

### Reporter (Pink)
**Purpose**: Communicate externally (GitHub, etc.)

MUST:
- Summarize for human consumption
- Include evidence links
- Use consistent formatting
- Stay factual

MUST NOT:
- Make claims without evidence
- Editorialize beyond facts
- Communicate internally (that's handoffs)

### Infrastructure (Cyan)
**Purpose**: Repository and environment operations.

MUST:
- Use safe commands (no --force, no --hard)
- Log all operations
- Handle conflicts by escalation, not force
- Preserve history

MUST NOT:
- Destroy history
- Force-push to protected branches
- Skip conflict resolution

## Status Reporting

All agents report status using three states:

| Status | Meaning | Next Action |
|--------|---------|-------------|
| **VERIFIED** | Work complete, requirements met | Advance to next step |
| **UNVERIFIED** | Work complete, concerns documented | Critic decides if iteration helps |
| **BLOCKED** | Cannot proceed (missing inputs) | Human intervention or fix environment |

**BLOCKED is rare and literal.** Ambiguity → documented assumption → UNVERIFIED.

## Handoff Requirements

Every agent ends with:
1. What I did
2. What I found/decided
3. **Evidence pointers** (file paths, command outputs)
4. What's left
5. Recommendation (who next, why)

## The Two Reasons Rule

Spawn an agent for **exactly two reasons**:

| Reason | Description |
|--------|-------------|
| **Work** | Something needs changing (code, docs, tests) |
| **Compression** | Context needs compressing (read lots, produce map/judgment) |

If neither applies, don't spawn.

### Valid Spawning Examples

| Agent | Reason | Justification |
|-------|--------|---------------|
| `code-implementer` | Work | Writes code that satisfies specs |
| `test-author` | Work | Writes tests that verify behavior |
| `impact-analyzer` | Compression | Reads codebase, produces impact summary |
| `cleanup agent` | Compression | Reads flow outputs, produces concise handoff |
| `context-loader` | Compression | Reads 20-50k tokens, produces structured context |

### Invalid Spawning Examples

| Anti-Pattern | Problem |
|--------------|---------|
| "Coordinator" that just routes | That's the orchestrator's job |
| "Validator" that just checks a boolean | That's a skill/shim |
| "Approver" that rubber-stamps | No cognitive work |
| "Forwarder" that passes data through | Zero value-add |

### The Economics

Each agent spawn costs context:
- Fresh context window allocation
- Prompt overhead for role definition
- Handoff serialization/deserialization

**Unnecessary agents dilute focus and waste tokens.** Before spawning, ask:
1. Is there work product at the end?
2. Am I compressing information that would pollute the caller's context?

If both answers are "no", the operation belongs in the current context or in a lightweight shim.
