# Flow Profiles

Profiles are **portable snapshots** of your swarm configuration. They capture flows, agents, and their wiring in a single file that you can save, share, compare, and apply.

## Why Profiles?

- **Snapshot**: Freeze a working configuration before experimenting
- **Share**: Send a colleague your exact swarm setup as one file
- **Compare**: Diff two profiles to see what changed
- **Switch**: Swap between configurations (e.g., teaching vs production)
- **Audit**: Track how your swarm evolves over time

## Quick Start

```bash
# List available profiles
make profile-list

# Save current config as a profile
make profile-save PROFILE_ID=my-baseline LABEL="My Baseline"

# Apply a profile
make profile-load PROFILE_ID=my-baseline

# After loading, regenerate adapters
make gen-flow-constants && make gen-adapters && make ts-build

# Compare two profiles
make profile-diff PROFILE_A=baseline PROFILE_B=experimental

# Compare a profile to current state
make profile-diff PROFILE_A=baseline CURRENT=1
```

## Profile File Format

Profiles use the `.swarm_profile.yaml` extension and live in `swarm/profiles/`.

```yaml
kind: swarm_profile
version: 1

meta:
  id: my-baseline
  label: "My Baseline Configuration"
  description: "7-flow SDLC with default agents"
  created_at: "2025-01-15T10:30:00Z"
  created_by: alice

# Full contents of swarm/config/flows.yaml
flows_yaml: |
  version: 1
  flows:
    - key: signal
      index: 1
      title: "Signal -> Spec"
      ...

# Individual flow definitions
flow_configs:
  - key: signal
    path: swarm/config/flows/signal.yaml
    yaml: |
      key: signal
      title: "Flow 1 - Signal → Spec"
      steps:
        - id: normalize
          agents: [signal-normalizer]
      ...

  - key: build
    path: swarm/config/flows/build.yaml
    yaml: |
      ...

# Agent definitions
agent_configs:
  - key: context-loader
    path: swarm/config/agents/context-loader.yaml
    yaml: |
      key: context-loader
      model: inherit
      flows: [build]
      ...

  - key: requirements-author
    path: swarm/config/agents/requirements-author.yaml
    yaml: |
      ...
```

## Commands Reference

### Save a Profile

```bash
make profile-save PROFILE_ID=<id> [LABEL='...'] [DESCRIPTION='...']
```

Captures:
- `swarm/config/flows.yaml` → `flows_yaml`
- `swarm/config/flows/*.yaml` → `flow_configs`
- `swarm/config/agents/*.yaml` → `agent_configs`

Example:
```bash
make profile-save PROFILE_ID=workshop-baseline \
  LABEL="Workshop Baseline" \
  DESCRIPTION="Clean 7-flow SDLC for teaching"
```

### Load a Profile

```bash
# Preview changes (dry-run, default via CLI)
uv run swarm/tools/profile_load.py baseline

# Apply with backup (safe - via Makefile)
make profile-load PROFILE_ID=baseline

# Apply with backup explicit
make profile-load PROFILE_ID=baseline DRY_RUN=0

# Preview only (no changes)
make profile-load PROFILE_ID=baseline DRY_RUN=1

# Apply without backup (dangerous)
make profile-load PROFILE_ID=baseline FORCE=1
```

**Safety Defaults:**

The CLI tool defaults to dry-run mode for safety:
```
🔒 DRY RUN — showing what would change; no files written.
```

To actually apply changes, use `--apply`:
- `--apply --backup`: Apply with backup files (recommended)
- `--apply --force`: Apply without backup (dangerous)

The Makefile target `make profile-load` defaults to `--apply --backup` for convenience.

**Git Tree Check:** The tool refuses to apply if your git tree is dirty (uncommitted changes), unless you pass `--force`.

Writes profile contents back to their original paths:
- `flows_yaml` → `swarm/config/flows.yaml`
- `flow_configs[*].yaml` → `flow_configs[*].path`
- `agent_configs[*].yaml` → `agent_configs[*].path`

**Current Profile Tracking:** After a successful apply, the loaded profile is tracked in `swarm/profiles/.current_profile`. Flow Studio displays the current profile in its header.

**Important**: After loading a profile, regenerate derived artifacts:
```bash
make gen-flow-constants && make gen-adapters && make ts-build
```

### Compare Profiles

```bash
# Compare two profiles
make profile-diff PROFILE_A=<id> PROFILE_B=<id>

# Compare profile to current working state
make profile-diff PROFILE_A=<id> CURRENT=1
```

Output shows:
- Changed files (unified diff)
- Added entries
- Removed entries

### List Profiles

```bash
make profile-list
```

Shows all profiles in `swarm/profiles/` with their labels.

## Workflow Examples

### Teaching Workflow

