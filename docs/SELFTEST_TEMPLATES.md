# Selftest Templates: Choosing Your Entry Point

**For: Teams evaluating adoption options**

This document compares the three entry points for adopting Flow Studio
tooling. Each template trades setup complexity for capability scope.

---

## Template Comparison

| Template | Setup Time | What You Get | Best For |
|----------|-----------|--------------|----------|
| selftest-minimal | 15-30 min | 3-tier CI validation, GitHub Action | Teams wanting CI gates without full swarm |
| flowstudio-only | 1 hour | Flow visualization UI, no SDLC | Teams wanting to visualize existing workflows |
| Full Flow Studio | 2-3 hours | Complete 7-flow SDLC, 53 agents | Teams adopting full agentic SDLC |

---

## Decision Tree

### Use selftest-minimal if...

- You want CI validation without committing to the full swarm
- Your team already has an SDLC but needs better governance checks
- You want to start with KERNEL/GOVERNANCE/OPTIONAL tiers and grow later
- You need a GitHub Action that blocks PRs on validation failures
- You want the smallest possible footprint to evaluate the approach

### Use flowstudio-only if...

- You want to visualize your existing workflows as node graphs
- You have custom flows you want to map before adopting agents
- Your team is evaluating whether flow-based thinking fits your process
- You want a local web UI without any CI or agent infrastructure
- You plan to add agents later but want to start with visualization

### Fork flow-studio if...

- You are ready to adopt a full agentic SDLC
- You want all 7 flows: Signal, Plan, Build, Review, Gate, Deploy, Wisdom
- You need 53 agents across shaping, spec, implementation, critic, and verification roles
- You want receipts, microloops, and adversarial review built in
- Your team has 2-3 hours for initial setup and is committed to the approach

---

## Quick Start

### selftest-minimal

Bootstrap script creates a standalone selftest infrastructure:

```bash
uv run swarm/tools/bootstrap_selftest_minimal.py --target /path/to/your-repo
```

This copies:
- `selftest.py` (3-tier validation)
- GitHub Action workflow
- Minimal configuration

See: [`swarm/tools/bootstrap_selftest_minimal.py`](../swarm/tools/bootstrap_selftest_minimal.py)

### flowstudio-only

Self-contained template with Flow Studio visualization:

```bash
cp -r templates/flowstudio-only /path/to/your-repo/flowstudio
cd /path/to/your-repo/flowstudio
make flow-studio
# Open http://localhost:5000
```

See: [`templates/flowstudio-only/README.md`](../templates/flowstudio-only/README.md)

### Full Flow Studio

Fork the repository and follow the adoption playbook:

```bash
# Fork on GitHub, then:
git clone https://github.com/YOUR-ORG/flow-studio
cd flow-studio
make dev-check
make demo-run
```

See: [`docs/ADOPTION_PLAYBOOK.md`](./ADOPTION_PLAYBOOK.md)

---

## Detailed Documentation

- **selftest-minimal**: [`docs/ADOPTING_SELFTEST_CORE.md`](./ADOPTING_SELFTEST_CORE.md)
- **Full adoption**: [`docs/ADOPTION_PLAYBOOK.md`](./ADOPTION_PLAYBOOK.md)
- **Selftest system internals**: [`swarm/SELFTEST_SYSTEM.md`](../swarm/SELFTEST_SYSTEM.md)

---

## Upgrade Paths

Templates are designed for incremental adoption:

```
selftest-minimal --> Full swarm
        |
        v
flowstudio-only --> Full swarm
```

**selftest-minimal to full swarm**: Add agent configs, flow specs, and
commands incrementally. The selftest infrastructure remains compatible.

**flowstudio-only to full swarm**: Your flow definitions become the
foundation. Add agents to implement each flow step.

Both paths preserve your existing work while adding capability.
