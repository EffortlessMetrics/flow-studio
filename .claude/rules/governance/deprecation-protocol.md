# Deprecation Protocol

How to sunset agents, flows, and capabilities without breaking dependents.

## The Principle

**Nothing with external dependents disappears without warning. Internal cleanup is encouraged.**

Deprecation is a contract with users: you will have time to migrate before things break.

## Deprecation Stages

### Stage 1: Marked

The item is flagged for deprecation but remains fully functional.

**Actions:**
- Add `@deprecated` tag to definition
- Add deprecation notice to documentation
- Log warnings on every use
- Document why it's being deprecated

**Marker format:**
```yaml
# In agent/flow/schema definition
deprecated:
  since: "v2.5.0"
  reason: "Superseded by new-agent with better coverage"
  alternative: "new-agent"
  removal_target: "v3.0.0"
```

**Log format:**
```
[DEPRECATION WARNING] Agent 'old-agent' is deprecated since v2.5.0.
  Use 'new-agent' instead. Removal planned for v3.0.0.
  See: docs/migration/old-agent-to-new-agent.md
```

### Stage 2: Migration

Alternative is documented and migration path is clear.

**Requirements:**
- Migration guide exists
- Alternative is production-ready
- Automated migration tooling (where feasible)
- Warnings escalate to prominent notices

**Migration guide must include:**
1. What's changing and why
2. Step-by-step migration instructions
3. Mapping of old → new (fields, parameters, behavior)
4. Known edge cases and how to handle them
5. Rollback instructions if migration fails

### Stage 3: Disabled

Using the deprecated item produces errors, but code remains.

**Actions:**
- Use triggers error with migration pointer
- Code remains in place (rollback possible)
- Metrics track attempted usage
- Support window for stragglers

**Error format:**
```
[DEPRECATION ERROR] Agent 'old-agent' is disabled as of v3.0.0.
  This agent no longer functions. Migrate to 'new-agent'.
  See: docs/migration/old-agent-to-new-agent.md
  If you cannot migrate, contact support before v3.1.0.
```

### Stage 4: Removed

Code is deleted from the codebase.

**Actions:**
- Delete implementation
- Delete tests (archive if historically interesting)
- Update documentation to remove references
- Add to CHANGELOG as breaking change

## Timeline Requirements

| Transition | Minimum Duration | Rationale |
|------------|------------------|-----------|
| Marked → Migration | Immediate | Documentation is a prerequisite |
| Migration → Disabled | 2 releases | Users need time to migrate |
| Disabled → Removed | 1 release | Final warning period |

**Example timeline:**
```
v2.5.0: Marked (warnings start)
v2.5.0: Migration (guide published same release)
v2.7.0: Disabled (errors, 2 releases later)
v2.8.0: Removed (code deleted, 1 release later)
```

## What Requires Deprecation Process

### Agents

Agents may have:
- External tooling that invokes them
- Flow configurations that reference them
- Scripts that depend on their output format

**Deprecation required:** Always

### Flows

Flows may have:
- CI/CD integrations
- Monitoring dashboards
- External orchestration dependencies

**Deprecation required:** Always

### Artifact Schemas

Schemas may have:
- Stored data in existing format
- Downstream consumers parsing output
- Integration contracts with external systems

**Deprecation required:** Always
**Additional requirement:** Schema migration tooling for stored data

### Public APIs/Contracts

APIs may have:
- External consumers
- Integration partners
- Documented contracts

**Deprecation required:** Always
**Additional requirement:** Versioned API support during migration

## What Can Be Removed Directly

### Internal Implementation Details

Code that:
- Is not exposed in any public interface
- Has no external references
- Is purely internal optimization

**Deprecation required:** No
**Best practice:** Comment in PR why no deprecation needed

### Unused Code with No References

Code that:
- Is never invoked
- Has no configuration references
- Is not documented as a feature

**Deprecation required:** No
**Best practice:** Verify with grep/search before removal

### Failed Experiments

Code that:
- Was never shipped to users
- Exists only in development branches
- Has no external documentation

**Deprecation required:** No
**Best practice:** Document the experiment's learnings before deletion

## Migration Requirements

### Documentation

Every deprecated item must have:
```
docs/migration/<old-item>-to-<new-item>.md
```

Contents:
1. **Summary**: One paragraph on what's changing
2. **Timeline**: When each stage happens
3. **Migration steps**: Numbered, actionable instructions
4. **Mapping table**: Old → New for all fields/parameters
5. **Edge cases**: Known issues and workarounds
6. **Rollback**: How to undo if needed
7. **Support**: Where to get help

### Automated Migration

Where feasible, provide tooling:

```bash
# Example: Agent migration
make migrate-agent FROM=old-agent TO=new-agent

# Example: Schema migration
make migrate-schema FROM=v1 TO=v2 DATA_PATH=swarm/runs/
```

Tooling should:
- Be idempotent (safe to run multiple times)
- Produce detailed logs
- Have dry-run mode
- Handle partial failures gracefully

### Warning Integration

Warnings must appear in:
- CLI output (if applicable)
- Log files
- Validation output (`make validate-swarm`)
- Documentation (deprecation badges)

## Validation

Pack-check validates deprecation compliance:

```python
def validate_deprecation(item):
    if item.deprecated:
        assert item.deprecated.since, "Deprecation must have 'since' version"
        assert item.deprecated.alternative, "Deprecation must have alternative"
        assert item.deprecated.removal_target, "Deprecation must have removal target"
        assert migration_guide_exists(item), "Migration guide required"
```

## The Rule

> External dependents get warning. Internal cleanup is encouraged.
> Two releases minimum from migration to disabled.
> One release minimum from disabled to removed.
> Every deprecation has a migration guide.

## Anti-Patterns

### Silent Removal
```
# BAD: Just delete it
git rm swarm/agents/old-agent.md
git commit -m "Remove old agent"
```

**Problem:** External users break without warning.

### Deprecation Without Alternative
```yaml
# BAD: No path forward
deprecated:
  since: "v2.5.0"
  reason: "No longer needed"
  # Missing: alternative
```

**Problem:** Users don't know what to do instead.

### Rushed Timeline
```
v2.5.0: Marked
v2.5.1: Removed  # BAD: No migration window
```

**Problem:** Users have no time to adapt.

### Warning Without Action
```
# BAD: Warn forever, never remove
deprecated:
  since: "v1.0.0"  # Three years ago
  removal_target: null
```

**Problem:** Deprecation warnings become noise.

## Tracking Deprecations

Maintain a deprecation registry:

```yaml
# specs/deprecations.yaml
deprecations:
  - item: old-agent
    type: agent
    since: v2.5.0
    stage: migration
    alternative: new-agent
    removal_target: v3.0.0
    migration_guide: docs/migration/old-agent-to-new-agent.md

  - item: v1-receipt-schema
    type: schema
    since: v2.4.0
    stage: disabled
    alternative: v2-receipt-schema
    removal_target: v2.8.0
    migration_guide: docs/migration/receipt-schema-v1-to-v2.md
```

This enables:
- Automated deprecation status checks
- Release note generation
- Migration progress tracking

---

## See Also
- [capability-registry.md](../artifacts/capability-registry.md) - Evidence for capabilities
- [pack-check-philosophy.md](./pack-check-philosophy.md) - Validation philosophy
- [agent-behavioral-contracts.md](./agent-behavioral-contracts.md) - Agent definitions
