# Platform Governance Status Endpoint

The Flow Studio FastAPI app has been extended with a `/platform/status` endpoint that provides real-time governance status tracking for the demo-swarm system.

## Quick Start

Start Flow Studio:
```bash
make flow-studio
```

Check governance status (in another terminal):
```bash
curl http://localhost:5000/platform/status | jq .
```

Or use the Makefile target:
```bash
make check-platform-status
```

## Endpoints

### GET /platform/status

Returns the current governance status (uses 30-second cache).

**Response:**
```json
{
  "timestamp": "2025-11-30T06:37:34+00:00",
  "service": "demo-swarm",
  "governance": {
    "kernel": {
      "ok": false,
      "last_run": "2025-11-30T06:37:33+00:00",
      "status": "BROKEN",
      "error": "Failed checks: fmt, clippy, tests"
    },
    "selftest": {
      "mode": "strict",
      "last_run": "2025-11-30T06:37:34+00:00",
      "status": "GREEN",
      "failed_steps": [],
      "degraded_steps": []
    },
    "state": "FULLY_GOVERNED"
  },
  "flows": {
    "total": 6,
    "healthy": 6,
    "degraded": 0,
    "broken": 0,
    "invalid_flows": []
  },
  "agents": {
    "total": 45,
    "by_status": {
      "healthy": 45,
      "misconfigured": 0,
      "unknown": 0
    },
    "invalid_agents": []
  },
  "hints": {
    "if_kernel_broken": "Run: make kernel-smoke --verbose",
    "if_selftest_broken": "Run: make selftest --plan && make selftest --step <id>",
    "how_to_heal": "See docs/SELFTEST_SYSTEM.md and CLAUDE.md § Key Patterns"
  }
}
```

### POST /platform/status/refresh

Force a recomputation of governance status (bypasses cache).

**Usage:**
```bash
curl -X POST http://localhost:5000/platform/status/refresh | jq .
```

## Governance States

The `governance.state` field can be one of four values:

- **FULLY_GOVERNED**: Kernel OK, selftest green, all flows and agents valid
- **DEGRADED**: Kernel OK, but selftest has governance-level failures
- **UNHEALTHY**: Kernel broken or major issues detected
- **UNKNOWN**: Unable to determine state (selftest hasn't run, etc.)

## Implementation Details

### StatusProvider

The `status_provider.py` module implements the core logic:

```python
from status_provider import StatusProvider
from pathlib import Path

provider = StatusProvider(repo_root=Path(...), cache_ttl_seconds=30)
status = provider.get_status(force_refresh=False)
print(status.to_json())
```

**Features:**
- Checks kernel health (cargo fmt, clippy, tests)
- Validates selftest governance status
- Verifies all 7 flows are loadable and valid
- Confirms all agents are registered and valid
- Returns rich status report with hints for remediation
- Supports caching with configurable TTL

### Kernel Checks

The kernel health check runs:
1. `cargo fmt --check` - Format validation
2. `cargo clippy --workspace --all-targets --all-features` - Lint check
3. `cargo test --workspace --tests` - Unit tests

If any fail, `kernel.status` is `BROKEN` and `kernel.ok` is `false`.

### Selftest Integration

If selftest has run and produced a JSON report, the status provider parses it to determine:
- Failed steps (tier: kernel/governance/optional)
- Degraded steps (governance failures in non-blocking mode)
- Overall selftest status: GREEN, YELLOW, RED, or UNKNOWN

### Flow Studio Smoke Coherence

The Flow Studio `flowstudio-smoke` selftest step and `/platform/status` both consume the same `SelfTestRunner.build_summary()` object. This ensures:

1. **Unified model**: Flow Studio's governance gate reads the same data as the status endpoint
2. **No divergence**: Both views reflect the same kernel/governance health state
3. **Fast path**: The smoke step runs in-process (~0.5–2s) without HTTP overhead

When `flowstudio-smoke` passes, `/platform/status` will report coherent governance. When it fails, the endpoint will reflect the same failures. See `swarm/SELFTEST_SYSTEM.md` § Flow Studio Governance Gate for details.

### Flow & Agent Validation

The status provider loads all YAML configs from:
- `swarm/config/flows/*.yaml` - 7 flows (signal, plan, build, review, gate, deploy, wisdom)
- `swarm/config/agents/*.yaml` - 43+ agents across all flows

Each is validated for:
- Valid YAML syntax
- Required fields (`key`, `category`, `color` for agents; `key`, `title` for flows)
- Non-empty values

## Caching

By default, status is cached for **5 minutes (300 seconds)** to avoid expensive recomputation. The cache is keyed by the timestamp of the last request. Use `FLOW_STUDIO_STATUS_TTL_SECONDS` env var to override (e.g., `30` for CI).

**To bypass cache:**
```bash
curl -X POST http://localhost:5000/platform/status/refresh | jq .
```

**To adjust cache TTL:**
```python
from status_provider import StatusProvider
provider = StatusProvider(cache_ttl_seconds=60)  # 60 second cache
```

**To disable caching:**
```python
provider = StatusProvider(cache_ttl_seconds=0)  # No cache
```

## Integration with Flow Studio

The endpoint is automatically available when Flow Studio starts. No additional configuration needed.

**Flask routes added:**
- `GET /platform/status` - Get cached status
- `POST /platform/status/refresh` - Force refresh
- `GET /api/health` - Existing health endpoint (still available)

## Hints & Remediation

The response includes actionable hints:

- **if_kernel_broken**: Command to run if kernel checks fail
- **if_selftest_broken**: Command to run if selftest governance fails
- **how_to_heal**: Documentation links for understanding and fixing issues

Example:
```json
"hints": {
  "if_kernel_broken": "Run: make kernel-smoke --verbose",
  "if_selftest_broken": "Run: make selftest --plan && make selftest --step <id>",
  "how_to_heal": "See docs/SELFTEST_SYSTEM.md and CLAUDE.md § Key Patterns"
}
```

## Error Handling

**If kernel-smoke fails:**
```json
{
  "error": "Failed checks: fmt, clippy, tests",
  "status": "BROKEN"
}
```

**If selftest is unavailable:**
```json
{
  "status": "UNKNOWN",
  "failed_steps": [],
  "degraded_steps": []
}
```

**If status provider cannot be initialized:**
```json
{
  "error": "Status provider not available",
  "service": "demo-swarm"
}
// HTTP 503
```

## Testing

Run the comprehensive acceptance test:
```python
# In swarm/tools/
python3 -c "
import sys
sys.path.insert(0, 'swarm/tools')
from flow_studio import create_app
app = create_app()
with app.test_client() as client:
    r = client.get('/platform/status')
    print(r.status_code)  # 200
    print(r.get_json()['service'])  # demo-swarm
"
```

## Makefile Target

```bash
make check-platform-status
```

This is a convenience wrapper around:
```bash
curl -s http://localhost:5000/platform/status | jq .
```

It requires Flow Studio to be running on localhost:5000.

## Monitoring & Observability

The status endpoint is suitable for:
- **Health checks**: Polling for `governance.state` to detect issues early
- **CI/CD integration**: Checking governance before deployment
- **Dashboards**: Real-time visualization of swarm health
- **Alerts**: Notifying on state transitions (FULLY_GOVERNED → DEGRADED, etc.)

Example monitoring script:
```bash
#!/bin/bash
while true; do
  state=$(curl -s http://localhost:5000/platform/status | jq '.governance.state')
  if [ "$state" = '"UNHEALTHY"' ]; then
    echo "ALERT: Governance state is UNHEALTHY"
    # Send notification, log, etc.
  fi
  sleep 300  # Poll every 5 minutes
done
```

## Troubleshooting

**Endpoint returns 503 (Service Unavailable):**
- Check that Flow Studio is running: `make flow-studio`
- Verify StatusProvider can be imported: `python3 -c "from status_provider import StatusProvider"`

**Selftest status is always UNKNOWN:**
- Selftest may not have run yet or is not available in your environment
- This is normal; kernel and flow checks still work

**Governance state is always UNHEALTHY:**
- Check kernel health: `make kernel-smoke --verbose`
- Review output for which checks are failing (fmt, clippy, tests)

**Large response times:**
- First request may take 30+ seconds if kernel-smoke hasn't run recently
- Subsequent requests are cached for 5 minutes (configurable via `FLOW_STUDIO_STATUS_TTL_SECONDS`)
- Use POST /platform/status/refresh to force a refresh

## Future Enhancements

Possible extensions to the status provider:

1. **Per-flow status**: Individual health for each of the 7 flows
2. **Per-agent status**: Agent availability and model assignment health
3. **Historical tracking**: Store status snapshots for trend analysis
4. **Metrics export**: Prometheus or OpenMetrics format for scraping
5. **Webhooks**: POST to external services on state changes
6. **Comparative analysis**: Diff governance state between runs

See `swarm/infrastructure/flow-6-extensions.md` for how to add observability extensions.