```bash
# Before workshop: save clean state
make profile-save PROFILE_ID=workshop-clean LABEL="Workshop Clean State"

# During workshop: make changes...
# ...students experiment...

# After workshop: restore clean state
make profile-load PROFILE_ID=workshop-clean
make gen-flow-constants && make gen-adapters && make ts-build
```

### Experimentation Workflow

```bash
# Save current state
make profile-save PROFILE_ID=before-experiment

# Make experimental changes...
# ...modify flows, agents...

# Compare to baseline
make profile-diff PROFILE_A=before-experiment CURRENT=1

# If experiment failed, restore
make profile-load PROFILE_ID=before-experiment
make gen-flow-constants && make gen-adapters && make ts-build
```

### Team Sharing Workflow

```bash
# Alice saves her optimized config
make profile-save PROFILE_ID=alice-optimized LABEL="Alice's Optimized Flow"

# Share via git
git add swarm/profiles/alice-optimized.swarm_profile.yaml
git commit -m "Add Alice's optimized profile"
git push

# Bob applies it
git pull
make profile-load PROFILE_ID=alice-optimized
make gen-flow-constants && make gen-adapters && make ts-build
```

### Profile-Aware Refactor Workflow

When making structural changes to flows or agents, use profiles as a safety net:

```bash
# 1. Save current state before experimenting
make profile-save PROFILE_ID=before-experiment

# 2. Make your changes
$EDITOR swarm/config/flows/*.yaml
$EDITOR swarm/config/agents/*.yaml

# 3. Regenerate & validate
make gen-flow-constants && make gen-adapters && make ts-build
make validate-swarm

# 4. If you regret everything, restore:
make profile-load PROFILE_ID=before-experiment
make gen-flow-constants && make gen-adapters && make ts-build
make validate-swarm
```

This workflow ensures you can always get back to a known-good state after experimenting with flow or agent configurations.

## What's NOT in a Profile

Profiles capture **configuration**, not runtime state:

| Included | Not Included |
|----------|--------------|
| `flows.yaml` | `swarm/runs/` (run artifacts) |
| Flow configs | `.claude/agents/*.md` (generated) |
| Agent configs | `flowConstants.ts` (generated) |
| | Git history |
| | Environment variables |

Generated files are rebuilt from profile contents via `make gen-*` commands.

## Schema Validation

Profiles are validated against `swarm/schemas/flow_profile.schema.json`.

Required fields:
- `kind`: Must be `"swarm_profile"`
- `version`: Currently `1`
- `meta.id`: Profile identifier (matches filename)
- `meta.label`: Human-readable name

## File Locations

```
swarm/
  profiles/                              # Profile storage
    baseline.swarm_profile.yaml          # Example profile
    workshop-clean.swarm_profile.yaml
  schemas/
    flow_profile.schema.json             # Validation schema
  config/
    flows.yaml                           # Flow ordering (live)
    flows/                               # Flow definitions (live)
    agents/                              # Agent configs (live)
    profile_registry.py                  # Profile operations
  tools/
    profile_save.py                      # Export tool
    profile_load.py                      # Import tool
    profile_diff.py                      # Compare tool
```

## Tips

1. **Name profiles semantically**: `workshop-baseline`, `prod-v2`, `experimental-3flow`
2. **Always regenerate after load**: The adapters and constants must match config
3. **Use dry-run first**: `make profile-load PROFILE_ID=x DRY_RUN=1`
4. **Commit baseline profiles**: Track them in git for reproducibility
5. **Gitignore experimental profiles**: Add to `.gitignore` if you don't want to share

## Flow Studio Integration

When a profile is loaded, Flow Studio displays the current profile in its header badge:

```
Profile: Baseline 7-Flow SDLC
```

This helps you know which configuration you're viewing. The badge shows:
- Profile label (or ID if no label)
- Tooltip with load timestamp and git branch

### Flow/Step Numbering

The `flow_registry.py` module provides consistent numbering:

```python
from swarm.config.flow_registry import (
    get_flow_index,      # Flow 1-7 index
    get_step_index,      # Step index within flow
    get_agent_position,  # Agent's positions: [(flow_key, step_id, flow_idx, step_idx), ...]
    get_total_flows,     # Total flows (7)
    get_total_steps,     # Steps in a flow
)

# Example: context-loader is at Build (3/6), Step 2/12
positions = get_agent_position("context-loader")
# [("build", "load_context", 3, 2)]
```

This numbering is stable because it comes from `swarm/config/flows.yaml` (captured in profiles). When you swap profiles, the numbering reflects that profile's flow structure.

## Related Documentation

- [VALIDATION_RULES.md](./VALIDATION_RULES.md) - Config validation (FR-001 through FR-005)
- [AGENT_OPS.md](./AGENT_OPS.md) - Agent configuration workflow
- [FLOW_STUDIO.md](./FLOW_STUDIO.md) - Visual flow exploration
