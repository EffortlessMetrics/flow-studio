# Panel Thinking (Anti-Goodhart)

## The Problem

Single metrics get gamed. Optimizing one number leads to perverse incentives.

Examples:
- Optimize test count -> trivial tests
- Optimize coverage % -> tests that execute but don't assert
- Optimize velocity -> technical debt accumulation
- Optimize "green builds" -> flaky test suppression

## The Solution: Panels of Evidence

Never evaluate on a single metric. Use complementary panels that resist gaming.

### Quality Panel

| Metric | Purpose | Gaming Risk |
|--------|---------|-------------|
| Tests passing | Basic correctness | Trivial tests |
| Line coverage | Code exercised | Coverage without assertion |
| Mutation score | Test effectiveness | Slow, expensive |
| Complexity | Maintainability | Over-abstraction |

**Panel insight**: High coverage + low mutation score = weak tests

### Velocity Panel

| Metric | Purpose | Gaming Risk |
|--------|---------|-------------|
| Cycle time | Speed | Cutting corners |
| Throughput | Volume | Small changes only |
| Lead time | End-to-end | Cherry-picking easy work |

**Panel insight**: High throughput + high lead time = batch sizes too large

### Trust Panel (DevLT)

| Metric | Purpose | Gaming Risk |
|--------|---------|-------------|
| Review time | Approval speed | Rubber-stamping |
| Revision count | First-time quality | Perfectionism |
| Evidence coverage | Audit completeness | Checkbox compliance |

**Panel insight**: Fast review + low evidence = insufficient verification

## The Rule

> Evaluate using panels, not single metrics.
> Contradictions within a panel reveal problems.
> Gaming one metric should hurt another in the same panel.

## Application

Gate decisions use panels:
- Don't merge just because "tests pass"
- Check: tests + coverage + complexity + security scan
- Contradictions trigger investigation

Routing decisions use panels:
- Don't advance just because "status == VERIFIED"
- Check: status + evidence count + concern severity
- Missing evidence triggers questions

## The Economics

Panels cost more to evaluate. That's the point.
- Single metric: cheap, gameable
- Panel: expensive, robust

Trade evaluation compute for decision quality.
