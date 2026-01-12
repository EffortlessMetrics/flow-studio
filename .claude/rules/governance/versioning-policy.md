# Versioning Policy

**"If you can't read yesterday's receipts, yesterday's work is lost."**

This rule defines how to version flows, agents, schemas, and configs to ensure backward compatibility and graceful evolution.

## What Gets Versioned

| Artifact Type | What Changes | Impact |
|---------------|--------------|--------|
| **Schemas** | Receipt, handoff, envelope formats | Breaks artifact parsing |
| **Flows** | Step structure, agent assignments | Breaks flow execution |
| **Agents** | Behavioral changes in prompts | Changes work output |
| **Configs** | YAML structures, registry formats | Breaks tooling |

## Versioning Schemes

Different artifacts use different versioning schemes based on their nature.

### Schemas: Semantic Versioning (MAJOR.MINOR.PATCH)

```
receipt_schema: 1.2.0
handoff_schema: 2.0.1
envelope_schema: 1.1.0
```

| Component | When to Bump | Example |
|-----------|--------------|---------|
| MAJOR | Breaking changes | Remove required field |
| MINOR | New optional fields | Add `git_sha` to receipt |
| PATCH | Bug fixes, clarifications | Fix enum typo |

### Flows: Date-Based (YYYY-MM-DD)

```yaml
flow_version: 2024-01-15
flow_key: build
```

Date-based because:
- Flows evolve incrementally
- No strict "compatibility" between versions
- Date provides context for when behavior changed

### Agents: Git SHA

Agent prompts live in repo. Version is the commit SHA.

```yaml
agent_key: code-implementer
prompt_sha: a1b2c3d4
```

Why Git SHA:
- Prompts change frequently
- Exact version is traceable in history
- No manual version management

### Configs: Semantic Versioning

```yaml
config_version: 1.0.0
```

Registry formats, YAML structures, and tooling configs use semver.

## Compatibility Guarantees

### PATCH (x.x.N)
- Bug fixes only
- No behavioral changes
- Fully backward compatible
- No migration required

### MINOR (x.N.0)
- New optional fields
- New enum values (additive)
- Backward compatible
- Old artifacts readable without modification

### MAJOR (N.0.0)
- Breaking changes
- Migration required
- Support N-1 minimum
- Document migration path

## Breaking Changes (Require MAJOR Bump)

| Change Type | Example | Why Breaking |
|-------------|---------|--------------|
| Remove required field | Drop `step_id` from receipt | Old readers expect it |
| Change field type | `tokens: number` → `tokens: object` | Parsing fails |
| Rename field | `started_at` → `start_time` | Old readers miss it |
| Change step order | Swap steps 2 and 3 | Flow execution differs |
| Change agent contract | Critic now fixes code | Behavioral change |
| Remove enum value | Drop `BLOCKED` status | Validation fails |

## Non-Breaking Changes (MINOR or PATCH)

| Change Type | Version | Example |
|-------------|---------|---------|
| Add optional field | MINOR | Add `workspace_root` |
| Add new enum value | MINOR | Add `DETOUR` to routing |
| Add new agent | MINOR | Add `lint-fixer` agent |
| Add new flow | MINOR | Add Flow 8 (Reset) |
| Improve prompt wording | PATCH | Clarify critic instructions |
| Fix typo in schema | PATCH | Fix `comletion` → `completion` |
| Add validation | PATCH | Require positive token counts |

## Version in Artifacts

### Receipts

```json
{
  "schema_version": "1.2.0",
  "engine": "claude-step",
  "step_id": "build-step-3",
  ...
}
```

### Handoff Envelopes

```json
{
  "schema_version": "2.0.0",
  "meta": { ... },
  "status": "VERIFIED",
  ...
}
```

### Flow Definitions

```yaml
flow_version: 2024-01-15
flow_key: build
steps:
  - id: step-1
    ...
```

## Reading Old Artifacts

The system MUST support reading N-1 version minimum.

### Version Detection

```python
def detect_version(artifact):
    if 'schema_version' in artifact:
        return artifact['schema_version']
    # Legacy: no version field = 1.0.0
    return '1.0.0'
```

### Version-Aware Parsing

```python
def parse_receipt(data):
    version = detect_version(data)

    if version.startswith('1.'):
        return parse_v1_receipt(data)
    elif version.startswith('2.'):
        return parse_v2_receipt(data)
    else:
        raise UnsupportedVersion(version)
```

## Migration Support

### MAJOR Version Migrations

When bumping MAJOR version:

1. **Document breaking changes** in changelog
2. **Provide migration script** for artifacts
3. **Support N-1 for reading** (at minimum)
4. **Deprecate N-2** with warning
5. **Remove N-3** support

### Migration Script Location

```
swarm/migrations/
├── receipt_v1_to_v2.py
├── handoff_v1_to_v2.py
└── README.md
```

### Migration Example

```python
def migrate_receipt_v1_to_v2(v1_receipt):
    """Migrate receipt from v1.x to v2.x format."""
    return {
        'schema_version': '2.0.0',
        'step_id': v1_receipt['step_id'],
        'tokens': {
            'prompt': v1_receipt.get('prompt_tokens', 0),
            'completion': v1_receipt.get('completion_tokens', 0),
            'total': v1_receipt.get('total_tokens', 0),
        },
        ...
    }
```

## Deprecation Policy

| Phase | Duration | Behavior |
|-------|----------|----------|
| Current | N/A | Full support |
| Deprecated | 2 releases | Warning on read, still functional |
| Removed | After deprecated | Error on read |

### Deprecation Warning

```python
if version < MIN_SUPPORTED_VERSION:
    warn(f"Receipt version {version} is deprecated. Migrate to {CURRENT_VERSION}.")
```

## The Rule

> Version everything that can break readers.
> Support N-1 minimum.
> Migration is mandatory for MAJOR bumps.

## Enforcement

### Validation

`validate_swarm.py` checks:
1. Schema versions are valid semver
2. Flow versions are valid dates
3. Referenced versions exist
4. No unsupported versions in active runs

### CI Checks

- Block MAJOR bumps without migration script
- Warn on deprecated version usage
- Track version distribution in runs

## Version Registry

Current versions are tracked in:

```yaml
# swarm/config/versions.yaml
schemas:
  receipt: 1.2.0
  handoff: 2.0.0
  envelope: 1.1.0
flows:
  signal: 2024-01-15
  plan: 2024-01-15
  build: 2024-01-15
  review: 2024-01-10
  gate: 2024-01-10
  deploy: 2024-01-08
  wisdom: 2024-01-08
config:
  agents: 1.0.0
  flows: 1.0.0
  profiles: 1.0.0
```

## Anti-Patterns

### Silent Breaking Changes
```
# BAD: Changed field type without version bump
tokens: 500  # Was number, now sometimes string
```

### Version Inflation
```
# BAD: MAJOR bump for adding optional field
schema_version: 5.0.0  # Was 4.0.0, only added optional field
```

### No Migration Path
```
# BAD: Breaking change with no migration script
ERROR: Cannot read receipt v1.0.0 (unsupported)
```

### Forgetting Legacy Artifacts
```
# BAD: Old runs become unreadable
swarm/runs/2024-01-01/  # Cannot parse receipts
```

---

## See Also
- [receipt-schema.md](../artifacts/receipt-schema.md) - Current receipt format
- [handoff-protocol.md](../artifacts/handoff-protocol.md) - Envelope structure
- [capability-registry.md](../artifacts/capability-registry.md) - Capability versioning
