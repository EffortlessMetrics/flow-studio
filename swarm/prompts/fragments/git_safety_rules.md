## Git Safety Rules

These rules apply when working with git operations:

### Prohibited Commands

Never use destructive git commands:
- No `git push --force` or `-f`
- No `git reset --hard`
- No `git clean -fd`
- No branch deletion without explicit permission
- No `git rebase` on shared branches

### Safe Patterns

Always use safe alternatives:
- Use `git push` without force flags
- Use `git stash` to preserve work
- Use `git reset --soft` when resetting
- Create backup branches before risky operations

### Commit Guidelines

- Write clear, descriptive commit messages
- Use conventional commit format: `<type>(<scope>): <description>`
- Never commit secrets, API keys, or credentials
- Stage files explicitly, avoid `git add .` when possible

### Branch Management

- Create feature branches for changes
- Keep main/master protected
- Delete branches only after merge is confirmed
- Use descriptive branch names: `feature/`, `fix/`, `chore/`
