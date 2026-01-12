# Staged Publication: The Lab and the Journal

> **Status:** Living document
> **Purpose:** Explain the draft/publish separation in agentic work

## The Metaphor

Academic research has two spaces:
- **The Lab**: Where experiments happen, failures occur, iterations run
- **The Journal**: Where verified results are published

AgOps adopts this model:
- **The Sandbox**: Where work happens, agents iterate, mistakes are made
- **The Boundary**: Where verified work is published to production

## Why Staged Publication

### The Lab is Messy
Research labs are full of:
- Failed experiments
- Partial results
- Abandoned approaches
- Work in progress

This is normal. This is how discovery works.

### Journals are Clean
Published papers contain:
- Verified results
- Complete methodology
- Reproducible findings
- Peer-reviewed claims

The mess is hidden. The quality is guaranteed.

### The Separation is Critical
If labs published directly:
- Bad science would spread
- Unverified claims would propagate
- Mistakes would become "truth"

The publication gate prevents this.

## AgOps Staged Publication

### The Sandbox (Lab)
Where agents work:
- Full autonomy
- High trust mode
- Destructive operations allowed
- Failures expected
- Iterations encouraged

### The Boundary (Journal Gate)
Where work is verified:
- Evidence checked
- Policies enforced
- Secrets scanned
- Anomalies detected
- Human approval required

### The Publication (Journal)
Where verified work lands:
- Production branch
- Deployed artifact
- Released version
- Public API

## The Stage Gate Model

```
+---------------------------------------------+
|                SANDBOX                      |
|                                             |
|   Draft PR created                          |
|   Work iterated                             |
|   Critics review                            |
|   Evidence gathered                         |
|                                             |
+-----------------------+---------------------+
                        |
                +-------v-------+
                |   GATE CHECK  |
                |               |
                | - Evidence?   |
                | - Secrets?    |
                | - Policy?     |
                | - Approval?   |
                +-------+-------+
                        |
           +------------+------------+
           |                         |
           v                         v
        PUBLISH                   BOUNCE
        (Merge)                   (Fix)
```

## PRs as Communication (Not Control)

Flow 3 may create Draft PRs:
- Wakes CI bots for feedback
- Signals "work in progress" to upstream
- Enables external review iteration

**Important:** PR status is **informational output**, not a control mechanism.

Flow 4 completes when work items are resolved:
- Work has been verified in the shadow fork
- Evidence is captured in receipts
- Flow 5 (Gate) can proceed

PR status (Draft/Ready) may be updated as a **communication signal** to upstream, but it does not control flow progression. The shadow fork is the source of truth, not the PR.

## What Stays in the Lab

### Iteration History
- Failed approaches
- Abandoned code
- Intermediate versions
- Debug artifacts

### Internal Communication
- Agent handoffs
- Critic reports
- Routing decisions
- Work-in-progress receipts

### Exploratory Work
- Spike implementations
- Proof of concepts
- Alternative approaches
- Learning experiments

## What Gets Published

### Verified Results
- Working code
- Passing tests
- Clean lint
- Security-cleared

### Summary Evidence
- Test results
- Coverage reports
- Gate approval
- Audit trail

### Clean History
- Squashed commits (optional)
- Clear commit messages
- Traceable changes

## The Bounce Pattern

When gate check fails:
1. Publication blocked
2. Work bounced back to lab
3. Specific issues identified
4. Iteration continues

This is normal. This is the system working.

Bounces are not failures. They're quality control.

## The Shadow Fork

The ultimate lab isolation:
- Fork from upstream
- Work blind to changes
- Complete the work
- Merge deliberately

Benefits:
- No race conditions
- No mid-work conflicts
- Clean atomic changes
- Clear before/after

## Deployment Models

AgOps supports multiple deployment models. The boundary is wherever you define it.

### Model A: Fork-to-Upstream (Recommended)

```
Your Fork (Sandbox)          Upstream Repo (Production)
┌─────────────────┐          ┌─────────────────┐
│ Flow 1: Signal  │          │                 │
│ Flow 2: Plan    │          │    main         │
│ Flow 3: Build   │    PR    │                 │
│ Flow 4: Review  │ ──────►  │  ◄── The Real   │
│ Flow 5: Gate    │          │      Boundary   │
│ Flow 6: Deploy  │          │                 │
│ Flow 7: Wisdom  │          │                 │
└─────────────────┘          └─────────────────┘
```

How it works:
1. Work happens in **your fork** (full autonomy)
2. All 7 flows run in your sandbox
3. Final output: **PR into upstream main**
4. Upstream maintainers review + merge

The boundary is the **PR into upstream**, not a branch in your repo.

### Model B: Branch-to-Main (Traditional)

```
Feature Branch (Sandbox)     Main Branch (Production)
┌─────────────────┐          ┌─────────────────┐
│ Flow 1-7        │    PR    │                 │
│ on feature/*    │ ──────►  │    main         │
│                 │          │                 │
└─────────────────┘          └─────────────────┘
```

How it works:
1. Work happens on **feature branch**
2. Flows run against branch
3. PR into main (same repo)
4. Branch protection = boundary

Works for teams that prefer single-repo workflows.

### Model C: Hybrid

Mix and match:
- Use fork for external contributions
- Use branch for internal work
- The system adapts

The principle is constant: **sandbox → gate → publish**.
The mechanism is flexible.

## Flexibility by Design

AgOps doesn't mandate a specific git workflow:
- Fork-based? Works.
- Branch-based? Works.
- Trunk-based with feature flags? Works.

The invariant is staged publication:
1. Work happens in isolation
2. Gate verifies before publish
3. Publication is deliberate

How you implement isolation is up to you.

## The Rule

> The sandbox is the lab: messy, iterative, autonomous.
> The boundary is the gate: verified, gated, deliberate.
> Publication is an act, not an accident.

## Anti-Patterns

### Direct to Production
Pushing directly to main without gate:
- No verification
- No evidence check
- No human approval
- High risk

### Lab Results as Truth
Treating draft work as complete:
- Unverified claims
- Missing evidence
- No quality gate
- Premature trust

### Gate as Obstacle
Viewing the gate as bureaucracy:
- Missing the point
- Quality is the goal
- Gate enables trust
- Skip gate = skip trust

## The Economics

Staged publication costs:
- Gate check time
- Bounce-back iterations
- Additional review

Staged publication saves:
- Production incidents
- Rollback fire drills
- Trust recovery
- Customer impact

The math: 30 minutes of gating saves 30 hours of incident response.
