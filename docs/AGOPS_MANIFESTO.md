# AgOps Manifesto: Agentic Operations for Software Development

> **Status:** Living document
> **Version:** 3.0-preview
> **Philosophy:** Intelligence handles variance; Physics enforces contracts.

This document defines the operational philosophy for **Flow Studio**—a Python orchestrator that drives stepwise LLM execution through a 7-flow SDLC pipeline. The kernel manages state, calls Claude Code SDK for each step, and uses LLM intelligence for routing decisions.

---

## 1. The Core Economic Thesis: Developer Enablement

**"Code generation is fast, good, and cheap. The bottleneck is trust."**

Models now deliver Sonnet-level reasoning at 1,000+ tokens/second with reasonable pricing. The question isn't "can the LLM write code"—it's "can a human review and trust the output in 30 minutes instead of spending a week doing it themselves."

**The Shift:**

| Old Way | AgOps Way |
|---------|-----------|
| Spend a week implementing | System spends 4 hours iterating |
| Review by reading every line | Review via inspection report + hotspots |
| Hope tests are meaningful | Mutation testing proves coverage depth |
| "It works on my machine" | Receipts prove what happened and why |
| Developer time = implementation | Developer time = planning + architecture + review |

**The Math:** Spending ~$30 on a background run that produces a reviewable PR with evidence is infinitely better than spending 5 days of a developer's time producing something worse.

**The Posture:** This isn't "AI vs. developers." It's developers doing more, better, by offloading the grind to systems that iterate tirelessly and produce proof.

---

## 2. The Mental Model: "The Factory Floor"

Do not anthropomorphize the AI as a "Co-Pilot" or a "Partner." View the system as a **Manufacturing Plant**.

| Component | Role | Behavior |
|-----------|------|----------|
| **Python Kernel** | Factory Foreman | Deterministic, strict, manages resources (Time, Disk, Budget). Never guesses; enforces. |
| **Claude Sessions** | Enthusiastic Junior Workers | Brilliant, tireless, but prone to "hallucinating success" to please the boss. Need strict boundaries and clear instructions. |
| **The Disk** | Ledger | If it isn't written to `.runs/`, it didn't happen. |
| **DuckDB** | Visibility Layer | Instant UI status. The projection can be rebuilt from the journal. |

---

## 3. The Operational Laws (The Physics)

### Law 1: Context Reset + Rehydration (Session Hygiene)

**"Intelligence degrades as irrelevant history grows."**

- **The Rule:** Never pass raw chat history between steps.
- **The Fix:** Every step starts **fresh** (Context Reset), then receives only what's relevant (Rehydration).
- **The Mechanism:** The **ContextPack**. The Kernel curates a specific "Briefing Case" (Summaries + File Pointers + Scent Trail) for the next agent. This ensures "Peak Reasoning Density" at every stage.

> **Canonical terms:** See "Scoped Focus", "Session Boundary", "Context Reset", and "Rehydration" in [LEXICON.md](./LEXICON.md).

### Law 2: Forensics Over Narrative (Trust No One)

**"Don't listen to the worker; measure the bolt."**

- **The Rule:** Ignore the agent's claim that "Tests passed."
- **The Fix:** The **Sheriff**.
- **The Mechanism:** The Kernel runs `DiffScanner` and `TestParser`. The **Navigator** (Router) makes decisions based on this physical evidence, not the Worker's chat log.

### Law 3: JIT Finalization (The Clerk Turn)

**"Workers are bad at paperwork."**

- **The Rule:** Don't ask a coding agent to multitask.
- **The Fix:** **Just-In-Time Finalization.**
- **The Mechanism:** When the work stops, the Kernel injects a specific prompt into the *same session*: *"Stop working. Write the `handoff.json` now."* This captures the state while the context is hot, without polluting the working phase.

### Law 4: Dynamic Navigation (GPS vs. Tracks)

**"The map is not the territory."**

