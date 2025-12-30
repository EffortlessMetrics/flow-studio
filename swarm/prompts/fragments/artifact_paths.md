## Artifact Path Conventions

All artifacts must use consistent path conventions:

### RUN_BASE Structure

```
RUN_BASE = swarm/runs/<run-id>/
```

Each flow writes to its designated subdirectory:
- `RUN_BASE/signal/` - Problem statement, requirements, BDD
- `RUN_BASE/plan/` - ADR, contracts, test plans
- `RUN_BASE/build/` - Implementation artifacts, receipts
- `RUN_BASE/review/` - PR feedback, review notes
- `RUN_BASE/gate/` - Audit reports, merge decisions
- `RUN_BASE/deploy/` - Deployment logs, verification
- `RUN_BASE/wisdom/` - Learnings, feedback actions

### Path Rules

1. Always use forward slashes (/) even on Windows
2. All paths relative to repo root or RUN_BASE
3. Never use absolute system paths
4. Never write outside designated locations
5. Use kebab-case for file and directory names
