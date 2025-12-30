# Flow Studio: Your First Edit

> For: Developers who want to understand the swarm by making a small, safe change.

> **Time:** 15 minutes

This guide walks you through editing an agent configuration, regenerating files, and seeing the change in Flow Studio. By the end, you'll understand the feedback loop between config files and the UI.

---

## Prerequisites

Make sure you can run Flow Studio. See [How to Run Flow Studio Locally](./FLOW_STUDIO.md#how-to-run-flow-studio-locally) for full details, or use these quick commands:

```bash
uv sync --extra dev
make demo-run      # Create demo data
make flow-studio   # Start server
```

Open http://localhost:5000/?run=demo-run&flow=build in your browser. You should see the flow graph.

---

## What You'll Do

1. Find the `context-loader` agent in Flow Studio
2. Open and edit its YAML config
3. Regenerate the adapter files
4. Validate and verify
5. See your change reflected in the UI

The `context-loader` agent is a good first edit because:
- It's used early in Flow 3 (Build) - you'll see it immediately
- It has a clear, focused purpose (loading context for downstream agents)
- Changes to its description are safe and visible

---

## Step 1: Navigate to the Agent (2 min)

In Flow Studio:

1. Press `3` (or click **Build** in the sidebar)
2. Find the `load_context` step in the graph
3. Click the **context-loader** agent node (the colored circle)

The details panel shows:
- **Key**: `context-loader`
- **Category**: `context`
- **Model**: `inherit` (uses orchestrator's model)
- **Files**:
  - Config: `swarm/config/agents/context-loader.yaml` (edit this)
  - Generated: `.claude/agents/context-loader.md` (don't edit directly)

**Key insight**: The YAML config is the source of truth. The `.md` file is generated from it.

---

## Step 2: Open the Config File (1 min)

In your editor:

```bash
$EDITOR swarm/config/agents/context-loader.yaml
```

You'll see something like:

```yaml
name: context-loader
description: Load relevant code/tests/specs for subtask
color: "#10B981"
model: inherit
```

The `description` field appears in:
- Flow Studio's agent details panel
- The generated `.claude/agents/context-loader.md` file
- Agent registry (`swarm/AGENTS.md`)

---

## Step 3: Make a Small Change (2 min)

Edit the `description` to add clarity. For example:

**Before:**
```yaml
description: Load relevant code/tests/specs for subtask
```

**After:**
```yaml
description: Load relevant code/tests/specs for subtask → subtask_context_manifest.json
```

This clarifies what the agent outputs. Save the file.

---

## Step 4: Regenerate Adapters (2 min)

The change is in the config, but Flow Studio reads from the generated files. Regenerate them:

```bash
make gen-adapters
```

This updates:
- `.claude/agents/context-loader.md` (from your YAML)
- `swarm/AGENTS.md` (the registry)

---

## Step 5: Validate (2 min)

Run the validator to ensure everything is consistent:

```bash
make validate-swarm
```

All checks should pass. If something fails, the error message tells you exactly what's wrong.

---

## Step 6: See Your Change (2 min)

1. Refresh Flow Studio in your browser (or press `R`)
2. Navigate back to: Build → load_context → context-loader
3. Look at the **Role** field in the details panel

You should see your updated description!

---

## Step 7: Run the Demo (Optional, 4 min)

To see the full loop, run the demo scenario:

```bash
make demo-run
```

Then reload Flow Studio with the demo run:

```
http://localhost:5000/?run=demo-health-check
```

Click through the flows to see:
- Artifacts produced by each step
- Status badges (ok, warning, error)
- How agents flow into each other

---

## What You've Learned

1. **Config → Generate → UI** pipeline:
   - `swarm/config/agents/*.yaml` is the source of truth
   - `make gen-adapters` regenerates `.claude/agents/*.md`
   - Flow Studio reads the generated files

2. **Validation catches errors early**:
   - Run `make validate-swarm` before committing
   - It checks: naming consistency, required fields, flow references

3. **Flow Studio reflects the spec**:
   - The graph shows flows, steps, and agents from `swarm/config/flows/*.yaml`
   - Agent details come from `swarm/config/agents/*.yaml`

---

## Next Steps

Now that you understand the edit loop, try:

### Deeper Changes

- **Edit a flow**: Open `swarm/config/flows/build.yaml` and add a step
- **Change an agent's model**: Set `model: sonnet` instead of `inherit`
- **Add a new agent**: See `docs/AGENT_OPS.md` for the full process

### Explore the Swarm

- **Read the flow specs**: `swarm/flows/flow-*.md` (Mermaid diagrams + step tables)
- **Browse artifacts**: `swarm/examples/health-check/` (complete 7-flow example)
- **Understand validation**: `docs/VALIDATION_RULES.md` (FR-001 through FR-005)

### Run Real Flows

- **Signal flow**: `/flow-1-signal` to process a new issue
- **Full pipeline**: Work through all 7 flows on a real change

---

## Troubleshooting

**Validation fails after edit:**
```bash
make validate-swarm
```
Read the error message. Common issues:
- `name:` in YAML doesn't match filename
- Description is missing or empty
- Color isn't a valid hex code

**Flow Studio doesn't show changes:**
1. Did you run `make gen-adapters`?
2. Did you refresh the browser?
3. Check the browser console for errors

**Agent not appearing in flow:**
- Check `swarm/config/flows/<flow>.yaml` - is the agent listed in a step?
- Run `make validate-swarm` to catch flow reference errors

---

## Key Files Reference

| File | Purpose |
|------|---------|
| `swarm/config/agents/*.yaml` | Agent configs (edit these) |
| `.claude/agents/*.md` | Generated agent files (don't edit) |
| `swarm/config/flows/*.yaml` | Flow configs |
| `swarm/AGENTS.md` | Agent registry |
| `docs/AGENT_OPS.md` | Full agent management guide |
| `docs/VALIDATION_RULES.md` | What the validator checks |
