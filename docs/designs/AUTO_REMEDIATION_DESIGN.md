# Auto-Remediation Executor Design

## Status

**Proposed**

---

## 1. Problem Statement

### Current State

The selftest system already includes a suggestion engine (`selftest_suggest_remediation.py`) that:

1. Reads `selftest_degradations.log` containing failures from degraded-mode runs
2. Matches error patterns against `swarm/config/selftest_remediation_map.yaml`
3. Outputs actionable remediation commands to stdout

**Design Principle (current)**: Read-only suggestions, not auto-execution.

### Pain Points

1. **Manual copy-paste loop**: Developers must manually copy suggested commands, paste them into terminal, and execute them. This adds friction to the feedback loop.

2. **Human error risk**: Copy-paste can introduce typos, truncation, or execution in the wrong directory. Commands like `make gen-adapters` are safe, but incorrect execution context causes silent failures.

3. **Slow iteration**: Each selftest failure requires:
   - Run selftest (30s-2min)
   - Review output, identify failure
   - Run `make selftest-suggest-remediation`
   - Copy command
   - Paste and execute
   - Re-run selftest to verify

   This loop could be tightened with automation.

4. **No audit trail for remediations**: When fixes are applied manually, there is no record of what was run, when, by whom, or whether it succeeded. This makes debugging regressions harder.

5. **CI/CD friction**: In automated pipelines, manual intervention blocks progress. Safe auto-remediation could unblock certain scenarios without human presence.

### Important Caveat: Out-of-Band Only

Auto-remediation operates **entirely outside** the seven SDLC flows (Signal, Plan, Build, Review, Gate, Deploy, Wisdom). It is a standalone utility that:

- Runs **before** or **after** flows, never **during**
- Fixes **tooling and governance** issues (lint, config sync, AC freshness), not **logic or design** issues
- Cannot be invoked by agents within a flow
- Cannot block developers from running flows

Agents never call auto-remediation. Developers call it manually or CI triggers it between workflow runs. This separation ensures that flow microloops remain pure and deterministic.

### Goal

Create an **Auto-Remediation Executor** that:

1. Reads suggestions from the existing suggestion engine
2. Executes safe remediations with explicit approval
3. Provides dry-run preview before execution
4. Logs all actions to an immutable audit trail
5. Integrates with approval workflows (CLI, Slack, GitHub)

---

## 2. Architecture

```
+-------------------------+     +------------------------+     +---------------------+
|                         |     |                        |     |                     |
| selftest_suggest_       |---->| remediation_executor   |---->| approval_gate       |
| remediation.py          |     | (dry-run first)        |     | (CLI/Slack/GitHub)  |
|                         |     |                        |     |                     |
+-------------------------+     +------------------------+     +---------------------+
                                        |                              |
                                        v                              v
                                +----------------+             +------------------+
                                |                |             |                  |
                                | audit_log.jsonl|             | execute & commit |
                                |                |             |                  |
                                +----------------+             +------------------+
```

### Component Responsibilities

| Component | Responsibility |
|-----------|----------------|
| `selftest_suggest_remediation.py` | Pattern matching, suggestion generation (existing) |
| `remediation_executor.py` | Orchestration: reads suggestions, performs dry-run, requests approval, executes |
| `approval_gate` | Human-in-the-loop: CLI prompt, Slack button, or GitHub PR comment |
| `audit_log.jsonl` | Immutable append-only log of all remediation attempts |
| `remediation_allowlist.yaml` | Defines which patterns are safe for auto-execution |

### Data Flow

1. **Input**: Developer runs `make selftest-remediate` or CI triggers remediation
2. **Suggestion fetch**: Executor calls suggestion engine to get pending remediations
3. **Allowlist check**: Filter suggestions against allowlist; block non-allowed patterns
4. **Dry-run**: Execute each command with `--dry-run` flag or equivalent; capture diff
5. **Approval request**: Present dry-run output to human; wait for approval
6. **Execute**: If approved, execute command for real; capture output
7. **Audit**: Log the entire transaction (suggestion, dry-run, approval, execution) to audit log
8. **Report**: Print summary; optionally post to GitHub PR

