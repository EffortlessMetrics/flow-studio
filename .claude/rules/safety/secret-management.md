# Secret Management: Full Lifecycle

**"Secrets are toxic waste. Handle accordingly."**

This rule covers the complete secret lifecycle: categorization, storage, rotation, detection, and incident response.

## Secret Categories

### API Keys
Provider-specific keys for external services.

| Provider | Pattern | Example Format |
|----------|---------|----------------|
| OpenAI | `sk-[A-Za-z0-9]{48}` | `sk-abc123...` |
| Anthropic | `sk-ant-[A-Za-z0-9-]{95}` | `sk-ant-api03-...` |
| GitHub (PAT) | `ghp_[A-Za-z0-9]{36}` | `ghp_abc123...` |
| GitHub (OAuth) | `gho_[A-Za-z0-9]{36}` | `gho_abc123...` |
| GitHub (App) | `ghs_[A-Za-z0-9]{36}` | `ghs_abc123...` |
| AWS Access Key | `AKIA[A-Z0-9]{16}` | `AKIAIOSFODNN7EXAMPLE` |
| AWS Secret Key | `[A-Za-z0-9/+=]{40}` | (40-char base64) |
| Slack | `xox[baprs]-[A-Za-z0-9-]+` | `xoxb-123-456-abc` |
| Stripe | `sk_live_[A-Za-z0-9]{24,}` | `sk_live_abc123...` |

### Credentials
Authentication for databases, services, and infrastructure.

| Type | Risk | Notes |
|------|------|-------|
| Database passwords | HIGH | Direct data access |
| Service account keys | HIGH | Often over-privileged |
| SSH private keys | CRITICAL | Infrastructure access |
| Cloud service credentials | HIGH | Resource control |

### Tokens
Short-lived or session-based authentication.

| Type | Lifetime | Notes |
|------|----------|-------|
| OAuth access tokens | Minutes-hours | Should auto-refresh |
| JWT signing keys | Long-lived | Rotation critical |
| Session tokens | Hours-days | Scope-limited |
| Refresh tokens | Days-weeks | Protect like credentials |

### Certificates
Cryptographic material for identity and encryption.

| Type | Risk | Rotation |
|------|------|----------|
| TLS private keys | HIGH | Annual or on compromise |
| Code signing certs | CRITICAL | Per security policy |
| CA certificates | CRITICAL | Rare, managed carefully |
| Client certs | MEDIUM | Per access policy |

---

## Storage Rules

### The Hierarchy

```
┌─────────────────────────────────────────────────────────┐
│  NEVER: Code, config files, logs, receipts, commits    │
├─────────────────────────────────────────────────────────┤
│  LOCAL DEV: .env files (gitignored)                    │
├─────────────────────────────────────────────────────────┤
│  RUNTIME: Environment variables                        │
├─────────────────────────────────────────────────────────┤
│  PRODUCTION: Vault / Secret Manager                    │
└─────────────────────────────────────────────────────────┘
```

### Environment Variables (Runtime)

Secrets are passed via environment variables at runtime:

```bash
# Good: Set in shell, not in files
export ANTHROPIC_API_KEY="sk-ant-..."
export OPENAI_API_KEY="sk-..."
export GITHUB_TOKEN="ghp_..."

# Good: Read from environment in code
api_key = os.environ.get("ANTHROPIC_API_KEY")
if not api_key:
    raise EnvironmentError("ANTHROPIC_API_KEY not set")
```

### .env Files (Local Dev Only)

For local development, use `.env` files that are gitignored:

```bash
# .env (MUST be in .gitignore)
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
GITHUB_TOKEN=ghp_...
DATABASE_URL=postgresql://user:pass@localhost/db
```

**Required .gitignore entries:**
```gitignore
.env
.env.local
.env.*.local
*.env
.secrets
secrets/
```

### Vault / Secret Manager (Production)

Production environments use dedicated secret management:

| Service | Use Case |
|---------|----------|
| HashiCorp Vault | Self-hosted, enterprise |
| AWS Secrets Manager | AWS-native workloads |
| GCP Secret Manager | GCP-native workloads |
| Azure Key Vault | Azure-native workloads |
| 1Password (CLI) | Small teams, local dev |

### NEVER Store Secrets In

| Location | Why |
|----------|-----|
| Source code | Committed to history forever |
| Config files (checked in) | Same as code |
| Logs | Often aggregated, retained, searchable |
| Receipts | Audit trail should not contain secrets |
| Error messages | May be displayed or logged |
| Comments | Still in code |
| Documentation | May be public |
| Slack/email | Retained, searchable, forwarded |

