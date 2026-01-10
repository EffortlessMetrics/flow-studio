# Epic: Spec System - JSON-First Runtime Transition

## Vision
The system should run entirely from **JSON specifications**, making prompts reproducible, versionable, and UI-editable.

## Current State (Legacy)

- swarm/prompts/agentic_steps/*.md (24k lines of Markdown)
- build_prompt() manually assembles prompts
- swarm/spec/compiler.py exists but FEATURE_FLAGGED_OFF

## Target State (Spec-First)

- swarm/specs/stations/*.json as runtime truth
- swarm/specs/flows/*.json for flow definitions
- SpecCompiler generates prompts at runtime
- Markdown prompts DEPRECATED

## Implementation Tasks

### Task 1: Create JSON Station Specs
Convert 50+ YAML station specs to JSON with schema validation.

### Task 2: Enable SpecCompiler (#8)
Change default: USE_SPEC_COMPILER = true
Add prompt hashing for reproducibility.

### Task 3: CI Validation (#17)
Add make validate-specs-compile target.
Validate all specs compile to valid prompts.

### Task 4: Fragment System
Organize reusable prompt fragments with template resolution.

### Task 5: Deprecate Markdown Prompts
Add deprecation warnings, archive old prompts.

### Task 6: Wisdom Automation (#15)
Auto-extract learnings and write scent trail.

## Migration Checklist

- Week 1: Preparation (create JSON specs)
- Week 2: Parallel Running (CI only)
- Week 3: Default Switch
- Week 4: Deprecation

## Acceptance Criteria

- [ ] All 50+ stations have JSON specs
- [ ] SpecCompiler is default
- [ ] CI validates spec compilation
- [ ] Prompt hashes are deterministic
- [ ] Wisdom auto-populates scent trail

## Related Issues
- #8 Enable SpecCompiler
- #15 Automate Wisdom Extraction
- #17 Add Spec Compilation Validation to CI
