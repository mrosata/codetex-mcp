# Benchmarks

Evaluation framework for measuring codetex-mcp's retrieval quality and context efficiency.

## Approaches

### 1. Retrieval Quality (IR Metrics)
Measures whether `SearchEngine.search()` returns the right files/symbols for a given query.

**Metrics:** Precision@k, Recall@k, MRR (Mean Reciprocal Rank), nDCG@k

### 2. Context Efficiency (Token Density)
Measures how many tokens codetex uses vs. naive approaches while preserving equivalent information.

**Metrics:** Compression Ratio, Coverage Score, Token Density

## Running Benchmarks

```bash
# Run all benchmarks
uv run pytest benchmarks/ -m benchmark -v

# Run only retrieval benchmarks
uv run pytest benchmarks/test_retrieval_bench.py -m benchmark -v

# Run only efficiency benchmarks
uv run pytest benchmarks/test_efficiency_bench.py -m benchmark -v
```

## Results

Benchmark results are written as JSON files to `benchmarks/results/`. Each file contains:

- `timestamp`: ISO 8601 timestamp of the run
- `git_sha`: Current git commit SHA
- `approach`: Which benchmark was run
- `metrics`: Aggregated metric values
- `per_query`: Per-query/per-task breakdown

Results files are gitignored — they're local to each development environment.

## Ground Truth Fixtures

Fixtures live in `benchmarks/fixtures/<repo_name>/`:

- `retrieval_queries.json`: Curated (query, expected_files, expected_symbols) tuples
- `efficiency_tasks.json`: Curated (task, relevant_files, relevant_symbols) tuples

### Adding New Test Cases

1. Add entries to the relevant JSON fixture file
2. Each retrieval query needs: `id`, `query`, `expected_files`, `expected_symbols`, `k`
3. Each efficiency task needs: `id`, `task`, `relevant_files`, `relevant_symbols`
4. Run the benchmark to verify your additions produce reasonable metrics

### Adding a New Repository

1. Create `benchmarks/fixtures/<repo_name>/`
2. Add `retrieval_queries.json` and `efficiency_tasks.json`
3. Set `repo_path` to the path where the repo is cloned locally
4. Add a test method in the benchmark runner that loads your fixtures

## Interpreting Results

### Retrieval Metrics
- **Precision@k**: Higher is better. What fraction of top-k results are relevant?
- **Recall@k**: Higher is better. What fraction of relevant items appear in top-k?
- **MRR**: Higher is better. How quickly does the first relevant result appear?
- **nDCG@k**: Higher is better. Are relevant results ranked higher?

### Efficiency Metrics
- **Compression Ratio**: Higher is better. How many times smaller is codetex context vs raw files?
- **Coverage Score**: Higher is better. What fraction of expected concepts appear in context?
- **Token Density**: Higher is better. What fraction of tokens are relevant?

## Metric Library

Pure metric functions live in `src/codetex_mcp/benchmarks/`:

- `metrics.py`: IR metrics (precision, recall, MRR, nDCG)
- `token_metrics.py`: Token efficiency metrics
- `baselines.py`: Naive baseline implementations
- `report.py`: JSON result writer
