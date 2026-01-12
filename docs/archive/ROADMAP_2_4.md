# v2.4 Roadmap

> **Archived:** This v2.4 roadmap is superseded by [ROADMAP_3_0.md](../ROADMAP_3_0.md). Kept for historical reference.

> **Status:** Draft — Shaping ideas for the next iteration.
> **Baseline:** v2.3.2 (Stepwise SDLC harness, context budgets, Flow Studio, 16-step selftest)

This roadmap captures potential directions for v2.4. Items are categorized by focus area and represent candidates, not commitments.

---

## Structure

Improvements to how the swarm is organized, configured, and extended.

- [ ] **Profile switcher in Flow Studio** — Expose per-profile context budgets and flow configurations in the UI sidebar
- [ ] **Config drift detection** — View comparing `runtime.yaml` vs `runtime_config.py` vs active profile; flag budget anomalies
- [ ] **Flow definition UI** — Visual editor for `flows/*.yaml` step definitions (read-only first, then editable)
- [ ] **Agent taxonomy browser** — Searchable, filterable view of all 48 agents with model/tier/flow assignments

---

## Velocity

Features that help users get value faster.

- [ ] **One-command "demo a real repo"** — `make demo-repo REPO=/path/to/repo` spins up Flow Studio with a fresh run
- [ ] **Scaffold for adopters** — `scripts/bootstrap-sdlc-harness.sh` generates minimal swarm config for new repos
- [ ] **Quick context load** — Pre-built context snapshots for common scenarios (greenfield, monorepo, legacy codebase)
- [ ] **CI template generator** — Generate GitHub Actions workflows from swarm config

---

## Governance

Mechanisms for maintaining quality as the swarm evolves.

- [ ] **Context-budget regression dashboard** — Tool that reports: % of steps truncated, avg `chars_used/budget`, priority distribution
- [ ] **Truncation metric in test-performance** — Gate on "no worse than X% truncated" for the baseline run
- [ ] **Gating surface documentation** — Explicit table in DoD: what test-swarm covers, what test-performance enforces, what selftest validates
- [ ] **Run artifact retention policy** — Automated cleanup of old runs based on age/count, preserving exemplars
- [ ] **Audit trail for profile changes** — Track who changed what profile when (git-based provenance)

---

## Observability

Better visibility into what the swarm is doing.

- [ ] **Step timing breakdown** — Show per-step duration in Flow Studio run detail modal
- [ ] **LLM token usage tracking** — Aggregate input/output token counts per flow, per run
- [ ] **Truncation visualization** — In Flow Studio, show which history items were included vs omitted (C/H/M/L)
- [ ] **Run comparison enhancements** — Side-by-side diff of artifacts between two runs

---

## Documentation

Improvements to onboarding and reference material.

- [ ] **Decision tree for first command** — Interactive or textual guide: "Which make target should I run first?"
- [ ] **Video walkthrough** — 10-minute screencast of the 20-minute tour
- [ ] **Adopter case studies** — Documented examples of teams integrating the swarm
- [ ] **FAQ / Troubleshooting expansion** — Common issues and resolutions

---

## Out of Scope for v2.4

These are explicitly deferred:

- Multi-tenant / hosted mode
- Real-time collaboration features
- Non-Claude/Gemini backend integrations
- Breaking changes to the flow spec format

---

## How to Contribute Ideas

1. Open an issue with the `[v2.4-candidate]` label
2. Describe the problem it solves and who benefits
3. Link to any related issues or prior art

Items will be refined and prioritized based on community interest and alignment with the swarm's core trade: **spend compute to save senior engineer attention**.
