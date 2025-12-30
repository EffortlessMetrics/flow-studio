# Branch Protection Rules

Defines which branches are protected and how to handle them safely.

## Never-Delete Branches

These branches must never be deleted locally or remotely:

- `main` - Primary production branch
- `master` - Legacy production branch (if exists)
- `develop` - Integration branch
- `release/*` - Release preparation branches
- `hotfix/*` - Critical fix branches (until merged)

## Protection Check

Before any branch operation, verify protection status:

```bash
# Check if branch matches protected pattern
is_protected() {
  local branch="$1"
  case "$branch" in
    main|master|develop|release/*|hotfix/*)
      return 0  # Protected
      ;;
    *)
      return 1  # Not protected
      ;;
  esac
}
```

## Current Branch Protection

```bash
# Never operate destructively on these
git branch -r | grep -E 'origin/(main|master|develop|release/|hotfix/)' | head -20
```

## Branch Operation Safety Matrix

| Operation | Protected Branch | Feature Branch |
|-----------|-----------------|----------------|
| Delete local | FORBIDDEN | Allowed after merge |
| Delete remote | FORBIDDEN | Allowed after merge |
| Force push | FORBIDDEN | Allowed with lease |
| Rebase | FORBIDDEN | Allowed before push |
| Reset --hard | FORBIDDEN | Allowed with backup |

## Merge Requirements

Protected branches require:

1. **PR review** - At least one approval
2. **CI passing** - All required checks green
3. **No force merge** - Linear history via rebase or squash only
4. **Branch up-to-date** - Must be current with target

## Feature Branch Naming

Safe-to-modify branches follow patterns:
- `feature/*` - New features
- `fix/*` - Bug fixes
- `chore/*` - Maintenance
- `docs/*` - Documentation
- `test/*` - Test additions
- `refactor/*` - Code restructuring

These can be rebased, force-pushed (with lease), and deleted after merge.