---

## Rotation Policy

### Immediate Rotation (Suspected Exposure)

Rotate immediately if:
- Secret appears in logs, commits, or error output
- Secret was sent via insecure channel
- Personnel with access departs
- Security incident detected
- Secret found in public location

### Scheduled Rotation

| Secret Type | Rotation Period | Notes |
|-------------|-----------------|-------|
| API keys | 90 days or on exposure | Automate if provider supports |
| Database passwords | 90 days | Coordinate with deployment |
| Service accounts | 90-180 days | Audit usage before rotation |
| JWT signing keys | Annual | Requires token invalidation planning |
| TLS certificates | Before expiry (30-day buffer) | Automate with ACME/cert-manager |

### Token Lifecycle

Short-lived tokens should auto-refresh:

```python
# Good: Use refresh tokens, short-lived access tokens
class TokenManager:
    def __init__(self):
        self.access_token = None
        self.refresh_token = os.environ.get("REFRESH_TOKEN")
        self.expires_at = 0

    def get_token(self):
        if time.time() >= self.expires_at - 60:  # 60s buffer
            self._refresh()
        return self.access_token

    def _refresh(self):
        # Exchange refresh token for new access token
        response = self._call_token_endpoint()
        self.access_token = response["access_token"]
        self.expires_at = time.time() + response["expires_in"]
```

---

## Detection Patterns

### Pre-Commit Hook Patterns

Scan for secrets before they enter git history:

```python
SECRET_PATTERNS = [
    # API Keys
    (r'sk-[A-Za-z0-9]{48}', 'OpenAI API key'),
    (r'sk-ant-[A-Za-z0-9-]{95}', 'Anthropic API key'),
    (r'ghp_[A-Za-z0-9]{36}', 'GitHub personal access token'),
    (r'gho_[A-Za-z0-9]{36}', 'GitHub OAuth token'),
    (r'ghs_[A-Za-z0-9]{36}', 'GitHub App token'),
    (r'AKIA[A-Z0-9]{16}', 'AWS access key'),
    (r'xox[baprs]-[A-Za-z0-9-]+', 'Slack token'),
    (r'sk_live_[A-Za-z0-9]{24,}', 'Stripe live key'),

    # Credentials in code
    (r'password\s*[=:]\s*["\'][^"\']{8,}["\']', 'Hardcoded password'),
    (r'secret\s*[=:]\s*["\'][^"\']{8,}["\']', 'Hardcoded secret'),
    (r'api_key\s*[=:]\s*["\'][^"\']{8,}["\']', 'Hardcoded API key'),
    (r'token\s*[=:]\s*["\'][^"\']{16,}["\']', 'Hardcoded token'),

    # Private keys
    (r'-----BEGIN (RSA |DSA |EC |OPENSSH )?PRIVATE KEY-----', 'Private key'),
    (r'-----BEGIN PGP PRIVATE KEY BLOCK-----', 'PGP private key'),

    # Connection strings with credentials
    (r'(mysql|postgresql|mongodb)://[^:]+:[^@]+@', 'Database connection with password'),
    (r'redis://:[^@]+@', 'Redis connection with password'),
]
```

### CI Scanning

Run secret detection on every PR:

```yaml
# Example: GitHub Actions with gitleaks
- name: Scan for secrets
  uses: gitleaks/gitleaks-action@v2
  env:
    GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

### Flow 6 Boundary Scan

Before pushing to upstream, scan the diff:

```bash
# Scan only the changes being pushed
git diff upstream/main...HEAD | grep -E \
  'sk-[A-Za-z0-9]{48}|sk-ant-|ghp_[A-Za-z0-9]{36}|AKIA[A-Z0-9]{16}|-----BEGIN .* PRIVATE KEY-----'
