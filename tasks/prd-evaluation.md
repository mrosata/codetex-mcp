# Evaluation Framework PRD

## Overview

codetex-mcp has reached MVP (US-001 through US-020 complete). Before promoting this tool, we need quantitative evidence that it provides value. This PRD defines three evaluation approaches to measure retrieval quality, context efficiency, and task completion impact.

## Problem Statement

We have no metrics to answer:
1. Does `SearchEngine.search()` return the right files/symbols for a given query?
2. Does codetex's tiered context use fewer tokens than naive approaches while preserving equivalent information?
3. Does providing codetex context actually help LLMs complete coding tasks better?

## Approach 1: Retrieval Quality (IR Metrics)

### Goal
Measure whether `SearchEngine.search()` returns the right files and symbols for a given query using standard information retrieval metrics.

### Method
- Curate ground-truth datasets with `(query, expected_files, expected_symbols)` tuples
- Run each query through `SearchEngine.search()`
- Compare retrieved results against ground truth
- Also run a keyword-based grep baseline for comparison

### Metrics
- **Precision@k**: Fraction of top-k results that are relevant
- **Recall@k**: Fraction of relevant items found in top-k results
- **MRR (Mean Reciprocal Rank)**: Average of 1/rank of first relevant result
- **nDCG@k (Normalized Discounted Cumulative Gain)**: Measures ranking quality with position discounting

### Ground Truth
- Dogfood: codetex-mcp's own codebase (~15-20 curated queries)
- Second repo: a well-known OSS Python project (~10-15 queries)

## Approach 2: Context Efficiency (Token Density)

### Goal
Measure how many tokens codetex uses vs. naive approaches to deliver equivalent information.

### Method
- Define tasks with known relevant files and symbols
- Fetch codetex tiered context (overview + file summaries + symbol details)
- Fetch naive baseline context (raw file dumps, grep results)
- Count tokens and measure information density

### Metrics
- **Compression Ratio**: `baseline_tokens / codetex_tokens`
- **Coverage Score**: Fraction of expected symbols/concepts present in the context
- **Token Density**: `relevant_tokens / total_tokens`

### Ground Truth
- Dogfood: codetex-mcp's own codebase (~10-15 curated tasks)
- Second repo: same OSS Python project (~10 tasks)

## Approach 3: Task Completion A/B (FUTURE — NOT READY)

### Goal
Measure whether providing codetex context improves LLM coding task correctness.

### Method (planned)
- Define coding tasks with verifiable correct answers
- Run each task through an LLM twice: once with codetex context, once without
- Score correctness via LLM-as-judge
- Compare success rates

### Why Deferred
- Requires LLM API calls (expensive)
- Needs reliable scoring methodology
- Should only be built after approaches 1+2 establish baselines

## Architecture

### Metrics as Library
Pure functions in `src/codetex_mcp/benchmarks/` — unit-testable, no I/O. Metric calculations are deterministic and well-defined.

### Benchmark Runners as Pytest
Files in `benchmarks/` use a `@pytest.mark.benchmark` marker so they can be run separately from unit tests via `uv run pytest benchmarks/ -m benchmark`.

### Structured Output
Every benchmark run produces a JSON file in `benchmarks/results/` with timestamp, git SHA, and all metric values — enables tracking over time.

### Dogfooding
Benchmarks run against codetex-mcp's own codebase as the primary test repo.

## User Stories

See `prd.json` stories US-021 through US-035 for detailed acceptance criteria.

- US-021–US-025: Approach 1 (Retrieval Quality)
- US-026–US-030: Approach 2 (Context Efficiency)
- US-031–US-032: Shared Infrastructure
- US-033–US-035: Approach 3 (Future — NOT READY)

## Success Criteria

1. All unit tests pass for metric calculations
2. Benchmark runners execute against codetex-mcp's own codebase
3. Results JSON files contain valid timestamp, git SHA, and metric values
4. Existing 504 tests remain unaffected
5. mypy and ruff clean
