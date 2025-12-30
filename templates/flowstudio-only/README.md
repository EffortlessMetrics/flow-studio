# Flow Studio (Standalone)

> For: Teams wanting flow visualization without the full swarm framework
>
> **Note**: The main demo-swarm kernel uses FastAPI for Flow Studio.
> This template intentionally uses Flask as a small, standalone visualizer with its
> own dependencies, isolated from the core runtime.

Visualize any YAML-defined flow graph. A minimal Flask-based tool for rendering
workflow diagrams with Cytoscape.js.

## Quick Start

```bash
# Install dependencies
pip install -e .

# Run the server
python -m flowstudio.server --debug

# Open http://localhost:5000
```

## Directory Structure

```
flowstudio-only/
├── pyproject.toml              # Dependencies: Flask, PyYAML
├── flowstudio/
│   ├── __init__.py             # Package marker
│   ├── config.py               # Configuration management
│   └── server.py               # Flask app with API endpoints
├── config/
│   ├── flows/                  # Flow definitions (YAML)
│   │   └── example.yaml        # Sample flow
│   └── agents/                 # Agent definitions (YAML)
│       └── *.yaml              # Sample agents
├── Dockerfile                  # Container deployment
└── README.md                   # This file
```

## Defining Flows

Create a YAML file in `config/flows/`:

```yaml
key: my-flow
title: "My Custom Flow"
description: "A workflow with multiple steps."
steps:
  - id: step-1
    title: "First Step"
    agents:
      - agent-a
      - agent-b
    role: "Description of what this step does."

  - id: step-2
    title: "Second Step"
    agents:
      - agent-c
    role: "Description of the second step."
```

## Defining Agents

Create a YAML file in `config/agents/`:

```yaml
key: agent-a
category: implementation    # Category for grouping
color: green               # Visual color (yellow, purple, green, red, blue, orange, pink, cyan)
short_role: "Brief description of what this agent does."
model: inherit             # Optional: model configuration
```

### Color Scheme

| Color  | Typical Use Case            |
|--------|----------------------------|
| yellow | Shaping, parsing, early stages |
| purple | Specification, design, architecture |
| green  | Implementation, execution |
| red    | Critics, reviewers |
| blue   | Verification, validation |
| orange | Analytics, monitoring |
| pink   | Reporting |
| cyan   | Infrastructure |

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Main UI (Cytoscape graph) |
| `/api/flows` | GET | List all flows |
| `/api/graph/<key>` | GET | Get graph data for a flow |
| `/api/reload` | POST | Reload config from disk |
| `/health` | GET | Health check |

## API Response Examples

### GET /api/flows

```json
[
  {
    "key": "example",
    "title": "Example Flow - Data Pipeline",
    "description": "A sample 3-step data processing pipeline.",
    "step_count": 3
  }
]
```

### GET /api/graph/example

```json
{
  "nodes": [
    {"data": {"id": "step:example:ingest", "label": "Ingest Data", "type": "step", ...}},
    {"data": {"id": "agent:data-fetcher", "label": "data-fetcher", "type": "agent", ...}}
  ],
  "edges": [
    {"data": {"id": "edge:step:ingest->transform", "source": "...", "target": "...", "type": "step-sequence"}},
    {"data": {"id": "edge:step:ingest->agent:data-fetcher", "source": "...", "target": "...", "type": "step-agent"}}
  ]
}
```

## Docker Deployment

```bash
# Build the image
docker build -t flowstudio .

# Run with mounted config
docker run -p 5000:5000 -v $(pwd)/config:/app/config flowstudio

# Or with Docker Compose
docker-compose up
```

## Production Deployment

For production, use gunicorn:

```bash
pip install gunicorn
gunicorn --bind 0.0.0.0:5000 --workers 4 "flowstudio.server:create_app()"
```

## Optional: FastAPI

Install FastAPI support for async performance:

```bash
pip install -e ".[fastapi]"
```

Then create a FastAPI adapter if needed. The core logic in `server.py` can be
reused with minimal changes.

## Customization

### Custom Config Directory

```bash
python -m flowstudio.server --config-dir /path/to/my/config
```

### Programmatic Usage

```python
from flowstudio import create_app, FlowStudioConfig
from pathlib import Path

config = FlowStudioConfig.from_project_root(Path("/my/project"))
app = create_app(config)
app.run(debug=True)
```

## Integration with Full Swarm

This template extracts the visualization layer from Flow Studio. For the
complete SDLC framework with 7 flows and 56 agents, see:

https://github.com/EffortlessMetrics/flow-studio

## License

MIT
