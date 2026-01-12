# Capability Registry

The capability registry is the single source of truth for what this system can do.

## Purpose

The registry prevents "narrative drift" where documentation claims capabilities
that aren't backed by code or tests. It enforces **evidence discipline** at the
capability level.

## File Location

```
specs/capabilities.yaml     # Canonical registry (machine-validated)
docs/reference/CAPABILITIES.md  # Generated view (DO NOT EDIT)
```

## Status Meanings

| Status | Meaning | Evidence Required |
|--------|---------|-------------------|
| **implemented** | Has code + test evidence; safe to claim | code + tests |
| **supported** | Has code but incomplete tests; use with caveats | code only |
| **aspirational** | Design exists; NOT shipped | none |

## Schema

```yaml
version: 1

surfaces:
  receipts:
    description: "Step execution audit trail"
    capabilities:
      - id: receipts.required_fields
        status: implemented
        summary: "Receipts include engine, mode, step_id, flow_key..."
        evidence:
          code:
            - path: swarm/runtime/receipt_io.py
              symbol: StepReceiptData
          tests:
            - kind: unit
              ref: tests/test_receipt_io.py
        notes: null  # Optional caveats for 'supported' status
```

## Evidence Types

### Code Evidence
Points to implementation:
```yaml
code:
  - path: swarm/runtime/receipt_io.py
    symbol: StepReceiptData  # Optional: class/function name
```

### Test Evidence
Points to verification:
```yaml
tests:
  - kind: unit        # unit | integration | bdd
    ref: tests/test_receipt_io.py::test_required_fields
```

### Design Evidence (aspirational only)
Points to design documents:
```yaml
design:
  - path: docs/QUALITY_EVENTS.md
```

## BDD Integration

BDD scenarios can reference capabilities with `@cap:<id>` tags:

```gherkin
@AC-SELFTEST-KERNEL-FAST @cap:selftest.kernel_smoke @executable
Scenario: Kernel smoke check is fast and reliable
  ...
```

The validator (FR-007) ensures all `@cap:` tags reference valid capabilities.

## Validation Rules (FR-007)

The `validate_capability_registry()` function enforces:

1. **implemented** capabilities MUST have ≥1 test pointer
2. **implemented** capabilities MUST have ≥1 code pointer
3. `@cap:<id>` tags in BDD MUST reference capabilities in registry
4. **aspirational** capabilities MUST NOT be claimed as shipped

## Generated Documentation

The generated doc (`docs/reference/CAPABILITIES.md`) is:
- Regenerated with `make gen-capabilities-doc`
- Checked in CI with `make check-capabilities-doc`
- Marked with "DO NOT EDIT" banner

## The Rule

> Claims require evidence. "Not measured" is valid. False certainty is not.

Every capability claim passes through the registry. If it's not in
`specs/capabilities.yaml` with proper evidence, it's not a capability we claim.

## Adding New Capabilities

1. Add entry to `specs/capabilities.yaml` with appropriate status
2. For `implemented`: add both code and test evidence
3. For `supported`: add code evidence, note why tests are incomplete
4. For `aspirational`: add design evidence, do NOT claim as shipped
5. Run `make gen-capabilities-doc` to update generated doc
6. Run `make validate-swarm` to verify

## Anti-Patterns

### Don't claim aspirational as implemented
```yaml
# BAD: No test evidence but claims implemented
- id: quality.mutation_testing
  status: implemented  # Wrong!
  evidence:
    design:
      - path: docs/QUALITY_EVENTS.md
```

### Don't skip evidence pointers
```yaml
# BAD: Implemented but no evidence
- id: routing.microloop_exit
  status: implemented
  # Missing evidence section!
```

### Don't use vague references
```yaml
# BAD: Vague reference
tests:
  - kind: unit
    ref: tests/  # Too vague - which test file?
```
