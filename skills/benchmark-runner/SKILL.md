---
name: benchmark-runner
description: 'Designs structured benchmarks comparing algorithms, models, or implementations with metrics, test cases, hardware context, and reproduction steps. Triggers on: "benchmark", "compare performance", "which is faster", "latency comparison", "run benchmark", "throughput test", "speed test".'
metadata:
  version: 1.1.1
  category: data
  tags: [benchmarking, performance, comparison, metrics]
  difficulty: intermediate
  phase: verify
---

# Benchmark Runner

Standardizes performance comparison methodology: metric selection, test case design,
environment capture, result formatting, and tradeoff analysis. Produces reproducible
benchmark reports that support informed decisions — not just "A is faster than B" but
"A is faster for small inputs while B scales better."

## Reference Files

| File                                | Contents                                                                                             | Load When                           |
| ----------------------------------- | ---------------------------------------------------------------------------------------------------- | ----------------------------------- |
| `references/metric-selection.md`    | Metric catalog (latency percentiles, throughput, memory, accuracy), selection criteria per task type | Always                              |
| `references/test-case-design.md`    | Representative input selection, scale variation, edge case coverage, warmup strategies               | Always                              |
| `references/environment-capture.md` | Hardware/software context recording, reproducibility requirements, variance control                  | Always                              |
| `references/statistical-rigor.md`   | Sample sizing, variance measurement, significance testing, outlier handling                          | Results need statistical validation |

## Prerequisites

- Clear candidates to compare (at least 2)
- Access to run or observe the candidates (code, API, or existing results)
- Representative workload definition

## Workflow

### Phase 1: Define Scope

1. **What are the candidates?** — Name each candidate precisely, including version.
   "Python dict vs Redis" is too vague. "Python 3.12 dict (in-process) vs Redis 7.2
   (localhost, TCP)" is testable.
2. **What claims need validation?** — "A is faster" → faster at what? For what input
   size? Under what load? Benchmark design flows from the specific claim.
3. **What is the decision context?** — Why does this comparison matter? This determines
   which metrics are most important.

### Phase 2: Select Metrics

Choose metrics that match the decision context:

| Metric Category | Specific Metrics                        | When Important                               |
| --------------- | --------------------------------------- | -------------------------------------------- |
| Latency         | P50, P95, P99, mean, std dev            | User-facing operations, API calls            |
| Throughput      | ops/sec, tokens/sec, MB/sec             | Batch processing, streaming                  |
| Memory          | Peak RSS, avg RSS, allocation rate      | Resource-constrained environments            |
| Accuracy        | F1, BLEU, exact match, precision/recall | ML models, algorithms with quality tradeoffs |
| Cost            | $/1K operations, $/hour, $/GB           | Cloud services, API comparisons              |
| Startup         | Time to first operation, cold start     | Serverless, CLI tools                        |

Select 2-4 metrics. More than 4 makes comparison tables unreadable.

### Phase 3: Design Test Cases

Create a matrix of inputs that reveal performance characteristics:

1. **Scale variation** — Small, medium, large inputs. Performance often changes
   non-linearly with scale.
2. **Representative data** — Use realistic inputs, not synthetic best-case data.
3. **Edge cases** — Empty input, maximum size, adversarial input.
4. **Warmup** — Exclude JIT compilation, cache warming, and connection establishment
   from measurements. Run N warmup iterations before recording.

### Phase 4: Specify Environment

Record everything needed to reproduce the results:

1. **Hardware** — CPU model, core count, RAM size, GPU model (if applicable)
2. **Software** — OS version, language runtime version, dependency versions
3. **Configuration** — Thread count, batch size, connection pool size, cache settings
4. **Isolation** — What else was running? Background processes affect results.

### Phase 5: Structure Results

Produce comparison tables with clear winners per metric, followed by tradeoff analysis.

## Output Format

````text
# Benchmark: {Descriptive Title}