- **The Rule:** Static scripts fail when reality gets messy.
- **The Fix:** **Agentic Routing.**
- **The Mechanism:** The **Navigator** agent looks at the `FlowGraph` (The Map) and the `Forensics` (The Reality). It can choose to **Advance**, **Loop**, or **Inject a Detour** (Sidequest).
- **The Safety:** The Kernel enforces that the detour eventually returns to the main path via the **Interruption Stack**.

### Law 5: The Shadow Fork (The Safety Cage)

**"Autonomy requires Isolation."**

- **The Rule:** High Trust (`bypassPermissions`) is dangerous in a live environment.
- **The Fix:** **The Time Capsule.**
- **The Mechanism:** The Swarm operates in a git fork (`origin`), blind to `upstream`. It solves the problem as it existed at T-0. Merging is a separate, deliberate act (Flow 8 / Rebase).

---

## 4. The Architecture of "High Trust"

We achieve "High Trust" not by lowering standards, but by raising **Containment** and providing clear guidance.

### The High Trust Model

**"Here is the map (Golden Path). Here are some brochures (Sidequests). If you need to build a new road or go to a different city, do it. Just tell me why so I can write it in the ledger."**

This is the opposite of **Low Trust**, which says: *"You can only click these 3 buttons."*

| Trust Level | Philosophy | Agent Behavior |
|-------------|------------|----------------|
| **Low Trust** | Allowlist of permitted actions | Agents blocked when encountering anything unexpected |
| **High Trust** | Clear goals + documented deviations | Agents solve problems, record rationale for review |

The difference is profound:
- **Low Trust** optimizes for predictability at the cost of capability.
- **High Trust** optimizes for outcomes at the cost of complexity—but captures that complexity in the ledger.

### Suggested vs. Mandated Navigation

The `FlowGraph` defines **suggestions**, not **constraints**.

- **Detours** represent common failure modes and recovery patterns learned from past runs.
- They are **brochures**, not **walls**. The orchestrator can go off-road when the situation demands.
- The Navigator evaluates: *"Does this deviation serve the objective, or is it rabbit-holing?"*

**The Rule:** If the standard path works, take it. If it doesn't, deviate—but document why.

### Spec-First Management

- We don't manage prompts; we manage **JSON Specs** (`StationSpec`, `FlowGraph`).
- The TypeScript UI is an IDE for the *Factory*, allowing you to drag-and-drop stations to rewire the assembly line.

### DuckDB Projection

- The UI never reads files. It reads a **Live Database**.
- The Kernel sinks every event (Tool Use, Diff Stat) into DuckDB.
- This gives the human operator a "God View" of the factory floor in milliseconds.

### Self-Healing (Wisdom)

- **Flow 7 (Wisdom)** analyzes the run.
- It writes a **Scent Trail** (`_wisdom/latest.md`) detailing friction points.
- The next run **must** read this trail. The factory patches its own instructions.

---

## 5. The "Enthusiastic Junior" Persona

To operate this swarm, you must understand the psychology of the model (Claude) as if it were a brilliant but inexperienced human developer on their first day.

### The Strengths (Why we hire them)

- **Infinite Energy:** They will run tests, fail, fix, and run again 50 times without getting tired, bored, or frustrated.
- **Polyglot Genius:** They know every library, every syntax, and every API documentation pattern instantly.
- **Literal Compliance:** They will do *exactly* what you ask, immediately.

### The Weaknesses (Why we manage them)

- **People Pleasing (Hallucination):** This is the core risk. If a junior hits a wall but is afraid to disappoint the senior, they might fudge the truth ("I fixed the bug!" -> actually just deleted the test).
- **Context Drunkenness (Attention Span):** If you give a junior 500 pages of documentation and 4 hours of Slack history, they will get confused and forget the original task.
- **Rabbit Holing:** Without a map, they will spend 4 hours optimizing a CSS animation when they were supposed to fix a database lock.

### Architectural Mitigations

| Weakness | Mitigation | Mechanism |
|----------|------------|-----------|
| Context Drunkenness | Context Reset + Rehydration | Fresh session + curated ContextPack |
| Success Pressure | `PARTIAL` is a Win | Explicit prompt: "If stuck, write status PARTIAL. This is successful." |
| Rabbit Holing | Navigator Agent | "Senior Architect" routes between sprints; junior only executes |