---

## 2.5 Out-of-Band Execution Model

This section clarifies how auto-remediation relates to the seven SDLC flows and establishes boundaries that prevent interference with normal development workflows.

### 2.5.1 Relationship to the Seven Flows

Auto-remediation is **out-of-band**, operating OUTSIDE and INDEPENDENT of the seven SDLC flows:

| Aspect | Seven Flows (Signal → Wisdom) | Auto-Remediation |
|--------|----------------------------|------------------|
| **Scope** | Feature development, bug fixes, design work | Tooling hygiene, governance alignment |
| **Invocation** | `/flow-N-*` commands by developer or orchestrator | `make selftest-remediate` by developer or CI |
| **Artifacts** | `RUN_BASE/<flow>/` directories | `selftest_remediation_audit.jsonl` |
| **Agent involvement** | Domain agents execute within flows | No agents; pure tooling |
| **Iteration model** | Microloops (author ⇄ critic) | Single-shot fixes |

The flows produce **business value artifacts** (requirements, ADRs, code, tests). Auto-remediation produces **tooling alignment** (regenerated adapters, lint fixes, AC matrix updates).

### 2.5.2 Design Principle: No Mid-Flow Blocking

**Guarantee**: Auto-remediation will NEVER:

1. **Block developers from running flows** — Flows are always executable regardless of remediation state
2. **Insert dependencies into flow microloops** — The author ⇄ critic cycles do not wait for remediation
3. **Modify flow artifacts** — Remediation only touches `swarm/config/`, `.claude/agents/`, lint files; never `RUN_BASE/`
4. **Require execution before flow runs** — Developers can skip auto-remediation entirely

**Corollary**: Auto-remediation can be disabled, broken, or skipped without impacting the ability to execute any flow. Flows are self-contained; remediation is optional maintenance.

### 2.5.3 When Auto-Remediation Applies vs. Does Not Apply

| Category | Auto-Remediation Applies | Auto-Remediation Does NOT Apply |
|----------|--------------------------|--------------------------------|
| **Config drift** | Adapter frontmatter out of sync with config YAML | Business logic errors in agent prompts |
| **Lint violations** | Ruff/format errors in tooling scripts | Test failures in `tests/` |
| **AC freshness** | Matrix missing newly added acceptance criteria | AC logic incorrect or incomplete |
| **Flow docs** | Autogen sections stale | Flow design decisions wrong |
| **Governance failures** | Selftest steps that can be fixed mechanically | Design flaws, security vulnerabilities |

**Rule of thumb**: If the fix is **deterministic and mechanical** (run a make target, apply a linter), auto-remediation applies. If the fix requires **judgment or design decisions**, it does not.

### 2.5.4 Timing Diagram

