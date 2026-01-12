# Data Retention: Artifact Lifecycle Management

Artifacts have finite lifetimes. This rule defines how long to keep what, and when to clean up.

## Why Retention Matters

Without retention policies:
- Storage grows unbounded
- Old artifacts become noise
- Privacy obligations go unmet
- Costs accumulate silently

With retention policies:
- Predictable storage costs
- Relevant data stays accessible
- Compliance requirements met
- Cleanup is automated

## Retention Periods

| Artifact Type | Location | Retention | Rationale |
|---------------|----------|-----------|-----------|
| Run artifacts | `RUN_BASE/<run-id>/` | 30 days | Debugging window |
| Receipts | `RUN_BASE/<flow>/receipts/` | 90 days | Audit trail |
| LLM transcripts | `RUN_BASE/<flow>/llm/` | 7 days | Cost, privacy |
| Logs | `RUN_BASE/<flow>/logs/` | 30 days | Debugging |
| Handoff envelopes | `RUN_BASE/<flow>/handoffs/` | 30 days | Debugging |
| Routing decisions | `RUN_BASE/<flow>/routing/` | 90 days | Audit trail |
| Git history | `.git/` | Forever | Source of truth |

## Cleanup Policies

### Automated Cleanup Job

Run daily at low-traffic hours:

```python
def cleanup_aged_artifacts():
    """Remove artifacts past retention period."""
    for run_id in list_runs():
        run_age = days_since_created(run_id)

        # Full run cleanup
        if run_age > 30 and not has_exception(run_id):
            archive_or_delete(run_id)
            continue

        # Transcript cleanup (more aggressive)
        if run_age > 7:
            delete_transcripts(run_id)

        # Receipt archival (longer retention)
        if run_age > 90:
            archive_receipts(run_id)
```

### Archive vs Delete

| Action | When | What Happens |
|--------|------|--------------|
| **Delete** | Past retention, no exception | Permanent removal |
| **Archive** | Past active period, audit needed | Compress and move to cold storage |
| **Retain** | Exception applies | Keep until exception cleared |

### Compression for Archives

Archived data uses:
- gzip for JSON/JSONL files
- tar.gz for directory bundles
- Naming: `<run-id>-archive-<date>.tar.gz`

Archive location:
```
swarm/archives/<year>/<month>/<run-id>-archive.tar.gz
```

## Exceptions

### Open PR References

Runs referenced by open PRs are retained until:
```yaml
exception:
  type: open_pr
  pr_number: 123
  run_ids: ["abc123", "def456"]
  expires_when: pr_closed
```

### Incident References

Runs with incidents are retained until post-mortem:
```yaml
exception:
  type: incident
  incident_id: "INC-2024-001"
  run_ids: ["abc123"]
  expires_when: postmortem_complete
  owner: "oncall@example.com"
```

### Compliance Holds

Legal or compliance holds override all retention:
```yaml
exception:
  type: compliance_hold
  hold_id: "LEGAL-2024-001"
  run_ids: ["*"]  # Can be wildcard
  expires_when: manual_release
  authority: "legal@example.com"
```

### Exception Priority

When exceptions conflict:
1. Compliance holds (highest) - never delete
2. Incident references - keep until cleared
3. Open PR references - keep until PR closed
4. Standard retention (lowest) - normal cleanup

## Storage Costs

### Estimates Per Run

| Component | Typical Size | Notes |
|-----------|--------------|-------|
| Receipts | 50-100 KB | JSON, highly compressible |
| Transcripts | 1-10 MB | JSONL, largest component |
| Handoffs | 20-50 KB | JSON, structured |
| Routing logs | 10-30 KB | JSONL, append-only |
| Other artifacts | 100-500 KB | Varies by flow |
| **Total per run** | **2-15 MB** | Uncompressed |
| **Compressed** | **200 KB - 2 MB** | ~10:1 ratio |

### Cost Triggers

| Threshold | Action |
|-----------|--------|
| > 1 GB total | Review oldest runs |
| > 100 runs | Enforce retention |
| > 10 GB total | Emergency cleanup |
| > 30 days old + no exception | Auto-cleanup eligible |

### Monitoring Storage Growth

Track weekly:
```bash
# Total storage
du -sh swarm/runs/

# Run count
ls -d swarm/runs/*/ | wc -l

# Aged runs (>30 days)
find swarm/runs/ -maxdepth 1 -type d -mtime +30 | wc -l

# Transcript size (cleanup priority)
du -sh swarm/runs/*/*/llm/
```

## Privacy Considerations

### PII in Logs/Transcripts

LLM transcripts may contain:
- User input with PII
- Generated content with PII
- Error messages with paths/usernames

**Mitigations:**
- 7-day transcript retention (shortest)
- No transcript archival (delete, don't archive)
- Redaction before archival if needed

### Right to Deletion Requests

On deletion request:
1. Identify all runs containing requester's data
2. Apply compliance hold (preserve for audit)
3. Delete identified artifacts
4. Document deletion in audit log
5. Release hold after confirmation

```yaml
deletion_request:
  requester: "user@example.com"
  received: "2024-01-15"
  runs_identified: ["run-001", "run-002"]
  status: "completed"
  completed: "2024-01-16"
  audit_log: "deletions/2024-01-16-user.log"
```

### Anonymization Options

For runs needed beyond transcript retention:
```python
def anonymize_transcript(transcript_path):
    """Remove PII while preserving structure."""
    # Replace emails
    # Replace usernames
    # Replace file paths with placeholders
    # Keep token counts and timestamps
```

Anonymized transcripts can be retained longer for analysis.

## Implementation Status

| Component | Status | Notes |
|-----------|--------|-------|
| Retention periods | Designed | This document |
| Cleanup job | Designed | Needs implementation |
| Exception handling | Designed | Needs implementation |
| Storage monitoring | Supported | Manual commands above |
| Anonymization | Designed | Needs implementation |

## The Rule

> Artifacts have finite lifetimes. Define retention upfront.
> Automate cleanup. Honor exceptions. Never delete git history.

## Commands

### Check Retention Status
```bash
make retention-status  # Show aged artifacts and exceptions
```

### Manual Cleanup
```bash
make cleanup-aged      # Remove artifacts past retention
make cleanup-transcripts  # Remove transcripts >7 days
```

### Apply Exception
```bash
make retention-hold RUN_ID=abc123 REASON="incident"
make retention-release RUN_ID=abc123
```

---

## See Also
- [receipt-schema.md](./receipt-schema.md) - Receipt structure
- [off-road-logging.md](./off-road-logging.md) - Routing audit trail
- [handoff-protocol.md](./handoff-protocol.md) - Handoff envelope structure