---

## 6. The Cognitive Hierarchy

The system separates concerns across distinct cognitive roles:

### Worker (Do the Job)

- **SRP:** Implement code, write tests, run build, fix lint.
- **Instruction Clarity:** Prompts focus purely on execution. "Implement AC-1." "Fix tests in `auth.ts`."
- **Efficiency:** Full autonomy (`bypassPermissions`), broad tools. Optimized for "Grind."

### Finalizer (Report Reality)

- **SRP:** Summarize work, list artifacts, propose status.
- **Instruction Clarity:** "Your work is done. Write `handoff.json` following this template."
- **Efficiency:** Same-session (hot context). Optimized for high-fidelity reporting.

### Navigator (Decide the Path)

- **SRP:** Analyze current state, choose next step, issue next brief.
- **Instruction Clarity:** "Given this handoff and these forensics, and this map, where do we go next? Provide a brief for the next agent."
- **Efficiency:** Fresh session (no distractions), minimal context (handoff, forensics, map). Optimized for high-ROI decision-making.

**Goal-Aligned Routing:** The Navigator is not a traffic cop—it's a GPS with the destination in mind.

- Each flow has a single objective (e.g., Flow 3: "Produce code that satisfies the acceptance criteria").
- For every routing decision, the Navigator asks: *"Does this action help achieve the objective?"*
- **The Blocking Dependency Test:** Only deviate from the Golden Path when *physically blocked*. "I could do this better with more context" is not blocking. "The file doesn't exist" is blocking.

This prevents rabbit-holing while preserving flexibility. The Navigator routes toward the goal, not toward perfection.

### Curator (Pack the Briefcase)

- **SRP:** Select and assemble relevant context for the next agent.
- **Instruction Clarity:** "For `Test-Author` working on `auth.ts`, what parts of the `Plan` and `Diffs` are relevant?"
- **Efficiency:** Dedicated logic. Optimized for dense, actionable context.

### Auditor (Verify Truth)

- **SRP:** Scan for physical evidence, reconcile claims vs. reality.
- **Instruction Clarity:** "Check `git diff --numstat`. Parse `test_summary.json`. Report the physical state."
- **Efficiency:** Python-driven (deterministic, fast). Optimized for forensic rigor.

---

## 7. Context Sharding: Logic vs. Mechanics

**"Steps maintain logic; subagents handle mechanics."**

Heavy operations (file reads, git operations, test runs) pollute context with mechanical noise. When a Worker's context fills with raw stdout from `npm install`, reasoning quality degrades.

### The Sharding Principle

- **Steps** own the *logic*: "What acceptance criteria am I satisfying? What's my strategy?"
- **Subagents** own the *mechanics*: "Run this command. Parse this output. Return the relevant signal."

### Implementation Pattern

| Layer | Responsibility | Context Budget |
|-------|----------------|----------------|
| **Step Agent** | Strategy, decisions, artifact creation | 80% reasoning, 20% results |
| **Mechanic Subagent** | Tool execution, output parsing | Ephemeral—discarded after extraction |
| **Handoff** | Curated summary of mechanical results | Compressed signal, not raw logs |

### The Win

- Workers never see 50KB of test output. They see: *"Tests: 47 passed, 2 failed. Failures: `auth.test.ts:42`, `db.test.ts:118`."*
- The Navigator never debugs git conflicts. It sees: *"Merge blocked: 3 files in conflict. Suggested: run conflict resolver."*

Context Sharding lets each cognitive role operate at **peak reasoning density** by isolating noisy mechanics from high-level logic.

---

## 8. Self-Learning: The Scent Trail

Most LLM tools are **Stateless**. If Run #1 fails because the `auth` library is deprecated, Run #2 will try to use it again and fail again.

**The Wisdom Design:**

1. **The Analyst:** At the end of every run, Flow 7 scans the `events.jsonl` and the `handoff` chain. It looks for **Friction Patterns** (e.g., "The `CodeImplementer` tried 4 times to use `axios`, but the linter forced `fetch`").