```
Time →

┌─────────────────────────────────────────────────────────────────────────────┐
│                                                                             │
│  Selftest (standalone)                                                      │
│  ┌──────────────────────┐                                                   │
│  │ make selftest        │                                                   │
│  │   ├─ KERNEL: PASS    │                                                   │
│  │   ├─ GOVERNANCE: FAIL│──┐                                                │
│  │   └─ OPTIONAL: SKIP  │  │                                                │
│  └──────────────────────┘  │                                                │
│                            │                                                │
│                            v                                                │
│  Degradation Log           │                                                │
│  ┌──────────────────────┐  │                                                │
│  │ selftest_degradations│<─┘                                                │
│  │ .log                 │                                                   │
│  └──────────────────────┘                                                   │
│            │                                                                │
│            v                                                                │
│  Auto-Remediation Layer (OUT-OF-BAND)                                       │
│  ┌──────────────────────────────────────────┐                               │
│  │ make selftest-remediate                  │                               │
│  │   ├─ Read degradation log                │                               │
│  │   ├─ Match patterns → suggestions        │                               │
│  │   ├─ Dry-run → show diff                 │                               │
│  │   ├─ Request approval                    │                               │
│  │   ├─ Execute (if approved)               │                               │
│  │   └─ Write audit log                     │                               │
│  └──────────────────────────────────────────┘                               │
│                                                                             │
│  ═══════════════════════════════════════════════════════════════════════    │
│  INDEPENDENT EXECUTION BOUNDARY                                             │
│  ═══════════════════════════════════════════════════════════════════════    │
│                                                                             │
│  Developer Flows (ALWAYS AVAILABLE)                                         │
│  ┌────────────────────────────────────────────────────────────────────┐     │
│  │                                                                    │     │
│  │  /flow-1-signal ──→ /flow-2-plan ──→ /flow-3-build ──→ ...        │     │
│  │       │                  │                 │                       │     │
│  │       v                  v                 v                       │     │
│  │  RUN_BASE/signal/   RUN_BASE/plan/   RUN_BASE/build/              │     │
│  │                                                                    │     │
│  │  These flows execute regardless of auto-remediation state          │     │
│  │                                                                    │     │
│  └────────────────────────────────────────────────────────────────────┘     │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 2.5.5 Use Cases

| Context | Selftest | Auto-Remediation | Flows | Notes |
|---------|----------|------------------|-------|-------|
| **Local dev (happy path)** | `make selftest` PASS | Not needed | Run freely | Normal workflow |
| **Local dev (governance fail)** | `make selftest-degraded` PASS | `make selftest-remediate` | Run freely | Fix governance at leisure |
| **CI/CD (pre-merge)** | `make selftest` in PR check | CI can auto-remediate lint | Gate blocks on selftest | PR must pass selftest |
| **Degraded mode** | KERNEL PASS, GOV FAIL | Optional; developer chooses | Run freely | Documented degradation is acceptable |
| **Post-flow (wisdom)** | May reveal new issues | Address in next cycle | Complete | Learnings feed forward |

### 2.5.6 Comparison: Flow Agents vs. Auto-Remediation

| Dimension | Flow Agents | Auto-Remediation |
|-----------|-------------|------------------|
| **Execution context** | Within flow orchestration | Standalone CLI or CI |
| **Invocation** | Orchestrator calls agent | Developer runs `make` target |
| **Blocking behavior** | Part of microloop; must complete | Never blocks flows |
| **Artifact generation** | Writes to `RUN_BASE/<flow>/` | Writes to working tree + audit log |
| **Judgment required** | Yes (design, implementation, review) | No (mechanical fixes only) |
| **Iteration model** | Microloops with critics | Single-shot execution |
| **Can be skipped** | Only by human decision at flow boundary | Always; no impact on flows |
| **Model usage** | Uses Claude (haiku/sonnet/opus) | No LLM; pure deterministic scripts |
| **Scope** | Feature work, bug fixes | Tooling hygiene |

### 2.5.7 Safety Boundary Summary

The out-of-band execution model provides these safety guarantees:

1. **Isolation**: Auto-remediation cannot corrupt flow artifacts
2. **Independence**: Flows execute without remediation as a prerequisite
3. **Auditability**: All remediations logged separately from flow receipts
4. **Reversibility**: Remediation changes are git-restorable; flow state unaffected
5. **Opt-in**: Developers consciously invoke remediation; it never runs implicitly within flows

**Design invariant**: If auto-remediation is broken, disabled, or unavailable, all seven flows remain fully functional. The swarm's core value proposition (flows producing auditable artifacts) is preserved.

---

## 3. Safety Framework

### 3.1 Defense in Depth

The executor implements multiple safety layers:

| Layer | Mechanism | Purpose |
|-------|-----------|---------|
| **L1: Allowlist** | Only patterns in `remediation_allowlist.yaml` can auto-execute | Prevent arbitrary command execution |
| **L2: Dry-run** | Always show diff/output before real execution | Human can verify expected changes |
| **L3: Approval** | Require explicit human action (y/n, button click, comment) | No silent execution |
| **L4: Timeout** | Auto-reject if no approval within configurable window (default: 10 min) | Prevent stale approvals |
| **L5: Audit** | Log every action with timestamp, actor, command, result | Full traceability |
| **L6: Rollback hint** | Log git SHA before execution; suggest rollback command | Recovery path documented |

### 3.2 Approval Flow

```
Pending Remediation Detected
           |
           v
    Is pattern in allowlist?
           |
    +------+------+
    |             |
   Yes           No
    |             |
    v             v
 Dry-run     Skip + warn
    |
    v
 Show diff to human
    |
    v
 Request approval (with timeout)
    |
    +------+------+------+
    |             |      |
 Approve      Reject   Timeout
    |             |      |
    v             v      v
 Execute      Skip    Auto-reject
    |
    v
 Log result
