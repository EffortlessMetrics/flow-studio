# Boundary Physics: Why Isolation Enables Autonomy

> **Status:** Living document
> **Purpose:** Teaching doc for the sandbox/boundary model

## The Paradox

How do you give agents **high autonomy** without **high risk**?

Traditional approaches choose one:
- High autonomy + high risk (YOLO mode)
- Low autonomy + low risk (permission prompts everywhere)

Flow Studio resolves this with **boundary physics**:
- High autonomy **inside the sandbox**
- Hard constraints **at the exits**

## The Two-Zone Model

```
┌─────────────────────────────────────────┐
│          WORK ZONE (Sandbox)            │
│                                         │
│   • Full tool access                    │
│   • No permission prompts               │
│   • Fast iteration cycles               │
│   • Destructive ops allowed             │
│   • "Break things and learn"            │
│                                         │
├─────────────────────────────────────────┤
│          EXIT ZONE (Boundary)           │
│                                         │
│   • Secrets scanning                    │
│   • Surface anomaly detection           │
│   • Destructive git ops blocked         │
│   • Human approval for publish          │
│   • "Nothing escapes unchecked"         │
│                                         │
└─────────────────────────────────────────┘
```

## Why This Works

### Inside the Sandbox

Agents can:
- Read any file in the workspace
- Write any file in the workspace
- Run any command (within OS sandbox)
- Make mistakes and fix them
- Iterate rapidly without human approval

This enables **velocity**. Agents don't wait for permission.

### At the Boundary

Before anything leaves:
- Secrets are scanned and redacted
- Surface anomalies are flagged
- Destructive git operations are blocked
- Humans approve publishing

This enables **safety**. Mistakes stay contained.

## The Economics

Traditional "permission-per-action" model:
- 10 file writes = 10 permission prompts
- 50 commands = 50 permission prompts
- 100 iterations = hundreds of interruptions
- Human becomes bottleneck

Boundary model:
- 100 iterations = 0 interruptions
- 1 publish attempt = 1 gate check
- Human reviews once, at the end

**10x-100x fewer interruptions** while maintaining safety.

## Shadow Fork Pattern

The Shadow Fork is the **canonical isolation mechanism**:

### T-0 Snapshot
When a run starts, the swarm captures the state of the repo.
This is the "time capsule" the swarm works against.

### Blind Operation
During the run, the swarm is **blind to upstream changes**.
It solves the problem as it existed at T-0.

### Benefits
- No race conditions with other contributors
- No merge conflicts during work
- Clean, atomic changes
- Clear audit of "before" vs "after"

### Deliberate Merge
When work is complete, Flow 8 (Rebase) handles:
- Fetching upstream changes
- Conflict detection
- Structured resolution
- Promotion to main timeline

## Session Boundaries

Beyond repo isolation, **session boundaries** prevent context pollution:

### The Problem
Long conversations accumulate:
- Irrelevant history
- Abandoned approaches
- Conflicting instructions
- Model drift

### The Solution
Each step starts **fresh**:
- Clean context
- Curated inputs (Context Pack)
- No prior conversation baggage
- "Fresh eyes" on the problem

### Rehydration
Fresh doesn't mean uninformed. Steps receive:
- Teaching notes (what to do)
- Prior step output (what happened)
- Relevant artifacts (specs, code)
- Scent trail (how we got here)

## Containment Hierarchy

Flow Studio has **three containment layers**:

### Layer 1: OS Sandbox
- Filesystem isolation (workspace only)
- Network restrictions (where possible)
- Process isolation
- Non-privileged execution

### Layer 2: Repo Isolation
- Shadow fork (blind to upstream)
- Branch protection (protected branches)
- Publishing gates (no direct push)

### Layer 3: Session Isolation
- Context reset between steps
- No shared mutable state
- Artifact-based handoffs

## bypassPermissions: When It's Safe

`bypassPermissions` removes per-action prompts. It's safe when:

**Containment is real:**
- Dedicated workspace (not home directory)
- No credentials in environment
- Secrets not in repository
- Network controlled

**Boundaries are enforced:**
- Secrets scanning at exit
- Destructive ops blocked
- Publishing gated
- Branch protection active

**Audit trail exists:**
- All actions logged
- Receipts capture evidence
- Decisions are traceable

## What Can Still Go Wrong

Boundaries don't prevent everything:

| Risk | Mitigation |
|------|------------|
| Agent writes bad code | Critics + tests + gate review |
| Agent makes wrong architectural choice | ADR review + human approval |
| Agent misunderstands requirements | Spec phase + iteration loops |
| Agent uses excessive tokens | Budget enforcement in kernel |
| Agent gets stuck in loop | Iteration limits + fuse detection |

The boundary model contains **blast radius**, not **all errors**.

## The Rule

> **Autonomy inside containment; gated publishing at exits.**
> **Engineering is default-allow; publishing is fail-closed.**

This is not "trust the model." This is trust:
- The sandbox
- The boundary valves
- The evidence trail

That's modern control design.
