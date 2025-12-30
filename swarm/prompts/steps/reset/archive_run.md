# Reset Flow: Archive Run Step

You are executing the **Archive Run** step in Flow 8 (Reset).

Your job is to archive old run artifacts to prevent accumulation in the `.runs/` directory. You implement an **archive-before-delete** policy - no run data is ever deleted without first being safely archived.

## Objective

Archive old run artifacts to:
1. Prevent unbounded growth of the `.runs/` directory
2. Preserve audit trail for historical runs
3. Free up working directory space
4. Maintain compliance with data retention policies

**Archive-before-delete is non-negotiable.** Never delete run data without first creating a verified archive.

## Inputs

From orchestrator context:
- `run_id`: The current run identifier (this run is NEVER archived)
- `RUN_BASE`: Path to run artifacts (`.runs/<run-id>/`)

From repository state (you gather these):
- `.runs/` directory contents
- `.runs/index.json` (run metadata)
- Run creation dates from `run_meta.json` files

Retention policy (defaults, overridable via config):
- `archive_threshold_days`: 7 (runs older than this are archived)
- `max_active_runs`: 10 (maximum runs to keep active)
- `archive_location`: `.runs/.archive/` (relative to repo root)

## Required Invariants

{{git_safety_rules}}

**Archive-Before-Delete Policy:**
- NEVER use `rm -rf` on any run directory without archiving first
- ALWAYS verify archive integrity before removing source
- NEVER archive the current run (`run_id` passed from orchestrator)
- ALWAYS update `.runs/index.json` after archiving

**Compression Requirements:**
- Use `tar.gz` format for cross-platform compatibility
- Include checksum file for verification
- Preserve directory structure within archive

## Retention Criteria

Runs are candidates for archiving if ANY of these conditions apply:

1. **Age-based**: `created_at` in `run_meta.json` is older than `archive_threshold_days`
2. **Count-based**: More than `max_active_runs` exist (archive oldest first)
3. **Status-based**: Run status is `COMPLETED` or `FAILED` (not `IN_PROGRESS`)

**Protected runs (NEVER archive):**
- The current run (`run_id`)
- Runs with status `IN_PROGRESS`
- Runs marked `protected: true` in `run_meta.json`

## Commands

### Step 1: Discover Archive Candidates

```bash
# Anchor to repo root
ROOT=$(git rev-parse --show-toplevel) || exit 2

# Configuration
ARCHIVE_THRESHOLD_DAYS=7
MAX_ACTIVE_RUNS=10
ARCHIVE_DIR="$ROOT/.runs/.archive"
CURRENT_RUN_ID="${RUN_ID:-}"  # Passed from orchestrator

# Create archive directory if needed
mkdir -p "$ARCHIVE_DIR"

# List all run directories (excluding special dirs)
echo "=== Discovering runs ==="
for run_dir in "$ROOT/.runs"/*/; do
  run_id=$(basename "$run_dir")

  # Skip special directories
  case "$run_id" in
    .archive|index.json|_wisdom) continue ;;
  esac

  # Skip current run
  if [ "$run_id" = "$CURRENT_RUN_ID" ]; then
    echo "SKIP (current): $run_id"
    continue
  fi

  # Check run_meta.json for age and status
  meta_file="$run_dir/run_meta.json"
  if [ -f "$meta_file" ]; then
    created_at=$(jq -r '.created_at // empty' "$meta_file" 2>/dev/null)
    status=$(jq -r '.status // "UNKNOWN"' "$meta_file" 2>/dev/null)
    protected=$(jq -r '.protected // false' "$meta_file" 2>/dev/null)

    echo "Found: $run_id (created: $created_at, status: $status, protected: $protected)"

    # Skip protected runs
    if [ "$protected" = "true" ]; then
      echo "SKIP (protected): $run_id"
      continue
    fi

    # Skip in-progress runs
    if [ "$status" = "IN_PROGRESS" ]; then
      echo "SKIP (in-progress): $run_id"
      continue
    fi
  else
    echo "WARN: No run_meta.json for $run_id"
  fi
done
```

### Step 2: Archive Each Candidate

For each run to be archived:

```bash
archive_run() {
  local run_id="$1"
  local run_dir="$ROOT/.runs/$run_id"
  local archive_name="${run_id}.tar.gz"
  local archive_path="$ARCHIVE_DIR/$archive_name"
  local checksum_path="$ARCHIVE_DIR/${run_id}.sha256"

  echo "=== Archiving: $run_id ==="

  # Step 2a: Create compressed archive
  echo "Creating archive..."
  tar -czf "$archive_path" -C "$ROOT/.runs" "$run_id" 2>/dev/null
  if [ $? -ne 0 ]; then
    echo "ERROR: Failed to create archive for $run_id"
    return 1
  fi

  # Step 2b: Generate checksum
  echo "Generating checksum..."
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$archive_path" > "$checksum_path"
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$archive_path" > "$checksum_path"
  else
    echo "WARN: No sha256 tool available, skipping checksum"
  fi

  # Step 2c: Verify archive integrity
  echo "Verifying archive..."
  tar -tzf "$archive_path" >/dev/null 2>&1
  if [ $? -ne 0 ]; then
    echo "ERROR: Archive verification failed for $run_id"
    rm -f "$archive_path" "$checksum_path"
    return 1
  fi

  # Step 2d: Record archive size
  archive_size=$(du -h "$archive_path" | cut -f1)
  echo "Archive created: $archive_name ($archive_size)"

  # Step 2e: Remove source directory (only after verification)
  echo "Removing source directory..."
  rm -rf "$run_dir"
  if [ $? -ne 0 ]; then
    echo "ERROR: Failed to remove source directory for $run_id"
    return 1
  fi

  echo "ARCHIVED: $run_id -> $archive_name"
  return 0
}
```

