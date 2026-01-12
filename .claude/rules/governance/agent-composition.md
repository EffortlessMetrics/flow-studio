# Agent Composition: When and How to Combine Agents

When to use one agent vs many. How to compose them when many are needed.

## The Two Reasons Rule

Spawn an agent for **exactly two reasons**:

| Reason | Description | Example |
|--------|-------------|---------|
| **Work** | Something needs changing (code, docs, tests) | `code-implementer`, `test-author` |
| **Compression** | Context needs compressing (read lots, produce summary) | `impact-analyzer`, `context-loader` |

If neither applies, don't spawn.

See [agent-behavioral-contracts.md](./agent-behavioral-contracts.md) for the full rule.

## Single Agent When

Use one agent when:

| Condition | Why |
|-----------|-----|
| Task is focused and bounded | Single responsibility = narrow trust |
| No conflicting roles | Writer shouldn't critique; critic shouldn't fix |
| Context fits in budget | No need to shard work |
| Clear success criteria | One agent can determine done |

### Examples

| Task | Agent | Why Single |
|------|-------|------------|
| Fix lint errors | `lint-fixer` | Narrow scope, clear exit |
| Write migration | `code-implementer` | Bounded by spec |
| Summarize codebase | `impact-analyzer` | Compression task |

## Multiple Agents When

Use multiple agents when:

| Condition | Why | Pattern |
|-----------|-----|---------|
| Adversarial tension needed | Writer shouldn't judge own work | Author + Critic |
| Different expertise required | Security != implementation | Specialist Delegation |
| Context would exceed budget | Shard to avoid pollution | Fan-Out/Fan-In |
| Parallel work possible | Independent subtasks | Fan-Out/Fan-In |

### Examples

| Task | Agents | Why Multiple |
|------|--------|--------------|
| Implement feature | `code-implementer` + `code-critic` | Adversarial quality |
| Full security review | `code-author` + `security-analyst` + `test-author` | Different expertise |
| Analyze large codebase | Multiple `context-loader` instances | Context sharding |

## Composition Patterns

### 1. Sequential Chain

```
A ───► B ───► C
```

Each agent's output feeds the next.

**Use for:**
- Pipelines (raw → structured → validated)
- Transformations (spec → code → test)
- Progressive refinement

**Example:**
```
requirements-author → requirements-critic → adr-author
```

### 2. Adversarial Loop

```
┌─────────────────────────┐
│                         │
│   Author ────► Critic   │
│      ▲           │      │
│      └───────────┘      │
│                         │
└─────────────────────────┘
```

Iterate until exit condition met.

**Use for:**
- Quality improvement (code, tests, docs)
- Requirement refinement
- Review cycles

**Exit conditions:**
1. VERIFIED (no issues)
2. `can_further_iteration_help == false`
3. Iteration limit reached
4. Repeated failure signature

See [microloop-rules.md](../execution/microloop-rules.md).

**Example:**
```
code-implementer ⇄ code-critic (max 5 iterations)
```

### 3. Fan-Out/Fan-In

```
             ┌──► A ──┐
             │        │
Coordinator ─┼──► B ──┼─► Aggregator
             │        │
             └──► C ──┘
```

Parallel work, then combine results.

**Use for:**
- Independent subtasks
- Parallel analysis
- Multi-file operations

**Example:**
```
impact-analyzer → [file-analyzer-1, file-analyzer-2, ...] → summary-aggregator
```

### 4. Specialist Delegation

```
Generalist ───► Specialist ───► Generalist
```

Deep dive on specific problem, then return.

**Use for:**
- Complex subproblems requiring expertise
- Security analysis mid-flow
- Performance investigation

**Example:**
```
code-implementer → security-analyst → code-implementer
```

## Anti-Patterns

### Coordinator That Just Routes

```
# BAD
coordinator-agent:
  job: "Route work to appropriate agents"
```

**Problem:** That's the orchestrator's job. Zero cognitive work.

### Validator That Checks Boolean

```
# BAD
validator-agent:
  job: "Check if tests pass"
```

**Problem:** That's a skill or shim. No LLM needed.

### Approver That Rubber-Stamps

```
# BAD
approver-agent:
  job: "Approve if looks good"
```

**Problem:** No cognitive work. If it can't reject, it shouldn't exist.

### Agent Per File

```
# BAD
file-1-agent, file-2-agent, file-3-agent...
```

**Problem:** Over-decomposition. Context loss. Coordination overhead.

### Self-Reviewing Agent

```
# BAD
writer-reviewer-agent:
  job: "Write code and review it"
```

**Problem:** No adversarial tension. Will be kind to itself.

## Spawning Cost

Each spawn costs:
- Fresh context window (~2k tokens overhead)
- Prompt overhead for role definition
- Handoff serialization/deserialization
- Potential context loss at boundaries

**The math:**
- 3 agents with 2k overhead each = 6k tokens wasted
- If task fits in one 30k context, don't shard

## The Composition Test

Before spawning additional agents, ask:

| Question | If Yes | If No |
|----------|--------|-------|
| Is there work product at the end? | Valid spawn | Don't spawn |
| Am I compressing information? | Valid spawn | Don't spawn |
| Is there adversarial tension needed? | Multiple agents | Single agent |
| Would single agent exceed context? | Shard work | Keep single |

All three "no"? Don't spawn.

## The Rule

> Compose agents only when: work requires adversarial tension, expertise differs,
> or context would exceed budget. Otherwise, single focused agent.
> Every spawn must produce work or compression.

## Trust Implications

Composition affects trust:

| Pattern | Trust Level | Why |
|---------|-------------|-----|
| Single narrow agent | HIGH | Bounded scope, clear evidence |
| Adversarial loop | HIGH | Independent verification |
| Sequential chain | MEDIUM | Depends on weakest link |
| Fan-out/fan-in | MEDIUM | Aggregation quality matters |
| Broad coordinator | LOW | Scope too wide |

See [narrow-trust.md](./narrow-trust.md) for the trust equation.

---

## See Also
- [agent-behavioral-contracts.md](./agent-behavioral-contracts.md) - Role families and the two reasons rule
- [narrow-trust.md](./narrow-trust.md) - Trust equation
- [scarcity-enforcement.md](./scarcity-enforcement.md) - Context budgets
- [microloop-rules.md](../execution/microloop-rules.md) - Adversarial loop exit conditions