```

### 3.3 Approval Channels

| Channel | Implementation | Use Case |
|---------|---------------|----------|
| **CLI** | Interactive `y/n` prompt | Local development |
| **Slack** | Button message via Slack API | Team notification, async approval |
| **GitHub** | PR comment with `/approve-remediation` command | CI/CD integration |

Phase 1 implements CLI only; Slack and GitHub are Phase 2/3.

---

## 4. Allowlisted Remediations (Safe to Auto-Execute)

These patterns are **safe** because they are:
- Idempotent (running twice produces same result)
- Non-destructive (no data loss, no file deletion)
- Reversible (changes can be undone via git)
- Local (no network calls, no external services)

| Pattern ID | Command | Rationale |
|------------|---------|-----------|
| `gen-adapters` | `make gen-adapters` | Regenerates adapter files from config; idempotent |
| `ruff-fix` | `uv run ruff check --fix` | Auto-fixes lint issues; safe, reversible |
| `ac-freshness-update` | `uv run swarm/tools/check_selftest_ac_freshness.py --update` | Updates AC matrix; idempotent |
| `gen-flows` | `make gen-flows` | Regenerates flow docs; idempotent |
| `validate-swarm` | `make validate-swarm` | Read-only validation; no side effects |

### Allowlist Schema

```yaml
# swarm/config/remediation_allowlist.yaml
version: "1.0.0"

allowed_patterns:
  - id: gen-adapters
    commands:
      - make gen-adapters
    dry_run_command: make gen-adapters --dry-run  # If available
    dry_run_mode: git-diff  # Use git diff to show changes
    max_file_changes: 50
    allowed_paths:
      - ".claude/agents/*.md"
      - "swarm/config/agents/*.yaml"

  - id: ruff-fix
    commands:
      - uv run ruff check --fix
    dry_run_command: uv run ruff check --diff
    dry_run_mode: command-output
    max_file_changes: 100
    allowed_paths:
      - "swarm/**/*.py"
      - "tests/**/*.py"

  - id: ac-freshness-update
    commands:
      - uv run swarm/tools/check_selftest_ac_freshness.py --update
    dry_run_command: uv run swarm/tools/check_selftest_ac_freshness.py --check
    dry_run_mode: command-output
    max_file_changes: 5
    allowed_paths:
      - "docs/SELFTEST_AC_MATRIX.md"

  - id: gen-flows
    commands:
      - make gen-flows
    dry_run_mode: git-diff
    max_file_changes: 20
    allowed_paths:
      - "swarm/flows/*.md"
```

---

## 5. Blocklisted Remediations (Never Auto-Execute)

These patterns are **blocked** because they:
- Have irreversible effects
- Touch external systems
- Require human judgment
- Handle sensitive data

| Pattern | Reason Blocked |
|---------|----------------|
| `git commit` / `git push` | Permanent changes to history; requires commit message judgment |
| `git reset --hard` | Destructive; loses uncommitted work |
| File deletions (`rm`, `unlink`) | Data loss risk |
| Config changes outside `swarm/` | May affect production |
| Commands requiring secrets | Security risk; should never be auto-executed |
| Database migrations | Schema changes require review |
| Network calls (`curl`, `wget`) | External system interaction |

### Blocklist Enforcement

The executor will:
1. Parse each command before execution
2. Check against blocklist patterns (regex matching)
3. Reject any command matching blocklist, even if in allowlist
4. Log rejection with reason

```python
BLOCKLIST_PATTERNS = [
    r"git\s+(commit|push|reset\s+--hard|merge|rebase)",
    r"rm\s+-rf?",
    r"curl|wget|http|https://",
    r"DROP|DELETE|TRUNCATE",  # SQL patterns
    r"--secret|--token|--password|--key",
    r"\.env|credentials|secrets",
]
```

---

## 6. API Design

```python
# swarm/tools/selftest_remediate_execute.py

