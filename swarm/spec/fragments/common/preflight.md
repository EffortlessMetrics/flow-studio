## Preflight Checks

Before starting your main work, verify these conditions. This prevents wasted effort on invalid inputs.

### Required Input Validation

1. **Check required inputs exist**:
   - Read each file listed in `io.required_inputs`
   - If any required input is missing, set `status: BLOCKED` with explicit list of missing files
   - Do not proceed with main work if required inputs are absent

2. **Verify input format**:
   - Required inputs should be parseable (YAML/JSON where expected)
   - If format is corrupted, set `status: BLOCKED` with parsing error details

### Context Validation

3. **Verify upstream artifacts**:
   - If this step depends on upstream outputs, check they exist
   - Missing upstream artifacts suggest the flow was invoked out of order

4. **Check RUN_BASE structure**:
   - Verify `{{run.base}}` directory exists
   - Verify you can write to your output directory

### State Validation

5. **Check for previous work**:
   - If this is a re-run, previous artifacts may exist
   - Read previous handoffs to understand prior state
   - Update and refine existing work rather than starting from scratch

### Preflight Outcomes

| Outcome | Action |
|---------|--------|
| All inputs present and valid | Proceed with main work |
| Required input missing | Set BLOCKED, list missing files, stop |
| Input format corrupted | Set BLOCKED, describe error, stop |
| Previous work exists | Read it, build upon it |

### Example Preflight Check

```
## Preflight

### Required Inputs
- [x] plan/adr.md (exists, 2.3KB)
- [x] plan/api_contracts.yaml (exists, 1.1KB)
- [ ] build/test_changes_summary.md (MISSING - optional, continuing)

### State
- Previous handoff found: build/handoff/implement.draft.json
- Previous status: UNVERIFIED
- Will build upon previous work

### Verdict
Preflight PASSED. Proceeding with implementation.
```

### When to Skip Preflight

Preflight is implicit - you do it automatically as you start reading inputs. You don't need to write a formal preflight section unless:
- You're hitting BLOCKED status
- You want to document why you're proceeding despite missing optional inputs
- The step has complex upstream dependencies
