# Compression as Value: The Art of Throwing Away

> **Status:** Living document
> **Purpose:** Explain why context compression is a value-creating activity

## The Insight

When `context-loader` or `impact-analyzer` runs, the value isn't in what they produce.

**The value is in what they throw away.**

## The Paradox

Context compression agents:
- Read 50,000 tokens
- Produce 2,000 tokens
- "Lost" 48,000 tokens

But this isn't loss. This is the job.

## Why Compression Creates Value

### Downstream Agents Work Better
- Less noise = clearer signal
- Focused context = focused reasoning
- Relevant information = relevant output

### Token Budget Goes Further
- 2,000 relevant tokens > 50,000 mixed tokens
- Smaller context = cheaper execution
- Faster processing = faster iteration

### Review is Easier
- Compressed summary = faster review
- Key points highlighted = attention directed
- Noise removed = signal amplified

## The Compression Hierarchy

### Raw Input
Everything that could be relevant:
- All files in directory
- All history
- All metadata
- All tangential information

### Curated Input
What's actually relevant:
- Files that matter for this step
- Recent relevant history
- Key metadata
- Core information only

### Compressed Output
What downstream needs to know:
- Summary of findings
- Key decisions made
- Relevant pointers
- Actionable recommendations

## Compression Agents

| Agent | Input (tokens) | Output (tokens) | Compression Ratio |
|-------|----------------|-----------------|-------------------|
| context-loader | 50,000 | 5,000 | 10:1 |
| impact-analyzer | 30,000 | 3,000 | 10:1 |
| cleanup | 20,000 | 2,000 | 10:1 |
| requirements-critic | 15,000 | 1,500 | 10:1 |

The compression ratio IS the value metric.

## What Gets Thrown Away

### Good Compression Removes:
- Irrelevant files
- Tangential details
- Redundant information
- Historical noise
- Boilerplate content

### Good Compression Keeps:
- Directly relevant information
- Key decisions and rationale
- Important constraints
- Actionable next steps
- Evidence pointers

## The Anti-Pattern: Pass-Through

Bad compression:
```
Input: 50,000 tokens
Output: 48,000 tokens
"Summary: Here's everything I read..."
```

This isn't compression. This is pass-through.
No value created. Downstream still drowns in noise.

## The Pattern: Aggressive Compression

Good compression:
```
Input: 50,000 tokens
Output: 2,000 tokens
"Key findings: 3 items
 Relevant files: 5 paths
 Recommendation: specific action
 Evidence: 4 pointers"
```

This is compression. 96% removed. Signal preserved.

## The Curator Mindset

Compression agents are **curators**, not **summarizers**.

### Summarizer (Weak)
"Here's a shorter version of everything"

### Curator (Strong)
"Here's what matters for the next step, and only that"

The difference:
- Summarizer preserves structure
- Curator preserves relevance

## Compression as Filtering

Think of compression as a filter:
- Input: noisy signal
- Filter: relevance to downstream task
- Output: clean signal

The filter criteria:
- Does downstream need this?
- Does this affect the decision?
- Does this provide evidence?
- Does this change the action?

If no to all: throw it away.

## The 90% Rule

Good compression throws away at least 90%.

If you're keeping more than 10%, ask:
- Is everything really relevant?
- Am I being too conservative?
- Am I afraid to lose information?

Fear of information loss = bad compression.

## The Rule

> The best context is the smallest context that works.
> Value is in what's removed, not what's kept.
> If compression ratio is low, compression failed.

## Implications

### For Agent Design
Compression agents should:
- Have clear "what downstream needs" criteria
- Be aggressive about removal
- Measure compression ratio

### For Context Budgets
Budgets should:
- Force compression (can't fit everything)
- Reward relevance (quality over quantity)
- Penalize bloat (downstream suffers)

### For Review
Compressed outputs should:
- Be obviously smaller than inputs
- Contain only relevant information
- Point to sources for depth

## The Economics

Compression costs:
- Tokens to read input
- Tokens to reason about relevance
- Tokens to produce output

Compression saves:
- Tokens for every downstream step
- Time for every downstream review
- Focus for every downstream decision

The math: 1 compression step saves 5-10 downstream steps.

Compression is an investment with compound returns.