from dataclasses import dataclass
from enum import Enum
from typing import List, Optional
from pathlib import Path


class ApprovalStatus(Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    TIMEOUT = "timeout"


class ExecutionStatus(Enum):
    NOT_STARTED = "not_started"
    DRY_RUN_COMPLETE = "dry_run_complete"
    EXECUTING = "executing"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class Remediation:
    """A single remediation suggestion with execution context."""
    id: str
    pattern_id: str
    step_id: str
    command: str
    rationale: str
    severity: str
    timestamp: str


@dataclass
class DryRunResult:
    """Result of executing a command in dry-run mode."""
    remediation_id: str
    command: str
    diff: str  # Git diff or command output showing changes
    affected_files: List[str]
    file_count: int
    safe_to_execute: bool
    warnings: List[str]


@dataclass
class ApprovalResult:
    """Result of the approval process."""
    remediation_id: str
    status: ApprovalStatus
    approver: Optional[str]
    channel: str  # "cli", "slack", "github"
    timestamp: str
    timeout_seconds: int


@dataclass
class ExecuteResult:
    """Result of executing a remediation."""
    remediation_id: str
    status: ExecutionStatus
    command: str
    stdout: str
    stderr: str
    exit_code: int
    duration_ms: int
    git_commit_before: str
    git_commit_after: Optional[str]


# Public API functions

def get_pending_remediations(
    degradation_log: Path = Path("selftest_degradations.log"),
    remediation_map: Path = Path("swarm/config/selftest_remediation_map.yaml"),
) -> List[Remediation]:
    """
    Read suggestions from selftest output.

    Calls the existing suggestion engine and converts output
    to Remediation objects.

    Returns:
        List of pending remediations that match known patterns.
    """
    ...


def check_allowlist(
    remediation: Remediation,
    allowlist_path: Path = Path("swarm/config/remediation_allowlist.yaml"),
) -> tuple[bool, Optional[str]]:
    """
    Check if a remediation pattern is in the allowlist.

    Returns:
        (is_allowed, rejection_reason) - True if allowed, False with reason if not.
    """
    ...


def dry_run(
    remediation: Remediation,
    working_dir: Path = Path.cwd(),
) -> DryRunResult:
    """
    Execute the remediation in dry-run mode.

    Depending on the pattern configuration, this either:
    1. Runs the command with a --dry-run flag
    2. Runs the command and captures git diff before/after
    3. Runs a separate dry-run command defined in allowlist

    Returns:
        DryRunResult with diff and safety assessment.
    """
    ...


def request_approval(
    remediation: Remediation,
    dry_run_result: DryRunResult,
    channel: str = "cli",
    timeout_seconds: int = 600,  # 10 minutes
) -> ApprovalResult:
    """
    Request human approval for the remediation.

    For CLI: Shows diff and prompts y/n
    For Slack: Posts message with approve/reject buttons
    For GitHub: Creates PR comment with /approve command

    Returns:
        ApprovalResult with status and approver info.
    """
    ...


def execute(
    remediation: Remediation,
    approval: ApprovalResult,
    working_dir: Path = Path.cwd(),
) -> ExecuteResult:
    """
    Execute the remediation command.

    Prerequisites:
    - Approval status must be APPROVED
    - Command must pass blocklist check

    Actions:
    1. Record git SHA before execution
    2. Execute the command
    3. Capture stdout/stderr
    4. Log to audit log

    Returns:
        ExecuteResult with execution details.
    """
    ...


def write_audit_log(
    remediation: Remediation,
    dry_run_result: DryRunResult,
    approval: ApprovalResult,
    execute_result: Optional[ExecuteResult],
    audit_log_path: Path = Path("selftest_remediation_audit.jsonl"),
) -> None:
    """
    Write a complete audit entry for the remediation attempt.

    The audit log is append-only JSONL format.
    Each entry contains the full transaction chain.
    """
    ...
```

---

## 7. Slack Integration (Phase 2)

### Message Format

```
:warning: Selftest Remediation Request

Step: agents-governance (GOVERNANCE tier)
Pattern: gen-adapters
Command: make gen-adapters

Dry-run preview:
```diff
- old_content
+ new_content
```

Affected files (3):
- .claude/agents/foo-bar.md
- .claude/agents/baz-qux.md
- swarm/config/agents/foo-bar.yaml

[Approve] [Reject]

Timeout: 10 minutes remaining
```

### Slack API Integration

```python
def post_approval_request_to_slack(
    remediation: Remediation,
    dry_run_result: DryRunResult,
    channel_id: str,
    webhook_url: str,
) -> str:
    """
    Post approval request to Slack channel.

    Returns:
        approval_id for tracking the response
    """
    payload = {
        "channel": channel_id,
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f":warning: *Selftest Remediation Request*\n\n"
                           f"*Step:* {remediation.step_id}\n"
                           f"*Pattern:* {remediation.pattern_id}\n"
                           f"*Command:* `{remediation.command}`"
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Dry-run preview:*\n```{dry_run_result.diff[:1000]}```"
                }
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Approve"},
                        "style": "primary",
                        "action_id": f"approve_{remediation.id}"
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Reject"},
                        "style": "danger",
                        "action_id": f"reject_{remediation.id}"
                    }
                ]
            }
        ]
    }
    # ... send to webhook