**Date:** {YYYY-MM-DD}
**Hardware:** {CPU}, {RAM}, {GPU if applicable}
**Software:** {runtime versions}
**Configuration:** {key settings that affect results}

## Candidates

| # | Candidate | Version | Configuration |
|---|-----------|---------|---------------|
| A | {name} | {version} | {relevant config} |
| B | {name} | {version} | {relevant config} |

## Test Cases

| # | Name | Input Size | Description | Warmup | Iterations |
|---|------|------------|-------------|--------|------------|
| 1 | Small | {size} | {what it represents} | {N} | {N} |
| 2 | Medium | {size} | {what it represents} | {N} | {N} |
| 3 | Large | {size} | {what it represents} | {N} | {N} |

## Results

### Latency (ms, lower is better)

| Test Case | A (P50 / P95 / P99) | B (P50 / P95 / P99) | Winner |
|-----------|---------------------|---------------------|--------|
| Small | {values} | {values} | {A or B} |
| Medium | {values} | {values} | {A or B} |
| Large | {values} | {values} | {A or B} |

### Memory (MB, lower is better)

| Test Case | A (Peak) | B (Peak) | Winner |
|-----------|----------|----------|--------|
| Small | {value} | {value} | {A or B} |
| Medium | {value} | {value} | {A or B} |
| Large | {value} | {value} | {A or B} |

## Analysis

### Overall Winner
**{Candidate}** wins on {N} of {M} metrics across all test cases.

### Tradeoff Summary
- **Choose A when:** {conditions where A is the better choice}
- **Choose B when:** {conditions where B is the better choice}

### Caveats
- {Limitation of this benchmark}
- {Condition under which results may differ}

## Reproduction

```bash
# Environment setup
{commands to recreate the environment}

# Run benchmark
{commands to execute the benchmark}
````

```text

## Configuring Scope

| Mode | Candidates | Depth | When to Use |
|------|-----------|-------|-------------|
| `quick` | 2 candidates, 1-2 metrics | Single test case, no statistics | Rough comparison, sanity check |
| `standard` | 2-3 candidates, 2-4 metrics | 3 test cases, mean + std dev | Default for most comparisons |
| `rigorous` | Any count, full metric suite | Multiple test cases, percentiles, significance tests | Publication, critical decisions |

## Calibration Rules

1. **Measure, don't guess.** Intuition about performance is unreliable. "Obviously
   faster" is not a benchmark result.
2. **Apples to apples.** Candidates must be compared under identical conditions.
   Different hardware, configuration, or input data invalidates the comparison.
3. **Report variance, not just means.** A mean of 50ms with std dev of 100ms is not
   the same as a mean of 50ms with std dev of 2ms. Always report spread.
4. **Warm up before measuring.** First-run performance includes JIT, cache warming,
   and connection setup. Exclude warmup iterations from results.
5. **Representative inputs only.** Benchmarking with synthetic best-case input is
   misleading. Use data that resembles production workloads.
6. **State the winner per metric, not overall.** "A is better" is lazy. "A has lower
   latency; B uses less memory" is useful.

## Error Handling

| Problem | Resolution |
|---------|------------|
| Cannot run candidates locally | Design the benchmark specification. Document what to measure and how. The user executes separately. |
| Results are noisy (high variance) | Increase iteration count. Check for background processes. Use dedicated hardware or containers for isolation. |
| Candidates serve different purposes | Acknowledge that the comparison is partial. Benchmark only the overlapping functionality. |
| No baseline exists | Establish one candidate as the baseline. Report relative performance (e.g., "B is 1.3x faster than A"). |
| Hardware context unavailable | Document what is known. Note that results may not be reproducible without full context. |

## When NOT to Benchmark

Push back if:
- The comparison is not performance-related (feature comparison → use a decision matrix or ADR instead)
- The candidates are fundamentally different tools (comparing a database to a message queue)
- The user wants to benchmark trivial operations (comparing two string concatenation methods in Python)
- Results from others already exist and conditions match — link to existing benchmarks instead
```