```

**Action on detection:** Block push, require removal.

---

## Exposure Response Protocol

### Step 1: Revoke Immediately

| Provider | Revocation Method |
|----------|-------------------|
| OpenAI | API Keys page in dashboard |
| Anthropic | Console > API Keys |
| GitHub | Settings > Developer settings > Tokens |
| AWS | IAM > Users > Security credentials |

**Do not wait.** Revoke first, assess second.

### Step 2: Rotate Affected Secrets

After revocation, generate new credentials:
1. Create new secret
2. Update all systems using the secret
3. Verify new secret works
4. Delete/disable old secret (if not already)

### Step 3: Audit Access Logs

Check for unauthorized usage during exposure window:

| Service | Log Location |
|---------|--------------|
| OpenAI | Usage dashboard |
| Anthropic | Console > Usage |
| GitHub | Security log |
| AWS | CloudTrail |

Look for:
- Unusual request patterns
- Requests from unexpected IPs
- Elevated permission usage
- Resource creation/deletion

### Step 4: Assess Blast Radius

Document the exposure:
- What secret was exposed?
- How long was it exposed?
- Where was it exposed? (commit, log, etc.)
- What access did it grant?
- What actions were taken with it?
- What data was potentially accessed?

### Step 5: Remediate Source

If secret was in commit history:
```bash
# For recent commits (not yet pushed)
git rebase -i HEAD~N  # Remove the secret

# For pushed commits (requires force push to feature branch)
git filter-branch --force --index-filter \
  'git rm --cached --ignore-unmatch path/to/secret/file' \
  --prune-empty HEAD

# Or use BFG Repo Cleaner (faster)
bfg --delete-files secrets.txt
bfg --replace-text passwords.txt
```

**Warning:** Never force push to protected branches. If secret is in main branch history, consider it permanently exposed.

---

## Flow Studio Specifics

### LLM API Keys

LLM provider keys power the swarm. Handle with care:

```bash
# Set in environment, never in config
export ANTHROPIC_API_KEY="..."
export OPENAI_API_KEY="..."

# Verify keys are not in config
grep -r "sk-ant-\|sk-[A-Za-z0-9]\{48\}" swarm/ .claude/
```

**Never commit:**
- API keys in `.claude/settings.json`
- Keys in flow configs
- Keys in runbook examples

### GitHub Tokens for repo-operator

The `repo-operator` agent needs GitHub access:

```bash
# Use GitHub CLI authentication (preferred)
gh auth login

# Or set token in environment
export GITHUB_TOKEN="ghp_..."
export GH_TOKEN="ghp_..."  # gh CLI also checks this
```

**Required scopes for repo-operator:**
- `repo` (full repository access)
- `workflow` (for CI triggers)
- `read:org` (for org-level operations)

### Secrets in Receipts and Logs

Receipts and logs are audit artifacts. They MUST NOT contain secrets.

**Redaction in logs:**
```python
def redact_secrets(text: str) -> str:
    """Redact known secret patterns from text."""
    patterns = [
        (r'sk-[A-Za-z0-9]{48}', '[REDACTED:OPENAI_KEY]'),
        (r'sk-ant-[A-Za-z0-9-]{95}', '[REDACTED:ANTHROPIC_KEY]'),
        (r'ghp_[A-Za-z0-9]{36}', '[REDACTED:GITHUB_TOKEN]'),
        (r'password=[^\s&]+', 'password=[REDACTED]'),
    ]
    for pattern, replacement in patterns:
        text = re.sub(pattern, replacement, text)
    return text
```

**Apply redaction:**
- Before writing receipts
- Before writing transcripts
- Before logging command output
- Before error messages

### Environment Verification

Before running flows, verify secret hygiene:

```bash
# Check: secrets not in tree
! grep -rE 'sk-[A-Za-z0-9]{48}|sk-ant-|ghp_' --include='*.py' --include='*.yaml' --include='*.json' .

# Check: .env is gitignored
git check-ignore .env  # Should output ".env"

# Check: required secrets are set (not empty)
[ -n "$ANTHROPIC_API_KEY" ] || echo "ANTHROPIC_API_KEY not set"
[ -n "$GITHUB_TOKEN" ] || echo "GITHUB_TOKEN not set"
```

---

## The Rule

> Secrets are toxic waste.
> Store them outside the repository.
> Rotate them before they become liabilities.
> Detect them before they escape.
> Respond to exposure immediately.
> Redact them from all output.

## Enforcement Points

| Check | When | Action |
|-------|------|--------|
| Pre-commit hook | Before commit | Block if pattern matches |
| CI secret scan | On PR | Fail PR if detected |
| Flow 6 boundary | Before push | Block push if detected |
| Receipt generation | Always | Redact before write |
| Log output | Always | Redact before write |

---

## See Also
- [boundary-automation.md](./boundary-automation.md) - Publish gate checks
- [sandbox-and-permissions.md](./sandbox-and-permissions.md) - Containment model
- [git-safety.md](./git-safety.md) - Git operations safety