```

### Callback Handler

```python
def handle_slack_callback(payload: dict) -> None:
    """
    Handle Slack interactive message callback.

    Called when user clicks Approve or Reject button.
    """
    action_id = payload["actions"][0]["action_id"]
    user = payload["user"]["name"]

    if action_id.startswith("approve_"):
        remediation_id = action_id.replace("approve_", "")
        # Update approval status in database/file
        # Trigger execution
        # Post result back to Slack
    elif action_id.startswith("reject_"):
        remediation_id = action_id.replace("reject_", "")
        # Log rejection
        # Post confirmation to Slack
```

---

## 8. Audit Log Schema

### JSONL Format

Each line in `selftest_remediation_audit.jsonl` is a complete JSON object:

```json
{
  "version": "1.0",
  "timestamp": "2025-12-01T12:00:00Z",
  "remediation_id": "rem-abc123",
  "transaction_id": "tx-xyz789",

  "suggestion": {
    "pattern_id": "gen-adapters",
    "step_id": "agents-governance",
    "command": "make gen-adapters",
    "severity": "governance",
    "rationale": "Config is out of sync"
  },

  "allowlist_check": {
    "allowed": true,
    "pattern_matched": "gen-adapters",
    "max_file_changes": 50
  },

  "dry_run": {
    "timestamp": "2025-12-01T12:00:05Z",
    "command": "make gen-adapters",
    "diff_summary": "+3 -2 in 3 files",
    "affected_files": [
      ".claude/agents/foo-bar.md",
      ".claude/agents/baz-qux.md"
    ],
    "file_count": 2,
    "safe_to_execute": true,
    "warnings": []
  },

  "approval": {
    "status": "approved",
    "approver": "developer@example.com",
    "channel": "cli",
    "requested_at": "2025-12-01T12:00:10Z",
    "decided_at": "2025-12-01T12:00:15Z",
    "timeout_seconds": 600
  },

  "execution": {
    "status": "success",
    "started_at": "2025-12-01T12:00:16Z",
    "completed_at": "2025-12-01T12:00:18Z",
    "duration_ms": 2340,
    "exit_code": 0,
    "stdout_summary": "Generated 2 adapter files",
    "stderr": "",
    "git_sha_before": "abc1234",
    "git_sha_after": "def5678"
  },

  "metadata": {
    "hostname": "dev-machine",
    "user": "developer",
    "working_dir": "/home/developer/project",
    "git_branch": "feat/selftest-resilience"
  }
}
```

### Log Rotation

The audit log should be rotated periodically:

```bash
# Rotate logs monthly
selftest_remediation_audit.jsonl
selftest_remediation_audit.2025-11.jsonl
selftest_remediation_audit.2025-10.jsonl
```

### Query Examples

```bash
# Find all approved remediations in the last week
cat selftest_remediation_audit.jsonl | \
  jq 'select(.approval.status == "approved") |
      select(.timestamp > "2025-11-24")'