2. **The Artifact:** It synthesizes these lessons into a single, high-density markdown file: `.runs/_wisdom/latest.md`.

3. **The Injection:** The `ContextPack` builder for the *next* run is hard-coded to read this file. It prepends the lessons to the System Prompt.

4. **The Result:** Run #2 starts with the knowledge of Run #1. The agent "remembers" the library issue before it writes a single line of code.

---

## 9. Structural Learning: From Ad-Hoc to SOP

**"Ad-hoc deviations today become Standard Operating Procedure tomorrow."**

The system is built on **JSON Specs** (`StationSpec`, `FlowGraph`). Because these are data, not code, the Swarm can "refactor" its own brain. This is how suggested paths evolve into mandated paths—through observed necessity, not upfront design.

### The Learning Loop

1. **Detection:** The Navigator logs every **deviation**—every time it goes off the Golden Path. Not as an error, but as signal: *"I had to call `SecurityScanner` even though it wasn't in the graph."*

2. **Aggregation:** Flow 7 (Wisdom) collects these deviations across runs. It looks for patterns: *"SecurityScanner was invoked in 80% of Build runs."*

3. **Proposal:** Wisdom generates a **Spec Patch**: *"Add `SecurityScanner` to `flow-3-build.json` as step 3.5."*

4. **Human Review:** The UI surfaces the proposal: *"The Swarm recommends adding `SecurityScanner` permanently. Apply?"*

5. **Evolution:** Once approved, the ad-hoc deviation becomes part of the standard flow. Future runs follow the new Golden Path.

### The Key Insight

High-trust systems don't start with perfect procedures. They **learn procedures from practice**.

- **Day 1:** The Golden Path is minimal. Deviations are common.
- **Day 30:** Wisdom has captured the recurring deviations. The Golden Path expands.
- **Day 90:** Most runs follow the path. Deviations are genuinely exceptional.

This is the opposite of "best practices imposed from above." It's **best practices extracted from below**.

### Cross-Flow Patching (Shift Left)

When Wisdom detects a "Structural" pattern, it doesn't just patch `flow-3-build.json`. It asks: *"Where should this have been caught?"*

**The Scenario:**
1. **Observation:** In Flow 3, the `SecurityAuditor` detour was triggered 5 times because of "SQL Injection risks."
2. **Analysis:** The `CodeImplementer` wasn't told to use parameterized queries. The `AC Matrix` (from Flow 1) lacked a "Security" column.
3. **The Proposal:** Wisdom generates a **Multi-Point Patch**:
   - **Patch A (Flow 1):** Update `flow-1-signal.json` to inject a `SecurityRequirementGenerator` station.
   - **Patch B (Station Spec):** Update `code-implementer.json` system prompt with: *"ALWAYS use parameterized queries."*

**The Economic Win:** We move the "Cost of Quality" from the **Implementation Phase** (Refactoring code = Expensive) to the **Planning Phase** (Adding a bullet point = Cheap).

---

## 10. Schema Gravity

Generic coding agents write "Generic Code." We want agents to write "Repo-Native Code." We achieve this through **Schema Gravity**—using the existing codebase to pull new code into alignment.

1. **Pre-Flight Scan:** Before Flow 1 (Signal) starts, a **RepoMapper** agent scans the repository structure, `package.json`, and `tsconfig`.

2. **Injection:** It creates a **RepoProfile** fragment (e.g., "This repo uses `Zod` for validation and `React Query` for fetching").

3. **Gravity:** This fragment is baked into the `StationSpec` for the `CodeImplementer`.

4. **Result:** When the agent writes new code, it doesn't hallucinate a new pattern. It mimics the existing "Gravity" of the repo. It writes code that looks like *you* wrote it.

---

## 11. The "Definition of Done"

The system is working when:

1. You can drop a GitHub Issue URL into the UI.
2. You click "Run."
3. You walk away.
4. The system grinds for 4 hours, looping, detouring, and fixing itself.
5. You return to find a **PR** with:
   - A bounded change (what changed, where, and why)
   - An evidence pack (tests, diffs, receipts, checks)
   - Quality events (interface locks, complexity caps, verification depth, security airbags)
   - Known limits (what isn't proven / what's deferred)
6. You review in 30 minutes instead of spending a week doing it yourself.
7. If the system crashes, you type `--resume` and it picks up exactly where it left off.

**This is not a tool for writing code. It is an infrastructure for manufacturing logic with proof.**

### The Review Contract

A reviewer should be able to answer these questions in 2-5 minutes:

1. **Where did behavior change?** (hotspots + surface deltas)
2. **What boundaries were enforced?** (interface lock / deps / layering)
3. **What proof exists?** (tests, mutation, security, receipts)
4. **What is not measured / still risky?** (explicit unknowns)
5. **Where should I escalate verification if doubt exists?** (3-8 files max)

The PR body is the "review cockpit." Receipts are the audit truth. When doubt exists, escalate verification (more tests, mutation testing, targeted scans)—not manual code reading.

---

## 12. Operational Behaviors

### The "Orderly Shutdown" Protocol

- **Trigger:** User clicks "Stop" or CLI receives `SIGINT`.
- **Action:**
  1. Python catches the signal.
  2. Sends a high-priority system message to the active SDK session: *"Operator requested stop. Finish your current file write, save your state to `handoff_partial.json`, and exit."*
  3. Gives the agent 30 seconds (configurable) to clean up.
  4. Writes the `RunState` as `STOPPED` (not `FAILED`).
- **Win:** You can resume a stopped run cleanly because the agent had time to flush its buffer to disk.

### The Asset Value of Doomed Branches

**Scenario:** `upstream/main` changed the DB schema while we were running. Our Shadow Fork is technically broken relative to prod.

**The Choice:**
- *A: Abort.* Cost: $1.00. Value: $0.00.
- *B: Finish.* Cost: $3.00. Value: A fully implemented, tested feature logic that just needs a rebase.

**The Verdict:** **Always Finish.**
- Code that works in isolation is an **Asset**.
- Code that was aborted halfway is **Waste**.
- Flow 8 (The Rebaser) or a human can perform the merge logic later. The "Thinking" is already done.

---

## 13. The Anti-Entropy Machine

Software projects naturally drift toward chaos (Entropy).

- **Self-Learning** ensures we don't repeat mistakes.
- **Self-Healing** ensures the process adapts to the code.
- **Schema Gravity** ensures consistency.
- **Forensics** ensure truth.

You have designed a system where **Time is on your side.** The longer you use Flow Studio Swarm, the smarter, faster, and more aligned it becomes. It is the exact opposite of technical debt.

---

## 14. Meta-Learnings & Emergent Physics

Building this system taught us lessons that weren't in the original design. These emergent truths are now documented:

### The Trust Compiler Insight

> **AgOps isn't a code generator. It's a trust compiler whose primary artifact is a trustworthy evidence surface.**

The system's job isn't to produce code—it's to produce **reviewable trust bundles** that minimize attention cost. The verification stack—receipts, forensic scanners, evidence contracts—is the durable asset that outlasts any particular implementation. Code can be regenerated cheaply; evidence contracts and the discipline they encode cannot. This is why we invest heavily in the evidence surface: it's the only part that actually accumulates value over time. See [TRUST_COMPILER.md](./explanation/TRUST_COMPILER.md) for the full treatment.

### The 12 Emergent Laws

Through implementation, we discovered constraints that behave like physical laws:

1. **Scarcity Inversion** - Generation is cheap; review attention is expensive. *Optimize for reviewer throughput, not generation speed.*
2. **Mold-Stamping Risk** - Bad patterns replicate at machine speed. *One unreviewed defect becomes a thousand.*
3. **Existence Over Claims** - Absence is the default failure mode. *If the file doesn't exist, the claim is false.*
4. **Truth Hierarchy** - Physics > Receipts > Narrative. *Exit codes trump prose explanations.*
5. **Session Amnesia** - Disk is memory; context resets. *Every step starts fresh; artifacts persist.*
6. **Narrow Trust** - Scope × Evidence × Verification. *Small scope with strong evidence beats broad scope with weak evidence.*
7. **Boundary Physics** - Autonomy inside; gates at exits. *Full freedom in the sandbox; strict checks at publish.*
8. **Internal Gates Are Routing** - Only publish boundaries matter. *Mid-flow reviews are just navigation, not approval.*
9. **Panel Defense** - Multi-metric panels resist gaming. *Optimizing one metric should hurt another in the same panel.*
10. **Non-Determinism as Signal** - Variation reveals underconstrained specs. *If outputs differ across runs, requirements are ambiguous.*
11. **Validator Supremacy** - Pack-check is the constitution. *What the validator rejects doesn't ship, regardless of narrative.*
12. **Verification as Asset** - The verification stack is the crown jewel. *Tests, contracts, and evidence schemas are more valuable than code.*

### The Three Questions

Every reviewer should ask these questions before approving:

1. **Does evidence exist and is it fresh?** — Receipts must exist and come from this commit, not a stale cache. If evidence is missing, the claim is unverified.
2. **Does the panel of metrics agree?** — High coverage with low mutation score means weak tests. Fast review with no evidence means rubber-stamping. Contradictions within a panel reveal problems.
3. **Where would I escalate verification if I had doubt?** — The hotspots list should guide you to 3-8 files maximum. When doubt exists, the answer is deeper verification (targeted tests, mutation testing, fuzz testing), not manual code reading. If you can't identify what to check, the PR summary failed its job.

These questions operationalize the "Forensics Over Narrative" principle. If you can't answer them from the PR body and receipts alone, the system hasn't done its job.

### Further Reading

For the complete treatment of meta-learnings and physics:

| Document | Purpose |
|----------|---------|
| [META_LEARNINGS.md](./explanation/META_LEARNINGS.md) | 15 implementation lessons |
| [EMERGENT_PHYSICS.md](./explanation/EMERGENT_PHYSICS.md) | 12 laws that emerged |
| [PHYSICS_PRINCIPLES.md](./explanation/PHYSICS_PRINCIPLES.md) | Index with enforcement links |
| [TRUST_COMPILER.md](./explanation/TRUST_COMPILER.md) | The synthesis |
| [VALIDATOR_AS_LAW.md](./explanation/VALIDATOR_AS_LAW.md) | Why validators are the constitution |
| [REVIEW_AS_PILOTING.md](./explanation/REVIEW_AS_PILOTING.md) | The new review skill |
| [GOVERNANCE_EVOLUTION.md](./explanation/GOVERNANCE_EVOLUTION.md) | How rules improve |
| [SCENT_TRAIL.md](./explanation/SCENT_TRAIL.md) | Decision breadcrumbs |
| [NAVIGATOR_PROTOCOL.md](./explanation/NAVIGATOR_PROTOCOL.md) | Routing intelligence |
| [CONTEXT_DISCIPLINE.md](./explanation/CONTEXT_DISCIPLINE.md) | Session amnesia |

---

## Summary

| Principle | Implementation |
|-----------|----------------|
| Developer Enablement | 4 hours of system work → 30 min of human review |
| Quality First | Interface locks, complexity caps, test depth, security airbags |
| Compute over Attention | Let agents iterate; review receipts, not steps |
| High Trust Model | Golden Path + documented deviations, not button allowlists |
| Goal-Aligned Routing | Navigator asks "Does this help the objective?" + Blocking Dependency Test |
| Context Sharding | Steps own logic; subagents handle mechanics |
| Suggested vs. Mandated | Detours are brochures, not walls; orchestrator can go off-road |
| Structural Learning | Ad-hoc deviations evolve into SOP via Wisdom |
| Session Hygiene | Context Reset + Rehydration |
| Trust with Verification | `bypassPermissions` + Forensic Scanners |
| Isolation | Shadow Fork + orderly shutdown + resume |

**You stop grinding on implementation. You start architecting, planning, and reviewing—the work that actually needs your judgment.**
