# Prompt Fragments Library

Reusable prompt fragments for step prompts. Fragments are injected at prompt compilation time using the `{{fragment_name}}` syntax.

## Usage

In any step prompt, reference a fragment:

```markdown
## Git Operations

{{git_safety_rules}}

## Branch Handling

{{branch_protection_rules}}
```

The prompt compiler replaces `{{fragment_name}}` with the contents of `fragments/fragment_name.md`.

## Available Fragments

| Fragment | Purpose | Use When |
|----------|---------|----------|
| `git_safety_rules` | Core git safety invariants | Any step performing git operations |
| `branch_protection_rules` | Protected branch patterns | Branch creation, deletion, or modification |
| `output_schema_header` | Standard output format | All steps (defines receipt structure) |
| `stash_safety` | Stash operation safety | Steps that may stash/unstash changes |
| `conflict_resolution_ladder` | Three-level escalation | Merge conflict handling |
| `testing_patterns` | Standard testing conventions | Test writing steps (test-author, test-critic) |

## Fragment Design Principles

1. **Single Concern**: Each fragment addresses one specific topic
2. **Composable**: Fragments can reference other fragments using `{{other_fragment}}`
3. **Self-Contained**: Each fragment is understandable without external context
4. **Actionable**: Fragments provide concrete guidance, not abstract principles

## Creating New Fragments

1. Create `fragment_name.md` in this directory
2. Follow the naming convention: `lowercase_with_underscores.md`
3. Start with a heading that matches the fragment purpose
4. Include concrete examples and anti-patterns
5. Add the fragment to the table above

## Fragment Composition

Fragments can include other fragments:

```markdown
# Safe Git Workflow

{{git_safety_rules}}

When stashing work:

{{stash_safety}}
```

The compiler resolves these recursively (with cycle detection).

## Compilation

Fragments are resolved by the prompt compiler in `swarm/prompts/compiler.py`. The compilation happens when:

1. A step prompt is loaded for execution
2. The step references fragments with `{{fragment_name}}` or `{{fragment:path/name}}`
3. The compiler substitutes fragment contents inline

### Supported Marker Syntax

- **Simple**: `{{fragment_name}}` or `{{path/to/fragment}}`
- **Explicit**: `{{fragment:path/to/fragment}}` (compatible with spec compiler)

Both syntaxes work identically. The explicit form matches the `swarm/spec/compiler.py` syntax.

## Testing Fragments

### Validate all prompts

```bash
uv run python -m swarm.prompts.compiler validate
```

### List available fragments

```bash
uv run python -m swarm.prompts.compiler list-fragments
```

### Compile a specific prompt

```bash
uv run python -m swarm.prompts.compiler compile --prompt swarm/prompts/agentic_steps/repo-operator.md
```

### Programmatic usage

```python
from swarm.prompts.compiler import compile_prompt, validate_prompt, list_fragments

# Compile a prompt with fragment injection
compiled = compile_prompt("swarm/prompts/agentic_steps/code-implementer.md")

# Validate a prompt for missing fragments
missing = validate_prompt("swarm/prompts/agentic_steps/code-implementer.md")

# List all available fragments
fragments = list_fragments()
```