# Find all failed executions
cat selftest_remediation_audit.jsonl | \
  jq 'select(.execution.status == "failed")'

# Count remediations by pattern
cat selftest_remediation_audit.jsonl | \
  jq -r '.suggestion.pattern_id' | sort | uniq -c

# Find who approved the most remediations
cat selftest_remediation_audit.jsonl | \
  jq -r 'select(.approval.status == "approved") | .approval.approver' | \
  sort | uniq -c | sort -rn
```

---

## 9. Implementation Plan

### Phase 1: CLI Tool with Local Approval (2-3 weeks)

**Deliverables**:
1. `selftest_remediate_execute.py` - Core executor module
2. `remediation_allowlist.yaml` - Initial allowlist config
3. CLI integration via `make selftest-remediate`
4. Audit log infrastructure
5. Unit tests for all functions
6. Integration test with actual remediation

**User Flow**:
```bash
$ make selftest-remediate

=== Auto-Remediation Executor ===

Found 2 pending remediations:

[1/2] gen-adapters
  Step: agents-governance
  Command: make gen-adapters

  Dry-run preview:
  --- .claude/agents/foo-bar.md
  +++ .claude/agents/foo-bar.md (regenerated)
  @@ -1,3 +1,3 @@
   ---
  -name: foo-bar
  +name: foo-bar
   description: Example agent

  Affected files: 2

  Execute this remediation? [y/N] y

  Executing: make gen-adapters
  ... (output)

  Success! Changes applied.
  Audit log: selftest_remediation_audit.jsonl

[2/2] ruff-fix
  Step: core-checks
  Command: uv run ruff check --fix

  Dry-run preview:
  ... (diff)

  Execute this remediation? [y/N] n

  Skipped.

=== Summary ===
Executed: 1
Skipped: 1
Audit log: selftest_remediation_audit.jsonl
```

### Phase 2: Slack Integration (2 weeks)

**Deliverables**:
1. Slack webhook configuration
2. Message formatting with buttons
3. Callback handler for button clicks
4. Timeout handling
5. Thread replies for execution results

### Phase 3: GitHub PR Integration (2 weeks)

**Deliverables**:
1. GitHub Actions workflow integration
2. PR comment parsing for `/approve-remediation`
3. Status checks integration
4. Bot user setup and permissions

---

## 10. Testing Strategy

### Unit Tests

```python
# tests/test_remediation_executor.py

class TestAllowlistCheck:
    def test_allowed_pattern_passes(self):
        """Patterns in allowlist should be allowed."""
        ...

    def test_unknown_pattern_rejected(self):
        """Patterns not in allowlist should be rejected."""
        ...

    def test_blocklist_overrides_allowlist(self):
        """Blocklisted commands rejected even if pattern allowed."""
        ...


class TestDryRun:
    def test_dry_run_captures_diff(self):
        """Dry run should capture git diff of changes."""
        ...

    def test_dry_run_counts_affected_files(self):
        """Should accurately count affected files."""
        ...

    def test_dry_run_warns_on_large_changes(self):
        """Should warn if changes exceed max_file_changes."""
        ...


class TestApproval:
    def test_cli_approval_accepts_y(self):
        """CLI should accept 'y' as approval."""
        ...

    def test_cli_approval_rejects_n(self):
        """CLI should reject on 'n'."""
        ...

    def test_timeout_auto_rejects(self):
        """Should auto-reject after timeout."""
        ...


class TestExecution:
    def test_execution_records_git_sha(self):
        """Should record git SHA before and after."""
        ...

    def test_execution_logs_to_audit(self):
        """Should write to audit log."""
        ...

    def test_execution_blocked_without_approval(self):
        """Should refuse to execute without approval."""
        ...


