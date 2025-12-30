## Output Format Requirements

All station outputs must follow these formatting guidelines:

### Handoff JSON Structure

Every step must produce a handoff file with:

```json
{
  "status": "VERIFIED | UNVERIFIED | PARTIAL | BLOCKED",
  "summary": "Two-paragraph summary of work done",
  "artifacts": {
    "name": "relative/path/to/artifact"
  },
  "can_further_iteration_help": "yes | no",
  "concerns": ["list of issues if UNVERIFIED"],
  "assumptions": ["assumptions made during execution"]
}
```

### Markdown Artifacts

When producing markdown documentation:
- Use clear section headers (##, ###)
- Include code blocks with language tags
- Use tables for structured data
- Keep line length reasonable (< 120 chars)

### Evidence Requirements

- All claims must have supporting evidence
- Test results must include actual output
- Metrics must cite their source
- Quotes must be verbatim from source
