# Conflict Resolution Ladder

Three-level escalation for merge conflicts. Start at Level 1, escalate only when necessary.

## Level 1: Mechanical Resolution

**Criteria**: Conflicts are purely syntactic with no semantic ambiguity.

**Auto-resolvable conflicts**:
- Whitespace differences (spaces, tabs, line endings)
- Import ordering (alphabetical, grouped)
- Trailing commas or semicolons
- Comment formatting
- Empty line differences
- Lock file conflicts (regenerate)

**Resolution approach**:
```bash
# For import sorting conflicts
# Accept both, then run import sorter
git checkout --ours <file>
# Then apply their imports manually or via tooling

# For lock files
git checkout --theirs package-lock.json  # or yarn.lock
npm install  # regenerate
```

**Confidence threshold**: Can resolve automatically with >95% confidence.

---

## Level 2: Semantic Resolution

**Criteria**: Conflicts require understanding code intent but have clear resolution.

**Resolvable with analysis**:
- Both sides add different items to same list/enum
- Both sides modify different parts of same function
- Renamed variable used in both branches
- Feature flag additions from both branches
- Test additions to same test file
- Configuration additions that don't conflict semantically

**Resolution approach**:
1. Read both versions completely
2. Understand the intent of each change
3. Merge intents, not just text
4. Verify merged result makes semantic sense
5. Run tests to validate

**Example - both sides add enum values**:
```diff
<<<<<<< HEAD
    STATUS_PENDING = "pending"
    STATUS_APPROVED = "approved"  # Our addition
=======
    STATUS_PENDING = "pending"
    STATUS_REJECTED = "rejected"  # Their addition
>>>>>>> feature/rejection
```

**Resolution**: Include both enum values, verify no duplicate values.

**Confidence threshold**: Can resolve with >80% confidence after analysis.

---

## Level 3: Human Escalation

**Criteria**: Conflicts require domain knowledge or involve risk beyond agent authority.

**Must escalate**:
- Both sides modify same logic differently (different business rules)
- Security-sensitive code conflicts
- Database migration conflicts
- API contract changes
- Configuration that affects production behavior
- Conflicts in files marked as human-owned
- When Level 2 confidence is below 80%

**Escalation format**:
```yaml
escalation:
  type: CONFLICT_RESOLUTION
  severity: HIGH | MEDIUM
  file: "path/to/conflicted/file"

  our_changes:
    summary: "What our branch changed"
    intent: "Why we made this change"

  their_changes:
    summary: "What their branch changed"
    intent: "Why they made this change (if known)"

  conflict_nature: "Why these changes conflict semantically"

  options:
    - option: "Accept ours"
      impact: "What would be lost/changed"
    - option: "Accept theirs"
      impact: "What would be lost/changed"
    - option: "Manual merge suggestion"
      suggestion: "Proposed resolution if any"
      confidence: 0.0-1.0

  recommendation: "Which option seems best and why"
  risk_if_wrong: "What could go wrong with bad resolution"
```

---

## Resolution Workflow

```
1. Identify conflict type
   |
   v
2. Is it purely mechanical?
   |-- YES --> Level 1: Auto-resolve
   |-- NO  --> Continue
   |
   v
3. Can semantic intent be determined with >80% confidence?
   |-- YES --> Level 2: Resolve with documentation
   |-- NO  --> Continue
   |
   v
4. Level 3: Escalate to human
```

## Documentation Requirements

All resolutions must document:

- **Level resolved at**: 1, 2, or 3
- **Confidence**: Percentage confidence in resolution
- **Strategy used**: How conflict was resolved
- **Verification**: What tests/checks were run
- **Risks**: Any remaining concerns