class TestAuditLog:
    def test_audit_log_is_valid_jsonl(self):
        """Each line should be valid JSON."""
        ...

    def test_audit_log_has_required_fields(self):
        """Each entry should have all required fields."""
        ...
```

### Integration Tests

```python
# tests/test_remediation_e2e.py

class TestEndToEnd:
    def test_full_remediation_flow(self, tmp_path):
        """
        E2E test:
        1. Create degradation log with known failure
        2. Run executor
        3. Approve via CLI
        4. Verify changes applied
        5. Verify audit log written
        """
        ...

    def test_rejected_remediation_leaves_no_changes(self, tmp_path):
        """Rejected remediation should not modify files."""
        ...
```

### Mock Slack Tests

```python
# tests/test_slack_integration.py

class TestSlackIntegration:
    @pytest.fixture
    def mock_slack_api(self):
        """Mock Slack API for testing."""
        ...

    def test_approval_request_message_format(self, mock_slack_api):
        """Message should include command, diff, and buttons."""
        ...

    def test_callback_handling(self, mock_slack_api):
        """Button clicks should be handled correctly."""
        ...
```

---

## 11. Risks and Mitigations

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Allowlist too permissive, unsafe command executed | Medium | High | Conservative initial allowlist; blocklist as safety net; all changes reversible via git |
| Dry-run differs from actual execution | Low | Medium | Use same command with --dry-run flag where possible; compare file counts |
| Approval timeout too short for async workflows | Medium | Low | Configurable timeout; default 10 min; document expected workflows |
| Audit log grows unbounded | Low | Low | Log rotation; archive old logs; keep only 90 days by default |
| Slack webhook security | Medium | High | Store webhook URL in secrets; validate callback signatures |
| Race condition: multiple remediations for same file | Low | Medium | Lock file during execution; fail fast if lock held |
| Confusion about flow integration | Medium | Medium | Section 2.5 explicitly documents out-of-band model; agents never invoke remediation; flows remain independent; training materials emphasize separation |

---

## 12. Success Criteria

### Phase 1 (CLI)

- [ ] Can execute `make selftest-remediate` and see pending remediations
- [ ] Dry-run shows accurate diff of proposed changes
- [ ] Approval prompt works correctly (y/n/timeout)
- [ ] Execution applies changes successfully
- [ ] Audit log contains complete transaction record
- [ ] All allowlisted patterns work correctly
- [ ] Blocklist prevents dangerous commands

### Phase 2 (Slack)

- [ ] Approval request posts to Slack with buttons
- [ ] Button clicks trigger appropriate action
- [ ] Timeout auto-rejects and posts notification
- [ ] Execution results posted as thread reply

### Phase 3 (GitHub)

- [ ] PR comment `/approve-remediation` triggers execution
- [ ] Status check updated with result
- [ ] Execution logs available in Actions

---

## 13. Open Questions

1. **Should auto-remediation commit changes?**
   - Current design: No, execution only modifies working tree
   - Alternative: Auto-commit with standard message
   - Recommendation: Keep manual commit for Phase 1; revisit for CI/CD use case

2. **How to handle multiple pending remediations?**
   - Current design: Process sequentially, approve each individually
   - Alternative: Batch approval for same-pattern remediations
   - Recommendation: Start with sequential; add batch in Phase 2

3. **Should dry-run always use git diff?**
   - Some commands have native --dry-run (e.g., ruff check --diff)
   - Git diff captures all changes but may miss command output
   - Recommendation: Configurable per-pattern in allowlist

4. **What happens if execution fails?**
   - Current design: Log failure, leave working tree in partial state
   - Alternative: Attempt rollback via git restore
   - Recommendation: Log failure, suggest manual recovery; no auto-rollback

---

## 14. References

- Existing suggestion engine: `swarm/tools/selftest_suggest_remediation.py`
- Remediation map: `swarm/config/selftest_remediation_map.yaml`
- Selftest system docs: `docs/SELFTEST_SYSTEM.md`
- Swarm philosophy: `swarm/positioning.md`
- Phase 3 backlog: `PHASE_3_TASKS.md` (P4.1)
