# Flow Studio

Flow Studio is a visual editor and documentation generator for the swarm's seven flows.

## Quick Start

### 1. See the Swarm Visually

```bash
make flow-studio
```

Then open [http://localhost:5000](http://localhost:5000) in your browser.

You'll see:
- **Left sidebar**: List of flows (Signal, Plan, Build, Review, Gate, Deploy, Wisdom)
- **Center**: Interactive node graph showing flow structure and agents
- **Right panel**: Details about selected flows or agents

### 2. Change a Flow

To reorder steps or change agent descriptions:

```bash
# 1. Edit the flow config
$EDITOR swarm/config/flows/deploy.yaml

# 2. Regenerate Mermaid diagrams and step descriptions
make gen-flows

# 3. Verify everything is in sync
make check-flows

# 4. Commit the changes
git add swarm/config/flows/ swarm/flows/flow-*.md
git commit -m "Update flow configs"
```

## Data Model

### Config Layer (Source of Truth)

Each flow has a **YAML config** at `swarm/config/flows/<key>.yaml`:

```yaml
key: deploy
title: "Flow 5 - Artifact → Prod (Deploy)"
description: "Move an approved artifact from 'ready to merge' to 'deployed'..."

steps:
  - id: decide
    agents:
      - repo-operator
    role: "Merge PR to target branch..."

  - id: monitor
    agents:
      - deploy-monitor
    role: "Watch CI/deployment events..."

  # ... more steps ...

cross_cutting:
  - repo-operator
  - gh-reporter
```

**Key fields:**

- `key` — stable identifier (used in flow spec filenames)
- `title` — human-readable title with flow number
- `description` — one-sentence goal
- `steps[]` — ordered list of execution steps
  - `id` — step identifier (e.g., "decide", "monitor")
  - `agents[]` — agents involved in this step
  - `role` — what this step does (narrative)
- `cross_cutting[]` — agents used across multiple steps

### Generated Layer (Read-Only)

The **flow Markdown** at `swarm/flows/flow-<key>.md` is **automatically generated** from the config:

```markdown
# Flow 5 - Artifact → Prod (Deploy)

...

## Mermaid

​```mermaid
flowchart TD
    ...
​```

## Steps

| Step | Agents | Role |
|------|--------|------|
| 1 | repo-operator | Merge PR... |
| 2 | deploy-monitor | Watch CI... |
...
```

**Do NOT edit the Mermaid or Steps sections by hand.** They will be regenerated when you run `make gen-flows`.

## Making Changes

### Reorder Steps

```bash
# Edit swarm/config/flows/deploy.yaml
# Move "monitor" before "decide" in the steps list

# Then regenerate:
make gen-flows

# The Mermaid diagram and step table will be updated automatically
```

### Change a Step's Role Description

```bash
# Edit the `role:` field in swarm/config/flows/deploy.yaml

# Then regenerate:
make gen-flows
```

### Add a New Step

```yaml
steps:
  # ... existing steps ...

  - id: new_step
    agents:
      - some-agent
    role: "What this step does..."
```

Then run `make gen-flows`.

### Change Which Agents Are in a Step

```yaml
steps:
  - id: decide
    agents:
      - agent-1
      - agent-2  # Added this agent
    role: "..."
```

Then run `make gen-flows`.

## Tools

### `gen_flows.py` — Generate/Update Flow Docs

```bash
# Regenerate all flows
uv run swarm/tools/gen_flows.py

# Check if flows are in sync with config (no changes)
uv run swarm/tools/gen_flows.py --check

# Regenerate a single flow
uv run swarm/tools/gen_flows.py --flow deploy
```

### `flow_studio.py` — Interactive UI

```bash
# Start the server on http://localhost:5000
uv run swarm/tools/flow_studio.py
```

Features:
- See all flows in a list
- Click on a flow to view its structure
- Click on agents/steps to see details
- (v2) Drag to reorder steps; edit roles in the UI

### Make Targets

```bash
make gen-flows      # Regenerate all flow docs
make check-flows    # Verify docs are in sync with config
make flow-studio    # Start interactive UI
make flows-help     # Show this reference
```

## Architecture

The system is split into three layers:

```
config layer (YAML)
    ↓ [gen_flows.py]
markdown layer (Markdown + Mermaid)
    ↓ [flow_studio.py]
UI layer (web browser)
```

**Flow of changes:**

1. You edit `swarm/config/flows/<key>.yaml`
2. Run `make gen-flows` → updates `swarm/flows/flow-*.md` (Mermaid + Steps)
3. Commit the YAML config and generated markdown
4. Optional: run `make flow-studio` to visualize

**Do NOT manually edit flow markdown.** The generator will overwrite your changes.

## Future Enhancements

### v1 (current)

- Read-only visualization of flows and agents
- Generator updates Mermaid and step tables
- CLI-only editing (edit YAML, regenerate)

### v2 (planned)

- Drag-to-reorder steps in the UI
- Edit role descriptions in a side panel
- Direct YAML update from the UI
- Real-time regeneration

### v3 (future)

- Add/remove agents from flows
- Create new steps
- Validate changes before save
- Integration with CI/CD (auto-validate on commit)

## Troubleshooting

**Q: Mermaid diagram didn't update after running `gen_flows.py`**

A: Make sure you edited `swarm/config/flows/<key>.yaml`, not the flow markdown. Run `make check-flows` to verify they're in sync.

**Q: "Flow file does not exist" error**

A: Check that the config `key` matches the flow markdown filename. For example:
- Config: `swarm/config/flows/deploy.yaml` (key = "deploy")
- Markdown: `swarm/flows/flow-deploy.md` (must end in "-<key>.md")

**Q: Flow Studio won't start**

A: Make sure dependencies are installed:
```bash
uv sync
```

FastAPI and its dependencies should be installed automatically. If issues persist, check:
```bash
uv run python -c "import fastapi; print('FastAPI OK')"
```

**Q: I accidentally edited flow-deploy.md by hand. Can I restore it?**

A: Run `make gen-flows` to regenerate from the config. Any manual edits outside the Mermaid/Steps sections will be preserved.

## See Also

- `CLAUDE.md` — Full swarm documentation
- `swarm/positioning.md` — Philosophy and axioms
- `swarm/AGENTS.md` — Agent registry
- `make flows-help` — Quick reference