### Step 3: Update Index

```bash
# Update .runs/index.json to remove archived entries
# Use the demoswarm shim for safe index manipulation
bash .claude/scripts/demoswarm.sh index remove-archived \
  --index "$ROOT/.runs/index.json" \
  --archived-ids "$ARCHIVED_RUN_IDS"
```

## Output

Write exactly one file: `.runs/<run-id>/reset/archive_report.md`

### Output Schema

```markdown
# Run Archive Report

## Summary

| Metric | Value |
|--------|-------|
| Runs Scanned | <count> |
| Runs Archived | <count> |
| Runs Skipped | <count> |
| Space Freed | <size> |
| Archive Location | .runs/.archive/ |

## Archived Runs

| Run ID | Created | Status | Archive Size | Checksum |
|--------|---------|--------|--------------|----------|
| <run-id> | <date> | <status> | <size> | <sha256 prefix> |
| ... | ... | ... | ... | ... |

## Skipped Runs

| Run ID | Reason |
|--------|--------|
| <run-id> | current run |
| <run-id> | in-progress |
| <run-id> | protected |
| ... | ... |

## Archive Verification

| Archive | Integrity Check | Checksum Written |
|---------|-----------------|------------------|
| <run-id>.tar.gz | PASS / FAIL | YES / NO |
| ... | ... | ... |

**All archives verified:** YES / NO

## Index Update

- Entries removed from index: <count>
- Index path: .runs/index.json
- Update timestamp: <ISO8601>

## Errors

<list of any errors encountered, or "none">

## Notes

<any additional context, warnings, or recommendations>
```

{{output_schema_header}}

## Control-Plane Result

Return this block for orchestrator routing:

```yaml
## Archive Run Result
step: archive_run
flow: reset
status: VERIFIED | UNVERIFIED | CANNOT_PROCEED
runs_scanned: <count>
runs_archived: <count>
runs_skipped: <count>
space_freed_bytes: <size in bytes>
space_freed_human: "<size with unit>"
archive_location: ".runs/.archive/"
archived_run_ids:
  - <run-id-1>
  - <run-id-2>
all_archives_verified: true | false
index_updated: true | false
errors: []
```

## Status Semantics

- **VERIFIED**: All archive candidates processed successfully, all archives verified, index updated
- **UNVERIFIED**: Archives created but some verifications failed, or index update failed (archives are still usable)
- **CANNOT_PROCEED**: Mechanical failure (cannot read .runs/, cannot create archive directory, no disk space)

## Decision Logic

### Archive Candidate Selection

```
is_archive_candidate(run) =
  run.id != current_run_id AND
  run.protected != true AND
  run.status != "IN_PROGRESS" AND
  (
    run.age_days > archive_threshold_days OR
    active_run_count > max_active_runs
  )
```

### Archive Priority

When count-based archiving is needed, archive in this order:
1. Oldest runs first (by `created_at`)
2. `FAILED` runs before `COMPLETED` runs (all else equal)

### Verification Requirements

An archive is verified if:
1. `tar -tzf <archive>` returns exit code 0
2. Archive file size > 0 bytes
3. Checksum file was written (if sha256 tool available)

## Handoff

After writing the archive report, explain what you did:

**Clean archiving:**
> "Archived 3 runs older than 7 days. Total space freed: 45MB. All archives verified, checksums written. Index updated to remove archived entries. Ready for verify_clean step."

**Nothing to archive:**
> "Scanned 5 runs, none met archiving criteria. All runs are either current, in-progress, or within retention window. No action taken."

**Partial success:**
> "Archived 2 of 3 candidate runs. Run 'abc123' archive failed verification - source retained, archive removed. Recommend manual investigation."

**Cannot proceed:**
> "Cannot access .runs/ directory. Check permissions. Archive step cannot proceed without read/write access to run storage."

## Philosophy

**Data preservation is paramount.** The archive-before-delete policy ensures no run data is ever lost. Even when storage is constrained, we trade space for safety.

**Verification is non-negotiable.** An archive that cannot be verified is useless. Better to keep the source directory than delete it with a corrupt archive.

**Idempotency matters.** Running this step multiple times should produce the same end state. Already-archived runs stay archived, already-current runs stay current.

## Recovery

If archive verification fails:
1. The source directory is NOT deleted
2. The failed archive is removed
3. The run remains in `.runs/` for the next archive attempt
4. Error is logged in archive_report.md

If disk space is critical:
1. Consider increasing `archive_threshold_days` temporarily
2. Move `.runs/.archive/` to external storage
3. Never delete unarchived runs to free space
